"""Bounded, non-executing intake for OOXML packages.

This module is deliberately independent from the format-specific DOCX, PPTX,
and XLSX adapters.  It validates an uploaded package completely before making
immutable part bytes available to those adapters.  It never extracts to disk,
resolves an external relationship, executes active content, or evaluates
Office formulas and fields.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import stat
import time
import unicodedata
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree


DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PPTX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)
XLSX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

RELATIONSHIPS_CONTENT_TYPE = (
    "application/vnd.openxmlformats-package.relationships+xml"
)
OFFICE_DOCUMENT_RELATIONSHIP_SUFFIX = "/officeDocument"
CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)

_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_COMPOUND_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")
_UNSAFE_XML_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_MACRO_EXTENSIONS = frozenset(
    {
        ".docm",
        ".dotm",
        ".pptm",
        ".potm",
        ".ppsm",
        ".xlsm",
        ".xltm",
        ".xlam",
    }
)
_MACRO_PART_BASENAMES = frozenset(
    {
        "vbaproject.bin",
        "vbadata.xml",
        "customui14.xml",
    }
)
_ENCRYPTED_PART_BASENAMES = frozenset({"encryptedpackage", "encryptioninfo"})
_ALLOWED_COMPRESSION_METHODS = frozenset(
    {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
)


class OoxmlFamily(str, Enum):
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"


_DECLARATION_BY_EXTENSION: dict[str, tuple[OoxmlFamily, str]] = {
    ".docx": (OoxmlFamily.DOCX, DOCX_MIME_TYPE),
    ".pptx": (OoxmlFamily.PPTX, PPTX_MIME_TYPE),
    ".xlsx": (OoxmlFamily.XLSX, XLSX_MIME_TYPE),
}

_MAIN_CONTENT_TYPES: dict[OoxmlFamily, frozenset[str]] = {
    OoxmlFamily.DOCX: frozenset(
        {
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document.main+xml"
        }
    ),
    OoxmlFamily.PPTX: frozenset(
        {
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation.main+xml"
        }
    ),
    OoxmlFamily.XLSX: frozenset(
        {
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet.main+xml"
        }
    ),
}


class OoxmlIntakeError(ValueError):
    """Base class for content-safe, reason-coded intake failures."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.details = MappingProxyType(dict(details or {}))

    @property
    def reason_code(self) -> str:
        """Compatibility spelling used by adapter/API error translators."""

        return self.code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "stage": self.stage,
            "details": dict(self.details),
        }


class OoxmlDeclarationError(OoxmlIntakeError):
    """The extension, declared MIME, or package family is inconsistent."""


class OoxmlSignatureError(OoxmlIntakeError):
    """The supplied bytes are not a supported unencrypted ZIP package."""


class OoxmlPathError(OoxmlIntakeError):
    """A package part or relationship target violates path containment."""


class OoxmlXmlError(OoxmlIntakeError):
    """An XML part is malformed or contains a prohibited declaration."""


class OoxmlRelationshipError(OoxmlIntakeError):
    """The relationship graph is malformed or has a missing internal target."""


class OoxmlSecurityError(OoxmlIntakeError):
    """Encrypted, macro-enabled, external, or other active content was denied."""


class OoxmlResourceLimitError(OoxmlIntakeError):
    """A configured package, XML, relationship, or time limit was exceeded."""


class OoxmlPartNotFoundError(OoxmlIntakeError):
    """A format adapter requested a part absent from the validated package."""


@dataclass(frozen=True, slots=True)
class OoxmlLimits:
    """Hard intake limits, all enforced before a package is returned."""

    max_package_bytes: int = 25 * 1024 * 1024
    max_entries: int = 2_048
    max_compressed_bytes: int = 25 * 1024 * 1024
    max_uncompressed_bytes: int = 128 * 1024 * 1024
    max_part_bytes: int = 16 * 1024 * 1024
    max_xml_bytes: int = 64 * 1024 * 1024
    max_xml_nodes: int = 500_000
    max_xml_depth: int = 128
    max_relationships: int = 8_192
    max_part_name_chars: int = 512
    timeout_seconds: float = 5.0
    read_chunk_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        integer_fields = (
            "max_package_bytes",
            "max_entries",
            "max_compressed_bytes",
            "max_uncompressed_bytes",
            "max_part_bytes",
            "max_xml_bytes",
            "max_xml_nodes",
            "max_xml_depth",
            "max_relationships",
            "max_part_name_chars",
            "read_chunk_bytes",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or float(self.timeout_seconds) <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_package_bytes": self.max_package_bytes,
            "max_entries": self.max_entries,
            "max_compressed_bytes": self.max_compressed_bytes,
            "max_uncompressed_bytes": self.max_uncompressed_bytes,
            "max_part_bytes": self.max_part_bytes,
            "max_xml_bytes": self.max_xml_bytes,
            "max_xml_nodes": self.max_xml_nodes,
            "max_xml_depth": self.max_xml_depth,
            "max_relationships": self.max_relationships,
            "max_part_name_chars": self.max_part_name_chars,
            "timeout_seconds": float(self.timeout_seconds),
            "read_chunk_bytes": self.read_chunk_bytes,
        }

    @classmethod
    def from_settings(cls, settings: Any) -> OoxmlLimits:
        """Project the shared Settings fields into this intake boundary.

        Keeping this duck typed avoids a configuration import cycle and lets
        focused adapter tests supply a minimal settings double.
        """

        defaults = cls()
        uncompressed = getattr(
            settings,
            "adapters_ooxml_max_uncompressed_bytes",
            defaults.max_uncompressed_bytes,
        )
        return cls(
            max_package_bytes=getattr(
                settings,
                "max_upload_bytes",
                20 * 1024 * 1024,
            ),
            max_entries=getattr(
                settings,
                "adapters_ooxml_max_entries",
                defaults.max_entries,
            ),
            max_compressed_bytes=getattr(
                settings,
                "adapters_ooxml_max_compressed_bytes",
                defaults.max_compressed_bytes,
            ),
            max_uncompressed_bytes=uncompressed,
            max_part_bytes=getattr(
                settings,
                "adapters_ooxml_max_part_bytes",
                defaults.max_part_bytes,
            ),
            # The shared release configuration bounds total expanded XML with
            # the same aggregate envelope as all uncompressed package parts.
            max_xml_bytes=uncompressed,
            max_xml_nodes=getattr(
                settings,
                "adapters_ooxml_max_xml_nodes",
                defaults.max_xml_nodes,
            ),
            max_xml_depth=getattr(
                settings,
                "adapters_ooxml_max_xml_depth",
                defaults.max_xml_depth,
            ),
            max_relationships=getattr(
                settings,
                "adapters_ooxml_max_relationships",
                defaults.max_relationships,
            ),
            max_part_name_chars=defaults.max_part_name_chars,
            timeout_seconds=getattr(
                settings,
                "adapters_ooxml_timeout_seconds",
                defaults.timeout_seconds,
            ),
            read_chunk_bytes=defaults.read_chunk_bytes,
        )


@dataclass(frozen=True, slots=True)
class OoxmlDeclaration:
    family: OoxmlFamily
    extension: str
    mime_type: str

    def __post_init__(self) -> None:
        expected = _DECLARATION_BY_EXTENSION.get(self.extension)
        if expected != (self.family, self.mime_type):
            raise ValueError("OOXML declaration family, extension, and MIME differ")


@dataclass(frozen=True, slots=True)
class OoxmlPart:
    name: str
    content_type: str
    compressed_bytes: int
    uncompressed_bytes: int
    crc32: str
    sha256: str
    is_xml: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "content_type": self.content_type,
            "compressed_bytes": self.compressed_bytes,
            "uncompressed_bytes": self.uncompressed_bytes,
            "crc32": self.crc32,
            "sha256": self.sha256,
            "is_xml": self.is_xml,
        }


@dataclass(frozen=True, slots=True)
class OoxmlRelationship:
    relationship_part: str
    source_part: str | None
    relationship_id: str
    relationship_type: str
    target: str
    resolved_part: str
    target_fragment: str | None = None
    target_mode: str = "internal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_part": self.relationship_part,
            "source_part": self.source_part,
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "target": self.target,
            "resolved_part": self.resolved_part,
            "target_fragment": self.target_fragment,
            "target_mode": self.target_mode,
        }


@dataclass(frozen=True, slots=True)
class OoxmlSecurityPolicy:
    external_relationships: str = "deny"
    macros: str = "deny"
    encryption: str = "deny"
    network_access: str = "prohibited"
    active_content_execution: str = "prohibited"
    formula_and_field_execution: str = "prohibited"
    package_storage: str = "memory_only_read_only"

    def to_dict(self) -> dict[str, str]:
        return {
            "external_relationships": self.external_relationships,
            "macros": self.macros,
            "encryption": self.encryption,
            "network_access": self.network_access,
            "active_content_execution": self.active_content_execution,
            "formula_and_field_execution": self.formula_and_field_execution,
            "package_storage": self.package_storage,
        }


@dataclass(frozen=True, slots=True)
class OoxmlManifest:
    schema_version: str
    family: OoxmlFamily
    extension: str
    mime_type: str
    package_sha256: str
    package_bytes: int
    entry_count: int
    compressed_bytes: int
    uncompressed_bytes: int
    xml_bytes: int
    xml_nodes: int
    main_part: str
    parts: tuple[OoxmlPart, ...]
    relationships: tuple[OoxmlRelationship, ...]
    limits: OoxmlLimits
    security_policy: OoxmlSecurityPolicy

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "family": self.family.value,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "package_sha256": self.package_sha256,
            "package_bytes": self.package_bytes,
            "entry_count": self.entry_count,
            "compressed_bytes": self.compressed_bytes,
            "uncompressed_bytes": self.uncompressed_bytes,
            "xml_bytes": self.xml_bytes,
            "xml_nodes": self.xml_nodes,
            "main_part": self.main_part,
            "parts": [part.to_dict() for part in self.parts],
            "relationships": [
                relationship.to_dict() for relationship in self.relationships
            ],
            "limits": self.limits.to_dict(),
            "security_policy": self.security_policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OoxmlPackage:
    """A completely validated package with immutable, bounded part access."""

    manifest: OoxmlManifest
    _parts: Mapping[str, bytes] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        detached = {str(name): bytes(value) for name, value in self._parts.items()}
        expected_names = tuple(part.name for part in self.manifest.parts)
        if tuple(sorted(detached)) != expected_names:
            raise ValueError("package parts differ from the validated manifest")
        for part in self.manifest.parts:
            data = detached[part.name]
            if (
                len(data) != part.uncompressed_bytes
                or hashlib.sha256(data).hexdigest() != part.sha256
            ):
                raise ValueError("package part bytes differ from the manifest")
        object.__setattr__(self, "_parts", MappingProxyType(detached))

    @property
    def part_names(self) -> tuple[str, ...]:
        return tuple(part.name for part in self.manifest.parts)

    @property
    def source_sha256(self) -> str:
        """Source identity spelling consumed by native Office adapters."""

        return self.manifest.package_sha256

    def list_parts(self) -> tuple[str, ...]:
        return self.part_names

    def has_part(self, name: str) -> bool:
        canonical = _canonical_part_name(
            name,
            limits=self.manifest.limits,
            stage="part_access",
        )
        return canonical in self._parts

    def read_part(self, name: str, *, max_bytes: int | None = None) -> bytes:
        canonical = _canonical_part_name(
            name,
            limits=self.manifest.limits,
            stage="part_access",
        )
        value = self._parts.get(canonical)
        if value is None:
            raise OoxmlPartNotFoundError(
                "part_not_found",
                "The requested OOXML part is not present.",
                stage="part_access",
                details={"part_name": canonical},
            )
        if max_bytes is not None:
            if (
                isinstance(max_bytes, bool)
                or not isinstance(max_bytes, int)
                or max_bytes < 0
            ):
                raise ValueError("max_bytes must be a non-negative integer")
            if len(value) > max_bytes:
                _raise_limit(
                    "part_read_bytes",
                    max_bytes,
                    len(value),
                    stage="part_access",
                )
        return value


@dataclass(slots=True)
class _Budget:
    limits: OoxmlLimits
    clock: Callable[[], float]
    started: float
    deadline: float
    xml_bytes: int = 0
    xml_nodes: int = 0
    relationships: int = 0

    @classmethod
    def start(
        cls,
        limits: OoxmlLimits,
        clock: Callable[[], float],
    ) -> _Budget:
        started = float(clock())
        if not math.isfinite(started):
            raise ValueError("clock must return finite values")
        return cls(
            limits=limits,
            clock=clock,
            started=started,
            deadline=started + float(limits.timeout_seconds),
        )

    def check_time(self, stage: str) -> None:
        now = float(self.clock())
        if not math.isfinite(now):
            raise ValueError("clock must return finite values")
        if now > self.deadline:
            raise OoxmlResourceLimitError(
                "processing_time_limit",
                "OOXML intake exceeded its processing-time limit.",
                stage=stage,
                details={
                    "limit_seconds": float(self.limits.timeout_seconds),
                    "elapsed_seconds": round(max(now - self.started, 0.0), 6),
                },
            )

    def add_xml_bytes(self, amount: int, *, stage: str) -> None:
        self.xml_bytes += amount
        if self.xml_bytes > self.limits.max_xml_bytes:
            _raise_limit(
                "xml_bytes",
                self.limits.max_xml_bytes,
                self.xml_bytes,
                stage=stage,
            )

    def add_xml_node(self, *, depth: int, stage: str) -> None:
        self.xml_nodes += 1
        if self.xml_nodes > self.limits.max_xml_nodes:
            _raise_limit(
                "xml_nodes",
                self.limits.max_xml_nodes,
                self.xml_nodes,
                stage=stage,
            )
        if depth > self.limits.max_xml_depth:
            _raise_limit(
                "xml_depth",
                self.limits.max_xml_depth,
                depth,
                stage=stage,
            )

    def add_relationship(self, *, stage: str) -> None:
        self.relationships += 1
        if self.relationships > self.limits.max_relationships:
            _raise_limit(
                "relationships",
                self.limits.max_relationships,
                self.relationships,
                stage=stage,
            )


def _raise_limit(name: str, limit: int, observed: int, *, stage: str) -> None:
    raise OoxmlResourceLimitError(
        f"{name}_limit",
        f"OOXML intake exceeded the configured {name} limit.",
        stage=stage,
        details={"limit_name": name, "limit": limit, "observed": observed},
    )


def detect_ooxml_type(
    filename: str | OoxmlDeclaration | Any,
    mime_type: str | None = None,
) -> OoxmlDeclaration:
    """Validate one OOXML extension/MIME declaration without reading bytes."""

    if isinstance(filename, OoxmlDeclaration):
        normalized_mime = (
            (mime_type or filename.mime_type)
            .split(";", 1)[0]
            .strip()
            .casefold()
        )
        if normalized_mime != filename.mime_type:
            raise OoxmlDeclarationError(
                "mime_mismatch",
                "The declared media type does not match the OOXML declaration.",
                stage="declaration",
            )
        return filename

    declared_object = None
    if not isinstance(filename, str):
        declared_object = filename
        extension_value = getattr(filename, "extension", None)
        filename = (
            f"document{extension_value}"
            if isinstance(extension_value, str)
            else ""
        )
        if mime_type is None:
            object_mime = getattr(declared_object, "mime_type", None)
            mime_type = object_mime if isinstance(object_mime, str) else None
    if not filename:
        raise OoxmlDeclarationError(
            "invalid_filename",
            "The OOXML filename or declaration is invalid.",
            stage="declaration",
        )
    normalized_filename = filename.replace("\\", "/")
    extension = (
        normalized_filename.casefold()
        if normalized_filename.casefold() in _DECLARATION_BY_EXTENSION
        or normalized_filename.casefold() in _MACRO_EXTENSIONS
        else PurePosixPath(normalized_filename).suffix.casefold()
    )
    if extension in _MACRO_EXTENSIONS:
        raise OoxmlSecurityError(
            "macro_enabled_extension_denied",
            "Macro-enabled Office packages are not supported.",
            stage="declaration",
            details={"extension": extension},
        )
    expected = _DECLARATION_BY_EXTENSION.get(extension)
    if expected is None:
        raise OoxmlDeclarationError(
            "unsupported_extension",
            "The filename does not declare a supported OOXML family.",
            stage="declaration",
            details={
                "extension": extension or None,
                "supported_extensions": sorted(_DECLARATION_BY_EXTENSION),
            },
        )
    normalized_mime = (mime_type or "").split(";", 1)[0].strip().casefold()
    family, expected_mime = expected
    if normalized_mime != expected_mime:
        raise OoxmlDeclarationError(
            "mime_mismatch",
            "The declared media type does not match the OOXML extension.",
            stage="declaration",
            details={
                "extension": extension,
                "content_type": normalized_mime or None,
                "expected_content_type": expected_mime,
            },
        )
    declaration = OoxmlDeclaration(
        family=family,
        extension=extension,
        mime_type=expected_mime,
    )
    if declared_object is not None:
        raw_kind = getattr(declared_object, "kind", None)
        kind_value = getattr(raw_kind, "value", raw_kind)
        if isinstance(kind_value, str) and kind_value.casefold() != family.value:
            raise OoxmlDeclarationError(
                "family_mismatch",
                "The OOXML input-kind declaration differs from its extension.",
                stage="declaration",
                details={
                    "declared_family": kind_value.casefold(),
                    "extension_family": family.value,
                },
            )
    return declaration


def _canonical_part_name(
    raw_name: str,
    *,
    limits: OoxmlLimits,
    stage: str,
) -> str:
    if not isinstance(raw_name, str) or not raw_name:
        raise OoxmlPathError(
            "part_path_empty",
            "An OOXML part name is empty.",
            stage=stage,
        )
    if len(raw_name) > limits.max_part_name_chars:
        _raise_limit(
            "part_name_chars",
            limits.max_part_name_chars,
            len(raw_name),
            stage=stage,
        )
    if "\\" in raw_name:
        raise OoxmlPathError(
            "part_path_backslash",
            "OOXML part names must use POSIX separators.",
            stage=stage,
        )
    if raw_name.startswith("/") or _WINDOWS_DRIVE.match(raw_name):
        raise OoxmlPathError(
            "part_path_absolute",
            "Absolute OOXML part paths are prohibited.",
            stage=stage,
        )

    decoded = unquote(raw_name)
    if decoded.count("/") != raw_name.count("/") or "\\" in decoded:
        raise OoxmlPathError(
            "part_path_encoded_separator",
            "Encoded OOXML path separators are prohibited.",
            stage=stage,
        )
    normalized = unicodedata.normalize("NFC", decoded)
    if _CONTROL_CHARACTER.search(normalized):
        raise OoxmlPathError(
            "part_path_control_character",
            "OOXML part names cannot contain control characters.",
            stage=stage,
        )
    components = normalized.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise OoxmlPathError(
            "part_path_traversal",
            "OOXML part paths must remain within the package root.",
            stage=stage,
        )
    return "/".join(components)


def _safe_xml(
    data: bytes,
    *,
    part_name: str,
    budget: _Budget,
) -> ElementTree.Element:
    stage = "xml"
    budget.add_xml_bytes(len(data), stage=stage)
    budget.check_time(stage)
    if _UNSAFE_XML_DECLARATION.search(data):
        raise OoxmlXmlError(
            "unsafe_xml_declaration",
            "DTD and entity declarations are prohibited in OOXML parts.",
            stage=stage,
            details={"part_name": part_name},
        )

    parser = ElementTree.XMLPullParser(events=("start", "end"))
    depth = 0
    root: ElementTree.Element | None = None

    def consume_events() -> None:
        nonlocal depth, root
        for event, element in parser.read_events():
            if event == "start":
                depth += 1
                if root is None:
                    root = element
                budget.add_xml_node(depth=depth, stage=stage)
            else:
                depth -= 1
                if depth < 0:
                    raise OoxmlXmlError(
                        "xml_malformed",
                        "An OOXML XML part has unbalanced elements.",
                        stage=stage,
                        details={"part_name": part_name},
                    )
            budget.check_time(stage)

    try:
        chunk_size = budget.limits.read_chunk_bytes
        for offset in range(0, len(data), chunk_size):
            parser.feed(data[offset : offset + chunk_size])
            consume_events()
        parser.close()
        consume_events()
    except ElementTree.ParseError as exc:
        raise OoxmlXmlError(
            "xml_malformed",
            "An OOXML XML part is malformed.",
            stage=stage,
            details={"part_name": part_name},
        ) from exc

    if root is None or depth != 0:
        raise OoxmlXmlError(
            "xml_malformed",
            "An OOXML XML part is empty or unbalanced.",
            stage=stage,
            details={"part_name": part_name},
        )
    return root


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_content_types(
    root: ElementTree.Element,
    *,
    part_names: frozenset[str],
    limits: OoxmlLimits,
) -> tuple[dict[str, str], dict[str, str]]:
    if root.tag != f"{{{CONTENT_TYPES_NAMESPACE}}}Types":
        raise OoxmlXmlError(
            "content_types_root_invalid",
            "The content-types part has an invalid root element.",
            stage="content_types",
        )
    defaults: dict[str, str] = {}
    overrides: dict[str, str] = {}
    for child in root:
        if not child.tag.startswith(f"{{{CONTENT_TYPES_NAMESPACE}}}"):
            raise OoxmlXmlError(
                "content_type_declaration_invalid",
                "A content-types declaration has an invalid namespace.",
                stage="content_types",
            )
        kind = _local_name(child.tag)
        if kind == "Default":
            extension = str(child.attrib.get("Extension") or "").casefold()
            content_type = str(child.attrib.get("ContentType") or "").strip()
            if (
                not extension
                or extension.startswith(".")
                or "/" in extension
                or "\\" in extension
                or _CONTROL_CHARACTER.search(extension)
                or not _valid_content_type(content_type)
            ):
                raise OoxmlXmlError(
                    "content_type_declaration_invalid",
                    "A default OOXML content-type declaration is invalid.",
                    stage="content_types",
                )
            if extension in defaults:
                raise OoxmlXmlError(
                    "content_type_declaration_duplicate",
                    "An OOXML content-type declaration is duplicated.",
                    stage="content_types",
                    details={"extension": extension},
                )
            defaults[extension] = content_type.casefold()
        elif kind == "Override":
            raw_part_name = str(child.attrib.get("PartName") or "")
            content_type = str(child.attrib.get("ContentType") or "").strip()
            if not raw_part_name.startswith("/") or raw_part_name.startswith("//"):
                raise OoxmlXmlError(
                    "content_type_declaration_invalid",
                    "An override OOXML part name must be package-root relative.",
                    stage="content_types",
                )
            part_name = _canonical_part_name(
                raw_part_name[1:],
                limits=limits,
                stage="content_types",
            )
            if not _valid_content_type(content_type):
                raise OoxmlXmlError(
                    "content_type_declaration_invalid",
                    "An override OOXML content type is invalid.",
                    stage="content_types",
                    details={"part_name": part_name},
                )
            if part_name in overrides:
                raise OoxmlXmlError(
                    "content_type_declaration_duplicate",
                    "An OOXML content-type override is duplicated.",
                    stage="content_types",
                    details={"part_name": part_name},
                )
            if part_name not in part_names:
                raise OoxmlXmlError(
                    "content_type_override_target_missing",
                    "A content-type override references a missing part.",
                    stage="content_types",
                    details={"part_name": part_name},
                )
            overrides[part_name] = content_type.casefold()
        else:
            raise OoxmlXmlError(
                "content_type_declaration_invalid",
                "The content-types part contains an unsupported declaration.",
                stage="content_types",
            )
    return defaults, overrides


def _valid_content_type(value: str) -> bool:
    return (
        bool(value)
        and "/" in value
        and ";" not in value
        and _CONTROL_CHARACTER.search(value) is None
        and len(value) <= 512
    )


def _resolve_content_types(
    part_names: frozenset[str],
    defaults: Mapping[str, str],
    overrides: Mapping[str, str],
) -> dict[str, str]:
    resolved = {"[Content_Types].xml": "application/xml"}
    for part_name in sorted(part_names - {"[Content_Types].xml"}):
        content_type = overrides.get(part_name)
        if content_type is None:
            # ``PurePosixPath('_rels/.rels').suffix`` is empty because the
            # root relationship part is itself a dotfile. OPC nevertheless
            # applies the ordinary ``rels`` default declaration to it.
            extension = (
                "rels"
                if part_name.casefold().endswith(".rels")
                else PurePosixPath(part_name).suffix.lstrip(".").casefold()
            )
            content_type = defaults.get(extension)
        if content_type is None:
            raise OoxmlXmlError(
                "content_type_missing",
                "An OOXML package part has no declared content type.",
                stage="content_types",
                details={"part_name": part_name},
            )
        resolved[part_name] = content_type
    return resolved


def _is_xml_part(part_name: str, content_type: str) -> bool:
    normalized_type = content_type.casefold()
    return (
        part_name.casefold().endswith((".xml", ".rels"))
        or normalized_type.endswith("+xml")
        or normalized_type in {"application/xml", "text/xml"}
    )


def _relationship_source(
    relationship_part: str,
    part_names: frozenset[str],
) -> str | None:
    if relationship_part == "_rels/.rels":
        return None
    components = relationship_part.split("/")
    if (
        len(components) < 3
        or components[-2] != "_rels"
        or not components[-1].endswith(".rels")
        or components[-1] == ".rels"
    ):
        raise OoxmlRelationshipError(
            "relationship_part_path_invalid",
            "An OOXML relationship part has an invalid package path.",
            stage="relationships",
            details={"part_name": relationship_part},
        )
    source_name = components[-1][: -len(".rels")]
    source_part = "/".join((*components[:-2], source_name))
    if source_part not in part_names:
        raise OoxmlRelationshipError(
            "relationship_source_missing",
            "An OOXML relationship part has no corresponding source part.",
            stage="relationships",
            details={"part_name": relationship_part},
        )
    return source_part


def _resolve_relationship_target(
    target: str,
    *,
    source_part: str | None,
    limits: OoxmlLimits,
) -> tuple[str, str | None]:
    if not target or _CONTROL_CHARACTER.search(target):
        raise OoxmlRelationshipError(
            "relationship_target_invalid",
            "An OOXML relationship target is empty or invalid.",
            stage="relationships",
        )
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query:
        raise OoxmlRelationshipError(
            "relationship_target_invalid",
            "An internal OOXML relationship target is not a package part URI.",
            stage="relationships",
        )
    if parsed.path.startswith("/") or "\\" in parsed.path:
        raise OoxmlPathError(
            "relationship_target_absolute",
            "An internal OOXML relationship target must remain package relative.",
            stage="relationships",
        )
    decoded = unquote(parsed.path)
    if decoded.count("/") != parsed.path.count("/") or "\\" in decoded:
        raise OoxmlPathError(
            "relationship_target_encoded_separator",
            "Encoded relationship path separators are prohibited.",
            stage="relationships",
        )
    if len(decoded) > limits.max_part_name_chars:
        _raise_limit(
            "part_name_chars",
            limits.max_part_name_chars,
            len(decoded),
            stage="relationships",
        )

    base = [] if source_part is None else source_part.split("/")[:-1]
    if not decoded:
        if source_part is None or not parsed.fragment:
            raise OoxmlRelationshipError(
                "relationship_target_invalid",
                "An internal OOXML relationship target has no package part.",
                stage="relationships",
            )
        resolved = source_part
    else:
        for component in unicodedata.normalize("NFC", decoded).split("/"):
            if component in {"", "."}:
                continue
            if component == "..":
                if not base:
                    raise OoxmlPathError(
                        "relationship_target_escape",
                        "An OOXML relationship target escapes the package root.",
                        stage="relationships",
                    )
                base.pop()
                continue
            if _CONTROL_CHARACTER.search(component):
                raise OoxmlPathError(
                    "relationship_target_control_character",
                    "An OOXML relationship target contains a control character.",
                    stage="relationships",
                )
            base.append(component)
        if not base:
            raise OoxmlRelationshipError(
                "relationship_target_invalid",
                "An internal OOXML relationship target has no package part.",
                stage="relationships",
            )
        resolved = "/".join(base)
        resolved = _canonical_part_name(
            resolved,
            limits=limits,
            stage="relationships",
        )

    fragment = parsed.fragment or None
    if fragment is not None and (
        len(fragment) > limits.max_part_name_chars
        or _CONTROL_CHARACTER.search(fragment)
    ):
        raise OoxmlRelationshipError(
            "relationship_fragment_invalid",
            "An OOXML relationship fragment is invalid.",
            stage="relationships",
        )
    return resolved, fragment


def _parse_relationships(
    xml_roots: Mapping[str, ElementTree.Element],
    *,
    part_names: frozenset[str],
    content_types: Mapping[str, str],
    budget: _Budget,
) -> tuple[OoxmlRelationship, ...]:
    relationships: list[OoxmlRelationship] = []
    for relationship_part in sorted(
        name for name in part_names if name.casefold().endswith(".rels")
    ):
        budget.check_time("relationships")
        if content_types.get(relationship_part) != RELATIONSHIPS_CONTENT_TYPE:
            raise OoxmlRelationshipError(
                "relationship_content_type_invalid",
                "An OOXML relationship part has an invalid content type.",
                stage="relationships",
                details={"part_name": relationship_part},
            )
        root = xml_roots.get(relationship_part)
        if root is None or root.tag != f"{{{RELATIONSHIPS_NAMESPACE}}}Relationships":
            raise OoxmlRelationshipError(
                "relationships_root_invalid",
                "An OOXML relationship part has an invalid root element.",
                stage="relationships",
                details={"part_name": relationship_part},
            )
        source_part = _relationship_source(relationship_part, part_names)
        seen_ids: set[str] = set()
        for child in root:
            budget.add_relationship(stage="relationships")
            if (
                child.tag != f"{{{RELATIONSHIPS_NAMESPACE}}}Relationship"
                or list(child)
            ):
                raise OoxmlRelationshipError(
                    "relationship_record_invalid",
                    "An OOXML relationship record is malformed.",
                    stage="relationships",
                    details={"part_name": relationship_part},
                )
            relationship_id = str(child.attrib.get("Id") or "")
            relationship_type = str(child.attrib.get("Type") or "")
            target = str(child.attrib.get("Target") or "")
            target_mode = str(child.attrib.get("TargetMode") or "Internal")
            if (
                not relationship_id
                or len(relationship_id) > 256
                or _CONTROL_CHARACTER.search(relationship_id)
                or not relationship_type
                or len(relationship_type) > 1_024
                or _CONTROL_CHARACTER.search(relationship_type)
            ):
                raise OoxmlRelationshipError(
                    "relationship_record_invalid",
                    "An OOXML relationship record is malformed.",
                    stage="relationships",
                    details={"part_name": relationship_part},
                )
            if relationship_id in seen_ids:
                raise OoxmlRelationshipError(
                    "relationship_id_duplicate",
                    "An OOXML relationship identifier is duplicated.",
                    stage="relationships",
                    details={"part_name": relationship_part},
                )
            seen_ids.add(relationship_id)
            normalized_type = relationship_type.casefold()
            if "vbaproject" in normalized_type or "macro" in normalized_type:
                raise OoxmlSecurityError(
                    "macro_relationship_denied",
                    "Macro relationships are prohibited.",
                    stage="relationships",
                    details={
                        "part_name": relationship_part,
                        "relationship_id": relationship_id,
                    },
                )
            normalized_mode = target_mode.casefold()
            if normalized_mode == "external":
                raise OoxmlSecurityError(
                    "external_relationship_denied",
                    "External OOXML relationships are prohibited.",
                    stage="relationships",
                    details={
                        "part_name": relationship_part,
                        "relationship_id": relationship_id,
                    },
                )
            if normalized_mode != "internal":
                raise OoxmlRelationshipError(
                    "relationship_target_mode_invalid",
                    "An OOXML relationship target mode is invalid.",
                    stage="relationships",
                    details={"part_name": relationship_part},
                )
            resolved_part, fragment = _resolve_relationship_target(
                target,
                source_part=source_part,
                limits=budget.limits,
            )
            if resolved_part not in part_names:
                raise OoxmlRelationshipError(
                    "relationship_target_missing",
                    "An internal OOXML relationship references a missing part.",
                    stage="relationships",
                    details={
                        "part_name": relationship_part,
                        "relationship_id": relationship_id,
                        "resolved_part": resolved_part,
                    },
                )
            relationships.append(
                OoxmlRelationship(
                    relationship_part=relationship_part,
                    source_part=source_part,
                    relationship_id=relationship_id,
                    relationship_type=relationship_type,
                    target=target,
                    resolved_part=resolved_part,
                    target_fragment=fragment,
                )
            )
    return tuple(
        sorted(
            relationships,
            key=lambda relationship: (
                relationship.source_part or "",
                relationship.relationship_id,
                relationship.relationship_type,
                relationship.resolved_part,
            ),
        )
    )


def _validate_active_content(
    part_names: frozenset[str],
    content_types: Mapping[str, str],
) -> None:
    for part_name in sorted(part_names):
        basename = PurePosixPath(part_name).name.casefold()
        if basename in _ENCRYPTED_PART_BASENAMES:
            raise OoxmlSecurityError(
                "encrypted_package_denied",
                "Encrypted Office package content is not supported.",
                stage="security_policy",
            )
        content_type = content_types.get(part_name, "").casefold()
        if (
            basename in _MACRO_PART_BASENAMES
            or "macroenabled" in content_type
            or "vbaproject" in content_type
        ):
            raise OoxmlSecurityError(
                "macro_content_denied",
                "Macro-enabled Office package content is prohibited.",
                stage="security_policy",
                details={"part_name": part_name},
            )


def _main_part_and_family(
    relationships: tuple[OoxmlRelationship, ...],
    content_types: Mapping[str, str],
) -> tuple[str, OoxmlFamily]:
    roots = [
        relationship
        for relationship in relationships
        if relationship.source_part is None
        and relationship.relationship_type.endswith(
            OFFICE_DOCUMENT_RELATIONSHIP_SUFFIX
        )
    ]
    if len(roots) != 1:
        raise OoxmlRelationshipError(
            "office_document_relationship_invalid",
            "The package must declare exactly one root Office document part.",
            stage="package_family",
            details={"relationship_count": len(roots)},
        )
    main_part = roots[0].resolved_part
    main_content_type = content_types.get(main_part, "").casefold()
    matching = [
        family
        for family, allowed in _MAIN_CONTENT_TYPES.items()
        if main_content_type in allowed
    ]
    if len(matching) != 1:
        raise OoxmlDeclarationError(
            "main_content_type_invalid",
            "The root Office document part has an unsupported content type.",
            stage="package_family",
            details={"main_part": main_part},
        )
    return main_part, matching[0]


def _zip_parts(
    payload: bytes,
    *,
    limits: OoxmlLimits,
    budget: _Budget,
) -> tuple[
    dict[str, bytes],
    dict[str, zipfile.ZipInfo],
    int,
    int,
    int,
]:
    parts: dict[str, bytes] = {}
    infos: dict[str, zipfile.ZipInfo] = {}
    equivalent_names: dict[str, str] = {}
    compressed_total = 0
    uncompressed_total = 0
    streamed_total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_entries:
                _raise_limit(
                    "entries",
                    limits.max_entries,
                    len(entries),
                    stage="zip_directory",
                )
            for info in entries:
                budget.check_time("zip_directory")
                raw_name = info.filename[:-1] if info.is_dir() else info.filename
                canonical = _canonical_part_name(
                    raw_name,
                    limits=limits,
                    stage="zip_directory",
                )
                if canonical in infos:
                    raise OoxmlPathError(
                        "duplicate_part",
                        "The OOXML ZIP contains duplicate canonical part names.",
                        stage="zip_directory",
                        details={"part_name": canonical},
                    )
                equivalent = canonical.casefold()
                if equivalent in equivalent_names:
                    raise OoxmlPathError(
                        "duplicate_part",
                        "The OOXML ZIP contains case-equivalent part names.",
                        stage="zip_directory",
                        details={"part_name": canonical},
                    )
                equivalent_names[equivalent] = canonical
                infos[canonical] = info
                compressed_total += int(info.compress_size)
                uncompressed_total += int(info.file_size)
                if compressed_total > limits.max_compressed_bytes:
                    _raise_limit(
                        "compressed_bytes",
                        limits.max_compressed_bytes,
                        compressed_total,
                        stage="zip_directory",
                    )
                if uncompressed_total > limits.max_uncompressed_bytes:
                    _raise_limit(
                        "uncompressed_bytes",
                        limits.max_uncompressed_bytes,
                        uncompressed_total,
                        stage="zip_directory",
                    )
                if info.file_size > limits.max_part_bytes:
                    _raise_limit(
                        "part_bytes",
                        limits.max_part_bytes,
                        int(info.file_size),
                        stage="zip_directory",
                    )
                if info.flag_bits & 0x1:
                    raise OoxmlSecurityError(
                        "encrypted_entry_denied",
                        "Encrypted ZIP entries are not supported.",
                        stage="zip_directory",
                    )
                if info.compress_type not in _ALLOWED_COMPRESSION_METHODS:
                    raise OoxmlSecurityError(
                        "compression_method_denied",
                        "The OOXML ZIP uses an unsupported compression method.",
                        stage="zip_directory",
                        details={"compression_method": int(info.compress_type)},
                    )
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_kind = stat.S_IFMT(unix_mode)
                if file_kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise OoxmlSecurityError(
                        "special_zip_entry_denied",
                        "Special filesystem entries are prohibited in OOXML ZIPs.",
                        stage="zip_directory",
                    )

            for canonical in sorted(infos):
                info = infos[canonical]
                if info.is_dir():
                    continue
                buffer = bytearray()
                with archive.open(info, mode="r") as stream:
                    while True:
                        budget.check_time("part_read")
                        chunk = stream.read(limits.read_chunk_bytes)
                        if not chunk:
                            break
                        buffer.extend(chunk)
                        streamed_total += len(chunk)
                        if len(buffer) > limits.max_part_bytes:
                            _raise_limit(
                                "part_bytes",
                                limits.max_part_bytes,
                                len(buffer),
                                stage="part_read",
                            )
                        if streamed_total > limits.max_uncompressed_bytes:
                            _raise_limit(
                                "uncompressed_bytes",
                                limits.max_uncompressed_bytes,
                                streamed_total,
                                stage="part_read",
                            )
                if len(buffer) != info.file_size:
                    raise OoxmlSignatureError(
                        "zip_size_mismatch",
                        "An OOXML ZIP part differs from its directory size.",
                        stage="part_read",
                        details={"part_name": canonical},
                    )
                parts[canonical] = bytes(buffer)
    except OoxmlIntakeError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError) as exc:
        raise OoxmlSignatureError(
            "invalid_zip",
            "The uploaded OOXML ZIP is malformed or truncated.",
            stage="zip",
        ) from exc
    except NotImplementedError as exc:
        raise OoxmlSecurityError(
            "compression_method_denied",
            "The OOXML ZIP uses an unsupported compression method.",
            stage="zip",
        ) from exc
    except MemoryError as exc:
        raise OoxmlResourceLimitError(
            "memory_allocation_refused",
            "OOXML intake could not remain within its memory envelope.",
            stage="part_read",
        ) from exc
    return parts, infos, len(infos), compressed_total, uncompressed_total


def intake_ooxml(
    data: bytes | bytearray | memoryview,
    filename: str | OoxmlDeclaration | Any,
    mime_type: str | None = None,
    *,
    limits: OoxmlLimits | None = None,
    clock: Callable[[], float] | None = None,
) -> OoxmlPackage:
    """Validate one OOXML package and return immutable bounded part access."""

    effective_limits = limits or OoxmlLimits()
    effective_clock = clock or time.monotonic
    budget = _Budget.start(effective_limits, effective_clock)
    declaration = detect_ooxml_type(filename, mime_type)
    budget.check_time("declaration")

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("OOXML package data must be bytes-like")
    package_size = len(data)
    if package_size > effective_limits.max_package_bytes:
        _raise_limit(
            "package_bytes",
            effective_limits.max_package_bytes,
            package_size,
            stage="signature",
        )
    payload = bytes(data)
    if not payload:
        raise OoxmlSignatureError(
            "empty_package",
            "The uploaded OOXML package is empty.",
            stage="signature",
        )
    if payload.startswith(_OLE_COMPOUND_SIGNATURE):
        raise OoxmlSecurityError(
            "encrypted_package_denied",
            "Encrypted or legacy compound Office packages are not supported.",
            stage="signature",
        )
    if not payload.startswith(_ZIP_SIGNATURES):
        raise OoxmlSignatureError(
            "signature_mismatch",
            "The uploaded OOXML file does not have a ZIP package signature.",
            stage="signature",
        )

    (
        parts,
        infos,
        entry_count,
        compressed_total,
        uncompressed_total,
    ) = _zip_parts(payload, limits=effective_limits, budget=budget)
    part_names = frozenset(parts)
    if "[Content_Types].xml" not in part_names:
        raise OoxmlXmlError(
            "content_types_missing",
            "The OOXML package has no content-types part.",
            stage="content_types",
        )
    if "_rels/.rels" not in part_names:
        raise OoxmlRelationshipError(
            "root_relationships_missing",
            "The OOXML package has no root relationships part.",
            stage="relationships",
        )

    content_types_root = _safe_xml(
        parts["[Content_Types].xml"],
        part_name="[Content_Types].xml",
        budget=budget,
    )
    defaults, overrides = _parse_content_types(
        content_types_root,
        part_names=part_names,
        limits=effective_limits,
    )
    # Name-based encrypted/macro markers are denied before content-type
    # resolution so a hostile package cannot obscure active content merely by
    # omitting its declaration.
    _validate_active_content(part_names, {})
    content_types = _resolve_content_types(part_names, defaults, overrides)
    _validate_active_content(part_names, content_types)

    xml_roots: dict[str, ElementTree.Element] = {
        "[Content_Types].xml": content_types_root
    }
    for part_name in sorted(part_names - {"[Content_Types].xml"}):
        if _is_xml_part(part_name, content_types[part_name]):
            xml_roots[part_name] = _safe_xml(
                parts[part_name],
                part_name=part_name,
                budget=budget,
            )

    relationships = _parse_relationships(
        xml_roots,
        part_names=part_names,
        content_types=content_types,
        budget=budget,
    )
    main_part, actual_family = _main_part_and_family(
        relationships,
        content_types,
    )
    if actual_family is not declaration.family:
        raise OoxmlDeclarationError(
            "family_mismatch",
            "The OOXML package family differs from its extension and MIME type.",
            stage="package_family",
            details={
                "declared_family": declaration.family.value,
                "detected_family": actual_family.value,
            },
        )
    if main_part not in xml_roots:
        raise OoxmlXmlError(
            "main_part_not_xml",
            "The root Office document part is not safe parsed XML.",
            stage="package_family",
            details={"main_part": main_part},
        )

    part_records = tuple(
        OoxmlPart(
            name=part_name,
            content_type=content_types[part_name],
            compressed_bytes=int(infos[part_name].compress_size),
            uncompressed_bytes=len(parts[part_name]),
            crc32=f"{infos[part_name].CRC:08x}",
            sha256=hashlib.sha256(parts[part_name]).hexdigest(),
            is_xml=part_name in xml_roots,
        )
        for part_name in sorted(parts)
    )
    manifest = OoxmlManifest(
        schema_version="ooxml-package-manifest-v1",
        family=declaration.family,
        extension=declaration.extension,
        mime_type=declaration.mime_type,
        package_sha256=hashlib.sha256(payload).hexdigest(),
        package_bytes=len(payload),
        entry_count=entry_count,
        compressed_bytes=compressed_total,
        uncompressed_bytes=uncompressed_total,
        xml_bytes=budget.xml_bytes,
        xml_nodes=budget.xml_nodes,
        main_part=main_part,
        parts=part_records,
        relationships=relationships,
        limits=effective_limits,
        security_policy=OoxmlSecurityPolicy(),
    )
    budget.check_time("manifest")
    return OoxmlPackage(manifest=manifest, _parts=parts)


def limits_from_settings(settings: Any) -> OoxmlLimits:
    """Project the default-off runtime settings into the intake contract."""

    return OoxmlLimits.from_settings(settings)


__all__ = [
    "DOCX_MIME_TYPE",
    "PPTX_MIME_TYPE",
    "XLSX_MIME_TYPE",
    "OoxmlDeclaration",
    "OoxmlDeclarationError",
    "OoxmlFamily",
    "OoxmlIntakeError",
    "OoxmlLimits",
    "OoxmlManifest",
    "OoxmlPackage",
    "OoxmlPart",
    "OoxmlPartNotFoundError",
    "OoxmlPathError",
    "OoxmlRelationship",
    "OoxmlRelationshipError",
    "OoxmlResourceLimitError",
    "OoxmlSecurityError",
    "OoxmlSignatureError",
    "OoxmlXmlError",
    "detect_ooxml_type",
    "intake_ooxml",
    "limits_from_settings",
]
