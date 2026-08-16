"""Retained quality and resource metrics for P03-US04."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import importlib.metadata as importlib_metadata
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
from typing import Any, Mapping, Sequence

from app.config import Settings
from app.services.ir import (
    DocumentIR,
    build_document_ir,
)
from app.services.layout import apply_layout_projection
from app.services.layout_order import project_relationship_order
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.regression.phase_03.test_p03_us04_real_reading_order import (
    CLEAN_SECTION,
    CLEAN_TITLE,
    CORPUS_SHA256,
    REVIEWED_PAIR_SLICES,
)


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
DEFAULT_ARTIFACT_RELATIVE_PATH = Path(
    "tracker/phase-03-layout/evidence/"
    "P03-US04-reading-order-metrics.json"
)
REVIEWED_CASES = tuple(CORPUS_SHA256)
PERFORMANCE_CASES = ("manufacturing-report", "uber-earnings")
ALL_CASES = (*REVIEWED_CASES, "uber-earnings")
EXPECTED_INPUTS: dict[str, dict[str, Any]] = {
    "catastrophe-recap": {
        "sha256": CORPUS_SHA256["catastrophe-recap"],
        "size_bytes": 58_779,
    },
    "clinical-study": {
        "sha256": CORPUS_SHA256["clinical-study"],
        "size_bytes": 750_004,
    },
    "component-datasheet": {
        "sha256": CORPUS_SHA256["component-datasheet"],
        "size_bytes": 329_199,
    },
    "esg-metrics": {
        "sha256": CORPUS_SHA256["esg-metrics"],
        "size_bytes": 60_516,
    },
    "manufacturing-report": {
        "sha256": CORPUS_SHA256["manufacturing-report"],
        "size_bytes": 380_274,
    },
    "purchase-agreement": {
        "sha256": CORPUS_SHA256["purchase-agreement"],
        "size_bytes": 152_828,
    },
    "ny-timetable": {
        "sha256": CORPUS_SHA256["ny-timetable"],
        "size_bytes": 26_109,
    },
    "clean-energy": {
        "sha256": CORPUS_SHA256["clean-energy"],
        "size_bytes": 122_014,
    },
    "finance-10k": {
        "sha256": CORPUS_SHA256["finance-10k"],
        "size_bytes": 87_105,
    },
    "uber-earnings": {
        "sha256": (
            "76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5"
        ),
        "size_bytes": 7_584_019,
    },
}
PHASE_02_PERFORMANCE_BASELINES = {
    "manufacturing-report": {
        "wall_seconds": 11.58,
        "five_percent_ceiling_seconds": 0.579,
        "peak_rss_mib": 1825.8,
    },
    "uber-earnings": {
        "wall_seconds": 29.15,
        "five_percent_ceiling_seconds": 1.4575,
        "peak_rss_mib": 2589.5,
    },
}
HOSTED_USAGE = {
    "hosted_requests": 0,
    "hosted_tokens": 0,
    "hosted_cost_usd": 0,
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
    "app/services/layout_order.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "app/services/source_text_alignment.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/lib/canonical-presentation.ts",
    "frontend/lib/normalize-document-json.ts",
    "frontend/lib/serialize-output.ts",
    "frontend/lib/types.ts",
    "frontend/package-lock.json",
    "frontend/tests/p03-us04-reading-order.test.mts",
    "tests/benchmarks/layout_reading_order_metrics.py",
    "tests/contract/test_p03_us04_reading_order_contract.py",
    "tests/performance/test_p03_us04_reading_order_performance.py",
    "tests/regression/phase_03/test_p03_us04_real_reading_order.py",
    "tests/stories/phase_03/test_p03_us04_adversarial.py",
    "tests/stories/phase_03/test_p03_us04_reading_order.py",
    "tracker/phase-03-layout/decisions/"
    "P03-relationship-order-policy.md",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
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


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=enabled,
    )


def _predecessor_settings() -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
    )


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(payload))
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _input_custody(
    workspace: Path,
    case: str,
) -> tuple[Path, bytes, dict[str, Any]]:
    source_path = workspace / "benchmark-expertmodeldata" / f"{case}.pdf"
    source_bytes = source_path.read_bytes()
    observed = {
        "path": f"benchmark-expertmodeldata/{case}.pdf",
        "size_bytes": len(source_bytes),
        "sha256": _sha256_bytes(source_bytes),
    }
    expected = EXPECTED_INPUTS[case]
    if (
        observed["size_bytes"] != expected["size_bytes"]
        or observed["sha256"] != expected["sha256"]
    ):
        raise ValueError(f"immutable benchmark input mismatch: {case}")
    return source_path, source_bytes, observed


def _all_input_custody(workspace: Path) -> dict[str, Any]:
    custody: dict[str, Any] = {}
    for case in ALL_CASES:
        _path, _source, observed = _input_custody(workspace, case)
        custody[case] = {
            "expected": deepcopy(EXPECTED_INPUTS[case]),
            "observed": observed,
            "exact_match": True,
        }
    return custody


def _code_custody(workspace: Path) -> dict[str, str]:
    custody: dict[str, str] = {}
    for relative_path in CODE_PATHS:
        path = workspace / relative_path
        if not path.is_file():
            raise ValueError(f"metrics code input is missing: {relative_path}")
        custody[relative_path] = _sha256_file(path)
    return custody


def _dependency_custody(
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    packages = {
        package: importlib_metadata.version(package)
        for package in (
            "docling",
            "docling-core",
            "pdfplumber",
            "pydantic",
        )
    }
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
        "python_packages": packages,
        "dependency_manifest_sha256": {
            relative_path: _sha256_file(workspace / relative_path)
            for relative_path in (
                "pyproject.toml",
                "uv.lock",
                "frontend/package-lock.json",
            )
        },
        "tesseract": {
            "path": str(executable),
            "version": completed.stdout.splitlines()[0].strip(),
            "sha256": _sha256_file(executable),
            "size_bytes": executable.stat().st_size,
        },
    }


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


def _paired_performance_summary(
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
    *,
    baseline_seconds: float,
    baseline_rss_mib: float,
) -> dict[str, Any]:
    if len(off_samples) != len(on_samples) or len(off_samples) < 5:
        raise ValueError("paired performance requires at least 5 pairs")
    signed_deltas = [
        float(on_sample["wall_seconds"])
        - float(off_sample["wall_seconds"])
        for off_sample, on_sample in zip(
            off_samples,
            on_samples,
            strict=True,
        )
    ]
    clipped = [max(delta, 0.0) for delta in signed_deltas]
    ceiling = round(baseline_seconds * 0.05, 4)
    p95_signed = _percentile95(signed_deltas)
    p95_clipped = _percentile95(clipped)
    return {
        "pair_count": len(signed_deltas),
        "execution_order_alternated": True,
        "process_model": "fresh_process_per_flag_state",
        "cache_state": (
            "operating-system caches were not explicitly flushed"
        ),
        "quantile_method": "empirical_p95_inclusive",
        "gate_value": "p95_of_clipped_nonnegative_paired_overhead",
        "flag_off_wall_seconds": [
            float(sample["wall_seconds"]) for sample in off_samples
        ],
        "flag_on_wall_seconds": [
            float(sample["wall_seconds"]) for sample in on_samples
        ],
        "paired_signed_wall_seconds_deltas": [
            round(value, 6) for value in signed_deltas
        ],
        "paired_nonnegative_overhead_seconds": [
            round(value, 6) for value in clipped
        ],
        "p50_signed_delta_seconds": round(
            statistics.median(signed_deltas),
            6,
        ),
        "p95_signed_delta_seconds": round(p95_signed, 6),
        "max_signed_delta_seconds": round(max(signed_deltas), 6),
        "p50_nonnegative_overhead_seconds": round(
            statistics.median(clipped),
            6,
        ),
        "p95_nonnegative_overhead_seconds": round(p95_clipped, 6),
        "max_nonnegative_overhead_seconds": round(max(clipped), 6),
        "phase_02_baseline_seconds": baseline_seconds,
        "five_percent_ceiling_seconds": ceiling,
        "p95_overhead_percent_of_baseline": round(
            p95_clipped / baseline_seconds * 100,
            4,
        ),
        "within_five_percent_ceiling": p95_clipped <= ceiling,
        "phase_02_peak_rss_baseline_mib": baseline_rss_mib,
        "flag_off_peak_rss_bytes": [
            int(sample["peak_rss_bytes"]) for sample in off_samples
        ],
        "flag_on_peak_rss_bytes": [
            int(sample["peak_rss_bytes"]) for sample in on_samples
        ],
        "paired_peak_rss_bytes_deltas": [
            int(on_sample["peak_rss_bytes"])
            - int(off_sample["peak_rss_bytes"])
            for off_sample, on_sample in zip(
                off_samples,
                on_samples,
                strict=True,
            )
        ],
    }


def _page(
    payload: Mapping[str, Any],
    page_index: int,
) -> Mapping[str, Any] | None:
    matches = [
        page
        for page in payload.get("pages") or []
        if page.get("page_index") == page_index
    ]
    return matches[0] if len(matches) == 1 else None


def _canonical_page(
    payload: Mapping[str, Any],
    page_index: int,
) -> Mapping[str, Any] | None:
    matches = [
        page
        for page in (
            payload.get("canonical_presentation", {}).get("pages") or []
        )
        if page.get("page_index") == page_index
    ]
    return matches[0] if len(matches) == 1 else None


def _detached(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _comparable_item(
    case: str,
    page_index: int,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    comparable = _detached(item)
    comparable.pop("reading_order", None)
    if (
        case == "clinical-study"
        and page_index == 1
        and item.get("id") == "p1-i14"
    ):
        comparable.pop("value", None)
        comparable.pop("md", None)
    if (
        case == "clean-energy"
        and page_index == 1
        and item.get("id") == "p1-i1"
    ):
        comparable.pop("value", None)
        comparable.pop("md", None)
        comparable.pop("items", None)
    return comparable


def _comparable_block(
    case: str,
    page_index: int,
    public_id: str,
    block: Mapping[str, Any],
) -> dict[str, Any]:
    comparable = _detached(block)
    if (
        case == "clinical-study"
        and page_index == 1
        and public_id == "p1-i14"
    ) or (
        case == "clean-energy"
        and page_index == 1
        and public_id == "p1-i1"
    ):
        comparable.pop("markdown", None)
        comparable.pop("text", None)
    if (
        case == "clean-energy"
        and page_index == 1
        and public_id == "p1-i1"
    ):
        for field in ("contributing_element_ids", "relationship_ids"):
            if isinstance(comparable.get(field), list):
                comparable[field] = sorted(comparable[field])
    return comparable


def _pair_quality(
    case: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for (
        oracle_case,
        page_index,
        pairs,
    ) in REVIEWED_PAIR_SLICES:
        if oracle_case != case:
            continue
        page = _page(payload, page_index)
        positions = (
            {
                str(item.get("id")): index
                for index, item in enumerate(page.get("items") or [])
            }
            if page is not None
            else {}
        )
        for before_id, after_id in pairs:
            results.append(
                {
                    "kind": "top_level",
                    "page_index": page_index,
                    "before_id": before_id,
                    "after_id": after_id,
                    "endpoints_present": (
                        before_id in positions and after_id in positions
                    ),
                    "matched": bool(
                        before_id in positions
                        and after_id in positions
                        and positions[before_id] < positions[after_id]
                    ),
                }
            )
    if case == "clean-energy":
        page = _page(payload, 1)
        owner_matches = (
            [
                item
                for item in page.get("items") or []
                if item.get("id") == "p1-i1"
            ]
            if page is not None
            else []
        )
        values = (
            [
                child.get("value")
                for child in owner_matches[0].get("items") or []
            ]
            if len(owner_matches) == 1
            else []
        )
        results.append(
            {
                "kind": "nested",
                "page_index": 1,
                "owner_id": "p1-i1",
                "before_value": CLEAN_TITLE,
                "after_value": CLEAN_SECTION,
                "endpoints_present": (
                    values.count(CLEAN_TITLE) == 1
                    and values.count(CLEAN_SECTION) == 1
                ),
                "matched": bool(
                    values.count(CLEAN_TITLE) == 1
                    and values.count(CLEAN_SECTION) == 1
                    and values.index(CLEAN_TITLE)
                    < values.index(CLEAN_SECTION)
                ),
            }
        )
    matched = sum(result["matched"] for result in results)
    return {
        "expected_pair_count": len(results),
        "matched_pair_count": matched,
        "all_pairs_matched": matched == len(results),
        "results": results,
    }


def _quality_snapshot(
    case: str,
    payload: Mapping[str, Any],
    markdown: str,
) -> dict[str, Any]:
    all_public_ids: list[str] = []
    keyed_items: dict[str, str] = {}
    keyed_blocks: dict[str, str] = {}
    canonical_primary_by_public: dict[str, str] = {}
    page_metadata_sha256: dict[str, str] = {}
    page_summaries: list[dict[str, Any]] = []
    contiguous = True
    canonical_order = True
    for public_page in payload.get("pages") or []:
        page_index = int(public_page["page_index"])
        public_items = list(public_page.get("items") or [])
        public_ids = [str(item.get("id") or "") for item in public_items]
        all_public_ids.extend(public_ids)
        ranks = [item.get("reading_order") for item in public_items]
        contiguous = contiguous and ranks == list(range(len(public_items)))
        canonical_page = _canonical_page(payload, page_index)
        blocks = (
            list(canonical_page.get("blocks") or [])
            if canonical_page is not None
            else []
        )
        canonical_order = canonical_order and (
            len(blocks) == len(public_items)
            and all(
                isinstance(block.get("primary_element_id"), str)
                and bool(block["primary_element_id"])
                for block in blocks
            )
        )
        primary_ids = [
            str(block.get("primary_element_id") or "")
            for block in blocks
        ]
        page_key = str(page_index)
        for item in public_items:
            public_id = str(item["id"])
            key = f"{page_index}:{public_id}"
            keyed_items[key] = _sha256_bytes(
                _canonical_json(
                    _comparable_item(
                        case,
                        page_index,
                        item,
                    )
                ).encode("utf-8")
            )
        for public_id, block in zip(
            public_ids,
            blocks,
            strict=False,
        ):
            key = f"{page_index}:{public_id}"
            primary_id = str(block.get("primary_element_id") or "")
            canonical_primary_by_public[key] = primary_id
            keyed_blocks[key] = _sha256_bytes(
                _canonical_json(
                    _comparable_block(
                        case,
                        page_index,
                        public_id,
                        block,
                    )
                ).encode("utf-8")
            )
        page_metadata = {
            key: value
            for key, value in public_page.items()
            if key != "items"
        }
        page_metadata_sha256[page_key] = _sha256_bytes(
            _canonical_json(page_metadata).encode("utf-8")
        )
        page_summaries.append(
            {
                "page_index": page_index,
                "public_item_ids": public_ids,
                "reading_order": ranks,
                "canonical_primary_element_ids": primary_ids,
                "canonical_block_count": len(blocks),
            }
        )
    canonical = payload.get("canonical_presentation") or {}
    canonical_markdown = str(
        canonical.get("full", {}).get("markdown") or ""
    )
    document_metadata = _detached(payload)
    document_metadata.pop("pages", None)
    document_metadata.pop("canonical_presentation", None)
    document_metadata.get("processing", {}).pop("duration_ms", None)
    serialized_payload = _canonical_json(payload)
    pair_quality = _pair_quality(case, payload)
    return {
        "pair_oracle": pair_quality,
        "public_item_count": len(all_public_ids),
        "duplicate_public_item_id_count": (
            len(all_public_ids) - len(set(all_public_ids))
        ),
        "reading_order_contiguous_all_pages": contiguous,
        "canonical_order_matches_public_all_pages": canonical_order,
        "markdown_equals_canonical_markdown": (
            markdown == canonical_markdown
        ),
        "keyed_item_sha256": keyed_items,
        "keyed_canonical_block_sha256": keyed_blocks,
        "canonical_primary_by_public_id": (
            canonical_primary_by_public
        ),
        "page_metadata_sha256": page_metadata_sha256,
        "document_metadata_sha256": _sha256_bytes(
            _canonical_json(document_metadata).encode("utf-8")
        ),
        "page_order": page_summaries,
        "rollback_projection_absent": (
            "relationship_order_" not in serialized_payload
            and "relationship_order_projection"
            not in serialized_payload
        ),
    }


def _snapshot(
    case: str,
    enabled: bool,
    workspace: Path,
) -> dict[str, Any]:
    source_path, source_bytes, input_identity = _input_custody(
        workspace,
        case,
    )
    settings = _settings(enabled)
    started = time.perf_counter()
    result = parse_document(
        source_bytes,
        source_path.name,
        settings,
    )
    wall_seconds = time.perf_counter() - started
    payload = result.model_dump(mode="json", exclude_none=False)
    serialized_json = _canonical_json(payload).encode("utf-8")
    semantic_json = _canonical_json(
        _semantic_payload(payload)
    ).encode("utf-8")
    markdown = to_markdown(payload)
    markdown_bytes = markdown.encode("utf-8")
    canonical_bytes = _canonical_json(
        payload.get("canonical_presentation") or {}
    ).encode("utf-8")
    return {
        "case": case,
        "enabled": enabled,
        "input_identity": input_identity,
        "wall_seconds": round(wall_seconds, 6),
        "processing_duration_ms": payload["processing"]["duration_ms"],
        "peak_rss_bytes": _rss_bytes(),
        "settings": {
            "layout_table_captions_enabled": (
                settings.layout_table_captions_enabled
            ),
            "layout_visual_relationships_enabled": (
                settings.layout_visual_relationships_enabled
            ),
            "layout_source_notes_enabled": (
                settings.layout_source_notes_enabled
            ),
            "layout_relationship_order_enabled": (
                settings.layout_relationship_order_enabled
            ),
            "canonical_serialization_enabled": (
                settings.canonical_serialization_enabled
            ),
        },
        "serialization": {
            "json_size_bytes": len(serialized_json),
            "json_sha256": _sha256_bytes(serialized_json),
            "semantic_json_size_bytes": len(semantic_json),
            "semantic_json_sha256": _sha256_bytes(semantic_json),
            "json_round_trip_equal": (
                json.loads(serialized_json) == payload
            ),
            "markdown_size_bytes": len(markdown_bytes),
            "markdown_sha256": _sha256_bytes(markdown_bytes),
            "canonical_size_bytes": len(canonical_bytes),
            "canonical_sha256": _sha256_bytes(canonical_bytes),
        },
        "quality": _quality_snapshot(case, payload, markdown),
        **HOSTED_USAGE,
    }


def _synthetic_document(
    anchor_count: int,
    *,
    overflow_secret: str | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for source_index in reversed(range(anchor_count)):
        value = (
            overflow_secret
            if source_index == anchor_count - 1
            and overflow_secret is not None
            else f"Anchor {source_index:03d}"
        )
        items.append(
            {
                "id": f"anchor-{source_index:03d}",
                "type": "text",
                "reading_order": len(items),
                "value": value,
                "md": value,
                "bbox": {
                    "x": 20.0,
                    "y": 10.0 + source_index * 12.0,
                    "width": 120.0,
                    "height": 8.0,
                    "unit": "pt",
                },
                "source": "native",
                "confidence": 0.99,
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "p03-us04-stage.pdf",
            "mime_type": "application/pdf",
            "sha256": hashlib.sha256(
                f"p03-us04-stage-{anchor_count}".encode("utf-8")
            ).hexdigest(),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 300.0,
                "page_height": anchor_count * 12.0 + 30.0,
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
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _synthetic_predecessor_ir(anchor_count: int) -> DocumentIR:
    ir = build_document_ir(_synthetic_document(anchor_count))
    return apply_layout_projection(ir, _settings(False))


def generate_stage_metrics() -> dict[str, Any]:
    predecessor = _synthetic_predecessor_ir(64)
    for _ in range(5):
        candidate = predecessor.model_copy(deep=True)
        project_relationship_order(candidate)

    samples: list[float] = []
    last_candidate = predecessor
    tracemalloc.start()
    for _ in range(100):
        started = time.perf_counter()
        candidate = predecessor.model_copy(deep=True)
        project_relationship_order(candidate)
        samples.append(time.perf_counter() - started)
        last_candidate = candidate
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    p95_seconds = _percentile95(samples)
    expected_ids = [
        f"anchor-{index:03d}" for index in range(64)
    ]
    return {
        "projection": "P03-US04_isolated_after_US01_US03_predecessor",
        "predecessor_flags": {
            "layout_table_captions_enabled": True,
            "layout_visual_relationships_enabled": True,
            "layout_source_notes_enabled": True,
            "layout_relationship_order_enabled": False,
        },
        "warmup_count": 5,
        "sample_count": 100,
        "anchor_count": 64,
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(p95_seconds, 9),
        "max_seconds": round(max(samples), 9),
        "min_seconds": round(min(samples), 9),
        "p95_ceiling_seconds": 0.050,
        "within_p95_ceiling": p95_seconds <= 0.050,
        "peak_allocated_bytes": peak_bytes,
        "peak_allocation_ceiling_bytes": 32 * 1024 * 1024,
        "within_peak_allocation_ceiling": (
            peak_bytes < 32 * 1024 * 1024
        ),
        "projected_ir_size_bytes": len(
            last_candidate.model_dump_json().encode("utf-8")
        ),
        "exact_order": (
            last_candidate.pages[0].presentation_element_ids
            == [
                next(
                    element.id
                    for element in last_candidate.elements
                    if element.properties.get("legacy_item", {}).get("id")
                    == public_id
                )
                for public_id in expected_ids
            ]
        ),
    }


def generate_boundary_metrics() -> dict[str, Any]:
    predecessor = _synthetic_predecessor_ir(512)
    started = time.perf_counter()
    candidate = predecessor.model_copy(deep=True)
    project_relationship_order(candidate)
    elapsed = time.perf_counter() - started
    public_ids_by_element = {
        element.id: element.properties.get("legacy_item", {}).get("id")
        for element in candidate.elements
    }
    observed_ids = [
        public_ids_by_element[element_id]
        for element_id in candidate.pages[0].presentation_element_ids
    ]
    expected_ids = [
        f"anchor-{index:03d}" for index in range(512)
    ]
    return {
        "anchor_count": 512,
        "anchor_limit": 512,
        "sample_count": 1,
        "elapsed_seconds": round(elapsed, 9),
        "ceiling_seconds": 0.250,
        "within_ceiling": elapsed <= 0.250,
        "exact_order": observed_ids == expected_ids,
        "unique_anchor_count": len(set(observed_ids)),
        "contiguous_reading_order": [
            next(
                element.reading_order
                for element in candidate.elements
                if element.id == element_id
            )
            for element_id in candidate.pages[0].presentation_element_ids
        ]
        == list(range(512)),
    }


def _without_concerns(ir: DocumentIR) -> dict[str, Any]:
    payload = ir.model_dump(mode="json")
    payload["concerns"] = []
    return payload


def generate_rollback_metrics() -> dict[str, Any]:
    secret = "PRIVATE P03 US04 ROLLBACK CONTENT"
    predecessor = build_document_ir(
        _synthetic_document(
            513,
            overflow_secret=secret,
        )
    )
    before = _without_concerns(predecessor)
    projected = predecessor.model_copy(deep=True)
    project_relationship_order(projected)
    after = _without_concerns(projected)
    concerns = [
        concern
        for concern in projected.concerns
        if concern.code.startswith("relationship_order_")
    ]
    serialized_concerns = _canonical_json(
        [
            concern.model_dump(mode="json")
            for concern in concerns
        ]
    )
    projected_twice = projected.model_copy(deep=True)
    project_relationship_order(projected_twice)
    return {
        "overflow_anchor_count": 513,
        "anchor_limit": 512,
        "exact_predecessor_restored": before == after,
        "concern_count": len(concerns),
        "concern_codes": [concern.code for concern in concerns],
        "concerns_sanitized": bool(
            concerns
            and secret not in serialized_concerns
            and all(
                concern.source_ref is None
                and concern.target_ref is None
                for concern in concerns
            )
        ),
        "repeated_projection_idempotent": (
            projected_twice == projected
        ),
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


def _worker_command(
    workspace: Path,
    case: str,
    enabled: bool,
    output: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "tests.benchmarks.layout_reading_order_metrics",
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
        prefix=f"p03-us04-{case}-",
    ) as temporary_directory:
        output = Path(temporary_directory) / "snapshot.json"
        completed = subprocess.run(
            _worker_command(
                workspace,
                case,
                enabled,
                output,
            ),
            cwd=workspace,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=330,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "fresh US04 metrics worker failed for "
                f"{case}/{enabled}: {completed.stderr[-4000:]}"
            )
        return json.loads(output.read_text(encoding="utf-8"))


def _paired_states(pair_index: int) -> tuple[bool, bool]:
    return (
        (False, True)
        if pair_index % 2 == 0
        else (True, False)
    )


def _sample_quality_valid(
    sample: Mapping[str, Any],
    *,
    require_oracle: bool,
) -> bool:
    quality = sample["quality"]
    serialization = sample["serialization"]
    return bool(
        serialization["json_round_trip_equal"]
        and quality["reading_order_contiguous_all_pages"]
        and quality["canonical_order_matches_public_all_pages"]
        and quality["markdown_equals_canonical_markdown"]
        and quality["duplicate_public_item_id_count"] == 0
        and (
            not require_oracle
            or quality["pair_oracle"]["all_pairs_matched"]
        )
        and sample["hosted_requests"] == 0
        and sample["hosted_tokens"] == 0
        and sample["hosted_cost_usd"] == 0
    )


def _case_quality_summary(
    case: str,
    off_samples: Sequence[Mapping[str, Any]],
    on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    off = off_samples[0]
    on = on_samples[0]
    off_quality = off["quality"]
    on_quality = on["quality"]
    keyed_items_equal = (
        on_quality["keyed_item_sha256"]
        == off_quality["keyed_item_sha256"]
    )
    keyed_blocks_equal = (
        on_quality["keyed_canonical_block_sha256"]
        == off_quality["keyed_canonical_block_sha256"]
    )
    canonical_identity_equal = (
        on_quality["canonical_primary_by_public_id"]
        == off_quality["canonical_primary_by_public_id"]
    )
    page_metadata_equal = (
        on_quality["page_metadata_sha256"]
        == off_quality["page_metadata_sha256"]
    )
    document_metadata_equal = (
        on_quality["document_metadata_sha256"]
        == off_quality["document_metadata_sha256"]
    )
    on_semantic_hashes = [
        sample["serialization"]["semantic_json_sha256"]
        for sample in on_samples
    ]
    off_semantic_hashes = [
        sample["serialization"]["semantic_json_sha256"]
        for sample in off_samples
    ]
    return {
        "json": {
            "all_flag_on_round_trip_equal": all(
                sample["serialization"]["json_round_trip_equal"]
                for sample in on_samples
            ),
            "all_flag_off_round_trip_equal": all(
                sample["serialization"]["json_round_trip_equal"]
                for sample in off_samples
            ),
            "flag_on_json_sha256": on["serialization"]["json_sha256"],
            "flag_off_json_sha256": off["serialization"]["json_sha256"],
            "flag_on_semantic_json_sha256": (
                on["serialization"]["semantic_json_sha256"]
            ),
            "flag_off_semantic_json_sha256": (
                off["serialization"]["semantic_json_sha256"]
            ),
            "keyed_items_equal_outside_accepted_corrections": (
                keyed_items_equal
            ),
            "page_metadata_exact": page_metadata_equal,
            "document_metadata_exact": document_metadata_equal,
        },
        "markdown": {
            "flag_on_sha256": on["serialization"]["markdown_sha256"],
            "flag_off_sha256": off["serialization"]["markdown_sha256"],
            "all_flag_on_matches_canonical": all(
                sample["quality"][
                    "markdown_equals_canonical_markdown"
                ]
                for sample in on_samples
            ),
            "all_flag_off_matches_canonical": all(
                sample["quality"][
                    "markdown_equals_canonical_markdown"
                ]
                for sample in off_samples
            ),
        },
        "canonical": {
            "flag_on_sha256": on["serialization"]["canonical_sha256"],
            "flag_off_sha256": off["serialization"]["canonical_sha256"],
            "keyed_blocks_equal_outside_accepted_corrections": (
                keyed_blocks_equal
            ),
            "primary_identity_by_public_id_exact": (
                canonical_identity_equal
            ),
            "all_flag_on_order_matches_public": all(
                sample["quality"][
                    "canonical_order_matches_public_all_pages"
                ]
                for sample in on_samples
            ),
            "all_flag_off_order_matches_public": all(
                sample["quality"][
                    "canonical_order_matches_public_all_pages"
                ]
                for sample in off_samples
            ),
        },
        "order": {
            "reviewed_pair_expected": on_quality[
                "pair_oracle"
            ]["expected_pair_count"],
            "reviewed_pair_matched": on_quality[
                "pair_oracle"
            ]["matched_pair_count"],
            "reviewed_pairs": on_quality["pair_oracle"]["results"],
            "all_flag_on_samples_match_oracle": all(
                sample["quality"]["pair_oracle"]["all_pairs_matched"]
                for sample in on_samples
            ),
            "all_flag_on_ranks_contiguous": all(
                sample["quality"][
                    "reading_order_contiguous_all_pages"
                ]
                for sample in on_samples
            ),
            "all_flag_on_ids_unique": all(
                sample["quality"]["duplicate_public_item_id_count"] == 0
                for sample in on_samples
            ),
            "flag_off_page_order": off_quality["page_order"],
            "flag_on_page_order": on_quality["page_order"],
        },
        "rollback": {
            "flag_off_settings_equal_exact_us03_predecessor": (
                _settings(False) == _predecessor_settings()
            ),
            "all_flag_off_samples_projection_absent": all(
                sample["quality"]["rollback_projection_absent"]
                for sample in off_samples
            ),
            "only_us04_setting_toggled": (
                _settings_delta()["changed_fields"]
                == ["layout_relationship_order_enabled"]
            ),
        },
        "all_keyed_mutation_within_policy": bool(
            keyed_items_equal
            and keyed_blocks_equal
            and canonical_identity_equal
            and page_metadata_equal
            and document_metadata_equal
        ),
        "all_flag_on_sample_quality_valid": all(
            _sample_quality_valid(sample, require_oracle=True)
            for sample in on_samples
        ),
        "all_flag_off_sample_quality_valid": all(
            _sample_quality_valid(sample, require_oracle=False)
            for sample in off_samples
        ),
        "flag_on_semantic_deterministic": len(
            set(on_semantic_hashes)
        )
        == 1,
        "flag_off_semantic_deterministic": len(
            set(off_semantic_hashes)
        )
        == 1,
        "finance_exact_semantic_flag_parity": (
            on["serialization"]["semantic_json_sha256"]
            == off["serialization"]["semantic_json_sha256"]
            if case == "finance-10k"
            else None
        ),
        "finance_exact_markdown_flag_parity": (
            on["serialization"]["markdown_sha256"]
            == off["serialization"]["markdown_sha256"]
            if case == "finance-10k"
            else None
        ),
    }


def _settings_delta() -> dict[str, Any]:
    off = asdict(_settings(False))
    on = asdict(_settings(True))
    changed = sorted(
        key for key in off if off[key] != on[key]
    )
    return {
        "changed_fields": changed,
        "flag_off": {
            key: off[key] for key in changed
        },
        "flag_on": {
            key: on[key] for key in changed
        },
        "accepted_predecessor_flags_enabled": all(
            getattr(_settings(False), field)
            for field in (
                "layout_table_captions_enabled",
                "layout_visual_relationships_enabled",
                "layout_source_notes_enabled",
            )
        ),
    }


def generate_artifact(
    workspace: Path = WORKSPACE,
    *,
    repeats: int = 5,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    if repeats < 5:
        raise ValueError("paired real performance requires at least 5 repeats")
    cases: dict[str, Any] = {}
    for case in ALL_CASES:
        pair_count = repeats if case in PERFORMANCE_CASES else 1
        off_samples: list[dict[str, Any]] = []
        on_samples: list[dict[str, Any]] = []
        execution_order: list[list[str]] = []
        for pair_index in range(pair_count):
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

        quality = _case_quality_summary(
            case,
            off_samples,
            on_samples,
        )
        case_record: dict[str, Any] = {
            "input": {
                "expected": deepcopy(EXPECTED_INPUTS[case]),
                "observed": deepcopy(
                    on_samples[0]["input_identity"]
                ),
                "exact_match": (
                    on_samples[0]["input_identity"]["sha256"]
                    == EXPECTED_INPUTS[case]["sha256"]
                    and on_samples[0]["input_identity"]["size_bytes"]
                    == EXPECTED_INPUTS[case]["size_bytes"]
                ),
            },
            "pair_count": pair_count,
            "execution_order": execution_order,
            "flag_off": off_samples[0],
            "flag_on": on_samples[0],
            "quality": quality,
            "sample_consistency": {
                "flag_off_semantic_sha256": [
                    sample["serialization"]["semantic_json_sha256"]
                    for sample in off_samples
                ],
                "flag_on_semantic_sha256": [
                    sample["serialization"]["semantic_json_sha256"]
                    for sample in on_samples
                ],
                "all_flag_off_quality_valid": all(
                    _sample_quality_valid(
                        sample,
                        require_oracle=False,
                    )
                    for sample in off_samples
                ),
                "all_flag_on_quality_valid": all(
                    _sample_quality_valid(
                        sample,
                        require_oracle=True,
                    )
                    for sample in on_samples
                ),
            },
        }
        if case in PERFORMANCE_CASES:
            baseline = PHASE_02_PERFORMANCE_BASELINES[case]
            case_record["paired_performance"] = (
                _paired_performance_summary(
                    off_samples,
                    on_samples,
                    baseline_seconds=baseline["wall_seconds"],
                    baseline_rss_mib=baseline["peak_rss_mib"],
                )
            )
        cases[case] = case_record

    top_level_pair_count = sum(
        len(pairs)
        for _case, _page_index, pairs in REVIEWED_PAIR_SLICES
    )
    expected_pair_count = top_level_pair_count + 1
    matched_pair_count = sum(
        cases[case]["quality"]["order"]["reviewed_pair_matched"]
        for case in REVIEWED_CASES
    )
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "story": "P03-US04",
        "generated_at": datetime.now(UTC).isoformat(),
        "measurement": {
            "quality_cases": list(REVIEWED_CASES),
            "performance_cases": list(PERFORMANCE_CASES),
            "performance_pair_count_per_case": repeats,
            "performance_worker_process_count": (
                len(PERFORMANCE_CASES) * repeats * 2
            ),
            "performance_execution_order": (
                "alternating off/on then on/off within paired indexes"
            ),
            "performance_quantile": (
                "empirical p95, statistics.quantiles inclusive method"
            ),
            "performance_gate_value": (
                "p95 of max(flag_on - flag_off, 0) paired overhead"
            ),
            "cache_disclaimer": (
                "operating-system caches were not explicitly flushed; "
                "no cold-cache claim is made"
            ),
            "peak_rss_semantics": (
                "per-worker parse-and-snapshot high-water mark"
            ),
            "layout_stage_isolated_from_full_parser": True,
            **HOSTED_USAGE,
        },
        "policy": {
            "feature_flag": (
                "PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED"
            ),
            "default_enabled": False,
            "rollback_value": False,
            "maximum_anchors_per_page": 512,
            "maximum_anchors_per_document": 65_536,
            "maximum_edges_per_page": 4096,
            "maximum_edges_per_document": 65_536,
            "maximum_references_per_anchor": 64,
            "maximum_prefix_candidates_per_page": 512,
            "maximum_prefix_comparisons_per_page": 65_536,
            "maximum_presentation_bytes_per_page": 1024 * 1024,
            "maximum_presentation_nodes_per_page": 65_536,
            "maximum_evidence_bytes_per_page": 1024 * 1024,
            "maximum_indexed_ir_records_per_collection": 262_144,
            "maximum_detailed_concerns_per_page": 16,
            "maximum_detailed_concerns_per_document": 256,
            **HOSTED_USAGE,
        },
        "settings_delta": _settings_delta(),
        "oracle": {
            "source": (
                "tests/regression/phase_03/"
                "test_p03_us04_real_reading_order.py"
            ),
            "reviewed_case_count": len(REVIEWED_CASES),
            "slice_count": len(REVIEWED_PAIR_SLICES),
            "top_level_pair_count": top_level_pair_count,
            "nested_pair_count": 1,
            "fixed_pair_count": expected_pair_count,
            "slices": _detached(REVIEWED_PAIR_SLICES),
            "nested_pair": {
                "case": "clean-energy",
                "page_index": 1,
                "owner_id": "p1-i1",
                "before_value": CLEAN_TITLE,
                "after_value": CLEAN_SECTION,
            },
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "dependency_custody": _dependency_custody(workspace),
        "input_custody": _all_input_custody(workspace),
        "code_sha256": _code_custody(workspace),
        "phase_02_performance_baselines": deepcopy(
            PHASE_02_PERFORMANCE_BASELINES
        ),
        "cases": cases,
        "layout_stage": generate_stage_metrics(),
        "maximum_boundary": generate_boundary_metrics(),
        "rollback": generate_rollback_metrics(),
        "aggregate": {
            "reviewed_pair_expected": expected_pair_count,
            "reviewed_pair_matched": matched_pair_count,
            "reviewed_pair_recall": (
                matched_pair_count / expected_pair_count
            ),
            "all_keyed_mutation_within_policy": all(
                cases[case]["quality"][
                    "all_keyed_mutation_within_policy"
                ]
                for case in REVIEWED_CASES
            ),
            "all_json_round_trip_exact": all(
                cases[case]["quality"]["json"][
                    "all_flag_on_round_trip_equal"
                ]
                and cases[case]["quality"]["json"][
                    "all_flag_off_round_trip_equal"
                ]
                for case in REVIEWED_CASES
            ),
            "all_markdown_matches_canonical": all(
                cases[case]["quality"]["markdown"][
                    "all_flag_on_matches_canonical"
                ]
                and cases[case]["quality"]["markdown"][
                    "all_flag_off_matches_canonical"
                ]
                for case in REVIEWED_CASES
            ),
            "all_canonical_order_matches_public": all(
                cases[case]["quality"]["canonical"][
                    "all_flag_on_order_matches_public"
                ]
                and cases[case]["quality"]["canonical"][
                    "all_flag_off_order_matches_public"
                ]
                for case in REVIEWED_CASES
            ),
            "all_flag_off_rollback_exact": all(
                cases[case]["quality"]["rollback"][
                    "all_flag_off_samples_projection_absent"
                ]
                for case in REVIEWED_CASES
            ),
            "performance_p95_within_five_percent": all(
                cases[case]["paired_performance"][
                    "within_five_percent_ceiling"
                ]
                for case in PERFORMANCE_CASES
            ),
            "stage_p95_within_50ms": None,
            "stage_peak_allocation_within_32mib": None,
            "maximum_boundary_within_250ms": None,
            "rollback_exact": None,
            "finance_exact_semantic_flag_parity": cases[
                "finance-10k"
            ]["quality"]["finance_exact_semantic_flag_parity"],
            "finance_exact_markdown_flag_parity": cases[
                "finance-10k"
            ]["quality"]["finance_exact_markdown_flag_parity"],
            **HOSTED_USAGE,
        },
    }
    artifact["aggregate"]["stage_p95_within_50ms"] = artifact[
        "layout_stage"
    ]["within_p95_ceiling"]
    artifact["aggregate"][
        "stage_peak_allocation_within_32mib"
    ] = artifact["layout_stage"]["within_peak_allocation_ceiling"]
    artifact["aggregate"][
        "maximum_boundary_within_250ms"
    ] = artifact["maximum_boundary"]["within_ceiling"]
    artifact["aggregate"]["rollback_exact"] = bool(
        artifact["rollback"]["exact_predecessor_restored"]
        and artifact["rollback"]["concerns_sanitized"]
        and artifact["rollback"]["repeated_projection_idempotent"]
    )
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
    parser.add_argument("--worker-case", choices=ALL_CASES)
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
        output = _snapshot(
            arguments.worker_case,
            arguments.worker_enabled == "true",
            workspace,
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
