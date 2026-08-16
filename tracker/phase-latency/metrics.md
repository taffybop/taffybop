# Phase Latency Metrics Contract

Status: **LAT-US01 Done under scoped r34 owner exception; LAT-US02 Done under requester-directed validation deferral; no LAT-US02 candidate pass recorded**

## LAT-US02 campaign blocker

Major [`LAT-US02-METRIC-CPU-001`](evidence/LAT-US02-cpu-lineage-blocker.md)
prevents the local production campaign. Aggregate child rusage plus live edge
snapshots cannot prove exact PID/create-time CPU custody for short-lived,
reparented, or intermediate native descendants. Independent
[production/security](evidence/LAT-US02-production-security-review.md) and
[metrics/custody](evidence/LAT-US02-metrics-custody-review.md) reviews therefore
prohibit launch and Done.

The requester subsequently marked LAT-US02 administratively Done after the
production implementation completed, explicitly deferring the remaining
evidence migration, complete validation, and campaign. This does not convert
the historical NO-GO into a pass. No LAT-US02 latency, RSS, or production-ASGI
measurement was taken. Numerical
RSS remains owner-deferred for this story only, but CPU completeness is not
observational or waived. The required metric registry's `After` cells remain
Pending, and no strict RSS, hosted, paired-Llama, story, or phase pass exists.

## r34 retained-evidence disposition

The exact r34 profile SHA-256 is
`7f50beda94a0ddfa36cef6d9c563ae1b5ba77b9e96d944cb4445d92b8cd4e01c`; its
evaluation SHA-256 is
`828f607e1a27cb501235c6294f9602fce7d021ee02d2f1efbfd93fc8a7dd4898`.
The evaluator was rerun over the retained bytes and reproduced that evaluation
exactly: 47 selected attempts and 94 role observations all succeeded, with no
attempt, role, controller, or drift failure. Quality/output, custody,
production-off, rollback, and hosted-use-zero checks are sealed in the
[r34 non-RSS validation](evidence/LAT-US01-r34-non-rss-validation.md).

The evaluation is nevertheless `passed: false` for exactly
`diagnostic_hwm_delta_exceeded`. This local HWM result is unchanged, unwaived,
and does not become a LlamaParse or RSS pass. The requester-approved
[scoped owner exception](decisions/LAT-US01-r34-scoped-owner-exception.md)
permits LAT-US01 completion only for these exact retained r34 bytes.

## Streamlined metric policy for LAT-US03–LAT-US08

The remaining stories use representative local smoke measurements only. A
story may complete when its production flow works end to end within configured
basic latency, memory, output-size, timeout, and queue targets and shows no
obvious predecessor regression. The strict registry and paired protocol below
are retained as deferred hardening references; they are not blocking completion
criteria for LAT-US03–LAT-US08 and must not be described as passed unless run.

## Deferred hardening measurement reference

The sole latency benchmark is
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md).
Its 15 authenticated observations are initial planning references only:
descriptive median 29.4 seconds and range 15.8 seconds to the provider-rounded
1.4 minutes. Cross-case summaries are descriptive and never thresholds.

The historical local parser run remains immutable diagnostic evidence: 15/15
successes, median 9.06 seconds, nearest-rank p95/maximum 46.76 seconds, median
peak RSS 1,437 MiB, and maximum peak RSS 2,590 MiB. These values cannot satisfy
or replace the paired LlamaParse gate.

## Deferred hardening metric registry

| Metric | Before/current | Hardening target | After |
|---|---|---|---|
| Provider Total Latency | One cache-disabled planning observation per 15 cases | At least five interleaved final-candidate/Llama observations per case | Pending |
| Candidate end-to-end latency | Historical isolated local diagnostics only | Retain every success/failure; compute per-case p50 and inclusive nearest-rank p95 | Pending |
| Candidate versus LlamaParse | Unmeasured | Candidate p50 ≤ paired Llama p50 and candidate p95 ≤ paired Llama p95 for each of 15 cases | Pending |
| Cold/warm attribution | Not consistently separated | Exact converter/model init and request-stage identities; diagnostic only | Pending |
| Material-stage coverage | Total duration only | 100% approved stage lifecycle/error coverage with nested accounting | Pending |
| Quality/reliability | Reviewed Phase 00–03 denominators | Unchanged or improved on every affected denominator; zero unexplained drift | Pending |
| Public compatibility | Current canonical API/schema/JSON/Markdown/frontend | Exact predecessor behavior unless separately approved additive diagnostics remain internal | Pending |
| Peak RSS/CPU/process/resources | Historical platform-bound diagnostics | Independently bounded and reviewed for each story and maximum concurrency; never offset by speed | Pending |
| Output/cost/egress | Current response identities and local-only cost profile | No unexplained output growth; provider/hosted use remains explicitly governed | Pending |
| Timeout/failure/rollback | Existing fail-closed behavior and flags | Every failure retained; default-off and reverse-order exact rollback pass | Pending |

## LAT-US01 predeclared non-latency gates

These gates were fixed before any final LAT-US01 real profile was accepted.
They do not replace the LlamaParse latency comparator, cannot create a latency
pass, and are conservative absolute safety caps rather than a same-environment
P00 performance-regression pass.

LlamaParse remains the latency and quality benchmark, while the unchanged
`67,108,864`-byte (64 MiB) diagnostic-versus-authoritative self-HWM ceiling is
an independent local instrumentation-overhead gate. Public LlamaParse evidence
provides no comparable per-job worker RSS, so it cannot replace, offset, or
waive this local limit. Conversely, a local RSS pass cannot create a
LlamaParse latency or quality pass. These strict benchmark families remain
historical/deferred hardening targets rather than LAT-US03–LAT-US08 completion
gates.
The sole current exception is the
[owner-directed LAT-US02 numerical RSS deferral](decisions/LAT-US02-owner-directed-rss-deferral.md):
LAT-US02 retains cold-initialization, prewarmed-idle, request-peak,
repeated-request, and shutdown RSS as observational values and may not claim a
strict RSS pass. Numerical RSS alone does not block this default-off story;
leaks, unbounded growth, OOM, orphaning, cleanup failure, unsafe admission, and
cross-request retention do. The strict 64 MiB gate remains available for later
hardening; remaining latency stories use the streamlined smoke policy above.

The resource reference is the exact retained M0 run metadata at
`tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/run-metadata.json`
(SHA-256 `386c333bff8ec0678d1194fff5899f82ec9475d29be7d72999a58c3817e3128f`,
8,025 bytes). The current locked environment has `docling-core 2.88.0`, while
M0 used `2.87.1`; therefore `environment_comparable=false` is mandatory and no
P00 tolerance/regression pass may be claimed. As stricter fail-closed absolute
safety caps despite that non-comparability:

- the all-15 cold authoritative self-HWM p50 must be no greater than
  `1,883,504,640` bytes and the maximum no greater than `3,394,068,480`
  bytes, numerically equal to the immutable P00 values plus its pre-existing
  25% margin but not credited as that environment-specific tolerance;
- every isolated authoritative, diagnostic, prewarmed, and Markdown worker
  must also remain no greater than its own retained M0 case RSS plus the
  unchanged `67,108,864`-byte P03 delta ceiling; for example, Uber is capped at
  `2,782,363,648` bytes and NY timetable at `2,105,491,456` bytes. These are
  conservative absolute safety caps, not claims that different lifecycles or
  output formats are comparable;
- within the same case and lifecycle, the diagnostic-role worker self-HWM minus
  the authoritative-role worker self-HWM must be no greater than `67,108,864`
  bytes; cross-lifecycle values are recorded but are not treated as comparable
  deltas;
- the fixed bounded-concurrent control is NY timetable plus Uber at concurrency
  two. Its synchronized descendant-inclusive aggregate RSS must be no greater
  than the sum of their predeclared ceilings, `4,887,855,104` bytes, and each
  worker must still pass its individual ceiling; and
- worker evidence is capped at `4,194,304` bytes and every response remains
  bounded by the existing `67,108,864`-byte harness limit.

No inherited CPU, thread-count, process-count, or file-descriptor regression
number exists, so none is invented. CPU evidence must be request-boundary
scoped from exact counters, recomputed per process, and no greater than request
wall time multiplied by host logical CPUs; the concurrent window uses the same
physical host capacity rule. Rounded, sampled-late, missing, or post-validation-
contaminated CPU evidence blocks.
Isolated execution permits exactly one owned parser-worker group; the fixed
concurrent control permits at most two and must observe occupancy two. PID plus
create-time identities are unique, every descendant is owned, all groups and
processes are reaped, and controller threads/file descriptors return exactly
to their pre-run baseline. Peak counts remain reported even though they have no
fabricated numeric regression ceiling.

Quality custody is bound to the exact retained P00-US10 run record
(SHA-256 `aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2`,
79,247 bytes) and semantic report
(SHA-256 `3d2e36fd6696039abaeb346fc458687f9f114a340bc895c8ee5b921efbb17c77`,
317,372 bytes). The default-off all-15 profile must retain 15 cases/30 pages,
210 reviewed claims with 109 literal, 162 semantic, and 48 excluded masks, 25
controls, 12 dimensions, quality signature
`a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed`,
and stable-output signature
`a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0`.
Per-case JSON may exclude only `/processing/duration_ms` from semantic identity;
Markdown remains exact. Hosted calls, credits, tokens, cost, and egress are
exactly zero in LAT-US01.

## Deferred paired comparison protocol

### Finite hosted-campaign sequencing

The previously authorized hosted allowance describes one optional hardening campaign:
five exact-input rounds over 30 pages at 10 Agentic credits/page, for 1,500
credits. It may run in a later hardening phase after the candidate is frozen;
it is not required by LAT-US08 or phase completion. Until executed, no story
records a paired LlamaParse pass.

If the optional campaign is executed during later hardening, for each of all 15
cases:

1. pin identical source bytes and document semantic comparability;
2. pin candidate code, dependency, model, configuration, environment, warm/cold,
   concurrency, timeout, output, and cache policy;
3. run LlamaCloud Parse v2 Agentic with cost optimizer off, cache disabled, and
   provider Total Latency;
4. collect at least five interleaved candidate/provider samples and retain raw
   successes, failures, timeouts, job IDs, and durations;
5. compute empirical p50 and inclusive nearest-rank p95 independently; and
6. fail the case unless both candidate percentiles are no greater than paired
   Llama values and every required quality/reliability gate passes.

Incomparable, stale, missing, failed, or custody-uncertain evidence is
**Unmeasured/Blocked**. Stage timings, local predecessor ratios, fixed local
durations, forecast ranges, cache hits, and corpus averages cannot confer a
pass.

## Deferred comprehensive quality and non-latency gates

Retain source-grounded reviewed-claim and control denominators for text,
reading order, captions, forms, running regions, printed pages, tables,
geometry, provenance, concerns, JSON, Markdown, API/schema, serializer, and
frontend behavior. Record deterministic repeatability, malformed input,
timeouts, cancellation, cleanup, security/privacy, custody, dependency
integrity, CPU/RSS/process/thread/file-descriptor/pixel limits, output size,
cost/egress, default-off, and rollback independently when the later hardening
phase is executed. These exhaustive checks are not current story-completion
requirements.

## Planning expectations, not acceptance claims

The phase was planned around approximately 25–45% improvement on the slowest
OCR-heavy documents. That range is a forecast only. No fixed projected duration
is a completion threshold and no improvement is claimed from the forecast.
Current story completion uses the basic functional and smoke policy above.
