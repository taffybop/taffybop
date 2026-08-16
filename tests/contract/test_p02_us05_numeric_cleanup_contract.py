from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.config import Settings
from app.services import ocr as ocr_module
from app.services import pipeline
from app.services.ocr import (
    ImageRegion,
    PdfRegionRequest,
    _build_lines,
)
from app.services.input_documents import (
    InputKind,
    LoadedDocument,
    SourcePage,
)
from app.services.selective_span_ocr import run_selective_span_ocr
from tests.benchmarks.numeric_cleanup_metrics import (
    OBSERVED_YEAR_LINE,
    OBSERVED_YEAR_TOKENS,
)
from tests.stories.phase_02.test_p02_us03_selective_span_ocr import (
    _refused_case,
    _render_factory,
)


def _blank_pdf(width: float = 100.0, height: float = 100.0) -> bytes:
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


def _tsv(words: tuple[str, ...]) -> str:
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext"
    )
    rows = [header]
    for index, word in enumerate(words, 1):
        rows.append(
            "5\t1\t1\t1\t1\t"
            f"{index}\t{10 + 30 * index}\t10\t24\t10\t95\t{word}"
        )
    return "\n".join(rows)


def _fake_render(
    _page: Any,
    _page_width: float,
    _page_height: float,
    _bounds: tuple[float, float, float, float],
    *,
    target_scale: float,
    max_pixels: int,
) -> tuple[
    bytes,
    tuple[float, float, float, float],
    float,
    tuple[int, int],
    tuple[float, float, float, float, float, float],
]:
    assert target_scale > 0
    assert max_pixels > 0
    return (
        b"png",
        (0.0, 0.0, 20.0, 20.0),
        1.0,
        (20, 20),
        (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    )


def _strict_legacy_ocr_png_lines(
    _executable: str,
    _png_bytes: bytes,
    _languages: tuple[str, ...],
    _timeout_seconds: float,
    _tessdata_path: str | None,
    *,
    crop_bounds: tuple[float, float, float, float],
    scale: float,
    page_width: float,
    page_height: float,
    pixel_to_page_transform: tuple[
        float,
        float,
        float,
        float,
        float,
        float,
    ]
    | None = None,
    raster_width: int | None = None,
    raster_height: int | None = None,
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    assert crop_bounds
    assert scale > 0
    assert page_width > 0
    assert page_height > 0
    del pixel_to_page_transform, raster_width, raster_height
    return [], [], []


def test_numeric_cleanup_flag_defaults_off_and_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().ocr_numeric_cleanup_v2_enabled is False

    monkeypatch.setenv(
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        "true",
    )

    assert Settings.from_env().ocr_numeric_cleanup_v2_enabled is True


def test_numeric_cleanup_flag_rejects_invalid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        "sometimes",
    )

    with pytest.raises(
        ValueError,
        match="PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
    ):
        Settings.from_env()


def test_numeric_cleanup_has_no_shared_ir_or_font_dependency() -> None:
    settings = Settings(ocr_numeric_cleanup_v2_enabled=True)

    assert settings.ocr_numeric_cleanup_v2_enabled is True
    assert settings.shared_ir_enabled is False
    assert settings.shared_ir_normalization_enabled is False
    assert settings.text_integrity_font_audit_enabled is False
    assert settings.text_integrity_font_recovery_enabled is False
    assert settings.text_integrity_selective_span_ocr_enabled is False
    assert settings.text_reconciliation_enabled is False
    assert replace(
        settings,
        ocr_numeric_cleanup_v2_enabled=False,
    ).ocr_numeric_cleanup_v2_enabled is False


def test_numeric_cleanup_resource_contract_matches_accepted_policy() -> None:
    assert ocr_module.MAX_NUMERIC_CLEANUP_LINE_CHARS == 65_536
    assert ocr_module.MAX_NUMERIC_CLEANUP_TOKENS == 4_096
    assert ocr_module.MAX_SPLIT_HEX_FRAGMENTS == 64
    assert ocr_module.MAX_SPLIT_HEX_CHARS == 128
    assert ocr_module._MAX_OCR_TSV_BYTES == 8 * 1024 * 1024
    assert ocr_module._MAX_OCR_TSV_WORDS == 100_000


def test_numeric_cleanup_does_not_change_ocr_diagnostic_schema() -> None:
    disabled = _build_lines(
        _tsv(OBSERVED_YEAR_TOKENS),
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
    )[0]
    enabled = _build_lines(
        _tsv(OBSERVED_YEAR_TOKENS),
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
        numeric_cleanup_v2_enabled=True,
    )[0]
    disabled_public = disabled.to_dict()
    enabled_public = enabled.to_dict()
    disabled_evidence = disabled.to_evidence_dict()
    enabled_evidence = enabled.to_evidence_dict()

    assert set(disabled_public) == set(enabled_public) == {
        "text",
        "bbox",
        "confidence",
        "word_count",
    }
    assert set(disabled_evidence) == set(enabled_evidence) == {
        "text",
        "bbox",
        "confidence",
        "word_count",
        "ocr_pass",
        "tokens",
    }
    assert [set(token) for token in disabled_evidence["tokens"]] == [
        set(token) for token in enabled_evidence["tokens"]
    ]
    assert all(
        set(token)
        == {
            "text",
            "bbox",
            "crop_pixel_bbox",
            "confidence",
            "ocr_pass",
            "word_index",
        }
        for token in enabled_evidence["tokens"]
    )
    assert disabled.word_count == enabled.word_count == 12
    assert enabled.text == OBSERVED_YEAR_LINE
    assert "numeric_cleanup" not in str(enabled_evidence)


def test_direct_raster_adapter_propagates_flag_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = SimpleNamespace(
        page_index=1,
        pixel_width=10,
        pixel_height=10,
        png_bytes=b"png",
        original_orientation=None,
        orientation_applied=False,
    )
    monkeypatch.setattr(
        ocr_module,
        "_resolve_tesseract",
        lambda _command: "/tesseract",
    )
    monkeypatch.setattr(
        ocr_module,
        "_ocr_png_lines",
        _strict_legacy_ocr_png_lines,
    )

    disabled = ocr_module.extract_raster_ocr(
        [page],
        tesseract_cmd="test",
    )
    assert disabled[1][0].lines == []
    assert disabled[1][0].warnings == []

    observed: list[bool] = []

    def capture(*args: Any, **kwargs: Any):
        del args
        observed.append(kwargs.pop("numeric_cleanup_v2_enabled"))
        return _strict_legacy_ocr_png_lines(
            "",
            b"",
            (),
            1.0,
            None,
            **kwargs,
        )

    monkeypatch.setattr(ocr_module, "_ocr_png_lines", capture)
    enabled = ocr_module.extract_raster_ocr(
        [page],
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
    )

    assert enabled[1][0].warnings == []
    assert observed == [True]


def test_rendered_pdf_adapter_propagates_flag_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ocr_module,
        "_resolve_tesseract",
        lambda _command: "/tesseract",
    )
    monkeypatch.setattr(ocr_module, "_render_region_png", _fake_render)
    monkeypatch.setattr(
        ocr_module,
        "_ocr_png_lines",
        _strict_legacy_ocr_png_lines,
    )
    request = PdfRegionRequest(
        page_index=1,
        bbox={"x": 10.0, "y": 10.0, "w": 20.0, "h": 20.0},
    )

    disabled = ocr_module.extract_rendered_pdf_ocr(
        _blank_pdf(),
        [request],
        tesseract_cmd="test",
    )
    assert disabled[1][0].warnings == []

    observed: list[bool] = []

    def capture(*args: Any, **kwargs: Any):
        del args
        observed.append(kwargs.pop("numeric_cleanup_v2_enabled"))
        return _strict_legacy_ocr_png_lines(
            "",
            b"",
            (),
            1.0,
            None,
            **kwargs,
        )

    monkeypatch.setattr(ocr_module, "_ocr_png_lines", capture)
    enabled = ocr_module.extract_rendered_pdf_ocr(
        _blank_pdf(),
        [request],
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
    )

    assert enabled[1][0].warnings == []
    assert observed == [True]


def test_embedded_pdf_adapter_propagates_flag_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeImage:
        def get_bounds(self) -> tuple[float, float, float, float]:
            return 10.0, 10.0, 30.0, 30.0

        def get_metadata(self) -> Any:
            return SimpleNamespace(width=20, height=20)

    class FakePage:
        def get_size(self) -> tuple[float, float]:
            return 100.0, 100.0

        def get_objects(self, **_kwargs: Any) -> list[FakeImage]:
            return [FakeImage()]

        def close(self) -> None:
            pass

    class FakeDocument:
        def __init__(self, _pdf_bytes: bytes) -> None:
            self.page = FakePage()

        def __len__(self) -> int:
            return 1

        def __getitem__(self, _index: int) -> FakePage:
            return self.page

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        ocr_module.pdfium,
        "PdfDocument",
        FakeDocument,
    )
    monkeypatch.setattr(
        ocr_module,
        "_resolve_tesseract",
        lambda _command: "/tesseract",
    )
    monkeypatch.setattr(ocr_module, "_render_region_png", _fake_render)
    monkeypatch.setattr(
        ocr_module,
        "_ocr_png_lines",
        _strict_legacy_ocr_png_lines,
    )

    disabled = ocr_module.extract_image_ocr(
        b"pdf",
        tesseract_cmd="test",
    )
    assert disabled[1][0].warnings == []

    observed: list[bool] = []

    def capture(*args: Any, **kwargs: Any):
        del args
        observed.append(kwargs.pop("numeric_cleanup_v2_enabled"))
        return _strict_legacy_ocr_png_lines(
            "",
            b"",
            (),
            1.0,
            None,
            **kwargs,
        )

    monkeypatch.setattr(ocr_module, "_ocr_png_lines", capture)
    enabled = ocr_module.extract_image_ocr(
        b"pdf",
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
    )

    assert enabled[1][0].warnings == []
    assert observed == [True]


def test_selective_renderer_omits_disabled_keyword_and_propagates_true() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    disabled_calls: list[Any] = []
    enabled_calls: list[Any] = []

    disabled = run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        {1: (612.0, 792.0)},
        tesseract_cmd="test-tesseract-that-does-not-exist",
        render_function=_render_factory(calls=disabled_calls),
    )
    enabled = run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        {1: (612.0, 792.0)},
        tesseract_cmd="test-tesseract-that-does-not-exist",
        render_function=_render_factory(calls=enabled_calls),
        numeric_cleanup_v2_enabled=True,
    )

    assert disabled.status == enabled.status == "complete"
    assert len(disabled_calls) == len(enabled_calls) == 1
    disabled_kwargs = disabled_calls[0][1]
    enabled_kwargs = enabled_calls[0][1]
    assert "numeric_cleanup_v2_enabled" not in disabled_kwargs
    assert enabled_kwargs.pop("numeric_cleanup_v2_enabled") is True
    assert enabled_kwargs == disabled_kwargs
    assert set(disabled_kwargs) == {
        "tesseract_cmd",
        "languages",
        "timeout_seconds",
        "render_scale",
        "max_render_pixels",
        "tessdata_path",
    }


def _loaded_raster() -> LoadedDocument:
    page = SourcePage(
        page_index=1,
        pixel_width=20,
        pixel_height=20,
        png_bytes=b"png",
        original_orientation=None,
        orientation_applied=False,
    )
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=b"image",
        processing_bytes=b"image",
        original_filename="image.png",
        processing_filename="image.png",
        mime_type="image/png",
        source_format="PNG",
        pages=(page,),
    )


def _mock_minimal_raster_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    raster_ocr: Callable[..., dict[int, list[ImageRegion]]],
) -> None:
    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: ({"body": {"children": []}}, []),
    )
    monkeypatch.setattr(pipeline, "extract_raster_ocr", raster_ocr)
    monkeypatch.setattr(
        pipeline,
        "extract_vector_tables",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "_analyze_shared_pages",
        lambda _context: None,
    )


def test_pipeline_preserves_flag_off_raster_adapter_call_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []

    def strict_raster(
        pages: Any,
        tesseract_cmd: str = "tesseract",
        languages: tuple[str, ...] = ("eng",),
        timeout_seconds: float = 30.0,
        max_render_pixels: int = 16_000_000,
        tessdata_path: str | None = None,
    ) -> dict[int, list[ImageRegion]]:
        calls.append(
            (
                pages,
                tesseract_cmd,
                languages,
                timeout_seconds,
                max_render_pixels,
                tessdata_path,
            )
        )
        return {1: []}

    _mock_minimal_raster_pipeline(monkeypatch, strict_raster)

    pipeline._parse_loaded_document(_loaded_raster(), Settings())

    assert len(calls) == 1


def test_pipeline_propagates_numeric_cleanup_to_raster_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def capture(
        *_args: Any,
        **kwargs: Any,
    ) -> dict[int, list[ImageRegion]]:
        calls.append(kwargs)
        return {1: []}

    _mock_minimal_raster_pipeline(monkeypatch, capture)

    pipeline._parse_loaded_document(
        _loaded_raster(),
        Settings(ocr_numeric_cleanup_v2_enabled=True),
    )

    assert len(calls) == 1
    assert calls[0]["numeric_cleanup_v2_enabled"] is True
