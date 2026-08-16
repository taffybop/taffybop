from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from app.config import Settings
from app.services.visual_model_contracts import canonical_visual_model_json
from app.services.visual_model_hosted import (
    DeterministicHostedTransport,
    HostedBudget,
    HostedDispatchPlan,
    HostedPolicy,
    HostedVisualModelAdapter,
)
from tests.stories.phase_06.test_p06_us01_model_contract import (
    _identity,
    _observation,
    _request,
    _response,
)


_VENDOR = "deterministic-visual-adapter"
_MODEL = "fixture-model"
_REGION = "in-test-1"
_DATA_CLASS = "internal"
_RETENTION = "zero-retention"


def _policy(**updates: Any) -> HostedPolicy:
    values: dict[str, Any] = {
        "feature_enabled": True,
        "policy_approved": True,
        "data_approved": True,
        "minimization_approved": True,
        "retention_approved": True,
        "allowed_vendors": [_VENDOR],
        "allowed_models": [_MODEL],
        "allowed_processing_regions": [_REGION],
        "allowed_data_classes": [_DATA_CLASS],
        "allowed_retention_policies": [_RETENTION],
    }
    values.update(updates)
    return HostedPolicy(**values)


def _plan(**updates: Any) -> HostedDispatchPlan:
    values: dict[str, Any] = {
        "vendor": _VENDOR,
        "model": _MODEL,
        "processing_region": _REGION,
        "data_class": _DATA_CLASS,
        "retention_policy": _RETENTION,
        "redaction_decision": "not_required",
        "redaction_context_id": "redaction-context-1",
        "reserved_cost_microunits": 100,
        "max_output_tokens": 200,
        "timeout_ms": 1_000,
    }
    values.update(updates)
    return HostedDispatchPlan(**values)


def _budget(**updates: int) -> HostedBudget:
    values = {
        "max_requests": 3,
        "max_request_pixels": 8_000,
        "max_document_pixels": 24_000,
        "max_cost_microunits": 300,
        "max_output_tokens": 600,
        "max_timeout_ms": 3_000,
    }
    values.update(updates)
    return HostedBudget(**values)


def _approved_hosted_settings(**updates: Any) -> Settings:
    values: dict[str, Any] = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_hosted_enabled": True,
        "visual_models_hosted_policy_approved": True,
        "visual_models_hosted_data_approved": True,
        "visual_models_hosted_minimization_approved": True,
        "visual_models_hosted_retention_approved": True,
        "visual_models_hosted_vendor": _VENDOR,
        "visual_models_hosted_model": _MODEL,
        "visual_models_hosted_processing_region": _REGION,
        "visual_models_hosted_data_class": _DATA_CLASS,
        "visual_models_hosted_retention_policy": _RETENTION,
        "visual_models_hosted_redaction_decision": "not_required",
        "visual_models_hosted_redaction_context_id": "redaction-context-1",
        "visual_models_hosted_max_requests": 3,
        "visual_models_hosted_max_request_pixels": 8_000,
        "visual_models_hosted_max_document_pixels": 24_000,
        "visual_models_hosted_max_cost_microunits": 300,
        "visual_models_hosted_max_output_tokens": 600,
        "visual_models_hosted_max_timeout_ms": 3_000,
        "visual_models_hosted_reserved_cost_microunits": 100,
        "visual_models_hosted_request_max_output_tokens": 200,
        "visual_models_hosted_request_timeout_ms": 1_000,
        "visual_models_hosted_max_attempts": 1,
    }
    values.update(updates)
    return Settings(**values)


def _hosted_response() -> dict[str, Any]:
    identity = _identity(kind="test_double")
    observation = _observation(identity=identity)
    return _response(observation).model_dump(mode="json", exclude_none=True)


def _adapter(
    *,
    transport: Any | None = None,
    policy: HostedPolicy | None = None,
    budget: HostedBudget | None = None,
    plan: HostedDispatchPlan | None = None,
) -> tuple[HostedVisualModelAdapter, Any, HostedBudget]:
    selected_transport = transport or DeterministicHostedTransport(
        _hosted_response(),
        actual_cost_microunits=37,
        output_tokens=11,
        elapsed_ms=9,
    )
    selected_budget = budget or _budget()
    return (
        HostedVisualModelAdapter(
            transport=selected_transport,
            policy=policy or _policy(),
            budget=selected_budget,
            plan=plan or _plan(),
        ),
        selected_transport,
        selected_budget,
    )


def test_hosted_configuration_defaults_off_and_ignores_stale_auxiliary_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings()
    assert defaults.visual_models_hosted_enabled is False
    assert defaults.visual_models_hosted_policy_approved is False
    assert defaults.visual_models_hosted_data_approved is False
    assert defaults.visual_models_hosted_minimization_approved is False
    assert defaults.visual_models_hosted_retention_approved is False
    assert defaults.visual_models_hosted_vendor is None
    assert defaults.visual_models_hosted_max_requests == 0
    assert defaults.visual_models_hosted_max_cost_microunits == 0

    with pytest.raises(ValueError, match="HOSTED_ENABLED"):
        Settings(visual_models_hosted_enabled=True)

    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_ENABLED", "false")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_POLICY_APPROVED", "not-bool")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_VENDOR", "x" * 1_000)
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_MAX_REQUESTS", "not-an-int")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_MAX_ATTEMPTS", "99")

    rolled_back = Settings.from_env()

    assert rolled_back.visual_models_hosted_enabled is False
    assert rolled_back.visual_models_hosted_policy_approved is False
    assert rolled_back.visual_models_hosted_vendor is None
    assert rolled_back.visual_models_hosted_max_requests == 0
    assert rolled_back.visual_models_hosted_max_attempts == 1


def test_enabled_hosted_configuration_remains_denied_without_approvals_or_budget(
) -> None:
    settings = Settings(
        visual_structure_schema_enabled=True,
        visual_models_contract_enabled=True,
        visual_models_hosted_enabled=True,
    )
    policy = HostedPolicy(feature_enabled=settings.visual_models_hosted_enabled)
    budget = HostedBudget(
        max_requests=settings.visual_models_hosted_max_requests,
        max_request_pixels=settings.visual_models_hosted_max_request_pixels,
        max_document_pixels=settings.visual_models_hosted_max_document_pixels,
        max_cost_microunits=settings.visual_models_hosted_max_cost_microunits,
        max_output_tokens=settings.visual_models_hosted_max_output_tokens,
        max_timeout_ms=settings.visual_models_hosted_max_timeout_ms,
    )

    assert policy.policy_approved is False
    assert policy.data_approved is False
    assert policy.minimization_approved is False
    assert policy.retention_approved is False
    assert budget.snapshot().remaining_requests == 0
    assert budget.snapshot().remaining_cost_microunits == 0


def test_explicit_environment_constructs_exact_policy_budget_and_dispatch_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED": "true",
        "PARSER_VISUAL_MODELS_CONTRACT_ENABLED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_ENABLED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_POLICY_APPROVED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_DATA_APPROVED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_MINIMIZATION_APPROVED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_RETENTION_APPROVED": "true",
        "PARSER_VISUAL_MODELS_HOSTED_VENDOR": _VENDOR,
        "PARSER_VISUAL_MODELS_HOSTED_MODEL": _MODEL,
        "PARSER_VISUAL_MODELS_HOSTED_PROCESSING_REGION": _REGION,
        "PARSER_VISUAL_MODELS_HOSTED_DATA_CLASS": _DATA_CLASS,
        "PARSER_VISUAL_MODELS_HOSTED_RETENTION_POLICY": _RETENTION,
        "PARSER_VISUAL_MODELS_HOSTED_REDACTION_DECISION": "not_required",
        "PARSER_VISUAL_MODELS_HOSTED_REDACTION_CONTEXT_ID": (
            "redaction-context-1"
        ),
        "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUESTS": "3",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_REQUEST_PIXELS": "8000",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_DOCUMENT_PIXELS": "24000",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_COST_MICROUNITS": "300",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_OUTPUT_TOKENS": "600",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_TIMEOUT_MS": "3000",
        "PARSER_VISUAL_MODELS_HOSTED_RESERVED_COST_MICROUNITS": "100",
        "PARSER_VISUAL_MODELS_HOSTED_REQUEST_MAX_OUTPUT_TOKENS": "200",
        "PARSER_VISUAL_MODELS_HOSTED_REQUEST_TIMEOUT_MS": "1000",
        "PARSER_VISUAL_MODELS_HOSTED_MAX_ATTEMPTS": "1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()
    policy = HostedPolicy(
        feature_enabled=settings.visual_models_hosted_enabled,
        policy_approved=settings.visual_models_hosted_policy_approved,
        data_approved=settings.visual_models_hosted_data_approved,
        minimization_approved=settings.visual_models_hosted_minimization_approved,
        retention_approved=settings.visual_models_hosted_retention_approved,
        allowed_vendors=[settings.visual_models_hosted_vendor],
        allowed_models=[settings.visual_models_hosted_model],
        allowed_processing_regions=[
            settings.visual_models_hosted_processing_region
        ],
        allowed_data_classes=[settings.visual_models_hosted_data_class],
        allowed_retention_policies=[
            settings.visual_models_hosted_retention_policy
        ],
    )
    budget = HostedBudget(
        max_requests=settings.visual_models_hosted_max_requests,
        max_request_pixels=settings.visual_models_hosted_max_request_pixels,
        max_document_pixels=settings.visual_models_hosted_max_document_pixels,
        max_cost_microunits=settings.visual_models_hosted_max_cost_microunits,
        max_output_tokens=settings.visual_models_hosted_max_output_tokens,
        max_timeout_ms=settings.visual_models_hosted_max_timeout_ms,
    )
    plan = HostedDispatchPlan(
        vendor=settings.visual_models_hosted_vendor,
        model=settings.visual_models_hosted_model,
        processing_region=settings.visual_models_hosted_processing_region,
        data_class=settings.visual_models_hosted_data_class,
        retention_policy=settings.visual_models_hosted_retention_policy,
        redaction_decision=settings.visual_models_hosted_redaction_decision,
        redaction_context_id=settings.visual_models_hosted_redaction_context_id,
        reserved_cost_microunits=(
            settings.visual_models_hosted_reserved_cost_microunits
        ),
        max_output_tokens=(
            settings.visual_models_hosted_request_max_output_tokens
        ),
        timeout_ms=settings.visual_models_hosted_request_timeout_ms,
        max_attempts=settings.visual_models_hosted_max_attempts,
    )

    assert policy.denial_reason(plan) is None
    assert budget.snapshot().max_requests == 3
    assert budget.snapshot().max_document_pixels == 24_000
    assert plan.vendor == _VENDOR
    assert plan.max_attempts == 1


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"visual_models_hosted_policy_approved": True}, "HOSTED_VENDOR"),
        ({"visual_models_hosted_data_approved": True}, "DATA_CLASS"),
        ({"visual_models_hosted_retention_approved": True}, "RETENTION_POLICY"),
        (
            {"visual_models_hosted_minimization_approved": True},
            "minimization approval",
        ),
        (
            {"visual_models_hosted_redaction_context_id": "unsafe/context"},
            "REDACTION_CONTEXT_ID",
        ),
        ({"visual_models_hosted_max_attempts": 2}, "MAX_ATTEMPTS"),
    ],
)
def test_hosted_configuration_rejects_incomplete_or_non_exact_authority(
    updates: dict[str, Any],
    message: str,
) -> None:
    values: dict[str, Any] = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_hosted_enabled": True,
    }
    values.update(updates)

    with pytest.raises(ValueError, match=message):
        Settings(**values)


@pytest.mark.parametrize(
    "updates",
    [
        {"visual_models_hosted_max_requests": 0},
        {
            "visual_models_hosted_request_max_output_tokens": 601,
            "visual_models_hosted_max_output_tokens": 600,
        },
        {
            "visual_models_hosted_request_timeout_ms": 3_001,
            "visual_models_hosted_max_timeout_ms": 3_000,
        },
        {"visual_models_hosted_max_request_pixels": 16_000_001},
    ],
)
def test_fully_approved_hosted_configuration_requires_bounded_budget(
    updates: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="hosted|HOSTED"):
        _approved_hosted_settings(**updates)


@pytest.mark.parametrize(
    ("policy_updates", "plan_updates", "code"),
    [
        ({"feature_enabled": False}, {}, "feature_disabled"),
        ({"policy_approved": False}, {}, "policy_approval_missing"),
        ({"data_approved": False}, {}, "data_approval_missing"),
        (
            {"minimization_approved": False},
            {},
            "minimization_approval_missing",
        ),
        ({"retention_approved": False}, {}, "retention_approval_missing"),
        ({}, {"vendor": _VENDOR.upper()}, "vendor_denied"),
        ({}, {"model": _MODEL.upper()}, "model_denied"),
        ({}, {"processing_region": "us-test-1"}, "processing_region_denied"),
        ({}, {"data_class": "restricted"}, "data_class_denied"),
        ({}, {"retention_policy": "thirty-days"}, "retention_policy_denied"),
    ],
)
def test_incomplete_or_non_exact_policy_denies_with_zero_calls(
    policy_updates: dict[str, Any],
    plan_updates: dict[str, Any],
    code: str,
) -> None:
    adapter, transport, budget = _adapter(
        policy=_policy(**policy_updates),
        plan=_plan(**plan_updates),
    )
    before = budget.snapshot()

    result = adapter.invoke(_request())

    assert result.status == "fallback"
    assert result.failure is not None
    assert result.failure.code == code
    assert result.audit.transport_calls == 0
    assert transport.call_count == 0
    assert budget.snapshot() == before


def test_approved_call_is_minimized_validated_and_exactly_accounted() -> None:
    adapter, transport, budget = _adapter()

    result = adapter.invoke(_request())

    assert result.status == "accepted"
    assert result.failure is None
    assert result.contract_envelope is not None
    assert result.contract_envelope.status == "accepted"
    assert len(result.contract_envelope.response.observations) == 1
    assert transport.call_count == 1
    call = transport.calls[0]
    outbound = call.request.model_dump(mode="python", exclude_none=True)
    assert "document_sha256" not in outbound
    assert "public_item_id" not in outbound["region"]
    assert [record["id"] for record in outbound["evidence"]] == [
        "evidence-label",
        "evidence-region",
    ]
    for record in outbound["evidence"]:
        assert "text" not in record
        assert "source_object_ids" not in record
        assert "source_token_ids" not in record
    assert call.timeout_ms == 1_000
    assert call.max_output_tokens == 200
    snapshot = budget.snapshot()
    assert snapshot.used_requests == 1
    assert snapshot.used_document_pixels == 8_000
    assert snapshot.used_cost_microunits == 37
    assert snapshot.used_output_tokens == 11
    assert snapshot.used_timeout_ms == 9
    assert result.audit.budget_after == snapshot
    assert result.audit.minimization.omitted_metadata == [
        "document_sha256",
        "evidence_source_object_ids",
        "evidence_source_token_ids",
        "evidence_text",
        "public_item_id",
    ]


@pytest.mark.parametrize(
    ("budget_updates", "code", "dimension"),
    [
        ({"max_requests": 0}, "budget_requests_exhausted", "requests"),
        (
            {"max_request_pixels": 7_999},
            "budget_request_pixels_exhausted",
            "request_pixels",
        ),
        (
            {"max_document_pixels": 7_999},
            "budget_document_pixels_exhausted",
            "document_pixels",
        ),
        ({"max_cost_microunits": 99}, "budget_cost_exhausted", "cost"),
        ({"max_output_tokens": 199}, "budget_tokens_exhausted", "tokens"),
        ({"max_timeout_ms": 999}, "budget_timeout_exhausted", "timeout"),
    ],
)
def test_each_non_positive_or_insufficient_budget_denies_before_dispatch(
    budget_updates: dict[str, int],
    code: str,
    dimension: str,
) -> None:
    adapter, transport, budget = _adapter(budget=_budget(**budget_updates))
    before = budget.snapshot()

    result = adapter.invoke(_request())

    assert result.status == "fallback"
    assert result.failure is not None
    assert result.failure.code == code
    assert result.failure.budget_dimension == dimension
    assert transport.call_count == 0
    assert budget.snapshot() == before


def test_exhausted_document_budget_prevents_a_second_dispatch() -> None:
    budget = _budget(
        max_requests=1,
        max_document_pixels=8_000,
        max_cost_microunits=100,
        max_output_tokens=200,
        max_timeout_ms=1_000,
    )
    adapter, transport, _ = _adapter(budget=budget)

    first = adapter.invoke(_request())
    exhausted_snapshot = budget.snapshot()
    second = adapter.invoke(_request())

    assert first.status == "accepted"
    assert second.status == "fallback"
    assert second.failure is not None
    assert second.failure.code == "budget_requests_exhausted"
    assert transport.call_count == 1
    assert budget.snapshot() == exhausted_snapshot


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ("timeout", "timeout"),
        ("quota", "quota"),
        ("error", "transport_error"),
    ],
)
def test_transport_failures_are_typed_and_conservatively_accounted(
    outcome: str,
    code: str,
) -> None:
    transport = DeterministicHostedTransport(
        _hosted_response(),
        outcome=outcome,
    )
    adapter, transport, budget = _adapter(transport=transport)

    result = adapter.invoke(_request())

    assert result.status == "fallback"
    assert result.contract_envelope is None
    assert result.failure is not None
    assert result.failure.code == code
    assert transport.call_count == 1
    snapshot = budget.snapshot()
    assert snapshot.used_requests == 1
    assert snapshot.used_document_pixels == 8_000
    assert snapshot.used_cost_microunits == 100
    assert snapshot.used_output_tokens == 200
    assert snapshot.used_timeout_ms == 1_000


def test_malformed_and_unsafe_responses_never_escape_as_content() -> None:
    malformed_transport = DeterministicHostedTransport(
        {"payload": "untrusted model prose"},
        actual_cost_microunits=5,
        output_tokens=2,
        elapsed_ms=3,
    )
    malformed_adapter, _, _ = _adapter(transport=malformed_transport)
    unsafe = _hosted_response()
    unsafe["request_id"] = "other-request"
    unsafe_transport = DeterministicHostedTransport(
        unsafe,
        actual_cost_microunits=5,
        output_tokens=2,
        elapsed_ms=3,
    )
    unsafe_adapter, _, _ = _adapter(transport=unsafe_transport)

    malformed = malformed_adapter.invoke(_request())
    rejected = unsafe_adapter.invoke(_request())

    assert malformed.failure is not None
    assert malformed.failure.code == "malformed_response"
    assert rejected.failure is not None
    assert rejected.failure.code == "unsafe_response"
    assert malformed.contract_envelope is rejected.contract_envelope is None
    assert "untrusted model prose" not in canonical_visual_model_json(malformed)


def test_usage_above_the_reserved_bound_is_rejected_without_budget_overrun() -> None:
    transport = DeterministicHostedTransport(
        _hosted_response(),
        actual_cost_microunits=101,
        output_tokens=201,
        elapsed_ms=1_001,
    )
    adapter, transport, budget = _adapter(transport=transport)

    result = adapter.invoke(_request())

    assert result.failure is not None
    assert result.failure.code == "transport_usage_exceeded"
    assert transport.call_count == 1
    snapshot = budget.snapshot()
    assert snapshot.used_cost_microunits == 100
    assert snapshot.used_output_tokens == 200
    assert snapshot.used_timeout_ms == 1_000
    assert snapshot.remaining_cost_microunits >= 0
    assert snapshot.remaining_output_tokens >= 0
    assert snapshot.remaining_timeout_ms >= 0


def test_audit_is_secret_and_payload_safe() -> None:
    secret = "api-key-super-secret"
    request_payload = _request().model_dump(mode="python", exclude_none=True)
    crop = b"crop-with-api-key-super-secret"
    request_payload["crop"].update(
        {
            "data": crop,
            "byte_length": len(crop),
            "content_sha256": hashlib.sha256(crop).hexdigest(),
        }
    )
    request_payload["evidence"][0]["text"] = "api-key-super-secret"
    request = type(_request()).model_validate(request_payload)
    transport = DeterministicHostedTransport(
        _hosted_response(),
        actual_cost_microunits=1,
        output_tokens=1,
        elapsed_ms=1,
    )
    transport.api_key = secret
    adapter, _, _ = _adapter(
        transport=transport,
        plan=_plan(redaction_context_id=secret),
    )

    result = adapter.invoke(request)
    audit_json = canonical_visual_model_json(result.audit)

    assert result.status == "accepted"
    assert secret not in audit_json
    assert secret not in repr(result.audit)
    assert request.document_sha256 not in audit_json
    assert result.audit.minimization.payload_logged is False
    assert result.audit.minimization.credentials_logged is False
    assert adapter.audit_events == (result.audit,)


def test_approved_mock_output_and_audit_are_deterministic() -> None:
    first_adapter, _, _ = _adapter()
    second_adapter, _, _ = _adapter()

    first = first_adapter.invoke(_request())
    second = second_adapter.invoke(deepcopy(_request()))

    assert canonical_visual_model_json(first) == canonical_visual_model_json(second)
    assert first.audit.event_id == second.audit.event_id
