# Source, expert, and baseline validation: `finance-10k`

## Scope and verdict

This report validates the three immutable source pages against the supplied expert Markdown/JSON and visually compares the successful baseline parser run `baseline-20260728-current`. It is analysis only.

All financial labels and values in the expert output are source-supported, so this is a high-quality textual reference. The expert is not a perfect structural reference: its page 1 and page 3 HTML lose the three-column span of `Years ended`, and its page 2 table splits one visual common-stock row into two logical records. Our baseline output corrects both defects and preserves source accounting symbols, with complete page/table coverage. Remaining limitations are sparse table confidence, no cell-level bboxes/provenance, and inconsistent classification of the repeated `Apple Inc.` running header across pages.

## Inventory and method

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `finance-10k.pdf` | 87,105 | `e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086` |
| Expert `finance-10k.md` | 12,969 | `0cada5fe6e5406e38ebe8251399e0ee61bce3127a378232bacb01771ff060517` |
| Expert `finance-10k.json` | 103,631 | `d426ac3542880372421023bf75acfe414fe604182383ab38723efb271d3f177a` |

- Source: three portrait native PDF pages, each 612 x 792 pt, rotation 0; printed pages 28, 30, and 32.
- Category: public-company financial statements/10-K.
- Layout: repeated company header, centered statement title and units note, one full-width financial table, accompanying-notes line, and running footer on each page.
- Complex elements: multi-row/spanning headers, indented section/subtotal hierarchy, accounting presentation signs, parenthesized negatives, long wrapped row labels, and printed versus physical pagination.
- Source object inventory:
  - Physical p1: 1,214 chars, 34 lines, 28 curves, 0 images/annotations, one detected table.
  - Physical p2: 1,617 chars, 28 lines, 42 curves, 0 images/annotations, one detected table.
  - Physical p3: 2,246 chars, 34 lines, 41 curves, 0 images/annotations, one detected table.
- Visual evidence: all three original-detail renders were inspected under `tmp/pdfs/llamaparse-15/finance-10k/page-*.png`; text/table geometry was checked with pdfplumber.
- Baseline evidence: the case's `our-output.json`, `our-output.md`, diagnostics, and comparison metrics in `runs/baseline-20260728-current`.

The status terms `Verified`, `Partially verified`, `Not independently verifiable`, `Incorrect`, and `Potentially inferred` describe source support, not agreement with another parser.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 28 | `Apple Inc.` near `y=43`; operations title and unit note at `y=63-82`; statement table at approximately `x=48-564, y=99-546`; notes line at `y=563`; footer at `y=766`. |
| 2 | 30 | Repeated company/title/unit block at `y=43-82`; balance-sheet table at approximately `x=48-564, y=100-702`; notes line at `y=716`; footer at `y=766`. |
| 3 | 32 | Repeated company/title/unit block at `y=43-82`; cash-flow table at approximately `x=48-565, y=90-709`; notes line at `y=726`; footer at `y=766`. |

## Evidence classification

- Explicit: every title, units note, table label, year/date header, amount, accounting symbol, note, company footer, and printed page number.
- PDF-vector-derived: ruling, indentation, visual grouping, header spanning, and emphasis; numeric values do not need geometric inference.
- Pixel-estimated: not needed for values.
- Model-inferred: HTML row/column spans and semantic heading/table roles are transformations of layout.
- Unverifiable: confidence calibration and intended machine-readable accounting semantics beyond the printed presentation.

## Expert element validation

Each expert page contains indexes 0-5 in `items.pages[n].items`.

| Page/item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| P1 items 0-2 | Company, statement title, units note | Verified | Wording and order match. The first two are bold text rather than heading types, which is internally inconsistent with pages 2-3 but not a content error. |
| P1 item 3 | Operations table | Partially verified | Every label and value matches. The HTML places `Years ended` in one ordinary center header instead of spanning all three date columns, and presentation `$` markers are generally dropped from numeric cells. |
| P1 items 4-5 | Notes line and footer/page 28 | Verified | Exact visible content. |
| P2 items 0-2 | Company, balance-sheet title, units note | Verified | Exact wording and correct order. |
| P2 item 3 | Balance-sheet table | Partially verified | Values and section ordering match, but one visual wrapped row is split into two logical records: the `Common stock ... 50,400,000 shares` record has blank values and a second `authorized; ... respectively` record receives 73,812 and 64,849. |
| P2 items 4-5 | Notes line and footer/page 30 | Verified | Exact visible content. |
| P3 items 0-2 | Company, cash-flow title, units note | Verified | Exact wording and order. |
| P3 item 3 | Cash-flow table | Partially verified | Every row/value matches, but `Years ended` again fails to span the three date columns and presentation `$` markers are generally omitted. |
| P3 items 4-5 | Notes line and footer/page 32 | Verified | Exact visible content. |
| Table bboxes | One table-region bbox per page | Verified | All three bboxes cover the corresponding source tables. There is no row/cell bbox. |
| Confidence/metadata | Page scores 0.100, 0.717, 0.675; table boxes 0.96-0.98 | Not independently verifiable | The page 1 score is especially inconsistent with its accurate content and high table score; score targets and calibration are not documented. |

## Concrete expert defects and limitations

### Spanning-header topology on pages 1 and 3

The source visually centers `Years ended` over all three date columns. Expert HTML uses a non-spanning header cell in the middle date position. This does not alter values but encodes the header hierarchy incorrectly. A downstream table consumer cannot reliably infer that the label governs all three years.

### Wrapped row split on page 2

`Common stock and additional paid-in capital, $0.00001 par value: 50,400,000 shares authorized; 15,550,061 and 15,943,425 shares issued and outstanding, respectively` is one source row with two amounts. Expert Markdown makes the visual wrap into two records, leaving the first record blank and attaching values only to the continuation. The words and amounts remain correct, but row identity is incorrect.

### Accounting presentation

The expert representation preserves parentheses but strips most display `$` symbols. This is not a numeric error, yet the symbols are explicit source content and can matter to presentation-faithful output. It should be distinguished from normalized numeric data.

## Baseline parser comparison

The baseline completed successfully with 3 pages, 18 top-level items, 3 tables, 100% bbox coverage, 100% source provenance, no warnings, and no parse concerns.

| Our page/item(s) | Status | Source-grounded assessment |
|---|---|---|
| P1 `p1-i1` to `p1-i3` | Verified | Company, title, and units note are exact and correctly located. |
| P1 `p1-i4` | Verified | All operations rows/values match. HTML correctly uses `<th colspan="3">Years ended</th>` over the three date columns and preserves the source `$` presentation where printed. |
| P1 `p1-i5` to `p1-i6` | Verified | Notes line and page 28 footer are exact. |
| P2 `p2-i1` to `p2-i3` | Partially verified | Text is exact. `Apple Inc.` is typed/rendered as an H1 rather than a repeated page header, unlike `p1-i1`. |
| P2 `p2-i4` | Verified | All labels/values match. The long common-stock label and 73,812/64,849 remain one row, correcting the expert split. A minor HTML oddity gives `LIABILITIES AND SHAREHOLDERS' EQUITY` `colspan="2"` plus a final empty cell, but it does not create a false value. |
| P2 `p2-i5` to `p2-i6` | Verified | Notes line and page 30 footer are exact. |
| P3 `p3-i1` to `p3-i3` | Partially verified | Text is exact; the repeated company name is again typed as an H1 rather than a header. |
| P3 `p3-i4` | Verified | All cash-flow rows/values match and `Years ended` correctly spans all three date columns. |
| P3 `p3-i5` to `p3-i6` | Verified | Notes line and page 32 footer are exact. |

Confirmed strengths relative to the expert:

- Correct multi-column `Years ended` spans on pages 1 and 3.
- Correct single-record handling of the wrapped common-stock row on page 2.
- Faithful accounting presentation signs and all visible native text.
- Accurate table-region bboxes, complete provenance, and correct physical page order.

Confirmed limitations:

- The three table items have null confidence and no row/cell bboxes despite containing most document content.
- No table item carries a parse concern, even though machine-readable topology is a separate task from text recovery.
- The repeated company header is typed inconsistently: `header` on page 1, `heading` on pages 2-3.
- Printed pages 28/30/32 live in footer text rather than a dedicated printed-page metadata field.

## Bounding boxes, confidence, and metadata

- Expert and our table-region boxes closely cover the source tables.
- Neither output exposes bboxes for header spans, rows, cells, display symbols, or indentation levels.
- Our non-table items have confidence around 0.94-0.97 while table confidence is null. The comparison's 83.33% confidence coverage therefore excludes the most structurally important items.
- Expert page confidence varies from 0.100 to 0.717 even though all three pages are similarly accurate. A high box detector score and a low page score cannot be interpreted without a score contract.
- Expert `job.tier` is `agentic`; top-level `markdown_full` and `text_full` are null.
- Our JSON explicitly records page dimensions, bbox units, physical page numbers, item source `native`, and processing versions. It does not promote the printed page numbers from footers.

## Standalone Markdown versus JSON

For each expert page, standalone Markdown is the JSON page-body Markdown followed by its separate footer item. The automated signal `standalone equals joined JSON body pages: False` is therefore expected and does not indicate wrong pairing. `markdown_full` is null.

Our schema does not expose a separate page-body Markdown field. `our-output.md` serializes page items in order and includes each footer. Its table HTML is consistent with the corresponding JSON item `md`.

## Mapped gaps

| Gap | Origin | Mapped capability | Exact evidence |
|---|---|---|---|
| `GAP-TABLE-002` | Expert | Preserve spanning headers and prevent visual line wraps from becoming extra logical rows. | P1/P3 `Years ended`; P2 common-stock row around `y=626-657`. Our baseline handles these correctly. |
| `GAP-TABLE-003` | Expert/contract | Preserve explicit accounting display symbols separately from normalized numeric values. | All three statements; expert drops most visible `$`, while our Markdown preserves them. |
| `GAP-BBOX-001` | Both | Provide hierarchical table, row, cell, and header-association geometry. | P1 `x=48-564, y=99-546`; P2 `y=100-702`; P3 `y=90-709`; both outputs stop at table-region boxes. |
| `GAP-PAGE-001` | Both | Classify repeated running headers consistently across pages without promoting them into document headings. | `Apple Inc.` is expert text on P1 but H1 on P2/P3; ours is header on P1 but H1 on P2/P3. |
| `GAP-PROVENANCE-001` | Both | Calibrate confidence by content task and attach confidence/provenance at cell level. | Expert page 1 confidence 0.100 versus table 0.96; our three table items have null confidence and only region-level native provenance. |
| `GAP-PAGE-001` | Both | Preserve physical and printed pagination as structured fields. | Physical pages 1-3 are printed 28, 30, and 32; both primarily carry printed numbers in footer content. |
| `GAP-SERIALIZATION-001` | Contract | Make page-body versus full-page footer inclusion explicit. | Expert standalone includes footers excluded from JSON body; our schema uses item-stream Markdown without a page-body field. |

## Open questions

- Should table output expose both presentation text (`$ 298,085`) and normalized numeric value (`298085`)?
- What table-level and cell-level confidence measures are intended?
- Should repeated company names be serialized as headers, omitted from body Markdown, or retained with a stable running-header type?
- Is the printed page number expected as structured metadata in addition to footer text?
- What contract should distinguish a visual line wrap from a logical row boundary?

## Guardrail

This report records evidence only. It makes no parser, test, story, corpus, or global benchmark change.
