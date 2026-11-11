"""Small, bounded LlamaParse v2 transport. No retries or tier upgrades.

The caller must use a Free LlamaCloud organization to rely on its free credit
allowance. The API has no documented free-only request switch.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from typing import Any

import httpx

API_BASE = "https://api.cloud.llamaindex.ai"
EXPAND = "markdown,text,items,metadata,job_metadata,usage"
STATUSES = frozenset({"PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"})
MAX_PROVIDER_RESPONSE_BYTES = 32 * 1024 * 1024
MODES = (
    {"id": "cost_effective", "label": "Cost Effective", "description": "Lower-cost AI parsing for simpler documents.", "credits_per_page": 3},
    {"id": "agentic", "label": "Agentic", "description": "AI parsing for more complex document layouts.", "credits_per_page": 10},
    {"id": "agentic_plus", "label": "Agentic Plus", "description": "More intensive AI parsing for difficult documents.", "credits_per_page": 45},
)


class LlamaParseError(Exception):
    """Only fixed, public-safe messages belong in this exception."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _api_key() -> str:
    return os.environ.get("LLAMA_CLOUD_API_KEY", "").strip()


def _invalid_response() -> LlamaParseError:
    return LlamaParseError(502, "provider_invalid_response", "LlamaParse returned an unexpected response.")


def _json_object(raw: bytes) -> dict[str, Any]:
    def reject_constant(_value: str) -> None:
        raise ValueError("Non-JSON constant")

    try:
        value = json.loads(raw, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid_response() from None
    if not isinstance(value, dict):
        raise _invalid_response()
    return value


def _provider_error(status: int) -> LlamaParseError:
    if status == 402:
        return LlamaParseError(402, "provider_credits_exhausted", "LlamaCloud credits are exhausted or billing requires attention. No retry was made.")
    if status == 429:
        return LlamaParseError(429, "provider_rate_limited", "LlamaCloud is limiting requests. No retry was made.")
    if status in {401, 403}:
        return LlamaParseError(503, "provider_authentication_failed", "LlamaCloud credentials or project permissions need attention.")
    if 400 <= status < 500:
        return LlamaParseError(502, "provider_rejected_request", "LlamaParse rejected the request. No retry was made.")
    return LlamaParseError(502, "provider_unavailable", "LlamaParse is unavailable. No retry was made.")


class LlamaParseClient:
    def __init__(
        self,
        *,
        key_provider: Callable[[], str] = _api_key,
        transport: httpx.AsyncBaseTransport | None = None,
        max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
    ) -> None:
        self._key_provider = key_provider
        self._transport = transport
        self._max_response_bytes = max_response_bytes

    @property
    def configured(self) -> bool:
        return bool(self._key_provider().strip())

    async def _request(self, method: str, path: str, **kwargs: Any) -> bytes:
        key = self._key_provider().strip()
        if not key:
            raise LlamaParseError(503, "provider_not_configured", "Set LLAMA_CLOUD_API_KEY on the server before parsing.")
        # A timed-out create may already have been accepted upstream. Never retry
        # it automatically: the provider may charge for that first submission.
        deadline = 90.0 if method == "POST" else 30.0
        try:
            async with asyncio.timeout(deadline):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(deadline, connect=10.0, pool=10.0),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        method,
                        API_BASE + path,
                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json", "Accept-Encoding": "identity"},
                        **kwargs,
                    ) as response:
                        if not 200 <= response.status_code < 300:
                            raise _provider_error(response.status_code)
                        if "application/json" not in response.headers.get("content-type", "").lower():
                            raise _invalid_response()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self._max_response_bytes:
                                raise LlamaParseError(502, "provider_response_too_large", "LlamaParse returned a result larger than this app can accept.")
                            raw.extend(chunk)
                        return bytes(raw)
        except (TimeoutError, httpx.TimeoutException):
            message = "LlamaParse did not respond in time. A submitted job may still run; do not automatically resubmit."
            raise LlamaParseError(504, "provider_timeout", message) from None
        except httpx.RequestError:
            raise LlamaParseError(502, "provider_unavailable", "Could not reach LlamaParse. A submitted job may still run; no retry was made.") from None

    async def create(self, data: bytes, filename: str, media_type: str, mode: str, max_pages: int) -> tuple[str, str]:
        raw = await self._request(
            "POST", "/api/v2/parse/upload",
            files={"file": (filename, data, media_type)},
            data={"configuration": json.dumps({"tier": mode, "version": "latest", "page_ranges": {"max_pages": max_pages}})},
        )
        value = _json_object(raw)
        job_id, status = value.get("id"), value.get("status")
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) or not isinstance(status, str) or status not in STATUSES:
            raise _invalid_response()
        return job_id, status

    async def poll(self, provider_id: str) -> bytes:
        raw = await self._request("GET", f"/api/v2/parse/{provider_id}", params={"expand": EXPAND})
        value = _json_object(raw)
        job = value.get("job")
        if not isinstance(job, dict) or job.get("id") != provider_id or not isinstance(job.get("status"), str) or job["status"] not in STATUSES:
            raise _invalid_response()
        # Validate the job envelope, not the provider's evolving optional output
        # schema. Missing/unrecognized sections remain inspectable in Raw JSON;
        # the UI must show them as unavailable instead of inventing content.
        # FAILED/CANCELLED and delayed/null usage also remain exactly as returned.
        return raw
