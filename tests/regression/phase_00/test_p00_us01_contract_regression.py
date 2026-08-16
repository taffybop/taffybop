"""Phase 00 regression gate for deterministic benchmark contracts."""

import json

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    Annotation,
    MetricRecord,
    MetricUnit,
    RunRecord,
    TruthClass,
    canonical_json,
)


def test_p00_us01_contract_output_is_stable_across_input_mapping_order() -> None:
    common = {
        "schema_version": CONTRACT_VERSION,
        "run_id": "stable",
        "parser_version": "1.0",
        "model_versions": {"layout": "1", "ocr": "none"},
        "commands": ("pytest",),
        "hardware": {"cpu": "test", "memory": "test"},
        "fixture_hashes": {"a": "a" * 64, "b": "b" * 64},
        "output_hashes": {"json": "d" * 64, "markdown": "c" * 64},
        "duration_ms": 0,
        "metrics": (
            MetricRecord(
                schema_version=CONTRACT_VERSION,
                metric_name="valid",
                measurement_method="synthetic-control",
                value=1,
                unit=MetricUnit.RATIO,
                tolerance=0,
                evidence_class=TruthClass.VISIBLE_TEXT,
            ),
        ),
    }
    reordered = {
        **dict(reversed(tuple(common.items()))),
        "model_versions": dict(reversed(tuple(common["model_versions"].items()))),
        "hardware": dict(reversed(tuple(common["hardware"].items()))),
        "fixture_hashes": dict(reversed(tuple(common["fixture_hashes"].items()))),
        "output_hashes": dict(reversed(tuple(common["output_hashes"].items()))),
    }

    ordered_record = RunRecord(**common)
    reordered_record = RunRecord(**reordered)

    assert json.dumps(ordered_record.model_dump(mode="json")) != json.dumps(
        reordered_record.model_dump(mode="json")
    )
    assert canonical_json(ordered_record) == canonical_json(reordered_record)


def test_p00_us01_measured_evidence_never_becomes_literal_exact_parity() -> None:
    with pytest.raises(ValidationError, match="cannot enter exact parity"):
        Annotation(
            schema_version=CONTRACT_VERSION,
            annotation_id="measured-chart-value",
            fixture_id="synthetic-chart",
            truth_class=TruthClass.MEASURED,
            claim="A vector-measured value with tolerance.",
            include_in_exact_parity=True,
        )
