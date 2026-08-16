# Decision: admit FFD-014 as a post-baseline blocking control defect

Date: **2026-08-14**  
Status: **Accepted for the active remediation queue**

## Decision

Add FFD-014 as a fourteenth root-cause card and a twenty-third bounded
implementation slice. It is a post-baseline production-control discovery, not
a rewrite of the immutable 25-gap source-grounded v2 disposition.

FFD-014 owns the Clinical physical-page-1 Crossmark non-target visual-overlay
custody transition in the P04 terminal table transaction. The exact failure is
an included placeholder with a public contributor in the validated baseline
versus an empty, omitted `unsupported_primary_ocr` reconstruction with a
different closed graph. It is not the optional-null difference described by
the preliminary diagnostic interpretation.

The user authorized this first segment on 2026-08-14. The segment must remain
generic, preserve the existing page-1 public representation, retain graph
custody, and pass at the unchanged production deadlines of 5.0 seconds per
document and 0.500 seconds per page. It pauses before any page-2-specific
content work. The independent NY timetable deadline/page-boundary condition is
not part of this card.

## Queue and dependency effect

- FFD-011 moves from `Validating` to `Blocked` while FFD-014 is active. Its
  focused Postal target remains a retained pass; this status change does not
  rewrite that evidence.
- FFD-014 moves through `Proposed` and `Ready` to `In Progress` only after its
  complete issue-card Definition of Ready and Genericity Definition of Ready
  are recorded.
- FFD-012 and FFD-013 remain unstarted.
- The one-production-defect WIP limit remains satisfied.
- Completing FFD-014 removes only the Clinical part of FFD-011's shared P04
  control blocker. The separately governed NY failure must still pass or
  receive an explicit bounded disposition before FFD-011 can return to
  `Validating`/`Done`.

## Evidence and immutability

The existing diagnostic root
`tracker/benchmarks/llamaparse-15/runs/20260813T174647Z-FFD-011-P04-deadline-diagnostic/`
remains immutable and diagnostic-only. Its production settings were unchanged;
its elevated document lanes are not release or closure evidence. FFD-014 must
create a new immutable full-PDF dual-system validation attempt after the
generic correction and automated controls pass.

The original 2026-08-13 queue decision remains historically correct for the
13-card/22-slice v2-derived inventory. This amendment records the later control
discovery without relabelling that earlier decision or adding a fabricated
`SG-026` to the frozen 25-gap denominator.
