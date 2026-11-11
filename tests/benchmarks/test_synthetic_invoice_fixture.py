"""Check authored invoice custody and independently reopened PDF cell contents."""

from decimal import Decimal
import hashlib
import io
import json

import pdfplumber

from tests.benchmarks.routing_evaluation import Expectations, evaluate_check
from tests.fixtures.invoices.builder import FIXTURE_DIR, STEM, build_pdf, source_truth


def test_rendered_pdf_grids_preserve_wrapped_rows_repeated_skus_and_totals():
    source = source_truth()
    pdf = (FIXTURE_DIR / f"{STEM}.pdf").read_bytes()
    assert pdf == build_pdf(), "Source edits require regenerating checked-in artifacts."
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        assert len(document.pages) == 1
        page = document.pages[0]
        tables = page.extract_tables()
        assert len(tables) == 2
        assert tables[0] == [source["headers"], *source["line_items"]]
        assert tables[1] == source["summary_rows"]
        assert "Currency: USD" in page.extract_text()
        assert "Fictional fixture. Not payable." in page.extract_text()
        # Repeated SKU rows are separate source deliveries with different amounts.
        repeated = [row for row in tables[0][1:] if row[1] == "BRK-101"]
        assert [(row[0], row[3], row[5]) for row in repeated] == [
            ("1", "2", "25.00"), ("3", "5", "62.50"),
        ]
        assert all("\n" in row[2] for row in repeated)


def test_authored_amounts_reconcile_without_binary_float_rounding():
    source = source_truth()
    amounts = []
    for row in source["line_items"]:
        amount = Decimal(row[3]) * Decimal(row[4])
        assert amount == Decimal(row[5])
        amounts.append(amount)
    subtotal, tax, total = [Decimal(row[1]) for row in source["summary_rows"]]
    assert sum(amounts) == subtotal == Decimal("125.70")
    assert (subtotal * Decimal(source["tax_rate"])).quantize(Decimal("0.01")) == tax
    assert subtotal + tax == total == Decimal("138.27")


def test_pdf_and_image_expectations_are_bound_to_distinct_real_source_bytes():
    hashes = []
    for kind in ("pdf", "png"):
        source_path = FIXTURE_DIR / f"{STEM}.{kind}"
        expected = Expectations.model_validate(json.loads(
            (FIXTURE_DIR / f"{STEM}.{kind}.expected.json").read_text()
        ))
        assert expected.source_sha256 == hashlib.sha256(source_path.read_bytes()).hexdigest()
        hashes.append(expected.source_sha256)
        assert expected.coverage == "selected_claims"
        assert len(expected.checks) == 16
        # Independently extracted source rows, rather than parser output, define the target.
        with pdfplumber.open(FIXTURE_DIR / f"{STEM}.pdf") as document:
            rendered_rows = [row for table in document.pages[0].extract_tables() for row in table]
        assert expected.checks[0].expected == rendered_rows
    assert hashes[0] != hashes[1]


def test_numeric_checks_distinguish_wrap_formatting_from_missing_or_wrong_values():
    expected = Expectations.model_validate(json.loads(
        (FIXTURE_DIR / f"{STEM}.pdf.expected.json").read_text()
    ))
    with pdfplumber.open(FIXTURE_DIR / f"{STEM}.pdf") as document:
        tables = document.pages[0].extract_tables()
    # Synthetic observations for the expectation test, not an API benchmark.
    for row in tables[0][1:]:
        row[2] = row[2].replace("\n", " ")
    response = {"pages": [{"page_index": 1, "items": [
        {"type": "table", "row_count": len(rows), "column_count": len(rows[0]), "rows": rows}
        for rows in tables
    ]}]}
    results = {check.check_id: evaluate_check(response, check)["status"] for check in expected.checks}
    assert results["invoice-table-row-linkage-and-totals"] == "fail"
    assert sum(status == "pass" for status in results.values()) == 15

    tables[0][2][4] = ""  # Missing unit price for CAB-220.
    tables[0][3][3] = "2"  # Wrong quantity on the second BRK-101 delivery.
    tables[1][2][1] = "138.72"  # Wrong total despite plausible decimal format.
    failures = {
        check.check_id for check in expected.checks
        if evaluate_check(response, check)["status"] == "fail"
    }
    assert failures == {
        "invoice-table-row-linkage-and-totals", "line-2-unit-price",
        "line-3-quantity", "summary-total",
    }
