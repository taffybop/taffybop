"""Strict schema and comparability guards for phase-latency evidence."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_contracts import (
    ArtifactIdentity,
    AttemptStatus,
    ConfigurationIdentity,
    LatencyAttempt,
    LatencyCampaign,
    ProviderTotalLatencyEvidence,
    SourceIdentity,
    StageTrace,
    SystemName,
    canonical_model_bytes,
    read_latency_campaign,
)
from tests.fixtures.phase_latency.factory import campaign, source, stage_trace
from tests.fixtures.phase_latency.factory import phase_exit_campaign


def test_campaign_round_trip_is_canonical_closed_and_byte_stable() -> None:
    original = campaign()
    encoded = canonical_model_bytes(original)
    rebuilt = read_latency_campaign(encoded)
    assert rebuilt == original
    assert canonical_model_bytes(rebuilt) == encoded

    value = original.model_dump(mode="json")
    value["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        LatencyCampaign.model_validate(value)


@pytest.mark.parametrize("field", ("size_bytes", "page_count"))
def test_source_identity_rejects_boolean_integer_aliases(field: str) -> None:
    value = source().model_dump(mode="json")
    value[field] = True
    with pytest.raises(ValidationError):
        SourceIdentity.model_validate(value)


def test_source_identity_requires_workspace_relative_path_and_matching_filename() -> (
    None
):
    value = source().model_dump(mode="json")
    value["path"] = "../private.pdf"
    with pytest.raises(ValidationError, match="workspace-relative"):
        SourceIdentity.model_validate(value)
    value = source().model_dump(mode="json")
    value["filename"] = "other.pdf"
    with pytest.raises(ValidationError, match="final path component"):
        SourceIdentity.model_validate(value)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("cache_disabled", False, "cache must be disabled"),
        ("cost_optimizer", True, "canonical profile"),
        ("credits_per_page", 9, "canonical profile"),
        ("tier", None, "canonical profile"),
        ("api_version", "v1", "canonical profile"),
    ],
)
def test_llamaparse_configuration_is_exact(
    field: str,
    replacement: object,
    message: str,
) -> None:
    value = campaign().attempts[1].configuration.model_dump(mode="json")
    value[field] = replacement
    with pytest.raises(ValidationError, match=message):
        ConfigurationIdentity.model_validate(value)


def test_provider_built_in_samples_and_cache_hits_are_unrepresentable() -> None:
    provider = campaign().attempts[1].model_dump(mode="json")
    provider["source_binding"] = "provider_built_in_sample"
    with pytest.raises(ValidationError):
        LatencyAttempt.model_validate(provider)
    provider = campaign().attempts[1].model_dump(mode="json")
    provider["cache_hit"] = True
    with pytest.raises(ValidationError, match="Cache hits|cache hits"):
        LatencyAttempt.model_validate(provider)


def test_provider_total_latency_binds_ui_artifact_timestamp_and_rounded_precision() -> (
    None
):
    minute = ProviderTotalLatencyEvidence(
        metric="provider_ui_total_latency",
        status="COMPLETED",
        job_id="pjb-minute14",
        display_value="1.4m",
        observed_at_utc="2026-08-08T12:00:00Z",
        retained_ui_evidence=ArtifactIdentity(
            path="tracker/evidence/llamaparse-minute14.png",
            sha256="a" * 64,
            size_bytes=10,
        ),
        normalized_display_ns=84_000_000_000,
        rounding_quantum_ns=6_000_000_000,
        lower_bound_inclusive_ns=81_000_000_000,
        upper_bound_exclusive_ns=87_000_000_000,
        rounding_rule="nearest_display_quantum_half_open",
    )
    assert minute.normalized_display_ns == 84_000_000_000
    assert minute.rounding_quantum_ns == 6_000_000_000

    provider = campaign().attempts[1].model_dump(mode="json")
    provider["provider_total_latency"]["normalized_display_ns"] += 1
    with pytest.raises(ValidationError, match="rounding bounds"):
        LatencyAttempt.model_validate(provider)

    provider = campaign().attempts[1].model_dump(mode="json")
    provider["provider_total_latency"]["observed_at_utc"] = "2026-08-08T17:30:00+05:30"
    with pytest.raises(ValidationError, match="must be UTC"):
        LatencyAttempt.model_validate(provider)

    provider = campaign().attempts[1].model_dump(mode="json")
    del provider["provider_total_latency"]["retained_ui_evidence"]
    with pytest.raises(ValidationError):
        LatencyAttempt.model_validate(provider)


def test_provider_total_latency_cannot_claim_precision_or_legacy_loose_fields() -> None:
    provider = campaign().attempts[1].model_dump(mode="json")
    provider["total_latency_ns"] += 1_000_000
    with pytest.raises(ValidationError, match="normalized UI display"):
        LatencyAttempt.model_validate(provider)

    provider = campaign().attempts[1].model_dump(mode="json")
    provider["provider_job_id"] = provider["provider_total_latency"]["job_id"]
    provider["provider_display_value"] = provider["provider_total_latency"][
        "display_value"
    ]
    with pytest.raises(ValidationError, match="Extra inputs"):
        LatencyAttempt.model_validate(provider)


def test_attempt_utc_chronology_is_retained_in_plan_order() -> None:
    value = campaign().model_dump(mode="json")
    value["attempts"][2]["started_at_utc"] = "2026-08-08T00:00:00Z"
    value["attempts"][2]["completed_at_utc"] = "2026-08-08T00:00:01Z"
    with pytest.raises(ValidationError, match="UTC chronology"):
        LatencyCampaign.model_validate(value)


def test_candidate_requires_local_trace_and_process_tree_while_provider_forbids_them() -> (
    None
):
    candidate = campaign().attempts[0].model_dump(mode="json")
    candidate["stage_trace"] = None
    with pytest.raises(ValidationError, match="complete-boundary trace"):
        LatencyAttempt.model_validate(candidate)

    provider = campaign().attempts[1].model_dump(mode="json")
    provider["process_tree"] = (
        campaign().attempts[0].process_tree.model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="cannot invent"):
        LatencyAttempt.model_validate(provider)


def test_campaign_rejects_source_or_semantic_request_drift_inside_one_pair() -> None:
    source_drift = campaign().model_dump(mode="json")
    source_drift["attempts"][1]["source"]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="one exact source"):
        LatencyCampaign.model_validate(source_drift)

    request_drift = campaign().model_dump(mode="json")
    request_drift["attempts"][1]["configuration"]["semantic_request_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="semantic request"):
        LatencyCampaign.model_validate(request_drift)


def test_campaign_rejects_missing_duplicate_reordered_or_reassigned_slots() -> None:
    original = campaign().model_dump(mode="json")

    missing = deepcopy(original)
    missing["attempts"].pop()
    with pytest.raises(ValidationError, match="at least 10|exactly one attempt"):
        LatencyCampaign.model_validate(missing)

    duplicate = deepcopy(original)
    duplicate["attempts"][1]["attempt_id"] = duplicate["attempts"][0]["attempt_id"]
    with pytest.raises(ValidationError, match="Attempt IDs|attempt IDs"):
        LatencyCampaign.model_validate(duplicate)

    reordered = deepcopy(original)
    reordered["attempts"][0], reordered["attempts"][1] = (
        reordered["attempts"][1],
        reordered["attempts"][0],
    )
    with pytest.raises(ValidationError, match="order"):
        LatencyCampaign.model_validate(reordered)

    reassigned = deepcopy(original)
    reassigned["attempts"][0]["pair_index"] = 2
    with pytest.raises(ValidationError, match="plan slot"):
        LatencyCampaign.model_validate(reassigned)


def test_stage_trace_rejects_unknown_fields_duplicate_ids_and_orphan_parents() -> None:
    value = stage_trace(20_000_000).model_dump(mode="json")
    value["spans"][0]["raw_text"] = "must never enter metrics"
    with pytest.raises(ValidationError, match="Extra inputs"):
        StageTrace.model_validate(value)

    value = stage_trace(20_000_000).model_dump(mode="json")
    value["spans"][2]["span_id"] = value["spans"][1]["span_id"]
    with pytest.raises(ValidationError, match="unique"):
        StageTrace.model_validate(value)

    value = stage_trace(20_000_000).model_dump(mode="json")
    value["spans"][1]["parent_span_id"] = "later-parent"
    with pytest.raises(ValidationError, match="precede"):
        StageTrace.model_validate(value)


def test_stage_status_and_authoritative_total_cannot_be_forged() -> None:
    value = stage_trace(20_000_000).model_dump(mode="json")
    value["authoritative_total_ns"] += 1
    with pytest.raises(ValidationError, match="root duration"):
        StageTrace.model_validate(value)

    value = stage_trace(20_000_000).model_dump(mode="json")
    value["spans"][1]["failure_code"] = "external_stage_error"
    with pytest.raises(ValidationError, match="successful stage"):
        StageTrace.model_validate(value)


def test_system_configuration_hash_is_derived_not_caller_asserted() -> None:
    value = campaign().attempts[0].configuration.model_dump(mode="json")
    value["bounded_concurrency"] = 2
    with pytest.raises(ValidationError, match="hash must be derived"):
        ConfigurationIdentity.model_validate(value)


def test_success_rejects_degraded_or_missing_required_child_stage() -> None:
    degraded = campaign().attempts[0].model_dump(mode="json")
    degraded["stage_trace"]["spans"][1]["status"] = "error"
    degraded["stage_trace"]["spans"][1]["failure_code"] = "external_stage_error"
    with pytest.raises(ValidationError, match="diagnostic stage was degraded"):
        LatencyAttempt.model_validate(degraded)

    missing = campaign().attempts[0].model_dump(mode="json")
    missing["stage_trace"]["spans"].pop(1)
    missing["stage_trace"]["attributed_top_level_union_ns"] -= 1_000_000
    missing["stage_trace"]["unattributed_remainder_ns"] += 1_000_000
    with pytest.raises(ValidationError, match="stage cardinality policy"):
        LatencyAttempt.model_validate(missing)


def test_failure_exception_classification_is_closed() -> None:
    value = campaign(
        failures={
            ("ny-timetable", 1, SystemName.CANDIDATE): AttemptStatus.ERROR,
        }
    ).attempts[0].model_dump(mode="json")
    value["failure"]["exception_type"] = "ArbitrarySecretDerivedClass"
    with pytest.raises(ValidationError):
        LatencyAttempt.model_validate(value)


def test_phase_exit_scope_is_exact_all_15_five_samples_and_1500_credits() -> None:
    retained = phase_exit_campaign()
    assert len(retained.plan) == 150
    assert len(retained.attempts) == 150
    assert retained.hosted_credits_used == 1_500
    assert sum(item.system.value == "llamaparse" for item in retained.attempts) == 75

    wrong_credit = retained.model_dump(mode="json")
    wrong_credit["hosted_credits_used"] = 1_499
    with pytest.raises(ValidationError, match="credits must be recomputed"):
        LatencyCampaign.model_validate(wrong_credit)

    source_drift = retained.model_dump(mode="json")
    source_drift["attempts"][0]["source"]["sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="registry|one exact source"):
        LatencyCampaign.model_validate(source_drift)


def test_global_semantics_and_provider_jobs_are_unique_across_cases() -> None:
    retained = phase_exit_campaign().model_dump(mode="json")
    target_case = retained["plan"][0]["case_id"]
    for attempt in retained["attempts"]:
        if attempt["case_id"] == target_case:
            attempt["configuration"]["semantic_request_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="global semantic"):
        LatencyCampaign.model_validate(retained)

    duplicate_job = phase_exit_campaign().model_dump(mode="json")
    provider_attempts = [
        item for item in duplicate_job["attempts"] if item["system"] == "llamaparse"
    ]
    provider_attempts[1]["provider_total_latency"]["job_id"] = (
        provider_attempts[0]["provider_total_latency"]["job_id"]
    )
    with pytest.raises(ValidationError, match="job IDs"):
        LatencyCampaign.model_validate(duplicate_job)
