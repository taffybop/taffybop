from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import ParseResult
from app.services.chart_assets import (
    ChartAssetAttempt,
    ChartResolution,
    build_chart_resolution,
)
from app.services.visual_contracts import VisualStructure
from app.services.visual_semantics import apply_visual_semantics
from app.services.visual_source_text import attach_visual_source_text


def _chart_item() -> dict[str, Any]:
    return {
        "id": "chart-transcript-owner",
        "type": "chart",
        "content_type": "chart",
        "reading_order": 0,
        "value": "OCR 2024",
        "ocr_text": "OCR 2024",
        "md": "OCR 2024",
        "bbox": {
            "x": 10.0,
            "y": 20.0,
            "width": 100.0,
            "height": 80.0,
            "unit": "pt",
        },
        "source": "ocr",
        "confidence": 0.9,
        "region_role": "content_region",
        "items": [
            {
                "text": "OCR 2024",
                "value": "OCR 2024",
                "bbox": {
                    "x": 15.0,
                    "y": 30.0,
                    "width": 40.0,
                    "height": 8.0,
                    "unit": "pt",
                },
                "confidence": 0.9,
                "source": "ocr",
                "accepted": True,
            }
        ],
        "parse_concerns": ["chart_values_not_structured"],
    }


def _native_chart_item() -> dict[str, Any]:
    item = _chart_item()
    native_text = "Native revenue 2024"
    native_bbox = {
        "x": 16.0,
        "y": 42.0,
        "width": 60.0,
        "height": 8.0,
        "unit": "pt",
    }
    return attach_visual_source_text(
        item,
        {
            "method": "pdf_text_layer_inside_visual_bbox",
            "text": native_text,
            "text_sha256": hashlib.sha256(native_text.encode("utf-8")).hexdigest(),
            "occurrences": [
                {
                    "id": "native-occurrence-1",
                    "occurrence_id": "native-occurrence-1",
                    "text": native_text,
                    "value": native_text,
                    "bbox": native_bbox,
                    "confidence": 1.0,
                    "word_count": 3,
                    "source": "native",
                    "accepted": True,
                    "selected": True,
                }
            ],
            "lines": [
                {
                    "text": native_text,
                    "bbox": native_bbox,
                    "source_token_ids": ["native-occurrence-1"],
                }
            ],
        },
        promote_primary=False,
    )


def _payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "chart-transcript.pdf",
            "mime_type": "application/pdf",
            "sha256": "1" * 64,
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
            "engine": "test",
            "ocr_engine": "test",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _resolved_payload(item: dict[str, Any]) -> dict[str, Any]:
    output = apply_visual_semantics(
        _payload(item),
        Settings(visual_structure_schema_enabled=True),
        input_kind="pdf",
    )
    staged = output["pages"][0]["items"][0]
    structure = VisualStructure.model_validate(staged["visual_structure"])
    resolution = build_chart_resolution(
        item=staged,
        structure=structure,
        page_index=1,
        source_order=0,
        asset_attempt=ChartAssetAttempt(None, "source_bytes_unavailable"),
        settings=Settings(),
    )
    staged["chart_resolution"] = resolution.model_dump(
        mode="json",
        exclude_none=True,
    )
    return output


def test_ungrounded_native_text_cannot_override_attributable_ocr() -> None:
    item = _chart_item()
    item["visual_source_text"] = "UNATTRIBUTED NATIVE CLAIM"

    output = _resolved_payload(item)
    resolved = ParseResult.model_validate(output).pages[0].items[0]
    assert resolved.chart_resolution is not None
    transcript = resolved.chart_resolution.transcript
    assert transcript.source == "ocr"
    assert transcript.text == "OCR 2024"

    assert resolved.visual_structure is not None
    evidence = {
        record.id: record for record in resolved.visual_structure.evidence
    }
    assert transcript.evidence_ids
    assert {
        evidence[evidence_id].provenance.extraction_method
        for evidence_id in transcript.evidence_ids
    } == {"ocr"}


def test_generated_caption_is_not_relabelled_as_a_source_transcript() -> None:
    item = _chart_item()
    item.pop("ocr_text")
    item["caption"] = "Model-generated chart narrative"
    item["caption_generated"] = True
    item["caption_source"] = "test-model"
    item["parse_concerns"].append("model_generated_visual_description")

    output = _resolved_payload(item)
    resolved = ParseResult.model_validate(output).pages[0].items[0]
    assert resolved.chart_resolution is not None
    transcript = resolved.chart_resolution.transcript
    assert transcript.source == "source_labels"
    assert transcript.text == "OCR 2024"
    assert "Model-generated" not in transcript.text


def test_native_transcript_keeps_only_its_exact_occurrence_evidence() -> None:
    native_text = "Native revenue 2024"
    output = _resolved_payload(_native_chart_item())
    resolved = ParseResult.model_validate(output).pages[0].items[0]
    assert resolved.chart_resolution is not None
    transcript = resolved.chart_resolution.transcript
    assert transcript.source == "native"
    assert transcript.text == native_text

    assert resolved.visual_structure is not None
    evidence = {
        record.id: record for record in resolved.visual_structure.evidence
    }
    assert len(transcript.evidence_ids) == 1
    [record] = [evidence[evidence_id] for evidence_id in transcript.evidence_ids]
    assert record.provenance.extraction_method == "explicit_text"
    assert record.provenance.source_token_ids == ["native-occurrence-1"]


def test_public_contract_rejects_transcript_and_confidence_custody_tampering() -> None:
    output = _resolved_payload(_chart_item())
    resolution = output["pages"][0]["items"][0]["chart_resolution"]

    confidence_tamper = deepcopy(resolution)
    confidence_tamper["confidence_dimensions"]["transcription"] = deepcopy(
        confidence_tamper["confidence_dimensions"]["family"]
    )
    with pytest.raises(
        ValidationError,
        match="confidence dimensions differ",
    ):
        ChartResolution.model_validate(confidence_tamper, strict=True)

    evidence_tamper = deepcopy(output)
    tampered_item = evidence_tamper["pages"][0]["items"][0]
    region_evidence_id = tampered_item["visual_structure"]["region"][
        "evidence_ids"
    ][0]
    tampered_item["chart_resolution"]["transcript"]["evidence_ids"] = [
        region_evidence_id
    ]
    with pytest.raises(ValidationError, match="chart transcript replay differs"):
        ParseResult.model_validate(evidence_tamper)


@pytest.mark.parametrize(
    "field",
    ["text", "source", "evidence_ids", "confidence"],
)
def test_public_contract_exactly_replays_ocr_transcript(
    field: str,
) -> None:
    output = _resolved_payload(_chart_item())
    item = output["pages"][0]["items"][0]
    resolution = item["chart_resolution"]
    transcript = resolution["transcript"]
    if field == "text":
        transcript["text"] = "FORGED OCR DECISION TEXT"
        transcript["text_sha256"] = hashlib.sha256(
            transcript["text"].encode("utf-8")
        ).hexdigest()
    elif field == "source":
        transcript["source"] = "source_labels"
    elif field == "evidence_ids":
        transcript["evidence_ids"] = item["visual_structure"]["region"][
            "evidence_ids"
        ]
    else:
        forged_confidence = {
            "value": None,
            "unavailable_reason": "source_confidence_unavailable",
        }
        transcript["confidence"] = forged_confidence
        resolution["confidence_dimensions"]["transcription"] = deepcopy(
            forged_confidence
        )

    with pytest.raises(ValidationError, match="chart transcript replay differs"):
        ParseResult.model_validate(output)


@pytest.mark.parametrize(
    ("source", "item"),
    [
        ("native", _native_chart_item()),
        (
            "source_labels",
            {key: value for key, value in _chart_item().items() if key != "ocr_text"},
        ),
    ],
)
def test_public_contract_replays_every_available_transcript_source(
    source: str,
    item: dict[str, Any],
) -> None:
    output = _resolved_payload(deepcopy(item))
    transcript = output["pages"][0]["items"][0]["chart_resolution"][
        "transcript"
    ]
    assert transcript["source"] == source
    transcript["text"] = f"FORGED {source} TEXT"
    transcript["text_sha256"] = hashlib.sha256(
        transcript["text"].encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValidationError, match="chart transcript replay differs"):
        ParseResult.model_validate(output)


def test_public_contract_exactly_replays_unavailable_transcript() -> None:
    item = _chart_item()
    item.pop("ocr_text")
    item["items"] = []
    item["value"] = ""
    item["md"] = ""
    output = _resolved_payload(item)
    transcript = output["pages"][0]["items"][0]["chart_resolution"][
        "transcript"
    ]
    assert transcript["status"] == "unavailable"
    transcript.update(
        {
            "status": "available",
            "source": "source_labels",
            "text": "FORGED LABEL",
            "text_sha256": hashlib.sha256(b"FORGED LABEL").hexdigest(),
            "evidence_ids": output["pages"][0]["items"][0][
                "visual_structure"
            ]["region"]["evidence_ids"],
        }
    )

    with pytest.raises(ValidationError):
        ParseResult.model_validate(output)
