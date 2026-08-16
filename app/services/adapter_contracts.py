"""Versioned, fail-closed contracts for document input adapters.

Phase 07 keeps the existing PDF and raster loaders as the implementation of
those formats.  This module adds the reusable boundary around them: immutable
capability declarations, affine coordinate normalization, conformance checks,
and deterministic single-adapter dispatch.  It deliberately knows nothing
about feature flags or HTTP so callers can retain the predecessor path as the
complete rollback boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Any, Callable, Literal, Mapping, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.input_documents import InputKind, LoadedDocument, load_document


ADAPTER_CONTRACT_VERSION = "1.0"
MAX_REGISTERED_ADAPTERS = 32
MAX_MANIFEST_ITEMS = 64
MAX_SIGNATURE_BYTES = 64
MAX_SIGNATURE_SEARCH_BYTES = 1_024
MAX_ADAPTER_INPUT_BYTES = 2 * 1024 * 1024 * 1024
MAX_ADAPTER_PAGES = 1_000_000
MAX_ADAPTER_REGIONS = 1_000_000
MAX_ADAPTER_RELATIONSHIPS = 1_000_000
MAX_ADAPTER_TIMEOUT_SECONDS = 3_600.0

# Only this module's production registry builder possesses this identity.  It
# distinguishes the shipped/current allowlist from ordinary public
# ``AdapterRegistry.register`` calls without accepting caller-supplied IDs or
# digests at the future-gate boundary.
_APPROVED_CURRENT_REGISTRATION_SEAL = object()

_ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,95}$"
_VERSION_PATTERN = r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][A-Za-z0-9.-]+)?$"
_CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"
_MIME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class AdapterContractModel(BaseModel):
    """Closed and frozen trust-boundary base model."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def require_exact_object(cls, value: Any) -> Any:
        if type(value) is cls:
            return value
        if type(value) is not dict:
            raise ValueError("adapter contract values must be exact objects")
        return value


def _sorted_unique(values: list[str], label: str) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must be sorted and unique")


def _normalized_extension(value: str) -> str:
    normalized = value.strip().casefold()
    if (
        len(normalized) < 2
        or len(normalized) > 24
        or not normalized.startswith(".")
        or not normalized[1:].isalnum()
    ):
        raise ValueError("adapter extension is invalid")
    return normalized


def _normalized_mime(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.split(";", 1)[0].strip().casefold()
    if not normalized:
        return None
    if len(normalized) > 127 or _MIME_PATTERN.fullmatch(normalized) is None:
        raise ValueError("adapter MIME type is invalid")
    return normalized


class AdapterBoundingBox(AdapterContractModel):
    x: FiniteFloat
    y: FiniteFloat
    width: FiniteFloat = Field(ge=0.0)
    height: FiniteFloat = Field(ge=0.0)
    unit: Literal["pt", "px", "logical"]


class AdapterCoordinateTransform(AdapterContractModel):
    """Invertible affine source-to-page/common-space transform."""

    id: str = Field(pattern=_ID_PATTERN)
    source_unit: Literal["pt", "px", "logical"]
    target_unit: Literal["pt", "px", "logical"]
    source_origin: Literal["top_left", "bottom_left"] = "top_left"
    target_origin: Literal["top_left", "bottom_left"] = "top_left"
    matrix: list[FiniteFloat] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_invertible(self) -> "AdapterCoordinateTransform":
        a, b, c, d, _e, _f = self.matrix
        diagonal_product = a * d
        cross_product = b * c
        determinant = diagonal_product - cross_product
        if (
            not math.isfinite(diagonal_product)
            or not math.isfinite(cross_product)
            or not math.isfinite(determinant)
            or abs(determinant) <= 1e-12
        ):
            raise ValueError("adapter coordinate transform must be invertible")
        if (
            self.source_unit == self.target_unit
            and self.source_origin == self.target_origin
            and self.id.endswith("identity")
            and tuple(self.matrix) != (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        ):
            raise ValueError("an identity transform must use the identity matrix")
        return self

    def apply(self, x: float, y: float) -> tuple[float, float]:
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("adapter coordinate input must be finite")
        a, b, c, d, e, f = self.matrix
        projected = (a * x + c * y + e, b * x + d * y + f)
        if not math.isfinite(projected[0]) or not math.isfinite(projected[1]):
            raise ValueError("adapter coordinate result must be finite")
        return projected

    def apply_bbox(self, bbox: AdapterBoundingBox) -> AdapterBoundingBox:
        if bbox.unit != self.source_unit:
            raise ValueError("adapter bbox unit differs from transform source")
        corners = (
            self.apply(bbox.x, bbox.y),
            self.apply(bbox.x + bbox.width, bbox.y),
            self.apply(bbox.x, bbox.y + bbox.height),
            self.apply(bbox.x + bbox.width, bbox.y + bbox.height),
        )
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        projected_width = max(xs) - min(xs)
        projected_height = max(ys) - min(ys)
        if not math.isfinite(projected_width) or not math.isfinite(projected_height):
            raise ValueError("adapter coordinate bounds must be finite")
        return AdapterBoundingBox(
            x=min(xs),
            y=min(ys),
            width=projected_width,
            height=projected_height,
            unit=self.target_unit,
        )

    def inverse(self, *, identity: str | None = None) -> "AdapterCoordinateTransform":
        a, b, c, d, e, f = self.matrix
        determinant = a * d - b * c
        inverse_matrix = [
            d / determinant,
            -b / determinant,
            -c / determinant,
            a / determinant,
            (c * f - d * e) / determinant,
            (b * e - a * f) / determinant,
        ]
        return AdapterCoordinateTransform(
            id=identity or f"{self.id}-inverse",
            source_unit=self.target_unit,
            target_unit=self.source_unit,
            source_origin=self.target_origin,
            target_origin=self.source_origin,
            matrix=inverse_matrix,
        )

    def round_trip_error(self, x: float, y: float) -> float:
        projected = self.apply(x, y)
        restored = self.inverse().apply(*projected)
        return math.hypot(restored[0] - x, restored[1] - y)


class AdapterSignatureFragment(AdapterContractModel):
    offset: int = Field(ge=0, le=MAX_SIGNATURE_SEARCH_BYTES)
    prefix_hex: str = Field(pattern=r"^(?:[0-9a-f]{2}){1,64}$")
    search_window: int = Field(default=0, ge=0, le=MAX_SIGNATURE_SEARCH_BYTES)

    @property
    def prefix(self) -> bytes:
        return bytes.fromhex(self.prefix_hex)

    def matches(self, data: bytes) -> bool:
        prefix = self.prefix
        end = min(
            len(data),
            self.offset + self.search_window + len(prefix),
        )
        return data.find(prefix, self.offset, end) >= 0


class AdapterSignature(AdapterContractModel):
    id: str = Field(pattern=_ID_PATTERN)
    extensions: list[str] = Field(min_length=1, max_length=MAX_MANIFEST_ITEMS)
    fragments: list[AdapterSignatureFragment] = Field(
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_signature(self) -> "AdapterSignature":
        normalized = [_normalized_extension(value) for value in self.extensions]
        if normalized != self.extensions:
            raise ValueError("signature extensions must already be normalized")
        _sorted_unique(self.extensions, "signature extensions")
        return self

    def applies_to(self, extension: str) -> bool:
        return extension in self.extensions

    def matches(self, data: bytes, extension: str) -> bool:
        return self.applies_to(extension) and all(
            fragment.matches(data) for fragment in self.fragments
        )


class AdapterResourceLimits(AdapterContractModel):
    max_input_bytes: int = Field(ge=1, le=MAX_ADAPTER_INPUT_BYTES)
    max_pages: int = Field(ge=1, le=MAX_ADAPTER_PAGES)
    max_regions: int = Field(ge=1, le=MAX_ADAPTER_REGIONS)
    max_relationships: int = Field(ge=1, le=MAX_ADAPTER_RELATIONSHIPS)
    timeout_seconds: FiniteFloat = Field(gt=0.0, le=MAX_ADAPTER_TIMEOUT_SECONDS)


class AdapterFallbackPolicy(AdapterContractModel):
    safe_failure_mode: Literal[
        "typed_error",
        "deterministic_predecessor",
        "unsupported",
    ]
    flag_off_behavior: Literal["legacy_dispatch", "unsupported"]
    network_access: Literal["forbidden", "explicit_policy_only"] = "forbidden"
    undeclared_capability: Literal["reject"] = "reject"


class AdapterSerializationCapabilities(AdapterContractModel):
    canonical_json: bool
    canonical_markdown: bool
    canonical_text: bool
    legacy_projection: bool


class AdapterCapabilities(AdapterContractModel):
    source_identity: bool
    physical_page_index: bool
    printed_page_label: bool
    provenance: bool
    relationships: bool
    visibility: bool
    concerns: bool
    coordinate_units: list[Literal["pt", "px", "logical"]] = Field(
        min_length=1,
        max_length=3,
    )
    content_origins: list[
        Literal[
            "native",
            "native_embedded",
            "uploaded",
            "rendered",
            "ocr",
            "generated",
            "derived",
        ]
    ] = Field(min_length=1, max_length=7)
    evidence_methods: list[
        Literal[
            "native",
            "ocr",
            "vector",
            "embedded",
            "recovered",
            "model",
            "derived",
        ]
    ] = Field(min_length=1, max_length=7)
    relationship_types: list[str] = Field(
        min_length=1,
        max_length=MAX_MANIFEST_ITEMS,
    )
    optional_capabilities: list[str] = Field(
        default_factory=list,
        max_length=MAX_MANIFEST_ITEMS,
    )
    visibility_policy: Literal[
        "source_visible_only",
        "source_declared_visibility",
    ]

    @model_validator(mode="after")
    def validate_capabilities(self) -> "AdapterCapabilities":
        for values, label in (
            (self.coordinate_units, "coordinate units"),
            (self.content_origins, "content origins"),
            (self.evidence_methods, "evidence methods"),
            (self.relationship_types, "relationship types"),
            (self.optional_capabilities, "optional capabilities"),
        ):
            _sorted_unique(values, label)
        for value in (*self.relationship_types, *self.optional_capabilities):
            if re.fullmatch(_CAPABILITY_PATTERN, value) is None:
                raise ValueError("adapter capability name is invalid")
        return self


class AdapterManifest(AdapterContractModel):
    schema_version: Literal["1.0"] = ADAPTER_CONTRACT_VERSION
    adapter_id: str = Field(pattern=_ID_PATTERN)
    adapter_version: str = Field(pattern=_VERSION_PATTERN)
    input_kind: str = Field(pattern=_CAPABILITY_PATTERN)
    extensions: list[str] = Field(min_length=1, max_length=MAX_MANIFEST_ITEMS)
    mime_types: list[str] = Field(min_length=1, max_length=MAX_MANIFEST_ITEMS)
    allow_missing_mime: bool = False
    signatures: list[AdapterSignature] = Field(
        min_length=1,
        max_length=MAX_MANIFEST_ITEMS,
    )
    capabilities: AdapterCapabilities
    coordinate_transforms: list[AdapterCoordinateTransform] = Field(
        min_length=1,
        max_length=8,
    )
    limits: AdapterResourceLimits
    fallback: AdapterFallbackPolicy
    serialization: AdapterSerializationCapabilities

    @model_validator(mode="after")
    def validate_manifest(self) -> "AdapterManifest":
        normalized_extensions = [
            _normalized_extension(value) for value in self.extensions
        ]
        if normalized_extensions != self.extensions:
            raise ValueError("adapter extensions must already be normalized")
        _sorted_unique(self.extensions, "adapter extensions")

        normalized_mimes = [_normalized_mime(value) for value in self.mime_types]
        if normalized_mimes != self.mime_types or any(
            value is None for value in normalized_mimes
        ):
            raise ValueError("adapter MIME types must already be normalized")
        _sorted_unique(self.mime_types, "adapter MIME types")

        signature_ids = [value.id for value in self.signatures]
        _sorted_unique(signature_ids, "adapter signatures")
        transform_ids = [value.id for value in self.coordinate_transforms]
        _sorted_unique(transform_ids, "adapter coordinate transforms")

        signature_extensions = {
            extension
            for signature in self.signatures
            for extension in signature.extensions
        }
        if signature_extensions != set(self.extensions):
            raise ValueError("adapter signatures must cover exactly its extensions")
        if any(
            transform.source_unit not in self.capabilities.coordinate_units
            for transform in self.coordinate_transforms
        ):
            raise ValueError("adapter transform uses an undeclared coordinate unit")
        return self


# Descriptive alias retained for callers that name the story-level concept.
AdapterCapabilityManifest = AdapterManifest


class AdapterConformanceIssue(AdapterContractModel):
    code: str = Field(pattern=_CAPABILITY_PATTERN)
    field: str | None = Field(default=None, max_length=128)
    message: str = Field(min_length=1, max_length=256)


class AdapterConformanceReport(AdapterContractModel):
    schema_version: Literal["1.0"] = ADAPTER_CONTRACT_VERSION
    adapter_id: str = Field(pattern=_ID_PATTERN)
    status: Literal["conforming", "nonconforming"]
    manifest_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    issues: list[AdapterConformanceIssue] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_status(self) -> "AdapterConformanceReport":
        if (self.status == "conforming") == bool(self.issues):
            raise ValueError("adapter conformance status and issues differ")
        if self.status == "conforming" and self.manifest_sha256 is None:
            raise ValueError("conforming adapter requires a manifest digest")
        return self

    @property
    def registration_allowed(self) -> bool:
        return self.status == "conforming"


class AdapterContractError(ValueError):
    """Safe reason-coded adapter-boundary failure."""

    def __init__(
        self,
        code: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


class AdapterRegistrationError(AdapterContractError):
    pass


class AdapterDispatchError(AdapterContractError):
    pass


@runtime_checkable
class DocumentAdapter(Protocol):
    @property
    def manifest(self) -> AdapterManifest | Mapping[str, Any]: ...

    def load(self, data: bytes, filename: str, settings: Any) -> Any: ...


def _canonical_manifest(manifest: AdapterManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def manifest_sha256(manifest: AdapterManifest) -> str:
    return hashlib.sha256(_canonical_manifest(manifest)).hexdigest()


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> AdapterConformanceIssue:
    return AdapterConformanceIssue(code=code, field=field, message=message)


def _manifest_validation_issues(exc: ValidationError) -> list[AdapterConformanceIssue]:
    issues: list[AdapterConformanceIssue] = []
    seen: set[str] = set()
    for error in exc.errors(include_url=False, include_context=False):
        location = ".".join(str(value) for value in error.get("loc", ()))
        top_level = location.split(".", 1)[0] if location else "manifest"
        error_type = str(error.get("type") or "invalid")
        if error_type == "missing":
            code = f"adapter_manifest_missing_{top_level}"
            message = "A mandatory adapter manifest field is missing."
        else:
            code = f"adapter_manifest_invalid_{top_level}"
            message = "An adapter manifest field is invalid."
        code = re.sub(r"[^a-z0-9_]", "_", code.casefold())[:64]
        if code in seen:
            continue
        seen.add(code)
        issues.append(_issue(code, message, field=location or None))
        if len(issues) == 32:
            break
    return issues or [
        _issue(
            "adapter_manifest_invalid",
            "The adapter manifest could not be validated.",
        )
    ]


def _coerce_manifest(value: Any) -> tuple[AdapterManifest | None, list[AdapterConformanceIssue]]:
    if isinstance(value, AdapterManifest):
        return value, []
    if type(value) is not dict:
        return None, [
            _issue(
                "adapter_manifest_invalid",
                "The adapter manifest is not a strict object.",
                field="manifest",
            )
        ]
    try:
        return AdapterManifest.model_validate(value, strict=True), []
    except ValidationError as exc:
        return None, _manifest_validation_issues(exc)


_MANDATORY_CAPABILITIES = (
    "source_identity",
    "physical_page_index",
    "printed_page_label",
    "provenance",
    "relationships",
    "visibility",
    "concerns",
)


def validate_adapter_conformance(adapter: Any) -> AdapterConformanceReport:
    """Validate an adapter without registering or invoking it.

    The manifest is read twice and compared canonically.  This inexpensive
    probe prevents a mutable adapter from changing ownership or capabilities
    between validation and dispatch.
    """

    adapter_id = "unknown-adapter"
    try:
        first_raw = adapter.manifest
        second_raw = adapter.manifest
    except Exception:
        return AdapterConformanceReport(
            adapter_id=adapter_id,
            status="nonconforming",
            issues=[
                _issue(
                    "adapter_manifest_unavailable",
                    "The adapter manifest could not be read.",
                    field="manifest",
                )
            ],
        )

    first, issues = _coerce_manifest(first_raw)
    second, second_issues = _coerce_manifest(second_raw)
    if first is not None:
        adapter_id = first.adapter_id
    elif type(first_raw) is dict:
        candidate = first_raw.get("adapter_id")
        if isinstance(candidate, str) and re.fullmatch(_ID_PATTERN, candidate):
            adapter_id = candidate
    existing_issue_keys = {(issue.code, issue.field) for issue in issues}
    issues.extend(
        issue
        for issue in second_issues
        if (issue.code, issue.field) not in existing_issue_keys
    )
    if first is None or second is None:
        return AdapterConformanceReport(
            adapter_id=adapter_id,
            status="nonconforming",
            issues=issues[:32],
        )

    first_digest = manifest_sha256(first)
    if first_digest != manifest_sha256(second):
        issues.append(
            _issue(
                "adapter_manifest_unstable",
                "The adapter manifest changed during conformance validation.",
                field="manifest",
            )
        )
    if not callable(getattr(adapter, "load", None)):
        issues.append(
            _issue(
                "adapter_load_missing",
                "The adapter does not expose a callable load operation.",
                field="load",
            )
        )
    for capability in _MANDATORY_CAPABILITIES:
        if getattr(first.capabilities, capability) is not True:
            issues.append(
                _issue(
                    f"adapter_capability_{capability}_missing",
                    "A mandatory adapter capability is not declared.",
                    field=f"capabilities.{capability}",
                )
            )
    if not all(
        (
            first.serialization.canonical_json,
            first.serialization.canonical_markdown,
            first.serialization.canonical_text,
            first.serialization.legacy_projection,
        )
    ):
        issues.append(
            _issue(
                "adapter_serialization_incomplete",
                "The adapter does not declare every required serializer.",
                field="serialization",
            )
        )
    if issues:
        return AdapterConformanceReport(
            adapter_id=adapter_id,
            status="nonconforming",
            manifest_sha256=first_digest,
            issues=issues[:32],
        )
    return AdapterConformanceReport(
        adapter_id=adapter_id,
        status="conforming",
        manifest_sha256=first_digest,
        issues=[],
    )


class AdapterRegistration(AdapterContractModel):
    adapter_id: str = Field(pattern=_ID_PATTERN)
    adapter_version: str = Field(pattern=_VERSION_PATTERN)
    input_kind: str = Field(pattern=_CAPABILITY_PATTERN)
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    extensions: list[str] = Field(min_length=1, max_length=MAX_MANIFEST_ITEMS)
    mime_types: list[str] = Field(min_length=1, max_length=MAX_MANIFEST_ITEMS)


@dataclass(frozen=True, slots=True)
class AdapterSelection:
    adapter: DocumentAdapter
    registration: AdapterRegistration
    extension: str
    media_type: str | None

    def load(self, data: bytes, filename: str, settings: Any) -> Any:
        return self.adapter.load(data, filename, settings)


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    adapter: DocumentAdapter
    manifest: AdapterManifest
    registration: AdapterRegistration
    approved_current: bool


class AdapterRegistry:
    """Bounded registry with atomic registration and one-adapter dispatch."""

    def __init__(self, *, max_adapters: int = MAX_REGISTERED_ADAPTERS) -> None:
        if isinstance(max_adapters, bool) or not 1 <= max_adapters <= MAX_REGISTERED_ADAPTERS:
            raise ValueError(
                f"max_adapters must be between 1 and {MAX_REGISTERED_ADAPTERS}"
            )
        self._max_adapters = max_adapters
        self._entries: dict[str, _RegistryEntry] = {}
        self._extensions: dict[str, str] = {}
        self._mime_types: dict[str, str] = {}

    @property
    def registrations(self) -> tuple[AdapterRegistration, ...]:
        return tuple(
            self._entries[adapter_id].registration.model_copy(deep=True)
            for adapter_id in sorted(self._entries)
        )

    def _approved_current_registrations(self) -> tuple[AdapterRegistration, ...]:
        """Internal immutable snapshot consumed by the production gate."""

        return tuple(
            self._entries[adapter_id].registration.model_copy(deep=True)
            for adapter_id in sorted(self._entries)
            if self._entries[adapter_id].approved_current
        )

    @property
    def advertised_mime_types(self) -> tuple[str, ...]:
        """Return only stable, registered MIME ownership in canonical order."""

        advertised: list[str] = []
        for media_type, adapter_id in sorted(self._mime_types.items()):
            try:
                self._stable_entry(adapter_id)
            except AdapterDispatchError:
                # A post-registration manifest mutation invalidates ownership.
                # Keep discovery fail-closed just as dispatch is fail-closed.
                continue
            advertised.append(media_type)
        return tuple(advertised)

    def register(self, adapter: DocumentAdapter) -> AdapterRegistration:
        return self.__register(adapter, approved_current=False)

    def _register_approved_current(
        self,
        adapter: DocumentAdapter,
        *,
        seal: object,
    ) -> AdapterRegistration:
        if seal is not _APPROVED_CURRENT_REGISTRATION_SEAL:
            raise AdapterRegistrationError("adapter_current_approval_forbidden")
        return self.__register(adapter, approved_current=True)

    def __register(
        self,
        adapter: DocumentAdapter,
        *,
        approved_current: bool,
    ) -> AdapterRegistration:
        report = validate_adapter_conformance(adapter)
        if not report.registration_allowed:
            first = report.issues[0]
            raise AdapterRegistrationError(
                first.code,
                details={
                    "adapter_id": report.adapter_id,
                    "field": first.field,
                    "issue_codes": [issue.code for issue in report.issues],
                },
            )
        manifest, _issues = _coerce_manifest(adapter.manifest)
        if manifest is None or report.manifest_sha256 is None:
            raise AdapterRegistrationError("adapter_manifest_invalid")
        commit_manifest_sha256 = manifest_sha256(manifest)
        if commit_manifest_sha256 != report.manifest_sha256:
            raise AdapterRegistrationError(
                "adapter_manifest_unstable",
                details={
                    "adapter_id": report.adapter_id,
                    "validated_manifest_sha256": report.manifest_sha256,
                    "commit_manifest_sha256": commit_manifest_sha256,
                    "issue_codes": ["adapter_manifest_unstable"],
                },
            )
        if len(self._entries) >= self._max_adapters:
            raise AdapterRegistrationError(
                "adapter_registry_limit",
                details={"max_adapters": self._max_adapters},
            )
        if manifest.adapter_id in self._entries:
            raise AdapterRegistrationError(
                "adapter_id_conflict",
                details={"adapter_id": manifest.adapter_id},
            )
        for extension in manifest.extensions:
            owner = self._extensions.get(extension)
            if owner is not None:
                raise AdapterRegistrationError(
                    "adapter_extension_conflict",
                    details={"extension": extension, "registered_owner": owner},
                )
        for media_type in manifest.mime_types:
            owner = self._mime_types.get(media_type)
            if owner is not None:
                raise AdapterRegistrationError(
                    "adapter_mime_conflict",
                    details={"media_type": media_type, "registered_owner": owner},
                )

        registration = AdapterRegistration(
            adapter_id=manifest.adapter_id,
            adapter_version=manifest.adapter_version,
            input_kind=manifest.input_kind,
            manifest_sha256=report.manifest_sha256,
            extensions=list(manifest.extensions),
            mime_types=list(manifest.mime_types),
        )
        # Commit all indexes only after every check has succeeded.
        self._entries[manifest.adapter_id] = _RegistryEntry(
            adapter=adapter,
            manifest=manifest.model_copy(deep=True),
            registration=registration.model_copy(deep=True),
            approved_current=approved_current,
        )
        self._extensions.update(
            {extension: manifest.adapter_id for extension in manifest.extensions}
        )
        self._mime_types.update(
            {media_type: manifest.adapter_id for media_type in manifest.mime_types}
        )
        return registration.model_copy(deep=True)

    def _stable_entry(self, adapter_id: str) -> _RegistryEntry:
        entry = self._entries[adapter_id]
        try:
            report = validate_adapter_conformance(entry.adapter)
        except Exception:
            report = None
        if report is None or (
            not report.registration_allowed
            or report.manifest_sha256 != entry.registration.manifest_sha256
        ):
            raise AdapterDispatchError(
                "adapter_registration_stale",
                details={
                    "adapter_id": adapter_id,
                    "issue_codes": (
                        [issue.code for issue in report.issues]
                        if report is not None
                        else ["adapter_conformance_unavailable"]
                    ),
                },
            )
        return entry

    def select(
        self,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> AdapterSelection:
        if type(data) is not bytes:
            raise AdapterDispatchError("adapter_input_invalid")
        normalized_name = (filename or "").replace("\\", "/")
        extension = PurePosixPath(normalized_name).suffix.casefold()
        adapter_id = self._extensions.get(extension)
        if adapter_id is None:
            raise AdapterDispatchError(
                "adapter_extension_unregistered",
                details={"extension": extension or None},
            )
        entry = self._stable_entry(adapter_id)
        try:
            media_type = _normalized_mime(content_type)
        except ValueError as exc:
            raise AdapterDispatchError("adapter_mime_invalid") from exc
        if media_type is None:
            if not entry.manifest.allow_missing_mime:
                raise AdapterDispatchError(
                    "adapter_mime_required",
                    details={"adapter_id": adapter_id},
                )
        elif media_type not in entry.manifest.mime_types:
            raise AdapterDispatchError(
                "adapter_mime_mismatch",
                details={"adapter_id": adapter_id, "media_type": media_type},
            )
        if len(data) > entry.manifest.limits.max_input_bytes:
            raise AdapterDispatchError(
                "adapter_input_limit_exceeded",
                details={
                    "adapter_id": adapter_id,
                    "max_input_bytes": entry.manifest.limits.max_input_bytes,
                },
            )
        if not data or not any(
            signature.matches(data, extension)
            for signature in entry.manifest.signatures
        ):
            raise AdapterDispatchError(
                "adapter_signature_mismatch",
                details={"adapter_id": adapter_id, "extension": extension},
            )
        return AdapterSelection(
            adapter=entry.adapter,
            registration=entry.registration.model_copy(deep=True),
            extension=extension,
            media_type=media_type,
        )

    def dispatch(
        self,
        data: bytes,
        filename: str,
        content_type: str | None,
        settings: Any,
    ) -> Any:
        selection = self.select(filename, content_type, data)
        return selection.load(data, filename, settings)


_RELATIONSHIP_TYPES = sorted(
    {
        "alternative_of",
        "annotation_of",
        "axis_of",
        "caption_of",
        "contains",
        "footnote_of",
        "legend_of",
        "reading_before",
        "references",
        "source_note_of",
    }
)


def _common_capabilities(
    *,
    coordinate_unit: Literal["pt", "px", "logical"],
    origins: list[
        Literal[
            "native",
            "native_embedded",
            "uploaded",
            "rendered",
            "ocr",
            "generated",
            "derived",
        ]
    ],
    evidence_methods: list[
        Literal[
            "native",
            "ocr",
            "vector",
            "embedded",
            "recovered",
            "model",
            "derived",
        ]
    ],
) -> AdapterCapabilities:
    return AdapterCapabilities(
        source_identity=True,
        physical_page_index=True,
        printed_page_label=True,
        provenance=True,
        relationships=True,
        visibility=True,
        concerns=True,
        coordinate_units=[coordinate_unit],
        content_origins=sorted(origins),
        evidence_methods=sorted(evidence_methods),
        relationship_types=list(_RELATIONSHIP_TYPES),
        optional_capabilities=[],
        visibility_policy="source_declared_visibility",
    )


def _limits(settings: Any | None) -> AdapterResourceLimits:
    return AdapterResourceLimits(
        max_input_bytes=int(getattr(settings, "max_upload_bytes", 20 * 1024 * 1024)),
        max_pages=int(getattr(settings, "max_pages", 100)),
        max_regions=65_536,
        max_relationships=65_536,
        timeout_seconds=float(
            getattr(settings, "document_timeout_seconds", 300.0)
        ),
    )


class BuiltinInputDocumentAdapter:
    """Adapter wrapper that delegates to the unchanged PDF/image loader."""

    def __init__(self, manifest: AdapterManifest, expected_kind: InputKind) -> None:
        self._manifest = manifest
        self._expected_kind = expected_kind

    @property
    def manifest(self) -> AdapterManifest:
        return self._manifest

    def load(
        self,
        data: bytes,
        filename: str,
        settings: Any,
    ) -> LoadedDocument:
        loaded = load_document(data, filename, settings)
        if loaded.kind is not self._expected_kind:
            raise AdapterDispatchError(
                "adapter_loaded_kind_mismatch",
                details={"adapter_id": self._manifest.adapter_id},
            )
        return loaded


def builtin_pdf_adapter(settings: Any | None = None) -> BuiltinInputDocumentAdapter:
    extension = ".pdf"
    manifest = AdapterManifest(
        adapter_id="builtin-pdf",
        adapter_version="1.0.0",
        input_kind="pdf",
        extensions=[extension],
        mime_types=sorted(
            [
                "application/octet-stream",
                "application/pdf",
                "application/x-pdf",
                "binary/octet-stream",
            ]
        ),
        allow_missing_mime=True,
        signatures=[
            AdapterSignature(
                id="pdf-header",
                extensions=[extension],
                fragments=[
                    AdapterSignatureFragment(
                        offset=0,
                        prefix_hex=b"%PDF-".hex(),
                        search_window=1_019,
                    )
                ],
            )
        ],
        capabilities=_common_capabilities(
            coordinate_unit="pt",
            origins=[
                "generated",
                "native",
                "native_embedded",
                "ocr",
                "rendered",
            ],
            evidence_methods=[
                "derived",
                "embedded",
                "model",
                "native",
                "ocr",
                "recovered",
                "vector",
            ],
        ),
        coordinate_transforms=[
            AdapterCoordinateTransform(
                id="pdf-page-identity",
                source_unit="pt",
                target_unit="pt",
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            )
        ],
        limits=_limits(settings),
        fallback=AdapterFallbackPolicy(
            safe_failure_mode="typed_error",
            flag_off_behavior="legacy_dispatch",
        ),
        serialization=AdapterSerializationCapabilities(
            canonical_json=True,
            canonical_markdown=True,
            canonical_text=True,
            legacy_projection=True,
        ),
    )
    return BuiltinInputDocumentAdapter(manifest, InputKind.PDF)


def builtin_image_adapter(settings: Any | None = None) -> BuiltinInputDocumentAdapter:
    signatures = [
        AdapterSignature(
            id="image-jpeg",
            extensions=[".jpeg", ".jpg"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="ffd8ff")
            ],
        ),
        AdapterSignature(
            id="image-png",
            extensions=[".png"],
            fragments=[
                AdapterSignatureFragment(
                    offset=0,
                    prefix_hex="89504e470d0a1a0a",
                )
            ],
        ),
        AdapterSignature(
            id="image-tiff-be",
            extensions=[".tif", ".tiff"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="4d4d002a")
            ],
        ),
        AdapterSignature(
            id="image-tiff-bigtiff-be",
            extensions=[".tif", ".tiff"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="4d4d002b")
            ],
        ),
        AdapterSignature(
            id="image-tiff-bigtiff-le",
            extensions=[".tif", ".tiff"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="49492b00")
            ],
        ),
        AdapterSignature(
            id="image-tiff-le",
            extensions=[".tif", ".tiff"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="49492a00")
            ],
        ),
        AdapterSignature(
            id="image-webp",
            extensions=[".webp"],
            fragments=[
                AdapterSignatureFragment(offset=0, prefix_hex="52494646"),
                AdapterSignatureFragment(offset=8, prefix_hex="57454250"),
            ],
        ),
    ]
    manifest = AdapterManifest(
        adapter_id="builtin-image",
        adapter_version="1.0.0",
        input_kind="image",
        extensions=[".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"],
        mime_types=sorted(
            [
                "image/jpeg",
                "image/jpg",
                "image/pjpeg",
                "image/png",
                "image/tiff",
                "image/webp",
                "image/x-tiff",
            ]
        ),
        allow_missing_mime=False,
        signatures=sorted(signatures, key=lambda value: value.id),
        capabilities=_common_capabilities(
            coordinate_unit="px",
            origins=["generated", "ocr", "uploaded"],
            evidence_methods=["derived", "model", "ocr"],
        ),
        coordinate_transforms=[
            AdapterCoordinateTransform(
                id="image-page-identity",
                source_unit="px",
                target_unit="px",
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            )
        ],
        limits=_limits(settings),
        fallback=AdapterFallbackPolicy(
            safe_failure_mode="typed_error",
            flag_off_behavior="legacy_dispatch",
        ),
        serialization=AdapterSerializationCapabilities(
            canonical_json=True,
            canonical_markdown=True,
            canonical_text=True,
            legacy_projection=True,
        ),
    )
    return BuiltinInputDocumentAdapter(manifest, InputKind.IMAGE)


def builtin_adapter_registry(settings: Any | None = None) -> Any:
    """Build the production registry behind its future-extension gate.

    PDF, raster, and enabled native Office adapters are registered as the
    explicit current allowlist before the gate is constructed.  The settings
    flag controls only whether new candidates may use the extension boundary;
    current dispatch remains available in either state.
    """

    registry = AdapterRegistry()
    registry._register_approved_current(
        builtin_pdf_adapter(settings),
        seal=_APPROVED_CURRENT_REGISTRATION_SEAL,
    )
    registry._register_approved_current(
        builtin_image_adapter(settings),
        seal=_APPROVED_CURRENT_REGISTRATION_SEAL,
    )
    # Office adapters are advertised only behind their format-local rollback
    # flags.  Imports stay lazy so flag-off startup remains the exact Phase 06
    # PDF/image path and does not import the OOXML stack.
    if bool(getattr(settings, "adapters_docx_native_enabled", False)):
        from app.services.docx_adapter import DocxNativeAdapter

        registry._register_approved_current(
            DocxNativeAdapter(settings),
            seal=_APPROVED_CURRENT_REGISTRATION_SEAL,
        )
    if bool(getattr(settings, "adapters_pptx_native_enabled", False)):
        from app.services.pptx_adapter import PptxNativeAdapter

        registry._register_approved_current(
            PptxNativeAdapter(settings),
            seal=_APPROVED_CURRENT_REGISTRATION_SEAL,
        )
    if bool(getattr(settings, "adapters_xlsx_native_enabled", False)):
        from app.services.xlsx_adapter import XlsxNativeAdapter

        registry._register_approved_current(
            XlsxNativeAdapter(settings),
            seal=_APPROVED_CURRENT_REGISTRATION_SEAL,
        )
    from app.services.future_adapter_gate import FutureAdapterGate

    return FutureAdapterGate(
        registry,
        enabled=bool(
            getattr(settings, "adapters_future_conformance_gate_enabled", False)
        ),
    )


def conforming_test_manifest(
    *,
    adapter_id: str = "fixture-adapter",
    extension: str = ".fixture",
    mime_type: str = "application/x-fixture",
) -> AdapterManifest:
    normalized_extension = _normalized_extension(extension)
    normalized_mime = _normalized_mime(mime_type)
    if normalized_mime is None:
        raise ValueError("fixture MIME type is required")
    return AdapterManifest(
        adapter_id=adapter_id,
        adapter_version="1.0.0",
        input_kind="fixture",
        extensions=[normalized_extension],
        mime_types=[normalized_mime],
        signatures=[
            AdapterSignature(
                id="fixture-header",
                extensions=[normalized_extension],
                fragments=[
                    AdapterSignatureFragment(offset=0, prefix_hex=b"FTR1".hex())
                ],
            )
        ],
        capabilities=_common_capabilities(
            coordinate_unit="px",
            origins=["native"],
            evidence_methods=["native"],
        ),
        coordinate_transforms=[
            AdapterCoordinateTransform(
                id="fixture-page-identity",
                source_unit="px",
                target_unit="px",
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            )
        ],
        limits=AdapterResourceLimits(
            max_input_bytes=1_024,
            max_pages=4,
            max_regions=32,
            max_relationships=64,
            timeout_seconds=1.0,
        ),
        fallback=AdapterFallbackPolicy(
            safe_failure_mode="typed_error",
            flag_off_behavior="unsupported",
        ),
        serialization=AdapterSerializationCapabilities(
            canonical_json=True,
            canonical_markdown=True,
            canonical_text=True,
            legacy_projection=True,
        ),
    )


class DeterministicAdapterTestDouble:
    """Small conforming adapter used by the reusable harness and consumers."""

    def __init__(
        self,
        manifest: AdapterManifest | None = None,
        *,
        result_factory: Callable[[bytes, str, Any], Any] | None = None,
    ) -> None:
        self._manifest = manifest or conforming_test_manifest()
        self._result_factory = result_factory
        self.calls = 0

    @property
    def manifest(self) -> AdapterManifest:
        return self._manifest

    def load(self, data: bytes, filename: str, settings: Any) -> Any:
        self.calls += 1
        if self._result_factory is not None:
            return self._result_factory(data, filename, settings)
        return {
            "adapter_id": self._manifest.adapter_id,
            "filename": PurePosixPath(filename.replace("\\", "/")).name,
            "source_sha256": hashlib.sha256(data).hexdigest(),
        }


class MissingCapabilityAdapterTestDouble:
    """Deliberately invalid adapter whose manifest omits one mandatory field."""

    def __init__(self, missing_field: str = "capabilities") -> None:
        manifest = conforming_test_manifest().model_dump(mode="json")
        manifest.pop(missing_field, None)
        self._manifest = manifest

    @property
    def manifest(self) -> Mapping[str, Any]:
        return self._manifest

    def load(self, data: bytes, filename: str, settings: Any) -> Any:
        raise AssertionError("a nonconforming adapter must never be invoked")


__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "AdapterBoundingBox",
    "AdapterCapabilities",
    "AdapterCapabilityManifest",
    "AdapterConformanceIssue",
    "AdapterConformanceReport",
    "AdapterContractError",
    "AdapterCoordinateTransform",
    "AdapterDispatchError",
    "AdapterFallbackPolicy",
    "AdapterManifest",
    "AdapterRegistration",
    "AdapterRegistrationError",
    "AdapterRegistry",
    "AdapterResourceLimits",
    "AdapterSelection",
    "AdapterSerializationCapabilities",
    "AdapterSignature",
    "AdapterSignatureFragment",
    "BuiltinInputDocumentAdapter",
    "DeterministicAdapterTestDouble",
    "DocumentAdapter",
    "MissingCapabilityAdapterTestDouble",
    "builtin_adapter_registry",
    "builtin_image_adapter",
    "builtin_pdf_adapter",
    "conforming_test_manifest",
    "manifest_sha256",
    "validate_adapter_conformance",
]
