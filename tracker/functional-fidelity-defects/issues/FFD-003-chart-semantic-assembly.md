# FFD-003 — Printed chart semantics are not assembled into complete structures

Status: **Proposed**  
Severity: **Critical**  
Priority: **P0**  
Primary story: **P05-US03; P05-US04 only for source-printed or safely measured values**  
Dependencies: **FFD-001, FFD-002**

## Scope and impact

| PDF | Physical / printed pages | Open chart structure |
|---|---|---|
| `catastrophe-recap` | p1 / 7 | legend, axes, selected years, panel organization |
| `clean-energy` | p1 / 11 | six panels, axes, legend, per-panel ordering |
| `egov-survey` | p1 / 37 | printed bar labels into year/category series |
| `esg-metrics` | p1 / 80 | fiscal-row chart series; source column association |
| `health-report` | p1 / 103 | axes, categories, and series for two charts |
| `manufacturing-report` | p1–p3 / visible 11, 15, 38 | five final visual owners' series/curve semantics |
| `uber-earnings` | p2 / 5 | two charts' series and printed endpoints/values |

Source SHA-256:

- Catastrophe `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e`
- Clean `161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d`
- eGov `7b6b95d79149c16297c6f7280caed0e14b7dcd53ad5067cb2657885b90562846`
- ESG `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9`
- Health `fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181`
- Manufacturing `414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f`
- Uber `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`

The regions are generally typed as charts, but their printed labels are not
assembled into useful panels, axes, legends, categories, series, and data
points. Downstream JSON consumers and the rendered UI receive mostly flat text.

Non-goals:

- LlamaParse chart-as-table cells are not requirements when values are not
  individually printed or safely measured from supported geometry.
- Do not invent intermediate values, hidden source data, or semantic prose.
- Do not fix OCR/token ownership in this card; those are prerequisites.

## Source-grounded oracle

Expected/source:

- Preserve every explicitly printed title, label, legend, tick, unit, category,
  and value and associate it to the correct source-visible structure.
- eGov has 24 printed bar values; all must be assigned to their printed
  year/category positions.
- Clean has exactly six visible panels.
- Health has two visible charts; Manufacturing's final contract has five chart
  owners; Uber p2 has two chart owners.
- Catastrophe's exhaustive Llama matrix, Clean inferred bar values, Health
  reconstructed matrices, Manufacturing interpolated time-series values, and
  Uber unprinted intermediate values are baseline overreach and excluded.

Current actual:

- The final source-semantics ledger records `series=0` and `points=0` for the
  reviewed Clean, ESG, Health, Manufacturing, and Uber owners.
- eGov's `40 (20.7%)` and `44 (22.8%)` are now correct in primary text, but the
  printed values remain unassociated.
- Catastrophe retains explicit flat labels but incomplete semantic structure.

Definition-of-Ready oracle: for each chart, enumerate owner ID/bbox, panels,
axes, ticks, categories, legends, series, explicitly printed values, permitted
measurement method/tolerance, and deliberately unresolved marks. No source
value may be admitted solely from LlamaParse output.

## Reproducible evidence

- Per-case: `comparison-final-source-grounded-v2/<case>/evidence.json`
- Service: `service-final-source-grounded-20260813-v2/<case>/`
- Authorities: `visual-source-adjudication.json`,
  `visual-source-semantics-resolution-ledger.json`, `table-source-truth-audit.md`
- Selected reference roots: `llamaparse-visual-routing-fix/` for Catastrophe,
  Clean, eGov, Health, Manufacturing; `llamaparse/` for ESG; and
  `llamaparse-visual-fix/` for Uber. Job IDs are retained in
  `artifact-manifest-final-source-grounded-v2.json`.

Primary chart signals:

- Catastrophe `FID-CATASTROPHE-RECAP-2f395dd7cc5f`
- Clean `FID-CLEAN-ENERGY-0525f89e6046`
- eGov `FID-EGOV-SURVEY-a03a9b3d8143`
- ESG `FID-ESG-METRICS-eacab23ed3e2`, `FID-ESG-METRICS-8a8ae6814176`
- Health `FID-HEALTH-REPORT-70d612f8076b`, `FID-HEALTH-REPORT-593ba60401dc`
- Manufacturing `FID-MANUFACTURING-REPORT-b2e2e0d03819`,
  `FID-MANUFACTURING-REPORT-36509236d9f7`,
  `FID-MANUFACTURING-REPORT-0c1da69598b8`,
  `FID-MANUFACTURING-REPORT-d3eb57d9916e`,
  `FID-MANUFACTURING-REPORT-38e67dcf2f06`
- Uber `FID-UBER-EARNINGS-f16d5ce9c450`, `FID-UBER-EARNINGS-02383585c8a4`

These signals compare whole chart projections and include Llama baseline
overreach. Only the source-printed subset defined by the Ready oracle is
primary; associated text/table/DOM rows are correlated manifestations.

## Root cause

- State: **Confirmed missing semantic assembly; per-family capability limits
  and oracles pending**
- Production boundary: P05 axis/panel/legend/category/series association after
  visual typing and source-text reconciliation.
- Why one defect: all cases lack the same intermediate chart structure rather
  than independent Markdown/JSON/UI fixes.
- Safety constraint: an association requires source geometry/provenance and
  ambiguity closure; unresolved marks stay unresolved with concerns.

## Acceptance criteria

1. Every affected chart has a reviewed oracle enumerating all required and
   deliberately unresolved structures before implementation.
2. Clean emits six ordered panels. All other cases emit exactly the
   source-visible chart-owner count stated above, without chart/table clones.
3. Every oracle title, axis, tick, unit, category, legend, series, and explicitly
   printed value is associated once to the correct owner/panel and source IDs.
4. All 24 eGov printed values are placed in the correct year/category series.
5. A data point is emitted only when its value is explicitly printed or a
   supported P05-US04 measurement has recorded geometry, calibration, method,
   tolerance, and confidence. Otherwise points remain absent.
6. Unsupported log/dual axes, ambiguous swatches, curves, or inferred values
   fail closed with concern codes rather than approximate output.
7. Public JSON validates context-free; raw Markdown equals canonical Markdown;
   the rendered UI groups each chart in source order with no flat-text duplicate.
8. Fresh seven-case reference/service/UI captures pass source review; a final
   all-15 drift screen proves tables, diagrams, photos, and prose did not move.

## Generic-production requirements

- Build chart structures from reusable visual evidence: owner geometry,
  panel/plot regions, axis orientation, tick alignment, legend swatches,
  label-value proximity, series continuity, and source provenance. Production
  behavior must not branch on a benchmark filename/hash/case, page number,
  chart/element ID, title/label string, expected value array, or fixed coordinate.
- Capability evidence must cover each supported chart family independently and
  record finite rules/tolerances for association or measurement. Unsupported
  families and ambiguous marks must remain explicit, concern-bearing gaps rather
  than receive a LlamaParse-derived or benchmark-specific reconstruction.
- Add transformed/synthetic chart variants that rename and reserialize the PDF,
  prepend a page, reorder/resize panels, move legends, change titles/categories/
  values, and vary axis scales and plot geometry. Structure and printed-value
  association must survive without modifying production constants.
- Negative/adversarial variants must include log/dual/descending axes,
  ambiguous swatches, missing ticks, crossing curves, unprinted intermediate
  values, decorative grids, and chart-like tables; no unsupported point or
  series may be fabricated.
- Run multiple unrelated real-PDF controls outside the seven target cases,
  including `finance-10k`, `clinical-study`, `insurance-acord`, and
  `purchase-agreement`, and retain evidence that tables, diagrams, images, and
  prose do not become charts or change order.

Genericity closure gates:

- [ ] Genericity review records per-family capability rules, transformed/synthetic
  proofs, adversarial outcomes, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, embedded expected series, or oracle leak

## Test and rerun plan

- Focused tests: one supported multi-panel chart, grouped/stacked legend chart,
  printed-value series, and curve/unresolved fallback; then one oracle-driven
  assertion for every real chart owner.
- Adversarial: ambiguous swatch, duplicated year label, missing tick, clipped
  baseline, unprinted value from baseline JSON, and chart-shaped table.
- Controls: NY and Postal tables, ACORD form, Clinical diagram, Component image,
  Uber photo, and all already-correct fixed PDFs.
- Suites: P05-US01/03/04, P02-US06, P03-US02/04, P04 visual-impostor gating,
  canonical/public-model/frontend visual tests.
- Rerun all seven affected PDFs through both systems after each bounded family;
  complete an all-15 drift gate at the wave boundary.

## Immediate affected-benchmark validation (mandatory)

- After each bounded chart-family production fix, immediately run every full
  affected PDF in that family through both systems. Before this card is Done,
  run the complete `catastrophe-recap`, `clean-energy`, `egov-survey`,
  `esg-metrics`, `health-report`, `manufacturing-report`, and `uber-earnings`
  PDFs through both LlamaParse and the service; page/owner crops are not closure.
- Store every attempt in a new immutable `FFD-003` rerun folder with source
  hashes, all parser/model settings, LlamaParse job IDs, service build/commit
  and configuration, timestamps, and artifact paths/hashes.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-003**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDFs are rerun to exercise chart
  assembly in normal pipeline context. For the chart family fixed in the current
  slice, manually compare only its source oracle and named chart owners below:
  the relevant Markdown chart/fallback fragments and local placement, rendered
  chart/panel/label-value DOM selectors and snapshots, and JSON paths for owner
  linkage, axes, series, categories, values, evidence, ambiguity, and provenance.
  Broader unrelated comparison belongs to the control, wave, and final all-15 gates.
- Apply the per-chart source oracle to Catastrophe p1/7, Clean p1/11, eGov
  p1/37, ESG p1/80, both Health p1/103 charts, all five Manufacturing owners on
  p1-p3/11,15,38, and both Uber p2/5 charts. Assert every emitted axis, legend,
  category, series, endpoint, and value is source-printed or allowed by an
  approved measured family; unsupported baseline-generated content must not be
  copied merely to resemble LlamaParse.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the target chart owner and panels, its caption, legend, axes,
  categories/series/values, immediate neighboring content, and local order. Any
  unexpected material change outside that boundary blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Source-ground every target-chart mismatch and every automated drift alert;
  retain page/owner snapshots or DOM selectors/excerpts, Markdown fragments, JSON
  paths, expected reference behavior, actual behavior, and harmless/accepted/
  material adjudication.
- Unit or schema tests alone cannot close this card. If any material chart
  structure, association, order, value, Markdown, rendered-UI, JSON, ambiguity,
  or provenance symptom remains, keep it discrepancy/in progress and repeat the
  fix plus fresh full-PDF two-system rerun until all assertions pass.

## Story and change record

- Story action: **Add source-grounded correction ACs to P05-US03. Add P05-US04
  ACs only for an explicitly supported measurement family; do not make Llama
  table parity an acceptance criterion.**
- Expected production files: unknown until Ready and should be split into
  bounded chart-family slices.
- Changed files/tests/artifacts/reviewer: none; remediation not started.

## Closure checklist

- [ ] Per-chart source structure/value oracle complete
- [ ] Baseline-overreach values explicitly excluded
- [ ] Focused real and synthetic regressions fail before fix
- [ ] Bounded production family/families complete
- [ ] Focused, adversarial, and control suites pass
- [ ] Fresh seven-case LlamaParse and service artifacts retained
- [ ] JSON provenance/ambiguity/tolerance contracts validate
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Clearleaf chart grouping reviewed visually and semantically
- [ ] All-15 drift gate passes
- [ ] Stories, evidence, registry, coverage, and index updated
- [ ] Independent closure review recorded
