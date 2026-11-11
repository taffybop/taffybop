"""Bounded, lossless PNG exports of supported embedded PDF image pixels.

This is deliberately separate from chart-source crops. It never renders a page,
resizes an image, invokes OCR, or claims a re-encoded PNG is the original stream.
Only uniquely matched detected_images records receive inline bytes.
"""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import json
import math
from typing import TYPE_CHECKING, Any, Literal
import zlib

import pdfplumber
from pdfminer.pdftypes import resolve1
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from app.models import ParseResult


POLICY = "embedded-image-inline-png-v1"
PNG_PREFIX = "data:image/png;base64,"


@dataclass(frozen=True)
class EmbeddedImageAssetLimits:
    max_assets: int = 16
    max_asset_bytes: int = 2 * 1024 * 1024
    max_total_asset_bytes: int = 8 * 1024 * 1024
    max_response_bytes: int = 48 * 1024 * 1024
    max_pixels: int = 8_000_000
    max_total_pixels: int = 32_000_000
    max_source_bytes: int = 20 * 1024 * 1024
    max_image_occurrences: int = 256


class EmbeddedImageAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    policy_id: Literal["embedded-image-inline-png-v1"] = POLICY
    representation: Literal["decoded_embedded_bitmap"] = "decoded_embedded_bitmap"
    encoding_note: Literal["source pixels converted to RGB and losslessly re-encoded as PNG"] = (
        "source pixels converted to RGB and losslessly re-encoded as PNG"
    )
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_index: int = Field(ge=1)
    source_object_id: int = Field(ge=1)
    source_occurrence_index: int = Field(ge=0)
    source_color_space: Literal["DeviceGray", "DeviceRGB"]
    source_stream_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    pixel_format: Literal["RGB"] = "RGB"
    pixel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/png"] = "image/png"
    encoding: Literal["data_uri_base64"] = "data_uri_base64"
    byte_length: int = Field(ge=1, le=2 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_uri: str = Field(max_length=len(PNG_PREFIX) + 4 * ((2 * 1024 * 1024 + 2) // 3))

    @model_validator(mode="after")
    def validate_bytes_and_pixels(self) -> "EmbeddedImageAsset":
        if self.width * self.height > 8_000_000 or not self.data_uri.startswith(PNG_PREFIX):
            raise ValueError("embedded image format or pixel limit differs")
        data = base64.b64decode(self.data_uri[len(PNG_PREFIX):], validate=True)
        if len(data) != self.byte_length or hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("embedded image byte identity differs")
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode != "RGB" or image.size != (self.width, self.height):
                raise ValueError("embedded image dimensions or pixel format differ")
            if hashlib.sha256(image.tobytes()).hexdigest() != self.pixel_sha256:
                raise ValueError("embedded image decoded pixels differ")
        return self


class _Refusal(ValueError):
    pass


def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def _name(value: Any) -> str:
    return str(getattr(resolve1(value), "name", ""))


def _box(image: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = [image.get(key) for key in ("x0", "top", "width", "height")]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return None
    if min(values[:2]) < 0 or min(values[2:]) <= 0:
        return None
    return tuple(float(value) for value in values)


def _matches(record: dict[str, Any], image: dict[str, Any]) -> bool:
    box = record.get("bbox")
    if record.get("region_origin") != "pdf_embedded" or not isinstance(box, dict):
        return False
    if box.get("unit", record.get("coordinate_unit", "pt")) != "pt":
        return False
    values = [box.get("x"), box.get("y"), box.get("width", box.get("w")), box.get("height", box.get("h"))]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return False
    source_box = _box(image)
    if source_box is None or any(abs(actual - expected) > 0.01 for actual, expected in zip(values, source_box, strict=True)):
        return False
    return (record.get("pixel_width"), record.get("pixel_height")) == image["srcsize"]


def _decode_image(image: dict[str, Any], limits: EmbeddedImageAssetLimits) -> tuple[Image.Image, bytes, str]:
    stream = image["stream"]
    attrs = stream.attrs
    if any(key in attrs for key in ("SMask", "Mask", "Decode")) or attrs.get("ImageMask"):
        raise _Refusal("masked_or_custom_decode_image")
    color_space = _name(attrs.get("ColorSpace"))
    if color_space not in {"DeviceGray", "DeviceRGB"} or resolve1(attrs.get("BitsPerComponent")) != 8:
        raise _Refusal("unsupported_color_space_or_bit_depth")
    width, height = image["srcsize"]
    if not (type(width) is int and type(height) is int and 0 < width <= 8192 and 0 < height <= 8192):
        raise _Refusal("invalid_source_dimensions")
    if width * height > limits.max_pixels:
        raise _Refusal("asset_pixel_limit")
    encoded = stream.get_rawdata()
    if not isinstance(encoded, bytes) or not encoded or len(encoded) > limits.max_asset_bytes:
        raise _Refusal("source_stream_byte_limit")
    filters = resolve1(attrs.get("Filter", []))
    if not isinstance(filters, list):
        filters = [filters]
    filters = [_name(value) for value in filters]
    params = resolve1(attrs.get("DecodeParms", {}))
    if params not in ({}, None):
        raise _Refusal("unsupported_decode_parameters")
    mode = "L" if color_space == "DeviceGray" else "RGB"
    expected_bytes = width * height * (1 if mode == "L" else 3)
    if filters == ["DCTDecode"]:
        with Image.open(io.BytesIO(encoded)) as jpeg:
            if jpeg.format != "JPEG" or jpeg.size != (width, height) or jpeg.mode != mode:
                raise _Refusal("jpeg_source_metadata_mismatch")
            pixels = jpeg.convert("RGB")
    else:
        if filters == ["FlateDecode"]:
            decoder = zlib.decompressobj()
            data = decoder.decompress(encoded, expected_bytes + 1)
            if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                raise _Refusal("invalid_or_oversized_image_stream")
        elif filters == []:
            data = encoded
        else:
            raise _Refusal("unsupported_image_filter")
        if len(data) != expected_bytes:
            raise _Refusal("decoded_source_size_mismatch")
        with Image.frombytes(mode, (width, height), data) as decoded:
            pixels = decoded.convert("RGB")
    return pixels, encoded, color_space


def attach_pdf_embedded_image_assets(
    payload: dict[str, Any], source: bytes, *, limits: EmbeddedImageAssetLimits | None = None,
) -> dict[str, Any]:
    """Return an additive copy with one asset per uniquely associated detection.

    Call on the final complete PDF payload after its other projections. The
    actual compact JSON size, including existing chart assets, is checked for
    each candidate. This is a 48 MiB asset-stage admission budget, leaving margin
    for later runtime sidecars below the frontend's 64 MiB response bound; it is
    not an exact final-wire cap. No base64 is copied into items or canonical views.
    Association uses source page, complete bbox and native dimensions; response
    IDs alone are never source proof. Unsupported cases retain their metadata.
    """
    limits = limits or EmbeddedImageAssetLimits()
    identity = hashlib.sha256(source).hexdigest()
    if (not source or len(source) > limits.max_source_bytes
            or payload.get("document", {}).get("sha256") != identity
            or payload.get("document", {}).get("mime_type") != "application/pdf"):
        return payload
    if _json_bytes(payload) >= limits.max_response_bytes:
        return payload
    output = deepcopy(payload)
    total_bytes = total_pixels = asset_count = occurrences = 0
    try:
        with pdfplumber.open(io.BytesIO(source)) as document:
            for page_record in output.get("pages", []):
                if occurrences >= limits.max_image_occurrences:
                    break
                page_index = page_record.get("page_index")
                if type(page_index) is not int or not 1 <= page_index <= len(document.pages):
                    continue
                records = page_record.get("detected_images", [])
                images = document.pages[page_index - 1].images
                # Uniqueness needs the complete page inventory. Never truncate
                # first and then mistake an omitted duplicate for a unique owner.
                if len(images) > limits.max_image_occurrences - occurrences:
                    marked = []
                    for record in records[:limits.max_image_occurrences]:
                        if not isinstance(record, dict) or record.get("region_origin") != "pdf_embedded" or "asset" in record:
                            continue
                        marked.append((record, record.get("asset_export")))
                        record["asset_export"] = {
                            "status": "unavailable", "reason": "source_occurrence_limit", "policy_id": POLICY,
                        }
                    if _json_bytes(output) > limits.max_response_bytes:
                        for record, previous in marked:
                            if previous is None:
                                del record["asset_export"]
                            else:
                                record["asset_export"] = previous
                    break
                occurrences += len(images)
                for occurrence, image in enumerate(images):
                    matching = [record for record in records if isinstance(record, dict) and _matches(record, image)]
                    if len(matching) != 1:
                        continue
                    target = matching[0]
                    # A second source object at the same placement is ambiguous.
                    if sum(_matches(target, other) for other in images) != 1 or "asset" in target:
                        continue
                    reason: str | None = None
                    asset: dict[str, Any] | None = None
                    pixels: Image.Image | None = None
                    try:
                        if asset_count >= limits.max_assets:
                            raise _Refusal("document_asset_count_limit")
                        source_pixels = image["srcsize"][0] * image["srcsize"][1]
                        if total_pixels + source_pixels > limits.max_total_pixels:
                            raise _Refusal("document_decoded_pixel_limit")
                        total_pixels += source_pixels
                        pixels, encoded, color_space = _decode_image(image, limits)
                        png = io.BytesIO()
                        pixels.save(png, format="PNG", optimize=False, compress_level=9)
                        data = png.getvalue()
                        if len(data) > limits.max_asset_bytes:
                            raise _Refusal("asset_byte_limit")
                        if total_bytes + len(data) > limits.max_total_asset_bytes:
                            raise _Refusal("document_asset_byte_limit")
                        asset = EmbeddedImageAsset(
                            source_document_sha256=identity, page_index=page_index,
                            source_object_id=image["stream"].objid,
                            source_occurrence_index=occurrence, source_color_space=color_space,
                            source_stream_sha256=hashlib.sha256(encoded).hexdigest(),
                            width=pixels.width, height=pixels.height,
                            pixel_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
                            byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            data_uri=PNG_PREFIX + base64.b64encode(data).decode("ascii"),
                        ).model_dump(mode="json")
                    except _Refusal as exc:
                        reason = str(exc)
                    except (ValueError, TypeError, KeyError, OSError, zlib.error):
                        reason = "source_image_decode_failed"
                    finally:
                        if pixels is not None:
                            pixels.close()
                    if asset is not None:
                        target["asset"] = asset
                        if _json_bytes(output) > limits.max_response_bytes:
                            del target["asset"]
                            reason = "response_byte_limit"
                        else:
                            total_bytes += asset["byte_length"]
                            asset_count += 1
                    if reason is not None:
                        target["asset_export"] = {"status": "unavailable", "reason": reason, "policy_id": POLICY}
                        if _json_bytes(output) > limits.max_response_bytes:
                            del target["asset_export"]
    except Exception:
        # Asset export is additive: malformed PDF structure must not discard an
        # otherwise valid parse or leak decoder exception text into its response.
        return payload
    return output


def attach_pdf_embedded_image_assets_to_result(
    result: ParseResult, source: bytes, *, limits: EmbeddedImageAssetLimits | None = None,
) -> ParseResult:
    """Preserve validated table/canonical objects while adding image extras.

    Only detected_images asset/asset_export keys are copied back. The one JSON
    projection counts aliases and None fields as the current API encoder does.
    The budget applies at this stage; later runtime sidecars consume the margin
    below the frontend's 64 MiB bound, not an asserted final-wire guarantee.
    No full ParseResult revalidation or table custody replay happens here.
    """
    if not any(
        isinstance(record, dict)
        and record.get("region_origin") == "pdf_embedded"
        and "asset" not in record
        for page in result.pages
        for records in [(page.model_extra or {}).get("detected_images")]
        if isinstance(records, list)
        for record in records
    ):
        return result
    projected = result.model_dump(mode="json", by_alias=True, exclude_none=False)
    updated = attach_pdf_embedded_image_assets(projected, source, limits=limits)
    if updated is projected:
        return result
    pages = list(result.pages)
    changed = False
    for page_index, (page, raw_page) in enumerate(zip(pages, updated["pages"], strict=True)):
        records = (page.model_extra or {}).get("detected_images")
        candidate_records = raw_page.get("detected_images")
        if not isinstance(records, list) or not isinstance(candidate_records, list) or len(records) != len(candidate_records):
            continue
        copied = list(records)
        page_changed = False
        for index, (original, candidate) in enumerate(zip(records, candidate_records, strict=True)):
            if not isinstance(original, dict) or not isinstance(candidate, dict):
                continue
            additions = {key: candidate[key] for key in ("asset", "asset_export")
                         if key in candidate and candidate[key] != original.get(key)}
            if additions:
                copied[index] = {**original, **additions}
                page_changed = True
        if page_changed:
            pages[page_index] = page.model_copy(update={"detected_images": copied})
            changed = True
    return result.model_copy(update={"pages": pages}) if changed else result
