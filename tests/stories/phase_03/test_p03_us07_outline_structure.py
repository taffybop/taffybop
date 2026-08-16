"""P03-US07 source-truth, readiness-fixture, and story acceptance tests."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from app.services.ir import EvidenceRecord, IRBoundingBox, round_trip_document
from app.services.presentation import build_canonical_presentation

from tests.fixtures.phase_03.outline_structure.contract import (
    CONCERN_CODES,
    INCIDENT_CARDINALITY,
    INTERSTITIAL_TYPES,
    IR_GROUP_DESCRIPTOR_FIELDS,
    IR_ITEM_DESCRIPTOR_FIELDS,
    MARKER_STYLES,
    PUBLIC_CONTINUATION_FIELDS,
    PUBLIC_GROUP_FIELDS,
    PUBLIC_ITEM_FIELDS,
    build_group_element_contract,
    canonical_closure,
    combine_terminal_processing_summaries,
    execute_transaction_witness,
    render_outline_group,
    sha256_text,
    strip_complete_outline_sidecars,
    terminal_reentry_order,
    validate_public_sidecar,
    validate_processing_summary,
    validate_source_report,
)
from tests.fixtures.phase_03.outline_structure.oracle import (
    CANONICAL_EXPECTATIONS,
    COMPONENT_GROUPS,
    PREDECESSOR_IDENTITIES,
    REVIEWED_COUNTS,
    SETTLEMENT_GROUP,
    SETTLEMENT_CONTINUATION_CANONICAL,
    SOURCE_IDENTITIES,
    SOURCE_REPORTS,
    oracle_sha256,
)
from tests.fixtures.phase_03.outline_structure.synthetic import (
    REQUIRED_SYNTHETIC_COVERAGE,
    SYNTHETIC_FIXTURES,
    SYNTHETIC_THRESHOLDS,
    build_deadline_witness,
    build_nonfinite_bbox_witness,
    build_resource_boundary_witness,
    build_synthetic_fixture,
    fixture_hashes,
    registry_sha256,
    self_check,
    verify_pdf_readers,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
BASELINE = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _box(word: dict[str, Any]) -> dict[str, float | str]:
    return {
        "x": round(float(word["x0"]), 3),
        "y": round(float(word["top"]), 3),
        "width": round(float(word["x1"]) - float(word["x0"]), 3),
        "height": round(float(word["bottom"]) - float(word["top"]), 3),
        "unit": "pt",
    }


def _all_component_nodes() -> list[dict[str, Any]]:
    return [node for group in COMPONENT_GROUPS for node in group["nodes"]]


def _relationship_counts(group: dict[str, Any]) -> Counter[str]:
    nodes = list(group["nodes"])
    sibling_counts = Counter(node["parent_index"] for node in nodes)
    return Counter(
        {
            "contains": len(nodes),
            "outline_parent_of": sum(
                node["parent_index"] is not None for node in nodes
            ),
            "outline_next": sum(max(count - 1, 0) for count in sibling_counts.values()),
            "outline_continuation_of": len(group.get("continuations") or ()),
        }
    )


def _path_value(payload: Any, path: tuple[str | int, ...]) -> Any:
    current = payload
    for part in path:
        current = current[part]
    return current


def test_reviewed_source_identities_are_exact() -> None:
    for case, identity in SOURCE_IDENTITIES.items():
        path = WORKSPACE / identity["path"]
        assert path.stat().st_size == identity["size_bytes"]
        assert _sha256(path) == identity["sha256"]
        with pdfplumber.open(path) as document:
            assert len(document.pages) == identity["page_count"]

    for identity in PREDECESSOR_IDENTITIES.values():
        path = WORKSPACE / identity["path"]
        assert path.stat().st_size == identity["size_bytes"]
        assert _sha256(path) == identity["sha256"]


def test_component_native_marker_truth_is_exact() -> None:
    expected = _all_component_nodes()
    with pdfplumber.open(CORPUS / "component-datasheet.pdf") as document:
        markers = [
            word
            for word in document.pages[0].extract_words()
            if word["text"] in {"•", "◦"}
        ]
    assert [word["text"] for word in markers] == [
        node["raw_marker"] for node in expected
    ]
    assert [_box(word) for word in markers] == [
        node["marker_bbox"] for node in expected
    ]
    assert Counter(word["text"] for word in markers) == Counter({"•": 11, "◦": 5})


def test_settlement_native_marker_truth_is_literal_period_style() -> None:
    expected = list(SETTLEMENT_GROUP["nodes"])
    with pdfplumber.open(CORPUS / "settlement-agreement.pdf") as document:
        markers = [
            word
            for word in document.pages[0].extract_words()
            if word["text"] in {"a.", "b.", "c.", "(a)", "(b)", "(c)"}
        ]
    assert [word["text"] for word in markers] == ["a.", "b.", "c."]
    assert [_box(word) for word in markers] == [
        node["marker_bbox"] for node in expected
    ]


def test_reviewed_predecessor_values_match_frozen_node_digests() -> None:
    component = json.loads(
        (BASELINE / "component-datasheet" / "our-output.json").read_text()
    )
    component_values = [
        value
        for item in component["pages"][0]["items"]
        if item["type"] == "list"
        for value in item["value"]
    ]
    settlement = json.loads(
        (BASELINE / "settlement-agreement" / "our-output.json").read_text()
    )
    settlement_values = [
        settlement["pages"][0]["items"][index]["value"] for index in (1, 2, 4)
    ]
    assert [
        hashlib.sha256(value.encode()).hexdigest() for value in component_values
    ] == [node["value_sha256"] for node in _all_component_nodes()]
    assert [
        hashlib.sha256(value.encode()).hexdigest() for value in settlement_values
    ] == [node["value_sha256"] for node in SETTLEMENT_GROUP["nodes"]]


def test_oracle_freezes_complete_source_identity_marker_and_bbox_contract() -> None:
    required_node_fields = {
        "id",
        "element_id",
        "group_id",
        "page_id",
        "source_public_item_id",
        "source_public_path",
        "source_bbox_id",
        "source_evidence_ids",
        "source_object",
        "sequence_kind",
        "marker_style",
        "raw_marker",
        "legacy_marker",
        "marker_ownership",
        "marker_separator",
        "body_text",
        "predecessor_value",
        "marker_bbox",
        "item_bbox",
        "level",
        "ordinal",
        "parent_id",
        "marker_evidence_id",
        "marker_bbox_id",
        "marker_bbox_record",
        "marker_evidence_record",
        "source_method",
        "confidence",
        "concern_codes",
        "relationship_ids",
        "incident_relationship_count",
    }
    baseline_by_case = {
        case: json.loads((BASELINE / case / "our-output.json").read_text())
        for case in ("component-datasheet", "settlement-agreement")
    }
    groups_by_case = {
        "component-datasheet": COMPONENT_GROUPS,
        "settlement-agreement": (SETTLEMENT_GROUP,),
    }
    for case, groups in groups_by_case.items():
        predecessor = baseline_by_case[case]
        _, ir = round_trip_document(predecessor)
        elements = {element.id: element for element in ir.elements}
        for group in groups:
            assert group["id"].startswith("outline-group-")
            assert group["element_id"].startswith("outline-element-")
            assert group["anchor_element_id"] in elements
            assert group["page_id"] == elements[group["anchor_element_id"]].page_id
            assert group["source_method"] == "native"
            assert group["confidence"] == {
                "scope": "evidence",
                "score": None,
                "unavailable_reason": "not_calibrated",
            }
            assert group["concern_codes"] == ()
            assert group["member_item_ids"] == tuple(
                node["id"] for node in group["nodes"]
            )
            assert group["member_element_ids"] == tuple(
                node["element_id"] for node in group["nodes"]
            )
            for node in group["nodes"]:
                assert required_node_fields <= set(node)
                public = _path_value(predecessor, node["source_public_path"])
                assert {
                    key: public["bbox"][key]
                    for key in ("x", "y", "width", "height", "unit")
                } == node["item_bbox"]
                assert public["source"] == node["source_method"] == "native"
                assert public["value"] == node["predecessor_value"]
                if node["marker_ownership"] == "separate":
                    assert public["marker"] == node["legacy_marker"]
                    assert node["body_text"] == node["predecessor_value"]
                    assert node["marker_separator"] == ""
                else:
                    assert node["legacy_marker"] is None
                    assert (
                        node["raw_marker"]
                        + node["marker_separator"]
                        + node["body_text"]
                        == node["predecessor_value"]
                    )
                element = elements[node["element_id"]]
                assert element.bbox_ids == [node["source_bbox_id"]]
                assert element.evidence_ids == list(node["source_evidence_ids"])
                assert node["source_object"] == {
                    "reader": "pdfplumber",
                    "page_index": 1,
                    "word_index": node["source_object"]["word_index"],
                }
                assert node["confidence"] == {
                    "scope": "evidence",
                    "score": None,
                    "unavailable_reason": "not_calibrated",
                }
                assert node["concern_codes"] == ()

    settlement = baseline_by_case["settlement-agreement"]
    continuation = SETTLEMENT_GROUP["continuations"][0]
    public_table = _path_value(settlement, continuation["source_public_path"])
    assert public_table["id"] == continuation["source_public_item_id"] == "p1-i4"
    assert public_table["type"] == continuation["source_type"] == "table"
    assert {
        key: public_table["bbox"][key] for key in ("x", "y", "width", "height", "unit")
    } == continuation["bbox"]
    _, settlement_ir = round_trip_document(settlement)
    table_element = next(
        element
        for element in settlement_ir.elements
        if element.id == continuation["element_id"]
    )
    assert table_element.bbox_ids == [continuation["bbox_id"]]
    assert table_element.evidence_ids == list(continuation["source_evidence_ids"])


def test_oracle_relationship_ids_metadata_backlinks_and_cardinality_are_exact() -> None:
    allowed_types = {
        "contains",
        "outline_parent_of",
        "outline_next",
        "outline_continuation_of",
    }
    all_ids: list[str] = []
    for group in (*COMPONENT_GROUPS, SETTLEMENT_GROUP):
        relationships = list(group["relationships"])
        relationship_ids = [relationship["id"] for relationship in relationships]
        assert relationship_ids == list(group["relationship_ids"])
        assert len(relationship_ids) == len(set(relationship_ids))
        all_ids.extend(relationship_ids)
        assert sum(group["relationship_cardinality"].values()) == len(relationships)
        for relationship in relationships:
            assert relationship["type"] in allowed_types
            assert relationship["id"].startswith("outline-relationship-")
            assert len(relationship["evidence_ids"]) >= 2
            metadata = relationship["metadata"]
            assert metadata["canonical_inert"] is True
            assert metadata["outline_group_id"] == group["id"]
            assert metadata["outline_policy"] == "p03-outline-structure-v1"
            if relationship["type"] == "outline_next":
                assert set(metadata) == {
                    "canonical_inert",
                    "outline_group_id",
                    "outline_policy",
                    "intervening_element_ids",
                }
            elif relationship["type"] == "outline_continuation_of":
                assert set(metadata) == {
                    "canonical_inert",
                    "outline_group_id",
                    "outline_policy",
                    "interstitial_kind",
                }
            else:
                assert set(metadata) == {
                    "canonical_inert",
                    "outline_group_id",
                    "outline_policy",
                }
        for node in group["nodes"]:
            expected = tuple(
                relationship["id"]
                for relationship in relationships
                if node["element_id"]
                in {relationship["source_id"], relationship["target_id"]}
            )
            assert node["relationship_ids"] == expected
            assert node["incident_relationship_count"] == len(expected)
        for continuation in group.get("continuations") or ():
            assert continuation["relationship_ids"] == tuple(
                relationship["id"]
                for relationship in relationships
                if relationship["source_id"] == continuation["element_id"]
                and relationship["type"] == "outline_continuation_of"
            )
    assert len(all_ids) == len(set(all_ids)) == 38


def test_oracle_denominators_and_relationships_are_internally_exact() -> None:
    component_counts = REVIEWED_COUNTS["component-datasheet"]
    component_nodes = _all_component_nodes()
    component_relationships = sum(
        (_relationship_counts(group) for group in COMPONENT_GROUPS),
        Counter(),
    )
    assert component_counts == {
        "group_count": 2,
        "node_count": 16,
        "level_zero_count": 11,
        "level_one_count": 5,
        "parent_relationship_count": 5,
        "next_relationship_count": 11,
        "continuation_relationship_count": 0,
        "contains_relationship_count": 16,
        "total_relationship_count": 32,
    }
    assert Counter(node["level"] for node in component_nodes) == Counter({0: 11, 1: 5})
    assert component_relationships == Counter(
        {
            "contains": 16,
            "outline_parent_of": 5,
            "outline_next": 11,
        }
    )

    settlement_counts = REVIEWED_COUNTS["settlement-agreement"]
    settlement_relationships = _relationship_counts(SETTLEMENT_GROUP)
    assert settlement_counts == {
        "group_count": 1,
        "node_count": 3,
        "level_zero_count": 3,
        "level_one_count": 0,
        "parent_relationship_count": 0,
        "next_relationship_count": 2,
        "continuation_relationship_count": 1,
        "contains_relationship_count": 3,
        "total_relationship_count": 6,
    }
    assert settlement_relationships == Counter(
        {
            "contains": 3,
            "outline_next": 2,
            "outline_continuation_of": 1,
        }
    )
    assert (
        sum(counts["total_relationship_count"] for counts in REVIEWED_COUNTS.values())
        == 38
    )


def test_readiness_fixture_registry_is_complete_unique_and_deterministic() -> None:
    self_check()
    hashes = fixture_hashes()
    assert len(SYNTHETIC_FIXTURES) == len(hashes) == 11
    assert len(set(hashes.values())) == 11
    assert len(REQUIRED_SYNTHETIC_COVERAGE) == 37
    assert oracle_sha256() == (
        "e3bddd0ce86ccbf1089b2e667b4b42922b41daaa20c5051634d21646d4f58bc5"
    )
    assert registry_sha256() == (
        "56d1ae95917de879b992030c7d8dddc4e03fada4e1b715974bdd4bde6a6e27c3"
    )


def test_readiness_registry_uses_strict_json_and_separate_nonfinite_witness() -> None:
    graph = build_synthetic_fixture("synthetic:p03-us07:graph-failures-v1")["payload"]
    json.dumps(graph, allow_nan=False, ensure_ascii=False, sort_keys=True)
    assert graph["malformed_bbox"]["x"] == {"invalid_number": "nan"}

    nonfinite = build_nonfinite_bbox_witness()
    assert math.isnan(nonfinite["x"])
    with pytest.raises(ValueError, match="Out of range float values"):
        json.dumps(nonfinite, allow_nan=False)


def test_every_frozen_count_and_byte_cap_has_exact_and_max_plus_one_witness() -> None:
    resource = build_synthetic_fixture("synthetic:p03-us07:resource-boundaries-v1")[
        "payload"
    ]
    expected_caps = {
        "maximum_source_characters_per_page",
        "maximum_source_characters_per_document",
        "maximum_source_words_per_page",
        "maximum_source_words_per_document",
        "maximum_marker_candidates_per_page",
        "maximum_marker_candidates_per_document",
        "maximum_marker_bytes",
        "maximum_item_text_bytes",
        "maximum_depth",
        "maximum_nodes_per_group",
        "maximum_groups_per_page",
        "maximum_groups_per_document",
        "maximum_nodes_per_page",
        "maximum_nodes_per_document",
        "maximum_interstitials_per_group",
        "maximum_relationships_per_page",
        "maximum_relationships_per_document",
        "maximum_comparisons_per_page",
        "maximum_public_group_bytes",
        "maximum_report_bytes",
        "maximum_concerns_per_page",
        "maximum_concerns_per_document",
    }
    assert set(resource["boundaries"]) == expected_caps
    for name in expected_caps:
        boundary = resource["boundaries"][name]
        assert boundary == {
            "exact": SYNTHETIC_THRESHOLDS[name],
            "maximum_plus_one": SYNTHETIC_THRESHOLDS[name] + 1,
        }
    assert resource["failure_injections"] == (
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
        "page_transaction",
        "document_transaction",
        "terminal_source_alignment_reentry",
    )


def test_every_readiness_pdf_opens_and_renders_with_both_local_readers() -> None:
    verify_pdf_readers()


def _canonical_context(
    case: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    predecessor = json.loads((BASELINE / case / "our-output.json").read_text())
    _, ir = round_trip_document(predecessor)
    presentation = build_canonical_presentation(ir).model_dump(
        mode="json",
        exclude_none=True,
    )
    blocks = {
        block["primary_element_id"]: block
        for page in presentation["pages"]
        for block in page["blocks"]
    }
    return presentation, blocks


def _canonical_block_for_group(
    group: dict[str, Any],
    presentation: dict[str, Any],
    blocks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    closure = canonical_closure(group, presentation)
    continuation_markdown = {
        value["element_id"]: blocks[value["element_id"]]["markdown"]
        for value in group.get("continuations") or ()
    }
    continuation_text = {
        value["element_id"]: blocks[value["element_id"]]["text"]
        for value in group.get("continuations") or ()
    }
    markdown, text = render_outline_group(
        group,
        continuation_markdown=continuation_markdown,
        continuation_text=continuation_text,
    )
    return {
        "id": closure.block_id,
        "page_id": closure.page_id,
        "primary_element_id": closure.primary_element_id,
        "primary_element_type": closure.primary_element_type,
        "scope": closure.scope,
        "markdown": markdown,
        "text": text,
        "contributing_element_ids": list(closure.contributing_element_ids),
        "relationship_ids": list(closure.relationship_ids),
        "excluded_contributions": [],
    }


def _public_sidecar_for_group(
    group: dict[str, Any],
    canonical_block: dict[str, Any],
) -> dict[str, Any]:
    relationships: list[dict[str, Any]] = []
    for value in group["relationships"]:
        metadata = value["metadata"]
        descriptor = {
            "id": value["id"],
            "type": value["type"],
            "source_id": value["source_id"],
            "target_id": value["target_id"],
            "evidence_ids": list(value["evidence_ids"]),
            "canonical_inert": metadata["canonical_inert"],
            "outline_group_id": metadata["outline_group_id"],
            "outline_policy": metadata["outline_policy"],
        }
        if value["type"] == "outline_next":
            descriptor["intervening_element_ids"] = list(
                metadata["intervening_element_ids"]
            )
        elif value["type"] == "outline_continuation_of":
            descriptor["interstitial_kind"] = metadata["interstitial_kind"]
        relationships.append(descriptor)

    continuations_by_target: dict[str, list[str]] = {}
    public_continuations: list[dict[str, Any]] = []
    for value in group.get("continuations") or ():
        continuations_by_target.setdefault(value["target_node_id"], []).append(
            value["id"]
        )
        public_continuations.append(
            {
                "id": value["id"],
                "element_id": value["element_id"],
                "source_public_item_id": value["source_public_item_id"],
                "source_public_path": list(value["source_public_path"]),
                "source_type": value["source_type"],
                "bbox_id": value["bbox_id"],
                "bbox": value["bbox"],
                "source_evidence_ids": list(value["source_evidence_ids"]),
                "target_node_id": value["target_node_id"],
                "source_method": value["source_method"],
                "confidence": value["confidence"],
                "concern_codes": list(value["concern_codes"]),
                "relationship_ids": list(value["relationship_ids"]),
            }
        )

    public_items = [
        {
            "id": node["id"],
            "element_id": node["element_id"],
            "source_public_item_id": node["source_public_item_id"],
            "source_public_path": list(node["source_public_path"]),
            "source_bbox_id": node["source_bbox_id"],
            "source_evidence_ids": [
                *node["source_evidence_ids"],
                node["marker_evidence_id"],
            ],
            "source_object": node["source_object"],
            "sequence_kind": node["sequence_kind"],
            "marker_style": node["marker_style"],
            "raw_marker": node["raw_marker"],
            "marker_bbox": node["marker_bbox"],
            "marker_ownership": node["marker_ownership"],
            "marker_separator": node["marker_separator"],
            "body_text": node["body_text"],
            "predecessor_value_sha256": node["value_sha256"],
            "level": node["level"],
            "ordinal": node["ordinal"],
            "parent_id": node["parent_id"],
            "marker_bbox_id": node["marker_bbox_id"],
            "marker_evidence_id": node["marker_evidence_id"],
            "source_method": node["source_method"],
            "confidence": node["confidence"],
            "concern_codes": list(node["concern_codes"]),
            "relationship_ids": list(node["relationship_ids"]),
            "continuation_ids": continuations_by_target.get(node["id"], []),
        }
        for node in group["nodes"]
    ]
    public_group = {
        "id": group["id"],
        "element_id": group["element_id"],
        "page_id": group["page_id"],
        "sequence_kind": group["sequence_kind"],
        "marker_style": group["marker_style"],
        "anchor_public_item_id": group["anchor_public_item_id"],
        "anchor_element_id": group["anchor_element_id"],
        "anchor_public_path": list(group["anchor_public_path"]),
        "group_bbox": group["group_bbox"],
        "member_item_ids": list(group["member_item_ids"]),
        "member_element_ids": list(group["member_element_ids"]),
        "continuation_ids": list(group["continuation_ids"]),
        "continuation_element_ids": list(group["continuation_element_ids"]),
        "relationship_ids": list(group["relationship_ids"]),
        "relationship_cardinality": group["relationship_cardinality"],
        "canonical_block_id": canonical_block["id"],
        "canonical_primary_element_id": canonical_block["primary_element_id"],
        "canonical_contributor_element_ids": canonical_block[
            "contributing_element_ids"
        ],
        "canonical_relationship_ids": canonical_block["relationship_ids"],
        "canonical_markdown_sha256": sha256_text(canonical_block["markdown"]),
        "canonical_text_sha256": sha256_text(canonical_block["text"]),
        "source_method": group["source_method"],
        "confidence": group["confidence"],
        "concern_codes": list(group["concern_codes"]),
    }
    return {
        "id": group["anchor_public_item_id"],
        "layout_outline_structure_projected": True,
        "outline_policy": "p03-outline-structure-v1",
        "outline_group": public_group,
        "outline_items": public_items,
        "outline_continuations": public_continuations,
        "relationships": relationships,
    }


def test_source_report_schema_counts_and_native_objects_are_executable() -> None:
    expected_counts = {
        "component-datasheet": (1_341, 226, 16),
        "settlement-agreement": (2_699, 444, 3),
    }
    for case, report in SOURCE_REPORTS.items():
        validate_source_report(report)
        source_path = WORKSPACE / SOURCE_IDENTITIES[case]["path"]
        with pdfplumber.open(source_path) as document:
            page = document.pages[0]
            assert (
                len(page.chars),
                len(page.extract_words()),
                len(report["pages"][0]["markers"]),
            ) == expected_counts[case]


def test_oracle_marker_and_group_bbox_evidence_records_are_resolved_ir() -> None:
    for case, groups in {
        "component-datasheet": COMPONENT_GROUPS,
        "settlement-agreement": (SETTLEMENT_GROUP,),
    }.items():
        predecessor = json.loads((BASELINE / case / "our-output.json").read_text())
        _, ir = round_trip_document(predecessor)
        resolved_evidence = {value.id for value in ir.evidence}
        added_evidence: set[str] = set()
        added_bboxes: set[str] = set()
        for group in groups:
            group_bbox = IRBoundingBox.model_validate(group["bbox_record"])
            group_evidence = EvidenceRecord.model_validate(group["evidence_record"])
            assert group_bbox.id == group["group_bbox_id"]
            assert group_bbox.role == "region"
            assert group_evidence.id == group["evidence_id"]
            assert group_evidence.element_id == group["element_id"]
            added_bboxes.add(group_bbox.id)
            added_evidence.add(group_evidence.id)
            for node in group["nodes"]:
                marker_bbox = IRBoundingBox.model_validate(node["marker_bbox_record"])
                marker_evidence = EvidenceRecord.model_validate(
                    node["marker_evidence_record"]
                )
                assert marker_bbox.id == node["marker_bbox_id"]
                assert marker_bbox.role == "annotation"
                assert marker_evidence.id == node["marker_evidence_id"]
                assert marker_evidence.element_id == node["element_id"]
                assert marker_evidence.value == node["raw_marker"]
                added_bboxes.add(marker_bbox.id)
                added_evidence.add(marker_evidence.id)
        assert len(added_bboxes) == sum(len(group["nodes"]) + 1 for group in groups)
        assert len(added_evidence) == len(added_bboxes)
        for group in groups:
            for relationship in group["relationships"]:
                assert set(relationship["evidence_ids"]) <= (
                    resolved_evidence | added_evidence
                )


def test_group_element_contract_and_page_region_membership_are_exact() -> None:
    for case, groups in {
        "component-datasheet": COMPONENT_GROUPS,
        "settlement-agreement": (SETTLEMENT_GROUP,),
    }.items():
        predecessor = json.loads((BASELINE / case / "our-output.json").read_text())
        _, ir = round_trip_document(predecessor)
        presentation = build_canonical_presentation(ir).model_dump(
            mode="json",
            exclude_none=True,
        )
        for group in groups:
            closure = canonical_closure(group, presentation)
            record = build_group_element_contract(group, closure)
            assert record["type"] == "outline_group"
            assert (
                record["reading_order"] is record["value"] is record["markdown"] is None
            )
            assert record["bbox_ids"] == [group["group_bbox_id"]]
            assert record["evidence_ids"] == [group["evidence_id"]]
            assert record["presentation_role"] == "subordinate"
            assert record["presentation"] == {
                "include_subordinate_ocr": None,
                "accepted": None,
            }
            assert record["properties"] == {
                "outline_policy": "p03-outline-structure-v1",
                "public_anchor_element_id": group["anchor_element_id"],
            }
            page = next(value for value in ir.pages if value.id == group["page_id"])
            assert record["id"] not in page.element_ids
            assert record["id"] not in page.presentation_element_ids
            regions = [
                value
                for value in ir.regions
                if group["anchor_element_id"] in value.element_ids
            ]
            assert len(regions) == 1
            projected_page_ids = [*page.element_ids, record["id"]]
            projected_region_ids = [*regions[0].element_ids, record["id"]]
            assert projected_page_ids.count(record["id"]) == 1
            assert projected_region_ids.count(record["id"]) == 1


def test_closed_schema_enums_cardinality_and_v1_scope_are_frozen() -> None:
    assert MARKER_STYLES == ("bullet", "decimal", "lower_alpha")
    assert INTERSTITIAL_TYPES == ("table",)
    assert len(CONCERN_CODES) == 11
    assert len(IR_GROUP_DESCRIPTOR_FIELDS) == 13
    assert len(IR_ITEM_DESCRIPTOR_FIELDS) == 19
    assert len(PUBLIC_GROUP_FIELDS) == 24
    assert len(PUBLIC_ITEM_FIELDS) == 25
    assert len(PUBLIC_CONTINUATION_FIELDS) == 13
    assert INCIDENT_CARDINALITY["group_element"]["contains_out"] == (2, 256)
    assert INCIDENT_CARDINALITY["root_item"]["total"] == (1, 322)
    assert INCIDENT_CARDINALITY["nested_item"]["total"] == (2, 323)
    assert INCIDENT_CARDINALITY["continuation"]["total"] == (1, 1)


def test_resource_measurement_primitives_execute_at_all_22_boundaries() -> None:
    resource = build_synthetic_fixture("synthetic:p03-us07:resource-boundaries-v1")[
        "payload"
    ]
    for counter in resource["boundaries"]:
        exact = build_resource_boundary_witness(counter)
        assert exact.measure() == exact.limit
        assert exact.execute() is True
        over = build_resource_boundary_witness(counter, maximum_plus_one=True)
        assert over.measure() == over.limit + 1
        assert over.execute() is False
    depth = build_resource_boundary_witness("maximum_depth")
    assert depth.observed == 8  # valid levels are exactly 0 through 7


def test_injected_deadlines_have_distinct_inclusive_and_overflow_witnesses() -> None:
    for name in (
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
    ):
        assert build_deadline_witness(name).execute() is True
        assert build_deadline_witness(name, maximum_plus_one=True).execute() is False


def test_processing_summary_and_terminal_timing_combination_are_exact() -> None:
    initial = {
        "policy_id": "p03-outline-structure-v1",
        "status": "projected",
        "reason": None,
        "group_count": 3,
        "node_count": 19,
        "relationship_count": 38,
        "concern_count": 0,
        "extraction_ms": 4.125,
        "projection_ms": 2.25,
        "total_ms": 6.375,
    }
    terminal = {
        **initial,
        "extraction_ms": 0.0,
        "projection_ms": 1.5,
        "total_ms": 1.5,
    }
    validate_processing_summary(initial)
    validate_processing_summary(terminal)
    combined = combine_terminal_processing_summaries(initial, terminal)
    assert combined == {
        **terminal,
        "extraction_ms": 4.125,
        "projection_ms": 3.75,
        "total_ms": 7.875,
    }


def test_real_predecessor_canonical_closure_and_byte_grammar_are_exact() -> None:
    for case, groups in {
        "component-datasheet": COMPONENT_GROUPS,
        "settlement-agreement": (SETTLEMENT_GROUP,),
    }.items():
        presentation, blocks = _canonical_context(case)
        for group in groups:
            expected = CANONICAL_EXPECTATIONS[group["oracle_id"]]
            closure = canonical_closure(group, presentation)
            block = _canonical_block_for_group(group, presentation, blocks)
            assert closure.block_id == expected["block_id"]
            assert closure.page_id == expected["page_id"]
            assert closure.primary_element_id == expected["primary_element_id"]
            assert closure.primary_element_type == expected["primary_element_type"]
            assert closure.scope == expected["scope"]
            assert (
                closure.predecessor_primary_ids == expected["predecessor_primary_ids"]
            )
            assert (
                closure.contributing_element_ids == expected["contributing_element_ids"]
            )
            assert (
                closure.predecessor_relationship_ids
                == expected["predecessor_relationship_ids"]
            )
            assert closure.relationship_ids == expected["relationship_ids"]
            assert len(block["markdown"].encode()) == expected["markdown_bytes"]
            assert sha256_text(block["markdown"]) == expected["markdown_sha256"]
            assert len(block["text"].encode()) == expected["text_bytes"]
            assert sha256_text(block["text"]) == expected["text_sha256"]
            assert block["contributing_element_ids"][0] == group["anchor_element_id"]
            assert group["element_id"] not in block["contributing_element_ids"]
            assert set(group["member_element_ids"]) <= set(
                block["contributing_element_ids"]
            )
            assert block["relationship_ids"] == sorted(block["relationship_ids"])
            assert "<script" not in block["markdown"].casefold()

    _, settlement_blocks = _canonical_context("settlement-agreement")
    table = settlement_blocks[SETTLEMENT_CONTINUATION_CANONICAL["primary_element_id"]]
    continuation = SETTLEMENT_CONTINUATION_CANONICAL
    assert table["id"] == continuation["block_id"]
    assert table["contributing_element_ids"] == list(
        continuation["contributing_element_ids"]
    )
    assert table["relationship_ids"] == list(continuation["relationship_ids"])
    assert len(table["markdown"].encode()) == continuation["markdown_bytes"]
    assert sha256_text(table["markdown"]) == continuation["markdown_sha256"]
    assert len(table["text"].encode()) == continuation["text_bytes"]
    assert sha256_text(table["text"]) == continuation["text_sha256"]


def test_public_validator_strip_reentry_and_failure_transactions_are_executable() -> (
    None
):
    presentation, blocks = _canonical_context("settlement-agreement")
    canonical_block = _canonical_block_for_group(
        SETTLEMENT_GROUP,
        presentation,
        blocks,
    )
    anchor = _public_sidecar_for_group(SETTLEMENT_GROUP, canonical_block)
    validate_public_sidecar(anchor, canonical_block)
    oversized = json.loads(json.dumps(anchor))
    oversized["relationships"][0]["evidence_ids"][0] = "x" * (512 * 1024)
    with pytest.raises(ValueError, match="complete outline sidecar exceeds byte cap"):
        validate_public_sidecar(oversized, canonical_block)

    predecessor = {"pages": [{"items": [{"id": anchor["id"], "type": "text"}]}]}
    projected = json.loads(json.dumps(predecessor))
    projected["pages"][0]["items"][0].update(anchor)
    projected["canonical_presentation"] = {"pages": [{"blocks": [canonical_block]}]}
    stripped = strip_complete_outline_sidecars(projected)
    stripped.pop("canonical_presentation")
    assert stripped == predecessor

    malformed = json.loads(json.dumps(projected))
    malformed["pages"][0]["items"][0]["outline_group"].pop("canonical_text_sha256")
    assert strip_complete_outline_sidecars(malformed) == malformed

    component_presentation, component_blocks = _canonical_context("component-datasheet")
    component_group = COMPONENT_GROUPS[0]
    component_block = _canonical_block_for_group(
        component_group,
        component_presentation,
        component_blocks,
    )
    component = json.loads(
        (BASELINE / "component-datasheet" / "our-output.json").read_text()
    )
    component_anchor = _path_value(component, component_group["anchor_public_path"])
    legacy_nested = json.loads(json.dumps(component_anchor["items"]))
    component_anchor.update(_public_sidecar_for_group(component_group, component_block))
    component["canonical_presentation"] = {"pages": [{"blocks": [component_block]}]}
    component_stripped = strip_complete_outline_sidecars(component)
    assert component_stripped["pages"][0]["items"][6]["items"] == legacy_nested

    assert terminal_reentry_order(forms_enabled=True) == (
        "snapshot",
        "strip_outline",
        "strip_forms",
        "drop_canonical",
        "round_trip_once",
        "replay_forms",
        "replay_outline",
        "validate_final_ir",
        "canonical_dry_run",
        "commit",
    )

    transaction_predecessor = {"pages": [{"items": [{"id": "p1-i1"}]}]}
    for outcome in ("page_failure", "document_failure", "canonical_failure"):
        result = execute_transaction_witness(
            transaction_predecessor,
            outcome=outcome,
        )
        assert result.committed is False
        restored = dict(result.payload)
        restored.pop("outline_concerns")
        assert restored == transaction_predecessor
    success = execute_transaction_witness(transaction_predecessor, outcome="success")
    assert success.committed is True
    assert success.events[-2:] == ("canonical_dry_run", "commit")


def test_canonical_closure_rejects_form_overlap_before_mutation() -> None:
    presentation, _ = _canonical_context("component-datasheet")
    group = COMPONENT_GROUPS[0]
    with pytest.raises(ValueError, match="overlaps form ownership"):
        canonical_closure(
            group,
            presentation,
            form_owned_element_ids=(group["member_element_ids"][0],),
        )
