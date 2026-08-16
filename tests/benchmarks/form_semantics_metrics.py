"""Local quality and resource metrics for P03-US06 form semantics.

The isolated profiles deliberately keep wall-clock timing separate from
``tracemalloc``.  Full parser comparisons run every flag state in a fresh
worker process and alternate off/on order within five paired samples.

This module can produce a preliminary payload, but it does not write the
retained Phase 03 evidence artifact unless an explicit ``--output`` path is
provided by the caller.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import gc
import hashlib
import importlib.metadata as importlib_metadata
from io import BytesIO
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Callable, Iterator, Mapping, Sequence

from app.config import Settings
from app.services.form_semantics import (
    FormEvidenceReport,
    FormSourcePage,
    SourceVector,
)
from app.services.ir import (
    MAX_FORM_GROUPS_PER_PAGE,
    DocumentIR,
    build_document_ir,
)
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
import app.services.form_semantics as semantics


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
DEFAULT_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/P03-US06-form-metrics.json"
)
PREDECESSOR_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/P03-US05-text-run-metrics.json"
)
PREDECESSOR_ARTIFACT_RAW_SHA256 = (
    "0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659"
)
PREDECESSOR_ARTIFACT_SEMANTIC_SHA256 = (
    "e432ce80d6351d1d161010aec7f8b32a1622a54cf1b14e14bfccb3411c79c3c3"
)
PAIRED_CASES = ("insurance-acord", "component-datasheet")
PAIRED_REPEAT_COUNT = 5
SOURCE_IDENTITIES: dict[str, dict[str, Any]] = {
    "insurance-acord": {
        "path": "benchmark-expertmodeldata/insurance-acord.pdf",
        "size_bytes": 17_086,
        "sha256": (
            "85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4"
        ),
        "page_count": 1,
    },
    "component-datasheet": {
        "path": "benchmark-expertmodeldata/component-datasheet.pdf",
        "size_bytes": 329_199,
        "sha256": (
            "5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4"
        ),
        "page_count": 3,
    },
}
M0_REFERENCES = {
    "insurance-acord": {
        "label": "M0_reference_context_not_paired_predecessor",
        "wall_seconds": 9.06,
        "peak_rss_mib": 1_401.1,
    },
    "component-datasheet": {
        "label": "M0_reference_context_not_paired_predecessor",
        "wall_seconds": 10.56,
        "peak_rss_mib": 1_840.3,
    },
}
EXTRACTION_CEILINGS_SECONDS = {
    "insurance-acord": 0.150,
    "component-datasheet": 0.300,
}
PAIRED_ABSOLUTE_CEILINGS_SECONDS = {
    "insurance-acord": 0.453,
    "component-datasheet": 0.528,
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
EXPECTED_FORM_SUMMARIES = {
    "insurance-acord": {
        "anchor_count": 6,
        "group_count": 6,
        "field_count": 24,
        "label_count": 42,
        "value_region_count": 24,
        "control_count": 24,
        "key_value_pair_count": 0,
    },
    "component-datasheet": {
        "anchor_count": 3,
        "group_count": 3,
        "field_count": 0,
        "label_count": 16,
        "value_region_count": 16,
        "control_count": 0,
        "key_value_pair_count": 16,
    },
}
TIMING_PATHS_REMOVED = (
    "processing.duration_ms",
    "processing.form_semantics.extraction_ms",
    "processing.form_semantics.projection_ms",
    "processing.form_semantics.total_ms",
)
FINAL_CODE_PATHS = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "app/config.py",
    "app/models.py",
    "app/services/acroform.py",
    "app/services/acroform_raw.py",
    "app/services/form_semantics.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/lib/canonical-presentation.ts",
    "frontend/lib/form-semantics.ts",
    "frontend/lib/normalize-document-json.ts",
    "frontend/lib/serialize-output.ts",
    "frontend/lib/types.ts",
    "frontend/package-lock.json",
    "frontend/tests/p03-us06-form-semantics.test.mts",
    "tests/benchmarks/form_semantics_metrics.py",
    "tests/contract/test_p03_us06_form_semantics_contract.py",
    "tests/fixtures/phase_03/form_semantics/__init__.py",
    "tests/fixtures/phase_03/form_semantics/oracle.py",
    "tests/fixtures/phase_03/form_semantics/synthetic.py",
    "tests/performance/test_p03_us06_form_performance.py",
    "tests/stories/phase_03/test_p03_us06_acroform_raw.py",
    "tests/stories/phase_03/test_p03_us06_acroform_security.py",
    "tests/stories/phase_03/test_p03_us06_form_source_security.py",
    "tests/stories/phase_03/test_p03_us06_forms_key_values.py",
    "tests/stories/phase_03/test_p03_us06_group_caps.py",
    "tracker/phase-03-layout/decisions/"
    "P03-form-and-key-value-semantics-policy.md",
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
ORACLE_CONSTANT_NAMES = (
    "SOURCE_IDENTITIES",
    "ACORD_GROUP_ORACLE",
    "ACORD_LABEL_ORACLE",
    "ACORD_EMPTY_FIELD_ORACLE",
    "ACORD_VALUE_REGION_ORACLE",
    "ACORD_FIELD_BOUNDARY_SOURCE_OBJECTS",
    "ACORD_CONTROL_ORACLE",
    "COMPONENT_KEY_VALUE_ORACLE",
    "COMPONENT_KEY_VALUE_PAIR_ORACLE",
    "ACORD_RELATIONSHIP_ORACLE",
    "COMPONENT_RELATIONSHIP_ORACLE",
    "ACORD_CANONICAL_INERT_ORACLE",
    "COMPONENT_CANONICAL_ORACLE",
    "ACORD_REVIEWED_COUNTS",
    "COMPONENT_REVIEWED_COUNTS",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
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


def _inclusive_p95(samples: Sequence[float]) -> float:
    """Return the policy's inclusive nearest-rank p95."""

    if not samples:
        raise ValueError("p95 requires at least one sample")
    ordered = sorted(float(sample) for sample in samples)
    rank = math.ceil(0.95 * len(ordered))
    return ordered[rank - 1]


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
        layout_forms_enabled=enabled,
    )


def _settings_delta() -> dict[str, Any]:
    disabled = asdict(_settings(False))
    enabled = asdict(_settings(True))
    changed = sorted(
        key for key in disabled if disabled[key] != enabled[key]
    )
    predecessor_fields = (
        "layout_table_captions_enabled",
        "layout_visual_relationships_enabled",
        "layout_source_notes_enabled",
        "layout_relationship_order_enabled",
        "layout_text_run_semantics_enabled",
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


def _source_custody(
    workspace: Path = WORKSPACE,
    cases: Sequence[str] = PAIRED_CASES,
) -> dict[str, Any]:
    custody: dict[str, Any] = {}
    for case in cases:
        expected = SOURCE_IDENTITIES[case]
        source = workspace / expected["path"]
        source_bytes = source.read_bytes()
        observed = {
            "path": expected["path"],
            "size_bytes": len(source_bytes),
            "sha256": _sha256_bytes(source_bytes),
            "page_count": _observed_pdf_page_count(source_bytes),
        }
        custody[case] = {
            "expected": deepcopy(expected),
            "observed": observed,
            "exact_match": observed == expected,
        }
    return custody


def _verified_source_bytes(workspace: Path, case: str) -> bytes:
    expected = SOURCE_IDENTITIES[case]
    source = (workspace / expected["path"]).read_bytes()
    if (
        len(source) != expected["size_bytes"]
        or _sha256_bytes(source) != expected["sha256"]
    ):
        raise ValueError(f"immutable source identity mismatch: {case}")
    return source


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strip exactly the four accepted run-dependent timing fields."""

    detached = json.loads(_canonical_json(payload))
    processing = detached.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
        form_summary = processing.get("form_semantics")
        if isinstance(form_summary, dict):
            for key in ("extraction_ms", "projection_ms", "total_ms"):
                form_summary.pop(key, None)
    return detached


def _report_semantic_payload(report: FormEvidenceReport) -> dict[str, Any]:
    payload = asdict(report)
    payload.pop("extraction_ms", None)
    return payload


def _report_size_bytes(report: FormEvidenceReport) -> int:
    return len(_canonical_json(asdict(report)).encode("utf-8"))


def _profile_timing(
    operation: Any,
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
            raise RuntimeError(
                "timing profile requires tracemalloc to remain disabled"
            )
        started_ns = time.perf_counter_ns()
        result = operation()
        elapsed_ns = time.perf_counter_ns() - started_ns
        if tracemalloc.is_tracing():
            raise RuntimeError(
                "timing profile operation enabled tracemalloc"
            )
        samples.append(elapsed_ns / 1_000_000_000)
        if after_sample is not None:
            after_sample(result)
        del result
    return samples


def _profile_allocations(
    operation: Any,
    *,
    warmup_count: int = 1,
    sample_count: int = 5,
) -> tuple[list[int], Any]:
    for _ in range(warmup_count):
        operation()
    peaks: list[int] = []
    last_result: Any = None
    for sample_index in range(sample_count):
        last_result = None
        gc.collect()
        if tracemalloc.is_tracing():
            raise RuntimeError(
                "allocation profile requires a fresh tracemalloc session"
            )
        tracemalloc.start()
        try:
            result = operation()
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        peaks.append(peak_bytes)
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
        "within_peak_allocation_ceiling": (
            maximum <= PEAK_ALLOCATION_CEILING_BYTES
        ),
    }


def generate_extraction_metrics(
    case: str,
    *,
    source_bytes: bytes | None = None,
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported form performance case: {case}")
    source = (
        source_bytes
        if source_bytes is not None
        else _verified_source_bytes(WORKSPACE, case)
    )

    def extract() -> FormEvidenceReport:
        return semantics.extract_form_evidence(source, max_pages=100)

    semantic_digests: set[str] = set()

    def retain_extraction_digest(report: FormEvidenceReport) -> None:
        semantic_digests.add(
            _sha256_bytes(
                _canonical_json(_report_semantic_payload(report)).encode(
                    "utf-8"
                )
            )
        )

    samples = _profile_timing(
        extract,
        after_sample=retain_extraction_digest,
    )
    peaks, traced_report = _profile_allocations(extract)
    if not isinstance(traced_report, FormEvidenceReport):
        raise RuntimeError("form extraction allocation profile produced no report")
    timing = _timing_summary(
        samples,
        ceiling_seconds=EXTRACTION_CEILINGS_SECONDS[case],
    )
    allocation = _allocation_summary(peaks)
    page_count = len(traced_report.pages)
    return {
        "case": case,
        "profile": "isolated_source_extraction",
        **timing,
        **allocation,
        "report_size_bytes": _report_size_bytes(traced_report),
        "report_size_ceiling_bytes": semantics.MAX_REPORT_BYTES,
        "within_report_size_ceiling": (
            _report_size_bytes(traced_report) <= semantics.MAX_REPORT_BYTES
        ),
        "semantic_deterministic": len(semantic_digests) == 1,
        "source_sha256_exact": (
            traced_report.source_sha256 == SOURCE_IDENTITIES[case]["sha256"]
        ),
        "page_count": page_count,
        "character_count": sum(
            len(page.chars) for page in traced_report.pages
        ),
        "word_count": sum(len(page.words) for page in traced_report.pages),
        "vector_count": sum(
            len(page.vectors) for page in traced_report.pages
        ),
        "interactive_control_count": sum(
            len(page.interactive_controls) for page in traced_report.pages
        ),
        "interactivity": traced_report.interactivity,
        **HOSTED_USAGE,
    }


def _projection_payloads(
    workspace: Path,
    case: str,
) -> tuple[dict[str, Any], FormEvidenceReport]:
    source = _verified_source_bytes(workspace, case)
    result = parse_document(
        source,
        f"{case}.pdf",
        _settings(False),
    )
    predecessor = build_document_ir(
        result.model_dump(mode="json", exclude_none=True)
    )
    evidence = semantics.extract_form_evidence(source, max_pages=100)
    return predecessor.model_dump(mode="json"), evidence


_PROJECTION_CACHE: dict[
    tuple[str, str], tuple[dict[str, Any], FormEvidenceReport]
] = {}


def _projection_inputs(
    case: str,
    *,
    workspace: Path = WORKSPACE,
) -> tuple[DocumentIR, FormEvidenceReport]:
    cache_key = (str(workspace.resolve()), case)
    if cache_key not in _PROJECTION_CACHE:
        _PROJECTION_CACHE[cache_key] = _projection_payloads(workspace, case)
    predecessor_payload, evidence = _PROJECTION_CACHE[cache_key]
    return (
        DocumentIR.model_validate(deepcopy(predecessor_payload)),
        deepcopy(evidence),
    )


def _form_role_counts(ir: DocumentIR) -> dict[str, int]:
    roles = [
        element.form_semantics.role
        for element in ir.elements
        if element.form_semantics is not None
        and element.form_semantics.policy_id == semantics.POLICY_ID
    ]
    return {
        role: roles.count(role)
        for role in (
            "group",
            "field",
            "label",
            "value_region",
            "control",
            "key_value_pair",
        )
    }


def _capture_projection_comparisons(
    predecessor: DocumentIR,
    evidence: FormEvidenceReport,
) -> tuple[dict[int, int], DocumentIR]:
    """Run one untimed projection and retain its final per-page counters."""

    captured: dict[int, int] = {}
    original_account = semantics._ProjectionBudget.account_comparisons
    original_commit = semantics._ProjectionBudget.commit_comparisons

    def capture(budget: Any) -> None:
        captured.clear()
        captured.update(budget.comparisons_by_page)

    def account(
        budget: Any,
        page_index: int,
        count: int,
    ) -> None:
        original_account(budget, page_index, count)
        capture(budget)

    def commit(
        budget: Any,
        page_index: int,
        baseline: int,
        local_comparisons: int,
    ) -> None:
        original_commit(
            budget,
            page_index,
            baseline,
            local_comparisons,
        )
        capture(budget)

    semantics._ProjectionBudget.account_comparisons = account
    semantics._ProjectionBudget.commit_comparisons = commit
    try:
        projected = semantics.project_form_semantics(predecessor, evidence)
    finally:
        semantics._ProjectionBudget.account_comparisons = original_account
        semantics._ProjectionBudget.commit_comparisons = original_commit
    return (
        {
            page.page_index: captured.get(page.page_index, 0)
            for page in evidence.pages
        },
        projected,
    )


def generate_projection_metrics(
    case: str,
    *,
    workspace: Path = WORKSPACE,
    predecessor: DocumentIR | None = None,
    evidence: FormEvidenceReport | None = None,
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported form performance case: {case}")
    if predecessor is None or evidence is None:
        predecessor, evidence = _projection_inputs(case, workspace=workspace)
    predecessor_payload = predecessor.model_dump(mode="json")

    def project() -> DocumentIR:
        return semantics.project_form_semantics(predecessor, evidence)

    semantic_digests: set[str] = set()

    def retain_projection_digest(result: DocumentIR) -> None:
        semantic_digests.add(
            _sha256_bytes(
                _canonical_json(result.model_dump(mode="json")).encode(
                    "utf-8"
                )
            )
        )

    samples = _profile_timing(
        project,
        after_sample=retain_projection_digest,
    )
    peaks, traced_projection = _profile_allocations(project)
    if not isinstance(traced_projection, DocumentIR):
        raise RuntimeError("form projection allocation profile produced no IR")
    replayed = semantics.project_form_semantics(traced_projection, evidence)
    comparisons_by_page, instrumented_projection = (
        _capture_projection_comparisons(predecessor, evidence)
    )
    timing = _timing_summary(
        samples,
        ceiling_seconds=PROJECTION_CEILING_SECONDS,
    )
    allocation = _allocation_summary(peaks)
    return {
        "case": case,
        "profile": "isolated_association_projection",
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
        "maximum_comparisons_on_page": max(
            comparisons_by_page.values(),
            default=0,
        ),
        "comparison_ceiling_per_page": semantics.MAX_COMPARISONS_PER_PAGE,
        "within_comparison_ceiling": all(
            count <= semantics.MAX_COMPARISONS_PER_PAGE
            for count in comparisons_by_page.values()
        ),
        "instrumented_projection_semantically_equal": (
            instrumented_projection.model_dump(mode="json")
            == traced_projection.model_dump(mode="json")
        ),
        "role_counts": _form_role_counts(traced_projection),
        **HOSTED_USAGE,
    }


def _boundary_document(anchor_count: int) -> dict[str, Any]:
    items = []
    for index in range(anchor_count):
        column = index % 16
        row = index // 16
        items.append(
            {
                "id": f"boundary-anchor-{index:03d}",
                "type": "text",
                "reading_order": index,
                "value": f"Boundary anchor {index}",
                "md": f"Boundary anchor {index}",
                "bbox": {
                    "x": 12.0 + column * 18.0,
                    "y": 12.0 + row * 14.0,
                    "width": 16.0,
                    "height": 10.0,
                    "unit": "pt",
                },
                "source": "native",
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "p03-us06-projector-boundary.pdf",
            "mime_type": "application/pdf",
            "sha256": _sha256_bytes(
                f"p03-us06-projector-boundary:{anchor_count}".encode()
            ),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 320.0,
                "page_height": 260.0,
                "unit": "pt",
                "success": True,
                "items": items,
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 0,
        },
        "warnings": [],
    }


def _boundary_inputs(
    group_count: int,
) -> tuple[DocumentIR, FormEvidenceReport, tuple[Any, ...]]:
    predecessor = build_document_ir(_boundary_document(group_count))
    elements_by_public_id = {
        str(element.properties.get("legacy_item", {}).get("id")): element
        for element in predecessor.elements
    }
    candidates = []
    vectors = []
    for index in range(group_count):
        public_id = f"boundary-anchor-{index:03d}"
        anchor = elements_by_public_id[public_id]
        column = index % 16
        row = index // 16
        bbox = (
            12.0 + column * 18.0,
            12.0 + row * 14.0,
            12.0,
            10.0,
        )
        control_token = f"control:boundary-{index:03d}"
        source_objects = (("rect", index, None),)
        candidates.append(
            semantics._GroupCandidate(
                group_key=f"boundary-group-{index:03d}",
                page_index=1,
                bbox=bbox,
                status="resolved",
                interactivity="static",
                canonical_mode="inert",
                anchor_public_item_id=public_id,
                anchor_element_id=anchor.id,
                contributor_public_item_ids=(public_id,),
                contributor_element_ids=(anchor.id,),
                records=(
                    semantics._RecordCandidate(
                        token=control_token,
                        role="control",
                        key=f"boundary-control-{index:03d}",
                        bbox=bbox,
                        source_objects=source_objects,
                        data={
                            "control_type": "checkbox",
                            "state": "ambiguous",
                            "origin": "static_vector",
                        },
                    ),
                ),
                relationships=(
                    (
                        "contains",
                        f"group:boundary-group-{index:03d}",
                        control_token,
                    ),
                    (
                        "control_of",
                        control_token,
                        f"group:boundary-group-{index:03d}",
                    ),
                ),
                source_objects=source_objects,
            )
        )
        vectors.append(
            SourceVector(
                kind="rect",
                index=index,
                x0=bbox[0],
                top=bbox[1],
                x1=bbox[0] + bbox[2],
                bottom=bbox[1] + bbox[3],
                fill=False,
            )
        )
    report = FormEvidenceReport(
        report_version=semantics.REPORT_VERSION,
        policy_id=semantics.POLICY_ID,
        source_sha256=predecessor.source_sha256,
        pages=(
            FormSourcePage(
                page_index=1,
                width=320.0,
                height=260.0,
                chars=(),
                words=(),
                vectors=tuple(vectors),
                annotations=(),
                interactivity="static",
            ),
        ),
        interactivity="static",
        concern_codes=(),
        extraction_ms=0.0,
    )
    return predecessor, report, tuple(candidates)


@contextmanager
def _fixed_candidates(candidates: tuple[Any, ...]) -> Iterator[None]:
    original_key_values = semantics._key_value_candidates
    original_static = semantics._static_form_candidates
    original_interactive = semantics._interactive_form_candidates
    semantics._key_value_candidates = lambda *_args, **_kwargs: ()
    semantics._static_form_candidates = (
        lambda *_args, **_kwargs: candidates
    )
    semantics._interactive_form_candidates = lambda *_args, **_kwargs: ()
    try:
        yield
    finally:
        semantics._key_value_candidates = original_key_values
        semantics._static_form_candidates = original_static
        semantics._interactive_form_candidates = original_interactive


def _without_form_limit_concern(ir: DocumentIR) -> dict[str, Any]:
    payload = ir.model_dump(mode="json")
    payload["concerns"] = [
        concern
        for concern in payload["concerns"]
        if concern.get("code") != "form_projection_failed_closed"
    ]
    return payload


def generate_boundary_metrics() -> dict[str, Any]:
    exact_count = MAX_FORM_GROUPS_PER_PAGE
    overflow_count = exact_count + 1
    exact_predecessor, exact_report, exact_candidates = _boundary_inputs(
        exact_count
    )
    overflow_predecessor, overflow_report, overflow_candidates = (
        _boundary_inputs(overflow_count)
    )

    with _fixed_candidates(exact_candidates):
        exact_started_ns = time.perf_counter_ns()
        exact = semantics.project_form_semantics(
            exact_predecessor,
            exact_report,
        )
        exact_elapsed = (
            time.perf_counter_ns() - exact_started_ns
        ) / 1_000_000_000
    with _fixed_candidates(overflow_candidates):
        overflow_started_ns = time.perf_counter_ns()
        overflow = semantics.project_form_semantics(
            overflow_predecessor,
            overflow_report,
        )
        overflow_elapsed = (
            time.perf_counter_ns() - overflow_started_ns
        ) / 1_000_000_000

    exact_counts = _form_role_counts(exact)
    overflow_counts = _form_role_counts(overflow)
    overflow_concerns = [
        concern.code
        for concern in overflow.concerns
        if concern.code == "form_projection_failed_closed"
    ]
    return {
        "boundary": "maximum_groups_per_page",
        "construction_timed": False,
        "exact_maximum": exact_count,
        "maximum_plus_one": overflow_count,
        "exact_elapsed_seconds": round(exact_elapsed, 9),
        "maximum_plus_one_elapsed_seconds": round(overflow_elapsed, 9),
        "ceiling_seconds_each": BOUNDARY_CEILING_SECONDS,
        "exact_within_ceiling": exact_elapsed <= BOUNDARY_CEILING_SECONDS,
        "maximum_plus_one_within_ceiling": (
            overflow_elapsed <= BOUNDARY_CEILING_SECONDS
        ),
        "within_ceiling": max(exact_elapsed, overflow_elapsed)
        <= BOUNDARY_CEILING_SECONDS,
        "exact_role_counts": exact_counts,
        "exact_completed": (
            exact_counts["group"] == exact_count
            and exact_counts["control"] == exact_count
        ),
        "maximum_plus_one_role_counts": overflow_counts,
        "maximum_plus_one_concern_codes": overflow_concerns,
        "maximum_plus_one_failed_closed": (
            not any(overflow_counts.values())
            and overflow_concerns == ["form_projection_failed_closed"]
            and _without_form_limit_concern(overflow)
            == _without_form_limit_concern(overflow_predecessor)
        ),
        **HOSTED_USAGE,
    }


def _rss_bytes_from_maxrss(value: int, *, platform_name: str) -> int:
    return value if platform_name == "darwin" else value * 1024


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return _rss_bytes_from_maxrss(value, platform_name=sys.platform)


def _paired_states(pair_index: int) -> tuple[bool, bool]:
    return (False, True) if pair_index % 2 == 0 else (True, False)


def _paired_performance_summary(
    case: str,
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if case not in PAIRED_CASES:
        raise ValueError(f"unsupported paired form case: {case}")
    if (
        len(off_samples) != PAIRED_REPEAT_COUNT
        or len(on_samples) != PAIRED_REPEAT_COUNT
    ):
        raise ValueError("paired form performance requires exactly 5 pairs")
    signed = [
        float(enabled["wall_seconds"])
        - float(disabled["wall_seconds"])
        for disabled, enabled in zip(off_samples, on_samples, strict=True)
    ]
    clipped = [max(delta, 0.0) for delta in signed]
    disabled_wall = [
        float(sample["wall_seconds"]) for sample in off_samples
    ]
    enabled_wall = [
        float(sample["wall_seconds"]) for sample in on_samples
    ]
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
        "paired_signed_wall_seconds_deltas": [
            round(delta, 6) for delta in signed
        ],
        "paired_nonnegative_overhead_seconds": [
            round(delta, 6) for delta in clipped
        ],
        "p50_signed_delta_seconds": round(statistics.median(signed), 6),
        "p95_signed_delta_seconds": round(_inclusive_p95(signed), 6),
        "p50_nonnegative_overhead_seconds": round(
            statistics.median(clipped), 6
        ),
        "p95_nonnegative_overhead_seconds": round(overhead_p95, 6),
        "current_paired_predecessor_p95_seconds": round(baseline_p95, 6),
        "five_percent_ceiling_seconds": round(five_percent_ceiling, 6),
        "absolute_ceiling_seconds": absolute_ceiling,
        "effective_ceiling_seconds": round(effective_ceiling, 6),
        "within_five_percent_ceiling": (
            overhead_p95 <= five_percent_ceiling
        ),
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


def _public_form_summary(payload: Mapping[str, Any]) -> dict[str, int]:
    anchors = [
        item
        for item in _iter_public_items(payload)
        if item.get("layout_forms_projected") is True
        and item.get("form_policy") == semantics.POLICY_ID
    ]
    return {
        "anchor_count": len(anchors),
        "group_count": sum("form_group" in anchor for anchor in anchors),
        "field_count": sum(
            len(anchor.get("form_fields", ())) for anchor in anchors
        ),
        "label_count": sum(
            len(anchor.get("form_labels", ())) for anchor in anchors
        ),
        "value_region_count": sum(
            len(anchor.get("form_value_regions", ())) for anchor in anchors
        ),
        "control_count": sum(
            len(anchor.get("form_controls", ())) for anchor in anchors
        ),
        "key_value_pair_count": sum(
            len(anchor.get("form_key_value_pairs", ())) for anchor in anchors
        ),
    }


def _worker_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    source = _verified_source_bytes(workspace, case)
    extractor_calls = 0
    original_extractor = semantics.extract_form_evidence

    def counted_extractor(*args: Any, **kwargs: Any) -> Any:
        nonlocal extractor_calls
        extractor_calls += 1
        return original_extractor(*args, **kwargs)

    semantics.extract_form_evidence = counted_extractor
    started_ns = time.perf_counter_ns()
    try:
        result = parse_document(
            source,
            f"{case}.pdf",
            _settings(enabled),
        )
    finally:
        elapsed_seconds = (
            time.perf_counter_ns() - started_ns
        ) / 1_000_000_000
        semantics.extract_form_evidence = original_extractor
    payload = result.model_dump(mode="json", exclude_none=True)
    semantic_json = _canonical_json(_semantic_payload(payload)).encode("utf-8")
    raw_json = _canonical_json(payload).encode("utf-8")
    markdown = to_markdown(payload).encode("utf-8")
    form_summary = _public_form_summary(payload)
    processing = payload.get("processing")
    processing_has_form_summary = (
        isinstance(processing, Mapping)
        and isinstance(processing.get("form_semantics"), Mapping)
    )
    return {
        "case": case,
        "enabled": enabled,
        "input_identity": deepcopy(SOURCE_IDENTITIES[case]),
        "wall_seconds": round(elapsed_seconds, 6),
        "peak_rss_bytes": _rss_bytes(),
        "rss_source": "resource.getrusage(RUSAGE_SELF).ru_maxrss",
        "rss_normalization": (
            "bytes_on_darwin_else_kibibytes_times_1024"
        ),
        "extractor_call_count": extractor_calls,
        "semantic_json_sha256": _sha256_bytes(semantic_json),
        "semantic_json_size_bytes": len(semantic_json),
        "raw_json_sha256": _sha256_bytes(raw_json),
        "raw_json_size_bytes": len(raw_json),
        "markdown_sha256": _sha256_bytes(markdown),
        "markdown_size_bytes": len(markdown),
        "form_summary": form_summary,
        "processing_has_form_summary": processing_has_form_summary,
        "flag_off_projection_absent": (
            not enabled
            and extractor_calls == 0
            and not processing_has_form_summary
            and not any(form_summary.values())
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
        "tests.benchmarks.form_semantics_metrics",
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
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
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
    with tempfile.TemporaryDirectory(prefix=f"p03-us06-{case}-") as directory:
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
                "fresh US06 metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4_000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def generate_paired_parser_metrics(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = PAIRED_REPEAT_COUNT,
) -> dict[str, Any]:
    if repeats != PAIRED_REPEAT_COUNT:
        raise ValueError("paired form performance requires exactly 5 repeats")
    cases: dict[str, Any] = {}
    for case in PAIRED_CASES:
        off_samples: list[dict[str, Any]] = []
        on_samples: list[dict[str, Any]] = []
        execution_order: list[list[str]] = []
        for pair_index in range(repeats):
            states = _paired_states(pair_index)
            execution_order.append(
                ["on" if state else "off" for state in states]
            )
            results: dict[bool, dict[str, Any]] = {}
            for state in states:
                results[state] = _fresh_snapshot(
                    workspace,
                    case,
                    state,
                )
            off_samples.append(results[False])
            on_samples.append(results[True])
        enabled_semantic_digests = {
            sample["semantic_json_sha256"] for sample in on_samples[:3]
        }
        cases[case] = {
            "execution_order": execution_order,
            "flag_off_samples": off_samples,
            "flag_on_samples": on_samples,
            "all_flag_off_extractor_counts_zero": all(
                sample["extractor_call_count"] == 0
                for sample in off_samples
            ),
            "all_flag_on_extractor_counts_one": all(
                sample["extractor_call_count"] == 1
                for sample in on_samples
            ),
            "all_flag_off_projection_absent": all(
                sample["flag_off_projection_absent"]
                for sample in off_samples
            ),
            "all_flag_on_processing_summaries_present": all(
                sample.get("processing_has_form_summary") is True
                for sample in on_samples
            ),
            "all_flag_on_form_summaries_exact": all(
                sample.get("form_summary") == EXPECTED_FORM_SUMMARIES[case]
                for sample in on_samples
            ),
            "flag_off_semantic_deterministic": len(
                {sample["semantic_json_sha256"] for sample in off_samples}
            )
            == 1,
            "flag_on_first_three_semantic_deterministic": (
                len(enabled_semantic_digests) == 1
            ),
            "flag_on_all_semantic_deterministic": len(
                {sample["semantic_json_sha256"] for sample in on_samples}
            )
            == 1,
            "all_samples_zero_hosted_usage": all(
                all(sample.get(key) == value for key, value in HOSTED_USAGE.items())
                for sample in (*off_samples, *on_samples)
            ),
            "timing_paths_removed": list(TIMING_PATHS_REMOVED),
            "paired_performance": _paired_performance_summary(
                case,
                off_samples,
                on_samples,
            ),
        }
    return {
        "pair_count_per_case": repeats,
        "performance_cases": list(PAIRED_CASES),
        "execution_order_policy": "off/on alternates by pair index",
        "cases": cases,
        **HOSTED_USAGE,
    }


def _code_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    return {
        relative: _file_identity(workspace, relative)
        for relative in FINAL_CODE_PATHS
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
    identity = _file_identity(workspace, PREDECESSOR_ARTIFACT_RELATIVE_PATH)
    if identity["sha256"] != PREDECESSOR_ARTIFACT_RAW_SHA256:
        raise ValueError("sealed P03-US05 artifact raw digest changed")
    path = workspace / PREDECESSOR_ARTIFACT_RELATIVE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("semantic_sha256") != PREDECESSOR_ARTIFACT_SEMANTIC_SHA256:
        raise ValueError("sealed P03-US05 artifact semantic digest changed")
    return {
        **identity,
        "raw_sha256": PREDECESSOR_ARTIFACT_RAW_SHA256,
        "semantic_sha256": PREDECESSOR_ARTIFACT_SEMANTIC_SHA256,
        "story": payload.get("story"),
        "relationship_order_retention_all_pass": payload.get(
            "aggregate", {}
        ).get("relationship_order_retention_all_pass"),
    }


def _oracle_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    from tests.fixtures.phase_03.form_semantics import oracle

    payload = {
        name: getattr(oracle, name)
        for name in ORACLE_CONSTANT_NAMES
    }
    source_identities = payload["SOURCE_IDENTITIES"]
    return {
        "oracle_file": _file_identity(
            workspace,
            "tests/fixtures/phase_03/form_semantics/oracle.py",
        ),
        "oracle_payload_sha256": _sha256_bytes(
            _canonical_json(payload).encode("utf-8")
        ),
        "source_identities_exact": source_identities == SOURCE_IDENTITIES,
        "source_identities": deepcopy(source_identities),
        "acord_reviewed_counts": deepcopy(payload["ACORD_REVIEWED_COUNTS"]),
        "component_reviewed_counts": deepcopy(
            payload["COMPONENT_REVIEWED_COUNTS"]
        ),
        "acord_relationship_oracle_sha256": _sha256_bytes(
            _canonical_json(payload["ACORD_RELATIONSHIP_ORACLE"]).encode(
                "utf-8"
            )
        ),
        "component_relationship_oracle_sha256": _sha256_bytes(
            _canonical_json(payload["COMPONENT_RELATIONSHIP_ORACLE"]).encode(
                "utf-8"
            )
        ),
    }


def _synthetic_fixture_custody(
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    from tests.fixtures.phase_03.form_semantics import synthetic

    hashes = synthetic.synthetic_self_check(verify_pdf_readers=False)
    return {
        "generator_file": _file_identity(
            workspace,
            "tests/fixtures/phase_03/form_semantics/synthetic.py",
        ),
        "fixture_count": len(synthetic.SYNTHETIC_FIXTURE_IDS),
        "required_capability_count": len(
            synthetic.REQUIRED_SYNTHETIC_COVERAGE
        ),
        "thresholds": dict(synthetic.SYNTHETIC_THRESHOLDS),
        "fixture_hashes": hashes,
        "registry_sha256": _sha256_bytes(
            _canonical_json(hashes).encode("utf-8")
        ),
        "self_check_passed": True,
        "pdf_reader_verification_scope": (
            "retained test gate; omitted from performance process"
        ),
    }


def _boundary_fixture_custody() -> dict[str, Any]:
    exact_count = MAX_FORM_GROUPS_PER_PAGE
    cases: dict[str, Any] = {}
    for name, count, expected in (
        ("exact_maximum", exact_count, "success"),
        ("maximum_plus_one", exact_count + 1, "page_fail_closed"),
    ):
        document = _boundary_document(count)
        cases[name] = {
            "group_count": count,
            "expected": expected,
            "preconstructed_candidates": True,
            "document_payload_sha256": _sha256_bytes(
                _canonical_json(document).encode("utf-8")
            ),
        }
    return {
        "boundary": "maximum_groups_per_page",
        "construction_excluded_from_timing": True,
        "cases": cases,
        "custody_sha256": _sha256_bytes(
            _canonical_json(cases).encode("utf-8")
        ),
    }


def _output_size_summary(paired: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    selected_keys = (
        "semantic_json_sha256",
        "semantic_json_size_bytes",
        "raw_json_sha256",
        "raw_json_size_bytes",
        "markdown_sha256",
        "markdown_size_bytes",
    )
    for case, record in paired["cases"].items():
        output[case] = {
            state: [
                {key: sample[key] for key in selected_keys}
                for sample in record[f"flag_{state}_samples"]
            ]
            for state in ("off", "on")
        }
    return output


def _control_summary(preliminary: Mapping[str, Any]) -> dict[str, Any]:
    controls: dict[str, Any] = {}
    for case, record in preliminary["paired_parser"]["cases"].items():
        controls[case] = {
            "expected_form_summary": deepcopy(EXPECTED_FORM_SUMMARIES[case]),
            "all_enabled_form_summaries_exact": record[
                "all_flag_on_form_summaries_exact"
            ],
            "all_disabled_form_projections_absent": record[
                "all_flag_off_projection_absent"
            ],
            "enabled_first_three_semantic_deterministic": record[
                "flag_on_first_three_semantic_deterministic"
            ],
            "enabled_all_semantic_deterministic": record[
                "flag_on_all_semantic_deterministic"
            ],
            "disabled_semantic_deterministic": record[
                "flag_off_semantic_deterministic"
            ],
            "zero_hosted_usage": record["all_samples_zero_hosted_usage"],
        }
    return controls


def _rollback_summary(preliminary: Mapping[str, Any]) -> dict[str, Any]:
    paired_cases = preliminary["paired_parser"]["cases"]
    projections = preliminary["isolated_projection"]
    return {
        "rollback_value": False,
        "only_us06_setting_toggled": (
            preliminary["settings_delta"]["changed_fields"]
            == ["layout_forms_enabled"]
        ),
        "all_flag_off_extractor_counts_zero": all(
            record["all_flag_off_extractor_counts_zero"]
            for record in paired_cases.values()
        ),
        "all_flag_off_projection_absent": all(
            record["all_flag_off_projection_absent"]
            for record in paired_cases.values()
        ),
        "all_repeated_projections_idempotent": all(
            record["repeated_projection_idempotent"]
            for record in projections.values()
        ),
        "maximum_plus_one_page_failed_closed": preliminary[
            "maximum_boundary"
        ]["maximum_plus_one_failed_closed"],
    }


def _aggregate_summary(preliminary: Mapping[str, Any]) -> dict[str, Any]:
    extraction = preliminary["isolated_extraction"]
    projection = preliminary["isolated_projection"]
    paired_cases = preliminary["paired_parser"]["cases"]
    boundary = preliminary["maximum_boundary"]
    return {
        "input_custody_exact": all(
            record["exact_match"]
            for record in preliminary["input_custody"].values()
        ),
        "source_extraction_p95_within_case_ceilings": all(
            record["within_p95_ceiling"] for record in extraction.values()
        ),
        "source_extraction_peak_within_64mib": all(
            record["within_peak_allocation_ceiling"]
            for record in extraction.values()
        ),
        "source_reports_within_8mib": all(
            record["within_report_size_ceiling"]
            for record in extraction.values()
        ),
        "projection_p95_within_50ms": all(
            record["within_p95_ceiling"] for record in projection.values()
        ),
        "projection_peak_within_64mib": all(
            record["within_peak_allocation_ceiling"]
            for record in projection.values()
        ),
        "projection_comparisons_within_page_cap": all(
            record["within_comparison_ceiling"]
            for record in projection.values()
        ),
        "maximum_boundary_within_250ms": boundary["exact_within_ceiling"],
        "maximum_plus_one_within_250ms": boundary[
            "maximum_plus_one_within_ceiling"
        ],
        "maximum_plus_one_failed_closed": boundary[
            "maximum_plus_one_failed_closed"
        ],
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
            for record in paired_cases.values()
        ),
        "enabled_form_summaries_exact": all(
            record["all_flag_on_form_summaries_exact"]
            for record in paired_cases.values()
        ),
        "flag_off_extractor_count_zero": all(
            record["all_flag_off_extractor_counts_zero"]
            for record in paired_cases.values()
        ),
        **HOSTED_USAGE,
    }


def _build_final_artifact_envelope(
    preliminary: Mapping[str, Any],
    *,
    code_custody: Mapping[str, Any],
    dependency_custody: Mapping[str, Any],
    predecessor_custody: Mapping[str, Any],
    oracle_custody: Mapping[str, Any],
    synthetic_fixture_custody: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    paired = preliminary["paired_parser"]
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "record_kind": "p03_us06_form_metrics",
        "story": "P03-US06",
        "status": "final_measurement_candidate",
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "retained_path": str(DEFAULT_ARTIFACT_RELATIVE_PATH),
        "measurement": {
            "performance_cases": list(PAIRED_CASES),
            "pair_count_per_case": PAIRED_REPEAT_COUNT,
            "worker_process_count": PAIRED_REPEAT_COUNT
            * len(PAIRED_CASES)
            * 2,
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
            "policy_id": semantics.POLICY_ID,
            "feature_flag": "PARSER_LAYOUT_FORMS_ENABLED",
            "default_enabled": False,
            "rollback_value": False,
            "source_extraction_p95_ceiling_seconds": deepcopy(
                EXTRACTION_CEILINGS_SECONDS
            ),
            "projection_p95_ceiling_seconds": PROJECTION_CEILING_SECONDS,
            "isolated_peak_allocation_ceiling_bytes": (
                PEAK_ALLOCATION_CEILING_BYTES
            ),
            "maximum_boundary_ceiling_seconds": BOUNDARY_CEILING_SECONDS,
            "maximum_report_bytes": semantics.MAX_REPORT_BYTES,
            "maximum_comparisons_per_page": (
                semantics.MAX_COMPARISONS_PER_PAGE
            ),
            "paired_absolute_ceiling_seconds": deepcopy(
                PAIRED_ABSOLUTE_CEILINGS_SECONDS
            ),
            "paired_percent_ceiling": 5.0,
            "peak_rss_delta_ceiling_bytes": PEAK_RSS_DELTA_CEILING_BYTES,
            "semantic_timing_paths_removed": list(TIMING_PATHS_REMOVED),
            **HOSTED_USAGE,
        },
        "settings_delta": deepcopy(preliminary["settings_delta"]),
        "m0_reference": deepcopy(M0_REFERENCES),
        "input_custody": deepcopy(preliminary["input_custody"]),
        "oracle_custody": deepcopy(oracle_custody),
        "synthetic_fixture_custody": deepcopy(synthetic_fixture_custody),
        "boundary_fixture_custody": _boundary_fixture_custody(),
        "predecessor_custody": deepcopy(predecessor_custody),
        "code_sha256": deepcopy(code_custody),
        "dependency_custody": deepcopy(dependency_custody),
        "source_extraction": deepcopy(preliminary["isolated_extraction"]),
        "association_projection": deepcopy(
            preliminary["isolated_projection"]
        ),
        "maximum_boundary": deepcopy(preliminary["maximum_boundary"]),
        "paired_parser": deepcopy(paired),
        "control_matrix": _control_summary(preliminary),
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
        raise ValueError("preliminary form metrics require exactly 5 repeats")
    return {
        "story": "P03-US06",
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
        "maximum_boundary": generate_boundary_metrics(),
        "paired_parser": generate_paired_parser_metrics(
            workspace,
            repeats=repeats,
        ),
        **HOSTED_USAGE,
    }


def generate_artifact(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = PAIRED_REPEAT_COUNT,
) -> dict[str, Any]:
    if repeats != PAIRED_REPEAT_COUNT:
        raise ValueError("retained form metrics require exactly 5 repeats")
    workspace = workspace.resolve()
    code_before = _code_custody(workspace)
    sources_before = _source_custody(workspace)
    preliminary = generate_preliminary_metrics(workspace, repeats=repeats)
    code_after = _code_custody(workspace)
    sources_after = _source_custody(workspace)
    if code_before != code_after:
        raise RuntimeError("US06 code custody changed during measurement")
    if sources_before != sources_after:
        raise RuntimeError("US06 source custody changed during measurement")
    if preliminary["input_custody"] != sources_before:
        raise RuntimeError("US06 preliminary source custody was inconsistent")
    return _build_final_artifact_envelope(
        preliminary,
        code_custody=code_after,
        dependency_custody=_dependency_custody(workspace),
        predecessor_custody=_predecessor_custody(workspace),
        oracle_custody=_oracle_custody(workspace),
        synthetic_fixture_custody=_synthetic_fixture_custody(workspace),
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--output", type=Path)
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
        if arguments.output is None:
            parser.error("--output is required in worker mode")
    elif arguments.worker_enabled is not None:
        parser.error("--worker-case is required with --worker-enabled")
    elif arguments.output is None:
        parser.error("--output is required for preliminary metrics")
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
        payload = generate_artifact(
            workspace,
            repeats=arguments.repeats,
        )
    else:
        payload = generate_preliminary_metrics(
            workspace,
            repeats=arguments.repeats,
        )
    if arguments.output is None:
        raise RuntimeError("metrics output path was not resolved")
    _write_json_atomic(arguments.output.resolve(), payload)


if __name__ == "__main__":
    main()
