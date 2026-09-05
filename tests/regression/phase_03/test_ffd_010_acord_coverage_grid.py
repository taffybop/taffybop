"""FFD-010 structure-preserving ownership for the ACORD coverage grid.

The oracle in this module is deliberately geometric.  The source is a static
vector form (it has no AcroForm fields), so stable ownership must come from the
visible ruled grid and must survive changes to file names and generated IDs.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from math import nan
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import ParseResult
from app.services.ir import ElementRecord
from app.services.serializer import to_markdown
from tests.regression.phase_03.test_p03_us06_acord_form_read_order import (
    _release_payload,
)

GRID_BBOX = (18.0, 288.0, 576.0, 276.0)
ROW_BOUNDARIES = (
    288.0,
    300.0,
    312.0,
    324.0,
    336.0,
    348.0,
    360.0,
    372.0,
    384.0,
    396.0,
    408.0,
    420.0,
    432.0,
    444.0,
    456.0,
    468.0,
    480.0,
    492.0,
    504.0,
    516.0,
    528.0,
    564.0,
)
COLUMN_BOUNDARIES = (
    18.0,
    36.0,
    176.4,
    194.4,
    212.4,
    331.2,
    378.0,
    424.8,
    514.8,
    594.0,
)
CONTROL_ORACLE = {
    (36.0, 312.0, "unchecked"),
    (50.4, 324.0, "unchecked"),
    (115.2, 324.0, "unchecked"),
    (36.0, 336.0, "unchecked"),
    (36.0, 348.0, "unchecked"),
    (36.0, 372.0, "unchecked"),
    (79.2, 372.0, "unchecked"),
    (122.4, 372.0, "unchecked"),
    (36.0, 396.0, "unchecked"),
    (36.0, 408.0, "unchecked"),
    (104.4, 408.0, "unchecked"),
    (36.0, 420.0, "unchecked"),
    (104.4, 420.0, "unchecked"),
    (36.0, 432.0, "unchecked"),
    (104.4, 432.0, "unchecked"),
    (36.0, 444.0, "unchecked"),
    (115.2, 444.0, "unchecked"),
    (36.0, 456.0, "unchecked"),
    (115.2, 456.0, "unchecked"),
    (36.0, 468.0, "unchecked"),
    (72.0, 468.0, "unchecked"),
    (424.8, 480.0, "unchecked"),
    (482.4, 480.0, "unchecked"),
    (158.4, 498.0, "unchecked"),
}

DISCLAIMER_PREFIX = "THIS IS TO CERTIFY THAT THE POLICIES OF INSURANCE"
DESCRIPTION_PREFIX = "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES"

# Repeated labels are counted explicitly instead of being hidden by set based
# assertions.  In particular OCCUR is source-visible twice and every currency
# value slot prints its own dollar marker.
VISIBLE_GRID_TEXT_COUNTS = {
    "INSR LTR": 1,
    "TYPE OF INSURANCE": 1,
    "ADDL INSR": 1,
    "SUBR WVD": 1,
    "POLICY NUMBER": 1,
    "POLICY EFF (MM/DD/YYYY)": 1,
    "POLICY EXP (MM/DD/YYYY)": 1,
    "COMMERCIAL GENERAL LIABILITY": 1,
    "CLAIMS-MADE": 2,
    "GEN'L AGGREGATE LIMIT APPLIES PER:": 1,
    "PROJECT": 1,
    "LOC": 1,
    "AUTOMOBILE LIABILITY": 1,
    "ANY AUTO": 1,
    "ALL OWNED AUTOS": 1,
    "SCHEDULED AUTOS": 1,
    "HIRED AUTOS": 1,
    "NON-OWNED AUTOS": 1,
    "UMBRELLA LIAB": 1,
    "EXCESS LIAB": 1,
    "DED": 1,
    "RETENTION $": 1,
    "WORKERS COMPENSATION AND EMPLOYERS' LIABILITY": 1,
    "Y / N": 1,
    "N / A": 1,
    "WC STATUTORY LIMITS": 1,
    "OTHER": 1,
    "EACH OCCURRENCE": 2,
    "DAMAGE TO RENTED PREMISES (Ea occurrence)": 1,
    "MED EXP (Any one person)": 1,
    "PERSONAL & ADV INJURY": 1,
    "GENERAL AGGREGATE": 1,
    "PRODUCTS - COMP/OP AGG": 1,
    "COMBINED SINGLE LIMIT (Ea accident)": 1,
    "BODILY INJURY (Per person)": 1,
    "BODILY INJURY (Per accident)": 1,
    "PROPERTY DAMAGE (Per accident)": 1,
    "E.L. EACH ACCIDENT": 1,
    "E.L. DISEASE - EA EMPLOYEE": 1,
    "E.L. DISEASE - POLICY LIMIT": 1,
}


def _bbox_tuple(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def _grid_overlap_ratio(value: Mapping[str, Any]) -> float:
    x, y, width, height = _bbox_tuple(value)
    grid_x, grid_y, grid_width, grid_height = GRID_BBOX
    overlap_width = max(
        0.0,
        min(x + width, grid_x + grid_width) - max(x, grid_x),
    )
    overlap_height = max(
        0.0,
        min(y + height, grid_y + grid_height) - max(y, grid_y),
    )
    return overlap_width * overlap_height / (grid_width * grid_height)


def _coverage_owner(payload: Mapping[str, Any]) -> dict[str, Any]:
    owners = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("form_group"), Mapping)
        and isinstance(item["form_group"].get("form_grid"), Mapping)
    ]
    assert len(owners) == 1
    return owners[0]


def _canonical_block(
    payload: Mapping[str, Any],
    *,
    primary_element_id: str,
) -> Mapping[str, Any]:
    matches = [
        block
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["primary_element_id"] == primary_element_id
    ]
    assert len(matches) == 1
    return matches[0]


def _normalized_source_text(value: object) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(without_tags).replace("-\n", "").split())


def _visible_phrase_count(value: str, phrase: str) -> int:
    return len(
        re.findall(
            rf"(?<!\w){re.escape(phrase)}(?!\w)",
            value,
        )
    )


def _assert_confidence_dimensions(value: object) -> None:
    assert isinstance(value, Mapping)
    assert set(value) == {"geometry", "role", "transcription", "state"}
    for dimension in value.values():
        assert isinstance(dimension, Mapping)
        assert set(dimension) in ({"score"}, {"unavailable_reason"})
        if "score" in dimension:
            assert type(dimension["score"]) in (int, float)
            assert 0.0 <= float(dimension["score"]) <= 1.0
        else:
            assert isinstance(dimension["unavailable_reason"], str)
            assert dimension["unavailable_reason"]


def _assert_complete_nonoverlapping_grid(grid: Mapping[str, Any]) -> None:
    rows = tuple(float(value) for value in grid["row_boundaries"])
    columns = tuple(float(value) for value in grid["column_boundaries"])
    cells = grid["cells"]
    assert isinstance(cells, Sequence) and not isinstance(cells, (str, bytes))
    assert rows == ROW_BOUNDARIES
    assert columns == COLUMN_BOUNDARIES

    occupied: dict[tuple[int, int], Mapping[str, Any]] = {}
    prior_position = (-1, -1)
    for reading_order, cell in enumerate(cells):
        assert isinstance(cell, Mapping)
        assert cell["reading_order"] == reading_order
        row = cell["row"]
        column = cell["column"]
        row_span = cell["row_span"]
        column_span = cell["column_span"]
        assert all(type(value) is int for value in (row, column, row_span, column_span))
        assert row_span >= 1 and column_span >= 1
        assert (row, column) > prior_position
        prior_position = (row, column)
        assert 0 <= row < len(rows) - 1
        assert 0 <= column < len(columns) - 1
        assert row + row_span <= len(rows) - 1
        assert column + column_span <= len(columns) - 1
        assert _bbox_tuple(cell["bbox"]) == pytest.approx(
            (
                columns[column],
                rows[row],
                columns[column + column_span] - columns[column],
                rows[row + row_span] - rows[row],
            ),
            abs=0.01,
        )
        for atomic_row in range(row, row + row_span):
            for atomic_column in range(column, column + column_span):
                position = (atomic_row, atomic_column)
                assert position not in occupied
                occupied[position] = cell
        assert cell["text_state"] in {"present", "empty"}
        if cell["text_state"] == "empty":
            assert cell["text"] is None
        else:
            assert isinstance(cell["text"], str) and cell["text"].strip()
        assert cell["value_state"] in {
            "present",
            "empty",
            "ambiguous",
            "not_applicable",
        }
        if cell["value_state"] == "present":
            assert isinstance(cell["value"], str) and cell["value"].strip()
        else:
            assert cell["value"] is None
        assert cell["cell_role"] in {"static", "value"}
        if cell["cell_role"] == "static":
            assert cell["value_state"] == "not_applicable"
            assert cell["static_kind"] in {
                "column_header",
                "row_header",
                "section_header",
                "qualifier",
            }
        else:
            assert cell["value_state"] != "not_applicable"
            assert cell["static_kind"] is None
        assert isinstance(cell["control_ids"], list)
        assert len(cell["control_ids"]) == len(set(cell["control_ids"]))
        assert cell["source_objects"]
        fragments = cell["content_fragments"]
        assert isinstance(fragments, list)
        assert [fragment["source_order"] for fragment in fragments] == list(
            range(len(fragments))
        )
        assert [
            fragment["control_id"]
            for fragment in fragments
            if fragment["kind"] == "control"
        ] == cell["control_ids"]
        assert (
            "\n".join(
                fragment["text"] for fragment in fragments if fragment["kind"] == "text"
            )
            or None
        ) == cell["text"]
        cell_x, cell_y, cell_width, cell_height = _bbox_tuple(cell["bbox"])
        cell_sources = {
            tuple(sorted(source.items())) for source in cell["source_objects"]
        }
        for fragment in fragments:
            assert fragment["kind"] in {"text", "control"}
            fragment_x, fragment_y, fragment_width, fragment_height = _bbox_tuple(
                fragment["bbox"]
            )
            assert fragment_x >= cell_x - 1.0
            assert fragment_y >= cell_y - 1.0
            assert fragment_x + fragment_width <= cell_x + cell_width + 1.0
            assert fragment_y + fragment_height <= cell_y + cell_height + 1.0
            assert {
                tuple(sorted(source.items())) for source in fragment["source_objects"]
            } <= cell_sources
            if fragment["kind"] == "text":
                assert isinstance(fragment["text"], str) and fragment["text"].strip()
                assert fragment.get("control_id") is None
            else:
                assert isinstance(fragment["control_id"], str)
                assert fragment["control_id"].strip()
                assert fragment.get("text") is None
        _assert_confidence_dimensions(cell["confidence_dimensions"])
        assert isinstance(cell["concern_codes"], list)
        assert len(cell["concern_codes"]) == len(set(cell["concern_codes"]))

        headers = [
            candidate["reading_order"]
            for candidate in cells
            if cell["static_kind"] != "column_header"
            and candidate["cell_role"] == "static"
            and candidate["static_kind"] == "column_header"
            and candidate["text_state"] == "present"
            and candidate["row"] == 0
            and max(candidate["column"], cell["column"])
            < min(
                candidate["column"] + candidate["column_span"],
                cell["column"] + cell["column_span"],
            )
        ]
        sections = [
            candidate["reading_order"]
            for candidate in cells
            if cell["cell_role"] == "value"
            and candidate["cell_role"] == "static"
            and candidate["static_kind"] == "section_header"
            and candidate["text_state"] == "present"
            and candidate["row"]
            <= cell["row"]
            < candidate["row"] + candidate["row_span"]
        ]
        labels = [
            candidate["reading_order"]
            for candidate in cells
            if cell["cell_role"] == "value"
            and candidate["cell_role"] == "static"
            and candidate["static_kind"] == "row_header"
            and candidate["text_state"] == "present"
            and candidate["row"] != 0
            and cell["row_span"] == 1
            and candidate["row"] == cell["row"]
            and candidate["row_span"] == 1
            and candidate["column"] + candidate["column_span"] == cell["column"]
        ]
        assert cell["header_cell_orders"] == headers
        assert cell["section_cell_orders"] == sections
        assert cell["label_cell_orders"] == labels

    assert set(occupied) == {
        (row, column)
        for row in range(len(rows) - 1)
        for column in range(len(columns) - 1)
    }
    assert any(cell["row_span"] > 1 for cell in cells)
    assert any(cell["column_span"] > 1 for cell in cells)


def _confidence(*, transcription: bool) -> dict[str, dict[str, float | str]]:
    return {
        "geometry": {"score": 1.0},
        "role": {"score": 1.0},
        "transcription": (
            {"score": 1.0}
            if transcription
            else {"unavailable_reason": "transcription_not_applicable"}
        ),
        "state": {"score": 1.0},
    }


def _content_fragments(
    *,
    text: str | None,
    control_ids: Sequence[str],
    bbox: Mapping[str, Any],
    source_objects: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    if text is not None:
        fragments.append(
            {
                "source_order": len(fragments),
                "kind": "text",
                "bbox": deepcopy(dict(bbox)),
                "text": text,
                "source_objects": deepcopy(list(source_objects)),
            }
        )
    for control_id in control_ids:
        fragments.append(
            {
                "source_order": len(fragments),
                "kind": "control",
                "bbox": deepcopy(dict(bbox)),
                "control_id": control_id,
                "source_objects": deepcopy(list(source_objects)),
            }
        )
    return fragments


def _synthetic_grid(
    *,
    filled: bool,
    left: float = 20.0,
    top: float = 40.0,
    scale: float = 1.0,
    renamed: bool = False,
) -> dict[str, Any]:
    """Build a small complete form grid with both row and column spans."""

    column_offsets = (0.0, 24.0, 124.0, 164.0, 244.0)
    row_offsets = (0.0, 18.0, 36.0, 60.0, 84.0)
    columns = [left + scale * value for value in column_offsets]
    rows = [top + scale * value for value in row_offsets]

    labels = (
        ("RISK COVERAGE MATRIX", "SYNTHETIC GRID ALPHA"),
        ("CLASS", "GROUP"),
        ("POLICY REFERENCE", "IDENTIFIER"),
        ("SELECT", "CONTROL"),
        ("LIMIT", "CAP"),
        ("PRIMARY", "FIRST"),
    )
    text = {
        original: replacement if renamed else original
        for original, replacement in labels
    }
    specifications: list[
        tuple[int, int, int, int, str | None, str | None, str, list[str]]
    ] = [
        (0, 0, 1, 4, text["RISK COVERAGE MATRIX"], None, "not_applicable", []),
        (1, 0, 1, 1, text["CLASS"], None, "not_applicable", []),
        (1, 1, 1, 1, text["POLICY REFERENCE"], None, "not_applicable", []),
        (1, 2, 1, 1, text["SELECT"], None, "not_applicable", []),
        (1, 3, 1, 1, text["LIMIT"], None, "not_applicable", []),
        (2, 0, 2, 1, text["PRIMARY"], None, "not_applicable", []),
        (
            2,
            1,
            1,
            1,
            None,
            "PX-9931" if filled else None,
            "present" if filled else "empty",
            [],
        ),
        (2, 2, 1, 1, None, None, "empty", ["synthetic-control-unchecked"]),
        (
            2,
            3,
            1,
            1,
            None,
            "1000000" if filled else None,
            "present" if filled else "empty",
            [],
        ),
        (
            3,
            1,
            1,
            1,
            None,
            "PX-9932" if filled else None,
            "present" if filled else "empty",
            [],
        ),
        (3, 2, 1, 1, None, None, "empty", ["synthetic-control-ambiguous"]),
        (
            3,
            3,
            1,
            1,
            None,
            "2000000" if filled else None,
            "present" if filled else "empty",
            [],
        ),
    ]
    cells = []
    for index, (
        row,
        column,
        row_span,
        column_span,
        cell_text,
        value,
        value_state,
        control_ids,
    ) in enumerate(specifications):
        bbox = {
            "x": columns[column],
            "y": rows[row],
            "width": columns[column + column_span] - columns[column],
            "height": rows[row + row_span] - rows[row],
            "unit": "pt",
        }
        source_objects = [{"kind": "line", "index": index}]
        cells.append(
            {
                "reading_order": index,
                "row": row,
                "column": column,
                "row_span": row_span,
                "column_span": column_span,
                "bbox": bbox,
                "cell_role": ("static" if value_state == "not_applicable" else "value"),
                "static_kind": (
                    "column_header"
                    if value_state == "not_applicable" and row == 0
                    else "section_header"
                    if value_state == "not_applicable" and row_span > 1
                    else "row_header"
                    if value_state == "not_applicable"
                    else None
                ),
                "text": cell_text,
                "text_state": "present" if cell_text is not None else "empty",
                "value": value,
                "value_state": value_state,
                "control_ids": control_ids,
                "content_fragments": _content_fragments(
                    text=cell_text,
                    control_ids=control_ids,
                    bbox=bbox,
                    source_objects=source_objects,
                ),
                "header_cell_orders": [],
                "section_cell_orders": [],
                "label_cell_orders": [],
                "source_objects": source_objects,
                "confidence_dimensions": _confidence(
                    transcription=cell_text is not None or value is not None
                ),
                "concern_codes": [],
            }
        )
    header_cells = [
        cell
        for cell in cells
        if cell["cell_role"] == "static"
        and cell["static_kind"] == "column_header"
        and cell["text_state"] == "present"
        and cell["row"] == 0
    ]
    static_labels = [
        cell
        for cell in cells
        if cell["cell_role"] == "static"
        and cell["static_kind"] == "row_header"
        and cell["text_state"] == "present"
        and cell["row"] != 0
    ]
    section_headers = [
        cell
        for cell in cells
        if cell["cell_role"] == "static"
        and cell["static_kind"] == "section_header"
        and cell["text_state"] == "present"
    ]
    for cell in cells:
        if cell["static_kind"] != "column_header":
            cell["header_cell_orders"] = [
                candidate["reading_order"]
                for candidate in header_cells
                if max(candidate["column"], cell["column"])
                < min(
                    candidate["column"] + candidate["column_span"],
                    cell["column"] + cell["column_span"],
                )
            ]
        if cell["cell_role"] != "value":
            continue
        cell["section_cell_orders"] = [
            candidate["reading_order"]
            for candidate in section_headers
            if candidate["row"]
            <= cell["row"]
            < candidate["row"] + candidate["row_span"]
        ]
        cell["label_cell_orders"] = [
            candidate["reading_order"]
            for candidate in static_labels
            if cell["row_span"] == 1
            and candidate["row"] == cell["row"]
            and candidate["row_span"] == 1
            and candidate["column"] + candidate["column_span"] == cell["column"]
        ]
    return {
        "bbox": {
            "x": columns[0],
            "y": rows[0],
            "width": columns[-1] - columns[0],
            "height": rows[-1] - rows[0],
            "unit": "pt",
        },
        "row_boundaries": rows,
        "column_boundaries": columns,
        "cells": cells,
    }


def _adjacent_label_grid() -> dict[str, Any]:
    """Build a minimal grid that distinguishes adjacency from any-left linking."""

    rows = [0.0, 12.0, 24.0]
    columns = [0.0, 20.0, 40.0, 60.0, 80.0]
    specifications = (
        (0, 0, 1, 4, "POLICY DATA", "static", "column_header", [], []),
        (1, 0, 1, 1, "POLICY NUMBER", "static", "row_header", [0], []),
        (1, 1, 1, 1, None, "value", None, [0], [1]),
        (1, 2, 1, 1, None, "value", None, [0], []),
        (1, 3, 1, 1, None, "value", None, [0], []),
    )
    cells = []
    for reading_order, (
        row,
        column,
        row_span,
        column_span,
        text_value,
        role,
        static_kind,
        header_orders,
        label_orders,
    ) in enumerate(specifications):
        bbox = {
            "x": columns[column],
            "y": rows[row],
            "width": columns[column + column_span] - columns[column],
            "height": rows[row + row_span] - rows[row],
            "unit": "pt",
        }
        source_objects = [{"kind": "line", "index": reading_order}]
        cells.append(
            {
                "reading_order": reading_order,
                "row": row,
                "column": column,
                "row_span": row_span,
                "column_span": column_span,
                "bbox": bbox,
                "cell_role": role,
                "static_kind": static_kind,
                "text": text_value,
                "text_state": "present" if text_value is not None else "empty",
                "value": None,
                "value_state": "not_applicable" if role == "static" else "empty",
                "control_ids": [],
                "content_fragments": _content_fragments(
                    text=text_value,
                    control_ids=(),
                    bbox=bbox,
                    source_objects=source_objects,
                ),
                "header_cell_orders": header_orders,
                "section_cell_orders": [],
                "label_cell_orders": label_orders,
                "source_objects": source_objects,
                "confidence_dimensions": _confidence(
                    transcription=text_value is not None
                ),
                "concern_codes": [],
            }
        )
    return {
        "bbox": {
            "x": columns[0],
            "y": rows[0],
            "width": columns[-1] - columns[0],
            "height": rows[-1] - rows[0],
            "unit": "pt",
        },
        "row_boundaries": rows,
        "column_boundaries": columns,
        "cells": cells,
    }


def _synthetic_ruled_source(
    *,
    filled: bool,
    left: float = 20.0,
    top: float = 40.0,
    scale: float = 1.0,
    renamed: bool = False,
    merged_policy_value: bool = False,
    vertically_merged_policy_value: bool = False,
    policy_value: str | None = None,
    mixed_amount_column: bool = False,
    control_glyph: str | None = None,
    control_label: str | None = None,
) -> tuple[Any, tuple[float, float, float, float], tuple[Any, ...]]:
    """Create source primitives for a closed grid with two merged cells."""

    from app.services.form_semantics import (
        FormSourcePage,
        SourceChar,
        SourceVector,
        SourceWord,
        _DetectedControl,
    )

    column_offsets = (0.0, 24.0, 124.0, 164.0, 244.0)
    row_offsets = (0.0, 18.0, 36.0, 60.0, 84.0)
    columns = tuple(left + scale * value for value in column_offsets)
    rows = tuple(top + scale * value for value in row_offsets)
    vectors = []

    def line(x0: float, y0: float, x1: float, y1: float) -> None:
        vectors.append(
            SourceVector(
                kind="line",
                index=len(vectors),
                x0=x0,
                top=y0,
                x1=x1,
                bottom=y1,
                fill=False,
            )
        )

    # The last two header columns merge, and the first data cell spans the
    # final two rows. The detector must infer both from the absent separators.
    for row_index, y in enumerate(rows):
        start = (
            columns[2]
            if row_index == 3 and vertically_merged_policy_value
            else columns[1]
            if row_index == 3
            else columns[0]
        )
        line(start, y, columns[-1], y)
    for column_index, x in enumerate(columns):
        start = rows[1] if column_index == 3 else rows[0]
        if merged_policy_value and column_index == 2:
            line(x, start, x, rows[2])
            line(x, rows[3], x, rows[-1])
        else:
            line(x, start, x, rows[-1])

    checkbox_row = 3 if merged_policy_value else 2
    checkbox_bbox = (
        columns[2] + 3.0 * scale,
        rows[checkbox_row] + 3.0 * scale,
        8.0 * scale,
        8.0 * scale,
    )
    checkbox_index = len(vectors)
    vectors.append(
        SourceVector(
            kind="rect",
            index=checkbox_index,
            x0=checkbox_bbox[0],
            top=checkbox_bbox[1],
            x1=checkbox_bbox[0] + checkbox_bbox[2],
            bottom=checkbox_bbox[1] + checkbox_bbox[3],
            fill=False,
        )
    )

    source_text = {
        (0, 0): "ALPHA" if renamed else "HEADER A",
        (0, 1): "BETA" if renamed else "HEADER B",
        (0, 2): "GAMMA" if renamed else "HEADER C",
        (1, 0): "FAMILY" if renamed else "CLASS",
        (2, 0): "FIRST" if renamed else "PRIMARY",
    }
    if mixed_amount_column:
        source_text[(1, 1)] = "AMOUNT"
        source_text[(1, 2)] = "$"
    if filled:
        source_text[(2, 1)] = (
            policy_value
            if policy_value is not None
            else "RENAMED-9931"
            if renamed
            else "PX-9931"
        )
        source_text[(3, 3)] = "7654321" if renamed else "1000000"
    words = []
    chars = []
    char_cursor = 0
    for (row, column), value in sorted(source_text.items()):
        word_left = columns[column] + 2.0 * scale
        word_top = rows[row] + 3.0 * scale
        text_column_span = (
            2
            if (row, column) == (0, 2)
            or (merged_policy_value and (row, column) == (2, 1))
            else 1
        )
        text_right = columns[column + text_column_span] - 2.0 * scale
        char_advance = min(
            3.5 * scale,
            (text_right - word_left) / max(1, len(value)),
        )
        words.append(
            SourceWord(
                index=len(words),
                text=value,
                x0=word_left,
                top=word_top,
                x1=min(
                    text_right,
                    word_left + max(4.0, len(value) * 3.5) * scale,
                ),
                bottom=word_top + 7.0 * scale,
                font_name="Helvetica",
                size=7.0 * scale,
                char_start=char_cursor,
                char_end=char_cursor + len(value),
            )
        )
        for offset, character in enumerate(value):
            char_left = word_left + offset * char_advance
            chars.append(
                SourceChar(
                    index=char_cursor + offset,
                    text=character,
                    x0=char_left,
                    top=word_top,
                    x1=char_left + 0.85 * char_advance,
                    bottom=word_top + 7.0 * scale,
                    font_name="Helvetica",
                    size=7.0 * scale,
                )
            )
        char_cursor += len(value)

    if control_glyph is not None:
        glyph_left = checkbox_bbox[0] + 2.0 * scale
        glyph_top = checkbox_bbox[1] + 1.5 * scale
        glyph_advance = min(3.0 * scale, checkbox_bbox[2] / len(control_glyph))
        words.append(
            SourceWord(
                index=len(words),
                text=control_glyph,
                x0=glyph_left,
                top=glyph_top,
                x1=glyph_left + glyph_advance * len(control_glyph),
                bottom=glyph_top + 5.0 * scale,
                font_name="Helvetica",
                size=6.0 * scale,
                char_start=char_cursor,
                char_end=char_cursor + len(control_glyph),
            )
        )
        for offset, character in enumerate(control_glyph):
            char_left = glyph_left + offset * glyph_advance
            chars.append(
                SourceChar(
                    index=char_cursor + offset,
                    text=character,
                    x0=char_left,
                    top=glyph_top,
                    x1=char_left + 0.85 * glyph_advance,
                    bottom=glyph_top + 5.0 * scale,
                    font_name="Helvetica",
                    size=6.0 * scale,
                )
            )
        char_cursor += len(control_glyph)

    if control_label is not None:
        label_left = checkbox_bbox[0] + checkbox_bbox[2] + 6.0 * scale
        label_top = checkbox_bbox[1] + 1.0 * scale
        label_right = columns[3] - 2.0 * scale
        label_advance = min(
            3.5 * scale,
            (label_right - label_left) / max(1, len(control_label)),
        )
        words.append(
            SourceWord(
                index=len(words),
                text=control_label,
                x0=label_left,
                top=label_top,
                x1=min(
                    label_right,
                    label_left + label_advance * len(control_label),
                ),
                bottom=label_top + 6.0 * scale,
                font_name="Helvetica",
                size=6.0 * scale,
                char_start=char_cursor,
                char_end=char_cursor + len(control_label),
            )
        )
        for offset, character in enumerate(control_label):
            char_left = label_left + offset * label_advance
            chars.append(
                SourceChar(
                    index=char_cursor + offset,
                    text=character,
                    x0=char_left,
                    top=label_top,
                    x1=char_left + 0.85 * label_advance,
                    bottom=label_top + 6.0 * scale,
                    font_name="Helvetica",
                    size=6.0 * scale,
                )
            )
        char_cursor += len(control_label)

    page = FormSourcePage(
        page_index=1,
        width=left + 300.0 * scale,
        height=top + 160.0 * scale,
        chars=tuple(chars),
        words=tuple(words),
        vectors=tuple(vectors),
        annotations=(),
        interactivity="static",
    )
    control = _DetectedControl(
        key="renamed-choice" if renamed else "synthetic-choice",
        group_key="renamed-grid" if renamed else "synthetic-grid",
        bbox=checkbox_bbox,
        label_key=None,
        source_objects=(("rect", checkbox_index, None),),
        state="unchecked",
    )
    candidate_bbox = (
        columns[0],
        rows[0],
        columns[-1] - columns[0],
        rows[-1] - rows[0],
    )
    return page, candidate_bbox, (control,)


def _validate_grid(payload: Mapping[str, Any]) -> Any:
    # Local import keeps this regression collectable while the FFD-010 public
    # model lands in the same change set.
    from app.services.form_semantics import PublicFormGrid

    return PublicFormGrid.model_validate(payload, strict=True)


def _render_mutated_owner(owner: Mapping[str, Any]) -> Any:
    from app.services.form_semantics import render_form_group_semantics

    group = owner["form_group"]
    anchor = ElementRecord(
        id=group["anchor_element_id"],
        page_id=f"page-{group['page_index']}",
        type=str(owner["type"]),
        properties={"legacy_item": deepcopy(dict(owner))},
    )
    rendering = render_form_group_semantics(anchor)
    assert rendering is not None
    return rendering


def test_public_form_grid_contract_caps_anchor_cells_at_page_shape_limit() -> None:
    from app.services.form_semantics import PublicFormGrid

    cell_schema = PublicFormGrid.model_json_schema()["properties"]["cells"]
    assert cell_schema["minItems"] == 4
    assert cell_schema["maxItems"] == 4_096


@pytest.mark.parametrize(
    ("filled", "expected_present_values"),
    ((False, ()), (True, ("PX-9931", "1000000", "PX-9932", "2000000"))),
)
def test_synthetic_blank_and_filled_grids_validate_without_losing_topology(
    filled: bool,
    expected_present_values: tuple[str, ...],
) -> None:
    grid = _validate_grid(_synthetic_grid(filled=filled))
    payload = grid.model_dump(mode="json")

    assert payload["row_boundaries"] == [40.0, 58.0, 76.0, 100.0, 124.0]
    assert payload["column_boundaries"] == [20.0, 44.0, 144.0, 184.0, 264.0]
    assert [
        cell["value"]
        for cell in payload["cells"]
        if cell["value"] in expected_present_values
    ] == list(expected_present_values)
    empty = [cell for cell in payload["cells"] if cell["value_state"] == "empty"]
    assert all(cell["value"] is None for cell in empty)
    assert len(empty) == (6 if not filled else 2)
    assert any(cell["row_span"] == 2 for cell in payload["cells"])
    assert any(cell["column_span"] == 4 for cell in payload["cells"])


def test_synthetic_grid_is_coordinate_and_vocabulary_independent() -> None:
    baseline = _validate_grid(_synthetic_grid(filled=True)).model_dump(mode="json")
    transformed = _validate_grid(
        _synthetic_grid(
            filled=True,
            left=73.25,
            top=119.5,
            scale=1.375,
            renamed=True,
        )
    ).model_dump(mode="json")

    assert [
        (cell["row"], cell["column"], cell["row_span"], cell["column_span"])
        for cell in transformed["cells"]
    ] == [
        (cell["row"], cell["column"], cell["row_span"], cell["column_span"])
        for cell in baseline["cells"]
    ]
    assert transformed["bbox"] == {
        "x": 73.25,
        "y": 119.5,
        "width": pytest.approx(335.5),
        "height": pytest.approx(115.5),
        "unit": "pt",
    }
    transformed_text = "\n".join(
        str(cell["text"] or cell["value"] or "") for cell in transformed["cells"]
    )
    assert "SYNTHETIC GRID ALPHA" in transformed_text
    assert "RISK COVERAGE MATRIX" not in transformed_text


@pytest.mark.parametrize(
    ("filled", "left", "top", "scale", "renamed"),
    (
        (False, 20.0, 40.0, 1.0, False),
        (True, 20.0, 40.0, 1.0, False),
        (False, 73.25, 119.5, 1.375, True),
        (True, 73.25, 119.5, 1.375, True),
    ),
)
def test_source_ruled_grid_detection_survives_blank_filled_moved_scaled_variants(
    filled: bool,
    left: float,
    top: float,
    scale: float,
    renamed: bool,
) -> None:
    from app.services.form_semantics import _build_ruled_form_grid

    page, candidate_bbox, controls = _synthetic_ruled_source(
        filled=filled,
        left=left,
        top=top,
        scale=scale,
        renamed=renamed,
    )

    grid = _build_ruled_form_grid(page, candidate_bbox, controls, ())

    assert grid is not None
    assert grid.bbox == pytest.approx(candidate_bbox, abs=0.01)
    assert [
        (cell.row, cell.column, cell.row_span, cell.column_span) for cell in grid.cells
    ] == [
        (0, 0, 1, 1),
        (0, 1, 1, 1),
        (0, 2, 1, 2),
        (1, 0, 1, 1),
        (1, 1, 1, 1),
        (1, 2, 1, 1),
        (1, 3, 1, 1),
        (2, 0, 2, 1),
        (2, 1, 1, 1),
        (2, 2, 1, 1),
        (2, 3, 1, 1),
        (3, 1, 1, 1),
        (3, 2, 1, 1),
        (3, 3, 1, 1),
    ]
    values = [cell.value for cell in grid.cells if cell.value_state == "present"]
    unproven_classification = "FAMILY" if renamed else "CLASS"
    assert values == [
        unproven_classification,
        *(
            ["RENAMED-9931", "7654321"]
            if renamed and filled
            else ["PX-9931", "1000000"]
            if filled
            else []
        ),
    ]
    class_cell = next(cell for cell in grid.cells if (cell.row, cell.column) == (1, 0))
    assert class_cell.cell_role == "value"
    assert class_cell.static_kind is None
    assert class_cell.value == unproven_classification
    assert [
        control_key for cell in grid.cells for control_key in cell.control_keys
    ] == [controls[0].key]
    header_cells = [
        cell
        for cell in grid.cells
        if cell.cell_role == "static"
        and cell.static_kind == "column_header"
        and cell.text_state == "present"
        and cell.row == 0
    ]
    static_labels = [
        cell
        for cell in grid.cells
        if cell.cell_role == "static"
        and cell.static_kind == "row_header"
        and cell.text_state == "present"
        and cell.row != 0
    ]
    section_headers = [
        cell
        for cell in grid.cells
        if cell.cell_role == "static"
        and cell.static_kind == "section_header"
        and cell.text_state == "present"
    ]
    for cell in grid.cells:
        if cell.cell_role == "static":
            assert cell.static_kind in {
                "column_header",
                "row_header",
                "section_header",
                "qualifier",
            }
            assert cell.header_cell_orders == tuple(
                candidate.reading_order
                for candidate in header_cells
                if cell.static_kind != "column_header"
                and max(candidate.column, cell.column)
                < min(
                    candidate.column + candidate.column_span,
                    cell.column + cell.column_span,
                )
            )
            assert cell.section_cell_orders == ()
            assert cell.label_cell_orders == ()
            continue
        assert cell.static_kind is None
        assert cell.header_cell_orders == tuple(
            candidate.reading_order
            for candidate in header_cells
            if max(candidate.column, cell.column)
            < min(
                candidate.column + candidate.column_span,
                cell.column + cell.column_span,
            )
        )
        assert cell.section_cell_orders == tuple(
            candidate.reading_order
            for candidate in section_headers
            if candidate.row <= cell.row < candidate.row + candidate.row_span
        )
        assert cell.label_cell_orders == tuple(
            candidate.reading_order
            for candidate in static_labels
            if cell.row_span == 1
            and candidate.row == cell.row
            and candidate.row_span == 1
            and candidate.column + candidate.column_span == cell.column
        )


def test_source_ruled_filled_merged_policy_cell_remains_a_present_value() -> None:
    from app.services.form_semantics import _build_ruled_form_grid

    page, candidate_bbox, controls = _synthetic_ruled_source(
        filled=True,
        merged_policy_value=True,
    )

    grid = _build_ruled_form_grid(page, candidate_bbox, controls, ())

    assert grid is not None
    policy_cells = [cell for cell in grid.cells if (cell.row, cell.column) == (2, 1)]
    assert len(policy_cells) == 1
    policy_cell = policy_cells[0]
    assert (policy_cell.row_span, policy_cell.column_span) == (1, 2)
    assert policy_cell.cell_role == "value"
    assert policy_cell.static_kind is None
    assert policy_cell.text == "PX-9931"
    assert policy_cell.text_state == "present"
    assert policy_cell.value == "PX-9931"
    assert policy_cell.value_state == "present"
    assert policy_cell.control_keys == ()


def test_source_ruled_entered123_rowspan_adjacent_to_control_remains_a_value() -> None:
    from app.services.form_semantics import _build_ruled_form_grid

    page, candidate_bbox, controls = _synthetic_ruled_source(
        filled=True,
        vertically_merged_policy_value=True,
        policy_value="ENTERED123",
    )

    grid = _build_ruled_form_grid(page, candidate_bbox, controls, ())

    assert grid is not None
    policy_cells = [cell for cell in grid.cells if (cell.row, cell.column) == (2, 1)]
    assert len(policy_cells) == 1
    policy_cell = policy_cells[0]
    assert (policy_cell.row_span, policy_cell.column_span) == (2, 1)
    assert policy_cell.cell_role == "value"
    assert policy_cell.static_kind is None
    assert policy_cell.text == "ENTERED123"
    assert policy_cell.text_state == "present"
    assert policy_cell.value == "ENTERED123"
    assert policy_cell.value_state == "present"
    assert policy_cell.label_cell_orders == ()
    adjacent_control_cells = [
        cell
        for cell in grid.cells
        if cell.row == policy_cell.row
        and cell.column == policy_cell.column + policy_cell.column_span
        and cell.control_keys
    ]
    assert len(adjacent_control_cells) == 1
    assert adjacent_control_cells[0].control_keys == (controls[0].key,)


def test_source_ruled_mixed_role_column_does_not_promote_entered_value_to_label() -> (
    None
):
    from app.services.form_semantics import _build_ruled_form_grid

    page, candidate_bbox, controls = _synthetic_ruled_source(
        filled=True,
        policy_value="ENTERED123",
        mixed_amount_column=True,
    )

    grid = _build_ruled_form_grid(page, candidate_bbox, controls, ())

    assert grid is not None
    cells = {(cell.row, cell.column): cell for cell in grid.cells}
    amount = cells[(1, 1)]
    currency_slot = cells[(1, 2)]
    entered = cells[(2, 1)]
    assert amount.text == "AMOUNT"
    assert amount.cell_role == "static"
    assert amount.static_kind == "row_header"
    assert currency_slot.text == "$"
    assert currency_slot.cell_role == "value"
    assert currency_slot.value is None
    assert currency_slot.value_state == "empty"
    assert currency_slot.label_cell_orders == (amount.reading_order,)
    assert entered.text == "ENTERED123"
    assert entered.cell_role == "value"
    assert entered.static_kind is None
    assert entered.value == "ENTERED123"
    assert entered.value_state == "present"


@pytest.mark.parametrize(
    ("glyph", "expected_state", "expected_concerns"),
    (
        ("X", "checked", ()),
        ("?", "ambiguous", ("form_control_state_ambiguous",)),
    ),
)
def test_source_character_mark_keeps_checkbox_and_grid_with_explicit_state(
    glyph: str,
    expected_state: str,
    expected_concerns: tuple[str, ...],
) -> None:
    from app.services.form_semantics import (
        _build_ruled_form_grid,
        _detect_static_controls,
    )

    page, candidate_bbox, _controls = _synthetic_ruled_source(
        filled=False,
        scale=1.5,
        control_glyph=glyph,
        control_label="OPTION",
    )

    controls, labels = _detect_static_controls(
        page,
        group_bbox=candidate_bbox,
        group_key="synthetic-grid",
    )

    assert len(controls) == 1
    assert len(labels) == 1
    control = controls[0]
    assert control.label_key == "option"
    assert control.state == expected_state
    assert control.concern_codes == expected_concerns
    glyph_chars = [
        char
        for char in page.chars
        if char.text == glyph
        and control.bbox[0] < (char.x0 + char.x1) / 2 < sum(control.bbox[::2])
        and control.bbox[1]
        < (char.top + char.bottom) / 2
        < control.bbox[1] + control.bbox[3]
    ]
    assert len(glyph_chars) == 1
    assert (
        "character_range",
        glyph_chars[0].index,
        glyph_chars[0].index + 1,
    ) in control.source_objects

    grid = _build_ruled_form_grid(page, candidate_bbox, controls, ())
    assert grid is not None
    owners = [cell for cell in grid.cells if control.key in cell.control_keys]
    assert len(owners) == 1


def test_source_broad_owner_with_two_equally_supported_grids_fails_closed() -> None:
    from app.services.form_semantics import (
        FormSourcePage,
        SourceVector,
        _build_ruled_form_grid,
        _DetectedControl,
        _snapped_ruled_region_bbox,
    )

    vectors = []

    def line(x0: float, y0: float, x1: float, y1: float) -> None:
        vectors.append(
            SourceVector(
                kind="line",
                index=len(vectors),
                x0=x0,
                top=y0,
                x1=x1,
                bottom=y1,
                fill=False,
            )
        )

    left, right = 10.0, 110.0
    for top, bottom in ((10.0, 40.0), (60.0, 90.0)):
        for y in (top, (top + bottom) / 2, bottom):
            line(left, y, right, y)
        for x in (left, 30.0, 50.0, 70.0, 90.0, right):
            line(x, top, x, bottom)
    checkbox_index = len(vectors)
    vectors.append(
        SourceVector(
            kind="rect",
            index=checkbox_index,
            x0=14.0,
            top=14.0,
            x1=22.0,
            bottom=22.0,
            fill=False,
        )
    )
    page = FormSourcePage(
        page_index=1,
        width=120.0,
        height=100.0,
        chars=(),
        words=(),
        vectors=tuple(vectors),
        annotations=(),
        interactivity="static",
    )
    broad_bbox = (left, 10.0, right - left, 80.0)
    control = _DetectedControl(
        key="synthetic-choice",
        group_key="synthetic-grid",
        bbox=(14.0, 14.0, 8.0, 8.0),
        label_key=None,
        source_objects=(("rect", checkbox_index, None),),
        state="unchecked",
    )

    assert _snapped_ruled_region_bbox(page, broad_bbox) is None
    assert _build_ruled_form_grid(page, broad_bbox, (control,), ()) is None


def test_source_backed_reading_edge_refuses_a_reversing_grid_move() -> None:
    from types import SimpleNamespace

    from app.services.form_semantics import (
        _raw_reading_constraints_allow_move,
        _reorder_form_grid_anchors,
    )
    from app.services.ir import (
        ElementRecord,
        IRBoundingBox,
        PageRecord,
        RelationshipRecord,
        RelationshipType,
    )

    old_order = ("a", "b", "c")
    page = PageRecord(
        id="page-1",
        page_index=1,
        page_number=1,
        page_label="1",
        coordinate_system_id="coords-1",
        element_ids=list(old_order),
        presentation_element_ids=list(old_order),
    )
    elements = [
        ElementRecord(
            id=element_id,
            page_id=page.id,
            type="text",
            reading_order=reading_order,
            bbox_ids=[f"bbox-{element_id}"],
            properties={"legacy_item": {"reading_order": reading_order}},
        )
        for reading_order, element_id in enumerate(old_order)
    ]
    bboxes = [
        IRBoundingBox(
            id=f"bbox-{element_id}",
            coordinate_system_id=page.coordinate_system_id,
            x=0.0,
            y=y,
            width=100.0,
            height=10.0,
        )
        for element_id, y in zip(old_order, (30.0, 0.0, 50.0), strict=True)
    ]
    relationships = [
        RelationshipRecord(
            id="legacy-a-b",
            type=RelationshipType.READING_BEFORE,
            source_id="a",
            target_id="b",
            metadata={"basis": "legacy_reading_order"},
        ),
        RelationshipRecord(
            id="legacy-b-c",
            type=RelationshipType.READING_BEFORE,
            source_id="b",
            target_id="c",
            metadata={"basis": "legacy_reading_order"},
        ),
        RelationshipRecord(
            id="source-a-b",
            type=RelationshipType.READING_BEFORE,
            source_id="a",
            target_id="b",
            evidence_ids=["source-reading-evidence"],
            metadata={"reference_metadata": [{"origin": "source"}]},
        ),
    ]
    ir = SimpleNamespace(
        pages=[page],
        elements=elements,
        bboxes=bboxes,
        relationships=relationships,
    )
    proposed_order = ("b", "a", "c")
    candidate = SimpleNamespace(
        page_index=1,
        anchor_element_id="b",
        form_grid=SimpleNamespace(bbox=(0.0, 10.0, 100.0, 10.0)),
    )

    assert not _raw_reading_constraints_allow_move(
        ir,
        old_order,
        proposed_order,
        page_index=1,
    )
    _reorder_form_grid_anchors(ir, (candidate,))

    assert tuple(page.presentation_element_ids) == old_order
    assert [element.reading_order for element in elements] == [0, 1, 2]
    reading_pairs = [
        (relationship.source_id, relationship.target_id)
        for relationship in ir.relationships
        if relationship.type is RelationshipType.READING_BEFORE
    ]
    assert ("a", "b") in reading_pairs
    assert ("b", "a") not in reading_pairs


def test_form_grid_links_only_the_immediately_adjacent_same_row_static_label() -> None:
    payload = _adjacent_label_grid()

    grid = _validate_grid(payload)

    assert grid.cells[2].label_cell_orders == [1]
    assert grid.cells[3].label_cell_orders == []
    assert grid.cells[4].label_cell_orders == []

    nonadjacent = deepcopy(payload)
    nonadjacent["cells"][3]["label_cell_orders"] = [1]
    with pytest.raises(ValidationError):
        _validate_grid(nonadjacent)


def test_synthetic_uncertain_value_requires_an_explicit_concern() -> None:
    payload = _synthetic_grid(filled=False)
    uncertain = payload["cells"][6]
    uncertain["value_state"] = "ambiguous"
    uncertain["concern_codes"] = ["form_value_state_ambiguous"]

    grid = _validate_grid(payload).model_dump(mode="json")

    assert grid["cells"][6]["value"] is None
    assert grid["cells"][6]["value_state"] == "ambiguous"
    assert grid["cells"][6]["concern_codes"] == ["form_value_state_ambiguous"]


def test_grid_renderer_preserves_control_text_control_source_order() -> None:
    from app.services.form_semantics import (
        PublicFormControl,
        PublicFormGroup,
        _render_public_form_grid,
    )

    payload = _synthetic_grid(filled=False)
    for cell in payload["cells"]:
        cell["control_ids"] = []
        cell["content_fragments"] = _content_fragments(
            text=cell["text"],
            control_ids=(),
            bbox=cell["bbox"],
            source_objects=cell["source_objects"],
        )

    target = payload["cells"][6]
    left_control_id = "control-left"
    right_control_id = "control-right"
    left_bbox = {"x": 48.0, "y": 80.0, "width": 8.0, "height": 8.0, "unit": "pt"}
    text_bbox = {
        "x": 60.0,
        "y": 80.0,
        "width": 52.0,
        "height": 8.0,
        "unit": "pt",
    }
    right_bbox = {
        "x": 128.0,
        "y": 80.0,
        "width": 8.0,
        "height": 8.0,
        "unit": "pt",
    }
    left_source = {"kind": "rect", "index": 100}
    text_source = {"kind": "character_range", "start": 0, "end": 7}
    right_source = {"kind": "rect", "index": 101}
    target["text"] = "BETWEEN"
    target["text_state"] = "present"
    target["control_ids"] = [left_control_id, right_control_id]
    target["source_objects"] = [left_source, text_source, right_source]
    target["content_fragments"] = [
        {
            "source_order": 0,
            "kind": "control",
            "bbox": left_bbox,
            "control_id": left_control_id,
            "source_objects": [left_source],
        },
        {
            "source_order": 1,
            "kind": "text",
            "bbox": text_bbox,
            "text": "BETWEEN",
            "source_objects": [text_source],
        },
        {
            "source_order": 2,
            "kind": "control",
            "bbox": right_bbox,
            "control_id": right_control_id,
            "source_objects": [right_source],
        },
    ]
    grid = _validate_grid(payload)
    group = PublicFormGroup.model_validate(
        {
            "id": "group-record",
            "element_id": "group-element",
            "page_index": 1,
            "bbox": payload["bbox"],
            "evidence_methods": ["vector"],
            "source_objects": [{"kind": "line", "index": 0}],
            "confidence_dimensions": _confidence(transcription=True),
            "concern_codes": [],
            "relationship_ids": ["rel-group-anchor"],
            "group_key": "fragment-order-grid",
            "status": "resolved",
            "interactivity": "static",
            "canonical_mode": "replace",
            "anchor_public_item_id": "anchor-item",
            "anchor_element_id": "anchor-element",
            "anchor_relationship_ids": ["rel-group-anchor"],
            "contributor_public_item_ids": ["anchor-item"],
            "contributor_element_ids": ["anchor-element"],
            "field_ids": [],
            "label_ids": [],
            "value_region_ids": [],
            "control_ids": [left_control_id, right_control_id],
            "key_value_pair_ids": [],
            "form_grid": grid,
        },
        strict=True,
    )

    def control_payload(
        control_id: str,
        element_id: str,
        bbox: Mapping[str, Any],
        source_object: Mapping[str, Any],
        state: str,
    ) -> dict[str, Any]:
        return {
            "id": control_id,
            "element_id": element_id,
            "page_index": 1,
            "bbox": bbox,
            "evidence_methods": ["vector"],
            "source_objects": [source_object],
            "confidence_dimensions": _confidence(transcription=False),
            "concern_codes": [],
            "relationship_ids": ["rel-group-control", f"rel-{control_id}"],
            "group_id": "group-record",
            "owner_field_id": None,
            "label_id": None,
            "control_type": "checkbox",
            "state": state,
            "origin": "static_vector",
        }

    controls = [
        PublicFormControl.model_validate(
            control_payload(
                left_control_id,
                "control-left-element",
                left_bbox,
                left_source,
                "unchecked",
            ),
            strict=True,
        ),
        PublicFormControl.model_validate(
            control_payload(
                right_control_id,
                "control-right-element",
                right_bbox,
                right_source,
                "checked",
            ),
            strict=True,
        ),
    ]

    rendering = _render_public_form_grid(group=group, controls=controls, labels=())

    assert rendering is not None
    markdown, text = rendering
    unchecked = (
        '<span role="checkbox" aria-checked="false" data-state="unchecked">☐</span>'
    )
    checked = '<span role="checkbox" aria-checked="true" data-state="checked">☑</span>'
    assert markdown.count(unchecked) == markdown.count(checked) == 1
    assert (
        markdown.index(unchecked) < markdown.index("BETWEEN") < markdown.index(checked)
    )
    assert text.count("☐ BETWEEN ☑") == 1


@pytest.mark.parametrize(
    "corruption",
    (
        "duplicate_anchor",
        "overlapping_span",
        "uncovered_slot",
        "cell_bbox_mismatch",
        "grid_bbox_mismatch",
        "unordered_boundary",
        "nonfinite_boundary",
        "duplicate_control_owner",
        "text_state_mismatch",
        "empty_cell_with_value",
        "present_cell_without_value",
        "static_cell_with_field_state",
        "value_cell_without_field_state",
        "reading_order_gap",
        "ambiguous_value_without_concern",
        "ambiguity_concern_without_ambiguous_value",
        "missing_header_relation",
        "missing_section_relation",
        "spurious_label_relation",
        "rowspanning_label_relation",
        "missing_content_fragments",
        "fragment_order_gap",
        "fragment_text_mismatch",
        "fragment_control_mismatch",
        "fragment_bbox_outside_cell",
        "fragment_source_outside_cell",
        "fragment_has_text_and_control",
        "unknown_key",
    ),
)
def test_synthetic_grid_contract_fails_closed_on_invalid_structure(
    corruption: str,
) -> None:
    payload = _synthetic_grid(filled=False)
    if corruption == "duplicate_anchor":
        payload["cells"].insert(1, deepcopy(payload["cells"][0]))
    elif corruption == "overlapping_span":
        payload["cells"][5]["column_span"] = 2
        payload["cells"][5]["bbox"]["width"] = 140.0 - 16.0
    elif corruption == "uncovered_slot":
        payload["cells"].pop()
    elif corruption == "cell_bbox_mismatch":
        payload["cells"][0]["bbox"]["width"] += 1.0
    elif corruption == "grid_bbox_mismatch":
        payload["bbox"]["height"] += 1.0
    elif corruption == "unordered_boundary":
        payload["row_boundaries"][2] = payload["row_boundaries"][1]
    elif corruption == "nonfinite_boundary":
        payload["column_boundaries"][1] = nan
    elif corruption == "duplicate_control_owner":
        payload["cells"][8]["control_ids"] = ["synthetic-control-unchecked"]
    elif corruption == "text_state_mismatch":
        payload["cells"][0]["text"] = None
    elif corruption == "empty_cell_with_value":
        payload["cells"][6]["value"] = "fabricated"
    elif corruption == "present_cell_without_value":
        payload["cells"][6]["value_state"] = "present"
    elif corruption == "static_cell_with_field_state":
        payload["cells"][0]["value_state"] = "empty"
    elif corruption == "value_cell_without_field_state":
        payload["cells"][6]["cell_role"] = "static"
    elif corruption == "reading_order_gap":
        payload["cells"][6]["reading_order"] += 1
    elif corruption == "ambiguous_value_without_concern":
        payload["cells"][6]["value_state"] = "ambiguous"
    elif corruption == "ambiguity_concern_without_ambiguous_value":
        payload["cells"][6]["concern_codes"] = ["form_value_state_ambiguous"]
    elif corruption == "missing_header_relation":
        payload["cells"][6]["header_cell_orders"] = []
    elif corruption == "missing_section_relation":
        payload["cells"][6]["section_cell_orders"] = []
    elif corruption == "spurious_label_relation":
        payload["cells"][6]["label_cell_orders"] = [1]
    elif corruption == "rowspanning_label_relation":
        payload["cells"][6]["label_cell_orders"] = [5]
    elif corruption == "missing_content_fragments":
        payload["cells"][0].pop("content_fragments")
    elif corruption == "fragment_order_gap":
        payload["cells"][0]["content_fragments"][0]["source_order"] = 1
    elif corruption == "fragment_text_mismatch":
        payload["cells"][0]["content_fragments"][0]["text"] = "ALTERED"
    elif corruption == "fragment_control_mismatch":
        payload["cells"][7]["content_fragments"][0]["control_id"] = "different-control"
    elif corruption == "fragment_bbox_outside_cell":
        payload["cells"][0]["content_fragments"][0]["bbox"]["x"] -= 2.0
    elif corruption == "fragment_source_outside_cell":
        payload["cells"][0]["content_fragments"][0]["source_objects"] = [
            {"kind": "line", "index": 999}
        ]
    elif corruption == "fragment_has_text_and_control":
        payload["cells"][0]["content_fragments"][0]["control_id"] = "different-control"
    elif corruption == "unknown_key":
        payload["cells"][0]["unexpected"] = True
    else:  # pragma: no cover - exhaustive tuple above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        _validate_grid(payload)


@pytest.mark.integration
def test_grid_renderer_keeps_filled_values_in_their_source_cells_after_transform() -> (
    None
):
    owner = deepcopy(_coverage_owner(_release_payload()))
    group = owner["form_group"]
    grid = group["form_grid"]
    empty_cells = [
        cell
        for cell in grid["cells"]
        if cell["value_state"] == "empty"
        and cell["text_state"] == "empty"
        and not cell["control_ids"]
    ]
    assert len(empty_cells) >= 3
    entered = ("SYNTHETIC-POLICY-9931", "987654321")
    for cell, value in zip(empty_cells[:2], entered, strict=True):
        cell["value"] = value
        cell["value_state"] = "present"
        cell["confidence_dimensions"]["transcription"] = {"score": 0.94}
    uncertain = empty_cells[2]
    uncertain["value_state"] = "ambiguous"
    uncertain["concern_codes"] = ["form_value_state_ambiguous"]

    # Simulate a renamed/reserialized source moved to physical page 2 and
    # rendered at a different scale.  Semantic IDs remain opaque; topology is
    # expected to follow the source-relative cell coordinates.
    scale = 0.8
    left, top = 42.0, 80.0
    source_left = float(grid["column_boundaries"][0])
    source_top = float(grid["row_boundaries"][0])

    def tx(value: float) -> float:
        return left + (float(value) - source_left) * scale

    def ty(value: float) -> float:
        return top + (float(value) - source_top) * scale

    grid["column_boundaries"] = [tx(value) for value in grid["column_boundaries"]]
    grid["row_boundaries"] = [ty(value) for value in grid["row_boundaries"]]
    grid["bbox"] = {
        "x": left,
        "y": top,
        "width": GRID_BBOX[2] * scale,
        "height": GRID_BBOX[3] * scale,
        "unit": "pt",
    }
    group["bbox"] = deepcopy(grid["bbox"])
    group["page_index"] = 2
    for key in (
        "form_fields",
        "form_labels",
        "form_value_regions",
        "form_controls",
        "form_key_value_pairs",
    ):
        for record in owner.get(key, []):
            record["page_index"] = 2
    for control in owner.get("form_controls", []):
        bbox = control["bbox"]
        bbox["x"] = tx(bbox["x"])
        bbox["y"] = ty(bbox["y"])
        bbox["width"] = float(bbox["width"]) * scale
        bbox["height"] = float(bbox["height"]) * scale
    for cell in grid["cells"]:
        bbox = cell["bbox"]
        bbox["x"] = tx(bbox["x"])
        bbox["y"] = ty(bbox["y"])
        bbox["width"] = float(bbox["width"]) * scale
        bbox["height"] = float(bbox["height"]) * scale
        for fragment in cell["content_fragments"]:
            fragment_bbox = fragment["bbox"]
            fragment_bbox["x"] = tx(fragment_bbox["x"])
            fragment_bbox["y"] = ty(fragment_bbox["y"])
            fragment_bbox["width"] = float(fragment_bbox["width"]) * scale
            fragment_bbox["height"] = float(fragment_bbox["height"]) * scale

    rendering = _render_mutated_owner(owner)
    assert rendering.markdown.count("<table") == 1
    assert rendering.markdown.count("</table>") == 1
    assert 'rowspan="' in rendering.markdown
    assert 'colspan="' in rendering.markdown
    for value in entered:
        assert rendering.markdown.count(value) == 1
        assert rendering.text.count(value) == 1
        populated_cells = [
            fragment
            for fragment in re.findall(
                r"<td [^>]*>.*?</td>",
                rendering.markdown,
                flags=re.DOTALL,
            )
            if value in fragment
        ]
        assert len(populated_cells) == 1
        assert 'headers="' in populated_cells[0]
        assert "aria-labelledby=" not in populated_cells[0]
        assert "aria-label=" not in populated_cells[0]
    assert rendering.markdown.count('data-value-state="ambiguous">?</span>') == 1
    assert rendering.text.count("[uncertain value]") == 1


@pytest.mark.integration
def test_real_acord_grid_has_one_bounded_resolved_public_owner() -> None:
    payload = _release_payload()
    owner = _coverage_owner(payload)
    group = owner["form_group"]
    grid = group["form_grid"]

    assert group["status"] == "resolved"
    assert group["interactivity"] == "static"
    assert group["canonical_mode"] == "replace"
    assert group["concern_codes"] == []
    assert _bbox_tuple(group["bbox"]) == pytest.approx(GRID_BBOX, abs=0.01)
    assert _bbox_tuple(grid["bbox"]) == pytest.approx(GRID_BBOX, abs=0.01)
    _assert_complete_nonoverlapping_grid(grid)
    cells = grid["cells"]
    assert len(cells) == 82
    assert len(cells) <= 4_096
    assert sum(cell["row_span"] > 1 or cell["column_span"] > 1 for cell in cells) == 30
    assert sum(cell["row_span"] * cell["column_span"] - 1 for cell in cells) == 107
    assert Counter(cell["text_state"] for cell in cells) == {
        "present": 47,
        "empty": 35,
    }
    assert Counter(cell["value_state"] for cell in cells) == {
        "not_applicable": 29,
        "empty": 53,
    }
    assert Counter(cell["static_kind"] for cell in cells) == {
        None: 53,
        "column_header": 8,
        "row_header": 16,
        "section_header": 4,
        "qualifier": 1,
    }
    assert {
        value_order: cells[value_order]["section_cell_orders"]
        for value_order in (8, 29, 46, 59)
    } == {
        8: [9],
        29: [30],
        46: [47],
        59: [60],
    }
    assert all(cell["value"] is None for cell in cells)
    assert all(
        cell["value_state"] == "empty"
        for cell in cells
        if cell["text_state"] == "empty"
    )
    dollar_cells = [cell for cell in cells if cell["text"] == "$"]
    assert len(dollar_cells) == 18
    assert all(
        cell["value"] is None and cell["value_state"] == "empty"
        for cell in dollar_cells
    )

    label_edges = [
        (cells[label_order], cell)
        for cell in cells
        for label_order in cell["label_cell_orders"]
    ]
    expected_label_rows = {1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14, 16, 17, 18, 19}
    assert len(label_edges) == 16
    assert {
        (label["row"], label["column"], value["row"], value["column"])
        for label, value in label_edges
    } == {(row, 7, row, 8) for row in expected_label_rows}
    assert all(
        label["cell_role"] == "static"
        and label["static_kind"] == "row_header"
        and label["text_state"] == "present"
        and label["row_span"] == 1
        and value["row_span"] == 1
        and label["column"] + label["column_span"] == value["column"]
        for label, value in label_edges
    )
    rowspanning_static_orders = {
        cell["reading_order"]
        for cell in cells
        if cell["cell_role"] == "static" and cell["row_span"] > 1
    }
    printed_not_applicable = [
        cell for cell in cells if _normalized_source_text(cell["text"]) == "N / A"
    ]
    assert len(printed_not_applicable) == 1
    not_applicable_cell = printed_not_applicable[0]
    assert not_applicable_cell["static_kind"] == "qualifier"
    assert not_applicable_cell["reading_order"] in rowspanning_static_orders
    assert not_applicable_cell["section_cell_orders"] == []
    assert not_applicable_cell["label_cell_orders"] == []
    assert len(not_applicable_cell["header_cell_orders"]) == 1
    not_applicable_header = cells[not_applicable_cell["header_cell_orders"][0]]
    assert not_applicable_header["static_kind"] == "column_header"
    assert (
        not_applicable_header["column"]
        <= 2
        < (not_applicable_header["column"] + not_applicable_header["column_span"])
    )
    assert rowspanning_static_orders.isdisjoint(
        label_order for cell in cells for label_order in cell["label_cell_orders"]
    )
    assert all(
        not cell["label_cell_orders"] for cell in cells if cell["cell_role"] == "static"
    )

    page = payload["pages"][0]
    controls = {control["id"]: control for control in owner.get("form_controls", [])}
    referenced_control_ids = {
        control_id for cell in grid["cells"] for control_id in cell["control_ids"]
    }
    assert len(referenced_control_ids) == 24
    assert referenced_control_ids <= set(controls)
    assert all(
        controls[control_id]["origin"] == "static_vector"
        and controls[control_id]["state"] in {"checked", "unchecked", "ambiguous"}
        for control_id in referenced_control_ids
    )
    assert Counter(
        controls[control_id]["state"] for control_id in referenced_control_ids
    ) == {"unchecked": 24}
    assert {
        (
            round(float(controls[control_id]["bbox"]["x"]), 1),
            round(float(controls[control_id]["bbox"]["y"]), 1),
            controls[control_id]["state"],
        )
        for control_id in referenced_control_ids
    } == CONTROL_ORACLE

    overlapping_grid_owners = [
        item
        for item in page["items"]
        if item.get("type") in {"table", "table_candidate"}
        and isinstance(item.get("bbox"), Mapping)
        and _grid_overlap_ratio(item["bbox"]) >= 0.9
    ]
    assert overlapping_grid_owners
    assert all(
        item["id"] in group["contributor_public_item_ids"]
        for item in overlapping_grid_owners
    )
    anchor_owners = [
        item
        for item in overlapping_grid_owners
        if item["id"] == group["anchor_public_item_id"]
    ]
    assert len(anchor_owners) == 1
    assert anchor_owners[0]["type"] in {"table", "table_candidate"}
    anchor_block = _canonical_block(
        payload,
        primary_element_id=group["anchor_element_id"],
    )
    assert anchor_block.get("omission_reason") is None
    assert '<table data-form-grid="true">' in anchor_block["markdown"]

    for item in (
        candidate
        for candidate in overlapping_grid_owners
        if candidate["id"] != group["anchor_public_item_id"]
    ):
        element_id = group["contributor_element_ids"][
            group["contributor_public_item_ids"].index(item["id"])
        ]
        block = _canonical_block(payload, primary_element_id=element_id)
        assert block["markdown"] == ""
        assert block["text"] == ""
        assert block["omission_reason"] == "consumed_by_relationship"
        assert block["suppressed_by_element_id"] == group["anchor_element_id"]


@pytest.mark.integration
def test_real_acord_grid_markdown_preserves_spans_without_duplicate_neighbors() -> None:
    payload = _release_payload()
    owner = _coverage_owner(payload)
    group = owner["form_group"]
    grid = group["form_grid"]
    block = _canonical_block(
        payload,
        primary_element_id=group["anchor_element_id"],
    )
    markdown = block["markdown"]

    assert markdown.count("<table") == markdown.count("</table>") == 1
    assert markdown.count("<thead>") == markdown.count("</thead>") == 1
    assert markdown.count("<tbody>") == markdown.count("</tbody>") == 1
    assert markdown.count("<tr") == 21
    assert markdown.count("<th ") == 28
    assert markdown.count("<td") == 54
    assert markdown.count('rowspan="') == 28
    assert markdown.count('colspan="') == 2
    rendered_cells: dict[int, tuple[str, dict[str, str]]] = {}
    for tag, raw_attributes in re.findall(r"<(th|td) ([^>]*)>", markdown):
        attributes = dict(re.findall(r'([a-z][a-z0-9-]*)="([^"]*)"', raw_attributes))
        rendered_cells[int(attributes["data-reading-order"])] = (tag, attributes)
    assert len(rendered_cells) == 82
    cell_dom_ids = {attributes["id"] for _tag, attributes in rendered_cells.values()}
    assert len(cell_dom_ids) == 82
    assert markdown.count('scope="col"') == 8
    assert markdown.count('scope="row"') == 16
    assert markdown.count('scope="rowgroup"') == 4
    assert markdown.count('data-static-kind="qualifier"') == 1
    assert markdown.count('headers="') == 74
    assert 'aria-labelledby="' not in markdown
    for cell in grid["cells"]:
        tag, attributes = rendered_cells[cell["reading_order"]]
        expected_tag = (
            "th"
            if cell["static_kind"] in {"column_header", "row_header", "section_header"}
            else "td"
        )
        assert tag == expected_tag
        expected_refs = [
            *cell["header_cell_orders"],
            *cell["section_cell_orders"],
            *cell["label_cell_orders"],
        ]
        expected_dom_refs = [rendered_cells[order][1]["id"] for order in expected_refs]
        if expected_dom_refs:
            assert attributes["headers"].split() == expected_dom_refs
            assert set(expected_dom_refs) <= cell_dom_ids
        else:
            assert "headers" not in attributes
        assert "aria-labelledby" not in attributes
        assert "aria-label" not in attributes
    controls_by_id = {
        control["id"]: control for control in owner.get("form_controls", [])
    }
    labels_by_id = {label["id"]: label for label in owner.get("form_labels", [])}
    rendered_control_attributes = re.findall(
        r'<span role="checkbox" ([^>]*)>',
        markdown,
    )
    ordered_controls = [
        controls_by_id[control_id]
        for cell in grid["cells"]
        for control_id in cell["control_ids"]
    ]
    assert len(rendered_control_attributes) == len(ordered_controls) == 24
    parsed_control_attributes = []
    for raw_attributes, control in zip(
        rendered_control_attributes,
        ordered_controls,
        strict=True,
    ):
        attributes = dict(re.findall(r'([a-z][a-z0-9-]*)="([^"]*)"', raw_attributes))
        parsed_control_attributes.append(attributes)
        label = labels_by_id.get(control.get("label_id"))
        if label is None:
            assert "aria-label" not in attributes
        else:
            assert attributes["aria-label"] == html.escape(label["text"], quote=True)
    assert Counter(
        (attributes["aria-checked"], attributes["data-state"])
        for attributes in parsed_control_attributes
    ) == {("false", "unchecked"): 24}
    assert DISCLAIMER_PREFIX not in markdown
    assert DESCRIPTION_PREFIX not in markdown
    assert all(
        isinstance(cell["value"], str) and cell["value"].strip()
        for cell in grid["cells"]
        if cell["value_state"] == "present"
    )

    normalized_cells = _normalized_source_text(
        "\n".join(str(cell["text"] or "") for cell in grid["cells"])
    )
    normalized_markdown = _normalized_source_text(markdown)
    for visible_text, expected_count in VISIBLE_GRID_TEXT_COUNTS.items():
        assert _visible_phrase_count(normalized_cells, visible_text) == expected_count
        assert (
            _visible_phrase_count(normalized_markdown, visible_text) == expected_count
        )
    assert normalized_cells.count("$") == 19
    assert normalized_markdown.count("$") == 19

    canonical = payload["canonical_presentation"]["full"]["markdown"]
    assert canonical.count(DISCLAIMER_PREFIX) == 1
    assert canonical.count(DESCRIPTION_PREFIX) == 1
    assert canonical.count(markdown) == 1
    heading_markers = (
        "# COVERAGES",
        "# CERTIFICATE NUMBER:",
        "# REVISION NUMBER:",
    )
    assert all(canonical.count(marker) == 1 for marker in heading_markers)
    positions = [canonical.index(marker) for marker in heading_markers]
    positions.extend(
        (
            canonical.index(DISCLAIMER_PREFIX),
            canonical.index(markdown),
            canonical.index(DESCRIPTION_PREFIX),
        )
    )
    assert positions == sorted(positions)

    page_items = payload["pages"][0]["items"]
    item_sequence = [
        next(item for item in page_items if item.get("value") == "COVERAGES"),
        next(item for item in page_items if item.get("value") == "CERTIFICATE NUMBER:"),
        next(item for item in page_items if item.get("value") == "REVISION NUMBER:"),
        next(
            item
            for item in page_items
            if item.get("type") == "text"
            and str(item.get("value") or "").startswith(DISCLAIMER_PREFIX)
        ),
        owner,
        next(
            item
            for item in page_items
            if item.get("type") == "text"
            and str(item.get("value") or "").startswith(DESCRIPTION_PREFIX)
        ),
    ]
    assert [page_items.index(item) for item in item_sequence] == sorted(
        page_items.index(item) for item in item_sequence
    )
    reading_orders = [int(item["reading_order"]) for item in item_sequence]
    assert reading_orders == sorted(reading_orders)
    assert len(reading_orders) == len(set(reading_orders))
    assert to_markdown(ParseResult.model_validate(payload)) == canonical


@pytest.mark.integration
def test_acord_parties_block_remains_the_reviewed_14_by_18_control() -> None:
    payload = _release_payload()
    parties = next(
        item
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("form_group"), Mapping)
        and item["form_group"].get("group_key") == "parties-and-insurers"
    )

    assert len(parties["form_labels"]) == 14
    assert len(parties["form_fields"]) == 18
    assert Counter(field["value_state"] for field in parties["form_fields"]) == {
        "empty": 18
    }
    assert all(field["value"] is None for field in parties["form_fields"])
    full = payload["canonical_presentation"]["full"]["markdown"].casefold()
    assert "phone name:" not in full
    assert "empty source-visible field" not in full
    assert "[signature]" not in full
