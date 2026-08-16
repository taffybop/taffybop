"""HTTP endpoint for document parsing."""

from __future__ import annotations

import importlib
import hashlib
import logging
from pathlib import PurePosixPath
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.errors import (
    AppError,
    DocumentProcessingError,
    DocumentProcessingTimeoutError,
    ExtractionEngineUnavailableError,
    UploadTooLargeError,
)
from app.models import ErrorResponse, OutputFormat, ParseResult
from app.services.input_documents import (
    DeclaredInput,
    detect_upload_type,
    validate_file_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter()

READ_CHUNK_BYTES = 1024 * 1024


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "").replace("\\", "/")
    return PurePosixPath(normalized).name


def _validate_declared_type(
    file: UploadFile,
    filename: str,
    settings: Settings | None = None,
) -> DeclaredInput:
    return detect_upload_type(filename, file.content_type, settings)


async def _read_bounded_upload(
    file: UploadFile,
    max_bytes: int,
    declared: DeclaredInput,
) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0

    while chunk := await file.read(READ_CHUNK_BYTES):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadTooLargeError(
                details={
                    "max_bytes": max_bytes,
                    "received_at_least_bytes": total_bytes,
                }
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    validate_file_signature(data, declared)
    return data


def _load_callable(module_name: str, function_name: str) -> Callable[..., Any]:
    try:
        module = importlib.import_module(module_name)
        function = getattr(module, function_name)
    except (ImportError, AttributeError) as exc:
        logger.exception("Unable to load %s.%s", module_name, function_name)
        raise ExtractionEngineUnavailableError(
            details={
                "component": f"{module_name}.{function_name}",
                "reason": type(exc).__name__,
            }
        ) from exc

    if not callable(function):
        raise ExtractionEngineUnavailableError(
            details={"component": f"{module_name}.{function_name}"}
        )
    return function


def _parse_document(
    data: bytes,
    filename: str,
    settings: Settings,
    parser_worker: Any | None = None,
    office_renderer: Any | None = None,
) -> Any:
    parse_document = _load_callable(
        "app.services.pipeline",
        "parse_document",
    )
    if (
        parser_worker is not None
        and getattr(
            parser_worker,
            "has_current_armed_broker_request",
            lambda: False,
        )()
    ):
        with parser_worker.claim_armed_broker_request():
            kwargs: dict[str, Any] = {"parser_worker": parser_worker}
            if office_renderer is not None:
                kwargs["office_renderer"] = office_renderer
            return parse_document(data, filename, settings, **kwargs)
    if settings.parser_latency_prewarm_enabled:
        if parser_worker is None:
            raise ExtractionEngineUnavailableError(
                details={"component": "parser_worker", "reason": "unavailable"}
            )
        source_sha256 = hashlib.sha256(data).hexdigest()
        with parser_worker.lease(
            settings,
            request_id=f"parse-{source_sha256}",
            binding={
                "schema_id": "parser-broker-request-binding-v1",
                "source_sha256": source_sha256,
                "source_bytes": len(data),
                "filename_sha256": hashlib.sha256(
                    filename.encode("utf-8")
                ).hexdigest(),
            },
        ):
            kwargs = {"parser_worker": parser_worker}
            if office_renderer is not None:
                kwargs["office_renderer"] = office_renderer
            return parse_document(data, filename, settings, **kwargs)
    if parser_worker is not None and getattr(
        parser_worker, "instrument_only", False
    ) is True:
        source_sha256 = hashlib.sha256(data).hexdigest()
        with parser_worker.lease(
            settings,
            request_id=f"parse-{source_sha256}",
            binding={
                "schema_id": "parser-broker-request-binding-v1",
                "source_sha256": source_sha256,
                "source_bytes": len(data),
                "filename_sha256": hashlib.sha256(
                    filename.encode("utf-8")
                ).hexdigest(),
            },
        ):
            kwargs = {"parser_worker": parser_worker}
            if office_renderer is not None:
                kwargs["office_renderer"] = office_renderer
            return parse_document(data, filename, settings, **kwargs)
    if office_renderer is not None:
        return parse_document(
            data,
            filename,
            settings,
            office_renderer=office_renderer,
        )
    return parse_document(data, filename, settings)


def _serialize_markdown(result: Any) -> str:
    to_markdown = _load_callable(
        "app.services.serializer",
        "to_markdown",
    )
    markdown = to_markdown(result)
    if not isinstance(markdown, str):
        raise DocumentProcessingError(
            details={"reason": "markdown_serializer_returned_non_string"}
        )
    return markdown


def _serialize_text(result: Any) -> str:
    to_text = _load_callable(
        "app.services.serializer",
        "to_text",
    )
    plain_text = to_text(result)
    if not isinstance(plain_text, str):
        raise DocumentProcessingError(
            details={"reason": "text_serializer_returned_non_string"}
        )
    return plain_text


@router.post(
    "/v1/parse",
    summary="Parse a supported document into structured JSON, Markdown, or text",
    responses={
        200: {
            "model": ParseResult,
            "description": (
                "Structured parse result, Markdown projection, or plain-text "
                "projection"
            ),
            "content": {
                "text/markdown": {
                    "schema": {"type": "string"},
                },
                "text/plain": {
                    "schema": {"type": "string"},
                },
            },
        },
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def parse_document_endpoint(
    request: Request,
    file: UploadFile = File(
        ...,
        description=(
            "PDF, PNG, JPEG, TIFF, WebP, or an enabled DOCX, PPTX, or XLSX "
            "document to parse"
        ),
    ),
    output_format: OutputFormat = Query(
        default=OutputFormat.JSON,
        description="Response representation",
    ),
    settings: Settings = Depends(get_settings),
) -> Response:
    filename = _safe_filename(file.filename)
    upload_content_type = file.content_type or ""

    try:
        declared = _validate_declared_type(file, filename, settings)
        data = await _read_bounded_upload(
            file,
            settings.max_upload_bytes,
            declared,
        )
    finally:
        await file.close()

    try:
        parser_worker = getattr(
            request.app.state,
            "parser_worker_runtime",
            None,
        )
        # This is an application-owned capability, never a request parameter.
        # Do not inspect or forward stale state while the fallback is disabled.
        office_renderer = (
            getattr(request.app.state, "office_renderer", None)
            if settings.adapters_office_fallback_enabled
            else None
        )
        armed_snapshot = (
            parser_worker.armed_broker_request_snapshot()
            if parser_worker is not None
            and hasattr(parser_worker, "armed_broker_request_snapshot")
            else None
        )
        if armed_snapshot is not None:
            parser_worker.validate_armed_request_input(
                data,
                filename,
                upload_content_type,
                output_format.value,
            )
        uses_parser_worker = settings.parser_latency_prewarm_enabled or (
            parser_worker is not None
            and getattr(parser_worker, "instrument_only", False) is True
        )

        async def invoke_parser() -> Any:
            if uses_parser_worker or office_renderer is not None:
                arguments: list[Any] = [data, filename, settings, parser_worker]
                if office_renderer is not None:
                    arguments.append(office_renderer)
                return await run_in_threadpool(
                    _parse_document,
                    *arguments,
                )
            return await run_in_threadpool(
                _parse_document,
                data,
                filename,
                settings,
            )

        # Install the application-owned telemetry client across the complete
        # parser thread boundary.  The default client constructed from
        # Settings still has a no-op exporter, while deployments and tests can
        # inject one bounded exporter through app.state without changing the
        # public endpoint or parser call signature.  Context variables are
        # copied by Starlette's threadpool helper.
        from app.services.telemetry import (
            telemetry_client_for_settings,
            use_telemetry,
        )

        telemetry_client = getattr(
            request.app.state,
            "parser_telemetry_client",
            None,
        )
        owns_telemetry_client = telemetry_client is None
        if telemetry_client is None:
            telemetry_client = telemetry_client_for_settings(settings)
        try:
            with use_telemetry(telemetry_client):
                result = await invoke_parser()
        finally:
            if owns_telemetry_client:
                telemetry_client.close()
        # The parser normally returns ``ParseResult``, but the HTTP boundary
        # must not trust that implementation detail.  Validate the exact plain
        # JSON projection before either serializer can expose it; documenting
        # a response model alone does not validate a manually-created
        # ``Response``.
        public_result = jsonable_encoder(result)
        validated_result = ParseResult.model_validate(public_result)
        public_result = validated_result.model_dump(
            mode="json",
            exclude_unset=True,
        )

        if output_format is OutputFormat.MARKDOWN:
            markdown = await run_in_threadpool(
                _serialize_markdown,
                public_result,
            )
            return Response(
                content=markdown,
                media_type="text/markdown",
            )

        if output_format is OutputFormat.TEXT:
            plain_text = await run_in_threadpool(
                _serialize_text,
                public_result,
            )
            return Response(
                content=plain_text,
                media_type="text/plain",
            )

        return JSONResponse(content=public_result)
    except AppError:
        raise
    except TimeoutError as exc:
        raise DocumentProcessingTimeoutError() from exc
    except Exception as exc:
        logger.exception("Document parsing failed for %s", filename)
        raise DocumentProcessingError(
            details={"reason": type(exc).__name__}
        ) from exc
