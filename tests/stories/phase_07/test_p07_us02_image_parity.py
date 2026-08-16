from __future__ import annotations

import hashlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.adapter_contracts import (
    AdapterBoundingBox,
    AdapterCoordinateTransform,
)
from app.services.visual_parity import (
    SharedVisualServiceRequest,
    VisualParityElement,
    VisualParityEnvelope,
    VisualParityError,
    VisualParityRelationship,
    VisualParitySource,
    compare_visual_parity,
    normalize_visual_semantics,
    run_shared_visual_service,
    visual_parity_envelope_from_public,
)


def _source(
    variant: str,
    *,
    pdf_scale: float = 2.0,
    page_label: str = "1",
) -> VisualParitySource:
    if variant == "direct_image":
        return VisualParitySource(
            source_id="direct-source",
            variant="direct_image",
            content_origin="uploaded_page",
            page_index=1,
            page_label=page_label,
            source_width=200.0,
            source_height=100.0,
            source_sha256="1" * 64,
            transform_to_common=AdapterCoordinateTransform(
                id="direct-to-common",
                source_unit="px",
                target_unit="px",
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            ),
        )
    return VisualParitySource(
        source_id="pdf-render-source",
        variant="pdf_render",
        content_origin="pdf_page_render",
        page_index=1,
        page_label=page_label,
        source_width=100.0,
        source_height=50.0,
        source_sha256="2" * 64,
        transform_to_common=AdapterCoordinateTransform(
            id="pdf-render-to-common",
            source_unit="pt",
            target_unit="px",
            matrix=[pdf_scale, 0.0, 0.0, pdf_scale, 0.0, 0.0],
        ),
    )


def _envelope(
    variant: str,
    *,
    pdf_scale: float = 2.0,
    chart_text: str = "Revenue by region",
    concerns: list[str] | None = None,
    page_label: str = "1",
) -> VisualParityEnvelope:
    direct = variant == "direct_image"
    factor = 1.0 if direct else 0.5
    unit = "px" if direct else "pt"
    origin = "uploaded_page" if direct else "pdf_page_render"
    prefix = "direct" if direct else "rendered"
    elements = [
        VisualParityElement(
            id=f"{prefix}-chart-id",
            ordinal=0,
            page_index=1,
            type="chart",
            text=chart_text,
            role="primary",
            bbox=AdapterBoundingBox(
                x=20.0 * factor,
                y=10.0 * factor,
                width=100.0 * factor,
                height=60.0 * factor,
                unit=unit,
            ),
            content_origin=origin,
            evidence_methods=["ocr", "raster"],
            source_locator=f"{prefix}:object:91",
        ),
        VisualParityElement(
            id=f"{prefix}-caption-id",
            ordinal=1,
            page_index=1,
            type="caption",
            text="Quarterly results",
            role="primary",
            bbox=AdapterBoundingBox(
                x=20.0 * factor,
                y=75.0 * factor,
                width=100.0 * factor,
                height=10.0 * factor,
                unit=unit,
            ),
            content_origin=origin,
            evidence_methods=["ocr"],
            source_locator=f"{prefix}:token:402",
        ),
    ]
    relationships = [
        VisualParityRelationship(
            id=f"{prefix}-relationship-id",
            type="caption_of",
            source_id=f"{prefix}-caption-id",
            target_id=f"{prefix}-chart-id",
        )
    ]
    return VisualParityEnvelope(
        source=_source(variant, pdf_scale=pdf_scale, page_label=page_label),
        elements=elements,
        relationships=relationships,
        concerns=concerns or ["chart_values_not_structured"],
        canonical_markdown="Quarterly results\r\n\r\nRevenue by region\r\n",
        canonical_text="Quarterly results\nRevenue by region\n",
    )


def test_direct_image_and_pdf_render_match_after_coordinate_normalization() -> None:
    direct = _envelope("direct_image")
    rendered = _envelope("pdf_render")

    report = compare_visual_parity(direct, rendered)

    assert report.equivalent is True
    assert report.status == "match"
    assert report.mismatches == []
    assert report.compared_element_count == 2
    assert report.compared_relationship_count == 1


def test_adapter_local_ids_locators_and_expected_origins_do_not_mask_semantics() -> None:
    direct = normalize_visual_semantics(_envelope("direct_image"))
    rendered = normalize_visual_semantics(_envelope("pdf_render"))

    assert [value.semantic_id for value in direct.elements] == [
        value.semantic_id for value in rendered.elements
    ]
    assert [value.origin for value in direct.elements] == [
        "visual_source",
        "visual_source",
    ]
    assert direct.relationships == rendered.relationships
    assert direct.common_page_bbox == rendered.common_page_bbox


def test_valid_but_wrong_transform_reports_actionable_mismatch() -> None:
    report = compare_visual_parity(
        _envelope("direct_image"),
        _envelope("pdf_render", pdf_scale=1.8),
    )

    assert report.equivalent is False
    assert report.status == "mismatch"
    assert "parity_transform_mismatch" in {
        mismatch.code for mismatch in report.mismatches
    }
    assert "parity_geometry_mismatch" in {
        mismatch.code for mismatch in report.mismatches
    }


@pytest.mark.parametrize(
    ("rendered", "expected_code"),
    [
        (
            _envelope("pdf_render", chart_text="Revenue by market"),
            "parity_text_mismatch",
        ),
        (
            _envelope("pdf_render", concerns=["chart_axis_unsupported"]),
            "parity_concern_mismatch",
        ),
        (
            _envelope("pdf_render", page_label="printed-2"),
            "parity_page_identity_mismatch",
        ),
    ],
)
def test_core_semantic_differences_have_specific_reason_codes(
    rendered: VisualParityEnvelope,
    expected_code: str,
) -> None:
    report = compare_visual_parity(_envelope("direct_image"), rendered)

    assert expected_code in {mismatch.code for mismatch in report.mismatches}


def test_relationship_direction_difference_is_not_hidden_by_id_normalization() -> None:
    rendered = _envelope("pdf_render")
    payload = rendered.model_dump(mode="json")
    relationship = payload["relationships"][0]
    relationship["source_id"], relationship["target_id"] = (
        relationship["target_id"],
        relationship["source_id"],
    )
    reversed_relationship = VisualParityEnvelope.model_validate(payload, strict=True)

    report = compare_visual_parity(
        _envelope("direct_image"),
        reversed_relationship,
    )

    assert "parity_relationship_mismatch" in {
        mismatch.code for mismatch in report.mismatches
    }


def test_shared_service_contract_routes_both_variants_through_one_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raster = b"same representative raster pixels"

    class Service:
        def __init__(self) -> None:
            self.variants: list[str] = []

        def analyze(self, request: SharedVisualServiceRequest) -> VisualParityEnvelope:
            self.variants.append(request.source.variant)
            return _envelope(request.source.variant).model_copy(
                update={"source": request.source}
            )

    service = Service()
    requests = [
        SharedVisualServiceRequest(
            request_id=f"request-{variant}",
            source=_source(variant),
            raster_width=200,
            raster_height=100,
            raster_byte_length=len(raster),
            raster_sha256=hashlib.sha256(raster).hexdigest(),
            raster_bytes=raster,
            evidence_ids=["fixture-evidence"],
        )
        for variant in ("direct_image", "pdf_render")
    ]

    direct, rendered = [
        run_shared_visual_service(request, service) for request in requests
    ]

    assert service.variants == ["direct_image", "pdf_render"]
    assert compare_visual_parity(direct, rendered).equivalent is True

    # The runtime flag selects the same input-neutral OCR seam used by direct
    # raster pages and PDF-rendered regions while flag-off retains the former
    # direct calls.
    import app.services.ocr as ocr_module

    routed: list[bytes] = []
    monkeypatch.setattr(ocr_module, "_resolve_tesseract", lambda _value: "fixture")
    monkeypatch.setattr(
        ocr_module,
        "run_shared_visual_ocr",
        lambda _executable, png, *_args, **_kwargs: (
            routed.append(png) or [],
            [],
            [],
        ),
    )
    page = SimpleNamespace(
        page_index=1,
        pixel_width=2,
        pixel_height=2,
        png_bytes=b"bounded-raster",
        original_orientation=None,
        orientation_applied=False,
    )
    ocr_module.extract_raster_ocr(
        [page],
        shared_visual_service_enabled=True,
    )
    assert routed == [b"bounded-raster"]


def test_shared_service_rejects_an_envelope_bound_to_another_source() -> None:
    raster = b"pixels"
    request = SharedVisualServiceRequest(
        request_id="request-direct",
        source=_source("direct_image"),
        raster_width=200,
        raster_height=100,
        raster_byte_length=len(raster),
        raster_sha256=hashlib.sha256(raster).hexdigest(),
        raster_bytes=raster,
        evidence_ids=[],
    )

    with pytest.raises(VisualParityError) as captured:
        run_shared_visual_service(
            request,
            lambda _request: _envelope("pdf_render"),
        )

    assert captured.value.code == "parity_service_source_mismatch"


def test_public_payload_helper_compares_json_and_canonical_views() -> None:
    def payload(*, rendered: bool) -> dict[str, Any]:
        factor = 0.5 if rendered else 1.0
        unit = "pt" if rendered else "px"
        origin = "pdf_page_render" if rendered else "uploaded_page"
        return {
            "pages": [
                {
                    "page_index": 1,
                    "page_label": "1",
                    "page_width": 100.0 if rendered else 200.0,
                    "page_height": 50.0 if rendered else 100.0,
                    "unit": unit,
                    "items": [
                        {
                            "id": "rendered-chart" if rendered else "direct-chart",
                            "type": "chart",
                            "value": "Revenue",
                            "source": "ocr",
                            "region_origin": origin,
                            "bbox": {
                                "x": 10.0 * factor,
                                "y": 5.0 * factor,
                                "width": 80.0 * factor,
                                "height": 40.0 * factor,
                            },
                        }
                    ],
                }
            ],
            "canonical_presentation": {
                "full": {"markdown": "Revenue\n", "text": "Revenue\n"}
            },
        }

    direct = visual_parity_envelope_from_public(
        payload(rendered=False),
        _source("direct_image"),
        include_types=["chart"],
    )
    rendered = visual_parity_envelope_from_public(
        payload(rendered=True),
        _source("pdf_render"),
        include_types=["chart"],
    )

    assert compare_visual_parity(direct, rendered).equivalent is True


def test_duplicate_elements_and_malformed_source_origin_fail_strict_validation() -> None:
    payload = _envelope("direct_image").model_dump(mode="json")
    payload["elements"][1]["id"] = payload["elements"][0]["id"]

    with pytest.raises(ValidationError, match="repeat an ID"):
        VisualParityEnvelope.model_validate(payload, strict=True)

    source = _source("direct_image").model_dump(mode="json")
    source["content_origin"] = "pdf_page_render"
    with pytest.raises(ValidationError, match="differs from its variant"):
        VisualParitySource.model_validate(source, strict=True)


def test_invalid_mapping_returns_bounded_failure_report() -> None:
    malformed = deepcopy(_envelope("pdf_render").model_dump(mode="json"))
    malformed["elements"][0]["bbox"]["x"] = float("nan")

    report = compare_visual_parity(_envelope("direct_image"), malformed)

    assert report.status == "mismatch"
    assert [value.code for value in report.mismatches] == [
        "parity_input_invalid"
    ]
    assert report.compared_element_count == 0
