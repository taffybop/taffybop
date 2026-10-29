from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings, parser_cors_origins
from app.main import create_app


def test_cors_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARSER_CORS_ALLOWED_ORIGINS", raising=False)
    with TestClient(create_app()) as client:
        response = client.options("/v1/parse", headers={
            "Origin": "https://taffybop.io",
            "Access-Control-Request-Method": "POST",
        })
        assert response.status_code == 405
        assert "access-control-allow-origin" not in response.headers
        assert parser_cors_origins() == ()


@pytest.mark.parametrize("origin", ["https://taffybop.io", "https://www.taffybop.io"])
def test_allowed_browser_upload_and_error_keep_json_contract(
    monkeypatch: pytest.MonkeyPatch,
    parsed_document: dict[str, Any],
    origin: str,
) -> None:
    monkeypatch.setenv(
        "PARSER_CORS_ALLOWED_ORIGINS", "https://taffybop.io,https://www.taffybop.io"
    )
    app = create_app()
    app.dependency_overrides[get_settings] = Settings
    monkeypatch.setattr(api_module, "_parse_document", lambda *_args: parsed_document)
    with TestClient(app) as client:
        preflight = client.options("/v1/parse", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,accept",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == origin
        assert preflight.headers["access-control-allow-methods"] == "POST"
        assert "access-control-allow-credentials" not in preflight.headers
        response = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", b"%PDF-1.7\n", "application/pdf")},
            headers={"Origin": origin},
        )
        assert response.status_code == 200
        assert response.json() == parsed_document
        assert response.headers["content-type"] == "application/json"
        assert response.headers["access-control-allow-origin"] == origin
        assert "Origin" in response.headers["vary"]
        assert "access-control-allow-credentials" not in response.headers
        invalid = client.post("/v1/parse", headers={"Origin": origin})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "request_validation_error"
        assert invalid.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", [
    "https://untrusted.example", "https://taffybop.io.evil.example",
    "http://taffybop.io", "https://taffybop.io:8443", "null",
])
def test_unlisted_browser_origins_get_no_cors_access(
    monkeypatch: pytest.MonkeyPatch, origin: str,
) -> None:
    monkeypatch.setenv("PARSER_CORS_ALLOWED_ORIGINS", "https://taffybop.io")
    with TestClient(create_app()) as client:
        preflight = client.options("/v1/parse", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
        })
        assert preflight.status_code == 400
        assert "access-control-allow-origin" not in preflight.headers
        # CORS controls browser access, not API authentication. Ordinary HTTP
        # requests remain reachable but receive no permission to read responses.
        response = client.post("/v1/parse", headers={"Origin": origin})
        assert response.status_code == 422
        assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(("method", "headers"), [("DELETE", "content-type"), ("POST", "authorization")])
def test_cors_does_not_enable_extra_methods_or_authentication_headers(
    monkeypatch: pytest.MonkeyPatch, method: str, headers: str,
) -> None:
    monkeypatch.setenv("PARSER_CORS_ALLOWED_ORIGINS", "https://taffybop.io")
    with TestClient(create_app()) as client:
        response = client.options("/v1/parse", headers={
            "Origin": "https://taffybop.io",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        })
        assert response.status_code == 400


@pytest.mark.parametrize("configured", [
    "*", "https://*.taffybop.io", "https://taffybop.io/path",
    "https://user:secret@taffybop.io", "https://taffybop.io?token=secret",
    "https://taffybop.io#fragment", "http://taffybop.io", "null",
    "https://taffybop.io,", "https://taffybop.io:65536", "https://taffybop.io:0",
])
def test_unsafe_or_malformed_cors_configuration_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, configured: str,
) -> None:
    monkeypatch.setenv("PARSER_CORS_ALLOWED_ORIGINS", configured)
    with pytest.raises(ValueError, match="PARSER_CORS_ALLOWED_ORIGINS") as error:
        create_app()
    assert "secret" not in str(error.value)


def test_cors_normalizes_exact_origins_and_allows_explicit_loopback_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "PARSER_CORS_ALLOWED_ORIGINS",
        "https://TAFFYBOP.io:443/,https://taffybop.io,http://127.0.0.1:3019,http://[::1]:3019",
    )
    assert parser_cors_origins() == (
        "https://taffybop.io", "http://127.0.0.1:3019", "http://[::1]:3019"
    )
