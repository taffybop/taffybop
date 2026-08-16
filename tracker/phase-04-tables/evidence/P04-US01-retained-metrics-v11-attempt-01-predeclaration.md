# P04-US01 Retained Metrics v11 — Canonical Attempt 01 Predeclaration

Date: 2026-08-07  
Status: Predeclared; not yet executed  
Canonical lineage: first canonical attempt under the independently approved
v11/v7/v4 design; the sealed v6 and v10 attempts remain failed history

## Frozen final-code inputs

The required final-code surface contains exactly 70 files and 5,747,758 bytes.
Its ordered canonical identity-list SHA-256 is
`b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff`.
Key identities are:

| Input | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | 97,979 | `c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5` |
| `tests/fixtures/phase_04/tables/metrics.py` | 528,707 | `dd6434ca4998061505df99eee868ac524b676fd59c723f1f926bc0c2cdd7fcf0` |
| `tests/performance/test_p04_us01_rss_lane.py` | 31,707 | `5397cc5fceaef3681fb6b2347120bb72403fd334f7bb830a438732d09a65b2cd` |
| `tests/performance/test_p04_us01_table_metrics.py` | 377,525 | `edebf677ca4279268254ba56d91c5d7e10798fcb8be5d98fee4c0faec07882fd` |
| Conditional-reachability amendment | 6,920 | `48311606bd9922f1e0acb7aff702b00fc8979be41a2a76f4d64ff510031e98aa` |
| Conditional-reachability exact approval | 13,229 | `30243dd9bf9edf7d000f629e4407d0d04fff91d265e4e61b8f65966b99e9df36` |
| External-RSS exact approval | 9,320 | `944fc16be396af0f0c5170850848523a76381857d28cd6318f3d0492c364f9fe` |

The exact v11 schemas are report/projection/paired/quality
`p04-us01-table-metrics-v11`,
`p04-us01-final-metrics-semantic-projection-v11`,
`p04-us01-paired-performance-v10`, and
`p04-us01-quality-evidence-v7`. External attestation remains
`p04-us01-external-rss-monitor-attestation-v7`; full lane protocol custody
remains `p04-us01-current-rss-lane-protocol-custody-v4`; lane runtime remains
`p04-us01-current-rss-lane-runtime-v2`; and execution accounting remains
`p04-us01-execution-accounting-v3`.

The exact destination
`tracker/phase-04-tables/evidence/P04-US01-final-metrics.json` is absent before
this attempt.

## Pre-execution evidence and failed history

- Independent final-code review reports zero open Blocking, Major,
  correctness, security, custody, compatibility, performance/resource, or
  Phase-boundary findings.
- The exact dedicated lane gate passed 23 tests with one known warning. The
  complete ordinary metrics module passed 397, with two expected opt-in real-
  campaign skips, one pressure-candidate deselection, and one known warning.
  The post-approval custody slice passed 17.
- The unchanged v10 pressure candidate passed three fresh pressure executions;
  its result is 1,247 bytes with SHA-256
  `371419e038f7edbf7413e6c0df5837b33d330bb4e5810315744bc2ce231abed5`.
- The unchanged v10 real `postal-10k` smoke passed with 2,022 continuous
  samples, maximum RSS gap `1,936,500 ns`, full v7/v4 custody, empty
  diagnostics, and zero children. Its result is 2,621 bytes with SHA-256
  `c98829dbc1dc32eba013d1b36483802d9c56c4e05616eb6f9739d70cc219bfd6`.
  It remains noncanonical and is not a current v11 metrics pass.
- Canonical v6 attempt 01 remains sealed failed at
  `tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v6-attempt-01-failed.json`,
  3,700 bytes with SHA-256
  `216802979ba1be4fe153447b72fda480ab3d35fa47e877315f7aa30aff902d35`.
  It produced no final artifact and is not retried or relabelled.
- Canonical v10 attempt 01 also remains sealed failed. Its four-file chain is:
  predeclaration 3,805 bytes
  `817954f24d2de8fd8cf7a5729b6cc7336e97a8c33c1765930848acc52b87ecb7`;
  stderr 1,491 bytes / 27 lines
  `6601cf62fb95bc02fe8bb63aab953e81834abf866bc0c69d47678ca7fe471bd3`;
  failure record 2,085 bytes
  `061497f31d468421305d2a540d33180caa92597e232527c62cc8af3f82cebea0`;
  and component diagnostic 3,402 bytes
  `de793f8f5e8112b4c674207017ab92237c21adf9794ab524a3cb544de592fb72`.
  It produced no final artifact and is not retried or relabelled.
- The separately predeclared v11 two-execution candidate attempt 01 remains a
  real sealed failure. Its first flag-off execution failed before returning a
  snapshot at `32,442,083 ns` against the unchanged `10,000,000 ns` hard RSS
  gap after 783 accepted samples; the flag-on execution never began. Exact
  identities are predeclaration
  `eb97e4bea052952cb2376ed1b6c07a24e894f5bb94b5f22666381001820b3280`,
  stderr `4ab99fdacd99d006425ed836fe00fbe30e9491d070a117182ea66019180a1c05`,
  and failure record
  `a66ac11f925b634d11067bd33a7fb9b7a6d436bb12460accc610518900e89c85`.
  It is not rerun, discarded, waived, or represented as a pass.
- Independent post-failure custody/disposition review is 9,263 bytes with
  SHA-256
  `025c02dd8ce48721b901f56dbb0c0f4596251f4390eb8e337558aab1c9e6023d`.
  It infers, without claiming proof, that current contrary reproducibility
  evidence supports an intermittent host-scheduling observation rather than an
  identified v11 reachability or monitor regression. It allows only this
  separately predeclared canonical campaign with every gate unchanged.

The earlier ordinary `12,069,250 ns` cadence miss and the delayed-PREPARE
active-CPU failure also remain explicit failed history. No failure above is an
outlier to remove from a metric, a ceiling waiver, or current pass evidence.

## Exact command

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 P04_US01_RUN_REAL_METRICS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false .venv/bin/python -c '
import json
import sys
from tests.fixtures.phase_04.tables import metrics

expected_surface = {
    "file_count": 70,
    "total_bytes": 5747758,
    "identity_aggregate_sha256": "b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff",
}
expected_downstream_history = {
    "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v6-attempt-01-failed.json": {
        "size_bytes": 3700,
        "sha256": "216802979ba1be4fe153447b72fda480ab3d35fa47e877315f7aa30aff902d35",
    },
    "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-predeclaration.md": {
        "size_bytes": 3805,
        "sha256": "817954f24d2de8fd8cf7a5729b6cc7336e97a8c33c1765930848acc52b87ecb7",
    },
    "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-stderr.txt": {
        "size_bytes": 1491,
        "sha256": "6601cf62fb95bc02fe8bb63aab953e81834abf866bc0c69d47678ca7fe471bd3",
    },
    "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-failed.json": {
        "size_bytes": 2085,
        "sha256": "061497f31d468421305d2a540d33180caa92597e232527c62cc8af3f82cebea0",
    },
    "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v10-attempt-01-component-diagnostic.md": {
        "size_bytes": 3402,
        "sha256": "de793f8f5e8112b4c674207017ab92237c21adf9794ab524a3cb544de592fb72",
    },
    "tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-predeclaration.md": {
        "size_bytes": 11616,
        "sha256": "eb97e4bea052952cb2376ed1b6c07a24e894f5bb94b5f22666381001820b3280",
    },
    "tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-stderr.txt": {
        "size_bytes": 1249,
        "sha256": "4ab99fdacd99d006425ed836fe00fbe30e9491d070a117182ea66019180a1c05",
    },
    "tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-failed.json": {
        "size_bytes": 2647,
        "sha256": "a66ac11f925b634d11067bd33a7fb9b7a6d436bb12460accc610518900e89c85",
    },
    "tracker/phase-04-tables/evidence/P04-US01-conditional-reachability-candidate-v11-attempt-01-independent-review.md": {
        "size_bytes": 9263,
        "sha256": "025c02dd8ce48721b901f56dbb0c0f4596251f4390eb8e337558aab1c9e6023d",
    },
    "tracker/phase-04-tables/evidence/P04-US01-pressure-candidate-v10-attempt-01-result.md": {
        "size_bytes": 1247,
        "sha256": "371419e038f7edbf7413e6c0df5837b33d330bb4e5810315744bc2ce231abed5",
    },
    "tracker/phase-04-tables/evidence/P04-US01-current-v10-real-postal-smoke-result.md": {
        "size_bytes": 2621,
        "sha256": "c98829dbc1dc32eba013d1b36483802d9c56c4e05616eb6f9739d70cc219bfd6",
    },
}
final_path = metrics.WORKSPACE / metrics.FINAL_METRICS_RELATIVE_PATH
attempt_seals = tuple(
    metrics.WORKSPACE / path
    for path in (
        "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-failed.json",
        "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-stderr.txt",
        "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-result.md",
        "tracker/phase-04-tables/evidence/P04-US01-retained-metrics-v11-attempt-01-independent-review.md",
    )
)

def current_surface():
    identities = [
        metrics.file_identity(metrics.WORKSPACE, path)
        for path in metrics.required_final_code_paths()
    ]
    return {
        "file_count": len(identities),
        "total_bytes": sum(identity["size_bytes"] for identity in identities),
        "identity_aggregate_sha256": metrics._sha256_bytes(metrics._canonical_bytes(identities)),
    }

def current_downstream_history():
    return {
        path: metrics.file_identity(metrics.WORKSPACE, path)
        for path in expected_downstream_history
    }

def expected_downstream_identities():
    return {
        path: {"path": path, **identity}
        for path, identity in expected_downstream_history.items()
    }

if sys.flags.optimize != 0:
    raise RuntimeError("canonical attempt requires non-optimized Python")
if final_path.exists() or any(path.exists() for path in attempt_seals):
    raise RuntimeError("canonical attempt-01 destination or seal already exists")
starting_surface = current_surface()
if starting_surface != expected_surface:
    raise RuntimeError("canonical attempt starting final-code surface differs")
starting_downstream_history = current_downstream_history()
if starting_downstream_history != expected_downstream_identities():
    raise RuntimeError("canonical attempt starting failed-history custody differs")

exit_code = metrics.main([
    "--workspace",
    str(metrics.WORKSPACE),
    "--generate-retained-report",
])
if exit_code != 0:
    raise RuntimeError("canonical metrics CLI returned nonzero")
ending_surface = current_surface()
if ending_surface != starting_surface:
    raise RuntimeError("canonical attempt ending final-code surface differs")
ending_downstream_history = current_downstream_history()
if ending_downstream_history != starting_downstream_history:
    raise RuntimeError("canonical attempt ending failed-history custody differs")
if any(path.exists() for path in attempt_seals):
    raise RuntimeError("canonical attempt-01 seal appeared during successful execution")

report = metrics.validate_retained_metrics_artifact(
    metrics.WORKSPACE,
    require_terminal_approval=False,
    require_all_measurement_gates=True,
)
accounting = report["execution_accounting"]
expected_accounting = {
    "expected_worker_count": 36,
    "retained_worker_count": 36,
    "skipped_worker_count": 0,
    "unexpected_extra_worker_count": 0,
    "fresh_worker_process_count": 36,
    "fresh_outer_observer_process_count": 36,
    "fresh_current_rss_lane_process_count": 36,
    "expected_global_process_identity_count": 108,
    "fresh_global_process_identity_count": 108,
}
if any(accounting[key] != value for key, value in expected_accounting.items()):
    raise RuntimeError("canonical execution accounting differs")
if accounting["global_process_identities_distinct"] is not True:
    raise RuntimeError("canonical global process identities differ")
if report["schema_id"] != metrics.SCHEMA_ID:
    raise RuntimeError("canonical report schema differs")
if report["final_code_identity_aggregate_sha256"] != expected_surface["identity_aggregate_sha256"]:
    raise RuntimeError("canonical report final-code binding differs")
if report["retention"] != {
    "state": "preapproval",
    "terminal_approval_expected": True,
    "binding_basis": metrics.TERMINAL_APPROVAL_BINDING,
}:
    raise RuntimeError("canonical preapproval retention differs")
if (
    report["gates"]["all_measurement_gates_passed"] is not True
    or report["gates"]["terminal_approval_bound"] is not False
    or report["gates"]["all_passed"] is not False
):
    raise RuntimeError("canonical preapproval gates differ")
if report["warnings"] != 0 or report["skips"] != 0 or report["hosted_usage"] != metrics.HOSTED_USAGE:
    raise RuntimeError("canonical warnings, skips, or hosted use differ")
if any(
    len(record["flag_off_samples"]) != metrics.PAIR_COUNT
    or len(record["flag_on_samples"]) != metrics.PAIR_COUNT
    for record in report["paired_performance"].values()
):
    raise RuntimeError("canonical paired raw sample count differs")
if len(report["quality"]["enabled_samples"]) != len(metrics.QUALITY_CASES):
    raise RuntimeError("canonical quality execution count differs")

artifact_identity = metrics.file_identity(metrics.WORKSPACE, metrics.FINAL_METRICS_RELATIVE_PATH)
print(json.dumps({
    "artifact_identity": artifact_identity,
    "execution_accounting": {key: accounting[key] for key in expected_accounting},
    "failed_history_custody": ending_downstream_history,
    "final_code_surface": ending_surface,
    "gates": report["gates"],
    "hosted_usage": report["hosted_usage"],
    "retention": report["retention"],
    "schema_id": report["schema_id"],
    "semantic_identity": report["semantic_identity"],
    "skips": report["skips"],
    "warnings": report["warnings"],
}, sort_keys=True, separators=(",", ":")))
'
```

The wrapper calls the current `metrics.main` retained-report CLI exactly once.
It rejects optimized Python, a changed final-code surface, any changed or absent
sealed failed-history/disposition/contrary-evidence input, any existing fixed
artifact, or any existing canonical attempt-01 failure/result/review seal
before the first worker. After success it rechecks the same final-code and
downstream-history surfaces, rejects any newly appeared attempt seal, and
strictly validates the artifact, 36/108 accounting, raw-pair/quality counts,
preapproval retention, measurement gates, and zero warning/skip/hosted use
before exiting zero. Run this command once under the required macOS process-observation permission.
No network, hosted model, dependency change, threshold change, permission
bypass, process-observation adapter, or output-path override is permitted.

## Fixed campaign and mandatory gates

The campaign contains exactly 36 fresh executions:

- five alternating disabled/enabled pairs for each of `ny-timetable`,
  `postal-10k`, and `finance-10k` (30 executions); and
- one enabled quality execution for each of `catastrophe-recap`, `finance-10k`,
  `postal-10k`, `clinical-study`, `ny-timetable`, and `insurance-acord`
  (6 executions).

Execution accounting v3 must retain exactly 36 distinct workers, 36 distinct
outer observers, and 36 distinct current-RSS lanes: exactly 108 globally
distinct PID/create-time identities across all roles and executions. No
execution, pair, identity, sample, warning, skip, or failed observation may be
removed, duplicated, substituted, quantiled away, or rerun.

Every paired snapshot must retain exact v7/v4 custody, empty worker/observer/lane
diagnostics, zero observed worker children, unchanged `RUSAGE_CHILDREN`, exact
target-read accounting, QoS/GC/thread/descriptor restoration, bounded process-
group cleanup, start/end/output edges, and `repair_extraction` off versus
`budget_start` on first-boundary topology. Each enabled quality snapshot must
retain full `_validate_snapshot` custody and required enabled `budget_start`;
the retained terminal check does not separately require equality of its first-
boundary string. The five always-reachable components
must run in every state; all six enabled-only components must be zero off;
enabled `budget_start` is mandatory; the five transaction/authority/replay
components may be zero only when their production branches are not reached.
Component seconds and calls must sum exactly. Named-stage completeness remains
false and the paired whole-parser guard remains mandatory.

The unchanged empirical gates are:

- p50 and p95 paired named-stage overhead ratio no greater than `0.10` for
  every case;
- p50 and p95 paired whole-parser overhead ratio no greater than `0.10` for
  every case;
- maximum of all five nonnegative enabled-minus-disabled candidate-window RSS
  increments no greater than `67,108,864` bytes for every case, with signed
  deltas retained;
- 1 ms current-RSS target and 10 ms hard maximum gap on every execution;
- 25 ms child-observer target and 100 ms hard maximum gap on every execution;
- no more than 8,388,608 marked-table sidecar bytes per table and 67,108,864
  Phase 04 sidecar bytes per document, with zero flag-off markers and positive
  flag-on marked tables;
- the unchanged 0.500-second page and 5.000-second document deadlines;
- exact-cell, repeated-value, legitimate-span, header, multiline-row, bbox,
  provenance, representation, deterministic semantic, reviewed concern, dense
  scaling, malformed-input, output, serializer/API, default-off, rollback,
  security, compatibility, corpus, and source-custody gates; and
- exact zero warnings, zero skips, zero hosted requests/tokens/cost, zero
  unexpected diagnostics, and zero extra executions.

The operative P03-US08 administrative renewal remains exact: decision 10,226
bytes / `93b95e2d07b4e58a6f8f9a8ae43e587ec199d4fbaaeac4d59c8770702fd32504`;
closed classifier JSON 9,722 bytes /
`99ac85518d573cb64abd4127444e45d631e767ec8ee236104c389fc420619c41`;
and independent approval 7,297 bytes /
`d269fde349c48faf36a050156bb8e95c2541958d601b97b2f6d54436c462828e`.
It preserves attempt 48,
all ceilings, maximum 5% candidate-specific bound, default-off rollback, every
non-waived gate, review no later than 2026-09-02, and expiry before production
enablement or any relevant running-region behavior/custody change. This
campaign must not describe Phase 03 as a strict current-artifact metrics pass.

## Success and failure handling

Success requires zero command exit and atomic creation of exactly one strict
canonical `p04-us01-table-metrics-v11` artifact at the fixed destination. The
artifact must bind the exact 70-file surface, all 36 executions and 108 process
identities, exact raw samples and quality evidence, zero warning/skip/hosted
usage, every measurement gate true, and retention state `preapproval` with
terminal approval still required. It is not P04-US01 completion until a fresh
independent production/security and metrics/custody approval is bound without
rerunning the samples.

Any nonzero exit, cadence/RSS/latency/correctness/custody/resource/output gate
failure, or artifact absence is canonical v11 attempt 01 failed. It must be
sealed with exact terminal and final-artifact custody and this exact canonical
design cannot be silently retried. In particular, any recurrence of a cadence
miss stops further campaign progression for a fresh monitor/environment design
review; it is not excused by the earlier candidate or contrary passing runs.

Neither outcome starts P04-US02, marks P04-US01 Done, approves production or
hosted use, exits Phase 04, authorizes Phase 05, or changes any P03 result.
