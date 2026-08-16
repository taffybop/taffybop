# P03-US04 Completion Report

Status: Done  
Story: Resolve relationship-aware reading order and bboxes  
Points: 5  
Started: 2026-07-31
Completed: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — final order plus source-evidence ownership validation; no semantic column inference, ungrounded content mutation, table repair, bbox mutation, or Phase 04 work |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P03-US03 and P01-US03 |
| Acceptance measurable | Pass — exact 41-pair denominator, reviewed clinical ownership correction, clean-energy two-child reorder, keyed immutability elsewhere, exact rollback, idempotence, and serializer parity |
| Dedicated tests identified | Pass — unit, story, negative, contract, real corpus, frontend, performance, custody, and cumulative regression paths |
| Fixtures available and authorized | Pass — nine immutable reviewed PDFs, mandatory P00-US09 four-role matrix, and bounded synthetic adversarial fixtures |
| API/frontend impact documented | Pass — item/block/view order, contiguous rank, one exact off-bbox contribution, and one exact two-child/parent reorder may change; schema stays stable and frontend does not infer |
| Feature flag identified | Pass — `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED`, default off and normalization-gated |
| Rollback defined | Pass — disable one flag for exact P03-US03 predecessor including absence of US04 diagnostics |
| Quality/performance specified | Pass — 41/41, zero remaining ownership/duplicate violations, keyed parity outside the two audited corrections, 5% paired p95, 50 ms stage p95, 250 ms limit case, <32 MiB allocation |

Definition-of-Ready result: **10/10 Pass**. Independent contract-readiness and
source-truth reviews both returned 10/10 with no blocker. P03-US04 is the sole
story in progress; P03-US05 remains Proposed. The accepted contract is
[P03-relationship-order-policy.md](../decisions/P03-relationship-order-policy.md).

## Implementation

The default-off projector now runs after the accepted P03-US01–US03 layout
stages and, including terminal source-alignment re-entry, performs a bounded
transactional final presentation pass:

- normalizes finite geometry through authoritative `transform_to_page`;
- creates atomic side-aware caption/owner/source-note bundles from trusted
  typed relationships;
- combines those hard constraints with bounded finite page-space ordering;
- preserves stable predecessor rank for ambiguity and validates a complete
  candidate `DocumentIR` inside the rollback boundary;
- rewrites page presentation arrays and contiguous public ranks together;
- moves only the two reviewed timetable title fragments before their unique
  physical-page-2 table;
- performs only the two exact allowlisted source-grounded content corrections;
  and
- emits bounded content-free concerns while restoring the exact affected
  predecessor page on any failure.

Marker fallback trust is bound to exact relationship ID, predecessor story,
and story-compatible relationship type. Raw clinical charspans prove coverage
and ownership but never reconstruct text; the one terminal contaminant is
removed from the predecessor scalar while all owned prefix bytes remain
unchanged.

The frontend production path did not need geometry logic. Its existing
canonical and legacy serializers consume backend item/block order; dedicated
tests cover normalization, rendering, copy, and download parity.

## Verification

The fixed real-corpus denominator passes **41/41** ordered pairs across all
nine reviewed cases. IDs are unique, public ranks contiguous, canonical order
matches page arrays, JSON round trips, and keyed mutations remain within the
two exact audited corrections. Finance is byte-equivalent across the flag;
the timetable page-3 negative remains unchanged.

Final gates:

- focused/adversarial/contract/performance/custody: **47 passed**;
- real-corpus regression: **44 passed**, 36 existing upstream warnings;
- independent truth/security review: **10/10 Pass**;
- independent contract/readiness review: **10/10 Pass**;
- frontend Node 22.18 lint, typecheck, production build, **67/67 unit**, and
  **1/1 bundle**: **Pass**; and
- targeted Ruff: **Pass**.

Five alternating fresh-process pairs recorded clipped inclusive p95 overhead
of **0.256858 s** for manufacturing (**2.2181%**, ceiling 0.579 s) and
**0.140290 s** for Uber (**0.4813%**, ceiling 1.4575 s). The isolated stage
recorded p50 **26.970 ms**, p95 **31.095 ms**, max **40.115 ms**, and peak
traced allocation **875,312 bytes**. The 512-anchor boundary completed in
**44.638 ms** against the 250 ms ceiling.

The retained artifact is
[P03-US04-reading-order-metrics.json](../evidence/P03-US04-reading-order-metrics.json),
373,160 bytes, with raw SHA-256
`826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154`
and semantic SHA-256
`46cef72e08707cc57fd54834c7ff4369a59558b4e2de1a47155da23b66803ab1`.
It binds final code, ten immutable PDFs, dependency manifests, local tool
identity, performance, rollback, and zero hosted usage. Detailed evidence is
in [P03-US04-verification.md](../evidence/P03-US04-verification.md).

The existing Starlette/httpx and upstream Docling warnings remain. No
controllable browser was available, so manual click-through is not claimed
and remains a Phase 03 exit retry.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria and 41/41 fixed pairs |
| Dedicated and adversarial tests pass | Pass |
| Impacted regressions and real benchmarks pass | Pass |
| API/schema and canonical compatibility pass | Pass |
| Frontend visible-path compatibility passes | Pass — automated milestone; browser unavailability recorded |
| Security/resource bounds pass | Pass — bounded geometry, relationships, data, concerns, and transactional rollback |
| Final-code metrics and exact input custody retained | Pass |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — truth/security, contract, and metrics/custody approved at 10/10 |
| No concurrent next story | Pass — P03-US05 remains Proposed |

Definition-of-Done result: **10/10 Pass**. P03-US04 is Done. P03-US05 is the
next dependency-ready Phase 03 story but remains Proposed until its separate
readiness gate passes. No Phase 04 work has started.
