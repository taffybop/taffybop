"""Focused P04-US01 contracts for opaque raw-group custody.

These controls deliberately distinguish literal Docling assertions from the
normalized semantic edges they support.  The sidecar is diagnostic-only: it
must retain every supported literal assertion without making an opaque group
or raw-only member authoritative in the public canonical presentation.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import (
    CanonicalSourceCustody,
    ParseResult,
    _canonical_presentation_sha256,
)
from app.services import opaque_group_custody as custody
from app.services.ir import DocumentIR, build_document_ir, round_trip_document
from app.services.presentation import build_canonical_presentation


SOURCE_SHA256 = "a" * 64
CUSTODY_RECORD_KEYS = {
    "record_id",
    "record_order",
    "page_index",
    "edge_kind",
    "owner_order",
    "owner_element_id",
    "owner_raw_ref",
    "raw_slot_index",
    "raw_target_slot_index",
    "raw_assertion_sha256",
    "member_element_id",
    "member_raw_ref",
    "member_type",
    "member_content_basis",
    "member_content_sha256",
    "group_element_id",
    "group_raw_ref",
    "group_type",
    "counterpart_element_id",
    "counterpart_raw_ref",
    "counterpart_type",
    "counterpart_content_basis",
    "counterpart_content_sha256",
    "relationship_id",
    "relationship_type",
    "relationship_field",
    "normalized_relationship_field",
    "normalization_outcome",
    "normalized_relationship_sha256",
    "normalized_assertion_count",
    "normalized_evidence_count",
    "source_element_id",
    "source_raw_ref",
    "source_type",
    "source_content_basis",
    "source_content_sha256",
    "target_element_id",
    "target_raw_ref",
    "target_type",
    "target_content_basis",
    "target_content_sha256",
}


def _prov(page_index: int = 1, *, top: float = 10.0) -> list[dict[str, Any]]:
    return [
        {
            "page_no": page_index,
            "bbox": {
                "l": 10.0,
                "t": top,
                "r": 90.0,
                "b": top + 12.0,
                "coord_origin": "TOPLEFT",
            },
        }
    ]


def _marker(reading_order: int) -> dict[str, Any]:
    # A literal marker is sufficient for direct custody/canonical helpers.  API
    # boundary tests below replace this with the production-sealed table fixture.
    return {
        "id": "public-table",
        "type": "table",
        "reading_order": reading_order,
        "value": [["T"]],
        "rows": [["T"]],
        "md": "<table><tr><td>T</td></tr></table>",
        "html": "<table><tr><td>T</td></tr></table>",
        "table_evidence": {},
    }


def _document(
    *,
    public_items: list[dict[str, Any]] | None = None,
    marked: bool = True,
    page_count: int = 1,
) -> dict[str, Any]:
    first_items = deepcopy(public_items or [])
    if marked:
        first_items.append(_marker(len(first_items)))
    pages: list[dict[str, Any]] = []
    for page_index in range(1, page_count + 1):
        pages.append(
            {
                "page_index": page_index,
                "page_number": page_index,
                "page_label": str(page_index),
                "page_width": 300.0,
                "page_height": 200.0,
                "unit": "pt",
                "success": True,
                "items": first_items if page_index == 1 else [],
                "warnings": [],
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "opaque-groups.pdf",
            "mime_type": "application/pdf",
            "sha256": SOURCE_SHA256,
            "page_count": page_count,
        },
        "pages": pages,
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _public_text() -> dict[str, Any]:
    return {
        "id": "public-text",
        "type": "text",
        "reading_order": 0,
        "value": "Public alpha",
        "md": "Public alpha",
        "source": "native",
    }


def _public_texts() -> list[dict[str, Any]]:
    return [
        _public_text(),
        {
            "id": "public-text-2",
            "type": "text",
            "reading_order": 1,
            "value": "Public beta",
            "md": "Public beta",
            "source": "native",
        },
        {
            "id": "public-text-3",
            "type": "text",
            "reading_order": 2,
            "value": "Parent member",
            "md": "Parent member",
            "source": "native",
        },
    ]


def _base_raw_graph(*, reciprocal_parent: bool = True) -> dict[str, Any]:
    parent_member: dict[str, Any] = {
        "self_ref": "#/texts/2",
        "label": "text",
        "text": "Parent member",
        "prov": _prov(top=50.0),
    }
    if reciprocal_parent:
        parent_member["parent"] = {"$ref": "#/groups/0"}
    return {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(top=10.0),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Public beta",
                "prov": _prov(top=30.0),
            },
            parent_member,
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [
                    {"$ref": "#/groups/1"},
                    {"$ref": "#/texts/0"},
                    {"$ref": "#/texts/2"},
                ],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [{"$ref": "#/texts/1"}],
            },
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/groups/0"},
                {"$ref": "#/texts/0"},
            ],
        },
        "furniture": {
            "self_ref": "#/furniture",
            "children": [
                {"$ref": "#/groups/1"},
                {"$ref": "#/texts/1"},
            ],
        },
    }


def _duplicate_assertion_raw_graph() -> dict[str, Any]:
    return {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(top=10.0),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Public beta",
                "prov": _prov(top=30.0),
                "parent": {"$ref": "#/groups/0"},
            },
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [
                    {"$ref": "#/texts/0"},
                    {"$ref": "#/texts/0"},
                    {"$ref": "#/texts/1"},
                ],
            }
        ],
    }


def _fixture(
    *,
    raw_graph: dict[str, Any] | None = None,
    public_items: list[dict[str, Any]] | None = None,
    marked: bool = True,
    page_count: int = 1,
) -> tuple[dict[str, Any], dict[str, Any], DocumentIR]:
    document = _document(
        public_items=public_items if public_items is not None else _public_texts(),
        marked=marked,
        page_count=page_count,
    )
    raw = deepcopy(raw_graph if raw_graph is not None else _base_raw_graph())
    ir = build_document_ir(
        document,
        raw_graph=raw,
        native_texts=tuple(
            "Public alpha Public beta Parent member" if page_index == 0 else ""
            for page_index in range(page_count)
        ),
    )
    return document, raw, ir


def _by_raw_ref(ir: DocumentIR) -> dict[str, Any]:
    return {
        raw_ref: element
        for element in ir.elements
        for raw_ref in element.properties.get("raw_refs", [])
    }


def _projection_inputs(
    document: dict[str, Any],
    raw_graph: dict[str, Any],
    ir: DocumentIR,
) -> tuple[DocumentIR, DocumentIR, Any]:
    detached_ir, detached = custody.detach_opaque_group_edges(ir, raw_graph)
    custody_ir = custody.restore_diagnostic_group_edges(detached_ir, detached)
    authoritative_ir = build_document_ir(document)
    return authoritative_ir, custody_ir, detached


def _detach_restore_project(
    document: dict[str, Any],
    raw_graph: dict[str, Any],
    ir: DocumentIR,
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw_graph,
        ir,
    )
    sealed, relationship_ids = custody.seal_diagnostic_custody(
        document,
        custody_ir,
        raw_graph=raw_graph,
        detached_custody=detached,
    )
    presentation_ir = custody_ir.model_copy(deep=True)
    expected_ids = set(relationship_ids)
    seen_ids: set[str] = set()
    for relationship in presentation_ir.relationships:
        if relationship.id in expected_ids:
            relationship.metadata["canonical_presentation_inert"] = True
            seen_ids.add(relationship.id)
    assert seen_ids == expected_ids
    canonical = build_canonical_presentation(presentation_ir).model_dump(
        mode="json",
        exclude_none=True,
    )
    sidecar = sealed.model_dump(mode="json")
    return canonical, sidecar, detached


def _record(
    sidecar: dict[str, Any],
    *,
    owner_ref: str,
    field: str,
    slot: int,
) -> dict[str, Any]:
    matches = [
        value
        for value in sidecar["records"]
        if value["owner_raw_ref"] == owner_ref
        and value["relationship_field"] == field
        and value["raw_slot_index"] == slot
    ]
    assert len(matches) == 1
    return matches[0]


def _reseal_sidecar(sidecar: dict[str, Any]) -> None:
    source_sha256 = sidecar["source_sha256"]
    for record_order, record in enumerate(sidecar["records"]):
        record["record_order"] = record_order
        record.pop("record_id", None)
        record["record_id"] = custody.record_id(record, source_sha256)
    sidecar["record_count"] = len(sidecar["records"])
    sidecar["records_sha256"] = custody.records_sha256(sidecar["records"])


def _production_payload_with_custody() -> dict[str, Any]:
    # Reuse the production-sealed table, not the deliberately skeletal direct
    # helper marker above, so this payload exercises the complete API validator.
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Authoritative prose",
                "prov": _prov(top=10.0),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            }
        ],
    }
    ir = build_document_ir(
        payload,
        raw_graph=raw,
        native_texts=("Authoritative prose",),
    )
    canonical, sidecar, _detached = _detach_restore_project(payload, raw, ir)
    sidecar["canonical_presentation_sha256"] = (
        _canonical_presentation_sha256(canonical)
    )
    payload["canonical_presentation"] = canonical
    payload["canonical_source_custody"] = sidecar
    return payload


def _bind_production_custody(
    payload: dict[str, Any],
    raw_graph: dict[str, Any],
    *,
    native_texts: tuple[str, ...],
) -> dict[str, Any]:
    bound = deepcopy(payload)
    bound.pop("canonical_presentation", None)
    bound.pop("canonical_source_custody", None)
    ir = build_document_ir(
        bound,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )
    canonical, sidecar, _detached = _detach_restore_project(
        bound,
        raw_graph,
        ir,
    )
    sidecar["canonical_presentation_sha256"] = (
        _canonical_presentation_sha256(canonical)
    )
    bound["canonical_presentation"] = canonical
    bound["canonical_source_custody"] = sidecar
    return bound


def _append_empty_page(payload: dict[str, Any]) -> None:
    payload["document"]["page_count"] = 2
    payload["pages"].append(
        {
            "page_index": 2,
            "page_number": 2,
            "page_label": "2",
            "page_width": 300,
            "page_height": 120,
            "unit": "pt",
            "success": True,
            "items": [],
            "warnings": [],
        }
    )


_NESTED_REFERENCE_PATHS = (
    ("graph", "graph.cells[0].item_ref"),
    ("data", "data.table_cells[0].ref"),
    (
        "annotations",
        "annotations[0].chart_data.table_cells[0].ref",
    ),
    (
        "meta",
        "meta.tabular_chart.chart_data.table_cells[0].ref",
    ),
)


def _nested_reference_fixture(
    path_kind: str,
    raw_reference: Any,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    DocumentIR,
    dict[str, Any],
]:
    document = _document(public_items=[], marked=True)
    document["pages"][0]["items"][0]["bbox"] = {
        "x": 10.0,
        "y": 10.0,
        "width": 80.0,
        "height": 12.0,
        "unit": "pt",
    }
    cell = {
        "text": "T",
        "start_row_offset_idx": 0,
        "end_row_offset_idx": 1,
        "start_col_offset_idx": 0,
        "end_col_offset_idx": 1,
    }
    raw_table: dict[str, Any] = {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": _prov(),
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [deepcopy(cell)],
        },
    }
    if path_kind == "graph":
        raw_table["graph"] = {
            "cells": [{"item_ref": deepcopy(raw_reference)}]
        }
        reference_metadata = {
            "cell_index": 0,
            "cell_id": None,
            "cell_label": None,
        }
    elif path_kind == "data":
        raw_table["data"]["table_cells"][0]["ref"] = deepcopy(raw_reference)
        reference_metadata = {
            "cell_index": 0,
            "start_row_offset_idx": 0,
            "end_row_offset_idx": 1,
            "start_col_offset_idx": 0,
            "end_col_offset_idx": 1,
        }
    elif path_kind == "annotations":
        raw_table["annotations"] = [
            {
                "kind": "chart",
                "chart_data": {
                    "table_cells": [
                        {**deepcopy(cell), "ref": deepcopy(raw_reference)}
                    ]
                },
            }
        ]
        reference_metadata = {
            "cell_index": 0,
            "start_row_offset_idx": 0,
            "end_row_offset_idx": 1,
            "start_col_offset_idx": 0,
            "end_col_offset_idx": 1,
        }
    elif path_kind == "meta":
        raw_table["meta"] = {
            "tabular_chart": {
                "chart_data": {
                    "table_cells": [
                        {**deepcopy(cell), "ref": deepcopy(raw_reference)}
                    ]
                }
            }
        }
        reference_metadata = {
            "cell_index": 0,
            "start_row_offset_idx": 0,
            "end_row_offset_idx": 1,
            "start_col_offset_idx": 0,
            "end_col_offset_idx": 1,
        }
    else:  # pragma: no cover - the closed parametrization owns this helper.
        raise AssertionError(f"unknown nested reference path: {path_kind}")
    raw = {
        "tables": [raw_table],
        "groups": [
            {
                "self_ref": f"#/groups/{index}",
                "label": "group",
                "children": [],
            }
            for index in range(2)
        ],
    }
    ir = build_document_ir(
        document,
        raw_graph=raw,
        native_texts=("T",),
    )
    return document, raw, ir, reference_metadata


def test_literal_marker_requires_zero_record_custody_sidecar() -> None:
    document, raw, ir = _fixture(raw_graph={})
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert set(sidecar) == {
        "policy_id",
        "schema_version",
        "authority",
        "source_sha256",
        "canonical_presentation_sha256",
        "record_count",
        "records_sha256",
        "records",
    }
    assert sidecar == {
        "policy_id": custody.POLICY_ID,
        "schema_version": custody.SCHEMA_VERSION,
        "authority": "diagnostic_only",
        "source_sha256": SOURCE_SHA256,
        "canonical_presentation_sha256": None,
        "record_count": 0,
        "records_sha256": custody.records_sha256([]),
        "records": [],
    }
    assert canonical["schema_version"] == "1.0"
    assert canonical["policy_id"] == "canonical-presentation-v1"
    assert len(canonical["pages"]) == 1

    committed = deepcopy(document)
    before = deepcopy(committed)
    _authoritative_ir, custody_ir, _ = _projection_inputs(document, raw, ir)
    sealed, relationship_ids = custody.seal_diagnostic_custody(
        committed,
        custody_ir,
        raw_graph=raw,
        detached_custody=detached,
    )
    assert sealed.model_dump(mode="json") == sidecar
    assert relationship_ids == ()
    assert committed == before
    assert not hasattr(custody, "build_canonical_projection")
    assert not hasattr(custody, "apply_canonical_projection")


def test_diagnostic_custody_has_no_output_authority_and_mutates_no_input() -> None:
    source = Path(custody.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "app.services.presentation",
        "build_canonical_presentation",
        "canonical_presentation",
        "build_canonical_projection",
        "apply_canonical_projection",
    ):
        assert forbidden not in source

    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    before_document = deepcopy(document)
    before_raw = deepcopy(raw)
    before_ir = custody_ir.model_dump(mode="json")
    before_detached = detached

    sealed, relationship_ids = custody.seal_diagnostic_custody(
        document,
        custody_ir,
        raw_graph=raw,
        detached_custody=detached,
    )
    sidecar = sealed.model_dump(mode="json")

    assert document == before_document
    assert raw == before_raw
    assert custody_ir.model_dump(mode="json") == before_ir
    assert detached == before_detached
    assert tuple(sorted(relationship_ids)) == relationship_ids
    assert set(relationship_ids) == {
        record["relationship_id"] for record in sidecar["records"]
    }
    assert set(sidecar) == {
        "policy_id",
        "schema_version",
        "authority",
        "source_sha256",
        "canonical_presentation_sha256",
        "record_count",
        "records_sha256",
        "records",
    }


@pytest.mark.parametrize(
    "mode",
    ("missing", "extra", "duplicate", "drop_records_and_id"),
)
def test_diagnostic_seal_rejects_every_record_relationship_id_divergence(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    original = custody._project_records

    def divergent(*args: Any, **kwargs: Any) -> Any:
        records, relationship_ids = original(*args, **kwargs)
        records = deepcopy(records)
        relationship_ids = set(relationship_ids)
        if mode == "missing":
            return records, set()
        if mode == "extra":
            return records, relationship_ids | {"rel-not-in-frozen-closure"}
        if mode == "duplicate":
            one = next(iter(relationship_ids))
            return records, (*sorted(relationship_ids), one)
        removed_id = next(
            relationship_id
            for relationship_id in relationship_ids
            if sum(
                record["relationship_id"] == relationship_id
                for record in records
            )
            == 1
        )
        records = [
            record
            for record in records
            if record["relationship_id"] != removed_id
        ]
        for record_order, record in enumerate(records):
            record["record_order"] = record_order
            record.pop("record_id", None)
            record["record_id"] = custody.record_id(record, SOURCE_SHA256)
        relationship_ids.remove(removed_id)
        return records, relationship_ids

    monkeypatch.setattr(custody, "_project_records", divergent)
    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.seal_diagnostic_custody(
            document,
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
        )


def test_marker_callback_cannot_mutate_relevant_raw_before_source_binding() -> None:
    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )

    class MutatingDocument(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            if key == "pages":
                raw["groups"][0]["children"][0] = {"$ref": "#/texts/999"}
            return super().get(key, default)

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
    ):
        custody.seal_diagnostic_custody(
            MutatingDocument(deepcopy(document)),
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
        )


@pytest.mark.parametrize("mutation", ("raw", "ir"))
def test_model_validation_callback_cannot_mutate_final_source_closure(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    original = CanonicalSourceCustody.model_validate

    def mutate_then_validate(value: Any, *args: Any, **kwargs: Any) -> Any:
        if mutation == "raw":
            raw["groups"][0]["children"][0] = {"$ref": "#/texts/999"}
        else:
            relationship = next(
                member
                for member in custody_ir.relationships
                if custody._opaque_group_descriptor(
                    member,
                    {element.id: element for element in custody_ir.elements},
                )
                is not None
            )
            relationship.metadata["field"] = "changed_after_validation"
        return original(value, *args, **kwargs)

    monkeypatch.setattr(
        CanonicalSourceCustody,
        "model_validate",
        staticmethod(mutate_then_validate),
    )
    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.seal_diagnostic_custody(
            document,
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
        )


def test_supported_literal_assertions_preserve_exact_direction_and_basis() -> None:
    document, raw, ir = _fixture()
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)
    by_ref = _by_raw_ref(ir)

    # Four children assertions, a reciprocal parent assertion, and the two
    # root reading-order assertions are independently retained.
    assert sidecar["record_count"] == 7
    assert [record["record_order"] for record in sidecar["records"]] == list(
        range(7)
    )
    assert len({record["record_id"] for record in sidecar["records"]}) == 7
    assert all(
        set(record) == CUSTODY_RECORD_KEYS for record in sidecar["records"]
    )

    group_to_group = _record(
        sidecar,
        owner_ref="#/groups/0",
        field="children",
        slot=0,
    )
    assert group_to_group["edge_kind"] == "group_membership"
    assert group_to_group["member_raw_ref"] == "#/groups/1"
    assert group_to_group["member_type"] == "group"
    assert group_to_group["member_content_basis"] == "opaque_group_empty"
    assert group_to_group["member_content_sha256"] == (
        custody.empty_group_content_sha256("group")
    )
    assert group_to_group["counterpart_type"] == "group"
    assert group_to_group["counterpart_content_basis"] == "opaque_group_empty"

    public_member = _record(
        sidecar,
        owner_ref="#/groups/0",
        field="children",
        slot=1,
    )
    assert public_member["member_raw_ref"] == "#/texts/0"
    assert public_member["member_type"] == "text"
    assert public_member["member_content_basis"] == "public_ir"
    assert public_member["member_content_sha256"] == custody.member_content_sha256(
        by_ref["#/texts/0"]
    )

    second_public = _record(
        sidecar,
        owner_ref="#/groups/1",
        field="children",
        slot=0,
    )
    assert second_public["member_raw_ref"] == "#/texts/1"
    assert second_public["member_type"] == "text"
    assert second_public["member_content_basis"] == "public_ir"
    assert second_public["member_content_sha256"] == (
        custody.member_content_sha256(by_ref["#/texts/1"])
    )
    assert second_public["counterpart_content_basis"] == "public_ir"
    assert second_public["counterpart_content_sha256"] == (
        second_public["member_content_sha256"]
    )
    assert {
        record["member_content_basis"] for record in sidecar["records"]
    } <= {"public_ir", "opaque_group_empty"}
    assert {
        record["counterpart_content_basis"] for record in sidecar["records"]
    } <= {"public_ir", "opaque_group_empty"}
    for record in sidecar["records"]:
        assert record["source_content_basis"] in {
            "public_ir",
            "opaque_group_empty",
        }
        assert record["target_content_basis"] in {
            "public_ir",
            "opaque_group_empty",
        }
        endpoint_by_ref = {
            record["source_raw_ref"]: (
                record["source_element_id"],
                record["source_type"],
                record["source_content_basis"],
                record["source_content_sha256"],
            ),
            record["target_raw_ref"]: (
                record["target_element_id"],
                record["target_type"],
                record["target_content_basis"],
                record["target_content_sha256"],
            ),
        }
        assert endpoint_by_ref[record["member_raw_ref"]] == (
            record["member_element_id"],
            record["member_type"],
            record["member_content_basis"],
            record["member_content_sha256"],
        )
        assert endpoint_by_ref[record["counterpart_raw_ref"]] == (
            record["counterpart_element_id"],
            record["counterpart_type"],
            record["counterpart_content_basis"],
            record["counterpart_content_sha256"],
        )
        assert len(record["raw_assertion_sha256"]) == 64
        assert len(record["normalized_relationship_sha256"]) == 64
        assert record["normalized_evidence_count"] >= 0

    child_assertion = _record(
        sidecar,
        owner_ref="#/groups/0",
        field="children",
        slot=2,
    )
    inverse_parent = _record(
        sidecar,
        owner_ref="#/texts/2",
        field="parent",
        slot=0,
    )
    assert child_assertion["normalization_outcome"] == "normalized_edge"
    assert inverse_parent["normalization_outcome"] == "merged_edge"
    assert inverse_parent["normalized_relationship_field"] == "children"
    assert inverse_parent["relationship_type"] == "contains"
    assert inverse_parent["source_element_id"] == by_ref["#/groups/0"].id
    assert inverse_parent["target_element_id"] == by_ref["#/texts/2"].id
    assert inverse_parent["owner_element_id"] == by_ref["#/texts/2"].id
    assert inverse_parent["member_element_id"] == by_ref["#/groups/0"].id
    assert inverse_parent["relationship_id"] == child_assertion["relationship_id"]
    assert inverse_parent["raw_assertion_sha256"] != (
        child_assertion["raw_assertion_sha256"]
    )
    assert inverse_parent["normalized_relationship_sha256"] == (
        child_assertion["normalized_relationship_sha256"]
    )
    assert inverse_parent["normalized_evidence_count"] == (
        child_assertion["normalized_evidence_count"]
    )

    for root_ref, field, target_ref in (
        ("#/body", "body.children.reading_order", "#/texts/0"),
        ("#/furniture", "furniture.children.reading_order", "#/texts/1"),
    ):
        root = _record(sidecar, owner_ref=root_ref, field=field, slot=0)
        assert root["edge_kind"] == "root_reading_order"
        assert root["normalization_outcome"] == "root_reading_order"
        assert root["owner_element_id"] is None
        assert root["raw_target_slot_index"] == 1
        assert root["member_raw_ref"] == target_ref
        assert root["member_element_id"] == root["target_element_id"]

    assert all(
        record["owner_element_id"] != record["member_element_id"]
        for record in sidecar["records"]
        if record["edge_kind"] != "root_reading_order"
    )


def test_legitimate_group_parent_body_is_not_projected_as_member_assertion() -> None:
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "parent": {"$ref": "#/body"},
                "children": [{"$ref": "#/texts/0"}],
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/groups/0"},
                {"$ref": "#/texts/0"},
            ],
        },
    }
    document, raw, ir = _fixture(raw_graph=raw)
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)

    assert sidecar["record_count"] == 2
    assert {
        (record["owner_raw_ref"], record["relationship_field"])
        for record in sidecar["records"]
    } == {
        ("#/groups/0", "children"),
        ("#/body", "body.children.reading_order"),
    }
    assert not any(
        record["owner_raw_ref"] == "#/groups/0"
        and record["relationship_field"] == "parent"
        for record in sidecar["records"]
    )


def test_duplicate_slots_and_reciprocal_parent_remain_distinct_assertions() -> None:
    raw = _duplicate_assertion_raw_graph()
    document, raw, ir = _fixture(raw_graph=raw)
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)

    duplicate_slots = [
        record
        for record in sidecar["records"]
        if record["owner_raw_ref"] == "#/groups/0"
        and record["relationship_field"] == "children"
        and record["member_raw_ref"] == "#/texts/0"
    ]
    assert [record["raw_slot_index"] for record in duplicate_slots] == [0, 1]
    assert len({record["record_id"] for record in duplicate_slots}) == 2
    assert len({record["relationship_id"] for record in duplicate_slots}) == 1
    assert len(
        {record["raw_assertion_sha256"] for record in duplicate_slots}
    ) == 2
    assert len(
        {record["normalized_relationship_sha256"] for record in duplicate_slots}
    ) == 1
    assert len(
        {record["normalized_evidence_count"] for record in duplicate_slots}
    ) == 1
    assert [record["normalization_outcome"] for record in duplicate_slots] == [
        "normalized_edge",
        "merged_edge",
    ]

    children = _record(
        sidecar,
        owner_ref="#/groups/0",
        field="children",
        slot=2,
    )
    parent = _record(
        sidecar,
        owner_ref="#/texts/1",
        field="parent",
        slot=0,
    )
    assert children["record_id"] != parent["record_id"]
    assert children["relationship_id"] == parent["relationship_id"]
    assert children["raw_assertion_sha256"] != parent["raw_assertion_sha256"]
    assert children["normalized_relationship_sha256"] == (
        parent["normalized_relationship_sha256"]
    )
    assert parent["normalized_relationship_field"] == "children"
    assert parent["normalization_outcome"] == "merged_edge"


@pytest.mark.parametrize(
    "mutation",
    [
        "sole_record_claims_merged",
        "normalized_field_differs_from_literal",
        "group_claims_two_normalized_edges",
    ],
)
def test_resealed_false_normalization_claims_are_rejected(mutation: str) -> None:
    raw = (
        _duplicate_assertion_raw_graph()
        if mutation == "group_claims_two_normalized_edges"
        else _base_raw_graph()
    )
    document, raw, ir = _fixture(raw_graph=raw)
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)
    CanonicalSourceCustody.model_validate(sidecar)
    forged = deepcopy(sidecar)

    if mutation == "group_claims_two_normalized_edges":
        duplicated = [
            record
            for record in forged["records"]
            if record["owner_raw_ref"] == "#/groups/0"
            and record["relationship_field"] == "children"
            and record["member_raw_ref"] == "#/texts/0"
        ]
        assert len(duplicated) == 2
        merged = next(
            record
            for record in duplicated
            if record["normalization_outcome"] == "merged_edge"
        )
        merged["normalization_outcome"] = "normalized_edge"
    else:
        sole = next(
            record
            for record in forged["records"]
            if record["owner_raw_ref"] == "#/groups/0"
            and record["relationship_field"] == "children"
            and record["member_raw_ref"] == "#/groups/1"
        )
        if mutation == "sole_record_claims_merged":
            sole["normalization_outcome"] = "merged_edge"
        else:
            sole["normalized_relationship_field"] = "parent"
            sole["relationship_id"] = custody.stable_id(
                "rel",
                sole["relationship_type"],
                sole["source_element_id"],
                sole["target_element_id"],
                sole["normalized_relationship_field"],
            )
    _reseal_sidecar(forged)

    with pytest.raises(ValidationError):
        CanonicalSourceCustody.model_validate(forged)


def test_public_primary_list_authority_survives_while_raw_edge_is_inert() -> None:
    public_list = {
        "id": "public-list",
        "type": "list",
        "reading_order": 0,
        "value": ["Visible public list"],
        "md": "- Visible public list",
        "source": "native",
    }
    public_detail = {
        "id": "public-list-detail",
        "type": "text",
        "reading_order": 1,
        "value": "Visible public list detail",
        "md": "Visible public list detail",
        "source": "native",
    }
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Visible public list detail",
                "prov": _prov(top=30.0),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "list",
                "children": [{"$ref": "#/texts/0"}],
            }
        ],
    }
    document, raw, ir = _fixture(
        raw_graph=raw,
        public_items=[public_list, public_detail],
    )
    canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)
    by_ref = _by_raw_ref(ir)
    public_group = by_ref["#/groups/0"]
    assert public_group.presentation_role == "primary"

    record = sidecar["records"][0]
    assert record["group_type"] == "list"
    assert record["group_element_id"] == public_group.id
    blocks = [block for page in canonical["pages"] for block in page["blocks"]]
    public_block = next(
        block for block in blocks if block["primary_element_id"] == public_group.id
    )
    assert "Visible public list" in public_block["markdown"]
    assert record["relationship_id"] not in public_block["relationship_ids"]

    canonical_json = json.dumps(canonical, sort_keys=True)
    sidecar_json = json.dumps(sidecar, sort_keys=True)
    assert "Visible public list detail" in canonical_json
    assert "Visible public list detail" not in sidecar_json
    assert "canonical_presentation" not in document
    assert "canonical_source_custody" not in document


def test_public_group_owner_is_a_component_page_and_content_anchor() -> None:
    public_list = {
        "id": "public-list",
        "type": "list",
        "reading_order": 0,
        "value": ["Visible public list"],
        "md": "- Visible public list",
        "source": "native",
    }
    raw = {
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "list",
                "children": [{"$ref": "#/groups/1"}],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [],
            },
        ]
    }
    document, raw, ir = _fixture(
        raw_graph=raw,
        public_items=[public_list],
    )
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)
    record = _record(
        sidecar,
        owner_ref="#/groups/0",
        field="children",
        slot=0,
    )

    assert record["page_index"] == 1
    assert record["source_raw_ref"] == "#/groups/0"
    assert record["source_content_basis"] == "public_ir"
    assert record["source_type"] == "list"
    assert record["target_raw_ref"] == "#/groups/1"
    assert record["target_content_basis"] == "opaque_group_empty"
    assert record["member_raw_ref"] == record["counterpart_raw_ref"] == (
        "#/groups/1"
    )


def test_group_component_page_is_derived_not_resealable() -> None:
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    _append_empty_page(payload)
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Authoritative prose",
                "prov": _prov(1),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [
                    {"$ref": "#/groups/1"},
                    {"$ref": "#/texts/0"},
                ],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [],
            },
        ],
    }
    bound = _bind_production_custody(
        payload,
        raw,
        native_texts=("Authoritative prose", ""),
    )
    ParseResult.model_validate(bound)
    forged = deepcopy(bound)
    sidecar = forged["canonical_source_custody"]
    group_to_group = next(
        record
        for record in sidecar["records"]
        if record["source_raw_ref"] == "#/groups/0"
        and record["target_raw_ref"] == "#/groups/1"
    )
    group_to_group["page_index"] = 2
    _reseal_sidecar(sidecar)

    with pytest.raises(ValidationError, match="page|binding"):
        ParseResult.model_validate(forged)


def test_unanchored_group_only_component_fails_closed() -> None:
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    raw = {
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/groups/1"}],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [],
            },
        ]
    }

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="component page anchor",
    ):
        _bind_production_custody(
            payload,
            raw,
            native_texts=("Authoritative prose",),
        )


def test_group_component_cannot_span_two_public_pages() -> None:
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    _append_empty_page(payload)
    payload["pages"][1]["items"] = [
        {
            "id": "p2-text",
            "type": "text",
            "reading_order": 0,
            "value": "Page two",
            "md": "Page two",
            "source": "native",
        }
    ]
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Authoritative prose",
                "prov": _prov(1),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Page two",
                "prov": _prov(2),
            },
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "prov": _prov(1),
                "children": [{"$ref": "#/texts/0"}],
                "references": [{"$ref": "#/groups/1"}],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "prov": _prov(2),
                "children": [{"$ref": "#/texts/1"}],
            },
        ],
    }

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="component page anchor",
    ):
        _bind_production_custody(
            payload,
            raw,
            native_texts=("Authoritative prose", "Page two"),
        )


def test_disconnected_same_page_public_anchored_components_pass() -> None:
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    table = payload["pages"][0]["items"][-1]
    table["reading_order"] = 2
    payload["pages"][0]["items"].insert(
        1,
        {
            "id": "p1-text-2",
            "type": "text",
            "reading_order": 1,
            "value": "Second public anchor",
            "md": "Second public anchor",
            "source": "native",
        },
    )
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Authoritative prose",
                "prov": _prov(1, top=10),
            },
            {
                "self_ref": "#/texts/1",
                "label": "text",
                "text": "Second public anchor",
                "prov": _prov(1, top=30),
            },
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            },
            {
                "self_ref": "#/groups/1",
                "label": "group",
                "children": [{"$ref": "#/texts/1"}],
            },
        ],
    }
    bound = _bind_production_custody(
        payload,
        raw,
        native_texts=("Authoritative prose Second public anchor",),
    )
    result = ParseResult.model_validate(bound)

    assert result.canonical_source_custody is not None
    assert result.canonical_source_custody.record_count == 2
    assert {record.page_index for record in result.canonical_source_custody.records} == {
        1
    }


@pytest.mark.parametrize(("path_kind", "field"), _NESTED_REFERENCE_PATHS)
def test_nested_scalar_group_reference_is_closed_exactly(
    path_kind: str,
    field: str,
) -> None:
    raw_reference = {"$ref": "#/groups/0"}
    document, raw, ir, reference_metadata = _nested_reference_fixture(
        path_kind,
        raw_reference,
    )
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)
    record = sidecar["records"][0]
    expected_assertion = {
        "field": field,
        "owner_raw_ref": "#/tables/0",
        "raw_slot_index": 0,
        "raw_target_slot_index": None,
        "reference_metadata": reference_metadata,
        "value": raw_reference,
    }

    assert len(detached.raw_closure.definitions) == 2
    assert len(detached.raw_closure.assertions) == 1
    assert sidecar["record_count"] == 1
    assert set(record) == CUSTODY_RECORD_KEYS
    assert record["owner_raw_ref"] == "#/tables/0"
    assert record["relationship_field"] == field
    assert record["raw_slot_index"] == 0
    assert record["raw_target_slot_index"] is None
    assert record["source_raw_ref"] == "#/tables/0"
    assert record["source_type"] == "table"
    assert record["source_content_basis"] == "public_ir"
    assert record["target_raw_ref"] == "#/groups/0"
    assert record["target_type"] == "group"
    assert record["target_content_basis"] == "opaque_group_empty"
    assert record["raw_assertion_sha256"] == hashlib.sha256(
        custody._canonical_bytes(expected_assertion)
    ).hexdigest()

    from app.services.presentation import build_canonical_presentation

    expected_canonical = build_canonical_presentation(
        build_document_ir(document)
    ).model_dump(mode="json", exclude_none=True)
    assert canonical == expected_canonical
    canonical_json = json.dumps(canonical, sort_keys=True)
    assert "#/groups/" not in canonical_json
    assert "raw_assertion_sha256" not in canonical_json


@pytest.mark.parametrize(("path_kind", "field"), _NESTED_REFERENCE_PATHS)
def test_nested_list_group_references_keep_stable_distinct_subslots(
    path_kind: str,
    field: str,
) -> None:
    raw_references = [
        {"$ref": "#/groups/0"},
        {"$ref": "#/groups/1"},
    ]
    document, raw, ir, reference_metadata = _nested_reference_fixture(
        path_kind,
        raw_references,
    )
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)
    records = sidecar["records"]

    assert len(detached.raw_closure.definitions) == 3
    assert len(detached.raw_closure.assertions) == 2
    assert sidecar["record_count"] == 2
    assert [record["raw_slot_index"] for record in records] == [0, 0]
    assert [record["raw_target_slot_index"] for record in records] == [0, 1]
    assert [record["target_raw_ref"] for record in records] == [
        "#/groups/0",
        "#/groups/1",
    ]
    assert len({record["record_id"] for record in records}) == 2
    assert len({record["raw_assertion_sha256"] for record in records}) == 2
    for target_slot, (record, raw_reference) in enumerate(
        zip(records, raw_references, strict=True)
    ):
        assert set(record) == CUSTODY_RECORD_KEYS
        assert record["owner_raw_ref"] == "#/tables/0"
        assert record["relationship_field"] == field
        assert record["source_raw_ref"] == "#/tables/0"
        assert record["source_content_basis"] == "public_ir"
        assert record["target_content_basis"] == "opaque_group_empty"
        expected_assertion = {
            "field": field,
            "owner_raw_ref": "#/tables/0",
            "raw_slot_index": 0,
            "raw_target_slot_index": target_slot,
            "reference_metadata": reference_metadata,
            "value": raw_reference,
        }
        assert record["raw_assertion_sha256"] == hashlib.sha256(
            custody._canonical_bytes(expected_assertion)
        ).hexdigest()

    from app.services.presentation import build_canonical_presentation

    expected_canonical = build_canonical_presentation(
        build_document_ir(document)
    ).model_dump(mode="json", exclude_none=True)
    assert canonical == expected_canonical


@pytest.mark.parametrize(("path_kind", "_field"), _NESTED_REFERENCE_PATHS)
def test_malformed_sibling_in_relevant_nested_list_fails_closed(
    path_kind: str,
    _field: str,
) -> None:
    document, raw, ir, _metadata = _nested_reference_fixture(
        path_kind,
        [{"$ref": "#/groups/0"}, {"$ref": 7}],
    )

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="nested raw assertion is malformed",
    ):
        custody.capture_opaque_group_edges(ir, raw)


@pytest.mark.parametrize(
    "declared_root_ref",
    [
        pytest.param("#/body/extra", id="extra-path"),
        pytest.param(7, id="non-string"),
    ],
)
def test_relevant_root_identity_must_be_exact(
    declared_root_ref: Any,
) -> None:
    raw = _base_raw_graph()
    raw["body"]["self_ref"] = declared_root_ref
    _document_value, raw, ir = _fixture(raw_graph=raw)

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="root identity is malformed",
    ):
        custody.capture_opaque_group_edges(ir, raw)


def test_unrelated_malformed_root_identity_is_ignored() -> None:
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "body": {
            "self_ref": 7,
            "children": [{"$ref": "#/texts/0"}],
        },
    }
    document, raw, ir = _fixture(raw_graph=raw)
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert sidecar["record_count"] == 0
    assert detached.raw_closure.assertions == ()
    assert canonical["policy_id"] == "canonical-presentation-v1"


def test_tuple_collections_and_relationship_slots_match_p01_list_semantics() -> None:
    clean_document, clean_raw, clean_ir = _fixture()
    clean_canonical, clean_sidecar, clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )
    tuple_raw = _base_raw_graph()
    tuple_raw["texts"] = tuple(tuple_raw["texts"])
    tuple_raw["groups"] = tuple(tuple_raw["groups"])
    tuple_raw["groups"][0]["children"] = tuple(
        tuple_raw["groups"][0]["children"]
    )
    document, tuple_raw, ir = _fixture(raw_graph=tuple_raw)
    canonical, sidecar, detached = _detach_restore_project(
        document,
        tuple_raw,
        ir,
    )

    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == clean_detached.raw_closure


@pytest.mark.parametrize(
    "path_kind",
    [pytest.param("graph", id="graph-cells"), pytest.param("data", id="data-cells")],
)
def test_tuple_nested_cells_match_p01_list_semantics(path_kind: str) -> None:
    field = dict(_NESTED_REFERENCE_PATHS)[path_kind]
    reference = {"$ref": "#/groups/0"}
    clean_document, clean_raw, clean_ir, _metadata = _nested_reference_fixture(
        path_kind,
        reference,
    )
    clean_canonical, clean_sidecar, clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )
    document, raw, _ir, _metadata = _nested_reference_fixture(
        path_kind,
        reference,
    )
    if path_kind == "graph":
        raw["tables"][0]["graph"]["cells"] = tuple(
            raw["tables"][0]["graph"]["cells"]
        )
    else:
        raw["tables"][0]["data"]["table_cells"] = tuple(
            raw["tables"][0]["data"]["table_cells"]
        )
    ir = build_document_ir(document, raw_graph=raw, native_texts=("T",))
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert sidecar["records"][0]["relationship_field"] == field
    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == clean_detached.raw_closure


@pytest.mark.parametrize(
    "invalid_children",
    [
        pytest.param("#/texts/0", id="string"),
        pytest.param(b"#/texts/0", id="bytes"),
        pytest.param(bytearray(b"#/texts/0"), id="bytearray"),
    ],
)
def test_relationship_slot_text_and_binary_scalars_fail_closed(
    invalid_children: Any,
) -> None:
    document, raw, ir = _fixture()
    raw["groups"][0]["children"] = invalid_children

    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.capture_opaque_group_edges(ir, raw)


@pytest.mark.parametrize(
    "raw_reference",
    [
        pytest.param(
            {"$ref": None, "cref": "#/texts/0"},
            id="null-ref-falls-back-to-cref",
        ),
        pytest.param(
            {"$ref": "", "cref": "#/texts/0"},
            id="empty-ref-falls-back-to-cref",
        ),
    ],
)
def test_ref_fallback_matches_p01_cref_semantics(
    raw_reference: dict[str, Any],
) -> None:
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [raw_reference],
            }
        ],
    }
    document, raw, ir = _fixture(raw_graph=raw)
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)
    record = sidecar["records"][0]

    assert sidecar["record_count"] == 1
    assert len(detached.raw_closure.assertions) == 1
    assert record["owner_raw_ref"] == "#/groups/0"
    assert record["member_raw_ref"] == "#/texts/0"
    assert record["source_raw_ref"] == "#/groups/0"
    assert record["target_raw_ref"] == "#/texts/0"
    assert canonical["policy_id"] == "canonical-presentation-v1"


@pytest.mark.parametrize(
    "padded_endpoint",
    [pytest.param("group", id="group-self-ref"), pytest.param("text", id="text-self-ref")],
)
def test_padded_definition_self_ref_matches_p01_normalized_binding(
    padded_endpoint: str,
) -> None:
    clean_raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            }
        ],
    }
    clean_document, clean_raw, clean_ir = _fixture(raw_graph=clean_raw)
    clean_canonical, clean_sidecar, clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )
    raw = deepcopy(clean_raw)
    collection = "groups" if padded_endpoint == "group" else "texts"
    raw[collection][0]["self_ref"] = f"  {raw[collection][0]['self_ref']}  "
    document, raw, ir = _fixture(raw_graph=raw)
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == clean_detached.raw_closure


@pytest.mark.parametrize(
    "raw_graph",
    [
        pytest.param(
            {
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [{"$ref": "#/texts/999"}],
                    }
                ]
            },
            id="dangling",
        ),
        pytest.param(
            {
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [{"$ref": "#/groups/0"}],
                    }
                ]
            },
            id="self-reference",
        ),
        pytest.param(
            {
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [{"$ref": "#/groups/1"}],
                    },
                    {
                        "self_ref": "#/groups/1",
                        "label": "group",
                        "children": [{"$ref": "#/groups/0"}],
                    },
                ]
            },
            id="cycle",
        ),
        pytest.param(
            {
                "texts": [
                    {
                        "self_ref": "#/texts/0",
                        "label": "text",
                        "text": "Page one",
                        "prov": _prov(1, top=10.0),
                    },
                    {
                        "self_ref": "#/texts/1",
                        "label": "text",
                        "text": "Page two",
                        "prov": _prov(2, top=10.0),
                    },
                ],
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [
                            {"$ref": "#/texts/0"},
                            {"$ref": "#/texts/1"},
                        ],
                    }
                ],
            },
            id="cross-page",
        ),
        pytest.param(
            {
                "texts": [
                    {
                        "self_ref": "#/texts/0",
                        "label": "text",
                        "text": "Unavailable raw-only text",
                        "prov": _prov(),
                    }
                ],
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [{"$ref": "#/texts/0"}],
                    }
                ],
            },
            id="raw-only-content",
        ),
        pytest.param(
            {
                "pictures": [
                    {
                        "self_ref": "#/pictures/0",
                        "label": "picture",
                        "prov": _prov(),
                    }
                ],
                "groups": [
                    {
                        "self_ref": "#/groups/0",
                        "label": "group",
                        "children": [{"$ref": "#/pictures/0"}],
                    }
                ],
            },
            id="raw-only-type",
        ),
    ],
)
def test_unsupported_relevant_assertions_fail_with_dedicated_integrity_error(
    raw_graph: dict[str, Any],
) -> None:
    page_count = 2 if any(
        provenance.get("page_no") == 2
        for value in raw_graph.get("texts", [])
        for provenance in value.get("prov", [])
    ) else 1
    if page_count == 2:
        document = _document(public_items=[], page_count=2)
        document["pages"][0]["items"] = [
            {
                "id": "page-one-text",
                "type": "text",
                "reading_order": 0,
                "value": "Page one",
                "md": "Page one",
                "source": "native",
            },
            _marker(1),
        ]
        document["pages"][1]["items"] = [
            {
                "id": "page-two-text",
                "type": "text",
                "reading_order": 0,
                "value": "Page two",
                "md": "Page two",
                "source": "native",
            }
        ]
        raw = deepcopy(raw_graph)
        ir = build_document_ir(
            document,
            raw_graph=raw,
            native_texts=("Page one", "Page two"),
        )
    else:
        document, raw, ir = _fixture(
            raw_graph=raw_graph,
            public_items=[],
        )
    before = deepcopy(document)

    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        _authoritative_ir, custody_ir, detached = _projection_inputs(
            document,
            raw,
            ir,
        )
        custody.seal_diagnostic_custody(
            document,
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
        )
    assert document == before


def test_irrelevant_raw_nan_is_ignored_without_semantic_drift() -> None:
    clean_document, clean_raw, clean_ir = _fixture()
    clean_canonical, clean_sidecar, _clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )

    document, raw, ir = _fixture()
    raw["irrelevant_metadata"] = {"score": float("nan")}
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == _clean_detached.raw_closure


def test_relevant_raw_nan_fails_with_dedicated_integrity_error() -> None:
    document, raw, ir = _fixture()
    # P01 ignores this unrecognized assertion annotation, but P04 custody owns
    # the complete literal RefItem and therefore requires finite strict JSON.
    raw["groups"][0]["children"][0]["score"] = float("nan")

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="finite|closure|invalid",
    ):
        custody.capture_opaque_group_edges(ir, raw)


def test_irrelevant_duplicate_definition_is_ignored_exactly() -> None:
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/9",
                "label": "text",
                "text": "Unrelated duplicate",
                "prov": _prov(),
            },
            {
                "self_ref": "#/texts/9",
                "label": "text",
                "text": "Unrelated duplicate",
                "prov": _prov(),
            },
        ]
    }
    document, raw, ir = _fixture(raw_graph=raw, public_items=[])
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)
    clean_document, clean_raw, clean_ir = _fixture(
        raw_graph={},
        public_items=[],
    )
    clean_canonical, clean_sidecar, clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )

    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == clean_detached.raw_closure
    assert sidecar["record_count"] == 0


def test_duplicate_definition_referenced_by_group_fails_closed() -> None:
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/9",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            },
            {
                "self_ref": "#/texts/9",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            },
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [{"$ref": "#/texts/9"}],
            }
        ],
    }
    document, raw, ir = _fixture(raw_graph=raw)

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="identity repeats|definition",
    ):
        custody.capture_opaque_group_edges(ir, raw)


def _deep_mapping(depth: int = 1_200) -> dict[str, Any]:
    root: dict[str, Any] = {}
    cursor = root
    for _index in range(depth):
        child: dict[str, Any] = {}
        cursor["next"] = child
        cursor = child
    return root


def test_irrelevant_deep_mapping_is_not_traversed_or_copied() -> None:
    clean_document, clean_raw, clean_ir = _fixture()
    clean_canonical, clean_sidecar, clean_detached = _detach_restore_project(
        clean_document,
        clean_raw,
        clean_ir,
    )

    document, raw, ir = _fixture()
    raw["irrelevant_deep_mapping"] = _deep_mapping()
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)

    assert canonical == clean_canonical
    assert sidecar == clean_sidecar
    assert detached.raw_closure == clean_detached.raw_closure


def test_relevant_deep_assertion_fails_with_dedicated_error() -> None:
    document, raw, ir = _fixture()
    raw["groups"][0]["children"][0]["metadata"] = _deep_mapping()

    with pytest.raises(
        custody.OpaqueGroupCustodyIntegrityError,
        match="closure|invalid|strict data",
    ):
        custody.capture_opaque_group_edges(ir, raw)


def test_large_irrelevant_relationship_list_is_streamed_outside_closure() -> None:
    document, raw, ir = _fixture()
    clean = custody.capture_opaque_group_edges(ir, raw)
    raw["texts"].append(
        {
            "self_ref": "#/texts/99",
            "label": "text",
            "children": [{"$ref": "#/texts/0"}] * 20_000,
        }
    )
    started = time.perf_counter()
    captured = custody.capture_opaque_group_edges(
        ir,
        raw,
        deadline=started + 5.0,
    )

    assert time.perf_counter() - started < 5.0
    assert captured.raw_closure == clean.raw_closure
    assert captured.original_relationship_ids == clean.original_relationship_ids


def test_relevant_group_relationship_list_hits_cap_before_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum = 8
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "children": [
                    {"$ref": "#/texts/0"} for _index in range(maximum + 1)
                ],
            }
        ],
    }
    _document_value, raw, ir = _fixture(raw_graph=raw)
    monkeypatch.setattr(custody, "MAX_RECORDS", maximum)

    with pytest.raises(
        custody.OpaqueGroupCustodyResourceError,
        match="assertion cap",
    ):
        custody.capture_opaque_group_edges(
            ir,
            raw,
            deadline=time.perf_counter() + 5.0,
        )


def test_relevant_root_relationship_list_hits_cap_before_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum = 8
    raw = _base_raw_graph()
    raw["body"]["children"] = [
        deepcopy(
            {"$ref": "#/groups/0"} if index % 2 == 0 else {"$ref": "#/texts/0"}
        )
        for index in range(maximum + 3)
    ]
    _document_value, raw, ir = _fixture(raw_graph=raw)
    monkeypatch.setattr(custody, "MAX_RECORDS", maximum)

    with pytest.raises(
        custody.OpaqueGroupCustodyResourceError,
        match="assertion cap",
    ):
        custody.capture_opaque_group_edges(
            ir,
            raw,
            deadline=time.perf_counter() + 5.0,
        )


@pytest.mark.parametrize(
    "path_kind",
    [pytest.param("graph", id="graph-cells"), pytest.param("data", id="data-cells")],
)
def test_relevant_nested_cell_list_hits_cap_before_projection(
    monkeypatch: pytest.MonkeyPatch,
    path_kind: str,
) -> None:
    maximum = 8
    document, raw, _ir, _metadata = _nested_reference_fixture(
        path_kind,
        {"$ref": "#/groups/0"},
    )
    raw_table = raw["tables"][0]
    if path_kind == "graph":
        raw_table["graph"]["cells"] = [
            {
                "cell_id": f"cell-{index}",
                "item_ref": {"$ref": "#/groups/0"},
            }
            for index in range(maximum + 1)
        ]
    else:
        template = raw_table["data"]["table_cells"][0]
        raw_table["data"]["table_cells"] = [
            {
                **deepcopy(template),
                "start_row_offset_idx": index,
                "end_row_offset_idx": index + 1,
                "ref": {"$ref": "#/groups/0"},
            }
            for index in range(maximum + 1)
        ]
        raw_table["data"]["num_rows"] = maximum + 1
    ir = build_document_ir(document, raw_graph=raw, native_texts=("T",))
    monkeypatch.setattr(custody, "MAX_RECORDS", maximum)

    with pytest.raises(
        custody.OpaqueGroupCustodyResourceError,
        match="assertion cap",
    ):
        custody.capture_opaque_group_edges(
            ir,
            raw,
            deadline=time.perf_counter() + 5.0,
        )


def test_singleton_root_placement_is_an_explicit_nonsemantic_nonclaim() -> None:
    raw = {
        "groups": [
            {
                "self_ref": "#/groups/0",
                "label": "group",
                "parent": {"$ref": "#/body"},
                "children": [],
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/groups/0"}],
        },
    }
    document, raw, ir = _fixture(raw_graph=raw, public_items=[])
    canonical, sidecar, detached = _detach_restore_project(document, raw, ir)
    clean_ir = build_document_ir(document)
    from app.services.presentation import build_canonical_presentation

    clean_canonical = build_canonical_presentation(clean_ir).model_dump(
        mode="json",
        exclude_none=True,
    )

    assert custody.ROOT_SINGLETON_POLICY == (
        "nonsemantic_placement_not_claimed"
    )
    assert detached.raw_closure.assertions == ()
    assert sidecar["record_count"] == 0
    assert canonical == clean_canonical


def test_detach_restore_is_exact_and_frozen_closure_detects_raw_toctou() -> None:
    document, raw, ir = _fixture()
    detached_ir, detached = custody.detach_opaque_group_edges(ir, raw)
    restored_ir = custody.restore_diagnostic_group_edges(detached_ir, detached)

    assert [
        relationship.model_dump(mode="json")
        for relationship in restored_ir.relationships
    ] == [relationship.model_dump(mode="json") for relationship in ir.relationships]

    changed = deepcopy(raw)
    changed["groups"][0]["children"].reverse()
    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.seal_diagnostic_custody(
            document,
            restored_ir,
            raw_graph=changed,
            detached_custody=detached,
        )


def test_frozen_closure_detects_final_ir_topology_toctou() -> None:
    document, raw, ir = _fixture()
    detached_ir, detached = custody.detach_opaque_group_edges(ir, raw)
    restored_ir = custody.restore_diagnostic_group_edges(detached_ir, detached)
    changed_ir = restored_ir.model_copy(deep=True)
    raw_edge = next(
        relationship
        for relationship in changed_ir.relationships
        if relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
        and str(relationship.metadata.get("source_ref", "")).startswith(
            "#/groups/"
        )
    )
    raw_edge.metadata["field"] = "captions"

    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.seal_diagnostic_custody(
            document,
            changed_ir,
            raw_graph=raw,
            detached_custody=detached,
        )


def test_relevant_raw_mutation_after_projection_precheck_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    committed = deepcopy(document)
    committed["canonical_presentation"] = {"predecessor": True}
    committed["canonical_source_custody"] = {"predecessor": True}
    before = deepcopy(committed)
    original_project_records = custody._project_records

    def project_then_mutate_live_raw(
        project_ir: DocumentIR,
        frozen_raw: dict[str, Any],
        *,
        deadline: float | None = None,
    ) -> Any:
        result = original_project_records(
            project_ir,
            frozen_raw,
            deadline=deadline,
        )
        raw["groups"][0]["children"].reverse()
        return result

    monkeypatch.setattr(custody, "_project_records", project_then_mutate_live_raw)
    with pytest.raises(custody.OpaqueGroupCustodyIntegrityError):
        custody.seal_diagnostic_custody(
            committed,
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
        )
    assert committed == before


def test_irrelevant_raw_mutation_after_projection_precheck_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, raw, ir = _fixture()
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    original_project_records = custody._project_records

    def project_then_mutate_irrelevant_raw(
        project_ir: DocumentIR,
        frozen_raw: Any,
        *,
        deadline: float | None = None,
    ) -> Any:
        result = original_project_records(
            project_ir,
            frozen_raw,
            deadline=deadline,
        )
        raw["irrelevant_post_precheck"] = {
            "score": float("nan"),
            "value": "outside relevant closure",
        }
        return result

    monkeypatch.setattr(custody, "_project_records", project_then_mutate_irrelevant_raw)
    sealed, relationship_ids = custody.seal_diagnostic_custody(
        document,
        custody_ir,
        raw_graph=raw,
        detached_custody=detached,
    )

    sidecar = sealed.model_dump(mode="json")
    assert tuple(sorted(relationship_ids)) == relationship_ids
    assert set(relationship_ids) == {
        record["relationship_id"] for record in sidecar["records"]
    }
    assert sidecar["record_count"] == 7


@pytest.mark.parametrize(
    ("failure", "expected_exception"),
    [
        pytest.param("resource", "OpaqueGroupCustodyResourceError", id="resource"),
        pytest.param("timeout", "OpaqueGroupCustodyTimeoutError", id="timeout"),
    ],
)
def test_diagnostic_seal_preserves_inputs_on_resource_or_timeout(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_exception: str,
) -> None:
    document, raw, ir = _fixture()
    document["canonical_presentation"] = {"predecessor": True}
    document["canonical_source_custody"] = {"predecessor": True}
    before = deepcopy(document)
    _authoritative_ir, custody_ir, detached = _projection_inputs(
        document,
        raw,
        ir,
    )
    deadline: float | None = None
    if failure == "resource":
        monkeypatch.setattr(custody, "MAX_RECORDS", 0)
    else:
        deadline = time.perf_counter() - 1.0

    exception_type = getattr(custody, expected_exception)
    with pytest.raises(exception_type):
        custody.seal_diagnostic_custody(
            document,
            custody_ir,
            raw_graph=raw,
            detached_custody=detached,
            deadline=deadline,
        )
    assert document == before


def test_terminal_recursion_error_rolls_back_exactly_as_resource_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import pipeline
    from app.services.input_documents import InputKind
    from tests.contract.test_p04_us01_p03_boundary import (
        _p03_settings,
        _projected_predecessor,
    )
    from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes

    fixture, transaction, baseline, baseline_ir = _projected_predecessor()

    def recurse(*_args: Any, **_kwargs: Any) -> Any:
        raise RecursionError("injected relevant closure recursion")

    monkeypatch.setattr(custody, "capture_opaque_group_edges", recurse)
    state: dict[str, Any] = {}
    now = time.perf_counter()
    actual = pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )

    assert strict_json_bytes(actual) == strict_json_bytes(baseline)
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    validated = state.get("_p04_validated_parse_result")
    assert isinstance(validated, ParseResult)
    assert strict_json_bytes(
        validated.model_dump(mode="json")
    ) == strict_json_bytes(
        ParseResult.model_validate(baseline).model_dump(mode="json")
    )
    assert not custody.has_literal_table_marker(actual)


def test_terminal_irrelevant_40mib_padding_stays_within_exact_rss_ceiling() -> None:
    root = Path(__file__).resolve().parents[2]
    script = r'''
import gc
import json
import resource
import sys
import time
from copy import deepcopy

from app.services import opaque_group_custody as custody
from app.services import pipeline
from app.services.input_documents import InputKind
from tests.contract.test_p04_us01_p03_boundary import (
    _p03_settings,
    _projected_predecessor,
)


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


fixture, transaction, baseline, baseline_ir = _projected_predecessor()
raw = deepcopy(fixture.raw_graph)
padding_bytes = 40 * 1024 * 1024
raw["irrelevant_padding"] = "x" * padding_bytes
gc.collect()
before = rss_bytes()
state = {}
now = time.perf_counter()
actual = pipeline._apply_terminal_table_authority(
    baseline,
    baseline_ir,
    transaction,
    _p03_settings(table_enabled=True),
    raw_graph=raw,
    native_texts=fixture.native_texts,
    text_run_evidence=None,
    form_evidence=None,
    outline_evidence=None,
    source_pdf_bytes=fixture.source_pdf_bytes,
    input_kind=InputKind.PDF,
    document_deadline=now + 5.0,
    page_deadlines={1: now + 0.5},
    state=state,
)
after = rss_bytes()
print(json.dumps({
    "custody_rejected": state.get("custody_rejected") is True,
    "delta_bytes": max(0, after - before),
    "marker": custody.has_literal_table_marker(actual),
    "padding_bytes": padding_bytes,
    "timed_out": state.get("timed_out") is True,
}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    measurement = json.loads(completed.stdout.strip().splitlines()[-1])

    assert measurement["padding_bytes"] == 41_943_040
    assert measurement["marker"] is True
    assert measurement["custody_rejected"] is False
    assert measurement["timed_out"] is False
    assert measurement["delta_bytes"] <= 67_108_864


@pytest.mark.parametrize(
    "scenario",
    (
        pytest.param("definitions", id="near-cap-disconnected-definitions"),
        pytest.param("assertions", id="near-cap-disconnected-assertions"),
    ),
)
def test_target_scoped_near_cap_disconnected_cardinality_stays_within_rss(
    scenario: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = r'''
import gc
import json
import resource
import sys
import time
import tracemalloc

from app.services import opaque_group_custody as custody
from tests.contract.test_p04_us01_opaque_group_custody import (
    _by_raw_ref,
    _fixture,
    _prov,
)


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


scenario = sys.argv[1]
base = {
    "texts": [
        {
            "self_ref": "#/texts/0",
            "label": "text",
            "text": "Public alpha",
            "prov": _prov(),
        }
    ],
    "groups": [
        {
            "self_ref": "#/groups/0",
            "label": "group",
            "children": [{"$ref": "#/texts/0"}],
        }
    ],
}
_document, _raw, ir = _fixture(raw_graph=base)
target_id = _by_raw_ref(ir)["#/texts/0"].id
if scenario == "definitions":
    count = custody.MAX_RAW_DEFINITIONS_SCANNED
    raw = {
        "texts": base["texts"] + [
            {"self_ref": f"#/texts/{index}", "label": "text"}
            for index in range(1, count - 1)
        ],
        "groups": base["groups"],
    }
    global_definition_count = count
    global_assertion_count = 1
elif scenario == "assertions":
    count = custody.MAX_RECORDS
    raw = {
        "texts": base["texts"] + [
            {"self_ref": f"#/texts/{index}", "label": "text"}
            for index in range(1, count)
        ],
        "groups": base["groups"] + [
            {
                "self_ref": f"#/groups/{index}",
                "label": "group",
                "children": [{"$ref": f"#/texts/{index}"}],
            }
            for index in range(1, count)
        ],
    }
    global_definition_count = count * 2
    global_assertion_count = count
else:
    raise AssertionError(f"unknown scenario: {scenario}")

gc.collect()
before_rss = rss_bytes()
tracemalloc.start()
started = time.perf_counter()
captured = custody.capture_opaque_group_edges(
    ir,
    raw,
    target_element_ids=frozenset({target_id}),
    deadline=started + 20.0,
)
elapsed_seconds = time.perf_counter() - started
_current_bytes, peak_allocated_bytes = tracemalloc.get_traced_memory()
tracemalloc.stop()
after_rss = rss_bytes()
print(json.dumps({
    "elapsed_seconds": elapsed_seconds,
    "global_assertion_count": global_assertion_count,
    "global_definition_count": global_definition_count,
    "peak_allocated_bytes": peak_allocated_bytes,
    "rss_delta_bytes": max(0, after_rss - before_rss),
    "selected_assertion_count": len(captured.raw_closure.assertions),
    "selected_definition_count": len(captured.raw_closure.definitions),
}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, scenario],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    measurement = json.loads(completed.stdout.strip().splitlines()[-1])

    expected_definitions = (
        custody.MAX_RAW_DEFINITIONS_SCANNED
        if scenario == "definitions"
        else custody.MAX_RECORDS * 2
    )
    expected_assertions = (
        1 if scenario == "definitions" else custody.MAX_RECORDS
    )
    assert measurement["global_definition_count"] == expected_definitions
    assert measurement["global_assertion_count"] == expected_assertions
    assert measurement["selected_definition_count"] == 2
    assert measurement["selected_assertion_count"] == 1
    assert measurement["elapsed_seconds"] < 20.0
    assert measurement["peak_allocated_bytes"] <= 67_108_864
    assert measurement["rss_delta_bytes"] <= 67_108_864


def test_unrelated_layout_value_error_is_not_reclassified_as_custody_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import layout

    document, raw, _ir = _fixture()

    def fail_layout(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("independent layout failure")

    monkeypatch.setattr(layout, "apply_layout_projection", fail_layout)
    settings = SimpleNamespace(
        layout_forms_enabled=False,
        layout_outline_structure_enabled=False,
    )
    with pytest.raises(ValueError, match="independent layout failure") as raised:
        round_trip_document(
            document,
            raw_graph=raw,
            native_texts=("Public alpha",),
            table_span_fidelity_enabled=True,
            layout_settings=settings,
        )
    assert type(raised.value) is ValueError
    assert not isinstance(
        raised.value,
        (
            custody.OpaqueGroupCustodyIntegrityError,
            custody.OpaqueGroupCustodyResourceError,
            custody.OpaqueGroupCustodyTimeoutError,
        ),
    )


def test_repeated_public_counterpart_content_hash_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_count = 64
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Public alpha",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": f"#/groups/{index}",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            }
            for index in range(group_count)
        ],
    }
    document, raw, ir = _fixture(raw_graph=raw)
    public_id = _by_raw_ref(ir)["#/texts/0"].id
    original = custody._member_content_digest_and_size
    calls: list[str] = []

    def counted(element: Any, *, deadline: float | None = None) -> Any:
        if element.id == public_id:
            calls.append(element.id)
        return original(element, deadline=deadline)

    monkeypatch.setattr(custody, "_member_content_digest_and_size", counted)
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)

    assert sidecar["record_count"] == group_count
    assert calls == [public_id]


def test_full_custody_sidecar_byte_cap_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import models

    assert models._CUSTODY_MAX_DOCUMENT_BYTES == 67_108_864
    document, raw, ir = _fixture()
    _canonical, sidecar, _detached = _detach_restore_project(document, raw, ir)
    exact_size = len(custody._canonical_bytes(sidecar))

    monkeypatch.setattr(models, "_CUSTODY_MAX_DOCUMENT_BYTES", exact_size)
    assert CanonicalSourceCustody.model_validate(sidecar).record_count == 7

    monkeypatch.setattr(models, "_CUSTODY_MAX_DOCUMENT_BYTES", exact_size - 1)
    with pytest.raises(ValidationError, match="document byte cap"):
        CanonicalSourceCustody.model_validate(sidecar)


def test_combined_table_and_source_custody_byte_cap_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import models

    assert models._TABLE_MAX_DOCUMENT_SIDECAR_BYTES == 67_108_864
    payload = _production_payload_with_custody()
    table_sidecar_bytes = sum(
        models._bounded_table_json_size(item["table_evidence"], 2**63) or 0
        for page in payload["pages"]
        for item in page["items"]
        if "table_evidence" in item
    )
    source_custody_bytes = models._bounded_table_json_size(
        payload["canonical_source_custody"],
        2**63,
    )
    assert source_custody_bytes is not None
    exact_combined_bytes = table_sidecar_bytes + source_custody_bytes

    # The unchanged 67,108,864-byte ceiling is inclusive over all table
    # evidence markers plus the P04 source-custody wrapper.  Shrinking the
    # ceiling around this bounded fixture proves exact acceptance and +1.
    monkeypatch.setattr(
        models,
        "_TABLE_MAX_DOCUMENT_SIDECAR_BYTES",
        exact_combined_bytes,
    )
    ParseResult.model_validate(payload)

    monkeypatch.setattr(
        models,
        "_TABLE_MAX_DOCUMENT_SIDECAR_BYTES",
        exact_combined_bytes - 1,
    )
    with pytest.raises(ValidationError, match="aggregate|byte cap"):
        ParseResult.model_validate(payload)


def test_api_serializer_retains_closed_custody_without_rendering_it() -> None:
    from app.services.serializer import to_markdown

    payload = _production_payload_with_custody()
    result = ParseResult.model_validate(payload)
    serialized = result.model_dump(mode="json")

    assert serialized["canonical_source_custody"] == (
        payload["canonical_source_custody"]
    )
    markdown = to_markdown(result)
    assert "Authoritative prose" in markdown
    assert "custody-" not in markdown
    assert "#/groups/" not in markdown


@pytest.mark.parametrize(
    "mutation",
    [
        "source_document_binding",
        "member_type",
        "counterpart_type",
        "member_content_digest",
        "counterpart_content_digest",
        "source_type",
        "target_type",
        "source_content_digest",
        "target_content_digest",
        "forbidden_member_raw_only_basis",
        "forbidden_counterpart_raw_only_basis",
        "page_range",
        "diagnostic_relationship_authority",
    ],
)
def test_api_rejects_source_endpoint_content_and_authority_forgeries(
    mutation: str,
) -> None:
    payload = _production_payload_with_custody()
    ParseResult.model_validate(payload)
    forged = deepcopy(payload)
    sidecar = forged["canonical_source_custody"]
    public = next(
        record
        for record in sidecar["records"]
        if record["member_content_basis"] == "public_ir"
    )

    if mutation == "source_document_binding":
        sidecar["source_sha256"] = "b" * 64
    elif mutation == "member_type":
        public["member_type"] = "picture"
    elif mutation == "counterpart_type":
        public["counterpart_type"] = "picture"
    elif mutation == "member_content_digest":
        public["member_content_sha256"] = "0" * 64
    elif mutation == "counterpart_content_digest":
        public["counterpart_content_sha256"] = "0" * 64
    elif mutation == "source_type":
        public["source_type"] = "picture"
    elif mutation == "target_type":
        public["target_type"] = "picture"
    elif mutation == "source_content_digest":
        public["source_content_sha256"] = "0" * 64
    elif mutation == "target_content_digest":
        public["target_content_sha256"] = "0" * 64
    elif mutation == "forbidden_member_raw_only_basis":
        public["member_content_basis"] = "raw_only_unavailable"
        public["member_content_sha256"] = None
    elif mutation == "forbidden_counterpart_raw_only_basis":
        public["counterpart_content_basis"] = "raw_only_unavailable"
        public["counterpart_content_sha256"] = None
    elif mutation == "page_range":
        public["page_index"] = forged["document"]["page_count"] + 1
    else:
        relationship_id = public["relationship_id"]
        block = forged["canonical_presentation"]["pages"][0]["blocks"][0]
        block["relationship_ids"].append(relationship_id)
    _reseal_sidecar(sidecar)

    with pytest.raises(ValidationError):
        ParseResult.model_validate(forged)


def _rename_record_raw_ref(
    record: dict[str, Any],
    old_raw_ref: str,
    new_raw_ref: str,
) -> None:
    for field in (
        "owner_raw_ref",
        "member_raw_ref",
        "group_raw_ref",
        "counterpart_raw_ref",
        "source_raw_ref",
        "target_raw_ref",
    ):
        if record[field] == old_raw_ref:
            record[field] = new_raw_ref


def test_global_public_raw_binding_rejects_one_record_only_rename() -> None:
    from tests.contract.test_p04_us01_table_api_schema import (
        _marked_payload_with_text,
    )

    payload = _marked_payload_with_text()
    raw = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Authoritative prose",
                "prov": _prov(),
            }
        ],
        "groups": [
            {
                "self_ref": f"#/groups/{index}",
                "label": "group",
                "children": [{"$ref": "#/texts/0"}],
            }
            for index in range(2)
        ],
    }
    bound = _bind_production_custody(
        payload,
        raw,
        native_texts=("Authoritative prose",),
    )
    ParseResult.model_validate(bound)
    forged = deepcopy(bound)
    sidecar = forged["canonical_source_custody"]
    assert sidecar["record_count"] == 2
    _rename_record_raw_ref(
        sidecar["records"][0],
        "#/texts/0",
        "#/texts/999",
    )
    _reseal_sidecar(sidecar)

    with pytest.raises(ValidationError, match="public raw binding"):
        ParseResult.model_validate(forged)


def test_coherent_all_field_raw_ref_reseal_documents_unkeyed_limitation() -> None:
    from app.services.serializer import to_markdown

    payload = _production_payload_with_custody()
    baseline = ParseResult.model_validate(payload)
    forged = deepcopy(payload)
    sidecar = forged["canonical_source_custody"]
    assert sidecar["record_count"] == 1
    record = sidecar["records"][0]
    _rename_record_raw_ref(record, "#/texts/0", "#/texts/999")
    # Raw-assertion digests are diagnostics, not keyed attestations.  A fully
    # coherent post-serialization rewrite can therefore reseal its own digest;
    # this accepted limitation must never be described as authenticity.
    record["raw_assertion_sha256"] = hashlib.sha256(
        b"coherent-unkeyed-raw-ref-rename"
    ).hexdigest()
    _reseal_sidecar(sidecar)

    accepted = ParseResult.model_validate(forged)
    assert accepted.pages == baseline.pages
    assert accepted.canonical_presentation == baseline.canonical_presentation
    assert accepted.canonical_source_custody is not None
    accepted_record = accepted.canonical_source_custody.records[0]
    assert "#/texts/999" in {
        accepted_record.owner_raw_ref,
        accepted_record.member_raw_ref,
        accepted_record.counterpart_raw_ref,
        accepted_record.source_raw_ref,
        accepted_record.target_raw_ref,
    }
    markdown = to_markdown(accepted)
    assert "#/texts/999" not in markdown
    assert "custody-" not in markdown


def test_no_marker_and_default_off_are_exact_and_do_not_call_custody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marked_document, raw, _ir = _fixture()
    unmarked_document, _raw, _unmarked_ir = _fixture(marked=False)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("custody helper called on excluded branch")

    monkeypatch.setattr(custody, "detach_opaque_group_edges", forbidden)
    projected, _ = round_trip_document(
        marked_document,
        raw_graph=raw,
        native_texts=("Public alpha",),
        table_span_fidelity_enabled=False,
    )
    assert projected == marked_document

    projected, _ = round_trip_document(
        unmarked_document,
        raw_graph=raw,
        native_texts=("Public alpha",),
        table_span_fidelity_enabled=True,
    )
    assert projected == unmarked_document


def test_import_order_keeps_default_modules_acyclic() -> None:
    root = Path(__file__).resolve().parents[2]
    scripts = (
        (
            "import sys; import app.models; "
            "print('app.services.opaque_group_custody' in sys.modules)"
        ),
        (
            "import sys; import app.services.opaque_group_custody; "
            "print('app.models' in sys.modules)"
        ),
    )
    outputs = [
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        for script in scripts
    ]
    assert outputs == ["False", "False"]
