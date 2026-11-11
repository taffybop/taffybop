"""Conservative local Docling retry for a collapsed, visibly ruled image table.

This does not infer a grid from text. A complete thin pixel grid supplies the
expected topology; Docling still supplies every cell value and its geometry.
Only the outer border is excluded from the retry crop, leaving text untouched.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np
from PIL import Image

from app.services.input_documents import SourcePage


@dataclass(frozen=True)
class _Grid:
    crop: tuple[int, int, int, int]
    xs: tuple[float, ...]
    ys: tuple[float, ...]
    png: bytes


def _box(value: Any, height: int) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        if any(type(value[key]) not in (int, float) for key in ("l", "t", "r", "b")):
            return None
        left, top, right, bottom = (float(value[key]) for key in ("l", "t", "r", "b"))
        origin = value.get("coord_origin")
        if origin == "BOTTOMLEFT":
            top, bottom = height - top, height - bottom
        elif origin != "TOPLEFT":
            return None
        if not all(math.isfinite(v) for v in (left, top, right, bottom)):
            return None
        return (left, top, right, bottom) if right > left and bottom > top else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _bands(indexes: np.ndarray) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for raw in indexes:
        value = int(raw)
        if result and value == result[-1][1] + 1:
            result[-1] = (result[-1][0], value)
        else:
            result.append((value, value))
    return result


def _detect_grid(page: SourcePage, table: dict[str, Any], max_pixels: int) -> _Grid | None:
    prov = table.get("prov")
    if not isinstance(prov, list) or len(prov) != 1 or not isinstance(prov[0], dict):
        return None
    if type(prov[0].get("page_no")) is not int or prov[0]["page_no"] != page.page_index:
        return None
    box = _box(prov[0].get("bbox"), page.pixel_height)
    if box is None:
        return None
    left, top, right, bottom = box
    if left < 0 or top < 0 or right > page.pixel_width or bottom > page.pixel_height:
        return None
    width, height = right - left, bottom - top
    if width < 60 or height < 40 or width * height > max_pixels:
        return None
    # Model boxes can stop a few pixels short of the outer rule. Padding is
    # limited and clipped to the actual source page; returned OCR never uses
    # guessed or out-of-page coordinates.
    padding = max(4, min(12, round(min(width, height) * 0.03)))
    bounds = (
        max(0, math.floor(left) - padding),
        max(0, math.floor(top) - padding),
        min(page.pixel_width, math.ceil(right) + padding),
        min(page.pixel_height, math.ceil(bottom) + padding),
    )
    if (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) > max_pixels:
        return None
    with Image.open(io.BytesIO(page.png_bytes)) as source:
        if source.size != (page.pixel_width, page.pixel_height):
            return None
        with source.crop(bounds) as region:
            with region.convert("L") as gray:
                mask = np.asarray(gray) < 160
        horizontal = _bands(np.flatnonzero(mask.mean(axis=1) >= 0.85))
        vertical = _bands(np.flatnonzero(mask.mean(axis=0) >= 0.85))
        if not (3 <= len(horizontal) <= 33 and 3 <= len(vertical) <= 17):
            return None
        if (len(horizontal) - 1) * (len(vertical) - 1) > 256:
            return None
        max_thickness = max(2, min(8, round(min(width, height) * 0.02)))
        if any(end - start + 1 > max_thickness for start, end in horizontal + vertical):
            return None
        # Require unbroken rules, including all four outer edges. Separate
        # tables, partial boxes, merged cells and text-only alignments refuse.
        x0, x1 = vertical[0][0], vertical[-1][1]
        y0, y1 = horizontal[0][0], horizontal[-1][1]
        if any(
            not np.all(mask[start:end + 1, x0:x1 + 1].any(axis=0))
            for start, end in horizontal
        ):
            return None
        if any(
            not np.all(mask[y0:y1 + 1, start:end + 1].any(axis=1))
            for start, end in vertical
        ):
            return None
        xs = tuple(bounds[0] + (a + b) / 2 for a, b in vertical)
        ys = tuple(bounds[1] + (a + b) / 2 for a, b in horizontal)
        if any(
            b - a < 16
            for boundaries in (xs, ys)
            for a, b in zip(boundaries, boundaries[1:])
        ):
            return None
        tolerance = padding + max_thickness
        if any(abs(a - b) > tolerance for a, b in zip((xs[0], ys[0], xs[-1], ys[-1]), box)):
            return None
        crop = (
            bounds[0] + vertical[0][1] + 2,
            bounds[1] + horizontal[0][1] + 2,
            bounds[0] + vertical[-1][0] - 1,
            bounds[1] + horizontal[-1][0] - 1,
        )
        if crop[2] <= crop[0] or crop[3] <= crop[1]:
            return None
        with source.crop(crop) as cropped:
            output = io.BytesIO()
            cropped.save(output, format="PNG")
        return _Grid(crop, xs, ys, output.getvalue())


def _text(value: Any) -> str | None:
    return " ".join(value.split()) if isinstance(value, str) else None


def _inside(
    box: tuple[float, float, float, float],
    cell: tuple[float, float, float, float],
    tolerance: float = 1.0,
) -> bool:
    return (
        box[0] >= cell[0] - tolerance
        and box[1] >= cell[1] - tolerance
        and box[2] <= cell[2] + tolerance
        and box[3] <= cell[3] + tolerance
    )


def _validate_replacement(
    original: dict[str, Any],
    retry: dict[str, Any],
    grid: _Grid,
    page: SourcePage,
) -> dict[str, Any] | None:
    tables = retry.get("tables")
    if not isinstance(tables, list) or len(tables) != 1 or not isinstance(tables[0], dict):
        return None
    candidate = tables[0]
    data = candidate.get("data")
    rows, columns = len(grid.ys) - 1, len(grid.xs) - 1
    if (
        not isinstance(data, dict)
        or type(data.get("num_rows")) is not int
        or type(data.get("num_cols")) is not int
    ):
        return None
    if (data["num_rows"], data["num_cols"]) != (rows, columns):
        return None
    cells, raw_grid = data.get("table_cells"), data.get("grid")
    if not isinstance(cells, list) or len(cells) != rows * columns:
        return None
    if (
        not isinstance(raw_grid, list)
        or len(raw_grid) != rows
        or any(not isinstance(row, list) or len(row) != columns for row in raw_grid)
    ):
        return None
    width, height = grid.crop[2] - grid.crop[0], grid.crop[3] - grid.crop[1]
    prov = candidate.get("prov")
    if (
        not isinstance(prov, list)
        or len(prov) != 1
        or not isinstance(prov[0], dict)
        or type(prov[0].get("page_no")) is not int
        or prov[0]["page_no"] != 1
    ):
        return None
    table_box = _box(prov[0].get("bbox"), height)
    if table_box is None or not _inside(table_box, (0, 0, width, height)):
        return None
    if (table_box[2] - table_box[0]) * (table_box[3] - table_box[1]) < width * height * 0.85:
        return None
    mapped: dict[tuple[int, int], dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            return None
        keys = (
            "start_row_offset_idx", "end_row_offset_idx",
            "start_col_offset_idx", "end_col_offset_idx", "row_span", "col_span",
        )
        if any(type(cell.get(key)) is not int for key in keys):
            return None
        row, col = cell[keys[0]], cell[keys[2]]
        if not (0 <= row < rows and 0 <= col < columns) or (row, col) in mapped:
            return None
        offsets = (cell[keys[1]], cell[keys[3]], cell["row_span"], cell["col_span"])
        if offsets != (row + 1, col + 1, 1, 1):
            return None
        if raw_grid[row][col] != cell or _text(cell.get("text")) is None:
            return None
        box = _box(cell.get("bbox"), height)
        if box is None or not _inside(box, (0, 0, width, height), 0):
            return None
        translated = (
            box[0] + grid.crop[0], box[1] + grid.crop[1],
            box[2] + grid.crop[0], box[3] + grid.crop[1],
        )
        source_cell = (grid.xs[col], grid.ys[row], grid.xs[col + 1], grid.ys[row + 1])
        if not _inside(translated, source_cell):
            return None
        result = deepcopy(cell)
        result["bbox"] = dict(zip(("l", "t", "r", "b"), translated), coord_origin="TOPLEFT")
        mapped[row, col] = result
    previous_cells = (original.get("data") or {}).get("table_cells")
    if not isinstance(previous_cells, list) or len(previous_cells) > 256:
        return None
    previous_nonempty = 0
    for previous in previous_cells:
        if not isinstance(previous, dict) or _text(previous.get("text")) is None:
            return None
        text = _text(previous["text"])
        if not text:
            continue
        previous_nonempty += 1
        box = _box(previous.get("bbox"), page.pixel_height)
        if box is None:
            return None
        matches = [
            (row, col)
            for row, col in mapped
            if _inside(
                box, (grid.xs[col], grid.ys[row], grid.xs[col + 1], grid.ys[row + 1])
            )
        ]
        if len(matches) != 1 or _text(mapped[matches[0]]["text"]) != text:
            return None
    if sum(bool(_text(cell["text"])) for cell in mapped.values()) <= previous_nonempty:
        return None
    replacement = deepcopy(data)
    replacement["table_cells"] = [mapped[row, col] for row in range(rows) for col in range(columns)]
    replacement["grid"] = [
        [deepcopy(mapped[row, col]) for col in range(columns)] for row in range(rows)
    ]
    return replacement


def recover_raster_tables(
    raw_docling: dict[str, Any],
    pages: Sequence[SourcePage],
    *,
    convert: Callable[[bytes], dict[str, Any]],
    max_pixels: int = 4_000_000,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Retry at most one collapsed table by default; failed retries never mutate it.

    The callback is the existing local converter, with a fresh configured
    per-conversion timeout. This is not a hard whole-request deadline. There
    are at most four source-grid inspections and one retry by default. This
    stage adds no network provider; recovered values remain unverified OCR.
    """
    summary: dict[str, Any] = {"attempted": 0, "recovered": 0, "events": []}
    tables = raw_docling.get("tables")
    if not isinstance(tables, list) or len(tables) > 256 or max_pixels <= 0 or max_retries <= 0:
        return summary
    page_map = {page.page_index: page for page in pages}
    inspected = 0
    for table in tables:
        if summary["attempted"] >= min(max_retries, 2) or inspected >= 4:
            break
        if not isinstance(table, dict) or not isinstance(table.get("data"), dict):
            continue
        data = table["data"]
        rows, cols = data.get("num_rows"), data.get("num_cols")
        if (
            type(rows) is not int or type(cols) is not int
            or not (0 <= rows <= 256 and 0 <= cols <= 256)
            or (rows >= 2 and cols >= 2)
        ):
            continue
        if "meta" in table and not isinstance(table["meta"], dict):
            continue
        prov = table.get("prov")
        if not isinstance(prov, list) or len(prov) != 1 or not isinstance(prov[0], dict):
            continue
        page = page_map.get(prov[0].get("page_no"))
        if page is None:
            continue
        inspected += 1
        try:
            grid = _detect_grid(page, table, min(max_pixels, 4_000_000))
        except (OSError, ValueError, TypeError, OverflowError):
            grid = None
        if grid is None:
            continue
        event: dict[str, Any] = {
            "page_index": page.page_index, "table_ref": table.get("self_ref"),
            "status": "retained", "reason": "retry_not_validated",
        }
        summary["events"].append(event)
        summary["attempted"] += 1
        try:
            retry = convert(grid.png)
            if isinstance(retry, dict):
                warnings = retry.get("_raster_retry_warnings", [])
                if isinstance(warnings, list):
                    event["warnings"] = [value for value in warnings[:10] if isinstance(value, str)]
                    event["conversion_status"] = (
                        "partial" if "Docling completed with partial success." in warnings
                        else "completed"
                    )
            replacement = _validate_replacement(table, retry, grid, page)
        except Exception:
            event["reason"] = "local_retry_failed"
            continue
        if replacement is None:
            continue
        original_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
        recovery = {
            "method": "local_docling_ruled_crop", "crop_bbox": list(grid.crop),
            "crop_sha256": hashlib.sha256(grid.png).hexdigest(),
            "page_sha256": hashlib.sha256(page.png_bytes).hexdigest(),
            "original_shape": [rows, cols],
            "recovered_shape": [replacement["num_rows"], replacement["num_cols"]],
            "original_data_sha256": hashlib.sha256(original_json.encode()).hexdigest(),
            "original_cells_preserved": True,
            "value_verification": "not_independently_verified",
        }
        table["data"] = replacement
        table.setdefault("meta", {})["raster_table_retry"] = recovery
        summary["recovered"] += 1
        event.update(
            status="recovered", reason="pixel_grid_matches_and_prior_cells_preserved", **recovery
        )
    return summary
