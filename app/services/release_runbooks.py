"""Machine-checkable Phase 08 release and rollback runbooks.

The contracts in this module are deliberately operationally inert.  A
runbook contains only allowlisted actions and a dry-run walker; it cannot
execute a shell command, contact a deployment platform, or mutate parser
configuration.  This keeps the release-first proof bounded while still
making ownership, ordering, stop conditions, evidence, and the exact
known-good target testable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from app.services.release_smoke_gate import (
    ReleasePin,
    ReleaseSmokeDecision,
)


_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_STEPS = 32
_MAX_TEXT = 256
_MAX_MANIFEST_BYTES = 131_072
_MAX_EVIDENCE_FILE_BYTES = 2_097_152


class RunbookValidationError(ValueError):
    """Raised when a runbook is incomplete, ambiguous, or unbounded."""


class RunbookKind(StrEnum):
    RELEASE = "release"
    ROLLBACK = "rollback"


class RunbookOwner(StrEnum):
    RELEASE = "release_owner"
    ARTIFACT = "artifact_owner"
    PRIVACY = "privacy_owner"
    API = "api_owner"
    ROLLBACK = "rollback_owner"


class RunbookAction(StrEnum):
    """Finite dry-run actions; arbitrary commands are intentionally absent."""

    RELEASE_PREFLIGHT = "release_preflight"
    VERIFY_ARTIFACTS = "verify_artifacts"
    VERIFY_HOSTED_POLICY = "verify_hosted_policy"
    VERIFY_SAFE_DEFAULTS = "verify_safe_defaults"
    VERIFY_SMOKE_GATE = "verify_smoke_gate"
    SELECT_CANDIDATE_NONPROD = "select_candidate_nonprod"
    VERIFY_CANDIDATE_FLOWS = "verify_candidate_flows"
    RECORD_RELEASE_EVIDENCE = "record_release_evidence"

    REQUEST_CANDIDATE_STOP = "request_candidate_stop"
    ENABLE_GLOBAL_KILL_SWITCH = "enable_global_kill_switch"
    RESTORE_KNOWN_GOOD_FLAGS = "restore_known_good_flags"
    SELECT_KNOWN_GOOD_ARTIFACTS = "select_known_good_artifacts"
    RESTORE_KNOWN_GOOD_POLICY = "restore_known_good_policy"
    VERIFY_KNOWN_GOOD_ARTIFACTS = "verify_known_good_artifacts"
    VERIFY_KNOWN_GOOD_FLOWS = "verify_known_good_flows"
    RECORD_ROLLBACK_EVIDENCE = "record_rollback_evidence"


class RollbackTrigger(StrEnum):
    SMOKE_GATE_BLOCK = "smoke_gate_block"
    OPERATOR_REQUEST = "operator_request"


_REQUIRED_ACTIONS: dict[RunbookKind, tuple[RunbookAction, ...]] = {
    RunbookKind.RELEASE: (
        RunbookAction.RELEASE_PREFLIGHT,
        RunbookAction.VERIFY_ARTIFACTS,
        RunbookAction.VERIFY_HOSTED_POLICY,
        RunbookAction.VERIFY_SAFE_DEFAULTS,
        RunbookAction.VERIFY_SMOKE_GATE,
        RunbookAction.SELECT_CANDIDATE_NONPROD,
        RunbookAction.VERIFY_CANDIDATE_FLOWS,
        RunbookAction.RECORD_RELEASE_EVIDENCE,
    ),
    RunbookKind.ROLLBACK: (
        RunbookAction.REQUEST_CANDIDATE_STOP,
        RunbookAction.ENABLE_GLOBAL_KILL_SWITCH,
        RunbookAction.RESTORE_KNOWN_GOOD_FLAGS,
        RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS,
        RunbookAction.RESTORE_KNOWN_GOOD_POLICY,
        RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS,
        RunbookAction.VERIFY_KNOWN_GOOD_FLOWS,
        RunbookAction.RECORD_ROLLBACK_EVIDENCE,
    ),
}
_ACTION_OWNERS: dict[RunbookAction, RunbookOwner] = {
    RunbookAction.RELEASE_PREFLIGHT: RunbookOwner.RELEASE,
    RunbookAction.VERIFY_ARTIFACTS: RunbookOwner.ARTIFACT,
    RunbookAction.VERIFY_HOSTED_POLICY: RunbookOwner.PRIVACY,
    RunbookAction.VERIFY_SAFE_DEFAULTS: RunbookOwner.RELEASE,
    RunbookAction.VERIFY_SMOKE_GATE: RunbookOwner.RELEASE,
    RunbookAction.SELECT_CANDIDATE_NONPROD: RunbookOwner.RELEASE,
    RunbookAction.VERIFY_CANDIDATE_FLOWS: RunbookOwner.API,
    RunbookAction.RECORD_RELEASE_EVIDENCE: RunbookOwner.RELEASE,
    RunbookAction.REQUEST_CANDIDATE_STOP: RunbookOwner.ROLLBACK,
    RunbookAction.ENABLE_GLOBAL_KILL_SWITCH: RunbookOwner.ROLLBACK,
    RunbookAction.RESTORE_KNOWN_GOOD_FLAGS: RunbookOwner.RELEASE,
    RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS: RunbookOwner.ARTIFACT,
    RunbookAction.RESTORE_KNOWN_GOOD_POLICY: RunbookOwner.PRIVACY,
    RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS: RunbookOwner.ARTIFACT,
    RunbookAction.VERIFY_KNOWN_GOOD_FLOWS: RunbookOwner.API,
    RunbookAction.RECORD_ROLLBACK_EVIDENCE: RunbookOwner.ROLLBACK,
}


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise RunbookValidationError(f"{field} must be a bounded identifier")
    return value


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RunbookValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _text(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TEXT
        or value != value.strip()
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RunbookValidationError(f"{field} must be bounded printable text")
    return value


def _enum(value: object, enum_type: type[StrEnum], field: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise RunbookValidationError(f"{field} is not allowlisted") from exc


@dataclass(frozen=True, slots=True)
class RunbookStep:
    step_id: str
    owner: RunbookOwner
    prerequisites: tuple[str, ...]
    action: RunbookAction
    expected_result: str
    abort_condition: str
    evidence_key: str
    next_approval: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _identifier(self.step_id, "step_id"))
        object.__setattr__(
            self, "owner", _enum(self.owner, RunbookOwner, "owner")
        )
        if not isinstance(self.prerequisites, tuple):
            raise RunbookValidationError("prerequisites must be an ordered tuple")
        prerequisites = tuple(
            _identifier(value, "prerequisite") for value in self.prerequisites
        )
        if len(prerequisites) != len(set(prerequisites)):
            raise RunbookValidationError("prerequisites must be unique")
        if self.step_id in prerequisites:
            raise RunbookValidationError("a step cannot depend on itself")
        object.__setattr__(self, "prerequisites", prerequisites)
        object.__setattr__(
            self, "action", _enum(self.action, RunbookAction, "action")
        )
        for field in ("expected_result", "abort_condition"):
            object.__setattr__(self, field, _text(getattr(self, field), field))
        object.__setattr__(
            self, "evidence_key", _identifier(self.evidence_key, "evidence_key")
        )
        approval = self.next_approval
        if approval != "complete":
            approval = _enum(approval, RunbookOwner, "next_approval").value
        object.__setattr__(self, "next_approval", approval)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "owner": self.owner.value,
            "prerequisites": list(self.prerequisites),
            "action": self.action.value,
            "expected_result": self.expected_result,
            "abort_condition": self.abort_condition,
            "evidence_key": self.evidence_key,
            "next_approval": self.next_approval,
        }


@dataclass(frozen=True, slots=True)
class RunbookManifest:
    schema_version: str
    runbook_id: str
    kind: RunbookKind
    environment: str
    known_good_release_id: str
    known_good_release_pin_sha256: str
    candidate_release_id: str
    candidate_release_pin_sha256: str
    smoke_gate_id: str
    steps: tuple[RunbookStep, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "parser-release-runbook-v1":
            raise RunbookValidationError("unsupported runbook schema version")
        object.__setattr__(
            self, "runbook_id", _identifier(self.runbook_id, "runbook_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, RunbookKind, "kind"))
        if self.environment != "non_production":
            raise RunbookValidationError(
                "release-first runbooks are restricted to non_production"
            )
        for field in ("known_good_release_id", "candidate_release_id", "smoke_gate_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        for field in (
            "known_good_release_pin_sha256",
            "candidate_release_pin_sha256",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if self.known_good_release_id == self.candidate_release_id:
            raise RunbookValidationError("candidate and known-good releases must differ")
        if self.known_good_release_pin_sha256 == self.candidate_release_pin_sha256:
            raise RunbookValidationError("candidate and known-good pins must differ")
        if (
            not isinstance(self.steps, tuple)
            or not 1 <= len(self.steps) <= _MAX_STEPS
            or any(type(step) is not RunbookStep for step in self.steps)
        ):
            raise RunbookValidationError("runbook steps are invalid or unbounded")
        self._validate_steps()

    def _validate_steps(self) -> None:
        ids = tuple(step.step_id for step in self.steps)
        if len(ids) != len(set(ids)):
            raise RunbookValidationError("runbook step identifiers must be unique")
        evidence = tuple(step.evidence_key for step in self.steps)
        if len(evidence) != len(set(evidence)):
            raise RunbookValidationError("runbook evidence keys must be unique")
        actions = tuple(step.action for step in self.steps)
        if actions != _REQUIRED_ACTIONS[self.kind]:
            raise RunbookValidationError(
                "runbook actions are missing, stale, duplicated, or out of order"
            )
        prior: set[str] = set()
        for index, step in enumerate(self.steps):
            unknown = set(step.prerequisites).difference(ids)
            if unknown:
                raise RunbookValidationError("runbook has an unknown prerequisite")
            if not set(step.prerequisites).issubset(prior):
                raise RunbookValidationError(
                    "runbook prerequisite is cyclic or appears after its dependent step"
                )
            if index == 0 and step.prerequisites:
                raise RunbookValidationError("the first runbook step has a prerequisite")
            if index and self.steps[index - 1].step_id not in step.prerequisites:
                raise RunbookValidationError(
                    "each runbook step must depend on the previous ordered step"
                )
            if step.owner is not _ACTION_OWNERS[step.action]:
                raise RunbookValidationError(
                    "runbook action is assigned to the wrong owner"
                )
            if index == len(self.steps) - 1:
                if step.next_approval != "complete":
                    raise RunbookValidationError(
                        "the final runbook step must close approval"
                    )
            elif step.next_approval == "complete":
                raise RunbookValidationError(
                    "a non-final runbook step cannot close approval"
                )
            elif step.next_approval != self.steps[index + 1].owner.value:
                raise RunbookValidationError(
                    "next approval does not match the next step owner"
                )
            prior.add(step.step_id)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runbook_id": self.runbook_id,
            "kind": self.kind.value,
            "environment": self.environment,
            "known_good_release_id": self.known_good_release_id,
            "known_good_release_pin_sha256": self.known_good_release_pin_sha256,
            "candidate_release_id": self.candidate_release_id,
            "candidate_release_pin_sha256": self.candidate_release_pin_sha256,
            "smoke_gate_id": self.smoke_gate_id,
            "steps": [step.to_mapping() for step in self.steps],
        }

    def canonical_bytes(self) -> bytes:
        encoded = json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > _MAX_MANIFEST_BYTES:
            raise RunbookValidationError("runbook manifest exceeds its byte cap")
        return encoded

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class RunbookDryRunResult:
    runbook_id: str
    status: str
    selected_release_id: str
    completed_actions: tuple[RunbookAction, ...]
    blocked_step_id: str | None
    reason: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "runbook_id": self.runbook_id,
            "status": self.status,
            "selected_release_id": self.selected_release_id,
            "completed_actions": [action.value for action in self.completed_actions],
            "blocked_step_id": self.blocked_step_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class VerifiedReleasePins:
    """Complete non-production pins whose declared local evidence was checked."""

    known_good: ReleasePin
    candidate: ReleasePin
    evidence_sha256: str


_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "runbook_id",
        "kind",
        "environment",
        "known_good_release_id",
        "known_good_release_pin_sha256",
        "candidate_release_id",
        "candidate_release_pin_sha256",
        "smoke_gate_id",
        "steps",
    }
)
_STEP_FIELDS = frozenset(
    {
        "step_id",
        "owner",
        "prerequisites",
        "action",
        "expected_result",
        "abort_condition",
        "evidence_key",
        "next_approval",
    }
)


def runbook_from_mapping(value: Mapping[str, Any]) -> RunbookManifest:
    """Strictly decode a runbook mapping, rejecting command-like extras."""

    if not isinstance(value, Mapping) or frozenset(value) != _MANIFEST_FIELDS:
        raise RunbookValidationError("runbook fields are incomplete or unsupported")
    raw_steps = value["steps"]
    if not isinstance(raw_steps, list) or len(raw_steps) > _MAX_STEPS:
        raise RunbookValidationError("runbook steps must be a bounded JSON array")
    steps: list[RunbookStep] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, Mapping) or frozenset(raw_step) != _STEP_FIELDS:
            raise RunbookValidationError("runbook step fields are incomplete or unsupported")
        prerequisites = raw_step["prerequisites"]
        if not isinstance(prerequisites, list):
            raise RunbookValidationError("prerequisites must be a JSON array")
        steps.append(
            RunbookStep(
                step_id=raw_step["step_id"],
                owner=raw_step["owner"],
                prerequisites=tuple(prerequisites),
                action=raw_step["action"],
                expected_result=raw_step["expected_result"],
                abort_condition=raw_step["abort_condition"],
                evidence_key=raw_step["evidence_key"],
                next_approval=raw_step["next_approval"],
            )
        )
    return RunbookManifest(
        schema_version=value["schema_version"],
        runbook_id=value["runbook_id"],
        kind=value["kind"],
        environment=value["environment"],
        known_good_release_id=value["known_good_release_id"],
        known_good_release_pin_sha256=value["known_good_release_pin_sha256"],
        candidate_release_id=value["candidate_release_id"],
        candidate_release_pin_sha256=value["candidate_release_pin_sha256"],
        smoke_gate_id=value["smoke_gate_id"],
        steps=tuple(steps),
    )


def load_runbook(path: Path) -> RunbookManifest:
    """Load one bounded local JSON runbook; no URI or network source is accepted."""

    if not isinstance(path, Path) or not path.is_file() or path.is_symlink():
        raise RunbookValidationError("runbook path must be a regular local file")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise RunbookValidationError("runbook file exceeds its byte cap")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunbookValidationError("runbook JSON is unreadable") from exc
    return runbook_from_mapping(value)


def load_verified_release_pins(path: Path, *, repository_root: Path) -> VerifiedReleasePins:
    """Load the checked-in non-production pins and verify every local identity.

    This is intentionally a small repository-evidence verifier, not a release
    artifact verifier.  US08 remains authoritative for shipped artifact bytes;
    here we prove that the runbook does not contain invented or unavailable
    hashes and that its complete pins are locally resolvable.
    """

    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise RunbookValidationError("release pin path must be a regular local file")
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise RunbookValidationError("release pin evidence exceeds its byte cap")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunbookValidationError("release pin evidence is unreadable") from exc
    expected_top = {
        "schema_version",
        "environment",
        "known_good",
        "candidate",
        "evidence",
    }
    if not isinstance(value, Mapping) or set(value) != expected_top:
        raise RunbookValidationError("release pin evidence fields are invalid")
    if (
        value["schema_version"] != "parser-nonproduction-release-pins-v1"
        or value["environment"] != "non_production"
    ):
        raise RunbookValidationError("release pin evidence is not non-production v1")
    pin_fields = {
        "release_id",
        "parser_version",
        "artifact_manifest_sha256",
        "configuration_sha256",
        "api_schema_sha256",
        "policy_sha256",
    }

    def decode_pin(raw_pin: object) -> ReleasePin:
        if not isinstance(raw_pin, Mapping) or set(raw_pin) != pin_fields:
            raise RunbookValidationError("release pin fields are invalid")
        try:
            return ReleasePin(**dict(raw_pin))
        except (TypeError, ValueError) as exc:
            raise RunbookValidationError("release pin is invalid") from exc

    known_good = decode_pin(value["known_good"])
    candidate = decode_pin(value["candidate"])
    if known_good.release_id == candidate.release_id or known_good == candidate:
        raise RunbookValidationError("release pins must be distinct")
    from app import __version__

    if (
        known_good.parser_version != __version__
        or candidate.parser_version != __version__
    ):
        raise RunbookValidationError("release pin parser version is not locally resolvable")
    evidence = value["evidence"]
    evidence_fields = {
        "artifact_manifest",
        "known_good_configuration",
        "candidate_configuration",
        "api_schema",
        "known_good_policy",
        "candidate_policy",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != evidence_fields:
        raise RunbookValidationError("release pin source evidence is invalid")
    root = repository_root.resolve(strict=True)

    def local_file(relative: object) -> Path:
        if not isinstance(relative, str) or not relative or len(relative) > _MAX_TEXT:
            raise RunbookValidationError("release pin evidence path is invalid")
        candidate_path = root / relative
        if candidate_path.is_symlink() or not candidate_path.is_file():
            raise RunbookValidationError("release pin evidence file is unavailable")
        resolved = candidate_path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise RunbookValidationError("release pin evidence escapes the repository")
        if resolved.stat().st_size > _MAX_EVIDENCE_FILE_BYTES:
            raise RunbookValidationError("release pin evidence file exceeds its byte cap")
        return resolved

    from app.services.artifact_manifest import load_manifest

    artifact_manifest = load_manifest(local_file(evidence["artifact_manifest"]))
    artifact_manifest.assert_authentic()
    if (
        known_good.artifact_manifest_sha256 != artifact_manifest.manifest_sha256
        or candidate.artifact_manifest_sha256 != artifact_manifest.manifest_sha256
    ):
        raise RunbookValidationError("release pin artifact identity is unbound")

    def file_digest(key: str) -> str:
        return hashlib.sha256(local_file(evidence[key]).read_bytes()).hexdigest()

    if known_good.configuration_sha256 != file_digest("known_good_configuration"):
        raise RunbookValidationError("known-good configuration identity is unbound")
    if candidate.configuration_sha256 != file_digest("candidate_configuration"):
        raise RunbookValidationError("candidate configuration identity is unbound")
    if known_good.policy_sha256 != file_digest("known_good_policy"):
        raise RunbookValidationError("known-good policy identity is unbound")
    if candidate.policy_sha256 != file_digest("candidate_policy"):
        raise RunbookValidationError("candidate policy identity is unbound")
    if evidence["api_schema"] != "runtime:app.main:app.openapi":
        raise RunbookValidationError("API schema evidence source is unsupported")
    from app.main import app

    api_digest = hashlib.sha256(
        json.dumps(app.openapi(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if (
        known_good.api_schema_sha256 != api_digest
        or candidate.api_schema_sha256 != api_digest
    ):
        raise RunbookValidationError("release pin API schema identity is unbound")
    return VerifiedReleasePins(
        known_good=known_good,
        candidate=candidate,
        evidence_sha256=hashlib.sha256(raw).hexdigest(),
    )


def validate_runbook_pair(
    release: RunbookManifest,
    rollback: RunbookManifest,
) -> None:
    """Require release and rollback manifests to bind the same exact pins."""

    if type(release) is not RunbookManifest or type(rollback) is not RunbookManifest:
        raise RunbookValidationError("runbook pair has the wrong contract type")
    if release.kind is not RunbookKind.RELEASE or rollback.kind is not RunbookKind.ROLLBACK:
        raise RunbookValidationError("runbook pair must contain release then rollback")
    fields = (
        "known_good_release_id",
        "known_good_release_pin_sha256",
        "candidate_release_id",
        "candidate_release_pin_sha256",
        "smoke_gate_id",
        "environment",
    )
    if any(getattr(release, field) != getattr(rollback, field) for field in fields):
        raise RunbookValidationError("release and rollback runbooks bind different targets")


def _validate_bindings(
    runbook: RunbookManifest,
    known_good: ReleasePin,
    candidate: ReleasePin,
) -> None:
    if type(runbook) is not RunbookManifest:
        raise RunbookValidationError("runbook has the wrong contract type")
    if type(known_good) is not ReleasePin or type(candidate) is not ReleasePin:
        raise RunbookValidationError("release pin has the wrong contract type")
    if (
        runbook.known_good_release_id != known_good.release_id
        or runbook.known_good_release_pin_sha256 != known_good.sha256
        or runbook.candidate_release_id != candidate.release_id
        or runbook.candidate_release_pin_sha256 != candidate.sha256
    ):
        raise RunbookValidationError("runbook is not bound to the supplied release pins")


def _walk(
    runbook: RunbookManifest,
    evidence: Mapping[str, bool],
    *,
    initial_release_id: str,
    success_release_id: str,
    failure_release_id: str | None = None,
) -> RunbookDryRunResult:
    if not isinstance(evidence, Mapping) or len(evidence) > _MAX_STEPS:
        raise RunbookValidationError("dry-run evidence is invalid or unbounded")
    required_evidence = frozenset(step.evidence_key for step in runbook.steps)
    if frozenset(evidence) != required_evidence:
        raise RunbookValidationError(
            "dry-run evidence keys must exactly match the runbook"
        )
    completed: list[RunbookAction] = []
    selected = initial_release_id
    blocked_selection = (
        initial_release_id if failure_release_id is None else failure_release_id
    )
    for step in runbook.steps:
        outcome = evidence.get(step.evidence_key)
        if type(outcome) is not bool:
            return RunbookDryRunResult(
                runbook_id=runbook.runbook_id,
                status="block",
                selected_release_id=blocked_selection,
                completed_actions=tuple(completed),
                blocked_step_id=step.step_id,
                reason="evidence_missing_or_failed",
            )
        if not outcome:
            return RunbookDryRunResult(
                runbook_id=runbook.runbook_id,
                status="block",
                selected_release_id=blocked_selection,
                completed_actions=tuple(completed),
                blocked_step_id=step.step_id,
                reason="abort_condition_met",
            )
        completed.append(step.action)
        if step.action is RunbookAction.SELECT_CANDIDATE_NONPROD:
            selected = success_release_id
        elif step.action is RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS:
            selected = success_release_id
        if failure_release_id is None:
            blocked_selection = selected
    return RunbookDryRunResult(
        runbook_id=runbook.runbook_id,
        status="pass",
        selected_release_id=success_release_id,
        completed_actions=tuple(completed),
        blocked_step_id=None,
        reason="dry_run_complete",
    )


def dry_run_release(
    runbook: RunbookManifest,
    *,
    known_good: ReleasePin,
    candidate: ReleasePin,
    smoke_decision: ReleaseSmokeDecision,
    evidence: Mapping[str, bool],
) -> RunbookDryRunResult:
    """Walk the release happy path only when the exact US10 decision passes."""

    _validate_bindings(runbook, known_good, candidate)
    if runbook.kind is not RunbookKind.RELEASE:
        raise RunbookValidationError("release dry-run received a rollback runbook")
    if type(smoke_decision) is not ReleaseSmokeDecision:
        raise RunbookValidationError("smoke decision has the wrong contract type")
    if (
        smoke_decision.gate_id != runbook.smoke_gate_id
        or smoke_decision.known_good_release_id != known_good.release_id
        or smoke_decision.known_good_release_pin_sha256 != known_good.sha256
        or smoke_decision.candidate_release_id != candidate.release_id
        or smoke_decision.candidate_release_pin_sha256 != candidate.sha256
        or smoke_decision.decision != "pass"
        or smoke_decision.selected_release_id != candidate.release_id
    ):
        return RunbookDryRunResult(
            runbook_id=runbook.runbook_id,
            status="block",
            selected_release_id=known_good.release_id,
            completed_actions=(),
            blocked_step_id=runbook.steps[0].step_id,
            reason="smoke_gate_not_passed_or_unbound",
        )
    return _walk(
        runbook,
        evidence,
        initial_release_id=known_good.release_id,
        success_release_id=candidate.release_id,
        failure_release_id=known_good.release_id,
    )


def dry_run_rollback(
    runbook: RunbookManifest,
    *,
    known_good: ReleasePin,
    candidate: ReleasePin,
    trigger: RollbackTrigger,
    evidence: Mapping[str, bool],
) -> RunbookDryRunResult:
    """Walk the documented rollback to the exact known-good identity."""

    _validate_bindings(runbook, known_good, candidate)
    if runbook.kind is not RunbookKind.ROLLBACK:
        raise RunbookValidationError("rollback dry-run received a release runbook")
    _enum(trigger, RollbackTrigger, "rollback_trigger")
    return _walk(
        runbook,
        evidence,
        initial_release_id=candidate.release_id,
        success_release_id=known_good.release_id,
    )


__all__ = [
    "RollbackTrigger",
    "RunbookAction",
    "RunbookDryRunResult",
    "RunbookKind",
    "RunbookManifest",
    "RunbookOwner",
    "RunbookStep",
    "RunbookValidationError",
    "VerifiedReleasePins",
    "dry_run_release",
    "dry_run_rollback",
    "load_runbook",
    "load_verified_release_pins",
    "runbook_from_mapping",
    "validate_runbook_pair",
]
