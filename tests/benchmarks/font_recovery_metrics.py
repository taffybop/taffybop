"""Reproducible P02-US02 recovery correctness and component metrics.

Recovery latency includes ``recover_pdf_font_text`` and strict report
serialization.  The required font-audit report is prepared before the timed
region.  Each corpus case runs in an isolated child process.

Healthy recovery overhead is compared with immutable Phase 0 per-case parse
records.  The retained P02-US01 healthy audit p95 and this runner's healthy
recovery p95 are added only as a conservative ceiling reference.  That sum is
not a paired full-parser benchmark and is not itself an observed percentile.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
P02_US01_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US01-font-audit-metrics.json"
)
BASELINE_OUTPUT = (
    "tracker/benchmarks/llamaparse-15/runs/"
    "baseline-20260728-current/catastrophe-recap/our-output.json"
)
CATASTROPHE_TRUTH = (
    "tracker/phase-00-baseline/evidence/"
    "P00-US02-catastrophe-truth.json"
)
CATASTROPHE_CASE_ID = "catastrophe-recap"
TARGET_SENTENCE = (
    "Windstorm Éowyn in Ireland and the UK followed with $690 million "
    "(€620 million)."
)
HEALTHY_OVERHEAD_TARGET_PERCENT = 10.0


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one observation is required")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "p50": _nearest_rank(values, 0.50),
        "p95": _nearest_rank(values, 0.95),
        "max": max(values),
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _phase_0_cases(workspace: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(workspace / PHASE_0_RUN)
    return {str(case["case_id"]): case for case in payload["cases"]}


def _measure_recovery(
    pdf_bytes: bytes,
    audit_payload: Mapping[str, Any],
    *,
    warmups: int,
    samples: int,
) -> tuple[dict[str, Any], list[float]]:
    from app.services.font_recovery import recover_pdf_font_text

    reference: dict[str, Any] | None = None
    for _ in range(warmups):
        payload = recover_pdf_font_text(
            pdf_bytes,
            audit_payload,
        ).model_dump(mode="json", exclude_none=True)
        if reference is None:
            reference = payload
        elif payload != reference:
            raise RuntimeError("font recovery changed during warmup")

    durations_ms: list[float] = []
    reports: list[dict[str, Any]] = []
    for _ in range(samples):
        started = perf_counter()
        payload = recover_pdf_font_text(
            pdf_bytes,
            audit_payload,
        ).model_dump(mode="json", exclude_none=True)
        durations_ms.append((perf_counter() - started) * 1000)
        reports.append(payload)

    first = reports[0]
    if any(report != first for report in reports[1:]):
        raise RuntimeError("font recovery changed across measured samples")
    if reference is not None and first != reference:
        raise RuntimeError("warmup and measured font recovery differ")
    return first, durations_ms


def _single_finding_audit(
    audit_payload: Mapping[str, Any],
    font_ref: str,
) -> dict[str, Any]:
    filtered = dict(audit_payload)
    filtered["findings"] = [
        finding
        for finding in audit_payload.get("findings", [])
        if isinstance(finding, Mapping)
        and finding.get("font_ref") == font_ref
    ]
    if len(filtered["findings"]) != 1:
        raise RuntimeError(f"expected one finding for {font_ref}")
    return filtered


def _glyph_is_grounded(glyph: Mapping[str, Any]) -> bool:
    bbox = glyph.get("bbox")
    coordinates = (
        bbox.get("x"),
        bbox.get("y"),
        bbox.get("width"),
        bbox.get("height"),
    ) if isinstance(bbox, Mapping) else ()
    code_point = glyph.get("unicode_code_point")
    recovered_text = glyph.get("recovered_text")
    return (
        isinstance(glyph.get("evidence_id"), str)
        and bool(glyph["evidence_id"])
        and isinstance(glyph.get("font_ref"), str)
        and bool(glyph["font_ref"])
        and isinstance(glyph.get("font_object_id"), int)
        and isinstance(glyph.get("page_index"), int)
        and isinstance(glyph.get("run_index"), int)
        and isinstance(glyph.get("glyph_index"), int)
        and glyph.get("cid") == glyph.get("glyph_id")
        and isinstance(code_point, int)
        and isinstance(recovered_text, str)
        and len(recovered_text) == 1
        and recovered_text == chr(code_point)
        and glyph.get("method") == "embedded_truetype_cmap_identity"
        and isinstance(glyph.get("width_delta_em"), (int, float))
        and math.isfinite(float(glyph["width_delta_em"]))
        and len(coordinates) == 4
        and all(
            isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) >= 0
            for value in coordinates
        )
    )


def _text_in_box(
    glyphs: list[Mapping[str, Any]],
    bbox: list[float],
    *,
    tolerance: float = 0.002,
) -> str:
    left, top, width, height = bbox
    right = left + width
    bottom = top + height
    selected: list[Mapping[str, Any]] = []
    for glyph in glyphs:
        glyph_bbox = glyph["bbox"]
        center_x = glyph_bbox["x"] + glyph_bbox["width"] / 2
        center_y = glyph_bbox["y"] + glyph_bbox["height"] / 2
        if (
            left - tolerance <= center_x <= right + tolerance
            and top - tolerance <= center_y <= bottom + tolerance
        ):
            selected.append(glyph)
    selected.sort(
        key=lambda glyph: (
            round(float(glyph["bbox"]["y"]), 2),
            glyph["bbox"]["x"],
            glyph["run_index"],
            glyph["glyph_index"],
        )
    )
    return "".join(str(glyph["recovered_text"]) for glyph in selected)


def _catastrophe_correctness(
    workspace: Path,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    runs = [
        run for run in report.get("runs", []) if isinstance(run, Mapping)
    ]
    glyphs = [
        glyph
        for run in runs
        for glyph in run.get("glyphs", [])
        if isinstance(glyph, Mapping)
    ]
    grounded = [_glyph_is_grounded(glyph) for glyph in glyphs]
    evidence_ids = [str(glyph["evidence_id"]) for glyph in glyphs]

    per_glyph = [
        {
            "evidence_id": glyph["evidence_id"],
            "page_index": glyph["page_index"],
            "run_index": glyph["run_index"],
            "glyph_index": glyph["glyph_index"],
            "font_ref": glyph["font_ref"],
            "font_object_id": glyph["font_object_id"],
            "cid": glyph["cid"],
            "glyph_id": glyph["glyph_id"],
            "unicode_code_point": glyph["unicode_code_point"],
            "original_text_sha256": hashlib.sha256(
                str(glyph["original_text"]).encode("utf-8")
            ).hexdigest(),
            "recovered_text": glyph["recovered_text"],
            "bbox": glyph["bbox"],
            "width_delta_em": glyph["width_delta_em"],
            "method": glyph["method"],
            "grounded": is_grounded,
        }
        for glyph, is_grounded in zip(glyphs, grounded, strict=True)
    ]
    per_run = [
        {
            "evidence_id": run["evidence_id"],
            "page_index": run["page_index"],
            "run_index": run["run_index"],
            "font_ref": run["font_ref"],
            "font_object_id": run["font_object_id"],
            "glyph_count": len(run["glyphs"]),
            "grounded_glyph_count": sum(
                _glyph_is_grounded(glyph) for glyph in run["glyphs"]
            ),
            "original_text_sha256": hashlib.sha256(
                str(run["original_text"]).encode("utf-8")
            ).hexdigest(),
            "recovered_text": run["recovered_text"],
            "recovered_text_sha256": hashlib.sha256(
                str(run["recovered_text"]).encode("utf-8")
            ).hexdigest(),
        }
        for run in runs
    ]

    per_font: list[dict[str, Any]] = []
    font_refs = sorted({str(run["font_ref"]) for run in runs})
    for font_ref in font_refs:
        font_runs = [run for run in runs if run["font_ref"] == font_ref]
        font_glyphs = [
            glyph for run in font_runs for glyph in run["glyphs"]
        ]
        per_font.append(
            {
                "font_ref": font_ref,
                "font_object_id": font_runs[0]["font_object_id"],
                "run_count": len(font_runs),
                "glyph_count": len(font_glyphs),
                "grounded_glyph_count": sum(
                    _glyph_is_grounded(glyph) for glyph in font_glyphs
                ),
                "unique_glyph_evidence_count": len(
                    {glyph["evidence_id"] for glyph in font_glyphs}
                ),
                "recovered_text_sha256": hashlib.sha256(
                    "".join(
                        str(run["recovered_text"]) for run in font_runs
                    ).encode("utf-8")
                ).hexdigest(),
            }
        )

    truth = _load_json(workspace / CATASTROPHE_TRUTH)
    labels = truth["chart_labels"]
    reviewed_regions = [
        {
            "region_id": str(label["annotation_id"]),
            "expected": str(label["text"]),
            "observed": _text_in_box(glyphs, label["bbox"]),
        }
        for label in labels
    ]
    source_note = next(
        element
        for element in truth["elements"]
        if element["element_id"] == "chart-source-note"
    )
    reviewed_regions.append(
        {
            "region_id": "chart-source-note",
            "expected": str(source_note["text"]),
            "observed": _text_in_box(glyphs, source_note["bbox"]),
        }
    )
    for region in reviewed_regions:
        region["exact_match"] = region["observed"] == region["expected"]

    from app.services.ir import round_trip_document
    from app.services.presentation import build_canonical_presentation

    baseline = _load_json(workspace / BASELINE_OUTPUT)
    projected, internal_ir = round_trip_document(
        baseline,
        font_recovery=dict(report),
    )
    presentation = build_canonical_presentation(internal_ir)
    projected_target_count = sum(
        str(item.get("value") or "").count(TARGET_SENTENCE)
        for page in projected.get("pages", [])
        for item in page.get("items", [])
    )
    full_text_target_count = presentation.full.text.count(TARGET_SENTENCE)

    return {
        "expected_font_count": 2,
        "recovered_font_count": report["fonts_recovered"],
        "expected_run_count": 29,
        "recovered_run_count": len(runs),
        "expected_glyph_count": 150,
        "recovered_glyph_count": len(glyphs),
        "grounded_glyph_count": sum(grounded),
        "grounding_rate": sum(grounded) / len(glyphs) if glyphs else 0.0,
        "unique_glyph_evidence_count": len(set(evidence_ids)),
        "target_sentence": TARGET_SENTENCE,
        "projected_target_exact_match_count": projected_target_count,
        "canonical_text_target_exact_match_count": full_text_target_count,
        "reviewed_region_count": len(reviewed_regions),
        "reviewed_region_exact_match_count": sum(
            bool(region["exact_match"]) for region in reviewed_regions
        ),
        "all_expected_counts_match": (
            report["fonts_recovered"] == 2
            and len(runs) == 29
            and len(glyphs) == 150
        ),
        "all_glyphs_grounded": bool(glyphs) and all(grounded),
        "all_glyph_evidence_unique": len(set(evidence_ids)) == len(glyphs),
        "target_sentence_exact": (
            projected_target_count == 1 and full_text_target_count == 1
        ),
        "all_reviewed_regions_exact": all(
            bool(region["exact_match"]) for region in reviewed_regions
        ),
        "per_font": per_font,
        "per_run": per_run,
        "per_glyph": per_glyph,
        "reviewed_regions": reviewed_regions,
    }


def _worker(
    workspace: Path,
    case_id: str,
    warmups: int,
    samples: int,
) -> int:
    pdf_path = workspace / "benchmark-expertmodeldata" / f"{case_id}.pdf"
    pdf_bytes = pdf_path.read_bytes()

    from app.services.font_audit import audit_pdf_fonts

    audit = audit_pdf_fonts(pdf_bytes)
    audit_payload = audit.model_dump(mode="json", exclude_none=True)
    if audit.status != "complete":
        raise RuntimeError(f"{case_id} audit did not complete")

    rss_before = _peak_rss_bytes()
    report, durations_ms = _measure_recovery(
        pdf_bytes,
        audit_payload,
        warmups=warmups,
        samples=samples,
    )

    per_font_latency: list[dict[str, Any]] = []
    if case_id == CATASTROPHE_CASE_ID:
        for finding in audit_payload["findings"]:
            font_ref = str(finding["font_ref"])
            font_report, font_durations = _measure_recovery(
                pdf_bytes,
                _single_finding_audit(audit_payload, font_ref),
                warmups=warmups,
                samples=samples,
            )
            per_font_latency.append(
                {
                    "font_ref": font_ref,
                    "font_object_id": finding.get("font_object_id"),
                    "warmup_count": warmups,
                    "sample_count": samples,
                    "latency_ms": _distribution(font_durations),
                    "fonts_recovered": font_report["fonts_recovered"],
                    "run_count": len(font_report["runs"]),
                    "recovered_glyph_count": (
                        font_report["recovered_glyph_count"]
                    ),
                    "deterministic": True,
                    "report_sha256": _sha256_json(font_report),
                }
            )

    rss_after = _peak_rss_bytes()
    result: dict[str, Any] = {
        "case_id": case_id,
        "source_path": pdf_path.relative_to(workspace).as_posix(),
        "source_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "source_size_bytes": len(pdf_bytes),
        "warmup_count": warmups,
        "sample_count": samples,
        "latency_ms": _distribution(durations_ms),
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "audit_status": audit_payload["status"],
        "audit_finding_count": len(audit_payload["findings"]),
        "status": report["status"],
        "fonts_considered": report["fonts_considered"],
        "fonts_recovered": report["fonts_recovered"],
        "font_programs_parsed": report["font_programs_parsed"],
        "pages_inspected": report["pages_inspected"],
        "characters_inspected": report["characters_inspected"],
        "run_count": len(report["runs"]),
        "recovered_glyph_count": report["recovered_glyph_count"],
        "refusal_count": len(report["refusals"]),
        "diagnostic_count": len(report["diagnostics"]),
        "short_circuited": (
            report["status"] == "complete"
            and report["fonts_considered"] == 0
            and report["fonts_recovered"] == 0
            and report["pages_inspected"] == 0
            and report["font_programs_parsed"] == 0
            and report["characters_inspected"] == 0
            and not report["runs"]
            and not report["refusals"]
            and not report["diagnostics"]
        ),
        "rewrite_count": len(report["runs"]),
        "deterministic": True,
        "report_sha256": _sha256_json(report),
        "per_font_latency": per_font_latency,
        "_durations_ms": durations_ms,
    }
    if case_id == CATASTROPHE_CASE_ID:
        result["correctness"] = _catastrophe_correctness(
            workspace,
            report,
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
    output: Path | None = None,
) -> dict[str, Any]:
    phase_0 = _phase_0_cases(workspace)
    us01_path = workspace / P02_US01_METRICS
    us01 = _load_json(us01_path)
    us01_p95 = float(
        us01["summary"]["healthy_additive_overhead_percent"]["p95"]
    )

    cases: list[dict[str, Any]] = []
    healthy_durations: list[float] = []
    healthy_overheads: list[float] = []
    for case_id in EXPECTED_CASE_IDS:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.font_recovery_metrics",
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
        durations = [
            float(duration) for duration in case.pop("_durations_ms")
        ]
        overheads = [
            duration / parse_latency_ms * 100 for duration in durations
        ]
        case["phase_0"] = {
            "run_id": baseline["run_id"],
            "parse_latency_ms": parse_latency_ms,
            "peak_rss_bytes": baseline["peak_rss_bytes"],
            "environment_sha256": baseline["environment_sha256"],
        }
        case["recovery_additive_overhead_percent"] = _distribution(
            overheads
        )
        if case_id != CATASTROPHE_CASE_ID:
            healthy_durations.extend(durations)
            healthy_overheads.extend(overheads)
        cases.append(case)

    healthy_cases = [
        case
        for case in cases
        if case["case_id"] != CATASTROPHE_CASE_ID
    ]
    catastrophe = next(
        case
        for case in cases
        if case["case_id"] == CATASTROPHE_CASE_ID
    )
    correctness = catastrophe["correctness"]
    healthy_recovery = _distribution(healthy_overheads)
    combined_ceiling = us01_p95 + healthy_recovery["p95"]

    if not all(bool(case["deterministic"]) for case in cases):
        raise RuntimeError("recovery was not deterministic for every case")
    if not all(bool(case["short_circuited"]) for case in healthy_cases):
        raise RuntimeError("a healthy case did not short-circuit recovery")
    if any(int(case["rewrite_count"]) for case in healthy_cases):
        raise RuntimeError("a healthy case produced a recovery rewrite")
    if not (
        correctness["all_expected_counts_match"]
        and correctness["all_glyphs_grounded"]
        and correctness["all_glyph_evidence_unique"]
        and correctness["target_sentence_exact"]
        and correctness["all_reviewed_regions_exact"]
    ):
        raise RuntimeError("catastrophe recovery correctness checks failed")

    command = [
        sys.executable,
        "-m",
        "tests.benchmarks.font_recovery_metrics",
        "run",
        "--workspace",
        str(workspace),
        "--warmups",
        str(warmups),
        "--samples",
        str(samples),
    ]
    if output is not None:
        command.extend(["--output", str(output)])

    return {
        "schema_version": "1.0",
        "record_kind": "p02_us02_font_recovery_component_metrics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "measurement_scope": (
            "isolated additive font recovery plus strict report "
            "serialization with the font audit prepared outside the timed "
            "region; Phase 0 parse records are historical per-case "
            "comparators, not paired full-parser samples"
        ),
        "workspace": str(workspace),
        "command": command,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "method": {
            "case_count": len(cases),
            "healthy_case_count": len(healthy_cases),
            "warmups_per_case": warmups,
            "samples_per_case": samples,
            "percentile": "nearest-rank",
            "isolation": "one child process per corpus case",
            "timed_region": (
                "recover_pdf_font_text plus Pydantic mode=json report "
                "serialization; audit precomputed before timing"
            ),
            "per_font_timing": (
                "catastrophe audit filtered to one finding per measured "
                "recovery; each pass still scans the real PDF page"
            ),
            "source_identity": (
                "each PDF SHA-256 matched its immutable Phase 0 source record"
            ),
            "rss": (
                "isolated-process peak RSS increment after audit "
                "precomputation, from before lazy recovery import through "
                "full-document and per-font recovery samples"
            ),
            "healthy_comparator": (
                "each isolated recovery duration divided by the immutable "
                "per-case Phase 0 parse latency"
            ),
            "combined_ceiling": (
                "arithmetic sum of independently measured retained P02-US01 "
                "healthy audit p95 and current healthy recovery p95; a "
                "conservative ceiling reference, not an observed or paired "
                "full-parser percentile"
            ),
        },
        "summary": {
            "case_count": len(cases),
            "page_count": sum(
                int(case["registered_page_count"])
                for case in phase_0.values()
            ),
            "deterministic_case_count": sum(
                bool(case["deterministic"]) for case in cases
            ),
            "healthy_case_count": len(healthy_cases),
            "healthy_short_circuit_count": sum(
                bool(case["short_circuited"]) for case in healthy_cases
            ),
            "healthy_rewrite_count": sum(
                int(case["rewrite_count"]) for case in healthy_cases
            ),
            "healthy_recovery_latency_ms": _distribution(
                healthy_durations
            ),
            "healthy_recovery_additive_overhead_percent": healthy_recovery,
            "retained_p02_us01_audit_additive_p95_percent": us01_p95,
            "combined_healthy_p95_ceiling_reference": {
                "retained_audit_p95_percent": us01_p95,
                "recovery_p95_percent": healthy_recovery["p95"],
                "arithmetic_ceiling_percent": combined_ceiling,
                "target_percent": HEALTHY_OVERHEAD_TARGET_PERCENT,
                "passes_target": (
                    combined_ceiling <= HEALTHY_OVERHEAD_TARGET_PERCENT
                ),
                "observed_paired_full_parser_percentile": False,
            },
            "catastrophe_recovery_latency_ms": catastrophe["latency_ms"],
            "catastrophe_font_count": (
                correctness["recovered_font_count"]
            ),
            "catastrophe_run_count": correctness["recovered_run_count"],
            "catastrophe_glyph_count": (
                correctness["recovered_glyph_count"]
            ),
            "catastrophe_grounding_rate": correctness["grounding_rate"],
            "catastrophe_target_sentence_exact": (
                correctness["target_sentence_exact"]
            ),
            "catastrophe_reviewed_regions_exact": (
                correctness["all_reviewed_regions_exact"]
            ),
            "max_isolated_peak_rss_increment_bytes": max(
                int(case["peak_rss_increment_bytes"]) for case in cases
            ),
            "retained_p02_us01_metrics_path": P02_US01_METRICS,
            "retained_p02_us01_metrics_sha256": hashlib.sha256(
                us01_path.read_bytes()
            ).hexdigest(),
        },
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
        else:
            child.add_argument(
                "--output",
                type=Path,
                help="also retain the complete JSON result at this path",
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
        output=args.output,
    )
    serialized = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{serialized}\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
