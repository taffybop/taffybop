from __future__ import annotations

from typing import Any

from app.services.pipeline import _docling_table_item, _table_html


def _cell(
    row: int,
    column: int,
    text: str,
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
    column_header: bool = False,
    row_header: bool = False,
    row_section: bool = False,
    row_span: int = 1,
    col_span: int = 1,
) -> dict[str, Any]:
    return {
        "start_row_offset_idx": row,
        "end_row_offset_idx": row + row_span,
        "start_col_offset_idx": column,
        "end_col_offset_idx": column + col_span,
        "row_span": row_span,
        "col_span": col_span,
        "text": text,
        "column_header": column_header,
        "row_header": row_header,
        "row_section": row_section,
        "bbox": {
            "l": left,
            "t": top,
            "r": right,
            "b": bottom,
            "coord_origin": "TOPLEFT",
        },
    }


def _word(
    text: str,
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> dict[str, Any]:
    return {
        "text": text,
        "x0": left,
        "top": top,
        "x1": right,
        "bottom": bottom,
    }


def _mixed_header_table() -> dict[str, Any]:
    return {
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0,
                    "t": 90,
                    "r": 300,
                    "b": 10,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": 3,
            "num_cols": 3,
            "table_cells": [
                _cell(
                    0,
                    1,
                    "Years ended",
                    left=150,
                    top=5,
                    right=250,
                    bottom=15,
                    column_header=True,
                    col_span=2,
                ),
                _cell(
                    1,
                    0,
                    "Beginning balance",
                    left=0,
                    top=40,
                    right=90,
                    bottom=50,
                    row_section=True,
                ),
                _cell(
                    1,
                    1,
                    "Period A $ 10",
                    left=100,
                    top=20,
                    right=190,
                    bottom=50,
                    column_header=True,
                ),
                _cell(
                    1,
                    2,
                    "Period B $ 20",
                    left=200,
                    top=20,
                    right=290,
                    bottom=50,
                    column_header=True,
                ),
                _cell(
                    2,
                    0,
                    "Next row",
                    left=0,
                    top=55,
                    right=90,
                    bottom=65,
                ),
                _cell(
                    2,
                    1,
                    "11",
                    left=160,
                    top=55,
                    right=175,
                    bottom=65,
                ),
                _cell(
                    2,
                    2,
                    "21",
                    left=260,
                    top=55,
                    right=275,
                    bottom=65,
                ),
            ],
        },
    }


def _mixed_header_words() -> list[dict[str, Any]]:
    return [
        _word("Period", left=110, top=20, right=145, bottom=28),
        _word("A", left=150, top=20, right=158, bottom=28),
        _word("$", left=150, top=41, right=155, bottom=49),
        _word("10", left=165, top=41, right=177, bottom=49),
        _word("Period", left=210, top=20, right=245, bottom=28),
        _word("B", left=250, top=20, right=258, bottom=28),
        _word("$", left=250, top=41, right=255, bottom=49),
        _word("20", left=265, top=41, right=277, bottom=49),
    ]


def test_table_html_honors_empty_grid_slots_and_spans() -> None:
    rows = [
        ["", "Years ended", "", ""],
        ["", "2023", "2022", "2021"],
        ["Revenue", "10", "20", "30"],
        ["", "All periods", "", ""],
    ]
    cells = [
        {
            "row": 0,
            "column": 1,
            "row_span": 1,
            "col_span": 3,
            "text": "Years ended",
            "column_header": True,
        },
        *[
            {
                "row": 1,
                "column": column,
                "row_span": 1,
                "col_span": 1,
                "text": year,
                "column_header": True,
            }
            for column, year in enumerate(("2023", "2022", "2021"), start=1)
        ],
        {
            "row": 2,
            "column": 0,
            "row_span": 2,
            "col_span": 1,
            "text": "Revenue",
            "column_header": False,
        },
        *[
            {
                "row": 2,
                "column": column,
                "row_span": 1,
                "col_span": 1,
                "text": value,
                "column_header": False,
            }
            for column, value in enumerate(("10", "20", "30"), start=1)
        ],
        {
            "row": 3,
            "column": 1,
            "row_span": 1,
            "col_span": 3,
            "text": "All periods",
            "column_header": False,
        },
    ]

    rendered = _table_html(rows, cells)

    assert "<thead>" in rendered
    assert "<tbody>" in rendered
    assert (
        "      <th></th>\n"
        '      <th colspan="3">Years ended</th>'
    ) in rendered
    assert (
        '      <td rowspan="2">Revenue</td>\n'
        "      <td>10</td>\n"
        "      <td>20</td>\n"
        "      <td>30</td>"
    ) in rendered
    assert (
        "    <tr>\n"
        '      <td colspan="3">All periods</td>\n'
        "    </tr>"
    ) in rendered


def test_docling_table_splits_header_and_first_body_row_by_geometry() -> None:
    _, table = _docling_table_item(
        _mixed_header_table(),
        {1: 100.0},
        {1: _mixed_header_words()},
    )

    assert table["row_count"] == 4
    assert table["column_count"] == 3
    assert table["rows"] == [
        ["", "Years ended", ""],
        ["", "Period A", "Period B"],
        ["Beginning balance", "$ 10", "$ 20"],
        ["Next row", "11", "21"],
    ]
    beginning_cell = next(
        cell for cell in table["cells"] if cell["text"] == "Beginning balance"
    )
    assert beginning_cell["row"] == 2
    assert beginning_cell["row_section"] is True

    split_header = next(
        cell for cell in table["cells"] if cell["text"] == "Period A"
    )
    split_value = next(cell for cell in table["cells"] if cell["text"] == "$ 10")
    assert split_header["column_header"] is True
    assert split_value["column_header"] is False
    assert split_header["split_from_text"] == "Period A $ 10"
    assert split_value["split_from_text"] == "Period A $ 10"

    assert (
        "      <th></th>\n"
        "      <th>Period A</th>\n"
        "      <th>Period B</th>"
    ) in table["html"]
    assert (
        "      <td>Beginning balance</td>\n"
        "      <td>$ 10</td>\n"
        "      <td>$ 20</td>"
    ) in table["html"]
    assert table["csv"].splitlines()[2] == "Beginning balance,$ 10,$ 20"


def test_mixed_header_row_is_unchanged_without_lossless_word_split() -> None:
    _, table = _docling_table_item(
        _mixed_header_table(),
        {1: 100.0},
        {
            1: [
                _word("Period", left=110, top=20, right=145, bottom=28),
                _word("A", left=150, top=20, right=158, bottom=28),
            ]
        },
    )

    assert table["row_count"] == 3
    assert table["rows"][1] == [
        "Beginning balance",
        "Period A $ 10",
        "Period B $ 20",
    ]
    assert all("split_from_text" not in cell for cell in table["cells"])
