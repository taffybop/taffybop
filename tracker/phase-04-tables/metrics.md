# Phase 04 Metrics

Release-first note: the metrics below remain useful diagnostics, but detailed
latency/RSS and exhaustive corpus denominators do not block the current
release. Record only representative functional results and any basic bounds
needed to show the supported flow completes safely.

Authority: **mutable, non-authoritative post-run summary**. Executable metric
targets are owned by the final-code Phase 04 fixture and the immutable Accepted
decisions/policy. If this summary diverges, those bound sources control; this
file may record outcomes but cannot create, relax, or reinterpret a gate.

## Current failed state and rejected v13 design

The last approved pre-retention corrections were
[`P04-US01-external-rss-lane-final-code-amendment.md`](decisions/P04-US01-external-rss-lane-final-code-amendment.md)
and
[`P04-US01-conditional-stage-reachability-final-code-amendment.md`](decisions/P04-US01-conditional-stage-reachability-final-code-amendment.md).
Their report/projection/paired/quality `v11`/`v11`/`v10`/`v7` canonical attempt
failed closed on its first flag-off execution after a `17,815,500 ns` gap and
2,009 accepted continuous samples. No snapshot returned and no retained final
artifact exists. The exact 11,760-byte post-failure review has SHA-256
`baa9797235ecc581e760acd2423dd94a38cb144129e9b556260151d6a82755dc`.

The later
[`leased-identity classified-cadence monitor amendment`](decisions/P04-US01-leased-identity-classified-cadence-monitor-amendment.md)
is preserved as an unapproved v12 design. It is controlled-superseded for any
future execution by the pending
[`v13 compact-transport monitor decision`](decisions/P04-US01-v13-compact-transport-monitor-controlled-supersession.md).
V13 uses report/projection/paired/quality `v13`/`v13`/`v12`/`v9`, external
attestation `v9`, observer process `v4`, and unchanged execution accounting
`v3`. It retains one authoritative RSS-only lane and the exact 36 worker / 36
observer / 36 lane / 108 global identity invariant, an explicit unreaped
worker-lifetime lease, and exactly one isolated three-second same-target
qualification. Qualification cannot enter measurements or replace cadence
through START-to-FINISH. Compact START/PROGRESS/CHECKPOINT records are chained
to complete PREPARE/terminal/failure custody without duplicating the full
32-entry ring. Inner-lane exchange/raw/compressed bounds are 4,096 / 8 MiB /
512 KiB. The fixed qualification ladder is 3/6/7/7.5/8/9 seconds, with the
ordinary 2-second operation timeout unchanged. Lane wire/protocol/terminal/
compact/runtime schemas are `v3`/`v6`/`v3`/`v1`/`v4`; failure,
qualification, cadence timing, and ring entry are `v2`/`v2`/`v2`/`v1`.
Worker lifetime lease remains `v1`. The unchanged 1 ms target and 10 ms hard
gap remain fail closed. The initial frozen v13 bundle was independently
rejected on 2026-08-07; its exact disposition is
[`P04-US01-v13-initial-exact-bundle-independent-review-rejected.md`](evidence/P04-US01-v13-initial-exact-bundle-independent-review-rejected.md).
It is non-operative and cannot be repaired in place. Corrective successor work
must be frozen under a new version, independently approved, and bound by a
separately reviewed immutable one-shot predeclaration before any real
execution.

Descriptions below of a “current” `v6` parent-thread, attestation-v1,
65,536-exchange, busy-deadline, `v11`, or reserved `v12` design are preserved
history and are superseded. The sealed `v10` and `v11` attempts are not
retried or relabelled.
No current-artifact metrics pass or retained final artifact exists.

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Exhibit 7 cell text accuracy | 30/30 | 30/30 | — |
| Exhibit 7 location cells | 5 explicit | 5 explicit | — |
| Exact public source-content bbox fidelity | Present but role-untyped | 30/30 exact five-key `pt` bboxes against the hash-bound Exhibit 7 Docling predecessor projection, using the existing `0.011 pt` numeric slack | — |
| Structural grid-slot containment | Phase-00 ruled slots retained | 30/30 public content bboxes wholly contained by their unchanged Phase-00 grid slots; a grid-slot substitution fails content-bbox fidelity | — |
| Cell bbox/provenance coverage | Present but uneven | 100% only on exhaustive exact-cell oracle fixtures, with source/evidence closure; otherwise dimension-specific unresolved concern and exclusion from scoring | — |
| False-span rate | Unmeasured | 0 on negative fixtures | — |
| Legitimate-span accuracy | Unmeasured | 100% on phase fixtures | — |
| Multilevel/rotated header fidelity | Reviewed failures present | 100% on explicitly enumerated reviewed header slots/spans; unavailable ownership remains unresolved | — |
| Multiline logical-row fidelity | Reviewed split/shift risk | 100%; 0 visual-wrap row splits | — |
| Dense timetable grid integrity | 3 pages with silent structural loss | 13 columns and 50 rows per page, or explicit fail-closed concern | — |
| Static form-grid observations | Confirmed ACORD topology loss | Preserve the reviewed region bbox and three visible header observations; retain form-grid/topology/ownership/cell/bbox/provenance concerns and claim no canonical ACORD grid accuracy | — |
| Candidate reconciliation omissions | Unmeasured | 0 unexplained | — |
| False canonical table rate | 1 confirmed chart duplicate plus form ambiguity | 0 on reviewed chart/form/aligned-prose controls | — |
| True borderless/key-value candidate selection | Missing on reviewed component block | 100% on reviewed positives | — |
| False multi-page merge rate | Unmeasured | 0 on negative fixtures | — |
| Cross-representation grid parity | Reviewed expert HTML/rows/CSV/JSON disagreement | 6/6 exact rows/value/cells/scoped HTML/scoped Markdown/CSV representations on exhaustive exact-cell oracle fixtures; unavailable real-fixture truth is excluded, not passed | — |
| Material table failures without targeted concern | Confirmed in dense/form fixtures | 0 on reviewed phase fixtures | — |
| TEDS/GriTS | Not baselined | Record and improve without text regression | — |
| Candidate p50/p95 latency versus LlamaCloud Parse v2 | Initial one-sample-per-case planning reference dated 2026-08-08 | For each applicable case after a ≥5-sample interleaved refresh, candidate p50 ≤ paired Llama p50 and candidate inclusive nearest-rank p95 ≤ paired Llama p95; no corpus-average masking or dropped failures | — |
| P04-US01 output-complete candidate-window peak RSS growth | Paired disabled run; absolute process HWM retained observationally | For each of three cases, `max(D_0,...,D_4) ≤ 67,108,864`, where worker `G=max(G_parse,G_api)`, pair `S=G_on-G_off`, and `D=max(0,S)` | — |
| P04-US01 output ceilings | No marked-table sidecar baseline | ≤ 8,388,608 bytes per marked table and ≤ 67,108,864 Phase 04 sidecar bytes per document | — |
| P04-US01 stage deadlines | No span-fidelity stage | ≤ 0.500 s/page and ≤ 5.000 s/document | — |

## Functional-fidelity observations — 2026-08-13

These are functional evidence only; they do not alter or claim the historical
latency/RSS campaign gates above.

| Metric | Before benchmark fix | After focused rerun |
|---|---:|---:|
| NY timetable source grid | 0/3 pages at 13 columns + 50 service rows | 3/3 pages; each service JSON table is `52x13` including title/header |
| Reviewed NY row shift | p3 omitted `3:32` in competing/baseline structures | exact source row retained with all 13 cells |
| NY semantic rendered tables | 0/3 post-fix baseline candidate pages | 3/3 canonical DOM tables with `colSpan=13` title |
| Reviewed strong unresolved physical-table UI | rendered as paragraph/preformatted content | 9/9 affected pages render semantic candidate-authority tables (clinical 2, ESG 1, finance 3, postal 2, settlement 1) |
| Visual-owned empty health grids in raw Markdown | 1 new blank `10x1` table during geometry rollout | 0; JSON gate evidence retained |
| Focused table backend checks | — | 22 passed after final guard; broader slice 27 passed |
| Focused table frontend checks | — | 50 passed; TypeScript clean |

The full case-by-case source adjudication and immutable artifact hashes are in
`../benchmarks/llamaparse-15/runs/functional-fidelity-20260813/table-source-truth-audit.md`.

The canonical prospective policy is the
[`Phase 04 LlamaParse latency supersession`](decisions/P04-LlamaParse-latency-canonical-supersession.md),
bound to
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md).
It uses LlamaCloud Parse v2, Agentic 10 credits/page, cost optimizer off, cache
disabled, and provider UI **Total Latency**. Its initial 2026-08-08
one-sample-per-case values are planning/reference ceilings only. Before
Definition of Done or phase exit, refresh each applicable case with at least
five interleaved candidate/Llama observations. Candidate p50 and empirical
inclusive nearest-rank p95 must each be no greater than the paired Llama p50
and p95 for that case. Evaluate every case independently: corpus-average
masking and dropped failures are prohibited.

Initial Phase 04 planning observations (all one-shot, not DoD evidence):

| Case | Provider UI Total Latency | LlamaCloud job ID |
|---|---:|---|
| `finance-10k` | 29.4 s | `pjb-415ucx2flb2ild9e0nzdsqnxqr6f` |
| `ny-timetable` | 45.6 s | `pjb-7ljh3v6chmcbpp7qriuwvbbglpat` |
| `postal-10k` | 25.3 s | `pjb-0qtz3dizelo6pu7gv0f4ur8g1bij` |

If the candidate and Llama inputs/outputs are not semantically comparable, the
latency result is **Unmeasured/Blocked**. M0 local-parser timings, flag-off wall
comparisons, and named-stage/component timings remain diagnostic observations
only; they cannot satisfy or replace the Llama latency gate. The earlier
[`P04-US01 table-stage overhead decision`](decisions/P04-US01-table-stage-overhead-controlled-supersession.md)
and its retained formulas remain immutable historical evidence, not the
prospective candidate-latency comparator. No existing schema or historical
artifact is relabelled as a Llama pass.

Latency passes only when unchanged required quality and reliability gates also
pass. Peak RSS, output, marker/default-off, deterministic semantic, deadline,
timeout/fail-closed, diagnostic, correctness, security, custody/hosted-use,
compatibility, rollback, corpus, and resource gates remain independent and
mandatory. The planning supersession does not assert an After value or a
current real-metrics pass; fresh final-code evidence and independent approval
remain required.

The controlled candidate-window RSS contract is documented in
[`P04-US01-phase04-stage-peak-rss-controlled-supersession.md`](decisions/P04-US01-phase04-stage-peak-rss-controlled-supersession.md).
The first non-retained `postal-10k` enabled smoke failed closed, produced no
snapshot or final artifact, and retained bounded stderr identity `1,817` bytes,
`28` lines, SHA-256
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`; its
surfaced `child process observed` reason remains exact history. Later protected
traces observed no child and failed `first async sample is late`, then internal
`sampling cadence exceeded`; they do not relabel the earlier observation.
Measured `psutil` `7.2.2` recursive-child minimum/p50/p95/maximum over 100 loops
was `5598292`/`6366604`/`6866666`/`8009000` ns, `memory_info()` p50 was `2584`
ns, and two child calls plus RSS was
`11151375`/`12825500`/`13876791`/`15760500` ns. That evidence proves the old
combined 10 ms cycle structurally impossible; it is not canonical retained
evidence or a pass.

After the approved two-lane renewal, the standard non-retained `postal-10k`
enabled `fresh_snapshot` smoke exited nonzero with neither a snapshot nor final
artifact. Exact stderr custody is `2,046` bytes / `33` lines / SHA-256
`d66eb3a2e92523decaf073edf95c5f434f8cfbc1bd88a7f5a11e1121b80ea612`.
The protected reproduction exposed `current_rss` `RuntimeError`; the exact
private-category diagnostic is `Phase04-stage RSS sampling cadence exceeded`.
It remains a failed observation and neither relabels the earlier `b13d0b...`
child smoke nor establishes a pass.

The same-worker two-lane/FIFO implementation described below is retained as
failed design history. The later, now-historical `v6` design used
controller-parent RSS and recursive-child threads targeting the exact
fresh-worker PID/create time;
self-HWM and full `RUSAGE_CHILDREN` endpoints are worker-supplied. A closed
AF_UNIX v1 protocol, non-inheritable exact monitor FD, five-second response
bound, cancellation-safe controller cleanup, exclusive controller-only
`0.001`-second scheduler interval, and parent-only v1 attestation bind this
split. The attestation is attached only after exact scheduler restoration and
proves a round-trip record match, not two independent measurements.

The retained duplex transcript is capped at `65,536` exchanges and
`16,777,216` canonical bytes in aggregate; an oversized expected operation
count is rejected before count-sized comparison allocation. Failed ABORT is
terminal and idempotent. After FINISH is accepted, cleanup can retry close but
cannot send ABORT or replay FINISH.

That historical `v6` non-real metrics contract passed `322` with `2` expected
real-campaign skips and `1` known warning. One real non-retained
`postal-10k` enabled smoke passed at wall `24.098229959` s, table stage
`1.153139165` s, RSS gap `5020584` ns / `1157` samples, child gap `37609250`
ns / `99` samples / `50` boundary checks, `51` protocol exchanges, zero
diagnostic bytes, matching record digests, and exact scheduler restoration.
Its `110788608`-byte absolute stage increment is observational only, not the
paired 64 MiB gate. No canonical retained campaign or pass exists.

The historical `v6` post-hardening repeat also passed without retention: wall
`23.843067667` s, table stage `1.136875792` s, RSS gap `5077708` ns / `1140`
continuous samples, child gap `36056209` ns / `93` samples / `50` boundary
checks, `51` exchanges / `18183` duplex bytes, zero diagnostic bytes, exact
scheduler restoration, and matching records. Its `23920640`-byte absolute
stage increment remains observational only and is not paired RSS evidence.

For each worker, current RSS is sampled with project-pinned `psutil` `7.2.2`
from `t0` immediately before the earliest P04-owned/first measured outermost
hook through `t1_api` after a conservative test-only dual-branch composite has
materialized the JSON and Markdown response bodies. At successful parse return,
the still-live sampler retains
`P_parse`, `E_parse`, and normalized self HWM `H_parse`; with start values
`B`/`H0`, `G_parse=max(max(0,P_parse-B),max(0,H_parse-H0))`. The production
callable probe invokes the exact callables/options for `jsonable_encoder`,
second `ParseResult` validation, the exclude-unset JSON dump, and materialized
`JSONResponse`, releases that body, then invokes the production Markdown
serializer and materializes the text/markdown `Response`. JSON then Markdown
is solely a conservative measurement sequence; production selects one branch
per request. The composite does not claim a literal single-request API
operation order, ASGI scheduling, or production `run_in_threadpool` scheduling.
It also retains a distinct true parsed-result pre identity and validated-public-
mapping identities before and after both measured branches. At `t1_api`, the
validated `ParseResult` is still live; it is released only after the terminal
sample. Output-complete `P_api`, `E_api`, and `H_api` produce
`G_api=max(max(0,P_api-B),max(0,H_api-H0))`. Worker growth is
`G=max(G_parse,G_api)` under
`p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`.

Through `t1_api`, only the one released parsed-result pre-projection, exact-
callable per-branch materialization in the measurement-only composite, ordered
synchronous boundaries, bounded streaming identities, and length/SHA-256 over
the existing JSON body occur. The JSON body is released before Markdown
preparation, and both response bodies are not deliberately retained together.
Allocation-heavy
JSON decode/replay, the parsed-result post identity/comparison, Markdown UTF-8
hash/parity, and final record validation occur strictly after `t1_api`. The
final record keeps parsed-result, jsonable-result, validated-public-mapping,
JSON body, and Markdown body identities distinct and proves the parsed result
and public mapping are unchanged. Instrumentation restoration occurs while
both observers are armed between the parse checkpoint and output work; it is
included in `G`, excluded from latency, and never subtracted.

The historical corrected design had two independent observer lanes. In the
later `v6` implementation those same lane algorithms ran in the controller
parent. The RSS lane performed
only bound PID/create-time identity validation plus `memory_info().rss`; it
never enumerates children, targets 2 ms, and fails above a 10 ms maximum across
its start edge, internal cadence, or end edge. A separate 1,000-iteration
diagnostic measured the combined identity-plus-RSS path at minimum/p50/p95/
maximum `2625`/`2709`/`2916`/`5209` ns. The recursive-child lane makes
one observation per cycle, targets 25 ms, and fails above 100 ms across its own
edges and cadence. A protected two-thread diagnostic recorded child count `76`
with p50/p95/maximum `40004666`/`42270750`/`47250166` ns and RSS count `985`
with p50/p95/maximum `2524625`/`8793625`/`8842125` ns; those diagnostics are
not a retained campaign.

The baseline tuple completes before recorded `t0`; both first observations are
proven before production is released. Slow zero-child checks run outside the
RSS lock at `t0`, every outermost hook, the parse checkpoint, every output
boundary, and `t1_api`. Both lanes join boundedly and retain exact source/
version, first/last offsets, target and hard cadence, maximum gap, count,
readiness, completion, and error; the child lane additionally retains its
residual statement and exact boundary-check count. The controlled decision
binds every literal child field name, and
`phase04_stage_rss_child_processes_observed` remains strict zero. Any child or
ambiguous, missing, late, early, invalid, incomplete, mutated, or non-parity
state fails closed.

The accepted no-waiver cadence correction FIFO-serializes every active
recursive child scan. Each scan follows `F-C-F`: await a forced continuous-RSS
request/completion generation, scan once, then await another forced RSS
generation. An active logical boundary therefore causes four forced reads
around two scans, each independent observer sample causes two, and pre-`t0`
causes zero. A generation is captured before its RSS read and completed only
after successful append/timestamp, so an already in-flight read cannot
acknowledge a later request. The cancellation-safe FIFO releases between a
boundary's two scans; stop/error/end paths notify all waiters; `finish()` uses
a FIFO barrier; and the lock order is acyclic. The existing sampling-scope
string binds these handoffs.

Historical same-worker implementation custody is metrics fixture
`ec2fa9085d5e2d2929f7b32e30d1afc7fb32f2399048ff518b863f6968963c63` /
`332756` bytes and performance test
`9d51bb5ca45aa561c8b9bbbbb5aabc1e1f06f9e323dae64d81fa95be25680129` /
`237378` bytes. Recorded verification is `458` passed / `2` expected real skips /
`1` warning; independent focused reviewer `17` passed; full metrics file `278`
passed / `2` expected real skips / `1` warning; and five repetitions of the
four-test race stress passed. Narrow review reported `0` Blocking and `0` Major.
This is not terminal or retained-campaign approval.

The static no-spawn guard is limited to the exact manifest-bound P04-owned
`app/` Python final-code path set, not the full transitive closure. The complete
cumulative `RUSAGE_CHILDREN` fingerprint—normalized `ru_maxrss` plus every
platform-exposed numeric cumulative field—must match exactly before `t0` as
part of the complete baseline tuple and at `t1_api`. Nonzero inherited
predecessor OCR/Tesseract rusage is allowed; the independent recursive child
lane and slow boundary checks remain residual controls. These controls mitigate
the between-observation child residual. For pair
`i`, signed `S_i=G_on_i-G_off_i` and nonnegative `D_i=max(0,S_i)` remain
retained. The exact paired formula is
`p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-output-complete-peak-rss-increment-v3`,
and the maximum of all five `D_i` values must meet the unchanged 64 MiB ceiling
for every reviewed case. Absolute process high-water values and cross-worker
deltas remain observational only; no such historical observation is
reclassified as a pass.

Every outer fresh worker uses `subprocess.Popen` and a private POSIX
session/process group with `start_new_session=True`, `close_fds=True`,
`stdin=subprocess.DEVNULL`, and only bootstrap pipes plus the exact monitor
socket in `pass_fds`; that socket is immediately made and verified
non-inheritable in the worker. A bootstrap barrier binds the exact leader
PID/create time and PGID/SID before
the requested command runs. Success, nonzero or zero exit with lingering
descendants, timeout, and diagnostic overflow all enter bounded group
TERM-to-KILL cleanup. Its resumable state machine defers cancellation, sends no
second signal after `EPERM`/`ESRCH` uncertainty, and permits one KILL retry only
after uninterrupted same-group proof. Completion requires PGID `ESRCH`, exact
leader reap, pipe/selector/bootstrap-FD/stream closure, and sanitized errors.
Required adversarial tests cover timeout descendants, TERM-ignore, inherited-
FD overflow, nonzero/zero lingering descendants, identity mismatch without a
signal, cancellation/resumption and the conditional KILL retry, uncertainty,
reap/closure, and error custody. This contains only descendants remaining in
the private group; arbitrary detached `setsid`/double-fork cleanup and removal
of theoretical PGID-reuse TOCTOU are not claimed. Static no-spawn, the
independent recursive child lane and slow boundary checks, and exact
`RUSAGE_CHILDREN` equality remain mandatory residual controls.

The pending retained report, semantic projection, paired performance, and
quality schemas are `p04-us01-table-metrics-v13`,
`p04-us01-final-metrics-semantic-projection-v13`,
`p04-us01-paired-performance-v12`, and
`p04-us01-quality-evidence-v9`. They have no campaign authority before exact-
byte approval and a separately reviewed immutable predeclaration. Old schemas,
formulas, one-lane child-
bracketed records, endpoint-only measurements, and absolute-HWM gate records
are rejected. The possible sub-10-ms transient below an inherited high-water
mark and a child born/reaped between observations are disclosed residuals
mitigated by synchronous boundaries, within-worker new-HWM growth, manifest-
bound static no-spawn and exact child-rusage fingerprint controls, and stress
probes. The proxy executes only in the worker and receives zero manual
resource credit. PREPARE identity and START/HWM/rusage setup are pre-`t0` and
can affect inherited `B`/`H0`; intermediate boundary IPC and production-output
work are inside `G`; FINISH-response decode and close are post-`t1`.
Controller sampler, child-observer, FIFO, and child-check allocations are
outside worker `G`, create no credit, and are explicitly attested. None is a
waiver or an exact instantaneous-peak claim. The interim `v2` RSS formula IDs
were never finalized or used as retained evidence and are rejected. The
accepted-but-unretained report/projection `v5`, paired `v4`, and quality `v2`
same-worker schemas are rejected, as are the earlier report/projection `v4`
and paired `v3` schemas.

The external-controller correction advances only the embedding schemas; it
changes neither formula ID, 1/10 ms RSS cadence, nor 25/100 ms child cadence.
All ceilings and
non-waived gates remain unchanged.

Required opt-in, noncanonical actual-sampler sensitivity consists of bounded
fresh-worker targets:
one touched 16 MiB
allocation sustained through `t1_api` and one touched 16 MiB allocation released
before `t1_api`; each target is at least 8 MiB observed current-RSS/HWM
sensitivity with cadence and resource closure. Managed-sandbox probes use a
no-child adapter because psutil enumeration returns `EPERM`, so separate
deterministic tests cover the child-observer, boundary checks, and child-
fingerprint behavior. The canonical retained campaign must run outside the
managed sandbox with the real independent child lane and boundary checks, no
adapter/bypass, and must fail closed without observation permission. These are
defense-in-depth controls, not canonical three-case-by-
five-pair evidence or proof of near-bound behavior. Deterministic arithmetic
owns exact 64 MiB equality and maximum-plus-one.
No probe result or near-bound empirical claim is recorded as a pass in this
historical summary. The exact retained final artifact remains absent, canonical
v11 is failed, and the v13 implementation is pending exact approval. The former
Phase Latency scheduling hold was superseded on 2026-08-10 by the release-first
policy; these historical failures remain deferred rather than converted to
passes.

Performance reports must retain the M0 RSS baselines most likely to expose
memory regressions: `ny-timetable` 1,944.0 MiB, `finance-10k` 1,802.7 MiB,
`postal-10k` 1,917.7 MiB, and `insurance-acord` 1,401.1 MiB. Retired local M0
latency values are intentionally omitted from this live plan and cannot serve
as latency ceilings or substitutes for the canonical Llama reference.

“Phase fixture” never expands an unavailable source oracle. Exact cell text,
bbox, provenance, and representation metrics use only fixtures with exhaustive
source-reviewed cell truth. Qualified real cases score only their enumerated
dimensions; every omitted dimension must retain its targeted fail-closed
concern and is excluded from both numerator and denominator.

For Exhibit 7, the original P04/Phase-00 oracle bytes remain structural truth:
their cell `bbox` values are ruled `grid_slot_bbox` rectangles. The separately
versioned `p04-us01-source-content-bbox-oracle-v1` derives all 30 public
`source_content_bbox` values only from the exact hash-verified Phase-03
predecessor and binds the immutable catastrophe PDF, predecessor, and
Phase-00 truth identities. Its semantic SHA-256 is emitted in each exact-table
score and the aggregate quality-oracle metadata. An exact cell passes only
when its public bbox matches that content oracle and is contained by the old
grid slot. Denominators remain 30 exact cells and six representations; no
record is removed or relabelled as an exclusion. HTML/Markdown parity requires
`scope="col"` and `scope="row"` according to retained header ownership.
