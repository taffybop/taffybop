from __future__ import annotations

import io
from collections.abc import Sequence

import pytest
from PIL import Image, ImageDraw

from app.config import Settings
from app.errors import (
    ImagePixelLimitExceededError,
    InvalidImageError,
    PageLimitExceededError,
)
from app.services.input_documents import (
    InputKind,
    detect_upload_type,
    load_document,
    validate_file_signature,
)


def test_document_page_limit_takes_precedence_over_legacy_pdf_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENT_PAGES", "12")
    monkeypatch.setenv("MAX_PDF_PAGES", "legacy-invalid-value")

    assert Settings.from_env().max_pages == 12


def _single_image_bytes(
    image_format: str,
    *,
    image: Image.Image | None = None,
    exif: Image.Exif | None = None,
) -> bytes:
    owned_image = image is None
    source = image or Image.new("RGB", (32, 20), "white")
    if owned_image:
        ImageDraw.Draw(source).rectangle((2, 2, 9, 9), fill="black")

    output = io.BytesIO()
    options: dict[str, object] = {}
    if image_format == "WEBP":
        options["lossless"] = True
    if exif is not None:
        options["exif"] = exif
    source.save(output, format=image_format, **options)
    if owned_image:
        source.close()
    return output.getvalue()


def _multipage_tiff_bytes(
    colors_and_sizes: Sequence[tuple[str, tuple[int, int]]],
) -> bytes:
    frames = [
        Image.new("RGB", size, color)
        for color, size in colors_and_sizes
    ]
    output = io.BytesIO()
    try:
        frames[0].save(
            output,
            format="TIFF",
            save_all=True,
            append_images=frames[1:],
            compression="tiff_deflate",
        )
    finally:
        for frame in frames:
            frame.close()
    return output.getvalue()


def _animated_webp_bytes() -> bytes:
    frames = [
        Image.new("RGB", (8, 6), "red"),
        Image.new("RGB", (8, 6), "blue"),
    ]
    output = io.BytesIO()
    try:
        frames[0].save(
            output,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
            lossless=True,
        )
    finally:
        for frame in frames:
            frame.close()
    return output.getvalue()


def _open_page_png(png_bytes: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(png_bytes))
    image.load()
    return image


@pytest.mark.parametrize(
    ("filename", "image_format", "mime_type", "source_format"),
    [
        ("scan.png", "PNG", "image/png", "PNG"),
        ("scan.jpg", "JPEG", "image/jpeg", "JPEG"),
        ("scan.jpeg", "JPEG", "image/jpeg", "JPEG"),
        ("scan.tif", "TIFF", "image/tiff", "TIFF"),
        ("scan.tiff", "TIFF", "image/tiff", "TIFF"),
        ("scan.webp", "WEBP", "image/webp", "WEBP"),
    ],
)
def test_loads_supported_single_image_formats_into_one_common_page(
    filename: str,
    image_format: str,
    mime_type: str,
    source_format: str,
) -> None:
    data = _single_image_bytes(image_format)

    loaded = load_document(data, filename, Settings())

    assert loaded.kind is InputKind.IMAGE
    assert loaded.original_bytes == data
    assert loaded.original_filename == filename
    assert loaded.mime_type == mime_type
    assert loaded.source_format == source_format
    assert loaded.processing_filename.endswith(".normalized.png")
    assert len(loaded.pages) == 1

    page = loaded.pages[0]
    assert page.page_index == 1
    assert (page.pixel_width, page.pixel_height) == (32, 20)
    assert page.original_orientation is None
    assert page.orientation_applied is False

    with _open_page_png(page.png_bytes) as normalized:
        assert normalized.format == "PNG"
        assert normalized.mode == "RGB"
        assert normalized.size == (32, 20)

    page_model = page.page_model(source_format)
    assert page_model["page_index"] == 1
    assert page_model["page_number"] == 1
    assert page_model["page_label"] == "1"
    assert page_model["unit"] == "px"
    assert page_model["image_metadata"] == {
        "frame_index": 0,
        "pixel_width": 32,
        "pixel_height": 20,
        "source_format": source_format,
        "original_orientation": None,
        "orientation_applied": False,
    }


def test_transparent_png_is_composited_onto_white_before_processing() -> None:
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    image.putpixel((1, 0), (220, 20, 30, 255))
    try:
        data = _single_image_bytes("PNG", image=image)
    finally:
        image.close()

    loaded = load_document(data, "transparent.png", Settings())

    with _open_page_png(loaded.pages[0].png_bytes) as normalized:
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (255, 255, 255)
        assert normalized.getpixel((1, 0)) == (220, 20, 30)


def test_jpeg_exif_orientation_is_applied_before_page_dimensions_are_recorded() -> None:
    image = Image.new("RGB", (80, 40), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 19, 39), fill="red")
    exif = image.getexif()
    exif[274] = 6
    try:
        data = _single_image_bytes("JPEG", image=image, exif=exif)
    finally:
        image.close()

    loaded = load_document(data, "rotated.jpg", Settings())
    page = loaded.pages[0]

    assert (page.pixel_width, page.pixel_height) == (40, 80)
    assert page.original_orientation == 6
    assert page.orientation_applied is True

    with _open_page_png(page.png_bytes) as normalized:
        top = normalized.getpixel((20, 5))
        bottom = normalized.getpixel((20, 70))
        assert top[0] > 180
        assert top[1] < 100
        assert top[2] < 100
        assert min(bottom) > 200


def test_multipage_tiff_preserves_frame_order_dimensions_and_page_numbers() -> None:
    data = _multipage_tiff_bytes(
        [
            ("red", (11, 7)),
            ("green", (13, 9)),
            ("blue", (15, 11)),
        ]
    )

    loaded = load_document(data, "frames.tiff", Settings())

    assert loaded.processing_filename.endswith(".normalized.tiff")
    assert [page.page_index for page in loaded.pages] == [1, 2, 3]
    assert [
        (page.pixel_width, page.pixel_height) for page in loaded.pages
    ] == [(11, 7), (13, 9), (15, 11)]
    assert [
        page.page_model("TIFF")["page_number"] for page in loaded.pages
    ] == [1, 2, 3]
    assert [
        page.page_model("TIFF")["page_label"] for page in loaded.pages
    ] == ["1", "2", "3"]

    expected_colors = [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
    for page, expected_color in zip(
        loaded.pages,
        expected_colors,
        strict=True,
    ):
        with _open_page_png(page.png_bytes) as normalized:
            assert normalized.getpixel((0, 0)) == expected_color

    with Image.open(io.BytesIO(loaded.processing_bytes)) as normalized_tiff:
        assert normalized_tiff.format == "TIFF"
        assert normalized_tiff.n_frames == 3


def test_animated_webp_is_one_document_page_not_a_multipage_container() -> None:
    loaded = load_document(
        _animated_webp_bytes(),
        "animated.webp",
        Settings(),
    )

    assert len(loaded.pages) == 1
    assert loaded.processing_filename.endswith(".normalized.png")


@pytest.mark.parametrize("signature", [b"II+\x00", b"MM\x00+"])
def test_bigtiff_signatures_pass_declared_type_validation(
    signature: bytes,
) -> None:
    declared = detect_upload_type("large.tiff", "image/tiff")

    validate_file_signature(signature + b"\x08\x00\x00\x00", declared)


def test_rejects_image_bytes_whose_signature_disagrees_with_extension() -> None:
    jpeg = _single_image_bytes("JPEG")

    with pytest.raises(InvalidImageError) as captured:
        load_document(jpeg, "pretends-to-be.png", Settings())

    assert captured.value.details == {
        "reason": "signature_mismatch",
        "expected_format": "PNG",
    }


def test_rejects_corrupt_image_even_when_signature_is_present() -> None:
    corrupt_png = b"\x89PNG\r\n\x1a\n" + b"corrupt image body"

    with pytest.raises(InvalidImageError) as captured:
        load_document(corrupt_png, "corrupt.png", Settings())

    assert captured.value.details == {
        "reason": "decode_failed",
        "expected_format": "PNG",
    }


def test_rejects_tiff_above_frame_limit_before_returning_partial_pages() -> None:
    data = _multipage_tiff_bytes(
        [
            ("red", (4, 4)),
            ("green", (4, 4)),
            ("blue", (4, 4)),
        ]
    )

    with pytest.raises(PageLimitExceededError) as captured:
        load_document(data, "three-pages.tiff", Settings(max_pages=2))

    assert captured.value.details == {
        "max_pages": 2,
        "page_count": 3,
        "document_type": "image",
    }


def test_rejects_single_frame_above_decoded_pixel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", (4, 4), "white")
    try:
        data = _single_image_bytes("PNG", image=image)
    finally:
        image.close()

    def unexpected_copy(_image: Image.Image) -> Image.Image:
        pytest.fail("oversized image pixels must not be copied or decoded")

    monkeypatch.setattr(Image.Image, "copy", unexpected_copy)

    with pytest.raises(ImagePixelLimitExceededError) as captured:
        load_document(
            data,
            "sixteen-pixels.png",
            Settings(
                max_image_pixels=15,
                max_image_total_pixels=100,
            ),
        )

    assert captured.value.details == {
        "frame_index": 0,
        "max_pixels": 15,
        "received_pixels": 16,
    }


def test_rejects_multipage_image_above_total_decoded_pixel_limit() -> None:
    data = _multipage_tiff_bytes(
        [
            ("red", (4, 4)),
            ("green", (4, 4)),
        ]
    )

    with pytest.raises(ImagePixelLimitExceededError) as captured:
        load_document(
            data,
            "too-many-total-pixels.tiff",
            Settings(
                max_image_pixels=16,
                max_image_total_pixels=31,
            ),
        )

    assert captured.value.details == {
        "max_total_pixels": 31,
        "received_at_least_pixels": 32,
    }
