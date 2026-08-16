"""Offline, deterministic Phase 08 functional release smoke gate.

The gate consumes bounded summaries produced by a small set of approved public
flows.  It has no parser runner, deployment client, network transport, traffic
canary, percentile calculation, or document-content field.  A candidate is
selectable only when its pinned upstream gates and every required smoke match
the pinned known-good release.  Every incomplete or failing comparison keeps
the known-good identity selected.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from typing import Any, Iterable, Mapping


_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FLOWS = 64
_MAX_DECISION_BYTES = 131_072


class ReleaseSmokeGateError(ValueError):
    """Raised when the release declaration itself is ambiguous or unbounded."""


class SmokeBlockReason(StrEnum):
    """Stable release-first blockers; no source payload can enter these values."""

    API_SCHEMA_INCOMPATIBLE = "api_schema_incompatible"
    ARTIFACT_GATE_FAILED = "artifact_gate_failed"
    ARTIFACT_GATE_UNBOUND = "artifact_gate_unbound"
    CANDIDATE_CORE_CONTENT_MISSING = "candidate_core_content_missing"
    CANDIDATE_CORE_CONTENT_REGRESSION = "candidate_core_content_regression"
    CANDIDATE_EVIDENCE_UNBOUND = "candidate_evidence_unbound"
    CANDIDATE_PARSE_FAILED = "candidate_parse_failed"
    CANDIDATE_SMOKE_MISSING = "candidate_smoke_missing"
    DUPLICATE_CANDIDATE_SMOKE = "duplicate_candidate_smoke"
    DUPLICATE_KNOWN_GOOD_SMOKE = "duplicate_known_good_smoke"
    FUNCTIONAL_STATUS_REGRESSION = "functional_status_regression"
    KNOWN_GOOD_CORE_CONTENT_MISSING = "known_good_core_content_missing"
    KNOWN_GOOD_EVIDENCE_UNBOUND = "known_good_evidence_unbound"
    KNOWN_GOOD_SMOKE_FAILED = "known_good_smoke_failed"
    KNOWN_GOOD_SMOKE_MISSING = "known_good_smoke_missing"
    POLICY_GATE_FAILED = "policy_gate_failed"
    POLICY_GATE_UNBOUND = "policy_gate_unbound"
    RESPONSE_SCHEMA_INCOMPATIBLE = "response_schema_incompatible"
    ROLLBACK_TARGET_MISMATCH = "rollback_target_mismatch"
    ROLLBACK_TARGET_UNAVAILABLE = "rollback_target_unavailable"
    UNEXPECTED_CANDIDATE_SMOKE = "unexpected_candidate_smoke"
    UNEXPECTED_KNOWN_GOOD_SMOKE = "unexpected_known_good_smoke"


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ReleaseSmokeGateError(f"{field} must be a bounded identifier")
    return value


def _sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReleaseSmokeGateError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _printable(value: str, field: str, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ReleaseSmokeGateError(f"{field} must be bounded printable text")
    return value


@dataclass(frozen=True, slots=True)
class ReleasePin:
    """All identities needed to compare and recover one release."""

    release_id: str
    parser_version: str
    artifact_manifest_sha256: str
    configuration_sha256: str
    api_schema_sha256: str
    policy_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "release_id", _identifier(self.release_id, "release_id")
        )
        object.__setattr__(
            self,
            "parser_version",
            _printable(self.parser_version, "parser_version"),
        )
        for field in (
            "artifact_manifest_sha256",
            "configuration_sha256",
            "api_schema_sha256",
            "policy_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))

    def to_mapping(self) -> dict[str, str]:
        """Return the complete, domain-separated release identity."""

        return {
            "schema_version": "parser-release-pin-v1",
            "release_id": self.release_id,
            "parser_version": self.parser_version,
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "configuration_sha256": self.configuration_sha256,
            "api_schema_sha256": self.api_schema_sha256,
            "policy_sha256": self.policy_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        """Digest binding smoke and rollback evidence to every release pin."""

        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class SmokeGateSpec:
    """Finite required public-flow coverage for one functional gate."""

    gate_id: str
    required_flow_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _identifier(self.gate_id, "gate_id"))
        if (
            not isinstance(self.required_flow_ids, tuple)
            or not 1 <= len(self.required_flow_ids) <= _MAX_FLOWS
        ):
            raise ReleaseSmokeGateError(
                "required public flows must contain between 1 and 64 entries"
            )
        flows = tuple(
            _identifier(value, "required_flow_id")
            for value in self.required_flow_ids
        )
        if flows != tuple(sorted(flows)) or len(flows) != len(set(flows)):
            raise ReleaseSmokeGateError(
                "required public flow identifiers must be sorted and unique"
            )
        object.__setattr__(self, "required_flow_ids", flows)


@dataclass(frozen=True, slots=True)
class PublicFlowSmoke:
    """Content-free summary of one public parse flow."""

    flow_id: str
    release_id: str
    release_pin_sha256: str
    parsing_succeeded: bool
    http_status: int
    response_schema_sha256: str
    core_content_present: bool
    core_content_sha256: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "flow_id", _identifier(self.flow_id, "flow_id"))
        object.__setattr__(
            self, "release_id", _identifier(self.release_id, "release_id")
        )
        object.__setattr__(
            self,
            "release_pin_sha256",
            _sha256(self.release_pin_sha256, "release_pin_sha256"),
        )
        for field in ("parsing_succeeded", "core_content_present"):
            if not isinstance(getattr(self, field), bool):
                raise ReleaseSmokeGateError(f"{field} must be a boolean")
        if (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise ReleaseSmokeGateError("http_status is outside its bound")
        if self.parsing_succeeded != (200 <= self.http_status <= 299):
            raise ReleaseSmokeGateError(
                "parsing_succeeded must be true exactly for a 2xx status"
            )
        object.__setattr__(
            self,
            "response_schema_sha256",
            _sha256(self.response_schema_sha256, "response_schema_sha256"),
        )
        if self.core_content_present:
            if self.core_content_sha256 is None:
                raise ReleaseSmokeGateError(
                    "present core content requires its comparison digest"
                )
            object.__setattr__(
                self,
                "core_content_sha256",
                _sha256(self.core_content_sha256, "core_content_sha256"),
            )
        elif self.core_content_sha256 is not None:
            raise ReleaseSmokeGateError(
                "absent core content cannot claim a comparison digest"
            )


@dataclass(frozen=True, slots=True)
class BoundUpstreamGate:
    """Candidate-bound pass/fail evidence from US08 or US09."""

    gate: str
    release_id: str
    binding_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        if self.gate not in {"artifact", "policy"}:
            raise ReleaseSmokeGateError("upstream gate must be artifact or policy")
        object.__setattr__(
            self, "release_id", _identifier(self.release_id, "release_id")
        )
        object.__setattr__(
            self,
            "binding_sha256",
            _sha256(self.binding_sha256, "binding_sha256"),
        )
        if not isinstance(self.passed, bool):
            raise ReleaseSmokeGateError("upstream gate result must be a boolean")


@dataclass(frozen=True, slots=True)
class RollbackTarget:
    """Locally resolvable target for the pinned known-good release."""

    release_id: str
    parser_version: str
    artifact_manifest_sha256: str
    configuration_sha256: str
    release_pin_sha256: str
    available: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "release_id", _identifier(self.release_id, "release_id")
        )
        object.__setattr__(
            self,
            "parser_version",
            _printable(self.parser_version, "parser_version"),
        )
        for field in (
            "artifact_manifest_sha256",
            "configuration_sha256",
            "release_pin_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if not isinstance(self.available, bool):
            raise ReleaseSmokeGateError("rollback availability must be a boolean")


@dataclass(frozen=True, slots=True)
class FlowSmokeDecision:
    flow_id: str
    status: str
    blocking_reasons: tuple[SmokeBlockReason, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "flow_id", _identifier(self.flow_id, "flow_id"))
        if self.status not in {"pass", "block"}:
            raise ReleaseSmokeGateError("flow decision status is invalid")
        if not isinstance(self.blocking_reasons, tuple) or any(
            type(value) is not SmokeBlockReason for value in self.blocking_reasons
        ):
            raise ReleaseSmokeGateError("flow blocking reasons are invalid")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ReleaseSmokeGateError(
                "flow blocking reasons must be unique"
            )
        if (self.status == "pass") != (not self.blocking_reasons):
            raise ReleaseSmokeGateError(
                "flow status and blocking reasons are inconsistent"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "status": self.status,
            "blocking_reasons": [value.value for value in self.blocking_reasons],
        }


@dataclass(frozen=True, slots=True)
class ReleaseSmokeDecision:
    """Stable operational artifact; this type performs no promotion."""

    schema_version: str
    gate_id: str
    decision: str
    summary: str
    known_good_release_id: str
    known_good_release_pin_sha256: str
    candidate_release_id: str
    candidate_release_pin_sha256: str
    selected_release_id: str
    blocking_reasons: tuple[SmokeBlockReason, ...]
    flows: tuple[FlowSmokeDecision, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "parser-release-smoke-decision-v1":
            raise ReleaseSmokeGateError("unsupported release decision schema")
        object.__setattr__(self, "gate_id", _identifier(self.gate_id, "gate_id"))
        for field in (
            "known_good_release_id",
            "candidate_release_id",
            "selected_release_id",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        for field in (
            "known_good_release_pin_sha256",
            "candidate_release_pin_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if self.known_good_release_id == self.candidate_release_id:
            raise ReleaseSmokeGateError("release decision identities must differ")
        if self.known_good_release_pin_sha256 == self.candidate_release_pin_sha256:
            raise ReleaseSmokeGateError("release decision pin digests must differ")
        if not isinstance(self.blocking_reasons, tuple) or any(
            type(value) is not SmokeBlockReason for value in self.blocking_reasons
        ):
            raise ReleaseSmokeGateError("release blocking reasons are invalid")
        stable = tuple(sorted(set(self.blocking_reasons), key=lambda value: value.value))
        if stable != self.blocking_reasons:
            raise ReleaseSmokeGateError(
                "release blocking reasons must be sorted and unique"
            )
        if (
            not isinstance(self.flows, tuple)
            or not 1 <= len(self.flows) <= _MAX_FLOWS
            or any(type(value) is not FlowSmokeDecision for value in self.flows)
        ):
            raise ReleaseSmokeGateError("release flow decisions are invalid or empty")
        flow_ids = tuple(value.flow_id for value in self.flows)
        if flow_ids != tuple(sorted(flow_ids)) or len(flow_ids) != len(set(flow_ids)):
            raise ReleaseSmokeGateError(
                "release flow decisions must be sorted and unique"
            )
        flow_reasons = {reason for flow in self.flows for reason in flow.blocking_reasons}
        if not flow_reasons.issubset(set(self.blocking_reasons)):
            raise ReleaseSmokeGateError(
                "flow blockers must be represented in release blockers"
            )
        if self.decision == "pass":
            if (
                self.summary != "candidate_selected"
                or self.selected_release_id != self.candidate_release_id
                or self.blocking_reasons
                or any(flow.status != "pass" for flow in self.flows)
            ):
                raise ReleaseSmokeGateError("passing release decision is inconsistent")
        elif self.decision == "block":
            if (
                self.summary != "candidate_blocked_known_good_retained"
                or self.selected_release_id != self.known_good_release_id
                or not self.blocking_reasons
            ):
                raise ReleaseSmokeGateError("blocking release decision is inconsistent")
        else:
            raise ReleaseSmokeGateError("release decision must pass or block")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "decision": self.decision,
            "summary": self.summary,
            "known_good_release_id": self.known_good_release_id,
            "known_good_release_pin_sha256": self.known_good_release_pin_sha256,
            "candidate_release_id": self.candidate_release_id,
            "candidate_release_pin_sha256": self.candidate_release_pin_sha256,
            "selected_release_id": self.selected_release_id,
            "blocking_reasons": [value.value for value in self.blocking_reasons],
            "flows": [value.to_mapping() for value in self.flows],
        }

    def canonical_bytes(self) -> bytes:
        encoded = json.dumps(
            self.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_DECISION_BYTES:
            raise ReleaseSmokeGateError("release decision exceeds its byte cap")
        return encoded

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _bounded_smokes(
    values: Iterable[PublicFlowSmoke],
    field: str,
) -> tuple[PublicFlowSmoke, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise ReleaseSmokeGateError(f"{field} must be a smoke sequence")
    try:
        smokes = tuple(islice(iter(values), _MAX_FLOWS + 1))
    except TypeError as exc:
        raise ReleaseSmokeGateError(f"{field} must be a smoke sequence") from exc
    if len(smokes) > _MAX_FLOWS:
        raise ReleaseSmokeGateError(f"{field} exceeds 64 entries")
    if any(type(value) is not PublicFlowSmoke for value in smokes):
        raise ReleaseSmokeGateError(f"{field} contains an invalid smoke")
    return smokes


def _index_smokes(
    values: tuple[PublicFlowSmoke, ...],
) -> tuple[dict[str, PublicFlowSmoke], frozenset[str]]:
    indexed: dict[str, PublicFlowSmoke] = {}
    duplicates: set[str] = set()
    for value in values:
        if value.flow_id in indexed:
            duplicates.add(value.flow_id)
        else:
            indexed[value.flow_id] = value
    return indexed, frozenset(duplicates)


def evaluate_release_smoke_gate(
    *,
    spec: SmokeGateSpec,
    known_good: ReleasePin,
    candidate: ReleasePin,
    known_good_smokes: Iterable[PublicFlowSmoke],
    candidate_smokes: Iterable[PublicFlowSmoke],
    artifact_gate: BoundUpstreamGate,
    policy_gate: BoundUpstreamGate,
    rollback_target: RollbackTarget,
) -> ReleaseSmokeDecision:
    """Compare bounded functional evidence and retain known-good on any blocker."""

    for value, expected_type, field in (
        (spec, SmokeGateSpec, "spec"),
        (known_good, ReleasePin, "known_good"),
        (candidate, ReleasePin, "candidate"),
        (artifact_gate, BoundUpstreamGate, "artifact_gate"),
        (policy_gate, BoundUpstreamGate, "policy_gate"),
        (rollback_target, RollbackTarget, "rollback_target"),
    ):
        if type(value) is not expected_type:
            raise ReleaseSmokeGateError(f"{field} has the wrong contract type")
    if artifact_gate.gate != "artifact" or policy_gate.gate != "policy":
        raise ReleaseSmokeGateError("upstream gates are assigned to the wrong slots")
    if known_good.release_id == candidate.release_id or known_good == candidate:
        raise ReleaseSmokeGateError(
            "known-good and candidate release pins must be distinct"
        )

    baseline_values = _bounded_smokes(known_good_smokes, "known_good_smokes")
    candidate_values = _bounded_smokes(candidate_smokes, "candidate_smokes")
    baseline_by_flow, baseline_duplicates = _index_smokes(baseline_values)
    candidate_by_flow, candidate_duplicates = _index_smokes(candidate_values)
    all_reasons: set[SmokeBlockReason] = set()
    flow_decisions: list[FlowSmokeDecision] = []
    required_flow_ids = frozenset(spec.required_flow_ids)

    if baseline_duplicates:
        all_reasons.add(SmokeBlockReason.DUPLICATE_KNOWN_GOOD_SMOKE)
    if candidate_duplicates:
        all_reasons.add(SmokeBlockReason.DUPLICATE_CANDIDATE_SMOKE)
    if frozenset(baseline_by_flow).difference(required_flow_ids):
        all_reasons.add(SmokeBlockReason.UNEXPECTED_KNOWN_GOOD_SMOKE)
    if frozenset(candidate_by_flow).difference(required_flow_ids):
        all_reasons.add(SmokeBlockReason.UNEXPECTED_CANDIDATE_SMOKE)

    if candidate.api_schema_sha256 != known_good.api_schema_sha256:
        all_reasons.add(SmokeBlockReason.API_SCHEMA_INCOMPATIBLE)

    artifact_bound = (
        artifact_gate.release_id == candidate.release_id
        and artifact_gate.binding_sha256 == candidate.artifact_manifest_sha256
    )
    if not artifact_bound:
        all_reasons.add(SmokeBlockReason.ARTIFACT_GATE_UNBOUND)
    elif not artifact_gate.passed:
        all_reasons.add(SmokeBlockReason.ARTIFACT_GATE_FAILED)

    policy_bound = (
        policy_gate.release_id == candidate.release_id
        and policy_gate.binding_sha256 == candidate.policy_sha256
    )
    if not policy_bound:
        all_reasons.add(SmokeBlockReason.POLICY_GATE_UNBOUND)
    elif not policy_gate.passed:
        all_reasons.add(SmokeBlockReason.POLICY_GATE_FAILED)

    rollback_bound = (
        rollback_target.release_id == known_good.release_id
        and rollback_target.parser_version == known_good.parser_version
        and rollback_target.artifact_manifest_sha256
        == known_good.artifact_manifest_sha256
        and rollback_target.configuration_sha256 == known_good.configuration_sha256
        and rollback_target.release_pin_sha256 == known_good.sha256
    )
    if not rollback_bound:
        all_reasons.add(SmokeBlockReason.ROLLBACK_TARGET_MISMATCH)
    if not rollback_target.available:
        all_reasons.add(SmokeBlockReason.ROLLBACK_TARGET_UNAVAILABLE)

    for flow_id in spec.required_flow_ids:
        reasons: list[SmokeBlockReason] = []
        baseline = baseline_by_flow.get(flow_id)
        contender = candidate_by_flow.get(flow_id)
        if flow_id in baseline_duplicates:
            reasons.append(SmokeBlockReason.DUPLICATE_KNOWN_GOOD_SMOKE)
        if flow_id in candidate_duplicates:
            reasons.append(SmokeBlockReason.DUPLICATE_CANDIDATE_SMOKE)
        if baseline is None:
            reasons.append(SmokeBlockReason.KNOWN_GOOD_SMOKE_MISSING)
        else:
            if (
                baseline.release_id != known_good.release_id
                or baseline.release_pin_sha256 != known_good.sha256
            ):
                reasons.append(SmokeBlockReason.KNOWN_GOOD_EVIDENCE_UNBOUND)
            if not baseline.parsing_succeeded:
                reasons.append(SmokeBlockReason.KNOWN_GOOD_SMOKE_FAILED)
            if not baseline.core_content_present:
                reasons.append(SmokeBlockReason.KNOWN_GOOD_CORE_CONTENT_MISSING)
        if contender is None:
            reasons.append(SmokeBlockReason.CANDIDATE_SMOKE_MISSING)
        else:
            if (
                contender.release_id != candidate.release_id
                or contender.release_pin_sha256 != candidate.sha256
            ):
                reasons.append(SmokeBlockReason.CANDIDATE_EVIDENCE_UNBOUND)
            if not contender.parsing_succeeded:
                reasons.append(SmokeBlockReason.CANDIDATE_PARSE_FAILED)
            elif baseline is not None:
                if contender.http_status != baseline.http_status:
                    reasons.append(SmokeBlockReason.FUNCTIONAL_STATUS_REGRESSION)
                if (
                    contender.response_schema_sha256
                    != baseline.response_schema_sha256
                ):
                    reasons.append(SmokeBlockReason.RESPONSE_SCHEMA_INCOMPATIBLE)
                if not contender.core_content_present:
                    reasons.append(SmokeBlockReason.CANDIDATE_CORE_CONTENT_MISSING)
                elif contender.core_content_sha256 != baseline.core_content_sha256:
                    reasons.append(
                        SmokeBlockReason.CANDIDATE_CORE_CONTENT_REGRESSION
                    )
        stable_reasons = tuple(dict.fromkeys(reasons))
        all_reasons.update(stable_reasons)
        flow_decisions.append(
            FlowSmokeDecision(
                flow_id=flow_id,
                status="pass" if not stable_reasons else "block",
                blocking_reasons=stable_reasons,
            )
        )

    blocking = tuple(sorted(all_reasons, key=lambda value: value.value))
    passed = not blocking
    decision = ReleaseSmokeDecision(
        schema_version="parser-release-smoke-decision-v1",
        gate_id=spec.gate_id,
        decision="pass" if passed else "block",
        summary=(
            "candidate_selected"
            if passed
            else "candidate_blocked_known_good_retained"
        ),
        known_good_release_id=known_good.release_id,
        known_good_release_pin_sha256=known_good.sha256,
        candidate_release_id=candidate.release_id,
        candidate_release_pin_sha256=candidate.sha256,
        selected_release_id=(
            candidate.release_id if passed else known_good.release_id
        ),
        blocking_reasons=blocking,
        flows=tuple(flow_decisions),
    )
    decision.canonical_bytes()
    return decision


__all__ = [
    "BoundUpstreamGate",
    "FlowSmokeDecision",
    "PublicFlowSmoke",
    "ReleasePin",
    "ReleaseSmokeDecision",
    "ReleaseSmokeGateError",
    "RollbackTarget",
    "SmokeBlockReason",
    "SmokeGateSpec",
    "evaluate_release_smoke_gate",
]
