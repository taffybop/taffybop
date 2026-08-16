"""Native PPTX/XLSX chart extraction with explicit source precedence.

Only bounded OOXML evidence is inspected.  Worksheet/embedded values outrank
chart caches, formulas remain inert text, external references are never
resolved, and unsupported or invalid charts stay as native placeholders.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Literal
from xml.etree import ElementTree as ET

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config import Settings
from app.services.office_native import (
    OfficeNativeError,
    OfficeNativeLimitError,
    OfficePackageView,
    OfficeRelationship,
    attr,
    coerce_package,
    local_name,
    read_relationships,
    read_xml,
    resolve_relationship_target,
)


OFFICE_CHART_SCHEMA_VERSION = "1.0"
_SUPPORTED_CHARTS = frozenset({"barChart", "lineChart", "pieChart", "areaChart"})
_MAX_CHARTS = 256
_MAX_SERIES = 128
_MAX_POINTS = 10_000
_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]{0,6})$")
_RANGE_RE = re.compile(
    r"^(?:'((?:[^']|'')+)'|([^!]+))!"
    r"(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6})"
    r"(?::(\$?[A-Za-z]{1,3}\$?[1-9][0-9]{0,6}))?$"
)


class OfficeChartContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OfficeChartPoint(OfficeChartContract):
    category: str = Field(min_length=1, max_length=1_024)
    series: str = Field(min_length=1, max_length=1_024)
    value: float = Field(allow_inf_nan=False)
    display_value: str = Field(min_length=1, max_length=128)
    method: Literal["cell_data", "embedded_data", "cached_data"]
    chart_part: str = Field(min_length=1, max_length=2_048)
    source_locator: str = Field(min_length=1, max_length=4_096)
    formula: str | None = Field(default=None, max_length=4_096)
    cache_value: float | None = Field(default=None, allow_inf_nan=False)
    conflict: bool = False


class OfficeChartStructure(OfficeChartContract):
    schema_version: Literal["1.0"]
    status: Literal["structured"]
    chart_type: Literal["barChart", "lineChart", "pieChart", "areaChart"]
    title: str | None = Field(default=None, max_length=4_096)
    axes: list[str] = Field(default_factory=list, max_length=8)
    legend: list[str] = Field(default_factory=list, max_length=_MAX_SERIES)
    categories: list[str] = Field(min_length=1, max_length=_MAX_POINTS)
    series: list[str] = Field(min_length=1, max_length=_MAX_SERIES)
    points: list[OfficeChartPoint] = Field(min_length=1, max_length=_MAX_POINTS)
    provenance: dict[str, Any]
    concerns: list[str] = Field(default_factory=list, max_length=256)
    markdown: str = Field(min_length=1, max_length=262_144)

    @model_validator(mode="after")
    def validate_chart(self) -> OfficeChartStructure:
        if self.series != list(dict.fromkeys(self.series)):
            raise ValueError("Office chart series are not deterministic")
        if self.legend and self.legend != self.series:
            raise ValueError("Office chart legend differs from its series")
        # Category labels are positional evidence, not identifiers. Repeated
        # labels (for example, two separate "Total" buckets) are valid and
        # must not be collapsed. The ordered projection still has to be the
        # exact series-major rectangle declared by the source chart.
        expected_count = len(self.series) * len(self.categories)
        if len(self.points) != expected_count:
            raise ValueError("Office chart point structure is incomplete")
        expected = [
            (series, category)
            for series in self.series
            for category in self.categories
        ]
        actual = [(point.series, point.category) for point in self.points]
        if actual != expected:
            raise ValueError("Office chart point structure is incomplete")
        if self.concerns != sorted(set(self.concerns)):
            raise ValueError("Office chart concerns are not deterministic")
        return self


class OfficeChartExtraction(OfficeChartContract):
    chart_part: str
    status: Literal["structured", "placeholder"]
    structure: OfficeChartStructure | None = None
    concern_codes: list[str] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_state(self) -> OfficeChartExtraction:
        if (self.status == "structured") != (self.structure is not None):
            raise ValueError("Office chart extraction state differs")
        if self.concern_codes != sorted(set(self.concern_codes)):
            raise ValueError("Office chart extraction concerns differ")
        return self


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(node) if local_name(child.tag) == name]


def _child(node: ET.Element | None, name: str) -> ET.Element | None:
    if node is None:
        return None
    return next((value for value in list(node) if local_name(value.tag) == name), None)


def _descendants(node: ET.Element | None, name: str) -> list[ET.Element]:
    if node is None:
        return []
    return [value for value in node.iter() if local_name(value.tag) == name]


def _node_value(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    value = attr(node, "val")
    if value is None:
        value = (node.text or "").strip()
    return value or None


def _rich_text(node: ET.Element | None) -> str | None:
    text = "".join((value.text or "") for value in _descendants(node, "t")).strip()
    return text or None


def _indexed_data_values(data: ET.Element) -> list[str] | None:
    """Read a complete bounded OOXML chart data vector without guessing.

    Cache and literal containers share the same ``ptCount``/``pt`` indexing
    contract. Producers may serialize points out of document order, so the
    explicit indices define order. Missing, duplicate, sparse, negative, or
    inconsistent indices are invalid evidence rather than positions we may
    infer or pad.
    """

    count_node = _child(data, "ptCount")
    count_raw = attr(count_node, "val") if count_node is not None else None
    try:
        point_count = int(count_raw or "")
    except ValueError:
        return None
    if point_count < 0 or point_count > _MAX_POINTS:
        return None
    indexed: list[tuple[int, str]] = []
    seen_indices: set[int] = set()
    for point in _descendants(data, "pt"):
        index_raw = attr(point, "idx")
        try:
            index = int(index_raw or "")
        except ValueError:
            return None
        if index < 0 or index >= point_count or index in seen_indices:
            return None
        seen_indices.add(index)
        value = _node_value(_child(point, "v")) or _rich_text(point) or ""
        indexed.append((index, value))
    if len(indexed) != point_count or seen_indices != set(range(point_count)):
        return None
    return [value for _index, value in sorted(indexed)]


def _reference(
    node: ET.Element | None,
    *,
    allow_direct_value: bool = False,
) -> tuple[str | None, list[str], Literal["cache", "literal", "missing", "invalid"]]:
    if node is None:
        return None, [], "missing"
    reference = next(
        (
            value
            for value in node.iter()
            if local_name(value.tag) in {"strRef", "numRef"}
        ),
        None,
    )
    if reference is None:
        # CT_SerTx represents a literal series name as a direct ``c:v``.
        # This form is deliberately opt-in so a value element in any other
        # chart context cannot be reinterpreted as a one-point data vector.
        if allow_direct_value:
            direct_node = _child(node, "v")
            if direct_node is not None:
                direct_value = _node_value(direct_node)
                if direct_value is None or len(direct_value) > 1_024:
                    return None, [], "invalid"
                return None, [direct_value], "literal"
        literals = next(
            (
                value
                for value in node.iter()
                if local_name(value.tag) in {"strLit", "numLit"}
            ),
            None,
        )
        if literals is None:
            return None, [], "missing"
        values = _indexed_data_values(literals)
        return (
            None,
            values or [],
            "literal" if values is not None else "invalid",
        )
    formula = _node_value(_child(reference, "f"))
    cache = next(
        (
            value
            for value in list(reference)
            if local_name(value.tag)
            in {"strCache", "numCache", "multiLvlStrCache"}
        ),
        None,
    )
    if cache is None:
        return formula, [], "missing"
    values = _indexed_data_values(cache)
    return (
        formula,
        values or [],
        "cache" if values is not None else "invalid",
    )


def _column_number(value: str) -> int:
    result = 0
    for character in value.upper():
        result = result * 26 + ord(character) - 64
    return result


def _cell_coordinate(value: str) -> tuple[int, int] | None:
    match = _CELL_RE.fullmatch(value)
    if match is None:
        return None
    return int(match.group(2)), _column_number(match.group(1))


def _range_coordinates(formula: str) -> tuple[str, list[str]] | None:
    if "[" in formula or "]" in formula or formula.startswith(("http:", "https:")):
        return None
    match = _RANGE_RE.fullmatch(formula.strip())
    if match is None:
        return None
    sheet = (match.group(1) or match.group(2) or "").replace("''", "'").strip()
    start_raw = match.group(3).replace("$", "")
    end_raw = (match.group(4) or match.group(3)).replace("$", "")
    start = _cell_coordinate(start_raw)
    end = _cell_coordinate(end_raw)
    if start is None or end is None:
        return None
    row_a, col_a = start
    row_b, col_b = end
    if row_b < row_a or col_b < col_a or (row_b - row_a + 1) * (col_b - col_a + 1) > _MAX_POINTS:
        return None

    def letters(column: int) -> str:
        result = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            result = chr(65 + remainder) + result
        return result

    cells = [
        f"{letters(column)}{row}"
        for row in range(row_a, row_b + 1)
        for column in range(col_a, col_b + 1)
    ]
    return sheet, cells


class _WorkbookData:
    def __init__(self, package: OfficePackageView) -> None:
        self._values: dict[tuple[str, str], str] = {}
        workbook_part = package.main_part or "xl/workbook.xml"
        workbook = read_xml(package, workbook_part, required=False)
        if workbook is None:
            return
        relationships = read_relationships(package, workbook_part)
        shared_part = next(
            (
                relationship.resolved_target
                for relationship in relationships.values()
                if not relationship.external
                and relationship.resolved_target is not None
                and relationship.relationship_type.casefold().endswith(
                    "/sharedstrings"
                )
            ),
            resolve_relationship_target(workbook_part, "sharedStrings.xml"),
        )
        shared: list[str] = []
        shared_root = read_xml(package, shared_part, required=False)
        if shared_root is not None:
            shared = [_rich_text(node) or "" for node in _children(shared_root, "si")]
        for sheet in _descendants(workbook, "sheet"):
            name = attr(sheet, "name")
            relationship_id = attr(sheet, "id")
            relationship = relationships.get(relationship_id or "")
            if not name or relationship is None or relationship.external or not relationship.resolved_target:
                continue
            root = read_xml(package, relationship.resolved_target, required=False)
            if root is None:
                continue
            for cell in _descendants(root, "c"):
                coordinate = (attr(cell, "r") or "").replace("$", "").upper()
                if _cell_coordinate(coordinate) is None:
                    continue
                cell_type = attr(cell, "t") or "n"
                raw = _node_value(_child(cell, "v"))
                if cell_type == "inlineStr":
                    raw = _rich_text(_child(cell, "is"))
                elif cell_type == "s" and raw is not None:
                    try:
                        raw = shared[int(raw)]
                    except (IndexError, ValueError):
                        raw = None
                if raw is not None:
                    self._values[(name, coordinate)] = raw
                if len(self._values) > _MAX_POINTS * _MAX_SERIES:
                    raise OfficeNativeLimitError(code="office_chart_cell_limit")

    def range(self, formula: str | None) -> tuple[list[str], list[str]] | None:
        if not formula:
            return None
        resolved = _range_coordinates(formula)
        if resolved is None:
            return None
        sheet, cells = resolved
        values: list[str] = []
        locators: list[str] = []
        for cell in cells:
            value = self._values.get((sheet, cell))
            if value is None:
                return None
            values.append(value)
            locators.append(f"{sheet}!{cell}")
        return values, locators


def _numeric(values: Sequence[str]) -> list[float] | None:
    result: list[float] = []
    for raw in values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        result.append(value)
    return result


def _markdown(title: str | None, points: Sequence[OfficeChartPoint]) -> str:
    lines: list[str] = []
    if title:
        lines.extend((title.replace("|", "\\|"), ""))
    lines.extend(
        (
            "| Category | Series | Value | Method |",
            "| --- | --- | ---: | --- |",
        )
    )
    for point in points:
        lines.append(
            "| "
            + " | ".join(
                (
                    point.category.replace("|", "\\|"),
                    point.series.replace("|", "\\|"),
                    point.display_value.replace("|", "\\|"),
                    point.method,
                )
            )
            + " |"
        )
    value = "\n".join(lines) + "\n"
    if len(value.encode("utf-8")) > 262_144:
        raise OfficeNativeLimitError(code="office_chart_serialization_limit")
    return value


def _extract_office_chart(
    source: Any,
    chart_part: str,
    *,
    input_format: Literal["pptx", "xlsx"],
) -> OfficeChartExtraction:
    package = coerce_package(source)
    root = read_xml(package, chart_part)
    chart_type_node = next(
        (
            node
            for node in root.iter()
            if local_name(node.tag).endswith("Chart")
            and local_name(node.tag) not in {"chart", "chartSpace"}
        ),
        None,
    )
    if chart_type_node is None or local_name(chart_type_node.tag) not in _SUPPORTED_CHARTS:
        return OfficeChartExtraction(
            chart_part=chart_part,
            status="placeholder",
            concern_codes=["office_chart_type_unsupported"],
        )
    chart_type = local_name(chart_type_node.tag)
    title_node = next(iter(_descendants(root, "title")), None)
    title = _rich_text(title_node)
    axes = [
        value
        for value in (_rich_text(node) for node in _descendants(root, "title")[1:])
        if value
    ][:8]
    concerns: set[str] = set()
    workbook = _WorkbookData(package) if input_format == "xlsx" else None
    embedded: _WorkbookData | None = None
    if input_format == "pptx":
        for relationship in read_relationships(package, chart_part).values():
            if relationship.external:
                concerns.add("office_chart_external_reference_not_fetched")
            elif relationship.resolved_target and relationship.resolved_target.endswith(
                (".xlsx", ".xlsm")
            ):
                data = package.read_part(relationship.resolved_target, required=False)
                if data is not None:
                    try:
                        embedded = _WorkbookData(coerce_package(data))
                    except OfficeNativeError:
                        concerns.add("office_chart_embedded_workbook_invalid")

    if input_format == "xlsx" and workbook is not None:
        # Chart formulas may be bound to the source workbook itself.  This
        # direct assignment makes that native evidence the first candidate.
        embedded = workbook

    series_names: list[str] = []
    chart_categories: list[str] | None = None
    points: list[OfficeChartPoint] = []
    chart_local_data_sources: set[str] = set()
    for series_index, series_node in enumerate(_children(chart_type_node, "ser"), 1):
        if series_index > _MAX_SERIES:
            raise OfficeNativeLimitError(code="office_chart_series_limit")
        candidate_workbook = workbook if input_format == "xlsx" else embedded
        name_formula, name_cache, name_source = _reference(
            _child(series_node, "tx"),
            allow_direct_value=True,
        )
        if name_source == "invalid":
            concerns.add("office_chart_data_invalid")
        elif name_source in {"cache", "literal"}:
            chart_local_data_sources.add(f"{name_source}_data")
        cached_series_name = (
            str(name_cache[0]).strip() if name_cache and name_cache[0] else None
        )
        native_series_name: str | None = None
        if candidate_workbook is not None:
            resolved_name = candidate_workbook.range(name_formula)
            if resolved_name is not None and len(resolved_name[0]) == 1:
                native_series_name = str(resolved_name[0][0]).strip() or None
        if name_source == "invalid" and native_series_name is None:
            return OfficeChartExtraction(
                chart_part=chart_part,
                status="placeholder",
                concern_codes=sorted(concerns),
            )
        if (
            native_series_name is not None
            and cached_series_name is not None
            and native_series_name != cached_series_name
        ):
            concerns.add("office_chart_cache_conflict")
        series_name = (
            native_series_name
            or cached_series_name
            or f"Series {series_index}"
        )
        category_formula, category_cache, category_source = _reference(
            _child(series_node, "cat")
        )
        if category_source == "missing":
            category_formula, category_cache, category_source = _reference(
                _child(series_node, "xVal")
            )
        value_formula, value_cache_raw, value_source = _reference(
            _child(series_node, "val")
        )
        if value_source == "missing":
            value_formula, value_cache_raw, value_source = _reference(
                _child(series_node, "yVal")
            )
        for source_kind in (category_source, value_source):
            if source_kind == "invalid":
                concerns.add("office_chart_data_invalid")
            elif source_kind in {"cache", "literal"}:
                chart_local_data_sources.add(f"{source_kind}_data")
        if any(
            formula and ("[" in formula or "]" in formula)
            for formula in (name_formula, category_formula, value_formula)
        ):
            concerns.add("office_chart_external_reference_not_fetched")

        method: Literal["cell_data", "embedded_data", "cached_data"] = "cached_data"
        source_values: list[str] | None = None
        source_locators: list[str] = []
        source_categories: list[str] | None = None
        if candidate_workbook is not None:
            resolved_values = candidate_workbook.range(value_formula)
            resolved_categories = candidate_workbook.range(category_formula)
            if resolved_values is not None and resolved_categories is not None:
                source_values, source_locators = resolved_values
                source_categories, _category_locators = resolved_categories
                method = "cell_data" if input_format == "xlsx" else "embedded_data"
        if source_values is None:
            source_values = value_cache_raw
            source_categories = category_cache
            source_label = "literal" if value_source == "literal" else "cache"
            source_locators = [
                f"{chart_part}#{source_label}[{index}]"
                for index in range(len(source_values))
            ]
        numeric_values = _numeric(source_values)
        cache_values = (
            _numeric(value_cache_raw) if value_source == "cache" else None
        )
        if (
            numeric_values is None
            or source_categories is None
            or not source_categories
            or len(source_categories) != len(numeric_values)
        ):
            concerns.add("office_chart_data_invalid")
            continue
        if method != "cached_data" and cache_values is not None and cache_values != numeric_values:
            concerns.add("office_chart_cache_conflict")
        if method != "cached_data" and category_cache:
            native_category_labels = [str(value).strip() for value in source_categories]
            cached_category_labels = [str(value).strip() for value in category_cache]
            if native_category_labels != cached_category_labels:
                concerns.add("office_chart_cache_conflict")
        if series_name in series_names:
            series_name = f"{series_name} ({series_index})"
        series_names.append(series_name)
        series_categories = [
            str(category).strip() or f"Category {index + 1}"
            for index, category in enumerate(source_categories)
        ]
        if chart_categories is None:
            chart_categories = series_categories
        elif series_categories != chart_categories:
            concerns.add("office_chart_data_invalid")
            return OfficeChartExtraction(
                chart_part=chart_part,
                status="placeholder",
                concern_codes=sorted(concerns),
            )
        for index, (category, value) in enumerate(zip(source_categories, numeric_values, strict=True)):
            category_text = series_categories[index]
            cache_value = cache_values[index] if cache_values and index < len(cache_values) else None
            points.append(
                OfficeChartPoint(
                    category=category_text,
                    series=series_name,
                    value=value,
                    display_value=format(value, ".15g"),
                    method=method,
                    chart_part=chart_part,
                    source_locator=(
                        source_locators[index]
                        if index < len(source_locators)
                        else f"{chart_part}#point[{index}]"
                    ),
                    formula=value_formula,
                    cache_value=cache_value,
                    conflict=(cache_value is not None and cache_value != value),
                )
            )
        if len(points) > _MAX_POINTS:
            raise OfficeNativeLimitError(code="office_chart_point_limit")

    # A rectangular chart projection is required by the Phase 05-style
    # structural validator.  Missing series/category points are withheld,
    # never guessed or padded.
    if (
        not points
        or chart_categories is None
        or len(points) != len(series_names) * len(chart_categories)
    ):
        concerns.add("office_chart_data_invalid")
        return OfficeChartExtraction(
            chart_part=chart_part,
            status="placeholder",
            concern_codes=sorted(concerns),
        )
    point_models = [OfficeChartPoint.model_validate(point) for point in points]
    structure = OfficeChartStructure(
        schema_version=OFFICE_CHART_SCHEMA_VERSION,
        status="structured",
        chart_type=chart_type,
        title=title,
        axes=axes,
        legend=list(series_names),
        categories=chart_categories,
        series=series_names,
        points=point_models,
        provenance={
            "method": "native_xml",
            "chart_part": chart_part,
            "input_format": input_format,
            "source_precedence": ["cell_data", "embedded_data", "cached_data"],
            "chart_local_data_sources": sorted(chart_local_data_sources),
            "external_content_fetched": False,
            "formulas_executed": False,
        },
        concerns=sorted(concerns),
        markdown=_markdown(title, point_models),
    )
    from app.services.visual_chart_validation import (
        validate_and_serialize_office_chart,
    )

    structure = validate_and_serialize_office_chart(structure)
    return OfficeChartExtraction(
        chart_part=chart_part,
        status="structured",
        structure=structure,
        concern_codes=sorted(concerns),
    )


def extract_office_chart(
    source: Any,
    chart_part: str,
    *,
    input_format: Literal["pptx", "xlsx"],
) -> OfficeChartExtraction:
    """Extract one chart, retaining invalid bounded data as a placeholder."""

    try:
        return _extract_office_chart(
            source,
            chart_part,
            input_format=input_format,
        )
    except ValidationError:
        # A schema-invalid title, label, locator, or rectangular projection is
        # unsupported native evidence, not a reason to lose the surrounding
        # Office document. Explicit resource-limit and package failures remain
        # typed exceptions and are intentionally not caught here.
        return OfficeChartExtraction(
            chart_part=chart_part,
            status="placeholder",
            concern_codes=["office_chart_data_invalid"],
        )


def _internal_relationship_targets(
    package: OfficePackageView,
    source_part: str,
    *relationship_suffixes: str,
) -> list[str]:
    suffixes = tuple(value.casefold() for value in relationship_suffixes)
    return sorted(
        {
            relationship.resolved_target
            for relationship in read_relationships(package, source_part).values()
            if not relationship.external
            and relationship.resolved_target is not None
            and relationship.relationship_type.casefold().endswith(suffixes)
        }
    )


def _discover_chart_relationship_graph(
    package: OfficePackageView,
    input_format: Literal["pptx", "xlsx"],
) -> tuple[list[str], set[str]]:
    """Discover only chart/drawing parts reachable from the validated main part."""

    main_part = package.main_part or {
        "pptx": "ppt/presentation.xml",
        "xlsx": "xl/workbook.xml",
    }[input_format]
    known_parts = set(package.part_names)
    charts = set(_internal_relationship_targets(package, main_part, "/chart"))
    drawings: set[str] = set()
    if input_format == "pptx":
        containers = _internal_relationship_targets(package, main_part, "/slide")
    else:
        containers = _internal_relationship_targets(
            package,
            main_part,
            "/worksheet",
            "/chartsheet",
        )
    for container_part in containers:
        charts.update(
            _internal_relationship_targets(package, container_part, "/chart")
        )
        if input_format == "xlsx":
            drawings.update(
                _internal_relationship_targets(package, container_part, "/drawing")
            )
    if input_format == "xlsx":
        for drawing_part in sorted(drawings):
            charts.update(
                _internal_relationship_targets(package, drawing_part, "/chart")
            )
    return (
        sorted(
            part
            for part in charts
            if part in known_parts
        ),
        {part for part in drawings if part in known_parts},
    )


def _item_chart_part(item: Mapping[str, Any]) -> str | None:
    for key in ("chart_part", "relationship_target", "source_part"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.lstrip("/")
    provenance = item.get("native_provenance")
    if isinstance(provenance, Mapping):
        for key in ("resolved_part", "relationship_target", "chart_part"):
            value = provenance.get(key)
            if isinstance(value, str) and value.strip():
                return value.lstrip("/")
    return None


def _xlsx_drawing_chart_relationships(
    item: Mapping[str, Any],
    package: OfficePackageView,
    known_chart_parts: Mapping[str, OfficeChartExtraction],
    known_drawing_parts: set[str],
) -> list[OfficeRelationship]:
    """Resolve the chart(s) owned by an XLSX drawing placeholder.

    P07-US06 deliberately represents the worksheet ``drawing`` relationship
    as one inert placeholder.  The chart stage is the first layer allowed to
    traverse that drawing's relationships, so it must perform this handoff
    rather than requiring the predecessor item to already claim chart
    semantics.
    """

    source_part = item.get("source_part")
    if not isinstance(source_part, str):
        provenance = item.get("native_provenance")
        if isinstance(provenance, Mapping):
            source_part = provenance.get("resolved_part")
    if not isinstance(source_part, str) or source_part not in known_drawing_parts:
        return []
    relationships = read_relationships(package, source_part)
    return sorted(
        (
            relationship
            for relationship in relationships.values()
            if not relationship.external
            and relationship.resolved_target in known_chart_parts
            and relationship.relationship_type.casefold().endswith("/chart")
        ),
        key=lambda relationship: (
            relationship.resolved_target or "",
            relationship.relationship_id,
        ),
    )


def apply_office_charts(
    payload: Mapping[str, Any],
    source: Any,
    settings: Settings | None = None,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    predecessor = deepcopy(dict(payload))
    active = (
        bool(settings.adapters_office_charts_enabled)
        if settings is not None and enabled is None
        else bool(enabled)
    )
    if not active:
        return predecessor
    input_format = str((predecessor.get("processing") or {}).get("input_format") or "").casefold()
    if input_format not in {"pptx", "xlsx"}:
        return predecessor
    package = coerce_package(source)
    chart_parts, known_drawing_parts = _discover_chart_relationship_graph(
        package,
        input_format,
    )
    if len(chart_parts) > _MAX_CHARTS:
        raise OfficeNativeLimitError(code="office_chart_count_limit")
    extractions = {
        part: extract_office_chart(package, part, input_format=input_format)
        for part in chart_parts
    }
    candidate = deepcopy(predecessor)
    structured_count = 0
    placeholder_count = 0

    used_item_ids = {
        item_id
        for page in candidate.get("pages") or []
        if isinstance(page, Mapping)
        for item in page.get("items") or []
        if isinstance(item, Mapping)
        and isinstance((item_id := item.get("id")), str)
    }

    def cloned_chart_id(item: Mapping[str, Any], chart_index: int) -> str:
        base = str(item.get("id") or "office-chart")
        suffix = chart_index + 1
        value = f"{base}-chart-{suffix}"
        while value in used_item_ids:
            suffix += 1
            value = f"{base}-chart-{suffix}"
        used_item_ids.add(value)
        return value

    deferred_concerns = {
        "office_chart_native_data_deferred",
        "pptx_chart_deferred",
        "xlsx_chart_deferred",
        "xlsx_drawing_native_deferred",
    }

    def bind_xlsx_relationship(
        item: dict[str, Any],
        relationship: OfficeRelationship,
    ) -> str:
        assert relationship.resolved_target is not None
        part = relationship.resolved_target
        item["type"] = "chart"
        item["content_type"] = "chart"
        item["chart_part"] = part
        item["relationship_id"] = relationship.relationship_id
        provenance = item.get("native_provenance")
        if isinstance(provenance, Mapping):
            grounded = dict(provenance)
        else:
            grounded = {}
        drawing_part = item.get("source_part")
        if isinstance(drawing_part, str):
            grounded["drawing_part"] = drawing_part
        grounded.update(
            {
                "relationship_id": relationship.relationship_id,
                "relationship_type": relationship.relationship_type,
                "relationship_target": relationship.target,
                "relationship_external": False,
                "resolved_part": part,
                "chart_part": part,
            }
        )
        item["native_provenance"] = grounded
        return part

    def apply_extraction(
        item: dict[str, Any],
        part: str,
        extraction: OfficeChartExtraction,
    ) -> None:
        nonlocal structured_count, placeholder_count
        item["type"] = "chart"
        item["content_type"] = "chart"
        item["chart_part"] = part
        current_concerns = set(item.get("parse_concerns") or []) - deferred_concerns
        if extraction.status == "structured" and extraction.structure is not None:
            chart = extraction.structure.model_dump(mode="json", exclude_none=True)
            item["office_chart"] = chart
            item["md"] = chart["markdown"]
            item["value"] = chart.get("title") or "[Structured Office chart]"
            item["placeholder"] = False
            item["fallback_eligible"] = False
            if "native_chart_pending" in item:
                item["native_chart_pending"] = False
            item["parse_concerns"] = sorted(
                current_concerns | set(extraction.concern_codes)
            )
            structured_count += 1
            return
        item["placeholder"] = True
        item["fallback_eligible"] = True
        if "native_chart_pending" in item:
            item["native_chart_pending"] = False
        item["parse_concerns"] = sorted(
            current_concerns | set(extraction.concern_codes)
        )
        placeholder_count += 1

    for page in candidate.get("pages") or []:
        if not isinstance(page, dict):
            continue
        rewritten_items: list[Any] = []
        for item in page.get("items") or []:
            if not isinstance(item, dict) or item.get("placeholder") is not True:
                rewritten_items.append(item)
                continue
            part = _item_chart_part(item)
            item_kind = str(item.get("content_type") or item.get("type")).casefold()
            if input_format == "xlsx" and item_kind in {
                "drawing",
                "unsupported_drawing",
            }:
                chart_relationships = _xlsx_drawing_chart_relationships(
                    item,
                    package,
                    extractions,
                    known_drawing_parts,
                )
                if not chart_relationships:
                    rewritten_items.append(item)
                    continue
                drawing_placeholder = deepcopy(item)
                for chart_index, relationship in enumerate(chart_relationships):
                    chart_item = (
                        item
                        if chart_index == 0
                        else deepcopy(drawing_placeholder)
                    )
                    if chart_index > 0:
                        chart_item["id"] = cloned_chart_id(item, chart_index)
                    chart_part = bind_xlsx_relationship(chart_item, relationship)
                    apply_extraction(
                        chart_item,
                        chart_part,
                        extractions[chart_part],
                    )
                    rewritten_items.append(chart_item)
                continue
            elif item_kind not in {"chart", "unsupported_chart"}:
                rewritten_items.append(item)
                continue
            if part not in extractions:
                item["parse_concerns"] = sorted(
                    set(item.get("parse_concerns") or [])
                    - deferred_concerns
                    | {"office_chart_relationship_unresolved"}
                )
                item["fallback_eligible"] = True
                placeholder_count += 1
                rewritten_items.append(item)
                continue
            apply_extraction(item, part, extractions[part])
            rewritten_items.append(item)
        page["items"] = rewritten_items
        for reading_order, item in enumerate(rewritten_items):
            if isinstance(item, dict):
                item["reading_order"] = reading_order
    candidate.setdefault("processing", {})["office_charts"] = {
        "schema_version": OFFICE_CHART_SCHEMA_VERSION,
        "status": "completed",
        "chart_part_count": len(chart_parts),
        "structured_chart_count": structured_count,
        "placeholder_chart_count": placeholder_count,
        "native_data_preferred": True,
        "formulas_executed": False,
        "external_content_fetched": False,
    }
    return candidate


extract_native_office_chart = extract_office_chart
