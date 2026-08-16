# FFD-004 — Relationship-aware reading order and running/caption ordering are incomplete

Status: **Proposed**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P03-US04 / P03-US08**  
Dependencies: **FFD-001 and FFD-002 for visual-owned text; removal/generalization of the pre-existing fixture gates recorded in `../pre-remediation-genericity-audit.md`**

## Scope and impact

| PDF | Physical / printed pages | Source-visible order issue | Surfaces |
|---|---|---|---|
| `clinical-study` | chiefly p1 / 1/21; broad text signal spans p1–p4 | sidebar/title and body order | JSON item/canonical order, Markdown, DOM |
| `esg-metrics` | p1 / 80 | source column/reading order | JSON item/canonical order, Markdown, DOM |
| `manufacturing-report` | p1–p3 / 11, 15, 38 | caption/owner ordering | JSON relationships/order, Markdown, DOM |
| `uber-earnings` | p1–p3 / 1, 5, 6 | title/date/footer/note and construction-text ordering/filtering | JSON item/running-region order, Markdown, DOM |

Source hashes:

- Clinical `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`
- ESG `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9`
- Manufacturing `414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f`
- Uber `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`

Non-goals:

- Do not repair OCR scalars (FFD-002/FFD-006), heading levels (FFD-005), or
  chart structures (FFD-003).
- Do not reorder from linguistic plausibility alone.
- Do not remove source-visible running content from full/evidence views.

## Source-grounded oracle

Expected/source:

- Clinical's main title precedes its metadata/sidebar stream; prose follows the
  source's column flow.
- ESG preserves the visible report-column sequence without interleaving chart,
  footnote, or navigation content.
- Manufacturing captions/source notes remain adjacent to and ordered with the
  correct chart owner.
- Uber preserves cover title/subtitle/date, slide headings/body, source notes,
  and footer/page identity in their appropriate body/header/footer roles;
  chart construction text is not emitted as surrounding prose.

Current actual is the v2 disposition's broad order gap: Clinical sidebar can
precede the title, ESG column order is degraded, Manufacturing retains caption
order differences, and Uber retains heading/date/footer and construction-text
filtering differences.

Definition-of-Ready oracle: record the exact public item IDs, source bboxes,
roles, atomic bundles, and expected sequence for each affected page. The
disposition does not establish a complete item-by-item order, and the broad
comparator sequence diff includes unrelated content differences.

## Reproducible evidence

- `comparison-final-source-grounded-v2/{clinical-study,esg-metrics,manufacturing-report,uber-earnings}/evidence.json`
- `service-final-source-grounded-20260813-v2/<case>/response.json`, canonical
  presentation, `response.md`, and per-page `rendered-dom.json`
- `comparison-text-render-fix/source-truth-text-render-review.md`
- Selected references: `llamaparse-visual-routing-fix/clinical-study/`,
  `llamaparse/esg-metrics/`,
  `llamaparse-visual-routing-fix/manufacturing-report/`, and
  `llamaparse-visual-fix/uber-earnings/`

Closest broad signals, to be split by the Ready sequence oracle:

- `FID-CLINICAL-STUDY-7ff711b5ea91`
- `FID-ESG-METRICS-0ce54fb8433b`
- `FID-MANUFACTURING-REPORT-38011101b317`
- `FID-UBER-EARNINGS-11268298b11c`

They are **correlated aggregate text-order signals**, not precise root-cause
proof. Visual-grounding caption findings for Manufacturing and rendered-DOM
order rows are also correlated. Heading rows belong to FFD-005.

## Root cause

- State: **Hypothesis; exact ordering constraints pending Ready**
- Production boundary: P03 relationship-aware atomic bundles, column bands,
  caption-owner edges, and P03 running-region/body projection.
- Why one defect: backend item order, Markdown order, and DOM order must all
  derive from one canonical relationship order; surface-specific fixes would
  drift.
- Safety: constraints must be finite, same-page, source-grounded, acyclic, and
  stable. Ambiguous columns/overlaps fail closed.

## Pre-remediation genericity blocker

`app/services/layout_order.py` currently activates reviewed Clean Energy and
Clinical behavior using exact item IDs, strings, and coordinates. Those
pre-existing rules are prohibited by `../generic-production-policy.md` and are
part of this defect's remediation boundary. FFD-004 cannot become Done by
adding another generic layer around them; they must be replaced with an
identity-independent capability and pass renamed, changed-text, translated/
scaled-geometry, page-offset, negative, adversarial, and unrelated-PDF tests.

## Acceptance criteria

1. Each affected page has a hash-bound expected sequence of public item IDs and
   body/header/footer roles, including explicitly unresolved items.
2. Clinical title precedes the reviewed sidebar bundle and all reviewed prose
   follows the source column flow exactly once.
3. ESG reviewed columns, notes, charts, footer, and navigation appear in the
   source order without interleaving or duplication.
4. Every Manufacturing caption/source note is adjacent to and associated with
   its correct owner in JSON, Markdown, and DOM.
5. Uber title/subtitle/date, slide body, notes, and footer/page identity match
   the reviewed sequence; identified construction-only tokens are absent from
   prose but retained as visual evidence where appropriate.
6. Cycles, ambiguous overlaps, duplicate anchors, cross-page edges, or
   unsupported semantic guesses do not reorder output and emit concerns.
7. Backend item order, canonical block order, raw Markdown, and Clearleaf DOM
   sequence are identical under the oracle.
8. Fresh four-case dual-system captures and an all-15 shared-order drift screen
   pass source review.

## Generic-production requirements

- Derive order and running-region roles from a reusable relationship graph over
  columns, containment, anchors, captions, repeated-page patterns, geometry, and
  source provenance. Production behavior must not branch on filenames, hashes,
  case IDs, page numbers, item IDs, heading/date/footer strings, or fixed bboxes.
- Capability evidence must expose the constraints and tie-breakers that produce
  each order decision, including an explicit fail-closed result for cycles or
  ambiguous overlaps; a stored expected sequence may be used only as test data.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes all text, varies column widths and gutters, moves a caption/source
  note, and changes header/footer coordinates. The intended semantic order and
  running-region roles must remain stable without production changes.
- Negative/adversarial variants must cover intersecting columns, floating
  callouts, a body line matching a running header, repeated captions, missing
  anchors, cycles, and cross-page edges; none may trigger semantic-only deletion
  or an unsupported reorder.
- Run multiple unrelated real-PDF controls through the shared ordering path,
  including `finance-10k`, `ny-timetable`, `purchase-agreement`, and
  `settlement-agreement`, retaining backend/Markdown/DOM order parity evidence.

Genericity closure gates:

- [ ] Genericity review records relationship rules, transformed/synthetic proof,
  adversarial outcomes, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch or embedded expected item sequence

## Test and rerun plan

- Focused regressions: one exact sequence fixture for sidebar/title, two-column
  flow, caption-owner bundle, and header/body/footer split; then real oracle
  assertions for all affected pages.
- Adversarial: cyclic edges, overlapping columns, shared caption, duplicate
  anchor, missing bbox, cross-page relation, and decorative chart text.
- Controls: Finance running header, NY title-first tables, Purchase banner/title,
  Settlement clauses, and Catastrophe table/chart order.
- Suites: P03-US02, P03-US04, P03-US08, canonical presentation, frontend
  rendered-order tests, and public context-free validation.
- Rerun the four affected PDFs through both systems and finish with all 15.

## Immediate affected-benchmark validation (mandatory)

- After every production fix or bounded document-order slice, immediately run
  the complete PDFs affected by that slice through both systems. Before Done,
  run full `clinical-study`, `esg-metrics`, `manufacturing-report`, and
  `uber-earnings`; page-only p1-p4 reruns are diagnostic, not closure evidence.
- Use a new immutable `FFD-004` rerun folder for each attempt. Record source
  SHA-256 values, parser/model/settings, LlamaParse job IDs, service build/commit
  and configuration, timestamps, and artifact paths/hashes.
- Preserve reference raw Markdown and the actual rendered Markdown UI in LlamaParse,
  snapshot and DOM/rendered representation where available, and full original
  JSON. Preserve service raw and canonical full Markdown, actual Clearleaf DOM
  and snapshot, and full original JSON.
- This immediate gate is a **targeted validation of FFD-004**, not an exhaustive
  whole-PDF/all-feature re-audit. Complete PDFs are rerun to preserve document
  ordering in normal pipeline context. For the document-order slice just fixed,
  manually compare only its completed sequence oracle and affected regions below:
  the relevant Markdown predecessor/successor fragments, rendered sequence/group
  DOM selectors and snapshots, and JSON paths for ordered items, relationships,
  page association, roles, anchors, and provenance. Broader unrelated comparison
  belongs to the control, wave, and final all-15 gates.
- Assert the completed sequence oracle for Clinical chiefly p1/1, ESG p1/80,
  Manufacturing p1-p3/11,15,38, and Uber p1-p3/1,5,6: sidebars/columns flow in
  source order, captions stay with owners, headers/footers/notes retain their
  proper regions, and construction or duplicate text does not enter body order.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the target sequence, its immediate predecessor/successor items,
  relevant sidebar/column, caption-owner pair, and running region. Any unexpected
  material change outside that boundary blocks closure and must be escalated as a
  cross-defect regression or separately tracked defect.
- Adjudicate every target-sequence mismatch and every automated drift alert
  against the rendered source, recording affected page/item sequence, reference
  and service Markdown fragments, snapshot or DOM selector/excerpt, JSON path,
  and harmless/accepted/material status.
- Tests alone cannot close the card. Any material reading-order, running-region,
  caption, Markdown, UI, JSON-order, relationship, or provenance symptom keeps
  it discrepancy/in progress; fix and repeat a fresh two-system full-PDF rerun.

## Story and change record

- Story action: **Add correction ACs and the exact sequence oracles to P03-US04
  and P03-US08; cross-link caption cases to P03-US02.**
- Expected production files: unknown until Ready.
- Changed files/tests/artifacts/reviewer: none; remediation not started.

## Closure checklist

- [ ] Exact item/role/order oracle recorded for every affected page
- [ ] Focused regressions fail before fix
- [ ] Bounded order/running-region correction complete
- [ ] Adversarial and control suites pass
- [ ] Fresh reference and service artifacts retained
- [ ] Public JSON and relationship graph validate
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Clearleaf DOM sequence/roles reviewed
- [ ] No semantic-only reordering or content deletion introduced
- [ ] All-15 drift screen passes
- [ ] Stories, evidence, registry, coverage, and index updated
- [ ] Independent closure review recorded
