"""Production and reviewed-document acceptance tests for P04-US01.

The readiness/oracle suite freezes what may be claimed.  This module exercises
the actual table pipeline and checks that only source-supported structure is
authoritative.  Candidate reconciliation, ownership gating, and continued-
table merging remain disabled because they belong to later Phase 04 stories.
"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.config import Settings
from app.models import ContentItem, ParseResult
from app.services.pipeline import _docling_table_item, parse_document
from app.services.ir import build_document_ir
from app.services.opaque_group_custody import stable_id
from app.services.presentation import (
    _build_canonical_presentation_from_validated,
    build_canonical_presentation,
)
from app.services.serializer import to_markdown
from app.services.table_semantics import finalize_table_pages, seal_table_pages
from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_CONFIGURATION,
    PREDECESSOR_OUTPUT_ROOT,
)
from tests.fixtures.phase_04.tables import metrics
from tests.fixtures.phase_04.tables.content_bbox_oracle import (
    EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION,
    source_content_bbox_oracle_sha256,
)
from tests.fixtures.phase_04.tables.oracle import (
    EXHIBIT7_EXACT,
    P04_US01_REAL_ORACLE,
)
from tests.fixtures.phase_04.tables.synthetic import (
    SyntheticGrid,
    build_synthetic_fixture,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _refresh_test_canonical_views(payload: dict[str, Any]) -> None:
    def render(blocks: list[Mapping[str, Any]], field: str) -> str:
        values = [
            str(block.get(field) or "").strip()
            for block in blocks
            if block.get("omission_reason") is None
            and str(block.get(field) or "").strip()
        ]
        return "\n\n".join(values).rstrip() + "\n" if values else ""

    def view(blocks: list[Mapping[str, Any]]) -> dict[str, Any]:
        included = [
            block
            for block in blocks
            if block.get("omission_reason") is None
        ]
        return {
            "block_ids": [str(block["id"]) for block in included],
            "markdown": render(included, "markdown"),
            "text": render(included, "text"),
        }

    canonical = payload["canonical_presentation"]
    all_blocks: list[Mapping[str, Any]] = []
    for page in canonical["pages"]:
        blocks = page["blocks"]
        all_blocks.extend(blocks)
        page["full"] = view(blocks)
        for scope in ("body", "header", "footer"):
            page[scope] = view(
                [block for block in blocks if block["scope"] == scope]
            )
    canonical["full"] = view(all_blocks)
    for scope in ("body", "header", "footer"):
        canonical[scope] = view(
            [block for block in all_blocks if block["scope"] == scope]
        )


def _source_sha256(case: str) -> str:
    return next(
        source.sha256
        for source in P04_US01_REAL_ORACLE.sources
        if source.case_id == case
    )


def _settings(*, span_fidelity: bool) -> Settings:
    return Settings(
        **PREDECESSOR_CONFIGURATION,
        table_span_fidelity_enabled=span_fidelity,
    )


@lru_cache(maxsize=None)
def _parse_real(case: str, span_fidelity: bool) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    source = path.read_bytes()
    assert hashlib.sha256(source).hexdigest() == _source_sha256(case)
    return parse_document(
        source,
        path.name,
        _settings(span_fidelity=span_fidelity),
    ).model_dump(mode="json", exclude_none=True)


@lru_cache(maxsize=None)
def _frozen_predecessor(case: str) -> dict[str, Any]:
    path = WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case / "our-output.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _tables(
    payload: Mapping[str, Any],
    *,
    page_index: int | None = None,
) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        if page_index is None or page["page_index"] == page_index
        for item in page["items"]
        if item.get("type") == "table"
    ]


def _one_table(payload: Mapping[str, Any], page_index: int) -> dict[str, Any]:
    matches = _tables(payload, page_index=page_index)
    assert len(matches) == 1
    return matches[0]


def _canonical_block_for_public_item(
    payload: Mapping[str, Any],
    *,
    page_index: int,
    public_item_id: str,
    raw_free: bool = False,
) -> dict[str, Any]:
    canonical = payload["canonical_presentation"]
    if raw_free:
        canonical = build_canonical_presentation(
            build_document_ir(
                {
                    "document": deepcopy(payload["document"]),
                    "pages": deepcopy(payload["pages"]),
                }
            )
        ).model_dump(mode="json", exclude_none=True)
    public_page = payload["pages"][page_index - 1]
    canonical_page = canonical["pages"][page_index - 1]
    matches = [
        block
        for item, block in zip(
            public_page["items"],
            canonical_page["blocks"],
            strict=True,
        )
        if item.get("id") == public_item_id
    ]
    assert len(matches) == 1
    return matches[0]


def _table_projection(table: Mapping[str, Any]) -> dict[str, Any]:
    projection = deepcopy(dict(table))
    projection.pop("table_evidence", None)
    return projection


def _sidecar(table: Mapping[str, Any], status: str) -> dict[str, Any]:
    sidecar = table.get("table_evidence")
    assert isinstance(sidecar, dict)
    assert sidecar["policy_id"] == "p04-table-evidence-v1"
    assert sidecar["version"] == "1.1"
    assert sidecar["scope"] == ["P04-US01"]
    assert sidecar["status"] == status
    assert sidecar["reconciliation"] is None
    assert sidecar["gate"] is None
    assert sidecar["continuation"] is None
    return sidecar


def _valid_sidecar(table: Mapping[str, Any]) -> dict[str, Any]:
    return _sidecar(table, "valid")


def _stable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = json.loads(json.dumps(payload, ensure_ascii=False))
    processing = stable.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
        for summary_name in ("form_semantics", "outline_structure"):
            summary = processing.get(summary_name)
            if isinstance(summary, dict):
                for key in ("extraction_ms", "projection_ms", "total_ms"):
                    summary.pop(key, None)
    return stable


def _raw_synthetic_table(fixture: SyntheticGrid) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for cell in fixture.cells:
        box = cell.bbox
        cells.append(
            {
                "start_row_offset_idx": cell.row,
                "end_row_offset_idx": cell.row + cell.row_span,
                "start_col_offset_idx": cell.column,
                "end_col_offset_idx": cell.column + cell.col_span,
                "row_span": cell.row_span,
                "col_span": cell.col_span,
                "text": cell.text,
                "column_header": cell.column_header,
                "row_header": cell.row_header,
                "row_section": False,
                "ref": {"$ref": f"#/texts/{cell.cell_id}"},
                "bbox": {
                    "l": box.x,
                    "t": box.y,
                    "r": box.x + box.width,
                    "b": box.y + box.height,
                    "coord_origin": "TOPLEFT",
                },
            }
        )
    return {
        "self_ref": f"#/tables/{fixture.fixture_id}",
        "label": "table",
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0.0,
                    "t": 100.0,
                    "r": 300.0,
                    "b": 0.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": fixture.row_count,
            "num_cols": fixture.column_count,
            "table_cells": cells,
        },
    }


def _synthetic_rows(fixture: SyntheticGrid) -> list[list[str]]:
    rows = [
        ["" for _column in range(fixture.column_count)]
        for _row in range(fixture.row_count)
    ]
    for cell in fixture.cells:
        rows[cell.row][cell.column] = cell.text
    return rows


def _run_synthetic(
    fixture_id: str,
    *,
    span_fidelity: bool = True,
) -> dict[str, Any]:
    fixture = build_synthetic_fixture(fixture_id)
    raw = _raw_synthetic_table(fixture)
    source_sha256 = hashlib.sha256(
        f"p04-us01:{fixture_id}".encode("utf-8")
    ).hexdigest()
    native_text = " ".join(cell.text for cell in fixture.cells)
    page_index, table = _docling_table_item(
        raw,
        {1: 100.0},
        {},
        [native_text],
        source_sha256,
        table_span_fidelity_enabled=span_fidelity,
    )
    table["id"] = f"synthetic-{fixture_id}"
    table["reading_order"] = 0
    pages = [
        {
            "page_index": page_index,
            "page_number": page_index,
            "page_label": str(page_index),
            "page_width": 300.0,
            "page_height": 100.0,
            "unit": "pt",
            "success": True,
            "items": [table],
            "warnings": [],
        }
    ]
    seal_table_pages(
        pages,
        source_sha256,
        [native_text],
        table_span_fidelity_enabled=span_fidelity,
    )
    finalize_table_pages(
        pages,
        source_sha256,
        table_span_fidelity_enabled=span_fidelity,
    )
    return pages[0]["items"][0]


@pytest.mark.integration
def test_default_off_full_pipeline_is_the_exact_phase03_predecessor() -> None:
    actual = _parse_real("catastrophe-recap", False)
    expected = _frozen_predecessor("catastrophe-recap")

    assert _stable_payload(actual) == _stable_payload(expected)
    assert all("table_evidence" not in table for table in _tables(actual))


def test_default_off_table_hooks_preserve_predecessor_bytes() -> None:
    fixture = build_synthetic_fixture("repeated_values_without_span")
    raw = _raw_synthetic_table(fixture)
    raw_before = _canonical_bytes(raw)
    arguments = (raw, {1: 100.0}, {}, ["Same 0 Same 1 Same 2"])

    predecessor_page, predecessor = _docling_table_item(*arguments)
    explicit_page, explicit_false = _docling_table_item(
        *arguments,
        table_span_fidelity_enabled=False,
    )
    assert predecessor_page == explicit_page == 1
    assert _canonical_bytes(predecessor) == _canonical_bytes(explicit_false)
    assert _canonical_bytes(raw) == raw_before
    assert "table_evidence" not in predecessor

    pages = [{"page_index": 1, "items": [deepcopy(predecessor)]}]
    before = _canonical_bytes(pages)
    assert (
        seal_table_pages(
            pages,
            "a" * 64,
            ["Same 0 Same 1 Same 2"],
            table_span_fidelity_enabled=False,
        )
        is None
    )
    assert _canonical_bytes(pages) == before


@pytest.mark.integration
def test_catastrophe_exact_cells_repetitions_headers_bbox_and_provenance() -> None:
    payload = _parse_real("catastrophe-recap", True)
    table = _one_table(payload, 1)
    sidecar = _valid_sidecar(table)
    expected_by_position = {
        (cell.row, cell.column): cell for cell in EXHIBIT7_EXACT.cells
    }
    actual_by_position = {
        (cell["row"], cell["column"]): cell for cell in table["cells"]
    }

    assert (table["row_count"], table["column_count"]) == (6, 5)
    assert len(table["rows"]) == 6
    assert len(table["cells"]) == len(actual_by_position) == 30
    assert set(actual_by_position) == set(expected_by_position)
    assert all(
        actual_by_position[position]["text"] == truth.text
        and (
            actual_by_position[position]["row_span"],
            actual_by_position[position]["col_span"],
        )
        == (truth.row_span, truth.col_span)
        for position, truth in expected_by_position.items()
    )
    repeated = [cell for cell in table["cells"] if cell["text"] == "United States"]
    assert len(repeated) == 5
    assert len({cell["id"] for cell in repeated}) == 5
    assert all((cell["row_span"], cell["col_span"]) == (1, 1) for cell in repeated)
    assert all(cell["column_header"] is (cell["row"] == 0) for cell in table["cells"])

    source_by_id = {item["id"]: item for item in sidecar["source_objects"]}
    evidence_by_id = {item["id"]: item for item in sidecar["evidence"]}
    source_ids = set(source_by_id)
    evidence_ids = set(evidence_by_id)
    assert source_ids and evidence_ids
    for cell in table["cells"]:
        position = (cell["row"], cell["column"])
        content_truth = EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION[position]
        structural_truth = expected_by_position[position]
        box = cell["bbox"]
        assert set(box) == {"x", "y", "width", "height", "unit"}
        assert box["unit"] == "pt"
        assert all(
            math.isfinite(float(box[key]))
            for key in ("x", "y", "width", "height")
        )
        assert box["width"] > 0 and box["height"] > 0
        assert metrics._bbox_matches(box, content_truth.bbox)
        assert metrics._bbox_contained_by_grid(box, structural_truth.bbox)
        assert set(cell["source_object_ids"]) <= source_ids
        assert set(cell["evidence_ids"]) <= evidence_ids
        native_text_evidence = [
            evidence_by_id[evidence_id]
            for evidence_id in cell["evidence_ids"]
            if evidence_by_id[evidence_id]["method"] == "native_text"
            and evidence_by_id[evidence_id]["dimension"] == "text"
        ]
        assert len(native_text_evidence) == 1
        text_evidence = native_text_evidence[0]
        native_sources = [
            source_by_id[source_id]
            for source_id in text_evidence["source_object_ids"]
            if source_id in cell["source_object_ids"]
            and source_by_id[source_id]["engine"] == "docling"
            and source_by_id[source_id]["object_type"] == "table_cell"
        ]
        assert len(native_sources) == 1
        source_object = native_sources[0]
        assert (
            source_object["engine"],
            source_object["object_type"],
            source_object["page_index"],
            source_object["raw_ref"],
        ) == ("docling", "table_cell", 1, "#/tables/0")
        assert text_evidence["source_object_ids"] == [source_object["id"]]
        assert text_evidence["bbox"] == box
        assert text_evidence["content_sha256"] == source_object["content_sha256"]
    expected_html = metrics._expected_html(EXHIBIT7_EXACT)
    assert table["html"] == table["md"] == expected_html
    assert table["html"].count('<th scope="col">') == 5
    assert '<th scope="row">' not in table["html"]
    scored = metrics._score_exact_table(payload, EXHIBIT7_EXACT)
    assert scored["exact_cell_numerator"] == scored["exact_cell_denominator"] == 30
    assert scored["source_content_bbox_numerator"] == 30
    assert scored["structural_grid_containment_numerator"] == 30
    assert scored["representation_numerator"] == scored[
        "representation_denominator"
    ] == 6
    assert scored["bbox_role_oracle"]["semantic_identity"]["sha256"] == (
        source_content_bbox_oracle_sha256()
    )
    assert scored["passed"] is True
    assert all(slot["kind"] == "anchor" for slot in sidecar["slots"])

    # P04 replaces only the table base.  The already validated P03 caption
    # remains its public owner exactly once, while every other contribution is
    # the current raw-free P04 table/cell projection (never stale P03 cells).
    target = _canonical_block_for_public_item(
        payload,
        page_index=1,
        public_item_id=table["id"],
    )
    raw_free_target = _canonical_block_for_public_item(
        payload,
        page_index=1,
        public_item_id=table["id"],
        raw_free=True,
    )
    caption_ids = table.get("caption_ids")
    assert isinstance(caption_ids, list) and len(caption_ids) == 1
    caption_id = caption_ids[0]
    assert target["contributing_element_ids"] == [
        raw_free_target["contributing_element_ids"][0],
        caption_id,
        *raw_free_target["contributing_element_ids"][1:],
    ]
    assert target["contributing_element_ids"].count(caption_id) == 1
    assert target["markdown"].endswith(raw_free_target["markdown"])
    assert target["text"].endswith(raw_free_target["text"])
    caption_block = _canonical_block_for_public_item(
        payload,
        page_index=1,
        public_item_id=caption_id,
    )
    assert caption_block["omission_reason"] == "consumed_by_relationship"
    assert caption_block["suppressed_by_element_id"] == (
        target["primary_element_id"]
    )


def test_synthetic_repetitions_multiline_headers_and_explicit_blanks() -> None:
    repeated_fixture = build_synthetic_fixture("repeated_values_without_span")
    repeated = _run_synthetic(repeated_fixture.fixture_id)
    repeated_sidecar = _valid_sidecar(repeated)
    same_cells = [cell for cell in repeated["cells"] if cell["text"] == "Same"]
    assert repeated["rows"] == _synthetic_rows(repeated_fixture)
    assert len(same_cells) == len({cell["id"] for cell in same_cells}) == 3
    assert all(cell["span_decision_id"] is None for cell in same_cells)
    assert all(slot["kind"] == "anchor" for slot in repeated_sidecar["slots"])

    multiline_fixture = build_synthetic_fixture("rotated_multiline_headers")
    multiline = _run_synthetic(multiline_fixture.fixture_id)
    _valid_sidecar(multiline)
    assert multiline["rows"] == _synthetic_rows(multiline_fixture)
    assert [cell["text"] for cell in multiline["cells"] if cell["row"] == 0] == [
        "Station\n(stop)",
        "Train 101\nWeekday",
        "Train 203\nExpress",
    ]
    assert all(
        cell["column_header"] is True
        for cell in multiline["cells"]
        if cell["row"] == 0
    )
    assert multiline["html"].count("<br>") == 3

    blank_fixture = build_synthetic_fixture("blank_stub_section_cells")
    blank = _run_synthetic(blank_fixture.fixture_id)
    blank_sidecar = _valid_sidecar(blank)
    blank_cells = [
        cell for cell in blank["cells"] if cell["row"] == 1 and cell["text"] == ""
    ]
    assert blank["rows"] == _synthetic_rows(blank_fixture)
    assert len(blank_cells) == 2
    blank_ids = {cell["id"] for cell in blank_cells}
    assert {
        slot["cell_id"]
        for slot in blank_sidecar["slots"]
        if slot["kind"] == "explicit_blank"
    } == blank_ids


@pytest.mark.parametrize(
    ("fixture_id", "expected_span", "covered_positions"),
    (
        ("legitimate_colspan", (1, 3), {(0, 1), (0, 2)}),
        ("legitimate_rowspan", (2, 1), {(1, 0)}),
    ),
)
def test_synthetic_supported_spans_have_independent_evidence_and_covered_slots(
    fixture_id: str,
    expected_span: tuple[int, int],
    covered_positions: set[tuple[int, int]],
) -> None:
    fixture = build_synthetic_fixture(fixture_id)
    table = _run_synthetic(fixture_id)
    sidecar = _valid_sidecar(table)
    spanned = next(
        cell
        for cell in table["cells"]
        if (cell["row_span"], cell["col_span"]) == expected_span
    )
    decision = next(
        item
        for item in sidecar["span_decisions"]
        if item["id"] == spanned["span_decision_id"]
    )
    evidence = {
        item["id"]: item
        for item in sidecar["evidence"]
        if item["id"] in decision["evidence_ids"]
    }

    assert table["rows"] == _synthetic_rows(fixture)
    assert decision["outcome"] == "supported"
    assert (decision["emitted_row_span"], decision["emitted_col_span"]) == (
        expected_span
    )
    assert {item["dimension"] for item in evidence.values()} >= {
        "geometry",
        "structure",
    }
    assert len(
        {
            source_id
            for item in evidence.values()
            for source_id in item["source_object_ids"]
        }
    ) >= 2
    covered = {
        (slot["row"], slot["column"])
        for slot in sidecar["slots"]
        if slot["kind"] == "covered"
    }
    assert covered == covered_positions


def test_synthetic_bottom_boundary_and_hostile_html_remain_data() -> None:
    boundary_fixture = build_synthetic_fixture("bottom_boundary_completeness")
    boundary = _run_synthetic(boundary_fixture.fixture_id)
    _valid_sidecar(boundary)
    assert boundary["rows"] == _synthetic_rows(boundary_fixture)
    assert boundary["rows"][-1] == [
        "FERS",
        "Federal Employees Retirement System",
    ]

    hostile_fixture = build_synthetic_fixture("html_escaping")
    hostile = _run_synthetic(hostile_fixture.fixture_id)
    _valid_sidecar(hostile)
    assert hostile["rows"] == _synthetic_rows(hostile_fixture)
    assert "<script>" not in hostile["html"]
    assert "<img " not in hostile["html"]
    assert "&lt;script&gt;" in hostile["html"]
    assert "&lt;img src=x onerror=alert(1)&gt;" in hostile["html"]
    assert "AT&amp;T" in hostile["html"]


@pytest.mark.parametrize(
    "fixture_id",
    ("ambiguous_border_refusal", "partial_grid_refusal"),
)
def test_synthetic_incomplete_grid_is_diagnostic_and_never_authoritative(
    fixture_id: str,
) -> None:
    fixture = build_synthetic_fixture(fixture_id)
    table = _run_synthetic(fixture.fixture_id)
    predecessor = _run_synthetic(fixture.fixture_id, span_fidelity=False)
    sidecar = table.get("table_evidence")

    assert isinstance(sidecar, dict)
    assert sidecar["status"] in {"unresolved", "structural_failure"}
    assert sidecar["status"] != "valid"
    assert "table_ambiguous_border_evidence" in sidecar["concerns"]
    assert _table_projection(table) == _table_projection(predecessor)
    assert predecessor["rows"] == _synthetic_rows(fixture)


@pytest.mark.integration
def test_finance_reviewed_spans_and_wrapped_row_are_preserved() -> None:
    payload = _parse_real("finance-10k", True)
    predecessor = _frozen_predecessor("finance-10k")
    tables = {page: _one_table(payload, page) for page in (1, 2, 3)}

    for page in (1, 2, 3):
        table = tables[page]
        predecessor_table = _one_table(predecessor, page)
        sidecar = table.get("table_evidence")
        assert isinstance(sidecar, dict)
        assert sidecar["status"] in {"unresolved", "structural_failure"}
        assert sidecar["status"] != "valid"
        assert "table_source_cell_grid_unresolved" in sidecar["concerns"]
        assert sidecar["source_objects"] and sidecar["evidence"]
        assert _table_projection(table) == _table_projection(predecessor_table)

    for page in (1, 3):
        table = tables[page]
        anchor = next(cell for cell in table["cells"] if cell["text"] == "Years ended")
        assert (anchor["row_span"], anchor["col_span"]) == (1, 3)

    balance = tables[2]
    wrapped = [
        row
        for row in balance["rows"]
        if "Common stock and additional paid-in capital" in row[0]
    ]
    assert len(wrapped) == 1
    assert len(wrapped[0]) == 3


@pytest.mark.integration
def test_clinical_headers_sections_and_group_spans_are_source_supported() -> None:
    payload = _parse_real("clinical-study", True)
    predecessor = _frozen_predecessor("clinical-study")
    table1 = _one_table(payload, 2)
    table2 = _one_table(payload, 4)
    for page, table in ((2, table1), (4, table2)):
        sidecar = table.get("table_evidence")
        assert isinstance(sidecar, dict)
        assert sidecar["status"] in {"unresolved", "structural_failure"}
        assert sidecar["status"] != "valid"
        assert "table_source_cell_grid_unresolved" in sidecar["concerns"]
        assert sidecar["source_objects"] and sidecar["evidence"]
        assert _table_projection(table) == _table_projection(
            _one_table(predecessor, page)
        )

    assert table1["column_count"] == 6
    first_row_headers = [
        cell
        for cell in table1["cells"]
        if cell["row"] == 0 and cell["text"]
    ]
    assert len(first_row_headers) == 5
    assert all(cell["column_header"] is True for cell in first_row_headers)
    for label in ("M(SD)", "Marital status", "Occupation"):
        section = next(cell for cell in table1["cells"] if cell["text"] == label)
        assert (section["row_span"], section["col_span"]) == (1, 1)

    assert table2["column_count"] == 9
    group_spans = sorted(
        cell["col_span"]
        for cell in table2["cells"]
        if cell["row"] == 0 and cell["col_span"] > 1
    )
    assert group_spans == [3, 4]


@pytest.mark.integration
def test_postal_glossary_recovers_source_proven_fers_boundary() -> None:
    payload = _parse_real("postal-10k", True)
    table = _one_table(payload, 1)
    sidecar = _valid_sidecar(table)
    predecessor = _one_table(_frozen_predecessor("postal-10k"), 1)

    assert table["rows"][:39] == predecessor["rows"]
    assert table["rows"][-1] == ["FERS", "Federal Employees Retirement System"]
    assert (table["row_count"], table["column_count"]) == (40, 2)
    assert len(table["cells"]) == 80
    assert sidecar["grid"]["row_count"] == 40
    assert sidecar["grid"]["column_count"] == 2
    headers = [cell for cell in table["cells"] if cell["row"] == 0]
    assert [cell["text"] for cell in headers] == ["Term or Acronym", "Definition"]
    assert all(cell["column_header"] is True for cell in headers)
    fers = [cell for cell in table["cells"] if cell["row"] == 39]
    assert [cell["text"] for cell in fers] == [
        "FERS",
        "Federal Employees Retirement System",
    ]
    assert all(cell["bbox"] is not None for cell in fers)
    assert all(cell["source_object_ids"] and cell["evidence_ids"] for cell in fers)


@pytest.mark.integration
def test_timetable_fails_closed_without_shifting_or_silently_merging_rows() -> None:
    payload = _parse_real("ny-timetable", True)
    predecessor = _frozen_predecessor("ny-timetable")

    assert len(_tables(payload)) == len(_tables(predecessor)) == 3
    for page_index in (1, 2, 3):
        table = _one_table(payload, page_index)
        predecessor_table = _one_table(predecessor, page_index)
        sidecar = table.get("table_evidence")
        assert isinstance(sidecar, dict)
        assert sidecar["status"] in {"unresolved", "structural_failure"}
        assert sidecar["status"] != "valid"
        assert sidecar["source_objects"] and sidecar["evidence"]
        assert "table_source_cell_grid_unresolved" in sidecar["concerns"]
        assert _table_projection(table) == _table_projection(predecessor_table)

    page3 = _one_table(payload, 3)
    assert page3["rows"][28] == [
        "",
        "2:55 3:01",
        "3:05",
        "3:18",
        "3:24",
        "3:30",
        "3:32 3:32 3:38",
        "3:43",
        "3:48",
        "3:51",
        "3:55",
        "3:57",
    ]
    assert all(len(row) == 12 for row in page3["rows"])


@pytest.mark.integration
def test_acord_form_owned_grid_retains_evidence_but_not_canonical_topology() -> None:
    payload = _parse_real("insurance-acord", True)
    predecessor = _frozen_predecessor("insurance-acord")
    assert len(_tables(payload, page_index=1)) == len(
        _tables(predecessor, page_index=1)
    ) == 2
    table = max(_tables(payload, page_index=1), key=lambda item: item["column_count"])
    predecessor_table = max(
        _tables(predecessor, page_index=1),
        key=lambda item: item["column_count"],
    )
    sidecar = table.get("table_evidence")

    assert isinstance(sidecar, dict)
    assert sidecar["status"] in {"unresolved", "structural_failure"}
    assert sidecar["status"] != "valid"
    assert "table_source_form_grid_topology_unresolved" in sidecar["concerns"]
    assert sidecar["source_objects"] and sidecar["evidence"]
    assert _table_projection(table) == _table_projection(predecessor_table)
    assert "INSR LTR" in table["rows"][0][0]
    assert "TYPE OF INSURANCE" in table["rows"][0][1]

    form_groups = {
        item["form_group"]["group_key"]: (
            item["id"],
            item["form_group"]["anchor_public_item_id"],
        )
        for page in payload["pages"]
        for item in page["items"]
        if item.get("layout_forms_projected") is True
    }
    assert form_groups == {
        "date": ("p1-i2", "p1-i2"),
        "parties-and-insurers": ("p1-i7", "p1-i7"),
        "coverages": ("p1-i13", "p1-i13"),
        "description-of-operations": ("p1-i14", "p1-i14"),
        "certificate-holder": ("p1-i15", "p1-i15"),
        "cancellation": ("p1-i16", "p1-i16"),
    }
    assert len({anchor for _item, anchor in form_groups.values()}) == 6
    assert any(
        item.get("id") == "p1-i17"
        and str(item.get("value") or "").startswith(
            "SHOULD ANY OF THE ABOVE DESCRIBED POLICIES"
        )
        for page in payload["pages"]
        for item in page["items"]
    )
    assert any(
        item.get("id") == "p1-i18"
        and item.get("value") == "AUTHORIZED REPRESENTATIVE"
        for page in payload["pages"]
        for item in page["items"]
    )


@pytest.mark.integration
def test_real_output_round_trips_api_schema_and_serializer_without_loss() -> None:
    payload = _parse_real("catastrophe-recap", True)
    table = _one_table(payload, 1)
    sidecar = _valid_sidecar(table)
    encoded = _canonical_bytes(payload)
    validated = ParseResult.model_validate_json(encoded)
    round_tripped = validated.model_dump(mode="json", exclude_none=True)
    public_table = _one_table(round_tripped, 1)
    content_item = ContentItem.model_validate(table)
    content_item_payload = content_item.model_dump(mode="json", exclude_none=True)

    assert public_table["table_evidence"] == sidecar
    assert public_table["cells"] == table["cells"]
    assert content_item_payload["table_evidence"] == sidecar
    assert ContentItem.model_json_schema()["additionalProperties"] is True
    markdown = to_markdown(validated)
    assert table["html"] in markdown
    assert table["html"].count("United States") == 5
    assert markdown.count("United States") == 7
    assert "table_evidence" not in markdown


@pytest.mark.integration
def test_clinical_output_context_free_json_round_trip_is_exact_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _parse_real("clinical-study", True)
    encoded = _canonical_bytes(payload)
    expected_markdown = to_markdown(payload)
    expected_sidecars = [
        deepcopy(item["table_evidence"])
        for page in payload["pages"]
        for item in page["items"]
        if "table_evidence" in item
    ]
    assert "canonical_source_custody" in payload, payload.get("warnings")
    expected_custody = deepcopy(payload["canonical_source_custody"])

    original_ir_builder = build_document_ir
    original_presentation_builder = _build_canonical_presentation_from_validated
    original_validator = ParseResult._validate_table_evidence_custody_impl
    ir_calls = 0
    presentation_calls = 0
    active_ir_calls = 0
    maximum_ir_depth = 0
    validator_calls: list[tuple[int, Any]] = []

    def ir_spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal ir_calls, active_ir_calls, maximum_ir_depth
        ir_calls += 1
        active_ir_calls += 1
        maximum_ir_depth = max(maximum_ir_depth, active_ir_calls)
        try:
            return original_ir_builder(*args, **kwargs)
        finally:
            active_ir_calls -= 1

    def presentation_spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal presentation_calls
        presentation_calls += 1
        return original_presentation_builder(*args, **kwargs)

    def validator_spy(self: ParseResult, context: Any) -> Any:
        validator_calls.append((id(self), context))
        return original_validator(self, context)

    monkeypatch.setattr("app.services.ir.build_document_ir", ir_spy)
    monkeypatch.setattr(
        "app.services.presentation._build_canonical_presentation_from_validated",
        presentation_spy,
    )
    monkeypatch.setattr(
        ParseResult,
        "_validate_table_evidence_custody_impl",
        validator_spy,
    )

    validated = ParseResult.model_validate_json(encoded)
    round_tripped = validated.model_dump(mode="json", exclude_none=True)

    assert _canonical_bytes(round_tripped) == encoded
    assert [
        item["table_evidence"]
        for page in round_tripped["pages"]
        for item in page["items"]
        if "table_evidence" in item
    ] == expected_sidecars
    assert round_tripped["canonical_source_custody"] == expected_custody
    assert to_markdown(validated) == expected_markdown
    assert ir_calls == 2
    assert presentation_calls == 2
    assert maximum_ir_depth == 1
    assert len(validator_calls) == 2
    assert validator_calls[0][0] == validator_calls[1][0] == id(validated)
    assert validator_calls[0][1] is None
    assert validator_calls[1][1] is not None
    assert not hasattr(validator_calls[1][1], "model_dump")

    ir_calls = 0
    presentation_calls = 0
    active_ir_calls = 0
    maximum_ir_depth = 0
    validator_calls.clear()
    with pytest.raises(
        ValueError,
        match="marked table canonical exact graph differs",
    ):
        ParseResult.model_validate(round_tripped, context=object())
    assert ir_calls == 1
    assert presentation_calls == 1
    assert maximum_ir_depth == 1
    assert len(validator_calls) == 1
    assert validator_calls[0][1] is not None


@pytest.mark.integration
def test_clinical_canonical_endpoint_substitution_requires_reseal_and_reseal_is_unkeyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = deepcopy(_parse_real("clinical-study", True))
    canonical = payload["canonical_presentation"]
    document_id = stable_id("doc", payload["document"]["sha256"])
    original_endpoint_id = stable_id(
        "el",
        document_id,
        "raw_ref",
        "#/texts/46",
    )
    replacement_endpoint_id = stable_id(
        "el",
        document_id,
        "raw_ref",
        "#/texts/48",
    )
    matches = [
        (block, exclusion)
        for page in canonical["pages"]
        for block in page["blocks"]
        for exclusion in block["excluded_contributions"]
        if exclusion["element_id"] == original_endpoint_id
    ]
    assert len(matches) == 1
    block, exclusion = matches[0]
    original_relationship_id = exclusion["relationship_ids"][0]
    relationship_shapes = [
        (original_endpoint_id, block["primary_element_id"], "children"),
        (block["primary_element_id"], original_endpoint_id, "children"),
        (original_endpoint_id, block["primary_element_id"], "parent"),
        (block["primary_element_id"], original_endpoint_id, "parent"),
    ]
    matching_shapes = [
        shape
        for shape in relationship_shapes
        if stable_id("rel", "contains", *shape)
        == original_relationship_id
    ]
    assert len(matching_shapes) == 1
    source_id, target_id, relationship_field = matching_shapes[0]
    replacement_relationship_id = stable_id(
        "rel",
        "contains",
        (
            replacement_endpoint_id
            if source_id == original_endpoint_id
            else source_id
        ),
        (
            replacement_endpoint_id
            if target_id == original_endpoint_id
            else target_id
        ),
        relationship_field,
    )
    assert exclusion["relationship_ids"] == [original_relationship_id]
    block["relationship_ids"].remove(original_relationship_id)
    block["relationship_ids"].append(replacement_relationship_id)
    block["relationship_ids"].sort()
    exclusion["element_id"] = replacement_endpoint_id
    exclusion["relationship_ids"] = [replacement_relationship_id]
    block["excluded_contributions"].sort(
        key=lambda value: (value["element_id"], value["reason"])
    )
    _refresh_test_canonical_views(payload)

    ir_calls = 0

    def forbidden_ir_builder(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal ir_calls
        ir_calls += 1
        raise AssertionError(
            "context-free reconstruction ran before canonical integrity"
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            "app.services.ir.build_document_ir",
            forbidden_ir_builder,
        )
        with pytest.raises(
            ValueError,
            match="canonical presentation digest differs",
        ):
            ParseResult.model_validate_json(_canonical_bytes(payload))
    assert ir_calls == 0

    # This is intentionally only an unkeyed structural-integrity seal.  A
    # party able to coherently edit both payload and digest is not granted
    # source authority; upstream source/custody gates remain necessary.
    payload["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = hashlib.sha256(_canonical_bytes(canonical)).hexdigest()
    validated = ParseResult.model_validate_json(_canonical_bytes(payload))
    round_tripped = validated.model_dump(mode="json", exclude_none=True)

    assert round_tripped["canonical_source_custody"]["authority"] == (
        "diagnostic_only"
    )
    assert round_tripped["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] == hashlib.sha256(
        _canonical_bytes(round_tripped["canonical_presentation"])
    ).hexdigest()
    assert replacement_endpoint_id in json.dumps(
        round_tripped["canonical_presentation"],
        sort_keys=True,
    )
