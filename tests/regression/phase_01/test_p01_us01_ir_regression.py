from __future__ import annotations

from typing import Any

from app.models import ParseResult
from app.services.ir import round_trip_document


def test_default_v1_projection_has_no_public_ir_fields(
    parsed_document: dict[str, Any],
) -> None:
    validated = ParseResult.model_validate(parsed_document).model_dump(mode="json")
    projected, _ir = round_trip_document(validated)

    assert projected == validated
    assert "ir" not in projected
    assert "elements" not in projected
    assert projected["schema_version"] == "1.0"


def test_pdf_point_and_image_pixel_coordinate_spaces_remain_distinct(
    parsed_document: dict[str, Any],
) -> None:
    image_document = {
        **parsed_document,
        "document": {
            **parsed_document["document"],
            "filename": "scan.png",
            "mime_type": "image/png",
        },
        "pages": [
            {
                **parsed_document["pages"][0],
                "unit": "px",
                "page_width": 1200,
                "page_height": 1600,
            }
        ],
    }

    _pdf_projection, pdf_ir = round_trip_document(parsed_document)
    image_projection, image_ir = round_trip_document(image_document)

    assert pdf_ir.coordinate_systems[0].unit == "pt"
    assert image_ir.coordinate_systems[0].unit == "px"
    assert image_projection == image_document
