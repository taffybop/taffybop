"""Real-corpus regressions for conservative classifier-unavailable routing."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import pytest

from app.services.serializer import to_markdown
from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
    CORPUS,
    _box_tuple,
    _parse_local_fidelity,
)
from tests.regression.phase_05.test_p05_us11_clinical_page3_flow_list import (
    EXPECTED_LIST as CLINICAL_FLOW_LIST,
)

EXPECTED_SOURCE_SHA256 = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    ),
    "clinical-study": (
        "4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2"
    ),
    "component-datasheet": (
        "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
    ),
    "egov-survey": (
        "7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846"
    ),
    "uber-earnings": (
        "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
    ),
    "clean-energy": (
        "161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d"
    ),
    "esg-metrics": (
        "6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9"
    ),
    "health-report": (
        "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
    ),
    "manufacturing-report": (
        "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f"
    ),
}


def _items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item, dict)
    ]


def _region_source_ids(item: Mapping[str, Any]) -> set[str]:
    structure = item["visual_structure"]
    region = next(
        evidence
        for evidence in structure["evidence"]
        if evidence["kind"] == "region"
    )
    return set(region["provenance"]["source_object_ids"])


@pytest.mark.integration
def test_classifier_unavailable_routes_exhibit_chart_without_inventing_values() -> None:
    source = CORPUS / "catastrophe-recap.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["catastrophe-recap"]
    )
    payload = _parse_local_fidelity("catastrophe-recap")
    chart = next(
        item
        for item in _items(payload)
        if _box_tuple(item.get("bbox") or {})
        == (100.221, 437.310, 444.032, 149.057)
    )

    assert chart["type"] == chart["content_type"] == "chart"
    assert chart.get("classification") is None
    assert chart["visual_structure"]["region"]["kind"] == "chart"
    assert chart["visual_structure"]["fallback"]["active"] is True
    assert not chart["visual_structure"]["series"]
    assert not chart["visual_structure"]["points"]
    assert {"#/pictures/1", "#/texts/3", chart["id"]} <= (
        _region_source_ids(chart)
    )
    assert "chart_values_not_structured" in chart["parse_concerns"]
    assert to_markdown(payload).count(
        "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)"
    ) == 1


@pytest.mark.integration
def test_classifier_unavailable_routes_real_flowchart_with_grounded_topology() -> None:
    source = CORPUS / "clinical-study.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["clinical-study"]
    )
    payload = _parse_local_fidelity("clinical-study")
    diagram = next(
        item
        for item in _items(payload)
        if _box_tuple(item.get("bbox") or {})
        == (123.364, 78.009, 452.636, 572.372)
    )

    assert diagram["type"] == diagram["content_type"] == "diagram"
    assert diagram.get("classification") is None
    assert diagram["visual_structure"]["region"]["kind"] == "diagram"
    assert diagram["visual_structure"]["fallback"]["active"] is False
    assert len(diagram["visual_structure"]["nodes"]) == 15
    assert len(diagram["visual_structure"]["connectors"]) == 14
    assert "diagram_relationships_not_structured" not in (
        diagram.get("parse_concerns") or []
    )
    assert diagram["value"] == diagram["md"] == CLINICAL_FLOW_LIST
    assert diagram.get("caption") is None
    markdown = to_markdown(payload)
    assert markdown.count(CLINICAL_FLOW_LIST) == 1
    assert markdown.count("Fig 1. Flowchart.") == 1
    assert payload["canonical_presentation"]["full"]["markdown"].count(
        CLINICAL_FLOW_LIST
    ) == 1


@pytest.mark.integration
def test_source_undeclared_board_and_pinout_remain_images() -> None:
    source = CORPUS / "component-datasheet.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["component-datasheet"]
    )
    payload = _parse_local_fidelity("component-datasheet")
    targets = {
        _box_tuple(item.get("bbox") or {}): item
        for item in _items(payload)
        if item.get("type") == "image"
    }

    assert {
        (114.983, 151.646, 295.742, 265.243),
        (133.843, 94.483, 133.628, 261.194),
    } <= set(targets)
    for bbox in (
        (114.983, 151.646, 295.742, 265.243),
        (133.843, 94.483, 133.628, 261.194),
    ):
        item = targets[bbox]
        assert item["type"] == item["content_type"] == "image"
        assert item.get("classification") is None
        assert "visual_structure" not in item
        assert "phase05_source_caption_routing" not in (item.get("meta") or {})


@pytest.mark.integration
def test_egov_native_chart_text_replaces_noisy_ocr_in_json_and_rendering() -> None:
    source = CORPUS / "egov-survey.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["egov-survey"]
    )
    payload = _parse_local_fidelity("egov-survey")
    chart = next(item for item in _items(payload) if item.get("id") == "p1-i3")

    assert chart["type"] == chart["content_type"] == "chart"
    assert chart["source"] == "native"
    assert chart["layout_visual_source_text_promoted"] is True
    assert chart["meta"]["phase05_visual_source_text"] == {
        "method": "pdf_text_layer_inside_visual_bbox",
        "occurrence_count": 74,
        "promoted_primary": True,
        "text_sha256": (
            "a049c6dd811ac1f8b80b4c48b935595ec2f212a2884de7fad34c6abdcd284aff"
        ),
    }
    assert chart["md"] == chart["value"] == chart["visual_source_text"]
    assert chart["md"] == chart["visual_structure"]["serialization"]["markdown"]
    assert "40 (20.7%)" in chart["md"]
    assert "44 (22.8%)" in chart["md"]
    assert "AO (20.7%)" not in chart["md"]
    assert "4A (22.8%)" not in chart["md"]
    assert "AO (20.7%)" in chart["ocr_text"]
    assert "4A (22.8%)" in chart["ocr_text"]
    markdown = to_markdown(payload)
    assert "AO (20.7%)" not in markdown
    assert "4A (22.8%)" not in markdown
    assert "40 (20.7%)" in markdown
    assert "44 (22.8%)" in markdown
    assert payload["canonical_presentation"]["full"]["markdown"] == markdown


@pytest.mark.integration
def test_uber_routes_only_explicit_charts_and_undirected_colored_node_groups() -> None:
    source = CORPUS / "uber-earnings.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["uber-earnings"]
    )
    payload = _parse_local_fidelity("uber-earnings")
    items = {item["id"]: item for item in _items(payload)}

    # The hero photo and category-position artwork are not charts merely
    # because text happens to be printed nearby or inside them.
    assert items["p1-i1"]["type"] == "image"
    assert "visual_structure" not in items["p1-i1"]
    assert items["p2-i4"]["type"] == "image"
    assert "visual_structure" not in items["p2-i4"]

    growth = items["p2-i8"]
    assert growth["type"] == growth["content_type"] == "chart"
    assert growth["meta"]["phase05_visual_source_text"]["promoted_primary"] is False
    assert growth.get("layout_visual_source_text_promoted") is not True
    assert "$82B" in growth["md"] and "$56B" in growth["md"]
    assert "2022 2023 2024 Q1'25 ARR" in growth["md"]
    assert not growth["visual_structure"]["series"]
    assert not growth["visual_structure"]["points"]

    margin = items["p2-i11"]
    assert margin["type"] == margin["content_type"] == "chart"
    assert margin["source"] == "native"
    assert margin["layout_visual_source_text_promoted"] is True
    assert margin["md"] == margin["visual_structure"]["serialization"]["markdown"]
    assert "Q1'25 ARR" in margin["md"]
    assert "QU25" not in margin["md"]
    assert not margin["visual_structure"]["series"]
    assert not margin["visual_structure"]["points"]

    for item_id in ("p3-i2", "p3-i3"):
        group = items[item_id]
        structure = group["visual_structure"]
        assert group["type"] == group["content_type"] == "diagram"
        assert len(structure["nodes"]) == 7
        assert {node["shape"] for node in structure["nodes"]} == {"ellipse"}
        assert structure["connectors"] == []
        assert structure["fallback"]["active"] is True
        assert "diagram_relationships_not_structured" in (
            group.get("parse_concerns") or []
        )
        assert not any("arrow" in str(value).casefold() for value in structure.values())


@pytest.mark.integration
def test_esg_uncaptioned_visuals_route_from_explicit_printed_chart_signatures() -> None:
    source = CORPUS / "esg-metrics.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["esg-metrics"]
    )
    payload = _parse_local_fidelity("esg-metrics")
    items = {item["id"]: item for item in _items(payload)}

    for item_id in ("p1-i13", "p1-i16"):
        chart = items[item_id]
        structure = chart["visual_structure"]
        assert chart["type"] == chart["content_type"] == "chart"
        assert chart.get("classification") is None
        assert chart["meta"]["phase05_visual_source_text"]["promoted_primary"] is False
        assert chart.get("layout_visual_source_text_promoted") is not True
        assert structure["region"]["kind"] == "chart"
        assert not structure["series"]
        assert not structure["points"]

    assert "71%" in items["p1-i13"]["visual_source_text"]
    assert "CY23" in items["p1-i16"]["visual_source_text"]
    # Fused source-layer year/footnote glyphs stay diagnostic and never
    # replace the more complete approved OCR presentation.
    assert "FY245" not in items["p1-i16"]["md"]
    assert "CY211" not in items["p1-i16"]["md"]


@pytest.mark.integration
def test_health_native_chart_text_cleans_character_split_source_glyphs() -> None:
    source = CORPUS / "health-report.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["health-report"]
    )
    payload = _parse_local_fidelity("health-report")
    items = {item["id"]: item for item in _items(payload)}
    first = items["p1-i2"]

    assert first["type"] == first["content_type"] == "chart"
    assert first["source"] == "native"
    assert first["layout_visual_source_text_promoted"] is True
    assert first["md"] == first["value"] == first["visual_source_text"]
    assert first["md"].startswith(
        "Total Men Women\n"
        "Age-standardised mortality rate per 100 000 population\n"
    )
    assert "\nT\no\nt\na\nl\n" not in first["md"]
    assert not first["visual_structure"]["series"]
    assert not first["visual_structure"]["points"]
    assert items["p1-i6"]["type"] == "chart"


@pytest.mark.integration
def test_manufacturing_first_uncaptioned_region_routes_without_invented_values() -> None:
    source = CORPUS / "manufacturing-report.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["manufacturing-report"]
    )
    payload = _parse_local_fidelity("manufacturing-report")
    charts = [item for item in _items(payload) if item.get("type") == "chart"]
    first = next(item for item in charts if item.get("id") == "p1-i2")

    assert len(charts) == 5
    assert first["content_type"] == "chart"
    assert first.get("classification") is None
    assert first["source"] == "native"
    assert first["layout_visual_source_text_promoted"] is True
    assert first["md"] == first["visual_source_text"]
    assert "United States, 1.6%" in first["md"]
    assert "World, 3.8%" in first["md"]
    assert not first["visual_structure"]["series"]
    assert not first["visual_structure"]["points"]


@pytest.mark.integration
def test_clean_energy_incomplete_native_layer_stays_semantic_sidecar_only() -> None:
    source = CORPUS / "clean-energy.pdf"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256["clean-energy"]
    )
    payload = _parse_local_fidelity("clean-energy")
    chart = next(item for item in _items(payload) if item.get("id") == "p1-i3")

    assert chart["type"] == chart["content_type"] == "chart"
    assert chart["meta"]["phase05_visual_source_text"]["promoted_primary"] is False
    assert chart.get("layout_visual_source_text_promoted") is not True
    assert chart["source"] == "ocr"
    assert "2022 2023" in chart["md"]
    assert "2022" not in chart["visual_source_text"]
    assert not chart["visual_structure"]["series"]
    assert not chart["visual_structure"]["points"]
