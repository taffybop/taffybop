# Expert validation: `ny-timetable`

## Scope and overall assessment

This report validates both the supplied expert Markdown/JSON and the `baseline-20260728-current` output from our parser against the three source PDF pages. It is analysis-only; all source, expert, and run artifacts were treated as immutable evidence.

The expert output is strong on table recovery: 149 of the 150 timetable data rows compare exactly with the native PDF table extraction. The material exception is one shifted row on physical PDF page 3. The expert also normalizes some multi-line station headings incorrectly, uses inconsistent heading/page-number markup, and reports derivative screenshots as images even though the PDF contains no raster images. Our baseline is materially worse on the core grid: every page collapses 13 source columns to 12 and contains only 49 of 50 service rows.

Status vocabulary:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — substantially supported, with a material qualification.
- **Not independently verifiable** — the output supplies a claim or score for which the source provides no independent test.
- **Incorrect** — contradicted by the source.
- **Potentially inferred** — plausible, but derived or model-interpreted rather than explicit in the source.

## Artifact inventory

| Artifact | Role | SHA-256 |
|---|---|---|
| `benchmark-expertmodeldata/ny-timetable.pdf` | Ground-truth source | `f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30` |
| `benchmark-expertmodeldata/ny-timetable.md` | Expert standalone Markdown | `cc939684182ad5220dddba6bdf3f60f3bbfd8e14977900c1814b129e0df7d396` |
| `benchmark-expertmodeldata/ny-timetable.json` | Expert structured output | `075e663d4cf4af674bf518343b4fabea6e281efc4606cb77bc2f854931af463d` |

- Document category: public-transit timetable.
- Page inventory: 3 portrait pages, each 612 × 792 PDF units.
- Printed pagination: source pages “Page 2 of 28”, “Page 3 of 28”, and “Page 4 of 28”.
- Layout: one dense, ruled timetable per page with a merged route/direction title, rotated multi-line station headings, and 50 service rows.
- Complex elements: merged cells, rotated text, narrow columns, repeated time values, and hundreds of vector ruling objects.
- Native object inventory per page: 665 rectangles, 199 lines, no curves, no raster images, and no annotations. Character counts are 2,600, 2,959, and 2,609.
- Expert job metadata: `tier=agentic`, `cost_optimized=false`, `triggered_auto_mode=false`; all page orientations are 0.

## Source page map

| Physical PDF page | Printed page | Source content | Expert item summary |
|---|---:|---|---|
| 1 | 2 of 28 | Weekday timetable to The Bronx; title row, station row, 50 services | Header, table, footer |
| 2 | 3 of 28 | Weekday timetable to The Bronx; title row, station row, 50 services | Header, table, footer |
| 3 | 4 of 28 | Weekday timetable to The Bronx; title row, station row, 50 services | Header, table, footer |

Native table inspection finds 52 visual rows on each page: one merged title row, one station-header row, and 50 data rows. The expert structured table contains 51 rows per page because it represents the title separately and keeps the normalized station header plus the 50 data rows.

## Expert element validation

| Page(s) | Expert element or claim | Evidence class | Status | Assessment |
|---|---|---|---|---|
| 1–3 | Page count, order, and orientation | Explicit text / page geometry | **Verified** | All three source pages are present in the correct order and orientation. |
| 1–3 | Timetable titles and directions | Explicit text | **Verified** | The directions and route/title text match the visible source, apart from the page-3 Markdown hierarchy issue described below. |
| 1 | Station headings and 50 timetable rows | Explicit vector text | **Verified** | All 50 data rows compare exactly with the source table extraction. |
| 2 | Fifty timetable data rows | Explicit vector text | **Verified** | All 50 data rows compare exactly with the source table extraction. |
| 2 | Multi-line station headings | Explicit vector text | **Partially verified** | The station identities are recoverable, but several normalized labels concatenate words without required separation. |
| 3 | Fifty timetable data rows | Explicit vector text | **Incorrect** | One row loses `3:32`, shifts subsequent times left, and duplicates the terminal `3:57`; the other 49 rows match. |
| 1–3 | Printed page numbers | Explicit text | **Verified** | Values 2, 3, and 4 of 28 are correct. Their serialization is inconsistent. |
| 1–3 | Table and header bounding boxes | Vector geometry | **Partially verified** | Boxes lie over the relevant page regions, but the table boxes include the separately represented title/header area and overlap the header boxes. |
| 1–3 | Page confidence values 1.0, 1.0, and 0.998 | Model metadata | **Not independently verifiable** | The source cannot establish these scores, and no cell-level confidence identifies the page-3 row error. |
| 1–3 | Six entries in `images_content_metadata` | Derived parser artifacts | **Incorrect** as a source-image inventory | The source PDF has zero raster images. The reported entries are page screenshots and table crops created during parsing. |

## Concrete expert discrepancies

### 1. Shifted service row on physical page 3

At source table row 28, approximately `(x=24.49, top=476.17, x1=375.00, bottom=488.15)`, the source row is:

```text
["", "3:01", "3:05", "3:18", "3:24", "3:30", "3:32",
 "3:38", "3:43", "3:48", "3:51", "3:55", "3:57"]
```

The expert row is:

```text
["", "3:01", "3:05", "3:18", "3:24", "3:30", "3:38",
 "3:43", "3:48", "3:51", "3:55", "3:57", "3:57"]
```

The `3:32` value at 103 St is omitted. Every later value in that row is displaced by one column, and the final `3:57` is duplicated. This is a source-contradicted structural error, not a harmless formatting normalization.

### 2. Page-2 station-header whitespace loss

The source uses visually separate, multi-line station labels. The normalized expert header joins several component words without a space:

- `Times Sq42 St`
- `66 StLincoln Center`
- `137 StCity College`
- `168 StWashington Hts`
- `Van Cortlandt Park242 St`

The station identities remain recognizable, so the header is partially rather than wholly unsupported, but the serialized text is not faithful.

### 3. Inconsistent heading and footer markup

- Pages 1 and 2 serialize their direction titles as Markdown headings; page 3 emits `Weekdays to The Bronx` without `#`.
- Pages 1 and 3 wrap the printed page number in `<page_number>...</page_number>`; page 2 emits plain `Page 3 of 28`.

The visible words are correct. The document hierarchy and metadata representation are inconsistent across otherwise homologous pages.

## Geometry and metadata limitations

- Expert table boxes are approximately `x=22.6–376.9`, `top=22.8–767.4`. They include the title region even though the title is also emitted as a separate header item. On page 1, for example, the separate header box is approximately `x=32.5`, `top=27.81`, `width=341.2`, `height=115.53`, so the two semantic elements overlap materially.
- The expert table structure excludes the merged title row while its box covers that row. The box therefore identifies a broad visual region, not the exact geometry of the structured rows.
- Bounding-box confidence values of 0.97–0.98 indicate model confidence, not source-grounded proof of exact boundaries.
- No item-level or cell-level confidence is supplied. The near-perfect page confidence does not expose the page-3 cell omission.
- The PDF contains only vector text and rules. Any “image” generated by full-page rendering or table cropping is derivative evidence and must not be described as a native source image.

## Standalone Markdown versus JSON representations

For this case, the standalone Markdown is reproducible page by page as:

```text
JSON page header, if present

JSON markdown.pages[i].markdown

JSON page footer, if present
```

The pages are then joined with blank lines, modulo outer whitespace. Both `markdown_full` and `text_full` are null.

The item-level representation is not the standalone presentation path. In particular, table items may use pipe-table Markdown and structured row arrays, while the JSON page body—and therefore the standalone Markdown—uses HTML tables. Consumers must not assume that `items.pages[].items[].md`, the page-body Markdown, and the standalone `.md` are byte- or structure-equivalent views.

## Our baseline output versus source

Reviewed artifacts:

- `runs/baseline-20260728-current/ny-timetable/our-output.json`
- `runs/baseline-20260728-current/ny-timetable/our-output.md`

The baseline reports `success`, three pages, native source provenance for all tables, zero native images, three rendered visual regions, and no document warnings. Those metadata facts are supported. The table result itself is not source-faithful.

| Baseline element or claim | Status | Source-grounded finding |
|---|---|---|
| Three pages and printed labels 2, 3, and 4 | **Verified** | JSON `page_number`/`page_label` and footer values agree with the source. |
| One table region per page | **Verified** | The boxes align with the visible timetable regions. |
| Table structure on all pages | **Incorrect** | Each baseline table has 12 columns; the source has 13. Adjacent station/time cells are repeatedly merged. |
| Service-row completeness | **Incorrect** | Each baseline page contains 49 data rows rather than 50, for 147 rather than 150 service rows. |
| Page-2 title reading order | **Incorrect** | `Weekdays`, spurious `ew`, and `to The Bronx` are emitted after the entire table instead of before it. |
| OCR recovery fragments | **Incorrect** | Page 1 adds `ew` and `741`; page 2 adds `ew`. `741` is a colon-dropped duplicate of a timetable value, not a separate source element. |
| Table parse-concern list | **Incorrect** as a diagnostic result | All three structurally invalid tables have an empty `parse_concerns` array. |
| Native versus rendered image counts | **Verified** | `document.image_count=0` correctly reflects the vector-only source, while render regions are counted separately. |
| Table/item confidence | **Not independently verifiable** / absent | The tables have null confidence. OCR fragments have confidence values, but confidence does not make the false fragments source-correct. |

The column collapse is systematic, not confined to the expert’s one bad page-3 row. For example, the first page’s source columns `137 St City College` and `168 St Washington Hts` contain separate values `12:36` and `12:42`; the baseline combines them as one cell, `12:36 12:42`. Its header correspondingly drifts into labels such as `168 St Washington Hts St` and `Dyckman 215 St`. Page 3 similarly merges station names (`103 St 137 St`, `City College 168`, and `St Washington Hts Dyckman St`) and combines adjacent times.

Page 2 is additionally misaligned at the table boundary. Its first structured row omits the `Notes` column. The first data cell becomes `8:37 8:41`, vertically combining South Ferry values from two different service rows; subsequent cells/rows shift. Thus a high token-recall proxy masks a severe grid error.

For all five reviewed cases, including this one, baseline standalone Markdown is exactly the non-empty JSON item `.md` values joined in page and `reading_order` sequence, modulo outer whitespace. Here that means the 12-column HTML tables and late OCR fragments in JSON are reproduced directly in `.md`; the standalone view does not repair them.

### Confirmed baseline gap disposition

| Gap | Baseline disposition | Evidence |
|---|---|---|
| `GAP-TABLE-002` | **Confirmed** | All three pages lose a column and a service row; numerous cells merge horizontally or vertically. |
| `GAP-TABLE-002` | **Confirmed** | Baseline normalized headers merge distinct station labels, more severely than the expert row-array whitespace loss. |
| `GAP-TABLE-003` | **Confirmed** | Title representation differs between page-1/page-3 table headers and page-2 late text fragments. |
| `GAP-BBOX-001` | **Confirmed with qualification** | Broad table localization is correct, but the box gives no evidence that the 12-column internal structure is correct. |
| `GAP-ORDER-001` | **Confirmed** | Page-2 top title is serialized after the table. |
| `GAP-OCR-001` | **Confirmed** | `ew` and `741` are admitted as alleged omission recovery despite being false/duplicate fragments. |

## Mapped gaps

These findings use the finalized gap taxonomy while retaining their baseline
dispositions and exact source regions.

| Gap | Mapped capability | Exact source region | Why reusable |
|---|---|---|---|
| `GAP-TABLE-002` | Dense-table cell omission causing row-wide column shift | Physical page 3, row box approximately `(24.49, 476.17, 375.00, 488.15)` | Tests preservation of cell count and column alignment in repetitive narrow tables. |
| `GAP-TABLE-002` | Multi-line/rotated table-header word-boundary loss | Physical page 2, station-header band at the top of the table | Tests whitespace reconstruction when a label is split across rotated visual lines. |
| `GAP-TABLE-003` | Inconsistent table-title and page-number representation across homologous pages | Page-3 direction title; page-2 footer | Tests stable document hierarchy and tag policy across repeated layouts. |
| `GAP-BBOX-001` | Semantic box includes and overlaps separately emitted title/header | All pages, approximately `x=22.6–376.9`, `top=22.8–767.4` | Tests whether table geometry corresponds to the rows represented in table data. |
| `GAP-ORDER-001` | Top-of-table title emitted after the table | Physical page 2, title at approximately `top=30.18–44.18` | Tests reading order when visual detection repairs a layout omission. |
| `GAP-OCR-001` | False OCR “recovery” admitted alongside native table content | Page 1 `ew`/`741`; page 2 `ew` | Tests duplicate suppression and evidence thresholds for selective OCR. |

## Open questions

1. Should the canonical table representation preserve station headings as visible multi-line strings, or normalize them to single-line labels? Either policy needs explicit whitespace rules.
2. Should a table bounding box include a merged visual title that is serialized as a separate heading, or should the two element boxes be disjoint?
3. Are derivative page/table renders intended to live in `images_content_metadata`? If so, the schema needs an explicit `native_source` versus `derived_render` provenance field.
