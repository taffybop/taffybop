# LAT-US02 owner-directed numerical RSS deferral

Status: **Requester-directed; operative only for LAT-US02**  
Date: 2026-08-10  
Decision owner: Requester

## Decision

For the default-off LAT-US02 implementation, numerical RSS measurements are
observational and the strict `67,108,864`-byte diagnostic-versus-authoritative
worker self-HWM threshold is not a LAT-US02 completion blocker. LAT-US02 must
retain cold-initialization, prewarmed-idle, request-peak, repeated-request, and
shutdown RSS values, but it must record `strict_rss_gate_pass_claimed=false`
and must not describe the 64 MiB gate as passed.

This direction does not alter the retained LAT-US01 r34 evaluation. That
evaluation remains `passed=false` solely for
`diagnostic_hwm_delta_exceeded`, including all five retained over-ceiling
pairs. It also does not change the numerical threshold itself.

## Reliability gates that remain blocking

Memory leaks, unbounded growth, OOM, failed cleanup, orphaned workers or
initializer threads, unsafe resource admission, cross-request state retention,
and process/thread/file-descriptor growth remain blocking failures. CPU,
process ownership, timeout, cancellation, shutdown, correctness, quality,
security, custody, compatibility, output, and rollback evidence also remain
independent and blocking.

Measurements may not be retried or selectively discarded to obtain a
favorable value. Every failed, timed-out, cancelled, or incomparable attempt
must remain in the LAT-US02 evidence denominator.

## Non-transfer and expiry

This deferral applies only to LAT-US02 while
`PARSER_LATENCY_PREWARM_ENABLED` remains false by default. It does not apply to
LAT-US03 or any later story, Phase 04, production enablement, the final hosted
LlamaParse campaign, LAT-US08 qualification, or phase exit. Those boundaries
retain their strict independently applicable RSS and resource requirements.

Rollback remains:

```text
PARSER_LATENCY_PREWARM_ENABLED=false
```
