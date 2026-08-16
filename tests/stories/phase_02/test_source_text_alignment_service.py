from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path

from app.services.source_text_alignment import (
    MAX_REPORT_BYTES,
    SOURCE_TEXT_ALIGNMENT_POLICY_ID,
    _bounded_json_size,
    _dataclass_json_default,
    align_pages_to_source,
    extract_source_text_evidence,
    text_for_bbox,
)


ROOT = Path(__file__).resolve().parents[3]
SOURCES = ROOT / "benchmark-expertmodeldata"
RETAINED = (
    ROOT
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
)


def _pages(case_id: str) -> list[dict[str, object]]:
    return json.loads(
        (RETAINED / case_id / "our-output.json").read_text(
            encoding="utf-8"
        )
    )["pages"]


def _item(
    pages: list[dict[str, object]],
    item_id: str,
) -> dict[str, object]:
    matches = [
        item
        for page in pages
        for item in page["items"]  # type: ignore[index]
        if item["id"] == item_id  # type: ignore[index]
    ]
    assert len(matches) == 1
    return matches[0]  # type: ignore[return-value]


def test_pdfium_evidence_excludes_icon_text_and_composes_diaeresis() -> None:
    evidence = extract_source_text_evidence(
        (SOURCES / "clinical-study.pdf").read_bytes(),
        max_pages=4,
    )

    assert evidence.usable is True
    author = text_for_bbox(
        evidence,
        1,
        {
            "x": 200.012,
            "y": 208.353,
            "width": 358.713,
            "height": 31.492,
        },
    )
    affiliations = text_for_bbox(
        evidence,
        1,
        {
            "x": 200.012,
            "y": 250.835,
            "width": 370.863,
            "height": 76.885,
        },
    )

    assert author is not None
    assert author.text.startswith("Sebastian Burchert1*, Mhd Salem")
    assert "BurchertID" not in author.text
    assert affiliations is not None
    assert "Freie Universität Berlin" in affiliations.text
    assert "Babeș-Bolyai University" in affiliations.text
    white_icon_characters = [
        character
        for page in evidence.pages
        for character in page.characters
        if character.excluded_reason == "white_icon_overlay"
    ]
    assert white_icon_characters
    assert all(
        character.fill_rgba == (255, 255, 255, 255)
        for character in white_icon_characters
    )


def test_type1_differences_recover_only_closed_glyph_roles() -> None:
    evidence = extract_source_text_evidence(
        (SOURCES / "esg-metrics.pdf").read_bytes(),
    )
    selection = text_for_bbox(
        evidence,
        1,
        {
            "x": 133.8,
            "y": 397.233,
            "width": 153.625,
            "height": 3.545,
        },
    )

    assert evidence.usable is True
    assert selection is not None
    assert selection.text.startswith("4 Energy data")
    assert "to reflect the divestiture" in selection.text
    glyphs = {
        glyph.glyph_name: glyph
        for glyph in evidence.type1_glyphs
    }
    assert glyphs["four.numr"].recovered_text == "4"
    assert glyphs["four.numr"].role == "superscript"
    assert glyphs["f_l"].recovered_text == "fl"
    assert glyphs["f_l"].role == "ligature"


def test_semantic_hyphen_requires_same_document_corroboration() -> None:
    pages = _pages("settlement-agreement")
    evidence = extract_source_text_evidence(
        (SOURCES / "settlement-agreement.pdf").read_bytes(),
    )
    summary = align_pages_to_source(pages, evidence)

    assert summary.selected_count == 1
    selected = summary.selections[0]
    assert selected.method == "pdfium_semantic_hyphen"
    assert selected.checks["pdfium_is_hyphen"] is True
    assert selected.checks["same_document_corroboration"] is True
    assert "Look-Back Date" in selected.selected_text


def test_alignment_is_transactional_and_idempotent() -> None:
    pages = _pages("purchase-agreement")
    before = deepcopy(pages)
    evidence = extract_source_text_evidence(
        (SOURCES / "purchase-agreement.pdf").read_bytes(),
    )

    first = align_pages_to_source(pages, evidence)
    after_first = deepcopy(pages)
    second = align_pages_to_source(pages, evidence)

    assert before != after_first
    assert first.policy_id == SOURCE_TEXT_ALIGNMENT_POLICY_ID
    assert first.selected_count == len(first.selections) == 4
    assert second.selected_count == 0
    assert pages == after_first

    invalid = extract_source_text_evidence(b"not a pdf")
    unchanged = deepcopy(pages)
    refused = align_pages_to_source(pages, invalid)
    assert refused.status == "refused"
    assert pages == unchanged


def test_postal_legacy_ocr_without_contributor_fails_closed() -> None:
    pages = _pages("postal-10k")
    before = deepcopy(pages)
    evidence = extract_source_text_evidence(
        (SOURCES / "postal-10k.pdf").read_bytes(),
        max_pages=3,
    )
    summary = align_pages_to_source(pages, evidence)

    # This immutable P00 predecessor predates source-bound OCR contributors.
    # It therefore remains attributable only as legacy public content and must
    # not be destructively reconciled. The dedicated complete-pipeline
    # regression covers contributor-backed ClO removal and table-owned FERS
    # suppression from fresh source bytes.
    assert summary.selected_count == 0
    assert summary.selections == ()
    assert pages == before
    assert _item(pages, "p1-i4")["value"] == "ClO"
    assert _item(pages, "p1-i5")["value"] == "FERS"
    assert all(
        item.get("source_alignment_suppressed") is not True
        for page in pages
        for item in page["items"]  # type: ignore[index]
    )


def test_fail_closed_bounds_return_no_partial_evidence() -> None:
    pdf_bytes = (SOURCES / "finance-10k.pdf").read_bytes()
    report = extract_source_text_evidence(pdf_bytes, max_pages=0)

    assert report.usable is False
    assert report.refusal_code == "source_alignment_max_pages_invalid"
    assert report.pages == ()
    assert report.type1_glyphs == ()


def test_report_bound_encoder_matches_public_serialization_exactly() -> None:
    evidence = extract_source_text_evidence(
        (SOURCES / "finance-10k.pdf").read_bytes(),
    )

    direct = json.dumps(
        evidence,
        default=_dataclass_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    public = json.dumps(
        evidence.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    assert direct == public
    assert _bounded_json_size(
        evidence,
        max_bytes=MAX_REPORT_BYTES,
        deadline=time.perf_counter() + 2.0,
    ) == len(public)
