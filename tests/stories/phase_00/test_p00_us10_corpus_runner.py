"""P00-US10 immutable corpus runner and semantic-report acceptance tests.

The tests use the real frozen benchmark context and a synthetic successful run
record.  They never invoke the heavyweight production parser.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from tests.benchmarks import corpus_runner
from tests.benchmarks.corpus_runner import (
    CLAIM_DIMENSION,
    DIMENSION_ORDER,
    LEGACY_M0_COMPARISON_SHA256,
    LEGACY_M0_METADATA_SHA256,
    REFERENCE_OUTPUT_IDENTITIES,
    REQUIRED_ENGINE_NAMES,
    RUNNER_VERSION,
    ArtifactEvidence,
    BenchmarkContext,
    CaseExecution,
    CaseOutputEvidence,
    CaseRecordEvidence,
    CaseStatus,
    ClaimTreatment,
    CorpusRunRecord,
    ErrorRecord,
    MetricDimension,
    OutputComparison,
    build_semantic_report,
    canonical_model_bytes,
    canonical_payload_bytes,
    capture_corpus,
    load_benchmark_context,
    load_case_execution,
    load_corpus_run,
    normalize_case_selection,
    read_legacy_m0_run,
    semantic_report_markdown,
    sha256_bytes,
)
from tests.benchmarks.corpus_registry import (
    EXPECTED_CASE_IDS,
    RegistryCase,
    sha256_file,
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS_REGISTRY_FILE_SHA256 = (
    "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb"
)
CONTROL_REGISTRY_FILE_SHA256 = (
    "a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5"
)
SHA_A = "a" * 64
EVIDENCE_ROOT = "tracker/phase-00-baseline/evidence"


@pytest.fixture(scope="module")
def benchmark_context() -> BenchmarkContext:
    """Run the complete, read-only P00-US10 preflight once for this module."""

    return load_benchmark_context(WORKSPACE)


def _source_triplet(case: RegistryCase) -> tuple[ArtifactEvidence, ...]:
    return tuple(
        ArtifactEvidence(
            role=artifact.role.value,
            path=artifact.path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
        for artifact in case.artifacts
    )


def _stable_output(case: RegistryCase, run_dir: str) -> CaseOutputEvidence:
    semantic_sha, markdown_sha = REFERENCE_OUTPUT_IDENTITIES[case.case_id]
    raw_path = f"{run_dir}/{case.case_id}/our-output.json"
    markdown_path = f"{run_dir}/{case.case_id}/our-output.md"
    return CaseOutputEvidence(
        raw_json=ArtifactEvidence(
            role="raw_json",
            path=raw_path,
            sha256=sha256_bytes(f"raw:{case.case_id}".encode()),
            size_bytes=100 + case.page_count,
        ),
        semantic_json=ArtifactEvidence(
            role="semantic_json",
            path=raw_path,
            sha256=semantic_sha,
            size_bytes=90 + case.page_count,
            derivation="canonical JSON excluding /processing/duration_ms",
        ),
        markdown=ArtifactEvidence(
            role="markdown",
            path=markdown_path,
            sha256=markdown_sha,
            size_bytes=50 + case.page_count,
        ),
        expected_page_count=case.page_count,
        observed_page_count=case.page_count,
        successful_page_count=case.page_count,
    )


def _successful_case(
    context: BenchmarkContext,
    case: RegistryCase,
    *,
    run_id: str,
    run_dir: str,
    order: int,
) -> CaseExecution:
    output = _stable_output(case, run_dir)
    semantic_sha, markdown_sha = REFERENCE_OUTPUT_IDENTITIES[case.case_id]
    return CaseExecution(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        case_id=case.case_id,
        order=order,
        status=CaseStatus.SUCCESS,
        registered_page_count=case.page_count,
        source_triplet=_source_triplet(case),
        started_at_utc="2026-07-29T00:00:00+00:00",
        completed_at_utc="2026-07-29T00:00:01+00:00",
        command=("synthetic-worker", case.case_id),
        worker_exit_code=0,
        parse_latency_ms=float(order),
        case_latency_ms=float(order + 1),
        cpu_ms=float(order) / 2,
        peak_rss_bytes=100_000_000 + order,
        settings_sha256=context.settings_sha256,
        environment_sha256=context.environment_sha256,
        output=output,
        reference_comparison=OutputComparison(
            case_id=case.case_id,
            current_semantic_json_sha256=semantic_sha,
            reference_semantic_json_sha256=semantic_sha,
            semantic_json_stable=True,
            current_markdown_sha256=markdown_sha,
            reference_markdown_sha256=markdown_sha,
            markdown_stable=True,
        ),
    )


def _successful_run(
    context: BenchmarkContext,
    *,
    run_id: str = "p00-us10-synthetic",
    case_ids: tuple[str, ...] = EXPECTED_CASE_IDS,
) -> CorpusRunRecord:
    run_dir = f"{EVIDENCE_ROOT}/{run_id}"
    selected = normalize_case_selection(context.corpus_registry, case_ids)
    selected_set = set(selected)
    cases = tuple(
        _successful_case(
            context,
            case,
            run_id=run_id,
            run_dir=run_dir,
            order=order,
        )
        for order, case in enumerate(
            (
                case
                for case in context.corpus_registry.cases
                if case.case_id in selected_set
            ),
            start=1,
        )
    )
    expected_pages = sum(case.registered_page_count for case in cases)
    record_evidence = tuple(
        CaseRecordEvidence(
            case_id=case.case_id,
            worker_record=ArtifactEvidence(
                role="worker_case_record",
                path=f"{run_dir}/{case.case_id}/case-record.json",
                sha256=sha256_bytes(f"worker:{case.case_id}".encode()),
                size_bytes=100,
            ),
            coordinator_record=ArtifactEvidence(
                role="coordinator_case_record",
                path=(
                    f"{run_dir}/{case.case_id}/"
                    "coordinator-case-record.json"
                ),
                sha256=sha256_bytes(f"coordinator:{case.case_id}".encode()),
                size_bytes=100,
            ),
        )
        for case in cases
    )
    return CorpusRunRecord(
        schema_version="1.0",
        record_kind="p00-us10-corpus-run",
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        run_dir=run_dir,
        status="success",
        started_at_utc="2026-07-29T00:00:00+00:00",
        completed_at_utc="2026-07-29T00:01:00+00:00",
        command=("synthetic-capture", *selected),
        cwd=".",
        settings=context.settings,
        settings_sha256=context.settings_sha256,
        execution_policy=corpus_runner.FIXED_EXECUTION_POLICY,
        environment=context.environment,
        environment_sha256=context.environment_sha256,
        frozen_inputs=context.frozen_inputs,
        selected_case_ids=selected,
        requested_case_count=len(cases),
        attempted_case_count=len(cases),
        success_count=len(cases),
        partial_count=0,
        error_count=0,
        timeout_count=0,
        skipped_count=0,
        expected_page_count=expected_pages,
        successful_page_count=expected_pages,
        cases=cases,
        case_record_evidence=record_evidence,
    )


def _error(code: str) -> ErrorRecord:
    return ErrorRecord(
        code=code,
        stage="test",
        exception_type="SyntheticFailure",
        message="synthetic failure",
        remediation="retain the failed evidence and use a new run ID",
        traceback="SyntheticFailure: synthetic failure",
    )


def test_real_preflight_loads_every_frozen_input_and_required_identity(
    benchmark_context: BenchmarkContext,
) -> None:
    context = benchmark_context

    assert context.workspace_root == WORKSPACE
    assert context.corpus_registry.case_count == 15
    assert context.corpus_registry.page_count == 30
    assert context.corpus_registry.artifact_count == 45
    assert tuple(case.case_id for case in context.corpus_registry.cases) == (
        EXPECTED_CASE_IDS
    )
    assert sum(batch.claim_count for batch in context.review_batches) == 210
    assert context.control_registry.gap_owner_count == 25
    assert context.control_registry.role_assignment_count == 100
    assert context.control_registry.case_gap_row_count == 109

    assert (
        context.frozen_inputs.corpus_registry.file_sha256
        == CORPUS_REGISTRY_FILE_SHA256
    )
    assert (
        context.frozen_inputs.control_registry.file_sha256
        == CONTROL_REGISTRY_FILE_SHA256
    )
    assert len(context.frozen_inputs.review_batches) == 3
    assert tuple(engine.name for engine in context.environment.engines) == (
        REQUIRED_ENGINE_NAMES
    )
    assert context.environment_sha256 == sha256_bytes(
        canonical_model_bytes(context.environment)
    )
    assert context.settings_sha256 == sha256_bytes(
        canonical_payload_bytes(context.settings)
    )


def test_selection_defaults_to_all_and_rejects_ambiguous_requests(
    benchmark_context: BenchmarkContext,
) -> None:
    registry = benchmark_context.corpus_registry

    assert normalize_case_selection(registry, None) == EXPECTED_CASE_IDS
    assert normalize_case_selection(
        registry,
        ("uber-earnings", "catastrophe-recap"),
    ) == ("catastrophe-recap", "uber-earnings")

    with pytest.raises(ValueError, match="must not be empty"):
        normalize_case_selection(registry, ())
    with pytest.raises(ValueError, match="contains duplicates"):
        normalize_case_selection(
            registry,
            ("catastrophe-recap", "catastrophe-recap"),
        )
    with pytest.raises(ValueError, match="unknown corpus cases: missing-case"):
        normalize_case_selection(registry, ("missing-case",))


def test_legacy_m0_reader_is_read_only_and_preserves_15_case_contract() -> None:
    metadata = (
        WORKSPACE
        / corpus_runner.LEGACY_M0_RUN_ROOT
        / "run-metadata.json"
    )
    comparison = (
        WORKSPACE
        / corpus_runner.LEGACY_M0_RUN_ROOT
        / "comparison-summary.json"
    )
    before = (
        (metadata.stat().st_mtime_ns, metadata.read_bytes()),
        (comparison.stat().st_mtime_ns, comparison.read_bytes()),
    )

    legacy = read_legacy_m0_run(WORKSPACE)

    assert legacy.case_ids == EXPECTED_CASE_IDS
    assert legacy.case_count == 15
    assert legacy.page_count == 30
    assert legacy.status == "success"
    assert legacy.metadata_sha256 == LEGACY_M0_METADATA_SHA256
    assert legacy.comparison_sha256 == LEGACY_M0_COMPARISON_SHA256
    assert len(legacy.performance_environment_fingerprint) == 64
    assert before == (
        (metadata.stat().st_mtime_ns, metadata.read_bytes()),
        (comparison.stat().st_mtime_ns, comparison.read_bytes()),
    )


def test_reference_output_hashes_verify_and_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus_runner._verify_reference_outputs(WORKSPACE)

    _, markdown_sha = REFERENCE_OUTPUT_IDENTITIES["catastrophe-recap"]
    monkeypatch.setitem(
        REFERENCE_OUTPUT_IDENTITIES,
        "catastrophe-recap",
        ("0" * 64, markdown_sha),
    )
    with pytest.raises(
        ValueError,
        match="legacy reference output identity changed for catastrophe-recap",
    ):
        corpus_runner._verify_reference_outputs(WORKSPACE)


def test_semantic_report_aggregates_all_masks_and_12_dimensions_without_scoring(
    benchmark_context: BenchmarkContext,
    tmp_path: Path,
) -> None:
    isolated_context = replace(
        benchmark_context,
        workspace_root=tmp_path.resolve(),
    )
    run = _successful_run(isolated_context)
    record_path = tmp_path / run.run_dir / "run-record.json"
    corpus_runner._write_json_exclusive(
        record_path,
        run.model_dump(mode="json"),
    )

    report = build_semantic_report(
        run,
        run_record_path=record_path,
        context=isolated_context,
    )
    rebuilt = build_semantic_report(
        run,
        run_record_path=record_path,
        context=isolated_context,
    )

    assert report.case_count == 15
    assert report.page_count == 30
    assert report.reviewed_claim_count == 210
    assert report.literal_eligible_count == 109
    assert report.semantic_eligible_count == 162
    assert report.excluded_unsupported_count == 48
    assert report.scored_claim_count == 0
    assert report.diagnostic_only_count == 162
    assert Counter(claim.treatment for claim in report.claim_ledger) == {
        ClaimTreatment.DIAGNOSTIC_ONLY: 162,
        ClaimTreatment.EXCLUDED_UNSUPPORTED: 48,
    }
    assert tuple(item.dimension for item in report.dimensions) == DIMENSION_ORDER
    assert {
        claim.claim_id
        for claim in report.claim_ledger
    } == {
        claim_id
        for dimension in report.dimensions
        for claim_id in dimension.claim_ids
    }
    assert all(
        claim.dimension is CLAIM_DIMENSION[claim.claim_type]
        for claim in report.claim_ledger
    )

    by_dimension = {item.dimension: item for item in report.dimensions}
    assert len(by_dimension[MetricDimension.HALLUCINATION].cross_cutting_claim_ids) == (
        48
    )
    assert len(
        by_dimension[MetricDimension.HALLUCINATION].safety_control_assignment_ids
    ) == 25
    assert len(by_dimension[MetricDimension.JSON].output_comparisons) == 15
    assert len(by_dimension[MetricDimension.MARKDOWN].output_comparisons) == 15
    assert report.all_outputs_stable is True
    assert report.cost.hosted_requests == 0
    assert report.cost.billed_usd == 0.0
    assert canonical_model_bytes(report) == canonical_model_bytes(rebuilt)
    markdown = semantic_report_markdown(report)
    assert "No single aggregate quality score is produced." in markdown
    assert all(
        f"| {dimension.value} |" in markdown for dimension in DIMENSION_ORDER
    )


def test_exclusive_writers_never_overwrite_existing_artifacts(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / "evidence" / "record.json"
    text_path = tmp_path / "evidence" / "record.md"

    corpus_runner._write_json_exclusive(json_path, {"z": 2, "a": 1})
    corpus_runner._write_text_exclusive(text_path, "immutable\n")

    assert json.loads(json_path.read_text(encoding="utf-8")) == {"a": 1, "z": 2}
    assert json_path.read_text(encoding="utf-8").endswith("\n")
    assert text_path.read_text(encoding="utf-8") == "immutable\n"
    with pytest.raises(FileExistsError):
        corpus_runner._write_json_exclusive(json_path, {"replacement": True})
    with pytest.raises(FileExistsError):
        corpus_runner._write_text_exclusive(text_path, "replacement\n")
    assert json.loads(json_path.read_text(encoding="utf-8")) == {"a": 1, "z": 2}
    assert text_path.read_text(encoding="utf-8") == "immutable\n"


def test_capture_refuses_run_directory_collision_before_executor_use(
    benchmark_context: BenchmarkContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    isolated_context = replace(
        benchmark_context,
        workspace_root=tmp_path.resolve(),
    )
    monkeypatch.setattr(
        corpus_runner,
        "load_benchmark_context",
        lambda *args, **kwargs: isolated_context,
    )
    run_id = "p00-us10-collision"
    run_dir = tmp_path / EVIDENCE_ROOT / run_id
    run_dir.mkdir(parents=True)
    executor_called = False

    def forbidden_executor(*args, **kwargs):
        nonlocal executor_called
        executor_called = True
        raise AssertionError("executor must not run after a collision")

    with pytest.raises(
        ValueError,
        match="canonical evidence child named by run_id",
    ):
        capture_corpus(
            run_dir=tmp_path / EVIDENCE_ROOT / "different-run-directory",
            run_id=run_id,
            selected_case_ids=("catastrophe-recap",),
            workspace_root=tmp_path,
            executor=forbidden_executor,
        )
    with pytest.raises(
        FileExistsError,
        match="refusing to overwrite immutable run directory",
    ):
        capture_corpus(
            run_dir=run_dir,
            run_id=run_id,
            selected_case_ids=("catastrophe-recap",),
            workspace_root=tmp_path,
            executor=forbidden_executor,
        )
    assert executor_called is False
    assert list(run_dir.iterdir()) == []


def test_run_record_requires_canonical_directory_and_case_record_bindings(
    benchmark_context: BenchmarkContext,
) -> None:
    run = _successful_run(
        benchmark_context,
        run_id="p00-us10-record-bindings",
        case_ids=("catastrophe-recap",),
    )

    assert run.run_dir == f"{EVIDENCE_ROOT}/{run.run_id}"
    assert tuple(
        evidence.case_id for evidence in run.case_record_evidence
    ) == run.selected_case_ids
    evidence = run.case_record_evidence[0]
    assert evidence.worker_record.path == (
        f"{run.run_dir}/catastrophe-recap/case-record.json"
    )
    assert evidence.coordinator_record.path == (
        f"{run.run_dir}/catastrophe-recap/coordinator-case-record.json"
    )

    payload = run.model_dump(mode="json")
    payload["run_dir"] = f"{EVIDENCE_ROOT}/different-run-id"
    with pytest.raises(
        ValidationError,
        match="canonical evidence child named by run_id",
    ):
        CorpusRunRecord.model_validate(payload)

    payload = run.model_dump(mode="json")
    payload["case_record_evidence"][0]["coordinator_record"]["path"] = (
        f"{run.run_dir}/catastrophe-recap/unbound-record.json"
    )
    with pytest.raises(
        ValidationError,
        match="case record evidence paths",
    ):
        CorpusRunRecord.model_validate(payload)


def test_capture_records_custom_registries_and_binds_worker_and_coordinator_records(
    benchmark_context: BenchmarkContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    isolated_context = replace(
        benchmark_context,
        workspace_root=tmp_path.resolve(),
    )
    monkeypatch.setattr(
        corpus_runner,
        "load_benchmark_context",
        lambda *args, **kwargs: isolated_context,
    )
    monkeypatch.setattr(
        corpus_runner,
        "verify_case_execution",
        lambda case, workspace_root: case,
    )
    run_id = "p00-us10-bound-records"
    relative_run_dir = Path(EVIDENCE_ROOT) / run_id
    case = isolated_context.corpus_registry.case_by_id("catastrophe-recap")

    def executor(command, **kwargs):
        output_dir = Path(command[command.index("--output-dir") + 1])
        worker = _successful_case(
            isolated_context,
            case,
            run_id=run_id,
            run_dir=relative_run_dir.as_posix(),
            order=1,
        )
        worker = CaseExecution.model_validate(
            {
                **worker.model_dump(mode="json"),
                "case_latency_ms": 123.456,
            }
        )
        corpus_runner._write_json_exclusive(
            output_dir / "case-record.json",
            worker.model_dump(mode="json"),
        )
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="worker success",
            stderr="",
        )

    corpus_registry_path = "custom/registered-corpus.json"
    control_registry_path = "custom/registered-controls.json"
    run = capture_corpus(
        run_dir=relative_run_dir,
        run_id=run_id,
        selected_case_ids=("catastrophe-recap",),
        workspace_root=tmp_path,
        corpus_registry_path=corpus_registry_path,
        control_registry_path=control_registry_path,
        executor=executor,
    )

    assert run.status == "success"
    assert run.run_dir == relative_run_dir.as_posix()
    assert run.command[run.command.index("--corpus-registry") + 1] == (
        corpus_registry_path
    )
    assert run.command[run.command.index("--control-registry") + 1] == (
        control_registry_path
    )
    command_text = (
        tmp_path / relative_run_dir / "command.txt"
    ).read_text(encoding="utf-8")
    assert f"--corpus-registry {corpus_registry_path}" in command_text
    assert f"--control-registry {control_registry_path}" in command_text

    evidence = run.case_record_evidence[0]
    worker_path = tmp_path / evidence.worker_record.path
    coordinator_path = tmp_path / evidence.coordinator_record.path
    assert sha256_file(worker_path) == evidence.worker_record.sha256
    assert worker_path.stat().st_size == evidence.worker_record.size_bytes
    assert sha256_file(coordinator_path) == evidence.coordinator_record.sha256
    assert (
        coordinator_path.stat().st_size
        == evidence.coordinator_record.size_bytes
    )

    worker = load_case_execution(worker_path)
    coordinator = load_case_execution(coordinator_path)
    assert coordinator == run.cases[0]
    assert worker.case_latency_ms == 123.456
    comparable_coordinator = CaseExecution.model_validate(
        {
            **coordinator.model_dump(mode="json"),
            "case_latency_ms": worker.case_latency_ms,
        }
    )
    assert canonical_model_bytes(worker) == canonical_model_bytes(
        comparable_coordinator
    )
    assert (tmp_path / relative_run_dir / "semantic-report.json").is_file()


def test_worker_offline_guard_runs_before_registry_or_output_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in (
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "TOKENIZERS_PARALLELISM",
    ):
        monkeypatch.delenv(name, raising=False)
    output_dir = tmp_path / "worker-output"

    with pytest.raises(ValueError, match="worker requires HF_HUB_OFFLINE=1"):
        corpus_runner.run_case_worker(
            workspace_root=tmp_path,
            corpus_registry_path="missing-registry.json",
            case_id="catastrophe-recap",
            output_dir=output_dir,
            run_id="p00-us10-offline-guard",
            order=1,
            expected_settings_sha256=SHA_A,
            expected_environment_sha256=SHA_A,
        )
    assert not output_dir.exists()

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")
    corpus_runner._require_offline_worker_environment()


def test_partial_case_and_top_level_counts_fail_closed(
    benchmark_context: BenchmarkContext,
) -> None:
    case = benchmark_context.corpus_registry.case_by_id("clinical-study")
    successful = _successful_case(
        benchmark_context,
        case,
        run_id="p00-us10-partial",
        run_dir=f"{EVIDENCE_ROOT}/p00-us10-partial",
        order=1,
    )
    output_payload = successful.output.model_dump(mode="json")
    output_payload.update(
        {
            "observed_page_count": 3,
            "successful_page_count": 2,
        }
    )
    partial_output = CaseOutputEvidence.model_validate(output_payload)
    case_payload = successful.model_dump(mode="json")
    case_payload.update(
        {
            "status": CaseStatus.PARTIAL,
            "worker_exit_code": 1,
            "output": partial_output.model_dump(mode="json"),
            "error": _error("partial-page-output").model_dump(mode="json"),
        }
    )
    partial = CaseExecution.model_validate(case_payload)

    assert partial.status is CaseStatus.PARTIAL
    assert partial.output is not None
    assert partial.output.successful_page_count == 2
    with pytest.raises(ValidationError, match="require an error"):
        CaseExecution.model_validate({**case_payload, "error": None})

    run = _successful_run(
        benchmark_context,
        run_id="p00-us10-partial",
        case_ids=("clinical-study",),
    )
    run_payload = run.model_dump(mode="json")
    run_payload.update(
        {
            "status": "completed_with_errors",
            "success_count": 0,
            "partial_count": 1,
            "successful_page_count": 2,
            "cases": [partial.model_dump(mode="json")],
        }
    )
    incomplete = CorpusRunRecord.model_validate(run_payload)
    assert incomplete.status == "completed_with_errors"
    with pytest.raises(ValidationError, match="run status"):
        CorpusRunRecord.model_validate({**run_payload, "status": "success"})


@pytest.mark.parametrize(
    ("mode", "expected_status", "error_code"),
    [
        ("missing-record", CaseStatus.ERROR, "missing-case-record"),
        ("timeout", CaseStatus.TIMEOUT, "case-timeout"),
    ],
)
def test_coordinator_retains_actionable_error_and_timeout_records(
    benchmark_context: BenchmarkContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    expected_status: CaseStatus,
    error_code: str,
) -> None:
    isolated_context = replace(
        benchmark_context,
        workspace_root=tmp_path.resolve(),
    )
    monkeypatch.setattr(
        corpus_runner,
        "load_benchmark_context",
        lambda *args, **kwargs: isolated_context,
    )
    observed_environment: dict[str, str] = {}

    def executor(command, **kwargs):
        observed_environment.update(kwargs["env"])
        if mode == "timeout":
            raise subprocess.TimeoutExpired(
                command,
                kwargs["timeout"],
                output=b"worker output",
                stderr=b"worker timeout",
            )
        return subprocess.CompletedProcess(
            command,
            returncode=7,
            stdout="worker output",
            stderr="worker error",
        )

    run_id = f"p00-us10-{mode}"
    relative_run_dir = Path(EVIDENCE_ROOT) / run_id
    run = capture_corpus(
        run_dir=relative_run_dir,
        run_id=run_id,
        selected_case_ids=("catastrophe-recap",),
        workspace_root=tmp_path,
        timeout_seconds=0.01,
        executor=executor,
    )
    retained_root = tmp_path / relative_run_dir
    retained_case = run.cases[0]

    assert run.status == "completed_with_errors"
    assert retained_case.status is expected_status
    assert retained_case.error is not None
    assert retained_case.error.code == error_code
    assert retained_case.output is None
    assert run.success_count == 0
    assert run.error_count == int(expected_status is CaseStatus.ERROR)
    assert run.timeout_count == int(expected_status is CaseStatus.TIMEOUT)
    assert not (retained_root / "semantic-report.json").exists()
    assert load_corpus_run(retained_root / "run-record.json") == run
    assert len(run.case_record_evidence) == 1
    evidence = run.case_record_evidence[0]
    assert evidence.case_id == "catastrophe-recap"
    assert evidence.worker_record.role == "worker_case_record"
    assert evidence.coordinator_record.role == "coordinator_case_record"
    assert evidence.worker_record.path == (
        f"{relative_run_dir.as_posix()}/catastrophe-recap/case-record.json"
    )
    assert evidence.coordinator_record.path == (
        f"{relative_run_dir.as_posix()}/catastrophe-recap/"
        "coordinator-case-record.json"
    )
    worker_record_path = tmp_path / evidence.worker_record.path
    coordinator_record_path = tmp_path / evidence.coordinator_record.path
    assert sha256_file(worker_record_path) == evidence.worker_record.sha256
    assert (
        worker_record_path.stat().st_size
        == evidence.worker_record.size_bytes
    )
    assert (
        sha256_file(coordinator_record_path)
        == evidence.coordinator_record.sha256
    )
    assert (
        coordinator_record_path.stat().st_size
        == evidence.coordinator_record.size_bytes
    )
    worker_record = load_case_execution(worker_record_path)
    coordinator_record = load_case_execution(coordinator_record_path)
    assert worker_record == coordinator_record == retained_case
    assert (
        retained_root
        / "catastrophe-recap"
        / "worker-stdout.log"
    ).read_text(encoding="utf-8") == "worker output"
    assert observed_environment["HF_HUB_OFFLINE"] == "1"
    assert observed_environment["TRANSFORMERS_OFFLINE"] == "1"
    assert observed_environment["TOKENIZERS_PARALLELISM"] == "false"


def test_production_tree_never_imports_benchmark_runner() -> None:
    violations: list[str] = []
    for path in sorted((WORKSPACE / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                names = (node.module or "",)
            else:
                continue
            if any(
                name == "tests"
                or name.startswith("tests.")
                or "corpus_runner" in name
                for name in names
            ):
                violations.append(f"{path.relative_to(WORKSPACE)}:{node.lineno}")
    assert violations == []

    runner_tree = ast.parse(
        Path(corpus_runner.__file__).read_text(encoding="utf-8"),
        filename=str(corpus_runner.__file__),
    )
    top_level_app_imports = []
    for node in runner_tree.body:
        if isinstance(node, ast.Import):
            names = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (node.module or "",)
        else:
            continue
        top_level_app_imports.extend(
            name for name in names if name == "app" or name.startswith("app.")
        )
    assert top_level_app_imports == []
