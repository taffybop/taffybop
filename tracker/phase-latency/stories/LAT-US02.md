# LAT-US02 — Prewarm and safely reuse parser workers

Status: **Done — production implementation complete; validation and campaign deferred by requester**  
Story points: 3  
Phase: Phase Latency — Latency Improvement  
Priority: High  
Dependencies: LAT-US01  
Feature flag: `parser.latency.prewarm.enabled` (default off)
Ready: 2026-08-10  
Started: 2026-08-10
Blocked: 2026-08-10
Architecture authorized: 2026-08-10
Completed: 2026-08-10

## Definition of Ready

Pass — 10/10 requirements, the lifecycle inspection, smallest reversible
design, owner-directed RSS treatment, completion estimate, and pre-code ETA are
recorded in [`LAT-US02-readiness.md`](../evidence/LAT-US02-readiness.md).
LAT-US02 is complete under the requester-directed validation deferral recorded
below. LAT-US03 and every later story remain Proposed until separately
confirmed and made Ready.

## User story

As an API consumer, I want parser workers ready before accepting work, so that
lazy model initialization does not inflate the first parse or create unstable
readiness.

## In scope

- Bounded startup initialization of the existing converter and approved local
  model artifacts.
- Readiness only after exact artifact/dependency validation succeeds.
- Safe per-worker reuse, startup timeout, failure isolation, shutdown cleanup,
  and cold/warm evidence.
- The requester-authorized one-to-one external Tesseract broker and permanent
  parser-worker fork denial needed for exact CPU lineage and quiescence.

## Out of scope

- Changing extraction options, model artifacts, model quality, or public API.
- Adding request concurrency, a worker pool, or cross-request result caching;
  the authorized broker remains serialized and one-to-one.

## Controlling LlamaParse and RSS policy

LlamaParse remains the latency and quality benchmark, and LAT-US02 performs no
hosted campaign or paired-Llama qualification. Under the requester-directed
[LAT-US02 numerical RSS deferral](../decisions/LAT-US02-owner-directed-rss-deferral.md),
cold-initialization, prewarmed-idle, request-peak, repeated-request, and
shutdown RSS remain mandatory observations, but the strict `67,108,864`-byte
diagnostic-versus-authoritative threshold is not a LAT-US02 completion blocker
and no strict RSS pass may be claimed. Leaks, unbounded growth, OOM, failed
cleanup, orphaning, unsafe admission, and cross-request retention remain
blocking. The deferral is non-transferable to later stories or phase exit.

## Acceptance criteria

1. A worker accepts requests only after its exact converter/model identity is
   validated or reports an explicit unavailable state.
2. Startup timeout, corrupt/missing artifact, dependency mismatch, and shutdown
   during initialization fail closed without serving a partial worker.
3. Reused workers produce byte/semantic-equivalent outputs, concerns,
   provenance, and deterministic IDs across repeated registered inputs.
4. No document content, result, tenant data, or mutable request state survives
   between requests.
5. Disabled prewarming preserves the exact predecessor lifecycle and output.
6. Cold and warm CPU/process/output evidence remains within independent
   budgets, all required RSS observations are retained under the scoped owner
   deferral, and local enabled/predecessor repetitions improve or preserve every
   applicable case with unchanged quality and reliability. Initial Llama rows
   are directional only; canonical paired qualification remains LAT-US08.

## Dedicated tests

- `tests/stories/phase_latency/test_lat_us02_worker_prewarm.py`
- Startup/readiness, corrupt artifact, timeout, shutdown, repeated-request,
  cross-request isolation, and dependency-integrity tests.
- Registered slow cases plus small clean controls.

## API/schema and compatibility

No public response change. Operational readiness semantics remain backward-
compatible and no new artifact is downloaded at runtime.

## Rollback

Set `PARSER_LATENCY_PREWARM_ENABLED=false`; retain the existing lazy lifecycle
and exact configured predecessor.

## Definition of Done

Fresh 10/10 readiness, all acceptance/focused/regression/compatibility/resource
and local latency gates, exact artifact custody, default-off rollback, retained
final-code evidence, independent reviews, and a completion report pass before
LAT-US03 starts. No hosted or paired-Llama pass is claimed before LAT-US08.

## Completion disposition

The requester marked LAT-US02 Done after the production implementation was
completed. The remaining shared benchmark/evidence-schema migration, final
production `KernelSandboxEvidence` assembly, complete regression and
authoritative host verification, and the one-shot local campaign were
explicitly deferred. This is an administrative completion decision, not a
claim that those validation gates passed.

Accordingly, LAT-US02 records no campaign GO, candidate pass, phase pass,
hosted or paired-Llama qualification, strict RSS pass, or production
enablement. The feature remains default-off and
`PARSER_LATENCY_PREWARM_ENABLED=false` remains the rollback. The historical
blocked handoff and independent review records are retained unchanged as the
exact validation state at closure.

## Historical remediation disposition

The default-off production lifecycle and the non-CPU campaign-controller
controls are implemented and tested, but the required campaign did not launch.
Independent [production/security](../evidence/LAT-US02-production-security-review.md)
and [metrics/custody](../evidence/LAT-US02-metrics-custody-review.md) reviews
confirmed Major [`LAT-US02-METRIC-CPU-001`](../evidence/LAT-US02-cpu-lineage-blocker.md):
Darwin request CPU cannot be proven complete for every owned native descendant
under the approved no-process-architecture scope. The owner-directed numerical
RSS deferral does not cover this CPU requirement.

The requester subsequently authorized the scoped
[permanently fork-denied worker and external Tesseract broker](../decisions/LAT-US02-fork-denied-worker-broker-authorization.md)
needed to remedy that Major. Production implementation subsequently completed,
while the remaining adversarial validation and campaign were deferred under
the completion disposition above.

The [blocked handoff](../reports/LAT-US02-blocked-handoff.md) records exact
identities, tests, zero campaign/hosted use, rollback, and the architecture
authority required to resume validation. LAT-US03 and every later story remain
Proposed pending separate requester confirmation and fresh readiness.
