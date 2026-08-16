# P04-US01 Conditional-Reachability Candidate v11 Attempt 01 Independent Review

Date: 2026-08-07  
Review scope: read-only post-failure custody and gate disposition  
Status: **APPROVED custody; candidate remains FAILED; separately predeclared
canonical progression permitted**

## Decision

The candidate failure is sealed correctly and must remain a failed,
noncanonical, non-retained observation. It must not be rerun under the same
candidate design, relabelled as a pass, discarded, treated as an outlier, or
used as retained or canonical metrics evidence.

The observed current-RSS cadence failure is real: the first `ny-timetable`
flag-off execution observed a `32,442,083 ns` continuous gap against the
unchanged `10,000,000 ns` hard maximum after 783 accepted continuous samples.
The monitor failed closed before returning a snapshot. No flag-on execution
began, so this candidate produced no corrected-topology pass evidence.

On the evidence available for this exact revision, the observation does not
constitute an open Blocking, Major, code-correctness, security, custody, or
performance-design finding. It is consistent with an intermittent host-
scheduling stall in the unchanged external monitor, rather than an identified
regression or root cause in the v11 conditional-reachability correction. That
ambient-cause characterization is an inference from the evidence, not proof.

A materially different, separately predeclared, one-shot canonical v11
campaign may proceed. It must bind this failed candidate as history, preserve
the exact 1 ms target and 10 ms hard current-RSS cadence limits and every other
gate, and fail and seal its own attempt on any recurrence. A canonical cadence
failure may not be removed as an outlier or silently retried under the same
design; it requires fresh independent monitor/environment design review before
further canonical progression.

## Exact sealed candidate evidence

| Artifact | Size | Lines | SHA-256 |
| --- | ---: | ---: | --- |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-predeclaration.md` | 11,616 bytes | n/a | `eb97e4bea052952cb2376ed1b6c07a24e894f5bb94b5f22666381001820b3280` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-stderr.txt` | 1,249 bytes | 24 | `4ab99fdacd99d006425ed836fe00fbe30e9491d070a117182ea66019180a1c05` |
| `tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-failed.json` | 2,647 bytes | n/a | `a66ac11f925b634d11067bd33a7fb9b7a6d436bb12460accc610518900e89c85` |

The failure JSON passes the harness strict bounded JSON loader. Independent
parsing found no duplicate keys or non-finite values. Its bindings agree with
the exact files and terminal transcript:

- schema `p04-us01-conditional-reachability-v11-candidate-failed-attempt-v1`;
- candidate `p04-us01-conditional-reachability-v11-attempt-01`, attempt 1;
- predeclaration size and digest above and inline-source size 7,750 bytes;
- verbatim terminal transcript size, 24-line count, and digest above;
- command exit `1`, zero stdout bytes, and `RuntimeError`;
- failure code `rss_sampling_cadence_exceeded` for `ny-timetable` with the
  table flag off;
- exact `32,442,083 ns` observed gap, `10,000,000 ns` hard gap, and 783
  accepted continuous samples;
- no returned snapshot, no second execution, no current or canonical metrics
  pass, and no same-design retry;
- the exact offline environment and independently approved pre-execution
  predeclaration identity; and
- final metrics absent before and after the failed attempt.

The traceback points to the first sequential `fresh_snapshot` call for the
flag-off state. Because that call raised inside the fail-closed external
monitor path, ordinary Python control flow never reached the following
flag-on call. The failure record's `second_execution_started: false` and
`snapshot_returned: false` therefore agree with both the immutable command and
the verbatim traceback.

At review time, the only downstream artifacts for this candidate were the
predeclaration, stderr transcript, and failed JSON above. No attempt-02 or pass
result existed. The retained final metrics destination remained absent:
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json`.

## Final-code and prior-failure custody

A post-failure read-only recomputation still returned exactly 70 required
final-code files and 5,747,758 bytes, with ordered canonical identity-list
SHA-256
`b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff`.
This exactly matches the pre-execution binding and the failure record. The
starting check necessarily completed before the first worker because the
immutable command performs that check before calling `fresh_snapshot`; the
traceback proves that the worker call was reached.

The sealed v10 attempt-01 history also remains byte-for-byte unchanged:

| Artifact | Size | Lines | SHA-256 |
| --- | ---: | ---: | --- |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-predeclaration.md` | 3,805 bytes | n/a | `817954f24d2de8fd8cf7a5729b6cc7336e97a8c33c1765930848acc52b87ecb7` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-stderr.txt` | 1,491 bytes | 27 | `6601cf62fb95bc02fe8bb63aab953e81834abf866bc0c69d47678ca7fe471bd3` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-failed.json` | 2,085 bytes | n/a | `061497f31d468421305d2a540d33180caa92597e232527c62cc8af3f82cebea0` |
| `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-component-diagnostic.md` | 3,402 bytes | n/a | `de793f8f5e8112b4c674207017ab92237c21adf9794ab524a3cb544de592fb72` |

That v10 attempt remains a failed canonical attempt caused by the superseded
over-strict component-reachability predicate. Its diagnostic remains
diagnostic only. Neither record is changed or converted into pass evidence by
this disposition.

## Gate interpretation and contrary reproducibility evidence

The new candidate failure is a gate failure for this candidate. Approval of
its custody does not approve its metrics outcome. The following evidence is
why the isolated cadence observation does not presently establish a
code/design Blocking, Major, or performance finding:

1. The failure occurred in the flag-off execution, inside the unchanged
   external current-RSS monitor, before a snapshot or enabled conditional-
   reachability topology existed. The v11 correction changes test-only
   component reachability validation, not the monitor scheduler, cadence,
   production parser behavior, or resource thresholds.
2. The same frozen design previously recorded one ordinary fail-closed
   `12,069,250 ns` cadence gap against `10,000,000 ns` after 32 accepted
   samples. With no code, threshold, cadence, or scheduler change, that exact
   control then passed in isolation and the complete ordinary metrics module
   passed 397 tests, with two expected opt-in real-campaign skips, one
   pressure-candidate deselection, and one known warning.
3. The v10 pressure candidate passed three fresh real worker executions under
   controller CPU pressure using the same exact RSS-lane bytes. Its exact test
   result was one pass and one known warning in 9.12 seconds, with full v7/v4
   validation and unchanged cadence/resource gates.
4. The v10 real `postal-10k` smoke, also using the same RSS-lane bytes,
   completed with 2,022 continuous samples and a `1,936,500 ns` maximum gap,
   full v7/v4 custody, empty diagnostics, unchanged child rusage, and no
   observed child process.

These contrary results do not erase either cadence miss. They show that the
miss has not reproduced as a deterministic defect under the reviewed exact
monitor design, including under the dedicated pressure candidate. The strict
10 ms gate performed its intended fail-closed function and remains mandatory.

## Non-waived gates and Phase boundaries

No latency, RSS, cadence, active-CPU, child-observer, output, sidecar, deadline,
correctness, security, compatibility, custody, resource, diagnostics,
determinism, offline/hosted-use, rollback, or final-code identity gate is
waived. No formula, threshold, scheduler setting, schema, or production
configuration changes. The operative P03-US08 exception and all of its
non-waived conditions remain unchanged; canonical P03-US08 strict-final
evidence remains absent, and this review does not describe Phase 03 as a
strict current-artifact metrics pass.

P04-US01 remains In Progress. P04-US02, P04-US04, and P04-US03 remain
Proposed. This review is not a current metrics pass, retained final artifact,
story completion, production or hosted-use approval, Phase 04 exit, or
authority to start another Phase 04 story. All ten Phase 05 stories remain
Proposed and unauthorized; no Phase 05 implementation or transition is
permitted.

The independent reviewer did not rerun a test, worker, snapshot, candidate,
canonical campaign, pressure case, stress case, or metrics command. Review
work was limited to read-only identity, strict-JSON, transcript, manifest,
artifact-absence, status, and prior-evidence inspection. The only edit made by
the reviewer is this new downstream independent-review file.
