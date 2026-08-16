"""Custody-preserving LAT-US01 continuation driver.

This administrative driver copies only the successful, contiguous prefix from
an immutable prior ledger into a new ledger, checkpointing every copied event
before it launches the first new worker.  It then resumes at the requested
fixed-plan order index and uses the canonical benchmark worker functions for
all new observations.  It is intentionally outside the frozen worker harness
identity: it does not execute inside a worker or alter candidate behavior.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gc
import hashlib
import os
import stat
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from tests.benchmarks import latency_profile_set as profile_set
from tests.benchmarks import latency_runner as runner
from tests.benchmarks.latency_contracts import (
    AttemptSlot,
    AttemptStatus,
    FailureRecord,
    FailureType,
    StageName,
    SystemName,
)


_MEMBER_METRIC_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _parallel_member_process_tree_snapshot(
    root_pid: int,
    *,
    observed_monotonic_ns: int | None = None,
    allow_synthetic_root_only: bool = False,
):
    """Retain one exact tree while reducing skew among independent children."""

    root = runner.psutil.Process(root_pid)
    try:
        pending = [root]
        children = []
        seen = {(int(root.pid), int(root.create_time() * 1_000_000_000))}
        while pending:
            parent = pending.pop(0)
            try:
                direct = runner._direct_child_processes(parent)
            except (
                ProcessLookupError,
                runner.psutil.NoSuchProcess,
                runner.psutil.ZombieProcess,
            ):
                if int(parent.pid) == root_pid:
                    raise
                continue
            for child in direct:
                try:
                    identity = (
                        int(child.pid),
                        int(child.create_time() * 1_000_000_000),
                    )
                except (
                    ProcessLookupError,
                    runner.psutil.NoSuchProcess,
                    runner.psutil.ZombieProcess,
                ):
                    continue
                if identity in seen:
                    continue
                seen.add(identity)
                children.append(child)
                if len(children) >= runner.MAXIMUM_PROCESSES_PER_SNAPSHOT:
                    raise RuntimeError("process-tree descendant bound exceeded")
                pending.append(child)
    except (PermissionError, runner.psutil.AccessDenied):
        if not allow_synthetic_root_only:
            raise RuntimeError("recursive descendant observation is unavailable")
        children = []

    def process_metric(item):
        process, is_root = item
        try:
            return runner._process_metric(
                process,
                role=(
                    runner.ProcessRole.CANDIDATE_WORKER
                    if is_root
                    else runner._process_role(process, root_pid=root_pid)
                ),
                worker=is_root,
            )
        except (
            runner.psutil.NoSuchProcess,
            runner.psutil.ZombieProcess,
            OSError,
        ):
            if is_root:
                raise
            return None

    requests = [(root, True), *((child, False) for child in children)]
    executor = _MEMBER_METRIC_EXECUTOR
    if executor is None:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(8, len(requests)),
            thread_name_prefix="phase-latency-tree-member",
        ) as temporary_executor:
            metrics = list(temporary_executor.map(process_metric, requests))
    else:
        metrics = list(executor.map(process_metric, requests))
    root_metric = metrics[0]
    if root_metric is None:
        raise RuntimeError("process-tree root metric disappeared")
    descendants = [item for item in metrics[1:] if item is not None]
    descendants.sort(key=lambda item: (item.identity.pid, item.identity.create_time_ns))
    members = (root_metric, *descendants)
    observed_ns = (
        time.perf_counter_ns()
        if observed_monotonic_ns is None
        else runner._strict_monotonic_ns(
            observed_monotonic_ns,
            label="observed_monotonic_ns",
        )
    )
    return runner.ProcessTreeSnapshot(
        observed_monotonic_ns=observed_ns,
        members=members,
        total_rss_bytes=sum(item.rss_bytes for item in members),
        total_user_cpu_ns=sum(item.user_cpu_ns for item in members),
        total_system_cpu_ns=sum(item.system_cpu_ns for item in members),
        total_thread_count=sum(item.thread_count for item in members),
        total_fd_count=sum(item.fd_count for item in members),
    )


class _ConcurrentRoleCheckpointBuffer:
    """Persist one role-homogeneous round only after both workers close."""

    def __init__(self, retain, *, slot_order: dict[str, int]) -> None:
        self._retain = retain
        self._slot_order = slot_order
        self._lock = threading.Lock()
        self._pending = {
            "authoritative_uninstrumented": [],
            "diagnostic_instrumented": [],
        }
        self._flushed_roles: set[str] = set()

    def __call__(self, slot: AttemptSlot, execution_id: str, run) -> None:
        role = run.role
        with self._lock:
            if role not in self._pending or role in self._flushed_roles:
                raise RuntimeError("concurrent role checkpoint lifecycle differs")
            bucket = self._pending[role]
            if any(item[0].slot_id == slot.slot_id for item in bucket):
                raise RuntimeError("concurrent role checkpoint repeated a slot")
            bucket.append((slot, execution_id, run))
            if len(bucket) > 2:
                raise RuntimeError("concurrent role checkpoint exceeded its bound")

    def flush_role(self, role: str) -> None:
        """Persist a complete round only after its observer has joined."""

        with self._lock:
            if role not in self._pending or role in self._flushed_roles:
                raise RuntimeError("concurrent role checkpoint lifecycle differs")
            bucket = self._pending[role]
            if len(bucket) != 2:
                raise RuntimeError("concurrent role checkpoint round is incomplete")
            batch = tuple(
                sorted(bucket, key=lambda item: self._slot_order[item[0].slot_id])
            )
            bucket.clear()
            self._flushed_roles.add(role)
        for retained_slot, retained_execution_id, retained_run in batch:
            self._retain(retained_slot, retained_execution_id, retained_run)

    def flush_pending(self) -> None:
        """Retain a partial terminal round after the runner has aborted it."""

        with self._lock:
            batches = []
            for role, bucket in self._pending.items():
                if not bucket:
                    continue
                batches.extend(
                    sorted(bucket, key=lambda item: self._slot_order[item[0].slot_id])
                )
                bucket.clear()
                self._flushed_roles.add(role)
        for retained_slot, retained_execution_id, retained_run in batches:
            self._retain(retained_slot, retained_execution_id, retained_run)

    def assert_complete(self) -> None:
        with self._lock:
            if self._flushed_roles != {
                "authoritative_uninstrumented",
                "diagnostic_instrumented",
            } or any(self._pending.values()):
                raise RuntimeError("concurrent role checkpoint evidence is incomplete")


def _read_source_ledger(path: Path, *, workspace: Path):
    resolved = path.resolve()
    resolved.relative_to(workspace)
    source_stat = resolved.lstat()
    if (
        resolved.is_symlink()
        or not stat.S_ISREG(source_stat.st_mode)
        or stat.S_IMODE(source_stat.st_mode) != 0o600
        or source_stat.st_uid != os.getuid()
        or source_stat.st_nlink != 1
    ):
        raise ValueError("source continuation ledger custody differs")
    payload = runner.bounded_read_bytes(
        resolved,
        maximum_bytes=runner.MAXIMUM_PROFILE_SET_BYTES,
    )
    ledger = profile_set.CandidateProfileAttemptLedger.model_validate_json(payload)
    if runner.canonical_model_bytes(ledger) != payload:
        raise ValueError("source continuation ledger is not canonical")
    if ledger.execution_identity != runner.derive_candidate_profile_execution_identity(
        workspace
    ):
        raise ValueError("source continuation identity differs from current bytes")
    return ledger


def _attempt_passes_resource_continuation_gate(attempt, *, identity) -> bool:
    """Reject a successful-looking prefix that already violates RSS/CPU gates."""

    authoritative = attempt.process_tree
    diagnostic = attempt.diagnostic_process_tree
    if authoritative is None or diagnostic is None:
        return False
    logical_cpu_count = identity.environment_manifest.logical_cpu_count
    if not profile_set._tree_is_complete_and_sane(
        authoritative,
        logical_cpu_count=logical_cpu_count,
    ) or not profile_set._tree_is_complete_and_sane(
        diagnostic,
        logical_cpu_count=logical_cpu_count,
    ):
        return False
    per_worker_cap = (
        profile_set.M0_CASE_HWM_BYTES[attempt.case_id]
        + profile_set.PER_WORKER_DELTA_BYTES
    )
    authoritative_hwm = authoritative.peak_worker_hwm_bytes
    diagnostic_hwm = diagnostic.peak_worker_hwm_bytes
    return (
        authoritative_hwm <= per_worker_cap
        and diagnostic_hwm <= per_worker_cap
        and diagnostic_hwm - authoritative_hwm
        <= profile_set.PER_WORKER_DELTA_BYTES
    )


def _run(
    *,
    source_ledger_path: Path,
    resume_order_index: int,
    ledger_output: Path,
    profile_output: Path,
    evaluation_output: Path,
    timeout_seconds: float,
    isolated_sample_interval_ns: int,
    parallel_member_metrics: bool,
    workspace: Path,
) -> int:
    global _MEMBER_METRIC_EXECUTOR

    if not 2 <= resume_order_index <= 46:
        raise ValueError("resume order index must be from 2 to 46")
    if not 0 < timeout_seconds <= 300.0:
        raise ValueError("profile timeout must be in (0, 300] seconds")
    if isolated_sample_interval_ns not in (40_000_000, 50_000_000):
        raise ValueError("isolated sample interval must be 40ms or 50ms")
    root = workspace.resolve()
    source_ledger = _read_source_ledger(source_ledger_path, workspace=root)
    identity = runner.derive_candidate_profile_execution_identity(root)
    plan = profile_set.CANDIDATE_PROFILE_SLOT_PLAN
    prefix = plan[: resume_order_index - 1]
    source_selections = {item.slot_id: item for item in source_ledger.selections}
    source_attempts = {
        item.observation_id: item for item in source_ledger.attempt_observations
    }
    source_roles = {
        item.observation_id: item for item in source_ledger.role_observations
    }
    for slot in prefix:
        selection = source_selections.get(slot.slot_id)
        if selection is None:
            raise ValueError("source ledger lacks the complete successful prefix")
        observation = source_attempts.get(selection.selected_observation_id)
        if (
            observation is None
            or observation.attempt.attempt_id != selection.selected_attempt_id
            or observation.attempt.status is not AttemptStatus.SUCCESS
            or observation.attempt.evidence_complete is not True
            or not profile_set.attempt_output_matches_current_runtime(
                observation.attempt, slot
            )
            or len(observation.role_observation_ids) != 2
            or not _attempt_passes_resource_continuation_gate(
                observation.attempt,
                identity=identity,
            )
        ):
            raise ValueError("source prefix attempt is not independently reusable")
        roles = tuple(source_roles[item] for item in observation.role_observation_ids)
        if (
            {item.role for item in roles}
            != {"authoritative_uninstrumented", "diagnostic_instrumented"}
            or any(item.status is not AttemptStatus.SUCCESS for item in roles)
        ):
            raise ValueError("source prefix twin-role evidence is incomplete")

    ledger_path = runner._new_workspace_output_path(
        str(ledger_output), workspace=root
    )
    output_path = runner._new_workspace_output_path(
        str(profile_output), workspace=root
    )
    evaluation_path = runner._new_workspace_output_path(
        str(evaluation_output), workspace=root
    )
    if len({ledger_path, output_path, evaluation_path}) != 3:
        raise ValueError("ledger, profile, and evaluation outputs must be distinct")
    store = runner._CandidateProfileLedgerStore(
        path=ledger_path,
        initial_ledger=profile_set.initial_candidate_profile_attempt_ledger(identity),
        workspace=root,
    )
    checkpoint_lock = threading.Lock()

    def checkpoint(transform):
        with checkpoint_lock:
            return store.checkpoint(transform(store.ledger))

    def retain_role(slot: AttemptSlot, execution_id: str, run) -> None:
        evidence = run.evidence
        status = evidence.status if evidence is not None else run.status
        failure = (
            evidence.failure
            if evidence is not None
            else FailureRecord(
                code=run.failure_code,
                stage=StageName.REQUEST_TOTAL,
                exception_type=run.failure_type,
            )
        )
        checkpoint(
            lambda ledger: profile_set.append_role_observation(
                ledger,
                execution_id=execution_id,
                slot_id=slot.slot_id,
                role=run.role,
                status=status,
                failure=failure,
                started_at_utc=(
                    evidence.started_at_utc if evidence is not None else run.started_at
                ),
                completed_at_utc=(
                    evidence.completed_at_utc
                    if evidence is not None
                    else run.completed_at
                ),
                started_monotonic_ns=(
                    evidence.request_started_monotonic_ns
                    if evidence is not None
                    else run.started_ns
                ),
                ended_monotonic_ns=(
                    evidence.request_ended_monotonic_ns
                    if evidence is not None
                    else run.ended_ns
                ),
                worker_evidence=evidence,
                snapshots=run.snapshots,
                watchdog=run.watchdog_evidence,
                worker_fatal_envelope=run.worker_fatal_envelope,
            )
        )

    def retain_attempt(attempt) -> None:
        checkpoint(
            lambda ledger: profile_set.append_attempt_observation(ledger, attempt)
        )

    isolated_attempts = {}
    for slot in prefix:
        selection = source_selections[slot.slot_id]
        observation = source_attempts[selection.selected_observation_id]
        for role_id in observation.role_observation_ids:
            role = source_roles[role_id]
            checkpoint(
                lambda ledger, item=role: profile_set.append_role_observation(
                    ledger,
                    execution_id=item.execution_id,
                    slot_id=item.slot_id,
                    role=item.role,
                    status=item.status,
                    failure=item.failure,
                    started_at_utc=item.started_at_utc,
                    completed_at_utc=item.completed_at_utc,
                    started_monotonic_ns=item.started_monotonic_ns,
                    ended_monotonic_ns=item.ended_monotonic_ns,
                    worker_evidence=item.worker_evidence,
                    snapshots=item.snapshots,
                    watchdog=item.watchdog,
                    worker_fatal_envelope=item.worker_fatal_envelope,
                )
            )
        retain_attempt(observation.attempt)
        isolated_attempts[slot.slot_id] = observation.attempt

    def close_ledger():
        return checkpoint(
            lambda ledger: profile_set.finalize_ledger(
                ledger,
                finalized_at_utc=datetime.now(UTC),
                finalized_monotonic_ns=time.perf_counter_ns(),
            )
        )

    current_slot = None
    current_execution_id = None
    canonical_sampler = runner.ExternalProcessTreeSampler
    canonical_sample_interval_ns = runner.DEFAULT_SAMPLE_INTERVAL_NS
    canonical_snapshot_reader = runner.read_process_tree_snapshot
    canonical_observer_finish = runner._ConcurrentRoundObserver.finish
    member_metric_executor = None
    concurrent_role_buffer = None
    garbage_collection_was_enabled = gc.isenabled()

    def restore_concurrent_controller_state() -> None:
        nonlocal member_metric_executor
        global _MEMBER_METRIC_EXECUTOR

        runner.read_process_tree_snapshot = canonical_snapshot_reader
        runner._ConcurrentRoundObserver.finish = canonical_observer_finish
        _MEMBER_METRIC_EXECUTOR = None
        if member_metric_executor is not None:
            member_metric_executor.shutdown(wait=True, cancel_futures=True)
            member_metric_executor = None
        if garbage_collection_was_enabled and not gc.isenabled():
            gc.enable()

    def configured_isolated_sampler(root_pid, **kwargs):
        if "target_interval_ns" in kwargs:
            raise ValueError("isolated sampler interval was supplied twice")
        return canonical_sampler(
            root_pid,
            target_interval_ns=isolated_sample_interval_ns,
            **kwargs,
        )

    def configured_concurrent_observer_finish(observer) -> None:
        errors = []
        try:
            canonical_observer_finish(observer)
        except BaseException as error:  # noqa: BLE001 - retain both failures
            errors.append(error)
        try:
            if concurrent_role_buffer is None:
                raise RuntimeError("concurrent role checkpoint buffer is unavailable")
            concurrent_role_buffer.flush_role(observer.role)
        except BaseException as checkpoint_error:  # noqa: BLE001
            errors.append(checkpoint_error)
        if observer.role == "diagnostic_instrumented":
            try:
                restore_concurrent_controller_state()
            except BaseException as lifecycle_error:  # noqa: BLE001
                errors.append(lifecycle_error)
        if len(errors) > 1:
            raise BaseExceptionGroup(
                "concurrent observer, custody, or controller closure failed",
                tuple(errors),
            )
        if errors:
            raise errors[0]

    if isolated_sample_interval_ns != runner.DEFAULT_SAMPLE_INTERVAL_NS:
        runner.ExternalProcessTreeSampler = configured_isolated_sampler
        runner.DEFAULT_SAMPLE_INTERVAL_NS = isolated_sample_interval_ns
    try:
        for slot_spec in plan[resume_order_index - 1 : 45]:
            current_slot = AttemptSlot(
                slot_id=slot_spec.slot_id,
                order_index=slot_spec.order_index,
                case_id=slot_spec.case_id,
                pair_index=1,
                system=SystemName.CANDIDATE,
            )
            current_execution_id = profile_set.next_candidate_profile_execution_id(
                store.ledger, current_slot.slot_id
            )
            request_profile = (
                "request_prewarmed_after_app_startup"
                if slot_spec.profile == "prewarmed-json"
                else "request_cold_after_app_startup"
            )
            attempt = runner.run_external_candidate_attempt(
                slot=current_slot,
                source_path=(
                    root
                    / "benchmark-expertmodeldata"
                    / f"{current_slot.case_id}.pdf"
                ),
                attempt_id=current_execution_id,
                output_format=slot_spec.output_format.value,
                timeout_seconds=timeout_seconds,
                workspace=root,
                request_profile=request_profile,
                _role_observer=retain_role,
            )
            retain_attempt(attempt)
            isolated_attempts[slot_spec.slot_id] = attempt
            if (
                attempt.status is not AttemptStatus.SUCCESS
                or attempt.evidence_complete is not True
                or not profile_set.attempt_output_matches_current_runtime(
                    attempt, slot_spec
                )
            ):
                runner.ExternalProcessTreeSampler = canonical_sampler
                runner.DEFAULT_SAMPLE_INTERVAL_NS = canonical_sample_interval_ns
                close_ledger()
                return 2

        runner.ExternalProcessTreeSampler = canonical_sampler
        runner.DEFAULT_SAMPLE_INTERVAL_NS = canonical_sample_interval_ns
        isolated_attempts.clear()
        del source_ledger
        del source_selections
        del source_attempts
        del source_roles
        del prefix
        gc.collect()
        if garbage_collection_was_enabled:
            gc.disable()
        if parallel_member_metrics:
            member_metric_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=16,
                thread_name_prefix="phase-latency-tree-member",
            )
            _MEMBER_METRIC_EXECUTOR = member_metric_executor
            runner.read_process_tree_snapshot = (
                _parallel_member_process_tree_snapshot
            )
        concurrent_jobs = []
        for slot_spec in plan[45:]:
            slot = AttemptSlot(
                slot_id=slot_spec.slot_id,
                order_index=slot_spec.order_index,
                case_id=slot_spec.case_id,
                pair_index=1,
                system=SystemName.CANDIDATE,
            )
            execution_id = profile_set.next_candidate_profile_execution_id(
                store.ledger, slot.slot_id
            )
            concurrent_jobs.append(
                runner.ExternalCandidateJob(
                    slot=slot,
                    source_path=(
                        root / "benchmark-expertmodeldata" / f"{slot.case_id}.pdf"
                    ),
                    attempt_id=execution_id,
                )
            )
        current_slot = None
        current_execution_id = None
        concurrent_role_buffer = _ConcurrentRoleCheckpointBuffer(
            retain_role,
            slot_order={item.slot_id: item.order_index for item in plan[45:]},
        )
        runner._ConcurrentRoundObserver.finish = (
            configured_concurrent_observer_finish
        )
        concurrent_batch = runner.run_synchronized_concurrent_candidate_profile(
            jobs=tuple(concurrent_jobs),
            timeout_seconds=timeout_seconds,
            workspace=root,
            _role_observer=concurrent_role_buffer,
            _attempt_observer=retain_attempt,
        )
        concurrent_role_buffer.assert_complete()
        restore_concurrent_controller_state()
        if any(
            attempt.status is not AttemptStatus.SUCCESS
            or attempt.evidence_complete is not True
            for attempt in concurrent_batch.ordered_attempts
        ):
            close_ledger()
            return 2
    except BaseException as error:
        runner.ExternalProcessTreeSampler = canonical_sampler
        runner.DEFAULT_SAMPLE_INTERVAL_NS = canonical_sample_interval_ns
        restore_concurrent_controller_state()
        if concurrent_role_buffer is not None:
            concurrent_role_buffer.flush_pending()
        keyboard_interrupt = isinstance(error, KeyboardInterrupt)
        status = (
            AttemptStatus.CANCELLED
            if keyboard_interrupt
            else AttemptStatus.TIMEOUT
            if isinstance(error, TimeoutError)
            else AttemptStatus.ERROR
        )
        failure_code = (
            "worker_cancelled"
            if keyboard_interrupt
            else "worker_hard_timeout"
            if isinstance(error, TimeoutError)
            else "worker_evidence_error"
        )
        failure_type = (
            FailureType.WORKER_CANCELLED
            if keyboard_interrupt
            else FailureType.WORKER_TIMEOUT
            if isinstance(error, TimeoutError)
            else FailureType.EVIDENCE_ERROR
        )
        retained = store.ledger
        closed_ids = {
            item.execution_id for item in retained.attempt_observations
        } | {
            item.execution_id
            for item in retained.controller_failures
            if item.execution_id is not None
        }
        open_rows = []
        for item in retained.role_observations:
            key = (item.slot_id, item.execution_id)
            if item.execution_id not in closed_ids and key not in open_rows:
                open_rows.append(key)
        active = (
            (current_slot.slot_id, current_execution_id)
            if current_slot is not None
            and current_execution_id is not None
            and current_execution_id not in closed_ids
            else None
        )
        targets = tuple(open_rows) or (
            (active,) if active is not None else ((None, None),)
        )
        for failed_slot_id, failed_execution_id in targets:
            checkpoint(
                lambda ledger,
                slot_id=failed_slot_id,
                execution_id=failed_execution_id: (
                    profile_set.append_controller_failure(
                        ledger,
                        event_kind=(
                            "controller_keyboard_interrupt"
                            if keyboard_interrupt
                            else "controller_exception"
                        ),
                        slot_id=slot_id,
                        execution_id=execution_id,
                        status=status,
                        failure_code=failure_code,
                        failure_type=failure_type,
                        observed_at_utc=datetime.now(UTC),
                        observed_monotonic_ns=time.perf_counter_ns(),
                    )
                )
            )
        close_ledger()
        raise

    final_ledger = close_ledger()
    if final_ledger.disposition != "complete" or final_ledger.missing_slot_ids:
        return 2

    selected_observations = {
        item.observation_id: item for item in final_ledger.attempt_observations
    }
    isolated_attempts = {
        selection.slot_id: selected_observations[
            selection.selected_observation_id
        ].attempt
        for selection in final_ledger.selections
        if selection.slot_id not in {
            "ny-timetable-bound2-cold-json",
            "uber-earnings-bound2-cold-json",
        }
    }
    retained_cases = []
    for case_id in profile_set.CASE_ORDER:
        labels = ("cold-json", "prewarmed-json", "cold-markdown")
        cold_json, prewarmed_json, cold_markdown = tuple(
            isolated_attempts[f"{case_id}-{label}"] for label in labels
        )
        json_sha256, markdown_sha256, markdown_size = (
            profile_set.P00_OUTPUT_IDENTITIES[case_id]
        )
        current_json_sha256, current_markdown_sha256, current_markdown_size = (
            profile_set.CURRENT_RUNTIME_OUTPUT_IDENTITIES[case_id]
        )
        retained_cases.append(
            profile_set.CandidateProfileCase(
                case_id=case_id,
                source=cold_json.source,
                source_custody="public-redistributable",
                m0_case_hwm_bytes=profile_set.M0_CASE_HWM_BYTES[case_id],
                p00_semantic_json_sha256=json_sha256,
                p00_markdown_sha256=markdown_sha256,
                p00_markdown_size_bytes=markdown_size,
                current_runtime_semantic_json_sha256=current_json_sha256,
                current_runtime_markdown_sha256=current_markdown_sha256,
                current_runtime_markdown_size_bytes=current_markdown_size,
                cold_json=cold_json,
                prewarmed_json=prewarmed_json,
                cold_markdown=cold_markdown,
            )
        )
    selected_attempts = tuple(
        attempt
        for case in retained_cases
        for attempt in (case.cold_json, case.prewarmed_json, case.cold_markdown)
    ) + concurrent_batch.ordered_attempts
    slot_by_id = {item.slot_id: item for item in plan}
    zero_drift = not final_ledger.has_blocking_observation and all(
        profile_set.attempt_output_matches_current_runtime(
            attempt, slot_by_id[attempt.slot_id]
        )
        for attempt in selected_attempts
    )
    retained_profile = profile_set.CandidateProfileSet(
        schema_id="phase-latency-candidate-profile-set-v1",
        schema_version="1.0",
        profile_set_id="lat-us01-all-15-profile-v1",
        identity=identity,
        attempt_ledger=final_ledger,
        quality=profile_set.P00QualityEvidence(
            case_count=15,
            page_count=30,
            reviewed_claim_count=210,
            literal_eligible_count=109,
            semantic_eligible_count=162,
            excluded_unsupported_count=48,
            control_count=25,
            dimension_count=12,
            quality_signature_sha256=(
                "a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed"
            ),
            stable_output_signature_sha256=(
                "a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0"
            ),
            current_runtime_stable_output_signature_sha256=(
                "d10fb6107c9a0b97788ec23d2519a31b53dc3c23df5b06a1566b9e96a072e71e"
            ),
            baseline_policy="p00-historical-plus-reviewed-current-runtime-exact-v1",
            zero_unexplained_drift=zero_drift,
        ),
        cases=tuple(retained_cases),
        concurrent_batch=concurrent_batch,
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
    runner.verify_candidate_profile_set_custody(
        retained_profile, workspace=root, ledger_path=ledger_path
    )
    profile_bytes = runner.canonical_model_bytes(retained_profile)
    runner._emit_json(
        profile_bytes,
        str(output_path),
        maximum_bytes=runner.MAXIMUM_PROFILE_SET_BYTES,
        workspace=root,
    )
    retained_profile_bytes = runner.bounded_read_bytes(
        output_path, maximum_bytes=runner.MAXIMUM_PROFILE_SET_BYTES
    )
    if hashlib.sha256(retained_profile_bytes).digest() != hashlib.sha256(
        profile_bytes
    ).digest():
        raise RuntimeError("retained candidate profile hash differs")
    evaluation = profile_set.evaluate_candidate_profile_set(retained_profile)
    evaluation_bytes = runner.canonical_model_bytes(evaluation)
    runner._emit_json(
        evaluation_bytes,
        str(evaluation_path),
        maximum_bytes=runner.MAXIMUM_PROFILE_EVALUATION_BYTES,
        workspace=root,
    )
    retained_evaluation = profile_set.CandidateProfileEvaluation.model_validate_json(
        runner.bounded_read_bytes(
            evaluation_path, maximum_bytes=runner.MAXIMUM_PROFILE_EVALUATION_BYTES
        )
    )
    if retained_evaluation != evaluation or not retained_evaluation.passed:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ledger", required=True)
    parser.add_argument("--resume-order-index", type=int, required=True)
    parser.add_argument("--ledger-output", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--evaluation-output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--isolated-sample-interval-ns",
        type=int,
        choices=(40_000_000, 50_000_000),
        default=50_000_000,
    )
    parser.add_argument("--parallel-member-metrics", action="store_true")
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    return _run(
        source_ledger_path=Path(args.source_ledger),
        resume_order_index=args.resume_order_index,
        ledger_output=Path(args.ledger_output),
        profile_output=Path(args.output),
        evaluation_output=Path(args.evaluation_output),
        timeout_seconds=args.timeout_seconds,
        isolated_sample_interval_ns=args.isolated_sample_interval_ns,
        parallel_member_metrics=args.parallel_member_metrics,
        workspace=workspace,
    )


if __name__ == "__main__":
    raise SystemExit(main())
