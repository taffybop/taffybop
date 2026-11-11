"""Owned HTTP/library checks. All worker observations are authored simulations.

Each database test owns an isolated temporary PostgreSQL database. No provider
network call or credential is needed, and existing retained databases are not
modified. Run with TAFFYBOP_TEST_DATABASE_URL set to the task admin socket DSN.
"""

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
import httpx
import pytest
from starlette.testclient import TestClient

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.product.allowance import TestAllowance, register_allowance
from app.product.api import ProductAPIService, configure_product_api
from app.product.contracts import Page, PageSection, ParseSettings
from app.product.database import Database, MigrationError
from app.product.lifecycle import WorkerRepository
from app.product.local_identity import LocalConfigurationError, LocalIdentity, load_local_configuration
from app.product.provider import ProviderObservation


FIXTURES = Path(__file__).parent / "fixtures/parse_extract_v1"
PDF = (FIXTURES / "dev-invoice-104.pdf").read_bytes()
SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28")
HOSTED_MARKERS = ("RENDER", "RENDER_SERVICE_ID", "DYNO", "K_SERVICE", "AWS_LAMBDA_FUNCTION_NAME", "WEBSITE_INSTANCE_ID", "CF_PAGES")


def environment(root="/private/tmp/px1-api-test", **changes):
    values = {"TAFFYBOP_PRODUCT_MODE": "local_development", "TAFFYBOP_DEPLOYMENT": "local",
              "TAFFYBOP_RUNTIME_PROFILE": "product_worker_local", "TAFFYBOP_LOCAL_OWNER": "local-api-owner",
              "TAFFYBOP_DATABASE_URL": "private-test-dsn", "TAFFYBOP_ARTIFACT_ROOT": root}
    values.update(changes)
    return values


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    administrative_dsn = os.environ.get("TAFFYBOP_TEST_DATABASE_URL")
    if not administrative_dsn:
        pytest.skip("real PostgreSQL: TAFFYBOP_TEST_DATABASE_URL is not configured")
    name = "px1_api_test_" + uuid4().hex
    with psycopg.connect(administrative_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        database = Database(make_conninfo(administrative_dsn, dbname=name))
        database.migrate()
        for key in HOSTED_MARKERS:
            monkeypatch.delenv(key, raising=False)
        for key, value in environment(str((tmp_path / "artifacts").resolve()), TAFFYBOP_DATABASE_URL=database._dsn).items():
            monkeypatch.setenv(key, value)
        app = FastAPI()
        configure_product_api(app)
        # Any accidental live HTTP dispatch makes these checks fail immediately.
        async def no_provider_http(*args, **kwargs):
            raise AssertionError("Provider HTTP transport must not be called")
        monkeypatch.setattr(httpx.AsyncClient, "send", no_provider_http)
        service = app.state.product_api_service
        with TestClient(app, base_url="http://127.0.0.1:8043", client=("127.0.0.1", 50001)) as client:
            yield SimpleNamespace(app=app, client=client, repo=service.repository,
                                  owner=service.identity.owner, database=database)
    finally:
        with psycopg.connect(administrative_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def upload(runtime, name="authored.pdf", data=PDF, media_type="application/pdf"):
    response = runtime.client.post("/v2/documents", files={"file": (name, data, media_type)})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def document(runtime, owner=None, **changes):
    values = dict(display_name="authored.pdf", data=PDF, media_type="application/pdf", page_count=1)
    values.update(changes)
    return runtime.repo.create_document(owner or runtime.owner, **values)


def simulated_job(runtime, *, status="COMPLETED"):
    source = document(runtime)
    job = runtime.repo.enqueue_parse(runtime.owner, source.id, idempotency_key=uuid4().hex, settings=SETTINGS)
    allowance = TestAllowance(id=uuid4(), job_ids=(job.id,), settings=SETTINGS, max_jobs=1, max_pages=10,
                              credit_limit="10", usd_limit="1", credits_per_page="1", usd_per_credit="0.1",
                              expires_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    register_allowance(runtime.database, allowance)
    worker = WorkerRepository(runtime.repo, allowance=allowance)
    claim = worker.claim()
    worker.accepted(claim, "simulated-api-id")
    claim = worker.claim()
    raw = ('{  "job": {"id": "simulated-api-id", "status": "' + status + '"}, "extra": [1, 2] }\n\n').encode()
    completed = worker.complete(claim, ProviderObservation(
        status, raw, markdown=PageSection(state="available", pages=(Page(page_number=2, content="  second\n"),
            Page(page_number=1, content="\tfirst "), Page(page_number=2, content=""))),
        text=PageSection(state="not_returned"), warnings=("Authored API simulation; no provider call.",),
    ))
    return source, completed, raw


def test_local_identity_requires_explicit_settings():
    assert load_local_configuration({}) is None
    config = load_local_configuration(environment())
    assert config.identity.owner == "local-api-owner"


@pytest.mark.parametrize("changes", [
    {"TAFFYBOP_PRODUCT_MODE": "hosted"}, {"TAFFYBOP_DEPLOYMENT": "production"},
    {"TAFFYBOP_DEPLOYMENT": ""}, {"TAFFYBOP_RUNTIME_PROFILE": "legacy_local"},
    {"TAFFYBOP_LOCAL_OWNER": ""}, {"TAFFYBOP_LOCAL_OWNER": "bad\nowner"},
    {"TAFFYBOP_ARTIFACT_ROOT": "relative"}, {"TAFFYBOP_ARTIFACT_ROOT": "/private/tmp/../other"},
    {"TAFFYBOP_DATABASE_URL": ""}, *({marker: "present"} for marker in HOSTED_MARKERS),
])
def test_hosted_or_incomplete_local_identity_rejected(changes):
    with pytest.raises(LocalConfigurationError):
        load_local_configuration(environment(**changes))


def test_disabled_product_fails_closed_without_database(monkeypatch):
    monkeypatch.delenv("TAFFYBOP_PRODUCT_MODE", raising=False)
    app = FastAPI()
    configure_product_api(app)
    with TestClient(app) as client:
        for route in ("/v2/config", "/v2/documents", "/v2/unknown"):
            response = client.get(route)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "product_unavailable"
            assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", [
    {"host": "evil.test"}, {"host": "127.0.0.1.evil.test"}, {"host": "127.1"},
    {"host": "user@127.0.0.1"}, {"origin": "https://evil.test"}, {"origin": "null"},
    {"origin": "http://127.0.0.1:8044"}, {"origin": "http://localhost:8043"},
    {"forwarded": "for=127.0.0.1"}, {"x-forwarded-for": "127.0.0.1"},
    {"x-forwarded-host": "127.0.0.1"}, {"sec-fetch-site": "cross-site"}, {"sec-fetch-site": "same-site"},
])
def test_local_access_rejects_spoofed_headers(runtime, headers):
    response = runtime.client.post("/v2/documents", headers=headers, files={"file": ("a.pdf", PDF, "application/pdf")})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "local_access_required"
    assert runtime.repo.list_documents(runtime.owner) == ()


def test_loopback_host_does_not_override_remote_peer(runtime):
    with TestClient(runtime.app, base_url="http://127.0.0.1:8043", client=("192.0.2.1", 9000)) as client:
        response = client.get("/v2/config")
        assert response.status_code == 403


def test_same_origin_config_is_truthful_and_secret_free(runtime):
    response = runtime.client.get("/v2/config", headers={"origin": "http://127.0.0.1:8043"})
    assert response.status_code == 200
    data = response.json()
    assert data["identity_mode"] == "local_development"
    assert data["uploads_enabled"] and not data["parse_enabled"]
    assert [item["id"] for item in data["modes"]] == ["fast", "cost_effective", "agentic"]
    assert runtime.owner not in response.text and runtime.database._dsn not in response.text


def test_upload_list_reopen_preview_and_download_exact_bytes(runtime):
    doc = upload(runtime, name="../private/日本語.pdf")
    assert doc["display_name"] == "日本語.pdf"
    assert doc["source"]["sha256"] == sha256(PDF).hexdigest()
    assert runtime.client.get("/v2/documents").json()["documents"] == [doc]
    assert runtime.client.get("/v2/documents/" + doc["id"]).json() == doc
    assert runtime.client.get(f"/v2/documents/{doc['id']}/jobs").json()["jobs"] == []
    url = f"/v2/artifacts/{doc['source']['id']}/content"
    inline = runtime.client.get(url)
    assert inline.content == PDF and inline.headers["content-type"] == "application/pdf"
    assert inline.headers["content-disposition"].startswith("inline;")
    assert "filename*=UTF-8''" in inline.headers["content-disposition"]
    assert inline.headers["x-content-type-options"] == "nosniff"
    assert inline.headers["cross-origin-resource-policy"] == "same-origin"
    download = runtime.client.get(url + "?download=true")
    assert download.content == PDF
    assert download.headers["content-disposition"].startswith("attachment;")


def test_png_upload_uses_decoded_mime_and_one_page(runtime):
    image = next(FIXTURES.glob("dev-*.png"))
    doc = upload(runtime, name=image.name, data=image.read_bytes(), media_type="image/png")
    assert doc["source"]["media_type"] == "image/png" and doc["page_count"] == 1


@pytest.mark.parametrize("extra", ["owner", "owner_id", "owner_key", "mode", "path"])
def test_upload_rejects_extra_fields_without_persistence(runtime, extra):
    response = runtime.client.post("/v2/documents", data={extra: "another-owner"}, files={"file": ("a.pdf", PDF)})
    assert response.status_code == 400
    assert runtime.repo.list_documents(runtime.owner) == ()


def test_duplicate_upload_files_are_rejected(runtime):
    response = runtime.client.post("/v2/documents", files=[("file", ("a.pdf", PDF)), ("file", ("b.pdf", PDF))])
    assert response.status_code == 400
    assert runtime.repo.list_documents(runtime.owner) == ()


def test_truncated_multipart_cannot_persist_completed_file(runtime):
    body = b'--sample\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\nContent-Type: application/pdf\r\n\r\n' + PDF + b"\r\n--sample\r\n"
    response = runtime.client.post("/v2/documents", content=body, headers={"content-type": "multipart/form-data; boundary=sample"})
    assert response.status_code == 400
    assert runtime.repo.list_documents(runtime.owner) == ()


@pytest.mark.parametrize("name,data,media,status", [
    ("empty.pdf", b"", "application/pdf", 422), ("text.pdf", b"not a PDF", "application/pdf", 400),
    ("broken.pdf", b"%PDF-broken", "application/pdf", 422),
    ("wrong.png", PDF, "image/png", 422), ("wrong.exe", PDF, "application/pdf", 422),
])
def test_upload_preserves_validation_errors(runtime, name, data, media, status):
    response = runtime.client.post("/v2/documents", files={"file": (name, data, media)})
    assert response.status_code == status
    assert set(response.json()) == {"error"}
    assert response.headers["cache-control"] == "no-store"
    assert runtime.repo.list_documents(runtime.owner) == ()


def test_oversize_declared_body_rejected_before_upload(runtime):
    response = runtime.client.post("/v2/documents", content=b"", headers={"content-length": str(11 * 1024 * 1024)})
    assert response.status_code == 413
    assert runtime.repo.list_documents(runtime.owner) == ()


def test_pagination_is_stable_and_owner_scoped(runtime):
    foreign = document(runtime, owner="foreign-owner")
    docs = [upload(runtime, name=f"{index}.pdf") for index in range(3)]
    first = runtime.client.get("/v2/documents?limit=2").json()
    assert [doc["id"] for doc in first["documents"]] == [docs[2]["id"], docs[1]["id"]]
    second = runtime.client.get("/v2/documents", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert second["documents"] == [docs[0]] and second["next_cursor"] is None
    assert str(foreign.id) not in str(first) + str(second)
    original = runtime.app.state.product_api_service
    runtime.app.state.product_api_service = ProductAPIService(LocalIdentity("foreign-owner"), original.repository, original.configuration)
    assert runtime.client.get("/v2/documents", params={"cursor": first["next_cursor"]}).status_code == 422


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 101}, {"limit": "bad"}, {"cursor": "broken"}, {"cursor": ""}, {"owner": "foreign"}])
def test_bad_list_inputs_are_sanitized(runtime, query):
    response = runtime.client.get("/v2/documents", params=query)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()["error"]) == {"code", "message"}


@pytest.mark.parametrize("bad_id", [123, {}, [], None])
def test_malformed_typed_cursor_is_validation_error(runtime, bad_id):
    payload = [sha256(runtime.owner.encode()).hexdigest(), datetime.now(timezone.utc).isoformat(), bad_id]
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    assert runtime.client.get("/v2/documents", params={"cursor": cursor}).status_code == 422


def test_parse_stays_disabled_without_enqueue(runtime):
    doc = upload(runtime)
    response = runtime.client.post(f"/v2/documents/{doc['id']}/parse", json={"mode": "fast"}, headers={"Idempotency-Key": "first"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "live_parse_unavailable"
    assert runtime.repo.list_document_jobs(runtime.owner, UUID(doc['id'])) == ()
    missing = runtime.client.post(f"/v2/documents/{uuid4()}/parse", json={"mode": "fast"}, headers={"Idempotency-Key": "first"})
    assert missing.status_code == 404


@pytest.mark.parametrize("body,headers", [({}, {"Idempotency-Key": "a"}), ({"mode": "fast"}, {}),
    ({"mode": "agentic_plus"}, {"Idempotency-Key": "a"}), ({"mode": "fast", "owner": "other"}, {"Idempotency-Key": "a"})])
def test_parse_body_and_header_contracts_are_validated(runtime, body, headers):
    doc = upload(runtime)
    response = runtime.client.post(f"/v2/documents/{doc['id']}/parse", json=body, headers=headers)
    assert response.status_code == 422


def test_simulated_job_result_and_original_download_are_faithful(runtime):
    doc, job, raw = simulated_job(runtime)
    history = runtime.client.get(f"/v2/documents/{doc.id}/jobs").json()
    assert history["jobs"] == [{"job": job.model_dump(mode="json"), "evidence_kind": "simulation"}]
    response = runtime.client.get(f"/v2/jobs/{job.id}")
    assert response.json() == job.model_dump(mode="json")
    assert response.headers["x-taffybop-evidence"] == "simulation"
    result = runtime.client.get(f"/v2/parse-results/{job.result_id}")
    assert result.headers["x-taffybop-evidence"] == "simulation"
    data = result.json()
    assert data["markdown"]["pages"] == [{"page_number": 2, "content": "  second\n"}, {"page_number": 1, "content": "\tfirst "}, {"page_number": 2, "content": ""}]
    assert data["text"]["state"] == "not_returned" and data["provider_version"] is None
    assert data["usage"]["actual_credits"] is None
    response = runtime.client.get(f"/v2/artifacts/{job.raw_response.id}/content")
    assert response.content == raw
    assert response.headers["x-taffybop-evidence"] == "simulation"
    assert response.headers["content-disposition"].startswith("attachment;")


@pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
def test_unsuccessful_terminal_raw_is_downloadable_without_success_result(runtime, status):
    _, job, raw = simulated_job(runtime, status=status)
    assert job.result_id is None
    response = runtime.client.get(f"/v2/jobs/{job.id}")
    assert response.json()["result_id"] is None
    assert runtime.client.get(f"/v2/artifacts/{job.raw_response.id}/content").content == raw


def test_unadmitted_authored_job_is_unverified_and_cancels_locally(runtime):
    doc = document(runtime)
    job = runtime.repo.enqueue_parse(runtime.owner, doc.id, idempotency_key="queued", settings=SETTINGS)
    history = runtime.client.get(f"/v2/documents/{doc.id}/jobs").json()
    assert history["jobs"][0]["evidence_kind"] == "unverified"
    first = runtime.client.post(f"/v2/jobs/{job.id}/cancel")
    assert first.status_code == 200 and first.json()["status"] == "cancelled"
    assert first.json()["cancellation_confirmed"] is True
    assert runtime.client.post(f"/v2/jobs/{job.id}/cancel").json() == first.json()
    assert runtime.client.post(f"/v2/jobs/{job.id}/cancel", json={"owner": "other"}).status_code == 422


def test_running_cancel_is_request_only(runtime):
    source = document(runtime)
    job = runtime.repo.enqueue_parse(runtime.owner, source.id, idempotency_key="running", settings=SETTINGS)
    worker = WorkerRepository(runtime.repo)
    worker.accepted(worker.claim(), "authored-running-id")
    response = runtime.client.post(f"/v2/jobs/{job.id}/cancel")
    assert response.status_code == 202
    assert response.json()["status"] == "cancel_requested" and not response.json()["cancellation_confirmed"]
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT capacity_slot FROM product.worker_executions WHERE job_id=%s", (job.id,)).fetchone()["capacity_slot"] == 1


@pytest.mark.parametrize("restriction", ["foreign", "deleted", "expired"])
def test_all_owned_reads_and_cancel_deny_inaccessible_resources(runtime, restriction):
    doc, job, _ = simulated_job(runtime)
    if restriction == "foreign":
        original = runtime.app.state.product_api_service
        runtime.app.state.product_api_service = ProductAPIService(LocalIdentity("another-owner"), original.repository, original.configuration)
    elif restriction == "deleted":
        runtime.repo.delete_document(runtime.owner, doc.id)
    else:
        with runtime.database.connect() as conn:
            conn.execute("UPDATE product.documents SET expires_at=created_at WHERE id=%s", (doc.id,))
    paths = [f"/v2/documents/{doc.id}", f"/v2/documents/{doc.id}/jobs", f"/v2/jobs/{job.id}",
             f"/v2/parse-results/{job.result_id}", f"/v2/artifacts/{doc.source.id}/content", f"/v2/artifacts/{job.raw_response.id}/content"]
    for path in paths:
        response = runtime.client.get(path)
        assert response.status_code == 404, (path, response.text)
        assert response.json() == {"error": {"code": "resource_not_found", "message": "Resource not found."}}
        assert response.headers["cache-control"] == "no-store"
    assert runtime.client.post(f"/v2/jobs/{job.id}/cancel").status_code == 404
    assert runtime.client.get("/v2/documents").json()["documents"] == []


def test_unknown_and_malformed_routes_have_safe_private_errors(runtime):
    for method, path, status in [("GET", "/v2/unknown", 404), ("TRACE", "/v2/documents", 404),
                                 ("GET", "/v2/documents/not-a-uuid", 422), ("GET", f"/v2/jobs/{uuid4()}", 404)]:
        response = runtime.client.request(method, path)
        assert response.status_code == status
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {"error"}


def test_storage_corruption_is_safe_unavailable_error(runtime):
    doc = document(runtime)
    artifact_path = runtime.repo.storage.root / str(doc.source.id)
    artifact_path.chmod(0o600)
    artifact_path.write_bytes(b"corrupt")
    response = runtime.client.get(f"/v2/artifacts/{doc.source.id}/content")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "library_unavailable"
    assert str(artifact_path) not in response.text and "corrupt" not in response.text


def test_schema_drift_rejects_enabled_startup_without_migrating(runtime):
    with runtime.database.connect() as conn:
        conn.execute("UPDATE product.schema_migrations SET sha256=%s WHERE version='001_persistence.sql'", ("0" * 64,))
    with pytest.raises(MigrationError):
        configure_product_api(FastAPI())
