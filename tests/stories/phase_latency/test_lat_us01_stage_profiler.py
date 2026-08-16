"""LAT-US01 deterministic profiler and paired-gate behavior."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.benchmarks import latency_worker
from tests.benchmarks.latency_campaign import (
    build_interleaved_plan,
    evaluate_campaign,
    nearest_rank,
    summarize_latency,
)
from tests.benchmarks.latency_contracts import (
    AttemptStatus,
    LatencyAttempt,
    LatencyCampaign,
    StageName,
    StageTrace,
    SystemName,
)
from tests.benchmarks.latency_instrumentation import ExternalStageCollector
from tests.benchmarks.latency_runner import main, run_external_candidate_attempt
from tests.fixtures.phase_latency.factory import (
    campaign,
    process_tree,
    source,
    stage_trace,
)


REPOSITORY = Path(__file__).resolve().parents[3]


def test_nearest_rank_is_empirical_inclusive_and_never_interpolates() -> None:
    values = (50, 10, 40, 20, 30)
    assert nearest_rank(values, 0.50) == 30
    assert nearest_rank(values, 0.95) == 50
    assert nearest_rank(values, 1.00) == 50
    assert summarize_latency(values).model_dump() == {
        "count": 5,
        "minimum_ns": 10,
        "p50_ns": 30,
        "p95_ns": 50,
        "maximum_ns": 50,
    }
    assert nearest_rank((1, 2, 3, 4, 5, 6), 0.50) == 3
    assert nearest_rank((1, 2, 3, 4, 5, 6), 0.95) == 6


@pytest.mark.parametrize(
    ("values", "percentile", "error"),
    [
        ((), 0.5, ValueError),
        ((1,), 0.0, ValueError),
        ((1,), 1.01, ValueError),
        ((1,), float("nan"), ValueError),
        ((1,), True, TypeError),
        ((True,), 0.5, TypeError),
        ((0,), 0.5, ValueError),
    ],
)
def test_nearest_rank_rejects_ambiguous_or_nonpositive_inputs(
    values: tuple[int, ...],
    percentile: float,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        nearest_rank(values, percentile)


def test_five_sample_plan_is_balanced_interleaved_and_immutable() -> None:
    plan = build_interleaved_plan(("ny-timetable",), sample_count=5)
    assert len(plan) == 10
    assert tuple(slot.order_index for slot in plan) == tuple(range(1, 11))
    assert tuple(slot.system for slot in plan[:4]) == (
        SystemName.CANDIDATE,
        SystemName.LLAMAPARSE,
        SystemName.CANDIDATE,
        SystemName.LLAMAPARSE,
    )
    assert {
        system: sum(slot.system is system for slot in plan) for system in SystemName
    } == {SystemName.CANDIDATE: 5, SystemName.LLAMAPARSE: 5}


def test_multi_case_plan_is_round_major_but_each_case_strictly_alternates() -> None:
    plan = build_interleaved_plan(("ny-timetable", "postal-10k"), sample_count=5)
    assert tuple((slot.case_id, slot.system) for slot in plan[:4]) == (
        ("ny-timetable", SystemName.CANDIDATE),
        ("postal-10k", SystemName.CANDIDATE),
        ("ny-timetable", SystemName.LLAMAPARSE),
        ("postal-10k", SystemName.LLAMAPARSE),
    )
    for case_id in ("ny-timetable", "postal-10k"):
        assert (
            tuple(slot.system for slot in plan if slot.case_id == case_id)
            == (
                SystemName.CANDIDATE,
                SystemName.LLAMAPARSE,
            )
            * 5
        )


def test_campaign_contract_rejects_case_contiguous_non_batch_schedule() -> None:
    value = campaign(case_ids=("ny-timetable", "postal-10k")).model_dump(mode="json")
    paired = list(zip(value["plan"], value["attempts"], strict=True))
    paired.sort(
        key=lambda item: (
            item[0]["case_id"],
            item[0]["pair_index"],
            0 if item[0]["system"] == "candidate" else 1,
        )
    )
    chronology_base = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    for order_index, (slot, attempt) in enumerate(paired, start=1):
        started_at = chronology_base + timedelta(seconds=2 * order_index)
        completed_at = started_at + timedelta(seconds=1)
        slot["order_index"] = order_index
        attempt["order_index"] = order_index
        attempt["started_at_utc"] = started_at.isoformat().replace("+00:00", "Z")
        attempt["completed_at_utc"] = completed_at.isoformat().replace("+00:00", "Z")
        if attempt["provider_total_latency"] is not None:
            attempt["provider_total_latency"]["observed_at_utc"] = attempt[
                "completed_at_utc"
            ]
    value["plan"] = [item[0] for item in paired]
    value["attempts"] = [item[1] for item in paired]
    with pytest.raises(ValidationError, match="round-major batches"):
        LatencyCampaign.model_validate(value)


def test_stage_trace_covers_complete_response_and_keeps_diagnostics_nested() -> None:
    trace = stage_trace(20_000_000)
    assert trace.authoritative_total_ns == 20_000_000
    assert trace.spans[0].name.value == "request_total"
    assert trace.spans[-1].name.value == "api.response_build"
    assert all(
        trace.spans[0].started_monotonic_ns
        <= span.started_monotonic_ns
        <= span.ended_monotonic_ns
        <= trace.spans[0].ended_monotonic_ns
        for span in trace.spans
    )

    value = trace.model_dump(mode="json")
    value["spans"][2]["ended_monotonic_ns"] = (
        value["spans"][0]["ended_monotonic_ns"] + 1
    )
    with pytest.raises(ValidationError, match="inside its parent"):
        StageTrace.model_validate(value)


def test_authoritative_total_is_an_uninstrumented_complete_response_measure() -> None:
    attempt = campaign().attempts[0]
    assert attempt.process_tree is not None
    assert attempt.stage_trace is not None
    assert attempt.instrumentation_manifest is not None
    assert attempt.configuration.total_latency_metric == "asgi_complete_response_bytes"
    assert attempt.total_latency_ns == (
        attempt.process_tree.request_ended_monotonic_ns
        - attempt.process_tree.request_started_monotonic_ns
    )
    assert attempt.diagnostic_total_latency_ns == (
        attempt.stage_trace.authoritative_total_ns
    )
    assert attempt.observer_delta_ns == (
        attempt.diagnostic_total_latency_ns - attempt.total_latency_ns
    )
    assert attempt.observer_adjustment_applied is False
    assert attempt.instrumentation_manifest.authoritative_total_policy == (
        "separate_uninstrumented_twin_no_observer_subtraction"
    )

    diagnostic_is_slower = attempt.model_dump(mode="json")
    diagnostic_is_slower["diagnostic_total_latency_ns"] += 1
    diagnostic_is_slower["observer_delta_ns"] += 1
    diagnostic_is_slower["stage_trace"]["authoritative_total_ns"] += 1
    diagnostic_is_slower["stage_trace"]["collector_finished_monotonic_ns"] += 1
    diagnostic_is_slower["stage_trace"]["spans"][0]["ended_monotonic_ns"] += 1
    diagnostic_is_slower["stage_trace"]["unattributed_remainder_ns"] += 1
    diagnostic_is_slower["diagnostic_process_tree"][
        "request_ended_monotonic_ns"
    ] += 1
    retained = LatencyAttempt.model_validate(diagnostic_is_slower)
    assert retained.total_latency_ns == attempt.total_latency_ns
    assert retained.diagnostic_total_latency_ns == attempt.total_latency_ns + 1
    assert retained.observer_delta_ns == 1

    adjusted = deepcopy(diagnostic_is_slower)
    adjusted["observer_adjustment_applied"] = True
    with pytest.raises(ValidationError):
        LatencyAttempt.model_validate(adjusted)


def test_complete_response_reader_materializes_the_last_byte_before_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def complete_response_clock() -> int:
        events.append("complete-response-boundary")
        return 4242

    monkeypatch.setattr(latency_worker.time, "perf_counter_ns", complete_response_clock)

    class Response:
        status_code = 200
        headers = {"content-type": "application/json; charset=utf-8"}

        def iter_bytes(self) -> Iterator[bytes]:
            events.append("first-byte")
            yield b"{"
            events.append("last-byte")
            yield b"}"
            events.append("iterator-exhausted")

    class Stream:
        def __enter__(self) -> Response:
            events.append("context-enter")
            return Response()

        def __exit__(self, *_args: object) -> None:
            events.append("context-exit")

    class Client:
        def stream(self, method: str, path: str, **_kwargs: object) -> Stream:
            assert (method, path) == ("POST", "/v1/parse")
            return Stream()

    status, media_type, response_bytes, complete_response_ns = (
        latency_worker._perform_request(
            Client(),
            source=source(),
            data=b"%PDF-1.7 bounded control",
            mime="application/pdf",
            output_format="json",
        )
    )
    events.append("request-returned")
    assert (status, media_type, response_bytes) == (200, "application/json", b"{}")
    assert complete_response_ns == 4242
    assert events == [
        "context-enter",
        "first-byte",
        "last-byte",
        "iterator-exhausted",
        "complete-response-boundary",
        "context-exit",
        "request-returned",
    ]


def test_external_twin_retains_output_outcome_cache_and_lifecycle_parity() -> None:
    slot = build_interleaved_plan(("synthetic-story-twin",), sample_count=5)[0]
    attempt = run_external_candidate_attempt(
        slot=slot,
        source_path=(
            REPOSITORY / "benchmark-expertmodeldata" / "insurance-acord.pdf"
        ),
        attempt_id="synthetic-story-twin",
        output_format="markdown",
        timeout_seconds=10.0,
        workspace=REPOSITORY,
        synthetic_fixture_mode="mock-testclient",
    )
    assert attempt.status is AttemptStatus.SUCCESS
    assert attempt.evidence_complete is True
    assert attempt.output is not None
    assert attempt.diagnostic_output is not None
    assert attempt.output.semantic_sha256 == attempt.diagnostic_output.semantic_sha256
    assert attempt.output.media_type == attempt.diagnostic_output.media_type
    assert attempt.authoritative_cache_state == attempt.diagnostic_cache_state
    assert attempt.configuration.worker_lifecycle.value == (
        "fresh_process_request_cold_after_app_startup"
    )
    assert attempt.twin_order == "authoritative_then_diagnostic"
    assert attempt.observer_adjustment_applied is False
    assert attempt.instrumentation_manifest is not None
    assert attempt.instrumentation_manifest.hosted_calls == 0

    output_drift = campaign().attempts[0].model_dump(mode="json")
    output_drift["diagnostic_output"]["semantic_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="semantic output parity"):
        LatencyAttempt.model_validate(output_drift)

    incomplete_outcome = campaign().attempts[0].model_dump(mode="json")
    incomplete_outcome["diagnostic_output"] = None
    with pytest.raises(ValidationError, match="complete twin evidence"):
        LatencyAttempt.model_validate(incomplete_outcome)

    cache_drift = campaign().attempts[0].model_dump(mode="json")
    cache_drift["diagnostic_cache_state"][
        "converter_cache_entries_after_request"
    ] += 1
    with pytest.raises(ValidationError, match="cache state differs"):
        LatencyAttempt.model_validate(cache_drift)


def test_external_stage_lifecycle_and_cardinality_fail_closed() -> None:
    regressing = ExternalStageCollector(clock=lambda: 99)
    regressing.start(started_ns=100)
    with pytest.raises(RuntimeError, match="clock regressed"):
        regressing.begin("api-parse-dispatch", StageName.API_PARSE_DISPATCH)

    missing_close = ExternalStageCollector(clock=lambda: 110)
    missing_close.start(started_ns=100)
    missing_close.begin("api-parse-dispatch", StageName.API_PARSE_DISPATCH)
    with pytest.raises(RuntimeError, match="unclosed spans"):
        missing_close.finish(finished_ns=120)

    duplicate_close = ExternalStageCollector(clock=lambda: 110)
    duplicate_close.start(started_ns=100)
    opened = duplicate_close.begin(
        "api-parse-dispatch", StageName.API_PARSE_DISPATCH
    )
    duplicate_close.close(opened, ended_ns=115)
    with pytest.raises(RuntimeError, match="closed more than once"):
        duplicate_close.close(opened, ended_ns=116)

    missing_required = campaign().attempts[0].model_dump(mode="json")
    missing_required["stage_trace"]["spans"].pop(1)
    missing_required["stage_trace"]["attributed_top_level_union_ns"] -= 1_000_000
    missing_required["stage_trace"]["unattributed_remainder_ns"] += 1_000_000
    with pytest.raises(ValidationError, match="cardinality policy"):
        LatencyAttempt.model_validate(missing_required)

    duplicate_required = campaign().attempts[0].model_dump(mode="json")
    duplicate = deepcopy(duplicate_required["stage_trace"]["spans"][1])
    duplicate["span_id"] = "dispatch-copy"
    duplicate_required["stage_trace"]["spans"].insert(2, duplicate)
    with pytest.raises(ValidationError, match="cardinality policy"):
        LatencyAttempt.model_validate(duplicate_required)

    degraded = campaign().attempts[0].model_dump(mode="json")
    degraded["stage_trace"]["spans"][1]["status"] = "error"
    degraded["stage_trace"]["spans"][1]["failure_code"] = "external_stage_error"
    with pytest.raises(ValidationError, match="diagnostic stage was degraded"):
        LatencyAttempt.model_validate(degraded)


def test_cli_plan_emits_the_exact_interleaved_schedule(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["plan", "--case", "ny-timetable", "--samples", "5"]) == 0
    decoded = json.loads(capsys.readouterr().out)
    assert len(decoded) == 10
    assert [item["system"] for item in decoded[:4]] == [
        "candidate",
        "llamaparse",
        "candidate",
        "llamaparse",
    ]


def test_a_retained_candidate_failure_blocks_quantiles_and_the_case() -> None:
    retained = campaign(
        failures={
            ("ny-timetable", 3, SystemName.CANDIDATE): AttemptStatus.TIMEOUT,
        }
    )
    gate = evaluate_campaign(retained)
    assert gate.passed is False
    assert gate.cases[0].candidate_failure_count == 1
    assert gate.cases[0].candidate is None
    assert gate.cases[0].llamaparse is None
    assert gate.cases[0].failure_codes == ("candidate_attempt_failed",)

    missing = retained.model_dump(mode="json")
    del missing["attempts"][4]
    with pytest.raises(ValidationError, match="at least 10|planned slot"):
        LatencyCampaign.model_validate(missing)


def test_p50_and_p95_are_both_independent_blocking_comparisons() -> None:
    passing = evaluate_campaign(campaign())
    assert passing.passed is True
    assert passing.cases[0].candidate is not None
    assert passing.cases[0].llamaparse is not None
    assert passing.cases[0].candidate.p50_ns == 100_000_000
    assert passing.cases[0].candidate.p95_ns == 120_000_000

    p50_failure = evaluate_campaign(
        campaign(
            candidate_ns=(
                80_000_000,
                130_000_000,
                140_000_000,
                150_000_000,
                160_000_000,
            ),
            llamaparse_ns=(
                100_000_000,
                110_000_000,
                120_000_000,
                200_000_000,
                210_000_000,
            ),
        )
    )
    assert "candidate_p50_exceeds_llamaparse" in p50_failure.cases[0].failure_codes

    p95_failure = evaluate_campaign(
        campaign(
            candidate_ns=(
                80_000_000,
                90_000_000,
                100_000_000,
                110_000_000,
                999_000_000,
            ),
            llamaparse_ns=(
                100_000_000,
                110_000_000,
                120_000_000,
                130_000_000,
                140_000_000,
            ),
        )
    )
    assert p95_failure.cases[0].failure_codes == ("candidate_p95_exceeds_llamaparse",)


def test_one_slow_case_cannot_be_hidden_by_another_case() -> None:
    value = campaign(case_ids=("ny-timetable", "postal-10k")).model_dump(mode="json")
    for attempt in value["attempts"]:
        if attempt["case_id"] != "postal-10k" or attempt["system"] != "candidate":
            continue
        attempt["total_latency_ns"] *= 10
        attempt["diagnostic_total_latency_ns"] = attempt["total_latency_ns"]
        attempt["observer_delta_ns"] = 0
        attempt["stage_trace"]["authoritative_total_ns"] = attempt["total_latency_ns"]
        attempt["stage_trace"]["spans"][0]["ended_monotonic_ns"] = (
            attempt["stage_trace"]["spans"][0]["started_monotonic_ns"]
            + attempt["total_latency_ns"]
        )
        attempt["stage_trace"]["collector_finished_monotonic_ns"] = attempt[
            "stage_trace"
        ]["spans"][0]["ended_monotonic_ns"]
        attempt["stage_trace"]["post_collector_duration_ns"] = 0
        attempt["stage_trace"]["spans"][2]["ended_monotonic_ns"] = (
            attempt["stage_trace"]["spans"][0]["ended_monotonic_ns"] - 1_000_000
        )
        attempt["stage_trace"]["spans"][3]["started_monotonic_ns"] = (
            attempt["stage_trace"]["spans"][0]["ended_monotonic_ns"] - 1_000_000
        )
        attempt["stage_trace"]["spans"][3]["ended_monotonic_ns"] = attempt[
            "stage_trace"
        ]["spans"][0]["ended_monotonic_ns"]
        attempt["stage_trace"]["attributed_top_level_union_ns"] = attempt[
            "total_latency_ns"
        ]
        attempt["stage_trace"]["unattributed_remainder_ns"] = 0
        attempt["process_tree"] = process_tree(attempt["total_latency_ns"]).model_dump(
            mode="json"
        )
        attempt["diagnostic_process_tree"] = deepcopy(attempt["process_tree"])
    chronology_base = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    for index, attempt in enumerate(value["attempts"]):
        started_at = chronology_base + timedelta(seconds=3 * index)
        completed_at = started_at + timedelta(seconds=2)
        attempt["started_at_utc"] = started_at.isoformat().replace("+00:00", "Z")
        attempt["completed_at_utc"] = completed_at.isoformat().replace("+00:00", "Z")
        if attempt["provider_total_latency"] is not None:
            attempt["provider_total_latency"]["observed_at_utc"] = attempt[
                "completed_at_utc"
            ]
    gate = evaluate_campaign(LatencyCampaign.model_validate(value))
    assert [case.case_id for case in gate.cases] == ["ny-timetable", "postal-10k"]
    assert gate.cases[0].passed is True
    assert gate.cases[1].passed is False
    assert gate.passed is False
    assert "corpus" not in gate.model_dump(mode="json")


def test_replacement_success_cannot_reuse_a_failed_plan_slot() -> None:
    retained = campaign(
        failures={
            ("ny-timetable", 2, SystemName.LLAMAPARSE): AttemptStatus.ERROR,
        }
    )
    value = deepcopy(retained.model_dump(mode="json"))
    value["attempts"].append(deepcopy(value["attempts"][-1]))
    value["attempts"][-1]["attempt_id"] = "replacement-success"
    with pytest.raises(ValidationError, match="exactly one attempt"):
        LatencyCampaign.model_validate(value)
