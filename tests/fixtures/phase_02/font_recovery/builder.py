"""Byte-stable synthetic TrueType and Type0 PDF recovery fixtures.

Every font program in this module is assembled from primitive table values in
memory. No extracted, downloaded, or third-party font bytes are used or
persisted.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType


_PDF_HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
_DOCUMENT_ID = b"503032464f4e545245434f56455259"
_CONTENT_CIDS = (1, 2, 3, 4, 1, 2, 3, 4)
EXPECTED_RECOVERED_TEXT = "ABCDABCD"


class FixtureIntegrityError(RuntimeError):
    """Raised when generated recovery fixtures are invalid or drift."""


@dataclass(frozen=True, slots=True)
class _FixtureSpec:
    fixture_id: str
    purpose: str
    unicode_to_gid: tuple[tuple[int, int], ...]
    embedded_program: bool = True
    cid_to_gid: tuple[int, ...] | None = None
    pdf_width_overrides: tuple[tuple[int, int], ...] = ()
    to_unicode_mapping: tuple[tuple[int, int], ...] = ()


_SAFE_MAPPING = (
    (ord("A"), 1),
    (ord("B"), 2),
    (ord("C"), 3),
    (ord("D"), 4),
)

_FIXTURES = (
    _FixtureSpec(
        fixture_id="safe-identity",
        purpose=(
            "Used CIDs equal GIDs, all used glyphs invert one-to-one, and PDF "
            "widths exactly match the generated TrueType hmtx table."
        ),
        unicode_to_gid=_SAFE_MAPPING,
    ),
    _FixtureSpec(
        fixture_id="healthy-identity",
        purpose=(
            "The live Type0 font is structurally recovery-compatible but its "
            "ToUnicode mapping is already healthy, providing a cross-PDF "
            "stale-audit negative control."
        ),
        unicode_to_gid=_SAFE_MAPPING,
        to_unicode_mapping=(
            (1, ord("A")),
            (2, ord("B")),
            (3, ord("C")),
            (4, ord("D")),
        ),
    ),
    _FixtureSpec(
        fixture_id="used-many-to-one",
        purpose=(
            "The used GID 1 has two Unicode candidates (Latin A and Greek "
            "capital alpha), so recovery must refuse that used glyph."
        ),
        unicode_to_gid=(
            *_SAFE_MAPPING,
            (0x0391, 1),
        ),
    ),
    _FixtureSpec(
        fixture_id="unused-alias-control",
        purpose=(
            "An unused GID has quote aliases while every used glyph remains "
            "one-to-one; unused ambiguity must not block safe recovery."
        ),
        unicode_to_gid=(
            (0x0022, 5),
            *_SAFE_MAPPING,
            (0x2033, 5),
        ),
    ),
    _FixtureSpec(
        fixture_id="ligature",
        purpose=(
            "Used GID 1 maps to the Unicode fi ligature and must follow the "
            "story's conservative ligature refusal path."
        ),
        unicode_to_gid=(
            (0xFB01, 1),
            (ord("B"), 2),
            (ord("C"), 3),
            (ord("D"), 4),
        ),
    ),
    _FixtureSpec(
        fixture_id="bidi-control",
        purpose=(
            "Used GID 1 maps to U+202E RIGHT-TO-LEFT OVERRIDE and must be "
            "refused before recovered text can reach public output."
        ),
        unicode_to_gid=(
            (0x202E, 1),
            (ord("B"), 2),
            (ord("C"), 3),
            (ord("D"), 4),
        ),
    ),
    _FixtureSpec(
        fixture_id="width-mismatch",
        purpose=(
            "The PDF declares a width for CID 1 that disagrees with the "
            "generated TrueType hmtx advance."
        ),
        unicode_to_gid=_SAFE_MAPPING,
        pdf_width_overrides=((1, 777),),
    ),
    _FixtureSpec(
        fixture_id="nonidentity",
        purpose=(
            "A CIDToGIDMap stream swaps used CIDs 1 and 2 instead of using "
            "the required identity mapping."
        ),
        unicode_to_gid=_SAFE_MAPPING,
        cid_to_gid=(0, 2, 1, 3, 4),
    ),
    _FixtureSpec(
        fixture_id="missing-program",
        purpose=(
            "The identity Type0 font has no FontFile2 entry and therefore no "
            "embedded cmap evidence to recover from."
        ),
        unicode_to_gid=_SAFE_MAPPING,
        embedded_program=False,
    ),
)

_FIXTURES_BY_ID = MappingProxyType(
    {fixture.fixture_id: fixture for fixture in _FIXTURES}
)
FIXTURE_IDS = tuple(_FIXTURES_BY_ID)


def _uint32_checksum(data: bytes) -> int:
    padded = data + b"\0" * ((-len(data)) % 4)
    return sum(
        struct.unpack(f">{len(padded) // 4}I", padded)
    ) & 0xFFFFFFFF


def _search_parameters(table_count: int) -> tuple[int, int, int]:
    largest_power = 1 << int(math.log2(table_count))
    search_range = largest_power * 16
    entry_selector = int(math.log2(largest_power))
    range_shift = table_count * 16 - search_range
    return search_range, entry_selector, range_shift


def _cmap_table(unicode_to_gid: Sequence[tuple[int, int]]) -> bytes:
    """Build one Unicode format-12 cmap with literal one-codepoint groups."""

    ordered = sorted(unicode_to_gid)
    if len({codepoint for codepoint, _gid in ordered}) != len(ordered):
        raise FixtureIntegrityError("cmap repeats a Unicode code point")
    groups = b"".join(
        struct.pack(">III", codepoint, codepoint, gid)
        for codepoint, gid in ordered
    )
    subtable = struct.pack(
        ">HHIII",
        12,
        0,
        16 + len(groups),
        0,
        len(ordered),
    ) + groups
    # Windows platform, full Unicode repertoire.
    return struct.pack(">HHHHI", 0, 1, 3, 10, 12) + subtable


def _head_table() -> bytes:
    return struct.pack(
        ">HHIIIHHqqhhhhHHhhh",
        1,
        0,
        0x00010000,
        0,  # checkSumAdjustment is patched after assembly.
        0x5F0F3CF5,
        0,
        1000,
        0,
        0,
        0,
        0,
        1000,
        1000,
        0,
        8,
        2,
        0,  # short loca offsets
        0,
    )


def _hhea_table(number_of_h_metrics: int, maximum_width: int) -> bytes:
    values = (
        struct.pack(">HH", 1, 0)
        + struct.pack(">hhhH", 800, -200, 0, maximum_width)
        + struct.pack(">hhhh", 0, 0, maximum_width, 1)
        + struct.pack(">hh", 0, 0)
        + struct.pack(">hhhh", 0, 0, 0, 0)
        + struct.pack(">hH", 0, number_of_h_metrics)
    )
    if len(values) != 36:
        raise FixtureIntegrityError("generated hhea table has wrong size")
    return values


def _maxp_table(number_of_glyphs: int) -> bytes:
    return struct.pack(
        ">IH13H",
        0x00010000,
        number_of_glyphs,
        *([0] * 13),
    )


def _post_table() -> bytes:
    # PostScript format 3 carries no copied glyph-name strings.
    return struct.pack(">IihhIIIII", 0x00030000, 0, 0, 0, 0, 0, 0, 0, 0)


def _glyph_tables(
    number_of_glyphs: int,
) -> tuple[bytes, bytes]:
    # Each glyph is a byte-stable empty simple glyph: a zero bbox, zero
    # contours, and a zero instruction length. No TrueType instructions exist.
    empty_glyph = struct.pack(">hhhhhH", 0, 0, 0, 0, 0, 0)
    glyf = empty_glyph * number_of_glyphs
    offsets = tuple(
        (index * len(empty_glyph)) // 2
        for index in range(number_of_glyphs + 1)
    )
    loca = struct.pack(f">{len(offsets)}H", *offsets)
    return glyf, loca


def _font_widths(number_of_glyphs: int) -> tuple[int, ...]:
    return tuple(500 + 20 * glyph_id for glyph_id in range(number_of_glyphs))


def _assemble_sfnt(tables: Mapping[bytes, bytes]) -> bytes:
    ordered = sorted(tables.items())
    table_count = len(ordered)
    search_range, entry_selector, range_shift = _search_parameters(table_count)
    header = struct.pack(
        ">IHHHH",
        0x00010000,
        table_count,
        search_range,
        entry_selector,
        range_shift,
    )
    cursor = len(header) + table_count * 16
    directory: list[bytes] = []
    bodies: list[bytes] = []
    offsets: dict[bytes, int] = {}
    for tag, body in ordered:
        if len(tag) != 4:
            raise FixtureIntegrityError("SFNT table tags must be four bytes")
        offsets[tag] = cursor
        directory.append(
            struct.pack(
                ">4sIII",
                tag,
                _uint32_checksum(body),
                cursor,
                len(body),
            )
        )
        padded = body + b"\0" * ((-len(body)) % 4)
        bodies.append(padded)
        cursor += len(padded)

    font = bytearray(header + b"".join(directory) + b"".join(bodies))
    head_offset = offsets[b"head"]
    adjustment = (
        0xB1B0AFBA - _uint32_checksum(bytes(font))
    ) & 0xFFFFFFFF
    struct.pack_into(">I", font, head_offset + 8, adjustment)
    if _uint32_checksum(bytes(font)) != 0xB1B0AFBA:
        raise FixtureIntegrityError("SFNT checksum adjustment is invalid")
    return bytes(font)


def _font_program(spec: _FixtureSpec) -> bytes:
    highest_gid = max(
        (gid for _codepoint, gid in spec.unicode_to_gid),
        default=0,
    )
    number_of_glyphs = highest_gid + 1
    widths = _font_widths(number_of_glyphs)
    glyf, loca = _glyph_tables(number_of_glyphs)
    hmtx = b"".join(
        struct.pack(">Hh", width, 0) for width in widths
    )
    return _assemble_sfnt(
        {
            b"cmap": _cmap_table(spec.unicode_to_gid),
            b"glyf": glyf,
            b"head": _head_table(),
            b"hhea": _hhea_table(number_of_glyphs, max(widths)),
            b"hmtx": hmtx,
            b"loca": loca,
            b"maxp": _maxp_table(number_of_glyphs),
            b"post": _post_table(),
        }
    )


def build_synthetic_truetype(fixture_id: str = "safe-identity") -> bytes:
    """Return a newly assembled synthetic TrueType program for one variant."""

    try:
        spec = _FIXTURES_BY_ID[fixture_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown font-recovery fixture {fixture_id!r}; "
            f"expected one of {FIXTURE_IDS}"
        ) from exc
    return _font_program(spec)


def _stream(data: bytes, *, entries: bytes = b"") -> bytes:
    prefix = b"<<"
    if entries:
        prefix += b" " + entries.strip()
    prefix += b" /Length " + str(len(data)).encode("ascii") + b" >>"
    return prefix + b"\nstream\n" + data + b"\nendstream"


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
                + b" /Root 1 0 R /ID [<"
                + _DOCUMENT_ID
                + b"><"
                + _DOCUMENT_ID
                + b">] >>\n"
            ),
            b"startxref\n",
            str(xref_offset).encode("ascii"),
            b"\n%%EOF\n",
        )
    )
    return b"".join(parts)


def _to_unicode_cmap(
    cids: Sequence[int],
    unicode_mapping: Sequence[tuple[int, int]] = (),
) -> bytes:
    mapped = dict(unicode_mapping)
    entries = b"\n".join(
        (
            f"<{cid:04X}> <{mapped.get(cid, 0x20):04X}>".encode("ascii")
        )
        for cid in sorted(set(cids))
    )
    return b"\n".join(
        (
            b"/CIDInit /ProcSet findresource begin",
            b"12 dict begin",
            b"begincmap",
            (
                b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
                b"/Supplement 0 >> def"
            ),
            b"/CMapName /SyntheticRecovery-ToUnicode def",
            b"/CMapType 2 def",
            b"1 begincodespacerange",
            b"<0000> <FFFF>",
            b"endcodespacerange",
            f"{len(set(cids))} beginbfchar".encode("ascii"),
            entries,
            b"endbfchar",
            b"endcmap",
            b"CMapName currentdict /CMap defineresource pop",
            b"end",
            b"end",
        )
    )


def _pdf_widths(spec: _FixtureSpec) -> tuple[int, ...]:
    number_of_glyphs = (
        max(gid for _codepoint, gid in spec.unicode_to_gid) + 1
    )
    font_widths = _font_widths(number_of_glyphs)
    overrides = dict(spec.pdf_width_overrides)
    return tuple(
        overrides.get(cid, font_widths[cid])
        for cid in range(1, 5)
    )


def _build_pdf(spec: _FixtureSpec) -> bytes:
    content_hex = "".join(f"{cid:04X}" for cid in _CONTENT_CIDS).encode(
        "ascii"
    )
    content = (
        b"BT\n/F1 20 Tf\n72 720 Td\n<"
        + content_hex
        + b"> Tj\nET"
    )
    type0 = (
        b"<< /Type /Font /Subtype /Type0 /BaseFont /SyntheticRecovery "
        b"/Encoding /Identity-H /DescendantFonts [6 0 R] "
        b"/ToUnicode 8 0 R >>"
    )
    widths = b" ".join(
        str(width).encode("ascii") for width in _pdf_widths(spec)
    )
    cid_to_gid = (
        b"/Identity" if spec.cid_to_gid is None else b"10 0 R"
    )
    descendant = (
        b"<< /Type /Font /Subtype /CIDFontType2 "
        b"/BaseFont /SyntheticRecovery "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        b"/Supplement 0 >> /FontDescriptor 7 0 R /DW 1000 "
        b"/W [1 ["
        + widths
        + b"]] /CIDToGIDMap "
        + cid_to_gid
        + b" >>"
    )
    descriptor = (
        b"<< /Type /FontDescriptor /FontName /SyntheticRecovery /Flags 4 "
        b"/FontBBox [0 0 1000 1000] /ItalicAngle 0 /Ascent 800 "
        b"/Descent -200 /CapHeight 700 /StemV 80"
    )
    if spec.embedded_program:
        descriptor += b" /FontFile2 9 0 R"
    descriptor += b" >>"
    font_program = _font_program(spec) if spec.embedded_program else b""

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        _stream(content),
        type0,
        descendant,
        descriptor,
        _stream(
            _to_unicode_cmap(
                _CONTENT_CIDS,
                spec.to_unicode_mapping,
            )
        ),
        (
            _stream(
                font_program,
                entries=(
                    b"/Length1 "
                    + str(len(font_program)).encode("ascii")
                ),
            )
            if spec.embedded_program
            else b"null"
        ),
    ]
    if spec.cid_to_gid is not None:
        mapping = b"".join(
            int(gid).to_bytes(2, "big") for gid in spec.cid_to_gid
        )
        objects.append(_stream(mapping))
    return _assemble_pdf(objects)


_BUILDERS: MappingProxyType[str, Callable[[], bytes]] = MappingProxyType(
    {
        fixture.fixture_id: (
            lambda fixture=fixture: _build_pdf(fixture)
        )
        for fixture in _FIXTURES
    }
)


def build_fixture(fixture_id: str) -> bytes:
    """Build one registered synthetic recovery PDF entirely in memory."""

    try:
        builder = _BUILDERS[fixture_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown font-recovery fixture {fixture_id!r}; "
            f"expected one of {FIXTURE_IDS}"
        ) from exc
    return builder()


def build_all_fixtures() -> dict[str, bytes]:
    """Return freshly generated fixture bytes in stable registry order."""

    return {
        fixture_id: build_fixture(fixture_id)
        for fixture_id in FIXTURE_IDS
    }


def fixture_hashes() -> dict[str, str]:
    """Return current SHA-256 identities in stable registry order."""

    return {
        fixture_id: hashlib.sha256(pdf_bytes).hexdigest()
        for fixture_id, pdf_bytes in build_all_fixtures().items()
    }


# Literal identities make accidental byte drift visible. Values are populated
# from the generated-only builders and checked by ``self_check``.
_EXPECTED_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "safe-identity": (
            "b320dfed43c3ed24b2b3cc886234adbe3fb2ad2998d5636b3104a3d6604b19f9"
        ),
        "healthy-identity": (
            "1aca98b24c3f1f59d489effe54c33ebdb598d8cba76e84bdde2baf35e6a7b770"
        ),
        "used-many-to-one": (
            "dfe2b999c95b7cba8726bee3134c79f841acfbba74da59151cb320c210363681"
        ),
        "unused-alias-control": (
            "288f9d701ffd08cb8d548d95dc3cda0240e7a2037a1a2bb5088d826aebebab9f"
        ),
        "ligature": (
            "ad00c6791ffe9c4bb076fd872d66cad40b28cfaaf8afb890cd6f633473a689a1"
        ),
        "bidi-control": (
            "0200c33509c89e4dcb1f8d319f3e430f6c54b78efb7b06bfaf901776a386a0b1"
        ),
        "width-mismatch": (
            "4bedf54c37709cbc8efca69db09e4c731f7d9a9f7441e25ec74c625ef2414cba"
        ),
        "nonidentity": (
            "2afbdadb8bc0aeb1aeaf7484f5734069cd58dbf6a84be1a00cb031ab0313a889"
        ),
        "missing-program": (
            "3a8ed77b9004158ad2dbc34da5062f8e210e1b27ba97dcce4167f0674ac4c302"
        ),
    }
)


def _reader_smoke(pdf_bytes: bytes, fixture_id: str) -> None:
    from pdfminer.high_level import extract_text
    import pypdfium2 as pdfium

    try:
        extract_text(io.BytesIO(pdf_bytes))
    except Exception as exc:
        raise FixtureIntegrityError(
            f"pdfminer could not open {fixture_id}: {exc}"
        ) from exc

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
                    text_page.get_text_range()
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
    except FixtureIntegrityError:
        raise
    except Exception as exc:
        raise FixtureIntegrityError(
            f"pypdfium2 could not open/render {fixture_id}: {exc}"
        ) from exc


def self_check(*, verify_readers: bool = True) -> dict[str, str]:
    """Verify registry coverage, determinism, hashes, and reader smoke."""

    if set(FIXTURE_IDS) != set(_BUILDERS):
        raise FixtureIntegrityError(
            "font-recovery registry and builder keys do not match"
        )

    hashes: dict[str, str] = {}
    for fixture_id in FIXTURE_IDS:
        first = build_fixture(fixture_id)
        second = build_fixture(fixture_id)
        if first != second:
            raise FixtureIntegrityError(
                f"{fixture_id} did not regenerate byte-identically"
            )
        if not first.startswith(_PDF_HEADER):
            raise FixtureIntegrityError(
                f"{fixture_id} does not have the expected PDF header"
            )
        has_program = b"/FontFile2" in first
        expected_program = _FIXTURES_BY_ID[fixture_id].embedded_program
        if has_program is not expected_program:
            raise FixtureIntegrityError(
                f"{fixture_id} embedded-program state drifted"
            )
        digest = hashlib.sha256(first).hexdigest()
        if digest != _EXPECTED_SHA256[fixture_id]:
            raise FixtureIntegrityError(
                f"{fixture_id} hash drift: expected "
                f"{_EXPECTED_SHA256[fixture_id]}, got {digest}"
            )
        hashes[fixture_id] = digest
        if verify_readers:
            _reader_smoke(first, fixture_id)
    return hashes


if __name__ == "__main__":
    for name, digest in self_check().items():
        print(f"{name} {digest}")
