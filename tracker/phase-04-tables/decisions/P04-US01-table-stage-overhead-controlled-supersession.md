# P04-US01 Table-Stage Overhead Controlled Supersession

Status: Implemented for review; fresh final metrics and independent approval pending  
Date: 2026-08-06  
Scope: P04-US01 metrics, tests, and documentation only  
Formula ID: `p04-us01-paired-nonnegative-additive-table-stage-over-flag-off-wall-v1`  
Paired-performance schema: `p04-us01-paired-performance-v2`

## Trigger and classification

The `p04-us01-table-metrics-v2` harness calculated a paired named-stage ratio
as `max(0, T_on - T_off) / T_off`, where `T_off` was the flag-off duration of
the named hook union. That denominator is incidental and can be extremely
small because most enabled-only table work is unreachable when the feature is
off. It therefore measured the incremental work as a multiple of a tiny hook
duration rather than as additive cost against the paired parser baseline.

This record controls a test-only metric interpretation. It changes no
production code, feature setting, runtime behavior, resource limit, or
threshold. It is not a waiver, retrospective metrics pass, story-completion
record, terminal evidence, or approval. The canonical retained P04-US01 final
metrics artifact remains absent, and fresh final-code evidence is still
required.

## Superseding formula and retained observations

For each isolated pair, let:

- `T_on` be the enabled non-overlapping named-stage-union seconds;
- `T_off` be the disabled non-overlapping named-stage-union seconds;
- `W_on` be the enabled whole-parser wall seconds; and
- `W_off` be the matching disabled whole-parser wall seconds.

The named table-stage additive-overhead ratio is now
`max(0, T_on - T_off) / W_off`. The harness retains the raw signed
`T_on - T_off` delta, its nonnegative projection, and the normalized ratio in
the explicit field
`paired_nonnegative_table_stage_additive_overhead_ratios`. A non-positive,
boolean, NaN, or infinite `W_off` fails closed.

Each of the three reviewed performance cases still requires exactly five
isolated alternating pairs. Empirical inclusive nearest rank remains the p50
and p95 method. Both quantiles must be at most the unchanged inclusive `0.10`
ceiling; an exact-bound observation passes and a maximum-plus-epsilon
observation fails.

The separate whole-parser ratio remains
`max(0, W_on - W_off) / W_off`, with independent p50 and p95 gates at the same
`0.10` ceiling. It continues to catch work outside the named hooks. Neither
latency gate can substitute for the other.

## Schema and semantic-projection closure

- The retained report advances from `p04-us01-table-metrics-v2` to
  `p04-us01-table-metrics-v3`.
- Its semantic projection advances from
  `p04-us01-final-metrics-semantic-projection-v2` to
  `p04-us01-final-metrics-semantic-projection-v3`.
- The former implicit paired-record shape advances to the closed
  `p04-us01-paired-performance-v2` shape. Each record carries that schema ID,
  the exact formula ID, and the explicit additive-ratio field.
- `p04-us01-quality-evidence-v2`, worker-diagnostic schemas, raw timing fields,
  component topology, limits, and all non-latency evidence schemas remain
  unchanged.

A v2 report, old semantic-projection ID, old paired shape, missing formula ID,
or ambiguous old ratio field cannot validate as v3. No old final artifact is
silently relabelled; no final v2 artifact exists.

## Failed first canonical attempt

The first opt-in canonical generation attempt failed before a retained report
could be written. Its enabled NY observation recorded
`repair_extraction={"call_count":0,"elapsed_seconds":0.0}` while the closed
topology requires that stage to be reachable. The attempt remains failed under
both formulas, and its observations are not an admissible pair.

The two unattached diagnostic snapshots bind the reviewed
`benchmark-expertmodeldata/ny-timetable.pdf` source: 26,109 bytes, three pages,
SHA-256
`f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30`.

| State | Diagnostic identity | Wall seconds | Named-stage seconds | Peak RSS bytes | Semantic JSON SHA-256 |
|---|---|---:|---:|---:|---|
| Off | 48,542 bytes; `7563e06e7edb32f76cadcff0abe4ab19c74374a638370c8629e6a1188dae4196` | `53.358287125` | `0.011959458` | `2605268992` | `a30dfdee212bec5565e40fe03c7eb4a958887bce4093201e204f6c53c5ef4d97` |
| On, invalid reachability | 50,103 bytes; `f9e7cc0422443ae9f2ac0e073ebcb47bf8060724c83fbc3d37787a3f53353cd4` | `66.5584465` | `5.017053458` | `2528886784` | `c00820fe05f5cf18c3d455eeb95a0e02a6ee0389da7b2288a412dff5c967211d` |

For diagnosis only, those observations yield a raw named-stage delta of
`5.005094000` seconds, old ratio `418.5050861000558`, superseding ratio
`0.09380162425894216`, and whole-parser ratio `0.24738723985042102`. None is a
gate result because the enabled observation is invalid.

## Post-fix single-pair diagnostics

After the repair-stage instrumentation target was corrected, one NY enabled
snapshot recorded
`repair_extraction={"call_count":1,"elapsed_seconds":0.001320541}`. The
snapshot is 50,115 bytes with SHA-256
`63dd638d465f65a43b925871b97eb5c9fed1c1dcbc741567d52b6b63831c98af`;
its wall time is `56.811742375` seconds, named-stage time is `5.004541374`
seconds, peak RSS is `2573991936` bytes, and semantic JSON SHA-256 is
`c00820fe05f5cf18c3d455eeb95a0e02a6ee0389da7b2288a412dff5c967211d`.
Reusing the earlier off observation gives a raw delta of `4.992581916`
seconds, old ratio `417.4588778187106`, superseding ratio
`0.09356713239883636`, and whole-parser ratio `0.06472200357387324`.

That NY comparison deliberately reuses a pre-fix off observation. It diagnoses
the formula only; it is not an isolated final-code pair or retained gate
evidence.

The postal diagnostic pair binds
`benchmark-expertmodeldata/postal-10k.pdf`: 83,589 bytes, three pages, SHA-256
`72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`.

| State | Diagnostic identity | Wall seconds | Named-stage seconds | Peak RSS bytes | Semantic JSON SHA-256 |
|---|---|---:|---:|---:|---|
| Off | 48,563 bytes; `9b9b762f60a5729956dacad8a313ebdf1c0aaddd294069fb1349e13396119422` | `21.86425875` | `0.081851042` | `2014674944` | `4bf296a17b758f709348b8824eb55bc32476b71686d4ba3f5c91b6d1e29e09a3` |
| On | 49,450 bytes; `9b2abd4656eb34aed169b031b9dde691dd358bf538d5e26f89c0e8e25d8bc313` | `22.753749958` | `0.926863585` | `2018476032` | `48cd9ed04d8696d0bed4502f21342642e71a47dfcb75598a42d7a48a86060dc6` |

The raw named-stage delta is `0.845012543` seconds, the old ratio is
`10.323784796777542`, the superseding ratio is `0.03864812215506734`, and the
whole-parser ratio is `0.04068243145905868`.

All diagnostic snapshots named above have unattached `worker_diagnostics` and
are single diagnostic observations rather than the required five retained
pairs. They support the denominator diagnosis only. They do not establish a
quality, latency, RSS, output, determinism, or overall metrics pass.

## Instrumentation transaction closure

Hook installation now restores the exact Pydantic validator and every earlier
owner attribute if any later target lookup or installation fails. Restoration
runs in reverse order and fails closed if rollback itself cannot complete. An
adversarial late-target-missing test proves no partial instrumentation survives
an `__enter__` failure. This test-harness correction changes no production
runtime behavior.

## Non-waiver and boundary

- The `0.10` named-stage and whole-parser ceilings, five pairs per case, three
  cases, alternating execution, nearest-rank quantiles, exact component union
  and reachability, raw signed/nonnegative deltas, RSS, output, default-off
  markers, semantic determinism, worker diagnostics, deadlines, resources,
  quality, correctness, security, compatibility, custody, rollback, all-corpus,
  and zero-hosted-use gates remain cumulative and mandatory.
- P03-US08 attempt 48 remains failed at `0.050946750` seconds against the
  unchanged `0.050000000`-second ceiling: `0.000946750` seconds or `1.8935%`
  over, inside but not waived by the unchanged maximum `5%` candidate-specific
  bound. Strict-final evidence remains absent; Phase 03 is not described as a
  strict current-artifact metrics pass.
- The active P03-US08 exception remains default-off, reviewable no later than
  2026-09-02, and expires before production enablement or a relevant
  running-region behavior or custody change. This decision does not amend or
  broaden it.
- No production, configuration, API, serializer, frontend, renewal, story
  status, completion report, terminal evidence, later Phase 04 story, or Phase
  05 content changes here.

## Required verification before any pass claim

The non-opt-in harness must cover exact-bound and maximum-plus-epsilon ratios,
tiny flag-off named-stage time independent of a valid wall denominator,
zero/invalid wall rejection, work outside named hooks, component-union and
reachability closure, hook-install rollback, old-schema/formula rejection, and
raw-sample/summary/semantic-digest tamper rejection. Python compilation and the
full non-opt-in metrics suite must pass.

Completion still requires fresh final-code identities, five isolated pairs for
each reviewed performance case, reviewed real quality documents, all affected
regressions and corpus screens, and independent production/security plus
metrics/custody approval. The first canonical attempt and single-pair
diagnostics above can never be promoted into that evidence.

## Superseded-code custody

These exact pre-edit identities bind the interpretation superseded by this
decision:

| Superseded path | Pre-supersession SHA-256 |
|---|---|
| `tests/fixtures/phase_04/tables/metrics.py` | `a7244985d3a4af5adac8d1ed74edd8acadf97a4e4ce314ea088c2d5a76fff6be` |
| `tests/performance/test_p04_us01_table_metrics.py` | `ecc4a8431a1155552f85d25a0b5bab2768fafb88c9d0960e5df1b3ed1e1859f2` |
| `tracker/phase-04-tables/metrics.md` | `d7bb601bc296082e74087b66c378333467fe24da7f394b157ffef68c51c4b13c` |
| `tracker/phase-04-tables/stories/P04-US01.md` | `9e4f9e5ab4618ec77122833108a1089c74abcf3e897f92dbb630e29f6b520f59` |
| `tracker/phase-04-tables/decisions/P04-table-evidence-policy.md` | `0b4982caf1f9dd9da636460b679a17f82c5092aeb7d148e7f8fa3a3a72c9f187` |

The historical hashes are retained verbatim rather than reconstructed from
the current workspace. Final review must bind both these superseded identities
and the exact final identities; this decision itself becomes a required
final-code policy input.
