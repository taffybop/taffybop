# P00-US04 all-corpus source-use decision

Decision date: 2026-07-29  
Decision status: Approved with no exceptions  
Approver: Workspace requester and artifact provider  
Expiry: None stated

## Decision

The requester confirmed in the active Phase 0 conversation that all remaining
14 PDF/Markdown/JSON triplets and their derived annotations are public and
redistributable with no exceptions. Together with the P00-US02 catastrophe
decision, this approves all 15 corpus triplets.

The covered 15-case, 45-artifact inventory is pinned by:

| Inventory | SHA-256 |
|---|---|
| `tracker/benchmarks/llamaparse-15/manifest.json` | `16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052` |

That manifest records the SHA-256 digest of every covered PDF, Markdown, and
JSON artifact. The remaining 14 case IDs are:

`clean-energy`, `clinical-study`, `component-datasheet`, `egov-survey`,
`esg-metrics`, `finance-10k`, `health-report`, `insurance-acord`,
`manufacturing-report`, `ny-timetable`, `postal-10k`, `purchase-agreement`,
`settlement-agreement`, and `uber-earnings`.

These exact artifacts and source-reviewed annotations derived from them may be
retained in the workspace, committed to a repository, redistributed with the
benchmark, and used in local, private-CI, and committed-CI validation.

## Boundaries

- This is the requester's source-use attestation; no independent license review
  or named license was supplied.
- The decision does not authorize mutation of the source/expert artifacts.
- Expert output remains comparison evidence, not automatic source truth.
- This decision authorizes benchmark/test metadata and use only. It does not
  authorize production parser changes, hosted processing, dependency changes,
  or Phase 1.
- Definition-of-Ready, bounded-scope, measurable-acceptance, test, regression,
  completion, and approval gates remain in force.

## Consumers and rollback

Affected consumers are the remaining Phase 0 corpus registry, reviewed-claim,
control-registry, and baseline-run stories. Rollback removes registrations and
derived annotations from active use; it does not delete or modify the approved
source/expert artifacts.
