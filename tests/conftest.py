from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings
from app.main import create_app


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "sample: exercises the supplied reference PDF without loading Docling",
    )
    config.addinivalue_line(
        "markers",
        "integration: exercises installed OCR or document-model dependencies",
    )


@pytest.fixture()
def parsed_document() -> dict[str, Any]:
    """Small normalized result used by endpoint tests without loading Docling."""

    return {
        "schema_version": "1.0",
        "document": {
            "filename": "sample.pdf",
            "mime_type": "application/pdf",
            "sha256": "0" * 64,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "heading",
                        "reading_order": 0,
                        "value": "Sample",
                        "md": "# Sample",
                        "source": "native",
                        "confidence": None,
                    }
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "test-double",
            "ocr_engine": "test-double",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


@pytest.fixture()
def api_app(
    monkeypatch: pytest.MonkeyPatch,
    parsed_document: dict[str, Any],
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_settings] = Settings
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda _data, _filename, _settings: parsed_document,
    )
    monkeypatch.setattr(
        api_module,
        "_serialize_markdown",
        lambda _result: "# Sample\n",
    )
    return application


@pytest.fixture()
def client(api_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(api_app) as test_client:
        yield test_client
    api_app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def sample_pdf_path() -> Path:
    path = Path(__file__).resolve().parents[1] / "Original document.pdf"
    if not path.is_file():
        pytest.skip("The supplied sample PDF is not present.")
    return path


@pytest.fixture(scope="session")
def generic_workaround_pdf_path() -> Path:
    path = (
        Path(__file__).resolve().parents[2]
        / "Oracle Life Sciences Clinical One Cloud Service 25.2.1.3 Generic "
        "Workaround Procedure.pdf"
    )
    if not path.is_file():
        pytest.skip("The supplied generic workaround regression PDF is not present.")
    return path


@pytest.fixture(scope="session")
def finance_pdf_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "finance-10k.pdf"
    if not path.is_file():
        pytest.skip("The supplied finance PDF regression fixture is not present.")
    return path


@pytest.fixture(scope="session")
def finance_reference_json_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "output.json"
    if not path.is_file():
        pytest.skip("The supplied finance JSON reference fixture is not present.")
    return path
