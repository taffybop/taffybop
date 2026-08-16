"""Bounded operational signals for quality, fallback, routes, and cost.

These events describe parser decisions, not extraction accuracy and not
statistically calibrated probabilities.  Every label is reduced to an enum
owned by :mod:`app.services.telemetry`; source values, identifiers, filenames,
prompts, crops, provider messages, and credentials have no output field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.services.telemetry import TelemetryClient, current_telemetry_client


_MAX_ATTRIBUTABLE_COST_MICRO_UNITS = 1_000_000_000_000

_SUPPORTED_REASONS = frozenset(
    {
        "accepted",
        "complete_region",
        "completed",
        "eligible",
        "hosted_response_accepted",
        "route_hosted",
        "route_local",
        "supported",
    }
)
_UNSUPPORTED_REASONS = frozenset(
    {
        "contract_disabled",
        "non_target_region",
        "routing_disabled",
        "unsupported",
    }
)
_VALIDATION_REASONS = frozenset(
    {
        "gap_not_evidenced",
        "malformed_response",
        "missing_phase05_contract",
        "transport_reply_malformed",
        "unsafe_response",
        "validation_failed",
        "visual_model_response_limit",
        "visual_model_response_malformed",
    }
)
_POLICY_REASONS = frozenset(
    {
        "data_approval_missing",
        "data_class_denied",
        "feature_disabled",
        "hosted_policy_denied",
        "minimization_approval_missing",
        "model_denied",
        "policy_approval_missing",
        "policy_denied",
        "processing_region_denied",
        "retention_approval_missing",
        "retention_policy_denied",
        "vendor_denied",
    }
)
_ADAPTER_UNAVAILABLE_REASONS = frozenset(
    {
        "adapter_unavailable",
        "local_visual_model_artifact_invalid",
        "local_visual_model_artifact_missing",
        "local_visual_model_artifact_unapproved",
        "local_visual_model_disabled",
        "no_adapter_available",
    }
)
_BUDGET_REASONS = frozenset(
    {
        "area_limit",
        "budget_cost_exhausted",
        "budget_document_pixels_exhausted",
        "budget_exhausted",
        "budget_request_pixels_exhausted",
        "budget_requests_exhausted",
        "budget_timeout_exhausted",
        "budget_tokens_exhausted",
        "region_limit",
    }
)
_TIMEOUT_REASONS = frozenset(
    {
        "local_visual_model_timeout",
        "timeout",
    }
)
_RAISED_REASONS = frozenset(
    {
        "adapter_failed",
        "local_visual_model_inference_failed",
        "local_visual_model_loader_failed",
        "quota",
        "raised",
        "transport_error",
        "transport_usage_exceeded",
    }
)

_SOURCE_ORIGINS = frozenset(
    {
        "explicit_text",
        "layout",
        "native",
        "ocr",
        "raster",
        "source",
        "source_transcription",
        "vector",
    }
)
_DERIVED_ORIGINS = frozenset(
    {
        "derived",
        "inferred",
        "model_derived_measurement",
        "model_inferred_relationship",
        "model_visual_identification",
    }
)
_GENERATED_ORIGINS = frozenset(
    {
        "generated",
        "model_generated_description",
    }
)


def _safe_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized or None


def bounded_reason(value: Any) -> str:
    """Map an internal reason to the fixed public telemetry vocabulary."""

    reason = _safe_string(value)
    if reason in _SUPPORTED_REASONS:
        return "supported"
    if reason in _UNSUPPORTED_REASONS:
        return "unsupported"
    if reason in _VALIDATION_REASONS:
        return "validation_failed"
    if reason in _POLICY_REASONS:
        return "policy_denied"
    if reason in _ADAPTER_UNAVAILABLE_REASONS:
        return "adapter_unavailable"
    if reason in _BUDGET_REASONS:
        return "budget_exhausted"
    if reason in _TIMEOUT_REASONS:
        return "timeout"
    if reason in _RAISED_REASONS:
        return "raised"
    return "unknown"


def bounded_origin(value: Any) -> str:
    """Classify provenance without retaining its source representation."""

    origin = _safe_string(value)
    if origin is None or origin == "none":
        return "none"
    if origin in _SOURCE_ORIGINS:
        return "source"
    if origin in _DERIVED_ORIGINS:
        return "derived"
    if origin in _GENERATED_ORIGINS:
        return "generated"
    if origin == "unverifiable":
        return "unverifiable"
    return "unverifiable"


def bounded_content_type(value: Any) -> str:
    content_type = _safe_string(value)
    if content_type in {"paragraph", "heading", "list", "list_item"}:
        return "text"
    if content_type in {"region", "page"}:
        return "layout"
    if content_type in {
        "text",
        "layout",
        "table",
        "chart",
        "diagram",
        "image",
        "document",
    }:
        return content_type
    return "unknown"


def bounded_route(value: Any) -> str:
    route = _safe_string(value)
    if route in {"deterministic", "local", "hosted", "review", "none"}:
        return route
    return "none"


def bounded_adapter(value: Any) -> str:
    adapter = _safe_string(value)
    if adapter in {"deterministic", "local", "hosted", "none"}:
        return adapter
    return "none"


def _bounded_cost(value: Any) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= _MAX_ATTRIBUTABLE_COST_MICRO_UNITS
    ):
        return value
    return None


def _member(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _hosted_audit_cost(adapter_result: Any) -> tuple[str, int | None]:
    """Classify call presence only; a reservation delta is not actual cost."""

    audit = _member(adapter_result, "audit")
    if audit is None:
        return "unknown", None
    calls = _member(audit, "transport_calls")
    if calls == 0:
        return "not_applicable", None
    if calls != 1:
        return "unknown", None
    return "unknown", None


def attributable_cost(
    adapter_result: Any,
    *,
    adapter: Any,
    invoked: bool,
    actual_cost_microunits: Any = None,
) -> tuple[str, int | None]:
    """Return exact cost only when a result contains attributable usage."""

    if not invoked:
        return "not_applicable", None
    adapter_class = bounded_adapter(adapter)
    if adapter_class in {"local", "deterministic", "none"}:
        return "not_applicable", None
    direct = _bounded_cost(actual_cost_microunits)
    if direct is None:
        direct = _bounded_cost(_member(adapter_result, "actual_cost_microunits"))
    if direct is not None:
        return "known", direct
    return _hosted_audit_cost(adapter_result)


@dataclass(frozen=True, slots=True)
class QualityTelemetry:
    """Failure-isolated observer over the common bounded telemetry client."""

    client: TelemetryClient | None = None
    enabled: bool = False

    def _client(self) -> TelemetryClient:
        return self.client or current_telemetry_client()

    def _event(
        self,
        name: str,
        labels: Mapping[str, str],
        *,
        value: int = 1,
    ) -> bool:
        if not self.enabled:
            return False
        try:
            bounded_value = (
                value
                if isinstance(value, int)
                and not isinstance(value, bool)
                and 1 <= value <= 256
                else 1
            )
            return self._client().counter(
                name,
                labels=labels,
                value=bounded_value,
            )
        except Exception:
            # Telemetry is never part of the parser's success boundary.
            return False

    def quality_decision(
        self,
        *,
        decision: str,
        reason: Any,
        origin: Any,
        content_type: Any,
        route: Any = "deterministic",
        outcome: str = "success",
        value: int = 1,
    ) -> bool:
        safe_decision = (
            decision
            if decision
            in {"accept", "concern", "fallback", "withhold", "skip", "deny"}
            else "unknown"
        )
        safe_outcome = (
            outcome
            if outcome
            in {
                "success",
                "error",
                "fallback",
                "denied",
                "withheld",
                "accepted",
                "unknown",
            }
            else "unknown"
        )
        return self._event(
            "parser.quality.decision",
            {
                "content_type": bounded_content_type(content_type),
                "decision": safe_decision,
                "origin": bounded_origin(origin),
                "outcome": safe_outcome,
                "reason": bounded_reason(reason),
                "route": bounded_route(route),
            },
            value=value,
        )

    def fallback(
        self,
        *,
        reason: Any,
        content_type: Any,
        route: Any = "deterministic",
        origin: Any = "none",
    ) -> bool:
        return self.quality_decision(
            decision="fallback",
            reason=reason,
            origin=origin,
            content_type=content_type,
            route=route,
            outcome="fallback",
        )

    def route_decision(
        self,
        *,
        route: Any,
        adapter: Any,
        decision: str,
        reason: Any,
        outcome: str,
        content_type: Any,
    ) -> bool:
        safe_decision = (
            decision
            if decision in {"route", "fallback", "skip", "deny"}
            else "unknown"
        )
        safe_outcome = (
            outcome
            if outcome
            in {
                "success",
                "error",
                "fallback",
                "denied",
                "withheld",
                "accepted",
                "unknown",
            }
            else "unknown"
        )
        return self._event(
            "parser.route.decision",
            {
                "adapter": bounded_adapter(adapter),
                "content_type": bounded_content_type(content_type),
                "decision": safe_decision,
                "outcome": safe_outcome,
                "reason": bounded_reason(reason),
                "route": bounded_route(route),
            },
        )

    def cost_usage(
        self,
        *,
        route: Any,
        adapter: Any,
        status: str,
        actual_cost_microunits: Any = None,
        outcome: str = "unknown",
    ) -> bool:
        safe_status = (
            status if status in {"known", "unknown", "not_applicable"} else "unknown"
        )
        safe_outcome = (
            outcome
            if outcome
            in {"success", "error", "fallback", "denied", "accepted", "unknown"}
            else "unknown"
        )
        if not self.enabled:
            return False
        try:
            cost = _bounded_cost(actual_cost_microunits)
            if safe_status == "known" and cost is None:
                safe_status = "unknown"
            labels = {
                "adapter": bounded_adapter(adapter),
                "cost_status": safe_status,
                "outcome": safe_outcome,
                "route": bounded_route(route),
            }
            if safe_status == "known" and cost is not None:
                return self._client().emit(
                    name="parser.cost.usage",
                    kind="counter",
                    value=cost,
                    unit="micro_units",
                    labels=labels,
                )
            return self._client().event("parser.cost.usage", labels=labels)
        except Exception:
            return False

    def visual_route(
        self,
        decision: Any,
        *,
        content_type: Any,
        adapter_result: Any = None,
        contract_envelope: Any = None,
        failure_code: Any = None,
        invoked: bool = False,
        actual_cost_microunits: Any = None,
    ) -> None:
        """Observe one finalized Phase 06 route without retaining its request."""

        action = bounded_route(_member(decision, "action"))
        selected = bounded_adapter(_member(decision, "selected_adapter"))
        route_reason = _member(decision, "reason")
        if action == "none":
            mapped_reason = bounded_reason(route_reason)
            denied = mapped_reason == "policy_denied"
            deterministic_success = mapped_reason == "supported"
            fallback = mapped_reason in {
                "adapter_unavailable",
                "budget_exhausted",
                "raised",
                "timeout",
                "validation_failed",
            }
            route = (
                "hosted"
                if denied
                else ("deterministic" if deterministic_success else "none")
            )
            self.route_decision(
                route=route,
                adapter=(
                    "none"
                    if denied
                    else ("deterministic" if deterministic_success else "none")
                ),
                decision="deny" if denied else ("fallback" if fallback else "skip"),
                reason=route_reason,
                outcome=(
                    "denied"
                    if denied
                    else (
                        "fallback"
                        if fallback
                        else ("success" if deterministic_success else "withheld")
                    )
                ),
                content_type=content_type,
            )
            if fallback or denied:
                self.fallback(
                    reason=route_reason,
                    content_type=content_type,
                    route=route,
                )
            elif deterministic_success:
                self.quality_decision(
                    decision="accept",
                    reason=route_reason,
                    origin="none",
                    content_type=content_type,
                    route=route,
                    outcome="success",
                )
            return

        adapter_contract_accepted = bool(
            contract_envelope is not None
            and _safe_string(_member(contract_envelope, "status")) == "accepted"
            and _member(contract_envelope, "response") is not None
        )
        mapped_failure = bounded_reason(failure_code)
        final_reason = "supported" if adapter_contract_accepted else failure_code
        final_outcome = "accepted" if adapter_contract_accepted else "fallback"
        self.route_decision(
            route=action,
            adapter=selected,
            decision="route" if adapter_contract_accepted else "fallback",
            reason=final_reason,
            outcome=final_outcome,
            content_type=content_type,
        )
        if invoked:
            status, cost = attributable_cost(
                adapter_result,
                adapter=selected,
                invoked=True,
                actual_cost_microunits=actual_cost_microunits,
            )
            self.cost_usage(
                route=action,
                adapter=selected,
                status=status,
                actual_cost_microunits=cost,
                outcome=final_outcome,
            )
        if not adapter_contract_accepted:
            self.fallback(
                reason=(failure_code if mapped_failure != "unknown" else "unknown"),
                content_type=content_type,
                route=action,
            )
            return

        # An accepted adapter contract is not yet a finalized document
        # outcome: grounding, confidence policy, and atomic merge can still
        # restore the predecessor.  The owning visual pipeline emits quality
        # and origin signals only after those boundaries pass.  This dispatch
        # observer intentionally owns route and attributable-call cost only.


def quality_telemetry_for_settings(
    settings: Any,
    *,
    client: TelemetryClient | None = None,
) -> QualityTelemetry:
    """Resolve the two-level default-off quality telemetry gate."""

    disabled_capabilities = tuple(
        getattr(settings, "parser_shipping_disabled_capabilities", ())
    )
    enabled = bool(
        getattr(settings, "telemetry_enabled", False)
        and getattr(settings, "telemetry_quality_enabled", False)
        and not getattr(settings, "parser_shipping_kill_switch", False)
        and "telemetry" not in disabled_capabilities
    )
    return QualityTelemetry(
        client=client,
        enabled=enabled,
    )


def observe_deterministic_result(result: Any, settings: Any) -> None:
    """Emit bounded aggregate outcomes from one finalized local parse.

    Only closed type/origin classes and counts cross the telemetry boundary.
    The walk is capped independently from document size and never reads item
    values, filenames, labels, prompts, crops, identifiers, or warning text.
    """

    observer = quality_telemetry_for_settings(settings)
    if not observer.enabled:
        return
    try:
        pages = _member(result, "pages")
        if not isinstance(pages, (list, tuple)):
            observer.fallback(
                reason="validation_failed",
                content_type="document",
                route="deterministic",
            )
            return
        counts: dict[tuple[str, str], int] = {}
        warning_count = min(
            len(_member(result, "warnings"))
            if isinstance(_member(result, "warnings"), (list, tuple))
            else 0,
            256,
        )
        remaining_items = 4_096
        incomplete = False
        for page in pages[:256]:
            if _member(page, "success") is False:
                incomplete = True
            page_warnings = _member(page, "warnings")
            if isinstance(page_warnings, (list, tuple)):
                warning_count = min(256, warning_count + len(page_warnings))
            items = _member(page, "items")
            if not isinstance(items, (list, tuple)):
                incomplete = True
                continue
            selected = items[:remaining_items]
            remaining_items -= len(selected)
            for item in selected:
                key = (
                    bounded_content_type(_member(item, "type")),
                    bounded_origin(_member(item, "source")),
                )
                counts[key] = min(4_096, counts.get(key, 0) + 1)
            if remaining_items == 0:
                break
        if len(pages) > 256:
            incomplete = True
        for (content_type, origin), count in sorted(counts.items()):
            remaining = count
            while remaining:
                chunk = min(remaining, 256)
                observer.quality_decision(
                    decision="accept",
                    reason="completed",
                    origin=origin,
                    content_type=content_type,
                    route="deterministic",
                    outcome="success",
                    value=chunk,
                )
                remaining -= chunk
        observer.quality_decision(
            decision="fallback" if incomplete else "accept",
            reason="validation_failed" if incomplete else "completed",
            origin="none",
            content_type="document",
            route="deterministic",
            outcome="fallback" if incomplete else "success",
        )
        if warning_count:
            observer.quality_decision(
                decision="concern",
                reason="unknown",
                origin="none",
                content_type="document",
                route="deterministic",
                outcome="unknown",
                value=warning_count,
            )
    except Exception:
        # Result observation is strictly a side channel.
        return


def observe_deterministic_failure(settings: Any, *, validation: bool) -> None:
    """Record a bounded local failure class without retaining exception data."""

    try:
        quality_telemetry_for_settings(settings).fallback(
            reason="validation_failed" if validation else "raised",
            content_type="document",
            route="deterministic",
        )
    except Exception:
        return


__all__ = [
    "QualityTelemetry",
    "attributable_cost",
    "bounded_adapter",
    "bounded_content_type",
    "bounded_origin",
    "bounded_reason",
    "bounded_route",
    "observe_deterministic_failure",
    "observe_deterministic_result",
    "quality_telemetry_for_settings",
]
