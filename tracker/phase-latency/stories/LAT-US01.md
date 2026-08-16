# LAT-US01 — Establish exact stage attribution and benchmark harness

Status: **Done — requester-approved scoped r34 owner exception**  
Story points: 5  
Phase: Phase Latency — Latency Improvement  
Priority: Critical  
Dependencies: P00-US10, P01-US04, P02-US06, P03-US08  
Feature flag: None — attribution is benchmark-worker-only and production code remains unchanged  
Ready: 2026-08-08  
Started: 2026-08-08
Completed: 2026-08-10

## Definition of Ready

Pass — 10/10 requirements are recorded in
[`LAT-US01-readiness.md`](../evidence/LAT-US01-readiness.md). LAT-US01 is the
completed predecessor of LAT-US02. The historical readiness transition changed
tracker records only; the exact r34 completion and limitation records now
govern its Done status.

## User story

As a parser performance owner, I want exact final-code stage and request
attribution, so that optimization targets are chosen from measured work without
mistaking an omitted or failed parse for a speedup.

## In scope

- Monotonic timings for input load, native PDF evidence, converter/model
  initialization, Docling conversion, rendering, every OCR route, vector table
  extraction, reconciliation/IR, validation, and JSON/Markdown response work.
- CPU, peak RSS, process/child count, output size, failure, timeout, retry, and
  cancellation accounting at bounded document and stage boundaries.
- Cold/warm, isolated/concurrent, success/failure, and cache-disabled profiles.
- A reproducible final-code harness for all 15 registered cases and the paired
  LlamaParse protocol.

## Out of scope

- Optimizing or skipping any parser work.
- Changing extraction, reconciliation, schema, serializer, or frontend output.
- Production telemetry export, production enablement, or a new dependency.

## Controlling LlamaParse and RSS policy

LlamaParse remains the latency and quality benchmark. Independently, every
applicable local authoritative/diagnostic pair must keep diagnostic worker
self-HWM minus authoritative worker self-HWM no greater than `67,108,864`
bytes (64 MiB). This is the unchanged local instrumentation-overhead gate and
applies in addition to every absolute, per-case, and concurrent RSS/resource
ceiling. A LlamaParse latency or quality result cannot replace, offset, or
waive this local gate; the public LlamaParse benchmark supplies no comparable
per-job worker RSS. Failure of either benchmark family blocks the story.

## Acceptance criteria

1. Every material stage in the approved inventory opens and closes exactly
   once per invocation or records an explicit failure/cancellation state.
2. Nested and overlapping timings reconcile under a documented rule without
   double counting; monotonic-clock anomalies and incomplete stages fail closed.
3. Cold versus warm and isolated versus bounded-concurrent runs retain exact
   input, source-tree, dependency, model, configuration, environment, and output
   identities.
4. The uninstrumented authoritative worker installs no stage hook or in-worker
   probe and preserves exact predecessor JSON/Markdown/API behavior; its
   separately identified diagnostic twin must prove output and outcome parity.
5. Diagnostic records contain bounded enums and identities, never document
   text, credentials, provider tokens, crops, or unbounded source-derived labels.
6. Every timeout, crash, malformed-input result, and failed provider/local run
   remains in the denominator; no cache hit or aggregate masks a failure.
7. All 15 cases retain unchanged reviewed quality, concern, provenance,
   compatibility, and output denominators.
8. The harness rejects fewer than five interleaved, semantically comparable
   candidate/LlamaParse samples per case and enforces candidate p50/p95 no
   greater than paired Llama values. LAT-US01 performs no optimization and
   therefore records no hosted or paired pass; the authorized 1,500-credit
   exact-input campaign is reserved for frozen final bytes in LAT-US08. Stage
   timings remain diagnostic and cannot create a pass.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us01_stage_profiler.py`
- `tests/performance/test_latency_benchmark_harness.py`
- Contract/API/serializer disabled-parity and metadata-bounds tests.
- Negative clock, duplicate-close, missing-close, timeout, cancellation,
  malformed-input, failed-worker, and missing-comparator controls.
- All 15 registered real documents plus synthetic lifecycle controls.

## Metrics and evidence

Retain raw stage/request observations, environment/configuration identities,
CPU/RSS/process/output measures, quality comparisons, failures, and synthetic
negative provider controls. Final paired Llama job IDs are retained by
LAT-US08. Record exact final-code identities in `../evidence/`; update
`../metrics.md` only from retained evidence.

## r34 non-RSS closure state

The retained r34 profile and evaluation are sealed by the
[non-RSS validation](../evidence/LAT-US01-r34-non-rss-validation.md) and the
separate [production/security](../evidence/LAT-US01-r34-production-security-review.md)
and [metrics/custody](../evidence/LAT-US01-r34-metrics-custody-review.md)
reviews. They establish every non-RSS requirement without a new campaign.
LAT-US01 is **Done under the requester-approved scoped r34 owner exception**
recorded in
[`LAT-US01-r34-scoped-owner-exception.md`](../decisions/LAT-US01-r34-scoped-owner-exception.md).
The r34 evaluation retains the `diagnostic_hwm_delta_exceeded` failure under the
unchanged 64 MiB local gate; the exception does not convert it into a pass.
LAT-US02 has not started.

## API/schema and compatibility

Disposable benchmark-worker diagnostics only. Public API, schemas, JSON,
Markdown, frontend, and legacy projections remain unchanged.

## Rollback

Stop the isolated benchmark worker. No production flag, telemetry module,
logger, cache, worker, or attribution boundary is installed, so the application
continues to execute the single exact configured predecessor path.

## Definition of Done

All acceptance criteria and focused tests pass; impacted Phase 00–03 and
full-corpus regressions pass; the paired-Llama harness rejects every incomplete,
non-interleaved, drifted, failed, or slower synthetic campaign; independent
resource gates pass; exact final-code evidence and quality denominators are
retained; hosted use is exactly zero for this non-optimization story; default-
off rollback is verified; production/security and metrics/custody reviews have
no blocking finding; completion and tracker records reconcile; LAT-US02 has not
started early.

## Done disposition

The requester-approved
[scoped r34 owner exception](../decisions/LAT-US01-r34-scoped-owner-exception.md)
is the sole controlled departure from the independent resource-gate sentence
above. It applies only to the retained r34 instrumentation-HWM failure, does
not call that gate a pass, and does not transfer to LAT-US02 or any other work.
