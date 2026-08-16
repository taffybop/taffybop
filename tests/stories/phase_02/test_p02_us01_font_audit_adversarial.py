from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import font_audit as font_audit_module
from app.services.font_audit import audit_pdf_fonts


_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_TYPE1_FONT = (
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    b"/Encoding /WinAnsiEncoding >>"
)


def _stream(data: bytes) -> bytes:
    return (
        b"<< /Length "
        + str(len(data)).encode("ascii")
        + b" >>\nstream\n"
        + data
        + b"\nendstream"
    )


def _assemble_pdf(objects: Sequence[bytes]) -> bytes:
    parts = [_PDF_HEADER]
    offsets = [0]
    cursor = len(_PDF_HEADER)

    for object_number, body in enumerate(objects, start=1):
        serialized = (
            f"{object_number} 0 obj\n".encode("ascii")
            + body
            + b"\nendobj\n"
        )
        offsets.append(cursor)
        parts.append(serialized)
        cursor += len(serialized)

    parts.extend(
        (
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
            *(
                f"{offset:010d} 00000 n \n".encode("ascii")
                for offset in offsets[1:]
            ),
            (
                b"trailer\n<< /Size "
                + str(len(objects) + 1).encode("ascii")
                + b" /Root 1 0 R >>\nstartxref\n"
            ),
            str(cursor).encode("ascii"),
            b"\n%%EOF\n",
        )
    )
    return b"".join(parts)


def _one_page_pdf(
    *,
    content: bytes,
    font_resources: bytes,
    font_objects: Sequence[bytes] = (),
) -> bytes:
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << "
        + font_resources
        + b" >> >> /Contents 4 0 R >>"
    )
    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page,
            _stream(content),
            *font_objects,
        )
    )


def test_used_direct_font_dictionary_cannot_silently_pass_zero_font_audit() -> None:
    pdf_bytes = _one_page_pdf(
        content=b"BT\n/F1 20 Tf\n72 720 Td\n(DIRECT FONT) Tj\nET",
        font_resources=b"/F1 " + _TYPE1_FONT,
    )

    report = audit_pdf_fonts(pdf_bytes)

    assert report.status == "complete"
    assert report.fonts_inspected == 1
    assert report.diagnostics == []
    font = report.fonts[0]
    assert font.font_ref == "direct:1"
    assert font.font_object_id is None
    assert font.object_identity_basis == "direct_dictionary"
    assert font.classification == "healthy"
    assert font.used_character_count == len("DIRECT FONT")


def test_processing_after_retained_character_cap_stops_or_obeys_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes = _one_page_pdf(
        content=(
            b"BT\n/F1 20 Tf\n72 720 Td\n("
            + (b"A" * 600)
            + b") Tj\nET"
        ),
        font_resources=b"/F1 5 0 R",
        font_objects=(_TYPE1_FONT,),
    )
    clock_calls = 0
    render_calls = 0
    original_render_char = font_audit_module._AuditDevice.render_char

    def expiring_perf_counter() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls <= 4 else 10.0

    def counting_render_char(*args: Any, **kwargs: Any) -> float:
        nonlocal render_calls
        render_calls += 1
        return original_render_char(*args, **kwargs)

    monkeypatch.setattr(font_audit_module, "MAX_RECORDED_CHARACTERS", 1)
    monkeypatch.setattr(font_audit_module, "MAX_AUDIT_SECONDS", 1.0)
    monkeypatch.setattr(
        font_audit_module._AuditDevice,
        "render_char",
        counting_render_char,
    )
    monkeypatch.setattr(
        font_audit_module,
        "time",
        SimpleNamespace(perf_counter=expiring_perf_counter),
    )

    report = audit_pdf_fonts(pdf_bytes)

    diagnostic_codes = {
        diagnostic.code for diagnostic in report.diagnostics
    }
    processing_stopped_at_cap = render_calls <= 2
    deadline_stopped_post_cap_processing = "audit_timeout" in diagnostic_codes
    assert processing_stopped_at_cap or deadline_stopped_post_cap_processing
    assert diagnostic_codes & {"character_limit", "audit_timeout"}
    assert report.status in {"partial", "unavailable"}
    assert report.characters_inspected <= 1


def test_excess_font_objects_are_not_passed_to_underlying_font_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    font_limit = 2
    font_count = 8
    font_resources = b" ".join(
        f"/F{index} {index + 4} 0 R".encode("ascii")
        for index in range(1, font_count + 1)
    )
    pdf_bytes = _one_page_pdf(
        content=b"BT\n/F1 20 Tf\n72 720 Td\n(BOUNDED FONTS) Tj\nET",
        font_resources=font_resources,
        font_objects=tuple(_TYPE1_FONT for _ in range(font_count)),
    )
    parsed_object_ids: list[object] = []
    original_get_font = font_audit_module.PDFResourceManager.get_font

    def counting_get_font(
        resource_manager: Any,
        object_id: object,
        spec: Any,
    ) -> Any:
        parsed_object_ids.append(object_id)
        return original_get_font(resource_manager, object_id, spec)

    monkeypatch.setattr(font_audit_module, "MAX_FONT_OBJECTS", font_limit)
    monkeypatch.setattr(
        font_audit_module.PDFResourceManager,
        "get_font",
        counting_get_font,
    )

    report = audit_pdf_fonts(pdf_bytes)

    assert "font_object_limit" in {
        diagnostic.code for diagnostic in report.diagnostics
    }
    assert report.status in {"partial", "unavailable"}
    assert len(parsed_object_ids) <= font_limit
