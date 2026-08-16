# Phase 2 font-audit synthetic PDF fixtures

These test-only fixtures are generated entirely in memory. No PDF binary or
third-party font program is stored, copied, downloaded, or embedded.

Use:

```python
from tests.fixtures.phase_02.font_audit import build_fixture, self_check

pdf_bytes = build_fixture("type0-missing-tounicode")
self_check()  # determinism, registered hashes, pdfminer, and pypdfium2
```

The serializer fixes object order, line endings, xref formatting, trailer ID,
and all stream bytes. Each call returns a new `bytes` value with the same
SHA-256 identity.

| Fixture ID | Structural purpose | SHA-256 |
|---|---|---|
| `healthy-winansi-intentional-spaces` | Standard Type1 Helvetica with explicit WinAnsi encoding and an ordinary encoded space | `819fc73a96a087ddbf1770a41bd02c9908bc1eaee9ff237fa29e511aaa40818d` |
| `type0-missing-tounicode` | Type0/CIDFontType2, Identity-H, Identity CIDToGID, no ToUnicode | `3027ce2495606718d10fddf0d34263aaa96f4082c2ec0e7d816bfb7957da9ce2` |
| `type0-nonidentity-cidtogid` | Type0/CIDFontType2 with a valid ToUnicode map and a CIDToGID stream mapping CID 1/2 to GID 5/3 | `b8c8db65d5249da32bdc1e8bb737477872ad917a3070ed652663875dc93d6563` |
| `standard14-no-embedded-font` | Standard-14 Times-Roman with the valid absence of FontDescriptor and embedded font data | `8267a3344a9dc3d373657c97bee73838f5b562d8bf3f222434c872f50bf12c8b` |

The two Type0 fixtures deliberately omit a font program. Their purpose is
dictionary/mapping inspection; PDFium may substitute or render missing glyphs.
Both pinned readers must still open them, enumerate their single page, and
complete native-text/render smoke checks. The Standard-14 fixture is the
negative control proving that absent font data is not inherently a defect.
