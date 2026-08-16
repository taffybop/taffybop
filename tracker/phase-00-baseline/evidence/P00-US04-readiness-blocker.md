# Former combined P00-US04 Definition-of-Ready result

Status: Closed — oversized story superseded by the approved replacement split  
Evaluation date: 2026-07-28  
Custody reevaluation: 2026-07-29  
Sequence state: stopped after P00-US03 reached Done

> **2026-07-29 denominator correction:** The requester subsequently approved
> 71 claims for P00-US06 and 210 corpus-wide after the case-table recount. The
> 73/212 values below remain the original split evidence. See
> [`P00-US06-claim-denominator-correction.md`](../decisions/P00-US06-claim-denominator-correction.md).

## Outcome

The former combined P00-US04 reached 8 of the 10 Definition-of-Ready checks. It
did not enter `Ready` or `In Progress` because:

1. the stated five-point scope combines more than one independently testable
   delivery unit;
2. “every scored element” and “every mapped story” do not yet have a finite,
   machine-readable claim/control inventory.

The prior custody failure is resolved. On 2026-07-29, the requester confirmed
that all remaining 14 PDF/Markdown/JSON triplets and derived annotations are
public and redistributable with no exceptions.

## Check-by-check result

| # | Definition-of-Ready check | Result | Evidence |
|---:|---|---|---|
| 1 | Scope and non-scope are explicit | Pass | The story identifies benchmark-only work and excludes parser behavior changes. |
| 2 | Points are 5 or fewer | Fail | The nominal five points combine portable corpus/custody registration, generalized schemas, conversion of 2,588 lines of review material, claim masks, and control mapping. These have independent acceptance and rollback boundaries. |
| 3 | Dependencies are Done | Pass | P00-US01 and P00-US02 are Done. |
| 4 | Acceptance criteria are measurable | Fail | Case/page totals are measurable, but “every scored element” and “every mapped story” have no finite machine-readable denominator. |
| 5 | Dedicated tests are identified | Pass | Unit, integration, negative, contract, fixture, and regression test locations are specified. |
| 6 | Fixtures are available and legally usable | Pass | All 45 source/expert artifacts exist and match their recorded hashes. The catastrophe triplet was already approved, and the requester confirmed on 2026-07-29 that all remaining 14 triplets and derived annotations are public and redistributable with no exceptions. |
| 7 | API/schema impact is documented | Pass | No public API impact; benchmark/test schema scope is stated. |
| 8 | Feature-flag requirements are identified | Pass | No feature flag is required for benchmark data. |
| 9 | Rollback behavior is defined | Pass | New registrations can be removed without deleting private source evidence. |
| 10 | Quality and performance measurements are specified | Pass | Corpus validation targets are stated and production parse-time impact is assigned to the runner now numbered P00-US10. |

## Inventory evidence

- 15 case triplets, 30 physical pages, and 45 source/expert artifacts are
  present; every recorded artifact hash matches.
- The reviewed case reports contain 2,588 lines of narrative evidence, exactly
  212 expert-validation rows, and 109 mapped-gap rows.
- Only the catastrophe case currently has machine-readable source-truth
  annotations.
- There is no generalized machine-readable claim inventory, inclusion-mask
  inventory, or target/positive/non-target/negative control registry.
- The frozen corpus manifest records absolute paths and hashes, but not custody,
  redistribution, reviewer/version, annotations, or scoring masks.

## Custody question and resolution

The choice is operational, not a challenge to the factual quality of the
files. It determines whether each exact hash-pinned artifact and its derived
annotations may be:

- copied into the workspace and repository;
- redistributed with the benchmark;
- executed in local, private, or committed CI; or
- replaced with a synthetic equivalent.

Public availability does not by itself state redistribution permission, and
“almost all files” left the exception set unknowable. A fail-closed benchmark
could not safely infer which files the qualification excluded.

The decision now explicitly covers these remaining case IDs:

`clean-energy`, `clinical-study`, `component-datasheet`, `egov-survey`,
`esg-metrics`, `finance-10k`, `health-report`, `insurance-acord`,
`manufacturing-report`, `ny-timetable`, `postal-10k`, `purchase-agreement`,
`settlement-agreement`, and `uber-earnings`.

The approved operational interpretation and immutable-artifact scope are
recorded in
[P00-US04 corpus custody and redistribution decision](../decisions/P00-US04-corpus-custody.md).

## Required scope split

The following replacement was approved by the requester on 2026-07-29:

| Proposed story | Points | Finite scope and denominator |
|---|---:|---|
| P00-US04 — Register the portable corpus | 3 | 15 cases, 30 physical pages, 45 hash-pinned artifacts, custody, page maps, and categories |
| P00-US05 — Define reviewed-claim and mask contracts | 3 | Versioned claim, evidence, region, reviewer, page-identity, and inclusion-mask schemas with P00-US02 backward-read controls |
| P00-US06 — Register reviewed claims batch A | 5 | 73 expert-validation rows: `manufacturing-report`, `esg-metrics`, `catastrophe-recap`, `finance-10k`, and `purchase-agreement` |
| P00-US07 — Register reviewed claims batch B | 5 | 76 expert-validation rows: `clinical-study`, `component-datasheet`, `insurance-acord`, `clean-energy`, and `ny-timetable` |
| P00-US08 — Register reviewed claims batch C | 5 | 63 expert-validation rows: `uber-earnings`, `health-report`, `postal-10k`, `egov-survey`, and `settlement-agreement` |
| P00-US09 — Register benchmark controls | 5 | 25 primary gap/story mappings, each with target, related-positive, non-target, and negative/ambiguous roles; all 109 case-gap rows accounted for |
| P00-US10 — Run immutable corpus baselines | 5 | Existing P00-US05 runner scope, renumbered after the prerequisite registrations |

The three claim batches account for exactly 212 expert-validation rows. The
approved split expands Phase 0 from 5 stories/23 points to 10 stories/44 points
and the full roadmap from 64 stories/301 points to 69 stories/322 points. The
approval is recorded in
[the Phase 0 benchmark-registration scope-split decision](../decisions/P00-US04-scope-split.md).

## Resume conditions

Sequential execution may resume only after:

1. the approved replacement split is applied consistently to the backlog and
   dependencies; and
2. the new P00-US04 passes its own Definition of Ready.

No replacement story or Phase 1 work had started when this audit closed.
