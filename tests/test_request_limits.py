from __future__ import annotations

import asyncio
from contextlib import suppress
from threading import Event
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import starlette.formparsers as formparsers

import app.api as api_module
from app.config import MEBIBYTE, Settings, get_settings, parser_public_resource_limits
from app.main import create_app
from app.request_limits import ParserRequestLimitsMiddleware


ORIGIN = "https://taffybop.io"
PREFIX = (
    b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="sample.pdf"\r\n'
    b"Content-Type: application/pdf\r\n\r\n"
)
SUFFIX = b"\r\n--boundary--\r\n"
BODY = PREFIX + b"%PDF-1.7\n" + SUFFIX
HEADERS = {"Content-Type": "multipart/form-data; boundary=boundary", "Origin": ORIGIN}


def _app(
    monkeypatch: pytest.MonkeyPatch,
    parsed_document: dict[str, Any],
    *,
    body_limit: int = 4096,
) -> FastAPI:
    monkeypatch.setenv("PARSER_MAX_REQUEST_BODY_BYTES", str(body_limit))
    monkeypatch.setenv("PARSER_MAX_CONCURRENT_PARSE_REQUESTS", "1")
    monkeypatch.setenv("PARSER_CORS_ALLOWED_ORIGINS", ORIGIN)
    app = create_app()
    app.dependency_overrides[get_settings] = Settings
    monkeypatch.setattr(api_module, "_parse_document", lambda *_args: parsed_document)
    return app


def _limits(app: FastAPI) -> ParserRequestLimitsMiddleware:
    middleware = app.middleware_stack
    while not isinstance(middleware, ParserRequestLimitsMiddleware):
        middleware = middleware.app
    return middleware


def _track_spools(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    opened = []
    original = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        value = original(*args, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)
    return opened


def test_public_limits_default_to_one_request_and_one_mib_multipart_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ["MAX_UPLOAD_BYTES", "PARSER_MAX_REQUEST_BODY_BYTES", "PARSER_MAX_CONCURRENT_PARSE_REQUESTS", "PARSER_UPLOAD_TIMEOUT_SECONDS"]:
        monkeypatch.delenv(name, raising=False)
    assert parser_public_resource_limits() == (21 * MEBIBYTE, 1, 60.0)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    assert parser_public_resource_limits() == (MEBIBYTE + 1024, 1, 60.0)
    monkeypatch.setenv("PARSER_MAX_REQUEST_BODY_BYTES", "2048")
    monkeypatch.setenv("PARSER_MAX_CONCURRENT_PARSE_REQUESTS", "2")
    assert parser_public_resource_limits() == (2048, 2, 60.0)


@pytest.mark.parametrize("name", ["PARSER_MAX_REQUEST_BODY_BYTES", "PARSER_MAX_CONCURRENT_PARSE_REQUESTS", "PARSER_UPLOAD_TIMEOUT_SECONDS"])
def test_zero_resource_limits_cannot_silently_disable_protection(
    monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError, match=name):
        create_app()


def test_declared_oversize_is_rejected_before_reading_or_spooling(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    app = _app(monkeypatch, parsed_document, body_limit=128)
    consumed = False

    async def scenario() -> None:
        async def body():
            nonlocal consumed
            consumed = True
            yield b"unread upload"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/parse", content=body(), headers={**HEADERS, "Content-Length": "129"})
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "upload_too_large"
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert response.json()["error"]["details"]["max_request_body_bytes"] == 128
            assert consumed is False

    asyncio.run(scenario())


@pytest.mark.parametrize("declared_length", [None, "1"])
def test_streamed_body_cap_counts_actual_bytes_and_closes_spooled_files(
    monkeypatch: pytest.MonkeyPatch,
    parsed_document: dict[str, Any],
    declared_length: str | None,
) -> None:
    app = _app(monkeypatch, parsed_document, body_limit=256)
    opened = []
    original_spool = formparsers.SpooledTemporaryFile
    parsed = []

    def spool(*args, **kwargs):
        value = original_spool(*args, **kwargs)
        opened.append(value)
        return value

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)
    monkeypatch.setattr(api_module, "_parse_document", lambda *_args: parsed.append(True) or parsed_document)

    async def scenario() -> None:
        async def chunks():
            yield PREFIX + b"%PDF-1.7\n"
            yield b"x" * 256
            pytest.fail("An oversized body must not be drained into the multipart parser.")

        headers = dict(HEADERS)
        if declared_length is not None:
            headers["Content-Length"] = declared_length
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/parse", content=chunks(), headers=headers)
            assert response.status_code == 413
            assert response.json()["error"]["code"] == "upload_too_large"
            assert response.headers["content-type"] == "application/json"
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert parsed == []
            assert opened and all(value.closed for value in opened)
            # Streaming rejection released admission for the next valid request.
            assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 200

    asyncio.run(scenario())


def test_exact_total_body_boundary_is_accepted(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    app = _app(monkeypatch, parsed_document, body_limit=len(BODY))
    with TestClient(app) as client:
        response = client.post("/v1/parse", content=BODY, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == parsed_document


def test_admission_covers_upload_and_processing_and_survives_processing_cancellation(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    app = _app(monkeypatch, parsed_document)
    parsing_started = Event()
    finish_parsing = Event()
    calls = []

    def parse(*_args):
        calls.append(True)
        parsing_started.set()
        assert finish_parsing.wait(5), "Test did not release its parser stub."
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)

    async def scenario() -> None:
        upload_started = asyncio.Event()
        finish_upload = asyncio.Event()

        async def chunks():
            yield PREFIX + b"%PDF-1.7\n"
            upload_started.set()
            await finish_upload.wait()
            yield SUFFIX

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/v1/parse", content=chunks(), headers=HEADERS))
            try:
                await asyncio.wait_for(upload_started.wait(), 2)
                busy = await asyncio.wait_for(client.post("/v1/parse", content=BODY, headers=HEADERS), 2)
                assert busy.status_code == 429
                assert busy.json()["error"]["code"] == "parser_busy"
                assert busy.headers["retry-after"] == "5"
                assert busy.headers["access-control-allow-origin"] == ORIGIN
                assert calls == []
                assert (await client.get("/healthz")).status_code == 200
                finish_upload.set()
                assert await asyncio.to_thread(parsing_started.wait, 2)
                assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 429

                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
                # The cancelled client did not stop its native parser thread.
                # Its slot must remain occupied until that thread completes.
                assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 429
                assert len(calls) == 1
                finish_parsing.set()
                await asyncio.wait_for(asyncio.gather(*tuple(_limits(app)._in_flight)), 2)
                assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 200
                assert len(calls) == 2
            finally:
                finish_upload.set()
                finish_parsing.set()
                first.cancel()
                with suppress(asyncio.CancelledError):
                    await first

    asyncio.run(scenario())


def test_cancelling_incomplete_upload_releases_admission(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    app = _app(monkeypatch, parsed_document, body_limit=2 * MEBIBYTE)
    opened = _track_spools(monkeypatch)

    async def scenario() -> None:
        waiting = asyncio.Event()
        never_finish = asyncio.Event()

        async def chunks():
            yield PREFIX + b"%PDF-1.7\n" + b"x" * MEBIBYTE
            waiting.set()
            await never_finish.wait()
            yield SUFFIX

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            first = asyncio.create_task(client.post("/v1/parse", content=chunks(), headers=HEADERS))
            await asyncio.wait_for(waiting.wait(), 2)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert opened and opened[0]._rolled is True
            assert all(spool.closed for spool in opened)
            assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("disconnected", [False, True])
def test_truncated_and_disconnected_uploads_close_partial_disk_spools(
    monkeypatch: pytest.MonkeyPatch,
    parsed_document: dict[str, Any],
    disconnected: bool,
) -> None:
    app = _app(monkeypatch, parsed_document, body_limit=2 * MEBIBYTE)
    opened = _track_spools(monkeypatch)

    async def scenario() -> None:
        messages = [
            {"type": "http.request", "body": PREFIX + b"%PDF-1.7\n" + b"x" * MEBIBYTE, "more_body": disconnected},
            {"type": "http.disconnect"},
        ]
        sent = []

        async def receive():
            return messages.pop(0)

        async def send(message):
            sent.append(message)

        await app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/v1/parse",
            "raw_path": b"/v1/parse", "query_string": b"", "root_path": "",
            "headers": [(key.lower().encode(), value.encode()) for key, value in HEADERS.items()],
            "client": ("127.0.0.1", 1234), "server": ("test", 80),
        }, receive, send)
        assert sent[0]["status"] == (400 if disconnected else 422)
        assert opened and opened[0]._rolled is True
        assert all(spool.closed for spool in opened)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 200

    asyncio.run(scenario())


def test_absolute_upload_deadline_rejects_trickle_and_closes_spools(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    monkeypatch.setenv("PARSER_UPLOAD_TIMEOUT_SECONDS", "0.08")
    app = _app(monkeypatch, parsed_document, body_limit=2 * MEBIBYTE)
    opened = _track_spools(monkeypatch)

    async def scenario() -> None:
        async def trickle():
            yield PREFIX + b"%PDF-1.7\n" + b"x" * MEBIBYTE
            # Every gap is shorter than the timeout, but the complete upload
            # exceeds it. An idle-only timer would incorrectly accept this.
            for _ in range(5):
                await asyncio.sleep(0.03)
                yield b"x"
            yield SUFFIX

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/parse", content=trickle(), headers=HEADERS)
            assert response.status_code == 408
            assert response.json()["error"]["code"] == "upload_timeout"
            assert response.json()["error"]["details"]["upload_timeout_seconds"] == 0.08
            assert response.headers["access-control-allow-origin"] == ORIGIN
            assert opened and opened[0]._rolled is True
            assert all(spool.closed for spool in opened)
            assert (await client.post("/v1/parse", content=BODY, headers=HEADERS)).status_code == 200

    asyncio.run(scenario())


def test_validation_and_parser_errors_release_admission(
    monkeypatch: pytest.MonkeyPatch, parsed_document: dict[str, Any],
) -> None:
    app = _app(monkeypatch, parsed_document)

    def broken(*_args):
        raise RuntimeError("synthetic parser failure")

    with TestClient(app) as client:
        assert client.post("/v1/parse", headers={"Origin": ORIGIN}).status_code == 422
        monkeypatch.setattr(api_module, "_parse_document", broken)
        failed = client.post("/v1/parse", content=BODY, headers=HEADERS)
        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "document_processing_failed"
        assert failed.headers["access-control-allow-origin"] == ORIGIN
        monkeypatch.setattr(api_module, "_parse_document", lambda *_args: parsed_document)
        assert client.post("/v1/parse", content=BODY, headers=HEADERS).status_code == 200
