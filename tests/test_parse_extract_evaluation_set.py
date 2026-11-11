"""Source/expectation custody checks, not a parser or extraction benchmark."""

from collections import Counter
from decimal import Decimal
import hashlib
import json

import pdfplumber
from PIL import Image, ImageChops, ImageStat
import pytest

from tests.fixtures.parse_extract_v1.builder import FIXTURE_DIR, build_pdf, definitions, render


def load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_source_and_expectation_hashes_and_asset_custody():
    manifest = load("manifest.json")
    assert manifest["corpus_version"] == "px1-initial-v1"
    assert manifest["source_definitions_sha256"] == digest(FIXTURE_DIR / "sources.json")
    assert manifest["expectations_sha256"] == digest(FIXTURE_DIR / "expected.json")
    assert manifest["provider_results"] == []  # No synthetic response can masquerade as observed output.
    assets = manifest["assets"]
    assert len(assets) == 8
    assert len({asset["asset_id"] for asset in assets}) == 8
    for asset in assets:
        path = FIXTURE_DIR / asset["path"]
        assert path.parent == FIXTURE_DIR
        assert digest(path) == asset["sha256"]
        assert path.stat().st_size == asset["size_bytes"] < 10 * 1024 * 1024
        assert asset["authorized_for_provider"] is True
        assert "fictional" in asset["authorization_basis"]


def test_render_siblings_stay_in_same_split_and_are_not_independent_documents():
    manifest = load("manifest.json")
    sources = definitions()
    assert manifest["independent_document_count"] == 4
    assert Counter(source["split"] for source in sources) == {"development": 2, "held_out": 2}
    for source in sources:
        siblings = [asset for asset in manifest["assets"] if asset["document_id"] == source["id"]]
        assert len(siblings) == 2
        assert {asset["split"] for asset in siblings} == {source["split"]}
        assert {asset["family"] for asset in siblings} == {source["family"]}
        assert {asset["media_type"] for asset in siblings} == {"application/pdf", f"image/{source['image_format']}"}


@pytest.mark.parametrize("source", definitions(), ids=lambda source: source["id"])
def test_independently_authored_evidence_is_actually_visible_in_source(source):
    path = FIXTURE_DIR / f"{source['id']}.pdf"
    assert path.read_bytes() == build_pdf(source)
    case = next(case for case in load("expected.json")["cases"] if case["document_id"] == source["id"])
    with pdfplumber.open(path) as document:
        assert len(document.pages) == 1
        page = document.pages[0]
        text = page.extract_text()
        assert source["title"] in text
        assert "synthetic" in text.lower()
        for line in source["lines"]:
            assert line in text
        for field in case["fields"]:
            assert field["evidence"]["page"] == 1
            assert field["evidence"]["quote"] in text
            if field["status"] == "found":
                assert field["value"] is not None
            else:
                assert field["value"] is None
            if field["status"] == "ambiguous":
                assert len(field["candidates"]) == 2
                assert all(candidate in text for candidate in field["candidates"])
        if "repeating_rows" in case:
            expected_rows = case["repeating_rows"]["rows"]
            table = page.extract_tables()[0]
            assert table == [source["table"]["headers"], *source["table"]["rows"]]
            assert [[str(row[column]) for column in case["repeating_rows"]["columns"]] for row in expected_rows] == table[1:]
            amounts = [Decimal(row["unit_price"]) * row["quantity"] for row in expected_rows]
            assert amounts == [Decimal(row["amount"]) for row in expected_rows]
            assert sum(amounts) == Decimal("73.20")
            assert [row["quantity"] for row in expected_rows if row["sku"] == "A100"] == [2, 1]


@pytest.mark.parametrize("source", definitions(), ids=lambda source: source["id"])
def test_image_sibling_is_a_readable_render_of_registered_pdf(source):
    extension = "png" if source["image_format"] == "png" else "jpg"
    with render((FIXTURE_DIR / f"{source['id']}.pdf").read_bytes()) as expected_image:
        with Image.open(FIXTURE_DIR / f"{source['id']}.{extension}") as actual_image:
            assert actual_image.size == expected_image.size == (1224, 1584)
            assert actual_image.width * actual_image.height < 20_000_000
            # Exact PNG pixels; small bounded JPEG loss. This does not prove OCR correctness.
            difference = ImageChops.difference(actual_image.convert("RGB"), expected_image)
            if extension == "png":
                assert difference.getbbox() is None
            else:
                assert max(ImageStat.Stat(difference).rms) < 3


def test_initial_denominators_and_missing_ambiguous_and_critical_expectations_are_frozen():
    cases = load("expected.json")["cases"]
    fields = [field for case in cases for field in case["fields"]]
    assert {case["document_id"] for case in cases} == {source["id"] for source in definitions()}
    assert len(fields) == 16
    assert Counter(field["status"] for field in fields) == {"found": 12, "missing": 3, "ambiguous": 1}
    assert sum(field["critical"] for field in fields) == 10
    assert sum(len(case.get("repeating_rows", {}).get("rows", [])) for case in cases) == 3
