"""One bounded, in-memory Phase 08 non-production rollback smoke.

This module deliberately has no deployment, process, filesystem mutation, or
network interface.  It enables a pinned candidate control snapshot in memory,
checks content-free representative flow fingerprints, injects one ordinary
functional failure, walks the exact US11 rollback actions, and verifies that
the complete known-good selection is restored.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from app.config import Settings
from app.services.feature_flags import shipping_flag_registry
from app.services.release_runbooks import (
    RollbackTrigger,
    RunbookAction,
    RunbookKind,
    RunbookManifest,
    dry_run_rollback,
)
from app.services.release_smoke_gate import ReleasePin
from app.services.artifact_manifest import (
    ArtifactManifest,
    LOCAL_REFERENCE_ARTIFACT_PROFILE,
    ManifestVerification,
    is_release_verification_attested,
)


_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_FLOWS = 16
_MAX_FLAGS = 64
_MAX_RECORD_BYTES = 131_072
_PHASE08_CONTROL_SETTINGS = frozenset(
    {
        "telemetry_enabled",
        "telemetry_resources_enabled",
        "telemetry_quality_enabled",
        "deterministic_confidence_enabled",
        "visual_confidence_enabled",
        "review_escalation_enabled",
    }
)
_ROLLBACK_ACTIONS = (
    RunbookAction.REQUEST_CANDIDATE_STOP,
    RunbookAction.ENABLE_GLOBAL_KILL_SWITCH,
    RunbookAction.RESTORE_KNOWN_GOOD_FLAGS,
    RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS,
    RunbookAction.RESTORE_KNOWN_GOOD_POLICY,
    RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS,
    RunbookAction.VERIFY_KNOWN_GOOD_FLOWS,
    RunbookAction.RECORD_ROLLBACK_EVIDENCE,
)
_FLOW_CONTRACT_AUTHORITY = object()
_FLOW_CONTRACT_SHA256 = (
    "5571466fb46f4dc54712532ce0f1ce9ea82f5302949d0ce23510b19c14e72901"
)


class RollbackSmokeError(ValueError):
    """Raised when the non-production smoke declaration is unsafe."""


@dataclass(slots=True)
class _InMemoryCallGate:
    """Bounded proof that one admission attempt invokes only an active route."""

    attempts: int = 0
    calls: int = 0

    def attempt(self, *, active: bool) -> None:
        if self.attempts >= 1:
            raise RollbackSmokeError("call-gate attempt exceeds the smoke bound")
        self.attempts += 1
        if active:
            self.calls += 1


class FlowOutcome(StrEnum):
    SUCCESS = "success"
    ORDINARY_FAILURE = "ordinary_failure"


class SmokeStatus(StrEnum):
    PASS = "pass"
    BLOCK = "block"


class SmokeBlockReason(StrEnum):
    CANDIDATE_CONTROLS_NOT_ENABLED = "candidate_controls_not_enabled"
    CANDIDATE_FLOW_MISMATCH = "candidate_flow_mismatch"
    INJECTION_NOT_DETECTED = "injection_not_detected"
    RUNBOOK_BLOCKED = "runbook_blocked"
    ARTIFACT_VERIFICATION_INVALID = "artifact_verification_invalid"
    RESTORE_MISMATCH = "restore_mismatch"


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise RollbackSmokeError(f"{field} must be a bounded identifier")
    return value


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise RollbackSmokeError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class ShippingFlagState:
    setting: str
    enabled: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "setting", _identifier(self.setting, "flag setting"))
        if type(self.enabled) is not bool:
            raise RollbackSmokeError("flag enabled state must be boolean")

    def to_mapping(self) -> dict[str, Any]:
        return {"setting": self.setting, "enabled": self.enabled}


@dataclass(frozen=True, slots=True)
class ShippingFlagSnapshot:
    global_kill_switch: bool
    disabled_capabilities: tuple[str, ...]
    flags: tuple[ShippingFlagState, ...]
    source_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.global_kill_switch) is not bool:
            raise RollbackSmokeError("global kill-switch state must be boolean")
        if not isinstance(self.disabled_capabilities, tuple):
            raise RollbackSmokeError("disabled capabilities must be a tuple")
        disabled = tuple(
            _identifier(value, "disabled capability")
            for value in self.disabled_capabilities
        )
        if disabled != tuple(sorted(set(disabled))):
            raise RollbackSmokeError("disabled capabilities must be sorted and unique")
        registry = shipping_flag_registry()
        if set(disabled).difference(registry.capabilities):
            raise RollbackSmokeError("disabled capabilities contain an unknown value")
        object.__setattr__(self, "disabled_capabilities", disabled)
        if self.source_sha256 is not None:
            object.__setattr__(
                self,
                "source_sha256",
                _digest(self.source_sha256, "flag profile source_sha256"),
            )
        if (
            not isinstance(self.flags, tuple)
            or not 1 <= len(self.flags) <= _MAX_FLAGS
            or any(type(value) is not ShippingFlagState for value in self.flags)
        ):
            raise RollbackSmokeError("flag snapshot is invalid or unbounded")
        settings = tuple(value.setting for value in self.flags)
        expected = tuple(sorted(flag.setting for flag in registry.flags))
        if settings != expected:
            raise RollbackSmokeError("flag snapshot must cover the exact shipping registry")
        enabled = {value.setting: value.enabled for value in self.flags}
        if self.global_kill_switch and any(enabled.values()):
            raise RollbackSmokeError("a killed flag snapshot cannot contain enabled flags")
        for flag in registry.flags:
            if enabled[flag.setting] and any(
                not enabled[dependency] for dependency in flag.dependencies
            ):
                raise RollbackSmokeError("flag snapshot has an enabled dependency gap")

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        source_sha256: str | None = None,
    ) -> "ShippingFlagSnapshot":
        if type(settings) is not Settings:
            raise RollbackSmokeError("flag snapshot requires concrete Settings")
        registry = shipping_flag_registry()
        effective = registry.resolve(settings)
        return cls(
            global_kill_switch=effective.parser_shipping_kill_switch,
            disabled_capabilities=tuple(
                sorted(effective.parser_shipping_disabled_capabilities)
            ),
            flags=tuple(
                ShippingFlagState(
                    setting=flag.setting,
                    enabled=bool(getattr(effective, flag.setting)),
                )
                for flag in sorted(registry.flags, key=lambda value: value.setting)
            ),
            source_sha256=source_sha256,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": "parser-shipping-flag-snapshot-v1",
            "global_kill_switch": self.global_kill_switch,
            "disabled_capabilities": list(self.disabled_capabilities),
            "flags": [value.to_mapping() for value in self.flags],
            "source_sha256": self.source_sha256,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.to_mapping(), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()

    def enabled_settings(self) -> frozenset[str]:
        return frozenset(value.setting for value in self.flags if value.enabled)


def load_shipping_flag_profile(path: Path) -> ShippingFlagSnapshot:
    """Load one bounded non-production flag profile into an effective snapshot."""

    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise RollbackSmokeError("flag profile must be a regular local file")
    if path.stat().st_size > 32_768:
        raise RollbackSmokeError("flag profile exceeds its byte cap")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RollbackSmokeError("flag profile is unreadable") from exc
    expected = {
        "schema_version",
        "profile_id",
        "environment",
        "global_kill_switch",
        "disabled_capabilities",
        "enabled_flags",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise RollbackSmokeError("flag profile fields are invalid")
    if (
        value["schema_version"] != "parser-nonproduction-flag-profile-v1"
        or value["environment"] != "non_production"
    ):
        raise RollbackSmokeError("flag profile is not non-production v1")
    _identifier(value["profile_id"], "flag profile_id")
    enabled = value["enabled_flags"]
    disabled = value["disabled_capabilities"]
    if not isinstance(enabled, list) or not isinstance(disabled, list):
        raise RollbackSmokeError("flag profile lists are invalid")
    normalized_enabled = tuple(_identifier(item, "enabled flag") for item in enabled)
    if normalized_enabled != tuple(sorted(set(normalized_enabled))):
        raise RollbackSmokeError("enabled flags must be sorted and unique")
    registry = shipping_flag_registry()
    registered = {flag.setting for flag in registry.flags}
    if set(normalized_enabled).difference(registered):
        raise RollbackSmokeError("flag profile enables an unknown setting")
    if type(value["global_kill_switch"]) is not bool or any(
        not isinstance(item, str) for item in disabled
    ):
        raise RollbackSmokeError("flag profile control values are invalid")
    try:
        settings = Settings(
            **{setting: True for setting in normalized_enabled},
            parser_shipping_kill_switch=value["global_kill_switch"],
            parser_shipping_disabled_capabilities=tuple(disabled),
        )
    except (TypeError, ValueError) as exc:
        raise RollbackSmokeError("flag profile is not a valid dependency profile") from exc
    snapshot = ShippingFlagSnapshot.from_settings(
        settings,
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
    if snapshot.enabled_settings() != frozenset(normalized_enabled):
        raise RollbackSmokeError("flag profile does not resolve to its declared settings")
    return snapshot


@dataclass(frozen=True, slots=True)
class HostedPolicySelection:
    profile_id: str
    hosted_enabled: bool
    default_decision: str
    maximum_transport_calls_on_denial: int
    required_gateway: str | None
    source_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _identifier(self.profile_id, "policy profile_id"))
        if type(self.hosted_enabled) is not bool:
            raise RollbackSmokeError("hosted policy enabled state is invalid")
        if self.default_decision != "deny":
            raise RollbackSmokeError("hosted policy must remain deny by default")
        if (
            type(self.maximum_transport_calls_on_denial) is not int
            or self.maximum_transport_calls_on_denial != 0
        ):
            raise RollbackSmokeError("hosted denial must allow zero transport calls")
        if self.required_gateway is not None:
            object.__setattr__(
                self,
                "required_gateway",
                _identifier(self.required_gateway, "required_gateway"),
            )
        if self.hosted_enabled and self.required_gateway != "manifest_bound_release_gateway":
            raise RollbackSmokeError("enabled hosted policy requires the release gateway")
        if not self.hosted_enabled and self.required_gateway is not None:
            raise RollbackSmokeError("disabled hosted policy cannot require a gateway")
        object.__setattr__(self, "source_sha256", _digest(self.source_sha256, "policy source_sha256"))


def load_hosted_policy_selection(path: Path) -> HostedPolicySelection:
    """Load one bounded, deny-by-default non-production policy selection."""

    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise RollbackSmokeError("hosted policy selection must be a regular local file")
    if path.stat().st_size > 32_768:
        raise RollbackSmokeError("hosted policy selection exceeds its byte cap")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RollbackSmokeError("hosted policy selection is unreadable") from exc
    common = {
        "schema_version",
        "profile_id",
        "environment",
        "hosted_enabled",
        "default_decision",
        "maximum_transport_calls_on_denial",
    }
    if not isinstance(value, Mapping) or frozenset(value) not in {
        frozenset(common),
        frozenset(common | {"required_gateway"}),
    }:
        raise RollbackSmokeError("hosted policy selection fields are invalid")
    if (
        value["schema_version"] != "parser-nonproduction-hosted-policy-selection-v1"
        or value["environment"] != "non_production"
    ):
        raise RollbackSmokeError("hosted policy selection is not non-production v1")
    return HostedPolicySelection(
        profile_id=value["profile_id"],
        hosted_enabled=value["hosted_enabled"],
        default_decision=value["default_decision"],
        maximum_transport_calls_on_denial=value[
            "maximum_transport_calls_on_denial"
        ],
        required_gateway=value.get("required_gateway"),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class RepresentativeFlow:
    flow_id: str
    release_pin_sha256: str
    outcome: FlowOutcome
    http_status: int
    response_schema_sha256: str
    canonical_output_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "flow_id", _identifier(self.flow_id, "flow_id"))
        object.__setattr__(
            self,
            "release_pin_sha256",
            _digest(self.release_pin_sha256, "release_pin_sha256"),
        )
        try:
            outcome = FlowOutcome(self.outcome)
        except (TypeError, ValueError) as exc:
            raise RollbackSmokeError("flow outcome is not allowlisted") from exc
        object.__setattr__(self, "outcome", outcome)
        if (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise RollbackSmokeError("flow HTTP status is outside its bound")
        if outcome is FlowOutcome.SUCCESS and not 200 <= self.http_status <= 299:
            raise RollbackSmokeError("successful flow must use a 2xx status")
        if outcome is FlowOutcome.ORDINARY_FAILURE and not 400 <= self.http_status <= 499:
            raise RollbackSmokeError("ordinary failure flow must use a 4xx status")
        for field in ("response_schema_sha256", "canonical_output_sha256"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))

    def compatible_identity(self) -> tuple[Any, ...]:
        return (
            self.flow_id,
            self.outcome,
            self.http_status,
            self.response_schema_sha256,
            self.canonical_output_sha256,
        )


@dataclass(frozen=True, slots=True)
class RepresentativeFlowContractEntry:
    flow_id: str
    outcome: FlowOutcome
    http_status: int
    response_schema_sha256: str
    canonical_output_sha256: str

    def __post_init__(self) -> None:
        probe = RepresentativeFlow(
            flow_id=self.flow_id,
            release_pin_sha256="0" * 64,
            outcome=self.outcome,
            http_status=self.http_status,
            response_schema_sha256=self.response_schema_sha256,
            canonical_output_sha256=self.canonical_output_sha256,
        )
        object.__setattr__(self, "flow_id", probe.flow_id)
        object.__setattr__(self, "outcome", probe.outcome)
        object.__setattr__(self, "response_schema_sha256", probe.response_schema_sha256)
        object.__setattr__(self, "canonical_output_sha256", probe.canonical_output_sha256)

    def compatible_identity(self) -> tuple[Any, ...]:
        return (
            self.flow_id,
            self.outcome,
            self.http_status,
            self.response_schema_sha256,
            self.canonical_output_sha256,
        )


@dataclass(frozen=True, slots=True)
class RepresentativeFlowContract:
    contract_id: str
    entries: tuple[RepresentativeFlowContractEntry, ...]
    source_sha256: str
    _authority: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _identifier(self.contract_id, "flow contract_id"))
        object.__setattr__(self, "source_sha256", _digest(self.source_sha256, "flow contract source_sha256"))
        if (
            not 2 <= len(self.entries) <= _MAX_FLOWS
            or any(type(value) is not RepresentativeFlowContractEntry for value in self.entries)
        ):
            raise RollbackSmokeError("flow contract entries are invalid or unbounded")
        ids = tuple(value.flow_id for value in self.entries)
        if ids != tuple(sorted(set(ids))):
            raise RollbackSmokeError("flow contract entries must be sorted and unique")
        if {value.outcome for value in self.entries} != {
            FlowOutcome.SUCCESS,
            FlowOutcome.ORDINARY_FAILURE,
        }:
            raise RollbackSmokeError("flow contract requires success and ordinary failure")


def load_representative_flow_contract(path: Path) -> RepresentativeFlowContract:
    """Load the bounded repository-owned representative-flow contract."""

    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise RollbackSmokeError("flow contract must be a regular local file")
    if path.stat().st_size > 32_768:
        raise RollbackSmokeError("flow contract exceeds its byte cap")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RollbackSmokeError("flow contract is unreadable") from exc
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if source_sha256 != _FLOW_CONTRACT_SHA256:
        raise RollbackSmokeError("flow contract differs from the pinned repository evidence")
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "contract_id",
        "environment",
        "flows",
    }:
        raise RollbackSmokeError("flow contract fields are invalid")
    if (
        value["schema_version"] != "parser-nonproduction-flow-contract-v1"
        or value["environment"] != "non_production"
        or not isinstance(value["flows"], list)
    ):
        raise RollbackSmokeError("flow contract is not non-production v1")
    fields = {
        "flow_id",
        "outcome",
        "http_status",
        "response_schema_sha256",
        "canonical_output_sha256",
    }
    entries = []
    for item in value["flows"]:
        if not isinstance(item, Mapping) or set(item) != fields:
            raise RollbackSmokeError("flow contract entry fields are invalid")
        entries.append(RepresentativeFlowContractEntry(**dict(item)))
    return RepresentativeFlowContract(
        contract_id=value["contract_id"],
        entries=tuple(entries),
        source_sha256=source_sha256,
        _authority=_FLOW_CONTRACT_AUTHORITY,
    )


@dataclass(frozen=True, slots=True)
class RollbackProfile:
    release: ReleasePin
    flags: ShippingFlagSnapshot
    hosted_policy: HostedPolicySelection
    artifact_profile_id: str
    flow_contract: RepresentativeFlowContract
    flows: tuple[RepresentativeFlow, ...]

    def __post_init__(self) -> None:
        if type(self.release) is not ReleasePin:
            raise RollbackSmokeError("rollback profile release pin is invalid")
        if type(self.flags) is not ShippingFlagSnapshot:
            raise RollbackSmokeError("rollback profile flags are invalid")
        if type(self.hosted_policy) is not HostedPolicySelection:
            raise RollbackSmokeError("rollback profile hosted policy is invalid")
        if self.flags.source_sha256 != self.release.configuration_sha256:
            raise RollbackSmokeError("flag profile is not bound to release configuration")
        if self.hosted_policy.source_sha256 != self.release.policy_sha256:
            raise RollbackSmokeError("hosted policy selection is not bound to release policy")
        object.__setattr__(
            self,
            "artifact_profile_id",
            _identifier(self.artifact_profile_id, "artifact_profile_id"),
        )
        if (
            type(self.flow_contract) is not RepresentativeFlowContract
            or self.flow_contract._authority is not _FLOW_CONTRACT_AUTHORITY
        ):
            raise RollbackSmokeError("representative flow contract is not repository-issued")
        if (
            not isinstance(self.flows, tuple)
            or not 2 <= len(self.flows) <= _MAX_FLOWS
            or any(type(value) is not RepresentativeFlow for value in self.flows)
        ):
            raise RollbackSmokeError("representative flows are invalid or unbounded")
        flow_ids = tuple(value.flow_id for value in self.flows)
        if flow_ids != tuple(sorted(flow_ids)) or len(flow_ids) != len(set(flow_ids)):
            raise RollbackSmokeError("representative flows must be sorted and unique")
        if any(value.release_pin_sha256 != self.release.sha256 for value in self.flows):
            raise RollbackSmokeError("representative flow is not bound to its release")
        if tuple(value.compatible_identity() for value in self.flows) != tuple(
            value.compatible_identity() for value in self.flow_contract.entries
        ):
            raise RollbackSmokeError("representative flows differ from their contract")
        if {value.outcome for value in self.flows} != {
            FlowOutcome.SUCCESS,
            FlowOutcome.ORDINARY_FAILURE,
        }:
            raise RollbackSmokeError(
                "representative flows require success and ordinary failure coverage"
            )


@dataclass(frozen=True, slots=True)
class RollbackSmokeSpec:
    smoke_id: str
    environment: str
    injection_flow_id: str
    injection: str = "ordinary_functional_failure"

    def __post_init__(self) -> None:
        object.__setattr__(self, "smoke_id", _identifier(self.smoke_id, "smoke_id"))
        if self.environment != "non_production":
            raise RollbackSmokeError("rollback smoke is restricted to non_production")
        object.__setattr__(
            self,
            "injection_flow_id",
            _identifier(self.injection_flow_id, "injection_flow_id"),
        )
        if self.injection != "ordinary_functional_failure":
            raise RollbackSmokeError("only the bounded ordinary failure is supported")


@dataclass(frozen=True, slots=True)
class RollbackSmokeRecord:
    schema_version: str
    smoke_id: str
    environment: str
    status: SmokeStatus
    injected_failure: str
    failure_detected: bool
    runbook_id: str
    runbook_sha256: str
    initial_candidate_pin_sha256: str
    expected_known_good_release_id: str
    expected_known_good_pin_sha256: str
    injected_flow_id: str
    injected_http_status: int
    selected_release_id: str
    restored_release_pin_sha256: str | None
    restored_flag_snapshot_sha256: str | None
    restored_artifact_manifest_sha256: str | None
    restored_configuration_sha256: str | None
    restored_policy_sha256: str | None
    restored_flow_set_sha256: str | None
    hosted_transport_attempts: int
    hosted_transport_calls: int
    post_stop_candidate_attempts: int
    post_stop_candidate_calls: int
    restored_flow_ids: tuple[str, ...]
    completed_actions: tuple[RunbookAction, ...]
    candidate_active: bool
    blocking_reasons: tuple[SmokeBlockReason, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "parser-nonproduction-rollback-smoke-v1":
            raise RollbackSmokeError("rollback record schema is unsupported")
        for field in (
            "smoke_id",
            "runbook_id",
            "expected_known_good_release_id",
            "injected_flow_id",
            "selected_release_id",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        if self.environment != "non_production":
            raise RollbackSmokeError("rollback record environment is invalid")
        try:
            status = SmokeStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise RollbackSmokeError("rollback record status is invalid") from exc
        object.__setattr__(self, "status", status)
        for field in (
            "runbook_sha256",
            "initial_candidate_pin_sha256",
            "expected_known_good_pin_sha256",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        for field in (
            "restored_release_pin_sha256",
            "restored_flag_snapshot_sha256",
            "restored_artifact_manifest_sha256",
            "restored_configuration_sha256",
            "restored_policy_sha256",
            "restored_flow_set_sha256",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _digest(value, field))
        if type(self.failure_detected) is not bool or type(self.candidate_active) is not bool:
            raise RollbackSmokeError("rollback record booleans are invalid")
        for field in (
            "hosted_transport_calls",
            "hosted_transport_attempts",
            "post_stop_candidate_attempts",
            "post_stop_candidate_calls",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1:
                raise RollbackSmokeError(f"{field} is outside its bound")
        if self.injected_failure != "ordinary_functional_failure":
            raise RollbackSmokeError("rollback record failure type is invalid")
        if (
            isinstance(self.injected_http_status, bool)
            or not isinstance(self.injected_http_status, int)
            or not 400 <= self.injected_http_status <= 499
        ):
            raise RollbackSmokeError("injected HTTP status must be an ordinary 4xx")
        if any(type(action) is not RunbookAction for action in self.completed_actions):
            raise RollbackSmokeError("rollback record action is invalid")
        if any(type(reason) is not SmokeBlockReason for reason in self.blocking_reasons):
            raise RollbackSmokeError("rollback record blocker is invalid")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise RollbackSmokeError("rollback record blockers must be unique")
        restored_flow_ids = tuple(
            _identifier(value, "restored flow_id") for value in self.restored_flow_ids
        )
        if restored_flow_ids != tuple(sorted(set(restored_flow_ids))):
            raise RollbackSmokeError("restored flow IDs must be sorted and unique")
        if status is SmokeStatus.PASS and (
            not self.failure_detected
            or self.candidate_active
            or self.blocking_reasons
            or self.restored_release_pin_sha256 != self.expected_known_good_pin_sha256
            or self.selected_release_id != self.expected_known_good_release_id
            or self.completed_actions != _ROLLBACK_ACTIONS
            or len(self.restored_flow_ids) < 2
            or any(
                value is None
                for value in (
                    self.restored_flag_snapshot_sha256,
                    self.restored_artifact_manifest_sha256,
                    self.restored_configuration_sha256,
                    self.restored_policy_sha256,
                    self.restored_flow_set_sha256,
                )
            )
            or self.hosted_transport_calls != 0
            or self.hosted_transport_attempts != 1
            or self.post_stop_candidate_attempts != 1
            or self.post_stop_candidate_calls != 0
        ):
            raise RollbackSmokeError("passing rollback record is inconsistent")
        if status is SmokeStatus.BLOCK and not self.blocking_reasons:
            raise RollbackSmokeError("blocking rollback record requires a reason")
        self.canonical_bytes()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "smoke_id": self.smoke_id,
            "environment": self.environment,
            "status": self.status.value,
            "injected_failure": self.injected_failure,
            "failure_detected": self.failure_detected,
            "runbook_id": self.runbook_id,
            "runbook_sha256": self.runbook_sha256,
            "initial_candidate_pin_sha256": self.initial_candidate_pin_sha256,
            "expected_known_good_release_id": self.expected_known_good_release_id,
            "expected_known_good_pin_sha256": self.expected_known_good_pin_sha256,
            "injected_flow_id": self.injected_flow_id,
            "injected_http_status": self.injected_http_status,
            "selected_release_id": self.selected_release_id,
            "restored_release_pin_sha256": self.restored_release_pin_sha256,
            "restored_flag_snapshot_sha256": self.restored_flag_snapshot_sha256,
            "restored_artifact_manifest_sha256": self.restored_artifact_manifest_sha256,
            "restored_configuration_sha256": self.restored_configuration_sha256,
            "restored_policy_sha256": self.restored_policy_sha256,
            "restored_flow_set_sha256": self.restored_flow_set_sha256,
            "hosted_transport_calls": self.hosted_transport_calls,
            "hosted_transport_attempts": self.hosted_transport_attempts,
            "post_stop_candidate_attempts": self.post_stop_candidate_attempts,
            "post_stop_candidate_calls": self.post_stop_candidate_calls,
            "restored_flow_ids": list(self.restored_flow_ids),
            "completed_actions": [value.value for value in self.completed_actions],
            "candidate_active": self.candidate_active,
            "blocking_reasons": [value.value for value in self.blocking_reasons],
        }

    def canonical_bytes(self) -> bytes:
        encoded = json.dumps(
            self.to_mapping(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > _MAX_RECORD_BYTES:
            raise RollbackSmokeError("rollback record exceeds its byte cap")
        return encoded

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _block_record(
    *,
    spec: RollbackSmokeSpec,
    runbook: RunbookManifest,
    candidate: RollbackProfile,
    known_good: RollbackProfile,
    detected: bool,
    reason: SmokeBlockReason,
    completed_actions: tuple[RunbookAction, ...] = (),
    candidate_active: bool = True,
    selected_release_id: str | None = None,
) -> RollbackSmokeRecord:
    return RollbackSmokeRecord(
        schema_version="parser-nonproduction-rollback-smoke-v1",
        smoke_id=spec.smoke_id,
        environment=spec.environment,
        status=SmokeStatus.BLOCK,
        injected_failure=spec.injection,
        failure_detected=detected,
        runbook_id=runbook.runbook_id,
        runbook_sha256=runbook.sha256,
        initial_candidate_pin_sha256=candidate.release.sha256,
        expected_known_good_release_id=known_good.release.release_id,
        expected_known_good_pin_sha256=known_good.release.sha256,
        injected_flow_id=spec.injection_flow_id,
        injected_http_status=422,
        selected_release_id=selected_release_id or candidate.release.release_id,
        restored_release_pin_sha256=None,
        restored_flag_snapshot_sha256=None,
        restored_artifact_manifest_sha256=None,
        restored_configuration_sha256=None,
        restored_policy_sha256=None,
        restored_flow_set_sha256=None,
        hosted_transport_attempts=0,
        hosted_transport_calls=0,
        post_stop_candidate_attempts=0,
        post_stop_candidate_calls=0,
        restored_flow_ids=(),
        completed_actions=completed_actions,
        candidate_active=candidate_active,
        blocking_reasons=(reason,),
    )


def execute_nonproduction_rollback_smoke(
    *,
    spec: RollbackSmokeSpec,
    runbook: RunbookManifest,
    known_good: RollbackProfile,
    candidate: RollbackProfile,
    artifact_manifest: ArtifactManifest,
    artifact_verification: ManifestVerification,
    fail_action: RunbookAction | None = None,
) -> RollbackSmokeRecord:
    """Execute one deterministic rollback state transition entirely in memory."""

    for value, expected, field in (
        (spec, RollbackSmokeSpec, "spec"),
        (runbook, RunbookManifest, "runbook"),
        (known_good, RollbackProfile, "known_good"),
        (candidate, RollbackProfile, "candidate"),
        (artifact_manifest, ArtifactManifest, "artifact_manifest"),
        (artifact_verification, ManifestVerification, "artifact_verification"),
    ):
        if type(value) is not expected:
            raise RollbackSmokeError(f"{field} has the wrong contract type")
    if runbook.kind is not RunbookKind.ROLLBACK:
        raise RollbackSmokeError("rollback smoke requires the rollback runbook")
    if fail_action is not None and type(fail_action) is not RunbookAction:
        raise RollbackSmokeError("fail_action must be an allowlisted runbook action")
    if known_good.release.release_id == candidate.release.release_id:
        raise RollbackSmokeError("candidate and known-good identities must differ")
    if (
        runbook.known_good_release_id != known_good.release.release_id
        or runbook.known_good_release_pin_sha256 != known_good.release.sha256
        or runbook.candidate_release_id != candidate.release.release_id
        or runbook.candidate_release_pin_sha256 != candidate.release.sha256
    ):
        raise RollbackSmokeError("rollback runbook is not bound to the supplied profiles")
    if known_good.flags.global_kill_switch or known_good.flags.disabled_capabilities:
        raise RollbackSmokeError("known-good flag snapshot must be the restored normal state")
    if known_good.flags.enabled_settings():
        raise RollbackSmokeError("known-good optional shipping flags must be off")
    if known_good.hosted_policy.hosted_enabled:
        raise RollbackSmokeError("known-good hosted policy must be disabled")
    if (
        artifact_manifest.manifest_sha256
        != known_good.release.artifact_manifest_sha256
        or artifact_manifest.manifest_sha256
        != candidate.release.artifact_manifest_sha256
    ):
        raise RollbackSmokeError("artifact manifest is not bound to both release pins")
    if not candidate.flags.enabled_settings().intersection(_PHASE08_CONTROL_SETTINGS):
        return _block_record(
            spec=spec,
            runbook=runbook,
            candidate=candidate,
            known_good=known_good,
            detected=False,
            reason=SmokeBlockReason.CANDIDATE_CONTROLS_NOT_ENABLED,
        )
    known_by_id = {value.flow_id: value for value in known_good.flows}
    candidate_by_id = {value.flow_id: value for value in candidate.flows}
    if set(known_by_id) != set(candidate_by_id) or any(
        candidate_by_id[flow_id].compatible_identity()
        != known_by_id[flow_id].compatible_identity()
        for flow_id in known_by_id
    ):
        return _block_record(
            spec=spec,
            runbook=runbook,
            candidate=candidate,
            known_good=known_good,
            detected=False,
            reason=SmokeBlockReason.CANDIDATE_FLOW_MISMATCH,
        )
    injection_target = candidate_by_id.get(spec.injection_flow_id)
    injected_failure = (
        replace(
            injection_target,
            outcome=FlowOutcome.ORDINARY_FAILURE,
            http_status=422,
            response_schema_sha256=hashlib.sha256(
                b"parser-error-envelope-v1"
            ).hexdigest(),
            canonical_output_sha256=hashlib.sha256(
                b"injected-ordinary-functional-failure"
            ).hexdigest(),
        )
        if injection_target is not None
        else None
    )
    detected = (
        injection_target is not None
        and injection_target.outcome is FlowOutcome.SUCCESS
        and 200 <= injection_target.http_status <= 299
        and injected_failure is not None
        and injected_failure.outcome is FlowOutcome.ORDINARY_FAILURE
        and 400 <= injected_failure.http_status <= 499
        and injected_failure.canonical_output_sha256
        != injection_target.canonical_output_sha256
    )
    if not detected:
        return _block_record(
            spec=spec,
            runbook=runbook,
            candidate=candidate,
            known_good=known_good,
            detected=False,
            reason=SmokeBlockReason.INJECTION_NOT_DETECTED,
        )

    selected_release_id = candidate.release.release_id
    active_release_pin = candidate.release.sha256
    artifact = candidate.release.artifact_manifest_sha256
    configuration = candidate.release.configuration_sha256
    policy = candidate.hosted_policy
    flags = candidate.flags
    flows = tuple(
        injected_failure if value.flow_id == spec.injection_flow_id else value
        for value in candidate.flows
    )
    candidate_active = True
    completed: list[RunbookAction] = []
    kill_snapshot = ShippingFlagSnapshot.from_settings(
        Settings(parser_shipping_kill_switch=True)
    )
    evidence_values: dict[str, bool] = {
        step.evidence_key: False for step in runbook.steps
    }
    artifact_verified = bool(
        is_release_verification_attested(artifact_verification)
        and artifact_verification.accepted is True
        and artifact_verification.purpose == "release_startup"
        and artifact_verification.release_id == artifact_manifest.release_id
        and artifact_verification.manifest_sha256 == artifact_manifest.manifest_sha256
        and artifact_verification.profile_id is not None
        and artifact_verification.profile_id
        == LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id
        and known_good.artifact_profile_id
        == LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id
        and candidate.artifact_profile_id
        == LOCAL_REFERENCE_ARTIFACT_PROFILE.profile_id
        and not artifact_verification.blocking_reasons
    )

    for step in runbook.steps:
        action = step.action
        if action is fail_action:
            break
        passed = True
        if action is RunbookAction.REQUEST_CANDIDATE_STOP:
            candidate_active = False
            passed = not candidate_active
        elif action is RunbookAction.ENABLE_GLOBAL_KILL_SWITCH:
            flags = kill_snapshot
            passed = flags.global_kill_switch and not flags.enabled_settings()
        elif action is RunbookAction.RESTORE_KNOWN_GOOD_FLAGS:
            flags = known_good.flags
            configuration = known_good.release.configuration_sha256
            passed = flags == known_good.flags
        elif action is RunbookAction.SELECT_KNOWN_GOOD_ARTIFACTS:
            artifact = known_good.release.artifact_manifest_sha256
            selected_release_id = known_good.release.release_id
            passed = artifact == artifact_manifest.manifest_sha256
        elif action is RunbookAction.RESTORE_KNOWN_GOOD_POLICY:
            policy = known_good.hosted_policy
            passed = not policy.hosted_enabled and policy.default_decision == "deny"
        elif action is RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS:
            passed = artifact_verified and artifact == artifact_manifest.manifest_sha256
        elif action is RunbookAction.VERIFY_KNOWN_GOOD_FLOWS:
            flows = known_good.flows
            passed = all(
                value.release_pin_sha256 == known_good.release.sha256
                for value in flows
            )
        elif action is RunbookAction.RECORD_ROLLBACK_EVIDENCE:
            active_release_pin = known_good.release.sha256
            passed = not candidate_active
        evidence_values[step.evidence_key] = passed
        if not passed:
            break
        completed.append(action)

    walked = dry_run_rollback(
        runbook,
        known_good=known_good.release,
        candidate=candidate.release,
        trigger=RollbackTrigger.SMOKE_GATE_BLOCK,
        evidence=evidence_values,
    )
    if walked.status != "pass":
        reason = (
            SmokeBlockReason.ARTIFACT_VERIFICATION_INVALID
            if RunbookAction.VERIFY_KNOWN_GOOD_ARTIFACTS
            not in walked.completed_actions
            and not artifact_verified
            else SmokeBlockReason.RUNBOOK_BLOCKED
        )
        return _block_record(
            spec=spec,
            runbook=runbook,
            candidate=candidate,
            known_good=known_good,
            detected=True,
            reason=reason,
            completed_actions=walked.completed_actions,
            candidate_active=(
                RunbookAction.REQUEST_CANDIDATE_STOP not in walked.completed_actions
            ),
            selected_release_id=walked.selected_release_id,
        )

    # Exercise one post-stop admission attempt through the guarded call seam.
    # The supplied runner is invoked only while the candidate remains active.
    candidate_gate = _InMemoryCallGate()
    candidate_gate.attempt(active=candidate_active)
    hosted_gate = _InMemoryCallGate()
    hosted_gate.attempt(
        active=policy.hosted_enabled and policy.default_decision != "deny"
    )
    flow_set_sha256 = hashlib.sha256(
        json.dumps(
            [
                {
                    "flow_id": value.flow_id,
                    "release_pin_sha256": value.release_pin_sha256,
                    "outcome": value.outcome.value,
                    "http_status": value.http_status,
                    "response_schema_sha256": value.response_schema_sha256,
                    "canonical_output_sha256": value.canonical_output_sha256,
                }
                for value in flows
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    restored = (
        not candidate_active
        and selected_release_id == known_good.release.release_id
        and active_release_pin == known_good.release.sha256
        and flags == known_good.flags
        and artifact == known_good.release.artifact_manifest_sha256
        and configuration == known_good.release.configuration_sha256
        and policy == known_good.hosted_policy
        and flows == known_good.flows
        and tuple(completed) == walked.completed_actions
        and candidate_gate.calls == 0
        and hosted_gate.calls == 0
    )
    if not restored:
        return _block_record(
            spec=spec,
            runbook=runbook,
            candidate=candidate,
            known_good=known_good,
            detected=True,
            reason=SmokeBlockReason.RESTORE_MISMATCH,
            completed_actions=tuple(completed),
            candidate_active=candidate_active,
            selected_release_id=selected_release_id,
        )
    return RollbackSmokeRecord(
        schema_version="parser-nonproduction-rollback-smoke-v1",
        smoke_id=spec.smoke_id,
        environment=spec.environment,
        status=SmokeStatus.PASS,
        injected_failure=spec.injection,
        failure_detected=True,
        runbook_id=runbook.runbook_id,
        runbook_sha256=runbook.sha256,
        initial_candidate_pin_sha256=candidate.release.sha256,
        expected_known_good_release_id=known_good.release.release_id,
        expected_known_good_pin_sha256=known_good.release.sha256,
        injected_flow_id=spec.injection_flow_id,
        injected_http_status=injected_failure.http_status,
        selected_release_id=known_good.release.release_id,
        restored_release_pin_sha256=known_good.release.sha256,
        restored_flag_snapshot_sha256=known_good.flags.sha256,
        restored_artifact_manifest_sha256=known_good.release.artifact_manifest_sha256,
        restored_configuration_sha256=known_good.release.configuration_sha256,
        restored_policy_sha256=known_good.release.policy_sha256,
        restored_flow_set_sha256=flow_set_sha256,
        hosted_transport_attempts=hosted_gate.attempts,
        hosted_transport_calls=0,
        post_stop_candidate_attempts=candidate_gate.attempts,
        post_stop_candidate_calls=candidate_gate.calls,
        restored_flow_ids=tuple(value.flow_id for value in known_good.flows),
        completed_actions=tuple(completed),
        candidate_active=False,
        blocking_reasons=(),
    )


__all__ = [
    "FlowOutcome",
    "RepresentativeFlow",
    "RepresentativeFlowContract",
    "RepresentativeFlowContractEntry",
    "HostedPolicySelection",
    "RollbackProfile",
    "RollbackSmokeError",
    "RollbackSmokeRecord",
    "RollbackSmokeSpec",
    "ShippingFlagSnapshot",
    "ShippingFlagState",
    "SmokeBlockReason",
    "SmokeStatus",
    "execute_nonproduction_rollback_smoke",
    "load_hosted_policy_selection",
    "load_representative_flow_contract",
    "load_shipping_flag_profile",
]
