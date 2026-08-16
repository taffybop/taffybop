"""Deny-by-default hosted visual-model adapter.

This module deliberately contains no HTTP client and no credential handling.
The only outbound boundary is :class:`HostedVisualModelTransport`, which is
implemented by deterministic test doubles in Phase 06.  A production
transport can only be added after the later hosted-use approvals are complete.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from app.services.visual_contracts import VisualBoundingBox
from app.services.visual_model_contracts import (
    VisualModelContract,
    VisualModelContractEnvelope,
    VisualModelCrop,
    VisualModelRequest,
    validate_visual_model_response,
)


_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_CODE_PATTERN = r"^[a-z][a-z0-9_]{2,95}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_OMITTED_METADATA = [
    "document_sha256",
    "evidence_source_object_ids",
    "evidence_source_token_ids",
    "evidence_text",
    "public_item_id",
]
_SENT_METADATA = [
    "evidence_geometry",
    "evidence_ids",
    "observation_types",
    "page_geometry",
    "region_id",
]

HostedFailureCode = Literal[
    "feature_disabled",
    "policy_approval_missing",
    "data_approval_missing",
    "minimization_approval_missing",
    "retention_approval_missing",
    "vendor_denied",
    "model_denied",
    "processing_region_denied",
    "data_class_denied",
    "retention_policy_denied",
    "budget_requests_exhausted",
    "budget_request_pixels_exhausted",
    "budget_document_pixels_exhausted",
    "budget_cost_exhausted",
    "budget_tokens_exhausted",
    "budget_timeout_exhausted",
    "minimization_failed",
    "timeout",
    "quota",
    "transport_error",
    "transport_reply_malformed",
    "transport_usage_exceeded",
    "malformed_response",
    "unsafe_response",
]


def _sorted_unique(values: list[str], label: str) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be sorted and unique")


class HostedPolicy(VisualModelContract):
    """Exact allow policy; every default denies hosted dispatch."""

    feature_enabled: bool = False
    policy_approved: bool = False
    data_approved: bool = False
    minimization_approved: bool = False
    retention_approved: bool = False
    allowed_vendors: list[str] = Field(default_factory=list, max_length=64)
    allowed_models: list[str] = Field(default_factory=list, max_length=128)
    allowed_processing_regions: list[str] = Field(
        default_factory=list,
        max_length=64,
    )
    allowed_data_classes: list[str] = Field(default_factory=list, max_length=64)
    allowed_retention_policies: list[str] = Field(
        default_factory=list,
        max_length=64,
    )

    @model_validator(mode="after")
    def validate_allowlists(self) -> "HostedPolicy":
        for label, values in (
            ("allowed vendors", self.allowed_vendors),
            ("allowed models", self.allowed_models),
            ("allowed processing regions", self.allowed_processing_regions),
            ("allowed data classes", self.allowed_data_classes),
            ("allowed retention policies", self.allowed_retention_policies),
        ):
            _sorted_unique(values, label)
            if any(not value or len(value) > 128 for value in values):
                raise ValueError(f"{label} contains an invalid value")
        return self

    def denial_reason(
        self,
        plan: "HostedDispatchPlan",
    ) -> HostedFailureCode | None:
        """Return the first stable denial; membership is exact/case-sensitive."""

        if not self.feature_enabled:
            return "feature_disabled"
        if not self.policy_approved:
            return "policy_approval_missing"
        if not self.data_approved:
            return "data_approval_missing"
        if not self.minimization_approved:
            return "minimization_approval_missing"
        if not self.retention_approved:
            return "retention_approval_missing"
        if plan.vendor not in self.allowed_vendors:
            return "vendor_denied"
        if plan.model not in self.allowed_models:
            return "model_denied"
        if plan.processing_region not in self.allowed_processing_regions:
            return "processing_region_denied"
        if plan.data_class not in self.allowed_data_classes:
            return "data_class_denied"
        if plan.retention_policy not in self.allowed_retention_policies:
            return "retention_policy_denied"
        return None


class HostedDispatchPlan(VisualModelContract):
    """One explicitly authorized, bounded hosted call."""

    vendor: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    processing_region: str = Field(min_length=1, max_length=128)
    data_class: str = Field(min_length=1, max_length=128)
    retention_policy: str = Field(min_length=1, max_length=128)
    redaction_decision: Literal["applied", "not_required"]
    redaction_context_id: str = Field(pattern=_ID_PATTERN)
    reserved_cost_microunits: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    timeout_ms: int = Field(ge=1)
    max_attempts: Literal[1] = 1


class HostedBudgetSnapshot(VisualModelContract):
    max_requests: int = Field(ge=0)
    max_request_pixels: int = Field(ge=0)
    max_document_pixels: int = Field(ge=0)
    max_cost_microunits: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_timeout_ms: int = Field(ge=0)
    used_requests: int = Field(ge=0)
    used_document_pixels: int = Field(ge=0)
    used_cost_microunits: int = Field(ge=0)
    used_output_tokens: int = Field(ge=0)
    used_timeout_ms: int = Field(ge=0)
    remaining_requests: int = Field(ge=0)
    remaining_document_pixels: int = Field(ge=0)
    remaining_cost_microunits: int = Field(ge=0)
    remaining_output_tokens: int = Field(ge=0)
    remaining_timeout_ms: int = Field(ge=0)


class HostedMinimizationAudit(VisualModelContract):
    crop_scope: Literal["approved_region_only"]
    metadata_scope: Literal["contract_minimum"]
    redaction_decision: Literal["applied", "not_required"]
    redaction_context_sha256: str = Field(pattern=_SHA256_PATTERN)
    omitted_metadata: list[str]
    sent_metadata: list[str]
    crop_pixels: int = Field(ge=0)
    crop_bytes: int = Field(ge=0)
    evidence_records: int = Field(ge=0)
    payload_logged: Literal[False] = False
    credentials_logged: Literal[False] = False

    @model_validator(mode="after")
    def validate_metadata_inventory(self) -> "HostedMinimizationAudit":
        if self.omitted_metadata != _OMITTED_METADATA:
            raise ValueError("hosted omitted-metadata inventory differs")
        if self.sent_metadata != _SENT_METADATA:
            raise ValueError("hosted sent-metadata inventory differs")
        return self


class HostedAuditEvent(VisualModelContract):
    event_id: str = Field(pattern=_SHA256_PATTERN)
    request_id: str = Field(pattern=_ID_PATTERN)
    region_id: str = Field(pattern=_ID_PATTERN)
    decision: Literal["denied", "accepted", "rejected"]
    code: str = Field(pattern=_CODE_PATTERN)
    vendor: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    processing_region: str = Field(min_length=1, max_length=128)
    data_class: str = Field(min_length=1, max_length=128)
    retention_policy: str = Field(min_length=1, max_length=128)
    transport_calls: Literal[0, 1]
    minimization: HostedMinimizationAudit
    budget_before: HostedBudgetSnapshot
    budget_after: HostedBudgetSnapshot


class HostedAdapterFailure(VisualModelContract):
    code: HostedFailureCode
    stage: Literal["policy", "budget", "minimization", "transport", "contract"]
    retryable: Literal[False] = False
    budget_dimension: Literal[
        "requests",
        "request_pixels",
        "document_pixels",
        "cost",
        "tokens",
        "timeout",
    ] | None = None
    contract_concern_codes: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_concerns(self) -> "HostedAdapterFailure":
        _sorted_unique(self.contract_concern_codes, "contract concern codes")
        if any(
            not code or len(code) > 96 for code in self.contract_concern_codes
        ):
            raise ValueError("contract concern code is invalid")
        return self


class HostedAdapterResult(VisualModelContract):
    status: Literal["accepted", "fallback"]
    contract_envelope: VisualModelContractEnvelope | None = None
    failure: HostedAdapterFailure | None = None
    audit: HostedAuditEvent

    @model_validator(mode="after")
    def validate_result(self) -> "HostedAdapterResult":
        if self.status == "accepted":
            if (
                self.failure is not None
                or self.contract_envelope is None
                or self.contract_envelope.status != "accepted"
                or self.audit.decision != "accepted"
            ):
                raise ValueError("accepted hosted result state differs")
        elif (
            self.failure is None
            or self.contract_envelope is not None
            or self.audit.decision == "accepted"
        ):
            raise ValueError("fallback hosted result state differs")
        return self


class HostedMinimizedEvidence(VisualModelContract):
    """Evidence identity/geometry only; text and internal source IDs are omitted."""

    id: str = Field(pattern=_ID_PATTERN)
    kind: str = Field(min_length=1, max_length=64)
    page_bbox: VisualBoundingBox | None = None
    source_origin: str = Field(min_length=1, max_length=64)


class HostedMinimizedRegion(VisualModelContract):
    id: str = Field(pattern=_ID_PATTERN)
    page_index: int = Field(ge=1, le=1_000_000)
    kind: Literal["image", "chart", "diagram"]
    page_bbox: VisualBoundingBox
    evidence_ids: list[str] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> "HostedMinimizedRegion":
        _sorted_unique(self.evidence_ids, "hosted region evidence IDs")
        return self


class HostedMinimizedRequest(VisualModelContract):
    """The complete and only payload supplied to a hosted transport."""

    schema_version: Literal["1.0"]
    request_id: str = Field(pattern=_ID_PATTERN)
    region: HostedMinimizedRegion
    crop: VisualModelCrop = Field(repr=False)
    evidence: list[HostedMinimizedEvidence] = Field(min_length=1, max_length=256)
    requested_observation_types: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_minimized_graph(self) -> "HostedMinimizedRequest":
        evidence_ids = [record.id for record in self.evidence]
        _sorted_unique(evidence_ids, "hosted evidence IDs")
        if not set(self.region.evidence_ids) <= set(evidence_ids):
            raise ValueError("hosted region references omitted evidence")
        _sorted_unique(
            self.requested_observation_types,
            "hosted observation types",
        )
        return self


class HostedTransportCall(VisualModelContract):
    vendor: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    processing_region: str = Field(min_length=1, max_length=128)
    retention_policy: str = Field(min_length=1, max_length=128)
    timeout_ms: int = Field(ge=1)
    max_output_tokens: int = Field(ge=1)
    request: HostedMinimizedRequest = Field(repr=False)


class HostedTransportReply(VisualModelContract):
    """Raw provider response plus bounded, integer accounting."""

    response: Any = Field(repr=False)
    actual_cost_microunits: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)


class HostedTransportError(RuntimeError):
    """Base error whose text is deliberately never copied to audit output."""


class HostedTransportTimeout(HostedTransportError):
    pass


class HostedTransportQuota(HostedTransportError):
    pass


@runtime_checkable
class HostedVisualModelTransport(Protocol):
    """No-network interface for an approved hosted transport implementation."""

    def invoke(self, call: HostedTransportCall) -> HostedTransportReply: ...


@dataclass(slots=True)
class _BudgetReservation:
    reserved_cost_microunits: int
    reserved_output_tokens: int
    reserved_timeout_ms: int
    settled: bool = False


class HostedBudget:
    """Thread-safe per-document reservation and exact usage ledger.

    All limits default to zero, so merely constructing a budget never grants
    dispatch authority.  A failed or unaccountable call consumes its full
    reservation; a successful reply releases only the verified unused amount.
    """

    def __init__(
        self,
        *,
        max_requests: int = 0,
        max_request_pixels: int = 0,
        max_document_pixels: int = 0,
        max_cost_microunits: int = 0,
        max_output_tokens: int = 0,
        max_timeout_ms: int = 0,
    ) -> None:
        limits = {
            "max_requests": max_requests,
            "max_request_pixels": max_request_pixels,
            "max_document_pixels": max_document_pixels,
            "max_cost_microunits": max_cost_microunits,
            "max_output_tokens": max_output_tokens,
            "max_timeout_ms": max_timeout_ms,
        }
        if any(type(value) is not int or value < 0 for value in limits.values()):
            raise ValueError("hosted budget limits must be non-negative integers")
        self._max_requests = max_requests
        self._max_request_pixels = max_request_pixels
        self._max_document_pixels = max_document_pixels
        self._max_cost_microunits = max_cost_microunits
        self._max_output_tokens = max_output_tokens
        self._max_timeout_ms = max_timeout_ms
        self._used_requests = 0
        self._used_document_pixels = 0
        self._used_cost_microunits = 0
        self._used_output_tokens = 0
        self._used_timeout_ms = 0
        self._lock = Lock()

    def _snapshot_unlocked(self) -> HostedBudgetSnapshot:
        return HostedBudgetSnapshot(
            max_requests=self._max_requests,
            max_request_pixels=self._max_request_pixels,
            max_document_pixels=self._max_document_pixels,
            max_cost_microunits=self._max_cost_microunits,
            max_output_tokens=self._max_output_tokens,
            max_timeout_ms=self._max_timeout_ms,
            used_requests=self._used_requests,
            used_document_pixels=self._used_document_pixels,
            used_cost_microunits=self._used_cost_microunits,
            used_output_tokens=self._used_output_tokens,
            used_timeout_ms=self._used_timeout_ms,
            remaining_requests=self._max_requests - self._used_requests,
            remaining_document_pixels=(
                self._max_document_pixels - self._used_document_pixels
            ),
            remaining_cost_microunits=(
                self._max_cost_microunits - self._used_cost_microunits
            ),
            remaining_output_tokens=(
                self._max_output_tokens - self._used_output_tokens
            ),
            remaining_timeout_ms=self._max_timeout_ms - self._used_timeout_ms,
        )

    def snapshot(self) -> HostedBudgetSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def _reserve(
        self,
        *,
        pixels: int,
        cost_microunits: int,
        output_tokens: int,
        timeout_ms: int,
    ) -> tuple[_BudgetReservation | None, HostedFailureCode | None, str | None]:
        with self._lock:
            remaining_requests = self._max_requests - self._used_requests
            remaining_pixels = (
                self._max_document_pixels - self._used_document_pixels
            )
            remaining_cost = (
                self._max_cost_microunits - self._used_cost_microunits
            )
            remaining_tokens = self._max_output_tokens - self._used_output_tokens
            remaining_timeout = self._max_timeout_ms - self._used_timeout_ms
            if remaining_requests <= 0:
                return None, "budget_requests_exhausted", "requests"
            if self._max_request_pixels <= 0 or pixels > self._max_request_pixels:
                return None, "budget_request_pixels_exhausted", "request_pixels"
            if remaining_pixels <= 0 or pixels > remaining_pixels:
                return None, "budget_document_pixels_exhausted", "document_pixels"
            if remaining_cost <= 0 or cost_microunits > remaining_cost:
                return None, "budget_cost_exhausted", "cost"
            if remaining_tokens <= 0 or output_tokens > remaining_tokens:
                return None, "budget_tokens_exhausted", "tokens"
            if remaining_timeout <= 0 or timeout_ms > remaining_timeout:
                return None, "budget_timeout_exhausted", "timeout"
            self._used_requests += 1
            self._used_document_pixels += pixels
            self._used_cost_microunits += cost_microunits
            self._used_output_tokens += output_tokens
            self._used_timeout_ms += timeout_ms
            return (
                _BudgetReservation(
                    reserved_cost_microunits=cost_microunits,
                    reserved_output_tokens=output_tokens,
                    reserved_timeout_ms=timeout_ms,
                ),
                None,
                None,
            )

    def _settle(
        self,
        reservation: _BudgetReservation,
        *,
        actual_cost_microunits: int,
        actual_output_tokens: int,
        actual_timeout_ms: int,
    ) -> bool:
        with self._lock:
            if reservation.settled:
                return False
            reservation.settled = True
            actual = (
                actual_cost_microunits,
                actual_output_tokens,
                actual_timeout_ms,
            )
            reserved = (
                reservation.reserved_cost_microunits,
                reservation.reserved_output_tokens,
                reservation.reserved_timeout_ms,
            )
            if any(type(value) is not int or value < 0 for value in actual) or any(
                observed > limit for observed, limit in zip(actual, reserved)
            ):
                return False
            self._used_cost_microunits -= reserved[0] - actual[0]
            self._used_output_tokens -= reserved[1] - actual[1]
            self._used_timeout_ms -= reserved[2] - actual[2]
            return True

    def _consume(self, reservation: _BudgetReservation) -> None:
        with self._lock:
            reservation.settled = True


class DeterministicHostedTransport:
    """In-memory transport double; it performs no DNS, HTTP, or model call."""

    def __init__(
        self,
        response: Any = None,
        *,
        outcome: Literal["success", "timeout", "quota", "error"] = "success",
        actual_cost_microunits: int = 0,
        output_tokens: int = 0,
        elapsed_ms: int = 0,
    ) -> None:
        self._response = deepcopy(response)
        self._outcome = outcome
        self._actual_cost_microunits = actual_cost_microunits
        self._output_tokens = output_tokens
        self._elapsed_ms = elapsed_ms
        self.calls: list[HostedTransportCall] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def invoke(self, call: HostedTransportCall) -> HostedTransportReply:
        self.calls.append(call)
        if self._outcome == "timeout":
            raise HostedTransportTimeout("details intentionally not retained")
        if self._outcome == "quota":
            raise HostedTransportQuota("details intentionally not retained")
        if self._outcome == "error":
            raise HostedTransportError("details intentionally not retained")
        return HostedTransportReply(
            response=deepcopy(self._response),
            actual_cost_microunits=self._actual_cost_microunits,
            output_tokens=self._output_tokens,
            elapsed_ms=self._elapsed_ms,
        )


def _minimize_request(request: VisualModelRequest) -> HostedMinimizedRequest:
    return HostedMinimizedRequest(
        schema_version="1.0",
        request_id=request.request_id,
        region=HostedMinimizedRegion(
            id=request.region.id,
            page_index=request.region.page_index,
            kind=request.region.kind,
            page_bbox=request.region.page_bbox,
            evidence_ids=list(request.region.evidence_ids),
        ),
        crop=request.crop,
        evidence=[
            HostedMinimizedEvidence(
                id=evidence.id,
                kind=evidence.kind,
                page_bbox=evidence.page_bbox,
                source_origin=evidence.source_origin,
            )
            for evidence in request.evidence
        ],
        requested_observation_types=list(request.requested_observation_types),
    )


def _minimization_audit(
    request: VisualModelRequest,
    plan: HostedDispatchPlan,
) -> HostedMinimizationAudit:
    return HostedMinimizationAudit(
        crop_scope="approved_region_only",
        metadata_scope="contract_minimum",
        redaction_decision=plan.redaction_decision,
        redaction_context_sha256=hashlib.sha256(
            plan.redaction_context_id.encode("utf-8")
        ).hexdigest(),
        omitted_metadata=list(_OMITTED_METADATA),
        sent_metadata=list(_SENT_METADATA),
        crop_pixels=request.crop.width * request.crop.height,
        crop_bytes=request.crop.byte_length,
        evidence_records=len(request.evidence),
        payload_logged=False,
        credentials_logged=False,
    )


def _audit_event(
    *,
    request: VisualModelRequest,
    plan: HostedDispatchPlan,
    decision: Literal["denied", "accepted", "rejected"],
    code: str,
    transport_calls: Literal[0, 1],
    minimization: HostedMinimizationAudit,
    budget_before: HostedBudgetSnapshot,
    budget_after: HostedBudgetSnapshot,
) -> HostedAuditEvent:
    safe = {
        "request_id": request.request_id,
        "region_id": request.region.id,
        "decision": decision,
        "code": code,
        "vendor": plan.vendor,
        "model": plan.model,
        "processing_region": plan.processing_region,
        "data_class": plan.data_class,
        "retention_policy": plan.retention_policy,
        "transport_calls": transport_calls,
        "minimization": minimization.model_dump(mode="json"),
        "budget_before": budget_before.model_dump(mode="json"),
        "budget_after": budget_after.model_dump(mode="json"),
    }
    event_id = hashlib.sha256(
        json.dumps(
            safe,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return HostedAuditEvent(event_id=event_id, **safe)


class HostedVisualModelAdapter:
    """Authorize, reserve, minimize, invoke once, validate, and account."""

    kind: Literal["hosted"] = "hosted"

    def __init__(
        self,
        *,
        transport: HostedVisualModelTransport,
        policy: HostedPolicy,
        budget: HostedBudget,
        plan: HostedDispatchPlan,
    ) -> None:
        self._transport = transport
        self._policy = HostedPolicy.model_validate(policy, strict=True)
        self._budget = budget
        self._plan = HostedDispatchPlan.model_validate(plan, strict=True)
        self._audit_events: list[HostedAuditEvent] = []
        self._attributable_costs: dict[str, int] = {}
        self._audit_lock = Lock()

    @property
    def audit_events(self) -> tuple[HostedAuditEvent, ...]:
        with self._audit_lock:
            return tuple(self._audit_events)

    def is_available(self) -> bool:
        return self._policy.feature_enabled

    def _record(
        self,
        event: HostedAuditEvent,
        *,
        actual_cost_microunits: int | None = None,
    ) -> None:
        with self._audit_lock:
            self._audit_events.append(event)
            if actual_cost_microunits is not None:
                self._attributable_costs[event.event_id] = actual_cost_microunits

    def attributable_cost_microunits(
        self,
        result: HostedAdapterResult,
    ) -> int | None:
        """Return exact reply usage for this adapter result, when available."""

        if not isinstance(result, HostedAdapterResult):
            return None
        with self._audit_lock:
            return self._attributable_costs.get(result.audit.event_id)

    def _fallback(
        self,
        *,
        request: VisualModelRequest,
        code: HostedFailureCode,
        stage: Literal["policy", "budget", "minimization", "transport", "contract"],
        decision: Literal["denied", "rejected"],
        calls: Literal[0, 1],
        minimization: HostedMinimizationAudit,
        before: HostedBudgetSnapshot,
        after: HostedBudgetSnapshot,
        dimension: str | None = None,
        concerns: list[str] | None = None,
        actual_cost_microunits: int | None = None,
    ) -> HostedAdapterResult:
        failure = HostedAdapterFailure(
            code=code,
            stage=stage,
            budget_dimension=dimension,
            contract_concern_codes=sorted(set(concerns or [])),
        )
        audit = _audit_event(
            request=request,
            plan=self._plan,
            decision=decision,
            code=code,
            transport_calls=calls,
            minimization=minimization,
            budget_before=before,
            budget_after=after,
        )
        self._record(
            audit,
            actual_cost_microunits=actual_cost_microunits,
        )
        return HostedAdapterResult(
            status="fallback",
            failure=failure,
            audit=audit,
        )

    def invoke(self, request: VisualModelRequest) -> HostedAdapterResult:
        request = VisualModelRequest.model_validate(request, strict=True)
        before = self._budget.snapshot()
        minimization = _minimization_audit(request, self._plan)
        denial = self._policy.denial_reason(self._plan)
        if denial is not None:
            return self._fallback(
                request=request,
                code=denial,
                stage="policy",
                decision="denied",
                calls=0,
                minimization=minimization,
                before=before,
                after=before,
            )
        try:
            minimized = _minimize_request(request)
        except (MemoryError, TypeError, ValueError, OverflowError):
            return self._fallback(
                request=request,
                code="minimization_failed",
                stage="minimization",
                decision="rejected",
                calls=0,
                minimization=minimization,
                before=before,
                after=before,
            )
        reservation, budget_code, dimension = self._budget._reserve(
            pixels=request.crop.width * request.crop.height,
            cost_microunits=self._plan.reserved_cost_microunits,
            output_tokens=self._plan.max_output_tokens,
            timeout_ms=self._plan.timeout_ms,
        )
        if reservation is None:
            return self._fallback(
                request=request,
                code=budget_code or "budget_requests_exhausted",
                stage="budget",
                decision="denied",
                calls=0,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
                dimension=dimension,
            )
        call = HostedTransportCall(
            vendor=self._plan.vendor,
            model=self._plan.model,
            processing_region=self._plan.processing_region,
            retention_policy=self._plan.retention_policy,
            timeout_ms=self._plan.timeout_ms,
            max_output_tokens=self._plan.max_output_tokens,
            request=minimized,
        )
        try:
            raw_reply = self._transport.invoke(call)
        except HostedTransportTimeout:
            self._budget._consume(reservation)
            return self._fallback(
                request=request,
                code="timeout",
                stage="transport",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
            )
        except HostedTransportQuota:
            self._budget._consume(reservation)
            return self._fallback(
                request=request,
                code="quota",
                stage="transport",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
            )
        except Exception:
            self._budget._consume(reservation)
            return self._fallback(
                request=request,
                code="transport_error",
                stage="transport",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
            )
        try:
            reply = HostedTransportReply.model_validate(raw_reply, strict=True)
        except (MemoryError, TypeError, ValueError, OverflowError):
            self._budget._consume(reservation)
            return self._fallback(
                request=request,
                code="transport_reply_malformed",
                stage="transport",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
            )
        if not self._budget._settle(
            reservation,
            actual_cost_microunits=reply.actual_cost_microunits,
            actual_output_tokens=reply.output_tokens,
            actual_timeout_ms=reply.elapsed_ms,
        ):
            return self._fallback(
                request=request,
                code="transport_usage_exceeded",
                stage="transport",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
                actual_cost_microunits=reply.actual_cost_microunits,
            )
        envelope = validate_visual_model_response(request, reply.response)
        if envelope.status != "accepted" or envelope.response is None:
            concerns = [concern.code for concern in envelope.concerns]
            malformed_codes = {
                "visual_model_response_limit",
                "visual_model_response_malformed",
            }
            code: HostedFailureCode = (
                "malformed_response"
                if concerns and set(concerns) <= malformed_codes
                else "unsafe_response"
            )
            return self._fallback(
                request=request,
                code=code,
                stage="contract",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
                concerns=concerns,
                actual_cost_microunits=reply.actual_cost_microunits,
            )
        identity = envelope.response.identity
        if (
            identity.adapter_kind not in {"hosted", "test_double"}
            or identity.adapter_name != self._plan.vendor
            or identity.model_name != self._plan.model
        ):
            return self._fallback(
                request=request,
                code="unsafe_response",
                stage="contract",
                decision="rejected",
                calls=1,
                minimization=minimization,
                before=before,
                after=self._budget.snapshot(),
                concerns=["visual_model_hosted_identity_mismatch"],
                actual_cost_microunits=reply.actual_cost_microunits,
            )
        after = self._budget.snapshot()
        audit = _audit_event(
            request=request,
            plan=self._plan,
            decision="accepted",
            code="hosted_response_accepted",
            transport_calls=1,
            minimization=minimization,
            budget_before=before,
            budget_after=after,
        )
        self._record(
            audit,
            actual_cost_microunits=reply.actual_cost_microunits,
        )
        return HostedAdapterResult(
            status="accepted",
            contract_envelope=envelope,
            audit=audit,
        )


__all__ = [
    "DeterministicHostedTransport",
    "HostedAdapterFailure",
    "HostedAdapterResult",
    "HostedAuditEvent",
    "HostedBudget",
    "HostedBudgetSnapshot",
    "HostedDispatchPlan",
    "HostedMinimizationAudit",
    "HostedMinimizedEvidence",
    "HostedMinimizedRegion",
    "HostedMinimizedRequest",
    "HostedPolicy",
    "HostedTransportCall",
    "HostedTransportError",
    "HostedTransportQuota",
    "HostedTransportReply",
    "HostedTransportTimeout",
    "HostedVisualModelAdapter",
    "HostedVisualModelTransport",
]
