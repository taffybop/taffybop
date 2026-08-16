# P04-US01 External-RSS Lane Final-Code Amendment Independent Review

Status: **APPROVED — exact final-code amendment revision only**  
Reviewed: 2026-08-07  
Review role: independent production/security and metrics/custody lane; not the
author of the reviewed amendment revision  
Scope: P04-US01 test/evidence infrastructure only; no production-path behavior
or enablement

## Decision

The exact revision identified below has no remaining Blocking, Major,
correctness, security, custody, compatibility, or performance finding. It is
approved as the independent final-code review required before a future
P04-US01 candidate or canonical metrics campaign may begin under every
otherwise-applicable gate.

This approval is only a campaign precondition. It is not a current-artifact
metrics pass, a retained final metrics artifact, P04-US01 completion, Phase 04
exit, production or hosted-use enablement, or authority for Phase 05.

## Exact reviewed identities

### Final-code amendment inputs

| Path | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | 97,979 | `c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5` |
| `tests/fixtures/phase_04/tables/metrics.py` | 527,588 | `8fb8ef4b05229c587f480d803057ce8963c38ed3558f741fe6fd03e755ab89b6` |
| `tests/performance/test_p04_us01_rss_lane.py` | 31,330 | `5091a9d2db656ef7cedaaec36d31e8d5bf41fef1ea84653e876177b65e6f23ca` |
| `tests/performance/test_p04_us01_table_metrics.py` | 369,578 | `4a34b563b4325c5f8f7b668ec8326ce0a3a7cfbc739025c8cf7920b93ff7ec4d` |
| `tracker/phase-04-tables/decisions/P04-US01-external-rss-lane-final-code-amendment.md` | 7,550 | `d9fec8413ce90be41dd411c9a0ddb6394a7d9a39fd7fba3056e477d509b54739` |

### Reconciled live governance

| Path | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `tracker/phase-04-tables/stories/P04-US01.md` | 25,066 | `ba39a1cfba24a1a3743febdccfdbf86f11affa33df6016758f0baaa7a83c892d` |
| `tracker/phase-04-tables/metrics.md` | 21,805 | `21aa5a7a83edd094acdecac966d4d3e20c921b5b4ef9297de47e1d3fb0ad8c0a` |
| `tracker/phase-04-tables/phase-regression.md` | 18,584 | `4ef481921d6be881cde94d6d6e9806bf211ea20693f01dac2abb18a63aa4b996` |
| `tracker/phase-04-tables/decisions/P04-table-evidence-policy.md` | 40,367 | `9138f01671dbcf5d3bd7948cea4bbeb747306ae86b16745121393d7a1f755d52` |
| `tracker/phase-04-tables/evidence/P04-US01-peak-rss-measurement-diagnostic.md` | 26,018 | `da52c9d1af8e2a09ae0d40dfed5d4670c25e3826cdd374d384738a3f418399dc` |
| `tracker/phase-04-tables/README.md` | 5,655 | `80c6de7c81dd36ce4eb1c9bbb8263a37aadd9d23ea16a1bd56c8cc7ec0596b36` |
| `tracker/phase-04-tables/decisions/P04-US01-phase04-stage-peak-rss-controlled-supersession.md` | 43,841 | `37d2b6215bda7815e06e026152c191d4507118a4b6fbc097f54e27aba1db76e6` |

The older RSS decision now explicitly marks its former `v6`
"current/exact-current" descriptions as historical and defers exact-current
mechanics to the amendment. The live story, metrics, regression, policy,
diagnostic, and README surfaces consistently retain P04-US01 as In Progress,
state that no current-artifact metrics pass exists, and preserve the later
stories and Phase 05 boundary.

### Operative P03-US08 administrative authority

| Path | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md` | 10,226 | `93b95e2d07b4e58a6f8f9a8ae43e587ec199d4fbaaeac4d59c8770702fd32504` |
| `tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json` | 9,722 | `99ac85518d573cb64abd4127444e45d631e767ec8ee236104c389fc420619c41` |
| `tracker/phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md` | 7,297 | `d269fde349c48faf36a050156bb8e95c2541958d601b97b2f6d54436c462828e` |

That exact authority preserves the attempt-48 latency observation, unchanged
ceilings, the maximum 5% candidate-specific bound, default-off rollback, and
every non-waived gate. Its unrelated-Phase-04 distinction does not waive RSS,
paired latency, correctness, security, compatibility, custody, resources,
output, rollback, or hosted-use gates. It remains reviewable no later than
2026-09-02 and expires before production enablement or a relevant
running-region behavior/custody change. Canonical P03-US08 strict-final
evidence remains absent; this review does not describe Phase 03 as a strict
current-artifact metrics pass.

This approval record cannot include its own stable size and digest without a
self-reference. It is an explicit upstream final-code input; a fresh retained
run must calculate and bind this file's then-current exact identity. It is
excluded only from the downstream evidence manifest, together with that
manifest's own path, to keep the custody graph acyclic.

## Independent review results

Static review verified all of the following on the exact bytes above:

- Protocol custody `p04-us01-current-rss-lane-protocol-custody-v4` retains the
  complete canonical transcript and independently bounds exchange count,
  uncompressed and compressed sizes, container depth, and structural tokens
  before JSON materialization. Bounded streaming zlib decoding rejects
  expansion overflow, incomplete streams, unused/trailing data, duplicate
  keys, non-finite numbers, and noncanonical JSON.
- BIND, PREPARE, pre-START READ, START, post-START READ, FINISH, summary,
  runtime, generation, timestamps, and exact target-read accounting are
  structurally and temporally bound. Missing, reordered, forged, malformed,
  ambiguous, truncated, or error-bearing success transcripts fail closed.
- Worker, controller observer, and current-RSS lane PID/create-time identities
  are role-bound and globally unique across the campaign. Lifecycle cleanup,
  descriptor and GC restoration, bounded reap/escalation, diagnostic capture,
  process-group absence, QoS readback, active CPU, and thread-count custody are
  closed and adversarially exercised.
- The schema cascade is internally coordinated at report `v10`, semantic
  projection `v10`, paired performance `v9`, quality evidence `v6`, external
  monitor attestation `v7`, observer process `v2`, execution accounting `v3`,
  lane protocol custody `v4`, lane runtime `v2`, and the corresponding current
  wire, summary, and lifecycle schemas.
- The autouse scheduler fixture applies only to its explicit frozen set of 25
  direct-sampler test names. It resolves parametrized tests through
  `request.node.originalname` with a base-name fallback, leaves every unlisted
  test unchanged, captures the exact prior interpreter switch interval, and
  restores it in `finally` even after failure.
- The production observer scheduler switch interval is 0.25 ms
  (`0.00025` seconds). This is intentionally distinct from, and does not alter,
  the current-RSS sampling target of 1 ms (`1,000,000 ns`) or its unchanged
  10 ms hard maximum gap.
- The independent-review path is explicitly required by final-code discovery
  and exposed as `upstream_approval_evidence_paths` in the measurement policy.
  It is excluded only from downstream evidence discovery. Shrink-resistance,
  final-code/downstream disjointness, manifest self-exclusion, and custody-graph
  acyclicity have explicit tests, including the approval path itself.

## Bound final-code test evidence

These commands were run on the exact code/test identities above outside the
managed restriction with the required macOS process-inspection permission:

| Command | Result |
| --- | --- |
| `.venv/bin/pytest -q tests/performance/test_p04_us01_rss_lane.py` | **23 passed**, 1 known `StarletteDeprecationWarning`, 4.64 s |
| `.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py -k 'not sustained_real_external_monitor_survives_controller_pressure'` | **395 passed**, 2 expected opt-in real-campaign skips, 1 pressure candidate deselected, 1 known `StarletteDeprecationWarning`, 80.83 s |

The ordinary module result is the final run after the deterministic
fixture/scheduler corrections. The two real-campaign skips are not waived and
must be exercised by the later retained campaign. The deselected controller-
pressure candidate is not covered by this approval. The independent reviewer
did not run a candidate, canonical, pressure, or stress campaign.

## Findings and boundaries

| Severity/gate | Open findings |
| --- | ---: |
| Blocking | 0 |
| Major | 0 |
| Correctness | 0 |
| Security | 0 |
| Custody | 0 |
| Compatibility | 0 |
| Performance/resource contract | 0 |

No canonical final metrics artifact exists at
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json`, and no
P04-US01 completion report exists. P04-US01 therefore remains In Progress;
P04-US02, P04-US04, and P04-US03 remain Proposed. All ten Phase 05 stories
remain Proposed and unauthorized.

Any byte change to a reviewed input above invalidates this exact-revision
approval and requires a new independent review. A future candidate or
canonical failure must be sealed and cannot be silently retried under the same
design. Every correctness, security, compatibility, RSS, paired-latency,
resource, output, custody, rollback, corpus, deterministic, diagnostic, and
hosted-use gate remains mandatory and non-waived.
