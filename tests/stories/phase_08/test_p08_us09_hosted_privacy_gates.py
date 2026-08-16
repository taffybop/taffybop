"""P08-US09 release-first hosted privacy and no-egress policy gates."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings
from app.services.input_documents import InputKind
from app.services.artifact_manifest import (
    ArtifactKind,
    ArtifactLocatorKind,
    ArtifactManifest,
    ManifestVerification,
    ReleaseArtifactProfile,
    ReleaseArtifactRequirement,
    path_artifact,
    verify_release_manifest,
)
from app.services.hosted_policy import (
    HostedPolicyReason,
    HostedReleaseGateway,
    HostedReleasePolicy,
    HostedReleasePolicyError,
    HostedRequestGovernance,
    TrustedLocalHostedFallback,
    trusted_local_hosted_fallback,
)
from app.services.telemetry import InMemoryTelemetryExporter, TelemetryClient
from app.services.visual_model_contracts import (
    VisualModelConfidenceDimensions,
    VisualModelIdentity,
    VisualModelObservation,
    VisualModelResponse,
)
from app.services.visual_model_hosted import (
    DeterministicHostedTransport,
    HostedBudget,
    HostedDispatchPlan,
    HostedPolicy,
    HostedTransportReply,
)
from app.services.visual_model_local import (
    DeterministicLocalVisualModelLoader,
    DeterministicLocalVisualModelRuntime,
    LocalVisualModelAdapter,
)
from app.services.visual_models import (
    VisualModelDependencies,
    apply_optional_visual_models,
)
from app.services.visual_semantics import apply_visual_semantics
from tests.stories.phase_05.test_p05_us01_visual_schema import _item, _payload
from tests.stories.phase_06.test_p06_us01_model_contract import _request
from tests.stories.phase_06.test_p06_us02_local_adapter import (
    _local_response,
    _settings as _local_settings,
    _write_artifact as _write_local_artifact,
)
from tests.stories.phase_06.test_p06_us06_merge_fallback import (
    _crop_provider,
    _phase06_settings,
)


VENDOR = "approved-test-provider"
MODEL = "grounded-fixture-model"
MODEL_VERSION = "fixture-v1"
REGION = "in-test-1"
DATA_CLASS = "internal"
RETENTION = "zero-retention"
EGRESS = "https://mock-provider.invalid/v1/visual"
MODEL_SOURCE = "https://models.example.invalid/grounded-fixture/fixture-v1"
MODEL_LICENSE = "Apache-2.0"
VALID_PDF = b"%PDF-1.7\n% hosted-policy public-flow fixture\n"


class _DynamicManifestTransport:
    """Build a grounded response from the already minimized request."""

    egress_destination = EGRESS

    def __init__(self, manifest: ArtifactManifest) -> None:
        self.manifest = manifest
        self.calls: list[Any] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, call: Any) -> HostedTransportReply:
        self.calls.append(call)
        artifact = self.manifest.artifact("model.hosted-grounded")
        assert artifact is not None
        identity = VisualModelIdentity(
            adapter_kind="test_double",
            adapter_name=VENDOR,
            adapter_version="1.0.0",
            model_name=MODEL,
            model_version=MODEL_VERSION,
            prompt_version="grounded-v1",
            response_schema_version="1.0",
            artifact_sha256=artifact.sha256,
            artifact_source=artifact.source,
            license_id=artifact.license_record,
        )
        label = next(
            value
            for value in call.request.evidence
            if value.kind == "label"
            and value.source_origin == "ocr"
            and value.page_bbox is not None
        )
        observation = VisualModelObservation(
            id="observation-hosted-dynamic",
            operation="add",
            observation_type="visual_identification",
            origin="model_visual_identification",
            explicitness="derived",
            method="explicit_text",
            text="2024",
            region_id=call.request.region.id,
            page_index=call.request.region.page_index,
            page_bbox=label.page_bbox,
            evidence_ids=[label.id],
            identity=identity,
            confidence=VisualModelConfidenceDimensions(model=0.8),
        )
        response = VisualModelResponse(
            schema_version="1.0",
            request_id=call.request.request_id,
            identity=identity,
            observations=[observation],
        )
        return HostedTransportReply(
            response=response.model_dump(mode="json", exclude_none=True),
            actual_cost_microunits=1,
            output_tokens=1,
            elapsed_ms=1,
        )


def _manifest(tmp_path: Path, *, release_id: str = "candidate-1") -> ArtifactManifest:
    model_path = tmp_path / "artifacts" / "hosted-model.identity"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(
        f"{VENDOR}\n{MODEL}\n{MODEL_VERSION}\n",
        encoding="utf-8",
    )
    artifact = path_artifact(
        root=tmp_path,
        artifact_id="model.hosted-grounded",
        kind=ArtifactKind.MODEL,
        capability="visual_models",
        version=MODEL_VERSION,
        source=MODEL_SOURCE,
        license_record=MODEL_LICENSE,
        locator_kind=ArtifactLocatorKind.FILE,
        locator="artifacts/hosted-model.identity",
        required=True,
    )
    return ArtifactManifest.create(release_id=release_id, artifacts=(artifact,))


def _manifest_profile(manifest: ArtifactManifest) -> ReleaseArtifactProfile:
    artifact = manifest.artifact("model.hosted-grounded")
    assert artifact is not None
    return ReleaseArtifactProfile(
        profile_id="hosted-test-profile-v1",
        requirements=(
            ReleaseArtifactRequirement(
                artifact_id=artifact.artifact_id,
                kind=artifact.kind,
                capability=artifact.capability,
                required=True,
                version=artifact.version,
                source=artifact.source,
                license_record=artifact.license_record,
                locator_kind=artifact.locator_kind,
                locator=artifact.locator,
            ),
        ),
    )


def _manifest_verification(
    root: Path,
    manifest: ArtifactManifest,
    *,
    profile: ReleaseArtifactProfile | None = None,
) -> ManifestVerification:
    selected_profile = profile or _manifest_profile(manifest)
    return verify_release_manifest(
        manifest,
        root=root,
        purpose="release_startup",
        profile=selected_profile,
    )


def _policy(manifest: ArtifactManifest, **updates: Any) -> HostedReleasePolicy:
    artifact = manifest.artifact("model.hosted-grounded")
    assert artifact is not None and artifact.sha256 is not None
    values: dict[str, Any] = {
        "policy_id": "hosted-release-policy-v1",
        "approved": True,
        "manifest_sha256": manifest.manifest_sha256,
        "model_artifact_id": artifact.artifact_id,
        "model_artifact_sha256": artifact.sha256,
        "vendor": VENDOR,
        "model": MODEL,
        "model_version": MODEL_VERSION,
        "allowed_data_classes": (DATA_CLASS,),
        "allowed_processing_regions": (REGION,),
        "allowed_residency_regions": (REGION,),
        "allowed_retention_policies": (RETENTION,),
        "allowed_egress_destinations": (EGRESS,),
        "allowed_redaction_decisions": ("not_required",),
        "subprocessor_approved": True,
        "allow_cache": False,
        "allow_whole_document": False,
        "require_processing_in_residency": True,
    }
    values.update(updates)
    return HostedReleasePolicy(**values)


def _governance(**updates: Any) -> HostedRequestGovernance:
    values: dict[str, Any] = {
        "tenant_permission": True,
        "residency_region": REGION,
        "egress_destination": EGRESS,
        "request_scope": "approved_region_only",
        "cache_requested": False,
    }
    values.update(updates)
    return HostedRequestGovernance(**values)


def _phase06_policy(**updates: Any) -> HostedPolicy:
    values: dict[str, Any] = {
        "feature_enabled": True,
        "policy_approved": True,
        "data_approved": True,
        "minimization_approved": True,
        "retention_approved": True,
        "allowed_vendors": [VENDOR],
        "allowed_models": [MODEL],
        "allowed_processing_regions": [REGION],
        "allowed_data_classes": [DATA_CLASS],
        "allowed_retention_policies": [RETENTION],
    }
    values.update(updates)
    return HostedPolicy(**values)


def _plan(**updates: Any) -> HostedDispatchPlan:
    values: dict[str, Any] = {
        "vendor": VENDOR,
        "model": MODEL,
        "processing_region": REGION,
        "data_class": DATA_CLASS,
        "retention_policy": RETENTION,
        "redaction_decision": "not_required",
        "redaction_context_id": "approved-redaction-context",
        "reserved_cost_microunits": 100,
        "max_output_tokens": 200,
        "timeout_ms": 1_000,
    }
    values.update(updates)
    return HostedDispatchPlan(**values)


def _budget() -> HostedBudget:
    return HostedBudget(
        max_requests=2,
        max_request_pixels=8_000,
        max_document_pixels=16_000,
        max_cost_microunits=200,
        max_output_tokens=400,
        max_timeout_ms=2_000,
    )


def _response(manifest: ArtifactManifest, **updates: Any) -> dict[str, Any]:
    artifact = manifest.artifact("model.hosted-grounded")
    assert artifact is not None
    values: dict[str, Any] = {
        "adapter_kind": "test_double",
        "adapter_name": VENDOR,
        "adapter_version": "1.0.0",
        "model_name": MODEL,
        "model_version": MODEL_VERSION,
        "prompt_version": "grounded-v1",
        "response_schema_version": "1.0",
        "artifact_sha256": artifact.sha256,
        "artifact_source": artifact.source,
        "license_id": artifact.license_record,
    }
    values.update(updates)
    identity = VisualModelIdentity(**values)
    observation = VisualModelObservation(
        id="observation-hosted-policy",
        operation="add",
        observation_type="generated_description",
        origin="model_generated_description",
        explicitness="generated",
        method="generated_description",
        text="Approved test-double observation",
        region_id="region-1",
        page_index=1,
        evidence_ids=["evidence-region"],
        identity=identity,
        confidence=VisualModelConfidenceDimensions(model=0.8),
    )
    return VisualModelResponse(
        schema_version="1.0",
        request_id="request-1",
        identity=identity,
        observations=[observation],
    ).model_dump(mode="json", exclude_none=True)


def _gateway(
    tmp_path: Path,
    *,
    hosted_enabled: bool = True,
    manifest: ArtifactManifest | None = None,
    policy: HostedReleasePolicy | dict[str, Any] | None | object = ...,
    governance: HostedRequestGovernance | dict[str, Any] | None = None,
    plan: HostedDispatchPlan | None = None,
    phase06_policy: HostedPolicy | None = None,
    transport: DeterministicHostedTransport | None = None,
    manifest_verification: ManifestVerification | None | object = ...,
    manifest_profile: ReleaseArtifactProfile | None = None,
    manifest_root: Path | None = None,
    telemetry: Any | None = None,
    max_audit_records: int = 128,
) -> tuple[
    HostedReleaseGateway,
    DeterministicHostedTransport,
    TrustedLocalHostedFallback,
    ArtifactManifest,
]:
    selected_manifest = manifest or _manifest(tmp_path)
    selected_profile = manifest_profile or _manifest_profile(selected_manifest)
    selected_verification = (
        _manifest_verification(
            manifest_root or tmp_path,
            selected_manifest,
            profile=selected_profile,
        )
        if manifest_verification is ...
        else manifest_verification
    )
    selected_policy = (
        _policy(selected_manifest) if policy is ... else policy
    )
    selected_transport = transport or DeterministicHostedTransport(
        _response(selected_manifest),
        actual_cost_microunits=10,
        output_tokens=5,
        elapsed_ms=7,
    )
    if not hasattr(selected_transport, "egress_destination"):
        selected_transport.egress_destination = EGRESS
    local_artifact_path, local_digest = _write_local_artifact(tmp_path)
    local_runtime = DeterministicLocalVisualModelRuntime(
        _local_response(local_digest)
    )
    selected_local = trusted_local_hosted_fallback(
        LocalVisualModelAdapter(
            _local_settings(local_artifact_path, local_digest),
            DeterministicLocalVisualModelLoader(local_runtime),
        )
    )
    return (
        HostedReleaseGateway(
            hosted_enabled=hosted_enabled,
            manifest=selected_manifest,
            manifest_verification=selected_verification,  # type: ignore[arg-type]
            manifest_profile_id=selected_profile.profile_id,
            policy=selected_policy,  # type: ignore[arg-type]
            governance=_governance() if governance is None else governance,
            transport=selected_transport,
            phase06_policy=phase06_policy or _phase06_policy(),
            budget=_budget(),
            plan=plan or _plan(),
            local_fallback=selected_local,
            telemetry=telemetry,
            max_audit_records=max_audit_records,
        ),
        selected_transport,
        selected_local,
        selected_manifest,
    )


def _approved_hosted_settings(*, hosted_enabled: bool = True) -> Settings:
    return _phase06_settings(
        visual_models_hosted_enabled=hosted_enabled,
        visual_models_hosted_policy_approved=True,
        visual_models_hosted_data_approved=True,
        visual_models_hosted_minimization_approved=True,
        visual_models_hosted_retention_approved=True,
        visual_models_hosted_vendor=VENDOR,
        visual_models_hosted_model=MODEL,
        visual_models_hosted_processing_region=REGION,
        visual_models_hosted_data_class=DATA_CLASS,
        visual_models_hosted_retention_policy=RETENTION,
        visual_models_hosted_redaction_decision="not_required",
        visual_models_hosted_redaction_context_id="approved-redaction-context",
        visual_models_hosted_max_requests=2,
        visual_models_hosted_max_request_pixels=8_000,
        visual_models_hosted_max_document_pixels=16_000,
        visual_models_hosted_max_cost_microunits=200,
        visual_models_hosted_max_output_tokens=400,
        visual_models_hosted_max_timeout_ms=2_000,
        visual_models_hosted_reserved_cost_microunits=100,
        visual_models_hosted_request_max_output_tokens=200,
        visual_models_hosted_request_timeout_ms=1_000,
        visual_models_routing_preference="hosted_only",
    )


def _deny_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    original_socket = socket.socket

    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("live external egress is prohibited")

    def guarded_socket(
        family: int = socket.AF_INET,
        *args: object,
        **kwargs: object,
    ) -> Any:
        # AnyIO's in-process TestClient uses an AF_UNIX socket pair for its
        # local event loop.  It is not external egress and remains permitted.
        if family in {socket.AF_INET, socket.AF_INET6}:
            denied()
        return original_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", guarded_socket)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


@pytest.fixture(autouse=True)
def _zero_live_external_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every US09 test fails immediately if any live socket path is attempted."""

    _deny_sockets(monkeypatch)


def test_missing_policy_denies_before_transport_and_uses_local_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    gateway, transport, local, _manifest_value = _gateway(tmp_path, policy=None)

    result = gateway.invoke(_request())

    assert result.status == "local_fallback"
    assert result.decision.reason is HostedPolicyReason.POLICY_MISSING
    assert result.transport_calls == 0
    assert result.fallback_invoked is True
    assert transport.call_count == 0
    assert local.invoke_count == 1
    assert result.contract_envelope is not None
    assert result.contract_envelope.status == "accepted"


def test_approved_policy_reaches_only_minimized_mock_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    gateway, transport, local, manifest = _gateway(tmp_path)

    result = gateway.invoke(_request())

    assert result.status == "hosted"
    assert result.decision.reason is HostedPolicyReason.APPROVED
    assert result.transport_calls == 1
    assert result.fallback_invoked is False
    assert transport.call_count == 1
    assert local.invoke_count == 0
    call = transport.calls[0]
    outbound = call.request.model_dump(mode="python", exclude_none=True)
    assert "document_sha256" not in outbound
    assert "public_item_id" not in outbound["region"]
    assert all("text" not in record for record in outbound["evidence"])
    assert all("source_object_ids" not in record for record in outbound["evidence"])
    assert call.processing_region == REGION
    assert call.retention_policy == RETENTION
    assert result.decision.manifest_sha256 == manifest.manifest_sha256


@pytest.mark.parametrize(
    ("policy_updates", "governance_updates", "plan_updates", "reason"),
    [
        ({}, {}, {"processing_region": "in-test-2"}, "processing_region_mismatch"),
        ({}, {}, {"retention_policy": "thirty-days"}, "retention_policy_mismatch"),
        ({}, {}, {"data_class": "restricted"}, "data_class_mismatch"),
        ({}, {"residency_region": "in-test-2"}, {}, "residency_region_mismatch"),
        ({}, {"egress_destination": "https://other.invalid/v1"}, {}, "egress_destination_mismatch"),
        ({"subprocessor_approved": False}, {}, {}, "subprocessor_not_approved"),
        ({}, {"cache_requested": True}, {}, "cache_not_allowed"),
        ({}, {"request_scope": "whole_document"}, {}, "whole_document_not_allowed"),
    ],
)
def test_policy_mismatches_deny_with_zero_transport_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy_updates: dict[str, Any],
    governance_updates: dict[str, Any],
    plan_updates: dict[str, Any],
    reason: str,
) -> None:
    _deny_sockets(monkeypatch)
    manifest = _manifest(tmp_path)
    gateway, transport, local, _ = _gateway(
        tmp_path,
        manifest=manifest,
        policy=_policy(manifest, **policy_updates),
        governance=_governance(**governance_updates),
        plan=_plan(**plan_updates),
    )

    result = gateway.invoke(_request())

    assert result.status == "local_fallback"
    assert result.decision.reason.value == reason
    assert result.transport_calls == 0
    assert transport.call_count == 0
    assert local.invoke_count == 1


def test_disabled_hosted_behavior_denies_even_with_an_approved_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    gateway, transport, local, _ = _gateway(tmp_path, hosted_enabled=False)

    result = gateway.invoke(_request())

    assert gateway.is_available() is False
    assert result.decision.reason is HostedPolicyReason.HOSTED_DISABLED
    assert transport.call_count == result.transport_calls == 0
    assert local.invoke_count == 1


def test_transport_must_declare_the_exact_approved_egress_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    manifest = _manifest(tmp_path)
    transport = DeterministicHostedTransport(_response(manifest))
    transport.egress_destination = "https://other.invalid/v1/visual"
    gateway, transport, local, _ = _gateway(
        tmp_path,
        manifest=manifest,
        transport=transport,
    )

    result = gateway.invoke(_request())

    assert result.decision.reason is HostedPolicyReason.EGRESS_DESTINATION_MISMATCH
    assert result.transport_calls == transport.call_count == 0
    assert local.invoke_count == 1


def test_manifest_and_model_artifact_bindings_deny_on_any_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    manifest = _manifest(tmp_path)
    other = _manifest(tmp_path / "other", release_id="other-release")
    wrong_manifest, transport_a, local_a, _ = _gateway(
        tmp_path,
        manifest=other,
        policy=_policy(manifest),
    )
    wrong_artifact, transport_b, local_b, _ = _gateway(
        tmp_path,
        manifest=manifest,
        policy=_policy(manifest, model_artifact_sha256="f" * 64),
    )

    digest_result = wrong_manifest.invoke(_request())
    artifact_result = wrong_artifact.invoke(_request())

    assert digest_result.decision.reason is HostedPolicyReason.MANIFEST_DIGEST_MISMATCH
    assert artifact_result.decision.reason is HostedPolicyReason.ARTIFACT_BINDING_MISMATCH
    assert transport_a.call_count == transport_b.call_count == 0
    assert local_a.invoke_count == local_b.invoke_count == 1


def test_hosted_response_must_resolve_to_the_exact_manifest_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    manifest = _manifest(tmp_path)
    transport = DeterministicHostedTransport(
        _response(manifest, artifact_sha256="e" * 64),
        actual_cost_microunits=1,
        output_tokens=1,
        elapsed_ms=1,
    )
    gateway, transport, local, _ = _gateway(
        tmp_path,
        manifest=manifest,
        transport=transport,
    )

    result = gateway.invoke(_request())

    assert transport.call_count == result.transport_calls == 1
    assert result.status == "local_fallback"
    assert result.decision.reason is HostedPolicyReason.RESPONSE_ARTIFACT_MISMATCH
    assert result.hosted_failure_code == "response_artifact_mismatch"
    assert local.invoke_count == 1


def test_malformed_or_phase06_denied_policy_never_reaches_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _deny_sockets(monkeypatch)
    malformed, transport_a, local_a, _ = _gateway(
        tmp_path,
        policy={"approved": True},
    )
    phase06_denied, transport_b, local_b, _ = _gateway(
        tmp_path / "phase06",
        phase06_policy=_phase06_policy(policy_approved=False),
    )

    malformed_result = malformed.invoke(_request())
    denied_result = phase06_denied.invoke(_request())

    assert malformed_result.decision.reason is HostedPolicyReason.POLICY_MALFORMED
    assert denied_result.decision.reason is HostedPolicyReason.PHASE06_POLICY_DENIED
    assert transport_a.call_count == transport_b.call_count == 0
    assert local_a.invoke_count == local_b.invoke_count == 1


def test_policy_decision_audit_and_telemetry_exclude_payloads_and_secrets(
    tmp_path: Path,
) -> None:
    secret = "hosted-api-key-secret-canary"
    exporter = InMemoryTelemetryExporter()
    telemetry = TelemetryClient(enabled=True, exporter=exporter)
    gateway, transport, _local, _ = _gateway(tmp_path, policy=None, telemetry=telemetry)
    transport.api_key = secret
    request_payload = _request().model_dump(mode="python")
    request_payload["evidence"][0]["text"] = secret
    request = type(_request()).model_validate(request_payload, strict=True)

    result = gateway.invoke(request)
    assert telemetry.flush(1.0) is True
    safe = json.dumps(
        {
            "result": result.safe_record(),
            "audit": gateway.audit_records,
            "telemetry": [event.canonical_bytes().decode("utf-8") for event in exporter.events],
        },
        sort_keys=True,
    )

    assert secret not in safe
    assert request.document_sha256 not in safe
    assert EGRESS not in safe
    assert request.request_id not in safe
    assert set(result.safe_record()) == {
        "status",
        "decision",
        "transport_calls",
        "fallback_invoked",
        "hosted_failure_code",
    }
    assert transport.call_count == 0
    telemetry.close()


def test_policy_and_audit_bounds_reject_credentials_and_unbounded_records(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    with pytest.raises(HostedReleasePolicyError, match="credential-free"):
        _policy(
            manifest,
            allowed_egress_destinations=(
                "https://api-key:secret@mock-provider.invalid/v1",
            ),
        )
    with pytest.raises(HostedReleasePolicyError, match="audit bound"):
        gateway, *_ = _gateway(tmp_path, max_audit_records=0)  # type: ignore[call-arg]


def test_existing_flags_remain_default_off_and_kill_switch_keeps_hosted_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = Settings()
    assert defaults.visual_models_hosted_enabled is False
    assert defaults.visual_models_hosted_policy_approved is False
    assert defaults.visual_models_hosted_max_requests == 0

    monkeypatch.setenv("PARSER_SHIPPING_KILL_SWITCH", "true")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_HOSTED_POLICY_APPROVED", "true")
    rolled_back = Settings.from_env()

    assert rolled_back.visual_models_hosted_enabled is False
    assert rolled_back.visual_models_hosted_max_requests == 0


class _StructuralGatewaySpoof:
    """Marker-shaped adapter that must never gain hosted authority."""

    kind = "hosted"
    release_policy_enforced = True

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def invoke(self, _request_value: Any) -> None:
        self.calls += 1


class _LocalKindSpoof:
    kind = "local"

    def invoke(self, _request_value: Any) -> None:
        return None


def test_structural_release_gateway_marker_cannot_bypass_concrete_injection_gate(
    tmp_path: Path,
) -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    spoof = _StructuralGatewaySpoof()

    result = apply_optional_visual_models(
        baseline,
        _approved_hosted_settings(),
        source_document_bytes=b"unused-source",
        input_kind=InputKind.PDF,
        dependencies=VisualModelDependencies(
            adapters={"hosted": spoof},  # type: ignore[dict-item]
            crop_provider=_crop_provider,
            deterministic_test_double=False,
        ),
    )

    assert result == baseline
    assert spoof.calls == 0


def test_deterministic_test_double_cannot_override_hosted_flag_off(
    tmp_path: Path,
) -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    gateway, transport, local, _ = _gateway(tmp_path)

    result = apply_optional_visual_models(
        baseline,
        _approved_hosted_settings(hosted_enabled=False),
        source_document_bytes=b"unused-source",
        input_kind=InputKind.PDF,
        dependencies=VisualModelDependencies(
            adapters={"hosted": gateway},
            crop_provider=_crop_provider,
            deterministic_test_double=True,
        ),
    )

    assert result == baseline
    assert transport.call_count == 0
    assert local.invoke_count == 0


def test_hosted_or_marker_only_adapter_cannot_occupy_local_fallback_slot(
    tmp_path: Path,
) -> None:
    from app.services.visual_model_hosted import HostedVisualModelAdapter

    manifest = _manifest(tmp_path)
    profile = _manifest_profile(manifest)
    verification = _manifest_verification(tmp_path, manifest, profile=profile)
    transport = DeterministicHostedTransport(_response(manifest))
    transport.egress_destination = EGRESS
    raw_hosted = HostedVisualModelAdapter(
        transport=transport,
        policy=_phase06_policy(),
        budget=_budget(),
        plan=_plan(),
    )

    with pytest.raises(HostedReleasePolicyError, match="factory-issued"):
        HostedReleaseGateway(
            hosted_enabled=True,
            manifest=manifest,
            manifest_verification=verification,
            manifest_profile_id=profile.profile_id,
            policy=_policy(manifest),
            governance=_governance(),
            transport=transport,
            phase06_policy=_phase06_policy(),
            budget=_budget(),
            plan=_plan(),
            local_fallback=raw_hosted,  # type: ignore[arg-type]
        )
    with pytest.raises(HostedReleasePolicyError, match="factory-issued"):
        HostedReleaseGateway(
            hosted_enabled=True,
            manifest=manifest,
            manifest_verification=verification,
            manifest_profile_id=profile.profile_id,
            policy=_policy(manifest),
            governance=_governance(),
            transport=transport,
            phase06_policy=_phase06_policy(),
            budget=_budget(),
            plan=_plan(),
            local_fallback=_StructuralGatewaySpoof(),  # type: ignore[arg-type]
        )
    with pytest.raises(HostedReleasePolicyError, match="concrete local adapter"):
        trusted_local_hosted_fallback(_LocalKindSpoof())  # type: ignore[arg-type]
    assert transport.call_count == 0


def test_unverified_profile_or_drifted_artifact_denies_before_transport(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    profile = _manifest_profile(manifest)
    accepted = _manifest_verification(tmp_path, manifest, profile=profile)
    assert accepted.accepted is True
    forged = ManifestVerification(
        purpose=accepted.purpose,
        release_id=accepted.release_id,
        manifest_sha256=accepted.manifest_sha256,
        accepted=True,
        checks=accepted.checks,
        disabled_capabilities=accepted.disabled_capabilities,
        blocking_reasons=(),
        profile_id=accepted.profile_id,
    )

    missing, transport_a, local_a, _ = _gateway(
        tmp_path,
        manifest=manifest,
        manifest_profile=profile,
        manifest_verification=None,
    )
    wrong_profile, transport_b, local_b, _ = _gateway(
        tmp_path,
        manifest=manifest,
        manifest_profile=profile,
        manifest_verification=replace(accepted, profile_id="other-profile-v1"),
    )
    forged_gateway, transport_c, local_c, _ = _gateway(
        tmp_path,
        manifest=manifest,
        manifest_profile=profile,
        manifest_verification=forged,
    )
    (tmp_path / "artifacts" / "hosted-model.identity").write_text(
        "drifted-model-bytes\n",
        encoding="utf-8",
    )
    drifted_report = _manifest_verification(tmp_path, manifest, profile=profile)
    assert drifted_report.accepted is False
    drifted, transport_d, local_d, _ = _gateway(
        tmp_path,
        manifest=manifest,
        manifest_profile=profile,
        manifest_verification=drifted_report,
    )

    results = [
        missing.invoke(_request()),
        wrong_profile.invoke(_request()),
        forged_gateway.invoke(_request()),
        drifted.invoke(_request()),
    ]

    assert all(
        result.decision.reason
        is HostedPolicyReason.MANIFEST_VERIFICATION_INVALID
        for result in results
    )
    assert [
        transport_a.call_count,
        transport_b.call_count,
        transport_c.call_count,
        transport_d.call_count,
    ] == [
        0,
        0,
        0,
        0,
    ]
    assert [
        local_a.invoke_count,
        local_b.invoke_count,
        local_c.invoke_count,
        local_d.invoke_count,
    ] == [1, 1, 1, 1]


def test_crop_geometry_mismatch_denies_before_transport(tmp_path: Path) -> None:
    gateway, transport, local, _ = _gateway(tmp_path)
    request_payload = _request().model_dump(mode="python")
    request_payload["crop"]["width"] = 400
    request = type(_request()).model_validate(request_payload, strict=True)

    result = gateway.invoke(request)

    assert result.status == "local_fallback"
    assert result.decision.reason is HostedPolicyReason.CROP_REGION_MISMATCH
    assert result.transport_calls == transport.call_count == 0
    assert local.invoke_count == 1


def test_production_orchestrator_rejects_raw_phase06_hosted_adapter(
    tmp_path: Path,
) -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    manifest = _manifest(tmp_path)
    transport = DeterministicHostedTransport(
        _response(manifest),
        actual_cost_microunits=1,
        output_tokens=1,
        elapsed_ms=1,
    )
    from app.services.visual_model_hosted import HostedVisualModelAdapter

    raw = HostedVisualModelAdapter(
        transport=transport,
        policy=_phase06_policy(),
        budget=_budget(),
        plan=_plan(),
    )
    settings = _phase06_settings(
        visual_models_hosted_enabled=True,
        visual_models_hosted_policy_approved=True,
        visual_models_hosted_data_approved=True,
        visual_models_hosted_minimization_approved=True,
        visual_models_hosted_retention_approved=True,
        visual_models_hosted_vendor=VENDOR,
        visual_models_hosted_model=MODEL,
        visual_models_hosted_processing_region=REGION,
        visual_models_hosted_data_class=DATA_CLASS,
        visual_models_hosted_retention_policy=RETENTION,
        visual_models_hosted_redaction_decision="not_required",
        visual_models_hosted_redaction_context_id="approved-redaction-context",
        visual_models_hosted_max_requests=2,
        visual_models_hosted_max_request_pixels=8_000,
        visual_models_hosted_max_document_pixels=16_000,
        visual_models_hosted_max_cost_microunits=200,
        visual_models_hosted_max_output_tokens=400,
        visual_models_hosted_max_timeout_ms=2_000,
        visual_models_hosted_reserved_cost_microunits=100,
        visual_models_hosted_request_max_output_tokens=200,
        visual_models_hosted_request_timeout_ms=1_000,
        visual_models_routing_preference="hosted_only",
    )
    dependencies = VisualModelDependencies(
        adapters={"hosted": raw},
        crop_provider=_crop_provider,
        deterministic_test_double=False,
    )

    result = apply_optional_visual_models(
        baseline,
        settings,
        source_document_bytes=b"unused-source",
        input_kind=InputKind.PDF,
        dependencies=dependencies,
    )

    assert result == baseline
    assert transport.call_count == 0


def test_production_orchestrator_admits_manifest_bound_gateway(
    tmp_path: Path,
) -> None:
    baseline = apply_visual_semantics(
        _payload(_item("chart", "chart-1", x=10.0)),
        Settings(visual_structure_schema_enabled=True),
        input_kind=InputKind.PDF,
    )
    manifest = _manifest(tmp_path)
    transport = _DynamicManifestTransport(manifest)
    gateway, _selected_transport, local, _ = _gateway(
        tmp_path,
        manifest=manifest,
        transport=transport,  # type: ignore[arg-type]
    )
    settings = _phase06_settings(
        visual_models_hosted_enabled=True,
        visual_models_hosted_policy_approved=True,
        visual_models_hosted_data_approved=True,
        visual_models_hosted_minimization_approved=True,
        visual_models_hosted_retention_approved=True,
        visual_models_hosted_vendor=VENDOR,
        visual_models_hosted_model=MODEL,
        visual_models_hosted_processing_region=REGION,
        visual_models_hosted_data_class=DATA_CLASS,
        visual_models_hosted_retention_policy=RETENTION,
        visual_models_hosted_redaction_decision="not_required",
        visual_models_hosted_redaction_context_id="approved-redaction-context",
        visual_models_hosted_max_requests=2,
        visual_models_hosted_max_request_pixels=8_000,
        visual_models_hosted_max_document_pixels=16_000,
        visual_models_hosted_max_cost_microunits=200,
        visual_models_hosted_max_output_tokens=400,
        visual_models_hosted_max_timeout_ms=2_000,
        visual_models_hosted_reserved_cost_microunits=100,
        visual_models_hosted_request_max_output_tokens=200,
        visual_models_hosted_request_timeout_ms=1_000,
        visual_models_routing_preference="hosted_only",
    )
    dependencies = VisualModelDependencies(
        adapters={"hosted": gateway},
        crop_provider=_crop_provider,
        deterministic_test_double=False,
    )

    result = apply_optional_visual_models(
        baseline,
        settings,
        source_document_bytes=b"unused-source",
        input_kind=InputKind.PDF,
        dependencies=dependencies,
    )

    assert transport.call_count == 1
    assert local.invoke_count == 0
    assert result != baseline
    assert "visual_model_evidence" in result["pages"][0]["items"][0]


def test_denied_gateway_keeps_representative_public_json_schema_compatible(
    client: TestClient,
    parsed_document: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _deny_sockets(monkeypatch)
    gateway, transport, local, _ = _gateway(tmp_path, policy=None)
    fallback = gateway.invoke(_request())
    assert fallback.status == "local_fallback"
    assert transport.call_count == 0
    assert local.invoke_count == 1
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: parsed_document,
    )

    response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == parsed_document
    assert "hosted" not in response.json()
