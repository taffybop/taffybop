# P04-US01 Pressure Candidate v10 — Attempt 01 Predeclaration

Date: 2026-08-07  
Status: Predeclared; not yet executed  
Classification: candidate-specific diagnostic, not canonical retained metrics

## Frozen design identities

| Path | SHA-256 |
|---|---|
| `tests/fixtures/phase_04/tables/rss_lane.py` | `c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5` |
| `tests/fixtures/phase_04/tables/metrics.py` | `8fb8ef4b05229c587f480d803057ce8963c38ed3558f741fe6fd03e755ab89b6` |
| `tests/performance/test_p04_us01_rss_lane.py` | `5091a9d2db656ef7cedaaec36d31e8d5bf41fef1ea84653e876177b65e6f23ca` |
| `tests/performance/test_p04_us01_table_metrics.py` | `4a34b563b4325c5f8f7b668ec8326ce0a3a7cfbc739025c8cf7920b93ff7ec4d` |
| `tracker/phase-04-tables/decisions/P04-US01-external-rss-lane-final-code-amendment.md` | `d9fec8413ce90be41dd411c9a0ddb6394a7d9a39fd7fba3056e477d509b54739` |
| `tracker/phase-04-tables/evidence/P04-US01-external-rss-lane-final-code-amendment-independent-review.md` | `944fc16be396af0f0c5170850848523a76381857d28cd6318f3d0492c364f9fe` |

The independent exact-byte approval reports zero Blocking/Major findings. The
post-approval manifest/shrink/acyclic slice passed 13 tests with one known
Starlette deprecation warning. The ordinary noncandidate module passed 395,
with two expected real-campaign skips, this pressure candidate deselected, and
one known warning. The dedicated lane module passed 23 with the same warning.

## Exact command and acceptance

Run exactly once:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py::test_sustained_real_external_monitor_survives_controller_pressure
```

The candidate passes only if all three fresh real worker executions finish
under controller CPU pressure and the test returns one pass. Every run must
retain valid external attestation, at least 256 continuous RSS samples, the
unchanged 10 ms RSS and 100 ms child hard gaps, at least eight child samples,
zero observed children, unchanged child rusage, exact sampler/lane quiescence,
cleanup, 0.25 ms production observer switch interval, scheduler/GC restoration,
35 outer duplex exchanges, three distinct worker PID/create-time identities,
no FD or named-thread leak, empty worker diagnostics, and zero nonzero exits.

A failure is sealed as candidate attempt 01 and this exact design is not
silently retried. A pass is only candidate-specific pressure evidence: it does
not create a retained metrics artifact, a canonical campaign, a current metrics
pass, story completion, production approval, Phase 04 exit, or Phase 05
authorization.
