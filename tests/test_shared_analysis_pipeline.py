"""Cross-format regression tests for the shared page-analysis pipeline.

The source raster and the PDFs in this module are generated in memory.  This
keeps the regression portable and, importantly, proves that the same pixels
are exercised as a direct upload, a full-page scanned PDF, and an embedded PDF
image.  Expensive OCR/layout calls are mocked in the deterministic tests; one
opt-in smoke test exercises the installed engines end to end.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import shutil
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import pytest
from PIL import Image, ImageDraw, ImageFont

import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind, LoadedDocument, load_document
from app.services.ocr import ImageRegion, OCRLine
from app.services.serializer import to_markdown


PAGE_WIDTH = 900
PAGE_HEIGHT = 650


def _raster_document() -> bytes:
    """Return a deterministic text-and-photograph-like page."""

    image = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), "#f5f7f7")
    draw = ImageDraw.Draw(image)
    heading = ImageFont.load_default(size=46)
    subheading = ImageFont.load_default(size=34)
    body = ImageFont.load_default(size=22)

    # A bounded visual region gives layout analysis something separate from
    # the page-source raster.  Shapes and labels are intentionally generic.
    draw.rounded_rectangle(
        (50, 55, 850, 235),
        radius=14,
        fill="#dcece7",
        outline="#557a70",
        width=3,
    )
    draw.rectangle((90, 105, 260, 210), fill="#197b67")
    draw.rectangle((330, 85, 470, 210), fill="#6aaa96")
    draw.rectangle((540, 125, 770, 210), fill="#b8d8cd")
    draw.text((107, 138), "IMAGE LABEL", fill="white", font=body)

    draw.text((50, 270), "Shared Pipeline Report", fill="black", font=heading)
    draw.text((700, 285), "May 7, 2025", fill="black", font=body)
    draw.text((50, 350), "Q1 2025 Earnings", fill="black", font=subheading)
    draw.text(
        (50, 420),
        "Revenue grew across all regions.",
        fill="black",
        font=body,
    )

    output = io.BytesIO()
    try:
        image.save(output, format="PNG", optimize=False)
        return output.getvalue()
    finally:
        image.close()


def _insert_native_text(
    document: pdfium.PdfDocument,
    page: pdfium.PdfPage,
    text: str,
    *,
    x: float,
    y: float,
    size: float,
) -> None:
    """Insert real machine-readable PDF text with PDFium's public/raw API."""

    font = pdfium.PdfFont.load_standard(document, "Helvetica")
    raw_object = pdfium_raw.FPDFPageObj_CreateTextObj(
        document.raw,
        font.raw,
        float(size),
    )
    encoded = (text + "\x00").encode("utf-16-le")
    encoded_pointer = ctypes.cast(
        encoded,
        ctypes.POINTER(ctypes.c_ushort),
    )
    assert pdfium_raw.FPDFText_SetText(raw_object, encoded_pointer)
    text_object = pdfium.PdfObject(raw_object, pdf=document)
    text_object.set_matrix(pdfium.PdfMatrix(e=x, f=y))
    page.insert_obj(text_object)


def _pdf_with_raster(
    raster_bytes: bytes,
    *,
    image_box: tuple[float, float, float, float],
    native_text: Iterable[tuple[str, float, float, float]] = (),
) -> bytes:
    """Embed the supplied raster in a one-page PDF without re-encoding it."""

    with Image.open(io.BytesIO(raster_bytes)) as source:
        source.load()
        bitmap = pdfium.PdfBitmap.from_pil(source.convert("RGB"))

    document = pdfium.PdfDocument.new()
    page = document.new_page(PAGE_WIDTH, PAGE_HEIGHT)
    try:
        left, bottom, width, height = image_box
        image_object = pdfium.PdfImage.new(document)
        image_object.set_bitmap(bitmap)
        image_object.set_matrix(
            pdfium.PdfMatrix()
            .scale(width, height)
            .translate(left, bottom)
        )
        page.insert_obj(image_object)
        for value, x, y, size in native_text:
            _insert_native_text(
                document,
                page,
                value,
                x=x,
                y=y,
                size=size,
            )
        page.gen_content()
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()
    finally:
        page.close()
        document.close()
        bitmap.close()


@pytest.fixture(scope="module")
def raster_bytes() -> bytes:
    return _raster_document()


@pytest.fixture(scope="module")
def scanned_pdf_bytes(raster_bytes: bytes) -> bytes:
    return _pdf_with_raster(
        raster_bytes,
        image_box=(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )


@pytest.fixture(scope="module")
def embedded_pdf_bytes(raster_bytes: bytes) -> bytes:
    return _pdf_with_raster(
        raster_bytes,
        image_box=(100, 100, 600, 300),
        native_text=(("NATIVE REPORT TITLE", 50, 600, 24),),
    )


def _image_objects(pdf_bytes: bytes) -> list[Any]:
    document = pdfium.PdfDocument(pdf_bytes)
    page = document[0]
    try:
        return list(
            page.get_objects(filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,))
        )
    finally:
        # Objects are only used by callers while this helper performs their
        # inspection, so return plain values instead of live page handles.
        page.close()
        document.close()


def _embedded_raster_digest(pdf_bytes: bytes) -> tuple[tuple[int, int], str]:
    document = pdfium.PdfDocument(pdf_bytes)
    page = document[0]
    try:
        image_object = next(
            page.get_objects(filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,))
        )
        bitmap = image_object.get_bitmap()
        try:
            embedded = bitmap.to_pil().convert("RGB")
            try:
                return embedded.size, hashlib.sha256(
                    embedded.tobytes()
                ).hexdigest()
            finally:
                embedded.close()
        finally:
            bitmap.close()
    finally:
        page.close()
        document.close()


def test_pdf_fixtures_contain_the_exact_same_source_raster(
    raster_bytes: bytes,
    scanned_pdf_bytes: bytes,
    embedded_pdf_bytes: bytes,
) -> None:
    """Guard against accidentally comparing different test images."""

    with Image.open(io.BytesIO(raster_bytes)) as source:
        source_rgb = source.convert("RGB")
        try:
            expected = (
                source_rgb.size,
                hashlib.sha256(source_rgb.tobytes()).hexdigest(),
            )
        finally:
            source_rgb.close()

    assert _embedded_raster_digest(scanned_pdf_bytes) == expected
    assert _embedded_raster_digest(embedded_pdf_bytes) == expected


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


def _text_item(
    index: int,
    value: str,
    *,
    label: str,
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, Any]:
    return {
        "self_ref": f"#/texts/{index}",
        "label": label,
        "text": value,
        "prov": _prov(x, y, width, height),
    }


def _shared_cover_layout() -> dict[str, Any]:
    picture = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": _prov(50, 55, 800, 180),
        "meta": {
            "classification": {
                "predictions": [
                    {
                        "class_name": "photograph",
                        "confidence": 0.98,
                    }
                ]
            }
        },
    }
    date = _text_item(
        0,
        "May 7, 2025",
        label="text",
        x=700,
        y=285,
        width=150,
        height=20,
    )
    section = _text_item(
        1,
        "Q1 2025 Earnings",
        label="section_header",
        x=50,
        y=350,
        width=340,
        height=40,
    )
    paragraph = _text_item(
        2,
        "Revenue grew across all regions.",
        label="text",
        x=50,
        y=420,
        width=430,
        height=20,
    )
    return {
        "texts": [date, section, paragraph],
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


def _full_page_ocr(*, pdf: bool) -> ImageRegion:
    lines = [
        OCRLine(
            text="‘",
            bbox={"x": 165, "y": 85, "w": 12, "h": 20},
            confidence=0.19,
            word_count=1,
        ),
        OCRLine(
            text="fae",
            bbox={"x": 390, "y": 120, "w": 42, "h": 18},
            confidence=0.23,
            word_count=1,
        ),
        # Layout intentionally misses this title.
        OCRLine(
            text="Shared Pipeline Report",
            bbox={"x": 50, "y": 265, "w": 520, "h": 52},
            confidence=0.97,
            word_count=3,
        ),
        # Compact spacing must reconcile to the authoritative layout spelling.
        OCRLine(
            text="May7,2025",
            bbox={"x": 700, "y": 285, "w": 150, "h": 20},
            confidence=0.90,
            word_count=1,
        ),
        OCRLine(
            text="Q1 2025 Earnings",
            bbox={"x": 50, "y": 350, "w": 340, "h": 40},
            confidence=0.95,
            word_count=3,
        ),
        OCRLine(
            text="Revenue grew across all regions.",
            bbox={"x": 50, "y": 420, "w": 430, "h": 20},
            confidence=0.96,
            word_count=5,
        ),
    ]
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={
            "x": 0,
            "y": 0,
            "w": PAGE_WIDTH,
            "h": PAGE_HEIGHT,
        },
        pixel_width=PAGE_WIDTH,
        pixel_height=PAGE_HEIGHT,
        area_ratio=1.0,
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=0.88,
        # PDF ingestion discovers an image object; direct-image ingestion calls
        # the same pixels a page image. Shared analysis must infer the same
        # page-source role from geometry rather than this adapter label.
        content_type="image" if pdf else "page_image",
    )


def _pdf_page(
    *,
    native_text: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    return (
        [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": float(PAGE_WIDTH),
                "page_height": float(PAGE_HEIGHT),
                "unit": "pt",
                "success": True,
                "items": [],
                "detected_images": [],
                "warnings": [],
            }
        ],
        [native_text],
    )


def _mock_shared_engines(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raw_layout: dict[str, Any],
    direct_region: ImageRegion | None = None,
    pdf_region: ImageRegion | None = None,
    native_text: str = "",
) -> None:
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (raw_layout, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: (
            {1: [direct_region]} if direct_region is not None else {1: []}
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_image_ocr",
        lambda *_args, **_kwargs: (
            {1: [pdf_region]} if pdf_region is not None else {1: []}
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: _pdf_page(native_text=native_text),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "_extract_table_repair_words",
        lambda *_args, **_kwargs: {},
    )


def _parse_loaded(loaded: LoadedDocument) -> dict[str, Any]:
    return pipeline._parse_loaded_document(
        loaded,
        Settings(),
    ).model_dump(mode="json")


def _primary_values(result: dict[str, Any]) -> list[str]:
    return [
        str(item.get("value") or "")
        for item in result["pages"][0]["items"]
        if item["type"] not in {"image", "chart", "diagram"}
    ]


def test_direct_image_and_scanned_pdf_share_quality_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
    raster_bytes: bytes,
    scanned_pdf_bytes: bytes,
) -> None:
    """The same pixels must receive the same primary-text decisions."""

    direct = load_document(
        raster_bytes,
        "shared-page.png",
        Settings(),
    )
    scanned = load_document(
        scanned_pdf_bytes,
        "shared-page.pdf",
        Settings(),
    )
    direct_region = _full_page_ocr(pdf=False)
    pdf_region = _full_page_ocr(pdf=True)
    _mock_shared_engines(
        monkeypatch,
        raw_layout=_shared_cover_layout(),
        direct_region=direct_region,
        pdf_region=pdf_region,
    )

    direct_result = _parse_loaded(direct)
    scanned_result = _parse_loaded(scanned)

    expected_values = [
        "Shared Pipeline Report",
        "May 7, 2025",
        "Q1 2025 Earnings",
        "Revenue grew across all regions.",
    ]
    assert _primary_values(direct_result) == expected_values
    assert _primary_values(scanned_result) == expected_values

    direct_markdown = to_markdown(direct_result)
    scanned_markdown = to_markdown(scanned_result)
    assert direct_markdown == scanned_markdown
    for markdown in (direct_markdown, scanned_markdown):
        assert "# Shared Pipeline Report" in markdown
        assert markdown.count("May 7, 2025") == 1
        assert "May7,2025" not in markdown
        assert "fae" not in markdown
        assert "‘" not in markdown

    for result in (direct_result, scanned_result):
        page = result["pages"][0]
        title = next(
            item
            for item in page["items"]
            if item.get("value") == "Shared Pipeline Report"
        )
        photograph = next(
            item
            for item in page["items"]
            if item.get("classification", {}).get("class_name")
            == "photograph"
        )
        page_source = page["detected_images"][0]

        assert title["type"] == "heading"
        assert title["label"] == "inferred_heading"
        assert photograph["region_role"] == "content_region"
        assert [line["value"] for line in photograph["items"]] == ["‘", "fae"]
        assert all(line["accepted"] is False for line in photograph["items"])
        assert page_source["region_role"] == "page_source"


def _embedded_chart_layout() -> dict[str, Any]:
    title = _text_item(
        0,
        "NATIVE REPORT TITLE",
        label="section_header",
        x=50,
        y=30,
        width=340,
        height=30,
    )
    chart = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": _prov(100, 250, 600, 300),
        "meta": {
            "classification": {
                "predictions": [
                    {"class_name": "bar_chart", "confidence": 0.98}
                ]
            }
        },
    }
    return {
        "texts": [title],
        "tables": [],
        "pictures": [chart],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/pictures/0"},
            ]
        },
    }


def _embedded_chart_region() -> ImageRegion:
    lines = [
        OCRLine(
            text="fae",
            bbox={"x": 135, "y": 275, "w": 32, "h": 17},
            confidence=0.20,
            word_count=1,
        ),
        OCRLine(
            text="Revenue by Region",
            bbox={"x": 140, "y": 315, "w": 250, "h": 24},
            confidence=0.94,
            word_count=3,
        ),
        OCRLine(
            text="North 40 South 60",
            bbox={"x": 150, "y": 410, "w": 360, "h": 24},
            confidence=0.91,
            word_count=4,
        ),
    ]
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 100, "y": 250, "w": 600, "h": 300},
        pixel_width=PAGE_WIDTH,
        pixel_height=PAGE_HEIGHT,
        area_ratio=round((600 * 300) / (PAGE_WIDTH * PAGE_HEIGHT), 6),
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=0.87,
        content_type="image",
    )


def test_embedded_pdf_chart_uses_shared_visual_ocr_and_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    embedded_pdf_bytes: bytes,
) -> None:
    """PDF picture regions get the same classification and OCR filtering."""

    loaded = load_document(
        embedded_pdf_bytes,
        "embedded-chart.pdf",
        Settings(),
    )
    region = _embedded_chart_region()
    _mock_shared_engines(
        monkeypatch,
        raw_layout=_embedded_chart_layout(),
        pdf_region=region,
        native_text="NATIVE REPORT TITLE",
    )

    result = _parse_loaded(loaded)
    page = result["pages"][0]
    title = next(
        item
        for item in page["items"]
        if item.get("value") == "NATIVE REPORT TITLE"
    )
    chart = next(item for item in page["items"] if item["type"] == "chart")

    assert title["source"] == "native"
    assert chart["region_role"] == "content_region"
    assert chart["classification"] == {
        "class_name": "bar_chart",
        "confidence": 0.98,
    }
    assert chart["ocr_text"] == "Revenue by Region\nNorth 40 South 60"
    assert "fae" in chart["raw_ocr_text"]
    assert [entry["accepted"] for entry in chart["items"]] == [
        False,
        True,
        True,
    ]
    assert chart["items"][0]["rejection_reason"] == "low_confidence"

    markdown = to_markdown(result)
    assert markdown.count("NATIVE REPORT TITLE") == 1
    assert markdown.count("Revenue by Region") == 1
    assert markdown.count("North 40 South 60") == 1
    assert "fae" not in markdown


def _native_overlay_layout() -> dict[str, Any]:
    title = _text_item(
        0,
        "NATIVE REPORT TITLE",
        label="section_header",
        x=50,
        y=25,
        width=340,
        height=30,
    )
    return {
        "texts": [title],
        "tables": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": "#/texts/0"}]},
    }


def _native_overlay_ocr() -> ImageRegion:
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": PAGE_WIDTH, "h": PAGE_HEIGHT},
        pixel_width=PAGE_WIDTH,
        pixel_height=PAGE_HEIGHT,
        area_ratio=1.0,
        text="NATIVEREPORTTITLE",
        lines=[
            OCRLine(
                text="NATIVEREPORTTITLE",
                bbox={"x": 50, "y": 25, "w": 340, "h": 30},
                confidence=0.96,
                word_count=1,
            )
        ],
        confidence=0.96,
        content_type="image",
    )


def test_native_pdf_text_is_authoritative_over_overlapping_visual_ocr(
    monkeypatch: pytest.MonkeyPatch,
    raster_bytes: bytes,
) -> None:
    """A searchable text layer must not be replaced or emitted twice."""

    searchable_scan = _pdf_with_raster(
        raster_bytes,
        image_box=(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        native_text=(("NATIVE REPORT TITLE", 50, 600, 24),),
    )
    loaded = load_document(
        searchable_scan,
        "searchable-scan.pdf",
        Settings(),
    )
    _mock_shared_engines(
        monkeypatch,
        raw_layout=_native_overlay_layout(),
        pdf_region=_native_overlay_ocr(),
        native_text="NATIVE REPORT TITLE",
    )

    result = _parse_loaded(loaded)
    title_items = [
        item
        for item in result["pages"][0]["items"]
        if "REPORT TITLE" in str(item.get("value") or "")
    ]

    assert len(title_items) == 1
    assert title_items[0]["value"] == "NATIVE REPORT TITLE"
    assert title_items[0]["source"] == "native"
    assert title_items[0]["type"] == "heading"
    markdown = to_markdown(result)
    assert markdown.count("NATIVE REPORT TITLE") == 1
    assert "NATIVEREPORTTITLE" not in markdown
    assert result["pages"][0]["detected_images"][0]["region_role"] == (
        "page_source"
    )


def test_pdf_render_selection_is_selective_and_native_aware() -> None:
    pages, _ = _pdf_page()
    native = "This native sentence has enough characters to be reliable."
    raw_text = _text_item(
        0,
        native,
        label="text",
        x=50,
        y=30,
        width=700,
        height=24,
    )
    reliable_raw = {
        "texts": [raw_text],
        "tables": [],
        "pictures": [],
    }

    assert pipeline._select_pdf_render_requests(
        pages,
        [native],
        reliable_raw,
        {1: []},
        Settings(),
    ) == []

    image_only_requests = pipeline._select_pdf_render_requests(
        pages,
        [""],
        {"texts": [], "tables": [], "pictures": []},
        {1: []},
        Settings(),
    )
    assert len(image_only_requests) == 1
    assert image_only_requests[0].content_type == "page_render"
    assert image_only_requests[0].region_role == "page_source"

    vector_chart = {
        "self_ref": "#/pictures/0",
        "label": "chart",
        "prov": _prov(100, 160, 500, 280),
    }
    chart_requests = pipeline._select_pdf_render_requests(
        pages,
        [native],
        {
            "texts": [raw_text],
            "tables": [],
            "pictures": [vector_chart],
        },
        {1: []},
        Settings(),
    )
    assert len(chart_requests) == 1
    assert chart_requests[0].content_type == "chart"
    assert chart_requests[0].region_role == "content_region"


def _complete_raw_table(
    rows: list[list[str]],
    *,
    page_no: int = 1,
) -> dict[str, Any]:
    cells = []
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            cells.append(
                {
                    "text": text,
                    "start_row_offset_idx": row_index,
                    "end_row_offset_idx": row_index + 1,
                    "start_col_offset_idx": column_index,
                    "end_col_offset_idx": column_index + 1,
                    "row_span": 1,
                    "col_span": 1,
                }
            )
    return {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": [
            {
                "page_no": page_no,
                "bbox": {
                    "l": 20.0,
                    "t": 40.0,
                    "r": 880.0,
                    "b": 590.0,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
        "data": {
            "num_rows": len(rows),
            "num_cols": len(rows[0]),
            "table_cells": cells,
        },
    }


def _stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_complete_native_table_keeps_full_page_visual_recovery(
) -> None:
    rows = [
        ["Stop", "Weekdays", "Saturday", "Sunday"],
        ["Ferry South", "12:04", "12:14", "12:24"],
        ["Lincoln Center", "12:10", "12:20", ""],
    ]
    footer_text = "Metropolitan Transportation Authority"
    native_text = "\n".join(
        [*(" ".join(row) for row in rows), footer_text]
    )
    raw = {
        "texts": [
            _text_item(
                0,
                footer_text,
                label="page_footer",
                x=30,
                y=615,
                width=360,
                height=18,
            )
        ],
        "tables": [_complete_raw_table(rows)],
        "pictures": [],
    }
    table_markdown = "<table>" + "".join(
        "<tr>"
        + "".join(f"<td>{value}</td>" for value in row)
        + "</tr>"
        for row in rows
    ) + "</table>"
    table_item = {
        "id": "table-1",
        "type": "table",
        "rows": rows,
        "value": rows,
        "md": table_markdown,
        "bbox": {
            "x": 20.0,
            "y": 40.0,
            "width": 860.0,
            "height": 550.0,
            "unit": "pt",
        },
    }
    footer_item = {
        "id": "footer-1",
        "type": "footer",
        "value": footer_text,
        "md": footer_text,
        "bbox": {
            "x": 30.0,
            "y": 615.0,
            "width": 360.0,
            "height": 18.0,
            "unit": "pt",
        },
    }
    pages, _ = _pdf_page(native_text=native_text)
    pages[0]["items"] = [table_item, footer_item]
    raw_before = _stable_json_bytes(raw)
    pages_before = _stable_json_bytes(pages)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        raw,
        {1: []},
        Settings(),
    )

    assert len(requests) == 1
    assert requests[0].content_type == "page_render"
    assert requests[0].region_role == "page_source"
    assert _stable_json_bytes(raw) == raw_before
    assert _stable_json_bytes(pages) == pages_before

    body_items = {1: [table_item, footer_item]}
    body_before = _stable_json_bytes(body_items)
    pipeline._supplement_unrepresented_raster_ocr(
        body_items,
        {1: [table_item]},
        {1: []},
        settings=Settings(),
    )
    assert _stable_json_bytes(body_items) == body_before
    markdown = to_markdown({"pages": [{"page_index": 1, "items": body_items[1]}]})
    assert markdown.count(table_markdown) == 1
    assert markdown.count(footer_text) == 1
    assert markdown.count("12:04") == 1


def test_dense_table_over_512_cells_keeps_full_page_visual_recovery(
) -> None:
    rows = [
        [f"r{row_index:02d}c{column_index:02d}" for column_index in range(13)]
        for row_index in range(52)
    ]
    rows[-1][-5:] = ["", "", "", "", ""]
    native_text = " ".join(value for row in rows for value in row)
    raw = {
        "texts": [],
        "tables": [_complete_raw_table(rows)],
        "pictures": [],
    }
    # Mirror the real timetable's sparse Docling grid while retaining more
    # than 95% source-token coverage and more than 512 concrete cells.
    del raw["tables"][0]["data"]["table_cells"][-5:]
    pages, _ = _pdf_page(native_text=native_text)
    raw_before = _stable_json_bytes(raw)
    pages_before = _stable_json_bytes(pages)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        raw,
        {1: []},
        Settings(),
    )

    assert len(raw["tables"][0]["data"]["table_cells"]) == 52 * 13 - 5
    assert len(requests) == 1
    assert requests[0].content_type == "page_render"
    assert requests[0].region_role == "page_source"
    assert _stable_json_bytes(raw) == raw_before
    assert _stable_json_bytes(pages) == pages_before


@pytest.mark.parametrize(
    "variant",
    (
        "partial",
        "empty",
        "malformed-provenance",
        "missing-origin",
        "unsupported-origin",
        "off-page-bbox",
        "malformed-cell",
    ),
)
def test_unreliable_raw_table_coverage_retains_full_page_render(
    variant: str,
) -> None:
    rows = [
        ["Route", "Weekday", "Weekend"],
        ["North Harbor", "06:10", "06:25"],
        ["South Terminal", "06:40", "06:55"],
    ]
    native_text = " ".join(value for row in rows for value in row)
    table = _complete_raw_table(rows)
    if variant == "partial":
        # Retain more than the normal 55% token threshold so structural
        # incompleteness, rather than incidental low coverage, is the reason
        # this raw grid cannot suppress the render fallback.
        table["data"]["table_cells"].pop()
    elif variant == "empty":
        table["data"]["table_cells"] = []
    elif variant == "malformed-provenance":
        table["prov"] = [{"page_no": "one", "bbox": {}}]
    elif variant == "missing-origin":
        table["prov"][0]["bbox"].pop("coord_origin")
    elif variant == "unsupported-origin":
        table["prov"][0]["bbox"]["coord_origin"] = "CENTER"
    elif variant == "off-page-bbox":
        table["prov"][0]["bbox"]["r"] = PAGE_WIDTH + 1.0
    elif variant == "malformed-cell":
        table["data"]["table_cells"][1] = "not-a-cell"
    pages, _ = _pdf_page(native_text=native_text)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        {"texts": [], "tables": [table], "pictures": []},
        {1: []},
        Settings(),
    )

    assert any(request.region_role == "page_source" for request in requests)


def test_scanned_page_still_renders_even_with_complete_raw_table_text() -> None:
    rows = [["Code", "Value"], ["A", "10"], ["B", "20"]]
    pages, _ = _pdf_page(native_text="")

    requests = pipeline._select_pdf_render_requests(
        pages,
        [""],
        {
            "texts": [],
            "tables": [_complete_raw_table(rows)],
            "pictures": [],
        },
        {1: []},
        Settings(),
    )

    assert len(requests) == 1
    assert requests[0].region_role == "page_source"
    assert requests[0].metadata["render_reason"] == "little_or_no_native_text"


def test_table_text_does_not_hide_unrepresented_native_prose() -> None:
    rows = [["Code", "Value"], ["A", "10"], ["B", "20"]]
    omitted = " ".join(
        [
            "This explanatory paragraph is intentionally absent from layout",
            "and therefore still requires the page-source recovery path",
        ]
    )
    native_text = " ".join(
        [*(value for row in rows for value in row), omitted]
    )
    pages, _ = _pdf_page(native_text=native_text)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        {
            "texts": [],
            "tables": [_complete_raw_table(rows)],
            "pictures": [],
        },
        {1: []},
        Settings(),
    )

    assert any(request.region_role == "page_source" for request in requests)


@pytest.mark.parametrize(
    ("rows", "native_text"),
    (
        (["route", "café", "✓", "†", "→"], "route café ✓ † →"),
        (["route", "caf"], "route café ✓ † →"),
        (["us"], "US"),
    ),
    ids=(
        "exact-unicode-closure",
        "unicode-content-missing",
        "case-drift",
    ),
)
def test_unicode_table_content_keeps_visual_recovery(
    rows: list[str],
    native_text: str,
) -> None:
    pages, _ = _pdf_page(native_text=native_text)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        {
            "texts": [],
            "tables": [_complete_raw_table([rows])],
            "pictures": [],
        },
        {1: []},
        Settings(),
    )

    assert any(request.region_role == "page_source" for request in requests)


@pytest.mark.parametrize(
    "provenance_variant",
    ("missing", "multiple", "off-page"),
)
def test_table_closure_ignores_prose_without_strict_page_provenance(
    provenance_variant: str,
) -> None:
    rows = [[f"table{index:02d}" for index in range(10)]]
    note = "short-footnote"
    native_text = " ".join([*rows[0], note])
    raw_note = _text_item(
        0,
        note,
        label="text",
        x=20,
        y=610,
        width=180,
        height=20,
    )
    if provenance_variant == "missing":
        raw_note["prov"] = []
    elif provenance_variant == "multiple":
        raw_note["prov"].append(deepcopy(raw_note["prov"][0]))
    else:
        raw_note["prov"][0]["bbox"]["r"] = PAGE_WIDTH + 1.0
    pages, _ = _pdf_page(native_text=native_text)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        {
            "texts": [raw_note],
            "tables": [_complete_raw_table(rows)],
            "pictures": [],
        },
        {1: []},
        Settings(),
    )

    assert pipeline._normalized_token_coverage(native_text, note) < 0.55
    assert any(request.region_role == "page_source" for request in requests)


def test_sparse_second_table_cannot_borrow_dominant_table_coverage() -> None:
    dominant_rows = [
        [f"primary-{row_index}-{column_index}" for column_index in range(6)]
        for row_index in range(5)
    ]
    sparse_rows = [["secondary-a", "secondary-b"], ["secondary-c", "missing"]]
    dominant = _complete_raw_table(dominant_rows)
    sparse = _complete_raw_table(sparse_rows)
    sparse["self_ref"] = "#/tables/1"
    sparse["data"]["table_cells"].pop()
    native_text = " ".join(
        [
            *(value for row in dominant_rows for value in row),
            *(value for row in sparse_rows for value in row),
        ]
    )
    pages, _ = _pdf_page(native_text=native_text)

    requests = pipeline._select_pdf_render_requests(
        pages,
        [native_text],
        {"texts": [], "tables": [dominant, sparse], "pictures": []},
        {1: []},
        Settings(),
    )

    assert any(request.region_role == "page_source" for request in requests)


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_SHARED_ANALYSIS_INTEGRATION") != "1",
    reason=(
        "Set RUN_SHARED_ANALYSIS_INTEGRATION=1 to run real cross-format "
        "OCR/layout parity."
    ),
)
@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract is required for shared-pipeline integration.",
)
def test_real_direct_image_and_full_page_pdf_preserve_unique_title(
    raster_bytes: bytes,
    scanned_pdf_bytes: bytes,
) -> None:
    """Opt-in smoke coverage for the installed OCR and layout engines."""

    settings = Settings(document_timeout_seconds=180.0)
    image_result = pipeline.parse_document(
        raster_bytes,
        "shared-page.png",
        settings,
    ).model_dump(mode="json")
    pdf_result = pipeline.parse_document(
        scanned_pdf_bytes,
        "shared-page.pdf",
        settings,
    ).model_dump(mode="json")

    for result in (image_result, pdf_result):
        markdown = to_markdown(result).casefold()
        assert markdown.count("shared pipeline report") == 1
        assert markdown.count("revenue grew across all regions") == 1
