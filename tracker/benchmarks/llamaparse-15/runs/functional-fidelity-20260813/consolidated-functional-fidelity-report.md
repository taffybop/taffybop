# LlamaParse-15 consolidated functional-fidelity report

Assessment date: 2026-08-13  
Reference: LlamaParse Agentic, project `ec7edb70-8bec-4b1b-9a17-451533884780`  
Implementation under test: dependency-valid release-fidelity profile  
Scope: functionality and output quality only

## Release decision

**NOT RELEASE READY for full LlamaParse-equivalent functional fidelity.**

The final source-grounded disposition is **3 fixed, 1 acceptable difference,
and 11 discrepancy found**. No PDF is classified as an exact match. Eleven
PDFs retain at least one independent, source-visible gap, chiefly chart or
diagram organization, visual-origin OCR, reading order, or form/table
presentation.

The final immutable v2 service run is complete: all 15 PDFs returned HTTP 200
for raw JSON and raw Markdown (30/30 responses), all 15 JSON responses
independently revalidate as public `ParseResult` objects, every Markdown
response is byte-identical to `canonical_presentation.full.markdown`, and all
30 pages have a retained render from the production Clearleaf React renderer.
The reference side contains 15 completed LlamaParse Agentic jobs, 15 raw
Markdown files, 15 full JSON responses, 30 rendered DOM captures, and 30
rendered snapshots. There are **0 evidence gaps**.

The deterministic comparator reports **278 functional discrepancy signals, 9
review-required signals, 54 accepted/harmless signals, and 2 hash-bound
resolved API failures**. These are deliberately conservative cross-surface
signals, not 278 independent defects. One unmatched or regrouped component can
produce correlated Markdown, JSON, table, visual, and DOM rows. The
source-grounded disposition is therefore the release decision; the raw signal
set remains intact for audit and reproduction.

## Evidence completeness

| Evidence | Result |
|---|---:|
| Source PDFs / physical pages | 15 / 30 |
| Selected LlamaParse Agentic jobs completed | 15 / 15 |
| Llama raw Markdown / full JSON | 15 / 15 |
| Llama rendered DOM / snapshots | 30 / 30 |
| Service raw Markdown / full JSON | 15 / 15 |
| Service rendered DOM | 30 / 30 |
| Service HTTP 200 outputs | 30 / 30 |
| Service public-model revalidation | 15 / 15 |
| Service Markdown = canonical JSON Markdown | 15 / 15 byte-exact |
| Missing comparison evidence | 0 |
| Upload limit | 20 MiB (`20,971,520` bytes) |
| Largest corpus PDF | `uber-earnings.pdf`, 7,584,019 bytes |

The final service run did not derive the UI from a generic Markdown engine.
It captured the actual Clearleaf canonical/legacy page renderer in its default
Body view. Raw HTTP JSON is also kept separately from the frontend's normalized
JSON projection. On the reference side, raw downloaded Markdown is kept
separately from JSON page Markdown because those LlamaParse surfaces are not
byte-equivalent.

Nine PDFs use a newer immutable LlamaParse rerun captured after an affected
correction: catastrophe, clean energy, clinical, eGov, health, manufacturing,
NY timetable, purchase, and Uber. The remaining six use their initial fresh
2026-08-13 run. `reference-selection.json` binds the choice, job ID, project,
tier, timestamp, and hashes. All 30 files downloaded as `rendered.png` are
valid JPEG/JFIF payloads with an incorrect extension; the artifact manifest
records the detected media type rather than concealing that upstream mismatch.

## Per-PDF source-grounded disposition

| PDF | Status | Corrected or accepted | Remaining functional gap | Primary story ownership |
|---|---|---|---|---|
| `catastrophe-recap` | **discrepancy found** | Public API and terminal table custody fixed; chart routing fixed; `Windstorm Éowyn` and `$690 million (€620 million)` already correct; Llama's inferred Exhibit 8 matrix accepted | Noisy chart OCR and incomplete legend, axis, year, and panel organization | P02-US06, P05-US03/04, P04-US01 |
| `clean-energy` | **discrepancy found** | Chart source evidence and bounded partial organization added; incomplete native layer is not promoted over fuller OCR; inferred values excluded | Six-panel reading order, fused/duplicated/rotated OCR, incomplete axes | P02-US04/06, P03-US04, P05-US03/04 |
| `clinical-study` | **discrepancy found** | Diagram routing, once-only approved OCR, and table UI fixed; unsupported Llama Mermaid details not copied | Sidebar/title order, damaged text/diacritics, flat headings, unresolved raster connectors | P02-US04, P03-US04/07, P05-US10 |
| `component-datasheet` | **discrepancy found** | Caption/list/key-value corrections retained; model-generated board/pinout prose accepted as non-source text | Noisy/incomplete pin labels, unmodeled pin topology, private-use NOTE glyph | P02-US01/06, P03-US02/04/07, P05-US10 |
| `egov-survey` | **discrepancy found** | Native chart text replaces visible `AO`/`4A` OCR with printed `40`/`44` across JSON, Markdown, and UI | Labels are not yet organized into complete year/category series | P02-US06, P05-US03/04 |
| `esg-metrics` | **discrepancy found** | Both explicit uncaptained regions now route as charts; unsafe fused native tokens remain subordinate | Superscripts/column order, small-chart OCR, and series organization | P02-US01/06, P03-US04, P05-US03/04 |
| `finance-10k` | **fixed** | `Apple Inc.` is a running header on all pages and never renders as H1; source-faithful merged bands accepted | No functional gap in reviewed scope; a harmless non-rendering item-level `md` marker remains | P03-US08 |
| `health-report` | **discrepancy found** | First chart's split native glyphs coalesced and promoted once; both regions remain charts; blank table suppressed | Second-chart OCR noise and incomplete axes/series | P02-US06, P05-US03/04 |
| `insurance-acord` | **discrepancy found** | Producer/contact/insured/insurer block renders once as a source-ordered semantic table with 14 labels and 18 blank values; synthetic empty/signature text removed | Lower coverage-grid ownership and visual/logo semantics remain open | P03-US04/06, P04-US01/02, P05-US01 |
| `manufacturing-report` | **discrepancy found** | All five visual regions route as charts; page-1 native labels promoted; `detected_text` remains boolean; no values invented | Residual page-2 OCR, series/curve semantics, caption order, `4.3.` typing | P02-US06, P03-US02/07, P05-US01/03/04 |
| `ny-timetable` | **fixed** | Every page has one title-first 13-column table with 50 service rows; detached `ew`/`741` removed | No functional gap in reviewed timetable/table/OCR scope | P02-US04, P04-US01/02/04 |
| `postal-10k` | **discrepancy found** | API custody fixed; false detached `ClO` removed; authoritative CIO/FERS table rows retained | Detached full FERS paragraph, four missing italic table spans, four em dashes serialized as hyphens | P02-US04/06, P03-US05/08, P04-US01 |
| `purchase-agreement` | **fixed** | Compact top-right deleted draft banner is text, title H1, `Background` H2, exact smart quotes restored, semantic bold/italic retained | No functional gap in reviewed banner/hierarchy/quote/emphasis scope | P01-US04, P02-US04, P03-US05 |
| `settlement-agreement` | **acceptable difference** | All three `Look-Back Date` strings and nested a./b./c., (i)–(iv) order are correct | Quotation styling differs without a functional text or hierarchy loss | P02-US04, P03-US07 |
| `uber-earnings` | **discrepancy found** | Cover-photo gibberish is diagnostic-only; page-2 charts and two page-3 seven-node/zero-edge groups are source-grounded; unsupported arrows excluded | Chart series/value organization, fan geometry, cross-boundary labels, heading/date/footer order | P03-US04/07/08, P05-US03/04/10 |

Each machine finding is retained in
`comparison-final-source-grounded-v2/<case>/evidence.json`. A finding records
the PDF, physical page(s), output surface, severity, expected LlamaParse
projection, actual service projection, hashes/paths, reproduction command,
story owner, acceptance criterion, and focused test anchor. That per-finding
ledger covers document structure and order; Markdown syntax and whitespace;
text integrity and OCR; table counts, spans, matrices, rows, columns, cells,
and serialization; JSON type/page/nesting/order fields; images, charts, and
diagrams; and rendered-DOM text, hierarchy, grouping, tables, links, and media.

## Production corrections and final evidence

1. **20 MiB upload boundary (`P07-US03`)** — backend settings, API adapters,
   frontend validation, examples, and documentation now use exactly
   `20,971,520` bytes. The boundary is accepted and boundary+1 is rejected.
   Independent OOXML/package/model safety caps remain unchanged.

2. **Public projection and terminal custody (`P04-US01`, `P03-US02`,
   `P03-US08`)** — `app/services/pipeline.py` and `app/models.py` now require
   public-reconstructible visual and running-region overlays. The catastrophe
   chart's projected-caption source edge is synthesized only from an exact
   bounded caption ID/text/bbox proof; arbitrary private edges remain rejected.
   Catastrophe and Postal both pass real HTTP JSON validation, and the final
   v2 run retains their table evidence.

3. **Dense tables and UI (`P04-US01/02/04`)** — `tables.py`,
   `table_semantics.py`, the table pipeline, and the Clearleaf table renderer
   recover and present NY's real 13-column grid, preserve merged title/header
   semantics, render strong source-supported candidates, and suppress empty
   visual-owned grids. Health's transient blank table remains absent.

4. **Visual routing and source text (`P05-US01/03/10`, `P03-US02`)** —
   `visual_semantics.py`, new `visual_source_text.py`, and a bounded layout
   custody seam route classifier-unavailable and uncaptained charts/diagrams
   from explicit source evidence. Native text requires finite same-unit owner
   containment, unique lineage, count closure, and a matching hash. No series,
   points, values, arrows, or prose are fabricated. `detected_text` remains a
   strict boolean while text lives in `visual_source_text`/`value`/`md`.

5. **OCR, text order, and semantic rendering (`P02-US04`, `P03-US05/08`,
   `P01-US04`)** — table-owned supplemental OCR is excluded without deleting
   authoritative table content; running regions replay under exact custody;
   source smart quotes and text runs preserve punctuation and emphasis;
   headings and emphasis render as semantic HTML. A fully deleted heading is
   demoted only when source geometry also proves a compact top-right revision
   banner, so legitimate struck headings keep their envelope.

6. **ACORD form semantics (`P03-US04/06`)** — backend and frontend admit
   replacement only for the complete, resolved, blank static
   `parties-and-insurers` group with exact labels, fields, geometry, and
   provenance. Incomplete, entered, ambiguous, non-target, or concern-bearing
   groups fail closed to the generic path.

7. **Benchmark evidence (`P00-US10`)** — the analyzer compares raw Markdown,
   full JSON, table logical/expanded matrices, visual sidecars, per-page DOM,
   and optional pixels. It handles printed labels versus physical page index,
   source-note/footer taxonomy, chart-owned table-shaped regions, immutable
   per-case reference selection, artifact failures, and source-adjudication
   caveats.

Every resolved cluster has focused regression tests and fresh public JSON,
raw Markdown, and rendered-UI evidence for each affected PDF. No discrepancy
was marked resolved from unit tests alone.

## Validation

- Final v2 all-15 public rerun: **15/15 PDFs**, **30/30 HTTP 200**.
- Public JSON revalidation: **15/15**; raw/canonical Markdown parity:
  **15/15 byte-exact**.
- Final UI evidence: **30/30** nonempty rendered DOM pages.
- Comparator/analyzer tests: **14 passed**; final comparison has **0 evidence
  gaps**.
- Frontend frozen-tree validation: **161/161 unit tests**, TypeScript, ESLint,
  production build, and bundle test passed.
- Final backend functional validation: **850 passed** in the deterministic
  non-integration slice (10 integration tests intentionally deselected), plus
  **31 passed** in the exact offline real-corpus slice; no failures, skips, or
  expected failures remained in either executed slice.
- Focused final-contract checks include the catastrophe/Postal HTTP custody
  pair, manufacturing native-text boolean/type and real-corpus projection,
  deleted-heading adversarial/positive geometry, exact upload boundary, NY
  13-column tables, ACORD blank form, visual source grounding, and Uber photo
  suppression.

Latency, CPU, memory, prewarm, socket/sandbox, and exhaustive hardening
campaigns were intentionally excluded unless they blocked correct parsing, as
requested. Historical failures in those suites are not counted as fidelity
defects.

## Comparison policy and remaining blockers

The hash-bound rendered PDF is authoritative when LlamaParse emits generated
image prose, interpolated chart values, fabricated signatures or links, table
matrices that contradict visible source structure, or directed arrows without
visible endpoint/direction proof. Those differences are accepted or left for
review; they are not copied into production to improve a raw diff.

Release readiness remains blocked by source-visible OCR/reading-order issues,
incomplete chart axes/series/panel organization, clinical and component
diagram topology, the ACORD coverage grid, and the remaining Postal formatting
and duplicate-text defects. The implementation is materially improved and all
parse-blocking, table-grid, and final-contract regressions found during this
campaign are corrected, but full LlamaParse-equivalent fidelity is not yet an
accurate claim.

## Evidence index

- [Machine comparison and every finding](comparison-final-source-grounded-v2/report.md)
- [Source-grounded final disposition](source-grounded-final-disposition-v2.json)
- [Hash-bound artifact manifest](artifact-manifest-final-source-grounded-v2.json)
- [Final backend and artifact validation](final-validation-source-grounded-v2.json)
- [Frontend quality and rendered-DOM validation](final-frontend-validation-source-grounded.json)
- [Final service run](service-final-source-grounded-20260813-v2/run.json)
- [Selected reference policy](reference-selection.json)
- [Final API-resolution ledger](resolution-ledger-final-source-grounded-v2.json)
- [Table source-truth audit](table-source-truth-audit.md)
- [Visual source review](visual-source-review.md) and
  [source-semantics ledger](visual-source-semantics-resolution-ledger.json)
- [Text/layout adjudication](text-layout-correction-adjudication-20260813-02/ledger.json)
- [ACORD form-resolution ledger](service-acord-form-fix-20260813-attempt-03/acord-form-resolution-ledger.json)
- Final service artifacts under
  `service-final-source-grounded-20260813-v2/<case>/`: `response.json`,
  `response.md`, `rendered-capture.json`, and per-page `rendered-dom.json`
