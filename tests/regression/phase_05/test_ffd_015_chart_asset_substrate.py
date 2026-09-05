"""FFD-015 source-asset, terminal-arbitration, and presentation regressions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import ValidationError

import app.models as public_models
from app.config import Settings
from app.models import ParseResult
from app.services import chart_assets
from app.services.chart_assets import (
    ChartAssetAttempt,
    ChartAssetLedger,
    ChartOwnerGeometryProof,
    ChartResolution,
    ChartSourceAsset,
    build_chart_resolution,
    chart_asset_limits,
    chart_resolution_markdown,
    prove_chart_owner_geometry,
    render_chart_source_asset,
)
from app.services.input_documents import InputKind, load_document
from app.services.ir import build_document_ir, round_trip_document
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown, to_text
from app.services.visual_contracts import VisualBoundingBox, VisualStructure
from app.services.visual_models import render_visual_model_crop
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_05.test_p05_us07_raster_bars import (
    _bar_evidence as _raster_bar_evidence,
)
from tests.stories.phase_05.test_p05_us07_raster_bars import (
    _chart as _raster_bar_chart,
)
from tests.stories.phase_05.test_p05_us07_raster_bars import (
    _settings as _raster_bar_settings,
)
from tests.stories.phase_05.test_p05_us07_raster_bars import (
    _source_payload as _raster_bar_payload,
)

WORKSPACE = Path(__file__).resolve().parents[3]
HEALTH_REPORT = WORKSPACE / "benchmark-expertmodeldata" / "health-report.pdf"
HEALTH_REPORT_SHA256 = (
    "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
)
HEALTH_CHART_OWNERS = (
    ("p1-i2", (44.802, 79.088, 496.730, 197.596)),
    ("p1-i6", (50.629, 352.723, 491.640, 201.810)),
)


def _box(
    coordinates: tuple[float, float, float, float],
    *,
    unit: str = "pt",
) -> VisualBoundingBox:
    x, y, width, height = coordinates
    return VisualBoundingBox(
        x=x,
        y=y,
        width=width,
        height=height,
        unit=unit,
    )


def _raw_owner_graph(
    bbox: VisualBoundingBox,
    owner_id: str,
) -> dict[str, Any]:
    return {
        "pictures": [
            {
                "self_ref": f"#/pictures/{owner_id}",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": bbox.x,
                            "t": bbox.y,
                            "r": bbox.x + bbox.width,
                            "b": bbox.y + bbox.height,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        ]
    }


def _strict_owner_proof(
    *,
    bbox: VisualBoundingBox,
    owner_id: str,
    input_kind: str,
    source_document_sha256: str,
    render_source_sha256: str | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
) -> ChartOwnerGeometryProof:
    """Build a strict raw-source proof instead of trusting the requested crop."""

    resolved_width = page_width or max(bbox.x + bbox.width + 1.0, 1.0)
    resolved_height = page_height or max(bbox.y + bbox.height + 1.0, 1.0)
    item = {
        "id": owner_id,
        "type": "chart",
        "content_type": "chart",
        "region_role": "content_region",
        "bbox": bbox.model_dump(mode="json"),
    }
    raw_graph = _raw_owner_graph(bbox, owner_id)
    proof = prove_chart_owner_geometry(
        item=item,
        page_items=[item],
        item_index=0,
        detected_images=None,
        raw_graph=raw_graph,
        page_index=1,
        page_width=resolved_width,
        page_height=resolved_height,
        page_unit=bbox.unit,
        input_kind=input_kind,
        source_document_sha256=source_document_sha256,
        render_source_sha256=render_source_sha256 or source_document_sha256,
    )
    assert proof is not None
    return proof


def _fallback_raw_graph() -> dict[str, Any]:
    return _raw_owner_graph(
        _box((10.0, 20.0, 100.0, 80.0)),
        "chart-asset-owner",
    )


def _external_caption_raw_graph(caption: str) -> dict[str, Any]:
    """Declare one same-page caption immediately above the chart owner."""

    return {
        "texts": [
            {
                "self_ref": "#/texts/chart-caption",
                "label": "caption",
                "text": caption,
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 5.0,
                            "r": 110.0,
                            "b": 15.0,
                            "coord_origin": "TOPLEFT",
                        },
                        "charspan": [0, len(caption)],
                    }
                ],
            }
        ],
        "pictures": [
            {
                "self_ref": "#/pictures/chart-asset-owner",
                "label": "chart",
                "captions": [{"$ref": "#/texts/chart-caption"}],
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 10.0,
                            "t": 20.0,
                            "r": 110.0,
                            "b": 100.0,
                            "coord_origin": "TOPLEFT",
                        },
                    }
                ],
            }
        ],
        "body": {
            "self_ref": "#/body",
            "children": [{"$ref": "#/pictures/chart-asset-owner"}],
        },
    }


def _chart_claim(owner_id: str, bbox: VisualBoundingBox) -> dict[str, Any]:
    return {
        "id": owner_id,
        "type": "chart",
        "content_type": "chart",
        "region_role": "content_region",
        "bbox": bbox.model_dump(mode="json"),
    }


def _p04_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _chart_owned_table_candidate(
    *,
    candidate_bbox: VisualBoundingBox,
    owner_bbox: VisualBoundingBox,
    owner_id: str,
    page_index: int,
) -> dict[str, Any]:
    """Build the exact bounded P04 singleton and gate replay fixture."""

    rows = [["A", "B"], ["1", "2"]]
    normalized_rows = [["a", "b"], ["1", "2"]]
    bbox = candidate_bbox.model_dump(mode="json")
    content_sha256 = _p04_digest(
        ["p04-us02-candidate-content-v1", normalized_rows, [], []]
    )
    candidate_id = _p04_digest(
        [
            "p04-us02-candidate-v1",
            page_index,
            "pdfplumber",
            bbox,
            2,
            2,
            content_sha256,
        ]
    )
    summary = {
        "candidate_id": candidate_id,
        "engine": "pdfplumber",
        "bbox": bbox,
        "rows": rows,
        "cells": [],
        "row_count": 2,
        "column_count": 2,
        "content_sha256": content_sha256,
    }
    reconciliation = {
        "cluster_id": _p04_digest(["p04-us02-cluster-v1", [candidate_id]]),
        "candidate_ids": [candidate_id],
        "selected_candidate_id": candidate_id,
        "outcome": "singleton",
        "absolute_threshold": 0.58,
        "selection_margin": 1.0,
        "scores": [
            {
                "candidate_id": candidate_id,
                "engine": "pdfplumber",
                "total": 0.857,
                "geometry": 0.65,
                "grid": 1.0,
                "cell_coverage": 1.0,
                "text_coverage": 1.0,
                "spans": 0.75,
                "provenance": 0.5,
                "bbox": bbox,
                "row_count": 2,
                "column_count": 2,
                "content_sha256": content_sha256,
                "candidate": summary,
            }
        ],
        "evidence_ids": [],
        "concern_codes": [],
    }
    gate_scores = {
        "alignment": 1.0,
        "cell_coverage": 1.0,
        "geometry": 0.75,
        "grid": 1.0,
        "owner_overlap": 1.0,
        "provenance": 0.85,
        "region_type": 1.0,
        "table_support": 0.933,
    }
    gate = {
        "decision_id": _p04_digest(
            [
                "p04-us04-gate-v1",
                candidate_id,
                "chart",
                [owner_id],
                gate_scores,
                [],
                ["table_candidate_chart_owned"],
            ]
        ),
        "candidate_id": candidate_id,
        "outcome": "chart",
        "owner_item_ids": [owner_id],
        "feature_scores": gate_scores,
        "evidence_ids": [],
        "concern_codes": ["table_candidate_chart_owned"],
    }
    return {
        "id": "superseded-table-candidate",
        "type": "table_candidate",
        "bbox": bbox,
        "engine": "pdfplumber",
        "rows": rows,
        "cells": [],
        "row_count": 2,
        "column_count": 2,
        "table_reconciliation": reconciliation,
        "table_candidate_gate": gate,
        "table_candidate_gate_reasons": ["typed_chart_owns_region"],
        "table_candidate_gate_sources": [
            {
                "owner_item_id": owner_id,
                "owner_type": "chart",
                "bbox": owner_bbox.model_dump(mode="json"),
                "overlap": 1.0,
            }
        ],
        "parse_concerns": ["table_candidate_chart_owned"],
    }


def _detected_pdf_owner(owner_id: str, bbox: VisualBoundingBox) -> dict[str, Any]:
    return {
        "id": owner_id,
        "type": "image",
        "bbox": bbox.model_dump(mode="json"),
        "region_role": "content_region",
        "region_origin": "pdf_page_render",
        "pixel_width": max(round(bbox.width * 2), 1),
        "pixel_height": max(round(bbox.height * 2), 1),
    }


def _source_png() -> tuple[bytes, list[tuple[int, int, int]]]:
    image = Image.new("RGB", (6, 4), (255, 0, 0))
    retained = [
        (1, 2, 3),
        (4, 5, 6),
        (7, 8, 9),
        (10, 11, 12),
        (13, 14, 15),
        (16, 17, 18),
        (19, 20, 21),
        (22, 23, 24),
    ]
    image.putdata(
        [
            *((255, 0, 0),) * 6,
            (255, 0, 0),
            *retained[:4],
            (255, 0, 0),
            (255, 0, 0),
            *retained[4:],
            (255, 0, 0),
            *((255, 0, 0),) * 6,
        ]
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    image.close()
    return output.getvalue(), retained


def _fallback_candidate(
    *,
    family: str = "bar_chart",
) -> tuple[dict[str, Any], VisualStructure]:
    source = _item(
        "chart",
        "chart-asset-owner",
        x=10.0,
        classification={"class_name": family, "confidence": 0.91},
    )
    source["visual_source_text"] = "2024 12\n2025 15"
    output = apply_visual_semantics(
        _payload(source),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    return item, VisualStructure.model_validate(item["visual_structure"])


def _complete_chart_png() -> bytes:
    image = Image.new("RGB", (200, 120), "white")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    image.close()
    return output.getvalue()


def _encoded_chart_image(image_format: str) -> bytes:
    image = Image.new("RGB", (200, 120))
    image.putdata(
        [
            (
                (x * 17 + y * 3) % 256,
                (x * 5 + y * 11) % 256,
                (x * 7 + y * 13) % 256,
            )
            for y in range(120)
            for x in range(200)
        ]
    )
    output = io.BytesIO()
    save_options: dict[str, Any] = {}
    if image_format == "JPEG":
        save_options = {"quality": 91, "subsampling": 0}
    elif image_format == "TIFF":
        save_options = {"compression": "tiff_deflate"}
    image.save(output, format=image_format, **save_options)
    image.close()
    return output.getvalue()


def _complete_source() -> tuple[dict[str, Any], bytes]:
    bars = _raster_bar_evidence()
    bars["bars"].append(
        {
            "source_object_id": "bar-2025-plan",
            "raster_pixel_bbox": {
                "x": 110.0,
                "y": 55.0,
                "width": 12.0,
                "height": 45.0,
                "unit": "px",
            },
            "axis_source_object_id": "axis-y",
            "category_label_source_token_id": "cat-c",
            "series_source_object_id": "series-plan",
            "mode": "grouped",
            "pixel_tolerance": 0.75,
        }
    )
    source = _raster_bar_payload(_raster_bar_chart(bars=bars))
    source["pages"][0]["items"][0]["classification"] = {
        "class_name": "bar_chart",
        "confidence": 0.99,
    }
    source_bytes = _complete_chart_png()
    source["document"].update(
        filename="complete-chart.png",
        mime_type="image/png",
        sha256=hashlib.sha256(source_bytes).hexdigest(),
    )
    source["pages"][0]["detected_images"] = [
        {
            "id": "uploaded-page-owner",
            "type": "image",
            "bbox": deepcopy(source["pages"][0]["items"][0]["bbox"]),
            "region_role": "page_source",
            "region_origin": "uploaded_page",
            "pixel_width": 200,
            "pixel_height": 120,
        }
    ]
    return source, source_bytes


def _complete_candidate() -> tuple[dict[str, Any], VisualStructure]:
    source, _source_bytes = _complete_source()
    output = apply_visual_semantics(
        source,
        _raster_bar_settings(structured=True),
        input_kind=InputKind.IMAGE,
    )
    item = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(item["visual_structure"])
    assert structure.fallback.active is False
    return item, structure


def _fallback_source() -> dict[str, Any]:
    source = _item(
        "chart",
        "chart-asset-owner",
        x=10.0,
        classification={"class_name": "bar_chart", "confidence": 0.91},
    )
    source["visual_source_text"] = "2024 12\n2025 15"
    payload = _payload(source)
    payload["document"]["sha256"] = HEALTH_REPORT_SHA256
    payload["pages"][0]["detected_images"] = [
        {
            "id": "synthetic-pdf-render-owner",
            "type": "image",
            "bbox": deepcopy(payload["pages"][0]["items"][0]["bbox"]),
            "region_role": "content_region",
            "region_origin": "pdf_page_render",
            "pixel_width": 200,
            "pixel_height": 160,
        }
    ]
    return payload


def _asset_settings(**overrides: Any) -> Settings:
    values = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "visual_structure_schema_enabled": True,
        "charts_source_asset_enabled": True,
        **overrides,
    }
    return Settings(**values)


def _retained_attempt(
    item: dict[str, Any],
    structure: VisualStructure,
) -> ChartAssetAttempt:
    if structure.region.page_bbox.unit == "px":
        source = _complete_chart_png()
        input_kind = "image"
        source_sha256 = hashlib.sha256(source).hexdigest()
    else:
        source = HEALTH_REPORT.read_bytes()
        input_kind = "pdf"
        source_sha256 = HEALTH_REPORT_SHA256
    owner_geometry_proof = _strict_owner_proof(
        bbox=structure.region.page_bbox,
        owner_id=item["id"],
        input_kind=input_kind,
        source_document_sha256=source_sha256,
        page_width=(
            595.276 if structure.region.page_bbox.unit == "pt" else 200.0
        ),
        page_height=(
            793.701 if structure.region.page_bbox.unit == "pt" else 120.0
        ),
    )
    return render_chart_source_asset(
        source=source,
        input_kind=input_kind,
        page_index=1,
        bbox=structure.region.page_bbox,
        owner_item_id=item["id"],
        source_document_sha256=source_sha256,
        owner_geometry_proof=owner_geometry_proof,
        limits=chart_asset_limits(Settings()),
        ledger=ChartAssetLedger(),
    )


def _resolve_complete_structure(
    item: dict[str, Any],
    structure: VisualStructure,
) -> ChartResolution:
    retained = _retained_attempt(item, structure)
    assert retained.asset is not None
    return build_chart_resolution(
        item=item,
        structure=structure,
        page_index=1,
        source_order=0,
        asset_attempt=retained,
        settings=_raster_bar_settings(structured=True),
    )


def _fallback_resolution_payload(
    *,
    owner_id: str = "chart-asset-owner",
    x: float = 10.0,
    source_order: int = 0,
) -> dict[str, Any]:
    source = _item(
        "chart",
        owner_id,
        x=x,
        classification={"class_name": "bar_chart", "confidence": 0.91},
    )
    source["visual_source_text"] = "2024 12\n2025 15"
    payload = _payload(source)
    payload["document"]["sha256"] = HEALTH_REPORT_SHA256
    output = apply_visual_semantics(
        payload,
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    item = output["pages"][0]["items"][0]
    item["reading_order"] = source_order
    structure = VisualStructure.model_validate(item["visual_structure"])
    resolution = build_chart_resolution(
        item=item,
        structure=structure,
        page_index=1,
        source_order=source_order,
        asset_attempt=_retained_attempt(item, structure),
        settings=Settings(),
    )
    item["chart_resolution"] = resolution.model_dump(mode="json")
    return output


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_source_asset_flag_off_preserves_exact_predecessor_payload() -> None:
    source = _fallback_source()
    source_bytes = HEALTH_REPORT.read_bytes()
    predecessor = apply_visual_semantics(
        deepcopy(source),
        Settings(visual_structure_schema_enabled=True),
        source_document_bytes=source_bytes,
        input_kind=InputKind.PDF,
    )
    explicit_off = apply_visual_semantics(
        deepcopy(source),
        _asset_settings(charts_source_asset_enabled=False),
        source_document_bytes=source_bytes,
        input_kind=InputKind.PDF,
    )

    assert _canonical_bytes(explicit_off) == _canonical_bytes(predecessor)
    assert "chart_resolution" not in explicit_off["pages"][0]["items"][0]


@pytest.mark.parametrize(
    ("owner_field", "owner_value"),
    (
        ("rows", [["Year", "Amount"]]),
        ("fields", [{"name": "Amount", "value": "12"}]),
        ("table_evidence", {"status": "accepted"}),
    ),
)
def test_declared_chart_with_tabular_or_form_ownership_is_excluded(
    owner_field: str,
    owner_value: Any,
) -> None:
    source = _fallback_source()
    source["pages"][0]["items"][0][owner_field] = owner_value
    predecessor = deepcopy(source)

    output = apply_visual_semantics(
        source,
        _asset_settings(),
        source_document_bytes=HEALTH_REPORT.read_bytes(),
        input_kind=InputKind.PDF,
    )

    assert _canonical_bytes(output) == _canonical_bytes(predecessor)
    assert "visual_structure" not in output["pages"][0]["items"][0]
    assert "chart_resolution" not in output["pages"][0]["items"][0]


@pytest.mark.integration
def test_fallback_chart_retains_source_image_as_the_only_terminal_primary() -> None:
    output = apply_visual_semantics(
        _fallback_source(),
        _asset_settings(),
        source_document_bytes=HEALTH_REPORT.read_bytes(),
        input_kind=InputKind.PDF,
        raw_graph=_fallback_raw_graph(),
    )
    result = ParseResult.model_validate(output)
    item = result.pages[0].items[0]
    assert item.chart_resolution is not None
    resolution = item.chart_resolution
    assert resolution.status == "image_primary_unsupported"
    assert resolution.primary_representation == "source_image"
    assert resolution.asset is not None
    assert resolution.asset.owner_item_id == item.id
    assert resolution.asset.physical_page == 1
    assert resolution.asset.source_document_sha256 == HEALTH_REPORT_SHA256
    assert resolution.asset.render_source_sha256 == HEALTH_REPORT_SHA256
    assert resolution.asset.owner_geometry_proof_kind == (
        "detected_image_and_docling_picture"
    )
    assert resolution.asset.owner_geometry_evidence_ids == [
        "detected:synthetic-pdf-render-owner",
        "docling:#/pictures/chart-asset-owner",
    ]
    assert len(resolution.asset.owner_geometry_evidence_sha256) == 64

    expected_markdown = chart_resolution_markdown(
        resolution,
        caption=item.caption,
    )
    assert expected_markdown is not None
    direct_markdown = to_markdown(result)
    direct_text = to_text(result)
    assert direct_markdown == f"{expected_markdown}\n"
    assert direct_markdown.count("data:image/png;base64,") == 1
    assert resolution.transcript.text is not None
    assert resolution.transcript.text not in direct_markdown
    assert direct_text == f"{resolution.transcript.text}\n"

    canonical = build_canonical_presentation(build_document_ir(output))
    assert len(canonical.pages[0].blocks) == 1
    block = canonical.pages[0].blocks[0]
    assert block.markdown == expected_markdown
    assert block.text == resolution.transcript.text
    assert canonical.full.markdown == direct_markdown
    assert canonical.full.markdown.count("data:image/png;base64,") == 1
    assert canonical.full.text == direct_text


@pytest.mark.integration
def test_image_primary_chart_external_caption_is_exactly_once_and_linked() -> None:
    """P03 externalization must not duplicate an FFD-015 image caption."""

    caption = "chart caption"
    payload = _fallback_resolution_payload()
    source_owner = payload["pages"][0]["items"][0]
    source_resolution = ChartResolution.model_validate(
        source_owner["chart_resolution"],
        strict=True,
    )
    assert source_owner["caption"] == caption
    assert source_resolution.status == "image_primary_unsupported"
    assert source_resolution.asset_status == "retained"

    settings = _asset_settings(layout_visual_relationships_enabled=True)
    projected, ir = round_trip_document(
        payload,
        raw_graph=_external_caption_raw_graph(caption),
        native_texts=(caption,),
        layout_settings=settings,
    )
    validated = ParseResult.model_validate(projected)
    [external_caption] = [
        item
        for item in validated.pages[0].items
        if item.type.casefold() == "caption"
    ]
    [chart_owner] = [
        item
        for item in validated.pages[0].items
        if item.type.casefold() == "chart"
    ]
    relationship_id = external_caption.relationship_id
    assert relationship_id is not None
    assert relationship_id.startswith("layout-rel-")
    owner_caption = getattr(chart_owner, "caption", None)
    assert owner_caption is None
    assert chart_owner.caption_ids == [external_caption.id]
    assert chart_owner.chart_resolution is not None
    owner_markdown = chart_resolution_markdown(
        chart_owner.chart_resolution,
        caption=owner_caption,
    )
    assert owner_markdown is not None
    assert caption not in owner_markdown

    raw_markdown = to_markdown(validated)
    canonical = build_canonical_presentation(ir)
    caption_block = next(
        block
        for block in canonical.pages[0].blocks
        if block.primary_element_type.casefold() == "caption"
        and block.omission_reason is None
    )
    chart_block = next(
        block
        for block in canonical.pages[0].blocks
        if block.primary_element_type.casefold() == "chart"
        and block.omission_reason is None
    )

    assert raw_markdown.count(caption) == 1
    assert raw_markdown.count("data:image/png;base64,") == 1
    assert canonical.full.markdown == raw_markdown
    assert canonical.full.markdown.count(caption) == 1
    assert canonical.full.markdown.count("data:image/png;base64,") == 1
    assert caption_block.markdown == caption
    assert caption not in chart_block.markdown
    assert relationship_id in caption_block.relationship_ids
    assert relationship_id in chart_block.relationship_ids

    # Both the public layout graph and its canonical replay are stable when
    # the complete compatibility document re-enters the P03 projection.
    reprojected, reprojected_ir = round_trip_document(
        projected,
        raw_graph=_external_caption_raw_graph(caption),
        native_texts=(caption,),
        layout_settings=settings,
    )
    assert reprojected == projected
    assert build_canonical_presentation(reprojected_ir) == canonical

    # A stale owner descriptor cannot be laundered into canonical evidence.
    stale_ir = ir.model_copy(deep=True)
    stale_owner = next(
        element
        for element in stale_ir.elements
        if (element.properties.get("legacy_item") or {}).get("id")
        == chart_owner.id
    )
    stale_legacy = deepcopy(stale_owner.properties["legacy_item"])
    stale_descriptor = next(
        descriptor
        for descriptor in stale_legacy["relationships"]
        if descriptor.get("type") == "caption_of"
    )
    stale_relationship_id = "layout-rel-stale-caption"
    stale_descriptor["id"] = stale_relationship_id
    stale_owner.properties["legacy_item"] = stale_legacy
    stale_caption = next(
        element
        for element in stale_ir.elements
        if (element.properties.get("legacy_item") or {}).get("id")
        == external_caption.id
    )
    stale_caption_legacy = deepcopy(stale_caption.properties["legacy_item"])
    stale_caption_legacy["relationship_id"] = stale_relationship_id
    stale_caption.properties["legacy_item"] = stale_caption_legacy
    stale_caption_projection = deepcopy(
        stale_caption.properties["layout_projection"]
    )
    stale_caption_projection["relationship_id"] = stale_relationship_id
    stale_caption.properties["layout_projection"] = stale_caption_projection

    stale_canonical = build_canonical_presentation(stale_ir)
    stale_block_ids = {
        relationship
        for page in stale_canonical.pages
        for block in page.blocks
        for relationship in block.relationship_ids
    }
    assert stale_relationship_id not in stale_block_ids


@pytest.mark.integration
def test_complete_chart_keeps_structured_primary_with_supplemental_asset() -> None:
    source, source_bytes = _complete_source()
    output = apply_visual_semantics(
        source,
        replace(
            _raster_bar_settings(structured=True),
            charts_source_asset_enabled=True,
        ),
        source_document_bytes=source_bytes,
        input_kind=InputKind.IMAGE,
    )
    result = ParseResult.model_validate(output)
    item = result.pages[0].items[0]
    assert item.chart_resolution is not None
    assert item.visual_structure is not None
    resolution = item.chart_resolution
    structure = item.visual_structure
    assert resolution.status == "structured_primary"
    assert resolution.primary_representation == "structured_chart"
    assert resolution.asset is not None
    assert structure.serialization is not None
    expected_markdown = structure.serialization.markdown

    direct_markdown = to_markdown(result)
    direct_text = to_text(result)
    assert direct_markdown == f"{expected_markdown.rstrip()}\n"
    assert direct_text == f"{expected_markdown.rstrip()}\n"
    assert (
        direct_markdown.count("| Category | Series | Value | Method | Tolerance |") == 1
    )
    assert item.caption is not None
    assert direct_markdown.count(item.caption) == 1
    assert "data:image/png;base64," not in direct_markdown
    assert resolution.asset.data_uri not in direct_markdown

    canonical = build_canonical_presentation(build_document_ir(output))
    assert len(canonical.pages[0].blocks) == 1
    block = canonical.pages[0].blocks[0]
    assert block.markdown == expected_markdown.strip()
    assert block.text == expected_markdown.strip()
    assert canonical.full.markdown == direct_markdown
    assert canonical.full.text == direct_text
    assert resolution.asset.data_uri not in canonical.full.markdown


@pytest.mark.integration
@pytest.mark.parametrize("evidence_kind", ("mark", "path", "point"))
def test_orphan_source_mark_path_or_point_blocks_structured_promotion(
    evidence_kind: str,
) -> None:
    item, complete = _complete_candidate()
    payload = complete.model_dump(mode="json", exclude_none=True)
    template = next(
        evidence for evidence in payload["evidence"] if evidence["kind"] == "mark"
    )
    orphan = deepcopy(template)
    orphan["id"] = f"orphan-{evidence_kind}-evidence"
    orphan["kind"] = evidence_kind
    orphan["provenance"]["source_object_ids"] = [f"orphan-{evidence_kind}-source"]
    orphan["provenance"]["source_token_ids"] = []
    payload["evidence"].append(orphan)
    structure = VisualStructure.model_validate(payload)

    resolution = _resolve_complete_structure(item, structure)

    assert resolution.asset_status == "retained"
    assert resolution.asset is not None
    assert resolution.status == "image_primary_incomplete"
    assert resolution.primary_representation == "source_image"
    assert resolution.semantic_analysis.completeness_gate_status == "failed"
    assert "ownership" in resolution.semantic_analysis.missing_features


@pytest.mark.integration
def test_fabricated_serialization_cannot_replace_point_derived_canonical_output() -> (
    None
):
    item, complete = _complete_candidate()
    payload = complete.model_dump(mode="json", exclude_none=True)
    deterministic_markdown = payload["serialization"]["markdown"]
    payload["serialization"]["markdown"] = (
        f"{deterministic_markdown}| fabricated | series | 999 | guessed | +/-0 |\n"
    )
    structure = VisualStructure.model_validate(payload)
    assert structure.serialization is not None
    assert structure.serialization.markdown != deterministic_markdown

    resolution = _resolve_complete_structure(item, structure)

    assert resolution.asset_status == "retained"
    assert resolution.asset is not None
    assert resolution.status == "image_primary_incomplete"
    assert resolution.primary_representation == "source_image"
    assert resolution.semantic_analysis.completeness_gate_status == "failed"
    assert "serialization" in resolution.semantic_analysis.missing_features


@pytest.mark.integration
@pytest.mark.parametrize(
    ("code", "severity", "stage"),
    (
        ("vector_primitive_limit_reached", "warning", "vector_inventory"),
        ("unrecognized_oracle_concern", "info", "schema"),
        ("visual_classifier_unavailable", "warning", "schema"),
    ),
)
def test_unknown_or_noninformational_concern_blocks_structured_promotion(
    code: str,
    severity: str,
    stage: str,
) -> None:
    item, complete = _complete_candidate()
    payload = complete.model_dump(mode="json", exclude_none=True)
    payload["concerns"].append(
        {
            "code": code,
            "severity": severity,
            "stage": stage,
            "evidence_ids": list(payload["region"]["evidence_ids"]),
        }
    )
    structure = VisualStructure.model_validate(payload)

    resolution = _resolve_complete_structure(item, structure)

    assert resolution.asset_status == "retained"
    assert resolution.asset is not None
    assert resolution.status == "image_primary_incomplete"
    assert resolution.primary_representation == "source_image"
    assert resolution.semantic_analysis.completeness_gate_status == "failed"
    assert "ambiguity_closure" in resolution.semantic_analysis.missing_features


@pytest.mark.integration
@pytest.mark.parametrize(
    ("image_format", "filename"),
    (("JPEG", "normalized-source.jpg"), ("TIFF", "normalized-source.tiff")),
)
def test_normalized_raster_binds_upload_and_processing_hashes_through_parse_result(
    image_format: str,
    filename: str,
) -> None:
    original_bytes = _encoded_chart_image(image_format)
    loaded = load_document(original_bytes, filename, Settings())
    original_sha256 = hashlib.sha256(loaded.original_bytes).hexdigest()
    processing_sha256 = hashlib.sha256(loaded.processing_bytes).hexdigest()

    assert loaded.kind is InputKind.IMAGE
    assert loaded.original_bytes == original_bytes
    assert loaded.processing_bytes != loaded.original_bytes
    assert processing_sha256 != original_sha256

    source, _unused_png = _complete_source()
    source["document"].update(
        filename=loaded.original_filename,
        mime_type=loaded.mime_type,
        sha256=original_sha256,
        render_source_sha256=processing_sha256,
    )
    output = apply_visual_semantics(
        source,
        replace(
            _raster_bar_settings(structured=True),
            charts_source_asset_enabled=True,
        ),
        source_document_bytes=loaded.processing_bytes,
        input_kind=loaded.kind,
    )

    result = ParseResult.model_validate(output)
    resolution = result.pages[0].items[0].chart_resolution
    assert result.document.sha256 == original_sha256
    assert result.document.render_source_sha256 == processing_sha256
    assert resolution is not None
    assert resolution.asset is not None
    assert resolution.asset.source_document_sha256 == original_sha256
    assert resolution.asset.render_source_sha256 == processing_sha256
    assert resolution.asset.source_document_sha256 != (
        resolution.asset.render_source_sha256
    )


def test_asset_refusal_is_terminal_and_skips_all_chart_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import chart_assets, visual_source_text

    source = _fallback_source()
    predecessor = apply_visual_semantics(
        deepcopy(source),
        Settings(visual_structure_schema_enabled=True),
        source_document_bytes=None,
        input_kind=InputKind.PDF,
    )
    predecessor_canonical = build_canonical_presentation(build_document_ir(predecessor))

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("chart analysis ran after source-asset refusal")

    monkeypatch.setattr(chart_assets, "classify_chart_family", forbidden)
    monkeypatch.setattr(chart_assets, "classify_chart_complexity", forbidden)
    monkeypatch.setattr(visual_source_text, "structure_source_text_chart", forbidden)
    output = apply_visual_semantics(
        deepcopy(source),
        _asset_settings(),
        source_document_bytes=None,
        input_kind=InputKind.PDF,
    )
    candidate = deepcopy(output["pages"][0]["items"][0])
    resolution = ChartResolution.model_validate(candidate.pop("chart_resolution"))

    assert candidate == predecessor["pages"][0]["items"][0]
    assert resolution.status == "asset_unavailable"
    assert resolution.asset_status == "unavailable"
    assert resolution.asset is None
    assert resolution.asset_unavailable_reason == "source_bytes_unavailable"
    assert resolution.primary_representation == "grounded_predecessor"
    assert resolution.family_classification.status == "not_run"
    assert resolution.family_classification.reason_codes == ["asset_unavailable"]
    assert resolution.complexity_classification.status == "not_run"
    assert resolution.complexity_classification.reason_codes == ["asset_unavailable"]
    assert resolution.semantic_analysis.attempt_status == ("not_run_asset_unavailable")
    assert resolution.semantic_analysis.failure_reason == "asset_unavailable"

    result = ParseResult.model_validate(output)
    assert to_markdown(result) == "chart visible text\n"
    assert resolution.transcript.text is not None
    assert to_text(result) == f"{resolution.transcript.text}\n"
    canonical = build_canonical_presentation(build_document_ir(output))
    assert canonical.model_dump(mode="json") == predecessor_canonical.model_dump(
        mode="json"
    )
    assert "data:image/png;base64," not in canonical.full.markdown


@pytest.mark.integration
def test_source_text_analyzer_failure_after_render_preserves_retained_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import visual_source_text

    recovered_text = "2024 12\n2025 15"
    recovered = {
        "method": "pdf_text_layer_inside_visual_bbox",
        "text": recovered_text,
        "text_sha256": hashlib.sha256(recovered_text.encode("utf-8")).hexdigest(),
        "occurrences": [],
        "lines": [],
    }
    events: list[str] = []
    retained_asset_ids: list[str] = []
    render = chart_assets.render_chart_source_asset

    def tracked_render(**kwargs: Any) -> ChartAssetAttempt:
        attempt = render(**kwargs)
        assert attempt.asset is not None
        events.append("asset_retained")
        retained_asset_ids.append(attempt.asset.asset_id)
        return attempt

    def fail_source_text_analysis(*_args: Any, **_kwargs: Any) -> Any:
        events.append("source_text_failed")
        raise ValueError("synthetic source-text analyzer failure")

    monkeypatch.setattr(
        visual_source_text,
        "recover_pdf_visual_source_text",
        lambda *_args, **_kwargs: deepcopy(recovered),
    )
    monkeypatch.setattr(
        visual_source_text,
        "structure_source_text_chart",
        fail_source_text_analysis,
    )
    monkeypatch.setattr(chart_assets, "render_chart_source_asset", tracked_render)
    settings = _asset_settings(
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
        charts_structured_output_enabled=True,
    )

    output = apply_visual_semantics(
        _fallback_source(),
        settings,
        source_document_bytes=HEALTH_REPORT.read_bytes(),
        input_kind=InputKind.PDF,
        raw_graph=_fallback_raw_graph(),
    )
    result = ParseResult.model_validate(output)
    item = result.pages[0].items[0]
    resolution = item.chart_resolution

    assert events[:2] == ["asset_retained", "source_text_failed"]
    assert resolution is not None
    assert resolution.asset_status == "retained"
    assert resolution.asset is not None
    assert retained_asset_ids == [resolution.asset.asset_id]
    assert resolution.asset.source_document_sha256 == HEALTH_REPORT_SHA256
    assert resolution.status == "image_primary_incomplete"
    assert resolution.primary_representation == "source_image"
    assert resolution.semantic_analysis.completeness_gate_status == "failed"
    assert item.visual_structure is not None
    assert item.visual_structure.fallback.active is True
    assert item.visual_structure.fallback.reason == "validation_failed"
    assert "chart_source_text_failed_closed" in {
        concern.code for concern in item.visual_structure.concerns
    }


@pytest.mark.integration
@pytest.mark.parametrize(("owner_id", "coordinates"), HEALTH_CHART_OWNERS)
def test_health_chart_owner_crop_is_deterministic_and_integrity_bound(
    owner_id: str,
    coordinates: tuple[float, float, float, float],
) -> None:
    source = HEALTH_REPORT.read_bytes()
    assert hashlib.sha256(source).hexdigest() == HEALTH_REPORT_SHA256
    source_bbox = _box(coordinates)
    owner_geometry_proof = _strict_owner_proof(
        bbox=source_bbox,
        owner_id=owner_id,
        input_kind="pdf",
        source_document_sha256=HEALTH_REPORT_SHA256,
        page_width=595.276,
        page_height=793.701,
    )

    first_attempt = render_chart_source_asset(
        source=source,
        input_kind="pdf",
        page_index=1,
        bbox=source_bbox,
        owner_item_id=owner_id,
        source_document_sha256=HEALTH_REPORT_SHA256,
        owner_geometry_proof=owner_geometry_proof,
        limits=chart_asset_limits(Settings()),
        ledger=ChartAssetLedger(),
    )
    second_attempt = render_chart_source_asset(
        source=source,
        input_kind="pdf",
        page_index=1,
        bbox=source_bbox,
        owner_item_id=owner_id,
        source_document_sha256=HEALTH_REPORT_SHA256,
        owner_geometry_proof=owner_geometry_proof,
        limits=chart_asset_limits(Settings()),
        ledger=ChartAssetLedger(),
    )
    assert first_attempt.unavailable_reason is None
    assert second_attempt.unavailable_reason is None
    assert first_attempt.asset is not None
    assert second_attempt.asset is not None
    public_asset = first_attempt.asset
    retained_bytes = base64.b64decode(
        public_asset.data_uri.removeprefix("data:image/png;base64,"),
        validate=True,
    )
    assert second_attempt.asset == public_asset
    assert public_asset.source_document_sha256 == HEALTH_REPORT_SHA256
    assert public_asset.render_source_sha256 == HEALTH_REPORT_SHA256
    assert public_asset.owner_item_id == owner_id
    assert public_asset.physical_page == 1
    assert public_asset.source_bbox == _box(coordinates)
    assert public_asset.byte_length == len(retained_bytes)
    assert public_asset.sha256 == hashlib.sha256(retained_bytes).hexdigest()
    assert retained_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    scale = public_asset.render_scale
    source_box = public_asset.source_bbox
    rendered_box = public_asset.rendered_bbox
    assert scale == 2.0
    pixel_width = rendered_box.width / public_asset.width
    pixel_height = rendered_box.height / public_asset.height
    expansion = (
        source_box.x - rendered_box.x,
        source_box.y - rendered_box.y,
        rendered_box.x + rendered_box.width - source_box.x - source_box.width,
        rendered_box.y + rendered_box.height - source_box.y - source_box.height,
    )
    assert 0.0 <= expansion[0] < pixel_width
    assert 0.0 <= expansion[1] < pixel_height
    assert 0.0 <= expansion[2] < pixel_width
    assert 0.0 <= expansion[3] < pixel_height
    assert public_asset.pixel_to_page_transform == [
        pixel_width,
        0.0,
        0.0,
        pixel_height,
        rendered_box.x,
        rendered_box.y,
    ]
    assert public_asset.page_device_dimensions is not None
    assert public_asset.crop_device_margins is not None
    page_width, page_height = public_asset.page_device_dimensions
    left, bottom, right, top = public_asset.crop_device_margins
    assert min(page_width, page_height) > 0
    assert min(left, bottom, right, top) >= 0
    assert public_asset.width == page_width - left - right
    assert public_asset.height == page_height - bottom - top

    with Image.open(io.BytesIO(retained_bytes)) as decoded:
        decoded.load()
        assert decoded.format == "PNG"
        assert decoded.mode == "RGB"
        assert decoded.size == (public_asset.width, public_asset.height)


def test_pdf_detected_image_cannot_self_authorize_without_raw_source_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detector derived from a requested crop is corroboration, not proof."""

    source_bbox = _box(HEALTH_CHART_OWNERS[1][1])
    item = _chart_claim("renamed-lower-chart", source_bbox)
    proof = prove_chart_owner_geometry(
        item=item,
        page_items=[item],
        item_index=0,
        detected_images=[_detected_pdf_owner("detector-only", source_bbox)],
        raw_graph=None,
        page_index=1,
        page_width=595.276,
        page_height=793.701,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256=HEALTH_REPORT_SHA256,
        render_source_sha256=HEALTH_REPORT_SHA256,
    )
    assert proof is None

    spawn_calls: list[tuple[Any, ...]] = []

    def forbidden_spawn(*args: Any, **_kwargs: Any) -> Any:
        spawn_calls.append(args)
        raise AssertionError("unproved geometry spawned a renderer")

    monkeypatch.setattr(chart_assets.multiprocessing, "get_context", forbidden_spawn)
    attempt = render_chart_source_asset(
        source=HEALTH_REPORT.read_bytes(),
        input_kind="pdf",
        page_index=1,
        bbox=source_bbox,
        owner_item_id=item["id"],
        source_document_sha256=HEALTH_REPORT_SHA256,
        owner_geometry_proof=proof,
        limits=chart_asset_limits(Settings()),
        ledger=ChartAssetLedger(),
    )
    assert attempt == ChartAssetAttempt(None, "owner_geometry_invalid")
    assert spawn_calls == []


def test_clipped_health_bbox_cannot_retain_against_complete_source_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    complete_bbox = _box(HEALTH_CHART_OWNERS[1][1])
    clipped_bbox = _box((72.626, 357.691, 461.416, 170.764))
    item = _chart_claim("renamed-clipped-chart", clipped_bbox)
    proof = prove_chart_owner_geometry(
        item=item,
        page_items=[item],
        item_index=0,
        detected_images=[_detected_pdf_owner("complete-lower-owner", complete_bbox)],
        raw_graph=_raw_owner_graph(complete_bbox, "complete-lower-owner"),
        page_index=1,
        page_width=595.276,
        page_height=793.701,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256=HEALTH_REPORT_SHA256,
        render_source_sha256=HEALTH_REPORT_SHA256,
    )
    assert proof is None

    def forbidden_spawn(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a clipped crop spawned a renderer")

    monkeypatch.setattr(chart_assets.multiprocessing, "get_context", forbidden_spawn)
    attempt = render_chart_source_asset(
        source=HEALTH_REPORT.read_bytes(),
        input_kind="pdf",
        page_index=1,
        bbox=clipped_bbox,
        owner_item_id=item["id"],
        source_document_sha256=HEALTH_REPORT_SHA256,
        owner_geometry_proof=proof,
        limits=chart_asset_limits(Settings()),
        ledger=ChartAssetLedger(),
    )
    assert attempt == ChartAssetAttempt(None, "owner_geometry_invalid")


def test_transformed_docling_bbox_proves_renamed_pdf_owner_generically() -> None:
    source_bbox = _box((123.456, 234.567, 210.125, 111.375))
    page_height = 792.0
    item = _chart_claim("arbitrary-renamed-owner", source_bbox)
    unrelated = _raw_owner_graph(_box((20.0, 30.0, 40.0, 50.0)), "other")
    raw_graph = _raw_owner_graph(source_bbox, "source-object-17")
    record_bbox = raw_graph["pictures"][0]["prov"][0]["bbox"]
    record_bbox.update(
        t=page_height - source_bbox.y,
        b=page_height - source_bbox.y - source_bbox.height,
        coord_origin="BOTTOMLEFT",
    )
    raw_graph["pictures"].extend(unrelated["pictures"])

    proof = prove_chart_owner_geometry(
        item=item,
        page_items=[item],
        item_index=0,
        detected_images=None,
        raw_graph=raw_graph,
        page_index=1,
        page_width=612.0,
        page_height=page_height,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="1" * 64,
        render_source_sha256="2" * 64,
    )

    assert proof is not None
    assert proof.owner_item_id == "arbitrary-renamed-owner"
    assert proof.owner_bbox == source_bbox
    assert proof.proof_kind == "docling_picture"
    assert proof.source_evidence_ids == ["docling:#/pictures/source-object-17"]


@pytest.mark.parametrize(
    "conflict",
    ("duplicate_source", "incomplete_source", "table", "form"),
)
def test_chart_owner_geometry_conflict_fails_closed(conflict: str) -> None:
    source_bbox = _box((80.0, 100.0, 300.0, 160.0))
    chart = _chart_claim("chart-owner", source_bbox)
    page_items = [chart]
    raw_graph = _raw_owner_graph(source_bbox, "source-owner")
    if conflict == "duplicate_source":
        duplicate = deepcopy(raw_graph["pictures"][0])
        duplicate["self_ref"] = "#/pictures/duplicate-owner"
        raw_graph["pictures"].append(duplicate)
    elif conflict == "incomplete_source":
        del raw_graph["pictures"][0]["prov"][0]["bbox"]["coord_origin"]
    else:
        page_items.append(
            {
                "id": f"competing-{conflict}",
                "type": conflict,
                "bbox": source_bbox.model_dump(mode="json"),
            }
        )

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=page_items,
        item_index=0,
        detected_images=None,
        raw_graph=raw_graph,
        page_index=1,
        page_width=612.0,
        page_height=792.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="3" * 64,
        render_source_sha256="3" * 64,
    )

    assert proof is None


def test_authoritative_table_with_full_table_and_eighty_percent_chart_overlap_blocks_owner() -> (
    None
):
    chart_bbox = _box((10.0, 20.0, 100.0, 100.0))
    table_bbox = _box((20.0, 20.0, 80.0, 100.0))
    chart = _chart_claim("chart-owner", chart_bbox)
    authoritative_table = {
        "id": "table-owner",
        "type": "table",
        "bbox": table_bbox.model_dump(mode="json"),
        "rows": [["A", "B"]],
    }

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart, authoritative_table],
        item_index=0,
        detected_images=None,
        raw_graph=_raw_owner_graph(chart_bbox, "chart-owner"),
        page_index=1,
        page_width=300.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="a" * 64,
        render_source_sha256="a" * 64,
    )

    assert proof is None


def test_sealed_chart_owned_table_candidate_does_not_conflict_with_its_owner() -> (
    None
):
    chart_bbox = _box((10.0, 20.0, 100.0, 100.0))
    candidate_bbox = _box((20.0, 20.0, 80.0, 100.0))
    chart = _chart_claim("chart-owner", chart_bbox)
    superseded_candidate = _chart_owned_table_candidate(
        candidate_bbox=candidate_bbox,
        owner_bbox=chart_bbox,
        owner_id="chart-owner",
        page_index=1,
    )

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart, superseded_candidate],
        item_index=0,
        detected_images=None,
        raw_graph=_raw_owner_graph(chart_bbox, "chart-owner"),
        page_index=1,
        page_width=300.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="d" * 64,
        render_source_sha256="d" * 64,
    )

    assert proof is not None


@pytest.mark.parametrize("forged_field", ("decision_id", "candidate_id"))
def test_forged_chart_owned_table_candidate_gate_cannot_exempt_overlap(
    forged_field: str,
) -> None:
    chart_bbox = _box((10.0, 20.0, 100.0, 100.0))
    candidate_bbox = _box((20.0, 20.0, 80.0, 100.0))
    chart = _chart_claim("chart-owner", chart_bbox)
    forged_candidate = _chart_owned_table_candidate(
        candidate_bbox=candidate_bbox,
        owner_bbox=chart_bbox,
        owner_id="chart-owner",
        page_index=1,
    )
    forged_candidate["table_candidate_gate"][forged_field] = "f" * 64

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart, forged_candidate],
        item_index=0,
        detected_images=None,
        raw_graph=_raw_owner_graph(chart_bbox, "chart-owner"),
        page_index=1,
        page_width=300.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="d" * 64,
        render_source_sha256="d" * 64,
    )

    assert proof is None


def test_resealed_gate_with_forged_candidate_content_digest_cannot_exempt_overlap() -> (
    None
):
    chart_bbox = _box((10.0, 20.0, 100.0, 100.0))
    candidate_bbox = _box((20.0, 20.0, 80.0, 100.0))
    chart = _chart_claim("chart-owner", chart_bbox)
    forged_candidate = _chart_owned_table_candidate(
        candidate_bbox=candidate_bbox,
        owner_bbox=chart_bbox,
        owner_id="chart-owner",
        page_index=1,
    )
    reconciliation = forged_candidate["table_reconciliation"]
    score = reconciliation["scores"][0]
    summary = score["candidate"]
    forged_content_sha256 = "e" * 64
    forged_candidate_id = _p04_digest(
        [
            "p04-us02-candidate-v1",
            1,
            "pdfplumber",
            candidate_bbox.model_dump(mode="json"),
            2,
            2,
            forged_content_sha256,
        ]
    )
    reconciliation["candidate_ids"] = [forged_candidate_id]
    reconciliation["selected_candidate_id"] = forged_candidate_id
    reconciliation["cluster_id"] = _p04_digest(
        ["p04-us02-cluster-v1", [forged_candidate_id]]
    )
    score["candidate_id"] = forged_candidate_id
    score["content_sha256"] = forged_content_sha256
    summary["candidate_id"] = forged_candidate_id
    summary["content_sha256"] = forged_content_sha256
    gate = forged_candidate["table_candidate_gate"]
    gate["candidate_id"] = forged_candidate_id
    gate["decision_id"] = _p04_digest(
        [
            "p04-us04-gate-v1",
            forged_candidate_id,
            "chart",
            gate["owner_item_ids"],
            gate["feature_scores"],
            gate["evidence_ids"],
            gate["concern_codes"],
        ]
    )

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart, forged_candidate],
        item_index=0,
        detected_images=None,
        raw_graph=_raw_owner_graph(chart_bbox, "chart-owner"),
        page_index=1,
        page_width=300.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="d" * 64,
        render_source_sha256="d" * 64,
    )

    assert proof is None


def test_disjoint_invalid_detected_record_cannot_reuse_valid_owner_identity() -> (
    None
):
    target_bbox = _box((80.0, 100.0, 300.0, 160.0))
    disjoint_bbox = _box((400.0, 500.0, 80.0, 70.0))
    chart = _chart_claim("chart-owner", target_bbox)
    detected_images = [_detected_pdf_owner("duplicate-detected-id", target_bbox)]
    invalid_duplicate = _detected_pdf_owner(
        "duplicate-detected-id",
        disjoint_bbox,
    )
    invalid_duplicate["region_origin"] = "untrusted_crop"
    detected_images.append(invalid_duplicate)

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart],
        item_index=0,
        detected_images=detected_images,
        raw_graph=_raw_owner_graph(target_bbox, "chart-owner"),
        page_index=1,
        page_width=612.0,
        page_height=792.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="e" * 64,
        render_source_sha256="e" * 64,
    )

    assert proof is None


@pytest.mark.parametrize(
    ("other_bbox", "accepted"),
    (
        ((20.0, 20.0, 100.0, 100.0), False),
        ((35.0, 45.0, 20.0, 20.0), False),
        ((110.0, 20.0, 100.0, 100.0), True),
        ((130.0, 50.0, 60.0, 60.0), True),
    ),
)
def test_material_visual_owner_overlap_is_distinct_from_mapping_equivalence(
    other_bbox: tuple[float, float, float, float],
    accepted: bool,
) -> None:
    target_bbox = _box((10.0, 20.0, 100.0, 100.0))
    neighboring_bbox = _box(other_bbox)
    target = _chart_claim("chart-a", target_bbox)
    neighbor = _chart_claim("chart-b", neighboring_bbox)
    raw_graph = _raw_owner_graph(target_bbox, "chart-a")
    raw_graph["pictures"].extend(
        _raw_owner_graph(neighboring_bbox, "chart-b")["pictures"]
    )

    proof = prove_chart_owner_geometry(
        item=target,
        page_items=[target, neighbor],
        item_index=0,
        detected_images=None,
        raw_graph=raw_graph,
        page_index=1,
        page_width=300.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="4" * 64,
        render_source_sha256="4" * 64,
    )

    assert (proof is not None) is accepted


@pytest.mark.parametrize("evidence_kind", ("docling", "detected"))
@pytest.mark.parametrize("malformed_overlap", (True, False))
def test_spatially_locatable_malformed_source_evidence_poisons_only_its_region(
    evidence_kind: str,
    malformed_overlap: bool,
) -> None:
    target_bbox = _box((80.0, 100.0, 300.0, 160.0))
    disjoint_bbox = _box((400.0, 500.0, 80.0, 70.0))
    malformed_bbox = target_bbox if malformed_overlap else disjoint_bbox
    chart = _chart_claim("chart-owner", target_bbox)
    raw_graph = _raw_owner_graph(target_bbox, "valid-owner")
    detected_images = [_detected_pdf_owner("valid-owner", target_bbox)]
    if evidence_kind == "docling":
        malformed = _raw_owner_graph(malformed_bbox, "malformed-owner")["pictures"][
            0
        ]
        del malformed["self_ref"]
        raw_graph["pictures"].append(malformed)
    else:
        malformed = _detected_pdf_owner("malformed-owner", malformed_bbox)
        del malformed["id"]
        detected_images.append(malformed)

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart],
        item_index=0,
        detected_images=detected_images,
        raw_graph=raw_graph,
        page_index=1,
        page_width=612.0,
        page_height=792.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="5" * 64,
        render_source_sha256="5" * 64,
    )

    assert (proof is None) is malformed_overlap


@pytest.mark.parametrize("evidence_kind", ("docling", "detected"))
def test_disjoint_duplicate_source_identity_is_still_ambiguous(
    evidence_kind: str,
) -> None:
    target_bbox = _box((80.0, 100.0, 300.0, 160.0))
    disjoint_bbox = _box((400.0, 500.0, 80.0, 70.0))
    chart = _chart_claim("chart-owner", target_bbox)
    raw_graph = _raw_owner_graph(target_bbox, "duplicate-id")
    detected_images = [_detected_pdf_owner("duplicate-id", target_bbox)]
    if evidence_kind == "docling":
        raw_graph["pictures"].extend(
            _raw_owner_graph(disjoint_bbox, "duplicate-id")["pictures"]
        )
    else:
        detected_images.append(_detected_pdf_owner("duplicate-id", disjoint_bbox))

    proof = prove_chart_owner_geometry(
        item=chart,
        page_items=[chart],
        item_index=0,
        detected_images=detected_images,
        raw_graph=raw_graph,
        page_index=1,
        page_width=612.0,
        page_height=792.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="6" * 64,
        render_source_sha256="6" * 64,
    )

    assert proof is None


def test_docling_identity_is_global_and_multi_provenance_cannot_hide_owner() -> (
    None
):
    target_bbox = _box((80.0, 100.0, 300.0, 160.0))
    chart = _chart_claim("chart-owner", target_bbox)

    duplicate_graph = _raw_owner_graph(target_bbox, "global-id")
    cross_page = _raw_owner_graph(_box((10.0, 10.0, 20.0, 20.0)), "global-id")
    cross_page["pictures"][0]["prov"][0]["page_no"] = 2
    duplicate_graph["pictures"].extend(cross_page["pictures"])

    hidden_graph = _raw_owner_graph(target_bbox, "valid-owner")
    hidden = _raw_owner_graph(_box((10.0, 10.0, 20.0, 20.0)), "hidden-owner")[
        "pictures"
    ][0]
    hidden["prov"].append(
        deepcopy(_raw_owner_graph(target_bbox, "unused")["pictures"][0]["prov"][0])
    )
    hidden["prov"][0]["page_no"] = 2
    hidden_graph["pictures"].append(hidden)

    for raw_graph in (duplicate_graph, hidden_graph):
        assert (
            prove_chart_owner_geometry(
                item=chart,
                page_items=[chart],
                item_index=0,
                detected_images=None,
                raw_graph=raw_graph,
                page_index=1,
                page_width=612.0,
                page_height=792.0,
                page_unit="pt",
                input_kind="pdf",
                source_document_sha256="7" * 64,
                render_source_sha256="7" * 64,
            )
            is None
        )


@pytest.mark.parametrize("origin", (None, "SIDEWAYS"))
def test_locatable_raw_bbox_with_unknown_origin_cannot_hide_exact_competitor(
    origin: str | None,
) -> None:
    target_bbox = _box((80.0, 100.0, 300.0, 160.0))
    chart = _chart_claim("chart-owner", target_bbox)
    raw_graph = _raw_owner_graph(target_bbox, "valid-owner")
    malformed = deepcopy(raw_graph["pictures"][0])
    malformed["self_ref"] = "#/pictures/malformed-owner"
    if origin is None:
        del malformed["prov"][0]["bbox"]["coord_origin"]
    else:
        malformed["prov"][0]["bbox"]["coord_origin"] = origin
    raw_graph["pictures"].append(malformed)

    assert (
        prove_chart_owner_geometry(
            item=chart,
            page_items=[chart],
            item_index=0,
            detected_images=None,
            raw_graph=raw_graph,
            page_index=1,
            page_width=612.0,
            page_height=792.0,
            page_unit="pt",
            input_kind="pdf",
            source_document_sha256="9" * 64,
            render_source_sha256="9" * 64,
        )
        is None
    )


@pytest.mark.parametrize("overlaps", (True, False))
def test_locatable_contradictory_page_bbox_aliases_poison_only_overlap(
    overlaps: bool,
) -> None:
    target_bbox = _box((10.0, 20.0, 100.0, 100.0))
    target = _chart_claim("chart-a", target_bbox)
    competitor_bbox = {
        "x": 10.0 if overlaps else 200.0,
        "y": 20.0,
        "width": 100.0,
        "w": 99.0,
        "height": 100.0,
        "h": 100.0,
        "unit": "pt",
    }
    competitor = {
        "id": "chart-b",
        "type": "chart",
        "content_type": "chart",
        "region_role": "content_region",
        "bbox": competitor_bbox,
    }
    proof = prove_chart_owner_geometry(
        item=target,
        page_items=[target, competitor],
        item_index=0,
        detected_images=None,
        raw_graph=_raw_owner_graph(target_bbox, "chart-a"),
        page_index=1,
        page_width=400.0,
        page_height=300.0,
        page_unit="pt",
        input_kind="pdf",
        source_document_sha256="8" * 64,
        render_source_sha256="8" * 64,
    )

    assert (proof is None) is overlaps


@pytest.mark.integration
def test_classified_image_to_chart_promotion_keeps_exact_source_owner_custody() -> (
    None
):
    source = _fallback_source()
    source["document"]["filename"] = "arbitrarily-renamed-input.pdf"
    source["pages"][0]["items"][0]["type"] = "image"
    source["pages"][0]["items"][0]["content_type"] = "image"
    source = json.loads(json.dumps(source))
    raw_graph = json.loads(json.dumps(_fallback_raw_graph()))

    output = apply_visual_semantics(
        source,
        _asset_settings(),
        source_document_bytes=HEALTH_REPORT.read_bytes(),
        input_kind=InputKind.PDF,
        raw_graph=raw_graph,
    )
    item = ParseResult.model_validate(output).pages[0].items[0]

    assert item.type == "chart"
    assert item.chart_resolution is not None
    assert item.chart_resolution.asset_status == "retained"
    assert item.chart_resolution.asset is not None
    assert item.chart_resolution.asset.owner_geometry_proof_kind == (
        "detected_image_and_docling_picture"
    )


@pytest.mark.parametrize(
    "corruption",
    (
        "malformed_base64",
        "digest_mismatch",
        "byte_length_mismatch",
        "dimension_mismatch",
        "transform_mismatch",
        "rendered_bbox_inset",
        "device_crop_mismatch",
        "owner_evidence_mismatch",
        "owner_proof_kind_mismatch",
        "unknown_key",
    ),
)
def test_inline_asset_contract_rejects_tampered_bytes_and_metadata(
    corruption: str,
) -> None:
    item, structure = _fallback_candidate()
    attempt = _retained_attempt(item, structure)
    assert attempt.asset is not None
    payload = attempt.asset.model_dump(mode="python")

    if corruption == "malformed_base64":
        payload["data_uri"] = f"{payload['data_uri']}!"
    elif corruption == "digest_mismatch":
        payload["sha256"] = "0" * 64
    elif corruption == "byte_length_mismatch":
        payload["byte_length"] += 1
    elif corruption == "dimension_mismatch":
        payload["width"] += 1
    elif corruption == "transform_mismatch":
        payload["pixel_to_page_transform"][0] += 0.01
    elif corruption == "rendered_bbox_inset":
        payload["rendered_bbox"]["x"] += 1.0
    elif corruption == "device_crop_mismatch":
        payload["crop_device_margins"][0] += 1
    elif corruption == "owner_evidence_mismatch":
        payload["owner_geometry_evidence_ids"][0] += "-tampered"
    elif corruption == "owner_proof_kind_mismatch":
        payload["owner_geometry_proof_kind"] = "detected_image"
    elif corruption == "unknown_key":
        payload["server_local_path"] = "/tmp/chart.png"
    else:  # pragma: no cover - exhaustive tuple above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        ChartSourceAsset.model_validate(payload, strict=True)


def test_terminal_state_matrix_retains_one_asset_or_fails_closed() -> None:
    fallback_item, fallback_structure = _fallback_candidate()
    retained = _retained_attempt(fallback_item, fallback_structure)
    assert retained.asset is not None
    unsupported = build_chart_resolution(
        item=fallback_item,
        structure=fallback_structure,
        page_index=1,
        source_order=0,
        asset_attempt=retained,
        settings=Settings(),
    )
    incomplete = build_chart_resolution(
        item=fallback_item,
        structure=fallback_structure,
        page_index=1,
        source_order=0,
        asset_attempt=retained,
        settings=_asset_settings(
            charts_vector_inventory_enabled=True,
            charts_structure_enabled=True,
            charts_vector_values_enabled=True,
            charts_structured_output_enabled=True,
        ),
    )

    complete_item, complete_structure = _complete_candidate()
    complete_asset = _retained_attempt(complete_item, complete_structure)
    assert complete_asset.asset is not None
    structured = build_chart_resolution(
        item=complete_item,
        structure=complete_structure,
        page_index=1,
        source_order=0,
        asset_attempt=complete_asset,
        settings=_raster_bar_settings(structured=True),
    )
    unavailable = build_chart_resolution(
        item=fallback_item,
        structure=fallback_structure,
        page_index=1,
        source_order=0,
        asset_attempt=ChartAssetAttempt(None, "render_failed"),
        settings=Settings(),
    )

    assert {
        resolution.status: (
            resolution.asset_status,
            resolution.primary_representation,
            resolution.primary_reason,
            resolution.semantic_analysis.attempt_status,
            resolution.semantic_analysis.completeness_gate_status,
        )
        for resolution in (structured, unsupported, incomplete, unavailable)
    } == {
        "structured_primary": (
            "retained",
            "structured_chart",
            "semantic_completeness_passed",
            "completed",
            "passed",
        ),
        "image_primary_unsupported": (
            "retained",
            "source_image",
            "semantic_family_not_supported",
            "not_run_no_approved_analyzer",
            "not_run",
        ),
        "image_primary_incomplete": (
            "retained",
            "source_image",
            "semantic_analysis_incomplete",
            "completed",
            "failed",
        ),
        "asset_unavailable": (
            "unavailable",
            "grounded_predecessor",
            "source_asset_unavailable",
            "not_run_asset_unavailable",
            "not_run",
        ),
    }
    assert unsupported.asset == incomplete.asset == retained.asset
    assert structured.asset == complete_asset.asset
    assert unavailable.asset is None
    assert unavailable.asset_unavailable_reason == "render_failed"
    assert unavailable.family_classification.status == "not_run"
    assert unavailable.family_classification.reason_codes == ["asset_unavailable"]
    assert unavailable.family_classification.evidence_ids == []
    assert unavailable.complexity_classification.status == "not_run"
    assert unavailable.complexity_classification.reason_codes == ["asset_unavailable"]
    assert unavailable.complexity_classification.evidence_ids == []
    for resolution in (structured, unsupported, incomplete, unavailable):
        assert (
            ChartResolution.model_validate(
                resolution.model_dump(mode="python"),
                strict=True,
            )
            == resolution
        )

    unsupported_markdown = chart_resolution_markdown(
        unsupported,
        caption="Revenue [source]",
    )
    incomplete_markdown = chart_resolution_markdown(
        incomplete,
        caption="Revenue [source]",
    )
    assert unsupported_markdown is not None
    assert incomplete_markdown is not None
    assert unsupported_markdown.count("data:image/png;base64,") == 1
    assert incomplete_markdown.count("data:image/png;base64,") == 1
    assert "Revenue \\[source\\]" in unsupported_markdown
    assert chart_resolution_markdown(structured, caption="Revenue") is None
    assert chart_resolution_markdown(unavailable, caption="Revenue") is None


def test_complexity_is_evidence_only_and_never_selects_the_primary() -> None:
    sparse_item, sparse_structure = _fallback_candidate(family="bar_chart")
    complex_item, complex_structure = _fallback_candidate(family="bubble_chart")
    sparse = build_chart_resolution(
        item=sparse_item,
        structure=sparse_structure,
        page_index=1,
        source_order=0,
        asset_attempt=_retained_attempt(sparse_item, sparse_structure),
        settings=Settings(),
    )
    complex_resolution = build_chart_resolution(
        item=complex_item,
        structure=complex_structure,
        page_index=1,
        source_order=0,
        asset_attempt=_retained_attempt(complex_item, complex_structure),
        settings=Settings(),
    )

    assert sparse.complexity_classification.status == "undetermined"
    assert sparse.complexity_classification.reason_codes == [
        "insufficient_source_features"
    ]
    assert complex_resolution.complexity_classification.status == "complex"
    assert complex_resolution.complexity_classification.reason_codes == [
        "multi_encoding_family"
    ]
    assert sparse.status == complex_resolution.status == "image_primary_unsupported"
    assert (
        sparse.primary_representation
        == complex_resolution.primary_representation
        == ("source_image")
    )


def test_inventory_without_an_approved_value_producer_is_unsupported() -> None:
    item, structure = _fallback_candidate(family="bar_chart")
    resolution = build_chart_resolution(
        item=item,
        structure=structure,
        page_index=1,
        source_order=0,
        asset_attempt=_retained_attempt(item, structure),
        settings=Settings(
            visual_structure_schema_enabled=True,
            charts_vector_inventory_enabled=True,
        ),
    )

    assert resolution.status == "image_primary_unsupported"
    assert resolution.primary_representation == "source_image"
    assert resolution.semantic_analysis.attempt_status == (
        "not_run_no_approved_analyzer"
    )
    assert resolution.semantic_analysis.completeness_gate_status == "not_run"
    assert resolution.semantic_analysis.failure_reason == "unsupported"


def test_conflicting_declared_and_office_families_remain_undetermined() -> None:
    item, structure = _fallback_candidate(family="bar_chart")
    item["office_chart"] = {"chart_type": "lineChart"}
    resolution = build_chart_resolution(
        item=item,
        structure=structure,
        page_index=1,
        source_order=0,
        asset_attempt=_retained_attempt(item, structure),
        settings=Settings(),
    )

    assert resolution.family_classification.status == "undetermined"
    assert resolution.family_classification.family == "undetermined"
    assert resolution.family_classification.reason_codes == ["multiple_family_signals"]
    assert resolution.status == "image_primary_unsupported"
    assert resolution.primary_representation == "source_image"


@pytest.mark.parametrize(
    "corruption",
    (
        "status_primary_mismatch",
        "retained_without_asset",
        "duplicate_concern",
        "asset_owner_mismatch",
    ),
)
def test_terminal_contract_rejects_impossible_combinations(corruption: str) -> None:
    item, structure = _fallback_candidate()
    resolution = build_chart_resolution(
        item=item,
        structure=structure,
        page_index=1,
        source_order=0,
        asset_attempt=_retained_attempt(item, structure),
        settings=Settings(),
    )
    payload = resolution.model_dump(mode="python")

    if corruption == "status_primary_mismatch":
        payload["status"] = "structured_primary"
    elif corruption == "retained_without_asset":
        payload["asset"] = None
    elif corruption == "duplicate_concern":
        payload["concern_codes"] *= 2
    elif corruption == "asset_owner_mismatch":
        payload["owner_item_id"] = "different-owner"
    else:  # pragma: no cover - exhaustive tuple above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        ChartResolution.model_validate(payload, strict=True)


def test_public_document_binds_chart_owner_order_page_bbox_and_source_hash() -> None:
    payload = _fallback_resolution_payload()

    result = ParseResult.model_validate(payload)
    encoded = result.model_dump_json(exclude_none=True)
    reparsed = ParseResult.model_validate_json(encoded)

    assert reparsed == result
    item = result.pages[0].items[0]
    assert item.chart_resolution is not None
    resolution = item.chart_resolution
    assert resolution.owner_item_id == item.id
    assert resolution.source_order == 0
    assert resolution.page_index == result.pages[0].page_index
    assert resolution.source_bbox == item.visual_structure.region.page_bbox
    assert resolution.asset is not None
    assert resolution.asset.source_document_sha256 == result.document.sha256
    assert resolution.asset.render_source_sha256 == result.document.sha256

    reordered = _fallback_resolution_payload(owner_id="chart-owner-a")
    second = _fallback_resolution_payload(
        owner_id="chart-owner-b",
        x=120.0,
        source_order=1,
    )["pages"][0]["items"][0]
    reordered["pages"][0]["items"] = [
        second,
        reordered["pages"][0]["items"][0],
    ]
    for reading_order, reordered_item in enumerate(reordered["pages"][0]["items"]):
        reordered_item["reading_order"] = reading_order
    reordered_result = ParseResult.model_validate(reordered)
    assert [
        item.chart_resolution.source_order
        for item in reordered_result.pages[0].items
        if item.chart_resolution is not None
    ] == [1, 0]
    expected_reordered_markdown = [
        chart_resolution_markdown(
            item.chart_resolution,
            caption=item.caption,
        )
        for item in reordered_result.pages[0].items
        if item.chart_resolution is not None
    ]
    assert all(value is not None for value in expected_reordered_markdown)
    reordered_canonical = build_canonical_presentation(
        build_document_ir(reordered_result)
    )
    assert [
        block.markdown for block in reordered_canonical.pages[0].blocks
    ] == expected_reordered_markdown
    assert to_markdown(reordered_result) == (
        "\n\n".join(value for value in expected_reordered_markdown if value is not None)
        + "\n"
    )

    wrong_page = _fallback_resolution_payload()
    wrong_page["pages"][0]["page_index"] = 2
    for evidence in wrong_page["pages"][0]["items"][0]["visual_structure"]["evidence"]:
        evidence["provenance"]["page_index"] = 2
    with pytest.raises(ValidationError, match="page binding differs"):
        ParseResult.model_validate(wrong_page)

    wrong_document = _fallback_resolution_payload()
    wrong_document["document"]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="document custody differs"):
        ParseResult.model_validate(wrong_document)


def test_public_document_rejects_aggregate_inline_asset_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fallback_resolution_payload(owner_id="chart-owner-a", x=10.0)
    second_payload = _fallback_resolution_payload(
        owner_id="chart-owner-b",
        x=120.0,
        source_order=1,
    )
    payload["pages"][0]["items"].append(second_payload["pages"][0]["items"][0])

    duplicate_source_slot = deepcopy(payload)
    duplicate_source_slot["pages"][0]["items"][1]["chart_resolution"][
        "source_order"
    ] = 0
    with pytest.raises(ValidationError, match="source order repeats"):
        ParseResult.model_validate(duplicate_source_slot)

    result = ParseResult.model_validate(payload)
    assets = [
        item.chart_resolution.asset
        for item in result.pages[0].items
        if item.chart_resolution is not None
    ]
    assert len(assets) == 2
    assert all(asset is not None for asset in assets)
    total_bytes = sum(asset.byte_length for asset in assets if asset is not None)
    monkeypatch.setattr(
        public_models,
        "_CHART_MAX_DOCUMENT_ASSET_BYTES",
        total_bytes - 1,
    )

    with pytest.raises(ValidationError, match="document byte cap"):
        ParseResult.model_validate(payload)


def test_raw_parse_result_rejects_canonical_data_uri_amplification_over_48_mib() -> (
    None
):
    payload = _fallback_resolution_payload()
    canonical = build_canonical_presentation(build_document_ir(payload)).model_dump(
        mode="json",
        exclude_none=True,
    )
    payload["canonical_presentation"] = canonical

    block = canonical["pages"][0]["blocks"][0]
    page = canonical["pages"][0]
    amplification_targets = (
        (block, "markdown"),
        (block, "text"),
        (page["full"], "markdown"),
        (page["full"], "text"),
        (page["body"], "markdown"),
        (page["body"], "text"),
        (canonical["full"], "markdown"),
        (canonical["full"], "text"),
        (canonical["body"], "markdown"),
        (canonical["body"], "text"),
    )
    prefix = "data:image/png;base64,"
    per_copy_bytes = (
        public_models._CHART_MAX_PUBLIC_INLINE_BYTES // len(amplification_targets)
    ) + 1
    amplified_uri = prefix + "A" * (per_copy_bytes - len(prefix))
    for target, field in amplification_targets:
        target[field] = amplified_uri

    assert len(amplified_uri.encode("ascii")) < (
        public_models._CHART_MAX_PUBLIC_INLINE_BYTES
    )
    assert (
        sum(
            len(target[field].encode("ascii"))
            for target, field in amplification_targets
        )
        > public_models._CHART_MAX_PUBLIC_INLINE_BYTES
    )
    with pytest.raises(
        ValidationError,
        match="chart inline response exceeds its byte cap",
    ):
        ParseResult.model_validate(payload)


def test_image_crop_retains_only_requested_pixels_without_neighbor_leakage() -> None:
    source, retained = _source_png()
    crop = render_visual_model_crop(
        source,
        InputKind.IMAGE,
        1,
        _box((1.0, 1.0, 4.0, 2.0), unit="px"),
        Settings(),
    )
    repeated = render_visual_model_crop(
        source,
        InputKind.IMAGE,
        1,
        _box((1.0, 1.0, 4.0, 2.0), unit="px"),
        Settings(),
    )

    assert crop is not None
    assert repeated is not None
    assert crop.data == repeated.data
    assert crop.content_sha256 == hashlib.sha256(crop.data).hexdigest()
    assert crop.byte_length == len(crop.data)
    assert (crop.width, crop.height) == (4, 2)
    with Image.open(io.BytesIO(crop.data)) as decoded:
        decoded.load()
        pixels = list(decoded.get_flattened_data())
        assert pixels == retained
        assert (255, 0, 0) not in pixels


def test_crop_refuses_unsafe_geometry_and_resource_caps() -> None:
    source, _ = _source_png()

    assert (
        render_visual_model_crop(
            source,
            InputKind.IMAGE,
            1,
            _box((0.5, 1.0, 4.0, 2.0), unit="px"),
            Settings(),
        )
        is None
    )
    assert (
        render_visual_model_crop(
            source,
            InputKind.IMAGE,
            1,
            _box((1.0, 1.0, 6.0, 2.0), unit="px"),
            Settings(),
        )
        is None
    )
    assert (
        render_visual_model_crop(
            source,
            InputKind.IMAGE,
            1,
            _box((1.0, 1.0, 4.0, 2.0), unit="pt"),
            Settings(),
        )
        is None
    )
    assert (
        render_visual_model_crop(
            source,
            InputKind.IMAGE,
            1,
            _box((1.0, 1.0, 4.0, 2.0), unit="px"),
            Settings(visual_models_max_crop_width=3),
        )
        is None
    )
    assert (
        render_visual_model_crop(
            source,
            InputKind.IMAGE,
            1,
            _box((1.0, 1.0, 4.0, 2.0), unit="px"),
            Settings(visual_models_max_crop_pixels=7),
        )
        is None
    )


def test_inline_asset_ledger_refusals_are_atomic() -> None:
    source, _ = _source_png()
    source_sha256 = hashlib.sha256(source).hexdigest()
    bbox = _box((1.0, 1.0, 4.0, 2.0), unit="px")
    limits = replace(chart_asset_limits(Settings()), min_width=1, min_height=1)
    owner_geometry_proof = _strict_owner_proof(
        bbox=bbox,
        owner_id="chart-owner",
        input_kind="image",
        source_document_sha256=source_sha256,
        page_width=6.0,
        page_height=4.0,
    )

    count_ledger = ChartAssetLedger(
        asset_count=limits.max_assets,
        total_bytes=123,
    )
    count_refusal = render_chart_source_asset(
        source=source,
        input_kind="image",
        page_index=1,
        bbox=bbox,
        owner_item_id="chart-owner",
        source_document_sha256=source_sha256,
        owner_geometry_proof=owner_geometry_proof,
        limits=limits,
        ledger=count_ledger,
    )
    assert count_refusal == ChartAssetAttempt(None, "document_asset_count_limit")
    assert count_ledger.asset_count == limits.max_assets
    assert count_ledger.total_bytes == 123
    assert count_ledger.response_bytes == 0
    assert count_ledger.attempt_count == 1
    assert count_ledger.deadline_monotonic is not None

    byte_ledger = ChartAssetLedger(asset_count=2, total_bytes=7)
    byte_refusal = render_chart_source_asset(
        source=source,
        input_kind="image",
        page_index=1,
        bbox=bbox,
        owner_item_id="chart-owner",
        source_document_sha256=source_sha256,
        owner_geometry_proof=owner_geometry_proof,
        limits=replace(limits, max_total_bytes=7),
        ledger=byte_ledger,
    )
    assert byte_refusal == ChartAssetAttempt(None, "document_asset_byte_limit")
    assert byte_ledger.asset_count == 2
    assert byte_ledger.total_bytes == 7
    assert byte_ledger.response_bytes == 0
    assert byte_ledger.attempt_count == 1
    assert byte_ledger.deadline_monotonic is not None

    invalid_identity = render_chart_source_asset(
        source=source,
        input_kind="image",
        page_index=1,
        bbox=bbox,
        owner_item_id="chart-owner",
        source_document_sha256="not-a-sha256",
        owner_geometry_proof=None,
        limits=limits,
        ledger=ChartAssetLedger(),
    )
    assert invalid_identity == ChartAssetAttempt(None, "source_bytes_unavailable")

    integrity_mismatch = render_chart_source_asset(
        source=source,
        input_kind="image",
        page_index=1,
        bbox=bbox,
        owner_item_id="chart-owner",
        source_document_sha256="0" * 64,
        owner_geometry_proof=None,
        limits=limits,
        ledger=ChartAssetLedger(),
    )
    assert integrity_mismatch == ChartAssetAttempt(None, "source_integrity_mismatch")


def test_response_byte_refusal_keeps_ledger_commit_fields_atomic() -> None:
    source, _ = _source_png()
    source_sha256 = hashlib.sha256(source).hexdigest()
    bbox = _box((1.0, 1.0, 4.0, 2.0), unit="px")
    owner_geometry_proof = _strict_owner_proof(
        bbox=bbox,
        owner_id="chart-owner",
        input_kind="image",
        source_document_sha256=source_sha256,
        page_width=6.0,
        page_height=4.0,
    )
    ledger = ChartAssetLedger(
        asset_count=2,
        total_bytes=7,
        response_bytes=17,
    )
    commit_before = (ledger.asset_count, ledger.total_bytes, ledger.response_bytes)
    limits = replace(
        chart_asset_limits(Settings()),
        min_width=1,
        min_height=1,
        max_response_bytes=ledger.response_bytes,
    )

    refusal = render_chart_source_asset(
        source=source,
        input_kind="image",
        page_index=1,
        bbox=bbox,
        owner_item_id="chart-owner",
        source_document_sha256=source_sha256,
        owner_geometry_proof=owner_geometry_proof,
        limits=limits,
        ledger=ledger,
    )

    assert refusal == ChartAssetAttempt(None, "response_byte_limit")
    assert (ledger.asset_count, ledger.total_bytes, ledger.response_bytes) == (
        commit_before
    )
    assert ledger.attempt_count == 1
    assert ledger.deadline_monotonic is not None


def test_exhausted_document_budgets_refuse_remaining_owners_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _ = _source_png()
    source_sha256 = hashlib.sha256(source).hexdigest()
    bbox = _box((1.0, 1.0, 4.0, 2.0), unit="px")
    limits = replace(chart_asset_limits(Settings()), min_width=1, min_height=1)
    spawn_calls: list[tuple[Any, ...]] = []

    def forbidden_spawn(*args: Any, **_kwargs: Any) -> Any:
        spawn_calls.append(args)
        raise AssertionError("an exhausted document budget spawned a renderer")

    monkeypatch.setattr(chart_assets.multiprocessing, "get_context", forbidden_spawn)

    attempt_exhausted = ChartAssetLedger(
        attempt_count=limits.max_assets,
        deadline_monotonic=float("inf"),
    )
    count_refusals = [
        render_chart_source_asset(
            source=source,
            input_kind="image",
            page_index=1,
            bbox=bbox,
            owner_item_id=owner_id,
            source_document_sha256=source_sha256,
            owner_geometry_proof=None,
            limits=limits,
            ledger=attempt_exhausted,
        )
        for owner_id in ("remaining-owner-a", "remaining-owner-b")
    ]
    assert count_refusals == [
        ChartAssetAttempt(None, "document_asset_count_limit"),
        ChartAssetAttempt(None, "document_asset_count_limit"),
    ]
    assert attempt_exhausted.attempt_count == limits.max_assets
    assert (
        attempt_exhausted.asset_count,
        attempt_exhausted.total_bytes,
        attempt_exhausted.response_bytes,
    ) == (0, 0, 0)

    time_exhausted = ChartAssetLedger(
        attempt_count=3,
        deadline_monotonic=0.0,
    )
    timeout_refusals = [
        render_chart_source_asset(
            source=source,
            input_kind="image",
            page_index=1,
            bbox=bbox,
            owner_item_id=owner_id,
            source_document_sha256=source_sha256,
            owner_geometry_proof=None,
            limits=limits,
            ledger=time_exhausted,
        )
        for owner_id in ("remaining-owner-c", "remaining-owner-d")
    ]
    assert timeout_refusals == [
        ChartAssetAttempt(None, "document_render_timeout"),
        ChartAssetAttempt(None, "document_render_timeout"),
    ]
    assert time_exhausted.attempt_count == 3
    assert (
        time_exhausted.asset_count,
        time_exhausted.total_bytes,
        time_exhausted.response_bytes,
    ) == (0, 0, 0)
    assert spawn_calls == []
