"""P08-US10 lightweight pinned functional release smoke gate."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import repeat

import pytest

from app.services.release_smoke_gate import (
    BoundUpstreamGate,
    PublicFlowSmoke,
    ReleasePin,
    ReleaseSmokeGateError,
    RollbackTarget,
    SmokeBlockReason,
    SmokeGateSpec,
    evaluate_release_smoke_gate,
)


def _digest(character: str) -> str:
    return character * 64


def _pins() -> tuple[ReleasePin, ReleasePin]:
    known_good = ReleasePin(
        release_id="release-known-good",
        parser_version="8.0.0-known-good",
        artifact_manifest_sha256=_digest("1"),
        configuration_sha256=_digest("2"),
        api_schema_sha256=_digest("3"),
        policy_sha256=_digest("4"),
    )
    candidate = ReleasePin(
        release_id="release-candidate",
        parser_version="8.0.0-candidate",
        artifact_manifest_sha256=_digest("5"),
        configuration_sha256=_digest("6"),
        api_schema_sha256=_digest("3"),
        policy_sha256=_digest("7"),
    )
    return known_good, candidate


def _smoke(pin: ReleasePin, *, flow_id: str = "public-pdf-json") -> PublicFlowSmoke:
    return PublicFlowSmoke(
        flow_id=flow_id,
        release_id=pin.release_id,
        release_pin_sha256=pin.sha256,
        parsing_succeeded=True,
        http_status=200,
        response_schema_sha256=_digest("8"),
        core_content_present=True,
        core_content_sha256=_digest("9"),
    )


def _inputs() -> dict[str, object]:
    known_good, candidate = _pins()
    return {
        "spec": SmokeGateSpec(
            gate_id="phase08-functional-smoke",
            required_flow_ids=("public-pdf-json",),
        ),
        "known_good": known_good,
        "candidate": candidate,
        "known_good_smokes": (_smoke(known_good),),
        "candidate_smokes": (_smoke(candidate),),
        "artifact_gate": BoundUpstreamGate(
            gate="artifact",
            release_id=candidate.release_id,
            binding_sha256=candidate.artifact_manifest_sha256,
            passed=True,
        ),
        "policy_gate": BoundUpstreamGate(
            gate="policy",
            release_id=candidate.release_id,
            binding_sha256=candidate.policy_sha256,
            passed=True,
        ),
        "rollback_target": RollbackTarget(
            release_id=known_good.release_id,
            parser_version=known_good.parser_version,
            artifact_manifest_sha256=known_good.artifact_manifest_sha256,
            configuration_sha256=known_good.configuration_sha256,
            release_pin_sha256=known_good.sha256,
            available=True,
        ),
    }


def test_matching_representative_public_flow_selects_candidate_deterministically() -> None:
    values = _inputs()

    first = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]
    second = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.sha256 == second.sha256
    assert first.decision == "pass"
    assert first.summary == "candidate_selected"
    assert first.selected_release_id == "release-candidate"
    assert first.blocking_reasons == ()
    assert first.flows[0].status == "pass"
    assert json.loads(first.canonical_bytes()) == first.to_mapping()
    assert len(values["known_good"].sha256) == 64  # type: ignore[union-attr]
    assert values["known_good"].sha256 != values["candidate"].sha256  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            {"parsing_succeeded": False, "http_status": 500},
            SmokeBlockReason.CANDIDATE_PARSE_FAILED,
        ),
        (
            {"core_content_sha256": _digest("a")},
            SmokeBlockReason.CANDIDATE_CORE_CONTENT_REGRESSION,
        ),
        (
            {"response_schema_sha256": _digest("b")},
            SmokeBlockReason.RESPONSE_SCHEMA_INCOMPATIBLE,
        ),
    ],
)
def test_functional_or_response_schema_regression_blocks_candidate(
    mutation: dict[str, object],
    reason: SmokeBlockReason,
) -> None:
    values = _inputs()
    candidate_smoke = values["candidate_smokes"][0]  # type: ignore[index]
    values["candidate_smokes"] = (replace(candidate_smoke, **mutation),)

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.decision == "block"
    assert reason in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


def test_pinned_api_schema_regression_blocks_before_selection() -> None:
    values = _inputs()
    candidate = values["candidate"]
    changed_candidate = replace(candidate, api_schema_sha256=_digest("c"))
    values["candidate"] = changed_candidate
    values["candidate_smokes"] = (_smoke(changed_candidate),)

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.blocking_reasons == (
        SmokeBlockReason.API_SCHEMA_INCOMPATIBLE,
    )
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("parser_version", "8.0.1-candidate"),
        ("configuration_sha256", _digest("a")),
    ],
)
def test_smoke_is_bound_to_candidate_parser_and_configuration_pin(
    field: str,
    changed_value: str,
) -> None:
    values = _inputs()
    values["candidate"] = replace(
        values["candidate"],
        **{field: changed_value},
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert SmokeBlockReason.CANDIDATE_EVIDENCE_UNBOUND in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize("smoke_name", ["known_good_smokes", "candidate_smokes"])
def test_every_smoke_requires_its_complete_release_pin_digest(
    smoke_name: str,
) -> None:
    values = _inputs()
    smoke = values[smoke_name][0]  # type: ignore[index]
    values[smoke_name] = (replace(smoke, release_pin_sha256=_digest("f")),)

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    expected = (
        SmokeBlockReason.KNOWN_GOOD_EVIDENCE_UNBOUND
        if smoke_name == "known_good_smokes"
        else SmokeBlockReason.CANDIDATE_EVIDENCE_UNBOUND
    )
    assert expected in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


def test_same_release_identity_is_an_ambiguous_declaration() -> None:
    values = _inputs()
    known_good = values["known_good"]
    values["candidate"] = replace(
        values["candidate"],
        release_id=known_good.release_id,
    )

    with pytest.raises(ReleaseSmokeGateError, match="must be distinct"):
        evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("gate_name", "reason"),
    [
        ("artifact_gate", SmokeBlockReason.ARTIFACT_GATE_FAILED),
        ("policy_gate", SmokeBlockReason.POLICY_GATE_FAILED),
    ],
)
def test_upstream_artifact_or_policy_failure_blocks(
    gate_name: str,
    reason: SmokeBlockReason,
) -> None:
    values = _inputs()
    values[gate_name] = replace(values[gate_name], passed=False)

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert reason in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


def test_missing_required_smoke_coverage_blocks() -> None:
    values = _inputs()
    values["spec"] = SmokeGateSpec(
        gate_id="phase08-functional-smoke",
        required_flow_ids=("public-image-json", "public-pdf-json"),
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.decision == "block"
    assert decision.flows[0].flow_id == "public-image-json"
    assert decision.flows[0].blocking_reasons == (
        SmokeBlockReason.KNOWN_GOOD_SMOKE_MISSING,
        SmokeBlockReason.CANDIDATE_SMOKE_MISSING,
    )
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize(
    ("smoke_name", "reason"),
    [
        ("known_good_smokes", SmokeBlockReason.UNEXPECTED_KNOWN_GOOD_SMOKE),
        ("candidate_smokes", SmokeBlockReason.UNEXPECTED_CANDIDATE_SMOKE),
    ],
)
def test_extra_unrequired_smoke_blocks_exact_flow_set(
    smoke_name: str,
    reason: SmokeBlockReason,
) -> None:
    values = _inputs()
    pin_name = "known_good" if smoke_name == "known_good_smokes" else "candidate"
    values[smoke_name] = (
        *values[smoke_name],  # type: ignore[misc]
        _smoke(values[pin_name], flow_id="unrequired-public-flow"),  # type: ignore[arg-type]
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert reason in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize(
    ("smoke_name", "reason"),
    [
        ("known_good_smokes", SmokeBlockReason.DUPLICATE_KNOWN_GOOD_SMOKE),
        ("candidate_smokes", SmokeBlockReason.DUPLICATE_CANDIDATE_SMOKE),
    ],
)
def test_duplicate_smoke_blocks_exact_flow_set(
    smoke_name: str,
    reason: SmokeBlockReason,
) -> None:
    values = _inputs()
    smoke = values[smoke_name][0]  # type: ignore[index]
    values[smoke_name] = (smoke, smoke)

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert reason in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


def test_smoke_iterator_is_consumed_only_to_the_hard_cap() -> None:
    values = _inputs()
    smoke = values["candidate_smokes"][0]  # type: ignore[index]
    values["candidate_smokes"] = repeat(smoke)

    with pytest.raises(ReleaseSmokeGateError, match="exceeds 64 entries"):
        evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]


def test_failing_candidate_public_flow_retains_pinned_known_good() -> None:
    values = _inputs()
    candidate_smoke = values["candidate_smokes"][0]  # type: ignore[index]
    values["candidate_smokes"] = (
        replace(candidate_smoke, parsing_succeeded=False, http_status=422),
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.to_mapping()["summary"] == (
        "candidate_blocked_known_good_retained"
    )
    assert decision.selected_release_id == decision.known_good_release_id
    assert SmokeBlockReason.CANDIDATE_PARSE_FAILED in decision.blocking_reasons


def test_unavailable_rollback_target_blocks_and_retains_known_good_identity() -> None:
    values = _inputs()
    values["rollback_target"] = replace(
        values["rollback_target"],
        available=False,
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.blocking_reasons == (
        SmokeBlockReason.ROLLBACK_TARGET_UNAVAILABLE,
    )
    assert decision.selected_release_id == "release-known-good"


def test_unbound_gate_and_rollback_evidence_fail_closed() -> None:
    values = _inputs()
    values["artifact_gate"] = replace(
        values["artifact_gate"],
        binding_sha256=_digest("d"),
    )
    values["rollback_target"] = replace(
        values["rollback_target"],
        configuration_sha256=_digest("e"),
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert decision.blocking_reasons == (
        SmokeBlockReason.ARTIFACT_GATE_UNBOUND,
        SmokeBlockReason.ROLLBACK_TARGET_MISMATCH,
    )
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize("pin_field", ["api_schema_sha256", "policy_sha256"])
def test_rollback_target_digest_binds_api_and_policy_pin(pin_field: str) -> None:
    values = _inputs()
    known_good = values["known_good"]
    wrong_complete_pin = replace(known_good, **{pin_field: _digest("e")})
    values["rollback_target"] = replace(
        values["rollback_target"],
        release_pin_sha256=wrong_complete_pin.sha256,
    )

    decision = evaluate_release_smoke_gate(**values)  # type: ignore[arg-type]

    assert SmokeBlockReason.ROLLBACK_TARGET_MISMATCH in decision.blocking_reasons
    assert decision.selected_release_id == "release-known-good"


@pytest.mark.parametrize(
    ("parsing_succeeded", "http_status"),
    [(True, 500), (False, 200)],
)
def test_smoke_rejects_contradictory_parse_and_http_status(
    parsing_succeeded: bool,
    http_status: int,
) -> None:
    pin = _pins()[1]

    with pytest.raises(ReleaseSmokeGateError, match="true exactly for a 2xx"):
        replace(
            _smoke(pin),
            parsing_succeeded=parsing_succeeded,
            http_status=http_status,
        )

    ordinary_failure = replace(
        _smoke(pin),
        parsing_succeeded=False,
        http_status=422,
    )
    assert ordinary_failure.parsing_succeeded is False
    assert ordinary_failure.http_status == 422


def test_gate_contracts_are_bounded_and_store_no_document_payload() -> None:
    with pytest.raises(ReleaseSmokeGateError, match="between 1 and 64"):
        SmokeGateSpec(gate_id="phase08-functional-smoke", required_flow_ids=())
    with pytest.raises(ReleaseSmokeGateError, match="sorted and unique"):
        SmokeGateSpec(
            gate_id="phase08-functional-smoke",
            required_flow_ids=("public-pdf-json", "public-pdf-json"),
        )
    with pytest.raises(ReleaseSmokeGateError, match="comparison digest"):
        PublicFlowSmoke(
            flow_id="public-pdf-json",
            release_id="release-candidate",
            release_pin_sha256=_digest("7"),
            parsing_succeeded=True,
            http_status=200,
            response_schema_sha256=_digest("8"),
            core_content_present=True,
            core_content_sha256=None,
        )

    decision = evaluate_release_smoke_gate(**_inputs())  # type: ignore[arg-type]
    encoded = decision.canonical_bytes().decode("utf-8")
    for forbidden in (
        "private-file.pdf",
        "document text",
        "prompt",
        "crop",
        "credential",
        "secret",
    ):
        assert forbidden not in encoded
