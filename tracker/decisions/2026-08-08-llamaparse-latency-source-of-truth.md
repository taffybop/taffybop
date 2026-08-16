# LlamaParse Latency Source-of-Truth Decision

Status: **Accepted for prospective unfinished-phase planning by explicit sponsor direction**  
Date: 2026-08-08  
Scope: latency benchmark policy for Phases 04–08 only

## Decision

The sole operative latency benchmark for every In Progress or Proposed story
in Phases 04–08 is the authenticated
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md).
The controlling provider measurement is LlamaCloud Parse v2, Agentic tier,
cost optimizer off, cache disabled, **Total Latency**.

The initial per-case values are planning/reference ceilings only. A story,
phase exit, canary, or release decision requires at least five interleaved
candidate/Llama observations per applicable case on the final candidate and a
semantically comparable Llama request. Candidate p50 and inclusive
nearest-rank p95 must each be no greater than their paired Llama values for
every case. No corpus average, discarded failure, cache hit, incomparable
format, reduced-quality path, or reduced-reliability path may create a pass.
An unavailable comparator is **Unmeasured/Blocked**.

## Supersession

Effective prospectively on 2026-08-08, previous local-parser durations,
matching-environment percentage tolerances, candidate flag-off ratios,
fixed-duration ceilings, stage/component latency budgets, and generic
“approved budget” latency targets are non-operative for Phase 04–08 latency
acceptance. Live planning documents must remove or explicitly retire those
benchmarks and point to the canonical LlamaParse record. Immutable completed
records, failed attempts, and historical decisions remain available for audit,
but cannot be relied upon as a current candidate-latency comparator.

For Phase 04, this latency-only supersession controls prospectively over the
candidate-latency clauses in these retained historical lineages without
rewriting their files:

- `P04-table-evidence-policy`;
- `P04-US01-table-stage-overhead-controlled-supersession`;
- `P04-US01-phase04-stage-peak-rss-controlled-supersession`;
- `P04-US01-external-rss-lane-final-code-amendment`;
- `P04-US01-conditional-stage-reachability-final-code-amendment`; and
- `P04-US01-v13-compact-transport-monitor-controlled-supersession`.

Their timing samples remain diagnostic history. Their RSS, process identity,
sampling cadence, cleanup, output, timeout/deadline safety, quality,
correctness, security, compatibility, custody, hosted-use, default-off, and
rollback requirements are not superseded.

Safety deadlines, monitor-cadence limits, request timeouts, recovery
objectives, and resource budgets are operational controls rather than parser
latency benchmarks and remain independently blocking. Local stage timings may
be retained only for attribution and optimization diagnosis; they cannot pass,
fail, offset, or waive the LlamaParse gate.

## Completed-phase and exception boundary

Phases 00–03 remain complete and immutable. This decision does not amend or
replace the active P03-US08 exception. Attempt 48 remains failed at
`running_region_projection` p95 `0.050946750` seconds against the unchanged
`0.050000000`-second ceiling: `0.000946750` seconds / `1.8935%` over, within
the maximum 5% candidate-specific bound. Strict-final evidence remains absent.
The exception remains default off, reviewable no later than 2026-09-02, and
expires before production enablement or any relevant running-region
semantic/runtime/custody change. It waives no RSS, paired/source/Uber latency,
correctness, security, compatibility, custody, resource, output, rollback, or
hosted-use gate. Phase 03 must not be described as a strict current-artifact
metrics pass.

## Non-waiver and boundary

Correctness, source fidelity, quality, security, privacy, hosted-use/custody,
API/schema/serializer/frontend compatibility, CPU/GPU/resources, RSS/memory,
output, cost/egress, determinism, timeout/fail-closed behavior, default-off,
rollback, dependency integrity, manual review, and release approval remain
cumulative and mandatory. Remote RSS is unknown, not zero.

This administrative decision changes no production code, test executable,
configuration, API, serializer, frontend behavior, dependency, story status,
or completed evidence. P04-US01 remains the sole In Progress story. All other
Phase 04 stories and every Phase 05–08 story remain Proposed. It authorizes no
Phase 05 implementation or production enablement.

Executable enforcement, refreshed paired evidence, exact final-code
identities, and independent production/security plus metrics/custody approval
remain required before any completion or release claim.
