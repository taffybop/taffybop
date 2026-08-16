"""Adversarial failure-boundary tests for LAT-US01 external instrumentation."""

from __future__ import annotations

import ast
import asyncio
import functools
import json
from pathlib import Path
import subprocess
import sys
import threading
import types
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_campaign import build_interleaved_plan
from tests.benchmarks.latency_contracts import (
    AttemptStatus,
    CacheStateEvidence,
    OutputIdentity,
    PrewarmEvidence,
    ProcessIdentity,
    ProcessMetric,
    ProcessRole,
    ProcessTreeSnapshot,
    StageName,
    StageStatus,
)
from tests.benchmarks.latency_instrumentation import (
    TARGET_BY_ID,
    DiagnosticInstrumentation,
    ExternalStageCollector,
    _binding_key,
    _binding_sha256,
    _parse_result_validation_target,
)
from tests.benchmarks.latency_runner import (
    ExternalCandidateJob,
    WORKER_STARTUP_PREWARM_TIMEOUT_SECONDS,
    _request_boundary_snapshots,
    _worker_request_deadline,
    _worker_startup_deadline,
    assemble_process_tree_metrics,
    run_bounded_concurrent_candidate_attempts,
)


REPOSITORY = Path(__file__).resolve().parents[2]
IDENTITY_SHA256 = "0" * 64


def _parse_result_validation_callers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    callers: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.qualnames: list[str] = []

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if self.qualnames:
                qualname = f"{self.qualnames[-1]}.<locals>.{node.name}"
            else:
                qualname = node.name
            self.qualnames.append(qualname)
            self.generic_visit(node)
            self.qualnames.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self._visit_function(node)

        def visit_AsyncFunctionDef(  # noqa: N802
            self, node: ast.AsyncFunctionDef
        ) -> None:
            self._visit_function(node)

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            function = node.func
            if (
                self.qualnames
                and isinstance(function, ast.Attribute)
                and function.attr == "model_validate"
                and isinstance(function.value, ast.Name)
                and function.value.id == "ParseResult"
            ):
                callers.add(self.qualnames[-1])
            self.generic_visit(node)

    Visitor().visit(tree)
    return callers


def _snapshot(
    observed_ns: int,
    *,
    rss_bytes: int,
    cumulative_cpu_ns: int,
    hwm_bytes: int,
) -> ProcessTreeSnapshot:
    metric = ProcessMetric(
        identity=ProcessIdentity(
            pid=4242,
            create_time_ns=1,
            role=ProcessRole.CANDIDATE_WORKER,
        ),
        rss_bytes=rss_bytes,
        user_cpu_ns=cumulative_cpu_ns,
        system_cpu_ns=0,
        thread_count=1,
        fd_count=1,
        self_hwm_bytes=hwm_bytes,
    )
    return ProcessTreeSnapshot(
        observed_monotonic_ns=observed_ns,
        members=(metric,),
        total_rss_bytes=rss_bytes,
        total_user_cpu_ns=cumulative_cpu_ns,
        total_system_cpu_ns=0,
        total_thread_count=1,
        total_fd_count=1,
    )


def test_real_parse_result_callers_are_exhaustively_routed() -> None:
    expected = {
        "app.api": {"parse_document_endpoint"},
        "app.services.pipeline": {
            "_apply_terminal_table_authority",
            "_apply_terminal_table_authority.<locals>.commit",
            "_parse_loaded_document",
        },
    }
    paths = {
        "app.api": REPOSITORY / "app" / "api.py",
        "app.services.pipeline": REPOSITORY / "app" / "services" / "pipeline.py",
    }
    for module_name, expected_callers in expected.items():
        observed_callers = _parse_result_validation_callers(paths[module_name])
        assert observed_callers == expected_callers
        for qualname in observed_callers:
            target = _parse_result_validation_target(module_name, qualname)
            assert target is not None
            assert target.target_id == (
                "api-result-validation"
                if module_name == "app.api"
                else "pipeline-result-validation"
            )

    assert _parse_result_validation_target(
        "app.services.pipeline",
        "unreviewed.<locals>.commit",
    ) is None


def test_pipeline_import_span_closes_before_target_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    ticks = iter((110, 120))

    def clock() -> int:
        value = next(ticks)
        events.append(f"clock-{value}")
        return value

    collector = ExternalStageCollector(clock=clock)
    collector.start(started_ns=100)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    module_name = "synthetic_latency_pipeline"
    module = types.ModuleType(module_name)

    def original_parse() -> str:
        return "original"

    def instrumented_parse() -> str:
        return "instrumented"

    module.parse_document = original_parse  # type: ignore[attr-defined]

    def load(requested_module: str, requested_function: str) -> Any:
        assert (requested_module, requested_function) == (
            module_name,
            "parse_document",
        )
        events.append("load")
        monkeypatch.setitem(sys.modules, module_name, module)
        return original_parse

    def install(retained_module: types.ModuleType) -> None:
        assert retained_module is module
        assert collector.invocation_count("pipeline-import-resolution") == 1
        events.append("install")
        retained_module.parse_document = instrumented_parse  # type: ignore[attr-defined]

    monkeypatch.setattr(manager, "install_module_targets", install)
    resolved = manager._resolve_and_patch_pipeline_callable(
        load,
        module_name,
        "parse_document",
    )
    assert resolved is instrumented_parse
    assert events == ["clock-110", "load", "clock-120", "install"]
    collector.finish(finished_ns=130)


def test_queue_submission_error_and_cancellation_close_once() -> None:
    class Clock:
        def __init__(self) -> None:
            self.value = 100
            self.lock = threading.Lock()

        def __call__(self) -> int:
            with self.lock:
                self.value += 10
                return self.value

    async def scenario() -> ExternalStageCollector:
        clock = Clock()
        collector = ExternalStageCollector(clock=clock)
        manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
        collector.start(started_ns=100)

        async def submission_error(_entered: Any) -> Any:
            raise RuntimeError("queue submission failed")

        with pytest.raises(RuntimeError, match="queue submission failed"):
            await manager._invoke_threadpool_with_queue_observation(
                submission_error,
                lambda: None,
                (),
                {},
            )

        async def cancelled(_entered: Any) -> Any:
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await manager._invoke_threadpool_with_queue_observation(
                cancelled,
                lambda: None,
                (),
                {},
            )
        collector.finish(finished_ns=1_000)
        return collector

    collector = asyncio.run(scenario())
    assert collector.invocation_count("api-threadpool-queue") == 2
    trace = collector.trace(
        request_started_ns=100,
        request_ended_ns=1_000,
        status=StageStatus.ERROR,
        root_failure_code="synthetic_queue_failure",
    )
    queue_spans = tuple(
        span for span in trace.spans if span.name is StageName.QUEUE_WAIT
    )
    assert tuple(span.status for span in queue_spans) == (
        StageStatus.ERROR,
        StageStatus.CANCELLED,
    )
    assert tuple(span.failure_code for span in queue_spans) == (
        "external_stage_error",
        "external_stage_cancelled",
    )


def test_queue_double_entry_is_rejected_without_duplicate_evidence() -> None:
    collector = ExternalStageCollector(clock=iter(range(110, 200, 10)).__next__)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    calls = 0
    collector.start(started_ns=100)

    async def double_entry(entered: Any) -> Any:
        entered()
        return entered()

    def operation() -> str:
        nonlocal calls
        calls += 1
        return "once"

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="entered more than once"):
            await manager._invoke_threadpool_with_queue_observation(
                double_entry,
                operation,
                (),
                {},
            )

    asyncio.run(scenario())
    collector.finish(finished_ns=1_000)
    assert calls == 1
    assert collector.invocation_count("api-threadpool-queue") == 1


def test_concurrent_queue_observers_keep_independent_ledgers() -> None:
    class Clock:
        def __init__(self) -> None:
            self.value = 100
            self.lock = threading.Lock()

        def __call__(self) -> int:
            with self.lock:
                self.value += 10
                return self.value

    clock = Clock()
    collector = ExternalStageCollector(clock=clock)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    collector.start(started_ns=100)

    async def dispatch(entered: Any) -> Any:
        await asyncio.sleep(0)
        return entered()

    async def scenario() -> tuple[str, str]:
        first, second = await asyncio.gather(
            manager._invoke_threadpool_with_queue_observation(
                dispatch, lambda: "first", (), {}
            ),
            manager._invoke_threadpool_with_queue_observation(
                dispatch, lambda: "second", (), {}
            ),
        )
        return first, second

    assert asyncio.run(scenario()) == ("first", "second")
    collector.finish(finished_ns=1_000)
    trace = collector.trace(
        request_started_ns=100,
        request_ended_ns=1_000,
        status=StageStatus.SUCCESS,
        root_failure_code=None,
    )
    queue_spans = tuple(
        span for span in trace.spans if span.name is StageName.QUEUE_WAIT
    )
    assert len(queue_spans) == 2
    assert len({span.execution_context_id for span in queue_spans}) == 2
    assert all(span.parent_span_id == "request" for span in queue_spans)


def test_response_boundary_trim_drives_request_only_rss_cpu_and_hwm() -> None:
    captured = (
        _snapshot(80, rss_bytes=900, cumulative_cpu_ns=80, hwm_bytes=900),
        _snapshot(95, rss_bytes=100, cumulative_cpu_ns=100, hwm_bytes=120),
        _snapshot(110, rss_bytes=500, cumulative_cpu_ns=140, hwm_bytes=550),
        _snapshot(130, rss_bytes=300, cumulative_cpu_ns=160, hwm_bytes=580),
        _snapshot(150, rss_bytes=200, cumulative_cpu_ns=170, hwm_bytes=600),
        _snapshot(170, rss_bytes=800, cumulative_cpu_ns=220, hwm_bytes=900),
    )
    retained = _request_boundary_snapshots(
        captured,
        request_started_monotonic_ns=100,
        request_ended_monotonic_ns=140,
        terminal_worker_hwm_bytes=650,
    )
    assert tuple(item.observed_monotonic_ns for item in retained) == (
        95,
        110,
        130,
        150,
    )
    assert retained[-1].members[0].self_hwm_bytes == 650

    metrics = assemble_process_tree_metrics(
        retained,
        request_started_monotonic_ns=100,
        request_ended_monotonic_ns=140,
        sampling_interval_target_ns=20,
        hard_maximum_gap_ns=100,
    )
    assert metrics.peak_total_rss_bytes == 500
    assert metrics.peak_worker_hwm_bytes == 650
    assert metrics.maximum_observed_process_cpu_ns == 70


def test_startup_and_request_deadlines_have_separate_injected_clock_origins() -> None:
    startup_deadline = _worker_startup_deadline(clock=lambda: 10.0)
    request_deadline = _worker_request_deadline(2.5, clock=lambda: 309.0)
    assert startup_deadline == 10.0 + WORKER_STARTUP_PREWARM_TIMEOUT_SECONDS
    assert request_deadline == 311.5
    assert request_deadline > startup_deadline

    with pytest.raises(ValueError, match="request deadline"):
        _worker_request_deadline(0.0, clock=lambda: 1.0)


@pytest.mark.parametrize(
    ("fixture_mode", "expected_status", "expected_failure_type"),
    [
        ("mock-testclient", AttemptStatus.SUCCESS, None),
        ("mock-crash", AttemptStatus.ERROR, "WorkerCrash"),
    ],
)
def test_bounded_concurrent_workers_isolate_success_and_error_evidence(
    fixture_mode: str,
    expected_status: AttemptStatus,
    expected_failure_type: str | None,
) -> None:
    plan = build_interleaved_plan(
        ("synthetic-concurrent-a", "synthetic-concurrent-b"),
        sample_count=5,
    )
    source_path = (
        REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf"
    )
    jobs = tuple(
        ExternalCandidateJob(
            slot=plan[index],
            source_path=source_path,
            attempt_id=f"synthetic-concurrent-{index + 1}-{fixture_mode}",
        )
        for index in range(2)
    )
    attempts = run_bounded_concurrent_candidate_attempts(
        jobs=jobs,
        bounded_concurrency=2,
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode=fixture_mode,
    )

    assert tuple(item.attempt_id for item in attempts) == tuple(
        job.attempt_id for job in jobs
    )
    assert all(item.status is expected_status for item in attempts)
    assert all(item.configuration.bounded_concurrency == 2 for item in attempts)
    if expected_failure_type is None:
        assert all(item.evidence_complete is True for item in attempts)
        assert all(item.failure is None for item in attempts)
        assert all(
            item.process_tree is not None and item.process_tree.worker_reaped is True
            for item in attempts
        )
    else:
        assert all(item.evidence_complete is False for item in attempts)
        assert all(item.output is None for item in attempts)
        assert all(item.failure is not None for item in attempts)
        assert {
            item.failure.exception_type.value
            for item in attempts
            if item.failure is not None
        } == {expected_failure_type}


def test_classifier_exception_closes_the_span_before_it_propagates() -> None:
    ticks = iter((110, 120))
    collector = ExternalStageCollector(clock=lambda: next(ticks))
    collector.start(started_ns=100)

    def reject(_result: object) -> tuple[StageStatus, str | None]:
        raise ValueError("classifier implementation failed")

    with pytest.raises(ValueError, match="classifier implementation failed"):
        collector.invoke(
            "classified-target",
            StageName.TABLE_AUTHORITY,
            lambda: object(),
            classifier=reject,
        )

    assert collector.invocation_count("classified-target") == 1
    failure = collector.first_failure()
    assert failure is not None
    assert failure.status is StageStatus.ERROR
    assert failure.failure_code == "classifier_external_stage_error"
    collector.finish(finished_ns=130)


def test_same_digest_distinct_wrapper_identity_is_rejected() -> None:
    collector = ExternalStageCollector(clock=lambda: 110)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    definition = TARGET_BY_ID["api-parse-dispatch"]

    def original() -> str:
        return "original"

    owner = types.SimpleNamespace(target=original)
    wrapper = collector.wrap(definition, original)
    manager._install(owner, "target", (definition,), wrapper)

    clone = types.FunctionType(
        wrapper.__code__,
        wrapper.__globals__,
        name=wrapper.__name__,
        argdefs=wrapper.__defaults__,
        closure=wrapper.__closure__,
    )
    functools.update_wrapper(clone, wrapper)
    assert _binding_sha256(clone) == _binding_sha256(wrapper)
    assert _binding_key(clone) != _binding_key(wrapper)
    owner.target = clone

    try:
        with pytest.raises(RuntimeError, match="identity|changed while installed"):
            manager.close()
    finally:
        owner.target = original


@pytest.mark.parametrize(
    ("raised", "expected_status"),
    [
        (None, StageStatus.SUCCESS),
        (RuntimeError, StageStatus.ERROR),
        (KeyboardInterrupt, StageStatus.CANCELLED),
    ],
)
def test_observer_restores_exact_binding_after_normal_error_and_baseexception(
    raised: type[BaseException] | None,
    expected_status: StageStatus,
) -> None:
    ticks = iter((110, 120))
    collector = ExternalStageCollector(clock=lambda: next(ticks))
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    definition = TARGET_BY_ID["api-parse-dispatch"]

    def original() -> str:
        if raised is not None:
            raise raised("synthetic observer boundary")
        return "ok"

    owner = types.SimpleNamespace(target=original)
    wrapper = collector.wrap(definition, original)
    manager._install(owner, "target", (definition,), wrapper)
    collector.start(started_ns=100)

    try:
        if raised is None:
            assert owner.target() == "ok"
        else:
            with pytest.raises(raised, match="synthetic observer boundary"):
                owner.target()
    finally:
        manager.close()

    assert owner.target is original
    assert _binding_key(owner.target) == _binding_key(original)
    failure = collector.first_failure()
    if expected_status is StageStatus.SUCCESS:
        assert failure is None
    else:
        assert failure is not None
        assert failure.status is expected_status
    collector.finish(finished_ns=130)


def test_cold_observer_install_does_not_eagerly_import_pipeline_or_docling() -> None:
    script = """
import json
from pathlib import Path
import sys

import app.api as api
from tests.benchmarks.latency_instrumentation import (
    DiagnosticInstrumentation,
    ExternalStageCollector,
)

def forbidden():
    return sorted(
        name for name in sys.modules
        if name == "app.services.pipeline" or name.startswith("docling")
    )

before = forbidden()
observer = DiagnosticInstrumentation(
    ExternalStageCollector(),
    workspace=Path.cwd(),
)
observer.install(api)
installed = forbidden()
observer.close()
after = forbidden()
print(json.dumps({"before": before, "installed": installed, "after": after}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads(completed.stdout)
    assert observed == {"before": [], "installed": [], "after": []}


def test_natural_docling_get_pipeline_restores_on_baseexception() -> None:
    class Converter:
        def __init__(self) -> None:
            self.initialized_pipelines: dict[str, object] = {}

        def _get_pipeline(self, key: str) -> object:
            self.initialized_pipelines[key] = object()
            raise KeyboardInterrupt("synthetic Docling cancellation")

    converter = Converter()
    original_key = _binding_key(converter._get_pipeline)
    collector = ExternalStageCollector(clock=lambda: 110)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    collector.start(started_ns=100)

    with pytest.raises(KeyboardInterrupt, match="synthetic Docling cancellation"):
        manager.invoke_with_natural_get_pipeline(
            converter,
            lambda: converter._get_pipeline("pdf"),
        )

    assert "_get_pipeline" not in vars(converter)
    assert _binding_key(converter._get_pipeline) == original_key
    failure = collector.first_failure()
    assert failure is not None
    assert failure.stage is StageName.DOCLING_PIPELINE_INITIALIZATION
    assert failure.status is StageStatus.CANCELLED
    manager.close()
    collector.finish(finished_ns=120)


@pytest.mark.parametrize(
    ("initial_cache", "expected_disposition", "profile"),
    [
        ({}, "initialized", "request_cold_after_app_startup"),
        ({"pdf": object()}, "reused", "request_prewarmed_after_app_startup"),
    ],
)
def test_docling_and_cache_lifecycle_dispositions_are_explicit(
    initial_cache: dict[str, object],
    expected_disposition: str,
    profile: str,
) -> None:
    class Converter:
        def __init__(self, retained: dict[str, object]) -> None:
            self.initialized_pipelines = dict(retained)

        def _get_pipeline(self, key: str) -> object:
            return self.initialized_pipelines.setdefault(key, object())

    converter = Converter(initial_cache)
    collector = ExternalStageCollector(clock=lambda: 110)
    manager = DiagnosticInstrumentation(collector, workspace=REPOSITORY)
    collector.start(started_ns=100)
    retained = manager.invoke_with_natural_get_pipeline(
        converter,
        lambda: converter._get_pipeline("pdf"),
    )
    assert retained is converter.initialized_pipelines["pdf"]
    assert manager._docling_dispositions == [expected_disposition]
    manager.close()
    collector.finish(finished_ns=120)

    cold = profile == "request_cold_after_app_startup"
    prewarm_evidence = (
        None
        if cold
        else PrewarmEvidence(
            policy="separate-pinned-route-equivalent-source-v1",
            source={
                "case_id": "synthetic-prewarm",
                "path": "tests/fixtures/phase_latency/synthetic-prewarm.pdf",
                "filename": "synthetic-prewarm.pdf",
                "sha256": "1" * 64,
                "size_bytes": 1,
                "page_count": 1,
            },
            output=OutputIdentity(
                sha256="2" * 64,
                semantic_sha256="2" * 64,
                size_bytes=1,
                media_type="text/markdown",
                validation="Markdown",
                semantic_exclusions=(),
            ),
            duration_ns=1,
            worker_self_cpu_ns=0,
            reaped_children_cpu_ns=0,
            worker_process_lifetime_hwm_bytes=1,
            reaped_children_process_lifetime_hwm_bytes=0,
            content_result_cache_observed=False,
        )
    )
    evidence = CacheStateEvidence(
        profile=profile,
        application_startup_completed=True,
        pipeline_loaded_at_request_start=not cold,
        converter_cache_entries_at_request_start=0 if cold else 1,
        converter_cache_entries_after_request=1,
        prewarm_request_completed=not cold,
        prewarm_evidence=prewarm_evidence,
        content_result_cache_observed=False,
        content_result_cache_proof_sha256=IDENTITY_SHA256,
        filesystem_cache_state="uncontrolled_shared_host_cache",
    )
    assert evidence.profile == profile

    invalid = evidence.model_dump(mode="json")
    invalid["prewarm_request_completed"] = cold
    with pytest.raises(ValidationError, match="request cache proof differs"):
        CacheStateEvidence.model_validate(invalid)
