from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.services.pipeline import _merge_body_items
from app.services.tables import _page_candidates


class _FakeTable:
    def __init__(
        self,
        bbox: tuple[float, float, float, float],
        rows: list[list[str]],
        row_bboxes: list[tuple[float, float, float, float]],
    ) -> None:
        self.bbox = bbox
        self.rows = [SimpleNamespace(bbox=row_bbox) for row_bbox in row_bboxes]
        self._extracted = rows

    def extract(self, **_kwargs: Any) -> list[list[str]]:
        return self._extracted


class _FakePage:
    rects: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []

    def __init__(self, tables: list[_FakeTable]) -> None:
        self._tables = tables

    def filter(self, _predicate: Any) -> _FakePage:
        return self

    def find_tables(self, _settings: Any = None) -> list[_FakeTable]:
        return self._tables


def test_standard_finder_rejects_ragged_single_column_text_boxes() -> None:
    table = _FakeTable(
        (81.024, 330.53, 540.816, 372.77),
        [
            ["Subject Number: 1190014"],
            [
                "Mapped route is not getting derived through configured rule "
                "for CRF: LOGS > Prior and"
            ],
            ["Concomitant Medications, Log line#16 after"],
        ],
        [
            (81.024, 330.53, 214.484, 344.66),
            (81.024, 344.66, 540.816, 360.05),
            (81.024, 360.05, 302.684, 372.77),
        ],
    )

    assert _page_candidates(_FakePage([table]), 7) == []


def test_standard_finder_keeps_uniform_single_column_table() -> None:
    table = _FakeTable(
        (72.264, 112.7, 534.58, 304.85),
        [["Approver"], ["Signed by Example User"]],
        [
            (72.264, 112.7, 534.58, 208.775),
            (72.264, 208.775, 534.58, 304.85),
        ],
    )

    candidates = _page_candidates(_FakePage([table]), 3)

    assert len(candidates) == 1
    assert candidates[0].table.rows == [
        ["Approver"],
        ["Signed by Example User"],
    ]


def test_standard_finder_keeps_multicolumn_table() -> None:
    table = _FakeTable(
        (72.0, 100.0, 540.0, 150.0),
        [["Name", "Role"], ["Example User", "Reviewer"]],
        [
            (72.0, 100.0, 540.0, 125.0),
            (72.0, 125.0, 540.0, 150.0),
        ],
    )

    candidates = _page_candidates(_FakePage([table]), 1)

    assert len(candidates) == 1
    assert candidates[0].table.rows[0] == ["Name", "Role"]


def test_partial_table_text_cannot_suppress_complete_body_text() -> None:
    complete_text = (
        "Mapped route is not getting derived through configured rule for CRF: "
        "LOGS > Prior and Concomitant Medications, Log line#16 after data entry "
        "for Route of Administration item is done"
    )
    subject_text = "Subject Number: 1190014"
    pages = [{"page_index": 7, "warnings": []}]
    body_items = {
        7: [
            {
                "type": "heading",
                "value": subject_text,
                "md": f"## {subject_text}",
                "bbox": {"x": 81.024, "y": 333.0, "width": 136.0, "height": 12.0},
                "source": "native",
                "confidence": None,
                "_sequence": 1,
            },
            {
                "type": "text",
                "value": complete_text,
                "md": complete_text,
                "bbox": {
                    "x": 81.024,
                    "y": 349.733,
                    "width": 462.112,
                    "height": 35.222,
                },
                "source": "native",
                "confidence": None,
                "_sequence": 2,
            },
        ]
    }
    tables = {
        7: [
            {
                "type": "table",
                "rows": [
                    [subject_text],
                    [
                        "Mapped route is not getting derived through configured "
                        "rule for CRF: LOGS > Prior and"
                    ],
                    ["Concomitant Medications, Log line#16 after"],
                ],
                "bbox": {
                    "x": 81.024,
                    "y": 330.53,
                    "width": 459.792,
                    "height": 42.24,
                },
                "source": "native",
            }
        ]
    }

    _merge_body_items(
        pages,
        body_items,
        tables,
        image_regions={},
        headers={},
        footers={},
    )

    values = [item.get("value") for item in pages[0]["items"]]
    assert complete_text in values
    assert subject_text in values
