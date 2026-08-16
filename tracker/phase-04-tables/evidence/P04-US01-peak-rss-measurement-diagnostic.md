# P04-US01 Peak-RSS Measurement Diagnostic

Status: **DIAGNOSTIC ONLY — not canonical retained metrics evidence**  
Observed: 2026-08-06  
Scope: frozen Optimization C candidate; `ny-timetable` only

## Exact-current addendum

This file preserves failed and noncanonical design observations. It does not
define the current contract. The exact-current pre-retention mechanics are in
the [`external-RSS lane final-code amendment`](../decisions/P04-US01-external-rss-lane-final-code-amendment.md)
and the later
[`conditional stage-reachability amendment`](../decisions/P04-US01-conditional-stage-reachability-final-code-amendment.md):
report/projection/paired/quality `v11`/`v11`/`v10`/`v7`, attestation `v7`,
observer process `v2`, execution accounting `v3`, and full lane protocol `v4`
using timed `select`, bounded generic zlib/base64 custody, fixed-plus-rate active
CPU, bounded PIPE diagnostics, and global three-role process uniqueness.
References below to controller-parent threads, attestation v1, or
busy-deadline state are historical design notes. The exact failed observation
values and hashes below remain unchanged and are not relabelled. The sealed
canonical `v10` attempt 01 separately failed its over-strict conditional-hook
reachability predicate and produced no final artifact. No retained final
artifact or current metrics pass exists.

## Canonical failure

The exact direct-file retained campaign was run once after the Optimization C
renewal refresh and independent review:

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 P04_US01_RUN_REAL_METRICS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false .venv/bin/python tests/fixtures/phase_04/tables/metrics.py --workspace /Users/vignesh/Downloads/taffybop --generate-retained-report
```

It exited `1` with `ValueError: one or more retained measurement gates
failed`. The fail-closed command wrote no
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json`; it is not a
retained metrics pass and is not relabelled here.

## First non-retained corrected smoke and traced diagnosis

The first later `postal-10k` enabled smoke was explicitly non-retained. It
failed closed with no snapshot and no final metrics artifact. Its bounded
stderr was exactly `1,817` bytes over `28` lines with SHA-256
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`, and
the surfaced reason was `child process observed`. That result remains the exact
history of that smoke and is not relabelled.

Later protected traced reproductions observed no child. They failed first with
`first async sample is late`, then with the internal `sampling cadence
exceeded` guard. These traces diagnose cadence independently; they do not erase
or reinterpret the original child observation and produced no canonical
snapshot or retained final artifact.

A direct project-pinned `psutil` `7.2.2` 100-loop timing probe measured
recursive child enumeration at minimum `5598292` ns, p50 `6366604` ns, p95
`6866666` ns, and maximum `8009000` ns. `memory_info()` p50 was `2584` ns.
The old combined cycle—recursive children, RSS, recursive children—measured
minimum `11151375` ns, p50 `12825500` ns, p95 `13876791` ns, and maximum
`15760500` ns. It was therefore structurally impossible for that design to
prove its 10 ms RSS hard maximum even with zero children.

A protected two-thread design probe then separated one recursive child
observation from the RSS-only lane. With a 25 ms child target it recorded child
count `76`, p50 `40004666` ns, p95 `42270750` ns, and maximum `47250166` ns.
With a 2 ms RSS target it recorded RSS count `985`, p50 `2524625` ns, p95
`8793625` ns, and maximum `8842125` ns. These timings support the controlled
two-lane correction only. They are neither canonical retained campaign samples
nor a latency, RSS, correctness, custody, or completion pass.

## Post-renewal real-smoke cadence failure

After the approved two-lane renewal, the standard non-retained `postal-10k`
enabled `fresh_snapshot` smoke exited nonzero. It produced no snapshot and did
not write
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json`. Its bounded
stderr was exactly `2,046` bytes over `33` lines with SHA-256
`d66eb3a2e92523decaf073edf95c5f434f8cfbc1bd88a7f5a11e1121b80ea612`.

A protected reproduction exposed the sanitized lane/category as `current_rss`
`RuntimeError`. The exact private-category diagnostic was
`Phase04-stage RSS sampling cadence exceeded`. This observation remains failed
and non-retained. It neither changes nor relabels the earlier
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`
`child process observed` smoke, the protected `first async sample is late`
trace, the earlier internal cadence trace, or any historical result. None is a
pass.

The accepted response is a no-waiver FIFO/generation handoff correction, not a
new cadence or resource allowance. Every active recursive child scan is FIFO-
serialized and follows `F-C-F`: await a forced continuous-RSS request/
completion generation, perform one scan, then await a second forced generation.
An active logical boundary therefore owns four forced RSS reads around two
scans, an independent child-observer sample owns two, and the pre-`t0` baseline
owns zero. Each generation is captured immediately before the RSS read begins
and is completed only after the sample and timestamp append succeeds. A stale
in-flight read therefore cannot acknowledge a later request.

The cancellation-safe FIFO deque releases its token between a boundary's two
scans, allowing the observer to take its turn. All stop, error, and end paths
notify generation and FIFO waiters; `finish()` uses a FIFO barrier while
committing terminal state; and the lock order is acyclic. The existing
`phase04_stage_rss_sampling_scope` string binds these forced request/completion
handoffs and fails closed if changed.

The accepted implementation identities are metrics fixture SHA-256
`ec2fa9085d5e2d2929f7b32e30d1afc7fb32f2399048ff518b863f6968963c63`
at `332756` bytes and performance test SHA-256
`9d51bb5ca45aa561c8b9bbbbb5aabc1e1f06f9e323dae64d81fa95be25680129`
at `237378` bytes. Recorded verification was `458` passed, `2` expected real
skips, and `1` warning; an independent focused reviewer slice passed `17`; the
full metrics-file run passed `278` with `2` expected real skips and `1` warning;
and the four-test race-stress slice passed five consecutive repetitions. The
narrow correction received independent approval with `0` Blocking and `0`
Major findings. It is not terminal story, metrics/custody, or production
approval.

That historical same-worker generation used report/projection/paired schemas
`v5`/`v5`/`v4` and quality `v2`. The formula IDs remained `v3`, RSS remained
2 ms target/10 ms hard, child observation remained 25 ms target/100 ms hard,
and all ceilings and non-waived gates remained unchanged. No retained artifact
or pass followed from that correction.

## Historical external-controller diagnostic smoke

The then-current, now-historical `v6` correction moved continuous RSS,
recursive-child
observation, FIFO work, and their monotonic timeline into controller-parent
threads bound to the exact fresh-worker PID/create time and private process
group. The worker supplies self-HWM and complete `RUSAGE_CHILDREN` endpoints
over a closed AF_UNIX v1 socketpair. The exact monitor FD is the sole
measurement `pass_fds` descriptor and is made and verified non-inheritable in
the worker. Raw worker attestation must be `null`; only after worker, monitor,
socket, scheduler, and lock cleanup does the parent attach v1 attestation.
The exact parent/worker record match proves round-trip custody, not an
independent duplicate measurement.

The transcript is aggregate-bounded to `65,536` exchanges and `16,777,216`
canonical duplex bytes. Oversized expected operation counts fail before any
count-sized comparison allocation. A failed ABORT is terminal/idempotent; once
FINISH is accepted, failed cleanup can retry close only and never sends ABORT
or FINISH again. The proxy executes only in the worker with zero manual
resource credit: PREPARE identity and START/HWM/rusage setup occur before
`t0` and can affect inherited `B`/`H0`; intermediate boundary IPC and
production-output work occur inside `G`; FINISH-response decode and close are
post-`t1`. Controller observer allocations are outside worker `G` and create
no credit.

That historical report/projection/paired/quality lineage was
`v6`/`v6`/`v5`/`v3`;
both formula IDs, both cadence pairs, every ceiling, and every non-waived gate
remain unchanged. Exact reviewed code identities are metrics fixture
`955383dd2b9ed4b778623fee652b72850a916713614e39f200cbff234c7cf28f` /
`397444` bytes and performance test
`61a83c0b00e96e168eaf34cfd1a00f2f02a2f9bfbc9a701cb71158ff81080393` /
`281525` bytes. Three independent then-current `v6` reviews each reported `0`
Blocking and `0` Major; their overlapping focused non-real slices passed 37
plus 5, 40, and 35 plus 19 checks, with only the known Starlette warning.
The historical `v6` full non-real module separately passed `322`, with `2`
expected real-campaign skips and `1` known Starlette warning.

One real, explicitly non-retained `postal-10k` enabled smoke passed at wall
`24.098229959` seconds, table stage `1.153139165` seconds, RSS maximum gap
`5020584` ns over `1157` samples, child maximum gap `37609250` ns over `99`
samples and `50` boundary checks, `51` successful exchanges, zero stdout/
stderr bytes, exact scheduler restoration, and matching records. Its
`110788608`-byte absolute stage increment is observational only. It is not the
paired enabled-minus-disabled 64 MiB result, no canonical campaign pass is
claimed, and no artifact was retained.

After final cleanup/resource hardening, a historical `v6` second non-retained
repeat passed at wall `23.843067667` seconds, table stage `1.136875792`
seconds, RSS maximum gap `5077708` ns over `1140` continuous samples, child
maximum gap `36056209` ns over `93` samples and `50` boundary checks, `51`
exchanges / `18183` canonical duplex bytes, zero stdout/stderr bytes, exact
scheduler restoration, and matching records. Its `23920640`-byte absolute
stage increment is observational only, not paired RSS evidence or a gate pass;
nothing was retained.

## Separate five-pair diagnostic

A later, explicitly non-canonical wrapper retained each fresh off/on worker in
`/private/tmp/p04-us01-c-paired-diagnostic-b991mrok` and stopped after the five
NY pairs because those pairs independently reproduced the blocker. The
canonical summary bytes have SHA-256
`70c380a9b059588fdb489653e6716d16c102240f17bac37c1dcb61ed4b2defb6`
and size `567994` bytes.

| Pair | Order | Off wall s | On wall s | Off stage s | On stage s | Off peak RSS | On peak RSS | Signed RSS delta |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | off, on | 49.572803625 | 51.383940917 | 0.011151124 | 3.682874875 | 2141028352 | 2026078208 | -114950144 |
| 2 | on, off | 48.219649125 | 51.302761625 | 0.010809916 | 3.658381667 | 2176630784 | 2261237760 | 84606976 |
| 3 | off, on | 47.954125042 | 51.966863167 | 0.010923250 | 3.726519544 | 2220916736 | 2157182976 | -63733760 |
| 4 | on, off | 47.948185291 | 51.440702792 | 0.010748377 | 3.704023458 | 1995735040 | 2236792832 | 241057792 |
| 5 | off, on | 47.856186875 | 51.036103750 | 0.011115206 | 3.708649208 | 2198323200 | 2197110784 | -1212416 |

The exact summary was:

- named-stage p50 `0.07702637875834766` and p95
  `0.0774823081590112`: pass at the unchanged `0.10` ceiling;
- whole-parser p50 `0.066447351589167` and p95
  `0.08367868502418704`: pass at the unchanged `0.10` ceiling; and
- maximum nonnegative absolute process-peak delta `241057792` bytes: fail at
  the unchanged `67108864`-byte ceiling.

Every off worker emitted semantic SHA-256
`a30dfdee212bec5565e40fe03c7eb4a958887bce4093201e204f6c53c5ef4d97`
at `1445246` bytes. Every on worker emitted semantic SHA-256
`c00820fe05f5cf18c3d455eeb95a0e02a6ee0389da7b2288a412dff5c967211d`
at `2521733` bytes.

The ten raw worker identities, in pair/off-on order, were:

| Sample | SHA-256 | Bytes |
|---|---|---:|
| pair-1-off | `7f2f2ba87ae311598146188d5451b95cc95b9f1f940e5e11d9acc74cd213f184` | 49510 |
| pair-1-on | `8b08f435b848c3064616de0af3232733ac19941dd1340d7072a60f14a69d98b5` | 51082 |
| pair-2-off | `f533293e524b8796b8a36aa207733e1692db432e2231ce25f27a3b78aa8f7b6e` | 49507 |
| pair-2-on | `23d46b9fcd6a9e39bc38a33504acd91b9020c2b49ddcd8e5a3524ac0280efaf0` | 51075 |
| pair-3-off | `fce9a9929347a91cdb35cfc68612d6c2ac606ccb43e7b693d4c15d3263d6b78d` | 49503 |
| pair-3-on | `9e9b890e5daf4b0f1be9c4c7e4571870aa53e521ad21463715bbabb1f9d319ad` | 51080 |
| pair-4-off | `63f15cc530f9158a6440d65aaf8a91dbf976f0310fd9518a6f70148443a1c026` | 49509 |
| pair-4-on | `0cc675bdc3ecd3023824af7fb94a7a8938ad46ee080857e6b33232c4593353b6` | 51082 |
| pair-5-off | `cc067009533c9cc5c4f692c435010e31a7dcc7202986f1269fe9afc0f4ac610d` | 49507 |
| pair-5-on | `e7c6db8c8ea8ae8b241faae1144eed043a4a3eb568a37adafd6d40f0b60e6da2` | 51083 |

## High-water attribution probe

One additional isolated enabled NY worker observed current RSS and Darwin
`resource.getrusage(RUSAGE_SELF).ru_maxrss` immediately before and after every
instrumented Phase 04 stage invocation. This was instrumentation-only and is
not a retained metrics sample.

- process-start high-water RSS: `64765952` bytes;
- high-water RSS immediately before the first table-stage invocation:
  `2177286144` bytes;
- high-water RSS after the final instrumented invocation and in the completed
  snapshot: `2177286144` bytes;
- current RSS before the first invocation: `1609187328` bytes;
- current RSS after the completed diagnostic snapshot: `1660289024` bytes;
- named-stage time: `3.640978333` seconds; and
- all `14` measured invocation records had a `0`-byte high-water increment.

The process peak was therefore established by the upstream parse before the
first Phase 04 stage call. The old cross-process subtraction mixed that
unrelated fresh-process high-water variance into the Phase 04 candidate gate.
It does not support raising the ceiling, dropping RSS, or claiming a pass. It
supports a separately reviewed, schema-bumped measurement correction that
retains absolute peaks as observations and applies the unchanged 64 MiB limit
to the paired, per-worker Phase 04 candidate-window growth defined below.

## Controlled supersession disposition

The diagnostic above remains unchanged, failed, and non-canonical. None of its
ten workers contains the schema-bumped candidate-window sampler record, so no
historical value or hash can be relabelled, recomputed into the new formula, or
promoted into retained evidence. In particular, the maximum nonnegative
absolute process-peak delta `241057792` remains a failure under the campaign
that produced it and is not called a pass.

The attribution probe's change from `1609187328` to `1660289024` bytes is
likewise not a historical `C` or `G`: its second observation followed the
completed diagnostic snapshot and no bounded continuous or synchronous-
boundary sampler existed. It diagnoses inherited-HWM masking only.

The Accepted test-only correction is recorded in
[`P04-US01-phase04-stage-peak-rss-controlled-supersession.md`](../decisions/P04-US01-phase04-stage-peak-rss-controlled-supersession.md).
For a fresh worker, `B` is synchronous current RSS immediately before the
earliest P04-owned/first measured outermost hook. Successful parse return
retains a checkpoint `P_parse`/`E_parse`/`H_parse` without stopping the sampler,
with `G_parse=max(max(0,P_parse-B),max(0,H_parse-H0))`. Using the same `B`/`H0`
baseline, a conservative test-only dual-branch composite then invokes the exact
production JSON callables/options and materializes a `JSONResponse`, releases
that body, invokes the exact production Markdown serializer/options and
materializes its `Response`, and ends at `t1_api`. JSON then Markdown is solely
the composite's measurement order. Production selects one response branch per
request, so this does not claim a literal single-request production/API
operation order, ASGI scheduling, or production `run_in_threadpool` scheduling.
Output-complete `P_api`/`E_api`/`H_api` produce
`G_api=max(max(0,P_api-B),max(0,H_api-H0))`; the conservative result is
`G=max(G_parse,G_api)` under
`p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`.

The fresh worker must retain exact JSON/Markdown body sizes and SHA-256 hashes,
media types, production-path identity, JSON structural and Markdown byte
parity, synchronous parse/output boundaries, JSON-body release order, and
distinct before/after digests proving parsed-result and validated-public-
mapping nonmutation. Through `t1_api`, only the one released parsed-result pre-
projection, exact-callable per-branch materialization in that measurement-only
composite, ordered boundary samples, bounded streaming identities, and JSON-
body length/SHA-256 over existing bytes occur; the validated `ParseResult`
remains live through the terminal sample. Allocation-heavy JSON decode/replay,
true parsed-result post projection/comparison, Markdown UTF-8 hash/parity, and final
record validation occur strictly after `t1_api`; jsonable-result identity is not
substituted for parsed-result custody. These requirements do not reinterpret
any diagnostic bytes above.

Project-pinned `psutil` `7.2.2` now has two independent lanes. The RSS lane
performs only bound PID/create-time identity validation plus
`memory_info().rss`; it never enumerates children, targets at most 2 ms, and
enforces a 10 ms hard maximum across its exact start edge, internal cadence,
and end edge. The child
lane makes one recursive `Process.children` observation per cycle, targets 25
ms, and enforces a 100 ms hard maximum across its own edges and cadence. The
complete baseline tuple—including process identity, `B`, `H0`, and cumulative
child-rusage start fingerprint—finishes before recorded `t0`; both first
asynchronous observations must be proven before production is released.

A later 1,000-iteration, non-retained source-cost probe measured cached
`create_time()` at minimum/p50/p95/maximum `42`/`84`/`125`/`500` ns,
`memory_info().rss` at `2541`/`2667`/`2959`/`32959` ns, and the implemented
bound PID/create-time plus RSS path at `2625`/`2709`/`2916`/`5209` ns. It
confirms that exact fast-lane wording and does not establish a canonical pass.

Slow zero-child checks run outside the RSS lock at `t0`, every outermost hook
entry/exit, the parse checkpoint, each exact production-output boundary, and
`t1_api`. The RSS lane never performs child enumeration. Each observer remains
active through `t1_api`, joins boundedly, and retains exact source/version,
first/last offset, target/hard interval, maximum gap, count, readiness,
completion, and error state. Child-specific retained fields additionally bind
its residual and boundary-check count; the primary decision records every
literal field name. Existing `phase04_stage_rss_child_processes_observed`
remains strict zero.

The exact manifest-bound P04-owned `app/` Python final-code path set must pass a
static no-spawn guard; this does not attest the full transitive closure. Fresh-
worker complete cumulative `RUSAGE_CHILDREN` fingerprints—normalized
`ru_maxrss` plus all platform-exposed numeric cumulative fields—must match
exactly before `t0` as part of the complete baseline and at `t1_api`; a nonzero
inherited baseline from predecessor OCR/Tesseract is valid. This supplements
the independent recursive child lane and slow boundary checks. Missing, late,
early, duplicate, malformed, over-gap, observer/join, identity, output parity/
nonmutation, or child-process state fails the worker without a replacement
sample. Parser latency still stops at successful parse return before the RSS
checkpoint. Instrumentation restoration then runs while the observers remain
armed and stays inside `G`. Worker-side in-window work is never subtracted;
controller observer allocations are outside worker `G` and create no credit.

The outer worker is separately contained on supported POSIX platforms through
`subprocess.Popen` with a private session/process group,
`start_new_session=True`, `close_fds=True`, and `stdin=subprocess.DEVNULL`.
A bootstrap barrier binds the exact leader PID/create time and PGID/SID before
releasing the requested
command. Success, nonzero exit, zero exit with a lingering descendant, timeout,
and diagnostic overflow all enter bounded, resumable group TERM-to-KILL
cleanup with deferred cancellation and concurrent pipe draining. No second
signal is allowed after `EPERM` or `ESRCH` uncertainty; a KILL interrupted by
cancellation may be retried once only after the intervening wait continuously
proves the same group without either uncertainty. Completion requires PGID
absence by `ESRCH`, reaping the exact leader, closing selectors, pipes,
bootstrap FDs, and streams, and emitting only sanitized errors.

Required adversarial coverage includes a timeout child, TERM-ignore, overflow
with inherited pipe FDs, nonzero and zero leader exits with lingering same-
group descendants, identity/group mismatch without signalling,
cancellation/resumption and the conditional KILL retry, uncertainty,
reap/closure, and sanitized-error custody. This is same-group containment, not
a claim to clean up an arbitrary detached `setsid`/double-fork descendant or to
eliminate theoretical PGID-reuse TOCTOU. The manifest-bound static no-spawn
guard, independent recursive child observer plus slow boundary checks, and
exact `RUSAGE_CHILDREN` fingerprint equality remain mandatory residual
controls.

For fresh pair `i`, signed `S_i=G_on_i-G_off_i` and nonnegative
`D_i=max(0,S_i)` remain retained. The authoritative gate for each of
`ny-timetable`, `postal-10k`, and `finance-10k` is
`max(D_0,...,D_4) <= 67,108,864` bytes under paired formula
`p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-output-complete-peak-rss-increment-v3`.
Absolute process HWM and cross-worker deltas remain raw observational fields
only. The possible sub-10-ms transient below an inherited HWM is a disclosed
sampling residual; a child born and reaped between observations is a separate disclosed
residual. Synchronous boundaries, self-HWM growth, manifest-bound static
no-spawn, exact child-rusage fingerprint equality, and stress probes mitigate
them.
The worker proxy receives zero manual credit: pre-`t0` identity/HWM/rusage
work can affect inherited `B`/`H0`, intermediate boundary/output work is
inside `G`, and FINISH-response decode/close is post-`t1`. Controller RSS-
sampler, child-observer, FIFO, and child-check allocations are outside worker
`G` and create no credit. None is a waiver or an exact instantaneous-peak
claim.

Two fresh-subprocess 16 MiB controls—one touched allocation sustained through
`t1_api`, one touched then released before it—must show at least 8 MiB sampler
current-RSS/HWM sensitivity while preserving cadence and resource closure. The
managed-sandbox probes use a no-child adapter because psutil enumeration returns
`EPERM`; they do not exercise the recursive child lane. Separate deterministic
tests own child-observer/boundary/fingerprint behavior. The canonical retained
campaign must run outside the managed sandbox with the real independent child
lane and boundary checks, no bypass, and fail closed when observation
permission is unavailable. The probes are non-
real defense-in-depth controls only: they neither reinterpret the failed
history above, replace the canonical three-case-by-five-pair campaign, nor
prove near-bound empirical
behavior. Deterministic arithmetic owns exact 64 MiB and plus-one behavior.

The retained report/projection IDs advance to `p04-us01-table-metrics-v6` and
`p04-us01-final-metrics-semantic-projection-v6`; paired performance advances
to `p04-us01-paired-performance-v5`, and quality evidence to
`p04-us01-quality-evidence-v3`. Older schemas, including the accepted-but-
unretained same-worker report/projection `v5`, paired `v4`, quality `v2`, and
the earlier one-lane report/projection `v4` and paired `v3`, plus the diagnostic
above are rejected as current evidence. The interim `v2` worker and paired RSS formulas
were never finalized, produced no retained evidence, and are rejected rather
than relabelled. P04-US01 remains In Progress, no current real-metrics pass is
claimed, and fresh final-code five-pair evidence plus terminal approval remain
required. One retained-generation attempt ran under the external-controller
`v6` lineage and failed closed before it could identify a case or flag state.
It surfaced only
`RuntimeError: fresh P04-US01 worker category=external_monitor_failure error_type=RuntimeError`,
wrote no final artifact, and has no recoverable exit code, private inner cause,
partial measurements, or completed gate results. Its immutable record is
`P04-US01-retained-metrics-v6-attempt-01-failed.json`, `3,700` bytes, SHA-256
`216802979ba1be4fe153447b72fda480ab3d35fa47e877315f7aa30aff902d35`.
It is failed history only: it is not a completed campaign, current metrics
pass, terminal approval, or completion record, and it cannot be retried and
substituted or relabelled.

Subsequent explicitly noncanonical design diagnostics exposed the following
unchanged-10-ms current-RSS cadence failures; every value remains a failed
candidate observation:

- controller-thread hardening: `26,436,958 ns` after `184` accepted samples;
- first dedicated observer process: `20,713,333 ns` after `615` accepted
  samples;
- QoS plus timed-wakeup observer: `10,489,542 ns` after `487` accepted
  samples;
- QoS plus busy-deadline observer during the full ordinary module:
  `17,014,875 ns` after `460` accepted samples; and
- zero-duration cooperative-yield candidate: `27,992,417 ns` after `299`
  accepted samples.

The cooperative-yield candidate was reverted. The remaining busy-deadline
candidate is rejected as final evidence and is being replaced by a
single-purpose current-RSS process so observer service and child-lane GIL work
cannot mask cadence. No successful retained artifact, completed canonical
campaign, current real-metrics pass, or terminal approval exists. Phase 05
remains outside this diagnostic and decision.
