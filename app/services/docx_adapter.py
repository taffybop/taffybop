"""Native, non-rendering DOCX adapter for the Phase 07 release path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

from app.services.office_native import (
    OfficeAdapterDisabledError,
    OfficeNativeLimitError,
    OfficeNativePackageError,
    OfficePackageView,
    OfficeRelationship,
    StableIdFactory,
    attr,
    build_parse_result,
    child,
    children,
    coerce_package,
    content_item,
    descendants,
    html_table,
    local_name,
    logical_page,
    markdown_table,
    native_provenance,
    normalized_text,
    office_adapter_manifest,
    parse_bool,
    read_relationships,
    read_xml,
    relationship_by_type,
)


DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_MAX_BLOCK_WRAPPER_DEPTH = 64
_VISIBLE_BLOCK_WRAPPERS = frozenset({"ins", "moveTo"})
_HIDDEN_BLOCK_WRAPPERS = frozenset({"del", "moveFrom"})
_BLOCK_CONTENT_NAMES = frozenset(
    {
        "altChunk",
        "del",
        "ins",
        "moveFrom",
        "moveTo",
        "p",
        "sdt",
        "sectPr",
        "tbl",
    }
)
_IGNORABLE_BLOCK_MARKERS = frozenset(
    {
        "bookmarkEnd",
        "bookmarkStart",
        "commentRangeEnd",
        "commentRangeStart",
        "customXmlDelRangeEnd",
        "customXmlDelRangeStart",
        "customXmlInsRangeEnd",
        "customXmlInsRangeStart",
        "moveFromRangeEnd",
        "moveFromRangeStart",
        "moveToRangeEnd",
        "moveToRangeStart",
        "permEnd",
        "permStart",
        "proofErr",
    }
)


@dataclass(frozen=True, slots=True)
class _Style:
    style_id: str
    name: str
    based_on: str | None
    outline_level: int | None


@dataclass(frozen=True, slots=True)
class _Paragraph:
    text: str
    runs: list[dict[str, Any]]
    style_id: str | None
    style_name: str | None
    heading_level: int | None
    list_level: int | None
    list_ordered: bool | None
    concerns: list[str]


def _related_or_sibling_part(
    relationships: Mapping[str, OfficeRelationship],
    relationship_suffix: str,
    sibling_part: str,
) -> str:
    for relationship in relationship_by_type(relationships, relationship_suffix):
        if not relationship.external and relationship.resolved_target is not None:
            return relationship.resolved_target
    return sibling_part


def _parse_styles(package: OfficePackageView, styles_part: str) -> dict[str, _Style]:
    root = read_xml(package, styles_part, required=False)
    if root is None:
        return {}
    raw: dict[str, _Style] = {}
    for node in children(root, "style"):
        if (attr(node, "type") or "paragraph") != "paragraph":
            continue
        style_id = (attr(node, "styleId") or "").strip()
        if not style_id:
            continue
        name_node = child(node, "name")
        based_node = child(node, "basedOn")
        paragraph_properties = child(node, "pPr")
        outline_node = (
            child(paragraph_properties, "outlineLvl")
            if paragraph_properties is not None
            else None
        )
        outline: int | None = None
        if outline_node is not None:
            try:
                outline = int(attr(outline_node, "val") or "") + 1
            except ValueError:
                outline = None
        raw[style_id] = _Style(
            style_id=style_id,
            name=(attr(name_node, "val") if name_node is not None else None)
            or style_id,
            based_on=(
                attr(based_node, "val") if based_node is not None else None
            ),
            outline_level=outline,
        )
    # Resolve only the heading-level property through a short, cycle-safe
    # inheritance chain.  Formatting remains source-local and never guessed.
    result: dict[str, _Style] = {}
    for style_id, style in raw.items():
        outline = style.outline_level
        cursor = style
        seen = {style_id}
        for _ in range(16):
            if outline is not None or cursor.based_on is None:
                break
            if cursor.based_on in seen or cursor.based_on not in raw:
                break
            seen.add(cursor.based_on)
            cursor = raw[cursor.based_on]
            outline = cursor.outline_level
        result[style_id] = _Style(
            style_id=style.style_id,
            name=style.name,
            based_on=style.based_on,
            outline_level=outline,
        )
    return result


def _parse_numbering(
    package: OfficePackageView,
    numbering_part: str,
) -> dict[tuple[str, int], str]:
    root = read_xml(package, numbering_part, required=False)
    if root is None:
        return {}
    abstract_formats: dict[tuple[str, int], str] = {}
    for abstract in children(root, "abstractNum"):
        abstract_id = (attr(abstract, "abstractNumId") or "").strip()
        for level in children(abstract, "lvl"):
            try:
                level_index = int(attr(level, "ilvl") or "0")
            except ValueError:
                continue
            format_node = child(level, "numFmt")
            abstract_formats[(abstract_id, level_index)] = (
                attr(format_node, "val") if format_node is not None else None
            ) or "bullet"
    numbering: dict[tuple[str, int], str] = {}
    for instance in children(root, "num"):
        num_id = (attr(instance, "numId") or "").strip()
        abstract_node = child(instance, "abstractNumId")
        abstract_id = (
            attr(abstract_node, "val") if abstract_node is not None else None
        )
        if not num_id or abstract_id is None:
            continue
        for (candidate, level_index), value in abstract_formats.items():
            if candidate == abstract_id:
                numbering[(num_id, level_index)] = value
    return numbering


def _run_hidden(run: ET.Element) -> bool:
    properties = child(run, "rPr")
    if properties is None:
        return False
    return any(
        local_name(node.tag) in {"vanish", "webHidden"}
        and parse_bool(attr(node, "val"), True)
        for node in list(properties)
    )


def _run_text(run: ET.Element, *, max_elements: int) -> str:
    if _run_hidden(run):
        return ""
    values: list[str] = []
    stack = [(run, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        if depth > _MAX_BLOCK_WRAPPER_DEPTH:
            raise OfficeNativeLimitError(
                code="docx_wrapper_depth_limit",
                details={"max_depth": _MAX_BLOCK_WRAPPER_DEPTH},
            )
        name = local_name(node.tag)
        if name == "instrText":
            continue
        if name == "t" and node.text:
            values.append(node.text)
        elif name == "tab":
            values.append("\t")
        elif name in {"br", "cr"}:
            values.append("\n")
        stack.extend(
            (nested, depth + 1)
            for nested in reversed(list(node))
        )
    return "".join(values)


def _paragraph_runs(
    paragraph: ET.Element,
    xml_path: str,
    *,
    max_elements: int,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    stack = [
        (node, 0)
        for node in reversed(list(paragraph))
        if local_name(node.tag) != "pPr"
    ]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        if depth > _MAX_BLOCK_WRAPPER_DEPTH:
            raise OfficeNativeLimitError(
                code="docx_wrapper_depth_limit",
                details={"max_depth": _MAX_BLOCK_WRAPPER_DEPTH},
            )
        name = local_name(node.tag)
        if name in _HIDDEN_BLOCK_WRAPPERS:
            continue
        if name == "r":
            text = _run_text(node, max_elements=max_elements)
            if text:
                properties = child(node, "rPr")
                run_style = child(properties, "rStyle") if properties is not None else None
                runs.append(
                    {
                        "text": text,
                        "bold": properties is not None
                        and child(properties, "b") is not None,
                        "italic": properties is not None
                        and child(properties, "i") is not None,
                        "underline": properties is not None
                        and child(properties, "u") is not None,
                        "style_id": (
                            attr(run_style, "val") if run_style is not None else None
                        ),
                        "xml_path": f"{xml_path}/r[{len(runs) + 1}]",
                    }
                )
            continue
        if name in {"instrText", "fldChar"}:
            continue
        stack.extend(
            (nested, depth + 1)
            for nested in reversed(list(node))
        )
    return runs


def _paragraph(
    node: ET.Element,
    *,
    xml_path: str,
    styles: Mapping[str, _Style],
    numbering: Mapping[tuple[str, int], str],
    max_elements: int,
) -> _Paragraph:
    runs = _paragraph_runs(node, xml_path, max_elements=max_elements)
    text = normalized_text(run["text"] for run in runs)
    properties = child(node, "pPr")
    style_node = child(properties, "pStyle") if properties is not None else None
    style_id = attr(style_node, "val") if style_node is not None else None
    style = styles.get(style_id or "")
    concerns: list[str] = []
    if style_id and style is None:
        concerns.append("docx_style_unresolved")
    heading_level = style.outline_level if style is not None else None
    if heading_level is None and style is not None:
        lowered = style.name.casefold().replace(" ", "")
        if lowered.startswith("heading"):
            suffix = lowered.removeprefix("heading")
            if suffix.isdigit():
                heading_level = max(1, min(int(suffix), 6))
    num_properties = child(properties, "numPr") if properties is not None else None
    list_level: int | None = None
    list_ordered: bool | None = None
    if num_properties is not None:
        level_node = child(num_properties, "ilvl")
        num_node = child(num_properties, "numId")
        try:
            list_level = int(
                attr(level_node, "val") if level_node is not None else "0"
            )
        except (TypeError, ValueError):
            list_level = 0
            concerns.append("docx_list_level_invalid")
        num_id = attr(num_node, "val") if num_node is not None else None
        list_format = numbering.get((num_id or "", list_level))
        if list_format is None:
            concerns.append("docx_numbering_unresolved")
            list_ordered = False
        else:
            list_ordered = list_format.casefold() not in {"bullet", "none"}
    return _Paragraph(
        text=text,
        runs=runs,
        style_id=style_id,
        style_name=style.name if style is not None else None,
        heading_level=heading_level,
        list_level=list_level,
        list_ordered=list_ordered,
        concerns=concerns,
    )


def _table_payload(
    node: ET.Element,
    *,
    part: str,
    table_index: int,
    xml_path: str | None = None,
    max_elements: int,
) -> dict[str, Any]:
    rows: list[list[str]] = []
    cells_payload: list[dict[str, Any]] = []
    header_rows: list[int] = []
    for row_index, row in enumerate(children(node, "tr")):
        row_properties = child(row, "trPr")
        if row_properties is not None and child(row_properties, "tblHeader") is not None:
            header_rows.append(row_index)
        values: list[str] = []
        column_index = 0
        for cell_index, cell_node in enumerate(children(row, "tc")):
            if len(cells_payload) >= max_elements:
                raise OfficeNativeLimitError(
                    code="docx_element_limit",
                    details={"max_elements": max_elements},
                )
            table_path = xml_path or f"/document/body/tbl[{table_index}]"
            cell_path = (
                f"{table_path}/tr[{row_index + 1}]"
                f"/tc[{cell_index + 1}]"
            )
            value = normalized_text(
                run["text"]
                for paragraph, paragraph_path in _policy_visible_paragraphs(
                    cell_node,
                    root_path=cell_path,
                    max_elements=max_elements,
                )
                for run in _paragraph_runs(
                    paragraph,
                    paragraph_path,
                    max_elements=max_elements,
                )
            )
            cell_properties = child(cell_node, "tcPr")
            grid_span_node = (
                child(cell_properties, "gridSpan")
                if cell_properties is not None
                else None
            )
            try:
                column_span = max(
                    int(attr(grid_span_node, "val") or "1")
                    if grid_span_node is not None
                    else 1,
                    1,
                )
            except ValueError:
                column_span = 1
            merge_node = (
                child(cell_properties, "vMerge")
                if cell_properties is not None
                else None
            )
            merge_value = attr(merge_node, "val") if merge_node is not None else None
            cells_payload.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "text": value,
                    "row_span": 1,
                    "column_span": column_span,
                    "vertical_merge": (
                        "continue"
                        if merge_node is not None and merge_value in {None, "continue"}
                        else "restart"
                        if merge_node is not None
                        else None
                    ),
                    "native_provenance": native_provenance(
                        part=part,
                        xml_path=cell_path,
                        coordinate_state="logical",
                    ),
                }
            )
            values.append(value)
            values.extend([""] * (column_span - 1))
            column_index += column_span
        rows.append(values)
    properties = child(node, "tblPr")
    caption_node = child(properties, "tblCaption") if properties is not None else None
    caption = attr(caption_node, "val") if caption_node is not None else None
    return {
        "rows": rows,
        "cells": cells_payload,
        "header_rows": header_rows,
        "caption": caption,
        "html": html_table(rows),
        "md": markdown_table(rows),
    }


def _section_payload(node: ET.Element) -> dict[str, Any]:
    page_size = child(node, "pgSz")
    section_type = child(node, "type")
    columns_node = child(node, "cols")
    result: dict[str, Any] = {
        "break_type": (
            attr(section_type, "val") if section_type is not None else "continuous"
        ),
        "orientation": (
            attr(page_size, "orient") if page_size is not None else None
        ),
    }
    if columns_node is not None:
        try:
            result["column_count"] = int(attr(columns_node, "num") or "1")
        except ValueError:
            result["column_count"] = None
    return result


def _drawing_items(
    node: ET.Element,
    *,
    package: OfficePackageView,
    relationships: Mapping[str, OfficeRelationship],
    ids: StableIdFactory,
    reading_order: int,
    part: str,
    xml_path: str,
    max_elements: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    drawing_nodes: list[ET.Element] = []
    stack = [(node, 0)]
    visited = 0
    while stack:
        candidate, depth = stack.pop()
        visited += 1
        if visited > max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        if depth > _MAX_BLOCK_WRAPPER_DEPTH:
            raise OfficeNativeLimitError(
                code="docx_wrapper_depth_limit",
                details={"max_depth": _MAX_BLOCK_WRAPPER_DEPTH},
            )
        name = local_name(candidate.tag)
        if name in _HIDDEN_BLOCK_WRAPPERS:
            continue
        if name in {"drawing", "pict", "object", "altChunk"}:
            drawing_nodes.append(candidate)
        stack.extend(
            (nested, depth + 1)
            for nested in reversed(list(candidate))
        )
    for drawing_index, drawing in enumerate(drawing_nodes, 1):
        drawing_path = f"{xml_path}/{local_name(drawing.tag)}[{drawing_index}]"
        blips = descendants(drawing, "blip")
        relationship_id = None
        linked = False
        if blips:
            relationship_id = attr(blips[0], "embed") or attr(blips[0], "link")
        relationship = relationships.get(relationship_id or "")
        if relationship is not None and not relationship.external:
            linked = relationship.resolved_target is not None
            available = (
                package.read_part(relationship.resolved_target, required=False)
                is not None
                if relationship.resolved_target is not None
                else False
            )
            if linked and available:
                result.append(
                    content_item(
                        ids,
                        "image",
                        reading_order + len(result),
                        value=f"[Embedded image: {relationship.resolved_target}]",
                        markdown=f"[Embedded image: {relationship.resolved_target}]",
                        provenance=native_provenance(
                            part=part,
                            xml_path=drawing_path,
                            coordinate_state="logical",
                            relationship=relationship,
                        ),
                        content_type="image",
                        asset_origin="native_embedded",
                        relationship_id=relationship.relationship_id,
                        source_part=relationship.resolved_target,
                    )
                )
                continue
        concerns = [
            "docx_external_media_not_fetched"
            if relationship is not None and relationship.external
            else "docx_media_relationship_broken"
            if relationship_id
            else "docx_unsupported_drawing"
        ]
        result.append(
            content_item(
                ids,
                "image",
                reading_order + len(result),
                value="[Unsupported Word drawing]",
                markdown="[Unsupported Word drawing]",
                provenance=native_provenance(
                    part=part,
                    xml_path=drawing_path,
                    coordinate_state="logical",
                    relationship=relationship,
                ),
                content_type="unsupported_drawing",
                placeholder=True,
                parse_concerns=concerns,
                relationship_id=relationship_id,
                fallback_eligible=True,
                linked_relationship=linked,
            )
        )
    return result


def _part_text_items(
    root: ET.Element,
    *,
    part: str,
    item_type: str,
    ids: StableIdFactory,
    reading_order: int,
    max_elements: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for paragraph, paragraph_path in _policy_visible_paragraphs(
        root,
        root_path=f"/{item_type}",
        max_elements=max_elements,
    ):
        text = normalized_text(
            run["text"]
            for run in _paragraph_runs(
                paragraph,
                paragraph_path,
                max_elements=max_elements,
            )
        )
        if not text:
            continue
        result.append(
            content_item(
                ids,
                item_type,
                reading_order + len(result),
                value=text,
                markdown=text,
                provenance=native_provenance(
                    part=part,
                    xml_path=paragraph_path,
                    coordinate_state="logical",
                ),
                region_role=item_type,
            )
        )
    return result


def _indexed_children(
    node: ET.Element,
    parent_path: str,
) -> list[tuple[ET.Element, str]]:
    """Return child paths indexed by local name in deterministic XML order."""

    counts: dict[str, int] = {}
    result: list[tuple[ET.Element, str]] = []
    for nested in list(node):
        name = local_name(nested.tag)
        counts[name] = counts.get(name, 0) + 1
        result.append((nested, f"{parent_path}/{name}[{counts[name]}]"))
    return result


def _sdt_content(node: ET.Element) -> ET.Element | None:
    """Return a transparent block SDT payload only when its shape is known."""

    direct = list(node)
    content = [nested for nested in direct if local_name(nested.tag) == "sdtContent"]
    if len(content) != 1 or any(
        local_name(nested.tag) not in {"sdtPr", "sdtEndPr", "sdtContent"}
        for nested in direct
    ):
        return None
    if any(
        local_name(nested.tag)
        not in _BLOCK_CONTENT_NAMES | _IGNORABLE_BLOCK_MARKERS
        for nested in list(content[0])
    ):
        return None
    return content[0]


def _policy_visible_paragraphs(
    root: ET.Element,
    *,
    root_path: str,
    max_elements: int,
) -> list[tuple[ET.Element, str]]:
    """Find visible paragraphs in order behind bounded transparent wrappers."""

    result: list[tuple[ET.Element, str]] = []
    stack = [
        (node, path, 0)
        for node, path in reversed(_indexed_children(root, root_path))
    ]
    visited = 0
    while stack:
        node, path, depth = stack.pop()
        visited += 1
        if visited > max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        if depth > _MAX_BLOCK_WRAPPER_DEPTH:
            raise OfficeNativeLimitError(
                code="docx_wrapper_depth_limit",
                details={"max_depth": _MAX_BLOCK_WRAPPER_DEPTH},
            )
        name = local_name(node.tag)
        if name in _HIDDEN_BLOCK_WRAPPERS or name in _IGNORABLE_BLOCK_MARKERS:
            continue
        if name == "p":
            result.append((node, path))
            continue
        if name == "sdt":
            content = _sdt_content(node)
            if content is None:
                continue
            nested_nodes = _indexed_children(content, f"{path}/sdtContent[1]")
        else:
            nested_nodes = _indexed_children(node, path)
        stack.extend(
            (nested, nested_path, depth + 1)
            for nested, nested_path in reversed(nested_nodes)
        )
    return result


def _visible_body_blocks(
    body: ET.Element,
    *,
    max_elements: int,
) -> list[tuple[ET.Element, str]]:
    """Flatten policy-visible block wrappers without recursive traversal."""

    visible: list[tuple[ET.Element, str]] = []
    stack = [
        (node, path, 0)
        for node, path in reversed(_indexed_children(body, "/document/body"))
    ]
    visited = 0
    while stack:
        node, path, depth = stack.pop()
        visited += 1
        if visited > max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        if depth > _MAX_BLOCK_WRAPPER_DEPTH:
            raise OfficeNativeLimitError(
                code="docx_wrapper_depth_limit",
                details={"max_depth": _MAX_BLOCK_WRAPPER_DEPTH},
            )
        name = local_name(node.tag)
        if name in _HIDDEN_BLOCK_WRAPPERS or name in _IGNORABLE_BLOCK_MARKERS:
            continue
        if name == "sdt":
            content = _sdt_content(node)
            if content is None:
                visible.append((node, path))
                continue
            nested_nodes = _indexed_children(content, f"{path}/sdtContent[1]")
            stack.extend(
                (nested, nested_path, depth + 1)
                for nested, nested_path in reversed(nested_nodes)
            )
            continue
        if name in _VISIBLE_BLOCK_WRAPPERS:
            nested_nodes = _indexed_children(node, path)
            stack.extend(
                (nested, nested_path, depth + 1)
                for nested, nested_path in reversed(nested_nodes)
            )
            continue
        visible.append((node, path))
    return visible


def parse_docx(
    source: Any,
    *,
    filename: str = "document.docx",
    enabled: bool = True,
    max_elements: int = 10_000,
) -> dict[str, Any]:
    """Extract policy-visible DOCX native evidence without rendering."""

    if not enabled:
        raise OfficeAdapterDisabledError(
            "DOCX native adapter is disabled.",
            details={"extension": ".docx"},
        )
    if isinstance(max_elements, bool) or max_elements < 1:
        raise ValueError("max_elements must be a positive integer")
    package = coerce_package(source)
    document_part = package.main_part or "word/document.xml"
    root = read_xml(package, document_part)
    if root is None:  # pragma: no cover - required=True raises first.
        raise OfficeNativePackageError(code="docx_document_part_missing")
    if local_name(root.tag) != "document":
        raise OfficeNativePackageError(code="docx_document_root_invalid")
    body = child(root, "body")
    if body is None:
        raise OfficeNativePackageError(code="docx_body_missing")

    relationships = read_relationships(package, document_part)
    main_directory = PurePosixPath(document_part).parent
    styles_part = _related_or_sibling_part(
        relationships,
        "/styles",
        str(main_directory / "styles.xml"),
    )
    numbering_part = _related_or_sibling_part(
        relationships,
        "/numbering",
        str(main_directory / "numbering.xml"),
    )
    styles = _parse_styles(package, styles_part)
    numbering = _parse_numbering(package, numbering_part)
    ids = StableIdFactory("docx")
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    def append(item: dict[str, Any]) -> None:
        if len(items) >= max_elements:
            raise OfficeNativeLimitError(
                code="docx_element_limit",
                details={"max_elements": max_elements},
            )
        item["reading_order"] = len(items)
        items.append(item)

    # Header content precedes the body in logical reading order; repeated
    # relationships are deduplicated by resolved package part.
    seen_supplemental: set[str] = set()
    for relationship in relationship_by_type(relationships, "/header"):
        if relationship.external or relationship.resolved_target is None:
            warnings.append("docx_external_header_not_fetched")
            continue
        if relationship.resolved_target in seen_supplemental:
            continue
        seen_supplemental.add(relationship.resolved_target)
        header_root = read_xml(package, relationship.resolved_target, required=False)
        if header_root is None:
            warnings.append("docx_header_relationship_broken")
            continue
        for item in _part_text_items(
            header_root,
            part=relationship.resolved_target,
            item_type="header",
            ids=ids,
            reading_order=len(items),
            max_elements=max_elements,
        ):
            item["native_provenance"].update(
                {
                    "relationship_id": relationship.relationship_id,
                    "relationship_type": relationship.relationship_type,
                }
            )
            append(item)

    pending_list: dict[str, Any] | None = None

    def flush_list() -> None:
        nonlocal pending_list
        if pending_list is None:
            return
        append(
            content_item(
                ids,
                "list",
                len(items),
                value="\n".join(entry["value"] for entry in pending_list["items"]),
                markdown=None,
                provenance=pending_list["native_provenance"],
                ordered=pending_list["ordered"],
                items=pending_list["items"],
                parse_concerns=pending_list["parse_concerns"],
            )
        )
        pending_list = None

    table_index = 0
    section_index = 0
    for body_node, body_path in _visible_body_blocks(
        body,
        max_elements=max_elements,
    ):
        name = local_name(body_node.tag)
        if name == "p":
            path = body_path
            paragraph = _paragraph(
                body_node,
                xml_path=path,
                styles=styles,
                numbering=numbering,
                max_elements=max_elements,
            )
            if paragraph.list_level is not None and paragraph.text:
                ordered = bool(paragraph.list_ordered)
                if pending_list is None or pending_list["ordered"] != ordered:
                    flush_list()
                    pending_list = {
                        "ordered": ordered,
                        "items": [],
                        "parse_concerns": [],
                        "native_provenance": native_provenance(
                            part=document_part,
                            xml_path=path,
                            coordinate_state="logical",
                        ),
                    }
                pending_list["items"].append(
                    {
                        "value": paragraph.text,
                        "text": paragraph.text,
                        "level": paragraph.list_level,
                        "runs": paragraph.runs,
                        "native_provenance": native_provenance(
                            part=document_part,
                            xml_path=path,
                            coordinate_state="logical",
                        ),
                    }
                )
                pending_list["parse_concerns"].extend(paragraph.concerns)
            else:
                flush_list()
                if paragraph.text:
                    item_type = "heading" if paragraph.heading_level else "text"
                    append(
                        content_item(
                            ids,
                            item_type,
                            len(items),
                            value=paragraph.text,
                            markdown=paragraph.text,
                            provenance=native_provenance(
                                part=document_part,
                                xml_path=path,
                                coordinate_state="logical",
                            ),
                            level=paragraph.heading_level,
                            style_id=paragraph.style_id,
                            style_name=paragraph.style_name,
                            runs=paragraph.runs,
                            parse_concerns=paragraph.concerns,
                        )
                    )
            drawing_items = _drawing_items(
                body_node,
                package=package,
                relationships=relationships,
                ids=ids,
                reading_order=len(items),
                part=document_part,
                xml_path=path,
                max_elements=max_elements,
            )
            if drawing_items:
                flush_list()
            for drawing_item in drawing_items:
                append(drawing_item)
            properties = child(body_node, "pPr")
            section = child(properties, "sectPr") if properties is not None else None
            if section is not None:
                flush_list()
                section_index += 1
                append(
                    content_item(
                        ids,
                        "section",
                        len(items),
                        value=f"Section {section_index}",
                        markdown=None,
                        provenance=native_provenance(
                            part=document_part,
                            xml_path=f"{path}/pPr/sectPr",
                            coordinate_state="logical",
                        ),
                        section=_section_payload(section),
                    )
                )
        elif name == "tbl":
            flush_list()
            table_index += 1
            payload = _table_payload(
                body_node,
                part=document_part,
                table_index=table_index,
                xml_path=body_path,
                max_elements=max_elements,
            )
            append(
                content_item(
                    ids,
                    "table",
                    len(items),
                    value=payload["rows"],
                    markdown=payload["md"],
                    provenance=native_provenance(
                        part=document_part,
                        xml_path=body_path,
                        coordinate_state="logical",
                    ),
                    rows=payload["rows"],
                    cells=payload["cells"],
                    html=payload["html"],
                    caption=payload["caption"],
                    header_rows=payload["header_rows"],
                )
            )
        elif name == "sectPr":
            flush_list()
            section_index += 1
            append(
                content_item(
                    ids,
                    "section",
                    len(items),
                    value=f"Section {section_index}",
                    markdown=None,
                    provenance=native_provenance(
                        part=document_part,
                        xml_path=body_path,
                        coordinate_state="logical",
                    ),
                    section=_section_payload(body_node),
                )
            )
        elif name in {"altChunk", "sdt"}:
            flush_list()
            append(
                content_item(
                    ids,
                    "text",
                    len(items),
                    value=f"[Unsupported Word {name}]",
                    markdown=f"[Unsupported Word {name}]",
                    provenance=native_provenance(
                        part=document_part,
                        xml_path=body_path,
                        coordinate_state="logical",
                    ),
                    placeholder=True,
                    fallback_eligible=True,
                    parse_concerns=[f"docx_{name.casefold()}_unsupported"],
                )
            )
    flush_list()

    for relationship in relationship_by_type(relationships, "/footer"):
        if relationship.external or relationship.resolved_target is None:
            warnings.append("docx_external_footer_not_fetched")
            continue
        if relationship.resolved_target in seen_supplemental:
            continue
        seen_supplemental.add(relationship.resolved_target)
        footer_root = read_xml(package, relationship.resolved_target, required=False)
        if footer_root is None:
            warnings.append("docx_footer_relationship_broken")
            continue
        for item in _part_text_items(
            footer_root,
            part=relationship.resolved_target,
            item_type="footer",
            ids=ids,
            reading_order=len(items),
            max_elements=max_elements,
        ):
            item["native_provenance"].update(
                {
                    "relationship_id": relationship.relationship_id,
                    "relationship_type": relationship.relationship_type,
                }
            )
            append(item)

    for suffix, item_type in (("/footnotes", "footnote"), ("/endnotes", "footnote")):
        for relationship in relationship_by_type(relationships, suffix):
            if relationship.external or relationship.resolved_target is None:
                warnings.append("docx_external_note_not_fetched")
                continue
            note_root = read_xml(package, relationship.resolved_target, required=False)
            if note_root is None:
                warnings.append("docx_note_relationship_broken")
                continue
            for item in _part_text_items(
                note_root,
                part=relationship.resolved_target,
                item_type=item_type,
                ids=ids,
                reading_order=len(items),
                max_elements=max_elements,
            ):
                append(item)

    page = logical_page(
        page_index=1,
        label="logical-document",
        items=items,
        coordinate_state="logical",
        warnings=warnings,
        extra={
            "logical_container": "document",
            "physical_page_number": None,
            "physical_page_label": None,
        },
    )
    return build_parse_result(
        filename=filename,
        mime_type=DOCX_MIME_TYPE,
        source_format="DOCX",
        source_sha256=package.digest([document_part, styles_part, numbering_part]),
        pages=[page],
        warnings=warnings,
    )


parse_docx_package = parse_docx


class DocxNativeAdapter:
    adapter_id = "docx-native"
    adapter_version = "1.0.0"
    extensions = (".docx",)
    mime_types = (DOCX_MIME_TYPE,)
    source_format = "DOCX"

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings
        self._manifest = office_adapter_manifest(
            adapter_id=self.adapter_id,
            input_kind="docx",
            extension=".docx",
            mime_type=DOCX_MIME_TYPE,
            coordinate_unit="logical",
            optional_capabilities=[
                "headers_footers",
                "logical_sections",
                "native_lists",
                "native_media",
                "native_tables",
                "native_text",
                "styles",
            ],
            settings=settings,
        )

    @property
    def manifest(self) -> Any:
        return self._manifest

    def load(self, data: bytes, filename: str, settings: Any) -> dict[str, Any]:
        from app.services.ooxml_intake import intake_ooxml, limits_from_settings

        package = intake_ooxml(
            data,
            filename,
            DOCX_MIME_TYPE,
            limits=limits_from_settings(settings),
        )
        return parse_docx(
            package,
            filename=filename,
            enabled=bool(getattr(settings, "adapters_docx_native_enabled", False)),
        )

    def parse(
        self,
        source: Any,
        *,
        filename: str = "document.docx",
        enabled: bool = True,
        max_elements: int = 10_000,
    ) -> dict[str, Any]:
        return parse_docx(
            source,
            filename=filename,
            enabled=enabled,
            max_elements=max_elements,
        )


DOCXAdapter = DocxNativeAdapter


__all__ = [
    "DOCXAdapter",
    "DOCX_MIME_TYPE",
    "DocxNativeAdapter",
    "parse_docx",
    "parse_docx_package",
]
