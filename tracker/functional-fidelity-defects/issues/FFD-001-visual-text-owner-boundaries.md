# FFD-001 — Legitimate native visual text is rejected at owner boundaries

Status: **Proposed**  
Severity: **Major**  
Priority: **P0**  
Primary story: **P03-US02 / P02-US06**  
Dependencies: **None; blocks complete structure work in FFD-003 and FFD-008**

## Scope and impact

| PDF | Physical / printed page | Region | Surfaces |
|---|---|---|---|
| `health-report` | p1 / 103 | second chart | public JSON visual text/provenance, raw Markdown, rendered DOM |
| `manufacturing-report` | p2 / 15 | page-2 chart owners | public JSON visual text/provenance, raw Markdown, rendered DOM |
| `uber-earnings` | p3 / 6 | first association diagram | public JSON diagram text/provenance, raw Markdown, rendered DOM |

Source PDFs and SHA-256:

- `benchmark-expertmodeldata/health-report.pdf` — `fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181`
- `benchmark-expertmodeldata/manufacturing-report.pdf` — `414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f`
- `benchmark-expertmodeldata/uber-earnings.pdf` — `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`

The owner-containment gate treats source text boxes that slightly cross a visual
crop as ineligible for native promotion. Users consequently see noisier OCR or
missing diagram labels even though a native source text layer exists.

Non-goals:

- Do not widen every visual bbox or admit foreign-owner/page text.
- Do not infer chart values, series, diagram edges, or semantic descriptions.
- Do not weaken the `detected_text` boolean or context-free public model.

## Source-grounded oracle

Expected/source behavior:

- Every source-visible native label belonging to the affected owner is attached
  once to that owner, in source reading order and with source-object/bbox proof.
- A box crossing the crop boundary is not by itself evidence that the text is
  foreign; ownership must be resolved from overlap, lineage, neighbouring
  owners, and unique assignment.

Current actual behavior:

- Health chart 2 retains residual primary OCR because its native text does not
  satisfy strict owner containment.
- Manufacturing p2 retains primary OCR for source boxes crossing chart-owner
  boundaries.
- Uber p3's first diagram omits exact source labels whose boxes cross its owner
  boundary.

Definition-of-Ready oracle still required: enumerate every affected source
text occurrence, its bbox/source-object IDs, candidate owner(s), expected owner,
and exact final order. The current adjudication establishes the failure class,
but not a complete token/bbox list; no implementation may start without it.

## Reproducible evidence

Evidence root: `tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/`.

- Health: `comparison-final-source-grounded-v2/health-report/evidence.json`,
  `service-final-source-grounded-20260813-v2/health-report/`
- Manufacturing: `comparison-final-source-grounded-v2/manufacturing-report/evidence.json`,
  `service-final-source-grounded-20260813-v2/manufacturing-report/`
- Uber: `comparison-final-source-grounded-v2/uber-earnings/evidence.json`,
  `service-final-source-grounded-20260813-v2/uber-earnings/`
- Root-cause ledger: `visual-source-semantics-resolution-ledger.json`
- Selected LlamaParse artifacts: `llamaparse-visual-routing-fix/health-report/`
  (`pjb-g66fg3bwy8plzgmslyhwfhb4taoe`),
  `llamaparse-visual-routing-fix/manufacturing-report/`
  (`pjb-vpn3e4kt636fnx2y4vlr98otbyic`), and
  `llamaparse-visual-fix/uber-earnings/`
  (`pjb-skyvq5noznjko41p3fs2vxgfgptg`)

Primary machine signals are not sufficiently isolated to the containment seam.
The closest review/structure signals are
`FID-HEALTH-REPORT-83893ff510f2`,
`FID-MANUFACTURING-REPORT-46077e86dadb`, and
`FID-UBER-EARNINGS-149c517c7653`; they are aggregate OCR proxies and therefore
**correlated/review-required**, not standalone proof. Chart-value and diagram
signals in the same case files are downstream manifestations split with
FFD-003/FFD-008.

Reproduce with the command stored in each case `evidence.json`, using the final
v2 release-fidelity profile and immutable `reference-selection.json`.

## Root cause

- State: **Confirmed failure boundary; exact token oracle pending**
- Production boundary: terminal visual source-text ownership/projection in the
  P03 visual-layout seam.
- Why one defect: all three cases fail the same unique-owner containment rule;
  OCR and structure differences are consequences.
- Safety constraint: acceptance requires a unique, finite, same-page,
  source-grounded assignment. Ambiguous or multi-owner text must remain
  unresolved with concerns.

## Acceptance criteria

1. The Ready oracle lists 100% of affected occurrences and expected owners for
   all three PDFs; every listed occurrence appears exactly once on that owner.
2. Public JSON records finite bbox, source IDs, selected method, and unique owner
   for every promoted occurrence; no occurrence is silently cloned or dropped.
3. Raw Markdown equals canonical full Markdown byte-for-byte and contains each
   approved label exactly once in the correct visual position; the DOM presents
   the same sequence.
4. A label more than the approved geometric tolerance outside an owner, inside
   a competing owner, cross-page, cross-unit, or without lineage remains
   excluded and concern-bearing.
5. Existing native promotions in eGov, manufacturing p1, and health chart 1 do
   not change; Uber's natural photograph remains diagnostic-only.
6. No series, point, value, connector, direction, or generated prose is emitted
   solely because label ownership was corrected.
7. Fresh LlamaParse and service JSON/Markdown/Clearleaf DOM artifacts are
   retained for Health, Manufacturing, and Uber and reviewed against the PDF.

## Generic-production requirements

- Implement owner assignment as a reusable capability over normalized geometry,
  overlap, source lineage, neighbouring-owner competition, and unique-assignment
  confidence. Production behavior must not branch on a benchmark filename,
  document hash, case ID, page number, owner/element ID, label string, or fixed
  coordinate/bbox from the Ready oracle.
- Capability evidence must explain the same decision rule for every promoted or
  rejected occurrence, including why a near-boundary label belongs to one owner
  and why an otherwise similar foreign label does not.
- Add at least one transformed or synthetic variant that changes the filename
  and file hash, prepends a page, shifts/scales the owner crop, changes the label
  text, and adds an adjacent competing visual. The correct label must still be
  uniquely assigned without updating production constants.
- Negative/adversarial variants must include a genuinely foreign straddling
  label, an equally plausible two-owner label, cross-page/cross-unit lineage,
  duplicate source identity, and missing lineage; each must fail closed without
  cloning or silently dropping content.
- Run multiple unrelated real-PDF controls through the same code path, including
  `egov-survey`, `clean-energy`, `clinical-study`, and the Uber p1 photograph,
  and retain per-occurrence decision evidence showing no ownership drift.

Genericity closure gates:

- [ ] Genericity review records the capability rule, transformed/synthetic proof,
  adversarial results, and unrelated real-PDF control results
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch or leaked oracle/fixture data

## Test and rerun plan

- Focused failing regression: construct one near-boundary label per affected
  geometry pattern and three real-corpus assertions using the completed oracle.
- Negative/adversarial: competing adjacent owners, >tolerance overflow,
  cross-unit box, duplicate source ID, missing lineage, and natural photograph.
- Required controls: `egov-survey`, `clean-energy`, `clinical-study`, and
  `uber-earnings` p1 photo.
- Shared-family suites: P02-US06 spatial tokens, P03-US02 visual children/source
  text, P05 visual schema, public model/canonical closure tests.
- Rerun matrix: affected three PDFs through both systems; then all-15 drift
  screen because this changes a shared projection seam.

## Immediate affected-benchmark validation (mandatory)

- After every production fix attempt, and before this card can be marked Done,
  run the **complete** `health-report`, `manufacturing-report`, and
  `uber-earnings` PDFs through both LlamaParse and the service. A crop or rerun
  of only p1, p2, or p3 is supporting evidence, not closure evidence.
- Create a new immutable `FFD-001` rerun folder; never replace an earlier run.
  Its manifest must retain each source SHA-256, parser settings/model options,
  LlamaParse job ID, service build/commit and configuration, timestamps, and
  the exact artifact paths and hashes.
- Preserve LlamaParse raw Markdown, its actual rendered Markdown UI snapshot
  and DOM/rendered representation where available, and its full original JSON.
  Preserve the service raw Markdown, canonical full Markdown, actual Clearleaf DOM
  and snapshot, and full original JSON response.
- This immediate gate is a **targeted validation of FFD-001**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDFs are rerun to preserve normal
  pipeline context. Manually compare only the named owner-boundary oracles and
  affected visual components below, their relevant Markdown owner/label fragments,
  the rendered owner-container/label DOM selectors and snapshots, and the JSON
  paths carrying component order, owner identity, source IDs, bboxes, and
  provenance. Broader unrelated comparison belongs to the control, wave, and
  final all-15 gates.
- On Health p1/103 chart 2, Manufacturing p2/15 chart owners, and Uber p3/6
  association diagram 1, verify every source-approved near-boundary label is
  attached exactly once to the correct visual owner in JSON, Markdown, and DOM;
  verify competing, foreign, and ambiguous labels remain excluded and
  concern-bearing.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: each target owner, its candidate labels, immediate sibling owners and
  captions, once-only occurrence, and local order. Any unexpected material change
  outside that boundary blocks closure and must be escalated as a cross-defect
  regression or separately tracked defect.
- Adjudicate every target-boundary mismatch and every automated drift alert
  against the rendered source PDF and completed occurrence/owner oracle. Record
  expected LlamaParse behavior, service behavior, page/region, Markdown fragment,
  snapshot or DOM selector/excerpt, JSON path, and harmless/accepted/material status.
- Unit/regression success cannot close this card. If any material owner,
  once-only, ordering, Markdown, rendered-UI, JSON, or provenance symptom
  remains, keep status as discrepancy/in progress, fix it, and repeat the fresh
  two-system full-PDF rerun until the issue-specific assertions pass.

## Story and change record

- Story action: **Add correction acceptance criteria to P03-US02 and P02-US06;
  cross-link P05-US03/P05-US10 without expanding this fix into structure work.**
- Expected production files: **Unknown until Ready; likely visual source-text
  ownership/projection and focused tests only.**
- Changed files: none.
- Test commands/results: not run; remediation not started.
- Fresh artifact paths/hashes: none.
- Reviewer/source decision: pending.

## Closure checklist

- [ ] Definition of Ready complete, including exact token/bbox/owner oracle
- [ ] Focused regression fails before fix
- [ ] Production correction complete
- [ ] Focused and control suites pass
- [ ] Fresh LlamaParse references retained
- [ ] Fresh service JSON retained and context-free validates
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Actual Clearleaf DOM retained and reviewed
- [ ] No unsupported values, prose, or topology added
- [ ] Story, evidence, registry, coverage, and index updated
- [ ] Independent closure review recorded
