# Reviewed-claim denominator correction

Status: Approved  
Approval date: 2026-07-29  
Authority: workspace requester in the active execution thread

## Decision

The requester approved correcting the reviewed-claim denominator to match the
frozen source-review tables one-to-one:

| Scope | Previous target | Approved corrected target |
|---|---:|---:|
| P00-US06 batch A | 73 | 71 |
| `manufacturing-report` | 23 | 21 |
| P00-US07 batch B | 76 | 76 |
| P00-US08 batch C | 63 | 63 |
| All 15 cases | 212 | 210 |

The correction preserves every existing source-review row and does not create,
split, infer, or delete an annotation. Batch A remains five cases and five
story points. Phase 0 remains 10 stories/44 points; the complete roadmap remains
69 stories/322 points.

## Evidence

The 15 `## Expert element validation` sections contain exactly 210 data rows:
71/76/63 across batches A/B/C. The three manufacturing tables contain
8 + 8 + 5 = 21 rows. All rows classify exactly once as 121 verified, 41
partially verified, 21 incorrect, 17 not independently verifiable, and 10
potentially inferred.

The recount and original readiness failure are retained in
[`P00-US06-readiness-blocker.md`](../evidence/P00-US06-readiness-blocker.md).

## Boundaries

- The frozen case reports and all PDF/Markdown/JSON triplets remain unchanged.
- One claim record must still map one-to-one to one review-table row.
- P00-US07 and P00-US08 case/batch counts remain unchanged.
- P00-US09 must resolve controls against the corrected completed 210-claim
  corpus.
- No production parser, API, schema, dependency, configuration, or Phase 1
  behavior is authorized by this correction.

This decision supersedes only the 73/212 numerical targets in the prior Phase 0
split. All other scope, points, dependencies, sequential gates, and
mandatory-stop conditions remain in force.
