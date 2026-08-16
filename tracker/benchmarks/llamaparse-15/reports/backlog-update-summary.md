# Backlog Update Summary

Status: Historical planning snapshot complete; canonical P00-US04 is now Done  
Evidence basis: 15 source-reviewed cases, 30 rendered pages, and the fixed
`baseline-20260728-current` run

> **2026-07-29 supersession:** The requester approved a bounded Phase 0 split
> after this historical report. The canonical roadmap is now 69 stories/322
> points; the runner then called P00-US05 is now P00-US10. The tables below
> remain the original 2026-07-28 planning record. See
> [`P00-US04-scope-split.md`](../../../phase-00-baseline/decisions/P00-US04-scope-split.md).

> **2026-08-01 estimate update:** P03-US07 and P03-US08 were each re-estimated
> from their historical 3-point plans to 5 points after independent
> Definition-of-Ready audits. The canonical roadmap is now 69 stories/326
> points. The original rows and phase totals below remain the 2026-07-28
> planning record.

> **2026-08-08 latency supersession:** Any latency language in this historical
> snapshot is non-operative for Phases 04–08. Their sole current comparator is
> [`latency-reference-v1.md`](../latency-reference-v1.md); non-latency evidence
> remains unaffected.

## Outcome

The existing nine-phase tracker remains the right delivery structure. The
benchmark confirms 25 reusable gap classes. Seven require new independently
testable stories; the remaining gaps are absorbed by existing stories through
source-grounded fixtures, measurable acceptance, regression slices,
performance guards, feature flags, and rollback.

| Portfolio | Stories | Points |
|---|---:|---:|
| Previous backlog | 57 | 268 |
| New stories | +7 | +31 |
| P04-US01 re-estimate | — | +2 |
| **Proposed backlog** | **64** | **301** |

All estimates use only 1, 2, 3, or 5 points. No story exceeds five points.

## New stories

| Story | Points | Reusable capability | Primary gaps |
|---|---:|---|---|
| [P00-US04 (superseded combined scope)](../../../phase-00-baseline/evidence/P00-US04-readiness-blocker.md) | 5 | Register reviewed multi-case truth, custody, and expert inclusion masks | GAP-BENCHMARK-001, GAP-COVERAGE-001 |
| [Then P00-US05, now P00-US10](../../../phase-00-baseline/stories/P00-US10.md) | 5 | Run immutable corpus baselines and semantic reports | GAP-BENCHMARK-002, GAP-PERFORMANCE-001 |
| [P03-US05](../../../phase-03-layout/stories/P03-US05.md) | 5 | Preserve source-visible redline and run semantics | GAP-REDLINE-001 |
| [P03-US06](../../../phase-03-layout/stories/P03-US06.md) | 5 | Extract forms, controls, blank values, and key-value relationships | GAP-FORM-001 |
| [P03-US07](../../../phase-03-layout/stories/P03-US07.md) | 3 | Preserve list and legal-clause hierarchy | GAP-LIST-001 |
| [P03-US08](../../../phase-03-layout/stories/P03-US08.md) | 3 | Separate running regions, physical pages, and printed page identity | GAP-PAGE-001 |
| [P04-US04](../../../phase-04-tables/stories/P04-US04.md) | 5 | Select source-supported table candidates and reject chart/form impostors | GAP-TABLE-001 |

No new phase was created. These capabilities have independent acceptance,
test, dependency, flag, and rollback boundaries and would make existing stories
internally larger than the five-point ceiling if merged into them.

## Existing-story updates

- All 57 pre-existing stories retain their original capability boundary.
- Every materially affected story now cites exact LlamaParse-15 cases and
  source regions, generalized behavior, a positive target, non-target
  regression, negative or ambiguous control, measurable quality and resource
  expectations, and flag/rollback behavior.
- P04-US01 changes from 3 to 5 points because its evidence now covers dense and
  rotated grids, multi-level headers, spans, multiline cells, blank/section
  rows, and irregular form-grid controls. It remains one cell/span-fidelity
  capability.
- P05-US07 and P05-US09 remain Proposed and are not Ready: the supplied corpus
  lacks an approved raster-bar positive and complete image/PDF parity twins.
- Phase 07's M5 exit gate remains blocked because the corpus has no fully
  scanned, direct-image, image-only-PDF, DOCX, PPTX, or XLSX semantic twin.

## Point impact by phase

| Phase | Previous | Proposed | Change |
|---|---:|---:|---:|
| 00 — Baseline | 3 stories / 13 pts | 5 / 23 | +2 / +10 |
| 01 — Shared IR | 4 / 20 | 4 / 20 | — |
| 02 — Text Integrity | 6 / 25 | 6 / 25 | — |
| 03 — Layout | 4 / 18 | 8 / 34 | +4 / +16 |
| 04 — Tables | 3 / 13 | 4 / 20 | +1 / +7 |
| 05 — Charts & Diagrams | 10 / 48 | 10 / 48 | — |
| 06 — Visual Models | 6 / 30 | 6 / 30 | — |
| 07 — Cross-format | 9 / 43 | 9 / 43 | — |
| 08 — Production Hardening | 12 / 58 | 12 / 58 | — |
| **Total** | **57 / 268** | **64 / 301** | **+7 / +33** |

## Dependency changes

- In this historical plan, P00-US04 depended on P00-US01 and P00-US02.
- In this historical plan, then-P00-US05 depended on P00-US03 and P00-US04.
- In this historical plan, P01-US01 depended on then-P00-US05 instead of
  P00-US03, ensuring reviewed
  corpus truth and repeatable runs precede behavior work.
- The approved superseding chain is P00-US04 through P00-US10, with P01-US01
  depending on P00-US10.
- P03-US05, P03-US06, P03-US07, and P03-US08 consume the shared IR and
  relationship-aware ordering capability as declared in their story files.
- P04-US04 depends on P04-US02 and P03-US06.
- P04-US03 now depends on P04-US02, P04-US04, and P03-US04. The recommended
  Phase 04 sequence is P04-US01 → P04-US02 → P04-US04 → P04-US03.
- All other dependency edges are unchanged.

The canonical graph is in
[tracker/dependencies.md](../../../dependencies.md), and the complete
source-reviewed sequence is in
[execution-order.md](../execution-order.md).

## Regression and milestone effect

- M0 runs all 15 cases and establishes approved truth, run identity, semantic
  metrics, and resource baselines.
- M1–M4 use targeted positive, non-target, and negative slices before an
  all-corpus drift screen at each capability boundary.
- M5 cannot close until approved cross-format semantic twins exist.
- M6 runs the full corpus, all added twins and controls, story tests, phase and
  prior-phase regressions, API/schema contracts, performance, privacy, canary,
  and rollback gates.

The detailed subsets and exit criteria are in
[milestone-plan.md](../milestone-plan.md). The exact one-owner mapping for all
25 gaps is in [gap-to-story-matrix.md](../gap-to-story-matrix.md).

## Change boundary

At creation time, this update changed tracker and benchmark evidence only and
implemented no story. Subsequent approved Phase 0 execution completed the
test/reporting-only P00-US01 contract and catastrophe source-truth P00-US02,
then captured and independently validated the five-run P00-US03 catastrophe
baseline without production changes. The remaining 14-case custody boundary
was retained for P00-US04 at that time and was subsequently resolved on
2026-07-29: all remaining triplets and derived annotations are public and
redistributable with no exceptions. The former combined P00-US04 remained
Proposed for its separate scope and finite-denominator failures at that
historical checkpoint. It was superseded; the bounded portable-registry
P00-US04 is now Done after independent review.
