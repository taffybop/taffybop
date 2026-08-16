"""Contract for the frozen P02-US06 spatial-token metrics artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
ARTIFACT = (
    WORKSPACE
    / "tracker/phase-02-text-integrity/evidence/"
    "P02-US06-spatial-token-metrics.json"
)
EXPECTED_SHA256 = (
    "3d13129a80bdd24e01cb1f9f41b3fe3286d5662fd797a58760a647d6d79d5900"
)
EXPECTED_SEMANTIC_SHA256 = (
    "5deccf8a57f0e97ba119228c9709d537c92ef0b2df186acce87d34742588d7c5"
)
SUCCESSOR_OWNED_INPUTS = frozenset(
    {
        ".env.example",
        "README.md",
        "app/config.py",
        "app/services/ocr.py",
        "app/services/pipeline.py",
    }
)
EXPECTED_YEAR_ROWS = (
    ("2015", 125.021, 562.51, 13.4, 4.6, 0.9633),
    ("2020", 165.421, 562.51, 14.6, 4.4, 0.9666),
    ("2025", 206.621, 562.51, 14.4, 4.6, 0.9650),
    ("2015", 232.021, 562.51, 13.4, 4.6, 0.9620),
    ("2020", 272.421, 562.51, 14.6, 4.4, 0.9685),
    ("2025", 313.621, 562.51, 14.6, 4.6, 0.9654),
    ("2015", 339.021, 562.51, 13.4, 4.6, 0.9618),
    ("2020", 379.621, 562.51, 14.6, 4.4, 0.9689),
    ("2025", 420.621, 562.51, 14.6, 4.6, 0.9657),
    ("2015", 446.221, 562.51, 13.4, 4.6, 0.9633),
    ("2020", 486.621, 562.51, 14.6, 4.4, 0.9666),
    ("2025", 527.621, 562.51, 14.6, 4.6, 0.9688),
)


def _artifact() -> dict[str, object]:
    content = ARTIFACT.read_bytes()
    assert len(content) == 51_298
    assert hashlib.sha256(content).hexdigest() == EXPECTED_SHA256
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload


def test_retained_spatial_token_artifact_has_exact_custody() -> None:
    payload = _artifact()

    assert payload["schema_version"] == "1.0"
    assert payload["record_kind"] == (
        "p02_us06_spatial_token_component_metrics"
    )
    assert payload["warmups"] == 2
    assert payload["samples"] == 10

    custody = payload["custody"]
    assert isinstance(custody, dict)
    assert custody["pre_post_input_identity_match"] is True
    assert custody["accepted_policy"]["sha256"] == (
        "1d0544f55df543ea010a22ef0379e90abb13256df4c2388032cd975715e10741"
    )
    assert custody["retained_p02_us05"]["artifact"]["sha256"] == (
        "5b347a6f98c47d9df3b52cfef40bb5c6bb5824f149cc8da6806cc23d5e3a174c"
    )

    run_inputs = payload["run_inputs"]
    assert isinstance(run_inputs, dict)
    assert len(run_inputs) == 16
    assert len(run_inputs) == len(set(run_inputs))
    assert SUCCESSOR_OWNED_INPUTS < set(run_inputs)
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

    # The raw artifact hash authenticates every exact at-run snapshot. Later
    # Phase 02 exit and Phase 03 stories own only these shared surfaces; all
    # US06-specific policy, implementation, target, runner, and tests remain
    # live-bound here.
    assert changed_since_seal == SUCCESSOR_OWNED_INPUTS


def test_retained_spatial_token_target_is_exact() -> None:
    payload = _artifact()
    semantic = payload["semantic_results"]
    assert isinstance(semantic, dict)
    target = semantic["target"]
    assert isinstance(target, dict)
    occurrences = target["occurrences"]
    assert isinstance(occurrences, list)
    assert len(occurrences) == 13

    years = target["year_occurrences"]
    assert isinstance(years, list)
    assert len(years) == len(EXPECTED_YEAR_ROWS)
    for occurrence, expected in zip(
        years,
        EXPECTED_YEAR_ROWS,
        strict=True,
    ):
        text, x, y, width, height, confidence = expected
        assert occurrence["text"] == text
        assert occurrence["bbox"] == {
            "x": x,
            "y": y,
            "w": width,
            "h": height,
            "width": width,
            "height": height,
            "unit": "pt",
        }
        assert occurrence["confidence"] == confidence
        assert occurrence["selected"] is True
        assert occurrence["primary_selected"] is True
        assert occurrence["short_alternative"] is False
        assert occurrence.get("duplicate_of") is None

    ih = target["ih_occurrences"]
    assert isinstance(ih, list)
    assert len(ih) == 1
    assert ih[0]["text"] == "iH"
    assert ih[0]["confidence"] == 0.4437
    assert ih[0]["bbox"] == {
        "x": 157.421,
        "y": 575.71,
        "w": 14.6,
        "h": 5.8,
        "width": 14.6,
        "height": 5.8,
        "unit": "pt",
    }
    assert ih[0]["selected"] is True
    assert ih[0]["primary_selected"] is False
    assert ih[0]["short_alternative"] is True
    assert ih[0].get("duplicate_of") is None

    assert target["summary"] == {
        "schema_version": "1.0",
        "total_occurrences": 13,
        "selected_occurrences": 13,
        "primary_selected_occurrences": 12,
        "duplicate_occurrences": 0,
        "short_alternative_occurrences": 1,
        "invalid_occurrences": 0,
        "oversized_text_occurrences": 0,
        "truncated_occurrences": 0,
        "occurrence_limit_reached": False,
        "short_alternative_limit_reached": False,
        "source_token_limit_reached": False,
        "serialized_byte_limit_reached": False,
        "serialized_occurrence_bytes": 5921,
        "fail_closed_overflow": False,
        "overflow_reason": None,
    }


def test_retained_spatial_token_artifact_meets_acceptance() -> None:
    payload = _artifact()
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)

    assert metrics["retained_target_occurrence_count"] == 13
    assert metrics["retained_target_partition_exact"] is True
    assert metrics["retained_target_summary_exact"] is True
    assert metrics["retained_year_occurrence_count"] == 12
    assert (
        metrics["retained_year_text_bbox_confidence_exact_count"] == 12
    )
    assert metrics["retained_year_unique_occurrence_id_count"] == 12
    assert metrics["retained_year_selected_count"] == 12
    assert metrics["retained_year_primary_selected_count"] == 12
    assert metrics["retained_ih_occurrence_count"] == 1
    assert metrics["retained_ih_exact"] is True
    assert metrics["retained_ih_grounded_short_alternative"] is True
    assert metrics["retained_ih_selected"] is True
    assert metrics["retained_ih_primary_selected"] is False
    assert metrics["overlap_candidate_count"] == 2
    assert metrics["overlap_selected_representative_count"] == 1
    assert metrics["overlap_duplicate_diagnostic_count"] == 1
    assert metrics["overlap_duplicate_primary_token_count"] == 0
    assert metrics["distant_repeated_line_value_count"] == 2
    assert metrics["distant_repeated_token_occurrence_count"] == 4
    assert metrics["grounded_short_alternative_count"] == 2
    assert metrics["negative_short_alternative_count"] == 0
    assert metrics["canonical_unsupported_short_noise_count"] == 0
    assert metrics["target_canonical_flag_on_off_parity"] is True
    assert metrics["target_flag_off_additive_keys_absent"] is True
    assert metrics["serialized_payload_bound_respected"] is True
    assert metrics["short_alternative_bound_exact"] is True
    assert metrics["source_token_bound_exact"] is True
    assert metrics["semantic_output_size_bytes"] == 23_613
    assert metrics["semantic_output_sha256"] == EXPECTED_SEMANTIC_SHA256
    assert metrics["hosted_model_request_count"] == 0
    assert metrics["hosted_model_token_count"] == 0
    assert metrics["hosted_model_cost_usd"] == 0.0

    ceiling = metrics["combined_healthy_p95_ceiling_reference"]
    assert isinstance(ceiling, dict)
    assert ceiling["observed_paired_full_parser_percentile"] is False
    assert ceiling["arithmetic_ceiling_percent"] <= 10.0
    assert ceiling["passes_target"] is True
