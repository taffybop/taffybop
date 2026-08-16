# FFD-005 — Heading, section, and callout hierarchy is flattened or mistyped

Status: **Proposed**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P03-US07**  
Dependencies: **FFD-004 for stable item order**

## Scope and impact

| PDF | Physical / printed page | Expected/source | Current actual | Surfaces |
|---|---|---|---|---|
| `clinical-study` | p1 / 1/21 | title H1; `Abstract` H2; `Background` and `Methods and findings` H3 | all four serialize as H1 | JSON roles/levels, Markdown, DOM |
| `manufacturing-report` | p3 / 38 | Figure 4.3 caption and following section retain distinct source roles | residual `4.3.`/caption hierarchy difference | JSON, Markdown, DOM |
| `uber-earnings` | p1–p3 / 1, 5, 6 | cover/slide title groups retain source levels | heading/title grouping remains degraded | JSON, Markdown, DOM |

Source SHA-256: Clinical
`4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`;
Manufacturing
`414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f`;
Uber `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`.

Non-goals: do not reorder items (FFD-004), recover PUA glyphs (FFD-007),
change heading typography without source role evidence, or reproduce generated
Llama descriptions. Component NOTE recovery and presentation are wholly scoped
to FFD-007 so the same source gap is not split across two queues.

## Source-grounded oracle

The Clinical four-heading oracle above is established by
`FID-CLINICAL-STUDY-a23b7affb315`. Exact Manufacturing and Uber public item
IDs, source bboxes, expected roles/levels, and surrounding order must be
recorded before Ready; existing evidence establishes visible hierarchy loss
but not a complete level oracle for those pages.

## Reproducible evidence

- `comparison-final-source-grounded-v2/clinical-study/evidence.json` and
  `service-final-source-grounded-20260813-v2/clinical-study/`
- Equivalent comparison/service paths for `manufacturing-report` and
  `uber-earnings`
- `comparison-text-render-fix/source-truth-text-render-review.md`
- Selected references: `llamaparse-visual-routing-fix/clinical-study/`,
  `llamaparse-visual-routing-fix/manufacturing-report/`, and
  `llamaparse-visual-fix/uber-earnings/`

Primary/closest signals:

- Clinical `FID-CLINICAL-STUDY-a23b7affb315`
- Manufacturing `FID-MANUFACTURING-REPORT-9598e3c65dec`
- Uber `FID-UBER-EARNINGS-57471b1f4c6b`

Rendered hierarchy and grouping rows are correlated downstream signals, not
separate defects.

## Root cause

- State: **Confirmed for Clinical; hypothesis/oracle pending for other cases**
- Boundary: outline/callout role derivation and canonical semantic projection.
- Failure: style/number cues are flattened into one heading level or a callout
  is promoted into the document outline.
- Safety: a heading/callout role requires source style, sequence, geometry, and
  unique contributor custody; ambiguous items remain text/callout-unknown.

## Acceptance criteria

1. Clinical emits exactly the established H1/H2/H3/H3 sequence across JSON,
   Markdown, and semantic DOM.
2. Ready oracles enumerate exact expected roles/levels for Manufacturing p3
   and all affected Uber slide groups.
3. Figure captions never enter the document outline.
4. No item is promoted from font size or numbering alone; ambiguous,
   duplicated, or construction text fails closed.
5. Canonical and raw Markdown are byte-identical; DOM uses the matching
   `h1`–`h6` or callout structure in canonical order.
6. Purchase title/Background, Finance running header, Settlement legal lists,
   and NY titles remain unchanged.
7. Fresh affected-case LlamaParse/service/DOM captures and all-15 hierarchy
   drift evidence are retained.

## Generic-production requirements

- Infer heading, section, caption, and callout roles from reusable structural
  evidence such as outline relationships, numbering continuity, typography,
  spacing, repetition, containment, and source order. Production behavior must
  not branch on filenames, hashes, benchmark cases, page numbers, item IDs,
  heading/caption strings, or fixed coordinates.
- Capability evidence must show that no single font-size, numbering, or literal
  match controls promotion and must explain why a visually similar caption,
  running header, callout, or emphasized body line stays out of the outline.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes all headings and numbering, varies font sizes/styles and indentation,
  and repositions a callout/caption. The hierarchy must remain correct without
  updating production constants or known-title lists.
- Negative/adversarial variants must include a large body sentence, numbered
  caption, repeated running header, unnumbered subheading, detached callout,
  duplicate title, and construction text; ambiguous candidates must fail closed.
- Run multiple unrelated real-PDF controls, including `purchase-agreement`,
  `finance-10k`, `settlement-agreement`, and `ny-timetable`, preserving
  their established JSON outline, Markdown levels, and semantic DOM.

Genericity closure gates:

- [ ] Genericity review records hierarchy predicates, transformed/synthetic proof,
  adversarial outcomes, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch or embedded title/level lookup

## Test and rerun plan

- Failing tests: exact Clinical sequence; source-oracle assertions for the
  remaining cases; one semantic callout fixture.
- Adversarial: numbered caption, all-caps footer, revision banner, bold body,
  duplicate heading, and callout without icon.
- Controls: Purchase, Finance, Settlement, NY, and Component p3 section.
- Suites: P03-US05/P03-US07/P03-US08, canonical presentation, frontend
  semantic-heading/callout tests.
- Rerun three affected PDFs through both systems, then all 15.

## Immediate affected-benchmark validation (mandatory)

- After each production fix, run the complete `clinical-study`,
  `manufacturing-report`, and `uber-earnings` PDFs through both LlamaParse and
  the service. A page-only rerun of Clinical p1, Manufacturing p3, or Uber
  p1-p3 may diagnose the change but cannot close this card.
- Create a new immutable `FFD-005` evidence folder for every attempt and record
  source hashes, parser/model/settings, LlamaParse job IDs, service build/commit
  and configuration, timestamps, and all artifact paths/hashes.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-005**, not an exhaustive
  whole-PDF/all-feature re-audit. Complete PDFs are rerun to preserve hierarchy
  inference in normal pipeline context. Manually compare only the role/level
  oracles and affected title, heading, caption, and callout components below:
  their Markdown heading fragments and outline positions, rendered heading/
  callout DOM selectors and snapshots, and JSON paths for type, role, level,
  nesting, page association, and provenance. Broader unrelated comparison belongs
  to the control, wave, and final all-15 gates.
- Assert Clinical p1/1 has one document H1 followed by `Abstract` H2 and
  `Background`/`Methods and findings` H3; verify Manufacturing p3/38 keeps the
  Figure 4.3 caption distinct from the following section; verify Uber p1-p3
  title groups retain source-backed levels. Captions, callouts, running text,
  and merely bold/all-caps text must not pollute the document outline.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: each target heading/title group, its parent and immediate outline
  siblings, the Figure 4.3 caption/next section boundary, and excluded callout or
  running-text candidates. Any unexpected material change outside that boundary
  blocks closure and must be escalated as a cross-defect regression or separately
  tracked defect.
- Source-ground every target-hierarchy mismatch and every automated drift alert
  with the PDF and completed role/level oracle; retain Markdown fragments,
  snapshot or DOM selector/excerpt, JSON paths, expected LlamaParse result,
  service result, and harmless/accepted/material disposition.
- Unit/frontend tests alone are insufficient. If any material heading level,
  role, outline, callout, Markdown, rendered-UI, JSON, or provenance symptom
  persists, keep status discrepancy/in progress and repeat the fix plus a fresh
  two-system full-PDF run until every assertion passes.

## Story and change record

- Story action: **Add correction ACs to P03-US07; explicitly extend it to
  source-grounded callout exclusion from the outline.**
- Expected production files: unknown until Ready.
- Changed files/tests/artifacts/reviewer: none; remediation not started.

## Closure checklist

- [ ] Complete role/level oracle for every target
- [ ] Focused tests fail before fix
- [ ] Production correction complete
- [ ] Adversarial/control suites pass
- [ ] Fresh LlamaParse/service JSON/Markdown/DOM retained
- [ ] Public outline validates and no caption/callout enters it
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Clearleaf semantic hierarchy reviewed
- [ ] Story/evidence/registry/coverage/index updated
- [ ] Independent closure review recorded
