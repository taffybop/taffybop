# LAT-US02 fork-denied worker and external Tesseract broker authorization

Status: **Requester-authorized for LAT-US02 implementation and local evidence**  
Date: 2026-08-10  
Decision owner: Requester

## Authorization

The requester explicitly authorized:

> Authorize a permanently fork-denied parser worker plus an external Tesseract
> broker with exact per-request wait4/CPU accounting and recursive
> process-quiescence checks for LAT-US02.

This direction authorizes the architecture expansion identified by
`LAT-US02-METRIC-CPU-001`. It supersedes the earlier lack-of-authorization
condition for this remedy only; it does not rewrite the historical blocker or
blocked handoff.

## Authorized boundary

The LAT-US02 implementation may add:

- a parser worker placed under a kernel-enforced permanent fork denial before
  parser or native dependency imports;
- one externally owned, one-to-one Tesseract broker as the sole parent of
  Tesseract jobs;
- gated child birth records, PID-reuse-safe native identities, exact one-time
  `wait4(exact_pid)` tombstones with integral CPU counters, and raw child HWM;
- request BEGIN/END admission barriers, exact worker and broker self counters,
  recursive quiescence, and external watchdog custody of worker, broker, and
  every released child; and
- private campaign instrumentation needed to compare brokered flag-off and
  flag-on paths symmetrically.

The parser supervisor and watchdog are control-plane components only. OCR
payload bytes must flow directly between the worker and its broker so their CPU
is not omitted from the request accounting boundary.

## Rollback and compatibility

The public feature flag remains default off. The required state matrix is:

1. flag off, no private evidence capability: execute the exact existing lazy
   parser path with no broker, supervisor client, or fork denial;
2. flag on, valid supervisor capability: use the fork-denied worker and broker;
3. flag on, absent or invalid capability: fail closed before readiness; and
4. flag off, private campaign capability: use broker instrumentation only for
   the symmetric local predecessor measurement.

Before paired brokered measurements, a separate brokerless flag-off run must
reproduce the retained output/error identity for every one of the 15 registered
cases. A mismatch stops the campaign. Therefore setting
`PARSER_LATENCY_PREWARM_ENABLED=false` remains the single production rollback;
campaign-only capability cannot silently redefine ordinary flag-off behavior.

## Platform and deployment limitation

The current evidence authority is restricted to the frozen non-root Darwin
host with exact Seatbelt, executable, runtime, artifact, dependency, broker,
supervisor, guard, and watchdog identities. `RLIMIT_NPROC=0` is not an
authoritative fork barrier for a root Linux container, and Darwin Seatbelt is
not available there. Enabled execution must reject unsupported or root
environments. The Docker default-off direct command remains unchanged; this
decision does not authorize generic container or production enablement.

## Gates that remain in force

- The local production campaign remains forbidden until focused/adversarial
  tests pass on frozen bytes and independent production/security and
  metrics/custody reviews both return GO with no Blocker or Major.
- Missing, rounded, late, reused, unmatched, contaminated, or incomplete CPU,
  lineage, wait, quiescence, watchdog, cleanup, artifact, or output evidence is
  blocking.
- Numerical RSS remains observational only under the separate scoped
  requester decision; leaks, growth, OOM, orphaning, and cleanup remain
  blocking, and no strict RSS pass may be claimed.
- No hosted LlamaParse call, production enablement, LAT-US03 work, later-story
  authority, Phase 04 execution, Phase 05 work, or phase-exit pass is granted.

LAT-US02 remains In Progress until the implementation, one permitted local
campaign, retained evidence, both reviews, final validation, and completion
record all pass.
