# Decision: source-grounded root-cause queue

Date: **2026-08-13**  
Status: **Accepted for tracker organization; no production work authorized by this record**

## Decision

Maintain a separate functional-fidelity queue with 13 root-cause defect cards
and 22 bounded implementation slices. Enforce a WIP limit of one production
defect. Existing Phase/User Stories remain the ownership record; issue cards
link to them and add correction acceptance criteria rather than rewriting
historical completion evidence.

Every slice also has an immediate affected-benchmark transition gate. After a
fix and its focused tests pass, each relevant full benchmark PDF must be run
separately through fresh LlamaParse and service jobs before that slice can move
from `Validating` to `Done` or the next production slice can begin. Both systems'
raw Markdown, actual rendered Markdown UI/DOM snapshots, and full unprojected
JSON responses must be retained immutably. The comparison at this gate targets
the particular defect's exact oracle, named symptoms, and declared collateral
boundary. Complete post-fix service outputs receive automated structural drift
comparison against their bound pre-fix service artifacts, fresh LlamaParse
outputs are checked for reference drift, and every changed service region
outside the boundary receives manual review. Unit tests alone never satisfy
this gate.

## Rationale

- Treating 278 correlated comparator rows as independent tickets would inflate
  the backlog and lead to repeated fixes for the same cause.
- Treating all chart or layout gaps as one ticket would make acceptance and
  rollback unreviewable.
- Root-cause cards preserve deduplication, while bounded work items permit
  one-at-a-time implementation and evidence closure.
- Immediate per-slice benchmark comparison proves the particular defect across
  all three surfaces and catches out-of-boundary drift while the responsible
  change is still isolated, instead of deferring discovery until a wave or
  release campaign.
- Retaining and automatically diffing complete outputs preserves broad drift
  visibility without repeatedly performing an exhaustive manual whole-PDF
  audit for every small defect. That comprehensive review belongs to the wave
  and final all-15 gates.
- The PDF is authoritative. LlamaParse remains the requested baseline but is
  not copied where it invents prose, values, or topology.

## Consequences

- `issues/` is the source of truth for defect state.
- `execution-order.md` is the current functional remediation queue; historical
  phase ordering remains historical context.
- Shared-root fixes require their entire control family plus an all-15 drift
  screen at the end of the wave.
- Each slice remains `Validating` until fresh LlamaParse and service artifacts
  for every affected full benchmark PDF prove its exact oracle and named
  symptoms resolved across raw Markdown structure, actual rendered UI/DOM
  presentation, and full JSON structure/content within the declared collateral
  boundary. The evidence must include source/job/build/settings and artifact
  hashes plus an issue-specific reviewer decision.
- Each complete post-fix service Markdown, DOM representation, and JSON output
  is automatically drift-compared with its bound pre-fix service artifact, and
  the fresh LlamaParse capture is checked against the selected prior reference.
  Every changed service region outside the declared boundary is manually
  adjudicated; unchanged unaffected regions are not exhaustively re-audited at
  this transition gate.
- A failed or incomplete affected-benchmark comparison returns the slice to
  `In Progress`; test success cannot override it. An acceptable difference
  requires explicit, bounded, source-grounded approval.
- The per-slice gate and wave screens are additive. After all defects close, a
  frozen release candidate must still complete the fresh final end-to-end
  LlamaParse/service comparison across all 15 benchmark PDFs before any
  functional-equivalence release claim.
- New stories are required for Uber undirected grouping and Component pinout
  topology because the existing directed-connector story does not promise
  those families. Diagnostic photo OCR receives a new story only if a source
  review decides it is release-relevant.
- This decision creates tracking structure only. Moving a card to `Ready` and
  beginning implementation remains an explicit subsequent action.
