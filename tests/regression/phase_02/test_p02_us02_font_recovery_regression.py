from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services import font_audit as font_audit_module
from app.services import font_recovery as font_recovery_module
from app.services import ir as ir_module
from app.services import pipeline
from app.services.input_documents import InputKind, LoadedDocument


WORKSPACE = Path(__file__).resolve().parents[3]
CATASTROPHE_PDF = (
    WORKSPACE / "benchmark-expertmodeldata" / "catastrophe-recap.pdf"
)
BASELINE_OUTPUT = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
    / "catastrophe-recap"
    / "our-output.json"
)
TARGET_SENTENCE = (
    "Windstorm Éowyn in Ireland and the UK followed with $690 million "
    "(€620 million)."
)


def test_pdf_pipeline_recovers_once_only_when_enabled(
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
    baseline = json.loads(BASELINE_OUTPUT.read_text(encoding="utf-8"))
    selected_items = [
        deepcopy(
            next(
                item
                for item in baseline["pages"][0]["items"]
                if "É w" in str(item.get("value") or "")
            )
        ),
        deepcopy(
            next(
                item
                for item in baseline["pages"][0]["items"]
                if item.get("type") == "chart"
            )
        ),
    ]
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
    native_texts = ["É w in Ireland; million ( € )."]
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
        context.pages[0]["items"] = deepcopy(selected_items)

    monkeypatch.setattr(pipeline, "_analyze_shared_pages", analyze)

    audit_calls = 0
    recovery_calls = 0
    real_audit = font_audit_module.audit_pdf_fonts
    real_recovery = font_recovery_module.recover_pdf_font_text

    def observed_audit(value: bytes):
        nonlocal audit_calls
        audit_calls += 1
        assert value is pdf_bytes
        return real_audit(value)

    def observed_recovery(value: bytes, audit_report: Any):
        nonlocal recovery_calls
        recovery_calls += 1
        assert value is pdf_bytes
        return real_recovery(value, audit_report)

    monkeypatch.setattr(
        font_audit_module,
        "audit_pdf_fonts",
        observed_audit,
    )
    monkeypatch.setattr(
        font_recovery_module,
        "recover_pdf_font_text",
        observed_recovery,
    )

    captured_recovery: list[Any] = []
    real_round_trip = ir_module.round_trip_document

    def observed_round_trip(
        document: Any,
        *,
        raw_graph: Any,
        native_texts: Any,
        font_audit: Any = None,
        font_recovery: Any = None,
    ):
        captured_recovery.append(font_recovery)
        return real_round_trip(
            document,
            raw_graph=raw_graph,
            native_texts=native_texts,
            font_audit=font_audit,
            font_recovery=font_recovery,
        )

    monkeypatch.setattr(
        ir_module,
        "round_trip_document",
        observed_round_trip,
    )

    common = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "text_integrity_font_audit_enabled": True,
    }
    disabled = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_integrity_font_recovery_enabled=False),
    ).model_dump(mode="json")
    assert audit_calls == 1
    assert recovery_calls == 0
    assert captured_recovery == [None]
    assert "É w" in disabled["pages"][0]["items"][0]["value"]
    assert "( € )" in disabled["pages"][0]["items"][0]["value"]

    enabled = pipeline._parse_loaded_document(
        loaded,
        Settings(**common, text_integrity_font_recovery_enabled=True),
    ).model_dump(mode="json")
    assert audit_calls == 2
    assert recovery_calls == 1
    assert captured_recovery[-1]["recovered_glyph_count"] == 150

    paragraph, chart = enabled["pages"][0]["items"]
    assert paragraph["value"].count(TARGET_SENTENCE) == 1
    assert paragraph["md"].count(TARGET_SENTENCE) == 1
    assert paragraph["font_recovery_original_value"] == (
        disabled["pages"][0]["items"][0]["value"]
    )
    assert {entry["selected"] for entry in paragraph[
        "font_recovery_alternatives"
    ]} == {True}

    # Chart recovery remains an attributable alternative until P02-US04.
    assert chart["value"] == disabled["pages"][0]["items"][1]["value"]
    assert chart["md"] == disabled["pages"][0]["items"][1]["md"]
    assert {
        entry["recovered_text"]
        for entry in chart["font_recovery_alternatives"]
    } >= {"Americas", "APAC", "EMEA", "USA"}
    assert {entry["selected"] for entry in chart[
        "font_recovery_alternatives"
    ]} == {False}

    canonical = enabled["canonical_presentation"]
    assert canonical["full"]["text"].count(TARGET_SENTENCE) == 1
    assert canonical["full"]["markdown"].count(TARGET_SENTENCE) == 1
    assert "É w" not in canonical["full"]["text"]
    assert "( € )" not in canonical["full"]["text"]

    serialized = json.dumps(enabled, ensure_ascii=False, sort_keys=True)
    assert "FontFile2" not in serialized
    assert "font_program_bytes" not in serialized
