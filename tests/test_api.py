from __future__ import annotations

import io
from copy import deepcopy
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import app.api as api_module
from app.config import MEBIBYTE, Settings, get_settings


VALID_PDF = b"%PDF-1.7\n% test payload\n"
DEFAULT_MAX_UPLOAD_BYTES = 20 * MEBIBYTE


def _image_bytes(image_format: str) -> bytes:
    image = Image.new("RGB", (8, 6), "white")
    output = io.BytesIO()
    options: dict[str, object] = {}
    if image_format == "WEBP":
        options["lossless"] = True
    try:
        image.save(output, format=image_format, **options)
    finally:
        image.close()
    return output.getvalue()


def _upload(
    client: TestClient,
    *,
    filename: str = "sample.pdf",
    content: bytes = VALID_PDF,
    content_type: str = "application/pdf",
    output_format: str = "json",
):
    return client.post(
        f"/v1/parse?output_format={output_format}",
        files={"file": (filename, content, content_type)},
    )


def _assert_error_envelope(
    response,
    *,
    status_code: int,
    code: str,
) -> dict[str, Any]:
    assert response.status_code == status_code
    assert response.headers["content-type"] == "application/json"
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["message"]
    assert isinstance(payload["error"]["details"], dict)
    return payload


def test_upload_limit_defaults_to_20_mib_and_honors_environment_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAX_UPLOAD_BYTES", raising=False)

    assert Settings().max_upload_bytes == DEFAULT_MAX_UPLOAD_BYTES
    assert Settings.from_env().max_upload_bytes == DEFAULT_MAX_UPLOAD_BYTES

    monkeypatch.setenv("MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES + 1))
    assert Settings.from_env().max_upload_bytes == DEFAULT_MAX_UPLOAD_BYTES + 1


def test_parse_pdf_returns_structured_json(
    client: TestClient,
    parsed_document: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, str, Settings]] = []

    def parse(data: bytes, filename: str, settings: Settings) -> dict[str, Any]:
        calls.append((data, filename, settings))
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)

    response = _upload(client, filename="../unsafe/sample.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == parsed_document
    assert len(calls) == 1
    assert calls[0][0] == VALID_PDF
    assert calls[0][1] == "sample.pdf"
    assert isinstance(calls[0][2], Settings)


def test_parse_json_preserves_additive_table_caption_relationships(
    client: TestClient,
    parsed_document: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = deepcopy(parsed_document)
    payload["pages"][0]["items"] = [
        {
            "id": "caption-1",
            "type": "caption",
            "reading_order": 0,
            "value": "Exhibit 7",
            "md": "Exhibit 7",
            "caption_of": "table-1",
            "relationship_id": "layout-rel-1",
            "relationship_type": "caption_of",
            "relationship_basis": "graph_and_geometry",
        },
        {
            "id": "table-1",
            "type": "table",
            "reading_order": 1,
            "value": [["A"]],
            "rows": [["A"]],
            "cells": [],
            "caption_of": ["caption-1"],
            "caption_ids": ["caption-1"],
            "relationships": [
                {
                    "id": "layout-rel-1",
                    "type": "caption_of",
                    "source_id": "caption-1",
                    "target_id": "table-1",
                }
            ],
        },
    ]
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: payload,
    )

    response = _upload(client)

    assert response.status_code == 200
    assert response.json()["pages"][0]["items"] == payload["pages"][0]["items"]


def test_parse_pdf_returns_markdown_content_type(
    client: TestClient,
    parsed_document: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serialized: list[Any] = []

    def serialize(result: Any) -> str:
        serialized.append(result)
        return "# Extracted\n\nImage text\n"

    monkeypatch.setattr(api_module, "_serialize_markdown", serialize)

    response = _upload(client, output_format="markdown")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text == "# Extracted\n\nImage text\n"
    assert serialized == [parsed_document]


@pytest.mark.parametrize(
    ("filename", "content_type", "image_format"),
    [
        ("scan.png", "image/png", "PNG"),
        ("scan.jpg", "image/jpeg", "JPEG"),
        ("scan.jpeg", "image/jpeg", "JPEG"),
        ("scan.tif", "image/tiff", "TIFF"),
        ("scan.tiff", "image/tiff", "TIFF"),
        ("scan.webp", "image/webp", "WEBP"),
        ("UPPER.JPG", "image/jpeg", "JPEG"),
    ],
)
def test_parse_accepts_supported_image_extension_and_mime_pairs(
    client: TestClient,
    parsed_document: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
    image_format: str,
) -> None:
    data = _image_bytes(image_format)
    calls: list[tuple[bytes, str, Settings]] = []

    def parse(
        uploaded: bytes,
        safe_filename: str,
        settings: Settings,
    ) -> dict[str, Any]:
        calls.append((uploaded, safe_filename, settings))
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)

    response = _upload(
        client,
        filename=f"../unsafe/{filename}",
        content=data,
        content_type=content_type,
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == parsed_document
    assert len(calls) == 1
    assert calls[0][0] == data
    assert calls[0][1] == filename
    assert isinstance(calls[0][2], Settings)


@pytest.mark.parametrize(
    ("filename", "content_type", "detail_key"),
    [
        ("sample.txt", "application/pdf", "expected_extension"),
        ("sample.pdf", "text/plain", "supported_content_types"),
    ],
)
def test_rejects_wrong_extension_or_mime_type(
    client: TestClient,
    filename: str,
    content_type: str,
    detail_key: str,
) -> None:
    response = _upload(
        client,
        filename=filename,
        content_type=content_type,
    )

    payload = _assert_error_envelope(
        response,
        status_code=415,
        code="unsupported_document_type",
    )
    assert detail_key in payload["error"]["details"]


def test_rejects_file_without_pdf_magic(client: TestClient) -> None:
    response = _upload(client, content=b"not really a PDF")

    payload = _assert_error_envelope(
        response,
        status_code=422,
        code="invalid_pdf",
    )
    assert payload["error"]["details"]["reason"] == "missing_pdf_header"


def test_rejects_image_extension_and_mime_mismatch(client: TestClient) -> None:
    response = _upload(
        client,
        filename="scan.png",
        content=_image_bytes("PNG"),
        content_type="image/jpeg",
    )

    payload = _assert_error_envelope(
        response,
        status_code=415,
        code="unsupported_document_type",
    )
    assert payload["error"]["details"]["content_type"] == "image/jpeg"
    assert payload["error"]["details"]["supported_content_types"] == [
        "image/png"
    ]


def test_rejects_unsupported_image_type(client: TestClient) -> None:
    response = _upload(
        client,
        filename="scan.gif",
        content=b"GIF89a",
        content_type="image/gif",
    )

    payload = _assert_error_envelope(
        response,
        status_code=415,
        code="unsupported_document_type",
    )
    details = payload["error"]["details"]
    assert details["expected_extension"] == ".pdf"
    assert ".gif" not in details["supported_extensions"]
    assert {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"} <= set(
        details["supported_extensions"]
    )


def test_rejects_empty_image_upload(client: TestClient) -> None:
    response = _upload(
        client,
        filename="empty.png",
        content=b"",
        content_type="image/png",
    )

    payload = _assert_error_envelope(
        response,
        status_code=422,
        code="invalid_image",
    )
    assert payload["error"]["details"] == {"size_bytes": 0}


def test_rejects_image_without_expected_magic(client: TestClient) -> None:
    response = _upload(
        client,
        filename="fake.webp",
        content=b"not really a WebP image",
        content_type="image/webp",
    )

    payload = _assert_error_envelope(
        response,
        status_code=422,
        code="invalid_image",
    )
    assert payload["error"]["details"] == {
        "reason": "signature_mismatch",
        "expected_format": "WEBP",
    }


def test_rejects_upload_above_configured_limit(
    client: TestClient,
    api_app: FastAPI,
) -> None:
    limit = len(VALID_PDF) - 1
    api_app.dependency_overrides[get_settings] = lambda: Settings(
        max_upload_bytes=limit
    )

    response = _upload(client)

    payload = _assert_error_envelope(
        response,
        status_code=413,
        code="upload_too_large",
    )
    assert payload["error"]["details"]["max_bytes"] == limit
    assert payload["error"]["details"]["received_at_least_bytes"] > limit


def test_default_upload_limit_accepts_exact_boundary_and_rejects_plus_one(
    client: TestClient,
) -> None:
    at_limit = VALID_PDF + b"\0" * (
        DEFAULT_MAX_UPLOAD_BYTES - len(VALID_PDF)
    )

    accepted = _upload(client, content=at_limit)
    rejected = _upload(client, content=at_limit + b"\0")

    assert accepted.status_code == 200
    payload = _assert_error_envelope(
        rejected,
        status_code=413,
        code="upload_too_large",
    )
    assert payload["error"]["details"] == {
        "max_bytes": DEFAULT_MAX_UPLOAD_BYTES,
        "received_at_least_bytes": DEFAULT_MAX_UPLOAD_BYTES + 1,
    }


def test_rejects_image_upload_above_configured_byte_limit(
    client: TestClient,
    api_app: FastAPI,
) -> None:
    data = _image_bytes("PNG")
    limit = len(data) - 1
    api_app.dependency_overrides[get_settings] = lambda: Settings(
        max_upload_bytes=limit
    )

    response = _upload(
        client,
        filename="too-large.png",
        content=data,
        content_type="image/png",
    )

    payload = _assert_error_envelope(
        response,
        status_code=413,
        code="upload_too_large",
    )
    assert payload["error"]["details"]["max_bytes"] == limit
    assert payload["error"]["details"]["received_at_least_bytes"] == len(data)


def test_unexpected_parser_error_uses_stable_envelope_without_leaking_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_data: bytes, _filename: str, _settings: Settings) -> None:
        raise RuntimeError("private backend detail")

    monkeypatch.setattr(api_module, "_parse_document", fail)

    response = _upload(client)

    payload = _assert_error_envelope(
        response,
        status_code=500,
        code="document_processing_failed",
    )
    assert "private backend detail" not in response.text
    assert payload["error"]["details"] == {"reason": "RuntimeError"}


def test_request_validation_error_uses_same_envelope(client: TestClient) -> None:
    response = _upload(client, output_format="xml")

    payload = _assert_error_envelope(
        response,
        status_code=422,
        code="request_validation_error",
    )
    assert payload["error"]["details"]["issues"]
    assert any(
        issue["location"][-1] == "output_format"
        for issue in payload["error"]["details"]["issues"]
    )
