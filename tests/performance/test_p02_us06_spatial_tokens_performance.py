from __future__ import annotations

import json
import math
import time
from copy import deepcopy

import pytest

from app.services import spatial_tokens as spatial_module
from app.services.spatial_tokens import (
    MAX_SPATIAL_OCCURRENCE_JSON_BYTES,
    MAX_SPATIAL_SOURCE_TOKENS,
    MAX_SPATIAL_TOKEN_OCCURRENCES,
    geometry_aware_unique_line_values,
)
from tests.stories.phase_02.test_p02_us06_spatial_tokens import (
    YEAR_LABELS,
    _bbox,
    _diagnostic,
    _line,
    _project,
    _token,
)
from tests.benchmarks import spatial_token_metrics as spatial_metrics


def _nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(len(ordered) * percentile) - 1, 0)]


def test_twelve_position_projection_is_deterministic_and_low_latency() -> None:
    tokens = [
        _token(
            text,
            _bbox(float(index * 38), width=24.0),
            word_index=index,
        )
        for index, text in enumerate(YEAR_LABELS)
    ]
    line = _line(
        " ".join(YEAR_LABELS),
        _bbox(0.0, width=450.0),
        tokens=tokens,
    )

    expected, expected_summary = _project([line], [_diagnostic()])
    durations_ms: list[float] = []
    for _sample in range(25):
        started = time.perf_counter_ns()
        occurrences, summary = _project(
            [deepcopy(line)],
            [_diagnostic()],
        )
        durations_ms.append(
            (time.perf_counter_ns() - started) / 1_000_000
        )
        assert occurrences == expected
        assert summary == expected_summary

    assert len(expected) == 12
    assert _nearest_rank(durations_ms, 0.95) < 50.0


def test_maximum_distant_repetition_projection_remains_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_payload_bound = 4 * MAX_SPATIAL_OCCURRENCE_JSON_BYTES
    monkeypatch.setattr(
        spatial_module,
        "MAX_SPATIAL_OCCURRENCE_JSON_BYTES",
        isolated_payload_bound,
    )
    tokens = [
        _token(
            "HEADER",
            _bbox(float(index * 2), width=1.0),
            word_index=index,
        )
        for index in range(MAX_SPATIAL_TOKEN_OCCURRENCES)
    ]
    line = _line(
        "distant repeated header",
        _bbox(0.0, width=5_000.0),
        tokens=tokens,
    )

    started = time.perf_counter_ns()
    occurrences, summary = _project(
        [line],
        [_diagnostic()],
        owner_bbox=_bbox(0.0, 0.0, 5_000.0, 100.0),
    )
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000
    serialized = json.dumps(
        occurrences,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert len(occurrences) == MAX_SPATIAL_TOKEN_OCCURRENCES
    assert summary["selected_occurrences"] == MAX_SPATIAL_TOKEN_OCCURRENCES
    assert summary["duplicate_occurrences"] == 0
    assert summary["occurrence_limit_reached"] is False
    assert len(serialized) <= isolated_payload_bound
    assert duration_ms < 1_000.0


def test_geometry_aware_line_dedup_avoids_quadratic_distant_scan() -> None:
    values = [
        (
            "HEADER",
            _bbox(float(index * 2), width=1.0, height=1.0),
        )
        for index in range(MAX_SPATIAL_SOURCE_TOKENS)
    ]

    started = time.perf_counter_ns()
    retained = geometry_aware_unique_line_values(values)
    duration_ms = (time.perf_counter_ns() - started) / 1_000_000

    assert retained == ["HEADER"] * MAX_SPATIAL_SOURCE_TOKENS
    assert duration_ms < 1_000.0


def test_metrics_runner_rejects_accepted_policy_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        spatial_metrics,
        "_input_identities",
        lambda _workspace: {
            spatial_metrics.SPATIAL_TOKEN_POLICY: {
                "path": spatial_metrics.SPATIAL_TOKEN_POLICY,
                "sha256": "0" * 64,
                "size_bytes": 1,
            }
        },
    )

    with pytest.raises(
        RuntimeError,
        match="accepted spatial-token policy identity mismatch",
    ):
        spatial_metrics._collect(tmp_path, warmups=0, samples=1)


def test_metrics_output_rejects_input_collision_and_writes_atomically(
    tmp_path,
) -> None:
    workspace = spatial_metrics.Path(__file__).resolve().parents[3]
    policy = workspace / spatial_metrics.SPATIAL_TOKEN_POLICY

    with pytest.raises(ValueError, match="output collides"):
        spatial_metrics._validated_output_path(workspace, policy)

    output = tmp_path / "nested" / "metrics.json"
    spatial_metrics._atomic_write_text(output, '{"complete":true}\n')

    assert output.read_text(encoding="utf-8") == '{"complete":true}\n'
    assert not list(output.parent.glob(f".{output.name}.*.tmp"))
