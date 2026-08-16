"""Real-document regression coverage for P03-US01."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"

EXPECTED = {
    "catastrophe-recap": [
        (
            1,
            "EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025",
            (100.700, 210.095, 250.220, 9.351),
        )
    ],
    "clinical-study": [
        (
            2,
            "Table 1. Demographic and baseline characteristics.",
            (36.000, 77.922, 169.539, 6.700),
        ),
        (
            4,
            (
                "Table 2. Pooled results from linear mixed models for "
                "primary and secondary outcomes ( N = 538, based on "
                "multiple imputation)."
            ),
            (36.000, 77.922, 424.521, 7.316),
        ),
    ],
}


def _settings(enabled: bool) -> Settings:
    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=enabled,
    )


@lru_cache(maxsize=None)
def _parse(case: str, enabled: bool) -> dict[str, Any]:
    path = CORPUS / f"{case}.pdf"
    return parse_document(
        path.read_bytes(),
        path.name,
        _settings(enabled),
    ).model_dump(mode="json", exclude_none=False)


@pytest.mark.integration
@pytest.mark.parametrize("case", ["catastrophe-recap", "clinical-study"])
def test_real_external_table_captions_are_grounded_once(case: str) -> None:
    payload = _parse(case, True)
    actual = []
    for page in payload["pages"]:
        for position, item in enumerate(page["items"]):
            if item["type"] != "caption":
                continue
            owner_id = item["caption_of"]
            owner_position = next(
                index
                for index, candidate in enumerate(page["items"])
                if candidate["id"] == owner_id
            )
            assert owner_position == position + 1
            owner = page["items"][owner_position]
            assert owner["type"] == "table"
            assert item["id"] in owner["caption_ids"]
            assert item["id"] in owner["caption_of"]
            assert any(
                relationship["type"] == "caption_of"
                and relationship["source_id"] == item["id"]
                and relationship["target_id"] == owner["id"]
                for relationship in owner["relationships"]
            )
            box = item["bbox"]
            actual.append(
                (
                    page["page_index"],
                    item["value"],
                    (
                        box["x"],
                        box["y"],
                        box["width"],
                        box["height"],
                    ),
                )
            )
    assert actual == EXPECTED[case]

    markdown = to_markdown(payload)
    for _page, caption, _bbox in EXPECTED[case]:
        assert markdown.count(caption) == 1


@pytest.mark.integration
@pytest.mark.parametrize("case", ["catastrophe-recap", "clinical-study"])
def test_real_table_rows_and_cells_are_identical_flag_on_off(case: str) -> None:
    enabled = _parse(case, True)
    disabled = _parse(case, False)

    enabled_tables = [
        (item["rows"], item["cells"])
        for page in enabled["pages"]
        for item in page["items"]
        if item["type"] == "table"
    ]
    disabled_tables = [
        (item["rows"], item["cells"])
        for page in disabled["pages"]
        for item in page["items"]
        if item["type"] == "table"
    ]
    assert enabled_tables == disabled_tables
    assert not [
        item
        for page in disabled["pages"]
        for item in page["items"]
        if item["type"] == "caption"
    ]


@pytest.mark.integration
def test_finance_non_target_is_exact_with_flag_on_and_off() -> None:
    enabled = _parse("finance-10k", True)
    disabled = _parse("finance-10k", False)

    enabled_content = {
        **enabled,
        "processing": {
            **enabled["processing"],
            "duration_ms": 0,
        },
    }
    disabled_content = {
        **disabled,
        "processing": {
            **disabled["processing"],
            "duration_ms": 0,
        },
    }
    assert enabled_content == disabled_content
    assert to_markdown(enabled) == to_markdown(disabled)
    assert not [
        item
        for page in enabled["pages"]
        for item in page["items"]
        if item["type"] == "caption"
    ]
