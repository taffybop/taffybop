# P04-US01 Conditional-Reachability Candidate v11 Attempt 01 Predeclaration

Date: 2026-08-07  
Status: Predeclared; not yet executed  
Classification: noncanonical, non-retained, two-execution reviewed-document
candidate  
Execution order: `ny-timetable` flag off, then `ny-timetable` flag on

## Frozen authority and inputs

The required final-code surface contains exactly 70 files and 5,747,758 bytes.
Its ordered canonical identity-list SHA-256 is
`b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff`.
Key exact identities are:

| Input | Size (bytes) | SHA-256 |
| --- | ---: | --- |
| `tests/fixtures/phase_04/tables/rss_lane.py` | 97,979 | `c07133c0bddf3c748303923aedd01ef4a63df2f5a90f6f5ce2c8f680eb98f0b5` |
| `tests/fixtures/phase_04/tables/metrics.py` | 528,707 | `dd6434ca4998061505df99eee868ac524b676fd59c723f1f926bc0c2cdd7fcf0` |
| `tests/performance/test_p04_us01_rss_lane.py` | 31,707 | `5397cc5fceaef3681fb6b2347120bb72403fd334f7bb830a438732d09a65b2cd` |
| `tests/performance/test_p04_us01_table_metrics.py` | 377,525 | `edebf677ca4279268254ba56d91c5d7e10798fcb8be5d98fee4c0faec07882fd` |
| Conditional-reachability amendment | 6,920 | `48311606bd9922f1e0acb7aff702b00fc8979be41a2a76f4d64ff510031e98aa` |
| Conditional-reachability independent approval | 13,229 | `30243dd9bf9edf7d000f629e4407d0d04fff91d265e4e61b8f65966b99e9df36` |
| External-RSS independent approval | 9,320 | `944fc16be396af0f0c5170850848523a76381857d28cd6318f3d0492c364f9fe` |

Independent v11 review reports zero Blocking, Major, correctness, security,
custody, compatibility, performance/resource, or Phase-boundary findings. The
final-code lane gate passed 23 tests; the exact ordinary metrics module passed
397, with two expected opt-in real-campaign skips, one pressure-candidate
deselection, and one known warning. The post-approval custody slice passed 17.

The sealed v10 attempt 01, its exact component diagnostic, and the recorded
pre-approval ambient CPU/cadence failures remain failed history. No threshold,
cadence, formula, or gate changed. The retained final metrics destination is
absent before this candidate.

## Exact command

Run this command once with required macOS process-observation permission:

```text
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false .venv/bin/python -c '
import json
import sys
from tests.fixtures.phase_04.tables import metrics

case_id = "ny-timetable"
final_path = metrics.WORKSPACE / metrics.FINAL_METRICS_RELATIVE_PATH
expected_final_code_surface = {
    "file_count": 70,
    "total_bytes": 5747758,
    "identity_aggregate_sha256": "b4da1b818f0acfa1b3c1ef527861699bceae2869a8c06b19b21dc9ee962f7cff",
}

def final_code_surface():
    paths = metrics.required_final_code_paths()
    identities = [metrics.file_identity(metrics.WORKSPACE, path) for path in paths]
    return {
        "file_count": len(identities),
        "total_bytes": sum(identity["size_bytes"] for identity in identities),
        "identity_aggregate_sha256": metrics._sha256_bytes(metrics._canonical_bytes(identities)),
    }

if sys.flags.optimize != 0:
    raise RuntimeError("candidate requires non-optimized Python assertions")
starting_final_code_surface = final_code_surface()
if starting_final_code_surface != expected_final_code_surface:
    raise RuntimeError("candidate starting final-code surface differs")
assert not final_path.exists()
off = metrics.fresh_snapshot(metrics.WORKSPACE, case_id, False)
on = metrics.fresh_snapshot(metrics.WORKSPACE, case_id, True)
metrics._validate_snapshot(off, case_id=case_id, enabled=False)
metrics._validate_snapshot(on, case_id=case_id, enabled=True)

for component in metrics.TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS:
    assert off["table_stage_components"][component]["call_count"] >= 1
    assert on["table_stage_components"][component]["call_count"] >= 1
for component in metrics.TABLE_STAGE_ENABLED_ONLY_COMPONENTS:
    assert off["table_stage_components"][component] == {"elapsed_seconds": 0.0, "call_count": 0}
for component in metrics.TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS:
    assert on["table_stage_components"][component]["call_count"] >= 1
for component in metrics.TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS:
    assert on["table_stage_components"][component] == {"elapsed_seconds": 0.0, "call_count": 0}
assert off["marked_table_count"] == 0
assert on["marked_table_count"] > 0
assert off["maximum_marked_table_bytes"] == off["document_sidecar_bytes"] == 0
assert on["maximum_marked_table_bytes"] <= metrics.TABLE_LIMITS["maximum_table_sidecar_bytes"]
assert on["document_sidecar_bytes"] <= metrics.TABLE_LIMITS["maximum_phase04_sidecars_per_document_bytes"]
assert off["phase04_stage_rss_first_boundary_component"] == "repair_extraction"
assert on["phase04_stage_rss_first_boundary_component"] == "budget_start"

stage_delta = max(0.0, on["table_stage_seconds"] - off["table_stage_seconds"])
stage_ratio = stage_delta / off["wall_seconds"]
whole_delta = max(0.0, on["wall_seconds"] - off["wall_seconds"])
whole_ratio = whole_delta / off["wall_seconds"]
rss_delta = max(0, on["phase04_stage_peak_rss_increment_bytes"] - off["phase04_stage_peak_rss_increment_bytes"])
assert stage_ratio <= metrics.TABLE_LIMITS["maximum_table_stage_p95_overhead_ratio"]
assert whole_ratio <= metrics.TABLE_LIMITS["maximum_table_stage_p95_overhead_ratio"]
assert rss_delta <= metrics.TABLE_LIMITS["maximum_peak_rss_delta_bytes"]

def bounded_state(snapshot):
    attestation = snapshot["external_rss_monitor_attestation"]
    lane = attestation["observer_runtime"]["current_rss_lane"]
    resource = lane["runtime"]["resource"]
    diagnostics = snapshot["worker_diagnostics"]
    identities = [
        [snapshot["phase04_stage_rss_worker_pid"], snapshot["phase04_stage_rss_process_create_time_ns"]],
        [attestation["observer_process"]["pid"], attestation["observer_process"]["process_create_time_ns"]],
        [lane["identity"]["pid"], lane["identity"]["process_create_time_ns"]],
    ]
    assert snapshot["phase04_stage_rss_continuous_maximum_gap_ns"] <= metrics.PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
    assert snapshot["phase04_stage_child_observer_continuous_maximum_gap_ns"] <= metrics.PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    assert snapshot["phase04_stage_rss_child_processes_observed"] == 0
    assert snapshot["phase04_stage_children_rusage_unchanged"] is True
    assert diagnostics["stdout"]["size_bytes"] == diagnostics["stderr"]["size_bytes"] == 0
    assert resource["active_cpu_duration_ns"] <= metrics.rss_lane.ACTIVE_CPU_FIXED_SLACK_NS + resource["active_wall_duration_ns"] * metrics.rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM // 1000000
    return {
        "enabled": snapshot["enabled"],
        "wall_seconds": snapshot["wall_seconds"],
        "table_stage_seconds": snapshot["table_stage_seconds"],
        "table_stage_call_count": snapshot["table_stage_call_count"],
        "table_stage_components": snapshot["table_stage_components"],
        "first_rss_boundary_component": snapshot["phase04_stage_rss_first_boundary_component"],
        "marked_table_count": snapshot["marked_table_count"],
        "phase04_stage_peak_rss_increment_bytes": snapshot["phase04_stage_peak_rss_increment_bytes"],
        "phase04_stage_current_rss_baseline_bytes": snapshot["phase04_stage_current_rss_baseline_bytes"],
        "phase04_stage_current_rss_peak_bytes": snapshot["phase04_stage_current_rss_peak_bytes"],
        "phase04_stage_current_rss_end_bytes": snapshot["phase04_stage_current_rss_end_bytes"],
        "rss_maximum_gap_ns": snapshot["phase04_stage_rss_continuous_maximum_gap_ns"],
        "rss_continuous_sample_count": snapshot["phase04_stage_rss_continuous_sample_count"],
        "rss_synchronous_sample_count": snapshot["phase04_stage_rss_synchronous_sample_count"],
        "child_maximum_gap_ns": snapshot["phase04_stage_child_observer_continuous_maximum_gap_ns"],
        "child_sample_count": snapshot["phase04_stage_child_observer_sample_count"],
        "child_boundary_count": snapshot["phase04_stage_child_boundary_check_count"],
        "maximum_marked_table_bytes": snapshot["maximum_marked_table_bytes"],
        "document_sidecar_bytes": snapshot["document_sidecar_bytes"],
        "worker_diagnostic_bytes": diagnostics["stdout"]["size_bytes"] + diagnostics["stderr"]["size_bytes"],
        "attestation_schema_id": attestation["schema_id"],
        "lane_protocol_schema_id": lane["protocol"]["schema_id"],
        "lane_runtime_schema_id": lane["runtime"]["schema_id"],
        "lane_exchange_count": lane["protocol"]["exchange_count"],
        "lane_duplex_bytes": lane["protocol"]["duplex_bytes"],
        "lane_compressed_bytes": lane["protocol"]["duplex_compressed_bytes"],
        "lane_active_wall_ns": resource["active_wall_duration_ns"],
        "lane_active_cpu_ns": resource["active_cpu_duration_ns"],
        "lane_active_cpu_duty_ppm": resource["active_cpu_duty_ppm"],
        "process_identities": identities,
    }

states = [bounded_state(off), bounded_state(on)]
all_identities = [tuple(identity) for state in states for identity in state["process_identities"]]
assert len(all_identities) == len(set(all_identities)) == 6
assert not final_path.exists()
ending_final_code_surface = final_code_surface()
if ending_final_code_surface != starting_final_code_surface:
    raise RuntimeError("candidate ending final-code surface differs")
print(json.dumps({
    "candidate_id": "p04-us01-conditional-reachability-v11-attempt-01",
    "schema_id": metrics.SCHEMA_ID,
    "case_id": case_id,
    "execution_order": ["flag_off", "flag_on"],
    "stage_delta_seconds": stage_delta,
    "stage_overhead_ratio": stage_ratio,
    "whole_parser_delta_seconds": whole_delta,
    "whole_parser_overhead_ratio": whole_ratio,
    "paired_rss_delta_bytes": rss_delta,
    "globally_distinct_process_identity_count": len(set(all_identities)),
    "final_code_surface": ending_final_code_surface,
    "states": states,
    "all_candidate_gates_passed": True,
}, sort_keys=True, separators=(",", ":")))
'
```

No network or hosted-model use is permitted. The command writes no evidence or
retained metrics file; its bounded stdout and terminal result must be transcribed
afterward with the predeclaration's exact identity.

## Required outcome and sealing rule

Pass requires zero exit; an exact v11 snapshot for each state; the five
always-reachable hooks in both states; all six enabled-only hooks exactly zero
off; enabled `budget_start`; all five conditional transaction/authority/replay
hooks exactly zero on; exact component sums/counts; non-optimized Python;
identical start/end binding to the predeclared 70-file final-code surface;
zero/positive off/on marked-table counts; exact first RSS boundary
`repair_extraction` off and `budget_start` on; full v7/v4 validation;
unchanged 10 ms RSS and 100 ms child gaps; zero children; unchanged child
rusage; empty diagnostics; six globally distinct worker/observer/lane
identities; unchanged 10% single-pair stage and whole-parser ceilings; unchanged
67,108,864-byte paired RSS ceiling; unchanged sidecar/resource gates; and no
retained final artifact.

Any nonzero exit or assertion failure is sealed as candidate v11 attempt 01 and
this exact design is not silently retried. A pass remains only a two-execution,
one-case candidate. It cannot replace the canonical three-case five-pair plus
quality campaign, retained final metrics, terminal metrics/custody approval,
P04-US01 completion, Phase 04 exit, production enablement, or Phase 05
authorization.
