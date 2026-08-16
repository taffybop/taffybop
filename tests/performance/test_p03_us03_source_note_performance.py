"""Bounded performance and metrics-harness checks for P03-US03."""

from __future__ import annotations

from copy import deepcopy

import pytest

import app.services.ocr as ocr_service
from tests.benchmarks.layout_source_note_metrics import (
    EXPECTED_EMITTED_NOTE_SIGNATURES,
    EXPECTED_LINK_TARGETS,
    EXPECTED_REVIEWED_NOTES,
    _artifact_semantic_payload,
    _canonical_json,
    _paired_performance_summary,
    _public_note_graph_valid,
    generate_stage_metrics,
)


def test_reviewed_and_emitted_inventories_are_fixed() -> None:
    assert sum(
        len(values) for values in EXPECTED_REVIEWED_NOTES.values()
    ) == 8
    assert {
        case: len(values)
        for case, values in EXPECTED_EMITTED_NOTE_SIGNATURES.items()
    } == {
        "catastrophe-recap": 1,
        "clinical-study": 10,
        "health-report": 3,
        "finance-10k": 0,
    }
    assert sum(
        len(values)
        for values in EXPECTED_EMITTED_NOTE_SIGNATURES.values()
    ) == 14
    assert EXPECTED_LINK_TARGETS["clinical-study"] == (
        "https://doi.org/10.1371/journal.pmed.1004460.t001",
        "https://doi.org/10.1371/journal.pmed.1004460.g001",
        "https://doi.org/10.1371/journal.pmed.1004460.t002",
    )


def test_paired_gate_uses_clipped_nonnegative_inclusive_p95() -> None:
    off = [{"wall_seconds": 10.0} for _ in range(5)]
    on = [
        {"wall_seconds": 9.0},
        {"wall_seconds": 9.0},
        {"wall_seconds": 9.0},
        {"wall_seconds": 9.0},
        {"wall_seconds": 10.7},
    ]

    summary = _paired_performance_summary(
        off,
        on,
        baseline_seconds=10.0,
    )

    assert summary["pair_count"] == 5
    assert summary["quantile_method"] == "empirical_p95_inclusive"
    assert summary["paired_signed_wall_seconds_deltas"] == [
        -1.0,
        -1.0,
        -1.0,
        -1.0,
        0.7,
    ]
    assert summary["paired_nonnegative_overhead_seconds"] == [
        0.0,
        0.0,
        0.0,
        0.0,
        0.7,
    ]
    assert summary["p95_signed_delta_seconds"] == pytest.approx(0.36)
    assert summary["p95_nonnegative_overhead_seconds"] == pytest.approx(
        0.56
    )
    assert summary["five_percent_ceiling_seconds"] == 0.5
    assert summary["within_five_percent_ceiling"] is False


def test_artifact_semantic_digest_excludes_run_metadata() -> None:
    first = {
        "story": "P03-US03",
        "generated_at": "2026-07-31T00:00:00+00:00",
        "semantic_sha256": "first",
        "aggregate": {"reviewed_note_matched": 8},
    }
    second = {
        **first,
        "generated_at": "2026-08-01T00:00:00+00:00",
        "semantic_sha256": "second",
    }

    assert _canonical_json(_artifact_semantic_payload(first)) == (
        _canonical_json(_artifact_semantic_payload(second))
    )


def test_public_graph_validator_rejects_dangling_or_duplicate_backlinks() -> None:
    relationship_id = "layout-rel-reviewed"
    payload = {
        "pages": [
            {
                "page_index": 1,
                "items": [
                    {
                        "id": "owner",
                        "type": "table",
                        "footnote_ids": ["note"],
                        "relationships": [
                            {
                                "id": relationship_id,
                                "type": "footnote_of",
                                "source_id": "note",
                                "target_id": "owner",
                            }
                        ],
                    },
                    {
                        "id": "note",
                        "type": "footnote",
                        "footnote_of": "owner",
                    },
                ],
            }
        ]
    }
    records = [
        {
            "id": "note",
            "owner_id": "owner",
            "relationship_id": relationship_id,
            "relationship_type": "footnote_of",
        }
    ]

    assert _public_note_graph_valid(payload, records) is True
    duplicate = deepcopy(payload)
    duplicate["pages"][0]["items"][0]["footnote_ids"].append("note")
    assert _public_note_graph_valid(duplicate, records) is False
    dangling = deepcopy(payload)
    dangling["pages"][0]["items"][0]["footnote_ids"] = ["missing"]
    assert _public_note_graph_valid(dangling, records) is False


def test_isolated_stage_profile_is_bounded_and_uses_actual_note_count() -> None:
    metrics = generate_stage_metrics()

    assert metrics["warmup_count"] == 5
    assert metrics["sample_count"] == 100
    assert metrics["note_count"] == 8
    assert 0 < metrics["p50_seconds"] <= metrics["p95_seconds"]
    assert metrics["p95_seconds"] <= metrics["max_seconds"]
    assert metrics["p95_seconds"] <= 0.05
    assert metrics["within_five_percent_ceiling"] is True
    assert metrics["peak_allocated_bytes"] < 32 * 1024 * 1024
    assert metrics["projected_ir_size_bytes"] < 8 * 1024 * 1024


def test_single_line_note_ocr_omits_redundant_sparse_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    empty_tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext\n"
    )

    def run(
        _executable: str,
        _png_bytes: bytes,
        _languages: tuple[str, ...],
        _timeout_seconds: float,
        _tessdata_path: str | None,
        *,
        page_segmentation_mode: int = 3,
    ) -> str:
        calls.append(page_segmentation_mode)
        return empty_tsv

    monkeypatch.setattr(ocr_service, "_run_tesseract_tsv", run)

    lines, rejected, warnings = ocr_service._ocr_png_lines(
        "/tesseract",
        b"png",
        ("eng",),
        30.0,
        None,
        crop_bounds=(0.0, 0.0, 100.0, 100.0),
        scale=1.0,
        page_width=100.0,
        page_height=100.0,
        sparse_pass_enabled=False,
        primary_page_segmentation_mode=7,
    )

    assert calls == [7]
    assert lines == []
    assert rejected == []
    assert warnings == []
