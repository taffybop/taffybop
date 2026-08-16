"""Immutable registry for the synthetic Phase 2 font-audit PDF fixtures.

The fixtures are generated from :mod:`builder`; no PDF binaries or third-party
font programs are stored in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


CidToGidKind = Literal["not-applicable", "identity", "stream"]


@dataclass(frozen=True, slots=True)
class FontAuditFixture:
    """Declared identity and font-dictionary state for one synthetic PDF."""

    fixture_id: str
    filename: str
    sha256: str
    purpose: str
    font_subtype: str
    encoding: str
    has_to_unicode: bool
    cid_to_gid: CidToGidKind
    has_embedded_font_program: bool
    is_standard_14: bool
    expected_native_text: str | None


# Hashes are intentionally literal. ``builder.self_check()`` regenerates each
# fixture twice and rejects either nondeterminism or drift from this registry.
FIXTURES = (
    FontAuditFixture(
        fixture_id="healthy-winansi-intentional-spaces",
        filename="healthy-winansi-intentional-spaces.pdf",
        sha256="819fc73a96a087ddbf1770a41bd02c9908bc1eaee9ff237fa29e511aaa40818d",
        purpose=(
            "Healthy WinAnsi control whose U+0020 values are ordinary encoded "
            "spaces, not collapsed visible glyphs."
        ),
        font_subtype="Type1",
        encoding="WinAnsiEncoding",
        has_to_unicode=False,
        cid_to_gid="not-applicable",
        has_embedded_font_program=False,
        is_standard_14=True,
        expected_native_text="ALPHA BETA",
    ),
    FontAuditFixture(
        fixture_id="type0-missing-tounicode",
        filename="type0-missing-tounicode.pdf",
        sha256="3027ce2495606718d10fddf0d34263aaa96f4082c2ec0e7d816bfb7957da9ce2",
        purpose=(
            "Type0/CIDFontType2 negative fixture with Identity-H encoding and "
            "an explicitly missing ToUnicode map."
        ),
        font_subtype="Type0",
        encoding="Identity-H",
        has_to_unicode=False,
        cid_to_gid="identity",
        has_embedded_font_program=False,
        is_standard_14=False,
        expected_native_text=None,
    ),
    FontAuditFixture(
        fixture_id="type0-nonidentity-cidtogid",
        filename="type0-nonidentity-cidtogid.pdf",
        sha256="b8c8db65d5249da32bdc1e8bb737477872ad917a3070ed652663875dc93d6563",
        purpose=(
            "Type0/CIDFontType2 negative fixture with a present ToUnicode CMap "
            "and a non-identity CIDToGIDMap stream."
        ),
        font_subtype="Type0",
        encoding="Identity-H",
        has_to_unicode=True,
        cid_to_gid="stream",
        has_embedded_font_program=False,
        is_standard_14=False,
        expected_native_text="AB",
    ),
    FontAuditFixture(
        fixture_id="standard14-no-embedded-font",
        filename="standard14-no-embedded-font.pdf",
        sha256="8267a3344a9dc3d373657c97bee73838f5b562d8bf3f222434c872f50bf12c8b",
        purpose=(
            "Standard-14 Type1 control where the absent FontDescriptor and "
            "embedded font program are valid and must not be treated as damage."
        ),
        font_subtype="Type1",
        encoding="StandardEncoding",
        has_to_unicode=False,
        cid_to_gid="not-applicable",
        has_embedded_font_program=False,
        is_standard_14=True,
        expected_native_text="STANDARD FOURTEEN",
    ),
)


FIXTURES_BY_ID = MappingProxyType(
    {fixture.fixture_id: fixture for fixture in FIXTURES}
)
