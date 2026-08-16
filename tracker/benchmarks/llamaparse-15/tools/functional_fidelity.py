#!/usr/bin/env python3
"""Deterministic functional-fidelity comparison for the LlamaParse-15 run.

The comparator intentionally operates on retained artifacts only.  It never
calls either parser and it writes only beneath the selected comparison output
directory.  Its projections are schema-aware enough to compare the LlamaParse
reference envelope with this service's public response envelope without
mistaking expected envelope-name differences for content parity.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any, Iterable, Mapping, Sequence
import unicodedata


SCHEMA_VERSION = "functional-fidelity-comparison-v1"
DEFAULT_MATRIX = Path("tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md")
DEFAULT_MANIFEST = Path("tracker/benchmarks/llamaparse-15/manifest.json")
TOKEN_RE = re.compile(r"[^\W_]+(?:[’'][^\W_]+)*|\d+(?:[.,]\d+)*", re.UNICODE)
HEADING_RE = re.compile(r"^( {0,3})(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
LIST_RE = re.compile(r"^( *)([-+*]|\d+[.)])[ \t]+(.+)$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
PIPE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")
AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>]+)>")
VISUAL_CAPTION_RE = re.compile(
    r"\b(?:figure|fig\.?|chart|graph|diagram|flowchart|exhibit)\s*[A-Za-z0-9.-]*",
    re.IGNORECASE,
)
PRINTED_PAGE_RE = re.compile(
    r"\\?<page_number>\s*([^<]+?)\s*\\?</page_number>", re.IGNORECASE
)
SEMANTIC_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "li",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "blockquote",
    "pre", "code", "a", "img", "strong", "em", "hr", "br", "dl", "dt",
    "dd", "figure", "figcaption",
}
LAYOUT_CLASS_RE = re.compile(
    r"^(?:text-(?:left|right|center|justify)|align-(?:top|middle|bottom)|"
    r"(?:m|p)[trblxy]?-[^ ]+|gap-[^ ]+|space-[xy]-[^ ]+|grid(?:-[^ ]+)?|"
    r"flex(?:-[^ ]+)?|items-[^ ]+|justify-[^ ]+|w-[^ ]+|min-w-[^ ]+|"
    r"max-w-[^ ]+|overflow-[xy]-[^ ]+)$"
)


TYPE_FAMILIES = {
    "paragraph": "text",
    "text": "text",
    "title": "heading",
    "section_header": "heading",
    "heading": "heading",
    "list": "list",
    "list_item": "list",
    "table": "table",
    "table_candidate": "table",
    "chart": "chart",
    "graph": "chart",
    "line_chart": "chart",
    "bar_chart": "chart",
    "pie_chart": "chart",
    "diagram": "diagram",
    "flow_chart": "diagram",
    "flowchart": "diagram",
    "image": "image",
    "figure": "image",
    "picture": "image",
    "link": "link",
    "header": "header",
    "footer": "footer",
    # The service exposes these layout roles explicitly while LlamaParse
    # usually serializes the same visible blocks as generic text.  They are
    # one semantic text family for cross-envelope comparison; the raw type
    # names remain in evidence.
    "caption": "text",
    "source_note": "text",
    "footnote": "text",
    "code": "code",
    "code_block": "code",
    "form": "form",
    "key_value": "form",
    "checkbox": "form",
}


CATEGORY_GAPS = {
    "api_parse_failure": "GAP-SERIALIZATION-001",
    "artifact_capture": "GAP-BENCHMARK-002",
    "page_sequence": "GAP-PAGE-001",
    "reading_order": "GAP-ORDER-001",
    "markdown_structure": "GAP-SERIALIZATION-001",
    "heading_hierarchy": "GAP-LIST-001",
    "list_hierarchy": "GAP-LIST-001",
    "links": "GAP-LINK-001",
    "text_integrity": "GAP-TEXT-001",
    "ocr": "GAP-OCR-001",
    "table_detection": "GAP-TABLE-001",
    "table_fidelity": "GAP-TABLE-002",
    "table_presentation": "GAP-TABLE-003",
    "json_structure": "GAP-SERIALIZATION-001",
    "bbox": "GAP-BBOX-001",
    "provenance": "GAP-PROVENANCE-001",
    "chart_detection": "GAP-CHART-001",
    "chart_values": "GAP-CHART-002",
    "diagram": "GAP-DIAGRAM-001",
    "image": "GAP-COVERAGE-001",
    "visual_grounding": "GAP-VISUAL-001",
    "rendered_dom": "GAP-SERIALIZATION-001",
}


ACCEPTANCE_CRITERIA = {
    "api_parse_failure": "Both public output modes return HTTP 200 with valid Markdown/full JSON for every accepted benchmark PDF.",
    "artifact_capture": "The rerun retains raw Markdown, full JSON, and one rendered DOM capture per source page for both systems.",
    "page_sequence": "Physical pages, printed page identities, and page-associated content remain complete and in source order.",
    "reading_order": "Top-level blocks and their text anchors serialize in the same user-visible reading order as the reviewed baseline.",
    "markdown_structure": "Canonical Markdown preserves render-significant block boundaries and syntax without losing or duplicating content.",
    "heading_hierarchy": "Heading levels and section order match the reviewed document hierarchy.",
    "list_hierarchy": "Ordered/unordered list identity, nesting, and item order match the reviewed baseline.",
    "links": "Every baseline link retains its visible text, destination, page association, and order.",
    "text_integrity": "No baseline text token is missing, added, duplicated, truncated, or moved out of reading order beyond an explicitly reviewed exception.",
    "ocr": "Text originating in scans or visual regions is retained with reviewed spelling, Unicode, values, and reading order.",
    "table_detection": "Every reviewed table is emitted once, on the correct page and in the correct document order.",
    "table_fidelity": "Headers, row/column order, every cell value, blank cells, and rowspan/colspan ownership match the reviewed table.",
    "table_presentation": "Raw Markdown, JSON, and rendered DOM expose the same canonical table semantics and user-visible header/body grouping.",
    "json_structure": "Pages and components retain stable types, order, nesting, page association, semantic fields, and canonical serialized content.",
    "bbox": "Components that are spatially grounded in the baseline retain a valid page-relative bounding box.",
    "provenance": "Extracted components retain field-level source/provenance metadata wherever the reviewed baseline exposes it.",
    "chart_detection": "Reviewed charts are detected once, placed on the correct page, and retain axes, series, legends, and labels.",
    "chart_values": "Explicit chart values and labels match the reviewed baseline without inference presented as source fact.",
    "diagram": "Reviewed diagram nodes, containment, connectors, labels, and direction remain ordered and grounded.",
    "image": "Reviewed images/figures are detected once, placed correctly, and retain associated captions or alt text.",
    "visual_grounding": "Visual descriptions and extracted labels are traceable to the correct visual region and do not invent unsupported content.",
    "rendered_dom": "Rendered Markdown preserves semantic tags, text, ordering, grouping, links, emphasis, code, and table structure page by page.",
}


COMPARISON_POLICY = {
    "baseline_role": (
        "LlamaParse is the requested reference baseline, not independent source truth; "
        "a difference can expose a baseline defect rather than a service defect."
    ),
    "json_envelopes": (
        "Exact wire-schema parity is not required. Raw keys, paths, types, and nesting are "
        "inventoried, while functional classification uses normalized page, content, table, "
        "visual, and ordering projections."
    ),
    "component_decomposition": (
        "Type-family and nesting-only differences are reported as acceptable schema differences; "
        "missing/reordered user-visible content is classified independently."
    ),
    "chart_table_polymorphism": (
        "A LlamaParse table item labelled only as chart is compared as a chart visual and excluded "
        "from business-table counts."
    ),
    "page_identity": (
        "Physical page association prefers service page_index; printed page labels are compared "
        "separately against LlamaParse page-number tokens."
    ),
    "ocr_and_visuals": (
        "Non-scanned visual-origin OCR aggregation is a token proxy, not spatial source truth; "
        "proxy-only differences require page-region review."
    ),
    "rendering": (
        "DOM checks compare semantic tags, text, grouping, tables, links, and meaningful layout "
        "tokens. PNG metrics are diagnostic unless viewport, fonts, theme, and renderer match."
    ),
    "surface_independence": (
        "Standalone reference Markdown and page Markdown embedded in LlamaParse JSON can differ; "
        "each surface is compared independently."
    ),
    "out_of_scope": "Latency, CPU, memory, and exhaustive hardening are not measured.",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u00ad", "")
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    return " ".join(text.casefold().split())


def _display_text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _tokens(value: Any) -> list[str]:
    return TOKEN_RE.findall(_normalize_text(value))


def _excerpt(value: Any, limit: int = 240) -> str:
    text = _display_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _duplicate_lines(value: str) -> list[dict[str, Any]]:
    lines = [
        _normalize_text(line)
        for line in value.splitlines()
        if len(_normalize_text(line)) >= 8
    ]
    return [
        {"text": line, "count": count}
        for line, count in Counter(lines).most_common()
        if count > 1
    ]


def _ratio(expected: Sequence[Any], actual: Sequence[Any]) -> float:
    if not expected and not actual:
        return 1.0
    def comparable(value: Any) -> Any:
        if isinstance(value, (Mapping, list, tuple, set)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return value

    return SequenceMatcher(
        None,
        [comparable(value) for value in expected],
        [comparable(value) for value in actual],
    ).ratio()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
        "present": path.is_file(),
    }
    if path.is_file():
        raw = _read_bytes(path)
        result.update({"size_bytes": len(raw), "sha256": _sha256_bytes(raw)})
    return result


def _canonical_type(value: Any) -> str:
    item_type = str(value or "unknown").strip().casefold().replace("-", "_")
    return TYPE_FAMILIES.get(item_type, item_type)


def _item_type(item: Mapping[str, Any]) -> str:
    return str(item.get("type") or item.get("label") or "unknown").casefold()


def _first_content(item: Mapping[str, Any]) -> str:
    for key in ("value", "text", "ocr_text", "caption", "description", "md"):
        value = item.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value)
    if _canonical_type(_item_type(item)) == "table":
        rows = _rows_from_value(item.get("rows"))
        return "\n".join("\t".join(row) for row in rows)
    return ""


def _child_items(item: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children: list[Mapping[str, Any]] = []
    for key in ("items", "children", "content", "contained_items"):
        value = item.get(key)
        if isinstance(value, list):
            children.extend(child for child in value if isinstance(child, Mapping))
    return children


def _physical_page_number(page: Mapping[str, Any], fallback: int) -> int:
    """Return physical order without conflating it with a printed label.

    LlamaParse's ``page_number`` is the physical ordinal.  The service has an
    explicit ``page_index`` and, for documents such as ``ny-timetable``, its
    backward-compatible ``page_number`` may instead contain the printed page
    label.  Physical association therefore prefers ``page_index``.
    """

    return _positive_int(page.get("page_index"), _positive_int(page.get("page_number"), fallback))


def _canonical_page_identity(value: Any) -> str:
    text = _display_text(value)
    text = re.sub(r"\s*/\s*", "/", text)
    text = text.casefold()
    pipe = re.fullmatch(r"page\s*\|\s*([1-9][0-9]{0,5})", text)
    if pipe:
        return pipe.group(1)
    page_of = re.fullmatch(
        r"page\s+([1-9][0-9]{0,5})\s+of\s+([1-9][0-9]{0,5})", text
    )
    if page_of:
        return f"{page_of.group(1)} of {page_of.group(2)}"
    return text


def _printed_page_identities(page: Mapping[str, Any], top: Sequence[Mapping[str, Any]]) -> list[str]:
    identities: list[str] = []

    def add(value: Any) -> None:
        normalized = _canonical_page_identity(value)
        if normalized and normalized not in identities:
            identities.append(normalized)

    page_identity = page.get("page_identity")
    if isinstance(page_identity, Mapping):
        for key in ("visible_text", "display_label", "detected_printed_label", "embedded_label"):
            if page_identity.get(key):
                add(page_identity[key])
                break
    for item, _depth in _walk_items(top):
        content = _first_content(item)
        for match in PRINTED_PAGE_RE.finditer(content):
            add(match.group(1))
        if _canonical_type(_item_type(item)) == "footer":
            for line in content.splitlines():
                candidate = _display_text(line)
                if re.fullmatch(
                    r"(?:[1-9][0-9]{0,5}|[1-9][0-9]{0,5}\s*/\s*[1-9][0-9]{0,5}|"
                    r"Page\s+(?:\|\s*)?[1-9][0-9]{0,5}(?:\s+of\s+[1-9][0-9]{0,5})?)",
                    candidate,
                    re.IGNORECASE,
                ):
                    add(candidate)
    return identities


def _bbox(item: Mapping[str, Any]) -> dict[str, float] | None:
    raw = item.get("bbox")
    boxes = raw if isinstance(raw, list) else [raw]
    for box in boxes:
        if not isinstance(box, Mapping):
            continue
        try:
            x = float(box.get("x", 0))
            y = float(box.get("y", 0))
            width = float(box.get("w", box.get("width", 0)))
            height = float(box.get("h", box.get("height", 0)))
        except (TypeError, ValueError):
            continue
        return {"x": x, "y": y, "w": width, "h": height}
    return None


def _bbox_labels(item: Mapping[str, Any]) -> set[str]:
    raw = item.get("bbox")
    boxes = raw if isinstance(raw, list) else [raw]
    return {
        str(box.get("label")).casefold()
        for box in boxes
        if isinstance(box, Mapping) and box.get("label")
    }


def _rows_from_value(value: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    if not isinstance(value, list):
        return rows
    for row in value:
        if isinstance(row, list):
            cells = row
        elif isinstance(row, Mapping) and isinstance(row.get("cells"), list):
            cells = row["cells"]
        else:
            continue
        rendered: list[str] = []
        for cell in cells:
            if isinstance(cell, Mapping):
                cell = next(
                    (cell.get(k) for k in ("value", "text", "md") if cell.get(k) is not None),
                    "",
                )
            rendered.append(_html_visible_text(str(cell or "")))
        rows.append(rendered)
    return rows


class _VisibleHTMLParser(HTMLParser):
    BLOCKS = {
        "p", "div", "section", "article", "header", "footer", "li", "tr",
        "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "br",
        "table", "thead", "tbody", "tfoot", "ul", "ol", "figure", "figcaption",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self.BLOCKS:
            self.parts.append("\n")
        elif not self.skip_depth and tag in {"td", "th"}:
            self.parts.append("\t")
        elif not self.skip_depth and tag == "img":
            values = dict(attrs)
            self.parts.append(values.get("alt") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def _html_visible_text(value: str) -> str:
    parser = _VisibleHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # malformed retained HTML should still be comparable
        return _display_text(re.sub(r"<[^>]+>", " ", unescape(value)))
    return _display_text(" ".join(parser.parts))


def markdown_visible_text(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = _html_visible_text(text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = AUTOLINK_RE.sub(r"\1", text)
    text = re.sub(r"(?m)^ {0,3}#{1,6}[ \t]+", "", text)
    text = re.sub(r"(?m)^\s*(?:[-+*]|\d+[.)])[ \t]+", "", text)
    text = re.sub(r"(?m)^\s*>[ \t]?", "", text)
    text = re.sub(r"(?m)^\s*(?:`{3,}|~{3,}).*$", "", text)
    text = re.sub(r"[*_~`]", "", text)
    return _display_text(text)


@dataclass
class ParsedTable:
    matrix: list[list[str]] = field(default_factory=list)
    header_row_count: int = 0
    spans: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self, *, page_number: int | None = None, index: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "row_count": len(self.matrix),
            "column_count": max((len(row) for row in self.matrix), default=0),
            "header_row_count": self.header_row_count,
            "matrix": self.matrix,
            "spans": self.spans,
            "normalized_digest": _json_digest(
                [[_normalize_text(cell) for cell in row] for row in self.matrix]
            ),
        }
        if page_number is not None:
            result["page_number"] = page_number
        if index is not None:
            result["table_index"] = index
        return result


class _TableHTMLParser(HTMLParser):
    """Extract tables and an expanded span-aware logical grid."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[ParsedTable] = []
        self.table_depth = 0
        self.in_header = False
        self.current: ParsedTable | None = None
        self.current_row: list[dict[str, Any]] | None = None
        self.current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self.current = ParsedTable()
            return
        if self.table_depth != 1 or self.current is None:
            return
        if tag == "thead":
            self.in_header = True
        elif tag == "tr":
            self.current_row = []
        elif tag in {"th", "td"} and self.current_row is not None:
            self.current_cell = {
                "text": [],
                "header": tag == "th" or self.in_header,
                "rowspan": _positive_int(values.get("rowspan"), 1),
                "colspan": _positive_int(values.get("colspan"), 1),
            }
        elif tag == "br" and self.current_cell is not None:
            self.current_cell["text"].append("\n")
        elif tag == "img" and self.current_cell is not None:
            self.current_cell["text"].append(values.get("alt") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self.table_depth == 1 and self.current is not None:
                self.tables.append(self.current)
                self.current = None
            self.table_depth = max(0, self.table_depth - 1)
            return
        if self.table_depth != 1 or self.current is None:
            return
        if tag in {"th", "td"} and self.current_cell is not None:
            self.current_cell["text"] = _display_text("".join(self.current_cell["text"]))
            assert self.current_row is not None
            self.current_row.append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            _append_expanded_row(self.current, self.current_row)
            if self.current_row and all(cell["header"] for cell in self.current_row):
                self.current.header_row_count += 1
            self.current_row = None
        elif tag == "thead":
            self.in_header = False

    def handle_data(self, data: str) -> None:
        if self.table_depth == 1 and self.current_cell is not None:
            self.current_cell["text"].append(data)


def _positive_int(value: Any, default: int) -> int:
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return default
    return converted if converted > 0 else default


def _append_expanded_row(table: ParsedTable, raw_cells: list[dict[str, Any]]) -> None:
    row_index = len(table.matrix)
    width = max((len(row) for row in table.matrix), default=0)
    row = [""] * width
    occupied: set[int] = set()
    for span in table.spans:
        if span["row"] < row_index < span["row"] + span["rowspan"]:
            for column in range(span["column"], span["column"] + span["colspan"]):
                while len(row) <= column:
                    row.append("")
                row[column] = span["text"]
                occupied.add(column)
    column = 0
    for cell in raw_cells:
        while column in occupied:
            column += 1
        colspan = cell["colspan"]
        rowspan = cell["rowspan"]
        for offset in range(colspan):
            while len(row) <= column + offset:
                row.append("")
            row[column + offset] = cell["text"]
        if colspan > 1 or rowspan > 1:
            table.spans.append(
                {
                    "row": row_index,
                    "column": column,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "header": bool(cell["header"]),
                    "text": cell["text"],
                }
            )
        column += colspan
    table.matrix.append(row)


def _html_tables(value: str) -> list[ParsedTable]:
    parser = _TableHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return parser.tables
    return parser.tables


def _split_pipe_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith(r"\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [_display_text(cell.replace(r"\|", "|")) for cell in cells]


def markdown_tables(markdown: str) -> list[dict[str, Any]]:
    tables = [table.as_dict(index=index) for index, table in enumerate(_html_tables(markdown), 1)]
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or not PIPE_SEPARATOR_RE.match(lines[index + 1]):
            index += 1
            continue
        rows = [_split_pipe_row(lines[index])]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            rows.append(_split_pipe_row(lines[index]))
            index += 1
        parsed = ParsedTable(matrix=rows, header_row_count=1)
        tables.append(parsed.as_dict(index=len(tables) + 1))
    return tables


def _markdown_links(markdown: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for match in LINK_RE.finditer(markdown):
        is_image = markdown[match.start()] == "!"
        links.append(
            {
                "kind": "image" if is_image else "link",
                "text": _display_text(match.group(1)),
                "target": unescape(match.group(2)),
                "offset": match.start(),
            }
        )
    for match in AUTOLINK_RE.finditer(markdown):
        links.append(
            {"kind": "link", "text": match.group(1), "target": match.group(1), "offset": match.start()}
        )
    return sorted(links, key=lambda value: value["offset"])


def markdown_profile(markdown: str) -> dict[str, Any]:
    canonical = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = canonical.split("\n")
    blocks: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    list_items: list[dict[str, Any]] = []
    in_fence: tuple[str, int, str, list[str]] | None = None
    paragraph: list[str] = []
    paragraph_start = 0
    html_table_depth = 0
    html_table_lines: list[str] = []
    html_table_start = 0

    def flush_paragraph(end_line: int) -> None:
        nonlocal paragraph, paragraph_start
        if not paragraph:
            return
        value = _display_text("\n".join(paragraph))
        blocks.append(
            {"kind": "paragraph", "line_start": paragraph_start, "line_end": end_line, "text": _excerpt(value)}
        )
        paragraph = []

    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index]
        if html_table_depth:
            html_table_lines.append(line)
            html_table_depth += len(re.findall(r"<table\b", line, re.I))
            html_table_depth -= len(re.findall(r"</table\s*>", line, re.I))
            if html_table_depth <= 0:
                value = "\n".join(html_table_lines)
                blocks.append(
                    {"kind": "table", "line_start": html_table_start, "line_end": line_number, "text": _excerpt(_html_visible_text(value))}
                )
                html_table_lines = []
                html_table_depth = 0
            index += 1
            continue
        if in_fence is not None:
            fence, start, language, body = in_fence
            if re.match(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$", line):
                blocks.append(
                    {"kind": "code", "line_start": start, "line_end": line_number, "language": language, "text": _excerpt("\n".join(body))}
                )
                in_fence = None
            else:
                body.append(line)
            index += 1
            continue
        fence_match = FENCE_RE.match(line)
        if fence_match:
            flush_paragraph(line_number - 1)
            in_fence = (fence_match.group(1), line_number, fence_match.group(2).strip(), [])
            index += 1
            continue
        if re.search(r"<table\b", line, re.I):
            flush_paragraph(line_number - 1)
            html_table_start = line_number
            html_table_lines = [line]
            html_table_depth = len(re.findall(r"<table\b", line, re.I)) - len(
                re.findall(r"</table\s*>", line, re.I)
            )
            if html_table_depth <= 0:
                blocks.append(
                    {"kind": "table", "line_start": line_number, "line_end": line_number, "text": _excerpt(_html_visible_text(line))}
                )
                html_table_lines = []
            index += 1
            continue
        heading = HEADING_RE.match(line)
        if heading:
            flush_paragraph(line_number - 1)
            record = {"level": len(heading.group(2)), "text": _display_text(heading.group(3)), "line": line_number}
            headings.append(record)
            blocks.append({"kind": "heading", **record})
            index += 1
            continue
        if index + 1 < len(lines) and line.strip() and SETEXT_RE.match(lines[index + 1]):
            flush_paragraph(line_number - 1)
            level = 1 if lines[index + 1].lstrip().startswith("=") else 2
            record = {"level": level, "text": _display_text(line), "line": line_number}
            headings.append(record)
            blocks.append({"kind": "heading", **record})
            index += 2
            continue
        list_match = LIST_RE.match(line)
        if list_match:
            flush_paragraph(line_number - 1)
            marker = list_match.group(2)
            record = {
                "ordered": marker[0].isdigit(),
                "level": len(list_match.group(1).expandtabs(4)) // 2,
                "text": _display_text(list_match.group(3)),
                "line": line_number,
            }
            list_items.append(record)
            blocks.append({"kind": "list_item", **record})
            index += 1
            continue
        if line.lstrip().startswith(">"):
            flush_paragraph(line_number - 1)
            blocks.append(
                {"kind": "blockquote", "line": line_number, "text": _excerpt(re.sub(r"^\s*>\s?", "", line))}
            )
            index += 1
            continue
        if not line.strip():
            flush_paragraph(line_number - 1)
            index += 1
            continue
        if not paragraph:
            paragraph_start = line_number
        paragraph.append(line)
        index += 1
    flush_paragraph(len(lines))
    if in_fence is not None:
        fence, start, language, body = in_fence
        blocks.append(
            {"kind": "unclosed_code", "line_start": start, "line_end": len(lines), "language": language, "text": _excerpt("\n".join(body))}
        )

    links = _markdown_links(markdown)
    blank_runs = [len(match.group(0).splitlines()) for match in re.finditer(r"(?:\n[ \t]*){2,}", canonical)]
    feature_counts = {
        "headings": len(headings),
        "list_items": len(list_items),
        "tables": len(markdown_tables(markdown)),
        "links": sum(link["kind"] == "link" for link in links),
        "images": sum(link["kind"] == "image" for link in links),
        "fenced_code_blocks": sum(block["kind"] in {"code", "unclosed_code"} for block in blocks),
        "strong_markers": len(re.findall(r"(?<!\\)(?:\*\*|__)(?=\S)", markdown)) // 2,
        "emphasis_markers": len(re.findall(r"(?<!\\)(?<!\*)\*(?!\*)|(?<!_)_(?!_)", markdown)) // 2,
        "hard_break_lines": sum(line.endswith("  ") for line in lines),
    }
    return {
        "raw_chars": len(markdown),
        "raw_bytes": len(markdown.encode("utf-8")),
        "raw_sha256": _sha256_bytes(markdown.encode("utf-8")),
        "visible_text": markdown_visible_text(markdown),
        "visible_text_digest": _sha256_bytes(_normalize_text(markdown_visible_text(markdown)).encode("utf-8")),
        "blocks": blocks,
        "block_kinds": [block["kind"] for block in blocks],
        "headings": headings,
        "list_items": list_items,
        "links": [{key: value for key, value in link.items() if key != "offset"} for link in links],
        "tables": markdown_tables(markdown),
        "feature_counts": feature_counts,
        "duplicate_lines": _duplicate_lines(markdown),
        "whitespace": {
            "line_ending": "crlf" if "\r\n" in markdown else "cr" if "\r" in markdown else "lf",
            "final_newline": markdown.endswith(("\n", "\r")),
            "blank_line_runs": blank_runs,
            "max_blank_run": max(blank_runs, default=0),
            "trailing_space_lines": sum(bool(re.search(r"[ \t]+$", line)) for line in lines),
            "tab_count": markdown.count("\t"),
        },
    }


class _SemanticDOMParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict[str, Any]] = []
        self.stack: list[int | None] = []
        self.item_types: list[str] = []
        self.text_events: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "svg"}:
            self.skip_depth += 1
            self.stack.append(None)
            return
        item_type = values.get("data-item-type")
        if item_type:
            self.item_types.append(str(item_type).casefold())
        if self.skip_depth or tag not in SEMANTIC_TAGS:
            self.stack.append(None)
            return
        parent_index = next((index for index in reversed(self.stack) if index is not None), None)
        classes = sorted(
            token
            for token in str(values.get("class") or "").split()
            if LAYOUT_CLASS_RE.match(token)
        )
        record = {
            "tag": tag,
            "depth": sum(value is not None for value in self.stack),
            "parent_tag": self.elements[parent_index]["tag"] if parent_index is not None else None,
            "text_parts": [],
            "attributes": {
                key: values[key]
                for key in ("href", "src", "alt", "rowspan", "colspan", "align", "role")
                if values.get(key) is not None
            },
            "layout_classes": classes,
        }
        self.elements.append(record)
        self.stack.append(len(self.elements) - 1)
        if tag == "img" and values.get("alt"):
            record["text_parts"].append(values["alt"])
            self.text_events.append(values["alt"])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        index = self.stack.pop()
        if tag in {"script", "style", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if index is not None:
            self.elements[index]["text"] = _display_text("".join(self.elements[index].pop("text_parts")))

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if data.strip() and any(index is not None for index in self.stack):
            self.text_events.append(data)
        for index in reversed(self.stack):
            if index is not None:
                self.elements[index]["text_parts"].append(data)


def dom_profile(payload: Mapping[str, Any]) -> dict[str, Any]:
    html = str(payload.get("html") or "")
    parser = _SemanticDOMParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    elements: list[dict[str, Any]] = []
    for element in parser.elements:
        if "text_parts" in element:
            element["text"] = _display_text("".join(element.pop("text_parts")))
        elements.append(element)
    semantic_text = _display_text(" ".join(parser.text_events))
    tags = [element["tag"] for element in elements]
    structural_sequence = [
        {
            "tag": element["tag"],
            "depth": element["depth"],
            "parent_tag": element["parent_tag"],
            "attributes": {
                key: element["attributes"][key]
                for key in ("rowspan", "colspan", "align", "role")
                if key in element["attributes"]
            },
        }
        for element in elements
    ]
    return {
        "page_number": payload.get("page_number"),
        "html_chars": len(html),
        "html_sha256": _sha256_bytes(html.encode("utf-8")),
        "semantic_elements": elements,
        "semantic_tags": tags,
        "structural_sequence": structural_sequence,
        "tag_counts": dict(sorted(Counter(tags).items())),
        "item_types": parser.item_types,
        "semantic_text": semantic_text,
        "headings": [
            {"level": int(element["tag"][1]), "text": element["text"]}
            for element in elements
            if re.fullmatch(r"h[1-6]", element["tag"])
        ],
        "links": [
            {"text": element["text"], "target": element["attributes"].get("href")}
            for element in elements
            if element["tag"] == "a"
        ],
        "images": [
            {"alt": element["attributes"].get("alt"), "src": element["attributes"].get("src")}
            for element in elements
            if element["tag"] == "img"
        ],
        "layout_classes": dict(
            sorted(Counter(token for element in elements for token in element["layout_classes"]).items())
        ),
        "tables": [table.as_dict(index=index) for index, table in enumerate(_html_tables(html), 1)],
    }


def _reference_pages(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = payload.get("items")
    if isinstance(value, Mapping) and isinstance(value.get("pages"), list):
        return [page for page in value["pages"] if isinstance(page, Mapping)]
    return []


def _candidate_pages(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = payload.get("pages")
    if isinstance(value, list):
        return [page for page in value if isinstance(page, Mapping)]
    value = payload.get("items")
    if isinstance(value, Mapping) and isinstance(value.get("pages"), list):
        return [page for page in value["pages"] if isinstance(page, Mapping)]
    return []


def _markdown_pages(payload: Mapping[str, Any], *, reference: bool) -> list[dict[str, Any]]:
    if reference:
        value = payload.get("markdown")
        if isinstance(value, Mapping) and isinstance(value.get("pages"), list):
            return [
                {"page_number": page.get("page_number", index), "markdown": str(page.get("markdown") or "")}
                for index, page in enumerate(value["pages"], 1)
                if isinstance(page, Mapping)
            ]
    pages = _reference_pages(payload) if reference else _candidate_pages(payload)
    result: list[dict[str, Any]] = []
    for index, page in enumerate(pages, 1):
        blocks: list[str] = []
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            value = item.get("md")
            if value is None:
                value = _first_content(item)
            if str(value or "").strip():
                blocks.append(str(value).strip())
        result.append(
            {
                "page_number": _physical_page_number(page, index),
                "printed_page_label": page.get("page_label"),
                "markdown": "\n\n".join(blocks),
            }
        )
    return result


def _walk_items(items: Iterable[Mapping[str, Any]], depth: int = 0) -> Iterable[tuple[Mapping[str, Any], int]]:
    for item in items:
        yield item, depth
        yield from _walk_items(_child_items(item), depth + 1)


def _item_tree(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": _item_type(item),
        "family": _canonical_type(_item_type(item)),
        "children": [_item_tree(child) for child in _child_items(item)],
    }


def _item_profile(pages: list[Mapping[str, Any]]) -> dict[str, Any]:
    top_types: list[str] = []
    top_families: list[str] = []
    page_profiles: list[dict[str, Any]] = []
    all_items: list[tuple[Mapping[str, Any], int, int]] = []
    for page_index, page in enumerate(pages, 1):
        page_number = _physical_page_number(page, page_index)
        top = [item for item in page.get("items") or [] if isinstance(item, Mapping)]
        types = [_item_type(item) for item in top]
        families = [_canonical_type(value) for value in types]
        top_types.extend(types)
        top_families.extend(families)
        walked = list(_walk_items(top))
        all_items.extend((item, depth, page_number) for item, depth in walked)
        reading_orders = [item.get("reading_order") for item in top if item.get("reading_order") is not None]
        printed_page_numbers = _printed_page_identities(page, top)
        monotonic = all(
            isinstance(value, (int, float)) for value in reading_orders
        ) and reading_orders == sorted(reading_orders) and len(reading_orders) == len(set(reading_orders))
        page_profiles.append(
            {
                "page_number": page_number,
                "top_level_type_sequence": types,
                "top_level_family_sequence": families,
                "top_level_item_count": len(top),
                "nested_item_count": len(walked) - len(top),
                "max_nesting_depth": max((depth for _, depth in walked), default=0),
                "reading_order_values": reading_orders,
                "reading_order_monotonic": monotonic if reading_orders else None,
                "content_anchors": [_excerpt(_first_content(item), 120) for item in top],
                "item_trees": [_item_tree(item) for item in top],
                "printed_page_numbers": printed_page_numbers,
                "page_label": page.get("page_label"),
            }
        )
    item_count = len(all_items)
    content_count = sum(bool(_first_content(item)) for item, _, _ in all_items)
    bbox_count = sum(_bbox(item) is not None for item, _, _ in all_items)
    confidence_count = sum(item.get("confidence") is not None for item, _, _ in all_items)
    provenance_count = sum(
        bool(item.get("source") or item.get("provenance") or item.get("source_type"))
        for item, _, _ in all_items
    )
    field_counts = Counter(key for item, _, _ in all_items for key in item)
    return {
        "page_count": len(pages),
        "page_numbers": [_physical_page_number(page, index) for index, page in enumerate(pages, 1)],
        "item_count": item_count,
        "top_level_type_sequence": top_types,
        "top_level_family_sequence": top_families,
        "type_counts": dict(sorted(Counter(top_types).items())),
        "family_counts": dict(sorted(Counter(top_families).items())),
        "field_counts": dict(sorted(field_counts.items())),
        "field_coverage": {
            "content": content_count / item_count if item_count else None,
            "bbox": bbox_count / item_count if item_count else None,
            "confidence": confidence_count / item_count if item_count else None,
            "provenance": provenance_count / item_count if item_count else None,
        },
        "pages": page_profiles,
    }


def _table_profile(pages: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    table_index = 0
    for page_index, page in enumerate(pages, 1):
        page_number = _physical_page_number(page, page_index)
        for item_index, item in enumerate(page.get("items") or [], 1):
            if not isinstance(item, Mapping) or _canonical_type(_item_type(item)) != "table":
                continue
            labels = _bbox_labels(item)
            if "chart" in labels:
                # LlamaParse uses a table-shaped JSON item to expose recovered
                # chart values.  It is compared as a chart visual below, not
                # counted again as a detected business/data table.  Some
                # responses carry both ``chart`` and ``table`` bbox labels;
                # the explicit chart label still owns the region and prevents
                # a duplicate business-table finding.
                continue
            table_index += 1
            logical_rows = _rows_from_value(item.get("rows"))
            html_tables = _html_tables(str(item.get("html") or item.get("md") or ""))
            if html_tables:
                parsed = html_tables[0]
                if not parsed.matrix:
                    parsed.matrix = logical_rows
            else:
                parsed = ParsedTable(matrix=logical_rows)
            record = parsed.as_dict(page_number=page_number, index=table_index)
            record.update(
                {
                    "page_table_index": sum(existing["page_number"] == page_number for existing in result) + 1,
                    "item_index": item_index,
                    "has_rows": isinstance(item.get("rows"), list),
                    "has_markdown": bool(item.get("md")),
                    "has_html": bool(item.get("html")),
                    "has_csv": bool(item.get("csv")),
                    "parse_concerns": item.get("parse_concerns") or [],
                    "logical_rows": logical_rows,
                    "logical_rows_digest": _json_digest(
                        [[_normalize_text(cell) for cell in row] for row in logical_rows]
                    ),
                    "field_sha256": {
                        key: _sha256_bytes(str(item.get(key) or "").encode("utf-8"))
                        for key in ("md", "html", "csv")
                        if item.get(key) is not None
                    },
                }
            )
            result.append(record)
    return result


def _visual_profile(pages: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages, 1):
        page_number = _physical_page_number(page, page_index)
        width = float(page.get("page_width") or page.get("width") or 0)
        height = float(page.get("page_height") or page.get("height") or 0)
        top = [item for item in page.get("items") or [] if isinstance(item, Mapping)]
        for item_index, item in enumerate(top, 1):
            raw_type = _item_type(item)
            family = _canonical_type(raw_type)
            labels = _bbox_labels(item)
            text = _first_content(item)
            inferred: str | None = None
            if family in {"chart", "diagram", "image"}:
                inferred = family
            elif family == "table" and "chart" in labels:
                # LlamaParse commonly represents a chart's recovered values as
                # a table.  It is still one visual model, not an independent
                # caption plus chart plus table.
                inferred = "chart"
            elif labels & {"image", "figure", "chart", "diagram"}:
                inferred = next(iter(sorted(labels & {"image", "figure", "chart", "diagram"})))
                inferred = "image" if inferred == "figure" else inferred
            if inferred is None:
                continue
            box = _bbox(item)
            normalized_box = None
            if box and width > 0 and height > 0:
                normalized_box = {
                    "x": box["x"] / width,
                    "y": box["y"] / height,
                    "w": box["w"] / width,
                    "h": box["h"] / height,
                }
            associated: list[str] = []
            for neighbor in top[max(0, item_index - 2) : min(len(top), item_index + 1)]:
                neighbor_text = _first_content(neighbor)
                if neighbor is not item and (VISUAL_CAPTION_RE.search(neighbor_text) or "caption" in _bbox_labels(neighbor)):
                    associated.append(_excerpt(neighbor_text))
            if inferred == "image":
                associated_text = " ".join(associated).casefold()
                numeric_count = len(re.findall(r"\d+(?:[.,]\d+)?%?", text))
                if "diagram" in associated_text or "flowchart" in associated_text:
                    inferred = "diagram"
                elif (
                    any(word in associated_text for word in ("chart", "graph"))
                    or numeric_count >= 6
                ):
                    inferred = "chart"
            contained_items = [
                {
                    "type": _item_type(child),
                    "text": _first_content(child),
                    "bbox": _bbox(child),
                    "reading_order": child.get("reading_order"),
                }
                for child in (
                    item.get("contained_items")
                    if isinstance(item.get("contained_items"), list)
                    else _child_items(item)
                )
                if isinstance(child, Mapping)
            ]
            relationships = []
            for relationship in item.get("relationships") or []:
                if not isinstance(relationship, Mapping):
                    continue
                relationships.append(
                    {
                        key: relationship.get(key)
                        for key in (
                            "type", "relationship_type", "source_id", "target_id",
                            "from_id", "to_id", "direction", "label", "basis",
                            "relationship_basis",
                        )
                        if relationship.get(key) is not None
                    }
                )
            result.append(
                {
                    "page_number": page_number,
                    "item_index": item_index,
                    "raw_type": raw_type,
                    "kind": inferred,
                    "text": text,
                    "text_excerpt": _excerpt(text, 500),
                    "text_digest": _sha256_bytes(_normalize_text(text).encode("utf-8")),
                    "bbox": box,
                    "normalized_bbox": normalized_box,
                    "associated_captions": associated,
                    "contained_items": contained_items,
                    "relationships": relationships,
                    "topology": {
                        key: item.get(key)
                        for key in ("nodes", "edges", "topology", "diagram_topology")
                        if item.get(key) is not None
                    },
                    "source": item.get("source") or item.get("provenance") or item.get("source_type"),
                }
            )
    return result


def _visual_group_key(visual: Mapping[str, Any]) -> tuple[int, str, str]:
    captions = visual.get("associated_captions") or []
    caption = captions[0] if captions else ""
    if not caption and VISUAL_CAPTION_RE.search(str(visual.get("text") or "")):
        caption = str(visual.get("text") or "")
    return (
        int(visual.get("page_number") or 0),
        str(visual.get("kind") or "unknown"),
        _normalize_text(caption)[:160],
    )


def _ocr_text(pages: list[Mapping[str, Any]], *, whole_document: bool) -> str:
    values: list[str] = []
    for page in pages:
        for item in page.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source") or item.get("source_type") or "").casefold()
            labels = _bbox_labels(item)
            family = _canonical_type(_item_type(item))
            if (
                whole_document
                or "ocr" in source
                or item.get("ocr_text")
                or family in {"image", "chart", "diagram"}
                or bool(labels & {"image", "figure", "chart", "diagram"})
            ):
                value = _first_content(item)
                if value:
                    values.append(value)
    return "\n".join(values)


def json_profile(payload: Mapping[str, Any], *, reference: bool) -> dict[str, Any]:
    pages = _reference_pages(payload) if reference else _candidate_pages(payload)
    schema_types: dict[str, set[str]] = {}

    def visit(value: Any, path: str, depth: int) -> None:
        kind = (
            "null" if value is None else "boolean" if isinstance(value, bool)
            else "integer" if isinstance(value, int) else "number" if isinstance(value, float)
            else "string" if isinstance(value, str) else "object" if isinstance(value, Mapping)
            else "array" if isinstance(value, list) else type(value).__name__
        )
        schema_types.setdefault(path or "$", set()).add(kind)
        if depth >= 5:
            return
        if isinstance(value, Mapping):
            for key, child in value.items():
                visit(child, f"{path}.{key}" if path else str(key), depth + 1)
        elif isinstance(value, list):
            for child in value[:50]:
                visit(child, f"{path}[]", depth + 1)

    visit(payload, "", 0)
    return {
        "top_level_keys": sorted(payload),
        "serialized_chars": len(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        "canonical_sha256": _json_digest(payload),
        "schema_paths": {
            path: sorted(kinds) for path, kinds in sorted(schema_types.items())
        },
        "items": _item_profile(pages),
        "tables": _table_profile(pages),
        "visuals": _visual_profile(pages),
        "markdown_pages": _markdown_pages(payload, reference=reference),
    }


def text_comparison(expected: str, actual: str) -> dict[str, Any]:
    expected_tokens = _tokens(expected)
    actual_tokens = _tokens(actual)
    expected_counter = Counter(expected_tokens)
    actual_counter = Counter(actual_tokens)
    overlap = sum((expected_counter & actual_counter).values())
    recall = overlap / len(expected_tokens) if expected_tokens else (1.0 if not actual_tokens else 0.0)
    precision = overlap / len(actual_tokens) if actual_tokens else (1.0 if not expected_tokens else 0.0)
    f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
    matcher = SequenceMatcher(None, expected_tokens, actual_tokens)
    missing_segments: list[dict[str, Any]] = []
    added_segments: list[dict[str, Any]] = []
    reordered_or_replaced: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"delete", "replace"} and i1 != i2:
            missing_segments.append({"token_start": i1, "token_end": i2, "text": " ".join(expected_tokens[i1:i2])})
        if tag in {"insert", "replace"} and j1 != j2:
            added_segments.append({"token_start": j1, "token_end": j2, "text": " ".join(actual_tokens[j1:j2])})
        if tag == "replace":
            reordered_or_replaced.append(
                {"expected": " ".join(expected_tokens[i1:i2]), "actual": " ".join(actual_tokens[j1:j2])}
            )
    return {
        "expected_chars": len(expected),
        "actual_chars": len(actual),
        "expected_tokens": len(expected_tokens),
        "actual_tokens": len(actual_tokens),
        "token_recall": recall,
        "token_precision": precision,
        "token_f1": f1,
        "token_sequence_ratio": matcher.ratio(),
        "missing_token_counts": [[token, count] for token, count in (expected_counter - actual_counter).most_common()],
        "added_token_counts": [[token, count] for token, count in (actual_counter - expected_counter).most_common()],
        "missing_segments": missing_segments,
        "added_segments": added_segments,
        "replaced_segments": reordered_or_replaced,
        "normalized_exact": _normalize_text(expected) == _normalize_text(actual),
    }


def parse_story_matrix(path: Path) -> dict[str, dict[str, Any]]:
    stories: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return stories
    for line in _read_text(path).splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [
            cell.strip().replace("`", "")
            for cell in line.strip().strip("|").split("|")
        ]
        if len(cells) < 6 or not cells[0].startswith("GAP-"):
            continue
        stories[cells[0]] = {
            "gap_id": cells[0],
            "primary_story": cells[1],
            "secondary_stories": cells[2],
            "story_action": cells[3],
            "dedicated_test_anchor": cells[4],
            "milestone": cells[5],
        }
    return stories


def _story(category: str, stories: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    gap_id = CATEGORY_GAPS[category]
    result = dict(stories.get(gap_id) or {"gap_id": gap_id, "primary_story": "unmapped"})
    result["acceptance_criterion"] = ACCEPTANCE_CRITERIA[category]
    return result


def _stable_issue_id(
    case_id: str, category: str, output_type: str, pages: Sequence[int], fingerprint: Any
) -> str:
    digest = _json_digest(
        {"case": case_id, "category": category, "output": output_type, "pages": list(pages), "fingerprint": fingerprint}
    )[:12]
    return f"FID-{case_id.upper()}-{digest}"


def _issue(
    *,
    case_id: str,
    category: str,
    output_type: str,
    severity: str,
    classification: str,
    pages: Sequence[int],
    summary: str,
    expected: Any,
    actual: Any,
    evidence: Any,
    stories: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    page_list = sorted(
        set(int(page) for page in pages if page is not None and int(page) > 0)
    )
    fingerprint = {"summary": summary, "expected": expected, "actual": actual, "evidence": evidence}
    return {
        "id": _stable_issue_id(case_id, category, output_type, page_list, fingerprint),
        "category": category,
        "output_type": output_type,
        "severity": severity,
        "classification": classification,
        "pages": page_list,
        "summary": summary,
        "expected": expected,
        "actual": actual,
        "evidence": evidence,
        "story": _story(category, stories),
    }


def _severity_for_text(metric: Mapping[str, Any]) -> str:
    floor = min(float(metric["token_recall"]), float(metric["token_precision"]), float(metric["token_sequence_ratio"]))
    if floor < 0.90:
        return "critical"
    if floor < 0.98:
        return "major"
    return "minor"


def _compare_table_lists(
    *,
    case_id: str,
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    output_type: str,
    stories: Mapping[str, Mapping[str, Any]],
    default_page: int = 0,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if len(expected) != len(actual):
        pages = [table.get("page_number", default_page) for table in expected + actual]
        issues.append(
            _issue(
                case_id=case_id,
                category="table_detection",
                output_type=output_type,
                severity="critical" if not actual and expected else "major",
                classification="functional_regression",
                pages=pages,
                summary="Table count or document order differs from LlamaParse.",
                expected={"table_count": len(expected), "page_order": [table.get("page_number") for table in expected]},
                actual={"table_count": len(actual), "page_order": [table.get("page_number") for table in actual]},
                evidence={"expected_digests": [table.get("normalized_digest") for table in expected], "actual_digests": [table.get("normalized_digest") for table in actual]},
                stories=stories,
            )
        )
    for index, (left, right) in enumerate(zip(expected, actual), 1):
        page = int(left.get("page_number") or right.get("page_number") or default_page)
        shape_changed = (
            left.get("row_count"), left.get("column_count"), left.get("header_row_count")
        ) != (
            right.get("row_count"), right.get("column_count"), right.get("header_row_count")
        )
        span_changed = [
            {key: span.get(key) for key in ("row", "column", "rowspan", "colspan", "header", "text")}
            for span in left.get("spans") or []
        ] != [
            {key: span.get(key) for key in ("row", "column", "rowspan", "colspan", "header", "text")}
            for span in right.get("spans") or []
        ]
        left_rows = left.get("matrix") or []
        right_rows = right.get("matrix") or []
        def cell_diff(left_matrix: Sequence[Sequence[Any]], right_matrix: Sequence[Sequence[Any]]) -> list[dict[str, Any]]:
            differences: list[dict[str, Any]] = []
            for row_index in range(max(len(left_matrix), len(right_matrix))):
                left_row = left_matrix[row_index] if row_index < len(left_matrix) else []
                right_row = right_matrix[row_index] if row_index < len(right_matrix) else []
                for column_index in range(max(len(left_row), len(right_row))):
                    expected_cell = left_row[column_index] if column_index < len(left_row) else None
                    actual_cell = right_row[column_index] if column_index < len(right_row) else None
                    if _normalize_text(expected_cell) != _normalize_text(actual_cell):
                        differences.append(
                            {"row": row_index + 1, "column": column_index + 1, "expected": expected_cell, "actual": actual_cell}
                        )
            return differences

        cell_differences = cell_diff(left_rows, right_rows)
        left_logical = left.get("logical_rows") or []
        right_logical = right.get("logical_rows") or []
        logical_cell_differences = cell_diff(left_logical, right_logical)
        logical_shape_changed = (
            len(left_logical), max((len(row) for row in left_logical), default=0)
        ) != (
            len(right_logical), max((len(row) for row in right_logical), default=0)
        )
        left_row_signatures = [_json_digest([_normalize_text(cell) for cell in row]) for row in left_rows]
        right_row_signatures = [_json_digest([_normalize_text(cell) for cell in row]) for row in right_rows]
        reordered_rows = Counter(left_row_signatures) == Counter(right_row_signatures) and left_row_signatures != right_row_signatures
        def column_signatures(rows: Sequence[Sequence[Any]]) -> list[str]:
            width = max((len(row) for row in rows), default=0)
            return [
                _json_digest(
                    [
                        _normalize_text(row[column] if column < len(row) else "")
                        for row in rows
                    ]
                )
                for column in range(width)
            ]

        left_columns = column_signatures(left_rows)
        right_columns = column_signatures(right_rows)
        reordered_columns = (
            Counter(left_columns) == Counter(right_columns)
            and left_columns != right_columns
        )
        if shape_changed or span_changed or cell_differences or logical_shape_changed or logical_cell_differences:
            total_cells = max(sum(len(row) for row in left_rows), 1)
            severity = "critical" if len(cell_differences) / total_cells >= 0.20 else "major"
            issues.append(
                _issue(
                    case_id=case_id,
                    category="table_fidelity" if output_type == "json" else "table_presentation",
                    output_type=output_type,
                    severity=severity,
                    classification="functional_regression",
                    pages=[page],
                    summary=f"Table {index} differs in shape, spans, row order, or cell content.",
                    expected={
                        "row_count": left.get("row_count"), "column_count": left.get("column_count"),
                        "header_row_count": left.get("header_row_count"), "spans": left.get("spans"),
                    },
                    actual={
                        "row_count": right.get("row_count"), "column_count": right.get("column_count"),
                        "header_row_count": right.get("header_row_count"), "spans": right.get("spans"),
                    },
                    evidence={
                        "table_index": index,
                        "shape_changed": shape_changed,
                        "span_changed": span_changed,
                        "row_order_changed": reordered_rows,
                        "column_order_changed": reordered_columns,
                        "cell_difference_count": len(cell_differences),
                        "cell_differences": cell_differences,
                        "logical_shape_changed": logical_shape_changed,
                        "logical_cell_difference_count": len(logical_cell_differences),
                        "logical_cell_differences": logical_cell_differences,
                        "expected_matrix": left_rows,
                        "actual_matrix": right_rows,
                        "expected_logical_rows": left_logical,
                        "actual_logical_rows": right_logical,
                        "expected_field_sha256": left.get("field_sha256"),
                        "actual_field_sha256": right.get("field_sha256"),
                    },
                    stories=stories,
                )
            )
        elif left.get("field_sha256") != right.get("field_sha256") and (
            left.get("field_sha256") or right.get("field_sha256")
        ):
            issues.append(
                _issue(
                    case_id=case_id,
                    category="table_presentation",
                    output_type=output_type,
                    severity="minor",
                    classification="harmless_formatting",
                    pages=[page],
                    summary=f"Table {index} serialized field bytes differ while logical cells and spans match.",
                    expected={"field_sha256": left.get("field_sha256")},
                    actual={"field_sha256": right.get("field_sha256")},
                    evidence={
                        "table_index": index,
                        "logical_rows_equal": True,
                        "expanded_matrix_equal": True,
                        "spans_equal": True,
                    },
                    stories=stories,
                )
            )
    return issues


def _compare_markdown(
    case_id: str,
    expected_markdown: str,
    actual_markdown: str,
    stories: Mapping[str, Mapping[str, Any]],
    *,
    expected_table_pages: Sequence[int] = (),
    actual_table_pages: Sequence[int] = (),
    document_pages: Sequence[int] = (),
    expected_page_markdown: Sequence[str] = (),
    actual_page_markdown: Sequence[str] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expected = markdown_profile(expected_markdown)
    actual = markdown_profile(actual_markdown)
    for index, table in enumerate(expected["tables"]):
        if index < len(expected_table_pages):
            table["page_number"] = int(expected_table_pages[index])
    for index, table in enumerate(actual["tables"]):
        if index < len(actual_table_pages):
            table["page_number"] = int(actual_table_pages[index])
    text_metric = text_comparison(expected["visible_text"], actual["visible_text"])
    issues: list[dict[str, Any]] = []
    page_profiles: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for page_index in range(max(len(expected_page_markdown), len(actual_page_markdown))):
        page_profiles.append(
            (
                markdown_profile(expected_page_markdown[page_index] if page_index < len(expected_page_markdown) else ""),
                markdown_profile(actual_page_markdown[page_index] if page_index < len(actual_page_markdown) else ""),
            )
        )

    def differing_pages(key: str) -> list[int]:
        pages = [
            index
            for index, (left, right) in enumerate(page_profiles, 1)
            if left.get(key) != right.get(key)
        ]
        return pages or list(document_pages)

    if not text_metric["normalized_exact"]:
        issues.append(
            _issue(
                case_id=case_id,
                category="text_integrity",
                output_type="markdown",
                severity=_severity_for_text(text_metric),
                classification="functional_regression",
                pages=[
                    index
                    for index, (left, right) in enumerate(page_profiles, 1)
                    if _normalize_text(left["visible_text"]) != _normalize_text(right["visible_text"])
                ] or document_pages,
                summary="Raw Markdown has missing, added, replaced, duplicated, or reordered visible text.",
                expected={"token_count": text_metric["expected_tokens"], "text_excerpt": _excerpt(expected["visible_text"])},
                actual={"token_count": text_metric["actual_tokens"], "text_excerpt": _excerpt(actual["visible_text"])},
                evidence={
                    **text_metric,
                    "expected_duplicate_lines": expected["duplicate_lines"],
                    "actual_duplicate_lines": actual["duplicate_lines"],
                },
                stories=stories,
            )
        )
    expected_headings = [{"level": row["level"], "text": _normalize_text(row["text"])} for row in expected["headings"]]
    actual_headings = [{"level": row["level"], "text": _normalize_text(row["text"])} for row in actual["headings"]]
    if expected_headings != actual_headings:
        issues.append(
            _issue(
                case_id=case_id, category="heading_hierarchy", output_type="markdown", severity="major",
                classification="functional_regression", pages=differing_pages("headings"),
                summary="Heading text, level, or order differs from LlamaParse.",
                expected=expected["headings"], actual=actual["headings"],
                evidence={"sequence_ratio": _ratio(expected_headings, actual_headings)}, stories=stories,
            )
        )
    expected_lists = [
        {"ordered": row["ordered"], "level": row["level"], "text": _normalize_text(row["text"])}
        for row in expected["list_items"]
    ]
    actual_lists = [
        {"ordered": row["ordered"], "level": row["level"], "text": _normalize_text(row["text"])}
        for row in actual["list_items"]
    ]
    if expected_lists != actual_lists:
        issues.append(
            _issue(
                case_id=case_id, category="list_hierarchy", output_type="markdown", severity="major",
                classification="functional_regression", pages=differing_pages("list_items"), summary="List identity, nesting, text, or order differs.",
                expected=expected["list_items"], actual=actual["list_items"],
                evidence={"sequence_ratio": _ratio(expected_lists, actual_lists)}, stories=stories,
            )
        )
    if expected["links"] != actual["links"]:
        issues.append(
            _issue(
                case_id=case_id, category="links", output_type="markdown", severity="major",
                classification="functional_regression", pages=differing_pages("links"), summary="Markdown links/images differ in text, target, or order.",
                expected=expected["links"], actual=actual["links"], evidence={"expected_count": len(expected["links"]), "actual_count": len(actual["links"])}, stories=stories,
            )
        )
    important_features = ("fenced_code_blocks", "strong_markers", "emphasis_markers")
    feature_diff = {
        key: {"expected": expected["feature_counts"][key], "actual": actual["feature_counts"][key]}
        for key in important_features
        if expected["feature_counts"][key] != actual["feature_counts"][key]
    }
    if feature_diff:
        issues.append(
            _issue(
                case_id=case_id, category="markdown_structure", output_type="markdown", severity="minor",
                classification="functional_regression", pages=differing_pages("feature_counts"), summary="User-visible Markdown emphasis or code syntax differs.",
                expected={key: value["expected"] for key, value in feature_diff.items()},
                actual={key: value["actual"] for key, value in feature_diff.items()}, evidence=feature_diff, stories=stories,
            )
        )
    issues.extend(
        _compare_table_lists(
            case_id=case_id, expected=expected["tables"], actual=actual["tables"],
            output_type="markdown", stories=stories,
        )
    )
    if expected["raw_sha256"] != actual["raw_sha256"] and not issues:
        issues.append(
            _issue(
                case_id=case_id, category="markdown_structure", output_type="markdown", severity="minor",
                classification="harmless_formatting", pages=document_pages,
                summary="Raw Markdown bytes differ, but visible text and parsed semantics are equivalent.",
                expected={"sha256": expected["raw_sha256"], "whitespace": expected["whitespace"]},
                actual={"sha256": actual["raw_sha256"], "whitespace": actual["whitespace"]},
                evidence={"normalized_text_exact": True, "block_kinds_equal": expected["block_kinds"] == actual["block_kinds"]}, stories=stories,
            )
        )
    return {"expected": expected, "actual": actual, "text": text_metric}, issues


def _compare_json(
    case_id: str,
    expected_payload: Mapping[str, Any],
    actual_payload: Mapping[str, Any],
    stories: Mapping[str, Mapping[str, Any]],
    *,
    scanned_candidate: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expected = json_profile(expected_payload, reference=True)
    actual = json_profile(actual_payload, reference=False)
    issues: list[dict[str, Any]] = []
    expected_items = expected["items"]
    actual_items = actual["items"]
    if expected_items["page_numbers"] != actual_items["page_numbers"]:
        issues.append(
            _issue(
                case_id=case_id, category="page_sequence", output_type="json", severity="critical",
                classification="functional_regression", pages=expected_items["page_numbers"] + actual_items["page_numbers"],
                summary="JSON page count, page numbers, or page order differs from LlamaParse.",
                expected=expected_items["page_numbers"], actual=actual_items["page_numbers"],
                evidence={"expected_page_count": expected_items["page_count"], "actual_page_count": actual_items["page_count"]}, stories=stories,
            )
        )
    for page_expected, page_actual in zip(expected_items["pages"], actual_items["pages"]):
        page = int(page_expected["page_number"])
        if (
            page_expected["printed_page_numbers"]
            and page_expected["printed_page_numbers"]
            != page_actual["printed_page_numbers"]
        ):
            issues.append(
                _issue(
                    case_id=case_id, category="page_sequence", output_type="json", severity="major",
                    classification="functional_regression", pages=[page],
                    summary="Printed page identity tokens differ from LlamaParse.",
                    expected={"printed_page_numbers": page_expected["printed_page_numbers"]},
                    actual={
                        "printed_page_numbers": page_actual["printed_page_numbers"],
                        "page_label": page_actual["page_label"],
                    },
                    evidence={
                        "physical_page": page,
                        "expected_page_label": page_expected["page_label"],
                        "actual_page_label": page_actual["page_label"],
                    }, stories=stories,
                )
            )
        if page_expected["top_level_family_sequence"] != page_actual["top_level_family_sequence"]:
            issues.append(
                _issue(
                    case_id=case_id, category="json_structure", output_type="json", severity="minor",
                    classification="acceptable_difference", pages=[page],
                    summary="Cross-envelope component decomposition or taxonomy differs on the page.",
                    expected=page_expected["top_level_family_sequence"], actual=page_actual["top_level_family_sequence"],
                    evidence={
                        "expected_types": page_expected["top_level_type_sequence"],
                        "actual_types": page_actual["top_level_type_sequence"],
                        "sequence_ratio": _ratio(page_expected["top_level_family_sequence"], page_actual["top_level_family_sequence"]),
                        "expected_anchors": page_expected["content_anchors"],
                        "actual_anchors": page_actual["content_anchors"],
                        "wire_schema_parity_required": False,
                        "semantic_content_and_order_compared_separately": True,
                    }, stories=stories,
                )
            )
        elif page_expected["top_level_type_sequence"] != page_actual["top_level_type_sequence"]:
            issues.append(
                _issue(
                    case_id=case_id, category="json_structure", output_type="json", severity="minor",
                    classification="acceptable_difference", pages=[page],
                    summary="Component type names differ but map to the same semantic families and order.",
                    expected=page_expected["top_level_type_sequence"], actual=page_actual["top_level_type_sequence"],
                    evidence={"canonical_families": page_expected["top_level_family_sequence"]}, stories=stories,
                )
            )
        if page_actual["reading_order_monotonic"] is False:
            issues.append(
                _issue(
                    case_id=case_id, category="reading_order", output_type="json", severity="major",
                    classification="functional_regression", pages=[page], summary="Service reading_order values are duplicate or non-monotonic.",
                    expected="strictly increasing unique values", actual=page_actual["reading_order_values"],
                    evidence={"content_anchors": page_actual["content_anchors"]}, stories=stories,
                )
            )
        def family_paths(trees: Sequence[Mapping[str, Any]]) -> list[str]:
            paths: list[str] = []

            def walk(tree: Mapping[str, Any], prefix: str = "") -> None:
                current = f"{prefix}/{tree.get('family')}"
                for child in tree.get("children") or []:
                    paths.append(f"{current}/{child.get('family')}")
                    walk(child, current)

            for tree in trees:
                walk(tree)
            return paths

        expected_paths = family_paths(page_expected["item_trees"])
        actual_paths = family_paths(page_actual["item_trees"])
        missing_paths = list((Counter(expected_paths) - Counter(actual_paths)).elements())
        extra_paths = list((Counter(actual_paths) - Counter(expected_paths)).elements())
        if missing_paths:
            issues.append(
                _issue(
                    case_id=case_id, category="json_structure", output_type="json", severity="minor",
                    classification="acceptable_difference", pages=[page],
                    summary="Cross-envelope nested component decomposition differs from LlamaParse.",
                    expected={"nested_family_paths": expected_paths},
                    actual={"nested_family_paths": actual_paths},
                    evidence={
                        "missing_paths": missing_paths,
                        "extra_paths": extra_paths,
                        "wire_schema_parity_required": False,
                        "semantic_content_and_order_compared_separately": True,
                    }, stories=stories,
                )
            )
        elif extra_paths:
            issues.append(
                _issue(
                    case_id=case_id, category="json_structure", output_type="json", severity="minor",
                    classification="acceptable_difference", pages=[page],
                    summary="Service JSON adds nested component relationships beyond LlamaParse.",
                    expected={"nested_family_paths": expected_paths},
                    actual={"nested_family_paths": actual_paths},
                    evidence={"extra_paths": extra_paths}, stories=stories,
                )
            )
    for field_name, category in (("bbox", "bbox"), ("provenance", "provenance")):
        expected_coverage = expected_items["field_coverage"].get(field_name)
        actual_coverage = actual_items["field_coverage"].get(field_name)
        if (
            expected_coverage is not None and actual_coverage is not None
            and expected_coverage >= 0.50 and actual_coverage + 0.10 < expected_coverage
        ):
            issues.append(
                _issue(
                    case_id=case_id, category=category, output_type="json", severity="major",
                    classification="functional_regression", pages=expected_items["page_numbers"],
                    summary=f"{field_name.title()} field coverage is materially below LlamaParse.",
                    expected={"coverage": expected_coverage}, actual={"coverage": actual_coverage},
                    evidence={"expected_field_counts": expected_items["field_counts"], "actual_field_counts": actual_items["field_counts"]}, stories=stories,
                )
            )
    issues.extend(
        _compare_table_lists(
            case_id=case_id, expected=expected["tables"], actual=actual["tables"], output_type="json", stories=stories
        )
    )
    page_text_metrics: list[dict[str, Any]] = []
    for page_index in range(
        max(len(expected["markdown_pages"]), len(actual["markdown_pages"]))
    ):
        expected_page = (
            expected["markdown_pages"][page_index]
            if page_index < len(expected["markdown_pages"])
            else {"page_number": None, "markdown": ""}
        )
        actual_page = (
            actual["markdown_pages"][page_index]
            if page_index < len(actual["markdown_pages"])
            else {"page_number": None, "markdown": ""}
        )
        physical_page = page_index + 1
        metric = text_comparison(
            markdown_visible_text(expected_page["markdown"]),
            markdown_visible_text(actual_page["markdown"]),
        )
        page_text_metrics.append(
            {
                "physical_page": physical_page,
                "expected_page_number": expected_page["page_number"],
                "actual_page_number": actual_page["page_number"],
                **metric,
            }
        )
        if not metric["normalized_exact"]:
            issues.append(
                _issue(
                    case_id=case_id, category="ocr" if scanned_candidate else "text_integrity",
                    output_type="json", severity=_severity_for_text(metric), classification="functional_regression", pages=[physical_page],
                    summary="Page-associated JSON component content differs from LlamaParse.",
                    expected={
                        "page_number": expected_page["page_number"],
                        "token_count": metric["expected_tokens"],
                        "excerpt": _excerpt(expected_page["markdown"]),
                    },
                    actual={
                        "page_number": actual_page["page_number"],
                        "token_count": metric["actual_tokens"],
                        "excerpt": _excerpt(actual_page["markdown"]),
                    },
                    evidence={
                        "physical_page": physical_page,
                        **metric,
                        "expected_duplicate_lines": _duplicate_lines(expected_page["markdown"]),
                        "actual_duplicate_lines": _duplicate_lines(actual_page["markdown"]),
                    }, stories=stories,
                )
            )
    expected_pages = _reference_pages(expected_payload)
    actual_pages = _candidate_pages(actual_payload)
    expected_ocr = _ocr_text(expected_pages, whole_document=scanned_candidate)
    actual_ocr = _ocr_text(actual_pages, whole_document=scanned_candidate)
    ocr_metric = text_comparison(expected_ocr, actual_ocr)
    if expected_ocr and not ocr_metric["normalized_exact"]:
        issues.append(
            _issue(
                case_id=case_id, category="ocr", output_type="json",
                severity=_severity_for_text(ocr_metric) if scanned_candidate else "minor",
                classification="functional_regression" if scanned_candidate else "review_required",
                pages=expected_items["page_numbers"],
                summary=(
                    "Whole-page OCR text differs from LlamaParse."
                    if scanned_candidate
                    else "Visual-origin text proxy differs and requires region-level review."
                ),
                expected={"token_count": ocr_metric["expected_tokens"], "excerpt": _excerpt(expected_ocr)},
                actual={"token_count": ocr_metric["actual_tokens"], "excerpt": _excerpt(actual_ocr)},
                evidence={
                    **ocr_metric,
                    "automated_proxy": not scanned_candidate,
                    "manual_region_confirmation_required": not scanned_candidate,
                }, stories=stories,
            )
        )
    visual_issues = _compare_visuals(case_id, expected["visuals"], actual["visuals"], stories)
    issues.extend(visual_issues)
    return {
        "expected": expected,
        "actual": actual,
        "page_text": page_text_metrics,
        "ocr_text": ocr_metric,
    }, issues


def _compare_visuals(
    case_id: str,
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    stories: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for kind in ("image", "chart", "diagram"):
        left = [row for row in expected if row["kind"] == kind]
        right = [row for row in actual if row["kind"] == kind]
        left_pages = Counter(int(row["page_number"]) for row in left)
        right_pages = Counter(int(row["page_number"]) for row in right)
        if kind == "image":
            mismatch = any(right_pages[page] < count for page, count in left_pages.items())
        else:
            mismatch = left_pages != right_pages
        if mismatch:
            category = {"image": "image", "chart": "chart_detection", "diagram": "diagram"}[kind]
            issues.append(
                _issue(
                    case_id=case_id, category=category, output_type="json",
                    severity="critical" if left and not right else "major",
                    classification="functional_regression",
                    pages=[row["page_number"] for row in left + right],
                    summary=f"{kind.title()} detection count or page placement differs from LlamaParse.",
                    expected=[{"page": row["page_number"], "type": row["raw_type"], "text": row["text"]} for row in left],
                    actual=[{"page": row["page_number"], "type": row["raw_type"], "text": row["text"]} for row in right],
                    evidence={
                        "expected_count": len(left), "actual_count": len(right),
                        "expected_page_counts": dict(sorted(left_pages.items())),
                        "actual_page_counts": dict(sorted(right_pages.items())),
                    }, stories=stories,
                )
            )
        elif kind == "image" and left_pages != right_pages:
            issues.append(
                _issue(
                    case_id=case_id, category="image", output_type="json", severity="minor",
                    classification="acceptable_difference",
                    pages=[row["page_number"] for row in right],
                    summary="Service emits additional image regions while retaining all LlamaParse image pages.",
                    expected=[{"page": row["page_number"], "type": row["raw_type"], "text": row["text"]} for row in left],
                    actual=[{"page": row["page_number"], "type": row["raw_type"], "text": row["text"]} for row in right],
                    evidence={
                        "expected_page_counts": dict(sorted(left_pages.items())),
                        "actual_page_counts": dict(sorted(right_pages.items())),
                        "review_required": True,
                    }, stories=stories,
                )
            )
        # Pair by page and semantic caption/key before comparing values.  This
        # avoids turning a missing visual near the start into N false shifted
        # value discrepancies later in the document.
        unmatched_actual = list(right)
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for expected_visual in left:
            candidates = [
                row
                for row in unmatched_actual
                if row["page_number"] == expected_visual["page_number"]
            ]
            if not candidates:
                continue
            expected_key = _visual_group_key(expected_visual)
            actual_visual = max(
                candidates,
                key=lambda row: SequenceMatcher(
                    None,
                    expected_key[2] or _normalize_text(expected_visual["text"]),
                    _visual_group_key(row)[2] or _normalize_text(row["text"]),
                ).ratio(),
            )
            unmatched_actual.remove(actual_visual)
            pairs.append((expected_visual, actual_visual))
        for index, (expected_visual, actual_visual) in enumerate(pairs, 1):
            text_metric = text_comparison(expected_visual["text"], actual_visual["text"])
            if expected_visual["text"] and not text_metric["normalized_exact"]:
                category = "chart_values" if kind == "chart" else "visual_grounding"
                issues.append(
                    _issue(
                        case_id=case_id, category=category, output_type="json", severity=_severity_for_text(text_metric),
                        classification="functional_regression", pages=[expected_visual["page_number"], actual_visual["page_number"]],
                        summary=f"{kind.title()} {index} labels, values, description, or caption differ.",
                        expected=expected_visual, actual=actual_visual, evidence=text_metric, stories=stories,
                    )
                )
            caption_metric = text_comparison(
                "\n".join(expected_visual.get("associated_captions") or []),
                "\n".join(actual_visual.get("associated_captions") or []),
            )
            if (
                expected_visual.get("associated_captions")
                and not caption_metric["normalized_exact"]
            ):
                issues.append(
                    _issue(
                        case_id=case_id, category="visual_grounding", output_type="json", severity="major",
                        classification="functional_regression", pages=[expected_visual["page_number"]],
                        summary=f"{kind.title()} {index} associated caption text or ordering differs.",
                        expected=expected_visual.get("associated_captions"),
                        actual=actual_visual.get("associated_captions"),
                        evidence=caption_metric, stories=stories,
                    )
                )
            if kind == "diagram":
                expected_topology = {
                    "contained_items": expected_visual.get("contained_items") or [],
                    "relationships": expected_visual.get("relationships") or [],
                    "topology": expected_visual.get("topology") or {},
                }
                actual_topology = {
                    "contained_items": actual_visual.get("contained_items") or [],
                    "relationships": actual_visual.get("relationships") or [],
                    "topology": actual_visual.get("topology") or {},
                }
                if expected_topology != actual_topology and any(
                    expected_topology.values()
                ):
                    issues.append(
                        _issue(
                            case_id=case_id, category="diagram", output_type="json", severity="major",
                            classification="functional_regression", pages=[expected_visual["page_number"]],
                            summary=f"Diagram {index} nodes, connectors, containment, or direction differ.",
                            expected=expected_topology, actual=actual_topology,
                            evidence={
                                "expected_digest": _json_digest(expected_topology),
                                "actual_digest": _json_digest(actual_topology),
                            }, stories=stories,
                        )
                    )
                elif not any(expected_topology.values()) and any(
                    actual_topology.values()
                ):
                    issues.append(
                        _issue(
                            case_id=case_id, category="diagram", output_type="json", severity="minor",
                            classification="acceptable_difference", pages=[actual_visual["page_number"]],
                            summary=f"Diagram {index} adds topology detail beyond LlamaParse.",
                            expected=expected_topology, actual=actual_topology,
                            evidence={"actual_digest": _json_digest(actual_topology)}, stories=stories,
                        )
                    )
            left_box = expected_visual.get("normalized_bbox")
            right_box = actual_visual.get("normalized_bbox")
            if left_box and right_box:
                distance = max(abs(left_box[key] - right_box[key]) for key in ("x", "y", "w", "h"))
                if distance > 0.15:
                    issues.append(
                        _issue(
                            case_id=case_id, category="visual_grounding", output_type="json", severity="major",
                            classification="functional_regression", pages=[expected_visual["page_number"]],
                            summary=f"{kind.title()} {index} page-relative placement differs materially.",
                            expected=left_box, actual=right_box, evidence={"maximum_normalized_edge_delta": distance}, stories=stories,
                        )
                    )
    return issues


def _dom_files(case_dir: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in sorted(case_dir.glob("pages/page-*/rendered-dom.json")):
        match = re.fullmatch(r"page-(\d+)", path.parent.name)
        if match:
            result[int(match.group(1))] = path
    return result


def _png_dimensions(path: Path) -> dict[str, int] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()[:24]
    if len(raw) == 24 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", raw[16:24])
        return {"width": width, "height": height}
    return None


def _png_comparison(expected: Path, actual: Path) -> dict[str, Any] | None:
    if not expected.is_file() or not actual.is_file():
        return None
    try:
        from PIL import Image, ImageChops, ImageStat

        with Image.open(expected) as expected_image, Image.open(actual) as actual_image:
            left = expected_image.convert("RGB")
            right = actual_image.convert("RGB")
            if left.size != right.size:
                return {
                    "same_dimensions": False,
                    "expected_dimensions": {"width": left.width, "height": left.height},
                    "actual_dimensions": {"width": right.width, "height": right.height},
                }
            difference = ImageChops.difference(left, right)
            extrema = difference.getextrema()
            stat = ImageStat.Stat(difference)
            changed_mask = difference.convert("L").point(lambda value: 255 if value > 8 else 0)
            changed_histogram = changed_mask.histogram()
            changed_pixels = changed_histogram[255]
            total_pixels = left.width * left.height
            return {
                "same_dimensions": True,
                "dimensions": {"width": left.width, "height": left.height},
                "pixel_exact": difference.getbbox() is None,
                "changed_pixel_ratio_over_8": changed_pixels / total_pixels if total_pixels else 0.0,
                "mean_absolute_channel_delta": stat.mean,
                "rms_channel_delta": stat.rms,
                "channel_extrema": extrema,
            }
    except Exception as exc:  # retained-image diagnostics must not abort text evidence
        return {"error_type": type(exc).__name__, "error": str(exc)}


def _compare_dom(
    case_id: str,
    reference_dir: Path,
    candidate_dir: Path,
    stories: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[int]]:
    reference_files = _dom_files(reference_dir)
    candidate_files = _dom_files(candidate_dir)
    issues: list[dict[str, Any]] = []
    missing_pages = sorted(set(reference_files) - set(candidate_files))
    extra_pages = sorted(set(candidate_files) - set(reference_files))
    if missing_pages or extra_pages:
        issues.append(
            _issue(
                case_id=case_id, category="artifact_capture", output_type="rendered_dom", severity="critical",
                classification="evidence_gap", pages=missing_pages + extra_pages,
                summary="Rendered DOM page capture set is incomplete or has unexpected pages.",
                expected=sorted(reference_files), actual=sorted(candidate_files),
                evidence={"missing_candidate_pages": missing_pages, "extra_candidate_pages": extra_pages}, stories=stories,
            )
        )
    expected_profiles: list[dict[str, Any]] = []
    actual_profiles: list[dict[str, Any]] = []
    for page in sorted(set(reference_files) & set(candidate_files)):
        expected_payload = _read_json(reference_files[page])
        actual_payload = _read_json(candidate_files[page])
        expected = dom_profile(expected_payload)
        actual = dom_profile(actual_payload)
        expected_profiles.append(expected)
        actual_profiles.append(actual)
        text_metric = text_comparison(expected["semantic_text"], actual["semantic_text"])
        if not text_metric["normalized_exact"]:
            issues.append(
                _issue(
                    case_id=case_id, category="rendered_dom", output_type="rendered_dom", severity=_severity_for_text(text_metric),
                    classification="functional_regression", pages=[page],
                    summary="Rendered Markdown visible semantic text differs from LlamaParse.",
                    expected={"excerpt": _excerpt(expected["semantic_text"]), "token_count": text_metric["expected_tokens"]},
                    actual={"excerpt": _excerpt(actual["semantic_text"]), "token_count": text_metric["actual_tokens"]},
                    evidence=text_metric, stories=stories,
                )
            )
        if expected["structural_sequence"] != actual["structural_sequence"]:
            issues.append(
                _issue(
                    case_id=case_id, category="rendered_dom", output_type="rendered_dom", severity="major",
                    classification="functional_regression", pages=[page],
                    summary="Rendered semantic tag hierarchy or order differs from LlamaParse.",
                    expected=expected["tag_counts"], actual=actual["tag_counts"],
                    evidence={
                        "expected_tag_sequence": expected["semantic_tags"],
                        "actual_tag_sequence": actual["semantic_tags"],
                        "sequence_ratio": _ratio(expected["structural_sequence"], actual["structural_sequence"]),
                        "expected_structure": expected["structural_sequence"],
                        "actual_structure": actual["structural_sequence"],
                        "expected_headings": expected["headings"], "actual_headings": actual["headings"],
                    }, stories=stories,
                )
            )
        if expected["item_types"] != actual["item_types"]:
            issues.append(
                _issue(
                    case_id=case_id, category="rendered_dom", output_type="rendered_dom", severity="major",
                    classification="functional_regression", pages=[page],
                    summary="Rendered item grouping/type sequence differs from LlamaParse.",
                    expected=expected["item_types"], actual=actual["item_types"],
                    evidence={"sequence_ratio": _ratio(expected["item_types"], actual["item_types"])}, stories=stories,
                )
            )
        issues.extend(
            _compare_table_lists(
                case_id=case_id, expected=expected["tables"], actual=actual["tables"],
                output_type="rendered_dom", stories=stories, default_page=page,
            )
        )
        if expected["links"] != actual["links"]:
            issues.append(
                _issue(
                    case_id=case_id, category="links", output_type="rendered_dom", severity="major",
                    classification="functional_regression", pages=[page], summary="Rendered links differ in text, target, or order.",
                    expected=expected["links"], actual=actual["links"], evidence={"expected_count": len(expected["links"]), "actual_count": len(actual["links"])}, stories=stories,
                )
            )
        expected_alt = [row.get("alt") for row in expected["images"]]
        actual_alt = [row.get("alt") for row in actual["images"]]
        if expected_alt != actual_alt:
            issues.append(
                _issue(
                    case_id=case_id, category="image", output_type="rendered_dom", severity="major",
                    classification="functional_regression", pages=[page],
                    summary="Rendered images differ in count, order, or alternative text.",
                    expected=expected["images"], actual=actual["images"],
                    evidence={"expected_alt_sequence": expected_alt, "actual_alt_sequence": actual_alt}, stories=stories,
                )
            )
        if expected["layout_classes"] != actual["layout_classes"] and (
            expected["structural_sequence"] == actual["structural_sequence"]
            and text_metric["normalized_exact"]
        ):
            issues.append(
                _issue(
                    case_id=case_id, category="rendered_dom", output_type="rendered_dom", severity="minor",
                    classification="harmless_formatting", pages=[page],
                    summary="Layout/spacing class tokens differ while rendered semantics and text match.",
                    expected=expected["layout_classes"], actual=actual["layout_classes"],
                    evidence={"semantic_tags_equal": True, "semantic_text_equal": True}, stories=stories,
                )
            )
    snapshots: list[dict[str, Any]] = []
    for page in sorted(set(reference_files) | set(candidate_files)):
        reference_png = reference_dir / "pages" / f"page-{page}" / "rendered.png"
        candidate_png = candidate_dir / "pages" / f"page-{page}" / "rendered.png"
        snapshots.append(
            {
                "page_number": page,
                "expected": {"present": reference_png.is_file(), "dimensions": _png_dimensions(reference_png), "sha256": _sha256_bytes(reference_png.read_bytes()) if reference_png.is_file() else None},
                "actual": {"present": candidate_png.is_file(), "dimensions": _png_dimensions(candidate_png), "sha256": _sha256_bytes(candidate_png.read_bytes()) if candidate_png.is_file() else None},
                "pixel_comparison": _png_comparison(reference_png, candidate_png),
            }
        )
    return {
        "expected_pages": expected_profiles,
        "actual_pages": actual_profiles,
        "snapshots": snapshots,
    }, issues, missing_pages


def _load_manifest_cases(path: Path) -> dict[str, Mapping[str, Any]]:
    if not path.is_file():
        return {}
    payload = _read_json(path)
    return {
        str(case["case_id"]): case
        for case in payload.get("cases") or []
        if isinstance(case, Mapping) and case.get("case_id")
    }


def _resolve_service_root(run_dir: Path, service_dir: Path | None) -> Path:
    if service_dir is None:
        return (run_dir / "service").resolve()
    if not service_dir.is_absolute() and len(service_dir.parts) == 1:
        return (run_dir / service_dir).resolve()
    return service_dir.resolve()


def _load_reference_roots(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = _read_json(path)
    cases = payload.get("cases") if isinstance(payload, Mapping) else None
    if not isinstance(cases, Mapping):
        raise ValueError("reference selection must contain a cases object")
    roots: dict[str, str] = {}
    for case_id, value in cases.items():
        root = value.get("root") if isinstance(value, Mapping) else value
        if not isinstance(root, str) or not root.strip():
            raise ValueError(f"{case_id}: invalid reference root")
        relative = Path(root)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{case_id}: reference root must stay within the run")
        roots[str(case_id)] = relative.as_posix()
    return roots


def _reference_dir(
    run_dir: Path,
    case_id: str,
    reference_roots: Mapping[str, str],
) -> Path:
    selected = (run_dir / reference_roots.get(case_id, "llamaparse") / case_id).resolve()
    if not selected.is_relative_to(run_dir):
        raise ValueError(f"{case_id}: selected reference escapes the run")
    return selected


def _display_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def _artifact_inventory(
    run_dir: Path,
    service_root: Path,
    case_id: str,
    reference_dir: Path,
) -> dict[str, Any]:
    reference = reference_dir
    candidate = service_root / case_id
    inventory = {
        "reference_markdown": _artifact(reference / "reference.md", run_dir),
        "reference_json": _artifact(reference / "reference.json", run_dir),
        "candidate_markdown": _artifact(candidate / "response.md", run_dir),
        "candidate_json": _artifact(candidate / "response.json", run_dir),
        "reference_dom_pages": sorted(_dom_files(reference)),
        "candidate_dom_pages": sorted(_dom_files(candidate)),
    }
    run_path = service_root / "run.json"
    if run_path.is_file():
        run_payload = _read_json(run_path)
        record = next(
            (
                row
                for row in run_payload.get("cases") or []
                if isinstance(row, Mapping) and row.get("case_id") == case_id
            ),
            None,
        )
        inventory["service_http"] = (record or {}).get("outputs") or {}
    return inventory


def analyze_case(
    run_dir: Path,
    case_id: str,
    *,
    stories: Mapping[str, Mapping[str, Any]],
    manifest_case: Mapping[str, Any] | None = None,
    service_root: Path | None = None,
    reference_dir: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    service_root = _resolve_service_root(run_dir, service_root)
    reference_dir = (reference_dir or run_dir / "llamaparse" / case_id).resolve()
    candidate_dir = service_root / case_id
    inventory = _artifact_inventory(run_dir, service_root, case_id, reference_dir)
    issues: list[dict[str, Any]] = []
    missing_core = [
        key for key in ("reference_markdown", "reference_json", "candidate_markdown", "candidate_json")
        if not inventory[key]["present"]
    ]
    if missing_core:
        expected_page_count = int(
            ((manifest_case or {}).get("source") or {}).get("page_count") or 0
        )
        issues.append(
            _issue(
                case_id=case_id, category="artifact_capture", output_type="capture", severity="critical",
                classification="evidence_gap", pages=range(1, expected_page_count + 1), summary="Required raw comparison artifacts are missing.",
                expected="reference.md, reference.json, response.md, and response.json",
                actual={"missing": missing_core}, evidence=inventory, stories=stories,
            )
        )
    invalid_service_outputs: list[dict[str, Any]] = []
    for output_name in ("json", "markdown"):
        http = (inventory.get("service_http") or {}).get(output_name) or {}
        if http.get("status_code") not in (None, 200):
            invalid_service_outputs.append(
                {
                    "output": output_name,
                    "status_code": http.get("status_code"),
                    "content_type": http.get("content_type"),
                    "sha256": http.get("sha256"),
                }
            )
    if not missing_core and not invalid_service_outputs:
        try:
            candidate_payload = _read_json(candidate_dir / "response.json")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            invalid_service_outputs.append(
                {"output": "json", "error": type(exc).__name__, "message": str(exc)}
            )
        else:
            if not isinstance(candidate_payload, Mapping) or not isinstance(
                candidate_payload.get("pages"), list
            ):
                invalid_service_outputs.append(
                    {
                        "output": "json",
                        "error": "invalid_parse_response",
                        "top_level_keys": sorted(candidate_payload)
                        if isinstance(candidate_payload, Mapping)
                        else None,
                    }
                )
    if invalid_service_outputs:
        manifest_page_count = int(
            ((manifest_case or {}).get("source") or {}).get("page_count") or 0
        )
        error_evidence: dict[str, Any] = {
            "outputs": invalid_service_outputs,
            "service_http": inventory.get("service_http") or {},
        }
        response_path = candidate_dir / "response.json"
        if response_path.is_file():
            error_evidence["response_excerpt"] = _excerpt(_read_text(response_path), 500)
        issues.append(
            _issue(
                case_id=case_id, category="api_parse_failure", output_type="service_api", severity="critical",
                classification="functional_regression", pages=range(1, manifest_page_count + 1),
                summary="The public parse API did not return successful, valid Markdown and JSON outputs.",
                expected={"json_status": 200, "markdown_status": 200, "json_pages": "array"},
                actual=invalid_service_outputs, evidence=error_evidence, stories=stories,
            )
        )
    metrics: dict[str, Any] = {}
    if not missing_core and not invalid_service_outputs:
        expected_markdown = _read_text(reference_dir / "reference.md")
        actual_markdown = _read_text(candidate_dir / "response.md")
        expected_json = _read_json(reference_dir / "reference.json")
        actual_json = _read_json(candidate_dir / "response.json")
        expected_table_pages = [
            int(table["page_number"])
            for table in _table_profile(_reference_pages(expected_json))
        ]
        actual_table_pages = [
            int(table["page_number"])
            for table in _table_profile(_candidate_pages(actual_json))
        ]
        document_pages = list(
            range(
                1,
                max(
                    len(_reference_pages(expected_json)),
                    len(_candidate_pages(actual_json)),
                )
                + 1,
            )
        )
        expected_page_markdown = [
            row["markdown"]
            for row in _markdown_pages(expected_json, reference=True)
        ]
        actual_page_markdown = [
            row["markdown"]
            for row in _markdown_pages(actual_json, reference=False)
        ]
        markdown_metrics, markdown_issues = _compare_markdown(
            case_id,
            expected_markdown,
            actual_markdown,
            stories,
            expected_table_pages=expected_table_pages,
            actual_table_pages=actual_table_pages,
            document_pages=document_pages,
            expected_page_markdown=expected_page_markdown,
            actual_page_markdown=actual_page_markdown,
        )
        metrics["markdown"] = markdown_metrics
        issues.extend(markdown_issues)
        scanned_candidate = bool(((manifest_case or {}).get("source") or {}).get("scanned_candidate"))
        json_metrics, json_issues = _compare_json(
            case_id, expected_json, actual_json, stories, scanned_candidate=scanned_candidate
        )
        metrics["json"] = json_metrics
        issues.extend(json_issues)
    dom_metrics, dom_issues, missing_dom_pages = _compare_dom(
        case_id, reference_dir, candidate_dir, stories
    )
    metrics["rendered_dom"] = dom_metrics
    issues.extend(dom_issues)
    evidence_gaps = [issue for issue in issues if issue["classification"] == "evidence_gap"]
    functional = [issue for issue in issues if issue["classification"] == "functional_regression"]
    review_required = [issue for issue in issues if issue["classification"] == "review_required"]
    accepted = [
        issue for issue in issues
        if issue["classification"] in {"acceptable_difference", "harmless_formatting"}
    ]
    if functional or review_required:
        status = "discrepancy_found"
    elif evidence_gaps:
        status = "pending"
    elif accepted:
        status = "acceptable_difference"
    else:
        status = "match"
    source_context = {
        "document_category": (manifest_case or {}).get("document_category"),
        "layout_characteristics": (manifest_case or {}).get("layout_characteristics") or [],
        "known_complex_elements": (manifest_case or {}).get("known_complex_elements") or [],
        "source_page_count": ((manifest_case or {}).get("source") or {}).get("page_count"),
        "scanned_candidate": bool(((manifest_case or {}).get("source") or {}).get("scanned_candidate")),
        "mixed_native_and_scanned_candidate": bool(
            ((manifest_case or {}).get("source") or {}).get("mixed_native_and_scanned_candidate")
        ),
    }
    counts = Counter(issue["severity"] for issue in issues)
    source_page_count = (
        int(source_context["source_page_count"])
        if source_context["source_page_count"] is not None
        else max(
            inventory["reference_dom_pages"] + inventory["candidate_dom_pages"] + [0]
        )
    )
    page_results: list[dict[str, Any]] = []
    json_page_metrics = {
        int(row["physical_page"]): row
        for row in metrics.get("json", {}).get("page_text", [])
    }
    for page in range(1, source_page_count + 1):
        page_issues = [issue for issue in issues if page in issue["pages"]]
        page_results.append(
            {
                "physical_page": page,
                "status": (
                    "discrepancy_found"
                    if any(
                        issue["classification"] in {"functional_regression", "review_required"}
                        for issue in page_issues
                    )
                    else "pending"
                    if any(issue["classification"] == "evidence_gap" for issue in page_issues)
                    else "acceptable_difference"
                    if page_issues
                    else "match"
                ),
                "json_text_metrics": json_page_metrics.get(page),
                "reference_dom_captured": page in inventory["reference_dom_pages"],
                "candidate_dom_captured": page in inventory["candidate_dom_pages"],
                "discrepancy_ids": [issue["id"] for issue in page_issues],
                "severity_counts": dict(
                    sorted(Counter(issue["severity"] for issue in page_issues).items())
                ),
            }
        )
    reproduction_command = (
        "python3 tracker/benchmarks/llamaparse-15/tools/functional_fidelity.py "
        f"{run_dir.as_posix()} --service-dir {service_root.as_posix()} --cases {case_id}"
    )
    if reference_dir.parent.name != "llamaparse":
        reproduction_command += " --reference-selection <retained-reference-selection.json>"
    for issue_index, issue in enumerate(issues):
        issue["reproduce"] = {
            "command": reproduction_command,
            "json_pointer": f"/discrepancies/{issue_index}",
            "artifact_paths": {
                key: value["path"]
                for key, value in inventory.items()
                if isinstance(value, Mapping) and value.get("path")
            },
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "status": status,
        "release_ready": not evidence_gaps and not functional and not review_required,
        "source_context": source_context,
        "artifact_inventory": inventory,
        "summary": {
            "discrepancy_count": len(issues),
            "functional_regressions": len(functional),
            "acceptable_or_harmless_differences": len(accepted),
            "evidence_gaps": len(evidence_gaps),
            "review_required": len(review_required),
            "severity_counts": {key: counts.get(key, 0) for key in ("critical", "major", "minor")},
            "missing_rendered_dom_pages": missing_dom_pages,
        },
        "metrics": metrics,
        "page_results": page_results,
        "discrepancies": issues,
        "reproduce": {
            "command": reproduction_command,
            "reference_root": _display_path(reference_dir, run_dir),
            "candidate_root": _display_path(candidate_dir, run_dir),
        },
    }


def _apply_resolution_ledger(
    result: dict[str, Any], ledger_case: Mapping[str, Any] | None
) -> None:
    """Attach a resolution only when a hash-bound ledger proves prior gaps.

    A manual "fixed" label is not accepted.  The ledger must list at least one
    prior discrepancy and bind all four current raw artifact SHA-256 values.
    Unrelated current discrepancies keep the case open.
    """
    if not ledger_case:
        return
    prior = ledger_case.get("prior_discrepancy_ids")
    hashes = ledger_case.get("validated_artifact_sha256")
    if not isinstance(prior, list) or not prior or not isinstance(hashes, Mapping):
        return
    inventory = result["artifact_inventory"]
    required = ("reference_markdown", "reference_json", "candidate_markdown", "candidate_json")
    if all(hashes.get(key) == inventory[key].get("sha256") for key in required):
        result["resolution_evidence"] = {
            "prior_discrepancy_ids": prior,
            "validated_artifact_sha256": dict(hashes),
            "code_changes": ledger_case.get("code_changes") or [],
            "validation": ledger_case.get("validation") or [],
            "resolved_discrepancies": ledger_case.get("resolved_discrepancies") or [],
            "validation_scope": ledger_case.get("validation_scope"),
            "remaining_evidence": ledger_case.get("remaining_evidence") or [],
        }
        result["summary"]["resolved_discrepancies"] = len(prior)
        if result["status"] in {"match", "acceptable_difference"}:
            result["status"] = "fixed"


def _report(summary: Mapping[str, Any], run_dir: Path, matrix_path: Path) -> str:
    cases = summary["cases"]
    lines = [
        "# LlamaParse-15 functional-fidelity comparison",
        "",
        f"Run: `{run_dir.name}`  ",
        f"Candidate artifacts: `{summary['service_root']}`  ",
        f"Analyzer schema: `{SCHEMA_VERSION}`  ",
        f"Story mapping: `{matrix_path.as_posix()}`",
        f"Reference selection: `{(summary.get('reference_selection') or {}).get('path') or 'default llamaparse batch'}`",
        "",
        "This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.",
        "",
        "Finding totals are conservative counts of reproducible discrepancy signals, not counts of unique root causes. A missing or regrouped item can create correlated Markdown, JSON, table, visual, and DOM signals. The source-grounded adjudication ledgers must be consulted before treating signals as separate production defects or forcing parity with model-generated, inferred, or source-contradicted baseline content.",
        "",
        "## Release readiness",
        "",
        f"**{'READY' if summary['release_ready'] else 'NOT READY'}** — {summary['functional_regressions']} functional regression(s), "
        f"{summary['review_required']} manual-review signal(s), {summary['evidence_gaps']} evidence gap(s), "
        f"{summary['acceptable_or_harmless_differences']} accepted/harmless difference(s), "
        f"and {summary.get('resolved_discrepancies', 0)} hash-validated resolved discrepancy/discrepancies.",
        "",
        "A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun. A hash-bound prior issue may be resolved while unrelated current findings keep the PDF at `discrepancy_found`.",
        "",
        "## Per-PDF status",
        "",
        "| PDF | Status | Critical | Major | Minor | Functional | Review | Evidence gaps | Evidence |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for case in cases:
        counts = case["summary"]["severity_counts"]
        lines.append(
            f"| `{case['case_id']}.pdf` | **{case['status']}** | {counts['critical']} | {counts['major']} | {counts['minor']} | "
            f"{case['summary']['functional_regressions']} | {case['summary']['review_required']} | "
            f"{case['summary']['evidence_gaps']} | "
            f"[`evidence.json`]({case['case_id']}/evidence.json) |"
        )
    lines.extend(["", "## Findings", ""])
    for case in cases:
        lines.extend([f"### {case['case_id']}", "", f"Status: **{case['status']}**", ""])
        lines.extend(
            [
                "| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |",
                "|---:|---|---:|---:|---:|---|---|---:|",
            ]
        )
        for page in case["page_results"]:
            metric = page.get("json_text_metrics") or {}
            percent = lambda value: "n/a" if value is None else f"{float(value) * 100:.2f}%"
            lines.append(
                f"| {page['physical_page']} | {page['status']} | {percent(metric.get('token_recall'))} | "
                f"{percent(metric.get('token_precision'))} | {percent(metric.get('token_sequence_ratio'))} | "
                f"{'yes' if page['reference_dom_captured'] else 'no'} | {'yes' if page['candidate_dom_captured'] else 'no'} | "
                f"{len(page['discrepancy_ids'])} |"
            )
        lines.append("")
        if case.get("resolution_evidence"):
            resolution = case["resolution_evidence"]
            lines.extend(
                [
                    "Resolved discrepancy evidence:",
                    "",
                    f"- Prior IDs: `{', '.join(resolution['prior_discrepancy_ids'])}`",
                    f"- Code changes: `{json.dumps(resolution.get('code_changes') or [], ensure_ascii=False)}`",
                    f"- Validation: `{json.dumps(resolution.get('validation') or [], ensure_ascii=False)}`",
                    f"- Validation scope: `{resolution.get('validation_scope') or 'not specified'}`",
                    f"- Remaining evidence: `{json.dumps(resolution.get('remaining_evidence') or [], ensure_ascii=False)}`",
                    "- Current raw artifacts are bound by SHA-256 in the case evidence.",
                    "",
                ]
            )
        if not case["discrepancies"]:
            lines.extend(["No functional or user-visible difference was detected by the deterministic projections.", ""])
            continue
        for issue in case["discrepancies"]:
            page_text = ", ".join(str(page) for page in issue["pages"]) or "document"
            story = issue["story"]
            lines.extend(
                [
                    f"- `{issue['id']}` — **{issue['severity']} / {issue['classification']}** — {issue['output_type']}, page(s) {page_text}: {issue['summary']} "
                    f"Owner: `{story.get('gap_id')}` / `{story.get('primary_story')}`; test: `{story.get('dedicated_test_anchor', 'unmapped')}`.",
                ]
            )
        lines.append("")
    lines.extend(
        [
            "## Comparison policy and limitations",
            "",
            "- **Signal counting:** Counts are intentionally conservative and may correlate across output surfaces or cascade after an unmatched table/visual. They are not a count of independently confirmed defects.",
            "- **JSON text scope:** LlamaParse page Markdown and the service all-item page projection are not perfectly symmetric; text metrics are diagnostic and require source-page review.",
            "- **Visual matching:** Baseline visual bboxes/fragments can represent generated descriptions or multiple regions for one source visual, while the service can group or refine them differently. Geometry/type-count signals therefore require source adjudication.",
            "- **Table matching:** Tables are paired in page order. One missing or baseline chart-as-table item can cascade later pairwise differences; chart-labelled table-shaped baseline items are compared as visuals instead of physical tables.",
            "- **Authority:** The hash-bound source PDF is authoritative. Baseline prose, inferred chart values, unsupported links, and source-contradicted structure are recorded as accepted differences rather than parity targets.",
            "",
            *[
                f"- **{key.replace('_', ' ').title()}:** {value}"
                for key, value in summary["comparison_policy"].items()
            ],
            "",
            "## Validation and resolution rule",
            "",
            "Each machine-readable discrepancy contains the expected LlamaParse projection, actual service projection, page/output type, complete table cell evidence where applicable, severity, story owner, acceptance criterion, and a stable reproduction command. Unit-test success alone is insufficient: resolved cases must retain fresh raw Markdown, JSON, rendered DOM, and snapshot evidence. The optional resolution ledger can label a clean case `fixed` only when it binds the current four raw artifact hashes and identifies prior discrepancy IDs.",
            "",
        ]
    )
    return "\n".join(lines)


def analyze_run(
    run_dir: Path,
    *,
    output_dir: Path | None = None,
    service_dir: Path | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
    matrix_path: Path = DEFAULT_MATRIX,
    cases: Sequence[str] | None = None,
    resolution_ledger: Path | None = None,
    reference_selection: Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    service_root = _resolve_service_root(run_dir, service_dir)
    reference_roots = _load_reference_roots(reference_selection)
    output_dir = (output_dir or run_dir / "comparison").resolve()
    for protected in ((run_dir / "llamaparse").resolve(), service_root):
        if output_dir == protected.resolve() or protected.resolve() in output_dir.parents:
            raise ValueError("comparison output must not be inside immutable parser artifact roots")
    stories = parse_story_matrix(matrix_path)
    manifest_cases = _load_manifest_cases(manifest_path)
    selected = list(cases or sorted(set(manifest_cases) or {path.name for path in (run_dir / "llamaparse").iterdir() if path.is_dir()}))
    ledger: Mapping[str, Any] = {}
    if resolution_ledger and resolution_ledger.is_file():
        payload = _read_json(resolution_ledger)
        ledger = payload.get("cases") or {}
    results: list[dict[str, Any]] = []
    for case_id in selected:
        result = analyze_case(
            run_dir,
            case_id,
            stories=stories,
            manifest_case=manifest_cases.get(case_id),
            service_root=service_root,
            reference_dir=_reference_dir(run_dir, case_id, reference_roots),
        )
        _apply_resolution_ledger(result, ledger.get(case_id) if isinstance(ledger, Mapping) else None)
        results.append(result)
    functional = sum(case["summary"]["functional_regressions"] for case in results)
    evidence_gaps = sum(case["summary"]["evidence_gaps"] for case in results)
    accepted = sum(case["summary"]["acceptable_or_harmless_differences"] for case in results)
    review_required = sum(case["summary"]["review_required"] for case in results)
    resolved = sum(case["summary"].get("resolved_discrepancies", 0) for case in results)
    status_counts = Counter(case["status"] for case in results)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "service_root": _display_path(service_root, run_dir),
        "case_count": len(results),
        "release_ready": bool(results) and not functional and not review_required and not evidence_gaps,
        "functional_regressions": functional,
        "review_required": review_required,
        "evidence_gaps": evidence_gaps,
        "acceptable_or_harmless_differences": accepted,
        "resolved_discrepancies": resolved,
        "status_counts": {status: status_counts.get(status, 0) for status in ("match", "acceptable_difference", "discrepancy_found", "fixed", "pending")},
        "story_matrix": {
            "path": matrix_path.as_posix(),
            "sha256": _sha256_bytes(matrix_path.read_bytes()) if matrix_path.is_file() else None,
            "mapped_gap_count": len(stories),
        },
        "comparison_policy": COMPARISON_POLICY,
        "reference_selection": {
            "path": reference_selection.as_posix() if reference_selection else None,
            "sha256": (
                _sha256_bytes(reference_selection.read_bytes())
                if reference_selection and reference_selection.is_file()
                else None
            ),
            "overrides": reference_roots,
        },
        "cases": results,
    }
    if write:
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in results:
            case_dir = output_dir / result["case_id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "evidence.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        machine_summary = dict(summary)
        machine_summary["cases"] = [
            {
                "case_id": case["case_id"], "status": case["status"],
                "release_ready": case["release_ready"], "summary": case["summary"],
                "evidence_path": f"{case['case_id']}/evidence.json",
            }
            for case in results
        ]
        (output_dir / "summary.json").write_text(
            json.dumps(machine_summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (output_dir / "report.md").write_text(
            _report(summary, run_dir, matrix_path), encoding="utf-8"
        )
    return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare retained LlamaParse and service functional-fidelity artifacts."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--service-dir",
        type=Path,
        help=(
            "Candidate artifact root. A bare name is resolved beneath RUN_DIR; "
            "other relative paths are resolved from the current directory."
        ),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--story-matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--resolution-ledger", type=Path)
    parser.add_argument(
        "--reference-selection",
        type=Path,
        help="JSON mapping case IDs to immutable reference artifact roots within RUN_DIR.",
    )
    parser.add_argument("--cases", nargs="+")
    parser.add_argument(
        "--fail-on-discrepancy", action="store_true",
        help="Exit 1 when any functional regression or evidence gap remains.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = analyze_run(
        args.run_dir,
        output_dir=args.output_dir,
        service_dir=args.service_dir,
        manifest_path=args.manifest,
        matrix_path=args.story_matrix,
        cases=args.cases,
        resolution_ledger=args.resolution_ledger,
        reference_selection=args.reference_selection,
    )
    print(
        json.dumps(
            {
                "run_id": summary["run_id"],
                "case_count": summary["case_count"],
                "release_ready": summary["release_ready"],
                "status_counts": summary["status_counts"],
                "functional_regressions": summary["functional_regressions"],
                "review_required": summary["review_required"],
                "evidence_gaps": summary["evidence_gaps"],
                "resolved_discrepancies": summary["resolved_discrepancies"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.fail_on_discrepancy and not summary["release_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
