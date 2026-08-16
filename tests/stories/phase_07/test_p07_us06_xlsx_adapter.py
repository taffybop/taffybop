"""Release-first coverage for the native XLSX evidence adapter."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.errors import UnsupportedDocumentTypeError
from app.main import create_app
from app.models import ParseResult
from app.services.adapter_contracts import AdapterRegistry, validate_adapter_conformance
from app.services.office_native import (
    OfficeAdapterDisabledError,
    OfficeNativeLimitError,
    OfficeNativePackageError,
)
from app.services.ooxml_intake import OoxmlSignatureError, intake_ooxml
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown, to_text
from app.services.xlsx_adapter import XLSX_MIME_TYPE, XlsxNativeAdapter, parse_xlsx
from tests.stories.phase_07.office_fixture_helpers import (
    DOC_REL_NS,
    relationships,
    unzip_package,
    xlsx_fixture,
    zip_package,
)


def _cells(output: dict[str, object]) -> dict[str, dict[str, object]]:
    page = output["pages"][0]  # type: ignore[index]
    table = page["items"][0]  # type: ignore[index]
    return {cell["coordinate"]: cell for cell in table["cells"]}


def test_representative_xlsx_preserves_ordered_typed_cells_and_public_output() -> None:
    output = parse_xlsx(xlsx_fixture(), filename="revenue.xlsx")
    result = ParseResult.model_validate(output)
    cells = _cells(output)

    assert output["document"]["mime_type"] == XLSX_MIME_TYPE
    assert output["document"]["date_system"] == "1900"
    assert [page["page_label"] for page in output["pages"]] == ["Summary", "Hidden"]
    assert [page["sheet_id"] for page in output["pages"]] == ["1", "2"]
    assert output["pages"][0]["unit"] == "logical"
    assert output["pages"][0]["geometry_available"] is False
    assert all("bbox" not in item for item in output["pages"][0]["items"])

    assert cells["A1"]["value"] == "Name"
    assert cells["B2"]["value"] == 10
    assert cells["B2"]["value_type"] == "number"
    assert cells["C2"]["value"] == "2024-01-01"
    assert cells["C2"]["value_type"] == "date"
    assert cells["C3"]["value"] == "#N/A"
    assert cells["C3"]["value_type"] == "error"

    markdown = to_markdown(result)
    assert markdown.count("<table>") == 1
    assert markdown.count("Revenue") == 1


def test_xlsx_retains_formula_and_cache_separately_without_execution() -> None:
    output = parse_xlsx(xlsx_fixture())
    formula = _cells(output)["B3"]

    assert formula["formula"] == "SUM(B2:B2)"
    assert formula["cached_value"] == 10
    assert formula["formula_cache_state"] == "present"
    assert formula["formula_executed"] is False
    assert output["processing"]["formula_policy"] == "preserve_without_execution"
    assert output["processing"]["formulas_executed"] is False

    missing = parse_xlsx(xlsx_fixture(include_formula_cache=False))
    missing_formula = _cells(missing)["B3"]
    assert missing_formula["formula"] == "SUM(B2:B2)"
    assert missing_formula["cached_value"] is None
    assert missing_formula["formula_cache_state"] == "missing"
    assert missing_formula["parse_concerns"] == ["xlsx_formula_cache_missing"]

    external = parse_xlsx(xlsx_fixture(formula="[external.xlsx]Data!A1"))
    external_formula = _cells(external)["B3"]
    assert "xlsx_external_formula_not_executed" in external_formula["parse_concerns"]
    assert external["processing"]["external_content_fetched"] is False

    huge_decimal = "9" * 400 + ".5"
    bounded = parse_xlsx(xlsx_fixture(numeric_value=huge_decimal))
    bounded_cell = _cells(bounded)["B2"]
    assert bounded_cell["value"] == huge_decimal
    assert bounded_cell["parse_concerns"] == ["xlsx_numeric_value_out_of_range"]
    json.dumps(bounded, allow_nan=False)
    assert ParseResult.model_validate(bounded)


def test_xlsx_visibility_tables_merges_and_drawing_placeholder_are_explicit() -> None:
    output = parse_xlsx(xlsx_fixture())
    encoded = json.dumps(output, sort_keys=True)
    visible = output["pages"][0]
    hidden = output["pages"][1]
    table = visible["items"][0]

    assert "HIDDEN COLUMN SECRET" not in encoded
    assert "HIDDEN ROW SECRET" not in encoded
    assert "HIDDEN SHEET SECRET" not in encoded
    assert hidden["visibility"] == "hidden"
    assert hidden["items"] == []
    assert table["hidden_columns"] == ["D"]
    assert table["hidden_rows"] == [4]
    assert table["merged_ranges"] == ["A3:A3"]
    assert table["native_tables"][0]["name"] == "RevenueTable"
    assert table["native_tables"][0]["range"] == "A1:C3"

    drawing = visible["items"][1]
    assert drawing["placeholder"] is True
    assert drawing["fallback_eligible"] is True
    assert drawing["source_part"] == "xl/drawings/drawing1.xml"
    assert drawing["parse_concerns"] == ["xlsx_drawing_native_deferred"]


def test_xlsx_sparse_range_and_cell_limits_fail_without_expansion() -> None:
    with pytest.raises(OfficeNativeLimitError) as sparse:
        parse_xlsx(
            xlsx_fixture(dimension="A1:XFD1048576"),
            max_sparse_area=1_000_000,
        )
    assert sparse.value.code == "xlsx_sparse_range_limit"

    with pytest.raises(OfficeNativeLimitError) as cells:
        parse_xlsx(xlsx_fixture(), max_cells=2)
    assert cells.value.code == "xlsx_cell_limit"

    with pytest.raises(OfficeNativePackageError) as out_of_bounds:
        parse_xlsx(xlsx_fixture(dimension="A1:XFE1"))
    assert out_of_bounds.value.code == "xlsx_cell_reference_out_of_bounds"

    with pytest.raises(OfficeNativeLimitError) as configured_rows:
        parse_xlsx(xlsx_fixture(), max_rows=3)
    assert configured_rows.value.code == "xlsx_row_limit"

    with pytest.raises(OfficeNativeLimitError) as configured_columns:
        parse_xlsx(xlsx_fixture(), max_columns=3)
    assert configured_columns.value.code == "xlsx_column_limit"


def test_xlsx_accepts_intake_package_and_disabled_mode_is_unsupported() -> None:
    data = xlsx_fixture()
    package = intake_ooxml(data, "bounded.xlsx", XLSX_MIME_TYPE)
    first = parse_xlsx(package, filename="bounded.xlsx")
    second = parse_xlsx(package, filename="bounded.xlsx")

    assert first == second
    assert first["document"]["sha256"] == package.source_sha256
    assert ParseResult.model_validate(first).pages[0].unit == "logical"

    entries = unzip_package(data)
    renamed = {
        (f"book/{name.removeprefix('xl/')}" if name.startswith("xl/") else name): value
        for name, value in entries.items()
    }
    renamed["_rels/.rels"] = renamed["_rels/.rels"].replace(
        b"xl/workbook.xml",
        b"book/workbook.xml",
    )
    renamed["[Content_Types].xml"] = renamed["[Content_Types].xml"].replace(
        b"/xl/",
        b"/book/",
    )
    renamed["book/meta/strings.xml"] = renamed.pop("book/sharedStrings.xml")
    renamed["book/meta/styles.xml"] = renamed.pop("book/styles.xml")
    renamed["[Content_Types].xml"] = renamed["[Content_Types].xml"].replace(
        b"/book/sharedStrings.xml",
        b"/book/meta/strings.xml",
    ).replace(
        b"/book/styles.xml",
        b"/book/meta/styles.xml",
    )
    renamed["book/_rels/workbook.xml.rels"] = relationships(
        [
            ("rId1", f"{DOC_REL_NS}/worksheet", "worksheets/sheet1.xml", None),
            ("rId2", f"{DOC_REL_NS}/worksheet", "worksheets/sheet2.xml", None),
            (
                "rIdStrings",
                f"{DOC_REL_NS}/sharedStrings",
                "meta/strings.xml",
                None,
            ),
            ("rIdStyles", f"{DOC_REL_NS}/styles", "meta/styles.xml", None),
        ]
    )
    renamed_package = intake_ooxml(
        zip_package(renamed),
        "renamed.xlsx",
        XLSX_MIME_TYPE,
    )
    renamed_output = parse_xlsx(renamed_package)
    assert renamed_package.manifest.main_part == "book/workbook.xml"
    assert _cells(renamed_output)["A1"]["value"] == "Name"
    assert _cells(renamed_output)["C2"]["value_type"] == "date"

    with pytest.raises(OfficeAdapterDisabledError) as disabled:
        parse_xlsx(package, enabled=False)
    assert disabled.value.code == "unsupported_document_type"


def test_xlsx_adapter_conforms_and_dispatches_through_shared_registry() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_xlsx_native_enabled=True,
    )
    adapter = XlsxNativeAdapter(settings)
    assert validate_adapter_conformance(adapter).registration_allowed is True
    registry = AdapterRegistry()
    registry.register(adapter)

    output = registry.dispatch(
        xlsx_fixture(),
        "registry.xlsx",
        XLSX_MIME_TYPE,
        settings,
    )
    assert ParseResult.model_validate(output).document.filename == "registry.xlsx"


def test_xlsx_public_pipeline_dispatch_and_flag_off_rollback() -> None:
    settings = Settings(
        adapters_conformance_enabled=True,
        adapters_ooxml_intake_enabled=True,
        adapters_xlsx_native_enabled=True,
    )
    result = parse_document(xlsx_fixture(), "public.xlsx", settings)

    assert result.document.filename == "public.xlsx"
    assert "Revenue" in to_text(result)
    assert "Revenue" in to_markdown(result)

    active_settings = {"value": settings}
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: active_settings["value"]
    with TestClient(application) as client:
        response = client.post(
            "/v1/parse?output_format=text",
            files={"file": ("public.xlsx", xlsx_fixture(), XLSX_MIME_TYPE)},
        )
        sparse = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "sparse.xlsx",
                    xlsx_fixture(dimension="A1:XFD1048576"),
                    XLSX_MIME_TYPE,
                )
            },
        )
        active_settings["value"] = Settings(
            adapters_conformance_enabled=True,
            adapters_ooxml_intake_enabled=True,
            adapters_xlsx_native_enabled=True,
            adapters_xlsx_max_cells=2,
        )
        limited = client.post(
            "/v1/parse?output_format=text",
            files={"file": ("limited.xlsx", xlsx_fixture(), XLSX_MIME_TYPE)},
        )
        malformed_entries = unzip_package(xlsx_fixture())
        malformed_entries["xl/worksheets/sheet1.xml"] = b"<worksheet"
        malformed = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "malformed.xlsx",
                    zip_package(malformed_entries),
                    XLSX_MIME_TYPE,
                )
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Revenue" in response.text
    assert sparse.status_code == 413
    assert sparse.json()["error"]["code"] == "ooxml_limit_exceeded"
    assert sparse.json()["error"]["details"]["reason"] == (
        "xlsx_sparse_range_limit"
    )
    assert limited.status_code == 413
    assert limited.json()["error"]["code"] == "ooxml_limit_exceeded"
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_ooxml"

    with pytest.raises(UnsupportedDocumentTypeError):
        parse_document(xlsx_fixture(), "disabled.xlsx", Settings())


def test_malformed_xlsx_fails_at_intake_or_raw_boundary() -> None:
    malformed = b"not an OOXML ZIP"
    with pytest.raises(OoxmlSignatureError):
        intake_ooxml(malformed, "bad.xlsx", XLSX_MIME_TYPE)
    with pytest.raises(OfficeNativePackageError) as raw:
        parse_xlsx(malformed)
    assert raw.value.code == "office_package_zip_invalid"
