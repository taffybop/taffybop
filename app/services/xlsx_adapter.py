"""Native XLSX workbook adapter with bounded sparse-range handling."""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
)


XLSX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
XLSX_MAX_ROWS = 1_048_576
XLSX_MAX_COLUMNS = 16_384
_CELL_REFERENCE = re.compile(r"^\$?([A-Za-z]{1,4})\$?([1-9][0-9]{0,6})$")
_RANGE_REFERENCE = re.compile(
    r"^\$?([A-Za-z]{1,4})\$?([1-9][0-9]{0,6})"
    r"(?::\$?([A-Za-z]{1,4})\$?([1-9][0-9]{0,6}))?$"
)
_EXTERNAL_FORMULA = re.compile(r"(?:\[[^\]]+\]|https?://|file:|\\\\)", re.I)


@dataclass(frozen=True, slots=True)
class _CellAddress:
    column: int
    row: int


def _column_index(label: str) -> int:
    result = 0
    for character in label.upper():
        if not "A" <= character <= "Z":
            raise OfficeNativePackageError(code="xlsx_cell_reference_invalid")
        result = result * 26 + (ord(character) - ord("A") + 1)
    return result


def _column_label(index: int) -> str:
    if index < 1:
        raise OfficeNativePackageError(code="xlsx_cell_reference_invalid")
    result: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(ord("A") + remainder))
    return "".join(reversed(result))


def _cell_address(
    reference: str,
    *,
    max_rows: int = XLSX_MAX_ROWS,
    max_columns: int = XLSX_MAX_COLUMNS,
) -> _CellAddress:
    match = _CELL_REFERENCE.fullmatch(reference.strip())
    if match is None:
        raise OfficeNativePackageError(
            code="xlsx_cell_reference_invalid",
            details={"reference": reference[:64]},
        )
    address = _CellAddress(
        column=_column_index(match.group(1)),
        row=int(match.group(2)),
    )
    if address.column > XLSX_MAX_COLUMNS or address.row > XLSX_MAX_ROWS:
        raise OfficeNativePackageError(
            code="xlsx_cell_reference_out_of_bounds",
            details={"reference": reference[:64]},
        )
    if address.row > max_rows:
        raise OfficeNativeLimitError(
            code="xlsx_row_limit",
            details={
                "reference": reference[:64],
                "max_rows": max_rows,
            },
        )
    if address.column > max_columns:
        raise OfficeNativeLimitError(
            code="xlsx_column_limit",
            details={
                "reference": reference[:64],
                "max_columns": max_columns,
            },
        )
    return address


def _range_bounds(
    reference: str,
    *,
    max_rows: int = XLSX_MAX_ROWS,
    max_columns: int = XLSX_MAX_COLUMNS,
) -> tuple[_CellAddress, _CellAddress]:
    match = _RANGE_REFERENCE.fullmatch(reference.strip())
    if match is None:
        raise OfficeNativePackageError(
            code="xlsx_range_reference_invalid",
            details={"reference": reference[:128]},
        )
    start = _cell_address(
        f"{match.group(1)}{match.group(2)}",
        max_rows=max_rows,
        max_columns=max_columns,
    )
    end = _cell_address(
        f"{match.group(3) or match.group(1)}{match.group(4) or match.group(2)}",
        max_rows=max_rows,
        max_columns=max_columns,
    )
    if end.column < start.column or end.row < start.row:
        raise OfficeNativePackageError(code="xlsx_range_reference_invalid")
    return start, end


def _range_area(
    reference: str,
    *,
    max_rows: int = XLSX_MAX_ROWS,
    max_columns: int = XLSX_MAX_COLUMNS,
) -> int:
    start, end = _range_bounds(
        reference,
        max_rows=max_rows,
        max_columns=max_columns,
    )
    return (end.column - start.column + 1) * (end.row - start.row + 1)


def _related_or_sibling_part(
    relationships: Mapping[str, OfficeRelationship],
    relationship_suffix: str,
    sibling_part: str,
) -> str:
    for relationship in relationships.values():
        if not relationship.relationship_type.casefold().endswith(
            relationship_suffix.casefold()
        ):
            continue
        if not relationship.external and relationship.resolved_target is not None:
            return relationship.resolved_target
    return sibling_part


def _shared_strings(package: OfficePackageView, part: str) -> list[str]:
    root = read_xml(package, part, required=False)
    if root is None:
        return []
    result: list[str] = []
    for item in children(root, "si"):
        result.append(
            normalized_text(
                node.text or ""
                for node in descendants(item, "t")
                if node.text is not None
            )
        )
    return result


def _style_date_flags(package: OfficePackageView, part: str) -> set[int]:
    root = read_xml(package, part, required=False)
    if root is None:
        return set()
    custom_formats: dict[int, str] = {}
    num_formats = child(root, "numFmts")
    if num_formats is not None:
        for node in children(num_formats, "numFmt"):
            try:
                format_id = int(attr(node, "numFmtId") or "")
            except ValueError:
                continue
            custom_formats[format_id] = attr(node, "formatCode") or ""
    date_format_ids = {
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        45,
        46,
        47,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
    }
    # Ignore quoted literals and bracketed color/locale annotations before
    # looking for date/time tokens.
    for format_id, code in custom_formats.items():
        normalized = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code).casefold()
        if re.search(r"(?:y+|d+|h+|s+|m{2,})", normalized):
            date_format_ids.add(format_id)
    cell_formats = child(root, "cellXfs")
    result: set[int] = set()
    if cell_formats is not None:
        for index, xf in enumerate(children(cell_formats, "xf")):
            try:
                format_id = int(attr(xf, "numFmtId") or "0")
            except ValueError:
                continue
            if format_id in date_format_ids:
                result.add(index)
    return result


def _excel_date(serial: Decimal, *, date_1904: bool) -> str:
    # Excel's 1900 system intentionally contains the fictitious 1900-02-29.
    # Preserve that value explicitly; do not silently shift it into another day.
    if not date_1904 and serial == Decimal(60):
        return "1900-02-29"
    whole = int(serial // 1)
    fraction = serial - Decimal(whole)
    if date_1904:
        base = dt.datetime(1904, 1, 1)
    else:
        base = dt.datetime(1899, 12, 31)
        if whole > 60:
            whole -= 1
    seconds = int((fraction * Decimal(86_400)).to_integral_value())
    value = base + dt.timedelta(days=whole, seconds=seconds)
    return value.date().isoformat() if seconds == 0 else value.isoformat()


def _scalar_number(value: str) -> tuple[int | float | str, list[str]]:
    if not value.strip():
        return value, []
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value, ["xlsx_numeric_value_invalid"]
    if not number.is_finite():
        return value, ["xlsx_numeric_value_invalid"]
    if number == number.to_integral_value():
        # Avoid constructing an attacker-controlled integer whose exponent is
        # vastly larger than the bounded XML text that represented it.
        if number and number.adjusted() > 4_096:
            return value, ["xlsx_numeric_value_out_of_range"]
        try:
            return int(number), []
        except (OverflowError, ValueError):
            return value, ["xlsx_numeric_value_out_of_range"]
    converted = float(number)
    if not math.isfinite(converted) or (converted == 0.0 and number != 0):
        return value, ["xlsx_numeric_value_out_of_range"]
    return converted, []


def _cell_value(
    cell_node: ET.Element,
    *,
    shared_strings: list[str],
    date_styles: set[int],
    date_1904: bool,
) -> tuple[Any, str, list[str]]:
    cell_type = (attr(cell_node, "t") or "n").strip()
    style_raw = attr(cell_node, "s")
    try:
        style_index = int(style_raw) if style_raw is not None else 0
    except ValueError:
        style_index = 0
    value_node = child(cell_node, "v")
    raw = (value_node.text or "") if value_node is not None else ""
    concerns: list[str] = []
    if cell_type == "inlineStr":
        inline = child(cell_node, "is")
        value = (
            normalized_text(
                node.text or ""
                for node in descendants(inline, "t")
                if node.text is not None
            )
            if inline is not None
            else ""
        )
        return value, "string", concerns
    if cell_type == "s":
        try:
            index = int(raw)
            return shared_strings[index], "string", concerns
        except (ValueError, IndexError):
            concerns.append("xlsx_shared_string_unresolved")
            return raw, "string", concerns
    if cell_type == "b":
        if raw not in {"0", "1"}:
            concerns.append("xlsx_boolean_value_invalid")
        return raw == "1", "boolean", concerns
    if cell_type == "e":
        return raw, "error", concerns
    if cell_type in {"str", "d"}:
        return raw, "date" if cell_type == "d" else "string", concerns
    parsed, numeric_concerns = _scalar_number(raw)
    concerns.extend(numeric_concerns)
    if style_index in date_styles and isinstance(parsed, (int, float)):
        try:
            return _excel_date(Decimal(str(parsed)), date_1904=date_1904), "date", concerns
        except (OverflowError, ValueError):
            concerns.append("xlsx_date_value_invalid")
    return parsed, "number", concerns


def _row_hidden(sheet: ET.Element, *, max_rows: int) -> set[int]:
    result: set[int] = set()
    for row in descendants(sheet, "row"):
        if not parse_bool(attr(row, "hidden"), False):
            continue
        try:
            reference = int(attr(row, "r") or "")
        except ValueError:
            raise OfficeNativePackageError(code="xlsx_row_reference_invalid") from None
        if reference < 1 or reference > XLSX_MAX_ROWS:
            raise OfficeNativePackageError(code="xlsx_row_reference_invalid")
        if reference > max_rows:
            raise OfficeNativeLimitError(
                code="xlsx_row_limit",
                details={"max_rows": max_rows},
            )
        result.add(reference)
    return result


def _column_hidden(sheet: ET.Element, *, max_columns: int) -> set[int]:
    result: set[int] = set()
    for column in descendants(sheet, "col"):
        if not parse_bool(attr(column, "hidden"), False):
            continue
        try:
            minimum = int(attr(column, "min") or "")
            maximum = int(attr(column, "max") or "")
        except ValueError:
            raise OfficeNativePackageError(code="xlsx_column_reference_invalid") from None
        if minimum < 1 or maximum < minimum or maximum > XLSX_MAX_COLUMNS:
            raise OfficeNativePackageError(code="xlsx_column_reference_invalid")
        if maximum > max_columns:
            raise OfficeNativeLimitError(
                code="xlsx_column_limit",
                details={"max_columns": max_columns},
            )
        result.update(range(minimum, maximum + 1))
    return result


def _overlapping_ranges(
    ranges: list[str],
    *,
    max_rows: int,
    max_columns: int,
) -> bool:
    bounds = [
        _range_bounds(
            reference,
            max_rows=max_rows,
            max_columns=max_columns,
        )
        for reference in ranges
    ]
    for index, (left_start, left_end) in enumerate(bounds):
        for right_start, right_end in bounds[index + 1 :]:
            if not (
                left_end.row < right_start.row
                or right_end.row < left_start.row
                or left_end.column < right_start.column
                or right_end.column < left_start.column
            ):
                return True
    return False


def _table_parts(
    package: OfficePackageView,
    *,
    sheet_part: str,
    relationships: Mapping[str, OfficeRelationship],
    max_rows: int,
    max_columns: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for relationship in relationships.values():
        if not relationship.relationship_type.casefold().endswith("/table"):
            continue
        if relationship.external or relationship.resolved_target is None:
            result.append(
                {
                    "relationship_id": relationship.relationship_id,
                    "placeholder": True,
                    "parse_concerns": ["xlsx_external_table_not_fetched"],
                }
            )
            continue
        root = read_xml(package, relationship.resolved_target, required=False)
        if root is None:
            result.append(
                {
                    "relationship_id": relationship.relationship_id,
                    "placeholder": True,
                    "parse_concerns": ["xlsx_table_relationship_broken"],
                }
            )
            continue
        reference = attr(root, "ref") or ""
        _range_bounds(
            reference,
            max_rows=max_rows,
            max_columns=max_columns,
        )
        result.append(
            {
                "name": attr(root, "displayName") or attr(root, "name"),
                "range": reference,
                "header_rows": int(attr(root, "headerRowCount") or "1"),
                "totals_rows": int(attr(root, "totalsRowCount") or "0"),
                "columns": [
                    {
                        "id": attr(column, "id"),
                        "name": attr(column, "name"),
                    }
                    for column in descendants(root, "tableColumn")
                ],
                "relationship_id": relationship.relationship_id,
                "native_provenance": native_provenance(
                    part=sheet_part,
                    xml_path="/worksheet/tableParts",
                    coordinate_state="logical",
                    relationship=relationship,
                ),
            }
        )
    return result


def _drawing_placeholders(
    sheet: ET.Element,
    *,
    sheet_part: str,
    relationships: Mapping[str, OfficeRelationship],
    ids: StableIdFactory,
    reading_order: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for kind in ("drawing", "legacyDrawing"):
        for index, node in enumerate(descendants(sheet, kind), 1):
            relationship_id = attr(node, "id")
            relationship = relationships.get(relationship_id or "")
            result.append(
                content_item(
                    ids,
                    "image",
                    reading_order + len(result),
                    value="[Worksheet drawing pending analysis]",
                    markdown="[Worksheet drawing pending analysis]",
                    provenance=native_provenance(
                        part=sheet_part,
                        xml_path=f"/worksheet/{kind}[{index}]",
                        coordinate_state="logical",
                        relationship=relationship,
                    ),
                    content_type="unsupported_drawing",
                    relationship_id=relationship_id,
                    source_part=(
                        relationship.resolved_target
                        if relationship is not None
                        else None
                    ),
                    placeholder=True,
                    fallback_eligible=True,
                    parse_concerns=[
                        "xlsx_external_drawing_not_fetched"
                        if relationship is not None and relationship.external
                        else "xlsx_drawing_native_deferred"
                    ],
                )
            )
    return result


def _sheet_payload(
    package: OfficePackageView,
    *,
    workbook_part: str,
    sheet_part: str,
    sheet_name: str,
    sheet_id: str,
    shared_strings: list[str],
    date_styles: set[int],
    date_1904: bool,
    max_cells: int,
    max_sparse_area: int,
    max_rows: int,
    max_columns: int,
) -> tuple[list[dict[str, Any]], list[str], tuple[int, int]]:
    root = read_xml(package, sheet_part)
    if root is None or local_name(root.tag) != "worksheet":
        raise OfficeNativePackageError(code="xlsx_worksheet_root_invalid")
    dimension = child(root, "dimension")
    dimension_reference = attr(dimension, "ref") if dimension is not None else None
    if dimension_reference:
        area = _range_area(
            dimension_reference,
            max_rows=max_rows,
            max_columns=max_columns,
        )
        if area > max_sparse_area:
            raise OfficeNativeLimitError(
                code="xlsx_sparse_range_limit",
                details={
                    "sheet": sheet_name,
                    "range": dimension_reference,
                    "max_sparse_area": max_sparse_area,
                },
            )

    hidden_rows = _row_hidden(root, max_rows=max_rows)
    hidden_columns = _column_hidden(root, max_columns=max_columns)
    ids = StableIdFactory(f"xlsx-{sheet_id}")
    relationships = read_relationships(package, sheet_part)
    cells: list[dict[str, Any]] = []
    warnings: list[str] = []
    maximum_row = 1
    maximum_column = 1
    minimum_row: int | None = None
    minimum_column: int | None = None
    sheet_data = child(root, "sheetData")
    for row_node in children(sheet_data, "row") if sheet_data is not None else []:
        row_reference_raw = attr(row_node, "r")
        try:
            row_reference = int(row_reference_raw or "")
        except ValueError:
            raise OfficeNativePackageError(code="xlsx_row_reference_invalid") from None
        if row_reference < 1 or row_reference > XLSX_MAX_ROWS:
            raise OfficeNativePackageError(code="xlsx_row_reference_invalid")
        if row_reference > max_rows:
            raise OfficeNativeLimitError(
                code="xlsx_row_limit",
                details={"sheet": sheet_name, "max_rows": max_rows},
            )
        if row_reference in hidden_rows or parse_bool(attr(row_node, "hidden"), False):
            continue
        for cell_index, cell_node in enumerate(children(row_node, "c"), 1):
            reference = (attr(cell_node, "r") or "").strip()
            address = _cell_address(
                reference,
                max_rows=max_rows,
                max_columns=max_columns,
            )
            if address.row != row_reference:
                raise OfficeNativePackageError(code="xlsx_cell_row_mismatch")
            if address.column in hidden_columns:
                continue
            if len(cells) >= max_cells:
                raise OfficeNativeLimitError(
                    code="xlsx_cell_limit",
                    details={"sheet": sheet_name, "max_cells": max_cells},
                )
            value, value_type, concerns = _cell_value(
                cell_node,
                shared_strings=shared_strings,
                date_styles=date_styles,
                date_1904=date_1904,
            )
            formula_node = child(cell_node, "f")
            formula = formula_node.text if formula_node is not None else None
            formula = formula.strip() if isinstance(formula, str) else None
            cache_state = "not_applicable"
            if formula is not None:
                cache_state = "present" if child(cell_node, "v") is not None else "missing"
                if cache_state == "missing":
                    concerns.append("xlsx_formula_cache_missing")
                if _EXTERNAL_FORMULA.search(formula):
                    concerns.append("xlsx_external_formula_not_executed")
            if formula is None and value in {"", None}:
                # Blank styled cells do not consume the public output budget.
                continue
            maximum_row = max(maximum_row, address.row)
            maximum_column = max(maximum_column, address.column)
            minimum_row = address.row if minimum_row is None else min(minimum_row, address.row)
            minimum_column = (
                address.column
                if minimum_column is None
                else min(minimum_column, address.column)
            )
            assert minimum_row is not None and minimum_column is not None
            if (
                (maximum_row - minimum_row + 1)
                * (maximum_column - minimum_column + 1)
                > max_sparse_area
            ):
                raise OfficeNativeLimitError(
                    code="xlsx_sparse_range_limit",
                    details={"sheet": sheet_name, "max_sparse_area": max_sparse_area},
                )
            try:
                style_index = int(attr(cell_node, "s") or "0")
            except ValueError:
                style_index = 0
                concerns.append("xlsx_style_index_invalid")
            cells.append(
                {
                    "coordinate": reference.upper().replace("$", ""),
                    "row": address.row,
                    "column": address.column,
                    "column_label": _column_label(address.column),
                    "value": value,
                    "value_type": value_type,
                    "formula": formula,
                    "cached_value": value if formula is not None and cache_state == "present" else None,
                    "formula_cache_state": cache_state,
                    "formula_executed": False,
                    "style_index": style_index,
                    "parse_concerns": list(dict.fromkeys(concerns)),
                    "native_provenance": native_provenance(
                        part=sheet_part,
                        xml_path=(
                            f"/worksheet/sheetData/row[@r='{address.row}']"
                            f"/c[@r='{reference}']"
                        ),
                        coordinate_state="logical",
                        extra={
                            "workbook_part": workbook_part,
                            "sheet_name": sheet_name,
                            "sheet_id": sheet_id,
                            "cell": reference.upper().replace("$", ""),
                        },
                    ),
                }
            )

    # Validate and retain merges without materializing their area.
    merge_ranges = [
        attr(node, "ref") or ""
        for node in descendants(root, "mergeCell")
    ]
    for reference in merge_ranges:
        if _range_area(
            reference,
            max_rows=max_rows,
            max_columns=max_columns,
        ) > max_sparse_area:
            raise OfficeNativeLimitError(code="xlsx_merge_range_limit")
    if _overlapping_ranges(
        merge_ranges,
        max_rows=max_rows,
        max_columns=max_columns,
    ):
        warnings.append("xlsx_merge_ranges_overlap")

    tables = _table_parts(
        package,
        sheet_part=sheet_part,
        relationships=relationships,
        max_rows=max_rows,
        max_columns=max_columns,
    )
    dense_rows: list[list[Any]] = []
    if cells:
        assert minimum_row is not None and minimum_column is not None
        height = maximum_row - minimum_row + 1
        width = maximum_column - minimum_column + 1
        if height * width <= max_sparse_area and height * width <= max_cells * 8:
            dense_rows = [["" for _ in range(width)] for _ in range(height)]
            for value in cells:
                dense_rows[value["row"] - minimum_row][
                    value["column"] - minimum_column
                ] = value["value"]

    table_item = content_item(
        ids,
        "table",
        0,
        value=dense_rows if dense_rows else cells,
        markdown=markdown_table(dense_rows) if dense_rows else None,
        provenance=native_provenance(
            part=sheet_part,
            xml_path="/worksheet/sheetData",
            coordinate_state="logical",
            extra={"sheet_name": sheet_name, "sheet_id": sheet_id},
        ),
        rows=dense_rows,
        cells=cells,
        html=html_table(dense_rows) if dense_rows else "",
        merged_ranges=merge_ranges,
        native_tables=tables,
        hidden_rows=sorted(hidden_rows),
        hidden_columns=[_column_label(index) for index in sorted(hidden_columns)],
        used_range=(
            f"{_column_label(min(cell['column'] for cell in cells))}"
            f"{min(cell['row'] for cell in cells)}:"
            f"{_column_label(maximum_column)}{maximum_row}"
            if cells
            else None
        ),
        dimension_reference=dimension_reference,
        parse_concerns=warnings,
    )
    items = [table_item]
    items.extend(
        _drawing_placeholders(
            root,
            sheet_part=sheet_part,
            relationships=relationships,
            ids=ids,
            reading_order=len(items),
        )
    )
    return items, warnings, (maximum_column, maximum_row)


def parse_xlsx(
    source: Any,
    *,
    filename: str = "workbook.xlsx",
    enabled: bool = True,
    max_sheets: int = 256,
    max_cells: int = 100_000,
    max_sparse_area: int = 1_000_000,
    max_rows: int = XLSX_MAX_ROWS,
    max_columns: int = XLSX_MAX_COLUMNS,
) -> dict[str, Any]:
    """Extract visible native workbook data without calculating formulas."""

    if not enabled:
        raise OfficeAdapterDisabledError(
            "XLSX native adapter is disabled.",
            details={"extension": ".xlsx"},
        )
    for name, value in (
        ("max_sheets", max_sheets),
        ("max_cells", max_cells),
        ("max_sparse_area", max_sparse_area),
        ("max_rows", max_rows),
        ("max_columns", max_columns),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if max_rows > XLSX_MAX_ROWS:
        raise ValueError(f"max_rows must not exceed {XLSX_MAX_ROWS}")
    if max_columns > XLSX_MAX_COLUMNS:
        raise ValueError(f"max_columns must not exceed {XLSX_MAX_COLUMNS}")
    package = coerce_package(source)
    workbook_part = package.main_part or "xl/workbook.xml"
    root = read_xml(package, workbook_part)
    if root is None or local_name(root.tag) != "workbook":
        raise OfficeNativePackageError(code="xlsx_workbook_root_invalid")
    relationships = read_relationships(package, workbook_part)
    workbook_directory = PurePosixPath(workbook_part).parent
    shared_strings_part = _related_or_sibling_part(
        relationships,
        "/sharedStrings",
        str(workbook_directory / "sharedStrings.xml"),
    )
    styles_part = _related_or_sibling_part(
        relationships,
        "/styles",
        str(workbook_directory / "styles.xml"),
    )
    workbook_properties = child(root, "workbookPr")
    date_1904 = parse_bool(
        attr(workbook_properties, "date1904") if workbook_properties is not None else None,
        False,
    )
    strings = _shared_strings(package, shared_strings_part)
    date_styles = _style_date_flags(package, styles_part)
    sheets_node = child(root, "sheets")
    sheet_nodes = children(sheets_node, "sheet") if sheets_node is not None else []
    if not sheet_nodes:
        raise OfficeNativePackageError(code="xlsx_sheet_list_missing")
    if len(sheet_nodes) > max_sheets:
        raise OfficeNativeLimitError(
            code="xlsx_sheet_limit",
            details={"max_sheets": max_sheets},
        )

    pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    remaining_cells = max_cells
    for workbook_order, sheet_node in enumerate(sheet_nodes, 1):
        name = (attr(sheet_node, "name") or f"Sheet{workbook_order}").strip()
        sheet_id = (attr(sheet_node, "sheetId") or str(workbook_order)).strip()
        state = (attr(sheet_node, "state") or "visible").strip().casefold()
        relationship_id = next(
            (
                value
                for value in sheet_node.attrib.values()
                if isinstance(value, str) and value.startswith("rId")
            ),
            None,
        )
        relationship = relationships.get(relationship_id or "")
        if (
            relationship is None
            or relationship.external
            or relationship.resolved_target is None
        ):
            raise OfficeNativePackageError(
                code="xlsx_sheet_relationship_invalid",
                details={"sheet": name},
            )
        if state != "visible":
            warning = "xlsx_hidden_sheet_omitted"
            warnings.append(warning)
            pages.append(
                logical_page(
                    page_index=workbook_order,
                    label=name,
                    items=[],
                    coordinate_state="logical",
                    warnings=[warning],
                    width=1.0,
                    height=1.0,
                    unit="logical",
                    extra={
                        "sheet_id": sheet_id,
                        "sheet_name": name,
                        "visibility": state,
                        "source_part": relationship.resolved_target,
                        "workbook_order": workbook_order,
                    },
                )
            )
            continue
        items, sheet_warnings, bounds = _sheet_payload(
            package,
            workbook_part=workbook_part,
            sheet_part=relationship.resolved_target,
            sheet_name=name,
            sheet_id=sheet_id,
            shared_strings=strings,
            date_styles=date_styles,
            date_1904=date_1904,
            max_cells=remaining_cells,
            max_sparse_area=max_sparse_area,
            max_rows=max_rows,
            max_columns=max_columns,
        )
        sheet_cells = sum(len(item.get("cells") or []) for item in items)
        remaining_cells -= sheet_cells
        width, height = bounds
        pages.append(
            logical_page(
                page_index=workbook_order,
                label=name,
                items=items,
                coordinate_state="logical",
                warnings=sheet_warnings,
                width=float(max(width, 1)),
                height=float(max(height, 1)),
                unit="logical",
                extra={
                    "sheet_id": sheet_id,
                    "sheet_name": name,
                    "visibility": "visible",
                    "source_part": relationship.resolved_target,
                    "relationship_id": relationship.relationship_id,
                    "workbook_order": workbook_order,
                },
            )
        )
        warnings.extend(sheet_warnings)

    result = build_parse_result(
        filename=filename,
        mime_type=XLSX_MIME_TYPE,
        source_format="XLSX",
        source_sha256=package.digest(
            [workbook_part, shared_strings_part, styles_part]
        ),
        pages=pages,
        warnings=warnings,
    )
    result["document"]["date_system"] = "1904" if date_1904 else "1900"
    result["processing"]["formula_policy"] = "preserve_without_execution"
    return result


parse_xlsx_package = parse_xlsx


class XlsxNativeAdapter:
    adapter_id = "xlsx-native"
    adapter_version = "1.0.0"
    extensions = (".xlsx",)
    mime_types = (XLSX_MIME_TYPE,)
    source_format = "XLSX"

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings
        self._manifest = office_adapter_manifest(
            adapter_id=self.adapter_id,
            input_kind="xlsx",
            extension=".xlsx",
            mime_type=XLSX_MIME_TYPE,
            coordinate_unit="logical",
            optional_capabilities=[
                "formula_cache",
                "merged_ranges",
                "native_cells",
                "native_tables",
                "sheet_order",
                "typed_values",
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
            XLSX_MIME_TYPE,
            limits=limits_from_settings(settings),
        )
        max_rows = int(getattr(settings, "adapters_xlsx_max_rows", 1_048_576))
        max_columns = int(getattr(settings, "adapters_xlsx_max_columns", 16_384))
        return parse_xlsx(
            package,
            filename=filename,
            enabled=bool(getattr(settings, "adapters_xlsx_native_enabled", False)),
            max_sheets=int(getattr(settings, "adapters_xlsx_max_sheets", 256)),
            max_cells=int(getattr(settings, "adapters_xlsx_max_cells", 100_000)),
            max_rows=max_rows,
            max_columns=max_columns,
        )

    def parse(
        self,
        source: Any,
        *,
        filename: str = "workbook.xlsx",
        enabled: bool = True,
        max_sheets: int = 256,
        max_cells: int = 100_000,
        max_sparse_area: int = 1_000_000,
        max_rows: int = XLSX_MAX_ROWS,
        max_columns: int = XLSX_MAX_COLUMNS,
    ) -> dict[str, Any]:
        return parse_xlsx(
            source,
            filename=filename,
            enabled=enabled,
            max_sheets=max_sheets,
            max_cells=max_cells,
            max_sparse_area=max_sparse_area,
            max_rows=max_rows,
            max_columns=max_columns,
        )


XLSXAdapter = XlsxNativeAdapter


__all__ = [
    "XLSXAdapter",
    "XLSX_MIME_TYPE",
    "XlsxNativeAdapter",
    "parse_xlsx",
    "parse_xlsx_package",
]
