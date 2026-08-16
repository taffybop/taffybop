# Phase 0 benchmark-registration scope split

Status: Approved  
Approval date: 2026-07-29  
Authority: workspace requester in the active execution thread

> **2026-07-29 denominator correction:** The requester subsequently approved
> batch A at 71 claims and the corpus at 210 after a source-table recount. The
> original split below is retained as the approval-time record. See
> [`P00-US06-claim-denominator-correction.md`](P00-US06-claim-denominator-correction.md).

## Decision

The requester approved replacing the oversized P00-US04/P00-US05 portion of
Phase 0 with this bounded sequence:

| Story | Points | Scope |
|---|---:|---|
| P00-US04 | 3 | Portable 15-case corpus registry |
| P00-US05 | 3 | Reviewed-claim and inclusion-mask contracts |
| P00-US06 | 5 | Reviewed claims batch A: 73 claims across 5 cases |
| P00-US07 | 5 | Reviewed claims batch B: 76 claims across 5 cases |
| P00-US08 | 5 | Reviewed claims batch C: 63 claims across 5 cases |
| P00-US09 | 5 | Benchmark control registry for 25 primary gap owners and 109 case-gap rows |
| P00-US10 | 5 | Immutable corpus runner previously identified as P00-US05 |

The existing completed P00-US01 through P00-US03 stories retain their IDs and
evidence. The former P00-US05 runner is renumbered P00-US10; historical records
that accurately describe its former proposed ID remain historical and should
not be rewritten as if the earlier plan never existed.

## Totals and dependencies

- Phase 0: 10 stories, 44 points.
- Full roadmap: 69 stories, 322 points.
- P00-US04 depends on P00-US01 and P00-US02.
- P00-US05 depends on P00-US04.
- P00-US06 depends on P00-US05.
- P00-US07 depends on P00-US06.
- P00-US08 depends on P00-US07.
- P00-US09 depends on P00-US08.
- P00-US10 depends on P00-US03 and P00-US09.
- P01-US01 depends on P00-US10.

## Boundaries

The original sequential Phase 0 authorization continues to apply to this
approved replacement sequence. Every replacement story must independently pass
Definition of Ready and Definition of Done, only one story may be In Progress,
and all original mandatory-stop conditions remain in force. Phase 1 remains
unauthorized.
