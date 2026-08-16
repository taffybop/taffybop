# Expert validation: `settlement-agreement`

## Scope and overall assessment

This report validates both the supplied expert Markdown/JSON and the `baseline-20260728-current` output from our parser against the single source PDF page. It is analysis-only; source, expert, and run artifacts were treated as immutable evidence.

The expert output is textually accurate and recovers the percentage table exactly. Its main limitations are weaker semantic typing of enumerated legal clauses, overlapping boxes with undocumented roles, a false datatype parse concern, and derivative images counted as if they were source content. Our baseline also recovers the table exactly and avoids the false concern, with one confirmed `Look-Back` hyphen loss plus page-label/confidence limitations. The final phrase “…and the” is source-complete for this physical page; it must not be labeled a parser truncation.

Status vocabulary:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — substantially supported, with a material qualification.
- **Not independently verifiable** — the output supplies a claim or score for which the source provides no independent test.
- **Incorrect** — contradicted by the source.
- **Potentially inferred** — plausible, but derived or model-interpreted rather than explicit in the source.

## Artifact inventory

| Artifact | Role | SHA-256 |
|---|---|---|
| `benchmark-expertmodeldata/settlement-agreement.pdf` | Ground-truth source | `adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc` |
| `benchmark-expertmodeldata/settlement-agreement.md` | Expert standalone Markdown | `7e86bd18f28470c52ccfa3f5156b56e3cbe01366274233aa4956ae56d4b30a34` |
| `benchmark-expertmodeldata/settlement-agreement.json` | Expert structured output | `cca63534b7853e8ea64ce106dc82629ce3172bfdaba8353cf7b7881d7af137ae` |

- Document category: legal settlement-agreement excerpt.
- Page inventory: 1 portrait page, 612 × 792 PDF units; printed page 24.
- Layout: continuation prose, lettered clauses (a), (b), and (c), an eight-row two-column percentage table, and a centered page number.
- Complex elements: legal outline/list structure, a verbose table header, percentage values, and a paragraph continuing onto the next physical page.
- Native object inventory: 2,699 characters, 446 words, 73 rectangles, no lines, no curves, no raster images, and no annotations.
- Expert job metadata: `tier=agentic`, `cost_optimized=false`, `triggered_auto_mode=false`, orientation 0, page confidence 0.998.

## Source page map

| Physical PDF page | Printed page | Source content | Expert item summary |
|---|---:|---|---|
| 1 | 24 | Continuation paragraph; clauses (a) and (b); percentage table; clause (c), which continues on the next source page | Six prose/table/footer items |

## Expert element validation

| Expert element or claim | Evidence class | Status | Assessment |
|---|---|---|---|
| Continuation paragraph | Explicit text | **Verified** | Wording and reading order match the source. |
| Clauses (a), (b), and (c) | Explicit text | **Verified** for text | The clause markers and all visible words are preserved, including the source typo “of the of”. |
| Explicit list/outline semantics for clauses | Semantic structure | **Partially verified** | Markers remain in plain text, but no explicit list or hierarchy relationship is encoded. |
| Two-column percentage table | Explicit text / vector layout | **Verified** | Header and all eight percentage rows match the source. |
| Final clause ending “…and the” | Explicit text and page boundary | **Verified** | The physical source page itself ends there; this is not expert truncation. |
| Printed page number 24 | Explicit text | **Verified** | Correct. |
| `header_value_type_mismatch` table concern | Model-generated metadata | **Incorrect** | The verbose percentage header is misclassified as a datetime-oriented header. |
| Paragraph and table bounding boxes | Vector geometry | **Partially verified** | Regions are broadly correct, but prose items combine a large box with overlapping line boxes whose semantics are undocumented. |
| Page confidence 0.998 | Model metadata | **Not independently verifiable** | The source cannot establish the score; no item/cell confidence is supplied. |
| Two entries in `images_content_metadata` | Derived parser artifacts | **Incorrect** as a source-image inventory | The PDF has no native raster image; these are a full-page render and table crop. |

## Concrete expert discrepancies and qualifications

### 1. Legal clause hierarchy is implicit rather than structured

The visible `(a)`, `(b)`, and `(c)` markers and clause text are correct. The expert emits them as ordinary prose, however, with no list item type, ordinal, nesting level, or relationship between each marker and its following paragraph/table. This is a semantic limitation, not a missing-text error.

### 2. The table concern is false

The expert reports `header_value_type_mismatch`, treating the verbose first-row header as if it established an expected datetime type. The table visibly maps settlement categories or thresholds to percentage values. The body’s percentage cells are exactly the expected data under that header. The warning is therefore unsupported by the source semantics.

### 3. The page-ending clause is not truncated by the expert

Clause (c) visibly reaches the bottom of printed page 24 and ends with “…and the”. The expert reproduces that text. Because the source page itself continues the sentence onto a later, absent page, this case must be distinguished from parser-side clipping or premature termination.

## Geometry and metadata limitations

- The expert table box, approximately `x=145.29`, `top=398.67`, `width=402.97`, `height=172.06`, aligns with the visible table and has bbox confidence 0.99.
- Prose items can carry both a large paragraph-region box and smaller overlapping line boxes. The schema does not label these as union/line/alternate boxes, so geometry consumers cannot safely interpret their cardinality.
- Item-level confidence is absent. A page-level score of 0.998 cannot show whether list semantics or the false table concern were considered uncertain.
- Native source image count is zero. `images_content_metadata.total_count=2` counts derivative artifacts and should not be used as an inventory of embedded source graphics.

## Explicit, derived, and unverifiable evidence

- All words, clause markers, page number, percentages, and table header text are explicit vector text.
- Table row/column grouping is source-grounded through alignment, fills, and rectangle geometry.
- Treating `(a)`, `(b)`, and `(c)` as a legal outline is a semantic interpretation, but it is strongly evidenced by explicit markers and sequence.
- The continuation beyond “…and the” is **Not independently verifiable** from this one-page source; only the fact that this page ends mid-sentence is verified.
- Confidence and concern-generation logic are model metadata and are **Not independently verifiable** as scores/methods, even where a resulting concern can be shown to be wrong.
- No pixel-only or model-generated image interpretation is needed.

## Standalone Markdown versus JSON representations

The standalone Markdown equals the JSON page header, if any, plus `markdown.pages[0].markdown` and the footer, separated by blank lines and modulo outer whitespace. `markdown_full` and `text_full` are null.

The item table’s `.md` representation uses a pipe table, while the JSON page body—and therefore the standalone Markdown—uses an HTML table. Structured item rows are another view. Consumers must treat item Markdown, page-body Markdown, and standalone Markdown as related but distinct serializations.

## Our baseline output versus source

Reviewed artifacts:

- `runs/baseline-20260728-current/settlement-agreement/our-output.json`
- `runs/baseline-20260728-current/settlement-agreement/our-output.md`

The baseline reports `success`, one native-source table, no images, and no warnings. It is substantially source-faithful: the table is exact and the only concrete body-character omission found is one line-wrap hyphen.

| Baseline element or claim | Status | Source-grounded finding |
|---|---|---|
| Continuation paragraph and clauses (a)–(c) | **Verified** with one exception | All visible words and markers are present, including “of the of”; one `Look-Back` loses its hyphen. |
| Clause (c) phrase `LookBack Date` | **Incorrect** | Source line ending `Look-` plus next-line `Back Date` should normalize to `Look-Back Date`, not `LookBack Date`. Later occurrence is preserved correctly. |
| Explicit legal list semantics | **Partially verified** | Baseline, like the expert, retains markers only as plain paragraph text. |
| Percentage table | **Verified** | Header and all seven participation bands/percentage values match. Baseline bbox `(144.99, 398.14, 547.64, 570.77)` closely matches the visible table. |
| Table concern generation | **Verified** | No false datatype concern is emitted. |
| Final phrase “…and the” | **Verified** | Baseline correctly stops at the physical source boundary. |
| Item geometry/provenance | **Verified** | Each prose/table/footer item has a single, usable native-source box. |
| Item confidence | **Not independently verifiable** / absent | Every baseline confidence field is null. |
| Page-label metadata | **Incorrect** | JSON page label/number is 1 even though the visible printed page is 24; the footer item itself correctly contains `24`. |
| Native image count | **Verified** | `document.image_count=0` matches the source. |

The lost hyphen occurs where the source breaks the compound across lines: `Look-` appears at the end of one vector-text line and `Back` begins the next. This is a reusable dehyphenation boundary case because the correct output must retain rather than remove the explicit semantic hyphen.

Baseline standalone Markdown is exactly the non-empty JSON item `.md` values joined in `reading_order`, modulo outer whitespace. The HTML table is therefore shared by JSON item Markdown and standalone Markdown; structured rows/cells and native provenance remain available only in JSON.

### Confirmed baseline gap disposition

| Gap | Baseline disposition | Evidence |
|---|---|---|
| `GAP-LIST-001` | **Confirmed** | Clause markers remain untyped plain text. |
| `GAP-DIAGNOSTICS-001` | Not observed in baseline | Baseline emits no false table concern. |
| `GAP-BBOX-001` | Not observed in baseline | Baseline uses one non-overlapping box per prose item rather than undocumented union/line duplicates. |
| `GAP-TEXT-001` | **Confirmed** | One line-break-spanning `Look-Back` becomes `LookBack`. |
| `GAP-PROVENANCE-001` | **Confirmed** | Confidence is null for all items, including the table. |
| `GAP-PAGE-001` | **Confirmed** | Printed page 24 is present only as footer content, not page metadata. |

## Mapped gaps

These findings use the finalized gap taxonomy while retaining their baseline
dispositions and exact source regions.

| Gap | Mapped capability | Exact source region | Why reusable |
|---|---|---|---|
| `GAP-LIST-001` | Preserve legal clause/list identity and nesting without changing text | Physical page 1, clauses `(a)`, `(b)`, and `(c)` surrounding the table | Tests semantic structure for legal prose interrupted by a table. |
| `GAP-DIAGNOSTICS-001` | Avoid false datatype concern on percentage tables with verbose headers | Physical page 1 table at approximately `(145.29, 398.67, 548.26, 570.73)` | Tests table validation against actual header/body semantics. |
| `GAP-BBOX-001` | Document overlapping paragraph/line box roles | All long prose items on physical page 1 | Tests whether geometry is usable without guessing box granularity. |
| `GAP-TEXT-001` | Preserve a semantic hyphen across a source line break | Clause (c), `Incentive Payment D Look-` / `Back Date` near the start of the final paragraph | Tests dehyphenation that must distinguish discretionary line-break hyphens from lexical hyphens. |
| `GAP-PROVENANCE-001` | Missing element/table confidence | All baseline items on physical page 1 | Tests whether uncertainty is attributable. |
| `GAP-PAGE-001` | Printed page label not propagated to page metadata | Bottom-center printed `24` | Reuses the excerpt-pagination gap also observed in `postal-10k` and `uber-earnings`. |

## Open questions

1. Should parenthesized legal clauses be serialized as ordered-list items, or as paragraphs with explicit `clause_id` and `level` fields?
2. Are large paragraph boxes plus line boxes intentional? If so, the schema needs a box-role field.
3. Should benchmark evaluation explicitly mark “source page ends mid-sentence” to prevent false truncation findings when only an excerpt is supplied?
