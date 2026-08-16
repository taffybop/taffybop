"""Public API/schema contracts for the P04-US01 table overlay."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models import (
    CanonicalSourceCustody,
    ContentItem,
    PageResult,
    ParseResult,
    TableCell,
    TableEvidence,
    TableSpanDecision,
    _canonical_presentation_sha256,
)
from app.services.serializer import to_markdown


def _hash(digit: str) -> str:
    return digit * 64


def _bind_empty_source_custody(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.opaque_group_custody import (
        POLICY_ID,
        SCHEMA_VERSION,
        has_literal_table_marker,
        records_sha256,
    )

    if has_literal_table_marker(payload):
        payload["canonical_source_custody"] = {
            "policy_id": POLICY_ID,
            "schema_version": SCHEMA_VERSION,
            "authority": "diagnostic_only",
            "source_sha256": payload["document"]["sha256"],
            "canonical_presentation_sha256": (
                _canonical_presentation_sha256(
                    payload["canonical_presentation"]
                )
            ),
            "record_count": 0,
            "records_sha256": records_sha256([]),
            "records": [],
        }
    return payload


def _reseal_bound_canonical(payload: dict[str, Any]) -> None:
    payload["canonical_source_custody"][
        "canonical_presentation_sha256"
    ] = _canonical_presentation_sha256(payload["canonical_presentation"])


def _valid_table() -> dict[str, Any]:
    cell_id = _hash("3")
    decision_id = _hash("9")
    source_id = _hash("1")
    evidence_id = _hash("2")
    bbox = {"x": 0, "y": 0, "width": 20, "height": 10, "unit": "pt"}
    cell = {
        "id": cell_id,
        "row": 0,
        "column": 0,
        "row_span": 1,
        "col_span": 2,
        "text": "A\ncontinued",
        "column_header": True,
        "row_header": False,
        "row_section": False,
        "bbox": bbox,
        "source": "native",
        "page_index": 1,
        "evidence_ids": [evidence_id],
        "source_object_ids": [source_id],
        "span_decision_id": decision_id,
        "confidence_dimensions": {
            "text": 1,
            "geometry": 1.0,
            "structure": 1,
            "header": 1,
        },
    }
    evidence = {
        "policy_id": "p04-table-evidence-v1",
        "version": "1.1",
        "scope": ["P04-US01"],
        "status": "valid",
        "table_id": _hash("6"),
        "candidate_id": _hash("7"),
        "page_index": 1,
        "grid": {
            "row_count": 1,
            "column_count": 2,
            "cell_ids": [cell_id],
        },
        "slots": [
            {
                "id": _hash("4"),
                "row": 0,
                "column": 0,
                "kind": "anchor",
                "cell_id": cell_id,
                "covered_by_cell_id": None,
            },
            {
                "id": _hash("5"),
                "row": 0,
                "column": 1,
                "kind": "covered",
                "cell_id": None,
                "covered_by_cell_id": cell_id,
            },
        ],
        "source_objects": [
            {
                "id": source_id,
                "engine": "docling",
                "object_type": "table_cell",
                "page_index": 1,
                "raw_ref": "#/tables/0/data/table_cells/0",
                "content_sha256": _hash("8"),
            }
        ],
        "evidence": [
            {
                "id": evidence_id,
                "method": "native_text",
                "dimension": "text",
                "page_index": 1,
                "bbox": bbox,
                "source_object_ids": [source_id],
                "confidence": 1,
                "content_sha256": _hash("8"),
            }
        ],
        "span_decisions": [
            {
                "id": decision_id,
                "cell_id": cell_id,
                "claimed_row_span": 1,
                "claimed_col_span": 2,
                "emitted_row_span": 1,
                "emitted_col_span": 2,
                "outcome": "supported",
                "evidence_ids": [evidence_id],
                "concern_codes": [],
            }
        ],
        "representation_custody": {
            "serializer_policy_id": "p04-table-grid-serializer-v1",
            "grid_shape": [1, 2],
            "cells_sha256": _hash("a"),
            "rows_sha256": _hash("b"),
            "html_sha256": _hash("c"),
            "markdown_sha256": _hash("d"),
            "csv_sha256": _hash("e"),
        },
        "reconciliation": None,
        "gate": None,
        "continuation": None,
        "concerns": [],
    }
    html = '<table><tr><th colspan="2">A<br>continued</th></tr></table>'
    return {
        "id": "table-1",
        "type": "table",
        "reading_order": 0,
        "value": [["A\ncontinued", ""]],
        "rows": [["A\ncontinued", ""]],
        "cells": [cell],
        "html": html,
        "md": html,
        "csv": "A\ncontinued,",
        "row_count": 1,
        "column_count": 2,
        "table_evidence": evidence,
    }


def _production_table() -> dict[str, Any]:
    from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
        _seal,
        _spanned_table,
    )

    table = _seal(_spanned_table())
    table.pop("_p04_predecessor_snapshot", None)
    return table


def _production_diagnostic() -> dict[str, Any]:
    from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
        _raw_cell,
        _raw_table,
        _seal,
    )

    return _seal(
        _raw_table(
            1,
            2,
            [
                _raw_cell(0, 0, "Span", col_span=2),
                _raw_cell(0, 1, "Collision"),
            ],
        )
    )


def _pdfplumber_source() -> dict[str, Any]:
    return {
        "id": _hash("0"),
        "engine": "pdfplumber",
        "object_type": "table_word_set",
        "page_index": 1,
        "raw_ref": None,
        "role": "header",
        "target_row": 0,
        "target_column": 0,
        "words": [
            {
                "id": _hash("b"),
                "text": "Header",
                "bbox": {
                    "x": 1,
                    "y": 1,
                    "width": 8,
                    "height": 4,
                    "unit": "pt",
                },
                "font_name": "ABCDEE+Helvetica-Bold",
                "bold": True,
            },
            {
                "id": _hash("c"),
                "text": "two",
                "bbox": {
                    "x": 10,
                    "y": 1,
                    "width": 6,
                    "height": 4,
                    "unit": "pt",
                },
                "font_name": "ABCDEE+Helvetica-Bold",
                "bold": True,
            },
        ],
        "content_sha256": _hash("d"),
    }


def _large_pdfplumber_sidecar(word_bytes: int) -> dict[str, Any]:
    sidecar = _valid_table()["table_evidence"]
    sidecar["status"] = "unresolved"
    sidecar["grid"] = {
        "row_count": 2,
        "column_count": 16,
        "cell_ids": [],
    }
    sidecar["slots"] = []
    sidecar["span_decisions"] = []
    sidecar["concerns"] = ["table_source_span_evidence_unresolved"]
    text = "x" * word_bytes
    sources: list[dict[str, Any]] = []
    for source_index in range(48):
        role_index, column = divmod(source_index, 16)
        role = ("header", "body_control", "bottom_row")[role_index]
        row = 0 if role == "header" else 1
        words = []
        for word_index in range(64):
            words.append(
                {
                    "id": f"{word_index + 1:064x}",
                    "text": text,
                    "bbox": {
                        "x": word_index * 2,
                        "y": row * 10,
                        "width": 1,
                        "height": 4,
                        "unit": "pt",
                    },
                    "font_name": "Regular",
                    "bold": False,
                }
            )
        sources.append(
            {
                "id": f"{source_index + 1:064x}",
                "engine": "pdfplumber",
                "object_type": "table_word_set",
                "page_index": 1,
                "raw_ref": None,
                "role": role,
                "target_row": row,
                "target_column": column,
                "words": words,
                "content_sha256": _hash("f"),
            }
        )
    sidecar["source_objects"] = sources
    sidecar["evidence"] = [
        {
            "id": _hash("a"),
            "method": "derived_comparison",
            "dimension": "header",
            "page_index": 1,
            "bbox": None,
            "source_object_ids": [source["id"] for source in sources],
            "confidence": 1,
            "content_sha256": _hash("e"),
        }
    ]
    return sidecar


def _parse_payload(
    item: dict[str, Any],
    *,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "table.pdf",
            "mime_type": "application/pdf",
            "sha256": source_sha256 or _hash("f"),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 300,
                "page_height": 120,
                "unit": "pt",
                "success": True,
                "items": [item],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "docling",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _with_bound_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.ir import round_trip_document
    from app.services.presentation import build_canonical_presentation

    bound = deepcopy(payload)
    _projected, ir = round_trip_document(bound)
    bound["canonical_presentation"] = build_canonical_presentation(ir).model_dump(
        mode="json",
        exclude_none=True,
    )
    return _bind_empty_source_custody(bound)


def _bound_payload(
    item: dict[str, Any],
    *,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    return _with_bound_canonical(
        _parse_payload(item, source_sha256=source_sha256)
    )


def _marked_payload_with_text() -> dict[str, Any]:
    payload = _parse_payload(_production_table(), source_sha256=_hash("a"))
    table = payload["pages"][0]["items"][0]
    table["reading_order"] = 1
    payload["pages"][0]["items"].insert(
        0,
        {
            "id": "p1-text",
            "type": "text",
            "reading_order": 0,
            "value": "Authoritative prose",
            "md": "Authoritative prose",
            "source": "native",
        },
    )
    return _with_bound_canonical(payload)


def _rebuild_canonical_views(canonical: dict[str, Any]) -> None:
    def render(blocks: list[dict[str, Any]]) -> dict[str, Any]:
        included = [
            block for block in blocks if block.get("omission_reason") is None
        ]

        def values(field: str) -> str:
            members = [
                str(block[field]).strip()
                for block in included
                if str(block[field]).strip()
            ]
            return "\n\n".join(members).rstrip() + "\n" if members else ""

        return {
            "block_ids": [str(block["id"]) for block in included],
            "markdown": values("markdown"),
            "text": values("text"),
        }

    all_blocks: list[dict[str, Any]] = []
    for page in canonical["pages"]:
        blocks = page["blocks"]
        all_blocks.extend(blocks)
        page["full"] = render(blocks)
        for scope in ("body", "header", "footer"):
            page[scope] = render(
                [block for block in blocks if block["scope"] == scope]
            )
    canonical["full"] = render(all_blocks)
    for scope in ("body", "header", "footer"):
        canonical[scope] = render(
            [block for block in all_blocks if block["scope"] == scope]
        )


def _stale_canonical_payload(
    table: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    payload = _with_bound_canonical(
        _parse_payload(table, source_sha256=_hash("a"))
    )
    block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    block["markdown"] = f"<table><tr><td>STALE {status}</td></tr></table>"
    block["text"] = f"STALE {status}"
    _rebuild_canonical_views(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)
    return payload


def _visual_marked_payload() -> dict[str, Any]:
    from app.services.presentation import build_canonical_presentation
    from tests.stories.phase_03.test_p03_us02_visual_children import (
        _box,
        _document,
        _project,
        _raw_graph,
        _raw_visual,
        _text_node,
        _visual_item,
    )

    visual = _visual_item(
        item_type="image",
        value="ACME",
        ocr_text="ACME",
        include_ocr_in_primary=False,
    )
    table = _production_table()
    table["reading_order"] = 1
    document = _document(visual, table, page_height=200.0)
    document["document"]["sha256"] = _hash("a")
    document["pages"][0]["page_width"] = 400.0
    raw_graph = _raw_graph(
        texts=[
            _text_node(
                "#/texts/0",
                "ACME",
                _box(30, 45, 50, 50),
                label="text",
            )
        ],
        visuals=[
            _raw_visual(
                label="picture",
                box=_box(10, 30, 80, 70),
                children=("#/texts/0",),
            )
        ],
    )
    projected, ir = _project(document, raw_graph, native_text="")
    projected["canonical_presentation"] = build_canonical_presentation(
        ir
    ).model_dump(mode="json", exclude_none=True)
    return _bind_empty_source_custody(projected)


def _form_replace_marked_payload() -> dict[str, Any]:
    from pathlib import Path

    from app.services.form_semantics import render_form_group_semantics
    from app.services.ir import build_document_ir
    from app.services.pipeline import _docling_table_item
    from app.services.table_semantics import finalize_table_pages, seal_table_pages
    from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
        _spanned_table,
    )

    frozen_path = Path(
        "tracker/phase-03-layout/evidence/"
        "P03-US08-post-US07-predecessor-20260801/"
        "component-datasheet/our-output.json"
    )
    frozen = json.loads(frozen_path.read_text())
    source_page = frozen["pages"][1]
    source_anchor = next(
        item for item in source_page["items"] if item["id"] == "p2-i8"
    )
    contributor_public_ids = source_anchor["form_group"][
        "contributor_public_item_ids"
    ]
    source_items = {item["id"]: item for item in source_page["items"]}
    form_items = [
        deepcopy(source_items[public_id])
        for public_id in contributor_public_ids
    ]
    for reading_order, item in enumerate(form_items):
        item["reading_order"] = reading_order

    payload = {
        "schema_version": "1.0",
        "document": deepcopy(frozen["document"]),
        "pages": [deepcopy(frozen["pages"][0]), deepcopy(source_page)],
        "processing": deepcopy(frozen["processing"]),
        "warnings": [],
    }
    payload["document"]["page_count"] = 2
    payload["pages"][0]["items"] = []
    payload["pages"][0]["warnings"] = []
    payload["pages"][1]["items"] = form_items
    payload["pages"][1]["warnings"] = []

    source_sha256 = payload["document"]["sha256"]
    raw_table = deepcopy(_spanned_table())
    raw_table["prov"][0]["page_no"] = 2
    native_text = " ".join(
        str(cell.get("text") or "")
        for cell in raw_table["data"]["table_cells"]
    )
    _page_index, table = _docling_table_item(
        raw_table,
        {2: payload["pages"][1]["page_height"]},
        {},
        ["", native_text],
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    table["id"] = "p2-p04-review-table"
    table["reading_order"] = len(form_items)
    snapshot = table.get("_p04_predecessor_snapshot")
    if isinstance(snapshot, dict):
        snapshot["id"] = table["id"]
        snapshot["reading_order"] = table["reading_order"]
    table_page = {
        key: deepcopy(payload["pages"][1][key])
        for key in (
            "page_index",
            "page_number",
            "page_label",
            "page_width",
            "page_height",
            "unit",
            "success",
            "warnings",
        )
    }
    table_page["items"] = [table]
    seal_table_pages(
        [table_page],
        source_sha256,
        ["", native_text],
        table_span_fidelity_enabled=True,
    )
    finalize_table_pages(
        [table_page],
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    payload["pages"][1]["items"].append(table_page["items"][0])
    payload = _with_bound_canonical(payload)

    public_ir = build_document_ir(
        {
            "document": {"sha256": source_sha256},
            "pages": [
                {
                    key: deepcopy(page[key])
                    for key in (
                        "page_index",
                        "page_number",
                        "page_label",
                        "page_width",
                        "page_height",
                        "unit",
                        "success",
                        "items",
                        "warnings",
                    )
                }
                for page in payload["pages"]
            ],
        }
    )
    elements_by_id = {element.id: element for element in public_ir.elements}
    anchor_id = source_anchor["form_group"]["anchor_element_id"]
    rendering = render_form_group_semantics(elements_by_id[anchor_id])
    assert rendering is not None
    blocks = {
        block["primary_element_id"]: block
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
    }
    anchor_block = blocks[anchor_id]
    anchor_block.update(
        markdown=rendering.markdown,
        text=rendering.text,
        contributing_element_ids=[
            anchor_id,
            *(
                contributor_id
                for contributor_id in rendering.contributor_element_ids
                if contributor_id != anchor_id
            ),
        ],
        relationship_ids=list(rendering.relationship_ids),
        excluded_contributions=[],
    )
    anchor_block.pop("omission_reason", None)
    anchor_block.pop("suppressed_by_element_id", None)
    for contributor_id in rendering.contributor_element_ids:
        if contributor_id == anchor_id:
            continue
        block = blocks[contributor_id]
        block.update(
            markdown="",
            text="",
            contributing_element_ids=[],
            relationship_ids=list(rendering.relationship_ids),
            excluded_contributions=[
                {
                    "element_id": anchor_id,
                    "reason": "already_claimed",
                    "relationship_ids": list(rendering.relationship_ids),
                }
            ],
            omission_reason="consumed_by_relationship",
            suppressed_by_element_id=anchor_id,
        )
    _rebuild_canonical_views(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)
    return payload


def _outline_marked_payload() -> dict[str, Any]:
    from pathlib import Path

    from app.services.ir import build_document_ir
    from app.services.pipeline import _docling_table_item
    from app.services.presentation import build_canonical_presentation
    from app.services.table_semantics import finalize_table_pages, seal_table_pages
    from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
        _spanned_table,
    )

    frozen_path = Path(
        "tracker/phase-03-layout/evidence/"
        "P03-US08-post-US07-predecessor-20260801/"
        "settlement-agreement/our-output.json"
    )
    payload = json.loads(frozen_path.read_text())
    page = payload["pages"][0]
    source_sha256 = payload["document"]["sha256"]
    raw_table = deepcopy(_spanned_table())
    raw_table["prov"][0]["page_no"] = 1
    native_text = " ".join(
        str(cell.get("text") or "")
        for cell in raw_table["data"]["table_cells"]
    )
    _page_index, table = _docling_table_item(
        raw_table,
        {1: page["page_height"]},
        {},
        [native_text],
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    table["id"] = "p1-outline-review-table"
    table["reading_order"] = len(page["items"])
    snapshot = table.get("_p04_predecessor_snapshot")
    if isinstance(snapshot, dict):
        snapshot["id"] = table["id"]
        snapshot["reading_order"] = table["reading_order"]
    table_page = {
        key: deepcopy(page[key])
        for key in (
            "page_index",
            "page_number",
            "page_label",
            "page_width",
            "page_height",
            "unit",
            "success",
            "warnings",
        )
    }
    table_page["items"] = [table]
    seal_table_pages(
        [table_page],
        source_sha256,
        [native_text],
        table_span_fidelity_enabled=True,
    )
    finalize_table_pages(
        [table_page],
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    page["items"].append(table_page["items"][0])

    public_ir = build_document_ir(
        {
            "document": {"sha256": source_sha256},
            "pages": [
                {
                    key: deepcopy(public_page[key])
                    for key in (
                        "page_index",
                        "page_number",
                        "page_label",
                        "page_width",
                        "page_height",
                        "unit",
                        "success",
                        "items",
                        "warnings",
                    )
                }
                for public_page in payload["pages"]
            ],
        }
    )
    predecessor = build_canonical_presentation(public_ir)
    table_primary_id = public_ir.pages[0].presentation_element_ids[-1]
    table_block = next(
        block
        for block in predecessor.pages[0].blocks
        if block.primary_element_id == table_primary_id
    )
    payload["canonical_presentation"]["pages"][0]["blocks"].append(
        table_block.model_dump(mode="json", exclude_none=True)
    )
    _rebuild_canonical_views(payload["canonical_presentation"])
    return _bind_empty_source_custody(payload)


def _at(value: dict[str, Any], path: tuple[str | int, ...]) -> Any:
    current: Any = value
    for segment in path:
        current = current[segment]
    return current


def test_table_sidecar_and_every_nested_schema_are_closed() -> None:
    schema = ContentItem.model_json_schema()
    property_schema = schema["properties"]["table_evidence"]
    definitions = schema["$defs"]
    nested = {
        "TableBoundingBox",
        "TableEvidence",
        "TableEvidenceRecord",
        "TableGrid",
        "TablePdfplumberSourceObject",
        "TablePdfplumberWord",
        "TableRepresentationCustody",
        "TableSlot",
        "TableSourceObject",
        "TableSpanDecision",
    }

    assert property_schema["anyOf"][0]["$ref"] == "#/$defs/TableEvidence"
    assert set(definitions["TableEvidence"]["properties"]) == {
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
    assert len(definitions["TableEvidence"]["properties"]) == 17
    assert set(definitions["TableEvidence"]["required"]) == set(
        definitions["TableEvidence"]["properties"]
    )
    assert all(definitions[name]["additionalProperties"] is False for name in nested)
    cell_schema = TableCell.model_json_schema()
    assert cell_schema["additionalProperties"] is False
    assert set(cell_schema["required"]) == set(cell_schema["properties"])
    assert cell_schema["$defs"]["TableConfidenceDimensions"][
        "additionalProperties"
    ] is False
    assert len(cell_schema["properties"]) == 16
    assert definitions["TableGrid"]["properties"]["row_count"]["maximum"] == 4_096
    assert (
        definitions["TableGrid"]["properties"]["column_count"]["maximum"]
        == 256
    )
    assert (
        definitions["TableEvidence"]["properties"]["source_objects"][
            "maxItems"
        ]
        == 65_536
    )
    source_items = definitions["TableEvidence"]["properties"][
        "source_objects"
    ]["items"]
    assert source_items["discriminator"] == {
        "mapping": {
            "docling": "#/$defs/TableSourceObject",
            "pdfplumber": "#/$defs/TablePdfplumberSourceObject",
        },
        "propertyName": "engine",
    }
    assert source_items["oneOf"] == [
        {"$ref": "#/$defs/TableSourceObject"},
        {"$ref": "#/$defs/TablePdfplumberSourceObject"},
    ]
    docling_schema = definitions["TableSourceObject"]
    assert set(docling_schema["properties"]) == {
        "id",
        "engine",
        "object_type",
        "page_index",
        "raw_ref",
        "content_sha256",
    }
    assert set(docling_schema["required"]) == set(docling_schema["properties"])
    assert definitions["TableEvidence"]["properties"]["version"]["const"] == "1.1"
    pdf_schema = definitions["TablePdfplumberSourceObject"]
    assert set(pdf_schema["required"]) == set(pdf_schema["properties"])
    assert pdf_schema["properties"]["raw_ref"]["type"] == "null"
    assert pdf_schema["properties"]["words"]["minItems"] == 1
    assert pdf_schema["properties"]["words"]["maxItems"] == 64
    word_schema = definitions["TablePdfplumberWord"]
    assert set(word_schema["required"]) == set(word_schema["properties"])
    assert word_schema["properties"]["font_name"]["maxLength"] == 256
    confidence_variants = definitions["TableEvidenceRecord"]["properties"][
        "confidence"
    ]["anyOf"]
    assert all(
        variant["minimum"] == 0 and variant["maximum"] == 1
        for variant in confidence_variants
    )
    assert cell_schema["properties"]["text"]["maxLength"] == 16_384
    assert cell_schema["properties"]["evidence_ids"]["maxItems"] == 64


def test_parse_route_exposes_json_markdown_and_text_200_schemas() -> None:
    from app.main import app

    schema = app.openapi()
    response = schema["paths"]["/v1/parse"]["post"]["responses"]["200"]
    content = response["content"]

    assert set(content) == {"application/json", "text/markdown", "text/plain"}
    assert content["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ParseResult"
    }
    assert content["text/markdown"]["schema"] == {"type": "string"}
    assert content["text/plain"]["schema"] == {"type": "string"}
    assert "TableEvidence" in schema["components"]["schemas"]
    assert "TableCell" in schema["components"]["schemas"]
    assert "TableConfidenceDimensions" in schema["components"]["schemas"]
    content_item = schema["components"]["schemas"]["ContentItem"]
    assert content_item["properties"]["cells"]["x-p04-valid-items"] == {
        "$ref": "#/components/schemas/TableCell"
    }
    marked_rule = content_item["allOf"][-1]
    assert marked_rule["if"]["properties"]["table_evidence"]["properties"][
        "status"
    ] == {"const": "valid"}
    assert marked_rule["then"]["properties"]["cells"]["items"] == {
        "$ref": "#/components/schemas/TableCell"
    }


def test_required_sidecar_nulls_survive_exclude_none_dump_and_json() -> None:
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["evidence"][0]["bbox"] = None
    sidecar = TableEvidence.model_validate(raw_sidecar)

    dumped = sidecar.model_dump(mode="json", exclude_none=True)
    encoded = json.loads(sidecar.model_dump_json(exclude_none=True))
    for payload in (dumped, encoded):
        assert set(payload) == set(raw_sidecar)
        assert set(payload["grid"]) == set(raw_sidecar["grid"])
        assert all(
            set(slot) == set(raw_slot)
            for slot, raw_slot in zip(
                payload["slots"], raw_sidecar["slots"], strict=True
            )
        )
        assert all(
            set(source) == set(raw_source)
            for source, raw_source in zip(
                payload["source_objects"],
                raw_sidecar["source_objects"],
                strict=True,
            )
        )
        assert all(
            set(record) == set(raw_record)
            for record, raw_record in zip(
                payload["evidence"],
                raw_sidecar["evidence"],
                strict=True,
            )
        )
        assert all(
            set(decision) == set(raw_decision)
            for decision, raw_decision in zip(
                payload["span_decisions"],
                raw_sidecar["span_decisions"],
                strict=True,
            )
        )
        assert set(payload["representation_custody"]) == set(
            raw_sidecar["representation_custody"]
        )
        assert payload["reconciliation"] is None
        assert payload["gate"] is None
        assert payload["continuation"] is None
        assert payload["slots"][0]["covered_by_cell_id"] is None
        assert payload["slots"][1]["cell_id"] is None
        assert payload["evidence"][0]["bbox"] is None

    unit_cell = deepcopy(_valid_table()["cells"][0])
    unit_cell["row_span"] = 1
    unit_cell["col_span"] = 1
    unit_cell["bbox"] = None
    unit_cell["span_decision_id"] = None
    unit_cell["confidence_dimensions"]["geometry"] = None
    unit_cell["confidence_dimensions"]["header"] = None
    validated_cell = TableCell.model_validate(unit_cell)
    for payload in (
        validated_cell.model_dump(mode="json", exclude_none=True),
        json.loads(validated_cell.model_dump_json(exclude_none=True)),
    ):
        assert set(payload) == set(unit_cell)
        assert payload["bbox"] is None
        assert payload["span_decision_id"] is None
        assert set(payload["confidence_dimensions"]) == {
            "text",
            "geometry",
            "structure",
            "header",
        }
        assert payload["confidence_dimensions"]["geometry"] is None
        assert payload["confidence_dimensions"]["header"] is None

    for slot in sidecar.slots:
        payload = slot.model_dump(mode="json", exclude_none=True)
        assert set(payload) == {
            "id",
            "row",
            "column",
            "kind",
            "cell_id",
            "covered_by_cell_id",
        }

    item = ContentItem.model_validate(_valid_table())
    assert "confidence" not in item.model_dump(exclude_none=True)

    for table in (_production_table(), _production_diagnostic()):
        result = ParseResult.model_validate(
            _bound_payload(table, source_sha256=_hash("a"))
        )
        for payload in (
            result.model_dump(mode="json", exclude_none=True),
            json.loads(result.model_dump_json(exclude_none=True)),
        ):
            serialized_sidecar = payload["pages"][0]["items"][0][
                "table_evidence"
            ]
            assert serialized_sidecar["reconciliation"] is None
            assert serialized_sidecar["gate"] is None
            assert serialized_sidecar["continuation"] is None
            ParseResult.model_validate(payload)


def test_pdfplumber_source_union_is_exact_bounded_and_lossless() -> None:
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"].insert(0, _pdfplumber_source())

    sidecar = TableEvidence.model_validate(raw_sidecar)
    for payload in (
        sidecar.model_dump(mode="json", exclude_none=True),
        json.loads(sidecar.model_dump_json(exclude_none=True)),
    ):
        recovery_source = payload["source_objects"][0]
        assert recovery_source == _pdfplumber_source()
        assert recovery_source["raw_ref"] is None
        assert recovery_source["words"][0]["bbox"]["unit"] == "pt"

    wrong_engine = deepcopy(raw_sidecar)
    wrong_engine["source_objects"][0]["engine"] = "vector"
    with pytest.raises(
        ValidationError,
        match="union tag|Input tag|Extra inputs are not permitted",
    ):
        TableEvidence.model_validate(wrong_engine)

    fabricated_ref = deepcopy(raw_sidecar)
    fabricated_ref["source_objects"][0]["raw_ref"] = "#/words/0"
    with pytest.raises(ValidationError):
        TableEvidence.model_validate(fabricated_ref)

    unknown_source_field = deepcopy(raw_sidecar)
    unknown_source_field["source_objects"][0]["candidate_id"] = _hash("e")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TableEvidence.model_validate(unknown_source_field)

    empty_source_font = deepcopy(raw_sidecar)
    empty_source_font["source_objects"][0]["words"][0]["font_name"] = ""
    empty_source_font["source_objects"][0]["words"][0]["bold"] = False
    with pytest.raises(ValidationError, match="at least|empty"):
        TableEvidence.model_validate(empty_source_font)

    obsolete_version = deepcopy(raw_sidecar)
    obsolete_version["version"] = "1.0"
    with pytest.raises(ValidationError, match="Input should be '1.1'|marker differs"):
        TableEvidence.model_validate(obsolete_version)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda source: source["words"][0].__setitem__("text", " \t "),
            "must not be blank",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "text", "x" * 16_385
            ),
            "at most|oversized",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "text", "unsafe\x00word"
            ),
            "unsafe control",
        ),
        (
            lambda source: source["words"][0].__setitem__("text", "\ud800"),
            "valid string|valid UTF-8",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "font_name", "x" * 257
            ),
            "at most|oversized",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "font_name", "unsafe\x00font"
            ),
            "unsafe control",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "font_name", "unsafe\nfont"
            ),
            "font metadata.*unsafe control",
        ),
        (
            lambda source: source["words"][0].__setitem__(
                "font_name", "unsafe\tfont"
            ),
            "font metadata.*unsafe control",
        ),
        (
            lambda source: source["words"][0].__setitem__("bold", False),
            "bold derivation",
        ),
        (
            lambda source: source["words"][0]["bbox"].__setitem__("x", -1),
            "greater than or equal|bounded table number",
        ),
        (
            lambda source: source["words"][0]["bbox"].__setitem__(
                "width", float("inf")
            ),
            "finite",
        ),
        (
            lambda source: source.__setitem__("target_column", 256),
            "less than 256|bounded strict integer",
        ),
    ],
)
def test_pdfplumber_source_rejects_malformed_words(
    mutation: Any,
    message: str,
) -> None:
    source = _pdfplumber_source()
    mutation(source)
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"].insert(0, source)

    with pytest.raises(ValidationError, match=message):
        TableEvidence.model_validate(raw_sidecar)


def test_pdfplumber_word_order_geometry_and_source_caps_are_closed() -> None:
    reordered = _pdfplumber_source()
    reordered["words"].reverse()
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"].insert(0, reordered)
    with pytest.raises(ValidationError, match="physical order"):
        TableEvidence.model_validate(raw_sidecar)

    duplicate_geometry = _pdfplumber_source()
    duplicate_geometry["words"][1]["bbox"] = deepcopy(
        duplicate_geometry["words"][0]["bbox"]
    )
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"].insert(0, duplicate_geometry)
    with pytest.raises(ValidationError, match="geometry repeats"):
        TableEvidence.model_validate(raw_sidecar)

    too_many_words = _pdfplumber_source()
    word = too_many_words["words"][0]
    too_many_words["words"] = []
    for index in range(65):
        copied = deepcopy(word)
        copied["id"] = f"{index:064x}"
        copied["bbox"]["x"] = index
        too_many_words["words"].append(copied)
    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"].insert(0, too_many_words)
    with pytest.raises(ValidationError, match="at most 64|between 1 and 64"):
        TableEvidence.model_validate(raw_sidecar)

    raw_sidecar = _valid_table()["table_evidence"]
    raw_sidecar["source_objects"] = []
    for index in range(49):
        source = _pdfplumber_source()
        source["id"] = f"{index:064x}"
        source["target_column"] = 0
        source["words"][0]["id"] = f"{index + 100:064x}"
        source["words"][1]["id"] = f"{index + 200:064x}"
        raw_sidecar["source_objects"].append(source)
    with pytest.raises(ValidationError, match="recovery source count"):
        TableEvidence.model_validate(raw_sidecar)

    repeated_target = _valid_table()["table_evidence"]
    first_source = _pdfplumber_source()
    second_source = deepcopy(first_source)
    second_source["id"] = _hash("e")
    repeated_target["source_objects"] = [
        first_source,
        repeated_target["source_objects"][0],
        second_source,
    ]
    with pytest.raises(ValidationError, match="source target repeats"):
        TableEvidence.model_validate(repeated_target)

    wrong_role_row = _valid_table()["table_evidence"]
    body_source = _pdfplumber_source()
    body_source["role"] = "body_control"
    wrong_role_row["source_objects"].insert(0, body_source)
    with pytest.raises(ValidationError, match="role target"):
        TableEvidence.model_validate(wrong_role_row)


def test_raw_sidecar_preflight_admits_and_rejects_the_exact_8mib_boundary() -> None:
    from app.models import _bounded_table_json_size

    admitted = _large_pdfplumber_sidecar(2_549)
    rejected = _large_pdfplumber_sidecar(2_550)

    assert _bounded_table_json_size(admitted, 8 * 1024 * 1024) == 8_386_608
    assert _bounded_table_json_size(rejected, 8 * 1024 * 1024) is None
    assert len(TableEvidence.model_validate(admitted).source_objects) == 48
    with pytest.raises(ValidationError, match="evidence exceeds its byte cap"):
        TableEvidence.model_validate(rejected)


def test_raw_preflight_rejects_unreachable_graph_count_before_models() -> None:
    table = _valid_table()
    sources = []
    for index in range(128):
        sources.append(
            {
                "id": f"{index + 1:064x}",
                "engine": "docling",
                "object_type": "table_cell",
                "page_index": 1,
                "raw_ref": f"#/tables/0/data/table_cells/{index + 1}",
                "content_sha256": _hash("f"),
            }
        )
    sources.append(table["table_evidence"]["source_objects"][0])
    sources.sort(key=lambda source: source["id"])
    table["table_evidence"]["source_objects"] = sources

    with pytest.raises(ValidationError, match="source graph count is unreachable"):
        ParseResult.model_validate(_parse_payload(table))


def test_raw_document_preflight_rejects_64mib_sidecar_aggregate() -> None:
    large_sidecar = _large_pdfplumber_sidecar(2_200)
    base_item = _valid_table()
    items = []
    for index in range(10):
        sidecar = dict(large_sidecar)
        sidecar["table_id"] = f"{index + 100:064x}"
        sidecar["candidate_id"] = f"{index + 200:064x}"
        item = dict(base_item)
        item["id"] = f"table-{index}"
        item["reading_order"] = index
        item["table_evidence"] = sidecar
        items.append(item)
    payload = _parse_payload(items[0])
    payload["pages"][0]["items"] = items

    with pytest.raises(ValidationError, match="document aggregate"):
        ParseResult.model_validate(payload)


def test_fresh_process_near_bound_sidecar_rss_and_early_rejection() -> None:
    script = r"""
import gc
import json
import os
import threading
import time

import psutil
from pydantic import ValidationError

from app.models import TableEvidence
from tests.contract.test_p04_us01_table_api_schema import (
    _large_pdfplumber_sidecar,
)

process = psutil.Process(os.getpid())
for word_bytes in (2549, 2550):
    raw = _large_pdfplumber_sidecar(word_bytes)
    gc.collect()
    baseline = process.memory_info().rss
    peak = [baseline]
    running = [True]

    def sample():
        while running[0]:
            peak[0] = max(peak[0], process.memory_info().rss)
            time.sleep(0.001)

    sampler = threading.Thread(target=sample)
    sampler.start()
    started = time.perf_counter()
    admitted = True
    try:
        model = TableEvidence.model_validate(raw)
    except ValidationError:
        admitted = False
        model = None
    elapsed = time.perf_counter() - started
    running[0] = False
    sampler.join()
    peak[0] = max(peak[0], process.memory_info().rss)
    print(json.dumps({
        "word_bytes": word_bytes,
        "admitted": admitted,
        "elapsed_seconds": elapsed,
        "rss_delta_bytes": peak[0] - baseline,
    }))
    del model, raw
    gc.collect()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    measurements = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]

    assert [record["admitted"] for record in measurements] == [True, False]
    assert all(
        record["rss_delta_bytes"] <= 64 * 1024 * 1024
        for record in measurements
    )
    assert measurements[1]["elapsed_seconds"] < measurements[0][
        "elapsed_seconds"
    ]


def test_live_api_retains_required_sidecar_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api as api_module
    from app.main import app

    result = ParseResult.model_validate(
        _bound_payload(_production_table(), source_sha256=_hash("a"))
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
                    b"%PDF-1.7\n% P04-US01 table\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200
    sidecar = response.json()["pages"][0]["items"][0]["table_evidence"]
    assert sidecar["reconciliation"] is None
    assert sidecar["gate"] is None
    assert sidecar["continuation"] is None


@pytest.mark.parametrize(
    "mutation",
    ["private_snapshot", "unauthorized_reconciliation"],
)
def test_live_api_revalidates_raw_parser_results_before_serialization(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    import app.api as api_module
    from app.main import app

    payload = _parse_payload(_production_table(), source_sha256=_hash("a"))
    table = payload["pages"][0]["items"][0]
    if mutation == "private_snapshot":
        table["_p04_predecessor_snapshot"] = {"type": "table"}
    else:
        table["table_evidence"]["reconciliation"] = {
            "selected_candidate_id": _hash("f")
        }
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% hostile P04-US01 result\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    encoded = response.text
    assert "_p04_predecessor_snapshot" not in encoded
    assert "selected_candidate_id" not in encoded


def test_live_api_rejects_coercible_marked_table_binding_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api as api_module
    from app.main import app

    payload = _parse_payload(_production_table(), source_sha256=_hash("a"))
    payload["document"]["page_count"] = "1"
    payload["pages"][0]["page_index"] = "1"
    payload["pages"][0]["page_width"] = "300"
    payload["pages"][0]["page_height"] = "300"
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% coercible P04-US01 result\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert "coercible P04-US01 result" not in response.text


def test_valid_table_is_strictly_validated_and_serializes_without_loss() -> None:
    table = _valid_table()
    validated = ContentItem.model_validate(table)
    public = validated.model_dump(mode="json")

    assert public["table_evidence"] == table["table_evidence"]
    assert public["cells"] == table["cells"]
    assert public["rows"] == table["rows"]
    assert jsonable_encoder(validated)["table_evidence"] == table["table_evidence"]

    production = _production_table()
    encoded = json.dumps(
        _bound_payload(production, source_sha256=_hash("a")),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    result = ParseResult.model_validate_json(encoded)
    assert to_markdown(result) == f"{production['html']}\n"


def test_table_marker_requires_canonical_while_marker_free_legacy_remains_optional(
) -> None:
    marked = _parse_payload(_production_table(), source_sha256=_hash("a"))
    with pytest.raises(
        ValidationError,
        match="marked table canonical presentation is absent",
    ):
        ParseResult.model_validate(marked)

    null_marker = deepcopy(marked)
    null_marker["pages"][0]["items"][0]["table_evidence"] = None
    with pytest.raises(
        ValidationError,
        match="marked table canonical presentation is absent",
    ):
        ParseResult.model_validate(null_marker)

    marker_free = deepcopy(marked)
    marker_free["pages"][0]["items"][0].pop("table_evidence")
    result = ParseResult.model_validate(marker_free)
    assert result.pages[0].items[0].type == "table"


def test_final_marked_custody_requires_exact_canonical_presentation_digest(
) -> None:
    payload = _bound_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    sidecar = payload["canonical_source_custody"]
    assert sidecar["canonical_presentation_sha256"] == (
        _canonical_presentation_sha256(payload["canonical_presentation"])
    )

    intermediate = deepcopy(sidecar)
    intermediate.pop("canonical_presentation_sha256")
    assert (
        CanonicalSourceCustody.model_validate(
            intermediate
        ).canonical_presentation_sha256
        is None
    )

    missing = deepcopy(payload)
    missing["canonical_source_custody"].pop(
        "canonical_presentation_sha256"
    )
    with pytest.raises(
        ValidationError,
        match="canonical presentation custody digest is absent",
    ):
        ParseResult.model_validate(missing)

    null = deepcopy(payload)
    null["canonical_source_custody"]["canonical_presentation_sha256"] = None
    with pytest.raises(
        ValidationError,
        match="canonical presentation SHA-256.*lower-case SHA-256",
    ):
        ParseResult.model_validate(null)


def test_marked_canonical_substitution_without_reseal_fails_closed() -> None:
    payload = _marked_payload_with_text()
    text_block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    text_block["markdown"] = "coherent but unsealed substitution"
    text_block["text"] = "coherent but unsealed substitution"
    _rebuild_canonical_views(payload["canonical_presentation"])

    with pytest.raises(
        ValidationError,
        match="canonical presentation digest differs",
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "primary_only",
        "remapped_relationships",
        "reordered_contributors",
        "reordered_relationships",
    ],
)
def test_production_table_requires_exact_ordered_canonical_graph(
    mutation: str,
) -> None:
    from app.services.presentation import CanonicalPresentation

    payload = _bound_payload(_production_table(), source_sha256=_hash("a"))
    block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    assert len(block["contributing_element_ids"]) == 5
    assert len(block["relationship_ids"]) == 4
    if mutation == "primary_only":
        block["contributing_element_ids"] = [block["primary_element_id"]]
    elif mutation == "remapped_relationships":
        block["relationship_ids"] = [
            f"forged-table-relationship-{index}"
            for index, _relationship_id in enumerate(block["relationship_ids"])
        ]
    elif mutation == "reordered_contributors":
        block["contributing_element_ids"] = [
            block["primary_element_id"],
            *reversed(block["contributing_element_ids"][1:]),
        ]
    else:
        block["relationship_ids"].reverse()
    _rebuild_canonical_views(payload["canonical_presentation"])
    CanonicalPresentation.model_validate(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)

    with pytest.raises(ValidationError, match="canonical exact graph"):
        ParseResult.model_validate(payload)


def test_visual_subordinate_ocr_requires_the_exact_closed_projection() -> None:
    from app.services.presentation import CanonicalPresentation

    payload = _visual_marked_payload()
    validated = ParseResult.model_validate(payload)
    owner = validated.pages[0].items[0]
    assert owner.model_extra["include_ocr_in_primary"] is False
    assert "ACME" not in validated.model_extra["canonical_presentation"][
        "full"
    ]["markdown"]

    forged = deepcopy(payload)
    forged_owner = forged["pages"][0]["items"][0]
    forged_owner["value"] = "ACME"
    forged_owner["md"] = "ACME"
    owner_block = forged["canonical_presentation"]["pages"][0]["blocks"][0]
    owner_block["markdown"] = "ACME"
    owner_block["text"] = "ACME"
    _rebuild_canonical_views(forged["canonical_presentation"])
    CanonicalPresentation.model_validate(forged["canonical_presentation"])
    _reseal_bound_canonical(forged)
    with pytest.raises(
        ValidationError,
        match="canonical (?:layout overlay|visual primary)",
    ):
        ParseResult.model_validate(forged)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("source", "derived"),
        ("type", "text"),
        ("presentation_role", "primary"),
        ("contained_by", "other-visual"),
        ("relationship_basis", "geometry"),
        ("relationship_id", "other-relationship"),
    ),
)
def test_visual_subordinate_child_rejects_nonclosed_custody(
    field: str,
    replacement: str,
) -> None:
    payload = _visual_marked_payload()
    contained = payload["pages"][0]["items"][0]["contained_items"]
    assert len(contained) == 1
    contained[0][field] = replacement

    with pytest.raises(
        ValidationError,
        match="marked table canonical contained-item custody differs",
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize("remap_public_sidecar", [False, True])
def test_form_replacement_rejects_globally_consistent_relationship_remap(
    remap_public_sidecar: bool,
) -> None:
    from app.services.presentation import CanonicalPresentation

    payload = _form_replace_marked_payload()
    ParseResult.model_validate(payload)
    anchor = next(
        item
        for item in payload["pages"][1]["items"]
        if (item.get("form_group") or {}).get("canonical_mode") == "replace"
    )
    contributor_ids = anchor["form_group"]["contributor_element_ids"]
    anchor_id = anchor["form_group"]["anchor_element_id"]
    blocks = {
        block["primary_element_id"]: block
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
    }
    assert len(contributor_ids) == 8
    assert len(blocks[anchor_id]["relationship_ids"]) == 20
    remap = {
        relationship_id: f"forged-form-relationship-{index}"
        for index, relationship_id in enumerate(
            blocks[anchor_id]["relationship_ids"]
        )
    }
    if remap_public_sidecar:
        group = anchor["form_group"]
        for key in ("relationship_ids", "anchor_relationship_ids"):
            group[key] = [
                remap[relationship_id]
                for relationship_id in group[key]
            ]
        for collection in (
            "form_fields",
            "form_labels",
            "form_value_regions",
            "form_controls",
            "form_key_value_pairs",
        ):
            for record in anchor.get(collection, []):
                record["relationship_ids"] = [
                    remap[relationship_id]
                    for relationship_id in record["relationship_ids"]
                ]
        for relationship in anchor["relationships"]:
            relationship_id = relationship["id"]
            if relationship_id in remap:
                relationship["id"] = remap[relationship_id]
    for contributor_id in contributor_ids:
        block = blocks[contributor_id]
        block["relationship_ids"] = [
            remap[relationship_id]
            for relationship_id in block["relationship_ids"]
        ]
        for exclusion in block["excluded_contributions"]:
            exclusion["relationship_ids"] = [
                remap[relationship_id]
                for relationship_id in exclusion["relationship_ids"]
            ]
    _rebuild_canonical_views(payload["canonical_presentation"])
    CanonicalPresentation.model_validate(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)

    with pytest.raises(ValidationError, match="canonical form custody"):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    ["contributor", "relationship", "exclusion"],
)
def test_outline_replacement_requires_exact_derived_graph(
    mutation: str,
) -> None:
    from app.services.presentation import CanonicalPresentation

    payload = _outline_marked_payload()
    ParseResult.model_validate(payload)
    anchor = next(
        item
        for item in payload["pages"][0]["items"]
        if isinstance(item.get("outline_group"), dict)
    )
    group = anchor["outline_group"]
    block = next(
        candidate
        for candidate in payload["canonical_presentation"]["pages"][0][
            "blocks"
        ]
        if candidate["primary_element_id"]
        == group["canonical_primary_element_id"]
    )
    if mutation == "contributor":
        group["canonical_contributor_element_ids"].append(
            "el-forged-extra"
        )
        block["contributing_element_ids"].append("el-forged-extra")
    elif mutation == "relationship":
        group["canonical_relationship_ids"].append(
            "rel-forged-extra"
        )
        block["relationship_ids"].append("rel-forged-extra")
    else:
        block["excluded_contributions"].append(
            {
                "element_id": "el-forged-excluded",
                "reason": "evidence_only_relationship",
                "relationship_ids": [block["relationship_ids"][0]],
            }
        )
    _rebuild_canonical_views(payload["canonical_presentation"])
    CanonicalPresentation.model_validate(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)

    with pytest.raises(
        ValidationError,
        match="canonical outline (?:custody|exact graph)",
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize("status", ["valid", "unresolved", "structural_failure"])
def test_marked_table_canonical_presentation_is_bound_to_authoritative_projection(
    status: str,
) -> None:
    table = _production_table() if status == "valid" else _production_diagnostic()
    table["table_evidence"]["status"] = status
    if status == "unresolved":
        table["table_evidence"]["concerns"] = [
            "table_source_span_evidence_unresolved"
        ]
    payload = _with_bound_canonical(
        _parse_payload(table, source_sha256=_hash("a"))
    )

    result = ParseResult.model_validate(payload)
    public = result.model_dump(mode="json", exclude_unset=True)

    assert public["pages"][0]["items"][0]["html"] == table["html"]
    canonical_block = public["canonical_presentation"]["pages"][0]["blocks"][0]
    assert canonical_block["primary_element_type"] == "table"
    assert canonical_block.get("omission_reason") is None
    assert canonical_block["markdown"] == table["html"]
    assert to_markdown(public) == f"{table['html']}\n"


def test_marked_table_canonical_binding_preserves_projected_p03_page_identity() -> None:
    from app.models import _canonical_ir_id
    from app.services.ir import build_document_ir
    from app.services.pipeline import _docling_table_item
    from app.services.presentation import (
        CanonicalPresentation,
        build_canonical_presentation,
    )
    from app.services.table_semantics import finalize_table_pages, seal_table_pages
    from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
        _spanned_table,
    )
    from tests.stories.phase_03.test_p03_us08_running_regions import (
        _direct_projected_witness,
    )

    projected, _ir, _predecessor, _predecessor_ir = _direct_projected_witness()
    source_sha256 = projected["document"]["sha256"]
    raw_table = _spanned_table()
    raw_table["prov"][0]["bbox"] = {
        "l": 0.0,
        "t": 10.0,
        "r": 300.0,
        "b": 120.0,
        "coord_origin": "TOPLEFT",
    }
    native_text = " ".join(
        str(cell.get("text") or "")
        for cell in raw_table["data"]["table_cells"]
    )
    _page_index, table = _docling_table_item(
        deepcopy(raw_table),
        {1: 792.0},
        {},
        [native_text],
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    table["id"] = "p1-table"
    table["reading_order"] = 1
    snapshot = table.get("_p04_predecessor_snapshot")
    if isinstance(snapshot, dict):
        snapshot["id"] = table["id"]
        snapshot["reading_order"] = table["reading_order"]
    table_pages = [
        {
            "page_index": 1,
            "page_number": 1,
            "page_label": "1",
            "page_width": 612.0,
            "page_height": 792.0,
            "unit": "pt",
            "success": True,
            "items": [table],
            "warnings": [],
        }
    ]
    seal_table_pages(
        table_pages,
        source_sha256,
        [native_text],
        table_span_fidelity_enabled=True,
    )
    finalize_table_pages(
        table_pages,
        source_sha256,
        table_span_fidelity_enabled=True,
    )
    table = table_pages[0]["items"][0]
    assert table["table_evidence"]["status"] == "valid"

    ir_source = {
        "document": {"sha256": source_sha256},
        "pages": [{**table_pages[0], "items": [table]}],
    }
    table_ir = build_document_ir(ir_source)
    [table_primary_id] = table_ir.pages[0].presentation_element_ids
    table_block = build_canonical_presentation(table_ir).pages[0].blocks[
        0
    ].model_dump(mode="json", exclude_none=True)

    projected["schema_version"] = "1.0"
    projected["document"].update(
        filename="combined-p03-p04.pdf",
        mime_type="application/pdf",
        page_count=1,
    )
    projected["processing"].update(
        engine="synthetic",
        ocr_engine="none",
        ocr_languages=[],
        duration_ms=1,
    )
    projected["warnings"] = []
    projected["pages"][0]["items"].append(table)
    canonical = projected["canonical_presentation"]
    canonical.update(
        schema_version="1.0",
        source_ir_version="1.0",
        policy_id="canonical-presentation-v1",
    )
    table_block["id"] = _canonical_ir_id(
        "pb",
        "1.0",
        "canonical-presentation-v1",
        "page-1",
        table_primary_id,
    )
    table_block["page_id"] = "page-1"
    canonical["pages"][0]["blocks"].append(table_block)
    _rebuild_canonical_views(canonical)
    CanonicalPresentation.model_validate(canonical)

    _bind_empty_source_custody(projected)
    validated = ParseResult.model_validate(projected)
    assert validated.pages[0].page_identity is not None
    assert validated.pages[0].page_identity.page_id == "page-1"

    stale = deepcopy(projected)
    stale_block = next(
        block
        for block in stale["canonical_presentation"]["pages"][0]["blocks"]
        if block["primary_element_type"] == "table"
    )
    stale_block["markdown"] = "<table><tr><td>STALE P03+P04</td></tr></table>"
    stale_block["text"] = "STALE P03+P04"
    _rebuild_canonical_views(stale["canonical_presentation"])
    CanonicalPresentation.model_validate(stale["canonical_presentation"])
    _reseal_bound_canonical(stale)
    with pytest.raises(
        ValidationError,
        match="canonical (?:content custody|exact graph)",
    ):
        ParseResult.model_validate(stale)


@pytest.mark.parametrize("status", ["valid", "unresolved", "structural_failure"])
def test_marked_table_rejects_independently_valid_stale_canonical_content(
    status: str,
) -> None:
    from app.services.presentation import CanonicalPresentation

    table = _production_table() if status == "valid" else _production_diagnostic()
    table["table_evidence"]["status"] = status
    if status == "unresolved":
        table["table_evidence"]["concerns"] = [
            "table_source_span_evidence_unresolved"
        ]
    payload = _stale_canonical_payload(table, status=status)
    CanonicalPresentation.model_validate(payload["canonical_presentation"])

    with pytest.raises(
        ValidationError,
        match="canonical (?:content custody|exact graph)",
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_marked_table_rejects_missing_extra_or_duplicate_canonical_projection(
    mutation: str,
) -> None:
    from app.services.presentation import CanonicalPresentation

    table = _production_table()
    payload = _with_bound_canonical(
        _parse_payload(table, source_sha256=_hash("a"))
    )
    canonical = payload["canonical_presentation"]
    blocks = canonical["pages"][0]["blocks"]
    original = deepcopy(blocks[0])
    if mutation == "missing":
        blocks.clear()
    else:
        forged = deepcopy(original)
        forged["id"] = f"canonical-forged-{mutation}"
        if mutation == "extra":
            forged["primary_element_id"] = "el-forged-table"
            forged["contributing_element_ids"] = ["el-forged-table"]
        blocks.append(forged)
    _rebuild_canonical_views(canonical)

    if mutation != "duplicate":
        CanonicalPresentation.model_validate(canonical)
    with pytest.raises(
        ValidationError,
        match=(
            "canonical (?:table|block) coverage|repeats a primary element"
        ),
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_block",
        "missing_public_item",
        "reordered",
        "mistyped",
        "misbound",
        "altered_canonical",
        "altered_public",
    ],
)
def test_marked_table_binds_every_non_table_block_and_exact_order(
    mutation: str,
) -> None:
    payload = _marked_payload_with_text()
    canonical = payload["canonical_presentation"]
    blocks = canonical["pages"][0]["blocks"]
    if mutation == "missing_block":
        blocks.pop(0)
    elif mutation == "missing_public_item":
        payload["pages"][0]["items"].pop(0)
        payload["pages"][0]["items"][0]["reading_order"] = 0
    elif mutation == "reordered":
        blocks.reverse()
    elif mutation == "mistyped":
        blocks[0]["primary_element_type"] = "heading"
    elif mutation == "misbound":
        blocks[0]["primary_element_id"], blocks[1]["primary_element_id"] = (
            blocks[1]["primary_element_id"],
            blocks[0]["primary_element_id"],
        )
        blocks[0]["contributing_element_ids"] = [
            blocks[0]["primary_element_id"]
        ]
        blocks[1]["contributing_element_ids"] = [
            blocks[1]["primary_element_id"]
        ]
    elif mutation == "altered_canonical":
        blocks[0]["markdown"] = "FORGED NON-TABLE CONTENT"
        blocks[0]["text"] = "FORGED NON-TABLE CONTENT"
    else:
        payload["pages"][0]["items"][0]["value"] = "ALTERED PUBLIC CONTENT"
        payload["pages"][0]["items"][0]["md"] = "ALTERED PUBLIC CONTENT"
    _rebuild_canonical_views(canonical)
    _reseal_bound_canonical(payload)

    with pytest.raises(ValidationError, match="marked table canonical"):
        ParseResult.model_validate(payload)


def test_marked_table_rejects_reversed_table_blocks() -> None:
    payload = _parse_payload(_production_table(), source_sha256=_hash("a"))
    payload["pages"][0]["items"].append(
        {
            "id": "legacy-table",
            "type": "table",
            "reading_order": 1,
            "value": [["Legacy"]],
            "rows": [["Legacy"]],
            "html": "<table><tr><td>Legacy</td></tr></table>",
            "md": "<table><tr><td>Legacy</td></tr></table>",
            "csv": "Legacy\n",
            "source": "native",
        }
    )
    payload = _with_bound_canonical(payload)
    payload["canonical_presentation"]["pages"][0]["blocks"].reverse()
    _rebuild_canonical_views(payload["canonical_presentation"])
    _reseal_bound_canonical(payload)

    with pytest.raises(ValidationError, match="canonical block binding"):
        ParseResult.model_validate(payload)


def test_marked_table_preserves_caption_body_and_source_note_relationships() -> None:
    table = _production_table()
    table["caption"] = "Reviewed caption"
    table["source_note"] = "Reviewed source note"
    payload = _bound_payload(table, source_sha256=_hash("a"))

    result = ParseResult.model_validate(payload)
    canonical_block = result.model_extra["canonical_presentation"]["pages"][0][
        "blocks"
    ][0]
    assert canonical_block["markdown"] == (
        f"Reviewed caption\n\n{table['html'].strip()}\n\nReviewed source note"
    )
    assert len(canonical_block["contributing_element_ids"]) == 7
    assert len(canonical_block["relationship_ids"]) == 6


def test_marked_canonical_preflight_enforces_exact_resource_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import models

    one_block = _with_bound_canonical(
        _parse_payload(_production_table(), source_sha256=_hash("a"))
    )
    block = one_block["canonical_presentation"]["pages"][0]["blocks"][0]
    block["markdown"] = "x" * models._TABLE_MAX_ITEM_BYTES
    models._preflight_raw_marked_canonical(one_block)
    block["markdown"] += "x"
    with pytest.raises(ValueError, match="block scalar exceeds"):
        models._preflight_raw_marked_canonical(one_block)

    one_block = _with_bound_canonical(
        _parse_payload(_production_table(), source_sha256=_hash("a"))
    )
    two_blocks = _marked_payload_with_text()
    monkeypatch.setattr(models, "_TABLE_MAX_CANONICAL_BLOCKS", 1)
    models._preflight_raw_marked_canonical(one_block)
    with pytest.raises(ValueError, match="block coverage"):
        models._preflight_raw_marked_canonical(two_blocks)

    canonical = one_block["canonical_presentation"]
    exact_view_bytes = sum(
        len(str(container[name][field]).encode("utf-8"))
        for container in (*canonical["pages"], canonical)
        for name in ("full", "body", "header", "footer")
        for field in ("markdown", "text")
    )
    monkeypatch.setattr(
        models,
        "_TABLE_MAX_CANONICAL_VIEW_BYTES",
        exact_view_bytes,
    )
    models._preflight_raw_marked_canonical(one_block)
    monkeypatch.setattr(
        models,
        "_TABLE_MAX_CANONICAL_VIEW_BYTES",
        exact_view_bytes - 1,
    )
    with pytest.raises(ValueError, match="views exceed"):
        models._preflight_raw_marked_canonical(one_block)


def test_legacy_unmarked_canonical_projection_remains_compatible() -> None:
    payload = _marked_payload_with_text()
    payload["pages"][0]["items"][1].pop("table_evidence")
    payload.pop("canonical_source_custody")
    text_block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    text_block["markdown"] = "Legacy additive canonical content"
    text_block["text"] = "Legacy additive canonical content"
    _rebuild_canonical_views(payload["canonical_presentation"])

    result = ParseResult.model_validate(payload)
    assert result.pages[0].items[0].value == "Authoritative prose"


def test_frozen_phase03_canonical_outputs_remain_compatible() -> None:
    from pathlib import Path

    root = Path(
        "tracker/phase-03-layout/evidence/"
        "P03-US08-post-US07-predecessor-20260801"
    )
    evidence_paths = sorted(root.glob("*/our-output.json"))
    assert len(evidence_paths) == 15
    for evidence_path in evidence_paths:
        ParseResult.model_validate(json.loads(evidence_path.read_text()))


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_live_api_rejects_forged_non_table_canonical_content_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    import app.api as api_module
    from app.main import app

    payload = _marked_payload_with_text()
    text_block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    text_block["markdown"] = "FORGED NON-TABLE SECRET"
    text_block["text"] = "FORGED NON-TABLE SECRET"
    _rebuild_canonical_views(payload["canonical_presentation"])
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/v1/parse?output_format={output_format}",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% forged canonical non-table\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert "FORGED NON-TABLE SECRET" not in response.text


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_live_api_rejects_subordinate_visual_ocr_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    import app.api as api_module
    from app.main import app
    from app.services.presentation import CanonicalPresentation

    payload = _visual_marked_payload()
    owner = payload["pages"][0]["items"][0]
    assert owner["include_ocr_in_primary"] is False
    assert owner["contained_items"][0]["value"] == "ACME"
    owner["value"] = "ACME"
    owner["md"] = "ACME"
    owner_block = payload["canonical_presentation"]["pages"][0]["blocks"][0]
    owner_block["markdown"] = "ACME"
    owner_block["text"] = "ACME"
    _rebuild_canonical_views(payload["canonical_presentation"])
    CanonicalPresentation.model_validate(payload["canonical_presentation"])
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/v1/parse?output_format={output_format}",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% forged subordinate OCR\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert "ACME" not in response.text


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_live_api_accepts_only_bound_canonical_table_projection(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    import app.api as api_module
    from app.main import app

    table = _production_table()
    result = ParseResult.model_validate(
        _with_bound_canonical(
            _parse_payload(table, source_sha256=_hash("a"))
        )
    )
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: result,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/v1/parse?output_format={output_format}",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% P04-US01 bound canonical table\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 200
    if output_format == "markdown":
        assert response.headers["content-type"].startswith("text/markdown")
        assert response.text == f"{table['html']}\n"
    else:
        public = response.json()
        assert public["pages"][0]["items"][0]["html"] == table["html"]
        assert (
            public["canonical_presentation"]["pages"][0]["blocks"][0][
                "markdown"
            ]
            == table["html"]
        )


@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_live_api_rejects_stale_canonical_table_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
) -> None:
    import app.api as api_module
    from app.main import app

    payload = _stale_canonical_payload(_production_table(), status="valid")
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/v1/parse?output_format={output_format}",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% P04-US01 stale canonical table\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert "STALE valid" not in response.text


@pytest.mark.parametrize("output_format", ["json", "markdown"])
@pytest.mark.parametrize("mutation", ["malformed_marker", "custody_invalid"])
def test_live_api_canonical_table_remains_fail_closed_for_invalid_markers(
    monkeypatch: pytest.MonkeyPatch,
    output_format: str,
    mutation: str,
) -> None:
    import app.api as api_module
    from app.main import app

    payload = _with_bound_canonical(
        _parse_payload(_production_table(), source_sha256=_hash("a"))
    )
    table = payload["pages"][0]["items"][0]
    if mutation == "malformed_marker":
        table["table_evidence"].pop("representation_custody")
    else:
        table["rows"][0][0] = "CUSTODY INVALID"
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/v1/parse?output_format={output_format}",
            files={
                "file": (
                    "table.pdf",
                    b"%PDF-1.7\n% P04-US01 invalid marker\n",
                    "application/pdf",
                )
            },
        )

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert "CUSTODY INVALID" not in response.text


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("table_evidence", "slots", 1, "covered_by_cell_id"), _hash("0")),
        (("table_evidence", "slots", 1, "column"), 0),
        (("table_evidence", "span_decisions", 0, "cell_id"), _hash("0")),
        (("table_evidence", "span_decisions", 0, "emitted_col_span"), 1),
        (
            ("table_evidence", "representation_custody", "cells_sha256"),
            _hash("0"),
        ),
        (("table_evidence", "table_id"), _hash("0")),
        (("cells", 0, "evidence_ids"), [_hash("0")]),
        (("rows", 0, 0), "custody tamper"),
    ],
)
def test_parse_result_delegates_topology_and_custody_to_runtime_validator(
    path: tuple[str | int, ...],
    replacement: Any,
) -> None:
    table = _production_table()
    parent = _at(table, path[:-1])
    parent[path[-1]] = replacement

    ContentItem.model_validate(table)
    with pytest.raises(
        ValidationError,
        match="topology or custody|graph reference",
    ):
        ParseResult.model_validate(
            _bound_payload(table, source_sha256=_hash("a"))
        )


def test_parse_result_binds_marked_table_to_document_and_outer_page() -> None:
    table = _production_table()
    with pytest.raises(
        ValidationError,
        match="topology or custody|page/document coverage",
    ):
        ParseResult.model_validate(
            _bound_payload(table, source_sha256=_hash("b"))
        )

    wrong_page = _bound_payload(table, source_sha256=_hash("a"))
    wrong_page["pages"][0]["page_index"] = 2
    with pytest.raises(
        ValidationError,
        match="topology or custody|page/document coverage",
    ):
        ParseResult.model_validate(wrong_page)

    clipped_page = _bound_payload(table, source_sha256=_hash("a"))
    clipped_page["pages"][0]["page_width"] = 10
    with pytest.raises(ValidationError, match="topology or custody"):
        ParseResult.model_validate(clipped_page)


def test_marked_document_page_item_and_table_identities_are_exact() -> None:
    wrong_count = _parse_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    wrong_count["document"]["page_count"] = 2
    with pytest.raises(ValidationError, match="page/document coverage"):
        ParseResult.model_validate(wrong_count)

    wrong_order = _parse_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    wrong_order["pages"][0]["items"][0]["reading_order"] = 1
    with pytest.raises(ValidationError, match="item identity/order"):
        ParseResult.model_validate(wrong_order)

    duplicate_item = _parse_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    duplicate_item["pages"][0]["items"].append(
        {
            "id": duplicate_item["pages"][0]["items"][0]["id"],
            "type": "text",
            "reading_order": 1,
            "value": "duplicate item identity",
        }
    )
    with pytest.raises(ValidationError, match="item identity/order"):
        ParseResult.model_validate(duplicate_item)

    duplicate_table = _parse_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    repeated = deepcopy(duplicate_table["pages"][0]["items"][0])
    repeated["id"] = "table-duplicate"
    repeated["reading_order"] = 1
    duplicate_table["pages"][0]["items"].append(repeated)
    with pytest.raises(ValidationError, match="document identity repeats"):
        ParseResult.model_validate(duplicate_table)


def test_parse_result_binds_recovery_words_to_outer_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.table_semantics as table_semantics

    monkeypatch.setattr(
        table_semantics,
        "validate_table_semantics",
        lambda _item, _source_sha256: True,
    )
    table = _valid_table()
    table["table_evidence"]["source_objects"].insert(
        0,
        _pdfplumber_source(),
    )
    table["table_evidence"]["evidence"][0]["source_object_ids"].insert(
        0,
        _pdfplumber_source()["id"],
    )
    ParseResult.model_validate(_bound_payload(table))

    outside = deepcopy(table)
    outside["table_evidence"]["source_objects"][0]["words"][0]["bbox"][
        "x"
    ] = 299
    outside["table_evidence"]["source_objects"][0]["words"][1]["bbox"][
        "x"
    ] = 310
    with pytest.raises(ValidationError, match="topology or custody"):
        ParseResult.model_validate(_bound_payload(outside))


@pytest.mark.parametrize(
    "path",
    [
        ("table_evidence",),
        ("table_evidence", "grid"),
        ("table_evidence", "slots", 0),
        ("table_evidence", "source_objects", 0),
        ("table_evidence", "evidence", 0),
        ("table_evidence", "span_decisions", 0),
        ("table_evidence", "representation_custody"),
        ("cells", 0),
        ("cells", 0, "confidence_dimensions"),
    ],
)
def test_unknown_marker_and_valid_cell_fields_are_rejected(
    path: tuple[str | int, ...],
) -> None:
    table = _valid_table()
    _at(table, path)["unknown_field"] = "must-fail"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ContentItem.model_validate(table)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("table_evidence", "page_index"), "1"),
        (("table_evidence", "grid", "row_count"), True),
        (("table_evidence", "scope"), ("P04-US01",)),
        (("table_evidence", "source_objects", 0, "page_index"), 1.0),
        (("table_evidence", "evidence", 0, "confidence"), "1"),
        (("table_evidence", "evidence", 0, "bbox", "x"), "0"),
        (("table_evidence", "span_decisions", 0, "claimed_col_span"), 2.0),
        (("table_evidence", "representation_custody", "grid_shape", 0), "1"),
        (("cells", 0, "row"), "0"),
        (("cells", 0, "column_header"), 1),
        (("cells", 0, "id"), "A" * 64),
    ],
)
def test_table_schema_rejects_numeric_string_boolean_and_container_coercion(
    path: tuple[str | int, ...],
    replacement: Any,
) -> None:
    table = _valid_table()
    parent = _at(table, path[:-1])
    parent[path[-1]] = replacement

    with pytest.raises(ValidationError):
        ContentItem.model_validate(table)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("table_evidence", "evidence", 0, "confidence"), float("nan")),
        (("table_evidence", "evidence", 0, "bbox", "width"), float("inf")),
        (("cells", 0, "confidence_dimensions", "text"), float("-inf")),
    ],
)
def test_table_schema_rejects_nonfinite_numbers(
    path: tuple[str | int, ...],
    replacement: Any,
) -> None:
    table = _valid_table()
    parent = _at(table, path[:-1])
    parent[path[-1]] = replacement

    with pytest.raises(ValidationError):
        ContentItem.model_validate(table)


def test_table_schema_enforces_utf8_byte_and_control_bounds() -> None:
    oversized_cell = _valid_table()["cells"][0]
    oversized_cell["text"] = "x" * 16_385
    with pytest.raises(ValidationError, match="at most|oversized"):
        TableCell.model_validate(oversized_cell)

    table = _valid_table()
    table["table_evidence"]["source_objects"][0]["raw_ref"] = "é" * 129
    with pytest.raises(ValidationError, match="oversized"):
        ContentItem.model_validate(table)

    for unsafe_reference in ("é", "table/0", "#/../cell", "#/a\\b", "#/a//b"):
        unsafe_source = _valid_table()
        unsafe_source["table_evidence"]["source_objects"][0][
            "raw_ref"
        ] = unsafe_reference
        with pytest.raises(ValidationError, match="source reference"):
            ContentItem.model_validate(unsafe_source)

    controlled = _valid_table()
    controlled["cells"][0]["text"] = "safe\x00unsafe"
    with pytest.raises(ValidationError, match="unsafe control"):
        ContentItem.model_validate(controlled)

    invalid_unicode = _valid_table()["cells"][0]
    invalid_unicode["text"] = "\ud800"
    with pytest.raises(ValidationError, match="valid string|valid UTF-8"):
        TableCell.model_validate(invalid_unicode)

    oversized_item = _valid_table()
    oversized_item["legacy_padding"] = "x" * (8 * 1024 * 1024)
    with pytest.raises(ValidationError, match="item exceeds its byte cap"):
        ContentItem.model_validate(oversized_item)

    oversized_html = _valid_table()
    oversized_html["html"] = "x" * (8 * 1024 * 1024)
    oversized_html["md"] = oversized_html["html"]
    with pytest.raises(ValidationError, match="item exceeds its byte cap"):
        ContentItem.model_validate(oversized_html)

    oversized_rows = _valid_table()
    oversized_rows["rows"] = [["x" * (8 * 1024 * 1024), ""]]
    oversized_rows["value"] = deepcopy(oversized_rows["rows"])
    with pytest.raises(ValidationError, match="item exceeds its byte cap"):
        ContentItem.model_validate(oversized_rows)


def test_marked_table_preflight_rejects_huge_integers_before_coercion() -> None:
    huge_integer = 1 << 100_000

    huge_sidecar = _valid_table()["table_evidence"]
    huge_sidecar["page_index"] = huge_integer
    with pytest.raises(ValidationError, match="integer exceeds its bit cap"):
        TableEvidence.model_validate(huge_sidecar)

    huge_cell = _valid_table()
    huge_cell["cells"][0]["row"] = huge_integer
    with pytest.raises(ValidationError, match="integer exceeds its bit cap"):
        ContentItem.model_validate(huge_cell)

    huge_page = _bound_payload(
        _production_table(),
        source_sha256=_hash("a"),
    )
    huge_page["pages"][0]["page_width"] = huge_integer
    with pytest.raises(ValidationError, match="geometry differs"):
        ParseResult.model_validate(huge_page)


def test_nonvalid_diagnostic_retains_predecessor_legacy_cells() -> None:
    table = _valid_table()
    sidecar = table["table_evidence"]
    sidecar["status"] = "unresolved"
    sidecar["grid"]["cell_ids"] = []
    sidecar["slots"] = []
    sidecar["span_decisions"] = []
    sidecar["concerns"] = ["table_source_span_evidence_unresolved"]
    legacy_cells = [
        {
            "row": 0,
            "column": 0,
            "row_span": 1,
            "col_span": 2,
            "text": "legacy predecessor",
            "column_header": False,
            "row_header": False,
            "row_section": False,
            "bbox": None,
            "source": "native",
            "legacy_additive_field": {"retained": True},
        }
    ]
    table["cells"] = legacy_cells

    public = ContentItem.model_validate(table).model_dump(mode="json")

    assert public["cells"] == legacy_cells
    assert public["table_evidence"]["status"] == "unresolved"
    assert public["table_evidence"]["grid"]["cell_ids"] == []

    malformed_cases = (
        (("cells",), None),
        (("row_count",), True),
        (("rows",), [["wrong width"]]),
        (("value",), [["different", "projection"]]),
        (("html",), 1),
    )
    for path, replacement in malformed_cases:
        malformed = deepcopy(table)
        parent = _at(malformed, path[:-1])
        parent[path[-1]] = replacement
        with pytest.raises(ValidationError, match="predecessor projection"):
            ContentItem.model_validate(malformed)

    divergent_predecessor = deepcopy(table)
    divergent_predecessor["row_count"] = 2
    divergent_predecessor["column_count"] = 2
    divergent_predecessor["rows"] = [["legacy", ""], ["recovered", "row"]]
    divergent_predecessor["value"] = deepcopy(divergent_predecessor["rows"])
    divergent_predecessor["table_evidence"]["representation_custody"][
        "grid_shape"
    ] = [2, 2]
    divergent = ContentItem.model_validate(divergent_predecessor)
    assert divergent.table_evidence is not None
    assert divergent.table_evidence.grid.row_count == 1
    assert divergent.table_evidence.representation_custody.grid_shape == [2, 2]


def test_parse_result_accepts_custodied_nonvalid_diagnostic_and_rejects_tamper(
) -> None:
    table = _production_diagnostic()
    sidecar = table["table_evidence"]
    assert sidecar["status"] == "structural_failure"
    assert sidecar["grid"]["cell_ids"] == []
    assert sidecar["slots"] == []
    assert sidecar["span_decisions"] == []

    validated = ParseResult.model_validate(
        _bound_payload(table, source_sha256=_hash("a"))
    )
    assert validated.pages[0].items[0].table_evidence is not None
    assert (
        validated.pages[0].items[0].table_evidence.status
        == "structural_failure"
    )

    tampered = deepcopy(table)
    tampered["rows"][0][0] = "diagnostic predecessor tamper"
    with pytest.raises(
        ValidationError,
        match="predecessor projection|topology or custody",
    ):
        ParseResult.model_validate(
            _bound_payload(tampered, source_sha256=_hash("a"))
        )


def test_nonvalid_marker_cannot_relabel_authoritative_arrays() -> None:
    table = _valid_table()
    table["table_evidence"]["status"] = "unresolved"
    table["table_evidence"]["concerns"] = [
        "table_source_span_evidence_unresolved"
    ]

    with pytest.raises(ValidationError, match="carries authority"):
        ContentItem.model_validate(table)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda table: table.__setitem__("table_evidence", None),
        lambda table: table.__setitem__("type", "chart"),
        lambda table: table.pop("cells"),
    ],
)
def test_partial_or_misbound_table_markers_are_rejected(mutation: Any) -> None:
    table = _valid_table()
    mutation(table)

    with pytest.raises(ValidationError):
        ContentItem.model_validate(table)


def test_default_off_legacy_table_payload_is_unchanged() -> None:
    legacy = {
        "id": "legacy-table",
        "type": "table",
        "reading_order": 0,
        "rows": [["A"]],
        "cells": [{"text": "A", "legacy": True}],
        "html": "<table><tr><td>A</td></tr></table>",
    }

    public = ContentItem.model_validate(legacy).model_dump(mode="json")
    sparse = ContentItem.model_validate(legacy).model_dump(
        mode="json",
        exclude_none=True,
    )

    assert public["rows"] == legacy["rows"]
    assert public["cells"] == legacy["cells"]
    assert public["html"] == legacy["html"]
    assert "table_evidence" not in public
    assert sparse == legacy
    assert list(sparse) == list(legacy)


def test_private_predecessor_snapshot_cannot_reach_parse_result() -> None:
    table = _valid_table()
    table["_p04_predecessor_snapshot"] = {"cells": [{"text": "private"}]}

    internal = ContentItem.model_validate(table).model_dump(mode="json")
    assert internal["_p04_predecessor_snapshot"] == table[
        "_p04_predecessor_snapshot"
    ]

    with pytest.raises(ValidationError, match="private P04 predecessor snapshot"):
        ParseResult.model_validate(_parse_payload(table))

    payload_with_models = _parse_payload(_valid_table())
    page_payload = payload_with_models["pages"][0]
    page_payload["items"] = [ContentItem.model_validate(table)]
    payload_with_models["pages"] = [PageResult.model_validate(page_payload)]
    with pytest.raises(ValidationError, match="private P04 predecessor snapshot"):
        ParseResult.model_validate(payload_with_models)


def test_direct_table_models_reject_mapping_subclasses() -> None:
    class MappingSubclass(dict[str, Any]):
        called = False

        def items(self):  # type: ignore[override]
            self.called = True
            raise AssertionError("hostile callback executed")

    evidence = MappingSubclass(_valid_table()["table_evidence"])
    with pytest.raises(ValidationError, match="exact object"):
        TableEvidence.model_validate(evidence)
    assert evidence.called is False

    decision = MappingSubclass(
        _valid_table()["table_evidence"]["span_decisions"][0]
    )
    with pytest.raises(ValidationError, match="exact object"):
        TableSpanDecision.model_validate(decision)
    assert decision.called is False

    for raw_source in (
        _valid_table()["table_evidence"]["source_objects"][0],
        _pdfplumber_source(),
    ):
        source = MappingSubclass(raw_source)
        sidecar = _valid_table()["table_evidence"]
        sidecar["source_objects"] = [source]
        with pytest.raises(ValidationError, match="exact object"):
            TableEvidence.model_validate(sidecar)
        assert source.called is False
