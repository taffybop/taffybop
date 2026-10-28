from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture()
def ui_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist-static"
    files = {
        "index.html": "<h1>Home</h1>",
        "studio/index.html": "<h1>Studio</h1>",
        "knowledge/index.html": "<h1>Knowledge</h1>",
        "privacy/index.html": "<h1>Privacy</h1>",
        "parse/index.html": "<a href='/studio'>Parse redirect</a>",
        "extract/index.html": "<a href='/studio'>Extract redirect</a>",
        "assets/index-aB12_C34.js": "console.log('public bundle');",
        "assets/index-aB12_C34.css": "body { color: black; }",
        "pdf.worker.min.mjs": "export const worker = true;",
        "icon.svg": "<svg />",
        "og-knowledge.svg": "<svg />",
        "robots.txt": "User-agent: *\nAllow: /\n",
        "samples/customer-support-handbook.pdf": "%PDF-1.7\npublic sample",
        ".env": "PRIVATE_ENV_SENTINEL",
        "app/main.py": "PRIVATE_SOURCE_SENTINEL",
        "assets/.env": "PRIVATE_ASSET_SENTINEL",
        "assets/debug.js": "PRIVATE_UNHASHED_SENTINEL",
        "assets/index-aB12_C34.js.map": "PRIVATE_SOURCE_MAP_SENTINEL",
        "samples/private.pdf": "PRIVATE_DOCUMENT_SENTINEL",
        "studio/private.txt": "PRIVATE_NESTED_SENTINEL",
        "404.html": "PRIVATE_FALLBACK_SENTINEL",
    }
    for relative_path, content in files.items():
        destination = dist / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    monkeypatch.setenv("PARSER_UI_DIST_PATH", str(dist))
    return dist


def test_default_is_backend_only_with_process_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PARSER_UI_DIST_PATH", raising=False)
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "check": "process"}
        assert client.get("/").status_code == 404
        assert client.get("/studio").status_code == 404
        assert "/v1/parse" in client.get("/openapi.json").json()["paths"]


def test_only_public_routes_and_hashed_assets_are_served(ui_dist: Path) -> None:
    expected = {
        "/": ("index.html", "text/html"),
        "/studio": ("studio/index.html", "text/html"),
        "/knowledge": ("knowledge/index.html", "text/html"),
        "/privacy": ("privacy/index.html", "text/html"),
        "/parse": ("parse/index.html", "text/html"),
        "/extract": ("extract/index.html", "text/html"),
        "/assets/index-aB12_C34.js": ("assets/index-aB12_C34.js", "text/javascript"),
        "/assets/index-aB12_C34.css": ("assets/index-aB12_C34.css", "text/css"),
        "/pdf.worker.min.mjs": ("pdf.worker.min.mjs", "text/javascript"),
        "/icon.svg": ("icon.svg", "image/svg+xml"),
        "/og-knowledge.svg": ("og-knowledge.svg", "image/svg+xml"),
        "/robots.txt": ("robots.txt", "text/plain"),
        "/samples/customer-support-handbook.pdf": (
            "samples/customer-support-handbook.pdf", "application/pdf"
        ),
    }
    with TestClient(create_app()) as client:
        for url, (filename, content_type) in expected.items():
            response = client.get(url)
            assert response.status_code == 200, url
            assert response.content == (ui_dist / filename).read_bytes()
            assert response.headers["content-type"].startswith(content_type)
            assert response.headers["x-content-type-options"] == "nosniff"
        assert client.head("/studio").content == b""
        assert client.head("/studio").status_code == 200
        assert client.get("/studio").headers["cache-control"] == "no-cache"
        assert "immutable" in client.get("/assets/index-aB12_C34.js").headers["cache-control"]


@pytest.mark.parametrize("url", [
    "/.env", "/app/main.py", "/assets/.env", "/assets/debug.js",
    "/assets/index-aB12_C34.js.map", "/samples/private.pdf",
    "/studio/private.txt", "/404.html", "/index.html", "/unknown",
    "/v1/unknown", "/assets/%2e%2e/.env", "/%2e%2e/app/main.py",
    "/assets/%252e%252e/.env", "/assets/index-aB12_C34.js%00.env",
    "/assets/..%5c.env", "/assets/", "/samples/",
])
def test_private_unknown_and_traversal_paths_stay_json_404(
    ui_dist: Path, url: str,
) -> None:
    with TestClient(create_app()) as client:
        response = client.get(url)
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
        assert response.json() == {"detail": "Not Found"}


def test_ui_does_not_change_api_success_or_error_responses(
    ui_dist: Path,
    parsed_document: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = Settings
    calls = []

    def parse(data: bytes, filename: str, settings: Settings) -> dict[str, Any]:
        calls.append((data, filename, settings))
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)
    with TestClient(app) as client:
        response = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", b"%PDF-1.7\n", "application/pdf")},
        )
        assert response.status_code == 200
        assert response.json() == parsed_document
        assert len(calls) == 1
        assert calls[0][:2] == (b"%PDF-1.7\n", "sample.pdf")
        assert isinstance(calls[0][2], Settings)
        invalid = client.post("/v1/parse?output_format=json")
        assert invalid.status_code == 422
        assert invalid.headers["content-type"] == "application/json"
        assert invalid.json()["error"]["code"] == "request_validation_error"
        assert client.get("/v1/parse").status_code == 405
        assert client.get("/healthz").json() == {"status": "ok", "check": "process"}


def test_symlink_files_and_directories_are_never_public(
    ui_dist: Path, tmp_path: Path,
) -> None:
    private = tmp_path / "private.txt"
    private.write_text("PRIVATE_SYMLINK_SENTINEL")
    (ui_dist / "icon.svg").unlink()
    (ui_dist / "icon.svg").symlink_to(private)
    (ui_dist / "assets/escape-aB12_C34.js").symlink_to(private)
    (ui_dist / "knowledge/index.html").unlink()
    (ui_dist / "knowledge").rmdir()
    (ui_dist / "knowledge").symlink_to(tmp_path, target_is_directory=True)
    (tmp_path / "index.html").write_text("PRIVATE_DIRECTORY_SENTINEL")
    with TestClient(create_app()) as client:
        for url in ["/icon.svg", "/assets/escape-aB12_C34.js", "/knowledge"]:
            assert client.get(url).status_code == 404
        assert client.get("/studio").status_code == 200


def test_assets_directory_symlink_is_not_exposed(ui_dist: Path, tmp_path: Path) -> None:
    assets = ui_dist / "assets"
    assets.rename(tmp_path / "outside-assets")
    assets.symlink_to(tmp_path / "outside-assets", target_is_directory=True)
    with TestClient(create_app()) as client:
        assert client.get("/assets/index-aB12_C34.js").status_code == 404


def test_configured_root_symlink_is_rejected(
    ui_dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = tmp_path / "linked-dist"
    linked.symlink_to(ui_dist, target_is_directory=True)
    monkeypatch.setenv("PARSER_UI_DIST_PATH", str(linked))
    with pytest.raises(RuntimeError, match="without symlinks"):
        create_app()


def test_configured_root_ancestor_symlink_is_rejected(
    ui_dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked = tmp_path / "linked-parent"
    linked.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("PARSER_UI_DIST_PATH", str(linked / ui_dist.name))
    with pytest.raises(RuntimeError, match="without symlinks"):
        create_app()


def test_symlink_swap_after_startup_cannot_expose_private_file(
    ui_dist: Path, tmp_path: Path,
) -> None:
    with TestClient(create_app()) as client:
        expected = client.get("/studio").content
        private = tmp_path / "private.txt"
        private.write_text("PRIVATE_REPLACEMENT_SENTINEL")
        page = ui_dist / "studio/index.html"
        page.unlink()
        page.symlink_to(private)
        assert client.get("/studio").content == expected


def test_missing_public_route_does_not_fall_back_to_home(ui_dist: Path) -> None:
    (ui_dist / "knowledge/index.html").unlink()
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/knowledge").status_code == 404


def test_invalid_configured_build_fails_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_UI_DIST_PATH", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="existing directory"):
        create_app()
    monkeypatch.setenv("PARSER_UI_DIST_PATH", str(tmp_path))
    with pytest.raises(RuntimeError, match="regular index.html"):
        create_app()
