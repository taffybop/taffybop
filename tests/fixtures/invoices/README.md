# Synthetic invoice fixture

`source.json` is fictional, authored source data, not an extraction response.
The PDF contains selectable text and two ruled tables. The PNG is a 144 dpi
rendering of that same page, with no native text layer. No customer data is used.

Four line items include two separate `BRK-101` deliveries (quantities 2 and 5),
wrapped descriptions, and linked quantity/unit-price/amount columns. The USD
subtotal is 125.70, tax at 10% is 12.57, and total is 138.27.

Regenerate from the repository root using installed test dependencies:

```bash
.venv/bin/python -m tests.fixtures.invoices.builder
.venv/bin/python -m pytest tests/benchmarks/test_synthetic_invoice_fixture.py -q
```

The PDF writer follows the repository's byte-stable synthetic-PDF convention.
PNG bytes can vary with the PDFium rendering version; regeneration updates its
source hash and requires visual review. Do not change source truth to match an
OCR result. The fixture tests independently reopen PDF table geometry/text and
verify decimal arithmetic; they do not call the production parser.

For the offline routing evaluator, use each `*.expected.json` with its matching
PDF or PNG and a saved real API response. The single ordered row check includes
the line-item header and four complete rows, followed by the three totals rows.
Both `table` and `table_candidate` items are accepted as observations; their
presence does not mean the extraction is trusted. Repeated SKUs must not be
deduplicated or reassigned quantities. A wrapped description remains one cell,
with `\n` at its visible line break.

This is an exact table-representation check: changed whitespace, omitted grids,
currency labels, extra rows or different column grouping fail even if some
numbers appear elsewhere as paragraphs. Interpret those failures by inspecting
the source and raw response. It covers selected table claims, not every invoice
field or all invoice layouts, and it is not a production accuracy score.

No response, latency, cost, routing decision, or model correction is fabricated.
Create a manifest pointing to actual saved responses only after parsing each
source; use the SHA-256 in the matching expectation for its `source.sha256`.

Each expectation has **16 checks**: the unchanged strict whole-row check plus
12 independent quantity/unit-price/amount checks and three summary-value checks.
Numeric checks select the source's 5-row/6-column line-item grid or 3-row/2-column
totals grid, then address the source-authored row and column; they do not use
parser item IDs or candidate values. If only description wrapping changes,
the strict check fails while all 15 numeric checks pass. Missing numeric cells
still fail their own checks. Passing numeric checks alone does not establish
SKU/description ownership; retain the whole-row result alongside them.
