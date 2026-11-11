# Initial PX evaluation sources

Version: `px1-initial-v1`, frozen 2026-11-11.

These are original fictional test documents authored for this repository. They
contain no customer, employee, private or third-party document data and may be
sent to the configured parsing/extraction providers within the test budget.
Authorization of the source is not approval to exceed configured spend limits.

[`sources.json`](sources.json) defines the printed documents.
[`expected.json`](expected.json) is a separately authored source-reading oracle;
it is never generated from a provider response or by the PDF builder.
[`manifest.json`](manifest.json) freezes both JSON hashes, each asset hash, split,
family, media type, page count, byte size and authorization basis. No provider
results are registered yet.

The four independent documents each have a selectable-text PDF and a 144 dpi
image-only render. Two development sources have PNG siblings; two held-out
sources have JPEG siblings at quality 92. Images are synthetic scan proxies,
not real scanner photographs. A render sibling remains in the parent's split
and must never count as an independent document. The source-reading oracle
applies to both versions; report PDF and image observations separately.

The test generator follows the existing repository's deterministic PDF convention
and uses installed PDFium/Pillow. ReportLab and Poppler are absent locally; no
packages were installed. Each latest image was visually inspected on 2026-11-11:
text and table cells are legible, with no clipping or overlaps. Tests separately
reopen PDF text/grids with pdfplumber and check PNG/JPEG render custody.

Regenerate only after a deliberate source/corpus revision and visual review:

```sh
.venv/bin/python -m tests.fixtures.parse_extract_v1.builder
.venv/bin/python -m pytest tests/test_parse_extract_evaluation_set.py -q
```

Regeneration rewrites source asset hashes, so it must not be used to accept
unexplained drift. The PDF bytes are deterministic; raster bytes depend on the
installed PDFium/Pillow versions. Do not modify expectations to agree with OCR or
LLM output. Keep historical fixtures and benchmark records unchanged.

The [evaluation protocol](../../../tracker/parse-extract-v1/EVALUATION.md)
defines selected claims, normalization, denominators, critical values and limits.
These fixtures are not application seed data or fabricated extraction results.
