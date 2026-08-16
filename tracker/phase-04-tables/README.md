# Phase 04 — Tables

Status: Complete — release-first core functionality validated  
Outcome: Source-faithful table candidates, cells, spans, representations, and
safe continued-table handling

## Release-first phase policy

Phase 04 may resume as the first delivery phase under the
[Phases 04–08 release-first policy](../release-first-phases-04-08.md).
P04-US01 completed its focused flag-on end-to-end table check and rollback
check. P04-US02 completed bounded cross-engine reconciliation, additive public
serialization, malformed-candidate fallback, and flag-off rollback checks.
P04-US04 completed deterministic typed ownership gating, noncanonical
alternative retention, malformed-candidate isolation, and flag-off rollback.
P04-US03 completed adjacent continuation scoring, page-preserving derived
grids, repeated-header handling, deterministic refusal, and flag-off rollback.
All four Phase 04 stories are complete under the release-first
core-functionality standard. Phase 05 has not been started.
Story completion does not require an RSS/latency campaign, process-lineage
accounting, retained evidence bundle, independent review, or exact-environment
qualification. Historical records below remain unchanged and non-passing
where they previously failed.

P04-US01's last approved pre-retention metrics mechanics were governed by the
[`external-RSS lane final-code amendment`](decisions/P04-US01-external-rss-lane-final-code-amendment.md)
and the later
[`conditional stage-reachability amendment`](decisions/P04-US01-conditional-stage-reachability-final-code-amendment.md).
Canonical v11 attempt 01 failed closed on the unchanged current-RSS cadence
gate and is sealed with no returned snapshot or final artifact. The later
[`leased-identity classified-cadence amendment`](decisions/P04-US01-leased-identity-classified-cadence-monitor-amendment.md)
is preserved as an unapproved v12 design. It is controlled-superseded for any
future execution by the pending
[`v13 compact-transport monitor decision`](decisions/P04-US01-v13-compact-transport-monitor-controlled-supersession.md).
The v13 implementation and live records still require exact-byte independent
approval and a separately reviewed immutable one-shot predeclaration. All
accidental preapproval activity is failed/noncanonical history. Every `v6`,
`v10`, and `v11` failure remains intact, the final artifact remains absent,
and no current-artifact metrics pass is asserted. On 2026-08-07 two
independent reviews rejected the initial frozen v13 bundle for deadline,
append-proof, failure-custody, protocol-state, and cleanup defects; the exact
rejection is retained in
[`P04-US01-v13-initial-exact-bundle-independent-review-rejected.md`](evidence/P04-US01-v13-initial-exact-bundle-independent-review-rejected.md).
The reserved v13 review leaf is not approval. Corrective successor work is
non-operative and has no real-execution authority until it is frozen under a
new version and independently approved.

## Release entry criteria

- Required Phase 03 production dependencies are available.
- Each story has one representative positive fixture and one ordinary
  conflict/fallback fixture suitable for a focused end-to-end check.

## Release exit criteria

- Repeated visible cells are not converted into fabricated spans.
- Docling and vector candidates reconcile with recorded evidence.
- Cell bboxes, confidence, provenance, captions, and concerns survive.
- Dense, rotated, multilevel, multiline, borderless, and form-grid tables retain
  reviewed row/column/header/span structure or fail closed with a concern.
- Charts, forms, and aligned prose do not become canonical tables; true
  borderless and coverage-grid candidates remain available.
- HTML, Markdown, rows, CSV, and JSON agree on canonical grid shape and cell
  identity.
- Multi-page merges occur only with measurable structural evidence.
- A representative table flow proves span fidelity, candidate reconciliation,
  visual-impostor rejection, and safe continuation or refusal.
- Flags default off, flag-off output remains compatible, and no known defect
  blocks the supported table flow.

## Stories

1. [P04-US01](stories/P04-US01.md) — Preserve explicit table cells and span fidelity — **Done**
2. [P04-US02](stories/P04-US02.md) — Reconcile Docling and vector table evidence — **Done**
3. [P04-US04](stories/P04-US04.md) — Gate table candidates and reject visual impostors — **Done**
4. [P04-US03](stories/P04-US03.md) — Handle continued and multi-page tables safely — **Done**

Total: 20 story points.

## Historical authorization and readiness checkpoint

The requester explicitly authorized Phase 04 on 2026-08-03. The accepted
[authorization decision](../decisions/2026-08-03-phase-04-authorization.md)
opens P04-US01 Definition-of-Ready work and authorizes sequential execution of
the four stories through the Phase 04 exit gate. It does not waive any gate or
authorize Phase 05.

P04-US01 passed its independent **10/10** Definition-of-Ready review on
2026-08-03. The exact hardened P03-US08 renewal received final independent
production/policy, metrics/custody/resource, and compatibility/boundary
approval on 2026-08-04, so P04-US01 entered In Progress at that historical
checkpoint. On 2026-08-08, the requester made Phase Latency the sole active
workstream; P04-US01 returned to **Ready — execution paused** without changing
its readiness or evidence. Under the current release-first policy P04-US01,
P04-US02, P04-US04, and P04-US03 are complete; Phase 04 is release-first
complete and Phase 05 remains outside the authorized work boundary.

Hardened superseding renewal (2026-08-03): the narrow
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](../phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](../phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json)
resolve that prerequisite for the named, default-off Phase 04 table paths and
protected table functions. Exact-bundle approval is recorded in
[the independent approval](../phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
At that historical checkpoint P04-US01 was Ready with execution paused. The
2026-08-10 release-first policy now permits Phase 04 to resume and supersedes
the former exclusive Phase Latency scheduling hold.
Attempt 48 remains failed at `ny-timetable` /
`running_region_projection` p95 **0.050946750 seconds** against the unchanged
**0.050000000-second** ceiling (**0.000946750 seconds / 1.8935%** over, within
the maximum **5%** candidate-specific bound); the companion remains
quarantined, strict-final evidence remains absent, and Phase 03 is not a
strict current-artifact metrics pass. Table-only changes admitted and sealed
by the executable record, and Phase 04 exit within that unchanged scope, no
longer trigger the former blanket required-code expiry. Any protected
running-region semantic/runtime/custody change or expansion of the admitted
Phase 04 scope requires a new explicit decision and expires the renewal before
the change; production enablement remains prohibited and review is due no
later than **2026-09-02**. Default-off rollback and every non-waived RSS,
paired/source/Uber latency, correctness, security, compatibility, custody,
resource, output, rollback, and hosted-use gate remain mandatory.

The current sponsor-authorized administrative continuity layer is
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260807-PHASE04-TABLES-ADMINISTRATIVE-CONTINUITY`](../phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md)
with a
[closed machine-readable classifier](../phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json).
It permits ongoing development, tests, fixtures, metrics infrastructure,
evidence, frontend work, and documentation only when semantically table-only,
default-off, and unrelated to protected P03 running-region behavior or
custody. It is not authority to mark a story Done, exit Phase 04, enable
production or hosted use, or enter Phase 05. Exact final-code gates and reviews
remain required. The exact frozen classifier received
[independent policy/custody approval](../phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md)
on 2026-08-07 with all nine required checks passing. That approval is limited
to administrative continuity and cannot replace any exact final-code, story,
production/security, metrics/custody, or Phase 04 exit review.

## Canonical Phase 04 latency benchmark

For prospective Phase 04 Definition-of-Done and exit decisions, the sole
operative candidate-latency comparator is the
[`Phase 04 LlamaParse latency supersession`](decisions/P04-LlamaParse-latency-canonical-supersession.md),
bound to the authenticated
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md):
LlamaCloud Parse v2, Agentic mode at 10 credits/page, cost optimizer off, cache
disabled, using the provider UI's **Total Latency** measurement. The initial
2026-08-08 one-sample-per-case observations are planning/reference ceilings
only and cannot complete a story or the phase.

Before Definition of Done or Phase 04 exit, every applicable case must be
refreshed with at least five interleaved candidate/Llama observations. For each
case independently, candidate p50 and empirical inclusive nearest-rank p95 must
each be less than or equal to the paired Llama p50 and p95. Corpus averages
cannot mask a slow case, and failed observations cannot be dropped. A case with
no semantically comparable Llama input/output is **Unmeasured/Blocked**; old M0
local-parser timings, flag-off comparisons, and local stage/component timings
remain diagnostics only and can never substitute for the Llama comparator.
Latency cannot pass unless all required quality and reliability results also
pass unchanged.

This prospective latency supersession does not rewrite historical decisions or
evidence and does not alter the P03-US08 exception above. That exception still
governs P03 only, including its exact attempt-48 observation, ceilings, bound,
expiry, rollback, and non-waived gates; it is not the Phase 04 candidate
latency comparator. All Phase 04 correctness, quality, RSS/memory, security,
compatibility, custody/hosted-use, resource, output, timeout/fail-closed,
default-off, and rollback gates remain cumulative and mandatory.
