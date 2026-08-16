from __future__ import annotations

import json
import struct
import zlib
from types import SimpleNamespace
from typing import Any

import pytest
from pdfminer.pdftypes import PDFStream
from pdfminer.psparser import LIT
from pydantic import ValidationError

from app.services import font_recovery as recovery_module
from app.services.font_audit import audit_pdf_fonts
from app.services.font_recovery import (
    FontRecoveryReport,
    recover_pdf_font_text,
)
from tests.fixtures.phase_02.font_recovery import (
    EXPECTED_RECOVERED_TEXT,
    build_fixture,
    build_synthetic_truetype,
)


def _safe_inputs() -> tuple[bytes, Any]:
    pdf_bytes = build_fixture("safe-identity")
    return pdf_bytes, audit_pdf_fonts(pdf_bytes)


@pytest.mark.parametrize(
    ("fixture_id", "reason_code", "programs_parsed", "characters_inspected"),
    (
        ("used-many-to-one", "embedded_cmap_many_to_one", 1, 8),
        ("ligature", "embedded_cmap_ligature", 1, 8),
        ("bidi-control", "embedded_cmap_unsafe_codepoint", 1, 8),
        ("width-mismatch", "font_advance_mismatch", 1, 8),
        ("nonidentity", "cid_to_gid_non_identity", 0, 0),
        ("missing-program", "embedded_program_missing", 0, 0),
    ),
)
def test_generated_unsafe_variants_fail_closed_with_specific_refusals(
    fixture_id: str,
    reason_code: str,
    programs_parsed: int,
    characters_inspected: int,
) -> None:
    pdf_bytes = build_fixture(fixture_id)
    report = recover_pdf_font_text(pdf_bytes, audit_pdf_fonts(pdf_bytes))

    assert report.status == "complete"
    assert report.fonts_considered == 1
    assert report.fonts_recovered == 0
    assert report.font_programs_parsed == programs_parsed
    assert report.characters_inspected == characters_inspected
    assert report.runs == []
    assert [refusal.reason_code for refusal in report.refusals] == [
        reason_code
    ]
    assert report.diagnostics == []


@pytest.mark.parametrize("fixture_id", ("safe-identity", "unused-alias-control"))
def test_only_used_glyph_ambiguity_controls_recovery(
    fixture_id: str,
) -> None:
    pdf_bytes = build_fixture(fixture_id)

    report = recover_pdf_font_text(pdf_bytes, audit_pdf_fonts(pdf_bytes))

    assert report.status == "complete"
    assert report.fonts_recovered == 1
    assert report.refusals == []
    assert [run.recovered_text for run in report.runs] == [
        EXPECTED_RECOVERED_TEXT
    ]
    assert report.recovered_glyph_count == len(EXPECTED_RECOVERED_TEXT)


def test_report_is_strict_json_and_contains_no_font_program_bytes() -> None:
    pdf_bytes, audit = _safe_inputs()
    report = recover_pdf_font_text(pdf_bytes, audit)

    payload = report.model_dump(mode="json")
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )

    assert FontRecoveryReport.model_validate(payload) == report
    assert "FontFile" not in serialized
    assert "font_program_bytes" not in serialized

    def assert_no_bytes(value: Any) -> None:
        assert not isinstance(value, (bytes, bytearray, memoryview))
        if isinstance(value, dict):
            for child in value.values():
                assert_no_bytes(child)
        elif isinstance(value, list):
            for child in value:
                assert_no_bytes(child)

    assert_no_bytes(payload)
    with pytest.raises(ValidationError):
        FontRecoveryReport.model_validate({**payload, "unexpected": True})


def test_invalid_pdf_and_audit_inputs_return_bounded_unavailable_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit = _safe_inputs()
    incomplete_audit = audit.model_dump(mode="json")
    incomplete_audit["status"] = "partial"

    not_bytes = recover_pdf_font_text("not-bytes", audit)  # type: ignore[arg-type]
    empty = recover_pdf_font_text(b"", audit)
    malformed = recover_pdf_font_text(b"%PDF-1.7\nnot-a-document", audit)
    invalid_audit = recover_pdf_font_text(pdf_bytes, {"unexpected": True})
    wrong_audit_type = recover_pdf_font_text(pdf_bytes, object())  # type: ignore[arg-type]
    incomplete = recover_pdf_font_text(pdf_bytes, incomplete_audit)

    assert not_bytes.diagnostics[0].code == "invalid_input_type"
    assert empty.diagnostics[0].code == "empty_pdf"
    assert malformed.diagnostics[0].code == "audit_source_mismatch"
    assert invalid_audit.diagnostics[0].code == "invalid_audit_report"
    assert wrong_audit_type.diagnostics[0].code == "invalid_audit_report"
    assert incomplete.diagnostics[0].code == "audit_incomplete"
    for report in (
        not_bytes,
        empty,
        malformed,
        invalid_audit,
        wrong_audit_type,
        incomplete,
    ):
        assert report.status == "unavailable"
        assert report.runs == []
        assert report.refusals == []
        assert report.recovered_glyph_count == 0

    monkeypatch.setattr(recovery_module, "MAX_INPUT_BYTES", len(pdf_bytes) - 1)
    oversized = recover_pdf_font_text(pdf_bytes, audit)
    assert oversized.status == "unavailable"
    assert oversized.diagnostics[0].code == "pdf_size_limit"


def test_direct_font_identity_is_refused_before_font_program_parsing() -> None:
    pdf_bytes, audit = _safe_inputs()
    payload = audit.model_dump(mode="json")
    font = payload["fonts"][0]
    finding = payload["findings"][0]
    for record in (font, finding):
        record["font_ref"] = "direct:1"
        record["font_object_id"] = None
        record["object_identity_basis"] = "direct_dictionary"

    report = recover_pdf_font_text(pdf_bytes, payload)

    assert report.status == "complete"
    assert report.fonts_considered == 1
    assert report.fonts_recovered == 0
    assert report.font_programs_parsed == 0
    assert report.pages_inspected == 0
    assert report.characters_inspected == 0
    assert report.runs == []
    assert [refusal.reason_code for refusal in report.refusals] == [
        "direct_font_identity_unsupported"
    ]


def test_stale_safe_audit_cannot_authorize_a_different_healthy_pdf() -> None:
    safe_pdf, safe_audit = _safe_inputs()
    healthy_pdf = build_fixture("healthy-identity")
    healthy_audit = audit_pdf_fonts(healthy_pdf)
    assert safe_pdf != healthy_pdf
    assert healthy_audit.status == "complete"
    assert healthy_audit.findings == []

    report = recover_pdf_font_text(healthy_pdf, safe_audit)

    assert report.status == "unavailable"
    assert report.fonts_considered == 0
    assert report.fonts_recovered == 0
    assert report.font_programs_parsed == 0
    assert report.runs == []
    assert report.refusals == []
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "audit_source_mismatch"
    ]


def test_unbound_audit_report_cannot_authorize_recovery() -> None:
    pdf_bytes, audit = _safe_inputs()
    payload = audit.model_dump(mode="json")
    payload.pop("source_sha256")

    report = recover_pdf_font_text(pdf_bytes, payload)

    assert report.status == "unavailable"
    assert report.font_programs_parsed == 0
    assert report.runs == []
    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "audit_source_unbound"
    ]


def test_unexpected_font_parser_failure_is_sanitized_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit = _safe_inputs()

    def fail_parser(_spec: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("secret-font-byte-marker")

    monkeypatch.setattr(recovery_module, "_extract_true_type", fail_parser)
    report = recover_pdf_font_text(pdf_bytes, audit)
    serialized = json.dumps(report.model_dump(mode="json"))

    assert report.status == "complete"
    assert report.fonts_recovered == 0
    assert report.font_programs_parsed == 0
    assert report.runs == []
    assert [refusal.reason_code for refusal in report.refusals] == [
        "embedded_font_malformed"
    ]
    assert "RuntimeError" in report.refusals[0].message
    assert "secret-font-byte-marker" not in serialized


def test_font_program_raw_decoded_and_filter_bounds_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery_module, "MAX_RAW_FONT_PROGRAM_BYTES", 4)
    with pytest.raises(recovery_module._RecoveryError) as raw_error:
        recovery_module._bounded_font_program(PDFStream({}, b"12345"))
    assert raw_error.value.code == "embedded_program_limit"

    monkeypatch.setattr(recovery_module, "MAX_RAW_FONT_PROGRAM_BYTES", 1_024)
    monkeypatch.setattr(recovery_module, "MAX_DECODED_FONT_PROGRAM_BYTES", 4)
    compressed = PDFStream(
        {"Filter": LIT("FlateDecode")},
        zlib.compress(b"12345"),
    )
    with pytest.raises(recovery_module._RecoveryError) as decoded_error:
        recovery_module._bounded_font_program(compressed)
    assert decoded_error.value.code == "embedded_program_limit"

    malformed = PDFStream({"Filter": LIT("FlateDecode")}, b"not-zlib")
    with pytest.raises(recovery_module._RecoveryError) as malformed_error:
        recovery_module._bounded_font_program(malformed)
    assert malformed_error.value.code == "embedded_program_malformed"

    unsupported = PDFStream({"Filter": LIT("ASCIIHexDecode")}, b"00>")
    with pytest.raises(recovery_module._RecoveryError) as filter_error:
        recovery_module._bounded_font_program(unsupported)
    assert filter_error.value.code == "embedded_program_filter_unsupported"


def test_sfnt_and_cmap_structural_limits_reject_before_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    font_bytes = build_synthetic_truetype()
    monkeypatch.setattr(recovery_module, "MAX_SFNT_TABLES", 1)
    with pytest.raises(recovery_module._RecoveryError) as table_error:
        recovery_module._parse_true_type(font_bytes)
    assert table_error.value.code == "embedded_font_table_limit"

    monkeypatch.setattr(recovery_module, "MAX_CMAP_SUBTABLES", 1)
    two_subtable_header = (
        struct.pack(">HH", 0, 2)
        + struct.pack(">HHI", 3, 10, 20)
        + struct.pack(">HHI", 0, 4, 20)
    )
    with pytest.raises(recovery_module._RecoveryError) as subtable_error:
        recovery_module._parse_unicode_cmap(
            two_subtable_header,
            num_glyphs=2,
        )
    assert subtable_error.value.code == "embedded_cmap_limit"

    monkeypatch.setattr(recovery_module, "MAX_CMAP_MAPPINGS", 1)
    format_12 = (
        struct.pack(">HHIII", 12, 0, 28, 0, 1)
        + struct.pack(">III", ord("A"), ord("B"), 1)
    )
    with pytest.raises(recovery_module._RecoveryError) as mapping_error:
        recovery_module._parse_cmap_format_12(
            format_12,
            num_glyphs=3,
            mapping_limit=1,
        )
    assert mapping_error.value.code == "embedded_cmap_limit"


def test_cmap_mapping_budget_is_cumulative_across_trusted_subtables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def format_12(start: int, glyph_id: int) -> bytes:
        return (
            struct.pack(">HHIII", 12, 0, 28, 0, 1)
            + struct.pack(">III", start, start + 1, glyph_id)
        )

    first_offset = 20
    second_offset = first_offset + 28
    cmap = (
        struct.pack(">HH", 0, 2)
        + struct.pack(">HHI", 3, 10, first_offset)
        + struct.pack(">HHI", 0, 4, second_offset)
        + format_12(ord("A"), 1)
        + format_12(ord("C"), 3)
    )
    monkeypatch.setattr(recovery_module, "MAX_CMAP_MAPPINGS", 2)

    with pytest.raises(recovery_module._RecoveryError) as error:
        recovery_module._parse_unicode_cmap(cmap, num_glyphs=5)

    assert error.value.code == "embedded_cmap_limit"


def test_used_gid_filter_does_not_hide_trusted_subtable_conflicts() -> None:
    def format_12(glyph_id: int) -> bytes:
        return (
            struct.pack(">HHIII", 12, 0, 28, 0, 1)
            + struct.pack(">III", ord("A"), ord("A"), glyph_id)
        )

    first_offset = 20
    second_offset = first_offset + 28
    cmap = (
        struct.pack(">HH", 0, 2)
        + struct.pack(">HHI", 3, 10, first_offset)
        + struct.pack(">HHI", 0, 4, second_offset)
        + format_12(1)
        + format_12(2)
    )

    with pytest.raises(recovery_module._RecoveryError) as conflict_error:
        recovery_module._parse_unicode_cmap(
            cmap,
            num_glyphs=3,
            used_glyph_ids=frozenset({1}),
        )

    assert (
        conflict_error.value.code
        == "embedded_cmap_conflicting_subtables"
    )


def test_compact_cmap_ranges_retain_only_used_glyphs_and_share_budget() -> None:
    groups = b"".join(
        struct.pack(
            ">III",
            start,
            start + 65_533,
            1,
        )
        for start in (0, 0x10000, 0x20000, 0x30000)
    )
    compact = (
        struct.pack(">HHIII", 12, 0, 16 + len(groups), 0, 4)
        + groups
    )
    budget = [recovery_module.MAX_CMAP_MAPPINGS]

    mapping = recovery_module._parse_cmap_format_12(
        compact,
        num_glyphs=65_535,
        mapping_budget=budget,
        used_glyph_ids=frozenset({1, 2, 3, 4}),
    )

    assert len(mapping) == 8
    assert set(mapping.values()) == {1, 2, 3, 4}
    assert budget == [8]

    one_mapping = (
        struct.pack(">HHIII", 12, 0, 28, 0, 1)
        + struct.pack(">III", 0x50000, 0x50008, 1)
    )
    with pytest.raises(recovery_module._RecoveryError) as aggregate_error:
        recovery_module._parse_cmap_format_12(
            one_mapping,
            num_glyphs=16,
            mapping_budget=budget,
            used_glyph_ids=frozenset({1}),
        )
    assert aggregate_error.value.code == "embedded_cmap_limit"


def test_cmap_expansion_checks_deadline_inside_compact_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compact = (
        struct.pack(">HHIII", 12, 0, 40, 0, 2)
        + struct.pack(">III", 0, 1, 1)
        + struct.pack(">III", 2, 3, 3)
    )
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(
        recovery_module,
        "time",
        SimpleNamespace(perf_counter=lambda: next(clock)),
    )

    with pytest.raises(recovery_module._RecoveryError) as timeout_error:
        recovery_module._parse_cmap_format_12(
            compact,
            num_glyphs=5,
            used_glyph_ids=frozenset({1, 2, 3, 4}),
            deadline=1.0,
        )
    assert timeout_error.value.code == "recovery_timeout"


@pytest.mark.parametrize(
    (
        "limit_name",
        "limit_value",
        "diagnostic_code",
        "expected_characters_inspected",
    ),
    (
        ("MAX_RECOVERY_RUNS", 0, "recovery_run_limit", 0),
        ("MAX_RECOVERED_GLYPHS", 3, "recovered_glyph_limit", 3),
    ),
)
def test_recovery_evidence_limits_never_emit_partial_runs(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    diagnostic_code: str,
    expected_characters_inspected: int,
) -> None:
    pdf_bytes, audit = _safe_inputs()
    monkeypatch.setattr(recovery_module, limit_name, limit_value)

    report = recover_pdf_font_text(pdf_bytes, audit)

    assert report.status == "partial"
    assert report.runs == []
    assert report.recovered_glyph_count == 0
    assert report.characters_inspected == expected_characters_inspected
    assert report.font_programs_parsed == 0
    assert diagnostic_code in {
        diagnostic.code for diagnostic in report.diagnostics
    }


def test_eligible_font_count_and_deadline_bounds_stop_before_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit = _safe_inputs()

    monkeypatch.setattr(recovery_module, "MAX_FONT_OBJECTS", 0)
    over_font_limit = recover_pdf_font_text(pdf_bytes, audit)
    assert over_font_limit.status == "unavailable"
    assert over_font_limit.diagnostics[0].code == "font_object_limit"
    assert over_font_limit.runs == []

    monkeypatch.setattr(recovery_module, "MAX_FONT_OBJECTS", 256)
    clock_values = iter((0.0, 6.0))
    monkeypatch.setattr(
        recovery_module,
        "time",
        SimpleNamespace(perf_counter=lambda: next(clock_values)),
    )
    timed_out = recover_pdf_font_text(pdf_bytes, audit)
    assert timed_out.status == "partial"
    assert timed_out.runs == []
    assert timed_out.font_programs_parsed == 0
    assert "recovery_timeout" in {
        diagnostic.code for diagnostic in timed_out.diagnostics
    }
