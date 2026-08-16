"""Production-shaped raw-provenance custody for selected vector tables."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.models import RunningRegionDescriptor
from app.services import pipeline, table_semantics
from app.services import running_regions
from app.services.ir import round_trip_document
from app.services.presentation import build_canonical_presentation
from tests.stories.phase_04.test_p04_us02_table_reconciliation import (
    _selected_vector_reconcile,
    _vector_table,
)


SOURCE_SHA256 = "a" * 64


def _sealed_vector_fixture() -> tuple[
    dict[str, Any],
    Any,
    dict[int, list[dict[str, Any]]],
    dict[str, Any],
    tuple[str, ...],
]:
    rows = [
        ["Stop", "AM", "PM"],
        ["A", "7:41", "19:41"],
        ["B", "7:55", "19:55"],
    ]
    vector = _vector_table(
        rows,
        bbox={"x": 10.0, "y": 10.0, "w": 75.0, "h": 60.0},
    )
    reconciled, preliminary = _selected_vector_reconcile(vector)
    body_items: dict[int, list[dict[str, Any]]] = {1: []}
    gated = table_semantics.gate_table_candidates(
        reconciled,
        body_items,
        {},
        {},
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    sealed: dict[int, list[dict[str, Any]]] = {}
    table_semantics.finalize_selected_vector_representations(
        gated,
        preliminary,
        SOURCE_SHA256,
        sealed,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
    )
    assert len(sealed.get(1, [])) == 1
    table = gated[1][0]
    table["id"] = "table-1"
    table["reading_order"] = 0
    footer = {
        "id": "footer-1",
        "type": "footer",
        "reading_order": 3,
        "value": "Page 1 of 1",
        "md": "Page 1 of 1",
        "bbox": {
            "x": 10.0,
            "y": 85.0,
            "width": 40.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": 0.97,
        "label": "page_footer",
        "items": [{"value": "Page 1 of 1", "confidence": None}],
    }
    supplemental = {
        "id": "ocr-1",
        "type": "text",
        "reading_order": 1,
        "value": "raster duplicate",
        "md": "raster duplicate",
        "bbox": {
            "x": 10.0,
            "y": 72.0,
            "width": 40.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "ocr",
        "confidence": 0.91,
        "label": "ocr_text",
        "raw_ocr_text": "raster duplicate",
    }
    survivor = {
        "id": "native-1",
        "type": "text",
        "reading_order": 2,
        "value": "represented note",
        "md": "represented note",
        "bbox": {
            "x": 55.0,
            "y": 72.0,
            "width": 30.0,
            "height": 5.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": 0.95,
    }
    payload = {
        "schema_version": "1.0",
        "document": {
            "filename": "raw-vector.pdf",
            "mime_type": "application/pdf",
            "sha256": SOURCE_SHA256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 100.0,
                "page_height": 100.0,
                "unit": "pt",
                "success": True,
                "items": [table, supplemental, survivor, footer],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
        },
        "warnings": [],
    }
    raw_cells = []
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            raw_cells.append(
                {
                    "start_row_offset_idx": row_index,
                    "end_row_offset_idx": row_index + 1,
                    "start_col_offset_idx": column_index,
                    "end_col_offset_idx": column_index + 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": text,
                    "column_header": row_index == 0,
                    "row_header": False,
                    "row_section": False,
                    "bbox": {
                        "l": float(vector.cell_bboxes[row_index][column_index]["x"]),
                        "t": float(vector.cell_bboxes[row_index][column_index]["y"]),
                        "r": float(vector.cell_bboxes[row_index][column_index]["x"])
                        + float(vector.cell_bboxes[row_index][column_index]["w"]),
                        "b": float(vector.cell_bboxes[row_index][column_index]["y"])
                        + float(vector.cell_bboxes[row_index][column_index]["h"]),
                        "coord_origin": "TOPLEFT",
                    },
                }
            )
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "page_footer",
                "text": "Page 1 of 1",
                "source": "native",
                "confidence": 0.97,
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 15.0,
                            "r": 50.0,
                            "b": 10.0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                        "charspan": [0, 11],
                    }
                ],
            }
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "annotations": [],
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 90.0,
                            "r": 85.0,
                            "b": 30.0,
                            "coord_origin": "BOTTOMLEFT",
                        },
                    }
                ],
                "data": {
                    "num_rows": 3,
                    "num_cols": 3,
                    "table_cells": raw_cells,
                },
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/tables/0"},
                {"$ref": "#/texts/0"},
            ],
        },
    }
    native_texts = (
        "Stop AM PM\nA 7:41 19:41\nB 7:55 19:55\nPage 1 of 1",
    )
    projected, internal_ir = round_trip_document(
        payload,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )
    projected["canonical_presentation"] = build_canonical_presentation(
        internal_ir
    ).model_dump(mode="json", exclude_none=True)
    return projected, internal_ir, sealed, raw_graph, native_texts


def _bind(
    payload: dict[str, Any],
    internal_ir: Any,
    sealed: dict[int, list[dict[str, Any]]],
    raw_graph: dict[str, Any],
    native_texts: tuple[str, ...],
) -> dict[int, list[dict[str, Any]]]:
    return pipeline._bind_selected_vector_terminal_representations(
        payload,
        internal_ir,
        sealed,
        SOURCE_SHA256,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )


def _stage_running_raw_target(
    payload: dict[str, Any],
    internal_ir: Any,
) -> RunningRegionDescriptor:
    footer = next(
        item for item in payload["pages"][0]["items"] if item["id"] == "footer-1"
    )
    element = next(
        value
        for value in internal_ir.elements
        if value.properties.get("legacy_item", {}).get("id") == "footer-1"
    )
    bbox = next(
        value for value in internal_ir.bboxes if value.id == element.bbox_ids[0]
    )
    block = next(
        value
        for value in payload["canonical_presentation"]["pages"][0]["blocks"]
        if value["primary_element_id"] == element.id
    )
    descriptor = RunningRegionDescriptor.model_validate(
        {
            "id": "running-region-raw-footer",
            "page_id": element.page_id,
            "physical_page_index": 1,
            "role": "footer",
            "canonical_scope": "footer",
            "source_public_item_id": "footer-1",
            "source_public_path": ["pages", 0, "items", 3],
            "source_element_id": element.id,
            "predecessor_type": "footer",
            "predecessor_item_sha256": running_regions._sha256_json(
                running_regions._compact_public_item_payload(footer)
            ),
            "bbox_id": bbox.id,
            "bbox": {
                "x": bbox.x,
                "y": bbox.y,
                "width": bbox.width,
                "height": bbox.height,
                "unit": "pt",
            },
            "evidence_ids": [element.evidence_ids[0]],
            "source_object_ids": ["synthetic:page:1:footer"],
            "source_method": "trusted_layout_role",
            "repetition_group_id": None,
            "repetition_page_indexes": [],
            "confidence": {
                "scope": "deterministic_rule",
                "score": 1.0,
                "unavailable_reason": None,
            },
            "concern_codes": [],
            "canonical_block_id": block["id"],
        }
    )
    running_regions._stage_direct_candidate(
        owner=footer,
        descriptor=descriptor,
        ir_document=internal_ir,
    )
    payload["canonical_presentation"] = (
        running_regions._build_projected_canonical(
            internal_ir,
            (),
            payload["canonical_presentation"],
        )
    )
    return descriptor


def test_production_raw_provenance_table_binds_and_is_sealed() -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )

    raw_relationship = next(
        relationship
        for relationship in internal_ir.relationships
        if relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
    )
    assert any(
        str(relationship.type.value) == "contains"
        and relationship.source_id == raw_relationship.target_id
        and relationship.metadata == {"collection": "items", "index": 0}
        for relationship in internal_ir.relationships
    )

    bound = _bind(payload, internal_ir, sealed, raw_graph, native_texts)

    assert len(bound.get(1, [])) == 1
    binding = bound[1][0]["terminal_binding"]
    custody = deepcopy(binding["ir_raw_provenance"])
    custody_sha256 = custody.pop("custody_sha256")
    assert custody_sha256 == pipeline._selected_vector_terminal_sha256(
        custody
    )


def test_running_raw_target_stage_asymmetry_binds_exact_predecessor() -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    descriptor = _stage_running_raw_target(payload, internal_ir)
    target = next(
        element
        for element in internal_ir.elements
        if element.id == descriptor.source_element_id
    )
    assert not set(target.properties["legacy_item"]).intersection(
        pipeline._TERMINAL_RUNNING_REGION_SIDECAR_KEYS
    )

    bound = _bind(payload, internal_ir, sealed, raw_graph, native_texts)

    assert len(bound.get(1, [])) == 1
    running_custody = bound[1][0]["terminal_binding"]["ir_raw_provenance"][
        "target_running_projection"
    ]
    assert running_custody["descriptor_id"] == descriptor.id
    assert running_custody["predecessor_item_sha256"] == (
        descriptor.predecessor_item_sha256
    )


def _relocated_running_raw_target_fixture() -> tuple[Any, ...]:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    descriptor = _stage_running_raw_target(payload, internal_ir)
    initial_bound = _bind(payload, internal_ir, sealed, raw_graph, native_texts)
    assert len(initial_bound.get(1, [])) == 1

    stripped_payload, stripped_ir = running_regions.strip_running_regions(
        payload,
        internal_ir,
    )
    stripped_bound = _bind(
        stripped_payload,
        stripped_ir,
        initial_bound,
        raw_graph,
        native_texts,
    )
    assert len(stripped_bound.get(1, [])) == 1
    assert stripped_bound[1][0]["terminal_authority_sha256"] == (
        initial_bound[1][0]["terminal_authority_sha256"]
    )

    terminal_source = deepcopy(stripped_payload)
    terminal_source.pop("canonical_presentation", None)
    terminal_source["pages"][0]["items"] = [
        item
        for item in terminal_source["pages"][0]["items"]
        if item["id"] not in {"ocr-1", "native-1"}
    ]
    terminal_payload, terminal_ir = round_trip_document(
        terminal_source,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )
    for item_position, item in enumerate(terminal_payload["pages"][0]["items"]):
        item["reading_order"] = item_position
        element = next(
            value
            for value in terminal_ir.elements
            if value.properties.get("legacy_item", {}).get("id") == item["id"]
        )
        element.reading_order = item_position
        element.properties["source_position"] = item_position
        element.properties["legacy_item"]["reading_order"] = item_position
    terminal_payload["canonical_presentation"] = build_canonical_presentation(
        terminal_ir
    ).model_dump(mode="json", exclude_none=True)
    terminal_footer = next(
        item
        for item in terminal_payload["pages"][0]["items"]
        if item["id"] == "footer-1"
    )
    terminal_predecessor_sha256 = running_regions._sha256_json(
        running_regions._compact_public_item_payload(terminal_footer)
    )
    relocated = descriptor.model_copy(
        deep=True,
        update={
            "source_public_path": ["pages", 0, "items", 1],
            "predecessor_item_sha256": terminal_predecessor_sha256,
        },
    )
    running_regions._stage_direct_candidate(
        owner=terminal_footer,
        descriptor=relocated,
        ir_document=terminal_ir,
    )
    terminal_payload["canonical_presentation"] = (
        running_regions._build_projected_canonical(
            terminal_ir,
            (),
            terminal_payload["canonical_presentation"],
        )
    )

    final_bound = _bind(
        terminal_payload,
        terminal_ir,
        stripped_bound,
        raw_graph,
        native_texts,
    )

    return (
        terminal_payload,
        terminal_ir,
        stripped_bound,
        initial_bound,
        final_bound,
        raw_graph,
        native_texts,
    )


def test_running_raw_target_custody_survives_strip_and_exact_relocation() -> None:
    (
        _terminal_payload,
        _terminal_ir,
        _stripped_bound,
        initial_bound,
        final_bound,
        _raw_graph,
        _native_texts,
    ) = _relocated_running_raw_target_fixture()

    assert len(final_bound.get(1, [])) == 1
    assert final_bound[1][0]["terminal_authority_sha256"] == (
        initial_bound[1][0]["terminal_authority_sha256"]
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "baseline_hash",
        "forged_hash",
        "path",
        "ir_public_descriptor",
        "prior_projection",
        "prior_custody",
    ),
)
def test_running_raw_target_relocated_hash_custody_tamper_refuses_authority(
    tamper: str,
) -> None:
    (
        terminal_payload,
        terminal_ir,
        stripped_bound,
        initial_bound,
        _final_bound,
        raw_graph,
        native_texts,
    ) = _relocated_running_raw_target_fixture()
    footer = next(
        item
        for item in terminal_payload["pages"][0]["items"]
        if item["id"] == "footer-1"
    )
    target = next(
        element
        for element in terminal_ir.elements
        if element.properties.get("legacy_item", {}).get("id") == "footer-1"
    )
    if tamper in {"baseline_hash", "forged_hash"}:
        changed = (
            initial_bound[1][0]["terminal_binding"]["ir_raw_provenance"]
            ["target_running_projection"]["predecessor_item_sha256"]
            if tamper == "baseline_hash"
            else "f" * 64
        )
        footer["running_region"]["predecessor_item_sha256"] = changed
        target.running_region = RunningRegionDescriptor.model_validate(
            footer["running_region"]
        )
    elif tamper == "path":
        footer["running_region"]["source_public_path"] = [
            "pages",
            0,
            "items",
            0,
        ]
        target.running_region = RunningRegionDescriptor.model_validate(
            footer["running_region"]
        )
    elif tamper == "ir_public_descriptor":
        target.running_region = target.running_region.model_copy(
            deep=True,
            update={"predecessor_item_sha256": "e" * 64},
        )
    elif tamper == "prior_projection":
        stripped_bound[1][0]["terminal_binding"]["ir_raw_provenance"][
            "target_running_projection"
        ]["descriptor_stable_sha256"] = "d" * 64
    else:
        stripped_bound[1][0]["terminal_binding"]["ir_raw_provenance"][
            "custody_sha256"
        ] = "c" * 64

    rebound = _bind(
        terminal_payload,
        terminal_ir,
        stripped_bound,
        raw_graph,
        native_texts,
    )
    if tamper == "prior_custody":
        assert len(rebound.get(1, [])) == 1
        assert rebound != stripped_bound
    else:
        assert rebound == {}


@pytest.mark.parametrize(
    "tamper",
    (
        "basis",
        "root",
        "source_index",
        "evidence_missing",
        "evidence_reordered",
        "extra_metadata",
    ),
)
def test_merged_raw_legacy_reading_edge_tamper_refuses_authority(
    tamper: str,
) -> None:
    (
        terminal_payload,
        terminal_ir,
        stripped_bound,
        _initial_bound,
        _final_bound,
        raw_graph,
        native_texts,
    ) = _relocated_running_raw_target_fixture()
    merged = next(
        relationship
        for relationship in terminal_ir.relationships
        if str(relationship.type.value) == "reading_before"
        and relationship.metadata.get("basis") == "legacy_reading_order"
        and "reference_metadata" in relationship.metadata
    )
    if tamper == "basis":
        merged.metadata["basis"] = "changed"
    elif tamper == "root":
        merged.metadata["reference_metadata"][0]["root_container"] = "#/other"
    elif tamper == "source_index":
        merged.metadata["reference_metadata"][0]["source_child_index"] = 2
    elif tamper == "evidence_missing":
        merged.evidence_ids.pop()
    elif tamper == "evidence_reordered":
        merged.evidence_ids.reverse()
    else:
        merged.metadata["unknown"] = True

    assert (
        _bind(
            terminal_payload,
            terminal_ir,
            stripped_bound,
            raw_graph,
            native_texts,
        )
        == {}
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "missing_sidecar",
        "wrong_policy",
        "unknown_sidecar",
        "wrong_type",
        "descriptor",
        "predecessor_hash",
    ),
)
def test_running_raw_target_stage_tamper_refuses_authority(tamper: str) -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    descriptor = _stage_running_raw_target(payload, internal_ir)
    footer = next(
        item for item in payload["pages"][0]["items"] if item["id"] == "footer-1"
    )
    target = next(
        element
        for element in internal_ir.elements
        if element.id == descriptor.source_element_id
    )
    if tamper == "missing_sidecar":
        footer.pop("running_region_policy")
    elif tamper == "wrong_policy":
        footer["running_region_policy"] = "changed"
    elif tamper == "unknown_sidecar":
        footer["unknown_semantic_sidecar"] = True
    elif tamper == "wrong_type":
        footer["type"] = "header"
    elif tamper == "descriptor":
        target.running_region = descriptor.model_copy(
            deep=True,
            update={"source_method": "cross_page_repetition"},
        )
    else:
        changed = "f" * 64
        target.running_region = descriptor.model_copy(
            deep=True,
            update={"predecessor_item_sha256": changed},
        )
        footer["running_region"]["predecessor_item_sha256"] = changed

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda graph: graph["tables"][0].update({"self_ref": "#/tables/9"}),
        lambda graph: graph["tables"][0]["prov"][0]["bbox"].update({"r": 91.0}),
        lambda graph: graph["body"]["children"].reverse(),
        lambda graph: graph["texts"][0].update({"text": "Changed footer"}),
        lambda graph: graph["tables"].append(deepcopy(graph["tables"][0])),
    ],
    ids=("raw_ref", "bbox", "body_order", "target_evidence", "duplicate_ref"),
)
def test_raw_provenance_mismatch_refuses_optional_authority(mutate: Any) -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    mutate(raw_graph)

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


def test_raw_ir_record_tamper_or_extra_refuses_optional_authority() -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    table_element = next(
        element
        for element in internal_ir.elements
        if element.properties.get("legacy_item", {}).get("id") == "table-1"
    )
    table_element.properties["unknown_semantic_sidecar"] = True

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


@pytest.mark.parametrize(
    "tamper",
    (
        "bbox_missing",
        "bbox_reordered",
        "evidence_metadata",
        "evidence_reordered",
        "relationship_missing",
        "relationship_extra",
        "relationship_evidence",
        "target_contains_missing",
        "target_contains_metadata",
        "target_extra_edge",
        "evidence_thief",
        "coordinate",
        "target_coordinate",
        "concern_raw_ref",
    ),
)
def test_raw_ir_custody_tamper_refuses_optional_authority(tamper: str) -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    table_element = next(
        element
        for element in internal_ir.elements
        if element.properties.get("legacy_item", {}).get("id") == "table-1"
    )
    raw_relationship = next(
        relationship
        for relationship in internal_ir.relationships
        if relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
    )
    target = next(
        element
        for element in internal_ir.elements
        if element.id == raw_relationship.target_id
    )
    target_contains = next(
        relationship
        for relationship in internal_ir.relationships
        if str(relationship.type.value) == "contains"
        and relationship.source_id == target.id
        and relationship.metadata == {"collection": "items", "index": 0}
    )
    if tamper == "bbox_missing":
        table_element.bbox_ids.pop()
    elif tamper == "bbox_reordered":
        table_element.bbox_ids.reverse()
    elif tamper == "evidence_metadata":
        derived = next(
            record
            for record in internal_ir.evidence
            if record.id in table_element.evidence_ids
            and str(record.method.value) == "derived"
        )
        derived.metadata["provenance_index"] = 1
    elif tamper == "evidence_reordered":
        table_element.evidence_ids.reverse()
    elif tamper == "relationship_missing":
        internal_ir.relationships = [
            value
            for value in internal_ir.relationships
            if value.id != raw_relationship.id
        ]
    elif tamper == "relationship_extra":
        internal_ir.relationships.append(
            raw_relationship.model_copy(
                deep=True,
                update={"id": "rel-extra-source-grounded"},
            )
        )
    elif tamper == "relationship_evidence":
        raw_relationship.evidence_ids.reverse()
    elif tamper == "target_contains_missing":
        internal_ir.relationships = [
            value
            for value in internal_ir.relationships
            if value.id != target_contains.id
        ]
    elif tamper == "target_contains_metadata":
        target_contains.metadata["index"] = 1
    elif tamper == "target_extra_edge":
        from app.services.ir import RelationshipType

        unrelated = next(
            element
            for element in internal_ir.elements
            if element.properties.get("legacy_item", {}).get("id") == "native-1"
        )
        internal_ir.relationships.append(
            raw_relationship.model_copy(
                deep=True,
                update={
                    "id": "rel-extra-target-edge",
                    "type": RelationshipType.CONTAINS,
                    "source_id": unrelated.id,
                    "target_id": target.id,
                    "evidence_ids": [],
                    "metadata": {},
                },
            )
        )
    elif tamper == "evidence_thief":
        from app.services.ir import RelationshipType

        unrelated = [
            element
            for element in internal_ir.elements
            if element.properties.get("legacy_item", {}).get("id")
            in {"ocr-1", "native-1"}
        ]
        assert len(unrelated) == 2
        internal_ir.relationships.append(
            raw_relationship.model_copy(
                deep=True,
                update={
                    "id": "rel-extra-evidence-thief",
                    "type": RelationshipType.CONTAINS,
                    "source_id": unrelated[0].id,
                    "target_id": unrelated[1].id,
                    "evidence_ids": [table_element.evidence_ids[0]],
                    "metadata": {},
                },
            )
        )
    elif tamper == "coordinate":
        raw_bbox = next(
            value
            for value in internal_ir.bboxes
            if value.id == table_element.bbox_ids[1]
        )
        coordinate = next(
            value
            for value in internal_ir.coordinate_systems
            if value.id == raw_bbox.coordinate_system_id
        )
        coordinate.transform_to_page = (2.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    elif tamper == "target_coordinate":
        target_bbox = next(
            value
            for value in internal_ir.bboxes
            if value.id == target.bbox_ids[0]
        )
        coordinate = next(
            value
            for value in internal_ir.coordinate_systems
            if value.id == target_bbox.coordinate_system_id
        )
        coordinate.transform_to_page = (2.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    else:
        from app.services.ir import IRConcern

        internal_ir.concerns.append(
            IRConcern(
                code="raw_provenance_probe",
                message="must remain fail closed",
                source_ref="#/tables/0",
            )
        )

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


def test_raw_graph_caps_refuse_before_reference_ir_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    raw_graph["texts"] = [
        {"self_ref": f"#/texts/{index}"}
        for index in range(pipeline._SELECTED_VECTOR_RAW_MAX_RECORDS + 1)
    ]
    from app.services import ir as ir_service

    monkeypatch.setattr(
        ir_service,
        "build_document_ir",
        lambda *_args, **_kwargs: pytest.fail(
            "reference IR must not build after raw cap refusal"
        ),
    )

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


def test_raw_graph_byte_cap_refuses_before_reference_ir_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, internal_ir, sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    raw_graph["tables"][0]["oversized_probe"] = "x" * (8 * 1024 * 1024)
    from app.services import ir as ir_service

    monkeypatch.setattr(
        ir_service,
        "build_document_ir",
        lambda *_args, **_kwargs: pytest.fail(
            "reference IR must not build after raw byte refusal"
        ),
    )

    assert _bind(payload, internal_ir, sealed, raw_graph, native_texts) == {}


def _raw_transition_fixture() -> tuple[
    dict[str, Any], Any, dict[str, Any], Any, list[dict[str, Any]]
]:
    payload, baseline_ir, _sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    snapshot = deepcopy(payload["pages"][0]["items"][1])
    terminal_source = deepcopy(payload)
    terminal_source.pop("canonical_presentation", None)
    terminal_source["pages"][0]["items"] = [
        item
        for item in terminal_source["pages"][0]["items"]
        if item["id"] != "ocr-1"
    ]
    terminal_payload, terminal_ir = round_trip_document(
        terminal_source,
        raw_graph=raw_graph,
        native_texts=native_texts,
    )
    terminal_positions = {}
    for item_position, item in enumerate(terminal_payload["pages"][0]["items"]):
        terminal_positions[item["id"]] = item_position
        item["reading_order"] = item_position
    for element in terminal_ir.elements:
        legacy = element.properties.get("legacy_item")
        legacy_id = legacy.get("id") if isinstance(legacy, dict) else None
        if legacy_id in terminal_positions:
            element.reading_order = terminal_positions[legacy_id]
            element.properties["source_position"] = terminal_positions[legacy_id]
            element.properties["legacy_item"]["reading_order"] = terminal_positions[
                legacy_id
            ]
    terminal_payload["canonical_presentation"] = build_canonical_presentation(
        terminal_ir
    ).model_dump(mode="json", exclude_none=True)
    selections = [
        {
            "owner_id": "ocr-1",
            "owner_type": "text",
            "page_index": 1,
            "terminal_reason": "selected_vector_source_owned_table_duplicate",
            "rejected_ocr_alternative": {
                "owner_snapshot": snapshot,
                "canonical_owner": {
                    "page_index": 1,
                    "owner_item_position": 1,
                },
            },
        }
    ]
    return payload, baseline_ir, terminal_payload, terminal_ir, selections


def test_raw_reading_edge_survives_selected_vector_ir_transition_exactly() -> None:
    _baseline, baseline_ir, terminal, terminal_ir, selections = (
        _raw_transition_fixture()
    )

    pipeline._validate_selected_vector_ir_transition(
        baseline_ir,
        terminal_ir,
        selections,
        terminal,
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "element_reading_order",
        "source_position",
        "legacy_reading_order",
        "public_reading_order",
    ),
)
def test_selected_vector_ir_transition_rejects_positional_tamper(
    tamper: str,
) -> None:
    _baseline, baseline_ir, terminal, terminal_ir, selections = (
        _raw_transition_fixture()
    )
    survivor = next(
        element
        for element in terminal_ir.elements
        if element.properties.get("legacy_item", {}).get("id") == "native-1"
    )
    public_survivor = next(
        item
        for item in terminal["pages"][0]["items"]
        if item["id"] == "native-1"
    )
    if tamper == "element_reading_order":
        survivor.reading_order += 1
    elif tamper == "source_position":
        survivor.properties["source_position"] += 1
    elif tamper == "legacy_reading_order":
        survivor.properties["legacy_item"]["reading_order"] += 1
    else:
        public_survivor["reading_order"] += 1

    with pytest.raises(ValueError):
        pipeline._validate_selected_vector_ir_transition(
            baseline_ir,
            terminal_ir,
            selections,
            terminal,
        )


def _anchor_limit_transition_fixture() -> tuple[Any, dict[str, Any], Any, list[dict[str, Any]]]:
    payload, _initial_ir, _sealed, raw_graph, native_texts = (
        _sealed_vector_fixture()
    )
    payload.pop("canonical_presentation", None)
    table, first_ocr, survivor, footer = payload["pages"][0]["items"]
    selected_items = [first_ocr]
    for index in range(2, 511):
        item = deepcopy(first_ocr)
        item.update(
            {
                "id": f"ocr-{index}",
                "reading_order": index,
                "value": f"raster duplicate {index}",
                "md": f"raster duplicate {index}",
                "raw_ocr_text": f"raster duplicate {index}",
            }
        )
        selected_items.append(item)
    survivor["reading_order"] = 511
    footer["reading_order"] = 512
    payload["pages"][0]["items"] = [
        table,
        *selected_items,
        survivor,
        footer,
    ]
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        layout_relationship_order_enabled=True,
    )
    baseline_payload, baseline_ir = round_trip_document(
        payload,
        raw_graph=raw_graph,
        native_texts=native_texts,
        text_reconciliation_enabled=True,
        layout_settings=settings,
    )
    selected_ids = {item["id"] for item in selected_items}
    terminal_source = deepcopy(baseline_payload)
    terminal_source["pages"][0]["items"] = [
        item
        for item in terminal_source["pages"][0]["items"]
        if item["id"] not in selected_ids
    ]
    terminal_payload, terminal_ir = round_trip_document(
        terminal_source,
        raw_graph=raw_graph,
        native_texts=native_texts,
        text_reconciliation_enabled=True,
        layout_settings=settings,
    )
    selections = [
        {
            "owner_id": item["id"],
            "owner_type": "text",
            "page_index": 1,
            "terminal_reason": "selected_vector_source_owned_table_duplicate",
            "rejected_ocr_alternative": {
                "owner_snapshot": deepcopy(item),
                "canonical_owner": {
                    "page_index": 1,
                    "owner_item_position": item_position,
                },
            },
        }
        for item_position, item in enumerate(
            baseline_payload["pages"][0]["items"]
        )
        if item["id"] in selected_ids
    ]
    assert len(selections) == 510
    return baseline_ir, terminal_payload, terminal_ir, selections


def test_resolved_relationship_order_anchor_limit_concern_is_exactly_closed() -> None:
    baseline_ir, terminal, terminal_ir, selections = (
        _anchor_limit_transition_fixture()
    )
    assert [value.code for value in baseline_ir.concerns] == [
        "relationship_order_page_limit"
    ]
    assert terminal_ir.concerns == []

    pipeline._validate_selected_vector_ir_transition(
        baseline_ir,
        terminal_ir,
        selections,
        terminal,
    )


@pytest.mark.parametrize(
    "tamper",
    ("message", "page_id", "anchor_count", "limit", "terminal_added"),
)
def test_resolved_anchor_limit_concern_tamper_is_rejected(tamper: str) -> None:
    baseline_ir, terminal, terminal_ir, selections = (
        _anchor_limit_transition_fixture()
    )
    concern = baseline_ir.concerns[0]
    if tamper == "message":
        concern.message = "Changed"
    elif tamper == "page_id":
        concern.metadata["page_id"] = "page-unknown"
    elif tamper == "anchor_count":
        concern.metadata["anchor_count"] -= 1
    elif tamper == "limit":
        concern.metadata["limit"] -= 1
    else:
        terminal_ir.concerns.append(concern.model_copy(deep=True))

    with pytest.raises(ValueError):
        pipeline._validate_selected_vector_ir_transition(
            baseline_ir,
            terminal_ir,
            selections,
            terminal,
        )


@pytest.mark.parametrize("tamper", ("metadata", "drop", "add", "evidence"))
def test_raw_reading_edge_transition_tamper_is_rejected(tamper: str) -> None:
    _baseline, baseline_ir, terminal, terminal_ir, selections = (
        _raw_transition_fixture()
    )
    baseline_raw = next(
        relationship
        for relationship in baseline_ir.relationships
        if relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
    )
    terminal_raw = next(
        relationship
        for relationship in terminal_ir.relationships
        if relationship.metadata.get("normalization_origin")
        == "docling_reference_graph"
    )
    if tamper == "metadata":
        baseline_raw.metadata["field"] = "body.children"
    elif tamper == "drop":
        terminal_ir.relationships = [
            value
            for value in terminal_ir.relationships
            if value.id != terminal_raw.id
        ]
    elif tamper == "add":
        terminal_ir.relationships.append(
            terminal_raw.model_copy(
                deep=True,
                update={"id": "rel-extra-raw-reading"},
            )
        )
    else:
        terminal_raw.evidence_ids.reverse()

    with pytest.raises(ValueError):
        pipeline._validate_selected_vector_ir_transition(
            baseline_ir,
            terminal_ir,
            selections,
            terminal,
        )
