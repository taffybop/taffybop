# LAT-US07 — Bound parser concurrency and queue latency

Status: **Proposed — paused for release-first Phase 04–08 delivery**  
Story points: 5  
Phase: Phase Latency — Latency Improvement  
Priority: High  
Dependencies: LAT-US06  
Feature flag: `parser.latency.worker_pool.enabled` (default off)

## User story

As a service operator, I want a bounded pool of prewarmed parser workers, so
that concurrent requests do not serialize behind one global conversion lock or
exhaust memory.

## In scope

- One safely owned converter per worker where thread/process safety requires it.
- Bounded worker count, queue depth, admission, fairness, cancellation,
  backpressure, readiness, crash replacement, and graceful shutdown.
- Separate service/queue and isolated-document measurements.

## Out of scope

- Sharing non-thread-safe converter state, unbounded scaling, production
  autoscaling, distributed scheduling, or cross-tenant result caching.

## Delivery validation policy

Completion requires production implementation and basic representative
end-to-end validation with bounded concurrent requests. Worker ownership,
queue admission, ordinary cancellation/shutdown, output compatibility, and
default-off rollback must work within configured targets. Sustained stress,
exhaustive scheduling/failure injection, strict throughput/RSS qualification,
process-lineage proof, and independent security/custody review are deferred to
later hardening.

## Acceptance criteria

1. No converter instance is used outside its declared safe ownership model and
   no request state crosses worker boundaries.
2. Configured worker and queue bounds backpressure or reject a representative
   over-capacity request with a compatible error.
3. Representative queue cancellation, worker failure, and shutdown complete
   without a duplicate or partial response.
4. A basic concurrency run preserves per-request output and attributes an
   injected failure to the correct request.
5. Disabled behavior restores the exact predecessor lock/lifecycle path.
6. Lightweight isolated and concurrent timing/memory smoke checks remain within
   basic configured targets.
7. Representative success output, timeout behavior, and rollback remain
   compatible at the tested concurrency.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us07_worker_pool.py`
- Representative ownership, queue-full, two-request concurrency,
  cancellation/failure, shutdown, output-compatibility, and rollback tests.

## API/schema and compatibility

Success outputs remain unchanged. Backpressure/timeout errors must preserve the
existing public error contract; no production deployment is authorized.

## Rollback

Set `PARSER_LATENCY_WORKER_POOL_ENABLED=false`; drain and stop latency-owned
workers, then restore the exact predecessor lifecycle and lock behavior.

## Definition of Done

Production code is complete and reviewed; focused tests and a representative
bounded-concurrency end-to-end flow pass; queue admission, output compatibility,
basic failure cleanup, shutdown, and default-off rollback are confirmed; and no
known blocking functional defect remains. Exhaustive stress, security,
performance, process-lineage, evidence, and adversarial validation is deferred
to later hardening.
