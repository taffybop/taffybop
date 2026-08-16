"""Deterministic helpers for evaluating paired LlamaParse latency evidence."""

from __future__ import annotations

import math
from itertools import islice
from collections.abc import Iterable, Sequence

from tests.benchmarks.latency_contracts import (
    MINIMUM_PAIRED_SAMPLES,
    AttemptSlot,
    AttemptStatus,
    CampaignLatencyGate,
    CaseLatencyGate,
    LatencyAttempt,
    LatencyCampaign,
    LatencyDistribution,
    SystemName,
    model_sha256,
)


def nearest_rank(values: Sequence[int], percentile: float) -> int:
    """Return an empirical inclusive nearest-rank quantile without interpolation."""

    if not values:
        raise ValueError("nearest-rank requires at least one sample")
    if isinstance(percentile, bool) or not isinstance(percentile, (int, float)):
        raise TypeError("percentile must be a finite number")
    numeric_percentile = float(percentile)
    if not math.isfinite(numeric_percentile) or not 0 < numeric_percentile <= 1:
        raise ValueError("percentile must be finite and in (0, 1]")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise TypeError("latency samples must be integer nanoseconds")
    if any(value <= 0 for value in values):
        raise ValueError("latency samples must be positive")
    ordered = sorted(values)
    index = math.ceil(numeric_percentile * len(ordered)) - 1
    return ordered[index]


def summarize_latency(values: Sequence[int]) -> LatencyDistribution:
    if not values:
        raise ValueError("latency distribution requires samples")
    ordered = sorted(values)
    return LatencyDistribution(
        count=len(ordered),
        minimum_ns=ordered[0],
        p50_ns=nearest_rank(ordered, 0.50),
        p95_ns=nearest_rank(ordered, 0.95),
        maximum_ns=ordered[-1],
    )


def build_interleaved_plan(
    case_ids: Iterable[str],
    *,
    sample_count: int = MINIMUM_PAIRED_SAMPLES,
) -> tuple[AttemptSlot, ...]:
    """Build fixed round-major C/L batches with strict per-case alternation."""

    if isinstance(sample_count, bool) or not isinstance(sample_count, int):
        raise TypeError("sample_count must be an integer")
    if not MINIMUM_PAIRED_SAMPLES <= sample_count <= 50:
        raise ValueError("sample_count must be between 5 and 50")
    normalized = tuple(islice(case_ids, 101))
    if len(normalized) > 100:
        raise ValueError("campaign case count exceeds its bound")
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("case IDs must be a non-empty unique sequence")
    slots: list[AttemptSlot] = []
    order = 1
    for pair_index in range(1, sample_count + 1):
        for system in (SystemName.CANDIDATE, SystemName.LLAMAPARSE):
            for case_id in normalized:
                slots.append(
                    AttemptSlot(
                        slot_id=f"{case_id}-p{pair_index:02d}-{system.value}",
                        order_index=order,
                        case_id=case_id,
                        pair_index=pair_index,
                        system=system,
                    )
                )
                order += 1
    return tuple(slots)


def _case_gate(case_id: str, attempts: Sequence[LatencyAttempt]) -> CaseLatencyGate:
    candidate = tuple(item for item in attempts if item.system is SystemName.CANDIDATE)
    llama = tuple(item for item in attempts if item.system is SystemName.LLAMAPARSE)
    if len(candidate) != len(llama):
        raise ValueError("validated campaign unexpectedly lost paired attempts")
    candidate_failures = sum(
        item.status is not AttemptStatus.SUCCESS for item in candidate
    )
    llama_failures = sum(item.status is not AttemptStatus.SUCCESS for item in llama)
    codes: list[str] = []
    candidate_distribution: LatencyDistribution | None = None
    llama_distribution: LatencyDistribution | None = None
    if candidate_failures:
        codes.append("candidate_attempt_failed")
    if llama_failures:
        codes.append("llamaparse_attempt_failed")
    if not candidate_failures and not llama_failures:
        candidate_distribution = summarize_latency(
            tuple(item.total_latency_ns for item in candidate)
        )
        # The provider UI rounds its Total Latency display.  Treating the
        # displayed midpoint as exact could award a pass that is not proven.
        # Compare against the inclusive lower edge of every retained display
        # interval, which is the conservative value favorable to neither the
        # candidate nor hidden provider precision.
        llama_distribution = summarize_latency(
            tuple(
                int(item.provider_total_latency.lower_bound_inclusive_ns)
                for item in llama
                if item.provider_total_latency is not None
            )
        )
        if candidate_distribution.p50_ns > llama_distribution.p50_ns:
            codes.append("candidate_p50_exceeds_llamaparse")
        if candidate_distribution.p95_ns > llama_distribution.p95_ns:
            codes.append("candidate_p95_exceeds_llamaparse")
    return CaseLatencyGate(
        case_id=case_id,
        sample_count_per_system=len(candidate),
        candidate_failure_count=candidate_failures,
        llamaparse_failure_count=llama_failures,
        candidate=candidate_distribution,
        llamaparse=llama_distribution,
        failure_codes=tuple(codes),
        passed=not codes,
    )


def evaluate_campaign(campaign: LatencyCampaign) -> CampaignLatencyGate:
    """Evaluate every case independently; no corpus aggregate is produced."""

    case_ids = sorted({attempt.case_id for attempt in campaign.attempts})
    cases = tuple(
        _case_gate(
            case_id,
            tuple(item for item in campaign.attempts if item.case_id == case_id),
        )
        for case_id in case_ids
    )
    return CampaignLatencyGate(
        schema_version="1.0",
        campaign_sha256=model_sha256(campaign),
        cases=cases,
        passed=all(case.passed for case in cases),
    )
