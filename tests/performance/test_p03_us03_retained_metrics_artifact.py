"""Custody and quality gate for the retained P03-US03 artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tests.benchmarks.layout_source_note_metrics import (
    CASES,
    CODE_PATHS,
    EXPECTED_EMITTED_NOTE_SIGNATURES,
    EXPECTED_INPUTS,
    EXPECTED_LINK_TARGETS,
    EXPECTED_REVIEWED_NOTES,
    PHASE_02_PERFORMANCE_BASELINES,
    _artifact_semantic_payload,
    _canonical_json,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker"
    / "phase-03-layout"
    / "evidence"
    / "P03-US03-source-note-metrics.json"
)
EXPECTED_ARTIFACT_SHA256 = (
    "c9f0cbbc0071bdf47ad19b00c6ed2996fb9bb80b1bf785bf9ae3e3c128a8ef7f"
)
P03_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/services/ir.py",
        "app/services/layout.py",
        "app/services/ocr.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/serializer.py",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/app/globals.css",
        "frontend/lib/layout-relationships.ts",
        "frontend/lib/types.ts",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact() -> dict[str, Any]:
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    return json.loads(raw)


def test_retained_artifact_binds_final_code_and_inputs() -> None:
    artifact = _artifact()

    assert artifact["schema_version"] == "1.0"
    assert artifact["story"] == "P03-US03"
    assert artifact["measurement"]["hosted_requests"] == 0
    assert artifact["measurement"]["performance_case_pair_count"] == 5
    assert artifact["measurement"]["performance_cases"] == [
        "catastrophe-recap",
        "clinical-study",
    ]
    assert artifact["phase_02_performance_baselines"] == (
        PHASE_02_PERFORMANCE_BASELINES
    )

    code_records = artifact["code_sha256"]
    assert len(code_records) == len(CODE_PATHS) == 22
    assert set(code_records) == set(CODE_PATHS)
    assert P03_SUCCESSOR_OWNED_INPUTS < set(code_records)
    for relative, record in code_records.items():
        assert record["path"] == relative
        assert len(record["sha256"]) == 64
        assert record["size_bytes"] > 0
        if relative in P03_SUCCESSOR_OWNED_INPUTS:
            continue
        path = WORKSPACE / relative
        assert path.is_file()
        assert path.stat().st_size == record["size_bytes"]
        assert _sha256(path) == record["sha256"]

    assert set(artifact["cases"]) == set(CASES)
    for case_name, expected in EXPECTED_INPUTS.items():
        case = artifact["cases"][case_name]
        source = WORKSPACE / case["input_path"]
        assert (
            source.stat().st_size
            == case["input_size_bytes"]
            == expected["size_bytes"]
        )
        assert (
            _sha256(source)
            == case["input_sha256"]
            == expected["sha256"]
        )


def test_retained_quality_inventory_is_exact_and_fail_closed() -> None:
    artifact = _artifact()
    expected_reviewed_total = 0
    expected_emitted_total = 0
    expected_links: set[str] = set()
    note_ids: set[str] = set()
    relationship_ids: set[str] = set()

    for case_name in CASES:
        case = artifact["cases"][case_name]
        flag_off = case["flag_off"]
        flag_on = case["flag_on"]
        expected_reviewed = EXPECTED_REVIEWED_NOTES[case_name]
        expected_signatures = EXPECTED_EMITTED_NOTE_SIGNATURES[case_name]
        case_links = set(EXPECTED_LINK_TARGETS[case_name])

        assert flag_off["enabled"] is False
        assert flag_off["layout_note_projection_absent"] is True
        assert flag_off["note_records"] == []
        assert flag_off["json_round_trip_equal"] is True
        assert flag_off["markdown_serialized"] is True
        assert case["all_flag_off_samples_projection_absent"] is True

        assert flag_on["enabled"] is True
        assert flag_on["layout_note_projection_absent"] is (
            not expected_signatures
        )
        assert flag_on["json_round_trip_equal"] is True
        assert flag_on["markdown_serialized"] is True
        assert flag_on["missing_expected_note_count"] == 0
        assert flag_on["unexpected_note_count"] == 0
        assert flag_on["missing_expected_link_count"] == 0
        assert flag_on["unexpected_link_count"] == 0
        assert flag_on["all_emitted_notes_exactly_classified"] is True
        assert flag_on["all_emitted_links_exactly_classified"] is True
        assert flag_on["all_relationships_valid"] is True
        assert case["all_flag_on_samples_quality_consistent"] is True
        assert case["reviewed_note_expected"] == len(expected_reviewed)
        assert case["reviewed_note_matched"] == len(expected_reviewed)
        assert case["reviewed_note_recall"] == 1.0
        assert case["expected_emitted_note_count"] == len(
            expected_signatures
        )
        assert case["flag_on_note_count"] == len(expected_signatures)
        assert set(flag_on["observed_link_targets"]) == case_links

        actual_signatures = tuple(
            (
                record["page_index"],
                record["type"],
                record["value"],
                record["owner_id"],
                record["owner_type"],
            )
            for record in flag_on["note_records"]
        )
        assert actual_signatures == expected_signatures
        for value in expected_reviewed:
            assert flag_on["reviewed_note_occurrences"][value] == 1
            assert flag_on["markdown_reviewed_occurrences"][value] == 1
            assert flag_on["canonical_reviewed_occurrences"][value] == 1

        for record in flag_on["note_records"]:
            assert record["id"] not in note_ids
            assert record["relationship_id"] not in relationship_ids
            note_ids.add(record["id"])
            relationship_ids.add(record["relationship_id"])
            assert record["owner_resolved"] is True
            assert record["owner_linked_back"] is True
            assert record["descriptor_exact"] is True
            assert record["relationship_type_exact"] is True
            assert record["order_after_owner"] is True
            assert record["bbox_external"] is True
            assert record["bbox_positive"] is True
            assert record["bbox_below_aligned_within_gap"] is True
            assert record["links_grounded"] is True
            assert record["canonical_block_present"] is True
            assert record["canonical_owner_block_present"] is True
            assert record["canonical_relationship_block_count"] == 2

        expected_reviewed_total += len(expected_reviewed)
        expected_emitted_total += len(expected_signatures)
        expected_links.update(case_links)

    aggregate = artifact["aggregate"]
    assert aggregate["reviewed_note_expected"] == 8
    assert aggregate["reviewed_note_matched"] == 8
    assert expected_reviewed_total == 8
    assert expected_emitted_total == 14
    assert len(expected_links) == 5
    assert aggregate["reviewed_note_recall"] == 1.0
    assert aggregate["false_association_count"] == 0
    assert aggregate["missing_expected_control_count"] == 0
    assert aggregate["all_emitted_notes_exactly_classified"] is True
    assert aggregate["all_emitted_links_exactly_classified"] is True
    assert aggregate["all_relationships_valid"] is True
    assert aggregate["all_performance_sample_quality_consistent"] is True
    assert aggregate["all_flag_off_samples_projection_absent"] is True
    assert aggregate["all_reviewed_markdown_once"] is True
    assert aggregate["all_reviewed_canonical_once"] is True
    assert aggregate["health_link_targets_once_in_output"] is True
    assert aggregate["finance_semantic_flag_parity"] is True
    assert aggregate["finance_markdown_flag_parity"] is True


def test_retained_performance_resources_and_dependency_custody() -> None:
    artifact = _artifact()

    for case_name in CASES:
        case = artifact["cases"][case_name]
        sample_count = 5 if case_name in PHASE_02_PERFORMANCE_BASELINES else 1
        resources = case["resource_samples"]
        for key in (
            "flag_off_peak_rss_bytes",
            "flag_on_peak_rss_bytes",
            "paired_peak_rss_bytes_deltas",
            "flag_off_semantic_json_size_bytes",
            "flag_on_semantic_json_size_bytes",
            "flag_off_markdown_size_bytes",
            "flag_on_markdown_size_bytes",
        ):
            assert len(resources[key]) == sample_count
        assert resources["max_flag_on_peak_rss_bytes"] > 0
        assert all(
            value > 0
            for value in resources["flag_off_semantic_json_size_bytes"]
        )
        assert all(
            value > 0
            for value in resources["flag_on_semantic_json_size_bytes"]
        )

    for case_name, baseline in PHASE_02_PERFORMANCE_BASELINES.items():
        performance = artifact["cases"][case_name][
            "paired_performance"
        ]
        assert performance["pair_count"] == 5
        assert performance["quantile_method"] == (
            "empirical_p95_inclusive"
        )
        assert len(performance["paired_signed_wall_seconds_deltas"]) == 5
        assert len(
            performance["paired_nonnegative_overhead_seconds"]
        ) == 5
        assert all(
            value >= 0
            for value in performance[
                "paired_nonnegative_overhead_seconds"
            ]
        )
        assert performance["five_percent_ceiling_seconds"] == (
            baseline["wall_seconds"] * 0.05
        )
        assert performance["p95_nonnegative_overhead_seconds"] <= (
            performance["five_percent_ceiling_seconds"]
        )
        assert performance["within_five_percent_ceiling"] is True

    stage = artifact["layout_stage"]
    assert stage["warmup_count"] == 5
    assert stage["sample_count"] == 100
    assert stage["note_count"] == 8
    assert stage["p95_seconds"] <= 0.050
    assert stage["peak_allocated_bytes"] < 32 * 1024 * 1024
    assert stage["within_five_percent_ceiling"] is True
    assert artifact["aggregate"][
        "performance_p95_within_five_percent"
    ] is True

    custody = artifact["dependency_custody"]
    assert custody["python_packages"] == {
        "docling": "2.114.0",
        "docling-core": "2.88.0",
        "pdfplumber": "0.11.10",
        "pydantic": "2.13.4",
    }
    assert custody["tesseract"]["version"] == "tesseract 5.5.3"
    assert custody["tesseract"]["size_bytes"] == 69184
    assert len(custody["tesseract"]["sha256"]) == 64


def test_retained_artifact_semantic_digest_matches_raw_evidence() -> None:
    artifact = _artifact()

    digest = hashlib.sha256(
        _canonical_json(_artifact_semantic_payload(artifact)).encode(
            "utf-8"
        )
    ).hexdigest()
    assert digest == artifact["semantic_sha256"]
