"""Custody and performance gate for the retained P03-US01 artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.regression.phase_03.test_p03_us01_real_benchmarks import (
    EXPECTED,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker"
    / "phase-03-layout"
    / "evidence"
    / "P03-US01-table-caption-metrics.json"
)
EXPECTED_ARTIFACT_SHA256 = (
    "98ccfb93b352dee0d01b5d614b1b298816ff80d817f1363fe27f682906f2857a"
)
P03_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/models.py",
        "app/services/ir.py",
        "app/services/layout.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/serializer.py",
        "frontend/README.md",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/app/globals.css",
        "frontend/lib/types.ts",
    }
)


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retained_metrics_bind_final_code_inputs_and_targets() -> None:
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    artifact = json.loads(raw)

    assert artifact["schema_version"] == "1.0"
    assert artifact["story"] == "P03-US01"
    assert artifact["measurement"] == {
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
    }
    # The sealed artifact still authenticates the exact at-run snapshots for
    # these files. Later Phase 03 stories own their current shared-code state
    # and bind it in their own retained artifacts.
    assert P03_SUCCESSOR_OWNED_INPUTS < set(artifact["code_sha256"])
    for relative, expected in artifact["code_sha256"].items():
        if relative in P03_SUCCESSOR_OWNED_INPUTS:
            continue
        assert _sha256(WORKSPACE / relative) == expected
    assert set(artifact["cases"]) == {
        "catastrophe-recap",
        "clinical-study",
        "finance-10k",
    }

    total_expected = 0
    total_actual = 0
    total_matched = 0
    duplicate_count = 0
    for case_name, case in artifact["cases"].items():
        source = WORKSPACE / case["input_path"]
        assert source.stat().st_size == case["input_size_bytes"]
        assert _sha256(source) == case["input_sha256"]
        expected_records = [
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
            for page_index, value, bbox in EXPECTED.get(case_name, [])
        ]
        actual_records = [
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
            for record in case["flag_on"]["caption_records"]
        ]
        assert case["expected_caption_records"] == expected_records
        assert case["actual_caption_records"] == actual_records
        assert actual_records == expected_records
        assert case["exact_caption_identities"] is True
        assert case["unexpected_caption_count"] == 0
        assert case["matched_caption_count"] == len(expected_records)
        assert case["caption_recall"] == 1.0
        assert case["caption_precision"] == 1.0
        assert case["flag_off"]["enabled"] is False
        assert case["flag_on"]["enabled"] is True
        assert case["flag_off"]["caption_records"] == []
        assert case["table_content_equal"] is True
        assert (
            case["flag_off"]["table_content_sha256"]
            == case["flag_on"]["table_content_sha256"]
        )
        for state in ("flag_off", "flag_on"):
            snapshot = case[state]
            assert snapshot["wall_seconds"] > 0
            assert snapshot["processing_duration_ms"] > 0
            assert snapshot["peak_rss_bytes"] > 0
            assert snapshot["json_size_bytes"] > 0
            assert snapshot["markdown_size_bytes"] >= 0
            assert len(snapshot["json_sha256"]) == 64
            assert len(snapshot["semantic_json_sha256"]) == 64
            assert len(snapshot["markdown_sha256"]) == 64
        for record in case["flag_on"]["caption_records"]:
            assert record["bbox"]["unit"] == "pt"
            assert record["source"] in {"native", "ocr", "mixed"}
            assert record["relationship_type"] == "caption_of"
            assert record["relationship_basis"] == "graph_and_geometry"
            assert record["relationship_id"].startswith("layout-rel-")
            assert record["owner_linked_back"] is True
        for expected_text in case["expected_caption_texts"]:
            occurrences = case["markdown_caption_occurrences"][
                expected_text
            ]
            assert occurrences == 1
            duplicate_count += max(occurrences - 1, 0)
        if expected_records:
            assert case["semantic_flag_on_off_equal"] is False
            assert (
                case["flag_off"]["semantic_json_sha256"]
                != case["flag_on"]["semantic_json_sha256"]
            )
        else:
            assert case_name == "finance-10k"
            assert case["semantic_flag_on_off_equal"] is True
            assert (
                case["flag_off"]["semantic_json_sha256"]
                == case["flag_on"]["semantic_json_sha256"]
            )
            assert (
                case["flag_off"]["markdown_sha256"]
                == case["flag_on"]["markdown_sha256"]
            )
        total_expected += len(expected_records)
        total_actual += len(actual_records)
        total_matched += case["matched_caption_count"]

    semantic = {
        key: value
        for key, value in artifact.items()
        if key not in {"generated_at", "semantic_sha256"}
    }
    assert hashlib.sha256(
        _canonical_json(semantic).encode("utf-8")
    ).hexdigest() == artifact["semantic_sha256"]

    aggregate = artifact["aggregate"]
    assert aggregate["reviewed_caption_expected"] == total_expected == 3
    assert aggregate["reviewed_caption_actual"] == total_actual == 3
    assert aggregate["reviewed_caption_matched"] == total_matched == 3
    assert aggregate["reviewed_caption_recall"] == 1.0
    assert aggregate["reviewed_caption_precision"] == 1.0
    assert aggregate["exact_caption_identities_all_cases"] is True
    assert aggregate["duplicate_markdown_caption_count"] == duplicate_count == 0
    assert aggregate["bbox_coverage"] == 1.0
    assert aggregate["relationship_coverage"] == 1.0
    assert aggregate["table_content_equal_all_targets"] is True
    assert aggregate["finance_control_semantic_equal"] is True


def test_retained_layout_stage_stays_below_five_percent_ceiling() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    stage = artifact["layout_stage"]

    assert stage["warmup_count"] == 5
    assert stage["sample_count"] == 100
    assert stage["p95_seconds"] <= stage["five_percent_ceiling_seconds"]
    assert stage["p95_seconds"] <= 0.050
    assert stage["peak_allocated_bytes"] <= 32 * 1024 * 1024
