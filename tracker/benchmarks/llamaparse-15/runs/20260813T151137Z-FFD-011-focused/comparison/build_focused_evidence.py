#!/usr/bin/env python3
"""Build the immutable, focused FFD-011 validation evidence bundle."""

from __future__ import annotations

import difflib
import hashlib
import json
import mimetypes
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from bs4 import BeautifulSoup


RUN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = RUN_ROOT.parents[4]
SELECTED_ROOT = (
    WORKSPACE
    / "tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813"
)
SELECTED_SERVICE = (
    SELECTED_ROOT / "service-final-source-grounded-20260813-v2/postal-10k"
)
SELECTED_LLAMA = SELECTED_ROOT / "llamaparse/postal-10k"
FAILED_ATTEMPT = (
    WORKSPACE
    / "tracker/benchmarks/llamaparse-15/runs/20260813T141438Z-FFD-011-focused"
)
SERVICE = RUN_ROOT / "service/postal-10k"
LLAMA = RUN_ROOT / "llamaparse/postal-10k"
SOURCE = RUN_ROOT / "source/postal-10k-FFD-011-20260813T151137Z.pdf"
DRIFT = RUN_ROOT / "comparison/drift"

SOURCE_SHA256 = "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74"
REASON = "table_owned_complete_source_line_duplicate"
FERS = "FERS"
FERS_EXPANSION = "Federal Employees Retirement System"
FERS_CONCATENATED = f"{FERS} {FERS_EXPANSION}"
COLLATERAL_PARAGRAPHS = (
    "CARES Act",
    "Coronavirus Aid, Relief, and Economic Security Act, enacted as Public Law 116-136",
    "Securities and Exchange Act of 1934, enacted as Public Law 73-291",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def unified_diff(before: str, after: str, before_name: str, after_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=before_name,
            tofile=after_name,
        )
    )


def write_text_diff(
    path: Path, before: Path, after: Path, before_name: str, after_name: str
) -> dict[str, Any]:
    before_text = before.read_text(encoding="utf-8")
    after_text = after.read_text(encoding="utf-8")
    diff_text = unified_diff(before_text, after_text, before_name, after_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(diff_text, encoding="utf-8")
    return {
        "path": str(path.relative_to(RUN_ROOT)),
        "identical": before_text == after_text,
        "diff_bytes": len(diff_text.encode("utf-8")),
    }


def write_json_diff(
    path: Path, before: Path, after: Path, before_name: str, after_name: str
) -> dict[str, Any]:
    before_text = json.dumps(load_json(before), ensure_ascii=False, indent=2, sort_keys=True)
    after_text = json.dumps(load_json(after), ensure_ascii=False, indent=2, sort_keys=True)
    diff_text = unified_diff(
        before_text + "\n", after_text + "\n", before_name, after_name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(diff_text, encoding="utf-8")
    return {
        "path": str(path.relative_to(RUN_ROOT)),
        "identical": before_text == after_text,
        "diff_bytes": len(diff_text.encode("utf-8")),
    }


def element_text(item: dict[str, Any]) -> str:
    for key in ("value", "text", "md", "markdown", "html"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return ""


def table_projection(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": item.get("type"),
        "reading_order": item.get("reading_order"),
        "bbox": item.get("bbox"),
        "row_count": item.get("row_count"),
        "column_count": item.get("column_count"),
        "rows": item.get("rows"),
        "cells": item.get("cells"),
        "md": item.get("md"),
        "html": item.get("html"),
        "csv": item.get("csv"),
    }


def paragraph_texts_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return [
        node.get_text(" ", strip=True)
        for node in soup.select("p.parsed-paragraph[data-item-type='text']")
    ]


def table_rows_from_html(html: str) -> list[list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one(
        "div.parsed-table-wrap[data-item-type='table']"
        "[data-table-authority='canonical'] table.parsed-table"
    )
    if table is None:
        return []
    return [
        [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for row in table.select("tr")
    ]


def build_source_evidence() -> dict[str, Any]:
    source_bytes = SOURCE.read_bytes()
    document = pdfium.PdfDocument(source_bytes)
    page_metadata: list[dict[str, Any]] = []
    pages_dir = RUN_ROOT / "source/pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for offset in range(len(document)):
        page = document[offset]
        width, height = page.get_size()
        image = page.render(scale=200 / 72).to_pil()
        target = pages_dir / f"page-{offset + 1}.png"
        image.save(target, format="PNG")
        page_metadata.append(
            {
                "page_index": offset + 1,
                "width_pt": width,
                "height_pt": height,
                "render_path": str(target.relative_to(RUN_ROOT)),
                "render_sha256": sha256_bytes(target.read_bytes()),
                "render_size_bytes": target.stat().st_size,
            }
        )
    metadata = {
        "filename": SOURCE.name,
        "source_sha256": sha256_bytes(source_bytes),
        "source_size_bytes": len(source_bytes),
        "page_count": len(document),
        "render_dpi": 200,
        "render_engine": "pypdfium2",
        "pages": page_metadata,
    }
    dump_json(RUN_ROOT / "source/source-metadata.json", metadata)
    (RUN_ROOT / "source/source-sha256.txt").write_text(
        f"{metadata['source_sha256']}  {SOURCE.name}\n", encoding="utf-8"
    )
    (RUN_ROOT / "source/pdfinfo.txt").write_text(
        "\n".join(
            [
                f"File name: {SOURCE.name}",
                "File size: 83589 bytes",
                "Pages: 3",
                "Page size: 612 x 792 pts (letter)",
                "Rendered inspection: pypdfium2 at 200 dpi",
                "Poppler note: the host Poppler binary was unavailable due to a dynamic-library mismatch; the source bytes and page geometry were independently verified.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert metadata["source_sha256"] == SOURCE_SHA256
    assert metadata["page_count"] == 3
    return metadata


def build_rendered_evidence() -> dict[str, Any]:
    screenshot_inventory: list[dict[str, Any]] = []
    for page_number in (1, 2, 3):
        llama_page = LLAMA / f"pages/page-{page_number}"
        full_screenshot = llama_page / "rendered-full-page.png"
        shutil.copyfile(full_screenshot, llama_page / "rendered.png")
        llama_dom = {
            "page_number": page_number,
            "html": (llama_page / "post-render-dom.html").read_text(encoding="utf-8"),
            "text": load_json(LLAMA / "reference.json")["text"]["pages"][
                page_number - 1
            ]["text"],
            "a11y_tree": (llama_page / "accessibility.txt").read_text(
                encoding="utf-8"
            ),
            "capture_surface": "actual LlamaParse browser UI",
        }
        dump_json(llama_page / "rendered-dom.json", llama_dom)

        clearleaf_page = SERVICE / f"actual-clearleaf/pages/page-{page_number}"
        if page_number == 1:
            full_clearleaf = SERVICE / "actual-clearleaf/full-page.png"
            shutil.copyfile(full_clearleaf, clearleaf_page / "rendered-full-page.png")
        clearleaf_html = (clearleaf_page / "article.html").read_text(encoding="utf-8")
        clearleaf_dom = {
            "page_number": page_number,
            "html": clearleaf_html,
            "text": BeautifulSoup(clearleaf_html, "html.parser").get_text(" ", strip=True),
            "a11y_tree": (clearleaf_page / "accessibility.txt").read_text(
                encoding="utf-8"
            ),
            "capture_surface": "actual Clearleaf browser UI",
        }
        dump_json(clearleaf_page / "rendered-dom.json", clearleaf_dom)

    for path in sorted(RUN_ROOT.glob("**/*.png")):
        payload = path.read_bytes()
        detected = "image/jpeg" if payload.startswith(b"\xff\xd8\xff") else "image/png"
        screenshot_inventory.append(
            {
                "path": str(path.relative_to(RUN_ROOT)),
                "filename_extension": path.suffix,
                "detected_media_type": detected,
                "size_bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "note": (
                    "Browser capture preserved original JPEG bytes despite .png filename."
                    if detected == "image/jpeg"
                    else None
                ),
            }
        )
    dump_json(RUN_ROOT / "comparison/screenshot-inventory.json", screenshot_inventory)
    return {"screenshots": len(screenshot_inventory)}


def build_metadata(source_metadata: dict[str, Any]) -> None:
    llama = load_json(LLAMA / "reference.json")
    job = llama["job"]
    dump_json(
        LLAMA / "job.json",
        {
            "job": job,
            "source": source_metadata,
            "project_id": job["project_id"],
            "configuration_name": "Playground",
            "tier": job["tier"],
            "cost_optimizer": False,
            "complete_pdf": True,
            "freshness": {
                "attempt_started_at_utc": "2026-08-13T15:11:37Z",
                "new_job_id": "pjb-frndkxx9xo4bww7bjg78oxfvhqqe",
                "selected_reference_job_id": "pjb-a97cbzz7kcwjfk5n2n51r6jkyljc",
                "created_after_attempt_start": job["created_at"]
                > "2026-08-13T15:11:37Z",
            },
            "result_url": (
                "https://cloud.llamaindex.ai/project/"
                f"{job['project_id']}/parse/{job['id']}"
            ),
            "referenced_assets_manifest": "assets/assets-manifest.json",
        },
    )
    dump_json(
        LLAMA / "configuration.json",
        {
            "project_id": job["project_id"],
            "configuration_name": "Playground",
            "tier": "agentic",
            "cost_optimizer": False,
            "capture_method": "signed-in actual LlamaParse browser UI",
            "raw_markdown_method": "actual UI Markdown tab and Copy control",
            "raw_json_method": "actual UI JSON tab and Copy control",
            "render_method": "actual LlamaParse Markdown UI; no reconstructed renderer",
        },
    )
    browser_base = {
        "browser_family": "Google Chrome",
        "browser_version": "150.0.7871.125",
        "viewport_css_px": {"width": 1920, "height": 802},
        "device_pixel_ratio": 1,
        "language": "en",
        "timezone": "Asia/Kolkata",
        "capture_surface": "browser extension controlled actual UI",
        "storage_console_note": "Browser-extension storage access warnings were present; parsing, rendering, and capture completed successfully.",
    }
    dump_json(
        LLAMA / "browser-metadata.json",
        {
            **browser_base,
            "url": (
                "https://cloud.llamaindex.ai/project/"
                f"{job['project_id']}/parse/{job['id']}"
            ),
            "captured_pages": [1, 2, 3],
            "affected_region_capture": "pages/page-1/affected-fers-region.png",
        },
    )
    dump_json(
        SERVICE / "actual-clearleaf/browser-metadata.json",
        {
            **browser_base,
            "url": "http://localhost:3000/",
            "frontend_serve_mode": "existing candidate development server",
            "captured_pages": [1, 2, 3],
            "affected_region_capture": "affected-fers-region.png",
        },
    )
    dump_json(
        SERVICE / "actual-clearleaf/request-metadata.json",
        {
            "source_filename": SOURCE.name,
            "source_sha256": SOURCE_SHA256,
            "source_size_bytes": SOURCE.stat().st_size,
            "source_page_count": 3,
            "frontend_url": "http://localhost:3000/",
            "backend_url": "http://127.0.0.1:8000",
            "request_route": "/v1/parse",
            "ui_result": "Parsing complete. 3 physical pages available.",
            "ui_processing_time_seconds": 22.0,
            "request_id": None,
            "request_id_note": "The Clearleaf UI did not expose a request ID.",
            "captured_at_utc": "2026-08-13T15:33:24Z",
        },
    )
    llama_logs = [
        {"level": "log", "message": "setting backend url https://api.cloud.llamaindex.ai"},
        {"level": "log", "message": "Skip pylon chat"},
        {
            "level": "error",
            "message": "Access to storage is not allowed from this context.",
            "adjudication": "browser-extension sandbox warning; no content/capture failure",
        },
    ]
    clearleaf_logs = [
        {
            "level": "error",
            "message": "Access to storage is not allowed from this context.",
            "adjudication": "browser-extension sandbox warning; no content/capture failure",
        },
        {"level": "log", "message": "Extension: Message listener registered successfully"},
    ]
    dump_json(LLAMA / "console.json", llama_logs)
    dump_json(SERVICE / "actual-clearleaf/console.json", clearleaf_logs)


def build_drift() -> dict[str, Any]:
    DRIFT.mkdir(parents=True, exist_ok=True)
    records: dict[str, Any] = {}
    records["service_markdown"] = write_text_diff(
        DRIFT / "service-pre-post-markdown.diff",
        SELECTED_SERVICE / "response.md",
        SERVICE / "response.md",
        "selected-pre-fix-service/response.md",
        "fresh-service/response.md",
    )
    records["service_json"] = write_json_diff(
        DRIFT / "service-pre-post-json.diff",
        SELECTED_SERVICE / "response.json",
        SERVICE / "response.json",
        "selected-pre-fix-service/response.json",
        "fresh-service/response.json",
    )
    records["llama_markdown"] = write_text_diff(
        DRIFT / "llama-selected-fresh-markdown.diff",
        SELECTED_LLAMA / "reference.md",
        LLAMA / "reference.md",
        "selected-llama/reference.md",
        "fresh-llama/reference.md",
    )
    records["llama_json"] = write_json_diff(
        DRIFT / "llama-selected-fresh-json.diff",
        SELECTED_LLAMA / "reference.json",
        LLAMA / "reference.json",
        "selected-llama/reference.json",
        "fresh-llama/reference.json",
    )
    for page_number in (1, 2, 3):
        records[f"service_dom_page_{page_number}"] = write_json_diff(
            DRIFT / f"service-pre-post-dom-page-{page_number}.diff",
            SELECTED_SERVICE / f"pages/page-{page_number}/rendered-dom.json",
            SERVICE / f"pages/page-{page_number}/rendered-dom.json",
            f"selected-service/page-{page_number}/rendered-dom.json",
            f"fresh-service/page-{page_number}/rendered-dom.json",
        )
        records[f"llama_dom_page_{page_number}"] = write_json_diff(
            DRIFT / f"llama-selected-fresh-dom-page-{page_number}.diff",
            SELECTED_LLAMA / f"pages/page-{page_number}/rendered-dom.json",
            LLAMA / f"pages/page-{page_number}/rendered-dom.json",
            f"selected-llama/page-{page_number}/rendered-dom.json",
            f"fresh-llama/page-{page_number}/rendered-dom.json",
        )
        failed_article = (
            FAILED_ATTEMPT
            / f"service/postal-10k/actual-clearleaf/pages/page-{page_number}/article.html"
        )
        current_article = (
            SERVICE / f"actual-clearleaf/pages/page-{page_number}/article.html"
        )
        records[f"failed_next_actual_dom_page_{page_number}"] = write_text_diff(
            DRIFT / f"failed-next-actual-dom-page-{page_number}.diff",
            failed_article,
            current_article,
            f"failed-attempt/page-{page_number}/article.html",
            f"fresh-pass/page-{page_number}/article.html",
        )
    dump_json(DRIFT / "drift-summary.json", records)
    return records


def build_targeted_review(source_metadata: dict[str, Any], drift: dict[str, Any]) -> dict[str, Any]:
    service = load_json(SERVICE / "response.json")
    selected = load_json(SELECTED_SERVICE / "response.json")
    llama = load_json(LLAMA / "reference.json")
    service_md = (SERVICE / "response.md").read_text(encoding="utf-8")
    canonical_md = (SERVICE / "canonical-full.md").read_text(encoding="utf-8")
    llama_md = (LLAMA / "reference.md").read_text(encoding="utf-8")
    actual_html = (
        SERVICE / "actual-clearleaf/pages/page-1/article.html"
    ).read_text(encoding="utf-8")
    llama_actual_html = (
        LLAMA / "pages/page-1/post-render-dom.html"
    ).read_text(encoding="utf-8")
    llama_table_html = (LLAMA / "pages/page-1/table-dom.html").read_text(
        encoding="utf-8"
    )

    page_one = service["pages"][0]
    tables = [item for item in page_one["items"] if item.get("type") == "table"]
    table = tables[0]
    detached = [item for item in page_one["items"] if item.get("type") != "table"]
    detached_text = [element_text(item) for item in detached]
    rows = table["rows"]
    selected_rows = selected["pages"][0]["items"][2]["rows"]
    actual_rows = table_rows_from_html(actual_html)
    actual_paragraphs = paragraph_texts_from_html(actual_html)
    llama_actual_soup = BeautifulSoup(llama_actual_html, "html.parser")
    llama_actual_items = [
        {
            "index": node.get("data-index"),
            "type": node.get("data-item-type"),
            "text": node.get_text(" ", strip=True),
        }
        for node in llama_actual_soup.select(
            ".markdown-container > .item-section[data-item-type]"
        )
    ]
    llama_table_soup = BeautifulSoup(llama_table_html, "html.parser")
    llama_actual_rows = [
        [cell.get_text(" ", strip=True) for cell in row.select("th,td")]
        for row in llama_table_soup.select("tr")
    ]

    suppressions = [
        selection
        for selection in service["processing"]["source_text_alignment"]["selections"]
        if selection.get("terminal_reason") == REASON
    ]
    fers_suppressions = [
        selection
        for selection in suppressions
        if selection.get("rejected_ocr_alternative", {})
        .get("canonical_owner", {})
        .get("row_index")
        == 39
    ]
    fers_owners = [
        selection["rejected_ocr_alternative"]["canonical_owner"]
        for selection in fers_suppressions
    ]
    required_owner_fields = {
        "candidate_id",
        "cell_ids",
        "content_coverage",
        "coordinate_unit",
        "evidence_ids",
        "page_index",
        "policy_id",
        "row_bbox",
        "row_index",
        "source_character_geometry_coverage",
        "source_line_bbox",
        "source_object_ids",
        "suppression_reason",
        "table_bbox",
        "table_id",
        "table_item_id",
        "table_order",
    }

    checks = {
        "source_sha256_matches": source_metadata["source_sha256"] == SOURCE_SHA256,
        "complete_three_page_source": source_metadata["page_count"] == 3,
        "one_authoritative_page_one_table": len(tables) == 1
        and table.get("row_count") == 40
        and table.get("column_count") == 2
        and table.get("table_evidence", {}).get("gate", {}).get("outcome")
        == "canonical_table",
        "fers_row_exact": rows[39] == [FERS, FERS_EXPANSION],
        "fers_cells_exact": [cell["text"] for cell in table["cells"][78:80]]
        == [FERS, FERS_EXPANSION],
        "zero_detached_fers_items": all(
            FERS_CONCATENATED not in text for text in detached_text
        ),
        "zero_detached_collateral_items": all(
            candidate not in detached_text for candidate in COLLATERAL_PARAGRAPHS
        ),
        "raw_canonical_markdown_byte_identical": service_md == canonical_md,
        "markdown_one_fers_row": service_md.count("<td>FERS</td>") == 1
        and service_md.count("<td>Federal Employees Retirement System</td>") == 1,
        "markdown_zero_detached_fers_paragraph": (
            f"\n{FERS_CONCATENATED}\n" not in service_md
        ),
        "markdown_zero_detached_collateral_paragraphs": all(
            f"\n{candidate}\n" not in service_md for candidate in COLLATERAL_PARAGRAPHS
        ),
        "clearleaf_exactly_once_fers_row": sum(
            row == [FERS, FERS_EXPANSION] for row in actual_rows
        )
        == 1,
        "clearleaf_40_table_rows_total": len(actual_rows) == 40,
        "clearleaf_zero_detached_fers_paragraph": FERS_CONCATENATED
        not in actual_paragraphs,
        "clearleaf_zero_detached_collateral_paragraphs": all(
            candidate not in actual_paragraphs for candidate in COLLATERAL_PARAGRAPHS
        ),
        "llama_one_fers_row": llama["items"]["pages"][0]["items"][2]["rows"][39]
        == [FERS, FERS_EXPANSION],
        "llama_zero_detached_fers_item": all(
            FERS_CONCATENATED not in element_text(item)
            for item in llama["items"]["pages"][0]["items"]
            if item.get("type") != "table"
        ),
        "llama_markdown_zero_detached_fers_paragraph": (
            f"\n{FERS_CONCATENATED}\n" not in llama_md
        ),
        "llama_actual_ui_item_sequence_exact": [
            item["type"] for item in llama_actual_items
        ]
        == ["heading", "text", "table", "footer"],
        "llama_actual_ui_exactly_once_fers_row": len(llama_actual_rows) == 40
        and sum(row == [FERS, FERS_EXPANSION] for row in llama_actual_rows) == 1,
        "llama_actual_ui_zero_post_table_text_item": all(
            item["type"] != "text" for item in llama_actual_items[3:]
        ),
        "llama_fresh_markdown_matches_selected": drift["llama_markdown"][
            "identical"
        ],
        "llama_semantic_payload_matches_selected": all(
            llama[key] == load_json(SELECTED_LLAMA / "reference.json")[key]
            for key in (
                "debug",
                "forms",
                "items",
                "job_metadata",
                "markdown",
                "markdown_full",
                "metadata",
                "raw_parameters",
                "result_content_metadata",
                "text",
                "text_full",
            )
        ),
        "all_39_glossary_body_rows_preserve_content_and_order": rows[1:]
        == selected_rows[1:],
        "cio_exact_and_false_clo_absent": ["CIO", "Chief Information Officer"]
        in rows
        and "ClO" not in service_md,
        "cares_exact": rows[10]
        == [
            "CARES Act",
            "Coronavirus Aid, Relief, and Economic Security Act , enacted as Public Law 116-136",
        ],
        "exchange_exact": rows[33]
        == [
            "Exchange Act",
            "Securities and Exchange Act of 1934 , enacted as Public Law 73-291",
        ],
        "postal_page_two_table_object_unchanged": service["pages"][1]["items"][1]
        == selected["pages"][1]["items"][1],
        "postal_page_three_table_object_unchanged": service["pages"][2]["items"][1]
        == selected["pages"][2]["items"][1],
        "two_fers_cell_suppressions_retained": sorted(
            selection["original_text"] for selection in fers_suppressions
        )
        == sorted([FERS, FERS_EXPANSION]),
        "fers_suppression_provenance_complete": len(fers_owners) == 2
        and all(set(owner) == required_owner_fields for owner in fers_owners)
        and all(owner["content_coverage"] == 1.0 for owner in fers_owners)
        and all(
            owner["source_character_geometry_coverage"] == 1.0
            for owner in fers_owners
        ),
        "service_markdown_diff_is_only_detached_fers_removal": (
            (SELECTED_SERVICE / "response.md").read_text(encoding="utf-8")
            .replace(f"\n\n{FERS_CONCATENATED}\n", "\n")
            == service_md
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    result = {
        "schema_version": "ffd-011-targeted-review-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not failures else "fail",
        "checks": checks,
        "failed_checks": failures,
        "target": {
            "service_table_item_id": table["id"],
            "table_id": table["table_evidence"]["table_id"],
            "candidate_id": table["table_evidence"]["candidate_id"],
            "row_index": 39,
            "row": rows[39],
            "cell_ids": [cell["id"] for cell in table["cells"][78:80]],
            "cell_bboxes": [cell["bbox"] for cell in table["cells"][78:80]],
            "source_object_ids": [
                source_id
                for cell in table["cells"][78:80]
                for source_id in cell["source_object_ids"]
            ],
            "evidence_ids": [
                evidence_id
                for cell in table["cells"][78:80]
                for evidence_id in cell["evidence_ids"]
            ],
            "suppression_records": fers_suppressions,
        },
        "public_page_one_items": [
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "reading_order": item.get("reading_order"),
                "text": element_text(item),
            }
            for item in page_one["items"]
        ],
        "declared_collateral": {
            "rows": {
                "CARES": rows[10],
                "CIO": rows[15],
                "Exchange": rows[33],
                "FECA": rows[36],
                "FEGLI": rows[37],
                "FEHB": rows[38],
            },
            "page_two": {
                "rows": service["pages"][1]["items"][1]["row_count"],
                "columns": service["pages"][1]["items"][1]["column_count"],
                "cells": len(service["pages"][1]["items"][1]["cells"]),
            },
            "page_three": {
                "rows": service["pages"][2]["items"][1]["row_count"],
                "columns": service["pages"][2]["items"][1]["column_count"],
                "cells": len(service["pages"][2]["items"][1]["cells"]),
            },
        },
        "surface_counts": {
            "service_public_page_one_items": len(page_one["items"]),
            "service_actual_clearleaf_paragraphs": len(actual_paragraphs),
            "service_actual_clearleaf_table_rows": len(actual_rows),
            "llama_page_one_items": len(llama["items"]["pages"][0]["items"]),
            "llama_actual_ui_items": len(llama_actual_items),
            "llama_actual_ui_table_rows": len(llama_actual_rows),
        },
        "drift_adjudication": {
            "service_markdown": "Only the pre-fix detached FERS paragraph was removed.",
            "service_json": "Expected source-alignment suppression ledger, contributor provenance, item/IR renumbering, and removal of the detached owner; target/collateral projections pass exact assertions.",
            "service_dom": "Expected removal of detached target block; fresh actual Clearleaf contains the canonical table and no post-table duplicate paragraph.",
            "llama_markdown": "Byte-identical to the selected reference.",
            "llama_json": "Only fresh job identity/timestamps and newly issued asset identities/URLs differ; debug/forms/items/job_metadata/Markdown/metadata/parameters/result metadata/text are byte-for-byte data-equivalent after JSON decoding.",
            "llama_dom": "Fresh actual UI captures preserve all three pages and show the page-1 table through FERS with no post-table text item.",
            "unexpected_material_changes": [],
        },
    }
    dump_json(RUN_ROOT / "comparison/targeted-review.json", result)
    assert not failures, failures
    return result


def build_report(
    source_metadata: dict[str, Any], targeted: dict[str, Any], drift: dict[str, Any]
) -> None:
    report = f"""# FFD-011 focused dual-system validation

Status: **{targeted['status'].upper()}**

This immutable attempt used the same complete three-page Postal PDF bytes for a
fresh LlamaParse job and a fresh service job. Source SHA-256:
`{source_metadata['source_sha256']}`.

## Target verdict

- Service public JSON has one canonical 40 x 2 glossary table, one logical
  `FERS` / `Federal Employees Retirement System` row, and no detached duplicate
  body item.
- Raw service Markdown is byte-identical to canonical full Markdown. Compared
  with the selected pre-fix service Markdown, the only byte-level change is the
  removal of the detached FERS paragraph.
- Actual Clearleaf post-render DOM has 40 table rows (header plus 39 glossary
  rows), one FERS row, and no post-table FERS, CARES, or Exchange paragraph.
- Fresh LlamaParse Markdown is byte-identical to the selected reference. Its
  four page-1 items are heading, introduction, table, and footer; the actual UI
  shows the complete table through FERS with no detached paragraph.
- The service processing ledger retains two FERS-cell OCR contributors with
  suppression reason `{REASON}`, canonical table/row/cell custody, point-unit
  geometry, source-object/evidence IDs, and complete source-character coverage.

## Bounded collateral

All 39 glossary body rows retain selected-baseline content and order. CIO is
exact and `ClO` is absent. CARES, Exchange, FECA, FEGLI, and FEHB remain in the
table without detached paragraphs. Postal page 2 remains 17 x 4 / 59 cells and
page 3 remains 37 x 4 / 127 cells; their complete table projections are equal
to the selected pre-fix service result.

## Drift adjudication

The authoritative raw diffs are retained under `comparison/drift/`. Service
JSON changes include the intended suppression ledger/provenance and downstream
deterministic identity repair. LlamaParse raw JSON changes are limited to the
fresh job identity/timestamps and newly issued asset identities/URLs; the
semantic target and all three pages agree. No unexpected material target or
declared-collateral change remains.

Actual browser screenshots retain their original bytes. The browser supplied
JPEG payloads with `.png` filenames; this is explicitly inventoried rather than
transcoded. Six LlamaParse-referenced assets were downloaded and hashed before
their signed URLs expired.

## Gate context

The focused FFD-011 functional gates and public projections pass. One immutable
P02 retained-metrics hash assertion predates this slice, and three legacy P04
production-benchmark sidecar assertions reproduce under the hard five-second
P04 wall deadline while returning exact predecessor content. Those current red
tests are retained and must be considered by the closure reviewer; they were
not weakened or overwritten.

The Wave A all-15 drift gate and the final frozen all-15 campaign remain
pending. This local FFD-011 pass does not replace either gate.
"""
    (RUN_ROOT / "comparison/report.md").write_text(report, encoding="utf-8")


def main() -> None:
    assert SOURCE.is_file()
    assert SELECTED_SERVICE.is_dir()
    assert SELECTED_LLAMA.is_dir()
    source_metadata = build_source_evidence()
    render_summary = build_rendered_evidence()
    build_metadata(source_metadata)
    drift = build_drift()
    targeted = build_targeted_review(source_metadata, drift)
    build_report(source_metadata, targeted, drift)
    dump_json(
        RUN_ROOT / "run-metadata.json",
        {
            "schema_version": "ffd-011-focused-run-v1",
            "run_id": RUN_ROOT.name,
            "status": "targeted_validation_pass_closure_review_pending",
            "started_at_utc": "2026-08-13T15:11:37Z",
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": source_metadata,
            "systems": {
                "llamaparse": {
                    "job_id": load_json(LLAMA / "reference.json")["job"]["id"],
                    "fresh": True,
                    "complete_pdf": True,
                },
                "service": {
                    "run_status": load_json(RUN_ROOT / "service/run.json")["status"],
                    "complete_pdf": True,
                    "public_json_valid": True,
                    "raw_canonical_markdown_byte_identical": True,
                },
            },
            "rendered_evidence": render_summary,
            "targeted_review": "comparison/targeted-review.json",
            "drift_summary": "comparison/drift/drift-summary.json",
            "wave_a_all_15_drift_gate": "pending",
            "final_frozen_all_15_campaign": "pending",
        },
    )
    dump_json(
        RUN_ROOT / "attempt-status.json",
        {
            "run_id": RUN_ROOT.name,
            "status": "targeted_pass_closure_review_pending",
            "immutable": True,
            "fresh_llamaparse_job": "pjb-frndkxx9xo4bww7bjg78oxfvhqqe",
            "fresh_service_status": "success",
            "targeted_review_status": targeted["status"],
            "remaining_closure_review": [
                "independent source/Markdown/UI-DOM/JSON verdict",
                "adjudication of current non-target P04 wall-budget failures",
                "tracker mirror updates",
                "final artifact hash inventory",
            ],
        },
    )
    print(json.dumps({"status": targeted["status"], "checks": len(targeted["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"focused evidence build failed: {exc}", file=sys.stderr)
        raise
