"""Release-first coverage for the native PPTX evidence adapter."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.errors import UnsupportedDocumentTypeError
from app.main import create_app
from app.models import ParseResult
from app.services.adapter_contracts import AdapterRegistry, validate_adapter_conformance
from app.services.office_native import (
    OfficeAdapterDisabledError,
    OfficeNativeLimitError,
    OfficeNativePackageError,
)
from app.services.ooxml_intake import OoxmlSignatureError, intake_ooxml
from app.services.pipeline import parse_document
from app.services.pptx_adapter import PPTX_MIME_TYPE, PptxNativeAdapter, parse_pptx
from app.services.serializer import to_markdown, to_text
from tests.stories.phase_07.office_fixture_helpers import (
    pptx_fixture,
    unzip_package,
    zip_package,
)


def test_representative_pptx_preserves_slide_order_text_media_tables_and_z_order() -> None:
    output = parse_pptx(pptx_fixture(), filename="results.pptx")
    result = ParseResult.model_validate(output)

    assert output["document"]["mime_type"] == PPTX_MIME_TYPE
    assert [page["page_label"] for page in output["pages"]] == ["Slide 1", "Slide 2"]
    assert [page["slide_id"] for page in output["pages"]] == ["256", "257"]
    assert output["pages"][1]["visibility"] == "hidden"
    assert output["pages"][1]["items"] == []

    items = output["pages"][0]["items"]
    assert [item["z_order"] for item in items] == list(range(len(items)))
    assert [item["reading_order"] for item in items] == list(range(len(items)))
    assert [item["type"] for item in items] == [
        "heading",
        "group",
        "text",
        "image",
        "table",
        "chart",
        "diagram",
    ]
    assert items[0]["value"] == "Quarterly Results"
    assert items[0]["placeholder_type"] == "title"
    assert items[3]["asset_origin"] == "native_embedded"
    assert items[4]["rows"] == [["Region", "Value"], ["East", "10"]]

    markdown = to_markdown(result)
    assert markdown.count("Quarterly Results") == 1
    assert markdown.count("Grouped text") == 1
    assert markdown.count("<table>") == 1


def test_pptx_composes_basic_group_geometry_in_slide_points() -> None:
    output = parse_pptx(pptx_fixture())
    items = output["pages"][0]["items"]
    group = next(item for item in items if item["type"] == "group")
    grouped_text = next(item for item in items if item.get("value") == "Grouped text")

    assert group["bbox"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 20.0,
        "height": 20.0,
        "unit": "pt",
    }
    assert grouped_text["bbox"] == {
        "x": 12.0,
        "y": 22.0,
        "width": 2.0,
        "height": 4.0,
        "unit": "pt",
    }
    assert grouped_text["native_provenance"]["source_transform"] == [
        2.0,
        0.0,
        0.0,
        2.0,
        127000.0,
        254000.0,
    ]
    assert all(item["bbox"]["unit"] == "pt" for item in items if item.get("bbox"))

    rotated_entries = unzip_package(pptx_fixture())
    rotated_original = rotated_entries["ppt/slides/slide1.xml"]
    rotated = rotated_original.replace(
        b'<p:grpSpPr><a:xfrm><a:off x="127000" y="254000"/><a:ext cx="254000" cy="254000"/><a:chOff x="0" y="0"/><a:chExt cx="127000" cy="127000"/></a:xfrm></p:grpSpPr>',
        b'<p:grpSpPr><a:xfrm rot="5400000"><a:off x="127000" y="254000"/><a:ext cx="254000" cy="127000"/><a:chOff x="0" y="0"/><a:chExt cx="127000" cy="127000"/></a:xfrm></p:grpSpPr>',
        1,
    )
    assert rotated != rotated_original
    rotated_entries["ppt/slides/slide1.xml"] = rotated
    rotated_output = parse_pptx(zip_package(rotated_entries))
    rotated_group = next(
        item for item in rotated_output["pages"][0]["items"] if item["type"] == "group"
    )
    assert rotated_group["bbox"]["x"] == pytest.approx(15.0)
    assert rotated_group["bbox"]["y"] == pytest.approx(15.0)
    assert rotated_group["bbox"]["width"] == pytest.approx(10.0)
    assert rotated_group["bbox"]["height"] == pytest.approx(20.0)
    assert rotated_group["bbox"]["unit"] == "pt"
    assert ParseResult.model_validate(rotated_output)

    entries = unzip_package(pptx_fixture())
    original = entries["ppt/slides/slide1.xml"]
    mutated = original.replace(
        b'<a:ext cx="254000" cy="254000"/><a:chOff x="0" y="0"/><a:chExt cx="127000" cy="127000"/>',
        b'<a:ext cx="1e308" cy="1e308"/><a:chOff x="0" y="0"/><a:chExt cx="1" cy="1"/>',
        1,
    )
    assert mutated != original
    entries["ppt/slides/slide1.xml"] = mutated
    overflow_output = parse_pptx(zip_package(entries))
    overflow_items = overflow_output["pages"][0]["items"]
    invalid_transform = next(
        item
        for item in overflow_items
        if item.get("parse_concerns") == ["pptx_shape_transform_invalid"]
    )
    assert invalid_transform["placeholder"] is True
    assert "bbox" not in invalid_transform
    assert "Infinity" not in json.dumps(overflow_output, allow_nan=False)
    assert ParseResult.model_validate(overflow_output)


def test_pptx_hidden_and_unsupported_content_follow_native_only_policy() -> None:
    output = parse_pptx(pptx_fixture())
    encoded = json.dumps(output, sort_keys=True)
    items = output["pages"][0]["items"]

    assert "LEAK ME NOT" not in encoded
    assert "pptx_hidden_element_omitted" in output["warnings"]
    assert "pptx_hidden_slide_omitted" in output["warnings"]

    chart = next(item for item in items if item["type"] == "chart")
    assert chart["placeholder"] is True
    assert chart["native_chart_pending"] is True
    assert chart["chart_part"] == "ppt/charts/chart1.xml"
    assert chart["parse_concerns"] == ["office_chart_native_data_deferred"]
    assert "visual_structure" not in chart

    diagram = next(item for item in items if item["type"] == "diagram")
    assert diagram["placeholder"] is True
    assert diagram["fallback_eligible"] is True
    assert diagram["parse_concerns"] == ["pptx_smartart_unsupported"]


def test_pptx_accepts_intake_package_and_is_deterministic() -> None:
    data = pptx_fixture()
    package = intake_ooxml(data, "bounded.pptx", PPTX_MIME_TYPE)

    first = parse_pptx(package, filename="bounded.pptx")
    second = parse_pptx(package, filename="bounded.pptx")

    assert first == second
    assert first["document"]["sha256"] == package.source_sha256
    assert ParseResult.model_validate(first).pages[0].unit == "pt"

    entries = unzip_package(data)
    renamed = {
        (f"deck/{name.removeprefix('ppt/')}" if name.startswith("ppt/") else name): value
        for name, value in entries.items()
    }
    renamed["_rels/.rels"] = renamed["_rels/.rels"].replace(
        b"ppt/presentation.xml",
        b"deck/presentation.xml",
    )
    renamed["[Content_Types].xml"] = renamed["[Content_Types].xml"].replace(
        b"/ppt/",
        b"/deck/",
    )
    renamed_package = intake_ooxml(
        zip_package(renamed),
        "renamed.pptx",
        PPTX_MIME_TYPE,
    )
    renamed_output = parse_pptx(renamed_package)
    assert renamed_package.manifest.main_part == "deck/presentation.xml"
    assert renamed_output["pages"][0]["items"][0]["value"] == "Quarterly Results"


def test_pptx_adapter_conforms_and_dispatches_through_shared_registry() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_pptx_native_enabled=True,
    )
    adapter = PptxNativeAdapter(settings)
    assert validate_adapter_conformance(adapter).registration_allowed is True
    registry = AdapterRegistry()
    registry.register(adapter)

    output = registry.dispatch(
        pptx_fixture(),
        "registry.pptx",
        PPTX_MIME_TYPE,
        settings,
    )
    assert ParseResult.model_validate(output).document.filename == "registry.pptx"


def test_pptx_public_pipeline_dispatch_and_flag_off_rollback() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_pptx_native_enabled=True,
    )
    result = parse_document(pptx_fixture(), "public.pptx", settings)

    assert result.document.filename == "public.pptx"
    assert "Quarterly Results" in to_text(result)
    assert "Quarterly Results" in to_markdown(result)

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        response = client.post(
            "/v1/parse?output_format=markdown",
            files={"file": ("public.pptx", pptx_fixture(), PPTX_MIME_TYPE)},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Quarterly Results" in response.text

    with pytest.raises(UnsupportedDocumentTypeError):
        parse_document(pptx_fixture(), "disabled.pptx", Settings())


def test_pptx_disabled_and_shape_limit_restore_safe_unsupported_behavior() -> None:
    with pytest.raises(OfficeAdapterDisabledError) as disabled:
        parse_pptx(pptx_fixture(), enabled=False)
    assert disabled.value.code == "unsupported_document_type"

    with pytest.raises(OfficeNativeLimitError) as limited:
        parse_pptx(pptx_fixture(), max_shapes=2)
    assert limited.value.code == "pptx_shape_limit"


def test_malformed_pptx_fails_at_intake_or_raw_boundary_without_rendering() -> None:
    malformed = b"not an OOXML ZIP"
    with pytest.raises(OoxmlSignatureError):
        intake_ooxml(malformed, "bad.pptx", PPTX_MIME_TYPE)
    with pytest.raises(OfficeNativePackageError) as raw:
        parse_pptx(malformed)
    assert raw.value.code == "office_package_zip_invalid"
