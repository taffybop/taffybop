# P04-US01 Retained Metrics v10 — Canonical Attempt 01 Predeclaration

Date: 2026-08-07  
Status: Predeclared; not yet executed  
Canonical lineage: first canonical attempt under the independently approved
v10/v7/v4 design; the sealed v6 attempt remains failed history

## Frozen inputs

The required final-code surface contains exactly 68 files and 5,717,874 bytes.
Its ordered canonical identity-list SHA-256 is
`c6c524e9aaac0300d5ad2f15f84c51c7b47ce106a0804f932e806d3c2a9e9eab`.
Key identities are:

| Input | SHA-256 |
|---|---|
| `tests/fixtures/phase_04/tables/rss_lane.py` | `c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5` |
| `tests/fixtures/phase_04/tables/metrics.py` | `8fb8ef4b05229c587f480d803057ce8963c38ed3558f741fe6fd03e755ab89b6` |
| `tests/performance/test_p04_us01_rss_lane.py` | `5091a9d2db656ef7cedaaec36d31e8d5bf41fef1ea84653e876177b65e6f23ca` |
| `tests/performance/test_p04_us01_table_metrics.py` | `4a34b563b4325c5f8f7b668ec8326ce0a3a7cfbc739025c8cf7920b93ff7ec4d` |
| Final-code amendment | `d9fec8413ce90be41dd411c9a0ddb6394a7d9a39fd7fba3056e477d509b54739` |
| Independent exact-byte approval | `944fc16be396af0f0c5170850848523a76381857d28cd6318f3d0492c364f9fe` |

The approval reports zero Blocking/Major findings. The dedicated lane gate
passed 23 tests. The complete ordinary noncandidate metrics module passed 395,
with two expected real-campaign skips, one pressure candidate deselected, and
one known warning. The single predeclared pressure candidate passed. The
noncanonical current-v10 real `postal-10k` enabled smoke passed with full v7/v4
attestation and empty diagnostics.

The exact destination
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json` is absent before
this attempt.

## Exact command

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 P04_US01_RUN_REAL_METRICS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false .venv/bin/python tests/fixtures/phase_04/tables/metrics.py --workspace /Users/vignesh/Downloads/taffybop --generate-retained-report
```

Run this command once under the required macOS process-observation permission.
No network or hosted-model use is permitted.

## Required result

The campaign contains exactly 36 fresh executions: five alternating disabled/
enabled pairs for each of `ny-timetable`, `postal-10k`, and `finance-10k`, plus
one enabled quality execution for each of the six reviewed cases. Execution
accounting v3 must retain exactly 108 globally distinct worker/observer/lane
PID/create-time identities.

Every correctness, exact-cell/span/header/bbox/provenance/representation,
default-off, rollback, serializer/API, deterministic, output, deadline,
resource, malformed-input, security, custody, offline/hosted-use, diagnostic,
paired latency, and paired RSS gate remains mandatory. Each case keeps five raw
pairs; no outlier or quantile removes the maximum paired RSS delta. The 10%
latency ceilings, `67,108,864`-byte paired RSS ceiling, 1 ms/10 ms RSS cadence,
25 ms/100 ms child cadence, 8 MiB per-table sidecar ceiling, and 64 MiB
per-document sidecar ceiling are unchanged.

Success requires zero command exit, atomic creation of one strict canonical
`p04-us01-table-metrics-v10` artifact at the fixed destination, complete v7/v4
attestation on every execution, zero unexpected diagnostics, all gates true,
and exact final-code identity custody. It still requires independent final
metrics/custody approval before story completion.

Failure requires no final artifact and a sealed attempt-01 failure record. This
exact design/campaign is not silently retried. Neither outcome may describe
Phase 03 as a strict current-artifact metrics pass. This predeclaration does not
complete P04-US01, start P04-US02, approve production, exit Phase 04, or
authorize Phase 05.
