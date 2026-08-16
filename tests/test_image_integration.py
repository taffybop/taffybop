from __future__ import annotations

import io
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_IMAGE_INTEGRATION") != "1",
        reason="Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
    ),
    pytest.mark.skipif(
        shutil.which("tesseract") is None,
        reason="Tesseract is required for image integration tests.",
    ),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    pytest.skip("No deterministic TrueType test font is installed.")


def _png_document() -> bytes:
    image = Image.new("RGB", (1600, 1200), "white")
    draw = ImageDraw.Draw(image)
    title = _font(40)
    body = _font(27)
    draw.text((70, 45), "DOCUMENT INTAKE FORM", fill="black", font=title)
    draw.text(
        (70, 115),
        "Please review every value before approval.",
        fill="black",
        font=body,
    )
    draw.text((70, 180), "Subject ID: 1190014", fill="black", font=body)
    draw.text(
        (70, 240),
        "Status: [X] Reviewed   [ ] Needs follow-up",
        fill="black",
        font=body,
    )

    left, top, right, bottom = 70, 340, 1510, 650
    for y in (top, 420, 525, bottom):
        draw.line((left, y, right, y), fill="black", width=3)
    for x in (left, 430, 1160, right):
        draw.line((x, top, x, bottom), fill="black", width=3)
    rows = [
        ("Field", "Description", "Value"),
        ("Route", "Route of Administration", "Intravenous"),
        (
            "Comment",
            "Complete after data entry for Route item is done",
            "Accepted",
        ),
    ]
    for row_index, row in enumerate(rows):
        y = top + 22 + row_index * 102
        for x, value in zip((90, 450, 1180), row, strict=True):
            draw.text((x, y), value, fill="black", font=body)

    draw.text(
        (70, 735),
        "Approval notes: No missing values were reported.",
        fill="black",
        font=body,
    )
    draw.text((1050, 1100), "RECOVERY_TOKEN_Z9Q7", fill="black", font=body)
    output = io.BytesIO()
    try:
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()


def _visual_document(kind: str) -> bytes:
    image = Image.new("RGB", (1200, 850), "white")
    draw = ImageDraw.Draw(image)
    title = _font(36)
    body = _font(24)
    if kind == "chart":
        draw.text((60, 40), "Revenue by Region", fill="black", font=title)
        draw.line((130, 700, 1050, 700), fill="black", width=4)
        draw.line((130, 180, 130, 700), fill="black", width=4)
        for index, (label, value, color) in enumerate(
            [
                ("North", 40, "#147d73"),
                ("South", 60, "#e97846"),
                ("West", 30, "#6658a6"),
            ]
        ):
            x = 250 + index * 260
            height = value * 7
            draw.rectangle(
                (x, 700 - height, x + 130, 700),
                fill=color,
                outline="black",
                width=2,
            )
            draw.text((x + 25, 715), label, fill="black", font=body)
            draw.text((x + 45, 660 - height), str(value), fill="black", font=body)
    else:
        draw.text((60, 40), "Review Workflow", fill="black", font=title)
        boxes = [
            (80, 300, 300, 410, "Start"),
            (470, 300, 730, 410, "Review"),
            (900, 300, 1120, 410, "Complete"),
        ]
        for left, top, right, bottom, label in boxes:
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=20,
                outline="#166f68",
                width=5,
                fill="#e7f5f2",
            )
            draw.text((left + 55, top + 38), label, fill="black", font=body)
        for start, end in ((300, 470), (730, 900)):
            draw.line((start, 355, end - 18, 355), fill="black", width=5)
            draw.polygon(
                [(end - 18, 343), (end, 355), (end - 18, 367)],
                fill="black",
            )

    output = io.BytesIO()
    try:
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()


def _two_frame_tiff() -> bytes:
    frames: list[Image.Image] = []
    for page_number in (1, 2):
        image = Image.new("RGB", (1200, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.text(
            (80, 80),
            f"FRAME {page_number} UNIQUE TOKEN",
            fill="black",
            font=_font(38),
        )
        frames.append(image)
    output = io.BytesIO()
    try:
        frames[0].save(
            output,
            format="TIFF",
            save_all=True,
            append_images=frames[1:],
            compression="tiff_deflate",
        )
        return output.getvalue()
    finally:
        for frame in frames:
            frame.close()


def _parse(data: bytes, filename: str) -> dict:
    from app.config import Settings
    from app.services.pipeline import parse_document

    return parse_document(
        data,
        filename,
        Settings(document_timeout_seconds=180.0),
    ).model_dump(mode="json")


def _page_text(page: dict) -> str:
    return "\n".join(
        str(item.get("ocr_text") or item.get("value") or "")
        for item in page["items"]
    )


def test_real_text_form_and_table_image_preserves_available_content() -> None:
    from app.services.serializer import to_markdown

    result = _parse(_png_document(), "intake.png")
    page = result["pages"][0]
    text = _page_text(page)

    assert result["document"]["page_count"] == 1
    assert page["page_number"] == 1
    assert page["unit"] == "px"
    assert "DOCUMENT INTAKE FORM" in text
    assert "1190014" in text
    assert "Complete after data entry for Route item is done" in text
    assert "[ ] []" not in text
    assert text.count("RECOVERY_TOKEN_Z9Q7") == 1
    assert "RECOVERY_TOKEN_Z9Q7" in to_markdown(result)
    for table in (item for item in page["items"] if item["type"] == "table"):
        assert table["rows"]
        assert table["cells"]
        assert table["html"]
        assert table["md"]
        assert table["csv"]


def test_real_http_endpoint_accepts_image_multipart() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    "intake.png",
                    _png_document(),
                    "image/png",
                )
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    result = response.json()
    assert result["document"]["filename"] == "intake.png"
    assert result["document"]["mime_type"] == "image/png"
    assert result["document"]["page_count"] == 1
    assert result["pages"][0]["unit"] == "px"


@pytest.mark.parametrize(
    ("kind", "expected_type"),
    [("chart", "chart"), ("diagram", "diagram")],
)
def test_real_visual_classification_is_confidence_gated_and_non_fabricating(
    kind: str,
    expected_type: str,
) -> None:
    result = _parse(_visual_document(kind), f"{kind}.png")
    visuals = [
        item
        for item in result["pages"][0]["items"]
        if item["type"] in {"image", "chart", "diagram"}
    ]
    matching = [item for item in visuals if item["type"] == expected_type]

    assert matching
    assert matching[0]["classification"]["confidence"] >= 0.6
    if expected_type == "chart":
        assert {"40", "60", "30"} <= set(
            str(matching[0]["ocr_text"]).split()
        )
        assert "series" not in matching[0]
        assert matching[0]["parse_concerns"] == [
            "chart_values_not_structured"
        ]
    else:
        assert "relationships" not in matching[0]
        assert "connectors" not in matching[0]
        assert matching[0]["parse_concerns"] == [
            "diagram_relationships_not_structured"
        ]


def test_real_multipage_tiff_keeps_frame_order_and_markdown() -> None:
    from app.services.serializer import to_markdown

    result = _parse(_two_frame_tiff(), "frames.tiff")

    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert [page["unit"] for page in result["pages"]] == ["px", "px"]
    assert "FRAME 1 UNIQUE TOKEN" in _page_text(result["pages"][0])
    assert "FRAME 2 UNIQUE TOKEN" in _page_text(result["pages"][1])
    markdown = to_markdown(result)
    assert "FRAME 1 UNIQUE TOKEN" in markdown
    assert "FRAME 2 UNIQUE TOKEN" in markdown


def test_supplied_photo_cover_has_clean_primary_output_and_region_roles() -> None:
    """Run the exact user fixture when its explicit local path is supplied."""

    from app.services.serializer import to_markdown

    fixture_value = os.getenv("UBEREATS_IMAGE_FIXTURE")
    if not fixture_value:
        pytest.skip("Set UBEREATS_IMAGE_FIXTURE to the supplied cover PNG.")
    fixture = Path(fixture_value)
    if not fixture.is_file():
        pytest.skip(f"Supplied image fixture is unavailable: {fixture}")

    result = _parse(fixture.read_bytes(), fixture.name)
    page = result["pages"][0]
    markdown = to_markdown(result)
    forbidden_primary = (
        "fae",
        "May7,2025",
        "Uber Technologies, Inc, 7",
    )

    assert all(value not in markdown for value in forbidden_primary)
    assert markdown.count("May 7, 2025") == 1
    title = next(
        item
        for item in page["items"]
        if item.get("value") == "Uber Technologies, Inc."
    )
    assert title["type"] == "heading"
    assert title["label"] == "inferred_heading"

    content_region = next(
        item
        for item in page["items"]
        if item.get("region_role") == "content_region"
    )
    page_source = page["detected_images"][0]
    assert page_source["region_role"] == "page_source"
    assert content_region["bbox"]["unit"] == "px"
    assert abs(content_region["bbox"]["x"] - 48) < 2
    assert abs(content_region["bbox"]["y"] - 267) < 2
    assert abs(content_region["bbox"]["width"] - 504) < 3
    assert abs(content_region["bbox"]["height"] - 148) < 3

    rejected = page_source.get("rejected_ocr_candidates") or []
    bad_overlap = next(
        candidate
        for candidate in rejected
        if candidate.get("text") == "Uber Technologies, Inc, 7"
    )
    assert bad_overlap["accepted"] is False
    assert bad_overlap["replaced_by"] == "Uber Technologies, Inc."
    assert all(
        line.get("accepted") is False
        for line in page_source["items"]
        if line.get("text") in {"‘", "fae"}
    )
