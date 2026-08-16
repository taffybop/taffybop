from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.services.release_runbooks import (
    RollbackTrigger,
    RunbookAction,
    RunbookKind,
    RunbookValidationError,
    dry_run_release,
    dry_run_rollback,
    load_runbook,
    load_verified_release_pins,
    runbook_from_mapping,
    validate_runbook_pair,
)
from app.services.release_smoke_gate import (
    BoundUpstreamGate,
    PublicFlowSmoke,
    ReleasePin,
    ReleaseSmokeGateError,
    RollbackTarget,
    SmokeGateSpec,
    evaluate_release_smoke_gate,
)


_ROOT = Path(__file__).resolve().parents[3]
_EVIDENCE = _ROOT / "tracker/phase-08-production-hardening/evidence"


def _pins() -> tuple[ReleasePin, ReleasePin]:
    verified = load_verified_release_pins(
        _EVIDENCE / "nonproduction-release-pins-v1.json",
        repository_root=_ROOT,
    )
    return verified.known_good, verified.candidate


def _smoke_decision(*, candidate_succeeds: bool = True):
    known_good, candidate = _pins()
    schema = "8" * 64
    content = "9" * 64
    return evaluate_release_smoke_gate(
        spec=SmokeGateSpec(
            gate_id="p08-functional-smoke-v1",
            required_flow_ids=("pdf.success",),
        ),
        known_good=known_good,
        candidate=candidate,
        known_good_smokes=(
            PublicFlowSmoke(
                flow_id="pdf.success",
                release_id=known_good.release_id,
                release_pin_sha256=known_good.sha256,
                parsing_succeeded=True,
                http_status=200,
                response_schema_sha256=schema,
                core_content_present=True,
                core_content_sha256=content,
            ),
        ),
        candidate_smokes=(
            PublicFlowSmoke(
                flow_id="pdf.success",
                release_id=candidate.release_id,
                release_pin_sha256=candidate.sha256,
                parsing_succeeded=candidate_succeeds,
                http_status=200 if candidate_succeeds else 422,
                response_schema_sha256=schema,
                core_content_present=candidate_succeeds,
                core_content_sha256=content if candidate_succeeds else None,
            ),
        ),
        artifact_gate=BoundUpstreamGate(
            gate="artifact",
            release_id=candidate.release_id,
            binding_sha256=candidate.artifact_manifest_sha256,
            passed=True,
        ),
        policy_gate=BoundUpstreamGate(
            gate="policy",
            release_id=candidate.release_id,
            binding_sha256=candidate.policy_sha256,
            passed=True,
        ),
        rollback_target=RollbackTarget(
            release_id=known_good.release_id,
            parser_version=known_good.parser_version,
            artifact_manifest_sha256=known_good.artifact_manifest_sha256,
            configuration_sha256=known_good.configuration_sha256,
            release_pin_sha256=known_good.sha256,
            available=True,
        ),
    )


def _runbooks():
    return (
        load_runbook(_EVIDENCE / "release-runbook-v1.json"),
        load_runbook(_EVIDENCE / "rollback-runbook-v1.json"),
    )


def _passing_evidence(runbook) -> dict[str, bool]:
    return {step.evidence_key: True for step in runbook.steps}


def _json_clone(value):
    return json.loads(json.dumps(value))


def test_checked_in_runbooks_are_owned_ordered_and_exactly_bound() -> None:
    release, rollback = _runbooks()
    known_good, candidate = _pins()

    validate_runbook_pair(release, rollback)
    assert release.kind is RunbookKind.RELEASE
    assert rollback.kind is RunbookKind.ROLLBACK
    assert release.known_good_release_pin_sha256 == known_good.sha256
    assert release.candidate_release_pin_sha256 == candidate.sha256
    assert all(step.owner.value.endswith("_owner") for step in release.steps)
    assert all(step.owner.value.endswith("_owner") for step in rollback.steps)
    assert all(step.expected_result and step.abort_condition for step in release.steps)
    assert all(step.expected_result and step.abort_condition for step in rollback.steps)

    raw = (_EVIDENCE / "release-runbook-v1.json").read_text(encoding="utf-8")
    raw += (_EVIDENCE / "rollback-runbook-v1.json").read_text(encoding="utf-8")
    assert '"command"' not in raw
    assert "subprocess" not in raw
    assert "shell" not in raw


def test_checked_in_release_pin_hashes_resolve_to_real_local_evidence() -> None:
    verified = load_verified_release_pins(
        _EVIDENCE / "nonproduction-release-pins-v1.json",
        repository_root=_ROOT,
    )
    assert verified.known_good.sha256 != verified.candidate.sha256
    assert len(verified.evidence_sha256) == 64


def test_happy_release_and_rollback_paths_are_walked_without_deployment() -> None:
    release, rollback = _runbooks()
    known_good, candidate = _pins()
    release_result = dry_run_release(
        release,
        known_good=known_good,
        candidate=candidate,
        smoke_decision=_smoke_decision(),
        evidence=_passing_evidence(release),
    )
    assert release_result.status == "pass"
    assert release_result.selected_release_id == candidate.release_id
    assert release_result.completed_actions == tuple(
        step.action for step in release.steps
    )

    rollback_result = dry_run_rollback(
        rollback,
        known_good=known_good,
        candidate=candidate,
        trigger=RollbackTrigger.OPERATOR_REQUEST,
        evidence=_passing_evidence(rollback),
    )
    assert rollback_result.status == "pass"
    assert rollback_result.selected_release_id == known_good.release_id
    assert rollback_result.completed_actions == tuple(
        step.action for step in rollback.steps
    )


def test_ordinary_functional_failure_blocks_before_any_release_action() -> None:
    release, _ = _runbooks()
    known_good, candidate = _pins()
    result = dry_run_release(
        release,
        known_good=known_good,
        candidate=candidate,
        smoke_decision=_smoke_decision(candidate_succeeds=False),
        evidence=_passing_evidence(release),
    )
    assert result.status == "block"
    assert result.selected_release_id == known_good.release_id
    assert result.completed_actions == ()
    assert result.reason == "smoke_gate_not_passed_or_unbound"


def test_malformed_or_pin_unbound_smoke_decision_cannot_select_candidate() -> None:
    release, _ = _runbooks()
    known_good, candidate = _pins()
    passing = _smoke_decision()
    with pytest.raises(ReleaseSmokeGateError, match="schema"):
        replace(passing, schema_version="garbage")

    unbound = replace(passing, candidate_release_pin_sha256="a" * 64)
    result = dry_run_release(
        release,
        known_good=known_good,
        candidate=candidate,
        smoke_decision=unbound,
        evidence=_passing_evidence(release),
    )
    assert result.status == "block"
    assert result.selected_release_id == known_good.release_id
    assert result.completed_actions == ()


def test_missing_or_failed_evidence_stops_and_retains_known_good() -> None:
    release, _ = _runbooks()
    known_good, candidate = _pins()
    evidence = _passing_evidence(release)
    evidence["release.candidate_flows"] = False
    result = dry_run_release(
        release,
        known_good=known_good,
        candidate=candidate,
        smoke_decision=_smoke_decision(),
        evidence=evidence,
    )
    assert result.status == "block"
    assert result.selected_release_id == known_good.release_id
    assert result.blocked_step_id == "release.candidate_flows"
    assert RunbookAction.RECORD_RELEASE_EVIDENCE not in result.completed_actions


def test_late_rollback_failure_reports_restored_known_good_selection() -> None:
    _, rollback = _runbooks()
    known_good, candidate = _pins()
    evidence = _passing_evidence(rollback)
    evidence["rollback.known_good_flows"] = False
    result = dry_run_rollback(
        rollback,
        known_good=known_good,
        candidate=candidate,
        trigger=RollbackTrigger.SMOKE_GATE_BLOCK,
        evidence=evidence,
    )
    assert result.status == "block"
    assert result.selected_release_id == known_good.release_id
    assert RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS in result.completed_actions
    assert result.blocked_step_id == "rollback.known_good_flows"


@pytest.mark.parametrize("field", ["owner", "abort_condition", "evidence_key"])
def test_missing_required_step_fields_fail_closed(field: str) -> None:
    release, _ = _runbooks()
    value = _json_clone(release.to_mapping())
    del value["steps"][2][field]
    with pytest.raises(RunbookValidationError):
        runbook_from_mapping(value)


def test_arbitrary_command_surface_is_rejected() -> None:
    release, _ = _runbooks()
    value = _json_clone(release.to_mapping())
    value["steps"][0]["command"] = "deploy --force"
    with pytest.raises(RunbookValidationError, match="unsupported"):
        runbook_from_mapping(value)


def test_promotion_before_smoke_gate_fails_required_order() -> None:
    release, _ = _runbooks()
    value = _json_clone(release.to_mapping())
    value["steps"][4]["action"], value["steps"][5]["action"] = (
        value["steps"][5]["action"],
        value["steps"][4]["action"],
    )
    with pytest.raises(RunbookValidationError, match="out of order"):
        runbook_from_mapping(value)


def test_wrong_owner_or_next_approval_fails_closed() -> None:
    release, _ = _runbooks()
    wrong_owner = _json_clone(release.to_mapping())
    wrong_owner["steps"][1]["owner"] = "release_owner"
    with pytest.raises(RunbookValidationError, match="owner"):
        runbook_from_mapping(wrong_owner)

    wrong_approval = _json_clone(release.to_mapping())
    wrong_approval["steps"][1]["next_approval"] = "api_owner"
    with pytest.raises(RunbookValidationError, match="next step owner"):
        runbook_from_mapping(wrong_approval)


def test_forward_or_cyclic_prerequisite_fails_closed() -> None:
    release, _ = _runbooks()
    value = _json_clone(release.to_mapping())
    value["steps"][2]["prerequisites"] = ["release.safe_defaults"]
    with pytest.raises(RunbookValidationError, match="cyclic|appears after"):
        runbook_from_mapping(value)


def test_stale_release_pin_cannot_be_dry_run() -> None:
    release, _ = _runbooks()
    known_good, candidate = _pins()
    stale_candidate = replace(candidate, configuration_sha256="a" * 64)
    with pytest.raises(RunbookValidationError, match="not bound"):
        dry_run_release(
            release,
            known_good=known_good,
            candidate=stale_candidate,
            smoke_decision=_smoke_decision(),
            evidence=_passing_evidence(release),
        )


def test_mismatched_release_and_rollback_pair_is_rejected() -> None:
    release, rollback = _runbooks()
    with pytest.raises(RunbookValidationError, match="different targets"):
        validate_runbook_pair(release, replace(rollback, smoke_gate_id="other-gate"))


def test_manifest_and_evidence_bounds_fail_closed() -> None:
    release, _ = _runbooks()
    value = _json_clone(release.to_mapping())
    value["steps"] = value["steps"] * 5
    with pytest.raises(RunbookValidationError, match="bounded"):
        runbook_from_mapping(value)

    known_good, candidate = _pins()
    oversized_evidence = {f"extra.{index}": True for index in range(33)}
    with pytest.raises(RunbookValidationError, match="unbounded"):
        dry_run_release(
            release,
            known_good=known_good,
            candidate=candidate,
            smoke_decision=_smoke_decision(),
            evidence=oversized_evidence,
        )

    unexpected_evidence = _passing_evidence(release)
    unexpected_evidence["unapproved.extra"] = True
    with pytest.raises(RunbookValidationError, match="exactly match"):
        dry_run_release(
            release,
            known_good=known_good,
            candidate=candidate,
            smoke_decision=_smoke_decision(),
            evidence=unexpected_evidence,
        )


def test_symlinked_runbook_is_not_loaded(tmp_path: Path) -> None:
    link = tmp_path / "release.json"
    link.symlink_to(_EVIDENCE / "release-runbook-v1.json")
    with pytest.raises(RunbookValidationError, match="regular local file"):
        load_runbook(link)


def test_runbook_canonicalization_is_deterministic() -> None:
    release, rollback = _runbooks()
    assert runbook_from_mapping(_json_clone(release.to_mapping())).sha256 == release.sha256
    assert runbook_from_mapping(_json_clone(rollback.to_mapping())).sha256 == rollback.sha256


def test_invalid_rollback_trigger_and_wrong_runbook_kind_fail_closed() -> None:
    release, rollback = _runbooks()
    known_good, candidate = _pins()
    with pytest.raises(RunbookValidationError, match="rollback_trigger"):
        dry_run_rollback(
            rollback,
            known_good=known_good,
            candidate=candidate,
            trigger="production_magic",  # type: ignore[arg-type]
            evidence=_passing_evidence(rollback),
        )
    with pytest.raises(RunbookValidationError, match="rollback runbook"):
        dry_run_release(
            rollback,
            known_good=known_good,
            candidate=candidate,
            smoke_decision=_smoke_decision(),
            evidence=_passing_evidence(rollback),
        )
