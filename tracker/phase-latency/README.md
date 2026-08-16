# Phase Latency — Latency Improvement

Status: **LAT-US01/LAT-US02 Done with recorded deferrals; LAT-US03–LAT-US08 paused for release-first Phase 04–08 delivery**  
Stories: **8**  
Story points: **36**  
Execution authority: **Paused; resume only after the core release or a new requester decision**

Outcome: Improve production parser latency while preserving representative
end-to-end behavior and a clean rollback. Exhaustive comparative, security,
resource, lineage, evidence, and adversarial qualification is deferred to a
later hardening phase.

## Historical authorization and current pause

On 2026-08-08 the requester explicitly authorized `phase-latency` under the
[`authorization decision`](../decisions/2026-08-08-phase-latency-authorization.md)
as the sole
active workstream. The requester's later
[`story-confirmation decision`](../decisions/2026-08-08-phase-latency-story-confirmation-boundary.md)
requires completion and reporting of one story followed by an explicit
confirmation before the next story may start. Only one story may be In
Progress. LAT-US01 is Done under its exact scoped r34 owner exception. On
2026-08-10 the requester separately confirmed LAT-US02, and LAT-US02 passed its
fresh [10/10 Definition of Ready](evidence/LAT-US02-readiness.md). The requester
subsequently marked LAT-US02 Done after production implementation completed,
while explicitly deferring the remaining evidence migration, complete
validation, and one-shot campaign. LAT-US03 and every later latency story
remain Proposed. On 2026-08-10 the requester paused them so core Phases 04–08
can proceed first under
[`release-first-phases-04-08.md`](../release-first-phases-04-08.md).

LAT-US02 is administratively Done under an explicit requester-directed
validation deferral. No campaign or hosted run occurred, and no campaign GO,
candidate pass, phase pass, or production enablement is claimed. The
[blocked handoff](reports/LAT-US02-blocked-handoff.md) and independent reviews
remain the historical validation record; the feature remains default-off.

P04-US01 retains its completed readiness work and historical start and may now
resume under the release-first acceptance criteria. Phase Latency no longer
holds the active workstream. No production enablement is granted by this
administrative scheduling update.

## P03-US08 continuity boundary

The exact
[`phase-latency administrative continuity renewal`](decisions/LAT-P03-US08-latency-continuity-renewal.md)
preserves failed attempt 48 at `0.050946750` seconds against the unchanged
`0.050000000`-second ceiling, every unchanged ceiling, the maximum 5%
candidate-specific bound, strict-final absence, sealed attempt-55 history,
default-off rollback, and every non-waived gate. It is reviewable no later than
2026-09-02 and expires before production enablement or any relevant protected
running-region semantic/runtime/reachability/output/dependency/evidence/custody
change. It is not a strict metrics pass or production approval.

## Streamlined delivery policy for LAT-US03–LAT-US08

The remaining stories are complete when their production implementation is
reviewed, focused functional tests pass, representative enabled end-to-end
flows work within basic configured latency/resource targets, public behavior is
compatible, ordinary failure cleanup works, and default-off rollback is
confirmed. A known blocking functional defect still prevents completion.

The hosted LlamaParse campaign, all-corpus qualification, strict percentile and
RSS gates, exhaustive security/privacy and evidence-custody review, exact
process-lineage proof, sustained stress, and broad adversarial matrices are
deferred hardening. They remain useful future targets, but no longer block
LAT-US03–LAT-US08 and must not be described as passed without execution.

## Deferred benchmark reference

The sole latency source of truth is
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md)
under the controlling
[`2026-08-08 source-of-truth decision`](../decisions/2026-08-08-llamaparse-latency-source-of-truth.md):
LlamaCloud Parse v2, Agentic tier, cost optimizer off, cache disabled, and
provider-UI **Total Latency**.

The existing 15 values remain planning references, not p50/p95 evidence or a
pass. The previously designed hosted campaign is retained as a later hardening
option; it is not required for LAT-US03–LAT-US08 completion or phase delivery.

## Deferred strict resource qualification

The historical `67,108,864`-byte instrumentation-overhead ceiling and related
absolute/per-case resource gates remain documented hardening targets. For
LAT-US03–LAT-US08, completion uses lightweight representative memory, latency,
output-size, queue, and cleanup checks against the feature's configured basic
bounds. Strict RSS qualification and exhaustive resource accounting are not
required for story completion.

## LAT-US01 r34 non-RSS closure

The retained r34 profile and evaluation have been revalidated exactly, with
47/47 successful attempts, 94/94 successful role observations, complete
quality/output/custody and hosted-use-zero evidence, and no production
instrumentation. See the [non-RSS validation](evidence/LAT-US01-r34-non-rss-validation.md),
[production/security review](evidence/LAT-US01-r34-production-security-review.md),
[metrics/custody review](evidence/LAT-US01-r34-metrics-custody-review.md), and
[conditional completion record](reports/LAT-US01-non-rss-closure-r34.md).

LAT-US01 is **Done under the requester-approved scoped r34 owner exception**.
Its evaluation remains false for the local instrumentation-HWM gate; no RSS
conclusion has changed. See the
[exception decision](decisions/LAT-US01-r34-scoped-owner-exception.md). That
checkpoint did not itself authorize LAT-US02; the requester supplied separate
LAT-US02 confirmation on 2026-08-10.

## Stories and execution order

1. [LAT-US01](stories/LAT-US01.md) — Establish exact stage attribution and benchmark harness — 5 points — **Done — scoped r34 owner exception**
2. [LAT-US02](stories/LAT-US02.md) — Prewarm and safely reuse parser workers — 3 points — **Done — production implementation complete; validation/campaign deferred**
3. [LAT-US03](stories/LAT-US03.md) — Reuse immutable document evidence within a request — 5 points — Proposed
4. [LAT-US04](stories/LAT-US04.md) — Execute independent page and OCR work concurrently — 5 points — Proposed
5. [LAT-US05](stories/LAT-US05.md) — Reduce redundant output materialization — 3 points — Proposed
6. [LAT-US06](stories/LAT-US06.md) — Route optional work only from sufficient source evidence — 5 points — Proposed
7. [LAT-US07](stories/LAT-US07.md) — Bound parser concurrency and queue latency — 5 points — Proposed
8. [LAT-US08](stories/LAT-US08.md) — Validate final latency flow and rollback — 5 points — Proposed

Total: **8 stories, 36 story points**.

## Phase entry criteria

- Phases 00–03 remain Done; P03-US08 remains accurately exception-bound.
- The preceding story is Done and the next story's production scope and direct
  dependencies are understood.
- Representative inputs for the primary end-to-end flow are available.
- The default-off rollback boundary is recorded.
- The requester separately confirms the next story before implementation.

## Phase exit criteria

- Production code for the latency features is complete and reviewed.
- Focused functional tests and representative enabled PDF/image JSON and
  Markdown end-to-end flows pass.
- Reuse, bounded concurrency, output materialization, routing, and worker-pool
  behavior meet their basic functional targets without a known blocking defect.
- Representative ordinary error, timeout/cancellation, cleanup, and shutdown
  checks leave the service usable.
- Lightweight latency, memory, output-size, and queue checks stay within the
  configured basic targets.
- All latency flags are false by default and reverse-order rollback restores the
  predecessor flow without residual latency-owned state or workers.
- Deferred hardening limitations are recorded without claiming the hosted,
  security, strict-performance, lineage, evidence, stress, or adversarial gates
  passed.

## Product integrity boundary

The streamlined policy does not authorize intentionally changing public
behavior, fabricating content, discarding required work, disabling ordinary
error handling, or ignoring a known blocking functional defect. It changes the
amount of validation required for story completion; it does not represent
deferred hardening checks as passed.

## Phase documents

- [Ordered backlog](backlog.md)
- [Metrics contract](metrics.md)
- [Regression and exit plan](phase-regression.md)
- [LAT-US01 readiness](evidence/LAT-US01-readiness.md)
- [LAT-US02 readiness](evidence/LAT-US02-readiness.md)
- [LAT-US02 owner-directed numerical RSS deferral](decisions/LAT-US02-owner-directed-rss-deferral.md)
- [LAT-US02 CPU-lineage campaign blocker](evidence/LAT-US02-cpu-lineage-blocker.md)
- [LAT-US02 production/security review](evidence/LAT-US02-production-security-review.md)
- [LAT-US02 metrics/custody review](evidence/LAT-US02-metrics-custody-review.md)
- [LAT-US02 blocked handoff](reports/LAT-US02-blocked-handoff.md)
- [LAT-US01 r34 non-RSS closure](reports/LAT-US01-non-rss-closure-r34.md)
- [LAT-US01 r34 scoped owner exception](decisions/LAT-US01-r34-scoped-owner-exception.md)
- [P03-US08 latency continuity renewal](decisions/LAT-P03-US08-latency-continuity-renewal.md)
