"""Mock upstream transport evidence only; no provider parsing or charges."""

import asyncio
from decimal import Decimal
from email.parser import BytesParser
from email.policy import default
import json

import httpx
import pytest

from app.product.contracts import ParseSettings
from app.product.provider import LlamaParseProvider, ProviderError


SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28", max_pages=7)


def provider(handler, **kwargs):
    return LlamaParseProvider(key_provider=lambda: "private-test-key", transport=httpx.MockTransport(handler), **kwargs)


def observe(data=None, *, raw=None):
    if raw is None:
        raw = json.dumps(data).encode()
    return asyncio.run(provider(lambda _: httpx.Response(200, content=raw, headers={"content-type": "application/json"})).poll("pjb-fixture"))


@pytest.mark.parametrize(("mode", "version"), [("fast", "2026-06-15"), ("cost_effective", "2026-09-28"), ("agentic", "2026-09-29")])
def test_submission_uses_immutable_product_pin_and_combined_upload(mode, version):
    calls = []

    async def handler(request):
        calls.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://api.cloud.llamaindex.ai/api/v2/parse/upload"
        assert request.headers["authorization"] == "Bearer private-test-key"
        assert request.headers["accept-encoding"] == "identity"
        body = await request.aread()
        message = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + body)
        parts = {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}
        assert json.loads(parts["configuration"].get_payload(decode=True)) == {"tier": mode, "version": version, "page_ranges": {"max_pages": 7}}
        assert parts["file"].get_payload(decode=True) == b"synthetic bytes"
        assert parts["file"].get_filename() == "fixture.pdf"
        return httpx.Response(200, json={"id": "pjb-fixture", "status": "PENDING"})

    result = asyncio.run(provider(handler).submit(b"synthetic bytes", "fixture.pdf", "application/pdf", SETTINGS.model_copy(update={"mode": mode, "requested_version": version})))
    assert (result.provider_job_id, result.status) == ("pjb-fixture", "PENDING")
    assert len(calls) == 1


@pytest.mark.parametrize(("status", "ambiguous", "code"), [
    (402, False, "provider_credits_exhausted"), (429, False, "provider_rate_limited"),
    (401, False, "provider_authentication_failed"), (403, False, "provider_authentication_failed"),
    (422, False, "provider_rejected_request"), (408, True, "provider_rejected_request"),
    (500, True, "provider_unavailable"), (302, True, "provider_unavailable"),
])
def test_submission_rejections_and_uncertainty_are_single_attempt_and_sanitized(status, ambiguous, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"secret": "provider body with credentials and source text"})

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider(handler).submit(b"source", "fixture.pdf", "application/pdf", SETTINGS))
    assert len(calls) == 1
    assert (raised.value.ambiguous, raised.value.code) == (ambiguous, code)
    assert "provider body" not in str(raised.value)
    assert "private-test-key" not in repr(raised.value)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_error_never_retries_and_marks_create_uncertain(failure):
    calls = []

    def handler(request):
        calls.append(request)
        raise failure("private exception with secret", request=request)

    with pytest.raises(ProviderError) as raised:
        asyncio.run(provider(handler).submit(b"source", "fixture.pdf", "application/pdf", SETTINGS))
    assert raised.value.ambiguous is True
    assert "private exception" not in str(raised.value)
    assert len(calls) == 1


@pytest.mark.parametrize("raw", [b"{}", b'{"id":"pjb-fixture","status":"NEW"}', b'{"id":"../escape","status":"PENDING"}', b"not JSON", b'{"id":"pjb-fixture","status":"PENDING","v":NaN}'])
def test_malformed_create_response_retains_unknown_acceptance(raw):
    value = provider(lambda _: httpx.Response(200, content=raw, headers={"content-type": "application/json"}))
    with pytest.raises(ProviderError) as raised:
        asyncio.run(value.submit(b"source", "fixture.pdf", "application/pdf", SETTINGS))
    assert raised.value.ambiguous is True


def test_missing_key_fails_without_transport_or_acceptance():
    def handler(_):
        pytest.fail("no key must not send a request")

    value = LlamaParseProvider(key_provider=lambda: " ", transport=httpx.MockTransport(handler))
    assert value.configured is False
    with pytest.raises(ProviderError) as raised:
        asyncio.run(value.submit(b"source", "fixture.pdf", "application/pdf", SETTINGS))
    assert raised.value.ambiguous is False
    assert raised.value.code == "provider_not_configured"


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"])
def test_poll_preserves_original_bytes_and_terminal_failures(status):
    raw = ('{\n "job": {"id":"pjb-fixture", "status":"' + status + '","usage":{"credits":null}}, "unknown": {"keep": [1,2]} }\n\n').encode()
    result = observe(raw=raw)
    assert result.raw == raw
    assert result.status == status
    assert result.provider_version is None
    assert result.usage.actual_credits is None
    assert result.usage.reconciliation == "pending"
    assert result.markdown.state == result.text.state == "not_returned"


def test_formats_preserve_independent_page_order_duplicates_and_whitespace():
    result = observe({"job": {"id": "pjb-fixture", "status": "COMPLETED"},
                      "markdown": {"pages": [{"page_number": 2, "markdown": "\n second ", "success": True}, {"page_number": 1, "markdown": "\tfirst\n"}, {"page_number": 2, "markdown": ""}]},
                      "text": {"pages": [{"page_number": 1, "text": " exact text "}]}})
    assert result.markdown.state == "available"
    assert [(p.page_number, p.content) for p in result.markdown.pages] == [(2, "\n second "), (1, "\tfirst\n"), (2, "")]
    assert [(p.page_number, p.content) for p in result.text.pages] == [(1, " exact text ")]


@pytest.mark.parametrize(("output", "state"), [
    (None, "not_returned"), ({"pages": []}, "empty"), ([], "unsupported"),
    ({"pages": [{"page_number": True, "markdown": "x"}]}, "unsupported"),
    ({"pages": [{"page_number": 0, "markdown": "x"}]}, "unsupported"),
    ({"pages": [{"page_number": 1, "error": "failed", "success": False}]}, "unsupported"),
    ({"pages": [{"page_number": 1, "markdown": "x", "success": False}]}, "unsupported"),
])
def test_optional_output_shape_is_not_invented(output, state):
    result = observe({"job": {"id": "pjb-fixture", "status": "COMPLETED"}, "markdown": output})
    assert result.markdown.state == state
    assert not result.markdown.pages
    assert bool(result.warnings) == (state == "unsupported")


@pytest.mark.parametrize(("credits", "actual"), [(0, Decimal(0)), (1.25, Decimal("1.25")), (None, None), (True, None), (-1, None), ("3", None)])
def test_only_observed_numeric_credits_become_actual_usage(credits, actual):
    result = observe({"job": {"id": "pjb-fixture", "status": "COMPLETED", "usage": {"credits": credits}}})
    assert result.usage.actual_credits == actual
    assert result.usage.estimated_credits is None
    assert result.usage.reconciliation == ("observed" if actual is not None else "pending")


def test_reported_version_never_comes_from_configuration_echo():
    result = observe({"job": {"id": "pjb-fixture", "status": "COMPLETED"}, "raw_parameters": {"version": "2026-09-28"}, "job_metadata": {"version": "2026-09-28"}})
    assert result.provider_version is None
    result = observe({"job": {"id": "pjb-fixture", "status": "COMPLETED", "version": "2026-09-28"}})
    assert result.provider_version == "2026-09-28"


@pytest.mark.parametrize("body", [
    {"job": {"id": "different", "status": "COMPLETED"}},
    {"job": {"id": "pjb-fixture", "status": "NEW"}},
    {"status": "COMPLETED", "id": "pjb-fixture"},
])
def test_unknown_poll_envelope_is_not_a_terminal_observation(body):
    with pytest.raises(ProviderError) as raised:
        observe(body)
    assert raised.value.code == "provider_invalid_response"


@pytest.mark.parametrize("identity", ["../escape", "", "pjb?key=secret"])
def test_poll_path_is_never_built_from_invalid_provider_id(identity):
    def handler(_):
        pytest.fail("invalid id must not send a request")

    with pytest.raises(ProviderError):
        asyncio.run(provider(handler).poll(identity))


def test_response_size_and_content_type_fail_closed_for_submit_and_poll():
    for method in ("submit", "poll"):
        for headers, content, limit in [({"content-type": "text/plain"}, b"{}", 100), ({"content-type": "application/json"}, b"{}", 1)]:
            value = provider(lambda _: httpx.Response(200, content=content, headers=headers), max_response_bytes=limit)
            with pytest.raises(ProviderError) as raised:
                asyncio.run(value.submit(b"source", "fixture.pdf", "application/pdf", SETTINGS) if method == "submit" else value.poll("pjb-fixture"))
            assert raised.value.ambiguous is (method == "submit")
