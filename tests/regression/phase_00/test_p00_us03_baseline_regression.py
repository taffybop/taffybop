"""Regression anchors for the P00-US03 measurement-only baseline story."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app
from app.models import ErrorResponse, ParseResult
from tests.benchmarks.baseline_report import (
    EXPECTED_API_SCHEMA_HASHES,
    canonical_payload_bytes,
    evaluate_catastrophe_quality,
    quality_outcome_payload,
    semantic_json_bytes,
    sha256_bytes,
)
from tests.benchmarks.source_truth import load_catastrophe_source_truth


WORKSPACE = Path(__file__).resolve().parents[3]
CURRENT_OUTPUT_ROOT = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
    / "catastrophe-recap"
)
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)


def test_measurement_story_does_not_change_current_catastrophe_semantics() -> None:
    raw_path = CURRENT_OUTPUT_ROOT / "our-output.json"
    markdown_path = CURRENT_OUTPUT_ROOT / "our-output.md"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    quality = evaluate_catastrophe_quality(
        payload,
        markdown,
        markdown,
        truth,
    )

    assert (
        sha256_bytes(semantic_json_bytes(payload))
        == "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9"
    )
    assert (
        sha256_bytes(markdown.encode("utf-8"))
        == "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1"
    )
    assert (
        sha256_bytes(
            canonical_payload_bytes(quality_outcome_payload(quality))
        )
        == "8507b5d0da5dfccda412b23757e091d59de7178899b3749305420649d9bbc998"
    )
    assert sum(check.passed for check in quality) == 5
    assert sum(not check.passed for check in quality) == 10


def test_public_api_schema_hashes_remain_at_the_captured_contract() -> None:
    schemas = {
        "openapi": create_app().openapi(),
        "parse_result": ParseResult.model_json_schema(),
        "error_response": ErrorResponse.model_json_schema(),
    }

    assert {
        name: sha256_bytes(canonical_payload_bytes(schema))
        for name, schema in schemas.items()
    } == EXPECTED_API_SCHEMA_HASHES


def test_production_parser_does_not_import_test_reporting_code() -> None:
    for path in (WORKSPACE / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "tests.benchmarks" not in source
        assert "baseline_report" not in source
