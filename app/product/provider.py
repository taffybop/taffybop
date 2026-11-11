"""Private, single-attempt product transport for LlamaParse v2.

This adapter neither admits jobs nor retries them. The worker must persist intent
before calling submit and retain capacity on ambiguous acceptance. Product pins
are taken from immutable ParseSettings, independently of the compatibility API.
Optional output is normalized conservatively; the original response is always
returned as bytes for durable capture.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
import json
import os
import re
from typing import Any, Protocol

import httpx

from app.product.contracts import Page, PageSection, ParseSettings, Usage
from app.services.llamaparse_client import API_BASE, EXPAND, MAX_PROVIDER_RESPONSE_BYTES, STATUSES

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class ProviderSubmission:
    provider_job_id: str
    status: str


@dataclass(frozen=True)
class ProviderObservation:
    status: str
    raw: bytes
    markdown: PageSection
    text: PageSection
    provider_version: str | None = None
    usage: Usage = field(default_factory=Usage)
    warnings: tuple[str, ...] = ()


class ProviderError(Exception):
    """Fixed safe details only; ambiguous means acceptance cannot be disproved."""

    def __init__(self, code: str, message: str, *, ambiguous: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ambiguous = ambiguous


class ParseProvider(Protocol):
    async def submit(self, data: bytes, filename: str, media_type: str,
                     settings: ParseSettings) -> ProviderSubmission: ...

    async def poll(self, provider_job_id: str) -> ProviderObservation: ...


def _invalid(*, ambiguous: bool = False) -> ProviderError:
    return ProviderError("provider_invalid_response", "LlamaParse returned an unsupported response.", ambiguous=ambiguous)


def _key() -> str:
    return os.environ.get("LLAMA_CLOUD_API_KEY", "").strip()


def _object(raw: bytes, *, ambiguous: bool) -> dict[str, Any]:
    def reject_constant(_value):
        raise ValueError("Non-finite JSON constant")

    try:
        value = json.loads(raw, parse_float=Decimal, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise _invalid(ambiguous=ambiguous) from None
    if not isinstance(value, dict):
        raise _invalid(ambiguous=ambiguous)
    return value


def _section(value: dict[str, Any], name: str) -> PageSection:
    output = value.get(name)
    if output is None:
        return PageSection(state="not_returned")
    if not isinstance(output, dict) or not isinstance(output.get("pages"), list):
        return PageSection(state="unsupported")
    pages = []
    for page in output["pages"]:
        if (not isinstance(page, dict)
                or type(page.get("page_number")) is not int or page["page_number"] < 1
                or not isinstance(page.get(name), str)
                or ("success" in page and page["success"] is not True)):
            return PageSection(state="unsupported")
        pages.append(Page(page_number=page["page_number"], content=page[name]))
    return PageSection(state="available" if pages else "empty", pages=tuple(pages))


def _usage(job: dict[str, Any]) -> tuple[Usage, tuple[str, ...]]:
    usage = job.get("usage")
    if usage is None:
        return Usage(), ()
    if isinstance(usage, dict):
        credits = usage.get("credits")
        if credits is None:
            return Usage(), ()
        if type(credits) is int or isinstance(credits, Decimal):
            credits = Decimal(credits)
            if credits.is_finite() and credits >= 0:
                return Usage(actual_credits=credits, reconciliation="observed"), ()
    return Usage(), ("Provider usage was not returned in a supported numeric form.",)


class LlamaParseProvider:
    def __init__(self, *, key_provider: Callable[[], str] = _key,
                 transport: httpx.AsyncBaseTransport | None = None,
                 max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES):
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("Invalid provider response limit")
        self._key_provider = key_provider
        self._transport = transport
        self._max_response_bytes = max_response_bytes

    @property
    def configured(self) -> bool:
        return bool(self._key_provider().strip())

    async def _request(self, method: str, path: str, **kwargs: Any) -> bytes:
        key = self._key_provider().strip()
        if not key:
            raise ProviderError("provider_not_configured", "LlamaParse credentials are not configured.")
        posting = method == "POST"
        deadline = 90.0 if posting else 30.0
        try:
            async with asyncio.timeout(deadline):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(deadline, connect=10, pool=10),
                    follow_redirects=False, trust_env=False,
                ) as client:
                    async with client.stream(
                        method, API_BASE + path,
                        headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                 "Accept-Encoding": "identity"}, **kwargs,
                    ) as response:
                        status = response.status_code
                        if not 200 <= status < 300:
                            # A received 408, redirect or server failure does not
                            # establish that a parse was never accepted.
                            ambiguous = posting and status not in {
                                400, 401, 402, 403, 404, 405, 413, 415, 422, 429,
                            }
                            if status == 402:
                                code, message = "provider_credits_exhausted", "LlamaCloud credits or billing require attention."
                            elif status == 429:
                                code, message = "provider_rate_limited", "LlamaCloud is limiting requests."
                            elif status in {401, 403}:
                                code, message = "provider_authentication_failed", "LlamaCloud credentials or permissions require attention."
                            elif 400 <= status < 500:
                                code, message = "provider_rejected_request", "LlamaParse rejected the request."
                            else:
                                code, message = "provider_unavailable", "LlamaParse is unavailable."
                            raise ProviderError(code, message, ambiguous=ambiguous)
                        if "application/json" not in response.headers.get("content-type", "").lower():
                            raise _invalid(ambiguous=posting)
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self._max_response_bytes:
                                raise ProviderError("provider_response_too_large", "LlamaParse returned a response above the supported limit.", ambiguous=posting)
                            raw.extend(chunk)
                        return bytes(raw)
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderError("provider_timeout", "LlamaParse did not respond in time. Acceptance may be unresolved.", ambiguous=posting) from None
        except httpx.RequestError:
            raise ProviderError("provider_unavailable", "LlamaParse could not be reached. Acceptance may be unresolved.", ambiguous=posting) from None

    async def submit(self, data: bytes, filename: str, media_type: str,
                     settings: ParseSettings) -> ProviderSubmission:
        raw = await self._request(
            "POST", "/api/v2/parse/upload",
            files={"file": (filename, data, media_type)},
            data={"configuration": json.dumps({"tier": settings.mode,
                  "version": settings.requested_version,
                  "page_ranges": {"max_pages": settings.max_pages}})},
        )
        value = _object(raw, ambiguous=True)
        identity, status = value.get("id"), value.get("status")
        if not isinstance(identity, str) or _ID.fullmatch(identity) is None or not isinstance(status, str) or status not in STATUSES:
            raise _invalid(ambiguous=True)
        return ProviderSubmission(identity, status)

    async def poll(self, provider_job_id: str) -> ProviderObservation:
        if not isinstance(provider_job_id, str) or _ID.fullmatch(provider_job_id) is None:
            raise ProviderError("provider_invalid_id", "The stored provider job identifier is invalid.")
        raw = await self._request("GET", f"/api/v2/parse/{provider_job_id}", params={"expand": EXPAND})
        value = _object(raw, ambiguous=False)
        job = value.get("job")
        if (not isinstance(job, dict) or job.get("id") != provider_job_id
                or not isinstance(job.get("status"), str) or job["status"] not in STATUSES):
            raise _invalid()
        markdown, text = _section(value, "markdown"), _section(value, "text")
        usage, warnings = _usage(job)
        warnings += tuple(f"Provider {name} output uses an unsupported shape; inspect raw JSON."
                          for name, section in (("markdown", markdown), ("text", text))
                          if section.state == "unsupported")
        # The documented freeform job_metadata may echo request configuration.
        # Do not treat that echo or the requested pin as an observed version.
        version = job.get("version")
        if not isinstance(version, str) or not version.strip() or len(version) > 128:
            version = None
        return ProviderObservation(job["status"], raw, markdown, text,
                                   provider_version=version, usage=usage, warnings=warnings)
