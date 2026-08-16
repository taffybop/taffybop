"""Independent runtime contracts for P04-US01 table semantics.

These tests exercise the production span-fidelity overlay only.  Candidate
reconciliation, ownership gating, and continued-table merging belong to later
stories and are intentionally never enabled here.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import random
import struct
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from app.models import ContentItem
from app.services import pipeline as document_pipeline
from app.services import table_semantics
from app.services.pipeline import (
    _apply_image_provenance_and_units,
    _docling_table_item,
    _enrich_ocr_confidence,
    _merge_body_items,
    _merge_tables,
    _normalize_docling_body,
    _supplement_unrepresented_raster_ocr,
)
from app.services.ocr import ImageRegion, OCRLine
from app.services.table_semantics import (
    _restore_all_table_predecessors,
    detach_table_overlays_for_phase03,
    finalize_table_pages,
    prepare_docling_table,
    prepare_docling_table_input,
    prepare_vector_table,
    replay_table_semantics,
    rebind_table_overlays_after_phase03,
    replace_marked_table_text,
    seal_table_pages,
    validate_table_semantics,
)


SOURCE_SHA256 = "a" * 64

SIDECAR_KEYS = {
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
CELL_KEYS = {
    "id",
    "row",
    "column",
    "row_span",
    "col_span",
    "text",
    "column_header",
    "row_header",
    "row_section",
    "bbox",
    "source",
    "page_index",
    "evidence_ids",
    "source_object_ids",
    "span_decision_id",
    "confidence_dimensions",
}
GRID_KEYS = {"row_count", "column_count", "cell_ids"}
SLOT_KEYS = {
    "id",
    "row",
    "column",
    "kind",
    "cell_id",
    "covered_by_cell_id",
}
SOURCE_OBJECT_KEYS = {
    "id",
    "engine",
    "object_type",
    "page_index",
    "raw_ref",
    "content_sha256",
}
EVIDENCE_KEYS = {
    "id",
    "method",
    "dimension",
    "page_index",
    "bbox",
    "source_object_ids",
    "confidence",
    "content_sha256",
}
SPAN_DECISION_KEYS = {
    "id",
    "cell_id",
    "claimed_row_span",
    "claimed_col_span",
    "emitted_row_span",
    "emitted_col_span",
    "outcome",
    "evidence_ids",
    "concern_codes",
}
REPRESENTATION_CUSTODY_KEYS = {
    "serializer_policy_id",
    "grid_shape",
    "cells_sha256",
    "rows_sha256",
    "html_sha256",
    "markdown_sha256",
    "csv_sha256",
}
CONFIDENCE_DIMENSION_KEYS = {"text", "geometry", "structure", "header"}
PUBLIC_PROJECTION_KEYS = (
    "rows",
    "cells",
    "value",
    "html",
    "md",
    "csv",
    "row_count",
    "column_count",
)


def _sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _representation_number_projection(value: object) -> object:
    if value is None or type(value) in (bool, str):
        return value
    if type(value) in (int, float):
        numeric = float(value)
        if numeric == 0.0:
            numeric = 0.0
        return {"$p04_f64": struct.pack(">d", numeric).hex()}
    if type(value) is list:
        return [_representation_number_projection(item) for item in value]
    assert type(value) is dict
    return {
        key: _representation_number_projection(value[key])
        for key in sorted(value)
    }


def _representation_sha256(value: object) -> str:
    return _canonical_sha256(_representation_number_projection(value))


def _raw_cell(
    row: int,
    column: int,
    text: str,
    *,
    row_span: int = 1,
    col_span: int = 1,
    bbox: bool = True,
    column_header: bool = False,
    row_header: bool = False,
    row_section: bool = False,
    reference_suffix: str | None = None,
) -> dict[str, Any]:
    left = float(column * 50)
    top = float(row * 20 + 10)
    cell: dict[str, Any] = {
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
        "ref": {
            "$ref": (
                "#/texts/"
                f"{reference_suffix if reference_suffix is not None else f'{row}-{column}'}"
            )
        },
    }
    if bbox:
        cell["bbox"] = {
            "l": left,
            "t": top,
            "r": left + float(50 * col_span),
            "b": top + float(20 * row_span),
            "coord_origin": "TOPLEFT",
        }
    return cell


def _raw_table(
    row_count: int,
    column_count: int,
    cells: list[dict[str, Any]],
    *,
    self_ref: str = "#/tables/0",
) -> dict[str, Any]:
    return {
        "self_ref": self_ref,
        "label": "table",
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0.0,
                    "t": 110.0,
                    "r": 300.0,
                    "b": 0.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": row_count,
            "num_cols": column_count,
            "table_cells": cells,
        },
    }


def _repeated_table() -> dict[str, Any]:
    cells = [
        _raw_cell(
            row,
            column,
            "United States" if column == 0 else str(row),
            column_header=row == 0,
        )
        for row in range(5)
        for column in range(2)
    ]
    return _raw_table(5, 2, cells)


def _spanned_table() -> dict[str, Any]:
    return _raw_table(
        2,
        3,
        [
            _raw_cell(
                0,
                0,
                "Years ended",
                col_span=3,
                column_header=True,
            ),
            _raw_cell(1, 0, "2025"),
            _raw_cell(1, 1, "2024"),
            _raw_cell(1, 2, "2023"),
        ],
    )


def _blank_table() -> dict[str, Any]:
    return _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Stub", column_header=True),
            _raw_cell(0, 1, "", column_header=True),
        ],
    )


def _seal(
    raw_item: dict[str, Any],
    *,
    finalize: bool = True,
    physical_page_index: int = 1,
) -> dict[str, Any]:
    raw_copy = deepcopy(raw_item)
    if physical_page_index != 1:
        raw_copy["prov"][0]["page_no"] = physical_page_index
    native_text = " ".join(
        str(cell.get("text") or "")
        for cell in raw_copy.get("data", {}).get("table_cells", [])
    )
    page_index, table = _docling_table_item(
        raw_copy,
        {physical_page_index: 120.0},
        {},
        [""] * (physical_page_index - 1) + [native_text],
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    table["id"] = f"predecessor-table-{physical_page_index}"
    table["reading_order"] = 0
    snapshot = table.get("_p04_predecessor_snapshot")
    if isinstance(snapshot, dict):
        snapshot["id"] = table["id"]
        snapshot["reading_order"] = table["reading_order"]
    pages = [
        {
            "page_index": page_index,
            "page_number": page_index,
            "page_label": str(page_index),
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "success": True,
            "items": [table],
            "warnings": [],
        }
    ]
    seal_table_pages(
        pages,
        SOURCE_SHA256,
        [native_text],
        table_span_fidelity_enabled=True,
    )
    if finalize:
        finalize_table_pages(
            pages,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
        )
    return pages[0]["items"][0]


def _projection(table: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(table.get(key))
        for key in PUBLIC_PROJECTION_KEYS
    }


def _make_well_formed_nonvalid(
    sidecar: dict[str, Any],
    status: str,
) -> None:
    sidecar["status"] = status
    sidecar["concerns"] = [
        (
            "table_source_span_evidence_unresolved"
            if status == "unresolved"
            else "table_malformed_source_evidence"
        )
    ]


def _assert_lower_sha256(value: object) -> None:
    assert type(value) is str
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def _assert_exact_valid_contract(table: dict[str, Any]) -> dict[str, Any]:
    sidecar = table["table_evidence"]
    assert type(sidecar) is dict
    assert set(sidecar) == SIDECAR_KEYS
    assert len(sidecar) == 17
    assert sidecar["policy_id"] == "p04-table-evidence-v1"
    assert sidecar["version"] == "1.1"
    assert sidecar["scope"] == ["P04-US01"]
    assert sidecar["status"] == "valid"
    assert sidecar["page_index"] == 1
    assert sidecar["reconciliation"] is None
    assert sidecar["gate"] is None
    assert sidecar["continuation"] is None
    _assert_lower_sha256(sidecar["table_id"])
    _assert_lower_sha256(sidecar["candidate_id"])

    assert set(sidecar["grid"]) == GRID_KEYS
    assert all(set(slot) == SLOT_KEYS for slot in sidecar["slots"])
    assert all(set(cell) == CELL_KEYS for cell in table["cells"])
    assert all(
        set(cell["confidence_dimensions"]) == CONFIDENCE_DIMENSION_KEYS
        for cell in table["cells"]
    )
    assert all(
        cell["bbox"] is None
        or set(cell["bbox"]) == {"x", "y", "width", "height", "unit"}
        for cell in table["cells"]
    )
    assert all(
        set(source_object) == SOURCE_OBJECT_KEYS
        for source_object in sidecar["source_objects"]
    )
    assert all(set(evidence) == EVIDENCE_KEYS for evidence in sidecar["evidence"])
    assert all(
        set(decision) == SPAN_DECISION_KEYS
        for decision in sidecar["span_decisions"]
    )
    assert set(sidecar["representation_custody"]) == REPRESENTATION_CUSTODY_KEYS
    return sidecar


def _assert_plain_json(value: object) -> None:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return
    if value_type is float:
        assert math.isfinite(value)
        return
    if value_type is list:
        for item in value:
            _assert_plain_json(item)
        return
    assert value_type is dict
    for key, item in value.items():
        assert type(key) is str
        _assert_plain_json(item)


def _assert_rejected_candidate(raw_item: dict[str, Any]) -> None:
    try:
        table = _seal(raw_item)
    except (TypeError, ValueError, TimeoutError) as error:
        assert len(str(error).encode("utf-8")) <= 256
        return
    sidecar = table.get("table_evidence")
    assert not isinstance(sidecar, dict) or sidecar.get("status") != "valid"


def test_valid_runtime_sidecar_and_nested_records_are_exactly_closed() -> None:
    table = _seal(_repeated_table())
    sidecar = _assert_exact_valid_contract(table)

    assert len(SIDECAR_KEYS) == 17
    assert "predecessor" not in sidecar
    assert not any(key.startswith("_p04") for key in table)
    assert len(table["cells"]) == 10
    assert sidecar["grid"]["row_count"] == 5
    assert sidecar["grid"]["column_count"] == 2
    assert len(sidecar["grid"]["cell_ids"]) == 10
    assert len(sidecar["slots"]) == 10


def test_repeated_values_remain_five_explicit_unit_span_cells() -> None:
    table = _seal(_repeated_table())
    sidecar = _assert_exact_valid_contract(table)
    repeated = [cell for cell in table["cells"] if cell["text"] == "United States"]

    assert len(repeated) == 5
    assert len({cell["id"] for cell in repeated}) == 5
    assert all((cell["row_span"], cell["col_span"]) == (1, 1) for cell in repeated)
    assert all(cell["span_decision_id"] is None for cell in repeated)
    assert all(slot["kind"] == "anchor" for slot in sidecar["slots"])
    assert [row[0] for row in table["rows"]] == ["United States"] * 5


def test_cell_bbox_provenance_and_evidence_references_are_closed() -> None:
    table = _seal(_repeated_table())
    sidecar = _assert_exact_valid_contract(table)
    source_object_ids = {item["id"] for item in sidecar["source_objects"]}
    evidence_ids = {item["id"] for item in sidecar["evidence"]}

    assert source_object_ids
    assert evidence_ids
    for source_object in sidecar["source_objects"]:
        _assert_lower_sha256(source_object["id"])
        _assert_lower_sha256(source_object["content_sha256"])
        assert source_object["page_index"] == 1
        assert "../" not in source_object["raw_ref"]
    for evidence in sidecar["evidence"]:
        _assert_lower_sha256(evidence["id"])
        _assert_lower_sha256(evidence["content_sha256"])
        assert set(evidence["source_object_ids"]) <= source_object_ids
    for cell in table["cells"]:
        _assert_lower_sha256(cell["id"])
        assert cell["bbox"] is not None
        assert cell["bbox"]["unit"] == "pt"
        assert cell["bbox"]["width"] > 0
        assert cell["bbox"]["height"] > 0
        assert set(cell["source_object_ids"]) <= source_object_ids
        assert set(cell["evidence_ids"]) <= evidence_ids


def test_table_geometry_evidence_uses_top_left_page_coordinates() -> None:
    table = _seal(_repeated_table())
    sidecar = _assert_exact_valid_contract(table)
    geometry = next(
        evidence
        for evidence in sidecar["evidence"]
        if evidence["dimension"] == "geometry"
    )

    assert table["bbox"] == {
        "x": 0.0,
        "y": 10.0,
        "w": 300.0,
        "h": 110.0,
        "width": 300.0,
        "height": 110.0,
        "unit": "pt",
    }
    assert geometry["bbox"] == {
        "x": 0.0,
        "y": 10.0,
        "width": 300.0,
        "height": 110.0,
        "unit": "pt",
    }


def test_non_top_left_cell_geometry_cannot_create_a_marker() -> None:
    raw = _repeated_table()
    raw["data"]["table_cells"][0]["bbox"]["coord_origin"] = "BOTTOMLEFT"

    _assert_rejected_candidate(raw)


def test_supported_colspan_has_covered_slots_and_matching_representations() -> None:
    table = _seal(_spanned_table())
    sidecar = _assert_exact_valid_contract(table)
    anchor = next(cell for cell in table["cells"] if cell["text"] == "Years ended")
    decision = next(
        item
        for item in sidecar["span_decisions"]
        if item["id"] == anchor["span_decision_id"]
    )
    covered = [slot for slot in sidecar["slots"] if slot["kind"] == "covered"]

    assert (anchor["row_span"], anchor["col_span"]) == (1, 3)
    assert decision["outcome"] == "supported"
    assert (decision["emitted_row_span"], decision["emitted_col_span"]) == (1, 3)
    assert decision["evidence_ids"]
    assert len(covered) == 2
    assert {(slot["row"], slot["column"]) for slot in covered} == {(0, 1), (0, 2)}
    assert all(slot["cell_id"] is None for slot in covered)
    assert all(slot["covered_by_cell_id"] == anchor["id"] for slot in covered)
    assert table["rows"] == [["Years ended", "", ""], ["2025", "2024", "2023"]]
    assert 'colspan="3"' in table["html"]
    assert table["md"] == table["html"]
    assert table["csv"] == "Years ended,,\n2025,2024,2023"


def test_explicit_blank_slot_is_not_conflated_with_span_coverage() -> None:
    table = _seal(_blank_table())
    sidecar = _assert_exact_valid_contract(table)
    blank_cell = next(cell for cell in table["cells"] if cell["text"] == "")
    blank_slot = next(
        slot
        for slot in sidecar["slots"]
        if (slot["row"], slot["column"]) == (0, 1)
    )

    assert blank_slot["kind"] == "explicit_blank"
    assert blank_slot["cell_id"] == blank_cell["id"]
    assert blank_slot["covered_by_cell_id"] is None


def test_representation_custody_hashes_the_single_semantic_grid() -> None:
    table = _seal(_spanned_table())
    custody = _assert_exact_valid_contract(table)["representation_custody"]

    assert custody["grid_shape"] == [2, 3]
    assert custody["cells_sha256"] == _representation_sha256(table["cells"])
    assert custody["rows_sha256"] == _representation_sha256(table["rows"])
    assert custody["html_sha256"] == _sha256_bytes(table["html"])
    assert custody["markdown_sha256"] == _sha256_bytes(table["md"])
    assert custody["csv_sha256"] == _sha256_bytes(table["csv"])


def test_ids_and_grid_order_do_not_depend_on_candidate_array_order() -> None:
    raw = _repeated_table()
    reordered = deepcopy(raw)
    reordered["data"]["table_cells"].reverse()
    first = _seal(raw)
    second = _seal(reordered)
    first_sidecar = _assert_exact_valid_contract(first)
    second_sidecar = _assert_exact_valid_contract(second)

    assert first_sidecar["table_id"] == second_sidecar["table_id"]
    assert first_sidecar["candidate_id"] == second_sidecar["candidate_id"]
    assert first_sidecar["grid"] == second_sidecar["grid"]
    assert first_sidecar["slots"] == second_sidecar["slots"]
    assert first["cells"] == second["cells"]
    assert first["rows"] == second["rows"]


@pytest.mark.parametrize("status", ["unresolved", "structural_failure"])
def test_relabelled_populated_valid_overlay_cannot_become_diagnostic(status: str) -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    _make_well_formed_nonvalid(sidecar, status)
    table["table_evidence"] = sidecar

    returned = replay_table_semantics(table, sidecar)

    assert returned is table
    assert table == expected
    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


@pytest.mark.parametrize(
    "mutation",
    ["unknown_status", "missing_key", "extra_key", "wrong_status_type"],
)
def test_unknown_or_malformed_sidecar_is_removed_on_replay(mutation: str) -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    if mutation == "unknown_status":
        sidecar["status"] = "VALID"
    elif mutation == "missing_key":
        sidecar.pop("grid")
    elif mutation == "extra_key":
        sidecar["invented_eighteenth_key"] = True
    else:
        sidecar["status"] = True
    table["table_evidence"] = sidecar

    returned = replay_table_semantics(table, sidecar)

    assert returned is table
    assert table == expected
    assert "table_evidence" not in table


def test_production_diagnostic_sidecar_survives_replay_without_authority() -> None:
    raw = _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Span", col_span=2),
            _raw_cell(0, 1, "Collision"),
        ],
    )
    table = _seal(raw, finalize=False)
    sidecar = deepcopy(table["table_evidence"])
    expected = _projection(table)

    assert sidecar["status"] == "structural_failure"
    assert sidecar["grid"]["cell_ids"] == []
    assert sidecar["slots"] == []
    assert sidecar["span_decisions"] == []

    replay_table_semantics(table, sidecar)

    assert _projection(table) == expected
    assert table["table_evidence"] == sidecar
    assert table["table_evidence"]["status"] != "valid"


@pytest.mark.parametrize("mutation", ["unreachable_source", "unused_evidence"])
def test_diagnostic_graph_rejects_every_unreachable_extra_node(
    mutation: str,
) -> None:
    raw = _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Span", col_span=2),
            _raw_cell(0, 1, "Collision"),
        ],
    )
    table = _seal(raw, finalize=False)
    predecessor = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    if mutation == "unreachable_source":
        sidecar["source_objects"].append(
            {
                "id": "0" * 64,
                "engine": "docling",
                "object_type": "table_cell",
                "page_index": 1,
                "raw_ref": "#/texts/unreachable",
                "content_sha256": "1" * 64,
            }
        )
        sidecar["source_objects"].sort(key=lambda source: source["id"])
    else:
        cell_source = next(
            source
            for source in sidecar["source_objects"]
            if source["object_type"] == "table_cell"
        )
        text_evidence = next(
            evidence
            for evidence in sidecar["evidence"]
            if evidence["dimension"] == "text"
            and evidence["source_object_ids"] == [cell_source["id"]]
        )
        injected = deepcopy(text_evidence)
        injected["id"] = "f" * 64
        sidecar["evidence"].append(injected)
        sidecar["evidence"].sort(key=lambda evidence: evidence["id"])
    table["table_evidence"] = sidecar

    assert validate_table_semantics(table, SOURCE_SHA256) is False
    replay_table_semantics(table, sidecar)

    assert table == predecessor


def test_shared_ocr_confidence_pass_preserves_exact_custodied_cells() -> None:
    raw_candidates = (
        _repeated_table(),
        _raw_table(
            1,
            2,
            [
                _raw_cell(0, 0, "Span", col_span=2),
                _raw_cell(0, 1, "Collision"),
            ],
        ),
    )
    for raw in raw_candidates:
        native_text = " ".join(
            str(raw_cell.get("text") or "")
            for raw_cell in raw.get("data", {}).get("table_cells", [])
        )
        table = _seal(raw, finalize=False)
        before_cells = deepcopy(table["cells"])
        before_sidecar = deepcopy(table["table_evidence"])
        cell = table["cells"][0]
        line = SimpleNamespace(
            text=cell["text"],
            bbox=deepcopy(cell["bbox"]),
            confidence=0.91,
            word_count=1,
        )
        pages = [
            {
                "page_index": 1,
                "page_width": 300.0,
                "page_height": 120.0,
                "unit": "pt",
                "items": [table],
            }
        ]

        _enrich_ocr_confidence(
            pages,
            {1: [SimpleNamespace(lines=[line])]},
        )
        expected_predecessor = deepcopy(
            table["_p04_predecessor_snapshot"]
        )
        seal_table_pages(
            pages,
            SOURCE_SHA256,
            [native_text],
            table_span_fidelity_enabled=True,
        )

        assert table["cells"] == before_cells
        assert table["table_evidence"] == before_sidecar
        assert table is not table["_p04_predecessor_snapshot"]
        if before_sidecar["status"] != "valid":
            assert _projection(table) == _projection(expected_predecessor)
            assert table["table_evidence"]["status"] in {
                "unresolved",
                "structural_failure",
            }


def test_indexed_ocr_confidence_is_byte_exact_to_predecessor_matching() -> None:
    def predecessor_text_matches(value: Mapping[str, Any], line: Any) -> bool:
        candidate = value.get("value")
        if not isinstance(candidate, str):
            candidate = value.get("text")
        if not isinstance(candidate, str):
            return False
        normalized_candidate = document_pipeline._normalized_search_text(  # noqa: SLF001
            candidate
        )
        normalized_line = document_pipeline._normalized_search_text(  # noqa: SLF001
            str(getattr(line, "text", "") or "")
        )
        if not normalized_candidate or not normalized_line:
            return False
        if (
            normalized_candidate in normalized_line
            or normalized_line in normalized_candidate
        ):
            return True
        compact_candidate = normalized_candidate.replace(" ", "")
        compact_line = normalized_line.replace(" ", "")
        return min(len(compact_candidate), len(compact_line)) >= 4 and (
            compact_candidate in compact_line
            or compact_line in compact_candidate
        )

    def predecessor_update(value: Any, page_lines: list[Any]) -> None:
        if isinstance(value, list):
            for entry in value:
                predecessor_update(entry, page_lines)
            return
        if not isinstance(value, dict):
            return
        box = value.get("bbox")
        if isinstance(box, Mapping) and value.get("confidence") is None:
            matching = [
                line
                for line in page_lines
                if document_pipeline._center_inside(  # noqa: SLF001
                    document_pipeline._coerce_bbox(line.bbox),  # noqa: SLF001
                    box,
                )
                and predecessor_text_matches(value, line)
            ]
            confidence = document_pipeline._line_confidence(  # noqa: SLF001
                matching
            )
            if confidence is not None:
                value["confidence"] = confidence
                value["confidence_source"] = "matched_page_ocr"
        for key, nested in value.items():
            if key not in {"annotations", "meta", "metadata"}:
                predecessor_update(nested, page_lines)

    lines = [
        SimpleNamespace(
            text="Gamma",
            bbox={"x": 45.0, "y": 42.0, "width": 10.0, "height": 6.0},
            confidence=0.63,
            word_count=1,
        ),
        SimpleNamespace(
            text="Alpha",
            bbox={"x": 10.0, "y": 10.0, "width": 10.0, "height": 8.0},
            confidence=0.7,
            word_count=2,
        ),
        SimpleNamespace(
            text="Beta",
            bbox={"x": 30.0, "y": 10.0, "width": 10.0, "height": 8.0},
            confidence=0.9,
            word_count=1,
        ),
        SimpleNamespace(
            text="elsewhere",
            bbox={"x": 200.0, "y": 200.0, "width": 5.0, "height": 5.0},
            confidence=0.99,
            word_count=1,
        ),
        SimpleNamespace(
            text="ignored malformed source box",
            bbox={"x": "bad"},
            confidence=1.0,
            word_count=1,
        ),
    ]
    pages = [
        {
            "page_index": 1,
            "items": [
                {
                    "type": "text",
                    "value": "Alpha Beta",
                    "bbox": {
                        "x": 0.0,
                        "y": 0.0,
                        "width": 50.0,
                        "height": 30.0,
                    },
                    "confidence": None,
                },
                {
                    "type": "text",
                    "value": "Gamma",
                    "bbox": {
                        "x": 0.0,
                        "y": 40.0,
                        "width": 50.0,
                        "height": 20.0,
                    },
                    "confidence": None,
                },
                {
                    "type": "text",
                    "value": "Alpha",
                    "bbox": {
                        "x": 0.0,
                        "y": 0.0,
                        "width": 50.0,
                        "height": 30.0,
                    },
                    "confidence": 0.4,
                },
            ],
        }
    ]
    expected = deepcopy(pages)
    predecessor_update(expected[0], lines)

    _enrich_ocr_confidence(
        pages,
        {1: [SimpleNamespace(lines=lines)]},
    )

    assert json.dumps(
        pages,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) == json.dumps(
        expected,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert pages[0]["items"][0]["confidence"] == 0.7667


def test_ocr_confidence_skips_malformed_untrusted_target_bbox() -> None:
    item = {
        "type": "text",
        "value": "Alpha",
        "bbox": {"x": 0.0, "y": 0.0, "width": "not-a-number"},
        "confidence": None,
    }
    pages = [{"page_index": 1, "items": [item]}]
    line = SimpleNamespace(
        text="Alpha",
        bbox={"x": 0.0, "y": 0.0, "width": 5.0, "height": 5.0},
        confidence=0.9,
        word_count=1,
    )

    _enrich_ocr_confidence(
        pages,
        {1: [SimpleNamespace(lines=[line])]},
    )

    assert item["confidence"] is None
    assert "confidence_source" not in item


def test_ocr_confidence_bbox_normalization_is_linear_in_lines_and_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = document_pipeline._coerce_bbox  # noqa: SLF001

    def counted(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(document_pipeline, "_coerce_bbox", counted)
    items = [
        {
            "type": "text",
            "value": f"row {index}",
            "bbox": {
                "x": 0.0,
                "y": float(index * 10),
                "width": 100.0,
                "height": 8.0,
            },
            "confidence": None,
        }
        for index in range(20)
    ]
    lines = [
        SimpleNamespace(
            text=f"row {index}",
            bbox={
                "x": 10.0,
                "y": float(index * 10),
                "width": 20.0,
                "height": 8.0,
            },
            confidence=0.8,
            word_count=2,
        )
        for index in range(20)
    ]

    _enrich_ocr_confidence(
        [{"page_index": 1, "items": items}],
        {1: [SimpleNamespace(lines=lines)]},
    )

    assert calls == len(items) + len(lines)
    assert all(item["confidence"] == 0.8 for item in items)


def test_diagnostic_custody_includes_predecessor_ocr_confidence() -> None:
    raw = _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Span", col_span=2),
            _raw_cell(0, 1, "Collision"),
        ],
    )
    native_text = "Span Collision"
    _, predecessor = _docling_table_item(
        raw,
        {1: 120.0},
        {},
        [native_text],
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    line = SimpleNamespace(
        text=predecessor["cells"][0]["text"],
        bbox=deepcopy(predecessor["cells"][0]["bbox"]),
        confidence=0.91,
        word_count=1,
    )
    image_regions = {1: [SimpleNamespace(lines=[line])]}
    _enrich_ocr_confidence(
        [{"page_index": 1, "items": [predecessor]}],
        image_regions,
    )

    _, diagnostic = _docling_table_item(
        raw,
        {1: 120.0},
        {},
        [native_text],
        SOURCE_SHA256,
        image_regions=image_regions,
        table_span_fidelity_enabled=True,
    )
    snapshot = diagnostic["_p04_predecessor_snapshot"]
    snapshot_before = deepcopy(snapshot)
    assert diagnostic is not snapshot
    assert "table_evidence" not in snapshot
    assert "_p04_predecessor_snapshot" not in snapshot
    json.dumps(diagnostic, allow_nan=False, sort_keys=True)

    original_text = diagnostic["rows"][0][0]
    diagnostic["rows"][0][0] = "overlay-only mutation"
    assert snapshot == snapshot_before
    diagnostic["rows"][0][0] = original_text
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [diagnostic],
        }
    ]
    _enrich_ocr_confidence(pages, image_regions)
    seal_table_pages(
        pages,
        SOURCE_SHA256,
        [native_text],
        table_span_fidelity_enabled=True,
    )

    assert _projection(diagnostic) == _projection(predecessor)
    assert diagnostic["cells"][0]["confidence"] == 0.91
    assert diagnostic["table_evidence"]["status"] == "structural_failure"
    assert diagnostic is not diagnostic["_p04_predecessor_snapshot"]
    assert "table_evidence" not in diagnostic["_p04_predecessor_snapshot"]
    assert (
        "_p04_predecessor_snapshot"
        not in diagnostic["_p04_predecessor_snapshot"]
    )
    json.dumps(pages, allow_nan=False, sort_keys=True)

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    assert "_p04_predecessor_snapshot" not in diagnostic
    json.dumps(pages, allow_nan=False, sort_keys=True)


def test_shared_confidence_is_cycle_safe_and_p04_private_graphs_are_opaque() -> None:
    private_snapshot: dict[str, Any] = {
        "type": "table",
        "confidence": None,
        "bbox": {
            "x": 0.0,
            "y": 0.0,
            "width": 20.0,
            "height": 10.0,
        },
    }
    item: dict[str, Any] = {
        "type": "text",
        "value": "Alpha",
        "confidence": None,
        "bbox": {
            "x": 0.0,
            "y": 0.0,
            "width": 20.0,
            "height": 10.0,
        },
        "_p04_predecessor_snapshot": private_snapshot,
    }
    private_snapshot["hostile_cycle"] = item
    item["hostile_public_cycle"] = item
    line = SimpleNamespace(
        text="Alpha",
        bbox={"x": 1.0, "y": 1.0, "width": 5.0, "height": 5.0},
        confidence=0.87,
        word_count=1,
    )

    _enrich_ocr_confidence(
        [{"page_index": 1, "items": [item]}],
        {1: [SimpleNamespace(lines=[line])]},
    )

    assert item["confidence"] == 0.87
    assert private_snapshot["confidence"] is None
    assert private_snapshot["hostile_cycle"] is item


def test_resource_limited_diagnostic_owns_independent_predecessor_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_hash_and_size = (
        table_semantics._canonical_table_sha256_and_size  # noqa: SLF001
    )

    def force_structure_limit(
        value: object,
        maximum_bytes: int,
        deadline: float,
    ) -> tuple[str, int]:
        digest, _size = original_hash_and_size(
            value,
            maximum_bytes,
            deadline,
        )
        return digest, 8_388_609

    monkeypatch.setattr(
        table_semantics,
        "_canonical_table_sha256_and_size",
        force_structure_limit,
    )
    raw = _raw_table(1, 1, [_raw_cell(0, 0, "bounded")])
    _, table = _docling_table_item(
        raw,
        {1: 120.0},
        {},
        ["bounded"],
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    monkeypatch.setattr(
        table_semantics,
        "_canonical_table_sha256_and_size",
        original_hash_and_size,
    )

    snapshot = table["_p04_predecessor_snapshot"]
    expected_snapshot = deepcopy(snapshot)
    assert table["table_evidence"]["status"] == "unresolved"
    assert table["table_evidence"]["concerns"] == [
        "table_resource_limit_exceeded"
    ]
    assert table is not snapshot
    assert "table_evidence" not in snapshot
    assert "_p04_predecessor_snapshot" not in snapshot
    json.dumps(table, allow_nan=False, sort_keys=True)

    table["rows"][0][0] = "overlay-only mutation"
    assert snapshot == expected_snapshot
    table["rows"][0][0] = expected_snapshot["rows"][0][0]
    assert validate_table_semantics(table, SOURCE_SHA256) is True

    sidecar = deepcopy(table["table_evidence"])
    replay_table_semantics(
        table,
        sidecar,
        source_sha256=SOURCE_SHA256,
    )
    assert table is not table["_p04_predecessor_snapshot"]
    assert "table_evidence" not in table["_p04_predecessor_snapshot"]
    assert (
        "_p04_predecessor_snapshot"
        not in table["_p04_predecessor_snapshot"]
    )
    json.dumps(table, allow_nan=False, sort_keys=True)


def test_malformed_marker_cannot_suppress_shared_confidence_enrichment() -> None:
    table = _seal(_repeated_table(), finalize=False)
    table["table_evidence"]["invented_eighteenth_key"] = True
    cell = table["cells"][0]
    line = SimpleNamespace(
        text=cell["text"],
        bbox=deepcopy(cell["bbox"]),
        confidence=0.91,
        word_count=1,
    )
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    _enrich_ocr_confidence(
        pages,
        {1: [SimpleNamespace(lines=[line])]},
    )
    seal_table_pages(
        pages,
        SOURCE_SHA256,
        [cell["text"]],
        table_span_fidelity_enabled=True,
    )

    assert cell["confidence"] == 0.91
    assert cell["confidence_source"] == "matched_page_ocr"
    assert "table_evidence" not in table


@pytest.mark.parametrize(
    "mutation",
    [
        "cell_extra",
        "slot_extra",
        "slot_collision",
        "grid_shape",
        "cell_id_collision",
        "source_object_id_collision",
    ],
)
def test_inconsistent_or_colliding_overlay_is_removed_transactionally(
    mutation: str,
) -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    table["table_evidence"] = sidecar
    if mutation == "cell_extra":
        table["cells"][0]["extra"] = "forbidden"
    elif mutation == "slot_extra":
        sidecar["slots"][0]["extra"] = "forbidden"
    elif mutation == "slot_collision":
        sidecar["slots"][1]["row"] = sidecar["slots"][0]["row"]
        sidecar["slots"][1]["column"] = sidecar["slots"][0]["column"]
    elif mutation == "grid_shape":
        sidecar["grid"]["row_count"] += 1
    elif mutation == "cell_id_collision":
        table["cells"][1]["id"] = table["cells"][0]["id"]
    else:
        sidecar["source_objects"].append(deepcopy(sidecar["source_objects"][0]))

    returned = replay_table_semantics(table, sidecar)

    assert returned is table
    assert "table_evidence" not in table
    assert table == expected


@pytest.mark.parametrize(
    "field",
    ["cells_sha256", "rows_sha256", "html_sha256", "markdown_sha256", "csv_sha256"],
)
def test_representation_hash_mismatch_removes_the_overlay(field: str) -> None:
    table = _seal(_spanned_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    sidecar["representation_custody"][field] = "0" * 64
    table["table_evidence"] = sidecar

    replay_table_semantics(table, sidecar)

    assert table == expected
    assert "table_evidence" not in table


@pytest.mark.parametrize(
    "mutation",
    [
        "concerns_plus_one",
        "evidence_ids_plus_one",
        "source_object_ids_plus_one",
        "identity_plus_one",
        "raw_ref_plus_one",
        "strict_integer_bool",
    ],
)
def test_nested_record_limits_and_strict_types_fail_closed(mutation: str) -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    table["table_evidence"] = sidecar
    if mutation == "concerns_plus_one":
        sidecar["concerns"] = ["table_resource_limit_exceeded"] * 65
    elif mutation == "evidence_ids_plus_one":
        table["cells"][0]["evidence_ids"] = [sidecar["evidence"][0]["id"]] * 65
    elif mutation == "source_object_ids_plus_one":
        table["cells"][0]["source_object_ids"] = [
            sidecar["source_objects"][0]["id"]
        ] * 65
    elif mutation == "identity_plus_one":
        table["cells"][0]["id"] = "a" * 257
    elif mutation == "raw_ref_plus_one":
        sidecar["source_objects"][0]["raw_ref"] = "r" * 257
    else:
        table["cells"][0]["row"] = True

    replay_table_semantics(table, sidecar)

    assert "table_evidence" not in table
    assert table == expected


@pytest.mark.parametrize("status", ["unresolved", "structural_failure"])
def test_text_replacement_excludes_every_nonvalid_marker(status: str) -> None:
    table = _seal(_repeated_table())
    _make_well_formed_nonvalid(table["table_evidence"], status)
    owner = SimpleNamespace(
        value="United States",
        markdown="United States",
        properties={"legacy_item": table},
    )
    before = deepcopy(vars(owner))

    returned = replace_marked_table_text(
        owner,
        selected_text="ATTACKER REPLACEMENT",
        replacement_mode="unique_substring",
        original_text="United States",
    )

    assert returned is None
    assert vars(owner) == before
    assert "ATTACKER REPLACEMENT" not in str(vars(owner))


def test_default_off_hooks_preserve_exact_object_identity_and_bytes() -> None:
    raw = _repeated_table()
    heights = {1: 100.0}
    words: dict[int, list[dict[str, Any]]] = {}
    item: dict[str, Any] = {"type": "table", "rows": [["A"]], "cells": []}
    vector_item = deepcopy(item)
    raw_vector = {"page_index": 1, "rows": [["A"]]}
    pages = [{"page_index": 1, "items": [deepcopy(item)]}]
    pages_before = deepcopy(pages)

    assert (
        prepare_docling_table_input(
            raw,
            heights,
            words,
            table_span_fidelity_enabled=False,
        )
        is raw
    )
    assert (
        prepare_docling_table(item, raw, table_span_fidelity_enabled=False)
        is item
    )
    assert (
        prepare_vector_table(
            vector_item,
            raw_vector,
            table_span_fidelity_enabled=False,
        )
        is vector_item
    )
    assert (
        seal_table_pages(
            pages,
            SOURCE_SHA256,
            ["A"],
            table_span_fidelity_enabled=False,
        )
        is None
    )
    assert pages == pages_before
    assert "table_evidence" not in pages[0]["items"][0]
    assert json.dumps(pages, sort_keys=True) == json.dumps(pages_before, sort_keys=True)


@pytest.mark.parametrize(
    ("dimension", "exact", "over"),
    [
        ("rows", 4_096, 4_097),
        ("columns", 256, 257),
        ("cell_text", 16_384, 16_385),
    ],
)
def test_declared_and_text_limits_are_inclusive_and_plus_one_rejects(
    dimension: str,
    exact: int,
    over: int,
) -> None:
    if dimension == "rows":
        accepted = _raw_table(exact, 1, [_raw_cell(0, 0, "A")])
        rejected = _raw_table(over, 1, [_raw_cell(0, 0, "A")])
    elif dimension == "columns":
        accepted = _raw_table(1, exact, [_raw_cell(0, 0, "A")])
        rejected = _raw_table(1, over, [_raw_cell(0, 0, "A")])
    else:
        accepted = _raw_table(1, 1, [_raw_cell(0, 0, "x" * exact)])
        rejected = _raw_table(1, 1, [_raw_cell(0, 0, "x" * over)])

    prepared = prepare_docling_table_input(
        accepted,
        {1: 100.0},
        {},
        table_span_fidelity_enabled=True,
    )
    assert type(prepared) is dict
    with pytest.raises((TypeError, ValueError, TimeoutError)):
        prepare_docling_table_input(
            rejected,
            {1: 100.0},
            {},
            table_span_fidelity_enabled=True,
        )


def test_cell_count_limit_plus_one_rejects_before_candidate_projection() -> None:
    shared_cell = _raw_cell(0, 0, "A")
    raw = _raw_table(1, 1, [shared_cell] * 65_537)

    with pytest.raises((TypeError, ValueError, TimeoutError)):
        prepare_docling_table_input(
            raw,
            {1: 100.0},
            {},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize(
    "bad_text",
    ["secret\x00payload", "secret\x1fpayload", "secret\x7fpayload", "secret\ud800payload"],
)
def test_unsafe_control_or_invalid_utf8_is_rejected_without_diagnostic_leak(
    bad_text: str,
) -> None:
    raw = _raw_table(1, 1, [_raw_cell(0, 0, bad_text)])

    with pytest.raises((TypeError, ValueError, TimeoutError)) as caught:
        prepare_docling_table_input(
            raw,
            {1: 100.0},
            {},
            table_span_fidelity_enabled=True,
        )

    assert "secret" not in str(caught.value)
    assert len(str(caught.value).encode("utf-8")) <= 256


@pytest.mark.parametrize("bad_number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_geometry_can_never_create_a_valid_marker(bad_number: float) -> None:
    raw = _raw_table(1, 1, [_raw_cell(0, 0, "A")])
    raw["data"]["table_cells"][0]["bbox"]["l"] = bad_number

    _assert_rejected_candidate(raw)


def test_unsupported_or_overlapping_span_never_becomes_authoritative() -> None:
    unsupported = _spanned_table()
    unsupported["data"]["table_cells"][0].pop("bbox")
    overlap = _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Span", col_span=2),
            _raw_cell(0, 1, "Collision"),
        ],
    )

    _assert_rejected_candidate(unsupported)
    _assert_rejected_candidate(overlap)


@pytest.mark.parametrize("spanned", [False, True])
def test_on_page_cell_outside_owning_table_never_becomes_authoritative(
    spanned: bool,
) -> None:
    raw = _spanned_table() if spanned else _repeated_table()
    # Keep the displaced content rectangle wholly on the 300 pt-wide page but
    # outside the independently bound 180 pt-wide table region.
    raw["prov"][0]["bbox"]["r"] = 180.0
    target = raw["data"]["table_cells"][0]
    target["bbox"].update({"l": 220.0, "r": 270.0})

    table = _seal(raw, finalize=False)
    predecessor = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = table["table_evidence"]

    assert sidecar["status"] in {"unresolved", "structural_failure"}
    assert "table_source_cell_bbox_unresolved" in sidecar["concerns"]
    if spanned:
        assert "table_source_span_evidence_unresolved" in sidecar["concerns"]
    assert _projection(table) == _projection(predecessor)
    assert sidecar["span_decisions"] == []


def test_narrow_content_rectangles_inside_bound_table_still_support_spans() -> None:
    colspan = _spanned_table()
    colspan["data"]["table_cells"][0]["bbox"].update(
        {"l": 20.0, "r": 45.0}
    )
    colspan_table = _seal(colspan)
    colspan_anchor = colspan_table["cells"][0]

    rowspan = _raw_table(
        3,
        2,
        [
            _raw_cell(0, 0, "Clinical measure", row_span=3),
            _raw_cell(0, 1, "Baseline"),
            _raw_cell(1, 1, "Week 4"),
            _raw_cell(2, 1, "Week 8"),
        ],
    )
    rowspan["data"]["table_cells"][0]["bbox"].update(
        {"t": 20.0, "b": 35.0}
    )
    rowspan_table = _seal(rowspan)
    rowspan_anchor = rowspan_table["cells"][0]

    assert colspan_table["table_evidence"]["status"] == "valid"
    assert (colspan_anchor["row_span"], colspan_anchor["col_span"]) == (1, 3)
    assert rowspan_table["table_evidence"]["status"] == "valid"
    assert (rowspan_anchor["row_span"], rowspan_anchor["col_span"]) == (3, 1)


@pytest.mark.parametrize("edge", ["left", "top", "right", "bottom"])
def test_table_content_region_ownership_uses_exact_half_point_boundary(
    edge: str,
) -> None:
    table_bbox = {
        "x": 10.0,
        "y": 20.0,
        "width": 100.0,
        "height": 80.0,
        "unit": "pt",
    }
    on_boundary = {
        "x": 20.0,
        "y": 30.0,
        "width": 20.0,
        "height": 10.0,
        "unit": "pt",
    }
    beyond_boundary = deepcopy(on_boundary)
    if edge == "left":
        on_boundary["x"] = 9.5
        beyond_boundary["x"] = 9.499
    elif edge == "top":
        on_boundary["y"] = 19.5
        beyond_boundary["y"] = 19.499
    elif edge == "right":
        on_boundary.update({"x": 90.5, "width": 20.0})
        beyond_boundary.update({"x": 90.501, "width": 20.0})
    else:
        on_boundary.update({"y": 90.5, "height": 10.0})
        beyond_boundary.update({"y": 90.501, "height": 10.0})

    deadline = table_semantics.perf_counter() + 0.500
    assert table_semantics._table_content_bbox_within_region(  # noqa: SLF001
        on_boundary,
        table_bbox,
        deadline,
    )
    assert not table_semantics._table_content_bbox_within_region(  # noqa: SLF001
        beyond_boundary,
        table_bbox,
        deadline,
    )


def test_hostile_multiline_text_is_preserved_as_data_and_html_escaped() -> None:
    hostile = "<script>alert('x')</script>\nline & more"
    table = _seal(_raw_table(1, 1, [_raw_cell(0, 0, hostile)]))
    _assert_exact_valid_contract(table)

    assert table["cells"][0]["text"] == hostile
    assert table["rows"] == [[hostile]]
    assert "<script>" not in table["html"]
    assert "&lt;script&gt;" in table["html"]
    assert "&amp; more" in table["html"]
    assert "<br>" in table["html"]
    assert table["md"] == table["html"]


def test_runtime_output_is_plain_json_and_content_item_compatible() -> None:
    table = _seal(_spanned_table())
    _assert_exact_valid_contract(table)
    _assert_plain_json(table)
    encoded = json.dumps(
        table,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    round_tripped = json.loads(encoded)
    validated = ContentItem.model_validate(table)
    public = validated.model_dump(mode="json")

    assert round_tripped == table
    assert public["table_evidence"] == table["table_evidence"]
    assert public["cells"] == table["cells"]
    assert public["rows"] == table["rows"]
    assert public["html"] == table["html"]
    assert public["csv"] == table["csv"]
    assert not any(key.startswith("_") for key in public)


def test_plain_data_guard_rejects_mapping_subclasses_without_callbacks() -> None:
    class HostileMapping(dict[str, Any]):
        called = False

        def items(self):  # type: ignore[override]
            self.called = True
            raise AssertionError("hostile callback executed")

    raw = HostileMapping(_repeated_table())

    with pytest.raises(TypeError, match="plain data"):
        prepare_docling_table_input(
            raw,
            {1: 100.0},
            {},
            table_span_fidelity_enabled=True,
        )
    assert raw.called is False


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_provenance",
        "ambiguous_provenance",
        "multi_page_provenance",
        "ambiguous_cell_reference",
        "unsafe_cell_reference",
        "contradictory_end_row",
        "contradictory_end_column",
    ],
)
def test_missing_ambiguous_or_contradictory_source_identity_never_authorizes(
    mutation: str,
) -> None:
    raw = _spanned_table()
    if mutation == "missing_provenance":
        raw.pop("prov")
    elif mutation == "ambiguous_provenance":
        raw["prov"].append(deepcopy(raw["prov"][0]))
    elif mutation == "multi_page_provenance":
        second = deepcopy(raw["prov"][0])
        second["page_no"] = 2
        raw["prov"].append(second)
    elif mutation == "ambiguous_cell_reference":
        raw["data"]["table_cells"][0]["ref"]["cref"] = "#/texts/other"
    elif mutation == "unsafe_cell_reference":
        raw["data"]["table_cells"][0]["ref"]["$ref"] = "#/texts/../secret"
    elif mutation == "contradictory_end_row":
        raw["data"]["table_cells"][0]["end_row_offset_idx"] += 1
    else:
        raw["data"]["table_cells"][0]["end_col_offset_idx"] -= 1

    table = _seal(raw)

    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


def test_missing_cell_reference_uses_truthful_table_structural_locator() -> None:
    raw = _spanned_table()
    raw["data"]["table_cells"][0].pop("ref")

    table = _seal(raw)
    sidecar = table["table_evidence"]
    cell = next(cell for cell in table["cells"] if cell["row"] == 0)
    cell_source = next(
        source
        for source in sidecar["source_objects"]
        if source["id"] == cell["source_object_ids"][0]
    )

    assert sidecar["status"] == "valid"
    assert cell_source["raw_ref"] == raw["self_ref"]
    assert validate_table_semantics(table, SOURCE_SHA256) is True


def test_missing_source_identity_returns_exact_pre_recovery_predecessor() -> None:
    raw = _raw_table(
        2,
        2,
        [
            _raw_cell(0, 0, "Name"),
            _raw_cell(0, 1, "Value"),
            _raw_cell(1, 0, "Alpha"),
            _raw_cell(1, 1, "1"),
        ],
    )
    words = {
        1: [
            {
                "text": cell["text"],
                "x0": cell["bbox"]["l"] + 1.0,
                "x1": cell["bbox"]["r"] - 1.0,
                "top": cell["bbox"]["t"] + 1.0,
                "bottom": cell["bbox"]["b"] - 1.0,
                "bold": cell["start_row_offset_idx"] == 0,
            }
            for cell in raw["data"]["table_cells"]
        ]
    }
    _, predecessor = _docling_table_item(
        raw,
        {1: 120.0},
        words,
        ["Name Value Alpha 1"],
        None,
        table_span_fidelity_enabled=False,
    )

    _, observed = _docling_table_item(
        raw,
        {1: 120.0},
        words,
        ["Name Value Alpha 1"],
        None,
        table_span_fidelity_enabled=True,
    )

    assert observed == predecessor
    assert all(cell["column_header"] is False for cell in observed["cells"])
    assert "table_evidence" not in observed
    assert "_p04_predecessor_snapshot" not in observed


def test_missing_cell_reference_ids_are_stable_without_array_order() -> None:
    raw = _spanned_table()
    for cell in raw["data"]["table_cells"]:
        cell.pop("ref")
    reordered = deepcopy(raw)
    reordered["data"]["table_cells"].reverse()

    first = _seal(raw)
    second = _seal(reordered)

    assert first == second
    assert {
        source["raw_ref"]
        for source in first["table_evidence"]["source_objects"]
        if source["object_type"] == "table_cell"
    } == {raw["self_ref"]}


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_structural_locator", "duplicate_direct_ref", "table_direct_ref"],
)
def test_cell_locator_collisions_fail_the_whole_table_closed(
    mutation: str,
) -> None:
    raw = _spanned_table()
    if mutation == "duplicate_structural_locator":
        duplicate = deepcopy(raw["data"]["table_cells"][0])
        duplicate.pop("ref")
        raw["data"]["table_cells"][0].pop("ref")
        raw["data"]["table_cells"].append(duplicate)
    elif mutation == "duplicate_direct_ref":
        raw["data"]["table_cells"][1]["ref"] = deepcopy(
            raw["data"]["table_cells"][0]["ref"]
        )
    else:
        raw["data"]["table_cells"][0]["ref"] = {
            "$ref": raw["self_ref"]
        }

    table = _seal(raw)

    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


@pytest.mark.parametrize(
    "mutation",
    [
        "claimed_span_type",
        "emitted_span_mismatch",
        "decision_cell_mismatch",
        "supported_concern",
        "decision_evidence_dimension",
        "cell_decision_mismatch",
        "covered_slot_redirect",
        "slot_order_swap",
        "grid_cell_order",
    ],
)
def test_replay_rejects_every_span_linkage_and_rectangular_topology_mutation(
    mutation: str,
) -> None:
    table = _seal(_spanned_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = table["table_evidence"]
    decision = sidecar["span_decisions"][0]
    span_cell = table["cells"][0]
    if mutation == "claimed_span_type":
        decision["claimed_col_span"] = "3"
    elif mutation == "emitted_span_mismatch":
        decision["emitted_col_span"] = 2
    elif mutation == "decision_cell_mismatch":
        decision["cell_id"] = table["cells"][1]["id"]
    elif mutation == "supported_concern":
        decision["concern_codes"] = [
            "table_source_span_evidence_unresolved"
        ]
    elif mutation == "decision_evidence_dimension":
        text_evidence_id = next(
            evidence["id"]
            for evidence in sidecar["evidence"]
            if evidence["dimension"] == "text"
            and evidence["source_object_ids"] == span_cell["source_object_ids"]
        )
        structure_evidence_id = next(
            evidence["id"]
            for evidence in sidecar["evidence"]
            if evidence["dimension"] == "structure"
        )
        decision["evidence_ids"] = sorted(
            [text_evidence_id, structure_evidence_id]
        )
    elif mutation == "cell_decision_mismatch":
        span_cell["span_decision_id"] = "0" * 64
    elif mutation == "covered_slot_redirect":
        covered = next(
            slot for slot in sidecar["slots"] if slot["kind"] == "covered"
        )
        covered["covered_by_cell_id"] = table["cells"][1]["id"]
    elif mutation == "slot_order_swap":
        sidecar["slots"][0], sidecar["slots"][1] = (
            sidecar["slots"][1],
            sidecar["slots"][0],
        )
    else:
        sidecar["grid"]["cell_ids"][0], sidecar["grid"]["cell_ids"][1] = (
            sidecar["grid"]["cell_ids"][1],
            sidecar["grid"]["cell_ids"][0],
        )

    replay_table_semantics(table, sidecar)

    assert table == expected
    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


def test_seal_binds_table_candidate_and_slot_ids_to_supplied_source_sha() -> None:
    table = _seal(_spanned_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    seal_table_pages(
        pages,
        "b" * 64,
        ["Years ended 2025 2024 2023"],
        table_span_fidelity_enabled=True,
    )

    assert table == expected
    assert "table_evidence" not in table


def test_canonical_serializer_emits_header_scopes_escaped_multiline_and_csv() -> None:
    raw = _raw_table(
        2,
        2,
        [
            _raw_cell(0, 0, "Region", column_header=True),
            _raw_cell(0, 1, "Value", column_header=True),
            _raw_cell(1, 0, 'North,\n<zone "A">', row_header=True),
            _raw_cell(1, 1, "42"),
        ],
    )

    table = _seal(raw)

    assert '<th scope="col">Region</th>' in table["html"]
    assert '<th scope="row">North,<br>&lt;zone &quot;A&quot;&gt;</th>' in table["html"]
    assert table["md"] == table["html"]
    assert table["csv"] == 'Region,Value\n"North,\n<zone ""A"">",42'
    assert table["rows"] == table["value"] == [
        ["Region", "Value"],
        ['North,\n<zone "A">', "42"],
    ]


def test_public_source_bound_validator_is_nonmutating_and_rejects_wrong_source() -> None:
    table = _seal(_spanned_table())
    before = deepcopy(table)

    assert validate_table_semantics(table, SOURCE_SHA256) is True
    assert table == before
    assert validate_table_semantics(table, "b" * 64) is False
    assert table == before


def test_public_validator_rejects_unreachable_source_and_evidence_pair() -> None:
    table = _seal(_repeated_table())
    before = deepcopy(table)
    sidecar = table["table_evidence"]
    injected_source_id = "0" * 64
    injected_evidence_id = "0" * 63 + "1"
    sidecar["source_objects"].append(
        {
            "id": injected_source_id,
            "engine": "docling",
            "object_type": "table_cell",
            "page_index": 1,
            "raw_ref": "#/evil/injected",
            "content_sha256": "1" * 64,
        }
    )
    sidecar["source_objects"].sort(key=lambda source: source["id"])
    sidecar["evidence"].append(
        {
            "id": injected_evidence_id,
            "method": "native_text",
            "dimension": "text",
            "page_index": 1,
            "bbox": None,
            "source_object_ids": [injected_source_id],
            "confidence": 1.0,
            "content_sha256": "1" * 64,
        }
    )
    sidecar["evidence"].sort(key=lambda evidence: evidence["id"])
    mutated = deepcopy(table)

    assert validate_table_semantics(table, SOURCE_SHA256) is False
    assert table == mutated
    assert table != before


def test_representation_number_projection_has_exact_cross_runtime_vector() -> None:
    vector = [
        {
            "bbox": {
                "x": -0.0,
                "y": 1.25,
                "width": 2,
                "height": 3.5,
                "unit": "pt",
            },
            "confidence": 1.0,
            "row": 0,
        }
    ]

    digest = table_semantics._table_representation_sha256(  # noqa: SLF001
        vector,
        table_semantics.perf_counter() + 0.500,
    )

    assert digest == "260420ce92ea6d3a8670ad3da8f055ae1b79c528d5aa665de30f9bc0af1bcc1c"


def test_streamed_representation_digest_is_exact_to_frozen_reference_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = random.Random(40401)
    numeric_atoms: list[object] = [
        -0.0,
        0.0,
        1,
        -1,
        2**53 - 1,
        2**53,
        -(2**63),
        1.25,
        -3.5,
        5e-324,
        1.7976931348623157e308,
    ]
    scalar_atoms: list[object] = [
        None,
        False,
        True,
        "",
        "plain",
        "quoted \\\" value",
        "line\nfeed",
        "café",
        *numeric_atoms,
    ]

    def generated(depth: int = 0) -> object:
        if depth >= 3 or generator.randrange(4) == 0:
            return deepcopy(generator.choice(scalar_atoms))
        if generator.randrange(2) == 0:
            return [generated(depth + 1) for _ in range(generator.randrange(5))]
        return {
            f"k{depth}_{index}": generated(depth + 1)
            for index in range(generator.randrange(5))
        }

    values = [generated() for _ in range(128)]
    values.extend(
        [
            numeric_atoms,
            {"z": [-0.0, 0, 2**53], "a": {"escaped": "\t\\\""}},
        ]
    )
    expected = [_representation_sha256(value) for value in values]
    monkeypatch.setattr(
        table_semantics,
        "_table_representation_number_projection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("streaming digest materialized a projection")
        ),
    )

    observed = [
        table_semantics._table_representation_sha256(  # noqa: SLF001
            value,
            table_semantics.perf_counter() + 0.500,
        )
        for value in values
    ]

    assert observed == expected


def test_streamed_representation_digest_enforces_exact_eight_mib_boundary() -> None:
    exact = ["x" * 1_048_573 for _ in range(7)] + ["x" * 1_048_572]

    digest = table_semantics._table_representation_sha256(  # noqa: SLF001
        exact,
        table_semantics.perf_counter() + 2.000,
    )

    assert digest == _representation_sha256(exact)
    exact[-1] += "x"
    with pytest.raises(ValueError, match="JSON limit exceeded"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            exact,
            table_semantics.perf_counter() + 2.000,
        )


def test_streamed_representation_digest_stops_encoding_after_output_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_dumps = table_semantics.dumps
    real_pack = table_semantics.pack
    clock = [0.0]
    dumps_calls = [0]
    pack_calls = [0]

    def counted_dumps(*args: object, **kwargs: object) -> str:
        dumps_calls[0] += 1
        clock[0] += 0.01
        return real_dumps(*args, **kwargs)

    def counted_pack(*args: object, **kwargs: object) -> bytes:
        pack_calls[0] += 1
        return real_pack(*args, **kwargs)

    monkeypatch.setattr(table_semantics, "dumps", counted_dumps)
    monkeypatch.setattr(table_semantics, "pack", counted_pack)
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: clock[0])
    value = ["x" * 900_000 for _ in range(11)] + [1.0]

    with pytest.raises(ValueError, match="canonical table JSON limit exceeded"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            value,
            0.105,
            value_is_plain=True,
        )

    assert dumps_calls == [10]
    assert pack_calls == [0]
    assert clock[0] == pytest.approx(0.1)


def test_streamed_representation_digest_preserves_projected_aggregate_boundary(
) -> None:
    # Logical projected footprint for four equal inner lists is
    # `384 + 1376 * member_count`: each numeric wrapper is exactly 328
    # aggregate bytes and three projected nodes. This exercises the old
    # projected-graph 64 MiB gate without materializing that graph.
    exact = [[0.0] * 48_770 for _ in range(4)]
    overflow = [[0.0] * 48_771 for _ in range(4)]

    digest = table_semantics._table_representation_sha256(  # noqa: SLF001
        exact,
        table_semantics.perf_counter() + 2.000,
        value_is_plain=True,
    )

    assert len(digest) == 64
    with pytest.raises(ValueError, match="aggregate byte limit exceeded"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            overflow,
            table_semantics.perf_counter() + 2.000,
            value_is_plain=True,
        )


def test_streamed_representation_digest_preserves_projected_depth_and_string_limits(
) -> None:
    exact: object = 0.0
    for _index in range(31):
        exact = [exact]
    assert len(
        table_semantics._table_representation_sha256(  # noqa: SLF001
            exact,
            table_semantics.perf_counter() + 0.500,
            value_is_plain=True,
        )
    ) == 64

    overflow: object = [exact]
    with pytest.raises(ValueError, match="nesting limit exceeded"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            overflow,
            table_semantics.perf_counter() + 0.500,
            value_is_plain=True,
        )

    with pytest.raises(ValueError, match="string limit exceeded"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            "x" * 1_048_577,
            table_semantics.perf_counter() + 0.500,
            value_is_plain=True,
        )


@pytest.mark.parametrize(
    "hostile",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {"$p04_f64": "collision"},
        {"café": 1},
        {1: "non-text key"},
        (1, 2),
        b"not-json",
    ],
)
def test_streamed_representation_digest_rejects_hostile_values(
    hostile: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            hostile,
            table_semantics.perf_counter() + 0.500,
        )


def test_streamed_representation_digest_rejects_cycle_depth_and_deadline() -> None:
    cyclic: list[object] = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            cyclic,
            table_semantics.perf_counter() + 0.500,
        )

    nested: object = "leaf"
    for _index in range(33):
        nested = [nested]
    with pytest.raises(ValueError, match="nesting limit"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            nested,
            table_semantics.perf_counter() + 0.500,
        )

    with pytest.raises(TimeoutError, match="deadline"):
        table_semantics._table_representation_sha256(  # noqa: SLF001
            [1],
            table_semantics.perf_counter() - 0.001,
        )


def test_paired_input_helper_preserves_disabled_identity_and_enabled_copies() -> None:
    raw = _repeated_table()
    disabled = table_semantics.prepare_docling_table_inputs(
        raw,
        {1: 120.0},
        {},
        table_span_fidelity_enabled=False,
    )
    document_deadline = table_semantics.table_span_fidelity_document_deadline()
    page_deadline = table_semantics.table_span_fidelity_page_deadline(
        document_deadline
    )
    enabled = table_semantics.prepare_docling_table_inputs(
        raw,
        {1: 120.0},
        {},
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=page_deadline,
        table_span_fidelity_document_deadline=document_deadline,
    )

    assert disabled == [raw, raw]
    assert disabled[0] is raw and disabled[1] is raw
    assert enabled[0] == raw and enabled[1] == raw
    assert enabled[0] is not raw and enabled[1] is not raw
    assert enabled[0] is not enabled[1]


def test_expired_document_deadline_restores_all_snapshots_and_finalizer_strips() -> None:
    first = _seal(_repeated_table(), finalize=False)
    second = _seal(_spanned_table(), finalize=False)
    first_expected = deepcopy(first["_p04_predecessor_snapshot"])
    second_expected = deepcopy(second["_p04_predecessor_snapshot"])
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [first, second],
        }
    ]

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() - 0.001
        ),
    )

    assert first == first_expected
    assert second == second_expected
    assert "_p04_predecessor_snapshot" not in first
    assert "_p04_predecessor_snapshot" not in second


def test_unrelated_large_body_is_not_charged_to_phase04_sidecar_budget() -> None:
    table = _seal(_spanned_table(), finalize=False)
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [
                {"type": "text", "value": "x" * (8 * 1024 * 1024 + 1)},
                table,
            ],
        }
    ]

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert pages[0]["items"][0]["value"].endswith("x")
    assert table["table_evidence"]["status"] == "valid"
    assert "_p04_predecessor_snapshot" not in table


def test_structure_content_accepts_exact_65536_cells_without_4096_truncation() -> None:
    record = [
        0,
        0,
        1,
        1,
        "",
        False,
        False,
        False,
        0,
        0.0,
        0.0,
        0.0,
        0.0,
        "#/tables/0",
        False,
    ]
    records = [record] * 65536

    content = table_semantics._table_structure_source_content(  # noqa: SLF001
        "#/tables/0",
        256,
        256,
        records,
        table_semantics.perf_counter() + 5.000,
    )

    assert len(content[-1]) == 65536
    with pytest.raises(ValueError, match="iteration limit exceeded"):
        table_semantics._table_structure_source_content(  # noqa: SLF001
            "#/tables/0",
            256,
            256,
            records + [record],
            table_semantics.perf_counter() + 5.000,
        )


def test_sidecar_byte_limit_accepts_exact_8_mib_and_rejects_plus_one() -> None:
    chunks = ["x" * 1048576 for _ in range(7)]
    partial = {"chunks": chunks}
    partial_size = len(
        json.dumps(
            partial,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    final_size = 8388608 - partial_size - 3
    exact = {"chunks": chunks + ["x" * final_size]}

    encoded = table_semantics._canonical_table_json_bytes(  # noqa: SLF001
        exact,
        8388608,
        table_semantics.perf_counter() + 5.000,
    )

    assert len(encoded) == 8388608
    exact["chunks"][-1] += "x"
    with pytest.raises(ValueError, match="JSON limit exceeded"):
        table_semantics._canonical_table_json_bytes(  # noqa: SLF001
            exact,
            8388608,
            table_semantics.perf_counter() + 5.000,
        )


def _pad_marked_table_to_exact_size(
    table: dict[str, Any], target_size: int
) -> None:
    table["relationships"] = [{"padding": ""} for _index in range(8)]
    public_table = {
        key: value
        for key, value in table.items()
        if key != "_p04_predecessor_snapshot"
    }
    base_size = len(
        json.dumps(
            public_table,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    remaining = target_size - base_size
    assert 0 <= remaining <= 8 * 1048576
    for record in table["relationships"]:
        padding_size = min(remaining, 1048576)
        record["padding"] = "x" * padding_size
        remaining -= padding_size
    assert remaining == 0
    assert len(
        json.dumps(
            public_table,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ) == target_size


def test_marked_table_item_exact_8_mib_is_inclusive_and_plus_one_rolls_back(
) -> None:
    exact = _seal(_spanned_table(), finalize=False)
    _pad_marked_table_to_exact_size(exact, 8388608)
    exact_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [exact],
        }
    ]

    seal_table_pages(
        exact_pages,
        SOURCE_SHA256,
        ["Years ended 2025 2024 2023"],
        table_span_fidelity_enabled=True,
    )
    assert exact["table_evidence"]["status"] == "valid"
    finalize_table_pages(
        exact_pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    assert exact["table_evidence"]["status"] == "valid"
    assert "_p04_predecessor_snapshot" not in exact

    overflow = _seal(_spanned_table(), finalize=False)
    _pad_marked_table_to_exact_size(overflow, 8388609)
    expected = deepcopy(overflow["_p04_predecessor_snapshot"])
    expected["relationships"] = deepcopy(overflow["relationships"])
    overflow_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [overflow],
        }
    ]

    seal_table_pages(
        overflow_pages,
        SOURCE_SHA256,
        ["Years ended 2025 2024 2023"],
        table_span_fidelity_enabled=True,
    )

    assert overflow == expected
    assert "table_evidence" not in overflow
    assert "_p04_predecessor_snapshot" not in overflow


def test_document_sidecar_exact_limit_is_inclusive_then_overflow_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_tables = [
        _seal(
            _raw_table(
                1,
                1,
                [_raw_cell(0, 0, str(index))],
                self_ref=f"#/tables/exact-{index}",
            ),
            finalize=False,
        )
        for index in range(2)
    ]
    deadline = table_semantics.perf_counter() + 5.000
    exact_limit = sum(
        len(
            table_semantics._canonical_table_json_bytes(  # noqa: SLF001
                table["table_evidence"], 8388608, deadline
            )
        )
        for table in exact_tables
    )
    monkeypatch.setattr(
        table_semantics,
        "_TABLE_DOCUMENT_SIDECAR_MAX_BYTES",
        exact_limit,
    )
    exact_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": exact_tables,
        }
    ]

    seal_table_pages(
        exact_pages,
        SOURCE_SHA256,
        ["0 1"],
        table_span_fidelity_enabled=True,
    )

    assert all("table_evidence" in table for table in exact_tables)

    overflow_tables = [deepcopy(table) for table in exact_tables]
    overflow_tables.append(
        _seal(
            _raw_table(
                1,
                1,
                [_raw_cell(0, 0, "overflow")],
                self_ref="#/tables/overflow",
            ),
            finalize=False,
        )
    )
    expected = [
        deepcopy(table["_p04_predecessor_snapshot"])
        for table in overflow_tables
    ]
    overflow_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": overflow_tables,
        }
    ]

    seal_table_pages(
        overflow_pages,
        SOURCE_SHA256,
        ["0 1 overflow"],
        table_span_fidelity_enabled=True,
    )

    assert overflow_tables == expected
    assert all("table_evidence" not in table for table in overflow_tables)
    assert all(
        "_p04_predecessor_snapshot" not in table
        for table in overflow_tables
    )


def test_expired_cleanup_restores_every_snapshot_without_marker_leak() -> None:
    tables = [
        _seal(_repeated_table(), finalize=False),
        _seal(_spanned_table(), finalize=False),
    ]
    expected = [
        deepcopy(table["_p04_predecessor_snapshot"])
        for table in tables
    ]
    pages = [{"items": tables}]

    table_semantics._restore_all_table_predecessors(  # noqa: SLF001
        pages, table_semantics.perf_counter() - 100.0
    )

    assert tables == expected
    assert all("table_evidence" not in table for table in tables)
    assert all("_p04_predecessor_snapshot" not in table for table in tables)


@pytest.mark.parametrize("attack", ["cycle", "oversize", "depth"])
def test_invalid_private_snapshot_is_never_installed_during_rollback(
    attack: str,
) -> None:
    table = _seal(_repeated_table(), finalize=False)
    if attack == "cycle":
        hostile_snapshot: dict[str, Any] = {"type": "table"}
        hostile_snapshot["cycle"] = hostile_snapshot
    elif attack == "oversize":
        hostile_snapshot = {
            "type": "table",
            "payload": "x" * 1048577,
        }
    else:
        nested: list[Any] = []
        root = nested
        for _index in range(33):
            child: list[Any] = []
            nested.append(child)
            nested = child
        hostile_snapshot = {"type": "table", "nested": root}
    table["_p04_predecessor_snapshot"] = hostile_snapshot
    table["table_evidence"]["status"] = "hostile"
    table["rows"][0][0] = "UNAUTHORIZED P04 PROJECTION"

    with pytest.raises(ValueError, match="predecessor.*unavailable"):
        replay_table_semantics(table, table["table_evidence"])

    assert table == {}


def test_document_rollback_with_one_corrupt_snapshot_never_returns_mixed_output() -> None:
    first = _seal(_repeated_table(), finalize=False)
    second = _seal(_spanned_table(), finalize=False)
    second_snapshot: dict[str, Any] = {"type": "table"}
    second_snapshot["cycle"] = second_snapshot
    second["_p04_predecessor_snapshot"] = second_snapshot
    first["rows"][0][0] = "FIRST UNAUTHORIZED P04 PROJECTION"
    second["rows"][0][0] = "SECOND UNAUTHORIZED P04 PROJECTION"
    pages = [{"items": [first, second]}]

    with pytest.raises(ValueError, match="predecessor.*unavailable"):
        table_semantics._restore_all_table_predecessors(  # noqa: SLF001
            pages,
            table_semantics.perf_counter() + 0.500,
        )

    assert first == {}
    assert second == {}


@pytest.mark.parametrize("operation", ["seal", "finalize"])
def test_document_commit_with_late_corrupt_snapshot_quarantines_all_candidates(
    operation: str,
) -> None:
    first = _seal(_repeated_table(), finalize=False)
    second = _seal(_spanned_table(), finalize=False)
    hostile_snapshot: dict[str, Any] = {"type": "table"}
    hostile_snapshot["cycle"] = hostile_snapshot
    second["_p04_predecessor_snapshot"] = hostile_snapshot
    first["rows"][0][0] = "FIRST UNAUTHORIZED P04 PROJECTION"
    second["rows"][0][0] = "SECOND UNAUTHORIZED P04 PROJECTION"
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [first, second],
        }
    ]

    with pytest.raises(ValueError, match="predecessor.*unavailable"):
        if operation == "seal":
            seal_table_pages(
                pages,
                SOURCE_SHA256,
                ["corrupt predecessor"],
                table_span_fidelity_enabled=True,
            )
        else:
            finalize_table_pages(
                pages,
                SOURCE_SHA256,
                table_span_fidelity_enabled=True,
            )

    assert first == {}
    assert second == {}


@pytest.mark.parametrize("failure_type", [MemoryError, RecursionError])
def test_document_seal_resource_failure_restores_every_predecessor(
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    tables = [
        _seal(_repeated_table(), finalize=False),
        _seal(_spanned_table(), finalize=False),
    ]
    expected = [
        deepcopy(table["_p04_predecessor_snapshot"])
        for table in tables
    ]
    pages = [{"items": tables}]

    def resource_failure(*_args: object, **_kwargs: object) -> int:
        raise failure_type("injected table allocation failure")

    monkeypatch.setattr(
        table_semantics,
        "_seal_table_page_overlays",
        resource_failure,
    )
    state: dict[str, Any] = {}

    seal_table_pages(
        pages,
        SOURCE_SHA256,
        ["allocation failure"],
        table_span_fidelity_enabled=True,
        table_span_fidelity_state=state,
    )

    assert state["custody_rejected"] is True
    assert tables == expected


@pytest.mark.parametrize("failure_type", [MemoryError, RecursionError])
def test_rollback_copy_failure_quarantines_every_table_candidate(
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    tables = [
        _seal(_repeated_table(), finalize=False),
        _seal(_spanned_table(), finalize=False),
    ]
    pages = [{"items": tables}]

    def resource_failure(_value: object) -> object:
        raise failure_type("injected predecessor copy failure")

    monkeypatch.setattr(table_semantics, "deepcopy", resource_failure)

    with pytest.raises(ValueError, match="predecessor.*unavailable"):
        table_semantics._restore_all_table_predecessors(  # noqa: SLF001
            pages,
            table_semantics.perf_counter() + 0.500,
        )

    assert tables == [{}, {}]


def test_sidecar_validation_timeout_restores_all_tables_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tables = [
        _seal(_repeated_table(), finalize=False),
        _seal(_spanned_table(), finalize=False),
    ]
    expected = [
        deepcopy(table["_p04_predecessor_snapshot"])
        for table in tables
    ]
    original = table_semantics._canonical_table_json_size  # noqa: SLF001

    def timeout_sidecar(value: object, maximum: int, deadline: float) -> int:
        if isinstance(value, dict) and value.get("policy_id") == "p04-table-evidence-v1":
            raise TimeoutError("table operation deadline exceeded")
        return original(value, maximum, deadline)

    monkeypatch.setattr(
        table_semantics,
        "_canonical_table_json_size",
        timeout_sidecar,
    )
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": tables,
        }
    ]

    seal_table_pages(
        pages,
        SOURCE_SHA256,
        ["table content"],
        table_span_fidelity_enabled=True,
    )

    assert tables == expected
    assert all("table_evidence" not in table for table in tables)
    assert all("_p04_predecessor_snapshot" not in table for table in tables)


def test_hostile_overlay_value_is_restored_before_replay_returns() -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    table["cells"][0]["text"] = "hostile\ud800value"

    returned = replay_table_semantics(table, sidecar)

    assert returned is table
    assert table == expected
    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


def test_hostile_marked_page_is_restored_before_seal_returns() -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    table["cells"][0]["text"] = "hostile\ud800value"
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    seal_table_pages(
        pages,
        SOURCE_SHA256,
        [],
        table_span_fidelity_enabled=True,
    )

    assert table == expected
    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


def test_nonvalid_overlay_retains_later_unrelated_relationship_metadata() -> None:
    raw = _raw_table(
        1,
        2,
        [
            _raw_cell(0, 0, "Span", col_span=2),
            _raw_cell(0, 1, "Collision"),
        ],
    )
    table = _seal(raw, finalize=False)
    table["caption_ids"] = ["caption-1"]
    table["caption_of"] = ["table-1"]
    table["relationships"] = [
        {"type": "caption", "target_id": "caption-1"}
    ]
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert table["table_evidence"]["status"] == "structural_failure"
    assert table["caption_ids"] == ["caption-1"]
    assert table["caption_of"] == ["table-1"]
    assert table["relationships"] == [
        {"type": "caption", "target_id": "caption-1"}
    ]
    assert "_p04_predecessor_snapshot" not in table


def test_replay_charges_each_physical_page_without_cross_page_spend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seal(_spanned_table(), finalize=False)
    second = _seal(
        _spanned_table(),
        finalize=False,
        physical_page_index=2,
    )
    pages = [
        {
            "page_index": page_index,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [table],
        }
        for page_index, table in ((1, first), (2, second))
    ]
    now = [100.0]
    original_replay = table_semantics._replay_table_overlay  # noqa: SLF001

    def consuming_replay(*args: Any, **kwargs: Any) -> None:
        now[0] += 0.300
        original_replay(*args, **kwargs)

    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    monkeypatch.setattr(
        table_semantics,
        "_replay_table_overlay",
        consuming_replay,
    )
    page_deadlines = {1: 100.5, 2: 100.5}

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=105.0,
        table_span_fidelity_page_deadlines=page_deadlines,
    )

    assert first["table_evidence"]["status"] == "valid"
    assert second["table_evidence"]["status"] == "valid"
    assert page_deadlines == {1: 100.8, 2: 100.8}
    assert now[0] == pytest.approx(100.6)


def test_page_segment_completion_accepts_exact_and_rejects_epsilon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: 100.0)
    exact = {1: 100.5, 2: 100.5}

    table_semantics._complete_table_page_segment(
        exact,
        1,
        100.0,
        100.5,
        105.0,
    )

    assert exact == {1: 100.5, 2: 101.0}
    epsilon = {1: 100.5, 2: 100.5}
    with pytest.raises(TimeoutError, match="page deadline"):
        table_semantics._complete_table_page_segment(
            epsilon,
            1,
            100.0,
            100.500001,
            105.0,
        )
    assert epsilon[1] == 100.5
    assert epsilon[2] == pytest.approx(101.000001)


def test_repeated_same_page_replays_share_one_cumulative_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _seal(_spanned_table(), finalize=False)
    second = _seal(_spanned_table(), finalize=False)
    expected = [
        deepcopy(first["_p04_predecessor_snapshot"]),
        deepcopy(second["_p04_predecessor_snapshot"]),
    ]
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [first, second],
        }
    ]
    now = [100.0]
    original_replay = table_semantics._replay_table_overlay  # noqa: SLF001

    def consuming_replay(*args: Any, **kwargs: Any) -> None:
        now[0] += 0.300
        original_replay(*args, **kwargs)

    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    monkeypatch.setattr(
        table_semantics,
        "_replay_table_overlay",
        consuming_replay,
    )

    finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=105.0,
        table_span_fidelity_page_deadlines={1: 100.5},
    )

    assert pages[0]["items"] == expected
    assert all("table_evidence" not in table for table in pages[0]["items"])
    assert all(
        "_p04_predecessor_snapshot" not in table
        for table in pages[0]["items"]
    )


def test_downstream_relationship_exact_list_bound_commits_and_plus_one_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hold the clock still so this contract proves the inclusive resource
    # boundary independently of machine speed. Runtime deadline tests exercise
    # the same finalizer with a moving deterministic clock elsewhere.
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: 0.0)
    exact = _seal(_spanned_table(), finalize=False)
    exact["relationships"] = [{}] * 65536
    exact_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [exact],
        }
    ]

    finalize_table_pages(
        exact_pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert exact["table_evidence"]["status"] == "valid"
    assert len(exact["relationships"]) == 65536
    assert exact["relationships"] == [{}] * 65536
    assert "_p04_predecessor_snapshot" not in exact

    overflow = _seal(_spanned_table(), finalize=False)
    predecessor = deepcopy(overflow["_p04_predecessor_snapshot"])
    overflow["relationships"] = [{}] * 65537
    overflow_pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [overflow],
        }
    ]

    finalize_table_pages(
        overflow_pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert overflow == predecessor
    assert "relationships" not in overflow
    assert "table_evidence" not in overflow
    assert "_p04_predecessor_snapshot" not in overflow


@pytest.mark.parametrize("field", ["type", "engine", "source", "bbox"])
def test_snapshot_refresh_never_adopts_hostile_core_field_mutation(
    field: str,
) -> None:
    table = _seal(_repeated_table(), finalize=False)
    expected = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    if field == "bbox":
        table[field] = {
            "x": 20.0,
            "y": 20.0,
            "width": 20.0,
            "height": 20.0,
            "unit": "pt",
        }
    elif field == "type":
        table[field] = "chart"
    elif field == "engine":
        table[field] = "evil"
    else:
        table[field] = "derived"

    replay_table_semantics(table, sidecar)

    assert table == expected
    assert "table_evidence" not in table
    assert "_p04_predecessor_snapshot" not in table


def test_recovery_only_overlay_text_cannot_suppress_body_before_rollback() -> None:
    table = _seal(_repeated_table(), finalize=False)
    table["rows"][0][0] = "RECOVERY_ONLY_TOKEN"
    body_item = {
        "type": "text",
        "value": "RECOVERY_ONLY_TOKEN",
        "md": "RECOVERY_ONLY_TOKEN",
        "bbox": {
            "x": 1.0,
            "y": 31.0,
            "width": 40.0,
            "height": 10.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }
    pages = [
        {
            "page_index": 1,
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "items": [],
            "warnings": [],
        }
    ]

    _merge_body_items(
        pages,
        {1: [body_item]},
        {1: [table]},
        {},
        {},
        {},
        table_decision_views={
            1: [table["_p04_predecessor_snapshot"]]
        },
    )

    emitted_body = next(
        item
        for item in pages[0]["items"]
        if item.get("value") == "RECOVERY_ONLY_TOKEN"
    )
    emitted_table = next(
        item for item in pages[0]["items"] if item.get("type") == "table"
    )
    expected_table = deepcopy(
        emitted_table["_p04_predecessor_snapshot"]
    )
    seal_table_pages(
        pages,
        SOURCE_SHA256,
        ["RECOVERY_ONLY_TOKEN"],
        table_span_fidelity_enabled=True,
    )

    assert emitted_body in pages[0]["items"]
    assert emitted_table == expected_table
    assert "table_evidence" not in emitted_table
    assert "_p04_predecessor_snapshot" not in emitted_table


def _ocr_region(
    text: str,
    *,
    role: str,
    bbox: dict[str, float],
    region_confidence: float | None = None,
) -> ImageRegion:
    return ImageRegion(
        page_index=1,
        object_index=1,
        bbox=deepcopy(bbox),
        pixel_width=120,
        pixel_height=40,
        area_ratio=1.0 if role == "page_source" else 0.05,
        text=text,
        lines=[
            OCRLine(
                text=text,
                bbox=deepcopy(bbox),
                confidence=0.93,
                word_count=max(len(text.split()), 1),
            )
        ],
        confidence=region_confidence,
        region_role=role,
        coordinate_unit="pt",
    )


def _empty_runtime_page() -> dict[str, Any]:
    return {
        "page_index": 1,
        "page_width": 300.0,
        "page_height": 120.0,
        "unit": "pt",
        "items": [],
        "warnings": [],
    }


def test_recovery_only_overlay_text_cannot_suppress_page_source_ocr() -> None:
    table = _seal(_repeated_table(), finalize=False)
    snapshot = table["_p04_predecessor_snapshot"]
    table["rows"][0][0] = "RECOVERY_ONLY_PAGE_OCR_TOKEN"
    body_items: dict[int, list[dict[str, Any]]] = {1: []}
    region = _ocr_region(
        "RECOVERY_ONLY_PAGE_OCR_TOKEN",
        role="page_source",
        bbox={"x": 1.0, "y": 31.0, "width": 80.0, "height": 10.0},
    )

    _supplement_unrepresented_raster_ocr(
        body_items,
        {1: [table]},
        {1: [region]},
        table_decision_views={1: [snapshot]},
    )

    assert [item["value"] for item in body_items[1]] == [
        "RECOVERY_ONLY_PAGE_OCR_TOKEN"
    ]
    assert table["_p04_predecessor_snapshot"] is snapshot
    assert "table_evidence" in table


def test_contained_image_confidence_is_exact_in_overlay_snapshot_and_rollback() -> None:
    table = _seal(_repeated_table(), finalize=False)
    predecessor = deepcopy(table["_p04_predecessor_snapshot"])
    region = _ocr_region(
        "IMAGE CONFIDENCE TOKEN",
        role="content_region",
        bbox={"x": 10.0, "y": 40.0, "width": 40.0, "height": 10.0},
    )

    baseline_pages = [_empty_runtime_page()]
    _merge_body_items(
        baseline_pages,
        {},
        {1: [predecessor]},
        {1: [region]},
        {},
        {},
    )
    _enrich_ocr_confidence(baseline_pages, {1: [region]})

    candidate_pages = [_empty_runtime_page()]
    _merge_body_items(
        candidate_pages,
        {},
        {1: [table]},
        {1: [region]},
        {},
        {},
        table_decision_views={
            1: [table["_p04_predecessor_snapshot"]]
        },
    )
    _enrich_ocr_confidence(candidate_pages, {1: [region]})
    emitted = next(
        item
        for item in candidate_pages[0]["items"]
        if item.get("type") == "table"
    )
    snapshot = emitted["_p04_predecessor_snapshot"]
    baseline = next(
        item
        for item in baseline_pages[0]["items"]
        if item.get("type") == "table"
    )

    assert emitted["embedded_images"][0]["confidence"] == 0.93
    assert (
        emitted["embedded_images"][0]["confidence_source"]
        == "matched_page_ocr"
    )
    assert snapshot["embedded_images"] == emitted["embedded_images"]
    assert snapshot == baseline
    assert "table_evidence" in emitted

    emitted["table_evidence"]["policy_id"] = "forged-policy"
    seal_table_pages(
        candidate_pages,
        SOURCE_SHA256,
        [""],
        table_span_fidelity_enabled=True,
    )

    assert candidate_pages == baseline_pages
    assert "table_evidence" not in emitted
    assert "_p04_predecessor_snapshot" not in emitted


def test_marker_free_body_merge_does_not_run_early_confidence_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table = _seal(_repeated_table(), finalize=False)[
        "_p04_predecessor_snapshot"
    ]
    region = _ocr_region(
        "MARKER FREE IMAGE",
        role="content_region",
        bbox={"x": 10.0, "y": 40.0, "width": 40.0, "height": 10.0},
    )
    calls = 0
    original = document_pipeline._enrich_ocr_confidence

    def counted(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        original(*args, **kwargs)

    monkeypatch.setattr(
        document_pipeline,
        "_enrich_ocr_confidence",
        counted,
    )

    _merge_body_items(
        [_empty_runtime_page()],
        {},
        {1: [table]},
        {1: [region]},
        {},
        {},
    )

    assert calls == 0


def _two_table_runtime_document() -> dict[str, Any]:
    first = _repeated_table()
    first["self_ref"] = "#/tables/0"
    second = deepcopy(first)
    second["self_ref"] = "#/tables/1"

    def text_item(index: int, value: str, y: float) -> dict[str, Any]:
        return {
            "self_ref": f"#/texts/{index}",
            "label": "text",
            "text": value,
            "prov": [
                {
                    "page_no": 1,
                    "bbox": {
                        "l": 1.0,
                        "t": y,
                        "r": 90.0,
                        "b": y + 10.0,
                        "coord_origin": "TOPLEFT",
                    },
                }
            ],
        }

    hierarchy = text_item(0, "HIERARCHY ANCHOR", 100.0)
    recovery = text_item(1, "RECOVERY ONLY BODY TOKEN", 31.0)
    return {
        "tables": [first, second],
        "texts": [hierarchy, recovery],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": hierarchy["self_ref"]},
                {"$ref": recovery["self_ref"]},
                {"$ref": first["self_ref"]},
                {"$ref": second["self_ref"]},
            ]
        },
    }


@pytest.mark.parametrize(
    "map_corruption",
    [
        "missing",
        "forged_nonidentity",
        "misaligned_length",
        "orphan_page",
        "orphan_page_no_state",
        "orphan_page_non_dict_state",
    ],
)
def test_corrupt_private_map_replays_atomic_page_to_full_flag_off_output(
    map_corruption: str,
) -> None:
    raw = _two_table_runtime_document()
    native_texts = [
        "HIERARCHY ANCHOR RECOVERY ONLY BODY TOKEN United States 0 1 2 3 4"
    ]
    baseline_body, baseline_docling = _normalize_docling_body(
        raw,
        {1: 120.0},
        native_texts,
        {},
        {},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    baseline_views: dict[int, list[dict[str, Any]]] = {}
    baseline_tables = _merge_tables(
        baseline_docling,
        {},
        table_decision_views_sink=baseline_views,
    )

    captured: dict[int, list[dict[str, Any]]] = {}
    state: dict[str, Any] = {}
    candidate_body, candidate_docling = _normalize_docling_body(
        raw,
        {1: 120.0},
        native_texts,
        {},
        {},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() + 5.0
        ),
        table_span_fidelity_page_deadlines={},
        table_span_fidelity_state=state,
        table_decision_views_sink=captured,
    )
    assert len(candidate_docling[1]) == 2
    assert all("table_evidence" in table for table in candidate_docling[1])
    candidate_docling[1][0]["rows"][0][0] = "RECOVERY ONLY BODY TOKEN"

    if map_corruption == "missing":
        corrupted = None
    elif map_corruption == "forged_nonidentity":
        corrupted = {
            1: [deepcopy(captured[1][0]), captured[1][1]]
        }
    elif map_corruption == "misaligned_length":
        corrupted = {1: [captured[1][0]]}
    else:
        corrupted = {1: list(captured[1]), 99: []}

    if map_corruption == "orphan_page_no_state":
        decision_state: Any = None
    elif map_corruption == "orphan_page_non_dict_state":
        decision_state = []
    else:
        decision_state = state

    candidate_views: dict[int, list[dict[str, Any]]] = {}
    candidate_tables = _merge_tables(
        candidate_docling,
        {},
        table_span_fidelity_enabled=True,
        table_decision_views=corrupted,
        table_decision_views_sink=candidate_views,
        table_span_fidelity_state=decision_state,
    )
    region = _ocr_region(
        "MAP IMAGE TOKEN",
        role="content_region",
        bbox={"x": 10.0, "y": 40.0, "width": 40.0, "height": 10.0},
    )
    baseline_pages = [_empty_runtime_page()]
    candidate_pages = [_empty_runtime_page()]
    _merge_body_items(
        baseline_pages,
        baseline_body,
        baseline_tables,
        {1: [region]},
        {},
        {},
        table_decision_views=baseline_views,
    )
    _merge_body_items(
        candidate_pages,
        candidate_body,
        candidate_tables,
        {1: [region]},
        {},
        {},
        table_decision_views=candidate_views,
        table_span_fidelity_state=decision_state,
    )
    _enrich_ocr_confidence(baseline_pages, {1: [region]})
    _enrich_ocr_confidence(candidate_pages, {1: [region]})

    if any(
        "table_evidence" in item
        for item in candidate_pages[0]["items"]
        if type(item) is dict
    ):
        try:
            detach_table_overlays_for_phase03(
                candidate_pages,
                deadline=table_semantics.perf_counter() + 0.500,
            )
        except (TimeoutError, TypeError, ValueError):
            _restore_all_table_predecessors(
                candidate_pages,
                table_semantics.perf_counter() + 0.500,
            )

    if type(decision_state) is dict:
        assert decision_state["custody_rejected"] is True
    else:
        assert all(
            "table_evidence" not in table
            and "_p04_predecessor_snapshot" not in table
            for table in candidate_tables[1]
        )
    assert candidate_pages == baseline_pages
    assert [
        item["value"]
        for item in candidate_pages[0]["items"]
        if item.get("type") == "text"
    ] == ["HIERARCHY ANCHOR", "RECOVERY ONLY BODY TOKEN"]
    assert sum(
        item.get("type") == "table"
        for item in candidate_pages[0]["items"]
    ) == 2
    assert all(
        "table_evidence" not in item
        and "_p04_predecessor_snapshot" not in item
        for item in candidate_pages[0]["items"]
        if item.get("type") == "table"
    )


def test_direct_image_px_detach_and_finalize_roll_back_exactly_to_flag_off() -> None:
    marked = _seal(_repeated_table(), finalize=False)
    predecessor = deepcopy(marked["_p04_predecessor_snapshot"])
    candidate_pages = [
        {
            **_empty_runtime_page(),
            "items": [marked],
        }
    ]
    baseline_pages = [
        {
            **_empty_runtime_page(),
            "items": [predecessor],
        }
    ]

    _apply_image_provenance_and_units(candidate_pages, {})
    _apply_image_provenance_and_units(baseline_pages, {})
    transaction = detach_table_overlays_for_phase03(
        candidate_pages,
        deadline=table_semantics.perf_counter() + 0.500,
    )

    assert candidate_pages == baseline_pages
    assert candidate_pages[0]["unit"] == "px"
    assert candidate_pages[0]["items"][0]["bbox"]["unit"] == "px"

    rebound = rebind_table_overlays_after_phase03(
        candidate_pages,
        transaction,
        deadline=table_semantics.perf_counter() + 0.500,
        transaction_is_owned=True,
    )
    assert "table_evidence" in rebound[0]["items"][0]
    finalize_table_pages(
        rebound,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert rebound == baseline_pages
    assert "table_evidence" not in rebound[0]["items"][0]
    assert "_p04_predecessor_snapshot" not in rebound[0]["items"][0]
