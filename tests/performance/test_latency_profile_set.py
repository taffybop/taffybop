"""Synthetic mutation gates for the closed LAT-US01 candidate profile set."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.benchmarks import latency_runner
from tests.benchmarks.latency_contracts import (
    ArtifactIdentity,
    AttemptSlot,
    AttemptStatus,
    CacheStateEvidence,
    ConfigurationIdentity,
    FailureCode,
    FailureRecord,
    FailureType,
    InstrumentationManifest,
    LatencyAttempt,
    OutputIdentity,
    PrewarmEvidence,
    ProcessTreeMetrics,
    SourceIdentity,
    StageName,
    StageStatus,
    SystemName,
    WorkerExecutionEvidence,
    WorkerFatalEnvelope,
    WorkerLifecycle,
    WorkerResourceBoundaryEvidence,
    canonical_model_bytes,
    configuration_identity_sha256,
)
from tests.benchmarks.latency_instrumentation import root_only_trace
from tests.benchmarks.latency_profile_set import (
    CASE_ORDER,
    CURRENT_RUNTIME_OUTPUT_IDENTITIES,
    HARNESS_PATHS,
    M0_CASE_HWM_BYTES,
    OBSERVER_HARNESS_PATHS,
    P00_OUTPUT_IDENTITIES,
    SOURCE_CUSTODY,
    ActiveSlotEvent,
    CandidateExecutionIdentity,
    CandidateProfileAttemptLedger,
    CandidateProfileCase,
    CandidateProfileSet,
    ConcurrentAggregateSnapshot,
    ConcurrentBatchEvidence,
    ConcurrentRoundEvidence,
    ConcurrentWorkerGroupMetric,
    ConcurrentWorkerInterval,
    P00QualityEvidence,
    append_attempt_observation,
    append_controller_failure,
    append_role_observation,
    candidate_profile_execution_id,
    candidate_profile_ledger_payload_sha256,
    evaluate_candidate_profile_set,
    finalize_ledger,
    initial_candidate_profile_attempt_ledger,
    next_candidate_profile_execution_id,
    seal_candidate_profile_attempt_ledger,
)
from tests.fixtures.phase_latency import factory

SHA_A = "a" * 64
SHA_B = "b" * 64
CANDIDATE_CODE_SHA256 = "1" * 64
PYPROJECT_SHA256 = "2" * 64
DEPENDENCY_LOCK_SHA256 = "3" * 64
MODEL_ARTIFACTS_SHA256 = "4" * 64
_OPEN_LEDGER: CandidateProfileAttemptLedger | None = None


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _source(case_id: str) -> SourceIdentity:
    sha256, size_bytes, page_count = SOURCE_CUSTODY[case_id]
    return SourceIdentity(
        case_id=case_id,
        path=f"benchmark-expertmodeldata/{case_id}.pdf",
        filename=f"{case_id}.pdf",
        sha256=sha256,
        size_bytes=size_bytes,
        page_count=page_count,
    )


def _external_tree(
    *,
    hwm_bytes: int,
    root_pid: int,
    lifecycle: WorkerLifecycle,
    total_ns: int = 20_000_000,
) -> ProcessTreeMetrics:
    return factory.process_tree_v2(
        total_ns,
        root_pid=root_pid,
        worker_hwm_bytes=hwm_bytes,
        tracker_preexisting=(
            lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
        ),
    )


def _configuration(
    *,
    lifecycle: WorkerLifecycle,
    output_format: str,
    bounded_concurrency: int,
    environment_sha256: str,
) -> ConfigurationIdentity:
    payload = factory.configuration(SystemName.CANDIDATE).model_dump(mode="python")
    payload.update(
        output_format=output_format,
        worker_lifecycle=lifecycle,
        bounded_concurrency=bounded_concurrency,
        runtime_sha256=environment_sha256,
        model_artifacts_sha256=MODEL_ARTIFACTS_SHA256,
    )
    if lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED:
        payload.update(
            prewarm_completed_before_request=True,
            internal_reuse_state="prewarmed_before_request",
            pipeline_import_state_at_request_start="loaded_by_controlled_prewarm",
            engine_cache_state_at_request_start="prewarmed_process_cache",
        )
    else:
        payload.update(
            prewarm_completed_before_request=False,
            internal_reuse_state="process_engine_cache_empty_at_request_start",
            pipeline_import_state_at_request_start="not_loaded",
            engine_cache_state_at_request_start=(
                "module_not_loaded_process_cache_empty"
            ),
        )
    payload["system_configuration_sha256"] = configuration_identity_sha256(payload)
    return ConfigurationIdentity.model_validate(payload)


def _manifest(
    *,
    observer_files: tuple[ArtifactIdentity, ...],
    environment_sha256: str,
    dependency_sha256: str,
) -> InstrumentationManifest:
    payload = factory.instrumentation_manifest().model_dump(mode="json")
    payload.update(
        harness_files=[item.model_dump(mode="json") for item in observer_files],
        runtime_sha256=environment_sha256,
        dependency_lock_sha256=dependency_sha256,
    )
    payload["manifest_sha256"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "manifest_sha256"}
    )
    return InstrumentationManifest.model_validate(payload)


def _cache_state(*, case_id: str, prewarmed: bool) -> CacheStateEvidence:
    common = {
        "application_startup_completed": True,
        "converter_cache_entries_after_request": 1,
        "content_result_cache_observed": False,
        "content_result_cache_proof_sha256": SHA_A,
        "filesystem_cache_state": "uncontrolled_shared_host_cache",
    }
    if not prewarmed:
        return CacheStateEvidence(
            **common,
            profile="request_cold_after_app_startup",
            pipeline_loaded_at_request_start=False,
            converter_cache_entries_at_request_start=0,
            prewarm_request_completed=False,
            prewarm_evidence=None,
        )
    control_case = "clean-energy" if case_id != "clean-energy" else "catastrophe-recap"
    expected_sha = CURRENT_RUNTIME_OUTPUT_IDENTITIES[control_case][0]
    return CacheStateEvidence(
        **common,
        profile="request_prewarmed_after_app_startup",
        pipeline_loaded_at_request_start=True,
        converter_cache_entries_at_request_start=1,
        prewarm_request_completed=True,
        prewarm_evidence=PrewarmEvidence(
            policy="separate-pinned-route-equivalent-source-v1",
            source=_source(control_case),
            output=OutputIdentity(
                sha256=expected_sha,
                semantic_sha256=expected_sha,
                size_bytes=1,
                media_type="application/json",
                validation="ParseResult",
                semantic_exclusions=("/processing/duration_ms",),
            ),
            duration_ns=1_000_000,
            worker_self_cpu_ns=500_000,
            reaped_children_cpu_ns=0,
            worker_process_lifetime_hwm_bytes=100,
            reaped_children_process_lifetime_hwm_bytes=0,
            content_result_cache_observed=False,
        ),
    )


def _output(case_id: str, *, output_format: str) -> OutputIdentity:
    semantic_json, markdown, markdown_size = CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id]
    if output_format == "markdown":
        return OutputIdentity(
            sha256=markdown,
            semantic_sha256=markdown,
            size_bytes=markdown_size,
            media_type="text/markdown",
            validation="Markdown",
            semantic_exclusions=(),
        )
    return OutputIdentity(
        sha256=SHA_B,
        semantic_sha256=semantic_json,
        size_bytes=100,
        media_type="application/json",
        validation="ParseResult",
        semantic_exclusions=("/processing/duration_ms",),
    )


def _attempt(
    *,
    case_id: str,
    label: str,
    order_index: int,
    bounded_concurrency: int,
    environment_sha256: str,
    dependency_sha256: str,
    manifest: InstrumentationManifest,
    execution_number: int = 1,
    status: AttemptStatus = AttemptStatus.SUCCESS,
    authoritative_hwm: int | None = None,
    diagnostic_hwm: int | None = None,
) -> LatencyAttempt:
    output_format = "markdown" if label.endswith("markdown") else "json"
    lifecycle = (
        WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
        if label == "prewarmed-json"
        else WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
    )
    slot_id = f"{case_id}-{label}"
    base = factory.attempt(
        AttemptSlot(
            slot_id=slot_id,
            order_index=order_index,
            case_id=case_id,
            pair_index=1,
            system=SystemName.CANDIDATE,
        ),
        total_ns=20_000_000,
        status=status,
        v2_resource_lifecycle=True,
    )
    payload = base.model_dump(mode="python")
    payload.update(
        attempt_id=candidate_profile_execution_id(slot_id, execution_number),
        source=_source(case_id),
        configuration=_configuration(
            lifecycle=lifecycle,
            output_format=output_format,
            bounded_concurrency=bounded_concurrency,
            environment_sha256=environment_sha256,
        ),
        candidate_code_sha256=CANDIDATE_CODE_SHA256,
        dependency_lock_sha256=dependency_sha256,
        environment_sha256=environment_sha256,
        model_artifacts_sha256=MODEL_ARTIFACTS_SHA256,
    )
    if status is AttemptStatus.SUCCESS:
        auth_hwm = authoritative_hwm or M0_CASE_HWM_BYTES[case_id]
        diag_hwm = diagnostic_hwm or auth_hwm
        authoritative_tree = _external_tree(
            hwm_bytes=auth_hwm,
            root_pid=10_000 + order_index,
            lifecycle=lifecycle,
        )
        diagnostic_tree = _external_tree(
            hwm_bytes=diag_hwm,
            root_pid=20_000 + order_index,
            lifecycle=lifecycle,
        )
        tracker_preexisting = (
            lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED
        )
        output = _output(case_id, output_format=output_format)
        cache = _cache_state(
            case_id=case_id,
            prewarmed=lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED,
        )
        payload.update(
            output=output,
            diagnostic_output=output,
            process_tree=authoritative_tree,
            diagnostic_process_tree=diagnostic_tree,
            instrumentation_manifest=manifest,
            authoritative_cache_state=cache,
            diagnostic_cache_state=cache,
            authoritative_network_isolation=factory.network_isolation_v2(),
            diagnostic_network_isolation=factory.network_isolation_v2(),
            authoritative_response_boundary_protocol=(
                "controller-response-freeze-and-post-response-resource-closure-v2"
            ),
            diagnostic_response_boundary_protocol=(
                "controller-response-freeze-and-post-response-resource-closure-v2"
            ),
            authoritative_resource_tracker_disposition=(
                factory.resource_tracker_disposition_v2(
                    authoritative_tree,
                    tracker_preexisting=tracker_preexisting,
                )
            ),
            diagnostic_resource_tracker_disposition=(
                factory.resource_tracker_disposition_v2(
                    diagnostic_tree,
                    tracker_preexisting=tracker_preexisting,
                )
            ),
            legacy_v1_authorization=None,
        )
    return LatencyAttempt.model_validate(payload)


def _worker_evidence(
    attempt: LatencyAttempt,
    identity: CandidateExecutionIdentity,
    *,
    diagnostic: bool,
) -> WorkerExecutionEvidence:
    assert attempt.status is AttemptStatus.SUCCESS
    tree = attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
    assert tree is not None
    output = attempt.diagnostic_output if diagnostic else attempt.output
    assert output is not None
    cache_state = (
        attempt.diagnostic_cache_state
        if diagnostic
        else attempt.authoritative_cache_state
    )
    network_isolation = (
        attempt.diagnostic_network_isolation
        if diagnostic
        else attempt.authoritative_network_isolation
    )
    assert cache_state is not None
    assert network_isolation is not None
    tracker_disposition = (
        attempt.diagnostic_resource_tracker_disposition
        if diagnostic
        else attempt.authoritative_resource_tracker_disposition
    )
    assert tracker_disposition is not None
    assert tree.lifecycle_exact_worker_self_cpu_ns is not None
    assert tree.lifecycle_reaped_children_cpu_ns is not None
    assert tree.worker_lifetime_hwm_bytes_at_resource_closure is not None
    assert tree.response_boundary_snapshot is not None
    assert tree.resource_closure_snapshot is not None
    response_observed_ns = tree.response_boundary_snapshot.observed_monotonic_ns
    closure_observed_ns = tree.resource_closure_snapshot.observed_monotonic_ns
    trace = (
        attempt.stage_trace
        if diagnostic
        else root_only_trace(
            request_started_ns=tree.request_started_monotonic_ns,
            request_ended_ns=tree.request_ended_monotonic_ns,
            status=StageStatus.SUCCESS,
            failure_code=None,
        )
    )
    assert trace is not None
    return WorkerExecutionEvidence(
        schema_id="phase-latency-external-worker-v2",
        measurement_role=(
            "diagnostic_instrumented" if diagnostic else "authoritative_uninstrumented"
        ),
        telemetry_source=("external_test_instrumentation" if diagnostic else "none"),
        source=attempt.source,
        configuration=attempt.configuration,
        candidate_code_sha256=identity.candidate_code_sha256,
        dependency_lock_sha256=identity.dependency_manifest_sha256,
        environment_sha256=identity.environment_manifest.manifest_sha256,
        exact_supplied_environment_sha256=(network_isolation.worker_environment_sha256),
        environment_manifest=identity.environment_manifest,
        model_artifacts_sha256=identity.model_artifacts_sha256,
        post_request_candidate_code_sha256=identity.candidate_code_sha256,
        post_request_dependency_lock_sha256=identity.dependency_manifest_sha256,
        post_request_environment_sha256=identity.environment_manifest.manifest_sha256,
        post_request_model_artifacts_sha256=identity.model_artifacts_sha256,
        status=AttemptStatus.SUCCESS,
        started_at_utc=attempt.started_at_utc,
        completed_at_utc=attempt.completed_at_utc,
        request_started_monotonic_ns=tree.request_started_monotonic_ns,
        request_ended_monotonic_ns=tree.request_ended_monotonic_ns,
        http_status=200,
        cache_hit=False,
        evidence_complete=True,
        output=output,
        error_response=None,
        failure=None,
        stage_trace=trace,
        cache_state=cache_state,
        network_isolation=network_isolation,
        instrumentation_manifest=(
            attempt.instrumentation_manifest if diagnostic else None
        ),
        response_boundary_protocol=(
            "controller-response-freeze-and-post-response-resource-closure-v2"
        ),
        response_boundary_signal_monotonic_ns=tree.request_ended_monotonic_ns,
        response_boundary_ack_monotonic_ns=response_observed_ns + 1,
        resource_closure_signal_monotonic_ns=closure_observed_ns - 1,
        resource_closure_ack_monotonic_ns=closure_observed_ns + 1,
        resource_tracker_disposition=tracker_disposition,
        resource_boundary=WorkerResourceBoundaryEvidence(
            basis="response-boundary-plus-post-response-reaped-lifecycle-v2",
            worker_self_user_cpu_delta_ns=(tree.lifecycle_exact_worker_self_cpu_ns),
            worker_self_system_cpu_delta_ns=0,
            reaped_children_user_cpu_delta_ns=(tree.lifecycle_reaped_children_cpu_ns),
            reaped_children_system_cpu_delta_ns=0,
            worker_process_lifetime_hwm_bytes=(
                tree.worker_lifetime_hwm_bytes_at_resource_closure
            ),
            reaped_children_process_lifetime_hwm_bytes=tree.reaped_children_hwm_bytes,
            conservative_root_plus_reaped_children_hwm_bytes=None,
            lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes=(
                tree.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
            ),
            response_boundary_worker_self_user_cpu_delta_ns=(
                tree.exact_worker_self_cpu_ns
            ),
            response_boundary_worker_self_system_cpu_delta_ns=0,
            response_boundary_reaped_children_user_cpu_delta_ns=(
                tree.exact_reaped_children_cpu_ns
            ),
            response_boundary_reaped_children_system_cpu_delta_ns=0,
            response_boundary_worker_process_lifetime_hwm_bytes=(
                tree.peak_worker_hwm_bytes
            ),
            response_boundary_reaped_children_process_lifetime_hwm_bytes=(
                tree.reaped_children_hwm_bytes
            ),
            post_response_cleanup_cpu_and_hwm_included=True,
        ),
        post_response_validation_duration_ns=(
            attempt.diagnostic_post_response_validation_duration_ns
            if diagnostic
            else attempt.authoritative_post_response_validation_duration_ns
        ),
        worker_hwm_bytes_at_response_boundary=tree.peak_worker_hwm_bytes,
        worker_hwm_bytes_at_resource_closure=(
            tree.worker_lifetime_hwm_bytes_at_resource_closure
        ),
    )


def _round(
    attempts: tuple[LatencyAttempt, LatencyAttempt], *, diagnostic: bool
) -> ConcurrentRoundEvidence:
    role = "diagnostic_instrumented" if diagnostic else "authoritative_uninstrumented"
    intervals = []
    for index, attempt in enumerate(attempts):
        tree = attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
        assert tree is not None
        intervals.append(
            ConcurrentWorkerInterval(
                case_id=attempt.case_id,
                attempt_id=attempt.attempt_id,
                slot_id=attempt.slot_id,
                worker_group_id=tree.snapshots[0].members[0].identity.pid,
                worker_create_time_ns=(
                    tree.snapshots[0].members[0].identity.create_time_ns
                ),
                request_started_monotonic_ns=tree.request_started_monotonic_ns,
                request_ended_monotonic_ns=tree.request_ended_monotonic_ns,
            )
        )
    interval_tuple = tuple(intervals)
    first, second = interval_tuple
    events = (
        ActiveSlotEvent(
            observed_monotonic_ns=1_000_000_000,
            event="start",
            slot_id=first.slot_id,
            active_slot_ids=(first.slot_id,),
        ),
        ActiveSlotEvent(
            observed_monotonic_ns=1_000_000_001,
            event="start",
            slot_id=second.slot_id,
            active_slot_ids=tuple(sorted((first.slot_id, second.slot_id))),
        ),
        ActiveSlotEvent(
            observed_monotonic_ns=1_019_999_999,
            event="end",
            slot_id=first.slot_id,
            active_slot_ids=(second.slot_id,),
        ),
        ActiveSlotEvent(
            observed_monotonic_ns=1_020_000_000,
            event="end",
            slot_id=second.slot_id,
            active_slot_ids=(),
        ),
    )
    snapshots = []
    for observed_ns in (1_000_000_002, 1_010_000_002, 1_020_000_000):
        sweep_started_ns = observed_ns - 2
        groups = tuple(
            ConcurrentWorkerGroupMetric(
                case_id=item.case_id,
                attempt_id=item.attempt_id,
                slot_id=item.slot_id,
                worker_group_id=item.worker_group_id,
                worker_create_time_ns=item.worker_create_time_ns,
                sampled_monotonic_ns=sweep_started_ns + index,
                rss_bytes=1_000,
                cumulative_cpu_ns=100,
            )
            for index, item in enumerate(interval_tuple)
        )
        snapshots.append(
            ConcurrentAggregateSnapshot(
                aggregation_basis=("bounded-skew-sequential-process-tree-sweep-v1"),
                sweep_started_monotonic_ns=sweep_started_ns,
                sweep_ended_monotonic_ns=observed_ns,
                observed_monotonic_ns=observed_ns,
                groups=groups,
                aggregate_rss_bytes=2_000,
                aggregate_cpu_ns=200,
            )
        )
    trees = tuple(
        attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
        for attempt in attempts
    )
    exact_cpu = sum(
        tree.exact_worker_self_cpu_ns
        + tree.exact_reaped_children_cpu_ns
        + tree.conservative_frozen_response_boundary_descendant_cpu_ns
        for tree in trees
        if tree is not None
    )
    conservative_cpu = sum(
        max(
            tree.maximum_observed_process_cpu_ns,
            tree.exact_worker_self_cpu_ns
            + tree.exact_reaped_children_cpu_ns
            + tree.conservative_frozen_response_boundary_descendant_cpu_ns,
        )
        for tree in trees
        if tree is not None
    )
    return ConcurrentRoundEvidence(
        role=role,
        round_index=2 if diagnostic else 1,
        barrier_id=(
            "lat-us01-bound2-diagnostic-barrier"
            if diagnostic
            else "lat-us01-bound2-authoritative-barrier"
        ),
        controller_started_monotonic_ns=990_000_000,
        controller_ended_monotonic_ns=1_030_000_000,
        worker_intervals=interval_tuple,
        active_slot_ledger=events,
        maximum_occupancy=2,
        overlap_ns=20_000_000,
        worker_group_count=2,
        bounded_skew_snapshots=tuple(snapshots),
        sampling_interval_target_ns=50_000_000,
        hard_maximum_gap_ns=250_000_000,
        maximum_observed_gap_ns=10_000_000,
        peak_bounded_skew_aggregate_rss_bytes=2_000,
        exact_aggregate_cpu_ns=exact_cpu,
        conservative_aggregate_cpu_ns=conservative_cpu,
        all_groups_reaped=True,
    )


def _attempt_ledger(
    identity: CandidateExecutionIdentity,
    attempts: tuple[LatencyAttempt, ...],
    *,
    close: bool,
) -> CandidateProfileAttemptLedger:
    ledger = initial_candidate_profile_attempt_ledger(identity)
    last_monotonic_ns = 0
    last_completed_at = datetime(2026, 8, 9, tzinfo=UTC)
    for attempt in attempts:
        for diagnostic in (False, True):
            worker = _worker_evidence(attempt, identity, diagnostic=diagnostic)
            tree = (
                attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
            )
            watchdog = (
                attempt.diagnostic_watchdog
                if diagnostic
                else attempt.authoritative_watchdog
            )
            assert tree is not None
            assert watchdog is not None
            ledger = append_role_observation(
                ledger,
                execution_id=attempt.attempt_id,
                slot_id=attempt.slot_id,
                role=worker.measurement_role,
                status=worker.status,
                failure=worker.failure,
                started_at_utc=worker.started_at_utc,
                completed_at_utc=worker.completed_at_utc,
                started_monotonic_ns=worker.request_started_monotonic_ns,
                ended_monotonic_ns=worker.request_ended_monotonic_ns,
                worker_evidence=worker,
                snapshots=tree.snapshots,
                watchdog=watchdog,
            )
            last_monotonic_ns = max(
                last_monotonic_ns, worker.request_ended_monotonic_ns
            )
            last_completed_at = max(last_completed_at, worker.completed_at_utc)
        ledger = append_attempt_observation(ledger, attempt)
    if close:
        ledger = finalize_ledger(
            ledger,
            finalized_at_utc=last_completed_at + timedelta(microseconds=1),
            finalized_monotonic_ns=last_monotonic_ns + 1,
        )
    return ledger


def _profile_set() -> CandidateProfileSet:
    global _OPEN_LEDGER
    pyproject = ArtifactIdentity(
        path="pyproject.toml", sha256=PYPROJECT_SHA256, size_bytes=944
    )
    lock = ArtifactIdentity(
        path="uv.lock", sha256=DEPENDENCY_LOCK_SHA256, size_bytes=606_213
    )
    dependency_sha = _canonical_hash(
        [
            {"path": item.path, "sha256": item.sha256, "size_bytes": item.size_bytes}
            for item in (pyproject, lock)
        ]
    )
    environment = factory.environment_identity()
    harness_files = tuple(
        ArtifactIdentity(path=path, sha256=SHA_A, size_bytes=1)
        for path in HARNESS_PATHS
    )
    observer_files = tuple(
        item for item in harness_files if item.path in OBSERVER_HARNESS_PATHS
    )
    manifest = _manifest(
        observer_files=observer_files,
        environment_sha256=environment.manifest_sha256,
        dependency_sha256=dependency_sha,
    )
    cases = []
    for case_index, case_id in enumerate(CASE_ORDER):
        cases.append(
            CandidateProfileCase(
                case_id=case_id,
                source=_source(case_id),
                source_custody="public-redistributable",
                m0_case_hwm_bytes=M0_CASE_HWM_BYTES[case_id],
                p00_semantic_json_sha256=P00_OUTPUT_IDENTITIES[case_id][0],
                p00_markdown_sha256=P00_OUTPUT_IDENTITIES[case_id][1],
                p00_markdown_size_bytes=P00_OUTPUT_IDENTITIES[case_id][2],
                current_runtime_semantic_json_sha256=(
                    CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id][0]
                ),
                current_runtime_markdown_sha256=(
                    CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id][1]
                ),
                current_runtime_markdown_size_bytes=(
                    CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id][2]
                ),
                cold_json=_attempt(
                    case_id=case_id,
                    label="cold-json",
                    order_index=3 * case_index + 1,
                    bounded_concurrency=1,
                    environment_sha256=environment.manifest_sha256,
                    dependency_sha256=dependency_sha,
                    manifest=manifest,
                ),
                prewarmed_json=_attempt(
                    case_id=case_id,
                    label="prewarmed-json",
                    order_index=3 * case_index + 2,
                    bounded_concurrency=1,
                    environment_sha256=environment.manifest_sha256,
                    dependency_sha256=dependency_sha,
                    manifest=manifest,
                ),
                cold_markdown=_attempt(
                    case_id=case_id,
                    label="cold-markdown",
                    order_index=3 * case_index + 3,
                    bounded_concurrency=1,
                    environment_sha256=environment.manifest_sha256,
                    dependency_sha256=dependency_sha,
                    manifest=manifest,
                ),
            )
        )
    concurrent_attempts = tuple(
        _attempt(
            case_id=case_id,
            label="bound2-cold-json",
            order_index=46 + index,
            bounded_concurrency=2,
            environment_sha256=environment.manifest_sha256,
            dependency_sha256=dependency_sha,
            manifest=manifest,
        )
        for index, case_id in enumerate(("ny-timetable", "uber-earnings"))
    )
    concurrent = ConcurrentBatchEvidence(
        schema_id="phase-latency-concurrent-batch-v1",
        batch_id="lat-us01-ny-uber-bound2-cold-json",
        bounded_concurrency=2,
        ordered_attempts=concurrent_attempts,
        authoritative_round=_round(concurrent_attempts, diagnostic=False),
        diagnostic_round=_round(concurrent_attempts, diagnostic=True),
        controller_thread_count_before=4,
        controller_thread_count_after=4,
        controller_fd_count_before=12,
        controller_fd_count_after=12,
        hosted_calls=0,
        hosted_credits=0,
        prompt_tokens=0,
        completion_tokens=0,
        billed_cost_microusd=0,
        egress_bytes=0,
    )
    identity = CandidateExecutionIdentity(
        candidate_code_sha256=CANDIDATE_CODE_SHA256,
        pyproject=pyproject,
        dependency_lock=lock,
        dependency_manifest_sha256=dependency_sha,
        environment_manifest=environment,
        environment_comparable=False,
        model_artifacts_sha256=MODEL_ARTIFACTS_SHA256,
        corpus_registry=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
            sha256="f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb",
            size_bytes=20_744,
        ),
        phase03_oracle=ArtifactIdentity(
            path="tests/fixtures/phase_03/running_regions/oracle.py",
            sha256="5e70b5df58284f544b43a6189055044c80c2a9a6404f143758be550e3879b563",
            size_bytes=160_147,
        ),
        m0_resource_record=ArtifactIdentity(
            path="tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current/run-metadata.json",
            sha256="386c333bff8ec0678d1194fff5899f82ec9475d29be7d72999a58c3817e3128f",
            size_bytes=8_025,
        ),
        p00_run_record=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/run-record.json",
            sha256="aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2",
            size_bytes=79_247,
        ),
        p00_semantic_report=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/semantic-report.json",
            sha256="3d2e36fd6696039abaeb346fc458687f9f114a340bc895c8ee5b921efbb17c77",
            size_bytes=317_372,
        ),
        current_runtime_run_record=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/run-record.json",
            sha256="2cfecdf72a588e0088618ed7001a20ddfa6742d2acf6e89b0a6f0efe5805cb3c",
            size_bytes=81_637,
        ),
        current_runtime_semantic_report=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.json",
            sha256="03044b2c9c4d9caec2cb7d247989ca00bd6556fea12502efc09cc2fb4143567a",
            size_bytes=317_415,
        ),
        current_runtime_semantic_report_markdown=ArtifactIdentity(
            path="tracker/phase-00-baseline/evidence/lat-us01-current-runtime-baseline-20260809-r01/semantic-report.md",
            sha256="47318b48735d81e1c7d5bb971617ef2d23e58cbe7e55c150229855359f2d8fe3",
            size_bytes=1_383,
        ),
        harness_files=harness_files,
        source_registry_sha256="0fe1648db893170c6584246e553afbc2939f70ed72d3ea15ec1a1d4fe6d05b5a",
    )
    selected_attempts = (
        tuple(
            attempt
            for case in cases
            for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
        )
        + concurrent_attempts
    )
    _OPEN_LEDGER = _attempt_ledger(identity, selected_attempts, close=False)
    attempt_ledger = finalize_ledger(
        _OPEN_LEDGER,
        finalized_at_utc=(
            max(item.completed_at_utc for item in selected_attempts)
            + timedelta(microseconds=1)
        ),
        finalized_monotonic_ns=(
            max(
                tree.request_ended_monotonic_ns
                for item in selected_attempts
                for tree in (item.process_tree, item.diagnostic_process_tree)
                if tree is not None
            )
            + 1
        ),
    )
    return CandidateProfileSet(
        schema_id="phase-latency-candidate-profile-set-v1",
        schema_version="1.0",
        profile_set_id="lat-us01-all-15-profile-v1",
        identity=identity,
        attempt_ledger=attempt_ledger,
        quality=P00QualityEvidence(
            case_count=15,
            page_count=30,
            reviewed_claim_count=210,
            literal_eligible_count=109,
            semantic_eligible_count=162,
            excluded_unsupported_count=48,
            control_count=25,
            dimension_count=12,
            quality_signature_sha256="a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed",
            stable_output_signature_sha256="a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0",
            current_runtime_stable_output_signature_sha256="d10fb6107c9a0b97788ec23d2519a31b53dc3c23df5b06a1566b9e96a072e71e",
            baseline_policy="p00-historical-plus-reviewed-current-runtime-exact-v1",
            zero_unexplained_drift=True,
        ),
        cases=tuple(cases),
        concurrent_batch=concurrent,
        production_instrumentation_enabled=False,
        production_feature_flag=None,
        rollback_disposition="stop-disposable-benchmark-workers",
        cache_policy="content-result-cache-disabled-filesystem-cache-uncontrolled",
        failure_retention_policy="retain-every-attempt-no-aggregate-masking-v1",
        environment_comparable=False,
        hosted_calls=0,
        hosted_credits=0,
        prompt_tokens=0,
        completion_tokens=0,
        billed_cost_microusd=0,
        egress_bytes=0,
    )


@pytest.fixture(scope="module")
def profile_set() -> CandidateProfileSet:
    return _profile_set()


@pytest.fixture(scope="module")
def open_ledger(profile_set: CandidateProfileSet) -> CandidateProfileAttemptLedger:
    del profile_set
    assert _OPEN_LEDGER is not None
    return _OPEN_LEDGER


def _payload(profile_set: CandidateProfileSet) -> dict[str, object]:
    return copy.deepcopy(profile_set.model_dump(mode="python"))


def _append_successful_attempt(
    ledger: CandidateProfileAttemptLedger,
    attempt: LatencyAttempt,
    identity: CandidateExecutionIdentity,
) -> CandidateProfileAttemptLedger:
    for diagnostic in (False, True):
        worker = _worker_evidence(attempt, identity, diagnostic=diagnostic)
        tree = attempt.diagnostic_process_tree if diagnostic else attempt.process_tree
        watchdog = (
            attempt.diagnostic_watchdog
            if diagnostic
            else attempt.authoritative_watchdog
        )
        assert tree is not None
        assert watchdog is not None
        ledger = append_role_observation(
            ledger,
            execution_id=attempt.attempt_id,
            slot_id=attempt.slot_id,
            role=worker.measurement_role,
            status=worker.status,
            failure=None,
            started_at_utc=worker.started_at_utc,
            completed_at_utc=worker.completed_at_utc,
            started_monotonic_ns=worker.request_started_monotonic_ns,
            ended_monotonic_ns=worker.request_ended_monotonic_ns,
            worker_evidence=worker,
            snapshots=tree.snapshots,
            watchdog=watchdog,
        )
    return append_attempt_observation(ledger, attempt)


def _close_ledger(
    ledger: CandidateProfileAttemptLedger,
) -> CandidateProfileAttemptLedger:
    return finalize_ledger(
        ledger,
        finalized_at_utc=(
            max(item.completed_at_utc for item in ledger.role_observations)
            + timedelta(microseconds=1)
        ),
        finalized_monotonic_ns=(
            max(item.ended_monotonic_ns for item in ledger.role_observations) + 1
        ),
    )


def test_failed_role_checkpoint_retains_bounded_worker_fatal_envelope(
    profile_set: CandidateProfileSet,
) -> None:
    ledger = initial_candidate_profile_attempt_ledger(profile_set.identity)
    slot_id = profile_set.cases[0].cold_json.slot_id
    execution_id = next_candidate_profile_execution_id(ledger, slot_id)
    started_at = datetime(2026, 8, 9, tzinfo=UTC)
    envelope = WorkerFatalEnvelope(
        schema_id="phase-latency-worker-fatal-envelope-v1",
        checkpoint="resource_tracker_cleanup_exit_code",
        exception_family="runtime",
        exit_code=88,
    )
    failure = FailureRecord(
        code=FailureCode.WORKER_EXITED_DURING_REQUEST,
        stage=StageName.REQUEST_TOTAL,
        exception_type=FailureType.WORKER_CRASH,
    )

    retained = append_role_observation(
        ledger,
        execution_id=execution_id,
        slot_id=slot_id,
        role="authoritative_uninstrumented",
        status=AttemptStatus.ERROR,
        failure=failure,
        started_at_utc=started_at,
        completed_at_utc=started_at + timedelta(microseconds=1),
        started_monotonic_ns=1,
        ended_monotonic_ns=2,
        worker_evidence=None,
        snapshots=(),
        watchdog=None,
        worker_fatal_envelope=envelope,
    )

    observation = retained.role_observations[0]
    assert observation.worker_fatal_envelope == envelope
    encoded = canonical_model_bytes(observation)
    assert len(canonical_model_bytes(envelope)) <= 512
    assert b"resource_tracker_cleanup_exit_code" in encoded
    assert b"document" not in encoded


def _profile_with_first_cold_selection(
    profile_set: CandidateProfileSet,
    *,
    ledger: CandidateProfileAttemptLedger,
    attempt: LatencyAttempt,
) -> CandidateProfileSet:
    payload = _payload(profile_set)
    payload["attempt_ledger"] = ledger.model_dump(mode="python")
    payload["cases"][0]["cold_json"] = attempt.model_dump(mode="python")
    payload["quality"]["zero_unexplained_drift"] = False
    return CandidateProfileSet.model_validate(payload)


def test_valid_all_15_profile_passes_every_gate(
    profile_set: CandidateProfileSet,
) -> None:
    result = evaluate_candidate_profile_set(profile_set)
    assert result.passed is True
    assert result.failure_codes == ()
    assert result.attempt_count == result.success_count == 47
    assert result.failure_count == 0


def test_current_runtime_baseline_is_additive_and_exact(
    profile_set: CandidateProfileSet,
) -> None:
    json_drift_cases = tuple(
        case_id
        for case_id in CASE_ORDER
        if P00_OUTPUT_IDENTITIES[case_id][0]
        != CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id][0]
    )
    assert json_drift_cases == (
        "clean-energy",
        "clinical-study",
        "finance-10k",
        "manufacturing-report",
        "ny-timetable",
        "postal-10k",
        "uber-earnings",
    )
    assert all(
        P00_OUTPUT_IDENTITIES[case_id][1:]
        == CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id][1:]
        for case_id in CASE_ORDER
    )
    assert profile_set.quality.baseline_policy == (
        "p00-historical-plus-reviewed-current-runtime-exact-v1"
    )
    assert profile_set.quality.zero_unexplained_drift is True


def test_final_profile_rejects_missing_or_mutated_current_runtime_custody(
    profile_set: CandidateProfileSet,
) -> None:
    missing = _payload(profile_set)
    missing["identity"]["current_runtime_run_record"] = None
    with pytest.raises(ValidationError, match="current-runtime baseline custody"):
        CandidateProfileSet.model_validate(missing)

    mutated = _payload(profile_set)
    mutated["cases"][0]["current_runtime_semantic_json_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="current-runtime output custody"):
        CandidateProfileSet.model_validate(mutated)


def test_prebaseline_ledger_identity_remains_readable(
    profile_set: CandidateProfileSet,
) -> None:
    identity_payload = profile_set.identity.model_dump(mode="python")
    for field in (
        "current_runtime_run_record",
        "current_runtime_semantic_report",
        "current_runtime_semantic_report_markdown",
    ):
        identity_payload.pop(field)
    historical_identity = CandidateExecutionIdentity.model_validate(identity_payload)
    historical_ledger = initial_candidate_profile_attempt_ledger(historical_identity)
    round_trip = CandidateProfileAttemptLedger.model_validate_json(
        canonical_model_bytes(historical_ledger)
    )
    assert round_trip == historical_ledger
    assert round_trip.execution_identity.current_runtime_run_record is None


def test_sampled_rss_above_worker_rusage_is_retained_conservatively(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    assert attempt.process_tree is not None
    tree_payload = attempt.process_tree.model_dump(mode="python")
    response_index = tree_payload["response_boundary_snapshot_index"]
    assert isinstance(response_index, int)
    response = tree_payload["snapshots"][response_index]
    response["members"][0]["rss_bytes"] += 16_384
    response["members"][0]["self_hwm_bytes"] += 16_384
    response["total_rss_bytes"] += 16_384
    tree_payload["response_boundary_snapshot"] = copy.deepcopy(response)
    request_snapshots = tree_payload["snapshots"][: response_index + 1]
    tree_payload["peak_total_rss_bytes"] = max(
        item["total_rss_bytes"] for item in request_snapshots
    )
    tree_payload["peak_worker_hwm_bytes"] = max(
        item["members"][0]["self_hwm_bytes"] for item in request_snapshots
    )
    tree_payload["response_through_resource_closure_peak_total_rss_bytes"] = max(
        item["total_rss_bytes"]
        for item in tree_payload["snapshots"][response_index:]
    )
    conservative_tree = ProcessTreeMetrics.model_validate(tree_payload)
    worker_reported_hwm = (
        attempt.process_tree.peak_worker_hwm_bytes
    )
    assert conservative_tree.peak_worker_hwm_bytes > worker_reported_hwm

    changed_attempt = attempt.model_copy(
        update={"process_tree": conservative_tree}
    )
    ledger_payload = profile_set.attempt_ledger.model_dump(mode="json")
    for observation in ledger_payload["role_observations"]:
        if (
            observation["execution_id"] == attempt.attempt_id
            and observation["role"] == "authoritative_uninstrumented"
        ):
            observation["snapshots"] = tree_payload["snapshots"]
    for observation in ledger_payload["attempt_observations"]:
        if observation["execution_id"] == attempt.attempt_id:
            observation["attempt"] = changed_attempt.model_dump(mode="json")
    changed_ledger = seal_candidate_profile_attempt_ledger(ledger_payload)
    profile_payload = _payload(profile_set)
    profile_payload["attempt_ledger"] = changed_ledger.model_dump(mode="python")
    profile_payload["cases"][0]["cold_json"] = changed_attempt.model_dump(
        mode="python"
    )
    retained = CandidateProfileSet.model_validate(profile_payload)
    assert retained.cases[0].cold_json.process_tree is not None
    assert (
        retained.cases[0].cold_json.process_tree.peak_worker_hwm_bytes
        == conservative_tree.peak_worker_hwm_bytes
    )


def test_trusted_harness_inventory_is_exact_and_observer_subset_is_nine(
    profile_set: CandidateProfileSet,
) -> None:
    assert (
        tuple(item.path for item in profile_set.identity.harness_files) == HARNESS_PATHS
    )
    assert "tests/benchmarks/latency_profile_set.py" in HARNESS_PATHS
    assert "tests/benchmarks/latency_watchdog.py" in HARNESS_PATHS
    assert len(HARNESS_PATHS) == 10
    assert len(OBSERVER_HARNESS_PATHS) == 9
    assert (
        tuple(
            item.path
            for item in profile_set.cases[
                0
            ].cold_json.instrumentation_manifest.harness_files
        )
        == OBSERVER_HARNESS_PATHS
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(cases=tuple(reversed(value["cases"]))),
        lambda value: value.update(cases=value["cases"][:-1]),
        lambda value: value["cases"][0]["source"].update(sha256="0" * 64),
        lambda value: value["cases"][0]["cold_json"].update(slot_id="wrong-slot"),
        lambda value: value["cases"][0]["cold_json"].update(order_index=2),
        lambda value: value["identity"]["corpus_registry"].update(sha256="0" * 64),
        lambda value: value["identity"]["phase03_oracle"].update(size_bytes=1),
        lambda value: value["identity"].update(
            harness_files=value["identity"]["harness_files"][:-1]
        ),
        lambda value: value["identity"].update(source_registry_sha256="0" * 64),
        lambda value: value["quality"].update(reviewed_claim_count=209),
        lambda value: value.update(hosted_calls=1),
        lambda value: value.update(extra_field="forbidden"),
        lambda value: value["concurrent_batch"].update(controller_thread_count_after=5),
        lambda value: value["concurrent_batch"]["authoritative_round"].update(
            barrier_id="wrong-barrier"
        ),
        lambda value: value["concurrent_batch"]["authoritative_round"].update(
            overlap_ns=0
        ),
        lambda value: value["concurrent_batch"]["authoritative_round"].update(
            maximum_observed_gap_ns=1
        ),
        lambda value: value["concurrent_batch"]["authoritative_round"][
            "worker_intervals"
        ][0].update(worker_group_id=99_999),
        lambda value: value["concurrent_batch"]["authoritative_round"][
            "bounded_skew_snapshots"
        ][0].update(aggregate_rss_bytes=1),
    ),
)
def test_structural_or_custody_mutations_fail_closed(
    profile_set: CandidateProfileSet,
    mutate: Callable[[dict[str, object]], object],
) -> None:
    payload = _payload(profile_set)
    mutate(payload)
    with pytest.raises(ValidationError):
        CandidateProfileSet.model_validate(payload)


def test_dependency_composite_mutation_fails_closed(
    profile_set: CandidateProfileSet,
) -> None:
    payload = _payload(profile_set)
    payload["identity"]["pyproject"]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="identity differs"):
        CandidateProfileSet.model_validate(payload)


def test_output_identity_drift_is_a_gate_failure(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    changed_output = attempt.output.model_copy(update={"semantic_sha256": "0" * 64})
    changed_diagnostic = attempt.diagnostic_output.model_copy(
        update={"semantic_sha256": "0" * 64}
    )
    changed_attempt = attempt.model_copy(
        update={"output": changed_output, "diagnostic_output": changed_diagnostic}
    )
    changed_case = profile_set.cases[0].model_copy(
        update={"cold_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    result = evaluate_candidate_profile_set(changed)
    assert result.passed is False
    assert "output_identity_drift" in result.failure_codes


def test_retained_failed_attempt_cannot_be_masked_by_aggregate(
    profile_set: CandidateProfileSet,
) -> None:
    failed = profile_set.cases[0].cold_json.model_copy(
        update={"status": AttemptStatus.ERROR, "evidence_complete": False}
    )
    changed_case = profile_set.cases[0].model_copy(update={"cold_json": failed})
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    result = evaluate_candidate_profile_set(changed)
    assert result.success_count == 46
    assert result.failure_count == 1
    assert {"attempt_failed", "evidence_incomplete"}.issubset(result.failure_codes)


def test_same_process_resource_evidence_is_not_accepted(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    local_tree = factory.process_tree()
    changed_attempt = attempt.model_copy(
        update={"process_tree": local_tree, "diagnostic_process_tree": local_tree}
    )
    changed_case = profile_set.cases[0].model_copy(
        update={"cold_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    assert "resource_cpu_sanity_failed" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_concurrent_aggregate_rss_ceiling_is_enforced(
    profile_set: CandidateProfileSet,
) -> None:
    round_evidence = profile_set.concurrent_batch.authoritative_round
    snapshot = round_evidence.bounded_skew_snapshots[0]
    groups = tuple(
        group.model_copy(update={"rss_bytes": 2_500_000_000})
        for group in snapshot.groups
    )
    changed_snapshot = snapshot.model_copy(
        update={"groups": groups, "aggregate_rss_bytes": 5_000_000_000}
    )
    changed_round = round_evidence.model_copy(
        update={
            "bounded_skew_snapshots": (changed_snapshot,),
            "peak_bounded_skew_aggregate_rss_bytes": 5_000_000_000,
        }
    )
    batch = profile_set.concurrent_batch.model_copy(
        update={"authoritative_round": changed_round}
    )
    changed = profile_set.model_copy(update={"concurrent_batch": batch})
    assert "concurrent_rss_exceeded" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_per_case_and_diagnostic_hwm_ceilings_are_independent(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    assert attempt.process_tree is not None
    assert attempt.diagnostic_process_tree is not None
    changed_attempt = attempt.model_copy(
        update={
            "diagnostic_process_tree": attempt.diagnostic_process_tree.model_copy(
                update={
                    "peak_worker_hwm_bytes": (
                        attempt.process_tree.peak_worker_hwm_bytes + 67_108_865
                    )
                }
            )
        }
    )
    changed_case = profile_set.cases[0].model_copy(
        update={"cold_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    failures = evaluate_candidate_profile_set(changed).failure_codes
    assert "diagnostic_hwm_delta_exceeded" in failures
    assert "per_case_hwm_exceeded" in failures


def test_cold_hwm_p50_and_maximum_are_nearest_rank_gates(
    profile_set: CandidateProfileSet,
) -> None:
    changed_cases = list(profile_set.cases)
    for index in range(8):
        attempt = changed_cases[index].cold_json
        assert attempt.process_tree is not None
        tree = attempt.process_tree.model_copy(
            update={"peak_worker_hwm_bytes": 3_500_000_000}
        )
        changed_cases[index] = changed_cases[index].model_copy(
            update={"cold_json": attempt.model_copy(update={"process_tree": tree})}
        )
    result = evaluate_candidate_profile_set(
        profile_set.model_copy(update={"cases": tuple(changed_cases)})
    )
    assert "cold_hwm_p50_exceeded" in result.failure_codes
    assert "cold_hwm_maximum_exceeded" in result.failure_codes


def test_sampled_cpu_may_exceed_exact_when_conservative_bound_passes(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    assert attempt.process_tree is not None
    changed_tree = attempt.process_tree.model_copy(
        update={
            "maximum_observed_process_cpu_ns": 1_000,
            "exact_worker_self_cpu_ns": 100,
            "exact_reaped_children_cpu_ns": 0,
        }
    )
    changed_attempt = attempt.model_copy(update={"process_tree": changed_tree})
    changed_case = profile_set.cases[0].model_copy(
        update={"cold_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    assert "resource_cpu_sanity_failed" not in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_conservative_cpu_capacity_is_fail_closed(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].cold_json
    assert attempt.process_tree is not None
    changed_tree = attempt.process_tree.model_copy(
        update={"exact_worker_self_cpu_ns": 10**12}
    )
    changed_attempt = attempt.model_copy(update={"process_tree": changed_tree})
    changed_case = profile_set.cases[0].model_copy(
        update={"cold_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    assert "resource_cpu_sanity_failed" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_concurrent_host_capacity_is_enforced(profile_set: CandidateProfileSet) -> None:
    round_evidence = profile_set.concurrent_batch.authoritative_round.model_copy(
        update={"conservative_aggregate_cpu_ns": 10**12}
    )
    batch = profile_set.concurrent_batch.model_copy(
        update={"authoritative_round": round_evidence}
    )
    changed = profile_set.model_copy(update={"concurrent_batch": batch})
    assert "concurrent_cpu_capacity_exceeded" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_expanded_controller_window_cannot_relax_concurrent_cpu_gate(
    profile_set: CandidateProfileSet,
) -> None:
    round_evidence = profile_set.concurrent_batch.authoritative_round
    request_union_ns = max(
        item.request_ended_monotonic_ns for item in round_evidence.worker_intervals
    ) - min(
        item.request_started_monotonic_ns for item in round_evidence.worker_intervals
    )
    logical_cpus = profile_set.identity.environment_manifest.logical_cpu_count
    changed_round = round_evidence.model_copy(
        update={
            "controller_started_monotonic_ns": 0,
            "controller_ended_monotonic_ns": 10**12,
            "conservative_aggregate_cpu_ns": (request_union_ns * logical_cpus + 1),
        }
    )
    changed_batch = profile_set.concurrent_batch.model_copy(
        update={"authoritative_round": changed_round}
    )
    changed = profile_set.model_copy(update={"concurrent_batch": changed_batch})
    assert "concurrent_cpu_capacity_exceeded" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_prewarmed_profile_requires_separate_source_resource_evidence(
    profile_set: CandidateProfileSet,
) -> None:
    attempt = profile_set.cases[0].prewarmed_json
    assert attempt.authoritative_cache_state is not None
    changed_cache = attempt.authoritative_cache_state.model_copy(
        update={"prewarm_evidence": None}
    )
    changed_attempt = attempt.model_copy(
        update={"authoritative_cache_state": changed_cache}
    )
    changed_case = profile_set.cases[0].model_copy(
        update={"prewarmed_json": changed_attempt}
    )
    changed = profile_set.model_copy(
        update={"cases": (changed_case, *profile_set.cases[1:])}
    )
    assert "cache_or_network_policy_failed" in (
        evaluate_candidate_profile_set(changed).failure_codes
    )


def test_profile_models_are_frozen_and_closed(profile_set: CandidateProfileSet) -> None:
    with pytest.raises(ValidationError):
        CandidateProfileSet.model_validate(
            {**profile_set.model_dump(mode="python"), "unknown": True}
        )
    with pytest.raises(ValidationError):
        profile_set.hosted_calls = 1


def test_initial_ledger_is_complete_before_launch_and_hash_sealed(
    profile_set: CandidateProfileSet,
) -> None:
    ledger = initial_candidate_profile_attempt_ledger(profile_set.identity)
    assert ledger.disposition == "in_progress"
    assert ledger.journal_event_count == 0
    assert ledger.checkpoint_index == 1
    assert ledger.previous_checkpoint_sha256 is None
    assert len(ledger.missing_slot_ids) == 47
    assert ledger.checkpoint_sha256 == candidate_profile_ledger_payload_sha256(ledger)
    assert next_candidate_profile_execution_id(
        ledger, "catastrophe-recap-cold-json"
    ) == candidate_profile_execution_id("catastrophe-recap-cold-json", 1)


def test_aborted_finalization_is_a_closed_journal_event(
    profile_set: CandidateProfileSet,
) -> None:
    initial = initial_candidate_profile_attempt_ledger(profile_set.identity)
    closed = finalize_ledger(
        initial,
        finalized_at_utc=datetime(2026, 8, 9, tzinfo=UTC),
        finalized_monotonic_ns=1,
    )
    assert closed.disposition == "aborted"
    assert closed.journal_event_count == 1
    assert closed.finalization_event_count == 1
    assert closed.checkpoint_index == 2
    assert closed.previous_checkpoint_sha256 == initial.checkpoint_sha256
    assert closed.finalization_event is not None
    assert closed.finalization_event.missing_slot_ids == closed.missing_slot_ids
    with pytest.raises(ValueError, match="immutable"):
        finalize_ledger(
            closed,
            finalized_at_utc=datetime(2026, 8, 9, tzinfo=UTC),
            finalized_monotonic_ns=2,
        )


def test_keyboard_interrupt_before_attempt_is_retained_content_free(
    profile_set: CandidateProfileSet,
) -> None:
    initial = initial_candidate_profile_attempt_ledger(profile_set.identity)
    slot_id = "catastrophe-recap-cold-json"
    execution_id = next_candidate_profile_execution_id(initial, slot_id)
    retained = append_controller_failure(
        initial,
        event_kind="controller_keyboard_interrupt",
        slot_id=slot_id,
        execution_id=execution_id,
        status=AttemptStatus.CANCELLED,
        failure_code=FailureCode.WORKER_CANCELLED,
        failure_type=FailureType.WORKER_CANCELLED,
        observed_at_utc=datetime(2026, 8, 9, tzinfo=UTC),
        observed_monotonic_ns=1,
    )
    closed = finalize_ledger(
        retained,
        finalized_at_utc=datetime(2026, 8, 9, tzinfo=UTC),
        finalized_monotonic_ns=2,
    )
    assert closed.disposition == "aborted"
    assert closed.controller_failure_count == 1
    assert closed.has_blocking_observation is True
    assert slot_id in closed.missing_slot_ids
    event_payload = closed.controller_failures[0].model_dump(mode="json")
    assert set(event_payload) == {
        "ledger_index",
        "event_id",
        "event_kind",
        "slot_id",
        "execution_id",
        "status",
        "failure_code",
        "failure_type",
        "observed_at_utc",
        "observed_monotonic_ns",
    }


def test_interrupted_concurrent_round_closes_each_open_execution(
    profile_set: CandidateProfileSet,
) -> None:
    ledger = initial_candidate_profile_attempt_ledger(profile_set.identity)
    attempts = profile_set.concurrent_batch.ordered_attempts
    execution_ids: list[str] = []
    for attempt in attempts:
        execution_id = next_candidate_profile_execution_id(ledger, attempt.slot_id)
        execution_ids.append(execution_id)
        worker = _worker_evidence(attempt, profile_set.identity, diagnostic=False)
        assert attempt.process_tree is not None
        assert attempt.authoritative_watchdog is not None
        ledger = append_role_observation(
            ledger,
            execution_id=execution_id,
            slot_id=attempt.slot_id,
            role="authoritative_uninstrumented",
            status=AttemptStatus.SUCCESS,
            failure=None,
            started_at_utc=worker.started_at_utc,
            completed_at_utc=worker.completed_at_utc,
            started_monotonic_ns=worker.request_started_monotonic_ns,
            ended_monotonic_ns=worker.request_ended_monotonic_ns,
            worker_evidence=worker,
            snapshots=attempt.process_tree.snapshots,
            watchdog=attempt.authoritative_watchdog,
        )
    for attempt, execution_id in zip(attempts, execution_ids, strict=True):
        ledger = append_controller_failure(
            ledger,
            event_kind="controller_keyboard_interrupt",
            slot_id=attempt.slot_id,
            execution_id=execution_id,
            status=AttemptStatus.CANCELLED,
            failure_code=FailureCode.WORKER_CANCELLED,
            failure_type=FailureType.WORKER_CANCELLED,
            observed_at_utc=attempt.completed_at_utc + timedelta(microseconds=1),
            observed_monotonic_ns=(attempt.process_tree.request_ended_monotonic_ns + 1),
        )
    closed = finalize_ledger(
        ledger,
        finalized_at_utc=(
            max(item.completed_at_utc for item in attempts) + timedelta(microseconds=2)
        ),
        finalized_monotonic_ns=(
            max(
                item.process_tree.request_ended_monotonic_ns
                for item in attempts
                if item.process_tree is not None
            )
            + 2
        ),
    )
    assert closed.disposition == "aborted"
    assert closed.role_observation_count == 2
    assert closed.controller_failure_count == 2
    assert closed.has_blocking_observation is True


def test_failed_retry_remains_blocking_after_successful_retry(
    profile_set: CandidateProfileSet,
    open_ledger: CandidateProfileAttemptLedger,
) -> None:
    original = profile_set.cases[0].cold_json
    assert original.instrumentation_manifest is not None
    failed = _attempt(
        case_id=original.case_id,
        label="cold-json",
        order_index=1,
        bounded_concurrency=1,
        environment_sha256=profile_set.identity.environment_manifest.manifest_sha256,
        dependency_sha256=profile_set.identity.dependency_manifest_sha256,
        manifest=original.instrumentation_manifest,
        execution_number=2,
        status=AttemptStatus.ERROR,
    )
    assert failed.failure is not None
    assert failed.process_tree is not None
    ledger = append_role_observation(
        open_ledger,
        execution_id=failed.attempt_id,
        slot_id=failed.slot_id,
        role="authoritative_uninstrumented",
        status=failed.status,
        failure=failed.failure,
        started_at_utc=failed.started_at_utc,
        completed_at_utc=failed.completed_at_utc,
        started_monotonic_ns=failed.process_tree.request_started_monotonic_ns,
        ended_monotonic_ns=failed.process_tree.request_ended_monotonic_ns,
        worker_evidence=None,
        snapshots=failed.process_tree.snapshots,
        watchdog=None,
    )
    ledger = append_attempt_observation(ledger, failed)
    successful = _attempt(
        case_id=original.case_id,
        label="cold-json",
        order_index=1,
        bounded_concurrency=1,
        environment_sha256=profile_set.identity.environment_manifest.manifest_sha256,
        dependency_sha256=profile_set.identity.dependency_manifest_sha256,
        manifest=original.instrumentation_manifest,
        execution_number=3,
    )
    ledger = _append_successful_attempt(ledger, successful, profile_set.identity)
    closed = _close_ledger(ledger)
    assert closed.disposition == "complete"
    assert closed.failed_role_observation_count == 1
    assert closed.failed_attempt_observation_count == 1
    assert closed.selections[0].selected_attempt_id == successful.attempt_id
    changed = _profile_with_first_cold_selection(
        profile_set, ledger=closed, attempt=successful
    )
    result = evaluate_candidate_profile_set(changed)
    assert result.attempt_count == 49
    assert result.failure_count == 1
    assert {
        "attempt_failed",
        "evidence_incomplete",
        "role_observation_failed",
    }.issubset(result.failure_codes)


def test_prior_output_drift_blocks_even_after_clean_retry_and_true_claim(
    profile_set: CandidateProfileSet,
    open_ledger: CandidateProfileAttemptLedger,
) -> None:
    original = profile_set.cases[0].cold_json
    assert original.instrumentation_manifest is not None
    drifted_payload = _attempt(
        case_id=original.case_id,
        label="cold-json",
        order_index=1,
        bounded_concurrency=1,
        environment_sha256=profile_set.identity.environment_manifest.manifest_sha256,
        dependency_sha256=profile_set.identity.dependency_manifest_sha256,
        manifest=original.instrumentation_manifest,
        execution_number=2,
    ).model_dump(mode="python")
    drifted_payload["output"]["semantic_sha256"] = "0" * 64
    drifted_payload["diagnostic_output"]["semantic_sha256"] = "0" * 64
    drifted = LatencyAttempt.model_validate(drifted_payload)
    ledger = _append_successful_attempt(open_ledger, drifted, profile_set.identity)
    clean = _attempt(
        case_id=original.case_id,
        label="cold-json",
        order_index=1,
        bounded_concurrency=1,
        environment_sha256=profile_set.identity.environment_manifest.manifest_sha256,
        dependency_sha256=profile_set.identity.dependency_manifest_sha256,
        manifest=original.instrumentation_manifest,
        execution_number=3,
    )
    ledger = _append_successful_attempt(ledger, clean, profile_set.identity)
    closed = _close_ledger(ledger)
    assert closed.drifted_attempt_observation_count == 1
    changed = _profile_with_first_cold_selection(
        profile_set, ledger=closed, attempt=clean
    )
    result = evaluate_candidate_profile_set(changed)
    assert result.passed is False
    assert "output_identity_drift" in result.failure_codes
    payload = _payload(changed)
    payload["quality"]["zero_unexplained_drift"] = True
    with pytest.raises(ValidationError, match="zero-drift claim"):
        CandidateProfileSet.model_validate(payload)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(checkpoint_sha256="0" * 64),
        lambda value: value.update(previous_checkpoint_sha256="0" * 64),
        lambda value: value.update(journal_event_count=1),
        lambda value: value.update(missing_slot_ids=value["missing_slot_ids"][:-1]),
        lambda value: value.update(extra_unbounded_content="forbidden"),
    ),
)
def test_initial_ledger_tampering_fails_closed(
    profile_set: CandidateProfileSet,
    mutate: Callable[[dict[str, object]], object],
) -> None:
    payload = initial_candidate_profile_attempt_ledger(profile_set.identity).model_dump(
        mode="python"
    )
    mutate(payload)
    with pytest.raises(ValidationError):
        CandidateProfileAttemptLedger.model_validate(payload)


def test_resealed_journal_order_tampering_still_fails(
    open_ledger: CandidateProfileAttemptLedger,
) -> None:
    payload = open_ledger.model_dump(mode="json")
    payload["role_observations"][0]["ledger_index"] = 2
    payload["role_observations"][0]["observation_id"] = "lat-us01-ledger-0002-role"
    with pytest.raises(ValidationError, match="indices must be contiguous"):
        seal_candidate_profile_attempt_ledger(payload)


def test_execution_retry_ids_are_canonical_and_bounded(
    open_ledger: CandidateProfileAttemptLedger,
) -> None:
    slot_id = "catastrophe-recap-cold-json"
    assert next_candidate_profile_execution_id(open_ledger, slot_id).endswith(
        "execution-02"
    )
    with pytest.raises(ValueError, match="1 to 16"):
        candidate_profile_execution_id(slot_id, 17)
    with pytest.raises(ValueError, match="active canonical retry"):
        append_controller_failure(
            open_ledger,
            event_kind="controller_exception",
            slot_id=slot_id,
            execution_id=f"lat-us01-{slot_id}",
            status=AttemptStatus.ERROR,
            failure_code=FailureCode.WORKER_EVIDENCE_ERROR,
            failure_type=FailureType.EVIDENCE_ERROR,
            observed_at_utc=datetime(2026, 8, 9, tzinfo=UTC),
            observed_monotonic_ns=1,
        )


def test_candidate_identity_accepts_new_app_and_dependency_bytes(
    profile_set: CandidateProfileSet,
) -> None:
    payload = profile_set.identity.model_dump(mode="python")
    payload["candidate_code_sha256"] = "5" * 64
    payload["model_artifacts_sha256"] = "6" * 64
    payload["pyproject"]["sha256"] = "7" * 64
    payload["pyproject"]["size_bytes"] = 1_001
    payload["dependency_lock"]["sha256"] = "8" * 64
    payload["dependency_lock"]["size_bytes"] = 2_002
    payload["dependency_manifest_sha256"] = _canonical_hash(
        [
            {
                "path": payload[key]["path"],
                "sha256": payload[key]["sha256"],
                "size_bytes": payload[key]["size_bytes"],
            }
            for key in ("pyproject", "dependency_lock")
        ]
    )
    changed = CandidateExecutionIdentity.model_validate(payload)
    assert changed.candidate_code_sha256 == "5" * 64
    assert changed.dependency_manifest_sha256 == payload["dependency_manifest_sha256"]


@pytest.mark.parametrize("mutation", ("slow_sweep", "sample_time_forgery"))
def test_bounded_skew_sweep_mutations_fail_closed(
    profile_set: CandidateProfileSet,
    mutation: str,
) -> None:
    payload = _payload(profile_set)
    snapshot = payload["concurrent_batch"]["authoritative_round"][
        "bounded_skew_snapshots"
    ][0]
    if mutation == "slow_sweep":
        snapshot["sweep_started_monotonic_ns"] = (
            snapshot["sweep_ended_monotonic_ns"] - 250_000_001
        )
    else:
        snapshot["groups"][0]["sampled_monotonic_ns"] = (
            snapshot["sweep_ended_monotonic_ns"] + 1
        )
    with pytest.raises(ValidationError):
        CandidateProfileSet.model_validate(payload)


def test_two_group_sweep_must_lie_wholly_inside_overlap(
    profile_set: CandidateProfileSet,
) -> None:
    payload = _payload(profile_set)
    snapshots = payload["concurrent_batch"]["authoritative_round"][
        "bounded_skew_snapshots"
    ]
    for snapshot in snapshots:
        snapshot["sweep_started_monotonic_ns"] = 999_999_999
    with pytest.raises(ValidationError, match="bounded-skew aggregate"):
        CandidateProfileSet.model_validate(payload)


def test_profile_custody_rejects_a_symlinked_ledger_before_dereference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_set: CandidateProfileSet,
) -> None:
    retained = tmp_path / "retained-ledger.json"
    retained.write_bytes(canonical_model_bytes(profile_set.attempt_ledger))
    retained.chmod(0o600)
    link = tmp_path / "ledger-link.json"
    link.symlink_to(retained.name)
    monkeypatch.setattr(
        latency_runner,
        "derive_candidate_profile_execution_identity",
        lambda _root: profile_set.identity,
    )

    with pytest.raises(ValueError, match="symlink"):
        latency_runner.verify_candidate_profile_set_custody(
            profile_set,
            workspace=tmp_path,
            ledger_path=link,
        )
