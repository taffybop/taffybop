from __future__ import annotations

import json
import math
from pathlib import Path
from time import perf_counter

from app.services.font_audit import audit_pdf_fonts


WORKSPACE = Path(__file__).resolve().parents[2]
FINANCE_PDF = (
    WORKSPACE / "benchmark-expertmodeldata" / "finance-10k.pdf"
)
PHASE_0_RUN = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
    / "run-record.json"
)


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


def _finance_parse_baseline_ms() -> float:
    run = json.loads(PHASE_0_RUN.read_text(encoding="utf-8"))
    case = next(
        case
        for case in run["cases"]
        if case["case_id"] == "finance-10k"
    )
    return float(case["parse_latency_ms"])


def test_healthy_pdf_font_audit_p95_stays_below_ten_percent() -> None:
    pdf_bytes = FINANCE_PDF.read_bytes()
    for _ in range(5):
        report = audit_pdf_fonts(pdf_bytes)
        assert report.status == "complete"
        assert report.findings == []

    durations_ms: list[float] = []
    for _ in range(30):
        started = perf_counter()
        report = audit_pdf_fonts(pdf_bytes)
        durations_ms.append((perf_counter() - started) * 1000)
        assert report.status == "complete"
        assert report.findings == []

    p95_ms = _nearest_rank(durations_ms, 0.95)
    baseline_ms = _finance_parse_baseline_ms()
    assert p95_ms <= baseline_ms * 0.10, {
        "audit_p95_ms": p95_ms,
        "phase_0_finance_parse_ms": baseline_ms,
        "overhead_percent": p95_ms / baseline_ms * 100,
    }
