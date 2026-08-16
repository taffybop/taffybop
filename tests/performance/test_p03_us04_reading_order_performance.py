"""Bounded performance and metrics-harness checks for P03-US04."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.benchmarks.layout_reading_order_metrics import (
    ALL_CASES,
    CODE_PATHS,
    DEFAULT_ARTIFACT_RELATIVE_PATH,
    EXPECTED_INPUTS,
    HOSTED_USAGE,
    PERFORMANCE_CASES,
    PHASE_02_PERFORMANCE_BASELINES,
    REVIEWED_CASES,
    REVIEWED_PAIR_SLICES,
    WORKSPACE,
    _all_input_custody,
    _artifact_semantic_payload,
    _canonical_json,
    _case_quality_summary,
    _code_custody,
    _dependency_custody,
    _paired_performance_summary,
    _paired_states,
    _parse_args,
    _settings,
    _settings_delta,
    _worker_command,
    _write_json_atomic,
    generate_boundary_metrics,
    generate_rollback_metrics,
    generate_stage_metrics,
)


def test_reviewed_oracle_and_all_input_identities_are_fixed() -> None:
    top_level_count = sum(
        len(pairs)
        for _case, _page_index, pairs in REVIEWED_PAIR_SLICES
    )

    assert len(REVIEWED_CASES) == 9
    assert len(REVIEWED_PAIR_SLICES) == 10
    assert top_level_count == 40
    assert top_level_count + 1 == 41
    assert set(REVIEWED_CASES) == set(EXPECTED_INPUTS) - {
        "uber-earnings"
    }
    assert ALL_CASES == (*REVIEWED_CASES, "uber-earnings")
    assert PERFORMANCE_CASES == (
        "manufacturing-report",
        "uber-earnings",
    )

    custody = _all_input_custody(WORKSPACE)

    assert set(custody) == set(ALL_CASES)
    assert all(record["exact_match"] for record in custody.values())
    assert all(
        record["observed"]["sha256"]
        == record["expected"]["sha256"]
        and record["observed"]["size_bytes"]
        == record["expected"]["size_bytes"]
        for record in custody.values()
    )


def test_settings_enable_us01_us03_and_toggle_only_us04() -> None:
    disabled = _settings(False)
    enabled = _settings(True)
    delta = _settings_delta()

    assert disabled.layout_table_captions_enabled is True
    assert disabled.layout_visual_relationships_enabled is True
    assert disabled.layout_source_notes_enabled is True
    assert disabled.layout_relationship_order_enabled is False
    assert enabled.layout_relationship_order_enabled is True
    assert delta == {
        "changed_fields": ["layout_relationship_order_enabled"],
        "flag_off": {"layout_relationship_order_enabled": False},
        "flag_on": {"layout_relationship_order_enabled": True},
        "accepted_predecessor_flags_enabled": True,
    }


def test_paired_gate_uses_clipped_nonnegative_inclusive_p95() -> None:
    off = [
        {"wall_seconds": 10.0, "peak_rss_bytes": 1000}
        for _ in range(5)
    ]
    on = [
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 10.7, "peak_rss_bytes": 1100},
    ]

    summary = _paired_performance_summary(
        off,
        on,
        baseline_seconds=10.0,
        baseline_rss_mib=123.0,
    )

    assert summary["pair_count"] == 5
    assert summary["quantile_method"] == "empirical_p95_inclusive"
    assert summary["gate_value"] == (
        "p95_of_clipped_nonnegative_paired_overhead"
    )
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
    assert summary["phase_02_peak_rss_baseline_mib"] == 123.0
    assert [_paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]


def test_phase_02_performance_and_rss_baselines_are_exact() -> None:
    assert PHASE_02_PERFORMANCE_BASELINES == {
        "manufacturing-report": {
            "wall_seconds": 11.58,
            "five_percent_ceiling_seconds": 0.579,
            "peak_rss_mib": 1825.8,
        },
        "uber-earnings": {
            "wall_seconds": 29.15,
            "five_percent_ceiling_seconds": 1.4575,
            "peak_rss_mib": 2589.5,
        },
    }
    assert all(
        baseline["five_percent_ceiling_seconds"]
        == pytest.approx(baseline["wall_seconds"] * 0.05)
        for baseline in PHASE_02_PERFORMANCE_BASELINES.values()
    )
    for baseline in PHASE_02_PERFORMANCE_BASELINES.values():
        samples = [
            {
                "wall_seconds": baseline["wall_seconds"],
                "peak_rss_bytes": 1,
            }
            for _ in range(5)
        ]
        summary = _paired_performance_summary(
            samples,
            samples,
            baseline_seconds=baseline["wall_seconds"],
            baseline_rss_mib=baseline["peak_rss_mib"],
        )
        assert summary["five_percent_ceiling_seconds"] == (
            baseline["five_percent_ceiling_seconds"]
        )


def test_artifact_semantic_digest_excludes_only_run_metadata() -> None:
    first = {
        "story": "P03-US04",
        "generated_at": "2026-07-31T00:00:00+00:00",
        "semantic_sha256": "first",
        "aggregate": {"reviewed_pair_matched": 41},
    }
    second = {
        **first,
        "generated_at": "2026-08-01T00:00:00+00:00",
        "semantic_sha256": "second",
    }

    assert _canonical_json(_artifact_semantic_payload(first)) == (
        _canonical_json(_artifact_semantic_payload(second))
    )

    changed = deepcopy(second)
    changed["aggregate"]["reviewed_pair_matched"] = 40
    assert _canonical_json(_artifact_semantic_payload(first)) != (
        _canonical_json(_artifact_semantic_payload(changed))
    )


def test_isolated_stage_profile_meets_time_and_allocation_gates() -> None:
    metrics = generate_stage_metrics()

    assert metrics["warmup_count"] == 5
    assert metrics["sample_count"] == 100
    assert metrics["anchor_count"] == 64
    assert 0 < metrics["p50_seconds"] <= metrics["p95_seconds"]
    assert metrics["p95_seconds"] <= metrics["max_seconds"]
    assert metrics["p95_seconds"] <= 0.050
    assert metrics["within_p95_ceiling"] is True
    assert metrics["peak_allocated_bytes"] < 32 * 1024 * 1024
    assert metrics["within_peak_allocation_ceiling"] is True
    assert metrics["exact_order"] is True


def test_maximum_512_anchor_boundary_sample_meets_250ms_gate() -> None:
    metrics = generate_boundary_metrics()

    assert metrics["anchor_count"] == metrics["anchor_limit"] == 512
    assert metrics["sample_count"] == 1
    assert 0 < metrics["elapsed_seconds"] <= 0.250
    assert metrics["within_ceiling"] is True
    assert metrics["exact_order"] is True
    assert metrics["unique_anchor_count"] == 512
    assert metrics["contiguous_reading_order"] is True


def test_overflow_rollback_is_exact_sanitized_and_idempotent() -> None:
    metrics = generate_rollback_metrics()

    assert metrics == {
        "overflow_anchor_count": 513,
        "anchor_limit": 512,
        "exact_predecessor_restored": True,
        "concern_count": 1,
        "concern_codes": ["relationship_order_page_limit"],
        "concerns_sanitized": True,
        "repeated_projection_idempotent": True,
    }


def _sample(
    *,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "wall_seconds": 1.0,
        "peak_rss_bytes": 1024,
        "serialization": {
            "json_round_trip_equal": True,
            "json_sha256": "json",
            "semantic_json_sha256": "semantic",
            "markdown_sha256": "markdown",
            "canonical_sha256": "canonical",
        },
        "quality": {
            "reading_order_contiguous_all_pages": True,
            "canonical_order_matches_public_all_pages": True,
            "markdown_equals_canonical_markdown": True,
            "duplicate_public_item_id_count": 0,
            "pair_oracle": {
                "expected_pair_count": 0,
                "matched_pair_count": 0,
                "all_pairs_matched": True,
                "results": [],
            },
            "keyed_item_sha256": {"1:item": "item-sha"},
            "keyed_canonical_block_sha256": {
                "1:item": "block-sha"
            },
            "canonical_primary_by_public_id": {
                "1:item": "element-id"
            },
            "page_metadata_sha256": {"1": "page-sha"},
            "document_metadata_sha256": "document-sha",
            "page_order": [],
            "rollback_projection_absent": not enabled,
        },
        **HOSTED_USAGE,
    }


def test_quality_summary_is_exact_across_json_markdown_canonical_and_order(
) -> None:
    summary = _case_quality_summary(
        "uber-earnings",
        [_sample(enabled=False)],
        [_sample(enabled=True)],
    )

    assert summary["json"][
        "keyed_items_equal_outside_accepted_corrections"
    ] is True
    assert summary["json"]["page_metadata_exact"] is True
    assert summary["json"]["document_metadata_exact"] is True
    assert summary["markdown"][
        "all_flag_on_matches_canonical"
    ] is True
    assert summary["canonical"][
        "keyed_blocks_equal_outside_accepted_corrections"
    ] is True
    assert summary["canonical"][
        "primary_identity_by_public_id_exact"
    ] is True
    assert summary["order"]["reviewed_pair_expected"] == 0
    assert summary["order"]["reviewed_pair_matched"] == 0
    assert summary["rollback"][
        "all_flag_off_samples_projection_absent"
    ] is True
    assert summary["all_keyed_mutation_within_policy"] is True


def test_custody_hashes_hosted_usage_and_atomic_worker_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert HOSTED_USAGE == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
    code = _code_custody(WORKSPACE)
    assert tuple(code) == CODE_PATHS
    assert all(
        len(digest) == 64
        and set(digest) <= set("0123456789abcdef")
        for digest in code.values()
    )

    executable = tmp_path / "tesseract"
    executable.write_bytes(b"fixed executable")
    monkeypatch.setattr(
        "tests.benchmarks.layout_reading_order_metrics."
        "importlib_metadata.version",
        lambda package: f"{package}-version",
    )
    monkeypatch.setattr(
        "tests.benchmarks.layout_reading_order_metrics.shutil.which",
        lambda _name: str(executable),
    )
    monkeypatch.setattr(
        "tests.benchmarks.layout_reading_order_metrics.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="tesseract 5.0\n",
        ),
    )
    dependencies = _dependency_custody()
    assert dependencies["tesseract"]["sha256"] == hashlib.sha256(
        b"fixed executable"
    ).hexdigest()
    assert set(dependencies["python_packages"]) == {
        "docling",
        "docling-core",
        "pdfplumber",
        "pydantic",
    }
    assert set(dependencies["dependency_manifest_sha256"]) == {
        "pyproject.toml",
        "uv.lock",
        "frontend/package-lock.json",
    }
    assert all(
        len(digest) == 64
        for digest in dependencies[
            "dependency_manifest_sha256"
        ].values()
    )

    output = tmp_path / "nested" / "artifact.json"
    _write_json_atomic(output, {"answer": 41})
    assert output.read_text(encoding="utf-8") == (
        '{\n  "answer": 41\n}\n'
    )
    assert not list(output.parent.glob("*.tmp"))

    command = _worker_command(
        WORKSPACE,
        "manufacturing-report",
        True,
        output,
    )
    assert command[-8:] == [
        "--workspace",
        str(WORKSPACE),
        "--worker-case",
        "manufacturing-report",
        "--worker-enabled",
        "true",
        "--output",
        str(output),
    ]
    parsed = _parse_args(
        [
            "--worker-case",
            "manufacturing-report",
            "--worker-enabled",
            "false",
            "--output",
            str(output),
        ]
    )
    assert parsed.worker_case == "manufacturing-report"
    assert parsed.worker_enabled == "false"
    assert parsed.output == output
    assert DEFAULT_ARTIFACT_RELATIVE_PATH == Path(
        "tracker/phase-03-layout/evidence/"
        "P03-US04-reading-order-metrics.json"
    )


def test_worker_cli_rejects_incomplete_modes() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--worker-case", "manufacturing-report"])
    with pytest.raises(SystemExit):
        _parse_args(["--worker-enabled", "true"])
