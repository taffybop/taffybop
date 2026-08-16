# FFD-002 — Rotation, fusion, duplication, and ordering defects in visual OCR

Status: **Proposed**  
Severity: **Major**  
Priority: **P0**  
Primary story: **P02-US06 / P02-US04**  
Dependencies: **FFD-001 where a native alternative crosses an owner boundary**

## Scope and impact

| PDF | Physical / printed page | Affected content | Surfaces |
|---|---|---|---|
| `catastrophe-recap` | p1 / 7 | chart-origin labels/ticks | JSON OCR/visual value, Markdown, DOM |
| `clean-energy` | p1 / 11 | six-panel rotated labels, years, axes | JSON OCR/visual value, Markdown, DOM |
| `esg-metrics` | p1 / 80 | small fiscal-row chart | JSON OCR/visual value, Markdown, DOM |
| `component-datasheet` | p2 / visible source page 7 | pinout labels | JSON OCR diagnostics/primary visual text, Markdown, DOM |

Source SHA-256 values respectively:

- `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e`
- `161d513c3ffa53ee3967bac6a7bb420d5d60a2008f79b4f7421b83e9b3a11a7d`
- `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9`
- `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`

Users receive fused, rotated, duplicated, noisy, or incorrectly ordered
visual-origin text. This defect covers token normalization and spatial order,
not higher-level chart/diagram structure.

Non-goals:

- Do not copy LlamaParse-interpolated chart values or generated image prose.
- Do not assemble axes/series/panels (FFD-003) or pinout topology (FFD-008).
- Do not globally spell-correct uncertain OCR without source evidence.

## Source-grounded oracle

Expected/source:

- Catastrophe visibly prints the chart title, region legend, y-axis ticks,
  selected years, `Annual total`, and source note.
- Clean Energy visibly has six panels with technology labels, units, axes,
  years, and percentage callouts; 51 exact PDF-layer occurrences are already
  retained, but that native layer is not complete enough to replace all OCR.
- ESG's fiscal-row chart has explicit printed fiscal labels/values. Unsafe
  fused native tokens such as `FY245`/`CY211` are correctly withheld today,
  while residual user-visible OCR remains noisy.
- Component p2's pinout visibly contains many pin labels; current extraction is
  incomplete/noisy.

Current actual:

- Catastrophe chart text is partly noisy/fused.
- Clean Energy has residual rotation, duplication, noise, and ordering errors.
- ESG fiscal-chart text remains noisy in Markdown/UI.
- Component pinout produces broken fragments such as the retained p2 OCR block
  rather than a clean label sequence.

Definition-of-Ready requirement: create a source-rendered line/token oracle for
each region, including normalized scalar, bbox, rotation, occurrence count,
source/native alternative, and expected order. Existing evidence does not
establish a safe complete token list for these four regions.

## Reproducible evidence

- `comparison-final-source-grounded-v2/{catastrophe-recap,clean-energy,esg-metrics,component-datasheet}/evidence.json`
- `service-final-source-grounded-20260813-v2/<case>/response.json`,
  `response.md`, and page `rendered-dom.json`
- `visual-source-adjudication.json`
- `visual-source-semantics-resolution-ledger.json`

Selected LlamaParse roots/jobs:

- `llamaparse-visual-routing-fix/catastrophe-recap/` — `pjb-28bcomrkzsgzg7uvfwiirhnteu3z`
- `llamaparse-visual-routing-fix/clean-energy/` — `pjb-rmfslteo6otbhxp9qj7kv61l50p0`
- `llamaparse/esg-metrics/` — `pjb-dnqqsnjbdx1np5utnrt9nx6fcibd`
- `llamaparse/component-datasheet/` — `pjb-vwv4utu38pi1splat9jlfba1cqrc`

Primary review signals:

- `FID-CATASTROPHE-RECAP-3d0d90699668`
- `FID-CLEAN-ENERGY-bb971422eb7a`
- `FID-ESG-METRICS-849a723b603a`

These are aggregate OCR proxies and require region-level source review. The
Component comparator has no isolated pinout-OCR signal; its broad p2 text row
`FID-COMPONENT-DATASHEET-94aa27605fa9` is correlated only. Markdown/JSON/DOM
text and chart-value findings are correlated cascades, some shared with
FFD-003, and must not be counted as additional defects.

## Root cause

- State: **Hypothesis supported by source review; exact per-region mechanisms
  must be confirmed during Ready**
- Production boundary: spatial OCR occurrence reconciliation, direction
  handling, line construction, and overlap-aware deduplication.
- Why one defect: the shared missing capability is source-geometric OCR token
  normalization before semantic assembly.
- Safety constraints: preserve original OCR and native alternatives; no
  language-model completion; repeated labels at distinct positions must not be
  text-deduplicated.

## Acceptance criteria

1. Ready oracles enumerate all visible target tokens/lines, rotation, bbox, and
   expected order for the four regions.
2. Every oracle occurrence is emitted once at its source position; overlapping
   duplicates are suppressed while spatially distinct repeated labels remain.
3. Approved rotations are normalized to readable line order without changing
   text whose orientation is semantically meaningful.
4. Fused tokens are split or coalesced only with source/native glyph proof;
   uncertain alternatives remain diagnostic and concern-bearing.
5. No target-region gibberish reaches canonical Markdown/UI; JSON preserves the
   original candidate, selection reason, and normalized occurrence evidence.
6. Raw Markdown equals canonical full Markdown, and Clearleaf DOM presents the
   same once-only order.
7. Chart series/values and diagram edges remain unchanged except where a newly
   clean printed label is exposed as unassociated evidence.
8. Fresh four-case LlamaParse/service/UI evidence plus an all-15 drift screen is
   retained and reviewed.

## Generic-production requirements

- Implement normalization from glyph/token geometry, writing direction,
  rotation, engine/source alternatives, confidence, and overlap evidence.
  Production behavior must not branch on benchmark filenames, document hashes,
  case IDs, page numbers, OCR/element IDs, target strings, or fixed coordinates.
- Capability evidence must show that fusion, splitting, rotation, ordering, and
  spatial deduplication are selected by documented reusable predicates, not by
  correction tables containing the observed Catastrophe, Clean, ESG, or
  Component text.
- Add at least one transformed or synthetic visual-text variant with a renamed
  and reserialized PDF, a prepended page, changed labels/numbers, changed font
  and scale, 90°/270° rotations, and shifted duplicate boxes. Expected lines and
  ordering must remain correct without changing production configuration.
- Negative/adversarial variants must cover spatially distinct repeated strings,
  uncertain glyphs, decorative rotation, cross-owner text, ambiguous fusion,
  empty imagery, and a low-confidence candidate that must remain diagnostic.
- Run multiple unrelated real-PDF controls through the same reconciliation
  path, including `egov-survey`, `health-report`, `manufacturing-report`, and
  the Uber p1 photograph, preserving their occurrence counts and provenance.

Genericity closure gates:

- [ ] Genericity review records reusable normalization predicates,
  transformed/synthetic proof, adversarial results, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, target-token patch, or leaked oracle

## Test and rerun plan

- Positive fixtures: 90°/270° label, split glyph word, fused year/footnote,
  repeated label at distinct positions, and source-backed short token.
- Real regressions: one exact source oracle assertion per affected region.
- Adversarial controls: overlapping duplicate, similar non-overlapping labels,
  uncertain glyph, cross-owner text, decorative rotation, and empty photo.
- Control PDFs: `egov-survey`, `health-report`, `manufacturing-report`, and
  `uber-earnings` p1.
- Suites: P02-US04 reconciliation, P02-US06 spatial tokens, P03-US02 visual
  source text, P05 visual schema and source-grounding regressions.
- Rerun all four affected PDFs through both systems, then run the all-15 drift
  gate because OCR reconciliation is shared.

## Immediate affected-benchmark validation (mandatory)

- After every production fix attempt, run the **complete** affected PDFs through
  both LlamaParse and the service: `catastrophe-recap`, `clean-energy`,
  `esg-metrics`, and `component-datasheet`. During a bounded family slice, rerun
  every full PDF touched by that slice; before Done, rerun all four. Page/region
  crops are diagnostic only.
- Write each attempt to a new immutable `FFD-002` evidence folder and record the
  source hashes, parser/model/settings, LlamaParse job IDs, service build/commit
  and configuration, timestamps, and hashes/paths for every preserved artifact.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM and snapshot,
  and the full original JSON response.
- This immediate gate is a **targeted validation of FFD-002**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete affected PDFs are rerun to preserve
  OCR reconciliation in normal pipeline context. For the family fixed in the
  current slice, manually compare only its token/line/rotation oracle and target
  regions below: relevant Markdown OCR fragments and local spatial order, rendered
  visual-owner/text DOM selectors and snapshots, and JSON paths for OCR candidates,
  selected text, rotation, bboxes, confidence, owner association, and provenance.
  Broader unrelated comparison belongs to the control, wave, and final all-15 gates.
- Verify the source-oracle tokens on Catastrophe p1/7, all six Clean Energy
  panels on p1/11, the ESG fiscal chart on p1/80, and the Component pinout on
  p2/visible 7: readable rotation, source-backed fusion/splitting, spatially
  correct order, one occurrence per position, no overlapping duplicates, and
  no target-region gibberish in Markdown or UI. Original uncertain candidates
  must remain diagnostic in JSON rather than being invented or discarded.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the selected family regions, their visual owners, overlapping OCR
  candidates, immediate label neighbors, occurrence counts, and local ordering.
  Any unexpected material change outside that boundary blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Adjudicate every target-region mismatch and every automated drift alert against
  the rendered source and token/line/rotation oracle, recording exact page/region,
  Markdown fragment, snapshot or DOM selector/excerpt, JSON path, expected
  LlamaParse result, service result, and materiality.
- Passing unit tests is insufficient. Any material OCR text, rotation,
  occurrence, order, Markdown, UI, JSON, or provenance symptom keeps the card
  discrepancy/in progress; fix and repeat a fresh full-PDF two-system run until
  every issue-specific assertion passes.

## Story and change record

- Story action: **Add correction ACs to P02-US06 and P02-US04; link downstream
  structure gaps without adding them to this card.**
- Expected production files: unknown until Ready.
- Changed files: none.
- Test commands/results: not run.
- Fresh artifacts/reviewer decision: pending.

## Closure checklist

- [ ] Complete token/line/rotation oracle for every target region
- [ ] Focused regressions fail before fix
- [ ] Production correction complete
- [ ] Positive, negative, adversarial, and controls pass
- [ ] Fresh LlamaParse and service artifacts retained
- [ ] Public JSON validates with original/selected OCR evidence
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Actual Clearleaf DOM reviewed for order and duplication
- [ ] No inferred values, prose, or topology introduced
- [ ] Story, evidence, registry, coverage, and index updated
- [ ] Independent closure review recorded
