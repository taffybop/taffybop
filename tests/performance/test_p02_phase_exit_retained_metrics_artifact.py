"""Contract for the frozen Phase 02 source-alignment exit artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker/phase-02-text-integrity/evidence/"
    "P02-source-text-alignment-metrics.json"
)
EXPECTED_SHA256 = (
    "6fdd74cb7adece95ae4a67cc98d1d02e3ca071f9166d4c8c26150768114dbacb"
)
EXPECTED_SEMANTIC_SHA256 = (
    "fcc2bf63c145347f8a7a40876dd60247e684e2d3616860b479f74c7d8240b558"
)
EXPECTED_SELECTION_COUNTS = {
    "catastrophe-recap": 0,
    "clean-energy": 0,
    "clinical-study": 5,
    "component-datasheet": 0,
    "egov-survey": 0,
    "esg-metrics": 5,
    "finance-10k": 0,
    "health-report": 0,
    "insurance-acord": 0,
    "manufacturing-report": 0,
    "ny-timetable": 0,
    "postal-10k": 2,
    "purchase-agreement": 1,
    "settlement-agreement": 1,
    "uber-earnings": 0,
}
PHASE03_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/models.py",
        "app/services/ir.py",
        "app/services/ocr.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
    }
)


def _artifact() -> dict[str, object]:
    content = ARTIFACT.read_bytes()
    assert len(content) == 439_414
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload


def test_retained_phase_exit_artifact_has_exact_custody() -> None:
    payload = _artifact()

    assert payload["schema_version"] == "1.0"
    assert payload["record_kind"] == "p02_source_text_alignment_metrics"
    assert payload["warmups"] == 2
    assert payload["samples"] == 10

    custody = payload["custody"]
    assert isinstance(custody, dict)
    assert custody["pre_post_input_identity_match"] is True
    assert custody["pre_post_corpus_identity_match"] is True
    assert custody["corpus_case_count"] == 15
    assert custody["pipeline"]["sha256"] == (
        "7bf2c642146394f48f70a42ac737596f1054843295f37d9da13934ff2fc540a2"
    )
    assert custody["production_code"]["sha256"] == (
        "8294ca5258db5f8dfb6d70f87e4ccefc132bb3b60eb6c979490533758d62976b"
    )

    run_inputs = payload["run_inputs"]
    assert isinstance(run_inputs, dict)
    assert len(run_inputs) == 67
    assert len(run_inputs) == len(set(run_inputs))
    assert PHASE03_SUCCESSOR_OWNED_INPUTS < set(run_inputs)
    changed_since_seal: set[str] = set()
    for relative_path, expected in run_inputs.items():
        assert isinstance(relative_path, str)
        assert isinstance(expected, dict)
        assert expected["path"] == relative_path
        assert len(str(expected["sha256"])) == 64
        assert int(expected["size_bytes"]) > 0
        content = (WORKSPACE / relative_path).read_bytes()
        current = {
            "path": relative_path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        if expected != current:
            changed_since_seal.add(relative_path)

    # The artifact hash above authenticates every exact at-run snapshot.
    # Phase 03 legitimately extends only these shared surfaces; all other
    # Phase 02 exit inputs remain live-bound here.
    assert changed_since_seal == PHASE03_SUCCESSOR_OWNED_INPUTS


def test_retained_phase_exit_artifact_meets_component_acceptance() -> None:
    payload = _artifact()
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)

    assert metrics["case_count"] == 15
    assert metrics["affected_case_count"] == 5
    assert metrics["affected_target_pass_count"] == 5
    assert metrics["flag_off_predecessor_exact_count"] == 15
    assert metrics["non_target_selected_case_count"] == 0
    assert metrics["non_target_changed_case_count"] == 0
    assert metrics["finance_10k_selected_count"] == 0
    assert metrics["finance_10k_pages_unchanged"] is True
    assert metrics["healthy_component_case_count"] == 10
    assert metrics["healthy_component_conservative_worst_case_id"] == (
        "ny-timetable"
    )
    assert metrics["healthy_component_latency_ms_by_case"]["ny-timetable"][
        "p95"
    ] == 400.88229200046044
    assert metrics["healthy_component_conservative_worst_case_p95_percent"] == (
        0.8573188451677939
    )
    assert metrics["component_overhead_passes"] is True

    ceiling = metrics["combined_healthy_p95_ceiling_reference"]
    assert isinstance(ceiling, dict)
    assert ceiling["arithmetic_ceiling_percent"] == 3.9526450465578975
    assert ceiling["target_percent"] == 10.0
    assert ceiling["passes_target"] is True
    assert ceiling["observed_paired_full_parser_percentile"] is False

    assert metrics["semantic_output_size_bytes"] == 418_996
    assert metrics["semantic_output_sha256"] == EXPECTED_SEMANTIC_SHA256
    assert metrics["hosted_model_request_count"] == 0
    assert metrics["hosted_model_token_count"] == 0
    assert metrics["hosted_model_cost_usd"] == 0.0


def test_retained_phase_exit_full_parser_screen_is_exact() -> None:
    payload = _artifact()
    semantic = payload["semantic_results"]
    assert isinstance(semantic, dict)
    screen = semantic["full_parser_screen"]
    assert isinstance(screen, dict)

    assert screen["provided"] is True
    assert screen["scope"] == "all_15_enabled"
    assert screen["case_count"] == 15
    assert screen["predecessor_pair_count"] == 15
    assert screen["target_results"] == {
        "catastrophe-recap": True,
        "clinical-study": True,
        "esg-metrics": True,
        "postal-10k": True,
        "purchase-agreement": True,
        "settlement-agreement": True,
    }
    assert set(screen["non_target_selection_counts"].values()) == {0}

    cases = screen["cases"]
    assert isinstance(cases, list)
    assert {
        str(case["case_id"]): int(case["summary"]["selected_count"])
        for case in cases
    } == EXPECTED_SELECTION_COUNTS
    assert all(
        bool(value)
        for row in screen["paired_non_target_predecessor_parity"].values()
        for value in row.values()
    )
    assert all(
        row["passes"] is True
        for row in screen["approved_owner_drift"].values()
    )
