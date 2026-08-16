"""Deterministic, offline release-artifact manifests and verification.

This module intentionally does not discover document inputs, user cache paths,
or credentials.  Release owners supply a bounded inventory of shipped
artifacts.  Every enabled record must bind concrete local bytes to a version,
source, SHA-256 digest, and usable license record.  An optional component whose
evidence is unavailable can be represented only as disabled with an explicit
fallback; required components fail closed.

The helpers operate entirely on local files and installed distribution
metadata.  They perform no network access and do not infer missing provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


MANIFEST_SCHEMA = "parser-release-artifact-manifest-v1"
RELEASE_PROFILE_SCHEMA = "parser-release-artifact-profile-v1"
STARTUP_MANIFEST_PATH_ENV = "PARSER_RELEASE_ARTIFACT_MANIFEST_PATH"
STARTUP_MANIFEST_SHA256_ENV = "PARSER_RELEASE_ARTIFACT_MANIFEST_SHA256"
STARTUP_CANDIDATE_ROOT_ENV = "PARSER_RELEASE_ARTIFACT_ROOT"
STARTUP_PROFILE_ENV = "PARSER_RELEASE_ARTIFACT_PROFILE"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_UNUSABLE_LICENSES = frozenset(
    {"", "unknown", "none", "n/a", "na", "unlicensed", "pending", "tbd"}
)
_SAFE_SOURCE_SCHEMES = frozenset({"https", "pkg", "registry", "repository", "urn"})
_LOCAL_PATH_MARKERS = (
    "/users/",
    "/home/",
    "/private/",
    "/tmp/",
    "\\users\\",
    "\\home\\",
    "~",
)
_RELEASE_VERIFICATION_AUTHORITY = object()


class ArtifactManifestError(ValueError):
    """Raised when manifest evidence is incomplete, ambiguous, or unsafe."""


class ArtifactVerificationError(RuntimeError):
    """Raised when a build/startup or rollback verification fails closed."""

    def __init__(self, report: "ManifestVerification") -> None:
        self.report = report
        reasons = ", ".join(report.blocking_reasons) or "manifest verification failed"
        super().__init__(reasons)


class ArtifactKind(StrEnum):
    """Bounded classes of output-producing release artifacts."""

    RUNTIME = "runtime"
    PYTHON_DEPENDENCY = "python_dependency"
    NATIVE_TOOL = "native_tool"
    OCR_DATA = "ocr_data"
    CONVERTER = "converter"
    MODEL = "model"
    RENDERER = "renderer"
    SCHEMA = "schema"
    PROMPT = "prompt"


class ArtifactLocatorKind(StrEnum):
    """Local-only verification mechanisms supported by the release gate."""

    FILE = "file"
    DIRECTORY = "directory"
    PYTHON_DISTRIBUTION = "python_distribution"
    DEBIAN_PACKAGE = "debian_package"
    HUGGINGFACE_MODEL = "huggingface_model"


@dataclass(frozen=True, slots=True)
class VerificationLimits:
    """Independent bounds for manifest parsing and local integrity checks."""

    max_manifest_bytes: int = 1_048_576
    max_artifacts: int = 512
    max_files_per_artifact: int = 100_000
    max_bytes_per_artifact: int = 16 * 1024 * 1024 * 1024
    timeout_seconds: float = 120.0
    read_chunk_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        integer_bounds = (
            self.max_manifest_bytes,
            self.max_artifacts,
            self.max_files_per_artifact,
            self.max_bytes_per_artifact,
            self.read_chunk_bytes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in integer_bounds):
            raise ArtifactManifestError("verification integer bounds must be positive")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0.001 <= float(self.timeout_seconds) <= 3_600.0
        ):
            raise ArtifactManifestError(
                "verification timeout must be between 0.001 and 3600 seconds"
            )


DEFAULT_VERIFICATION_LIMITS = VerificationLimits()


def _printable(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ArtifactManifestError(f"{field} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ArtifactManifestError(
            f"{field} must be non-empty printable text no longer than {maximum} characters"
        )
    return normalized


def _identifier(value: str, *, field: str) -> str:
    normalized = _printable(value, field=field, maximum=128).casefold()
    if _IDENTIFIER_RE.fullmatch(normalized) is None:
        raise ArtifactManifestError(f"{field} must be a bounded identifier")
    return normalized


def _reason(value: str, *, field: str) -> str:
    normalized = _printable(value, field=field, maximum=128).casefold()
    if _REASON_RE.fullmatch(normalized) is None:
        raise ArtifactManifestError(f"{field} must be a bounded reason code")
    return normalized


def _source_record(value: str) -> str:
    normalized = _printable(value, field="source", maximum=512)
    folded = normalized.casefold()
    if any(marker in folded for marker in _LOCAL_PATH_MARKERS) or folded.startswith("file:"):
        raise ArtifactManifestError("source must not contain a local or user cache path")
    parsed = urlsplit(normalized)
    if parsed.scheme.casefold() not in _SAFE_SOURCE_SCHEMES:
        raise ArtifactManifestError("source must use an approved provenance scheme")
    if parsed.scheme.casefold() == "https":
        if not parsed.netloc or parsed.username or parsed.password:
            raise ArtifactManifestError("HTTPS source must identify a host without credentials")
        if parsed.query or parsed.fragment:
            raise ArtifactManifestError("source must not contain query data or fragments")
    elif not parsed.path:
        raise ArtifactManifestError("source must contain a concrete provenance identity")
    return normalized


def _license_record(value: str) -> str:
    normalized = _printable(value, field="license_record", maximum=256)
    if normalized.casefold() in _UNUSABLE_LICENSES:
        raise ArtifactManifestError("license record is not usable")
    if any(marker in normalized.casefold() for marker in _LOCAL_PATH_MARKERS):
        raise ArtifactManifestError("license record must not contain a local path")
    return normalized


def _sha256(value: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ArtifactManifestError("artifact SHA-256 must be 64 lowercase hex characters")
    return value


def _relative_locator(value: str) -> str:
    normalized = _printable(value, field="locator", maximum=512).replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or normalized.startswith("~")
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(part.casefold() in {".cache", "cache", ".huggingface"} for part in path.parts)
    ):
        raise ArtifactManifestError(
            "file and directory locators must be safe build-root-relative paths"
        )
    return path.as_posix()


def _distribution_locator(value: str) -> str:
    normalized = _printable(value, field="locator", maximum=128).casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", normalized) is None:
        raise ArtifactManifestError("distribution locator must be a package name")
    return normalized


@dataclass(frozen=True, slots=True)
class ReleaseArtifactRequirement:
    """One approved identity in the repository-owned release profile."""

    artifact_id: str
    kind: ArtifactKind
    capability: str
    required: bool
    version: str | None = None
    source: str | None = None
    license_record: str | None = None
    locator_kind: ArtifactLocatorKind | None = None
    locator: str | None = None
    fallback: str | None = None
    build_generated_evidence: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, field="artifact_id")
        )
        object.__setattr__(
            self, "capability", _identifier(self.capability, field="capability")
        )
        try:
            kind = self.kind if isinstance(self.kind, ArtifactKind) else ArtifactKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ArtifactManifestError("release profile artifact kind is unsupported") from exc
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.required, bool):
            raise ArtifactManifestError("release profile required marker must be boolean")
        if not isinstance(self.build_generated_evidence, bool):
            raise ArtifactManifestError("build-generated evidence marker must be boolean")
        if self.required:
            if self.locator_kind is None or self.locator is None:
                raise ArtifactManifestError(
                    "required release profile artifacts need a concrete locator"
                )
            if not self.build_generated_evidence:
                if any(
                    value is None
                    for value in (self.version, self.source, self.license_record)
                ):
                    raise ArtifactManifestError(
                        "pinned required artifacts need version, source, and license"
                    )
                object.__setattr__(
                    self,
                    "version",
                    _printable(self.version or "", field="version", maximum=128),
                )
                object.__setattr__(self, "source", _source_record(self.source or ""))
                object.__setattr__(
                    self, "license_record", _license_record(self.license_record or "")
                )
            elif any(
                value is not None
                for value in (self.version, self.source, self.license_record)
            ):
                raise ArtifactManifestError(
                    "build-generated profile evidence must not contain guessed metadata"
                )
            try:
                locator_kind = (
                    self.locator_kind
                    if isinstance(self.locator_kind, ArtifactLocatorKind)
                    else ArtifactLocatorKind(self.locator_kind)
                )
            except (TypeError, ValueError) as exc:
                raise ArtifactManifestError(
                    "release profile locator kind is unsupported"
                ) from exc
            locator = (
                _distribution_locator(self.locator or "")
                if locator_kind
                in {
                    ArtifactLocatorKind.PYTHON_DISTRIBUTION,
                    ArtifactLocatorKind.DEBIAN_PACKAGE,
                }
                else _relative_locator(self.locator or "")
            )
            object.__setattr__(self, "locator_kind", locator_kind)
            object.__setattr__(self, "locator", locator)
            if self.fallback is not None:
                raise ArtifactManifestError("required profile artifacts cannot define fallback")
        else:
            if self.build_generated_evidence:
                raise ArtifactManifestError(
                    "disabled optional requirements cannot generate evidence"
                )
            if any(
                value is not None
                for value in (
                    self.version,
                    self.source,
                    self.license_record,
                    self.locator_kind,
                    self.locator,
                )
            ):
                raise ArtifactManifestError(
                    "unselected optional profile artifacts cannot claim unavailable evidence"
                )
            if self.fallback is None:
                raise ArtifactManifestError("optional profile artifacts require fallback")
            object.__setattr__(
                self, "fallback", _reason(self.fallback, field="fallback")
            )


@dataclass(frozen=True, slots=True)
class ReleaseArtifactProfile:
    """Authoritative, finite release inventory owned by this repository."""

    profile_id: str
    requirements: tuple[ReleaseArtifactRequirement, ...]
    schema: str = RELEASE_PROFILE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RELEASE_PROFILE_SCHEMA:
            raise ArtifactManifestError("release artifact profile schema is unsupported")
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, field="profile_id")
        )
        requirements = tuple(
            sorted(tuple(self.requirements), key=lambda item: item.artifact_id)
        )
        if not requirements or not any(item.required for item in requirements):
            raise ArtifactManifestError(
                "release artifact profile must contain required artifacts"
            )
        if any(not isinstance(item, ReleaseArtifactRequirement) for item in requirements):
            raise ArtifactManifestError(
                "release profile requirements must be typed artifact requirements"
            )
        if len({item.artifact_id for item in requirements}) != len(requirements):
            raise ArtifactManifestError("release artifact profile contains duplicate identities")
        object.__setattr__(self, "requirements", requirements)


RELEASE_ARTIFACT_PROFILE = ReleaseArtifactProfile(
    profile_id="document-parse-api-0.1.0-production",
    requirements=(
        ReleaseArtifactRequirement(
            artifact_id="python.fastapi",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="0.139.2",
            source="https://github.com/fastapi/fastapi",
            license_record="MIT",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="fastapi",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.uvicorn",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="0.51.0",
            source="https://github.com/Kludex/uvicorn",
            license_record="BSD-3-Clause",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="uvicorn",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.python-multipart",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="0.0.32",
            source="https://github.com/Kludex/python-multipart",
            license_record="Apache-2.0",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="python-multipart",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.docling",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="2.114.0",
            source="https://github.com/docling-project/docling",
            license_record="MIT",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="docling",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.pillow",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="12.3.0",
            source="https://github.com/python-pillow/Pillow",
            license_record="MIT-CMU",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="pillow",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.pypdfium2",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="5.12.1",
            source="https://github.com/pypdfium2-team/pypdfium2",
            license_record="BSD-3-Clause, Apache-2.0, dependency licenses",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="pypdfium2",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.pdfminer.six",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="20260107",
            source="https://github.com/pdfminer/pdfminer.six",
            license_record="MIT",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="pdfminer.six",
        ),
        ReleaseArtifactRequirement(
            artifact_id="python.pdfplumber",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            version="0.11.10",
            source="https://github.com/jsvine/pdfplumber",
            license_record="License :: OSI Approved :: MIT License",
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="pdfplumber",
        ),
        ReleaseArtifactRequirement(
            artifact_id="model.visual.optional",
            kind=ArtifactKind.MODEL,
            capability="visual_models",
            required=False,
            fallback="deterministic_visual",
        ),
        ReleaseArtifactRequirement(
            artifact_id="renderer.office.optional",
            kind=ArtifactKind.RENDERER,
            capability="adapters_office_fallback",
            required=False,
            fallback="native_only",
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.python.torch",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="torch",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.python.torchvision",
            kind=ArtifactKind.PYTHON_DEPENDENCY,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            locator="torchvision",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.debian.tesseract-ocr",
            kind=ArtifactKind.NATIVE_TOOL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
            locator="tesseract-ocr",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.debian.tesseract-ocr-eng",
            kind=ArtifactKind.OCR_DATA,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
            locator="tesseract-ocr-eng",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.debian.libgl1",
            kind=ArtifactKind.NATIVE_TOOL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
            locator="libgl1",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.debian.libglib2.0-0",
            kind=ArtifactKind.NATIVE_TOOL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
            locator="libglib2.0-0",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.debian.libgomp1",
            kind=ArtifactKind.NATIVE_TOOL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
            locator="libgomp1",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.model.docling-layout-heron",
            kind=ArtifactKind.MODEL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.HUGGINGFACE_MODEL,
            locator="opt/docling-models/docling-project--docling-layout-heron",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.model.docling-models",
            kind=ArtifactKind.MODEL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.HUGGINGFACE_MODEL,
            locator="opt/docling-models/docling-project--docling-models",
            build_generated_evidence=True,
        ),
        ReleaseArtifactRequirement(
            artifact_id="docker.model.document-figure-classifier",
            kind=ArtifactKind.MODEL,
            capability="local_core",
            required=True,
            locator_kind=ArtifactLocatorKind.HUGGINGFACE_MODEL,
            locator=(
                "opt/docling-models/"
                "docling-project--DocumentFigureClassifier-v2.5"
            ),
            build_generated_evidence=True,
        ),
    ),
)

LOCAL_REFERENCE_ARTIFACT_PROFILE = ReleaseArtifactProfile(
    profile_id="document-parse-api-0.1.0-local-reference",
    requirements=tuple(
        requirement
        for requirement in RELEASE_ARTIFACT_PROFILE.requirements
        if not requirement.artifact_id.startswith("docker.")
    ),
)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One shipped artifact or one explicitly disabled optional capability."""

    artifact_id: str
    kind: ArtifactKind
    required: bool
    enabled: bool
    capability: str
    version: str | None = None
    source: str | None = None
    sha256: str | None = None
    license_record: str | None = None
    locator_kind: ArtifactLocatorKind | None = None
    locator: str | None = None
    fallback: str | None = None
    unavailable_reason: str | None = None
    notices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, field="artifact_id")
        )
        object.__setattr__(
            self, "capability", _identifier(self.capability, field="capability")
        )
        try:
            kind = self.kind if isinstance(self.kind, ArtifactKind) else ArtifactKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ArtifactManifestError("artifact kind is unsupported") from exc
        object.__setattr__(self, "kind", kind)
        if not isinstance(self.required, bool) or not isinstance(self.enabled, bool):
            raise ArtifactManifestError("required and enabled must be booleans")
        if self.required and not self.enabled:
            raise ArtifactManifestError("required artifacts cannot be disabled")

        if self.enabled:
            if any(
                value is None
                for value in (
                    self.version,
                    self.source,
                    self.sha256,
                    self.license_record,
                    self.locator_kind,
                    self.locator,
                )
            ):
                raise ArtifactManifestError(
                    "enabled artifacts require version, source, SHA-256, license, and locator"
                )
            version = _printable(self.version or "", field="version", maximum=128)
            source = _source_record(self.source or "")
            digest = _sha256(self.sha256 or "")
            license_record = _license_record(self.license_record or "")
            try:
                locator_kind = (
                    self.locator_kind
                    if isinstance(self.locator_kind, ArtifactLocatorKind)
                    else ArtifactLocatorKind(self.locator_kind)
                )
            except (TypeError, ValueError) as exc:
                raise ArtifactManifestError("artifact locator kind is unsupported") from exc
            locator = (
                _distribution_locator(self.locator or "")
                if locator_kind
                in {
                    ArtifactLocatorKind.PYTHON_DISTRIBUTION,
                    ArtifactLocatorKind.DEBIAN_PACKAGE,
                }
                else _relative_locator(self.locator or "")
            )
            object.__setattr__(self, "version", version)
            object.__setattr__(self, "source", source)
            object.__setattr__(self, "sha256", digest)
            object.__setattr__(self, "license_record", license_record)
            object.__setattr__(self, "locator_kind", locator_kind)
            object.__setattr__(self, "locator", locator)
            if self.unavailable_reason is not None:
                raise ArtifactManifestError(
                    "enabled artifacts cannot carry an unavailable reason"
                )
        else:
            if self.required:
                raise ArtifactManifestError("disabled artifact cannot be required")
            if any(
                value is not None
                for value in (
                    self.version,
                    self.source,
                    self.sha256,
                    self.license_record,
                    self.locator_kind,
                    self.locator,
                )
            ):
                raise ArtifactManifestError(
                    "disabled optional artifacts must not claim unavailable evidence"
                )
            if self.fallback is None or self.unavailable_reason is None:
                raise ArtifactManifestError(
                    "disabled optional artifacts require fallback and unavailable reason"
                )

        if not self.required:
            if self.fallback is None:
                raise ArtifactManifestError("optional artifacts require a fallback")
            object.__setattr__(
                self, "fallback", _reason(self.fallback, field="fallback")
            )
        elif self.fallback is not None:
            object.__setattr__(
                self, "fallback", _reason(self.fallback, field="fallback")
            )
        if self.unavailable_reason is not None:
            object.__setattr__(
                self,
                "unavailable_reason",
                _reason(self.unavailable_reason, field="unavailable_reason"),
            )

        if not isinstance(self.notices, tuple) or any(
            not isinstance(value, str) for value in self.notices
        ):
            raise ArtifactManifestError("notices must be a tuple of reason codes")
        notices = self.notices
        if len(notices) > 32 or len(set(notices)) != len(notices):
            raise ArtifactManifestError("notices must contain at most 32 unique values")
        normalized_notices = tuple(
            sorted(_reason(value, field="notice") for value in notices)
        )
        object.__setattr__(self, "notices", normalized_notices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "required": self.required,
            "enabled": self.enabled,
            "capability": self.capability,
            "version": self.version,
            "source": self.source,
            "sha256": self.sha256,
            "license_record": self.license_record,
            "locator_kind": self.locator_kind.value if self.locator_kind else None,
            "locator": self.locator,
            "fallback": self.fallback,
            "unavailable_reason": self.unavailable_reason,
            "notices": list(self.notices),
        }


def disabled_optional_artifact(
    *,
    artifact_id: str,
    kind: ArtifactKind,
    capability: str,
    fallback: str,
    unavailable_reason: str,
) -> ArtifactRecord:
    """Represent unavailable evidence without fabricating its values."""

    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=kind,
        required=False,
        enabled=False,
        capability=capability,
        fallback=fallback,
        unavailable_reason=unavailable_reason,
    )


def _record_from_dict(value: Mapping[str, Any]) -> ArtifactRecord:
    expected = {
        "artifact_id",
        "kind",
        "required",
        "enabled",
        "capability",
        "version",
        "source",
        "sha256",
        "license_record",
        "locator_kind",
        "locator",
        "fallback",
        "unavailable_reason",
        "notices",
    }
    if set(value) != expected:
        raise ArtifactManifestError("artifact record fields differ from the schema")
    notices = value["notices"]
    if not isinstance(notices, list) or any(not isinstance(item, str) for item in notices):
        raise ArtifactManifestError("artifact notices must be a list of strings")
    return ArtifactRecord(
        artifact_id=value["artifact_id"],
        kind=value["kind"],
        required=value["required"],
        enabled=value["enabled"],
        capability=value["capability"],
        version=value["version"],
        source=value["source"],
        sha256=value["sha256"],
        license_record=value["license_record"],
        locator_kind=value["locator_kind"],
        locator=value["locator"],
        fallback=value["fallback"],
        unavailable_reason=value["unavailable_reason"],
        notices=tuple(notices),
    )


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """Canonical machine-readable release inventory."""

    release_id: str
    artifacts: tuple[ArtifactRecord, ...]
    manifest_sha256: str
    schema: str = MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MANIFEST_SCHEMA:
            raise ArtifactManifestError("artifact manifest schema is unsupported")
        object.__setattr__(
            self, "release_id", _identifier(self.release_id, field="release_id")
        )
        artifacts = tuple(sorted(tuple(self.artifacts), key=lambda item: item.artifact_id))
        if not artifacts:
            raise ArtifactManifestError("artifact manifest must not be empty")
        if len({item.artifact_id for item in artifacts}) != len(artifacts):
            raise ArtifactManifestError("artifact manifest contains a duplicate artifact")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "manifest_sha256", _sha256(self.manifest_sha256))

    @classmethod
    def create(
        cls,
        *,
        release_id: str,
        artifacts: Iterable[ArtifactRecord],
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> "ArtifactManifest":
        supplied = tuple(artifacts)
        if any(not isinstance(item, ArtifactRecord) for item in supplied):
            raise ArtifactManifestError("artifact manifest records must be ArtifactRecord values")
        ordered = tuple(sorted(supplied, key=lambda item: item.artifact_id))
        if len(ordered) > limits.max_artifacts:
            raise ArtifactManifestError("artifact manifest exceeds its record limit")
        normalized_release = _identifier(release_id, field="release_id")
        payload = {
            "schema": MANIFEST_SCHEMA,
            "release_id": normalized_release,
            "artifacts": [item.to_dict() for item in ordered],
        }
        digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
        manifest = cls(
            schema=MANIFEST_SCHEMA,
            release_id=normalized_release,
            artifacts=ordered,
            manifest_sha256=digest,
        )
        if len(manifest.to_json_bytes()) > limits.max_manifest_bytes:
            raise ArtifactManifestError("artifact manifest exceeds its byte limit")
        return manifest

    @classmethod
    def from_json_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> "ArtifactManifest":
        if not isinstance(raw, bytes) or len(raw) > limits.max_manifest_bytes:
            raise ArtifactManifestError("artifact manifest exceeds its byte limit")

        def unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ArtifactManifestError("artifact manifest contains a duplicate key")
                result[key] = value
            return result

        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactManifestError("artifact manifest is not canonical JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {
            "schema",
            "release_id",
            "artifacts",
            "manifest_sha256",
        }:
            raise ArtifactManifestError("artifact manifest fields differ from the schema")
        raw_artifacts = payload["artifacts"]
        if not isinstance(raw_artifacts, list) or len(raw_artifacts) > limits.max_artifacts:
            raise ArtifactManifestError("artifact manifest records are invalid or unbounded")
        if any(not isinstance(item, dict) for item in raw_artifacts):
            raise ArtifactManifestError("artifact manifest records must be objects")
        manifest = cls(
            schema=payload["schema"],
            release_id=payload["release_id"],
            artifacts=tuple(_record_from_dict(item) for item in raw_artifacts),
            manifest_sha256=payload["manifest_sha256"],
        )
        manifest.assert_authentic()
        return manifest

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "release_id": self.release_id,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }

    def computed_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.semantic_payload())).hexdigest()

    def assert_authentic(self) -> None:
        if self.computed_sha256() != self.manifest_sha256:
            raise ArtifactManifestError("artifact manifest digest mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {**self.semantic_payload(), "manifest_sha256": self.manifest_sha256}

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    def artifact(self, artifact_id: str) -> ArtifactRecord | None:
        target = _identifier(artifact_id, field="artifact_id")
        return next((item for item in self.artifacts if item.artifact_id == target), None)

    def binds(self, artifact_id: str, *, version: str, sha256: str) -> bool:
        """Return whether an enabled record binds the exact supplied identity."""

        item = self.artifact(artifact_id)
        return bool(
            item is not None
            and item.enabled
            and item.version == version
            and item.sha256 == sha256
        )


@dataclass(slots=True)
class _DigestBudget:
    limits: VerificationLimits
    deadline: float
    entries: int = 0
    files: int = 0
    bytes_read: int = 0

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise _LocalVerificationFailure("verification_timeout")
        if (
            self.entries > self.limits.max_files_per_artifact
            or self.files > self.limits.max_files_per_artifact
        ):
            raise _LocalVerificationFailure("file_limit_exceeded")
        if self.bytes_read > self.limits.max_bytes_per_artifact:
            raise _LocalVerificationFailure("byte_limit_exceeded")


class _LocalVerificationFailure(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _hash_file_bytes(path: Path, budget: _DigestBudget) -> tuple[str, int]:
    if path.is_symlink():
        raise _LocalVerificationFailure("symlink_not_allowed")
    if not path.is_file():
        raise _LocalVerificationFailure("artifact_missing")
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                budget.check()
                chunk = stream.read(budget.limits.read_chunk_bytes)
                if not chunk:
                    break
                size += len(chunk)
                budget.bytes_read += len(chunk)
                budget.check()
                digest.update(chunk)
    except OSError as exc:
        raise _LocalVerificationFailure("artifact_unreadable") from exc
    return digest.hexdigest(), size


def _resolve_relative(root: Path, locator: str) -> Path:
    root = root.resolve()
    current = root
    for part in PurePosixPath(locator).parts:
        current = current / part
        if current.is_symlink():
            raise _LocalVerificationFailure("symlink_not_allowed")
    try:
        resolved = current.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise _LocalVerificationFailure("locator_outside_build_root") from exc
    return resolved


def _hash_directory(path: Path, budget: _DigestBudget) -> str:
    if path.is_symlink():
        raise _LocalVerificationFailure("symlink_not_allowed")
    if not path.is_dir():
        raise _LocalVerificationFailure("artifact_missing")
    files: list[Path] = []

    def visit(directory: Path) -> None:
        budget.check()
        try:
            with os.scandir(directory) as iterator:
                entries: list[os.DirEntry[str]] = []
                for entry in iterator:
                    budget.entries += 1
                    budget.check()
                    entries.append(entry)
        except OSError as exc:
            raise _LocalVerificationFailure("artifact_unreadable") from exc
        for entry in sorted(entries, key=lambda value: value.name):
            budget.check()
            try:
                if entry.is_symlink():
                    raise _LocalVerificationFailure("symlink_not_allowed")
                candidate = Path(entry.path)
                if entry.is_file(follow_symlinks=False):
                    budget.files += 1
                    budget.check()
                    files.append(candidate)
                elif entry.is_dir(follow_symlinks=False):
                    visit(candidate)
                else:
                    raise _LocalVerificationFailure("special_file_not_allowed")
            except OSError as exc:
                raise _LocalVerificationFailure("artifact_unreadable") from exc

    visit(path)
    if not files:
        raise _LocalVerificationFailure("artifact_empty")
    digest = hashlib.sha256(b"parser-artifact-directory-v1\0")
    for candidate in sorted(
        files, key=lambda item: item.relative_to(path).as_posix()
    ):
        budget.check()
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        file_digest, size = _hash_file_bytes(candidate, budget)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest()


def _huggingface_model_evidence(
    path: Path,
    budget: _DigestBudget,
) -> tuple[str, str, str, str]:
    """Derive revision/source/license only from the downloaded model tree."""

    if path.is_symlink() or not path.is_dir():
        raise _LocalVerificationFailure("artifact_missing")
    folder = path.name
    organization, separator, repository = folder.partition("--")
    if (
        separator != "--"
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", organization)
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", repository)
    ):
        raise _LocalVerificationFailure("model_source_unavailable")
    source = _source_record(
        f"https://huggingface.co/{organization}/{repository}"
    )
    trees = path / ".cache" / "huggingface" / "trees"
    if trees.is_symlink() or not trees.is_dir():
        raise _LocalVerificationFailure("model_revision_unavailable")
    try:
        revisions = []
        with os.scandir(trees) as iterator:
            for entry in iterator:
                budget.entries += 1
                budget.check()
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise _LocalVerificationFailure("model_revision_unavailable")
                name = entry.name
                if not name.endswith(".json") or re.fullmatch(
                    r"[0-9a-f]{40}\.json", name
                ) is None:
                    raise _LocalVerificationFailure("model_revision_unavailable")
                revisions.append(name.removesuffix(".json"))
    except OSError as exc:
        raise _LocalVerificationFailure("model_revision_unavailable") from exc
    if len(revisions) != 1:
        raise _LocalVerificationFailure("model_revision_unavailable")
    revision = revisions[0]
    readme = path / "README.md"
    if readme.is_symlink() or not readme.is_file():
        raise _LocalVerificationFailure("model_license_unavailable")
    try:
        with readme.open("r", encoding="utf-8") as stream:
            header = stream.read(16_384)
    except (OSError, UnicodeDecodeError) as exc:
        raise _LocalVerificationFailure("model_license_unavailable") from exc
    frontmatter = header.split("---", 2)
    if len(frontmatter) < 3:
        raise _LocalVerificationFailure("model_license_unavailable")
    match = re.search(
        r"(?mi)^license:\s*['\"]?([A-Za-z0-9.+-]{1,128})['\"]?\s*$",
        frontmatter[1],
    )
    if match is None:
        raise _LocalVerificationFailure("model_license_unavailable")
    license_record = _license_record(match.group(1))
    digest = _hash_directory(path, budget)
    return digest, revision, source, license_record


def _hash_distribution(
    name: str,
    budget: _DigestBudget,
    *,
    candidate_root: Path,
) -> tuple[str, str]:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError as exc:
        raise _LocalVerificationFailure("artifact_missing") from exc
    version = distribution.version
    files = distribution.files
    if not files:
        raise _LocalVerificationFailure("distribution_file_inventory_missing")
    try:
        root = Path(candidate_root).resolve(strict=True)
    except OSError as exc:
        raise _LocalVerificationFailure("build_root_unavailable") from exc
    if not root.is_dir():
        raise _LocalVerificationFailure("build_root_unavailable")
    digest = hashlib.sha256(b"parser-python-distribution-v1\0")
    normalized_name = name.casefold().replace("_", "-")
    identity = f"{normalized_name}@{version}".encode("utf-8")
    digest.update(len(identity).to_bytes(4, "big"))
    digest.update(identity)
    for entry in sorted(files, key=lambda item: str(item)):
        budget.entries += 1
        budget.files += 1
        budget.check()
        relative = str(entry).replace("\\", "/").encode("utf-8")
        unresolved = Path(distribution.locate_file(entry))
        try:
            path = unresolved.resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError) as exc:
            raise _LocalVerificationFailure(
                "distribution_outside_candidate_root"
            ) from exc
        file_digest, size = _hash_file_bytes(path, budget)
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest(), version


def _debian_query(
    name: str,
    *,
    candidate_root: Path,
    arguments: Sequence[str],
    timeout_seconds: float,
) -> str:
    try:
        root = Path(candidate_root).resolve(strict=True)
    except OSError as exc:
        raise _LocalVerificationFailure("build_root_unavailable") from exc
    try:
        completed = subprocess.run(
            (
                "dpkg-query",
                f"--root={root}",
                *arguments,
                name,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.001, timeout_seconds),
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _LocalVerificationFailure("debian_metadata_unavailable") from exc
    if completed.returncode != 0:
        raise _LocalVerificationFailure("artifact_missing")
    return completed.stdout


def _debian_package_evidence(
    name: str,
    budget: _DigestBudget,
    *,
    candidate_root: Path,
) -> tuple[str, str, str, str]:
    remaining = max(0.001, budget.deadline - time.monotonic())
    fields = _debian_query(
        name,
        candidate_root=candidate_root,
        arguments=(
            "-W",
            "-f=${binary:Package}\n${source:Package}\n${Version}\n${db:Status-Abbrev}\n",
        ),
        timeout_seconds=remaining,
    ).splitlines()
    if len(fields) != 4 or fields[3].strip() != "ii":
        raise _LocalVerificationFailure("debian_metadata_unusable")
    binary_name = _distribution_locator(fields[0].split(":", 1)[0])
    source_name = _distribution_locator(fields[1].split(" ", 1)[0] or binary_name)
    version = _printable(fields[2], field="version", maximum=128)
    source = _source_record(f"pkg:debian/{source_name}@{version}")
    license_record = _license_record(
        f"pkg:debian/{source_name}@{version}/copyright"
    )
    remaining = max(0.001, budget.deadline - time.monotonic())
    listed = _debian_query(
        name,
        candidate_root=candidate_root,
        arguments=("-L",),
        timeout_seconds=remaining,
    ).splitlines()
    if not listed:
        raise _LocalVerificationFailure("distribution_file_inventory_missing")
    root = Path(candidate_root).resolve(strict=True)
    digest = hashlib.sha256(b"parser-debian-package-v1\0")
    identity = f"{binary_name}@{version}".encode("utf-8")
    digest.update(len(identity).to_bytes(4, "big"))
    digest.update(identity)
    copyright_seen = False
    hashed_entries = 0
    for raw in sorted(set(listed)):
        budget.entries += 1
        budget.check()
        if not raw.startswith("/"):
            raise _LocalVerificationFailure("debian_inventory_unsafe")
        relative_text = raw.removeprefix("/")
        path = root / relative_text
        if path.is_symlink():
            target = os.readlink(path).encode("utf-8")
            entry_digest = hashlib.sha256(b"symlink\0" + target).hexdigest()
            size = len(target)
        elif path.is_file():
            budget.files += 1
            budget.check()
            entry_digest, size = _hash_file_bytes(path, budget)
        elif path.is_dir():
            continue
        else:
            raise _LocalVerificationFailure("artifact_missing")
        if relative_text == f"usr/share/doc/{binary_name}/copyright":
            copyright_seen = True
            try:
                resolved_copyright = path.resolve(strict=True)
                resolved_copyright.relative_to(root)
            except (OSError, ValueError) as exc:
                raise _LocalVerificationFailure(
                    "debian_license_record_missing"
                ) from exc
            if not resolved_copyright.is_file():
                raise _LocalVerificationFailure("debian_license_record_missing")
            copyright_digest, copyright_size = _hash_file_bytes(
                resolved_copyright, budget
            )
            digest.update(b"copyright-target\0")
            digest.update(copyright_size.to_bytes(8, "big"))
            digest.update(bytes.fromhex(copyright_digest))
        relative = relative_text.encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry_digest))
        hashed_entries += 1
    if not hashed_entries or not copyright_seen:
        raise _LocalVerificationFailure("debian_license_record_missing")
    return digest.hexdigest(), version, source, license_record


def _local_digest(
    record: ArtifactRecord,
    root: Path,
    limits: VerificationLimits,
) -> str:
    budget = _DigestBudget(
        limits=limits,
        deadline=time.monotonic() + float(limits.timeout_seconds),
    )
    if record.locator_kind is ArtifactLocatorKind.FILE:
        path = _resolve_relative(root, record.locator or "")
        budget.files = 1
        digest, _ = _hash_file_bytes(path, budget)
        return digest
    if record.locator_kind is ArtifactLocatorKind.DIRECTORY:
        return _hash_directory(_resolve_relative(root, record.locator or ""), budget)
    if record.locator_kind is ArtifactLocatorKind.PYTHON_DISTRIBUTION:
        digest, installed_version = _hash_distribution(
            record.locator or "", budget, candidate_root=root
        )
        if installed_version != record.version:
            raise _LocalVerificationFailure("version_mismatch")
        try:
            distribution = metadata.distribution(record.locator or "")
            source = _distribution_source(distribution)
            license_record = _distribution_license(distribution)
        except (metadata.PackageNotFoundError, ArtifactManifestError) as exc:
            raise _LocalVerificationFailure("provenance_unavailable") from exc
        if source != record.source or license_record != record.license_record:
            raise _LocalVerificationFailure("provenance_mismatch")
        return digest
    if record.locator_kind is ArtifactLocatorKind.DEBIAN_PACKAGE:
        digest, installed_version, source, license_record = _debian_package_evidence(
            record.locator or "", budget, candidate_root=root
        )
        if installed_version != record.version:
            raise _LocalVerificationFailure("version_mismatch")
        if source != record.source or license_record != record.license_record:
            raise _LocalVerificationFailure("provenance_mismatch")
        return digest
    if record.locator_kind is ArtifactLocatorKind.HUGGINGFACE_MODEL:
        digest, revision, source, license_record = _huggingface_model_evidence(
            _resolve_relative(root, record.locator or ""), budget
        )
        if revision != record.version:
            raise _LocalVerificationFailure("version_mismatch")
        if source != record.source or license_record != record.license_record:
            raise _LocalVerificationFailure("provenance_mismatch")
        return digest
    raise _LocalVerificationFailure("locator_kind_unsupported")


def digest_local_artifact(
    *,
    root: Path,
    locator_kind: ArtifactLocatorKind,
    locator: str,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> str:
    """Return a deterministic digest for concrete local bytes."""

    normalized_locator = (
        _distribution_locator(locator)
        if locator_kind
        in {
            ArtifactLocatorKind.PYTHON_DISTRIBUTION,
            ArtifactLocatorKind.DEBIAN_PACKAGE,
        }
        else _relative_locator(locator)
    )
    if not isinstance(locator_kind, ArtifactLocatorKind):
        try:
            locator_kind = ArtifactLocatorKind(locator_kind)
        except (TypeError, ValueError) as exc:
            raise ArtifactManifestError("artifact locator kind is unsupported") from exc
    if locator_kind is ArtifactLocatorKind.PYTHON_DISTRIBUTION:
        budget = _DigestBudget(
            limits=limits,
            deadline=time.monotonic() + float(limits.timeout_seconds),
        )
        try:
            digest, _version = _hash_distribution(
                normalized_locator, budget, candidate_root=Path(root)
            )
            return digest
        except _LocalVerificationFailure as exc:
            raise ArtifactManifestError(
                f"local artifact cannot be hashed: {exc.reason}"
            ) from exc
    if locator_kind is ArtifactLocatorKind.DEBIAN_PACKAGE:
        budget = _DigestBudget(
            limits=limits,
            deadline=time.monotonic() + float(limits.timeout_seconds),
        )
        try:
            digest, _version, _source, _license = _debian_package_evidence(
                normalized_locator, budget, candidate_root=Path(root)
            )
            return digest
        except _LocalVerificationFailure as exc:
            raise ArtifactManifestError(
                f"local artifact cannot be hashed: {exc.reason}"
            ) from exc
    if locator_kind is ArtifactLocatorKind.HUGGINGFACE_MODEL:
        budget = _DigestBudget(
            limits=limits,
            deadline=time.monotonic() + float(limits.timeout_seconds),
        )
        try:
            digest, _revision, _source, _license = _huggingface_model_evidence(
                _resolve_relative(Path(root), normalized_locator), budget
            )
            return digest
        except _LocalVerificationFailure as exc:
            raise ArtifactManifestError(
                f"local artifact cannot be hashed: {exc.reason}"
            ) from exc

    placeholder = ArtifactRecord(
        artifact_id="digest.probe",
        kind=ArtifactKind.RUNTIME,
        required=True,
        enabled=True,
        capability="digest.probe",
        version="probe",
        source="urn:parser:digest-probe",
        sha256="0" * 64,
        license_record="internal-verification-only",
        locator_kind=locator_kind,
        locator=normalized_locator,
    )
    try:
        return _local_digest(placeholder, Path(root), limits)
    except _LocalVerificationFailure as exc:
        raise ArtifactManifestError(
            f"local artifact cannot be hashed: {exc.reason}"
        ) from exc


def path_artifact(
    *,
    root: Path,
    artifact_id: str,
    kind: ArtifactKind,
    capability: str,
    version: str,
    source: str,
    license_record: str,
    locator_kind: ArtifactLocatorKind,
    locator: str,
    required: bool,
    fallback: str | None = None,
    notices: tuple[str, ...] = (),
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactRecord:
    """Create a record from bytes present under the selected build root."""

    if locator_kind is ArtifactLocatorKind.PYTHON_DISTRIBUTION:
        raise ArtifactManifestError(
            "use python_distribution_artifact for installed distributions"
        )
    digest = digest_local_artifact(
        root=Path(root),
        locator_kind=locator_kind,
        locator=locator,
        limits=limits,
    )
    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=kind,
        required=required,
        enabled=True,
        capability=capability,
        version=version,
        source=source,
        sha256=digest,
        license_record=license_record,
        locator_kind=locator_kind,
        locator=locator,
        fallback=fallback,
        notices=notices,
    )


def _distribution_source(distribution: metadata.Distribution) -> str:
    values = distribution.metadata.get_all("Project-URL") or []
    parsed_values: list[tuple[str, str]] = []
    for value in values:
        label, separator, url = value.partition(",")
        if separator and url.strip():
            parsed_values.append((label.strip().casefold(), url.strip()))
    for preferred in ("source", "repository", "homepage"):
        for label, url in parsed_values:
            if label == preferred:
                return _source_record(url)
    homepage = distribution.metadata.get("Home-page")
    if homepage:
        return _source_record(homepage)
    raise ArtifactManifestError(
        f"{distribution.metadata.get('Name', 'distribution')} has no usable source record"
    )


def _distribution_license(distribution: metadata.Distribution) -> str:
    for field in ("License-Expression", "License"):
        value = distribution.metadata.get(field)
        if value and value.strip().casefold() not in _UNUSABLE_LICENSES:
            return _license_record(value)
    for classifier in distribution.metadata.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return _license_record(classifier)
    raise ArtifactManifestError(
        f"{distribution.metadata.get('Name', 'distribution')} has no usable license record"
    )


def python_distribution_artifact(
    distribution_name: str,
    *,
    artifact_id: str | None = None,
    capability: str = "local_core",
    required: bool = True,
    fallback: str | None = None,
    notices: tuple[str, ...] = (),
    root: Path | None = None,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactRecord:
    """Build evidence only from installed bytes and package metadata.

    Missing source or license metadata is an error.  No registry lookup or
    network request is attempted.
    """

    locator = _distribution_locator(distribution_name)
    try:
        distribution = metadata.distribution(locator)
    except metadata.PackageNotFoundError as exc:
        raise ArtifactManifestError(
            f"installed distribution unavailable: {locator}"
        ) from exc
    budget = _DigestBudget(
        limits=limits,
        deadline=time.monotonic() + float(limits.timeout_seconds),
    )
    try:
        digest, version = _hash_distribution(
            locator,
            budget,
            candidate_root=Path.cwd() if root is None else Path(root),
        )
    except _LocalVerificationFailure as exc:
        raise ArtifactManifestError(
            f"installed distribution cannot be hashed: {exc.reason}"
        ) from exc
    normalized_id = artifact_id or f"python:{locator.replace('_', '-')}"
    return ArtifactRecord(
        artifact_id=normalized_id,
        kind=ArtifactKind.PYTHON_DEPENDENCY,
        required=required,
        enabled=True,
        capability=capability,
        version=version,
        source=_distribution_source(distribution),
        sha256=digest,
        license_record=_distribution_license(distribution),
        locator_kind=ArtifactLocatorKind.PYTHON_DISTRIBUTION,
        locator=locator,
        fallback=fallback,
        notices=notices,
    )


def debian_package_artifact(
    package_name: str,
    *,
    root: Path,
    artifact_id: str,
    kind: ArtifactKind = ArtifactKind.NATIVE_TOOL,
    capability: str = "local_core",
    required: bool = True,
    fallback: str | None = None,
    notices: tuple[str, ...] = (),
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactRecord:
    """Build evidence from installed dpkg metadata, bytes, and copyright."""

    locator = _distribution_locator(package_name)
    budget = _DigestBudget(
        limits=limits,
        deadline=time.monotonic() + float(limits.timeout_seconds),
    )
    try:
        digest, version, source, license_record = _debian_package_evidence(
            locator, budget, candidate_root=Path(root)
        )
    except _LocalVerificationFailure as exc:
        raise ArtifactManifestError(
            f"installed Debian package cannot be inventoried: {exc.reason}"
        ) from exc
    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=kind,
        required=required,
        enabled=True,
        capability=capability,
        version=version,
        source=source,
        sha256=digest,
        license_record=license_record,
        locator_kind=ArtifactLocatorKind.DEBIAN_PACKAGE,
        locator=locator,
        fallback=fallback,
        notices=notices,
    )


def huggingface_model_artifact(
    *,
    root: Path,
    artifact_id: str,
    capability: str,
    locator: str,
    required: bool = True,
    fallback: str | None = None,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactRecord:
    """Build model identity from downloaded revision, card, and local bytes."""

    normalized_locator = _relative_locator(locator)
    budget = _DigestBudget(
        limits=limits,
        deadline=time.monotonic() + float(limits.timeout_seconds),
    )
    try:
        digest, revision, source, license_record = _huggingface_model_evidence(
            _resolve_relative(Path(root), normalized_locator), budget
        )
    except _LocalVerificationFailure as exc:
        raise ArtifactManifestError(
            f"downloaded model evidence is unusable: {exc.reason}"
        ) from exc
    return ArtifactRecord(
        artifact_id=artifact_id,
        kind=ArtifactKind.MODEL,
        required=required,
        enabled=True,
        capability=capability,
        version=revision,
        source=source,
        sha256=digest,
        license_record=license_record,
        locator_kind=ArtifactLocatorKind.HUGGINGFACE_MODEL,
        locator=normalized_locator,
        fallback=fallback,
    )


@dataclass(frozen=True, slots=True)
class ArtifactCheck:
    artifact_id: str
    outcome: str
    reason: str
    capability: str
    fallback: str | None = None
    actual_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ManifestVerification:
    """Bounded, content-free result for build or startup policy."""

    purpose: str
    release_id: str
    manifest_sha256: str
    accepted: bool
    checks: tuple[ArtifactCheck, ...]
    disabled_capabilities: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    profile_id: str | None = None
    _authority: object | None = field(default=None, repr=False, compare=False)

    def raise_if_blocked(self) -> "ManifestVerification":
        if not self.accepted:
            raise ArtifactVerificationError(self)
        return self


def _profile_policy(
    manifest: ArtifactManifest,
    profile: ReleaseArtifactProfile,
) -> tuple[tuple[str, ...], tuple[ArtifactCheck, ...], tuple[str, ...]]:
    """Compare one candidate with the finite repository-owned profile."""

    from app.services.feature_flags import shipping_flag_registry

    allowed_capabilities = shipping_flag_registry().capabilities | {"local_core"}
    requirements = {item.artifact_id: item for item in profile.requirements}
    records = {item.artifact_id: item for item in manifest.artifacts}
    blocking: set[str] = set()
    supplemental_checks: list[ArtifactCheck] = []
    disabled_capabilities: set[str] = set()

    for record in manifest.artifacts:
        if record.capability not in allowed_capabilities:
            blocking.add(f"{record.artifact_id}:unknown_capability")
        if record.artifact_id not in requirements:
            blocking.add(f"{record.artifact_id}:unapproved_artifact")

    for requirement in profile.requirements:
        record = records.get(requirement.artifact_id)
        if record is None:
            if requirement.required:
                blocking.add(f"{requirement.artifact_id}:profile_required_missing")
            else:
                disabled_capabilities.add(requirement.capability)
                supplemental_checks.append(
                    ArtifactCheck(
                        artifact_id=requirement.artifact_id,
                        outcome="disabled",
                        reason="profile_optional_absent",
                        capability=requirement.capability,
                        fallback=requirement.fallback,
                    )
                )
            continue
        if record.kind is not requirement.kind:
            blocking.add(f"{record.artifact_id}:profile_kind_mismatch")
        if record.capability != requirement.capability:
            blocking.add(f"{record.artifact_id}:profile_capability_mismatch")
        if record.required is not requirement.required:
            reason = (
                "profile_required_downgrade"
                if requirement.required
                else "profile_optional_promoted"
            )
            blocking.add(f"{record.artifact_id}:{reason}")
        if requirement.required:
            if not record.enabled:
                blocking.add(f"{record.artifact_id}:profile_required_disabled")
                continue
            fields = (
                ("locator_kind", "locator")
                if requirement.build_generated_evidence
                else (
                    "version",
                    "source",
                    "license_record",
                    "locator_kind",
                    "locator",
                )
            )
            for field in fields:
                if getattr(record, field) != getattr(requirement, field):
                    blocking.add(f"{record.artifact_id}:profile_{field}_mismatch")
        else:
            if record.enabled:
                blocking.add(f"{record.artifact_id}:profile_optional_unapproved")
            if record.fallback != requirement.fallback:
                blocking.add(f"{record.artifact_id}:profile_fallback_mismatch")

    return (
        tuple(sorted(blocking)),
        tuple(sorted(supplemental_checks, key=lambda item: item.artifact_id)),
        tuple(sorted(disabled_capabilities)),
    )


def verify_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    purpose: str,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Verify all enabled artifacts without network or document access."""

    normalized_purpose = _reason(purpose, field="purpose")
    if len(manifest.artifacts) > limits.max_artifacts:
        raise ArtifactManifestError("artifact manifest exceeds its record limit")
    checks: list[ArtifactCheck] = []
    disabled_capabilities: set[str] = set()
    blocking_reasons: list[str] = []
    if manifest.computed_sha256() != manifest.manifest_sha256:
        blocking_reasons.append("manifest:digest_mismatch")
    root_path = Path(root)
    if not root_path.is_dir():
        blocking_reasons.append("manifest:build_root_unavailable")

    for record in manifest.artifacts:
        if not record.enabled:
            disabled_capabilities.add(record.capability)
            checks.append(
                ArtifactCheck(
                    artifact_id=record.artifact_id,
                    outcome="disabled",
                    reason=record.unavailable_reason or "optional_disabled",
                    capability=record.capability,
                    fallback=record.fallback,
                )
            )
            continue
        try:
            actual = _local_digest(record, root_path, limits)
            reason = "verified"
            matches = actual == record.sha256
            if not matches:
                reason = "hash_mismatch"
        except _LocalVerificationFailure as exc:
            actual = None
            matches = False
            reason = exc.reason

        if matches:
            checks.append(
                ArtifactCheck(
                    artifact_id=record.artifact_id,
                    outcome="verified",
                    reason="verified",
                    capability=record.capability,
                    fallback=record.fallback,
                    actual_sha256=actual,
                )
            )
            continue

        exact_reason = f"{record.artifact_id}:{reason}"
        if record.required:
            blocking_reasons.append(exact_reason)
            outcome = "blocked"
        else:
            disabled_capabilities.add(record.capability)
            outcome = "fallback"
        checks.append(
            ArtifactCheck(
                artifact_id=record.artifact_id,
                outcome=outcome,
                reason=reason,
                capability=record.capability,
                fallback=record.fallback,
                actual_sha256=actual,
            )
        )

    return ManifestVerification(
        purpose=normalized_purpose,
        release_id=manifest.release_id,
        manifest_sha256=manifest.manifest_sha256,
        accepted=not blocking_reasons,
        checks=tuple(checks),
        disabled_capabilities=tuple(sorted(disabled_capabilities)),
        blocking_reasons=tuple(blocking_reasons),
        profile_id=None,
    )


def verify_release_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    purpose: str,
    profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Verify bytes and enforce the authoritative release inventory."""

    profile_reasons, supplemental_checks, profile_disabled = _profile_policy(
        manifest, profile
    )
    report = verify_manifest(
        manifest,
        root=root,
        purpose=purpose,
        limits=limits,
    )
    blocking = tuple(sorted(set(report.blocking_reasons) | set(profile_reasons)))
    checks = tuple(
        sorted(
            (*report.checks, *supplemental_checks),
            key=lambda item: item.artifact_id,
        )
    )
    disabled = tuple(
        sorted(set(report.disabled_capabilities) | set(profile_disabled))
    )
    return replace(
        report,
        accepted=not blocking,
        checks=checks,
        disabled_capabilities=disabled,
        blocking_reasons=blocking,
        profile_id=profile.profile_id,
        _authority=_RELEASE_VERIFICATION_AUTHORITY,
    )


def is_release_verification_attested(report: object) -> bool:
    """Recognize only reports issued by authoritative profile verification."""

    return bool(
        type(report) is ManifestVerification
        and report._authority is _RELEASE_VERIFICATION_AUTHORITY
        and report.profile_id is not None
    )


def build_release_manifest(
    *,
    release_id: str,
    root: Path,
    profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactManifest:
    """Generate concrete evidence for the current candidate, entirely offline."""

    records: list[ArtifactRecord] = []
    for requirement in profile.requirements:
        if not requirement.required:
            records.append(
                disabled_optional_artifact(
                    artifact_id=requirement.artifact_id,
                    kind=requirement.kind,
                    capability=requirement.capability,
                    fallback=requirement.fallback or "not_selected",
                    unavailable_reason="not_selected_for_release",
                )
            )
            continue
        if requirement.locator_kind is ArtifactLocatorKind.PYTHON_DISTRIBUTION:
            record = python_distribution_artifact(
                requirement.locator or "",
                artifact_id=requirement.artifact_id,
                capability=requirement.capability,
                required=True,
                root=Path(root),
                limits=limits,
            )
        elif requirement.locator_kind is ArtifactLocatorKind.DEBIAN_PACKAGE:
            record = debian_package_artifact(
                requirement.locator or "",
                root=Path(root),
                artifact_id=requirement.artifact_id,
                kind=requirement.kind,
                capability=requirement.capability,
                required=True,
                limits=limits,
            )
        elif requirement.locator_kind is ArtifactLocatorKind.HUGGINGFACE_MODEL:
            record = huggingface_model_artifact(
                root=Path(root),
                artifact_id=requirement.artifact_id,
                capability=requirement.capability,
                locator=requirement.locator or "",
                required=True,
                limits=limits,
            )
        else:
            record = path_artifact(
                root=Path(root),
                artifact_id=requirement.artifact_id,
                kind=requirement.kind,
                capability=requirement.capability,
                version=requirement.version or "",
                source=requirement.source or "",
                license_record=requirement.license_record or "",
                locator_kind=requirement.locator_kind or ArtifactLocatorKind.FILE,
                locator=requirement.locator or "",
                required=True,
                limits=limits,
            )
        records.append(record)
    manifest = ArtifactManifest.create(
        release_id=release_id,
        artifacts=records,
        limits=limits,
    )
    profile_report = verify_release_manifest(
        manifest,
        root=Path(root),
        purpose="generated_build",
        profile=profile,
        limits=limits,
    )
    profile_report.raise_if_blocked()
    return manifest


def apply_manifest_capability_rollbacks(
    settings: Any,
    verification: ManifestVerification,
) -> Any:
    """Apply optional-artifact failures to effective shipping flags."""

    if not verification.accepted:
        raise ArtifactVerificationError(verification)
    from app.services.feature_flags import shipping_flag_registry

    registry = shipping_flag_registry()
    effective = settings
    for capability in verification.disabled_capabilities:
        if capability == "local_core":
            raise ArtifactManifestError("required local-core capability cannot be disabled")
        if capability not in registry.capabilities:
            raise ArtifactManifestError(
                f"artifact capability is not a registered rollback target: {capability}"
            )
        effective = registry.rollback(effective, capability)
    return effective


def verify_build_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Fail a candidate build when required artifact evidence does not match."""

    return verify_manifest(
        manifest, root=root, purpose="build", limits=limits
    ).raise_if_blocked()


def verify_startup_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Fail startup when a required shipped artifact is missing or changed."""

    return verify_manifest(
        manifest, root=root, purpose="startup", limits=limits
    ).raise_if_blocked()


def verify_release_build_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Production build gate bound to the repository-owned profile."""

    return verify_release_manifest(
        manifest,
        root=root,
        purpose="release_build",
        profile=profile,
        limits=limits,
    ).raise_if_blocked()


def verify_release_startup_manifest(
    manifest: ArtifactManifest,
    *,
    root: Path,
    profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ManifestVerification:
    """Production startup gate bound to the repository-owned profile."""

    return verify_release_manifest(
        manifest,
        root=root,
        purpose="release_startup",
        profile=profile,
        limits=limits,
    ).raise_if_blocked()


def load_manifest(
    path: Path,
    *,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ArtifactManifest:
    """Load a bounded manifest file without following a symlink."""

    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ArtifactManifestError("artifact manifest file is unavailable or unsafe")
    try:
        size = manifest_path.stat().st_size
        if size > limits.max_manifest_bytes:
            raise ArtifactManifestError("artifact manifest exceeds its byte limit")
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ArtifactManifestError("artifact manifest file is unreadable") from exc
    return ArtifactManifest.from_json_bytes(raw, limits=limits)


@dataclass(frozen=True, slots=True)
class ConfiguredArtifactVerification:
    """Safe startup result with operationally resolved parser settings."""

    verification: ManifestVerification
    effective_settings: Any
    profile_id: str


def release_artifact_verification_requested(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the explicit digest-pinned startup gate is selected."""

    values = os.environ if environ is None else environ
    manifest_path = values.get(STARTUP_MANIFEST_PATH_ENV, "").strip()
    expected_digest = values.get(STARTUP_MANIFEST_SHA256_ENV, "").strip()
    if not manifest_path and not expected_digest:
        return False
    if not manifest_path or not expected_digest:
        raise ArtifactManifestError(
            "configured artifact verification requires manifest path and expected digest"
        )
    _printable(manifest_path, field="manifest_path", maximum=2_048)
    _sha256(expected_digest)
    return True


def verify_configured_startup_manifest(
    settings: Any,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> ConfiguredArtifactVerification | None:
    """Verify an explicitly selected release manifest before serving requests.

    With neither selection variable present this is a strict no-op.  A partial
    selection, unexpected digest, profile mismatch, or byte mismatch blocks
    startup without placing paths or configuration values in the result.
    """

    values = os.environ if environ is None else environ
    if not release_artifact_verification_requested(values):
        return None
    profile_name = values.get(STARTUP_PROFILE_ENV, "production").strip().casefold()
    selected_profile = profile
    if profile is RELEASE_ARTIFACT_PROFILE:
        if profile_name == "production":
            selected_profile = RELEASE_ARTIFACT_PROFILE
        elif profile_name == "local_reference":
            selected_profile = LOCAL_REFERENCE_ARTIFACT_PROFILE
        else:
            raise ArtifactManifestError("configured release artifact profile is unknown")
    manifest_value = values[STARTUP_MANIFEST_PATH_ENV].strip()
    expected_digest = _sha256(values[STARTUP_MANIFEST_SHA256_ENV].strip())
    base = Path.cwd() if cwd is None else Path(cwd)
    manifest_path = Path(manifest_value)
    if not manifest_path.is_absolute():
        manifest_path = base / manifest_path
    manifest = load_manifest(manifest_path, limits=limits)
    if manifest.manifest_sha256 != expected_digest:
        raise ArtifactVerificationError(
            ManifestVerification(
                purpose="release_startup",
                release_id=manifest.release_id,
                manifest_sha256=manifest.manifest_sha256,
                accepted=False,
                checks=(),
                disabled_capabilities=(),
                blocking_reasons=("manifest:unexpected_digest",),
                profile_id=None,
            )
        )
    root_value = values.get(STARTUP_CANDIDATE_ROOT_ENV, "").strip()
    candidate_root = Path(root_value) if root_value else base
    if not candidate_root.is_absolute():
        candidate_root = base / candidate_root
    report = verify_release_startup_manifest(
        manifest,
        root=candidate_root,
        profile=selected_profile,
        limits=limits,
    )
    effective = apply_manifest_capability_rollbacks(settings, report)
    return ConfiguredArtifactVerification(
        verification=report,
        effective_settings=effective,
        profile_id=selected_profile.profile_id,
    )


@dataclass(frozen=True, slots=True)
class ManifestSelection:
    manifest: ArtifactManifest
    verification: ManifestVerification
    rolled_back: bool
    requested_sha256: str


class ManifestCatalog:
    """Digest-pinned candidate selection with a deterministic known-good target."""

    def __init__(
        self,
        manifests: Iterable[ArtifactManifest],
        *,
        known_good_sha256: str,
        profile: ReleaseArtifactProfile = RELEASE_ARTIFACT_PROFILE,
    ) -> None:
        values = tuple(manifests)
        by_digest = {value.manifest_sha256: value for value in values}
        if not values or len(by_digest) != len(values):
            raise ArtifactManifestError("manifest catalog is empty or contains duplicates")
        known_good = _sha256(known_good_sha256)
        if known_good not in by_digest:
            raise ArtifactManifestError("known-good manifest is not present in catalog")
        for value in values:
            value.assert_authentic()
        self._by_digest = by_digest
        self.known_good_sha256 = known_good
        self.profile = profile

    def select(self, manifest_sha256: str) -> ArtifactManifest:
        digest = _sha256(manifest_sha256)
        try:
            return self._by_digest[digest]
        except KeyError as exc:
            raise ArtifactManifestError("requested manifest is not in the pinned catalog") from exc

    def rollback(self) -> ArtifactManifest:
        return self._by_digest[self.known_good_sha256]

    def select_verified(
        self,
        requested_sha256: str,
        *,
        candidate_root: Path,
        known_good_root: Path | None = None,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> ManifestSelection:
        """Use the candidate only if it verifies; otherwise restore known-good."""

        requested = _sha256(requested_sha256)
        candidate = self._by_digest.get(requested)
        if candidate is not None:
            candidate_report = verify_release_manifest(
                candidate,
                root=candidate_root,
                purpose="candidate_startup",
                profile=self.profile,
                limits=limits,
            )
            if candidate_report.accepted:
                return ManifestSelection(
                    manifest=candidate,
                    verification=candidate_report,
                    rolled_back=False,
                    requested_sha256=requested,
                )

        known_good = self.rollback()
        rollback_report = verify_release_manifest(
            known_good,
            root=known_good_root if known_good_root is not None else candidate_root,
            purpose="rollback_startup",
            profile=self.profile,
            limits=limits,
        )
        if not rollback_report.accepted:
            raise ArtifactVerificationError(rollback_report)
        return ManifestSelection(
            manifest=known_good,
            verification=rollback_report,
            rolled_back=True,
            requested_sha256=requested,
        )


def license_summary(manifest: ArtifactManifest) -> tuple[dict[str, Any], ...]:
    """Return a deterministic human-reviewable summary without local paths."""

    return tuple(
        {
            "artifact_id": record.artifact_id,
            "version": record.version,
            "source": record.source,
            "license_record": record.license_record,
            "notices": list(record.notices),
            "enabled": record.enabled,
            "fallback": record.fallback,
        }
        for record in manifest.artifacts
    )


def _release_cli(argv: Sequence[str] | None = None) -> int:
    """Deterministic build/verification seam for candidate-image tooling."""

    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.services.artifact_manifest")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--release-id", required=True)
    generate.add_argument("--candidate-root", required=True, type=Path)
    generate.add_argument("--output", required=True, type=Path)
    generate.add_argument("--digest-output", type=Path)
    generate.add_argument(
        "--profile", choices=("production", "local_reference"), default="production"
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", required=True, type=Path)
    expected_group = verify.add_mutually_exclusive_group(required=True)
    expected_group.add_argument("--expected-sha256")
    expected_group.add_argument("--expected-sha256-file", type=Path)
    verify.add_argument("--candidate-root", required=True, type=Path)
    verify.add_argument("--purpose", choices=("build", "startup"), default="build")
    verify.add_argument(
        "--profile", choices=("production", "local_reference"), default="production"
    )
    arguments = parser.parse_args(argv)
    profile = (
        RELEASE_ARTIFACT_PROFILE
        if arguments.profile == "production"
        else LOCAL_REFERENCE_ARTIFACT_PROFILE
    )

    if arguments.command == "generate":
        manifest = build_release_manifest(
            release_id=arguments.release_id,
            root=arguments.candidate_root,
            profile=profile,
        )
        output = arguments.output
        if output.is_symlink() or not output.parent.is_dir():
            raise ArtifactManifestError("manifest output location is unavailable or unsafe")
        output.write_bytes(manifest.to_json_bytes())
        if arguments.digest_output is not None:
            digest_output = arguments.digest_output
            if digest_output.is_symlink() or not digest_output.parent.is_dir():
                raise ArtifactManifestError(
                    "manifest digest output location is unavailable or unsafe"
                )
            digest_output.write_text(
                manifest.manifest_sha256 + "\n", encoding="ascii"
            )
        print(
            json.dumps(
                {
                    "artifact_count": len(manifest.artifacts),
                    "manifest_sha256": manifest.manifest_sha256,
                    "release_id": manifest.release_id,
                },
                sort_keys=True,
            )
        )
        return 0

    if arguments.expected_sha256_file is not None:
        expected_path = arguments.expected_sha256_file
        if expected_path.is_symlink() or not expected_path.is_file():
            raise ArtifactManifestError("manifest digest file is unavailable or unsafe")
        try:
            expected_value = expected_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ArtifactManifestError("manifest digest file is unreadable") from exc
    else:
        expected_value = arguments.expected_sha256
    expected = _sha256(expected_value)
    manifest = load_manifest(arguments.manifest)
    if manifest.manifest_sha256 != expected:
        raise ArtifactManifestError("release manifest does not match expected digest")
    report = (
        verify_release_build_manifest(
            manifest, root=arguments.candidate_root, profile=profile
        )
        if arguments.purpose == "build"
        else verify_release_startup_manifest(
            manifest, root=arguments.candidate_root, profile=profile
        )
    )
    print(
        json.dumps(
            {
                "accepted": report.accepted,
                "disabled_capabilities": list(report.disabled_capabilities),
                "manifest_sha256": report.manifest_sha256,
                "release_id": report.release_id,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "ArtifactCheck",
    "ArtifactKind",
    "ArtifactLocatorKind",
    "ArtifactManifest",
    "ArtifactManifestError",
    "ArtifactRecord",
    "ArtifactVerificationError",
    "ConfiguredArtifactVerification",
    "DEFAULT_VERIFICATION_LIMITS",
    "MANIFEST_SCHEMA",
    "LOCAL_REFERENCE_ARTIFACT_PROFILE",
    "RELEASE_ARTIFACT_PROFILE",
    "RELEASE_PROFILE_SCHEMA",
    "ReleaseArtifactProfile",
    "ReleaseArtifactRequirement",
    "STARTUP_CANDIDATE_ROOT_ENV",
    "STARTUP_MANIFEST_PATH_ENV",
    "STARTUP_MANIFEST_SHA256_ENV",
    "STARTUP_PROFILE_ENV",
    "ManifestCatalog",
    "ManifestSelection",
    "ManifestVerification",
    "VerificationLimits",
    "apply_manifest_capability_rollbacks",
    "build_release_manifest",
    "digest_local_artifact",
    "disabled_optional_artifact",
    "debian_package_artifact",
    "huggingface_model_artifact",
    "is_release_verification_attested",
    "license_summary",
    "load_manifest",
    "path_artifact",
    "python_distribution_artifact",
    "release_artifact_verification_requested",
    "verify_build_manifest",
    "verify_configured_startup_manifest",
    "verify_manifest",
    "verify_release_build_manifest",
    "verify_release_manifest",
    "verify_release_startup_manifest",
    "verify_startup_manifest",
]


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    raise SystemExit(_release_cli())
