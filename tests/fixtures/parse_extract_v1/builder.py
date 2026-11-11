"""Render authored source definitions; never read or generate expected values.

The byte-stable PDF writer follows existing repository fixture conventions.
No new generator dependency or hosted service is needed. Regeneration does not
constitute permission to alter the frozen source truth or expectations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium


FIXTURE_DIR = Path(__file__).parent
WIDTH, HEIGHT = 612, 792
TABLE_X = (44, 108, 236, 334, 450, 568)
TABLE_Y = (290, 322, 354, 386, 418)


def definitions() -> list[dict[str, Any]]:
    return json.loads((FIXTURE_DIR / "sources.json").read_text())["documents"]


def _literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(source: dict[str, Any]) -> bytes:
    commands = ["0 g", "0 G", "0.6 w"]

    def text(top: int, value: str, *, x: int = 44, size: int = 11) -> None:
        commands.append(
            f"BT /F1 {size} Tf 1 0 0 1 {x} {HEIGHT - top} Tm ({_literal(value)}) Tj ET"
        )

    text(59, source["title"], size=16)
    for index, line in enumerate(source["lines"]):
        text(110 + index * 25, line)
    if table := source.get("table"):
        for x in TABLE_X:
            commands.append(f"{x} {HEIGHT - TABLE_Y[0]} m {x} {HEIGHT - TABLE_Y[-1]} l S")
        for y in TABLE_Y:
            commands.append(f"{TABLE_X[0]} {HEIGHT - y} m {TABLE_X[-1]} {HEIGHT - y} l S")
        for row_index, row in enumerate([table["headers"], *table["rows"]]):
            for column, value in enumerate(row):
                text(TABLE_Y[row_index] + 21, value, x=TABLE_X[column] + 7, size=10)
        for index, line in enumerate(source["after_table"]):
            text(460 + index * 25, line)
    text(735, "Authored synthetic evaluation source - no customer data", size=9)
    text(753, "Page 1 of 1", size=9)
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def render(pdf: bytes):
    """Return a detached RGB Pillow image at 144 dpi."""
    with pdfium.PdfDocument(pdf) as document:
        page = document[0]
        bitmap = page.render(scale=2)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
            page.close()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_fixtures(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = []
    for source in definitions():
        pdf = build_pdf(source)
        pdf_path = output_dir / f"{source['id']}.pdf"
        pdf_path.write_bytes(pdf)
        extension = "png" if source["image_format"] == "png" else "jpg"
        image_path = output_dir / f"{source['id']}.{extension}"
        with render(pdf) as image:
            image.save(image_path, format=source["image_format"], **({"quality": 92} if extension == "jpg" else {}))
        for path, mime in ((pdf_path, "application/pdf"), (image_path, f"image/{source['image_format']}")):
            assets.append({
                "asset_id": path.name,
                "document_id": source["id"],
                "split": source["split"],
                "family": source["family"],
                "path": path.name,
                "media_type": mime,
                "page_count": 1,
                "size_bytes": path.stat().st_size,
                "sha256": _hash(path),
                "authorized_for_provider": True,
                "authorization_basis": "Original fictional test source authored for this repository; no customer or private data.",
            })
    manifest = {
        "schema_version": "px-evaluation-manifest/1",
        "frozen_on": "2026-11-11",
        "corpus_version": "px1-initial-v1",
        "coverage": "selected_claims_only",
        "independent_document_count": len(definitions()),
        "source_definitions_sha256": _hash(FIXTURE_DIR / "sources.json"),
        "expectations_sha256": _hash(FIXTURE_DIR / "expected.json"),
        "assets": assets,
        "provider_results": [],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args()
    write_fixtures(args.output_dir)


if __name__ == "__main__":
    main()
