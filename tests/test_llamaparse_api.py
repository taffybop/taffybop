"""Offline HTTP contract tests; these do not measure LlamaParse accuracy."""

from __future__ import annotations

import asyncio
import io
import json
from email.parser import BytesParser
from email.policy import default

import httpx
import pypdfium2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import app.llamaparse_api as api
from app.services.llamaparse_client import EXPAND, LlamaParseClient


@pytest.fixture(autouse=True)
def isolated_provider_admission(monkeypatch, tmp_path):
    # Mocked outstanding jobs must never fence the actual local workspace.
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", "legacy_local")
    monkeypatch.setenv("TAFFYBOP_PROVIDER_LOCK_PATH", str(tmp_path / "admission/provider.lock"))


def pdf_bytes(pages: int = 1) -> bytes:
    document = pypdfium2.PdfDocument.new()
    try:
        for _ in range(pages):
            page = document.new_page(200, 200)
            page.close()
        output = io.BytesIO()
        document.save(output)
        return output.getvalue()
    finally:
        document.close()


def image_bytes(image_format: str = "PNG", size: tuple[int, int] = (8, 6)) -> bytes:
    output = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        image.save(output, format=image_format)
    return output.getvalue()


def application(handler, *, key: str = "test-key-not-real", **service_options):
    app = FastAPI()
    transport = httpx.MockTransport(handler)
    app.state.llamaparse_service = api.LlamaParseService(LlamaParseClient(key_provider=lambda: key, transport=transport), **service_options)
    app.include_router(api.router)
    return app


def submit(client, *, mode="cost_effective", data=None, filename="sample.pdf", media_type="application/pdf"):
    return client.post("/v1/llamaparse/jobs", files={"file": (filename, pdf_bytes() if data is None else data, media_type)}, data={"mode": mode})


def assert_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert set(response.json()["error"]) == {"code", "message"}
    assert response.headers["cache-control"] == "no-store"


def test_config_never_exposes_key_and_reports_exact_modes():
    def unexpected(_request):
        pytest.fail("Configuration must not call LlamaCloud")

    with TestClient(application(unexpected, key="private-test-secret")) as client:
        response = client.get("/v1/llamaparse/config")
    assert response.status_code == 200
    assert "private-test-secret" not in response.text
    value = response.json()
    assert value["configured"] is True
    assert [(mode["id"], mode["label"], mode["credits_per_page"]) for mode in value["modes"]] == [
        ("cost_effective", "Cost Effective", 3), ("agentic", "Agentic", 10), ("agentic_plus", "Agentic Plus", 45),
    ]
    assert value["default_mode"] == "cost_effective"
    assert value["max_upload_bytes"] == 10 * 1024 * 1024
    assert value["max_pages"] == 10


@pytest.mark.parametrize(("mode", "credits"), [("cost_effective", 3), ("agentic", 10), ("agentic_plus", 45)])
def test_create_exact_tier_single_combined_upload_and_opaque_id(mode, credits):
    calls = []
    source = pdf_bytes(2)

    async def handler(request):
        calls.append(request)
        assert str(request.url) == "https://api.cloud.llamaindex.ai/api/v2/parse/upload"
        assert request.headers["authorization"] == "Bearer test-key-not-real"
        body = await request.aread()
        message = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + body)
        parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
        assert json.loads(parts["configuration"].get_payload(decode=True)) == {"tier": mode, "version": "latest", "page_ranges": {"max_pages": 10}}
        assert parts["file"].get_payload(decode=True) == source
        assert parts["file"].get_filename() == "sample.pdf"
        return httpx.Response(200, json={"id": "pjb-provider-id", "status": "PENDING"})

    with TestClient(application(handler)) as client:
        response = submit(client, mode=mode, data=source, filename="../sample.pdf")
    assert response.status_code == 202
    value = response.json()
    assert value["mode"] == mode
    assert value["status"] == "PENDING"
    assert value["estimated_credits"] == 2 * credits
    assert value["page_count"] == 2
    assert value["job_id"] != "pjb-provider-id"
    assert len(value["job_id"]) >= 32
    assert len(calls) == 1


@pytest.mark.parametrize(("image_format", "filename", "media_type"), [("PNG", "image.png", "image/png"), ("JPEG", "image.jpeg", "image/jpeg")])
def test_valid_image_is_one_page(image_format, filename, media_type):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "pjb-image", "status": "RUNNING"})

    with TestClient(application(handler)) as client:
        response = submit(client, data=image_bytes(image_format), filename=filename, media_type=media_type)
    assert response.status_code == 202
    assert response.json()["page_count"] == 1
    assert response.json()["estimated_credits"] == 3
    assert len(calls) == 1


@pytest.mark.parametrize(("kwargs", "status", "code"), [
    ({"mode": "fast"}, 400, "invalid_mode"),
    ({"data": b""}, 422, "empty_file"),
    ({"data": b"hello"}, 400, "unsupported_file"),
    ({"data": b"%PDF-1.7\ncorrupt"}, 422, "invalid_pdf"),
    ({"data": b"\x89PNG\r\n\x1a\ncorrupt", "filename": "bad.png", "media_type": "image/png"}, 422, "invalid_image"),
    ({"filename": "sample.exe"}, 422, "file_type_mismatch"),
    ({"media_type": "image/png"}, 422, "file_type_mismatch"),
])
def test_invalid_input_has_no_provider_calls(kwargs, status, code):
    def unexpected(_request):
        pytest.fail("Invalid input must not incur a provider call")

    with TestClient(application(unexpected)) as client:
        response = submit(client, **kwargs)
    assert_error(response, status, code)


def test_pdf_page_limit_before_provider_call():
    def unexpected(_request):
        pytest.fail("Too many pages must not reach provider")

    with TestClient(application(unexpected)) as client:
        response = submit(client, data=pdf_bytes(11))
    assert_error(response, 413, "too_many_pages")


def test_file_byte_limit_before_provider_call(monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 50)
    with TestClient(application(lambda _request: pytest.fail("Oversized file reached provider"))) as client:
        response = submit(client)
    assert_error(response, 413, "upload_too_large")


def test_image_pixel_limit_before_decode_and_provider_call(monkeypatch):
    monkeypatch.setattr(api, "MAX_IMAGE_PIXELS", 40)
    with TestClient(application(lambda _request: pytest.fail("Oversized image reached provider"))) as client:
        response = submit(client, data=image_bytes(), filename="photo.png", media_type="image/png")
    assert_error(response, 413, "image_too_large")


def test_missing_key_is_503_without_provider_call():
    with TestClient(application(lambda _request: pytest.fail("Unconfigured provider called"), key="")) as client:
        assert client.get("/v1/llamaparse/config").json()["configured"] is False
        response = submit(client)
    assert_error(response, 503, "provider_not_configured")


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_poll_preserves_exact_json_bytes_and_real_job_status(status):
    raw = ('{\n "job": {"id":"pjb-result", "status":"' + status + '", "usage":{"credits":null}},\n "markdown":{"pages":[{"page_number":1,"markdown":"é\\n|a|b|"}]}, "text":{"pages":[{"text":"é"}]}, "extra": [1,2] }\n').encode()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "pjb-result", "status": "PENDING"})
        assert request.url.params["expand"] == EXPAND
        assert request.url.path == "/api/v2/parse/pjb-result"
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    with TestClient(application(handler)) as client:
        token = submit(client).json()["job_id"]
        response = client.get("/v1/llamaparse/jobs/" + token)
    assert response.status_code == 200
    assert response.content == raw
    assert response.json()["job"]["status"] == status
    assert response.json()["job"]["usage"]["credits"] is None
    assert len(calls) == 2


@pytest.mark.parametrize("value", [
    {"status": "COMPLETED"},
    {"job": {"id": "pjb-result", "status": "SUCCESS"}},
    {"job": {"id": "somebody-elses-job", "status": "RUNNING"}},
])
def test_invalid_poll_shape_is_502_not_fabricated_success(value):
    def handler(request):
        return httpx.Response(200, json={"id": "pjb-result", "status": "PENDING"} if request.method == "POST" else value)

    with TestClient(application(handler)) as client:
        token = submit(client).json()["job_id"]
        response = client.get("/v1/llamaparse/jobs/" + token)
    assert_error(response, 502, "provider_invalid_response")


@pytest.mark.parametrize("optional", [{}, {"markdown": None}, {"markdown": {"pages": [{"markdown": 5}]}, "text": "unrecognized optional output"}])
def test_completed_optional_outputs_remain_available_as_raw_json(optional):
    raw = json.dumps({"job": {"id": "pjb-result", "status": "COMPLETED"}, **optional}, indent=2).encode()

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "pjb-result", "status": "PENDING"})
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    with TestClient(application(handler)) as client:
        token = submit(client).json()["job_id"]
        response = client.get("/v1/llamaparse/jobs/" + token)
    assert response.status_code == 200
    assert response.content == raw


def test_failed_provider_job_without_output_remains_failed_raw_response():
    raw = b'{"job":{"id":"pjb-result","status":"FAILED","error_message":"Unable to parse"}}'

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "pjb-result", "status": "PENDING"})
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    with TestClient(application(handler)) as client:
        token = submit(client).json()["job_id"]
        response = client.get("/v1/llamaparse/jobs/" + token)
    assert response.content == raw
    assert response.json()["job"]["status"] == "FAILED"


@pytest.mark.parametrize(("upstream", "status", "code"), [(402, 402, "provider_credits_exhausted"), (429, 429, "provider_rate_limited"), (401, 503, "provider_authentication_failed"), (403, 503, "provider_authentication_failed"), (422, 502, "provider_rejected_request"), (500, 502, "provider_unavailable"), (302, 502, "provider_unavailable")])
def test_provider_errors_sanitized_without_retry(upstream, status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(upstream, text="private-test-secret and customer document", headers={"location": "https://another-host.invalid"})

    with TestClient(application(handler)) as client:
        response = submit(client)
    assert_error(response, status, code)
    assert "private-test-secret" not in response.text
    assert "customer document" not in response.text
    assert len(calls) == 1


def test_provider_timeout_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret upstream details", request=request)

    with TestClient(application(handler)) as client:
        response = submit(client)
    assert_error(response, 504, "provider_timeout")
    assert "secret upstream details" not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"id":"../../escape","status":"PENDING"}', b'{"id":"pjb-id","status":"NEW"}'])
def test_invalid_create_shape_fails_without_retry(payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=payload, headers={"content-type": "application/json"})

    with TestClient(application(handler)) as client:
        response = submit(client)
    assert_error(response, 502, "provider_invalid_response")
    assert len(calls) == 1


def test_unknown_and_expired_jobs_are_not_forwarded():
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "pjb-id", "status": "PENDING"})

    with TestClient(application(handler, clock=lambda: now[0], ttl_seconds=10)) as client:
        assert_error(client.get("/v1/llamaparse/jobs/pjb-any-provider-job"), 404, "job_not_found")
        token = submit(client).json()["job_id"]
        now[0] = 10
        assert_error(client.get("/v1/llamaparse/jobs/" + token), 404, "job_not_found")
    assert len(calls) == 1


def test_registry_full_rejects_before_billable_create_and_recovers_after_expiry():
    calls = []
    now = [0.0]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "pjb-id", "status": "PENDING"})

    with TestClient(application(handler, max_jobs=1, ttl_seconds=10, clock=lambda: now[0])) as client:
        assert submit(client).status_code == 202
        assert_error(submit(client), 503, "job_capacity_reached")
        assert len(calls) == 1
        now[0] = 11
        assert submit(client).status_code == 202
    assert len(calls) == 2


def test_submission_admission_rejects_concurrent_call_and_releases_after_error():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def handler(request):
            calls.append(request)
            if len(calls) == 1:
                started.set()
                await release.wait()
                return httpx.Response(500, text="private")
            return httpx.Response(200, json={"id": "pjb-id", "status": "PENDING"})

        app = application(handler)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            async def post():
                return await client.post("/v1/llamaparse/jobs", files={"file": ("x.png", image_bytes(), "image/png")}, data={"mode": "cost_effective"})

            first = asyncio.create_task(post())
            await asyncio.wait_for(started.wait(), 2)
            assert_error(await post(), 429, "submission_busy")
            release.set()
            assert_error(await first, 502, "provider_unavailable")
            assert (await post()).status_code == 202
            assert len(calls) == 2

    asyncio.run(run())


def test_chunked_body_cap_before_spooling_and_releases_admission(monkeypatch):
    monkeypatch.setattr(api, "MAX_BODY_BYTES", 256)

    async def run():
        app = application(lambda _request: pytest.fail("Invalid stream reached provider"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            async def chunks():
                yield b'--abc\r\nContent-Disposition: form-data; name="file"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'
                yield b"b" * 256

            # Correct multipart header ensures the parser actually consumes the
            # body; each receive is bounded even without Content-Length.
            response = await client.post("/v1/llamaparse/jobs", content=chunks(), headers={"content-type": "multipart/form-data; boundary=abc"})
            assert_error(response, 413, "upload_too_large")
            assert app.state.llamaparse_service.submission.acquire(blocking=False)
            app.state.llamaparse_service.submission.release()

    asyncio.run(run())


def test_cancelled_upload_closes_spools_and_releases_admission(monkeypatch):
    import starlette.formparsers as formparsers

    spools = []
    original = formparsers.SpooledTemporaryFile

    def tracked_spool(*args, **kwargs):
        spool = original(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", tracked_spool)

    async def run():
        started = asyncio.Event()
        app = application(lambda _request: pytest.fail("Cancelled upload reached provider"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            async def chunks():
                yield b'--abc\r\nContent-Disposition: form-data; name="file"; filename="x.png"\r\nContent-Type: image/png\r\n\r\npixels'
                started.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(client.post("/v1/llamaparse/jobs", content=chunks(), headers={"content-type": "multipart/form-data; boundary=abc"}))
            await asyncio.wait_for(started.wait(), 2)
            assert len(spools) == 1 and not spools[0].closed
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert spools[0].closed
            assert app.state.llamaparse_service.submission.acquire(blocking=False)
            app.state.llamaparse_service.submission.release()

    asyncio.run(run())


def test_absolute_upload_deadline_returns_408_and_releases_admission(monkeypatch):
    monkeypatch.setattr(api, "UPLOAD_TIMEOUT_SECONDS", 0.01)

    async def run():
        app = application(lambda _request: pytest.fail("Timed-out upload reached provider"))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            async def chunks():
                yield b'--abc\r\nContent-Disposition: form-data; name="file"; filename="x.png"\r\nContent-Type: image/png\r\n\r\npixels'
                await asyncio.sleep(0.03)
                yield b"more"

            response = await client.post("/v1/llamaparse/jobs", content=chunks(), headers={"content-type": "multipart/form-data; boundary=abc"})
            assert_error(response, 408, "upload_timeout")
            assert app.state.llamaparse_service.submission.acquire(blocking=False)
            app.state.llamaparse_service.submission.release()

    asyncio.run(run())


def test_malformed_multipart_is_sanitized_400():
    with TestClient(application(lambda _request: pytest.fail("Malformed upload reached provider"))) as client:
        response = client.post("/v1/llamaparse/jobs", content=b"not multipart", headers={"content-type": "multipart/form-data; boundary=abc"})
    assert_error(response, 400, "invalid_upload")


def test_provider_response_size_is_bounded():
    app = application(lambda _request: httpx.Response(200, content=b" " * 51, headers={"content-type": "application/json"}))
    app.state.llamaparse_service.client._max_response_bytes = 50
    with TestClient(app) as client:
        response = submit(client)
    assert_error(response, 502, "provider_response_too_large")
