from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

import app.services.pipeline as pipeline
import app.services.visual_diagram_topology as diagram_topology
from app.config import Settings
from app.models import ParseResult
from app.services.input_documents import InputKind
from app.services.serializer import to_markdown
from app.services.visual_contracts import VisualStructure
from app.services.visual_raster_diagram import RasterDiagramOwnerBinding
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import (
    _item,
    _payload,
    _public_loaded_image,
    _public_raw_layout,
    _public_region,
)


def _occurrence(
    identifier: str,
    text: str,
    x: float,
    y: float,
    width: float,
    height: float = 10.0,
) -> dict[str, Any]:
    return {
        "occurrence_id": identifier,
        "line_occurrence_id": f"line-{identifier}",
        "text": text,
        "bbox": {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "unit": "pt",
        },
        "confidence": 0.97,
        "ocr_pass": "standard",
        "word_index": 0,
        "selected": True,
        "primary_selected": True,
        "short_alternative": False,
        "retention_reason": "primary_selected",
        "duplicate_of": None,
    }


def _topology_evidence() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "source_object_id": "node-start",
                "shape": "rectangle",
                "page_bbox": {
                    "x": 20.0,
                    "y": 30.0,
                    "width": 70.0,
                    "height": 40.0,
                    "unit": "pt",
                },
                "label_source_token_id": "label-start",
                "confidence": 0.96,
            },
            {
                "source_object_id": "node-review",
                "shape": "diamond",
                "page_bbox": {
                    "x": 120.0,
                    "y": 30.0,
                    "width": 60.0,
                    "height": 50.0,
                    "unit": "pt",
                },
                "label_source_token_id": "label-review",
                "confidence": 0.94,
            },
            {
                "source_object_id": "node-end",
                "shape": "rounded_rectangle",
                "page_bbox": {
                    "x": 220.0,
                    "y": 30.0,
                    "width": 60.0,
                    "height": 40.0,
                    "unit": "pt",
                },
                "label_source_token_id": "label-end",
                "confidence": 0.95,
            },
        ],
        "connectors": [
            {
                "source_object_id": "edge-start-review",
                "source_node_source_object_id": "node-start",
                "target_node_source_object_id": "node-review",
                "path_points": [
                    {"x": 90.0, "y": 50.0},
                    {"x": 105.0, "y": 50.0},
                    {"x": 120.0, "y": 55.0},
                ],
                "arrowhead": {
                    "source_object_id": "arrow-start-review",
                    "bbox": {
                        "x": 117.0,
                        "y": 52.0,
                        "width": 6.0,
                        "height": 6.0,
                        "unit": "pt",
                    },
                    "tip": {"x": 120.0, "y": 55.0},
                },
                "endpoint_tolerance": 3.0,
                "confidence": 0.93,
                "direction_confidence": 0.91,
            },
            {
                "source_object_id": "edge-review-end",
                "source_node_source_object_id": "node-review",
                "target_node_source_object_id": "node-end",
                "path_points": [
                    {"x": 180.0, "y": 55.0},
                    {"x": 200.0, "y": 55.0},
                    {"x": 220.0, "y": 50.0},
                ],
                "arrowhead": {
                    "source_object_id": "arrow-review-end",
                    "bbox": {
                        "x": 217.0,
                        "y": 47.0,
                        "width": 6.0,
                        "height": 6.0,
                        "unit": "pt",
                    },
                    "tip": {"x": 220.0, "y": 50.0},
                },
                "endpoint_tolerance": 3.0,
                "confidence": 0.92,
                "direction_confidence": 0.90,
            },
        ],
    }


def _diagram(
    *,
    diagram_id: str = "diagram-topology",
    evidence: Any | None = None,
    repeated_label: bool = False,
) -> dict[str, Any]:
    diagram = _item("diagram", diagram_id, x=0.0)
    diagram["bbox"] = {
        "x": 0.0,
        "y": 0.0,
        "width": 300.0,
        "height": 180.0,
        "unit": "pt",
    }
    diagram["coordinate_unit"] = "pt"
    diagram["items"] = []
    diagram["caption"] = "Approval flow"
    diagram["md"] = "Approval flow\nlegacy diagram fallback"
    diagram["ocr_token_occurrences"] = [
        _occurrence("label-start", "Start", 35.0, 45.0, 30.0),
        _occurrence("label-review", "Review", 130.0, 48.0, 40.0),
        _occurrence(
            "label-end",
            "Review" if repeated_label else "End",
            235.0,
            45.0,
            30.0,
        ),
    ]
    diagram.setdefault("meta", {})[
        "phase05_diagram_topology_evidence"
    ] = deepcopy(_topology_evidence() if evidence is None else evidence)
    return diagram


def _settings(*, topology: bool = True, canonical: bool = False) -> Settings:
    return Settings(
        shared_ir_enabled=canonical,
        shared_ir_normalization_enabled=canonical,
        canonical_serialization_enabled=canonical,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        visual_structure_schema_enabled=True,
        diagrams_topology_enabled=topology,
    )


def _output(diagram: dict[str, Any] | None = None) -> dict[str, Any]:
    source = deepcopy(diagram or _diagram())
    direct = source.pop("diagram_topology_evidence", None)
    meta = source.setdefault("meta", {})
    metadata = meta.pop("phase05_diagram_topology_evidence", None)
    evidence = direct if direct is not None else metadata
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            diagram_topology,
            "extract_pdf_diagram_topology_evidence",
            lambda *_args, **_kwargs: deepcopy(evidence),
        )
        return apply_visual_semantics(
            _payload(source),
            _settings(),
            source_document_bytes=b"locally-owned-pdf",
            input_kind=InputKind.PDF,
        )


def _structure(diagram: dict[str, Any] | None = None) -> VisualStructure:
    output = _output(diagram)
    return VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )


def test_simple_directed_topology_is_authoritative_and_deterministic() -> None:
    output = _output()
    first = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )
    second = _structure()

    assert first == second
    assert first.fallback.active is False
    assert first.serialization is not None
    assert first.serialization.status == "diagram_topology"
    assert first.serialization.row_count == len(first.connectors) == 2
    assert first.serialization.caption_occurrences == 1
    assert [node.shape for node in first.nodes] == [
        "rectangle",
        "diamond",
        "rounded_rectangle",
    ]
    assert all(connector.directed is True for connector in first.connectors)
    assert "diagram_topology_unresolved" not in {
        concern.code for concern in first.concerns
    }
    assert "diagram_relationships_not_structured" not in output["pages"][0][
        "items"
    ][0]["parse_concerns"]


def test_nodes_labels_paths_endpoints_and_direction_are_fully_grounded() -> None:
    structure = _structure()
    evidence = {record.id: record for record in structure.evidence}
    labels = {label.id: label for label in structure.labels}

    for node in structure.nodes:
        node_records = [
            evidence[evidence_id]
            for evidence_id in node.evidence_ids
            if evidence[evidence_id].kind == "node"
        ]
        assert len(node_records) == 1
        assert node_records[0].page_bbox == node.page_bbox
        assert node_records[0].provenance.source_object_ids
        assert node.confidence.geometry is not None
        if node.label_id is not None:
            label = labels[node.label_id]
            assert set(label.evidence_ids) <= set(node.evidence_ids)
            assert label.page_bbox is not None
            assert label.page_bbox.x >= node.page_bbox.x
            assert label.page_bbox.x + label.page_bbox.width <= (
                node.page_bbox.x + node.page_bbox.width
            )

    for connector in structure.connectors:
        assert evidence[connector.path_evidence_id].kind == "path"
        assert {
            evidence[evidence_id].kind
            for evidence_id in connector.endpoint_evidence_ids
        } == {"point"}
        assert evidence[connector.direction_evidence_id].kind == "connector"
        assert {
            connector.path_evidence_id,
            connector.direction_evidence_id,
            *connector.endpoint_evidence_ids,
        } <= set(connector.evidence_ids)
        assert connector.confidence.geometry is not None
        assert connector.confidence.direction is not None


def test_repeated_node_text_retains_distinct_spatial_occurrences() -> None:
    structure = _structure(_diagram(repeated_label=True))
    labels = {label.id: label for label in structure.labels}
    repeated = [labels[node.label_id] for node in structure.nodes if node.label_id]
    repeated = [label for label in repeated if label.text == "Review"]

    assert len(repeated) == 2
    assert repeated[0].id != repeated[1].id
    assert repeated[0].page_bbox != repeated[1].page_bbox
    source_tokens = {
        token_id
        for label in repeated
        for evidence_id in label.evidence_ids
        for record in structure.evidence
        if record.id == evidence_id
        for token_id in record.provenance.source_token_ids
    }
    assert source_tokens == {"label-review", "label-end"}


@pytest.mark.parametrize(
    ("mutation", "concern"),
    [
        ({"crossed": True}, "diagram_connector_crossing_ambiguous"),
        ({"disconnected": True}, "diagram_connector_disconnected"),
        (
            {"direction_ambiguous": True},
            "diagram_connector_direction_ambiguous",
        ),
    ],
)
def test_affected_connector_is_withheld_while_clean_neighbor_survives(
    mutation: dict[str, Any],
    concern: str,
) -> None:
    evidence = _topology_evidence()
    evidence["connectors"][0].update(mutation)
    structure = _structure(_diagram(evidence=evidence))

    assert structure.fallback.active is False
    assert len(structure.connectors) == 1
    path_record = next(
        record
        for record in structure.evidence
        if record.id == structure.connectors[0].path_evidence_id
    )
    assert path_record.provenance.source_object_ids == ["edge-review-end"]
    assert concern in {value.code for value in structure.concerns}


def test_label_outside_node_is_not_attached_to_that_node() -> None:
    diagram = _diagram()
    diagram["ocr_token_occurrences"].append(
        _occurrence("outside-label", "Outside", 185.0, 130.0, 45.0)
    )
    diagram["meta"]["phase05_diagram_topology_evidence"]["nodes"][1][
        "label_source_token_id"
    ] = "outside-label"
    structure = _structure(diagram)
    review = next(
        node
        for node in structure.nodes
        if any(
            "node-review" in record.provenance.source_object_ids
            for record in structure.evidence
            if record.id in node.evidence_ids
        )
    )

    assert review.label_id is None
    assert len(structure.connectors) == 2
    assert "diagram_label_outside_node" in {
        concern.code for concern in structure.concerns
    }


def test_unsupported_node_shape_withholds_dependent_graph() -> None:
    evidence = _topology_evidence()
    evidence["nodes"][1]["shape"] = "hexagon"
    structure = _structure(_diagram(evidence=evidence))

    assert structure.fallback.active is True
    assert structure.connectors == []
    assert len(structure.nodes) == 2
    codes = {concern.code for concern in structure.concerns}
    assert "diagram_node_unsupported_shape" in codes
    assert "diagram_connector_endpoint_unresolved" in codes


def test_geometry_detected_crossing_withholds_both_affected_edges() -> None:
    def node(source_id: str, x: float, y: float) -> dict[str, Any]:
        return {
            "source_object_id": source_id,
            "shape": "rectangle",
            "page_bbox": {
                "x": x,
                "y": y,
                "width": 40.0,
                "height": 30.0,
                "unit": "pt",
            },
        }

    def edge(
        source_id: str,
        source_node: str,
        target_node: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> dict[str, Any]:
        return {
            "source_object_id": source_id,
            "source_node_source_object_id": source_node,
            "target_node_source_object_id": target_node,
            "path_points": [
                {"x": start[0], "y": start[1]},
                {"x": end[0], "y": end[1]},
            ],
            "arrowhead": {
                "source_object_id": f"arrow-{source_id}",
                "bbox": {
                    "x": end[0] - 3.0,
                    "y": end[1] - 3.0,
                    "width": 6.0,
                    "height": 6.0,
                    "unit": "pt",
                },
                "tip": {"x": end[0], "y": end[1]},
            },
        }

    evidence = {
        "nodes": [
            node("north-west", 20.0, 20.0),
            node("north-east", 220.0, 20.0),
            node("south-west", 20.0, 120.0),
            node("south-east", 220.0, 120.0),
        ],
        "connectors": [
            edge(
                "falling-edge",
                "north-west",
                "south-east",
                (60.0, 40.0),
                (220.0, 135.0),
            ),
            edge(
                "rising-edge",
                "south-west",
                "north-east",
                (60.0, 135.0),
                (220.0, 40.0),
            ),
        ],
    }
    structure = _structure(_diagram(evidence=evidence))

    assert structure.fallback.active is True
    assert structure.connectors == []
    assert "diagram_connector_crossing_ambiguous" in {
        concern.code for concern in structure.concerns
    }


def test_pdf_vector_producer_requires_contained_labels_and_explicit_arrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _payload(_diagram())
    predecessor = apply_visual_semantics(
        source,
        _settings(topology=False),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        predecessor["pages"][0]["items"][0]["visual_structure"]
    )

    class FakePage:
        height = 792.0
        rects = [
            {"x0": 20.0, "x1": 90.0, "top": 30.0, "bottom": 70.0},
            {"x0": 120.0, "x1": 180.0, "top": 30.0, "bottom": 80.0},
        ]
        lines = [
            {"x0": 90.0, "y0": 742.0, "x1": 120.0, "y1": 737.0},
            {"x0": 120.0, "y0": 737.0, "x1": 114.0, "y1": 742.0},
            {"x0": 120.0, "y0": 737.0, "x1": 114.0, "y1": 732.0},
        ]

    class FakeDocument:
        pages = [FakePage()]

        def __enter__(self) -> "FakeDocument":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", lambda *_args, **_kwargs: FakeDocument())
    evidence = diagram_topology.extract_pdf_diagram_topology_evidence(
        b"bounded-pdf",
        structure,
        page_index=1,
    )

    assert evidence is not None
    assert len(evidence["nodes"]) == 2
    assert len(evidence["connectors"]) == 1
    assert evidence["connectors"][0]["source_node_source_object_id"].endswith(
        "rect:0"
    )
    assert evidence["connectors"][0]["target_node_source_object_id"].endswith(
        "rect:1"
    )
    assert len(
        evidence["connectors"][0]["arrowhead"]["source_object_ids"]
    ) == 2


def test_pdf_source_bytes_reach_the_producer_without_private_item_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagram = _diagram()
    del diagram["meta"]["phase05_diagram_topology_evidence"]
    seen: list[tuple[bytes, int]] = []

    def produce(
        source_pdf_bytes: bytes,
        _structure: VisualStructure,
        *,
        page_index: int,
    ) -> dict[str, Any]:
        seen.append((source_pdf_bytes, page_index))
        return _topology_evidence()

    monkeypatch.setattr(
        diagram_topology,
        "extract_pdf_diagram_topology_evidence",
        produce,
    )
    output = apply_visual_semantics(
        _payload(diagram),
        _settings(),
        source_document_bytes=b"owned-pdf-bytes",
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        output["pages"][0]["items"][0]["visual_structure"]
    )

    assert seen == [(b"owned-pdf-bytes", 1)]
    assert structure.fallback.active is False
    assert len(structure.connectors) == 2


@pytest.mark.parametrize("projection", ("metadata", "direct"))
def test_request_carried_vector_graph_cannot_authorize_invalid_current_bytes(
    projection: str,
) -> None:
    diagram = _diagram()
    evidence = diagram["meta"].pop("phase05_diagram_topology_evidence")
    if projection == "metadata":
        diagram["meta"]["phase05_diagram_topology_evidence"] = evidence
    else:
        diagram["diagram_topology_evidence"] = evidence

    output = apply_visual_semantics(
        _payload(diagram),
        _settings(),
        source_document_bytes=b"not-a-pdf",
        input_kind=InputKind.PDF,
    )

    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])
    assert structure.fallback.active is True
    assert structure.nodes == []
    assert structure.connectors == []
    assert "diagram_topology_evidence" not in item
    assert "phase05_diagram_topology_evidence" not in item.get("meta", {})


def test_pdf_producer_rejects_excess_geometry_without_prefix_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = apply_visual_semantics(
        _payload(_diagram()),
        _settings(topology=False),
        input_kind=InputKind.PDF,
    )
    structure = VisualStructure.model_validate(
        predecessor["pages"][0]["items"][0]["visual_structure"]
    )

    class ExcessPage:
        height = 792.0
        rects: list[dict[str, Any]] = []
        lines = [{} for _ in range(1_025)]

    class ExcessDocument:
        pages = [ExcessPage()]

        def __enter__(self) -> "ExcessDocument":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    import pdfplumber

    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda *_args, **_kwargs: ExcessDocument(),
    )
    with pytest.raises(ValueError, match="resource limit"):
        diagram_topology.extract_pdf_diagram_topology_evidence(
            b"bounded-pdf",
            structure,
            page_index=1,
        )


def test_strict_json_and_markdown_own_caption_once_without_table_item() -> None:
    output = _output()
    result = ParseResult.model_validate(output)
    encoded = result.model_dump_json(exclude_none=True)
    restored = ParseResult.model_validate_json(encoded)
    markdown = to_markdown(restored)

    assert json.loads(encoded)["pages"][0]["items"][0]["type"] == "diagram"
    assert not any(item.type == "table" for item in restored.pages[0].items)
    assert markdown.count("Approval flow") == 1
    assert markdown.count("### Nodes") == 1
    assert markdown.count("### Connections") == 1
    assert markdown.count("| Source | Direction | Target |") == 1
    assert "legacy diagram fallback" not in markdown


def test_flag_off_is_exact_us01_and_config_dependencies_are_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _payload(_diagram())
    predecessor = apply_visual_semantics(
        deepcopy(source),
        _settings(topology=False),
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        Settings(
            ocr_numeric_cleanup_v2_enabled=True,
            ocr_spatial_token_preservation_enabled=True,
            visual_structure_schema_enabled=True,
            diagrams_topology_enabled=False,
        ),
        input_kind=InputKind.PDF,
    )
    assert explicit_off == predecessor
    fallback = VisualStructure.model_validate(
        predecessor["pages"][0]["items"][0]["visual_structure"]
    )
    assert fallback.fallback.active is True
    assert fallback.nodes == fallback.connectors == []

    with pytest.raises(ValueError, match="PARSER_DIAGRAMS_TOPOLOGY_ENABLED"):
        Settings(
            visual_structure_schema_enabled=True,
            diagrams_topology_enabled=True,
        )
    monkeypatch.setenv("PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED", "true")
    monkeypatch.setenv("PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED", "true")
    monkeypatch.setenv("PARSER_DIAGRAMS_TOPOLOGY_ENABLED", "true")
    assert Settings.from_env().diagrams_topology_enabled is True


def test_all_phase05_feature_flags_default_off() -> None:
    settings = Settings()
    assert all(
        getattr(settings, name) is False
        for name in (
            "visual_structure_schema_enabled",
            "charts_vector_inventory_enabled",
            "charts_structure_enabled",
            "charts_vector_values_enabled",
            "charts_structured_output_enabled",
            "charts_raster_structure_enabled",
            "charts_raster_bar_values_enabled",
            "charts_raster_line_values_enabled",
            "charts_raster_analysis_enabled",
            "diagrams_topology_enabled",
        )
    )


def test_malformed_item_rolls_back_locally_without_orphan_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = _diagram(
        diagram_id="bad-diagram",
        evidence={"nodes": "not-a-list", "connectors": []},
    )
    valid = _diagram(diagram_id="good-diagram")
    evidence_by_id = {
        candidate["id"]: candidate["meta"].pop(
            "phase05_diagram_topology_evidence"
        )
        for candidate in (malformed, valid)
    }

    def produce(
        _source_pdf_bytes: bytes,
        structure: VisualStructure,
        *,
        page_index: int,
    ) -> dict[str, Any]:
        assert page_index == 1
        owner_ids = {
            record.provenance.public_item_id for record in structure.evidence
        }
        assert len(owner_ids) == 1
        return deepcopy(evidence_by_id[next(iter(owner_ids))])

    monkeypatch.setattr(
        diagram_topology,
        "extract_pdf_diagram_topology_evidence",
        produce,
    )
    table = _item("table", "owned-table", x=2.0)
    source = _payload(malformed, valid, table)
    output = apply_visual_semantics(
        deepcopy(source),
        _settings(),
        source_document_bytes=b"locally-owned-pdf",
        input_kind=InputKind.PDF,
    )
    by_id = {item["id"]: item for item in output["pages"][0]["items"]}
    bad = VisualStructure.model_validate(by_id["bad-diagram"]["visual_structure"])
    good = VisualStructure.model_validate(by_id["good-diagram"]["visual_structure"])

    assert bad.fallback.active is True
    assert bad.nodes == bad.connectors == []
    assert "diagram_topology_evidence_malformed" in {
        concern.code for concern in bad.concerns
    }
    assert good.fallback.active is False
    assert len(good.nodes) == 3 and len(good.connectors) == 2
    assert "visual_structure" not in by_id["owned-table"]


def test_representative_public_image_parse_emits_one_edge_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = _public_loaded_image()
    raw = _public_raw_layout()
    picture = raw["pictures"][0]
    picture["annotations"] = [{"kind": "layout", "label": "diagram"}]
    locally_derived_evidence = {
        "nodes": [
            {
                "source_object_id": "raw-node-a",
                "shape": "rectangle",
                "page_bbox": {
                    "x": 20.0,
                    "y": 35.0,
                    "width": 50.0,
                    "height": 30.0,
                    "unit": "px",
                },
                "label_source_token_id": "public-start",
            },
            {
                "source_object_id": "raw-node-b",
                "shape": "rectangle",
                "page_bbox": {
                    "x": 120.0,
                    "y": 35.0,
                    "width": 50.0,
                    "height": 30.0,
                    "unit": "px",
                },
                "label_source_token_id": "public-end",
            },
        ],
        "connectors": [
            {
                "source_object_id": "raw-edge-a-b",
                "source_node_source_object_id": "raw-node-a",
                "target_node_source_object_id": "raw-node-b",
                "path_points": [
                    {"x": 70.0, "y": 50.0},
                    {"x": 120.0, "y": 50.0},
                ],
                "arrowhead": {
                    "source_object_id": "raw-arrow-a-b",
                    "bbox": {
                        "x": 117.0,
                        "y": 47.0,
                        "width": 6.0,
                        "height": 6.0,
                        "unit": "px",
                    },
                    "tip": {"x": 120.0, "y": 50.0},
                },
            }
        ],
    }
    picture["meta"] = {}
    occurrences = [
        _occurrence("public-start", "Start", 30.0, 45.0, 25.0),
        _occurrence("public-end", "End", 135.0, 45.0, 20.0),
    ]
    for occurrence in occurrences:
        occurrence["bbox"]["unit"] = "px"
    summary = {
        "fail_closed_overflow": False,
        "source_token_limit_reached": False,
        "occurrence_limit_reached": False,
        "short_alternative_limit_reached": False,
        "serialized_byte_limit_reached": False,
    }
    monkeypatch.setattr(pipeline, "load_document", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (deepcopy(raw), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [_public_region()]},
    )
    monkeypatch.setattr(
        pipeline,
        "project_ocr_token_occurrences",
        lambda **_kwargs: (deepcopy(occurrences), deepcopy(summary)),
    )
    monkeypatch.setattr(
        "app.services.visual_raster_diagram.bind_raster_diagram_owner",
        lambda item, **_kwargs: RasterDiagramOwnerBinding(
            owner_id="locally-derived-image",
            owner_index=0,
            item=deepcopy(dict(item)),
        ),
    )
    monkeypatch.setattr(
        "app.services.visual_raster_diagram.derive_raster_diagram_topology_evidence",
        lambda *_args, **_kwargs: deepcopy(locally_derived_evidence),
    )

    result = pipeline.parse_document(
        b"request",
        "visual.png",
        _settings(canonical=True),
    )
    diagram = next(item for item in result.pages[0].items if item.type == "diagram")

    assert diagram.visual_structure is not None
    assert diagram.visual_structure.fallback.active is False
    assert diagram.visual_structure.serialization is not None
    assert diagram.visual_structure.serialization.status == "diagram_topology"
    assert len(diagram.visual_structure.nodes) == 2
    assert len(diagram.visual_structure.connectors) == 1
    assert "diagram_relationships_not_structured" not in (
        diagram.model_extra or {}
    ).get("parse_concerns", [])
    markdown = to_markdown(result)
    assert result.canonical_presentation is not None
    assert markdown.count("### Nodes") == 1
    assert markdown.count("| Source | Direction | Target |") == 1
