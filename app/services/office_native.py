"""Small, dependency-free helpers shared by the native OOXML adapters.

The Phase 07 intake service owns the production package boundary.  The
adapters intentionally use a tiny duck-typed view so they can consume that
service without depending on a concrete package class.  Raw bytes are also
accepted for focused tests and embedding applications; that compatibility
path applies conservative ZIP/XML limits and never executes package content.
"""

from __future__ import annotations

import hashlib
import io
import math
import posixpath
import re
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import escape
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


OOXML_MAX_PARTS = 4_096
OOXML_MAX_PART_BYTES = 16 * 1024 * 1024
OOXML_MAX_TOTAL_BYTES = 64 * 1024 * 1024
OOXML_MAX_COMPRESSION_RATIO = 200.0
OOXML_MAX_XML_BYTES = 8 * 1024 * 1024

_ID_CLEAN = re.compile(r"[^A-Za-z0-9_.:-]+")
_UNSAFE_XML_DECLARATION = re.compile(
    br"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)


class OfficeNativeError(ValueError):
    """A deterministic, content-safe native adapter refusal."""

    code = "office_native_invalid"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message or code or self.code)
        self.code = code or self.code
        self.details = dict(details or {})


class OfficeNativePackageError(OfficeNativeError):
    code = "office_package_invalid"


class OfficeNativeLimitError(OfficeNativeError):
    code = "office_native_limit"


class OfficeAdapterDisabledError(OfficeNativeError):
    code = "unsupported_document_type"


def _part_not_found(exc: BaseException) -> bool:
    if isinstance(exc, (KeyError, FileNotFoundError)):
        return True
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code.casefold() in {
        "part_not_found",
        "ooxml_part_not_found",
        "office_package_part_missing",
    }:
        return True
    return type(exc).__name__ in {
        "OoxmlPartNotFoundError",
        "OOXMLPartNotFoundError",
        "PartNotFoundError",
    }


def _safe_part_name(raw_name: str) -> str:
    if not isinstance(raw_name, str):
        raise OfficeNativePackageError(code="office_part_name_invalid")
    decoded = unquote(raw_name).replace("\\", "/")
    if "\x00" in decoded:
        raise OfficeNativePackageError(code="office_part_name_invalid")
    decoded = decoded.lstrip("/")
    path = PurePosixPath(decoded)
    if (
        not decoded
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise OfficeNativePackageError(code="office_part_path_unsafe")
    normalized = posixpath.normpath(decoded)
    if normalized == ".." or normalized.startswith("../"):
        raise OfficeNativePackageError(code="office_part_path_unsafe")
    return normalized


class _RawZipPackage:
    """Immutable bounded view used only when the intake object is unavailable."""

    def __init__(self, raw: bytes) -> None:
        self.source_sha256 = hashlib.sha256(raw).hexdigest()
        parts: dict[str, bytes] = {}
        total = 0
        try:
            with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
                infos = archive.infolist()
                if not infos or len(infos) > OOXML_MAX_PARTS:
                    raise OfficeNativeLimitError(
                        code="office_package_part_limit",
                        details={"max_parts": OOXML_MAX_PARTS},
                    )
                for info in infos:
                    if info.is_dir():
                        continue
                    name = _safe_part_name(info.filename)
                    if name in parts:
                        raise OfficeNativePackageError(
                            code="office_package_duplicate_part"
                        )
                    if info.flag_bits & 0x1:
                        raise OfficeNativePackageError(
                            code="office_package_encrypted_part"
                        )
                    if info.file_size > OOXML_MAX_PART_BYTES:
                        raise OfficeNativeLimitError(
                            code="office_package_part_size_limit",
                            details={"max_part_bytes": OOXML_MAX_PART_BYTES},
                        )
                    total += info.file_size
                    if total > OOXML_MAX_TOTAL_BYTES:
                        raise OfficeNativeLimitError(
                            code="office_package_total_size_limit",
                            details={"max_total_bytes": OOXML_MAX_TOTAL_BYTES},
                        )
                    if info.file_size and info.compress_size == 0:
                        raise OfficeNativeLimitError(
                            code="office_package_compression_ratio_limit"
                        )
                    ratio = info.file_size / max(info.compress_size, 1)
                    if ratio > OOXML_MAX_COMPRESSION_RATIO:
                        raise OfficeNativeLimitError(
                            code="office_package_compression_ratio_limit",
                            details={
                                "max_compression_ratio": OOXML_MAX_COMPRESSION_RATIO
                            },
                        )
                    data = archive.read(info)
                    if len(data) != info.file_size:
                        raise OfficeNativePackageError(
                            code="office_package_part_size_mismatch"
                        )
                    parts[name] = data
        except OfficeNativeError:
            raise
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
            raise OfficeNativePackageError(
                code="office_package_zip_invalid",
                details={"reason": type(exc).__name__},
            ) from exc
        self._parts = parts
        self.part_names = tuple(sorted(parts))

    def read_part(self, name: str) -> bytes:
        return self._parts[_safe_part_name(name)]


class OfficePackageView:
    """Normalize raw bytes, mappings, or a bounded intake package."""

    def __init__(self, package: Any) -> None:
        if isinstance(package, (bytes, bytearray, memoryview)):
            package = _RawZipPackage(bytes(package))
        self._package = package
        if not (
            isinstance(package, Mapping)
            or callable(getattr(package, "read_part", None))
            or isinstance(getattr(package, "parts", None), Mapping)
        ):
            raise TypeError("OOXML package must expose read_part or a part mapping")

    @property
    def source_sha256(self) -> str | None:
        for name in ("source_sha256", "sha256", "digest"):
            raw = getattr(self._package, name, None)
            raw = raw() if callable(raw) else raw
            if isinstance(raw, str):
                value = raw.strip().casefold()
                if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
                    return value
        return None

    @property
    def main_part(self) -> str | None:
        """Return the intake-validated OOXML main part when available."""

        manifest = getattr(self._package, "manifest", None)
        manifest = manifest() if callable(manifest) else manifest
        if isinstance(manifest, Mapping):
            raw = manifest.get("main_part")
        else:
            raw = getattr(manifest, "main_part", None)
        if not isinstance(raw, str) or not raw.strip():
            return None
        return _safe_part_name(raw)

    @property
    def part_names(self) -> tuple[str, ...]:
        """Return normalized manifest names when the intake exposes them."""

        package = self._package
        candidates: Any = getattr(package, "part_names", None)
        candidates = candidates() if callable(candidates) else candidates
        if candidates is None:
            listing = getattr(package, "list_parts", None)
            candidates = listing() if callable(listing) else None
        if candidates is None:
            parts = package if isinstance(package, Mapping) else getattr(package, "parts", None)
            if isinstance(parts, Mapping):
                candidates = parts.keys()
        if candidates is None:
            manifest = getattr(package, "manifest", None)
            manifest = manifest() if callable(manifest) else manifest
            if isinstance(manifest, Mapping):
                candidates = manifest.keys()
            elif manifest is not None:
                candidates = getattr(manifest, "parts", manifest)
        if candidates is None:
            return ()
        names: list[str] = []
        try:
            iterator = iter(candidates)
        except TypeError:
            return ()
        for entry in iterator:
            if isinstance(entry, str):
                raw_name = entry
            else:
                raw_name = next(
                    (
                        value
                        for value in (
                            getattr(entry, "name", None),
                            getattr(entry, "part_name", None),
                            getattr(entry, "path", None),
                        )
                        if isinstance(value, str)
                    ),
                    None,
                )
            if raw_name is not None:
                names.append(_safe_part_name(raw_name))
        return tuple(sorted(dict.fromkeys(names)))

    def read_part(self, name: str, *, required: bool = True) -> bytes | None:
        safe_name = _safe_part_name(name)
        package = self._package
        try:
            if isinstance(package, Mapping):
                value = package[safe_name]
            elif isinstance(getattr(package, "parts", None), Mapping):
                value = package.parts[safe_name]
            else:
                reader = package.read_part
                try:
                    value = reader(safe_name)
                except Exception as exc:
                    if not _part_not_found(exc):
                        raise
                    # Some lightweight package doubles expose OPC names with
                    # a leading slash, while the production intake correctly
                    # rejects absolute paths.  Retry only for that narrow
                    # compatibility case; if the alternate spelling is also
                    # missing or explicitly refused as absolute, surface the
                    # original not-found result to the common required/
                    # optional handling below.
                    try:
                        value = reader(f"/{safe_name}")
                    except Exception as alternate_exc:
                        if _part_not_found(alternate_exc) or getattr(
                            alternate_exc, "code", None
                        ) == "part_path_absolute":
                            raise exc
                        raise
        except Exception as exc:
            if not _part_not_found(exc):
                raise
            if required:
                raise OfficeNativePackageError(
                    code="office_package_part_missing",
                    details={"part": safe_name},
                ) from None
            return None
        if value is None:
            if required:
                raise OfficeNativePackageError(
                    code="office_package_part_missing",
                    details={"part": safe_name},
                )
            return None
        if hasattr(value, "data"):
            value = value.data
        if isinstance(value, memoryview):
            value = value.tobytes()
        elif isinstance(value, bytearray):
            value = bytes(value)
        if not isinstance(value, bytes):
            raise OfficeNativePackageError(
                code="office_package_part_type_invalid",
                details={"part": safe_name},
            )
        if len(value) > OOXML_MAX_PART_BYTES:
            raise OfficeNativeLimitError(
                code="office_package_part_size_limit",
                details={"part": safe_name, "max_part_bytes": OOXML_MAX_PART_BYTES},
            )
        return value

    def digest(self, seed_parts: Iterable[str]) -> str:
        known = self.source_sha256
        if known is not None:
            return known
        digest = hashlib.sha256()
        found = False
        for part in sorted(dict.fromkeys(seed_parts)):
            data = self.read_part(part, required=False)
            if data is None:
                continue
            found = True
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
        if not found:
            raise OfficeNativePackageError(code="office_package_empty")
        return digest.hexdigest()


def coerce_package(source: Any) -> OfficePackageView:
    if isinstance(source, OfficePackageView):
        return source
    return OfficePackageView(source)


def parse_xml(data: bytes, *, part: str) -> ET.Element:
    if len(data) > OOXML_MAX_XML_BYTES:
        raise OfficeNativeLimitError(
            code="office_xml_size_limit",
            details={"part": part, "max_xml_bytes": OOXML_MAX_XML_BYTES},
        )
    # The bytes are already bounded above, so scan the entire XML part.  A
    # declaration placed after a long legal prefix must not reach an XML
    # implementation that could expand it.
    if _UNSAFE_XML_DECLARATION.search(data) is not None:
        raise OfficeNativePackageError(
            code="office_xml_dtd_forbidden",
            details={"part": part},
        )
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise OfficeNativePackageError(
            code="office_xml_malformed",
            details={"part": part},
        ) from exc


def read_xml(
    package: OfficePackageView,
    part: str,
    *,
    required: bool = True,
) -> ET.Element | None:
    data = package.read_part(part, required=required)
    if data is None:
        return None
    return parse_xml(data, part=part)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def attr(element: ET.Element, name: str, default: str | None = None) -> str | None:
    if name in element.attrib:
        return element.attrib[name]
    for key, value in element.attrib.items():
        if local_name(key) == name:
            return value
    return default


def children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if local_name(child.tag) == name]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next(
        (candidate for candidate in list(element) if local_name(candidate.tag) == name),
        None,
    )


def descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [candidate for candidate in element.iter() if local_name(candidate.tag) == name]


def relationship_part(source_part: str) -> str:
    source = PurePosixPath(_safe_part_name(source_part))
    return str(source.parent / "_rels" / f"{source.name}.rels")


@dataclass(frozen=True, slots=True)
class OfficeRelationship:
    relationship_id: str
    relationship_type: str
    target: str
    target_mode: str
    source_part: str
    resolved_target: str | None

    @property
    def external(self) -> bool:
        return self.target_mode.casefold() == "external"


def resolve_relationship_target(source_part: str, target: str) -> str:
    decoded = unquote(target).replace("\\", "/")
    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or "\x00" in decoded:
        raise OfficeNativePackageError(code="office_relationship_target_unsafe")
    if decoded.startswith("/"):
        candidate = decoded.lstrip("/")
    else:
        candidate = posixpath.join(posixpath.dirname(source_part), decoded)
    return _safe_part_name(posixpath.normpath(candidate))


def read_relationships(
    package: OfficePackageView,
    source_part: str,
) -> dict[str, OfficeRelationship]:
    rel_part = relationship_part(source_part)
    root = read_xml(package, rel_part, required=False)
    if root is None:
        return {}
    relationships: dict[str, OfficeRelationship] = {}
    for node in descendants(root, "Relationship"):
        relationship_id = (attr(node, "Id") or "").strip()
        relationship_type = (attr(node, "Type") or "").strip()
        target = (attr(node, "Target") or "").strip()
        target_mode = (attr(node, "TargetMode") or "Internal").strip()
        if not relationship_id or not relationship_type or not target:
            raise OfficeNativePackageError(
                code="office_relationship_malformed",
                details={"part": rel_part},
            )
        if relationship_id in relationships:
            raise OfficeNativePackageError(
                code="office_relationship_duplicate",
                details={"part": rel_part},
            )
        resolved = None
        if target_mode.casefold() != "external":
            resolved = resolve_relationship_target(source_part, target)
        relationships[relationship_id] = OfficeRelationship(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            target=target,
            target_mode=target_mode,
            source_part=_safe_part_name(source_part),
            resolved_target=resolved,
        )
    return relationships


def relationship_by_type(
    relationships: Mapping[str, OfficeRelationship],
    suffix: str,
) -> list[OfficeRelationship]:
    suffix = suffix.casefold()
    return [
        relationship
        for relationship in relationships.values()
        if relationship.relationship_type.casefold().endswith(suffix)
    ]


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def finite_number(value: str | None, *, default: float = 0.0) -> float:
    try:
        result = float(value) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise OfficeNativePackageError(code="office_numeric_value_invalid") from exc
    if not math.isfinite(result):
        raise OfficeNativePackageError(code="office_numeric_value_invalid")
    return result


def normalized_text(values: Iterable[str]) -> str:
    text = "".join(values)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def html_table(rows: list[list[Any]]) -> str:
    body: list[str] = ["<table>"]
    for row in rows:
        body.append("<tr>")
        for value in row:
            body.append(f"<td>{escape('' if value is None else str(value))}</td>")
        body.append("</tr>")
    body.append("</table>")
    return "".join(body)


def markdown_table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [["" if value is None else str(value) for value in row] for row in rows]
    for row in padded:
        row.extend([""] * (width - len(row)))

    def safe(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    lines = ["| " + " | ".join(safe(value) for value in padded[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend(
        "| " + " | ".join(safe(value) for value in row) + " |"
        for row in padded[1:]
    )
    return "\n".join(lines)


def native_provenance(
    *,
    part: str,
    xml_path: str,
    coordinate_state: str,
    relationship: OfficeRelationship | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "method": "native_xml",
        "part": _safe_part_name(part),
        "xml_path": xml_path,
        "coordinate_state": coordinate_state,
    }
    if relationship is not None:
        result["relationship_id"] = relationship.relationship_id
        result["relationship_type"] = relationship.relationship_type
        result["relationship_target"] = relationship.target
        result["relationship_external"] = relationship.external
        if relationship.resolved_target is not None:
            result["resolved_part"] = relationship.resolved_target
    if extra:
        result.update(extra)
    return result


class StableIdFactory:
    def __init__(self, prefix: str) -> None:
        self.prefix = _ID_CLEAN.sub("-", prefix).strip("-") or "office"
        self._counts: dict[str, int] = {}

    def next(self, kind: str) -> str:
        clean = _ID_CLEAN.sub("-", kind).strip("-") or "item"
        count = self._counts.get(clean, 0) + 1
        self._counts[clean] = count
        return f"{self.prefix}-{clean}-{count}"


def content_item(
    ids: StableIdFactory,
    kind: str,
    reading_order: int,
    *,
    value: Any = None,
    markdown: str | None = None,
    provenance: Mapping[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": ids.next(kind),
        "type": kind,
        "reading_order": reading_order,
        "source": "native",
        "native_provenance": dict(provenance),
    }
    if value is not None:
        item["value"] = value
    if markdown is not None:
        item["md"] = markdown
    item.update(extra)
    return item


def logical_page(
    *,
    page_index: int,
    label: str,
    items: list[dict[str, Any]],
    coordinate_state: str,
    warnings: Iterable[str] = (),
    width: float | None = None,
    height: float | None = None,
    unit: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    has_extents = width is not None and height is not None
    coordinate_unit = unit or ("pt" if has_extents else "logical")
    physical = has_extents and coordinate_unit != "logical"
    page: dict[str, Any] = {
        "page_index": page_index,
        "page_number": label,
        "page_label": label,
        "page_width": float(width if has_extents else 1.0),
        "page_height": float(height if has_extents else 1.0),
        "unit": coordinate_unit,
        "success": True,
        "items": items,
        "warnings": list(dict.fromkeys(warnings)),
        "coordinate_state": coordinate_state,
        "geometry_available": physical,
    }
    if extra:
        page.update(extra)
    return page


def build_parse_result(
    *,
    filename: str,
    mime_type: str,
    source_format: str,
    source_sha256: str,
    pages: list[dict[str, Any]],
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": filename,
            "mime_type": mime_type,
            "sha256": source_sha256,
            "page_count": len(pages),
            "source_format": source_format,
            "native_evidence": True,
            "content_execution": "disabled",
        },
        "pages": pages,
        "processing": {
            "engine": "ooxml-native",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 0,
            "local_processing": True,
            "input_format": source_format.casefold(),
            "native_only": True,
            "formulas_executed": False,
            "macros_executed": False,
            "external_content_fetched": False,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def office_adapter_manifest(
    *,
    adapter_id: str,
    input_kind: str,
    extension: str,
    mime_type: str,
    coordinate_unit: str,
    optional_capabilities: Iterable[str],
    settings: Any | None = None,
) -> Any:
    """Build the shared immutable P07-US01 manifest for an Office adapter."""

    from app.services.adapter_contracts import (
        AdapterCapabilities,
        AdapterCoordinateTransform,
        AdapterFallbackPolicy,
        AdapterManifest,
        AdapterResourceLimits,
        AdapterSerializationCapabilities,
        AdapterSignature,
        AdapterSignatureFragment,
    )

    return AdapterManifest(
        adapter_id=adapter_id,
        adapter_version="1.0.0",
        input_kind=input_kind,
        extensions=[extension],
        mime_types=[mime_type],
        allow_missing_mime=False,
        signatures=[
            AdapterSignature(
                id=f"{input_kind}-zip-header",
                extensions=[extension],
                fragments=[
                    AdapterSignatureFragment(
                        offset=0,
                        prefix_hex=b"PK\x03\x04".hex(),
                    )
                ],
            )
        ],
        capabilities=AdapterCapabilities(
            source_identity=True,
            physical_page_index=True,
            printed_page_label=True,
            provenance=True,
            relationships=True,
            visibility=True,
            concerns=True,
            coordinate_units=[coordinate_unit],
            content_origins=["native", "native_embedded"],
            evidence_methods=["embedded", "native"],
            relationship_types=["contains", "reading_before", "references"],
            optional_capabilities=sorted(dict.fromkeys(optional_capabilities)),
            visibility_policy="source_declared_visibility",
        ),
        coordinate_transforms=[
            AdapterCoordinateTransform(
                id=f"{input_kind}-{coordinate_unit}-identity",
                source_unit=coordinate_unit,
                target_unit=coordinate_unit,
                matrix=[1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            )
        ],
        limits=AdapterResourceLimits(
            max_input_bytes=int(
                getattr(settings, "max_upload_bytes", 20 * 1024 * 1024)
            ),
            max_pages=int(getattr(settings, "max_pages", 100)),
            max_regions=100_000,
            max_relationships=int(
                getattr(settings, "adapters_ooxml_max_relationships", 65_536)
            ),
            timeout_seconds=float(
                getattr(settings, "document_timeout_seconds", 300.0)
            ),
        ),
        fallback=AdapterFallbackPolicy(
            safe_failure_mode="typed_error",
            flag_off_behavior="unsupported",
            network_access="forbidden",
        ),
        serialization=AdapterSerializationCapabilities(
            canonical_json=True,
            canonical_markdown=True,
            canonical_text=True,
            legacy_projection=True,
        ),
    )


__all__ = [
    "OfficeAdapterDisabledError",
    "OfficeNativeError",
    "OfficeNativeLimitError",
    "OfficeNativePackageError",
    "OfficePackageView",
    "OfficeRelationship",
    "StableIdFactory",
    "attr",
    "build_parse_result",
    "child",
    "children",
    "coerce_package",
    "content_item",
    "descendants",
    "finite_number",
    "html_table",
    "local_name",
    "logical_page",
    "markdown_table",
    "native_provenance",
    "normalized_text",
    "office_adapter_manifest",
    "parse_bool",
    "parse_xml",
    "read_relationships",
    "read_xml",
    "relationship_by_type",
    "resolve_relationship_target",
]
