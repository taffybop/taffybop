"""Regression coverage for conservative, image-only quality improvements.

The fixtures in this module are synthetic on purpose: they reproduce the
geometry and OCR failure modes of a cover image without depending on a file in
one developer's Downloads directory.  The tests exercise normalization and
serialization contracts, while all PDF-specific code paths remain untouched.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind, LoadedDocument, SourcePage
from app.services.ocr import (
    ImageRegion,
    OCRLine,
    _merge_sparse_ocr_lines_with_diagnostics,
)
from app.services.serializer import to_markdown


def _prov(
    x: float,
    y: float,
    width: float,
    height: float,
) -> list[dict[str, Any]]:
    return [
        {
            "page_no": 1,
            "bbox": {
                "l": x,
                "t": y,
                "r": x + width,
                "b": y + height,
                "coord_origin": "TOPLEFT",
            },
        }
    ]


def _raw_picture(
    *,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    picture: dict[str, Any] = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": _prov(48, 70, 504, 145),
    }
    if meta is not None:
        picture["meta"] = meta
    return picture


def _cover_raw_docling() -> dict[str, Any]:
    picture = _raw_picture(
        meta={
            "classification": {
                "predictions": [
                    {
                        "class_name": "photograph",
                        "confidence": 0.99,
                    }
                ]
            }
        }
    )
    date = {
        "self_ref": "#/texts/0",
        "label": "text",
        "text": "May 7, 2025",
        "prov": _prov(505, 235, 47, 12),
    }
    subtitle = {
        "self_ref": "#/texts/1",
        "label": "section_header",
        "text": "Q1 2025 Earnings",
        "prov": _prov(48, 300, 307, 35),
    }
    supplemental = {
        "self_ref": "#/texts/2",
        "label": "text",
        "text": "Supplemental Data",
        "prov": _prov(48, 355, 144, 16),
    }
    return {
        "texts": [date, subtitle, supplemental],
        "tables": [],
        "pictures": [picture],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": "#/pictures/0"},
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/texts/2"},
            ]
        },
    }


def _cover_region() -> ImageRegion:
    lines = [
        # False OCR detections inside the photograph. They remain useful as
        # diagnostics, but are not trustworthy document content.
        OCRLine(
            text="‘",
            bbox={"x": 170, "y": 75, "w": 16, "h": 30},
            confidence=0.21,
            word_count=1,
        ),
        OCRLine(
            text="fae",
            bbox={"x": 255, "y": 110, "w": 35, "h": 20},
            confidence=0.24,
            word_count=1,
        ),
        # Docling missed this large title, so full-page OCR must recover it.
        OCRLine(
            text="Uber Technologies, Inc.",
            bbox={"x": 48, "y": 220, "w": 412, "h": 52},
            confidence=0.96,
            word_count=3,
        ),
        # The layout result contains the same date with spaces. This OCR
        # spelling must not be emitted as a second primary item.
        OCRLine(
            text="May7,2025",
            bbox={"x": 505, "y": 235, "w": 47, "h": 12},
            confidence=0.85,
            word_count=1,
        ),
        OCRLine(
            text="Q1 2025 Earnings",
            bbox={"x": 48, "y": 300, "w": 307, "h": 35},
            confidence=0.93,
            word_count=3,
        ),
        OCRLine(
            text="Supplemental Data",
            bbox={"x": 48, "y": 355, "w": 144, "h": 16},
            confidence=0.94,
            word_count=2,
        ),
        # A normal high-confidence line is deliberately also recovered to
        # prove that confidence alone does not turn arbitrary text into a
        # heading.
        OCRLine(
            text="Additional financial information is unaudited.",
            bbox={"x": 48, "y": 395, "w": 390, "h": 16},
            confidence=0.97,
            word_count=5,
        ),
    ]
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 600, "h": 800},
        pixel_width=600,
        pixel_height=800,
        area_ratio=1.0,
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=0.87,
        content_type="page_image",
        metadata={"frame_index": 0},
    )


@pytest.fixture()
def loaded_cover_image() -> LoadedDocument:
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"synthetic cover source",
        processing_bytes=b"synthetic normalized cover",
        original_filename="cover.png",
        processing_filename="cover.normalized.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(
            SourcePage(
                page_index=1,
                pixel_width=600,
                pixel_height=800,
                png_bytes=b"synthetic page PNG",
                original_orientation=None,
                orientation_applied=False,
            ),
        ),
    )


def test_low_confidence_visual_ocr_is_diagnostic_not_primary_markdown() -> None:
    raw = {
        "texts": [],
        "tables": [],
        "pictures": [_raw_picture()],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": "#/pictures/0"}]},
    }
    region = _cover_region()

    body, _tables = pipeline._normalize_docling_body(
        raw,
        {1: 800.0},
        [""],
        {1: [region]},
        preserve_visual_items=True,
    )

    visual = body[1][0]
    assert visual["type"] == "image"
    assert visual["detected_text"] is False
    assert visual["ocr_text"] == ""
    assert [entry["value"] for entry in visual["items"]] == ["‘", "fae"]
    assert all(entry["accepted"] is False for entry in visual["items"])
    assert all(
        entry["rejection_reason"] == "low_confidence"
        for entry in visual["items"]
    )

    markdown = to_markdown(
        {
            "pages": [
                {
                    "items": [
                        {
                            **visual,
                            "id": "p1-i1",
                            "reading_order": 0,
                        }
                    ]
                }
            ]
        }
    )
    assert "fae" not in markdown
    assert "‘" not in markdown


@pytest.mark.parametrize(
    ("confidence", "expected_primary"),
    [
        (0.54, False),
        (0.72, True),
    ],
)
def test_unclassified_visual_requires_reliable_aggregate_ocr_for_primary_text(
    confidence: float,
    expected_primary: bool,
) -> None:
    raw = {
        "texts": [],
        "tables": [],
        "pictures": [_raw_picture()],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": "#/pictures/0"}]},
    }
    lines = [
        OCRLine(
            text="fate token",
            bbox={"x": 90, "y": 100, "w": 90, "h": 14},
            confidence=confidence,
            word_count=2,
        ),
        OCRLine(
            text="blur marks",
            bbox={"x": 260, "y": 150, "w": 90, "h": 14},
            confidence=confidence,
            word_count=2,
        ),
    ]
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 600, "h": 800},
        pixel_width=600,
        pixel_height=800,
        area_ratio=1.0,
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=confidence,
        content_type="page_image",
    )

    body, _tables = pipeline._normalize_docling_body(
        raw,
        {1: 800.0},
        [""],
        {1: [region]},
        preserve_visual_items=True,
    )

    visual = body[1][0]
    assert visual.get("classification") is None
    assert visual["ocr_text"] == "fate token\nblur marks"
    assert visual["confidence"] == confidence
    assert visual["include_ocr_in_primary"] is expected_primary
    if expected_primary:
        assert visual["value"] == visual["ocr_text"]
        assert visual["md"] == visual["ocr_text"]
    else:
        assert visual["value"] == ""
        assert visual["md"] == "[Image detected; no reliable text extracted.]"
        assert "retained as image-level metadata" in visual["warnings"][0]


def test_compact_spacing_variant_is_deduplicated_against_layout_text() -> None:
    layout_date = {
        "type": "text",
        "value": "May 7, 2025",
        "md": "May 7, 2025",
        "bbox": pipeline._bbox(505, 235, 47, 12),
        "source": "ocr",
        "confidence": 0.92,
    }
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 600, "h": 800},
        pixel_width=600,
        pixel_height=800,
        area_ratio=1.0,
        lines=[
            OCRLine(
                text="May7,2025",
                bbox={"x": 505, "y": 235, "w": 47, "h": 12},
                confidence=0.85,
                word_count=1,
            )
        ],
        content_type="page_image",
    )
    body = {1: [layout_date]}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["May 7, 2025"]


def test_informative_small_low_confidence_text_can_still_be_recovered() -> None:
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 320, "h": 180},
        pixel_width=320,
        pixel_height=180,
        area_ratio=1.0,
        lines=[
            OCRLine(
                text="SMALL TOKEN 42",
                bbox={"x": 12, "y": 150, "w": 95, "h": 7},
                confidence=0.35,
                word_count=3,
            )
        ],
        content_type="page_image",
    )
    body: dict[int, list[dict[str, Any]]] = {1: []}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == ["SMALL TOKEN 42"]
    assert body[1][0]["confidence"] == 0.35


def test_overlapping_ocr_passes_keep_better_text_and_reject_artifact() -> None:
    primary = OCRLine(
        text="Uber Technologies, Inc, 7",
        bbox={"x": 49, "y": 401, "w": 503, "h": 67},
        confidence=0.8843,
        word_count=4,
    )
    sparse = OCRLine(
        text="Uber Technologies, Inc.",
        bbox={"x": 49, "y": 395, "w": 411, "h": 73},
        confidence=0.9603,
        word_count=3,
    )

    accepted, rejected = _merge_sparse_ocr_lines_with_diagnostics(
        [primary],
        [sparse],
    )

    assert [line.text for line in accepted] == [
        "Uber Technologies, Inc."
    ]
    assert rejected == [
        {
            **primary.to_dict(),
            "ocr_pass": "standard",
            "accepted": False,
            "rejection_reason": "overlapping_ocr_candidate",
            "replaced_by": "Uber Technologies, Inc.",
        }
    ]


def test_large_recovered_title_is_promoted_without_promoting_body_text(
    monkeypatch: pytest.MonkeyPatch,
    loaded_cover_image: LoadedDocument,
) -> None:
    region = _cover_region()
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (_cover_raw_docling(), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [region]},
    )

    result = pipeline._parse_loaded_document(
        loaded_cover_image,
        Settings(),
    ).model_dump(mode="json")
    page = result["pages"][0]

    title = next(
        item
        for item in page["items"]
        if item.get("value") == "Uber Technologies, Inc."
    )
    body_text = next(
        item
        for item in page["items"]
        if item.get("value")
        == "Additional financial information is unaudited."
    )
    assert title["type"] == "heading"
    assert title["level"] == 1
    assert title["label"] == "inferred_heading"
    assert "heading_inferred_from_image_geometry" in title["parse_concerns"]
    assert body_text["type"] == "text"
    assert body_text["label"] == "ocr_text"

    markdown = to_markdown(result)
    assert "# Uber Technologies, Inc." in markdown
    assert markdown.count("May 7, 2025") == 1
    assert "May7,2025" not in markdown
    assert "fae" not in markdown


def test_page_source_and_content_region_have_explicit_distinct_roles(
    monkeypatch: pytest.MonkeyPatch,
    loaded_cover_image: LoadedDocument,
) -> None:
    region = _cover_region()
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (_cover_raw_docling(), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [region]},
    )

    result = pipeline._parse_loaded_document(
        loaded_cover_image,
        Settings(),
    ).model_dump(mode="json")
    page = result["pages"][0]
    content_region = next(
        item
        for item in page["items"]
        if item["type"] in {"image", "chart", "diagram"}
    )
    page_source = page["detected_images"][0]

    assert content_region["region_role"] == "content_region"
    assert page_source["region_role"] == "page_source"
    assert content_region["bbox"] != page_source["bbox"]
    assert page_source["content_type"] == "page_image"


def test_model_picture_description_is_marked_as_generated_and_has_fallback() -> None:
    description = "A green delivery bag sits among plants by a doorway."
    raw_with_description = {
        "texts": [],
        "tables": [],
        "pictures": [
            _raw_picture(
                meta={
                    "description": {
                        "text": description,
                        "created_by": "smolvlm",
                    }
                }
            )
        ],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": "#/pictures/0"}]},
    }
    raw_without_description = {
        **raw_with_description,
        "pictures": [_raw_picture()],
    }

    described, _tables = pipeline._normalize_docling_body(
        raw_with_description,
        {1: 800.0},
        [""],
        {},
        preserve_visual_items=True,
    )
    fallback, _tables = pipeline._normalize_docling_body(
        raw_without_description,
        {1: 800.0},
        [""],
        {},
        preserve_visual_items=True,
    )

    described_item = described[1][0]
    assert described_item["caption"] == description
    assert described_item["caption_source"] == "smolvlm"
    assert "model_generated_visual_description" in (
        described_item["parse_concerns"]
    )
    assert described_item["md"] == description

    fallback_item = fallback[1][0]
    assert fallback_item["caption"] is None
    assert fallback_item["detected_text"] is False
    assert fallback_item["md"] == (
        "[Image detected; no reliable text extracted.]"
    )


def test_captioning_options_are_local_optional_and_configurable(
    tmp_path,
) -> None:
    options = pipeline._docling_pipeline_options(
        ("eng",),
        "tesseract",
        None,
        str(tmp_path),
        30.0,
        describe_pictures=True,
        picture_description_prompt="Describe only visible content.",
    )

    assert options.do_picture_description is True
    assert options.picture_description_options.batch_size == 1
    assert (
        options.picture_description_options.prompt
        == "Describe only visible content."
    )
    assert pipeline._picture_description_model_available(str(tmp_path)) is False
