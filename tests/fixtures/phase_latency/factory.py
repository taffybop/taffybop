"""Small valid records used to test latency evidence mutations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from tests.benchmarks.latency_campaign import build_interleaved_plan
from tests.benchmarks.latency_contracts import (
    CAMPAIGN_SCHEMA_ID,
    PHASE_EXIT_CORPUS_REGISTRY,
    PHASE_EXIT_ORACLE_ARTIFACT,
    PHASE_EXIT_SOURCE_REGISTRY_SHA256,
    PROCESS_TREE_SCHEMA_ID,
    SCHEMA_VERSION,
    STAGE_TRACE_SCHEMA_ID,
    ArtifactIdentity,
    AttemptSlot,
    AttemptStatus,
    CacheStateEvidence,
    CallableTargetEvidence,
    CampaignScope,
    ConfigurationIdentity,
    EnvironmentIdentityEvidence,
    FailureRecord,
    FailureType,
    InstalledDistributionIdentity,
    InstrumentationManifest,
    LatencyAttempt,
    LatencyCampaign,
    NetworkIsolationEvidence,
    ObserverOverheadEvidence,
    OSNetworkSandboxEvidence,
    OutputIdentity,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    ProcessTreeMetrics,
    ProcessTreeSnapshot,
    ProviderTotalLatencyEvidence,
    ResourceTrackerDisposition,
    RuntimeBinaryIdentity,
    SourceBinding,
    SourceIdentity,
    StageCardinalityPolicy,
    StageName,
    StageSpan,
    StageStatus,
    StageTrace,
    SystemName,
    WorkerLifecycle,
    WorkerWatchdogEvidence,
    configuration_identity_sha256,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def environment_identity() -> EnvironmentIdentityEvidence:
    names = (
        "docling",
        "docling-core",
        "fastapi",
        "httpx",
        "numpy",
        "pdfplumber",
        "pillow",
        "psutil",
        "pydantic",
        "pypdf",
        "pypdfium2",
        "pytesseract",
        "starlette",
        "torch",
        "torchvision",
    )
    distributions = tuple(
        InstalledDistributionIdentity(
            name=name,
            version="2.88.0" if name == "docling-core" else "1.0",
            verified_file_count=1,
            verified_aggregate_bytes=1,
            installed_files_sha256=SHA_A,
            identity_basis=(
                "all-record-hashed-installed-files-with-declared-digests-v1"
            ),
        )
        for name in names
    )
    binaries = tuple(
        RuntimeBinaryIdentity(
            role=role,
            resolved_path_sha256=SHA_B,
            size_bytes=1,
            content_sha256=SHA_C,
            version="1.0" if role != "eng-traineddata" else None,
        )
        for role in ("python", "tesseract", "eng-traineddata")
    )
    value: dict[str, object] = {
        "schema_id": "phase-latency-environment-identity-v1",
        "python_implementation": "CPython",
        "python_version": "3.13.0",
        "python_cache_tag": "cpython-313",
        "system": "Darwin",
        "release": "test",
        "machine": "arm64",
        "cpu_model_sha256": SHA_D,
        "logical_cpu_count": 10,
        "physical_cpu_count": 10,
        "total_memory_bytes": 34_359_738_368,
        "power_thermal_state": "unavailable_uncontrolled",
        "sanitized_worker_environment_sha256": SHA_E,
        "distributions": distributions,
        "binaries": binaries,
        "p00_reference_docling_core_version": "2.87.1",
        "observed_docling_core_version": "2.88.0",
        "p00_comparable": False,
        "noncomparability_reason": "docling-core-2.88.0-vs-p00-2.87.1",
    }
    serializable = {
        key: (
            [item.model_dump(mode="json") for item in item_value]
            if isinstance(item_value, tuple)
            else item_value
        )
        for key, item_value in value.items()
    }
    value["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            serializable,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return EnvironmentIdentityEvidence.model_validate(value)


def source(case_id: str = "ny-timetable") -> SourceIdentity:
    return SourceIdentity(
        case_id=case_id,
        path=f"benchmark-expertmodeldata/{case_id}.pdf",
        filename=f"{case_id}.pdf",
        sha256=SHA_A if case_id == "ny-timetable" else SHA_B,
        size_bytes=26_109 if case_id == "ny-timetable" else 83_589,
        page_count=3,
    )


def configuration(system: SystemName) -> ConfigurationIdentity:
    common: dict[str, object] = {
        "system": system,
        "semantic_request_sha256": SHA_E,
        "output_format": "json",
        "cache_disabled": True,
        "cache_scope": "content_and_result_cache",
        "bounded_concurrency": 1,
    }
    if system is SystemName.CANDIDATE:
        from tests.benchmarks.latency_instrumentation import TARGETS

        observed_stages = {
            StageName.API_PARSE_DISPATCH,
            StageName.DOCLING_CONVERSION,
            StageName.RESPONSE_MATERIALIZATION,
        }
        grouped: dict[str, tuple[StageName, list[str]]] = {}
        for target in TARGETS:
            existing = grouped.setdefault(target.policy_id, (target.stage, []))
            if existing[0] is not target.stage:
                raise AssertionError("fixture target policy stage differs")
            existing[1].append(target.target_id)
        policies = tuple(
            sorted(
                (
                    StageCardinalityPolicy(
                        policy_id=policy_id,
                        stage=stage,
                        minimum_calls=int(stage in observed_stages),
                        maximum_calls=int(stage in observed_stages),
                        condition_id="fixture-always",
                        exclusive_group=None,
                        allow_degraded_on_success=False,
                        target_ids=tuple(sorted(target_ids)),
                    )
                    for policy_id, (stage, target_ids) in grouped.items()
                ),
                key=lambda item: item.policy_id,
            )
        )
        fields = dict(
            **common,
            service="document-parse-api",
            api_version="v1",
            tier=None,
            cost_optimizer=None,
            credits_per_page=None,
            total_latency_metric="asgi_complete_response_bytes",
            worker_lifecycle=WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD,
            prewarm_completed_before_request=False,
            settings_sha256=SHA_F,
            runtime_sha256=SHA_C,
            model_artifacts_sha256=SHA_D,
            required_stage_inventory=tuple(
                sorted(
                    (
                        StageName.API_PARSE_DISPATCH,
                        StageName.DOCLING_CONVERSION,
                        StageName.RESPONSE_MATERIALIZATION,
                    ),
                    key=lambda item: item.value,
                )
            ),
            stage_cardinality_policies=policies,
            internal_reuse_state="process_engine_cache_empty_at_request_start",
            application_startup_completed_before_request=True,
            pipeline_import_state_at_request_start="not_loaded",
            engine_cache_state_at_request_start="module_not_loaded_process_cache_empty",
            filesystem_cache_state="uncontrolled_shared_host_cache",
            content_result_cache_proof_sha256=SHA_A,
        )
        fields["system_configuration_sha256"] = configuration_identity_sha256(fields)
        return ConfigurationIdentity(**fields)
    fields = dict(
        **common,
        service="LlamaCloud Parse",
        api_version="v2",
        tier="Agentic",
        cost_optimizer=False,
        credits_per_page=10,
        total_latency_metric="provider_ui_total_latency",
        worker_lifecycle=WorkerLifecycle.HOSTED_EXACT_UPLOAD,
        prewarm_completed_before_request=False,
        settings_sha256=None,
        runtime_sha256=None,
        model_artifacts_sha256=None,
        required_stage_inventory=(),
        stage_cardinality_policies=(),
        internal_reuse_state="provider_cache_disabled",
        application_startup_completed_before_request=False,
        pipeline_import_state_at_request_start="provider_not_applicable",
        engine_cache_state_at_request_start="provider_cache_disabled",
        filesystem_cache_state="provider_not_observable",
        content_result_cache_proof_sha256=None,
    )
    fields["system_configuration_sha256"] = configuration_identity_sha256(fields)
    return ConfigurationIdentity(**fields)


def stage_trace(
    total_ns: int,
    *,
    status: AttemptStatus = AttemptStatus.SUCCESS,
) -> StageTrace:
    stage_status = StageStatus(status.value)
    failure_code = None if status is AttemptStatus.SUCCESS else "parse_failed"
    started = 1_000_000_000
    spans = (
        StageSpan(
            span_id="request",
            name=StageName.REQUEST_TOTAL,
            parent_span_id=None,
            started_monotonic_ns=started,
            ended_monotonic_ns=started + total_ns,
            status=stage_status,
            failure_code=failure_code,
        ),
        StageSpan(
            span_id="dispatch",
            name=StageName.API_PARSE_DISPATCH,
            parent_span_id="request",
            started_monotonic_ns=started,
            ended_monotonic_ns=started + 1_000_000,
            status=stage_status,
            failure_code=failure_code,
        ),
        StageSpan(
            span_id="parse",
            name=StageName.DOCLING_CONVERSION,
            parent_span_id="request",
            started_monotonic_ns=started + 1_000_000,
            ended_monotonic_ns=started + total_ns - 1_000_000,
            status=stage_status,
            failure_code=failure_code,
        ),
        StageSpan(
            span_id="response",
            name=StageName.RESPONSE_MATERIALIZATION,
            parent_span_id="request",
            started_monotonic_ns=started + total_ns - 1_000_000,
            ended_monotonic_ns=started + total_ns,
            status=(
                StageStatus.SUCCESS if status is AttemptStatus.SUCCESS else stage_status
            ),
            failure_code=(None if status is AttemptStatus.SUCCESS else failure_code),
        ),
    )
    return StageTrace(
        schema_id=STAGE_TRACE_SCHEMA_ID,
        status=stage_status,
        authoritative_total_ns=total_ns,
        collector_started_monotonic_ns=started,
        collector_finished_monotonic_ns=started + total_ns,
        pre_collector_duration_ns=0,
        post_collector_duration_ns=0,
        attributed_top_level_union_ns=total_ns,
        unattributed_remainder_ns=0,
        spans=spans,
    )


def _worker_metric(*, rss: int, hwm: int, cpu: int) -> ProcessMetric:
    return ProcessMetric(
        identity=ProcessIdentity(
            pid=4101,
            create_time_ns=123_000_000,
            role=ProcessRole.CANDIDATE_WORKER,
        ),
        rss_bytes=rss,
        user_cpu_ns=cpu,
        system_cpu_ns=cpu // 4,
        thread_count=4,
        fd_count=12,
        self_hwm_bytes=hwm,
    )


def _tesseract_metric() -> ProcessMetric:
    return ProcessMetric(
        identity=ProcessIdentity(
            pid=4102,
            create_time_ns=124_000_000,
            role=ProcessRole.TESSERACT,
        ),
        rss_bytes=25,
        user_cpu_ns=5,
        system_cpu_ns=1,
        thread_count=1,
        fd_count=3,
        self_hwm_bytes=None,
    )


def _snapshot(
    observed_ns: int, members: Sequence[ProcessMetric]
) -> ProcessTreeSnapshot:
    values = tuple(members)
    return ProcessTreeSnapshot(
        observed_monotonic_ns=observed_ns,
        members=values,
        total_rss_bytes=sum(item.rss_bytes for item in values),
        total_user_cpu_ns=sum(item.user_cpu_ns for item in values),
        total_system_cpu_ns=sum(item.system_cpu_ns for item in values),
        total_thread_count=sum(item.thread_count for item in values),
        total_fd_count=sum(item.fd_count for item in values),
    )


def process_tree(total_ns: int = 20_000_000) -> ProcessTreeMetrics:
    request_started_ns = 1_000_000_000
    request_ended_ns = request_started_ns + total_ns
    timestamps = [request_started_ns - 5_000_000]
    current = request_started_ns
    while current < request_ended_ns:
        timestamps.append(current)
        current += 5_000_000
    if timestamps[-1] != request_ended_ns:
        timestamps.append(request_ended_ns)
    timestamps.append(request_ended_ns + 5_000_000)
    active_index = max(1, (len(timestamps) - 1) // 2)
    snapshots = tuple(
        _snapshot(
            observed_ns,
            (
                (
                    _worker_metric(rss=100, hwm=100, cpu=0)
                    if index == 0
                    else _worker_metric(
                        rss=150 if index == active_index else 120,
                        hwm=150,
                        cpu=index * 10,
                    )
                ),
                *(() if index != active_index else (_tesseract_metric(),)),
            ),
        )
        for index, observed_ns in enumerate(timestamps)
    )
    gaps = tuple(
        current.observed_monotonic_ns - previous.observed_monotonic_ns
        for previous, current in pairwise(snapshots)
    )
    final_root_cpu = (
        snapshots[-1].members[0].user_cpu_ns + snapshots[-1].members[0].system_cpu_ns
    )
    transient_child_cpu = sum(
        member.user_cpu_ns + member.system_cpu_ns
        for member in snapshots[active_index].members[1:]
    )
    return ProcessTreeMetrics(
        schema_id=PROCESS_TREE_SCHEMA_ID,
        scope="candidate_worker_and_descendants",
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
        sampling_interval_target_ns=5_000_000,
        hard_maximum_gap_ns=5_000_000,
        maximum_observed_gap_ns=max(gaps),
        snapshots=snapshots,
        peak_total_rss_bytes=max(item.total_rss_bytes for item in snapshots),
        peak_worker_hwm_bytes=150,
        maximum_observed_process_cpu_ns=(final_root_cpu + transient_child_cpu),
        exact_worker_self_cpu_ns=final_root_cpu,
        exact_reaped_children_cpu_ns=0,
        reaped_children_hwm_bytes=0,
        conservative_process_lifetime_hwm_bytes=150,
        resource_boundary_basis="same-process-rusage-self-v1",
        resource_boundary_complete=True,
        rss_measurement_basis=("sampled_process_tree_lower_bound_at_bounded_cadence"),
        cpu_measurement_basis="sum_of_per_process_request_cumulative_deltas",
        worker_hwm_measurement_basis="same_process_ru_maxrss",
        descendant_observation_basis="recursive_psutil",
        cleanup_disposition="same_process_restored",
        worker_reaped=False,
        observed_descendants_reaped=True,
    )


def process_tree_v2(
    total_ns: int = 20_000_000,
    *,
    root_pid: int = 4_101,
    worker_hwm_bytes: int = 150,
    tracker_preexisting: bool = False,
) -> ProcessTreeMetrics:
    """Return genuine synthetic v2 response/cleanup resource evidence."""

    request_started_ns = 1_000_000_000
    request_ended_ns = request_started_ns + total_ns
    response_observed_ns = request_ended_ns + 1
    closure_observed_ns = request_ended_ns + 5_000_000
    root_identity = ProcessIdentity(
        pid=root_pid,
        create_time_ns=root_pid * 1_000_000,
        role=ProcessRole.CANDIDATE_WORKER,
    )
    tracker_identity = ProcessIdentity(
        pid=root_pid + 1,
        create_time_ns=(root_pid + 1) * 1_000_000,
        role=ProcessRole.RESOURCE_TRACKER,
    )

    root_baseline_user_ns = 1_000
    root_baseline_system_ns = 250
    root_request_user_ns = max(1, total_ns // 10)
    root_request_system_ns = max(1, total_ns // 40)
    root_cleanup_user_ns = 100
    root_cleanup_system_ns = 25
    tracker_baseline_user_ns = 1_000 if tracker_preexisting else 0
    tracker_baseline_system_ns = 250 if tracker_preexisting else 0
    tracker_request_user_ns = max(1, total_ns // 50)
    tracker_request_system_ns = max(1, total_ns // 100)
    tracker_cleanup_user_ns = 50
    tracker_cleanup_system_ns = 10

    def worker_metric(
        *, rss_bytes: int, user_cpu_ns: int, system_cpu_ns: int
    ) -> ProcessMetric:
        return ProcessMetric(
            identity=root_identity,
            rss_bytes=rss_bytes,
            user_cpu_ns=user_cpu_ns,
            system_cpu_ns=system_cpu_ns,
            thread_count=4,
            fd_count=12,
            self_hwm_bytes=worker_hwm_bytes,
        )

    def tracker_metric(*, user_cpu_ns: int, system_cpu_ns: int) -> ProcessMetric:
        return ProcessMetric(
            identity=tracker_identity,
            rss_bytes=25,
            user_cpu_ns=user_cpu_ns,
            system_cpu_ns=system_cpu_ns,
            thread_count=1,
            fd_count=3,
            self_hwm_bytes=None,
        )

    baseline_members = (
        worker_metric(
            rss_bytes=100,
            user_cpu_ns=root_baseline_user_ns,
            system_cpu_ns=root_baseline_system_ns,
        ),
    )
    if tracker_preexisting:
        baseline_members += (
            tracker_metric(
                user_cpu_ns=tracker_baseline_user_ns,
                system_cpu_ns=tracker_baseline_system_ns,
            ),
        )
    midpoint_members = (
        worker_metric(
            rss_bytes=110,
            user_cpu_ns=root_baseline_user_ns + root_request_user_ns // 2,
            system_cpu_ns=(root_baseline_system_ns + root_request_system_ns // 2),
        ),
        tracker_metric(
            user_cpu_ns=(tracker_baseline_user_ns + tracker_request_user_ns // 2),
            system_cpu_ns=(tracker_baseline_system_ns + tracker_request_system_ns // 2),
        ),
    )
    response_members = (
        worker_metric(
            rss_bytes=120,
            user_cpu_ns=root_baseline_user_ns + root_request_user_ns,
            system_cpu_ns=root_baseline_system_ns + root_request_system_ns,
        ),
        tracker_metric(
            user_cpu_ns=tracker_baseline_user_ns + tracker_request_user_ns,
            system_cpu_ns=(tracker_baseline_system_ns + tracker_request_system_ns),
        ),
    )
    closure_members = (
        worker_metric(
            rss_bytes=115,
            user_cpu_ns=(
                root_baseline_user_ns + root_request_user_ns + root_cleanup_user_ns
            ),
            system_cpu_ns=(
                root_baseline_system_ns
                + root_request_system_ns
                + root_cleanup_system_ns
            ),
        ),
    )
    snapshots = (
        _snapshot(request_started_ns - 5_000_000, baseline_members),
        _snapshot(request_started_ns, baseline_members),
        _snapshot(request_started_ns + max(1, total_ns // 2), midpoint_members),
        _snapshot(response_observed_ns, response_members),
        _snapshot(closure_observed_ns, closure_members),
    )
    maximum_gap_ns = max(
        current.observed_monotonic_ns - previous.observed_monotonic_ns
        for previous, current in pairwise(snapshots)
    )
    request_worker_cpu_ns = root_request_user_ns + root_request_system_ns
    request_tracker_cpu_ns = tracker_request_user_ns + tracker_request_system_ns
    baseline_tracker_cpu_ns = tracker_baseline_user_ns + tracker_baseline_system_ns
    response_tracker_cpu_ns = baseline_tracker_cpu_ns + request_tracker_cpu_ns
    root_cleanup_cpu_ns = root_cleanup_user_ns + root_cleanup_system_ns
    tracker_cleanup_cpu_ns = tracker_cleanup_user_ns + tracker_cleanup_system_ns

    return ProcessTreeMetrics(
        schema_id=PROCESS_TREE_SCHEMA_ID,
        scope="candidate_worker_and_descendants",
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
        sampling_interval_target_ns=maximum_gap_ns,
        hard_maximum_gap_ns=maximum_gap_ns,
        maximum_observed_gap_ns=maximum_gap_ns,
        snapshots=snapshots,
        peak_total_rss_bytes=max(
            snapshot.total_rss_bytes for snapshot in snapshots[:4]
        ),
        peak_worker_hwm_bytes=worker_hwm_bytes,
        maximum_observed_process_cpu_ns=(
            request_worker_cpu_ns + request_tracker_cpu_ns
        ),
        exact_worker_self_cpu_ns=request_worker_cpu_ns,
        exact_reaped_children_cpu_ns=0,
        conservative_frozen_response_boundary_descendant_cpu_ns=(
            request_tracker_cpu_ns
        ),
        post_response_lifecycle_cpu_ns=(root_cleanup_cpu_ns + tracker_cleanup_cpu_ns),
        baseline_descendant_cumulative_cpu_ns=baseline_tracker_cpu_ns,
        response_boundary_descendant_cumulative_cpu_ns=(response_tracker_cpu_ns),
        lifecycle_exact_worker_self_cpu_ns=(
            request_worker_cpu_ns + root_cleanup_cpu_ns
        ),
        lifecycle_reaped_children_cpu_ns=(
            response_tracker_cpu_ns + tracker_cleanup_cpu_ns
        ),
        reaped_children_hwm_bytes=25,
        conservative_process_lifetime_hwm_bytes=None,
        lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes=(
            worker_hwm_bytes + 25
        ),
        resource_boundary_basis=(
            "response-boundary-plus-post-response-reaped-lifecycle-v2"
        ),
        resource_boundary_complete=True,
        response_boundary_snapshot=snapshots[3],
        response_boundary_snapshot_index=3,
        resource_closure_snapshot=snapshots[4],
        response_boundary_descendant_count=1,
        response_boundary_descendant_roles=(ProcessRole.RESOURCE_TRACKER,),
        resource_closure_complete=True,
        resource_tracker_freeze_disposition=("controller-sigstop-snapshot-sigcont-v1"),
        resource_tracker_command_fd=9,
        resource_tracker_worker_write_fd=10,
        resource_tracker_stopped_state_verified=True,
        resource_tracker_resumed_state_verified=True,
        response_through_resource_closure_peak_total_rss_bytes=max(
            snapshot.total_rss_bytes for snapshot in snapshots[3:]
        ),
        worker_reported_hwm_bytes_at_response_boundary=worker_hwm_bytes,
        worker_lifetime_hwm_bytes_at_resource_closure=worker_hwm_bytes,
        rss_measurement_basis=("sampled_process_tree_lower_bound_at_bounded_cadence"),
        cpu_measurement_basis="sum_of_per_process_request_cumulative_deltas",
        worker_hwm_measurement_basis="worker_reported_ru_maxrss",
        descendant_observation_basis="recursive_psutil",
        cleanup_disposition="external_worker_reaped",
        worker_reaped=True,
        observed_descendants_reaped=True,
    )
    cpu_baselines: dict[tuple[int, int], int] = {}
    cpu_maxima: dict[tuple[int, int], int] = {}
    for snapshot in snapshots:
        for member in snapshot.members:
            identity = (member.identity.pid, member.identity.create_time_ns)
            cumulative = member.user_cpu_ns + member.system_cpu_ns
            if identity not in cpu_baselines:
                cpu_baselines[identity] = (
                    cumulative
                    if snapshot.observed_monotonic_ns <= request_started_ns
                    else 0
                )
            cpu_maxima[identity] = max(
                cpu_maxima.get(identity, cumulative),
                cumulative,
            )
    return ProcessTreeMetrics(
        schema_id=PROCESS_TREE_SCHEMA_ID,
        scope="candidate_worker_and_descendants",
        request_started_monotonic_ns=request_started_ns,
        request_ended_monotonic_ns=request_ended_ns,
        sampling_interval_target_ns=5_000_000,
        hard_maximum_gap_ns=10_000_000,
        maximum_observed_gap_ns=max(
            current.observed_monotonic_ns - previous.observed_monotonic_ns
            for previous, current in pairwise(snapshots)
        ),
        snapshots=snapshots,
        peak_total_rss_bytes=175,
        peak_worker_hwm_bytes=150,
        maximum_observed_process_cpu_ns=sum(
            maximum - cpu_baselines[identity]
            for identity, maximum in cpu_maxima.items()
        ),
        exact_worker_self_cpu_ns=150,
        exact_reaped_children_cpu_ns=0,
        reaped_children_hwm_bytes=0,
        conservative_process_lifetime_hwm_bytes=150,
        resource_boundary_basis="same-process-rusage-self-v1",
        resource_boundary_complete=True,
        rss_measurement_basis="sampled_process_tree_lower_bound_at_bounded_cadence",
        cpu_measurement_basis="sum_of_per_process_request_cumulative_deltas",
        worker_hwm_measurement_basis="same_process_ru_maxrss",
        descendant_observation_basis="recursive_psutil",
        cleanup_disposition="same_process_restored",
        worker_reaped=False,
        observed_descendants_reaped=True,
    )


def instrumentation_manifest() -> InstrumentationManifest:
    from tests.benchmarks.latency_instrumentation import TARGETS

    installed_ids = {
        "api-json-response",
        "api-parse-dispatch",
        "pipeline-docling-conversion",
    }
    signature = "(*args: Any, **kwargs: Any) -> Any"
    targets = tuple(
        sorted(
            (
                CallableTargetEvidence(
                    target_id=definition.target_id,
                    stage=definition.stage,
                    module=definition.source_module,
                    attribute=definition.attribute,
                    qualname=definition.source_attribute,
                    source=ArtifactIdentity(
                        path="tests/fixtures/phase_latency/factory.py",
                        sha256=SHA_A,
                        size_bytes=1,
                    ),
                    signature=signature,
                    signature_sha256=hashlib.sha256(signature.encode()).hexdigest(),
                    callable_kind=(
                        "class_binding"
                        if definition.strategy == "response_constructor"
                        else "bound_method"
                        if definition.strategy == "natural_instance_get_pipeline"
                        else "async_function"
                        if definition.strategy == "exception_only_async"
                        else "sync_function"
                    ),
                    code_sha256=SHA_B,
                    wrapper_strategy=definition.strategy,
                    classifier_id=definition.classifier_id,
                    cardinality_policy_id=definition.policy_id,
                    installed=definition.target_id in installed_ids,
                    invocation_count=int(definition.target_id in installed_ids),
                    pre_binding_sha256=(
                        SHA_C if definition.target_id in installed_ids else None
                    ),
                    installed_binding_sha256=(
                        SHA_D if definition.target_id in installed_ids else None
                    ),
                    post_restore_binding_sha256=(
                        SHA_C if definition.target_id in installed_ids else None
                    ),
                    restored_exact_binding=(
                        True if definition.target_id in installed_ids else None
                    ),
                )
                for definition in TARGETS
            ),
            key=lambda item: item.target_id,
        )
    )
    files = tuple(
        ArtifactIdentity(path=path, sha256=SHA_A, size_bytes=1)
        for path in (
            "tests/benchmarks/latency_campaign.py",
            "tests/benchmarks/latency_child_guard/sitecustomize.py",
            "tests/benchmarks/latency_contracts.py",
            "tests/benchmarks/latency_instrumentation.py",
            "tests/benchmarks/latency_isolation.py",
            "tests/benchmarks/latency_network_probe.py",
            "tests/benchmarks/latency_runner.py",
            "tests/benchmarks/latency_watchdog.py",
            "tests/benchmarks/latency_worker.py",
        )
    )
    overhead = ObserverOverheadEvidence(
        calibration_id="external_exception_wrapper_noop_v1",
        call_count=256,
        unwrapped_total_ns=100,
        wrapped_total_ns=120,
        absolute_delta_ns=20,
        adjustment_applied=False,
    )
    value: dict[str, object] = {
        "schema_id": "phase-latency-external-observer-manifest-v1",
        "schema_version": "1.0",
        "observer_mode": "diagnostic_external_test_instrumentation",
        "observer_version": "lat-us01-v1",
        "authoritative_total_policy": (
            "separate_uninstrumented_twin_no_observer_subtraction"
        ),
        "harness_files": files,
        "targets": targets,
        "installed_target_count": 3,
        "request_collector_id": "external-request-scoped-perf-counter-ns-v1",
        "import_hook_finder_id": "phase-latency-scoped-meta-path-finder-v1",
        "import_hook_loader_id": "phase-latency-scoped-loader-v1",
        "python_implementation": "CPython",
        "python_version": "3.13.0",
        "runtime_sha256": SHA_C,
        "dependency_lock_sha256": SHA_B,
        "docling_version": "2.114.0",
        "docling_get_pipeline_signature_sha256": SHA_E,
        "docling_get_pipeline_disposition": "not_observed",
        "observer_overhead": overhead,
        "hosted_calls": 0,
    }
    serializable = {
        key: (
            [item.model_dump(mode="json") for item in item_value]
            if isinstance(item_value, tuple)
            else item_value.model_dump(mode="json")
            if hasattr(item_value, "model_dump")
            else item_value
        )
        for key, item_value in value.items()
    }
    value["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            serializable,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return InstrumentationManifest.model_validate(value)


def cache_state() -> CacheStateEvidence:
    return CacheStateEvidence(
        profile="request_cold_after_app_startup",
        application_startup_completed=True,
        pipeline_loaded_at_request_start=False,
        converter_cache_entries_at_request_start=0,
        converter_cache_entries_after_request=1,
        prewarm_request_completed=False,
        content_result_cache_observed=False,
        content_result_cache_proof_sha256=SHA_A,
        filesystem_cache_state="uncontrolled_shared_host_cache",
    )


def network_isolation() -> NetworkIsolationEvidence:
    return NetworkIsolationEvidence(
        policy="sanitized-offline-env-and-python-af-inet-deny-v1",
        worker_environment_sha256=SHA_E,
        inherited_sensitive_variable_count=0,
        offline_environment_applied=True,
        python_socket_guard_installed=True,
        denied_network_attempt_count=0,
        hosted_calls_completed=0,
        source_bytecode_policy="fresh-empty-pycache-prefix-source-import-v1",
    )


def network_isolation_v2() -> NetworkIsolationEvidence:
    return NetworkIsolationEvidence(
        policy="sanitized-offline-env-python-deny-and-os-process-tree-deny-v2",
        worker_environment_sha256=SHA_E,
        inherited_sensitive_variable_count=0,
        offline_environment_applied=True,
        python_socket_guard_installed=True,
        denied_network_attempt_count=0,
        hosted_calls_completed=0,
        source_bytecode_policy="fresh-empty-pycache-prefix-source-import-v1",
        ipv6_capability_suppressed_with_zero_exit_restore_requirement=True,
        python_guard_restore_disposition="controller-verified-worker-zero-exit",
        os_process_tree_sandbox=OSNetworkSandboxEvidence(
            policy="macos-sandbox-exec-deny-inet-process-tree-v1",
            platform="Darwin",
            executable_path="/usr/bin/sandbox-exec",
            executable_size_bytes=1,
            executable_sha256=SHA_A,
            profile_size_bytes=1,
            profile_sha256=SHA_B,
            child_guard_size_bytes=1,
            child_guard_sha256=SHA_C,
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
        ),
    )


def resource_tracker_disposition_v2(
    tree: ProcessTreeMetrics,
    *,
    tracker_preexisting: bool,
) -> ResourceTrackerDisposition:
    response = tree.response_boundary_snapshot
    if response is None or len(response.members) != 2:
        raise ValueError("v2 tracker fixture requires one response descendant")
    return ResourceTrackerDisposition(
        policy="disposable-worker-resource-tracker-reap-v1",
        disposition=(
            "preexisting_at_baseline_reaped_after_response"
            if tracker_preexisting
            else "started_during_request_reaped_after_response"
        ),
        identity=response.members[1].identity,
        tracker_fd=tree.resource_tracker_command_fd,
        worker_write_fd=tree.resource_tracker_worker_write_fd,
        cleanup_started_monotonic_ns=tree.request_ended_monotonic_ns + 2,
        cleanup_ended_monotonic_ns=tree.request_ended_monotonic_ns + 3,
        shutdown_api="cpython-multiprocessing-resource-tracker-private-stop",
        exit_code=0,
        no_relaunch_immediately_after_cleanup_verified=True,
        controller_no_relaunch_through_zero_exit_verified=True,
        latency_adjustment_applied=False,
    )


def attempt(
    slot: AttemptSlot,
    *,
    total_ns: int,
    status: AttemptStatus = AttemptStatus.SUCCESS,
    v2_resource_lifecycle: bool = True,
) -> LatencyAttempt:
    succeeded = status is AttemptStatus.SUCCESS
    candidate_v2 = (
        slot.system is SystemName.CANDIDATE and succeeded and v2_resource_lifecycle
    )
    candidate_tree = (
        process_tree_v2(total_ns)
        if candidate_v2
        else process_tree(total_ns)
        if slot.system is SystemName.CANDIDATE
        else None
    )
    tracker_disposition = (
        resource_tracker_disposition_v2(
            candidate_tree,
            tracker_preexisting=False,
        )
        if candidate_v2 and candidate_tree is not None
        else None
    )
    started_at = datetime(2026, 8, 8, 12, tzinfo=UTC) + timedelta(
        seconds=slot.order_index
    )
    completed_at = started_at + timedelta(microseconds=max(1, total_ns // 1_000))
    return LatencyAttempt(
        attempt_id=f"attempt-{slot.slot_id}",
        slot_id=slot.slot_id,
        order_index=slot.order_index,
        case_id=slot.case_id,
        pair_index=slot.pair_index,
        system=slot.system,
        source=source(slot.case_id),
        source_binding=(
            SourceBinding.WORKSPACE_BYTES
            if slot.system is SystemName.CANDIDATE
            else SourceBinding.EXACT_BYTE_UPLOAD
        ),
        configuration=configuration(slot.system),
        candidate_code_sha256=(SHA_A if slot.system is SystemName.CANDIDATE else None),
        dependency_lock_sha256=(SHA_B if slot.system is SystemName.CANDIDATE else None),
        environment_sha256=(SHA_C if slot.system is SystemName.CANDIDATE else None),
        model_artifacts_sha256=(SHA_D if slot.system is SystemName.CANDIDATE else None),
        status=status,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        total_latency_ns=total_ns,
        cache_hit=False,
        evidence_complete=succeeded,
        output=(
            OutputIdentity(
                sha256=SHA_F,
                semantic_sha256=SHA_F,
                size_bytes=100,
                media_type=(
                    "application/json"
                    if slot.system is SystemName.CANDIDATE
                    else "application/octet-stream"
                ),
                validation=(
                    "ParseResult"
                    if slot.system is SystemName.CANDIDATE
                    else "provider_retained_artifact"
                ),
                semantic_exclusions=(
                    ("/processing/duration_ms",)
                    if slot.system is SystemName.CANDIDATE
                    else ()
                ),
                retained_artifact=(
                    ArtifactIdentity(
                        path=(
                            "tests/fixtures/phase_latency/provider-output-"
                            f"{slot.case_id}-p{slot.pair_index:02d}.bin"
                        ),
                        sha256=SHA_F,
                        size_bytes=100,
                    )
                    if slot.system is SystemName.LLAMAPARSE
                    else None
                ),
            )
            if succeeded
            else None
        ),
        failure=(
            None
            if succeeded
            else FailureRecord(
                code="parse_failed",
                stage=StageName.DOCLING_CONVERSION,
                exception_type=FailureType.REQUEST_EXCEPTION,
            )
        ),
        stage_trace=(
            stage_trace(total_ns, status=status)
            if slot.system is SystemName.CANDIDATE
            else None
        ),
        process_tree=(candidate_tree),
        diagnostic_total_latency_ns=(
            total_ns if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        diagnostic_process_tree=(
            candidate_tree
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        diagnostic_output=(
            OutputIdentity(
                sha256=SHA_F,
                semantic_sha256=SHA_F,
                size_bytes=100,
                media_type="application/json",
                validation="ParseResult",
                semantic_exclusions=("/processing/duration_ms",),
                retained_artifact=None,
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        twin_order=(
            (
                "authoritative_then_diagnostic"
                if slot.pair_index % 2
                else "diagnostic_then_authoritative"
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        observer_delta_ns=(
            0 if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        observer_adjustment_applied=(
            False if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        instrumentation_manifest=(
            instrumentation_manifest()
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        authoritative_cache_state=(
            cache_state() if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        diagnostic_cache_state=(
            cache_state() if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        authoritative_network_isolation=(
            (network_isolation_v2() if candidate_v2 else network_isolation())
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        diagnostic_network_isolation=(
            (network_isolation_v2() if candidate_v2 else network_isolation())
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        authoritative_post_response_validation_duration_ns=(
            10 if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        diagnostic_post_response_validation_duration_ns=(
            12 if slot.system is SystemName.CANDIDATE and succeeded else None
        ),
        authoritative_response_boundary_protocol=(
            (
                "controller-response-freeze-and-post-response-resource-closure-v2"
                if candidate_v2
                else "controller-terminal-sample-before-post-response-validation-v1"
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        diagnostic_response_boundary_protocol=(
            (
                "controller-response-freeze-and-post-response-resource-closure-v2"
                if candidate_v2
                else "controller-terminal-sample-before-post-response-validation-v1"
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        authoritative_resource_tracker_disposition=tracker_disposition,
        diagnostic_resource_tracker_disposition=tracker_disposition,
        authoritative_watchdog=(
            WorkerWatchdogEvidence(
                schema_id="phase-latency-worker-watchdog-v1",
                exit_code=0,
                outcome="worker_exited",
                worker_kill_attempted=False,
                worker_kill_confirmed=False,
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        diagnostic_watchdog=(
            WorkerWatchdogEvidence(
                schema_id="phase-latency-worker-watchdog-v1",
                exit_code=0,
                outcome="worker_exited",
                worker_kill_attempted=False,
                worker_kill_confirmed=False,
            )
            if slot.system is SystemName.CANDIDATE and succeeded
            else None
        ),
        provider_total_latency=(
            ProviderTotalLatencyEvidence(
                metric="provider_ui_total_latency",
                status="COMPLETED",
                job_id=(f"pjb-{slot.case_id.replace('-', '')}{slot.pair_index:02d}"),
                display_value=f"{total_ns / 1_000_000_000:.3f}s",
                observed_at_utc=completed_at + timedelta(seconds=1),
                retained_ui_evidence=ArtifactIdentity(
                    path=(
                        "tests/fixtures/phase_latency/provider-ui-"
                        f"{slot.case_id}-p{slot.pair_index:02d}.png"
                    ),
                    sha256=SHA_B,
                    size_bytes=1,
                ),
                normalized_display_ns=total_ns,
                rounding_quantum_ns=1_000_000,
                lower_bound_inclusive_ns=max(0, total_ns - 500_000),
                upper_bound_exclusive_ns=total_ns + 500_000,
                rounding_rule="nearest_display_quantum_half_open",
            )
            if slot.system is SystemName.LLAMAPARSE and succeeded
            else None
        ),
        legacy_v1_authorization=(
            "synthetic-control-only-v1"
            if slot.system is SystemName.CANDIDATE and not v2_resource_lifecycle
            else None
        ),
    )


def campaign(
    *,
    case_ids: Sequence[str] = ("ny-timetable",),
    candidate_ns: Sequence[int] = (
        80_000_000,
        90_000_000,
        100_000_000,
        110_000_000,
        120_000_000,
    ),
    llamaparse_ns: Sequence[int] = (
        100_000_000,
        110_000_000,
        120_000_000,
        130_000_000,
        140_000_000,
    ),
    failures: Mapping[tuple[str, int, SystemName], AttemptStatus] | None = None,
) -> LatencyCampaign:
    if len(candidate_ns) != len(llamaparse_ns):
        raise ValueError("fixture sample arrays must have equal length")
    plan = build_interleaved_plan(case_ids, sample_count=len(candidate_ns))
    failures = failures or {}
    attempts: list[LatencyAttempt] = []
    for slot in plan:
        samples = candidate_ns if slot.system is SystemName.CANDIDATE else llamaparse_ns
        attempts.append(
            attempt(
                slot,
                total_ns=samples[slot.pair_index - 1],
                status=failures.get(
                    (slot.case_id, slot.pair_index, slot.system),
                    AttemptStatus.SUCCESS,
                ),
                v2_resource_lifecycle=False,
            )
        )
    return LatencyCampaign(
        schema_version=SCHEMA_VERSION,
        schema_id=CAMPAIGN_SCHEMA_ID,
        campaign_id="lat-us01-test-campaign",
        scope=CampaignScope.SYNTHETIC_CONTROL,
        candidate_code_sha256=SHA_A,
        dependency_lock_sha256=SHA_B,
        environment_sha256=SHA_C,
        model_artifacts_sha256=SHA_D,
        authorized_hosted_credit_limit=1_500,
        hosted_credits_used=sum(
            item.source.page_count * int(item.configuration.credits_per_page or 0)
            for item in attempts
            if item.system is SystemName.LLAMAPARSE
        ),
        minimum_samples_per_case_per_system=len(candidate_ns),
        plan=plan,
        attempts=tuple(attempts),
    )


def phase_exit_campaign() -> LatencyCampaign:
    """Closed all-15 synthetic record used only for contract mutation tests."""

    from tests.fixtures.phase_03.running_regions.oracle import SOURCE_IDENTITIES

    plan = build_interleaved_plan(tuple(SOURCE_IDENTITIES), sample_count=5)
    attempts = tuple(
        attempt(
            slot,
            total_ns=(
                (80_000_000, 90_000_000, 100_000_000, 110_000_000, 120_000_000)
                if slot.system is SystemName.CANDIDATE
                else (100_000_000, 110_000_000, 120_000_000, 130_000_000, 140_000_000)
            )[slot.pair_index - 1],
            v2_resource_lifecycle=True,
        )
        for slot in plan
    )
    retained_environment = environment_identity()
    value = {
        "schema_version": SCHEMA_VERSION,
        "schema_id": CAMPAIGN_SCHEMA_ID,
        "campaign_id": "lat-us08-phase-exit-control",
        "scope": CampaignScope.PHASE_EXIT_ALL_15.value,
        "candidate_code_sha256": SHA_A,
        "dependency_lock_sha256": SHA_B,
        "environment_sha256": retained_environment.manifest_sha256,
        "environment_manifest": retained_environment.model_dump(mode="json"),
        "model_artifacts_sha256": SHA_D,
        "corpus_registry": PHASE_EXIT_CORPUS_REGISTRY,
        "phase03_oracle_artifact": PHASE_EXIT_ORACLE_ARTIFACT,
        "source_registry_sha256": PHASE_EXIT_SOURCE_REGISTRY_SHA256,
        "provider_evidence_registry": {
            "path": "tests/fixtures/phase_latency/provider-evidence-registry.json",
            "sha256": SHA_F,
            "size_bytes": 1,
        },
        "authorized_hosted_credit_limit": 1_500,
        "hosted_credits_used": 1_500,
        "minimum_samples_per_case_per_system": 5,
        "plan": [item.model_dump(mode="json") for item in plan],
        "attempts": [item.model_dump(mode="json") for item in attempts],
    }
    for retained in value["attempts"]:
        registered = SOURCE_IDENTITIES[retained["case_id"]]
        retained["source"] = {
            "case_id": retained["case_id"],
            "path": registered["path"],
            "filename": registered["path"].rsplit("/", 1)[-1],
            "sha256": registered["sha256"],
            "size_bytes": registered["size_bytes"],
            "page_count": registered["page_count"],
        }
        if retained["system"] == "candidate":
            retained["environment_sha256"] = retained_environment.manifest_sha256
            retained["configuration"]["runtime_sha256"] = (
                retained_environment.manifest_sha256
            )
            retained["configuration"]["system_configuration_sha256"] = (
                configuration_identity_sha256(retained["configuration"])
            )
            manifest = retained.get("instrumentation_manifest")
            if manifest is not None:
                manifest["runtime_sha256"] = retained_environment.manifest_sha256
                manifest_payload = {
                    key: item
                    for key, item in manifest.items()
                    if key != "manifest_sha256"
                }
                manifest["manifest_sha256"] = hashlib.sha256(
                    json.dumps(
                        manifest_payload,
                        allow_nan=False,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest()
        elif retained["provider_total_latency"] is not None:
            retained["provider_total_latency"]["reviewed_sidecar"] = {
                "path": (
                    "tests/fixtures/phase_latency/provider-sidecars/"
                    f"{retained['provider_total_latency']['job_id']}.json"
                ),
                "sha256": SHA_E,
                "size_bytes": 1,
            }
    return LatencyCampaign.model_validate(value)
