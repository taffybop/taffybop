# Functional Fidelity Defect Tracker

Status: **Active remediation queue; FFD-014 is In Progress and FFD-011 is Blocked on shared P04 controls**  
Created: **2026-08-13**  
Release posture: **Not ready while any P0/P1 defect remains open**

This folder is the working queue for the source-grounded defects that remain
after the 15-PDF LlamaParse functional-fidelity benchmark. It deliberately
does not copy or replace the immutable benchmark artifacts. Every defect links
back to the final v2 evidence package.

## What is tracked

- **14 root-cause defects** in [`issues/`](issues/): 13 from the frozen v2
  source-gap inventory plus the post-baseline P04 control defect FFD-014.
- **25/25 authoritative remaining-gap statements** mapped in
  [`source-gap-coverage.md`](source-gap-coverage.md).
- **23 ordered implementation slices** in [`execution-order.md`](execution-order.md).
- The machine-readable mirror in [`registry.json`](registry.json).

The comparator's **278 functional signals are not 278 defects**. They include
correlated Markdown, JSON, table, visual, and DOM manifestations of the same
root cause. They remain available for audit, but work is planned from the 25
source-grounded gaps and the 13 deduplicated baseline causes. FFD-014 is a
separately evidenced post-baseline production-control discovery and does not
rewrite that immutable denominator. See
[`signal-adjudication.md`](signal-adjudication.md).

Every remediation is also governed by the mandatory
[`generic-production-policy.md`](generic-production-policy.md). Benchmark PDFs
are reproductions and validation controls, never runtime identifiers. A change
that matches a known fixture through its name, hash, case ID, page number,
unique text/coordinates, stable element ID, Llama job/artifact, prompt lookup,
or memorized expected output is prohibited and cannot enter production.
The initial [`pre-remediation genericity audit`](pre-remediation-genericity-audit.md)
also found pre-existing fixture-specific production gates in the relationship-
ordering path. A defect cannot close while such logic remains in its affected
or dependent capability path; the policy applies to the whole final path, not
only to newly added lines.

## Operating model

Use a strict **WIP limit of one production defect**:

1. Select the first unblocked work item from `execution-order.md`.
2. Complete its Definition of Ready and the policy's Genericity Definition of
   Ready in the owning defect card.
3. Add a focused failing regression before changing production behavior.
4. Refresh the LlamaParse reference for the affected PDF before implementation
   and bind its job ID and hashes. LlamaParse is the requested comparison
   baseline; the PDF remains source truth.
5. Make one bounded, reusable capability correction and run its positive
   variants, identity-independence, negative/adversarial, unrelated-PDF, and
   named control families.
6. Immediately after the production correction and focused tests pass, rerun
   each relevant **full benchmark PDF by itself** through both LlamaParse and
   the service. Do this before starting or validating another production
   defect.
7. Capture both runs in new immutable artifact folders: raw Markdown, the
   full original JSON response, and the actual rendered Markdown UI/DOM plus
   snapshots. Capture LlamaParse's displayed rendering and Clearleaf's actual
   rendered DOM; a synthetic Markdown preview is not a substitute.
8. Perform and record an issue-specific, source-grounded comparison of the
   card's exact defect oracle, named symptoms, and declared collateral boundary
   across all three surfaces. Run an automated full-output drift comparison of
   the post-fix service artifacts against the bound pre-fix service artifacts,
   then manually review every changed region outside that boundary. Also flag
   any fresh-versus-selected LlamaParse reference drift. Unchanged
   out-of-boundary content does not need a manual whole-PDF re-audit here.
9. Update the card, evidence hashes, owning story, coverage table, and index.
10. Review the production diff and repository search for prohibited fixture
   identifiers, recording commands and results in the defect card.
11. Mark the work Done only after this immediate affected-benchmark gate, the
    full closure gate, and the genericity gates pass.

Do not start a second production fix while one is `In Progress` or
`Validating`. Investigation and source review may occur in parallel as long as
they do not mutate production code.

Historical WIP note (2026-08-13): FFD-011's second fresh complete-PDF dual-system
attempt passes its source/Markdown/actual-UI-DOM/full-JSON target and collateral
review. The card remains `Validating` because three current NY/Clinical P04
production-benchmark custody tests remain red. A bounded test-only 5/10/15/30
second diagnostic proved two independent causes: Clinical deterministically
rejects a non-target visual-block shape during terminal canonical splice,
while NY exceeds the five-second terminal document clock and has observations
at the independent 500 ms page boundary. Every diagnostic output preserves the
reviewed content, but elevated-budget output is explicitly non-closure and the
production limits remain unchanged. These tests run with FFD-011 source
alignment disabled, but the mandatory named-control gate is not waived.
FFD-012 has not started.

Earlier WIP supersession (2026-08-14; superseded again below): exact capture proves the Clinical cause
is not an optional-null difference. The validated baseline page-1 Crossmark
canonical block is an included image placeholder with its public visual
contributor, while fresh predecessor/candidate reconstruction omits the same
owner with empty content and `unsupported_primary_ocr`; the relationship and
exclusion graphs also differ. FFD-014 now owns that generic non-target visual-
overlay custody transition and was then the sole `Validating` production defect.
FFD-011 is `Blocked`, preserving its passing Postal artifacts, until FFD-014
and the separately governed NY control blocker are resolved. Production limits
remain 5.0 seconds/document and 0.500 seconds/page. The user-authorized first
FFD-014 segment is limited to the Clinical physical-page-1 Crossmark boundary
and pauses before page-2-specific work. Its bounded page-1 service/UI handoff
passes target and non-regression review but is not a transaction-exercising
dual-system closure bundle. See the dated
[`FFD-014 queue amendment`](decisions/2026-08-14-ffd-014-post-baseline-control-amendment.md).

Page-one release supersession (2026-08-14): after reviewing the bounded
handoff, the requester authorized source-visible header/article-label,
visual-label, order, footer, and interactive Full-default corrections for
Clinical physical page 1. The exact scope is recorded in the
[`page-one release-slice amendment`](decisions/2026-08-14-ffd-014-clinical-page-one-release-slice-amendment.md).
The final full-page regression and fresh HTTP/Full-renderer handoff pass that
page-one boundary. Terminal P04 table custody does not: the latest named 5s and
test-only 10s observations remain unresolved and predate the final footer-
replay patch. FFD-014 is therefore `In Progress`, not `Validating`, and FFD-011
remains `Blocked`. Production remains at 5.0 seconds/document and 0.500
seconds/page; the 10-second seam is test-only and non-closure. No Clinical
page-2 source was inspected, no other defect closed, and the Wave A/final
all-15 gates remain pending.

## Immediate affected-benchmark closure gate

Every implementation slice has a mandatory local benchmark gate. As soon as a
fix passes its focused tests, and while the owning card is still `Validating`,
run every relevant full benchmark PDF separately through a fresh LlamaParse
job and the exact service candidate being reviewed. Store the source identity,
job/build identifiers, settings, timestamps, and hashes with these immutable
artifacts for each system:

- raw Markdown;
- the actual rendered Markdown UI/DOM and visual snapshots; and
- the full, unprojected JSON response.

Compare those fresh outputs against the PDF source and against each other only
for the particular defect being validated: its exact oracle, named symptoms,
and the collateral boundary declared before implementation. Within that
boundary, review the applicable Markdown structure, rendered presentation,
JSON structure/content, and relevant OCR, table, form, chart, diagram, or image
semantics. Also run an automated whole-output structural drift comparison over
the complete Markdown, rendered DOM representation, and JSON, using the bound
pre-fix service output as the change-footprint baseline. Check the fresh
LlamaParse capture against its selected prior reference so a baseline change is
not mistaken for a service fix. Manually inspect every post-fix service change
reported outside the declared boundary and either prove it is non-regressive
or return the defect to `In Progress`.

The complete outputs are retained so drift cannot be hidden, but this immediate
gate is not an exhaustive manual re-audit of every unaffected page or feature.
Comprehensive whole-PDF review occurs at the wave gate where applicable and at
the mandatory final frozen all-15 campaign. Record the expected LlamaParse
result and actual service result for the defect, plus the drift report,
out-of-boundary changed-region decisions, reproducible artifact paths/hashes,
and reviewer findings.

A focused or unit-test pass does not satisfy this gate. A slice cannot move to
`Done`, and the next production slice cannot begin, until its relevant
benchmark comparison passes or a remaining difference is explicitly approved
under the tracker's acceptable-difference rules. Passing this local gate does
not replace wave drift screens or the final frozen end-to-end all-15
LlamaParse/service validation; both remain mandatory.

## Status and priority

Status is one of `Proposed`, `Ready`, `In Progress`, `Validating`, `Blocked`,
`Deferred`, `Done`, or `Superseded`.

Severity describes user impact:

- **Critical** — missing/false meaning or materially wrong semantic ownership.
- **Major** — substantial user-visible degradation or downstream structural loss.
- **Minor** — localized fidelity loss or diagnostic-only noise.

Priority controls execution:

- **P0** — foundational correctness defect that contaminates downstream output.
- **P1** — release blocker or shared prerequisite.
- **P2** — localized user-visible defect.
- **P3** — low-impact or diagnostic-only work; re-adjudicate before implementation.

Severity and priority are independent.

## Definition of Ready

A work item can move from `Proposed` to `Ready` only when all are recorded:

1. Source PDF SHA-256, physical page, printed page when different, and bounded
   region/token oracle.
2. Visual/source review confirming that the behavior is genuinely in the PDF.
3. LlamaParse expected output and our actual output on Markdown, JSON, and DOM.
4. Primary comparator signal IDs plus disposition of correlated signals.
5. Confirmed root cause or a falsifiable root-cause hypothesis.
6. One primary Phase/User Story and an explicit decision on addendum versus new story.
7. Dependencies, non-goals, and a change surface small enough to review.
8. Finite, measurable acceptance criteria.
9. Focused positive, negative, adversarial, and non-target control plan.
10. Exact affected-PDF and control-PDF rerun matrix.
11. Exact defect oracle, named symptoms, and a declared collateral boundary
    identifying the pages, components, and cross-surface structures allowed to
    change; everything else is outside-boundary.
12. The reusable capability contract, decision inputs, ambiguity/fail-closed
    behavior, and all Genericity Definition of Ready evidence required by
    [`generic-production-policy.md`](generic-production-policy.md).

## Definition of Done

All items are mandatory:

1. Focused regression reproduces the source-grounded defect.
2. Production correction is bounded and reviewed.
3. Focused and named control suites pass.
4. Immediately after the fix and focused tests, every relevant full benchmark
   PDF is rerun separately through fresh LlamaParse and service jobs into new,
   immutable artifact folders before another production defect begins.
5. Each rerun retains raw Markdown, the full original JSON response, and the
   actual rendered Markdown UI/DOM plus snapshots for both systems.
6. An issue-specific, source-grounded comparison proves the reported defect's
   exact oracle and named symptoms are resolved across Markdown structure,
   rendered presentation, and JSON structure/content within the declared
   collateral boundary.
7. Automated full-output drift comparison is retained for complete Markdown,
   rendered DOM representation, and JSON against the bound pre-fix service
   artifacts; fresh-versus-selected LlamaParse reference drift is also
   recorded. Every post-fix service change outside the declared boundary is
   manually reviewed and accepted as non-regressive.
8. Public JSON validates context-free and preserves page/order/provenance contracts.
9. Raw Markdown is byte-identical to canonical full Markdown.
10. Actual LlamaParse rendered evidence and actual Clearleaf rendered DOM are
    captured; the defect boundary and every flagged outside-boundary change are
    visually/semantically reviewed.
11. Defect-relevant text, table, chart, diagram, or form content is correct exactly once.
12. No unsupported Llama-generated prose, inferred values, or invented arrows are copied.
13. Evidence hashes, story acceptance criteria, the issue card, registry, and index are updated.
14. Shared-root changes pass their full control family; each wave passes an all-15 drift screen.
15. A reviewer records the focused source/Markdown/JSON/DOM decision and
    outside-boundary drift disposition. Exhaustive unaffected-region review is
    deferred to the applicable wave and final all-15 gates.
16. Positive variants, rename independence, applicable reorder/page-offset,
    negative/adversarial, and unrelated-PDF controls prove the behavior is not
    fixture-specific.
17. Production diff/search review finds no prohibited identifiers, lookups, or
    memorized outputs, and every Genericity Definition of Done item in
    [`generic-production-policy.md`](generic-production-policy.md) is recorded.
18. After all defect closures, the frozen release candidate passes the separate
    final all-15 LlamaParse/service validation in
    [`final-all-15-validation.md`](final-all-15-validation.md).

Unit tests alone never satisfy this Definition of Done.

## Evidence authority

All relative evidence paths in this tracker are rooted at:

`tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/`

Primary authorities:

- `source-grounded-final-disposition-v2.json` — 15-case adjudicated status and
  the authoritative 25 remaining gaps.
- `comparison-final-source-grounded-v2/<case>/evidence.json` — raw correlated
  cross-surface signals.
- `service-final-source-grounded-20260813-v2/<case>/` — final service JSON,
  Markdown, and rendered-DOM evidence.
- `artifact-manifest-final-source-grounded-v2.json` — source/reference/service
  identity and custody.
- `resolution-ledger-final-source-grounded-v2.json` — resolved public projection
  and terminal custody defects.

The source-grounded disposition is SHA-256
`5bb478ca60486969293ec12e2099987130b33f25b5d37af9bcff649138dd7a17`.

## Boundaries

- This queue covers functionality and output quality only.
- Latency, CPU, memory, exhaustive hardening, and unrelated historical phase
  work are outside this queue unless they directly block correct parsing.
- The 20 MiB upload limit is already implemented and is not an open defect.
- The three fixed PDFs and one acceptable-difference PDF remain regression
  controls; they are not reopened by raw comparator signals alone.
