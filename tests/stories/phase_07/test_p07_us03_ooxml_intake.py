"""Focused release-first checks for bounded, non-executing OOXML intake."""

from __future__ import annotations

import io
import socket
import stat
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any
from xml.sax.saxutils import quoteattr

import pytest

from app.config import Settings
from app.services.ooxml_intake import (
    DOCX_MIME_TYPE,
    PPTX_MIME_TYPE,
    XLSX_MIME_TYPE,
    OoxmlDeclarationError,
    OoxmlFamily,
    OoxmlLimits,
    OoxmlPartNotFoundError,
    OoxmlPathError,
    OoxmlRelationshipError,
    OoxmlResourceLimitError,
    OoxmlSecurityError,
    OoxmlSignatureError,
    OoxmlXmlError,
    detect_ooxml_type,
    intake_ooxml,
)


_CONTENT_TYPES_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
_RELATIONSHIPS_NAMESPACE = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_OFFICE_DOCUMENT_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "officeDocument"
)
_HYPERLINK_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "hyperlink"
)
_IMAGE_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)

_FAMILY_SPEC: dict[OoxmlFamily, dict[str, Any]] = {
    OoxmlFamily.DOCX: {
        "filename": "minimal.docx",
        "mime_type": DOCX_MIME_TYPE,
        "main_part": "word/document.xml",
        "main_content_type": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document.main+xml"
        ),
        "main_xml": (
            b'<w:document xmlns:w="urn:test-word"><w:body><w:p/>'
            b"</w:body></w:document>"
        ),
    },
    OoxmlFamily.PPTX: {
        "filename": "minimal.pptx",
        "mime_type": PPTX_MIME_TYPE,
        "main_part": "ppt/presentation.xml",
        "main_content_type": (
            "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation.main+xml"
        ),
        "main_xml": (
            b'<p:presentation xmlns:p="urn:test-presentation">'
            b"<p:sldIdLst/></p:presentation>"
        ),
    },
    OoxmlFamily.XLSX: {
        "filename": "minimal.xlsx",
        "mime_type": XLSX_MIME_TYPE,
        "main_part": "xl/workbook.xml",
        "main_content_type": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet.main+xml"
        ),
        # The expression remains inert source bytes. Intake has no formula
        # evaluator and the manifest explicitly records non-execution policy.
        "main_xml": (
            b'<workbook xmlns="urn:test-spreadsheet"><definedNames>'
            b'<definedName name="fixture">1+1</definedName>'
            b"</definedNames></workbook>"
        ),
    },
}

RelationshipSpec = tuple[str, str, str, str | None]


def _content_types(
    main_part: str,
    main_content_type: str,
    *,
    defaults: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> bytes:
    default_values = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
        **dict(defaults or {}),
    }
    override_values = {main_part: main_content_type, **dict(overrides or {})}
    members = [
        (
            f"<Default Extension={quoteattr(extension)} "
            f"ContentType={quoteattr(content_type)}/>"
        )
        for extension, content_type in sorted(default_values.items())
    ]
    members.extend(
        (
            f"<Override PartName={quoteattr('/' + part_name)} "
            f"ContentType={quoteattr(content_type)}/>"
        )
        for part_name, content_type in sorted(override_values.items())
    )
    return (
        f'<Types xmlns="{_CONTENT_TYPES_NAMESPACE}">'
        + "".join(members)
        + "</Types>"
    ).encode()


def _relationships(records: Sequence[RelationshipSpec]) -> bytes:
    members: list[str] = []
    for relationship_id, relationship_type, target, target_mode in records:
        mode = (
            ""
            if target_mode is None
            else f" TargetMode={quoteattr(target_mode)}"
        )
        members.append(
            f"<Relationship Id={quoteattr(relationship_id)} "
            f"Type={quoteattr(relationship_type)} "
            f"Target={quoteattr(target)}{mode}/>"
        )
    return (
        f'<Relationships xmlns="{_RELATIONSHIPS_NAMESPACE}">'
        + "".join(members)
        + "</Relationships>"
    ).encode()


def _package_entries(
    family: OoxmlFamily,
    *,
    main_xml: bytes | None = None,
    main_content_type: str | None = None,
    root_extra: Sequence[RelationshipSpec] = (),
    relationship_parts: Mapping[str, Sequence[RelationshipSpec]] | None = None,
    extra_parts: Mapping[str, bytes] | None = None,
    defaults: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
    content_types_xml: bytes | None = None,
    omit: frozenset[str] = frozenset(),
) -> dict[str, bytes]:
    spec = _FAMILY_SPEC[family]
    main_part = str(spec["main_part"])
    selected_main_type = main_content_type or str(spec["main_content_type"])
    root_records: tuple[RelationshipSpec, ...] = (
        (
            "rIdOfficeDocument",
            _OFFICE_DOCUMENT_RELATIONSHIP,
            main_part,
            None,
        ),
        *root_extra,
    )
    entries: dict[str, bytes] = {
        "_rels/.rels": _relationships(root_records),
        main_part: main_xml if main_xml is not None else bytes(spec["main_xml"]),
        **dict(extra_parts or {}),
    }
    for name, records in dict(relationship_parts or {}).items():
        entries[name] = _relationships(records)
    entries["[Content_Types].xml"] = content_types_xml or _content_types(
        main_part,
        selected_main_type,
        defaults=defaults,
        overrides=overrides,
    )
    return {name: value for name, value in entries.items() if name not in omit}


def _zip_entries(
    entries: Sequence[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    special_modes: Mapping[str, int] | None = None,
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for name, value in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 8, 12, 0, 0, 0))
            info.compress_type = compression
            mode = dict(special_modes or {}).get(name, 0o600)
            info.external_attr = mode << 16
            archive.writestr(info, value)
    return output.getvalue()


def _package(
    family: OoxmlFamily = OoxmlFamily.DOCX,
    **kwargs: Any,
) -> bytes:
    return _zip_entries(tuple(_package_entries(family, **kwargs).items()))


def _intake(data: bytes, family: OoxmlFamily = OoxmlFamily.DOCX, **kwargs: Any):
    spec = _FAMILY_SPEC[family]
    return intake_ooxml(
        data,
        str(spec["filename"]),
        str(spec["mime_type"]),
        **kwargs,
    )


@pytest.mark.parametrize("family", tuple(OoxmlFamily))
def test_minimal_office_packages_have_deterministic_immutable_manifests(
    family: OoxmlFamily,
) -> None:
    data = _package(family)

    first = _intake(data, family)
    second = _intake(data, family)
    spec = _FAMILY_SPEC[family]

    assert first.manifest.to_dict() == second.manifest.to_dict()
    assert first.manifest.schema_version == "ooxml-package-manifest-v1"
    assert first.manifest.family is family
    assert first.manifest.main_part == spec["main_part"]
    assert first.manifest.mime_type == spec["mime_type"]
    assert first.manifest.entry_count == 3
    assert first.part_names == tuple(sorted(first.part_names))
    assert len(first.manifest.parts) == 3
    assert len(first.manifest.relationships) == 1
    assert first.manifest.relationships[0].source_part is None
    assert first.manifest.relationships[0].resolved_part == spec["main_part"]
    assert first.read_part(str(spec["main_part"])) == spec["main_xml"]
    assert first.has_part(str(spec["main_part"])) is True
    assert first.manifest.security_policy.to_dict() == {
        "external_relationships": "deny",
        "macros": "deny",
        "encryption": "deny",
        "network_access": "prohibited",
        "active_content_execution": "prohibited",
        "formula_and_field_execution": "prohibited",
        "package_storage": "memory_only_read_only",
    }
    with pytest.raises(FrozenInstanceError):
        first.manifest.main_part = "changed.xml"  # type: ignore[misc]
    with pytest.raises(TypeError):
        first._parts[str(spec["main_part"])] = b"changed"  # type: ignore[index]


def test_manifest_records_are_sorted_independently_of_zip_entry_order() -> None:
    entries = tuple(_package_entries(OoxmlFamily.DOCX).items())
    forward = _intake(_zip_entries(entries))
    reverse = _intake(_zip_entries(tuple(reversed(entries))))

    assert forward.manifest.package_sha256 != reverse.manifest.package_sha256
    assert forward.manifest.parts == reverse.manifest.parts
    assert forward.manifest.relationships == reverse.manifest.relationships
    assert forward.part_names == reverse.part_names


def test_read_only_part_access_has_bounded_and_missing_part_failures() -> None:
    package = _intake(_package())
    main = package.read_part("word/document.xml")

    with pytest.raises(OoxmlResourceLimitError) as oversized:
        package.read_part("word/document.xml", max_bytes=len(main) - 1)
    assert oversized.value.code == "part_read_bytes_limit"
    assert oversized.value.stage == "part_access"

    with pytest.raises(OoxmlPartNotFoundError) as missing:
        package.read_part("word/missing.xml")
    assert missing.value.code == "part_not_found"

    with pytest.raises(OoxmlPathError) as traversal:
        package.read_part("../outside.xml")
    assert traversal.value.code == "part_path_traversal"


def test_declarations_require_matching_extension_mime_and_package_family() -> None:
    declaration = detect_ooxml_type("UPPER.DOCX", f"{DOCX_MIME_TYPE}; charset=binary")
    assert declaration.family is OoxmlFamily.DOCX

    with pytest.raises(OoxmlDeclarationError) as wrong_mime:
        detect_ooxml_type("sample.docx", "application/zip")
    assert wrong_mime.value.code == "mime_mismatch"

    with pytest.raises(OoxmlDeclarationError) as unsupported:
        detect_ooxml_type("sample.doc", "application/msword")
    assert unsupported.value.code == "unsupported_extension"

    docx_data = _package(OoxmlFamily.DOCX)
    with pytest.raises(OoxmlDeclarationError) as wrong_family:
        _intake(docx_data, OoxmlFamily.PPTX)
    assert wrong_family.value.code == "family_mismatch"


def test_declared_input_objects_and_shared_settings_projection_are_supported() -> None:
    declared = SimpleNamespace(
        kind=SimpleNamespace(value="docx"),
        extension=".docx",
        mime_type=DOCX_MIME_TYPE,
    )
    settings = SimpleNamespace(
        max_upload_bytes=4_000,
        adapters_ooxml_max_entries=12,
        adapters_ooxml_max_compressed_bytes=3_000,
        adapters_ooxml_max_uncompressed_bytes=8_000,
        adapters_ooxml_max_part_bytes=2_000,
        adapters_ooxml_max_xml_nodes=100,
        adapters_ooxml_max_xml_depth=10,
        adapters_ooxml_max_relationships=20,
        adapters_ooxml_timeout_seconds=1.5,
    )
    limits = OoxmlLimits.from_settings(settings)

    package = intake_ooxml(_package(), declared, limits=limits)

    assert package.manifest.family is OoxmlFamily.DOCX
    assert package.source_sha256 == package.manifest.package_sha256
    assert package.list_parts() == package.part_names
    assert limits.max_package_bytes == 4_000
    assert limits.max_xml_bytes == 8_000
    assert limits.timeout_seconds == 1.5


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty_package"),
        (b"not a zip", "signature_mismatch"),
        (b"PK\x03\x04truncated", "invalid_zip"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"encrypted", "encrypted_package_denied"),
    ],
)
def test_invalid_truncated_and_compound_inputs_fail_before_xml(
    data: bytes,
    code: str,
) -> None:
    error_type = OoxmlSecurityError if "encrypted" in code else OoxmlSignatureError
    with pytest.raises(error_type) as caught:
        _intake(data)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("bad_name", "code"),
    [
        ("../outside.xml", "part_path_traversal"),
        ("/absolute.xml", "part_path_absolute"),
        ("word\\outside.xml", "part_path_backslash"),
        ("word/%2foutside.xml", "part_path_encoded_separator"),
    ],
)
def test_zip_part_paths_are_canonical_and_contained(
    bad_name: str,
    code: str,
) -> None:
    entries = list(_package_entries(OoxmlFamily.DOCX).items())
    entries.append((bad_name, b"<unsafe/>"))

    with pytest.raises(OoxmlPathError) as caught:
        _intake(_zip_entries(tuple(entries)))
    assert caught.value.code == code
    assert caught.value.stage == "zip_directory"


def test_unicode_and_percent_decoding_cannot_create_duplicate_parts() -> None:
    entries = list(_package_entries(OoxmlFamily.DOCX).items())
    entries.extend(
        [
            ("word/a%20b.xml", b"<first/>"),
            ("word/a b.xml", b"<second/>"),
        ]
    )

    with pytest.raises(OoxmlPathError) as caught:
        _intake(_zip_entries(tuple(entries)))
    assert caught.value.code == "duplicate_part"


def test_symlink_and_unsupported_compression_entries_are_denied() -> None:
    entries = list(_package_entries(OoxmlFamily.DOCX).items())
    entries.append(("word/link.xml", b"target"))
    symlink_mode = stat.S_IFLNK | 0o777
    with pytest.raises(OoxmlSecurityError) as special:
        _intake(
            _zip_entries(
                tuple(entries),
                special_modes={"word/link.xml": symlink_mode},
            )
        )
    assert special.value.code == "special_zip_entry_denied"

    with pytest.raises(OoxmlSecurityError) as compression:
        _intake(
            _zip_entries(
                tuple(_package_entries(OoxmlFamily.DOCX).items()),
                compression=zipfile.ZIP_BZIP2,
            )
        )
    assert compression.value.code == "compression_method_denied"


def test_duplicate_content_types_and_missing_required_parts_fail_closed() -> None:
    base = _package_entries(OoxmlFamily.DOCX)
    duplicate_defaults = (
        f'<Types xmlns="{_CONTENT_TYPES_NAMESPACE}">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="XML" ContentType="application/xml"/>'
        "</Types>"
    ).encode()
    duplicate = _package(
        content_types_xml=duplicate_defaults,
    )
    with pytest.raises(OoxmlXmlError) as duplicated:
        _intake(duplicate)
    assert duplicated.value.code == "content_type_declaration_duplicate"

    without_types = _zip_entries(
        tuple(
            (name, value)
            for name, value in base.items()
            if name != "[Content_Types].xml"
        )
    )
    with pytest.raises(OoxmlXmlError) as missing_types:
        _intake(without_types)
    assert missing_types.value.code == "content_types_missing"

    without_relationships = _package(omit=frozenset({"_rels/.rels"}))
    with pytest.raises(OoxmlRelationshipError) as missing_relationships:
        _intake(without_relationships)
    assert missing_relationships.value.code == "root_relationships_missing"


@pytest.mark.parametrize(
    "unsafe_xml",
    [
        (
            b'<?xml version="1.0"?><!DOCTYPE w:document '
            b'[<!ENTITY leak SYSTEM "file:///etc/passwd">]>'
            b'<w:document xmlns:w="urn:test">&leak;</w:document>'
        ),
        b'<w:document xmlns:w="urn:test"><w:body></w:document>',
    ],
)
def test_dtd_entities_and_malformed_xml_are_rejected(unsafe_xml: bytes) -> None:
    with pytest.raises(OoxmlXmlError) as caught:
        _intake(_package(main_xml=unsafe_xml))
    assert caught.value.code in {"unsafe_xml_declaration", "xml_malformed"}


def test_external_relationship_is_denied_without_network_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls: list[tuple[Any, ...]] = []

    def unexpected_network(*args: Any, **_kwargs: Any) -> None:
        network_calls.append(args)
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "create_connection", unexpected_network)
    data = _package(
        relationship_parts={
            "word/_rels/document.xml.rels": (
                (
                    "rIdExternal",
                    _HYPERLINK_RELATIONSHIP,
                    "https://example.invalid/private",
                    "External",
                ),
            )
        }
    )

    with pytest.raises(OoxmlSecurityError) as caught:
        _intake(data)
    assert caught.value.code == "external_relationship_denied"
    assert network_calls == []


def test_internal_relationships_resolve_relative_paths_without_escape() -> None:
    data = _package(
        OoxmlFamily.PPTX,
        relationship_parts={
            "ppt/slides/_rels/slide1.xml.rels": (
                ("rIdImage", _IMAGE_RELATIONSHIP, "../media/image1.png", None),
            )
        },
        extra_parts={
            "ppt/slides/slide1.xml": b"<slide/>",
            "ppt/media/image1.png": b"not-decoded-by-intake",
        },
        defaults={"png": "image/png"},
    )
    package = _intake(data, OoxmlFamily.PPTX)

    image_relationship = next(
        relationship
        for relationship in package.manifest.relationships
        if relationship.relationship_id == "rIdImage"
    )
    assert image_relationship.source_part == "ppt/slides/slide1.xml"
    assert image_relationship.resolved_part == "ppt/media/image1.png"


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("missing.xml", "relationship_target_missing"),
        ("../../../outside.xml", "relationship_target_escape"),
        ("/absolute.xml", "relationship_target_absolute"),
    ],
)
def test_malformed_or_escaping_internal_relationships_fail(
    target: str,
    code: str,
) -> None:
    data = _package(
        relationship_parts={
            "word/_rels/document.xml.rels": (
                ("rIdBad", _IMAGE_RELATIONSHIP, target, None),
            )
        }
    )
    error_type = (
        OoxmlPathError
        if "escape" in code or "absolute" in code
        else OoxmlRelationshipError
    )
    with pytest.raises(error_type) as caught:
        _intake(data)
    assert caught.value.code == code


def test_duplicate_relationship_ids_are_rejected_per_source_part() -> None:
    data = _package(
        relationship_parts={
            "word/_rels/document.xml.rels": (
                ("rIdSame", _IMAGE_RELATIONSHIP, "media/a.png", None),
                ("rIdSame", _IMAGE_RELATIONSHIP, "media/b.png", None),
            )
        },
        extra_parts={
            "word/media/a.png": b"a",
            "word/media/b.png": b"b",
        },
        defaults={"png": "image/png"},
    )
    with pytest.raises(OoxmlRelationshipError) as caught:
        _intake(data)
    assert caught.value.code == "relationship_id_duplicate"


def test_macro_and_encrypted_content_is_denied_before_adapter_access() -> None:
    with pytest.raises(OoxmlSecurityError) as macro_extension:
        detect_ooxml_type(
            "active.docm",
            "application/vnd.ms-word.document.macroEnabled.12",
        )
    assert macro_extension.value.code == "macro_enabled_extension_denied"

    macro_part = _package(extra_parts={"word/vbaProject.bin": b"active"})
    with pytest.raises(OoxmlSecurityError) as macro_content:
        _intake(macro_part)
    assert macro_content.value.code == "macro_content_denied"

    encrypted_marker = _package(extra_parts={"EncryptionInfo": b"marker"})
    with pytest.raises(OoxmlSecurityError) as encrypted_content:
        _intake(encrypted_marker)
    assert encrypted_content.value.code == "encrypted_package_denied"


def test_zip_encryption_flag_is_denied_from_the_central_directory() -> None:
    raw = bytearray(_package())
    central = raw.find(b"PK\x01\x02")
    assert central >= 0
    flags = int.from_bytes(raw[central + 8 : central + 10], "little") | 0x1
    raw[central + 8 : central + 10] = flags.to_bytes(2, "little")

    with pytest.raises(OoxmlSecurityError) as caught:
        _intake(bytes(raw))
    assert caught.value.code == "encrypted_entry_denied"


def test_formula_text_remains_inert_and_byte_exact() -> None:
    data = _package(OoxmlFamily.XLSX)
    package = _intake(data, OoxmlFamily.XLSX)

    workbook_xml = package.read_part("xl/workbook.xml")
    assert b"1+1" in workbook_xml
    assert package.manifest.security_policy.formula_and_field_execution == (
        "prohibited"
    )


def test_every_byte_entry_part_xml_node_and_depth_limit_fails_at_boundary() -> None:
    data = _package()
    baseline = _intake(data).manifest
    maximum_part = max(part.uncompressed_bytes for part in baseline.parts)
    cases = (
        (
            replace(OoxmlLimits(), max_package_bytes=len(data) - 1),
            "package_bytes_limit",
        ),
        (replace(OoxmlLimits(), max_entries=2), "entries_limit"),
        (
            replace(
                OoxmlLimits(),
                max_compressed_bytes=baseline.compressed_bytes - 1,
            ),
            "compressed_bytes_limit",
        ),
        (
            replace(
                OoxmlLimits(),
                max_uncompressed_bytes=baseline.uncompressed_bytes - 1,
            ),
            "uncompressed_bytes_limit",
        ),
        (
            replace(OoxmlLimits(), max_part_bytes=maximum_part - 1),
            "part_bytes_limit",
        ),
        (
            replace(OoxmlLimits(), max_xml_bytes=baseline.xml_bytes - 1),
            "xml_bytes_limit",
        ),
        (
            replace(OoxmlLimits(), max_xml_nodes=baseline.xml_nodes - 1),
            "xml_nodes_limit",
        ),
        (replace(OoxmlLimits(), max_xml_depth=1), "xml_depth_limit"),
    )

    for limits, expected_code in cases:
        with pytest.raises(OoxmlResourceLimitError) as caught:
            _intake(data, limits=limits)
        assert caught.value.code == expected_code
        assert caught.value.details


def test_relationship_and_part_name_limits_fail_at_their_boundaries() -> None:
    relationship_data = _package(
        relationship_parts={
            "word/_rels/document.xml.rels": (
                ("rIdImage", _IMAGE_RELATIONSHIP, "media/a.png", None),
            )
        },
        extra_parts={"word/media/a.png": b"a"},
        defaults={"png": "image/png"},
    )
    with pytest.raises(OoxmlResourceLimitError) as relationships:
        _intake(
            relationship_data,
            limits=replace(OoxmlLimits(), max_relationships=1),
        )
    assert relationships.value.code == "relationships_limit"

    entries = list(_package_entries(OoxmlFamily.DOCX).items())
    entries.append((f"word/{'x' * 40}.xml", b"<long/>"))
    with pytest.raises(OoxmlResourceLimitError) as part_name:
        _intake(
            _zip_entries(tuple(entries)),
            limits=replace(OoxmlLimits(), max_part_name_chars=32),
        )
    assert part_name.value.code == "part_name_chars_limit"


def test_processing_timeout_is_checked_before_package_expansion() -> None:
    ticks = iter((10.0, 11.0))

    def clock() -> float:
        return next(ticks, 11.0)

    with pytest.raises(OoxmlResourceLimitError) as caught:
        _intake(
            _package(),
            limits=replace(OoxmlLimits(), timeout_seconds=0.5),
            clock=clock,
        )
    assert caught.value.code == "processing_time_limit"
    assert caught.value.stage == "declaration"


def test_limits_reject_invalid_configuration_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="max_entries"):
        OoxmlLimits(max_entries=0)
    with pytest.raises(ValueError, match="timeout_seconds"):
        OoxmlLimits(timeout_seconds=float("nan"))

    # Disabled auxiliary settings remain lazy for exact rollback, while the
    # same stale value fails startup as soon as intake is enabled.
    monkeypatch.setenv("PARSER_ADAPTERS_OOXML_MAX_ENTRIES", "stale")
    assert Settings.from_env().adapters_ooxml_intake_enabled is False
    monkeypatch.setenv("PARSER_ADAPTERS_CONFORMANCE_ENABLED", "true")
    monkeypatch.setenv("PARSER_ADAPTERS_OOXML_INTAKE_ENABLED", "true")
    with pytest.raises(ValueError, match="PARSER_ADAPTERS_OOXML_MAX_ENTRIES"):
        Settings.from_env()
