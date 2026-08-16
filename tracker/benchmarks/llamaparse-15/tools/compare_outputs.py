#!/usr/bin/env python3
"""Create reproducible semantic comparison metrics and per-case report drafts."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import pdfplumber


TOKEN_PATTERN = re.compile(r"[^\W_]+(?:[’'][^\W_]+)*|\d+(?:[.,]\d+)*", re.UNICODE)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("\u00ad", "")
    normalized = re.sub(r"[\u2010-\u2015]", "-", normalized)
    return " ".join(normalized.split())


def tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(normalize_text(text))


def compare_text(reference: str, candidate: str) -> dict[str, Any]:
    reference_tokens = tokens(reference)
    candidate_tokens = tokens(candidate)
    reference_counter = Counter(reference_tokens)
    candidate_counter = Counter(candidate_tokens)
    overlap = sum((reference_counter & candidate_counter).values())
    recall = overlap / len(reference_tokens) if reference_tokens else None
    precision = overlap / len(candidate_tokens) if candidate_tokens else None
    if precision is not None and recall is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = None
    missing = reference_counter - candidate_counter
    extra = candidate_counter - reference_counter
    return {
        "reference_chars": len(reference),
        "candidate_chars": len(candidate),
        "reference_tokens": len(reference_tokens),
        "candidate_tokens": len(candidate_tokens),
        "token_multiset_overlap": overlap,
        "token_recall": recall,
        "token_precision": precision,
        "token_f1": f1,
        "normalized_sequence_ratio": SequenceMatcher(
            None, normalize_text(reference), normalize_text(candidate)
        ).ratio(),
        "missing_token_counts": missing.most_common(30),
        "extra_token_counts": extra.most_common(30),
    }


def source_pages(pdf_path: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as document:
        for index, page in enumerate(document.pages, start=1):
            pages.append(
                {
                    "page_number": index,
                    "text": page.extract_text(x_tolerance=2, y_tolerance=3) or "",
                    "width": float(page.width),
                    "height": float(page.height),
                    "unit": "pt",
                }
            )
    return pages


def expert_pages(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return []
    pages = value.get("pages")
    return pages if isinstance(pages, list) else []


def page_markdown_from_our(page: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in page.get("items") or []:
        if not isinstance(item, dict):
            continue
        value = (
            item.get("md")
            or item.get("value")
            or item.get("ocr_text")
            or item.get("caption")
            or ""
        )
        if value:
            blocks.append(str(value).strip())
    return "\n\n".join(blocks)


def top_level_items(pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for page in pages
        if isinstance(page, dict)
        for item in (page.get("items") or [])
        if isinstance(item, dict)
    ]


def item_profile(items: list[dict[str, Any]], *, expert: bool) -> dict[str, Any]:
    types = Counter(str(item.get("type") or "unknown") for item in items)
    bbox_count = 0
    confidence_count = 0
    provenance_count = 0
    concern_count = 0
    table_summaries: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        bbox = item.get("bbox")
        if isinstance(bbox, list):
            boxes = [value for value in bbox if isinstance(value, dict)]
            bbox_count += int(bool(boxes))
            confidence_count += int(
                any(box.get("confidence") is not None for box in boxes)
            )
        elif isinstance(bbox, dict):
            bbox_count += 1
        if item.get("confidence") is not None:
            confidence_count += 1
        if expert:
            provenance_count += int(
                bool(
                    item.get("source")
                    or item.get("provenance")
                    or item.get("source_type")
                )
            )
        else:
            provenance_count += int(
                bool(item.get("source") or item.get("provenance"))
            )
        concerns = item.get("parse_concerns") or []
        concern_count += len(concerns) if isinstance(concerns, list) else 1
        if str(item.get("type") or "").casefold() == "table":
            rows = item.get("rows")
            if isinstance(rows, list):
                row_count = len(rows)
                column_count = max(
                    (
                        len(row)
                        if isinstance(row, list)
                        else len(row.get("cells") or [])
                        if isinstance(row, dict)
                        else 0
                    )
                    for row in rows
                ) if rows else 0
            else:
                row_count = None
                column_count = None
            table_summaries.append(
                {
                    "item_index": index,
                    "row_count": row_count,
                    "column_count": column_count,
                    "has_html": bool(item.get("html")),
                    "has_markdown": bool(item.get("md")),
                    "has_csv": bool(item.get("csv")),
                    "parse_concerns": concerns,
                }
            )
    count = len(items)
    return {
        "item_count": count,
        "type_counts": dict(sorted(types.items())),
        "bbox_coverage": bbox_count / count if count else None,
        "confidence_coverage": confidence_count / count if count else None,
        "provenance_coverage": provenance_count / count if count else None,
        "parse_concern_count": concern_count,
        "tables": table_summaries,
    }


def duplicate_lines(text: str) -> list[dict[str, Any]]:
    lines = [
        normalize_text(line)
        for line in text.splitlines()
        if len(normalize_text(line)) >= 8
    ]
    counts = Counter(lines)
    return [
        {"line": line, "count": count}
        for line, count in counts.most_common()
        if count > 1
    ][:30]


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def report_markdown(metrics: dict[str, Any], run_dir: Path) -> str:
    case_id = metrics["case_id"]
    document = metrics["document"]
    profiles = metrics["item_profiles"]
    comparisons = metrics["text_comparisons"]
    source_ours = comparisons["source_native_proxy_vs_ours"]
    source_expert = comparisons["source_native_proxy_vs_expert"]
    expert_ours = comparisons["expert_vs_ours"]
    lines = [
        f"# {case_id} - Baseline comparison",
        "",
        "Status: Generated metric draft; source-grounded manual findings are maintained in "
        f"[the case report](../../../cases/{case_id}.md).",
        "",
        "## Run identity",
        "",
        f"- Run: `{run_dir.name}`",
        f"- Source: `{document['source_filename']}`",
        f"- Source pages: {document['source_page_count']}",
        f"- Expert Markdown pages: {document['expert_page_count']}",
        f"- Our pages: {document['our_page_count']}",
        f"- Our parse status: `{document['our_status']}`",
        "",
        "## Document-level comparison",
        "",
        "| Measure | Expert | Ours |",
        "|---|---:|---:|",
        f"| Top-level items | {profiles['expert']['item_count']} | {profiles['ours']['item_count']} |",
        f"| Tables | {len(profiles['expert']['tables'])} | {len(profiles['ours']['tables'])} |",
        f"| Bbox coverage | {percent(profiles['expert']['bbox_coverage'])} | {percent(profiles['ours']['bbox_coverage'])} |",
        f"| Confidence coverage | {percent(profiles['expert']['confidence_coverage'])} | {percent(profiles['ours']['confidence_coverage'])} |",
        f"| Provenance coverage | {percent(profiles['expert']['provenance_coverage'])} | {percent(profiles['ours']['provenance_coverage'])} |",
        f"| Parse concerns | {profiles['expert']['parse_concern_count']} | {profiles['ours']['parse_concern_count']} |",
        "",
        "### Text proxy metrics",
        "",
        "These metrics use the PDF native text layer as a diagnostic proxy, not as "
        "authoritative visual ground truth. Damaged mappings, charts, and scanned "
        "regions require the manual source review in the case report.",
        "",
        "| Comparison | Token recall | Token precision | Token F1 | Sequence ratio |",
        "|---|---:|---:|---:|---:|",
        f"| Source-native proxy -> Expert | {percent(source_expert['token_recall'])} | {percent(source_expert['token_precision'])} | {percent(source_expert['token_f1'])} | {percent(source_expert['normalized_sequence_ratio'])} |",
        f"| Source-native proxy -> Ours | {percent(source_ours['token_recall'])} | {percent(source_ours['token_precision'])} | {percent(source_ours['token_f1'])} | {percent(source_ours['normalized_sequence_ratio'])} |",
        f"| Expert -> Ours | {percent(expert_ours['token_recall'])} | {percent(expert_ours['token_precision'])} | {percent(expert_ours['token_f1'])} | {percent(expert_ours['normalized_sequence_ratio'])} |",
        "",
        "## Item types",
        "",
        f"- Expert: `{json.dumps(profiles['expert']['type_counts'], sort_keys=True)}`",
        f"- Ours: `{json.dumps(profiles['ours']['type_counts'], sort_keys=True)}`",
        "",
        "## Page-level metrics",
        "",
        "| Page | Source chars | Expert body chars | Our item Markdown chars | Expert/source token recall | Our/source token recall |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for page in metrics["pages"]:
        lines.append(
            "| {page_number} | {source_chars} | {expert_chars} | {our_chars} | "
            "{expert_recall} | {our_recall} |".format(
                page_number=page["page_number"],
                source_chars=page["source_chars"],
                expert_chars=page["expert_body_chars"],
                our_chars=page["our_item_markdown_chars"],
                expert_recall=percent(
                    page["source_vs_expert"]["token_recall"]
                ),
                our_recall=percent(page["source_vs_ours"]["token_recall"]),
            )
        )
    lines.extend(
        [
            "",
            "## Automated comparison signals",
            "",
            f"- Expert duplicated normalized lines: {len(metrics['duplicates']['expert'])}",
            f"- Our duplicated normalized lines: {len(metrics['duplicates']['ours'])}",
            f"- Our document warnings: `{json.dumps(document['our_warnings'], ensure_ascii=False)}`",
            f"- Expert standalone Markdown equals joined JSON body pages: `{document['expert_standalone_matches_json_body']}`",
            "",
            "## Manual source-grounded findings",
            "",
            "See the linked case report. Automated metrics must not be converted into "
            "gap IDs without checking the rendered source page.",
            "",
        ]
    )
    return "\n".join(lines)


def compare_case(
    corpus_root: Path,
    run_dir: Path,
    case_id: str,
) -> dict[str, Any]:
    source_path = corpus_root / f"{case_id}.pdf"
    expert_json_path = corpus_root / f"{case_id}.json"
    expert_markdown_path = corpus_root / f"{case_id}.md"
    case_dir = run_dir / case_id
    our_json_path = case_dir / "our-output.json"
    diagnostics_path = case_dir / "diagnostics.json"

    expert = load_json(expert_json_path)
    diagnostics = load_json(diagnostics_path)
    ours = load_json(our_json_path) if our_json_path.is_file() else {"pages": []}
    expert_markdown = expert_markdown_path.read_text(encoding="utf-8")
    our_markdown_path = case_dir / "our-output.md"
    our_markdown = (
        our_markdown_path.read_text(encoding="utf-8")
        if our_markdown_path.is_file()
        else ""
    )
    source = source_pages(source_path)
    expert_markdown_pages = expert_pages(expert, "markdown")
    expert_item_pages = expert_pages(expert, "items")
    our_pages = ours.get("pages") or []
    source_text = "\n\n".join(page["text"] for page in source)
    joined_expert_body = "\n\n".join(
        str(page.get("markdown") or "") for page in expert_markdown_pages
    )
    expert_items = top_level_items(expert_item_pages)
    our_items = top_level_items(our_pages)

    page_metrics: list[dict[str, Any]] = []
    for index in range(max(len(source), len(expert_markdown_pages), len(our_pages))):
        source_page = source[index] if index < len(source) else {}
        expert_page = (
            expert_markdown_pages[index]
            if index < len(expert_markdown_pages)
            else {}
        )
        our_page = our_pages[index] if index < len(our_pages) else {}
        source_page_text = str(source_page.get("text") or "")
        expert_page_text = str(expert_page.get("markdown") or "")
        our_page_text = page_markdown_from_our(our_page)
        page_metrics.append(
            {
                "page_number": index + 1,
                "source_chars": len(source_page_text),
                "expert_body_chars": len(expert_page_text),
                "our_item_markdown_chars": len(our_page_text),
                "source_dimensions": {
                    "width": source_page.get("width"),
                    "height": source_page.get("height"),
                    "unit": source_page.get("unit"),
                },
                "expert_success": expert_page.get("success"),
                "our_success": our_page.get("success"),
                "our_dimensions": {
                    "width": our_page.get("page_width"),
                    "height": our_page.get("page_height"),
                    "unit": our_page.get("unit"),
                },
                "source_vs_expert": compare_text(
                    source_page_text, expert_page_text
                ),
                "source_vs_ours": compare_text(source_page_text, our_page_text),
                "expert_vs_ours": compare_text(
                    expert_page_text, our_page_text
                ),
            }
        )

    metrics: dict[str, Any] = {
        "schema_version": "1.0",
        "case_id": case_id,
        "document": {
            "source_filename": source_path.name,
            "source_page_count": len(source),
            "expert_page_count": len(expert_markdown_pages),
            "our_page_count": len(our_pages),
            "our_status": diagnostics.get("status"),
            "our_warnings": ours.get("warnings") or [],
            "expert_standalone_matches_json_body": (
                expert_markdown.strip() == joined_expert_body.strip()
            ),
        },
        "item_profiles": {
            "expert": item_profile(expert_items, expert=True),
            "ours": item_profile(our_items, expert=False),
        },
        "text_comparisons": {
            "source_native_proxy_vs_expert": compare_text(
                source_text, expert_markdown
            ),
            "source_native_proxy_vs_ours": compare_text(
                source_text, our_markdown
            ),
            "expert_vs_ours": compare_text(expert_markdown, our_markdown),
            "expert_json_body_vs_ours": compare_text(
                joined_expert_body, our_markdown
            ),
        },
        "duplicates": {
            "expert": duplicate_lines(expert_markdown),
            "ours": duplicate_lines(our_markdown),
        },
        "pages": page_metrics,
    }
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_root", type=Path)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()

    corpus_root = args.corpus_root.resolve()
    run_dir = args.run_dir.resolve()
    cases = args.cases or sorted(path.stem for path in corpus_root.glob("*.pdf"))
    summary: list[dict[str, Any]] = []
    for case_id in cases:
        case_dir = run_dir / case_id
        metrics = compare_case(corpus_root, run_dir, case_id)
        metrics_path = case_dir / "comparison-metrics.json"
        metrics_path.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (case_dir / "comparison-report.md").write_text(
            report_markdown(metrics, run_dir), encoding="utf-8"
        )
        summary.append(
            {
                "case_id": case_id,
                "source_pages": metrics["document"]["source_page_count"],
                "expert_pages": metrics["document"]["expert_page_count"],
                "our_pages": metrics["document"]["our_page_count"],
                "expert_items": metrics["item_profiles"]["expert"]["item_count"],
                "our_items": metrics["item_profiles"]["ours"]["item_count"],
                "source_proxy_expert_token_f1": metrics["text_comparisons"][
                    "source_native_proxy_vs_expert"
                ]["token_f1"],
                "source_proxy_our_token_f1": metrics["text_comparisons"][
                    "source_native_proxy_vs_ours"
                ]["token_f1"],
                "expert_our_token_f1": metrics["text_comparisons"][
                    "expert_vs_ours"
                ]["token_f1"],
            }
        )
    (run_dir / "comparison-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
