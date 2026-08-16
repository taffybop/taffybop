# Expert-output validation: `clinical-study`

## Scope and verdict

This report validates the four supplied source pages against the expert Markdown and JSON. Text coverage and numeric cell content are generally strong. The important expert defects are structural: Table 1 over-merges section-label rows, Table 2 is serialized as ten columns although the source has nine, the Mermaid flowchart detaches bullet details from their containing nodes, and the physical-page-1 footer geometry incorrectly incorporates body regions.

## Inventory

All expected files are present and paired correctly.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `clinical-study.pdf` | 750,004 | `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2` |
| `clinical-study.md` | 19,996 | `25e32291b2f2c477b64ba4185a0c10c8931b5823be9f8c38810c24680bacd43a` |
| `clinical-study.json` | 163,250 | `ab19827f9b0dad0b38d7c15e879e209152c54d1c198c2a571b093b0a32d6f056` |

- Source format: four-page native/raster-mixed PDF, each page 612 × 792 pt, rotation 0.
- Physical-to-printed pages: 1→1/21, 2→7/21, 3→10/21, 4→11/21. This is a deliberate non-contiguous article excerpt, not a 21-page source with missing parsed pages.
- Category: academic/clinical research article.
- Layout: two-column journal page with metadata sidebar; dense ruled tables; raster participant-flow diagram; running headers and footers.
- Complex elements: multi-level table headers, blank/section rows, footnotes and superscripts, long multi-column prose, links, raster diagram nodes/connectors, non-contiguous printed pagination.
- Source object inventory:

| Physical page | Native chars | Images | Lines | Rectangles | Curves | Dominant content |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 3,828 | 1 | 6 | 258 | 55 | Article title/authors/sidebar/abstract |
| 2 | 2,900 | 0 | 2 | 0 | 356 | Table 1 and continuation prose |
| 3 | 218 | 1 | 2 | 0 | 3 | Raster flowchart plus caption/link |
| 4 | 3,841 | 0 | 3 | 0 | 250 | Table 2 and continuation prose |

- Renders inspected: all four `tmp/pdfs/llamaparse-15/clinical-study/page-*.png`.
- The standalone Markdown differs from concatenated JSON page-body Markdown in a systematic header/footer way; this is not an incorrect file pairing.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 1/21 | Running journal header; article type, title, authors and affiliations in the main column; open-access/citation/editor/dates/copyright/data-availability sidebar; abstract headings and opening body; footer at `y≈750`. |
| 2 | 7/21 | Table 1 and its footnotes/link at `x≈34, y≈86–498`; article prose resumes in the lower-right region; running header/footer. |
| 3 | 10/21 | Raster flowchart at `x≈125, y≈83, w≈455, h≈573`; caption and DOI below; running header/footer. |
| 4 | 11/21 | Table 2 and notes/link at `x≈34, y≈88–289`; two-column prose below; running header/footer. |

The opening or closing partial sentences on physical pages 1, 2, and 4 are faithful to the selected source pages. For example, p2 starts at `weekly phone calls...` and ends at `which means that`; this is page-excerpt continuity, not expert truncation.

## Expert element validation

| Element | Expert representation | Status | Source-grounded assessment |
|---|---|---|---|
| Page count/dimensions | Four successful item pages, 612 × 792 | Verified | Matches source. |
| Printed pagination | Footer markup `1/21`, `7/21`, `10/21`, `11/21` | Verified | Matches each visible page. Structured `printed_page_number` remains null. |
| Running headers | Header items | Verified | Journal name and short title are correct. |
| P1 title, authors, affiliations | Heading/text items with superscripts | Verified | Content and semantic order are faithful. |
| P1 sidebar metadata | Text/link/key-value items | Verified | Citation, editor, dates, copyright, peer-review, and data-availability text match the page. |
| P1 icon descriptions | `Check for updates logo`, `Open Access icon` | Potentially inferred | The icons/labels are visible, but these semantic descriptions are not ordinary printed paragraph text and have no provenance marker. |
| Abstract headings and prose | H2/H3 and text | Verified | Correct hierarchy and source-page completeness. |
| Table 1 cell values | Six-column table | Verified | Column order and numeric/text values match the source. |
| Table 1 section structure | HTML colspans for `M (SD)`, `% (n)`, `Marital status`, `Education`, `Occupation` | Partially verified | The labels are correct, but the source places them in the stub column with other cells blank; expert HTML merges each across all six columns. |
| P2 prose and page-boundary fragments | Text items | Verified | Correct two-column reading order and faithful page-boundary fragments. |
| P3 flowchart labels | Mermaid nodes | Verified | Counts and wording are transcribed accurately from raster pixels. |
| P3 flowchart relationships | Mermaid edges/subgraphs | Partially verified | Main allocation/follow-up paths are present, but detail bullets are detached from the Excluded/Non-completer nodes; see below. |
| Table 2 cell values | Table rows | Verified | The substantive values match the source. |
| Table 2 column/span structure | Ten-column rows and HTML | Incorrect | Source has nine columns; expert adds a tenth empty cell and an incorrect four-column final header span. |
| Table 2 footnotes | Text items | Partially verified | Content is otherwise faithful, but `Hedges‘ g` uses the wrong-direction quotation mark versus the source's `Hedges’ g`. |
| P4 prose | Text items | Verified | Correct reading order and faithful selected-page boundary. |
| Captions and DOI links | Caption/link items | Verified | Tables/figure are correctly associated with their links. |
| Major content bboxes | Table/figure regions | Verified | P2 table, p3 figure, and p4 table regions align closely with the source. |
| P1 footer bbox | Composite footer region and children | Incorrect | It spans body content and reuses citation/date body bboxes rather than only the footer. |
| Confidence values | Page 0.881/0.984/0.740/0.976; item scores | Not independently verifiable | No calibration definition; high item confidence coexists with structural errors. |
| Metadata/full fields | Physical pages populated; printed pages null; full fields null | Partially verified | Physical pagination is correct; printed pagination and full serializations are not structured. |

## Concrete expert errors

### Table 1 changes blank-cell structure into merged cells

The source is six columns. Its second row shows `M (SD)` in the left stub only; later section rows similarly place `% (n)`, `Marital status`, `Education³`, and `Occupation` in the stub while the remaining five cells are blank. The expert HTML serializes each as `<th colspan="6">...`.

All substantive values are retained, so the table remains usable for many readers, but its merged-cell ground truth is inaccurate. This matters for cell coordinates, span-aware export, and exact table reconstruction.

### Table 2 is serialized with an extra column

The source has nine columns:

1. Outcomes
2. Time point
3. SbS + CAU
4. n
5. CAU
6. n
7. Mean diff. (95% CI)
8. p-value
9. Effect size

The expert HTML declares header spans of 2 + 4 + 4 = 10 columns, although the final `Linear mixed model analysis` group covers only three source columns. Every body row then receives a tenth empty `<td>`. The JSON `rows` arrays also have length 10. `Primary` and `Secondary`, which appear in the source's first/stub column with the remainder blank, are converted to full-width spans.

This is a confirmed expert structural error even though the displayed values are correct. The expert table must not be used as span/column-count ground truth.

### P3 Mermaid loses containment

The source figure is an embedded raster; all node text and arrows are explicit in pixels. The expert correctly creates the main path:

`Assessed → Included → Randomized → Allocated → post-assessment → follow-up → intention-to-treat`,

with side branches for exclusions, baseline non-completion, and non-completers.

However, `B1`–`B4`, `H1`–`H7`, and `I1`–`I2` are placed in independent Mermaid subgraphs without edges to `B`, `H`, or `I`. In the source, these bullets are text inside the corresponding Excluded/Non-completer box. A Mermaid renderer is therefore free to display them as detached groups and does not preserve the source relationship.

Evidence categories:

- Explicit in raster pixels: every box label, bullet, count, connector, and arrow direction.
- Model-derived: conversion into Mermaid node IDs, subgraphs, and graph layout.
- Unverifiable: whether the generated Mermaid was visually rendered and checked; no rendered derivative is included.

### P1 footer geometry is contaminated by body elements

The actual footer is around `y=750`. The expert composite footer bbox is `x=36, y=519.88, w=540.21, h=237.36`, spanning a large portion of the page. Its child DOI bbox at `y=602.99` points to the peer-review-history link in the sidebar, and a date bbox at `y=519.88` points to the body `Published` date. Those are combined with genuine footer children at `y≈750`. The footer text is correct, but its grounding is not.

## Bounding boxes, confidence, and structured metadata

- Table 1 (`x=34.10, y=86.34, w=542.81, h=411.92`), the p3 chart crop (`x=124.71, y=82.91, w=455.36, h=573.29`), and Table 2 (`x=34.25, y=87.94, w=542.68, h=201.25`) cover the intended regions.
- Table bboxes include many text fragments but do not supply an explicit source-cell grid or stable cell IDs suitable for span validation.
- Diagram nodes and edges have no node/connector-level geometry after conversion to Mermaid.
- Coordinate units/origin are not declared, though values align with PDF points and a top-left origin.
- Item-level confidence does not separate transcription accuracy from structural accuracy.
- Page metadata does not retain the visible non-contiguous printed page labels.

## Standalone Markdown versus JSON page-body Markdown

The standalone Markdown includes the running PLOS headers and footers/page numbers between physical pages. The JSON `markdown.pages[].markdown` bodies exclude those repeated regions while retaining substantive page content. This explains the manifest mismatch and should be treated as two serialization scopes, not as a wrong case pairing.

Top-level `markdown_full` and `text_full` are null. Any evaluator concatenating page bodies must explicitly decide whether repeated headers/footers are expected. It must also preserve the fact that physical pages 1–4 correspond to printed pages 1, 7, 10, and 11.

## Mapped gaps

These findings use the finalized gap taxonomy. Their baseline confirmation
status is recorded in the next section.

| Gap | Mapped capability | Exact evidence |
|---|---|---|
| `GAP-TABLE-002` | Recover multi-level headers, blank cells, section rows, and row/column spans without inventing columns or merges. | Physical p2 / printed p7, Table 1 `x≈34, y≈86–498`; physical p4 / printed p11, Table 2 `x≈34, y≈88–289`. |
| `GAP-DIAGRAM-001` | Preserve diagram nodes, containment, connectors, direction, and evidence geometry in a source-grounded graph. | Physical p3 / printed p10, flowchart `x≈125, y≈83, w≈455, h≈573`; expert detail nodes are detached from their parent boxes. |
| `GAP-BBOX-001` | Prevent region contamination and retain canonical parent/child geometry. | Physical p1 / printed p1, actual footer `y≈750`; expert footer starts at `y=519.88` and absorbs body DOI/date regions. |
| `GAP-PROVENANCE-001` | Distinguish pixel transcription from model-derived structure and calibrate each separately. | P3 raster labels versus Mermaid topology; table values versus span reconstruction. |
| `GAP-PAGE-001` | Retain physical and printed pagination, including non-contiguous excerpts. | Physical pages 1–4 map to printed 1/21, 7/21, 10/21, 11/21; JSON printed page fields are null. |
| `GAP-SERIALIZATION-001` | Define page-body/full-document header and footer semantics. | Headers/footers differ by scope across the supplied views. |
| `GAP-TABLE-003` | Preserve one valid table shape across Markdown, HTML, rows, CSV, and JSON. | Table 2 has a ten-column error across structured forms. |

## Fixed-baseline assessment

Baseline artifacts: [our Markdown](../runs/baseline-20260728-current/clinical-study/our-output.md) and [our JSON](../runs/baseline-20260728-current/clinical-study/our-output.json).

The parse reports success for all four pages and emits 39 top-level items: four headers, four footers, four headings, two images, two tables, one diagram, and 22 text items.

### Source-grounded results

- Verified strengths:
  - All four physical pages, page sizes, non-contiguous footer labels, and major content-region bboxes are retained.
  - Most body prose and substantive table values are present.
  - Table 1 has the correct six-column shape and keeps `M (SD)`, `% (n)`, `Marital status`, `Education`, and `Occupation` in the stub column with five blank cells. This is more faithful than the expert's invented `colspan=6`.
  - Table 2 has the correct nine-column shape, correct 4+3 grouped headers, and stub-only `Primary`/`Secondary` rows. This is more faithful than the expert's ten-column serialization.
  - The p3 figure is correctly detected/classified as a flow chart with a close bbox and an explicit `diagram_relationships_not_structured` concern.
- Confirmed source errors:
  - P1 reading order emits the left metadata/sidebar before the article title and main-column content. The result begins with icon noise (`a1111111111`), `OPENACCESS`, citation/editor/dates, then fuses `Data Availability ... RESEARCHARTICLE` before finally emitting the title.
  - P1 contains native-text integrity errors including `Universita ¨t`, `Babe ș`, `Weconducted`, `Sebastian BurchertID`, and malformed DOI spacing.
  - `Abstract`, `Background`, and `Methods and findings` are all serialized as H1, flattening the source hierarchy.
  - Table 1's caption, all three footnotes, and its visible DOI link are absent from p2. The `.t001` URL is instead appended to the end of the p1 Methods paragraph, where no such visible text occurs.
  - P2 prose contains fused/damaged text such as `CODwas` and `'ehelpers'` instead of `COD was` and `"e-helpers"`.
  - P3 diagram content is emitted twice: first as fragmented token-per-line OCR and then as a second flatter transcription. Parentheses/bullets are lost, labels are corrupt, and no node/edge/containment structure is produced. The figure DOI is omitted.
  - Table 2's caption and all four explanatory footnotes are omitted. One numeric cell is corrupted: source `−0.76 (−2.26, 0.74)` becomes `- 0.76 ( - 2,26, 0.74)`, changing the lower confidence-limit decimal.
  - P4 prose contains `WHODASscores` without the source space.

### Confirmed mapped gaps

| Gap | Severity | Baseline status | Exact baseline evidence |
|---|---|---|---|
| `GAP-ORDER-001` | High | Confirmed | Physical p1 / printed p1 two-column page: sidebar is serialized before the title/main column. |
| `GAP-LAYOUT-001` | High | Confirmed | Physical pp2/4: table captions and notes are dropped despite correct major bboxes. |
| `GAP-TABLE-002` | High | Confirmed for caption/footnote/value integrity; span reconstruction is a source-correct strength | P2 Table 1 `x≈35, y≈87–498` loses caption/notes/link. P4 Table 2 `x≈35, y≈88–289` loses caption/notes and changes `−2.26` to `- 2,26`. |
| `GAP-DIAGRAM-001` | High | Confirmed | P3 / printed p10, flowchart `x≈128, y≈89, w≈447, h≈565`: duplicate/noisy transcription and no structured nodes, containment, or connectors. |
| `GAP-UNICODE-001` | Medium | Confirmed | P1 affiliations contain broken diacritics and Unicode spacing. |
| `GAP-TEXT-001` | Medium | Confirmed | P1 methods and p2/p4 body contain fused words and lost hyphens/spaces. |
| `GAP-SERIALIZATION-001` | Medium | Confirmed | P1 `.t001` link is attached to the wrong page/paragraph; heading levels are flattened; table notes/captions are not serialized with their table. |
| `GAP-OCR-001` | Low | Confirmed | P1 update/open-access icon regions produce `a1111111111` and `OPENACCESS` in primary Markdown without a reliable visual-text policy. |
| `GAP-PAGE-001` | Low | Confirmed | Physical page labels remain 1–4; printed labels 1/21, 7/21, 10/21, 11/21 are only footer text. |

### Source-correct disagreements with the expert

The baseline should receive credit, not a penalty, for both table shapes:

- Table 1 retains one stub cell plus blanks rather than inventing full-width merged section rows.
- Table 2 is nine columns, not the expert's erroneous ten, and uses a three-column final grouped header.

These structural improvements do not cancel the confirmed omissions or the `2,26` numeric corruption. Metrics that compare raw expert HTML will obscure this distinction and must be interpreted through the source review.

## Open questions

- Is the intended table ground truth visual cell occupancy, semantic grouping, or both?
- Should section labels such as `Primary` be represented as one stub cell plus blanks, or as a semantic group object distinct from colspan?
- What canonical graph schema should precede optional Mermaid generation?
- Can printed page labels be populated from footers without confusing them with physical indices?
- What confidence dimensions are intended for OCR/text, layout, table structure, and diagram topology?

## Guardrail

The baseline was assessed read-only. No parser behavior, source artifact, phase/story file, test, or global benchmark aggregate was changed. Expert span, Mermaid, and footer-bbox errors remain excluded from parity targets.
