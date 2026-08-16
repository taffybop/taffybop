# P04-US01 Pressure Candidate v10 — Attempt 01 Result

Date: 2026-08-07  
Status: **PASS — candidate-specific only**  
Canonical/retained status: none

Predeclaration: `P04-US01-pressure-candidate-v10-attempt-01-predeclaration.md`  
Predeclaration size: 2,605 bytes  
Predeclaration SHA-256: `ca1dac38049f0495e2394cf04483948eed15833a443fc11eb9d969b9beb11bac`

Exact command:

```text
.venv/bin/pytest -q tests/performance/test_p04_us01_table_metrics.py::test_sustained_real_external_monitor_survives_controller_pressure
```

Exact result: `1 passed, 1 warning in 9.12s`; exit code `0`.

The warning was the already documented Starlette `httpx` TestClient
deprecation warning. The test completed all three predeclared fresh-worker
executions and therefore satisfied every assertion listed in the immutable
predeclaration: unchanged RSS/child cadence limits, minimum sample counts,
zero children, unchanged child rusage, full v7/v4 attestation, exact cleanup,
0.25 ms observer switch interval, scheduler/GC restoration, distinct worker
identities, and no FD/thread/diagnostic leak.

No final metrics file, retained campaign, canonical pass, story completion,
production approval, Phase 04 exit, or Phase 05 authorization was created or
claimed.
