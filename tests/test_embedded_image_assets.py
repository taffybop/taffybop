"""Source-pixel identity, association and budgets for embedded bitmap exports."""

import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import zlib

from pdfminer.pdftypes import PDFStream
from pdfminer.psparser import LIT
from PIL import Image
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from pydantic import ValidationError
import pytest
import pdfplumber

import app.services.embedded_image_assets as asset_module

from app.services.embedded_image_assets import (
    EmbeddedImageAsset,
    EmbeddedImageAssetLimits,
    PNG_PREFIX,
    _decode_image,
    _matches,
    attach_pdf_embedded_image_assets,
    attach_pdf_embedded_image_assets_to_result,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "benchmark-expertmodeldata/insurance-acord.pdf"
RESPONSE = ROOT / (
    "tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/"
    "service-final-source-grounded-20260813-v2/insurance-acord/response.json"
)


@pytest.fixture
def observed():
    return json.loads(RESPONSE.read_text()), SOURCE.read_bytes()


def _record(payload):
    return payload["pages"][0]["detected_images"][0]


def _size(payload):
    return len(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())


def test_real_saved_response_gets_source_pixels_once_without_changing_ocr(observed):
    payload, source = observed
    before = deepcopy(payload)
    result = attach_pdf_embedded_image_assets(payload, source)
    assert payload == before
    asset = _record(result)["asset"]
    assert asset["representation"] == "decoded_embedded_bitmap"
    assert (asset["width"], asset["height"]) == (285, 122)
    assert asset["source_document_sha256"] == hashlib.sha256(source).hexdigest()
    assert asset["source_object_id"] == 23
    assert asset["source_stream_sha256"] == "181cd2a2ce998594e71d8c8b8cdf232c158d6367bc721be3256b9fa1eb444eea"
    png = base64.b64decode(asset["data_uri"][len(PNG_PREFIX):], validate=True)
    assert len(png) == asset["byte_length"]
    assert hashlib.sha256(png).hexdigest() == asset["sha256"]
    # Independent decoder: compare native embedded pixels, never a page crop.
    with pdfium.PdfDocument(source) as document:
        page = document[0]
        source_image = list(page.get_objects(filter=(pdfium_raw.FPDF_PAGEOBJ_IMAGE,)))[0]
        bitmap = source_image.get_bitmap(render=False)
        expected = bitmap.to_pil().convert("RGB")
        try:
            with Image.open(io.BytesIO(png)) as exported:
                assert exported.size == expected.size
                assert exported.tobytes() == expected.tobytes()
                assert asset["pixel_sha256"] == hashlib.sha256(expected.tobytes()).hexdigest()
        finally:
            expected.close()
            bitmap.close()
            page.close()
    assert json.dumps(result).count(asset["data_uri"]) == 1
    del _record(result)["asset"]
    assert result == before


@pytest.mark.parametrize("change", ["wrong_source", "wrong_dimensions", "shifted_bbox", "page_crop", "duplicate_detection"])
def test_no_asset_is_assigned_without_unique_source_association(observed, change):
    payload, source = observed
    if change == "wrong_source":
        payload["document"]["sha256"] = "0" * 64
    elif change == "wrong_dimensions":
        _record(payload)["pixel_width"] += 1
    elif change == "shifted_bbox":
        _record(payload)["bbox"]["x"] += 1
    elif change == "page_crop":
        _record(payload)["region_origin"] = "pdf_page_render"
    else:
        payload["pages"][0]["detected_images"].append(deepcopy(_record(payload)))
    result = attach_pdf_embedded_image_assets(payload, source)
    assert all("asset" not in item for item in result["pages"][0]["detected_images"])


@pytest.mark.parametrize(("limits", "reason"), [
    (replace(EmbeddedImageAssetLimits(), max_assets=0), "document_asset_count_limit"),
    (replace(EmbeddedImageAssetLimits(), max_pixels=1), "asset_pixel_limit"),
    (replace(EmbeddedImageAssetLimits(), max_total_pixels=1), "document_decoded_pixel_limit"),
    (replace(EmbeddedImageAssetLimits(), max_total_asset_bytes=1), "document_asset_byte_limit"),
])
def test_asset_limits_refuse_explicitly_without_losing_detected_metadata(observed, limits, reason):
    payload, source = observed
    result = attach_pdf_embedded_image_assets(payload, source, limits=limits)
    assert "asset" not in _record(result)
    assert _record(result)["asset_export"]["reason"] == reason
    del _record(result)["asset_export"]
    assert result == payload


def test_actual_response_budget_includes_preexisting_payload_bytes(observed):
    payload, source = observed
    payload["preexisting_artifact"] = "existing bytes already in response" * 1000
    maximum = _size(payload) + 200
    result = attach_pdf_embedded_image_assets(
        payload, source, limits=replace(EmbeddedImageAssetLimits(), max_response_bytes=maximum)
    )
    assert "asset" not in _record(result)
    assert _record(result)["asset_export"]["reason"] == "response_byte_limit"
    assert _size(result) <= maximum
    assert attach_pdf_embedded_image_assets(
        payload, source, limits=replace(EmbeddedImageAssetLimits(), max_response_bytes=_size(payload))
    ) is payload


def test_existing_asset_is_not_overwritten_or_duplicated(observed):
    payload, source = observed
    _record(payload)["asset"] = {"existing": "untouched"}
    assert attach_pdf_embedded_image_assets(payload, source) == payload


def test_asset_validator_rechecks_png_dimensions_byte_hash_and_pixel_hash(observed):
    payload, source = observed
    asset = _record(attach_pdf_embedded_image_assets(payload, source))["asset"]
    EmbeddedImageAsset.model_validate(asset)
    for field, value in (("width", 286), ("sha256", "0" * 64), ("pixel_sha256", "0" * 64)):
        with pytest.raises(ValidationError):
            EmbeddedImageAsset.model_validate({**asset, field: value})


def test_masked_custom_decode_and_expanding_streams_are_not_silently_rendered():
    attrs = {"Width": 1, "Height": 1, "BitsPerComponent": 8, "ColorSpace": LIT("DeviceGray"), "Filter": LIT("FlateDecode")}
    for extra, reason in [({"SMask": 1}, "masked_or_custom_decode_image"), ({"Decode": [1, 0]}, "masked_or_custom_decode_image"), ({"DecodeParms": {"Predictor": 12}}, "unsupported_decode_parameters")]:
        image = {"srcsize": (1, 1), "stream": PDFStream({**attrs, **extra}, zlib.compress(b"\xff"))}
        with pytest.raises(ValueError, match=reason):
            _decode_image(image, EmbeddedImageAssetLimits())
    image = {"srcsize": (1, 1), "stream": PDFStream(attrs, zlib.compress(b"x" * 1_000_000))}
    with pytest.raises(ValueError, match="invalid_or_oversized_image_stream"):
        _decode_image(image, EmbeddedImageAssetLimits())


def test_supported_jpeg_exports_decoded_pixels_at_native_dimensions():
    with Image.new("RGB", (8, 6), (40, 100, 170)) as image:
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG")
    jpeg = encoded.getvalue()
    attrs = {"Width": 8, "Height": 6, "BitsPerComponent": 8, "ColorSpace": LIT("DeviceRGB"), "Filter": LIT("DCTDecode")}
    actual, original, color_space = _decode_image({"srcsize": (8, 6), "stream": PDFStream(attrs, jpeg)}, EmbeddedImageAssetLimits())
    try:
        with Image.open(io.BytesIO(jpeg)) as expected:
            assert actual.size == expected.size
            assert actual.tobytes() == expected.convert("RGB").tobytes()
        assert original == jpeg
        assert color_space == "DeviceRGB"
    finally:
        actual.close()


@pytest.mark.parametrize(("field", "value"), [
    ("x0", float("nan")), ("top", float("inf")), ("width", 0),
    ("height", -1), ("x0", -1), ("height", float("nan")),
])
def test_nonfinite_or_invalid_source_geometry_never_matches(field, value):
    record = {"region_origin": "pdf_embedded", "pixel_width": 10, "pixel_height": 10,
              "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}
    source = {"x0": 0, "top": 0, "width": 10, "height": 10, "srcsize": (10, 10)}
    source[field] = value
    assert not _matches(record, source)


@pytest.mark.parametrize("source_occurrences", [1, 2])
def test_occurrence_budget_bounds_uniqueness_and_stops_later_page_inventory(
    observed, monkeypatch, source_occurrences,
):
    payload, source = observed
    with pdfplumber.open(io.BytesIO(source)) as document:
        source_image = document.pages[0].images[0]
    payload["pages"].append({**deepcopy(payload["pages"][0]), "page_index": 2})
    later_page_reads = []

    class FirstPage:
        images = [source_image] * source_occurrences

    class LaterPage:
        @property
        def images(self):
            later_page_reads.append(True)
            raise AssertionError("Exhausted occurrence budget must stop source-page inspection.")

    class Document:
        pages = [FirstPage(), LaterPage()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(asset_module.pdfplumber, "open", lambda *_args, **_kwargs: Document())
    result = attach_pdf_embedded_image_assets(
        payload, source, limits=replace(EmbeddedImageAssetLimits(), max_image_occurrences=1)
    )
    assert later_page_reads == []
    if source_occurrences == 1:
        assert "asset" in _record(result)
    else:
        assert "asset" not in _record(result)
        assert _record(result)["asset_export"]["reason"] == "source_occurrence_limit"


@pytest.mark.parametrize("max_assets", [0, 16])
def test_typed_wrapper_preserves_cached_tables_and_all_non_asset_fields(
    observed, monkeypatch, max_assets,
):
    from app.models import ParseResult

    payload, source = observed
    validated = ParseResult.model_validate(payload)
    before = validated.model_dump(mode="json")
    cached_tables = [item for item in validated.pages[0].items if item.type in {"table", "table_candidate"}]
    assert cached_tables

    def forbid_revalidation(*_args, **_kwargs):
        raise AssertionError("Asset attachment must not replay the table custody transaction.")

    monkeypatch.setattr(ParseResult, "model_validate", forbid_revalidation)
    result = attach_pdf_embedded_image_assets_to_result(
        validated, source, limits=replace(EmbeddedImageAssetLimits(), max_assets=max_assets)
    )
    assert result is not validated
    assert result.pages[0].items is validated.pages[0].items
    retained_tables = [item for item in result.pages[0].items if item.type in {"table", "table_candidate"}]
    assert all(actual is original for actual, original in zip(retained_tables, cached_tables, strict=True))
    assert result.document is validated.document
    assert result.processing is validated.processing
    assert result.canonical_source_custody is validated.canonical_source_custody
    if "canonical_presentation" in (validated.model_extra or {}):
        assert result.model_extra["canonical_presentation"] is validated.model_extra["canonical_presentation"]
    after = result.model_dump(mode="json")
    record = _record(after)
    assert ("asset" if max_assets else "asset_export") in record
    record.pop("asset", None)
    record.pop("asset_export", None)
    assert after == before
    assert validated.model_dump(mode="json") == before


@pytest.mark.parametrize("records", [None, "malformed", 42, [], [{"region_origin": "pdf_page_render"}],
    [{"region_origin": "pdf_embedded", "asset": {"existing": True}}]])
def test_typed_wrapper_skips_serialization_and_pdf_loading_without_eligible_images(
    observed, monkeypatch, records,
):
    from app.models import ParseResult

    payload, source = observed
    payload["pages"][0]["detected_images"] = records
    validated = ParseResult.model_validate(payload)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("An ineligible PDF must not be serialized or reparsed.")

    monkeypatch.setattr(ParseResult, "model_dump", unexpected)
    monkeypatch.setattr(asset_module.pdfplumber, "open", unexpected)
    assert attach_pdf_embedded_image_assets_to_result(validated, source) is validated


def test_typed_wrapper_budget_projection_matches_api_alias_and_null_encoding(observed, monkeypatch):
    from app.models import ParseResult
    from fastapi.encoders import jsonable_encoder

    payload, source = observed
    validated = ParseResult.model_validate(payload)
    expected = jsonable_encoder(validated)
    observed_projection = []

    def inspect_projection(projected, _source, **_kwargs):
        observed_projection.append(projected)
        return projected

    monkeypatch.setattr(asset_module, "attach_pdf_embedded_image_assets", inspect_projection)
    assert attach_pdf_embedded_image_assets_to_result(validated, source) is validated
    assert observed_projection == [expected]
