# P04-US01 Leased-Identity Classified-Cadence Monitor Amendment

Date: 2026-08-07  
Story: P04-US01  
Scope: test-only retained-metrics monitor, failure classification, and evidence
custody; no production-path or production-configuration change  
Status: **PENDING exact-byte independent production/security and
metrics/custody approval; no campaign authority**

## Decision basis

Canonical `v11` attempt 01 is sealed as a genuine fail-closed failure. Its
independent disposition is exactly `11,760` bytes with SHA-256
`baa9797235ecc581e760acd2423dd94a38cb144129e9b556260151d6a82755dc`
at
`tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-independent-review.md`.
That review opened one Blocking finding for canonical performance/resource
evidence and measurement custody and required a genuinely fresh monitor design
before another campaign. It did not establish a production table-correctness
or security regression.

This amendment accepts all three retained current-RSS cadence misses as design
inputs. None is discarded, relabelled, quantiled away, or called an outlier:

| Context | Observed continuous gap | Accepted continuous samples before failure | Disposition |
| --- | ---: | ---: | --- |
| ordinary real-monitor control | `12,069,250 ns` | `32` | fail closed; later isolated and clean-module passes do not erase it |
| v11 precanonical candidate | `32,442,083 ns` | `783` | failed candidate; immutable and never rerun under that design |
| v11 canonical attempt 01, first `ny-timetable` flag-off snapshot | `17,815,500 ns` | `2,009` | failed canonical attempt; no returned snapshot or final artifact |

The contrary evidence remains equally explicit but is not promoted into
canonical evidence: the exact ordinary module later passed `397` tests with
two expected opt-in real-campaign skips, one pressure-candidate deselection,
and one known warning; the v10 pressure candidate passed three fresh real
workers with full then-current cadence/resource custody; and the v10 real
`postal-10k` smoke completed `2,022` continuous samples with a
`1,936,500 ns` maximum gap. These results show non-deterministic recurrence
under the historical monitor. They neither negate a miss nor authorize a
retry.

The fresh design separates two questions without relaxing either one:

1. whether the controller owns one exact, still-live worker identity whose PID
   cannot be recycled while the monitor reads it; and
2. whether the one authoritative current-RSS lane actually meets the unchanged
   cadence through every measured edge.

It does so through an explicit unreaped worker-lifetime lease, an autonomous
RSS-only authoritative lane, a fixed one-shot same-target qualification, and
bounded success/failure telemetry that classifies where time was spent. This
is a new `v12` design. It is not a same-design environmental retry of `v11`.

## Unreaped worker-identity lifetime lease

Each execution retains exactly the existing three fresh role identities:
worker, controller-owned observer, and observer-owned current-RSS lane. The
fixed campaign still contains 36 executions and therefore requires exactly 36
globally distinct identities for each role and exactly 108 globally distinct
identities across all roles. Qualification creates no fourth process, no
second sampler, no alternate target, and no extra campaign identity.

Before the worker command is released, the controller must bind the exact
leader PID/create-time, private process group/session, bootstrap ownership, and
safe/default `SIGCHLD` disposition into a lifetime lease. Lease acquisition
strictly precedes monitor BIND and lane PREPARE. The lease is valid only while
all of the following remain true:

- the exact worker ownership guard is live and unreleased;
- no `poll`, `wait`, `waitpid`, reap, ownership release, or process-group
  cleanup has occurred;
- no code path can transfer or duplicate authority over the target PID;
- the observer and lane remain bound to the exact leased PID/create-time; and
- monitor quiescence occurs before any worker reap, release, or group cleanup.

The record must retain the exact acquisition, command-release, sampling,
quiescence, and lease-release ordering and zero early poll/wait/reap/release/
group-cleanup counts. A non-default or unsafe `SIGCHLD` state, missing lease,
identity mismatch, early reap opportunity, ambiguous ordering, or cleanup
before quiescence fails closed. The lease is not inferred merely from a stored
PID/create-time tuple: it is affirmative custody that the owned worker remains
unreaped for the entire period in which the authoritative lane may read it.

The lease removes repeated PID/create-time discovery from the autonomous
sampling loop without removing identity validation. Exact PID/create-time,
parent, PGID, and SID are validated at lease acquisition and at BIND, PREPARE
begin/end, every synchronous READ, START, PROGRESS, CHECKPOINT, FINISH, ABORT,
and cleanup. Any boundary mismatch fails the execution. Only after both
observer and lane quiescence are proven may the lease be released; lease
release must precede the ordinary owned-process poll/wait/reap and process-
group-absence cleanup path.

## One authoritative autonomous RSS-only lane

There is exactly one authoritative current-RSS lane per worker execution. Once
bound to the leased target, its active loop performs only the governed
same-process current-RSS read and monotonic timestamp/accounting work. It does
not enumerate children, rediscover or reacquire target identity, consult a
second cadence sampler, use controller observations as substitute samples, or
credit qualification observations toward measured output-complete RSS.

The authoritative lane remains responsible for every start edge, internal
continuous sample, synchronous production boundary, parse checkpoint, output
boundary, FINISH edge, and end edge required by the existing measurement
contract. Exact first/last timestamps, counts, peak/end values, monotonicity,
edge coverage, readiness, completion, error state, and full bounded protocol
transcript remain mandatory. The independent recursive-child observer and slow
zero-child boundary checks remain separate residual controls at the unchanged
25 ms target and 100 ms hard gap.

The current-RSS target remains exactly 1 ms and its maximum permitted edge or
continuous gap remains exactly 10 ms. The authoritative measured cadence is
evaluated exactly as a hard maximum. No average, percentile, grace interval,
post-hoc exclusion, qualification result, host-load label, or classified cause
can forgive a measured gap above 10 ms.

## Fixed one-shot same-target qualification

Every worker execution performs exactly one current-RSS qualification against
the same leased worker target and through the same authoritative lane that
will perform the execution's measurements. The duration is fixed at exactly
`3,000,000,000 ns` by the final-code contract and has a separate fixed six-
second operation timeout. Neither value has an environment override. It occurs
after exact lease and monitor binding but before the measurement baseline,
`t0`, START, production command release, latency clocks, peak-RSS window, or
output-complete window.

Qualification is isolated from the measurements: its samples, RSS peak,
start/end edges, elapsed time, CPU accounting, resource state, and telemetry
are retained in a distinct qualification record and cannot enter or offset the
baseline, HWM/current-RSS growth, paired RSS, named-stage latency, whole-parser
latency, deadline, output, or quality records. It is one-shot: it cannot be
restarted, extended, repeated, or replaced after an unfavorable result. It
must be bound to the same target, lane identity, lease, exact 1 ms target, and
10 ms hard gap as the later measurement.

A qualification failure terminates before production command release, retains
its finalized bounded runtime/failure evidence, seals the predeclared attempt
as failed, and permits no same-design retry. A qualification success
establishes only that the lane met the unchanged
cadence during that isolated three-second interval. It is a precondition, not
canonical evidence, and never replaces or weakens authoritative cadence
validation from START through FINISH. A later measured cadence failure still
fails and seals the attempt even when qualification passed.

## Classified bounded cadence telemetry

Both successful qualification/measurement records and cadence failures retain
bounded telemetry sufficient to distinguish scheduler/wakeup delay from the
governed current-RSS sampling-call duration and the complete timestamp-to-
timestamp gap. Each cadence timing record binds the previous accepted
timestamp, intended deadline, wake timestamp, read start/end timestamps,
scheduler delay, sampling-call duration, observed gap, operation context, and
accepted state. Records use a fixed 32-entry ring plus exact bounded maxima;
there is no unbounded history.

The closed classifications are exactly `within_gate`, `scheduler_delay`,
`sampling_call_duration`, and `combined`. The final schema binds finite
nonnegative counts and maxima, the exact failing interval when present, its
operation context, the number of accepted samples before failure, target and
hard limits, lane/target/lease identities, qualification-versus-measurement
phase, and whether the failure occurred before production release. A gap at
exactly 10 ms is accepted and a gap one nanosecond over fails transactionally
without appending a false accepted sample. Success records retain the same
bounded classification families rather than reporting only failures; failure
records retain finalized runtime and do not discard CPU/resource custody.

Classification is explanatory custody, not an alternate result. Every
category is closed and strictly validated; unknown, contradictory, missing,
oversized, non-finite, negative, out-of-order, or internally inconsistent
telemetry fails closed. Raw diagnostic output remains empty and bounded under
the existing PIPE controls. No unbounded event list, stack, environment dump,
process inventory, or sensitive command material may enter the artifact.

The one authoritative lane's accepted sample timestamps remain the sole source
for the measured 10 ms cadence decision. Controller clocks, qualification
telemetry, process-QoS observations, and cause classifications may corroborate
or explain that decision but cannot replace it.

## Schema lineage and approval boundary

The intended embedding lineage is report/projection/paired/quality
`p04-us01-table-metrics-v12`,
`p04-us01-final-metrics-semantic-projection-v12`,
`p04-us01-paired-performance-v11`, and
`p04-us01-quality-evidence-v8`. External monitor attestation advances to
`p04-us01-external-rss-monitor-attestation-v8` and the enclosing observer to
`p04-us01-controller-observer-process-v3`. Execution accounting remains
`p04-us01-execution-accounting-v3` because its exact 36/36/36 and global-108
cardinality does not change; final validation must prove that invariant rather
than treating the retained schema ID as sufficient. The worker lease is
`p04-us01-worker-lifetime-lease-v1`. The current-RSS lane advances together to:

- wire `p04-us01-current-rss-lane-wire-v2`;
- protocol custody `p04-us01-current-rss-lane-protocol-custody-v5`;
- summary `p04-us01-current-rss-lane-summary-v2`;
- runtime `p04-us01-current-rss-lane-runtime-v3`;
- failure `p04-us01-current-rss-lane-failure-v1`;
- capability qualification
  `p04-us01-current-rss-lane-capability-qualification-v1`; and
- cadence timing `p04-us01-current-rss-lane-cadence-timing-v1`.

Runtime v3 retains distinct qualification and measurement CPU/resource gates
plus their combined custody. Each remains subject to the unchanged active-CPU
arithmetic; qualification creates no measurement credit. The combined record
uses exact `qualification_and_measurement_wall_duration_ns`,
`qualification_and_measurement_cpu_duration_ns`,
`qualification_and_measurement_cpu_duty_ppm`, and
`qualification_and_measurement_cpu_maximum_ns` fields.

All earlier report/projection/paired/quality and attestation/observer schemas
are rejected for a current retained `v12` artifact. Every `v6`, `v10`, and
`v11` predeclaration, transcript, failure, diagnostic, and review remains
immutable historical evidence with its original status. No `v12` candidate or
canonical predeclaration may be written or run until:

1. production code remains unchanged and all new test/evidence code, schemas,
   tests, this amendment, and the reconciled live Phase 04 records are frozen;
2. proportionate focused, adversarial, pressure, malformed-protocol,
   compatibility, security, custody, performance, memory, resource, cleanup,
   and prior-phase regressions pass on those exact bytes;
3. the pending independent-review leaf at
   `tracker/phase-04-tables/evidence/P04-US01-leased-identity-classified-cadence-monitor-amendment-independent-review.md`
   is replaced by an exact-identity production/security and metrics/custody
   approval with zero Blocking, Major, correctness, security, custody,
   compatibility, or performance/resource findings; and
4. a separately reviewed immutable one-shot predeclaration binds the complete
   failed-history chain, exact code surface, absent destination/seals, fixed
   qualification, unchanged gates, bounded failure custody, and no overwrite
   or retry path.

Pending design text, implementation, passing unit tests, or qualification by
itself supplies no campaign authority. Any candidate or canonical failure,
including qualification, lease, identity, classification, cadence, cleanup,
or an unrelated gate failure, must be sealed under its predeclaration and must
not be rerun or relabelled under the same design.

## Unchanged gates, rollback, and phase boundary

This amendment changes no production parser path, output, custody behavior,
hosted use, feature default, or rollback. The P04-US01 table feature remains
default off. The three performance cases, five pairs, quality cases, both
nonnegative paired formulas, `0.10` named-stage and whole-parser latency
ceilings, `67,108,864`-byte paired RSS ceiling, 1 ms/10 ms current-RSS cadence,
25 ms/100 ms child cadence, fixed `2,000,000 ns + floor(active_wall_ns *
100,000 / 1,000,000)` lane active-CPU ceiling, output limits, deadlines,
correctness, security, compatibility, custody, resource, deterministic,
diagnostic, corpus, dependency, rollback, offline, and hosted-use gates remain
unchanged and non-waived.

The operative P03-US08 administrative renewal is unchanged. In particular,
its exact attempt-48 observation remains `0.050946750` seconds against the
unchanged `0.050000000`-second ceiling, a `0.000946750`-second / `1.8935%`
overage within the maximum 5% candidate-specific bound. All ceilings,
default-off rollback, non-waived gates, review no later than 2026-09-02, and
expiry before production enablement or any relevant running-region behavior/
custody change remain binding. Canonical P03-US08 strict-final evidence remains
absent, and this amendment does not describe Phase 03 as a strict current-
artifact metrics pass.

P04-US01 remains In Progress with no retained current metrics artifact or
terminal approval. P04-US02, P04-US04, and P04-US03 remain Proposed and must
not start. All Phase 05 stories remain Proposed and unauthorized. This pending
amendment is not P04-US01 completion, production or hosted-use approval, Phase
04 exit, or authority to cross the Phase 04 boundary.
