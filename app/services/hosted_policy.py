"""Manifest-bound, deny-by-default policy for optional hosted processing.

Phase 06 owns the bounded minimized transport adapter.  This module adds the
release authority that must approve an exact manifest, provider/model
identity, data class, processing and residency region, retention policy, and
egress destination *before* that adapter can be invoked.  It contains no HTTP
client, credential field, or document logging surface.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from app.services.artifact_manifest import (
    ArtifactCheck,
    ArtifactKind,
    ArtifactManifest,
    ArtifactManifestError,
    ManifestVerification,
    is_release_verification_attested,
)
from app.services.visual_model_contracts import (
    VisualModelContractEnvelope,
    VisualModelRequest,
)
from app.services.visual_model_hosted import (
    HostedAdapterResult,
    HostedBudget,
    HostedDispatchPlan,
    HostedPolicy,
    HostedVisualModelAdapter,
    HostedVisualModelTransport,
)
from app.services.visual_model_local import LocalVisualModelAdapter


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_POLICY_FIELDS = frozenset(
    {
        "policy_id",
        "approved",
        "manifest_sha256",
        "model_artifact_id",
        "model_artifact_sha256",
        "vendor",
        "model",
        "model_version",
        "allowed_data_classes",
        "allowed_processing_regions",
        "allowed_residency_regions",
        "allowed_retention_policies",
        "allowed_egress_destinations",
        "allowed_redaction_decisions",
        "subprocessor_approved",
        "allow_cache",
        "allow_whole_document",
        "require_processing_in_residency",
    }
)
_GOVERNANCE_FIELDS = frozenset(
    {
        "tenant_permission",
        "residency_region",
        "egress_destination",
        "request_scope",
        "cache_requested",
    }
)


class HostedReleasePolicyError(ValueError):
    """Raised when a policy declaration itself is unsafe or ambiguous."""


class HostedPolicyReason(StrEnum):
    """Stable bounded decisions; no source or secret can enter this field."""

    APPROVED = "approved"
    HOSTED_DISABLED = "hosted_disabled"
    POLICY_MISSING = "policy_missing"
    POLICY_MALFORMED = "policy_malformed"
    POLICY_NOT_APPROVED = "policy_not_approved"
    TENANT_PERMISSION_MISSING = "tenant_permission_missing"
    MANIFEST_INVALID = "manifest_invalid"
    MANIFEST_DIGEST_MISMATCH = "manifest_digest_mismatch"
    ARTIFACT_BINDING_MISMATCH = "artifact_binding_mismatch"
    VENDOR_MISMATCH = "vendor_mismatch"
    MODEL_MISMATCH = "model_mismatch"
    DATA_CLASS_MISMATCH = "data_class_mismatch"
    PROCESSING_REGION_MISMATCH = "processing_region_mismatch"
    RESIDENCY_REGION_MISMATCH = "residency_region_mismatch"
    PROCESSING_RESIDENCY_MISMATCH = "processing_residency_mismatch"
    RETENTION_POLICY_MISMATCH = "retention_policy_mismatch"
    EGRESS_DESTINATION_MISMATCH = "egress_destination_mismatch"
    REDACTION_POLICY_MISMATCH = "redaction_policy_mismatch"
    SUBPROCESSOR_NOT_APPROVED = "subprocessor_not_approved"
    CACHE_NOT_ALLOWED = "cache_not_allowed"
    WHOLE_DOCUMENT_NOT_ALLOWED = "whole_document_not_allowed"
    PHASE06_POLICY_DENIED = "phase06_policy_denied"
    HOSTED_ADAPTER_FALLBACK = "hosted_adapter_fallback"
    RESPONSE_ARTIFACT_MISMATCH = "response_artifact_mismatch"
    MANIFEST_VERIFICATION_INVALID = "manifest_verification_invalid"
    CROP_REGION_MISMATCH = "crop_region_mismatch"
    LOCAL_FALLBACK_UNAVAILABLE = "local_fallback_unavailable"


def _identifier(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER_RE.fullmatch(value) is None
        or any(ord(character) < 32 for character in value)
    ):
        raise HostedReleasePolicyError(f"{field_name} must be a bounded identifier")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise HostedReleasePolicyError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _sorted_identifiers(
    values: tuple[str, ...],
    field_name: str,
    *,
    maximum: int = 64,
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not 1 <= len(values) <= maximum:
        raise HostedReleasePolicyError(
            f"{field_name} must contain between 1 and {maximum} values"
        )
    normalized = tuple(_identifier(value, field_name) for value in values)
    if normalized != tuple(sorted(normalized)) or len(set(normalized)) != len(
        normalized
    ):
        raise HostedReleasePolicyError(f"{field_name} must be sorted and unique")
    return normalized


def _egress_destination(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or value != value.strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise HostedReleasePolicyError("egress destination is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise HostedReleasePolicyError(
            "egress destination must be credential-free exact HTTPS origin/path"
        )
    return value


def _sorted_destinations(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not 1 <= len(values) <= 64:
        raise HostedReleasePolicyError(
            "allowed egress destinations must contain between 1 and 64 values"
        )
    normalized = tuple(_egress_destination(value) for value in values)
    if normalized != tuple(sorted(normalized)) or len(set(normalized)) != len(
        normalized
    ):
        raise HostedReleasePolicyError(
            "allowed egress destinations must be sorted and unique"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class HostedReleasePolicy:
    """One exact, manifest-pinned hosted release approval."""

    policy_id: str
    approved: bool
    manifest_sha256: str
    model_artifact_id: str
    model_artifact_sha256: str
    vendor: str
    model: str
    model_version: str
    allowed_data_classes: tuple[str, ...]
    allowed_processing_regions: tuple[str, ...]
    allowed_residency_regions: tuple[str, ...]
    allowed_retention_policies: tuple[str, ...]
    allowed_egress_destinations: tuple[str, ...]
    allowed_redaction_decisions: tuple[str, ...]
    subprocessor_approved: bool = False
    allow_cache: bool = False
    allow_whole_document: bool = False
    require_processing_in_residency: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        if not isinstance(self.approved, bool):
            raise HostedReleasePolicyError("approved must be a boolean")
        object.__setattr__(
            self,
            "manifest_sha256",
            _sha256(self.manifest_sha256, "manifest_sha256"),
        )
        object.__setattr__(
            self,
            "model_artifact_id",
            _identifier(self.model_artifact_id, "model_artifact_id"),
        )
        object.__setattr__(
            self,
            "model_artifact_sha256",
            _sha256(self.model_artifact_sha256, "model_artifact_sha256"),
        )
        for name in ("vendor", "model", "model_version"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "allowed_data_classes",
            "allowed_processing_regions",
            "allowed_residency_regions",
            "allowed_retention_policies",
            "allowed_redaction_decisions",
        ):
            object.__setattr__(
                self,
                name,
                _sorted_identifiers(getattr(self, name), name),
            )
        if not set(self.allowed_redaction_decisions) <= {"applied", "not_required"}:
            raise HostedReleasePolicyError("redaction decisions are unsupported")
        object.__setattr__(
            self,
            "allowed_egress_destinations",
            _sorted_destinations(self.allowed_egress_destinations),
        )
        for name in (
            "subprocessor_approved",
            "allow_cache",
            "allow_whole_document",
            "require_processing_in_residency",
        ):
            if not isinstance(getattr(self, name), bool):
                raise HostedReleasePolicyError(f"{name} must be a boolean")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HostedReleasePolicy":
        """Strictly parse a bounded policy mapping without coercion."""

        if set(value) != _POLICY_FIELDS:
            raise HostedReleasePolicyError("hosted policy fields differ from the schema")
        converted = dict(value)
        for name in (
            "allowed_data_classes",
            "allowed_processing_regions",
            "allowed_residency_regions",
            "allowed_retention_policies",
            "allowed_egress_destinations",
            "allowed_redaction_decisions",
        ):
            raw = converted[name]
            if not isinstance(raw, (list, tuple)) or any(
                not isinstance(item, str) for item in raw
            ):
                raise HostedReleasePolicyError(f"{name} must be a string sequence")
            converted[name] = tuple(raw)
        return cls(**converted)


@dataclass(frozen=True, slots=True)
class HostedRequestGovernance:
    """Non-content authority supplied for one hosted request profile."""

    tenant_permission: bool = False
    residency_region: str = "local"
    egress_destination: str = "https://denied.invalid"
    request_scope: str = "approved_region_only"
    cache_requested: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_permission, bool) or not isinstance(
            self.cache_requested, bool
        ):
            raise HostedReleasePolicyError(
                "tenant_permission and cache_requested must be booleans"
            )
        object.__setattr__(
            self,
            "residency_region",
            _identifier(self.residency_region, "residency_region"),
        )
        object.__setattr__(
            self,
            "egress_destination",
            _egress_destination(self.egress_destination),
        )
        if self.request_scope not in {"approved_region_only", "whole_document"}:
            raise HostedReleasePolicyError("request_scope is unsupported")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HostedRequestGovernance":
        if set(value) != _GOVERNANCE_FIELDS:
            raise HostedReleasePolicyError(
                "hosted request governance fields differ from the schema"
            )
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class HostedGovernanceDecision:
    """Safe decision record with no document, tenant, endpoint, or secret fields."""

    allowed: bool
    reason: HostedPolicyReason
    manifest_sha256: str | None
    policy_present: bool

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool) or not isinstance(
            self.policy_present, bool
        ):
            raise HostedReleasePolicyError("decision booleans are invalid")
        if not isinstance(self.reason, HostedPolicyReason):
            raise HostedReleasePolicyError("decision reason is invalid")
        if self.allowed is not (self.reason is HostedPolicyReason.APPROVED):
            raise HostedReleasePolicyError("decision state is inconsistent")
        if self.manifest_sha256 is not None:
            _sha256(self.manifest_sha256, "manifest_sha256")

    def safe_record(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "manifest_sha256": self.manifest_sha256,
            "policy_present": self.policy_present,
        }


@dataclass(frozen=True, slots=True)
class HostedGatewayResult:
    """Typed hosted/fallback result; payload-bearing values are repr-hidden."""

    status: str
    decision: HostedGovernanceDecision
    transport_calls: int
    fallback_invoked: bool
    hosted_failure_code: str | None = None
    contract_envelope: Any | None = field(default=None, repr=False)
    hosted_result: HostedAdapterResult | None = field(default=None, repr=False)
    fallback_result: Any | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.status not in {"hosted", "local_fallback", "local_unavailable"}:
            raise HostedReleasePolicyError("hosted gateway status is unsupported")
        if self.transport_calls not in {0, 1}:
            raise HostedReleasePolicyError("hosted gateway transport calls are invalid")
        if self.hosted_failure_code is not None:
            _identifier(self.hosted_failure_code, "hosted_failure_code")
        if self.status == "hosted" and (
            not self.decision.allowed
            or self.transport_calls != 1
            or self.fallback_invoked
            or not isinstance(self.contract_envelope, VisualModelContractEnvelope)
            or self.contract_envelope.status != "accepted"
        ):
            raise HostedReleasePolicyError("hosted gateway accepted state is invalid")
        if self.status != "hosted" and not self.fallback_invoked:
            raise HostedReleasePolicyError("hosted fallback state is invalid")

    @property
    def failure(self) -> Any | None:
        """Compatibility surface consumed by the Phase 06 route dispatcher."""

        return self.hosted_result.failure if self.hosted_result is not None else None

    def safe_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision.safe_record(),
            "transport_calls": self.transport_calls,
            "fallback_invoked": self.fallback_invoked,
            "hosted_failure_code": self.hosted_failure_code,
        }


class LocalHostedFallback(Protocol):
    def invoke(self, request: VisualModelRequest) -> Any: ...


_LOCAL_FALLBACK_AUTHORITY = object()


class TrustedLocalHostedFallback:
    """Factory-issued authority for one explicitly local fallback.

    A raw adapter cannot occupy the fallback slot merely by claiming a
    ``kind`` attribute.  Deployment wiring must deliberately wrap its local
    implementation with :func:`trusted_local_hosted_fallback`; the wrapper is
    the only concrete type accepted by :class:`HostedReleaseGateway`.
    """

    __slots__ = ("_delegate", "_invoke_count")
    kind = "local"

    def __init__(self, delegate: Any, *, _authority: object) -> None:
        if _authority is not _LOCAL_FALLBACK_AUTHORITY:
            raise HostedReleasePolicyError(
                "trusted local fallback must be created by its authority factory"
            )
        self._delegate = delegate
        self._invoke_count = 0

    @property
    def invoke_count(self) -> int:
        return self._invoke_count

    def invoke(self, request: VisualModelRequest) -> Any:
        self._invoke_count += 1
        delegate = self._delegate
        if callable(delegate) and not hasattr(delegate, "invoke"):
            return delegate(request)
        return delegate.invoke(request)


def trusted_local_hosted_fallback(
    fallback: LocalVisualModelAdapter,
) -> TrustedLocalHostedFallback:
    """Authorize only the concrete offline Phase 06 local adapter.

    Exact concrete typing prevents hosted adapters and marker-only objects from
    spoofing a ``kind = 'local'`` attribute at the injection boundary.
    """

    if type(fallback) is not LocalVisualModelAdapter:
        raise HostedReleasePolicyError(
            "trusted production fallback must be the concrete local adapter"
        )
    return TrustedLocalHostedFallback(
        fallback,
        _authority=_LOCAL_FALLBACK_AUTHORITY,
    )


def _verified_model_artifact(
    verification: ManifestVerification | None,
    *,
    manifest: ArtifactManifest,
    profile_id: str,
    artifact_id: str,
    artifact_sha256: str,
    capability: str,
) -> bool:
    """Require an accepted startup report for this exact release and artifact."""

    if (
        not is_release_verification_attested(verification)
        or verification.accepted is not True
        or verification.purpose != "release_startup"
        or verification.profile_id != profile_id
        or verification.release_id != manifest.release_id
        or verification.manifest_sha256 != manifest.manifest_sha256
        or verification.blocking_reasons
    ):
        return False
    matching = tuple(
        check
        for check in verification.checks
        if type(check) is ArtifactCheck and check.artifact_id == artifact_id
    )
    return bool(
        len(matching) == 1
        and matching[0].outcome == "verified"
        and matching[0].reason == "verified"
        and matching[0].capability == capability
        and matching[0].actual_sha256 == artifact_sha256
    )


def _crop_is_bound_to_region(request: VisualModelRequest) -> bool:
    """Conservatively bind declared crop geometry to the requested region.

    Image crops are one source pixel per output pixel.  PDF crops may be
    rendered at up to the production renderer's fixed 2x scale; both axes must
    nevertheless share that scale within one output pixel of rounding.
    """

    box = request.region.page_bbox
    crop = request.crop
    if box.width <= 0 or box.height <= 0:
        return False
    if box.unit == "px":
        return bool(
            abs(crop.width - box.width) <= 1.0
            and abs(crop.height - box.height) <= 1.0
        )
    if box.unit != "pt":
        return False
    scale_x = crop.width / box.width
    scale_y = crop.height / box.height
    if not (0 < scale_x <= 2.0 + (1.0 / box.width)):
        return False
    if not (0 < scale_y <= 2.0 + (1.0 / box.height)):
        return False
    scale = (scale_x + scale_y) / 2.0
    return bool(
        abs(crop.width - box.width * scale) <= 1.0
        and abs(crop.height - box.height * scale) <= 1.0
    )


class HostedReleaseGateway:
    """Evaluate release policy, invoke Phase 06 once, or stay local."""

    kind = "hosted"
    release_policy_enforced = True

    def __init__(
        self,
        *,
        hosted_enabled: bool = False,
        manifest: ArtifactManifest,
        manifest_verification: ManifestVerification,
        manifest_profile_id: str,
        policy: HostedReleasePolicy | Mapping[str, Any] | None,
        governance: HostedRequestGovernance | Mapping[str, Any],
        transport: HostedVisualModelTransport,
        phase06_policy: HostedPolicy,
        budget: HostedBudget,
        plan: HostedDispatchPlan,
        local_fallback: TrustedLocalHostedFallback,
        telemetry: Any | None = None,
        max_audit_records: int = 128,
    ) -> None:
        if not isinstance(hosted_enabled, bool):
            raise HostedReleasePolicyError("hosted_enabled must be a boolean")
        if not 1 <= max_audit_records <= 1_024:
            raise HostedReleasePolicyError("hosted policy audit bound is invalid")
        self._hosted_enabled = hosted_enabled
        self._manifest = manifest
        self._manifest_verification = manifest_verification
        self._manifest_profile_id = _identifier(
            manifest_profile_id,
            "manifest_profile_id",
        )
        self._policy, self._policy_malformed = self._parse_policy(policy)
        self._governance, self._governance_malformed = self._parse_governance(
            governance
        )
        self._phase06_policy = HostedPolicy.model_validate(
            phase06_policy, strict=True
        )
        self._plan = HostedDispatchPlan.model_validate(plan, strict=True)
        declared_egress = getattr(transport, "egress_destination", None)
        try:
            self._transport_egress_destination = _egress_destination(
                declared_egress
            )
        except (TypeError, ValueError):
            self._transport_egress_destination = None
        self._adapter = HostedVisualModelAdapter(
            transport=transport,
            policy=self._phase06_policy,
            budget=budget,
            plan=self._plan,
        )
        if type(local_fallback) is not TrustedLocalHostedFallback:
            raise HostedReleasePolicyError(
                "local fallback lacks factory-issued local authority"
            )
        self._local_fallback = local_fallback
        self._telemetry = telemetry
        self._audit: deque[dict[str, Any]] = deque(maxlen=max_audit_records)
        self._lock = threading.Lock()

    @staticmethod
    def _parse_policy(
        policy: HostedReleasePolicy | Mapping[str, Any] | None,
    ) -> tuple[HostedReleasePolicy | None, bool]:
        if policy is None:
            return None, False
        if isinstance(policy, HostedReleasePolicy):
            return policy, False
        if isinstance(policy, Mapping):
            try:
                return HostedReleasePolicy.from_mapping(policy), False
            except (TypeError, ValueError):
                return None, True
        return None, True

    @staticmethod
    def _parse_governance(
        governance: HostedRequestGovernance | Mapping[str, Any],
    ) -> tuple[HostedRequestGovernance | None, bool]:
        if isinstance(governance, HostedRequestGovernance):
            return governance, False
        if isinstance(governance, Mapping):
            try:
                return HostedRequestGovernance.from_mapping(governance), False
            except (TypeError, ValueError):
                return None, True
        return None, True

    @property
    def audit_records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(value) for value in self._audit)

    def is_available(self) -> bool:
        """Availability never grants dispatch authority; invoke re-evaluates."""

        return self._hosted_enabled

    def _decision(self, reason: HostedPolicyReason) -> HostedGovernanceDecision:
        policy = self._policy
        return HostedGovernanceDecision(
            allowed=reason is HostedPolicyReason.APPROVED,
            reason=reason,
            manifest_sha256=(
                policy.manifest_sha256
                if policy is not None and _SHA256_RE.fullmatch(policy.manifest_sha256)
                else None
            ),
            policy_present=policy is not None,
        )

    def evaluate(self) -> HostedGovernanceDecision:
        """Return the first exact denial without inspecting request payloads."""

        if not self._hosted_enabled:
            return self._decision(HostedPolicyReason.HOSTED_DISABLED)
        if self._policy_malformed or self._governance_malformed:
            return self._decision(HostedPolicyReason.POLICY_MALFORMED)
        policy = self._policy
        governance = self._governance
        if policy is None:
            return self._decision(HostedPolicyReason.POLICY_MISSING)
        if governance is None:
            return self._decision(HostedPolicyReason.POLICY_MALFORMED)
        if not policy.approved:
            return self._decision(HostedPolicyReason.POLICY_NOT_APPROVED)
        if not governance.tenant_permission:
            return self._decision(HostedPolicyReason.TENANT_PERMISSION_MISSING)
        if not isinstance(self._manifest, ArtifactManifest):
            return self._decision(HostedPolicyReason.MANIFEST_INVALID)
        try:
            self._manifest.assert_authentic()
        except (ArtifactManifestError, TypeError, ValueError):
            return self._decision(HostedPolicyReason.MANIFEST_INVALID)
        if self._manifest.manifest_sha256 != policy.manifest_sha256:
            return self._decision(HostedPolicyReason.MANIFEST_DIGEST_MISMATCH)
        artifact = self._manifest.artifact(policy.model_artifact_id)
        if (
            artifact is None
            or not artifact.enabled
            or artifact.kind is not ArtifactKind.MODEL
            or artifact.version != policy.model_version
            or artifact.sha256 != policy.model_artifact_sha256
            or not self._manifest.binds(
                policy.model_artifact_id,
                version=policy.model_version,
                sha256=policy.model_artifact_sha256,
            )
        ):
            return self._decision(HostedPolicyReason.ARTIFACT_BINDING_MISMATCH)
        if not _verified_model_artifact(
            self._manifest_verification,
            manifest=self._manifest,
            profile_id=self._manifest_profile_id,
            artifact_id=artifact.artifact_id,
            artifact_sha256=artifact.sha256 or "",
            capability=artifact.capability,
        ):
            return self._decision(
                HostedPolicyReason.MANIFEST_VERIFICATION_INVALID
            )
        if self._plan.vendor != policy.vendor:
            return self._decision(HostedPolicyReason.VENDOR_MISMATCH)
        if self._plan.model != policy.model:
            return self._decision(HostedPolicyReason.MODEL_MISMATCH)
        if self._plan.data_class not in policy.allowed_data_classes:
            return self._decision(HostedPolicyReason.DATA_CLASS_MISMATCH)
        if self._plan.processing_region not in policy.allowed_processing_regions:
            return self._decision(HostedPolicyReason.PROCESSING_REGION_MISMATCH)
        if governance.residency_region not in policy.allowed_residency_regions:
            return self._decision(HostedPolicyReason.RESIDENCY_REGION_MISMATCH)
        if (
            policy.require_processing_in_residency
            and self._plan.processing_region != governance.residency_region
        ):
            return self._decision(
                HostedPolicyReason.PROCESSING_RESIDENCY_MISMATCH
            )
        if self._plan.retention_policy not in policy.allowed_retention_policies:
            return self._decision(HostedPolicyReason.RETENTION_POLICY_MISMATCH)
        if governance.egress_destination not in policy.allowed_egress_destinations:
            return self._decision(HostedPolicyReason.EGRESS_DESTINATION_MISMATCH)
        if self._transport_egress_destination != governance.egress_destination:
            return self._decision(HostedPolicyReason.EGRESS_DESTINATION_MISMATCH)
        if self._plan.redaction_decision not in policy.allowed_redaction_decisions:
            return self._decision(HostedPolicyReason.REDACTION_POLICY_MISMATCH)
        if not policy.subprocessor_approved:
            return self._decision(HostedPolicyReason.SUBPROCESSOR_NOT_APPROVED)
        if governance.cache_requested and not policy.allow_cache:
            return self._decision(HostedPolicyReason.CACHE_NOT_ALLOWED)
        if governance.request_scope == "whole_document" and not policy.allow_whole_document:
            return self._decision(HostedPolicyReason.WHOLE_DOCUMENT_NOT_ALLOWED)
        if self._phase06_policy.denial_reason(self._plan) is not None:
            return self._decision(HostedPolicyReason.PHASE06_POLICY_DENIED)
        return self._decision(HostedPolicyReason.APPROVED)

    def _emit(self, decision: HostedGovernanceDecision, *, validation: bool = False) -> None:
        if self._telemetry is None:
            return
        try:
            self._telemetry.event(
                "parser.hosted.policy",
                labels={
                    "outcome": "accepted" if decision.allowed else "denied",
                    "route": "hosted",
                    "reason": (
                        "validation_failed"
                        if validation
                        else "supported" if decision.allowed else "policy_denied"
                    ),
                    "adapter": "hosted",
                    "decision": "accept" if decision.allowed else "deny",
                },
            )
        except Exception:
            return

    def _record(self, result: HostedGatewayResult) -> HostedGatewayResult:
        safe = result.safe_record()
        with self._lock:
            self._audit.append(safe)
        return result

    def _invoke_local(
        self,
        request: VisualModelRequest,
        *,
        decision: HostedGovernanceDecision,
        transport_calls: int,
        hosted_result: HostedAdapterResult | None = None,
        hosted_failure_code: str | None = None,
    ) -> HostedGatewayResult:
        try:
            fallback_result = self._local_fallback.invoke(request)
        except Exception:
            unavailable = self._decision(
                HostedPolicyReason.LOCAL_FALLBACK_UNAVAILABLE
            )
            self._emit(unavailable, validation=True)
            return self._record(
                HostedGatewayResult(
                    status="local_unavailable",
                    decision=unavailable,
                    transport_calls=transport_calls,
                    fallback_invoked=True,
                    hosted_failure_code=hosted_failure_code,
                    hosted_result=hosted_result,
                )
            )
        contract_envelope = (
            fallback_result
            if isinstance(fallback_result, VisualModelContractEnvelope)
            else getattr(fallback_result, "contract_envelope", None)
        )
        if (
            not isinstance(contract_envelope, VisualModelContractEnvelope)
            or contract_envelope.status != "accepted"
            or contract_envelope.response is None
            or contract_envelope.response.identity.adapter_kind == "hosted"
        ):
            unavailable = self._decision(
                HostedPolicyReason.LOCAL_FALLBACK_UNAVAILABLE
            )
            self._emit(unavailable, validation=True)
            return self._record(
                HostedGatewayResult(
                    status="local_unavailable",
                    decision=unavailable,
                    transport_calls=transport_calls,
                    fallback_invoked=True,
                    hosted_failure_code=hosted_failure_code,
                    hosted_result=hosted_result,
                    fallback_result=fallback_result,
                )
            )
        return self._record(
            HostedGatewayResult(
                status="local_fallback",
                decision=decision,
                transport_calls=transport_calls,
                fallback_invoked=True,
                hosted_failure_code=hosted_failure_code,
                contract_envelope=contract_envelope,
                hosted_result=hosted_result,
                fallback_result=fallback_result,
            )
        )

    def invoke(self, request: VisualModelRequest) -> HostedGatewayResult:
        """Authorize before transport and deterministically fall back locally."""

        request = VisualModelRequest.model_validate(request, strict=True)
        decision = self.evaluate()
        if decision.allowed and not _crop_is_bound_to_region(request):
            decision = self._decision(HostedPolicyReason.CROP_REGION_MISMATCH)
        self._emit(decision)
        if not decision.allowed:
            return self._invoke_local(
                request,
                decision=decision,
                transport_calls=0,
            )

        hosted = self._adapter.invoke(request)
        calls = hosted.audit.transport_calls
        if hosted.status != "accepted" or hosted.contract_envelope is None:
            failure_code = hosted.failure.code if hosted.failure is not None else None
            fallback_decision = self._decision(
                HostedPolicyReason.HOSTED_ADAPTER_FALLBACK
            )
            self._emit(fallback_decision, validation=True)
            return self._invoke_local(
                request,
                decision=fallback_decision,
                transport_calls=calls,
                hosted_result=hosted,
                hosted_failure_code=failure_code,
            )

        response = hosted.contract_envelope.response
        identity = response.identity if response is not None else None
        policy = self._policy
        artifact = (
            self._manifest.artifact(policy.model_artifact_id)
            if policy is not None
            else None
        )
        if (
            identity is None
            or policy is None
            or artifact is None
            or identity.adapter_name != policy.vendor
            or identity.model_name != policy.model
            or identity.model_version != policy.model_version
            or identity.artifact_sha256 != policy.model_artifact_sha256
            or identity.artifact_source != artifact.source
            or identity.license_id != artifact.license_record
        ):
            mismatch = self._decision(
                HostedPolicyReason.RESPONSE_ARTIFACT_MISMATCH
            )
            self._emit(mismatch, validation=True)
            return self._invoke_local(
                request,
                decision=mismatch,
                transport_calls=calls,
                hosted_result=hosted,
                hosted_failure_code="response_artifact_mismatch",
            )

        return self._record(
            HostedGatewayResult(
                status="hosted",
                decision=decision,
                transport_calls=calls,
                fallback_invoked=False,
                contract_envelope=hosted.contract_envelope,
                hosted_result=hosted,
            )
        )


__all__ = [
    "HostedGatewayResult",
    "HostedGovernanceDecision",
    "HostedPolicyReason",
    "HostedReleaseGateway",
    "HostedReleasePolicy",
    "HostedReleasePolicyError",
    "HostedRequestGovernance",
    "LocalHostedFallback",
    "TrustedLocalHostedFallback",
    "trusted_local_hosted_fallback",
]
