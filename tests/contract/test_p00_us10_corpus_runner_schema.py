"""Strict schema and invariant contract for the P00-US10 corpus runner."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import tests.benchmarks.corpus_runner as runner
from tests.benchmarks.corpus_runner import (
    DIMENSION_ORDER,
    RUNNER_VERSION,
    ArtifactEvidence,
    CaseExecution,
    CaseOutputEvidence,
    CaseRecordEvidence,
    CaseStatus,
    ClaimTreatment,
    CorpusRunRecord,
    CorpusSemanticReport,
    DimensionReport,
    EngineIdentity,
    EnvironmentIdentity,
    ErrorRecord,
    ExecutionPolicy,
    FrozenInputIdentity,
    MetricDimension,
    OfflineCostReport,
    PerformanceReport,
    ReviewedClaimResult,
    canonical_model_bytes,
    load_corpus_run,
    load_semantic_report,
    read_legacy_m0_run,
)


WORKSPACE = Path(__file__).resolve().parents[2]
LEGACY_RUN_ROOT = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
CASE_ID = "catastrophe-recap"
RUN_ID = "p00-us10-contract"
STARTED = "2026-07-29T00:00:00+00:00"
COMPLETED = "2026-07-29T00:00:01+00:00"


def _canonical_sha(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact(
    role: str,
    path: str,
    *,
    sha256: str = SHA_A,
    size_bytes: int = 10,
    derivation: str | None = None,
) -> ArtifactEvidence:
    return ArtifactEvidence(
        role=role,
        path=path,
        sha256=sha256,
        size_bytes=size_bytes,
        derivation=derivation,
    )


def _binding(
    identity: str,
    suffix: str,
    *,
    file_sha256: str = SHA_A,
    semantic_sha256: str = SHA_B,
) -> dict[str, object]:
    return {
        "identity": identity,
        "path": f"tracker/phase-00-baseline/evidence/{suffix}.json",
        "file_sha256": file_sha256,
        "semantic_sha256": semantic_sha256,
    }


def _frozen_inputs() -> FrozenInputIdentity:
    return FrozenInputIdentity(
        corpus_registry=_binding("p00-us04-corpus-registry", "corpus"),
        control_registry=_binding(
            "p00-us09-control-registry",
            "controls",
            file_sha256=SHA_B,
            semantic_sha256=SHA_C,
        ),
        review_batches=(
            _binding("p00-us06-reviewed-claims-batch-a", "batch-a"),
            _binding("p00-us07-reviewed-claims-batch-b", "batch-b"),
            _binding("p00-us08-reviewed-claims-batch-c", "batch-c"),
        ),
        legacy_metadata_sha256=SHA_D,
        legacy_comparison_sha256=SHA_E,
    )


def _environment() -> EnvironmentIdentity:
    return EnvironmentIdentity(
        application_version="0.1.0",
        application_source_sha256=SHA_A,
        runner_source_sha256=SHA_B,
        python_version="3.13.5",
        python_executable=".venv/bin/python",
        platform="test-platform",
        machine="arm64",
        processor="arm",
        logical_cpu_count=10,
        physical_cpu_count=10,
        total_memory_bytes=32 * 1024**3,
        engines=tuple(
            EngineIdentity(name=name, version="1.0")
            for name in runner.REQUIRED_ENGINE_NAMES
        ),
    )


def _execution_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        network_access="disabled",
        hosted_services="disabled",
        image_captioning=False,
        optional_models="disabled",
        hf_hub_offline=True,
        transformers_offline=True,
        tokenizers_parallelism=False,
    )


def _settings() -> dict[str, object]:
    return {
        "document_timeout_seconds": 300.0,
        "image_captioning_enabled": False,
    }


def _output_comparison(
    *,
    case_id: str = CASE_ID,
    semantic_stable: bool = True,
    markdown_stable: bool = True,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "current_semantic_json_sha256": SHA_A,
        "reference_semantic_json_sha256": (
            SHA_A if semantic_stable else SHA_B
        ),
        "semantic_json_stable": semantic_stable,
        "current_markdown_sha256": SHA_C,
        "reference_markdown_sha256": (
            SHA_C if markdown_stable else SHA_D
        ),
        "markdown_stable": markdown_stable,
    }


def _case_output() -> CaseOutputEvidence:
    raw_path = (
        "tracker/phase-00-baseline/evidence/"
        f"{RUN_ID}/{CASE_ID}/our-output.json"
    )
    return CaseOutputEvidence(
        raw_json=_artifact(
            "raw_json",
            raw_path,
            sha256=SHA_A,
            size_bytes=100,
        ),
        semantic_json=_artifact(
            "semantic_json",
            raw_path,
            sha256=SHA_B,
            size_bytes=90,
            derivation="canonical JSON excluding /processing/duration_ms",
        ),
        markdown=_artifact(
            "markdown",
            (
                "tracker/phase-00-baseline/evidence/"
                f"{RUN_ID}/{CASE_ID}/our-output.md"
            ),
            sha256=SHA_C,
            size_bytes=50,
        ),
        expected_page_count=1,
        observed_page_count=1,
        successful_page_count=1,
    )


def _case_record_evidence() -> CaseRecordEvidence:
    case_root = (
        "tracker/phase-00-baseline/evidence/"
        f"{RUN_ID}/{CASE_ID}"
    )
    return CaseRecordEvidence(
        case_id=CASE_ID,
        worker_record=_artifact(
            "worker_case_record",
            f"{case_root}/case-record.json",
            sha256=SHA_D,
            size_bytes=500,
        ),
        coordinator_record=_artifact(
            "coordinator_case_record",
            f"{case_root}/coordinator-case-record.json",
            sha256=SHA_E,
            size_bytes=500,
        ),
    )


def _source_triplet() -> tuple[ArtifactEvidence, ...]:
    return (
        _artifact(
            "source",
            f"benchmark-expertmodeldata/{CASE_ID}.pdf",
            sha256=SHA_A,
        ),
        _artifact(
            "expert_markdown",
            f"benchmark-expertmodeldata/{CASE_ID}.md",
            sha256=SHA_B,
        ),
        _artifact(
            "expert_json",
            f"benchmark-expertmodeldata/{CASE_ID}.json",
            sha256=SHA_C,
        ),
    )


def _case_execution(
    *,
    status: CaseStatus = CaseStatus.SUCCESS,
    worker_exit_code: int = 0,
    output: CaseOutputEvidence | None = None,
    reference_comparison: dict[str, object] | None = None,
    error: ErrorRecord | None = None,
    skip: dict[str, object] | None = None,
) -> CaseExecution:
    environment = _environment()
    settings = _settings()
    if output is None and status is CaseStatus.SUCCESS:
        output = _case_output()
    if reference_comparison is None and status is CaseStatus.SUCCESS:
        reference_comparison = _output_comparison()
    return CaseExecution(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=RUN_ID,
        case_id=CASE_ID,
        order=1,
        status=status,
        registered_page_count=1,
        source_triplet=_source_triplet(),
        started_at_utc=STARTED,
        completed_at_utc=COMPLETED,
        command=(".venv/bin/python", "-m", "tests.benchmarks.corpus_runner"),
        worker_exit_code=worker_exit_code,
        parse_latency_ms=10.0,
        case_latency_ms=12.0,
        cpu_ms=8.0,
        peak_rss_bytes=1024,
        settings_sha256=_canonical_sha(settings),
        environment_sha256=hashlib.sha256(
            canonical_model_bytes(environment)
        ).hexdigest(),
        output=output,
        reference_comparison=reference_comparison,
        error=error,
        skip=skip,
    )


def _run_record(*, case: CaseExecution | None = None) -> CorpusRunRecord:
    environment = _environment()
    settings = _settings()
    case = case or _case_execution()
    successful_pages = (
        case.output.successful_page_count if case.output is not None else 0
    )
    status_counts = {
        CaseStatus.SUCCESS: 0,
        CaseStatus.PARTIAL: 0,
        CaseStatus.ERROR: 0,
        CaseStatus.TIMEOUT: 0,
        CaseStatus.SKIPPED: 0,
    }
    status_counts[case.status] += 1
    all_success = case.status is CaseStatus.SUCCESS and successful_pages == 1
    return CorpusRunRecord(
        schema_version="1.0",
        record_kind="p00-us10-corpus-run",
        runner_version=RUNNER_VERSION,
        run_id=RUN_ID,
        run_dir=f"tracker/phase-00-baseline/evidence/{RUN_ID}",
        status="success" if all_success else "completed_with_errors",
        started_at_utc=STARTED,
        completed_at_utc=COMPLETED,
        command=(".venv/bin/python", "-m", "tests.benchmarks.corpus_runner"),
        cwd=".",
        settings=settings,
        settings_sha256=_canonical_sha(settings),
        execution_policy=_execution_policy(),
        environment=environment,
        environment_sha256=hashlib.sha256(
            canonical_model_bytes(environment)
        ).hexdigest(),
        frozen_inputs=_frozen_inputs(),
        selected_case_ids=(CASE_ID,),
        requested_case_count=1,
        attempted_case_count=1,
        success_count=status_counts[CaseStatus.SUCCESS],
        partial_count=status_counts[CaseStatus.PARTIAL],
        error_count=status_counts[CaseStatus.ERROR],
        timeout_count=status_counts[CaseStatus.TIMEOUT],
        skipped_count=status_counts[CaseStatus.SKIPPED],
        expected_page_count=1,
        successful_page_count=successful_pages,
        cases=(case,),
        case_record_evidence=(_case_record_evidence(),),
    )


def _source_locator(*, case_id: str = CASE_ID) -> dict[str, object]:
    return {
        "case_id": case_id,
        "physical_page": 1,
        "printed_page": "7",
        "region_id": "contract:claim:region",
        "region_scope": "source_region",
        "bbox": None,
        "coordinates": {
            "origin": "top_left",
            "unit": "pt",
            "bbox_format": "[x,y,width,height]",
            "page_space": "displayed_after_source_rotation",
        },
    }


def _claim_result(
    *,
    claim_id: str = "contract:claim:01",
    literal_eligible: bool = True,
    semantic_eligible: bool = True,
    treatment: ClaimTreatment = ClaimTreatment.PASS,
    evaluator_id: str | None = "contract-evaluator-v1",
) -> ReviewedClaimResult:
    return ReviewedClaimResult(
        claim_id=claim_id,
        case_id=CASE_ID,
        claim_type="text",
        dimension="text",
        review_status="verified",
        source_locators=(_source_locator(),),
        literal_eligible=literal_eligible,
        semantic_eligible=semantic_eligible,
        treatment=treatment,
        diagnostic_reason="Explicit synthetic contract outcome.",
        evaluator_id=evaluator_id,
        output_artifact_sha256=SHA_A,
    )


def _dimension(
    dimension: MetricDimension,
    *,
    claim: ReviewedClaimResult | None = None,
    output_comparisons: tuple[dict[str, object], ...] = (),
) -> DimensionReport:
    owns_claim = claim is not None and claim.dimension is dimension
    scored = (
        owns_claim
        and claim.treatment
        in {
            ClaimTreatment.PASS,
            ClaimTreatment.PARTIAL,
            ClaimTreatment.FAIL,
        }
    )
    return DimensionReport(
        dimension=dimension,
        claim_ids=(claim.claim_id,) if owns_claim else (),
        eligible_literal_count=(
            int(claim.literal_eligible) if owns_claim else 0
        ),
        eligible_semantic_count=(
            int(claim.semantic_eligible) if owns_claim else 0
        ),
        scored_count=int(scored),
        pass_count=int(scored and claim.treatment is ClaimTreatment.PASS),
        partial_count=int(
            scored and claim.treatment is ClaimTreatment.PARTIAL
        ),
        fail_count=int(scored and claim.treatment is ClaimTreatment.FAIL),
        diagnostic_only_count=int(
            owns_claim
            and claim.treatment is ClaimTreatment.DIAGNOSTIC_ONLY
        ),
        excluded_count=int(
            owns_claim
            and claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
        ),
        output_comparisons=output_comparisons,
        observation=f"{dimension.value} reported independently.",
    )


def _distribution(value: float = 10.0) -> dict[str, object]:
    return {
        "count": 1,
        "minimum": value,
        "p50": value,
        "p95": value,
        "maximum": value,
        "mean": value,
    }


def _performance(
    *,
    environment_comparable: bool = True,
    within_tolerance: bool | None = True,
) -> PerformanceReport:
    return PerformanceReport(
        case_count=1,
        case_latency_ms=_distribution(12.0),
        parse_latency_ms=_distribution(10.0),
        cpu_ms=_distribution(8.0),
        peak_rss_bytes=_distribution(1024.0),
        total_raw_json_bytes=100,
        total_markdown_bytes=50,
        reference_latency_p50_ms=20.0,
        reference_latency_p95_ms=20.0,
        reference_rss_p50_bytes=2048.0,
        reference_rss_max_bytes=2048.0,
        tolerance_percent=25.0,
        environment_comparable=environment_comparable,
        within_tolerance=within_tolerance,
    )


def _cost() -> OfflineCostReport:
    return OfflineCostReport(
        hosted_requests=0,
        prompt_tokens=0,
        completion_tokens=0,
        billed_usd=0.0,
        method="fixed offline execution policy",
    )


def _semantic_report() -> CorpusSemanticReport:
    run = _run_record()
    claim = _claim_result()
    comparison_payload = _output_comparison()
    dimensions = tuple(
        _dimension(
            dimension,
            claim=claim,
            output_comparisons=(
                (comparison_payload,)
                if dimension is MetricDimension.JSON
                else ()
            ),
        )
        for dimension in DIMENSION_ORDER
    )
    comparison = runner.OutputComparison.model_validate(comparison_payload)
    return CorpusSemanticReport(
        schema_version="1.0",
        report_kind="p00-us10-corpus-semantic-report",
        runner_version=RUNNER_VERSION,
        run_id=RUN_ID,
        run_record=_artifact(
            "corpus_run_record",
            (
                "tracker/phase-00-baseline/evidence/"
                f"{RUN_ID}/run-record.json"
            ),
            sha256=SHA_D,
            size_bytes=1000,
        ),
        run_semantic_sha256=hashlib.sha256(
            canonical_model_bytes(run)
        ).hexdigest(),
        frozen_inputs=_frozen_inputs(),
        selected_case_ids=(CASE_ID,),
        case_count=1,
        page_count=1,
        reviewed_claim_count=1,
        literal_eligible_count=1,
        semantic_eligible_count=1,
        excluded_unsupported_count=0,
        scored_claim_count=1,
        diagnostic_only_count=0,
        claim_ledger=(claim,),
        dimensions=dimensions,
        performance=_performance(),
        cost=_cost(),
        quality_signature_sha256=runner._quality_signature(
            (claim,),
            dimensions,
        ),
        stable_output_signature_sha256=runner._stable_output_signature(
            (comparison,)
        ),
        all_outputs_stable=True,
    )


STRICT_MODELS = (
    ArtifactEvidence,
    EngineIdentity,
    EnvironmentIdentity,
    FrozenInputIdentity,
    ExecutionPolicy,
    ErrorRecord,
    CaseOutputEvidence,
    CaseExecution,
    CaseRecordEvidence,
    ReviewedClaimResult,
    DimensionReport,
    PerformanceReport,
    OfflineCostReport,
    CorpusRunRecord,
    CorpusSemanticReport,
)


def _payload(model: Any) -> dict[str, Any]:
    return deepcopy(model.model_dump(mode="json"))


@pytest.mark.parametrize("model", STRICT_MODELS)
def test_runner_models_are_strict_frozen_contracts(model: type[Any]) -> None:
    schema = model.model_json_schema()

    assert model.model_config["extra"] == "forbid"
    assert model.model_config["frozen"] is True
    assert schema["additionalProperties"] is False


def test_enums_and_dimension_order_are_exact_and_versioned() -> None:
    assert RUNNER_VERSION == "P00-US10-1.0"
    assert tuple(dimension.value for dimension in DIMENSION_ORDER) == (
        "text",
        "layout",
        "reading_order",
        "table",
        "chart",
        "diagram",
        "markdown",
        "json",
        "hallucination",
        "diagnostics",
        "performance",
        "cost",
    )
    assert DIMENSION_ORDER == tuple(MetricDimension)
    assert {status.value for status in CaseStatus} == {
        "success",
        "partial",
        "error",
        "timeout",
        "skipped",
    }
    assert {treatment.value for treatment in ClaimTreatment} == {
        "pass",
        "partial",
        "fail",
        "diagnostic_only",
        "excluded_unsupported",
    }


def test_canonical_model_bytes_are_deterministic_and_models_are_immutable() -> None:
    first = _artifact("raw_json", "evidence/output.json", sha256=SHA_A)
    second = ArtifactEvidence.model_validate(
        {
            "size_bytes": first.size_bytes,
            "sha256": first.sha256,
            "path": first.path,
            "role": first.role,
            "derivation": first.derivation,
        }
    )

    assert canonical_model_bytes(first) == canonical_model_bytes(second)
    assert canonical_model_bytes(first) == (
        b'{"derivation":null,"path":"evidence/output.json","role":"raw_json",'
        b'"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"size_bytes":10}'
    )
    with pytest.raises(ValidationError, match="frozen"):
        first.role = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "path",
    (
        "/absolute/output.json",
        "../escape.json",
        "evidence/../escape.json",
        "evidence\\output.json",
        "evidence//output.json",
    ),
)
def test_artifact_paths_fail_closed(path: str) -> None:
    with pytest.raises(ValidationError, match="portable|canonical"):
        _artifact("raw_json", path)


def test_artifact_rejects_extra_fields_and_invalid_hashes() -> None:
    payload = _payload(_artifact("raw_json", "evidence/output.json"))
    payload["silent_extra"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        ArtifactEvidence.model_validate(payload)

    payload.pop("silent_extra")
    payload["sha256"] = "not-a-hash"
    with pytest.raises(ValidationError, match="pattern"):
        ArtifactEvidence.model_validate(payload)


@pytest.mark.parametrize("value", ("", "unknown", " unavailable ", "null"))
def test_engine_identity_rejects_missing_or_ambiguous_versions(
    value: str,
) -> None:
    with pytest.raises(ValidationError, match="explicit|at least 1"):
        EngineIdentity(name="docling", version=value)


def test_environment_requires_every_engine_once_in_canonical_order() -> None:
    environment = _environment()
    payload = _payload(environment)
    payload["engines"] = payload["engines"][:-1]
    with pytest.raises(
        ValidationError,
        match="at least 6|every required engine",
    ):
        EnvironmentIdentity.model_validate(payload)

    payload = _payload(environment)
    payload["engines"][0], payload["engines"][1] = (
        payload["engines"][1],
        payload["engines"][0],
    )
    with pytest.raises(ValidationError, match="required engine in order"):
        EnvironmentIdentity.model_validate(payload)

    payload = _payload(environment)
    payload["application_version"] = "unavailable"
    with pytest.raises(ValidationError, match="application version"):
        EnvironmentIdentity.model_validate(payload)


def test_frozen_inputs_require_three_unique_canonical_review_batches() -> None:
    inputs = _frozen_inputs()
    payload = _payload(inputs)
    payload["review_batches"][2] = payload["review_batches"][1]
    with pytest.raises(ValidationError, match="identities must be unique"):
        FrozenInputIdentity.model_validate(payload)

    payload = _payload(inputs)
    payload["review_batches"].reverse()
    with pytest.raises(ValidationError, match="canonical order"):
        FrozenInputIdentity.model_validate(payload)


def test_execution_policy_cannot_silently_enable_external_models() -> None:
    policy = _execution_policy()
    for field, value in (
        ("network_access", "enabled"),
        ("hosted_services", "enabled"),
        ("image_captioning", True),
        ("optional_models", "enabled"),
        ("hf_hub_offline", False),
    ):
        payload = _payload(policy)
        payload[field] = value
        with pytest.raises(ValidationError):
            ExecutionPolicy.model_validate(payload)


def test_error_records_require_actionable_nonempty_evidence() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        ErrorRecord(
            code="parse_failed",
            stage="parse",
            exception_type="RuntimeError",
            message="failure",
            remediation="",
            traceback="trace",
        )


def test_case_output_requires_roles_volatility_mask_and_page_consistency() -> None:
    output = _case_output()

    payload = _payload(output)
    payload["raw_json"]["role"] = "json"
    with pytest.raises(ValidationError, match="canonical roles"):
        CaseOutputEvidence.model_validate(payload)

    payload = _payload(output)
    payload["semantic_json"]["path"] = "evidence/semantic.json"
    with pytest.raises(ValidationError, match="derived from the raw JSON"):
        CaseOutputEvidence.model_validate(payload)

    payload = _payload(output)
    payload["semantic_json"]["derivation"] = "all fields"
    with pytest.raises(ValidationError, match="volatility mask"):
        CaseOutputEvidence.model_validate(payload)

    payload = _payload(output)
    payload["successful_page_count"] = 2
    with pytest.raises(ValidationError, match="cannot exceed observed"):
        CaseOutputEvidence.model_validate(payload)


def test_successful_case_requires_clean_complete_page_and_output_evidence() -> None:
    case = _case_execution()
    for field, value, message in (
        ("worker_exit_code", 1, "exit code zero"),
        ("output", None, "complete clean evidence"),
        ("reference_comparison", None, "complete clean evidence"),
        (
            "error",
            {
                "code": "unexpected",
                "stage": "parse",
                "exception_type": "RuntimeError",
                "message": "failure",
                "remediation": "inspect",
                "traceback": "trace",
            },
            "complete clean evidence",
        ),
    ):
        payload = _payload(case)
        payload[field] = value
        with pytest.raises(ValidationError, match=message):
            CaseExecution.model_validate(payload)

    payload = _payload(case)
    payload["output"]["successful_page_count"] = 0
    with pytest.raises(ValidationError, match="every registered page"):
        CaseExecution.model_validate(payload)


def test_non_successful_cases_require_explicit_failure_or_skip_evidence() -> None:
    success = _case_execution()

    for status in ("partial", "error", "timeout"):
        payload = _payload(success)
        payload.update(
            {
                "status": status,
                "worker_exit_code": 1,
                "output": None,
                "reference_comparison": None,
                "error": None,
            }
        )
        with pytest.raises(ValidationError, match="require an error"):
            CaseExecution.model_validate(payload)

    payload = _payload(success)
    payload.update(
        {
            "status": "skipped",
            "worker_exit_code": 0,
            "output": None,
            "reference_comparison": None,
            "skip": None,
        }
    )
    with pytest.raises(ValidationError, match="explicit skip"):
        CaseExecution.model_validate(payload)


def test_case_identity_time_and_triplet_order_fail_closed() -> None:
    case = _case_execution()
    payload = _payload(case)
    payload["run_id"] = "INVALID RUN"
    with pytest.raises(ValidationError, match="stable lowercase"):
        CaseExecution.model_validate(payload)

    payload = _payload(case)
    payload["completed_at_utc"] = "2026-07-28T23:59:59+00:00"
    with pytest.raises(ValidationError, match="cannot precede"):
        CaseExecution.model_validate(payload)

    payload = _payload(case)
    payload["source_triplet"].reverse()
    with pytest.raises(ValidationError, match="canonical roles"):
        CaseExecution.model_validate(payload)


def test_reviewed_claims_preserve_dimension_masks_and_evaluator_boundary() -> None:
    claim = _claim_result()

    payload = _payload(claim)
    payload["dimension"] = "chart"
    with pytest.raises(ValidationError, match="versioned type map"):
        ReviewedClaimResult.model_validate(payload)

    payload = _payload(claim)
    payload["semantic_eligible"] = False
    with pytest.raises(ValidationError, match="requires semantic"):
        ReviewedClaimResult.model_validate(payload)

    payload = _payload(claim)
    payload["evaluator_id"] = None
    with pytest.raises(ValidationError, match="versioned evaluator"):
        ReviewedClaimResult.model_validate(payload)

    payload = _payload(claim)
    payload["treatment"] = "diagnostic_only"
    with pytest.raises(ValidationError, match="cannot name"):
        ReviewedClaimResult.model_validate(payload)

    payload = _payload(claim)
    payload["treatment"] = "partial"
    with pytest.raises(ValidationError, match="cannot be partially"):
        ReviewedClaimResult.model_validate(payload)

    payload = _payload(claim)
    payload["source_locators"][0]["case_id"] = "other-case"
    with pytest.raises(ValidationError, match="claim case"):
        ReviewedClaimResult.model_validate(payload)


def test_unsupported_claims_cannot_enter_any_scored_denominator() -> None:
    payload = _payload(_claim_result())
    payload.update(
        {
            "review_status": "incorrect",
            "literal_eligible": True,
            "semantic_eligible": True,
            "treatment": "pass",
        }
    )
    with pytest.raises(ValidationError, match="cannot enter a denominator"):
        ReviewedClaimResult.model_validate(payload)

    payload.update(
        {
            "literal_eligible": False,
            "semantic_eligible": False,
            "treatment": "diagnostic_only",
            "evaluator_id": None,
        }
    )
    with pytest.raises(ValidationError, match="explicit exclusions"):
        ReviewedClaimResult.model_validate(payload)

    payload["treatment"] = "excluded_unsupported"
    assert (
        ReviewedClaimResult.model_validate(payload).treatment
        is ClaimTreatment.EXCLUDED_UNSUPPORTED
    )


def test_dimension_reports_reconcile_counts_and_unique_references() -> None:
    dimension = _dimension(MetricDimension.TEXT, claim=_claim_result())

    payload = _payload(dimension)
    payload["scored_count"] = 2
    with pytest.raises(ValidationError, match="pass/partial/fail"):
        DimensionReport.model_validate(payload)

    payload = _payload(dimension)
    payload["claim_ids"] = [payload["claim_ids"][0]] * 2
    with pytest.raises(ValidationError, match="claim IDs must be unique"):
        DimensionReport.model_validate(payload)

    payload = _payload(
        _dimension(
            MetricDimension.JSON,
            output_comparisons=(_output_comparison(),),
        )
    )
    payload["output_comparisons"].append(
        deepcopy(payload["output_comparisons"][0])
    )
    with pytest.raises(ValidationError, match="unique by case"):
        DimensionReport.model_validate(payload)


def test_performance_requires_complete_distributions_and_honest_tolerance() -> None:
    report = _performance()

    payload = _payload(report)
    payload["cpu_ms"]["count"] = 2
    with pytest.raises(ValidationError, match="every distribution"):
        PerformanceReport.model_validate(payload)

    payload = _payload(report)
    payload["within_tolerance"] = False
    with pytest.raises(ValidationError, match="declared bounds"):
        PerformanceReport.model_validate(payload)

    with pytest.raises(ValidationError, match="cannot claim"):
        _performance(
            environment_comparable=False,
            within_tolerance=True,
        )

    assert (
        _performance(
            environment_comparable=False,
            within_tolerance=None,
        ).within_tolerance
        is None
    )


def test_performance_distribution_rejects_disordered_quantiles() -> None:
    payload = _payload(_performance())
    payload["case_latency_ms"].update(
        {"minimum": 10, "p50": 9, "p95": 8, "maximum": 7}
    )
    with pytest.raises(ValidationError, match="quantiles must be ordered"):
        PerformanceReport.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("hosted_requests", 1),
        ("prompt_tokens", 1),
        ("completion_tokens", 1),
        ("billed_usd", 0.01),
    ),
)
def test_offline_cost_cannot_hide_hosted_usage(
    field: str,
    value: int | float,
) -> None:
    payload = _payload(_cost())
    payload[field] = value
    with pytest.raises(ValidationError):
        OfflineCostReport.model_validate(payload)


def test_corpus_run_reconciles_settings_environment_cases_and_counts() -> None:
    run = _run_record()

    payload = _payload(run)
    payload["settings_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="does not match settings"):
        CorpusRunRecord.model_validate(payload)

    payload = _payload(run)
    payload["environment_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="does not match environment"):
        CorpusRunRecord.model_validate(payload)

    payload = _payload(run)
    payload["success_count"] = 0
    with pytest.raises(ValidationError, match="counts do not reconcile"):
        CorpusRunRecord.model_validate(payload)

    payload = _payload(run)
    payload["cases"][0]["settings_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="top-level settings"):
        CorpusRunRecord.model_validate(payload)

    payload = _payload(run)
    payload["status"] = "completed_with_errors"
    with pytest.raises(ValidationError, match="status does not match"):
        CorpusRunRecord.model_validate(payload)


def test_corpus_run_rejects_duplicate_unknown_or_misordered_cases() -> None:
    run = _run_record()
    payload = _payload(run)
    payload["selected_case_ids"] = [CASE_ID, CASE_ID]
    payload["requested_case_count"] = 2
    with pytest.raises(ValidationError, match="must be unique"):
        CorpusRunRecord.model_validate(payload)

    payload = _payload(run)
    payload["selected_case_ids"] = ["not-registered"]
    payload["cases"][0]["case_id"] = "not-registered"
    with pytest.raises(ValidationError, match="canonical registry order"):
        CorpusRunRecord.model_validate(payload)


def test_run_loader_round_trips_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    run = _run_record()
    path = tmp_path / "run-record.json"
    path.write_bytes(canonical_model_bytes(run))

    assert load_corpus_run(path) == run

    payload = _payload(run)
    payload["silent_extra"] = "not allowed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_corpus_run(path)


def test_semantic_report_reconciles_all_dimensions_claims_and_signatures() -> None:
    report = _semantic_report()

    assert tuple(item.dimension for item in report.dimensions) == DIMENSION_ORDER
    assert report.reviewed_claim_count == 1
    assert report.literal_eligible_count == 1
    assert report.semantic_eligible_count == 1
    assert report.scored_claim_count == 1
    assert report.all_outputs_stable
    assert "overall_score" not in CorpusSemanticReport.model_fields


def test_semantic_report_rejects_missing_or_misordered_dimensions() -> None:
    report = _semantic_report()

    payload = _payload(report)
    payload["dimensions"] = payload["dimensions"][:-1]
    with pytest.raises(
        ValidationError,
        match="at least 12|all 12 dimensions",
    ):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    payload["dimensions"][0], payload["dimensions"][1] = (
        payload["dimensions"][1],
        payload["dimensions"][0],
    )
    with pytest.raises(ValidationError, match="canonical order"):
        CorpusSemanticReport.model_validate(payload)


def test_semantic_report_rejects_claim_count_and_primary_coverage_drift() -> None:
    report = _semantic_report()

    payload = _payload(report)
    payload["reviewed_claim_count"] = 2
    with pytest.raises(ValidationError, match="counts do not reconcile"):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    text_report = next(
        item for item in payload["dimensions"] if item["dimension"] == "text"
    )
    text_report["claim_ids"] = []
    with pytest.raises(ValidationError, match="exactly cover the ledger"):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    payload["claim_ledger"] = [
        payload["claim_ledger"][0],
        payload["claim_ledger"][0],
    ]
    payload["reviewed_claim_count"] = 2
    with pytest.raises(ValidationError, match="unique and canonical"):
        CorpusSemanticReport.model_validate(payload)


def test_semantic_report_rejects_false_output_and_signature_claims() -> None:
    report = _semantic_report()

    payload = _payload(report)
    payload["all_outputs_stable"] = False
    with pytest.raises(ValidationError, match="does not match comparisons"):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    payload["quality_signature_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="quality signature"):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    payload["stable_output_signature_sha256"] = SHA_A
    with pytest.raises(ValidationError, match="stable output signature"):
        CorpusSemanticReport.model_validate(payload)

    payload = _payload(report)
    payload["run_record"]["role"] = "raw_json"
    with pytest.raises(ValidationError, match="corpus run record"):
        CorpusSemanticReport.model_validate(payload)


def test_semantic_report_loader_round_trips_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    report = _semantic_report()
    path = tmp_path / "semantic-report.json"
    path.write_bytes(canonical_model_bytes(report))

    assert load_semantic_report(path) == report

    payload = _payload(report)
    payload["overall_score"] = 1.0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs"):
        load_semantic_report(path)


def test_legacy_m0_reader_is_strict_read_only_and_preserves_source_bytes() -> None:
    metadata_path = LEGACY_RUN_ROOT / "run-metadata.json"
    comparison_path = LEGACY_RUN_ROOT / "comparison-summary.json"
    before_metadata = metadata_path.read_bytes()
    before_comparison = comparison_path.read_bytes()

    legacy = read_legacy_m0_run(WORKSPACE)

    assert legacy.schema_version == "1.0"
    assert legacy.status == "success"
    assert legacy.case_count == 15
    assert legacy.page_count == 30
    assert legacy.case_ids == runner.EXPECTED_CASE_IDS
    assert metadata_path.read_bytes() == before_metadata
    assert comparison_path.read_bytes() == before_comparison
