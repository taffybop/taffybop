"""Release-first coverage for bounded, native-first Office fallback."""

from __future__ import annotations

import io
import multiprocessing
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import create_app
from app.models import OfficeVisualFallback, ParseResult
from app.services.office_fallback import (
    DeterministicOfficeRenderer,
    OfficeRenderRequest,
    OfficeRenderResult,
    UnavailableOfficeRenderer,
    apply_office_visual_fallback,
)
from app.services.pptx_adapter import PPTX_MIME_TYPE
from tests.stories.phase_07.office_fixture_helpers import pptx_fixture


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "adapters_conformance_enabled": True,
        "adapters_image_parity_enabled": True,
        "adapters_ooxml_intake_enabled": True,
        "adapters_docx_native_enabled": True,
        "adapters_pptx_native_enabled": True,
        "adapters_xlsx_native_enabled": True,
        "adapters_office_charts_enabled": True,
        "adapters_office_fallback_enabled": True,
        "adapters_office_fallback_max_regions": 2,
        "adapters_office_fallback_max_width": 8,
        "adapters_office_fallback_max_height": 8,
        "adapters_office_fallback_max_total_pixels": 64,
        "adapters_office_fallback_timeout_seconds": 2.0,
    }
    values.update(overrides)
    return Settings(**values)


def _png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (width, height), "white")
    try:
        image.save(output, format="PNG")
    finally:
        image.close()
    return output.getvalue()


def _payload(*, include_placeholder: bool = True) -> dict[str, object]:
    items: list[dict[str, object]] = [
        {
            "id": "native-title",
            "type": "text",
            "value": "Quarterly review",
            "origin": "native",
            "evidence_method": "native",
            "native_provenance": {
                "part": "ppt/slides/slide1.xml",
                "xml_path": "/p:sld/p:cSld/p:spTree/p:sp[1]",
            },
        }
    ]
    if include_placeholder:
        items.append(
            {
                "id": "unsupported-smart-art",
                "type": "diagram",
                "value": "[Unsupported SmartArt]",
                "origin": "native",
                "evidence_method": "native",
                "office_placeholder": {
                    "status": "unsupported",
                    "source_part": "ppt/diagrams/data1.xml",
                    "source_xml_path": "/dgm:dataModel/dgm:ptLst",
                },
                "parse_concerns": ["pptx_smartart_native_unsupported"],
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "fixture.pptx",
            "mime_type": (
                "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation"
            ),
            "sha256": "a" * 64,
            "page_count": 1,
            "source_format": "PPTX",
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "Slide 1",
                "page_width": 720.0,
                "page_height": 540.0,
                "unit": "pt",
                "items": items,
            }
        ],
        "processing": {"input_format": "pptx"},
        "warnings": [],
    }


def _render_result(
    width: int = 8,
    height: int = 8,
    *,
    renderer_name: str = "fixture-renderer",
    transform: tuple[float, float, float, float, float, float] = (
        1.0,
        0.0,
        0.0,
        1.0,
        2.0,
        3.0,
    ),
) -> OfficeRenderResult:
    return OfficeRenderResult(
        png_bytes=_png(width, height),
        width=width,
        height=height,
        renderer_name=renderer_name,
        renderer_version="1.0.0",
        semantic_items=(
            {
                "type": "text",
                "text": "Quarterly review",
                "evidence_method": "ocr",
            },
            {
                "type": "diagram",
                "text": "Approve then archive",
                "evidence_method": "ocr",
            },
        ),
        transform=transform,
    )


def _slow_render(_request: OfficeRenderRequest) -> OfficeRenderResult:
    time.sleep(5.0)
    return _render_result()


def _pixel_budget_result(request: OfficeRenderRequest) -> OfficeRenderResult:
    return _render_result(
        width=4 if request.placeholder_id.endswith("-2") else 6,
        height=4 if request.placeholder_id.endswith("-2") else 6,
    )


def _items(output: dict[str, object]) -> list[dict[str, object]]:
    pages = output["pages"]
    assert isinstance(pages, list)
    items = pages[0]["items"]
    assert isinstance(items, list)
    return items


def test_unsupported_placeholder_gains_only_unique_rendered_evidence() -> None:
    payload = _payload()
    native_before = deepcopy(_items(payload)[0])
    placeholder_before = deepcopy(_items(payload)[1])
    renderer = DeterministicOfficeRenderer(_render_result())

    output = apply_office_visual_fallback(
        payload,
        _settings(),
        renderer=renderer,
        source_bytes=b"bounded-pptx-fixture",
    )

    native, placeholder = _items(output)
    sidecar = placeholder["office_visual_fallback"]
    assert native == native_before
    assert {
        key: placeholder[key]
        for key in placeholder_before
    } == placeholder_before
    assert len(renderer.requests) == 1
    assert renderer.requests[0].placeholder_id == "unsupported-smart-art"
    assert renderer.requests[0].source_part == "ppt/diagrams/data1.xml"
    assert renderer.requests[0].source_bytes == b"bounded-pptx-fixture"
    assert sidecar["status"] == "merged"
    assert sidecar["native_authority"] is True
    assert sidecar["transform"] == [1.0, 0.0, 0.0, 1.0, 2.0, 3.0]
    assert sidecar["transform_source_unit"] == "px"
    assert sidecar["transform_target_unit"] == "pt"
    assert [item["text"] for item in sidecar["items"]] == [
        "Approve then archive"
    ]
    assert sidecar["items"][0]["id"] == (
        "unsupported-smart-art:rendered:1"
    )
    assert sidecar["items"][0]["origin"] == "rendered"
    assert output["processing"]["office_fallback"] == {
        "schema_version": "1.0",
        "status": "completed",
        "rendered_region_count": 1,
        "merged_item_count": 1,
        "deduplicated_item_count": 1,
        "failed_region_count": 0,
        "native_authority": True,
    }
    # The production endpoint accepts only an application-owned renderer
    # capability; the request cannot select or configure one.
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: _settings()
    api_renderer = DeterministicOfficeRenderer(_render_result())
    application.state.office_renderer = api_renderer
    with TestClient(application) as client:
        response = client.post(
            "/v1/parse",
            files={
                "file": (
                    "fallback.pptx",
                    pptx_fixture(),
                    PPTX_MIME_TYPE,
                )
            },
        )
        application.state.office_renderer = DeterministicOfficeRenderer(
            _render_result(renderer_name="x" * 129)
        )
        malformed_response = client.post(
            "/v1/parse",
            files={
                "file": (
                    "fallback.pptx",
                    pptx_fixture(),
                    PPTX_MIME_TYPE,
                )
            },
        )
        del application.state.office_renderer
        unavailable_response = client.post(
            "/v1/parse",
            files={
                "file": (
                    "fallback.pptx",
                    pptx_fixture(),
                    PPTX_MIME_TYPE,
                )
            },
        )
    assert response.status_code == 200
    public_items = response.json()["pages"][0]["items"]
    public_fallback = next(
        item["office_visual_fallback"]
        for item in public_items
        if "office_visual_fallback" in item
    )
    assert public_fallback["status"] == "merged"
    wrong_page = response.json()
    next(
        item["office_visual_fallback"]
        for item in wrong_page["pages"][0]["items"]
        if "office_visual_fallback" in item
    )["logical_label"] = "Slide 9"
    with pytest.raises(ValueError, match="Office fallback page binding differs"):
        ParseResult.model_validate(wrong_page)
    assert api_renderer.requests
    schemas = application.openapi()["components"]["schemas"]
    assert "office_visual_fallback" in schemas["ContentItem"]["properties"]
    assert "office_fallback" in schemas["ProcessingMetadata"]["properties"]
    assert "OfficeVisualFallback" in schemas
    assert "OfficeFallbackProcessingSummary" in schemas
    unavailable_items = unavailable_response.json()["pages"][0]["items"]
    unavailable = next(
        item["office_visual_fallback"]
        for item in unavailable_items
        if "office_visual_fallback" in item
    )
    assert unavailable["reason"] == "office_renderer_unavailable"
    assert malformed_response.status_code == 200
    malformed_items = malformed_response.json()["pages"][0]["items"]
    malformed = next(
        item["office_visual_fallback"]
        for item in malformed_items
        if "office_visual_fallback" in item
    )
    assert malformed["status"] == "unavailable"
    assert malformed["reason"] == "office_renderer_result_malformed"

    # Identical semantics on distinct logical pages are not duplicates. Native
    # content continues to deduplicate fallback observations on its own page.
    repeated_payload = _payload()
    repeated_pages = repeated_payload["pages"]
    assert isinstance(repeated_pages, list)
    second_page = deepcopy(repeated_pages[0])
    second_page["page_index"] = 2
    second_page["page_number"] = 2
    second_page["page_label"] = "Slide 2"
    second_page["items"][0]["id"] = "native-title-2"
    second_page["items"][1]["id"] = "unsupported-smart-art-2"
    repeated_pages.append(second_page)
    repeated = apply_office_visual_fallback(
        repeated_payload,
        _settings(adapters_office_fallback_max_total_pixels=128),
        renderer=DeterministicOfficeRenderer(_render_result()),
    )
    assert [
        page["items"][1]["office_visual_fallback"]["items"][0]["text"]
        for page in repeated["pages"]
    ] == ["Approve then archive", "Approve then archive"]
    assert repeated["processing"]["office_fallback"]["merged_item_count"] == 2
    assert repeated["processing"]["office_fallback"][
        "deduplicated_item_count"
    ] == 2


def test_supported_native_item_is_neither_rendered_nor_overwritten() -> None:
    payload = _payload(include_placeholder=False)
    before = deepcopy(payload)

    def fail_if_called(_request: object) -> OfficeRenderResult:
        pytest.fail("supported native content must not reach the renderer")

    renderer = DeterministicOfficeRenderer(fail_if_called)
    output = apply_office_visual_fallback(payload, _settings(), renderer=renderer)

    assert renderer.requests == []
    assert _items(output) == _items(before)
    assert output["document"] == before["document"]
    assert output["processing"]["office_fallback"]["rendered_region_count"] == 0


@pytest.mark.parametrize(
    ("renderer", "reason"),
    [
        (UnavailableOfficeRenderer(), "office_renderer_unavailable"),
        (DeterministicOfficeRenderer(_slow_render), "office_renderer_timeout"),
    ],
)
def test_renderer_failure_preserves_native_item_and_records_concern(
    renderer: object,
    reason: str,
) -> None:
    payload = _payload()
    placeholder_before = deepcopy(_items(payload)[1])
    child_pids_before = {
        process.pid for process in multiprocessing.active_children()
    }
    started = time.monotonic()

    output = apply_office_visual_fallback(
        payload,
        _settings(adapters_office_fallback_timeout_seconds=0.25),
        renderer=renderer,
    )
    elapsed = time.monotonic() - started

    placeholder = _items(output)[1]
    expected_native = deepcopy(placeholder_before)
    expected_native.pop("parse_concerns")
    assert {
        key: placeholder[key]
        for key in placeholder_before
        if key != "parse_concerns"
    } == expected_native
    assert placeholder["parse_concerns"][:-1] == placeholder_before[
        "parse_concerns"
    ]
    assert placeholder["office_visual_fallback"]["status"] == "unavailable"
    assert placeholder["office_visual_fallback"]["reason"] == reason
    assert reason in placeholder["parse_concerns"]
    assert output["processing"]["office_fallback"]["failed_region_count"] == 1
    if reason == "office_renderer_timeout":
        assert elapsed < 2.0
        assert {
            process.pid for process in multiprocessing.active_children()
        } <= child_pids_before


def test_renderer_output_is_rejected_outside_declared_pixel_bounds() -> None:
    renderer = DeterministicOfficeRenderer(_render_result(width=5, height=4))

    output = apply_office_visual_fallback(
        _payload(),
        _settings(
            adapters_office_fallback_max_width=4,
            adapters_office_fallback_max_height=4,
            adapters_office_fallback_max_total_pixels=16,
        ),
        renderer=renderer,
    )

    request = renderer.requests[0]
    placeholder = _items(output)[1]
    assert (request.max_width, request.max_height, request.max_pixels) == (4, 4, 16)
    assert placeholder["office_visual_fallback"]["renderer"] is None
    assert placeholder["office_visual_fallback"]["reason"] == (
        "office_renderer_resource_limit"
    )
    assert "office_renderer_resource_limit" in placeholder["parse_concerns"]

    valid_png = _png(4, 4)
    byte_bounded_renderer = DeterministicOfficeRenderer(
        OfficeRenderResult(
            # A valid PNG remains valid with trailing bytes, so the byte gate
            # must run before Pillow decoding and before child-to-parent IPC.
            png_bytes=valid_png + b"oversized-trailing-data",
            width=4,
            height=4,
            renderer_name="fixture-renderer",
            renderer_version="1.0.0",
            semantic_items=(
                {
                    "type": "diagram",
                    "text": "must not be admitted",
                    "evidence_method": "ocr",
                },
            ),
        )
    )
    native_before = deepcopy(_items(_payload())[1])
    byte_bounded = apply_office_visual_fallback(
        _payload(),
        _settings(adapters_office_fallback_max_renderer_bytes=len(valid_png)),
        renderer=byte_bounded_renderer,
    )
    byte_bounded_item = _items(byte_bounded)[1]
    assert byte_bounded_renderer.requests[0].max_renderer_bytes == len(valid_png)
    assert {
        key: byte_bounded_item[key]
        for key in native_before
        if key != "parse_concerns"
    } == {
        key: native_before[key]
        for key in native_before
        if key != "parse_concerns"
    }
    assert byte_bounded_item["parse_concerns"][:-1] == native_before[
        "parse_concerns"
    ]
    assert byte_bounded_item["office_visual_fallback"]["status"] == "unavailable"
    assert byte_bounded_item["office_visual_fallback"]["reason"] == (
        "office_renderer_resource_limit"
    )
    assert "office_renderer_resource_limit" in byte_bounded_item["parse_concerns"]
    with pytest.raises(
        ValueError,
        match="PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_RENDERER_BYTES",
    ):
        _settings(adapters_office_fallback_max_renderer_bytes=0)

    document = _payload()
    second = deepcopy(_items(document)[1])
    second["id"] = "unsupported-smart-art-2"
    _items(document).append(second)
    cumulative_renderer = DeterministicOfficeRenderer(_pixel_budget_result)

    cumulative = apply_office_visual_fallback(
        document,
        _settings(adapters_office_fallback_max_total_pixels=50),
        renderer=cumulative_renderer,
    )

    assert [request.max_pixels for request in cumulative_renderer.requests] == [
        50,
        14,
    ]
    first_item, second_item = _items(cumulative)[1:]
    assert first_item["office_visual_fallback"]["status"] == "merged"
    assert second_item["office_visual_fallback"]["reason"] == (
        "office_renderer_resource_limit"
    )

    for invalid_transform in (
        (1e308, 1e308, 1e308, 1e308, 0.0, 0.0),
        (1e308, 0.0, 0.0, 1.0, 0.0, 0.0),
        (float("inf"), 0.0, 0.0, 1.0, 0.0, 0.0),
    ):
        invalid = apply_office_visual_fallback(
            _payload(),
            _settings(),
            renderer=DeterministicOfficeRenderer(
                _render_result(transform=invalid_transform)
            ),
        )
        invalid_sidecar = _items(invalid)[1]["office_visual_fallback"]
        assert invalid_sidecar["status"] == "unavailable"
        assert invalid_sidecar["reason"] == "office_renderer_transform_invalid"

    public_sidecar = deepcopy(
        first_item["office_visual_fallback"]
    )
    public_sidecar["transform"] = [
        1e308,
        1e308,
        1e308,
        1e308,
        0.0,
        0.0,
    ]
    with pytest.raises(ValidationError, match="not invertible"):
        OfficeVisualFallback.model_validate(public_sidecar, strict=True)


def test_flag_off_is_an_exact_no_renderer_predecessor_path() -> None:
    payload = _payload()

    def fail_if_called(_request: object) -> OfficeRenderResult:
        pytest.fail("flag-off fallback must not invoke a renderer")

    renderer = DeterministicOfficeRenderer(fail_if_called)
    output = apply_office_visual_fallback(
        payload,
        Settings(),
        renderer=renderer,
        source_bytes=b"ignored",
    )

    assert output == payload
    assert renderer.requests == []
