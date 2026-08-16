from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest


@pytest.mark.sample
def test_sample_vector_table_extractor_finds_five_reference_tables(
    sample_pdf_path: Path,
) -> None:
    from app.services.tables import extract_vector_tables

    tables_by_page = extract_vector_tables(sample_pdf_path.read_bytes())

    assert {page: len(tables_by_page[page]) for page in (2, 3, 4)} == {
        2: 2,
        3: 2,
        4: 1,
    }
    assert sum(len(tables) for tables in tables_by_page.values()) == 5

    assert tables_by_page[2][0].rows[0] == [
        "Version",
        "Date",
        "Author(s)",
        "Changes",
    ]
    assert tables_by_page[2][1].rows[0] == [
        "Title",
        "Author(s)",
        "Location in QMS",
        "Comments",
    ]
    assert "Development Manager or Designee" in tables_by_page[3][0].rows[0][0]
    assert "Satish Reddi" in tables_by_page[3][0].rows[0][0]
    assert tables_by_page[3][1].rows[0] == [
        "Name",
        "Role",
        "Version(s)",
        "Date",
    ]
    assert tables_by_page[4][0].rows[0][0].startswith("Approvers:")


@pytest.mark.sample
def test_generic_workaround_page_seven_paragraph_is_not_a_vector_table(
    generic_workaround_pdf_path: Path,
) -> None:
    from app.services.tables import extract_vector_tables

    tables_by_page = extract_vector_tables(
        generic_workaround_pdf_path.read_bytes()
    )

    assert {page: len(tables_by_page[page]) for page in (2, 3, 4, 5)} == {
        2: 2,
        3: 2,
        4: 1,
        5: 1,
    }
    assert not tables_by_page[7]


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="Tesseract is required for targeted image OCR.",
)
def test_sample_image_ocr_detects_logo_and_three_signature_panels(
    sample_pdf_path: Path,
) -> None:
    from app.services.ocr import extract_image_ocr

    images_by_page = extract_image_ocr(sample_pdf_path.read_bytes())
    all_images = [
        image
        for page_images in images_by_page.values()
        for image in page_images
    ]
    extracted_text = "\n".join(image.text for image in all_images)

    assert {page: len(images_by_page[page]) for page in (1, 3, 4)} == {
        1: 1,
        3: 1,
        4: 2,
    }
    assert len(all_images) == 4
    assert "ORACLE" in extracted_text
    assert "Signer Name: Satish Reddi" in extracted_text
    assert "Signing Reason: I am the author of this document" in extracted_text
    assert "Signer Name: Prasad Bilugu" in extracted_text
    assert "Signer Name: Raghavendra Sharma" in extracted_text
    assert extracted_text.count("Signer Name:") == 3
    assert extracted_text.count("Signing Reason:") == 3
    assert extracted_text.count("Signing Time:") == 3


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 to run the Docling sample pipeline.",
)
def test_full_sample_pipeline_matches_reference_invariants(
    sample_pdf_path: Path,
) -> None:
    from app.config import Settings
    from app.services.pipeline import parse_document

    result = parse_document(
        sample_pdf_path.read_bytes(),
        sample_pdf_path.name,
        Settings(),
    ).model_dump(mode="json")

    assert [page["page_label"] for page in result["pages"]] == [
        "1",
        "2",
        "3",
        "4",
        "6",
        "7",
    ]
    tables = [
        item
        for page in result["pages"]
        for item in page["items"]
        if item["type"] == "table"
    ]
    assert len(tables) == 5

    all_text = "\n".join(
        str(item.get("ocr_text") or item.get("value") or "")
        for page in result["pages"]
        for item in page["items"]
    )
    assert "Satish Reddi" in all_text
    assert "Prasad Bilugu" in all_text
    assert "Raghavendra Sharma" in all_text

    page_seven = next(page for page in result["pages"] if page["page_label"] == "7")
    page_seven_text = "\n".join(
        str(item.get("value") or "") for item in page_seven["items"]
    )
    # The key and value are independent reading-order items in the normalized
    # JSON, even though they appear together on the rendered line.
    assert "Defect ID:" in page_seven_text
    assert "COE-7237" in page_seven_text
    assert "PROJECTED_VISIT" in page_seven_text


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 to run the Docling regression pipeline.",
)
def test_generic_workaround_page_seven_preserves_complete_paragraph(
    generic_workaround_pdf_path: Path,
) -> None:
    from app.config import Settings
    from app.services.pipeline import parse_document

    expected = (
        "Mapped route is not getting derived through configured rule for CRF: "
        "LOGS > Prior and Concomitant Medications, Log line#16 after data entry "
        "for Route of Administration item is done"
    )
    result = parse_document(
        generic_workaround_pdf_path.read_bytes(),
        generic_workaround_pdf_path.name,
        Settings(),
    ).model_dump(mode="json")
    page_seven = next(page for page in result["pages"] if page["page_index"] == 7)

    matching_items = [
        item
        for item in page_seven["items"]
        if expected in str(item.get("value") or "")
    ]
    false_tables = [
        item
        for item in page_seven["items"]
        if item["type"] == "table"
        and "Subject Number: 1190014" in str(item.get("value") or "")
    ]

    assert len(matching_items) == 1
    assert matching_items[0]["type"] == "text"
    assert not false_tables


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="Set RUN_INTEGRATION=1 to run the finance PDF regression.",
)
def test_finance_pdf_retains_reference_pages_headings_and_tables(
    finance_pdf_path: Path,
    finance_reference_json_path: Path,
) -> None:
    from app.config import Settings
    from app.services.pipeline import parse_document

    reference = json.loads(finance_reference_json_path.read_text())
    reference_pages = reference["items"]["pages"]
    result = parse_document(
        finance_pdf_path.read_bytes(),
        finance_pdf_path.name,
        Settings(),
    ).model_dump(mode="json")

    assert result["document"]["page_count"] == len(reference_pages) == 3
    assert [
        (page["page_width"], page["page_height"], page["unit"])
        for page in result["pages"]
    ] == [(612.0, 792.0, "pt")] * 3

    expected_headings = [
        "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "CONSOLIDATED BALANCE SHEETS",
        "CONSOLIDATED STATEMENTS OF CASH FLOWS",
    ]
    expected_last_rows = [
        ["Diluted", "15,812,547", "16,325,819", "16,864,919"],
        ["Total liabilities and shareholders’ equity", "352,583", "352,755"],
        ["Cash paid for interest", "3,803", "2,865", "2,687"],
    ]
    for page, heading, expected_last_row in zip(
        result["pages"],
        expected_headings,
        expected_last_rows,
        strict=True,
    ):
        page_text = "\n".join(
            str(item.get("value") or "")
            for item in page["items"]
        )
        tables = [
            item for item in page["items"] if item["type"] == "table"
        ]
        assert heading in page_text
        assert "See accompanying Notes to Consolidated Financial Statements." in (
            page_text
        )
        assert len(tables) == 1
        actual_last_row = tables[0]["rows"][-1]
        assert len(actual_last_row) == len(expected_last_row)
        assert [
            " ".join(
                str(cell).replace("’", "'").replace("$", "").split()
            )
            for cell in actual_last_row
        ] == [
            " ".join(
                str(cell).replace("’", "'").replace("$", "").split()
            )
            for cell in expected_last_row
        ]
        assert tables[0]["html"]
        assert tables[0]["md"]
        assert tables[0]["csv"]
