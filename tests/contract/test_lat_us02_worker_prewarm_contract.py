"""LAT-US02 public configuration and API compatibility contracts."""

from __future__ import annotations

from collections.abc import Iterator
import inspect
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings
from app.errors import ExtractionEngineUnavailableError
from app.main import create_app
from app.models import ErrorResponse
from app.services import pipeline


_PREWARM_ENVIRONMENT = (
    "PARSER_LATENCY_PREWARM_ENABLED",
    "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
    "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
    "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256",
    "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256",
    "DOCLING_ARTIFACTS_PATH",
    "TESSERACT_CMD",
    "TESSERACT_DATA_PATH",
)


@pytest.fixture()
def clean_prewarm_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[pytest.MonkeyPatch]:
    for name in _PREWARM_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


def test_prewarm_is_default_off() -> None:
    settings = Settings()

    assert settings.parser_latency_prewarm_enabled is False
    assert settings.parser_latency_prewarm_timeout_seconds == 300.0
    assert settings.parser_latency_prewarm_shutdown_grace_seconds == 2.0
    assert settings.parser_latency_prewarm_artifacts_sha256 is None
    assert settings.parser_latency_prewarm_dependency_sha256 is None


def test_single_flag_rollback_ignores_every_enabled_only_value(
    clean_prewarm_environment: pytest.MonkeyPatch,
) -> None:
    monkeypatch = clean_prewarm_environment
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv(
        "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
        "also-not-a-number",
    )
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256", "stale")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256", "stale")
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", "/missing/stale/prewarm-tree")
    monkeypatch.setenv("TESSERACT_CMD", "relative-predecessor-command")
    monkeypatch.setenv("TESSERACT_DATA_PATH", "relative/predecessor/data")

    settings = Settings.from_env()

    assert settings.parser_latency_prewarm_enabled is False
    assert settings.parser_latency_prewarm_timeout_seconds == 300.0
    assert settings.parser_latency_prewarm_shutdown_grace_seconds == 2.0
    assert settings.parser_latency_prewarm_artifacts_sha256 is None
    assert settings.parser_latency_prewarm_dependency_sha256 is None
    assert settings.tesseract_cmd == "relative-predecessor-command"
    assert settings.tesseract_data_path == "relative/predecessor/data"


@pytest.mark.parametrize(
    ("missing_name", "message"),
    [
        ("DOCLING_ARTIFACTS_PATH", "requires DOCLING_ARTIFACTS_PATH"),
        (
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256",
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256 is required",
        ),
        (
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256",
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256 is required",
        ),
        ("TESSERACT_CMD", "requires an absolute.*TESSERACT_CMD"),
        ("TESSERACT_DATA_PATH", "requires an absolute.*TESSERACT_DATA_PATH"),
    ],
)
def test_enabled_prewarm_requires_explicit_local_identity_configuration(
    clean_prewarm_environment: pytest.MonkeyPatch,
    missing_name: str,
    message: str,
) -> None:
    monkeypatch = clean_prewarm_environment
    values = {
        "PARSER_LATENCY_PREWARM_ENABLED": "true",
        "DOCLING_ARTIFACTS_PATH": "/deployment/models",
        "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": "a" * 64,
        "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "b" * 64,
        "TESSERACT_CMD": "/runtime/tesseract",
        "TESSERACT_DATA_PATH": "/runtime/tessdata",
    }
    values.pop(missing_name)
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        (
            "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256",
            "f" * 63,
            "must be a lowercase SHA-256 digest",
        ),
        (
            "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256",
            "g" * 64,
            "must be a lowercase SHA-256 digest",
        ),
        (
            "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
            "0.9",
            "must be at least 1.0",
        ),
        (
            "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
            "901",
            "must be at most 900.0",
        ),
        (
            "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
            "0.09",
            "must be at least 0.1",
        ),
        (
            "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
            "31",
            "must be at most 30.0",
        ),
    ],
)
def test_enabled_prewarm_rejects_malformed_or_unbounded_auxiliary_values(
    clean_prewarm_environment: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch = clean_prewarm_environment
    values = {
        "PARSER_LATENCY_PREWARM_ENABLED": "true",
        "DOCLING_ARTIFACTS_PATH": "/deployment/models",
        "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256": "a" * 64,
        "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256": "b" * 64,
        "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS": "10",
        "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS": "1",
        "TESSERACT_CMD": "/runtime/tesseract",
        "TESSERACT_DATA_PATH": "/runtime/tessdata",
    }
    values[name] = value
    for environment_name, environment_value in values.items():
        monkeypatch.setenv(environment_name, environment_value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()


def test_enabled_prewarm_normalizes_environment_digests_and_retains_bounds(
    clean_prewarm_environment: pytest.MonkeyPatch,
) -> None:
    monkeypatch = clean_prewarm_environment
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "yes")
    monkeypatch.setenv("DOCLING_ARTIFACTS_PATH", "/deployment/models")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256", "A" * 64)
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256", "B" * 64)
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS", "0.5")
    monkeypatch.setenv("TESSERACT_CMD", "/runtime/tesseract")
    monkeypatch.setenv("TESSERACT_DATA_PATH", "/runtime/tessdata")

    settings = Settings.from_env()

    assert settings.parser_latency_prewarm_enabled is True
    assert settings.docling_artifacts_path == "/deployment/models"
    assert settings.parser_latency_prewarm_artifacts_sha256 == "a" * 64
    assert settings.parser_latency_prewarm_dependency_sha256 == "b" * 64
    assert settings.parser_latency_prewarm_timeout_seconds == 12.5
    assert settings.parser_latency_prewarm_shutdown_grace_seconds == 0.5


def test_pipeline_public_signature_is_additive_and_preserves_three_argument_calls() -> (
    None
):
    signature = inspect.signature(pipeline.parse_document)
    parameters = tuple(signature.parameters.values())

    assert tuple(parameter.name for parameter in parameters[:3]) == (
        "document_bytes",
        "filename",
        "settings",
    )
    assert all(
        parameter.kind
        is inspect.Parameter.POSITIONAL_OR_KEYWORD
        for parameter in parameters[:3]
    )
    assert parameters[3].name == "parser_worker"
    assert parameters[3].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters[3].default is None


def test_enabled_and_disabled_openapi_are_byte_equivalent_and_worker_free(
    clean_prewarm_environment: pytest.MonkeyPatch,
) -> None:
    monkeypatch = clean_prewarm_environment
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    disabled = create_app().openapi()
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "true")
    enabled = create_app().openapi()

    assert enabled == disabled
    encoded = json.dumps(enabled, sort_keys=True, separators=(",", ":"))
    assert "prewarm" not in encoded.casefold()
    response_503 = enabled["paths"]["/v1/parse"]["post"]["responses"]["503"]
    assert response_503["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_worker_unavailable_uses_the_existing_closed_error_schema() -> None:
    error = ExtractionEngineUnavailableError(
        details={"component": "parser_worker", "reason": "unavailable"}
    )
    encoded = error.response().model_dump(mode="json")

    assert ErrorResponse.model_validate(encoded).model_dump(mode="json") == encoded
    assert encoded == {
        "error": {
            "code": "extraction_engine_unavailable",
            "message": "The document extraction engine is unavailable.",
            "details": {
                "component": "parser_worker",
                "reason": "unavailable",
            },
        }
    }


def test_enabled_and_disabled_json_markdown_and_serializer_bytes_are_equal(
    clean_prewarm_environment: pytest.MonkeyPatch,
) -> None:
    monkeypatch = clean_prewarm_environment
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    payload: dict[str, Any] = {
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
                "items": [],
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
    calls: list[int] = []

    def parse(*args: object) -> dict[str, Any]:
        calls.append(len(args))
        return payload

    monkeypatch.setattr(api_module, "_parse_document", parse)
    monkeypatch.setattr(api_module, "_serialize_markdown", lambda _value: "# Stable\n")

    disabled_app = create_app()
    disabled_app.dependency_overrides[get_settings] = Settings
    with TestClient(disabled_app) as client:
        disabled_json = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", b"%PDF-1.7\n% control", "application/pdf")},
        )
        disabled_markdown = client.post(
            "/v1/parse?output_format=markdown",
            files={"file": ("sample.pdf", b"%PDF-1.7\n% control", "application/pdf")},
        )

    enabled_settings = Settings(
        docling_artifacts_path="/deployment/models",
        tesseract_cmd="/runtime/tesseract",
        tesseract_data_path="/runtime/tessdata",
        parser_latency_prewarm_enabled=True,
        parser_latency_prewarm_artifacts_sha256="a" * 64,
        parser_latency_prewarm_dependency_sha256="b" * 64,
    )
    enabled_app = create_app()
    enabled_app.dependency_overrides[get_settings] = lambda: enabled_settings
    enabled_app.state.parser_worker_runtime = object()
    with TestClient(enabled_app) as client:
        enabled_json = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", b"%PDF-1.7\n% control", "application/pdf")},
        )
        enabled_markdown = client.post(
            "/v1/parse?output_format=markdown",
            files={"file": ("sample.pdf", b"%PDF-1.7\n% control", "application/pdf")},
        )

    assert calls == [3, 3, 4, 4]
    assert enabled_json.status_code == disabled_json.status_code == 200
    assert enabled_json.content == disabled_json.content
    assert enabled_json.headers["content-type"] == disabled_json.headers["content-type"]
    assert enabled_markdown.status_code == disabled_markdown.status_code == 200
    assert enabled_markdown.content == disabled_markdown.content == b"# Stable\n"
    assert (
        enabled_markdown.headers["content-type"]
        == disabled_markdown.headers["content-type"]
        == "text/markdown; charset=utf-8"
    )
