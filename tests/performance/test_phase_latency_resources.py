"""Deterministic process-tree and complete-boundary resource contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_contracts import (
    LatencyAttempt,
    ProcessMetric,
    ProcessTreeMetrics,
    ProcessTreeSnapshot,
)
from tests.fixtures.phase_latency.factory import campaign, process_tree


def test_process_tree_retains_worker_descendant_peak_and_terminal_cleanup() -> None:
    metrics = process_tree()
    assert len(metrics.snapshots) >= 3
    active = next(
        snapshot for snapshot in metrics.snapshots if len(snapshot.members) > 1
    )
    assert [member.identity.role.value for member in active.members] == [
        "candidate_worker",
        "tesseract",
    ]
    assert metrics.peak_total_rss_bytes == 175
    assert metrics.peak_worker_hwm_bytes == 150
    assert len(metrics.snapshots[-1].members) == 1
    assert metrics.maximum_observed_gap_ns == 5_000_000


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("total_rss_bytes", 1, "recomputed"),
        ("total_user_cpu_ns", 1, "recomputed"),
        ("total_system_cpu_ns", 1, "recomputed"),
        ("total_thread_count", 1, "recomputed"),
        ("total_fd_count", 1, "recomputed"),
    ],
)
def test_process_snapshot_totals_are_recomputed(
    field: str,
    replacement: int,
    message: str,
) -> None:
    active = next(
        snapshot for snapshot in process_tree().snapshots if len(snapshot.members) > 1
    )
    value = active.model_dump(mode="json")
    value[field] = replacement
    with pytest.raises(ValidationError, match=message):
        ProcessTreeSnapshot.model_validate(value)


def test_process_identity_and_cadence_drift_fail_closed() -> None:
    value = process_tree().model_dump(mode="json")
    value["snapshots"][2]["members"][0]["identity"]["create_time_ns"] += 1
    with pytest.raises(ValidationError, match="identity changed"):
        ProcessTreeMetrics.model_validate(value)

    value = process_tree().model_dump(mode="json")
    for snapshot in value["snapshots"][2:]:
        snapshot["observed_monotonic_ns"] += 10_000_001
    value["maximum_observed_gap_ns"] = 15_000_001
    with pytest.raises(ValidationError, match="cadence exceeded"):
        ProcessTreeMetrics.model_validate(value)

    value = process_tree().model_dump(mode="json")
    value["peak_total_rss_bytes"] -= 1
    with pytest.raises(ValidationError, match="peak must be recomputed"):
        ProcessTreeMetrics.model_validate(value)


def test_descendant_hwm_is_unknown_not_invented_and_worker_hwm_is_required() -> None:
    active = next(
        snapshot for snapshot in process_tree().snapshots if len(snapshot.members) > 1
    )
    descendant = active.members[1].model_dump(mode="json")
    descendant["self_hwm_bytes"] = 25
    with pytest.raises(ValidationError, match="cannot be invented"):
        ProcessMetric.model_validate(descendant)

    worker = process_tree().snapshots[0].members[0].model_dump(mode="json")
    worker["self_hwm_bytes"] = None
    with pytest.raises(ValidationError, match="must be present"):
        ProcessMetric.model_validate(worker)


def test_process_snapshot_rejects_duplicate_or_noncanonical_descendants() -> None:
    active = next(
        snapshot for snapshot in process_tree().snapshots if len(snapshot.members) > 1
    )
    value = active.model_dump(mode="json")
    value["members"].append(deepcopy(value["members"][1]))
    value["total_rss_bytes"] += value["members"][1]["rss_bytes"]
    value["total_user_cpu_ns"] += value["members"][1]["user_cpu_ns"]
    value["total_system_cpu_ns"] += value["members"][1]["system_cpu_ns"]
    value["total_thread_count"] += value["members"][1]["thread_count"]
    value["total_fd_count"] += value["members"][1]["fd_count"]
    with pytest.raises(ValidationError, match="unique"):
        ProcessTreeSnapshot.model_validate(value)


def test_candidate_latency_is_bound_to_root_trace_through_complete_response() -> None:
    candidate = campaign().attempts[0]
    assert candidate.stage_trace is not None
    assert candidate.stage_trace.spans[-1].name.value == "api.response_build"
    assert candidate.diagnostic_total_latency_ns == (
        candidate.stage_trace.authoritative_total_ns
    )
    assert candidate.process_tree is not None
    assert candidate.total_latency_ns == (
        candidate.process_tree.request_ended_monotonic_ns
        - candidate.process_tree.request_started_monotonic_ns
    )

    value = candidate.model_dump(mode="json")
    value["total_latency_ns"] -= 1
    with pytest.raises(ValidationError, match="authoritative total"):
        LatencyAttempt.model_validate(value)


def test_process_samples_bind_request_and_terminal_threads_fds_and_children() -> None:
    value = process_tree().model_dump(mode="json")
    value["request_ended_monotonic_ns"] += 10_000_001
    with pytest.raises(ValidationError, match="terminal snapshot"):
        ProcessTreeMetrics.model_validate(value)

    value = process_tree().model_dump(mode="json")
    value["snapshots"][-1]["members"].append(
        deepcopy(
            next(
                snapshot
                for snapshot in value["snapshots"]
                if len(snapshot["members"]) > 1
            )["members"][1]
        )
    )
    child = value["snapshots"][-1]["members"][-1]
    for field, member_field in (
        ("total_rss_bytes", "rss_bytes"),
        ("total_user_cpu_ns", "user_cpu_ns"),
        ("total_system_cpu_ns", "system_cpu_ns"),
        ("total_thread_count", "thread_count"),
        ("total_fd_count", "fd_count"),
    ):
        value["snapshots"][-1][field] += child[member_field]
    value["peak_total_rss_bytes"] = max(
        snapshot["total_rss_bytes"] for snapshot in value["snapshots"]
    )
    with pytest.raises(ValidationError, match="no descendants"):
        ProcessTreeMetrics.model_validate(value)

    for field, message in (
        ("thread_count", "threads"),
        ("fd_count", "file descriptors"),
    ):
        value = process_tree().model_dump(mode="json")
        value["snapshots"][-1]["members"][0][field] += 1
        total_field = (
            "total_thread_count" if field == "thread_count" else "total_fd_count"
        )
        value["snapshots"][-1][total_field] += 1
        with pytest.raises(ValidationError, match=message):
            ProcessTreeMetrics.model_validate(value)
