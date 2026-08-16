from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from app.services import font_audit as font_audit_module
from app.services.font_audit import (
    FontAuditReport,
    audit_pdf_fonts,
)
from tests.benchmarks.corpus_registry import EXPECTED_CASE_IDS
from tests.fixtures.phase_02.font_audit import (
    FIXTURES,
    build_fixture,
    fixture_hashes,
    self_check,
)


WORKSPACE = Path(__file__).resolve().parents[3]
FIXTURE_REGISTRY = (
    WORKSPACE
    / "tracker"
    / "phase-02-text-integrity"
    / "evidence"
    / "P02-font-fixture-registry.json"
)
CORPUS_ROOT = WORKSPACE / "benchmark-expertmodeldata"


def test_synthetic_font_fixture_registry_is_complete_and_byte_stable() -> None:
    verified = self_check()
    assert verified == fixture_hashes()
    assert len(verified) == 4

    registry = json.loads(FIXTURE_REGISTRY.read_text(encoding="utf-8"))
    assert registry["schema_version"] == "1.0"
    assert registry["storage"] == "deterministic-in-memory-only"
    assert registry["contains_third_party_font_programs"] is False
    assert {
        entry["fixture_id"]: entry["sha256"]
        for entry in registry["fixtures"]
    } == verified

    for entry in registry["fixtures"]:
        report = audit_pdf_fonts(build_fixture(entry["fixture_id"]))
        assert len(report.fonts) == 1
        font = report.fonts[0]
        assert font.classification == entry["expected_classification"]
        if "expected_cid_to_gid" in entry:
            assert font.cid_to_gid == entry["expected_cid_to_gid"]
        if "expected_embedded_program" in entry:
            assert (
                font.embedded_program
                is entry["expected_embedded_program"]
            )
        expected_reasons = entry.get("expected_reason_codes", [])
        actual_reasons = [
            reason
            for finding in report.findings
            for reason in finding.reason_codes
        ]
        assert actual_reasons == expected_reasons

    for fixture in FIXTURES:
        pdf_bytes = build_fixture(fixture.fixture_id)
        assert pdf_bytes.startswith(b"%PDF-1.7")
        assert b"/FontFile" not in pdf_bytes


def test_both_confirmed_catastrophe_font_subsets_are_reason_coded() -> None:
    pdf_bytes = (CORPUS_ROOT / "catastrophe-recap.pdf").read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == (
        "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
    )

    first = audit_pdf_fonts(pdf_bytes)
    second = audit_pdf_fonts(pdf_bytes)

    assert first == second
    assert first.status == "complete"
    assert first.pages_inspected == 1
    assert first.characters_inspected == 1414
    assert first.font_cache_hit_count >= 1
    assert {finding.font_object_id for finding in first.findings} == {13, 25}
    assert {finding.health for finding in first.findings} == {"suspicious"}

    expected = {
        13: {
            "base_font": "HelveticaNowText-Regular",
            "used": 131,
            "spaces": 128,
            "space_cids": 30,
        },
        25: {
            "base_font": "HelveticaNowText-Bold",
            "used": 19,
            "spaces": 13,
            "space_cids": 8,
        },
    }
    for finding in first.findings:
        counts = finding.confidence_basis
        target = expected[finding.font_object_id]
        assert finding.base_font == target["base_font"]
        assert counts["used_character_count"] == target["used"]
        assert counts["mapped_space_count"] == target["spaces"]
        assert counts["distinct_space_mapped_cids"] == target["space_cids"]
        assert finding.reason_codes == [
            "many_to_one_space_mapping",
            "positive_advance_space_mapping",
        ]
        assert finding.runs
        assert finding.page_indexes == [1]
        for run in finding.runs:
            assert run.page_index == 1
            assert run.mapped_space_count == run.character_count
            assert run.distinct_cids
            for value in (
                run.bbox.x,
                run.bbox.y,
                run.bbox.width,
                run.bbox.height,
            ):
                assert math.isfinite(value)
                assert value >= 0


def test_healthy_finance_type0_fonts_are_not_flagged() -> None:
    pdf_bytes = (CORPUS_ROOT / "finance-10k.pdf").read_bytes()
    assert hashlib.sha256(pdf_bytes).hexdigest() == (
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
    )

    report = audit_pdf_fonts(pdf_bytes)

    assert report.status == "complete"
    assert report.pages_inspected == 3
    assert report.findings == []
    assert report.fonts
    assert {font.classification for font in report.fonts} == {"healthy"}
    assert {font.subtype for font in report.fonts} == {"Type0"}
    assert {font.to_unicode for font in report.fonts} == {"present"}
    assert {font.cid_to_gid for font in report.fonts} == {"non_identity"}
    assert {font.embedded_program for font in report.fonts} == {True}
    assert {font.embedded_program_state for font in report.fonts} == {
        "present"
    }
    assert {font.distinct_space_mapped_cids for font in report.fonts} == {1}


def test_complete_approved_corpus_has_no_unexpected_font_findings() -> None:
    observed: dict[str, tuple[tuple[int | None, tuple[str, ...]], ...]] = {}
    for case_id in EXPECTED_CASE_IDS:
        report = audit_pdf_fonts((CORPUS_ROOT / f"{case_id}.pdf").read_bytes())
        assert report.status == "complete"
        observed[case_id] = tuple(
            (
                finding.font_object_id,
                tuple(finding.reason_codes),
            )
            for finding in report.findings
        )

    assert observed == {
        case_id: (
            (
                13,
                (
                    "many_to_one_space_mapping",
                    "positive_advance_space_mapping",
                ),
            ),
            (
                25,
                (
                    "many_to_one_space_mapping",
                    "positive_advance_space_mapping",
                ),
            ),
        )
        if case_id == "catastrophe-recap"
        else ()
        for case_id in EXPECTED_CASE_IDS
    }


@pytest.mark.parametrize(
    ("fixture_id", "classification", "to_unicode", "cid_to_gid", "embedded"),
    (
        (
            "healthy-winansi-intentional-spaces",
            "healthy",
            "not_applicable",
            "not_applicable",
            False,
        ),
        (
            "type0-missing-tounicode",
            "unresolved",
            "missing",
            "identity",
            False,
        ),
        (
            "type0-nonidentity-cidtogid",
            "healthy",
            "present",
            "non_identity",
            False,
        ),
        (
            "standard14-no-embedded-font",
            "healthy",
            "not_applicable",
            "not_applicable",
            False,
        ),
    ),
)
def test_synthetic_structural_states_are_distinct_without_false_positives(
    fixture_id: str,
    classification: str,
    to_unicode: str,
    cid_to_gid: str,
    embedded: bool,
) -> None:
    report = audit_pdf_fonts(build_fixture(fixture_id))

    assert report.status == "complete"
    assert len(report.fonts) == 1
    font = report.fonts[0]
    assert font.classification == classification
    assert font.to_unicode == to_unicode
    assert font.cid_to_gid == cid_to_gid
    assert font.embedded_program is embedded
    if classification == "unresolved":
        assert [(finding.health, finding.reason_codes) for finding in report.findings] == [
            ("unresolved", ["to_unicode_missing"])
        ]
    else:
        assert report.findings == []


def test_report_is_strict_json_safe_and_never_contains_font_program_bytes() -> None:
    pdf_bytes = (CORPUS_ROOT / "catastrophe-recap.pdf").read_bytes()
    report = audit_pdf_fonts(pdf_bytes)
    payload = report.model_dump(mode="json")
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert FontAuditReport.model_validate(payload) == report
    assert report.source_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert "FontFile" not in serialized
    assert "font_program_bytes" not in serialized
    with pytest.raises(ValueError):
        FontAuditReport.model_validate({**payload, "unexpected": True})


def test_invalid_and_bounded_inputs_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = audit_pdf_fonts(b"")
    malformed = audit_pdf_fonts(b"%PDF-1.7\nnot a document")
    not_bytes = audit_pdf_fonts("not-bytes")  # type: ignore[arg-type]

    assert empty.status == malformed.status == not_bytes.status == "unavailable"
    assert empty.findings == malformed.findings == not_bytes.findings == []
    assert {empty.diagnostics[0].code, malformed.diagnostics[0].code} == {
        "empty_pdf",
        "pdf_audit_failed",
    }
    assert not_bytes.diagnostics[0].code == "invalid_input_type"

    monkeypatch.setattr(font_audit_module, "MAX_INPUT_BYTES", 10)
    oversized = audit_pdf_fonts(b"%PDF-1.7\nxx")
    assert oversized.status == "unavailable"
    assert oversized.diagnostics[0].code == "pdf_size_limit"


def test_character_and_cmap_limits_return_bounded_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = build_fixture("healthy-winansi-intentional-spaces")
    monkeypatch.setattr(
        font_audit_module,
        "MAX_RECORDED_CHARACTERS",
        2,
    )
    truncated = audit_pdf_fonts(healthy)
    assert truncated.status == "partial"
    assert truncated.characters_inspected == 2
    assert [diagnostic.code for diagnostic in truncated.diagnostics] == [
        "character_limit"
    ]

    monkeypatch.setattr(
        font_audit_module,
        "MAX_RECORDED_CHARACTERS",
        500_000,
    )
    monkeypatch.setattr(font_audit_module, "MAX_RAW_CMAP_BYTES", 1)
    bounded_cmap = audit_pdf_fonts(
        build_fixture("type0-nonidentity-cidtogid")
    )
    assert bounded_cmap.status == "unavailable"
    assert {
        diagnostic.code for diagnostic in bounded_cmap.diagnostics
    } == {"page_audit_failed", "to_unicode_stream_limit"}
    assert bounded_cmap.findings == []


def test_audit_deadline_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(font_audit_module, "MAX_AUDIT_SECONDS", -1.0)
    report = audit_pdf_fonts(
        build_fixture("healthy-winansi-intentional-spaces")
    )

    assert report.status == "unavailable"
    assert report.findings == []
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "audit_timeout"
    ]
