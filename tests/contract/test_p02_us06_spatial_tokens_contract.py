from __future__ import annotations

import json
import re
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.config import Settings
from app.services import ocr as ocr_module
from app.services import pipeline
from app.services.input_documents import (
    InputKind,
    LoadedDocument,
    SourcePage,
)
from app.services.ir import build_document_ir
from app.services.ocr import ImageRegion, PdfRegionRequest
from app.services.pipeline import _image_item
from app.services.presentation import build_canonical_presentation
from app.services.selective_span_ocr import run_selective_span_ocr
from app.services.serializer import to_markdown
from app.services.spatial_tokens import (
    MAX_SPATIAL_OCCURRENCE_JSON_BYTES,
    MAX_SPATIAL_SHORT_ALTERNATIVES,
    MAX_SPATIAL_SOURCE_TOKENS,
    MAX_SPATIAL_TOKEN_OCCURRENCES,
    MAX_SPATIAL_TOKEN_TEXT_CHARS,
    SHORT_TOKEN_MIN_OWNER_CONTAINMENT,
    SPATIAL_TOKEN_OVERLAP_THRESHOLD,
    SPATIAL_TOKEN_SCHEMA_VERSION,
)
from tests.stories.phase_02.test_p02_us06_spatial_tokens import (
    _bbox,
    _line,
)
from tests.stories.phase_02.test_p02_us03_selective_span_ocr import (
    _refused_case,
    _render_factory,
)


def _spatial_settings() -> Settings:
    return Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
    )


def _chart_region(*, confidence: float = 0.4437) -> ImageRegion:
    return ImageRegion(
        page_index=1,
        object_index=8,
        bbox=_bbox(100.0, 0.0, 200.0, 100.0),
        pixel_width=1_000,
        pixel_height=500,
        area_ratio=0.25,
        text="iH",
        lines=[
            _line(
                "iH",
                _bbox(157.421, 20.0, 14.6, 5.8),
                confidence=confidence,
            )
        ],
        confidence=confidence,
        content_type="chart",
        region_role="content_region",
        region_origin="pdf_page_render",
        coordinate_unit="pt",
    )


def _document(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "spatial-token.png",
            "mime_type": "image/png",
            "sha256": "6" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [item],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "fixture",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def test_spatial_flag_defaults_off_loads_from_env_and_requires_numeric_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().ocr_spatial_token_preservation_enabled is False

    monkeypatch.setenv(
        "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
        "true",
    )
    monkeypatch.delenv(
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        raising=False,
    )
    with pytest.raises(
        ValueError,
        match="PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
    ):
        Settings.from_env()

    monkeypatch.setenv(
        "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED",
        "true",
    )
    loaded = Settings.from_env()

    assert loaded.ocr_numeric_cleanup_v2_enabled is True
    assert loaded.ocr_spatial_token_preservation_enabled is True
    assert loaded.shared_ir_enabled is False
    assert loaded.text_reconciliation_enabled is False


def test_spatial_flag_rejects_invalid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
        "sometimes",
    )

    with pytest.raises(
        ValueError,
        match="PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED",
    ):
        Settings.from_env()


def test_spatial_contract_constants_match_accepted_policy() -> None:
    assert SPATIAL_TOKEN_SCHEMA_VERSION == "1.0"
    assert SPATIAL_TOKEN_OVERLAP_THRESHOLD == 0.80
    assert SHORT_TOKEN_MIN_OWNER_CONTAINMENT == 0.95
    assert MAX_SPATIAL_SOURCE_TOKENS == 4_096
    assert MAX_SPATIAL_TOKEN_OCCURRENCES == 2_048
    assert MAX_SPATIAL_SHORT_ALTERNATIVES == 256
    assert MAX_SPATIAL_TOKEN_TEXT_CHARS == 256
    assert MAX_SPATIAL_OCCURRENCE_JSON_BYTES == 1_048_576


def test_enabled_occurrence_and_summary_schema_is_additive_and_bounded() -> (
    None
):
    item = _image_item(
        _chart_region(),
        _spatial_settings(),
        source_document_identity="sha256:catastrophe",
    )
    occurrence = item["ocr_token_occurrences"][0]
    summary = item["ocr_occurrence_summary"]

    required_occurrence_fields = {
        "occurrence_id",
        "line_occurrence_id",
        "text",
        "bbox",
        "crop_pixel_bbox",
        "confidence",
        "ocr_pass",
        "word_index",
        "selected",
        "primary_selected",
        "short_alternative",
        "retention_reason",
    }
    assert required_occurrence_fields <= set(occurrence)
    assert set(occurrence) <= required_occurrence_fields | {"duplicate_of"}
    assert occurrence.get("duplicate_of") is None
    assert re.fullmatch(r"ocr-token-[0-9a-f]{64}", occurrence["occurrence_id"])
    assert re.fullmatch(
        r"ocr-line-[0-9a-f]{64}",
        occurrence["line_occurrence_id"],
    )
    assert set(summary) == {
        "schema_version",
        "total_occurrences",
        "selected_occurrences",
        "primary_selected_occurrences",
        "duplicate_occurrences",
        "short_alternative_occurrences",
        "invalid_occurrences",
        "oversized_text_occurrences",
        "truncated_occurrences",
        "source_token_limit_reached",
        "occurrence_limit_reached",
        "short_alternative_limit_reached",
        "serialized_byte_limit_reached",
        "fail_closed_overflow",
        "overflow_reason",
        "serialized_occurrence_bytes",
    }
    assert summary["fail_closed_overflow"] is False
    assert summary["overflow_reason"] is None
    serialized = json.dumps(
        item["ocr_token_occurrences"],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert summary["serialized_occurrence_bytes"] == len(serialized)
    assert len(serialized) <= MAX_SPATIAL_OCCURRENCE_JSON_BYTES


def test_disabled_item_projection_is_exactly_the_p02_us05_shape() -> None:
    region = _chart_region(confidence=0.96)
    disabled = _image_item(
        deepcopy(region),
        Settings(ocr_numeric_cleanup_v2_enabled=True),
        source_document_identity="sha256:catastrophe",
    )
    enabled = _image_item(
        deepcopy(region),
        _spatial_settings(),
        source_document_identity="sha256:catastrophe",
    )

    assert "ocr_token_occurrences" not in disabled
    assert "ocr_occurrence_summary" not in disabled
    assert json.dumps(disabled, sort_keys=True, separators=(",", ":")) == (
        json.dumps(
            {
                key: value
                for key, value in enabled.items()
                if key
                not in {
                    "ocr_token_occurrences",
                    "ocr_occurrence_summary",
                }
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def test_occurrences_are_not_ir_children_or_canonical_contributions() -> None:
    enabled_item = _image_item(
        _chart_region(),
        _spatial_settings(),
        source_document_identity="sha256:catastrophe",
    )
    disabled_shape = deepcopy(enabled_item)
    disabled_shape.pop("ocr_token_occurrences")
    disabled_shape.pop("ocr_occurrence_summary")

    enabled_ir = build_document_ir(_document(enabled_item))
    disabled_ir = build_document_ir(_document(disabled_shape))
    enabled_presentation = build_canonical_presentation(enabled_ir)
    disabled_presentation = build_canonical_presentation(disabled_ir)

    assert len(enabled_ir.elements) == len(disabled_ir.elements)
    assert {
        element.type for element in enabled_ir.elements
    } == {element.type for element in disabled_ir.elements}
    assert not any(
        "ocr_token_occurrences"
        in str(element.properties.get("collection") or "")
        for element in enabled_ir.elements
    )
    assert enabled_presentation.full.markdown == (
        disabled_presentation.full.markdown
    )
    assert enabled_presentation.full.text == disabled_presentation.full.text
    assert "iH" not in enabled_presentation.full.markdown
    assert "iH" not in enabled_presentation.full.text
    assert to_markdown(_document(enabled_item)) == to_markdown(
        _document(disabled_shape)
    )


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


def test_pipeline_omits_spatial_keyword_on_exact_flag_off_adapter_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []

    def strict_p02_us05_raster(
        pages: Any,
        tesseract_cmd: str = "tesseract",
        languages: tuple[str, ...] = ("eng",),
        timeout_seconds: float = 30.0,
        max_render_pixels: int = 16_000_000,
        tessdata_path: str | None = None,
        *,
        numeric_cleanup_v2_enabled: bool = False,
    ) -> dict[int, list[ImageRegion]]:
        calls.append(
            (
                pages,
                tesseract_cmd,
                languages,
                timeout_seconds,
                max_render_pixels,
                tessdata_path,
                numeric_cleanup_v2_enabled,
            )
        )
        return {1: []}

    _mock_minimal_raster_pipeline(monkeypatch, strict_p02_us05_raster)

    pipeline._parse_loaded_document(
        _loaded_raster(),
        Settings(ocr_numeric_cleanup_v2_enabled=True),
    )

    assert len(calls) == 1
    assert calls[0][-1] is True


def test_pipeline_propagates_both_required_flags_only_when_enabled(
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

    pipeline._parse_loaded_document(_loaded_raster(), _spatial_settings())

    assert len(calls) == 1
    assert calls[0]["numeric_cleanup_v2_enabled"] is True
    assert calls[0]["spatial_token_preservation_enabled"] is True


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


def _strict_p02_us05_ocr_png_lines(
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
    numeric_cleanup_v2_enabled: bool = False,
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    assert crop_bounds
    assert scale > 0
    assert page_width > 0
    assert page_height > 0
    assert numeric_cleanup_v2_enabled is True
    del pixel_to_page_transform, raster_width, raster_height
    return [], [], []


def test_all_ocr_adapters_omit_disabled_spatial_kwarg_and_propagate_true(
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

    raster_page = SimpleNamespace(
        page_index=1,
        pixel_width=20,
        pixel_height=20,
        png_bytes=b"png",
        original_orientation=None,
        orientation_applied=False,
    )
    request = PdfRegionRequest(
        page_index=1,
        bbox={"x": 10.0, "y": 10.0, "w": 20.0, "h": 20.0},
    )
    monkeypatch.setattr(ocr_module.pdfium, "PdfDocument", FakeDocument)
    monkeypatch.setattr(
        ocr_module,
        "_resolve_tesseract",
        lambda _command: "/tesseract",
    )
    monkeypatch.setattr(ocr_module, "_render_region_png", _fake_render)
    monkeypatch.setattr(
        ocr_module,
        "_ocr_png_lines",
        _strict_p02_us05_ocr_png_lines,
    )

    disabled_results = (
        ocr_module.extract_raster_ocr(
            [raster_page],
            tesseract_cmd="test",
            numeric_cleanup_v2_enabled=True,
        ),
        ocr_module.extract_image_ocr(
            b"pdf",
            tesseract_cmd="test",
            numeric_cleanup_v2_enabled=True,
        ),
        ocr_module.extract_rendered_pdf_ocr(
            b"pdf",
            [request],
            tesseract_cmd="test",
            numeric_cleanup_v2_enabled=True,
        ),
    )
    assert all(result[1][0].warnings == [] for result in disabled_results)

    observed: list[bool] = []

    def capture(*args: Any, **kwargs: Any):
        observed.append(kwargs.pop("spatial_token_preservation_enabled"))
        return _strict_p02_us05_ocr_png_lines(*args, **kwargs)

    monkeypatch.setattr(ocr_module, "_ocr_png_lines", capture)
    ocr_module.extract_raster_ocr(
        [raster_page],
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
        spatial_token_preservation_enabled=True,
    )
    ocr_module.extract_image_ocr(
        b"pdf",
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
        spatial_token_preservation_enabled=True,
    )
    ocr_module.extract_rendered_pdf_ocr(
        b"pdf",
        [request],
        tesseract_cmd="test",
        numeric_cleanup_v2_enabled=True,
        spatial_token_preservation_enabled=True,
    )

    assert observed == [True, True, True]


def test_selective_adapter_omits_disabled_spatial_kwarg_and_propagates_true() -> (
    None
):
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
        numeric_cleanup_v2_enabled=True,
    )
    enabled = run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        {1: (612.0, 792.0)},
        tesseract_cmd="test-tesseract-that-does-not-exist",
        render_function=_render_factory(calls=enabled_calls),
        numeric_cleanup_v2_enabled=True,
        spatial_token_preservation_enabled=True,
    )

    assert disabled.status == enabled.status == "complete"
    assert len(disabled_calls) == len(enabled_calls) == 1
    disabled_kwargs = disabled_calls[0][1]
    enabled_kwargs = enabled_calls[0][1]
    assert "spatial_token_preservation_enabled" not in disabled_kwargs
    assert enabled_kwargs.pop("spatial_token_preservation_enabled") is True
    assert enabled_kwargs == disabled_kwargs
    assert disabled_kwargs["numeric_cleanup_v2_enabled"] is True
