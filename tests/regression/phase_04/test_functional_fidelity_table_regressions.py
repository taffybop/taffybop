"""Source-grounded table regressions discovered by the fidelity benchmark."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.services import pipeline
from app.services.tables import extract_vector_tables


WORKSPACE = Path(__file__).resolve().parents[3]
TIMETABLE = WORKSPACE / "benchmark-expertmodeldata" / "ny-timetable.pdf"
TIMETABLE_SHA256 = (
    "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30"
)
TIMETABLE_HEADER = [
    "Notes",
    "South Ferry",
    "Chambers St",
    "Times Sq 42 St",
    "66 St Lincoln Center",
    "96 St",
    "103 St",
    "137 St City College",
    "168 St Washington Hts",
    "Dyckman St",
    "215 St",
    "238 St",
    "Van Cortlandt Park 242 St",
]
HEALTH_REPORT = WORKSPACE / "benchmark-expertmodeldata" / "health-report.pdf"
HEALTH_REPORT_SHA256 = (
    "fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181"
)


def test_timetable_recovers_source_columns_and_visible_service_rows() -> None:
    source = TIMETABLE.read_bytes()
    assert hashlib.sha256(source).hexdigest() == TIMETABLE_SHA256

    tables_by_page = extract_vector_tables(
        source,
        preserve_cell_geometry=True,
    )

    assert set(tables_by_page) == {1, 2, 3}
    assert all(len(tables_by_page[page]) == 1 for page in (1, 2, 3))
    for page in (1, 2, 3):
        table = tables_by_page[page][0]
        assert table.logical_rows_recovered is True
        assert (len(table.rows), len(table.rows[0])) == (52, 13)
        assert all(len(row) == 13 for row in table.rows)
        assert len(table.row_bboxes) == 52
        assert len(table.cell_bboxes) == 52
        assert all(len(row) == 13 for row in table.cell_bboxes)
        assert table.rows[0] == ["Weekdays to The Bronx"] + [""] * 12
        assert table.rows[1] == TIMETABLE_HEADER

    assert tables_by_page[1][0].rows[2] == [
        "Mon",
        "12:00",
        "12:04",
        "12:17",
        "12:23",
        "12:28",
        "12:30",
        "12:36",
        "12:42",
        "12:46",
        "12:49",
        "12:56",
        "12:57",
    ]
    assert tables_by_page[3][0].rows[28] == [
        "",
        "3:01",
        "3:05",
        "3:18",
        "3:24",
        "3:30",
        "3:32",
        "3:38",
        "3:43",
        "3:48",
        "3:51",
        "3:55",
        "3:57",
    ]


def test_timetable_html_preserves_spanning_title_and_station_headers() -> None:
    table = extract_vector_tables(
        TIMETABLE.read_bytes(),
        preserve_cell_geometry=True,
    )[1][0]
    item = pipeline._vector_table_item(
        table,
        table_span_fidelity_enabled=True,
    )

    assert '<th colspan="13">Weekdays to The Bronx</th>' in item["html"]
    assert "<thead>" in item["html"]
    assert "<th>66 St Lincoln Center</th>" in item["html"]
    assert "<td>12:36</td>" in item["html"]
    assert "12:36 12:42" not in item["html"]


def test_visual_owned_empty_grid_has_no_user_facing_table_serialization() -> None:
    source = HEALTH_REPORT.read_bytes()
    assert hashlib.sha256(source).hexdigest() == HEALTH_REPORT_SHA256

    tables = extract_vector_tables(
        source,
        preserve_cell_geometry=True,
    )[1]
    empty_grid = next(
        table
        for table in tables
        if table.rows and not any(value for row in table.rows for value in row)
    )
    assert (len(empty_grid.rows), len(empty_grid.rows[0])) == (10, 1)

    item = pipeline._vector_table_item(
        empty_grid,
        table_span_fidelity_enabled=True,
    )

    # Keep source geometry as noncanonical gate evidence, but do not emit an
    # empty <table> into raw Markdown or the rendered Markdown surface.
    assert item["rows"] == empty_grid.rows
    assert item["html"] == ""
    assert item["md"] == ""
    assert item["csv"] == ""
