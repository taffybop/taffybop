"""Small, custody-safe P02-US04 reconciliation fixtures.

The records deliberately identify both the extraction engine and the underlying
source layer.  Engine identity alone is not independent evidence: native and
layout candidates can be produced by different libraries while still consuming
the same damaged PDF text layer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SOURCE_SHA256 = "a" * 64
DEFAULT_BBOX = {
    "x": 72.0,
    "y": 120.0,
    "width": 180.0,
    "height": 12.0,
    "unit": "pt",
}


def candidate(
    candidate_id: str,
    text: str,
    *,
    source_kind: str,
    lineage_family: str,
    method: str,
    origin_asset_id: str,
    evidence_ids: tuple[str, ...],
    confidence: float | None = None,
    mapping_safety: str | None = None,
    span_id: str = "span-1",
    page_index: int = 1,
    bbox: dict[str, Any] | None = None,
    source_sha256: str = SOURCE_SHA256,
    font_ref: str | None = None,
    font_object_id: int | None = None,
    audit_finding_id: str | None = None,
    audit_run_index: int | None = None,
    run_evidence_id: str | None = None,
    selective_span_id: str | None = None,
    selective_outcome_id: str | None = None,
    recovery_refusal_reason_code: str | None = "embedded_program_missing",
    transform_valid: bool | None = None,
    pass_completed: bool | None = None,
    candidate_complete: bool | None = None,
    word_count: int | None = None,
    retained_token_count: int | None = None,
    candidate_truncated: bool = False,
    token_truncated: bool = False,
    malformed_output_concern: bool = False,
    languages: tuple[str, ...] = (),
    is_primary: bool | None = None,
) -> dict[str, Any]:
    """Build one strict normalized candidate and its complete lineage."""

    if mapping_safety is None:
        mapping_safety = {
            "native": "unsafe",
            "layout": "unsafe",
            "font_recovery": "safe",
            "selective_ocr": "not_applicable",
        }[source_kind]
    if is_primary is None:
        is_primary = source_kind == "native"
    provenance: dict[str, Any] = {
        "source_sha256": source_sha256,
        "lineage_family": lineage_family,
        "origin_asset_id": origin_asset_id,
        "method": method,
        "candidate_truncated": candidate_truncated,
        "token_truncated": token_truncated,
        "malformed_output_concern": malformed_output_concern,
        "languages": list(languages),
    }
    if source_kind in {"native", "layout", "font_recovery", "selective_ocr"}:
        provenance["audit_source_sha256"] = source_sha256
    if source_kind in {"font_recovery", "selective_ocr"}:
        provenance["recovery_source_sha256"] = source_sha256
        provenance.update(
            {
                "audit_finding_id": (
                    audit_finding_id or f"audit-finding:{span_id}"
                ),
                "audit_run_index": audit_run_index or 1,
                "font_ref": font_ref or "object:25",
                "font_object_id": font_object_id or 25,
            }
        )
    if source_kind == "font_recovery":
        provenance.update(
            {
                "run_evidence_id": run_evidence_id or evidence_ids[0],
            }
        )
    if source_kind == "selective_ocr":
        provenance.update(
            {
                "selective_ocr_source_sha256": source_sha256,
                "selective_span_id": selective_span_id or span_id,
                "selective_outcome_id": (
                    selective_outcome_id or f"selective-outcome:{span_id}"
                ),
                "transform_valid": (
                    True if transform_valid is None else transform_valid
                ),
                "pass_completed": (
                    True if pass_completed is None else pass_completed
                ),
                "candidate_complete": (
                    True if candidate_complete is None else candidate_complete
                ),
                "word_count": 1 if word_count is None else word_count,
                "retained_token_count": (
                    1 if retained_token_count is None else retained_token_count
                ),
                "languages": list(languages or ("eng",)),
            }
        )
        if recovery_refusal_reason_code is not None:
            provenance["recovery_refusal_reason_code"] = (
                recovery_refusal_reason_code
            )
    return {
        "candidate_id": candidate_id,
        "span_id": span_id,
        "page_index": page_index,
        "text": text,
        "bbox": deepcopy(bbox or DEFAULT_BBOX),
        "source_kind": source_kind,
        "mapping_safety": mapping_safety,
        "confidence": confidence,
        "evidence_ids": list(evidence_ids),
        "provenance": provenance,
        "is_primary": is_primary,
    }


def group(
    candidates: list[dict[str, Any]],
    *,
    group_id: str = "group-1",
    span_id: str = "span-1",
    page_index: int = 1,
    owner_element_id: str = "owner-1",
    owner_text: str | None = None,
    owner_markdown: str | None = None,
    target_bbox: dict[str, Any] | None = None,
    owner_bbox: dict[str, Any] | None = None,
    replacement_original_text: str | None = None,
    expected_scripts: tuple[str, ...] = ("Latn",),
) -> dict[str, Any]:
    """Build one bounded, same-page reconciliation group."""

    if owner_text is None:
        primary = next(
            (row for row in candidates if row.get("is_primary")),
            candidates[0],
        )
        owner_text = str(primary["text"])
    return {
        "group_id": group_id,
        "span_id": span_id,
        "page_index": page_index,
        "page_width_points": 612.0,
        "page_height_points": 792.0,
        "owner_element_id": owner_element_id,
        "owner_text": owner_text,
        "owner_markdown": owner_markdown or owner_text,
        "target_bbox": deepcopy(target_bbox or DEFAULT_BBOX),
        "owner_bbox": deepcopy(owner_bbox or DEFAULT_BBOX),
        "replacement_original_text": (
            owner_text
            if replacement_original_text is None
            else replacement_original_text
        ),
        "expected_scripts": list(expected_scripts),
        "candidates": deepcopy(candidates),
    }


def deterministic_font_case() -> dict[str, Any]:
    """A safe embedded-font cmap must beat the known-damaged native layer."""

    rows = [
        candidate(
            "native-catastrophe",
            "É w ( € )",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:25",
            evidence_ids=("ev-native-catastrophe",),
        ),
        candidate(
            "font-catastrophe",
            "Equity (US$)",
            source_kind="font_recovery",
            lineage_family="embedded_font_program",
            method="embedded_truetype_cmap_identity",
            origin_asset_id="embedded-font-program:25",
            evidence_ids=(
                "ev-font-run-catastrophe",
                "ev-font-glyph-1",
                "ev-font-glyph-2",
            ),
            mapping_safety="safe",
        ),
    ]
    return group(rows, owner_text="É w ( € )")


def independent_ocr_case() -> dict[str, Any]:
    """A visible raster reading may win when both text-layer options are unsafe."""

    rows = [
        candidate(
            "native-unsafe",
            "ClO",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:31",
            evidence_ids=("ev-native-unsafe",),
        ),
        candidate(
            "font-unsafe",
            "C1O",
            source_kind="font_recovery",
            lineage_family="embedded_font_program",
            method="unsupported_font_guess",
            origin_asset_id="embedded-font-program:31",
            evidence_ids=("ev-font-unsafe",),
            mapping_safety="unsafe",
        ),
        candidate(
            "ocr-independent",
            "CIO",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:page-1:crop-2",
            evidence_ids=("ev-ocr-independent", "ev-ocr-token-cio"),
            confidence=0.99,
            word_count=1,
            retained_token_count=1,
        ),
    ]
    return group(rows, owner_text="ClO")


def dependent_bad_layer_case() -> dict[str, Any]:
    """Two libraries consuming one text layer are one evidence source."""

    rows = [
        candidate(
            "native-dependent",
            "40 AO",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdfium_text",
            origin_asset_id="pdf-text-layer:chart-7",
            evidence_ids=("ev-native-dependent",),
        ),
        candidate(
            "layout-dependent",
            "40 AO",
            source_kind="layout",
            lineage_family="pdf_text_layer",
            method="docling_pdf_text",
            origin_asset_id="pdf-text-layer:chart-7",
            evidence_ids=("ev-layout-dependent",),
        ),
        candidate(
            "ocr-counterevidence",
            "40 40",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:page-1:chart-7",
            evidence_ids=("ev-ocr-counterevidence",),
            confidence=0.82,
            word_count=2,
            retained_token_count=2,
        ),
    ]
    return group(rows, owner_text="40 AO")


def low_margin_case() -> dict[str, Any]:
    """Plausible independent readings below the required margin remain open."""

    rows = [
        candidate(
            "ocr-low-margin-a",
            "FERS",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="synthetic-raster:page-1:row-4:capture-a",
            evidence_ids=("ev-ocr-low-margin-a",),
            confidence=0.94,
            word_count=1,
            retained_token_count=1,
        ),
        candidate(
            "ocr-low-margin-b",
            "FEBS",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="synthetic-raster:page-1:row-4:capture-b",
            evidence_ids=("ev-ocr-low-margin-b",),
            confidence=0.91,
            word_count=1,
            retained_token_count=1,
        ),
    ]
    return group(rows, owner_text="damaged")


def partial_overlap_case() -> dict[str, Any]:
    """A candidate covering only part of the owner cannot replace the owner."""

    partial_bbox = {
        "x": 72.0,
        "y": 120.0,
        "width": 70.0,
        "height": 12.0,
        "unit": "pt",
    }
    rows = [
        candidate(
            "native-partial",
            "Retirement benefits FERS contribution",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:row-9",
            evidence_ids=("ev-native-partial",),
        ),
        candidate(
            "ocr-partial",
            "FERS",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:page-1:row-9-fragment",
            evidence_ids=("ev-ocr-partial",),
            confidence=0.99,
            bbox=partial_bbox,
            word_count=1,
            retained_token_count=1,
        ),
    ]
    return group(
        rows,
        owner_text="Retirement benefits FERS contribution",
    )


def mixed_script_case() -> dict[str, Any]:
    """Visually confusable mixed-script text is never selected by plausibility."""

    rows = [
        candidate(
            "native-latin",
            "paypal total",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:mixed-1",
            evidence_ids=("ev-native-latin",),
            confidence=0.86,
            mapping_safety="unsafe",
        ),
        candidate(
            "ocr-cyrillic",
            "раураl total",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:page-1:mixed-1",
            evidence_ids=("ev-ocr-cyrillic",),
            confidence=0.99,
            word_count=2,
            retained_token_count=2,
        ),
    ]
    return group(rows, owner_text="paypal total", expected_scripts=("Latn",))


def healthy_native_case() -> dict[str, Any]:
    """A lone healthy native candidate is inert and remains canonical."""

    rows = [
        candidate(
            "native-healthy",
            "Audited healthy text",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:healthy-1",
            evidence_ids=("ev-native-healthy",),
            confidence=0.99,
            mapping_safety="healthy",
        )
    ]
    return group(rows, owner_text="Audited healthy text")


def reconciliation_cases() -> dict[str, dict[str, Any]]:
    """Return every deterministic positive, negative, and non-target case."""

    return {
        "deterministic_font": deterministic_font_case(),
        "independent_ocr": independent_ocr_case(),
        "dependent_bad_layer": dependent_bad_layer_case(),
        "low_margin": low_margin_case(),
        "partial_overlap": partial_overlap_case(),
        "mixed_script": mixed_script_case(),
        "healthy_native": healthy_native_case(),
    }
