"""Shared fail-closed owner eligibility for source-note projection."""

from __future__ import annotations

import math
from typing import Any, Mapping


SOURCE_NOTE_OWNER_TYPES = frozenset(
    {"table", "image", "chart", "diagram"}
)
_UNRESOLVED_CANDIDATE_REASON = "upstream_reconciliation_unresolved"
_MIN_TABLE_SUPPORT = 0.62
_MIN_CELL_COVERAGE = 0.75
_MAX_ROWS = 4_096
_MAX_COLUMNS = 256
_MAX_CELLS = 65_536


def is_eligible_unresolved_table_candidate(
    item: Mapping[str, Any],
) -> bool:
    """Accept one bounded unresolved-table candidate shape.

    ``table_candidate`` remains a candidate. This predicate grants only note
    ownership when the public table gate already proves an unowned,
    structurally usable unresolved grid. Partial, weak, or malformed gate/grid
    state fails closed.
    """

    item_type = item.get("type")
    if type(item_type) is not str or item_type.casefold() != "table_candidate":
        return False

    gate = item.get("table_candidate_gate")
    reasons = item.get("table_candidate_gate_reasons")
    sources = item.get("table_candidate_gate_sources")
    rows = item.get("rows")
    row_count = item.get("row_count")
    column_count = item.get("column_count")
    if (
        type(gate) is not dict
        or gate.get("outcome") != "unresolved"
        or gate.get("owner_item_ids") != []
        or reasons != [_UNRESOLVED_CANDIDATE_REASON]
        or sources != []
        or type(rows) is not list
        or type(row_count) is not int
        or type(row_count) is bool
        or row_count != len(rows)
        or not 2 <= row_count <= _MAX_ROWS
        or type(column_count) is not int
        or type(column_count) is bool
        or not 2 <= column_count <= _MAX_COLUMNS
        or row_count * column_count > _MAX_CELLS
    ):
        return False

    feature_scores = gate.get("feature_scores")
    table_support = (
        feature_scores.get("table_support")
        if type(feature_scores) is dict
        else None
    )
    cell_coverage = (
        feature_scores.get("cell_coverage")
        if type(feature_scores) is dict
        else None
    )
    if (
        type(table_support) not in {int, float}
        or type(table_support) is bool
        or not _MIN_TABLE_SUPPORT <= table_support <= 1.0
        or not math.isfinite(table_support)
        or type(cell_coverage) not in {int, float}
        or type(cell_coverage) is bool
        or not _MIN_CELL_COVERAGE <= cell_coverage <= 1.0
        or not math.isfinite(cell_coverage)
    ):
        return False

    return all(
        type(row) is list
        and len(row) == column_count
        and all(type(cell) is str for cell in row)
        for row in rows
    )


def is_source_note_owner_item(item: Mapping[str, Any]) -> bool:
    """Accept definitive owners or an eligible unresolved table candidate."""

    item_type = item.get("type")
    return (
        type(item_type) is str
        and (
            item_type.casefold() in SOURCE_NOTE_OWNER_TYPES
            or is_eligible_unresolved_table_candidate(item)
        )
    )
