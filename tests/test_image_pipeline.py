from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind, LoadedDocument, SourcePage
from app.services.ocr import ImageRegion, OCRLine, _merge_sparse_ocr_lines
from app.services.presentation import CanonicalPresentation
from app.services.serializer import to_markdown


def _prov(
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> list[dict[str, Any]]:
    return [
        {
            "page_no": 1,
            "bbox": {
                "l": left,
                "t": top,
                "r": right,
                "b": bottom,
                "coord_origin": "TOPLEFT",
            },
        }
    ]


def _text(
    index: int,
    label: str,
    value: str,
    *,
    top: float,
) -> dict[str, Any]:
    return {
        "self_ref": f"#/texts/{index}",
        "label": label,
        "text": value,
        "prov": _prov(10, top, 290, top + 20),
    }


def _table() -> dict[str, Any]:
    cells = []
    rows = [
        ["Item", "Value"],
        ["Alpha", "10"],
        ["Wrapped label remains complete", "20"],
    ]
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            cells.append(
                {
                    "start_row_offset_idx": row,
                    "end_row_offset_idx": row + 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": value,
                    "column_header": row == 0,
                    "row_header": False,
                    "row_section": False,
                    "bbox": {
                        "l": 10 + column * 140,
                        "t": 120 + row * 24,
                        "r": 150 + column * 140,
                        "b": 144 + row * 24,
                        "coord_origin": "TOPLEFT",
                    },
                }
            )
    return {
        "self_ref": "#/tables/0",
        "label": "table",
        "prov": _prov(10, 120, 290, 192),
        "data": {
            "num_rows": 3,
            "num_cols": 2,
            "table_cells": cells,
        },
    }


def _image_region() -> ImageRegion:
    lines = [
        OCRLine(
            text="Quarterly Summary",
            bbox={"x": 10, "y": 10, "w": 220, "h": 20},
            confidence=0.96,
            word_count=2,
        ),
        OCRLine(
            text="First paragraph remains complete.",
            bbox={"x": 10, "y": 45, "w": 260, "h": 18},
            confidence=0.91,
            word_count=4,
        ),
        OCRLine(
            text="Consent accepted",
            bbox={"x": 10, "y": 80, "w": 160, "h": 18},
            confidence=0.93,
            word_count=2,
        ),
        OCRLine(
            text="Item Value Alpha 10 Wrapped label remains complete 20",
            bbox={"x": 10, "y": 120, "w": 280, "h": 72},
            confidence=0.9,
            word_count=10,
        ),
        OCRLine(
            text="Revenue by region North 40 South 60",
            bbox={"x": 10, "y": 215, "w": 280, "h": 55},
            confidence=0.88,
            word_count=7,
        ),
        OCRLine(
            text="Start Review Complete",
            bbox={"x": 10, "y": 285, "w": 280, "h": 55},
            confidence=0.86,
            word_count=3,
        ),
    ]
    return ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 300, "h": 360},
        pixel_width=300,
        pixel_height=360,
        area_ratio=1.0,
        text="\n".join(line.text for line in lines),
        lines=lines,
        confidence=0.91,
        content_type="page_image",
        metadata={"frame_index": 0},
    )


def _raw_docling() -> dict[str, Any]:
    title = _text(0, "section_header", "Quarterly Summary", top=10)
    paragraph = _text(
        1,
        "text",
        "First paragraph remains complete.",
        top=45,
    )
    checkbox = _text(
        2,
        "checkbox_selected",
        "Consent accepted",
        top=80,
    )
    chart_caption = _text(3, "caption", "Revenue by region", top=210)
    diagram_caption = _text(4, "caption", "Review workflow", top=280)
    chart = {
        "self_ref": "#/pictures/0",
        "label": "picture",
        "prov": _prov(10, 210, 290, 275),
        "captions": [{"$ref": "#/texts/3"}],
        "annotations": [{"kind": "layout", "label": "chart"}],
        "meta": {
            "classification": {
                "predictions": [
                    {"class_name": "bar_chart", "confidence": 0.97}
                ]
            }
        },
    }
    diagram = {
        "self_ref": "#/pictures/1",
        "label": "picture",
        "prov": _prov(10, 280, 290, 345),
        "captions": [{"$ref": "#/texts/4"}],
        "meta": {
            "classification": {
                "predictions": [
                    {"class_name": "flow_chart", "confidence": 0.94}
                ]
            }
        },
    }
    return {
        "texts": [
            title,
            paragraph,
            checkbox,
            chart_caption,
            diagram_caption,
        ],
        "tables": [_table()],
        "pictures": [chart, diagram],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/texts/2"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/pictures/0"},
                {"$ref": "#/pictures/1"},
            ]
        },
    }


def test_image_docling_options_enable_classifier_without_runtime_compilation() -> None:
    image_options = pipeline._docling_pipeline_options(
        ("eng",),
        "tesseract",
        None,
        None,
        30.0,
        classify_pictures=True,
    )
    pdf_options = pipeline._docling_pipeline_options(
        ("eng",),
        "tesseract",
        None,
        None,
        30.0,
    )

    assert image_options.do_picture_classification is True
    assert (
        image_options.picture_classification_options.engine_options.compile_model
        is False
    )
    assert pdf_options.do_picture_classification is False


def test_image_conversion_skips_missing_optional_classifier_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from docling.datamodel.base_models import ConversionStatus

    classifier_settings: list[bool] = []

    class StubDocument:
        def export_to_dict(self, **_kwargs: Any) -> dict[str, Any]:
            return {"texts": [], "tables": [], "pictures": []}

    class StubConverter:
        def convert(self, *_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(
                status=ConversionStatus.SUCCESS,
                errors=[],
                document=StubDocument(),
            )

    def image_converter(
        _languages: tuple[str, ...],
        _tesseract_cmd: str,
        _tesseract_data_path: str | None,
        _artifacts_path: str | None,
        _timeout_seconds: float,
        classify_pictures: bool,
    ) -> tuple[StubConverter, Any]:
        classifier_settings.append(classify_pictures)
        return StubConverter(), nullcontext()

    monkeypatch.setattr(
        pipeline,
        "_image_converter_and_lock",
        image_converter,
    )

    raw, warnings = pipeline._convert_with_docling(
        b"valid normalized image",
        "scan.normalized.png",
        Settings(docling_artifacts_path=str(tmp_path)),
        input_kind=InputKind.IMAGE,
    )

    assert classifier_settings == [False]
    assert raw == {"texts": [], "tables": [], "pictures": []}
    assert warnings == [
        "Picture classification was skipped because its model is unavailable "
        "in the configured local Docling artifacts."
    ]


def test_picture_classifier_stays_enabled_when_model_is_available(
    tmp_path,
) -> None:
    from docling.datamodel.picture_classification_options import (
        DocumentPictureClassifierOptions,
    )

    options = DocumentPictureClassifierOptions.from_preset(
        "document_figure_classifier_v2"
    )
    (tmp_path / options.repo_cache_folder).mkdir()

    assert pipeline._picture_classifier_model_available(None) is True
    assert (
        pipeline._picture_classifier_model_available(str(tmp_path))
        is True
    )


def test_sparse_ocr_adds_isolated_values_without_repeating_labels() -> None:
    primary = [
        OCRLine(
            text="North South West",
            bbox={"x": 10, "y": 100, "w": 300, "h": 20},
            confidence=0.9,
            word_count=3,
        )
    ]
    sparse = [
        OCRLine(
            text="40",
            bbox={"x": 80, "y": 50, "w": 25, "h": 18},
            confidence=0.88,
            word_count=1,
        ),
        OCRLine(
            text="North",
            bbox={"x": 10, "y": 100, "w": 80, "h": 20},
            confidence=0.91,
            word_count=1,
        ),
    ]

    merged = _merge_sparse_ocr_lines(primary, sparse)

    assert [line.text for line in merged] == ["40", "North South West"]


def test_image_checkbox_cleanup_removes_repeated_visual_markers() -> None:
    pages = [
        {
            "items": [
                {
                    "label": "checkbox_unselected",
                    "value": "[ ] [] Needs follow-up",
                    "md": "[ ] [] Needs follow-up",
                },
                {
                    "label": "checkbox_selected",
                    "value": "[x] [X] Reviewed",
                    "md": "[x] [X] Reviewed",
                },
            ]
        }
    ]

    pipeline._clean_image_checkbox_markers(pages)

    assert [item["value"] for item in pages[0]["items"]] == [
        "[ ] Needs follow-up",
        "[x] Reviewed",
    ]


@pytest.fixture()
def loaded_image() -> LoadedDocument:
    page = SourcePage(
        page_index=1,
        pixel_width=300,
        pixel_height=360,
        png_bytes=b"normalized png",
        original_orientation=6,
        orientation_applied=True,
    )
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"original image",
        processing_bytes=b"normalized image",
        original_filename="scan.jpg",
        processing_filename="scan.normalized.png",
        mime_type="image/jpeg",
        source_format="JPEG",
        pages=(page,),
    )


def test_image_uses_shared_layout_table_and_markdown_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    loaded_image: LoadedDocument,
) -> None:
    region = _image_region()
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (_raw_docling(), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [region]},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: pytest.fail(
            "PDF vector extraction must not run for an image"
        ),
    )

    result = pipeline._parse_loaded_document(
        loaded_image,
        Settings(),
    ).model_dump(mode="json")

    assert result["document"]["mime_type"] == "image/jpeg"
    assert result["document"]["page_count"] == 1
    assert result["document"]["orientation_corrected_pages"] == [1]
    page = result["pages"][0]
    assert page["page_index"] == page["page_number"] == 1
    assert page["unit"] == "px"
    assert page["page_width"] == 300
    assert page["page_height"] == 360
    assert page["image_metadata"]["orientation_applied"] is True
    assert [item["reading_order"] for item in page["items"]] == list(
        range(len(page["items"]))
    )
    assert len({item["id"] for item in page["items"]}) == len(page["items"])

    heading = next(item for item in page["items"] if item["type"] == "heading")
    paragraph = next(
        item
        for item in page["items"]
        if item.get("value") == "First paragraph remains complete."
    )
    checkbox = next(
        item
        for item in page["items"]
        if item.get("value") == "[x] Consent accepted"
    )
    assert heading["source"] == paragraph["source"] == checkbox["source"] == "ocr"
    assert heading["confidence"] == 0.96
    assert heading["bbox"]["unit"] == "px"

    table = next(item for item in page["items"] if item["type"] == "table")
    assert table["rows"] == [
        ["Item", "Value"],
        ["Alpha", "10"],
        ["Wrapped label remains complete", "20"],
    ]
    assert len(table["cells"]) == 6
    assert table["row_count"] == 3
    assert table["column_count"] == 2
    assert "<thead>" in table["html"]
    assert "<tbody>" in table["html"]
    assert table["md"] == table["html"]
    assert table["csv"].splitlines()[-1] == (
        "Wrapped label remains complete,20"
    )
    assert table["source"] == "ocr"
    assert all(cell["source"] == "ocr" for cell in table["cells"])
    assert all(cell["bbox"]["unit"] == "px" for cell in table["cells"])

    chart = next(item for item in page["items"] if item["type"] == "chart")
    assert "North 40 South 60" in chart["ocr_text"]
    assert chart["caption"] == "Revenue by region"
    assert chart["parse_concerns"] == ["chart_values_not_structured"]
    assert "series" not in chart
    assert "visible_values" not in chart
    assert chart["annotations"] == [{"kind": "layout", "label": "chart"}]
    assert chart["classification"] == {
        "class_name": "bar_chart",
        "confidence": 0.97,
    }

    diagram = next(item for item in page["items"] if item["type"] == "diagram")
    assert "Start Review Complete" in diagram["ocr_text"]
    assert diagram["parse_concerns"] == [
        "diagram_relationships_not_structured"
    ]
    assert "relationships" not in diagram
    assert "connectors" not in diagram
    assert diagram["classification"] == {
        "class_name": "flow_chart",
        "confidence": 0.94,
    }

    assert len(page["detected_images"]) == 1
    assert page["detected_images"][0]["content_type"] == "page_image"
    assert not any(
        item["type"] == "image"
        and item.get("content_type") == "page_image"
        for item in page["items"]
    )

    markdown = to_markdown(result)
    assert markdown.index("# Quarterly Summary") < markdown.index(
        "First paragraph remains complete."
    )
    assert "Wrapped label remains complete" in markdown
    assert "North 40 South 60" in markdown
    assert "Start Review Complete" in markdown


def test_direct_image_stream_builds_one_flagged_canonical_presentation(
    monkeypatch: pytest.MonkeyPatch,
    loaded_image: LoadedDocument,
) -> None:
    region = _image_region()
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (_raw_docling(), []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_raster_ocr",
        lambda *_args, **_kwargs: {1: [region]},
    )
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: pytest.fail(
            "PDF vector extraction must not run for an image"
        ),
    )

    result = pipeline._parse_loaded_document(
        loaded_image,
        Settings(
            shared_ir_enabled=True,
            shared_ir_normalization_enabled=True,
            canonical_serialization_enabled=True,
        ),
    )
    payload = result.model_dump(mode="json")
    canonical = CanonicalPresentation.model_validate(
        payload["canonical_presentation"]
    )
    blocks = [
        block
        for page in canonical.pages
        for block in page.blocks
        if block.omission_reason is None
    ]
    by_type = {
        block.primary_element_type: block
        for block in blocks
        if block.primary_element_type in {"table", "chart", "diagram"}
    }

    assert set(by_type) == {"table", "chart", "diagram"}
    assert by_type["table"].markdown.startswith("<table>")
    assert by_type["chart"].markdown == "Revenue by region"
    assert by_type["diagram"].markdown == "Review workflow"
    assert "North 40 South 60" not in by_type["chart"].markdown
    assert "Start Review Complete" not in by_type["diagram"].markdown
    contributions = [
        element_id
        for block in blocks
        for element_id in block.contributing_element_ids
    ]
    assert len(contributions) == len(set(contributions))
    assert to_markdown(result) == canonical.full.markdown


def test_uncertain_visuals_preserve_ocr_without_inventing_structure() -> None:
    region = _image_region()
    raw = _raw_docling()

    body, tables = pipeline._normalize_docling_body(
        raw,
        {1: 360.0},
        [""],
        {1: [region]},
        preserve_visual_items=True,
    )

    assert len(tables[1]) == 1
    chart = next(item for item in body[1] if item["type"] == "chart")
    diagram = next(item for item in body[1] if item["type"] == "diagram")
    assert chart["confidence"] == 0.88
    assert diagram["confidence"] == 0.86
    assert "relationships" not in diagram
    assert "series" not in chart


def test_raster_ocr_recovers_only_lines_missing_from_structured_items() -> None:
    represented = {
        "type": "text",
        "value": "Subject ID: 1190014",
        "bbox": pipeline._bbox(10, 20, 260, 20),
        "source": "ocr",
        "confidence": 0.95,
    }
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 300, "h": 200},
        pixel_width=300,
        pixel_height=200,
        area_ratio=1.0,
        lines=[
            OCRLine(
                text="Subject ID: 1190014",
                bbox={"x": 10, "y": 20, "w": 260, "h": 20},
                confidence=0.95,
                word_count=3,
            ),
            OCRLine(
                text="Oral",
                bbox={"x": 180, "y": 80, "w": 50, "h": 20},
                confidence=0.91,
                word_count=1,
            ),
        ],
    )
    body = {1: [represented]}

    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {},
        {1: [region]},
    )

    assert [item["value"] for item in body[1]] == [
        "Subject ID: 1190014",
        "Oral",
    ]
    assert body[1][-1]["source"] == "ocr"
    assert body[1][-1]["confidence"] == 0.91
    assert body[1][-1]["parse_concerns"] == [
        "layout_omission_recovered_by_ocr"
    ]


def test_image_form_graph_preserves_cells_links_and_explicit_fields() -> None:
    form = {
        "self_ref": "#/form_items/0",
        "label": "form",
        "prov": _prov(10, 20, 290, 120),
        "graph": {
            "cells": [
                {
                    "cell_id": 1,
                    "label": "key",
                    "text": "Subject ID",
                    "orig": "Subject ID",
                    "prov": _prov(10, 30, 110, 50),
                },
                {
                    "cell_id": 2,
                    "label": "value",
                    "text": "1190014",
                    "orig": "1190014",
                    "prov": _prov(130, 30, 220, 50),
                },
                {
                    "cell_id": 3,
                    "label": "checkbox",
                    "text": "Reviewed",
                    "orig": "☒ Reviewed",
                    "prov": _prov(10, 70, 130, 90),
                },
            ],
            "links": [
                {
                    "label": "to_value",
                    "source_cell_id": 1,
                    "target_cell_id": 2,
                }
            ],
        },
    }
    raw = {
        "texts": [],
        "tables": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [form],
        "body": {"children": [{"$ref": "#/form_items/0"}]},
    }

    body, tables = pipeline._normalize_docling_body(
        raw,
        {1: 200.0},
        [""],
        {},
        preserve_graph_items=True,
    )

    assert not tables
    assert len(body[1]) == 1
    item = body[1][0]
    assert item["type"] == "form"
    assert item["fields"] == [
        {
            "key": "Subject ID",
            "value": "1190014",
            "key_cell_id": 1,
            "value_cell_id": 2,
            "relation": "to_value",
        }
    ]
    assert item["links"] == [
        {
            "label": "to_value",
            "source_cell_id": 1,
            "target_cell_id": 2,
        }
    ]
    assert [cell["label"] for cell in item["cells"]] == [
        "key",
        "value",
        "checkbox",
    ]
    assert "**Subject ID:** 1190014" in item["md"]
    assert "Reviewed" in item["md"]


def test_low_confidence_picture_classification_remains_an_image() -> None:
    raw = {
        "texts": [],
        "tables": [],
        "pictures": [
            {
                "self_ref": "#/pictures/0",
                "label": "picture",
                "prov": _prov(10, 20, 290, 160),
                "meta": {
                    "classification": {
                        "predictions": [
                            {
                                "class_name": "bar_chart",
                                "confidence": 0.42,
                            }
                        ]
                    }
                },
            }
        ],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": "#/pictures/0"}]},
    }

    body, _tables = pipeline._normalize_docling_body(
        raw,
        {1: 200.0},
        [""],
        {},
        preserve_visual_items=True,
    )

    item = body[1][0]
    assert item["type"] == "image"
    assert item["classification"]["class_name"] == "bar_chart"
    assert item["md"] == "[Image detected; no reliable text extracted.]"
    assert not item["detected_text"]


def test_full_page_raster_is_cataloged_without_becoming_a_table_row() -> None:
    page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "page_width": 300.0,
        "page_height": 200.0,
        "unit": "px",
        "success": True,
        "items": [],
        "warnings": [],
    }
    table = {
        "type": "table",
        "rows": [["A"]],
        "cells": [],
        "row_count": 1,
        "column_count": 1,
        "value": [["A"]],
        "md": "<table><tr><td>A</td></tr></table>",
        "html": "<table><tr><td>A</td></tr></table>",
        "csv": "A",
        "bbox": pipeline._bbox(40, 40, 220, 120),
        "source": "ocr",
        "confidence": 0.9,
    }
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 300, "h": 200},
        pixel_width=300,
        pixel_height=200,
        area_ratio=1.0,
        text="A",
        lines=[],
        confidence=0.9,
        content_type="page_image",
    )

    pipeline._merge_body_items(
        [page],
        {},
        {1: [table]},
        {1: [region]},
        {},
        {},
    )

    emitted_table = next(item for item in page["items"] if item["type"] == "table")
    assert emitted_table["rows"] == [["A"]]
    assert len(page["detected_images"]) == 1
    assert len(page["items"]) == 1


def test_near_identical_footer_uses_confident_full_page_ocr_once() -> None:
    footer = {
        "type": "footer",
        "value": "RECOVERY_TOKEN_Z9Q/",
        "md": "RECOVERY_TOKEN_Z9Q/",
        "bbox": pipeline._bbox(100, 170, 180, 20),
        "source": "ocr",
        "confidence": None,
        "items": [{"value": "RECOVERY_TOKEN_Z9Q/"}],
    }
    line = OCRLine(
        text="RECOVERY_TOKEN_Z9Q7",
        bbox={"x": 100, "y": 170, "w": 180, "h": 20},
        confidence=0.92,
        word_count=1,
    )
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0, "y": 0, "w": 300, "h": 200},
        pixel_width=300,
        pixel_height=200,
        area_ratio=1.0,
        lines=[line],
        content_type="page_image",
    )
    footers = {1: footer}

    pipeline._reconcile_image_decorations({}, footers, {1: [region]})
    body: dict[int, list[dict[str, Any]]] = {1: []}
    pipeline._supplement_unrepresented_raster_ocr(
        body,
        {},
        {1: [region]},
        {1: [footer]},
    )

    assert footer["value"] == "RECOVERY_TOKEN_Z9Q7"
    assert footer["layout_value"] == "RECOVERY_TOKEN_Z9Q/"
    assert footer["confidence"] == 0.92
    assert footer["parse_concerns"] == [
        "layout_text_corrected_by_full_page_ocr"
    ]
    assert not body[1]
    assert to_markdown({"pages": [{"items": [footer]}]}) == (
        "RECOVERY_TOKEN_Z9Q7\n"
    )


def test_pdf_default_keeps_prior_behavior_and_does_not_add_graph_items() -> None:
    raw = {
        "texts": [],
        "tables": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [
            {
                "self_ref": "#/key_value_items/0",
                "label": "key_value_region",
                "graph": {"cells": [], "links": []},
            }
        ],
        "form_items": [],
        "body": {"children": [{"$ref": "#/key_value_items/0"}]},
    }

    body, _tables = pipeline._normalize_docling_body(
        raw,
        {1: 200.0},
        [""],
        {},
    )

    assert not body
