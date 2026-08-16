"""API-boundary custody checks for projected P03-US08 output."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.models import ParseResult
from tests.stories.phase_03.test_p03_us08_running_regions import (
    _direct_projected_witness,
)


def _valid_projected_result() -> dict[str, Any]:
    projected, _ir, _predecessor, _predecessor_ir = _direct_projected_witness()
    projected.update({"schema_version": "1.0", "warnings": []})
    projected["document"].update(
        {
            "filename": "projected.pdf",
            "mime_type": "application/pdf",
            "page_count": 1,
        }
    )
    projected["processing"].update(
        {
            "engine": "docling",
            "ocr_engine": "tesseract",
            "ocr_languages": ["eng"],
            "duration_ms": 0,
        }
    )
    projected["canonical_presentation"].update(
        {
            "schema_version": "1.0",
            "source_ir_version": "1.0",
            "policy_id": "canonical-presentation-v1",
        }
    )
    return projected


def test_projected_api_model_accepts_exact_cross_surface_witness() -> None:
    payload = _valid_projected_result()
    validated = ParseResult.model_validate(payload)
    assert validated.document.sha256 == "1" * 64


def test_projected_api_encoder_retains_closed_explicit_nulls() -> None:
    encoded = jsonable_encoder(ParseResult.model_validate(_valid_projected_result()))
    summary = encoded["processing"]["running_regions"]
    identity = encoded["pages"][0]["page_identity"]
    descriptor = encoded["pages"][0]["items"][0]["running_region"]

    assert set(summary) == set(
        (
            "policy_id",
            "status",
            "reason",
            "source_page_count",
            "identity_count",
            "detected_label_count",
            "embedded_label_count",
            "legacy_fallback_count",
            "candidate_count",
            "comparison_count",
            "running_region_count",
            "header_count",
            "footer_count",
            "top_navigation_count",
            "bottom_navigation_count",
            "concern_count",
            "extraction_ms",
            "projection_ms",
            "total_ms",
        )
    )
    assert summary["reason"] is None
    assert "embedded_label" in identity
    assert "unavailable_reason" in identity["confidence"]
    assert "repetition_group_id" in descriptor
    assert "unavailable_reason" in descriptor["confidence"]


def test_projected_api_model_rejects_compact_owner_numeric_coercion() -> None:
    payload = _valid_projected_result()
    item = payload["pages"][0]["items"][0]
    descriptor = item["running_region"]
    for field in ("x", "y", "width", "height"):
        item["bbox"][field] = int(item["bbox"][field])
        descriptor["bbox"][field] = int(descriptor["bbox"][field])

    with pytest.raises(
        ValidationError,
        match="projected predecessor compact item differs",
    ):
        ParseResult.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("document", "sha256"), "A" * 64),
        (("document", "page_count"), True),
        (("pages", 0, "page_index"), True),
        (("pages", 0, "page_width"), "612"),
        (("pages", 0, "items", 0, "reading_order"), False),
        (("pages", 0, "items", 0, "confidence"), "1.0"),
        (("pages", 0, "page_identity", "page_id"), "forged-page"),
        (
            ("pages", 0, "items", 0, "running_region", "id"),
            "running-region-forged",
        ),
        (
            (
                "pages",
                0,
                "items",
                0,
                "running_region",
                "predecessor_item_sha256",
            ),
            "0" * 64,
        ),
        (
            ("canonical_presentation", "pages", 0, "page_identity", "page_id"),
            "forged-page",
        ),
        (
            ("canonical_presentation", "pages", 0, "footer", "text"),
            "forged\n",
        ),
    ],
)
def test_projected_api_model_rejects_cross_surface_tampering(
    path: tuple[str | int, ...], replacement: Any
) -> None:
    payload = _valid_projected_result()
    current: Any = payload
    for segment in path[:-1]:
        current = current[segment]
    current[path[-1]] = replacement
    with pytest.raises(ValidationError):
        ParseResult.model_validate(payload)


def test_summary_free_api_model_rejects_even_empty_us08_fields() -> None:
    payload = _valid_projected_result()
    payload["processing"].pop("running_regions")
    payload.pop("canonical_presentation")
    payload["pages"][0].pop("page_identity")
    item = payload["pages"][0]["items"][0]
    item.pop("layout_running_region_projected")
    item.pop("running_region_policy")
    item.pop("running_region")
    payload["running_region_concerns"] = []
    with pytest.raises(ValidationError, match="require a summary"):
        ParseResult.model_validate(payload)


def test_summary_free_api_model_rejects_nested_us08_remnant() -> None:
    payload = _valid_projected_result()
    payload["processing"].pop("running_regions")
    payload.pop("canonical_presentation")
    payload["pages"][0].pop("page_identity")
    item = payload["pages"][0]["items"][0]
    item.pop("layout_running_region_projected")
    item.pop("running_region_policy")
    item.pop("running_region")
    item["properties"] = {"running_region_shadow": {}}
    with pytest.raises(ValidationError, match="retains running-region"):
        ParseResult.model_validate(payload)


def test_projected_api_model_rejects_content_bearing_exception() -> None:
    payload = _valid_projected_result()
    payload["processing"]["running_regions"]["concern_count"] = 1
    payload["running_region_concerns"] = [
        {
            "code": "running_region_geometry_ambiguous",
            "source_ref": "page:1",
            "count": 1,
            "cap": 64,
            "exception_class": "SecretPayload",
        }
    ]
    with pytest.raises(ValidationError, match="content-free"):
        ParseResult.model_validate(payload)


def test_nonprojecting_api_model_rejects_explicit_empty_concern_ledger() -> None:
    payload = _valid_projected_result()
    payload.pop("canonical_presentation")
    payload["pages"][0].pop("page_identity")
    item = payload["pages"][0]["items"][0]
    item.pop("layout_running_region_projected")
    item.pop("running_region_policy")
    item.pop("running_region")
    payload["processing"]["running_regions"] = {
        **payload["processing"]["running_regions"],
        "status": "not_applicable",
        "reason": "running_region_input_not_applicable",
        "source_page_count": 0,
        "identity_count": 0,
        "detected_label_count": 0,
        "legacy_fallback_count": 0,
        "candidate_count": 0,
        "running_region_count": 0,
        "footer_count": 0,
    }
    payload["running_region_concerns"] = []
    with pytest.raises(ValidationError, match="presence differs"):
        ParseResult.model_validate(payload)
