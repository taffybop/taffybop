"""Focused release-first checks for P04-US04 table candidate gating."""

from __future__ import annotations

from copy import deepcopy
from inspect import getsource
from math import isfinite
from typing import Any

from app.services import pipeline, table_semantics
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _raw_cell,
    _raw_table,
    _seal,
)
from tests.stories.phase_04.test_p04_us02_table_reconciliation import (
    _core_projection,
    _enabled_reconcile,
    _legacy_vector_item,
    _marked_table,
    _vector_table,
)


_SOURCE_SHA256 = "a" * 64
_GATE_KEYS = {
    "decision_id",
    "candidate_id",
    "outcome",
    "owner_item_ids",
    "feature_scores",
    "evidence_ids",
    "concern_codes",
}


def _reconciled_marked_table(
    rows: list[list[str]],
    *,
    source_headers: bool = True,
) -> dict[str, Any]:
    if source_headers:
        marked = _marked_table(rows)
    else:
        cells = [
            _raw_cell(
                row_index,
                column_index,
                text,
                column_header=False,
                reference_suffix=f"borderless-{row_index}-{column_index}",
            )
            for row_index, row in enumerate(rows)
            for column_index, text in enumerate(row)
        ]
        marked = _seal(
            _raw_table(
                len(rows),
                len(rows[0]),
                cells,
                self_ref="#/tables/borderless",
            ),
            finalize=False,
        )
    return _enabled_reconcile(marked, _vector_table(rows))[1][0]


def _reconciled_legacy_table(
    rows: list[list[str]],
    *,
    page_index: int,
) -> dict[str, Any]:
    raw = _vector_table(rows, page_index=page_index)
    legacy = _legacy_vector_item(raw)
    return table_semantics.reconcile_table_candidates(
        {page_index: [legacy]},
        {},
        {page_index: [raw]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )[page_index][0]


def _gate_candidates(
    tables: dict[int, list[dict[str, Any]]],
    body_items: dict[int, list[dict[str, Any]]],
    *,
    enabled: bool = True,
) -> dict[int, list[dict[str, Any]]]:
    return table_semantics.gate_table_candidates(
        tables,
        body_items,
        {},
        {},
        _SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=enabled,
    )


def _gate(table: dict[str, Any]) -> dict[str, Any]:
    sidecar = table.get("table_evidence")
    value = (
        sidecar.get("gate")
        if type(sidecar) is dict
        else table.get("table_candidate_gate")
    )
    assert type(value) is dict
    assert set(value) == _GATE_KEYS
    assert type(value["decision_id"]) is str and value["decision_id"]
    assert type(value["candidate_id"]) is str and value["candidate_id"]
    assert value["outcome"] in {
        "canonical_table",
        "form",
        "key_value",
        "chart",
        "visual",
        "unresolved",
        "structural_failure",
    }
    assert type(value["owner_item_ids"]) is list
    assert value["owner_item_ids"] == sorted(set(value["owner_item_ids"]))
    assert all(
        type(owner_id) is str and owner_id for owner_id in value["owner_item_ids"]
    )
    assert type(value["feature_scores"]) is dict
    assert value["feature_scores"]
    assert all(
        type(name) is str
        and name
        and type(score) in (int, float)
        and type(score) is not bool
        and isfinite(float(score))
        for name, score in value["feature_scores"].items()
    )
    assert type(value["evidence_ids"]) is list
    assert type(value["concern_codes"]) is list
    assert len(value["concern_codes"]) == len(set(value["concern_codes"]))

    bbox = table.get("bbox")
    width = bbox.get("width", bbox.get("w")) if type(bbox) is dict else None
    height = bbox.get("height", bbox.get("h")) if type(bbox) is dict else None
    retains_source_geometry = (
        type(bbox) is dict
        and type(bbox.get("x")) in (int, float)
        and type(bbox.get("y")) in (int, float)
        and type(width) in (int, float)
        and type(height) in (int, float)
        and float(width) > 0
        and float(height) > 0
    )
    has_geometry_feature = any(
        token in name.casefold()
        for name in value["feature_scores"]
        for token in ("geometry", "bbox", "overlap")
    )
    assert retains_source_geometry or has_geometry_feature
    return value


def _alternative(body_items: dict[int, list[dict[str, Any]]], page: int = 1):
    alternatives = [
        item
        for item in body_items.get(page, [])
        if item.get("type") == "table_candidate"
    ]
    assert len(alternatives) == 1
    alternative = alternatives[0]
    assert "table_evidence" not in alternative
    return alternative


def _chart() -> dict[str, Any]:
    return {
        "id": "chart-1",
        "type": "chart",
        "label": "chart",
        "value": "Revenue by quarter",
        "md": "Revenue by quarter",
        "bbox": {
            "x": 0.0,
            "y": 10.0,
            "width": 300.0,
            "height": 110.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": 1.0,
        "parse_concerns": [],
    }


def _form() -> dict[str, Any]:
    return {
        "id": "form-1",
        "type": "form",
        "label": "form",
        "value": {
            "fields": [{"key": "Name", "value": "Example"}],
            "unlinked_cells": [],
        },
        "md": "**Name:** Example",
        "bbox": {
            "x": 0.0,
            "y": 10.0,
            "width": 300.0,
            "height": 110.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": 1.0,
        "parse_concerns": [],
        "form_group": {"id": "form-group-1", "canonical_mode": "active"},
    }


def test_flag_off_returns_exact_table_identity_and_does_not_touch_body() -> None:
    table = _reconciled_marked_table(
        [["Account", "Q1", "Q2"], ["Cash", "10", "11"]]
    )
    tables = {1: [table]}
    chart = _chart()
    body_items = {1: [chart]}
    expected_tables = deepcopy(tables)
    expected_body = deepcopy(body_items)

    returned = _gate_candidates(tables, body_items, enabled=False)

    assert returned is tables
    assert returned == expected_tables
    assert body_items == expected_body
    assert returned[1][0]["table_evidence"]["gate"] is None
    assert "table_candidate_gate" not in returned[1][0]


def test_true_source_supported_table_is_canonical_and_deterministic() -> None:
    table = _reconciled_marked_table(
        [
            ["Account", "Q1", "Q2"],
            ["Cash", "10", "11"],
            ["Total", "10", "11"],
        ]
    )
    expected_projection = _core_projection(table)

    first = _gate_candidates({1: [deepcopy(table)]}, {1: []})
    second = _gate_candidates({1: [deepcopy(table)]}, {1: []})

    assert len(first[1]) == len(second[1]) == 1
    first_table = first[1][0]
    second_table = second[1][0]
    assert _core_projection(first_table) == expected_projection
    first_gate = _gate(first_table)
    second_gate = _gate(second_table)
    assert first_gate == second_gate
    assert first_gate["outcome"] == "canonical_table"
    assert first_gate["owner_item_ids"] == []
    assert first_gate["candidate_id"] == table["table_evidence"]["candidate_id"]
    assert "P04-US04" in first_table["table_evidence"]["scope"]


def test_chart_overlap_suppresses_table_and_retains_typed_owner() -> None:
    table = _reconciled_marked_table(
        [["Label", "Value"], ["Alpha", "10"], ["Beta", "20"]]
    )
    chart = _chart()
    expected_chart = deepcopy(chart)
    body_items = {1: [chart]}

    result = _gate_candidates({1: [table]}, body_items)

    assert result.get(1, []) == []
    assert body_items[1][0] == expected_chart
    alternative = _alternative(body_items)
    gate = _gate(alternative)
    assert gate["outcome"] == "chart"
    assert gate["owner_item_ids"] == ["chart-1"]
    assert "table_candidate_chart_owned" in gate["concern_codes"]


def test_form_owned_region_remains_form_and_table_is_only_an_alternative() -> None:
    table = _reconciled_marked_table(
        [["Field", "Value"], ["Name", "Example"], ["Date", "2026-08-12"]]
    )
    form = _form()
    expected_form = deepcopy(form)
    body_items = {1: [form]}

    result = _gate_candidates({1: [table]}, body_items)

    assert result.get(1, []) == []
    assert body_items[1][0] == expected_form
    alternative = _alternative(body_items)
    gate = _gate(alternative)
    assert gate["outcome"] == "form"
    assert gate["owner_item_ids"] == ["form-1"]
    assert "table_candidate_form_owned" in gate["concern_codes"]


def test_borderless_two_column_key_value_is_retained_without_fake_headers() -> None:
    rows = [
        ["Rated voltage", "5 V"],
        ["Supply current", "2 A"],
        ["Temperature", "85 C"],
    ]
    table = _reconciled_marked_table(rows, source_headers=False)
    assert all(not cell["column_header"] for cell in table["cells"])
    body_items: dict[int, list[dict[str, Any]]] = {1: []}

    result = _gate_candidates({1: [table]}, body_items)

    assert result.get(1, []) == []
    alternative = _alternative(body_items)
    gate = _gate(alternative)
    assert gate["outcome"] == "key_value"
    assert "table_candidate_key_value_alternative" in gate["concern_codes"]
    assert alternative["rows"] == rows
    assert alternative["column_count"] == 2
    assert all(not cell["column_header"] for cell in alternative["cells"])


def test_two_row_headerless_aligned_prose_is_not_forced_to_canonical_table() -> None:
    rows = [
        ["Prepared by", "Finance"],
        ["Reviewed by", "Audit"],
    ]
    table = _reconciled_legacy_table(rows, page_index=1)
    assert table["cells"] == []
    body_items: dict[int, list[dict[str, Any]]] = {1: []}

    result = _gate_candidates({1: [table]}, body_items)

    assert result.get(1, []) == []
    alternative = _alternative(body_items)
    gate = _gate(alternative)
    assert gate["outcome"] in {"key_value", "unresolved"}
    assert alternative["rows"] == rows
    assert not any(
        cell.get("column_header") is True or cell.get("row_header") is True
        for cell in alternative.get("cells", [])
        if type(cell) is dict
    )


def test_unresolved_reconciliation_cannot_be_forced_through_the_gate() -> None:
    docling_rows = [["Metric", "Q1"], ["Revenue", "10"]]
    conflicting_rows = [["Metric", "Q1"], ["Revenue", "11"]]
    unresolved = _enabled_reconcile(
        _marked_table(docling_rows),
        _vector_table(conflicting_rows),
    )[1][0]
    assert unresolved["table_evidence"]["status"] == "unresolved"
    body_items: dict[int, list[dict[str, Any]]] = {1: []}

    result = _gate_candidates({1: [unresolved]}, body_items)

    assert result.get(1, []) == []
    alternative = _alternative(body_items)
    gate = _gate(alternative)
    assert gate["outcome"] == "unresolved"
    assert "table_candidate_ownership_ambiguous" in gate["concern_codes"]
    assert set(gate["concern_codes"]) <= set(alternative["parse_concerns"])


def test_malformed_candidate_isolated_without_corrupting_other_page() -> None:
    good = _reconciled_marked_table(
        [["Account", "Q1", "Q2"], ["Cash", "10", "11"]]
    )
    malformed = _reconciled_legacy_table(
        [["Broken", "Value"], ["A", "1"]],
        page_index=2,
    )
    malformed["bbox"]["w"] = "wide"
    malformed["bbox"]["width"] = "wide"
    body_items: dict[int, list[dict[str, Any]]] = {1: [], 2: []}

    result = _gate_candidates(
        {1: [deepcopy(good)], 2: [malformed]},
        body_items,
    )

    assert len(result[1]) == 1
    assert _gate(result[1][0])["outcome"] == "canonical_table"
    assert result.get(2, []) == []
    alternative = _alternative(body_items, page=2)
    malformed_gate = _gate(alternative)
    assert malformed_gate["outcome"] == "structural_failure"
    assert "table_candidate_structure_invalid" in malformed_gate["concern_codes"]
    assert body_items[1] == []


def test_shared_pipeline_calls_gate_after_reconciliation_before_suppression() -> None:
    source = getsource(pipeline._analyze_shared_pages)
    merge_position = source.index("tables = _merge_tables(")
    gate_position = source.index("tables = table_semantics.gate_table_candidates(")
    ocr_suppression_position = source.index("_supplement_unrepresented_page_ocr(")
    body_merge_position = source.index("_merge_body_items(")

    assert merge_position < gate_position < ocr_suppression_position
    assert gate_position < body_merge_position
    gate_call = source[gate_position:ocr_suppression_position]
    assert (
        "table_candidate_gate_enabled="
        "context.settings.table_candidate_gate_enabled"
    ) in gate_call.replace(" ", "").replace("\n", "")
