"""Focused release-first checks for P04-US03 continued tables."""

from __future__ import annotations

from copy import deepcopy
from csv import reader as csv_reader
from inspect import getsource
from io import StringIO
from typing import Any

import pytest

from app.services import pipeline, table_semantics
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _raw_cell,
    _raw_table,
    _seal,
)
from tests.stories.phase_04.test_p04_us02_table_reconciliation import (
    _core_projection,
    _vector_table,
)


_SOURCE_SHA256 = "a" * 64
_CONTINUATION_KEYS = {
    "merge_id",
    "outcome",
    "source_table_ids",
    "continued_from",
    "page_indexes",
    "signal_ids",
    "repeated_header_cell_ids",
    "evidence_ids",
    "concern_codes",
}


def _gated_table(
    rows: list[list[str]],
    *,
    page_index: int,
    caption_id: str | None = None,
    table_reference: int | None = None,
    table_width: float = 300.0,
    table_y: float = 10.0,
    table_height: float = 110.0,
) -> dict[str, Any]:
    reference = page_index - 1 if table_reference is None else table_reference
    cells = [
        _raw_cell(
            row_index,
            column_index,
            text,
            column_header=row_index == 0,
            reference_suffix=(
                f"p{page_index}-t{reference}-{row_index}-{column_index}"
            ),
        )
        for row_index, row in enumerate(rows)
        for column_index, text in enumerate(row)
    ]
    raw = _raw_table(
        len(rows),
        len(rows[0]),
        cells,
        self_ref=f"#/tables/{reference}",
    )
    vertical_shift = table_y - 10.0
    for cell in raw["data"]["table_cells"]:
        bbox = cell.get("bbox")
        if type(bbox) is dict:
            bbox["t"] = float(bbox["t"]) + vertical_shift
            bbox["b"] = float(bbox["b"]) + vertical_shift
    raw["prov"][0]["bbox"]["r"] = table_width
    raw["prov"][0]["bbox"]["t"] = 120.0 - table_y
    raw["prov"][0]["bbox"]["b"] = 120.0 - table_y - table_height
    marked = _seal(
        raw,
        finalize=False,
        physical_page_index=page_index,
    )
    if table_reference is not None:
        marked["id"] = f"predecessor-table-{page_index}-{reference}"
        snapshot = marked.get("_p04_predecessor_snapshot")
        if type(snapshot) is dict:
            snapshot["id"] = marked["id"]
    if caption_id is not None:
        marked["caption_ids"] = [caption_id]
    vector = _vector_table(
        rows,
        page_index=page_index,
        bbox={
            "x": 0.0,
            "y": table_y,
            "w": table_width,
            "h": table_height,
        },
    )
    reconciled = table_semantics.reconcile_table_candidates(
        {page_index: [deepcopy(marked)]},
        {page_index: [deepcopy(marked)]},
        {page_index: [vector]},
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
    )[page_index][0]
    body_items: dict[int, list[dict[str, Any]]] = {page_index: []}
    gated = table_semantics.gate_table_candidates(
        {page_index: [reconciled]},
        body_items,
        {},
        {},
        _SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )[page_index][0]
    assert gated["table_evidence"]["gate"]["outcome"] == "canonical_table"
    assert body_items[page_index] == []
    gated.pop("_p04_predecessor_snapshot", None)
    return gated


def _page(page_index: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "page_index": page_index,
        "page_number": page_index,
        "page_label": str(page_index),
        "page_width": 300.0,
        "page_height": 120.0,
        "unit": "pt",
        "success": True,
        "items": items,
        "warnings": [],
    }


def _verified_pages() -> list[dict[str, Any]]:
    first = _gated_table(
        [
            ["Account", "Amount"],
            ["Cash", "10"],
            ["Receivables", "20"],
        ],
        page_index=1,
        caption_id="statement-caption",
    )
    second = _gated_table(
        [
            ["Account", "Amount"],
            ["Debt", "5"],
            ["Total", "25"],
        ],
        page_index=2,
        caption_id="statement-caption",
    )
    return [_page(1, [first]), _page(2, [second])]


def _merge(pages: list[dict[str, Any]], *, enabled: bool = True) -> None:
    returned = table_semantics.merge_continued_tables(
        pages,
        _SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
        table_multi_page_merge_enabled=enabled,
    )
    assert returned is None


def _continuation(table: dict[str, Any]) -> dict[str, Any] | None:
    sidecar = table.get("table_evidence")
    value = (
        sidecar.get("continuation")
        if type(sidecar) is dict
        else table.get("table_continuation")
    )
    if value is None:
        return None
    assert type(value) is dict
    assert set(value) == _CONTINUATION_KEYS
    assert type(value["merge_id"]) is str and value["merge_id"]
    assert value["outcome"] in {
        "page_local",
        "merged",
        "unresolved",
        "ineligible",
    }
    assert type(value["source_table_ids"]) is list
    assert value["source_table_ids"]
    assert len(value["source_table_ids"]) == len(set(value["source_table_ids"]))
    assert value["continued_from"] is None or (
        type(value["continued_from"]) is str and value["continued_from"]
    )
    assert type(value["page_indexes"]) is list
    assert value["page_indexes"] == sorted(set(value["page_indexes"]))
    for key in (
        "signal_ids",
        "repeated_header_cell_ids",
        "evidence_ids",
        "concern_codes",
    ):
        assert type(value[key]) is list
        assert len(value[key]) == len(set(value[key]))
    return value


def _all_items(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for page in pages:
        items.extend(
            item for item in page.get("items", []) if type(item) is dict
        )
        items.extend(
            item
            for item in page.get("derived_tables", [])
            if type(item) is dict
        )
    return items


def _derived_merge(
    pages: list[dict[str, Any]],
    original_ids: set[str],
) -> dict[str, Any]:
    matches = []
    for item in _all_items(pages):
        decision = _continuation(item)
        if (
            item.get("id") not in original_ids
            and item.get("type") == "table"
            and "table_evidence" not in item
            and type(item.get("derived_from_table_ids")) is list
            and type(decision) is dict
            and decision["outcome"] == "merged"
        ):
            matches.append(item)
    assert len(matches) == 1
    return matches[0]


def _original_tables_by_id(
    pages: list[dict[str, Any]],
    original_ids: set[str],
) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in _all_items(pages)
        if item.get("id") in original_ids
    }


def test_flag_off_is_exact_identity_and_keeps_both_tables_page_local() -> None:
    pages = _verified_pages()
    expected = deepcopy(pages)
    first_page = pages[0]
    first_table = pages[0]["items"][0]

    _merge(pages, enabled=False)

    assert pages == expected
    assert pages[0] is first_page
    assert pages[0]["items"][0] is first_table
    assert all(
        item["table_evidence"]["continuation"] is None
        for page in pages
        for item in page["items"]
    )


def test_verified_adjacent_pair_creates_one_page_preserving_derived_merge() -> None:
    pages = _verified_pages()
    originals = [page["items"][0] for page in pages]
    original_ids = {table["id"] for table in originals}
    original_projection = {
        table["id"]: _core_projection(table) for table in originals
    }
    source_table_ids = {
        table["table_evidence"]["table_id"] for table in originals
    }
    second_header_ids = {
        cell["id"]
        for cell in originals[1]["cells"]
        if cell["column_header"]
    }

    _merge(pages)

    retained = _original_tables_by_id(pages, original_ids)
    assert set(retained) == original_ids
    assert {
        table_id: _core_projection(table) for table_id, table in retained.items()
    } == original_projection
    assert [item["id"] for item in pages[0]["items"][:-1]] == [originals[0]["id"]]
    assert [item["id"] for item in pages[1]["items"]] == [originals[1]["id"]]
    derived = _derived_merge(pages, original_ids)
    assert pages[0]["items"][-1] is derived
    assert "table_evidence" not in derived
    assert set(derived["derived_from_table_ids"]) == source_table_ids
    decision = _continuation(derived)
    assert decision is not None
    assert set(decision["source_table_ids"]) == source_table_ids
    assert decision["continued_from"] == originals[0]["table_evidence"]["table_id"]
    assert decision["page_indexes"] == [1, 2]
    assert len(decision["signal_ids"]) >= 2
    assert set(decision["repeated_header_cell_ids"]) == second_header_ids
    assert decision["concern_codes"] == []
    for table in retained.values():
        local_decision = _continuation(table)
        assert local_decision is not None
        assert local_decision["outcome"] == "page_local"
        assert table["table_evidence"]["scope"] == [
            "P04-US01",
            "P04-US02",
            "P04-US04",
            "P04-US03",
        ]
    assert derived["rows"] == [
        ["Account", "Amount"],
        ["Cash", "10"],
        ["Receivables", "20"],
        ["Debt", "5"],
        ["Total", "25"],
    ]

    page_local_cells = [
        cell for table in originals for cell in table["cells"]
    ]
    for cell in derived["cells"]:
        assert cell["page_index"] in {1, 2}
        assert type(cell["bbox"]) is dict
        assert cell["evidence_ids"]
        assert cell["source_object_ids"]
        assert any(
            source["page_index"] == cell["page_index"]
            and source["column"] == cell["column"]
            and source["text"] == cell["text"]
            and source["bbox"] == cell["bbox"]
            and source["evidence_ids"] == cell["evidence_ids"]
            and source["source_object_ids"] == cell["source_object_ids"]
            for source in page_local_cells
        )
    assert sum(cell["page_index"] == 1 for cell in derived["cells"]) == 6
    assert sum(cell["page_index"] == 2 for cell in derived["cells"]) == 4


def test_derived_rows_json_html_markdown_and_csv_share_one_grid() -> None:
    pages = _verified_pages()
    original_ids = {page["items"][0]["id"] for page in pages}

    _merge(pages)

    derived = _derived_merge(pages, original_ids)
    rows = derived["rows"]
    assert derived["value"] == rows
    assert list(csv_reader(StringIO(derived["csv"]))) == rows
    assert derived["md"] == derived["html"]
    assert derived["html"].startswith("<table>")
    assert derived["html"].endswith("</table>")
    assert derived["html"].count("<tr>") == len(rows)
    assert derived["html"].count("Account") == 1
    assert derived["csv"].count("Account") == 1


def test_two_continuation_chains_share_page_with_contiguous_public_order() -> None:
    first_account = _gated_table(
        [["Account", "Amount"], ["Cash", "10"]],
        page_index=1,
        table_reference=0,
    )
    second_account = _gated_table(
        [["Account", "Amount"], ["Debt", "5"]],
        page_index=2,
        table_reference=1,
    )
    first_product = _gated_table(
        [["Product", "Price"], ["Book", "7"]],
        page_index=1,
        table_reference=2,
    )
    second_product = _gated_table(
        [["Product", "Price"], ["Pen", "2"]],
        page_index=2,
        table_reference=3,
    )
    for reading_order, table in enumerate((first_account, first_product)):
        table["reading_order"] = reading_order
    for reading_order, table in enumerate((second_account, second_product)):
        table["reading_order"] = reading_order
    pages = [
        _page(1, [first_account, first_product]),
        _page(2, [second_account, second_product]),
    ]

    _merge(pages)

    derived = [
        item
        for item in pages[0]["items"]
        if type(item.get("table_continuation")) is dict
        and item["table_continuation"].get("outcome") == "merged"
    ]
    assert len(derived) == 2
    assert [item["reading_order"] for item in pages[0]["items"]] == [0, 1, 2, 3]
    assert [item["reading_order"] for item in derived] == [2, 3]

    from app.models import ParseResult
    from tests.contract.test_p04_us01_table_api_schema import (
        _with_bound_canonical,
    )

    payload = {
        "schema_version": "1.0",
        "document": {
            "filename": "continued-tables.pdf",
            "mime_type": "application/pdf",
            "sha256": _SOURCE_SHA256,
            "page_count": 2,
        },
        "pages": pages,
        "processing": {
            "engine": "docling",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }
    public_result = ParseResult.model_validate(_with_bound_canonical(payload))
    assert [item.reading_order for item in public_result.pages[0].items] == [
        0,
        1,
        2,
        3,
    ]


def test_unrelated_adjacent_tables_remain_local_with_incompatible_concern() -> None:
    first = _gated_table(
        [["Account", "Amount"], ["Cash", "10"]],
        page_index=1,
        caption_id="balance-sheet",
    )
    second = _gated_table(
        [
            ["Region", "Units", "Margin"],
            ["North", "8", "20%"],
        ],
        page_index=2,
        caption_id="sales-summary",
    )
    pages = [_page(1, [first]), _page(2, [second])]
    original_ids = {first["id"], second["id"]}

    _merge(pages)

    assert set(_original_tables_by_id(pages, original_ids)) == original_ids
    assert not any(
        type(_continuation(item)) is dict
        and _continuation(item)["outcome"] == "merged"
        for item in _all_items(pages)
    )
    decisions = [
        decision
        for item in _all_items(pages)
        if (decision := _continuation(item)) is not None
    ]
    assert decisions
    assert any(
        decision["outcome"] == "ineligible"
        and "table_continuation_incompatible" in decision["concern_codes"]
        for decision in decisions
    )


def test_one_signal_pair_stays_local_with_ambiguity_concern() -> None:
    rows_one = [["Account", "Amount"], ["Cash", "10"]]
    rows_two = [["Account", "Amount"], ["Debt", "5"]]
    first = _gated_table(
        rows_one,
        page_index=1,
        table_width=300.0,
        table_y=10.0,
        table_height=40.0,
    )
    second = _gated_table(
        rows_two,
        page_index=2,
        table_width=160.0,
        table_y=60.0,
        table_height=40.0,
    )
    pages = [_page(1, [first]), _page(2, [second])]
    original_ids = {first["id"], second["id"]}

    _merge(pages)

    assert set(_original_tables_by_id(pages, original_ids)) == original_ids
    assert not any(
        type(_continuation(item)) is dict
        and _continuation(item)["outcome"] == "merged"
        for item in _all_items(pages)
    )
    decisions = [
        decision
        for item in _all_items(pages)
        if (decision := _continuation(item)) is not None
    ]
    assert any(
        decision["outcome"] == "unresolved"
        and "table_continuation_ambiguous" in decision["concern_codes"]
        for decision in decisions
    )


@pytest.mark.parametrize(
    "outcome",
    ["chart", "form", "unresolved", "structural_failure"],
)
def test_noncanonical_gate_outcome_never_enters_continuation_scoring(
    outcome: str,
) -> None:
    first = _gated_table(
        [["Account", "Amount"], ["Cash", "10"]],
        page_index=1,
    )
    second = _gated_table(
        [["Account", "Amount"], ["Debt", "5"]],
        page_index=2,
    )
    alternative = deepcopy(second)
    sidecar = alternative.pop("table_evidence")
    alternative["candidate_table_evidence"] = sidecar
    alternative["type"] = "table_candidate"
    alternative["table_candidate_gate"] = deepcopy(sidecar["gate"])
    alternative["table_candidate_gate"]["outcome"] = outcome
    pages = [_page(1, [first]), _page(2, [alternative])]
    expected_alternative = deepcopy(alternative)

    _merge(pages)

    assert pages[1]["items"][0] == expected_alternative
    assert not any(
        type(_continuation(item)) is dict
        and _continuation(item)["outcome"] == "merged"
        for item in _all_items(pages)
    )


def test_malformed_third_page_does_not_block_unrelated_verified_merge() -> None:
    pages = _verified_pages()
    original_ids = {page["items"][0]["id"] for page in pages}
    malformed = {
        "id": "malformed-table-3",
        "type": "table",
        "bbox": {"x": 0.0, "y": 0.0, "width": "wide", "height": 10.0},
        "rows": "not-a-grid",
        "cells": ["not-a-cell"],
        "row_count": 1,
        "column_count": 1,
        "table_evidence": {
            "gate": {"outcome": "canonical_table"},
        },
    }
    pages.append(_page(3, [malformed]))

    _merge(pages)

    derived = _derived_merge(pages, original_ids)
    decision = _continuation(derived)
    assert decision is not None
    assert decision["page_indexes"] == [1, 2]
    assert any(
        item.get("id") == "malformed-table-3" for item in _all_items(pages)
    )


def test_shared_pipeline_runs_continuation_after_page_local_seal() -> None:
    source = getsource(pipeline._analyze_shared_pages)
    seal_position = source.index("seal_table_pages(")
    merge_position = source.index("table_semantics.merge_continued_tables(")

    assert seal_position < merge_position
    merge_call = source[merge_position:]
    normalized = merge_call.replace(" ", "").replace("\n", "")
    assert (
        "table_multi_page_merge_enabled="
        "context.settings.table_multi_page_merge_enabled"
    ) in normalized
    assert (
        "table_candidate_gate_enabled="
        "context.settings.table_candidate_gate_enabled"
    ) in normalized
