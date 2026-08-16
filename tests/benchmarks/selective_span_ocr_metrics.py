"""Reproducible P02-US03 selective-span OCR component metrics.

This runner measures only the selective routing component.  Font audit and
font recovery reports are prepared before timed regions.  Deterministic
routing, evidence, soft-failure, and healthy-control samples use test doubles;
one separately labeled warmup/sample series exercises the production
PDFium/local-Tesseract path over four exact audited crops.  It never invokes
the document pipeline, layout models, or broad page-analysis OCR.

The retained P02-US01 audit p95, retained P02-US02 recovery p95, and current
healthy selective-planning p95 are added as a conservative ceiling reference.
That arithmetic sum is not a paired full-parser observation or percentile.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import re
import resource
import shutil
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar

from tests.benchmarks.corpus_registry import EXPECTED_CASE_IDS


PHASE_0_RUN = (
    "tracker/phase-00-baseline/evidence/"
    "p00-us10-corpus-20260729-03/run-record.json"
)
P02_US01_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US01-font-audit-metrics.json"
)
P02_US02_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US02-font-recovery-metrics.json"
)
DEFAULT_OUTPUT = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US03-selective-span-ocr-metrics.json"
)
HEALTHY_OVERHEAD_TARGET_PERCENT = 10.0
EXPECTED_TESSERACT_VERSION = "5.5.3"
EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES = 4_113_088
EXPECTED_ENG_TRAINEDDATA_SHA256 = (
    "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
)

_PayloadT = TypeVar("_PayloadT", bound=Mapping[str, Any])


def _nearest_rank(values: list[float], percentile: float) -> float:
    """Return the nearest-rank percentile used by retained Phase 2 metrics."""

    if not values:
        raise ValueError("at least one observation is required")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("observations must be finite and non-negative")
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


def _distribution(values: list[float]) -> dict[str, float]:
    """Summarize non-empty observations without interpolated percentiles."""

    return {
        "p50": _nearest_rank(values, 0.50),
        "p95": _nearest_rank(values, 0.95),
        "max": max(values),
    }


def _peak_rss_bytes() -> int:
    """Return process peak RSS in bytes on Darwin and POSIX CI hosts."""

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _peak_child_rss_bytes() -> int:
    """Return the greatest observed child-process peak RSS in bytes."""

    value = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _reference_tesseract_binding(
    command: str = "tesseract",
    *,
    tessdata_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve and enforce the OCR executable/language asset policy binding."""

    executable = shutil.which(command.strip()) if command.strip() else None
    if executable is None:
        raise RuntimeError("accepted Tesseract executable is unavailable")
    executable_path = Path(executable).resolve()
    completed = subprocess.run(
        [str(executable_path), "--version"],
        check=False,
        capture_output=True,
        timeout=5.0,
    )
    version_output = completed.stdout + completed.stderr
    version_text = version_output.decode("utf-8", errors="replace")
    version_lines = version_text.splitlines()
    version_line = version_lines[0].strip() if version_lines else ""
    match = re.fullmatch(r"tesseract\s+(\S+)", version_line)
    observed_version = match.group(1) if match is not None else None
    if completed.returncode != 0 or observed_version != EXPECTED_TESSERACT_VERSION:
        raise RuntimeError(
            "Tesseract reference version mismatch: "
            f"expected {EXPECTED_TESSERACT_VERSION}, "
            f"observed {observed_version or version_line or 'unavailable'}"
        )

    if tessdata_path is None:
        listed = subprocess.run(
            [str(executable_path), "--list-langs"],
            check=False,
            capture_output=True,
            timeout=5.0,
        )
        listed_text = (listed.stdout + listed.stderr).decode(
            "utf-8",
            errors="replace",
        )
        directory_match = re.search(
            r'available languages in "([^"]+)"',
            listed_text,
        )
        if listed.returncode != 0 or directory_match is None:
            raise RuntimeError(
                "could not resolve the configured Tesseract language directory"
            )
        tessdata_directory = Path(directory_match.group(1))
    else:
        tessdata_directory = tessdata_path
    traineddata_path = (
        tessdata_directory.expanduser().resolve() / "eng.traineddata"
    )
    try:
        traineddata = traineddata_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            "accepted eng.traineddata asset is unavailable"
        ) from exc
    observed_size = len(traineddata)
    observed_sha256 = hashlib.sha256(traineddata).hexdigest()
    if (
        observed_size != EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
        or observed_sha256 != EXPECTED_ENG_TRAINEDDATA_SHA256
    ):
        raise RuntimeError(
            "eng.traineddata reference identity mismatch: "
            f"expected {EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES} bytes/"
            f"{EXPECTED_ENG_TRAINEDDATA_SHA256}, observed "
            f"{observed_size} bytes/{observed_sha256}"
        )
    return {
        "executable_path": str(executable_path),
        "version": observed_version,
        "version_line": version_line,
        "version_output_sha256": hashlib.sha256(version_output).hexdigest(),
        "language": "eng",
        "traineddata_path": str(traineddata_path),
        "traineddata_directory": str(traineddata_path.parent),
        "traineddata_size_bytes": observed_size,
        "traineddata_sha256": observed_sha256,
        "accepted_version": EXPECTED_TESSERACT_VERSION,
        "accepted_traineddata_size_bytes": (
            EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
        ),
        "accepted_traineddata_sha256": (
            EXPECTED_ENG_TRAINEDDATA_SHA256
        ),
        "policy_binding_passed": True,
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _file_identity(workspace: Path, relative_path: str) -> dict[str, Any]:
    path = workspace / relative_path
    content = path.read_bytes()
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _phase_0_cases(workspace: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(workspace / PHASE_0_RUN)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Phase 0 run record must contain a cases list")
    return {str(case["case_id"]): case for case in cases}


def _phase_0_source_binding(
    workspace: Path,
    case_id: str,
    source_bytes: bytes,
) -> dict[str, Any]:
    """Bind current corpus bytes to their immutable Phase 0 source record."""

    try:
        case = _phase_0_cases(workspace)[case_id]
    except KeyError as exc:
        raise KeyError(f"unknown Phase 0 corpus case {case_id!r}") from exc
    expected_hashes = [
        str(artifact["sha256"])
        for artifact in case["source_triplet"]
        if artifact.get("role") == "source"
    ]
    if len(expected_hashes) != 1:
        raise RuntimeError(
            f"{case_id} must have exactly one Phase 0 source identity"
        )
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash != expected_hashes[0]:
        raise RuntimeError(f"{case_id} source hash differs from Phase 0")
    return {
        "source_sha256": actual_hash,
        "source_size_bytes": len(source_bytes),
        "phase_0_run_id": str(case["run_id"]),
        "phase_0_parse_latency_ms": float(case["parse_latency_ms"]),
        "phase_0_peak_rss_bytes": int(case["peak_rss_bytes"]),
        "phase_0_environment_sha256": str(case["environment_sha256"]),
    }


def _retained_overhead_inputs(workspace: Path) -> dict[str, Any]:
    """Load and cross-check the immutable US01 and US02 p95 inputs."""

    us01_identity = _file_identity(workspace, P02_US01_METRICS)
    us02_identity = _file_identity(workspace, P02_US02_METRICS)
    us01 = _load_json(workspace / P02_US01_METRICS)
    us02 = _load_json(workspace / P02_US02_METRICS)
    if us01.get("record_kind") != (
        "p02_us01_font_audit_component_metrics_summary"
    ):
        raise RuntimeError("unexpected retained P02-US01 metrics kind")
    if us02.get("record_kind") != (
        "p02_us02_font_recovery_component_metrics"
    ):
        raise RuntimeError("unexpected retained P02-US02 metrics kind")

    audit_p95 = float(
        us01["summary"]["healthy_additive_overhead_percent"]["p95"]
    )
    recovery_p95 = float(
        us02["summary"][
            "healthy_recovery_additive_overhead_percent"
        ]["p95"]
    )
    us02_summary = us02["summary"]
    if (
        us02_summary["retained_p02_us01_metrics_path"]
        != P02_US01_METRICS
        or us02_summary["retained_p02_us01_metrics_sha256"]
        != us01_identity["sha256"]
        or not math.isclose(
            float(
                us02_summary[
                    "retained_p02_us01_audit_additive_p95_percent"
                ]
            ),
            audit_p95,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise RuntimeError(
            "retained P02-US02 metrics do not bind the current US01 artifact"
        )
    retained_ceiling = us02_summary[
        "combined_healthy_p95_ceiling_reference"
    ]
    expected_retained_ceiling = audit_p95 + recovery_p95
    if (
        bool(retained_ceiling["observed_paired_full_parser_percentile"])
        or not math.isclose(
            float(retained_ceiling["arithmetic_ceiling_percent"]),
            expected_retained_ceiling,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise RuntimeError("retained P02-US02 cumulative ceiling drifted")
    return {
        "audit_p95_percent": audit_p95,
        "recovery_p95_percent": recovery_p95,
        "retained_audit_recovery_ceiling_percent": (
            expected_retained_ceiling
        ),
        "p02_us01_metrics": us01_identity,
        "p02_us02_metrics": us02_identity,
    }


def _conservative_healthy_p95_ceiling(
    workspace: Path,
    selective_planning_p95_percent: float,
) -> dict[str, Any]:
    """Add current healthy planning p95 to the two retained components."""

    if (
        not math.isfinite(selective_planning_p95_percent)
        or selective_planning_p95_percent < 0
    ):
        raise ValueError(
            "selective planning p95 must be finite and non-negative"
        )
    retained = _retained_overhead_inputs(workspace)
    arithmetic_ceiling = (
        float(retained["retained_audit_recovery_ceiling_percent"])
        + selective_planning_p95_percent
    )
    return {
        "retained_audit_p95_percent": retained["audit_p95_percent"],
        "retained_recovery_p95_percent": retained["recovery_p95_percent"],
        "selective_planning_p95_percent": selective_planning_p95_percent,
        "arithmetic_ceiling_percent": arithmetic_ceiling,
        "target_percent": HEALTHY_OVERHEAD_TARGET_PERCENT,
        "passes_target": arithmetic_ceiling
        <= HEALTHY_OVERHEAD_TARGET_PERCENT,
        "observed_paired_full_parser_percentile": False,
        "retained_artifacts": {
            "p02_us01": retained["p02_us01_metrics"],
            "p02_us02": retained["p02_us02_metrics"],
        },
    }


def _measure_deterministic(
    operation: Callable[[], _PayloadT],
    *,
    warmups: int,
    samples: int,
) -> tuple[dict[str, Any], list[float]]:
    """Measure an operation and require byte-stable JSON payloads."""

    if warmups < 0 or samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    reference: dict[str, Any] | None = None
    for _ in range(warmups):
        payload = dict(operation())
        if reference is None:
            reference = payload
        elif _canonical_json(payload) != _canonical_json(reference):
            raise RuntimeError("operation changed during warmup")

    durations_ms: list[float] = []
    payloads: list[dict[str, Any]] = []
    for _ in range(samples):
        started = perf_counter()
        payload = dict(operation())
        durations_ms.append((perf_counter() - started) * 1000)
        payloads.append(payload)

    first = payloads[0]
    first_bytes = _canonical_json(first)
    if any(_canonical_json(payload) != first_bytes for payload in payloads[1:]):
        raise RuntimeError("operation changed across measured samples")
    if reference is not None and _canonical_json(reference) != first_bytes:
        raise RuntimeError("warmup and measured operation differ")
    return first, durations_ms


def _pdf_page_sizes(pdf_bytes: bytes) -> dict[int, tuple[float, float]]:
    """Read displayed PDF page sizes without rendering or model execution."""

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    page_sizes: dict[int, tuple[float, float]] = {}
    try:
        for page_index in range(1, len(document) + 1):
            page = document[page_index - 1]
            try:
                page_sizes[page_index] = tuple(
                    float(value) for value in page.get_size()
                )
            finally:
                page.close()
    finally:
        document.close()
    return page_sizes


def _catastrophe_refusal_variant(
    audit_payload: Mapping[str, Any],
    recovery_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a typed benchmark-only refusal while retaining safe neighbors.

    The real catastrophe report safely recovers two fonts.  The smaller
    four-run font is converted into an explicit refusal in this test-only
    report variant.  Its four real audit bboxes become targets while the other
    font's 25 real, safely recovered runs remain same-page non-authority
    neighbors.  The source PDF and audit bytes are unchanged.
    """

    findings = [
        finding
        for finding in audit_payload.get("findings", [])
        if isinstance(finding, Mapping)
    ]
    if len(findings) < 2:
        raise RuntimeError(
            "catastrophe benchmark requires two audited font findings"
        )
    target = min(
        findings,
        key=lambda finding: len(finding.get("runs") or []),
    )
    target_font_ref = str(target["font_ref"])
    target_runs = list(target.get("runs") or [])
    if len(target_runs) != 4:
        raise RuntimeError(
            "catastrophe benchmark target must retain four real audit runs"
        )

    variant = deepcopy(dict(recovery_payload))
    variant["runs"] = [
        run
        for run in recovery_payload.get("runs", [])
        if isinstance(run, Mapping)
        and str(run.get("font_ref")) != target_font_ref
    ]
    variant["refusals"] = [
        {
            "font_ref": target_font_ref,
            "font_object_id": target.get("font_object_id"),
            "page_indexes": sorted(
                {
                    int(run["page_index"])
                    for run in target_runs
                    if isinstance(run, Mapping)
                }
            ),
            "reason_code": "benchmark_explicit_refusal_variant",
            "message": (
                "Deterministic benchmark-only refusal used to exercise "
                "selective routing; the retained production recovery remains "
                "unchanged."
            ),
        }
    ]
    variant["fonts_recovered"] = len(
        {
            str(run["font_ref"])
            for run in variant["runs"]
            if isinstance(run, Mapping)
        }
    )
    variant["recovered_glyph_count"] = sum(
        len(run.get("glyphs") or [])
        for run in variant["runs"]
        if isinstance(run, Mapping)
    )

    from app.services.font_recovery import FontRecoveryReport

    validated = FontRecoveryReport.model_validate(variant).model_dump(
        mode="json",
        exclude_none=True,
    )
    neighbor_findings = [
        finding
        for finding in findings
        if str(finding.get("font_ref")) != target_font_ref
    ]
    descriptor = {
        "variant_kind": "deterministic_test_only_recovery_refusal",
        "target_font_ref": target_font_ref,
        "target_font_object_id": target.get("font_object_id"),
        "unresolved_target_span_count": len(target_runs),
        "healthy_neighbor_font_refs": sorted(
            str(finding["font_ref"]) for finding in neighbor_findings
        ),
        "healthy_neighbor_span_count": sum(
            len(finding.get("runs") or [])
            for finding in neighbor_findings
        ),
        "source_pdf_changed": False,
        "audit_report_changed": False,
        "retained_production_recovery_changed": False,
    }
    return validated, descriptor


class _BenchmarkRenderDouble:
    """One-request-at-a-time render/OCR double with request instrumentation."""

    def __init__(
        self,
        page_sizes: Mapping[int, tuple[float, float]],
        *,
        fail_unavailable: bool,
    ) -> None:
        self.page_sizes = dict(page_sizes)
        self.fail_unavailable = fail_unavailable
        self.calls: list[dict[str, Any]] = []
        self.successful_render_count = 0

    def __call__(
        self,
        _pdf_bytes: bytes,
        requests: Any,
        **_kwargs: Any,
    ) -> dict[int, list[Any]]:
        from app.services.ocr import (
            ImageRegion,
            OCRLine,
            OCRToken,
            OCRUnavailableError,
        )

        request_list = list(requests)
        if len(request_list) != 1:
            raise RuntimeError(
                "selective benchmark expected exactly one request per call"
            )
        request = request_list[0]
        source = {
            "x": float(request.bbox["x"]),
            "y": float(request.bbox["y"]),
            "width": float(
                request.bbox.get("width", request.bbox.get("w"))
            ),
            "height": float(
                request.bbox.get("height", request.bbox.get("h"))
            ),
        }
        metadata = dict(request.metadata)
        self.calls.append(
            {
                "page_index": int(request.page_index),
                "source_bbox": source,
                "span_id": str(metadata.get("selective_span_id") or ""),
                "font_ref": str(metadata.get("font_ref") or ""),
                "audit_run_index": int(
                    metadata.get("audit_run_index") or 0
                ),
                "region_role": str(request.region_role),
                "content_type": str(request.content_type),
            }
        )
        if self.fail_unavailable:
            raise OCRUnavailableError(
                "deterministic benchmark OCR-unavailable soft failure"
            )

        page_width, page_height = self.page_sizes[int(request.page_index)]
        crop_left = max(source["x"] - 3.0, 0.0)
        crop_top = max(source["y"] - 3.0, 0.0)
        crop_right = min(
            source["x"] + source["width"] + 3.0,
            page_width,
        )
        crop_bottom = min(
            source["y"] + source["height"] + 3.0,
            page_height,
        )
        pixel_width = max(math.ceil((crop_right - crop_left) * 5.0), 1)
        pixel_height = max(math.ceil((crop_bottom - crop_top) * 5.0), 1)
        actual_scale_x = pixel_width / (crop_right - crop_left)
        actual_scale_y = pixel_height / (crop_bottom - crop_top)
        pixel_bbox = {
            "x": round(
                (source["x"] - crop_left) * actual_scale_x,
                3,
            ),
            "y": round(
                (source["y"] - crop_top) * actual_scale_y,
                3,
            ),
            "w": round(source["width"] * actual_scale_x, 3),
            "h": round(source["height"] * actual_scale_y, 3),
            "unit": "px",
        }
        page_bbox = {
            "x": source["x"],
            "y": source["y"],
            "w": source["width"],
            "h": source["height"],
        }
        text = f"BENCHMARK-SPAN-{metadata['audit_run_index']}"
        token = OCRToken(
            text=text,
            bbox=dict(page_bbox),
            crop_pixel_bbox=pixel_bbox,
            confidence=0.99,
            ocr_pass="standard",
            word_index=0,
        )
        line = OCRLine(
            text=text,
            bbox=dict(page_bbox),
            confidence=0.99,
            word_count=1,
            ocr_pass="standard",
            tokens=[token],
        )
        self.successful_render_count += 1
        return {
            int(request.page_index): [
                ImageRegion(
                    page_index=int(request.page_index),
                    object_index=0,
                    bbox=dict(page_bbox),
                    pixel_width=pixel_width,
                    pixel_height=pixel_height,
                    area_ratio=(
                        source["width"]
                        * source["height"]
                        / (page_width * page_height)
                    ),
                    text=text,
                    lines=[line],
                    confidence=0.99,
                    content_type="text",
                    metadata={
                        **metadata,
                        "benchmark_render_double": True,
                    },
                    region_role="content_region",
                    region_origin="pdf_page_render",
                    coordinate_unit="pt",
                )
            ]
        }

    def instrumentation(self) -> dict[str, Any]:
        return {
            "render_call_count": len(self.calls),
            "requested_region_count": len(self.calls),
            "successful_render_count": self.successful_render_count,
            "requests": list(self.calls),
            "broad_page_render_count": 0,
            "document_model_invocation_count": 0,
        }


def _constant_clock() -> float:
    """Make report cost/deadline fields byte-stable; latency is timed outside."""

    return 100.0


def _selective_operation(
    pdf_bytes: bytes,
    audit_payload: Mapping[str, Any],
    recovery_payload: Mapping[str, Any],
    page_sizes: Mapping[int, tuple[float, float]],
    *,
    fail_unavailable: bool,
) -> dict[str, Any]:
    from app.services.selective_span_ocr import run_selective_span_ocr

    renderer = _BenchmarkRenderDouble(
        page_sizes,
        fail_unavailable=fail_unavailable,
    )
    report = run_selective_span_ocr(
        pdf_bytes,
        audit_payload,
        recovery_payload,
        page_sizes,
        tesseract_cmd="",
        languages=("eng",),
        render_function=renderer,
        clock=_constant_clock,
    )
    return {
        "report": report.model_dump(mode="json", exclude_none=True),
        "instrumentation": renderer.instrumentation(),
    }


def _candidate_evidence_complete(
    outcome: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> bool:
    """Check the complete crop/cost/candidate/token evidence relationship."""

    cost = outcome.get("cost")
    crop_bbox = outcome.get("crop_bbox")
    source_bbox = outcome.get("source_bbox")
    tokens = candidate.get("tokens")
    if not (
        isinstance(cost, Mapping)
        and isinstance(crop_bbox, Mapping)
        and isinstance(source_bbox, Mapping)
        and isinstance(tokens, list)
        and tokens
    ):
        return False
    numeric_cost_fields = (
        "requested_scale",
        "requested_dpi",
        "actual_dpi_x",
        "actual_dpi_y",
        "pixel_width",
        "pixel_height",
        "pixel_count",
        "rendered_area_points2",
        "page_area_ratio",
        "elapsed_ms",
        "timeout_budget_seconds",
        "padding_points",
    )
    if any(
        not isinstance(cost.get(field), (int, float))
        or isinstance(cost.get(field), bool)
        or not math.isfinite(float(cost[field]))
        or float(cost[field]) < 0
        for field in numeric_cost_fields
    ):
        return False
    if int(cost["pixel_count"]) != (
        int(cost["pixel_width"]) * int(cost["pixel_height"])
    ):
        return False
    if not (
        len(cost.get("crop_to_page_transform") or []) == 6
        and len(cost.get("page_to_crop_transform") or []) == 6
        and cost.get("engine") == "tesseract"
        and cost.get("languages") == ["eng"]
        and cost.get("passes_attempted") == ["standard", "sparse"]
        and cost.get("passes_completed")
        and isinstance(cost.get("padding_clipped"), bool)
    ):
        return False
    if not (
        outcome.get("status") == "candidate"
        and outcome.get("span_id")
        and outcome.get("font_ref")
        and isinstance(outcome.get("audit_run_index"), int)
        and outcome.get("refusal_reason_code")
        and candidate.get("evidence_id")
        and candidate.get("span_id") == outcome.get("span_id")
        and candidate.get("text")
        and candidate.get("method") == "selective_pdf_tesseract_tsv"
        and candidate.get("selected") is False
        and candidate.get("ocr_pass") in {"standard", "sparse"}
        and isinstance(candidate.get("bbox"), Mapping)
        and isinstance(candidate.get("crop_pixel_bbox"), Mapping)
        and candidate["crop_pixel_bbox"].get("unit") == "px"
        and candidate.get("word_count") == len(tokens)
    ):
        return False
    for token in tokens:
        if not (
            isinstance(token, Mapping)
            and token.get("evidence_id")
            and token.get("text")
            and isinstance(token.get("bbox"), Mapping)
            and isinstance(token.get("crop_pixel_bbox"), Mapping)
            and token["crop_pixel_bbox"].get("unit") == "px"
            and token.get("ocr_pass") in {"standard", "sparse"}
            and isinstance(token.get("word_index"), int)
            and token.get("method") == "tesseract_tsv"
        ):
            return False
    return True


def _candidate_evidence_rows(
    report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for outcome in report.get("outcomes", []):
        if not isinstance(outcome, Mapping):
            continue
        for candidate in outcome.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            rows.append(
                {
                    "span_id": outcome.get("span_id"),
                    "candidate_evidence_id": candidate.get("evidence_id"),
                    "token_evidence_ids": [
                        token.get("evidence_id")
                        for token in candidate.get("tokens", [])
                        if isinstance(token, Mapping)
                    ],
                    "complete": _candidate_evidence_complete(
                        outcome,
                        candidate,
                    ),
                }
            )
    return rows


def _real_production_path_measurement(
    pdf_bytes: bytes,
    audit_payload: Mapping[str, Any],
    recovery_payload: Mapping[str, Any],
    page_sizes: Mapping[int, tuple[float, float]],
    *,
    engine_binding: Mapping[str, Any],
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    """Measure repeated bounded PDFium/Tesseract runs over all four targets."""

    from app.services.selective_span_ocr import run_selective_span_ocr

    if warmups < 0 or samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")

    def measure_once() -> tuple[dict[str, Any], float]:
        started = perf_counter()
        report = run_selective_span_ocr(
            pdf_bytes,
            audit_payload,
            recovery_payload,
            page_sizes,
            tesseract_cmd=str(engine_binding["executable_path"]),
            languages=("eng",),
            tessdata_path=str(engine_binding["traineddata_directory"]),
        )
        latency_ms = (perf_counter() - started) * 1000.0
        payload = report.model_dump(mode="json", exclude_none=True)
        outcomes = [
            outcome
            for outcome in payload.get("outcomes", [])
            if isinstance(outcome, Mapping)
        ]
        if (
            payload.get("known_span_count") != 4
            or payload.get("terminal_outcome_count") != 4
            or len(outcomes) != 4
        ):
            raise RuntimeError(
                "real production sample did not retain all four target outcomes"
            )
        if any(
            outcome.get("status") not in {"candidate", "no_text"}
            or not isinstance(outcome.get("cost"), Mapping)
            for outcome in outcomes
        ):
            raise RuntimeError(
                "real production sample did not complete every bounded crop"
            )
        candidate_rows = _candidate_evidence_rows(payload)
        if not candidate_rows or not all(
            bool(row["complete"]) for row in candidate_rows
        ):
            raise RuntimeError(
                "real production sample retained incomplete candidate evidence"
            )
        return payload, latency_ms

    def structural_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = deepcopy(dict(payload))
        normalized["elapsed_ms"] = 0.0
        for outcome in normalized.get("outcomes", []):
            if not isinstance(outcome, dict):
                continue
            attempt = outcome.get("attempt")
            if isinstance(attempt, dict) and "elapsed_ms" in attempt:
                attempt["elapsed_ms"] = 0.0
            cost = outcome.get("cost")
            if isinstance(cost, dict) and "elapsed_ms" in cost:
                cost["elapsed_ms"] = 0.0
        return normalized

    self_rss_before = _peak_rss_bytes()
    child_rss_before = _peak_child_rss_bytes()
    structural_reference: bytes | None = None
    for _ in range(warmups):
        warmup_payload, _warmup_latency = measure_once()
        warmup_structure = _canonical_json(
            structural_payload(warmup_payload)
        )
        if structural_reference is None:
            structural_reference = warmup_structure
        elif warmup_structure != structural_reference:
            raise RuntimeError(
                "real OCR structure/evidence changed during warmup"
            )

    measured_payloads: list[dict[str, Any]] = []
    latency_samples_ms: list[float] = []
    report_elapsed_samples_ms: list[float] = []
    for _ in range(samples):
        payload, latency_ms = measure_once()
        structure = _canonical_json(structural_payload(payload))
        if structural_reference is None:
            structural_reference = structure
        elif structure != structural_reference:
            raise RuntimeError(
                "real OCR structure/evidence changed across samples"
            )
        measured_payloads.append(payload)
        latency_samples_ms.append(latency_ms)
        report_elapsed_samples_ms.append(float(payload["elapsed_ms"]))

    self_rss_after = _peak_rss_bytes()
    child_rss_after = _peak_child_rss_bytes()
    payload = measured_payloads[0]
    outcomes = [
        outcome
        for outcome in payload.get("outcomes", [])
        if isinstance(outcome, Mapping)
    ]
    candidate_rows = _candidate_evidence_rows(payload)
    outcome_evidence = []
    for outcome in outcomes:
        candidates = [
            candidate
            for candidate in outcome.get("candidates", [])
            if isinstance(candidate, Mapping)
        ]
        outcome_evidence.append(
            {
                "span_id": outcome.get("span_id"),
                "page_index": outcome.get("page_index"),
                "font_ref": outcome.get("font_ref"),
                "audit_run_index": outcome.get("audit_run_index"),
                "refusal_reason_code": outcome.get(
                    "refusal_reason_code"
                ),
                "terminal_status": outcome.get("status"),
                "terminal_reason_code": outcome.get("reason_code"),
                "source_bbox": outcome.get("source_bbox"),
                "crop_bbox": outcome.get("crop_bbox"),
                "attempt": outcome.get("attempt"),
                "cost": outcome.get("cost"),
                "candidate_evidence_ids": [
                    candidate.get("evidence_id")
                    for candidate in candidates
                ],
                "token_evidence_ids": [
                    token.get("evidence_id")
                    for candidate in candidates
                    for token in candidate.get("tokens", [])
                    if isinstance(token, Mapping)
                ],
            }
        )
    return {
        "measurement_kind": (
            "isolated_real_pdfium_tesseract_production_path"
        ),
        "warmup_count": warmups,
        "sample_count": samples,
        "mocked": False,
        "actual_pdfium_render": True,
        "actual_local_tesseract": True,
        "candidate_selection_invoked": False,
        "structurally_deterministic": True,
        "structural_report_sha256": hashlib.sha256(
            structural_reference or b""
        ).hexdigest(),
        "timing_fields_normalized_for_structure": [
            "report.elapsed_ms",
            "outcomes[].attempt.elapsed_ms",
            "outcomes[].cost.elapsed_ms",
        ],
        "latency_ms": _distribution(latency_samples_ms),
        "latency_samples_ms": latency_samples_ms,
        "report_elapsed_ms": _distribution(
            report_elapsed_samples_ms
        ),
        "report_elapsed_samples_ms": report_elapsed_samples_ms,
        "worker_peak_rss_before_bytes": self_rss_before,
        "worker_peak_rss_after_bytes": self_rss_after,
        "child_peak_rss_before_bytes": child_rss_before,
        "child_peak_rss_after_bytes": child_rss_after,
        "observed_peak_rss_bytes": max(
            self_rss_after,
            child_rss_after,
        ),
        "observed_peak_rss_increment_bytes": max(
            self_rss_after - self_rss_before,
            child_rss_after - child_rss_before,
            0,
        ),
        "tesseract_binding": dict(engine_binding),
        "report": payload,
        "outcome_evidence": outcome_evidence,
        "candidate_evidence": candidate_rows,
    }


def _worker_target(
    workspace: Path,
    warmups: int,
    samples: int,
) -> int:
    case_id = "catastrophe-recap"
    source_path = (
        workspace / "benchmark-expertmodeldata" / f"{case_id}.pdf"
    )
    pdf_bytes = source_path.read_bytes()
    source_binding = _phase_0_source_binding(
        workspace,
        case_id,
        pdf_bytes,
    )

    from app.services.font_audit import audit_pdf_fonts
    from app.services.font_recovery import recover_pdf_font_text

    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    audit_payload = audit.model_dump(mode="json", exclude_none=True)
    recovery_payload = recovery.model_dump(mode="json", exclude_none=True)
    variant, descriptor = _catastrophe_refusal_variant(
        audit_payload,
        recovery_payload,
    )
    page_sizes = _pdf_page_sizes(pdf_bytes)

    rss_before = _peak_rss_bytes()
    success, success_durations = _measure_deterministic(
        lambda: _selective_operation(
            pdf_bytes,
            audit_payload,
            variant,
            page_sizes,
            fail_unavailable=False,
        ),
        warmups=warmups,
        samples=samples,
    )
    soft_failure, soft_failure_durations = _measure_deterministic(
        lambda: _selective_operation(
            pdf_bytes,
            audit_payload,
            variant,
            page_sizes,
            fail_unavailable=True,
        ),
        warmups=warmups,
        samples=samples,
    )
    rss_after = _peak_rss_bytes()
    result = {
        "case_id": case_id,
        "source_path": source_path.relative_to(workspace).as_posix(),
        **source_binding,
        "audit_report_sha256": _sha256_json(audit_payload),
        "production_recovery_report_sha256": _sha256_json(
            recovery_payload
        ),
        "benchmark_recovery_variant_sha256": _sha256_json(variant),
        "recovery_variant": descriptor,
        "page_sizes_points": {
            str(page): [width, height]
            for page, (width, height) in page_sizes.items()
        },
        "warmup_count": warmups,
        "sample_count": samples,
        "mocked_selective_execution": {
            "latency_ms": _distribution(success_durations),
            "deterministic": True,
            **success,
        },
        "ocr_unavailable_soft_failure": {
            "latency_ms": _distribution(soft_failure_durations),
            "deterministic": True,
            **soft_failure,
        },
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "_success_durations_ms": success_durations,
        "_soft_failure_durations_ms": soft_failure_durations,
    }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _worker_real_target(
    workspace: Path,
    warmups: int,
    samples: int,
) -> int:
    """Measure the actual renderer/OCR path in its own benchmark process."""

    case_id = "catastrophe-recap"
    source_path = (
        workspace / "benchmark-expertmodeldata" / f"{case_id}.pdf"
    )
    pdf_bytes = source_path.read_bytes()
    source_binding = _phase_0_source_binding(
        workspace,
        case_id,
        pdf_bytes,
    )

    from app.services.font_audit import audit_pdf_fonts
    from app.services.font_recovery import recover_pdf_font_text

    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    audit_payload = audit.model_dump(mode="json", exclude_none=True)
    recovery_payload = recovery.model_dump(mode="json", exclude_none=True)
    variant, descriptor = _catastrophe_refusal_variant(
        audit_payload,
        recovery_payload,
    )
    page_sizes = _pdf_page_sizes(pdf_bytes)
    engine_binding = _reference_tesseract_binding()
    real_production_path = _real_production_path_measurement(
        pdf_bytes,
        audit_payload,
        variant,
        page_sizes,
        engine_binding=engine_binding,
        warmups=warmups,
        samples=samples,
    )
    result = {
        "case_id": case_id,
        "source_path": source_path.relative_to(workspace).as_posix(),
        **source_binding,
        "audit_report_sha256": _sha256_json(audit_payload),
        "production_recovery_report_sha256": _sha256_json(
            recovery_payload
        ),
        "benchmark_recovery_variant_sha256": _sha256_json(variant),
        "recovery_variant": descriptor,
        "page_sizes_points": {
            str(page): [width, height]
            for page, (width, height) in page_sizes.items()
        },
        "real_production_path": real_production_path,
    }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _worker_healthy(
    workspace: Path,
    case_id: str,
    warmups: int,
    samples: int,
) -> int:
    source_path = (
        workspace / "benchmark-expertmodeldata" / f"{case_id}.pdf"
    )
    pdf_bytes = source_path.read_bytes()
    source_binding = _phase_0_source_binding(
        workspace,
        case_id,
        pdf_bytes,
    )

    from app.services.font_audit import audit_pdf_fonts
    from app.services.font_recovery import recover_pdf_font_text

    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    audit_payload = audit.model_dump(mode="json", exclude_none=True)
    recovery_payload = recovery.model_dump(mode="json", exclude_none=True)
    if audit_payload["findings"] or recovery_payload["refusals"]:
        raise RuntimeError(f"{case_id} is not a healthy planning control")
    page_sizes = _pdf_page_sizes(pdf_bytes)

    rss_before = _peak_rss_bytes()
    measured, durations = _measure_deterministic(
        lambda: _selective_operation(
            pdf_bytes,
            audit_payload,
            recovery_payload,
            page_sizes,
            fail_unavailable=False,
        ),
        warmups=warmups,
        samples=samples,
    )
    rss_after = _peak_rss_bytes()
    report = measured["report"]
    instrumentation = measured["instrumentation"]
    if (
        report["known_span_count"] != 0
        or report["terminal_outcome_count"] != 0
        or report["rendered_span_count"] != 0
        or report["rendered_pixel_count"] != 0
        or report["rendered_area_points2"] != 0
        or instrumentation["render_call_count"] != 0
    ):
        raise RuntimeError(f"{case_id} did not remain render-free")

    result = {
        "case_id": case_id,
        "source_path": source_path.relative_to(workspace).as_posix(),
        **source_binding,
        "audit_report_sha256": _sha256_json(audit_payload),
        "recovery_report_sha256": _sha256_json(recovery_payload),
        "warmup_count": warmups,
        "sample_count": samples,
        "planning_latency_ms": _distribution(durations),
        "planning_additive_overhead_percent": _distribution(
            [
                duration
                / float(source_binding["phase_0_parse_latency_ms"])
                * 100.0
                for duration in durations
            ]
        ),
        "deterministic": True,
        **measured,
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "_durations_ms": durations,
    }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _run_worker(
    workspace: Path,
    *,
    scenario: str,
    case_id: str | None,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "tests.benchmarks.selective_span_ocr_metrics",
        "worker",
        "--workspace",
        str(workspace),
        "--scenario",
        scenario,
        "--warmups",
        str(warmups),
        "--samples",
        str(samples),
    ]
    if case_id is not None:
        command.extend(["--case-id", case_id])
    completed = subprocess.run(
        command,
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise TypeError("selective benchmark worker must return a JSON object")
    return payload


def _collect(
    workspace: Path,
    *,
    warmups: int,
    samples: int,
    output: Path | None = None,
) -> dict[str, Any]:
    """Collect target, soft-failure, and healthy planning component metrics."""

    workspace = workspace.resolve()
    target = _run_worker(
        workspace,
        scenario="target",
        case_id=None,
        warmups=warmups,
        samples=samples,
    )
    real_target = _run_worker(
        workspace,
        scenario="real_target",
        case_id=None,
        warmups=warmups,
        samples=samples,
    )
    for binding_field in (
        "case_id",
        "source_sha256",
        "audit_report_sha256",
        "production_recovery_report_sha256",
        "benchmark_recovery_variant_sha256",
    ):
        if real_target.get(binding_field) != target.get(binding_field):
            raise RuntimeError(
                "real and deterministic target workers have different "
                f"{binding_field} bindings"
            )
    target["real_production_path"] = real_target.pop(
        "real_production_path"
    )
    target["real_production_worker_binding"] = real_target
    healthy_case_ids = [
        case_id
        for case_id in EXPECTED_CASE_IDS
        if case_id != "catastrophe-recap"
    ]
    controls = [
        _run_worker(
            workspace,
            scenario="healthy",
            case_id=case_id,
            warmups=warmups,
            samples=samples,
        )
        for case_id in healthy_case_ids
    ]

    healthy_durations: list[float] = []
    healthy_overheads: list[float] = []
    for control in controls:
        durations = [
            float(value) for value in control.pop("_durations_ms")
        ]
        healthy_durations.extend(durations)
        healthy_overheads.extend(
            duration
            / float(control["phase_0_parse_latency_ms"])
            * 100.0
            for duration in durations
        )
    success_durations = [
        float(value)
        for value in target.pop("_success_durations_ms")
    ]
    soft_failure_durations = [
        float(value)
        for value in target.pop("_soft_failure_durations_ms")
    ]

    success = target["mocked_selective_execution"]
    success_report = success["report"]
    soft_failure = target["ocr_unavailable_soft_failure"]
    soft_failure_report = soft_failure["report"]
    real_production = target["real_production_path"]
    real_report = real_production["report"]
    variant = target["recovery_variant"]
    target_font_ref = str(variant["target_font_ref"])
    neighbor_font_refs = set(variant["healthy_neighbor_font_refs"])
    success_requests = success["instrumentation"]["requests"]
    soft_failure_requests = soft_failure["instrumentation"]["requests"]
    neighbor_render_count = sum(
        str(request["font_ref"]) in neighbor_font_refs
        for request in [*success_requests, *soft_failure_requests]
    )
    target_request_count = sum(
        str(request["font_ref"]) == target_font_ref
        for request in [*success_requests, *soft_failure_requests]
    )
    candidate_rows = _candidate_evidence_rows(success_report)
    candidate_ids = [
        str(row["candidate_evidence_id"]) for row in candidate_rows
    ]
    token_ids = [
        str(token_id)
        for row in candidate_rows
        for token_id in row["token_evidence_ids"]
    ]
    real_candidate_rows = _candidate_evidence_rows(real_report)
    real_candidate_ids = [
        str(row["candidate_evidence_id"])
        for row in real_candidate_rows
    ]
    real_token_ids = [
        str(token_id)
        for row in real_candidate_rows
        for token_id in row["token_evidence_ids"]
    ]
    real_outcomes = [
        outcome
        for outcome in real_report["outcomes"]
        if isinstance(outcome, Mapping)
    ]
    real_costs = [
        outcome["cost"]
        for outcome in real_outcomes
        if isinstance(outcome.get("cost"), Mapping)
    ]
    real_terminal_coverage = (
        int(real_report["terminal_outcome_count"])
        / int(real_report["known_span_count"])
        if int(real_report["known_span_count"])
        else 0.0
    )
    real_neighbor_render_count = sum(
        str(outcome.get("font_ref")) in neighbor_font_refs
        for outcome in real_outcomes
        if isinstance(outcome.get("cost"), Mapping)
    )
    known_target_opportunities = int(
        success_report["known_span_count"]
    ) + int(soft_failure_report["known_span_count"])
    terminal_outcomes = int(
        success_report["terminal_outcome_count"]
    ) + int(soft_failure_report["terminal_outcome_count"])
    terminal_coverage = (
        terminal_outcomes / known_target_opportunities
        if known_target_opportunities
        else 0.0
    )
    healthy_render_calls = sum(
        int(control["instrumentation"]["render_call_count"])
        for control in controls
    )
    healthy_rendered_spans = sum(
        int(control["report"]["rendered_span_count"])
        for control in controls
    )
    healthy_rendered_pixels = sum(
        int(control["report"]["rendered_pixel_count"])
        for control in controls
    )
    healthy_rendered_area = sum(
        float(control["report"]["rendered_area_points2"])
        for control in controls
    )
    healthy_latency = _distribution(healthy_durations)
    healthy_overhead = _distribution(healthy_overheads)
    ceiling = _conservative_healthy_p95_ceiling(
        workspace,
        healthy_overhead["p95"],
    )
    target_area_ratio = sum(
        float(outcome["cost"]["page_area_ratio"])
        for outcome in success_report["outcomes"]
        if isinstance(outcome.get("cost"), Mapping)
    )
    maximum_crop_pixels = max(
        (
            int(outcome["cost"]["pixel_count"])
            for outcome in success_report["outcomes"]
            if isinstance(outcome.get("cost"), Mapping)
        ),
        default=0,
    )
    real_area_ratio = sum(
        float(cost["page_area_ratio"]) for cost in real_costs
    )
    real_maximum_crop_pixels = max(
        (int(cost["pixel_count"]) for cost in real_costs),
        default=0,
    )
    engine_binding = real_production["tesseract_binding"]
    real_latency_samples = [
        float(value)
        for value in real_production["latency_samples_ms"]
    ]
    real_report_elapsed_samples = [
        float(value)
        for value in real_production["report_elapsed_samples_ms"]
    ]

    if terminal_coverage != 1.0:
        raise RuntimeError("not every unresolved target has a terminal outcome")
    if (
        neighbor_render_count
        or healthy_render_calls
        or healthy_rendered_spans
        or healthy_rendered_pixels
        or healthy_rendered_area
    ):
        raise RuntimeError("healthy neighbor/control selective rendering occurred")
    if target_request_count != known_target_opportunities:
        raise RuntimeError("selective requests did not stay on target fonts")
    if not candidate_rows or not all(
        bool(row["complete"]) for row in candidate_rows
    ):
        raise RuntimeError("selective candidate evidence is incomplete")
    if (
        len(set(candidate_ids)) != len(candidate_ids)
        or len(set(token_ids)) != len(token_ids)
    ):
        raise RuntimeError("selective candidate/token evidence IDs repeat")
    if (
        real_report["status"] != "complete"
        or int(real_report["known_span_count"]) != 4
        or int(real_report["terminal_outcome_count"]) != 4
        or int(real_report["rendered_span_count"]) != 4
        or real_terminal_coverage != 1.0
        or real_neighbor_render_count != 0
        or len(real_costs) != 4
        or not real_candidate_rows
        or not all(bool(row["complete"]) for row in real_candidate_rows)
        or len(set(real_candidate_ids)) != len(real_candidate_ids)
        or len(set(real_token_ids)) != len(real_token_ids)
        or real_area_ratio > 0.05
        or real_maximum_crop_pixels > 4_000_000
        or int(real_production["warmup_count"]) != warmups
        or int(real_production["sample_count"]) != samples
        or real_production["structurally_deterministic"] is not True
        or len(real_latency_samples) != samples
        or len(real_report_elapsed_samples) != samples
        or real_production["latency_ms"]
        != _distribution(real_latency_samples)
        or real_production["report_elapsed_ms"]
        != _distribution(real_report_elapsed_samples)
        or int(real_production["observed_peak_rss_bytes"]) <= 0
    ):
        raise RuntimeError(
            "real PDFium/Tesseract target measurement is incomplete"
        )
    if (
        engine_binding.get("version") != EXPECTED_TESSERACT_VERSION
        or engine_binding.get("traineddata_size_bytes")
        != EXPECTED_ENG_TRAINEDDATA_SIZE_BYTES
        or engine_binding.get("traineddata_sha256")
        != EXPECTED_ENG_TRAINEDDATA_SHA256
        or engine_binding.get("policy_binding_passed") is not True
    ):
        raise RuntimeError("real OCR environment is not policy-bound")
    if not ceiling["passes_target"]:
        raise RuntimeError("cumulative healthy p95 ceiling exceeds 10%")

    command = [
        sys.executable,
        "-m",
        "tests.benchmarks.selective_span_ocr_metrics",
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
        "record_kind": (
            "p02_us03_selective_span_ocr_component_metrics"
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "measurement_scope": (
            "isolated selective-span planning, deterministic OCR-unavailable "
            "soft failure, bounded mocked render/OCR execution, and one real "
            "production-path PDFium/local-Tesseract measurement series over "
            "the four catastrophe refusal targets; font audit/recovery and "
            "page-size preparation occur outside timed regions; no document "
            "pipeline, layout model, broad page OCR, network service, or "
            "candidate selection is invoked"
        ),
        "workspace": str(workspace),
        "command": command,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "real_selective_ocr": engine_binding,
        },
        "method": {
            "case_count": 1 + len(controls),
            "healthy_control_count": len(controls),
            "warmups_per_scenario": warmups,
            "samples_per_scenario": samples,
            "percentile": "nearest-rank",
            "isolation": (
                "one child process for the deterministic target/soft-failure "
                "pair, a separate child process for the real production "
                "warmups/sample series (whose selective renderer spawns one "
                "bounded worker per target), and one child process per "
                "healthy control"
            ),
            "timed_region": (
                "run_selective_span_ocr plus strict Pydantic mode=json "
                "serialization for deterministic samples; the real sample "
                "times one production run over all four targets including "
                "PDFium allocation, both local Tesseract passes, projection, "
                "and strict report validation; audit, recovery, page geometry, "
                "and source hash binding are precomputed"
            ),
            "target_variant": (
                "exact catastrophe source/audit with a test-only explicit "
                "recovery refusal for its real four-run object:25 font; real "
                "safe object:13 audit/recovery spans remain non-authority "
                "same-page neighbors"
            ),
            "mocked_execution": (
                "one request per bounded unresolved span; deterministic "
                "ImageRegion/OCRLine/OCRToken evidence at planned 5 px/pt "
                "dimensions; no rasterization, OCR executable, or model call"
            ),
            "real_execution": (
                "repeated untuned production calls over the exact same four "
                "real audit boxes, using the coordinator's default renderer, "
                "PDFium at the fixed 5 px/pt target, local Tesseract PSM 3/11, "
                "and the exact accepted English language asset; timing fields "
                "are ignored only for structural/evidence determinism; "
                "nearest-rank latency/report-elapsed distributions and peak "
                "RSS are retained separately from deterministic samples"
            ),
            "soft_failure": (
                "the render/OCR double raises OCRUnavailableError for every "
                "planned target; native/audit/recovery inputs remain intact"
            ),
            "source_identity": (
                "all 15 current PDF SHA-256 values match the immutable Phase "
                "0 source records; audit/recovery/variant JSON hashes are "
                "also retained per case"
            ),
            "rss": (
                "isolated-process peak RSS increment from after audit, "
                "recovery, and page-size preparation through all measured "
                "selective component samples; the real sample additionally "
                "records worker and spawned render-child peak RSS observations"
            ),
            "healthy_comparator": (
                "each external healthy planning duration divided by that "
                "case's immutable Phase 0 parse latency"
            ),
            "combined_ceiling": (
                "arithmetic sum of retained P02-US01 audit p95, retained "
                "P02-US02 recovery p95, and current healthy selective "
                "planning p95; conservative reference only, not a paired "
                "full-parser percentile"
            ),
        },
        "summary": {
            "case_count": 1 + len(controls),
            "exact_source_hash_count": 1 + len(controls),
            "deterministic_scenario_count": 2 + len(controls),
            "real_production_scenario_count": 1,
            "real_production_warmup_count": int(
                real_production["warmup_count"]
            ),
            "real_production_sample_count": int(
                real_production["sample_count"]
            ),
            "real_production_structurally_deterministic": bool(
                real_production["structurally_deterministic"]
            ),
            "real_production_measured_target_execution_count": (
                int(real_production["sample_count"])
                * int(real_report["known_span_count"])
            ),
            "unresolved_target_opportunity_count": (
                known_target_opportunities
            ),
            "unresolved_target_terminal_outcome_count": terminal_outcomes,
            "unresolved_target_terminal_coverage": terminal_coverage,
            "healthy_neighbor_span_count": int(
                variant["healthy_neighbor_span_count"]
            ),
            "healthy_neighbor_render_count": neighbor_render_count,
            "healthy_control_count": len(controls),
            "healthy_control_render_call_count": healthy_render_calls,
            "healthy_control_rendered_span_count": healthy_rendered_spans,
            "healthy_control_rendered_pixel_count": (
                healthy_rendered_pixels
            ),
            "healthy_control_rendered_area_points2": (
                healthy_rendered_area
            ),
            "candidate_count": int(success_report["candidate_count"]),
            "candidate_evidence_complete_count": sum(
                bool(row["complete"]) for row in candidate_rows
            ),
            "candidate_evidence_completeness": (
                sum(bool(row["complete"]) for row in candidate_rows)
                / len(candidate_rows)
            ),
            "unique_candidate_evidence_count": len(set(candidate_ids)),
            "token_count": int(success_report["token_count"]),
            "unique_token_evidence_count": len(set(token_ids)),
            "mocked_selective_rendered_span_count": int(
                success_report["rendered_span_count"]
            ),
            "mocked_selective_rendered_area_points2": float(
                success_report["rendered_area_points2"]
            ),
            "mocked_selective_rendered_page_area_ratio": (
                target_area_ratio
            ),
            "mocked_selective_rendered_pixel_count": int(
                success_report["rendered_pixel_count"]
            ),
            "maximum_selective_crop_pixel_count": maximum_crop_pixels,
            "real_production_target_opportunity_count": int(
                real_report["known_span_count"]
            ),
            "real_production_terminal_outcome_count": int(
                real_report["terminal_outcome_count"]
            ),
            "real_production_terminal_coverage": real_terminal_coverage,
            "real_production_healthy_neighbor_render_count": (
                real_neighbor_render_count
            ),
            "real_production_candidate_count": int(
                real_report["candidate_count"]
            ),
            "real_production_candidate_evidence_complete_count": sum(
                bool(row["complete"]) for row in real_candidate_rows
            ),
            "real_production_token_count": int(real_report["token_count"]),
            "real_production_unique_candidate_evidence_count": len(
                set(real_candidate_ids)
            ),
            "real_production_unique_token_evidence_count": len(
                set(real_token_ids)
            ),
            "real_production_rendered_span_count": int(
                real_report["rendered_span_count"]
            ),
            "real_production_rendered_area_points2": float(
                real_report["rendered_area_points2"]
            ),
            "real_production_rendered_page_area_ratio": real_area_ratio,
            "real_production_rendered_pixel_count": int(
                real_report["rendered_pixel_count"]
            ),
            "real_production_maximum_crop_pixel_count": (
                real_maximum_crop_pixels
            ),
            "real_production_latency_ms": dict(
                real_production["latency_ms"]
            ),
            "real_production_report_elapsed_ms": dict(
                real_production["report_elapsed_ms"]
            ),
            "real_production_observed_peak_rss_bytes": int(
                real_production["observed_peak_rss_bytes"]
            ),
            "real_production_observed_peak_rss_increment_bytes": int(
                real_production["observed_peak_rss_increment_bytes"]
            ),
            "accepted_tesseract_version": engine_binding["version"],
            "accepted_eng_traineddata_size_bytes": engine_binding[
                "traineddata_size_bytes"
            ],
            "accepted_eng_traineddata_sha256": engine_binding[
                "traineddata_sha256"
            ],
            "broad_page_render_count": 0,
            "document_model_invocation_count": 0,
            "mocked_selective_execution_latency_ms": _distribution(
                success_durations
            ),
            "ocr_unavailable_soft_failure_latency_ms": _distribution(
                soft_failure_durations
            ),
            "healthy_selective_planning_latency_ms": healthy_latency,
            "healthy_selective_planning_additive_overhead_percent": (
                healthy_overhead
            ),
            "combined_healthy_p95_ceiling_reference": ceiling,
            "max_isolated_peak_rss_increment_bytes": max(
                [
                    int(target["peak_rss_increment_bytes"]),
                    int(
                        real_production[
                            "observed_peak_rss_increment_bytes"
                        ]
                    ),
                    *[
                        int(control["peak_rss_increment_bytes"])
                        for control in controls
                    ],
                ]
            ),
        },
        "candidate_evidence": candidate_rows,
        "real_production_candidate_evidence": real_candidate_rows,
        "target": target,
        "healthy_controls": controls,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("run", "worker"):
        child = subparsers.add_parser(operation)
        child.add_argument("--workspace", type=Path, required=True)
        child.add_argument("--warmups", type=int, default=2)
        child.add_argument("--samples", type=int, default=10)
        if operation == "run":
            child.add_argument(
                "--output",
                type=Path,
                help=(
                    "also write the complete JSON result; the retained path "
                    f"is {DEFAULT_OUTPUT}"
                ),
            )
        else:
            child.add_argument(
                "--scenario",
                choices=("target", "real_target", "healthy"),
                required=True,
            )
            child.add_argument(
                "--case-id",
                choices=EXPECTED_CASE_IDS,
            )
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    if args.warmups < 0 or args.samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    if args.operation == "worker":
        if args.scenario == "target":
            if args.case_id is not None:
                raise ValueError("target worker does not accept --case-id")
            return _worker_target(
                workspace,
                args.warmups,
                args.samples,
            )
        if args.scenario == "real_target":
            if args.case_id is not None:
                raise ValueError(
                    "real target worker does not accept --case-id"
                )
            return _worker_real_target(
                workspace,
                args.warmups,
                args.samples,
            )
        if args.case_id is None or args.case_id == "catastrophe-recap":
            raise ValueError(
                "healthy worker requires a non-catastrophe --case-id"
            )
        return _worker_healthy(
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
