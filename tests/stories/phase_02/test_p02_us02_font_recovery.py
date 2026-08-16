from __future__ import annotations

import json
import math
from pathlib import Path

from app.services.font_audit import audit_pdf_fonts
from app.services.font_recovery import (
    WIDTH_TOLERANCE_EM,
    FontRecoveryGlyph,
    FontRecoveryReport,
    recover_pdf_font_text,
)
from app.services.ir import EvidenceMethod, round_trip_document
from app.services.presentation import build_canonical_presentation
from tests.benchmarks.corpus_registry import EXPECTED_CASE_IDS
from tests.fixtures.phase_02.font_recovery import (
    EXPECTED_RECOVERED_TEXT,
    FIXTURE_IDS,
    build_fixture,
    fixture_hashes,
    self_check,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS_ROOT = WORKSPACE / "benchmark-expertmodeldata"
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
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


def _catastrophe_report() -> FontRecoveryReport:
    pdf_bytes = (CORPUS_ROOT / "catastrophe-recap.pdf").read_bytes()
    audit = audit_pdf_fonts(pdf_bytes)
    return recover_pdf_font_text(pdf_bytes, audit)


def _glyphs(report: FontRecoveryReport) -> list[FontRecoveryGlyph]:
    return [glyph for run in report.runs for glyph in run.glyphs]


def _text_in_box(
    report: FontRecoveryReport,
    bbox: list[float],
    *,
    tolerance: float = 0.002,
) -> str:
    left, top, width, height = bbox
    right = left + width
    bottom = top + height
    selected = []
    for glyph in _glyphs(report):
        center_x = glyph.bbox.x + glyph.bbox.width / 2
        center_y = glyph.bbox.y + glyph.bbox.height / 2
        if (
            left - tolerance <= center_x <= right + tolerance
            and top - tolerance <= center_y <= bottom + tolerance
        ):
            selected.append(glyph)
    selected.sort(
        key=lambda glyph: (
            round(glyph.bbox.y, 2),
            glyph.bbox.x,
            glyph.run_index,
            glyph.glyph_index,
        )
    )
    return "".join(glyph.recovered_text for glyph in selected)


def test_generated_recovery_fixtures_are_byte_stable_and_safe() -> None:
    assert self_check() == fixture_hashes()
    assert FIXTURE_IDS == (
        "safe-identity",
        "healthy-identity",
        "used-many-to-one",
        "unused-alias-control",
        "ligature",
        "bidi-control",
        "width-mismatch",
        "nonidentity",
        "missing-program",
    )
    safe_pdf = build_fixture("safe-identity")
    safe = recover_pdf_font_text(safe_pdf, audit_pdf_fonts(safe_pdf))

    assert safe.status == "complete"
    assert safe.fonts_considered == safe.fonts_recovered == 1
    assert safe.font_programs_parsed == 1
    assert safe.recovered_glyph_count == len(EXPECTED_RECOVERED_TEXT)
    assert "".join(run.recovered_text for run in safe.runs) == (
        EXPECTED_RECOVERED_TEXT
    )


def test_catastrophe_recovery_is_exact_deterministic_and_fully_grounded() -> None:
    first = _catastrophe_report()
    second = _catastrophe_report()

    assert first == second
    assert first.status == "complete"
    assert first.fonts_considered == first.fonts_recovered == 2
    assert first.font_programs_parsed == 2
    assert first.pages_inspected == 1
    assert first.characters_inspected == 1414
    assert first.recovered_glyph_count == 150
    assert len(first.runs) == 29
    assert first.refusals == []
    assert first.diagnostics == []
    assert {run.font_object_id for run in first.runs} == {13, 25}

    runs = {run.recovered_text: run for run in first.runs}
    assert runs["Windstorm Éowyn "].original_text == "          É w   "
    assert runs["€620 million"].original_text == "€           "
    assert runs["Americas"].font_object_id == 25
    assert runs["APAC"].font_object_id == 25
    assert runs["EMEA"].font_object_id == 25
    assert runs["USA"].font_object_id == 25

    glyphs = _glyphs(first)
    assert len(glyphs) == 150
    assert len({glyph.evidence_id for glyph in glyphs}) == 150
    for glyph in glyphs:
        assert glyph.cid == glyph.glyph_id
        assert glyph.recovered_text == chr(glyph.unicode_code_point)
        assert glyph.method == "embedded_truetype_cmap_identity"
        assert glyph.width_delta_em <= WIDTH_TOLERANCE_EM
        assert glyph.embedded_advance_width >= 0
        assert glyph.units_per_em >= 16
        assert math.isfinite(glyph.page_advance)
        assert math.isfinite(glyph.pdf_width_em)
        for coordinate in (
            glyph.bbox.x,
            glyph.bbox.y,
            glyph.bbox.width,
            glyph.bbox.height,
        ):
            assert math.isfinite(coordinate)
            assert coordinate >= 0

    # CID 3 is the real space glyph in the embedded cmap; it remains a space
    # rather than being stripped or guessed from language context.
    space_glyphs = [glyph for glyph in glyphs if glyph.cid == 3]
    assert space_glyphs
    assert {glyph.recovered_text for glyph in space_glyphs} == {" "}


def test_all_reviewed_chart_labels_and_source_note_match_visible_truth() -> None:
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    report = _catastrophe_report()

    assert len(truth["chart_labels"]) == 23
    for label in truth["chart_labels"]:
        assert _text_in_box(report, label["bbox"]) == label["text"]

    source_note = next(
        element
        for element in truth["elements"]
        if element["element_id"] == "chart-source-note"
    )
    assert _text_in_box(report, source_note["bbox"]) == source_note["text"]


def test_real_paragraph_projects_exactly_with_original_evidence_retained() -> None:
    pdf_bytes = (CORPUS_ROOT / "catastrophe-recap.pdf").read_bytes()
    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    baseline = json.loads(BASELINE_OUTPUT.read_text(encoding="utf-8"))

    projected, internal_ir = round_trip_document(
        baseline,
        font_audit=audit.model_dump(mode="json", exclude_none=True),
        font_recovery=recovery.model_dump(mode="json", exclude_none=True),
    )
    presentation = build_canonical_presentation(internal_ir)

    paragraph = next(
        item
        for item in projected["pages"][0]["items"]
        if TARGET_SENTENCE in str(item.get("value") or "")
    )
    assert paragraph["value"].count(TARGET_SENTENCE) == 1
    assert paragraph["md"].count(TARGET_SENTENCE) == 1
    assert paragraph["font_recovery_original_value"].count("É w") == 1
    assert paragraph["font_recovery_original_value"].count("( € )") == 1
    assert len(paragraph["font_recovery_alternatives"]) == 2
    assert {entry["selected"] for entry in paragraph[
        "font_recovery_alternatives"
    ]} == {True}

    assert presentation.full.text.count(TARGET_SENTENCE) == 1
    assert presentation.full.markdown.count(TARGET_SENTENCE) == 1
    assert "É w" not in presentation.full.text
    assert "( € )" not in presentation.full.text

    paragraph_element = next(
        element
        for element in internal_ir.elements
        if element.presentation_role == "primary"
        and TARGET_SENTENCE in str(element.value or "")
    )
    methods = {
        evidence.method
        for evidence in internal_ir.evidence
        if evidence.element_id == paragraph_element.id
    }
    assert EvidenceMethod.NATIVE in methods
    assert EvidenceMethod.RECOVERED in methods
    assert {
        concern.code
        for concern in internal_ir.concerns
        if concern.target_ref == paragraph_element.id
    } >= {"pdf_font_text_recovered"}


def test_every_healthy_corpus_case_short_circuits_without_rewrite() -> None:
    observed: dict[str, tuple[int, int, int, int]] = {}
    for case_id in EXPECTED_CASE_IDS:
        if case_id == "catastrophe-recap":
            continue
        pdf_bytes = (CORPUS_ROOT / f"{case_id}.pdf").read_bytes()
        audit = audit_pdf_fonts(pdf_bytes)
        report = recover_pdf_font_text(pdf_bytes, audit)
        observed[case_id] = (
            report.pages_inspected,
            report.fonts_recovered,
            report.recovered_glyph_count,
            len(report.runs),
        )
        assert report.status == "complete"
        assert report.refusals == []
        assert report.diagnostics == []

    assert observed == {
        case_id: (0, 0, 0, 0)
        for case_id in EXPECTED_CASE_IDS
        if case_id != "catastrophe-recap"
    }
