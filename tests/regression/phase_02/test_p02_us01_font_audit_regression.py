from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import app.services.font_audit as font_audit_module
import app.services.ir as ir_module
import app.services.pipeline as pipeline
from app.config import Settings
from app.services.input_documents import InputKind, LoadedDocument
from app.services.ir import DocumentIR


WORKSPACE = Path(__file__).resolve().parents[3]
CATASTROPHE_PDF = (
    WORKSPACE / "benchmark-expertmodeldata" / "catastrophe-recap.pdf"
)


def _masked(payload: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(payload)
    output["processing"]["duration_ms"] = 0
    return output


def test_pdf_adapter_audits_once_and_emits_internal_ir_concerns_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = CATASTROPHE_PDF.read_bytes()
    loaded = LoadedDocument(
        kind=InputKind.PDF,
        original_bytes=pdf_bytes,
        processing_bytes=pdf_bytes,
        original_filename="catastrophe-recap.pdf",
        processing_filename="catastrophe-recap.pdf",
        mime_type="application/pdf",
        source_format="PDF",
    )
    pages = [
        {
            "page_index": 1,
            "page_number": 1,
            "page_label": "1",
            "page_width": 612.0,
            "page_height": 792.0,
            "unit": "pt",
            "success": True,
            "items": [],
            "warnings": [],
        }
    ]
    native_texts = ["Native text remains byte-stable"]
    raw_graph = {"body": {"children": []}}

    monkeypatch.setattr(pipeline.shutil, "which", lambda _command: "/tesseract")
    monkeypatch.setattr(
        pipeline,
        "_native_pdf_pages",
        lambda *_args, **_kwargs: (deepcopy(pages), list(native_texts)),
    )
    monkeypatch.setattr(
        pipeline,
        "_convert_with_docling",
        lambda *_args, **_kwargs: (raw_graph, []),
    )
    monkeypatch.setattr(
        pipeline,
        "extract_image_ocr",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        pipeline,
        "_select_pdf_render_requests",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        pipeline,
        "extract_rendered_pdf_ocr",
        lambda *_args, **_kwargs: {},
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

    def analyze(context: pipeline.SharedAnalysisContext) -> None:
        context.pages[0]["items"] = [
            {
                "id": "p1-i1",
                "type": "text",
                "reading_order": 0,
                "value": native_texts[0],
                "md": native_texts[0],
                "bbox": {
                    "x": 72,
                    "y": 72,
                    "width": 180,
                    "height": 12,
                    "unit": "pt",
                },
                "source": "native",
            }
        ]

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)

    audit_calls = 0
    real_audit = font_audit_module.audit_pdf_fonts

    def observed_audit(value: bytes):
        nonlocal audit_calls
        audit_calls += 1
        assert value is pdf_bytes
        return real_audit(value)

    monkeypatch.setattr(
        font_audit_module,
        "audit_pdf_fonts",
        observed_audit,
    )

    captured: list[DocumentIR] = []
    real_round_trip = ir_module.round_trip_document

    def observed_round_trip(
        document: Any,
        *,
        raw_graph: Any,
        native_texts: Any,
        font_audit: Any = None,
    ):
        result = real_round_trip(
            document,
            raw_graph=raw_graph,
            native_texts=native_texts,
            font_audit=font_audit,
        )
        captured.append(result[1])
        return result

    monkeypatch.setattr(
        ir_module,
        "round_trip_document",
        observed_round_trip,
    )

    common = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
    }
    disabled = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_integrity_font_audit_enabled=False),
    ).model_dump(mode="json")
    assert audit_calls == 0

    enabled = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_integrity_font_audit_enabled=True),
    ).model_dump(mode="json")
    assert audit_calls == 1

    assert _masked(enabled) == _masked(disabled)
    assert "font_audit" not in str(enabled)
    assert len(captured) == 2
    assert captured[0].concerns == []
    font_concerns = [
        concern
        for concern in captured[1].concerns
        if concern.code == "pdf_font_mapping_suspicious"
    ]
    assert {concern.source_ref for concern in font_concerns} == {
        "pdf-font-object:13",
        "pdf-font-object:25",
    }
    assert all(
        concern.target_ref == captured[1].pages[0].id
        for concern in font_concerns
    )
