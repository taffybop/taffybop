# P03-US08 Latency-Phase Administrative Continuity Renewal

Status: **Accepted by explicit sponsor authorization; exact independent review required before any LAT story is Done**  
Date: 2026-08-08  
Decision ID: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260808-PHASE-LATENCY-CONTINUITY`

## Purpose and authority

The requester explicitly authorized autonomous completion of `phase-latency`
while requiring every improvement to preserve existing reliability, stability,
correctness, quality, safety, compatibility, and rollback. This decision is the
narrow administrative continuity record needed to let independently gated,
default-off latency work proceed without falsely relabelling the protected
P03-US08 result.

This is not a strict P03-US08 metrics pass, a production approval, a release
approval, a Phase 04 completion, or Phase 05 authority. It does not authorize a
latency change that modifies protected running-region semantics, reachability,
stage-specific behavior, custody, or outputs.

## Immutable exception basis

The sole accepted P03-US08 observation remains failed attempt 48 for
`ny-timetable` at `running_region_projection`:

| Field | Exact value |
|---|---:|
| Metric | `latency_p95_seconds` |
| Observed | `0.050946750` seconds |
| Strict ceiling | `0.050000000` seconds |
| Overrun | `0.000946750` seconds |
| Overrun fraction | `0.018935` (`1.8935%`) |
| Maximum candidate-specific bound | `0.05` (`5%`) |

Attempt 48 remains failed. Its raw identity remains SHA-256
`1289f186c1cd6ee7f99eaa843f66e5416f15c0215e205e0ed5936737cd2a7123`
at 158,921 bytes and its recorded semantic SHA-256 remains
`51433843638d69a2d09ced0d96a44a34323b1f5ece9c890c7c91088bac2df2e5`.
Failed history remains sealed through attempt 55 as exactly 55 artifacts under
manifest SHA-256
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.
The canonical strict-final artifact remains absent and the complete companion
remains quarantined.

Every existing ceiling is unchanged. In particular:

- running-region projection p95: `0.050000000` seconds;
- source-extraction p95: `0.250000000` seconds;
- paired parser ceilings: `2.338000000` seconds for `ny-timetable` and
  `1.457500000` seconds for `uber-earnings`;
- allocation delta and peak-RSS delta: `67,108,864` bytes each; and
- source report size: `8,388,608` bytes.

The maximum 5% bound remains candidate-specific to the exact attempt-48
observation. It is not a replacement ceiling or a general tolerance.

## Closed latency-change classifier

A `phase-latency` change is admitted by this renewal only when every condition
below is true:

1. It belongs only to LAT-US01 through LAT-US08 in their dependency order, with
   no more than one story In Progress.
2. It is default off and disabling its latency flag chain restores the exact
   configured predecessor without latency-phase work, output drift, residual
   workers, caches, or telemetry.
3. It does not change P03 running-region selection, source evidence, semantic
   rules, projection, printed-page identity, reachability, call count, error
   interpretation, public output, serializer meaning, or custody.
4. Generic measurement or execution-lifecycle work may observe an external
   running-region boundary only when the protected P03 implementation and its
   stage-specific behavior remain unchanged. A change to whether, when, how
   often, or with which evidence a protected P03 function executes is not
   admitted.
5. It does not weaken, skip, rescore, average away, or reinterpret any latency,
   RSS, resource, correctness, quality, security, compatibility, custody,
   output, timeout, rollback, or hosted-use gate.
6. Final-code identities, comparable inputs, configuration, dependencies,
   fixtures, failures, results, and reviewer findings remain retained and
   reviewable. Ambiguity fails closed.
7. It adds no production enablement, hosted use, Phase 04 table behavior,
   Phase 05 work/status transition, or capability outside `phase-latency`.

Shared-file placement, indirection, a default-off flag, or a claimed speedup
does not make a mixed change admissible. Any mixed latency/running-region
change is a protected P03 change and expires this renewal before reliance.

## Gates not waived

No gate other than the exact attempt-48 projection-p95 observation is waived.
All of the following remain independently blocking and fail closed:

- RSS, allocation, CPU/GPU, process, thread, file-descriptor, queue, timeout,
  cancellation, cleanup, and other resource limits;
- paired parser, source-extraction, projection, and canonical paired
  LlamaParse latency gates;
- correctness, source fidelity, quality, non-fabrication, determinism, and
  preservation of alternative evidence;
- malformed-input, security, privacy, and fail-closed behavior;
- API, schema, canonical serializer, frontend, and predecessor compatibility;
- code, dependency, fixture, benchmark, input, evidence, model, and hosted-use
  custody;
- output-size, diagnostic, cost, and egress limits; and
- default-off behavior, exact rollback, independent review, and every prior-
  phase or latency-story exit gate.

Latency cannot be credited by omitting extraction work without independently
sufficient source evidence, dropping failures, using cache hits in an uncached
comparison, reducing output quality, or masking a slow case with an aggregate.

## Expiry, review, and rollback

This renewal must remain reviewable no later than **2026-09-02** and expires at
the earliest of:

- immediately before production enablement or production reliance;
- immediately before any relevant P03 running-region semantic, runtime,
  reachability, output, dependency, evidence, or custody change;
- immediately before any ceiling, maximum-bound, default-off, rollback, or
  non-waived-gate change;
- immediately before work outside LAT-US01–LAT-US08, any Phase 04 behavior
  change while Phase 04 is paused, or any Phase 05 work/status transition;
- immediately on classifier ambiguity, bypass or suppression of a required
  gate, or rollback failure; or
- at `2026-09-02T23:59:59Z` unless earlier replaced by a reviewed renewal or a
  strict current-code P03-US08 campaign.

Expiry is fail closed. The immediate latency rollback is to disable every
`PARSER_LATENCY_*` switch in reverse dependency order and restore the exact
configured predecessor. `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false
by default and independent; disabling it continues to perform zero P03-US08
work. No production use is authorized.

## Required review and evidence

The machine-readable companion is
[`LAT-P03-US08-latency-continuity-renewal.json`](../evidence/LAT-P03-US08-latency-continuity-renewal.json).
Before any LAT story is marked Done, independent production/security and
metrics/custody reviewers must verify the exact renewal bytes, immutable
attempt-48 facts, classifier closure, expiry triggers, rollback, all non-waived
gates, and absence of a strict-pass or production claim. Story-level and phase-
exit reviews remain separately mandatory.

