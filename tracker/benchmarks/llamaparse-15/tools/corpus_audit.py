#!/usr/bin/env python3
"""Inventory and render the immutable LlamaParse benchmark corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2


EXPECTED_EXTENSIONS = (".pdf", ".md", ".json")

CASE_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "catastrophe-recap": {
        "document_category": "insurance catastrophe recap",
        "layout_characteristics": [
            "single-column narrative",
            "ruled table",
            "four-panel vector chart",
            "running footer",
        ],
        "known_complex_elements": [
            "malformed embedded-font Unicode mapping",
            "external captions",
            "source note",
            "vector-measured chart values",
            "physical-versus-printed page identity",
        ],
    },
    "clean-energy": {
        "document_category": "clean-energy infographic",
        "layout_characteristics": [
            "landscape page",
            "six horizontal small-multiple panels",
            "running header and footer",
        ],
        "known_complex_elements": [
            "six independent chart scales and units",
            "printed growth labels",
            "vector-measured bar values",
            "embedded logo image",
        ],
    },
    "clinical-study": {
        "document_category": "clinical research article excerpt",
        "layout_characteristics": [
            "main column with sidebar",
            "dense scientific tables",
            "flowchart page",
            "headers, footers, and printed page labels",
        ],
        "known_complex_elements": [
            "multi-column reading order",
            "merged and multiline table cells",
            "table footnotes",
            "diagram nodes and connectors",
            "scientific symbols and inline links",
        ],
    },
    "component-datasheet": {
        "document_category": "technical component datasheet excerpt",
        "layout_characteristics": [
            "single-column technical prose",
            "margin captions",
            "nested lists",
            "callout box",
            "key-value groups",
        ],
        "known_complex_elements": [
            "board photograph",
            "pin-numbering diagram",
            "borderless key-value tables",
            "technical symbols and units",
            "physical-versus-printed page identity",
        ],
    },
    "egov-survey": {
        "document_category": "government survey report",
        "layout_characteristics": [
            "single-column narrative",
            "stacked bar chart",
            "running chapter marker and footer",
        ],
        "known_complex_elements": [
            "printed chart data labels",
            "legend and categories",
            "caption and source note",
            "physical-versus-printed page identity",
        ],
    },
    "esg-metrics": {
        "document_category": "ESG and sustainability metrics report",
        "layout_characteristics": [
            "landscape dashboard",
            "two-column composition",
            "dense data table",
            "donut and stacked-bar charts",
        ],
        "known_complex_elements": [
            "small text",
            "table footnotes",
            "chart labels and leaders",
            "mixed table-and-chart reading order",
            "physical-versus-printed page identity",
        ],
    },
    "finance-10k": {
        "document_category": "financial statement from annual report",
        "layout_characteristics": [
            "three portrait pages",
            "dense financial tables",
            "hierarchical row labels",
            "running footers",
        ],
        "known_complex_elements": [
            "borderless and lightly ruled tables",
            "accounting negatives",
            "multi-level column headers",
            "subtotal and total semantics",
            "physical-versus-printed page identity",
        ],
    },
    "health-report": {
        "document_category": "public-health statistical report",
        "layout_characteristics": [
            "two vertically stacked charts",
            "rotated category labels",
            "captions, notes, and source lines",
        ],
        "known_complex_elements": [
            "bar and point chart",
            "bubble chart",
            "printed and geometry-derived values",
            "legend symbols",
            "physical-versus-printed page identity",
        ],
    },
    "insurance-acord": {
        "document_category": "blank insurance certificate form",
        "layout_characteristics": [
            "dense ruled form",
            "merged cells",
            "key-value regions",
            "checkbox controls",
        ],
        "known_complex_elements": [
            "form field relationships",
            "empty values",
            "checkbox state",
            "multiline cells",
            "small text",
        ],
    },
    "manufacturing-report": {
        "document_category": "manufacturing and economic analysis report",
        "layout_characteristics": [
            "multiple charts per page",
            "callout labels",
            "captions and source notes",
            "running headers and footers",
        ],
        "known_complex_elements": [
            "ranked scatter curves",
            "labeled points",
            "percentile guides",
            "chart-to-table reconstruction",
            "physical-versus-printed page identity",
        ],
    },
    "ny-timetable": {
        "document_category": "public-transport timetable",
        "layout_characteristics": [
            "three full-page dense tables",
            "rotated column headers",
            "repeated schedule blocks",
            "running page labels",
        ],
        "known_complex_elements": [
            "high cell count",
            "blank and repeated cells",
            "row-group separators",
            "time-value fidelity",
            "physical-versus-printed page identity",
        ],
    },
    "postal-10k": {
        "document_category": "financial statement from annual report",
        "layout_characteristics": [
            "three portrait pages",
            "dense financial tables",
            "hierarchical rows and totals",
            "running footers",
        ],
        "known_complex_elements": [
            "multi-level headers",
            "accounting negatives",
            "multiline labels",
            "subtotal and total semantics",
            "physical-versus-printed page identity",
        ],
    },
    "purchase-agreement": {
        "document_category": "legal purchase-agreement redline",
        "layout_characteristics": [
            "single-column legal prose",
            "centered headings",
            "recital structure",
            "redline banner",
        ],
        "known_complex_elements": [
            "strikethrough deletion",
            "underlined insertion and placeholder",
            "text color",
            "legally material text-decoration semantics",
        ],
    },
    "settlement-agreement": {
        "document_category": "legal settlement-agreement excerpt",
        "layout_characteristics": [
            "single-column legal prose",
            "lettered clauses",
            "embedded percentage table",
            "running page number",
        ],
        "known_complex_elements": [
            "legal clause hierarchy",
            "table-interrupted prose",
            "percentage values",
            "source page ending mid-sentence",
            "physical-versus-printed page identity",
        ],
    },
    "uber-earnings": {
        "document_category": "investor earnings presentation excerpt",
        "layout_characteristics": [
            "three landscape slides",
            "photographic cover",
            "flag grid and charts",
            "two topology diagrams with sidebar",
        ],
        "known_complex_elements": [
            "generated image description",
            "small flag identification",
            "printed and vector-derived chart values",
            "diagram nodes and connector direction",
            "parallel visual and structured representations",
        ],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_pages(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return []
    pages = value.get("pages")
    return pages if isinstance(pages, list) else []


def json_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def render_pdf(pdf_path: Path, render_root: Path, case_id: str) -> list[str]:
    case_dir = render_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    document = pypdfium2.PdfDocument(str(pdf_path))
    outputs: list[str] = []
    for page_index in range(len(document)):
        page = document[page_index]
        bitmap = page.render(scale=1.5)
        image = bitmap.to_pil()
        output = case_dir / f"page-{page_index + 1:03d}.png"
        image.save(output, format="PNG", optimize=True)
        outputs.append(str(output))
        image.close()
        bitmap.close()
        page.close()
    document.close()
    return outputs


def inspect_pdf(pdf_path: Path) -> dict[str, Any]:
    page_stats: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as document:
        metadata = {
            str(key): value
            for key, value in (document.metadata or {}).items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        for page_number, page in enumerate(document.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            fonts = sorted(
                {
                    str(char.get("fontname"))
                    for char in page.chars
                    if char.get("fontname")
                }
            )
            page_stats.append(
                {
                    "page_number": page_number,
                    "width_pt": round(float(page.width), 3),
                    "height_pt": round(float(page.height), 3),
                    "rotation": int(page.rotation or 0),
                    "native_text_chars": len(text),
                    "native_word_count": len(page.extract_words() or []),
                    "character_objects": len(page.chars),
                    "image_objects": len(page.images),
                    "line_objects": len(page.lines),
                    "rect_objects": len(page.rects),
                    "curve_objects": len(page.curves),
                    "fonts": fonts,
                }
            )
    page_count = len(page_stats)
    text_pages = sum(1 for page in page_stats if page["native_text_chars"] >= 20)
    return {
        "page_count": page_count,
        "metadata": metadata,
        "page_stats": page_stats,
        "native_text_page_count": text_pages,
        "scanned_candidate": bool(page_count and text_pages == 0),
        "mixed_native_and_scanned_candidate": bool(
            page_count and 0 < text_pages < page_count
        ),
    }


def inspect_case(
    corpus_root: Path,
    case_id: str,
    render_root: Path | None,
) -> dict[str, Any]:
    paths = {
        extension: corpus_root / f"{case_id}{extension}"
        for extension in EXPECTED_EXTENSIONS
    }
    present = {extension: path.is_file() for extension, path in paths.items()}
    case: dict[str, Any] = {
        "case_id": case_id,
        "source_filename": paths[".pdf"].name,
        "source_format": "PDF",
        "benchmark_markdown_filename": paths[".md"].name,
        "benchmark_json_filename": paths[".json"].name,
        "expected_files_present": all(present.values()),
        "file_presence": present,
        "files": {},
        "corpus_validation_issues": [],
        **CASE_DESCRIPTORS.get(
            case_id,
            {
                "document_category": "unclassified",
                "layout_characteristics": [],
                "known_complex_elements": [],
            },
        ),
    }
    for extension, path in paths.items():
        if path.is_file():
            case["files"][extension] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        else:
            case["corpus_validation_issues"].append(
                f"missing expected {extension} file"
            )
    if not all(present.values()):
        return case

    source = inspect_pdf(paths[".pdf"])
    case["source"] = source

    try:
        expert = json.loads(paths[".json"].read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        case["corpus_validation_issues"].append(
            f"expert JSON is not valid UTF-8 JSON: {exc}"
        )
        return case

    markdown_file = paths[".md"].read_text(encoding="utf-8")
    markdown_pages = json_pages(expert, "markdown")
    text_pages = json_pages(expert, "text")
    joined_markdown_pages = "\n\n".join(
        str(page.get("markdown") or "").strip()
        for page in markdown_pages
        if isinstance(page, dict)
    ).strip()
    joined_text_pages = "\n\n".join(
        str(page.get("text") or "").strip()
        for page in text_pages
        if isinstance(page, dict)
    ).strip()
    markdown_full = json_string(expert, "markdown_full")
    text_full = json_string(expert, "text_full")
    expert_page_counts = {
        key: len(json_pages(expert, key))
        for key in ("markdown", "text", "items")
    }
    case["expert_output"] = {
        "top_level_keys": sorted(expert.keys()),
        "page_counts": expert_page_counts,
        "markdown_file_matches_markdown_full_exactly": (
            markdown_full == markdown_file if markdown_full is not None else None
        ),
        "markdown_file_matches_markdown_full_trimmed": (
            markdown_full.strip() == markdown_file.strip()
            if markdown_full is not None
            else None
        ),
        "markdown_file_matches_joined_pages_trimmed": (
            joined_markdown_pages == markdown_file.strip()
        ),
        "markdown_file_chars": len(markdown_file),
        "joined_markdown_pages_chars": len(joined_markdown_pages),
        "markdown_full_chars": (
            len(markdown_full) if markdown_full is not None else None
        ),
        "joined_text_pages_chars": len(joined_text_pages),
        "text_full_chars": len(text_full) if text_full is not None else None,
        "item_count": sum(
            len(page.get("items") or [])
            for page in json_pages(expert, "items")
            if isinstance(page, dict)
        ),
    }
    for key, count in expert_page_counts.items():
        if count and count != source["page_count"]:
            case["corpus_validation_issues"].append(
                f"source has {source['page_count']} pages but expert {key} has {count}"
            )
    if markdown_full is not None and markdown_full.strip() != markdown_file.strip():
        case["corpus_validation_issues"].append(
            "benchmark Markdown file differs from expert JSON markdown_full"
        )
    if joined_markdown_pages != markdown_file.strip():
        case["corpus_validation_issues"].append(
            "benchmark Markdown file differs from concatenated expert JSON markdown pages"
        )

    if render_root is not None:
        case["rendered_pages"] = render_pdf(
            paths[".pdf"], render_root, case_id
        )
    return case


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--render-root", type=Path)
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    grouped: dict[str, set[str]] = {}
    for path in corpus_root.iterdir():
        if not path.is_file():
            continue
        grouped.setdefault(path.stem, set()).add(path.suffix.lower())
    case_ids = sorted(grouped)
    cases = [
        inspect_case(corpus_root, case_id, args.render_root)
        for case_id in case_ids
    ]
    duplicate_pairing_issues = [
        {
            "case_id": case_id,
            "extensions": sorted(extensions),
            "unexpected_extensions": sorted(
                extensions - set(EXPECTED_EXTENSIONS)
            ),
        }
        for case_id, extensions in sorted(grouped.items())
        if extensions != set(EXPECTED_EXTENSIONS)
    ]
    payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_root": str(corpus_root),
        "source_files_immutable": True,
        "expected_case_count": 15,
        "case_count": len(cases),
        "all_expected_triplets_present": all(
            case["expected_files_present"] for case in cases
        ),
        "pairing_issues": duplicate_pairing_issues,
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
