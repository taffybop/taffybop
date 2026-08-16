"""Reproducible P02-US04 text-reconciliation correctness and metrics.

The evidence classes in this runner are intentionally separate:

* ``actual_production_inputs`` use the immutable Phase 0 PDFs and raw parser
  outputs with the unmodified final-code font-audit, recovery, and selective
  OCR reports.
* ``actual_renderer_test_only_upstream`` reuses the real PDFium/Tesseract
  evidence retained by P02-US03, but preserves its explicit
  ``deterministic_test_only_recovery_refusal`` label.  It is not counted as an
  actual production selection result.
* ``deterministic_synthetic_controls`` exercise policy decisions that the
  approved corpus does not currently produce, including the OCR-win branch.

The approved 15-document corpus contains no scanned or mixed scanned/native
PDF.  It also has no reviewed registry of complete, typed reconciliation
candidate groups for the historical false/duplicate OCR observations.  This
runner therefore does not manufacture either kind of corpus claim.

Audit, recovery, selective routing, and IR preparation occur outside timed
regions.  Synthetic and actual-render controls time reconciliation plus strict
report serialization.  Actual-document timings are a conservative upper bound
that also includes legacy/canonical projection, invariant scans, structural
hashing, and strict serialization.  The healthy overhead is an isolated
additive component compared with retained Phase 0 per-case parse latency.  Its
arithmetic sum with the retained P02-US03 ceiling is not a paired full-parser
percentile.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import resource
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
P02_US03_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US03-selective-span-ocr-metrics.json"
)
CATASTROPHE_TRUTH = (
    "tracker/phase-00-baseline/evidence/"
    "P00-US02-catastrophe-truth.json"
)
CORPUS_MANIFEST = "tracker/benchmarks/llamaparse-15/manifest.json"
DEFAULT_OUTPUT = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US04-text-reconciliation-metrics.json"
)
CATASTROPHE_CASE_ID = "catastrophe-recap"
HEALTHY_OVERHEAD_TARGET_PERCENT = 10.0
TARGET_SENTENCE = (
    "Windstorm Éowyn in Ireland and the UK followed with $690 million "
    "(€620 million)."
)
EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS = 29
EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS = 26
EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS = 3
EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS = 2
EXPECTED_ACTUAL_CATASTROPHE_UNRESOLVED_RUNS = 27
EXPECTED_ACTUAL_CATASTROPHE_SELECTED_OWNERLESS_RUNS = 0
EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT = {
    "font-recovery-2052c75845712e2f0c50b389": "€620 million",
    "font-recovery-7c86ff071ee7c01e83ad963d": "Windstorm Éowyn ",
}
EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS = {
    "font-recovery-00f74f87a6ef83a02ee5c2fd",
    "font-recovery-04aba9c02dd0aa4b5dcf48ec",
    "font-recovery-0d8bbeb62d60b630b071493c",
    "font-recovery-133173690719b0326c427f51",
    "font-recovery-170da8a0d1639e8839af1983",
    "font-recovery-377212694926c1ac13d6f2af",
    "font-recovery-4b0aa1854870faaf1805fae2",
    "font-recovery-549be7bf6b38ebf93cf7ef2d",
    "font-recovery-5eea654bc9570b837af178fb",
    "font-recovery-5ef5da83ae873fe93e991b92",
    "font-recovery-611bdca6fe4386865eca8316",
    "font-recovery-7a4f121f6eff5a1e4db46f83",
    "font-recovery-8349d86fb938e6be9bf7aa3d",
    "font-recovery-83c5707f46d5320ef427002f",
    "font-recovery-8c439e685c9d30d9157533a4",
    "font-recovery-a3e1806afb6e4f2cd922e49c",
    "font-recovery-b1d0093ab9513a68fddf81de",
    "font-recovery-c5134685c37a02634526c160",
    "font-recovery-cf11bf71af8dcca6db0a8c46",
    "font-recovery-db97bc9559a6d82f221032c0",
    "font-recovery-dc610473aa99c8014c9f92fb",
    "font-recovery-de83c37a9a7b656eb367709d",
    "font-recovery-dfb78e51e0a49c09592a9b5e",
    "font-recovery-eb353a99e490b7d748bb94ce",
}
EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS = {
    "font-recovery-c88b58fd72009ab618b76eec",
    "font-recovery-ca29fe39da5c208c350783c8",
    "font-recovery-f4bf0927d43e6816053bb831",
}
EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID = (
    "el-45cc69113896661ffd89"
)
EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID = "p1-i2"
EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID = (
    "el-05e74d7032a69bdc451e"
)
EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID = "p1-i5"
EXPECTED_REVIEWED_CATASTROPHE_REGIONS = 24
EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES = 4
POLICY_ID = "text-reconciliation-v1"
POLICY_PATH = (
    "tracker/phase-02-text-integrity/decisions/"
    "P02-text-reconciliation-policy.md"
)
PRODUCTION_RECONCILIATION_CODE = "app/services/text_reconciliation.py"
PRODUCTION_IR_CODE = "app/services/ir.py"
PRODUCTION_PRESENTATION_CODE = "app/services/presentation.py"

EXPECTED_RETAINED_SHA256 = {
    "phase_0": "aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2",
    "p02_us01": "b9fe7452f49de5ef36980ba05d0d58d07c2516ec576ba23911696b4b35db9f3d",
    "p02_us02": "7f418317fd93efc320896adc1472b35140fad102abddacc07a4ba51eceec5a39",
    "p02_us03": "1e6af0c9354b7357bb1a09c0c9a2b3b832d2cd70a3169977b8259d61e111b074",
    "catastrophe_truth": "d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac",
    "corpus_manifest": "16736d189fa38ed10de9755abc181743d87d3199e8cb6275afa32ee39c96a052",
    "policy": "2b3086d4cf21833f1b58ac2e2e75756216e31f7895abca7e8dbc2edc376cdb2c",
}

_PayloadT = TypeVar("_PayloadT", bound=Mapping[str, Any])


def _nearest_rank(values: list[float], percentile: float) -> float:
    """Return the nearest-rank percentile used by retained Phase 2 evidence."""

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
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _structural_report_sha256(value: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(value))
    if "elapsed_ms" in payload:
        payload["elapsed_ms"] = 0.0
    return _sha256_json(payload)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _file_identity(workspace: Path, relative_path: str) -> dict[str, Any]:
    content = (workspace / relative_path).read_bytes()
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _code_bindings(workspace: Path) -> dict[str, dict[str, Any]]:
    return {
        "text_reconciliation": _file_identity(
            workspace,
            PRODUCTION_RECONCILIATION_CODE,
        ),
        "ir": _file_identity(workspace, PRODUCTION_IR_CODE),
        "presentation": _file_identity(
            workspace,
            PRODUCTION_PRESENTATION_CODE,
        ),
        "metrics_runner": _file_identity(
            workspace,
            "tests/benchmarks/text_reconciliation_metrics.py",
        ),
    }


def _phase_0_cases(workspace: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(workspace / PHASE_0_RUN)
    if payload.get("record_kind") != "p00-us10-corpus-run":
        raise RuntimeError("unexpected retained Phase 0 run kind")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise TypeError("Phase 0 run record must contain a cases list")
    result = {str(case["case_id"]): case for case in cases}
    if tuple(result) != EXPECTED_CASE_IDS:
        raise RuntimeError("retained Phase 0 case order or membership drifted")
    return result


def _source_artifact(case: Mapping[str, Any]) -> Mapping[str, Any]:
    sources = [
        artifact
        for artifact in case.get("source_triplet", [])
        if isinstance(artifact, Mapping) and artifact.get("role") == "source"
    ]
    if len(sources) != 1:
        raise RuntimeError(
            f"{case.get('case_id')} must have exactly one source artifact"
        )
    return sources[0]


def _phase_0_case_binding(
    workspace: Path,
    case_id: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    """Load and verify one immutable PDF plus its retained raw parser output."""

    try:
        case = _phase_0_cases(workspace)[case_id]
    except KeyError as exc:
        raise KeyError(f"unknown Phase 0 case {case_id!r}") from exc
    source = _source_artifact(case)
    source_path = workspace / str(source["path"])
    pdf_bytes = source_path.read_bytes()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if (
        source_sha256 != source.get("sha256")
        or len(pdf_bytes) != int(source["size_bytes"])
    ):
        raise RuntimeError(f"{case_id} source differs from Phase 0")

    output = case.get("output")
    raw_json = output.get("raw_json") if isinstance(output, Mapping) else None
    if not isinstance(raw_json, Mapping):
        raise RuntimeError(f"{case_id} has no retained Phase 0 raw JSON")
    raw_path = workspace / str(raw_json["path"])
    raw_bytes = raw_path.read_bytes()
    if (
        hashlib.sha256(raw_bytes).hexdigest() != raw_json.get("sha256")
        or len(raw_bytes) != int(raw_json["size_bytes"])
    ):
        raise RuntimeError(f"{case_id} raw output differs from Phase 0")
    document = json.loads(raw_bytes)
    if not isinstance(document, dict):
        raise TypeError(f"{case_id} raw output must be a JSON object")
    if document.get("document", {}).get("sha256") != source_sha256:
        raise RuntimeError(f"{case_id} raw output has a foreign source hash")

    binding = {
        "case_id": case_id,
        "source_path": str(source["path"]),
        "source_sha256": source_sha256,
        "source_size_bytes": len(pdf_bytes),
        "phase_0_run_id": str(case["run_id"]),
        "phase_0_parse_latency_ms": float(case["parse_latency_ms"]),
        "phase_0_peak_rss_bytes": int(case["peak_rss_bytes"]),
        "phase_0_environment_sha256": str(case["environment_sha256"]),
        "phase_0_raw_output": {
            "path": str(raw_json["path"]),
            "sha256": str(raw_json["sha256"]),
            "size_bytes": int(raw_json["size_bytes"]),
        },
    }
    return pdf_bytes, document, binding


def _retained_inputs(workspace: Path) -> dict[str, Any]:
    """Load and validate the chained P02-US01 through P02-US03 evidence."""

    identities = {
        "phase_0": _file_identity(workspace, PHASE_0_RUN),
        "p02_us01": _file_identity(workspace, P02_US01_METRICS),
        "p02_us02": _file_identity(workspace, P02_US02_METRICS),
        "p02_us03": _file_identity(workspace, P02_US03_METRICS),
        "catastrophe_truth": _file_identity(workspace, CATASTROPHE_TRUTH),
        "corpus_manifest": _file_identity(workspace, CORPUS_MANIFEST),
        "policy": _file_identity(workspace, POLICY_PATH),
    }
    for label, expected_sha256 in EXPECTED_RETAINED_SHA256.items():
        if identities[label]["sha256"] != expected_sha256:
            raise RuntimeError(
                f"approved retained {label} artifact identity drifted"
            )
    us01 = _load_json(workspace / P02_US01_METRICS)
    us02 = _load_json(workspace / P02_US02_METRICS)
    us03 = _load_json(workspace / P02_US03_METRICS)
    expected_kinds = (
        (
            us01,
            "p02_us01_font_audit_component_metrics_summary",
            "P02-US01",
        ),
        (us02, "p02_us02_font_recovery_component_metrics", "P02-US02"),
        (
            us03,
            "p02_us03_selective_span_ocr_component_metrics",
            "P02-US03",
        ),
    )
    for payload, expected_kind, label in expected_kinds:
        if payload.get("record_kind") != expected_kind:
            raise RuntimeError(f"unexpected retained {label} metrics kind")

    us02_summary = us02["summary"]
    if (
        us02_summary["retained_p02_us01_metrics_sha256"]
        != identities["p02_us01"]["sha256"]
    ):
        raise RuntimeError("P02-US02 no longer binds retained P02-US01")
    us03_ceiling = us03["summary"][
        "combined_healthy_p95_ceiling_reference"
    ]
    retained_artifacts = us03_ceiling["retained_artifacts"]
    if (
        retained_artifacts["p02_us01"]["sha256"]
        != identities["p02_us01"]["sha256"]
        or retained_artifacts["p02_us02"]["sha256"]
        != identities["p02_us02"]["sha256"]
        or bool(us03_ceiling["observed_paired_full_parser_percentile"])
    ):
        raise RuntimeError("P02-US03 retained ceiling bindings drifted")
    us03_ceiling_percent = float(us03_ceiling["arithmetic_ceiling_percent"])
    if (
        not math.isfinite(us03_ceiling_percent)
        or us03_ceiling_percent < 0
        or us03_ceiling_percent > HEALTHY_OVERHEAD_TARGET_PERCENT
    ):
        raise RuntimeError("P02-US03 retained ceiling is invalid")

    catastrophe = next(
        case
        for case in us02["cases"]
        if case["case_id"] == CATASTROPHE_CASE_ID
    )
    correctness = catastrophe["correctness"]
    if (
        correctness["target_sentence"] != TARGET_SENTENCE
        or int(correctness["recovered_run_count"])
        != EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS
        or int(correctness["reviewed_region_count"])
        != EXPECTED_REVIEWED_CATASTROPHE_REGIONS
        or not bool(correctness["all_reviewed_regions_exact"])
    ):
        raise RuntimeError("retained P02-US02 catastrophe truth drifted")
    return {
        "identities": identities,
        "p02_us01": us01,
        "p02_us02": us02,
        "p02_us03": us03,
        "retained_p02_us03_ceiling_percent": us03_ceiling_percent,
        "catastrophe_correctness": correctness,
    }


def _reciprocal_overlap(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> dict[str, float]:
    """Return intersection divided by each positive page-point box area."""

    def coordinates(box: Mapping[str, Any]) -> tuple[float, float, float, float]:
        x = float(box["x"])
        y = float(box["y"])
        width = float(box.get("width", box.get("w")))
        height = float(box.get("height", box.get("h")))
        values = (x, y, width, height)
        if (
            any(not math.isfinite(value) for value in values)
            or width <= 0
            or height <= 0
            or box.get("unit") != "pt"
        ):
            raise ValueError("overlap boxes must be finite positive page points")
        return x, y, width, height

    first_x, first_y, first_width, first_height = coordinates(first)
    second_x, second_y, second_width, second_height = coordinates(second)
    intersection_width = max(
        min(first_x + first_width, second_x + second_width)
        - max(first_x, second_x),
        0.0,
    )
    intersection_height = max(
        min(first_y + first_height, second_y + second_height)
        - max(first_y, second_y),
        0.0,
    )
    intersection_area = intersection_width * intersection_height
    return {
        "intersection_points2": intersection_area,
        "first_area_ratio": intersection_area / (first_width * first_height),
        "second_area_ratio": intersection_area
        / (second_width * second_height),
    }


def _fixture_limitations(
    workspace: Path,
    retained: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the corpus gaps instead of silently promoting synthetic inputs."""

    manifest = _load_json(workspace / CORPUS_MANIFEST)
    manifest_cases = manifest.get("cases")
    if not isinstance(manifest_cases, list):
        raise TypeError("corpus manifest must contain cases")
    scan_rows = [
        {
            "case_id": str(case["case_id"]),
            "scanned_candidate": bool(
                case.get("source", {}).get("scanned_candidate")
            ),
            "mixed_native_and_scanned_candidate": bool(
                case.get("source", {}).get(
                    "mixed_native_and_scanned_candidate"
                )
            ),
        }
        for case in manifest_cases
    ]
    if (
        tuple(row["case_id"] for row in scan_rows) != EXPECTED_CASE_IDS
        or any(
            row["scanned_candidate"]
            or row["mixed_native_and_scanned_candidate"]
            for row in scan_rows
        )
    ):
        raise RuntimeError("approved corpus scan classification drifted")

    us03 = retained["p02_us03"]
    target = us03["target"]
    variant = target["recovery_variant"]
    if variant.get("variant_kind") != (
        "deterministic_test_only_recovery_refusal"
    ):
        raise RuntimeError("retained P02-US03 refusal label drifted")
    real_report = target["real_production_path"]["report"]
    outcomes = [
        outcome
        for outcome in real_report.get("outcomes", [])
        if isinstance(outcome, Mapping)
    ]
    overlap_rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        candidates = [
            candidate
            for candidate in outcome.get("candidates", [])
            if isinstance(candidate, Mapping)
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "retained actual-render outcome must have one candidate"
            )
        overlap = _reciprocal_overlap(
            outcome["source_bbox"],
            candidates[0]["bbox"],
        )
        overlap_rows.append(
            {
                "span_id": outcome["span_id"],
                "candidate_evidence_id": candidates[0]["evidence_id"],
                "source_bbox_area_overlap": overlap["first_area_ratio"],
                "candidate_bbox_area_overlap": overlap["second_area_ratio"],
                "passes_policy_minimum": min(
                    overlap["first_area_ratio"],
                    overlap["second_area_ratio"],
                )
                >= 0.80,
            }
        )
    if (
        len(overlap_rows) != EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES
        or any(row["passes_policy_minimum"] for row in overlap_rows)
    ):
        raise RuntimeError(
            "retained actual-render geometry no longer demonstrates the "
            "documented fixture limitation"
        )
    return {
        "approved_corpus_case_count": len(scan_rows),
        "approved_scanned_candidate_count": sum(
            row["scanned_candidate"] for row in scan_rows
        ),
        "approved_mixed_native_scanned_candidate_count": sum(
            row["mixed_native_and_scanned_candidate"] for row in scan_rows
        ),
        "actual_production_ocr_win_fixture_available": False,
        "actual_renderer_evidence_upstream_kind": variant["variant_kind"],
        "actual_renderer_candidate_target_overlap": overlap_rows,
        "reviewed_typed_false_duplicate_candidate_registry_available": False,
        "limitations": [
            (
                "The approved 15-document corpus contains no scanned or "
                "mixed native/scanned PDF, and unmodified production recovery "
                "leaves no selective-OCR target that can establish an actual "
                "production OCR-win result."
            ),
            (
                "The four actual PDFium/Tesseract candidates retained by "
                "P02-US03 require a deterministic test-only recovery refusal "
                "and fail the frozen 0.80 reciprocal target-overlap gate."
            ),
            (
                "Historical reviewed false/duplicate OCR observations are "
                "not registered as complete typed P02-US04 candidate groups; "
                "this runner does not manufacture a corpus-wide candidate "
                "selection claim from prose observations."
            ),
        ],
    }


def _combined_healthy_ceiling(
    retained: Mapping[str, Any],
    reconciliation_p95_percent: float,
) -> dict[str, Any]:
    if (
        not math.isfinite(reconciliation_p95_percent)
        or reconciliation_p95_percent < 0
    ):
        raise ValueError(
            "reconciliation p95 overhead must be finite and non-negative"
        )
    retained_percent = float(
        retained["retained_p02_us03_ceiling_percent"]
    )
    arithmetic = retained_percent + reconciliation_p95_percent
    return {
        "retained_p02_us03_arithmetic_ceiling_percent": retained_percent,
        "reconciliation_p95_percent": reconciliation_p95_percent,
        "arithmetic_ceiling_percent": arithmetic,
        "target_percent": HEALTHY_OVERHEAD_TARGET_PERCENT,
        "passes_target": arithmetic <= HEALTHY_OVERHEAD_TARGET_PERCENT,
        "observed_paired_full_parser_percentile": False,
        "retained_artifacts": deepcopy(retained["identities"]),
    }


def _environment_compatibility(
    workspace: Path,
    retained: Mapping[str, Any],
) -> dict[str, Any]:
    """Require the historical latency denominator's hardware/runtime class."""

    import psutil

    retained_environment = retained["p02_us03"]["environment"]
    phase_0_environment = _load_json(workspace / PHASE_0_RUN).get(
        "environment"
    )
    if not isinstance(phase_0_environment, Mapping):
        raise RuntimeError("retained Phase 0 environment is unavailable")
    current = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "total_memory_bytes": int(psutil.virtual_memory().total),
    }
    expected = {
        key: phase_0_environment[key] for key in current
    }
    mismatches = {
        key: {"expected": expected[key], "observed": current[key]}
        for key in current
        if current[key] != expected[key]
    }
    if mismatches:
        raise RuntimeError(
            "current environment is incompatible with Phase 0 latency "
            f"denominators: {mismatches}"
        )
    return {
        "compatible": True,
        "current": current,
        "phase_0_environment_sha256": retained["p02_us03"]["target"][
            "phase_0_environment_sha256"
        ],
        "retained_p02_us03_environment": retained_environment,
    }


def _measure_deterministic(
    operation: Callable[[], _PayloadT],
    *,
    warmups: int,
    samples: int,
) -> tuple[dict[str, Any], list[float]]:
    """Measure an operation and require byte-stable normalized payloads."""

    if warmups < 0 or samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    reference_bytes: bytes | None = None
    for _ in range(warmups):
        payload = dict(operation())
        payload_bytes = _canonical_json(payload)
        if reference_bytes is None:
            reference_bytes = payload_bytes
        elif payload_bytes != reference_bytes:
            raise RuntimeError("operation changed during warmup")

    durations_ms: list[float] = []
    first: dict[str, Any] | None = None
    first_bytes: bytes | None = None
    for _ in range(samples):
        started = perf_counter()
        payload = dict(operation())
        durations_ms.append((perf_counter() - started) * 1000.0)
        payload_bytes = _canonical_json(payload)
        if first is None:
            first = payload
            first_bytes = payload_bytes
        elif payload_bytes != first_bytes:
            raise RuntimeError("operation changed across measured samples")

    if first is None or first_bytes is None:
        raise RuntimeError("measurement produced no samples")
    if reference_bytes is not None and reference_bytes != first_bytes:
        raise RuntimeError("warmup and measured operation differ")
    return first, durations_ms


def _constant_clock() -> float:
    """Make report elapsed fields stable while external latency remains real."""

    return 100.0


def _pdf_page_sizes(pdf_bytes: bytes) -> dict[int, tuple[float, float]]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf_bytes)
    sizes: dict[int, tuple[float, float]] = {}
    try:
        for page_index in range(1, len(document) + 1):
            page = document[page_index - 1]
            try:
                sizes[page_index] = tuple(
                    float(value) for value in page.get_size()
                )
            finally:
                page.close()
    finally:
        document.close()
    return sizes


def _prepare_actual_p02_us03_case(
    workspace: Path,
    case_id: str,
) -> dict[str, Any]:
    """Prepare the real finalized P02-US03 component input for reconciliation."""

    pdf_bytes, document, binding = _phase_0_case_binding(workspace, case_id)

    from app.services.font_audit import audit_pdf_fonts
    from app.services.font_recovery import recover_pdf_font_text
    from app.services.ir import round_trip_document
    from app.services.selective_span_ocr import run_selective_span_ocr

    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    page_sizes = _pdf_page_sizes(pdf_bytes)
    selective = run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        page_sizes,
        tesseract_cmd="",
        languages=("eng",),
    )
    audit_payload = audit.model_dump(mode="json", exclude_none=True)
    recovery_payload = recovery.model_dump(mode="json", exclude_none=True)
    selective_payload = selective.model_dump(mode="json", exclude_none=True)
    for label, payload in (
        ("font audit", audit_payload),
        ("font recovery", recovery_payload),
        ("selective OCR", selective_payload),
    ):
        if payload.get("source_sha256") != binding["source_sha256"]:
            raise RuntimeError(f"{case_id} {label} source binding drifted")
    if selective_payload.get("known_span_count") != 0:
        raise RuntimeError(
            f"{case_id} unmodified production input unexpectedly routed OCR"
        )
    projection, ir = round_trip_document(
        document,
        font_audit=audit_payload,
        font_recovery=recovery_payload,
        selective_span_ocr=selective_payload,
    )
    if ir.source_sha256 != binding["source_sha256"]:
        raise RuntimeError(f"{case_id} prepared IR source binding drifted")
    recovery_ownership = _recovery_ownership(ir)
    recovery_run_ids = {
        str(run["evidence_id"])
        for run in recovery_payload.get("runs", [])
        if isinstance(run, Mapping) and run.get("evidence_id")
    }
    observed_owned_run_ids = {
        *recovery_ownership["owner_linked_run_evidence_ids"],
        *recovery_ownership["ownerless_run_evidence_ids"],
    }
    if recovery_run_ids != observed_owned_run_ids:
        raise RuntimeError(
            f"{case_id} recovery ownership does not cover exact run evidence"
        )
    font_decision_evidence_bindings = (
        _font_decision_evidence_bindings(ir, recovery_payload)
        if recovery_run_ids
        else []
    )
    audit_sha256 = _sha256_json(audit_payload)
    recovery_sha256 = _sha256_json(recovery_payload)
    selective_sha256 = _structural_report_sha256(selective_payload)
    retained_us03 = _load_json(workspace / P02_US03_METRICS)
    if case_id == CATASTROPHE_CASE_ID:
        retained_case = retained_us03["target"]
        retained_recovery_sha256 = retained_case[
            "production_recovery_report_sha256"
        ]
        if (
            retained_case["source_sha256"] != binding["source_sha256"]
            or retained_case["audit_report_sha256"] != audit_sha256
            or retained_recovery_sha256 != recovery_sha256
        ):
            raise RuntimeError(
                "actual catastrophe inputs differ from retained P02-US03"
            )
    else:
        retained_case = next(
            control
            for control in retained_us03["healthy_controls"]
            if control["case_id"] == case_id
        )
        if (
            retained_case["source_sha256"] != binding["source_sha256"]
            or retained_case["audit_report_sha256"] != audit_sha256
            or retained_case["recovery_report_sha256"] != recovery_sha256
            or _structural_report_sha256(retained_case["report"])
            != selective_sha256
        ):
            raise RuntimeError(
                f"{case_id} inputs differ from retained P02-US03"
            )
    return {
        "pdf_bytes": pdf_bytes,
        "document": document,
        "binding": binding,
        "audit": audit_payload,
        "recovery": recovery_payload,
        "selective": selective_payload,
        "p02_us03_projection": projection,
        "p02_us03_ir": ir,
        "p02_us03_ir_fingerprint": _ir_fingerprint(ir),
        "p02_us03_presentation": _presentation_payload(ir),
        "recovery_ownership": recovery_ownership,
        "font_decision_evidence_bindings": (
            font_decision_evidence_bindings
        ),
        "audit_report_sha256": audit_sha256,
        "recovery_report_sha256": recovery_sha256,
        "selective_report_sha256": selective_sha256,
    }


def _recovery_ownership(ir: Any) -> dict[str, Any]:
    """Count exact recovery-run ownership without conflating evidence copies."""

    linked_run_ids: set[str] = set()
    for element in ir.elements:
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        for row in legacy.get("font_recovery_alternatives", []):
            if isinstance(row, Mapping) and row.get("run_evidence_id"):
                linked_run_ids.add(str(row["run_evidence_id"]))

    alternative_targets = {
        str(relationship.source_id): str(relationship.target_id)
        for relationship in ir.relationships
        if str(relationship.type.value) == "alternative_of"
    }
    ownerless_run_ids: set[str] = set()
    for element in ir.elements:
        metadata = element.properties.get("font_recovery")
        if (
            isinstance(metadata, Mapping)
            and metadata.get("run_evidence_id")
            and element.id not in alternative_targets
        ):
            ownerless_run_ids.add(str(metadata["run_evidence_id"]))
    if linked_run_ids & ownerless_run_ids:
        raise RuntimeError("recovery run is both owner-linked and ownerless")
    return {
        "owner_linked_run_count": len(linked_run_ids),
        "ownerless_run_count": len(ownerless_run_ids),
        "owner_linked_run_evidence_ids": sorted(linked_run_ids),
        "ownerless_run_evidence_ids": sorted(ownerless_run_ids),
    }


def _count_text(value: Any, target: str) -> int:
    """Count exact target occurrences in all retained string leaves."""

    if isinstance(value, str):
        return value.count(target)
    if isinstance(value, Mapping):
        return sum(_count_text(item, target) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return sum(_count_text(item, target) for item in value)
    return 0


def _presentation_payload(ir: Any) -> dict[str, Any]:
    from app.services.presentation import build_canonical_presentation

    presentation = build_canonical_presentation(ir)
    return presentation.model_dump(mode="json", exclude_none=True)


def _canonical_element_block_counts(
    presentation: Mapping[str, Any],
) -> Counter[str]:
    """Count blocks in which each IR element contributes canonically."""

    counts: Counter[str] = Counter()
    for page in presentation.get("pages", []):
        if not isinstance(page, Mapping):
            continue
        for block in page.get("blocks", []):
            if (
                not isinstance(block, Mapping)
                or block.get("omission_reason")
            ):
                continue
            element_ids = {
                str(value)
                for value in (
                    block.get("primary_element_id"),
                    *block.get("contributing_element_ids", []),
                )
                if isinstance(value, str) and value
            }
            counts.update(element_ids)
    return counts


def _ir_fingerprint(ir: Any) -> dict[str, Any]:
    payload = ir.model_dump(mode="json", exclude_none=True)
    return {
        "sha256": _sha256_json(payload),
        "page_count": len(payload.get("pages", [])),
        "element_count": len(payload.get("elements", [])),
        "evidence_count": len(payload.get("evidence", [])),
        "relationship_count": len(payload.get("relationships", [])),
        "concern_count": len(payload.get("concerns", [])),
    }


def _exact_parity(
    left_projection: Mapping[str, Any],
    left_ir: Any,
    right_projection: Mapping[str, Any],
    right_ir: Any,
) -> dict[str, Any]:
    left_ir_payload = left_ir.model_dump(mode="json", exclude_none=True)
    right_ir_payload = right_ir.model_dump(mode="json", exclude_none=True)
    left_presentation = _presentation_payload(left_ir)
    right_presentation = _presentation_payload(right_ir)
    projection_equal = _canonical_json(left_projection) == _canonical_json(
        right_projection
    )
    ir_equal = _canonical_json(left_ir_payload) == _canonical_json(
        right_ir_payload
    )
    presentation_equal = _canonical_json(
        left_presentation
    ) == _canonical_json(right_presentation)
    return {
        "projection_byte_equivalent": projection_equal,
        "ir_byte_equivalent": ir_equal,
        "canonical_presentation_byte_equivalent": presentation_equal,
        "exact": projection_equal and ir_equal and presentation_equal,
        "left_projection_sha256": _sha256_json(left_projection),
        "right_projection_sha256": _sha256_json(right_projection),
        "left_ir_sha256": _sha256_json(left_ir_payload),
        "right_ir_sha256": _sha256_json(right_ir_payload),
        "left_presentation_sha256": _sha256_json(left_presentation),
        "right_presentation_sha256": _sha256_json(right_presentation),
    }


def _report_coverage(
    report: Mapping[str, Any],
    input_groups: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute evidence/reason/alternative and no-completion invariants."""

    def finite_unit_number(value: Any) -> bool:
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(float(value))
            and 0 <= float(value) <= 1
        )

    def nonempty_unique_strings(value: Any) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value))
        )

    outcomes = [
        outcome
        for outcome in report.get("outcomes", [])
        if isinstance(outcome, Mapping)
    ]
    reason_complete = 0
    evidence_complete = 0
    alternatives_complete = 0
    canonical_once = 0
    semantic_completions = 0
    duplicate_occurrences = 0
    schema_complete = 0
    expected_component_scores = {
        "authority",
        "independence",
        "mapping_safety",
        "geometry",
        "replacement_scope",
        "completeness",
        "script",
        "confidence",
    }
    for outcome in outcomes:
        if isinstance(outcome.get("reason_code"), str) and outcome[
            "reason_code"
        ]:
            reason_complete += 1
        decisions = [
            row
            for row in outcome.get("decisions", [])
            if isinstance(row, Mapping)
        ]
        decision_ids = [
            str(row.get("candidate_id") or "") for row in decisions
        ]
        decision_schema_complete = (
            bool(decisions)
            and len(decision_ids) == len(set(decision_ids))
            and all(
                isinstance(row.get("candidate_id"), str)
                and bool(row["candidate_id"])
                and isinstance(row.get("text"), str)
                and bool(row["text"])
                and nonempty_unique_strings(row.get("evidence_ids"))
                and isinstance(row.get("bbox"), Mapping)
                and row.get("source_kind")
                and row.get("mapping_safety")
                and row.get("method")
                and row.get("lineage_family")
                and row.get("origin_asset_id")
                and isinstance(row.get("component_scores"), Mapping)
                and set(row["component_scores"])
                == expected_component_scores
                and all(
                    finite_unit_number(value)
                    for value in row["component_scores"].values()
                )
                and finite_unit_number(row.get("total_score"))
                and "confidence" in row
                and (
                    row["confidence"] is None
                    or finite_unit_number(row["confidence"])
                )
                and finite_unit_number(
                    row.get("candidate_target_overlap")
                )
                and finite_unit_number(
                    row.get("target_candidate_overlap")
                )
                and finite_unit_number(
                    row.get("owner_target_overlap")
                )
                and finite_unit_number(
                    row.get("target_owner_overlap")
                )
                and not isinstance(
                    row.get("independent_support_count"),
                    bool,
                )
                and isinstance(
                    row.get("independent_support_count"),
                    int,
                )
                and row["independent_support_count"] >= 1
                and nonempty_unique_strings(row.get("reason_codes"))
                and isinstance(row.get("observed_scripts"), list)
                and all(
                    isinstance(value, str) and value
                    for value in row["observed_scripts"]
                )
                and row["observed_scripts"]
                == sorted(set(row["observed_scripts"]))
                and isinstance(row.get("eligible"), bool)
                and isinstance(row.get("selected"), bool)
                for row in decisions
            )
        )
        if decision_schema_complete:
            evidence_complete += 1
        if (
            decision_schema_complete
            and outcome.get("rule_version") == "1.0"
            and isinstance(outcome.get("group_id"), str)
            and bool(outcome["group_id"])
            and isinstance(outcome.get("span_id"), str)
            and bool(outcome["span_id"])
            and isinstance(outcome.get("owner_element_id"), str)
            and bool(outcome["owner_element_id"])
            and not isinstance(outcome.get("page_index"), bool)
            and isinstance(outcome.get("page_index"), int)
            and outcome["page_index"] >= 1
            and isinstance(outcome.get("target_bbox"), Mapping)
            and "margin" in outcome
            and (
                outcome["margin"] is None
                or (
                    not isinstance(outcome["margin"], bool)
                    and isinstance(outcome["margin"], (int, float))
                    and math.isfinite(float(outcome["margin"]))
                )
            )
            and outcome.get("status")
            in {"selected", "unchanged", "unresolved"}
            and outcome.get("replacement_mode")
            in {"none", "whole_owner", "unique_substring"}
            and isinstance(outcome.get("selected_candidate_ids"), list)
            and "selected_text" in outcome
        ):
            schema_complete += 1

        selected_ids = [
            str(value)
            for value in outcome.get("selected_candidate_ids", [])
        ]
        if len(selected_ids) != len(set(selected_ids)):
            duplicate_occurrences += len(selected_ids) - len(set(selected_ids))
        if input_groups is None:
            alternatives_complete += int(bool(decisions))
        else:
            group_id = str(outcome.get("group_id") or "")
            group = input_groups.get(group_id)
            expected_candidates = (
                [
                    row
                    for row in group.get("candidates", [])
                    if isinstance(row, Mapping)
                ]
                if isinstance(group, Mapping)
                else []
            )
            expected_ids = {
                str(candidate["candidate_id"])
                for candidate in expected_candidates
            }
            observed_ids = {
                str(row["candidate_id"]) for row in decisions
            }
            alternatives_complete += int(
                observed_ids == expected_ids
                and all(
                    next(
                        candidate
                        for candidate in expected_candidates
                        if candidate["candidate_id"] == decision["candidate_id"]
                    )["evidence_ids"]
                    == decision["evidence_ids"]
                    for decision in decisions
                )
            )
            selected_text = outcome.get("selected_text")
            if selected_text is not None and selected_text not in {
                candidate.get("text")
                for candidate in expected_candidates
                if str(candidate.get("candidate_id")) in selected_ids
            }:
                semantic_completions += 1

        if outcome.get("selected_text") is not None:
            canonical_once += int(len(selected_ids) == 1)

    denominator = len(outcomes)
    return {
        "outcome_count": denominator,
        "reason_complete_count": reason_complete,
        "reason_coverage": (
            reason_complete / denominator if denominator else 1.0
        ),
        "evidence_complete_count": evidence_complete,
        "evidence_coverage": (
            evidence_complete / denominator if denominator else 1.0
        ),
        "schema_complete_count": schema_complete,
        "schema_coverage": (
            schema_complete / denominator if denominator else 1.0
        ),
        "alternatives_complete_count": alternatives_complete,
        "alternative_retention": (
            alternatives_complete / denominator if denominator else 1.0
        ),
        "canonical_once_count": canonical_once,
        "canonical_duplicate_count": duplicate_occurrences,
        "semantic_completion_count": semantic_completions,
    }


def _synthetic_groups() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build bounded policy controls that are never labeled corpus evidence."""

    from tests.fixtures.phase_02.text_reconciliation import (
        candidate,
        group,
        reconciliation_cases,
    )

    groups: list[dict[str, Any]] = []
    expected_statuses: dict[str, str] = {}
    base_expectations = {
        "deterministic_font": "selected",
        "independent_ocr": "selected",
        "dependent_bad_layer": "unresolved",
        "low_margin": "unresolved",
        "partial_overlap": "unresolved",
        "mixed_script": "unresolved",
        "healthy_native": "unchanged",
    }
    for index, (name, raw_group) in enumerate(
        reconciliation_cases().items(),
        start=1,
    ):
        prepared = deepcopy(raw_group)
        group_id = f"synthetic-{index:02d}-{name}"
        span_id = f"synthetic-span-{index:02d}"
        prepared["group_id"] = group_id
        prepared["span_id"] = span_id
        prepared["owner_element_id"] = f"synthetic-owner-{index:02d}"
        for row in prepared["candidates"]:
            row["span_id"] = span_id
            provenance = row.get("provenance")
            if not isinstance(provenance, dict):
                continue
            if "audit_finding_id" in provenance:
                provenance["audit_finding_id"] = (
                    f"audit-finding:{span_id}"
                )
            if row.get("source_kind") == "selective_ocr":
                provenance["selective_span_id"] = span_id
                provenance["selective_outcome_id"] = (
                    f"selective-outcome:{span_id}"
                )
        groups.append(prepared)
        expected_statuses[group_id] = base_expectations[name]

    overlap_rows = [
        candidate(
            "synthetic-native-exact-overlap",
            "Settlement amount",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="synthetic-pdf-text-layer:settlement",
            evidence_ids=("synthetic-ev-native-exact-overlap",),
            mapping_safety="healthy",
            span_id="synthetic-span-08",
        ),
        candidate(
            "synthetic-ocr-exact-overlap",
            "Settlement amount",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="synthetic-raster:settlement",
            evidence_ids=("synthetic-ev-ocr-exact-overlap",),
            confidence=0.99,
            span_id="synthetic-span-08",
        ),
    ]
    overlap_group = group(
        overlap_rows,
        group_id="synthetic-08-exact-overlap",
        span_id="synthetic-span-08",
        owner_element_id="synthetic-owner-08",
        owner_text="Settlement amount",
    )
    groups.append(overlap_group)
    expected_statuses[overlap_group["group_id"]] = "unchanged"

    repeated_text = "Repeated grounded label"
    repeated_boxes = (
        {
            "x": 72.0,
            "y": 240.0,
            "width": 140.0,
            "height": 12.0,
            "unit": "pt",
        },
        {
            "x": 320.0,
            "y": 240.0,
            "width": 140.0,
            "height": 12.0,
            "unit": "pt",
        },
    )
    for offset, bbox in enumerate(repeated_boxes, start=9):
        span_id = f"synthetic-span-{offset:02d}"
        repeated = candidate(
            f"synthetic-native-repeated-{offset}",
            repeated_text,
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id=f"synthetic-pdf-text-layer:repeated:{offset}",
            evidence_ids=(f"synthetic-ev-native-repeated-{offset}",),
            mapping_safety="healthy",
            span_id=span_id,
            bbox=bbox,
        )
        repeated_group = group(
            [repeated],
            group_id=f"synthetic-{offset:02d}-distinct-geometry",
            span_id=span_id,
            owner_element_id=f"synthetic-owner-{offset:02d}",
            owner_text=repeated_text,
            target_bbox=bbox,
            owner_bbox=bbox,
        )
        groups.append(repeated_group)
        expected_statuses[repeated_group["group_id"]] = "unchanged"

    if len(groups) != 10 or len(expected_statuses) != 10:
        raise RuntimeError("synthetic reconciliation control count drifted")
    return groups, expected_statuses


def _reconciliation_operation(
    groups: Sequence[Mapping[str, Any]],
    *,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    from app.services.text_reconciliation import reconcile_text_candidates
    from tests.fixtures.phase_02.text_reconciliation import SOURCE_SHA256

    bound_source_sha256 = source_sha256 or SOURCE_SHA256
    report = reconcile_text_candidates(
        list(groups),
        source_sha256=bound_source_sha256,
        clock=_constant_clock,
    )
    payload = report.model_dump(mode="json", exclude_none=False)
    _canonical_json(payload)
    return payload


def _synthetic_measurement(
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    """Measure deterministic policy branches using explicitly synthetic data."""

    groups, expected_statuses = _synthetic_groups()
    input_groups = {str(group["group_id"]): group for group in groups}
    rss_before = _peak_rss_bytes()
    report, durations_ms = _measure_deterministic(
        lambda: _reconciliation_operation(groups),
        warmups=warmups,
        samples=samples,
    )
    rss_after = _peak_rss_bytes()

    reordered = deepcopy(groups)
    reordered.reverse()
    for candidate_group in reordered:
        candidate_group["candidates"].reverse()
    reordered_report = _reconciliation_operation(reordered)
    if _canonical_json(report) != _canonical_json(reordered_report):
        raise RuntimeError(
            "group or candidate order changed synthetic decisions"
        )
    outcomes = [
        outcome
        for outcome in report.get("outcomes", [])
        if isinstance(outcome, Mapping)
    ]
    observed_statuses = {
        str(outcome["group_id"]): str(outcome["status"])
        for outcome in outcomes
    }
    if observed_statuses != expected_statuses:
        raise RuntimeError(
            "synthetic terminal decisions differ from the accepted policy"
        )
    expected_counts = {
        "selected": 2,
        "unchanged": 4,
        "unresolved": 4,
    }
    observed_counts = {
        status: sum(value == status for value in observed_statuses.values())
        for status in expected_counts
    }
    if observed_counts != expected_counts:
        raise RuntimeError("synthetic terminal counts drifted")
    expected_branches = {
        "synthetic-01-deterministic_font": (
            "deterministic_font_evidence",
            ["font-catastrophe"],
        ),
        "synthetic-02-independent_ocr": (
            "independent_high_confidence_ocr",
            ["ocr-independent"],
        ),
        "synthetic-03-dependent_bad_layer": (
            "dependent_source_agreement",
            [],
        ),
        "synthetic-04-low_margin": ("low_margin_conflict", []),
        "synthetic-05-partial_overlap": (
            "partial_overlap_conflict",
            [],
        ),
        "synthetic-06-mixed_script": ("mixed_script_conflict", []),
        "synthetic-07-healthy_native": (
            "healthy_native_authoritative",
            ["native-healthy"],
        ),
        "synthetic-08-exact-overlap": (
            "healthy_native_authoritative",
            ["synthetic-native-exact-overlap"],
        ),
        "synthetic-09-distinct-geometry": (
            "healthy_native_authoritative",
            ["synthetic-native-repeated-9"],
        ),
        "synthetic-10-distinct-geometry": (
            "healthy_native_authoritative",
            ["synthetic-native-repeated-10"],
        ),
    }
    observed_branches = {
        str(outcome["group_id"]): (
            str(outcome["reason_code"]),
            list(outcome["selected_candidate_ids"]),
        )
        for outcome in outcomes
    }
    unresolved_group_ids = {
        group_id
        for group_id, status in expected_statuses.items()
        if status == "unresolved"
    }
    concern_group_ids = {
        str(concern["group_id"])
        for concern in report.get("concerns", [])
        if isinstance(concern, Mapping) and concern.get("group_id")
    }
    if (
        observed_branches != expected_branches
        or concern_group_ids != unresolved_group_ids
    ):
        raise RuntimeError(
            "synthetic winner, reason, or concern branch drifted"
        )
    dependent = next(
        outcome
        for outcome in outcomes
        if outcome["group_id"] == "synthetic-03-dependent_bad_layer"
    )
    if {
        int(decision["independent_support_count"])
        for decision in dependent["decisions"]
        if decision["lineage_family"] == "pdf_text_layer"
    } != {1}:
        raise RuntimeError("dependent text-layer engines gained extra votes")
    coverage = _report_coverage(report, input_groups)
    if (
        coverage["reason_coverage"] != 1.0
        or coverage["evidence_coverage"] != 1.0
        or coverage["schema_coverage"] != 1.0
        or coverage["alternative_retention"] != 1.0
        or coverage["canonical_duplicate_count"] != 0
        or coverage["semantic_completion_count"] != 0
    ):
        raise RuntimeError("synthetic evidence or no-completion gate failed")

    repeated_outcomes = [
        outcome
        for outcome in outcomes
        if str(outcome["group_id"]).endswith("distinct-geometry")
    ]
    if (
        len(repeated_outcomes) != 2
        or len(
            {
                outcome["owner_element_id"]
                for outcome in repeated_outcomes
            }
        )
        != 2
        or {outcome["selected_text"] for outcome in repeated_outcomes}
        != {"Repeated grounded label"}
    ):
        raise RuntimeError("distinct-geometry equal text was suppressed")

    return {
        "evidence_class": "deterministic_synthetic_test_only",
        "actual_production_input": False,
        "scenario_count": 9,
        "group_count": len(groups),
        "candidate_count": sum(
            len(group["candidates"]) for group in groups
        ),
        "expected_terminal_counts": expected_counts,
        "observed_terminal_counts": observed_counts,
        "warmup_count": warmups,
        "sample_count": samples,
        "latency_ms": _distribution(durations_ms),
        "latency_samples_ms": durations_ms,
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "input_sha256": _sha256_json(groups),
        "report_sha256": _sha256_json(report),
        "order_permutation_report_sha256": _sha256_json(reordered_report),
        "structurally_deterministic": True,
        "coverage": coverage,
        "outcomes": outcomes,
        "concerns": report["concerns"],
    }


def _boxes_match(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    tolerance: float = 1e-9,
) -> bool:
    return all(
        math.isclose(
            float(first.get(field, first.get(short))),
            float(second.get(field, second.get(short))),
            rel_tol=0.0,
            abs_tol=tolerance,
        )
        for field, short in (
            ("x", "x"),
            ("y", "y"),
            ("width", "w"),
            ("height", "h"),
        )
    )


def _actual_renderer_test_only_groups(
    workspace: Path,
    retained: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Join actual OCR evidence to its explicitly test-only refusal context."""

    from app.services.text_reconciliation import _ir_audit_identity
    from tests.fixtures.phase_02.text_reconciliation import candidate, group

    prepared = _prepare_actual_p02_us03_case(
        workspace,
        CATASTROPHE_CASE_ID,
    )
    source_sha256 = str(prepared["binding"]["source_sha256"])
    us03_target = retained["p02_us03"]["target"]
    if (
        us03_target["source_sha256"] != source_sha256
        or us03_target["audit_report_sha256"]
        != prepared["audit_report_sha256"]
        or us03_target["production_recovery_report_sha256"]
        != prepared["recovery_report_sha256"]
        or us03_target["recovery_variant"]["variant_kind"]
        != "deterministic_test_only_recovery_refusal"
    ):
        raise RuntimeError(
            "retained actual-render evidence no longer binds actual inputs"
        )
    real_report = us03_target["real_production_path"]["report"]
    recovery_runs = [
        run
        for run in prepared["recovery"].get("runs", [])
        if isinstance(run, Mapping)
    ]
    ir = prepared["p02_us03_ir"]
    ir_evidence = [
        evidence.model_dump(mode="json", exclude_none=True)
        for evidence in ir.evidence
    ]
    groups: list[dict[str, Any]] = []
    input_trace: list[dict[str, Any]] = []
    for outcome in real_report.get("outcomes", []):
        if not isinstance(outcome, Mapping):
            continue
        candidates = [
            row
            for row in outcome.get("candidates", [])
            if isinstance(row, Mapping)
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "actual-render test-only outcome must retain one candidate"
            )
        matching_runs = [
            run
            for run in recovery_runs
            if run.get("font_ref") == outcome.get("font_ref")
            and run.get("font_object_id")
            == outcome.get("font_object_id")
            and int(run.get("page_index") or 0)
            == int(outcome.get("page_index") or 0)
            and all(
                math.isclose(
                    float(run["bbox"][field]),
                    float(outcome["source_bbox"][field]),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                for field in ("x", "y", "height")
            )
            and math.isclose(
                _reciprocal_overlap(
                    outcome["source_bbox"],
                    run["bbox"],
                )["first_area_ratio"],
                1.0,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and float(outcome["source_bbox"]["width"])
            <= float(run["bbox"]["width"])
        ]
        if len(matching_runs) != 1:
            raise RuntimeError(
                "actual-render target does not join uniquely to recovery run"
            )
        run = matching_runs[0]
        run_index = int(run["run_index"])
        audit_identity = _ir_audit_identity(
            ir,
            page_index=int(outcome["page_index"]),
            font_ref=str(outcome["font_ref"]),
            font_object_id=int(outcome["font_object_id"]),
            bbox=outcome["source_bbox"],
        )
        if (
            not isinstance(audit_identity, Mapping)
            or audit_identity.get("source_sha256") != source_sha256
        ):
            raise RuntimeError(
                "actual-render outcome has no retained audit identity"
            )
        native_evidence = [
            row
            for row in ir_evidence
            if row.get("method") == "native"
            and row.get("metadata", {}).get("source_sha256")
            == source_sha256
            and row.get("metadata", {}).get("font_ref") == run["font_ref"]
            and row.get("metadata", {}).get("font_object_id")
            == run["font_object_id"]
            and row.get("metadata", {}).get("run_index") == run_index
            and row.get("metadata", {}).get("page_index")
            == run["page_index"]
            and row.get("metadata", {}).get("alternative_role") == "original"
        ]
        native_evidence.sort(
            key=lambda row: int(row["metadata"]["glyph_index"])
        )
        run_glyphs = [
            glyph
            for glyph in run.get("glyphs", [])
            if isinstance(glyph, Mapping)
        ]
        if (
            len(native_evidence) != len(run_glyphs)
            or "".join(str(row.get("value") or "") for row in native_evidence)
            != run.get("original_text")
            or any(
                row.get("value") != glyph.get("original_text")
                or row.get("metadata", {}).get("glyph_index")
                != glyph.get("glyph_index")
                or row.get("metadata", {}).get("cid") != glyph.get("cid")
                or row.get("metadata", {}).get("glyph_id")
                != glyph.get("glyph_id")
                for row, glyph in zip(
                    native_evidence,
                    run_glyphs,
                    strict=True,
                )
            )
        ):
            raise RuntimeError(
                "actual native glyph evidence does not match recovery run"
            )
        owner_ids = {str(row["element_id"]) for row in native_evidence}
        if len(owner_ids) != 1:
            raise RuntimeError("actual native evidence has multiple owners")
        raw_ocr = candidates[0]
        tokens = [
            token
            for token in raw_ocr.get("tokens", [])
            if isinstance(token, Mapping)
        ]
        cost = outcome.get("cost")
        attempt = outcome.get("attempt")
        if not isinstance(cost, Mapping) or not isinstance(attempt, Mapping):
            raise RuntimeError("actual-render candidate has incomplete cost")
        pass_completed = bool(cost.get("passes_completed"))
        evidence_ids = (
            str(raw_ocr["evidence_id"]),
            *(str(token["evidence_id"]) for token in tokens),
        )
        span_id = str(outcome["span_id"])
        native = candidate(
            f"actual-native-{run['evidence_id']}",
            str(run["original_text"]),
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id=f"pdf-text-layer:{run['font_ref']}",
            evidence_ids=tuple(str(row["id"]) for row in native_evidence),
            mapping_safety="unsafe",
            span_id=span_id,
            page_index=int(outcome["page_index"]),
            bbox=dict(run["bbox"]),
            source_sha256=source_sha256,
        )
        ocr = candidate(
            f"actual-ocr-{raw_ocr['evidence_id']}",
            str(raw_ocr["text"]),
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method=str(raw_ocr["method"]),
            origin_asset_id=f"rendered-crop:{span_id}",
            evidence_ids=evidence_ids,
            confidence=float(raw_ocr["confidence"]),
            span_id=span_id,
            page_index=int(outcome["page_index"]),
            bbox=dict(raw_ocr["bbox"]),
            source_sha256=source_sha256,
            selective_span_id=span_id,
            selective_outcome_id=span_id,
            recovery_refusal_reason_code=str(
                outcome["refusal_reason_code"]
            ),
            audit_finding_id=str(audit_identity["audit_finding_id"]),
            audit_run_index=int(audit_identity["audit_run_index"]),
            font_ref=str(outcome["font_ref"]),
            font_object_id=int(outcome["font_object_id"]),
            transform_valid=bool(
                attempt.get("transform_valid")
                and cost.get("transform_valid")
            ),
            pass_completed=pass_completed,
            candidate_complete=(
                bool(raw_ocr.get("evidence_id"))
                and len(tokens) == int(raw_ocr["word_count"])
            ),
            word_count=int(raw_ocr["word_count"]),
            retained_token_count=len(tokens),
            languages=tuple(str(value) for value in cost["languages"]),
        )
        candidate_group = group(
            [native, ocr],
            group_id=f"actual-render-test-only-{span_id}",
            span_id=span_id,
            page_index=int(outcome["page_index"]),
            owner_element_id=next(iter(owner_ids)),
            owner_text=str(run["original_text"]),
            owner_markdown=str(run["original_text"]),
            target_bbox=dict(outcome["source_bbox"]),
            owner_bbox=dict(run["bbox"]),
            replacement_original_text=str(run["original_text"]),
            expected_scripts=("Latn",),
        )
        groups.append(candidate_group)
        overlap = _reciprocal_overlap(
            outcome["source_bbox"],
            raw_ocr["bbox"],
        )
        recovery_overlap = _reciprocal_overlap(
            outcome["source_bbox"],
            run["bbox"],
        )
        input_trace.append(
            {
                "group_id": candidate_group["group_id"],
                "span_id": span_id,
                "recovery_run_evidence_id": run["evidence_id"],
                "audit_finding_id": audit_identity["audit_finding_id"],
                "audit_run_index": audit_identity["audit_run_index"],
                "font_ref": outcome["font_ref"],
                "font_object_id": outcome["font_object_id"],
                "native_evidence_ids": native["evidence_ids"],
                "ocr_candidate_evidence_id": raw_ocr["evidence_id"],
                "ocr_token_evidence_ids": [
                    token["evidence_id"] for token in tokens
                ],
                "ocr_text": raw_ocr["text"],
                "ocr_confidence": raw_ocr["confidence"],
                "source_bbox": deepcopy(outcome["source_bbox"]),
                "recovery_run_bbox": deepcopy(run["bbox"]),
                "source_bbox_recovery_coverage": recovery_overlap[
                    "first_area_ratio"
                ],
                "recovery_bbox_source_coverage": recovery_overlap[
                    "second_area_ratio"
                ],
                "source_bbox_area_overlap": overlap["first_area_ratio"],
                "candidate_bbox_area_overlap": overlap["second_area_ratio"],
            }
        )
    if len(groups) != EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES:
        raise RuntimeError("actual-render test-only group count drifted")
    binding = {
        "evidence_class": (
            "actual_pdfium_tesseract_with_test_only_upstream_refusal"
        ),
        "actual_pdfium_render": True,
        "actual_local_tesseract": True,
        "actual_production_upstream_input": False,
        "upstream_variant_kind": us03_target["recovery_variant"][
            "variant_kind"
        ],
        "source_sha256": source_sha256,
        "audit_report_sha256": prepared["audit_report_sha256"],
        "production_recovery_report_sha256": prepared[
            "recovery_report_sha256"
        ],
        "benchmark_recovery_variant_sha256": us03_target[
            "benchmark_recovery_variant_sha256"
        ],
        "retained_p02_us03_metrics_sha256": retained["identities"][
            "p02_us03"
        ]["sha256"],
        "input_trace": input_trace,
    }
    return groups, binding


def _actual_renderer_test_only_measurement(
    workspace: Path,
    retained: Mapping[str, Any],
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    """Measure reconciliation without relabeling the upstream refusal variant."""

    groups, binding = _actual_renderer_test_only_groups(workspace, retained)
    input_groups = {str(group["group_id"]): group for group in groups}
    rss_before = _peak_rss_bytes()
    report, durations_ms = _measure_deterministic(
        lambda: _reconciliation_operation(
            groups,
            source_sha256=str(binding["source_sha256"]),
        ),
        warmups=warmups,
        samples=samples,
    )
    rss_after = _peak_rss_bytes()
    outcomes = [
        outcome
        for outcome in report.get("outcomes", [])
        if isinstance(outcome, Mapping)
    ]
    if (
        len(outcomes) != EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES
        or report.get("selected_count") != 0
        or report.get("unchanged_count") != 0
        or report.get("unresolved_count")
        != EXPECTED_ACTUAL_RENDER_TEST_ONLY_OUTCOMES
        or any(outcome.get("status") != "unresolved" for outcome in outcomes)
    ):
        raise RuntimeError(
            "actual-render test-only candidates did not fail closed"
        )
    input_trace_by_group = {
        str(row["group_id"]): row for row in binding["input_trace"]
    }
    reciprocal_overlap_gate_count = 0
    for outcome in outcomes:
        trace = input_trace_by_group.get(str(outcome.get("group_id")))
        ocr_decisions = [
            decision
            for decision in outcome.get("decisions", [])
            if isinstance(decision, Mapping)
            and decision.get("source_kind") == "selective_ocr"
        ]
        if len(ocr_decisions) != 1 or not isinstance(trace, Mapping):
            raise RuntimeError(
                "actual-render OCR decision identity is incomplete"
            )
        decision = ocr_decisions[0]
        candidate_target = float(
            decision["candidate_target_overlap"]
        )
        target_candidate = float(
            decision["target_candidate_overlap"]
        )
        if not (
            decision.get("eligible") is False
            and "reciprocal_overlap_below_minimum"
            in decision.get("reason_codes", [])
            and math.isclose(
                candidate_target,
                float(trace["candidate_bbox_area_overlap"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and math.isclose(
                target_candidate,
                float(trace["source_bbox_area_overlap"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and min(candidate_target, target_candidate) < 0.80
        ):
            raise RuntimeError(
                "actual-render OCR geometry refusal evidence drifted"
            )
        reciprocal_overlap_gate_count += 1
    coverage = _report_coverage(report, input_groups)
    if (
        coverage["reason_coverage"] != 1.0
        or coverage["evidence_coverage"] != 1.0
        or coverage["schema_coverage"] != 1.0
        or coverage["alternative_retention"] != 1.0
        or coverage["canonical_duplicate_count"] != 0
        or coverage["semantic_completion_count"] != 0
    ):
        raise RuntimeError(
            "actual-render test-only evidence retention gate failed"
        )
    concern_group_ids = {
        str(concern["group_id"])
        for concern in report.get("concerns", [])
        if isinstance(concern, Mapping) and concern.get("group_id")
    }
    if concern_group_ids != set(input_groups):
        raise RuntimeError(
            "actual-render test-only unresolved concerns are incomplete"
        )
    return {
        **binding,
        "group_count": len(groups),
        "candidate_count": sum(
            len(group["candidates"]) for group in groups
        ),
        "warmup_count": warmups,
        "sample_count": samples,
        "latency_ms": _distribution(durations_ms),
        "latency_samples_ms": durations_ms,
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "input_sha256": _sha256_json(groups),
        "report_sha256": _sha256_json(report),
        "reciprocal_overlap_gate_count": (
            reciprocal_overlap_gate_count
        ),
        "structurally_deterministic": True,
        "coverage": coverage,
        "outcomes": outcomes,
        "concerns": report["concerns"],
    }


def _projection_reconciliation_traces(
    projection: Mapping[str, Any],
    reconciled_ir: Any | None = None,
) -> list[dict[str, Any]]:
    """Collect one terminal trace per group from legacy and IR diagnostics.

    Owner-linked alternatives are observable on projected legacy owners.
    Ownerless recovery alternatives have no projected primary owner, so their
    retained IR element diagnostic is the only honest terminal-trace source.
    """

    candidates: list[dict[str, Any]] = []
    for page in projection.get("pages", []):
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items", []):
            if not isinstance(item, Mapping):
                continue
            for trace in item.get("text_reconciliation", []):
                if isinstance(trace, Mapping):
                    candidates.append(
                        {
                            "item_id": item.get("id"),
                            "trace_location": "legacy_projection",
                            **deepcopy(dict(trace)),
                        }
                    )
    if reconciled_ir is not None:
        for element in reconciled_ir.elements:
            property_values = (
                (
                    "ir_element",
                    element.properties.get("text_reconciliation"),
                ),
                (
                    "ir_element_legacy",
                    (
                        element.properties.get("legacy_item", {}).get(
                            "text_reconciliation"
                        )
                        if isinstance(
                            element.properties.get("legacy_item"),
                            Mapping,
                        )
                        else None
                    ),
                ),
            )
            for location, value in property_values:
                rows = value if isinstance(value, list) else [value]
                for trace in rows:
                    if (
                        isinstance(trace, Mapping)
                        and trace.get("group_id")
                        and trace.get("span_id")
                        and trace.get("status")
                        and trace.get("reason_code")
                    ):
                        candidates.append(
                            {
                                "element_id": element.id,
                                "trace_location": location,
                                **deepcopy(dict(trace)),
                            }
                        )

    by_group: dict[str, dict[str, Any]] = {}
    sources_by_group: dict[str, list[dict[str, str]]] = {}
    source_priority = {
        "legacy_projection": 0,
        "ir_element_legacy": 1,
        "ir_element": 2,
    }

    def comparable(trace: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in trace.items()
            if key
            not in {
                "item_id",
                "element_id",
                "trace_location",
                "trace_locations",
                "trace_sources",
                # IR element state adds this convenience marker to the
                # otherwise exact report outcome.
                "selected",
            }
        }

    for trace in candidates:
        group_id = str(trace.get("group_id") or "")
        if not group_id:
            continue
        source = {
            key: str(trace[key])
            for key in ("trace_location", "item_id", "element_id")
            if trace.get(key) is not None
        }
        if source not in sources_by_group.setdefault(group_id, []):
            sources_by_group[group_id].append(source)
        prior = by_group.get(group_id)
        if prior is not None:
            if _canonical_json(comparable(prior)) != _canonical_json(
                comparable(trace)
            ):
                raise RuntimeError(
                    "reconciliation trace sources disagree for "
                    f"{group_id}"
                )
            if source_priority.get(
                str(trace.get("trace_location")),
                99,
            ) >= source_priority.get(
                str(prior.get("trace_location")),
                99,
            ):
                continue
        by_group[group_id] = trace

    traces = []
    for group_id, trace in by_group.items():
        sources = sorted(
            sources_by_group[group_id],
            key=lambda row: (
                source_priority.get(row.get("trace_location", ""), 99),
                row.get("item_id", ""),
                row.get("element_id", ""),
            ),
        )
        traces.append(
            {
                **trace,
                "trace_locations": sorted(
                    {source["trace_location"] for source in sources},
                    key=lambda value: source_priority.get(value, 99),
                ),
                "trace_sources": sources,
            }
        )
    traces.sort(
        key=lambda row: (
            int(row.get("page_index") or 0),
            str(row.get("owner_element_id") or ""),
            str(row.get("span_id") or ""),
            str(row.get("group_id") or ""),
            str(row.get("item_id") or ""),
        )
    )
    return traces


def _projection_alternative_state(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    font_rows: list[dict[str, Any]] = []
    ocr_rows: list[dict[str, Any]] = []
    for page in projection.get("pages", []):
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items", []):
            if not isinstance(item, Mapping):
                continue
            for row in item.get("font_recovery_alternatives", []):
                if isinstance(row, Mapping):
                    font_rows.append(
                        {"item_id": item.get("id"), **deepcopy(dict(row))}
                    )
            for row in item.get("selective_ocr_candidates", []):
                if isinstance(row, Mapping):
                    ocr_rows.append(
                        {"item_id": item.get("id"), **deepcopy(dict(row))}
                    )
    return {
        "font_recovery_alternative_count": len(font_rows),
        "font_recovery_selected_count": sum(
            bool(row.get("selected")) for row in font_rows
        ),
        "selective_ocr_candidate_count": len(ocr_rows),
        "selective_ocr_selected_count": sum(
            bool(row.get("selected")) for row in ocr_rows
        ),
        "font_recovery_rows": font_rows,
        "selective_ocr_rows": ocr_rows,
    }


def _source_text_values(ir: Any) -> set[str]:
    values: set[str] = set()
    for element in ir.elements:
        for value in (element.value, element.markdown):
            if isinstance(value, str):
                values.add(value)
        legacy = element.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        for key in ("value", "text", "md", "font_recovery_original_value"):
            value = legacy.get(key)
            if isinstance(value, str):
                values.add(value)
        for list_key, text_key in (
            ("font_recovery_alternatives", "recovered_text"),
            ("selective_ocr_candidates", "text"),
        ):
            for row in legacy.get(list_key, []):
                if isinstance(row, Mapping) and isinstance(
                    row.get(text_key),
                    str,
                ):
                    values.add(str(row[text_key]))
    for evidence in ir.evidence:
        if isinstance(evidence.value, str):
            values.add(evidence.value)
    return values


def _nested_retained_evidence_ids(value: Any) -> set[str]:
    retained: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                isinstance(item, str)
                and key.endswith("evidence_id")
            ):
                retained.add(item)
            elif (
                key.endswith("evidence_ids")
                and isinstance(item, Sequence)
                and not isinstance(item, (str, bytes, bytearray))
            ):
                retained.update(
                    str(candidate)
                    for candidate in item
                    if isinstance(candidate, str)
                )
            retained.update(_nested_retained_evidence_ids(item))
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            retained.update(_nested_retained_evidence_ids(item))
    return retained


def _retained_input_evidence_ids(ir: Any) -> set[str]:
    """Return only evidence identities present before reconciliation."""

    retained = {str(evidence.id) for evidence in ir.evidence}
    for element in ir.elements:
        retained.update(str(value) for value in element.evidence_ids)
        retained.update(_nested_retained_evidence_ids(element.properties))
    for relationship in ir.relationships:
        retained.update(str(value) for value in relationship.evidence_ids)
        retained.update(_nested_retained_evidence_ids(relationship.metadata))
    for concern in ir.concerns:
        retained.update(_nested_retained_evidence_ids(concern.metadata))
    return retained


def _normalized_evidence_core(ir: Any) -> dict[str, str]:
    """Hash immutable evidence fields, excluding only US04 selection marks."""

    result: dict[str, str] = {}
    for evidence in ir.evidence:
        payload = evidence.model_dump(mode="json", exclude_none=True)
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("selected", None)
            metadata.pop("text_reconciliation", None)
        result[str(evidence.id)] = _sha256_json(payload)
    return result


def _element_content_and_role_core(ir: Any) -> dict[str, str]:
    """Hash primary-bearing element content that US04 must not invent."""

    return {
        str(element.id): _sha256_json(
            {
                "page_id": str(element.page_id),
                "type": str(element.type),
                "value": element.value,
                "markdown": element.markdown,
                "presentation_role": str(element.presentation_role),
            }
        )
        for element in ir.elements
    }


def _font_decision_evidence_bindings(
    ir: Any,
    recovery: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Bind each recovery run to its exact retained native/recovered records."""

    elements = {str(element.id): element for element in ir.elements}
    evidence = {str(row.id): row for row in ir.evidence}
    boxes = {str(box.id): box for box in ir.bboxes}
    registry: dict[str, dict[str, Any]] = {}
    for owner in ir.elements:
        legacy = owner.properties.get("legacy_item")
        if not isinstance(legacy, Mapping):
            continue
        for summary in legacy.get("font_recovery_alternatives", []):
            if not isinstance(summary, Mapping):
                continue
            run_id = str(summary.get("run_evidence_id") or "")
            if not run_id:
                continue
            entry = registry.setdefault(run_id, {})
            if "summary" in entry:
                raise RuntimeError(
                    f"{run_id} repeats a legacy recovery summary"
                )
            entry["summary"] = dict(summary)
            entry["owner_element_id"] = str(owner.id)
    for alternate in ir.elements:
        font = alternate.properties.get("font_recovery")
        if not isinstance(font, Mapping):
            continue
        run_id = str(font.get("run_evidence_id") or "")
        if not run_id:
            continue
        entry = registry.setdefault(run_id, {})
        if "alternate_element_id" in entry:
            raise RuntimeError(
                f"{run_id} repeats a recovery alternative element"
            )
        entry["font_properties"] = dict(font)
        entry["alternate_element_id"] = str(alternate.id)

    runs = [
        dict(run)
        for run in recovery.get("runs", [])
        if isinstance(run, Mapping)
    ]
    run_ids = [str(run.get("evidence_id") or "") for run in runs]
    if (
        not run_ids
        or any(not run_id for run_id in run_ids)
        or len(run_ids) != len(set(run_ids))
        or set(registry) != set(run_ids)
    ):
        raise RuntimeError(
            "recovery reports and retained IR registries do not bind exactly"
        )

    bindings: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda value: str(value["evidence_id"])):
        run_id = str(run["evidence_id"])
        entry = registry[run_id]
        owner_id = entry.get("owner_element_id")
        alternate_id = entry.get("alternate_element_id")
        anchor_id = str(alternate_id or owner_id or "")
        anchor = elements.get(anchor_id)
        summary = entry.get("summary")
        if anchor is None:
            raise RuntimeError(f"{run_id} has no retained IR anchor")
        if isinstance(summary, Mapping):
            raw_recovered_ids = summary.get("glyph_evidence_ids")
        else:
            raw_recovered_ids = [
                evidence_id
                for evidence_id in anchor.evidence_ids
                if (
                    str(evidence_id) in evidence
                    and str(evidence[str(evidence_id)].method.value)
                    == "recovered"
                )
            ]
        if (
            not isinstance(raw_recovered_ids, Sequence)
            or isinstance(raw_recovered_ids, (str, bytes, bytearray))
        ):
            raise RuntimeError(f"{run_id} has no bounded evidence registry")
        recovered_ids = [str(value) for value in raw_recovered_ids]
        if (
            not recovered_ids
            or len(recovered_ids) != len(set(recovered_ids))
        ):
            raise RuntimeError(
                f"{run_id} recovered evidence identities are invalid"
            )
        recovered_rows = [evidence.get(value) for value in recovered_ids]
        if any(row is None for row in recovered_rows):
            raise RuntimeError(f"{run_id} has dangling recovered evidence")

        native_rows: list[Any] = []
        native_ids: list[str] = []
        glyphs = [
            glyph
            for glyph in run.get("glyphs", [])
            if isinstance(glyph, Mapping)
        ]
        if len(glyphs) != len(recovered_rows):
            raise RuntimeError(
                f"{run_id} glyph and recovered evidence counts differ"
            )
        for glyph, recovered_row in zip(glyphs, recovered_rows, strict=True):
            metadata = recovered_row.metadata
            native_id = metadata.get("original_evidence_id")
            native_row = (
                evidence.get(str(native_id))
                if isinstance(native_id, str) and native_id
                else None
            )
            bbox = boxes.get(str(recovered_row.bbox_id or ""))
            bbox_payload = (
                bbox.model_dump(mode="json", exclude_none=True)
                if bbox is not None
                else None
            )
            if (
                str(recovered_row.method.value) != "recovered"
                or str(recovered_row.element_id) != anchor_id
                or recovered_row.value != glyph.get("recovered_text")
                or metadata.get("source_sha256") != ir.source_sha256
                or metadata.get("font_ref") != run.get("font_ref")
                or metadata.get("font_object_id")
                != run.get("font_object_id")
                or metadata.get("run_index") != run.get("run_index")
                or metadata.get("glyph_index") != glyph.get("glyph_index")
                or not isinstance(bbox_payload, Mapping)
                or not _boxes_match(bbox_payload, glyph["bbox"])
                or native_row is None
                or str(native_row.method.value) != "native"
                or str(native_row.element_id) != anchor_id
                or native_row.bbox_id != recovered_row.bbox_id
                or native_row.value != glyph.get("original_text")
                or native_row.metadata.get("source_sha256")
                != ir.source_sha256
                or native_row.metadata.get("font_ref")
                != run.get("font_ref")
                or native_row.metadata.get("font_object_id")
                != run.get("font_object_id")
                or native_row.metadata.get("run_index")
                != run.get("run_index")
                or native_row.metadata.get("glyph_index")
                != glyph.get("glyph_index")
            ):
                raise RuntimeError(
                    f"{run_id} retained glyph evidence lineage drifted"
                )
            native_rows.append(native_row)
            native_ids.append(str(native_row.id))
        if (
            "".join(str(row.value or "") for row in recovered_rows)
            != run.get("recovered_text")
            or "".join(str(row.value or "") for row in native_rows)
            != run.get("original_text")
        ):
            raise RuntimeError(
                f"{run_id} retained evidence values differ from recovery"
            )
        bindings.append(
            {
                "run_evidence_id": run_id,
                "owner_element_id": owner_id,
                "alternate_element_id": alternate_id,
                "anchor_element_id": anchor_id,
                "font_candidate_id": f"font:{run_id}",
                "font_evidence_ids": recovered_ids,
                "native_candidate_id": f"native:{run_id}",
                "native_evidence_ids": native_ids,
            }
        )
    return bindings


def _font_run_id_from_trace(trace: Mapping[str, Any]) -> str | None:
    prefix = "font-group:"
    group_id = str(trace.get("group_id") or "")
    if not group_id.startswith(prefix):
        return None
    run_id = group_id[len(prefix) :]
    return run_id or None


def _selection_surface_disagreements(
    reconciled_ir: Any,
    traces: Sequence[Mapping[str, Any]],
    *,
    canonical_element_block_counts: Mapping[str, int],
    font_bindings: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Require decision identities to agree across every retained surface."""

    evidence = {str(row.id): row for row in reconciled_ir.evidence}
    relationships_by_source: dict[str, list[Any]] = {}
    for relationship in reconciled_ir.relationships:
        relationships_by_source.setdefault(
            str(relationship.source_id),
            [],
        ).append(relationship)
    canonical_counts = Counter(
        {
            str(element_id): int(count)
            for element_id, count in canonical_element_block_counts.items()
        }
    )

    def property_trace(element: Any, group_id: str) -> Mapping[str, Any] | None:
        value = element.properties.get("text_reconciliation")
        rows = value if isinstance(value, list) else [value]
        matches = [
            row
            for row in rows
            if isinstance(row, Mapping)
            and row.get("group_id") == group_id
        ]
        return matches[0] if len(matches) == 1 else None

    disagreements: list[str] = []
    for trace in traces:
        group_id = str(trace.get("group_id") or "")
        terminal = trace.get("status") in {"selected", "unchanged"}
        selected_ids = {
            str(value) for value in trace.get("selected_candidate_ids", [])
        }
        decisions = [
            decision
            for decision in trace.get("decisions", [])
            if isinstance(decision, Mapping)
        ]
        selected_decisions = [
            decision
            for decision in decisions
            if decision.get("selected") is True
        ]
        if terminal and (
            len(selected_ids) != 1
            or len(selected_decisions) != 1
            or str(selected_decisions[0].get("candidate_id"))
            not in selected_ids
        ):
            disagreements.append(f"{group_id}:decision_selection")
            continue
        if not terminal and (selected_ids or selected_decisions):
            disagreements.append(f"{group_id}:unresolved_selection")
            continue
        for decision in decisions:
            expected_selected = decision.get("selected") is True
            for evidence_id in decision.get("evidence_ids", []):
                record = evidence.get(str(evidence_id))
                state = (
                    record.metadata.get("text_reconciliation")
                    if record is not None
                    else None
                )
                if not (
                    record is not None
                    and record.metadata.get("selected")
                    is expected_selected
                    and isinstance(state, Mapping)
                    and state.get("group_id") == group_id
                    and state.get("selected") is expected_selected
                    and state.get("status") == trace.get("status")
                    and state.get("reason_code")
                    == trace.get("reason_code")
                ):
                    disagreements.append(
                        f"{group_id}:evidence:{evidence_id}"
                    )

        run_id = _font_run_id_from_trace(trace)
        if run_id is not None:
            binding = font_bindings.get(run_id)
            if not isinstance(binding, Mapping):
                disagreements.append(f"{group_id}:input_binding")
                continue
            expected_owner_id = binding.get("owner_element_id")
            expected_alternate_id = (
                binding.get("alternate_element_id")
            )
            trace_locations = {
                str(value) for value in trace.get("trace_locations", [])
            }
            if expected_owner_id is not None:
                if "legacy_projection" not in trace_locations:
                    disagreements.append(f"{group_id}:trace_location")
            elif trace_locations != {"ir_element"}:
                disagreements.append(f"{group_id}:trace_location")

            linked_rows: list[tuple[Any, Mapping[str, Any]]] = []
            for element in reconciled_ir.elements:
                legacy = element.properties.get("legacy_item")
                if not isinstance(legacy, Mapping):
                    continue
                linked_rows.extend(
                    (element, row)
                    for row in legacy.get(
                        "font_recovery_alternatives",
                        [],
                    )
                    if isinstance(row, Mapping)
                    and row.get("run_evidence_id") == run_id
                )
            expected_linked_count = int(expected_owner_id is not None)
            if (
                len(linked_rows) != expected_linked_count
                or (
                    linked_rows
                    and str(linked_rows[0][0].id)
                    != str(expected_owner_id)
                )
            ):
                disagreements.append(f"{group_id}:legacy_topology")

            font_selected = (
                terminal and f"font:{run_id}" in selected_ids
            )
            if linked_rows and (
                linked_rows[0][1].get("selected") is not font_selected
            ):
                disagreements.append(f"{group_id}:legacy_selection")
            owner = (
                next(
                    (
                        element
                        for element in reconciled_ir.elements
                        if str(element.id) == str(expected_owner_id)
                    ),
                    None,
                )
                if expected_owner_id is not None
                else None
            )
            if expected_owner_id is not None:
                owner_state = (
                    property_trace(owner, group_id)
                    if owner is not None
                    else None
                )
                if (
                    owner_state is None
                    or owner_state.get("selected") is not terminal
                    or (
                        terminal
                        and canonical_counts[str(expected_owner_id)] != 1
                    )
                ):
                    disagreements.append(f"{group_id}:owner_surface")

            alternate = (
                next(
                    (
                        element
                        for element in reconciled_ir.elements
                        if str(element.id) == str(expected_alternate_id)
                    ),
                    None,
                )
                if expected_alternate_id is not None
                else None
            )
            observed_font_elements = [
                element
                for element in reconciled_ir.elements
                if (
                    isinstance(
                        element.properties.get("font_recovery"),
                        Mapping,
                    )
                    and element.properties["font_recovery"].get(
                        "run_evidence_id"
                    )
                    == run_id
                )
            ]
            if {
                str(element.id) for element in observed_font_elements
            } != (
                {str(expected_alternate_id)}
                if expected_alternate_id is not None
                else set()
            ):
                disagreements.append(f"{group_id}:element_topology")
            if alternate is not None:
                raw_font = alternate.properties.get("font_recovery")
                alternate_state = property_trace(alternate, group_id)
                if not (
                    isinstance(raw_font, Mapping)
                    and raw_font.get("selected") is font_selected
                    and isinstance(alternate_state, Mapping)
                    and alternate_state.get("selected") is font_selected
                ):
                    disagreements.append(
                        f"{group_id}:alternate_selection"
                    )
                alternative_relationships = [
                    relationship
                    for relationship in relationships_by_source.get(
                        str(alternate.id),
                        [],
                    )
                    if str(relationship.type.value) == "alternative_of"
                ]
                if expected_owner_id is None:
                    if alternative_relationships:
                        disagreements.append(
                            f"{group_id}:ownerless_relationship"
                        )
                    if font_selected and (
                        canonical_counts[str(alternate.id)] != 1
                        or str(alternate.presentation_role) == "alternate"
                    ):
                        disagreements.append(
                            f"{group_id}:ownerless_canonical"
                        )
                elif (
                    len(alternative_relationships) != 1
                    or str(alternative_relationships[0].target_id)
                    != str(expected_owner_id)
                ):
                    disagreements.append(
                        f"{group_id}:relationship_topology"
                    )
                else:
                    relationship = alternative_relationships[0]
                    state = relationship.metadata.get(
                        "text_reconciliation"
                    )
                    if not (
                        relationship.metadata.get("selected")
                        is font_selected
                        and isinstance(state, Mapping)
                        and state.get("group_id") == group_id
                        and state.get("selected") is font_selected
                    ):
                        disagreements.append(
                            f"{group_id}:relationship:{relationship.id}"
                        )
            continue

        if not group_id.startswith("ocr-group:"):
            continue
        span_id = str(trace.get("span_id") or "")
        ocr_elements = []
        for element in reconciled_ir.elements:
            raw = element.properties.get("selective_span_ocr")
            if isinstance(raw, Mapping) and raw.get("span_id") == span_id:
                ocr_elements.append(element)
        decisions_by_id = {
            str(decision.get("candidate_id")): decision
            for decision in decisions
        }
        observed_candidate_ids = {
            f"ocr:{element.id}:{span_id}" for element in ocr_elements
        }
        expected_candidate_ids = {
            candidate_id
            for candidate_id, decision in decisions_by_id.items()
            if decision.get("source_kind") == "selective_ocr"
        }
        if observed_candidate_ids != expected_candidate_ids:
            disagreements.append(f"{group_id}:ocr_element_topology")
        for element in ocr_elements:
            candidate_id = f"ocr:{element.id}:{span_id}"
            decision = decisions_by_id.get(candidate_id)
            expected_selected = bool(
                isinstance(decision, Mapping)
                and decision.get("selected") is True
            )
            raw = element.properties.get("selective_span_ocr")
            state = property_trace(element, group_id)
            candidate_concerns = [
                concern
                for concern in reconciled_ir.concerns
                if (
                    concern.code == "pdf_selective_ocr_alternative"
                    and concern.metadata.get("candidate_element_id")
                    == element.id
                    and concern.source_ref == span_id
                )
            ]
            if len(candidate_concerns) != 1:
                disagreements.append(
                    f"{group_id}:ocr_concern:{element.id}"
                )
                continue
            concern = candidate_concerns[0]
            source_evidence_id = concern.metadata.get("evidence_id")
            owner_id = (
                raw.get("owner_element_id")
                if isinstance(raw, Mapping)
                else None
            )
            legacy_rows: list[Mapping[str, Any]] = []
            if owner_id is not None:
                owner = next(
                    (
                        candidate
                        for candidate in reconciled_ir.elements
                        if str(candidate.id) == str(owner_id)
                    ),
                    None,
                )
                legacy = (
                    owner.properties.get("legacy_item")
                    if owner is not None
                    else None
                )
                if isinstance(legacy, Mapping):
                    legacy_rows = [
                        row
                        for row in legacy.get(
                            "selective_ocr_candidates",
                            [],
                        )
                        if (
                            isinstance(row, Mapping)
                            and row.get("span_id") == span_id
                            and row.get("evidence_id")
                            == source_evidence_id
                        )
                    ]
            if not (
                isinstance(raw, Mapping)
                and raw.get("selected") is expected_selected
                and isinstance(state, Mapping)
                and state.get("selected") is expected_selected
                and concern.metadata.get("selected")
                is expected_selected
                and len(legacy_rows) == int(owner_id is not None)
                and all(
                    row.get("selected") is expected_selected
                    for row in legacy_rows
                )
            ):
                disagreements.append(
                    f"{group_id}:ocr_selection:{element.id}"
                )
            alternative_relationships = [
                relationship
                for relationship in relationships_by_source.get(
                    str(element.id),
                    [],
                )
                if str(relationship.type.value) == "alternative_of"
            ]
            if owner_id is None:
                if alternative_relationships:
                    disagreements.append(
                        f"{group_id}:ocr_ownerless_relationship"
                    )
                if expected_selected and (
                    canonical_counts[str(element.id)] != 1
                    or str(element.presentation_role) == "alternate"
                ):
                    disagreements.append(
                        f"{group_id}:ocr_ownerless_canonical"
                    )
            elif (
                len(alternative_relationships) != 1
                or str(alternative_relationships[0].target_id)
                != str(owner_id)
            ):
                disagreements.append(
                    f"{group_id}:ocr_relationship_topology:{element.id}"
                )
            else:
                relationship = alternative_relationships[0]
                rel_state = relationship.metadata.get(
                    "text_reconciliation"
                )
                if not (
                    relationship.metadata.get("selected")
                    is expected_selected
                    and isinstance(rel_state, Mapping)
                    and rel_state.get("selected") is expected_selected
                ):
                    disagreements.append(
                        f"{group_id}:ocr_relationship:{element.id}"
                    )
    return sorted(set(disagreements))


def _reconciled_ir_operation(
    ir: Any,
    original_document: Mapping[str, Any],
    font_decision_evidence_bindings: Sequence[Mapping[str, Any]],
    expected_presentation_sha256: str,
) -> dict[str, Any]:
    """Run the production IR boundary and serialize every observable view."""

    from app.services.ir import project_legacy_pages
    from app.services.text_reconciliation import reconcile_document_ir

    reconciled = reconcile_document_ir(ir)
    ir_payload = reconciled.model_dump(mode="json", exclude_none=True)
    projection = {
        **deepcopy(dict(original_document)),
        "pages": project_legacy_pages(
            reconciled,
            original_document.get("pages", []),
        ),
    }
    presentation = _presentation_payload(reconciled)
    traces = _projection_reconciliation_traces(projection, reconciled)
    alternative_state = _projection_alternative_state(projection)
    trace_coverage = _report_coverage({"outcomes": traces})
    input_texts = _source_text_values(ir)
    retained_evidence_ids = _retained_input_evidence_ids(ir)
    decision_evidence_ids = {
        str(evidence_id)
        for trace in traces
        for decision in trace.get("decisions", [])
        if isinstance(decision, Mapping)
        for evidence_id in decision.get("evidence_ids", [])
        if isinstance(evidence_id, str)
    }
    unretained_decision_evidence_ids = sorted(
        decision_evidence_ids - retained_evidence_ids
    )
    selected_trace_texts = [
        str(trace["selected_text"])
        for trace in traces
        if isinstance(trace.get("selected_text"), str)
    ]
    semantic_completion_count = sum(
        selected_text not in input_texts
        for selected_text in selected_trace_texts
    )
    evidence_ids_before = {str(evidence.id) for evidence in ir.evidence}
    evidence_ids_after = {
        str(evidence.id) for evidence in reconciled.evidence
    }
    evidence_core_before = _normalized_evidence_core(ir)
    evidence_core_after = _normalized_evidence_core(reconciled)
    element_core_before = _element_content_and_role_core(ir)
    element_core_after = _element_content_and_role_core(reconciled)
    full = presentation.get("full", {})
    block_ids = [str(value) for value in full.get("block_ids", [])]
    canonical_element_counts = _canonical_element_block_counts(
        presentation
    )
    font_bindings = {
        str(binding["run_evidence_id"]): binding
        for binding in font_decision_evidence_bindings
    }
    surface_disagreements = _selection_surface_disagreements(
        reconciled,
        traces,
        canonical_element_block_counts=canonical_element_counts,
        font_bindings=font_bindings,
    )
    alternate_element_ids = {
        str(element.id)
        for element in reconciled.elements
        if str(element.presentation_role) == "alternate"
    }
    result = {
        "ir_sha256": _sha256_json(ir_payload),
        "projection_sha256": _sha256_json(projection),
        "presentation_sha256": _sha256_json(presentation),
        "canonical_presentation_unchanged": (
            _sha256_json(presentation) == expected_presentation_sha256
        ),
        "ir_fingerprint": _ir_fingerprint(reconciled),
        "trace_count": len(traces),
        "traces": traces,
        "legacy_projection_trace_count": sum(
            "legacy_projection" in trace.get("trace_locations", [])
            for trace in traces
        ),
        "ir_only_trace_count": sum(
            set(trace.get("trace_locations", [])) == {"ir_element"}
            for trace in traces
        ),
        "trace_coverage": trace_coverage,
        "font_recovery_trace_run_evidence_ids": sorted(
            run_id
            for trace in traces
            if (run_id := _font_run_id_from_trace(trace)) is not None
        ),
        "alternative_state": alternative_state,
        "reason_complete_count": trace_coverage["reason_complete_count"],
        "evidence_identity_retained": evidence_ids_before == evidence_ids_after,
        "evidence_identity_exact": evidence_ids_before == evidence_ids_after,
        "evidence_core_unchanged": (
            evidence_core_before == evidence_core_after
        ),
        "element_content_and_role_unchanged": (
            element_core_before == element_core_after
        ),
        "evidence_identity_before_count": len(evidence_ids_before),
        "evidence_identity_after_count": len(evidence_ids_after),
        "decision_evidence_id_count": len(decision_evidence_ids),
        "font_decision_evidence_binding_count": len(font_bindings),
        "font_decision_evidence_bindings_sha256": _sha256_json(
            list(font_decision_evidence_bindings)
        ),
        "unretained_decision_evidence_ids": (
            unretained_decision_evidence_ids
        ),
        "semantic_completion_count": semantic_completion_count,
        "canonical_duplicate_block_id_count": (
            len(block_ids) - len(set(block_ids))
        ),
        "canonical_full_block_count": len(block_ids),
        "canonical_element_contribution_count": len(
            canonical_element_counts
        ),
        "canonical_element_block_counts_sha256": _sha256_json(
            dict(sorted(canonical_element_counts.items()))
        ),
        "alternate_canonical_leak_count": len(
            set(canonical_element_counts) & alternate_element_ids
        ),
        "selection_surface_disagreements": surface_disagreements,
        "target_sentence_counts": {
            "projected_values": sum(
                str(item.get("value") or "").count(TARGET_SENTENCE)
                for page in projection.get("pages", [])
                if isinstance(page, Mapping)
                for item in page.get("items", [])
                if isinstance(item, Mapping)
            ),
            "canonical_text": str(full.get("text") or "").count(
                TARGET_SENTENCE
            ),
            "canonical_markdown": str(full.get("markdown") or "").count(
                TARGET_SENTENCE
            ),
        },
    }
    _canonical_json(result)
    return result


def _flag_off_parity(prepared: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the omitted-US04 path with the explicit default-off path."""

    from app.services.ir import round_trip_document

    explicit_off_projection, explicit_off_ir = round_trip_document(
        prepared["document"],
        font_audit=prepared["audit"],
        font_recovery=prepared["recovery"],
        selective_span_ocr=prepared["selective"],
        text_reconciliation_enabled=False,
    )
    return _exact_parity(
        prepared["p02_us03_projection"],
        prepared["p02_us03_ir"],
        explicit_off_projection,
        explicit_off_ir,
    )


def _flag_on_integration(
    prepared: Mapping[str, Any],
    direct_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Exercise the production round-trip flag and compare the direct adapter."""

    from app.services.ir import round_trip_document

    projection, ir = round_trip_document(
        prepared["document"],
        font_audit=prepared["audit"],
        font_recovery=prepared["recovery"],
        selective_span_ocr=prepared["selective"],
        text_reconciliation_enabled=True,
    )
    observed = {
        "projection_sha256": _sha256_json(projection),
        "ir_sha256": _ir_fingerprint(ir)["sha256"],
        "presentation_sha256": _sha256_json(_presentation_payload(ir)),
    }
    expected = {
        key: str(direct_result[key]) for key in observed
    }
    return {
        "exact": observed == expected,
        "observed": observed,
        "direct_adapter": expected,
    }


def _reconciliation_reentry(
    prepared: Mapping[str, Any],
) -> dict[str, Any]:
    """Require production reconciliation re-entry to be byte-stable."""

    from app.services.ir import project_legacy_pages
    from app.services.text_reconciliation import reconcile_document_ir

    first_ir = reconcile_document_ir(prepared["p02_us03_ir"])
    second_ir = reconcile_document_ir(first_ir)
    first_projection = {
        **deepcopy(dict(prepared["document"])),
        "pages": project_legacy_pages(
            first_ir,
            prepared["document"].get("pages", []),
        ),
    }
    second_projection = {
        **deepcopy(dict(prepared["document"])),
        "pages": project_legacy_pages(
            second_ir,
            prepared["document"].get("pages", []),
        ),
    }
    parity = _exact_parity(
        first_projection,
        first_ir,
        second_projection,
        second_ir,
    )
    return {
        **parity,
        "first_projection_sha256": parity["left_projection_sha256"],
        "second_projection_sha256": parity["right_projection_sha256"],
        "first_ir_sha256": parity["left_ir_sha256"],
        "second_ir_sha256": parity["right_ir_sha256"],
        "first_presentation_sha256": parity["left_presentation_sha256"],
        "second_presentation_sha256": parity[
            "right_presentation_sha256"
        ],
        "same_object_on_reentry": second_ir is first_ir,
        "first_terminal_concern_count": sum(
            concern.code
            in {
                "pdf_text_reconciliation_selected",
                "pdf_text_reconciliation_unresolved",
            }
            for concern in first_ir.concerns
        ),
        "second_terminal_concern_count": sum(
            concern.code
            in {
                "pdf_text_reconciliation_selected",
                "pdf_text_reconciliation_unresolved",
            }
            for concern in second_ir.concerns
        ),
        "first_manifest_count": sum(
            concern.code == "pdf_text_reconciliation_complete"
            for concern in first_ir.concerns
        ),
        "second_manifest_count": sum(
            concern.code == "pdf_text_reconciliation_complete"
            for concern in second_ir.concerns
        ),
    }


def _actual_case_measurement(
    workspace: Path,
    case_id: str,
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    """Measure the real final-code IR boundary for one immutable corpus case."""

    prepared = _prepare_actual_p02_us03_case(workspace, case_id)
    input_ir = prepared["p02_us03_ir"]
    input_fingerprint = _ir_fingerprint(input_ir)
    expected_presentation_sha256 = _sha256_json(
        prepared["p02_us03_presentation"]
    )
    flag_off_parity = _flag_off_parity(prepared)
    if not flag_off_parity["exact"]:
        raise RuntimeError(f"{case_id} explicit flag-off output drifted")

    rss_before = _peak_rss_bytes()
    result, durations_ms = _measure_deterministic(
        lambda: _reconciled_ir_operation(
            input_ir,
            prepared["document"],
            prepared["font_decision_evidence_bindings"],
            expected_presentation_sha256,
        ),
        warmups=warmups,
        samples=samples,
    )
    rss_after = _peak_rss_bytes()
    flag_on_integration = _flag_on_integration(prepared, result)
    if not flag_on_integration["exact"]:
        raise RuntimeError(
            f"{case_id} flag-on round-trip differs from direct adapter"
        )
    reconciliation_reentry = _reconciliation_reentry(prepared)
    if (
        not reconciliation_reentry["exact"]
        or not reconciliation_reentry["same_object_on_reentry"]
        or reconciliation_reentry["first_ir_sha256"]
        != result["ir_sha256"]
        or reconciliation_reentry["first_projection_sha256"]
        != result["projection_sha256"]
        or reconciliation_reentry["first_presentation_sha256"]
        != result["presentation_sha256"]
    ):
        raise RuntimeError(
            f"{case_id} reconciliation re-entry drifted"
        )
    if _ir_fingerprint(input_ir) != input_fingerprint:
        raise RuntimeError(f"{case_id} reconciliation mutated caller IR")
    if (
        not result["evidence_identity_exact"]
        or not result["evidence_core_unchanged"]
        or not result["element_content_and_role_unchanged"]
        or not result["canonical_presentation_unchanged"]
        or result["unretained_decision_evidence_ids"]
        or result["semantic_completion_count"] != 0
        or result["canonical_duplicate_block_id_count"] != 0
        or result["alternate_canonical_leak_count"] != 0
        or result["selection_surface_disagreements"]
        or result["reason_complete_count"] != result["trace_count"]
        or result["trace_coverage"]["reason_coverage"] != 1.0
        or result["trace_coverage"]["evidence_coverage"] != 1.0
        or result["trace_coverage"]["schema_coverage"] != 1.0
        or result["trace_coverage"]["alternative_retention"] != 1.0
        or result["trace_coverage"]["canonical_duplicate_count"] != 0
    ):
        raise RuntimeError(
            f"{case_id} production reconciliation evidence gate failed"
        )

    healthy = case_id != CATASTROPHE_CASE_ID
    catastrophe_policy_resolution: dict[str, Any] | None = None
    if healthy:
        if (
            result["trace_count"] != 0
            or result["ir_sha256"] != input_fingerprint["sha256"]
            or result["projection_sha256"]
            != _sha256_json(prepared["p02_us03_projection"])
            or result["presentation_sha256"]
            != expected_presentation_sha256
        ):
            raise RuntimeError(
                f"{case_id} healthy flag-on reconciliation was not inert"
            )
    else:
        ownership = prepared["recovery_ownership"]
        expected_by_run = {
            str(run["evidence_id"]): str(run["recovered_text"])
            for run in prepared["recovery"].get("runs", [])
            if isinstance(run, Mapping)
        }
        expected_original_by_run = {
            str(run["evidence_id"]): str(run["original_text"])
            for run in prepared["recovery"].get("runs", [])
            if isinstance(run, Mapping)
        }
        evidence_bindings_by_run = {
            str(binding["run_evidence_id"]): binding
            for binding in prepared["font_decision_evidence_bindings"]
        }
        prose_run_ids = set(
            EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
        )
        chart_run_ids = set(
            EXPECTED_ACTUAL_CATASTROPHE_CHART_RUN_IDS
        )
        ownerless_run_ids = set(
            EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUN_IDS
        )
        pinned_run_ids = (
            prose_run_ids | chart_run_ids | ownerless_run_ids
        )
        if (
            prose_run_ids & chart_run_ids
            or prose_run_ids & ownerless_run_ids
            or chart_run_ids & ownerless_run_ids
            or set(expected_by_run) != pinned_run_ids
            or set(expected_original_by_run) != pinned_run_ids
            or {
                run_id: expected_by_run[run_id]
                for run_id in prose_run_ids
            }
            != EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
            or set(
                ownership["owner_linked_run_evidence_ids"]
            )
            != prose_run_ids | chart_run_ids
            or set(ownership["ownerless_run_evidence_ids"])
            != ownerless_run_ids
            or set(evidence_bindings_by_run) != pinned_run_ids
            or not all(
                binding.get("owner_element_id")
                == EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
                and binding.get("alternate_element_id") is None
                for run_id, binding in evidence_bindings_by_run.items()
                if run_id in prose_run_ids
            )
            or not all(
                binding.get("owner_element_id")
                == EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
                and isinstance(
                    binding.get("alternate_element_id"),
                    str,
                )
                and bool(binding["alternate_element_id"])
                for run_id, binding in evidence_bindings_by_run.items()
                if run_id in chart_run_ids
            )
            or not all(
                binding.get("owner_element_id") is None
                and isinstance(
                    binding.get("alternate_element_id"),
                    str,
                )
                and bool(binding["alternate_element_id"])
                for run_id, binding in evidence_bindings_by_run.items()
                if run_id in ownerless_run_ids
            )
        ):
            raise RuntimeError(
                "catastrophe pinned recovery membership drifted"
            )
        already_primary_run_ids = {
            run_id
            for run_id, binding in evidence_bindings_by_run.items()
            if (
                binding.get("owner_element_id") is not None
                and binding.get("alternate_element_id") is None
            )
        }
        if already_primary_run_ids != prose_run_ids:
            raise RuntimeError(
                "catastrophe already-primary run topology drifted"
            )
        expected_selected = Counter(
            expected_by_run[run_id] for run_id in already_primary_run_ids
        )
        observed_selected = Counter(
            str(trace["selected_text"])
            for trace in result["traces"]
            if trace.get("status") in {"selected", "unchanged"}
            and isinstance(trace.get("selected_text"), str)
        )
        traces_by_run = {
            run_id: trace
            for trace in result["traces"]
            if (run_id := _font_run_id_from_trace(trace)) is not None
        }

        def decisions_match(
            run_id: str,
            trace: Mapping[str, Any],
        ) -> bool:
            raw_decisions = trace.get("decisions")
            if (
                not isinstance(raw_decisions, list)
                or len(raw_decisions) != 2
                or not all(
                    isinstance(decision, Mapping)
                    for decision in raw_decisions
                )
            ):
                return False
            decision_ids = [
                str(decision.get("candidate_id") or "")
                for decision in raw_decisions
            ]
            if (
                len(decision_ids) != len(set(decision_ids))
                or set(decision_ids)
                != {f"font:{run_id}", f"native:{run_id}"}
            ):
                return False
            decisions_by_id = {
                str(decision["candidate_id"]): decision
                for decision in raw_decisions
            }
            if {
                candidate_id: list(decision.get("evidence_ids", []))
                for candidate_id, decision in decisions_by_id.items()
            } != {
                f"font:{run_id}": list(
                    evidence_bindings_by_run[run_id][
                        "font_evidence_ids"
                    ]
                ),
                f"native:{run_id}": list(
                    evidence_bindings_by_run[run_id][
                        "native_evidence_ids"
                    ]
                ),
            }:
                return False
            font_decision = decisions_by_id[f"font:{run_id}"]
            native_decision = decisions_by_id[f"native:{run_id}"]
            if (
                font_decision.get("text") != expected_by_run[run_id]
                or native_decision.get("text")
                != expected_original_by_run[run_id]
                or native_decision.get("selected") is not False
            ):
                return False
            if run_id in already_primary_run_ids:
                return bool(
                    font_decision.get("reason_codes")
                    == ["deterministic_font_safe"]
                    and font_decision.get("selected") is True
                    and native_decision.get("reason_codes")
                    == ["native_mapping_unsafe"]
                )
            return bool(
                "replacement_range_ambiguous"
                in font_decision.get("reason_codes", [])
                and font_decision.get("selected") is False
                and "native_mapping_unsafe"
                in native_decision.get("reason_codes", [])
            )

        exact_trace_binding = (
            set(traces_by_run) == set(expected_by_run)
            and set(evidence_bindings_by_run) == set(expected_by_run)
            and all(
                (
                    (
                        trace.get("status") == "unchanged"
                        and trace.get("selected_text")
                        == expected_by_run[run_id]
                        and trace.get("reason_code")
                        == "deterministic_font_evidence"
                        and trace.get("selected_candidate_ids")
                        == [f"font:{run_id}"]
                        and trace.get("replacement_mode") == "none"
                    )
                    if run_id in already_primary_run_ids
                    else (
                        trace.get("status") == "unresolved"
                        and trace.get("selected_text") is None
                        and trace.get("reason_code")
                        == "replacement_range_ambiguous"
                        and trace.get("selected_candidate_ids") == []
                        and trace.get("replacement_mode") == "none"
                    )
                )
                and decisions_match(run_id, trace)
                for run_id, trace in traces_by_run.items()
            )
        )
        legacy_item_ids_by_run = {
            run_id: {
                str(source["item_id"])
                for source in trace.get("trace_sources", [])
                if (
                    isinstance(source, Mapping)
                    and source.get("trace_location")
                    == "legacy_projection"
                    and source.get("item_id") is not None
                )
            }
            for run_id, trace in traces_by_run.items()
        }
        exact_trace_topology = (
            all(
                trace.get("owner_element_id")
                == EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
                and legacy_item_ids_by_run[run_id]
                == {
                    EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID
                }
                for run_id, trace in traces_by_run.items()
                if run_id in prose_run_ids
            )
            and all(
                trace.get("owner_element_id")
                == EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
                and legacy_item_ids_by_run[run_id]
                == {
                    EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID
                }
                for run_id, trace in traces_by_run.items()
                if run_id in chart_run_ids
            )
            and all(
                legacy_item_ids_by_run[run_id] == set()
                and set(trace.get("trace_locations", []))
                == {"ir_element"}
                and trace.get("owner_element_id")
                == evidence_bindings_by_run[run_id].get(
                    "alternate_element_id"
                )
                for run_id, trace in traces_by_run.items()
                if run_id in ownerless_run_ids
            )
        )
        linked_trace_ids = set(traces_by_run) & set(
            ownership["owner_linked_run_evidence_ids"]
        )
        ownerless_trace_ids = set(traces_by_run) & set(
            ownership["ownerless_run_evidence_ids"]
        )
        unchanged_run_ids = {
            run_id
            for run_id, trace in traces_by_run.items()
            if trace.get("status") == "unchanged"
        }
        unresolved_run_ids = {
            run_id
            for run_id, trace in traces_by_run.items()
            if trace.get("status") == "unresolved"
        }
        selected_ownerless_run_ids = {
            run_id
            for run_id in ownerless_trace_ids
            if traces_by_run[run_id].get("selected_candidate_ids")
        }
        if (
            len(prepared["recovery"].get("runs", []))
            != EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS
            or ownership["owner_linked_run_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
            or ownership["ownerless_run_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
            or result["trace_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS
            or result["font_decision_evidence_binding_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS
            or result["legacy_projection_trace_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
            or result["ir_only_trace_count"]
            != EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
            or not exact_trace_binding
            or not exact_trace_topology
            or len(linked_trace_ids)
            != EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
            or len(ownerless_trace_ids)
            != EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
            or unchanged_run_ids != already_primary_run_ids
            or len(unresolved_run_ids)
            != EXPECTED_ACTUAL_CATASTROPHE_UNRESOLVED_RUNS
            or selected_ownerless_run_ids
            or len(selected_ownerless_run_ids)
            != EXPECTED_ACTUAL_CATASTROPHE_SELECTED_OWNERLESS_RUNS
            or observed_selected != expected_selected
            or set(result["target_sentence_counts"].values()) != {1}
            or result["alternative_state"][
                "font_recovery_alternative_count"
            ]
            != EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
            or result["alternative_state"][
                "font_recovery_selected_count"
            ]
            != EXPECTED_ACTUAL_CATASTROPHE_UNCHANGED_RUNS
            or result["alternative_state"][
                "selective_ocr_candidate_count"
            ]
            != 0
        ):
            raise RuntimeError(
                "actual catastrophe recovery did not reconcile exactly"
            )
        catastrophe_policy_resolution = {
            "policy": (
                "preserve already-primary prose; leave ambiguous linked "
                "chart and ownerless alternatives unresolved"
            ),
            "prose_run_text": dict(
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_RUN_TEXT
            ),
            "prose_owner_element_id": (
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_OWNER_ELEMENT_ID
            ),
            "prose_legacy_item_id": (
                EXPECTED_ACTUAL_CATASTROPHE_PROSE_LEGACY_ITEM_ID
            ),
            "chart_run_ids": sorted(chart_run_ids),
            "chart_owner_element_id": (
                EXPECTED_ACTUAL_CATASTROPHE_CHART_OWNER_ELEMENT_ID
            ),
            "chart_legacy_item_id": (
                EXPECTED_ACTUAL_CATASTROPHE_CHART_LEGACY_ITEM_ID
            ),
            "pinned_ownerless_run_ids": sorted(ownerless_run_ids),
            "already_primary_unchanged_run_ids": sorted(
                unchanged_run_ids
            ),
            "owner_linked_unresolved_run_ids": sorted(
                unresolved_run_ids & linked_trace_ids
            ),
            "ownerless_unresolved_run_ids": sorted(
                unresolved_run_ids & ownerless_trace_ids
            ),
            "selected_ownerless_run_ids": sorted(
                selected_ownerless_run_ids
            ),
            "unchanged_count": len(unchanged_run_ids),
            "unresolved_count": len(unresolved_run_ids),
            "selected_ownerless_count": len(
                selected_ownerless_run_ids
            ),
            "canonical_presentation_unchanged": result[
                "canonical_presentation_unchanged"
            ],
            "element_content_and_role_unchanged": result[
                "element_content_and_role_unchanged"
            ],
        }

    return {
        "evidence_class": "actual_production_input",
        "actual_production_input": True,
        "healthy_control": healthy,
        **prepared["binding"],
        "audit_report_sha256": prepared["audit_report_sha256"],
        "recovery_report_sha256": prepared["recovery_report_sha256"],
        "selective_report_sha256": prepared["selective_report_sha256"],
        "recovery_ownership": prepared["recovery_ownership"],
        "font_decision_evidence_bindings": prepared[
            "font_decision_evidence_bindings"
        ],
        "catastrophe_policy_resolution": catastrophe_policy_resolution,
        "audit_finding_count": len(prepared["audit"].get("findings", [])),
        "recovery_run_count": len(prepared["recovery"].get("runs", [])),
        "selective_known_span_count": int(
            prepared["selective"]["known_span_count"]
        ),
        "input_ir_fingerprint": input_fingerprint,
        "flag_off_parity": flag_off_parity,
        "flag_on_integration": flag_on_integration,
        "reconciliation_reentry": reconciliation_reentry,
        "warmup_count": warmups,
        "sample_count": samples,
        "latency_ms": _distribution(durations_ms),
        "latency_samples_ms": durations_ms,
        "peak_rss_before_bytes": rss_before,
        "peak_rss_after_bytes": rss_after,
        "peak_rss_increment_bytes": max(rss_after - rss_before, 0),
        "structurally_deterministic": True,
        "result": result,
    }


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
        "tests.benchmarks.text_reconciliation_metrics",
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
        raise TypeError("reconciliation worker must return a JSON object")
    return payload


def _collect(
    workspace: Path,
    *,
    warmups: int,
    samples: int,
    output: Path | None = None,
) -> dict[str, Any]:
    """Collect custody, correctness, determinism, and component performance."""

    workspace = workspace.resolve()
    retained = _retained_inputs(workspace)
    environment_compatibility = _environment_compatibility(
        workspace,
        retained,
    )
    code_bindings = _code_bindings(workspace)
    limitations = _fixture_limitations(workspace, retained)
    actual_cases = [
        _run_worker(
            workspace,
            scenario="actual",
            case_id=case_id,
            warmups=warmups,
            samples=samples,
        )
        for case_id in EXPECTED_CASE_IDS
    ]
    synthetic = _run_worker(
        workspace,
        scenario="synthetic",
        case_id=None,
        warmups=warmups,
        samples=samples,
    )
    actual_renderer_test_only = _run_worker(
        workspace,
        scenario="actual_renderer_test_only",
        case_id=None,
        warmups=warmups,
        samples=samples,
    )

    healthy_cases = [
        case for case in actual_cases if bool(case["healthy_control"])
    ]
    catastrophe = next(
        case
        for case in actual_cases
        if case["case_id"] == CATASTROPHE_CASE_ID
    )
    if (
        len(actual_cases) != len(EXPECTED_CASE_IDS)
        or len(healthy_cases) != len(EXPECTED_CASE_IDS) - 1
        or sum(bool(case["flag_off_parity"]["exact"]) for case in actual_cases)
        != len(EXPECTED_CASE_IDS)
        or sum(
            bool(case["flag_on_integration"]["exact"])
            for case in actual_cases
        )
        != len(EXPECTED_CASE_IDS)
        or sum(
            bool(case["reconciliation_reentry"]["exact"])
            and bool(
                case["reconciliation_reentry"][
                    "same_object_on_reentry"
                ]
            )
            for case in actual_cases
        )
        != len(EXPECTED_CASE_IDS)
        or catastrophe["recovery_ownership"]["owner_linked_run_count"]
        != EXPECTED_ACTUAL_CATASTROPHE_OWNER_LINKED_RUNS
        or catastrophe["recovery_ownership"]["ownerless_run_count"]
        != EXPECTED_ACTUAL_CATASTROPHE_OWNERLESS_RUNS
        or catastrophe["reconciliation_reentry"][
            "second_terminal_concern_count"
        ]
        != EXPECTED_ACTUAL_CATASTROPHE_RECOVERY_RUNS
        or catastrophe["reconciliation_reentry"][
            "second_manifest_count"
        ]
        != 1
    ):
        raise RuntimeError("actual corpus reconciliation coverage drifted")

    healthy_durations: list[float] = []
    healthy_overheads: list[float] = []
    for case in healthy_cases:
        durations = [
            float(value) for value in case["latency_samples_ms"]
        ]
        healthy_durations.extend(durations)
        healthy_overheads.extend(
            duration / float(case["phase_0_parse_latency_ms"]) * 100.0
            for duration in durations
        )
    all_actual_durations = [
        float(value)
        for case in actual_cases
        for value in case["latency_samples_ms"]
    ]
    healthy_overhead_distribution = _distribution(healthy_overheads)
    combined_ceiling = _combined_healthy_ceiling(
        retained,
        healthy_overhead_distribution["p95"],
    )
    if not combined_ceiling["passes_target"]:
        raise RuntimeError("cumulative healthy p95 ceiling exceeded 10%")

    actual_reason_total = sum(
        int(case["result"]["reason_complete_count"])
        for case in actual_cases
    )
    actual_trace_total = sum(
        int(case["result"]["trace_count"]) for case in actual_cases
    )
    total_semantic_completions = (
        sum(
            int(case["result"]["semantic_completion_count"])
            for case in actual_cases
        )
        + int(synthetic["coverage"]["semantic_completion_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "semantic_completion_count"
            ]
        )
    )
    total_canonical_duplicates = (
        sum(
            int(case["result"]["canonical_duplicate_block_id_count"])
            for case in actual_cases
        )
        + int(synthetic["coverage"]["canonical_duplicate_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "canonical_duplicate_count"
            ]
        )
    )
    total_alternate_canonical_leaks = sum(
        int(case["result"]["alternate_canonical_leak_count"])
        for case in actual_cases
    )
    total_selection_surface_disagreements = sum(
        len(case["result"]["selection_surface_disagreements"])
        for case in actual_cases
    )
    total_unretained_decision_evidence_ids = sum(
        len(case["result"]["unretained_decision_evidence_ids"])
        for case in actual_cases
    )
    reason_denominator = (
        actual_trace_total
        + int(synthetic["coverage"]["outcome_count"])
        + int(actual_renderer_test_only["coverage"]["outcome_count"])
    )
    reason_numerator = (
        actual_reason_total
        + int(synthetic["coverage"]["reason_complete_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "reason_complete_count"
            ]
        )
    )
    actual_evidence_total = sum(
        int(case["result"]["trace_coverage"]["evidence_complete_count"])
        for case in actual_cases
    )
    actual_alternative_total = sum(
        int(
            case["result"]["trace_coverage"][
                "alternatives_complete_count"
            ]
        )
        for case in actual_cases
    )
    evidence_denominator = (
        actual_trace_total
        + int(synthetic["coverage"]["outcome_count"])
        + int(actual_renderer_test_only["coverage"]["outcome_count"])
    )
    evidence_numerator = (
        actual_evidence_total
        + int(synthetic["coverage"]["evidence_complete_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "evidence_complete_count"
            ]
        )
    )
    alternative_denominator = (
        actual_trace_total
        + int(synthetic["coverage"]["outcome_count"])
        + int(actual_renderer_test_only["coverage"]["outcome_count"])
    )
    alternative_numerator = (
        actual_alternative_total
        + int(synthetic["coverage"]["alternatives_complete_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "alternatives_complete_count"
            ]
        )
    )
    reason_coverage = (
        reason_numerator / reason_denominator if reason_denominator else 1.0
    )
    evidence_coverage = (
        evidence_numerator / evidence_denominator
        if evidence_denominator
        else 1.0
    )
    alternative_retention = (
        alternative_numerator / alternative_denominator
        if alternative_denominator
        else 1.0
    )
    schema_denominator = reason_denominator
    schema_numerator = (
        sum(
            int(case["result"]["trace_coverage"]["schema_complete_count"])
            for case in actual_cases
        )
        + int(synthetic["coverage"]["schema_complete_count"])
        + int(
            actual_renderer_test_only["coverage"][
                "schema_complete_count"
            ]
        )
    )
    schema_coverage = (
        schema_numerator / schema_denominator
        if schema_denominator
        else 1.0
    )
    if (
        reason_coverage != 1.0
        or evidence_coverage != 1.0
        or schema_coverage != 1.0
        or alternative_retention != 1.0
        or total_semantic_completions != 0
        or total_canonical_duplicates != 0
        or total_alternate_canonical_leaks != 0
        or total_selection_surface_disagreements != 0
        or total_unretained_decision_evidence_ids != 0
    ):
        raise RuntimeError("aggregate reconciliation correctness gate failed")

    peak_increments = [
        int(case["peak_rss_increment_bytes"]) for case in actual_cases
    ] + [
        int(synthetic["peak_rss_increment_bytes"]),
        int(actual_renderer_test_only["peak_rss_increment_bytes"]),
    ]
    summary = {
        "actual_production_case_count": len(actual_cases),
        "exact_source_hash_count": len(actual_cases),
        "actual_catastrophe_case_count": 1,
        "actual_catastrophe_recovery_run_count": catastrophe[
            "recovery_run_count"
        ],
        "actual_catastrophe_owner_linked_run_count": catastrophe[
            "recovery_ownership"
        ]["owner_linked_run_count"],
        "actual_catastrophe_ownerless_run_count": catastrophe[
            "recovery_ownership"
        ]["ownerless_run_count"],
        "actual_catastrophe_terminal_group_count": catastrophe["result"][
            "trace_count"
        ],
        "actual_catastrophe_legacy_projection_trace_count": catastrophe[
            "result"
        ]["legacy_projection_trace_count"],
        "actual_catastrophe_ownerless_ir_only_trace_count": catastrophe[
            "result"
        ]["ir_only_trace_count"],
        "actual_catastrophe_unchanged_count": catastrophe[
            "catastrophe_policy_resolution"
        ]["unchanged_count"],
        "actual_catastrophe_unresolved_count": catastrophe[
            "catastrophe_policy_resolution"
        ]["unresolved_count"],
        "actual_catastrophe_owner_linked_unresolved_count": len(
            catastrophe["catastrophe_policy_resolution"][
                "owner_linked_unresolved_run_ids"
            ]
        ),
        "actual_catastrophe_ownerless_unresolved_count": len(
            catastrophe["catastrophe_policy_resolution"][
                "ownerless_unresolved_run_ids"
            ]
        ),
        "actual_catastrophe_selected_ownerless_count": catastrophe[
            "catastrophe_policy_resolution"
        ]["selected_ownerless_count"],
        "actual_catastrophe_canonical_presentation_unchanged": (
            catastrophe["catastrophe_policy_resolution"][
                "canonical_presentation_unchanged"
            ]
        ),
        "actual_catastrophe_element_content_and_role_unchanged": (
            catastrophe["catastrophe_policy_resolution"][
                "element_content_and_role_unchanged"
            ]
        ),
        "actual_catastrophe_linked_alternative_selected_count": catastrophe[
            "result"
        ]["alternative_state"]["font_recovery_selected_count"],
        "actual_catastrophe_target_sentence_exact": (
            set(catastrophe["result"]["target_sentence_counts"].values())
            == {1}
        ),
        "retained_p02_us02_catastrophe_reviewed_region_count": (
            retained["catastrophe_correctness"]["reviewed_region_count"]
        ),
        "retained_p02_us02_catastrophe_reviewed_regions_exact": (
            retained["catastrophe_correctness"][
                "all_reviewed_regions_exact"
            ]
        ),
        "healthy_control_count": len(healthy_cases),
        "healthy_flag_on_exact_parity_count": sum(
            case["result"]["ir_sha256"]
            == case["input_ir_fingerprint"]["sha256"]
            for case in healthy_cases
        ),
        "flag_off_exact_parity_count": sum(
            bool(case["flag_off_parity"]["exact"]) for case in actual_cases
        ),
        "flag_on_round_trip_exact_count": sum(
            bool(case["flag_on_integration"]["exact"])
            for case in actual_cases
        ),
        "actual_reentry_exact_count": sum(
            bool(case["reconciliation_reentry"]["exact"])
            and bool(
                case["reconciliation_reentry"][
                    "same_object_on_reentry"
                ]
            )
            for case in actual_cases
        ),
        "authenticated_manifest_reentry_exact_count": sum(
            bool(case["reconciliation_reentry"]["exact"])
            and case["reconciliation_reentry"]["first_manifest_count"]
            == 1
            and case["reconciliation_reentry"]["second_manifest_count"]
            == 1
            for case in actual_cases
        ),
        "actual_catastrophe_reentry_terminal_group_count": catastrophe[
            "reconciliation_reentry"
        ]["second_terminal_concern_count"],
        "actual_catastrophe_reentry_manifest_count": catastrophe[
            "reconciliation_reentry"
        ]["second_manifest_count"],
        "actual_evidence_identity_exact_count": sum(
            bool(case["result"]["evidence_identity_exact"])
            for case in actual_cases
        ),
        "actual_evidence_core_unchanged_count": sum(
            bool(case["result"]["evidence_core_unchanged"])
            for case in actual_cases
        ),
        "actual_element_content_and_role_unchanged_count": sum(
            bool(
                case["result"][
                    "element_content_and_role_unchanged"
                ]
            )
            for case in actual_cases
        ),
        "actual_canonical_presentation_unchanged_count": sum(
            bool(case["result"]["canonical_presentation_unchanged"])
            for case in actual_cases
        ),
        "actual_production_reconciliation_latency_ms": _distribution(
            all_actual_durations
        ),
        "actual_catastrophe_reconciliation_latency_ms": catastrophe[
            "latency_ms"
        ],
        "healthy_reconciliation_latency_ms": _distribution(
            healthy_durations
        ),
        "healthy_reconciliation_additive_overhead_percent": (
            healthy_overhead_distribution
        ),
        "deterministic_synthetic_scenario_count": synthetic[
            "scenario_count"
        ],
        "deterministic_synthetic_group_count": synthetic["group_count"],
        "deterministic_synthetic_terminal_counts": synthetic[
            "observed_terminal_counts"
        ],
        "actual_renderer_test_only_group_count": (
            actual_renderer_test_only["group_count"]
        ),
        "actual_renderer_test_only_unresolved_count": len(
            actual_renderer_test_only["outcomes"]
        ),
        "actual_production_ocr_win_fixture_available": limitations[
            "actual_production_ocr_win_fixture_available"
        ],
        "reviewed_typed_false_duplicate_candidate_registry_available": (
            limitations[
                "reviewed_typed_false_duplicate_candidate_registry_available"
            ]
        ),
        "reason_coverage": reason_coverage,
        "evidence_coverage": evidence_coverage,
        "schema_coverage": schema_coverage,
        "alternative_retention": alternative_retention,
        "canonical_duplicate_count": total_canonical_duplicates,
        "alternate_canonical_leak_count": (
            total_alternate_canonical_leaks
        ),
        "selection_surface_disagreement_count": (
            total_selection_surface_disagreements
        ),
        "unretained_decision_evidence_id_count": (
            total_unretained_decision_evidence_ids
        ),
        "semantic_completion_count": total_semantic_completions,
        "max_isolated_peak_rss_increment_bytes": max(peak_increments),
        "combined_healthy_p95_ceiling_reference": combined_ceiling,
    }
    post_run_retained = _retained_inputs(workspace)
    post_run_code_bindings = _code_bindings(workspace)
    if (
        post_run_retained["identities"] != retained["identities"]
        or post_run_code_bindings != code_bindings
    ):
        raise RuntimeError(
            "retained inputs or measured code changed during collection"
        )
    summary["pre_post_custody_match"] = True
    metrics = {
        "schema_version": "1.0",
        "record_kind": "p02_us04_text_reconciliation_component_metrics",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "measurement_scope": (
            "isolated final-code text reconciliation plus strict output "
            "serialization; immutable Phase 0 PDFs/raw outputs and unmodified "
            "P02-US03 inputs are actual production inputs; retained PDFium/"
            "Tesseract evidence with a deterministic test-only upstream "
            "refusal and deterministic synthetic decision controls are "
            "reported separately and never promoted to corpus production "
            "results; audit, recovery, selective routing, and IR preparation "
            "occur outside timed regions; timed actual-document samples are "
            "a conservative upper bound covering reconciliation, legacy and "
            "canonical projection, invariant scans, structural hashing, and "
            "strict serialization; the approved corpus has no scanned "
            "or mixed scanned/native PDF and no reviewed typed registry for "
            "the historical false/duplicate OCR candidates; the cumulative "
            "healthy ceiling is arithmetic, not a paired full-parser "
            "percentile"
        ),
        "workspace": str(workspace),
        "command": [
            sys.executable,
            "-m",
            "tests.benchmarks.text_reconciliation_metrics",
            "run",
            "--workspace",
            str(workspace),
            "--warmups",
            str(warmups),
            "--samples",
            str(samples),
        ],
        "environment": environment_compatibility,
        "method": {
            "policy_id": POLICY_ID,
            "percentile_method": "nearest_rank",
            "warmups_per_scenario": warmups,
            "samples_per_scenario": samples,
            "timed_scope": (
                "reconcile_document_ir/reconcile_text_candidates; actual IR "
                "samples also include legacy/canonical projection, invariant "
                "scans, structural hashing, and strict serialization"
            ),
            "prepared_outside_timing": [
                "font_audit",
                "font_recovery",
                "selective_span_ocr",
                "source_ir",
            ],
            "observed_paired_full_parser_percentile": False,
        },
        "input_bindings": deepcopy(retained["identities"]),
        "code_bindings": code_bindings,
        "fixture_limitations": limitations,
        "summary": summary,
        "actual_production_inputs": actual_cases,
        "actual_renderer_test_only_upstream": actual_renderer_test_only,
        "deterministic_synthetic_controls": synthetic,
    }
    _canonical_json(metrics)
    if output is not None:
        output_path = output
        if not output_path.is_absolute():
            output_path = workspace / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                metrics,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--warmups", type=int, default=2)
    run.add_argument("--samples", type=int, default=10)
    run.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))

    worker = subparsers.add_parser("worker")
    worker.add_argument("--workspace", type=Path, required=True)
    worker.add_argument("--warmups", type=int, default=2)
    worker.add_argument("--samples", type=int, default=10)
    worker.add_argument(
        "--scenario",
        choices=("actual", "synthetic", "actual_renderer_test_only"),
        required=True,
    )
    worker.add_argument("--case-id", choices=EXPECTED_CASE_IDS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    if args.warmups < 0 or args.samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    if args.operation == "worker":
        if args.scenario == "actual":
            if args.case_id is None:
                raise ValueError("actual worker requires --case-id")
            payload = _actual_case_measurement(
                workspace,
                args.case_id,
                warmups=args.warmups,
                samples=args.samples,
            )
        elif args.scenario == "synthetic":
            if args.case_id is not None:
                raise ValueError("synthetic worker does not accept --case-id")
            payload = _synthetic_measurement(
                warmups=args.warmups,
                samples=args.samples,
            )
        else:
            if args.case_id is not None:
                raise ValueError(
                    "actual-render test-only worker does not accept --case-id"
                )
            retained = _retained_inputs(workspace)
            payload = _actual_renderer_test_only_measurement(
                workspace,
                retained,
                warmups=args.warmups,
                samples=args.samples,
            )
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        return 0

    metrics = _collect(
        workspace,
        warmups=args.warmups,
        samples=args.samples,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "record_kind": metrics["record_kind"],
                "summary": metrics["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
