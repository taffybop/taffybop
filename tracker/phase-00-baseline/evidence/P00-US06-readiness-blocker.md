# P00-US06 Definition-of-Ready Blocker

Status: Resolved by approved denominator correction; retained as failure evidence  
Date: 2026-07-29  
Story: P00-US06 — Register reviewed claims batch A

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope explicit | **Fail** | The story fixes batch A at 73 rows and `manufacturing-report` at 23, but the immutable source-review tables contain 71 and 21 respectively. The exact one-to-one scope is therefore unresolved. |
| Points at most 5 | Pass | Story remains 5 points under either finite denominator. |
| Dependencies Done | Pass | P00-US05 is Done after all gates and independent review. |
| Acceptance measurable | **Fail** | AC1 requires 73 records mapped one-to-one to five tables that contain only 71 rows; AC4 cannot reconcile the declared manufacturing/total counts. |
| Dedicated tests identified | Pass | `tests/stories/phase_00/test_p00_us06_reviewed_claims_batch_a.py` is specified. |
| Fixtures available and legally usable | Pass | All five PDF/Markdown/JSON triplets and derived annotations are approved public/redistributable with no exceptions. |
| API/schema impact documented | Pass | Benchmark-data only; no production API/schema effect. |
| Feature flag identified | Pass | None; no production runtime path. |
| Rollback defined | Pass | Remove batch A registration while retaining contracts, sources, and narrative reviews. |
| Quality/performance measures specified | Pass | Classification, locator, unsupported-literal, canonical-hash, and regression measures are specified, although the claim denominator must be corrected first. |

Definition-of-Ready result: **8/10 Pass; 2 Fail**. P00-US06 must remain
Proposed and must not enter Ready or In Progress.

## Independent source-row recount

Rows were counted only inside each frozen case report's
`## Expert element validation` section. Markdown header and separator rows were
excluded; every remaining table row contains exactly one normalized review
status.

### Approved batch A versus current tables

| Case | Approved target | Current table rows | Difference |
|---|---:|---:|---:|
| `manufacturing-report` | 23 | 21 | -2 |
| `esg-metrics` | 13 | 13 | 0 |
| `catastrophe-recap` | 15 | 15 | 0 |
| `finance-10k` | 11 | 11 | 0 |
| `purchase-agreement` | 11 | 11 | 0 |
| **Batch A** | **73** | **71** | **-2** |

The manufacturing section contains three expert-validation tables with
8 + 8 + 5 = 21 data rows. The approved value 23 cannot be reproduced from
those tables; its exact counting error was not recorded.

### Corpus reconciliation

| Batch | Approved target | Current table rows |
|---|---:|---:|
| A — P00-US06 | 73 | 71 |
| B — P00-US07 | 76 | 76 |
| C — P00-US08 | 63 | 63 |
| **Corpus** | **212** | **210** |

The 210 rows classify completely as:

| Review status | Rows |
|---|---:|
| Verified | 121 |
| Partially verified | 41 |
| Incorrect | 21 |
| Not independently verifiable | 17 |
| Potentially inferred | 10 |
| **Total** | **210** |

The P00-US05 implementation reviewer independently reproduced the 71/76/63
batch counts, 210 total, and the complete status distribution.

## Why execution must stop

P00-US06 AC1 says records map one-to-one to source-review table rows. It is
impossible to produce 73 one-to-one records from 71 rows without either
changing the approved denominator or changing what “one-to-one” means. Adding
two invented rows would violate the source-grounded benchmark boundary.
Mutating the frozen case report is not authorized.

Custody is not a blocker: all five triplets and their derived annotations are
public and redistributable. The blocker is solely the contradictory approved
claim denominator.

## Resolution choices

1. **Recommended — correct the target to the source evidence.** Approve batch A
   as 71 claims, `manufacturing-report` as 21, and the all-corpus target as 210.
   Retain the one-to-one row requirement and frozen case reports. Story points
   remain 5.
2. Keep 73/212 only by approving two explicitly named, source-reviewed
   manufacturing subclaims in a new sidecar and changing AC1 from one-to-one
   table rows to one-to-one atomic claims. This needs a separate review
   decision; the two claims cannot be inferred or fabricated.
3. Unfreeze and edit the manufacturing case report to add two real validation
   rows. This is not recommended because it changes the frozen analysis record.

No option has been applied. Explicit requester approval is required before the
approved finite denominator or one-to-one acceptance boundary changes.

## Resolution

On 2026-07-29, the requester approved option 1: batch A is corrected to 71,
`manufacturing-report` to 21, and the all-corpus total to 210. The one-to-one
row requirement and frozen reports are retained. The superseding decision is
[`P00-US06-claim-denominator-correction.md`](../decisions/P00-US06-claim-denominator-correction.md).

This record preserves the failed 8/10 gate. P00-US06 required and subsequently
received a fresh Definition-of-Ready evaluation against the corrected scope.
