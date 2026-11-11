"""Local LlamaParse proxy: bounded uploads and ephemeral job capabilities.

The registry belongs to one process, expires after an hour, and is lost on
restart. It is not a user authentication system or a durable job history.
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import threading
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import pypdfium2
from fastapi import APIRouter, Request, Response
from PIL import Image, UnidentifiedImageError
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from app.product.runtime_profile import (
    RuntimeProfileError, legacy_submission_enabled, require_legacy_submission,
)
from app.services.llamaparse_client import LlamaParseClient, LlamaParseError, MODES
from app.upload_request import UploadCleanupRoute

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
MAX_PAGES = 10
MAX_IMAGE_PIXELS = 20_000_000
UPLOAD_TIMEOUT_SECONDS = 60.0
JOB_TTL_SECONDS = 3600
MAX_JOBS = 128
DEFAULT_MODE = "cost_effective"


@dataclass(frozen=True)
class Job:
    provider_id: str
    mode: str
    page_count: int
    created_at: float
    activity_id: str | None = None


class LlamaParseService:
    def __init__(self, client: LlamaParseClient | None = None, *, clock: Callable[[], float] = time.monotonic, max_jobs: int = MAX_JOBS, ttl_seconds: float = JOB_TTL_SECONDS) -> None:
        self.client = client or LlamaParseClient()
        self.clock = clock
        self.max_jobs = max_jobs
        self.ttl_seconds = ttl_seconds
        self.submission = threading.BoundedSemaphore(1)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.admission = None

    def _expire(self) -> None:
        now = self.clock()
        self._jobs = {key: job for key, job in self._jobs.items() if now - job.created_at < self.ttl_seconds}

    def check_capacity(self) -> None:
        with self._lock:
            self._expire()
            if len(self._jobs) >= self.max_jobs:
                raise LlamaParseError(503, "job_capacity_reached", "This app has reached its temporary job limit. Wait for older jobs to expire.")

    def remember(self, provider_id: str, mode: str, pages: int, activity_id: str | None = None) -> str:
        with self._lock:
            token = secrets.token_urlsafe(32)
            self._jobs[token] = Job(provider_id, mode, pages, self.clock(), activity_id)
            return token

    def lookup(self, token: str) -> Job:
        with self._lock:
            self._expire()
            job = self._jobs.get(token)
        if job is None:
            raise LlamaParseError(404, "job_not_found", "This job is unknown, expired, or was lost when the app restarted.")
        return job


_default_service = LlamaParseService()


def _service(request: Request) -> LlamaParseService:
    return getattr(request.app.state, "llamaparse_service", _default_service)


def _error(error: LlamaParseError) -> JSONResponse:
    return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status, headers={"Cache-Control": "no-store"})


class LlamaParseRoute(UploadCleanupRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def bounded_handle(request: Request) -> Response:
            acquired = False
            service = _service(request)
            try:
                if request.method == "POST":
                    if not legacy_submission_enabled():
                        raise RuntimeProfileError()
                    if not service.client.configured:
                        raise LlamaParseError(503, "provider_not_configured", "Set LLAMA_CLOUD_API_KEY on the server before parsing.")
                    service.admission = require_legacy_submission()
                    acquired = service.submission.acquire(blocking=False)
                    if not acquired:
                        raise LlamaParseError(429, "submission_busy", "Another file is being submitted. Wait for that submission to finish.")
                    service.check_capacity()
                    length = request.headers.get("content-length")
                    if length is not None:
                        try:
                            declared = int(length)
                        except ValueError:
                            raise LlamaParseError(400, "invalid_request", "The upload has an invalid Content-Length.") from None
                        if declared < 0:
                            raise LlamaParseError(400, "invalid_request", "The upload has an invalid Content-Length.")
                        if declared > MAX_BODY_BYTES:
                            raise LlamaParseError(413, "upload_too_large", "Files must be 10 MiB or smaller.")
                    receive = request.receive
                    consumed = 0
                    deadline = time.monotonic() + UPLOAD_TIMEOUT_SECONDS

                    async def bounded_receive():
                        nonlocal consumed
                        try:
                            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                                message = await receive()
                        except TimeoutError:
                            raise LlamaParseError(408, "upload_timeout", "The upload did not finish within 60 seconds.") from None
                        if message["type"] == "http.request":
                            consumed += len(message.get("body", b""))
                            if consumed > MAX_BODY_BYTES:
                                raise LlamaParseError(413, "upload_too_large", "Files must be 10 MiB or smaller.")
                        return message

                    request = Request(request.scope, receive=bounded_receive)
                response = await handle(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RuntimeProfileError:
                return _error(LlamaParseError(503, "provider_admission_unavailable", "Local provider admission is unavailable; check the runtime profile and reconcile outstanding provider work."))
            except LlamaParseError as exc:
                return _error(exc)
            except (HTTPException, ClientDisconnect, MultipartParseError):
                return _error(LlamaParseError(400, "invalid_upload", "Provide one complete multipart file upload and a supported mode."))
            finally:
                if acquired:
                    service.submission.release()

        return bounded_handle


router = APIRouter(prefix="/v1/llamaparse", tags=["llamaparse"], route_class=LlamaParseRoute)


@router.get("/config")
async def config(request: Request) -> dict:
    return {
        "configured": _service(request).client.configured,
        "submission_enabled": legacy_submission_enabled(),
        "modes": list(MODES),
        "default_mode": DEFAULT_MODE,
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_pages": MAX_PAGES,
        "max_image_pixels": MAX_IMAGE_PIXELS,
        "job_ttl_seconds": JOB_TTL_SECONDS,
    }


def _validate_file(data: bytes, filename: str, content_type: str | None) -> tuple[str, str, int]:
    if not data:
        raise LlamaParseError(422, "empty_file", "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise LlamaParseError(413, "upload_too_large", "Files must be 10 MiB or smaller.")
    if data.startswith(b"%PDF-"):
        media_type, extension = "application/pdf", ".pdf"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type, extension = "image/png", ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        media_type, extension = "image/jpeg", ".jpg"
    else:
        raise LlamaParseError(400, "unsupported_file", "Upload a PDF, PNG, or JPEG file.")
    if content_type and content_type.split(";", 1)[0].strip().lower() not in {media_type, "application/octet-stream"}:
        raise LlamaParseError(422, "file_type_mismatch", "The file content does not match its declared type.")
    filename = PurePosixPath(filename.replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    valid_extensions = {".jpg", ".jpeg"} if extension == ".jpg" else {extension}
    if suffix and suffix not in valid_extensions:
        raise LlamaParseError(422, "file_type_mismatch", "The filename extension does not match its content.")
    filename = _safe_filename(filename, extension)
    if media_type == "application/pdf":
        try:
            document = pypdfium2.PdfDocument(data)
            try:
                pages = len(document)
            finally:
                document.close()
        except pypdfium2.PdfiumError:
            raise LlamaParseError(422, "invalid_pdf", "The PDF could not be opened. Use a valid PDF without password protection.") from None
        if pages < 1:
            raise LlamaParseError(422, "empty_document", "The PDF has no pages.")
        if pages > MAX_PAGES:
            raise LlamaParseError(413, "too_many_pages", "PDFs must contain no more than 10 pages.")
        return filename, media_type, pages
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise LlamaParseError(413, "image_too_large", "Images must contain no more than 20 million pixels.")
                if getattr(image, "n_frames", 1) != 1:
                    raise LlamaParseError(422, "animated_image", "Upload a single-frame PNG or JPEG image.")
                image.verify()
            # JPEG verification alone checks headers; decode to reject truncated
            # pixels before creating a billable job. No OCR or models run here.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LlamaParseError(413, "image_too_large", "Images must contain no more than 20 million pixels.") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise LlamaParseError(422, "invalid_image", "The image could not be decoded. Upload a complete PNG or JPEG file.") from None
    return filename, media_type, 1


def _safe_filename(filename: str, extension: str) -> str:
    # The provider needs a name, not a local path or multipart header controls.
    cleaned = "".join(char for char in filename if char.isprintable() and char not in {'"', "\r", "\n"})[:180]
    return cleaned if cleaned and PurePosixPath(cleaned).suffix else "document" + extension


@router.post("/jobs", status_code=202, openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {"type": "object", "required": ["file", "mode"], "properties": {"file": {"type": "string", "format": "binary"}, "mode": {"type": "string", "enum": [mode["id"] for mode in MODES]}}}}}}})
async def create_job(request: Request) -> JSONResponse:
    form = await request.form(max_files=1, max_fields=1, max_part_size=1024)
    file, mode = form.get("file"), form.get("mode")
    if not isinstance(file, UploadFile) or not file.filename or len(form.multi_items()) != 2:
        raise LlamaParseError(400, "invalid_upload", "Provide exactly one file and one mode.")
    mode_info = next((item for item in MODES if item["id"] == mode), None)
    if mode_info is None:
        raise LlamaParseError(400, "invalid_mode", "Choose Cost Effective, Agentic, or Agentic Plus.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    filename, media_type, pages = _validate_file(data, file.filename, file.content_type)
    service = _service(request)
    # Persist uncertainty before a billable request; process death cannot grant
    # the product worker permission to overlap an untracked legacy job.
    admission = require_legacy_submission()
    activity_id = admission.begin_legacy_submission()
    provider_id, status = await service.client.create(data, filename, media_type, str(mode), MAX_PAGES)
    admission.acknowledge_legacy_submission(activity_id, provider_id)
    token = service.remember(provider_id, str(mode), pages, activity_id)
    return JSONResponse({"job_id": token, "mode": mode, "status": status, "estimated_credits": pages * mode_info["credits_per_page"], "page_count": pages}, status_code=202)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> Response:
    service = _service(request)
    job = service.lookup(job_id)
    raw = await service.client.poll(job.provider_id)
    if job.activity_id is not None and service.admission is not None:
        if json.loads(raw)["job"]["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            service.admission.finish_legacy_submission(job.activity_id, job.provider_id)
    return Response(content=raw, media_type="application/json")
