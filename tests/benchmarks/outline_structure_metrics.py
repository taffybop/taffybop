"""Local quality, resource, and custody metrics for P03-US07 outlines.

Wall-clock timing and traced allocation are deliberately isolated. Full-parser
comparisons use fresh workers, five paired samples, and alternating flag order.
The module never writes retained evidence unless the caller supplies an
explicit ``--output`` path.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata as importlib_metadata
import json
import math
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import app.services.outline_structure as outlines
from app.config import Settings
from app.services.ir import DocumentIR, build_document_ir
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.benchmarks.form_semantics_metrics import _public_form_summary
from tests.fixtures.phase_03.outline_structure.contract import (
    POLICY_ID,
    validate_processing_summary,
    validate_source_report,
)
from tests.fixtures.phase_03.outline_structure.oracle import (
    PREDECESSOR_IDENTITIES,
    REVIEWED_COUNTS,
    SOURCE_IDENTITIES,
    SOURCE_REPORTS,
    oracle_payload,
    oracle_sha256,
)
from tests.fixtures.phase_03.outline_structure.synthetic import (
    REQUIRED_SYNTHETIC_COVERAGE,
    SYNTHETIC_FIXTURES,
    SYNTHETIC_THRESHOLDS,
    build_deadline_witness,
    build_resource_boundary_witness,
    fixture_hashes,
    registry_sha256,
    verify_pdf_readers,
)
from tests.fixtures.phase_03.outline_structure.synthetic import (
    self_check as synthetic_self_check,
)

WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
DEFAULT_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/P03-US07-outline-metrics.json"
)
PREDECESSOR_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/P03-US06-form-metrics.json"
)
PREDECESSOR_ARTIFACT_SIZE_BYTES = 82_347
PREDECESSOR_ARTIFACT_RAW_SHA256 = (
    "7e7da0d0d2a2f528b247e560399940e7c091ad765903ef5177381d140a01c290"
)
PREDECESSOR_ARTIFACT_SEMANTIC_SHA256 = (
    "7cfff9b19f129ab29f2a14317a479c50ed38397921ef9111b0a4b57f7d557fc7"
)
M0_ARTIFACT_RELATIVE_PATH = Path("tracker/benchmarks/llamaparse-15/baseline-summary.md")
M0_ARTIFACT_SIZE_BYTES = 10_127
M0_ARTIFACT_RAW_SHA256 = (
    "e4bf5583bfd7833d1f84fab631e6492e58699b8f26b03b3fcee37bf4a0e2a29a"
)

PAIRED_CASES = ("component-datasheet", "settlement-agreement")
CONTROL_CASES = (*PAIRED_CASES, "finance-10k")
PAIRED_REPEAT_COUNT = 5
FINANCE_IDENTITY = {
    "path": "benchmark-expertmodeldata/finance-10k.pdf",
    "size_bytes": 87_105,
    "sha256": "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
    "page_count": 3,
}
M0_REFERENCES = {
    "component-datasheet": {
        "label": "M0_reference_context_not_paired_predecessor",
        "wall_seconds": 10.56,
        "peak_rss_mib": 1_840.3,
    },
    "settlement-agreement": {
        "label": "M0_reference_context_not_paired_predecessor",
        "wall_seconds": 6.48,
        "peak_rss_mib": 1_410.7,
    },
}
EXTRACTION_CEILINGS_SECONDS = {
    "component-datasheet": 0.250,
    "settlement-agreement": 0.150,
}
PAIRED_ABSOLUTE_CEILINGS_SECONDS = {
    "component-datasheet": 0.528,
    "settlement-agreement": 0.324,
}
PROJECTION_CEILING_SECONDS = 0.050
BOUNDARY_CEILING_SECONDS = 0.250
PEAK_ALLOCATION_CEILING_BYTES = 64 * 1024 * 1024
PEAK_RSS_DELTA_CEILING_BYTES = 64 * 1024 * 1024
HOSTED_USAGE = {
    "hosted_requests": 0,
    "hosted_tokens": 0,
    "hosted_cost_usd": 0,
}
TIMING_PATHS_REMOVED = (
    "processing.duration_ms",
    "processing.form_semantics.extraction_ms",
    "processing.form_semantics.projection_ms",
    "processing.form_semantics.total_ms",
    "processing.outline_structure.extraction_ms",
    "processing.outline_structure.projection_ms",
    "processing.outline_structure.total_ms",
)
EXPECTED_OUTLINE_SUMMARIES = {
    case: {
        "group_count": counts["group_count"],
        "node_count": counts["node_count"],
        "relationship_count": counts["total_relationship_count"],
    }
    for case, counts in REVIEWED_COUNTS.items()
}
EXPECTED_FORM_SUMMARIES = {
    "component-datasheet": {
        "anchor_count": 3,
        "group_count": 3,
        "field_count": 0,
        "label_count": 16,
        "value_region_count": 16,
        "control_count": 0,
        "key_value_pair_count": 16,
    },
    "settlement-agreement": {
        "anchor_count": 0,
        "group_count": 0,
        "field_count": 0,
        "label_count": 0,
        "value_region_count": 0,
        "control_count": 0,
        "key_value_pair_count": 0,
    },
}

FINAL_CODE_PATHS = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "app/config.py",
    "app/models.py",
    "app/services/form_semantics.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/outline_structure.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/lib/canonical-presentation.ts",
    "frontend/lib/normalize-document-json.ts",
    "frontend/lib/outline-structure.ts",
    "frontend/lib/serialize-output.ts",
    "frontend/lib/types.ts",
    "frontend/package-lock.json",
    "frontend/tests/p03-us07-outline-structure.test.mts",
    "tests/benchmarks/outline_structure_metrics.py",
    "tests/contract/test_p03_us07_outline_structure_contract.py",
    "tests/fixtures/phase_03/outline_structure/__init__.py",
    "tests/fixtures/phase_03/outline_structure/contract.py",
    "tests/fixtures/phase_03/outline_structure/oracle.py",
    "tests/fixtures/phase_03/outline_structure/synthetic.py",
    "tests/performance/test_p03_us07_outline_performance.py",
    "tests/regression/phase_03/test_p03_us07_real_outlines.py",
    "tests/stories/phase_03/test_p03_us07_outline_structure.py",
    "tracker/phase-03-layout/decisions/P03-outline-structure-policy.md",
)
DEPENDENCY_MANIFEST_PATHS = (
    "pyproject.toml",
    "uv.lock",
    "frontend/package-lock.json",
)
LOCAL_PACKAGE_DISTRIBUTIONS = (
    "docling",
    "docling-core",
    "pdfminer.six",
    "pdfplumber",
    "pydantic",
    "pypdfium2",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _artifact_semantic_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(value))
    detached.pop("generated_at", None)
    detached.pop("semantic_sha256", None)
    return detached


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _file_identity(workspace: Path, relative: str | Path) -> dict[str, Any]:
    relative_path = Path(relative)
    path = workspace / relative_path
    if not path.is_file():
        raise ValueError(f"metrics custody input is missing: {relative_path}")
    return {
        "path": str(relative_path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return deepcopy(dict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        result = model_dump(mode="json")
        if isinstance(result, dict):
            return result
    if is_dataclass(value):
        result = asdict(value)
        if isinstance(result, dict):
            return result
    raise TypeError(f"unsupported metrics payload type: {type(value).__name__}")


def _inclusive_p95(samples: Sequence[float]) -> float:
    if not samples:
        raise ValueError("p95 requires at least one sample")
    ordered = sorted(float(sample) for sample in samples)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=True,
        layout_outline_structure_enabled=enabled,
    )


def _settings_delta() -> dict[str, Any]:
    disabled = asdict(_settings(False))
    enabled = asdict(_settings(True))
    changed = sorted(key for key in disabled if disabled[key] != enabled[key])
    predecessor_fields = (
        "layout_table_captions_enabled",
        "layout_visual_relationships_enabled",
        "layout_source_notes_enabled",
        "layout_relationship_order_enabled",
        "layout_text_run_semantics_enabled",
        "layout_forms_enabled",
    )
    return {
        "changed_fields": changed,
        "flag_off": {key: disabled[key] for key in changed},
        "flag_on": {key: enabled[key] for key in changed},
        "accepted_predecessor_flags_enabled": all(
            getattr(_settings(False), field) for field in predecessor_fields
        ),
    }


def _observed_pdf_page_count(source_bytes: bytes) -> int:
    import pdfplumber

    with pdfplumber.open(BytesIO(source_bytes)) as pdf:
        return len(pdf.pages)


def _source_identity(case: str) -> Mapping[str, Any]:
    if case == "finance-10k":
        return FINANCE_IDENTITY
    return SOURCE_IDENTITIES[case]


def _source_custody(
    workspace: Path = WORKSPACE,
    cases: Sequence[str] = PAIRED_CASES,
) -> dict[str, Any]:
    custody: dict[str, Any] = {}
    for case in cases:
        expected = dict(_source_identity(case))
        source = workspace / str(expected["path"])
        source_bytes = source.read_bytes()
        observed = {
            "path": expected["path"],
            "size_bytes": len(source_bytes),
            "sha256": _sha256_bytes(source_bytes),
            "page_count": _observed_pdf_page_count(source_bytes),
        }
        identity_fields = ("path", "size_bytes", "sha256", "page_count")
        custody[case] = {
            "expected": expected,
            "observed": observed,
            "exact_match": all(
                observed[field] == expected[field] for field in identity_fields
            ),
        }
    return custody


def _verified_source_bytes(workspace: Path, case: str) -> bytes:
    expected = _source_identity(case)
    source = (workspace / str(expected["path"])).read_bytes()
    if (
        len(source) != expected["size_bytes"]
        or _sha256_bytes(source) != expected["sha256"]
    ):
        raise ValueError(f"immutable source identity mismatch: {case}")
    return source


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove exactly the seven accepted run-dependent timing fields."""

    detached = json.loads(_canonical_json(payload))
    processing = detached.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
        for summary_name in ("form_semantics", "outline_structure"):
            summary = processing.get(summary_name)
            if isinstance(summary, dict):
                for key in ("extraction_ms", "projection_ms", "total_ms"):
                    summary.pop(key, None)
    return detached


def _report_semantic_payload(report: Any) -> dict[str, Any]:
    stable = _payload(report)
    stable.pop("extraction_ms", None)
    return stable


def _report_size_bytes(report: Any) -> int:
    return len(_canonical_json(_payload(report)).encode("utf-8"))


def _profile_timing(
    operation: Callable[[], Any],
    *,
    warmup_count: int = 2,
    sample_count: int = 20,
    after_sample: Callable[[Any], None] | None = None,
) -> list[float]:
    if tracemalloc.is_tracing():
        raise RuntimeError("timing profile requires tracemalloc to be disabled")
    for _ in range(warmup_count):
        operation()
    samples: list[float] = []
    for _ in range(sample_count):
        gc.collect()
        if tracemalloc.is_tracing():
            raise RuntimeError("timing profile requires tracemalloc to remain disabled")
        started_ns = time.perf_counter_ns()
        result = operation()
        elapsed_ns = time.perf_counter_ns() - started_ns
        if tracemalloc.is_tracing():
            raise RuntimeError("timed operation enabled tracemalloc")
        samples.append(elapsed_ns / 1_000_000_000)
        if after_sample is not None:
            after_sample(result)
        del result
    return samples


def _profile_allocations(
    operation: Callable[[], Any],
    *,
    warmup_count: int = 1,
    sample_count: int = 5,
) -> tuple[list[int], Any]:
    for _ in range(warmup_count):
        operation()
    peaks: list[int] = []
    last_result: Any = None
    for sample_index in range(sample_count):
        gc.collect()
        if tracemalloc.is_tracing():
            raise RuntimeError("allocation profile requires a fresh tracer")
        tracemalloc.start()
        try:
            result = operation()
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        peaks.append(peak)
        if sample_index == sample_count - 1:
            last_result = result
        else:
            del result
    return peaks, last_result


def _timing_summary(
    samples: Sequence[float],
    *,
    ceiling_seconds: float,
) -> dict[str, Any]:
    p95_seconds = _inclusive_p95(samples)
    return {
        "warmup_count": 2,
        "sample_count": 20,
        "quantile_method": "empirical_p95_inclusive_nearest_rank",
        "quantile_formula": "sorted(samples)[ceil(0.95 * n) - 1]",
        "clock": "time.perf_counter_ns",
        "timing_tracemalloc_enabled": False,
        "timing_tracemalloc_state_verified": True,
        "timing_results_retained": False,
        "gc_collection_outside_timed_interval": True,
        "samples_seconds": [round(sample, 9) for sample in samples],
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(p95_seconds, 9),
        "min_seconds": round(min(samples), 9),
        "max_seconds": round(max(samples), 9),
        "p95_ceiling_seconds": ceiling_seconds,
        "within_p95_ceiling": p95_seconds <= ceiling_seconds,
    }


def _allocation_summary(peaks: Sequence[int]) -> dict[str, Any]:
    maximum = max(peaks)
    return {
        "allocation_measured_in_separate_call": True,
        "allocation_warmup_count": 1,
        "allocation_sample_count": 5,
        "tracemalloc_reset_between_samples": True,
        "peak_allocated_samples_bytes": list(peaks),
        "peak_allocated_bytes": maximum,
        "peak_allocation_ceiling_bytes": PEAK_ALLOCATION_CEILING_BYTES,
        "within_peak_allocation_ceiling": (maximum <= PEAK_ALLOCATION_CEILING_BYTES),
    }


def generate_extraction_metrics(
    case: str,
    *,
    source_bytes: bytes | None = None,
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported outline performance case: {case}")
    source = source_bytes or _verified_source_bytes(WORKSPACE, case)

    def extract() -> Any:
        return outlines.extract_outline_evidence(source, max_pages=100)

    semantic_digests: set[str] = set()

    def retain_digest(report: Any) -> None:
        semantic_digests.add(
            _sha256_bytes(
                _canonical_json(_report_semantic_payload(report)).encode("utf-8")
            )
        )

    samples = _profile_timing(extract, after_sample=retain_digest)
    peaks, report = _profile_allocations(extract)
    report_payload = _payload(report)
    validate_source_report(report_payload)
    expected = deepcopy(SOURCE_REPORTS[case])
    expected.pop("extraction_ms", None)
    timing = _timing_summary(
        samples,
        ceiling_seconds=EXTRACTION_CEILINGS_SECONDS[case],
    )
    allocation = _allocation_summary(peaks)
    report_size = _report_size_bytes(report)
    return {
        "case": case,
        "profile": "isolated_native_outline_extraction",
        **timing,
        **allocation,
        "report_size_bytes": report_size,
        "report_size_ceiling_bytes": int(SYNTHETIC_THRESHOLDS["maximum_report_bytes"]),
        "within_report_size_ceiling": report_size
        <= int(SYNTHETIC_THRESHOLDS["maximum_report_bytes"]),
        "semantic_deterministic": len(semantic_digests) == 1,
        "source_sha256_exact": (
            report_payload.get("source_sha256") == SOURCE_IDENTITIES[case]["sha256"]
        ),
        "source_report_exact": _report_semantic_payload(report) == expected,
        "reviewed_counts": deepcopy(report_payload.get("counts")),
        **HOSTED_USAGE,
    }


def _projection_payloads(
    workspace: Path,
    case: str,
) -> tuple[dict[str, Any], Any]:
    source = _verified_source_bytes(workspace, case)
    result = parse_document(source, f"{case}.pdf", _settings(False))
    predecessor = build_document_ir(result.model_dump(mode="json", exclude_none=True))
    evidence = outlines.extract_outline_evidence(source, max_pages=100)
    return predecessor.model_dump(mode="json"), evidence


_PROJECTION_CACHE: dict[tuple[str, str], tuple[dict[str, Any], Any]] = {}


def _projection_inputs(
    case: str,
    *,
    workspace: Path = WORKSPACE,
) -> tuple[DocumentIR, Any]:
    cache_key = (str(workspace.resolve()), case)
    if cache_key not in _PROJECTION_CACHE:
        _PROJECTION_CACHE[cache_key] = _projection_payloads(workspace, case)
    predecessor_payload, evidence = _PROJECTION_CACHE[cache_key]
    return (
        DocumentIR.model_validate(deepcopy(predecessor_payload)),
        deepcopy(evidence),
    )


def _outline_ir_summary(ir: DocumentIR) -> dict[str, int]:
    group_count = sum(element.outline_group is not None for element in ir.elements)
    node_count = sum(element.outline_item is not None for element in ir.elements)
    relationship_count = sum(
        relationship.metadata.get("outline_policy") == POLICY_ID
        for relationship in ir.relationships
    )
    return {
        "group_count": group_count,
        "node_count": node_count,
        "relationship_count": relationship_count,
    }


def _capture_projection_comparisons(
    predecessor: DocumentIR,
    evidence: Any,
) -> tuple[dict[int, int], DocumentIR]:
    """Run one untimed projection while observing the production ledger."""

    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        evidence,
        metrics=projection_metrics,
    )
    comparisons = projection_metrics.get("comparisons_by_page")
    if not isinstance(comparisons, Mapping):
        raise TypeError("outline comparison ledger is unavailable")
    return (
        {int(key): int(value) for key, value in comparisons.items()},
        projected,
    )


def generate_projection_metrics(
    case: str,
    *,
    workspace: Path = WORKSPACE,
    predecessor: DocumentIR | None = None,
    evidence: Any | None = None,
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported outline performance case: {case}")
    if predecessor is None or evidence is None:
        predecessor, evidence = _projection_inputs(case, workspace=workspace)
    predecessor_payload = predecessor.model_dump(mode="json")

    def project() -> DocumentIR:
        return outlines.project_outline_structure(predecessor, evidence)

    semantic_digests: set[str] = set()

    def retain_digest(result: DocumentIR) -> None:
        semantic_digests.add(
            _sha256_bytes(
                _canonical_json(result.model_dump(mode="json")).encode("utf-8")
            )
        )

    samples = _profile_timing(project, after_sample=retain_digest)
    peaks, traced_projection = _profile_allocations(project)
    if not isinstance(traced_projection, DocumentIR):
        raise TypeError("outline allocation profile produced no IR")
    replayed = outlines.project_outline_structure(traced_projection, evidence)
    comparisons_by_page, instrumented_projection = _capture_projection_comparisons(
        predecessor, evidence
    )
    timing = _timing_summary(
        samples,
        ceiling_seconds=PROJECTION_CEILING_SECONDS,
    )
    allocation = _allocation_summary(peaks)
    maximum_comparisons = int(SYNTHETIC_THRESHOLDS["maximum_comparisons_per_page"])
    return {
        "case": case,
        "profile": "isolated_outline_projection",
        **timing,
        **allocation,
        "projected_ir_size_bytes": len(
            traced_projection.model_dump_json().encode("utf-8")
        ),
        "semantic_deterministic": len(semantic_digests) == 1,
        "predecessor_unmodified": (
            predecessor.model_dump(mode="json") == predecessor_payload
        ),
        "repeated_projection_idempotent": (
            replayed.model_dump(mode="json")
            == traced_projection.model_dump(mode="json")
        ),
        "comparison_instrumentation_separate_from_timing": True,
        "comparisons_by_page": comparisons_by_page,
        "maximum_comparisons_on_page": max(comparisons_by_page.values(), default=0),
        "comparison_ceiling_per_page": maximum_comparisons,
        "within_comparison_ceiling": all(
            count <= maximum_comparisons for count in comparisons_by_page.values()
        ),
        "instrumented_projection_semantically_equal": (
            instrumented_projection.model_dump(mode="json")
            == traced_projection.model_dump(mode="json")
        ),
        "outline_summary": _outline_ir_summary(traced_projection),
        "outline_summary_exact": _outline_ir_summary(traced_projection)
        == EXPECTED_OUTLINE_SUMMARIES[case],
        **HOSTED_USAGE,
    }


def _rss_bytes_from_maxrss(value: int, *, platform_name: str) -> int:
    return value if platform_name == "darwin" else value * 1_024


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return _rss_bytes_from_maxrss(value, platform_name=sys.platform)


def _paired_states(pair_index: int) -> tuple[bool, bool]:
    return (False, True) if pair_index % 2 == 0 else (True, False)


def _iter_public_items(payload: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        items = page.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, Mapping):
                yield item


def _public_outline_summary(payload: Mapping[str, Any]) -> dict[str, int]:
    anchors = [
        item
        for item in _iter_public_items(payload)
        if item.get("layout_outline_structure_projected") is True
        and item.get("outline_policy") == POLICY_ID
    ]
    relationship_ids = {
        str(relationship.get("id"))
        for anchor in anchors
        for relationship in anchor.get("relationships", ())
        if isinstance(relationship, Mapping)
        and relationship.get("outline_policy") == POLICY_ID
    }
    return {
        "group_count": len(anchors),
        "node_count": sum(len(anchor.get("outline_items", ())) for anchor in anchors),
        "continuation_count": sum(
            len(anchor.get("outline_continuations", ())) for anchor in anchors
        ),
        "relationship_count": len(relationship_ids),
    }


def _outline_semantic_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    anchors = []
    for page in payload.get("pages", []):
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items", []):
            if not isinstance(item, Mapping) or (
                item.get("layout_outline_structure_projected") is not True
            ):
                continue
            anchors.append(
                {
                    "page_index": page.get("page_index"),
                    "anchor_id": item.get("id"),
                    "outline_policy": item.get("outline_policy"),
                    "outline_group": item.get("outline_group"),
                    "outline_items": item.get("outline_items"),
                    "outline_continuations": item.get("outline_continuations"),
                    "relationships": [
                        relationship
                        for relationship in item.get("relationships", [])
                        if isinstance(relationship, Mapping)
                        and relationship.get("outline_policy") == POLICY_ID
                    ],
                }
            )
    processing = payload.get("processing")
    summary = (
        processing.get("outline_structure") if isinstance(processing, Mapping) else None
    )
    if isinstance(summary, Mapping):
        summary = deepcopy(dict(summary))
        for key in ("extraction_ms", "projection_ms", "total_ms"):
            summary.pop(key, None)
    return {"anchors": anchors, "processing": summary}


def _worker_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    source = _verified_source_bytes(workspace, case)
    extractor_calls = 0
    original_extractor = outlines.extract_outline_evidence

    def counted_extractor(*args: Any, **kwargs: Any) -> Any:
        nonlocal extractor_calls
        extractor_calls += 1
        return original_extractor(*args, **kwargs)

    outlines.extract_outline_evidence = counted_extractor
    started_ns = time.perf_counter_ns()
    try:
        result = parse_document(source, f"{case}.pdf", _settings(enabled))
    finally:
        elapsed_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000
        outlines.extract_outline_evidence = original_extractor
    payload = result.model_dump(mode="json", exclude_none=True)
    semantic_json = _canonical_json(_semantic_payload(payload)).encode("utf-8")
    outline_semantic = _canonical_json(_outline_semantic_view(payload)).encode("utf-8")
    raw_json = _canonical_json(payload).encode("utf-8")
    markdown = to_markdown(payload).encode("utf-8")
    outline_summary = _public_outline_summary(payload)
    processing = payload.get("processing")
    outline_processing = (
        processing.get("outline_structure") if isinstance(processing, Mapping) else None
    )
    processing_has_outline_summary = isinstance(outline_processing, Mapping)
    if processing_has_outline_summary:
        validate_processing_summary(outline_processing)
    form_summary = _public_form_summary(payload)
    return {
        "case": case,
        "enabled": enabled,
        "input_identity": deepcopy(dict(_source_identity(case))),
        "wall_seconds": round(elapsed_seconds, 6),
        "peak_rss_bytes": _rss_bytes(),
        "rss_source": "resource.getrusage(RUSAGE_SELF).ru_maxrss",
        "rss_normalization": "bytes_on_darwin_else_kibibytes_times_1024",
        "extractor_call_count": extractor_calls,
        "semantic_json_sha256": _sha256_bytes(semantic_json),
        "semantic_json_size_bytes": len(semantic_json),
        "outline_semantic_sha256": _sha256_bytes(outline_semantic),
        "outline_semantic_size_bytes": len(outline_semantic),
        "raw_json_sha256": _sha256_bytes(raw_json),
        "raw_json_size_bytes": len(raw_json),
        "markdown_sha256": _sha256_bytes(markdown),
        "markdown_size_bytes": len(markdown),
        "outline_summary": outline_summary,
        "processing_outline_summary": deepcopy(outline_processing),
        "processing_has_outline_summary": processing_has_outline_summary,
        "form_summary": form_summary,
        "flag_off_projection_absent": (
            not enabled
            and extractor_calls == 0
            and not processing_has_outline_summary
            and outline_summary
            == {
                "group_count": 0,
                "node_count": 0,
                "continuation_count": 0,
                "relationship_count": 0,
            }
        ),
        **HOSTED_USAGE,
    }


def _worker_command(
    workspace: Path,
    case: str,
    enabled: bool,
    output: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tests.benchmarks.outline_structure_metrics",
        "--workspace",
        str(workspace),
        "--worker-case",
        case,
        "--worker-enabled",
        "true" if enabled else "false",
        "--output",
        str(output),
    ]


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fresh_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"p03-us07-{case}-") as directory:
        output = Path(directory) / "snapshot.json"
        completed = subprocess.run(
            _worker_command(workspace, case, enabled, output),
            cwd=workspace,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=360,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "fresh US07 metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4_000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def _paired_performance_summary(
    case: str,
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported paired outline case: {case}")
    if (
        len(off_samples) != PAIRED_REPEAT_COUNT
        or len(on_samples) != PAIRED_REPEAT_COUNT
    ):
        raise ValueError("paired outline performance requires exactly 5 pairs")
    signed = [
        float(enabled["wall_seconds"]) - float(disabled["wall_seconds"])
        for disabled, enabled in zip(off_samples, on_samples, strict=True)
    ]
    clipped = [max(delta, 0.0) for delta in signed]
    disabled_wall = [float(sample["wall_seconds"]) for sample in off_samples]
    enabled_wall = [float(sample["wall_seconds"]) for sample in on_samples]
    baseline_p95 = _inclusive_p95(disabled_wall)
    overhead_p95 = _inclusive_p95(clipped)
    five_percent_ceiling = 0.05 * baseline_p95
    absolute_ceiling = PAIRED_ABSOLUTE_CEILINGS_SECONDS[case]
    effective_ceiling = min(five_percent_ceiling, absolute_ceiling)
    disabled_rss = [int(sample["peak_rss_bytes"]) for sample in off_samples]
    enabled_rss = [int(sample["peak_rss_bytes"]) for sample in on_samples]
    maximum_rss_delta = max(enabled_rss) - max(disabled_rss)
    return {
        "case": case,
        "pair_count": len(signed),
        "process_model": "fresh_process_per_flag_state",
        "execution_order_alternated": True,
        "cache_state": "operating-system caches were not explicitly flushed",
        "quantile_method": "empirical_p95_inclusive_nearest_rank",
        "quantile_formula": "sorted(samples)[ceil(0.95 * n) - 1]",
        "gate_value": "p95_of_clipped_nonnegative_paired_overhead",
        "flag_off_wall_seconds": disabled_wall,
        "flag_on_wall_seconds": enabled_wall,
        "paired_signed_wall_seconds_deltas": [round(delta, 6) for delta in signed],
        "paired_nonnegative_overhead_seconds": [round(delta, 6) for delta in clipped],
        "p50_signed_delta_seconds": round(statistics.median(signed), 6),
        "p95_signed_delta_seconds": round(_inclusive_p95(signed), 6),
        "p50_nonnegative_overhead_seconds": round(statistics.median(clipped), 6),
        "p95_nonnegative_overhead_seconds": round(overhead_p95, 6),
        "current_paired_predecessor_p95_seconds": round(baseline_p95, 6),
        "five_percent_ceiling_seconds": round(five_percent_ceiling, 6),
        "absolute_ceiling_seconds": absolute_ceiling,
        "effective_ceiling_seconds": round(effective_ceiling, 6),
        "within_five_percent_ceiling": overhead_p95 <= five_percent_ceiling,
        "within_absolute_ceiling": overhead_p95 <= absolute_ceiling,
        "within_both_ceilings": overhead_p95 <= effective_ceiling,
        "flag_off_peak_rss_bytes": disabled_rss,
        "flag_on_peak_rss_bytes": enabled_rss,
        "flag_off_maximum_peak_rss_bytes": max(disabled_rss),
        "flag_on_maximum_peak_rss_bytes": max(enabled_rss),
        "maximum_peak_rss_delta_bytes": maximum_rss_delta,
        "peak_rss_delta_ceiling_bytes": PEAK_RSS_DELTA_CEILING_BYTES,
        "within_peak_rss_delta_ceiling": (
            maximum_rss_delta <= PEAK_RSS_DELTA_CEILING_BYTES
        ),
        "m0_reference": deepcopy(M0_REFERENCES[case]),
        **HOSTED_USAGE,
    }


def generate_paired_parser_metrics(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = PAIRED_REPEAT_COUNT,
) -> dict[str, Any]:
    if repeats != PAIRED_REPEAT_COUNT:
        raise ValueError("paired outline metrics require exactly 5 repeats")
    cases: dict[str, Any] = {}
    for case in PAIRED_CASES:
        off_samples: list[dict[str, Any]] = []
        on_samples: list[dict[str, Any]] = []
        execution_order: list[list[str]] = []
        for pair_index in range(repeats):
            states = _paired_states(pair_index)
            execution_order.append(["on" if state else "off" for state in states])
            results: dict[bool, dict[str, Any]] = {}
            for state in states:
                results[state] = _fresh_snapshot(workspace, case, state)
            off_samples.append(results[False])
            on_samples.append(results[True])
        expected = {
            **EXPECTED_OUTLINE_SUMMARIES[case],
            "continuation_count": 1 if case == "settlement-agreement" else 0,
        }
        cases[case] = {
            "execution_order": execution_order,
            "flag_off_samples": off_samples,
            "flag_on_samples": on_samples,
            "all_flag_off_extractor_counts_zero": all(
                sample["extractor_call_count"] == 0 for sample in off_samples
            ),
            "all_flag_on_extractor_counts_one": all(
                sample["extractor_call_count"] == 1 for sample in on_samples
            ),
            "all_flag_off_projection_absent": all(
                sample["flag_off_projection_absent"] for sample in off_samples
            ),
            "all_flag_on_processing_summaries_present": all(
                sample["processing_has_outline_summary"] for sample in on_samples
            ),
            "all_flag_on_outline_summaries_exact": all(
                sample["outline_summary"] == expected for sample in on_samples
            ),
            "flag_off_semantic_deterministic": len(
                {sample["semantic_json_sha256"] for sample in off_samples}
            )
            == 1,
            "flag_on_first_three_semantic_deterministic": len(
                {sample["semantic_json_sha256"] for sample in on_samples[:3]}
            )
            == 1,
            "flag_on_all_semantic_deterministic": len(
                {sample["semantic_json_sha256"] for sample in on_samples}
            )
            == 1,
            "flag_on_outline_semantic_deterministic": len(
                {sample["outline_semantic_sha256"] for sample in on_samples}
            )
            == 1,
            "all_samples_forms_predecessor_present": all(
                sample["form_summary"] == EXPECTED_FORM_SUMMARIES[case]
                for sample in (*off_samples, *on_samples)
            ),
            "all_samples_zero_hosted_usage": all(
                all(sample.get(key) == value for key, value in HOSTED_USAGE.items())
                for sample in (*off_samples, *on_samples)
            ),
            "timing_paths_removed": list(TIMING_PATHS_REMOVED),
            "paired_performance": _paired_performance_summary(
                case, off_samples, on_samples
            ),
        }
    return {
        "pair_count_per_case": repeats,
        "performance_cases": list(PAIRED_CASES),
        "execution_order_policy": "off/on alternates by pair index",
        "cases": cases,
        **HOSTED_USAGE,
    }


_PRODUCTION_LIMIT_ATTRIBUTES = {
    "maximum_source_characters_per_page": "MAX_SOURCE_CHARACTERS_PER_PAGE",
    "maximum_source_characters_per_document": "MAX_SOURCE_CHARACTERS_PER_DOCUMENT",
    "maximum_source_words_per_page": "MAX_SOURCE_WORDS_PER_PAGE",
    "maximum_source_words_per_document": "MAX_SOURCE_WORDS_PER_DOCUMENT",
    "maximum_marker_candidates_per_page": "MAX_MARKER_CANDIDATES_PER_PAGE",
    "maximum_marker_candidates_per_document": "MAX_MARKER_CANDIDATES_PER_DOCUMENT",
    "maximum_marker_bytes": "MAX_MARKER_BYTES",
    "maximum_item_text_bytes": "MAX_ITEM_TEXT_BYTES",
    "maximum_depth": "MAX_DEPTH",
    "maximum_nodes_per_group": "MAX_NODES_PER_GROUP",
    "maximum_groups_per_page": "MAX_GROUPS_PER_PAGE",
    "maximum_groups_per_document": "MAX_GROUPS_PER_DOCUMENT",
    "maximum_nodes_per_page": "MAX_NODES_PER_PAGE",
    "maximum_nodes_per_document": "MAX_NODES_PER_DOCUMENT",
    "maximum_interstitials_per_group": "MAX_INTERSTITIALS_PER_GROUP",
    "maximum_relationships_per_page": "MAX_RELATIONSHIPS_PER_PAGE",
    "maximum_relationships_per_document": "MAX_RELATIONSHIPS_PER_DOCUMENT",
    "maximum_comparisons_per_page": "MAX_COMPARISONS_PER_PAGE",
    "maximum_public_group_bytes": "MAX_PUBLIC_GROUP_BYTES",
    "maximum_report_bytes": "MAX_REPORT_BYTES",
    "maximum_concerns_per_page": "MAX_CONCERNS_PER_PAGE",
    "maximum_concerns_per_document": "MAX_CONCERNS_PER_DOCUMENT",
}
_PRODUCTION_DEADLINE_ATTRIBUTES = {
    "source_extraction_deadline": "SOURCE_EXTRACTION_DEADLINE_SECONDS",
    "projection_page_deadline": "PROJECTION_PAGE_DEADLINE_SECONDS",
    "projection_document_deadline": "PROJECTION_DOCUMENT_DEADLINE_SECONDS",
}


def generate_resource_boundary_metrics() -> dict[str, Any]:
    boundaries: dict[str, Any] = {}
    for counter, attribute in _PRODUCTION_LIMIT_ATTRIBUTES.items():
        exact_started_ns = time.perf_counter_ns()
        exact = build_resource_boundary_witness(counter)
        exact_observed = exact.measure()
        exact_accepted = exact.execute()
        exact_elapsed_seconds = (
            time.perf_counter_ns() - exact_started_ns
        ) / 1_000_000_000
        overflow_started_ns = time.perf_counter_ns()
        maximum_plus_one = build_resource_boundary_witness(
            counter, maximum_plus_one=True
        )
        maximum_plus_one_observed = maximum_plus_one.measure()
        maximum_plus_one_refused = not maximum_plus_one.execute()
        maximum_plus_one_elapsed_seconds = (
            time.perf_counter_ns() - overflow_started_ns
        ) / 1_000_000_000
        production_limit = getattr(outlines, attribute)
        boundaries[counter] = {
            "production_attribute": attribute,
            "production_limit": production_limit,
            "registry_limit": exact.limit,
            "unit": exact.unit,
            "scope": exact.scope,
            "exact_observed": exact_observed,
            "exact_accepted": exact_accepted,
            "exact_elapsed_seconds": round(exact_elapsed_seconds, 9),
            "maximum_plus_one_observed": maximum_plus_one_observed,
            "maximum_plus_one_refused": maximum_plus_one_refused,
            "maximum_plus_one_elapsed_seconds": round(
                maximum_plus_one_elapsed_seconds,
                9,
            ),
            "boundary_ceiling_seconds_each": BOUNDARY_CEILING_SECONDS,
            "within_boundary_ceiling": (
                exact_elapsed_seconds <= BOUNDARY_CEILING_SECONDS
                and maximum_plus_one_elapsed_seconds <= BOUNDARY_CEILING_SECONDS
            ),
            "production_limit_exact": production_limit == exact.limit,
            "binding": "production_constant_and_dedicated_validator_gate",
        }
    return {
        "boundary_count": len(boundaries),
        "boundaries": boundaries,
        "all_exact_accepted": all(
            value["exact_accepted"] for value in boundaries.values()
        ),
        "all_maximum_plus_one_refused": all(
            value["maximum_plus_one_refused"] for value in boundaries.values()
        ),
        "all_production_limits_exact": all(
            value["production_limit_exact"] for value in boundaries.values()
        ),
        "all_within_boundary_ceiling": all(
            value["within_boundary_ceiling"] for value in boundaries.values()
        ),
    }


def generate_deadline_metrics() -> dict[str, Any]:
    deadlines: dict[str, Any] = {}
    for name, attribute in _PRODUCTION_DEADLINE_ATTRIBUTES.items():
        exact = build_deadline_witness(name)
        maximum_plus_one = build_deadline_witness(name, maximum_plus_one=True)
        production_limit = getattr(outlines, attribute)
        deadlines[name] = {
            "production_attribute": attribute,
            "production_limit_seconds": production_limit,
            "registry_limit_seconds": exact.limit_seconds,
            "exact_elapsed_seconds": exact.elapsed_seconds,
            "exact_accepted": exact.execute(),
            "maximum_plus_one_elapsed_seconds": maximum_plus_one.elapsed_seconds,
            "maximum_plus_one_refused": not maximum_plus_one.execute(),
            "production_limit_exact": production_limit == exact.limit_seconds,
            "clock": "injected_monotonic_witness",
        }
    return {
        "deadline_count": len(deadlines),
        "deadlines": deadlines,
        "all_exact_accepted": all(
            value["exact_accepted"] for value in deadlines.values()
        ),
        "all_maximum_plus_one_refused": all(
            value["maximum_plus_one_refused"] for value in deadlines.values()
        ),
        "all_production_limits_exact": all(
            value["production_limit_exact"] for value in deadlines.values()
        ),
    }


def _target_control(case: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    observed = _public_outline_summary(payload)
    expected = {
        **EXPECTED_OUTLINE_SUMMARIES[case],
        "continuation_count": 1 if case == "settlement-agreement" else 0,
    }
    form_summary = _public_form_summary(payload)
    expected_form_summary = EXPECTED_FORM_SUMMARIES[case]
    return {
        "case": case,
        "role": "target",
        "expected": expected,
        "observed": observed,
        "outline_exact": observed == expected,
        "form_summary": form_summary,
        "expected_form_summary": deepcopy(expected_form_summary),
        "form_predecessor_exact": form_summary == expected_form_summary,
        "exact": (observed == expected and form_summary == expected_form_summary),
    }


def generate_control_matrix(
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    targets: dict[str, Any] = {}
    for case in PAIRED_CASES:
        source = _verified_source_bytes(workspace, case)
        payload = parse_document(source, f"{case}.pdf", _settings(True)).model_dump(
            mode="json", exclude_none=True
        )
        targets[case] = _target_control(case, payload)

    finance_source = _verified_source_bytes(workspace, "finance-10k")
    finance_payload = parse_document(
        finance_source, "finance-10k.pdf", _settings(True)
    ).model_dump(mode="json", exclude_none=True)
    finance_summary = _public_outline_summary(finance_payload)

    synthetic_self_check()
    verify_pdf_readers()
    return {
        "targets": targets,
        "finance_non_target": {
            "case": "finance-10k",
            "role": "non_target_regression",
            "observed": finance_summary,
            "zero_false_outlines": finance_summary
            == {
                "group_count": 0,
                "node_count": 0,
                "continuation_count": 0,
                "relationship_count": 0,
            },
        },
        "synthetic_registry": {
            "fixture_count": len(SYNTHETIC_FIXTURES),
            "capability_count": len(REQUIRED_SYNTHETIC_COVERAGE),
            "pdf_count": sum(fixture.kind == "pdf" for fixture in SYNTHETIC_FIXTURES),
            "self_check_passed": True,
            "reader_check_passed": True,
        },
        "all_targets_exact": all(value["exact"] for value in targets.values()),
        "all_real_controls_pass": all(value["exact"] for value in targets.values())
        and finance_summary
        == {
            "group_count": 0,
            "node_count": 0,
            "continuation_count": 0,
            "relationship_count": 0,
        },
        **HOSTED_USAGE,
    }


def generate_relationship_order_retention_metrics(
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    from tests.benchmarks.text_run_semantics_metrics import (
        generate_relationship_order_retention,
    )
    from tests.regression.phase_03.test_p03_us04_real_reading_order import (
        REVIEWED_CASES,
    )

    preparsed: dict[str, Mapping[str, Any]] = {}
    for case in REVIEWED_CASES:
        source_path = workspace / "benchmark-expertmodeldata" / f"{case}.pdf"
        preparsed[case] = parse_document(
            source_path.read_bytes(),
            source_path.name,
            _settings(True),
        ).model_dump(mode="json", exclude_none=True)
        gc.collect()
    return generate_relationship_order_retention(
        workspace,
        preparsed_payloads=preparsed,
    )


def _code_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    return {
        relative: _file_identity(workspace, relative) for relative in FINAL_CODE_PATHS
    }


def _dependency_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    executable_value = shutil.which(Settings().tesseract_cmd)
    if executable_value is None:
        raise RuntimeError("tesseract executable is unavailable")
    executable = Path(executable_value).resolve()
    completed = subprocess.run(
        [str(executable), "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("tesseract version query failed")
    node_value = shutil.which("node")
    node: dict[str, Any] | None = None
    if node_value is not None:
        node_path = Path(node_value).resolve()
        node_version = subprocess.run(
            [str(node_path), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        node = {
            "path": str(node_path),
            "version": node_version,
            "size_bytes": node_path.stat().st_size,
            "sha256": _sha256_file(node_path),
        }
    return {
        "python_packages": {
            package: importlib_metadata.version(package)
            for package in LOCAL_PACKAGE_DISTRIBUTIONS
        },
        "dependency_manifests": {
            relative: _file_identity(workspace, relative)
            for relative in DEPENDENCY_MANIFEST_PATHS
        },
        "local_tool_identity": {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "tesseract": {
                "path": str(executable),
                "version": completed.stdout.splitlines()[0].strip(),
                "size_bytes": executable.stat().st_size,
                "sha256": _sha256_file(executable),
            },
            "node": node,
        },
        "offline_environment": {
            key: os.environ.get(key)
            for key in (
                "HF_HUB_OFFLINE",
                "TOKENIZERS_PARALLELISM",
                "TRANSFORMERS_OFFLINE",
            )
        },
        **HOSTED_USAGE,
    }


def _predecessor_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    artifact = _file_identity(workspace, PREDECESSOR_ARTIFACT_RELATIVE_PATH)
    if (
        artifact["size_bytes"] != PREDECESSOR_ARTIFACT_SIZE_BYTES
        or artifact["sha256"] != PREDECESSOR_ARTIFACT_RAW_SHA256
    ):
        raise ValueError("sealed P03-US06 artifact raw identity changed")
    payload = json.loads(
        (workspace / PREDECESSOR_ARTIFACT_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    if payload.get("semantic_sha256") != PREDECESSOR_ARTIFACT_SEMANTIC_SHA256:
        raise ValueError("sealed P03-US06 artifact semantic identity changed")
    reviewed_values: dict[str, Any] = {}
    for case, expected in PREDECESSOR_IDENTITIES.items():
        observed = _file_identity(workspace, expected["path"])
        if observed["size_bytes"] != expected["size_bytes"] or (
            observed["sha256"] != expected["sha256"]
        ):
            raise ValueError(f"reviewed predecessor value evidence changed: {case}")
        reviewed_values[case] = {
            "role": "reviewed_value_custody_not_configured_snapshot",
            "expected": deepcopy(expected),
            "observed": observed,
            "exact_match": True,
        }
    return {
        "p03_us06_artifact": {
            **artifact,
            "raw_sha256": PREDECESSOR_ARTIFACT_RAW_SHA256,
            "semantic_sha256": PREDECESSOR_ARTIFACT_SEMANTIC_SHA256,
            "story": payload.get("story"),
            "status": payload.get("status"),
        },
        "reviewed_value_custody": reviewed_values,
        "configured_predecessor_definition": (
            "all P03-US01-US06 flags enabled with US07 disabled"
        ),
    }


def _m0_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    identity = _file_identity(workspace, M0_ARTIFACT_RELATIVE_PATH)
    if identity["size_bytes"] != M0_ARTIFACT_SIZE_BYTES or (
        identity["sha256"] != M0_ARTIFACT_RAW_SHA256
    ):
        raise ValueError("M0 baseline summary identity changed")
    return {
        **identity,
        "role": "historical_context_not_paired_predecessor",
        "cases": deepcopy(M0_REFERENCES),
    }


def _oracle_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    payload = oracle_payload()
    return {
        "oracle_file": _file_identity(
            workspace, "tests/fixtures/phase_03/outline_structure/oracle.py"
        ),
        "oracle_payload_sha256": oracle_sha256(),
        "source_identities_exact": payload["source_identities"] == SOURCE_IDENTITIES,
        "reviewed_counts": deepcopy(payload["reviewed_counts"]),
        "canonical_expectations_sha256": _sha256_bytes(
            _canonical_json(payload["canonical_expectations"]).encode("utf-8")
        ),
        "settlement_addendum": _file_identity(
            workspace,
            "tracker/phase-03-layout/evidence/P03-US07-settlement-marker-addendum.md",
        ),
        "frozen_phase_00_records": {
            "case_review": _file_identity(
                workspace,
                "tracker/benchmarks/llamaparse-15/cases/settlement-agreement.md",
            ),
            "comparison_report": _file_identity(
                workspace,
                "tracker/benchmarks/llamaparse-15/runs/"
                "baseline-20260728-current/settlement-agreement/"
                "comparison-report.md",
            ),
        },
    }


def _contract_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    return {
        "contract_file": _file_identity(
            workspace, "tests/fixtures/phase_03/outline_structure/contract.py"
        ),
        "policy_id": POLICY_ID,
    }


def _synthetic_fixture_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    synthetic_self_check()
    hashes = fixture_hashes()
    return {
        "generator_file": _file_identity(
            workspace, "tests/fixtures/phase_03/outline_structure/synthetic.py"
        ),
        "fixture_count": len(SYNTHETIC_FIXTURES),
        "required_capability_count": len(REQUIRED_SYNTHETIC_COVERAGE),
        "thresholds": dict(SYNTHETIC_THRESHOLDS),
        "fixture_hashes": hashes,
        "registry_sha256": registry_sha256(),
        "self_check_passed": True,
        "pdf_reader_verification_scope": (
            "retained test/control gate; omitted from timed profiles"
        ),
    }


def _output_size_summary(paired: Mapping[str, Any]) -> dict[str, Any]:
    selected_keys = (
        "semantic_json_sha256",
        "semantic_json_size_bytes",
        "outline_semantic_sha256",
        "outline_semantic_size_bytes",
        "raw_json_sha256",
        "raw_json_size_bytes",
        "markdown_sha256",
        "markdown_size_bytes",
    )
    return {
        case: {
            state: [
                {key: sample[key] for key in selected_keys}
                for sample in record[f"flag_{state}_samples"]
            ]
            for state in ("off", "on")
        }
        for case, record in paired["cases"].items()
    }


def _rollback_summary(preliminary: Mapping[str, Any]) -> dict[str, Any]:
    paired_cases = preliminary["paired_parser"]["cases"]
    projections = preliminary["isolated_projection"]
    return {
        "rollback_value": False,
        "only_us07_setting_toggled": preliminary["settings_delta"]["changed_fields"]
        == ["layout_outline_structure_enabled"],
        "all_flag_off_extractor_counts_zero": all(
            record["all_flag_off_extractor_counts_zero"]
            for record in paired_cases.values()
        ),
        "all_flag_off_projection_absent": all(
            record["all_flag_off_projection_absent"] for record in paired_cases.values()
        ),
        "all_repeated_projections_idempotent": all(
            record["repeated_projection_idempotent"] for record in projections.values()
        ),
        "configured_predecessor_flags_unchanged": preliminary["settings_delta"][
            "accepted_predecessor_flags_enabled"
        ],
    }


def _aggregate_summary(preliminary: Mapping[str, Any]) -> dict[str, Any]:
    extraction = preliminary["isolated_extraction"]
    projection = preliminary["isolated_projection"]
    paired_cases = preliminary["paired_parser"]["cases"]
    resources = preliminary["resource_boundaries"]
    deadlines = preliminary["deadline_boundaries"]
    order = preliminary["relationship_order_retention"]
    return {
        "input_custody_exact": all(
            record["exact_match"] for record in preliminary["input_custody"].values()
        ),
        "source_reports_exact": all(
            record["source_report_exact"] for record in extraction.values()
        ),
        "source_extraction_p95_within_case_ceilings": all(
            record["within_p95_ceiling"] for record in extraction.values()
        ),
        "source_extraction_peak_within_64mib": all(
            record["within_peak_allocation_ceiling"] for record in extraction.values()
        ),
        "source_reports_within_8mib": all(
            record["within_report_size_ceiling"] for record in extraction.values()
        ),
        "projection_p95_within_50ms": all(
            record["within_p95_ceiling"] for record in projection.values()
        ),
        "projection_peak_within_64mib": all(
            record["within_peak_allocation_ceiling"] for record in projection.values()
        ),
        "projection_comparisons_within_page_cap": all(
            record["within_comparison_ceiling"] for record in projection.values()
        ),
        "projection_summaries_exact": all(
            record["outline_summary_exact"] for record in projection.values()
        ),
        "resource_exact_boundaries_pass": resources["all_exact_accepted"],
        "resource_maximum_plus_one_refused": resources["all_maximum_plus_one_refused"],
        "resource_production_limits_exact": resources["all_production_limits_exact"],
        "resource_boundaries_within_250ms": resources["all_within_boundary_ceiling"],
        "deadline_exact_boundaries_pass": deadlines["all_exact_accepted"],
        "deadline_maximum_plus_one_refused": deadlines["all_maximum_plus_one_refused"],
        "deadline_production_limits_exact": deadlines["all_production_limits_exact"],
        "paired_parser_within_five_percent": all(
            record["paired_performance"]["within_five_percent_ceiling"]
            for record in paired_cases.values()
        ),
        "paired_parser_within_absolute_ceilings": all(
            record["paired_performance"]["within_absolute_ceiling"]
            for record in paired_cases.values()
        ),
        "paired_parser_within_both_ceilings": all(
            record["paired_performance"]["within_both_ceilings"]
            for record in paired_cases.values()
        ),
        "paired_rss_delta_within_64mib": all(
            record["paired_performance"]["within_peak_rss_delta_ceiling"]
            for record in paired_cases.values()
        ),
        "enabled_semantic_determinism": all(
            record["flag_on_first_three_semantic_deterministic"]
            and record["flag_on_all_semantic_deterministic"]
            and record["flag_on_outline_semantic_deterministic"]
            for record in paired_cases.values()
        ),
        "enabled_outline_summaries_exact": all(
            record["all_flag_on_outline_summaries_exact"]
            for record in paired_cases.values()
        ),
        "flag_off_extractor_count_zero": all(
            record["all_flag_off_extractor_counts_zero"]
            for record in paired_cases.values()
        ),
        "flag_on_extractor_count_one": all(
            record["all_flag_on_extractor_counts_one"]
            for record in paired_cases.values()
        ),
        "flag_on_processing_summaries_present": all(
            record["all_flag_on_processing_summaries_present"]
            for record in paired_cases.values()
        ),
        "forms_predecessor_summaries_exact": all(
            record["all_samples_forms_predecessor_present"]
            for record in paired_cases.values()
        ),
        "real_control_matrix_all_pass": preliminary["control_matrix"][
            "all_real_controls_pass"
        ],
        "relationship_order_retention_all_pass": order["all_pass"],
        "relationship_order_expected": order["total_expected"],
        "relationship_order_matched": order["total_matched"],
        **HOSTED_USAGE,
    }


def _build_final_artifact_envelope(
    preliminary: Mapping[str, Any],
    *,
    code_custody: Mapping[str, Any],
    dependency_custody: Mapping[str, Any],
    predecessor_custody: Mapping[str, Any],
    m0_custody: Mapping[str, Any],
    oracle_custody: Mapping[str, Any],
    contract_custody: Mapping[str, Any],
    synthetic_fixture_custody: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    paired = preliminary["paired_parser"]
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "record_kind": "p03_us07_outline_metrics",
        "story": "P03-US07",
        "status": "final_measurement_candidate",
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "retained_path": str(DEFAULT_ARTIFACT_RELATIVE_PATH),
        "measurement": {
            "performance_cases": list(PAIRED_CASES),
            "pair_count_per_case": PAIRED_REPEAT_COUNT,
            "worker_process_count": PAIRED_REPEAT_COUNT * len(PAIRED_CASES) * 2,
            "execution_order": "alternating off/on by pair index",
            "quantile_method": "empirical_p95_inclusive_nearest_rank",
            "quantile_formula": "sorted(samples)[ceil(0.95 * n) - 1]",
            "cache_disclaimer": (
                "operating-system caches were not explicitly flushed; "
                "no cold-cache claim is made"
            ),
            "timing_and_traced_allocation_measured_separately": True,
            "timing_outputs_released_between_samples": True,
            "pre_post_code_custody_match": True,
            "pre_post_source_custody_match": True,
            **HOSTED_USAGE,
        },
        "policy": {
            "policy_id": POLICY_ID,
            "feature_flag": "PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED",
            "default_enabled": False,
            "rollback_value": False,
            "source_extraction_p95_ceiling_seconds": deepcopy(
                EXTRACTION_CEILINGS_SECONDS
            ),
            "projection_p95_ceiling_seconds": PROJECTION_CEILING_SECONDS,
            "isolated_peak_allocation_ceiling_bytes": (PEAK_ALLOCATION_CEILING_BYTES),
            "maximum_boundary_ceiling_seconds": BOUNDARY_CEILING_SECONDS,
            "paired_absolute_ceiling_seconds": deepcopy(
                PAIRED_ABSOLUTE_CEILINGS_SECONDS
            ),
            "paired_percent_ceiling": 5.0,
            "peak_rss_delta_ceiling_bytes": PEAK_RSS_DELTA_CEILING_BYTES,
            "semantic_timing_paths_removed": list(TIMING_PATHS_REMOVED),
            "resource_limits": dict(SYNTHETIC_THRESHOLDS),
            **HOSTED_USAGE,
        },
        "settings_delta": deepcopy(preliminary["settings_delta"]),
        "m0_reference": deepcopy(m0_custody),
        "input_custody": deepcopy(preliminary["input_custody"]),
        "predecessor_custody": deepcopy(predecessor_custody),
        "oracle_custody": deepcopy(oracle_custody),
        "contract_custody": deepcopy(contract_custody),
        "synthetic_fixture_custody": deepcopy(synthetic_fixture_custody),
        "code_sha256": deepcopy(code_custody),
        "dependency_custody": deepcopy(dependency_custody),
        "source_extraction": deepcopy(preliminary["isolated_extraction"]),
        "outline_projection": deepcopy(preliminary["isolated_projection"]),
        "resource_boundaries": deepcopy(preliminary["resource_boundaries"]),
        "deadline_boundaries": deepcopy(preliminary["deadline_boundaries"]),
        "paired_parser": deepcopy(paired),
        "control_matrix": deepcopy(preliminary["control_matrix"]),
        "relationship_order_retention": deepcopy(
            preliminary["relationship_order_retention"]
        ),
        "output_sizes": _output_size_summary(paired),
        "rollback": _rollback_summary(preliminary),
        "aggregate": _aggregate_summary(preliminary),
        **HOSTED_USAGE,
    }
    artifact["semantic_sha256"] = _sha256_bytes(
        _canonical_json(_artifact_semantic_payload(artifact)).encode("utf-8")
    )
    return artifact


def generate_preliminary_metrics(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = PAIRED_REPEAT_COUNT,
) -> dict[str, Any]:
    if repeats != PAIRED_REPEAT_COUNT:
        raise ValueError("preliminary outline metrics require exactly 5 repeats")
    return {
        "story": "P03-US07",
        "status": "preliminary_not_retained",
        "input_custody": _source_custody(workspace),
        "settings_delta": _settings_delta(),
        "isolated_extraction": {
            case: generate_extraction_metrics(
                case,
                source_bytes=_verified_source_bytes(workspace, case),
            )
            for case in PAIRED_CASES
        },
        "isolated_projection": {
            case: generate_projection_metrics(case, workspace=workspace)
            for case in PAIRED_CASES
        },
        "resource_boundaries": generate_resource_boundary_metrics(),
        "deadline_boundaries": generate_deadline_metrics(),
        "paired_parser": generate_paired_parser_metrics(workspace, repeats=repeats),
        "control_matrix": generate_control_matrix(workspace),
        "relationship_order_retention": (
            generate_relationship_order_retention_metrics(workspace)
        ),
        **HOSTED_USAGE,
    }


def generate_artifact(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = PAIRED_REPEAT_COUNT,
) -> dict[str, Any]:
    if repeats != PAIRED_REPEAT_COUNT:
        raise ValueError("retained outline metrics require exactly 5 repeats")
    workspace = workspace.resolve()
    code_before = _code_custody(workspace)
    sources_before = _source_custody(workspace, CONTROL_CASES)
    preliminary = generate_preliminary_metrics(workspace, repeats=repeats)
    code_after = _code_custody(workspace)
    sources_after = _source_custody(workspace, CONTROL_CASES)
    if code_before != code_after:
        raise RuntimeError("US07 code custody changed during measurement")
    if sources_before != sources_after:
        raise RuntimeError("US07 source custody changed during measurement")
    if preliminary["input_custody"] != {
        case: sources_before[case] for case in PAIRED_CASES
    }:
        raise RuntimeError("US07 preliminary source custody was inconsistent")
    return _build_final_artifact_envelope(
        preliminary,
        code_custody=code_after,
        dependency_custody=_dependency_custody(workspace),
        predecessor_custody=_predecessor_custody(workspace),
        m0_custody=_m0_custody(workspace),
        oracle_custody=_oracle_custody(workspace),
        contract_custody=_contract_custody(workspace),
        synthetic_fixture_custody=_synthetic_fixture_custody(workspace),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--repeats",
        type=int,
        choices=(PAIRED_REPEAT_COUNT,),
        default=PAIRED_REPEAT_COUNT,
    )
    parser.add_argument("--final-artifact", action="store_true")
    parser.add_argument("--worker-case", choices=PAIRED_CASES)
    parser.add_argument("--worker-enabled", choices=("true", "false"))
    arguments = parser.parse_args(argv)
    if arguments.worker_case is not None:
        if arguments.final_artifact:
            parser.error("--final-artifact is unavailable in worker mode")
        if arguments.worker_enabled is None:
            parser.error("--worker-enabled is required with --worker-case")
    elif arguments.worker_enabled is not None:
        parser.error("--worker-case is required with --worker-enabled")
    return arguments


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse_args(argv)
    workspace = arguments.workspace.resolve()
    if arguments.worker_case is not None:
        payload = _worker_snapshot(
            workspace,
            arguments.worker_case,
            arguments.worker_enabled == "true",
        )
    elif arguments.final_artifact:
        payload = generate_artifact(workspace, repeats=arguments.repeats)
    else:
        payload = generate_preliminary_metrics(workspace, repeats=arguments.repeats)
    _write_json_atomic(arguments.output.resolve(), payload)


if __name__ == "__main__":
    main()
