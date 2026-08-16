# LAT-US02 blocked handoff — CPU lineage authority required

Date: 2026-08-10  
Story status: **In Progress — blocked before the production local campaign**  
Feature flag: `parser.latency.prewarm.enabled` (default off)  
Production enablement: **Not authorized**

## Outcome

LAT-US02's default-off prewarm lifecycle, ownership, artifact/dependency
validation, readiness, unavailable behavior, reuse, shutdown, rollback, and
compatibility implementation is present on frozen application identity
`4c75f9384e298a65adab275ec3a12df8088af2db84064e1a99c3e9931f4a53ed`.
The hardened campaign controller's non-CPU security and custody findings are
fixed and independently revalidated.

The story is **not Done**. Major `LAT-US02-METRIC-CPU-001` prevents the required
one-shot local enabled/predecessor campaign because Darwin cannot provide
complete native descendant CPU lineage under the approved architecture. See
the [blocker](../evidence/LAT-US02-cpu-lineage-blocker.md),
[production/security review](../evidence/LAT-US02-production-security-review.md),
and [metrics/custody review](../evidence/LAT-US02-metrics-custody-review.md).

## Validation retained

- LAT-US02 controller/contract matrix: **165 passed**, one existing Starlette
  deprecation warning; focused production-adapter suite: **62 passed**.
- Frozen production implementation plus API/image/schema coverage: **106
  passed**, one existing warning; additional affected API coverage: **107
  passed**, one existing warning.
- Earlier dedicated LAT-US02 contract/lifecycle coverage reached **54 passed**
  after the shutdown-cancellation regression; those tests are included in the
  later combined matrix.
- Python compilation passed for the production lifecycle and all frozen
  campaign-controller sources.
- A complete backend run, performed because application identity changed from
  the historical report, ended **4,908 passed, 29 skipped, 55 failed, 171
  warnings** in `2,009.13` seconds. It is not represented as green. Failures
  cluster in historical exact-code/evidence/status/API pins invalidated by
  unrelated/future-phase workspace changes, outer-sandbox Unix-socket/process
  controls, loaded performance thresholds, and one unrelated Phase 04
  recursion/resource case. No such failure is used to waive the CPU Major.
- Frontend was not rerun because no frontend-consumed surface changed. The
  attachment's `105` count is not workspace-backed; the persisted Phase 03 exit
  report records **106/106** frontend unit checks and **22/22** responsive
  checks for its historical identity.

## Campaign and metric disposition

- Production local campaign attempts: **0**
- Hosted LlamaParse calls/credits/egress: **0**
- LAT-US02 latency p50/p95: **not measured**
- LAT-US02 five-phase RSS: **not measured**
- Strict `67,108,864`-byte RSS pass: **not claimed**
- No retry, selection, or discarded attempt exists.

The requester-approved RSS treatment remains recorded and non-transferable,
but it cannot waive CPU lineage, leaks, OOM, growth, orphaning, cleanup, or
state-retention controls.

## Rollback and scope boundary

Rollback remains `PARSER_LATENCY_PREWARM_ENABLED=false`; the flag is still
default-off and production is not enabled. The approved artifact tree was not
mutated. LAT-US01 retained evidence remains sealed and unchanged.

No external broker, privileged EndpointSecurity service, VM/container
accounting boundary, process pool, or LAT-US03 work was started. Any such CPU
authority is a material architecture expansion and requires explicit requester
direction before work resumes.

LAT-US03 and every later story remain Proposed.
