# P04-US01 v13 Compact-Transport Monitor Controlled Supersession

Date: 2026-08-07  
Story: P04-US01  
Scope: test-only retained-metrics monitor, bounded transport, failure custody,
and schema lineage; no production parser or production configuration change  
Status: **PENDING exact-byte independent production/security and
metrics/custody approval; no real-execution or campaign authority**

## Decision and historical boundary

This decision is a fresh, controlled supersession for any future P04-US01
retained-metrics execution. It does not edit, relabel, approve, or erase the
pending `v12` leased-identity design, either accidental execution record, or
any `v6`, `v10`, or `v11` evidence. The `v12` schema reservations were never
approved for a candidate or canonical campaign and are rejected for a current
artifact rather than renamed.

Canonical `v11` attempt 01 remains a genuine fail-closed result. Its first
`ny-timetable` flag-off execution observed a `17,815,500 ns` current-RSS gap
after `2,009` accepted continuous samples. It returned no snapshot, started no
later execution, and wrote no final artifact. Its independent disposition is
exactly `11,760` bytes with SHA-256
`baa9797235ecc581e760acd2423dd94a38cb144129e9b556260151d6a82755dc`.
Earlier observed gaps of `12,069,250 ns` after `32` accepted samples and
`32,442,083 ns` after `783` accepted samples remain failures too. Passing
historical controls do not negate any miss.

The later implementation diagnostics and accidental real activity are
retained separately. They are neither warm-ups nor retries and provide no
current pass, candidate, canonical, production, hosted-use, story-completion,
or phase-exit authority. In particular, an accidentally reached qualification
failed `rss_qualification_cadence_exceeded` after `332` accepted samples and
also observed CPU above the unchanged active-CPU allowance. Production START,
measurement, and worker-command release did not occur. The chronological
record is
[`P04-US01-v13-preapproval-accidental-real-execution-history.md`](../evidence/P04-US01-v13-preapproval-accidental-real-execution-history.md).

The design change is limited to test/evidence mechanics needed to make the
same unchanged gates observable through a bounded protocol. It changes no
table truth, production table code, feature default, production execution
path, API, serializer, frontend contract, running-region behavior, or custody.

## Invariants retained from the leased-identity design

Every execution still owns exactly three fresh identities: worker,
controller-owned observer, and observer-owned current-RSS lane. The fixed
campaign remains 36 executions and requires exactly 36 globally distinct
identities of each role and 108 globally distinct identities overall.
Qualification creates no fourth role or alternate sampler.

Before worker command release, the controller must acquire an affirmative
unreaped lifetime lease over the exact PID, create time, parent, PGID, SID,
bootstrap ownership, and safe/default `SIGCHLD` state. Lease acquisition
precedes observer BIND and lane PREPARE. No poll, wait, waitpid, reap,
ownership release, or group cleanup may occur while sampling can still target
that identity. Both sampling lanes must be proven quiescent before lease
release; lease release must precede ordinary owned-process cleanup. Missing or
ambiguous identity, unsafe `SIGCHLD`, early-release opportunity, unproven
quiescence, or ordering drift fails closed.

There is exactly one authoritative current-RSS lane. Its active loop performs
only lease-bound same-process current RSS reads and monotonic cadence
accounting. It never enumerates children, reacquires another target, credits a
controller observation, or uses qualification samples in the measurement.
The independent recursive-child observer remains a separate residual control.

Every execution performs exactly one isolated qualification against the same
leased target and through the same lane before baseline, `t0`, START, worker
command release, latency clocks, RSS windows, or output work. Qualification is
fixed at `3,000,000,000 ns`; it cannot be restarted, extended, repeated, or
replaced. A qualification pass is only a precondition. It does not enter a
measurement formula or replace cadence validation from START through FINISH.
A failure terminates before production release and seals the predeclared
attempt with no same-design retry.

The current-RSS target remains exactly `1,000,000 ns` and its hard maximum gap
remains exactly `10,000,000 ns`. The recursive-child target remains
`25,000,000 ns` with a `100,000,000 ns` hard maximum. A current-RSS gap at
exactly 10 ms is accepted; one nanosecond above fails transactionally without
crediting a false accepted sample. No percentile, average, grace interval,
cause classification, environment label, or qualification result can forgive
an edge or continuous gap above the applicable hard limit.

## Bounded compact transport

The authoritative lane uses canonical AF_UNIX frames no larger than `65,536`
bytes. One execution permits at most `4,096` request/response exchanges,
`8,388,608` raw canonical duplex bytes, and `524,288` compressed transcript
bytes. Canonical transcript nesting is capped at 32 and structural tokens at
`524,288`. Capacity is preflighted before response transmission and reserves
space for one terminal exchange. Overflow, malformed canonical JSON,
duplicate keys, non-finite values, decompression excess, depth/token excess,
sequence drift, premature EOF, or inability to retain the terminal exchange
fails closed.

`READ` returns only its exact RSS value, observation timestamp, and lease
commitment. START, PROGRESS, and CHECKPOINT return a versioned compact summary,
not the full 32-entry cadence ring. Each compact record binds the accepted
sample count, first/latest timestamps, peak/end values, exact maxima, cadence
chain, ring count/hash/predecessor/maxima commitments, latest operation
context, lease identity, and the preceding compact commitment. A new compact
record must chain to the exact previous transmitted compact record; later
terminal or failure evidence must bind the last compact anchor.

The complete bounded cadence ring and maximum witnesses appear only where
their full custody is required: the PREPARE qualification attempt, a terminal
FINISH summary, or a failure. They are not duplicated on START, PROGRESS, or
CHECKPOINT. FINISH retains the full terminal summary plus runtime record.
ABORT and every error are terminal and leave no ambiguous continuation state.
Protocol custody retains the compressed canonical transcript, exact raw and
compressed sizes and digests, all exchange counts and operation ordering, and
recomputable closed bounds.

These inner-lane limits are distinct from the enclosing external-monitor
protocol, whose pre-existing maximum remains 65,536 exchanges and 16,777,216
canonical duplex bytes. Neither layer may borrow unused capacity or substitute
its transcript for the other layer's custody.

## Qualification deadlines and fail-closed finalization

All PREPARE timing values are fixed final-code constants with no environment
override:

| Boundary | Limit |
| --- | ---: |
| Qualification target window | `3,000,000,000 ns` |
| Lane service attempt deadline | `6.0 s` |
| Failure-finalizer deadline from dispatch | `7.0 s` |
| Response-ready deadline from dispatch | `7.5 s` |
| Lane client absolute response deadline | `8.0 s` |
| Enclosing observer PREPARE relay deadline | `9.0 s` |
| Ordinary non-PREPARE lane operation timeout | unchanged `2.0 s` |

The service-owned monotonic watchdog covers the qualification work. The same
dispatch-anchored guard then bounds exact attempt materialization, failure
classification, runtime restoration, response construction, and response
readiness. The client has the outer 8-second absolute deadline, and the
observer relay has a final 9-second bound so each inner failure can be
delivered without an unbounded wait. Timeout, signal-mask/timer drift,
watchdog cleanup failure, response-construction failure, response
transmission failure, or a missing finalized runtime record fails closed with
sanitized bounded custody.

The ordinary 2-second operation limit is unchanged and cannot be promoted to
the PREPARE ladder or vice versa. Bound and prepared idle reads remain owner-
custodied blocking states; they cannot execute production work and terminate
only through closed protocol or owner cleanup.

## Failure evidence without silent loss or duplication

Cadence timing retains the closed classifications `within_gate`,
`scheduler_delay`, `sampling_call_duration`, and `combined`. Every accepted
entry commits previous timestamp, intended deadline, wake, read start/end,
scheduler delay, read duration, observed gap, phase, operation context, lease,
and chain predecessor. A fixed 32-entry ring plus exact chain/predecessor and
maximum-witness commitments bounds history.

A qualification attempt—pass or fail—retains the complete applicable cadence
ring once. If qualification fails, the enclosing failure embeds that exact
attempt once and retains only a bounded outer projection: cause precedence,
all observed failure codes, scalar counts and maxima, exact attempt/ring hashes,
ring predecessor and maximum commitments, last compact anchor, runtime, and
lease/worker identities. Its outer cadence ring and witnesses are explicitly
empty; the exact hashes must bind the embedded attempt. Any duplication,
omission, mismatch, contradictory cause, unknown code, negative/non-finite
number, impossible count, broken chain, or changed predecessor fails closed.

The runtime record embeds only
`p04-us01-current-rss-lane-qualification-runtime-commitment-v1`: qualification
status/cause, exact wall/CPU/resource scalars, lease identity, and the
qualification SHA-256. It must not duplicate the qualification ring. Separate
qualification, measurement-active, and combined resource arithmetic remains
mandatory. Qualification creates no measurement credit.

Raw diagnostic streams remain empty for a successful canonical execution and
bounded on failure. Evidence cannot include unbounded histories, stack traces,
source text, document bytes, paths, commands, environment dumps, credentials,
process inventories, or unsanitized exceptions.

## Schema lineage

Any future current retained artifact must use exactly:

- report `p04-us01-table-metrics-v13`;
- semantic projection `p04-us01-final-metrics-semantic-projection-v13`;
- paired performance `p04-us01-paired-performance-v12`;
- quality evidence `p04-us01-quality-evidence-v9`;
- external monitor attestation
  `p04-us01-external-rss-monitor-attestation-v9`;
- controller observer `p04-us01-controller-observer-process-v4`;
- execution accounting `p04-us01-execution-accounting-v3`;
- lane wire `p04-us01-current-rss-lane-wire-v3`;
- lane protocol custody `p04-us01-current-rss-lane-protocol-custody-v6`;
- lane terminal summary `p04-us01-current-rss-lane-summary-v3`;
- lane compact summary `p04-us01-current-rss-lane-compact-summary-v1`;
- lane runtime `p04-us01-current-rss-lane-runtime-v4`;
- lane failure `p04-us01-current-rss-lane-failure-v2`;
- lane qualification
  `p04-us01-current-rss-lane-capability-qualification-v2`;
- lane qualification-runtime commitment
  `p04-us01-current-rss-lane-qualification-runtime-commitment-v1`;
- cadence timing `p04-us01-current-rss-lane-cadence-timing-v2`;
- cadence ring entry `p04-us01-current-rss-lane-cadence-ring-entry-v1`;
- worker lifetime lease `p04-us01-worker-lifetime-lease-v1`; and
- unchanged lane lifecycle `p04-us01-current-rss-lane-lifecycle-v1`.

All earlier or reserved report, projection, paired, quality, attestation,
observer, wire, protocol, summary, compact, runtime, failure, qualification,
cadence, ring, lease, or execution schema combinations are rejected for a
current artifact. Historical evidence retains its original identifiers.

## Unchanged gates

The fixed campaign still contains three performance cases and five independent
flag-off/flag-on pairs per case. Both nonnegative additive named-stage and
whole-parser latency ratios retain the unchanged inclusive `0.10` p50 and p95
ceilings. The exact paired RSS formula remains
`p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-output-complete-peak-rss-increment-v3`,
with an unchanged inclusive `67,108,864`-byte maximum. The worker formula
remains `p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`.

The fixed-plus-rate active CPU maximum remains `2,000,000 ns +
floor(active_wall_ns * 100,000 / 1,000,000)`. Qualification, measurement, and
combined arithmetic are each independently mandatory. All named-stage,
whole-parser, paired RSS, cadence, child, output, deadline, correctness,
quality, determinism, malformed-input, security, compatibility, custody,
memory, resource, dependency, diagnostic, cleanup, rollback, offline, and
hosted-use gates remain unchanged and non-waived.

The P04-US01 feature remains default off. Disabling it restores the exact
predecessor behavior. No production or hosted use is approved.

## P03-US08 administrative boundary

The operative P03-US08 administrative continuity renewal remains unchanged.
Its exact attempt-48 observation is `0.050946750` seconds against the unchanged
`0.050000000`-second ceiling: `0.000946750` seconds / `1.8935%` over, within
the maximum 5% candidate-specific bound. The renewal distinguishes only
unrelated, default-off Phase 04 table changes from protected running-region
semantic/runtime/custody changes. It waives no RSS, paired or source latency,
correctness, security, compatibility, custody, resource, output, rollback, or
hosted-use gate. It remains reviewable no later than 2026-09-02 and expires
before production enablement or any relevant running-region behavior/custody
change. Canonical P03-US08 strict-final evidence remains absent; Phase 03 is
not described as a strict current-artifact metrics pass.

## Approval and one-shot boundary

No real candidate, control, qualification, PREPARE, reviewed-corpus campaign,
or canonical execution is authorized until all of the following hold on one
exact frozen byte set:

1. production code remains unchanged from its independent approval and every
   test/evidence source, schema, marker, decision, and live Phase 04 record is
   reconciled and hash-bound;
2. focused, adversarial, malformed-protocol, compatibility, security, custody,
   performance, memory, resource, timeout, cleanup, prior-phase, and default-
   off regressions pass without entering an opt-in real path;
3. an independent reviewer approves the exact implementation, tests, this
   decision, reconciled governance, failure history, and unchanged gates with
   zero Blocking, Major, correctness, security, custody, compatibility, or
   performance/resource findings; and
4. a separately reviewed immutable one-shot predeclaration binds the complete
   failed-history chain, exact source identities, exact command and environment,
   absent destination and seals, fixed execution order, all gates, bounded
   failure custody, and no overwrite or retry path.

Any candidate or canonical failure—including qualification, lease, identity,
cadence, CPU, transport, transcript, finalization, output, cleanup, or any
other non-waived gate—must be sealed under that predeclaration and must not be
rerun or relabelled under the same design. Passing deterministic tests or an
independent design approval alone supplies no execution authority.

P04-US01 remains In Progress with no retained current metrics artifact or
terminal approval. P04-US02, P04-US04, and P04-US03 remain Proposed. Every
Phase 05 story remains Proposed and unauthorized.
