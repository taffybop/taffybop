"""Contract for the frozen P02-US05 numeric-cleanup metrics artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker/phase-02-text-integrity/evidence/"
    "P02-US05-numeric-cleanup-metrics.json"
)
EXPECTED_SHA256 = (
    "5b347a6f98c47d9df3b52cfef40bb5c6bb5824f149cc8da6806cc23d5e3a174c"
)
EXPECTED_SEMANTIC_SHA256 = (
    "e0febf0c4dbf81e7390efd02db5a149370c69c6c82b358ddeef7099741bcc756"
)
P02_US06_SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/services/ocr.py",
        "app/services/pipeline.py",
        "app/services/selective_span_ocr.py",
    }
)


def _artifact() -> dict[str, object]:
    content = ARTIFACT.read_bytes()
    assert len(content) == 27_361
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload


def test_retained_numeric_cleanup_artifact_has_exact_custody() -> None:
    payload = _artifact()

    assert payload["schema_version"] == "1.0"
    assert payload["record_kind"] == (
        "p02_us05_numeric_cleanup_component_metrics"
    )
    assert payload["warmups"] == 2
    assert payload["samples"] == 10
    custody = payload["custody"]
    assert isinstance(custody, dict)
    assert custody["pre_post_input_identity_match"] is True

    run_inputs = payload["run_inputs"]
    assert isinstance(run_inputs, dict)
    assert len(run_inputs) == 15
    assert len(run_inputs) == len(set(run_inputs))
    assert P02_US06_SUCCESSOR_OWNED_INPUTS < set(run_inputs)
    for relative_path, expected in run_inputs.items():
        assert isinstance(relative_path, str)
        assert isinstance(expected, dict)
        assert expected["path"] == relative_path
        assert len(str(expected["sha256"])) == 64
        assert int(expected["size_bytes"]) > 0
        # The sealed artifact authenticates the exact at-run snapshots. P02-US06
        # legitimately extends these shared adapter/configuration files; its own
        # retained artifact assumes current-state custody for them. All immutable
        # US05 policy, target, runner, and dedicated-test inputs stay live-bound.
        if relative_path in P02_US06_SUCCESSOR_OWNED_INPUTS:
            continue
        content = (WORKSPACE / relative_path).read_bytes()
        assert expected == {
            "path": relative_path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }


def test_retained_numeric_cleanup_artifact_meets_acceptance() -> None:
    payload = _artifact()
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)

    assert metrics["observed_year_token_count"] == 12
    assert metrics["observed_years_exact"] is True
    assert metrics["observed_48_digit_false_join_count"] == 0
    assert metrics["flag_off_observed_legacy_exact"] is True
    assert metrics["sequential_year_token_count"] == 12
    assert metrics["sequential_years_exact"] is True
    assert metrics["flag_off_sequential_legacy_exact"] is True
    assert metrics["approved_digest_case_count"] == 35
    assert metrics["approved_digest_join_count"] == 35
    assert metrics["approved_digest_flag_off_compatibility_count"] == 35
    assert metrics["numeric_control_case_count"] == 16
    assert metrics["numeric_control_exact_count"] == 16
    assert metrics["bound_case_count"] == 4
    assert metrics["bound_fail_closed_count"] == 4
    assert metrics["semantic_output_sha256"] == EXPECTED_SEMANTIC_SHA256
    assert metrics["hosted_model_request_count"] == 0
    assert metrics["hosted_model_token_count"] == 0
    assert metrics["hosted_model_cost_usd"] == 0.0

    ceiling = metrics["combined_healthy_p95_ceiling_reference"]
    assert isinstance(ceiling, dict)
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True


def test_retained_numeric_cleanup_target_bytes_are_exact() -> None:
    payload = _artifact()
    semantic = payload["semantic_results"]
    assert isinstance(semantic, dict)
    target = semantic["target"]
    assert isinstance(target, dict)

    observed = target["observed"]
    assert isinstance(observed, dict)
    assert observed["flag_on"].split() == [
        "2015",
        "2020",
        "2025",
        "2015",
        "2020",
        "2025",
        "2015",
        "2020",
        "2025",
        "2015",
        "2020",
        "2025",
    ]
    assert observed["flag_off"] == (
        "201520202025201520202025201520202025201520202025"
    )

    sequential = target["sequential"]
    assert isinstance(sequential, dict)
    assert sequential["flag_on"].split() == [
        str(year) for year in range(2010, 2022)
    ]
    assert sequential["flag_off"] == (
        "201020112012201320142015201620172018201920202021"
    )
