from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
import app.services.ir as ir_module
from app.services.ir import (
    DocumentIR,
    TextColorRecord,
    build_document_ir,
    round_trip_document,
)


SOURCE_SHA256 = "1" * 64


def _item(
    identifier: str,
    value: str,
    *,
    reading_order: int,
    x: float,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": "heading",
        "reading_order": reading_order,
        "value": value,
        "md": f"# {value}",
        "bbox": {
            "x": x,
            "y": 30.0,
            "width": 220.0,
            "height": 20.0,
            "unit": "pt",
        },
        "source": "native",
        "confidence": None,
    }


def _document() -> dict[str, Any]:
    owner = _item(
        "p1-i1",
        "Draft of 6/1/20",
        reading_order=0,
        x=40.0,
    )
    owner["cells"] = [
        {
            "text": "Cell text",
            "bbox": {
                "x": 40.0,
                "y": 60.0,
                "width": 80.0,
                "height": 14.0,
                "unit": "pt",
            },
            "source": "native",
        }
    ]
    owner["items"] = [
        {
            "value": "Nested value",
            "text": "Nested text",
            "bbox": {
                "x": 130.0,
                "y": 60.0,
                "width": 100.0,
                "height": 14.0,
                "unit": "pt",
            },
            "source": "native",
        }
    ]
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "redline.pdf",
            "mime_type": "application/pdf",
            "sha256": SOURCE_SHA256,
            "page_count": 2,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [owner],
                "warnings": [],
            },
            {
                "page_index": 2,
                "page_number": 2,
                "page_label": "2",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    _item(
                        "p2-i1",
                        "Other page",
                        reading_order=0,
                        x=40.0,
                    )
                ],
                "warnings": [],
            },
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
            "warnings": [],
        },
    }


def _valid_payload() -> dict[str, Any]:
    payload = build_document_ir(_document()).model_dump(mode="json")
    first_page = payload["pages"][0]
    owner_id = first_page["presentation_element_ids"][0]
    owner = next(
        element
        for element in payload["elements"]
        if element["id"] == owner_id
    )
    bbox_id = owner["bbox_ids"][0]
    owner_bbox = next(
        bbox for bbox in payload["bboxes"] if bbox["id"] == bbox_id
    )
    rule_bbox = deepcopy(owner_bbox)
    rule_bbox.update(
        {
            "id": "text-rule-box-1",
            "y": 38.0,
            "width": 220.0,
            "height": 0.5,
            "role": "field",
        }
    )
    payload["bboxes"].append(rule_bbox)
    target = owner["properties"]["legacy_item"]["value"]
    rule_id = "text-rule-1"
    run_id = "text-run-1"
    payload["text_rules"] = [
        {
            "id": rule_id,
            "source_sha256": SOURCE_SHA256,
            "page_id": first_page["id"],
            "bbox_id": rule_bbox["id"],
            "source_object_kind": "rect",
            "source_object_index": 0,
            "color": {
                "space": "rgb",
                "components": [1.0, 0.0, 0.0],
                "raw_value": [1.0, 0.0, 0.0],
            },
            "width": 220.0,
            "thickness": 0.5,
            "evidence_method": "vector",
            "extraction_policy_id": "p03-text-run-extraction-v1",
        }
    ]
    payload["text_runs"] = [
        {
            "id": run_id,
            "source_sha256": SOURCE_SHA256,
            "page_id": first_page["id"],
            "element_id": owner_id,
            "target_path": ["value"],
            "target_text_sha256": hashlib.sha256(
                target.encode("utf-8")
            ).hexdigest(),
            "change_group_id": "change-group-1",
            "text": "Draft",
            "source_text": "Draft",
            "start": 0,
            "end": 5,
            "bbox_id": bbox_id,
            "font_size": 12.0,
            "font_name": "TimesNewRomanPSMT",
            "bold": False,
            "italic": False,
            "color": {
                "space": "rgb",
                "components": [1.0, 0.0, 0.0],
                "raw_value": [1.0, 0.0, 0.0],
            },
            "source_character_indexes": [0, 1, 2, 3, 4],
            "change_state": "deleted",
            "decorations": ["strikethrough"],
            "placeholder": False,
            "rule_ids": [rule_id],
            "evidence_ids": [owner["evidence_ids"][0]],
            "evidence_method": "vector",
            "semantic_derivation": "same_color_midline_rule",
            "extraction_policy_id": "p03-text-run-extraction-v1",
            "association_policy_id": "p03-text-run-association-v1",
        }
    ]
    run_evidence = next(
        evidence
        for evidence in payload["evidence"]
        if evidence["id"] == owner["evidence_ids"][0]
    )
    run_evidence["method"] = "vector"
    owner["text_run_ids"] = [run_id]
    return payload


def _owner(payload: dict[str, Any]) -> dict[str, Any]:
    owner_id = payload["pages"][0]["presentation_element_ids"][0]
    return next(
        element
        for element in payload["elements"]
        if element["id"] == owner_id
    )


def _second_page_owner(payload: dict[str, Any]) -> dict[str, Any]:
    owner_id = payload["pages"][1]["presentation_element_ids"][0]
    return next(
        element
        for element in payload["elements"]
        if element["id"] == owner_id
    )


def _retarget(
    payload: dict[str, Any],
    path: list[str | int],
    target: str,
    *,
    text: str,
) -> None:
    run = payload["text_runs"][0]
    run["target_path"] = path
    run["target_text_sha256"] = hashlib.sha256(
        target.encode("utf-8")
    ).hexdigest()
    run["text"] = text
    run["source_text"] = text
    run["start"] = 0
    run["end"] = len(text)
    run["source_character_indexes"] = list(range(len(text)))


def test_existing_ir_ingests_with_empty_text_semantic_defaults() -> None:
    ir = build_document_ir(
        _document(),
        text_run_evidence={"ignored_without_projection": True},
    )
    assert ir.text_rules == []
    assert ir.text_runs == []
    assert all(element.text_run_ids == [] for element in ir.elements)

    prior_payload = ir.model_dump(mode="json")
    assert "text_rules" not in prior_payload
    assert "text_runs" not in prior_payload
    for element in prior_payload["elements"]:
        assert "text_run_ids" not in element
    validated = DocumentIR.model_validate(prior_payload)
    assert validated.text_rules == []
    assert validated.text_runs == []
    assert all(element.text_run_ids == [] for element in validated.elements)


def test_valid_text_semantics_graph_round_trips_strictly() -> None:
    validated = DocumentIR.model_validate(_valid_payload())
    assert validated.text_runs[0].target_path == ("value",)
    assert validated.text_rules[0].evidence_method.value == "vector"
    assert (
        DocumentIR.model_validate(validated.model_dump(mode="json"))
        == validated
    )

    extra = _valid_payload()
    extra["text_runs"][0]["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        DocumentIR.model_validate(extra)


@pytest.mark.parametrize(
    ("path", "target", "text"),
    [
        (["value"], "Draft of 6/1/20", "Draft"),
        (["cells", 0, "text"], "Cell text", "Cell"),
        (["items", 0, "value"], "Nested value", "Nested"),
        (["items", 0, "text"], "Nested text", "Nested"),
    ],
)
def test_allowlisted_target_paths_resolve_exact_public_slots(
    path: list[str | int],
    target: str,
    text: str,
) -> None:
    payload = _valid_payload()
    _retarget(payload, path, target, text=text)
    assert DocumentIR.model_validate(payload).text_runs[0].text == text


@pytest.mark.parametrize(
    "path",
    [
        [],
        ["md"],
        ["cells", -1, "text"],
        ["cells", 0, "value"],
        ["items", 0, "md"],
        ["items", True, "text"],
        ["items", 0, "text", "extra"],
    ],
)
def test_nonallowlisted_target_paths_are_rejected(
    path: list[str | int | bool],
) -> None:
    payload = _valid_payload()
    payload["text_runs"][0]["target_path"] = path
    with pytest.raises(ValidationError):
        DocumentIR.model_validate(payload)


def test_target_child_requires_finite_same_page_bbox() -> None:
    payload = _valid_payload()
    owner = _owner(payload)
    target = owner["properties"]["legacy_item"]["cells"][0]["text"]
    _retarget(payload, ["cells", 0, "text"], target, text="Cell")
    owner["properties"]["legacy_item"]["cells"][0]["bbox"]["width"] = float(
        "nan"
    )
    with pytest.raises(ValidationError, match="target child.*invalid bbox"):
        DocumentIR.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "run_source",
        "rule_source",
        "dangling_rule",
        "dangling_evidence",
        "cross_page_run_bbox",
        "cross_page_rule",
        "cross_page_evidence",
        "missing_inverse",
        "dangling_inverse",
        "duplicate_graph_id",
    ],
)
def test_graph_rejects_unbound_or_cross_page_records(mutation: str) -> None:
    payload = _valid_payload()
    run = payload["text_runs"][0]
    rule = payload["text_rules"][0]
    owner = _owner(payload)
    second_page = payload["pages"][1]
    second_owner = _second_page_owner(payload)

    if mutation == "run_source":
        run["source_sha256"] = "2" * 64
    elif mutation == "rule_source":
        rule["source_sha256"] = "2" * 64
    elif mutation == "dangling_rule":
        run["rule_ids"] = ["missing-rule"]
    elif mutation == "dangling_evidence":
        run["evidence_ids"] = ["missing-evidence"]
    elif mutation == "cross_page_run_bbox":
        run["bbox_id"] = second_owner["bbox_ids"][0]
    elif mutation == "cross_page_rule":
        rule["page_id"] = second_page["id"]
        rule["bbox_id"] = second_owner["bbox_ids"][0]
    elif mutation == "cross_page_evidence":
        run["evidence_ids"] = [second_owner["evidence_ids"][0]]
    elif mutation == "missing_inverse":
        owner["text_run_ids"] = []
    elif mutation == "dangling_inverse":
        owner["text_run_ids"] = ["missing-run"]
    elif mutation == "duplicate_graph_id":
        rule["id"] = run["id"]
        run["rule_ids"] = [run["id"]]

    with pytest.raises(ValidationError):
        DocumentIR.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    ["digest", "slice", "bounds", "source_order", "font_bytes"],
)
def test_run_local_integrity_is_strict(mutation: str) -> None:
    payload = _valid_payload()
    run = payload["text_runs"][0]
    if mutation == "digest":
        run["target_text_sha256"] = "2" * 64
    elif mutation == "slice":
        run["text"] = "DraFt"
    elif mutation == "bounds":
        run["end"] = 200
    elif mutation == "source_order":
        run["source_character_indexes"] = [0, 2, 1, 3, 4]
    elif mutation == "font_bytes":
        run["font_name"] = "é" * 129
    with pytest.raises(ValidationError):
        DocumentIR.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("change_state", "replacement"),
        ("decorations", ["underline"]),
        ("decorations", ["strikethrough", "underline"]),
        ("placeholder", True),
        ("semantic_derivation", "source_style"),
        ("evidence_method", "native"),
        ("extraction_policy_id", "wrong-extraction-policy"),
        ("association_policy_id", "wrong-association-policy"),
        ("evidence_ids", []),
    ],
)
def test_run_state_derivation_and_evidence_method_are_coherent(
    field: str,
    value: Any,
) -> None:
    payload = _valid_payload()
    payload["text_runs"][0][field] = value
    with pytest.raises(ValidationError):
        DocumentIR.model_validate(payload)


@pytest.mark.parametrize("mutation", ["element", "bbox", "method"])
def test_run_evidence_matches_its_element_bbox_and_method(
    mutation: str,
) -> None:
    payload = _valid_payload()
    run = payload["text_runs"][0]
    owner = _owner(payload)
    evidence = next(
        record
        for record in payload["evidence"]
        if record["id"] == run["evidence_ids"][0]
    )
    if mutation == "element":
        child = next(
            element
            for element in payload["elements"]
            if element["properties"].get("parent_element_id") == owner["id"]
        )
        owner["evidence_ids"].remove(evidence["id"])
        child["evidence_ids"].append(evidence["id"])
        evidence["element_id"] = child["id"]
    elif mutation == "bbox":
        evidence["bbox_id"] = payload["text_rules"][0]["bbox_id"]
    else:
        evidence["method"] = "native"
    with pytest.raises(ValidationError, match=f"evidence .*{mutation}"):
        DocumentIR.model_validate(payload)


def test_source_style_state_and_placeholder_source_text_are_exact() -> None:
    source_style = _valid_payload()
    run = source_style["text_runs"][0]
    run.update(
        {
            "change_group_id": None,
            "change_state": "unknown",
            "decorations": [],
            "rule_ids": [],
            "evidence_method": "native",
            "semantic_derivation": "source_style",
        }
    )
    source_style["text_rules"] = []
    run_evidence = next(
        record
        for record in source_style["evidence"]
        if record["id"] == run["evidence_ids"][0]
    )
    run_evidence["method"] = "native"
    assert DocumentIR.model_validate(source_style).text_runs[0].change_state == (
        "unknown"
    )
    source_style["text_runs"][0]["change_state"] = "unchanged"
    with pytest.raises(ValidationError, match="source-style"):
        DocumentIR.model_validate(source_style)

    placeholder = _valid_payload()
    owner = _owner(placeholder)
    owner["value"] = "___"
    owner["properties"]["legacy_item"]["value"] = "___"
    owner["properties"]["legacy_item"]["md"] = "# ___"
    run = placeholder["text_runs"][0]
    run.update(
        {
            "target_text_sha256": hashlib.sha256(b"___").hexdigest(),
            "text": "___",
            "source_text": "__x",
            "start": 0,
            "end": 3,
            "source_character_indexes": [0, 1, 2],
            "change_state": "unknown",
            "decorations": ["underline"],
            "placeholder": True,
            "semantic_derivation": "same_color_underlined_placeholder",
        }
    )
    with pytest.raises(ValidationError, match="underlined-placeholder"):
        DocumentIR.model_validate(placeholder)


def test_rule_geometry_color_order_and_exact_link_union_are_strict() -> None:
    dimensions = _valid_payload()
    dimensions["text_rules"][0]["width"] += 1.0
    with pytest.raises(ValidationError, match="dimensions disagree"):
        DocumentIR.model_validate(dimensions)

    color = _valid_payload()
    color["text_rules"][0]["color"]["components"] = [0.0, 0.0, 1.0]
    with pytest.raises(ValidationError, match="incompatible color"):
        DocumentIR.model_validate(color)

    out_of_order = _valid_payload()
    second_rule = deepcopy(out_of_order["text_rules"][0])
    second_rule["id"] = "text-rule-2"
    second_rule["source_object_index"] = 1
    second_bbox = next(
        deepcopy(bbox)
        for bbox in out_of_order["bboxes"]
        if bbox["id"] == second_rule["bbox_id"]
    )
    second_bbox["id"] = "text-rule-box-2"
    second_bbox["y"] -= 1.0
    out_of_order["bboxes"].append(second_bbox)
    second_rule["bbox_id"] = second_bbox["id"]
    out_of_order["text_rules"].append(second_rule)
    out_of_order["text_runs"][0]["rule_ids"].append(second_rule["id"])
    with pytest.raises(ValidationError, match="canonical bbox order"):
        DocumentIR.model_validate(out_of_order)

    unlinked = _valid_payload()
    second_rule = deepcopy(unlinked["text_rules"][0])
    second_rule["id"] = "text-rule-unlinked"
    second_rule["source_object_index"] = 1
    second_bbox = next(
        deepcopy(bbox)
        for bbox in unlinked["bboxes"]
        if bbox["id"] == second_rule["bbox_id"]
    )
    second_bbox["id"] = "text-rule-box-unlinked"
    second_bbox["y"] += 1.0
    unlinked["bboxes"].append(second_bbox)
    second_rule["bbox_id"] = second_bbox["id"]
    unlinked["text_rules"].append(second_rule)
    with pytest.raises(ValidationError, match="not linked"):
        DocumentIR.model_validate(unlinked)


def test_ir_document_and_page_semantic_collection_caps_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = DocumentIR.model_json_schema()["properties"]
    assert schema["text_runs"]["maxItems"] == 10_000
    assert schema["text_rules"]["maxItems"] == 10_000
    assert ir_module._MAX_TEXT_RUNS_PER_PAGE == 4_096
    assert ir_module._MAX_TEXT_RULES_PER_PAGE == 4_096

    monkeypatch.setattr(ir_module, "_MAX_TEXT_RUNS_PER_PAGE", 0)
    with pytest.raises(ValidationError, match="run limit"):
        DocumentIR.model_validate(_valid_payload())

    monkeypatch.setattr(ir_module, "_MAX_TEXT_RUNS_PER_PAGE", 4_096)
    monkeypatch.setattr(ir_module, "_MAX_TEXT_RULES_PER_PAGE", 0)
    with pytest.raises(ValidationError, match="rule limit"):
        DocumentIR.model_validate(_valid_payload())


def test_semantic_and_target_bboxes_must_be_inside_and_match_the_ir() -> None:
    outside = _valid_payload()
    run = outside["text_runs"][0]
    evidence = next(
        record
        for record in outside["evidence"]
        if record["id"] == run["evidence_ids"][0]
    )
    run_bbox = next(
        deepcopy(bbox)
        for bbox in outside["bboxes"]
        if bbox["id"] == run["bbox_id"]
    )
    run_bbox.update({"id": "outside-run-box", "x": 700.0})
    outside["bboxes"].append(run_bbox)
    run["bbox_id"] = run_bbox["id"]
    evidence["bbox_id"] = run_bbox["id"]
    with pytest.raises(ValidationError, match="outside its page extent"):
        DocumentIR.model_validate(outside)

    owner_mismatch = _valid_payload()
    _owner(owner_mismatch)["properties"]["legacy_item"]["bbox"]["x"] += 1.0
    with pytest.raises(ValidationError, match="owner bbox disagrees"):
        DocumentIR.model_validate(owner_mismatch)

    child_mismatch = _valid_payload()
    owner = _owner(child_mismatch)
    target = owner["properties"]["legacy_item"]["cells"][0]["text"]
    _retarget(
        child_mismatch,
        ["cells", 0, "text"],
        target,
        text="Cell",
    )
    owner["properties"]["legacy_item"]["cells"][0]["bbox"]["x"] += 1.0
    with pytest.raises(ValidationError, match="child bbox disagrees"):
        DocumentIR.model_validate(child_mismatch)


@pytest.mark.parametrize("target_kind", ["owner", "child"])
def test_target_geometry_allows_additional_non_page_space_bboxes(
    target_kind: str,
) -> None:
    payload = _valid_payload()
    owner = _owner(payload)
    page = payload["pages"][0]
    target_element = owner
    if target_kind == "child":
        target = owner["properties"]["legacy_item"]["cells"][0]["text"]
        _retarget(
            payload,
            ["cells", 0, "text"],
            target,
            text="Cell",
        )
        target_element = next(
            element
            for element in payload["elements"]
            if element["properties"].get("parent_element_id") == owner["id"]
            and element["properties"].get("collection") == "cells"
            and element["properties"].get("index") == 0
        )

    raw_coordinate = deepcopy(payload["coordinate_systems"][0])
    raw_coordinate.update(
        {
            "id": f"raw-coordinate-{target_kind}",
            "page_id": page["id"],
            "unit": "px",
        }
    )
    payload["coordinate_systems"].append(raw_coordinate)
    source_bbox = next(
        bbox
        for bbox in payload["bboxes"]
        if bbox["id"] == target_element["bbox_ids"][0]
    )
    raw_bbox = deepcopy(source_bbox)
    raw_bbox.update(
        {
            "id": f"raw-bbox-{target_kind}",
            "coordinate_system_id": raw_coordinate["id"],
        }
    )
    payload["bboxes"].append(raw_bbox)
    target_element["bbox_ids"].append(raw_bbox["id"])

    assert DocumentIR.model_validate(payload).text_runs


@pytest.mark.parametrize("mutation", ["gap", "semantics"])
def test_change_groups_are_adjacent_and_semantically_coherent(
    mutation: str,
) -> None:
    payload = _valid_payload()
    first = payload["text_runs"][0]
    second = deepcopy(first)
    second.update(
        {
            "id": "text-run-2",
            "text": "of" if mutation == "gap" else " of",
            "source_text": "of" if mutation == "gap" else " of",
            "start": 6 if mutation == "gap" else 5,
            "end": 8,
            "source_character_indexes": (
                [5, 6] if mutation == "gap" else [5, 6, 7]
            ),
        }
    )
    if mutation == "semantics":
        second.update(
            {
                "change_state": "unchanged",
                "decorations": ["underline"],
                "semantic_derivation": "same_color_underline_rule",
            }
        )
    payload["text_runs"].append(second)
    _owner(payload)["text_run_ids"].append(second["id"])
    expected = "not adjacent" if mutation == "gap" else "incoherent"
    with pytest.raises(ValidationError, match=expected):
        DocumentIR.model_validate(payload)


def test_intervals_are_ordered_and_nonoverlapping_per_target() -> None:
    payload = _valid_payload()
    second = deepcopy(payload["text_runs"][0])
    second.update(
        {
            "id": "text-run-2",
            "change_group_id": "change-group-2",
            "text": "t of",
            "source_text": "t of",
            "start": 4,
            "end": 8,
            "source_character_indexes": [5, 6, 7, 8],
        }
    )
    payload["text_runs"].append(second)
    _owner(payload)["text_run_ids"].append(second["id"])
    with pytest.raises(ValidationError, match="overlaps or precedes"):
        DocumentIR.model_validate(payload)


@pytest.mark.parametrize(
    "color",
    [
        {"space": "rgb", "components": [1.0, 0.0]},
        {"space": "gray", "components": [1.1]},
        {"space": "cmyk", "components": [0.0, 0.0, 0.0, float("nan")]},
        {
            "space": "unknown",
            "components": [0.0],
            "raw_value": "unknown",
        },
        {
            "space": "rgb",
            "components": [1.0, 0.0, 0.0],
            "raw_value": [1.0, 2.0, 3.0, 4.0, 5.0],
        },
    ],
)
def test_color_shape_range_and_raw_value_are_bounded(
    color: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        TextColorRecord.model_validate(color)


def test_config_flag_defaults_false_reads_env_and_requires_predecessors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().layout_text_run_semantics_enabled is False
    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_CANONICAL_SERIALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED", "true")
    monkeypatch.setenv("PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED", "true")
    assert Settings.from_env().layout_text_run_semantics_enabled is True

    enabled = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "layout_relationship_order_enabled": True,
        "layout_text_run_semantics_enabled": True,
    }
    for dependency in (
        "shared_ir_normalization_enabled",
        "canonical_serialization_enabled",
        "layout_relationship_order_enabled",
    ):
        invalid = {**enabled, dependency: False}
        with pytest.raises(ValueError):
            Settings(**invalid)


def test_round_trip_forwards_evidence_only_to_layout_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = {"source_sha256": SOURCE_SHA256, "runs": []}
    captured: dict[str, Any] = {}

    def fake_projection(
        ir: DocumentIR,
        settings: object,
        *,
        text_run_evidence: dict[str, Any] | None,
    ) -> DocumentIR:
        captured["settings"] = settings
        captured["evidence"] = text_run_evidence
        return ir

    import app.services.layout as layout

    monkeypatch.setattr(layout, "apply_layout_projection", fake_projection)
    settings = object()
    public, ir = round_trip_document(
        _document(),
        text_run_evidence=evidence,
        layout_settings=settings,
    )
    assert captured == {"settings": settings, "evidence": evidence}
    assert ir.text_runs == []
    assert public["pages"] == _document()["pages"]
