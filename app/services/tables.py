"""Supplemental vector-table extraction for PDFs.

pdfplumber's normal table finder handles stroked borders well. Some PDF
generators, however, paint borders as collections of very thin filled
rectangles. This module reconstructs those borders and supplies them back to
pdfplumber as explicit row and column boundaries.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import pdfplumber


_MAX_RULE_THICKNESS = 1.75
_MIN_RULE_LENGTH = 6.0
_MIN_TABLE_WIDTH = 24.0
_Y_CLUSTER_TOLERANCE = 1.25
_X_JOIN_TOLERANCE = 2.5
_BOUNDARY_TOLERANCE = 3.0
_VERTICAL_SUPPORT_TOLERANCE = 2.0
_MIN_VISUAL_ROW_HEIGHT = 24.0
_MAX_UNCONNECTED_RULE_GAP = 144.0


@dataclass(slots=True)
class RawTable:
    """A text table located on a one-based physical PDF page."""

    page_index: int
    bbox: dict[str, float]
    rows: list[list[str]]
    row_bboxes: list[dict[str, float]]
    parse_concerns: list[str] = field(default_factory=list)
    cell_bboxes: tuple[tuple[dict[str, float] | None, ...], ...] = ()
    geometry_inferred: bool | None = None
    logical_rows_recovered: bool = False


@dataclass(slots=True)
class _HorizontalRule:
    y: float
    boundaries: tuple[float, ...]


@dataclass(slots=True)
class _VerticalRule:
    x: float
    top: float
    bottom: float


@dataclass(slots=True)
class _Candidate:
    table: RawTable
    inferred: bool


def _number_clusters(values: Iterable[float], tolerance: float) -> list[list[float]]:
    """Cluster sorted scalar coordinates that differ only by drawing noise."""

    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or value - median(clusters[-1]) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return clusters


def _bbox_dict(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    """Convert pdfplumber's top-left x0/top/x1/bottom tuple to x/y/w/h."""

    x0, top, x1, bottom = (float(value) for value in bbox)
    return {
        "x": round(x0, 3),
        "y": round(top, 3),
        "w": round(max(0.0, x1 - x0), 3),
        "h": round(max(0.0, bottom - top), 3),
    }


def _normalize_cell(value: Any) -> str:
    """Normalize incidental PDF spacing while retaining meaningful line breaks."""

    if value is None:
        return ""
    lines = []
    for line in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        clean = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if clean:
            lines.append(clean)
    return "\n".join(lines)


def _clean_table(
    page_index: int,
    table: Any,
    *,
    preserve_cell_geometry: bool = False,
) -> RawTable | None:
    """Extract rows, remove phantom margins, and retain source cell geometry."""

    extracted = table.extract(x_tolerance=2, y_tolerance=2) or []
    table_rows = list(getattr(table, "rows", []))
    row_count = max(len(extracted), len(table_rows))
    if row_count == 0:
        return None
    if preserve_cell_geometry and row_count > 4_096:
        return None

    normalized: list[list[str]] = []
    row_bboxes: list[dict[str, float]] = []
    cell_bboxes: list[list[dict[str, float] | None]] | None = None
    geometry_malformed = False
    if preserve_cell_geometry:
        cell_bboxes = []
    for index in range(row_count):
        values = extracted[index] if index < len(extracted) else []
        normalized.append([_normalize_cell(value) for value in values])
        if index < len(table_rows) and getattr(table_rows[index], "bbox", None):
            row_bboxes.append(_bbox_dict(table_rows[index].bbox))
        else:
            row_bboxes.append(_bbox_dict(table.bbox))
        if preserve_cell_geometry and cell_bboxes is not None:
            raw_cells = (
                getattr(table_rows[index], "cells", ())
                if index < len(table_rows)
                else ()
            )
            if not isinstance(raw_cells, (list, tuple)):
                geometry_malformed = True
                raw_cells = ()
            if len(raw_cells) > 256:
                return None
            geometry_row: list[dict[str, float] | None] = []
            for raw_cell in raw_cells:
                if raw_cell is None:
                    geometry_row.append(None)
                    continue
                if not isinstance(raw_cell, (list, tuple)) or len(raw_cell) != 4:
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                try:
                    coordinates = tuple(float(value) for value in raw_cell)
                except (TypeError, ValueError):
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                if (
                    any(
                        value != value or abs(value) == float("inf")
                        for value in coordinates
                    )
                    or coordinates[2] <= coordinates[0]
                    or coordinates[3] <= coordinates[1]
                ):
                    geometry_malformed = True
                    geometry_row.append(None)
                    continue
                geometry_row.append(_bbox_dict(coordinates))
            cell_bboxes.append(geometry_row)

    column_count = max((len(row) for row in normalized), default=0)
    if cell_bboxes is not None:
        column_count = max(
            column_count,
            max((len(row) for row in cell_bboxes), default=0),
        )
    if column_count == 0:
        return None
    if preserve_cell_geometry and (
        column_count > 256 or row_count * column_count > 65_536
    ):
        return None
    for row in normalized:
        row.extend([""] * (column_count - len(row)))
    if cell_bboxes is not None:
        for row in cell_bboxes:
            row.extend([None] * (column_count - len(row)))

    # Only trim unsupported empty edge columns. Source geometry makes an
    # explicit blank cell independently retainable.
    has_text = any(cell for row in normalized for cell in row)
    left, right = 0, column_count
    if cell_bboxes is not None:
        while left < right and all(
            not row[left] and cell_bboxes[index][left] is None
            for index, row in enumerate(normalized)
        ):
            left += 1
        while right > left and all(
            not row[right - 1] and cell_bboxes[index][right - 1] is None
            for index, row in enumerate(normalized)
        ):
            right -= 1
        normalized = [row[left:right] for row in normalized]
        cell_bboxes = [row[left:right] for row in cell_bboxes]
    elif has_text:
        while left < right and all(not row[left] for row in normalized):
            left += 1
        while right > left and all(not row[right - 1] for row in normalized):
            right -= 1
        normalized = [row[left:right] for row in normalized]

    kept_rows: list[list[str]] = []
    kept_bboxes: list[dict[str, float]] = []
    kept_cell_bboxes: list[list[dict[str, float] | None]] | None = None
    if cell_bboxes is not None:
        kept_cell_bboxes = []
    preserved_visual_row = False
    for index, (row, bbox) in enumerate(zip(normalized, row_bboxes, strict=True)):
        row_has_text = any(row)
        row_has_geometry = (
            cell_bboxes is not None and any(cell_bboxes[index])
        )
        is_visual_row = not row_has_text and bbox["h"] >= _MIN_VISUAL_ROW_HEIGHT
        if row_has_text or row_has_geometry or is_visual_row:
            kept_rows.append(row)
            kept_bboxes.append(bbox)
            if kept_cell_bboxes is not None and cell_bboxes is not None:
                kept_cell_bboxes.append(cell_bboxes[index])
            preserved_visual_row = preserved_visual_row or is_visual_row

    if not kept_rows:
        return None

    concerns = ["contains_empty_visual_rows"] if preserved_visual_row else []
    if preserve_cell_geometry and geometry_malformed:
        concerns.append("contains_malformed_cell_geometry")
    return RawTable(
        page_index=page_index,
        bbox=_bbox_dict(table.bbox),
        rows=kept_rows,
        row_bboxes=kept_bboxes,
        parse_concerns=concerns,
        cell_bboxes=(
            tuple(tuple(cell for cell in row) for row in kept_cell_bboxes)
            if kept_cell_bboxes is not None and not geometry_malformed
            else ()
        ),
    )


def _word_center(word: Mapping[str, Any]) -> tuple[float, float]:
    """Return the displayed-page center of a pdfplumber word."""

    return (
        (float(word["x0"]) + float(word["x1"])) / 2,
        (float(word["top"]) + float(word["bottom"])) / 2,
    )


def _words_in_box(
    words: Iterable[Mapping[str, Any]],
    box: Mapping[str, float],
    *,
    upright: bool | None = None,
) -> list[Mapping[str, Any]]:
    """Select words by center point so stroked borders cannot clip glyphs."""

    left = float(box["x"])
    top = float(box["y"])
    right = left + float(box["w"])
    bottom = top + float(box["h"])
    selected: list[Mapping[str, Any]] = []
    for word in words:
        if upright is not None and bool(word.get("upright", True)) is not upright:
            continue
        try:
            center_x, center_y = _word_center(word)
        except (KeyError, TypeError, ValueError):
            continue
        if left <= center_x <= right and top <= center_y <= bottom:
            selected.append(word)
    return selected


def _cluster_words_by_axis(
    words: Iterable[Mapping[str, Any]],
    *,
    axis: str,
    tolerance: float,
) -> list[list[Mapping[str, Any]]]:
    """Cluster words with coincident displayed-page x or y centers."""

    axis_index = 0 if axis == "x" else 1
    ordered = sorted(
        words,
        key=lambda word: (
            _word_center(word)[axis_index],
            _word_center(word)[1 - axis_index],
        ),
    )
    clusters: list[list[Mapping[str, Any]]] = []
    for word in ordered:
        coordinate = _word_center(word)[axis_index]
        if not clusters:
            clusters.append([word])
            continue
        cluster_coordinate = median(
            _word_center(member)[axis_index] for member in clusters[-1]
        )
        if coordinate - cluster_coordinate > tolerance:
            clusters.append([word])
        else:
            clusters[-1].append(word)
    return clusters


def _rotated_cell_text(words: Iterable[Mapping[str, Any]]) -> str:
    """Restore clockwise-rotated header words to visual reading order."""

    vertical_lines = _cluster_words_by_axis(words, axis="x", tolerance=2.0)
    rendered_lines: list[str] = []
    for line in vertical_lines:
        # pdfplumber reports clockwise-rotated glyph sequences in reverse.
        # Reading each vertical line bottom-to-top and reversing each token
        # restores the page-visible word order without a language lexicon.
        tokens = [
            str(word.get("text") or "")[::-1]
            for word in sorted(
                line,
                key=lambda word: (
                    float(word.get("top", 0.0)),
                    float(word.get("x0", 0.0)),
                ),
                reverse=True,
            )
            if str(word.get("text") or "")
        ]
        if tokens:
            rendered_lines.append(" ".join(tokens))
    return " ".join(rendered_lines).strip()


def _dense_grid_logical_rows(
    table: RawTable,
    page_words: Sequence[Mapping[str, Any]],
) -> RawTable | None:
    """Expand source-packed ruled rows into their visible logical rows.

    Some timetable generators draw a full column grid but only one horizontal
    rule for each group of several services. pdfplumber correctly recovers the
    13 source columns, yet returns five visible baselines joined by newlines in
    each physical band. A competing layout model may instead recover the row
    baselines while silently collapsing a narrow column. This routine uses the
    exact vector cell boundaries and displayed word baselines together, so the
    supplemental candidate carries both dimensions without guessing from cell
    text or document-specific labels.
    """

    column_count = max((len(row) for row in table.rows), default=0)
    if (
        column_count < 6
        or len(table.rows) < 3
        or not table.cell_bboxes
        or len(table.cell_bboxes) != len(table.rows)
        or len(table.row_bboxes) != len(table.rows)
        or any(len(row) != column_count for row in table.rows)
        or any(len(row) != column_count for row in table.cell_bboxes)
    ):
        return None

    row_word_sets = [
        _words_in_box(page_words, row_box)
        for row_box in table.row_bboxes
    ]
    rotated_ratios = []
    for words in row_word_sets:
        rotated_count = sum(not bool(word.get("upright", True)) for word in words)
        rotated_ratios.append(rotated_count / len(words) if words else 0.0)
    header_candidates = [
        index
        for index, ratio in enumerate(rotated_ratios[: min(4, len(table.rows))])
        if ratio >= 0.60
    ]
    if len(header_candidates) != 1:
        return None
    header_index = header_candidates[0]
    if header_index + 1 >= len(table.rows):
        return None

    logical_word_rows: list[list[list[Mapping[str, Any]]]] = []
    logical_bounds: list[list[tuple[float, float]]] = []
    for row_index in range(header_index + 1, len(table.rows)):
        row_box = table.row_bboxes[row_index]
        upright_words = _words_in_box(
            row_word_sets[row_index], row_box, upright=True
        )
        baselines = _cluster_words_by_axis(
            upright_words,
            axis="y",
            tolerance=2.5,
        )
        if len(baselines) < 2 or len(baselines) > 32:
            return None
        centers = [
            median(_word_center(word)[1] for word in baseline)
            for baseline in baselines
        ]
        top = float(row_box["y"])
        bottom = top + float(row_box["h"])
        boundaries = [top]
        boundaries.extend(
            (before + after) / 2
            for before, after in zip(centers, centers[1:])
        )
        boundaries.append(bottom)
        logical_word_rows.append(baselines)
        logical_bounds.append(
            list(zip(boundaries, boundaries[1:]))
        )

    group_sizes = [len(rows) for rows in logical_word_rows]
    if median(group_sizes) < 3 or max(group_sizes) - min(group_sizes) > 1:
        return None

    expanded_rows: list[list[str]] = []
    expanded_row_bboxes: list[dict[str, float]] = []
    expanded_cell_bboxes: list[list[dict[str, float] | None]] = []

    # Preserve leading spanning title bands using source words rather than
    # fragments clipped at column boundaries.
    for row_index in range(header_index):
        title_words = [
            word
            for word in row_word_sets[row_index]
            if bool(word.get("upright", True))
        ]
        title = " ".join(
            str(word.get("text") or "")
            for word in sorted(
                title_words,
                key=lambda word: (
                    float(word.get("top", 0.0)),
                    float(word.get("x0", 0.0)),
                ),
            )
            if str(word.get("text") or "")
        ).strip()
        if not title:
            return None
        expanded_rows.append([title] + [""] * (column_count - 1))
        expanded_row_bboxes.append(dict(table.row_bboxes[row_index]))
        expanded_cell_bboxes.append(
            [
                dict(cell) if cell is not None else None
                for cell in table.cell_bboxes[row_index]
            ]
        )

    header_row: list[str] = []
    for cell_box in table.cell_bboxes[header_index]:
        if cell_box is None:
            return None
        rotated_words = _words_in_box(page_words, cell_box, upright=False)
        header_text = _rotated_cell_text(rotated_words)
        if not header_text:
            return None
        header_row.append(header_text)
    expanded_rows.append(header_row)
    expanded_row_bboxes.append(dict(table.row_bboxes[header_index]))
    expanded_cell_bboxes.append(
        [
            dict(cell) if cell is not None else None
            for cell in table.cell_bboxes[header_index]
        ]
    )

    for relative_index, baselines in enumerate(logical_word_rows):
        source_row_index = header_index + 1 + relative_index
        source_cells = table.cell_bboxes[source_row_index]
        for baseline, (top, bottom) in zip(
            baselines,
            logical_bounds[relative_index],
            strict=True,
        ):
            row = ["" for _ in range(column_count)]
            for word in baseline:
                center_x, _ = _word_center(word)
                column = next(
                    (
                        index
                        for index, cell_box in enumerate(source_cells)
                        if cell_box is not None
                        and float(cell_box["x"])
                        <= center_x
                        <= float(cell_box["x"]) + float(cell_box["w"])
                    ),
                    None,
                )
                if column is None:
                    return None
                token = str(word.get("text") or "").strip()
                if token:
                    row[column] = " ".join(
                        part for part in (row[column], token) if part
                    )
            if sum(bool(value) for value in row) < 2:
                return None
            expanded_rows.append(row)
            expanded_row_bboxes.append(
                {
                    "x": float(table.bbox["x"]),
                    "y": round(top, 3),
                    "w": float(table.bbox["w"]),
                    "h": round(bottom - top, 3),
                }
            )
            expanded_cell_bboxes.append(
                [
                    {
                        "x": float(cell_box["x"]),
                        "y": round(top, 3),
                        "w": float(cell_box["w"]),
                        "h": round(bottom - top, 3),
                    }
                    if cell_box is not None
                    else None
                    for cell_box in source_cells
                ]
            )

    if len(expanded_rows) <= len(table.rows):
        return None
    return RawTable(
        page_index=table.page_index,
        bbox=dict(table.bbox),
        rows=expanded_rows,
        row_bboxes=expanded_row_bboxes,
        parse_concerns=list(table.parse_concerns),
        cell_bboxes=tuple(
            tuple(cell for cell in row) for row in expanded_cell_bboxes
        ),
        geometry_inferred=table.geometry_inferred,
        logical_rows_recovered=True,
    )


def _is_fill_area_rect(obj: Mapping[str, Any]) -> bool:
    """Identify filled areas whose perimeter is not a visible table border."""

    if (
        obj.get("object_type") != "rect"
        or obj.get("fill") is not True
        or bool(obj.get("stroke"))
    ):
        return False
    try:
        width = float(obj.get("width") or 0.0)
        height = float(obj.get("height") or 0.0)
    except (TypeError, ValueError):
        return False
    return width > _MAX_RULE_THICKNESS and height > _MAX_RULE_THICKNESS


def _has_supported_standard_geometry(table: RawTable) -> bool:
    """Reject ragged one-column regions produced from unrelated text boxes."""

    column_count = max((len(row) for row in table.rows), default=0)
    if column_count != 1:
        return True
    if len(table.rows) < 2 or len(table.row_bboxes) != len(table.rows):
        return False

    table_left = float(table.bbox["x"])
    table_right = table_left + float(table.bbox["w"])
    return all(
        abs(float(row_box["x"]) - table_left) <= _BOUNDARY_TOLERANCE
        and abs(
            float(row_box["x"]) + float(row_box["w"]) - table_right
        )
        <= _BOUNDARY_TOLERANCE
        for row_box in table.row_bboxes
    )


def _drawing_primitives(
    page: Any,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float]], list[_VerticalRule]]:
    """Return horizontal segments, tiny joints, and thin vertical rules."""

    horizontal: list[tuple[float, float, float]] = []
    joints: list[tuple[float, float]] = []
    vertical: list[_VerticalRule] = []

    for rect in page.rects:
        x0, x1 = float(rect["x0"]), float(rect["x1"])
        top, bottom = float(rect["top"]), float(rect["bottom"])
        width, height = x1 - x0, bottom - top
        if width <= _MAX_RULE_THICKNESS and height <= _MAX_RULE_THICKNESS:
            joints.append(((x0 + x1) / 2, (top + bottom) / 2))
        elif height <= _MAX_RULE_THICKNESS and width >= _MIN_RULE_LENGTH:
            horizontal.append((x0, x1, (top + bottom) / 2))
        elif width <= _MAX_RULE_THICKNESS and height >= _MIN_RULE_LENGTH:
            vertical.append(_VerticalRule((x0 + x1) / 2, top, bottom))

    # True line operators need no rectangle reconstruction, but including them
    # lets the same inference path bridge mixed line/filled-border tables.
    for line in page.lines:
        x0, x1 = sorted((float(line["x0"]), float(line["x1"])))
        top, bottom = sorted((float(line["top"]), float(line["bottom"])))
        width, height = x1 - x0, bottom - top
        if height <= _MAX_RULE_THICKNESS and width >= _MIN_RULE_LENGTH:
            horizontal.append((x0, x1, (top + bottom) / 2))
        elif width <= _MAX_RULE_THICKNESS and height >= _MIN_RULE_LENGTH:
            vertical.append(_VerticalRule((x0 + x1) / 2, top, bottom))

    return horizontal, joints, vertical


def _horizontal_rules(
    segments: list[tuple[float, float, float]],
    joints: list[tuple[float, float]],
) -> list[_HorizontalRule]:
    """Rebuild full horizontal rules and infer their repeated column joints."""

    y_clusters: list[list[tuple[float, float, float]]] = []
    for segment in sorted(segments, key=lambda value: (value[2], value[0])):
        if (
            not y_clusters
            or segment[2] - median(value[2] for value in y_clusters[-1])
            > _Y_CLUSTER_TOLERANCE
        ):
            y_clusters.append([segment])
        else:
            y_clusters[-1].append(segment)

    rules: list[_HorizontalRule] = []
    for y_cluster in y_clusters:
        y = median(segment[2] for segment in y_cluster)
        unique_segments = sorted(
            {
                (round(segment[0], 3), round(segment[1], 3))
                for segment in y_cluster
                if segment[1] - segment[0] >= _MIN_RULE_LENGTH
            }
        )
        components: list[list[tuple[float, float]]] = []
        for segment in unique_segments:
            disconnected = (
                components
                and segment[0] - max(value[1] for value in components[-1])
                > _X_JOIN_TOLERANCE
            )
            if not components or disconnected:
                components.append([segment])
            else:
                components[-1].append(segment)

        for component in components:
            x0 = min(segment[0] for segment in component)
            x1 = max(segment[1] for segment in component)
            if x1 - x0 < _MIN_TABLE_WIDTH:
                continue

            boundary_values = [x0, x1]
            ordered = sorted(component)
            for previous, following in zip(ordered, ordered[1:]):
                gap = following[0] - previous[1]
                if -_Y_CLUSTER_TOLERANCE <= gap <= _X_JOIN_TOLERANCE:
                    boundary_values.append((previous[1] + following[0]) / 2)
            boundary_values.extend(
                x
                for x, joint_y in joints
                if abs(joint_y - y) <= _Y_CLUSTER_TOLERANCE
                and x0 - _X_JOIN_TOLERANCE <= x <= x1 + _X_JOIN_TOLERANCE
            )

            x_clusters = _number_clusters(boundary_values, _Y_CLUSTER_TOLERANCE)
            boundaries = tuple(median(cluster) for cluster in x_clusters)
            if len(boundaries) >= 2:
                rules.append(_HorizontalRule(y=y, boundaries=boundaries))
    return rules


def _same_signature(left: _HorizontalRule, right: _HorizontalRule) -> bool:
    """Check whether two rules describe the same table width and columns."""

    return len(left.boundaries) == len(right.boundaries) and all(
        abs(a - b) <= _BOUNDARY_TOLERANCE
        for a, b in zip(left.boundaries, right.boundaries, strict=True)
    )


def _has_vertical_support(
    vertical: list[_VerticalRule],
    x: float,
    top: float,
    bottom: float,
) -> bool:
    """Return whether a thin vertical rule connects two horizontal rules."""

    return any(
        abs(rule.x - x) <= _VERTICAL_SUPPORT_TOLERANCE
        and rule.top <= top + _VERTICAL_SUPPORT_TOLERANCE
        and rule.bottom >= bottom - _VERTICAL_SUPPORT_TOLERANCE
        for rule in vertical
    )


def _split_rule_group(
    group: list[_HorizontalRule],
    vertical: list[_VerticalRule],
) -> list[list[_HorizontalRule]]:
    """Split repeated rule signatures into connected table-shaped runs."""

    ordered = sorted(group, key=lambda rule: rule.y)
    if len(ordered) < 2:
        return []

    column_count = len(ordered[0].boundaries) - 1
    runs: list[list[_HorizontalRule]] = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:]):
        left = median((previous.boundaries[0], current.boundaries[0]))
        right = median((previous.boundaries[-1], current.boundaries[-1]))
        outline_connected = _has_vertical_support(
            vertical, left, previous.y, current.y
        ) and _has_vertical_support(vertical, right, previous.y, current.y)
        gap_too_large = current.y - previous.y > _MAX_UNCONNECTED_RULE_GAP

        if column_count == 1 and not outline_connected:
            runs.append([current])
        elif column_count > 1 and gap_too_large and not outline_connected:
            runs.append([current])
        else:
            runs[-1].append(current)

    valid: list[list[_HorizontalRule]] = []
    for run in runs:
        if len(run) < 2:
            continue
        if len(run[0].boundaries) > 2:
            valid.append(run)
            continue
        if all(
            _has_vertical_support(
                vertical,
                median((before.boundaries[0], after.boundaries[0])),
                before.y,
                after.y,
            )
            and _has_vertical_support(
                vertical,
                median((before.boundaries[-1], after.boundaries[-1])),
                before.y,
                after.y,
            )
            for before, after in zip(run, run[1:])
        ):
            valid.append(run)
    return valid


def _inferred_rule_groups(page: Any) -> list[tuple[list[float], list[float]]]:
    """Infer explicit x/y table boundaries from thin filled PDF geometry."""

    segments, joints, vertical = _drawing_primitives(page)
    rules = _horizontal_rules(segments, joints)
    signature_groups: list[list[_HorizontalRule]] = []
    for rule in sorted(rules, key=lambda value: value.y):
        for group in signature_groups:
            if _same_signature(group[0], rule):
                group.append(rule)
                break
        else:
            signature_groups.append([rule])

    results: list[tuple[list[float], list[float]]] = []
    for group in signature_groups:
        for run in _split_rule_group(group, vertical):
            x_boundaries = [
                median(rule.boundaries[index] for rule in run)
                for index in range(len(run[0].boundaries))
            ]
            y_boundaries = [rule.y for rule in run]
            results.append((x_boundaries, y_boundaries))
    return results


def _overlap_area(
    left: dict[str, float],
    right: dict[str, float],
) -> float:
    """Calculate intersection area for x/y/w/h boxes."""

    x0 = max(left["x"], right["x"])
    y0 = max(left["y"], right["y"])
    x1 = min(left["x"] + left["w"], right["x"] + right["w"])
    y1 = min(left["y"] + left["h"], right["y"] + right["h"])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _is_duplicate(left: RawTable, right: RawTable) -> bool:
    """Treat near-identical or substantially contained table boxes as duplicates."""

    intersection = _overlap_area(left.bbox, right.bbox)
    left_area = left.bbox["w"] * left.bbox["h"]
    right_area = right.bbox["w"] * right.bbox["h"]
    smaller = min(left_area, right_area)
    union = left_area + right_area - intersection
    return (
        smaller > 0
        and (
            intersection / smaller >= 0.82
            or (union > 0 and intersection / union >= 0.55)
        )
    )


def _page_candidates(
    page: Any,
    page_index: int,
    *,
    preserve_cell_geometry: bool = False,
) -> list[_Candidate]:
    """Run inferred explicit-border extraction plus pdfplumber's standard finder."""

    inferred: list[_Candidate] = []
    for x_boundaries, y_boundaries in _inferred_rule_groups(page):
        settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "explicit",
            "explicit_vertical_lines": x_boundaries,
            "explicit_horizontal_lines": y_boundaries,
            "snap_tolerance": 1.5,
            "join_tolerance": 1.5,
            "intersection_tolerance": 2.5,
            "edge_min_length": 3,
        }
        expected_bbox = (
            min(x_boundaries),
            min(y_boundaries),
            max(x_boundaries),
            max(y_boundaries),
        )
        expected_area = (expected_bbox[2] - expected_bbox[0]) * (
            expected_bbox[3] - expected_bbox[1]
        )
        for table in page.find_tables(settings):
            table_area = (table.bbox[2] - table.bbox[0]) * (
                table.bbox[3] - table.bbox[1]
            )
            intersection = _overlap_area(
                _bbox_dict(expected_bbox), _bbox_dict(table.bbox)
            )
            if min(expected_area, table_area) <= 0 or intersection / min(
                expected_area, table_area
            ) < 0.8:
                continue
            clean = _clean_table(
                page_index,
                table,
                preserve_cell_geometry=preserve_cell_geometry,
            )
            if clean is not None:
                inferred.append(_Candidate(clean, inferred=True))

    # pdfplumber exposes the perimeter of every rectangle as table edges.
    # Large fill-only rectangles are commonly text backgrounds or marked
    # content spans, so letting them participate can turn wrapped paragraphs
    # into ragged one-column tables and crop words at rectangle boundaries.
    standard_page = page.filter(lambda obj: not _is_fill_area_rect(obj))
    standard: list[_Candidate] = []
    for table in standard_page.find_tables():
        clean = _clean_table(
            page_index,
            table,
            preserve_cell_geometry=preserve_cell_geometry,
        )
        if clean is not None and _has_supported_standard_geometry(clean):
            standard.append(_Candidate(clean, inferred=False))

    # Inferred borders intentionally take precedence: default extraction often
    # mistakes filled text backgrounds for extra rows and tiny joints for
    # phantom columns.
    selected: list[_Candidate] = []
    for candidate in sorted(
        inferred,
        key=lambda value: value.table.bbox["w"] * value.table.bbox["h"],
        reverse=True,
    ):
        if not any(_is_duplicate(candidate.table, item.table) for item in selected):
            selected.append(candidate)
    for candidate in standard:
        if not any(_is_duplicate(candidate.table, item.table) for item in selected):
            selected.append(candidate)
    if preserve_cell_geometry:
        try:
            page_words = page.extract_words(extra_attrs=["upright"])
        except (AttributeError, KeyError, TypeError, ValueError):
            page_words = []
        for candidate in selected:
            candidate.table.geometry_inferred = candidate.inferred
            expanded = _dense_grid_logical_rows(candidate.table, page_words)
            if expanded is not None:
                candidate.table = expanded
    return selected


def extract_vector_tables(
    pdf_bytes: bytes,
    *,
    preserve_cell_geometry: bool = False,
) -> dict[int, list[RawTable]]:
    """Extract bordered vector tables, keyed by one-based physical page index."""

    if not pdf_bytes:
        raise ValueError("pdf_bytes must not be empty")

    result: dict[int, list[RawTable]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            candidates = _page_candidates(
                page,
                page_index,
                preserve_cell_geometry=preserve_cell_geometry,
            )
            tables = sorted(
                (candidate.table for candidate in candidates),
                key=lambda table: (table.bbox["y"], table.bbox["x"]),
            )
            result[page_index] = tables
    return result
