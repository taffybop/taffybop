"""Adversarial v2 resource-boundary and downgrade contracts for LAT-US01.

These controls use synthetic model evidence only.  They never invoke the parser,
LlamaParse, or the all-15 candidate profile runner.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import pairwise

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_contracts import (
    AttemptSlot,
    AttemptStatus,
    CampaignScope,
    FailureCode,
    FailureRecord,
    FailureType,
    LatencyAttempt,
    LatencyCampaign,
    NetworkIsolationEvidence,
    OSNetworkSandboxEvidence,
    OutputIdentity,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    ProcessTreeMetrics,
    ProcessTreeSnapshot,
    ResourceTrackerDisposition,
    StageName,
    StageStatus,
    SystemName,
    WorkerExecutionEvidence,
    WorkerWatchdogEvidence,
)
from tests.benchmarks.latency_instrumentation import root_only_trace
from tests.benchmarks.latency_profile_set import (
    CandidateProfileAttemptLedger,
    CandidateProfileSet,
    _tree_is_complete_and_sane,
    append_attempt_observation,
    append_role_observation,
    candidate_profile_ledger_payload_sha256,
    evaluate_candidate_profile_set,
    initial_candidate_profile_attempt_ledger,
)
from tests.fixtures.phase_latency import factory
from tests.performance.test_latency_profile_set import _profile_set

_REQUEST_STARTED_NS = 1_000_000_000
_REQUEST_DURATION_NS = 20_000_000
_REQUEST_ENDED_NS = _REQUEST_STARTED_NS + _REQUEST_DURATION_NS
_ROOT_IDENTITY = ProcessIdentity(
    pid=41_001,
    create_time_ns=41_001_000_000,
    role=ProcessRole.CANDIDATE_WORKER,
)
_TRACKER_IDENTITY = ProcessIdentity(
    pid=41_002,
    create_time_ns=41_002_000_000,
    role=ProcessRole.RESOURCE_TRACKER,
)


def _metric(
    identity: ProcessIdentity,
    *,
    rss_bytes: int,
    cpu_ns: int,
    hwm_bytes: int | None = None,
) -> ProcessMetric:
    return ProcessMetric(
        identity=identity,
        rss_bytes=rss_bytes,
        user_cpu_ns=cpu_ns,
        system_cpu_ns=0,
        thread_count=1,
        fd_count=3,
        self_hwm_bytes=hwm_bytes,
    )


def _snapshot(
    observed_ns: int,
    members: tuple[ProcessMetric, ...],
) -> ProcessTreeSnapshot:
    return ProcessTreeSnapshot(
        observed_monotonic_ns=observed_ns,
        members=members,
        total_rss_bytes=sum(item.rss_bytes for item in members),
        total_user_cpu_ns=sum(item.user_cpu_ns for item in members),
        total_system_cpu_ns=sum(item.system_cpu_ns for item in members),
        total_thread_count=sum(item.thread_count for item in members),
        total_fd_count=sum(item.fd_count for item in members),
    )


def _v2_tree(
    *,
    with_tracker: bool,
    root_request_cpu_ns: int = 12_000_000,
    reaped_request_cpu_ns: int = 1_000_000,
    baseline_tracker_cpu_ns: int = 5_000_000,
    request_tracker_cpu_ns: int = 8_000_000,
    root_post_response_cpu_ns: int = 2_000_000,
    tracker_post_response_cpu_ns: int = 1_000_000,
) -> ProcessTreeMetrics:
    root_baseline_cpu = 1_000
    root_mid_cpu = root_baseline_cpu + root_request_cpu_ns // 2
    root_response_cpu = root_baseline_cpu + root_request_cpu_ns
    root_closure_cpu = root_response_cpu + root_post_response_cpu_ns

    baseline_members = (
        _metric(
            _ROOT_IDENTITY,
            rss_bytes=700,
            cpu_ns=root_baseline_cpu,
            hwm_bytes=800,
        ),
    )
    mid_members = (
        _metric(
            _ROOT_IDENTITY,
            rss_bytes=850,
            cpu_ns=root_mid_cpu,
            hwm_bytes=1_000,
        ),
    )
    response_members = (
        _metric(
            _ROOT_IDENTITY,
            rss_bytes=900,
            cpu_ns=root_response_cpu,
            hwm_bytes=1_100,
        ),
    )
    if with_tracker:
        baseline_members += (
            _metric(
                _TRACKER_IDENTITY,
                rss_bytes=100,
                cpu_ns=baseline_tracker_cpu_ns,
            ),
        )
        mid_members += (
            _metric(
                _TRACKER_IDENTITY,
                rss_bytes=100,
                cpu_ns=(baseline_tracker_cpu_ns + request_tracker_cpu_ns // 2),
            ),
        )
        response_members += (
            _metric(
                _TRACKER_IDENTITY,
                rss_bytes=100,
                cpu_ns=baseline_tracker_cpu_ns + request_tracker_cpu_ns,
            ),
        )

    snapshots = (
        _snapshot(_REQUEST_STARTED_NS - 5_000_000, baseline_members),
        _snapshot(_REQUEST_STARTED_NS + 10_000_000, mid_members),
        _snapshot(_REQUEST_ENDED_NS + 1, response_members),
        _snapshot(
            _REQUEST_ENDED_NS + 5_000_000,
            (
                _metric(
                    _ROOT_IDENTITY,
                    rss_bytes=920,
                    cpu_ns=root_closure_cpu,
                    hwm_bytes=1_200,
                ),
            ),
        ),
    )
    response_descendant_cpu_ns = (
        baseline_tracker_cpu_ns + request_tracker_cpu_ns if with_tracker else 0
    )
    baseline_descendant_cpu_ns = baseline_tracker_cpu_ns if with_tracker else 0
    lifecycle_reaped_cpu_ns = reaped_request_cpu_ns
    if with_tracker:
        lifecycle_reaped_cpu_ns += (
            response_descendant_cpu_ns + tracker_post_response_cpu_ns
        )
    post_response_cpu_ns = root_post_response_cpu_ns + (
        tracker_post_response_cpu_ns if with_tracker else 0
    )
    request_observed_cpu_ns = root_request_cpu_ns + (
        request_tracker_cpu_ns if with_tracker else 0
    )

    return ProcessTreeMetrics(
        schema_id="phase-latency-process-tree-metrics-v1",
        scope="candidate_worker_and_descendants",
        request_started_monotonic_ns=_REQUEST_STARTED_NS,
        request_ended_monotonic_ns=_REQUEST_ENDED_NS,
        sampling_interval_target_ns=10_000_000,
        hard_maximum_gap_ns=20_000_000,
        maximum_observed_gap_ns=max(
            current.observed_monotonic_ns - previous.observed_monotonic_ns
            for previous, current in pairwise(snapshots)
        ),
        snapshots=snapshots,
        peak_total_rss_bytes=max(item.total_rss_bytes for item in snapshots[:3]),
        peak_worker_hwm_bytes=1_100,
        maximum_observed_process_cpu_ns=request_observed_cpu_ns,
        exact_worker_self_cpu_ns=root_request_cpu_ns,
        exact_reaped_children_cpu_ns=reaped_request_cpu_ns,
        conservative_frozen_response_boundary_descendant_cpu_ns=(
            request_tracker_cpu_ns if with_tracker else 0
        ),
        post_response_lifecycle_cpu_ns=post_response_cpu_ns,
        baseline_descendant_cumulative_cpu_ns=baseline_descendant_cpu_ns,
        response_boundary_descendant_cumulative_cpu_ns=(response_descendant_cpu_ns),
        lifecycle_exact_worker_self_cpu_ns=(
            root_request_cpu_ns + root_post_response_cpu_ns
        ),
        lifecycle_reaped_children_cpu_ns=lifecycle_reaped_cpu_ns,
        reaped_children_hwm_bytes=400,
        conservative_process_lifetime_hwm_bytes=None,
        lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes=1_600,
        resource_boundary_basis=(
            "response-boundary-plus-post-response-reaped-lifecycle-v2"
        ),
        resource_boundary_complete=True,
        response_boundary_snapshot=snapshots[2],
        response_boundary_snapshot_index=2,
        resource_closure_snapshot=snapshots[3],
        response_boundary_descendant_count=int(with_tracker),
        response_boundary_descendant_roles=(
            (ProcessRole.RESOURCE_TRACKER,) if with_tracker else ()
        ),
        resource_closure_complete=True,
        resource_tracker_freeze_disposition=(
            "controller-sigstop-snapshot-sigcont-v1"
            if with_tracker
            else "not_required_root_only"
        ),
        resource_tracker_command_fd=9 if with_tracker else None,
        resource_tracker_worker_write_fd=10 if with_tracker else None,
        resource_tracker_stopped_state_verified=True if with_tracker else None,
        resource_tracker_resumed_state_verified=True if with_tracker else None,
        response_through_resource_closure_peak_total_rss_bytes=max(
            item.total_rss_bytes for item in snapshots[2:]
        ),
        worker_reported_hwm_bytes_at_response_boundary=1_100,
        worker_lifetime_hwm_bytes_at_resource_closure=1_200,
        rss_measurement_basis=("sampled_process_tree_lower_bound_at_bounded_cadence"),
        cpu_measurement_basis="sum_of_per_process_request_cumulative_deltas",
        worker_hwm_measurement_basis="worker_reported_ru_maxrss",
        descendant_observation_basis="recursive_psutil",
        cleanup_disposition="external_worker_reaped",
        worker_reaped=True,
        observed_descendants_reaped=True,
    )


def _v2_network_isolation() -> NetworkIsolationEvidence:
    sandbox = OSNetworkSandboxEvidence(
        policy="macos-sandbox-exec-deny-inet-process-tree-v1",
        platform="Darwin",
        executable_path="/usr/bin/sandbox-exec",
        executable_size_bytes=1,
        executable_sha256="1" * 64,
        profile_size_bytes=1,
        profile_sha256="2" * 64,
        child_guard_size_bytes=1,
        child_guard_sha256="3" * 64,
        inherited_by_descendants=True,
        fresh_subprocess_exit_code=0,
        nested_subprocess_exit_code=0,
        ipv4_tcp_connect="EPERM",
        ipv4_tcp_bind="EPERM",
        ipv4_udp_send="EPERM",
        ipv6_tcp_connect="EPERM",
        ipv6_tcp_bind="EPERM",
        ipv6_udp_send="EPERM",
        filesystem_unix_connect="EPERM",
        unix_socketpair_roundtrip=True,
        child_guard_subprocess_exit_code=0,
        child_guard_bindings_exact=True,
        child_guard_ipv4_socket_create="EPERM",
        child_guard_ipv6_socket_create="EPERM",
        child_guard_getaddrinfo="EPERM",
        child_guard_gethostbyaddr="EPERM",
        child_guard_gethostbyname="EPERM",
        child_guard_gethostbyname_ex="EPERM",
        child_guard_getnameinfo="EPERM",
        child_guard_getfqdn_denied_via_guarded_primitive=True,
        child_guard_ipv6_capability_suppressed=True,
        child_guard_unix_socketpair_roundtrip=True,
        child_guard_denied_attempt_count=8,
    )
    return NetworkIsolationEvidence(
        policy="sanitized-offline-env-python-deny-and-os-process-tree-deny-v2",
        worker_environment_sha256="4" * 64,
        inherited_sensitive_variable_count=0,
        offline_environment_applied=True,
        python_socket_guard_installed=True,
        denied_network_attempt_count=0,
        hosted_calls_completed=0,
        source_bytecode_policy="fresh-empty-pycache-prefix-source-import-v1",
        ipv6_capability_suppressed_with_zero_exit_restore_requirement=True,
        python_guard_restore_disposition="controller-verified-worker-zero-exit",
        os_process_tree_sandbox=sandbox,
    )


def _preexisting_tracker_disposition() -> ResourceTrackerDisposition:
    return ResourceTrackerDisposition(
        policy="disposable-worker-resource-tracker-reap-v1",
        disposition="preexisting_at_baseline_reaped_after_response",
        identity=_TRACKER_IDENTITY,
        tracker_fd=9,
        worker_write_fd=10,
        cleanup_started_monotonic_ns=_REQUEST_ENDED_NS + 2,
        cleanup_ended_monotonic_ns=_REQUEST_ENDED_NS + 3,
        shutdown_api="cpython-multiprocessing-resource-tracker-private-stop",
        exit_code=0,
        no_relaunch_immediately_after_cleanup_verified=True,
        controller_no_relaunch_through_zero_exit_verified=True,
        latency_adjustment_applied=False,
    )


def _cold_attempt_with_preexisting_tracker_payload() -> dict[str, object]:
    slot = AttemptSlot(
        slot_id="synthetic-v2-p01-candidate",
        order_index=1,
        case_id="synthetic-v2",
        pair_index=1,
        system=SystemName.CANDIDATE,
    )
    base = factory.attempt(
        slot,
        total_ns=_REQUEST_DURATION_NS,
        status=AttemptStatus.ERROR,
    )
    tree = _v2_tree(with_tracker=True)
    network = _v2_network_isolation()
    disposition = _preexisting_tracker_disposition()
    payload = base.model_dump(mode="python")
    output = OutputIdentity(
        sha256=factory.SHA_F,
        semantic_sha256=factory.SHA_F,
        size_bytes=100,
        media_type="application/json",
        validation="ParseResult",
        semantic_exclusions=("/processing/duration_ms",),
    )
    watchdog = WorkerWatchdogEvidence(
        schema_id="phase-latency-worker-watchdog-v1",
        exit_code=0,
        outcome="worker_exited",
        worker_kill_attempted=False,
        worker_kill_confirmed=False,
    )
    payload.update(
        attempt_id="synthetic-v2-p01-candidate",
        status=AttemptStatus.SUCCESS,
        evidence_complete=True,
        output=output,
        failure=None,
        stage_trace=factory.stage_trace(_REQUEST_DURATION_NS),
        process_tree=tree,
        diagnostic_total_latency_ns=_REQUEST_DURATION_NS,
        diagnostic_process_tree=tree,
        diagnostic_output=output,
        twin_order="authoritative_then_diagnostic",
        observer_delta_ns=0,
        observer_adjustment_applied=False,
        instrumentation_manifest=factory.instrumentation_manifest(),
        authoritative_cache_state=factory.cache_state(),
        diagnostic_cache_state=factory.cache_state(),
        authoritative_network_isolation=network,
        diagnostic_network_isolation=network,
        authoritative_post_response_validation_duration_ns=10,
        diagnostic_post_response_validation_duration_ns=12,
        authoritative_response_boundary_protocol=(
            "controller-response-freeze-and-post-response-resource-closure-v2"
        ),
        diagnostic_response_boundary_protocol=(
            "controller-response-freeze-and-post-response-resource-closure-v2"
        ),
        authoritative_resource_tracker_disposition=disposition,
        diagnostic_resource_tracker_disposition=disposition,
        authoritative_watchdog=watchdog,
        diagnostic_watchdog=watchdog,
        legacy_v1_authorization=None,
    )
    return payload


@pytest.fixture(scope="module")
def valid_v2_profile() -> CandidateProfileSet:
    return _profile_set()


def test_v2_basis_cannot_use_v1_shaped_process_evidence() -> None:
    payload = factory.process_tree(_REQUEST_DURATION_NS).model_dump(mode="python")
    payload["resource_boundary_basis"] = (
        "response-boundary-plus-post-response-reaped-lifecycle-v2"
    )

    with pytest.raises(ValidationError, match="v2|closure|boundary"):
        ProcessTreeMetrics.model_validate(payload)


def test_v2_closure_shape_cannot_claim_a_v1_resource_basis() -> None:
    payload = _v2_tree(with_tracker=False).model_dump(mode="python")
    payload["resource_boundary_basis"] = (
        "exact-rusage-self-and-reaped-children-before-validation-v1"
    )

    with pytest.raises(ValidationError, match="v2|closure|basis"):
        ProcessTreeMetrics.model_validate(payload)


def test_prewarm_tracker_cpu_subtracts_baseline_and_is_counted_once() -> None:
    tree = _v2_tree(with_tracker=True)
    assert tree.baseline_descendant_cumulative_cpu_ns == 5_000_000
    assert tree.response_boundary_descendant_cumulative_cpu_ns == 13_000_000
    assert tree.conservative_frozen_response_boundary_descendant_cpu_ns == 8_000_000
    assert (
        tree.exact_worker_self_cpu_ns
        + tree.exact_reaped_children_cpu_ns
        + tree.conservative_frozen_response_boundary_descendant_cpu_ns
        == 21_000_000
    )

    # Root plus sampled tracker equals the one-CPU wall bound.  The separately
    # reaped request child pushes the fully accounted total above it, so a gate
    # that omits or double-books the frozen tracker cannot pass this control.
    assert _tree_is_complete_and_sane(tree, logical_cpu_count=1) is False

    overcounted = tree.model_dump(mode="python")
    overcounted["conservative_frozen_response_boundary_descendant_cpu_ns"] = 13_000_000
    with pytest.raises(ValidationError, match="frozen|descendant CPU"):
        ProcessTreeMetrics.model_validate(overcounted)


def test_cold_lifecycle_cannot_claim_a_preexisting_tracker() -> None:
    payload = _cold_attempt_with_preexisting_tracker_payload()

    with pytest.raises(ValidationError, match="cold|preexisting|baseline|lifecycle"):
        LatencyAttempt.model_validate(payload)


def test_tracker_read_and_worker_write_pipe_fds_must_differ() -> None:
    disposition = _preexisting_tracker_disposition().model_dump(mode="python")
    disposition["worker_write_fd"] = disposition["tracker_fd"]
    with pytest.raises(ValidationError, match="endpoint|pipe|differ"):
        ResourceTrackerDisposition.model_validate(disposition)

    tree = _v2_tree(with_tracker=True).model_dump(mode="python")
    tree["resource_tracker_worker_write_fd"] = tree["resource_tracker_command_fd"]
    with pytest.raises(ValidationError, match="freeze|tracker|FD"):
        ProcessTreeMetrics.model_validate(tree)


def test_profile_evaluator_rejects_a_selected_v1_boundary_protocol(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    profile = valid_v2_profile
    first_case = profile.cases[0]
    downgraded_attempt = first_case.cold_json.model_copy(
        update={
            "authoritative_response_boundary_protocol": (
                "controller-terminal-sample-before-post-response-validation-v1"
            ),
            "diagnostic_response_boundary_protocol": (
                "controller-terminal-sample-before-post-response-validation-v1"
            ),
        }
    )
    downgraded_case = first_case.model_copy(update={"cold_json": downgraded_attempt})
    downgraded_profile = profile.model_copy(
        update={"cases": (downgraded_case, *profile.cases[1:])}
    )

    evaluation = evaluate_candidate_profile_set(downgraded_profile)
    assert evaluation.passed is False
    assert "protocol_v2_required" in evaluation.failure_codes


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("resource_tracker_command_fd", None),
        ("resource_tracker_worker_write_fd", None),
        ("resource_tracker_stopped_state_verified", False),
        ("resource_tracker_resumed_state_verified", False),
    ),
)
def test_profile_evaluator_rejects_downgraded_tracker_freeze_proof(
    valid_v2_profile: CandidateProfileSet,
    field: str,
    value: object,
) -> None:
    first_case = valid_v2_profile.cases[0]
    attempt = first_case.cold_json
    assert attempt.process_tree is not None
    changed_attempt = attempt.model_copy(
        update={"process_tree": attempt.process_tree.model_copy(update={field: value})}
    )
    changed_profile = valid_v2_profile.model_copy(
        update={
            "cases": (
                first_case.model_copy(update={"cold_json": changed_attempt}),
                *valid_v2_profile.cases[1:],
            )
        }
    )

    evaluation = evaluate_candidate_profile_set(changed_profile)
    assert evaluation.passed is False
    assert "resource_cpu_sanity_failed" in evaluation.failure_codes


def test_phase_exit_campaign_rejects_a_v1_candidate_boundary() -> None:
    payload = factory.phase_exit_campaign().model_dump(mode="python")
    candidate = next(
        attempt
        for attempt in payload["attempts"]
        if attempt["system"] == SystemName.CANDIDATE
    )
    candidate["authoritative_response_boundary_protocol"] = (
        "controller-terminal-sample-before-post-response-validation-v1"
    )
    candidate["diagnostic_response_boundary_protocol"] = (
        "controller-terminal-sample-before-post-response-validation-v1"
    )

    with pytest.raises(ValidationError, match="phase-exit|protocol|v2"):
        LatencyCampaign.model_validate(payload)


def test_ledger_binds_worker_resource_totals_to_the_assembled_attempt(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    ledger_payload = deepcopy(valid_v2_profile.attempt_ledger.model_dump(mode="json"))
    resource_boundary = ledger_payload["role_observations"][0]["worker_evidence"][
        "resource_boundary"
    ]
    resource_boundary["worker_self_user_cpu_delta_ns"] += 1
    if resource_boundary["basis"].endswith("-v2"):
        resource_boundary["response_boundary_worker_self_user_cpu_delta_ns"] += 1
    ledger_payload["checkpoint_sha256"] = candidate_profile_ledger_payload_sha256(
        ledger_payload
    )

    with pytest.raises(ValidationError, match="worker|resource|attempt"):
        CandidateProfileAttemptLedger.model_validate(ledger_payload)


def test_ledger_binds_response_hwm_to_the_assembled_attempt_tree(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    ledger_payload = deepcopy(valid_v2_profile.attempt_ledger.model_dump(mode="json"))
    worker = ledger_payload["role_observations"][0]["worker_evidence"]
    worker["worker_hwm_bytes_at_response_boundary"] -= 1
    worker["resource_boundary"][
        "response_boundary_worker_process_lifetime_hwm_bytes"
    ] -= 1
    ledger_payload["checkpoint_sha256"] = candidate_profile_ledger_payload_sha256(
        ledger_payload
    )

    with pytest.raises(ValidationError, match="worker|resource|attempt"):
        CandidateProfileAttemptLedger.model_validate(ledger_payload)


def test_ledger_binds_failed_twin_failure_to_the_assembled_attempt(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    attempt = valid_v2_profile.cases[0].cold_json
    retained_roles = {
        item.role: item
        for item in valid_v2_profile.attempt_ledger.role_observations
        if item.execution_id == attempt.attempt_id
    }
    assert set(retained_roles) == {
        "authoritative_uninstrumented",
        "diagnostic_instrumented",
    }
    parse_failure = FailureRecord(
        code=FailureCode.PARSE_FAILED,
        stage=StageName.DOCLING_CONVERSION,
        exception_type=FailureType.REQUEST_EXCEPTION,
    )

    failed_workers: dict[str, WorkerExecutionEvidence] = {}
    for role_name in (
        "authoritative_uninstrumented",
        "diagnostic_instrumented",
    ):
        retained = retained_roles[role_name]
        assert retained.worker_evidence is not None
        worker_payload = retained.worker_evidence.model_dump(mode="python")
        if role_name == "diagnostic_instrumented":
            assert attempt.diagnostic_total_latency_ns is not None
            failed_trace = factory.stage_trace(
                attempt.diagnostic_total_latency_ns,
                status=AttemptStatus.ERROR,
            )
        else:
            failed_trace = root_only_trace(
                request_started_ns=retained.worker_evidence.request_started_monotonic_ns,
                request_ended_ns=retained.worker_evidence.request_ended_monotonic_ns,
                status=StageStatus.ERROR,
                failure_code=FailureCode.PARSE_FAILED,
            )
        worker_payload.update(
            status=AttemptStatus.ERROR,
            http_status=None,
            evidence_complete=False,
            output=None,
            error_response=None,
            failure=parse_failure,
            stage_trace=failed_trace,
        )
        failed_workers[role_name] = WorkerExecutionEvidence.model_validate(
            worker_payload
        )

    failed_attempt_payload = attempt.model_dump(mode="python")
    failed_attempt_payload.update(
        status=AttemptStatus.ERROR,
        evidence_complete=False,
        output=None,
        failure=parse_failure,
        diagnostic_failure=parse_failure,
        failure_stage_parity_policy=(
            "authoritative-root-versus-diagnostic-first-failed-stage-v1"
        ),
        error_response=None,
        stage_trace=failed_workers["diagnostic_instrumented"].stage_trace,
        diagnostic_output=None,
        diagnostic_error_response=None,
    )
    failed_attempt = LatencyAttempt.model_validate(failed_attempt_payload)

    ledger = initial_candidate_profile_attempt_ledger(valid_v2_profile.identity)
    for role_name in (
        "authoritative_uninstrumented",
        "diagnostic_instrumented",
    ):
        retained = retained_roles[role_name]
        ledger = append_role_observation(
            ledger,
            execution_id=attempt.attempt_id,
            slot_id=attempt.slot_id,
            role=role_name,
            status=AttemptStatus.ERROR,
            failure=parse_failure,
            started_at_utc=retained.started_at_utc,
            completed_at_utc=retained.completed_at_utc,
            started_monotonic_ns=retained.started_monotonic_ns,
            ended_monotonic_ns=retained.ended_monotonic_ns,
            worker_evidence=failed_workers[role_name],
            snapshots=retained.snapshots,
            watchdog=retained.watchdog,
        )
    ledger = append_attempt_observation(ledger, failed_attempt)

    ledger_payload = deepcopy(ledger.model_dump(mode="json"))
    authoritative_role = next(
        item
        for item in ledger_payload["role_observations"]
        if item["role"] == "authoritative_uninstrumented"
    )
    changed_failure = FailureRecord(
        code=FailureCode.REQUEST_EXCEPTION,
        stage=StageName.REQUEST_TOTAL,
        exception_type=FailureType.REQUEST_EXCEPTION,
    ).model_dump(mode="json")
    authoritative_role["failure"] = changed_failure
    authoritative_role["worker_evidence"]["failure"] = changed_failure
    authoritative_role["worker_evidence"]["stage_trace"]["spans"][0]["failure_code"] = (
        FailureCode.REQUEST_EXCEPTION
    )
    ledger_payload["checkpoint_sha256"] = candidate_profile_ledger_payload_sha256(
        ledger_payload
    )

    with pytest.raises(ValidationError, match="failed|failure|twin|role"):
        CandidateProfileAttemptLedger.model_validate(ledger_payload)


def test_ledger_binds_normalized_worker_environment_to_execution_identity(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    ledger_payload = deepcopy(valid_v2_profile.attempt_ledger.model_dump(mode="json"))
    execution_id = ledger_payload["attempt_observations"][0]["execution_id"]
    changed_sha256 = "0" * 64
    for role in ledger_payload["role_observations"]:
        if role["execution_id"] == execution_id:
            role["worker_evidence"]["network_isolation"][
                "worker_environment_sha256"
            ] = changed_sha256
    attempt = ledger_payload["attempt_observations"][0]["attempt"]
    attempt["authoritative_network_isolation"]["worker_environment_sha256"] = (
        changed_sha256
    )
    attempt["diagnostic_network_isolation"]["worker_environment_sha256"] = (
        changed_sha256
    )
    ledger_payload["checkpoint_sha256"] = candidate_profile_ledger_payload_sha256(
        ledger_payload
    )

    with pytest.raises(ValidationError, match="environment|identity"):
        CandidateProfileAttemptLedger.model_validate(ledger_payload)


def test_evaluator_rejects_selected_worker_environment_downgrade(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    first_case = valid_v2_profile.cases[0]
    attempt = first_case.cold_json
    changed_sha256 = "0" * 64
    assert attempt.authoritative_network_isolation is not None
    assert attempt.diagnostic_network_isolation is not None
    changed = attempt.model_copy(
        update={
            "authoritative_network_isolation": (
                attempt.authoritative_network_isolation.model_copy(
                    update={"worker_environment_sha256": changed_sha256}
                )
            ),
            "diagnostic_network_isolation": (
                attempt.diagnostic_network_isolation.model_copy(
                    update={"worker_environment_sha256": changed_sha256}
                )
            ),
        }
    )
    changed_profile = valid_v2_profile.model_copy(
        update={
            "cases": (
                first_case.model_copy(update={"cold_json": changed}),
                *valid_v2_profile.cases[1:],
            )
        }
    )

    evaluation = evaluate_candidate_profile_set(changed_profile)
    assert evaluation.passed is False
    assert "cache_or_network_policy_failed" in evaluation.failure_codes


def test_worker_rejects_tracker_cleanup_after_resource_closure_signal(
    valid_v2_profile: CandidateProfileSet,
) -> None:
    worker_payload = deepcopy(
        valid_v2_profile.attempt_ledger.role_observations[0].worker_evidence.model_dump(
            mode="json"
        )
    )
    worker_payload["resource_tracker_disposition"]["cleanup_ended_monotonic_ns"] = (
        worker_payload["resource_closure_signal_monotonic_ns"] + 1
    )

    with pytest.raises(ValidationError, match="cleanup|closure"):
        WorkerExecutionEvidence.model_validate(worker_payload)


def test_v1_is_retained_only_inside_the_explicit_synthetic_campaign_scope() -> None:
    control = factory.campaign()
    candidate_index = next(
        index
        for index, slot in enumerate(control.plan)
        if slot.system is SystemName.CANDIDATE
    )
    legacy_attempt = factory.attempt(
        control.plan[candidate_index],
        total_ns=control.attempts[candidate_index].total_latency_ns,
        v2_resource_lifecycle=False,
    )
    payload = control.model_dump(mode="python")
    payload["attempts"] = list(payload["attempts"])
    payload["attempts"][candidate_index] = legacy_attempt.model_dump(mode="python")

    retained = LatencyCampaign.model_validate(payload)
    assert retained.scope is CampaignScope.SYNTHETIC_CONTROL
    assert retained.attempts[candidate_index].legacy_v1_authorization == (
        "synthetic-control-only-v1"
    )
    assert retained.attempts[
        candidate_index
    ].authoritative_response_boundary_protocol == (
        "controller-terminal-sample-before-post-response-validation-v1"
    )

    payload["attempts"][candidate_index]["legacy_v1_authorization"] = None
    with pytest.raises(ValidationError, match="v1|legacy|synthetic"):
        LatencyCampaign.model_validate(payload)
