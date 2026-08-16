from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.artifact_manifest import (
    LOCAL_REFERENCE_ARTIFACT_PROFILE,
    ManifestVerification,
    load_manifest,
    verify_release_startup_manifest,
)
from app.services.release_runbooks import (
    RunbookAction,
    RunbookValidationError,
    load_runbook,
    load_verified_release_pins,
)
from app.services.rollback_smoke import (
    FlowOutcome,
    RepresentativeFlow,
    RollbackProfile,
    RollbackSmokeError,
    RollbackSmokeSpec,
    ShippingFlagSnapshot,
    SmokeBlockReason,
    SmokeStatus,
    execute_nonproduction_rollback_smoke,
    load_hosted_policy_selection,
    load_representative_flow_contract,
    load_shipping_flag_profile,
)


_ROOT = Path(__file__).resolve().parents[3]
_EVIDENCE = _ROOT / "tracker/phase-08-production-hardening/evidence"
_MANIFEST_PATH = _EVIDENCE / "shipped-artifacts-reference-v1.json"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pins():
    verified = load_verified_release_pins(
        _EVIDENCE / "nonproduction-release-pins-v1.json",
        repository_root=_ROOT,
    )
    return verified.known_good, verified.candidate


def _flow_set(pin_sha256: str) -> tuple[RepresentativeFlow, ...]:
    return (
        RepresentativeFlow(
            flow_id="public-invalid-input-json",
            release_pin_sha256=pin_sha256,
            outcome=FlowOutcome.ORDINARY_FAILURE,
            http_status=415,
            response_schema_sha256=_digest("error-envelope-v1"),
            canonical_output_sha256=_digest("unsupported-file-type"),
        ),
        RepresentativeFlow(
            flow_id="public-pdf-json",
            release_pin_sha256=pin_sha256,
            outcome=FlowOutcome.SUCCESS,
            http_status=200,
            response_schema_sha256=_digest("parse-result-v1"),
            canonical_output_sha256=_digest("known-good-public-result"),
        ),
    )


def _profiles() -> tuple[RollbackProfile, RollbackProfile]:
    known_pin, candidate_pin = _pins()
    flow_contract = load_representative_flow_contract(
        _EVIDENCE / "representative-flows-v1.json"
    )
    known_flows = tuple(
        RepresentativeFlow(
            flow_id=value.flow_id,
            release_pin_sha256=known_pin.sha256,
            outcome=value.outcome,
            http_status=value.http_status,
            response_schema_sha256=value.response_schema_sha256,
            canonical_output_sha256=value.canonical_output_sha256,
        )
        for value in flow_contract.entries
    )
    candidate_flows = tuple(
        replace(value, release_pin_sha256=candidate_pin.sha256)
        for value in known_flows
    )
    known = RollbackProfile(
        release=known_pin,
        flags=load_shipping_flag_profile(_EVIDENCE / "known-good-flags-v1.json"),
        hosted_policy=load_hosted_policy_selection(
            _EVIDENCE / "known-good-hosted-policy-v1.json"
        ),
        artifact_profile_id=LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id,
        flow_contract=flow_contract,
        flows=known_flows,
    )
    candidate = RollbackProfile(
        release=candidate_pin,
        flags=load_shipping_flag_profile(_EVIDENCE / "candidate-flags-v1.json"),
        hosted_policy=load_hosted_policy_selection(
            _EVIDENCE / "candidate-hosted-policy-v1.json"
        ),
        artifact_profile_id=LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id,
        flow_contract=flow_contract,
        flows=candidate_flows,
    )
    return known, candidate


def _artifact_evidence():
    manifest = load_manifest(_MANIFEST_PATH)
    verification = verify_release_startup_manifest(
        manifest,
        root=_ROOT,
        profile=LOCAL_REFERENCE_ARTIFACT_PROFILE,
    )
    return manifest, verification


def _smoke(**updates: Any):
    known, candidate = _profiles()
    manifest, verification = _artifact_evidence()
    values: dict[str, Any] = {
        "spec": RollbackSmokeSpec(
            smoke_id="p08-bounded-rollback-smoke-v1",
            environment="non_production",
            injection_flow_id="public-pdf-json",
        ),
        "runbook": load_runbook(_EVIDENCE / "rollback-runbook-v1.json"),
        "known_good": known,
        "candidate": candidate,
        "artifact_manifest": manifest,
        "artifact_verification": verification,
    }
    values.update(updates)
    return execute_nonproduction_rollback_smoke(**values)


def _canonical_json_digest(response) -> str:
    return hashlib.sha256(
        json.dumps(response.json(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _schema_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _schema_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [] if not value else [_schema_shape(value[0])]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _response_flow(flow_id: str, pin_sha256: str, response) -> RepresentativeFlow:
    shape = json.dumps(
        _schema_shape(response.json()), sort_keys=True, separators=(",", ":")
    )
    return RepresentativeFlow(
        flow_id=flow_id,
        release_pin_sha256=pin_sha256,
        outcome=(
            FlowOutcome.SUCCESS
            if 200 <= response.status_code <= 299
            else FlowOutcome.ORDINARY_FAILURE
        ),
        http_status=response.status_code,
        response_schema_sha256=_digest(shape),
        canonical_output_sha256=_canonical_json_digest(response),
    )


def test_one_bounded_nonproduction_failure_restores_exact_known_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("rollback smoke attempted a live external call")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)

    known, candidate = _profiles()
    record = _smoke(
        known_good=known,
        candidate=candidate,
    )
    rollback = load_runbook(_EVIDENCE / "rollback-runbook-v1.json")

    assert record.status is SmokeStatus.PASS
    assert record.failure_detected is True
    assert record.injected_failure == "ordinary_functional_failure"
    assert record.completed_actions == tuple(step.action for step in rollback.steps)
    assert record.selected_release_id == known.release.release_id
    assert record.restored_release_pin_sha256 == known.release.sha256
    assert record.restored_flag_snapshot_sha256 == known.flags.sha256
    assert record.restored_artifact_manifest_sha256 == known.release.artifact_manifest_sha256
    assert record.restored_configuration_sha256 == known.release.configuration_sha256
    assert record.restored_policy_sha256 == known.release.policy_sha256
    assert record.restored_flow_ids == tuple(value.flow_id for value in known.flows)
    assert record.candidate_active is False
    assert record.hosted_transport_calls == 0
    assert record.post_stop_candidate_attempts == 1
    assert record.post_stop_candidate_calls == 0
    assert record.blocking_reasons == ()
    assert record.restored_flow_set_sha256 is not None


def test_representative_public_success_and_ordinary_failure_are_restored(
    client: TestClient,
) -> None:
    success_before = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", b"%PDF-1.7\n% rollback smoke\n", "application/pdf")},
    )
    failure_before = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.exe", b"not-supported", "application/octet-stream")},
    )
    assert success_before.status_code == 200
    assert failure_before.status_code == 415

    known, candidate = _profiles()
    known_flows = tuple(
        sorted(
            (
                _response_flow("public-pdf-json", known.release.sha256, success_before),
                _response_flow(
                    "public-invalid-input-json",
                    known.release.sha256,
                    failure_before,
                ),
            ),
            key=lambda value: value.flow_id,
        )
    )
    candidate_flows = tuple(
        replace(value, release_pin_sha256=candidate.release.sha256)
        for value in known_flows
    )
    # The runtime observations must match the repository-owned flow contract.
    assert tuple(value.compatible_identity() for value in known_flows) == tuple(
        value.compatible_identity() for value in known.flow_contract.entries
    )
    record = _smoke(known_good=known, candidate=candidate)
    assert record.status is SmokeStatus.PASS

    success_after = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", b"%PDF-1.7\n% rollback smoke\n", "application/pdf")},
    )
    failure_after = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.exe", b"not-supported", "application/octet-stream")},
    )
    assert success_after.status_code == success_before.status_code
    assert failure_after.status_code == failure_before.status_code
    assert _canonical_json_digest(success_after) == _canonical_json_digest(success_before)
    assert _canonical_json_digest(failure_after) == _canonical_json_digest(failure_before)


def test_identical_smoke_is_deterministic_and_privacy_bounded() -> None:
    first = _smoke()
    second = _smoke()
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.sha256 == second.sha256
    assert len(first.canonical_bytes()) < 4_096
    encoded = first.canonical_bytes().decode("utf-8")
    for forbidden in ("document content", "filename", "prompt", "crop", "credential", "secret"):
        assert forbidden not in encoded.casefold()


def test_missing_candidate_controls_blocks_before_rollback() -> None:
    known, candidate = _profiles()
    no_controls_pin = replace(
        candidate.release,
        configuration_sha256=known.flags.source_sha256,
    )
    no_controls = replace(
        candidate,
        release=no_controls_pin,
        flags=known.flags,
        flows=tuple(
            replace(value, release_pin_sha256=no_controls_pin.sha256)
            for value in candidate.flows
        ),
    )
    with pytest.raises(RollbackSmokeError, match="not bound"):
        _smoke(candidate=no_controls)


def test_injection_must_target_exactly_one_successful_flow() -> None:
    record = _smoke(
        spec=RollbackSmokeSpec(
            smoke_id="p08-bounded-rollback-smoke-v1",
            environment="non_production",
            injection_flow_id="public-invalid-input-json",
        )
    )
    assert record.status is SmokeStatus.BLOCK
    assert record.blocking_reasons == (SmokeBlockReason.INJECTION_NOT_DETECTED,)
    with pytest.raises(RollbackSmokeError, match="ordinary failure"):
        RollbackSmokeSpec(
            smoke_id="p08-bounded-rollback-smoke-v1",
            environment="non_production",
            injection_flow_id="public-pdf-json",
            injection="multiple_failures",
        )


def test_changed_candidate_flow_blocks_before_injection() -> None:
    known, candidate = _profiles()
    changed = tuple(
        replace(value, canonical_output_sha256="e" * 64)
        if value.flow_id == "public-pdf-json"
        else value
        for value in candidate.flows
    )
    with pytest.raises(RollbackSmokeError, match="contract"):
        replace(candidate, flows=changed)


@pytest.mark.parametrize(
    "action",
    [
        RunbookAction.REQUEST_CANDIDATE_STOP,
        RunbookAction.RESTORE_KNOWN_GOOD_FLAGS,
        RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS,
        RunbookAction.RESTORE_KNOWN_GOOD_POLICY,
        RunbookAction.VERIFY_KNOWN_GOOD_FLOWS,
    ],
)
def test_any_documented_rollback_action_failure_blocks(action: RunbookAction) -> None:
    record = _smoke(fail_action=action)
    assert record.status is SmokeStatus.BLOCK
    assert record.blocking_reasons == (SmokeBlockReason.RUNBOOK_BLOCKED,)
    assert action not in record.completed_actions


def test_fabricated_artifact_verification_blocks_restoration() -> None:
    manifest, accepted = _artifact_evidence()
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
    record = _smoke(
        artifact_manifest=manifest,
        artifact_verification=forged,
    )
    assert record.status is SmokeStatus.BLOCK
    assert record.blocking_reasons == (
        SmokeBlockReason.ARTIFACT_VERIFICATION_INVALID,
    )
    assert RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS not in record.completed_actions


def test_stale_pin_or_mismatched_runbook_fails_closed() -> None:
    known, candidate = _profiles()
    stale_pin = replace(candidate.release, policy_sha256="d" * 64)
    with pytest.raises(RollbackSmokeError, match="hosted policy selection"):
        replace(candidate, release=stale_pin)

    runbook = load_runbook(_EVIDENCE / "rollback-runbook-v1.json")
    with pytest.raises(RollbackSmokeError, match="not bound"):
        _smoke(runbook=replace(runbook, candidate_release_pin_sha256="a" * 64))


def test_profiles_reject_unknown_flags_or_fail_open_hosted_policy(tmp_path: Path) -> None:
    bad_flags = tmp_path / "bad-flags.json"
    bad_flags.write_text(
        json.dumps(
            {
                "schema_version": "parser-nonproduction-flag-profile-v1",
                "profile_id": "bad-flags",
                "environment": "non_production",
                "global_kill_switch": False,
                "disabled_capabilities": [],
                "enabled_flags": ["unknown_enabled_flag"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RollbackSmokeError, match="unknown setting"):
        load_shipping_flag_profile(bad_flags)

    bad_policy = tmp_path / "bad-policy.json"
    bad_policy.write_text(
        json.dumps(
            {
                "schema_version": "parser-nonproduction-hosted-policy-selection-v1",
                "profile_id": "bad-policy",
                "environment": "non_production",
                "hosted_enabled": True,
                "default_decision": "allow",
                "maximum_transport_calls_on_denial": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RollbackSmokeError, match="deny by default"):
        load_hosted_policy_selection(bad_policy)


def test_modified_or_copied_flow_contract_cannot_gain_repository_authority(
    tmp_path: Path,
) -> None:
    modified = tmp_path / "representative-flows-v1.json"
    value = json.loads(
        (_EVIDENCE / "representative-flows-v1.json").read_text(encoding="utf-8")
    )
    value["flows"][1]["canonical_output_sha256"] = "f" * 64
    modified.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RollbackSmokeError, match="pinned repository evidence"):
        load_representative_flow_contract(modified)


def test_production_environment_and_unbounded_flows_are_rejected() -> None:
    with pytest.raises(RollbackSmokeError, match="non_production"):
        RollbackSmokeSpec(
            smoke_id="p08-bounded-rollback-smoke-v1",
            environment="production",
            injection_flow_id="public-pdf-json",
        )
    known, _ = _profiles()
    oversized = tuple(
        replace(
            known.flows[0],
            flow_id=f"ordinary-flow-{index:02d}",
        )
        for index in range(17)
    )
    with pytest.raises(RollbackSmokeError, match="unbounded"):
        replace(known, flows=oversized)


def test_default_off_snapshot_is_exact_and_candidate_snapshot_is_dependency_valid() -> None:
    known, candidate = _profiles()
    assert known.flags == ShippingFlagSnapshot.from_settings(
        # Preserve the checked-in source binding while comparing effective state.
        Settings(),
        source_sha256=known.flags.source_sha256,
    )
    assert candidate.flags.enabled_settings() == {
        "telemetry_enabled",
        "telemetry_resources_enabled",
        "telemetry_quality_enabled",
        "deterministic_confidence_enabled",
        "visual_confidence_enabled",
        "review_escalation_enabled",
    }
    assert known.hosted_policy.hosted_enabled is False
    assert known.hosted_policy.maximum_transport_calls_on_denial == 0
