"""Release-first coverage for the native DOCX evidence adapter."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.errors import UnsupportedDocumentTypeError
from app.main import create_app
from app.models import ParseResult
from app.services.adapter_contracts import AdapterRegistry, validate_adapter_conformance
from app.services.docx_adapter import DOCX_MIME_TYPE, DocxNativeAdapter, parse_docx
from app.services.office_native import (
    OfficeAdapterDisabledError,
    OfficeNativeLimitError,
    OfficeNativePackageError,
)
from app.services.ooxml_intake import OoxmlSignatureError, intake_ooxml
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown, to_text
from tests.stories.phase_07.office_fixture_helpers import (
    DOC_REL_NS,
    docx_fixture,
    relationships,
    unzip_package,
    zip_package,
)


def test_representative_docx_preserves_logical_native_content_in_public_output() -> None:
    output = parse_docx(docx_fixture(), filename="quarterly.docx")
    result = ParseResult.model_validate(output)
    page = output["pages"][0]

    assert output["document"]["filename"] == "quarterly.docx"
    assert output["document"]["mime_type"] == DOCX_MIME_TYPE
    assert page["unit"] == "logical"
    assert page["coordinate_state"] == "logical"
    assert page["geometry_available"] is False
    assert [item["type"] for item in page["items"]] == [
        "header",
        "heading",
        "list",
        "table",
        "image",
        "image",
        "section",
        "footer",
    ]
    assert [item["reading_order"] for item in page["items"]] == list(range(8))
    assert all("bbox" not in item for item in page["items"])

    heading = page["items"][1]
    assert heading["value"] == "Quarterly Report"
    assert heading["level"] == 1
    assert heading["style_id"] == "Heading1"
    assert heading["runs"][0]["bold"] is True

    list_item = page["items"][2]
    assert list_item["ordered"] is True
    assert [(entry["value"], entry["level"]) for entry in list_item["items"]] == [
        ("First item", 0),
        ("Nested item", 1),
    ]

    markdown = to_markdown(result)
    assert markdown.count("Quarterly Report") == 1
    assert markdown.count("Acme Header") == 1
    assert markdown.count("Acme Footer") == 1
    assert markdown.count("<table>") == 1

    entries = unzip_package(docx_fixture())
    entries["word/document.xml"] = b"""<w:document xmlns:w="urn:word">
      <w:body>
        <w:p><w:r><w:t>Before wrappers</w:t></w:r></w:p>
        <w:sdt><w:sdtPr/><w:sdtContent>
          <w:p><w:r><w:t>Controlled block</w:t></w:r></w:p>
          <w:ins><w:p><w:r><w:t>Inserted block</w:t></w:r></w:p></w:ins>
          <w:del><w:p><w:r><w:t>Deleted block</w:t></w:r></w:p></w:del>
          <w:moveFrom><w:p><w:r><w:t>Old moved block</w:t></w:r></w:p></w:moveFrom>
          <w:moveTo><w:p><w:r><w:t>Visible moved block</w:t></w:r></w:p></w:moveTo>
        </w:sdtContent></w:sdt>
        <w:p>
          <w:r><w:t>Before inline</w:t></w:r>
          <w:del><w:r><w:t>Deleted inline</w:t></w:r></w:del>
          <w:ins><w:r><w:t>Inserted inline</w:t></w:r></w:ins>
          <w:moveFrom><w:r><w:t>Old moved inline</w:t></w:r></w:moveFrom>
          <w:moveTo><w:r><w:t>Visible moved inline</w:t></w:r></w:moveTo>
        </w:p>
        <w:sdt><w:sdtPr/><w:opaque/></w:sdt>
      </w:body>
    </w:document>"""
    wrapped_source = zip_package(entries)
    wrapped = parse_docx(wrapped_source, filename="wrapped.docx")
    assert wrapped == parse_docx(wrapped_source, filename="wrapped.docx")
    wrapped_items = wrapped["pages"][0]["items"]
    assert [item["value"] for item in wrapped_items] == [
        "Acme Header",
        "Before wrappers",
        "Controlled block",
        "Inserted block",
        "Visible moved block",
        "Before inlineInserted inlineVisible moved inline",
        "[Unsupported Word sdt]",
        "Acme Footer",
    ]
    assert "Deleted" not in json.dumps(wrapped, sort_keys=True)
    assert "Old moved" not in json.dumps(wrapped, sort_keys=True)
    assert wrapped_items[2]["native_provenance"]["xml_path"] == (
        "/document/body/sdt[1]/sdtContent[1]/p[1]"
    )
    assert wrapped_items[3]["native_provenance"]["xml_path"] == (
        "/document/body/sdt[1]/sdtContent[1]/ins[1]/p[1]"
    )
    assert wrapped_items[6]["parse_concerns"] == ["docx_sdt_unsupported"]
    assert ParseResult.model_validate(wrapped).document.filename == "wrapped.docx"


def test_docx_table_media_section_and_placeholder_are_grounded_once() -> None:
    output = parse_docx(docx_fixture())
    items = output["pages"][0]["items"]
    table = next(item for item in items if item["type"] == "table")
    assert table["rows"] == [["Region", "Revenue"], ["East", "10"]]
    assert table["header_rows"] == [0]
    assert table["caption"] == "Revenue table"
    assert len(table["cells"]) == 4
    assert all(
        cell["native_provenance"]["method"] == "native_xml"
        and cell["native_provenance"]["part"] == "word/document.xml"
        for cell in table["cells"]
    )

    embedded = next(item for item in items if item.get("asset_origin") == "native_embedded")
    assert embedded["source_part"] == "word/media/image1.png"
    assert embedded["native_provenance"]["relationship_id"] == "rIdImage"

    placeholder = next(item for item in items if item.get("placeholder"))
    assert placeholder["fallback_eligible"] is True
    assert placeholder["parse_concerns"] == ["docx_unsupported_drawing"]
    assert "bbox" not in placeholder

    section = next(item for item in items if item["type"] == "section")
    assert section["section"] == {
        "break_type": "nextPage",
        "orientation": "landscape",
        "column_count": 2,
    }
    assert all(
        item["native_provenance"]["method"] == "native_xml"
        and item["native_provenance"]["coordinate_state"] == "logical"
        for item in items
    )

    # Supplemental parts and table cells share the main paragraph revision
    # policy: insert/move-to text is visible, while delete/move-from text is
    # omitted without disturbing deterministic order or provenance.
    entries = unzip_package(docx_fixture())
    entries["word/header1.xml"] = b"""<w:hdr xmlns:w="urn:word"><w:p>
      <w:r><w:t>Header </w:t></w:r>
      <w:del><w:r><w:t>DELETED HEADER</w:t></w:r></w:del>
      <w:ins><w:r><w:t>inserted </w:t></w:r></w:ins>
      <w:moveFrom><w:r><w:t>OLD HEADER</w:t></w:r></w:moveFrom>
      <w:moveTo><w:r><w:t>moved</w:t></w:r></w:moveTo>
    </w:p></w:hdr>"""
    entries["word/footer1.xml"] = b"""<w:ftr xmlns:w="urn:word"><w:p>
      <w:moveFrom><w:r><w:t>OLD FOOTER</w:t></w:r></w:moveFrom>
      <w:moveTo><w:r><w:t>Visible footer</w:t></w:r></w:moveTo>
    </w:p></w:ftr>"""
    entries["word/document.xml"] = entries["word/document.xml"].replace(
        b"<w:r><w:t>East</w:t></w:r>",
        b"""<w:del><w:r><w:t>DELETED CELL</w:t></w:r></w:del>
        <w:ins><w:r><w:t>East</w:t></w:r></w:ins>
        <w:moveFrom><w:r><w:t>OLD CELL</w:t></w:r></w:moveFrom>""",
        1,
    )
    revised = parse_docx(zip_package(entries), filename="revised.docx")
    revised_items = revised["pages"][0]["items"]
    revised_table = next(item for item in revised_items if item["type"] == "table")
    encoded = json.dumps(revised, sort_keys=True)
    assert revised_items[0]["value"] == "Header inserted moved"
    assert revised_items[-1]["value"] == "Visible footer"
    assert revised_table["rows"] == [["Region", "Revenue"], ["East", "10"]]
    assert "DELETED" not in encoded
    assert "OLD CELL" not in encoded
    assert "OLD HEADER" not in encoded
    assert "OLD FOOTER" not in encoded
    assert revised_table["cells"][2]["native_provenance"]["xml_path"] == (
        "/document/body/tbl[1]/tr[2]/tc[1]"
    )
    assert ParseResult.model_validate(revised).document.filename == "revised.docx"


def test_docx_accepts_the_bounded_immutable_intake_package() -> None:
    data = docx_fixture()
    package = intake_ooxml(data, "bounded.docx", DOCX_MIME_TYPE)

    first = parse_docx(package, filename="bounded.docx")
    second = parse_docx(package, filename="bounded.docx")

    assert first == second
    assert first["document"]["sha256"] == package.source_sha256
    assert "word/document.xml" in package.part_names
    assert ParseResult.model_validate(first).document.filename == "bounded.docx"

    # Optional OOXML parts must stay optional through the native adapter's
    # duck-typed package view; the production intake rejects leading-slash
    # compatibility probes instead of converting absence into a path error.
    from app.services.office_native import OfficePackageView

    view = OfficePackageView(package)
    assert view.read_part("word/not-present.xml", required=False) is None
    with pytest.raises(OfficeNativePackageError) as missing:
        view.read_part("word/not-present.xml")
    assert missing.value.code == "office_package_part_missing"

    # The adapter follows the intake-validated main part and its auxiliary
    # relationships instead of assuming the conventional word/ locations.
    entries = unzip_package(data)
    renamed = {
        (f"custom/{name.removeprefix('word/')}" if name.startswith("word/") else name): value
        for name, value in entries.items()
    }
    renamed["_rels/.rels"] = renamed["_rels/.rels"].replace(
        b"word/document.xml",
        b"custom/document.xml",
    )
    renamed["[Content_Types].xml"] = renamed["[Content_Types].xml"].replace(
        b"/word/",
        b"/custom/",
    )
    renamed["custom/meta/styles-custom.xml"] = renamed.pop("custom/styles.xml")
    renamed["custom/meta/numbering-custom.xml"] = renamed.pop("custom/numbering.xml")
    renamed["custom/_rels/document.xml.rels"] = relationships(
        [
            ("rIdHeader", f"{DOC_REL_NS}/header", "header1.xml", None),
            ("rIdFooter", f"{DOC_REL_NS}/footer", "footer1.xml", None),
            ("rIdImage", f"{DOC_REL_NS}/image", "media/image1.png", None),
            ("rIdStyles", f"{DOC_REL_NS}/styles", "meta/styles-custom.xml", None),
            (
                "rIdNumbering",
                f"{DOC_REL_NS}/numbering",
                "meta/numbering-custom.xml",
                None,
            ),
        ]
    )
    renamed_package = intake_ooxml(
        zip_package(renamed),
        "renamed.docx",
        DOCX_MIME_TYPE,
    )
    renamed_output = parse_docx(renamed_package)
    assert renamed_package.manifest.main_part == "custom/document.xml"
    assert renamed_output["pages"][0]["items"][1]["style_name"] == "Heading 1"
    assert renamed_output["pages"][0]["items"][2]["ordered"] is True


def test_docx_adapter_conforms_and_dispatches_through_shared_registry() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_docx_native_enabled=True,
    )
    adapter = DocxNativeAdapter(settings)
    assert validate_adapter_conformance(adapter).registration_allowed is True
    registry = AdapterRegistry()
    registry.register(adapter)

    output = registry.dispatch(
        docx_fixture(),
        "registry.docx",
        DOCX_MIME_TYPE,
        settings,
    )
    assert ParseResult.model_validate(output).document.filename == "registry.docx"


def test_docx_public_pipeline_dispatch_and_flag_off_rollback() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_docx_native_enabled=True,
    )
    result = parse_document(docx_fixture(), "public.docx", settings)

    assert result.document.filename == "public.docx"
    assert "Quarterly Report" in to_text(result)
    assert "Quarterly Report" in to_markdown(result)

    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("public.docx", docx_fixture(), DOCX_MIME_TYPE)},
        )
    assert response.status_code == 200
    assert response.json()["document"]["filename"] == "public.docx"
    assert "Quarterly Report" in json.dumps(response.json(), sort_keys=True)

    with pytest.raises(UnsupportedDocumentTypeError):
        parse_document(docx_fixture(), "disabled.docx", Settings())


def test_docx_disabled_and_element_limit_fail_before_partial_output() -> None:
    with pytest.raises(OfficeAdapterDisabledError) as disabled:
        parse_docx(docx_fixture(), enabled=False)
    assert disabled.value.code == "unsupported_document_type"

    with pytest.raises(OfficeNativeLimitError) as limited:
        parse_docx(docx_fixture(), max_elements=2)
    assert limited.value.code == "docx_element_limit"

    entries = unzip_package(docx_fixture())
    nested = b"<w:ins>" * 66 + b"<w:p/>" + b"</w:ins>" * 66
    entries["word/document.xml"] = (
        b'<w:document xmlns:w="urn:word"><w:body>'
        + nested
        + b"</w:body></w:document>"
    )
    with pytest.raises(OfficeNativeLimitError) as depth_limited:
        parse_docx(zip_package(entries))
    assert depth_limited.value.code == "docx_wrapper_depth_limit"

    supplemental_entries = unzip_package(docx_fixture())
    supplemental_entries["word/header1.xml"] = (
        b'<w:hdr xmlns:w="urn:word">'
        + b"<w:ins>" * 66
        + b"<w:p><w:r><w:t>too deep</w:t></w:r></w:p>"
        + b"</w:ins>" * 66
        + b"</w:hdr>"
    )
    with pytest.raises(OfficeNativeLimitError) as supplemental_depth:
        parse_docx(zip_package(supplemental_entries))
    assert supplemental_depth.value.code == "docx_wrapper_depth_limit"


def test_malformed_docx_fails_through_intake_or_raw_compatibility_boundary() -> None:
    malformed = b"not an OOXML ZIP"
    with pytest.raises(OoxmlSignatureError):
        intake_ooxml(malformed, "bad.docx", DOCX_MIME_TYPE)
    with pytest.raises(OfficeNativePackageError) as raw:
        parse_docx(malformed)
    assert raw.value.code == "office_package_zip_invalid"

    entries = unzip_package(docx_fixture())
    entries["word/document.xml"] = (
        b" " * 17_000
        + b'<!DOCTYPE document [<!ENTITY expansion "unsafe">]>'
        + b'<w:document xmlns:w="urn:word"><w:body>&expansion;</w:body></w:document>'
    )
    with pytest.raises(OfficeNativePackageError) as declaration:
        parse_docx(zip_package(entries))
    assert declaration.value.code == "office_xml_dtd_forbidden"


def test_docx_json_has_no_invented_geometry_or_executed_content() -> None:
    output = parse_docx(docx_fixture())
    encoded = json.dumps(output, sort_keys=True)

    assert '"bbox"' not in encoded
    assert output["processing"]["macros_executed"] is False
    assert output["processing"]["formulas_executed"] is False
    assert output["processing"]["external_content_fetched"] is False
    assert ParseResult.model_validate_json(json.dumps(output))
