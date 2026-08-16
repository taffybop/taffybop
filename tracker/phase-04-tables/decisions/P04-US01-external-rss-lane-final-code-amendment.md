# P04-US01 External-RSS Lane Final-Code Amendment

Date: 2026-08-07  
Story: P04-US01  
Scope: test-only retained-metrics infrastructure; no production-path change  
Status: Accepted only with a separate independent approval bound to these exact bytes

## Decision

This amendment supersedes only the current external-RSS implementation and
custody descriptions in the earlier P04-US01 RSS supersession and Phase 04
evidence policy. It does not rewrite or relabel any historical result. In
particular, the sealed external-controller `v6` attempt remains failed, its
artifact remains immutable, and no canonical current-artifact metrics pass or
retained final metrics artifact exists.

The metric formulas, three performance cases, five pairs, quality cases,
`67,108,864`-byte paired RSS ceiling, `0.10` latency ceilings, 1 ms current-RSS
target, 10 ms hard current-RSS gap, 25 ms child target, 100 ms hard child gap,
output limits, deadlines, correctness, security, compatibility, custody,
resource, rollback, corpus, deterministic, diagnostic, and hosted-use gates
are unchanged and non-waived.

The final-code lineage is:

- report `p04-us01-table-metrics-v10`;
- semantic projection `p04-us01-final-metrics-semantic-projection-v10`;
- paired performance `p04-us01-paired-performance-v9`;
- quality evidence `p04-us01-quality-evidence-v6`;
- external monitor attestation
  `p04-us01-external-rss-monitor-attestation-v7`;
- external observer process `p04-us01-controller-observer-process-v2`;
- execution accounting `p04-us01-execution-accounting-v3`;
- current-RSS lane wire `p04-us01-current-rss-lane-wire-v1`;
- current-RSS lane protocol custody
  `p04-us01-current-rss-lane-protocol-custody-v4`;
- current-RSS lane summary `p04-us01-current-rss-lane-summary-v1`;
- current-RSS lane runtime `p04-us01-current-rss-lane-runtime-v2`; and
- current-RSS lane lifecycle `p04-us01-current-rss-lane-lifecycle-v1`.

Every earlier embedding schema is rejected for a current retained artifact; it
is not reinterpreted under these mechanics.

## Process and timing custody

Every retained execution uses three fresh, bound PID/create-time identities:
the worker, a controller-owned observer process, and the observer-owned
single-thread current-RSS lane. Role-specific and global uniqueness are
mandatory across the entire campaign. The fixed campaign has 36 executions,
so execution accounting requires exactly 108 globally distinct role
identities. Reuse across roles or executions fails closed.

The lane uses project-pinned `psutil` `7.2.2` and only exact target identity
validation plus `memory_info().rss`. During the active window it uses timed
`select` wakeups; it does not busy-spin. It retains exact start, continuous,
synchronous, and end-edge evidence and keeps the unchanged 1 ms target and
10 ms hard maximum gap. Its exact target-read count is one PREPARE read plus
continuous samples plus synchronous samples.

Runtime v2 retains lifetime wall/CPU observations and a separately bound active
START-to-FINISH window. Active CPU must be no greater than
`2,000,000 ns + floor(active_wall_ns * 100,000 / 1,000,000)`. The fixed term
covers bounded startup/terminal work; the steady-state term is 10% of active
wall time. Exact-bound and one-unit-over tests remain mandatory. Thread count
must remain one, file-descriptor count and cyclic GC state must restore exactly,
and the requested lane QoS must be applied and read back exactly before the
dedicated process terminates. Each target read must remain within the unchanged
hard gap, and all resource fields are validated against the terminal summary.

Bound and prepared service states may block while legitimately idle. They do
not apply the two-second lane or five-second observer IPC round-trip bound as a
shorter document-load lifetime. Controller/client round trips and every
response transmission remain individually bounded; EOF, worker deadline, and
owned cleanup terminate idle services. Real delayed controls must prove that
PREPARE can remain idle beyond both round-trip constants without losing exact
cleanup or attestation.

## Protocol and resource bounds

The worker-facing external-monitor protocol and current-RSS lane wire retain a
64 KiB per-frame maximum. The observer's controller-only internal transport
uses a separate 1 MiB per-frame maximum so it can carry the bounded full lane
custody record; this does not relax the worker-facing cap.

Protocol custody v4 retains the full canonical request/response transcript,
not only commitments. It applies all of these independent bounds before
materialization:

- at most 4,096 exchanges;
- at most 8 MiB canonical uncompressed duplex JSON;
- at most 512 KiB compressed zlib bytes;
- at most 32 JSON container levels; and
- at most 512 Ki structural tokens.

The transcript is one complete zlib stream encoded as strict canonical base64.
The record retains compressed and uncompressed sizes and SHA-256 identities,
plus the operation list and digest. Validation uses bounded streaming
decompression, requires stream EOF, rejects unused/trailing/unconsumed input,
rejects oversized expansion, and then requires strict canonical JSON with no
duplicate keys or non-finite numbers. The accepted zlib stream is not required
to byte-match a new compression performed by a possibly different system zlib
build; its retained compressed hash still provides exact artifact custody.
Before `json.loads`, a string/escape-aware scanner rejects excess top-level
exchanges, nesting, and structural tokens so a compact adversarial transcript
cannot create an unbounded Python object graph.

Operation-specific validation binds BIND parent/worker/lane identity, PREPARE
target-read accounting, the subsequent pre-START READ to the START baseline,
generation and summary progression, post-START READ time coverage, and FINISH
summary/runtime. The enclosing attestation separately binds lifecycle after
the lane has quiesced. Any
missing, reordered, forged, malformed, truncated, ambiguous, or error-bearing
success transcript fails closed.

Observer and lane subprocess diagnostics use OS pipes. Kernel pipe
backpressure bounds a non-reading producer; streams are read only after the
process is reaped, retained reads are capped, nonempty or incomplete capture
fails, secrets are sanitized, and both streams must close. Timeout, repeated
wait error, malformed frame, EOF, diagnostic flood, nonzero exit, lingering
descendant, TERM-ignore/KILL, cancellation, and cleanup retry paths must retain
bounded reap, process-group absence, descriptor closure, and sanitized error
custody.

## Administrative and rollback custody

The final-code manifest must include the exact operative P03-US08
administrative renewal decision, its closed machine-readable classifier, and
its independent approval leaf, in addition to the older preserved chain. This
binds the authorization that distinguishes unrelated Phase 04 table changes
without changing attempt-48, any ceiling, the maximum 5% candidate-specific
bound, default-off rollback, or any non-waived gate.

This amendment changes only test/evidence infrastructure. Production table
behavior remains controlled by the existing default-off Phase 04 flag and its
rollback tests. No candidate or canonical campaign may run until these exact
bytes and the final code receive independent Blocking/Major review. A failed
candidate or canonical run must be sealed and cannot be silently retried under
the same design. This amendment authorizes neither production enablement,
Phase 04 exit, nor any Phase 05 work.
