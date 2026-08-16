"""Custody and quality gate for the retained P03-US05 artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from tests.benchmarks.text_run_semantics_metrics import (
    CODE_PATHS,
    CONTROL_MATRIX,
    DEFAULT_ARTIFACT_RELATIVE_PATH,
    FIXED_DENOMINATORS,
    HOSTED_USAGE,
    M0_REFERENCE,
    POSTAL_ITALIC_TARGETS,
    PURCHASE_SOURCE_SEQUENCE,
    SOURCE_IDENTITIES,
    SYNTHETIC_FIXTURE_IDS,
    US04_ARTIFACT_RAW_SHA256,
    US04_ARTIFACT_SEMANTIC_SHA256,
    _artifact_semantic_payload,
    _canonical_json,
)


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = WORKSPACE / DEFAULT_ARTIFACT_RELATIVE_PATH
# Set to the final raw-byte digest when the closure run writes the retained
# artifact.  Leaving this unset is permitted only while the artifact is absent.
EXPECTED_ARTIFACT_SHA256: str | None = (
    "0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659"
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
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/types.ts",
    }
)

pytestmark = pytest.mark.skipif(
    not ARTIFACT.is_file(),
    reason="P03-US05 retained metrics are written during story closure",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact() -> dict[str, Any]:
    raw = ARTIFACT.read_bytes()
    assert EXPECTED_ARTIFACT_SHA256 is not None, (
        "seal EXPECTED_ARTIFACT_SHA256 after generating the final artifact"
    )
    assert len(EXPECTED_ARTIFACT_SHA256) == 64
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_SHA256
    return json.loads(raw)


def _assert_zero_hosted_usage(value: Any) -> None:
    if isinstance(value, Mapping):
        hosted_keys = set(HOSTED_USAGE) & set(value)
        for key in hosted_keys:
            assert value[key] == 0
        for child in value.values():
            _assert_zero_hosted_usage(child)
    elif isinstance(value, list):
        for child in value:
            _assert_zero_hosted_usage(child)


def test_retained_artifact_binds_raw_semantic_code_and_source_custody(
) -> None:
    artifact = _artifact()

    assert artifact["schema_version"] == "1.0"
    assert artifact["story"] == "P03-US05"
    assert len(artifact["semantic_sha256"]) == 64
    semantic_digest = hashlib.sha256(
        _canonical_json(
            _artifact_semantic_payload(artifact)
        ).encode("utf-8")
    ).hexdigest()
    assert semantic_digest == artifact["semantic_sha256"]

    code_records = artifact["code_sha256"]
    assert set(code_records) == set(CODE_PATHS)
    assert P03_SUCCESSOR_OWNED_INPUTS < set(code_records)
    for relative, record in code_records.items():
        assert record["path"] == relative
        assert record["size_bytes"] > 0
        assert len(record["sha256"]) == 64
        if relative in P03_SUCCESSOR_OWNED_INPUTS:
            continue
        path = WORKSPACE / relative
        assert path.is_file()
        assert path.stat().st_size == record["size_bytes"]
        assert _sha256(path) == record["sha256"]

    assert set(artifact["input_custody"]) == set(SOURCE_IDENTITIES)
    for case, expected in SOURCE_IDENTITIES.items():
        custody = artifact["input_custody"][case]
        assert custody["expected"] == expected
        assert custody["observed"] == expected
        assert custody["exact_match"] is True
        source = WORKSPACE / expected["path"]
        assert source.stat().st_size == expected["size_bytes"]
        assert _sha256(source) == expected["sha256"]


def test_retained_controls_denominators_and_rollback_are_exact() -> None:
    artifact = _artifact()

    assert artifact["m0_reference"] == M0_REFERENCE
    assert artifact["fixed_denominators"] == FIXED_DENOMINATORS
    matrix = artifact["control_matrix"]
    assert set(matrix["matrix_results"]) == set(CONTROL_MATRIX)
    for key, expected in CONTROL_MATRIX.items():
        row = matrix["matrix_results"][key]
        assert {
            name: row[name] for name in ("claim_id", "case", "role")
        } == expected
        assert row["pass"] is True

    purchase = matrix["cases"]["purchase-agreement"]["summary"]
    assert purchase["deleted_logical_group_count"] == 6
    assert purchase["deleted_group_rule_edge_count"] == 7
    assert purchase["deleted_run_rule_link_count"] == 9
    assert purchase["blue_run_count"] == 2
    assert purchase["blue_rule_link_count"] == 4
    assert purchase["inserted_or_replacement_count"] == 0
    assert not any(purchase["false_deletion_controls"].values())
    assert purchase["active_projection_item_count"] > 0

    postal = matrix["cases"]["postal-10k"]["summary"]
    assert postal["postal_italic_targets"] == POSTAL_ITALIC_TARGETS
    finance = matrix["cases"]["finance-10k"]["summary"]
    assert finance["deleted_run_count"] == 0
    assert finance["inserted_or_replacement_count"] == 0
    assert finance["run_count"] > 0

    rollback = artifact["rollback"]
    assert rollback["flag_off_extractor_count"] == 0
    assert rollback["flag_off_projection_absent"] is True
    assert rollback["only_us05_setting_toggled"] is True
    assert rollback["repeated_projection_idempotent"] is True

    predecessor = artifact["predecessor_custody"]
    assert predecessor["reviewed_pair_expected"] == 41
    assert predecessor["reviewed_pair_matched"] == 41
    predecessor_path = WORKSPACE / predecessor["path"]
    assert predecessor_path.is_file()
    assert predecessor_path.stat().st_size == predecessor["size_bytes"]
    assert _sha256(predecessor_path) == predecessor["raw_sha256"]
    assert predecessor["raw_sha256"] == US04_ARTIFACT_RAW_SHA256
    assert (
        predecessor["semantic_sha256"]
        == US04_ARTIFACT_SEMANTIC_SHA256
    )

    retention = artifact["relationship_order_retention"]
    assert retention["oracle"] == {
        "path": predecessor["path"],
        "raw_sha256": US04_ARTIFACT_RAW_SHA256,
        "semantic_sha256": US04_ARTIFACT_SEMANTIC_SHA256,
        "reviewed_case_count": 9,
        "slice_count": 10,
    }
    assert len(retention["source_custody"]) == 9
    assert set(retention["source_custody"]) == set(retention["cases"])
    for custody in retention["source_custody"].values():
        assert custody["exact_match"] is True
        assert custody["observed"] == custody["expected"]
    assert retention["top_level_expected"] == 40
    assert retention["top_level_matched"] == 40
    assert len(retention["top_level_results"]) == 40
    assert all(
        result["matched"] is True
        and result["before_position"] < result["after_position"]
        for result in retention["top_level_results"]
    )
    assert retention["nested_expected"] == 1
    assert retention["nested_matched"] == 1
    assert retention["nested_result"]["public_matched"] is True
    assert retention["nested_result"]["canonical_field_matched"] == {
        "markdown": True,
        "text": True,
    }
    assert retention["nested_result"]["matched"] is True
    assert retention["total_expected"] == 41
    assert retention["total_matched"] == 41
    purchase_sequence = retention["purchase_source_sequence"]
    assert purchase_sequence["expected_count"] == 7
    assert purchase_sequence["observed_count"] == 7
    assert purchase_sequence["expected"] == [
        list(entry) for entry in PURCHASE_SOURCE_SEQUENCE
    ]
    assert purchase_sequence["observed"] == purchase_sequence["expected"]
    assert purchase_sequence["strictly_ordered"] is True
    assert purchase_sequence["exact"] is True
    stable_entries = {
        entry["item_id"]: entry
        for entry in purchase_sequence["entries"]
        if entry["observed"][0] == "item"
    }
    assert stable_entries["p1-i11"]["source_text"] == "EXECUTION VERSION"
    assert stable_entries["p1-i1"]["source_text"] == (
        "ASSET PURCHASE AGREEMENT"
    )
    assert stable_entries["p1-i2"]["source_text"].startswith(
        "THIS ASSET PURCHASE AGREEMENT"
    )
    assert all(
        len(entry["source_text_sha256"]) == 64
        for entry in stable_entries.values()
    )
    assert retention["all_pass"] is True


def test_retained_synthetic_custody_and_resource_bounds_are_exact() -> None:
    artifact = _artifact()

    synthetic = artifact["synthetic_fixture_custody"]
    assert tuple(synthetic) == SYNTHETIC_FIXTURE_IDS
    for fixture_id, record in synthetic.items():
        assert record["payload"]["fixture_id"] == fixture_id
        assert len(record["payload_sha256"]) == 64
        assert record["payload_sha256"] == hashlib.sha256(
            _canonical_json(record["payload"]).encode("utf-8")
        ).hexdigest()
    limits = synthetic["synthetic:p03-us05:limits-v1"]["payload"]
    assert limits["exact_maximum"] == 64
    assert limits["maximum_plus_one"] == 65
    assert len(limits["exact_source_sha256"]) == 64
    assert len(limits["maximum_plus_one_source_sha256"]) == 64

    extraction = artifact["source_extraction"]
    assert extraction["warmup_count"] == 2
    assert extraction["sample_count"] == 20
    assert len(extraction["samples_seconds"]) == 20
    assert extraction["timing_tracemalloc_enabled"] is False
    assert extraction["allocation_measured_in_separate_call"] is True
    assert extraction["gc_collection_outside_timed_interval"] is True
    assert (
        extraction["p95_seconds"]
        <= extraction["p95_ceiling_seconds"]
        == 0.150
    )
    assert extraction["within_p95_ceiling"] is True
    assert (
        extraction["peak_allocated_bytes"]
        < extraction["peak_allocation_ceiling_bytes"]
        == 64 * 1024 * 1024
    )
    assert extraction["within_peak_allocation_ceiling"] is True
    assert extraction["report_size_bytes"] <= 8 * 1024 * 1024
    assert extraction["character_count"] == 3_338
    assert extraction["candidate_rule_count"] == 13
    assert extraction["retained_rule_count"] == 13
    assert extraction["semantic_deterministic"] is True

    projection = artifact["association_projection"]
    assert projection["warmup_count"] == 2
    assert projection["sample_count"] == 20
    assert len(projection["samples_seconds"]) == 20
    assert projection["timing_tracemalloc_enabled"] is False
    assert projection["allocation_measured_in_separate_call"] is True
    assert projection["gc_collection_outside_timed_interval"] is True
    assert (
        projection["p95_seconds"]
        <= projection["p95_ceiling_seconds"]
        == 0.050
    )
    assert projection["within_p95_ceiling"] is True
    assert (
        projection["peak_allocated_bytes"]
        < projection["peak_allocation_ceiling_bytes"]
        == 32 * 1024 * 1024
    )
    assert projection["within_peak_allocation_ceiling"] is True
    assert projection["projected_ir_size_bytes"] <= 8 * 1024 * 1024
    assert projection["predecessor_unmodified"] is True
    assert projection["repeated_projection_idempotent"] is True

    boundary = artifact["maximum_boundary"]
    assert boundary["exact_maximum"] == 64
    assert boundary["maximum_plus_one"] == 65
    assert boundary["exact_completed"] is True
    assert (
        boundary["elapsed_seconds"]
        <= boundary["ceiling_seconds"]
        == 0.250
    )
    assert boundary["within_ceiling"] is True
    assert boundary["maximum_plus_one_elapsed_seconds"] <= 0.250
    assert boundary["maximum_plus_one_within_ceiling"] is True
    assert boundary["maximum_plus_one_failed_closed"] is True
    assert boundary["maximum_plus_one_refusal_code"] is None
    assert boundary["maximum_plus_one_usable"] is True
    assert boundary["maximum_plus_one_page_status"] == "unavailable"
    assert boundary["maximum_plus_one_page_concern_code"] == (
        "text_run_rule_limit"
    )


def test_retained_paired_parser_and_uber_memory_guard_are_exact() -> None:
    artifact = _artifact()
    paired = artifact["paired_parser"]

    purchase = paired["purchase_parser_budget"]
    assert len(purchase["flag_off_samples"]) == 5
    assert len(purchase["flag_on_samples"]) == 5
    assert purchase["execution_order"] == [
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
    ]
    assert purchase["all_flag_off_extractor_counts_zero"] is True
    assert purchase["all_flag_on_extractor_counts_one"] is True
    assert purchase["flag_off_semantic_deterministic"] is True
    assert purchase["flag_on_semantic_deterministic"] is True
    performance = purchase["paired_performance"]
    assert performance["pair_count"] == 5
    assert performance["process_model"] == (
        "fresh_process_per_flag_state"
    )
    assert performance["quantile_method"] == (
        "empirical_p95_inclusive"
    )
    assert performance["gate_value"] == (
        "p95_of_clipped_nonnegative_paired_overhead"
    )
    assert len(performance["paired_signed_wall_seconds_deltas"]) == 5
    assert len(
        performance["paired_nonnegative_overhead_seconds"]
    ) == 5
    assert performance["p95_nonnegative_overhead_seconds"] <= (
        performance["five_percent_ceiling_seconds"]
    )
    assert performance["p95_nonnegative_overhead_seconds"] <= 0.309
    assert performance["within_five_percent_ceiling"] is True
    assert performance["within_absolute_ceiling"] is True
    assert performance["within_both_ceilings"] is True
    assert performance["m0_reference"] == M0_REFERENCE

    uber = paired["uber_memory_guard"]
    assert len(uber["flag_off_samples"]) == 5
    assert len(uber["flag_on_samples"]) == 5
    assert uber["all_flag_off_extractor_counts_zero"] is True
    assert uber["all_flag_on_extractor_counts_one"] is True
    memory = uber["memory_guard"]
    assert memory["case"] == "uber-earnings"
    assert memory["pair_count"] == 5
    assert memory["process_model"] == "fresh_process_per_flag_state"
    assert len(memory["flag_off_peak_rss_bytes"]) == 5
    assert len(memory["flag_on_peak_rss_bytes"]) == 5
    assert len(memory["paired_peak_rss_bytes_deltas"]) == 5
    assert memory["all_measurements_positive"] is True

    for case_metrics in artifact["output_sizes"].values():
        assert case_metrics["semantic_json_size_bytes"] > 0
        assert case_metrics["markdown_size_bytes"] > 0
        assert case_metrics["semantic_json_size_bytes"] <= 8 * 1024 * 1024


def test_retained_dependency_and_zero_hosted_custody_are_exact() -> None:
    artifact = _artifact()
    dependency = artifact["dependency_custody"]

    assert dependency["python_packages"] == {
        "docling": "2.114.0",
        "docling-core": "2.88.0",
        "pdfplumber": "0.11.10",
        "pydantic": "2.13.4",
    }
    assert set(dependency["dependency_manifest_sha256"]) == {
        "pyproject.toml",
        "uv.lock",
        "frontend/package-lock.json",
    }
    assert all(
        len(value) == 64
        for value in dependency[
            "dependency_manifest_sha256"
        ].values()
    )
    tool = dependency["local_tool_identity"]
    assert tool["python_executable"]
    assert tool["python_version"]
    assert tool["platform"]
    assert tool["tesseract"]["version"].startswith("tesseract ")
    assert tool["tesseract"]["size_bytes"] > 0
    assert len(tool["tesseract"]["sha256"]) == 64

    aggregate = artifact["aggregate"]
    assert aggregate["deleted_logical_group_count"] == 6
    assert aggregate["deleted_group_rule_edge_count"] == 7
    assert aggregate["deleted_run_rule_link_count"] == 9
    assert aggregate["blue_run_count"] == 2
    assert aggregate["blue_rule_link_count"] == 4
    assert aggregate["source_proven_inserted_replacement_count"] == 0
    assert aggregate["false_deletion_count"] == 0
    assert aggregate["all_control_matrix_rows_pass"] is True
    assert aggregate["source_extraction_p95_within_150ms"] is True
    assert aggregate["source_extraction_peak_within_64mib"] is True
    assert aggregate["projection_p95_within_50ms"] is True
    assert aggregate["projection_peak_within_32mib"] is True
    assert aggregate["maximum_boundary_within_250ms"] is True
    assert aggregate["maximum_plus_one_failed_closed"] is True
    assert aggregate["maximum_plus_one_within_250ms"] is True
    assert aggregate["paired_parser_within_five_percent"] is True
    assert aggregate["paired_parser_within_309ms"] is True
    assert aggregate["paired_parser_within_both_ceilings"] is True
    assert aggregate["flag_off_extractor_count"] == 0
    assert aggregate["idempotence"] is True
    assert aggregate["purchase_source_sequence_expected"] == 7
    assert aggregate["purchase_source_sequence_matched"] == 7
    assert aggregate["relationship_order_retention_all_pass"] is True
    assert aggregate["predecessor_order_expected"] == 41
    assert aggregate["predecessor_order_matched"] == 41

    _assert_zero_hosted_usage(artifact)
