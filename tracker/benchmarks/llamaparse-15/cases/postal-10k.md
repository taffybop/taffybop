# Expert validation: `postal-10k`

## Scope and overall assessment

This report validates both the supplied expert Markdown/JSON and the `baseline-20260728-current` output from our parser against the three source PDF pages. It is analysis-only; source, expert, and run artifacts were treated as immutable evidence.

The expert output recovers the glossary and nearly all financial-table values correctly. Its principal failures are structural: it mishandles multi-row/spanning financial headers, strips explicit currency glyphs inconsistently, assigns inconsistent heading types, and emits a false datatype concern. Our baseline is better on the financial tables but detaches and partially loses the final glossary row, adds a false OCR duplicate, and drops explicit typography.

Status vocabulary:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — substantially supported, with a material qualification.
- **Not independently verifiable** — the output supplies a claim or score for which the source provides no independent test.
- **Incorrect** — contradicted by the source.
- **Potentially inferred** — plausible, but derived or model-interpreted rather than explicit in the source.

## Artifact inventory

| Artifact | Role | SHA-256 |
|---|---|---|
| `benchmark-expertmodeldata/postal-10k.pdf` | Ground-truth source | `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74` |
| `benchmark-expertmodeldata/postal-10k.md` | Expert standalone Markdown | `49513ae511062bd4ad54ef281b696bb87dd6bb84a20100fd0a055b15c5fd9f05` |
| `benchmark-expertmodeldata/postal-10k.json` | Expert structured output | `c312e77b9cc9ae0d90d1f20f67dd485f085497d7131ceb9342c4066deb2f7966` |

- Document category: public-company annual-report excerpts.
- Page inventory: 3 portrait pages, each 612 × 792 PDF units.
- Printed pagination: 2, 46, and 49.
- Layout:
  - page 1: glossary heading, introduction, two-column banded glossary table, and two italicized act definitions;
  - page 2: “Consolidated Statements of Operations” and a four-column financial table with a two-row merged header;
  - page 3: “Consolidated Statements of Cash Flows” and a dense four-column financial table.
- Complex elements: banded table rows, multi-row/colspan headers, financial symbols, em dashes, italics, and footnote-like scale labels.
- Native object inventory: no raster images. Character counts are 1,824, 772, and 2,134; rectangle counts are 40, 18, and 42.
- Expert job metadata: `tier=agentic`, `cost_optimized=false`, `triggered_auto_mode=false`; all page orientations are 0.

## Source page map

| Physical PDF page | Printed page | Source content | Expert item summary |
|---|---:|---|---|
| 1 | 2 | Glossary, 39 glossary entries, CARES Act and Exchange Act definitions | Heading, prose, table, prose, footer |
| 2 | 46 | Consolidated Statements of Operations for years ended September 30, 2025–2023 | Title-as-text, table, footer |
| 3 | 49 | Consolidated Statements of Cash Flows for years ended September 30, 2025–2023 | Two headings, table, footer |

## Expert element validation

| Page(s) | Expert element or claim | Evidence class | Status | Assessment |
|---|---|---|---|---|
| 1 | Glossary heading and introductory prose | Explicit text | **Verified** | Text and reading order match the source. |
| 1 | Glossary table, 39 entries plus header | Explicit text and fills | **Verified** | All table rows compare correctly; HTML preserves the source italics. |
| 1 | CARES Act and Exchange Act definitions | Explicit text / typography | **Verified** | Wording and italic emphasis are preserved. |
| 2–3 | Financial row labels and numeric magnitudes | Explicit text | **Verified** with symbol exceptions | Values and em dashes match; currency-glyph loss is assessed separately. |
| 2 | Two-row table header in item HTML | Explicit text / table geometry | **Verified** | The item HTML correctly uses a three-column span for “Year Ended September 30,”. |
| 2 | Same header in item row arrays | Explicit text / table geometry | **Incorrect** | The row arrays repeat “Year Ended September 30,” into each year cell rather than preserving the colspan relationship. |
| 3 | “Years Ended September 30,” spanning header | Explicit text / table geometry | **Incorrect** | Both the item rows and page-body HTML split the phrase into incorrect columns. |
| 2–3 | Currency-symbol preservation | Explicit glyphs | **Incorrect** | Several visible `$` glyphs are dropped, and page 3 retains only one of three equivalent symbols in one row. |
| 2–3 | Heading hierarchy | Explicit typography plus semantic classification | **Partially verified** | The visible title text is correct, but page 2 is typed as prose while similar page-3 text is split into two level-1 headings. |
| 2–3 | `header_value_type_mismatch` parse concern | Model-generated metadata | **Incorrect** | A date-like spanning header over numeric financial values is normal; the concern misclassifies the table schema. |
| 1–3 | Page confidence 0.993, 0.084, and 0.675 | Model metadata | **Not independently verifiable** | The source cannot validate these scores. The 0.084 score is not localized to any table cell or element. |
| 1–3 | Six entries in `images_content_metadata` | Derived parser artifacts | **Incorrect** as a source-image inventory | All three PDF pages are vector-only; the entries are generated page/table images. |

## Concrete expert discrepancies

### 1. Page-2 row arrays lose colspan semantics

The visible source has a single heading, “Year Ended September 30,” centered across the 2025, 2024, and 2023 columns. The expert item HTML represents this correctly with:

```html
<th colspan="3">Year Ended September 30,</th>
```

The same item’s structured row arrays instead repeat `Year Ended September 30,<br/>` in each of the three year cells. This creates an internal inconsistency: the HTML view is source-faithful, while the structured rows are not.

### 2. Page-3 spanning header is split into false columns

The source phrase is “Years Ended September 30,” spanning the three year columns. The item rows serialize it approximately as:

```text
["(in millions)", "Years Ended September<br/>2025", "2024", "30,<br/>2023"]
```

The standalone/page-body HTML also places `Years Ended September`, a blank, and `30,` in separate columns. That is not the source’s logical table structure. The relevant source title/header band is around `top=90.27–100.27`; the expert table box begins around `x=60.41`, `top=90.19`, `width=491.14`, `height=591.91`.

### 3. Explicit currency glyphs are removed inconsistently

These are visible source glyphs, not inferred currency:

- Page 2, operating revenue: `$` at approximately `x=260.63`, `360.38`, and `460.13`, `top=133.02–143.02`; all three are absent in the expert table.
- Page 2, net loss: the same x positions at `top=318.27–328.27`; all three are absent.
- Page 3, net loss: `$` at approximately `x=408.0`, `457.5`, and `507.0`, `top=133.02–143.02`; all three are absent.
- Page 3, cash and cash equivalents at year end: the same x positions at `top=627.27–637.27`; the expert retains only the first symbol and drops the other two.
- Page 3, cash paid for interest: the same x positions at `top=670.02–680.02`; all three are absent.

The expert does preserve the source em dashes. This isolates the issue to symbol capture/normalization rather than wholesale row loss.

### 4. Title semantic typing is inconsistent

Page 2’s statement title is emitted as a `text` item even though its own bounding-box metadata labels it `paragraph_title`. Page 3 uses two level-1 heading items for the analogous two-line title. The text itself is visible and correct; the hierarchy is not stable.

### 5. False datatype parse concern

Both financial pages flag `header_value_type_mismatch`, apparently because the date-bearing header was expected to be a datetime while the columns contain numeric values. This is ordinary financial-table structure: the date phrase describes the reporting periods, not the data type of every body cell. The concern is contradicted by the table’s visible semantics.

## Geometry and metadata limitations

- Bounding-box confidence is present, but item-level and cell-level confidence is absent. A page score of 0.084 on page 2 does not reveal whether the uncertainty concerns title typing, header structure, currency glyphs, or body values.
- On page 3, the “STATEMENTS OF CASH FLOWS” item includes overlapping boxes, including one box spanning both title lines. Without box-role metadata, consumers cannot know whether these are alternate detections, line boxes, or a union box.
- Table boxes identify broad regions but do not prove the logical header spans encoded in the row arrays.
- `images_content_metadata` blends derivative full-page screenshots and table crops into an image count even though native PDF image count is zero.

## Explicit, derived, and unverifiable evidence

- Financial labels, numbers, currency symbols, em dashes, and header phrases are explicit vector text.
- Cell/row groupings and colspans are recoverable from visible alignment and rule geometry; these are source-grounded layout relationships.
- Heading levels are semantic classifications. They can be evaluated for consistency with typography and document structure, but an exact Markdown level is not literally printed.
- Confidence values and parse-concern generation logic are model metadata and are **Not independently verifiable** unless calibrated evidence is supplied.
- No material table value in this case needs pixel-only or model-only inference.

## Standalone Markdown versus JSON representations

The standalone Markdown equals, page by page, the optional JSON page header, `markdown.pages[i].markdown`, and optional footer joined with blank lines, modulo outer whitespace. `markdown_full` and `text_full` are null.

The item-level representation is distinct:

- table item `.md` can be a pipe table;
- item row arrays provide another logical view;
- item `.html` may preserve a colspan that the rows do not;
- JSON page-body Markdown—and therefore standalone Markdown—uses HTML tables and can differ again.

This case demonstrates why those views cannot be treated as interchangeable. Page 2’s item HTML is more faithful than its row arrays; page 3’s page-body HTML itself contains the header split.

## Our baseline output versus source

Reviewed artifacts:

- `runs/baseline-20260728-current/postal-10k/our-output.json`
- `runs/baseline-20260728-current/postal-10k/our-output.md`

The baseline reports `success`, three pages, three native-source tables, zero native images, and no document warnings. It materially outperforms the expert output on the two financial tables, but has a concrete bottom-boundary failure in the glossary.

| Baseline element or claim | Status | Source-grounded finding |
|---|---|---|
| Page-1 glossary table through `FEHB` | **Verified** | Header and rows `AED` through `FEHB` match the source text. |
| Final `FERS` glossary row | **Incorrect** | `FERS` is pushed out of the 39-row table as standalone OCR text; its definition, `Federal Employees Retirement System`, is omitted. The source table has 40 rows including its header. |
| OCR-recovered `ClO` | **Incorrect** | This is a false duplicate/misread of the already correct `CIO` row, emitted at approximately `x=61.6`, `top=335.6`. |
| Glossary italics | **Incorrect** | Italic `CARES Act`, its expanded name, `Exchange Act`, and its expanded name are flattened to plain text. |
| Pages 2–3 spanning financial headers | **Verified** | Baseline HTML and row arrays preserve a single three-column `Year(s) Ended September 30,` span. |
| Pages 2–3 financial values and currency glyphs | **Verified** | All visible numeric magnitudes and all explicit `$` glyphs are retained, including all three comparable cells in each applicable row. |
| Page-3 em dashes | **Partially verified** | Row positions are correct, but four source em dashes are normalized to ASCII hyphens. |
| Financial-statement heading typing | **Verified** | Both titles are emitted consistently as level-1 headings. |
| Financial-table concern generation | **Verified** | Baseline does not repeat the expert’s false `header_value_type_mismatch`. |
| Page-label metadata | **Incorrect** | JSON uses physical sequence labels 1, 2, and 3 rather than visible printed pages 2, 46, and 49. Footer items do preserve the printed values. |
| Table confidence | **Not independently verifiable** / absent | All three table confidence fields are null; nearby text confidence does not localize table uncertainty. |
| Native versus rendered image counts | **Verified** | `document.image_count=0` correctly separates the vector-only source from three rendered visual regions. |

The two page-1 OCR items are both marked `layout_omission_recovered_by_ocr`. That concern is only half-right for `FERS`: the acronym is genuinely omitted by the table engine, but the recovery fails to capture the definition or reattach the row. It is wrong for `ClO`, which duplicates a source row already present as `CIO`.

The financial tables demonstrate why the expert output is not an automatic oracle. Relative to the source, the baseline’s page-2 and page-3 headers and currency glyphs are more faithful than the expert’s, even though automated expert-to-ours text metrics cannot express that structural advantage.

Baseline standalone Markdown is exactly the non-empty JSON item `.md` values joined in page and `reading_order` sequence, modulo outer whitespace. It uses the same HTML tables as the JSON items; structured rows/cells and provenance remain JSON-only.

### Confirmed baseline gap disposition

| Gap | Baseline disposition | Evidence |
|---|---|---|
| `GAP-TABLE-002` | Not observed in baseline | Both financial headers preserve the source colspan correctly. |
| `GAP-TEXT-001` | Not observed for currency; related style loss remains | Baseline preserves every tested `$`, but changes em dashes to hyphens and drops glossary italics. |
| `GAP-SERIALIZATION-001` | Not observed in baseline | Both statement titles receive the same heading type. |
| `GAP-DIAGNOSTICS-001` | Not observed in financial tables | The expert’s false concern is absent; separate OCR recovery concerns are assessed under `GAP-OCR-001`. |
| `GAP-PROVENANCE-001` | **Confirmed** | Table confidence is null and no cell-level confidence exists. |
| `GAP-TEXT-001` | **Confirmed** | The last glossary row is split from the table and loses its definition. |
| `GAP-OCR-001` | **Confirmed** | False `ClO` duplication and incomplete `FERS` recovery are both admitted. |
| `GAP-TEXT-001` | **Confirmed** | Explicit italics and em-dash glyph identity are not preserved. |
| `GAP-PAGE-001` | **Confirmed** | Printed page labels exist in footer items but not in JSON page metadata. |

## Mapped gaps

These findings use the finalized gap taxonomy while retaining their baseline
dispositions and exact source regions.

| Gap | Mapped capability | Exact source region | Why reusable |
|---|---|---|---|
| `GAP-TABLE-002` | Multi-row and spanning financial-header preservation | Pages 2–3, top table-header bands; page 3 around `top=90.19–133.02` | Tests consistency among HTML, row arrays, and page-body serialization. |
| `GAP-TEXT-001` | Explicit currency-glyph retention and provenance | Page 2 at `top=133.02` and `318.27`; page 3 at `133.02`, `627.27`, and `670.02` | Tests whether semantically important narrow glyphs are preserved per cell. |
| `GAP-SERIALIZATION-001` | Stable semantic typing of homologous statement titles | Page 2 title versus page 3 two-line title | Tests hierarchy consistency across visually analogous pages. |
| `GAP-DIAGNOSTICS-001` | False header datatype warning on financial tables | Pages 2–3 table metadata | Tests concern generation against common date-period headers. |
| `GAP-PROVENANCE-001` | Page-level confidence without local evidence | Page 2 score 0.084; page 3 score 0.675 | Tests whether uncertainty is calibrated and attributable to elements/cells. |
| `GAP-TEXT-001` | Bottom table row detached and partially lost | Page 1, `FERS — Federal Employees Retirement System` at the bottom of the glossary | Tests table-boundary completeness and row reattachment. |
| `GAP-OCR-001` | False duplicate and incomplete selective-OCR recovery | Page 1 `CIO` row around `top=335.6`; `FERS` row around `top=713.6` | Tests reconciliation of OCR candidates against already extracted table cells. |
| `GAP-TEXT-001` | Explicit italics/em-dash identity flattened | Page 1 CARES/Exchange Act rows; page 3 four em-dash cells | Tests typographic and character-level fidelity without changing values. |
| `GAP-PAGE-001` | Printed page label not propagated to page metadata | Page footers 2, 46, and 49 | Tests physical-index versus printed-label semantics across excerpted documents. |

## Open questions

1. Which representation is normative when item rows, item HTML, and page-body HTML disagree?
2. Is currency normalization allowed to remove repeated `$` glyphs? If yes, the schema needs an explicit inherited-currency rule; otherwise the visible glyphs should be retained.
3. What calibration evidence supports the page confidence values, especially 0.084 for a page whose body values are largely correct?
4. Should statement titles be encoded as one heading, two headings, or a title plus subtitle? A stable policy is needed before treating heading-level variance as a parser defect.
