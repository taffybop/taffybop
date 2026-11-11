"""PX1 persistent local library. No HTTP handler can submit provider work.

The worker is a separate, explicitly guarded process. This router exposes stored
state only; successful captures without immutable simulation provenance remain
unverified. Production authentication and live parsing are later gates.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import time
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from app.llamaparse_api import (
    MAX_BODY_BYTES, MAX_UPLOAD_BYTES, UPLOAD_TIMEOUT_SECONDS, _validate_file,
)
from app.product.contracts import DocumentList, ParseRequest
from app.product.database import Database, MigrationError
from app.product.lifecycle import WorkerRepository
from app.product.local_identity import (
    LocalIdentity, LocalRequestDenied, load_local_configuration,
)
from app.product.provider_config import ProviderConfiguration, load_provider_configuration
from app.product.repository import ProductRepository, ResourceNotFound
from app.product.storage import LocalArtifactStore
from app.services.llamaparse_client import LlamaParseError
from app.upload_request import UploadCleanupRoute


DISABLED_REASON = "Live parsing is unavailable until provider qualification and spending bounds are verified."


@dataclass(frozen=True)
class ProductAPIService:
    identity: LocalIdentity
    repository: ProductRepository
    configuration: ProviderConfiguration


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _service(request: Request) -> ProductAPIService:
    return request.app.state.product_api_service


def _owner(request: Request) -> str:
    return request.scope["product_owner"]


def _response(model, *, status: int = 200, evidence: str | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if evidence is not None:
        headers["X-TaffyBop-Evidence"] = evidence
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=headers)


class ProductBoundaryMiddleware:
    """Guard every /v2 path and bound receive before multipart/JSON parsing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope["path"] == "/v2" or scope["path"].startswith("/v2/")):
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        service = getattr(scope["app"].state, "product_api_service", None)
        if service is None:
            return await _error(503, "product_unavailable", "The saved library is unavailable in this session.")(scope, receive, send)
        try:
            scope["product_owner"] = service.identity.authorize(request)
        except LocalRequestDenied:
            return await _error(403, "local_access_required", str(LocalRequestDenied()))(scope, receive, send)
        consumed = 0
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                declared = int(declared)
                if declared < 0:
                    raise ValueError()
            except ValueError:
                return await _error(400, "invalid_request", "The request has an invalid Content-Length.")(scope, receive, send)
            if declared > MAX_BODY_BYTES:
                return await _error(413, "upload_too_large", "Files must be 10 MiB or smaller.")(scope, receive, send)
        deadline = time.monotonic() + UPLOAD_TIMEOUT_SECONDS
        tail = b""
        boundary = None
        if scope["method"] == "POST" and scope["path"] == "/v2/documents":
            kind, options = parse_options_header(request.headers.get("content-type", ""))
            boundary = options.get(b"boundary")
            if (kind != b"multipart/form-data" or boundary is None or not 1 <= len(boundary) <= 70
                    or any(char < 32 or char > 126 for char in boundary)):
                return await _error(400, "invalid_upload", "Provide exactly one complete multipart file upload.")(scope, receive, send)
            scope["product_upload_complete"] = False

        async def bounded_receive():
            nonlocal consumed, tail
            try:
                async with asyncio.timeout(max(0, deadline - time.monotonic())):
                    message = await receive()
            except TimeoutError:
                raise LlamaParseError(408, "upload_timeout", "The upload did not finish within 60 seconds.") from None
            if message["type"] == "http.request":
                body = message.get("body", b"")
                consumed += len(body)
                if consumed > MAX_BODY_BYTES:
                    raise LlamaParseError(413, "upload_too_large", "Files must be 10 MiB or smaller.")
                if boundary is not None:
                    tail = (tail + body)[-(len(boundary) + 8):]
                    if not message.get("more_body", False):
                        closing = b"\r\n--" + boundary + b"--"
                        scope["product_upload_complete"] = (tail.endswith(closing) or tail.endswith(closing + b"\r\n")) and (declared is None or consumed == declared)
            return message

        started = False

        async def private_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [(name, value) for name, value in message.get("headers", ())
                           if name.lower() not in {b"cache-control", b"x-content-type-options", b"cross-origin-resource-policy"}]
                headers.extend([(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                (b"cross-origin-resource-policy", b"same-origin")])
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, bounded_receive, private_send)
        except Exception:
            if started:
                raise
            await _error(503, "library_unavailable", "The saved library could not be accessed. Try again later.")(scope, receive, private_send)


class ProductRoute(UploadCleanupRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def safe_handle(request):
            try:
                allowed_query = ({"limit", "cursor"} if request.url.path == "/v2/documents" and request.method == "GET"
                                 else {"download"} if request.url.path.endswith("/content") else set())
                if any(name not in allowed_query for name in request.query_params):
                    return _error(422, "invalid_request", "The request is invalid.")
                return await handle(request)
            except ResourceNotFound:
                return _error(404, "resource_not_found", "Resource not found.")
            except (RequestValidationError, ValidationError):
                return _error(422, "invalid_request", "The request is invalid.")
            except LlamaParseError as exc:
                return _error(exc.status, exc.code, exc.message)
            except (HTTPException, ClientDisconnect, MultipartParseError):
                return _error(400, "invalid_request", "Provide a complete valid request.")
        return safe_handle


router = APIRouter(prefix="/v2", tags=["product-local"], route_class=ProductRoute)


@router.get("/config")
def config(request: Request):
    configuration = _service(request).configuration
    return {"schema_version": "2.0", "enabled": True, "identity_mode": "local_development",
            "uploads_enabled": True, "parse_enabled": False, "disabled_reason": DISABLED_REASON,
            "default_mode": configuration.default_settings.mode,
            "modes": [{"id": "fast", "label": "Fast"}, {"id": "cost_effective", "label": "Cost-effective"},
                      {"id": "agentic", "label": "Agentic"}]}


@router.post("/documents", status_code=201)
async def upload_document(request: Request):
    form = await request.form(max_files=1, max_fields=0, max_part_size=1024)
    file = form.get("file")
    if (not isinstance(file, UploadFile) or not file.filename or len(form.multi_items()) != 1
            or not request.scope.get("product_upload_complete")):
        return _error(400, "invalid_upload", "Provide exactly one complete multipart file upload.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    filename, media_type, pages = _validate_file(data, file.filename, file.content_type)
    # PDF/image validation performs no OCR or network access. Database/storage
    # operations run in the thread pool, as do the synchronous read endpoints.
    from starlette.concurrency import run_in_threadpool
    document = await run_in_threadpool(_service(request).repository.create_document, _owner(request),
                                      display_name=filename, media_type=media_type, data=data, page_count=pages)
    return _response(document, status=201)


def _cursor(owner: str, document) -> str:
    payload = [sha256(owner.encode()).hexdigest(), document.created_at.isoformat(), str(document.id)]
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _before(owner: str, cursor: str):
    try:
        if len(cursor) > 2048 or not cursor.isascii():
            raise ValueError()
        payload = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (not isinstance(payload, list) or len(payload) != 3
                or not all(isinstance(value, str) for value in payload)
                or payload[0] != sha256(owner.encode()).hexdigest()):
            raise ValueError()
        created, identity = datetime.fromisoformat(payload[1]), UUID(payload[2])
        if created.tzinfo is None:
            raise ValueError()
        return created, identity
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise LlamaParseError(422, "invalid_cursor", "The document cursor is invalid.") from None


@router.get("/documents")
def list_documents(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25,
                   cursor: Annotated[str | None, Query(max_length=2048)] = None):
    owner, repo = _owner(request), _service(request).repository
    documents = repo.list_documents(owner, limit=limit, before=_before(owner, cursor) if cursor is not None else None)
    next_cursor = None
    if len(documents) == limit:
        last = documents[-1]
        if repo.list_documents(owner, limit=1, before=(last.created_at, last.id)):
            next_cursor = _cursor(owner, last)
    return _response(DocumentList(documents=documents, next_cursor=next_cursor))


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, request: Request):
    return _response(_service(request).repository.get_document(_owner(request), document_id))


@router.get("/documents/{document_id}/jobs")
def document_jobs(document_id: UUID, request: Request):
    rows = _service(request).repository.list_document_jobs(_owner(request), document_id)
    return {"schema_version": "2.0", "jobs": [{"job": job.model_dump(mode="json"), "evidence_kind": kind} for job, kind in rows]}


@router.post("/documents/{document_id}/parse")
def parse_document(document_id: UUID, body: ParseRequest, request: Request,
                   idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]):
    if any(not 32 <= ord(char) <= 126 for char in idempotency_key):
        return _error(422, "invalid_request", "The request is invalid.")
    _service(request).repository.get_document(_owner(request), document_id)
    # Deliberately no enqueue or transport path. Simulations are created only
    # by the separately allowlisted private runner, never ordinary user actions.
    return _error(503, "live_parse_unavailable", DISABLED_REASON)


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, request: Request):
    repo, owner = _service(request).repository, _owner(request)
    return _response(repo.get_job(owner, job_id), evidence=repo.job_evidence_kind(owner, job_id))


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID, request: Request):
    # Consume through the bounded receive path before rejecting unexpected input.
    if await request.body():
        return _error(422, "invalid_request", "Cancellation does not accept a request body.")
    from starlette.concurrency import run_in_threadpool
    repo, owner = _service(request).repository, _owner(request)
    job = await run_in_threadpool(WorkerRepository(repo).request_cancel, owner, job_id)
    kind = await run_in_threadpool(repo.job_evidence_kind, owner, job_id)
    return _response(job, status=200 if job.status in {"succeeded", "failed", "cancelled"} else 202, evidence=kind)


@router.get("/parse-results/{result_id}")
def get_result(result_id: UUID, request: Request):
    repo, owner = _service(request).repository, _owner(request)
    result = repo.get_parse_result(owner, result_id)
    return _response(result, evidence=repo.job_evidence_kind(owner, result.job_id))


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: UUID, request: Request,
                     download: Annotated[bool, Query()] = False):
    artifact, filename, data, evidence = _service(request).repository.download_artifact(_owner(request), artifact_id)
    disposition = "attachment" if download or artifact.media_type == "application/json" else "inline"
    fallback = "source" + {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "application/json": ".json"}[artifact.media_type]
    return Response(content=data, media_type=artifact.media_type, headers={
        "Content-Disposition": f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}",
        "X-TaffyBop-Evidence": evidence, "Cache-Control": "no-store",
    })


@router.api_route("", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"], include_in_schema=False)
@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE", "CONNECT"], include_in_schema=False)
def missing_route(path: str = ""):
    return _error(404, "resource_not_found", "Resource not found.")


def configure_product_api(application: FastAPI) -> None:
    """Freeze explicit server config; never migrate or acquire provider admission."""
    configuration = load_local_configuration()
    application.state.product_api_service = None
    if configuration is not None:
        database = Database(configuration.database_url)
        # Verify the installed schema read-only. A missing/drifted migration
        # prevents startup; HTTP imports never implicitly apply migrations.
        from pathlib import Path
        with database.connect() as conn:
            installed = {row["version"]: row["sha256"] for row in conn.execute("SELECT version,sha256 FROM product.schema_migrations")}
        expected = {path.name: sha256(path.read_bytes()).hexdigest() for path in Path(__file__).with_name("migrations").glob("[0-9][0-9][0-9]_*.sql")}
        if not expected or installed != expected:
            raise MigrationError("Apply and verify product migrations explicitly")
        application.state.product_api_service = ProductAPIService(
            configuration.identity, ProductRepository(database, LocalArtifactStore(configuration.artifact_root)),
            load_provider_configuration(),
        )
    application.include_router(router)
    application.add_middleware(ProductBoundaryMiddleware)
