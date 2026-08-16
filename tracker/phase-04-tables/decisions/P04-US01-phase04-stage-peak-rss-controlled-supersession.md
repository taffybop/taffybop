# P04-US01 Phase04-Stage Peak-RSS Controlled Supersession

Status: Accepted as a test-only measurement contract; fresh evidence and terminal approval pending  
Date: 2026-08-06  
Scope: P04-US01 metrics, tests, and documentation only  
Retained-report schema: `p04-us01-table-metrics-v6`  
Semantic-projection schema: `p04-us01-final-metrics-semantic-projection-v6`  
Paired-performance schema: `p04-us01-paired-performance-v5`  
Quality-evidence schema: `p04-us01-quality-evidence-v3`  
Worker formula ID: `p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`  
Paired formula ID: `p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-output-complete-peak-rss-increment-v3`

Supersession notice (2026-08-07): the implementation and embedding-schema
mechanics in this record are preserved historical `v6` design custody. The
exact-current pre-retention contract is
[`P04-US01-external-rss-lane-final-code-amendment.md`](P04-US01-external-rss-lane-final-code-amendment.md),
subject to exact-byte independent approval. Every use of “current” or
“exact-current” below is scoped to the historical `v6` generation and cannot
support a current-artifact pass.

## Trigger and classification

### Current external-controller closure

This 2026-08-06 revision supersedes the same-worker ownership statements in
the earlier sections of this record while preserving their measurements and
failed status as history. The unchanged `v3` formulas still measure the exact
fresh worker. Continuous current RSS, the candidate timeline, recursive-child
observations, FIFO child scans, and `F-C-F` request-completion handoffs are now
owned by controller-parent threads bound to the exact fresh-worker PID,
psutil create time, PPID, private PGID, and SID. The worker supplies only its
normalized self-HWM and exact `RUSAGE_CHILDREN` endpoint fingerprints through
a closed, sequenced AF_UNIX socketpair protocol.

The inherited monitor descriptor is the sole `pass_fds` exception to
`close_fds=True`; worker bootstrap immediately makes it non-inheritable,
verifies AF_UNIX/SOCK_STREAM, and the CLI worker refuses to run without it.
Controller responses use the same five-second operation bound as worker
requests. Monitor cleanup defers `KeyboardInterrupt` and `SystemExit` until
sampler threads are stopped, both endpoints are closed, the controller's
exclusive `0.001`-second switch interval is restored exactly, and its lock is
released. A non-reading peer, malformed/truncated frame, identity drift,
sequence/state error, timeout, cancellation, or cleanup uncertainty fails the
sample without replacement.

Every final snapshot receives a parent-only
`p04-us01-external-rss-monitor-attestation-v1` after worker completion and
controller cleanup. It binds controller identity, exact worker-group
ownership, the compact operation sequence and recomputable duplex transcript
SHA-256, original/effective/restored scheduler values, exact sources/scopes,
worker resource-payload SHA-256, and the exact round-trip match between the
controller-returned RSS record and the worker-retained projection. That match
is custody evidence, not a claim of two independent measurements. Raw worker
output must carry `external_rss_monitor_attestation: null`; any worker-supplied
attestation or missing final parent attachment fails closed.

The transcript admits at most `65,536` exchanges and `16,777,216` aggregate
canonical duplex bytes in addition to the per-frame cap. Expected operation
counts above that exchange ceiling fail before any count-sized comparison is
allocated. ABORT is terminal even when its request fails. Once FINISH is
accepted, a failed close can retry close only—never send a semantically invalid
ABORT—and subsequent cleanup is idempotent.

Controller sampler and recursive-observer allocations are outside worker
`G`, create no resource credit, and are never described as worker RSS. The
proxy executes only in the worker and receives zero manual resource credit.
Its PREPARE identity and START/HWM/rusage setup occur before `t0` and can
affect inherited `B`/`H0`; intermediate boundary IPC and production-output
work occur inside `G`; FINISH-response decode and socket close occur after
`t1`. This ownership change advances
report/projection/paired/quality schemas from the accepted-but-unretained
`v5`/`v5`/`v4`/`v2` generation to `v6`/`v6`/`v5`/`v3`; both RSS formula IDs,
the 2 ms/10 ms RSS cadence, the 25 ms/100 ms child cadence, and every ceiling
remain unchanged.

The final exact-current external-controller non-real gate passed `322` tests
with `2` expected real-campaign skips and `1` known Starlette deprecation
warning. The earlier pre-final `311`/`2`/`1` run remains historical rather
than being relabelled. A real,
non-retained `postal-10k` enabled smoke then passed with wall
`24.098229959` seconds, table stage `1.153139165` seconds, RSS maximum gap
`5020584` ns over `1157` continuous samples, child maximum gap `37609250` ns
over `99` samples and `50` boundary checks, `51` successful protocol
exchanges, zero stdout/stderr bytes, exact scheduler restoration, and matching
records. Its `110788608`-byte absolute worker-stage increment is observational
only: it is neither the paired enabled-minus-disabled 64 MiB result nor a gate
pass. Earlier external smokes that failed closed—including managed-sandbox
`sysctl` child-enumeration permission failures—retained no artifact and are
not replaced or relabelled. No canonical `v6` campaign has run.

After final cleanup/resource hardening, an exact-current second non-retained
`postal-10k` enabled smoke passed with wall `23.843067667` seconds, table stage
`1.136875792` seconds, RSS maximum gap `5077708` ns over `1140` continuous
samples, child maximum gap `36056209` ns over `93` samples and `50` boundary
checks, `51` exchanges / `18183` canonical duplex bytes, zero stdout/stderr
bytes, exact scheduler restoration, and matching records. Its `23920640`-byte
absolute worker-stage increment is likewise observational only, not paired RSS
evidence or a gate pass; nothing was retained.

The first Optimization C canonical retained campaign failed closed and wrote no
final metrics artifact. A separate five-pair NY diagnostic reproduced the
blocker: named-stage p95 `0.0774823081590112` and whole-parser p95
`0.08367868502418704` were within the unchanged `0.10` ceilings, but the
maximum nonnegative enabled-minus-disabled absolute process high-water delta
was `241057792` bytes against the unchanged `67108864`-byte ceiling.

The attribution probe then showed that upstream parsing had established the
enabled worker's `2177286144`-byte lifetime high-water mark before the first
Phase 04 hook. All `14` measured Phase 04 invocations had a `0`-byte lifetime
high-water increment even though current RSS changed from `1609187328` bytes
before the first invocation to `1660289024` bytes in the completed diagnostic
snapshot. Cross-worker subtraction of absolute lifetime high-water marks
therefore mixed unrelated upstream fresh-process variance into the
candidate-specific Phase 04 resource gate. Conversely, using only lifetime
high-water endpoints would mask candidate-window growth below an inherited
high-water mark.

That diagnostic current-RSS difference is attribution evidence only. Its end
sample was taken after the completed diagnostic snapshot, and it had neither
the bounded continuous window nor the boundary samples defined below, so it is
not a historical `C` or `G` observation and cannot be used as a new-formula
pass.

The first later, non-retained `postal-10k` enabled smoke under the initial
continuous-sampler implementation also failed closed and produced neither a
snapshot nor a final metrics artifact. Its bounded stderr was exactly `1,817`
bytes over `28` lines with SHA-256
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`;
the surfaced reason was `child process observed`. That observation remains
exact failed history and is not relabelled. Later protected traced
reproductions observed no child and instead failed first with `first async
sample is late` and then with the internal `sampling cadence exceeded` guard.
Those later reproductions diagnose a different mechanism; they neither erase
nor reinterpret the original child observation.

Direct, 100-iteration `psutil` `7.2.2` measurements showed why the initial
single-loop design could not meet its own 10 ms limit. Recursive child
enumeration took minimum `5598292` ns, p50 `6366604` ns, p95 `6866666` ns, and
maximum `8009000` ns; `memory_info()` had p50 `2584` ns; and two recursive
child enumerations plus one RSS read took minimum `11151375` ns, p50
`12825500` ns, p95 `13876791` ns, and maximum `15760500` ns. The old loop was
therefore structurally incapable of proving a 10 ms RSS cadence even when no
child existed. A protected two-thread probe with a 25 ms child-observer target
then recorded `76` child observations with p50 `40004666` ns, p95 `42270750`
ns, and maximum `47250166` ns, while the independent 2 ms RSS lane recorded
`985` observations with p50 `2524625` ns, p95 `8793625` ns, and maximum
`8842125` ns. These are design diagnostics only, not canonical retained
campaign evidence or a resource-gate pass.

After the approved two-lane renewal, the standard non-retained `postal-10k`
enabled `fresh_snapshot` smoke also failed closed. It exited nonzero and wrote
neither a snapshot nor the final metrics artifact. Its bounded stderr was
exactly `2,046` bytes over `33` lines with SHA-256
`d66eb3a2e92523decaf073edf95c5f434f8cfbc1bd88a7f5a11e1121b80ea612`.
A protected reproduction exposed a `current_rss` `RuntimeError`; the exact
private-category diagnostic was `Phase04-stage RSS sampling cadence exceeded`.
This is a new failed observation. It does not relabel the earlier
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`
child-observation smoke, any prior cadence trace, or any result as a pass.

This record supersedes only that test-only RSS interpretation. It changes no
production code, parser behavior, feature setting, configuration default,
resource ceiling, package use in production, or story status. It is not a
waiver, a retrospective pass, a retained metrics artifact, a terminal
approval, or completion evidence. P04-US01 remains In Progress, the canonical
final metrics artifact remains absent, and the failed campaign remains failed.

The earlier
`p04-us01-worker-max-current-growth-and-new-hwm-growth-v2` worker wording and
`p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-stage-peak-rss-increment-v2`
paired wording were an interim, never-finalized documentation state. No
retained worker, campaign, approval, or pass used either ID. They are rejected
as current evidence rather than relabelled; the output-complete `v3` IDs above
are the only accepted formulas.

## Candidate window and exact worker formula

The independent RSS sampler and child observer are instantiated and ready
before parser wall timing begins. The baseline tuple—process identity, current
RSS `B`, self-HWM `H0`, and cumulative `RUSAGE_CHILDREN` start fingerprint—is
completed before the recorded `t0`; no partial baseline operation is included
after the window start. Both first asynchronous observations are proven before
any measured production operation is released. The measurement is armed
exactly once at `t0`, immediately before the earliest P04-owned, first measured
outermost hook executes. The same baseline and two observers remain active
through successful `parse_document` return, an explicit parse checkpoint
`t_parse`, and the conservative test-only dual-branch response-materialization
composite described below. The candidate window ends only at `t1_api`, after
the composite's Markdown `Response` body is materialized and the validated
public mapping's post-output streaming identity is taken.
Instrumentation restoration occurs after `t_parse` while both observers remain
armed, before output materialization; its overhead is therefore conservatively
inside `G`. Allocation-heavy output parity/replay and parsed-result post-check
serialization, quality scoring, and retained-report construction remain
outside the window; the bounded identities named below remain inside it.

Parser latency is separate from this RSS window. Whole-parser wall timing ends
immediately when `parse_document` returns, before the parse RSS checkpoint or
any output probe. Named-stage latency remains the non-overlapping in-parser
hook union. JSON/Markdown probe time must never enter either latency formula.

Every outermost measured named-hook entry and exit receives a synchronous RSS
sample and a slow zero-child boundary check outside the RSS sampler lock;
nested hooks do not create a second candidate window. The same two boundary
operations occur at `t0`, the parse checkpoint, each ordered production-output/
identity boundary defined below, and `t1_api`. The RSS lane never performs
child enumeration and never stops or restarts during instrumentation
restoration or between boundaries. The child-observer lane independently makes
one recursive observation per cycle rather than bracketing an RSS read with two
recursive calls.

The closed formula uses these byte-valued observations:

- `B` is current RSS read synchronously as part of the baseline tuple completed
  immediately before recorded `t0`, from
  `psutil.Process(exact_worker_pid_create_time).memory_info().rss` in the
  controller parent.
- `E_parse` is current RSS read synchronously at `t_parse`, immediately after
  successful parse return. `P_parse` is the maximum of `B`, `E_parse`, every
  asynchronous sample through that checkpoint, and every synchronous named-
  hook boundary sample through that checkpoint.
- `H_parse` is normalized `resource.getrusage(RUSAGE_SELF).ru_maxrss` at the
  parse checkpoint. `C_parse=max(0,P_parse-B)`,
  `Q_parse=max(0,H_parse-H0)`, and `G_parse=max(C_parse,Q_parse)`.
- `E_api` is current RSS read synchronously at `t1_api`. `P_api` is the maximum
  of `B`, `E_api`, every asynchronous sample, and every synchronous named-hook,
  parse-checkpoint, and output-path boundary sample inside inclusive
  `[t0,t1_api]`.
- `H0` and `H_api` are normalized
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` values sampled as part of the
  completed pre-`t0` baseline tuple and at `t1_api`. Darwin values are bytes;
  Linux values are KiB multiplied by
  `1024`; any other platform fails this retained harness closed.
- `C_api=max(0,P_api-B)`, `Q_api=max(0,H_api-H0)`, and
  `G_api=max(C_api,Q_api)`.
- `G=max(G_parse,G_api)` is the authoritative conservative per-worker growth
  under worker formula
  `p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`.

The current-RSS terms prevent an inherited high-water mark from hiding
sustained or sampled growth below that waterline. The HWM terms independently
catch a new process high-water mark, including one between current-RSS samples.
No endpoint alone may replace `G`, and neither a negative value nor a decrease
is allowed to create resource credit. `G_parse` remains independently retained
even though the output-complete observation is cumulative from the same
baseline; any incoherence or decrease across checkpoints fails closed.

## Conservative test-only dual-branch output-materialization composite

After the parse checkpoint and instrument restoration, both observers remain
armed while the measurement first takes the true parsed-result pre-identity from
`result.model_dump(mode="json", exclude_unset=False)`, hashes that projection
with the bounded streaming canonical encoder, and releases the projection. It
then invokes the exact production callables and options for each response
branch: `jsonable_encoder(result)`, `ParseResult.model_validate(...)`,
`model_dump(mode="json", exclude_unset=True)`, and a materialized
`JSONResponse(content=...)` body for JSON; and the production Markdown
serializer over the validated public mapping plus a materialized text/markdown
`Response` body for Markdown. The test-only composite deliberately measures
the JSON branch first, releases that response and body, and then measures the
Markdown branch. Production selects one response branch per request. The
composite therefore does not reproduce or claim a literal single-request
production/API operation order, ASGI scheduling, or the production
`run_in_threadpool` scheduling of the Markdown branch. It conservatively
exercises exact production callables, options, and per-branch materialization
within one measurement window solely for RSS evidence.

The validated public mapping gets a bounded streaming identity immediately
after its dump and again after both measured branches, before `t1_api`, proving
that the composite did not mutate it. The validated `ParseResult` object
remains live through `t1_api` and is released only after the terminal sample,
conservatively keeping its retained memory inside `G`. The JSON branch
completes and its body is released before the Markdown branch begins, so the
composite does not retain both response bodies simultaneously.

The exact ordered synchronous boundary names are
`source_result_identity_pre`, `source_result_identity_post`,
`source_result_identity_release_post`, `jsonable_encoder_pre`,
`jsonable_encoder_post`, `jsonable_streaming_identity_post`,
`parse_result_validate_post`, `public_result_dump_post`,
`public_result_streaming_identity_post`, `json_response_pre`,
`json_response_body_post`, `json_response_streaming_identity_post`,
`json_response_release_post`, `markdown_serializer_pre`,
`markdown_serializer_post`, `markdown_response_pre`,
`markdown_response_body_post`, and
`public_result_after_streaming_identity_post`. Missing, reordered, duplicated,
or unbalanced boundaries fail closed. `t1_api` follows the last boundary
immediately.

Only the one released parsed-result pre-projection, exact-callable per-branch
materialization in the measurement-only composite, those boundary samples,
bounded streaming identities, and SHA-256/length reads over the already-
materialized JSON body occur before `t1_api`. JSON decoding, response replay,
parsed-result
post projection/identity, Markdown UTF-8 encoding/hash comparison, and other
allocation-heavy parity/nonmutation diagnostics run strictly after `t1_api`.
The final output-probe record retains distinct parsed-result before/after,
jsonable-result, validated-public-mapping before/after, JSON response body, and
Markdown/response-body size/hash fields; both nonmutation booleans, JSON
structural parity, Markdown byte parity, media types, release order, exact
schema/path, and exact boundary tuple are validated. Parsed-result custody is
not inferred from the jsonable-result identity. The probe must use the same
production encoder, validator, dump options, serializer, and response classes
as `app/api.py`; a shortcut or conflated identity fails review.

The exact `p04-us01-production-output-probe-v1` fields are `schema_id`,
`production_output_path`, `output_boundary_names`, `output_boundary_count`,
`source_result_before_size_bytes`, `source_result_before_sha256`,
`source_result_after_size_bytes`, `source_result_after_sha256`,
`source_result_unchanged`, `jsonable_result_size_bytes`,
`jsonable_result_sha256`, `public_result_size_bytes`, `public_result_sha256`,
`public_result_after_size_bytes`, `public_result_after_sha256`,
`public_result_unchanged`, `json_response_body_size_bytes`,
`json_response_body_sha256`, `json_response_decodes_to_public_result`,
`json_response_media_type`, `json_response_released_before_markdown`,
`markdown_utf8_size_bytes`, `markdown_utf8_sha256`,
`markdown_response_body_size_bytes`, `markdown_response_body_sha256`,
`markdown_response_matches_utf8`, and `markdown_response_media_type`. Missing
or additional fields fail closed.

The measurement boundary must continue to prove that no flag-dependent Phase
04 production parse allocation, or allocation made by the exact production
callables/options used for either measured response branch, occurs before `t0`
or after `t1_api`. The explicitly separated post-`t1_api` diagnostics and the
JSON-then-Markdown sequencing are test-only evidence mechanics, not a claim
about one production response flow. A new or relocated P04-owned production
allocation outside the closed window invalidates this formula and fails review;
it is not silently excluded.

## Two-lane sampling cadence, identity, and fail-closed rules

The current-RSS source is project-pinned `psutil` `7.2.2`. The RSS lane performs
only bound PID/create-time identity validation and `memory_info().rss`; it
performs no recursive child enumeration, targets an interval no greater than
`2,000,000` ns (2 ms), and requires a maximum
observed gap no greater than `10,000,000` ns (10 ms). Its exact edge proof spans
recorded `t0` to the first asynchronous RSS observation, consecutive RSS
observations, and the last RSS observation to `t1_api`. The synchronous RSS
reads at `t0`, parse checkpoint, `t1_api`, named-hook, and output-path
boundaries are additive safeguards, not substitutes for the continuous RSS
lane.

A separate, non-retained 1,000-iteration source-cost diagnostic measured cached
`create_time()` identity validation at minimum/p50/p95/maximum
`42`/`84`/`125`/`500` ns, `memory_info().rss` at
`2541`/`2667`/`2959`/`32959` ns, and the combined bound PID/create-time plus
RSS path at `2625`/`2709`/`2916`/`5209` ns. This confirms the implemented fast
lane rather than changing either cadence bound or establishing a metrics pass.

The child-observer lane independently calls project-pinned `psutil` `7.2.2`
`Process.children(recursive=True)` exactly once per observation. It targets
`25,000,000` ns (25 ms) and requires a maximum observed gap no greater than
`100,000,000` ns (100 ms), with its own start edge, internal cadence, end edge,
count, readiness, completion, and error validation. It must complete its first
zero-child observation before measured production work is released. Slow
zero-child checks also run at `t0`, every outermost hook entry/exit, the parse
checkpoint, every output boundary, and `t1_api`; they run outside the RSS lane's
lock and cannot delay or replace an RSS observation. The baseline tuple is
fully complete before recorded `t0`, so neither observer can misstate a
partially constructed start boundary.

The accepted no-waiver correction serializes every active recursive child scan
through a cancellation-safe FIFO deque. Each active scan uses exact `F-C-F`
protocol: request and await completion of a forced continuous-RSS generation,
perform exactly one recursive child scan, then request and await completion of
a second forced continuous-RSS generation. Therefore each active logical
boundary owns two serialized child scans and four forced RSS handoffs, each
independent child-observer sample owns one scan and two forced RSS handoffs,
and the pre-`t0` baseline owns zero handoffs. The deque token is released after
the first boundary scan before the direct synchronous RSS read and is reacquired
for the second scan, preventing the boundary from starving the independent
observer.

The continuous lane captures the current request generation immediately before
each RSS read begins and advances the completed generation only after that read
has been successfully appended with its timestamp. An RSS read already in
flight when a later request is issued cannot acknowledge that later generation.
Every stop, observer/sampler error, and end transition notifies both progress
and FIFO waiters. `finish()` acquires a FIFO barrier before committing terminal
state. The lock order is acyclic: FIFO turn, then child-scan serialization,
then request/completion progress; no path waits for FIFO or a child scan while
holding the sampler state/progress lock.

The retained `phase04_stage_rss_sampling_scope` value binds these handoffs
exactly as
`controller_parent_threads_targeting_exact_fresh_worker_pid_and_create_time_from_first_measured_phase04_table_stage_pre_entry_through_production_json_and_markdown_output_completion_with_independent_continuous_current_rss_and_live_recursive_child_observers_with_forced_request_completion_generation_handoffs_around_every_active_fifo_serialized_recursive_child_scan_plus_worker_acknowledged_synchronous_bracketed_path_boundary_samples_and_worker_supplied_hwm_rusage`.
Changing or omitting that scope string fails closed.

The controller attaches and final validation recomputes the existing RSS
source/version, PID/process
create time, platform, exact window/component, timestamps/duration,
`phase04_stage_rss_first_async_offset_ns`,
`phase04_stage_rss_last_async_offset_ns`,
`phase04_stage_rss_sampling_target_interval_ns`,
`phase04_stage_rss_continuous_maximum_gap_ns`,
`phase04_stage_rss_sampling_hard_maximum_gap_ns`, RSS sample counts,
readiness/completion/error, and all formula observations. It separately retains
and validates exact child fields
`phase04_stage_child_observer_source`,
`phase04_stage_child_observer_source_version`,
`phase04_stage_child_observer_target_interval_ns`,
`phase04_stage_child_observer_hard_maximum_gap_ns`,
`phase04_stage_child_observer_first_offset_ns`,
`phase04_stage_child_observer_last_offset_ns`,
`phase04_stage_child_observer_continuous_maximum_gap_ns`,
`phase04_stage_child_observer_sample_count`,
`phase04_stage_child_boundary_check_count`,
`phase04_stage_child_observer_ready`,
`phase04_stage_child_observer_completed`,
`phase04_stage_child_observer_error`, and
`phase04_stage_child_observer_residual`. Existing
`phase04_stage_rss_child_processes_observed` remains a strict zero field. Both
controller observer threads join within bounded intervals before attestation.

The sample fails with no replacement observation on either observer's
exception, thread-start/readiness/join failure, late first observation, early
stop, absent/duplicate start or finish, missing `t0`/`t_parse`/`t1_api`,
invalid/non-finite/negative value, incoherent identity/timestamp/count, either
lane's edge or cadence violation, nonzero child observation or boundary check,
output identity/parity/nonmutation failure, or any descendant-scope ambiguity.
Only the exact fresh worker is measured; child aggregation is forbidden.

The superseded same-worker FIFO/generation correction was bound to exact code
identities:
`tests/fixtures/phase_04/tables/metrics.py` SHA-256
`ec2fa9085d5e2d2929f7b32e30d1afc7fb32f2399048ff518b863f6968963c63`
at `332756` bytes, and
`tests/performance/test_p04_us01_table_metrics.py` SHA-256
`9d51bb5ca45aa561c8b9bbbbb5aabc1e1f06f9e323dae64d81fa95be25680129`
at `237378` bytes. That historical correction changed no schema or formula:
report/projection/paired then remained `v5`/`v5`/`v4`, worker and paired formula IDs
remain `v3`, RSS cadence remains 2 ms target/10 ms hard, child cadence remains
25 ms target/100 ms hard, and every latency, RSS, output, correctness, security,
compatibility, custody, resource, rollback, and hosted-use ceiling remains
unchanged.

Recorded historical verification for those exact code identities is `458` passed, `2`
expected real-corpus skips, and `1` warning; an independent focused reviewer
slice passed `17`; the full metrics-file run passed `278` with `2` expected real
skips and `1` warning; and the four-test race-stress slice passed five
consecutive repetitions. Independent review approved the narrow correction with
`0` Blocking and `0` Major findings. That approval is not terminal story,
metrics/custody, or production approval and cannot replace a real retained
campaign.

Independent child observations and slow boundary checks can still leave a
residual for a child created and reaped entirely between them. The retained
campaign therefore also binds an exact static no-spawn guard only over the
manifest-bound P04-owned/app final-code path set. For this freeze that set is
exactly `app/api.py`, `app/config.py`, `app/models.py`,
`app/services/opaque_group_custody.py`, `app/services/pipeline.py`,
`app/services/serializer.py`, `app/services/source_text_alignment.py`,
`app/services/table_semantics.py`, `app/services/tables.py`, and
`app/services/text_reconciliation.py`; it is not a claim about the full
transitive dependency closure. Because every measurement state runs in a fresh
worker, it retains the complete cumulative
`resource.getrusage(RUSAGE_CHILDREN)` fingerprint before `t0` as part of the
completed baseline tuple and again at `t1_api`: normalized `ru_maxrss` plus
every numeric cumulative field exposed by the platform. Schema
`p04-us01-children-rusage-fingerprint-v1` retains exact fields `schema_id`,
`ru_utime_seconds_hex`, `ru_stime_seconds_hex`, `ru_maxrss_bytes`, `ru_ixrss`,
`ru_idrss`, `ru_isrss`, `ru_minflt`, `ru_majflt`, `ru_nswap`, `ru_inblock`,
`ru_oublock`, `ru_msgsnd`, `ru_msgrcv`, `ru_nsignals`, `ru_nvcsw`, and
`ru_nivcsw`. The two fingerprints must be exactly equal. A nonzero inherited
fingerprint is valid because pre-`t0` predecessor OCR/Tesseract may have run;
equality still detects a later smaller reaped child whose peak does not exceed
the inherited child HWM because another cumulative field changes. Any forbidden
spawn reference in the bound set, fingerprint difference, live descendant in
either child lane, or live descendant at a slow boundary fails the worker. The
child observer remains a residual control rather than an event-perfect
guarantee; the static and full-fingerprint controls mitigate a child created
and reaped between observations without adding child memory to the candidate.

The bounded RSS sampler cannot claim a mathematically exact instantaneous
peak. A sub-10-ms transient that remains below the inherited HWM could occur
between samples. Synchronous parse/hook/output RSS boundaries, the HWM
backstops, exact manifest-bound static no-spawn guard, exact `RUSAGE_CHILDREN`
cumulative-fingerprint equality, RSS maximum-gap enforcement, and defense-in-
depth allocation stress probes reduce those residuals. The proxy runs only in
the worker and receives zero manual resource credit: pre-`t0` identity/HWM/
rusage setup can affect inherited `B`/`H0`, intermediate boundary IPC and
production-output work are inside `G`, and FINISH-response decode plus socket
close are post-`t1`. Controller sampler, child-observer, FIFO, and child-
enumeration allocations are outside the exact worker process, create no
credit, and are retained as an explicit attested allocation split. The
residuals are disclosed; they do not raise the ceiling, waive
the gate, or turn a missing observation into a pass.

Two bounded fresh-subprocess controls provide non-real, defense-in-depth
sampler sensitivity only: one touches and retains a 16 MiB allocation through
`t1_api`; the other touches 16 MiB and releases it before `t1_api`. Each must
show at least 8 MiB current-RSS/HWM sensitivity while preserving cadence and
resource controls. In the managed sandbox these probes use an explicit no-child
process adapter because real psutil child enumeration returns `EPERM`; they do
not verify child scope. Separate deterministic tests own the child-observer,
slow-boundary-check, and child-fingerprint logic. Canonical retained-campaign
workers use the real independent recursive child-observer lane and boundary
checks with no bypass and fail closed if permission is unavailable; this means
the canonical retained campaign must run outside the managed sandbox.
These are canonical evidence workers, not production request workers.
Deterministic arithmetic tests, not these empirical probes, own exact
`67,108,864`-byte equality and maximum-plus-one behavior. The probes
neither replace the canonical three-case-by-five-pair campaign nor establish
near-bound empirical behavior.

## Outer worker process-group containment

Every outer fresh worker is launched by `subprocess.Popen` on supported POSIX
platforms in a private session/process group with `start_new_session=True`,
`close_fds=True`, `stdin=subprocess.DEVNULL`, and only the two bootstrap pipes
plus the exact monitor socket in `pass_fds`. The monitor socket is immediately
made and verified non-inheritable after worker exec. A bootstrap barrier prevents
the requested worker command from running until the parent binds the exact
leader PID and psutil create time together with the private PGID and SID; the
group must be distinct
from the parent and the leader PID, PGID, and SID must agree. This contains the
worker and descendants that remain in that private same-session/process group.

All success, nonzero exit, zero exit with a lingering descendant, timeout, and
diagnostic-overflow paths enter a bounded, resumable cleanup state machine. It
issues group `SIGTERM`, waits a fixed grace period while draining pipes, then
uses group `SIGKILL` only while authority over the already-bound group remains
uninterrupted. An `EPERM` or `ESRCH` observation makes signal authority
uncertain and permanently forbids a second signal. A cancellation at the KILL
syscall boundary permits at most one KILL retry, and only after the complete
intervening wait continuously re-proves the same group with neither `EPERM` nor
`ESRCH`; cancellation is otherwise deferred until cleanup reaches a terminal
state. Success requires an `ESRCH` absence proof for the bound PGID, reaping the
exact leader, and closing/draining selectors, pipes, bootstrap descriptors, and
worker streams. Setup and cleanup errors expose only sanitized categories,
error types, bounded byte counts/digests, and permitted errno values, never raw
worker output, paths, command text, environment values, or secrets.

Adversarial verification must cover timeout with a same-group descendant, a
TERM-ignoring descendant requiring KILL, diagnostic overflow with inherited
pipe descriptors, nonzero and zero leader exits with lingering descendants,
identity/group mismatch without signalling, cancellation at TERM and KILL
boundaries, the single permitted KILL-retry condition, cleanup uncertainty,
leader reap, FD/pipe closure, and sanitized-error custody. These controls do
not claim cleanup of an arbitrary descendant that deliberately detaches with a
new `setsid`/double fork, and they cannot eliminate the theoretical POSIX PGID-
reuse TOCTOU between a proof and a signal. The manifest-bound static no-spawn
guard, independent recursive child-observer lane and boundary checks, and exact
`RUSAGE_CHILDREN` fingerprint equality remain mandatory controls for those
disclosed residuals; they do not expand the measured memory scope.

Managed-sandbox real child enumeration returns `EPERM`. The two explicit
no-child-adapter allocation sensitivity controls remain non-real only; the
canonical retained campaign must run outside that sandbox with its real
independent recursive child-observer lane and slow boundary checks, no adapter
or permission bypass, and fail closed if observation authority is unavailable.

## Exact paired gate

Each of `ny-timetable`, `postal-10k`, and `finance-10k` still requires exactly
five fresh isolated alternating off/on pairs from the same final-code freeze.
For pair `i`:

- `S_i = G_on_i - G_off_i` is the retained signed output-complete window growth
  delta; and
- `D_i = max(0, S_i)` is its nonnegative gated projection.

The authoritative per-case RSS condition is
`max(D_0, D_1, D_2, D_3, D_4) <= 67,108,864` bytes. Exact equality passes and
maximum plus one fails. All five `S_i` and `D_i` values remain visible; no
quantile, averaging, outlier removal, reordering, or negative credit is
permitted. A failure in one worker invalidates that pair and the campaign; it
cannot be replaced selectively.

Absolute full-process `ru_maxrss` remains retained for each worker. Raw
cross-worker `peak_on - peak_off` deltas also remain visible but are explicitly
`observational_only_not_gated`. They cannot be reported as passes and cannot
substitute for `S_i`, `D_i`, or the maximum-of-five gate. The within-worker HWM
growth terms `Q_parse` and `Q_api` remain authoritative only as conservative
members of `G_parse` and `G_api`.

## Schema and old-artifact rejection

- The retained report advances from the accepted but unretained
  `p04-us01-table-metrics-v5` to `p04-us01-table-metrics-v6`.
- Its semantic projection advances from the accepted but unretained
  `p04-us01-final-metrics-semantic-projection-v5` to
  `p04-us01-final-metrics-semantic-projection-v6`.
- Paired performance advances from the accepted but unretained
  `p04-us01-paired-performance-v4` to `p04-us01-paired-performance-v5` and
  carries both unchanged exact RSS formula IDs,
  signed/nonnegative output-complete deltas, and the maximum-of-five result.
- Quality evidence advances from `p04-us01-quality-evidence-v2` to
  `p04-us01-quality-evidence-v3` because it embeds enabled snapshots with the
  required parent attestation.

An old report/projection/paired schema, one-lane child-bracketed record,
endpoint-only record, missing RSS or child-observer edge/cadence/count/
readiness/completion/error field, different formula ID, old cross-worker
absolute-HWM gate, or relabelled diagnostic must fail closed. The formula IDs
and all ceilings remain unchanged. No old observation is promoted or
rewritten. Latency formulas, worker diagnostics, and all non-RSS contracts
remain cumulative and unchanged. The earlier `v4`/`v4`/`v3` lineage remains
historical; immediate predecessor `v5`/`v5`/`v4`/quality-`v2` bytes are also
rejected as current evidence.

## Non-waiver and boundary

- The RSS ceiling remains exactly `67,108,864` bytes for all three cases and
  all five pairs. The latency, paired whole-parser, correctness, quality,
  output, resource, deadline, default-off, rollback, determinism, diagnostic,
  security, compatibility, API, serializer, frontend, custody, corpus,
  dependency-integrity, and zero-hosted-use gates remain mandatory.
- The exact named-stage and whole-parser latency ceilings remain `0.10`; this
  RSS correction cannot compensate for either latency failure. Both latency
  clocks stop at parse return and exclude the RSS checkpoint and output probe.
- The exact historical diagnostic samples, hashes, values, failed status, and
  absence of canonical retained evidence remain unchanged in
  `P04-US01-peak-rss-measurement-diagnostic.md`.
- P03-US08 attempt 48 remains failed at `0.050946750` seconds against the
  unchanged `0.050000000`-second ceiling: `0.000946750` seconds or `1.8935%`
  over, within but not waived by the maximum `5%` candidate-specific bound.
  Strict-final evidence remains absent. This record neither changes nor
  broadens the separately controlled, default-off P03 renewal.
- P04-US02, P04-US04, P04-US03, production enablement, and Phase 05 remain
  outside this decision. P04-US01 stays In Progress until fresh final-code
  evidence and every terminal approval are complete.

## Required verification before any pass claim

Non-opt-in tests must cover all formula members and precedence, exact-bound and
maximum-plus-one, below-inherited-HWM growth, a new-HWM-only observation,
negative signed pair retention, maximum-of-five aggregation, source/version
and process identity, both lanes' target and hard cadence plus edge/count/
readiness/completion/error fields, every boundary, first-observation release
proof, `F-C-F` request/completion ordering, exact active-boundary four-handoff/
observer two-handoff/pre-`t0` zero-handoff counts, stale in-flight generation
rejection, cancellation-safe FIFO ordering and between-scan release, stop/error/
end notification, finish barrier, acyclic lock ordering, start/finish and thread
failures, malformed samples, child-process rejection, static no-spawn
tamper, any `RUSAGE_CHILDREN` fingerprint difference, every parse/output
checkpoint and sync-count, exact composite boundary order plus production
callable/options and per-branch materialization, the pre-`t1_api`
bounded-identity/post-`t1_api` allocation split, JSON and Markdown response byte
size/hash/parity, distinct parsed/jsonable/public identities, result and public-
mapping nonmutation, body release, restoration and latency-clock separation,
old-schema and old-formula rejection, observational absolute peaks, semantic
digest tamper, and fail-closed artifact handling. Controlled stress
probes must exercise short-lived and sustained allocations without being used
as retained real campaign samples. The exact 16 MiB sustained/released fresh-
subprocess controls require at least 8 MiB current-RSS/HWM sensitivity plus
cadence and resource closure. Their managed-sandbox no-child adapter does not
test child controls; separate deterministic tests own the independent child
observer, slow boundary checks, and fingerprint behavior, while canonical
workers permit no adapter or permission bypass and must run outside the managed
sandbox. Deterministic unit arithmetic
alone owns the exact 64 MiB and plus-one
boundary.

Completion still requires exact final-code identities, five fresh alternating
pairs for each of the three reviewed cases, reviewed real quality documents,
all affected regressions and corpus screens, and independent
production/security plus metrics/custody approval. This Accepted measurement
contract is only permission to collect that evidence; it is not evidence that
any gate currently passes.

## Superseded-document custody

These exact pre-edit identities bind the documentation superseded by this
decision:

| Superseded path | Pre-supersession SHA-256 |
|---|---|
| `tracker/phase-04-tables/decisions/P04-table-evidence-policy.md` | `fa6e278c32278b691199258b5a30a3774cb5ac083bfebccb8f528a43716e1358` |
| `tracker/phase-04-tables/metrics.md` | `8a91d8eba84d4b6ce85a4efbca6d9de10bb023e075e44d8056d173c64bd9a5de` |
| `tracker/phase-04-tables/stories/P04-US01.md` | `52b8cee361dc191056b825b15602cefdb5991ea124b7b84bf73fc0a42c7197c9` |
| `tracker/phase-04-tables/evidence/P04-US01-peak-rss-measurement-diagnostic.md` | `3046f3bc9d428938a135aab9ce72230d536affa2c1dfeea07f4ab82039ff624e` |
| `tracker/phase-04-tables/phase-regression.md` | `4b3c02e64ffd5b1cb8d0b2e632739d7944b83bb049b60d60f7ce9ab89745ae94` |

The hashes are retained verbatim from the immediate pre-supersession
workspace. Final review must bind this decision and every final-code identity;
the old documents and failed diagnostics cannot be reconstructed as a current
pass.

That table remains the unchanged custody record for the initial controlled
supersession. The immediate pre-two-lane-correction identities are separately
preserved here and are not rewritten as current evidence:

| Pre-two-lane path | SHA-256 |
|---|---|
| `tracker/phase-04-tables/decisions/P04-US01-phase04-stage-peak-rss-controlled-supersession.md` | `ff8c03a4b8c15f78de7b1eacca8ddc464b9c51c5aaf4d224116b747d13023f0c` |
| `tracker/phase-04-tables/decisions/P04-table-evidence-policy.md` | `07bb48d50635122795d44cfe1a4c6471b8d3f3d18884dc354acf09ad59e97045` |
| `tracker/phase-04-tables/metrics.md` | `7303e4ea5cad68ce9984108a02abee2619869b96c6573928f5cf679d95911f0b` |
| `tracker/phase-04-tables/phase-regression.md` | `81ebbce119bf9066b4b54026f15591699f8d488a5a5189a0d3acdef6ef188438` |
| `tracker/phase-04-tables/stories/P04-US01.md` | `87e9c0eaa62dab72fc227a2c47ee23842f7fe902bd7296d718182eb1fcfb6196` |
| `tracker/phase-04-tables/evidence/P04-US01-peak-rss-measurement-diagnostic.md` | `60fb4283bdb096245103c151250400133ba0752a52b88448e77ca2428b6510e8` |

One external-controller `v6` retained-generation attempt ran and failed closed
without a final artifact; its immutable record is
`../evidence/P04-US01-retained-metrics-v6-attempt-01-failed.json`. It is not a
completed campaign or pass. The later noncanonical cadence candidates listed
in `../evidence/P04-US01-peak-rss-measurement-diagnostic.md` also remain failed
history. The exact retained final artifact remains absent. These identities
establish lineage only; they are not pass or completion evidence.
