"""Contract and local-only controls for LAT-US02 prewarm evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_prewarm_contracts import (
    AttemptStatus,
    CleanupEvidence,
    EvaluationFailureCode,
    FailureCode,
    FailureRecord,
    LocalPrewarmAttempt,
    LocalPrewarmEvidenceBundle,
    OutputIdentity,
    RequestObservation,
    ResourcePhase,
    RSS_DISPOSITION,
    RunMode,
    configuration_identity,
    evaluate_local_prewarm_bundle,
)
from tests.benchmarks.latency_prewarm_runner import (
    LocalCampaignResult,
    LocalCase,
    run_synthetic_local_campaign,
)


@pytest.fixture(scope="module")
def local_result(tmp_path_factory: pytest.TempPathFactory) -> LocalCampaignResult:
    directory = tmp_path_factory.mktemp("lat-us02-prewarm-contract")
    source = directory / "synthetic-prewarm.pdf"
    source.write_bytes(b"%PDF-1.7\n% bounded LAT-US02 contract control\n%%EOF\n")
    return run_synthetic_local_campaign(
        workspace=Path(__file__).resolve().parents[2],
        cases=(
            LocalCase(
                case_id="synthetic-prewarm",
                source_path=source,
                source_label="tests/fixtures/phase_latency/synthetic-prewarm.pdf",
                page_count=1,
                directional_llama_latency_ms=29_400,
            ),
        ),
        repetitions=2,
        request_count=2,
    )


def _replace_attempt(
    bundle: LocalPrewarmEvidenceBundle, changed: LocalPrewarmAttempt
) -> LocalPrewarmEvidenceBundle:
    payload = bundle.model_dump(mode="python")
    payload["attempts"] = tuple(
        changed if item.attempt_id == changed.attempt_id else item
        for item in bundle.attempts
    )
    return LocalPrewarmEvidenceBundle.model_validate(payload)


def test_local_runner_retains_repeated_enabled_and_predecessor_attempts(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    evaluation = local_result.evaluation

    assert bundle.evidence_scope == "synthetic_contract_control"
    assert len(bundle.attempts) == 4
    assert tuple(item.mode for item in bundle.attempts) == (
        RunMode.PREDECESSOR,
        RunMode.ENABLED,
        RunMode.PREDECESSOR,
        RunMode.ENABLED,
    )
    assert bundle.case_indexes[0].predecessor_attempt_ids == (
        "lat-us02-synthetic-prewarm-predecessor_lazy-r01",
        "lat-us02-synthetic-prewarm-predecessor_lazy-r02",
    )
    assert bundle.case_indexes[0].enabled_attempt_ids == (
        "lat-us02-synthetic-prewarm-prewarm_enabled-r01",
        "lat-us02-synthetic-prewarm-prewarm_enabled-r02",
    )
    assert evaluation.attempt_count == 4
    assert evaluation.case_count == 1
    assert evaluation.failure_codes == ()
    assert evaluation.non_rss_blocking_gates_passed is True
    assert evaluation.completion_eligible_under_owner_rss_deferral is True
    assert evaluation.cases[0].byte_output_parity is True
    assert evaluation.cases[0].semantic_output_parity is True
    assert evaluation.cases[0].latency_improved_or_preserved is True


def test_every_attempt_retains_exact_identity_timing_output_and_resources(
    local_result: LocalCampaignResult,
) -> None:
    for attempt in local_result.bundle.attempts:
        assert attempt.source.sha256
        assert attempt.execution.application_code_sha256
        assert attempt.execution.dependency_manifest_sha256
        assert attempt.execution.parser_runtime_sha256
        assert attempt.execution.runtime_artifacts.artifacts
        assert attempt.configuration.sha256
        assert attempt.worker.startup_duration_ns >= 0
        assert attempt.worker.application_identity_validated is True
        assert attempt.worker.dependency_identity_validated is True
        assert attempt.worker.parser_runtime_identity_validated is True
        assert attempt.worker.runtime_artifact_identity_validated is True
        assert attempt.worker.configuration_identity_validated is True
        assert attempt.worker.converter_identity_validated is True
        assert len(attempt.worker.requests) == 2
        assert all(item.latency_ns > 0 for item in attempt.worker.requests)
        assert all(item.output is not None for item in attempt.worker.requests)
        assert attempt.worker.resources.cold_initialization.rss_bytes > 0
        assert attempt.worker.resources.request_peak.rss_bytes > 0
        assert attempt.worker.resources.repeated_request.rss_bytes > 0
        assert attempt.worker.resources.shutdown.rss_bytes > 0
        assert attempt.cleanup.worker_exited is True
        assert attempt.cleanup.worker_reaped is True
        assert attempt.cleanup.all_owned_processes_reaped is True
        assert attempt.cleanup.threads_returned_to_baseline is True
        assert attempt.cleanup.file_descriptors_returned_to_baseline is True
        if attempt.mode is RunMode.ENABLED:
            assert attempt.worker.prewarm_completed is True
            assert attempt.worker.resources.prewarmed_idle is not None
            assert (
                attempt.worker.resources.prewarmed_idle.phase
                is ResourcePhase.PREWARMED_IDLE
            )
        else:
            assert attempt.worker.prewarm_completed is False
            assert attempt.worker.resources.prewarmed_idle is None


def test_all_hosted_cost_and_qualification_fields_are_hard_zero_or_false(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    assert bundle.hosted_campaign_invoked is False
    assert bundle.hosted_calls == 0
    assert bundle.hosted_credits == 0
    assert bundle.prompt_tokens == 0
    assert bundle.completion_tokens == 0
    assert bundle.billed_cost_microusd == 0
    assert bundle.egress_bytes == 0
    assert bundle.llamaparse_qualification_claimed is False
    assert bundle.directional_llama_references[0].directional_only is True
    assert bundle.directional_llama_references[0].qualification_claimed is False
    for attempt in bundle.attempts:
        assert attempt.hosted_calls == 0
        assert attempt.hosted_credits == 0
        assert attempt.prompt_tokens == 0
        assert attempt.completion_tokens == 0
        assert attempt.billed_cost_microusd == 0
        assert attempt.egress_bytes == 0
        assert attempt.worker.hosted_calls == 0

    payload = bundle.model_dump(mode="python")
    payload["hosted_calls"] = 1
    with pytest.raises(ValidationError):
        LocalPrewarmEvidenceBundle.model_validate(payload)


def test_rss_is_explicitly_observational_and_cannot_claim_a_strict_pass(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    evaluation = local_result.evaluation
    assert bundle.rss_disposition == RSS_DISPOSITION
    assert bundle.strict_rss_gate_pass_claimed is False
    assert evaluation.rss_disposition == RSS_DISPOSITION
    assert evaluation.strict_rss_gate_pass_claimed is False
    for attempt in bundle.attempts:
        assert attempt.rss_disposition == RSS_DISPOSITION
        assert attempt.strict_rss_gate_pass_claimed is False
        assert attempt.worker.rss_disposition == RSS_DISPOSITION
        assert attempt.worker.strict_rss_gate_pass_claimed is False

    payload = bundle.model_dump(mode="python")
    payload["strict_rss_gate_pass_claimed"] = True
    with pytest.raises(ValidationError):
        LocalPrewarmEvidenceBundle.model_validate(payload)


def test_large_numerical_rss_does_not_change_non_rss_evaluation(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    attempt = bundle.attempts[0]
    resources = attempt.worker.resources
    huge = 16 * 1024 * 1024 * 1024
    changed_resources = resources.model_copy(
        update={
            "request_peak": resources.request_peak.model_copy(
                update={"rss_bytes": huge}
            ),
            "repeated_request": resources.repeated_request.model_copy(
                update={"rss_bytes": huge + 1}
            ),
        }
    )
    changed_worker = attempt.worker.model_copy(update={"resources": changed_resources})
    changed_attempt = attempt.model_copy(update={"worker": changed_worker})
    changed_bundle = _replace_attempt(bundle, changed_attempt)

    evaluation = evaluate_local_prewarm_bundle(changed_bundle)
    assert evaluation.failure_codes == ()
    assert evaluation.strict_rss_gate_pass_claimed is False
    assert evaluation.rss_disposition == RSS_DISPOSITION


@pytest.mark.parametrize(
    ("updates", "failure_code"),
    (
        ({"cleanup_completed": False}, EvaluationFailureCode.CLEANUP_FAILED),
        (
            {
                "cleanup_completed": False,
                "owned_process_count_after_shutdown": 1,
                "all_owned_processes_reaped": False,
            },
            EvaluationFailureCode.ORPHANED_PROCESS,
        ),
        ({"threads_returned_to_baseline": False}, EvaluationFailureCode.THREAD_LEAK),
        (
            {"file_descriptors_returned_to_baseline": False},
            EvaluationFailureCode.FILE_DESCRIPTOR_LEAK,
        ),
        ({"oom_observed": True}, EvaluationFailureCode.WORKER_OOM),
        (
            {"unbounded_rss_growth_observed": True},
            EvaluationFailureCode.UNBOUNDED_RSS_GROWTH,
        ),
        (
            {"state_retention_detected": True},
            EvaluationFailureCode.CROSS_REQUEST_STATE_RETAINED,
        ),
    ),
)
def test_reliability_resource_failures_remain_blocking(
    local_result: LocalCampaignResult,
    updates: dict[str, object],
    failure_code: EvaluationFailureCode,
) -> None:
    bundle = local_result.bundle
    attempt = bundle.attempts[0]
    cleanup_payload = attempt.cleanup.model_dump(mode="python")
    cleanup_payload.update(updates)
    cleanup = CleanupEvidence.model_validate(cleanup_payload)
    changed_bundle = _replace_attempt(
        bundle, attempt.model_copy(update={"cleanup": cleanup})
    )

    evaluation = evaluate_local_prewarm_bundle(changed_bundle)
    assert failure_code in evaluation.failure_codes
    assert evaluation.non_rss_blocking_gates_passed is False
    assert evaluation.completion_eligible_under_owner_rss_deferral is False
    assert evaluation.strict_rss_gate_pass_claimed is False


def test_failed_attempt_is_retained_and_blocks_without_retry_masking(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    attempt = bundle.attempts[0]
    first = attempt.worker.requests[0]
    request_failure = FailureRecord(
        code=FailureCode.REQUEST_FAILED,
        stage="request",
        detail_sha256="d" * 64,
        retryable=False,
    )
    failed_request = RequestObservation(
        request_index=first.request_index,
        latency_ns=first.latency_ns,
        status=AttemptStatus.ERROR,
        output=None,
        failure=request_failure,
    )
    worker = attempt.worker.model_copy(
        update={"requests": (failed_request, *attempt.worker.requests[1:])}
    )
    failed_attempt = LocalPrewarmAttempt.model_validate(
        {
            **attempt.model_dump(mode="python"),
            "worker": worker,
            "status": AttemptStatus.ERROR,
            "failure": request_failure,
        }
    )
    changed_bundle = _replace_attempt(bundle, failed_attempt)

    assert len(changed_bundle.attempts) == len(bundle.attempts)
    assert changed_bundle.attempts[0].status is AttemptStatus.ERROR
    evaluation = evaluate_local_prewarm_bundle(changed_bundle)
    assert EvaluationFailureCode.ATTEMPT_FAILED in evaluation.failure_codes
    assert EvaluationFailureCode.LATENCY_REGRESSION in evaluation.failure_codes


def test_json_raw_hash_may_vary_when_duration_normalized_bytes_match(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    attempt = bundle.attempts[0]
    request = attempt.worker.requests[0]
    assert request.output is not None
    output = request.output.model_copy(
        update={"sha256": "e" * 64, "size_bytes": request.output.size_bytes + 7}
    )
    changed_request = request.model_copy(update={"output": output})
    worker = attempt.worker.model_copy(
        update={"requests": (changed_request, *attempt.worker.requests[1:])}
    )
    changed_bundle = _replace_attempt(
        bundle, attempt.model_copy(update={"worker": worker})
    )

    evaluation = evaluate_local_prewarm_bundle(changed_bundle)
    assert evaluation.cases[0].byte_output_parity is True
    assert EvaluationFailureCode.OUTPUT_BYTE_PARITY_FAILED not in (
        evaluation.failure_codes
    )


def test_changed_normalized_json_or_semantic_identity_blocks_parity(
    local_result: LocalCampaignResult,
) -> None:
    bundle = local_result.bundle
    attempt = bundle.attempts[0]
    request = attempt.worker.requests[0]
    assert request.output is not None
    output = request.output.model_copy(
        update={"normalized_sha256": "e" * 64, "semantic_sha256": "f" * 64}
    )
    worker = attempt.worker.model_copy(
        update={
            "requests": (
                request.model_copy(update={"output": output}),
                *attempt.worker.requests[1:],
            )
        }
    )
    changed_bundle = _replace_attempt(
        bundle, attempt.model_copy(update={"worker": worker})
    )

    evaluation = evaluate_local_prewarm_bundle(changed_bundle)
    assert EvaluationFailureCode.OUTPUT_BYTE_PARITY_FAILED in evaluation.failure_codes
    assert EvaluationFailureCode.OUTPUT_SEMANTIC_PARITY_FAILED in (
        evaluation.failure_codes
    )


def test_markdown_requires_exact_raw_byte_identity() -> None:
    with pytest.raises(ValidationError, match="Markdown"):
        OutputIdentity(
            sha256="a" * 64,
            normalized_sha256="b" * 64,
            semantic_sha256="a" * 64,
            size_bytes=10,
            media_type="text/markdown",
            validation="ParseResult",
            normalization_policy="raw_bytes_exact_v1",
        )


def test_bundle_rejects_dropped_or_unindexed_attempt_history(
    local_result: LocalCampaignResult,
) -> None:
    payload = local_result.bundle.model_dump(mode="python")
    payload["attempts"] = payload["attempts"][:-1]
    with pytest.raises(ValidationError, match="unknown attempt|every retained"):
        LocalPrewarmEvidenceBundle.model_validate(payload)

    payload = local_result.bundle.model_dump(mode="python")
    payload["attempts"] = (*payload["attempts"], payload["attempts"][0])
    with pytest.raises(ValidationError, match="unique"):
        LocalPrewarmEvidenceBundle.model_validate(payload)


def test_configuration_is_exact_default_off_or_enabled_pair() -> None:
    predecessor = configuration_identity(
        prewarm_enabled=False, startup_timeout_ns=5_000_000_000
    )
    enabled = configuration_identity(
        prewarm_enabled=True, startup_timeout_ns=5_000_000_000
    )
    assert predecessor.prewarm_enabled is False
    assert enabled.prewarm_enabled is True
    assert predecessor.feature_flag == "parser.latency.prewarm.enabled"
    assert predecessor.runtime_downloads_allowed is False
    assert predecessor.mutable_cross_request_state_allowed is False

    payload = predecessor.model_dump(mode="python")
    payload["startup_timeout_ns"] += 1
    with pytest.raises(ValidationError, match="configuration identity"):
        type(predecessor).model_validate(payload)


def test_contract_models_are_closed_and_immutable(
    local_result: LocalCampaignResult,
) -> None:
    payload = local_result.bundle.model_dump(mode="python")
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        LocalPrewarmEvidenceBundle.model_validate(payload)

    with pytest.raises(ValidationError):
        local_result.bundle.hosted_calls = 1  # type: ignore[misc]
