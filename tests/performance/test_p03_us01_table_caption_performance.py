"""Bounded performance/resource checks for P03-US01."""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc

import app.services.layout as layout_service
from app.config import Settings
from app.services.ir import round_trip_document
from app.services.layout import apply_layout_projection
from tests.stories.phase_03.test_p03_us01_table_captions import (
    _box,
    _caption,
    _document,
    _enabled,
    _raw_graph,
    _table,
    _table_item,
)


PHASE_02_CATASTROPHE_SECONDS = 8.50
MAX_LAYOUT_OVERHEAD_SECONDS = PHASE_02_CATASTROPHE_SECONDS * 0.05


def _retained_ir(caption_count: int = 1):
    captions = [
        _caption(
            f"#/texts/{index}",
            f"Caption {index}",
            _box(10, 20 + index * 0.01, 55, 25 + index * 0.01),
        )
        for index in range(caption_count)
    ]
    raw = _raw_graph(
        captions=captions,
        tables=[
            _table(
                "#/tables/0",
                [str(caption["self_ref"]) for caption in captions],
                box=_box(10, 30, 80, 60),
            )
        ],
    )
    _, ir = round_trip_document(
        _document(_table_item()),
        raw_graph=raw,
        native_texts=(" ".join(f"Caption {i}" for i in range(caption_count)),),
    )
    return ir


def _many_owner_ir(
    owner_count: int,
    *,
    same_text: bool,
):
    captions = []
    tables = []
    items = []
    native_texts = []
    for index in range(owner_count):
        caption_text = "Repeated caption" if same_text else f"Caption {index}"
        caption_top = 10.0 + index * 40.0
        table_top = caption_top + 8.0
        caption_ref = f"#/texts/{index}"
        table_ref = f"#/tables/{index}"
        captions.append(
            _caption(
                caption_ref,
                caption_text,
                _box(10, caption_top, 55, caption_top + 5),
            )
        )
        tables.append(
            _table(
                table_ref,
                [caption_ref],
                box=_box(10, table_top, 80, table_top + 25),
            )
        )
        item = _table_item(f"p1-table-{index}", y=table_top)
        item["reading_order"] = index
        items.append(item)
        native_texts.append(caption_text)

    document = _document(*items)
    document["pages"][0]["page_height"] = owner_count * 40.0 + 50.0
    _, ir = round_trip_document(
        document,
        raw_graph=_raw_graph(captions=captions, tables=tables),
        native_texts=tuple(native_texts),
    )
    return ir


def test_layout_caption_projection_p95_is_below_phase_ceiling() -> None:
    ir = _retained_ir()
    samples: list[float] = []
    for _ in range(5):
        apply_layout_projection(ir, _enabled())
    for _ in range(50):
        started = time.perf_counter()
        apply_layout_projection(ir, _enabled())
        samples.append(time.perf_counter() - started)

    p95 = statistics.quantiles(samples, n=100, method="inclusive")[94]

    assert p95 <= MAX_LAYOUT_OVERHEAD_SECONDS
    assert p95 <= 0.050


def test_maximum_supported_caption_references_are_bounded() -> None:
    ir = _retained_ir(64)
    tracemalloc.start()
    projected = apply_layout_projection(ir, _enabled())
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    payload_bytes = len(
        json.dumps(
            projected.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert peak_bytes <= 32 * 1024 * 1024
    assert payload_bytes <= 512 * 1024
    assert sum(
        element.type == "caption"
        and element.presentation_role == "primary"
        for element in projected.elements
    ) == 64


def test_reference_overflow_fails_closed_without_output_growth() -> None:
    ir = _retained_ir(65)
    projected = apply_layout_projection(ir, _enabled())
    page = projected.pages[0]

    assert len(page.presentation_element_ids) == 1
    assert any(
        concern.code == "table_caption_reference_limit"
        for concern in projected.concerns
    )


def test_many_owner_distinct_caption_projection_scales_near_linearly() -> None:
    small_ir = _many_owner_ir(128, same_text=False)
    large_ir = _many_owner_ir(512, same_text=False)

    started = time.perf_counter()
    apply_layout_projection(small_ir, _enabled())
    small_seconds = time.perf_counter() - started
    started = time.perf_counter()
    projected = apply_layout_projection(large_ir, _enabled())
    large_seconds = time.perf_counter() - started

    assert large_seconds <= small_seconds * 6.0 + 0.050
    assert large_seconds <= 1.0
    assert sum(
        element.type == "caption"
        and element.presentation_role == "primary"
        for element in projected.elements
    ) == 512


def test_many_owner_same_text_candidates_fail_closed_in_linear_space() -> None:
    ir = _many_owner_ir(512, same_text=True)

    tracemalloc.start()
    started = time.perf_counter()
    projected = apply_layout_projection(ir, _enabled())
    elapsed = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    concerns = [
        concern
        for concern in projected.concerns
        if concern.code == "table_caption_same_text_candidate_limit"
    ]
    assert len(concerns) == 1
    assert concerns[0].metadata["candidate_count"] == 512
    assert concerns[0].metadata["limit"] == 128
    assert elapsed <= 2.0
    assert peak_bytes <= 96 * 1024 * 1024
    assert all(
        element.type != "caption"
        or element.presentation_role != "primary"
        for element in projected.elements
    )


def test_candidate_overflow_avoids_pairwise_geometry_work(
    monkeypatch,
) -> None:
    original = layout_service._intersection_area
    calls = 0

    def counted(first, second):
        nonlocal calls
        calls += 1
        return original(first, second)

    monkeypatch.setattr(layout_service, "_intersection_area", counted)

    same_text = apply_layout_projection(
        _many_owner_ir(129, same_text=True),
        _enabled(),
    )
    page_overflow = apply_layout_projection(
        _many_owner_ir(513, same_text=False),
        _enabled(),
    )

    assert calls == 0
    assert any(
        concern.code == "table_caption_same_text_candidate_limit"
        for concern in same_text.concerns
    )
    assert any(
        concern.code == "table_caption_page_candidate_limit"
        for concern in page_overflow.concerns
    )
