"""Thin input adapters for PDF documents and standalone raster images."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.errors import (
    ImagePixelLimitExceededError,
    InvalidImageError,
    InvalidPdfError,
    PageLimitExceededError,
    UnsupportedDocumentTypeError,
)


PDF_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/octet-stream",
        "binary/octet-stream",
    }
)

IMAGE_TYPE_BY_EXTENSION: dict[str, tuple[str, str, frozenset[str]]] = {
    ".png": ("PNG", "image/png", frozenset({"image/png"})),
    ".jpg": (
        "JPEG",
        "image/jpeg",
        frozenset({"image/jpeg", "image/jpg", "image/pjpeg"}),
    ),
    ".jpeg": (
        "JPEG",
        "image/jpeg",
        frozenset({"image/jpeg", "image/jpg", "image/pjpeg"}),
    ),
    ".tif": (
        "TIFF",
        "image/tiff",
        frozenset({"image/tiff", "image/x-tiff"}),
    ),
    ".tiff": (
        "TIFF",
        "image/tiff",
        frozenset({"image/tiff", "image/x-tiff"}),
    ),
    ".webp": ("WEBP", "image/webp", frozenset({"image/webp"})),
}

OOXML_TYPE_BY_EXTENSION: dict[str, tuple[str, str, frozenset[str], str]] = {
    ".docx": (
        "DOCX",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/octet-stream",
                "binary/octet-stream",
            }
        ),
        "adapters_docx_native_enabled",
    ),
    ".pptx": (
        "PPTX",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/octet-stream",
                "binary/octet-stream",
            }
        ),
        "adapters_pptx_native_enabled",
    ),
    ".xlsx": (
        "XLSX",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        frozenset(
            {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/octet-stream",
                "binary/octet-stream",
            }
        ),
        "adapters_xlsx_native_enabled",
    ),
}

SUPPORTED_EXTENSIONS = frozenset({".pdf", *IMAGE_TYPE_BY_EXTENSION})


class InputKind(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"


@dataclass(frozen=True, slots=True)
class DeclaredInput:
    kind: InputKind
    extension: str
    mime_type: str
    source_format: str


@dataclass(frozen=True, slots=True)
class SourcePage:
    page_index: int
    pixel_width: int
    pixel_height: int
    png_bytes: bytes
    original_orientation: int | None
    orientation_applied: bool

    def page_model(self, source_format: str) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "page_number": self.page_index,
            "page_label": str(self.page_index),
            "page_width": float(self.pixel_width),
            "page_height": float(self.pixel_height),
            "unit": "px",
            "success": True,
            "items": [],
            "detected_images": [],
            "warnings": [],
            "image_metadata": {
                "frame_index": self.page_index - 1,
                "pixel_width": self.pixel_width,
                "pixel_height": self.pixel_height,
                "source_format": source_format,
                "original_orientation": self.original_orientation,
                "orientation_applied": self.orientation_applied,
            },
        }


@dataclass(frozen=True, slots=True)
class LoadedDocument:
    kind: InputKind
    original_bytes: bytes
    processing_bytes: bytes
    original_filename: str
    processing_filename: str
    mime_type: str
    source_format: str
    pages: tuple[SourcePage, ...] = ()


def _extension_input(
    filename: str,
    settings: Settings | None = None,
) -> DeclaredInput:
    extension = PurePosixPath(filename).suffix.lower()
    if extension == ".pdf":
        return DeclaredInput(
            kind=InputKind.PDF,
            extension=extension,
            mime_type="application/pdf",
            source_format="PDF",
        )
    image_spec = IMAGE_TYPE_BY_EXTENSION.get(extension)
    office_spec = OOXML_TYPE_BY_EXTENSION.get(extension)
    if office_spec is not None and settings is not None:
        source_format, mime_type, _media_types, flag_name = office_spec
        if bool(getattr(settings, flag_name, False)):
            return DeclaredInput(
                kind=InputKind(extension.removeprefix(".")),
                extension=extension,
                mime_type=mime_type,
                source_format=source_format,
            )
    if image_spec is None:
        enabled_extensions = set(SUPPORTED_EXTENSIONS)
        if settings is not None:
            enabled_extensions.update(
                candidate_extension
                for candidate_extension, (*_unused, flag_name) in OOXML_TYPE_BY_EXTENSION.items()
                if bool(getattr(settings, flag_name, False))
            )
        raise UnsupportedDocumentTypeError(
            details={
                "filename": filename or None,
                # Retained for clients that consumed the former PDF-only
                # validation detail.
                "expected_extension": ".pdf",
                "expected_extensions": sorted(enabled_extensions),
                "supported_extensions": sorted(enabled_extensions),
            }
        )
    source_format, mime_type, _ = image_spec
    return DeclaredInput(
        kind=InputKind.IMAGE,
        extension=extension,
        mime_type=mime_type,
        source_format=source_format,
    )


def detect_upload_type(
    filename: str,
    content_type: str | None,
    settings: Settings | None = None,
) -> DeclaredInput:
    """Validate the filename extension and declared HTTP media type."""

    declared = _extension_input(filename, settings)
    media_type = (content_type or "").split(";", 1)[0].strip().lower()

    if declared.kind is InputKind.PDF:
        # Keep the established PDF behavior: a missing content type and generic
        # binary types remain accepted for existing clients.
        if media_type and media_type not in PDF_MEDIA_TYPES:
            raise UnsupportedDocumentTypeError(
                details={
                    "content_type": media_type,
                    "supported_content_types": sorted(PDF_MEDIA_TYPES),
                }
            )
        return declared

    if declared.kind in {InputKind.DOCX, InputKind.PPTX, InputKind.XLSX}:
        _, _, allowed_media_types, _ = OOXML_TYPE_BY_EXTENSION[declared.extension]
    else:
        _, _, allowed_media_types = IMAGE_TYPE_BY_EXTENSION[declared.extension]
    if not media_type or media_type not in allowed_media_types:
        raise UnsupportedDocumentTypeError(
            details={
                "filename": filename or None,
                "content_type": media_type or None,
                "supported_content_types": sorted(allowed_media_types),
            }
        )
    return declared


def validate_file_signature(data: bytes, declared: DeclaredInput) -> None:
    """Reject an empty upload or bytes that disagree with the declared type."""

    if not data:
        if declared.kind is InputKind.PDF:
            raise InvalidPdfError(
                "The uploaded PDF is empty.",
                details={"size_bytes": 0},
            )
        if declared.kind is InputKind.IMAGE:
            raise InvalidImageError(
                "The uploaded image is empty.",
                details={"size_bytes": 0},
            )
        from app.errors import InvalidOoxmlError

        raise InvalidOoxmlError(
            "The uploaded Office package is empty.",
            details={"size_bytes": 0},
        )

    if declared.kind is InputKind.PDF:
        # ISO 32000 readers permit limited leading data before the PDF header.
        if b"%PDF-" not in data[:1024]:
            raise InvalidPdfError(details={"reason": "missing_pdf_header"})
        return

    if declared.kind in {InputKind.DOCX, InputKind.PPTX, InputKind.XLSX}:
        if not data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
            from app.errors import InvalidOoxmlError

            raise InvalidOoxmlError(
                details={
                    "reason": "signature_mismatch",
                    "expected_format": declared.source_format,
                }
            )
        return

    signatures = {
        "PNG": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "JPEG": data.startswith(b"\xff\xd8\xff"),
        "TIFF": data.startswith(
            (
                b"II*\x00",
                b"MM\x00*",
                b"II+\x00",
                b"MM\x00+",
            )
        ),
        "WEBP": (
            len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
        ),
    }
    if not signatures.get(declared.source_format, False):
        raise InvalidImageError(
            details={
                "reason": "signature_mismatch",
                "expected_format": declared.source_format,
            }
        )


def _white_background_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        return background
    converted = image.convert("RGB")
    clean = Image.new("RGB", converted.size, "white")
    clean.paste(converted)
    converted.close()
    return clean


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    # Pillow stores encoder-specific state on the image passed to ``save``.
    # Keep the normalized frame pristine because multi-page TIFF assembly
    # reuses it with a different encoder immediately afterward.
    disposable = image.copy()
    try:
        disposable.save(output, format="PNG", optimize=False)
    finally:
        disposable.close()
    return output.getvalue()


def _normalized_processing_bytes(
    frames: list[Image.Image],
) -> tuple[bytes, str]:
    output = io.BytesIO()
    if len(frames) == 1:
        frames[0].save(output, format="PNG", optimize=False)
        return output.getvalue(), ".png"

    frames[0].save(
        output,
        format="TIFF",
        save_all=True,
        append_images=frames[1:],
        compression="tiff_deflate",
    )
    return output.getvalue(), ".tiff"


def _load_image_document(
    data: bytes,
    filename: str,
    declared: DeclaredInput,
    settings: Settings,
) -> LoadedDocument:
    normalized_frames: list[Image.Image] = []
    source_pages: list[SourcePage] = []
    total_pixels = 0

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                actual_format = str(image.format or "").upper()
                if actual_format != declared.source_format:
                    raise InvalidImageError(
                        details={
                            "reason": "decoded_format_mismatch",
                            "expected_format": declared.source_format,
                            "detected_format": actual_format or None,
                        }
                    )

                # TIFF is the supported multi-page raster container. Animated
                # WebP/APNG files are still one uploaded image and therefore
                # intentionally expose only their first frame.
                frame_count = (
                    int(getattr(image, "n_frames", 1) or 1)
                    if declared.source_format == "TIFF"
                    else 1
                )
                if frame_count > settings.max_pages:
                    raise PageLimitExceededError(
                        details={
                            "max_pages": settings.max_pages,
                            "page_count": frame_count,
                            "document_type": "image",
                        }
                    )

                for frame_index in range(frame_count):
                    image.seek(frame_index)
                    encoded_width, encoded_height = image.size
                    frame_pixels = encoded_width * encoded_height
                    if encoded_width <= 0 or encoded_height <= 0:
                        raise InvalidImageError(
                            details={
                                "reason": "invalid_dimensions",
                                "frame_index": frame_index,
                            }
                        )
                    # Check header dimensions before copying/converting a frame,
                    # because those operations force full pixel allocation.
                    if frame_pixels > settings.max_image_pixels:
                        raise ImagePixelLimitExceededError(
                            details={
                                "frame_index": frame_index,
                                "max_pixels": settings.max_image_pixels,
                                "received_pixels": frame_pixels,
                            }
                        )
                    total_pixels += frame_pixels
                    if total_pixels > settings.max_image_total_pixels:
                        raise ImagePixelLimitExceededError(
                            details={
                                "max_total_pixels": settings.max_image_total_pixels,
                                "received_at_least_pixels": total_pixels,
                            }
                        )

                    original_orientation = image.getexif().get(274)
                    copied = image.copy()
                    try:
                        oriented = ImageOps.exif_transpose(copied)
                        if oriented is not copied:
                            copied.close()
                        rgb = _white_background_rgb(oriented)
                        if rgb is not oriented:
                            oriented.close()
                    except Exception:
                        copied.close()
                        raise

                    width, height = rgb.size
                    if width <= 0 or height <= 0:
                        rgb.close()
                        raise InvalidImageError(
                            details={
                                "reason": "invalid_dimensions",
                                "frame_index": frame_index,
                            }
                        )
                    normalized_frames.append(rgb)
                    source_pages.append(
                        SourcePage(
                            page_index=frame_index + 1,
                            pixel_width=width,
                            pixel_height=height,
                            png_bytes=_png_bytes(rgb),
                            original_orientation=(
                                int(original_orientation)
                                if isinstance(original_orientation, int)
                                else None
                            ),
                            orientation_applied=original_orientation in range(2, 9),
                        )
                    )

        processing_bytes, normalized_extension = _normalized_processing_bytes(
            normalized_frames
        )
    except (
        InvalidImageError,
        ImagePixelLimitExceededError,
        PageLimitExceededError,
    ):
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImagePixelLimitExceededError(
            details={
                "reason": "decoded_dimensions_exceed_safe_limit",
                "max_pixels": settings.max_image_pixels,
            }
        ) from exc
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise InvalidImageError(
            details={
                "reason": "decode_failed",
                "expected_format": declared.source_format,
            }
        ) from exc
    finally:
        for frame in normalized_frames:
            frame.close()

    base_name = str(PurePosixPath(filename).with_suffix("")) or "image"
    return LoadedDocument(
        kind=InputKind.IMAGE,
        original_bytes=data,
        processing_bytes=processing_bytes,
        original_filename=filename,
        processing_filename=f"{base_name}.normalized{normalized_extension}",
        mime_type=declared.mime_type,
        source_format=declared.source_format,
        pages=tuple(source_pages),
    )


def load_document(
    data: bytes,
    filename: str,
    settings: Settings,
) -> LoadedDocument:
    """Load one supported document into the shared extraction input model."""

    declared = _extension_input(filename, settings)
    validate_file_signature(data, declared)

    if declared.kind is InputKind.PDF:
        return LoadedDocument(
            kind=InputKind.PDF,
            original_bytes=data,
            processing_bytes=data,
            original_filename=filename,
            processing_filename=filename or "document.pdf",
            mime_type="application/pdf",
            source_format="PDF",
        )

    if declared.kind in {InputKind.DOCX, InputKind.PPTX, InputKind.XLSX}:
        return LoadedDocument(
            kind=declared.kind,
            original_bytes=data,
            processing_bytes=data,
            original_filename=filename,
            processing_filename=filename,
            mime_type=declared.mime_type,
            source_format=declared.source_format,
        )

    return _load_image_document(data, filename, declared, settings)


def load_document_via_adapter(
    data: bytes,
    filename: str,
    settings: Settings,
    content_type: str | None = None,
) -> Any:
    """Load a registered format through the Phase 07 adapter boundary.

    Keeping this helper separate preserves the exact legacy call path and call
    shape while the conformance flag is off.
    """

    if not settings.adapters_conformance_enabled:
        return load_document(data, filename, settings)
    from app.services.adapter_contracts import builtin_adapter_registry

    registry = builtin_adapter_registry(settings)
    declared = _extension_input(filename, settings)
    dispatch_content_type = content_type or declared.mime_type
    return registry.dispatch(data, filename, dispatch_content_type, settings)
