from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import math

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.config import Settings
from app.services import ocr as ocr_module
from app.services.ocr import (
    PDF_RENDER_CROP_PADDING_POINTS,
    ImageRegion,
    PdfRegionRequest,
    _build_lines,
    _render_region_png,
)
from app.services.selective_span_ocr import (
    MAX_SELECTIVE_CANDIDATES_PER_CROP,
    MAX_SELECTIVE_CONCERNS,
    MAX_SELECTIVE_CROP_PIXELS,
    MAX_SELECTIVE_CROP_SECONDS,
    MAX_SELECTIVE_DOCUMENT_PIXELS,
    MAX_SELECTIVE_DOCUMENT_SECONDS,
    MAX_SELECTIVE_DOCUMENT_TARGETS,
    MAX_SELECTIVE_PAGE_AREA_RATIO,
    MAX_SELECTIVE_PAGE_TARGETS,
    MAX_SELECTIVE_TOKENS_PER_CROP,
    SELECTIVE_DPI,
    SELECTIVE_PADDING_POINTS,
    SELECTIVE_RENDER_SCALE,
)


def _blank_pdf(width: float, height: float) -> bytes:
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            f"{width} {height}] >>"
        ).encode("ascii"),
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, payload in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def _selective_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "text_integrity_font_audit_enabled": True,
        "text_integrity_font_recovery_enabled": True,
        "pdf_visual_analysis_enabled": True,
        "text_integrity_selective_span_ocr_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_selective_span_ocr_flag_defaults_off_and_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().text_integrity_selective_span_ocr_enabled is False

    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("PDF_VISUAL_ANALYSIS_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED",
        "true",
    )

    assert Settings.from_env().text_integrity_selective_span_ocr_enabled is True


@pytest.mark.parametrize(
    "disabled_dependencies",
    (
        {
            "shared_ir_enabled": False,
            "shared_ir_normalization_enabled": False,
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
        },
        {
            "shared_ir_normalization_enabled": False,
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
        },
        {
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
        },
        {"text_integrity_font_recovery_enabled": False},
        {"pdf_visual_analysis_enabled": False},
    ),
)
def test_selective_span_ocr_requires_every_policy_dependency(
    disabled_dependencies: dict[str, bool],
) -> None:
    enabled = _selective_settings()

    with pytest.raises(ValueError, match="SELECTIVE_SPAN_OCR_ENABLED requires"):
        replace(enabled, **disabled_dependencies)


def test_direct_raster_and_pdf_crop_lines_share_typed_evidence_schema() -> None:
    tsv = "\n".join(
        (
            (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext"
            ),
            "5\t1\t1\t1\t1\t1\t10\t5\t30\t8\t93\tBroken",
            "5\t1\t1\t1\t1\t2\t44\t5\t20\t8\t87\ttext",
        )
    )
    direct = _build_lines(
        tsv,
        crop_bounds=(0.0, 0.0, 100.0, 50.0),
        scale=1.0,
        page_width=100.0,
        page_height=50.0,
        ocr_pass="standard",
    )[0].to_evidence_dict()
    pdf_crop = _build_lines(
        tsv,
        crop_bounds=(72.0, 680.0, 172.0, 730.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
        ocr_pass="standard",
    )[0].to_evidence_dict()

    expected_line_keys = {
        "text",
        "bbox",
        "confidence",
        "word_count",
        "ocr_pass",
        "tokens",
    }
    expected_token_keys = {
        "text",
        "bbox",
        "crop_pixel_bbox",
        "confidence",
        "ocr_pass",
        "word_index",
    }
    assert set(direct) == set(pdf_crop) == expected_line_keys
    assert [set(token) for token in direct["tokens"]] == [
        expected_token_keys,
        expected_token_keys,
    ]
    assert [set(token) for token in pdf_crop["tokens"]] == [
        expected_token_keys,
        expected_token_keys,
    ]
    assert direct["text"] == pdf_crop["text"] == "Broken text"
    assert direct["ocr_pass"] == pdf_crop["ocr_pass"] == "standard"
    assert [token["text"] for token in direct["tokens"]] == [
        "Broken",
        "text",
    ]
    assert direct["tokens"][0]["crop_pixel_bbox"] == (
        pdf_crop["tokens"][0]["crop_pixel_bbox"]
    )
    assert direct["tokens"][0]["bbox"] != pdf_crop["tokens"][0]["bbox"]


def test_typed_token_evidence_does_not_change_legacy_image_region_schema() -> None:
    tsv = "\n".join(
        (
            (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext"
            ),
            "5\t1\t1\t1\t1\t1\t10\t5\t30\t8\t93\tNative",
        )
    )
    line = _build_lines(
        tsv,
        crop_bounds=(0.0, 0.0, 100.0, 50.0),
        scale=1.0,
        page_width=100.0,
        page_height=50.0,
    )[0]
    region = ImageRegion(
        page_index=1,
        object_index=0,
        bbox={"x": 0.0, "y": 0.0, "w": 100.0, "h": 50.0},
        pixel_width=100,
        pixel_height=50,
        area_ratio=1.0,
        lines=[line],
        render_pixel_width=99,
        render_pixel_height=49,
        rendered_crop_bbox={
            "x": 0.1,
            "y": 0.1,
            "w": 99.0,
            "h": 49.0,
        },
        rendered_page_size=(100.0, 50.0),
        pixel_to_page_transform=(1.0, 0.0, 0.0, 1.0, 0.1, 0.1),
    )

    assert set(line.to_dict()) == {
        "text",
        "bbox",
        "confidence",
        "word_count",
    }
    assert set(region.to_dict()["lines"][0]) == {
        "text",
        "bbox",
        "confidence",
        "word_count",
    }
    assert "ocr_pass" not in region.to_dict()["lines"][0]
    assert "tokens" not in region.to_dict()["lines"][0]
    assert "render_pixel_width" not in region.to_dict()
    assert "rendered_crop_bbox" not in region.to_dict()
    assert "pixel_to_page_transform" not in region.to_dict()


def test_pdfium_fractional_page_and_crop_use_realized_raster_affine() -> None:
    page_width = 612.37
    page_height = 792.29
    source_bounds = (72.123, 55.969, 159.789, 76.747)
    document = pdfium.PdfDocument(_blank_pdf(page_width, page_height))
    page = document[0]
    try:
        (
            png_bytes,
            crop_bounds,
            scale,
            actual_dimensions,
            pixel_to_page,
        ) = _render_region_png(
            page,
            page_width,
            page_height,
            source_bounds,
            target_scale=5.0,
            max_pixels=4_000_000,
        )
    finally:
        page.close()
        document.close()

    with Image.open(BytesIO(png_bytes)) as image:
        assert image.size == actual_dimensions

    page_pixel_width = math.ceil(page_width * scale)
    page_pixel_height = math.ceil(page_height * scale)
    expected_x_factor = page_width / page_pixel_width
    expected_y_factor = page_height / page_pixel_height
    expected_left_pixels = math.ceil(crop_bounds[0] * scale)
    expected_top_pixels = math.ceil(
        (page_height - crop_bounds[3]) * scale
    )
    assert pixel_to_page == pytest.approx(
        (
            expected_x_factor,
            0.0,
            0.0,
            expected_y_factor,
            expected_left_pixels * expected_x_factor,
            expected_top_pixels * expected_y_factor,
        ),
        abs=1e-12,
    )
    assert pixel_to_page[0] != pytest.approx(1.0 / scale, abs=1e-8)
    assert pixel_to_page[3] != pytest.approx(1.0 / scale, abs=1e-8)

    tsv = "\n".join(
        (
            (
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext"
            ),
            "5\t1\t1\t1\t1\t1\t10\t5\t30\t8\t93\tFractional",
        )
    )
    line = _build_lines(
        tsv,
        crop_bounds=crop_bounds,
        scale=scale,
        page_width=page_width,
        page_height=page_height,
        pixel_to_page_transform=pixel_to_page,
    )[0]
    assert line.bbox["x"] == pytest.approx(
        pixel_to_page[4] + 10 * pixel_to_page[0],
        abs=0.001,
    )
    assert line.bbox["y"] == pytest.approx(
        pixel_to_page[5] + 5 * pixel_to_page[3],
        abs=0.001,
    )


def test_quantized_render_pixel_bound_is_checked_before_pdfium_allocation() -> None:
    class _PageThatMustNotRender:
        def render(self, **_kwargs: Any) -> None:
            raise AssertionError("PDFium allocation must not start")

    with pytest.raises(
        RuntimeError,
        match="Quantized PDF render exceeds",
    ):
        _render_region_png(
            _PageThatMustNotRender(),
            3.0,
            3.0,
            (0.0, 0.0, 3.0, 3.0),
            target_scale=5.0,
            max_pixels=2,
        )


def test_exact_affine_is_private_to_selective_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    def observe(*_args: object, **kwargs: object):
        captured.append(kwargs.get("pixel_to_page_transform"))
        return [], [], []

    monkeypatch.setattr(
        ocr_module,
        "_resolve_tesseract",
        lambda _command: "/test/tesseract",
    )
    monkeypatch.setattr(ocr_module, "_ocr_png_lines", observe)
    source_bbox = {
        "x": 72.123,
        "y": 55.969,
        "width": 87.666,
        "height": 20.778,
    }
    regions = ocr_module.extract_rendered_pdf_ocr(
        _blank_pdf(612.37, 792.29),
        [
            PdfRegionRequest(page_index=1, bbox=source_bbox),
            PdfRegionRequest(
                page_index=1,
                bbox=source_bbox,
                metadata={"selective_span_id": "span-test"},
            ),
        ],
        tesseract_cmd="test",
    )[1]

    assert captured[0] is None
    assert captured[1] == regions[1].pixel_to_page_transform
    assert regions[0].to_dict()["pixel_width"] == regions[1].to_dict()[
        "pixel_width"
    ]
    assert "pixel_to_page_transform" not in regions[0].to_dict()


def test_selective_ocr_resource_contract_matches_the_accepted_policy() -> None:
    assert SELECTIVE_RENDER_SCALE == 5.0
    assert SELECTIVE_DPI == 360.0
    assert SELECTIVE_PADDING_POINTS == 3.0
    assert SELECTIVE_PADDING_POINTS == PDF_RENDER_CROP_PADDING_POINTS
    assert MAX_SELECTIVE_CROP_PIXELS == 4_000_000
    assert MAX_SELECTIVE_PAGE_TARGETS == 16
    assert MAX_SELECTIVE_DOCUMENT_TARGETS == 64
    assert MAX_SELECTIVE_DOCUMENT_PIXELS == 32_000_000
    assert MAX_SELECTIVE_PAGE_AREA_RATIO == 0.05
    assert MAX_SELECTIVE_CROP_SECONDS == 30.0
    assert MAX_SELECTIVE_DOCUMENT_SECONDS == 60.0
    assert MAX_SELECTIVE_CANDIDATES_PER_CROP == 256
    assert MAX_SELECTIVE_TOKENS_PER_CROP == 2_048
    assert MAX_SELECTIVE_CONCERNS == 256
