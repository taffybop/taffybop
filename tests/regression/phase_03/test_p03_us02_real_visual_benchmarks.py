"""Real-document regression coverage for P03-US02."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.config import Settings
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
LOCAL_FIDELITY_ARTIFACTS = WORKSPACE / ".models" / "docling"

CORPUS_SHA256 = {
    "catastrophe-recap": (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    ),
    "manufacturing-report": (
        "414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f"
    ),
    "uber-earnings": (
        "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
    ),
    "component-datasheet": (
        "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
    ),
    "finance-10k": (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    ),
}

# page, caption text, caption bbox, owner bbox, caption side
EXPECTED_LINKED_CAPTIONS = {
    "catastrophe-recap": [
        (
            1,
            "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)",
            (100.700, 401.275, 218.160, 9.351),
            (100.221, 437.310, 444.032, 149.057),
            "above",
        )
    ],
    "manufacturing-report": [
        (
            1,
            (
                "Figure 2.2: National 5-Year Compound Annual Growth, by "
                "Country (2018 to 2023): Higher is Better"
            ),
            (102.240, 663.309, 410.151, 20.883),
            (92.235, 403.530, 418.890, 242.893),
            "below",
        ),
        (
            2,
            (
                "Figure 2.7: U.S. Manufacturing Share of GDP, Constant "
                "vs. Current Dollars"
            ),
            (139.800, 236.829, 335.154, 9.360),
            (90.325, 37.601, 408.357, 179.583),
            "below",
        ),
        (
            2,
            (
                "Figure 2.8: Global Manufacturing Value Added by "
                "Industry, by Country/Region (2020)"
            ),
            (117.360, 670.509, 382.912, 9.360),
            (98.456, 286.447, 417.317, 370.763),
            "below",
        ),
        (
            3,
            (
                "Figure 4.3: Average Weekly Hours for All Employees "
                "(Seasonally Adjusted)"
            ),
            (139.200, 422.709, 336.359, 9.360),
            (89.097, 146.063, 430.534, 259.492),
            "below",
        ),
    ],
}

EXHIBIT_8_CHILDREN = {
    "er cas": (161.061, 438.535, 26.962, 6.259),
    "C": (273.276, 438.535, 15.836, 6.259),
}

UBER_FALSE_PHOTO_OCR = {
    "é",
    "™=",
    "aus",
    ">",
    ";",
    "“if",
    "La",
    "hen",
    "ate",
    "7",
    "Ne",
    "or",
    "/",
    "o",
    "4",
    "rN",
    ".»™",
    "~",
    "a",
}
EXPECTED_UBER_CONTAINED_VALUES = frozenset(
    {
        "/",
        "4",
        "7",
        ";",
        "La",
        "Ne",
        "a",
        "ate",
        "aus",
        "hen",
        "o",
        "or",
        "rN",
        "é",
        "“if",
    }
)
EXPECTED_UBER_CONTAINED_VALUE_SHA256 = (
    "459ab313b2309c951fb41189a7cec8d5e63130147628cdb45fcc27b86f2eced2"
)

COMPONENT_CAPTION = "Figure 1. The Raspberry Pi Pico Rev3 board."


def _settings(enabled: bool) -> Settings:
    return Settings(
        # Keep the predecessor/flag-parity checks on the same offline local
        # artifact contract as the release-fidelity run.  The optional figure
        # classifier is intentionally absent and must not be downloaded.
        docling_artifacts_path=str(LOCAL_FIDELITY_ARTIFACTS),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_visual_relationships_enabled=enabled,
    )


def _local_fidelity_settings() -> Settings:
    """Mirror the benchmark's local deterministic feature profile."""

    return Settings(
        docling_artifacts_path=str(LOCAL_FIDELITY_ARTIFACTS),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=True,
        layout_outline_structure_enabled=True,
        layout_running_regions_enabled=True,
        table_span_fidelity_enabled=True,
        table_evidence_reconciliation_enabled=True,
        table_candidate_gate_enabled=True,
        table_multi_page_merge_enabled=True,
        visual_structure_schema_enabled=True,
        charts_vector_inventory_enabled=True,
        charts_structure_enabled=True,
        charts_vector_values_enabled=True,
        charts_structured_output_enabled=True,
        charts_raster_structure_enabled=True,
        charts_raster_bar_values_enabled=True,
        charts_raster_line_values_enabled=True,
        charts_raster_analysis_enabled=True,
        diagrams_topology_enabled=True,
    )


@lru_cache(maxsize=None)
def _parse(case: str, enabled: bool) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        _settings(enabled),
    ).model_dump(mode="json", exclude_none=False)


@lru_cache(maxsize=None)
def _parse_local_fidelity(case: str) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        _local_fidelity_settings(),
    ).model_dump(mode="json", exclude_none=False)


def _box_tuple(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def _containment_ratio(
    child: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> float:
    child_x, child_y, child_width, child_height = _box_tuple(child)
    owner_x, owner_y, owner_width, owner_height = _box_tuple(owner)
    overlap_width = max(
        min(child_x + child_width, owner_x + owner_width)
        - max(child_x, owner_x),
        0.0,
    )
    overlap_height = max(
        min(child_y + child_height, owner_y + owner_height)
        - max(child_y, owner_y),
        0.0,
    )
    child_area = child_width * child_height
    return (
        overlap_width * overlap_height / child_area
        if child_area > 0
        else 0.0
    )


def _page_items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for page in payload["pages"]
        for item in page["items"]
    ]


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _owner_for_caption(
    page: Mapping[str, Any],
    caption: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    owner_id = caption.get("caption_of")
    for index, item in enumerate(page["items"]):
        if item.get("id") == owner_id:
            return index, item
    raise AssertionError(f"unresolved visual caption owner: {owner_id!r}")


def test_real_visual_fixture_custody_is_unchanged() -> None:
    for case, expected_sha256 in CORPUS_SHA256.items():
        source = (CORPUS / f"{case}.pdf").read_bytes()
        assert hashlib.sha256(source).hexdigest() == expected_sha256


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    ["catastrophe-recap", "manufacturing-report"],
)
def test_real_visual_captions_have_exact_identity_link_and_order(
    case: str,
) -> None:
    payload = _parse(case, True)
    actual = []
    for page in payload["pages"]:
        for caption_position, item in enumerate(page["items"]):
            if item.get("type") != "caption":
                continue
            owner_position, owner = _owner_for_caption(page, item)
            if owner.get("type") not in {"image", "chart", "diagram"}:
                continue

            relationship_id = item.get("relationship_id")
            assert relationship_id
            assert item.get("relationship_type") == "caption_of"
            assert item.get("relationship_basis") == "graph_and_geometry"
            assert item["id"] in (owner.get("caption_ids") or [])
            assert item["id"] in (owner.get("caption_of") or [])
            assert any(
                relationship.get("id") == relationship_id
                and relationship.get("type") == "caption_of"
                and relationship.get("source_id") == item["id"]
                and relationship.get("target_id") == owner["id"]
                for relationship in owner.get("relationships") or []
            )

            caption_box = _box_tuple(item["bbox"])
            owner_box = _box_tuple(owner["bbox"])
            side = (
                "above"
                if caption_box[1] + caption_box[3] <= owner_box[1]
                else "below"
            )
            if side == "above":
                assert caption_position + 1 == owner_position
            else:
                assert owner_position + 1 == caption_position

            # External text belongs to the caption item only. The visual keeps
            # its original region bbox and authorized OCR content.
            assert item["value"] not in str(owner.get("value") or "")
            assert item["value"] not in str(owner.get("md") or "")
            assert item["value"] not in str(owner.get("caption") or "")
            actual.append(
                (
                    page["page_index"],
                    item["value"],
                    caption_box,
                    owner_box,
                    side,
                )
            )

    assert actual == EXPECTED_LINKED_CAPTIONS[case]
    markdown = to_markdown(payload)
    for _page, caption, _caption_box, _owner_box, _side in (
        EXPECTED_LINKED_CAPTIONS[case]
    ):
        assert markdown.count(caption) == 1


@pytest.mark.integration
def test_exhibit_8_children_remain_nested_grounded_and_not_caption_text() -> None:
    payload = _parse("catastrophe-recap", True)
    caption = next(
        item
        for item in _page_items(payload)
        if item.get("type") == "caption"
        and item.get("value")
        == EXPECTED_LINKED_CAPTIONS["catastrophe-recap"][0][1]
    )
    owner = next(
        item
        for item in _page_items(payload)
        if item.get("id") == caption["caption_of"]
    )
    contained = {
        str(item.get("value")): item
        for item in owner.get("contained_items") or []
    }

    assert set(EXHIBIT_8_CHILDREN) <= set(contained)
    assert not (set(EXHIBIT_8_CHILDREN) & set(caption["value"].splitlines()))
    for text, expected_bbox in EXHIBIT_8_CHILDREN.items():
        child = contained[text]
        assert child.get("type") == "visual_text"
        assert child.get("presentation_role") == "subordinate"
        assert child.get("contained_by") == owner["id"]
        assert _box_tuple(child["bbox"]) == expected_bbox
        assert child["id"] in (owner.get("contains_ids") or [])
        assert any(
            relationship.get("type") == "contains"
            and relationship.get("source_id") == owner["id"]
            and relationship.get("target_id") == child["id"]
            for relationship in owner.get("relationships") or []
        )


@pytest.mark.integration
def test_uber_uncaptioned_photo_ocr_remains_subordinate() -> None:
    payload = _parse("uber-earnings", True)
    first_page = payload["pages"][0]
    owner = next(
        item
        for item in first_page["items"]
        if item.get("type") == "image"
        and _box_tuple(item["bbox"])
        == (68.978, 69.672, 1781.229, 522.914)
    )

    assert owner.get("include_ocr_in_primary") is False
    assert not owner.get("caption")
    assert not owner.get("caption_source")
    assert not owner.get("value")
    assert str(owner.get("md") or "").startswith("[Image detected;")
    assert not [
        item
        for item in first_page["items"]
        if item.get("type") == "caption"
        and item.get("caption_of") == owner["id"]
    ]

    contained = owner.get("contained_items") or []
    contained_values = {str(item.get("value")) for item in contained}
    # Fifteen children meet the public 80%-containment gate. The other five
    # declared references remain retained IR evidence with geometry concerns;
    # none may be reclassified or promoted into prose.
    assert len(contained) == len(contained_values) == 15
    assert contained_values == EXPECTED_UBER_CONTAINED_VALUES
    assert contained_values < UBER_FALSE_PHOTO_OCR
    assert all(
        _containment_ratio(item["bbox"], owner["bbox"]) >= 0.80
        for item in contained
    )
    assert not (
        UBER_FALSE_PHOTO_OCR
        & set(str(owner.get("value") or "").splitlines())
    )
    assert not (
        UBER_FALSE_PHOTO_OCR
        & set(str(owner.get("md") or "").splitlines())
    )
    assert all(
        item.get("presentation_role") == "subordinate"
        and item.get("contained_by") == owner["id"]
        for item in contained
    )


@pytest.mark.integration
def test_uber_photo_ocr_remains_subordinate_in_local_fidelity_profile() -> None:
    assert LOCAL_FIDELITY_ARTIFACTS.is_dir()
    payload = _parse_local_fidelity("uber-earnings")
    first_page = payload["pages"][0]
    owner = next(
        item
        for item in first_page["items"]
        if item.get("type") == "image"
        and _box_tuple(item["bbox"])
        == (68.978, 69.672, 1781.229, 522.914)
    )

    assert any(
        "Picture classification was skipped" in warning
        for warning in payload["warnings"]
    )
    assert owner.get("classification") is None
    assert owner.get("confidence") == 0.5419
    assert owner.get("include_ocr_in_primary") is False
    assert owner.get("value") == ""
    assert str(owner.get("md") or "").startswith("[Image detected;")
    assert owner.get("ocr_text")
    assert not (
        UBER_FALSE_PHOTO_OCR
        & set(str(owner.get("value") or "").splitlines())
    )
    assert not (
        UBER_FALSE_PHOTO_OCR
        & set(str(owner.get("md") or "").splitlines())
    )

    markdown = to_markdown(payload)
    assert "fate\nie\nYe\n1 pet" not in markdown


@pytest.mark.integration
def test_manufacturing_chart_ocr_survives_subpoint_crop_coordinate_drift() -> None:
    payload = _parse_local_fidelity("manufacturing-report")
    owner = next(
        item
        for item in payload["pages"][0]["items"]
        if item.get("id") == "p1-i2"
    )
    expected_ocr = (
        "25th 50th 75th 100th\n"
        "20.0% Percentile Percentile Percentile\n"
        "15.0%\n"
        "United States, 1.6%\n"
        "10.0% || Australia, 0.3% India, 6.5%\n"
        "5.0% Japan, 1.1%\n"
        "World, 3.8% Ireland, 6.5%\n"
        "0.0%\n"
        "-5.0% Germany, 1.7%\n"
        "@ italy, 0.1%\n"
        "Mexico, 1.4%\n"
        "-10.0% France, 1.0%\n"
        "-15.0%"
    )

    assert owner.get("include_ocr_in_primary") is True
    assert owner.get("detected_text") is True
    assert type(owner.get("detected_text")) is bool
    assert owner.get("ocr_text") == expected_ocr
    assert owner.get("source") == "native"
    assert owner.get("layout_visual_source_text_promoted") is True
    assert owner.get("value") == owner.get("md") == owner.get(
        "visual_source_text"
    )
    assert "United States, 1.6%" in owner["md"]
    assert "World, 3.8%" in owner["md"]
    assert not owner["visual_structure"]["series"]
    assert not owner["visual_structure"]["points"]
    assert owner.get("caption") is None
    assert to_markdown(payload).count(owner["md"]) == 1
    assert payload["canonical_presentation"]["full"]["markdown"].count(
        owner["md"]
    ) == 1


@pytest.mark.integration
def test_component_photo_caption_is_preserved_without_invented_ownership() -> None:
    payload = _parse("component-datasheet", True)
    first_page = payload["pages"][0]
    source_caption_items = [
        item
        for item in first_page["items"]
        if item.get("value") == COMPONENT_CAPTION
    ]
    owner = next(
        item
        for item in first_page["items"]
        if item.get("type") == "image"
        and _box_tuple(item["bbox"])
        == (114.983, 151.646, 295.742, 265.243)
    )

    assert len(source_caption_items) == 1
    assert not source_caption_items[0].get("caption_of")
    assert source_caption_items[0]["id"] not in (
        owner.get("caption_ids") or []
    )
    assert not [
        item
        for item in first_page["items"]
        if item.get("type") == "caption"
        and item.get("caption_of") == owner["id"]
    ]
    assert to_markdown(payload).count(COMPONENT_CAPTION) == 1


@pytest.mark.integration
def test_finance_non_target_is_semantically_exact_with_flag_on_and_off() -> None:
    enabled = _parse("finance-10k", True)
    disabled = _parse("finance-10k", False)

    assert _semantic_payload(enabled) == _semantic_payload(disabled)
    assert to_markdown(enabled) == to_markdown(disabled)
    assert not [
        item
        for item in _page_items(enabled)
        if item.get("type") == "caption"
    ]
    assert not [
        relationship
        for item in _page_items(enabled)
        for relationship in item.get("relationships") or []
        if relationship.get("type") in {"caption_of", "contains"}
    ]
