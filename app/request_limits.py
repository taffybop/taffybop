"""Admission and streaming body limits before FastAPI parses upload forms."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from threading import BoundedSemaphore

from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import AppError, ParserBusyError, UploadTimeoutError, UploadTooLargeError


class _UploadRejected(MultiPartException):
    # Starlette closes already-spooled multipart files on MultiPartException.
    # Its generated 400 is suppressed below in favor of our typed 413/408.
    pass


def _error_response(error: AppError, *, retry_after: str | None = None) -> JSONResponse:
    return JSONResponse(
        error.response().model_dump(mode="json"),
        status_code=error.status_code,
        headers={"Retry-After": retry_after} if retry_after else None,
    )


class ParserRequestLimitsMiddleware:
    """Hold a non-queued per-process slot across upload, parse, and response.

    The body limit counts every multipart byte, including chunked requests
    without Content-Length, before those bytes reach the multipart parser.
    This is not authentication or a hard native-processing deadline.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_body_bytes: int,
        max_concurrent_parse_requests: int,
        upload_timeout_seconds: float,
    ) -> None:
        if max_request_body_bytes < 1 or max_concurrent_parse_requests < 1:
            raise ValueError("Parser request limits must be positive.")
        self.app = app
        self.max_request_body_bytes = max_request_body_bytes
        self.max_concurrent_parse_requests = max_concurrent_parse_requests
        self.upload_timeout_seconds = upload_timeout_seconds
        self._slots = BoundedSemaphore(max_concurrent_parse_requests)
        self._in_flight: set[asyncio.Task[None]] = set()

    def _request_done(self, task: asyncio.Task[None]) -> None:
        self._in_flight.discard(task)
        if not task.cancelled():
            # The caller may have disconnected while admitted work finished.
            # Retrieve background exceptions; normal awaited failures still
            # propagate through FastAPI's existing error handling.
            task.exception()

    def _too_large(self, received: int) -> JSONResponse:
        return _error_response(UploadTooLargeError(
            "The upload request exceeds the configured size limit.",
            details={
                "max_request_body_bytes": self.max_request_body_bytes,
                "received_at_least_bytes": received,
            },
        ))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/v1/parse"
        ):
            await self.app(scope, receive, send)
            return

        # Reject declared oversized bodies without reading or spooling them.
        for name, value in scope.get("headers", ()):
            if name.lower() == b"content-length" and value.isdigit():
                declared_bytes = int(value)
                if declared_bytes > self.max_request_body_bytes:
                    await self._too_large(declared_bytes)(scope, receive, send)
                    return

        if not self._slots.acquire(blocking=False):
            response = _error_response(
                ParserBusyError(details={
                    "max_concurrent_parse_requests": self.max_concurrent_parse_requests,
                }),
                retry_after="5",
            )
            await response(scope, receive, send)
            return

        received_bytes = 0
        body_exceeded = False
        upload_timed_out = False
        request_body_complete = False
        upload_deadline = asyncio.get_running_loop().time() + self.upload_timeout_seconds

        async def bounded_receive() -> Message:
            nonlocal received_bytes, body_exceeded, request_body_complete, upload_timed_out
            if request_body_complete:
                return await receive()
            remaining = upload_deadline - asyncio.get_running_loop().time()
            try:
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError as exc:
                upload_timed_out = True
                raise _UploadRejected("Upload deadline exceeded.") from exc
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_request_body_bytes:
                    body_exceeded = True
                    raise _UploadRejected("Upload request body limit exceeded.")
                if not message.get("more_body", False):
                    request_body_complete = True
            return message

        async def bounded_send(message: Message) -> None:
            # FastAPI converts multipart exceptions to a 400. It must not send
            # that response when this middleware owns a more precise 413.
            if not body_exceeded and not upload_timed_out:
                await send(message)

        async def run_admitted() -> None:
            try:
                try:
                    await self.app(scope, bounded_receive, bounded_send)
                except _UploadRejected:
                    pass
                if body_exceeded:
                    await self._too_large(received_bytes)(scope, receive, send)
                elif upload_timed_out:
                    await _error_response(UploadTimeoutError(details={
                        "upload_timeout_seconds": self.upload_timeout_seconds,
                    }))(scope, receive, send)
            finally:
                self._slots.release()

        task = asyncio.create_task(run_admitted())
        self._in_flight.add(task)
        task.add_done_callback(self._request_done)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not request_body_complete:
                # FastAPI has not finished parsing the form, so native parsing
                # cannot have started. Cancel this incomplete upload promptly.
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            # Once the body is complete, keep the slot until the admitted task
            # and any parser thread it awaits finish, even if its caller leaves.
            raise
