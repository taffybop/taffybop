"""Reusable cryptographically valid unresolved table-candidate fixture."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

from app.services.table_semantics import validate_table_semantics
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _raw_cell,
    _raw_table,
    _seal,
)
from tests.stories.phase_04.test_p04_us02_table_reconciliation import (
    _enabled_reconcile,
    _vector_table,
)
from tests.stories.phase_04.test_p04_us04_table_candidate_gate import (
    _alternative,
    _gate_candidates,
)


SOURCE_SHA256 = "a" * 64


@lru_cache(maxsize=16)
def _base_raw_table(y: float) -> dict[str, Any]:
    rows = [["Group", "Value"], ["A", "1"]]
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            cell = _raw_cell(
                row_index,
                column_index,
                text,
                column_header=row_index == 0,
                reference_suffix=f"authority-{row_index}-{column_index}",
            )
            cell["bbox"] = {
                "l": 10.0 + column_index * 35.0,
                "t": y + row_index * 15.0,
                "r": 10.0 + (column_index + 1) * 35.0,
                "b": y + (row_index + 1) * 15.0,
                "coord_origin": "TOPLEFT",
            }
            cells.append(cell)
    raw_table = _raw_table(2, 2, cells)
    raw_table["prov"][0]["bbox"] = {
        "l": 10.0,
        "t": y,
        "r": 80.0,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    return raw_table


def authoritative_docling_raw_table(*, y: float) -> dict[str, Any]:
    return deepcopy(_base_raw_table(float(y)))


def authoritative_spanned_docling_raw_table(
    *,
    y: float,
) -> dict[str, Any]:
    raw_table = _raw_table(
        2,
        2,
        [
            _raw_cell(
                0,
                0,
                "one spanning cell",
                row_span=2,
                col_span=2,
                reference_suffix="authority-span",
            )
        ],
    )
    raw_table["prov"][0]["bbox"] = {
        "l": 10.0,
        "t": y,
        "r": 80.0,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    raw_table["data"]["table_cells"][0]["bbox"] = deepcopy(
        raw_table["prov"][0]["bbox"]
    )
    return raw_table


def authoritative_partial_docling_raw_table(
    *,
    y: float,
    row_count: int = 4,
    column_count: int = 4,
    covered_slots: int = 13,
) -> dict[str, Any]:
    assert 0 < covered_slots <= row_count * column_count
    cell_width = 70.0 / column_count
    cell_height = 30.0 / row_count
    cells: list[dict[str, Any]] = []
    for row in range(row_count):
        for column in range(column_count):
            if len(cells) >= covered_slots:
                break
            cell = _raw_cell(
                row,
                column,
                f"{row}:{column}",
                reference_suffix=f"authority-partial-{row}-{column}",
            )
            cell["bbox"] = {
                "l": 10.0 + column * cell_width,
                "t": y + row * cell_height,
                "r": 10.0 + (column + 1) * cell_width,
                "b": y + (row + 1) * cell_height,
                "coord_origin": "TOPLEFT",
            }
            cells.append(cell)
        if len(cells) >= covered_slots:
            break
    raw_table = _raw_table(row_count, column_count, cells)
    raw_table["prov"][0]["bbox"] = {
        "l": 10.0,
        "t": y,
        "r": 80.0,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    return raw_table


def authoritative_partial_spanned_docling_raw_table(
    *,
    y: float,
) -> dict[str, Any]:
    raw_table = _raw_table(
        2,
        4,
        [
            _raw_cell(
                0,
                0,
                "partial spanning cell",
                row_span=2,
                col_span=2,
                reference_suffix="authority-partial-span",
            ),
            _raw_cell(
                0,
                2,
                "upper",
                reference_suffix="authority-partial-upper",
            ),
            _raw_cell(
                1,
                2,
                "lower",
                reference_suffix="authority-partial-lower",
            ),
        ],
    )
    raw_table["prov"][0]["bbox"] = {
        "l": 10.0,
        "t": y,
        "r": 80.0,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    raw_table["data"]["table_cells"][0]["bbox"] = {
        "l": 10.0,
        "t": y,
        "r": 45.0,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    raw_table["data"]["table_cells"][1]["bbox"] = {
        "l": 45.0,
        "t": y,
        "r": 62.5,
        "b": y + 15.0,
        "coord_origin": "TOPLEFT",
    }
    raw_table["data"]["table_cells"][2]["bbox"] = {
        "l": 45.0,
        "t": y + 15.0,
        "r": 62.5,
        "b": y + 30.0,
        "coord_origin": "TOPLEFT",
    }
    return raw_table


def authoritative_unresolved_table_candidate_from_raw(
    item_id: str,
    raw_table: dict[str, Any],
) -> dict[str, Any]:
    marked = _seal(raw_table, finalize=False)
    conflicting_rows = deepcopy(marked["rows"])
    changed = False
    for row in conflicting_rows:
        for column_index in range(len(row)):
            if row[column_index]:
                row[column_index] = (
                    "alternate"
                    if row[column_index] == "different"
                    else "different"
                )
                changed = True
                break
        if changed:
            break
    assert changed
    bbox = marked["bbox"]
    conflicting_vector = _vector_table(
        conflicting_rows,
        bbox={
            "x": float(bbox["x"]),
            "y": float(bbox["y"]),
            "w": float(bbox.get("w", bbox["width"])),
            "h": float(bbox.get("h", bbox["height"])),
        },
    )
    if marked["table_evidence"]["status"] == "unresolved":
        # Keep the authenticated Docling sidecar as the unresolved anchor.
        # A provenance-weaker vector alternative creates the same real P04
        # US02 state without replacing the source grid with a vector-only
        # diagnostic candidate.
        conflicting_vector.cell_bboxes = ()
    unresolved = _enabled_reconcile(marked, conflicting_vector)[1][0]
    assert type(unresolved.get("table_evidence")) is dict
    assert unresolved["table_evidence"]["scope"] == ["P04-US01", "P04-US02"]
    assert unresolved["table_evidence"]["reconciliation"]["outcome"] == (
        "unresolved"
    )
    body_items: dict[int, list[dict[str, Any]]] = {1: []}
    assert _gate_candidates({1: [unresolved]}, body_items) == {1: []}
    candidate = _alternative(body_items)
    candidate_view = deepcopy(candidate)
    candidate_view["type"] = "table"
    candidate_view["table_evidence"] = candidate_view.pop(
        "candidate_table_evidence"
    )
    assert validate_table_semantics(candidate_view, SOURCE_SHA256)
    candidate["id"] = item_id
    candidate["reading_order"] = 0
    return candidate


@lru_cache(maxsize=16)
def _base_candidate(y: float) -> dict[str, Any]:
    return authoritative_unresolved_table_candidate_from_raw(
        "cached-authoritative-candidate",
        authoritative_docling_raw_table(y=y),
    )


def authoritative_unresolved_table_candidate(
    item_id: str,
    *,
    y: float,
) -> dict[str, Any]:
    candidate = deepcopy(_base_candidate(float(y)))
    candidate["id"] = item_id
    candidate["reading_order"] = 0
    return candidate
