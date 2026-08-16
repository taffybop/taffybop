# LlamaParse-15 Confirmed Gap Register

Status: Source-reviewed and mapped  
Evidence date: 2026-07-28  
Authority: rendered source page, then source objects; expert and current-parser
outputs are comparison evidence

## Reading this register

A gap is confirmed only when the source page or its objects support the claim.
Failure to reproduce an incorrect, unprinted, inferred, or unverifiable expert
field is not a parser defect. In particular, the current parser is safer than
the expert when it declines to emit unsupported exact chart values or a
signature in a blank field.

Frequency is the observed count in this 15-case corpus, not an estimate of
production prevalence. Root-cause statements are hypotheses until their mapped
story produces diagnostic evidence.

## Index

| Gap | Severity | Primary phase/story | Observed cases |
|---|---|---|---|
| GAP-BENCHMARK-001 | High | P00-US04 | All 15 |
| GAP-BENCHMARK-002 | High | P00-US10 | All 15 |
| GAP-COVERAGE-001 | High blocker | P07-US02/US08/US09 | Corpus-level |
| GAP-UNICODE-001 | Critical | P02-US01–US04 | catastrophe, clinical |
| GAP-TEXT-001 | High | P02-US04/US06 | clinical, ESG, postal, settlement |
| GAP-OCR-001 | High | P02-US04–US06, P05-US06 | 10 visual/dense cases |
| GAP-LAYOUT-001 | High | P03-US01–US03 | catastrophe, clinical, charts |
| GAP-ORDER-001 | High | P03-US04 | clinical, ESG, ACORD, timetable, purchase, manufacturing |
| GAP-PAGE-001 | Medium | P03-US08 | 12 excerpt/report cases |
| GAP-REDLINE-001 | Critical | P03-US05 | purchase |
| GAP-FORM-001 | Critical | P03-US06 | ACORD, component |
| GAP-LIST-001 | Medium | P03-US07 | component, settlement |
| GAP-LINK-001 | Medium | P01-US01/US02 | health, manufacturing |
| GAP-BBOX-001 | High | P01-US01/US02, P03-US04 | 12 cases |
| GAP-TABLE-001 | High | P04-US04 | health, component, ACORD |
| GAP-TABLE-002 | Critical | P04-US01/US02 | clinical, finance, ACORD, timetable, postal |
| GAP-TABLE-003 | High | P01-US03/US04, P04-US01 | clinical, component, finance, timetable, postal |
| GAP-CHART-001 | High | P05-US01/US03/US06 | 8 chart cases |
| GAP-CHART-002 | High | P05-US02–US05/US07–US09 | 7 chart cases |
| GAP-DIAGRAM-001 | High | P05-US10 | clinical, component, Uber |
| GAP-VISUAL-001 | Medium | P06-US01/US05/US06 | component, ACORD, Uber |
| GAP-SERIALIZATION-001 | High | P01-US03/US04 | All 15 contracts; 10 material cases |
| GAP-PROVENANCE-001 | High | P01-US01/US02, P08-US05/US06 | All visual/table cases |
| GAP-DIAGNOSTICS-001 | High | P08-US04–US07 | 12 cases |
| GAP-PERFORMANCE-001 | High | P08-US03/US10 | timetable, Uber |

## GAP-BENCHMARK-001 — Reviewed ground truth is not yet an executable corpus contract

### Evidence

- Benchmark cases: all 15; source page maps and expert statuses are in
  [`cases/`](cases/).
- Source ground truth: 45 files form valid triplets, but reviewed annotations
  currently live in analysis reports rather than approved benchmark schemas.
- Expert output: includes wrong table spans/columns, wrong chart associations,
  a New Zealand→Australia error, unsupported URLs/directions, and a fabricated
  signature.
- Our output: provides the M0 candidate artifacts but cannot be scored safely
  against unreviewed expert fields.

### Classification

- Category: benchmark governance; severity: High; frequency: 15/15 cases.
- Reproducible: Yes. Cross-format relevance: foundational to every format.

### Suspected pipeline stage

Benchmark/ground-truth management, outside production parsing.

### Root-cause hypothesis

The repository began with one catastrophe assessment and has no approved
multi-case annotation/custody workflow. This is a planning conclusion, not a
production-code root cause.

### Expected reusable behavior

Versioned hashes, page/region annotations, evidence classes, review statuses,
custody, and expert-parity masks validate before a result can be scored.

### Feasibility

Current stack; bounded test/reporting work. No model is required.

### Cost and risk

- Accuracy impact: prevents false targets; latency/memory: benchmark-only.
- Regression risk: low; operational complexity: reviewer/custody workflow.

### Backlog mapping

- Existing phase: 00; approved bounded chain: **P00-US04–P00-US09** at
  3/3/5/5/5/5 points. P00-US04 is the primary registry owner; P00-US05–US09
  consume it for claim contracts, 210 reviewed claims, and finite controls.
- Dedicated fixtures: all case manifests plus invalid-hash,
  unsupported-truth, and custody/control negatives.

## GAP-BENCHMARK-002 — No approved immutable corpus runner and semantic report gate

### Evidence

- Benchmark cases: all 15; M0 run
  [`baseline-20260728-current`](runs/baseline-20260728-current/).
- Source truth: severe timetable grid loss still scores 0.974 expert/ours token
  F1 on one page; raw similarity is therefore insufficient.
- Expert/our output: 15/15 executed, but the analysis scripts are not yet an
  approved test capability or release gate.

### Classification

- Category: benchmark execution; severity: High; frequency: corpus-wide.
- Reproducible: Yes. Cross-format relevance: foundational.

### Suspected pipeline stage

Benchmark runner, semantic comparison, and reporting.

### Root-cause hypothesis

Existing baseline work was designed for one fixture and does not provide an
immutable multi-category milestone contract.

### Expected reusable behavior

New run IDs, fixed settings, complete environment/resource identity, reviewed
semantic metrics, explicit errors/skips, and no overwrite.

### Feasibility

Current stack; moderate test/reporting work.

### Cost and risk

- Accuracy: enables valid gates; runtime/storage: all selected documents and
  retained artifacts.
- Regression risk: low to production; metric-design risk: High.

### Backlog mapping

- Existing phase: 00; approved story: **P00-US10**, 5 points.
- Dedicated fixture: reviewed subset plus timeout, changed-hash, collision, and
  partial-run controls.

## GAP-COVERAGE-001 — Corpus cannot close scanned, direct-image, or Office parity

### Evidence

- Corpus: 15 PDFs, 30 pages; every page has native text. There are no direct
  image inputs, fully scanned PDFs, DOCX, PPTX, or XLSX twins.
- Source ground truth: some embedded/raster regions exist, but they do not prove
  whole-document input parity.
- Expert/our output: no result can establish M5 equivalence without equivalent
  source submissions.

### Classification

- Category: test coverage; severity: High blocker; frequency: corpus-level.
- Reproducible: Yes. Cross-format relevance: defining.

### Suspected pipeline stage

Fixture acquisition and cross-format conformance.

### Root-cause hypothesis

The supplied corpus was selected for PDF parsing quality rather than semantic
input twins.

### Expected reusable behavior

Approved pixel-identical direct-image/image-only-PDF/embedded-image twins and
native Office or synthetic semantic twins with common annotations.

### Feasibility

Current stack for crops/synthetic fixtures; rights and semantic Office twins are
partly unknown.

### Cost and risk

- Accuracy: blocks false cross-format claims; runtime/storage: moderate.
- Regression risk: low; operational complexity: custody and authoring.

### Backlog mapping

- Existing phase/stories: 07, P07-US02/US08/US09; no new story.
- Proposed points: unchanged; this remains a Definition-of-Ready blocker.
- Dedicated fixtures: M5 twin set defined in `milestone-plan.md`.

## GAP-UNICODE-001 — Suspicious native mappings and Unicode runs remain corrupt

### Evidence

- [`catastrophe-recap`](cases/catastrophe-recap.md), physical p1/printed p7,
  paragraph near `x≈100, y≈169–184`: source reads
  `Windstorm Éowyn ... €620 million`; expert presentation is correct but its
  repair method is undisclosed; ours emits `É w ... € `.
- [`clinical-study`](cases/clinical-study.md), p1: source names and symbols
  include diacritics; ours contains forms such as `Universita ¨t`.

### Classification

- Category: Unicode/text integrity; severity: Critical; frequency: 2 cases.
- Reproducible: Yes. Cross-format relevance: native PDF, OCR, images, Office.

### Suspected pipeline stage

Native extraction, font audit, selective OCR, text reconciliation.

### Root-cause hypothesis

Confirmed on catastrophe: malformed but present `/ToUnicode` maps are trusted.
Other spacing/diacritic failures may also involve candidate normalization; that
portion remains a hypothesis.

### Expected reusable behavior

Detect suspicious mappings, retain raw glyph evidence, recover only when
embedded-font evidence is safe, otherwise use bounded OCR or emit uncertainty.

### Feasibility

Current stack plus bounded font inspection; optional OCR for unresolved spans.

### Cost and risk

- Accuracy: restores named entities and amounts; latency/memory: low except
  selective crops.
- Regression risk: High if healthy fonts are rewritten; complexity: moderate.

### Backlog mapping

- Existing phase/stories: 02, P02-US01–US04; no new story; 5 points each remain.
- Dedicated fixture: catastrophe bad map, healthy/missing/non-identity fonts,
  clinical diacritic span, multilingual negative.

## GAP-TEXT-001 — Word boundaries, narrow symbols, and critical spans are altered

### Evidence

- [`clinical-study`](cases/clinical-study.md), p1/p4: `We conducted` becomes
  `Weconducted`; table `−2.26` becomes `−2,26`.
- [`esg-metrics`](cases/esg-metrics.md), p1 notes 3–7: superscript markers become
  `$`, `%`, quotes, parentheses; `reflect` becomes `re & ect`.
- [`postal-10k`](cases/postal-10k.md), p1: ours loses the final FERS definition
  and admits false `ClO`; explicit currency glyph behavior varies.
- [`settlement-agreement`](cases/settlement-agreement.md), p1: `Look-Back`
  becomes `LookBack`.

### Classification

- Category: text integrity; severity: High; frequency: 4 cases.
- Reproducible: Yes. Cross-format relevance: all text-bearing formats.

### Suspected pipeline stage

Native/OCR reconciliation, token normalization, line joining, serialization.

### Root-cause hypothesis

Spatial gaps and narrow glyphs appear to be normalized without sufficient
character/run evidence; exact causes must be traced per fixture.

### Expected reusable behavior

Preserve source punctuation/symbols and word boundaries, retain raw alternatives,
and flag unresolved critical spans rather than silently normalizing them.

### Feasibility

Current stack; minor-to-moderate reconciliation work.

### Cost and risk

- Accuracy: High; latency/memory: negligible to low.
- Regression risk: Medium, especially legitimate line-break/hyphen rules.

### Backlog mapping

- Existing phase/stories: 02, P02-US04/US06; no new story.
- Dedicated fixture: cited spans plus positive wrapped prose, financial
  non-target, and ambiguous line-end hyphen.

## GAP-OCR-001 — Noisy, fused, repeated, or hidden OCR enters canonical output

### Evidence

- Catastrophe chart fuses years and drops `1H`; clean-energy duplicates panels,
  admits `‘0'V AB D0 ‘VA`, and reads IEA as `led`.
- EGOV changes printed `40`/`44` to `AO`/`4A`; ESG, health, and manufacturing
  admit rotated-label artifacts and duplicate native/OCR passes.
- Timetable adds `ew`/`741`; postal adds `ClO`; Uber emits false photo OCR and
  hidden construction/chart text not visibly intended as slide content.

### Classification

- Category: OCR/reconciliation; severity: High; frequency: 10 cases.
- Reproducible: Yes. Cross-format relevance: scanned/image/PDF visual regions.

### Suspected pipeline stage

Targeted OCR, token cleanup, candidate scoring, coordinate deduplication,
canonical presentation.

### Root-cause hypothesis

Global thresholds, ASCII-like cleanup, text-only deduplication, and flattening of
multiple passes appear to admit weak candidates or destroy spatial repetition.
Per-case traces must verify each cause.

### Expected reusable behavior

Coordinate-aware candidates, numeric-safe cleanup, geometry-supported short
tokens, source-visible filtering, retained alternatives, and exactly one
canonical representation.

### Feasibility

Current OCR/layout stack; no model required for core fixes.

### Cost and risk

- Accuracy: High; latency: neutral to small scoring overhead; memory: more word
  alternatives.
- Regression risk: High if aggressive suppression removes rare valid labels.

### Backlog mapping

- Existing phase/stories: P02-US04–US06 and P05-US06; no new story.
- Dedicated fixtures: every cited region, repeated-year positive, numeric/hex
  negative, low-confidence short-token ambiguity.

## GAP-LAYOUT-001 — Captions, notes, and footnotes lose ownership or disappear

### Evidence

- Catastrophe p1: Exhibit 7 caption and chart source note are absent; chart
  internal fragments are flattened into its caption-like text.
- Clinical p2/p4: ours preserves more faithful table grids than the expert but
  loses table captions/footnotes; p3 flowchart is duplicated with weak caption
  ownership.
- Health/manufacturing: chart Markdown includes captions outside plot bboxes and
  sometimes serializes them before plot text.

### Classification

- Category: layout relationships; severity: High; frequency: at least 6 cases.
- Reproducible: Yes. Cross-format relevance: tables/charts/figures in all formats.

### Suspected pipeline stage

Graph normalization, caption/child separation, source-note association, crop
routing, reading order.

### Root-cause hypothesis

Existing normalization drops referenced nodes after owner emission or combines
captions and internal children; source notes can fall outside selected crops.

### Expected reusable behavior

Distinct elements with `caption_of`, `source_note_of`, `footnote_of`, and
`contains`, each with source geometry and deterministic order.

### Feasibility

Current stack; minor-to-moderate relationship work.

### Cost and risk

- Accuracy: High; latency/memory: negligible/small IR growth.
- Regression risk: Medium through duplication/order changes.

### Backlog mapping

- Existing phase/stories: 03, P03-US01–US03; no new story.
- Dedicated fixtures: catastrophe exhibits; clinical Tables 1/2 and flowchart;
  health/manufacturing caption controls.

## GAP-ORDER-001 — Columns, running regions, and recovered fragments serialize out of order

### Evidence

- Clinical p1 crosses sidebar/main-column boundaries and appends
  `RESEARCHARTICLE` to sidebar text.
- ESG moves lower-left navigation ahead of right-column charts.
- ACORD contact text from `y≈121–139` appears after the signature region.
- Timetable p2 puts the top title after the table; purchase p1 moves redline top
  matter after all body prose; manufacturing p2 swallows header/caption into a
  chart item.

### Classification

- Category: reading order; severity: High; frequency: 6 cases.
- Reproducible: Yes. Cross-format relevance: multi-column, forms, slides, pages.

### Suspected pipeline stage

Region ownership, column inference, relationship-aware ordering, OCR insertion.

### Root-cause hypothesis

Flattened engine order and late visual/OCR recovery are merged without stable
column/ownership constraints.

### Expected reusable behavior

Geometry/relationship graph order with stable tie-breaking, column/sidebar
boundaries, owner-relative recovered content, and cycle concerns.

### Feasibility

Current stack; bounded but algorithmic.

### Cost and risk

- Accuracy: High; latency: low graph work; memory: small.
- Regression risk: High for overlapping columns and stable IDs.

### Backlog mapping

- Existing phase/story: P03-US04, 5 points; no new story.
- Dedicated fixture: cited cases plus simple single-column non-target and cyclic
  synthetic negative.

## GAP-PAGE-001 — Physical page, printed label, and running regions are conflated

### Evidence

- Physical p1 is printed p7 (catastrophe), p11 (clean), p80 (ESG), p103
  (health), and p24 (settlement).
- Clinical physical pages 1–4 are printed 1/7/10/11; finance pages 1–3 are
  28/30/32; timetable pages 1–3 are 2/3/4.
- Our `page_label` generally remains the physical index; repeated `Apple Inc.`
  changes from header to heading across homologous pages.

### Classification

- Category: metadata/running layout; severity: Medium; frequency: 12 cases.
- Reproducible: Yes. Cross-format relevance: paginated documents/slides.

### Suspected pipeline stage

Header/footer classification, page-label detection, canonical body/full policy.

### Root-cause hypothesis

Page identity is initialized from array position and bare footer numbers are not
promoted to a distinct printed-label field.

### Expected reusable behavior

Preserve physical index, embedded label, detected printed label, confidence/bbox,
and running regions without overwriting array identity.

### Feasibility

Current stack; small-to-moderate.

### Cost and risk

- Accuracy: Medium; latency/memory: negligible.
- Regression risk: body numbers misclassified as labels; presentation churn.

### Backlog mapping

- Existing phase: 03; new story required: **P03-US08**, 3 points.
- Dedicated fixture: cited excerpts plus body-number and absent-label negatives.
- Readiness update (2026-08-01): the original 3-point planning estimate above
  is retained as history; independent source/projection, replay, frontend,
  resource, and metrics-contract review re-estimated P03-US08 to 5 points.

## GAP-REDLINE-001 — Legally material deletion and insertion state is lost

### Evidence

- [`purchase-agreement`](cases/purchase-agreement.md), p1 top and opening date:
  source has red struck `Draft of 6/1/20`, struck `June`/`23`, and a blue
  underlined placeholder.
- Expert preserves some banner strike syntax but flattens the dates; ours keeps
  tokens but loses all redline state and moves the banner after the body.

### Classification

- Category: text-run/layout semantics; severity: Critical; frequency: 1 case.
- Reproducible: Yes. Cross-format relevance: redlined PDF, DOCX, images.

### Suspected pipeline stage

Vector/text-run evidence, layout relationships, shared IR, serialization.

### Root-cause hypothesis

Text color and intersecting line/rectangle geometry are discarded during
normalization; the parser retains only plain character streams.

### Expected reusable behavior

Exact run bboxes, style/rule evidence, deletion/insertion/placeholder or
ambiguous state, redline and active views, never silent evidence loss.

### Feasibility

Current PDF vector stack; moderate cross-component work.

### Cost and risk

- Accuracy: Critical legal meaning; latency/memory: low.
- Regression risk: High if decorative/table rules become changes.

### Backlog mapping

- Existing phase: 03; new story required: **P03-US05**, 5 points.
- Dedicated fixture: purchase p1, underlined-heading non-target, table-rule and
  ambiguous-overlap negatives.

## GAP-FORM-001 — Static form fields, blank values, and controls are not represented

### Evidence

- [`insurance-acord`](cases/insurance-acord.md), p1: 125 lines, 20 rectangles,
  no widgets/annotations. Both parsers lose producer/coverage grid ownership;
  ours omits static checkboxes and has no field/control records.
- Expert additionally fabricates `[signature]` in a blank region; ours safely
  does not.
- [`component-datasheet`](cases/component-datasheet.md), p2/p3: aligned GPIO/pin
  and operating-condition pairs become unrelated text or ambiguous table data.

### Classification

- Category: forms/key-values; severity: Critical; frequency: 2 cases.
- Reproducible: Yes. Cross-format relevance: PDF, scans, direct images, Office.

### Suspected pipeline stage

Layout grouping, static control detection, form/table classification.

### Root-cause hypothesis

The current model exposes text/tables but has no form field/control relationship
contract; aligned pairs are flattened and drawn boxes treated as generic rules.

### Expected reusable behavior

Form/group/field/label/value/control records; explicit blank and static
checked/unchecked/ambiguous states; no fabricated values.

### Feasibility

Current layout/vector/OCR stack; complex but bounded.

### Cost and risk

- Accuracy: Critical for automation; latency/memory: low-to-moderate geometry.
- Regression risk: decorative squares and table cells becoming controls.

### Backlog mapping

- Existing phase: 03; new story required: **P03-US06**, 5 points.
- Dedicated fixture: ACORD, datasheet pairs, true table non-target, decorative
  square and ambiguous-control negatives.

## GAP-LIST-001 — Nested lists and legal clauses lose hierarchy

### Evidence

- Component p1 nested feature bullets are flattened into arrays without parent
  levels.
- Settlement p1 clauses `a.`–`c.` remain plain text around an intervening
  percentage table; text is source-correct but outline relationships are absent.

### Classification

- Category: list/outline layout; severity: Medium; frequency: 2 cases.
- Reproducible: Yes. Cross-format relevance: technical/legal/Office documents.

### Suspected pipeline stage

Layout grouping, marker/indent inference, canonical serialization.

### Root-cause hypothesis

Normalization preserves strings but does not retain marker/indent hierarchy or
continuity across other elements.

### Expected reusable behavior

Marker, ordinal, level, parent, continuation, bbox, and provenance with
conservative ambiguity handling.

### Feasibility

Current stack; moderate.

### Cost and risk

- Accuracy: Medium; latency/memory: negligible.
- Regression risk: parenthesized prose/financial rows becoming lists.

### Backlog mapping

- Existing phase: 03; new story required: **P03-US07**, 3 points.
- Dedicated fixture: component/settlement, related positive, financial/legal
  non-target, ambiguous marker negative.
- Readiness update (2026-08-01): the original 3-point planning estimate above
  is retained as history; independent architecture, fixture, canonical-custody,
  terminal-replay, frontend, resource, and metrics review re-estimated
  P03-US07 to 5 points.

## GAP-LINK-001 — PDF link targets are flattened or unsupported targets are invented

### Evidence

- Health p1 has two visible StatLinks backed by PDF annotations; ours emits
  ordinary text/URL rather than link objects.
- Manufacturing p3 has annotation-backed BLS URL flattened to text.
- ESG expert adds a Micron sustainability URL despite no visible URL and zero
  PDF annotations; ours safely omits the target but loses the visible `>`.

### Classification

- Category: link/provenance; severity: Medium; frequency: 3 cases.
- Reproducible: Yes. Cross-format relevance: PDF and Office relationships.

### Suspected pipeline stage

Input adapter, shared IR annotation relationships, serialization.

### Root-cause hypothesis

Annotation targets are not modeled as evidence-linked relationships, while
semantic post-processing may invent plausible targets.

### Expected reusable behavior

Visible anchor text and source annotation target remain distinct, with bbox,
method, and a no-inference rule for absent targets.

### Feasibility

Current PDF/IR stack; small-to-moderate.

### Cost and risk

- Accuracy/security: prevents invented or lost destinations; latency: negligible.
- Regression risk: malformed/external links and privacy/security policy.

### Backlog mapping

- Existing phase/stories: P01-US01/US02; no new story.
- Dedicated fixture: health/manufacturing annotations, ESG no-annotation
  negative, malformed/external-link control.

## GAP-BBOX-001 — Coarse or overlapping boxes do not ground represented content

### Evidence

- Expert chart rows generally have one plot box and no cell/mark boxes; clinical
  footer includes body regions; ACORD table spans disclaimer/description.
- Our chart items serialize captions outside plot bboxes; timetable table boxes
  are accurate while their 12-column structure is wrong; diagram boxes do not
  ground nodes/edges.

### Classification

- Category: geometry/provenance; severity: High; frequency: 12 cases.
- Reproducible: Yes. Cross-format relevance: all spatial formats.

### Suspected pipeline stage

Shared IR, ownership validation, structured extraction, serialization.

### Root-cause hypothesis

Region-level boxes survive, but child/field ownership and box roles are flattened
or never created; containment is not validated against presentation.

### Expected reusable behavior

Declared coordinate units/transforms and primary/child box roles for every
represented span, cell, control, mark, node, and edge; presentation cannot claim
unowned text.

### Feasibility

Current stack for most native/OCR elements; derived mark/edge boxes require
Phase 04/05 work.

### Cost and risk

- Accuracy/auditability: High; memory/output size: moderate.
- Regression risk: box cardinality/API growth and coordinate transforms.

### Backlog mapping

- Existing stories: P01-US01/US02, P03-US04; no new story.
- Dedicated fixture: clinical footer, ACORD grid, timetable, charts/diagrams,
  coordinate transform negatives.

## GAP-TABLE-001 — Table candidate gating admits impostors and misses aligned structure

### Evidence

- Health p1 bubble chart is emitted once as chart and again as a false
  one-column table over the same region.
- Component p3 key-value block is emitted as separate text rather than an
  explicit key-value/table alternative.
- ACORD form/table candidates are forced into unusable grids without a clear
  form alternative or structural concern.

### Classification

- Category: table detection/classification; severity: High; frequency: 3 cases.
- Reproducible: Yes. Cross-format relevance: tables, charts, forms, images.

### Suspected pipeline stage

Layout/table candidate classification and overlap reconciliation.

### Root-cause hypothesis

Aligned native text is promoted without respecting competing visual/form region
ownership; borderless and key-value evidence lacks a common candidate gate.

### Expected reusable behavior

Score grid/alignment/coverage and competing ownership; select table,
form/key-value, visual fallback, or unresolved alternative deterministically.

### Feasibility

Current stack; complex but bounded.

### Cost and risk

- Accuracy: High; latency: low-to-moderate scoring; memory: alternatives.
- Regression risk: real borderless tables withheld or visuals promoted.

### Backlog mapping

- Existing phase: 04; new story required: **P04-US04**, 5 points.
- Dedicated fixture: health, component, ACORD, financial positive, aligned-prose
  negative.

## GAP-TABLE-002 — Grid, header, span, row, and multiline fidelity fails silently

### Evidence

- Timetable p1–p3: source 13 columns/50 service rows; ours emits 12 columns and
  49 rows per page with merged/shifted cells.
- ACORD: both current tables lose essential header/cell/control ownership.
- Clinical: ours is more source-faithful than expert on 6/9-column topology, but
  captions/footnotes and one value punctuation fail; expert creates wrong spans.
- Finance ours improves expert spans/wrapped row, showing source review must
  permit parser-better outcomes; postal exposes multi-row header concerns.

### Classification

- Category: table structure; severity: Critical; frequency: 5 cases.
- Reproducible: Yes. Cross-format relevance: native/scanned/image/Office tables.

### Suspected pipeline stage

Table extraction, cell alignment/span inference, evidence reconciliation,
validation/concerns.

### Root-cause hypothesis

Thin/narrow/rotated or irregular grids exceed current alignment heuristics;
region-level success is accepted without row/column/cell invariants.

### Expected reusable behavior

Explicit cell bboxes, row/column/header/span topology, multiline ownership,
source coverage, candidate alternatives, and fail-closed structural concerns.

### Feasibility

Current Docling/pdfplumber stack; bounded but high regression risk.

### Cost and risk

- Accuracy: Critical; latency/memory: moderate on dense grids.
- Regression risk: High across ruled/borderless/merged tables.

### Backlog mapping

- Existing stories: P04-US01 (re-estimated 3→5) and P04-US02; no additional
  story beyond P04-US04 gating.
- Dedicated fixture: timetable, ACORD, clinical, finance/postal positives,
  conflicting-grid negative.

## GAP-TABLE-003 — Table representations disagree or preserve invalid structure

### Evidence

- Expert clinical Table 2 has 10 cells in rows/HTML for a 9-column source;
  component raw HTML contains Markdown emphasis as literal cell text.
- Expert timetable/Postal item rows, item HTML, page-body Markdown, CSV, and
  standalone Markdown encode different headers/spans.
- Our JSON and Markdown are projection-consistent, but consistently propagate
  the invalid 12-column timetable and malformed ACORD grids.

### Classification

- Category: table serialization; severity: High; frequency: 5 cases.
- Reproducible: Yes. Cross-format relevance: every table consumer.

### Suspected pipeline stage

Canonical IR/presentation and table serializers.

### Root-cause hypothesis

Representations are generated from different intermediate shapes or serialize
an unvalidated canonical grid.

### Expected reusable behavior

One validated table model projects HTML, Markdown, CSV, and JSON consistently;
span-capable views remain traceable to the same cells.

### Feasibility

Current stack; moderate.

### Cost and risk

- Accuracy/compatibility: High; latency: negligible; memory: small.
- Regression risk: downstream snapshots and span normalization.

### Backlog mapping

- Existing stories: P01-US03/US04 and P04-US01; no new story.
- Dedicated fixture: clinical/component/timetable/postal/ACORD representations,
  invalid-shape negative.

## GAP-CHART-001 — Explicit chart structure is noisy, flattened, or absent

### Evidence

- Clean-energy six panels lose panel/axis/bar relationships and duplicate labels.
- EGOV has 24 explicitly printed segment values; ours fails to structure them
  and corrupts `40`/`44`.
- ESG/health/manufacturing/Uber charts preserve some captions/labels but lose
  swatch, series, category, rotated-label, point, or stack association.
- Catastrophe drops `1H` and fuses repeated years.

### Classification

- Category: chart structure; severity: High; frequency: 8 cases.
- Reproducible: Yes. Cross-format relevance: vector/raster/images/Office charts.

### Suspected pipeline stage

Chart typing, label OCR/native recovery, axes/legend/series/category association.

### Root-cause hypothesis

Regions are classified as charts, but the current pipeline stops at flat OCR and
does not preserve spatial label/mark relationships.

### Expected reusable behavior

Chart/panel/axis/tick/unit/legend/series/category/printed-label records with
geometry and explicit fallback.

### Feasibility

Current vector/OCR stack for supported charts; optional local visual fallback
for difficult raster labels.

### Cost and risk

- Accuracy: High; latency/memory: low-to-moderate vector, higher raster.
- Regression risk: wrong label/series association.

### Backlog mapping

- Existing stories: P05-US01/US03/US06; no new story.
- Dedicated fixtures: all cited charts, simple positive, non-chart visual
  non-target, ambiguous legend negative.

## GAP-CHART-002 — Derived values lack a safe evidence, tolerance, and validation contract

### Evidence

- Catastrophe expert values include material year shifts and impossible
  annual<1H relation; clean-energy exact values are unprinted and sometimes
  materially above vector bars.
- Health expert supplies 112 unprinted cells and often follows text-label
  placement rather than bubble centers.
- Manufacturing expert has wrong printed stack associations and ungrounded
  line/raster samples; Uber intermediate values are plausible vector
  measurements but not literal source data.
- Our parser emits zero structured chart values, correctly avoiding fabrication
  but leaving achievable printed/vector structure unused.

### Classification

- Category: chart measurement/validation; severity: High; frequency: 7 cases.
- Reproducible: Yes. Cross-format relevance: vector, raster, Office charts.

### Suspected pipeline stage

Vector/raster mark measurement, calibration, provenance, validation,
serialization.

### Root-cause hypothesis

No local structured chart service exists; the expert transformation does not
disclose methods/tolerances and sometimes loses category association.

### Expected reusable behavior

Evidence priority, mark/axis calibration, explicit/vector/pixel/model method,
numeric tolerance, validation, and withholding. Exact latent values with no
source/dataset are explicitly not reliably achievable.

### Feasibility

Current stack for supported vector charts; raster CV is costlier; optional models
may assist structure but never prove hidden exact data.

### Cost and risk

- Accuracy: High; latency/memory: moderate vector, potentially high raster/model.
- Regression/hallucination risk: Critical without provenance and validators.

### Backlog mapping

- Existing stories: P05-US02–US05 and P05-US07–US09; no new story.
- Dedicated fixture: all chart cases, authoritative synthetic data, wrong-year,
  wrong-stack, impossible-value, and unknowable-value negatives.

## GAP-DIAGRAM-001 — Diagram nodes, containment, connectors, and direction are unstructured

### Evidence

- Clinical p3: ours emits noisy diagram text plus a duplicate image and
  `diagram_relationships_not_structured`; expert Mermaid detaches bullet content
  from containing nodes.
- Component p2: explicit pin/test-point labels are noisy/unusable and relations
  absent.
- Uber p3: ours has no graph; expert converts wedge associations to directed
  arrows although source shows no arrowheads.

### Classification

- Category: diagram topology; severity: High; frequency: 3 cases.
- Reproducible: Yes. Cross-format relevance: raster/vector/slides/images.

### Suspected pipeline stage

Diagram typing, node/connector detection, containment/direction validation.

### Root-cause hypothesis

Current support stops at OCR/fallback; expert semantic conversion overstates
direction and does not ground edges.

### Expected reusable behavior

Nodes, labels, containers, connector paths, endpoints, explicit/ambiguous
direction, edge-level bboxes, and safe fallback without invented arrows.

### Feasibility

Current geometry/OCR for basic supported diagrams; optional model for complex
cases under grounding.

### Cost and risk

- Accuracy: High; latency/memory: moderate; model path potentially high.
- Regression/hallucination risk: High for edge direction.

### Backlog mapping

- Existing story: P05-US10, 5 points; no new story.
- Dedicated fixture: clinical/component/Uber, explicit-arrow positive,
  undirected-association negative, disconnected/overlap control.

## GAP-VISUAL-001 — Source pixels, generated descriptions, and icon identities are conflated

### Evidence

- Component expert emits plausible unmarked board/pin descriptions; ours avoids
  those claims but produces unusable OCR and generic placeholders.
- ACORD expert calls the mark a logo and fabricates a signature; ours safely
  omits signature but cannot expose `ACORD` semantically.
- Uber expert mislabels New Zealand as Australia; ours emits false photo OCR and
  no grounded flag/image semantics.

### Classification

- Category: image/icon semantics; severity: Medium; frequency: 3 cases.
- Reproducible: Yes. Cross-format relevance: images, scans, embedded images,
  slides.

### Suspected pipeline stage

Visual routing, optional model contracts, observation grounding/merge.

### Root-cause hypothesis

There is no enabled grounded description/identity path in M0, while the expert
does not consistently distinguish generated prose from transcription.

### Expected reusable behavior

Separate visible OCR, source caption, deterministic class, and generated
description/identity; cite pixels/regions; reject blank or contradictory claims.

### Feasibility

Minor deterministic improvements for logos; optional local/hosted model for open
visual semantics; some fine-grained identities remain uncertain.

### Cost and risk

- Accuracy: Medium; model latency/memory/cost: potentially high.
- Regression/privacy/hallucination risk: High; hosted path policy-gated.

### Backlog mapping

- Existing stories: P06-US01/US05/US06; no new story.
- Dedicated fixture: component/ACORD/Uber, blank-signature negative,
  look-alike flag/icon controls, no-model fallback.

## GAP-SERIALIZATION-001 — Canonical projections propagate duplicates or follow inconsistent scope rules

### Evidence

- Expert standalone Markdown matches joined page bodies for only 2/15 cases;
  header/footer/full/body/item semantics vary and `markdown_full`/`text_full`
  are null.
- Our Markdown is exactly the ordered JSON item Markdown in 15/15 cases, but
  this propagates false tables, duplicate chart passes, generic placeholders,
  and late/misowned fragments unchanged.
- Multiple expert cases differ among item Markdown, HTML, rows, CSV, and page
  Markdown.

### Classification

- Category: serialization; severity: High; frequency: contract-wide.
- Reproducible: Yes. Cross-format relevance: every output surface.

### Suspected pipeline stage

Canonical IR presentation, backend/frontend serializers, body/full policy.

### Root-cause hypothesis

Expert artifacts expose several independently generated views. Our single path
has parity but lacks semantic/ownership validation before serialization.

### Expected reusable behavior

One validated IR, deterministic per-element/page/body/full projections,
relationship-based deduplication, documented header/footer policy, and frontend
parity.

### Feasibility

Current stack; moderate cross-backend/frontend work.

### Cost and risk

- Accuracy/consistency: High; latency: negligible; memory: small.
- Regression risk: High downstream snapshot/content changes.

### Backlog mapping

- Existing stories: P01-US03/US04; no new story.
- Dedicated fixture: all case JSON/Markdown pairs, duplicated visual/table
  negative, old-schema fallback.

## GAP-PROVENANCE-001 — Field-level method and confidence do not match the represented claim

### Evidence

- M0 top-level bbox/provenance coverage is 100%, but confidence coverage is
  23.02%; tables generally have null confidence.
- Expert chart/table values often have one region confidence with no cell/mark
  method; high scores coexist with wrong values, spans, and grid associations.
- Our chart classification confidence does not measure label completeness,
  structure, or value accuracy; malformed ACORD/timetable tables have no
  structural confidence/concern.
- Expert image counts often combine source images and derived renders/crops.

### Classification

- Category: provenance/confidence; severity: High; frequency: all structured or
  visual cases.
- Reproducible: Yes. Cross-format relevance: foundational.

### Suspected pipeline stage

Shared IR, evidence merge, confidence model, serializers/telemetry.

### Root-cause hypothesis

Current provenance identifies a producing path at item level, not the evidence
and task dimension behind each claim.

### Expected reusable behavior

Per-span/cell/control/mark/node/edge method, source-vs-derived asset origin,
geometry, alternatives, and separate detection/recognition/structure/
relationship/value/grounding confidence.

### Feasibility

Current stack for evidence contracts; calibration requires reviewed data and
Phase 08 measurement.

### Cost and risk

- Accuracy/auditability: High; output/memory: moderate.
- Regression risk: schema growth and misleading pseudo-probabilities.

### Backlog mapping

- Existing stories: P01-US01/US02 and P08-US05/US06; no new story.
- Dedicated fixture: all reviewed structured/visual cases plus confidence
  calibration and source/derived-image controls.

## GAP-DIAGNOSTICS-001 — Material failures are silent, missing, or misclassified

### Evidence

- M0 reports 0 document warnings for all 15 cases despite source-confirmed
  critical/high gaps.
- Timetable's three invalid grids and ACORD's malformed tables have empty
  table concerns; purchase redline loss is silent.
- Uber records three Tesseract orientation-detection failures only on stderr
  while the structured result still reports zero document warnings.
- Some expert concerns are false (`header_value_type_mismatch` on percentage/
  financial/key-value tables), while high page confidence hides errors.
- Our chart/diagram fallback concerns are useful but do not cover OCR noise,
  label loss, duplicated representations, or false tables consistently.

### Classification

- Category: quality diagnostics/calibration; severity: High; frequency: 12 cases.
- Reproducible: Yes. Cross-format relevance: all formats.

### Suspected pipeline stage

Quality instrumentation, confidence calibration, validation, review routing.

### Root-cause hypothesis

Concern generation is stage-local and not evaluated against source coverage,
structural invariants, competing candidates, or calibrated task confidence.

### Expected reusable behavior

Typed local concerns for missing/duplicate/unsupported/invalid structure,
calibrated confidence dimensions, document-level aggregation, and grounded
review packets.

### Feasibility

Current stack after earlier evidence/validators; calibration needs reviewed
corpus growth.

### Cost and risk

- Accuracy/operations: High; latency: low; review cost: potentially moderate.
- Regression risk: alert noise and poorly calibrated thresholds.

### Backlog mapping

- Existing stories: P08-US04–US07; no new story.
- Dedicated fixture: every confirmed silent/false concern, clean financial
  non-target, ambiguity and review-budget controls.

## GAP-PERFORMANCE-001 — Canonical latency and resource evidence require enforcement

### Evidence

- The authenticated 2026-08-08
  [LlamaParse latency reference](latency-reference-v1.md) now owns unfinished-
  phase latency acceptance. Its 15 initial rows are one-sample planning
  ceilings, so repeated paired distributions are still required.
- The M0 network-disabled local parser remains resource evidence only: median
  peak RSS 1,437 MiB and maximum 2,590 MiB (`uber-earnings`). Its durations are
  retired from latency acceptance.
- Optional visual models were disabled and external model cost was zero, so
  later capabilities can only increase resource pressure without explicit
  gates.

### Classification

- Category: performance/resource; severity: High; frequency: two maxima plus
  corpus-wide measurement.
- Reproducible: exact provider job identities are recorded; at least five
  interleaved samples per applicable case are still required.
- Cross-format relevance: all formats and optional models.

### Suspected pipeline stage

Document stages, table/visual processing, worker lifecycle, telemetry/release
gate.

### Root-cause hypothesis

The run used isolated cold workers and heavyweight local engines; attribution by
stage is not yet instrumented. No unverified cause is asserted.

### Expected reusable behavior

Per-case candidate/LlamaParse p50/p95, stage attribution, CPU/RSS/output/model-
cost metrics, reference environment, regression attribution, canary blocking,
and rollback.

### Feasibility

Current stack for instrumentation; optimization feasibility remains unknown
until attribution.

### Cost and risk

- Accuracy tradeoff: gates must not reward disabling required quality.
- Latency/memory impact: instrumentation low; operational complexity: moderate.
- Regression risk: noisy hardware measurements and cold/warm ambiguity.

### Backlog mapping

- Existing stories: P08-US03 and P08-US10; P00-US10 establishes runner evidence.
- Proposed points: unchanged at 5 each.
- Dedicated fixtures: `ny-timetable`, `uber-earnings`, representative small
  PDFs, repeated cold/warm/concurrency controls.
