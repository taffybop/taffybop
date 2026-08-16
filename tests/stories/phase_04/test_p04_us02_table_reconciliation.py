"""Focused release-first checks for P04-US02 table reconciliation."""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.models import ParseResult
from app.services import pipeline, table_semantics
from app.services.serializer import to_markdown
from app.services.tables import RawTable
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _raw_cell,
    _raw_table,
    _seal,
)


_RECONCILIATION_KEYS = {
    "cluster_id",
    "candidate_ids",
    "selected_candidate_id",
    "outcome",
    "absolute_threshold",
    "selection_margin",
    "scores",
    "evidence_ids",
    "concern_codes",
}
_SOURCE_SHA256 = "a" * 64


def _marked_table(
    rows: list[list[str]],
    *,
    raw_index: int = 0,
) -> dict[str, Any]:
    assert rows and rows[0]
    assert all(len(row) == len(rows[0]) for row in rows)
    cells = [
        _raw_cell(
            row_index,
            column_index,
            text,
            column_header=row_index == 0,
            reference_suffix=f"{raw_index}-{row_index}-{column_index}",
        )
        for row_index, row in enumerate(rows)
        for column_index, text in enumerate(row)
    ]
    raw = _raw_table(
        len(rows),
        len(rows[0]),
        cells,
        self_ref=f"#/tables/{raw_index}",
    )
    return _seal(raw, finalize=False)


def _vector_table(
    rows: list[list[str]],
    *,
    page_index: int = 1,
    bbox: dict[str, float] | None = None,
) -> RawTable:
    assert rows and rows[0]
    assert all(len(row) == len(rows[0]) for row in rows)
    table_bbox = deepcopy(
        bbox
        or {
            "x": 0.0,
            "y": 10.0,
            "w": 300.0,
            "h": 110.0,
        }
    )
    row_height = float(table_bbox["h"]) / len(rows)
    column_width = float(table_bbox["w"]) / len(rows[0])
    row_bboxes = [
        {
            "x": float(table_bbox["x"]),
            "y": float(table_bbox["y"]) + row_index * row_height,
            "w": float(table_bbox["w"]),
            "h": row_height,
        }
        for row_index in range(len(rows))
    ]
    cell_bboxes = tuple(
        tuple(
            {
                "x": float(table_bbox["x"]) + column_index * column_width,
                "y": float(table_bbox["y"]) + row_index * row_height,
                "w": column_width,
                "h": row_height,
            }
            for column_index in range(len(rows[0]))
        )
        for row_index in range(len(rows))
    )
    return RawTable(
        page_index=page_index,
        bbox=table_bbox,
        rows=deepcopy(rows),
        row_bboxes=row_bboxes,
        cell_bboxes=cell_bboxes,
        geometry_inferred=False,
    )


def _legacy_vector_item(raw: RawTable) -> dict[str, Any]:
    item = pipeline._vector_table_item(
        raw,
        table_span_fidelity_enabled=True,
    )
    item["id"] = f"vector-table-{raw.page_index}"
    item["reading_order"] = 0
    return item


def _legacy_docling_item(rows: list[list[str]]) -> dict[str, Any]:
    table: dict[str, Any] = {
        "type": "table",
        "bbox": {
            "x": 0.0,
            "y": 10.0,
            "w": 300.0,
            "h": 110.0,
            "width": 300.0,
            "height": 110.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
        "rows": deepcopy(rows),
        "cells": [],
        "row_count": len(rows),
        "column_count": len(rows[0]),
        "parse_concerns": [],
        "engine": "docling",
        "embedded_images": [],
    }
    pipeline._refresh_table_serializations(table)
    return table


def _enabled_reconcile(
    marked: dict[str, Any],
    vector: RawTable,
) -> dict[int, list[dict[str, Any]]]:
    return table_semantics.reconcile_table_candidates(
        {1: [deepcopy(marked)]},
        {1: [deepcopy(marked)]},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )


def _reconciliation(table: dict[str, Any]) -> dict[str, Any]:
    sidecar = table.get("table_evidence")
    value = (
        sidecar.get("reconciliation")
        if type(sidecar) is dict
        else table.get("table_reconciliation")
    )
    assert type(value) is dict
    assert set(value) == _RECONCILIATION_KEYS
    assert type(value["cluster_id"]) is str and value["cluster_id"]
    assert type(value["candidate_ids"]) is list
    assert value["candidate_ids"]
    assert len(value["candidate_ids"]) == len(set(value["candidate_ids"]))
    assert all(
        type(candidate_id) is str and candidate_id
        for candidate_id in value["candidate_ids"]
    )
    assert type(value["absolute_threshold"]) in (int, float)
    assert type(value["absolute_threshold"]) is not bool
    assert isfinite(float(value["absolute_threshold"]))
    assert type(value["selection_margin"]) in (int, float)
    assert type(value["selection_margin"]) is not bool
    assert isfinite(float(value["selection_margin"]))
    assert type(value["scores"]) is list
    assert len(value["scores"]) == len(value["candidate_ids"])
    assert {
        score.get("candidate_id")
        for score in value["scores"]
        if type(score) is dict
    } == set(value["candidate_ids"])
    assert all(
        type(score) is dict and type(score.get("candidate")) is dict
        for score in value["scores"]
    )
    assert type(value["evidence_ids"]) is list
    assert type(value["concern_codes"]) is list
    assert len(value["concern_codes"]) == len(set(value["concern_codes"]))
    return value


def _retained_rows(reconciliation: dict[str, Any]) -> list[list[list[str]]]:
    return [
        score["candidate"].get("rows")
        for score in reconciliation["scores"]
    ]


def _core_projection(table: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(table.get(key))
        for key in (
            "rows",
            "cells",
            "bbox",
            "caption_ids",
            "source_note_ids",
            "html",
            "md",
            "csv",
            "value",
            "row_count",
            "column_count",
        )
    }


def test_flag_off_returns_the_exact_predecessor_mapping_by_identity() -> None:
    marked = _marked_table([["Name", "Value"], ["A", "1"]])
    merged = {1: [marked]}
    expected = deepcopy(merged)

    returned = table_semantics.reconcile_table_candidates(
        merged,
        {1: [deepcopy(marked)]},
        {1: [_vector_table(marked["rows"])]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=False,
    )

    assert returned is merged
    assert returned == expected
    assert marked["table_evidence"]["reconciliation"] is None
    assert "table_reconciliation" not in marked


def test_overlapping_source_faithful_docling_candidate_wins_without_loss() -> None:
    docling_rows = [
        ["Account", "Amount"],
        ["Cash", "10"],
        ["Total", "10"],
    ]
    vector_rows = docling_rows[:-1]
    marked = _marked_table(docling_rows)
    marked["caption_ids"] = ["caption-1"]
    marked["source_note_ids"] = ["source-note-1"]
    expected = _core_projection(marked)
    expected_candidate_id = marked["table_evidence"]["candidate_id"]

    result = _enabled_reconcile(marked, _vector_table(vector_rows))

    assert list(result) == [1]
    assert len(result[1]) == 1
    winner = result[1][0]
    reconciliation = _reconciliation(winner)
    assert reconciliation["outcome"] == "selected"
    assert reconciliation["selected_candidate_id"] == expected_candidate_id
    assert len(reconciliation["candidate_ids"]) == 2
    assert _core_projection(winner) == expected
    assert "P04-US02" in winner["table_evidence"]["scope"]
    assert vector_rows in _retained_rows(reconciliation)


def test_semantic_duplicate_pair_collapses_to_one_canonical_table() -> None:
    rows = [["Name", "Value"], ["A", "1"], ["B", "2"]]
    marked = _marked_table(rows)

    result = _enabled_reconcile(marked, _vector_table(rows))

    assert len(result[1]) == 1
    reconciliation = _reconciliation(result[1][0])
    assert reconciliation["outcome"] == "duplicate_collapsed"
    assert reconciliation["selected_candidate_id"] in reconciliation["candidate_ids"]
    assert len(reconciliation["candidate_ids"]) == 2
    assert _retained_rows(reconciliation) == [rows, rows]


def test_low_margin_conflict_stays_unresolved_with_retained_alternatives() -> None:
    docling_rows = [["Metric", "Q1"], ["Revenue", "10"]]
    vector_rows = [["Metric", "Q1"], ["Revenue", "11"]]
    marked = _marked_table(docling_rows)

    result = _enabled_reconcile(marked, _vector_table(vector_rows))

    assert len(result[1]) == 1
    unresolved = result[1][0]
    reconciliation = _reconciliation(unresolved)
    assert reconciliation["outcome"] == "unresolved"
    assert reconciliation["selected_candidate_id"] is None
    assert len(reconciliation["candidate_ids"]) == 2
    assert set(reconciliation["concern_codes"])
    assert all(
        type(code) is str and code.startswith("table_")
        for code in reconciliation["concern_codes"]
    )
    assert {tuple(map(tuple, rows)) for rows in _retained_rows(reconciliation)} == {
        tuple(map(tuple, docling_rows)),
        tuple(map(tuple, vector_rows)),
    }
    sidecar = unresolved["table_evidence"]
    assert sidecar["status"] == "unresolved"
    assert set(reconciliation["concern_codes"]) <= set(sidecar["concerns"])
    assert set(reconciliation["concern_codes"]) <= set(
        unresolved["parse_concerns"]
    )


def test_exact_source_grid_recovery_resolves_collapsed_low_margin_candidate() -> None:
    source_rows = [
        ["Timetable", "", ""],
        ["Stop A", "Stop B", "Stop C"],
        ["x", "1", "2"],
        ["y", "3", "4"],
    ]
    collapsed_rows = [
        ["Timetable", ""],
        ["Stop A Stop B", "Stop C"],
        ["x", "1 2"],
        ["y", "3 4"],
    ]
    marked = _marked_table(collapsed_rows)
    vector = _vector_table(source_rows)
    vector.logical_rows_recovered = True
    vector_item = _legacy_vector_item(vector)

    result = table_semantics.reconcile_table_candidates(
        {1: [deepcopy(marked), vector_item]},
        {1: [deepcopy(marked)]},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    winner = result[1][0]
    reconciliation = _reconciliation(winner)
    assert reconciliation["outcome"] == "selected"
    assert reconciliation["selection_margin"] < 0.1
    assert (winner["row_count"], winner["column_count"]) == (4, 3)
    assert winner["rows"] == source_rows
    assert winner["engine"] == "pdfplumber"


def test_low_margin_exception_requires_explicit_logical_row_recovery() -> None:
    source_rows = [
        ["Timetable", "", ""],
        ["Stop A", "Stop B", "Stop C"],
        ["x", "1", "2"],
        ["y", "3", "4"],
    ]
    collapsed_rows = [
        ["Timetable", ""],
        ["Stop A Stop B", "Stop C"],
        ["x", "1 2"],
        ["y", "3 4"],
    ]
    marked = _marked_table(collapsed_rows)
    vector = _vector_table(source_rows)

    result = table_semantics.reconcile_table_candidates(
        {1: [deepcopy(marked), _legacy_vector_item(vector)]},
        {1: [deepcopy(marked)]},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    reconciliation = _reconciliation(result[1][0])
    assert reconciliation["outcome"] == "unresolved"
    assert reconciliation["selected_candidate_id"] is None


def test_same_geometry_conflict_does_not_collapse_by_candidate_identity() -> None:
    first_rows = [["Metric", "Q1"], ["Revenue", "10"]]
    second_rows = [["Metric", "Q1"], ["Revenue", "11"]]
    first_raw = _vector_table(first_rows)
    second_raw = _vector_table(second_rows)
    first = _legacy_vector_item(first_raw)
    second = _legacy_vector_item(second_raw)
    first["id"] = "vector-candidate-first"
    second["id"] = "vector-candidate-second"
    assert first["engine"] == second["engine"] == "pdfplumber"
    assert first["bbox"] == second["bbox"]
    assert first["row_count"] == second["row_count"]
    assert first["column_count"] == second["column_count"]

    result = table_semantics.reconcile_table_candidates(
        {1: [first, second]},
        {},
        {1: [first_raw, second_raw]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    assert len(result[1]) == 1
    reconciliation = _reconciliation(result[1][0])
    assert reconciliation["outcome"] == "unresolved"
    assert reconciliation["selected_candidate_id"] is None
    assert len(reconciliation["candidate_ids"]) == 2
    assert {
        tuple(map(tuple, rows)) for rows in _retained_rows(reconciliation)
    } == {
        tuple(map(tuple, first_rows)),
        tuple(map(tuple, second_rows)),
    }
    assert "table_reconciliation_conflict" in reconciliation["concern_codes"]


def test_malformed_candidate_is_isolated_from_an_unrelated_page() -> None:
    marked = _marked_table([["Name", "Value"], ["A", "1"]])
    unrelated_raw = _vector_table(
        [["Code", "Description"], ["X", "Unrelated"]],
        page_index=2,
    )
    unrelated = _legacy_vector_item(unrelated_raw)
    unrelated_expected = _core_projection(unrelated)
    malformed = {
        "page_index": 1,
        "bbox": {"x": 0.0, "y": 10.0, "w": "wide", "h": 110.0},
        "rows": [["broken"]],
        "row_bboxes": [],
        "parse_concerns": [],
        "cell_bboxes": (),
        "geometry_inferred": False,
    }

    result = table_semantics.reconcile_table_candidates(
        {1: [deepcopy(marked)], 2: [unrelated]},
        {1: [deepcopy(marked)]},
        {1: [malformed], 2: [unrelated_raw]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    assert set(result) == {1, 2}
    assert len(result[1]) == len(result[2]) == 1
    affected = _reconciliation(result[1][0])
    assert affected["outcome"] == "singleton"
    assert affected["concern_codes"]
    assert _core_projection(result[2][0]) == unrelated_expected
    unrelated_reconciliation = _reconciliation(result[2][0])
    assert unrelated_reconciliation["outcome"] == "singleton"
    assert unrelated_reconciliation["concern_codes"] == []


def _selected_vector_reconcile(
    vector: RawTable,
    *,
    sink: dict[int, list[dict[str, Any]]] | None = None,
    vector_tables: dict[int, list[RawTable]] | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    owned_sink = {} if sink is None else sink
    candidate = pipeline._vector_table_item(
        vector,
        table_span_fidelity_enabled=True,
    )
    result = table_semantics.reconcile_table_candidates(
        {1: [candidate]},
        {},
        vector_tables or {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        selected_vector_sink=owned_sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )
    return result, owned_sink


def test_selected_vector_sink_is_source_bound_and_post_gate_sealed() -> None:
    vector = _vector_table(
        [
            ["Account", "Q1", "Q2"],
            ["Cash", "10", "11"],
            ["Total", "10", "11"],
        ],
        bbox={"x": 0.0, "y": 10.0, "w": 300.0, "h": 120.0},
    )
    reconciled, preliminary = _selected_vector_reconcile(vector)

    assert len(preliminary[1]) == 1
    assert preliminary[1][0]["source_sha256"] == _SOURCE_SHA256
    assert preliminary[1][0]["logical_rows_recovered"] is False
    assert type(preliminary[1][0]["vector_sha256"]) is str

    body_items: dict[int, list[dict[str, Any]]] = {1: []}
    gated = table_semantics.gate_table_candidates(
        reconciled,
        body_items,
        {},
        {},
        _SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    assert gated[1][0]["table_candidate_gate"]["outcome"] == "canonical_table"
    sealed: dict[int, list[dict[str, Any]]] = {9: [{"stale": True}]}
    table_semantics.finalize_selected_vector_representations(
        gated,
        preliminary,
        _SOURCE_SHA256,
        sealed,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )

    assert set(sealed) == {1}
    assert len(sealed[1]) == 1
    authority = sealed[1][0]
    assert authority["source_sha256"] == _SOURCE_SHA256
    assert authority["output_position"] == 0
    assert authority["table_candidate_gate"]["outcome"] == "canonical_table"
    assert type(authority["post_gate_table_sha256"]) is str
    assert type(authority["post_gate_authority_sha256"]) is str

    mismatched_source = {1: [{"stale": True}]}
    table_semantics.finalize_selected_vector_representations(
        gated,
        preliminary,
        "b" * 64,
        mismatched_source,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    assert mismatched_source == {}


def test_selected_vector_sink_clears_stale_state_and_rejects_gate_failure() -> None:
    vector = _vector_table(
        [["Name", "Value"], ["A", "1"]]
    )
    reconciled, preliminary = _selected_vector_reconcile(vector)
    reconciled[1][0]["bbox"]["width"] = "wide"
    reconciled[1][0]["bbox"]["w"] = "wide"
    body_items: dict[int, list[dict[str, Any]]] = {1: []}
    gated = table_semantics.gate_table_candidates(
        reconciled,
        body_items,
        {},
        {},
        _SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    assert gated[1] == []

    sealed: dict[int, list[dict[str, Any]]] = {1: [{"stale": True}]}
    table_semantics.finalize_selected_vector_representations(
        gated,
        preliminary,
        _SOURCE_SHA256,
        sealed,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    assert sealed == {}

    disabled_sink: dict[int, list[dict[str, Any]]] = {1: [{"stale": True}]}
    table_semantics.reconcile_table_candidates(
        {1: [pipeline._vector_table_item(vector)]},
        {},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=False,
        selected_vector_sink=disabled_sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )
    assert disabled_sink == {}


def test_selected_vector_sink_rejects_ambiguous_or_nonexact_raw_origin() -> None:
    rows = [["Name", "Value"], ["A", "1"]]
    first = _vector_table(rows)
    second = _vector_table(rows)
    second.cell_bboxes = tuple(
        (
            {
                "x": 0.0,
                "y": row[0]["y"],
                "w": 140.0,
                "h": row[0]["h"],
            },
            {
                "x": 140.0,
                "y": row[1]["y"],
                "w": 160.0,
                "h": row[1]["h"],
            },
        )
        for row in second.cell_bboxes
    )
    _, ambiguous_sink = _selected_vector_reconcile(
        first,
        vector_tables={1: [first, second]},
    )
    assert ambiguous_sink == {}

    shifted = _vector_table(rows)
    candidate = pipeline._vector_table_item(
        first, table_span_fidelity_enabled=True
    )
    shifted.bbox["x"] = 1.0
    shifted.row_bboxes = [
        {**box, "x": 1.0} for box in shifted.row_bboxes
    ]
    shifted.cell_bboxes = tuple(
        tuple({**box, "x": box["x"] + 1.0} for box in row)
        for row in shifted.cell_bboxes
    )
    shifted_sink: dict[int, list[dict[str, Any]]] = {}
    table_semantics.reconcile_table_candidates(
        {1: [candidate]},
        {},
        {1: [shifted]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        selected_vector_sink=shifted_sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )
    assert shifted_sink == {}


def test_selected_vector_sink_rejects_raw_table_under_wrong_page_key() -> None:
    misplaced = _vector_table(
        [["Name", "Value", "State"], ["A", "1", "open"]],
        page_index=2,
    )
    candidate = pipeline._vector_table_item(
        misplaced,
        table_span_fidelity_enabled=True,
    )
    sink: dict[int, list[dict[str, Any]]] = {}

    table_semantics.reconcile_table_candidates(
        {1: [candidate]},
        {},
        {1: [misplaced]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        selected_vector_sink=sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )

    assert sink == {}


@pytest.mark.parametrize("extra_key", ["relationships", "caption_ids", "unknown"])
def test_selected_vector_sink_rejects_extra_public_candidate_keys(
    extra_key: str,
) -> None:
    vector = _vector_table([["Name", "Value"], ["A", "1"]])
    candidate = pipeline._vector_table_item(
        vector, table_span_fidelity_enabled=True
    )
    candidate[extra_key] = [] if extra_key != "unknown" else "sidecar"
    sink: dict[int, list[dict[str, Any]]] = {}

    table_semantics.reconcile_table_candidates(
        {1: [candidate]},
        {},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        selected_vector_sink=sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )

    assert sink == {}


def test_selected_vector_sink_rejects_open_grid_or_unproved_inference() -> None:
    gap = _vector_table([["Name", "Value"], ["A", "1"]])
    gap.cell_bboxes = tuple(
        (
            row[0],
            {**row[1], "x": row[1]["x"] + 1.0, "w": row[1]["w"] - 1.0},
        )
        for row in gap.cell_bboxes
    )
    _, gap_sink = _selected_vector_reconcile(gap)
    assert gap_sink == {}

    inferred = _vector_table([["Name", "Value"], ["A", "1"]])
    inferred.geometry_inferred = True
    inferred.logical_rows_recovered = False
    _, unproved_sink = _selected_vector_reconcile(inferred)
    assert unproved_sink == {}

    inferred.logical_rows_recovered = True
    _, proved_sink = _selected_vector_reconcile(inferred)
    assert len(proved_sink[1]) == 1
    assert proved_sink[1][0]["logical_rows_recovered"] is True


def test_selected_vector_projection_failure_cannot_change_public_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _vector_table(
        [["Name", "Value"], ["A", "1"]], page_index=1
    )
    second = _vector_table(
        [["Code", "Description"], ["B", "two"]], page_index=2
    )
    merged = {
        1: [pipeline._vector_table_item(first, table_span_fidelity_enabled=True)],
        2: [pipeline._vector_table_item(second, table_span_fidelity_enabled=True)],
    }
    raw = {1: [first], 2: [second]}
    expected = table_semantics.reconcile_table_candidates(
        deepcopy(merged),
        {},
        raw,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    def refuse_optional_projection(*_args: object, **_kwargs: object) -> object:
        raise TimeoutError("optional vector authority deadline")

    monkeypatch.setattr(
        table_semantics,
        "_selected_vector_authority_projection",
        refuse_optional_projection,
    )
    sink: dict[int, list[dict[str, Any]]] = {1: [{"stale": True}]}
    observed = table_semantics.reconcile_table_candidates(
        deepcopy(merged),
        {},
        raw,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        selected_vector_sink=sink,
        selected_vector_source_sha256=_SOURCE_SHA256,
    )

    assert observed == expected
    assert sink == {}


def test_merge_tables_retains_overlap_only_when_reconciliation_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [["Name", "Value"], ["A", "1"]]
    docling = _legacy_docling_item(rows)
    vector = _vector_table(rows)
    observed: dict[bool, list[str]] = {}

    def capture(
        merged: dict[int, list[dict[str, Any]]],
        _docling_tables: object,
        _vector_tables: object,
        *,
        table_span_fidelity_enabled: bool = False,
        table_evidence_reconciliation_enabled: bool = False,
    ) -> dict[int, list[dict[str, Any]]]:
        assert table_span_fidelity_enabled is True
        observed[table_evidence_reconciliation_enabled] = [
            table["engine"] for table in merged[1]
        ]
        return merged

    monkeypatch.setattr(
        table_semantics,
        "reconcile_table_candidates",
        capture,
    )

    disabled = pipeline._merge_tables(
        {1: [deepcopy(docling)]},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=False,
    )
    enabled = pipeline._merge_tables(
        {1: [deepcopy(docling)]},
        {1: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )

    assert observed[False] == ["docling"]
    assert [table["engine"] for table in disabled[1]] == ["docling"]
    assert observed[True] == ["docling", "pdfplumber"]
    assert [table["engine"] for table in enabled[1]] == [
        "docling",
        "pdfplumber",
    ]


def test_public_json_and_markdown_expose_additive_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api as api_module
    from app.main import app
    from tests.contract.test_p04_us01_table_api_schema import (
        _bound_payload,
        _production_table,
    )

    table = _production_table()
    reconciled = table_semantics.reconcile_table_candidates(
        {1: [deepcopy(table)]},
        {1: [deepcopy(table)]},
        {1: [_vector_table(table["rows"])]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )[1][0]
    result = ParseResult.model_validate(
        _bound_payload(reconciled, source_sha256="a" * 64)
    )
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: result,
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% P04-US02 table\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200
    public_table = response.json()["pages"][0]["items"][0]
    assert set(public_table["table_evidence"]) == {
        "policy_id",
        "version",
        "scope",
        "status",
        "table_id",
        "candidate_id",
        "page_index",
        "grid",
        "slots",
        "source_objects",
        "evidence",
        "span_decisions",
        "representation_custody",
        "reconciliation",
        "gate",
        "continuation",
        "concerns",
    }
    assert public_table["table_evidence"]["scope"] == [
        "P04-US01",
        "P04-US02",
    ]
    assert set(
        public_table["table_evidence"]["reconciliation"]
    ) == _RECONCILIATION_KEYS
    markdown = to_markdown(result)
    assert public_table["rows"][0][0] in markdown
