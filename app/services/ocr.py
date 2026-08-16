"""Targeted, local OCR for raster images embedded in PDF pages.

The module deliberately renders each image's *page region* instead of asking
PDFium for the raw image stream.  Page rendering composites soft masks and
other transparency correctly, which is important for signatures and scanned
stamps that otherwise look blank when their raw stream is decoded in
isolation.
"""

from __future__ import annotations

import csv
import io
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Protocol, Sequence

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from PIL import Image


_TARGET_RENDER_SCALE = 5.0  # PDF points are normally 1/72", so this is 360 DPI.
_MAX_RENDER_PIXELS = 16_000_000
PDF_RENDER_CROP_PADDING_POINTS = 3.0
_MAX_OCR_TSV_BYTES = 8 * 1024 * 1024
_MAX_OCR_TSV_WORDS = 100_000
MAX_NUMERIC_CLEANUP_LINE_CHARS = 65_536
MAX_NUMERIC_CLEANUP_TOKENS = 4_096
MAX_SPLIT_HEX_FRAGMENTS = 64
MAX_SPLIT_HEX_CHARS = 128

_SPLIT_HEX_FRAGMENT_RE = re.compile(r"[A-F0-9]{2,}")
_SPLIT_HEX_EXACT_LENGTHS: dict[str, frozenset[int]] = {
    "MD5": frozenset({32}),
    "SHA1": frozenset({40}),
    "SHA-1": frozenset({40}),
    "SHA224": frozenset({56}),
    "SHA-224": frozenset({56}),
    "SHA256": frozenset({64}),
    "SHA-256": frozenset({64}),
    "SHA384": frozenset({96}),
    "SHA-384": frozenset({96}),
    "SHA512": frozenset({128}),
    "SHA-512": frozenset({128}),
}
_SPLIT_HEX_GENERIC_LENGTHS = frozenset({32, 40, 56, 64, 96, 128})
_SPLIT_HEX_GENERIC_LABELS = frozenset(
    {"HASH", "CHECKSUM", "DIGEST", "FINGERPRINT"}
)


class OCRUnavailableError(RuntimeError):
    """Raised when the configured local Tesseract executable is unavailable."""


@dataclass(slots=True)
class OCRToken:
    """One OCR token projected into the input page coordinate system."""

    text: str
    bbox: dict[str, float]
    crop_pixel_bbox: dict[str, float]
    confidence: float | None
    ocr_pass: str
    word_index: int

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": dict(self.bbox),
            "crop_pixel_bbox": dict(self.crop_pixel_bbox),
            "confidence": self.confidence,
            "ocr_pass": self.ocr_pass,
            "word_index": self.word_index,
        }


@dataclass(slots=True)
class OCRLine:
    """One OCR line in top-left PDF point coordinates.

    ``confidence`` is normalized to the inclusive range 0.0–1.0.
    """

    text: str
    bbox: dict[str, float]
    confidence: float | None
    word_count: int
    ocr_pass: str = "standard"
    tokens: list[OCRToken] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "text": self.text,
            "bbox": dict(self.bbox),
            "confidence": self.confidence,
            "word_count": self.word_count,
        }

    def to_evidence_dict(self) -> dict[str, Any]:
        """Return the shared PDF/direct-raster OCR evidence contract."""

        return {
            **self.to_dict(),
            "ocr_pass": self.ocr_pass,
            "tokens": [token.to_evidence_dict() for token in self.tokens],
        }


@dataclass(slots=True)
class ImageRegion:
    """One visual page region and any text recognized inside it.

    The structure is intentionally input-neutral.  PDF adapters populate it
    from embedded objects or selectively rendered page regions, while the
    image adapter uses it for each oriented raster frame.
    """

    page_index: int
    object_index: int
    bbox: dict[str, float]
    pixel_width: int | None
    pixel_height: int | None
    area_ratio: float
    text: str = ""
    lines: list[OCRLine] = field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    content_type: str = "image"
    metadata: dict[str, Any] = field(default_factory=dict)
    rejected_lines: list[dict[str, Any]] = field(default_factory=list)
    region_role: str | None = None
    region_origin: str | None = None
    coordinate_unit: str | None = None
    render_pixel_width: int | None = None
    render_pixel_height: int | None = None
    rendered_crop_bbox: dict[str, float] | None = None
    rendered_page_size: tuple[float, float] | None = None
    pixel_to_page_transform: tuple[
        float,
        float,
        float,
        float,
        float,
        float,
    ] | None = None
    ocr_pass_statuses: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "page_index": self.page_index,
            "object_index": self.object_index,
            "bbox": dict(self.bbox),
            "pixel_width": self.pixel_width,
            "pixel_height": self.pixel_height,
            "area_ratio": self.area_ratio,
            "text": self.text,
            "lines": [line.to_dict() for line in self.lines],
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "content_type": self.content_type,
            "metadata": dict(self.metadata),
            "rejected_lines": [dict(line) for line in self.rejected_lines],
            "region_role": self.region_role,
            "region_origin": self.region_origin,
            "coordinate_unit": self.coordinate_unit,
        }


@dataclass(slots=True)
class _OCRWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float | None


class RasterPage(Protocol):
    page_index: int
    pixel_width: int
    pixel_height: int
    png_bytes: bytes
    original_orientation: int | None
    orientation_applied: bool


@dataclass(frozen=True, slots=True)
class PdfRegionRequest:
    """A top-left PDF-point region requested by shared visual analysis."""

    page_index: int
    bbox: Mapping[str, float]
    content_type: str = "image"
    region_role: str = "content_region"
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _point_bbox(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {
        "x": round(float(x), 3),
        "y": round(float(y), 3),
        "w": round(float(width), 3),
        "h": round(float(height), 3),
    }


def _normalise_languages(languages: Sequence[str]) -> tuple[str, ...]:
    normalised = tuple(
        language.strip() for language in languages if language and language.strip()
    )
    if not normalised:
        raise ValueError("At least one Tesseract language must be configured.")
    return normalised


def _resolve_tesseract(tesseract_cmd: str) -> str:
    command = tesseract_cmd.strip()
    if not command:
        raise OCRUnavailableError("No Tesseract executable was configured.")

    resolved = shutil.which(command)
    if resolved is None:
        raise OCRUnavailableError(
            f"Tesseract executable {tesseract_cmd!r} was not found or is not executable."
        )
    return resolved


def _render_scale(
    width_points: float,
    height_points: float,
    *,
    target_scale: float,
    max_pixels: int,
) -> float:
    area_points = max(width_points * height_points, 1.0)
    capped_scale = math.sqrt(max_pixels / area_points)
    return max(0.5, min(target_scale, capped_scale))


def _image_dimensions(image_object: Any) -> tuple[int | None, int | None]:
    try:
        metadata = image_object.get_metadata()
    except Exception:
        return None, None

    width = int(metadata.width) if metadata.width > 0 else None
    height = int(metadata.height) if metadata.height > 0 else None
    return width, height


def _visible_bounds(
    image_object: Any,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float] | None:
    """Return clamped PDF bottom-left bounds, or ``None`` if not visible."""

    left, bottom, right, top = (float(value) for value in image_object.get_bounds())
    left, right = sorted((left, right))
    bottom, top = sorted((bottom, top))

    left = max(0.0, min(page_width, left))
    right = max(0.0, min(page_width, right))
    bottom = max(0.0, min(page_height, bottom))
    top = max(0.0, min(page_height, top))
    if right - left <= 0.01 or top - bottom <= 0.01:
        return None
    return left, bottom, right, top


def _render_region_png(
    page: Any,
    page_width: float,
    page_height: float,
    bounds: tuple[float, float, float, float],
    *,
    target_scale: float,
    max_pixels: int,
) -> tuple[
    bytes,
    tuple[float, float, float, float],
    float,
    tuple[int, int],
    tuple[float, float, float, float, float, float],
]:
    left, bottom, right, top = bounds
    crop_left = max(0.0, left - PDF_RENDER_CROP_PADDING_POINTS)
    crop_bottom = max(0.0, bottom - PDF_RENDER_CROP_PADDING_POINTS)
    crop_right = min(page_width, right + PDF_RENDER_CROP_PADDING_POINTS)
    crop_top = min(page_height, top + PDF_RENDER_CROP_PADDING_POINTS)
    crop_width = crop_right - crop_left
    crop_height = crop_top - crop_bottom
    scale = _render_scale(
        crop_width,
        crop_height,
        target_scale=target_scale,
        max_pixels=max_pixels,
    )
    page_pixel_width = math.ceil(page_width * scale)
    page_pixel_height = math.ceil(page_height * scale)
    crop_pixels = tuple(
        math.ceil(value * scale)
        for value in (
            crop_left,
            crop_bottom,
            page_width - crop_right,
            page_height - crop_top,
        )
    )
    expected_pixel_width = (
        page_pixel_width - crop_pixels[0] - crop_pixels[2]
    )
    expected_pixel_height = (
        page_pixel_height - crop_pixels[1] - crop_pixels[3]
    )
    if (
        expected_pixel_width < 1
        or expected_pixel_height < 1
        or expected_pixel_width * expected_pixel_height > max_pixels
    ):
        raise RuntimeError(
            "Quantized PDF render exceeds the configured pixel bound."
        )

    bitmap = page.render(
        scale=scale,
        crop=(
            crop_left,
            crop_bottom,
            page_width - crop_right,
            page_height - crop_top,
        ),
        fill_color=(255, 255, 255, 255),
        optimize_mode="print",
    )
    try:
        image = bitmap.to_pil()
        try:
            actual_dimensions = (int(image.width), int(image.height))
            if actual_dimensions != (
                expected_pixel_width,
                expected_pixel_height,
            ):
                raise RuntimeError(
                    "PDF renderer dimensions differ from quantized geometry."
                )
            crop_to_page_transform = (
                page_width / page_pixel_width,
                0.0,
                0.0,
                page_height / page_pixel_height,
                crop_pixels[0] * page_width / page_pixel_width,
                crop_pixels[3] * page_height / page_pixel_height,
            )
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue(), (
                crop_left,
                crop_bottom,
                crop_right,
                crop_top,
            ), scale, actual_dimensions, crop_to_page_transform
        finally:
            image.close()
    finally:
        bitmap.close()


def _run_tesseract_tsv(
    executable: str,
    png_bytes: bytes,
    languages: tuple[str, ...],
    timeout_seconds: float,
    tessdata_path: str | None,
    *,
    page_segmentation_mode: int = 3,
) -> str:
    command = [
        executable,
        "stdin",
        "stdout",
        "-l",
        "+".join(languages),
        "--psm",
        str(page_segmentation_mode),
    ]
    if tessdata_path:
        command.extend(["--tessdata-dir", tessdata_path])
    command.append("tsv")
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            result = subprocess.run(
                command,
                input=png_bytes,
                stdout=stdout_file,
                stderr=stderr_file,
                check=False,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as error:
            raise OCRUnavailableError(
                f"Tesseract executable {executable!r} is no longer available."
            ) from error

        stdout_file.seek(0, io.SEEK_END)
        stdout_size = stdout_file.tell()
        if stdout_size > _MAX_OCR_TSV_BYTES:
            raise RuntimeError(
                "Tesseract TSV output exceeds the bounded size."
            )
        stdout_file.seek(0)
        stdout = stdout_file.read(_MAX_OCR_TSV_BYTES + 1)
        if result.returncode != 0:
            stderr_file.seek(0)
            detail = stderr_file.read(2_000).decode(
                "utf-8",
                errors="replace",
            ).strip()
            if len(detail) > 500:
                detail = f"{detail[:497]}..."
            message = f"Tesseract exited with status {result.returncode}"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message)

    return stdout.decode("utf-8", errors="replace")


def _line_overlap_of_smaller(first: OCRLine, second: OCRLine) -> float:
    left = max(float(first.bbox["x"]), float(second.bbox["x"]))
    top = max(float(first.bbox["y"]), float(second.bbox["y"]))
    right = min(
        float(first.bbox["x"]) + float(first.bbox["w"]),
        float(second.bbox["x"]) + float(second.bbox["w"]),
    )
    bottom = min(
        float(first.bbox["y"]) + float(first.bbox["h"]),
        float(second.bbox["y"]) + float(second.bbox["h"]),
    )
    overlap = max(right - left, 0.0) * max(bottom - top, 0.0)
    first_area = float(first.bbox["w"]) * float(first.bbox["h"])
    second_area = float(second.bbox["w"]) * float(second.bbox["h"])
    smaller = min(first_area, second_area)
    return overlap / smaller if smaller else 0.0


def _merge_sparse_ocr_lines(
    primary: Sequence[OCRLine],
    sparse: Sequence[OCRLine],
    *,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
) -> list[OCRLine]:
    """Add isolated sparse-text results without duplicating primary lines."""

    merged, _rejected = _merge_sparse_ocr_lines_with_diagnostics(
        primary,
        sparse,
        **(
            {"numeric_cleanup_v2_enabled": True}
            if numeric_cleanup_v2_enabled
            else {}
        ),
        **(
            {"spatial_token_preservation_enabled": True}
            if spatial_token_preservation_enabled
            else {}
        ),
    )
    return merged


def _normalized_ocr_text(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", value.casefold()).strip()


def _line_confidence_value(line: OCRLine) -> float:
    return float(line.confidence) if line.confidence is not None else -1.0


def _preferred_overlapping_line(
    first: OCRLine,
    second: OCRLine,
    *,
    similarity: float,
    first_text: str,
    second_text: str,
) -> OCRLine:
    """Choose a complete, confident OCR candidate without sample-specific rules."""

    first_confidence = _line_confidence_value(first)
    second_confidence = _line_confidence_value(second)
    if similarity >= 0.86 and abs(first_confidence - second_confidence) >= 0.03:
        return first if first_confidence > second_confidence else second

    first_tokens = set(first_text.split())
    second_tokens = set(second_text.split())
    if first_tokens < second_tokens:
        return second
    if second_tokens < first_tokens:
        return first

    if first_confidence != second_confidence:
        return first if first_confidence > second_confidence else second
    return first if len(first_text) >= len(second_text) else second


def _merge_sparse_ocr_lines_with_diagnostics(
    primary: Sequence[OCRLine],
    sparse: Sequence[OCRLine],
    *,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
) -> tuple[list[OCRLine], list[dict[str, Any]]]:
    """Reconcile OCR passes and retain every discarded overlapping candidate."""

    merged = list(primary)
    origins = ["standard" for _ in primary]
    rejected: list[dict[str, Any]] = []
    for candidate in sparse:
        candidate_text = _normalized_ocr_text(
            _clean_ocr_line(
                candidate.text,
                **(
                    {"numeric_cleanup_v2_enabled": True}
                    if numeric_cleanup_v2_enabled
                    else {}
                ),
            )
        )
        candidate_tokens = set(candidate_text.split())
        if not candidate_text:
            continue
        matched = False
        for index, existing in enumerate(merged):
            overlap = _line_overlap_of_smaller(candidate, existing)
            if overlap < 0.3:
                continue
            existing_text = _normalized_ocr_text(
                _clean_ocr_line(
                    existing.text,
                    **(
                        {"numeric_cleanup_v2_enabled": True}
                        if numeric_cleanup_v2_enabled
                        else {}
                    ),
                )
            )
            existing_tokens = set(existing_text.split())
            compact_equal = (
                len(candidate_text.replace(" ", "")) >= 4
                and candidate_text.replace(" ", "")
                == existing_text.replace(" ", "")
            )
            similarity = SequenceMatcher(
                None,
                candidate_text,
                existing_text,
            ).ratio()
            related = (
                compact_equal
                or candidate_tokens <= existing_tokens
                or existing_tokens <= candidate_tokens
                or (overlap >= 0.6 and similarity >= 0.86)
            )
            if not related:
                continue

            preferred = _preferred_overlapping_line(
                existing,
                candidate,
                similarity=similarity,
                first_text=existing_text,
                second_text=candidate_text,
            )
            if preferred is candidate:
                existing_evidence = (
                    existing.to_evidence_dict()
                    if spatial_token_preservation_enabled
                    else existing.to_dict()
                )
                rejected.append(
                    {
                        **existing_evidence,
                        "ocr_pass": origins[index],
                        "accepted": False,
                        "rejection_reason": "overlapping_ocr_candidate",
                        "replaced_by": candidate.text,
                    }
                )
                merged[index] = candidate
                origins[index] = "sparse"
            else:
                candidate_evidence = (
                    candidate.to_evidence_dict()
                    if spatial_token_preservation_enabled
                    else candidate.to_dict()
                )
                rejected.append(
                    {
                        **candidate_evidence,
                        "ocr_pass": "sparse",
                        "accepted": False,
                        "rejection_reason": "overlapping_ocr_candidate",
                        "replaced_by": existing.text,
                    }
                )
            matched = True
            break
        if not matched:
            merged.append(candidate)
            origins.append("sparse")
    merged.sort(
        key=lambda line: (
            float(line.bbox["y"]),
            float(line.bbox["x"]),
        )
    )
    return merged, rejected


def _parse_confidence(value: str) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return None
    return min(confidence, 100.0) / 100.0


def _parse_tsv_words(tsv: str) -> list[tuple[tuple[int, int, int, int], _OCRWord]]:
    words: list[tuple[tuple[int, int, int, int], _OCRWord]] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    required = {
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise RuntimeError("Tesseract returned malformed TSV output.")

    for row in reader:
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        try:
            key = (
                int(row["page_num"]),
                int(row["block_num"]),
                int(row["par_num"]),
                int(row["line_num"]),
            )
            word = _OCRWord(
                text=text,
                left=int(row["left"]),
                top=int(row["top"]),
                width=int(row["width"]),
                height=int(row["height"]),
                confidence=_parse_confidence(row["conf"]),
            )
        except (TypeError, ValueError):
            continue
        if word.width > 0 and word.height > 0:
            words.append((key, word))
            if len(words) > _MAX_OCR_TSV_WORDS:
                raise ValueError("Tesseract TSV word count exceeds the bound.")
    return words


def _join_split_hex_tokens(text: str) -> str:
    """Join long uppercase hexadecimal values split into several OCR tokens."""

    tokens = text.split()
    result: list[str] = []
    index = 0
    while index < len(tokens):
        if not re.fullmatch(r"[A-F0-9]{2,}", tokens[index]):
            result.append(tokens[index])
            index += 1
            continue

        end = index
        joined = ""
        while end < len(tokens) and re.fullmatch(r"[A-F0-9]{2,}", tokens[end]):
            joined += tokens[end]
            end += 1

        if end - index >= 2 and len(joined) >= 24:
            result.append(joined)
        else:
            result.extend(tokens[index:end])
        index = end
    return " ".join(result)


def _split_hex_expected_lengths(label_token: str) -> frozenset[int]:
    """Return exact allowed digest lengths for one adjacent context token."""

    if label_token.endswith((":", "=")):
        label_token = label_token[:-1]
    if not label_token.isascii():
        return frozenset()
    label = label_token.upper()
    if label in _SPLIT_HEX_GENERIC_LABELS:
        return _SPLIT_HEX_GENERIC_LENGTHS
    return _SPLIT_HEX_EXACT_LENGTHS.get(label, frozenset())


def _join_split_hex_tokens_numeric_safe(text: str) -> str:
    """Join only exact, explicitly labeled uppercase digest fragments."""

    if len(text) > MAX_NUMERIC_CLEANUP_LINE_CHARS:
        return text
    tokens = text.split()
    if len(tokens) > MAX_NUMERIC_CLEANUP_TOKENS:
        return text

    result: list[str] = []
    index = 0
    while index < len(tokens):
        if _SPLIT_HEX_FRAGMENT_RE.fullmatch(tokens[index]) is None:
            result.append(tokens[index])
            index += 1
            continue

        end = index
        combined_length = 0
        contains_hex_letter = False
        while (
            end < len(tokens)
            and _SPLIT_HEX_FRAGMENT_RE.fullmatch(tokens[end]) is not None
        ):
            fragment = tokens[end]
            combined_length += len(fragment)
            if (
                end - index + 1 > MAX_SPLIT_HEX_FRAGMENTS
                or combined_length > MAX_SPLIT_HEX_CHARS
            ):
                return text
            contains_hex_letter = contains_hex_letter or any(
                "A" <= character <= "F" for character in fragment
            )
            end += 1

        fragments = tokens[index:end]
        expected_lengths = (
            _split_hex_expected_lengths(tokens[index - 1])
            if index > 0
            else frozenset()
        )
        if (
            len(fragments) >= 2
            and contains_hex_letter
            and combined_length in expected_lengths
        ):
            result.append("".join(fragments))
        else:
            result.extend(fragments)
        index = end
    return " ".join(result)


def _clean_ocr_line(
    text: str,
    *,
    numeric_cleanup_v2_enabled: bool = False,
) -> str:
    text = " ".join(text.split())

    # Signature widgets often contribute a border or icon that Tesseract sees
    # as a lone vertical glyph before a stable field name.
    text = re.sub(
        r"^(?:[|¦!Il1Uu]\s+)+(?=(?:Signed|Signer|Signing)\b)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^[^\w]+(?=(?:Signed|Signer|Signing)\b)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^[|¦!]\s+", "", text)
    text = re.sub(
        r"(?<=:)\s*[|¦!l]\s+(?=(?:am|approve|accept|confirm|review)\b)",
        " I ",
        text,
        flags=re.IGNORECASE,
    )
    cleanup = (
        _join_split_hex_tokens_numeric_safe
        if numeric_cleanup_v2_enabled
        else _join_split_hex_tokens
    )
    return cleanup(text).strip()


def _weighted_confidence(words: Iterable[_OCRWord]) -> float | None:
    numerator = 0.0
    denominator = 0
    for word in words:
        if word.confidence is None:
            continue
        weight = max(len(word.text), 1)
        numerator += word.confidence * weight
        denominator += weight
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _build_lines(
    tsv: str,
    *,
    crop_bounds: tuple[float, float, float, float],
    scale: float,
    page_width: float,
    page_height: float,
    ocr_pass: str = "standard",
    pixel_to_page_transform: Sequence[float] | None = None,
    raster_width: int | None = None,
    raster_height: int | None = None,
    numeric_cleanup_v2_enabled: bool = False,
) -> list[OCRLine]:
    grouped: dict[tuple[int, int, int, int], list[_OCRWord]] = {}
    for key, word in _parse_tsv_words(tsv):
        grouped.setdefault(key, []).append(word)

    if pixel_to_page_transform is None:
        crop_left, _, _, crop_top = crop_bounds
        pixel_to_page_transform = (
            1.0 / scale,
            0.0,
            0.0,
            1.0 / scale,
            crop_left,
            page_height - crop_top,
        )
    if len(pixel_to_page_transform) != 6 or not all(
        math.isfinite(float(value))
        for value in pixel_to_page_transform
    ):
        raise ValueError(
            "pixel_to_page_transform must contain six finite values"
        )
    a, b, c, d, e, f = (
        float(value) for value in pixel_to_page_transform
    )

    def project(pixel_x: float, pixel_y: float) -> tuple[float, float]:
        return (
            a * pixel_x + c * pixel_y + e,
            b * pixel_x + d * pixel_y + f,
        )

    lines: list[OCRLine] = []

    for key in sorted(grouped):
        words = sorted(grouped[key], key=lambda item: (item.left, item.top))
        if (
            raster_width is not None
            and raster_height is not None
            and any(
                word.left < 0
                or word.top < 0
                or word.left + word.width > raster_width
                or word.top + word.height > raster_height
                for word in words
            )
        ):
            raise RuntimeError(
                "Tesseract TSV geometry exceeds the OCR raster."
            )
        text = _clean_ocr_line(
            " ".join(word.text for word in words),
            **(
                {"numeric_cleanup_v2_enabled": True}
                if numeric_cleanup_v2_enabled
                else {}
            ),
        )
        if not text:
            continue

        left = min(word.left for word in words)
        top = min(word.top for word in words)
        right = max(word.left + word.width for word in words)
        bottom = max(word.top + word.height for word in words)
        projected_left, projected_top = project(left, top)
        projected_right, projected_bottom = project(right, bottom)
        x = max(0.0, min(page_width, projected_left))
        y = max(0.0, min(page_height, projected_top))
        width = max(
            0.0,
            min(page_width - x, projected_right - projected_left),
        )
        height = max(
            0.0,
            min(page_height - y, projected_bottom - projected_top),
        )
        tokens: list[OCRToken] = []
        for word_index, word in enumerate(words):
            projected_token_x, projected_token_y = project(
                word.left,
                word.top,
            )
            projected_token_right, projected_token_bottom = project(
                word.left + word.width,
                word.top + word.height,
            )
            token_x = max(
                0.0,
                min(page_width, projected_token_x),
            )
            token_y = max(
                0.0,
                min(page_height, projected_token_y),
            )
            token_width = max(
                0.0,
                min(
                    page_width - token_x,
                    projected_token_right - projected_token_x,
                ),
            )
            token_height = max(
                0.0,
                min(
                    page_height - token_y,
                    projected_token_bottom - projected_token_y,
                ),
            )
            tokens.append(
                OCRToken(
                    text=word.text,
                    bbox=_point_bbox(
                        token_x,
                        token_y,
                        token_width,
                        token_height,
                    ),
                    crop_pixel_bbox=_point_bbox(
                        word.left,
                        word.top,
                        word.width,
                        word.height,
                    ),
                    confidence=word.confidence,
                    ocr_pass=ocr_pass,
                    word_index=word_index,
                )
            )

        lines.append(
            OCRLine(
                text=text,
                bbox=_point_bbox(x, y, width, height),
                confidence=_weighted_confidence(words),
                word_count=len(words),
                ocr_pass=ocr_pass,
                tokens=tokens,
            )
        )
    return lines


def _ocr_png_lines(
    executable: str,
    png_bytes: bytes,
    languages: tuple[str, ...],
    timeout_seconds: float,
    tessdata_path: str | None,
    *,
    crop_bounds: tuple[float, float, float, float],
    scale: float,
    page_width: float,
    page_height: float,
    pixel_to_page_transform: Sequence[float] | None = None,
    raster_width: int | None = None,
    raster_height: int | None = None,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
    sparse_pass_enabled: bool = True,
    primary_page_segmentation_mode: int = 3,
) -> tuple[list[OCRLine], list[dict[str, Any]], list[str]]:
    """Run and reconcile the shared standard/sparse OCR passes.

    Both PDF-rendered regions and direct raster pages use this function.  A
    failure in the supplemental sparse pass is non-fatal: the standard pass is
    retained and the problem is surfaced as a region warning.
    """

    primary_tsv = _run_tesseract_tsv(
        executable,
        png_bytes,
        languages,
        timeout_seconds,
        tessdata_path,
        page_segmentation_mode=primary_page_segmentation_mode,
    )
    primary_lines = _build_lines(
        primary_tsv,
        crop_bounds=crop_bounds,
        scale=scale,
        page_width=page_width,
        page_height=page_height,
        ocr_pass="standard",
        pixel_to_page_transform=pixel_to_page_transform,
        raster_width=raster_width,
        raster_height=raster_height,
        **(
            {"numeric_cleanup_v2_enabled": True}
            if numeric_cleanup_v2_enabled
            else {}
        ),
    )
    warnings: list[str] = []
    if not sparse_pass_enabled:
        return primary_lines, [], warnings
    try:
        sparse_tsv = _run_tesseract_tsv(
            executable,
            png_bytes,
            languages,
            timeout_seconds,
            tessdata_path,
            page_segmentation_mode=11,
        )
        sparse_lines = _build_lines(
            sparse_tsv,
            crop_bounds=crop_bounds,
            scale=scale,
            page_width=page_width,
            page_height=page_height,
            ocr_pass="sparse",
            pixel_to_page_transform=pixel_to_page_transform,
            raster_width=raster_width,
            raster_height=raster_height,
            **(
                {"numeric_cleanup_v2_enabled": True}
                if numeric_cleanup_v2_enabled
                else {}
            ),
        )
        lines, rejected = _merge_sparse_ocr_lines_with_diagnostics(
            primary_lines,
            sparse_lines,
            **(
                {"numeric_cleanup_v2_enabled": True}
                if numeric_cleanup_v2_enabled
                else {}
            ),
            **(
                {"spatial_token_preservation_enabled": True}
                if spatial_token_preservation_enabled
                else {}
            ),
        )
    except subprocess.TimeoutExpired:
        lines = primary_lines
        rejected = []
        warnings.append(
            "Sparse-text OCR timed out; standard OCR was retained."
        )
    except OCRUnavailableError:
        raise
    except Exception as error:
        lines = primary_lines
        rejected = []
        warnings.append(
            f"Sparse-text OCR failed; standard OCR was retained: {error}"
        )
    return lines, rejected, warnings


def run_shared_visual_ocr(
    *args: Any,
    **kwargs: Any,
) -> tuple[list[OCRLine], list[dict[str, Any]], list[str]]:
    """Stable input-neutral seam for direct and PDF-rendered raster OCR."""

    return _ocr_png_lines(*args, **kwargs)


def _completed_ocr_pass_statuses(
    warnings: Sequence[str],
) -> dict[str, str]:
    combined = " ".join(str(warning) for warning in warnings).casefold()
    if "sparse-text ocr timed out" in combined:
        sparse_status = "timed_out"
    elif "sparse-text ocr failed" in combined:
        sparse_status = "failed"
    else:
        sparse_status = "completed"
    return {
        "standard": "completed",
        "sparse": sparse_status,
    }


def _set_region_text(region: ImageRegion) -> None:
    """Update aggregate OCR fields from a region's accepted OCR lines."""

    region.text = "\n".join(line.text for line in region.lines)
    region.confidence = _weighted_confidence(
        _OCRWord(
            text=line.text,
            left=0,
            top=0,
            width=0,
            height=0,
            confidence=line.confidence,
        )
        for line in region.lines
    )


def extract_image_ocr(
    pdf_bytes: bytes,
    tesseract_cmd: str = "tesseract",
    languages: Sequence[str] = ("eng",),
    timeout_seconds: float = 30,
    render_scale: float = _TARGET_RENDER_SCALE,
    max_render_pixels: int = _MAX_RENDER_PIXELS,
    tessdata_path: str | None = None,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
    shared_visual_service_enabled: bool = False,
) -> dict[int, list[ImageRegion]]:
    """Detect visible PDF image objects and OCR each corresponding page crop.

    Args:
        pdf_bytes: Complete PDF file contents.
        tesseract_cmd: Local Tesseract executable name or path.
        languages: Tesseract language identifiers.
        timeout_seconds: Maximum OCR time for each embedded image.
        render_scale: Preferred PDF-point render scale (5 is approximately
            360 DPI).
        max_render_pixels: Per-image memory guard for the rendered crop.
        tessdata_path: Optional local Tesseract trained-data directory.

    Returns:
        A mapping from one-based physical page index to image regions.  Pages
        without visible images are included with an empty list.

    Raises:
        OCRUnavailableError: If the configured Tesseract executable is absent.
        ValueError: If no language is configured or the timeout is invalid.
        pypdfium2.PdfiumError: If the supplied PDF cannot be opened.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if render_scale <= 0:
        raise ValueError("render_scale must be greater than zero.")
    if max_render_pixels <= 0:
        raise ValueError("max_render_pixels must be greater than zero.")

    executable = _resolve_tesseract(tesseract_cmd)
    configured_languages = _normalise_languages(languages)
    document = pdfium.PdfDocument(pdf_bytes)
    results: dict[int, list[ImageRegion]] = {
        page_index: [] for page_index in range(1, len(document) + 1)
    }

    try:
        for zero_based_page_index in range(len(document)):
            page_index = zero_based_page_index + 1
            page = document[zero_based_page_index]
            try:
                page_width, page_height = (float(value) for value in page.get_size())
                image_objects = page.get_objects(
                    filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,)
                )
                for object_index, image_object in enumerate(image_objects):
                    try:
                        bounds = _visible_bounds(
                            image_object,
                            page_width,
                            page_height,
                        )
                    except Exception:
                        # A malformed object whose geometry cannot be read
                        # cannot be represented safely as an image region.
                        continue
                    if bounds is None:
                        continue

                    left, bottom, right, top = bounds
                    width = right - left
                    height = top - bottom
                    pixel_width, pixel_height = _image_dimensions(image_object)
                    region = ImageRegion(
                        page_index=page_index,
                        object_index=object_index,
                        bbox=_point_bbox(
                            left,
                            page_height - top,
                            width,
                            height,
                        ),
                        pixel_width=pixel_width,
                        pixel_height=pixel_height,
                        area_ratio=round(
                            (width * height) / (page_width * page_height),
                            6,
                        ),
                        region_role=(
                            "page_source"
                            if (width * height) / (page_width * page_height)
                            >= 0.85
                            else "content_region"
                        ),
                        region_origin="pdf_embedded",
                        coordinate_unit="pt",
                    )
                    results[page_index].append(region)

                    try:
                        (
                            png_bytes,
                            crop_bounds,
                            scale,
                            _actual_dimensions,
                            crop_to_page_transform,
                        ) = _render_region_png(
                            page,
                            page_width,
                            page_height,
                            bounds,
                            target_scale=render_scale,
                            max_pixels=max_render_pixels,
                        )
                        (
                            region.lines,
                            region.rejected_lines,
                            ocr_warnings,
                        ) = (
                            run_shared_visual_ocr
                            if shared_visual_service_enabled
                            else _ocr_png_lines
                        )(
                            executable,
                            png_bytes,
                            configured_languages,
                            timeout_seconds,
                            tessdata_path,
                            crop_bounds=crop_bounds,
                            scale=scale,
                            page_width=page_width,
                            page_height=page_height,
                            **(
                                {"numeric_cleanup_v2_enabled": True}
                                if numeric_cleanup_v2_enabled
                                else {}
                            ),
                            **(
                                {"spatial_token_preservation_enabled": True}
                                if spatial_token_preservation_enabled
                                else {}
                            ),
                        )
                        region.warnings.extend(ocr_warnings)
                        region.ocr_pass_statuses = (
                            _completed_ocr_pass_statuses(ocr_warnings)
                        )
                        _set_region_text(region)
                    except subprocess.TimeoutExpired:
                        region.ocr_pass_statuses = {
                            "standard": "timed_out",
                            "sparse": "not_run",
                        }
                        region.warnings.append(
                            f"Tesseract timed out after {timeout_seconds:g} seconds."
                        )
                    except OCRUnavailableError:
                        raise
                    except Exception as error:
                        region.ocr_pass_statuses = {
                            "standard": "failed",
                            "sparse": "not_run",
                        }
                        region.warnings.append(f"Image OCR failed: {error}")
            finally:
                page.close()
    finally:
        document.close()

    return results


def extract_rendered_pdf_ocr(
    pdf_bytes: bytes,
    requests: Sequence[PdfRegionRequest],
    tesseract_cmd: str = "tesseract",
    languages: Sequence[str] = ("eng",),
    timeout_seconds: float = 30,
    render_scale: float = _TARGET_RENDER_SCALE,
    max_render_pixels: int = _MAX_RENDER_PIXELS,
    tessdata_path: str | None = None,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
    shared_visual_service_enabled: bool = False,
) -> dict[int, list[ImageRegion]]:
    """Render selected PDF page regions and analyze them with shared OCR.

    This adapter is intentionally selective. Callers request only scanned
    pages, layout-detected visuals without a recoverable embedded raster, or
    regions whose structured/native extraction is incomplete.
    """

    if not requests:
        return {}
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if render_scale <= 0:
        raise ValueError("render_scale must be greater than zero.")
    if max_render_pixels <= 0:
        raise ValueError("max_render_pixels must be greater than zero.")

    executable = _resolve_tesseract(tesseract_cmd)
    configured_languages = _normalise_languages(languages)
    document = pdfium.PdfDocument(pdf_bytes)
    results: dict[int, list[ImageRegion]] = {}
    try:
        for object_index, request in enumerate(requests):
            if request.page_index < 1 or request.page_index > len(document):
                continue
            page = document[request.page_index - 1]
            try:
                page_width, page_height = (
                    float(value) for value in page.get_size()
                )
                try:
                    left = float(request.bbox["x"])
                    top_y = float(request.bbox["y"])
                    width = float(
                        request.bbox.get("width", request.bbox.get("w"))
                    )
                    height = float(
                        request.bbox.get("height", request.bbox.get("h"))
                    )
                except (KeyError, TypeError, ValueError):
                    continue

                left = max(0.0, min(page_width, left))
                top_y = max(0.0, min(page_height, top_y))
                right = max(left, min(page_width, left + width))
                bottom_y = max(top_y, min(page_height, top_y + height))
                if right - left <= 0.01 or bottom_y - top_y <= 0.01:
                    continue

                bounds = (
                    left,
                    page_height - bottom_y,
                    right,
                    page_height - top_y,
                )
                region = ImageRegion(
                    page_index=request.page_index,
                    object_index=object_index,
                    bbox=_point_bbox(
                        left,
                        top_y,
                        right - left,
                        bottom_y - top_y,
                    ),
                    pixel_width=None,
                    pixel_height=None,
                    area_ratio=round(
                        ((right - left) * (bottom_y - top_y))
                        / (page_width * page_height),
                        6,
                    ),
                    content_type=request.content_type,
                    metadata=dict(request.metadata),
                    region_role=request.region_role,
                    region_origin="pdf_page_render",
                    coordinate_unit="pt",
                )
                results.setdefault(request.page_index, []).append(region)
                try:
                    (
                        png_bytes,
                        crop_bounds,
                        scale,
                        actual_dimensions,
                        crop_to_page_transform,
                    ) = _render_region_png(
                        page,
                        page_width,
                        page_height,
                        bounds,
                        target_scale=render_scale,
                        max_pixels=max_render_pixels,
                    )
                    crop_width = crop_bounds[2] - crop_bounds[0]
                    crop_height = crop_bounds[3] - crop_bounds[1]
                    region.pixel_width = max(round(crop_width * scale), 1)
                    region.pixel_height = max(round(crop_height * scale), 1)
                    strict_selective_evidence = bool(
                        request.metadata.get("selective_span_id")
                    )
                    source_note_single_line = bool(
                        request.content_type
                        == "layout_source_note_zone"
                        and request.metadata.get(
                            "layout_source_note_zone"
                        )
                        is True
                    )
                    (
                        region.render_pixel_width,
                        region.render_pixel_height,
                    ) = actual_dimensions
                    region.pixel_to_page_transform = (
                        crop_to_page_transform
                    )
                    region.rendered_crop_bbox = _point_bbox(
                        crop_to_page_transform[4],
                        crop_to_page_transform[5],
                        actual_dimensions[0] * crop_to_page_transform[0],
                        actual_dimensions[1] * crop_to_page_transform[3],
                    )
                    region.rendered_page_size = (
                        page_width,
                        page_height,
                    )
                    (
                        region.lines,
                        region.rejected_lines,
                        ocr_warnings,
                    ) = (
                        run_shared_visual_ocr
                        if shared_visual_service_enabled
                        else _ocr_png_lines
                    )(
                        executable,
                        png_bytes,
                        configured_languages,
                        timeout_seconds,
                        tessdata_path,
                        crop_bounds=crop_bounds,
                        scale=scale,
                        page_width=page_width,
                        page_height=page_height,
                        pixel_to_page_transform=(
                            crop_to_page_transform
                            if strict_selective_evidence
                            else None
                        ),
                        raster_width=(
                            actual_dimensions[0]
                            if strict_selective_evidence
                            else None
                        ),
                        raster_height=(
                            actual_dimensions[1]
                            if strict_selective_evidence
                            else None
                        ),
                        **(
                            {"numeric_cleanup_v2_enabled": True}
                            if numeric_cleanup_v2_enabled
                            else {}
                        ),
                        **(
                            {"spatial_token_preservation_enabled": True}
                            if spatial_token_preservation_enabled
                            else {}
                        ),
                        **(
                            {
                                "sparse_pass_enabled": False,
                                "primary_page_segmentation_mode": 7,
                            }
                            if source_note_single_line
                            else {}
                        ),
                    )
                    region.warnings.extend(ocr_warnings)
                    region.ocr_pass_statuses = (
                        {
                            "standard": "completed",
                            "sparse": "not_run",
                        }
                        if source_note_single_line
                        else _completed_ocr_pass_statuses(ocr_warnings)
                    )
                    if source_note_single_line:
                        region.metadata["ocr_profile"] = (
                            "single_line_standard"
                        )
                    region.metadata["render_scale"] = round(scale, 4)
                    _set_region_text(region)
                except subprocess.TimeoutExpired:
                    region.ocr_pass_statuses = {
                        "standard": "timed_out",
                        "sparse": "not_run",
                    }
                    region.warnings.append(
                        f"Tesseract timed out after {timeout_seconds:g} seconds."
                    )
                except OCRUnavailableError:
                    raise
                except Exception as error:
                    region.ocr_pass_statuses = {
                        "standard": "failed",
                        "sparse": "not_run",
                    }
                    region.warnings.append(f"Rendered-region OCR failed: {error}")
            finally:
                page.close()
    finally:
        document.close()
    return results


def _scaled_raster_png(
    page: RasterPage,
    max_render_pixels: int,
) -> tuple[bytes, float, tuple[int, int]]:
    area = max(page.pixel_width * page.pixel_height, 1)
    if area <= max_render_pixels:
        return (
            page.png_bytes,
            1.0,
            (page.pixel_width, page.pixel_height),
        )

    scale = math.sqrt(max_render_pixels / area)
    width = max(round(page.pixel_width * scale), 1)
    height = max(round(page.pixel_height * scale), 1)
    with Image.open(io.BytesIO(page.png_bytes)) as image:
        resized = image.resize((width, height), Image.Resampling.LANCZOS)
        try:
            output = io.BytesIO()
            resized.save(output, format="PNG")
            return output.getvalue(), scale, (width, height)
        finally:
            resized.close()


def extract_raster_ocr(
    pages: Sequence[RasterPage],
    tesseract_cmd: str = "tesseract",
    languages: Sequence[str] = ("eng",),
    timeout_seconds: float = 30,
    max_render_pixels: int = _MAX_RENDER_PIXELS,
    tessdata_path: str | None = None,
    numeric_cleanup_v2_enabled: bool = False,
    spatial_token_preservation_enabled: bool = False,
    shared_visual_service_enabled: bool = False,
) -> dict[int, list[ImageRegion]]:
    """OCR each oriented standalone raster frame as one full-page region."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero.")
    if max_render_pixels <= 0:
        raise ValueError("max_render_pixels must be greater than zero.")

    executable = _resolve_tesseract(tesseract_cmd)
    configured_languages = _normalise_languages(languages)
    results: dict[int, list[ImageRegion]] = {}

    for page in pages:
        region = ImageRegion(
            page_index=page.page_index,
            object_index=0,
            bbox=_point_bbox(
                0,
                0,
                page.pixel_width,
                page.pixel_height,
            ),
            pixel_width=page.pixel_width,
            pixel_height=page.pixel_height,
            area_ratio=1.0,
            content_type="page_image",
            region_role="page_source",
            region_origin="uploaded_page",
            coordinate_unit="px",
            metadata={
                "frame_index": page.page_index - 1,
                "original_orientation": page.original_orientation,
                "orientation_applied": page.orientation_applied,
            },
        )
        results[page.page_index] = [region]

        try:
            png_bytes, scale, actual_dimensions = _scaled_raster_png(
                page,
                max_render_pixels,
            )
            (
                region.lines,
                region.rejected_lines,
                ocr_warnings,
            ) = (
                run_shared_visual_ocr
                if shared_visual_service_enabled
                else _ocr_png_lines
            )(
                executable,
                png_bytes,
                configured_languages,
                timeout_seconds,
                tessdata_path,
                crop_bounds=(
                    0.0,
                    0.0,
                    float(page.pixel_width),
                    float(page.pixel_height),
                ),
                scale=scale,
                page_width=float(page.pixel_width),
                page_height=float(page.pixel_height),
                **(
                    {"numeric_cleanup_v2_enabled": True}
                    if numeric_cleanup_v2_enabled
                    else {}
                ),
                **(
                    {"spatial_token_preservation_enabled": True}
                    if spatial_token_preservation_enabled
                    else {}
                ),
            )
            region.warnings.extend(ocr_warnings)
            region.ocr_pass_statuses = _completed_ocr_pass_statuses(
                ocr_warnings
            )
            _set_region_text(region)
        except subprocess.TimeoutExpired:
            region.ocr_pass_statuses = {
                "standard": "timed_out",
                "sparse": "not_run",
            }
            region.warnings.append(
                f"Tesseract timed out after {timeout_seconds:g} seconds."
            )
        except OCRUnavailableError:
            raise
        except Exception as error:
            region.ocr_pass_statuses = {
                "standard": "failed",
                "sparse": "not_run",
            }
            region.warnings.append(f"Image OCR failed: {error}")

    return results
