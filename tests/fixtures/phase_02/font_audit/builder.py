"""Byte-stable builders for the Phase 2 font-audit PDF fixtures.

The module deliberately writes a small, conventional PDF syntax itself. This
avoids generator timestamps, random document IDs, platform-specific font
subsetting, and any dependency on copied font programs.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Sequence
from types import MappingProxyType

from .registry import FIXTURES, FIXTURES_BY_ID


_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_DOCUMENT_ID = b"434c4541524c45414646495854555245"
_PAGE_DICTIONARY = (
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
    b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
)


class FixtureIntegrityError(RuntimeError):
    """Raised when generated fixture bytes or reader checks drift."""


def _stream(data: bytes, *, entries: bytes = b"") -> bytes:
    """Return a PDF stream object body with an exact direct length."""

    prefix = b"<<"
    if entries:
        prefix += b" " + entries.strip()
    prefix += b" /Length " + str(len(data)).encode("ascii") + b" >>"
    return prefix + b"\nstream\n" + data + b"\nendstream"


def _assemble_pdf(objects: Sequence[bytes]) -> bytes:
    """Serialize indirect objects with fixed ordering and a classic xref."""

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
        [
            f"xref\n0 {len(objects) + 1}\n".encode("ascii"),
            b"0000000000 65535 f \n",
            *(
                f"{offset:010d} 00000 n \n".encode("ascii")
                for offset in offsets[1:]
            ),
            (
                b"trailer\n<< /Size "
                + str(len(objects) + 1).encode("ascii")
                + b" /Root 1 0 R /ID [<"
                + _DOCUMENT_ID
                + b"><"
                + _DOCUMENT_ID
                + b">] >>\n"
            ),
            b"startxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        ]
    )
    return b"".join(parts)


def _single_page_objects(content: bytes, *font_objects: bytes) -> tuple[bytes, ...]:
    """Return the common catalog/page objects plus caller-supplied fonts."""

    return (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _PAGE_DICTIONARY,
        _stream(content),
        *font_objects,
    )


def _build_healthy_winansi_intentional_spaces() -> bytes:
    content = b"BT\n/F1 20 Tf\n72 720 Td\n(ALPHA BETA) Tj\nET"
    font = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    return _assemble_pdf(_single_page_objects(content, font))


def _cid_font_descriptor(base_font: bytes) -> bytes:
    return (
        b"<< /Type /FontDescriptor /FontName /"
        + base_font
        + b" /Flags 4 /FontBBox [0 -200 1000 900] /ItalicAngle 0 "
        b"/Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 >>"
    )


def _type0_font(*, base_font: bytes, to_unicode_object: int | None) -> bytes:
    body = (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /"
        + base_font
        + b" /Encoding /Identity-H /DescendantFonts [6 0 R]"
    )
    if to_unicode_object is not None:
        body += b" /ToUnicode " + str(to_unicode_object).encode("ascii") + b" 0 R"
    return body + b" >>"


def _cid_font(
    *,
    base_font: bytes,
    cid_to_gid: bytes,
    widths: bytes,
) -> bytes:
    return (
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /"
        + base_font
        + b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        b"/Supplement 0 >> /FontDescriptor 7 0 R /DW 1000 /W "
        + widths
        + b" /CIDToGIDMap "
        + cid_to_gid
        + b" >>"
    )


def _build_type0_missing_tounicode() -> bytes:
    base_font = b"SyntheticMissingMap"
    content = b"BT\n/F1 20 Tf\n72 720 Td\n<000100020003> Tj\nET"
    type0 = _type0_font(base_font=base_font, to_unicode_object=None)
    descendant = _cid_font(
        base_font=base_font,
        cid_to_gid=b"/Identity",
        widths=b"[1 [600 600 600]]",
    )
    descriptor = _cid_font_descriptor(base_font)
    return _assemble_pdf(
        _single_page_objects(content, type0, descendant, descriptor)
    )


_TO_UNICODE_CMAP = b"\n".join(
    (
        b"/CIDInit /ProcSet findresource begin",
        b"12 dict begin",
        b"begincmap",
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        b"/CMapName /SyntheticNonIdentity-ToUnicode def",
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


def _build_type0_nonidentity_cidtogid() -> bytes:
    base_font = b"SyntheticNonIdentity"
    content = b"BT\n/F1 20 Tf\n72 720 Td\n<00010002> Tj\nET"
    type0 = _type0_font(base_font=base_font, to_unicode_object=8)
    descendant = _cid_font(
        base_font=base_font,
        cid_to_gid=b"9 0 R",
        widths=b"[1 [600 600]]",
    )
    descriptor = _cid_font_descriptor(base_font)
    # Big-endian uint16 entries for CID 0, 1, and 2 map to GIDs 0, 5, and 3.
    cid_to_gid_map = b"\x00\x00\x00\x05\x00\x03"
    return _assemble_pdf(
        _single_page_objects(
            content,
            type0,
            descendant,
            descriptor,
            _stream(_TO_UNICODE_CMAP),
            _stream(cid_to_gid_map),
        )
    )


def _build_standard14_no_embedded_font() -> bytes:
    content = b"BT\n/F1 20 Tf\n72 720 Td\n(STANDARD FOURTEEN) Tj\nET"
    # Times-Roman is one of PDF's Standard 14 fonts. It correctly has neither
    # a FontDescriptor nor FontFile/FontFile2/FontFile3 program.
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>"
    return _assemble_pdf(_single_page_objects(content, font))


_BUILDERS: MappingProxyType[str, Callable[[], bytes]] = MappingProxyType(
    {
        "healthy-winansi-intentional-spaces": (
            _build_healthy_winansi_intentional_spaces
        ),
        "type0-missing-tounicode": _build_type0_missing_tounicode,
        "type0-nonidentity-cidtogid": _build_type0_nonidentity_cidtogid,
        "standard14-no-embedded-font": _build_standard14_no_embedded_font,
    }
)


def build_fixture(fixture_id: str) -> bytes:
    """Build one registered fixture entirely in memory.

    Raises:
        KeyError: if ``fixture_id`` is not registered.
    """

    if fixture_id not in FIXTURES_BY_ID:
        raise KeyError(
            f"unknown font-audit fixture {fixture_id!r}; "
            f"expected one of {tuple(FIXTURES_BY_ID)}"
        )
    return _BUILDERS[fixture_id]()


def build_all_fixtures() -> dict[str, bytes]:
    """Return freshly generated bytes for every fixture in registry order."""

    return {
        fixture.fixture_id: build_fixture(fixture.fixture_id)
        for fixture in FIXTURES
    }


def fixture_hashes() -> dict[str, str]:
    """Return freshly calculated SHA-256 identities in registry order."""

    return {
        fixture_id: hashlib.sha256(pdf_bytes).hexdigest()
        for fixture_id, pdf_bytes in build_all_fixtures().items()
    }


def _verify_with_pdfminer(pdf_bytes: bytes, fixture_id: str) -> str:
    from pdfminer.high_level import extract_text

    try:
        return extract_text(io.BytesIO(pdf_bytes)).strip()
    except Exception as exc:  # pragma: no cover - dependency error detail
        raise FixtureIntegrityError(
            f"pdfminer could not open {fixture_id}: {exc}"
        ) from exc


def _verify_with_pdfium(pdf_bytes: bytes, fixture_id: str) -> str:
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        try:
            if len(document) != 1:
                raise FixtureIntegrityError(
                    f"{fixture_id} has {len(document)} pages; expected 1"
                )
            page = document[0]
            try:
                text_page = page.get_textpage()
                try:
                    native_text = text_page.get_text_range()
                finally:
                    text_page.close()
                bitmap = page.render(scale=0.25)
                try:
                    bitmap.to_pil()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
        return native_text
    except FixtureIntegrityError:
        raise
    except Exception as exc:  # pragma: no cover - dependency error detail
        raise FixtureIntegrityError(
            f"pypdfium2 could not open/render {fixture_id}: {exc}"
        ) from exc


def self_check(*, verify_readers: bool = True) -> dict[str, str]:
    """Verify registry coverage, byte determinism, hashes, and PDF readers.

    Reader checks exercise the project's pinned ``pdfminer.six`` and
    ``pypdfium2`` packages. Pass ``verify_readers=False`` for the dependency-free
    determinism/hash check.
    """

    registered_ids = tuple(fixture.fixture_id for fixture in FIXTURES)
    if set(registered_ids) != set(_BUILDERS):
        raise FixtureIntegrityError(
            "fixture registry and builder keys do not match"
        )

    actual_hashes: dict[str, str] = {}
    for fixture in FIXTURES:
        first = build_fixture(fixture.fixture_id)
        second = build_fixture(fixture.fixture_id)
        if first != second:
            raise FixtureIntegrityError(
                f"{fixture.fixture_id} did not regenerate byte-identically"
            )
        if b"/FontFile" in first:
            raise FixtureIntegrityError(
                f"{fixture.fixture_id} unexpectedly embeds a font program"
            )

        actual_hash = hashlib.sha256(first).hexdigest()
        if actual_hash != fixture.sha256:
            raise FixtureIntegrityError(
                f"{fixture.fixture_id} hash drift: expected {fixture.sha256}, "
                f"got {actual_hash}"
            )
        actual_hashes[fixture.fixture_id] = actual_hash

        if verify_readers:
            pdfminer_text = _verify_with_pdfminer(first, fixture.fixture_id)
            pdfium_text = _verify_with_pdfium(first, fixture.fixture_id)
            if fixture.expected_native_text is not None:
                for reader, native_text in (
                    ("pdfminer", pdfminer_text),
                    ("pypdfium2", pdfium_text),
                ):
                    if native_text != fixture.expected_native_text:
                        raise FixtureIntegrityError(
                            f"{reader} extracted {native_text!r} from "
                            f"{fixture.fixture_id}; expected "
                            f"{fixture.expected_native_text!r}"
                        )

    return actual_hashes


if __name__ == "__main__":
    for name, digest in self_check().items():
        print(f"{name} {digest}")
