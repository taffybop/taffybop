"""P08-US07 grounded, budgeted, parser-safe review routing."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings, get_settings
from app.models import ParseResult
from app.services import pipeline
from app.services.deterministic_confidence import apply_deterministic_confidence
from app.services.feature_flags import shipping_flag_registry
from app.services.review_routing import (
    ReviewBudget,
    ReviewOutcome,
    ReviewOutcomeLedger,
    ReviewRuntime,
    ReviewSubmission,
    build_review_packets,
    route_parse_result_for_review,
    use_review_runtime,
)
from app.services.serializer import to_markdown, to_text
from app.services.telemetry import (
    InMemoryTelemetryExporter,
    TelemetryClient,
    TelemetryEvent,
    use_telemetry,
)
from tests.stories.phase_06.test_p06_us05_grounding import _fallback_chart


VALID_PDF = b"%PDF-1.7\n% review routing fixture\n"


class ReviewTestAdapter:
    """Explicit in-memory test double; no live review transport exists."""

    def __init__(
        self,
        *,
        status: str = "queued",
        fail: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self.status = status
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[object, str]] = []

    def submit(
        self,
        packet: object,
        *,
        idempotency_key: str,
    ) -> ReviewSubmission:
        self.calls.append((packet, idempotency_key))
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.fail:
            raise RuntimeError("private adapter failure")
        return ReviewSubmission(status=self.status)


class RaisingExporter:
    def export(self, _event: TelemetryEvent) -> None:
        raise RuntimeError("private exporter failure")


def _result(*, grounded: bool = True) -> ParseResult:
    item, _structure = _fallback_chart()
    if not grounded:
        item.pop("visual_structure")
    return ParseResult.model_validate(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "private-name.pdf",
                "mime_type": "application/pdf",
                "sha256": "0" * 64,
                "page_count": 1,
            },
            "pages": [
                {
                    "page_index": 1,
                    "page_number": 1,
                    "page_label": "iv",
                    "page_width": 612.0,
                    "page_height": 792.0,
                    "unit": "pt",
                    "success": True,
                    "items": [item],
                    "warnings": [],
                }
            ],
            "processing": {
                "engine": "test-double",
                "ocr_engine": "test-double",
                "ocr_languages": ["eng"],
                "duration_ms": 1,
            },
            "warnings": [],
        }
    )


def _confidence_result(*, grounded: bool = True) -> ParseResult:
    return apply_deterministic_confidence(
        _result(grounded=grounded),
        enabled=True,
    )


def _enabled_settings() -> Settings:
    return Settings(
        telemetry_enabled=True,
        telemetry_resources_enabled=True,
        telemetry_quality_enabled=True,
        deterministic_confidence_enabled=True,
        visual_confidence_enabled=True,
        review_escalation_enabled=True,
    )


def test_low_confidence_visual_creates_one_grounded_content_free_packet() -> None:
    packets, exhausted = build_review_packets(
        _confidence_result(),
        budget=ReviewBudget(),
    )

    assert exhausted is False
    assert len(packets) == 1
    packet = packets[0]
    assert packet.element_id == "chart-1"
    assert packet.physical_page == 1
    assert packet.printed_page_label == "iv"
    assert packet.region.model_dump(mode="json") == {
        "x": 10.0,
        "y": 20.0,
        "width": 100.0,
        "height": 80.0,
        "unit": "pt",
    }
    assert packet.evidence_ids
    assert packet.origin == "source"
    assert packet.reason == "visual_withheld"
    assert packet.confidence_dimensions[0].outcome == "withheld"
    encoded = json.dumps(packet.model_dump(mode="json"), sort_keys=True)
    for canary in (
        "private-name.pdf",
        "chart visible text",
        "chart caption",
        "2024",
        "password",
        "secret",
        "prompt",
        "crop",
    ):
        assert canary not in encoded


def test_ungrounded_candidate_never_calls_review_adapter() -> None:
    source = _confidence_result(grounded=False)
    adapter = ReviewTestAdapter()

    routed = route_parse_result_for_review(
        source,
        enabled=True,
        runtime=ReviewRuntime(adapter=adapter),
    )

    assert routed.status == "no_candidates"
    assert routed.result is source
    assert routed.packets == ()
    assert adapter.calls == []


def test_invalid_private_packet_preserves_valid_legacy_predecessor() -> None:
    raw = _result().model_dump(mode="json")
    raw["pages"][0]["page_label"] = ""
    source = apply_deterministic_confidence(
        ParseResult.model_validate(raw),
        enabled=True,
    )
    adapter = ReviewTestAdapter()

    routed = route_parse_result_for_review(
        source,
        enabled=True,
        runtime=ReviewRuntime(adapter=adapter),
    )

    assert routed.status == "no_candidates"
    assert routed.result is source
    assert routed.packets == ()
    assert routed.adapter_calls == 0
    assert adapter.calls == []


def test_budget_exhaustion_falls_back_without_adapter_call() -> None:
    source = _confidence_result()
    adapter = ReviewTestAdapter()
    budget = ReviewBudget(
        max_packets=1,
        max_regions=1,
        max_items=1,
        max_bytes=1_024,
        max_cost_units=1,
        cost_per_packet=2,
    )

    routed = route_parse_result_for_review(
        source,
        enabled=True,
        runtime=ReviewRuntime(adapter=adapter, budget=budget),
    )

    assert routed.status == "budget_exhausted"
    assert routed.result is source
    assert routed.packets == ()
    assert adapter.calls == []


def test_unavailable_route_is_deterministic_and_preserves_predecessor() -> None:
    source = _confidence_result()

    first = route_parse_result_for_review(source, enabled=True)
    second = route_parse_result_for_review(source, enabled=True)

    assert first.status == second.status == "unavailable"
    assert first.result is second.result is source
    assert first.packets == second.packets
    assert first.adapter_calls == second.adapter_calls == 0


@pytest.mark.parametrize("mode", ["failure", "timeout"])
def test_failed_or_timed_out_adapter_never_fails_parsing(mode: str) -> None:
    source = _confidence_result()
    adapter = ReviewTestAdapter(
        fail=mode == "failure",
        delay_seconds=0.05 if mode == "timeout" else 0.0,
    )

    routed = route_parse_result_for_review(
        source,
        enabled=True,
        runtime=ReviewRuntime(adapter=adapter, timeout_ms=5),
    )

    assert routed.status == ("failed" if mode == "failure" else "timeout")
    assert routed.result is source
    assert routed.adapter_calls == 1
    assert len(adapter.calls) == 1


def test_success_routes_once_and_public_status_exposes_no_packet_metadata() -> None:
    source = _confidence_result()
    adapter = ReviewTestAdapter()

    routed = route_parse_result_for_review(
        source,
        enabled=True,
        runtime=ReviewRuntime(adapter=adapter),
    )

    assert routed.status == "queued"
    assert routed.result is not source
    assert routed.adapter_calls == 1
    assert len(adapter.calls) == 1
    packet, idempotency_key = adapter.calls[0]
    assert idempotency_key == routed.packets[0].packet_id
    assert packet == routed.packets[0]
    public = (routed.result.model_extra or {})["review_routing"]
    assert public == {
        "schema_version": "1.0",
        "policy_id": "p08-grounded-review-v1",
        "status": "queued",
        "packet_count": 1,
        "total_cost_units": 1,
    }
    encoded = json.dumps(public, sort_keys=True)
    assert "packet_id" not in encoded
    assert "element_id" not in encoded
    assert "evidence" not in encoded
    assert "region" not in encoded
    assert "page_label" not in encoded
    assert to_markdown(routed.result) == to_markdown(source)
    assert to_text(routed.result) == to_text(source)


def test_outcome_recording_is_idempotent_and_never_changes_source_truth() -> None:
    source = _confidence_result()
    before = source.model_dump(mode="json", exclude_unset=True)
    packet = build_review_packets(source, budget=ReviewBudget())[0][0]
    ledger = ReviewOutcomeLedger(max_outcomes=2)
    outcome = ReviewOutcome(
        outcome_id="outcome-1",
        packet_id=packet.packet_id,
        decision="correct",
    )

    assert ledger.record(outcome) is True
    assert ledger.record(outcome) is False
    assert ledger.outcomes == (outcome,)
    assert source.model_dump(mode="json", exclude_unset=True) == before
    with pytest.raises(ValueError, match="idempotency conflict"):
        ledger.record(outcome.model_copy(update={"decision": "reject"}))
    with pytest.raises(ValueError, match="already has an outcome"):
        ledger.record(
            ReviewOutcome(
                outcome_id="outcome-2",
                packet_id=packet.packet_id,
                decision="accept",
            )
        )


def test_review_telemetry_is_bounded_private_and_exporter_failure_isolated() -> None:
    source = _confidence_result()
    adapter = ReviewTestAdapter()
    exporter = InMemoryTelemetryExporter()
    telemetry = TelemetryClient(enabled=True, exporter=exporter)

    with use_telemetry(telemetry):
        routed = route_parse_result_for_review(
            source,
            enabled=True,
            runtime=ReviewRuntime(adapter=adapter),
        )
    assert telemetry.flush(1.0)
    assert routed.status == "queued"
    assert len(exporter.events) == 1
    event = exporter.events[0]
    assert event.name == "parser.review.route"
    assert dict(event.labels) == {
        "decision": "route",
        "outcome": "accepted",
        "reason": "supported",
        "route": "review",
    }
    encoded = event.canonical_bytes().decode("utf-8")
    assert "chart-1" not in encoded
    assert "private-name" not in encoded
    assert "visual-evidence" not in encoded
    telemetry.close()

    failing = TelemetryClient(enabled=True, exporter=RaisingExporter())
    with use_telemetry(failing):
        still_routed = route_parse_result_for_review(
            source,
            enabled=True,
            runtime=ReviewRuntime(adapter=ReviewTestAdapter()),
        )
    assert failing.flush(1.0)
    assert still_routed.status == "queued"
    assert failing.stats.exporter_failures == 1
    failing.close()


def test_flag_off_and_confidence_rollback_send_nothing_and_are_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result()
    expected = baseline.model_dump(mode="json", exclude_unset=True)
    adapter = ReviewTestAdapter()
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: baseline,
    )

    with use_review_runtime(ReviewRuntime(adapter=adapter)):
        disabled = pipeline.parse_document(VALID_PDF, "sample.pdf", Settings())
    rolled_back_settings = shipping_flag_registry().rollback(
        _enabled_settings(),
        "confidence",
    )
    with use_review_runtime(ReviewRuntime(adapter=adapter)):
        restored = pipeline.parse_document(
            VALID_PDF,
            "sample.pdf",
            rolled_back_settings,
        )

    assert disabled is restored is baseline
    assert disabled.model_dump(mode="json", exclude_unset=True) == expected
    assert rolled_back_settings.review_escalation_enabled is False
    assert adapter.calls == []


def test_public_api_is_additive_on_success_and_exact_when_default_off(
    api_app: object,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _result()
    expected = ParseResult.model_validate(
        baseline.model_dump(mode="json")
    ).model_dump(mode="json", exclude_unset=True)
    adapter = ReviewTestAdapter()
    monkeypatch.setattr(
        pipeline,
        "_parse_document_without_stage_telemetry",
        lambda *_args, **_kwargs: _result(),
    )
    monkeypatch.setattr(
        api_module,
        "_parse_document",
        lambda data, filename, settings: pipeline.parse_document(
            data,
            filename,
            settings,
        ),
    )

    api_app.dependency_overrides[get_settings] = _enabled_settings  # type: ignore[attr-defined]
    with use_review_runtime(ReviewRuntime(adapter=adapter)):
        enabled = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
        )
    api_app.dependency_overrides[get_settings] = Settings  # type: ignore[attr-defined]
    with use_review_runtime(ReviewRuntime(adapter=adapter)):
        disabled = client.post(
            "/v1/parse?output_format=json",
            files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
        )

    assert enabled.status_code == disabled.status_code == 200
    assert enabled.json()["review_routing"]["status"] == "queued"
    assert disabled.json() == expected
    assert "review_routing" not in disabled.json()
    assert len(adapter.calls) == 1


def test_public_schema_is_unchanged_and_default_runtime_has_zero_live_calls() -> None:
    schema = deepcopy(ParseResult.model_json_schema())
    source = _confidence_result()

    routed = route_parse_result_for_review(source, enabled=True)

    assert routed.status == "unavailable"
    assert routed.adapter_calls == 0
    assert ParseResult.model_json_schema() == schema
    assert "review_routing" not in schema.get("properties", {})
    assert Settings().review_escalation_enabled is False
