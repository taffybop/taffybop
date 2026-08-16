"""Regression controls for the immutable P00-US02 catastrophe truth."""

import json
from pathlib import Path

from tests.benchmarks.source_truth import (
    ArtifactRole,
    ChartSeries,
    load_catastrophe_source_truth,
)


WORKSPACE = Path(__file__).resolve().parents[3]
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)


def test_registered_expert_identity_is_not_replaced_by_stale_assessment_input() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    expert_json = next(
        artifact
        for artifact in truth.artifacts
        if artifact.role is ArtifactRole.EXPERT_JSON
    )

    assert (
        expert_json.sha256
        == "cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db"
    )
    assert expert_json.path == "benchmark-expertmodeldata/catastrophe-recap.json"
    assert len(truth.table_cells) == 30
    assert all(cell.row_span == 1 for cell in truth.table_cells)

    current_expert = json.loads((WORKSPACE / expert_json.path).read_text())
    items = current_expert["items"]["pages"][0]["items"]
    exhibit8_title = "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)"
    assert sum(item.get("value") == exhibit8_title for item in items) == 1

    exhibit7 = next(
        item
        for item in items
        if item.get("type") == "table"
        and item.get("rows", [[]])[0][0] == "Date(s)"
    )
    assert [row[2] for row in exhibit7["rows"][1:]] == [
        "United States",
    ] * 5
    assert "rowspan" not in json.dumps(exhibit7).lower()

    chart = next(
        item
        for item in items
        if item.get("type") == "table"
        and item.get("rows", [[]])[0] == [
            "Region",
            "Year",
            "Annual total",
            "1H",
        ]
    )
    assert len(chart["rows"][1:]) == 44
    assert all(
        float(annual_total) >= float(first_half)
        for _, _, annual_total, first_half in chart["rows"][1:]
    )


def test_source_measured_truth_preserves_safer_disagreement_with_expert() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    points = {
        (point.panel, point.year, point.series): point
        for point in truth.chart_measurements
    }

    # The current expert artifact says USA 2022 annual is 48. The reviewed PDF
    # vector geometry is about 118.10, so literal expert parity must stay off.
    reviewed = points[("USA", 2022, ChartSeries.ANNUAL_TOTAL)]
    assert reviewed.value == 118.10
    assert reviewed.tolerance == 1.0
    assert not reviewed.include_in_exact_parity
