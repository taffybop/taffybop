from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from typing import Any

import pytest
from PIL import Image, ImageDraw

from app.services.visual_raster_diagram import (
    bind_raster_diagram_owner,
    derive_raster_diagram_topology_evidence,
)


def _box(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _line(text: str, box: dict[str, Any]) -> dict[str, Any]:
    return {
        "accepted": True,
        "bbox": deepcopy(box),
        "confidence": 0.97,
        "rejection_reason": None,
        "source": "ocr",
        "text": text,
        "value": text,
        "word_count": len(text.split()),
    }


def _token(
    identifier: str,
    text: str,
    box: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bbox": deepcopy(box),
        "confidence": 0.97,
        "crop_pixel_bbox": {
            "x": box["x"] * 2,
            "y": box["y"] * 2,
            "width": box["width"] * 2,
            "height": box["height"] * 2,
            "unit": "px",
        },
        "duplicate_of": None,
        "line_occurrence_id": f"line-{identifier}",
        "occurrence_id": identifier,
        "ocr_pass": "standard",
        "primary_selected": True,
        "retention_reason": "primary_selected",
        "selected": True,
        "short_alternative": False,
        "text": text,
        "word_index": 0,
    }


def _summary() -> dict[str, Any]:
    return {
        "duplicate_occurrences": 0,
        "fail_closed_overflow": False,
        "invalid_occurrences": 0,
        "occurrence_limit_reached": False,
        "overflow_reason": None,
        "oversized_text_occurrences": 0,
        "primary_selected_occurrences": 2,
        "schema_version": "1.0",
        "selected_occurrences": 2,
        "serialized_byte_limit_reached": False,
        "serialized_occurrence_bytes": 512,
        "short_alternative_limit_reached": False,
        "short_alternative_occurrences": 0,
        "source_token_limit_reached": False,
        "total_occurrences": 2,
        "truncated_occurrences": 0,
    }


def _owner(*, identifier: str = "p1-image1") -> dict[str, Any]:
    first_box = _box(50.0, 45.0, 30.0, 10.0)
    second_box = _box(50.0, 145.0, 30.0, 10.0)
    text = "Start\nEnd"
    return {
        "id": identifier,
        "type": "image",
        "value": text,
        "md": text,
        "ocr_text": text,
        "cleaned_ocr_text": text,
        "raw_ocr_text": text,
        "bbox": _box(10.0, 10.0, 120.0, 180.0),
        "coordinate_unit": "pt",
        "pixel_width": 240,
        "pixel_height": 360,
        "region_role": "content_region",
        "region_origin": "pdf_embedded",
        "items": [_line("Start", first_box), _line("End", second_box)],
        "ocr_occurrence_summary": _summary(),
        "ocr_token_occurrences": [
            _token("owner-start", "Start", first_box),
            _token("owner-end", "End", second_box),
        ],
    }


def _diagram(*, identifier: str = "diagram-a") -> dict[str, Any]:
    owner = _owner()
    item = {
        "id": identifier,
        "type": "diagram",
        "content_type": "diagram",
        "region_role": "content_region",
        # The bounded overshoot models real OCR/layout union behavior.
        "bbox": _box(11.0, 11.0, 119.6, 180.2),
        "caption": "Approval flow",
        "value": "Approval flow\nStart\nEnd",
        "md": "Approval flow\nStart\nEnd",
        "ocr_text": owner["ocr_text"],
        "raw_ocr_text": owner["raw_ocr_text"],
        "items": deepcopy(owner["items"]),
        "ocr_occurrence_summary": deepcopy(owner["ocr_occurrence_summary"]),
        # IDs legitimately differ because public owner projections re-key them.
        "ocr_token_occurrences": [
            {
                **deepcopy(owner["ocr_token_occurrences"][0]),
                "occurrence_id": "item-start",
            },
            {
                **deepcopy(owner["ocr_token_occurrences"][1]),
                "occurrence_id": "item-end",
            },
        ],
    }
    return item


def test_exact_unique_owner_binding_preserves_layout_and_ocr_proof() -> None:
    diagram = _diagram()
    owner = _owner()

    bound = bind_raster_diagram_owner(
        diagram,
        page_items=[diagram],
        detected_images=[owner],
        page_index=1,
        page_unit="pt",
        input_kind="pdf",
    )

    assert bound is not None
    assert bound.owner_id == "p1-image1"
    assert bound.item["bbox"] == owner["bbox"]
    proof = bound.item["meta"]["phase05_raster_diagram_owner"]
    assert proof["layout_bbox"] == diagram["bbox"]
    assert proof["detected_bbox"] == owner["bbox"]
    assert proof["layout_coverage"] >= 0.95
    assert proof["detected_coverage"] >= 0.95
    assert proof["ocr_ledger_sha256"]
    assert bound.item["items"] == owner["items"]
    assert bound.item["ocr_token_occurrences"] == owner["ocr_token_occurrences"]


@pytest.mark.parametrize(
    "mutation",
    (
        "tampered_markdown",
        "tampered_raw_ocr",
        "tampered_line",
        "tampered_summary",
        "tampered_token_geometry",
        "truncated_ledger",
        "wrong_role",
        "wrong_origin",
        "wrong_pixels",
    ),
)
def test_owner_binding_rejects_tampered_or_incomplete_ledger(
    mutation: str,
) -> None:
    diagram = _diagram()
    owner = _owner()
    if mutation == "tampered_markdown":
        owner["md"] += "!"
    elif mutation == "tampered_raw_ocr":
        owner["raw_ocr_text"] += "!"
    elif mutation == "tampered_line":
        owner["items"][0]["text"] = "Changed"
    elif mutation == "tampered_summary":
        owner["ocr_occurrence_summary"]["total_occurrences"] = 3
    elif mutation == "tampered_token_geometry":
        owner["ocr_token_occurrences"][0]["bbox"]["x"] += 1.0
    elif mutation == "truncated_ledger":
        owner["ocr_occurrence_summary"]["occurrence_limit_reached"] = True
    elif mutation == "wrong_role":
        owner["region_role"] = "page_source"
    elif mutation == "wrong_origin":
        owner["region_origin"] = "pdf_page_render"
    elif mutation == "wrong_pixels":
        owner["pixel_width"] = 0

    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[owner],
            page_index=1,
            page_unit="pt",
            input_kind="pdf",
        )
        is None
    )


def test_owner_binding_rejects_duplicate_owner_and_duplicate_claim() -> None:
    diagram = _diagram()
    duplicate_owner = _owner(identifier="p1-image2")
    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[_owner(), duplicate_owner],
            page_index=1,
            page_unit="pt",
            input_kind="pdf",
        )
        is None
    )


def _direct_image_flow() -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    image = Image.new("RGB", (600, 600), "white")
    draw = ImageDraw.Draw(image)
    node_boxes = (
        (210, 25, 390, 85),
        (210, 165, 390, 285),
        (35, 430, 215, 490),
        (385, 430, 565, 490),
    )
    for box in node_boxes:
        draw.rectangle(box, outline="black", width=3)
    # Start -> review.
    draw.line((300, 85, 300, 165), fill="black", width=3)
    draw.polygon(((300, 165), (291, 150), (309, 150)), fill="black")
    # Review -> accepted/rejected fan-out with one shared trunk.
    draw.line((300, 285, 300, 360, 125, 360, 125, 430), fill="black", width=3)
    draw.line((300, 360, 475, 360, 475, 430), fill="black", width=3)
    draw.polygon(((125, 430), (116, 415), (134, 415)), fill="black")
    draw.polygon(((475, 430), (466, 415), (484, 415)), fill="black")

    text_lines = (
        ("Start", (278, 49)),
        ("Review", (274, 181)),
        ("Identity valid", (246, 214)),
        ("Consent present", (241, 249)),
        ("Yes", (180, 341)),
        ("No", (405, 341)),
        ("Accepted", (98, 453)),
        ("Rejected", (448, 453)),
    )
    draw.ellipse((225, 216, 231, 222), fill="black")
    draw.ellipse((225, 251, 231, 257), fill="black")
    items: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] = []
    for line_index, (text, (x, y)) in enumerate(text_lines):
        draw.text((x, y), text, fill="black")
        left, top, right, bottom = draw.textbbox((x, y), text)
        line_box = {
            "x": float(left),
            "y": float(top),
            "width": float(right - left),
            "height": float(bottom - top),
            "unit": "px",
        }
        items.append(_line(text, line_box))
        tokens.append(
            {
                **_token(f"direct-{line_index}", text, line_box),
                "line_occurrence_id": f"direct-line-{line_index}",
            }
        )
    accepted_text = "\n".join(text for text, _point in text_lines)
    summary = _summary()
    summary.update(
        {
            "primary_selected_occurrences": len(tokens),
            "selected_occurrences": len(tokens),
            "total_occurrences": len(tokens),
        }
    )
    owner = {
        "id": "direct-image-owner",
        "type": "image",
        "value": accepted_text,
        "md": accepted_text,
        "ocr_text": accepted_text,
        "cleaned_ocr_text": accepted_text,
        "raw_ocr_text": accepted_text,
        "bbox": {
            "x": 0.0,
            "y": 0.0,
            "width": 600.0,
            "height": 600.0,
            "unit": "px",
        },
        "coordinate_unit": "px",
        "pixel_width": 600,
        "pixel_height": 600,
        "region_role": "page_source",
        "region_origin": "uploaded_page",
        "items": items,
        "ocr_occurrence_summary": summary,
        "ocr_token_occurrences": tokens,
    }
    diagram = {
        "id": "direct-diagram",
        "type": "diagram",
        "content_type": "diagram",
        "region_role": "content_region",
        "bbox": deepcopy(owner["bbox"]),
        "value": accepted_text,
        "md": accepted_text,
        "ocr_text": accepted_text,
        "raw_ocr_text": accepted_text,
        "items": deepcopy(items),
        "ocr_occurrence_summary": deepcopy(summary),
        "ocr_token_occurrences": deepcopy(tokens),
    }
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue(), diagram, owner


def test_direct_image_detector_owns_nodes_details_fanout_and_edge_labels() -> None:
    source, diagram, owner = _direct_image_flow()
    binding = bind_raster_diagram_owner(
        diagram,
        page_items=[diagram],
        detected_images=[owner],
        page_index=1,
        page_unit="px",
        input_kind="image",
    )
    assert binding is not None

    evidence = derive_raster_diagram_topology_evidence(
        binding,
        source,
        page_index=1,
        input_kind="image",
    )

    assert evidence is not None
    assert [node["label"]["text"] for node in evidence["nodes"]] == [
        "Start",
        "Review",
        "Accepted",
        "Rejected",
    ]
    assert [
        detail["text"] for node in evidence["nodes"] for detail in node["details"]
    ] == ["Identity valid", "Consent present"]
    node_text = {
        node["source_object_id"]: node["label"]["text"] for node in evidence["nodes"]
    }
    assert {
        (
            node_text[connector["source_node_source_object_id"]],
            node_text[connector["target_node_source_object_id"]],
            connector.get("label", {}).get("text"),
        )
        for connector in evidence["connectors"]
    } == {
        ("Start", "Review", None),
        ("Review", "Accepted", "Yes"),
        ("Review", "Rejected", "No"),
    }
    assert evidence["accounting"] == {
        "node_count": 4,
        "connector_component_count": 2,
        "connector_count": 3,
        "arrowhead_count": 3,
        "detail_count": 2,
        "unowned_topology_component_count": 0,
    }


def _edit_png(source: bytes, editor: Any) -> bytes:
    with Image.open(BytesIO(source)) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image)
    editor(draw)
    output = BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _sync_direct_ledger(
    diagram: dict[str, Any],
    owner: dict[str, Any],
) -> None:
    text = "\n".join(line["text"] for line in owner["items"])
    owner.update(
        {
            "value": text,
            "md": text,
            "ocr_text": text,
            "cleaned_ocr_text": text,
            "raw_ocr_text": text,
        }
    )
    count = len(owner["ocr_token_occurrences"])
    owner["ocr_occurrence_summary"].update(
        {
            "primary_selected_occurrences": count,
            "selected_occurrences": count,
            "total_occurrences": count,
        }
    )
    diagram.update(
        {
            "value": text,
            "md": text,
            "ocr_text": text,
            "raw_ocr_text": text,
            "items": deepcopy(owner["items"]),
            "ocr_token_occurrences": deepcopy(owner["ocr_token_occurrences"]),
            "ocr_occurrence_summary": deepcopy(owner["ocr_occurrence_summary"]),
        }
    )


def _derive_direct(
    source: bytes,
    diagram: dict[str, Any],
    owner: dict[str, Any],
) -> dict[str, Any] | None:
    binding = bind_raster_diagram_owner(
        diagram,
        page_items=[diagram],
        detected_images=[owner],
        page_index=1,
        page_unit="px",
        input_kind="image",
    )
    assert binding is not None
    return derive_raster_diagram_topology_evidence(
        binding,
        source,
        page_index=1,
        input_kind="image",
    )


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "Sta\x00rt",
        "Sta\x1brt",
        "Sta\x7frt",
        "Sta\nrt",
        "Sta\rrt",
        "Sta\u2028rt",
        "Sta\u2029rt",
        "Sta\u202art",
        "Sta\u202brt",
        "Sta\u202crt",
        "Sta\u202drt",
        "Sta\u202ert",
        "Sta\u2066rt",
        "Sta\u2067rt",
        "Sta\u2068rt",
        "Sta\u2069rt",
    ),
)
def test_owner_binding_rejects_control_or_bidirectional_label_text(
    unsafe_text: str,
) -> None:
    _source, diagram, owner = _direct_image_flow()
    owner["items"][0]["text"] = unsafe_text
    owner["items"][0]["value"] = unsafe_text
    owner["ocr_token_occurrences"][0]["text"] = unsafe_text
    _sync_direct_ledger(diagram, owner)

    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[owner],
            page_index=1,
            page_unit="px",
            input_kind="image",
        )
        is None
    )


def test_owner_binding_rejects_visual_label_codepoint_overflow() -> None:
    _source, diagram, owner = _direct_image_flow()
    oversized = "\U0001f642" * 1_025
    owner["items"][0]["text"] = oversized
    owner["items"][0]["value"] = oversized
    owner["ocr_token_occurrences"][0]["text"] = oversized
    _sync_direct_ledger(diagram, owner)

    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[owner],
            page_index=1,
            page_unit="px",
            input_kind="image",
        )
        is None
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "arrowless",
        "double_ended",
        "spur",
        "orphan",
        "thin_orphan",
        "gray_orphan",
        "light_gray_orphan",
    ),
)
def test_detector_rejects_incomplete_or_unowned_topology_ink(
    mutation: str,
) -> None:
    source, diagram, owner = _direct_image_flow()

    def edit(draw: ImageDraw.ImageDraw) -> None:
        if mutation == "arrowless":
            draw.rectangle((288, 147, 312, 166), fill="white")
            draw.line((300, 145, 300, 165), fill="black", width=3)
            draw.line((210, 165, 390, 165), fill="black", width=3)
        elif mutation == "double_ended":
            draw.polygon(
                ((300, 85), (291, 100), (309, 100)),
                fill="black",
            )
        elif mutation == "spur":
            draw.line((300, 320, 345, 320), fill="black", width=3)
        elif mutation == "orphan":
            draw.line((20, 560, 120, 560), fill="black", width=3)
        elif mutation == "thin_orphan":
            draw.line((20, 560, 120, 560), fill="black", width=1)
        elif mutation == "gray_orphan":
            draw.line((20, 560, 120, 560), fill=(210, 210, 210), width=3)
        else:
            draw.line((20, 560, 120, 560), fill=(220, 220, 220), width=3)

    changed = _edit_png(source, edit)
    assert _derive_direct(changed, diagram, owner) is None


def test_detector_rejects_unmarked_x_crossing() -> None:
    source, diagram, owner = _direct_image_flow()
    added: list[tuple[str, tuple[int, int]]] = []

    def edit(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((5, 100, 155, 150), outline="black", width=3)
        draw.rectangle((445, 100, 595, 150), outline="black", width=3)
        draw.line((155, 125, 445, 125), fill="black", width=3)
        draw.polygon(((445, 125), (430, 116), (430, 134)), fill="black")
        for text, point in (("Left", (60, 116)), ("Right", (500, 116))):
            draw.text(point, text, fill="black")
            added.append((text, point))

    changed = _edit_png(source, edit)
    with Image.open(BytesIO(changed)) as opened:
        measure = ImageDraw.Draw(opened)
        for offset, (text, point) in enumerate(added, start=20):
            left, top, right, bottom = measure.textbbox(point, text)
            box = {
                "x": float(left),
                "y": float(top),
                "width": float(right - left),
                "height": float(bottom - top),
                "unit": "px",
            }
            owner["items"].append(_line(text, box))
            owner["ocr_token_occurrences"].append(
                {
                    **_token(f"cross-{offset}", text, box),
                    "line_occurrence_id": f"cross-line-{offset}",
                }
            )
    _sync_direct_ledger(diagram, owner)
    assert _derive_direct(changed, diagram, owner) is None


def test_detector_rejects_ambiguous_connector_label() -> None:
    source, diagram, owner = _direct_image_flow()
    new_point = (307, 310)

    def edit(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((175, 338, 205, 354), fill="white")
        draw.text(new_point, "Yes", fill="black")

    changed = _edit_png(source, edit)
    with Image.open(BytesIO(changed)) as opened:
        left, top, right, bottom = ImageDraw.Draw(opened).textbbox(
            new_point,
            "Yes",
        )
    box = {
        "x": float(left),
        "y": float(top),
        "width": float(right - left),
        "height": float(bottom - top),
        "unit": "px",
    }
    owner["items"][4]["bbox"] = deepcopy(box)
    owner["ocr_token_occurrences"][4]["bbox"] = deepcopy(box)
    owner["ocr_token_occurrences"][4]["crop_pixel_bbox"] = deepcopy(box)
    owner["ocr_token_occurrences"][4]["crop_pixel_bbox"]["unit"] = "px"
    _sync_direct_ledger(diagram, owner)
    assert _derive_direct(changed, diagram, owner) is None


@pytest.mark.parametrize("mutation", ("malformed", "low_contrast"))
def test_detector_rejects_malformed_or_low_contrast_source(mutation: str) -> None:
    source, diagram, owner = _direct_image_flow()
    if mutation == "malformed":
        changed = b"not-an-image"
    else:
        with Image.open(BytesIO(source)) as opened:
            image = opened.convert("L").point(lambda value: 150 if value < 128 else 200)
        output = BytesIO()
        image.save(output, format="PNG")
        image.close()
        changed = output.getvalue()
    assert _derive_direct(changed, diagram, owner) is None


def test_detector_contains_optional_backend_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, diagram, owner = _direct_image_flow()

    def fail_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic backend failure")

    monkeypatch.setattr(
        "app.services.visual_raster_diagram.Image.open",
        fail_open,
    )
    assert _derive_direct(source, diagram, owner) is None


def _transform_direct_source(
    source: bytes,
    diagram: dict[str, Any],
    owner: dict[str, Any],
    *,
    rotation: int = 0,
    scale: float = 1.0,
    offset: tuple[int, int] = (0, 0),
) -> bytes:
    with Image.open(BytesIO(source)) as opened:
        content = opened.convert("RGB")
    transpose = {
        0: None,
        90: Image.Transpose.ROTATE_90,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_270,
    }.get(rotation)
    if rotation not in {0, 90, 180, 270}:
        raise ValueError("unsupported test rotation")
    if transpose is not None:
        content = content.transpose(transpose)
    if scale != 1.0:
        resized = content.resize(
            (round(content.width * scale), round(content.height * scale)),
            Image.Resampling.LANCZOS,
        )
        content.close()
        content = resized
    canvas = Image.new(
        "RGB",
        (content.width + offset[0] + 40, content.height + offset[1] + 40),
        "white",
    )
    canvas.paste(content, offset)
    original_size = 600.0

    def transform(box: dict[str, Any]) -> dict[str, Any]:
        x = float(box["x"])
        y = float(box["y"])
        width = float(box["width"])
        height = float(box["height"])
        if rotation == 90:
            x, y, width, height = (
                y,
                original_size - (x + width),
                height,
                width,
            )
        elif rotation == 180:
            x, y = (
                original_size - (x + width),
                original_size - (y + height),
            )
        elif rotation == 270:
            x, y, width, height = (
                original_size - (y + height),
                x,
                height,
                width,
            )
        return {
            "x": x * scale + offset[0],
            "y": y * scale + offset[1],
            "width": width * scale,
            "height": height * scale,
            "unit": "px",
        }

    for line in owner["items"]:
        line["bbox"] = transform(line["bbox"])
    for token in owner["ocr_token_occurrences"]:
        token["bbox"] = transform(token["bbox"])
    owner["bbox"] = {
        "x": float(offset[0]),
        "y": float(offset[1]),
        "width": float(content.width),
        "height": float(content.height),
        "unit": "px",
    }
    owner["pixel_width"] = content.width
    owner["pixel_height"] = content.height
    diagram["bbox"] = deepcopy(owner["bbox"])
    _sync_direct_ledger(diagram, owner)
    output = BytesIO()
    canvas.save(output, format="PNG")
    content.close()
    canvas.close()
    return output.getvalue()


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_detector_preserves_multiline_node_order_across_right_angle_rotations(
    rotation: int,
) -> None:
    source, diagram, owner = _direct_image_flow()
    line_boxes: list[dict[str, Any]] = []

    def edit(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((220, 30, 380, 82), fill="white")
        for text, point in (("First", (282, 38)), ("Second", (276, 58))):
            draw.text(point, text, fill="black")
            left, top, right, bottom = draw.textbbox(point, text)
            line_boxes.append(
                {
                    "x": float(left),
                    "y": float(top),
                    "width": float(right - left),
                    "height": float(bottom - top),
                    "unit": "px",
                }
            )

    changed = _edit_png(source, edit)
    owner["items"][0] = _line("First", line_boxes[0])
    owner["items"].insert(1, _line("Second", line_boxes[1]))
    owner["ocr_token_occurrences"][0] = {
        **_token("direct-0", "First", line_boxes[0]),
        "line_occurrence_id": "direct-line-0",
    }
    owner["ocr_token_occurrences"].insert(
        1,
        {
            **_token("direct-start-second", "Second", line_boxes[1]),
            "line_occurrence_id": "direct-line-start-second",
        },
    )
    _sync_direct_ledger(diagram, owner)
    if rotation:
        changed = _transform_direct_source(
            changed,
            diagram,
            owner,
            rotation=rotation,
        )

    evidence = _derive_direct(changed, diagram, owner)

    assert evidence is not None
    labels = {node["label"]["text"] for node in evidence["nodes"]}
    assert "First Second" in labels
    assert "Second First" not in labels
    assert evidence["accounting"]["connector_count"] == 3


@pytest.mark.parametrize(
    ("rotation", "scale", "offset"),
    (
        (90, 1.0, (0, 0)),
        (180, 1.0, (0, 0)),
        (270, 1.0, (0, 0)),
        (0, 0.75, (83, 47)),
    ),
)
def test_detector_is_owner_transform_and_right_angle_orientation_independent(
    rotation: int,
    scale: float,
    offset: tuple[int, int],
) -> None:
    source, diagram, owner = _direct_image_flow()
    changed = _transform_direct_source(
        source,
        diagram,
        owner,
        rotation=rotation,
        scale=scale,
        offset=offset,
    )

    evidence = _derive_direct(changed, diagram, owner)

    assert evidence is not None
    assert evidence["accounting"]["node_count"] == 4
    assert evidence["accounting"]["connector_count"] == 3
    assert evidence["accounting"]["unowned_topology_component_count"] == 0
    assert sorted(
        connector.get("label", {}).get("text")
        for connector in evidence["connectors"]
        if "label" in connector
    ) == ["No", "Yes"]


@pytest.mark.parametrize("glyph", (".", "i", "1"))
def test_detector_does_not_promote_punctuation_letter_or_digit_to_bullets(
    glyph: str,
) -> None:
    source, diagram, owner = _direct_image_flow()
    points = ((225, 211), (225, 246))
    glyph_boxes: list[dict[str, Any]] = []

    def edit(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((221, 211, 235, 227), fill="white")
        draw.rectangle((221, 246, 235, 262), fill="white")
        for point in points:
            draw.text(point, glyph, fill="black")
            left, top, right, bottom = draw.textbbox(point, glyph)
            glyph_boxes.append(
                {
                    "x": float(left),
                    "y": float(top),
                    "width": float(right - left),
                    "height": float(bottom - top),
                    "unit": "px",
                }
            )

    changed = _edit_png(source, edit)
    for detail_index, (item_index, token_index, box) in enumerate(
        zip((2, 3), (2, 3), glyph_boxes, strict=True)
    ):
        lexical_box = owner["ocr_token_occurrences"][token_index]["bbox"]
        left = min(box["x"], lexical_box["x"])
        top = min(box["y"], lexical_box["y"])
        right = max(
            box["x"] + box["width"],
            lexical_box["x"] + lexical_box["width"],
        )
        bottom = max(
            box["y"] + box["height"],
            lexical_box["y"] + lexical_box["height"],
        )
        owner["items"][item_index]["text"] = (
            f"{glyph} {owner['items'][item_index]['text']}"
        )
        owner["items"][item_index]["value"] = owner["items"][item_index]["text"]
        owner["items"][item_index]["word_count"] += 1
        owner["items"][item_index]["bbox"] = {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
            "unit": "px",
        }
        owner["ocr_token_occurrences"][token_index]["word_index"] = 1
        owner["ocr_token_occurrences"].append(
            {
                **_token(f"glyph-{glyph}-{detail_index}", glyph, box),
                "line_occurrence_id": owner["ocr_token_occurrences"][token_index][
                    "line_occurrence_id"
                ],
                "word_index": 0,
            }
        )
    _sync_direct_ledger(diagram, owner)

    evidence = _derive_direct(changed, diagram, owner)

    assert evidence is not None
    assert evidence["accounting"]["detail_count"] == 0
    labels = "\n".join(node["label"]["text"] for node in evidence["nodes"])
    assert f"{glyph} Identity valid" in labels
    assert f"{glyph} Consent present" in labels


@pytest.mark.parametrize("stroke_width", (0, 1))
def test_detector_rejects_unrecognized_label_ink_inside_node(
    stroke_width: int,
) -> None:
    source, diagram, owner = _direct_image_flow()
    changed = _edit_png(
        source,
        lambda draw: draw.text(
            (330, 220),
            "SECRET",
            fill="black",
            stroke_width=stroke_width,
            stroke_fill="black",
        ),
    )

    assert _derive_direct(changed, diagram, owner) is None


@pytest.mark.parametrize("shade", (120, 218))
def test_detector_rejects_unrecognized_gray_label_ink_inside_node(
    shade: int,
) -> None:
    source, diagram, owner = _direct_image_flow()
    changed = _edit_png(
        source,
        lambda draw: draw.text(
            (330, 220),
            "SECRET",
            fill=(shade, shade, shade),
        ),
    )

    assert _derive_direct(changed, diagram, owner) is None


@pytest.mark.parametrize(
    "mutation",
    (
        "overflow_bbox",
        "overflow_confidence",
        "nan_confidence",
        "deep_tree",
        "huge_text",
        "huge_integer",
        "extra_line_tree",
        "extra_token_tree",
    ),
)
def test_owner_binding_rejects_hostile_values_before_materialization(
    mutation: str,
) -> None:
    diagram = _diagram()
    owner = _owner()
    if mutation == "overflow_bbox":
        owner["bbox"]["x"] = 10**10_000
    elif mutation == "overflow_confidence":
        owner["items"][0]["confidence"] = 10**10_000
    elif mutation == "nan_confidence":
        owner["ocr_token_occurrences"][0]["confidence"] = float("nan")
    elif mutation == "deep_tree":
        nested: dict[str, Any] = {}
        cursor = nested
        for _ in range(20):
            cursor["child"] = {}
            cursor = cursor["child"]
        owner["hostile"] = nested
    elif mutation == "huge_text":
        owner["hostile"] = "x" * 8_388_609
    elif mutation == "huge_integer":
        owner["hostile"] = 10**10_000
    elif mutation == "extra_line_tree":
        owner["items"][0]["hostile"] = {"child": {"value": "x"}}
    elif mutation == "extra_token_tree":
        owner["ocr_token_occurrences"][0]["hostile"] = {"child": {"value": "x"}}

    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[owner],
            page_index=1,
            page_unit="pt",
            input_kind="pdf",
        )
        is None
    )


def test_owner_binding_contains_mapping_implementation_exception() -> None:
    class ExplodingMapping(dict[str, Any]):
        def __len__(self) -> int:
            raise RuntimeError("synthetic mapping failure")

    diagram = ExplodingMapping(_diagram())

    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram],
            detected_images=[_owner()],
            page_index=1,
            page_unit="pt",
            input_kind="pdf",
        )
        is None
    )

    competing = _diagram(identifier="diagram-b")
    assert (
        bind_raster_diagram_owner(
            diagram,
            page_items=[diagram, competing],
            detected_images=[_owner()],
            page_index=1,
            page_unit="pt",
            input_kind="pdf",
        )
        is None
    )
