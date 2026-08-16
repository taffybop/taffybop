"""Fail-closed registration gate for adapters added after Phase 07."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


_ESSENTIAL_DECLARATIONS = (
    "grounding",
    "limits",
    "fallback",
    "serialization",
    "rollback",
)


class FutureAdapterGateError(ValueError):
    code = "future_adapter_rejected"

    def __init__(self, code: str | None = None, *, adapter_id: str | None = None) -> None:
        self.code = code or self.code
        self.adapter_id = adapter_id
        super().__init__(self.code)


class FutureAdapterGateDisabledError(FutureAdapterGateError):
    code = "future_adapter_gate_disabled"


class AdapterCompatibilityManifest(BaseModel):
    """Compact release compatibility declaration for one candidate adapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"]
    adapter_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,63}$")
    adapter_version: str = Field(min_length=1, max_length=64)
    grounding: Literal["source_locator_and_transform", "logical_source_locator"]
    limits: Literal["declared_and_enforced"]
    fallback: Literal["declared_deterministic", "unsupported_without_fabrication"]
    serialization: list[Literal["json", "markdown", "text"]] = Field(
        min_length=3,
        max_length=3,
    )
    rollback: Literal["feature_flag"]
    native_first: bool
    safe_intake: bool
    no_external_fetch: bool
    no_active_content_execution: bool
    capability_tests: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def validate_compatibility(self) -> AdapterCompatibilityManifest:
        if self.serialization != ["json", "markdown", "text"]:
            raise ValueError("future adapter serialization declaration differs")
        if not (
            self.native_first
            and self.safe_intake
            and self.no_external_fetch
            and self.no_active_content_execution
        ):
            raise ValueError("future adapter safety declaration differs")
        if self.capability_tests != sorted(set(self.capability_tests)):
            raise ValueError("future adapter capability tests differ")
        return self


class FutureAdapterCandidate(Protocol):
    manifest: Any
    compatibility_manifest: AdapterCompatibilityManifest | dict[str, Any]

    def load(self, data: bytes, filename: str, settings: Any) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class FutureAdapterGateResult:
    accepted: bool
    adapter_id: str | None
    reason_codes: tuple[str, ...]
    manifest_sha256: str | None


@dataclass(frozen=True, slots=True)
class FutureAdapterSelection:
    """Adapter metadata plus a bound, revalidating load operation.

    Unlike the core registry selection, this public gate selection never
    exposes the candidate adapter. Its load method accepts only the exact
    request that was selected and re-enters gate dispatch so current core and
    compatibility conformance are checked again.
    """

    registration: Any
    extension: str
    media_type: str | None
    _gate: Any = field(repr=False, compare=False)
    _data: bytes = field(repr=False, compare=False)
    _filename: str = field(repr=False, compare=False)
    _content_type: str | None = field(repr=False, compare=False)

    def load(self, data: bytes, filename: str, settings: Any) -> Any:
        if type(data) is not bytes or data != self._data or filename != self._filename:
            raise FutureAdapterGateError("future_adapter_selection_input_mismatch")
        return self._gate.dispatch(
            data,
            filename,
            self._content_type,
            settings,
        )


def _manifest_value(adapter: Any, field: str) -> Any:
    value = getattr(adapter, field, None)
    return value() if callable(value) else value


def _core_adapter_identity(adapter: Any) -> tuple[str | None, str | None]:
    manifest = _manifest_value(adapter, "manifest")
    if manifest is None:
        return None, None
    adapter_id = getattr(manifest, "adapter_id", None)
    adapter_version = getattr(manifest, "adapter_version", None)
    if isinstance(manifest, dict):
        adapter_id = manifest.get("adapter_id")
        adapter_version = manifest.get("adapter_version")
    return (
        adapter_id if isinstance(adapter_id, str) else None,
        adapter_version if isinstance(adapter_version, str) else None,
    )


def evaluate_future_adapter(adapter: Any) -> FutureAdapterGateResult:
    adapter_id, adapter_version = _core_adapter_identity(adapter)
    raw = _manifest_value(adapter, "compatibility_manifest")
    reasons: list[str] = []
    if raw is None:
        reasons.extend(
            f"future_adapter_missing_{name}_declaration"
            for name in _ESSENTIAL_DECLARATIONS
        )
        return FutureAdapterGateResult(False, adapter_id, tuple(reasons), None)
    if isinstance(raw, BaseModel):
        raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        return FutureAdapterGateResult(
            False,
            adapter_id,
            ("future_adapter_manifest_malformed",),
            None,
        )
    for field in _ESSENTIAL_DECLARATIONS:
        value = raw.get(field)
        if field not in raw or value is None or value == "":
            reasons.append(f"future_adapter_missing_{field}_declaration")
    if reasons:
        return FutureAdapterGateResult(False, adapter_id, tuple(reasons), None)
    try:
        manifest = AdapterCompatibilityManifest.model_validate(raw, strict=True)
    except ValidationError:
        return FutureAdapterGateResult(
            False,
            adapter_id,
            ("future_adapter_manifest_malformed",),
            None,
        )
    if manifest.adapter_id != adapter_id or manifest.adapter_version != adapter_version:
        return FutureAdapterGateResult(
            False,
            adapter_id,
            ("future_adapter_identity_mismatch",),
            None,
        )
    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FutureAdapterGateResult(
        True,
        adapter_id,
        (),
        hashlib.sha256(encoded).hexdigest(),
    )


class FutureAdapterGate:
    """Validate candidates before delegating to the shared adapter registry."""

    __slots__ = (
        "__approved_current",
        "__candidate_adapters",
        "__candidate_core_digests",
        "__enabled",
        "__registry",
        "__results",
        "__sealed",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_FutureAdapterGate__sealed", False):
            raise AttributeError("future adapter gate configuration is immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        registry: Any,
        *,
        enabled: bool,
    ) -> None:
        from app.services.adapter_contracts import AdapterRegistry

        if type(registry) is not AdapterRegistry:
            raise FutureAdapterGateError("future_adapter_registry_unavailable")
        # The registry is deliberately name-mangled and has no public
        # accessor. Candidate registration and dispatch must stay mediated by
        # this gate; exposing the mutable registry would recreate a bypass.
        self.__registry = registry
        self.__enabled = bool(enabled)
        self.__results: dict[str, FutureAdapterGateResult] = {}
        self.__candidate_adapters: dict[str, Any] = {}
        self.__candidate_core_digests: dict[str, str] = {}
        current = {
            str(value.adapter_id): str(value.manifest_sha256)
            for value in (getattr(registry, "registrations", ()) or ())
        }
        self.__approved_current: dict[str, str] = {}
        # Invoke the exact registry implementation, not an instance attribute
        # supplied by the caller, so construction cannot replace the internal
        # approved-current snapshot reader.
        approved_registrations = (
            AdapterRegistry._approved_current_registrations(registry)
        )
        for registration in approved_registrations:
            adapter_id = str(getattr(registration, "adapter_id", ""))
            digest = str(getattr(registration, "manifest_sha256", ""))
            if not adapter_id or current.get(adapter_id) != digest:
                raise FutureAdapterGateError(
                    "future_adapter_approved_registry_invalid",
                    adapter_id=adapter_id or None,
                )
            self.__approved_current[adapter_id] = digest
        self.__sealed = True

    @property
    def enabled(self) -> bool:
        return self.__enabled

    @property
    def results(self) -> tuple[FutureAdapterGateResult, ...]:
        return tuple(self.__results[key] for key in sorted(self.__results))

    def _authorization_reason(self, registration: Any) -> str | None:
        adapter_id = str(getattr(registration, "adapter_id", ""))
        core_digest = str(getattr(registration, "manifest_sha256", ""))
        approved_digest = self.__approved_current.get(adapter_id)
        if approved_digest is not None:
            if core_digest == approved_digest:
                return None
            return "future_adapter_current_registration_stale"

        accepted = self.__results.get(adapter_id)
        adapter = self.__candidate_adapters.get(adapter_id)
        if (
            accepted is None
            or not accepted.accepted
            or accepted.manifest_sha256 is None
            or adapter is None
            or self.__candidate_core_digests.get(adapter_id) != core_digest
        ):
            return "future_adapter_compatibility_unaccepted"
        try:
            current = evaluate_future_adapter(adapter)
        except Exception:
            return "future_adapter_compatibility_stale"
        if current != accepted:
            return "future_adapter_compatibility_stale"
        return None

    def _authorized_registrations(self) -> tuple[Any, ...]:
        registrations = tuple(
            getattr(self.__registry, "registrations", ()) or ()
        )
        raw_advertised = getattr(self.__registry, "advertised_mime_types", ())
        raw_advertised = (
            raw_advertised() if callable(raw_advertised) else raw_advertised
        )
        stable_mime_types = {str(value) for value in (raw_advertised or ())}
        return tuple(
            registration
            for registration in registrations
            if self._authorization_reason(registration) is None
            and all(
                str(media_type) in stable_mime_types
                for media_type in getattr(registration, "mime_types", ())
            )
        )

    @property
    def registrations(self) -> tuple[Any, ...]:
        """Expose only approved-current or compatibility-gated registrations."""

        return self._authorized_registrations()

    def register(self, adapter: Any) -> FutureAdapterGateResult:
        adapter_id, _version = _core_adapter_identity(adapter)
        if not self.__enabled:
            raise FutureAdapterGateDisabledError(adapter_id=adapter_id)
        result = evaluate_future_adapter(adapter)
        if not result.accepted:
            raise FutureAdapterGateError(
                result.reason_codes[0], adapter_id=result.adapter_id
            )
        register = getattr(self.__registry, "register", None)
        if not callable(register):
            raise FutureAdapterGateError(
                "future_adapter_registry_unavailable", adapter_id=result.adapter_id
            )
        try:
            registration = register(adapter)
        except Exception as exc:
            code = str(getattr(exc, "code", "adapter_conformance_failed"))
            raise FutureAdapterGateError(code, adapter_id=result.adapter_id) from exc
        assert result.adapter_id is not None
        self.__results[result.adapter_id] = result
        self.__candidate_adapters[result.adapter_id] = adapter
        self.__candidate_core_digests[result.adapter_id] = str(
            getattr(registration, "manifest_sha256", "")
        )
        return result

    def advertised_mime_types(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(media_type)
                    for registration in self._authorized_registrations()
                    for media_type in getattr(registration, "mime_types", ())
                }
            )
        )

    def _select_raw(
        self,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> Any:
        select = getattr(self.__registry, "select", None)
        if not callable(select):
            raise FutureAdapterGateError("future_adapter_registry_unavailable")
        selection = select(filename, content_type, data)
        reason = self._authorization_reason(selection.registration)
        if reason is not None:
            raise FutureAdapterGateError(
                reason,
                adapter_id=str(selection.registration.adapter_id),
            )
        return selection

    def select(
        self,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> FutureAdapterSelection:
        selection = self._select_raw(filename, content_type, data)
        return FutureAdapterSelection(
            registration=selection.registration.model_copy(deep=True),
            extension=str(selection.extension),
            media_type=(
                str(selection.media_type)
                if selection.media_type is not None
                else None
            ),
            _gate=self,
            _data=data,
            _filename=filename,
            _content_type=content_type,
        )

    def dispatch(
        self,
        data: bytes,
        filename: str,
        content_type: str | None,
        settings: Any,
    ) -> Any:
        selection = self._select_raw(filename, content_type, data)
        return selection.load(data, filename, settings)


def compatibility_manifest_for(
    adapter_id: str,
    adapter_version: str,
    *,
    grounding: Literal[
        "source_locator_and_transform", "logical_source_locator"
    ] = "source_locator_and_transform",
) -> AdapterCompatibilityManifest:
    return AdapterCompatibilityManifest(
        schema_version="1.0",
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        grounding=grounding,
        limits="declared_and_enforced",
        fallback="declared_deterministic",
        serialization=["json", "markdown", "text"],
        rollback="feature_flag",
        native_first=True,
        safe_intake=True,
        no_external_fetch=True,
        no_active_content_execution=True,
        capability_tests=[],
    )
