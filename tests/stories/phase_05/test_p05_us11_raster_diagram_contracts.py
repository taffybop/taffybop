from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any

import pytest
from pydantic import ValidationError

import app.services.visual_raster_diagram as raster_diagram
from app.config import Settings
from app.models import ContentItem
from app.services.input_documents import InputKind
from app.services.ir import build_document_ir, round_trip_document
from app.services.presentation import build_canonical_presentation
from app.services.visual_contracts import (
    DiagramConnector,
    DiagramNode,
    VisualBoundingBox,
    VisualConfidenceDimensions,
    VisualLabel,
)
from app.services.visual_diagram_topology import (
    _build_raster_markdown,
    structure_diagram_topology,
)
from app.services.visual_raster_diagram import (
    bind_raster_diagram_owner,
    derive_raster_diagram_topology_evidence,
)
from app.services.visual_semantics import apply_visual_semantics, build_visual_fallback
from tests.stories.phase_05.test_p05_us01_visual_schema import _payload
from tests.stories.phase_05.test_p05_us11_raster_diagram import (
    _diagram,
    _direct_image_flow,
    _edit_png,
    _line,
    _owner,
    _sync_direct_ledger,
    _token,
    _transform_direct_source,
)


@lru_cache(maxsize=1)
def _authoritative_payload() -> dict[str, Any]:
    _source, diagram, owner = _direct_image_flow()
    diagram.update(
        reading_order=0,
        source="ocr",
        confidence=0.9,
        parse_concerns=["diagram_relationships_not_structured"],
    )
    binding = bind_raster_diagram_owner(
        diagram,
        page_items=[diagram],
        detected_images=[owner],
        page_index=1,
        page_unit="px",
        input_kind="image",
    )
    assert binding is not None
    by_id = {
        token["occurrence_id"]: token
        for token in binding.item["ocr_token_occurrences"]
    }

    def label(token_id: str) -> dict[str, Any]:
        token = by_id[token_id]
        return {
            "text": token["text"],
            "page_bbox": deepcopy(token["bbox"]),
            "raster_pixel_bbox": deepcopy(token["bbox"]),
            "source_token_ids": [token_id],
        }

    def box(x: float, y: float, width: float, height: float) -> dict[str, Any]:
        return {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "unit": "px",
        }

    def node(
        source_id: str,
        node_box: dict[str, Any],
        token_id: str,
        details: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "source_object_id": source_id,
            "shape": "rectangle",
            "page_bbox": deepcopy(node_box),
            "raster_pixel_bbox": deepcopy(node_box),
            "label": label(token_id),
            "details": details or [],
            "confidence": 1.0,
        }

    def detail(
        token_id: str,
        bullet_id: str,
        bullet_box: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **label(token_id),
            "bullet": {
                "source_object_id": bullet_id,
                "page_bbox": deepcopy(bullet_box),
                "raster_pixel_bbox": deepcopy(bullet_box),
            },
        }

    def connector(
        source_id: str,
        component_index: int,
        source_node: str,
        target_node: str,
        points: list[tuple[float, float]],
        arrow_id: str,
        arrow_box: dict[str, Any],
        label_token_id: str | None = None,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "source_object_id": source_id,
            "component_index": component_index,
            "source_node_source_object_id": source_node,
            "target_node_source_object_id": target_node,
            "path_points": [{"x": x, "y": y} for x, y in points],
            "raster_path_points": [{"x": x, "y": y} for x, y in points],
            "arrowhead": {
                "source_object_id": arrow_id,
                "page_bbox": deepcopy(arrow_box),
                "raster_pixel_bbox": deepcopy(arrow_box),
                "tip": {"x": points[-1][0], "y": points[-1][1]},
                "raster_tip": {"x": points[-1][0], "y": points[-1][1]},
            },
            "endpoint_tolerance": 5.0,
            "confidence": 1.0,
            "direction_confidence": 1.0,
        }
        if label_token_id is not None:
            value["label"] = label(label_token_id)
        return value

    proof = binding.item["meta"]["phase05_raster_diagram_owner"]
    raw = {
        "schema_version": "1.0",
        "source": {
            "kind": "raster",
            "owner_id": binding.owner_id,
            "page_bbox": box(0.0, 0.0, 600.0, 600.0),
            "raster_pixel_bbox": box(0.0, 0.0, 600.0, 600.0),
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "ocr_ledger_sha256": proof["ocr_ledger_sha256"],
        },
        "nodes": [
            node("node-start", box(210.0, 25.0, 180.0, 60.0), "direct-0"),
            node(
                "node-review",
                box(210.0, 165.0, 180.0, 120.0),
                "direct-1",
                [
                    detail("direct-2", "bullet-identity", box(225.0, 216.0, 7.0, 7.0)),
                    detail("direct-3", "bullet-consent", box(225.0, 251.0, 7.0, 7.0)),
                ],
            ),
            node("node-accepted", box(35.0, 430.0, 180.0, 60.0), "direct-6"),
            node("node-rejected", box(385.0, 430.0, 180.0, 60.0), "direct-7"),
        ],
        "connectors": [
            connector(
                "edge-start-review",
                1,
                "node-start",
                "node-review",
                [(300.0, 85.0), (300.0, 165.0)],
                "arrow-start-review",
                box(291.0, 150.0, 18.0, 15.0),
            ),
            connector(
                "edge-review-accepted",
                2,
                "node-review",
                "node-accepted",
                [(300.0, 285.0), (300.0, 360.0), (125.0, 360.0), (125.0, 430.0)],
                "arrow-review-accepted",
                box(116.0, 415.0, 18.0, 15.0),
                "direct-4",
            ),
            connector(
                "edge-review-rejected",
                2,
                "node-review",
                "node-rejected",
                [(300.0, 285.0), (300.0, 360.0), (475.0, 360.0), (475.0, 430.0)],
                "arrow-review-rejected",
                box(466.0, 415.0, 18.0, 15.0),
                "direct-5",
            ),
        ],
        "accounting": {
            "node_count": 4,
            "connector_component_count": 2,
            "connector_count": 3,
            "arrowhead_count": 3,
            "detail_count": 2,
            "unowned_topology_component_count": 0,
        },
    }
    item = deepcopy(binding.item)
    item.update(
        reading_order=0,
        source="ocr",
        confidence=0.9,
        parse_concerns=["diagram_relationships_not_structured"],
    )
    item.setdefault("meta", {})[
        "phase05_diagram_topology_evidence"
    ] = deepcopy(raw)
    fallback = build_visual_fallback(
        item,
        kind="diagram",
        page_index=1,
        page_unit="px",
        document_identity="1" * 64,
        item_index=0,
        input_kind="image",
        classifier_available=True,
    )
    structure = structure_diagram_topology(
        item,
        fallback,
        page_index=1,
        input_kind="image",
    )
    assert not structure.fallback.active
    assert structure.serialization is not None
    item["visual_structure"] = structure.model_dump(
        mode="json", exclude_none=True
    )
    item["value"] = structure.serialization.markdown
    item["md"] = structure.serialization.markdown
    item["parse_concerns"] = []
    ContentItem.model_validate(deepcopy(item))
    return item


def _authoritative_item() -> dict[str, Any]:
    return deepcopy(_authoritative_payload())


@pytest.mark.parametrize("caption_case", ["none", "match", "mismatch"])
def test_layout_reentry_preserves_exact_authoritative_raster_serialization(
    caption_case: str,
) -> None:
    item = _authoritative_item()
    expected = item["visual_structure"]["serialization"]["markdown"]
    caption = "Fig 1. Flowchart."
    external_caption = caption_case != "none"
    raw_caption = (
        caption if caption_case == "match" else "Different figure caption."
    )
    if external_caption:
        item["caption"] = caption
        structure = item["visual_structure"]
        captioned, caption_count = _build_raster_markdown(
            item,
            [VisualLabel.model_validate(value) for value in structure["labels"]],
            [DiagramNode.model_validate(value) for value in structure["nodes"]],
            [
                DiagramConnector.model_validate(value)
                for value in structure["connectors"]
            ],
        )
        assert caption_count == 1
        structure["serialization"]["markdown"] = captioned
        structure["serialization"]["caption_occurrences"] = 1
        item["value"] = item["md"] = captioned
        ContentItem.model_validate(item)
    child_token = next(
        token
        for token in item["ocr_token_occurrences"]
        if token["occurrence_id"] == "direct-2"
    )
    child_box = child_token["bbox"]
    owner_box = item["bbox"]
    raw_graph = {
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": child_token["text"],
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": child_box["x"],
                            "t": child_box["y"],
                            "r": child_box["x"] + child_box["width"],
                            "b": child_box["y"] + child_box["height"],
                            "coord_origin": "TOPLEFT",
                        },
                        "charspan": [0, 1],
                    }
                ],
            },
            *(
                [
                    {
                        "self_ref": "#/texts/1",
                        "label": "caption",
                        "text": raw_caption,
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {
                                    "l": 20.0,
                                    "t": 620.0,
                                    "r": 180.0,
                                    "b": 638.0,
                                    "coord_origin": "TOPLEFT",
                                },
                                "charspan": [2, 3],
                            }
                        ],
                    }
                ]
                if external_caption
                else []
            ),
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "diagram",
                "captions": (
                    [{"$ref": "#/texts/1"}] if external_caption else []
                ),
                "children": [{"$ref": "#/texts/0"}],
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": owner_box["x"],
                            "t": owner_box["y"],
                            "r": owner_box["x"] + owner_box["width"],
                            "b": owner_box["y"] + owner_box["height"],
                            "coord_origin": "TOPLEFT",
                        },
                        "charspan": [0, 1],
                    }
                ],
            }
        ],
        "tables": [],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/pictures/0"}],
        },
    }
    document = {
        "schema_version": "1.0",
        "document": {
            "filename": "diagram.png",
            "mime_type": "image/png",
            "sha256": "1" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 600.0,
                "page_height": 700.0 if external_caption else 600.0,
                "unit": "px",
                "success": True,
                "items": [item],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }

    projected, internal_ir = round_trip_document(
        document,
        raw_graph=raw_graph,
        native_texts=(
            " ".join((child_token["text"], raw_caption))
            if external_caption
            else child_token["text"],
        ),
        layout_settings=Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            layout_visual_relationships_enabled=True,
        ),
    )
    owner = next(
        value
        for value in projected["pages"][0]["items"]
        if value.get("type") == "diagram"
    )
    expected_owner = (
        item["visual_structure"]["serialization"]["markdown"]
        if caption_case == "mismatch"
        else expected
    )
    assert owner["value"] == owner["md"] == expected_owner
    ContentItem.model_validate(owner)
    canonical = build_canonical_presentation(internal_ir)
    assert canonical.full.markdown.count(expected_owner) == 1
    if caption_case == "match":
        captions = [
            value
            for value in projected["pages"][0]["items"]
            if value.get("type") == "caption"
        ]
        assert len(captions) == 1
        assert captions[0]["value"] == captions[0]["md"] == caption
        assert canonical.full.markdown.count(caption) == 1
        reprojected, reentered_ir = round_trip_document(
            projected,
            raw_graph=raw_graph,
            native_texts=(" ".join((child_token["text"], raw_caption)),),
            layout_settings=Settings(
                shared_ir_enabled=True,
                shared_ir_normalization_enabled=True,
                layout_visual_relationships_enabled=True,
            ),
        )
        reentered_owner = next(
            value
            for value in reprojected["pages"][0]["items"]
            if value.get("type") == "diagram"
        )
        assert reentered_owner["value"] == reentered_owner["md"] == expected
        ContentItem.model_validate(reentered_owner)
        reentered_canonical = build_canonical_presentation(reentered_ir)
        assert reentered_canonical.full.markdown.count(caption) == 1
        assert reentered_canonical.full.markdown.count(expected) == 1
    elif caption_case == "mismatch":
        assert all(
            value.get("type") != "caption"
            for value in projected["pages"][0]["items"]
        )
        assert canonical.full.markdown.count(caption) == 1
        assert raw_caption not in canonical.full.markdown


def _reseal_markdown(item: dict[str, Any]) -> None:
    structure = item["visual_structure"]
    markdown, _caption_count = _build_raster_markdown(
        item,
        [VisualLabel.model_validate(value) for value in structure["labels"]],
        [DiagramNode.model_validate(value) for value in structure["nodes"]],
        [
            DiagramConnector.model_validate(value)
            for value in structure["connectors"]
        ],
    )
    structure["serialization"]["markdown"] = markdown
    item["value"] = item["md"] = markdown


def _evidence_by_id(item: dict[str, Any], identifier: str) -> dict[str, Any]:
    return next(
        value
        for value in item["visual_structure"]["evidence"]
        if value["id"] == identifier
    )


def test_raster_graph_is_a_grounded_hierarchical_list_and_revalidates() -> None:
    item = _authoritative_item()
    structure = ContentItem.model_validate(item).visual_structure
    assert structure is not None
    expected = (
        "- Start\n"
        "  - Review\n"
        "    - Identity valid\n"
        "    - Consent present\n"
        "    - Yes: Accepted\n"
        "    - No: Rejected"
    )

    assert item["value"] == item["md"] == expected
    assert structure.serialization is not None
    assert structure.serialization.markdown == expected
    assert len(structure.nodes) == 4
    assert len(structure.connectors) == 3
    assert sum(len(node.detail_label_ids) for node in structure.nodes) == 2
    assert sorted(
        label.text for label in structure.labels if label.role == "connector"
    ) == ["No", "Yes"]
    raster_evidence = [
        record
        for record in structure.evidence
        if record.provenance.extraction_method == "raster"
    ]
    assert raster_evidence
    assert all(record.raster_pixel_bbox is not None for record in raster_evidence)
    assert all(record.transform_ids for record in raster_evidence)


def test_apply_semantics_commits_owner_bbox_graph_and_public_text_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, diagram, owner = _direct_image_flow()
    diagram.update(source="ocr", confidence=0.9)
    raw = deepcopy(
        _authoritative_payload()["meta"]["phase05_diagram_topology_evidence"]
    )
    monkeypatch.setattr(
        raster_diagram,
        "derive_raster_diagram_topology_evidence",
        lambda *_args, **_kwargs: deepcopy(raw),
    )
    payload = _payload(diagram)
    payload["pages"][0].update(
        page_width=600.0,
        page_height=600.0,
        unit="px",
        detected_images=[owner],
    )
    settings = Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        diagrams_topology_enabled=True,
    )

    result = apply_visual_semantics(
        payload,
        settings,
        source_document_bytes=source,
        input_kind=InputKind.IMAGE,
    )

    item = result["pages"][0]["items"][0]
    validated = ContentItem.model_validate(item)
    assert validated.visual_structure is not None
    assert validated.visual_structure.fallback.active is False
    assert item["bbox"] == raw["source"]["page_bbox"]
    assert item["value"] == item["md"]
    assert item["value"] == validated.visual_structure.serialization.markdown
    assert "diagram_relationships_not_structured" not in item["parse_concerns"]


def test_canonical_block_is_the_exact_authoritative_diagram_list() -> None:
    item = _authoritative_item()
    payload = _payload(item)
    payload["pages"][0].update(page_width=600.0, page_height=600.0, unit="px")

    canonical = build_canonical_presentation(build_document_ir(payload))

    assert len(canonical.pages) == 1
    assert len(canonical.pages[0].blocks) == 1
    block = canonical.pages[0].blocks[0]
    assert block.primary_element_type == "diagram"
    assert block.markdown == item["md"]
    assert block.text == item["value"]


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_multiline_raster_graph_replays_across_right_angle_rotations(
    rotation: int,
) -> None:
    source, diagram, owner = _direct_image_flow()
    diagram.update(
        reading_order=0,
        source="ocr",
        confidence=0.9,
        parse_concerns=["diagram_relationships_not_structured"],
    )
    line_boxes: list[dict[str, Any]] = []

    def edit(draw: Any) -> None:
        draw.rectangle((220, 30, 380, 82), fill="white")
        for text, point in (("First", (282, 38)), ("Second", (276, 58))):
            draw.text(point, text, fill="black")
            left, top, right, bottom = draw.textbbox(point, text)
            line_boxes.append(
                {
                    "x": float(left),
                    "y": float(top),
                    "width": float(right - left),
                    "height": float(bottom - top),
                    "unit": "px",
                }
            )

    changed = _edit_png(source, edit)
    owner["items"][0] = _line("First", line_boxes[0])
    owner["items"].insert(1, _line("Second", line_boxes[1]))
    owner["ocr_token_occurrences"][0] = {
        **_token("direct-0", "First", line_boxes[0]),
        "line_occurrence_id": "direct-line-0",
    }
    owner["ocr_token_occurrences"].insert(
        1,
        {
            **_token("direct-start-second", "Second", line_boxes[1]),
            "line_occurrence_id": "direct-line-start-second",
        },
    )
    _sync_direct_ledger(diagram, owner)
    if rotation:
        changed = _transform_direct_source(
            changed,
            diagram,
            owner,
            rotation=rotation,
        )
    binding = bind_raster_diagram_owner(
        diagram,
        page_items=[diagram],
        detected_images=[owner],
        page_index=1,
        page_unit="px",
        input_kind="image",
    )
    assert binding is not None
    raw = derive_raster_diagram_topology_evidence(
        binding,
        changed,
        page_index=1,
        input_kind="image",
    )
    assert raw is not None
    item = deepcopy(binding.item)
    item.setdefault("meta", {})[
        "phase05_diagram_topology_evidence"
    ] = deepcopy(raw)
    fallback = build_visual_fallback(
        item,
        kind="diagram",
        page_index=1,
        page_unit="px",
        document_identity="2" * 64,
        item_index=0,
        input_kind="image",
        classifier_available=True,
    )
    structure = structure_diagram_topology(
        item,
        fallback,
        page_index=1,
        input_kind="image",
    )
    assert structure.fallback.active is False
    assert structure.serialization is not None
    assert "First Second" in {label.text for label in structure.labels}
    item["visual_structure"] = structure.model_dump(
        mode="json", exclude_none=True
    )
    item["value"] = item["md"] = structure.serialization.markdown
    item["parse_concerns"] = []
    ContentItem.model_validate(item)


def test_raster_derivation_does_not_run_after_vector_source_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagram = _diagram()
    owner = _owner()
    diagram.update(source="ocr", confidence=0.9)
    payload = _payload(diagram)
    payload["pages"][0]["detected_images"] = [owner]
    calls: list[str] = []

    def fail_vector(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic vector failure")

    def record_raster(*_args: Any, **_kwargs: Any) -> Any:
        calls.append("raster")
        return None

    monkeypatch.setattr(
        "app.services.visual_diagram_topology.extract_pdf_diagram_topology_evidence",
        fail_vector,
    )
    monkeypatch.setattr(
        raster_diagram,
        "derive_raster_diagram_topology_evidence",
        record_raster,
    )
    settings = Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        diagrams_topology_enabled=True,
    )

    result = apply_visual_semantics(
        payload,
        settings,
        source_document_bytes=b"bounded-pdf",
        input_kind=InputKind.PDF,
    )

    item = ContentItem.model_validate(result["pages"][0]["items"][0])
    assert item.visual_structure is not None
    assert item.visual_structure.fallback.active is True
    assert calls == []


@pytest.mark.parametrize("projection", ("metadata", "direct"))
def test_preloaded_raster_graph_cannot_authorize_different_current_bytes(
    projection: str,
) -> None:
    _source, diagram, owner = _direct_image_flow()
    diagram.update(source="ocr", confidence=0.9)
    preloaded = deepcopy(
        _authoritative_payload()["meta"]["phase05_diagram_topology_evidence"]
    )
    if projection == "metadata":
        diagram.setdefault("meta", {})[
            "phase05_diagram_topology_evidence"
        ] = preloaded
    else:
        diagram["diagram_topology_evidence"] = preloaded
    payload = _payload(diagram)
    payload["pages"][0].update(
        page_width=600.0,
        page_height=600.0,
        unit="px",
        detected_images=[owner],
    )
    settings = Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        diagrams_topology_enabled=True,
    )

    result = apply_visual_semantics(
        payload,
        settings,
        source_document_bytes=b"not-an-image",
        input_kind=InputKind.IMAGE,
    )

    item = ContentItem.model_validate(result["pages"][0]["items"][0])
    assert item.visual_structure is not None
    assert item.visual_structure.fallback.active is True
    assert item.visual_structure.nodes == []
    assert item.visual_structure.connectors == []
    assert "diagram_relationships_not_structured" in (
        item.model_extra or {}
    )["parse_concerns"]
    assert "phase05_diagram_topology_evidence" not in (
        item.model_extra or {}
    ).get("meta", {})
    assert "diagram_topology_evidence" not in (item.model_extra or {})


@pytest.mark.parametrize(
    "mutation",
    (
        "public_value",
        "public_markdown",
        "raw_transform",
        "raw_accounting",
        "raw_token_owner",
        "raw_removed",
        "fully_resealed_label_omission",
        "fully_resealed_arrow_outside",
        "fully_resealed_target_rebind",
        "fully_resealed_node_overlap",
        "fully_resealed_endpoint_ambiguity",
        "fully_resealed_path_through_node",
        "fully_resealed_component_collapse",
        "fully_resealed_component_split",
        "semantic_edge",
        "semantic_detail_reuse",
        "semantic_connector_label_reuse",
        "raster_evidence",
    ),
)
def test_content_item_rejects_resealed_raster_graph_tampering(
    mutation: str,
) -> None:
    item = _authoritative_item()
    raw = item["meta"]["phase05_diagram_topology_evidence"]
    structure = item["visual_structure"]
    if mutation == "public_value":
        item["value"] += "!"
    elif mutation == "public_markdown":
        item["md"] += "!"
    elif mutation == "raw_transform":
        raw["source"]["transform"][0] *= 1.01
    elif mutation == "raw_accounting":
        raw["accounting"]["detail_count"] += 1
    elif mutation == "raw_token_owner":
        raw["nodes"][1]["details"][1]["source_token_ids"] = deepcopy(
            raw["nodes"][1]["details"][0]["source_token_ids"]
        )
    elif mutation == "raw_removed":
        del item["meta"]["phase05_diagram_topology_evidence"]
    elif mutation == "fully_resealed_label_omission":
        raw_connector = next(
            value
            for value in raw["connectors"]
            if value.get("label", {}).get("text") == "Yes"
        )
        del raw_connector["label"]
        yes_label = next(
            value
            for value in structure["labels"]
            if value.get("role") == "connector" and value.get("text") == "Yes"
        )
        yes_label_id = yes_label["id"]
        yes_evidence_ids = set(yes_label["evidence_ids"])
        structure["labels"] = [
            value
            for value in structure["labels"]
            if value["id"] != yes_label_id
        ]
        for occurrence_index, label in enumerate(structure["labels"]):
            label["occurrence_index"] = occurrence_index
        structure["evidence"] = [
            value
            for value in structure["evidence"]
            if value["id"] not in yes_evidence_ids
        ]
        semantic_connector = next(
            value
            for value in structure["connectors"]
            if value.get("label_id") == yes_label_id
        )
        del semantic_connector["label_id"]
        semantic_connector["evidence_ids"] = [
            value
            for value in semantic_connector["evidence_ids"]
            if value not in yes_evidence_ids
        ]
        resealed_markdown = item["md"].replace(
            "    - Yes: Accepted",
            "    - Accepted",
        )
        item["value"] = item["md"] = resealed_markdown
        structure["serialization"]["markdown"] = resealed_markdown
    elif mutation == "fully_resealed_arrow_outside":
        raw_connector = raw["connectors"][0]
        raw_connector["endpoint_tolerance"] = 600.0
        outside_box = {
            "x": 750.0,
            "y": 750.0,
            "width": 18.0,
            "height": 15.0,
            "unit": "px",
        }
        raw_connector["arrowhead"]["page_bbox"] = deepcopy(outside_box)
        raw_connector["arrowhead"]["raster_pixel_bbox"] = deepcopy(
            outside_box
        )
        semantic_connector = structure["connectors"][0]
        direction = _evidence_by_id(
            item,
            semantic_connector["direction_evidence_id"],
        )
        direction["page_bbox"] = deepcopy(outside_box)
        direction["raster_pixel_bbox"] = deepcopy(outside_box)
    elif mutation == "fully_resealed_target_rebind":
        raw_connector = raw["connectors"][0]
        raw_connector["target_node_source_object_id"] = "node-accepted"
        raw_connector["endpoint_tolerance"] = 600.0
        semantic_connector = structure["connectors"][0]
        semantic_connector["target_node_id"] = structure["nodes"][2]["id"]
        target_evidence = _evidence_by_id(
            item,
            semantic_connector["endpoint_evidence_ids"][1],
        )
        target_evidence["provenance"]["source_object_ids"] = sorted(
            ("edge-start-review", "node-accepted")
        )
        _reseal_markdown(item)
    elif mutation == "fully_resealed_node_overlap":
        overlap_box = {
            "x": 120.0,
            "y": 25.0,
            "width": 180.0,
            "height": 260.0,
            "unit": "px",
        }
        raw["nodes"][0]["page_bbox"] = deepcopy(overlap_box)
        raw["nodes"][0]["raster_pixel_bbox"] = deepcopy(overlap_box)
        semantic_node = structure["nodes"][0]
        semantic_node["page_bbox"] = deepcopy(overlap_box)
        node_evidence = next(
            _evidence_by_id(item, evidence_id)
            for evidence_id in semantic_node["evidence_ids"]
            if _evidence_by_id(item, evidence_id)["kind"] == "node"
        )
        node_evidence["page_bbox"] = deepcopy(overlap_box)
        node_evidence["raster_pixel_bbox"] = deepcopy(overlap_box)
    elif mutation == "fully_resealed_endpoint_ambiguity":
        review_box = {
            "x": 210.0,
            "y": 86.0,
            "width": 180.0,
            "height": 199.0,
            "unit": "px",
        }
        raw["nodes"][1]["page_bbox"] = deepcopy(review_box)
        raw["nodes"][1]["raster_pixel_bbox"] = deepcopy(review_box)
        semantic_node = structure["nodes"][1]
        semantic_node["page_bbox"] = deepcopy(review_box)
        node_evidence = next(
            _evidence_by_id(item, evidence_id)
            for evidence_id in semantic_node["evidence_ids"]
            if _evidence_by_id(item, evidence_id)["kind"] == "node"
        )
        node_evidence["page_bbox"] = deepcopy(review_box)
        node_evidence["raster_pixel_bbox"] = deepcopy(review_box)
        raw_connector = raw["connectors"][0]
        short_path = [{"x": 300.0, "y": 85.0}, {"x": 300.0, "y": 86.0}]
        raw_connector["path_points"] = deepcopy(short_path)
        raw_connector["raster_path_points"] = deepcopy(short_path)
        arrow_box = {
            "x": 291.0,
            "y": 71.0,
            "width": 18.0,
            "height": 15.0,
            "unit": "px",
        }
        raw_connector["arrowhead"]["page_bbox"] = deepcopy(arrow_box)
        raw_connector["arrowhead"]["raster_pixel_bbox"] = deepcopy(arrow_box)
        raw_connector["arrowhead"]["tip"] = {"x": 300.0, "y": 86.0}
        raw_connector["arrowhead"]["raster_tip"] = {
            "x": 300.0,
            "y": 86.0,
        }
        semantic_connector = structure["connectors"][0]
        path_evidence = _evidence_by_id(
            item,
            semantic_connector["path_evidence_id"],
        )
        path_box = {
            "x": 300.0,
            "y": 85.0,
            "width": 0.0,
            "height": 1.0,
            "unit": "px",
        }
        path_evidence["page_bbox"] = deepcopy(path_box)
        path_evidence["raster_pixel_bbox"] = deepcopy(path_box)
        target_evidence = _evidence_by_id(
            item,
            semantic_connector["endpoint_evidence_ids"][1],
        )
        target_box = {
            "x": 300.0,
            "y": 86.0,
            "width": 0.0,
            "height": 0.0,
            "unit": "px",
        }
        target_evidence["page_bbox"] = deepcopy(target_box)
        target_evidence["raster_pixel_bbox"] = deepcopy(target_box)
        direction = _evidence_by_id(
            item,
            semantic_connector["direction_evidence_id"],
        )
        direction["page_bbox"] = deepcopy(arrow_box)
        direction["raster_pixel_bbox"] = deepcopy(arrow_box)
    elif mutation == "fully_resealed_path_through_node":
        raw_connector = raw["connectors"][1]
        path = [
            (300.0, 285.0),
            (300.0, 330.0),
            (180.0, 330.0),
            (180.0, 360.0),
            (20.0, 360.0),
            (20.0, 540.0),
            (575.0, 540.0),
            (575.0, 460.0),
            (565.0, 460.0),
            (385.0, 460.0),
            (385.0, 410.0),
            (125.0, 410.0),
            (125.0, 430.0),
        ]
        public_path = [{"x": x, "y": y} for x, y in path]
        raw_connector["path_points"] = deepcopy(public_path)
        raw_connector["raster_path_points"] = deepcopy(public_path)
        semantic_connector = structure["connectors"][1]
        path_evidence = _evidence_by_id(
            item,
            semantic_connector["path_evidence_id"],
        )
        path_box = {
            "x": 20.0,
            "y": 285.0,
            "width": 555.0,
            "height": 255.0,
            "unit": "px",
        }
        path_evidence["page_bbox"] = deepcopy(path_box)
        path_evidence["raster_pixel_bbox"] = deepcopy(path_box)
    elif mutation == "fully_resealed_component_collapse":
        for raw_connector in raw["connectors"]:
            raw_connector["component_index"] = 1
        raw["accounting"]["connector_component_count"] = 1
    elif mutation == "fully_resealed_component_split":
        raw["connectors"][2]["component_index"] = 3
        raw["accounting"]["connector_component_count"] = 3
    elif mutation == "semantic_edge":
        structure["connectors"][0]["target_node_id"] = structure["nodes"][2]["id"]
    elif mutation == "semantic_detail_reuse":
        structure["nodes"][0]["detail_label_ids"] = [
            structure["nodes"][1]["detail_label_ids"][0]
        ]
    elif mutation == "semantic_connector_label_reuse":
        labelled = [
            value for value in structure["connectors"] if "label_id" in value
        ]
        labelled[1]["label_id"] = labelled[0]["label_id"]
    else:
        raster_record = next(
            record
            for record in structure["evidence"]
            if record["provenance"]["extraction_method"] == "raster"
        )
        raster_record["raster_pixel_bbox"]["x"] += 1.0

    with pytest.raises(ValidationError):
        ContentItem.model_validate(item)


@pytest.mark.parametrize(
    ("identity_kind", "unsafe_value"),
    (
        ("source_object_id", "arrow\x00identity"),
        ("occurrence_id", "token\nidentity"),
        ("line_occurrence_id", "line\u202eidentity"),
    ),
)
def test_content_item_rejects_resealed_unsafe_raster_source_identifiers(
    identity_kind: str,
    unsafe_value: str,
) -> None:
    item = _authoritative_item()
    raw = item["meta"]["phase05_diagram_topology_evidence"]
    structure = item["visual_structure"]
    if identity_kind == "source_object_id":
        raw_connector = raw["connectors"][0]
        raw_connector["arrowhead"]["source_object_id"] = unsafe_value
        direction = _evidence_by_id(
            item,
            structure["connectors"][0]["direction_evidence_id"],
        )
        direction["provenance"]["source_object_ids"] = sorted(
            (raw_connector["source_object_id"], unsafe_value)
        )
    elif identity_kind == "occurrence_id":
        item["ocr_token_occurrences"][0]["occurrence_id"] = unsafe_value
        raw["nodes"][0]["label"]["source_token_ids"] = [unsafe_value]
        label_id = structure["nodes"][0]["label_id"]
        label = next(
            value for value in structure["labels"] if value["id"] == label_id
        )
        label_evidence = _evidence_by_id(item, label["evidence_ids"][0])
        label_evidence["provenance"]["source_token_ids"] = [unsafe_value]
    else:
        item["ocr_token_occurrences"][0]["line_occurrence_id"] = unsafe_value

    with pytest.raises(ValidationError):
        ContentItem.model_validate(item)


def _label(identifier: str, text: str, index: int, role: str = "node") -> VisualLabel:
    return VisualLabel(
        id=f"label-{identifier}",
        text=text,
        role=role,
        page_bbox=VisualBoundingBox(
            x=float(index * 10), y=float(index * 10), width=5.0, height=5.0, unit="pt"
        ),
        evidence_ids=[f"evidence-label-{identifier}"],
        occurrence_index=index,
    )


def _node(identifier: str, label: VisualLabel, x: float, y: float) -> DiagramNode:
    return DiagramNode(
        id=f"node-{identifier}",
        shape="rectangle",
        label_id=label.id,
        page_bbox=VisualBoundingBox(x=x, y=y, width=20.0, height=10.0, unit="pt"),
        evidence_ids=[f"evidence-node-{identifier}", label.evidence_ids[0]],
        confidence=VisualConfidenceDimensions(geometry=1.0),
    )


def _edge(
    identifier: str,
    source: DiagramNode,
    target: DiagramNode,
    label: VisualLabel | None = None,
) -> DiagramConnector:
    evidence_ids = [
        f"path-{identifier}",
        f"source-{identifier}",
        f"target-{identifier}",
        f"direction-{identifier}",
    ]
    if label is not None:
        evidence_ids.extend(label.evidence_ids)
    return DiagramConnector(
        id=f"edge-{identifier}",
        source_node_id=source.id,
        target_node_id=target.id,
        label_id=label.id if label is not None else None,
        directed=True,
        path_evidence_id=evidence_ids[0],
        endpoint_evidence_ids=evidence_ids[1:3],
        direction_evidence_id=evidence_ids[3],
        evidence_ids=evidence_ids,
        confidence=VisualConfidenceDimensions(geometry=1.0, direction=1.0),
    )


def test_raster_only_graph_fields_are_absent_from_legacy_public_shape() -> None:
    label = _label("legacy", "Legacy", 0)
    source = _node("legacy-source", label, 0.0, 0.0)
    target_label = _label("legacy-target", "Target", 1)
    target = _node("legacy-target", target_label, 0.0, 20.0)
    connector = _edge("legacy", source, target)

    assert "detail_label_ids" not in source.model_dump(
        mode="json", exclude_none=True
    )
    assert "label_id" not in connector.model_dump(mode="json", exclude_none=True)


def test_list_serializer_handles_merge_rooted_loop_and_disconnected_start() -> None:
    labels = [
        _label("a", "A\\|root", 0),
        _label("b", "B", 1),
        _label("c", "C", 2),
        _label("d", "D", 3),
        _label("e", "E", 4),
        _label("f", "F", 5),
        _label("yes", "Yes", 6, role="connector"),
    ]
    a, b, c, d, e, f = (
        _node("a", labels[0], 0.0, 0.0),
        _node("b", labels[1], 0.0, 20.0),
        _node("c", labels[2], 40.0, 20.0),
        _node("d", labels[3], 0.0, 40.0),
        _node("e", labels[4], 100.0, 0.0),
        _node("f", labels[5], 100.0, 20.0),
    )
    connectors = [
        _edge("ab", a, b),
        _edge("ac", a, c),
        _edge("bd", b, d),
        _edge("cd", c, d, labels[6]),
        _edge("db", d, b),
        _edge("ef", e, f),
    ]

    markdown, caption_count = _build_raster_markdown(
        {"caption": "Flow | one"}, labels, [a, b, c, d, e, f], connectors
    )

    assert caption_count == 1
    assert markdown == (
        "Flow \\| one\n"
        "\n"
        "- A\\\\\\|root\n"
        "  - B\n"
        "    - D\n"
        "      - Returns to: B\n"
        "  - C\n"
        "    - Yes: Continues at: D\n"
        "- E\n"
        "  - F"
    )


def test_list_serializer_rejects_rootless_cycle_and_ambiguous_reference() -> None:
    labels = [_label("a", "Same", 0), _label("b", "Same", 1), _label("c", "C", 2)]
    a = _node("a", labels[0], 0.0, 0.0)
    b = _node("b", labels[1], 0.0, 20.0)
    c = _node("c", labels[2], 40.0, 0.0)
    with pytest.raises(ValueError, match="starting point|rootless"):
        _build_raster_markdown(
            {}, labels[:2], [a, b], [_edge("ab", a, b), _edge("ba", b, a)]
        )
    with pytest.raises(ValueError, match="reference text is ambiguous"):
        _build_raster_markdown(
            {},
            labels,
            [c, a, b],
            [_edge("ca", c, a), _edge("cb", c, b), _edge("ab", a, b)],
        )


def test_visual_label_unicode_and_control_boundaries_are_closed() -> None:
    accepted = _label("safe", "😀" * 1_024, 0)
    assert len(accepted.text.encode("utf-8")) == 4_096
    normalized = _label("newline", "A\r\nB\rC", 1)
    assert normalized.text == "A\nB\nC"
    for unsafe in (
        "x" * 1_025,
        "😀" * 1_024 + "x",
        "A\x00B",
        "A\u2028B",
        "A\u2029B",
        "A\u202eB",
    ):
        with pytest.raises(ValidationError):
            _label("unsafe", unsafe, 2)
