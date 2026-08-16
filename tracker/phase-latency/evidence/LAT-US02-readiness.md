# LAT-US02 Definition-of-Ready Record

Status: **10/10 Pass; LAT-US02 is the sole In Progress story**  
Date: 2026-08-10  
Story: LAT-US02 — Prewarm and safely reuse parser workers

## Prerequisite reconciliation

LAT-US01 remains Done only under its exact requester-approved scoped r34 owner
exception. A fresh pre-change reconciliation reproduced the retained
evaluation byte-for-byte as `passed=false` solely for
`diagnostic_hwm_delta_exceeded`; it did not convert the r34 RSS result into a
pass. The retained profile, evaluation, and private attempt-ledger SHA-256
values remain respectively:

- `7f50beda94a0ddfa36cef6d9c563ae1b5ba77b9e96d944cb4445d92b8cd4e01c`
- `828f607e1a27cb501235c6294f9602fce7d021ee02d2f1efbfd93fc8a7dd4898`
- `28b8e9d6d82727fb1c17c911dbe5a06ab68ac3117f62b2851a87c943c56d4041`

All three are regular mode-`0600` files. All 47 attempts and 94 role
observations remain successful. The current pre-LAT-US02 application,
dependency-lock, and model-tree identities exactly match r34:

- application: `d1d65d70a98dcdbbfbdccae9cb5c82316395765777f1c8fb9a439af8d64624d7`
- dependency lock: `0253ae6df39a044b66d2b10d1a486841c7a25b2b1225e9a6aee2b6bf3016a2dc`
- model tree: `a204f7eaeb2cac3d30ea9618d7ebe1afdfab74646a4c2b47ba0897d386b764f5`

All ten retained LAT-US01 harness identities also match. The focused
continuation-driver check passed 4/4 with one pre-existing warning. No retained
LAT-US01 evidence, decision, evaluation, limitation, or completion record is
reopened by this readiness transition.

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — bounded startup validation/prewarm and safe reuse of the existing local converters only; no extraction-option, model, public-output, result-cache, concurrency-pool, LAT-US03+, Phase 04, Phase 05, hosted-campaign, or production-enablement work |
| Points at most 5 | Pass — 3 |
| Dependencies Done | Pass — LAT-US01 is Done under its exact non-transferable r34 exception, with the failed local HWM conclusion preserved |
| Acceptance measurable | Pass — READY is atomic after exact identities and both pipelines validate; missing/corrupt/mismatched/timeout/cancel/shutdown states fail closed; repeated output/isolation, disabled parity, cleanup, and local enabled/predecessor comparisons are explicit |
| Dedicated tests identified | Pass — `tests/stories/phase_latency/test_lat_us02_worker_prewarm.py` plus focused API/config/contract, subprocess-timeout, malformed/failure, real-document, compatibility, resource, and impacted Phase 00–03 regressions |
| Fixtures available and authorized | Pass — the registered 15-case public/redistributable corpus, existing synthetic PDFs/images, malformed controls, and exact local Docling/Tesseract artifacts are available; no hosted input or runtime download is required |
| API/schema impact documented | Pass — no public response/schema/serializer change; enabled startup/readiness is operational and failures use the existing content-free extraction-unavailable boundary |
| Feature flag identified | Pass — `parser.latency.prewarm.enabled`, mapped to `PARSER_LATENCY_PREWARM_ENABLED`, remains false by default |
| Rollback defined | Pass — `PARSER_LATENCY_PREWARM_ENABLED=false` restores the exact lazy LAT-US01/predecessor converter lifecycle without residual owned resources |
| Quality/performance specified | Pass — every applicable local enabled/predecessor case must improve or preserve request latency with byte/semantic quality and reliability unchanged; hosted Llama rows remain directional; numerical RSS is retained but owner-deferred exactly as recorded below |

Definition-of-Ready result: **10/10 Pass**.

## Lifecycle and architecture inspection

The current worker has no startup/readiness/shutdown lifecycle. It lazily
constructs separate PDF and image `DocumentConverter` instances in process
`lru_cache` entries, and both conversions share one process-global lock.
Converter construction alone is not prewarming: Docling's natural
`initialize_pipeline()` path performs the heavyweight model initialization on
the first conversion. Artifact checks are presence-only, Tesseract is checked
only after request work begins, and no production cache cleanup exists.

No worker-pool or process-concurrency architecture change is required. The
smallest reversible design is one per-application, per-PID runtime owned by the
ASGI lifespan. The enabled path will validate a deployment-pinned bounded
artifact/dependency/configuration identity, initialize the existing PDF and
image converter keys under the existing lock, and publish READY atomically
only after both pipelines succeed. Enabled requests must receive that exact
runtime explicitly and fail closed on state, PID, generation, configuration,
or retained-artifact mutation. Shutdown stops admission and clears both owned
converter caches/references. The disabled branch retains the existing lazy
functions unchanged.

Docling model initialization is synchronous and exposes no safe cancellation
API. An async/thread timeout would leave a partially initialized native worker
alive. Therefore the enabled-only startup boundary requires a worker-fatal
watchdog: if initialization does not complete within the configured deadline,
the disposable Uvicorn worker exits without publishing READY and is restarted
by process supervision. This is failure isolation, not a parser-worker pool;
the broader pool remains LAT-US07 scope.

A dual-format converter could share one model pipeline, but that would be a
larger cross-format state change. LAT-US02 retains the two existing converter
paths and measures their observational idle RSS instead.

## Owner-directed RSS handling

The requester-directed
[LAT-US02 RSS deferral](../decisions/LAT-US02-owner-directed-rss-deferral.md)
is part of this readiness basis. Cold initialization, prewarmed idle, request
peak, repeated-request, and shutdown RSS remain mandatory observations. The
strict 64 MiB numerical gate is not a LAT-US02 completion blocker and no strict
RSS pass may be claimed. Leaks, unbounded growth, OOM, failed cleanup, orphaned
workers/threads, unsafe admission, and cross-request retention remain blocking.
The deferral does not transfer to later stories, Phase 04, production, LAT-US08,
or phase exit.

## Before-code progress statement

At this transition, inspection, prerequisite reconciliation, scope, and design
are complete: **15% complete**, with an evidence-based **2–4 hour estimated
remaining time** for implementation, focused validation, local evidence,
independent reviews, and final record reconciliation. No genuine blocker is
known. This statement was recorded before production implementation began.

LAT-US02 is the only story permitted to be In Progress. LAT-US03–LAT-US08
remain Proposed and unauthorized; P04-US01 remains Ready with execution paused,
Phase 05 remains Proposed, production remains disabled, and the final hosted
LlamaParse campaign remains reserved for LAT-US08.
