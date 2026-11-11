from __future__ import annotations

import io
from copy import deepcopy

import pytest
from PIL import Image, ImageDraw

from app.services.input_documents import SourcePage
from app.services.raster_table_retry import _detect_grid, recover_raster_tables


def _case(*, shift: int = 0, scale: int = 1, gap: bool = False):
    xs = [shift + scale * x for x in (30, 150, 330, 470)]
    ys = [shift + scale * y for y in (40, 100, 170, 230)]
    image = Image.new("RGB", (xs[-1] + 30, ys[-1] + 40), "white")
    draw = ImageDraw.Draw(image)
    for y in ys:
        draw.line((xs[0], y, xs[-1], y), fill="black", width=3 * scale)
    for x in xs:
        draw.line((x, ys[0], x, ys[-1]), fill="black", width=3 * scale)
    if gap:
        draw.rectangle((xs[0] + 20, ys[0] - 5, xs[0] + 40, ys[0] + 5), fill="white")
    texts = [["Code", "Description", "Count"], ["A1", "First item", "17"], ["B2", "Second item", "17"]]
    for row in range(3):
        for col in range(3):
            draw.text((xs[col] + 12, ys[row] + 12), texts[row][col], fill="black")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    page = SourcePage(1, image.width, image.height, stream.getvalue(), None, False)
    image.close()
    table = {"self_ref": "#/tables/0", "prov": [{"page_no": 1, "bbox": {
        "l": xs[0] - 2, "t": page.pixel_height - ys[0] + 2,
        "r": xs[-1] + 2, "b": page.pixel_height - ys[-1] - 2,
        "coord_origin": "BOTTOMLEFT"}}], "data": {
        "num_rows": 1, "num_cols": 2, "table_cells": [
            {"text": texts[2][col], "bbox": {"l": xs[col] + 12, "t": ys[2] + 12,
              "r": xs[col] + 80, "b": ys[2] + 30, "coord_origin": "TOPLEFT"}}
            for col in (1, 2)
        ]}}
    return {"tables": [table]}, page, xs, ys, texts


def _retry(raw, page, xs, ys, texts):
    grid = _detect_grid(page, raw["tables"][0], 4_000_000)
    assert grid is not None
    width, height = grid.crop[2] - grid.crop[0], grid.crop[3] - grid.crop[1]
    cells = []
    for row in range(3):
        for col in range(3):
            cells.append({"text": texts[row][col], "bbox": {
                "l": xs[col] + 12 - grid.crop[0], "t": ys[row] + 12 - grid.crop[1],
                "r": xs[col] + 80 - grid.crop[0], "b": ys[row] + 30 - grid.crop[1],
                "coord_origin": "TOPLEFT"}, "start_row_offset_idx": row,
                "end_row_offset_idx": row + 1, "start_col_offset_idx": col,
                "end_col_offset_idx": col + 1, "row_span": 1, "col_span": 1})
    return {"tables": [{"prov": [{"page_no": 1, "bbox": {
        "l": 0, "t": height, "r": width, "b": 0, "coord_origin": "BOTTOMLEFT"}}],
        "data": {"num_rows": 3, "num_cols": 3, "table_cells": cells,
                 "grid": [[deepcopy(cell) for cell in cells[r * 3:r * 3 + 3]] for r in range(3)]}}]}


@pytest.mark.parametrize("shift,scale", [(0, 1), (63, 1), (17, 2)])
def test_recovers_only_source_ruled_grid_and_maps_cells_to_original_page(shift, scale):
    raw, page, xs, ys, texts = _case(shift=shift, scale=scale)
    original = deepcopy(raw)
    retry = _retry(raw, page, xs, ys, texts)
    calls = []

    def convert(png):
        calls.append(png)
        with Image.open(io.BytesIO(png)) as crop:
            assert crop.width < page.pixel_width and crop.height < page.pixel_height
        return retry

    summary = recover_raster_tables(raw, [page], convert=convert)
    assert summary["recovered"] == summary["attempted"] == len(calls) == 1
    table = raw["tables"][0]
    assert table["self_ref"] == original["tables"][0]["self_ref"]
    assert table["prov"] == original["tables"][0]["prov"]
    assert [[cell["text"] for cell in row] for row in table["data"]["grid"]] == texts
    assert table["data"]["grid"][1][2]["bbox"] == {
        "l": xs[2] + 12, "t": ys[1] + 12, "r": xs[2] + 80,
        "b": ys[1] + 30, "coord_origin": "TOPLEFT"}
    assert table["meta"]["raster_table_retry"]["original_cells_preserved"] is True
    assert len(summary["events"][0]["crop_sha256"]) == 64
    assert retry["tables"][0]["data"]["table_cells"][0]["bbox"]["l"] != xs[0] + 12


@pytest.mark.parametrize("mutation", ["gap", "no_grid", "valid_original", "nan", "outside", "bad_meta", "too_many_pixels"])
def test_does_not_retry_without_safe_source_geometry(mutation):
    raw, page, *_ = _case(gap=mutation == "gap")
    options = {}
    if mutation == "no_grid":
        image = Image.new("RGB", (page.pixel_width, page.pixel_height), "white")
        output = io.BytesIO(); image.save(output, format="PNG"); image.close()
        page = SourcePage(1, page.pixel_width, page.pixel_height, output.getvalue(), None, False)
    elif mutation == "valid_original":
        raw["tables"][0]["data"]["num_rows"] = 3
    elif mutation == "nan":
        raw["tables"][0]["prov"][0]["bbox"]["l"] = float("nan")
    elif mutation == "outside":
        raw["tables"][0]["prov"][0]["bbox"]["l"] = -10
    elif mutation == "bad_meta":
        raw["tables"][0]["meta"] = "bad"
    elif mutation == "too_many_pixels":
        options["max_pixels"] = 100
    before = repr(raw)
    summary = recover_raster_tables(raw, [page], convert=lambda _: pytest.fail("unexpected retry"), **options)
    assert summary["attempted"] == summary["recovered"] == 0
    assert repr(raw) == before


@pytest.mark.parametrize("mutation", ["multiple_tables", "no_tables", "changed_old", "lost_old", "wrong_position", "wrong_grid", "bad_bbox", "duplicate_cell", "span", "timeout", "failure"])
def test_failed_or_ambiguous_retry_retains_exact_original(mutation):
    raw, page, xs, ys, texts = _case()
    retry = _retry(raw, page, xs, ys, texts)
    data = retry["tables"][0]["data"]
    if mutation == "multiple_tables":
        retry["tables"].append(deepcopy(retry["tables"][0]))
    elif mutation == "no_tables":
        retry["tables"].clear()
    elif mutation in ("changed_old", "lost_old"):
        data["table_cells"][7]["text"] = "wrong" if mutation == "changed_old" else ""
        data["grid"][2][1]["text"] = data["table_cells"][7]["text"]
    elif mutation == "wrong_position":
        data["table_cells"][7]["text"], data["table_cells"][4]["text"] = data["table_cells"][4]["text"], data["table_cells"][7]["text"]
        data["grid"][2][1], data["grid"][1][1] = deepcopy(data["table_cells"][7]), deepcopy(data["table_cells"][4])
    elif mutation == "wrong_grid":
        data["num_rows"] = 4
    elif mutation == "bad_bbox":
        data["table_cells"][0]["bbox"]["l"] = -1
        data["grid"][0][0] = deepcopy(data["table_cells"][0])
    elif mutation == "duplicate_cell":
        data["table_cells"][1] = deepcopy(data["table_cells"][0])
    elif mutation == "span":
        data["table_cells"][0]["row_span"] = 2
        data["grid"][0][0] = deepcopy(data["table_cells"][0])
    before = deepcopy(raw)

    def convert(_):
        if mutation == "timeout":
            raise TimeoutError("synthetic timeout")
        if mutation == "failure":
            raise RuntimeError("synthetic failure")
        return retry

    summary = recover_raster_tables(raw, [page], convert=convert)
    assert summary["attempted"] == 1 and summary["recovered"] == 0
    assert raw == before


def test_retry_budget_is_per_document_even_when_first_retry_fails():
    raw, page, *_ = _case()
    raw["tables"].append(deepcopy(raw["tables"][0]))
    calls = []
    summary = recover_raster_tables(raw, [page], convert=lambda png: calls.append(png) or {"tables": []})
    assert summary["attempted"] == len(calls) == 1


def test_source_cell_value_cannot_be_preserved_by_the_same_value_elsewhere():
    raw, page, xs, ys, texts = _case()
    retry = _retry(raw, page, xs, ys, texts)
    data = retry["tables"][0]["data"]
    data["table_cells"][8]["text"] = "18"
    data["grid"][2][2]["text"] = "18"
    # "17" remains in another row; preserving the token bag is insufficient.
    before = deepcopy(raw)
    assert recover_raster_tables(raw, [page], convert=lambda _: retry)["recovered"] == 0
    assert raw == before


def test_verified_retry_cells_avoid_duplicate_prose_but_keep_other_locations():
    from app.services.ocr import ImageRegion, OCRLine
    from app.services.pipeline import _supplement_unrepresented_raster_ocr

    def box(x, y, width=70):
        return {"x": x, "y": y, "width": width, "height": 20, "w": width, "h": 20}

    table = {"type": "table", "parse_concerns": ["raster_table_recovered_by_regional_ocr"],
             "cells": [{"text": "Accepted", "bbox": box(120, 100)}]}
    region = ImageRegion(1, 0, box(0, 0, 500), 500, 500, 1.0,
                         lines=[OCRLine("Accepted", box(120, 100), 0.95, 1),
                                OCRLine("Accepted", box(400, 100), 0.95, 1),
                                OCRLine("Accepted", box(120, 200), 0.95, 1),
                                OCRLine("Additional note", box(120, 300), 0.95, 2)],
                         region_role="page_source", region_origin="uploaded_page")
    body = {1: []}
    _supplement_unrepresented_raster_ocr(body, {1: [table]}, {1: [region]})
    assert [(item["value"], item["bbox"]["x"], item["bbox"]["y"]) for item in body[1]] == [
        ("Accepted", 400, 100), ("Accepted", 120, 200), ("Additional note", 120, 300),
    ]


def test_partial_retry_warnings_remain_explicit_even_when_grid_is_valid():
    raw, page, xs, ys, texts = _case()
    retry = _retry(raw, page, xs, ys, texts)
    retry["_raster_retry_warnings"] = ["Docling completed with partial success."]
    summary = recover_raster_tables(raw, [page], convert=lambda _: retry)
    assert summary["recovered"] == 1
    assert summary["events"][0]["conversion_status"] == "partial"
    assert summary["events"][0]["warnings"] == ["Docling completed with partial success."]


@pytest.mark.parametrize("text", ["Accepted Accepted", "Accepted extra evidence"])
def test_retry_dedup_does_not_drop_repeated_or_additional_ocr_words(text):
    from app.services.ocr import ImageRegion, OCRLine
    from app.services.pipeline import _supplement_unrepresented_raster_ocr

    box = {"x": 120, "y": 100, "width": 100, "height": 20, "w": 100, "h": 20}
    table = {"type": "table", "parse_concerns": ["raster_table_recovered_by_regional_ocr"],
             "cells": [{"text": "Accepted", "bbox": box}]}
    region = ImageRegion(1, 0, box, 500, 500, 1.0,
                         lines=[OCRLine(text, box, 0.95, len(text.split()))],
                         region_role="page_source", region_origin="uploaded_page")
    body = {1: []}
    _supplement_unrepresented_raster_ocr(body, {1: [table]}, {1: [region]})
    assert [item["value"] for item in body[1]] == [text]
