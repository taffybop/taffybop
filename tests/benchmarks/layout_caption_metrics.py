"""Retained real-document and bounded-stage metrics for P03-US01."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.ir import round_trip_document
from app.services.layout import apply_layout_projection
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.regression.phase_03.test_p03_us01_real_benchmarks import (
    EXPECTED,
)
from tests.stories.phase_03.test_p03_us01_table_captions import (
    _box,
    _caption,
    _document,
    _enabled,
    _raw_graph,
    _table,
    _table_item,
)


WORKSPACE = Path(__file__).resolve().parents[2]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
PHASE_02_CATASTROPHE_SECONDS = 8.50
LAYOUT_OVERHEAD_CEILING_SECONDS = PHASE_02_CATASTROPHE_SECONDS * 0.05
CODE_PATHS = (
    ".env.example",
    "README.md",
    "app/config.py",
    "app/models.py",
    "app/services/ir.py",
    "app/services/layout.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "tests/stories/phase_03/test_p03_us01_table_captions.py",
    "tests/contract/test_p03_us01_table_caption_contract.py",
    "tests/benchmarks/layout_caption_metrics.py",
    "tests/regression/phase_03/test_p03_us01_real_benchmarks.py",
    "tests/performance/test_p03_us01_table_caption_performance.py",
    "tests/test_api.py",
    "frontend/lib/types.ts",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/app/globals.css",
    "frontend/README.md",
    "frontend/tests/p03-us01-table-captions.test.mts",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
        layout_table_captions_enabled=enabled,
    )


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    detached = json.loads(_canonical_json(payload))
    detached.get("processing", {}).pop("duration_ms", None)
    return detached


def _table_content(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "page_index": page["page_index"],
            "rows": item.get("rows"),
            "cells": item.get("cells"),
        }
        for page in payload["pages"]
        for item in page["items"]
        if item["type"] == "table"
    ]


def _caption_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for page in payload["pages"]:
        items_by_id = {
            item.get("id"): item
            for item in page["items"]
            if isinstance(item, dict)
        }
        for item in page["items"]:
            if item["type"] != "caption":
                continue
            owner = items_by_id.get(item.get("caption_of"))
            owner_linked_back = bool(
                isinstance(owner, dict)
                and owner.get("type") == "table"
                and item["id"] in (owner.get("caption_ids") or [])
                and item["id"] in (owner.get("caption_of") or [])
                and any(
                    isinstance(relationship, dict)
                    and relationship.get("id")
                    == item.get("relationship_id")
                    and relationship.get("type") == "caption_of"
                    and relationship.get("source_id") == item["id"]
                    and relationship.get("target_id") == owner.get("id")
                    for relationship in owner.get("relationships") or []
                )
            )
            records.append(
                {
                    "page_index": page["page_index"],
                    "id": item["id"],
                    "value": item["value"],
                    "bbox": item["bbox"],
                    "source": item.get("source"),
                    "confidence": item.get("confidence"),
                    "caption_of": item.get("caption_of"),
                    "relationship_id": item.get("relationship_id"),
                    "relationship_type": item.get("relationship_type"),
                    "relationship_basis": item.get("relationship_basis"),
                    "owner_linked_back": owner_linked_back,
                }
            )
    return records


def _parse_snapshot(case: str, enabled: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    path = CORPUS / f"{case}.pdf"
    source = path.read_bytes()
    started = time.perf_counter()
    result = parse_document(source, path.name, _settings(enabled))
    wall_seconds = time.perf_counter() - started
    payload = result.model_dump(mode="json", exclude_none=False)
    json_bytes = _canonical_json(payload).encode("utf-8")
    markdown_bytes = to_markdown(payload).encode("utf-8")
    return payload, {
        "enabled": enabled,
        "wall_seconds": round(wall_seconds, 6),
        "processing_duration_ms": payload["processing"]["duration_ms"],
        "peak_rss_bytes": _rss_bytes(),
        "json_size_bytes": len(json_bytes),
        "json_sha256": _sha256_bytes(json_bytes),
        "semantic_json_sha256": _sha256_bytes(
            _canonical_json(_semantic_payload(payload)).encode("utf-8")
        ),
        "markdown_size_bytes": len(markdown_bytes),
        "markdown_sha256": _sha256_bytes(markdown_bytes),
        "caption_records": _caption_records(payload),
        "table_content_sha256": _sha256_bytes(
            _canonical_json(_table_content(payload)).encode("utf-8")
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


def _parse_snapshot_fresh(
    case: str,
    enabled: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Measure one configuration in a new process with isolated max RSS."""

    with tempfile.TemporaryDirectory(
        prefix=f"p03-us01-{case}-",
    ) as temporary_directory:
        snapshot_path = Path(temporary_directory) / "snapshot.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.benchmarks.layout_caption_metrics",
                "--worker-case",
                case,
                "--worker-enabled",
                "true" if enabled else "false",
                "--output",
                str(snapshot_path),
            ],
            cwd=WORKSPACE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=330,
            check=False,
        )
        if completed.returncode != 0:
            diagnostic = completed.stderr[-4000:]
            raise RuntimeError(
                f"fresh metrics worker failed for {case}/"
                f"{enabled}: {diagnostic}"
            )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return snapshot["payload"], snapshot["metrics"]


def _caption_identity_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "page_index": record["page_index"],
            "value": record["value"],
            "bbox": {
                "x": record["bbox"]["x"],
                "y": record["bbox"]["y"],
                "width": record["bbox"]["width"],
                "height": record["bbox"]["height"],
            },
        }
        for record in records
    ]


def _expected_caption_identity_records(
    case: str,
) -> list[dict[str, Any]]:
    return [
        {
            "page_index": page_index,
            "value": value,
            "bbox": {
                "x": bbox[0],
                "y": bbox[1],
                "width": bbox[2],
                "height": bbox[3],
            },
        }
        for page_index, value, bbox in EXPECTED.get(case, [])
    ]


def _stage_metrics() -> dict[str, Any]:
    raw = _raw_graph(
        captions=[
            _caption("#/texts/0", "Caption", _box(10, 20, 55, 25))
        ],
        tables=[
            _table(
                "#/tables/0",
                ["#/texts/0"],
                box=_box(10, 30, 80, 60),
            )
        ],
    )
    _, ir = round_trip_document(
        _document(_table_item()),
        raw_graph=raw,
        native_texts=("Caption",),
    )
    for _ in range(5):
        apply_layout_projection(ir, _enabled())
    samples: list[float] = []
    tracemalloc.start()
    for _ in range(100):
        started = time.perf_counter()
        apply_layout_projection(ir, _enabled())
        samples.append(time.perf_counter() - started)
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ordered = sorted(samples)
    return {
        "warmup_count": 5,
        "sample_count": 100,
        "p50_seconds": round(statistics.median(samples), 9),
        "p95_seconds": round(
            statistics.quantiles(
                samples,
                n=100,
                method="inclusive",
            )[94],
            9,
        ),
        "max_seconds": round(max(samples), 9),
        "min_seconds": round(ordered[0], 9),
        "peak_allocated_bytes": peak_bytes,
        "phase_02_catastrophe_ceiling_seconds": (
            PHASE_02_CATASTROPHE_SECONDS
        ),
        "five_percent_ceiling_seconds": (
            LAYOUT_OVERHEAD_CEILING_SECONDS
        ),
    }


def generate_artifact() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for case in ("catastrophe-recap", "clinical-study", "finance-10k"):
        disabled_payload, disabled = _parse_snapshot_fresh(case, False)
        enabled_payload, enabled = _parse_snapshot_fresh(case, True)
        expected_records = _expected_caption_identity_records(case)
        actual_records = _caption_identity_records(
            enabled["caption_records"]
        )
        expected_keys = {
            _canonical_json(record)
            for record in expected_records
        }
        actual_keys = {
            _canonical_json(record)
            for record in actual_records
        }
        matched_caption_count = len(expected_keys & actual_keys)
        expected_texts = [
            record["value"] for record in expected_records
        ]
        actual_texts = [
            record["value"] for record in actual_records
        ]
        enabled_markdown = to_markdown(enabled_payload)
        cases[case] = {
            "input_path": f"benchmark-expertmodeldata/{case}.pdf",
            "input_size_bytes": (
                CORPUS / f"{case}.pdf"
            ).stat().st_size,
            "input_sha256": _sha256_file(CORPUS / f"{case}.pdf"),
            "expected_caption_count": len(expected_records),
            "expected_caption_records": expected_records,
            "expected_caption_texts": expected_texts,
            "actual_caption_count": len(actual_records),
            "actual_caption_records": actual_records,
            "actual_caption_texts": actual_texts,
            "matched_caption_count": matched_caption_count,
            "unexpected_caption_count": len(
                actual_keys - expected_keys
            ),
            "exact_caption_identities": (
                actual_records == expected_records
            ),
            "caption_recall": (
                matched_caption_count / len(expected_records)
                if expected_records
                else float(not actual_records)
            ),
            "caption_precision": (
                matched_caption_count / len(actual_records)
                if actual_records
                else float(not expected_records)
            ),
            "markdown_caption_occurrences": {
                text: enabled_markdown.count(text)
                for text in expected_texts
            },
            "table_content_equal": (
                enabled["table_content_sha256"]
                == disabled["table_content_sha256"]
            ),
            "semantic_flag_on_off_equal": (
                enabled["semantic_json_sha256"]
                == disabled["semantic_json_sha256"]
            ),
            "wall_seconds_delta": round(
                enabled["wall_seconds"] - disabled["wall_seconds"],
                6,
            ),
            "processing_duration_ms_delta": (
                enabled["processing_duration_ms"]
                - disabled["processing_duration_ms"]
            ),
            "peak_rss_bytes_delta": (
                enabled["peak_rss_bytes"]
                - disabled["peak_rss_bytes"]
            ),
            "json_size_bytes_delta": (
                enabled["json_size_bytes"]
                - disabled["json_size_bytes"]
            ),
            "flag_off": disabled,
            "flag_on": enabled,
        }

    caption_records = [
        record
        for value in cases.values()
        for record in value["flag_on"]["caption_records"]
    ]
    reviewed_caption_expected = sum(
        value["expected_caption_count"]
        for value in cases.values()
    )
    reviewed_caption_actual = sum(
        value["actual_caption_count"]
        for value in cases.values()
    )
    reviewed_caption_matched = sum(
        value["matched_caption_count"]
        for value in cases.values()
    )
    artifact: dict[str, Any] = {
        "schema_version": "1.0",
        "story": "P03-US01",
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": {
            "feature_flag": "PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED",
            "default_enabled": False,
            "rollback_value": False,
            "relationship_type": "caption_of",
            "minimum_horizontal_overlap": 0.20,
            "maximum_gap_points": 72.0,
            "maximum_internal_overlap": 0.20,
            "maximum_references_per_table": 64,
            "maximum_same_text_candidates_per_page": 128,
            "maximum_caption_candidates_per_page": 512,
            "physical_equivalence_overlap": 0.80,
            "raw_bbox_policy": "union_all_usable_same_page_provenance",
            "hosted_requests": 0,
            "hosted_tokens": 0,
            "hosted_cost_usd": 0,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "docling": importlib.metadata.version("docling"),
            "docling_core": importlib.metadata.version("docling-core"),
            "pydantic": importlib.metadata.version("pydantic"),
        },
        "measurement": {
            "full_parser_process_model": (
                "one fresh subprocess per case and flag state"
            ),
            "full_parser_cache_state": (
                "no in-process converter or model reuse between snapshots"
            ),
            "peak_rss_semantics": (
                "per-worker process-lifetime high-water mark"
            ),
            "full_parser_deltas_are_paired_process_snapshots": True,
            "layout_stage_isolated_from_full_parser": True,
        },
        "code_sha256": {
            path: _sha256_file(WORKSPACE / path)
            for path in CODE_PATHS
        },
        "cases": cases,
        "layout_stage": _stage_metrics(),
        "aggregate": {
            "reviewed_caption_expected": reviewed_caption_expected,
            "reviewed_caption_actual": reviewed_caption_actual,
            "reviewed_caption_matched": reviewed_caption_matched,
            "reviewed_caption_recall": (
                reviewed_caption_matched / reviewed_caption_expected
            ),
            "reviewed_caption_precision": (
                reviewed_caption_matched / reviewed_caption_actual
            ),
            "exact_caption_identities_all_cases": all(
                value["exact_caption_identities"]
                for value in cases.values()
            ),
            "duplicate_markdown_caption_count": sum(
                max(count - 1, 0)
                for value in cases.values()
                for count in value[
                    "markdown_caption_occurrences"
                ].values()
            ),
            "bbox_coverage": (
                sum(
                    isinstance(record.get("bbox"), dict)
                    and float(record["bbox"].get("width", 0)) > 0
                    and float(record["bbox"].get("height", 0)) > 0
                    for record in caption_records
                )
                / reviewed_caption_expected
            ),
            "relationship_coverage": (
                sum(
                    isinstance(record.get("caption_of"), str)
                    and bool(record["caption_of"])
                    and isinstance(record.get("relationship_id"), str)
                    and bool(record["relationship_id"])
                    and record.get("relationship_type") == "caption_of"
                    and record.get("relationship_basis")
                    == "graph_and_geometry"
                    and record.get("owner_linked_back") is True
                    for record in caption_records
                )
                / reviewed_caption_expected
            ),
            "table_content_equal_all_targets": all(
                value["table_content_equal"]
                for case, value in cases.items()
                if case in EXPECTED
            ),
            "finance_control_semantic_equal": cases[
                "finance-10k"
            ]["semantic_flag_on_off_equal"],
        },
    }
    semantic = {
        key: value
        for key, value in artifact.items()
        if key not in {"generated_at", "semantic_sha256"}
    }
    artifact["semantic_sha256"] = _sha256_bytes(
        _canonical_json(semantic).encode("utf-8")
    )
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--worker-case",
        choices=("catastrophe-recap", "clinical-study", "finance-10k"),
    )
    parser.add_argument(
        "--worker-enabled",
        choices=("true", "false"),
    )
    arguments = parser.parse_args()
    if arguments.worker_case is not None:
        if arguments.worker_enabled is None:
            parser.error("--worker-enabled is required with --worker-case")
        payload, metrics = _parse_snapshot(
            arguments.worker_case,
            arguments.worker_enabled == "true",
        )
        _write_json_atomic(
            arguments.output,
            {"payload": payload, "metrics": metrics},
        )
        return
    if arguments.worker_enabled is not None:
        parser.error("--worker-case is required with --worker-enabled")
    artifact = generate_artifact()
    _write_json_atomic(arguments.output, artifact)


if __name__ == "__main__":
    main()
