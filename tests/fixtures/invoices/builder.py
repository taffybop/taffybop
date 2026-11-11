"""Generate a byte-stable invoice and image from independently authored truth.

Like the existing font-audit fixtures, this uses a minimal conventional PDF
writer to avoid generator timestamps, random IDs, and new runtime dependencies.
It never imports the parser or derives truth from an extraction response.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


FIXTURE_DIR = Path(__file__).parent
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
TABLE_X = (44, 76, 151, 352, 393, 478, 568)
TABLE_Y = (230, 260, 310, 360, 410, 460)
SUMMARY_X = (352, 490, 568)
SUMMARY_Y = (494, 524, 554, 584)
STEM = "supplier-repeat-sku"


def source_truth() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "source.json").read_text(encoding="utf-8"))


def invoice_rows(source: dict[str, Any]) -> list[list[str]]:
    return [source["headers"], *source["line_items"], *source["summary_rows"]]


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(source: dict[str, Any] | None = None) -> bytes:
    source = source_truth() if source is None else source
    commands: list[str] = ["0 g", "0 G", "0.6 w"]

    def text(x: float, top: float, value: str, size: float = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        for index, line in enumerate(value.split("\n")):
            commands.append(
                f"BT /{font} {size:g} Tf 1 0 0 1 {x:g} "
                f"{PAGE_HEIGHT - top - index * 14:g} Tm ({_pdf_literal(line)}) Tj ET"
            )

    def grid(xs: tuple[int, ...], ys: tuple[int, ...]) -> None:
        for x in xs:
            commands.append(f"{x} {PAGE_HEIGHT - ys[0]} m {x} {PAGE_HEIGHT - ys[-1]} l S")
        for y in ys:
            commands.append(f"{xs[0]} {PAGE_HEIGHT - y} m {xs[-1]} {PAGE_HEIGHT - y} l S")

    text(44, 56, source["supplier"], 19, True)
    text(44, 79, "SYNTHETIC SUPPLIER INVOICE", 10)
    text(421, 56, "INVOICE", 20, True)
    text(44, 126, f"Bill to: {source['customer']}", 11)
    text(44, 149, f"Invoice number: {source['invoice_number']}", 11)
    text(44, 172, f"Invoice date: {source['invoice_date']}", 11)
    text(421, 126, f"Currency: {source['currency']}", 11, True)
    text(44, 211, "Line items", 12, True)
    grid(TABLE_X, TABLE_Y)
    for row_index, row in enumerate([source["headers"], *source["line_items"]]):
        for column, value in enumerate(row):
            text(TABLE_X[column] + 5, TABLE_Y[row_index] + 19, value,
                 9 if row_index == 0 else 10, row_index == 0)
    grid(SUMMARY_X, SUMMARY_Y)
    for row_index, row in enumerate(source["summary_rows"]):
        for column, value in enumerate(row):
            text(SUMMARY_X[column] + 7, SUMMARY_Y[row_index] + 19, value, 10, row_index == 2)
    text(44, 629, "Keep both BRK-101 lines: they are separate deliveries.", 10)
    text(44, 724, source["footer"], 9)
    text(513, 745, "Page 1 of 1", 9)

    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def expectation(source: dict[str, Any], source_bytes: bytes, source_name: str) -> dict[str, Any]:
    checks = [{
            "check_id": "invoice-table-row-linkage-and-totals",
            "kind": "rows",
            "selector": {"page_index": 1, "item_type": ["table", "table_candidate"]},
            "pointer": "/rows",
            "expected": invoice_rows(source),
            "ordered": True,
            "truth_class": "visible_text",
            "evidence_ref": (
                f"{source_name}, page 1: complete line-item grid followed by totals grid; "
                "source-authored tests/fixtures/invoices/source.json; descriptions use "
                "one newline per visible wrap; currency is printed in column headers and totals labels"
            ),
        }]
    for row_index, row in enumerate(source["line_items"], start=1):
        for name, column in (("quantity", 3), ("unit-price", 4), ("amount", 5)):
            checks.append({
                "check_id": f"line-{row[0]}-{name}",
                "kind": "field",
                "selector": {
                    "page_index": 1,
                    "item_type": ["table", "table_candidate"],
                    "match": {"row_count": len(source["line_items"]) + 1, "column_count": 6},
                },
                "pointer": f"/rows/{row_index}/{column}",
                "expected": row[column],
                "expected_count": 1,
                "truth_class": "visible_text",
                "evidence_ref": (
                    f"{source_name}, page 1: line {row[0]}, SKU {row[1]}, {name}; "
                    "source-authored tests/fixtures/invoices/source.json"
                ),
            })
    for row_index, (name, row) in enumerate(zip(
        ("subtotal", "tax", "total"), source["summary_rows"], strict=True
    )):
        checks.append({
            "check_id": f"summary-{name}",
            "kind": "field",
            "selector": {
                "page_index": 1,
                "item_type": ["table", "table_candidate"],
                "match": {"row_count": 3, "column_count": 2},
            },
            "pointer": f"/rows/{row_index}/1",
            "expected": row[1],
            "expected_count": 1,
            "truth_class": "visible_text",
            "evidence_ref": (
                f"{source_name}, page 1: totals grid, {row[0]}; "
                "source-authored tests/fixtures/invoices/source.json"
            ),
        })
    return {
        "schema_version": "1.0",
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "reviewer": "synthetic-invoice-source-author / supplier-repeat-sku-v1",
        "coverage": "selected_claims",
        "checks": checks,
    }


def write_fixture(output_dir: Path) -> dict[str, Path]:
    import pypdfium2 as pdfium

    output_dir.mkdir(parents=True, exist_ok=True)
    source = source_truth()
    pdf_bytes = build_pdf(source)
    paths = {"pdf": output_dir / f"{STEM}.pdf", "png": output_dir / f"{STEM}.png"}
    paths["pdf"].write_bytes(pdf_bytes)
    # 144 dpi; an image-only counterpart of the exact same authored source.
    with pdfium.PdfDocument(pdf_bytes) as document:
        page = document[0]
        bitmap = page.render(scale=2)
        image = bitmap.to_pil().convert("RGB")
        try:
            image.save(paths["png"], format="PNG")
        finally:
            image.close()
            bitmap.close()
            page.close()
    for kind in ("pdf", "png"):
        expected_path = output_dir / f"{STEM}.{kind}.expected.json"
        expected_path.write_text(
            json.dumps(expectation(source, paths[kind].read_bytes(), paths[kind].name), indent=2) + "\n",
            encoding="utf-8",
        )
        paths[f"{kind}_expected"] = expected_path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args()
    paths = write_fixture(args.output_dir)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))


if __name__ == "__main__":
    main()
