"""Stable application errors and FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models import ApiError, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors safe to expose to API clients."""

    status_code = 500
    code = "internal_error"
    default_message = "The document could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details or {}

    def response(self) -> ErrorResponse:
        return ErrorResponse(
            error=ApiError(
                code=self.code,
                message=self.message,
                details=self.details,
            )
        )


class UnsupportedDocumentTypeError(AppError):
    status_code = 415
    code = "unsupported_document_type"
    default_message = (
        "Only PDF, PNG, JPEG, TIFF, and WebP documents are supported."
    )


class UploadTooLargeError(AppError):
    status_code = 413
    code = "upload_too_large"
    default_message = "The uploaded document exceeds the configured size limit."


class InvalidPdfError(AppError):
    status_code = 422
    code = "invalid_pdf"
    default_message = "The uploaded file is not a valid PDF document."


class InvalidImageError(AppError):
    status_code = 422
    code = "invalid_image"
    default_message = "The uploaded file is not a valid supported image."


class InvalidOoxmlError(AppError):
    status_code = 422
    code = "invalid_ooxml"
    default_message = "The uploaded file is not a valid supported Office package."


class OoxmlLimitExceededError(AppError):
    status_code = 413
    code = "ooxml_limit_exceeded"
    default_message = "The Office package exceeds a configured safety limit."


class PageLimitExceededError(AppError):
    status_code = 413
    code = "page_limit_exceeded"
    default_message = "The document exceeds the configured page limit."


class ImagePixelLimitExceededError(AppError):
    status_code = 413
    code = "image_pixel_limit_exceeded"
    default_message = "The image exceeds the configured decoded-pixel limit."


class ExtractionEngineUnavailableError(AppError):
    status_code = 503
    code = "extraction_engine_unavailable"
    default_message = "The document extraction engine is unavailable."


class DocumentProcessingTimeoutError(AppError):
    status_code = 504
    code = "document_processing_timeout"
    default_message = "Document processing exceeded the configured time limit."


class DocumentProcessingError(AppError):
    status_code = 500
    code = "document_processing_failed"
    default_message = "The document could not be processed."


def _json_error(error: ErrorResponse, *, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return _json_error(exc.response(), status_code=exc.status_code)


async def request_validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = {
        "issues": [
            {
                "location": [str(part) for part in issue.get("loc", ())],
                "message": issue.get("msg", "Invalid value."),
                "type": issue.get("type", "validation_error"),
            }
            for issue in exc.errors()
        ]
    }
    error = ErrorResponse(
        error=ApiError(
            code="request_validation_error",
            message="The request is invalid.",
            details=details,
        )
    )
    return _json_error(error, status_code=422)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
