# LAT-US08 — Validate final latency flow and rollback

Status: **Proposed — paused for release-first Phase 04–08 delivery**  
Story points: 5  
Phase: Phase Latency — Latency Improvement  
Priority: Critical  
Dependencies: LAT-US07  
Feature flag: None — integrated functional validation and phase completion

## User story

As a release owner, I want the final latency flow validated end to end on
representative inputs, so that the production implementation can ship with a
working rollback while deeper qualification is deferred to hardening.

## In scope

- Final production-code and configuration review for the latency flow.
- Representative enabled end-to-end parsing across the main supported input
  and output paths.
- Focused functional tests, basic compile/static checks, public-contract smoke
  checks, lightweight latency/resource targets, default-off behavior, and
  reverse-order rollback.

## Out of scope

- Hosted performance campaigns, all-corpus qualification, exhaustive security,
  process-lineage/evidence-custody proof, sustained stress, and adversarial
  validation; these move to a later hardening phase.
- Production promotion, hosted customer traffic, Phase 04
  implementation/resumption, or Phase 05 work/status changes.

## Delivery validation policy

Completion is based on production readiness and basic integrated validation,
not a hosted or exhaustive qualification campaign. Representative flows must
succeed, public behavior and rollback must remain compatible, and lightweight
targets must show no obvious latency, memory, cleanup, or stability regression.
LlamaParse comparison, strict percentile/RSS gates, exhaustive evidence and
lineage proof, independent security/custody approval, and broad adversarial
coverage are explicitly deferred and are not represented as passed.

## Acceptance criteria

1. The final production code and configuration compile and pass the focused
   functional suite for the implemented latency features.
2. Representative PDF/image inputs complete through the enabled production
   flow and return compatible JSON and Markdown outputs.
3. A repeated request and a small bounded-concurrency flow complete without
   obvious cross-request state, duplicate responses, hangs, or cleanup leaks.
4. Basic malformed-input, timeout/cancellation, and worker-failure checks return
   compatible errors and leave the service usable.
5. Lightweight latency, memory, output-size, and queue checks remain within the
   configured basic targets; no hosted comparison or strict percentile claim is
   required.
6. All latency flags remain false by default, and reverse-order rollback
   restores the predecessor flow without residual latency-owned workers/state.
7. Known deferred hardening items and limitations are documented without being
   reported as validated or passed.

## Basic validation

- `tests/stories/phase_latency/test_lat_us08_phase_exit.py`
- Focused latency-feature tests and Python compilation/static checks for changed
  production modules.
- Representative enabled PDF/image JSON and Markdown end-to-end checks.
- Basic repeat, bounded-concurrency, malformed-input, timeout/cancellation,
  worker-failure, output-bound, default-off, and reverse-order rollback checks.

## Rollback

Disable all `PARSER_LATENCY_*` flags in reverse dependency order, drain and
terminate latency-owned workers, clear only request-scoped latency state, and
verify exact predecessor outputs/configuration. Production remains disabled.

## Definition of Done

Production code is complete and reviewed; the focused suite, compilation, and
representative integrated flows pass; basic compatibility, bounds, failure
handling, cleanup, default-off behavior, and rollback are confirmed; known
limitations are recorded; and no blocking functional defect remains. Deeper
security, performance, process-lineage, evidence/custody, all-corpus, stress,
and adversarial qualification remains deferred to a later hardening phase.
