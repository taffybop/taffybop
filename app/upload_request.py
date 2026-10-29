"""Keep multipart temporary files owned until the upload route completes."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser


class _OwnedMultipartRequest(Request):
    _upload_parser: MultiPartParser | None = None

    async def _get_form(
        self,
        *,
        max_files: int | float = 1000,
        max_fields: int | float = 1000,
        max_part_size: int = 1024 * 1024,
    ) -> FormData:
        content_type, _ = parse_options_header(self.headers.get("Content-Type"))
        if self._form is None and content_type == b"multipart/form-data":
            self._upload_parser = MultiPartParser(
                self.headers,
                self.stream(),
                max_files=max_files,
                max_fields=max_fields,
                max_part_size=max_part_size,
            )
            try:
                self._form = await self._upload_parser.parse()
            except MultiPartException as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
            return self._form
        return await super()._get_form(
            max_files=max_files, max_fields=max_fields, max_part_size=max_part_size
        )

    def close_upload_spools(self) -> None:
        if self._upload_parser is not None:
            # This pinned Starlette parser tracks every created spool here,
            # including incomplete parts that never reach the returned FormData.
            for spool in self._upload_parser._files_to_close_on_error:
                spool.close()


class UploadCleanupRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def handle_owned_upload(request: Request) -> Response:
            owned = _OwnedMultipartRequest(request.scope, receive=request.receive)
            try:
                return await handle(owned)
            finally:
                # Synchronous close also runs when the coroutine is cancelled;
                # valid files stay open until the endpoint has consumed them.
                owned.close_upload_spools()

        return handle_owned_upload
