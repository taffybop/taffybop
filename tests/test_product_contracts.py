"""Offline v2 boundary checks; no routes, persistence or provider quality claims."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.product.contracts import (
    Artifact, Document, DocumentList, Job, Page, PageSection,
    ParseRequest, ParseResult, ParseSettings, Usage,
)
from app.product.export_contracts import serialized_schema

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
ID = UUID("c904fe69-8826-4c81-ad52-c848244b227c")
SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28")


def artifact(**changes):
    return Artifact(id=ID, sha256="a" * 64, size_bytes=123, media_type="application/json", **changes)


def document_data():
    return dict(id=ID, display_name="synthetic.pdf", source=Artifact(
        id=ID, sha256="b" * 64, size_bytes=123, media_type="application/pdf",
    ), page_count=1, created_at=NOW)


def job_data(**changes):
    return dict(dict(id=ID, document_id=ID, status="queued", settings=SETTINGS,
        created_at=NOW, updated_at=NOW), **changes)


def result_data():
    return dict(id=ID, document_id=ID, job_id=ID, created_at=NOW, settings=SETTINGS,
        raw=artifact(), markdown=PageSection(state="not_returned"),
        text=PageSection(state="unsupported"))


def test_request_rejects_owner_provider_settings_and_confidence_inputs():
    with pytest.raises(ValidationError):
        ParseRequest()
    assert ParseRequest(mode="fast").mode == "fast"
    for field, value in [("owner_id", str(ID)), ("api_key", "not-a-real-key"),
                         ("requested_version", "latest"), ("confidence", 0.99)]:
        with pytest.raises(ValidationError):
            ParseRequest.model_validate({"mode": "fast", field: value})
    with pytest.raises(ValidationError):
        ParseRequest(mode="agentic_plus")


@pytest.mark.parametrize("version", ["latest", "2026-02-30", "2026-9-28", "", 2026])
def test_settings_require_a_real_dated_pin(version):
    with pytest.raises(ValidationError):
        ParseSettings(mode="fast", requested_version=version)


def test_resource_json_roundtrip_and_schema_version():
    document = Document(**document_data())
    listing = DocumentList(documents=(document,), next_cursor=None)
    assert DocumentList.model_validate_json(listing.model_dump_json()) == listing
    assert listing.model_dump(mode="json")["schema_version"] == "2.0"
    with pytest.raises(ValidationError):
        Document(**document_data(), schema_version="1.0")


@pytest.mark.parametrize("name", ["../test.pdf", "C:\\test.pdf", "a\nb.pdf", 'a"b.pdf', "..", ""])
def test_document_names_are_display_names_not_paths(name):
    value = document_data()
    value["display_name"] = name
    with pytest.raises(ValidationError):
        Document(**value)


@pytest.mark.parametrize("changes", [
    {"created_at": datetime(2026, 11, 11)},
    {"state": "deleted"},
    {"state": "expired"},
    {"deleted_at": NOW},
    {"expires_at": NOW - timedelta(seconds=1)},
    {"page_count": True},
    {"page_count": 11},
])
def test_invalid_document_metadata_is_rejected(changes):
    with pytest.raises(ValidationError):
        Document(**dict(document_data(), **changes))


def test_image_cannot_claim_multiple_pages_or_json_as_source():
    for media_type, pages in [("image/png", 2), ("application/json", 1)]:
        value = document_data()
        value.update(source=Artifact(id=ID, sha256="b" * 64, size_bytes=123, media_type=media_type), page_count=pages)
        with pytest.raises(ValidationError):
            Document(**value)


def test_unknown_usage_is_not_zero_and_estimates_are_separate():
    pending = Usage(estimated_credits=Decimal("3"), estimate_price_version="reviewed-list-v1")
    assert pending.actual_credits is None
    assert pending.reconciliation == "pending"
    observed_zero = Usage(actual_credits=Decimal("0"), reconciliation="observed")
    assert observed_zero.actual_credits == 0
    assert Usage.model_validate_json(pending.model_dump_json()) == pending


@pytest.mark.parametrize("changes", [
    {"actual_credits": "0"},
    {"reconciliation": "observed"},
    {"estimated_credits": "3"},
    {"estimate_price_version": "list-v1"},
    {"actual_credits": "-1", "reconciliation": "observed"},
    {"actual_credits": "NaN", "reconciliation": "observed"},
    {"actual_credits": "Infinity", "reconciliation": "observed"},
])
def test_usage_does_not_invent_or_conflate_observations(changes):
    with pytest.raises(ValidationError):
        Usage(**changes)


def test_submission_unknown_and_cancellation_request_are_nonterminal():
    unknown = Job(**job_data(status="submission_unknown", started_at=NOW))
    cancel = Job(**job_data(status="cancel_requested", cancellation_requested_at=NOW))
    assert unknown.finished_at is None and unknown.result_id is None
    assert not cancel.cancellation_confirmed and cancel.finished_at is None
    # A provider can cancel independently of a local request.
    cancelled = Job(**job_data(status="cancelled", finished_at=NOW,
        cancellation_confirmed=True, raw_response=artifact()))
    assert cancelled.cancellation_requested_at is None


def test_success_can_precede_observed_billing_and_failure_retains_raw():
    success = Job(**job_data(status="succeeded", started_at=NOW, finished_at=NOW,
        result_id=ID, raw_response=artifact()))
    assert success.usage.reconciliation == "pending"
    failed = Job(**job_data(status="failed", finished_at=NOW, raw_response=artifact(),
        error={"code": "provider_failed", "message": "The provider could not parse this document."}))
    assert failed.raw_response == success.raw_response
    assert failed.result_id is None


@pytest.mark.parametrize("changes", [
    {"status": "succeeded", "finished_at": NOW},
    {"status": "failed", "finished_at": NOW},
    {"status": "cancelled", "finished_at": NOW},
    {"status": "cancel_requested"},
    {"status": "running"},
    {"status": "submission_unknown"},
    {"finished_at": NOW},
    {"result_id": ID},
    {"raw_response": artifact()},
    {"cancellation_confirmed": True},
    {"attempt": True},
    {"updated_at": NOW - timedelta(seconds=1)},
])
def test_job_cannot_claim_an_inconsistent_outcome(changes):
    with pytest.raises(ValidationError):
        Job(**job_data(**changes))


def test_formats_preserve_independent_order_duplicate_page_ids_and_empty_content():
    markdown = PageSection(state="available", pages=(
        Page(page_number=2, content=" second\n"),
        Page(page_number=1, content=""),
        Page(page_number=2, content="é | unchanged"),
    ))
    result = ParseResult(**dict(result_data(), markdown=markdown))
    assert [page.page_number for page in result.markdown.pages] == [2, 1, 2]
    assert result.markdown.pages[0].content == " second\n"
    assert result.markdown.pages[1].content == ""
    assert result.text.state == "unsupported"
    assert result.provider_version is None  # requested pin is not an observed version
    assert ParseResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("state,pages", [
    ("available", ()), ("empty", (Page(page_number=1, content=""),)),
    ("not_returned", (Page(page_number=1, content="text"),)),
])
def test_absent_empty_unsupported_and_available_remain_distinct(state, pages):
    with pytest.raises(ValidationError):
        PageSection(state=state, pages=pages)


def test_result_rejects_non_json_raw_and_mutation():
    value = result_data()
    value["raw"] = document_data()["source"]
    with pytest.raises(ValidationError):
        ParseResult(**value)
    result = ParseResult(**result_data())
    with pytest.raises(ValidationError):
        result.settings.mode = "agentic"
    with pytest.raises(ValidationError):
        result.raw.sha256 = "b" * 64
    with pytest.raises(ValidationError):
        result.warnings = ("changed",)


def test_reviewed_schema_snapshot_matches_models():
    snapshot = Path(__file__).resolve().parents[1] / "tracker/parse-extract-v1/contracts/v2.schema.json"
    assert snapshot.read_text(encoding="utf-8") == serialized_schema()
