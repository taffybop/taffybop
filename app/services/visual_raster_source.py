"""Conservative source-byte evidence producer for small conventional charts.

The producer is deliberately independent of the Phase 05 semantic services.  It
does not mutate public items and returns only their existing private raster
evidence seams.  Missing, ambiguous, oversized, or unsupported inputs refuse
with ``None``.
"""

from __future__ import annotations

import hashlib
import io
import math
import re
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError


_MAX_OCCURRENCES = 512
_NUMBER_RE = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?%?$"
)


@dataclass(frozen=True, slots=True)
class _Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0

    def mapping(self, unit: Literal["pt", "px"] = "px") -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "unit": unit,
        }


@dataclass(frozen=True, slots=True)
class _Word:
    identifier: str
    text: str
    page_box: _Box
    pixel_box: _Box


@dataclass(frozen=True, slots=True)
class _AxisFit:
    slope: float
    intercept: float
    residual: float
    tolerance: float


@dataclass(frozen=True, slots=True)
class _Legend:
    word: _Word
    color: tuple[int, int, int]
    swatch: _Box


class _Refusal(ValueError):
    pass


def _stable(prefix: str, *parts: Any) -> str:
    encoded = repr(parts).encode("utf-8", errors="strict")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:20]}"


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Refusal("non-numeric geometry")
    result = float(value)
    if not math.isfinite(result):
        raise _Refusal("non-finite geometry")
    return result


def _box(value: Any) -> _Box:
    if not isinstance(value, Mapping):
        raise _Refusal("missing geometry")
    result = _Box(
        _number(value.get("x")),
        _number(value.get("y")),
        _number(value.get("width", value.get("w"))),
        _number(value.get("height", value.get("h"))),
    )
    if min(result.x, result.y) < 0 or result.width <= 0 or result.height <= 0:
        raise _Refusal("invalid geometry")
    return result


def _text(value: Any, maximum: int = 1_024) -> str:
    if not isinstance(value, str):
        raise _Refusal("missing text")
    result = value.strip()
    if not result or len(result) > maximum:
        raise _Refusal("invalid text")
    return result


def _contains(outer: _Box, inner: _Box, tolerance: float = 0.75) -> bool:
    return (
        inner.x >= outer.x - tolerance
        and inner.y >= outer.y - tolerance
        and inner.right <= outer.right + tolerance
        and inner.bottom <= outer.bottom + tolerance
    )


def _tick_value(text: str) -> float | None:
    value = text.strip().replace("\N{MINUS SIGN}", "-")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1].strip()
    if value[:1] in {"$", "€", "£", "¥", "₹"}:
        value = value[1:].strip()
    if not _NUMBER_RE.fullmatch(value):
        return None
    numeric = value[:-1] if value.endswith("%") else value
    result = float(numeric.replace(",", ""))
    return -result if negative else result


def _transform_box(box: _Box, matrix: Sequence[float]) -> _Box:
    a, b, c, d, e, f = matrix
    points = (
        (a * box.x + c * box.y + e, b * box.x + d * box.y + f),
        (a * box.right + c * box.y + e, b * box.right + d * box.y + f),
        (a * box.x + c * box.bottom + e, b * box.x + d * box.bottom + f),
        (a * box.right + c * box.bottom + e, b * box.right + d * box.bottom + f),
    )
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return _Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _inverse_page_box(box: _Box, matrix: Sequence[float]) -> _Box:
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    if abs(determinant) < 1e-12:
        raise _Refusal("singular raster transform")
    inverse = (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant,
    )
    return _transform_box(box, inverse)


def _same_box(first: _Box, second: _Box, tolerance: float = 0.75) -> bool:
    return all(
        abs(left - right) <= tolerance
        for left, right in (
            (first.x, second.x),
            (first.y, second.y),
            (first.width, second.width),
            (first.height, second.height),
        )
    )


def _source_crop(
    source: bytes,
    *,
    item_box: _Box,
    page_index: int,
    input_kind: str,
    settings: Any,
) -> tuple[Image.Image, tuple[float, float, float, float, float, float], str]:
    if not source or page_index < 1:
        raise _Refusal("source bytes unavailable")
    max_width = int(settings.charts_raster_max_crop_width)
    max_height = int(settings.charts_raster_max_crop_height)
    max_pixels = int(settings.charts_raster_max_total_pixels)
    if input_kind == "image":
        direct_matrix = (1.0, 0.0, 0.0, 1.0, item_box.x, item_box.y)
        try:
            with Image.open(io.BytesIO(source)) as opened:
                frame_count = int(getattr(opened, "n_frames", 1) or 1)
                frame = page_index - 1 if frame_count > 1 else 0
                if frame >= frame_count:
                    raise _Refusal("image page is unavailable")
                opened.seek(frame)
                if opened.width * opened.height > int(
                    getattr(settings, "max_image_pixels", 50_000_000)
                ):
                    raise _Refusal("source image exceeds its decode bound")
                left = round(item_box.x)
                top = round(item_box.y)
                right = round(item_box.right)
                bottom = round(item_box.bottom)
                if (
                    min(left, top) < 0
                    or right > opened.width
                    or bottom > opened.height
                    or abs(left - item_box.x) > 1e-6
                    or abs(top - item_box.y) > 1e-6
                    or abs(right - item_box.right) > 1e-6
                    or abs(bottom - item_box.bottom) > 1e-6
                ):
                    raise _Refusal("direct-image chart crop is not pixel aligned")
                width, height = right - left, bottom - top
                if (
                    width <= 0
                    or height <= 0
                    or width > max_width
                    or height > max_height
                    or width * height > max_pixels
                ):
                    raise _Refusal("chart crop exceeds raster bounds")
                crop = opened.crop((left, top, right, bottom)).convert("RGB")
        except (OSError, UnidentifiedImageError) as exc:
            raise _Refusal("source image cannot be decoded") from exc
        return crop, direct_matrix, "direct_image"

    if input_kind != "pdf":
        raise _Refusal("unsupported raster source kind")
    document: Any | None = None
    page: Any | None = None
    bitmap: Any | None = None
    try:
        document = pdfium.PdfDocument(source)
        if page_index > len(document):
            raise _Refusal("PDF page is unavailable")
        page = document[page_index - 1]
        page_width, page_height = (float(value) for value in page.get_size())
        if not _contains(_Box(0.0, 0.0, page_width, page_height), item_box, 1e-6):
            raise _Refusal("PDF chart crop leaves its page")
        scale = min(
            2.0,
            max_width / item_box.width,
            max_height / item_box.height,
            math.sqrt(max_pixels / (item_box.width * item_box.height)),
        )
        if scale <= 0:
            raise _Refusal("PDF render scale is invalid")
        expected_width = max(1, math.ceil(item_box.width * scale))
        expected_height = max(1, math.ceil(item_box.height * scale))
        if expected_width * expected_height > max_pixels:
            raise _Refusal("PDF chart crop exceeds raster bounds")
        bitmap = page.render(
            scale=scale,
            crop=(
                item_box.x,
                page_height - item_box.bottom,
                page_width - item_box.right,
                item_box.y,
            ),
            fill_color=(255, 255, 255, 255),
            optimize_mode="print",
        )
        rendered = bitmap.to_pil()
        crop = rendered.convert("RGB")
        if (
            crop.width <= 0
            or crop.height <= 0
            or crop.width > max_width
            or crop.height > max_height
            or crop.width * crop.height > max_pixels
        ):
            crop.close()
            raise _Refusal("PDF renderer exceeded raster bounds")
        matrix = (
            item_box.width / crop.width,
            0.0,
            0.0,
            item_box.height / crop.height,
            item_box.x,
            item_box.y,
        )
        return crop, matrix, "pdf_render"
    except _Refusal:
        raise
    except Exception as exc:
        raise _Refusal("PDF chart crop cannot be rendered") from exc
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        if document is not None:
            document.close()


def _words(
    item: Mapping[str, Any],
    *,
    item_box: _Box,
    panel: _Box,
    matrix: Sequence[float],
) -> list[_Word]:
    raw = item.get("ocr_token_occurrences")
    if (
        not isinstance(raw, Sequence)
        or isinstance(raw, (str, bytes, bytearray))
        or not 1 <= len(raw) <= _MAX_OCCURRENCES
    ):
        raise _Refusal("bounded OCR occurrences are unavailable")
    output: list[_Word] = []
    identifiers: set[str] = set()
    for occurrence in raw:
        if not isinstance(occurrence, Mapping) or occurrence.get("selected") is False:
            continue
        identifier = _text(
            occurrence.get("occurrence_id", occurrence.get("id")), 128
        )
        if identifier in identifiers:
            raise _Refusal("OCR occurrence identity repeats")
        identifiers.add(identifier)
        text = _text(occurrence.get("text"))
        page_box = _box(occurrence.get("bbox"))
        if not _contains(item_box, page_box):
            continue
        derived_pixels = _inverse_page_box(page_box, matrix)
        raw_pixels = occurrence.get("crop_pixel_bbox")
        if raw_pixels is not None:
            asserted_pixels = _box(raw_pixels)
            raw_matches_local = _same_box(asserted_pixels, derived_pixels)
            a, b, c, d, e, f = matrix
            raw_matches_same_scale_page = (
                abs(b) <= 1e-12
                and abs(c) <= 1e-12
                and a > 0
                and d > 0
                and _same_box(
                    _Box(
                        asserted_pixels.x - e / a,
                        asserted_pixels.y - f / d,
                        asserted_pixels.width,
                        asserted_pixels.height,
                    ),
                    derived_pixels,
                )
            )
            if not raw_matches_local and not raw_matches_same_scale_page:
                raise _Refusal("OCR pixels have an unowned raster coordinate space")
        pixel_box = derived_pixels
        if not _same_box(_transform_box(pixel_box, matrix), page_box) or not _contains(
            panel, pixel_box
        ):
            raise _Refusal("OCR pixel/page geometry differs from source crop")
        output.append(_Word(identifier, text, page_box, pixel_box))
    if len(output) < 5:
        raise _Refusal("chart OCR is incomplete")
    return output


def _is_dark(pixel: tuple[int, int, int]) -> bool:
    return max(pixel) <= 110 and max(pixel) - min(pixel) <= 35


def _is_color(pixel: tuple[int, int, int]) -> bool:
    return max(pixel) - min(pixel) >= 45 and min(pixel) <= 220


def _color_near(
    pixel: tuple[int, int, int], color: tuple[int, int, int], tolerance: int = 30
) -> bool:
    return max(abs(pixel[index] - color[index]) for index in range(3)) <= tolerance


def _longest_run(values: Sequence[bool], *, gap: int = 1) -> tuple[int, int]:
    best = (0, 0)
    start: int | None = None
    last_true = -1
    for index, value in enumerate((*values, *(False for _ in range(gap + 1)))):
        if value:
            if start is None:
                start = index
            last_true = index
            continue
        if start is not None and index - last_true > gap:
            if last_true + 1 - start > best[1] - best[0]:
                best = (start, last_true + 1)
            start = None
            last_true = -1
    return best


def _fit_axis(ticks: Sequence[tuple[float, float]]) -> _AxisFit:
    if len(ticks) < 2 or len({position for position, _value in ticks}) != len(ticks):
        raise _Refusal("numeric ticks are incomplete")
    ordered = sorted(ticks)
    deltas = [
        ordered[index + 1][1] - ordered[index][1]
        for index in range(len(ordered) - 1)
    ]
    if not deltas or any(delta == 0 for delta in deltas) or not (
        all(delta > 0 for delta in deltas) or all(delta < 0 for delta in deltas)
    ):
        raise _Refusal("numeric ticks are not monotonic")
    count = float(len(ticks))
    mean_x = sum(position for position, _value in ticks) / count
    mean_y = sum(value for _position, value in ticks) / count
    denominator = sum((position - mean_x) ** 2 for position, _value in ticks)
    if denominator <= 0:
        raise _Refusal("numeric axis is singular")
    slope = sum(
        (position - mean_x) * (value - mean_y) for position, value in ticks
    ) / denominator
    intercept = mean_y - slope * mean_x
    residual = max(
        abs(slope * position + intercept - value) for position, value in ticks
    )
    span = max(value for _position, value in ticks) - min(
        value for _position, value in ticks
    )
    tolerance = max(0.1, span * 0.005)
    if slope == 0 or residual > tolerance:
        raise _Refusal("numeric axis is not linearly calibrated")
    return _AxisFit(slope, intercept, residual, tolerance)


def _axis_geometry(
    image: Image.Image,
    words: Sequence[_Word],
) -> tuple[_Box, _Box, list[tuple[_Word, float, float]], _AxisFit, float]:
    pixels = image.load()
    width, height = image.size
    numeric = [(word, _tick_value(word.text)) for word in words]
    numeric = [(word, value) for word, value in numeric if value is not None]
    candidates: list[
        tuple[int, int, int, int, list[tuple[_Word, float, float]], _AxisFit]
    ] = []
    minimum_run = max(20, round(height * 0.28))
    for x in range(max(1, round(width * 0.05)), max(2, round(width * 0.55))):
        start, end = _longest_run(
            [_is_dark(pixels[x, y]) for y in range(height)], gap=1
        )
        if end - start < minimum_run:
            continue
        ticks: list[tuple[_Word, float, float]] = []
        for word, value in numeric:
            assert value is not None
            if (
                word.pixel_box.right <= x + 2
                and x - word.pixel_box.right <= max(14.0, word.pixel_box.width)
                and start - 2 <= word.pixel_box.center_y <= end + 2
            ):
                ticks.append((word, word.pixel_box.center_y, value))
        try:
            fit = _fit_axis([(position, value) for _word, position, value in ticks])
        except _Refusal:
            continue
        candidates.append((x, start, end, end - start, ticks, fit))
    if not candidates:
        raise _Refusal("no OCR-grounded vertical axis")
    candidates.sort(key=lambda value: (-len(value[4]), -value[3], value[0]))
    best = candidates[0]
    equivalent = [
        value
        for value in candidates
        if len(value[4]) == len(best[4])
        and abs(value[3] - best[3]) <= 2
        and {tick[0].identifier for tick in value[4]}
        == {tick[0].identifier for tick in best[4]}
    ]
    xs = sorted(value[0] for value in equivalent)
    groups: list[list[int]] = []
    for x in xs:
        if not groups or x > groups[-1][-1] + 1:
            groups.append([x])
        else:
            groups[-1].append(x)
    if len(groups) != 1:
        raise _Refusal("vertical axis geometry is ambiguous")
    x_group = groups[0]
    y_start = max(value[1] for value in equivalent if value[0] in x_group)
    y_end = min(value[2] for value in equivalent if value[0] in x_group)
    y_axis = _Box(float(x_group[0]), float(y_start), float(len(x_group)), float(y_end - y_start))
    fit = best[5]
    baseline = -fit.intercept / fit.slope
    if not y_axis.y - 2 <= baseline <= y_axis.bottom + 2:
        raise _Refusal("calibrated zero baseline leaves the axis")
    row_candidates: list[tuple[int, int, int]] = []
    for y in range(max(0, round(baseline) - 2), min(height, round(baseline) + 3)):
        start, end = _longest_run(
            [_is_dark(pixels[x, y]) for x in range(width)], gap=1
        )
        if start <= y_axis.right + 2 and end - max(start, round(y_axis.x)) >= max(
            25, round(width * 0.25)
        ):
            row_candidates.append((y, start, end))
    if not row_candidates:
        raise _Refusal("zero baseline is not visibly grounded")
    row_candidates.sort(key=lambda value: (abs(value[0] - baseline), -(value[2] - value[1])))
    chosen_y, start, end = row_candidates[0]
    rows = sorted(
        value[0]
        for value in row_candidates
        if value[1] <= start + 2 and value[2] >= end - 2
    )
    x_axis = _Box(float(max(start, round(y_axis.x))), float(min(rows)), float(end - max(start, round(y_axis.x))), float(max(rows) - min(rows) + 1))
    if abs(chosen_y - baseline) > 2:
        raise _Refusal("visible baseline differs from numeric calibration")
    return y_axis, x_axis, best[4], fit, float(chosen_y)


def _component(
    points: set[tuple[int, int]], seed: tuple[int, int]
) -> set[tuple[int, int]]:
    output: set[tuple[int, int]] = set()
    pending = deque([seed])
    points.remove(seed)
    while pending:
        x, y = pending.popleft()
        output.add((x, y))
        for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if neighbor in points:
                points.remove(neighbor)
                pending.append(neighbor)
    return output


def _components_for_color(
    image: Image.Image,
    color: tuple[int, int, int],
    bounds: _Box,
) -> list[tuple[_Box, int]]:
    pixels = image.load()
    left = max(0, math.floor(bounds.x))
    top = max(0, math.floor(bounds.y))
    right = min(image.width, math.ceil(bounds.right))
    bottom = min(image.height, math.ceil(bounds.bottom))
    points = {
        (x, y)
        for y in range(top, bottom)
        for x in range(left, right)
        if _color_near(pixels[x, y], color)
    }
    output: list[tuple[_Box, int]] = []
    while points:
        member = _component(points, min(points, key=lambda point: (point[1], point[0])))
        xs = [point[0] for point in member]
        ys = [point[1] for point in member]
        output.append(
            (
                _Box(
                    float(min(xs)),
                    float(min(ys)),
                    float(max(xs) - min(xs) + 1),
                    float(max(ys) - min(ys) + 1),
                ),
                len(member),
            )
        )
    return output


def _dominant_color(
    image: Image.Image,
    search: _Box,
) -> tuple[tuple[int, int, int], _Box] | None:
    pixels = image.load()
    left = max(0, math.floor(search.x))
    top = max(0, math.floor(search.y))
    right = min(image.width, math.ceil(search.right))
    bottom = min(image.height, math.ceil(search.bottom))
    colored = {
        (x, y)
        for y in range(top, bottom)
        for x in range(left, right)
        if _is_color(pixels[x, y])
    }
    results: list[tuple[int, float, tuple[int, int, int], _Box]] = []
    while colored:
        member = _component(colored, min(colored, key=lambda point: (point[1], point[0])))
        if len(member) < 6:
            continue
        xs = [point[0] for point in member]
        ys = [point[1] for point in member]
        box = _Box(
            float(min(xs)),
            float(min(ys)),
            float(max(xs) - min(xs) + 1),
            float(max(ys) - min(ys) + 1),
        )
        density = len(member) / (box.width * box.height)
        if box.width < 3 or box.height < 3 or density < 0.65:
            continue
        samples = [pixels[x, y] for x, y in member]
        channels = tuple(
            sorted(pixel[index] for pixel in samples)[len(samples) // 2]
            for index in range(3)
        )
        color = (int(channels[0]), int(channels[1]), int(channels[2]))
        results.append((len(member), density, color, box))
    if len(results) != 1:
        return None
    _area, _density, color, box = results[0]
    return color, box


def _legend_entries(
    image: Image.Image,
    words: Sequence[_Word],
    *,
    y_axis: _Box,
    baseline: float,
    excluded: set[str],
) -> list[_Legend]:
    output: list[_Legend] = []
    used_colors: list[tuple[int, int, int]] = []
    used_swatches: list[_Box] = []
    for word in words:
        if (
            word.identifier in excluded
            or word.pixel_box.center_y >= baseline
            or word.pixel_box.x <= y_axis.x
        ):
            continue
        search = _Box(
            max(y_axis.right, word.pixel_box.x - max(36.0, 3 * word.pixel_box.height)),
            max(0.0, word.pixel_box.y - 2.0),
            max(0.0, word.pixel_box.x - max(y_axis.right, word.pixel_box.x - max(36.0, 3 * word.pixel_box.height)) - 1.0),
            word.pixel_box.height + 4.0,
        )
        if search.width <= 0:
            continue
        match = _dominant_color(image, search)
        if match is None:
            continue
        color, swatch = match
        if any(max(abs(color[index] - other[index]) for index in range(3)) <= 30 for other in used_colors):
            raise _Refusal("legend colors are not unique")
        if any(_same_box(swatch, other, 1.0) for other in used_swatches):
            raise _Refusal("legend swatch association repeats")
        used_colors.append(color)
        used_swatches.append(swatch)
        output.append(_Legend(word, color, swatch))
    if not output or len(output) > 8:
        raise _Refusal("a unique visible legend is unavailable")
    return sorted(output, key=lambda value: (value.word.pixel_box.y, value.word.pixel_box.x))


def _nearest_category(box: _Box, categories: Sequence[_Word]) -> _Word | None:
    ordered = sorted(
        (abs(box.center_x - word.pixel_box.center_x), word.identifier, word)
        for word in categories
    )
    if not ordered:
        return None
    if len(ordered) > 1 and abs(ordered[1][0] - ordered[0][0]) <= 1.0:
        return None
    spacing = min(
        (
            abs(categories[index + 1].pixel_box.center_x - categories[index].pixel_box.center_x)
            for index in range(len(categories) - 1)
        ),
        default=max(box.width * 4.0, 20.0),
    )
    return ordered[0][2] if ordered[0][0] <= max(box.width * 1.5, spacing * 0.45) else None


def _bar_candidates(
    image: Image.Image,
    legends: Sequence[_Legend],
    categories: Sequence[_Word],
    *,
    plot: _Box,
    baseline: float,
    y_source: str,
) -> list[dict[str, Any]] | None:
    output: list[dict[str, Any]] = []
    ownership: set[tuple[str, str]] = set()
    for legend in legends:
        components = _components_for_color(image, legend.color, plot)
        admitted = 0
        for box, area in components:
            density = area / (box.width * box.height)
            if (
                box.width < 4
                or box.height < 8
                or box.width > plot.width * 0.25
                or density < 0.8
                or abs(box.bottom - baseline) > 2.0
            ):
                continue
            category = _nearest_category(box, categories)
            if category is None:
                raise _Refusal("bar category ownership is ambiguous")
            key = (legend.word.identifier, category.identifier)
            if key in ownership:
                raise _Refusal("multiple bars claim one series/category")
            ownership.add(key)
            admitted += 1
            output.append(
                {
                    "source_object_id": _stable("raster-bar", legend.word.identifier, category.identifier, box),
                    "family": "bar",
                    "orientation": "vertical",
                    "raster_pixel_bbox": box.mapping(),
                    "axis_source_object_id": y_source,
                    "category_label_source_token_id": category.identifier,
                    "series_source_object_id": _stable("raster-series", legend.word.identifier, legend.color),
                    "mode": "simple",
                    "pixel_tolerance": 1.0,
                    "display_precision": 2,
                }
            )
        if admitted not in {0, len(categories)}:
            raise _Refusal("bar series coverage is incomplete")
    return output or None


def _line_candidates(
    image: Image.Image,
    legends: Sequence[_Legend],
    categories: Sequence[_Word],
    *,
    plot: _Box,
    y_source: str,
) -> list[dict[str, Any]] | None:
    pixels = image.load()
    paths: list[dict[str, Any]] = []
    for legend in legends:
        points: list[tuple[_Word, _Box]] = []
        for category in categories:
            center_x = round(category.pixel_box.center_x)
            colored = [
                (x, y)
                for y in range(max(0, math.floor(plot.y)), min(image.height, math.ceil(plot.bottom)))
                for x in range(max(0, center_x - 4), min(image.width, center_x + 5))
                if _color_near(pixels[x, y], legend.color)
            ]
            if not colored:
                return None
            ys = sorted({value[1] for value in colored})
            groups: list[list[int]] = []
            for y in ys:
                if not groups or y > groups[-1][-1] + 2:
                    groups.append([y])
                else:
                    groups[-1].append(y)
            substantial = [
                group
                for group in groups
                if sum(group[0] <= y <= group[-1] for _x, y in colored) >= 5
                and len(group) <= 9
            ]
            if len(substantial) != 1:
                return None
            group = substantial[0]
            members = [(x, y) for x, y in colored if group[0] <= y <= group[-1]]
            xs = [value[0] for value in members]
            member_ys = [value[1] for value in members]
            points.append(
                (
                    category,
                    _Box(
                        float(min(xs)),
                        float(min(member_ys)),
                        float(max(xs) - min(xs) + 1),
                        float(max(member_ys) - min(member_ys) + 1),
                    ),
                )
            )
        if len(points) < 2:
            return None
        for (_left_category, left), (_right_category, right) in zip(points, points[1:]):
            x0, y0 = left.center_x, left.center_y
            x1, y1 = right.center_x, right.center_y
            samples = max(2, round(abs(x1 - x0)))
            visible = 0
            for index in range(samples + 1):
                ratio = index / samples
                x = round(x0 + (x1 - x0) * ratio)
                y = round(y0 + (y1 - y0) * ratio)
                if any(
                    0 <= x + dx < image.width
                    and 0 <= y + dy < image.height
                    and _color_near(pixels[x + dx, y + dy], legend.color)
                    for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
                ):
                    visible += 1
            if visible / (samples + 1) < 0.75:
                return None
        paths.append(
            {
                "source_object_id": _stable("raster-path", legend.word.identifier, legend.color),
                "axis_source_object_id": y_source,
                "series_source_object_id": _stable("raster-series", legend.word.identifier, legend.color),
                "family": "line",
                "interpolation": "linear",
                "pixel_tolerance": 1.0,
                "points": [
                    {
                        "source_object_id": _stable("raster-marker", legend.word.identifier, category.identifier, box),
                        "category_label_source_token_id": category.identifier,
                        "raster_pixel_bbox": box.mapping(),
                    }
                    for category, box in points
                ],
            }
        )
    return paths or None


def derive_raster_chart_evidence(
    item: Mapping[str, Any],
    *,
    source_document_bytes: bytes | None,
    page_index: int,
    input_kind: str,
    settings: Any,
) -> dict[str, object] | None:
    """Derive strict existing P05 raster evidence from source bytes and OCR.

    The supported release slice is a small, white-background, conventional 2-D
    chart with two or more numeric y ticks, a visible zero baseline, two or more
    categories, a unique color legend, and either complete simple vertical bars
    or complete visible marker-line paths.
    """

    started = time.monotonic()
    image: Image.Image | None = None
    try:
        if not isinstance(item, Mapping) or source_document_bytes is None:
            raise _Refusal("source evidence is unavailable")
        item_box = _box(item.get("bbox"))
        image, matrix, variant = _source_crop(
            source_document_bytes,
            item_box=item_box,
            page_index=page_index,
            input_kind=input_kind,
            settings=settings,
        )
        pixel_count = image.width * image.height
        work_units = math.ceil(pixel_count / 16) + len(
            item.get("ocr_token_occurrences") or ()
        ) * 4
        if work_units > int(settings.charts_raster_max_work_units):
            raise _Refusal("source analysis exceeds its work budget")

        deadline = started + float(settings.charts_raster_timeout_seconds)
        if time.monotonic() > deadline:
            raise _Refusal("source analysis timed out")
        panel = _Box(0.0, 0.0, float(image.width), float(image.height))
        words = _words(item, item_box=item_box, panel=panel, matrix=matrix)
        grayscale = image.convert("L")
        try:
            histogram = grayscale.histogram()
        finally:
            grayscale.close()
        light_fraction = sum(histogram[225:]) / pixel_count
        if light_fraction < max(0.65, float(settings.charts_raster_minimum_quality)):
            raise _Refusal("source chart quality is unsupported")

        y_axis, x_axis, numeric_ticks, fit, baseline = _axis_geometry(image, words)
        if time.monotonic() > deadline:
            raise _Refusal("source analysis timed out")
        tick_ids = {word.identifier for word, _position, _value in numeric_ticks}
        categories = sorted(
            (
                word
                for word in words
                if word.identifier not in tick_ids
                and word.pixel_box.y >= baseline - 1.0
                and x_axis.x - 2 <= word.pixel_box.center_x <= x_axis.right + 2
            ),
            key=lambda word: (word.pixel_box.center_x, word.identifier),
        )
        if not 2 <= len(categories) <= 64 or any(
            categories[index + 1].pixel_box.center_x
            - categories[index].pixel_box.center_x
            < 8
            for index in range(len(categories) - 1)
        ):
            raise _Refusal("category OCR is incomplete or ambiguous")

        excluded = tick_ids | {word.identifier for word in categories}
        legends = _legend_entries(
            image,
            words,
            y_axis=y_axis,
            baseline=baseline,
            excluded=excluded,
        )
        excluded.update(legend.word.identifier for legend in legends)
        plot = _Box(
            y_axis.right,
            y_axis.y,
            max(1.0, x_axis.right - y_axis.right),
            max(1.0, baseline - y_axis.y + 1.0),
        )
        y_source = _stable("raster-axis", "y", y_axis)
        x_source = _stable("raster-axis", "x", x_axis)
        bars: list[dict[str, Any]] | None = None
        lines: list[dict[str, Any]] | None = None
        bars_enabled = bool(
            getattr(settings, "charts_raster_bar_values_enabled", False)
        )
        lines_enabled = bool(
            getattr(settings, "charts_raster_line_values_enabled", False)
        )
        family_passes = int(bars_enabled) + int(lines_enabled)
        work_units += math.ceil(
            plot.width * plot.height * len(legends) * family_passes / 16
        )
        if work_units > int(settings.charts_raster_max_work_units):
            raise _Refusal("source mark analysis exceeds its work budget")
        if time.monotonic() > deadline:
            raise _Refusal("source analysis timed out")
        if bars_enabled:
            try:
                bars = _bar_candidates(
                    image,
                    legends,
                    categories,
                    plot=plot,
                    baseline=baseline,
                    y_source=y_source,
                )
            except _Refusal:
                bars = None
        if lines_enabled:
            try:
                lines = _line_candidates(
                    image,
                    legends,
                    categories,
                    plot=plot,
                    y_source=y_source,
                )
            except _Refusal:
                lines = None
        # Marks are optional children.  Structure remains useful without them,
        # while two simultaneously plausible families have no safe authority.
        if bars is not None and lines is not None:
            bars = None
            lines = None
        if time.monotonic() > deadline:
            raise _Refusal("source analysis timed out")

        labels: list[dict[str, Any]] = []
        roles: dict[str, str] = {
            **{identifier: "tick" for identifier in tick_ids},
            **{word.identifier: "category" for word in categories},
            **{legend.word.identifier: "legend" for legend in legends},
        }
        remaining = [word for word in words if word.identifier not in roles]
        title_candidates = [
            word
            for word in remaining
            if word.pixel_box.bottom <= y_axis.y + 2
            and word.pixel_box.x >= y_axis.x
        ]
        if len(title_candidates) == 1:
            roles[title_candidates[0].identifier] = "title"
        for word in sorted(words, key=lambda value: (value.pixel_box.y, value.pixel_box.x, value.identifier)):
            role = roles.get(word.identifier)
            if role is not None:
                labels.append(
                    {
                        "source_token_id": word.identifier,
                        "text": word.text,
                        "role": role,
                        "raster_pixel_bbox": word.pixel_box.mapping(),
                    }
                )

        page_unit = str(item.get("coordinate_unit") or (item.get("bbox") or {}).get("unit") or ("pt" if input_kind == "pdf" else "px"))
        if page_unit not in {"pt", "px"}:
            raise _Refusal("unsupported page coordinate unit")
        structure: dict[str, Any] = {
            "transform": {
                "source_id": _stable("raster-source-transform", page_index, item_box, image.size),
                "matrix": list(matrix),
            },
            "panel": {
                "source_object_id": _stable("raster-panel", page_index, item_box),
                "raster_pixel_bbox": panel.mapping(),
                "page_bbox": item_box.mapping(page_unit),
            },
            "labels": labels,
            "axes": [
                {
                    "source_object_id": y_source,
                    "orientation": "y",
                    "scale": "linear",
                    "raster_pixel_bbox": y_axis.mapping(),
                    "page_bbox": _transform_box(y_axis, matrix).mapping(page_unit),
                    "baseline_position": baseline,
                    "calibration_tolerance": fit.tolerance,
                    "ticks": [
                        {
                            "source_token_id": word.identifier,
                            "position": position,
                            "value": value,
                        }
                        for word, position, value in sorted(numeric_ticks, key=lambda value: value[1])
                    ],
                },
                {
                    "source_object_id": x_source,
                    "orientation": "x",
                    "scale": "linear",
                    "raster_pixel_bbox": x_axis.mapping(),
                    "page_bbox": _transform_box(x_axis, matrix).mapping(page_unit),
                    "baseline_position": x_axis.y,
                    "calibration_tolerance": 0.1,
                    "category_label_source_token_ids": [word.identifier for word in categories],
                    "ticks": [
                        {
                            "source_token_id": word.identifier,
                            "position": word.pixel_box.center_x,
                            "value": float(index),
                        }
                        for index, word in enumerate(categories)
                    ],
                },
            ],
            "legends": [
                {
                    "source_object_id": _stable("raster-legend", page_index, item_box),
                    "entries": [
                        {
                            "source_object_id": _stable("raster-series", legend.word.identifier, legend.color),
                            "label_source_token_id": legend.word.identifier,
                            "swatch_source_object_id": _stable("raster-swatch", legend.word.identifier, legend.swatch),
                            "swatch_raster_pixel_bbox": legend.swatch.mapping(),
                            "color": "#{:02x}{:02x}{:02x}".format(*legend.color),
                            "sampled_color": "#{:02x}{:02x}{:02x}".format(*legend.color),
                        }
                        for legend in legends
                    ],
                }
            ],
        }
        result: dict[str, object] = {
            "phase05_raster_gate_evidence": {
                "crop_width": image.width,
                "crop_height": image.height,
                "total_pixels": pixel_count,
                "work_units": work_units,
                "quality": round(light_fraction, 6),
                "input_variant": variant,
                "coordinate_tolerance": float(settings.charts_raster_coordinate_tolerance),
                "blurred": False,
                "occluded": False,
                "incomplete": False,
                "unsupported": False,
                "simulated_elapsed_seconds": 0.0,
            },
            "phase05_raster_structure_evidence": structure,
        }
        if bars is not None:
            result["phase05_raster_bar_evidence"] = {"bars": bars}
        elif lines is not None:
            result["phase05_raster_line_evidence"] = {"paths": lines}
        return result
    except (MemoryError, OverflowError, TypeError, ValueError, pdfium.PdfiumError):
        return None
    finally:
        if image is not None:
            image.close()


__all__ = ["derive_raster_chart_evidence"]
