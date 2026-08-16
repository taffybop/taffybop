"""Focused ownership contracts for the bounded P04-US01 C optimization."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.services import table_semantics
from tests.contract.test_p04_us01_table_semantics_runtime_contract import (
    _seal,
    _spanned_table,
)


_SNAPSHOT_KEY = "_p04_predecessor_snapshot"


def _marked_table(*, item_id: str, reading_order: int) -> dict[str, Any]:
    table = _seal(_spanned_table(), finalize=False)
    table["id"] = item_id
    table["reading_order"] = reading_order
    snapshot = table[_SNAPSHOT_KEY]
    snapshot["id"] = item_id
    snapshot["reading_order"] = reading_order
    return table


def _pages(*tables: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "page_index": 1,
            "page_number": 1,
            "page_label": "1",
            "page_width": 300.0,
            "page_height": 120.0,
            "unit": "pt",
            "success": True,
            "items": list(tables),
            "warnings": [],
        }
    ]


def test_detach_holds_snapshot_free_overlay_and_splits_cross_aliases() -> None:
    table = _marked_table(item_id="table-0", reading_order=0)
    snapshot = table[_SNAPSHOT_KEY]
    # Untrusted plain data may share a non-cyclic nested container.  The held
    # overlay, frozen predecessor, and installed predecessor must nevertheless
    # become three independent ownership domains.
    table["bbox"] = snapshot["bbox"]
    assert table["bbox"] is snapshot["bbox"]
    pages = _pages(table)
    expected_predecessor = deepcopy(snapshot)

    transaction = table_semantics.detach_table_overlays_for_phase03(
        pages,
        deadline=table_semantics.perf_counter() + 2.0,
    )

    held_overlay = transaction[0][5]
    frozen_predecessor = transaction[0][6]
    installed_predecessor = pages[0]["items"][0]
    assert _SNAPSHOT_KEY not in held_overlay
    assert held_overlay["bbox"] == frozen_predecessor["bbox"]
    assert installed_predecessor == expected_predecessor
    assert held_overlay["bbox"] is not frozen_predecessor["bbox"]
    assert held_overlay["bbox"] is not installed_predecessor["bbox"]
    assert frozen_predecessor["bbox"] is not installed_predecessor["bbox"]

    held_overlay["bbox"]["x"] += 1.0
    assert frozen_predecessor["bbox"] == expected_predecessor["bbox"]
    assert installed_predecessor["bbox"] == expected_predecessor["bbox"]
    frozen_predecessor["bbox"]["y"] += 1.0
    assert installed_predecessor["bbox"] == expected_predecessor["bbox"]


@pytest.mark.parametrize(
    "failure",
    (
        TimeoutError("injected snapshot-free overlay timeout"),
        MemoryError("injected snapshot-free overlay resource failure"),
    ),
    ids=("timeout", "resource"),
)
def test_detach_snapshot_free_staging_failure_is_atomic(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    pages = _pages(
        _marked_table(item_id="table-0", reading_order=0),
        _marked_table(item_id="table-1", reading_order=1),
    )
    before = deepcopy(pages)
    original_validate = table_semantics._validate_plain_table_value
    calls = 0

    def fail_second_overlay(
        value: Any,
        deadline: float,
    ) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise failure
        return original_validate(value, deadline)

    monkeypatch.setattr(
        table_semantics,
        "_validate_plain_table_value",
        fail_second_overlay,
    )

    with pytest.raises(type(failure), match="snapshot-free overlay"):
        table_semantics.detach_table_overlays_for_phase03(
            pages,
            deadline=table_semantics.perf_counter() + 2.0,
        )

    assert calls == 2
    assert pages == before


def test_detach_rejects_forbidden_delta_atomically() -> None:
    first = _marked_table(item_id="table-0", reading_order=0)
    second = _marked_table(item_id="table-1", reading_order=1)
    second["embedded_images"] = [{"id": "forged-p04-image"}]
    pages = _pages(first, second)
    before = deepcopy(pages)

    with pytest.raises(ValueError, match="table overlay P04 delta differs"):
        table_semantics.detach_table_overlays_for_phase03(
            pages,
            deadline=table_semantics.perf_counter() + 2.0,
        )

    assert pages == before
