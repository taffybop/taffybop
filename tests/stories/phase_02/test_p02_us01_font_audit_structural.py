from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence

import pytest
from pdfminer.pdftypes import PDFStream

from app.services.font_audit import audit_pdf_fonts


_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_FONT_PROGRAM_BYTES = (
    b"P02-US01-EMBEDDED-PROGRAM-MUST-NOT-BE-DECODED-OR-RETAINED"
)
_TO_UNICODE_CMAP = b"\n".join(
    (
        b"/CIDInit /ProcSet findresource begin",
        b"12 dict begin",
        b"begincmap",
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
        b"/Supplement 0 >> def",
        b"/CMapName /StructuralAudit-ToUnicode def",
        b"/CMapType 2 def",
        b"1 begincodespacerange",
        b"<0000> <FFFF>",
        b"endcodespacerange",
        b"2 beginbfchar",
        b"<0001> <0041>",
        b"<0002> <0042>",
        b"endbfchar",
        b"endcmap",
        b"CMapName currentdict /CMap defineresource pop",
        b"end",
        b"end",
    )
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

    xref_offset = cursor
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
                + b" /Root 1 0 R >>\n"
            ),
            b"startxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        )
    )
    return b"".join(parts)


def _type0_pdf(
    cid_to_gid_bytes: bytes,
    *,
    to_unicode_cmap: bytes = _TO_UNICODE_CMAP,
    font_file_entry: bytes | None = None,
    font_file_object: bytes = b"null",
) -> bytes:
    descriptor = (
        b"<< /Type /FontDescriptor /FontName /StructuralAudit "
        b"/Flags 4 /FontBBox [0 -200 1000 900] /ItalicAngle 0 "
        b"/Ascent 800 /Descent -200 /CapHeight 700 /StemV 80"
    )
    if font_file_entry is not None:
        descriptor += b" /FontFile2 " + font_file_entry
    descriptor += b" >>"

    return _assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 5 0 R >> >> "
                b"/Contents 4 0 R >>"
            ),
            _stream(b"BT\n/F1 20 Tf\n72 720 Td\n<00010002> Tj\nET"),
            (
                b"<< /Type /Font /Subtype /Type0 "
                b"/BaseFont /StructuralAudit /Encoding /Identity-H "
                b"/DescendantFonts [6 0 R] /ToUnicode 8 0 R >>"
            ),
            (
                b"<< /Type /Font /Subtype /CIDFontType2 "
                b"/BaseFont /StructuralAudit "
                b"/CIDSystemInfo << /Registry (Adobe) "
                b"/Ordering (Identity) /Supplement 0 >> "
                b"/FontDescriptor 7 0 R /DW 1000 "
                b"/W [1 [600 600]] /CIDToGIDMap 9 0 R >>"
            ),
            descriptor,
            _stream(to_unicode_cmap),
            _stream(cid_to_gid_bytes),
            font_file_object,
        )
    )


@pytest.mark.parametrize(
    ("cid_to_gid_bytes", "expected_state"),
    (
        pytest.param(
            # Used CIDs 1 and 2 map to equal GIDs. The odd trailing byte is
            # outside those used entries and must not make bounded inspection
            # classify their complete values as malformed.
            b"\x00\x00\x00\x01\x00\x02\xff",
            "identity",
            id="identity-valued-stream-for-used-cids",
        ),
        pytest.param(
            b"\x00\x00\x00\x05\x00\x03",
            "non_identity",
            id="non-identity-stream-for-used-cids",
        ),
        pytest.param(
            # CID 2 is used, but only its first big-endian uint16 byte exists.
            b"\x00\x00\x00\x01\x00",
            "malformed",
            id="truncated-stream-at-used-cid",
        ),
    ),
)
def test_cid_to_gid_stream_is_inspected_for_used_cids(
    cid_to_gid_bytes: bytes,
    expected_state: str,
) -> None:
    report = audit_pdf_fonts(_type0_pdf(cid_to_gid_bytes))

    assert report.status == "complete"
    assert len(report.fonts) == 1
    font = report.fonts[0]
    assert font.used_character_count == 2
    assert font.distinct_used_cids == 2
    assert font.cid_to_gid == expected_state
    assert font.cid_to_gid != "stream"


def test_conflicting_to_unicode_definitions_are_explicitly_unresolved() -> None:
    ambiguous_cmap = _TO_UNICODE_CMAP.replace(
        b"2 beginbfchar\n<0001> <0041>\n<0002> <0042>",
        (
            b"3 beginbfchar\n"
            b"<0001> <0041>\n"
            b"<0001> <0042>\n"
            b"<0002> <0042>"
        ),
    )

    report = audit_pdf_fonts(
        _type0_pdf(
            b"\x00\x00\x00\x01\x00\x02",
            to_unicode_cmap=ambiguous_cmap,
        )
    )

    assert report.status == "complete"
    assert len(report.fonts) == 1
    assert report.fonts[0].to_unicode == "ambiguous"
    assert report.fonts[0].classification == "unresolved"
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.health == "unresolved"
    assert finding.reason_codes == ["to_unicode_ambiguous"]
    assert finding.confidence_basis[
        "to_unicode_ambiguous_used_cids"
    ] == [1]


@pytest.mark.parametrize(
    (
        "font_file_entry",
        "font_file_object",
        "expected_available",
        "expected_state",
    ),
    (
        pytest.param(
            b"10 0 R",
            _stream(_FONT_PROGRAM_BYTES),
            True,
            "present",
            id="resolvable-pdf-stream",
        ),
        pytest.param(
            None,
            b"null",
            False,
            "missing",
            id="missing-entry",
        ),
        pytest.param(
            b"99 0 R",
            b"null",
            False,
            "dangling",
            id="dangling-reference",
        ),
        pytest.param(
            b"10 0 R",
            b"<< /Length 123 /NotAStream true >>",
            False,
            "non_stream",
            id="resolved-non-stream-object",
        ),
    ),
)
def test_embedded_program_requires_a_resolvable_pdf_stream(
    monkeypatch: pytest.MonkeyPatch,
    font_file_entry: bytes | None,
    font_file_object: bytes,
    expected_available: bool,
    expected_state: str,
) -> None:
    original_decode: Callable[[PDFStream], None] = PDFStream.decode

    def reject_font_program_decode(stream: PDFStream) -> None:
        if stream.get_rawdata() == _FONT_PROGRAM_BYTES:
            pytest.fail("font audit decoded the embedded font program")
        original_decode(stream)

    monkeypatch.setattr(PDFStream, "decode", reject_font_program_decode)
    report = audit_pdf_fonts(
        _type0_pdf(
            b"\x00\x00\x00\x01\x00\x02",
            font_file_entry=font_file_entry,
            font_file_object=font_file_object,
        )
    )

    assert report.status == "complete"
    assert len(report.fonts) == 1
    font = report.fonts[0]
    assert font.embedded_program is expected_available
    assert font.embedded_program_state == expected_state

    serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    forbidden_representations = (
        _FONT_PROGRAM_BYTES.decode("ascii"),
        _FONT_PROGRAM_BYTES.hex(),
        base64.b64encode(_FONT_PROGRAM_BYTES).decode("ascii"),
    )
    assert all(value not in serialized for value in forbidden_representations)
