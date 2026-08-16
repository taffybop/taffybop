"""Retained quality and resource metrics for P03-US05.

The module is intentionally local-only.  Its full parser measurements run in
fresh worker processes, while the isolated source-extraction and projection
profiles keep timing separate from ``tracemalloc`` so allocation tracing does
not distort the latency sample.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
import gc
import hashlib
import importlib.metadata as importlib_metadata
import io
import json
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
from typing import Any, Iterable, Mapping, Sequence

import pdfplumber

from app.config import Settings
from app.services.ir import DocumentIR, build_document_ir
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
import app.services.text_run_semantics as semantics


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
DEFAULT_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/"
    "P03-US05-text-run-metrics.json"
)
PERFORMANCE_CASE = "purchase-agreement"
MEMORY_GUARD_CASE = "uber-earnings"
PAIRED_CASES = (PERFORMANCE_CASE, MEMORY_GUARD_CASE)
US04_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/"
    "P03-US04-reading-order-metrics.json"
)
US04_ARTIFACT_RAW_SHA256 = (
    "826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154"
)
US04_ARTIFACT_SEMANTIC_SHA256 = (
    "46cef72e08707cc57fd54834c7ff4369a59558b4e2de1a47155da23b66803ab1"
)
PURCHASE_SOURCE_SEQUENCE = (
    ("deleted", "Draft of 6/1/20"),
    (
        "deleted",
        "This is a draft document. Certain updates will be needed prior to "
        "finalizing this.",
    ),
    (
        "deleted",
        "In particular, bracketed items with '[ ]' indicate a known "
        "open/non-final item.",
    ),
    ("deleted", "This is Confidential to The City of Johnstown"),
    ("item", "p1-i11"),
    ("item", "p1-i1"),
    ("item", "p1-i2"),
)
PURCHASE_STABLE_ITEM_TEXT = {
    "p1-i11": ("exact", "EXECUTION VERSION"),
    "p1-i1": ("exact", "ASSET PURCHASE AGREEMENT"),
    "p1-i2": ("prefix", "THIS ASSET PURCHASE AGREEMENT"),
}
SOURCE_IDENTITIES: dict[str, dict[str, Any]] = {
    "purchase-agreement": {
        "path": "benchmark-expertmodeldata/purchase-agreement.pdf",
        "size_bytes": 152_828,
        "sha256": (
            "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14"
        ),
    },
    "postal-10k": {
        "path": "benchmark-expertmodeldata/postal-10k.pdf",
        "size_bytes": 83_589,
        "sha256": (
            "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74"
        ),
    },
    "finance-10k": {
        "path": "benchmark-expertmodeldata/finance-10k.pdf",
        "size_bytes": 87_105,
        "sha256": (
            "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086"
        ),
    },
    "uber-earnings": {
        "path": "benchmark-expertmodeldata/uber-earnings.pdf",
        "size_bytes": 7_584_019,
        "sha256": (
            "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
        ),
    },
}
M0_REFERENCE = {
    "label": "M0_reference_context_not_paired_predecessor",
    "wall_seconds": 6.18,
    "peak_rss_mib": 1_401.0,
}
HOSTED_USAGE = {
    "hosted_requests": 0,
    "hosted_tokens": 0,
    "hosted_cost_usd": 0,
}
FIXED_DENOMINATORS = {
    "purchase_page_1_characters": 3_338,
    "purchase_page_1_filled_rules": 13,
    "repair_expected": 3,
    "deleted_logical_groups_expected": 6,
    "deleted_group_rule_edges_expected": 7,
    "deleted_run_rule_links_expected": 9,
    "blue_runs_expected": 2,
    "blue_rule_links_expected": 4,
    "same_page_false_deletion_expected": 0,
    "same_page_false_deletion_control_count": 3,
    "source_proven_inserted_replacement_expected": 0,
    "purchase_source_sequence_expected": 7,
    "predecessor_order_expected": 41,
}
CONTROL_MATRIX = {
    "target": {
        "claim_id": "p00-us06:purchase-agreement:expert-row-01",
        "case": "purchase-agreement",
        "role": "target",
    },
    "related_positive": {
        "claim_id": "p00-us08:postal-10k:expert-row-03",
        "case": "postal-10k",
        "role": "related_positive",
    },
    "non_target_regression": {
        "claim_id": "p00-us06:finance-10k:expert-row-01",
        "case": "finance-10k",
        "role": "non_target_regression",
    },
    "negative_ambiguous_claim": {
        "claim_id": "p00-us06:purchase-agreement:expert-row-05",
        "case": "purchase-agreement",
        "role": "negative_ambiguous_claim",
    },
}
SYNTHETIC_FIXTURE_IDS = (
    "synthetic:p03-us05:plain-legal-v1",
    "synthetic:p03-us05:table-rule-v1",
    "synthetic:p03-us05:decorative-rule-v1",
    "synthetic:p03-us05:ambiguous-overlap-v1",
    "synthetic:p03-us05:markup-injection-v1",
    "synthetic:p03-us05:thresholds-v1",
    "synthetic:p03-us05:transforms-v1",
    "synthetic:p03-us05:limits-v1",
)
POSTAL_ITALIC_TARGETS = {
    "CARES Act": ["cells", 20, "text"],
    "Coronavirus Aid, Relief, and Economic Security Act": [
        "cells",
        21,
        "text",
    ],
    "Exchange Act": ["cells", 66, "text"],
    "Securities and Exchange Act of 1934": [
        "cells",
        67,
        "text",
    ],
}
CODE_PATHS = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "app/config.py",
    "app/models.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "app/services/text_run_semantics.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/lib/canonical-presentation.ts",
    "frontend/lib/normalize-document-json.ts",
    "frontend/lib/serialize-output.ts",
    "frontend/lib/text-run-semantics.ts",
    "frontend/lib/types.ts",
    "frontend/package-lock.json",
    "frontend/tests/p03-us05-redline-runs.test.mts",
    "tests/benchmarks/text_run_semantics_metrics.py",
    "tests/contract/test_p03_us05_target_path_order_interop.py",
    "tests/contract/test_p03_us05_text_run_contract.py",
    "tests/fixtures/p03_us05_target_path_order.json",
    "tests/performance/test_p03_us05_text_run_performance.py",
    "tests/regression/phase_03/test_p03_us04_real_reading_order.py",
    "tests/regression/phase_03/test_p03_us05_real_redline_runs.py",
    "tests/stories/phase_03/test_p03_us05_adversarial.py",
    "tests/stories/phase_03/test_p03_us05_algorithm_hardening.py",
    "tests/stories/phase_03/test_p03_us05_redline_runs.py",
    "tracker/phase-03-layout/decisions/"
    "P03-text-run-semantics-policy.md",
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


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _percentile95(samples: Sequence[float]) -> float:
    if not samples:
        raise ValueError("p95 requires at least one sample")
    if len(samples) == 1:
        return float(samples[0])
    return statistics.quantiles(
        samples,
        n=100,
        method="inclusive",
    )[94]


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=enabled,
    )


def _settings_delta() -> dict[str, Any]:
    off = asdict(_settings(False))
    on = asdict(_settings(True))
    changed = sorted(key for key in off if off[key] != on[key])
    return {
        "changed_fields": changed,
        "flag_off": {key: off[key] for key in changed},
        "flag_on": {key: on[key] for key in changed},
        "accepted_predecessor_flags_enabled": all(
            getattr(_settings(False), field)
            for field in (
                "layout_table_captions_enabled",
                "layout_visual_relationships_enabled",
                "layout_source_notes_enabled",
                "layout_relationship_order_enabled",
            )
        ),
    }


def _source_custody(
    workspace: Path = WORKSPACE,
    cases: Iterable[str] = SOURCE_IDENTITIES,
) -> dict[str, Any]:
    custody: dict[str, Any] = {}
    for case in cases:
        expected = SOURCE_IDENTITIES[case]
        source = workspace / expected["path"]
        observed = {
            "path": expected["path"],
            "size_bytes": source.stat().st_size,
            "sha256": _sha256_file(source),
        }
        custody[case] = {
            "expected": deepcopy(expected),
            "observed": observed,
            "exact_match": observed == expected,
        }
    return custody


def _verified_source_bytes(workspace: Path, case: str) -> bytes:
    custody = _source_custody(workspace, (case,))[case]
    if not custody["exact_match"]:
        raise ValueError(f"immutable source identity mismatch: {case}")
    return (workspace / SOURCE_IDENTITIES[case]["path"]).read_bytes()


def _code_custody(workspace: Path = WORKSPACE) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for relative in CODE_PATHS:
        path = workspace / relative
        if not path.is_file():
            raise ValueError(f"metrics code input is missing: {relative}")
        output[relative] = {
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    return output


def _dependency_custody(
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
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
            for package in (
                "docling",
                "docling-core",
                "pdfplumber",
                "pydantic",
            )
        },
        "dependency_manifest_sha256": {
            relative: _sha256_file(workspace / relative)
            for relative in (
                "pyproject.toml",
                "uv.lock",
                "frontend/package-lock.json",
            )
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
    }


@lru_cache(maxsize=1)
def _purchase_projection_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    source = _verified_source_bytes(WORKSPACE, PERFORMANCE_CASE)
    result = parse_document(
        source,
        f"{PERFORMANCE_CASE}.pdf",
        _settings(False),
    )
    predecessor = build_document_ir(
        result.model_dump(mode="json", exclude_none=True)
    )
    evidence = semantics.extract_text_run_evidence(source, max_pages=1)
    if not evidence.usable:
        raise RuntimeError("purchase source evidence was unavailable")
    return (
        predecessor.model_dump(mode="json"),
        evidence.model_dump(mode="json"),
    )


def _projection_inputs() -> tuple[DocumentIR, semantics.TextRunEvidence]:
    predecessor, evidence = _purchase_projection_payloads()
    return (
        DocumentIR.model_validate(deepcopy(predecessor)),
        semantics.TextRunEvidence.model_validate(deepcopy(evidence)),
    )


def generate_extraction_metrics(
    source_bytes: bytes | None = None,
) -> dict[str, Any]:
    source = (
        source_bytes
        if source_bytes is not None
        else _verified_source_bytes(WORKSPACE, PERFORMANCE_CASE)
    )
    warmup_count = 2
    sample_count = 20
    for _ in range(warmup_count):
        semantics.extract_text_run_evidence(source, max_pages=1)
    samples: list[float] = []
    reports: list[semantics.TextRunEvidence] = []
    for _ in range(sample_count):
        gc.collect()
        started = time.perf_counter()
        report = semantics.extract_text_run_evidence(source, max_pages=1)
        samples.append(time.perf_counter() - started)
        reports.append(report)
    tracemalloc.start()
    traced_report = semantics.extract_text_run_evidence(source, max_pages=1)
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    p95_seconds = _percentile95(samples)
    semantic_digests = {
        _sha256_bytes(
            _canonical_json(
                {
                    key: value
                    for key, value in report.model_dump(
                        mode="json"
                    ).items()
                    if key != "elapsed_ms"
                }
            ).encode("utf-8")
        )
        for report in reports
    }
    report_size = len(
        traced_report.model_dump_json(exclude_none=True).encode("utf-8")
    )
    return {
        "warmup_count": warmup_count,
        "sample_count": sample_count,
        "quantile_method": "empirical_p95_inclusive",
        "timing_tracemalloc_enabled": False,
        "allocation_measured_in_separate_call": True,
        "gc_collection_outside_timed_interval": True,
        "samples_seconds": [round(sample, 9) for sample in samples],
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(p95_seconds, 9),
        "min_seconds": round(min(samples), 9),
        "max_seconds": round(max(samples), 9),
        "p95_ceiling_seconds": 0.150,
        "within_p95_ceiling": p95_seconds <= 0.150,
        "peak_allocated_bytes": peak_bytes,
        "peak_allocation_ceiling_bytes": 64 * 1024 * 1024,
        "within_peak_allocation_ceiling": peak_bytes < 64 * 1024 * 1024,
        "report_size_bytes": report_size,
        "report_size_ceiling_bytes": semantics.MAX_REPORT_BYTES,
        "within_report_size_ceiling": (
            report_size <= semantics.MAX_REPORT_BYTES
        ),
        "usable": all(report.usable for report in reports)
        and traced_report.usable,
        "semantic_deterministic": len(semantic_digests) == 1,
        "character_count": traced_report.character_count,
        "candidate_rule_count": traced_report.candidate_rule_count,
        "run_count": len(traced_report.runs),
        "retained_rule_count": len(traced_report.rules),
        **HOSTED_USAGE,
    }


def generate_projection_metrics(
    predecessor: DocumentIR | None = None,
    evidence: semantics.TextRunEvidence | None = None,
) -> dict[str, Any]:
    if predecessor is None or evidence is None:
        predecessor, evidence = _projection_inputs()
    predecessor_payload = predecessor.model_dump(mode="json")
    warmup_count = 2
    sample_count = 20
    for _ in range(warmup_count):
        semantics.project_text_run_semantics(predecessor, evidence)
    samples: list[float] = []
    semantic_digests: set[str] = set()
    projected: DocumentIR | None = None
    for _ in range(sample_count):
        gc.collect()
        started = time.perf_counter()
        projected = semantics.project_text_run_semantics(
            predecessor,
            evidence,
        )
        samples.append(time.perf_counter() - started)
        semantic_digests.add(
            _sha256_bytes(
                _canonical_json(
                    projected.model_dump(mode="json")
                ).encode("utf-8")
            )
        )
    tracemalloc.start()
    traced_projection = semantics.project_text_run_semantics(
        predecessor,
        evidence,
    )
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if projected is None:
        raise RuntimeError("projection profile produced no sample")
    repeated = semantics.project_text_run_semantics(projected, evidence)
    p95_seconds = _percentile95(samples)
    projected_size = len(
        traced_projection.model_dump_json().encode("utf-8")
    )
    return {
        "warmup_count": warmup_count,
        "sample_count": sample_count,
        "quantile_method": "empirical_p95_inclusive",
        "timing_tracemalloc_enabled": False,
        "allocation_measured_in_separate_call": True,
        "gc_collection_outside_timed_interval": True,
        "samples_seconds": [round(sample, 9) for sample in samples],
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(p95_seconds, 9),
        "min_seconds": round(min(samples), 9),
        "max_seconds": round(max(samples), 9),
        "p95_ceiling_seconds": 0.050,
        "within_p95_ceiling": p95_seconds <= 0.050,
        "peak_allocated_bytes": peak_bytes,
        "peak_allocation_ceiling_bytes": 32 * 1024 * 1024,
        "within_peak_allocation_ceiling": peak_bytes < 32 * 1024 * 1024,
        "projected_ir_size_bytes": projected_size,
        "projected_ir_size_ceiling_bytes": semantics.MAX_REPORT_BYTES,
        "within_projected_ir_size_ceiling": (
            projected_size <= semantics.MAX_REPORT_BYTES
        ),
        "run_count": len(projected.text_runs),
        "rule_count": len(projected.text_rules),
        "semantic_deterministic": len(semantic_digests) == 1,
        "predecessor_unmodified": (
            predecessor.model_dump(mode="json") == predecessor_payload
        ),
        "repeated_projection_idempotent": (
            repeated.model_dump(mode="json")
            == projected.model_dump(mode="json")
        ),
        **HOSTED_USAGE,
    }


_PAGE_WIDTH = 300.0
_PAGE_HEIGHT = 300.0


def _pdf_literal(value: str) -> bytes:
    return (
        value.encode("latin-1")
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def _color_command(color: tuple[float, ...]) -> bytes:
    operator = b"g" if len(color) == 1 else b"rg"
    components = " ".join(f"{value:.15g}" for value in color).encode()
    return components + b" " + operator


def _text_command(
    text: str,
    *,
    x: float,
    baseline_y: float,
    color: tuple[float, ...],
) -> bytes:
    return b"\n".join(
        (
            _color_command(color),
            (
                f"BT /F1 12 Tf 1 0 0 1 {x:.8g} {baseline_y:.8g} Tm ".encode()
                + b"("
                + _pdf_literal(text)
                + b") Tj ET"
            ),
        )
    )


def _rect_command(
    *,
    x: float,
    bottom_y: float,
    width: float,
    height: float,
    color: tuple[float, ...],
) -> bytes:
    return b"\n".join(
        (
            _color_command(color),
            (
                f"{x:.15g} {bottom_y:.15g} {width:.15g} "
                f"{height:.15g} re f"
            ).encode(),
        )
    )


def _pdf_bytes(commands: Iterable[bytes]) -> bytes:
    content = b"\n".join(commands)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(payload)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _first_word_bbox(pdf_bytes: bytes) -> dict[str, float]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        word = document.pages[0].extract_words()[0]
    return {
        "x": float(word["x0"]),
        "y": float(word["top"]),
        "width": float(word["x1"]) - float(word["x0"]),
        "height": float(word["bottom"]) - float(word["top"]),
    }


@lru_cache(maxsize=2)
def _limit_fixture(rule_count: int) -> bytes:
    color = (1.0, 0.0, 0.0)
    text = _text_command(
        "M",
        x=40.0,
        baseline_y=150.0,
        color=color,
    )
    bbox = _first_word_bbox(_pdf_bytes((text,)))
    rules: list[bytes] = []
    for index in range(rule_count):
        ratio = 0.36 + 0.32 * index / max(rule_count - 1, 1)
        center_top = bbox["y"] + ratio * bbox["height"]
        center_pdf_y = _PAGE_HEIGHT - center_top
        rules.append(
            _rect_command(
                x=bbox["x"],
                bottom_y=center_pdf_y - 0.005,
                width=bbox["width"],
                height=0.01,
                color=color,
            )
        )
    return _pdf_bytes((text, *rules))


def generate_boundary_metrics() -> dict[str, Any]:
    exact_bytes = _limit_fixture(semantics.MAX_RULES_PER_RUN)
    overflow_bytes = _limit_fixture(semantics.MAX_RULES_PER_RUN + 1)
    semantics.extract_text_run_evidence(exact_bytes, max_pages=1)
    started = time.perf_counter()
    exact = semantics.extract_text_run_evidence(
        exact_bytes,
        max_pages=1,
    )
    elapsed_seconds = time.perf_counter() - started
    overflow_started = time.perf_counter()
    overflow = semantics.extract_text_run_evidence(
        overflow_bytes,
        max_pages=1,
    )
    overflow_elapsed_seconds = time.perf_counter() - overflow_started
    overflow_page = overflow.pages[0] if len(overflow.pages) == 1 else None
    exact_rule_links = (
        len(exact.runs[0].rule_ids)
        if exact.usable and len(exact.runs) == 1
        else 0
    )
    return {
        "boundary": "maximum_rules_per_run",
        "exact_maximum": semantics.MAX_RULES_PER_RUN,
        "maximum_plus_one": semantics.MAX_RULES_PER_RUN + 1,
        "exact_fixture_sha256": _sha256_bytes(exact_bytes),
        "maximum_plus_one_fixture_sha256": _sha256_bytes(overflow_bytes),
        "exact_usable": exact.usable,
        "exact_rule_link_count": exact_rule_links,
        "exact_completed": (
            exact.usable
            and exact_rule_links == semantics.MAX_RULES_PER_RUN
        ),
        "elapsed_seconds": round(elapsed_seconds, 9),
        "ceiling_seconds": 0.250,
        "within_ceiling": elapsed_seconds <= 0.250,
        "maximum_plus_one_usable": overflow.usable,
        "maximum_plus_one_refusal_code": overflow.refusal_code,
        "maximum_plus_one_page_status": (
            overflow_page.status if overflow_page is not None else None
        ),
        "maximum_plus_one_page_concern_code": (
            overflow_page.concern_code
            if overflow_page is not None
            else None
        ),
        "maximum_plus_one_run_count": len(overflow.runs),
        "maximum_plus_one_rule_count": len(overflow.rules),
        "maximum_plus_one_elapsed_seconds": round(
            overflow_elapsed_seconds,
            9,
        ),
        "maximum_plus_one_within_ceiling": (
            overflow_elapsed_seconds <= 0.250
        ),
        "maximum_plus_one_failed_closed": (
            overflow.usable
            and overflow.refusal_code is None
            and overflow_page is not None
            and overflow_page.status == "unavailable"
            and overflow_page.concern_code == "text_run_rule_limit"
            and not overflow.runs
            and not overflow.rules
        ),
        **HOSTED_USAGE,
    }


def _paired_states(pair_index: int) -> tuple[bool, bool]:
    return (False, True) if pair_index % 2 == 0 else (True, False)


def _paired_performance_summary(
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(off_samples) != len(on_samples) or len(off_samples) < 5:
        raise ValueError("paired parser performance requires at least 5 pairs")
    signed = [
        float(on["wall_seconds"]) - float(off["wall_seconds"])
        for off, on in zip(off_samples, on_samples, strict=True)
    ]
    clipped = [max(value, 0.0) for value in signed]
    predecessor_samples = [
        float(sample["wall_seconds"]) for sample in off_samples
    ]
    predecessor_p95 = _percentile95(predecessor_samples)
    five_percent_ceiling = predecessor_p95 * 0.05
    absolute_ceiling = 0.309
    effective_ceiling = min(five_percent_ceiling, absolute_ceiling)
    p95_signed = _percentile95(signed)
    p95_clipped = _percentile95(clipped)
    return {
        "pair_count": len(signed),
        "execution_order_alternated": True,
        "process_model": "fresh_process_per_flag_state",
        "cache_state": (
            "operating-system caches were not explicitly flushed"
        ),
        "quantile_method": "empirical_p95_inclusive",
        "gate_value": "p95_of_clipped_nonnegative_paired_overhead",
        "flag_off_wall_seconds": predecessor_samples,
        "flag_on_wall_seconds": [
            float(sample["wall_seconds"]) for sample in on_samples
        ],
        "paired_signed_wall_seconds_deltas": [
            round(value, 6) for value in signed
        ],
        "paired_nonnegative_overhead_seconds": [
            round(value, 6) for value in clipped
        ],
        "p50_signed_delta_seconds": round(statistics.median(signed), 6),
        "p95_signed_delta_seconds": round(p95_signed, 6),
        "max_signed_delta_seconds": round(max(signed), 6),
        "p50_nonnegative_overhead_seconds": round(
            statistics.median(clipped),
            6,
        ),
        "p95_nonnegative_overhead_seconds": round(p95_clipped, 6),
        "max_nonnegative_overhead_seconds": round(max(clipped), 6),
        "current_paired_predecessor_p95_seconds": round(
            predecessor_p95,
            6,
        ),
        "five_percent_ceiling_seconds": round(
            five_percent_ceiling,
            6,
        ),
        "absolute_ceiling_seconds": absolute_ceiling,
        "effective_ceiling_seconds": round(effective_ceiling, 6),
        "within_five_percent_ceiling": (
            p95_clipped <= five_percent_ceiling
        ),
        "within_absolute_ceiling": p95_clipped <= absolute_ceiling,
        "within_both_ceilings": p95_clipped <= effective_ceiling,
        "m0_reference": deepcopy(M0_REFERENCE),
        **HOSTED_USAGE,
    }


def _memory_guard_summary(
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if len(off_samples) != len(on_samples) or len(off_samples) < 5:
        raise ValueError("memory guard requires at least 5 fresh pairs")
    off_rss = [int(sample["peak_rss_bytes"]) for sample in off_samples]
    on_rss = [int(sample["peak_rss_bytes"]) for sample in on_samples]
    deltas = [
        on - off for off, on in zip(off_rss, on_rss, strict=True)
    ]
    return {
        "case": MEMORY_GUARD_CASE,
        "pair_count": len(off_rss),
        "execution_order_alternated": True,
        "process_model": "fresh_process_per_flag_state",
        "peak_rss_semantics": "worker_process_high_water_mark",
        "flag_off_peak_rss_bytes": off_rss,
        "flag_on_peak_rss_bytes": on_rss,
        "paired_peak_rss_bytes_deltas": deltas,
        "max_flag_on_peak_rss_bytes": max(on_rss),
        "all_measurements_positive": all(
            value > 0 for value in (*off_rss, *on_rss)
        ),
        **HOSTED_USAGE,
    }


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(payload))
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _iter_items(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for page in payload.get("pages", ()):
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items", ()):
            if isinstance(item, Mapping):
                yield item


def _public_page(
    payload: Mapping[str, Any],
    page_index: int,
) -> Mapping[str, Any]:
    matches = [
        page
        for page in payload.get("pages", ())
        if isinstance(page, Mapping)
        and page.get("page_index") == page_index
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one public page at index {page_index}"
        )
    return matches[0]


def _public_item(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> Mapping[str, Any]:
    matches = [
        item
        for item in _public_page(payload, page_index).get("items", ())
        if isinstance(item, Mapping) and item.get("id") == item_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one public item {item_id} on page {page_index}"
        )
    return matches[0]


def _public_target(
    item: Mapping[str, Any],
    path: Iterable[str | int],
) -> str:
    target: Any = item
    for component in path:
        if isinstance(component, int):
            if not isinstance(target, list):
                raise ValueError("target path index does not select a list")
            target = target[component]
        else:
            if not isinstance(target, Mapping):
                raise ValueError("target path key does not select a mapping")
            target = target[component]
    if not isinstance(target, str):
        raise ValueError("target path did not resolve to text")
    return target


def _purchase_source_sequence_metrics(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    page = _public_page(payload, 1)
    raw_items = page.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("purchase page items are unavailable")
    items = [
        item for item in raw_items if isinstance(item, Mapping)
    ]
    positions = {
        str(item.get("id")): position
        for position, item in enumerate(items)
    }
    if len(positions) != len(items):
        raise ValueError("purchase page item ids are not unique")

    grouped: dict[
        str,
        list[tuple[int, Mapping[str, Any], Mapping[str, Any]]],
    ] = {}
    for position, item in enumerate(items):
        for run in item.get("text_runs", ()):
            if (
                isinstance(run, Mapping)
                and run.get("change_state") == "deleted"
                and isinstance(run.get("change_group_id"), str)
            ):
                grouped.setdefault(
                    str(run["change_group_id"]),
                    [],
                ).append((position, item, run))

    events: list[dict[str, Any]] = []
    for group_id, records in grouped.items():
        item_positions = {position for position, _item, _run in records}
        paths = {
            tuple(run.get("target_path", ()))
            for _position, _item, run in records
        }
        if len(item_positions) != 1 or len(paths) != 1:
            raise ValueError(
                f"deleted group {group_id} spans multiple targets"
            )
        position, item, first_run = records[0]
        target_path = tuple(first_run.get("target_path", ()))
        target = _public_target(item, target_path)
        start = min(int(run["start"]) for _p, _i, run in records)
        end = max(int(run["end"]) for _p, _i, run in records)
        text_value = " ".join(target[start:end].split())
        if text_value in {
            expected_text
            for kind, expected_text in PURCHASE_SOURCE_SEQUENCE
            if kind == "deleted"
        }:
            if target_path != ("value",):
                raise ValueError(
                    "purchase deleted source-sequence group is not scalar"
                )
            events.append(
                {
                    "locator": [position, start],
                    "observed": ["deleted", text_value],
                    "item_id": str(item.get("id")),
                    "target_path": list(target_path),
                    "start": start,
                    "end": end,
                }
            )

    for _kind, item_id in PURCHASE_SOURCE_SEQUENCE:
        if _kind != "item":
            continue
        item = _public_item(payload, 1, item_id)
        item_value = item.get("value")
        if not isinstance(item_value, str):
            raise ValueError(
                f"purchase source-sequence item lacks text: {item_id}"
            )
        match_kind, expected_text = PURCHASE_STABLE_ITEM_TEXT[item_id]
        text_matched = (
            item_value == expected_text
            if match_kind == "exact"
            else item_value.startswith(expected_text)
        )
        if not text_matched:
            raise ValueError(
                f"purchase source-sequence item text changed: {item_id}"
            )
        events.append(
            {
                "locator": [positions[item_id], 0],
                "observed": ["item", item_id],
                "item_id": item_id,
                "target_path": ["value"],
                "start": 0,
                "end": len(item_value),
                "text_match_kind": match_kind,
                "expected_text": expected_text,
                "source_text": item_value,
                "source_text_sha256": _sha256_bytes(
                    item_value.encode("utf-8")
                ),
            }
        )

    events.sort(key=lambda event: tuple(event["locator"]))
    observed = tuple(
        tuple(event["observed"]) for event in events
    )
    locators = [tuple(event["locator"]) for event in events]
    strictly_ordered = all(
        current > previous
        for previous, current in zip(locators, locators[1:])
    )
    exact = (
        len(events) == len(PURCHASE_SOURCE_SEQUENCE)
        and observed == PURCHASE_SOURCE_SEQUENCE
        and strictly_ordered
    )
    return {
        "expected_count": len(PURCHASE_SOURCE_SEQUENCE),
        "observed_count": len(events),
        "expected": deepcopy(PURCHASE_SOURCE_SEQUENCE),
        "observed": deepcopy(observed),
        "entries": events,
        "strictly_ordered": strictly_ordered,
        "exact": exact,
    }


def _public_run_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    runs: list[Mapping[str, Any]] = []
    items_with_projection = 0
    for item in _iter_items(payload):
        item_runs = item.get("text_runs")
        if isinstance(item_runs, list):
            items_with_projection += 1
            runs.extend(
                run for run in item_runs if isinstance(run, Mapping)
            )
    deleted = [run for run in runs if run.get("change_state") == "deleted"]
    group_rule_edges = {
        (str(run.get("change_group_id")), str(rule_id))
        for run in deleted
        for rule_id in run.get("rule_ids", ())
    }
    inserted_or_replacement = [
        run
        for run in runs
        if run.get("change_state") in {"inserted", "replacement"}
    ]
    blue = [
        run
        for run in runs
        if run.get("text") in {"EXECUTION VERSION", "_______"}
    ]
    false_deletion_controls = {
        text: any(
            run.get("text") == text
            and run.get("change_state") == "deleted"
            for run in runs
        )
        for text in ("EXECUTION VERSION", "Background", "Exhibit A")
    }
    postal_italic = {
        str(run.get("text")): list(run.get("target_path", ()))
        for run in runs
        if run.get("italic") is True
        and run.get("text") in POSTAL_ITALIC_TARGETS
    }
    return {
        "item_count": sum(1 for _ in _iter_items(payload)),
        "items_with_projection": items_with_projection,
        "run_count": len(runs),
        "deleted_run_count": len(deleted),
        "deleted_logical_group_count": len(
            {
                str(run.get("change_group_id"))
                for run in deleted
                if run.get("change_group_id")
            }
        ),
        "deleted_group_rule_edge_count": len(group_rule_edges),
        "deleted_run_rule_link_count": sum(
            len(run.get("rule_ids", ())) for run in deleted
        ),
        "blue_run_count": len(blue),
        "blue_rule_link_count": sum(
            len(run.get("rule_ids", ())) for run in blue
        ),
        "inserted_or_replacement_count": len(inserted_or_replacement),
        "false_deletion_controls": false_deletion_controls,
        "postal_italic_targets": postal_italic,
        "active_projection_item_count": sum(
            "active_text" in item for item in _iter_items(payload)
        ),
    }


def _worker_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    source = _verified_source_bytes(workspace, case)
    extractor_calls = 0
    original_extractor = semantics.extract_text_run_evidence

    def counted_extractor(*args: Any, **kwargs: Any) -> Any:
        nonlocal extractor_calls
        extractor_calls += 1
        return original_extractor(*args, **kwargs)

    semantics.extract_text_run_evidence = counted_extractor
    started = time.perf_counter()
    try:
        result = parse_document(
            source,
            f"{case}.pdf",
            _settings(enabled),
        )
    finally:
        elapsed = time.perf_counter() - started
        semantics.extract_text_run_evidence = original_extractor
    payload = result.model_dump(mode="json", exclude_none=True)
    semantic_payload = _semantic_payload(payload)
    semantic_json = _canonical_json(semantic_payload).encode("utf-8")
    raw_json = _canonical_json(payload).encode("utf-8")
    markdown = to_markdown(payload).encode("utf-8")
    summary = _public_run_summary(payload)
    return {
        "case": case,
        "enabled": enabled,
        "input_identity": deepcopy(SOURCE_IDENTITIES[case]),
        "wall_seconds": round(elapsed, 6),
        "peak_rss_bytes": _rss_bytes(),
        "extractor_call_count": extractor_calls,
        "semantic_json_sha256": _sha256_bytes(semantic_json),
        "semantic_json_size_bytes": len(semantic_json),
        "raw_json_sha256": _sha256_bytes(raw_json),
        "raw_json_size_bytes": len(raw_json),
        "markdown_sha256": _sha256_bytes(markdown),
        "markdown_size_bytes": len(markdown),
        "text_run_summary": summary,
        "flag_off_projection_absent": (
            not enabled
            and extractor_calls == 0
            and summary["items_with_projection"] == 0
            and summary["run_count"] == 0
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
        "tests.benchmarks.text_run_semantics_metrics",
        "--workspace",
        str(workspace),
        "--worker-case",
        case,
        "--worker-enabled",
        "true" if enabled else "false",
        "--output",
        str(output),
    ]


def _fresh_snapshot(
    workspace: Path,
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=f"p03-us05-{case}-",
    ) as temporary_directory:
        output = Path(temporary_directory) / "snapshot.json"
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
                "fresh US05 metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def generate_paired_parser_metrics(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = 5,
) -> dict[str, Any]:
    if repeats < 5:
        raise ValueError("paired parser metrics require at least 5 repeats")
    paired: dict[str, Any] = {}
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
        paired[case] = {
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
            "flag_off_semantic_deterministic": (
                len(
                    {
                        sample["semantic_json_sha256"]
                        for sample in off_samples
                    }
                )
                == 1
            ),
            "flag_on_semantic_deterministic": (
                len(
                    {
                        sample["semantic_json_sha256"]
                        for sample in on_samples
                    }
                )
                == 1
            ),
        }
    return {
        "purchase_parser_budget": {
            **paired[PERFORMANCE_CASE],
            "paired_performance": _paired_performance_summary(
                paired[PERFORMANCE_CASE]["flag_off_samples"],
                paired[PERFORMANCE_CASE]["flag_on_samples"],
            ),
        },
        "uber_memory_guard": {
            **paired[MEMORY_GUARD_CASE],
            "memory_guard": _memory_guard_summary(
                paired[MEMORY_GUARD_CASE]["flag_off_samples"],
                paired[MEMORY_GUARD_CASE]["flag_on_samples"],
            ),
        },
    }


def _synthetic_fixture_custody() -> dict[str, Any]:
    fixture_contracts = {
        identifier: {
            "fixture_id": identifier,
            "policy_id": semantics.TEXT_RUN_POLICY_ID,
            "generator_path": (
                "tests/stories/phase_03/test_p03_us05_adversarial.py"
            ),
        }
        for identifier in SYNTHETIC_FIXTURE_IDS
    }
    fixture_contracts["synthetic:p03-us05:limits-v1"].update(
        {
            "exact_maximum": semantics.MAX_RULES_PER_RUN,
            "maximum_plus_one": semantics.MAX_RULES_PER_RUN + 1,
            "exact_source_sha256": _sha256_bytes(
                _limit_fixture(semantics.MAX_RULES_PER_RUN)
            ),
            "maximum_plus_one_source_sha256": _sha256_bytes(
                _limit_fixture(semantics.MAX_RULES_PER_RUN + 1)
            ),
        }
    )
    return {
        identifier: {
            "payload": payload,
            "payload_sha256": _sha256_bytes(
                _canonical_json(payload).encode("utf-8")
            ),
        }
        for identifier, payload in fixture_contracts.items()
    }


def _us04_artifact(workspace: Path) -> dict[str, Any]:
    path = workspace / US04_ARTIFACT_RELATIVE_PATH
    raw_sha256 = _sha256_file(path)
    if raw_sha256 != US04_ARTIFACT_RAW_SHA256:
        raise ValueError("sealed P03-US04 artifact raw digest changed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("semantic_sha256")
        != US04_ARTIFACT_SEMANTIC_SHA256
    ):
        raise ValueError("sealed P03-US04 semantic digest changed")
    return payload


def _predecessor_custody(workspace: Path) -> dict[str, Any]:
    path = workspace / US04_ARTIFACT_RELATIVE_PATH
    payload = _us04_artifact(workspace)
    aggregate = payload["aggregate"]
    return {
        "path": str(US04_ARTIFACT_RELATIVE_PATH),
        "size_bytes": path.stat().st_size,
        "raw_sha256": US04_ARTIFACT_RAW_SHA256,
        "semantic_sha256": payload["semantic_sha256"],
        "reviewed_pair_expected": aggregate["reviewed_pair_expected"],
        "reviewed_pair_matched": aggregate["reviewed_pair_matched"],
    }


def generate_relationship_order_retention(
    workspace: Path = WORKSPACE,
    *,
    preparsed_payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    sealed = _us04_artifact(workspace)
    oracle = sealed["oracle"]
    slices = oracle["slices"]
    nested = oracle["nested_pair"]
    case_order = list(
        dict.fromkeys(
            [
                str(slice_record[0])
                for slice_record in slices
            ]
            + [str(nested["case"])]
        )
    )
    if (
        len(case_order) != oracle["reviewed_case_count"]
        or len(slices) != oracle["slice_count"]
        or oracle["top_level_pair_count"] != 40
        or oracle["nested_pair_count"] != 1
        or oracle["fixed_pair_count"] != 41
    ):
        raise ValueError("sealed P03-US04 order oracle is inconsistent")

    parsed = dict(preparsed_payloads or {})
    source_custody: dict[str, Any] = {}
    case_results: dict[str, Any] = {}
    top_level_results: list[dict[str, Any]] = []
    for case in case_order:
        prior_custody = sealed["input_custody"][case]
        observed = prior_custody["observed"]
        source_path = workspace / observed["path"]
        current = {
            "path": observed["path"],
            "size_bytes": source_path.stat().st_size,
            "sha256": _sha256_file(source_path),
        }
        if (
            current != observed
            or current["size_bytes"]
            != prior_custody["expected"]["size_bytes"]
            or current["sha256"]
            != prior_custody["expected"]["sha256"]
        ):
            raise ValueError(
                f"P03-US04 reviewed source custody changed: {case}"
            )
        source_custody[case] = {
            "expected": deepcopy(observed),
            "observed": current,
            "exact_match": True,
        }
        payload = parsed.get(case)
        if payload is None:
            payload = parse_document(
                source_path.read_bytes(),
                source_path.name,
                _settings(True),
            ).model_dump(mode="json", exclude_none=True)
        parsed[case] = payload

        case_expected = 0
        case_matched = 0
        for slice_case, page_index, pairs in slices:
            if slice_case != case:
                continue
            page = _public_page(payload, int(page_index))
            items = page.get("items")
            if not isinstance(items, list):
                raise ValueError(f"page items are unavailable: {case}")
            positions = {
                str(item.get("id")): position
                for position, item in enumerate(items)
                if isinstance(item, Mapping)
            }
            if len(positions) != len(items):
                raise ValueError(f"page item ids are not unique: {case}")
            for before_id, after_id in pairs:
                before_position = positions.get(str(before_id))
                after_position = positions.get(str(after_id))
                matched = (
                    before_position is not None
                    and after_position is not None
                    and before_position < after_position
                )
                top_level_results.append(
                    {
                        "case": case,
                        "page_index": int(page_index),
                        "before_id": str(before_id),
                        "after_id": str(after_id),
                        "before_position": before_position,
                        "after_position": after_position,
                        "matched": matched,
                    }
                )
                case_expected += 1
                case_matched += int(matched)
        case_results[case] = {
            "top_level_expected": case_expected,
            "top_level_matched": case_matched,
        }
        gc.collect()

    nested_payload = parsed[str(nested["case"])]
    nested_owner = _public_item(
        nested_payload,
        int(nested["page_index"]),
        str(nested["owner_id"]),
    )
    nested_values = [
        str(child.get("value"))
        for child in nested_owner.get("items", ())
        if isinstance(child, Mapping)
    ]
    before_value = str(nested["before_value"])
    after_value = str(nested["after_value"])
    public_nested_matched = (
        nested_values.count(before_value) == 1
        and nested_values.count(after_value) == 1
        and nested_values.index(before_value)
        < nested_values.index(after_value)
    )
    nested_page = _public_page(
        nested_payload,
        int(nested["page_index"]),
    )
    nested_public_items = nested_page.get("items")
    if not isinstance(nested_public_items, list):
        raise ValueError("nested oracle public items are unavailable")
    nested_owner_position = [
        str(item.get("id"))
        for item in nested_public_items
        if isinstance(item, Mapping)
    ].index(str(nested["owner_id"]))
    canonical_pages = [
        page
        for page in nested_payload.get(
            "canonical_presentation",
            {},
        ).get("pages", ())
        if isinstance(page, Mapping)
        and page.get("page_index") == nested["page_index"]
    ]
    if len(canonical_pages) != 1:
        raise ValueError("nested oracle canonical page is unavailable")
    canonical_blocks = canonical_pages[0].get("blocks")
    if (
        not isinstance(canonical_blocks, list)
        or len(canonical_blocks) != len(nested_public_items)
    ):
        raise ValueError("nested oracle canonical blocks are inconsistent")
    canonical_owner = canonical_blocks[nested_owner_position]
    canonical_field_results: dict[str, bool] = {}
    for field in ("markdown", "text"):
        field_value = canonical_owner.get(field)
        canonical_field_results[field] = (
            isinstance(field_value, str)
            and field_value.count(before_value) == 1
            and field_value.count(after_value) == 1
            and field_value.index(before_value)
            < field_value.index(after_value)
        )
    nested_matched = public_nested_matched and all(
        canonical_field_results.values()
    )
    nested_result = {
        **deepcopy(nested),
        "observed_values": nested_values,
        "public_matched": public_nested_matched,
        "canonical_field_matched": canonical_field_results,
        "matched": nested_matched,
    }
    purchase_sequence = _purchase_source_sequence_metrics(
        parsed["purchase-agreement"]
    )
    top_level_matched = sum(
        int(result["matched"]) for result in top_level_results
    )
    total_matched = top_level_matched + int(nested_matched)
    all_pass = (
        len(top_level_results) == oracle["top_level_pair_count"]
        and top_level_matched == oracle["top_level_pair_count"]
        and nested_matched
        and total_matched == oracle["fixed_pair_count"]
        and purchase_sequence["exact"]
    )
    return {
        "oracle": {
            "path": str(US04_ARTIFACT_RELATIVE_PATH),
            "raw_sha256": US04_ARTIFACT_RAW_SHA256,
            "semantic_sha256": US04_ARTIFACT_SEMANTIC_SHA256,
            "reviewed_case_count": oracle["reviewed_case_count"],
            "slice_count": oracle["slice_count"],
        },
        "source_custody": source_custody,
        "cases": case_results,
        "top_level_results": top_level_results,
        "top_level_expected": oracle["top_level_pair_count"],
        "top_level_matched": top_level_matched,
        "nested_expected": oracle["nested_pair_count"],
        "nested_matched": int(nested_matched),
        "nested_result": nested_result,
        "total_expected": oracle["fixed_pair_count"],
        "total_matched": total_matched,
        "purchase_source_sequence": purchase_sequence,
        "all_pass": all_pass,
    }


def generate_control_metrics(
    workspace: Path = WORKSPACE,
    *,
    payloads_out: dict[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for case in ("purchase-agreement", "postal-10k", "finance-10k"):
        source = _verified_source_bytes(workspace, case)
        result = parse_document(
            source,
            f"{case}.pdf",
            _settings(True),
        )
        payload = result.model_dump(mode="json", exclude_none=True)
        if payloads_out is not None:
            payloads_out[case] = payload
        summaries[case] = {
            "summary": _public_run_summary(payload),
            "semantic_json_size_bytes": len(
                _canonical_json(_semantic_payload(payload)).encode("utf-8")
            ),
            "markdown_size_bytes": len(
                to_markdown(payload).encode("utf-8")
            ),
        }
    purchase = summaries["purchase-agreement"]["summary"]
    postal = summaries["postal-10k"]["summary"]
    finance = summaries["finance-10k"]["summary"]
    return {
        "cases": summaries,
        "matrix_results": {
            "target": {
                **CONTROL_MATRIX["target"],
                "pass": (
                    purchase["deleted_logical_group_count"] == 6
                    and purchase["deleted_group_rule_edge_count"] == 7
                    and purchase["deleted_run_rule_link_count"] == 9
                ),
            },
            "related_positive": {
                **CONTROL_MATRIX["related_positive"],
                "pass": (
                    postal["postal_italic_targets"]
                    == POSTAL_ITALIC_TARGETS
                ),
            },
            "non_target_regression": {
                **CONTROL_MATRIX["non_target_regression"],
                "pass": (
                    finance["inserted_or_replacement_count"] == 0
                    and finance["deleted_run_count"] == 0
                    and finance["run_count"] > 0
                ),
            },
            "negative_ambiguous_claim": {
                **CONTROL_MATRIX["negative_ambiguous_claim"],
                "pass": (
                    purchase["blue_run_count"] == 2
                    and purchase["inserted_or_replacement_count"] == 0
                ),
            },
        },
    }


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def generate_artifact(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = 5,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    predecessor, evidence = _projection_inputs()
    extraction = generate_extraction_metrics(
        _verified_source_bytes(workspace, PERFORMANCE_CASE)
    )
    projection = generate_projection_metrics(predecessor, evidence)
    boundary = generate_boundary_metrics()
    control_payloads: dict[str, Mapping[str, Any]] = {}
    controls = generate_control_metrics(
        workspace,
        payloads_out=control_payloads,
    )
    order_retention = generate_relationship_order_retention(
        workspace,
        preparsed_payloads=control_payloads,
    )
    paired = generate_paired_parser_metrics(workspace, repeats=repeats)
    purchase_performance = paired["purchase_parser_budget"][
        "paired_performance"
    ]
    purchase_summary = controls["cases"][PERFORMANCE_CASE]["summary"]
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "story": "P03-US05",
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement": {
            "performance_case": PERFORMANCE_CASE,
            "memory_guard_case": MEMORY_GUARD_CASE,
            "pair_count_per_case": repeats,
            "worker_process_count": repeats * 4,
            "execution_order": (
                "alternating off/on then on/off within paired indexes"
            ),
            "quantile_method": "empirical_p95_inclusive",
            "cache_disclaimer": (
                "operating-system caches were not explicitly flushed; "
                "no cold-cache claim is made"
            ),
            "timing_and_traced_allocation_measured_separately": True,
            **HOSTED_USAGE,
        },
        "policy": {
            "policy_id": semantics.TEXT_RUN_POLICY_ID,
            "extraction_policy_id": (
                semantics.TEXT_RUN_EXTRACTION_POLICY_ID
            ),
            "association_policy_id": (
                semantics.TEXT_RUN_ASSOCIATION_POLICY_ID
            ),
            "feature_flag": (
                "PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED"
            ),
            "default_enabled": False,
            "rollback_value": False,
            "source_extraction_p95_ceiling_seconds": 0.150,
            "source_extraction_peak_allocation_ceiling_bytes": (
                64 * 1024 * 1024
            ),
            "projection_p95_ceiling_seconds": 0.050,
            "projection_peak_allocation_ceiling_bytes": (
                32 * 1024 * 1024
            ),
            "maximum_boundary_ceiling_seconds": 0.250,
            "paired_absolute_ceiling_seconds": 0.309,
            "paired_percent_ceiling": 5.0,
            "maximum_report_bytes": semantics.MAX_REPORT_BYTES,
            "maximum_rules_per_run": semantics.MAX_RULES_PER_RUN,
            **HOSTED_USAGE,
        },
        "settings_delta": _settings_delta(),
        "m0_reference": deepcopy(M0_REFERENCE),
        "fixed_denominators": deepcopy(FIXED_DENOMINATORS),
        "input_custody": _source_custody(workspace),
        "control_matrix": controls,
        "relationship_order_retention": order_retention,
        "synthetic_fixture_custody": _synthetic_fixture_custody(),
        "predecessor_custody": _predecessor_custody(workspace),
        "code_sha256": _code_custody(workspace),
        "dependency_custody": _dependency_custody(workspace),
        "source_extraction": extraction,
        "association_projection": projection,
        "maximum_boundary": boundary,
        "paired_parser": paired,
        "output_sizes": {
            case: {
                key: value
                for key, value in metrics.items()
                if key.endswith("_size_bytes")
            }
            for case, metrics in controls["cases"].items()
        },
        "rollback": {
            "flag_off_extractor_count": sum(
                sample["extractor_call_count"]
                for sample in paired["purchase_parser_budget"][
                    "flag_off_samples"
                ]
            ),
            "flag_off_projection_absent": all(
                sample["flag_off_projection_absent"]
                for sample in paired["purchase_parser_budget"][
                    "flag_off_samples"
                ]
            ),
            "only_us05_setting_toggled": (
                _settings_delta()["changed_fields"]
                == ["layout_text_run_semantics_enabled"]
            ),
            "repeated_projection_idempotent": projection[
                "repeated_projection_idempotent"
            ],
        },
        "aggregate": {
            "deleted_logical_group_count": purchase_summary[
                "deleted_logical_group_count"
            ],
            "deleted_group_rule_edge_count": purchase_summary[
                "deleted_group_rule_edge_count"
            ],
            "deleted_run_rule_link_count": purchase_summary[
                "deleted_run_rule_link_count"
            ],
            "blue_run_count": purchase_summary["blue_run_count"],
            "blue_rule_link_count": purchase_summary[
                "blue_rule_link_count"
            ],
            "source_proven_inserted_replacement_count": (
                purchase_summary["inserted_or_replacement_count"]
            ),
            "false_deletion_count": sum(
                purchase_summary["false_deletion_controls"].values()
            ),
            "all_control_matrix_rows_pass": all(
                row["pass"]
                for row in controls["matrix_results"].values()
            ),
            "source_extraction_p95_within_150ms": extraction[
                "within_p95_ceiling"
            ],
            "source_extraction_peak_within_64mib": extraction[
                "within_peak_allocation_ceiling"
            ],
            "projection_p95_within_50ms": projection[
                "within_p95_ceiling"
            ],
            "projection_peak_within_32mib": projection[
                "within_peak_allocation_ceiling"
            ],
            "maximum_boundary_within_250ms": boundary[
                "within_ceiling"
            ],
            "maximum_plus_one_failed_closed": boundary[
                "maximum_plus_one_failed_closed"
            ],
            "maximum_plus_one_within_250ms": boundary[
                "maximum_plus_one_within_ceiling"
            ],
            "paired_parser_within_five_percent": purchase_performance[
                "within_five_percent_ceiling"
            ],
            "paired_parser_within_309ms": purchase_performance[
                "within_absolute_ceiling"
            ],
            "paired_parser_within_both_ceilings": (
                purchase_performance["within_both_ceilings"]
            ),
            "flag_off_extractor_count": 0,
            "idempotence": projection[
                "repeated_projection_idempotent"
            ],
            "purchase_source_sequence_expected": order_retention[
                "purchase_source_sequence"
            ]["expected_count"],
            "purchase_source_sequence_matched": order_retention[
                "purchase_source_sequence"
            ]["observed_count"]
            if order_retention["purchase_source_sequence"]["exact"]
            else 0,
            "relationship_order_retention_all_pass": order_retention[
                "all_pass"
            ],
            "predecessor_order_expected": order_retention[
                "total_expected"
            ],
            "predecessor_order_matched": order_retention[
                "total_matched"
            ],
            **HOSTED_USAGE,
        },
        **HOSTED_USAGE,
    }
    artifact["semantic_sha256"] = _sha256_bytes(
        _canonical_json(
            _artifact_semantic_payload(artifact)
        ).encode("utf-8")
    )
    return artifact


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workspace",
        type=Path,
        default=WORKSPACE,
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--worker-case", choices=PAIRED_CASES)
    parser.add_argument(
        "--worker-enabled",
        choices=("true", "false"),
    )
    arguments = parser.parse_args(argv)
    if arguments.worker_case is not None:
        if arguments.worker_enabled is None:
            parser.error(
                "--worker-enabled is required with --worker-case"
            )
        if arguments.output is None:
            parser.error("--output is required in worker mode")
    elif arguments.worker_enabled is not None:
        parser.error(
            "--worker-case is required with --worker-enabled"
        )
    return arguments


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse_args(argv)
    workspace = arguments.workspace.resolve()
    if arguments.worker_case is not None:
        output = _worker_snapshot(
            workspace,
            arguments.worker_case,
            arguments.worker_enabled == "true",
        )
        output_path = arguments.output
    else:
        output = generate_artifact(
            workspace,
            repeats=arguments.repeats,
        )
        output_path = (
            arguments.output
            if arguments.output is not None
            else workspace / DEFAULT_ARTIFACT_RELATIVE_PATH
        )
    if output_path is None:
        raise RuntimeError("metrics output path was not resolved")
    _write_json_atomic(output_path.resolve(), output)


if __name__ == "__main__":
    main()
