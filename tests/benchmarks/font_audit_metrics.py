"""Reproducible P02-US01 corpus and component-performance evidence.

The measured latency is the additive font audit plus strict report
serialization introduced before the unchanged parse pipeline. Complete healthy
reports take a verified no-copy IR attachment path. Phase 0 per-case parse
latency is retained as the historical comparator; this runner does not
mislabel the result as a paired full-parser benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from tests.benchmarks.corpus_registry import EXPECTED_CASE_IDS


PHASE_0_RUN = (
    "tracker/phase-00-baseline/evidence/"
    "p00-us10-corpus-20260729-03/run-record.json"
)


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one observation is required")
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _phase_0_cases(workspace: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(
        (workspace / PHASE_0_RUN).read_text(encoding="utf-8")
    )
    return {str(case["case_id"]): case for case in payload["cases"]}


def _worker(workspace: Path, case_id: str, warmups: int, samples: int) -> int:
    pdf_path = workspace / "benchmark-expertmodeldata" / f"{case_id}.pdf"
    pdf_bytes = pdf_path.read_bytes()
    rss_before = _peak_rss_bytes()

    from app.services.font_audit import audit_pdf_fonts

    reference: dict[str, Any] | None = None
    for _ in range(warmups):
        report = audit_pdf_fonts(pdf_bytes)
        payload = report.model_dump(mode="json")
        if reference is None:
            reference = payload
        elif payload != reference:
            raise RuntimeError(f"{case_id} audit changed during warmup")

    durations_ms: list[float] = []
    reports: list[dict[str, Any]] = []
    for _ in range(samples):
        started = perf_counter()
        report = audit_pdf_fonts(pdf_bytes)
        payload = report.model_dump(mode="json")
        durations_ms.append((perf_counter() - started) * 1000)
        reports.append(payload)

    first = reports[0]
    if any(report != first for report in reports[1:]):
        raise RuntimeError(f"{case_id} audit changed across measured samples")
    if reference is not None and first != reference:
        raise RuntimeError(f"{case_id} warmup and measured audits differ")

    findings = [
        {
            "font_ref": finding["font_ref"],
            "font_object_id": finding["font_object_id"],
            "health": finding["health"],
            "reason_codes": finding["reason_codes"],
        }
        for finding in first["findings"]
    ]
    fonts_inspected = int(first["fonts_inspected"])
    cache_hits = int(first["font_cache_hit_count"])
    cache_lookups = fonts_inspected + cache_hits
    result = {
        "case_id": case_id,
        "source_path": pdf_path.relative_to(workspace).as_posix(),
        "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "source_size_bytes": len(pdf_bytes),
        "warmup_count": warmups,
        "sample_count": samples,
        "latency_ms": {
            "p50": _nearest_rank(durations_ms, 0.50),
            "p95": _nearest_rank(durations_ms, 0.95),
            "max": max(durations_ms),
        },
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": _peak_rss_bytes(),
        "status": first["status"],
        "pages_inspected": first["pages_inspected"],
        "characters_inspected": first["characters_inspected"],
        "fonts_inspected": fonts_inspected,
        "font_cache_hit_count": cache_hits,
        "font_cache_lookup_count": cache_lookups,
        "font_cache_hit_rate": (
            cache_hits / cache_lookups if cache_lookups else 0.0
        ),
        "findings": findings,
        "deterministic": True,
        "_durations_ms": durations_ms,
    }
    result["peak_rss_increment_bytes"] = max(
        result["peak_rss_after_bytes"] - rss_before,
        0,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _collect(
    workspace: Path,
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    phase_0 = _phase_0_cases(workspace)
    cases: list[dict[str, Any]] = []
    healthy_overheads: list[float] = []

    for case_id in EXPECTED_CASE_IDS:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.font_audit_metrics",
                "worker",
                "--workspace",
                str(workspace),
                "--case-id",
                case_id,
                "--warmups",
                str(warmups),
                "--samples",
                str(samples),
            ],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
        case = json.loads(completed.stdout)
        baseline = phase_0[case_id]
        expected_hash = next(
            artifact["sha256"]
            for artifact in baseline["source_triplet"]
            if artifact["role"] == "source"
        )
        if case["source_sha256"] != expected_hash:
            raise RuntimeError(f"{case_id} source hash differs from Phase 0")

        parse_latency_ms = float(baseline["parse_latency_ms"])
        case["phase_0"] = {
            "run_id": baseline["run_id"],
            "parse_latency_ms": parse_latency_ms,
            "peak_rss_bytes": baseline["peak_rss_bytes"],
            "environment_sha256": baseline["environment_sha256"],
        }
        case["additive_overhead_percent"] = {
            key: float(value) / parse_latency_ms * 100
            for key, value in case["latency_ms"].items()
        }
        if not case["findings"]:
            healthy_overheads.extend(
                float(value) / parse_latency_ms * 100
                for value in case.pop("_durations_ms")
            )
        else:
            case.pop("_durations_ms")
        cases.append(case)

    statuses = {case["status"] for case in cases}
    unexpected_findings = [
        case["case_id"]
        for case in cases
        if case["findings"] and case["case_id"] != "catastrophe-recap"
    ]
    target_findings = next(
        case["findings"]
        for case in cases
        if case["case_id"] == "catastrophe-recap"
    )
    total_cache_hits = sum(case["font_cache_hit_count"] for case in cases)
    total_cache_lookups = sum(
        case["font_cache_lookup_count"] for case in cases
    )
    return {
        "schema_version": "1.0",
        "record_kind": "p02_us01_font_audit_component_metrics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "measurement_scope": (
            "isolated additive font audit plus strict report serialization; "
            "complete healthy reports use a verified no-copy IR attachment "
            "path; Phase 0 parse records are historical per-case comparators, "
            "not paired full-parser samples"
        ),
        "workspace": str(workspace),
        "command": [
            sys.executable,
            "-m",
            "tests.benchmarks.font_audit_metrics",
            "run",
            "--workspace",
            str(workspace),
            "--warmups",
            str(warmups),
            "--samples",
            str(samples),
        ],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "case_count": len(cases),
        "page_count": sum(case["pages_inspected"] for case in cases),
        "warmups_per_case": warmups,
        "samples_per_case": samples,
        "statuses": sorted(statuses),
        "deterministic_case_count": sum(
            bool(case["deterministic"]) for case in cases
        ),
        "bad_font_target_count": 2,
        "bad_font_detected_count": len(target_findings),
        "bad_font_recall": len(target_findings) / 2,
        "healthy_case_count": len(cases) - 1,
        "healthy_false_positive_case_count": len(unexpected_findings),
        "healthy_false_positive_rate": len(unexpected_findings)
        / (len(cases) - 1),
        "font_cache_hit_count": total_cache_hits,
        "font_cache_lookup_count": total_cache_lookups,
        "font_cache_hit_rate": (
            total_cache_hits / total_cache_lookups
            if total_cache_lookups
            else 0.0
        ),
        "healthy_additive_overhead_percent": {
            "p50": _nearest_rank(healthy_overheads, 0.50),
            "p95": _nearest_rank(healthy_overheads, 0.95),
            "max": max(healthy_overheads),
        },
        "max_isolated_peak_rss_increment_bytes": max(
            case["peak_rss_increment_bytes"] for case in cases
        ),
        "cases": cases,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)

    for operation in ("run", "worker"):
        child = subparsers.add_parser(operation)
        child.add_argument("--workspace", type=Path, required=True)
        child.add_argument("--warmups", type=int, default=2)
        child.add_argument("--samples", type=int, default=10)
        if operation == "worker":
            child.add_argument(
                "--case-id",
                choices=EXPECTED_CASE_IDS,
                required=True,
            )
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    if args.warmups < 0 or args.samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    if args.operation == "worker":
        return _worker(
            workspace,
            args.case_id,
            args.warmups,
            args.samples,
        )

    result = _collect(
        workspace,
        warmups=args.warmups,
        samples=args.samples,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
