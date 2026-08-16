"""Custody and performance gate for the retained P03-US02 artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tests.benchmarks.layout_visual_relationship_metrics import (
    CASES,
    CODE_PATHS,
    EXPECTED_INPUTS,
    PHASE_02_PERFORMANCE_BASELINES,
    UBER_FALSE_PHOTO_OCR,
    _canonical_json,
    _expected_caption_records,
    _relationship_summary,
)
from tests.regression.phase_03.test_p03_us02_real_visual_benchmarks import (
    EXPECTED_UBER_CONTAINED_VALUES,
    EXPECTED_UBER_CONTAINED_VALUE_SHA256,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker"
    / "phase-03-layout"
    / "evidence"
    / "P03-US02-visual-relationship-metrics.json"
)

# Set this only after the artifact is generated from the final reviewed code.
# Keeping the gate explicitly unarmed prevents a provisional run from being
# mistaken for retained evidence.
EXPECTED_ARTIFACT_SHA256: str | None = (
    "8fa4704412f75138f885b8b8a6c7b62053f2232f9ce1070f509df5ded12462d3"
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
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/layout-relationships.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/primary-item-text.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact() -> dict[str, Any]:
    assert EXPECTED_ARTIFACT_SHA256 is not None, (
        "P03-US02 retained artifact is not finalized"
    )
    assert ARTIFACT.is_file()
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    return json.loads(raw)


def _summary_payload(
    pages: list[dict[str, Any]],
    *,
    canonical_pages: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"pages": pages}
    if canonical_pages is not None:
        payload["canonical_presentation"] = {"pages": canonical_pages}
    return payload


def _empty_canonical_page(page_index: int) -> dict[str, Any]:
    return {"page_index": page_index, "blocks": []}


def test_relationship_summary_rejects_orphan_owner_backlinks() -> None:
    payload = _summary_payload(
        [
            {
                "page_index": 1,
                "items": [
                    {
                        "id": "visual-1",
                        "type": "image",
                        "caption_ids": ["ghost-caption"],
                        "contains_ids": ["ghost-child"],
                        "contained_items": [],
                        "relationships": [],
                    }
                ],
            }
        ],
        canonical_pages=[_empty_canonical_page(1)],
    )

    summary = _relationship_summary(payload)
    assert summary["caption_backlink_failure_count"] == 1
    assert summary["contains_backlink_failure_count"] == 1


def test_relationship_summary_rejects_duplicate_children_and_global_ids() -> None:
    child = {
        "id": "child-1",
        "type": "visual_text",
        "contained_by": "visual-1",
        "presentation_role": "subordinate",
        "relationship_id": "shared-relationship",
        "relationship_type": "contains",
    }
    pages = []
    for page_index in (1, 2):
        owner_id = f"visual-{page_index}"
        page_child = {**child, "contained_by": owner_id}
        pages.append(
            {
                "page_index": page_index,
                "items": [
                    {
                        "id": owner_id,
                        "type": "image",
                        "contains_ids": ["child-1", "child-1"],
                        "contained_items": [page_child, page_child],
                        "relationships": [
                            {
                                "id": "shared-relationship",
                                "type": "contains",
                                "source_id": owner_id,
                                "target_id": "child-1",
                            }
                        ],
                    }
                ],
            }
        )

    summary = _relationship_summary(
        _summary_payload(
            pages,
            canonical_pages=[
                _empty_canonical_page(1),
                _empty_canonical_page(2),
            ],
        )
    )
    assert summary["duplicate_contained_item_id_count"] == 2
    assert summary["duplicate_relationship_id_count"] == 1
    assert summary["contains_backlink_failure_count"] >= 2


def test_relationship_summary_rejects_cross_owner_child_id_reuse() -> None:
    owners = []
    for owner_index in (1, 2):
        owner_id = f"visual-{owner_index}"
        relationship_id = f"relationship-{owner_index}"
        owners.append(
            {
                "id": owner_id,
                "type": "image",
                "contains_ids": ["shared-child"],
                "contained_items": [
                    {
                        "id": "shared-child",
                        "type": "visual_text",
                        "contained_by": owner_id,
                        "presentation_role": "subordinate",
                        "relationship_id": relationship_id,
                        "relationship_type": "contains",
                    }
                ],
                "relationships": [
                    {
                        "id": relationship_id,
                        "type": "contains",
                        "source_id": owner_id,
                        "target_id": "shared-child",
                    }
                ],
            }
        )
    payload = _summary_payload(
        [{"page_index": 1, "items": owners}],
        canonical_pages=[_empty_canonical_page(1)],
    )

    summary = _relationship_summary(payload)
    assert summary["duplicate_contained_item_id_count"] == 1


def test_relationship_summary_requires_canonical_page_evidence() -> None:
    payload = _summary_payload(
        [{"page_index": 1, "items": []}],
        canonical_pages=None,
    )

    summary = _relationship_summary(payload)
    assert summary["missing_canonical_presentation_count"] == 1
    assert summary["missing_canonical_page_count"] == 1
    assert summary["missing_canonical_blocks_count"] == 1


def test_retained_metrics_bind_final_code_inputs_and_targets() -> None:
    artifact = _artifact()

    assert artifact["schema_version"] == "1.0"
    assert artifact["story"] == "P03-US02"
    assert artifact["measurement"] == {
        "full_parser_process_model": (
            "one fresh subprocess per case and flag state"
        ),
        "full_parser_cache_state": (
            "no in-process converter or model reuse between snapshots"
        ),
        "peak_rss_semantics": (
            "per-worker parse-and-snapshot high-water mark before "
            "evidence-file serialization"
        ),
        "full_parser_deltas_are_paired_process_snapshots": True,
        "layout_stage_isolated_from_full_parser": True,
    }
    assert artifact["phase_02_performance_baselines"] == (
        PHASE_02_PERFORMANCE_BASELINES
    )
    assert set(artifact["code_sha256"]) == set(CODE_PATHS)
    assert P03_SUCCESSOR_OWNED_INPUTS < set(artifact["code_sha256"])
    for relative, expected_sha256 in artifact["code_sha256"].items():
        # The sealed artifact authenticates these exact at-run snapshots.
        # Later Phase 03 stories own the current shared-code state and bind
        # their changes in successor artifacts.
        if relative in P03_SUCCESSOR_OWNED_INPUTS:
            continue
        path = WORKSPACE / relative
        assert path.is_file()
        assert _sha256(path) == expected_sha256

    assert set(artifact["cases"]) == set(CASES)
    total_expected = 0
    total_actual = 0
    total_matched = 0
    duplicate_count = 0
    for case_name in CASES:
        case = artifact["cases"][case_name]
        expected_input = EXPECTED_INPUTS[case_name]
        source = WORKSPACE / case["input_path"]
        assert (
            source.stat().st_size
            == case["input_size_bytes"]
            == expected_input["size_bytes"]
        )
        assert (
            _sha256(source)
            == case["input_sha256"]
            == expected_input["sha256"]
        )

        expected_records = _expected_caption_records(case_name)
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
                "owner_bbox": {
                    "x": record["owner_bbox"]["x"],
                    "y": record["owner_bbox"]["y"],
                    "width": record["owner_bbox"]["width"],
                    "height": record["owner_bbox"]["height"],
                },
                "side": record["side"],
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
            assert len(snapshot["table_content_sha256"]) == 64
            relationship_summary = snapshot["relationship_summary"]
            for metric in (
                "unresolved_endpoint_count",
                "duplicate_page_item_id_count",
                "duplicate_contained_item_id_count",
                "duplicate_relationship_id_count",
                "invalid_caption_relationship_count",
                "invalid_contains_relationship_count",
                "caption_backlink_failure_count",
                "contains_backlink_failure_count",
                "contained_semantics_failure_count",
                "contained_page_item_leak_count",
                "contained_canonical_primary_leak_count",
                "missing_canonical_presentation_count",
                "missing_canonical_page_count",
                "duplicate_canonical_page_index_count",
                "missing_canonical_blocks_count",
                "extra_canonical_page_count",
            ):
                assert relationship_summary[metric] == 0

        for record in case["flag_on"]["caption_records"]:
            assert record["bbox"]["unit"] == "pt"
            assert record["owner_bbox"]["unit"] == "pt"
            assert record["source"] in {"native", "ocr", "mixed"}
            assert record["owner_type"] in {"image", "chart", "diagram"}
            assert record["relationship_type"] == "caption_of"
            assert record["relationship_basis"] == "graph_and_geometry"
            assert record["relationship_id"].startswith("layout-rel-")
            assert record["owner_linked_back"] is True
            assert record["side"] in {"above", "below"}
            assert record["side_order_correct"] is True
            assert record["owner_external_text_clean"] is True

        for expected_text in case["expected_caption_texts"]:
            occurrences = case["markdown_caption_occurrences"][
                expected_text
            ]
            assert occurrences == 1
            duplicate_count += max(occurrences - 1, 0)

        if case_name == "finance-10k":
            assert case["semantic_flag_on_off_equal"] is True
            assert (
                case["flag_off"]["semantic_json_sha256"]
                == case["flag_on"]["semantic_json_sha256"]
            )
            assert (
                case["flag_off"]["markdown_sha256"]
                == case["flag_on"]["markdown_sha256"]
            )
        else:
            assert case["semantic_flag_on_off_equal"] is False
            assert (
                case["flag_off"]["semantic_json_sha256"]
                != case["flag_on"]["semantic_json_sha256"]
            )

        total_expected += len(expected_records)
        total_actual += len(actual_records)
        total_matched += case["matched_caption_count"]

    aggregate = artifact["aggregate"]
    assert aggregate["reviewed_caption_expected"] == total_expected == 5
    assert aggregate["reviewed_caption_actual"] == total_actual == 5
    assert aggregate["reviewed_caption_matched"] == total_matched == 5
    assert aggregate["reviewed_caption_recall"] == 1.0
    assert aggregate["reviewed_caption_precision"] == 1.0
    assert aggregate["exact_caption_identities_all_cases"] is True
    assert (
        aggregate["duplicate_markdown_caption_count"]
        == duplicate_count
        == 0
    )
    assert aggregate["caption_bbox_coverage"] == 1.0
    assert aggregate["caption_relationship_coverage"] == 1.0
    assert aggregate["side_order_coverage"] == 1.0
    assert aggregate["owner_external_text_clean_coverage"] == 1.0
    assert aggregate["unresolved_relationship_endpoint_count"] == 0
    assert aggregate["contained_page_item_leak_count"] == 0
    assert aggregate["contained_canonical_primary_leak_count"] == 0
    assert aggregate["caption_relationship_count"] == 5
    assert aggregate["contains_relationship_count"] >= 17
    assert aggregate["table_content_equal_all_cases"] is True


def test_retained_controls_are_source_grounded_and_fail_closed() -> None:
    artifact = _artifact()
    cases = artifact["cases"]

    catastrophe = cases["catastrophe-recap"]["flag_on"]["controls"]
    assert catastrophe["exact_exhibit_8_children"] is True
    assert (
        catastrophe["actual_exhibit_8_children"]
        == catastrophe["expected_exhibit_8_children"]
    )
    assert catastrophe["caption_fragment_leak_count"] == 0

    uber = cases["uber-earnings"]["flag_on"]["controls"]
    assert uber["photo_found"] is True
    assert uber["photo_bbox"] == {
        "x": 68.978,
        "y": 69.672,
        "width": 1781.229,
        "height": 522.914,
        "unit": "pt",
    }
    assert uber["include_ocr_in_primary"] is False
    assert uber["caption_fields_empty"] is True
    assert uber["linked_caption_count"] == 0
    assert uber["contained_item_count"] == 15
    assert set(uber["contained_values"]) == EXPECTED_UBER_CONTAINED_VALUES
    assert len(uber["contained_values"]) == len(
        set(uber["contained_values"])
    ) == 15
    assert (
        uber["contained_value_sha256"]
        == EXPECTED_UBER_CONTAINED_VALUE_SHA256
    )
    assert uber["contained_values_exact"] is True
    assert uber["contained_values_are_strict_source_subset"] is True
    assert uber["minimum_containment_ratio"] >= 0.80
    assert uber["false_ocr_value_coverage"] == (
        15 / len(UBER_FALSE_PHOTO_OCR)
    )
    assert uber["false_ocr_primary_leak_count"] == 0

    component = cases["component-datasheet"]["flag_on"]["controls"]
    assert component["photo_found"] is True
    assert component["source_caption_page_item_count"] == 1
    assert component["source_caption_unowned"] is True
    assert component["source_caption_markdown_count"] == 1
    assert component["invented_caption_link_count"] == 0

    finance = cases["finance-10k"]["flag_on"]["controls"]
    assert finance["visual_owner_count"] == 0
    assert finance["visual_caption_count"] == 0

    aggregate = artifact["aggregate"]
    assert aggregate["catastrophe_exact_children"] is True
    assert aggregate["catastrophe_caption_fragment_leak_count"] == 0
    assert aggregate["uber_false_ocr_primary_leak_count"] == 0
    assert aggregate["uber_false_ocr_value_coverage"] == (
        15 / len(UBER_FALSE_PHOTO_OCR)
    )
    assert (
        aggregate["uber_contained_value_sha256"]
        == EXPECTED_UBER_CONTAINED_VALUE_SHA256
    )
    assert aggregate["component_source_caption_count"] == 1
    assert aggregate["component_invented_caption_link_count"] == 0
    assert aggregate["finance_control_semantic_equal"] is True


def test_retained_artifact_semantic_digest_matches_raw_evidence() -> None:
    artifact = _artifact()
    semantic = {
        key: value
        for key, value in artifact.items()
        if key not in {"generated_at", "semantic_sha256"}
    }
    assert hashlib.sha256(
        _canonical_json(semantic).encode("utf-8")
    ).hexdigest() == artifact["semantic_sha256"]


def test_retained_layout_stage_stays_below_five_percent_ceiling() -> None:
    artifact = _artifact()
    stage = artifact["layout_stage"]

    assert stage["warmup_count"] == 5
    assert stage["sample_count"] == 100
    assert stage["p95_seconds"] <= stage["five_percent_ceiling_seconds"]
    assert stage["p95_seconds"] <= 0.050
    assert stage["peak_allocated_bytes"] <= 32 * 1024 * 1024
