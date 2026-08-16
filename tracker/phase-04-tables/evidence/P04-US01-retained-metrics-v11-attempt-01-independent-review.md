# P04-US01 Retained Metrics v11 Attempt 01 Independent Review

Date: 2026-08-07  
Review scope: independent post-failure production/security and metrics/custody
disposition  
Status: **CUSTODY APPROVED — CANONICAL ATTEMPT FAILED; FURTHER CAMPAIGN
PROGRESSION BLOCKED PENDING A GENUINELY FRESH MONITOR/ENVIRONMENT DESIGN
REVIEW**

## Decision

Canonical v11 attempt 01 is a real, correctly fail-closed failure. It is not a
current metrics pass, a partial pass, a candidate result, a retained metrics
artifact, or approval of P04-US01. Its exact command must not be rerun, and its
failure must not be relabelled, discarded, quantiled away, treated as an
outlier, or reused as evidence for a later pass.

The attempt's first `ny-timetable` flag-off snapshot observed a
`17,815,500 ns` continuous current-RSS sampling gap against the unchanged
`10,000,000 ns` hard maximum after 2,009 accepted continuous samples. The
external monitor failed closed before returning the snapshot. No later pair,
case, or quality execution started, no partial measurement was retained, and
no final metrics artifact was created.

This recurrence activates the stop condition in the exact prior independent
candidate disposition. The earlier candidate observed `32,442,083 ns` against
the same 10 ms hard maximum, and the ordinary module previously observed
`12,069,250 ns`. Contrary pressure, smoke, isolated, and clean-module passes
remain valid history, but they no longer authorize another campaign under the
same monitor/environment design after a canonical recurrence.

The open finding is Blocking for canonical performance/resource evidence and
measurement custody. It does not establish a production table-correctness or
security regression: the failure occurred in the unchanged external monitor
during the first flag-off execution, before any returned snapshot or enabled
table-topology evidence existed. The blocker is that the current
monitor/environment design has now failed the immutable cadence gate in both a
precanonical candidate and the canonical campaign, so it cannot presently
supply reliable canonical proof.

No next candidate or canonical campaign may begin until a genuinely fresh
monitor/environment design review is completed, independently approved, and
bound into a new predeclaration. Merely choosing a quieter time, rerunning the
same command, renumbering the attempt, or calling the miss ambient is not a
fresh design review.

## Exact canonical attempt evidence

| Artifact | Size | Lines | SHA-256 |
| --- | ---: | ---: | --- |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-predeclaration.md` | 19,362 bytes | n/a | `0ea5c73722f093fa4265b075571c1be71153ac20bca0253a10891abdd6a6df34` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-stderr.txt` | 2,005 bytes | 39 | `e5f83dd0c3117787dffdbbd7ff4ca71436e6df0f75a36bae7931f4534bbf6b0c` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-failed.json` | 3,795 bytes | n/a | `0eccd48b3f7a9826c5ba3f3bae58c3a1658f70be1f8148430f144bcd39e573bf` |

The failure JSON passes the harness strict bounded JSON loader. Independent
parsing found no duplicate keys or non-finite values. It exactly binds the
predeclaration size, digest, and 8,178-byte inline wrapper; the verbatim
terminal transcript size, line count, and digest; the surfaced exception
message; the failure values; command exit `1`; zero stdout bytes; the fixed
offline environment; and the approved pre-execution review.

The transcript contains the same failure category and exact values recorded in
JSON:

- `failure_code=rss_sampling_cadence_exceeded`;
- `observed_gap_ns=17815500`;
- `hard_gap_ns=10000000`; and
- `accepted_continuous_count=2009`.

The record correctly states that the wrapper called `metrics.main` exactly
once, its post-success checks were not reached, the snapshot was not returned,
the final artifact was absent before and after the attempt, and no current,
terminal, completion, production, hosted-use, or Phase 03 strict-current-
artifact pass was claimed.

## Execution position and cleanup custody

The frozen implementation fixes `PERFORMANCE_CASES` as `ny-timetable`,
`postal-10k`, then `finance-10k`. `paired_states(0)` is `(False, True)`.
`generate_paired_metrics` calls `fresh_snapshot` sequentially for those states
inside pair 0. The traceback reaches the first `fresh_snapshot` and raises
before it returns. Therefore exactly one parser snapshot execution began:
`ny-timetable`, pair 0, flag off. The flag-on state, later pairs, later
performance cases, and all quality executions were unreachable after that
exception.

The fail-closed worker runner quiesces the monitor before worker release,
terminates the owned worker process group in its `finally` path, closes
selectors and diagnostic streams, and then runs the monitor binding's outer
abort cleanup. A cleanup failure would have surfaced as a process-group or
monitor cleanup error instead of the retained cadence error. The failure
record binds a separate post-failure read-only process-list check with zero
matching metrics workers and zero matching RSS-lane processes. This independent
review's later read-only host process-list check also found no matching
survivor. That later observation corroborates, but does not replace, the
failure-time cleanup custody.

## Frozen code, failed-history, and artifact custody

A separate post-failure read-only recomputation still returned exactly 70
required final-code files and 5,747,758 bytes, with ordered canonical
identity-list SHA-256
`b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff`.
The canonical final artifact remains absent at
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json`, and no canonical
v11 attempt-01 success result exists.

The eleven downstream history/disposition/contrary-evidence inputs bound by
the canonical predeclaration remain unchanged:

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v6-attempt-01-failed.json` | 3,700 | `216802979ba1be4fe153447b72fda480ab3d35fa47e877315f7aa30aff902d35` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-predeclaration.md` | 3,805 | `817954f24d2de8fd8cf7a5729b6cc7336e97a8c33c1765930848acc52b87ecb7` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-stderr.txt` | 1,491 | `6601cf62fb95bc02fe8bb63aab953e81834abf866bc0c69d47678ca7fe471bd3` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-failed.json` | 2,085 | `061497f31d468421305d2a540d33180caa92597e232527c62cc8af3f82cebea0` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-component-diagnostic.md` | 3,402 | `de793f8f5e8112b4c674207017ab92237c21adf9794ab524a3cb544de592fb72` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-predeclaration.md` | 11,616 | `eb97e4bea052952cb2376ed1b6c07a24e894f5bb94b5f22666381001820b3280` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-stderr.txt` | 1,249 | `4ab99fdacd99d006425ed836fe00fbe30e9491d070a117182ea66019180a1c05` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-failed.json` | 2,647 | `a66ac11f925b634d11067bd33a7fb9b7a6d436bb12460accc610518900e89c85` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-independent-review.md` | 9,263 | `025c02dd8ce48721b901f56dbb0c0f4596251f4390eb8e337558aab1c9e6023d` |
| `tracker/phase-04-tables/evidence/P04-US01-pressure-candidate-v10-attempt-01-result.md` | 1,247 | `371419e038f7edbf7413e6c0df5837b33d330bb4e5810315744bc2ce231abed5` |
| `tracker/phase-04-tables/evidence/P04-US01-current-v10-real-postal-smoke-result.md` | 2,621 | `c98829dbc1dc32eba013d1b36483802d9c56c4e05616eb6f9739d70cc219bfd6` |

The v6 and v10 canonical failures remain failures. The v10 component record
remains diagnostic only. The v11 two-execution candidate remains failed, and
its prior independent review remains the exact authority whose recurrence
condition now stops progression. The pressure candidate, postal smoke, later
isolated pass, and clean 397-test ordinary run remain contrary evidence only;
none can replace this canonical failure.

## Required fresh-review disposition

Before any later metrics campaign, the implementation lane must produce a
new, reviewable monitor/environment design package that, at minimum:

1. treats all three retained cadence misses (`12,069,250 ns`, `32,442,083 ns`,
   and `17,815,500 ns`) and all contrary passing evidence as inputs rather than
   selecting only a favorable run;
2. investigates whether the recurrence arises from host scheduling, the
   current-RSS lane, observer/controller interaction, process QoS, IPC, target
   reads, or another bounded resource path, with diagnostics designed before
   any new candidate;
3. preserves the 1 ms target and 10 ms hard maximum gap, 25 ms/100 ms child
   cadence, fixed-plus-rate active-CPU formula, latency/RSS/output limits, and
   every correctness, security, compatibility, custody, resource, diagnostic,
   offline/hosted-use, and rollback gate;
4. does not disguise a threshold, cadence, formula, scheduler, sampling-scope,
   process-ownership, or custody change as an environmental retry;
5. obtains proportionate adversarial and pressure validation and a new
   independent exact-byte production/security and metrics/custody approval;
6. predeclares any genuinely new candidate or canonical attempt with exact
   start/end code and complete failed-history custody, fixed one-shot seals,
   and no overwrite or same-design retry path; and
7. leaves every existing failed artifact immutable and explicitly downstream
   of the new design.

This review does not prescribe a particular implementation change and does not
authorize weakening the gate. If investigation cannot establish a genuinely
new reviewable design, P04-US01 remains blocked at the canonical metrics gate.

## Findings and boundaries

| Finding class | Open findings |
| --- | ---: |
| Canonical performance/resource evidence | **1 Blocking** |
| Production table correctness | 0 established by this failure |
| Security | 0 |
| Failure custody | 0 after sealing |
| Compatibility | 0 |
| Phase boundary | 0 |

All formulas, limits, thresholds, schemas, output controls, default-off
rollback, and non-waived gates remain unchanged. The operative P03-US08
administrative renewal remains unchanged, including attempt 48, all ceilings,
the maximum 5% candidate-specific bound, default-off rollback, every non-waived
gate, review no later than 2026-09-02, and expiry before production enablement
or a relevant running-region behavior/custody change. Canonical P03-US08
strict-final evidence remains absent; this review does not describe Phase 03
as a strict current-artifact metrics pass.

P04-US01 remains In Progress and has no current retained metrics pass or
terminal metrics/custody approval. P04-US02, P04-US04, and P04-US03 remain
Proposed and must not start. This review is not story completion, production
or hosted-use approval, Phase 04 exit, or authority to cross the Phase 04
boundary. All ten Phase 05 stories remain Proposed and unauthorized.

The independent reviewer did not run or rerun a worker, snapshot, candidate,
canonical campaign, pressure case, stress case, metrics command, or test.
Review activity was limited to read-only artifact/hash, strict-JSON,
source-control-flow, final-code/history, final-artifact/status, and host
process-list inspection. The only edit made by the reviewer is this new
downstream independent-review file.
