"""Focused resource and fail-closed tests for US01 table word evidence."""

from __future__ import annotations

import sys
import tracemalloc
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import pipeline


_EXTRACTION_ARGUMENTS = {
    "x_tolerance": 2,
    "y_tolerance": 2,
    "keep_blank_chars": False,
    "use_text_flow": False,
}
_FLAG_ON_EXTRACTION_ARGUMENTS = {
    **_EXTRACTION_ARGUMENTS,
    "extra_attrs": ["fontname"],
}


class _FakePage:
    def __init__(self, words: list[Any]) -> None:
        self.words = words
        self.calls: list[dict[str, Any]] = []

    def extract_words(self, **kwargs: Any) -> list[Any]:
        self.calls.append(dict(kwargs))
        return self.words


class _FakeDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakeDocument:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class _DishonestWords(list[Any]):
    def __init__(self, reported_length: int) -> None:
        super().__init__()
        self.reported_length = reported_length

    def __len__(self) -> int:
        return self.reported_length


def _install_pdfplumber(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[_FakePage],
) -> None:
    module = SimpleNamespace(open=lambda _stream: _FakeDocument(pages))
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


def _table(
    page_index: int,
    *,
    mixed_row: bool = False,
    row_count: int = 2,
    column_count: int = 2,
) -> dict[str, Any]:
    cells = [
        {
            "start_row_offset_idx": row,
            "end_row_offset_idx": row + 1,
            "start_col_offset_idx": column,
            "end_col_offset_idx": column + 1,
            "row_span": 1,
            "col_span": 1,
            "text": f"r{row}c{column}",
            "column_header": bool(mixed_row and row == 0 and column == 0),
            "row_header": False,
            "row_section": False,
        }
        for row in range(row_count)
        for column in range(column_count)
    ]
    return {
        "data": {
            "num_rows": row_count,
            "num_cols": column_count,
            "table_cells": cells,
        },
        "prov": [{"page_no": page_index}],
    }


def _word(
    text: str = "value",
    *,
    x0: int | float = 1.0,
    x1: int | float = 2.0,
    top: int | float = 3.0,
    bottom: int | float = 4.0,
) -> dict[str, Any]:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "fontname": "must-not-leak",
        "object": object(),
    }


def test_default_off_keeps_the_predecessor_mixed_row_path_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage(
        [
            {
                "text": 17,
                "x0": "1.25",
                "x1": "2.5",
                "top": "3.75",
                "bottom": "4.0",
                "extra": "predecessor ignores this",
            },
            {"text": "   ", "x0": 0, "x1": 1, "top": 0, "bottom": 1},
        ]
    )
    _install_pdfplumber(monkeypatch, [page])

    def unexpected_clock() -> float:
        raise AssertionError("the default-off predecessor must not start a clock")

    monkeypatch.setattr(pipeline.time, "perf_counter", unexpected_clock)
    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1, mixed_row=True)]},
    )

    assert observed == {
        1: [
            {
                "text": "17",
                "x0": 1.25,
                "x1": 2.5,
                "top": 3.75,
                "bottom": 4.0,
            }
        ]
    }
    assert page.calls == [_EXTRACTION_ARGUMENTS]


def test_flag_on_selects_recovery_eligible_pages_and_sanitizes_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _FakePage([_word("first"), _word("   ")])
    second = _FakePage([_word("second", x0=5, x1=8, top=13, bottom=21)])
    _install_pdfplumber(monkeypatch, [first, second])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)

    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(2), _table(1)]},
        table_span_fidelity_enabled=True,
    )

    assert list(observed) == [1, 2]
    assert observed == {
        1: [{"text": "first", "x0": 1.0, "x1": 2.0, "top": 3.0, "bottom": 4.0, "font_name": "must-not-leak", "bold": False}],
        2: [{"text": "second", "x0": 5.0, "x1": 8.0, "top": 13.0, "bottom": 21.0, "font_name": "must-not-leak", "bold": False}],
    }
    assert first.calls == [_FLAG_ON_EXTRACTION_ARGUMENTS]
    assert second.calls == [_FLAG_ON_EXTRACTION_ARGUMENTS]


def test_flag_on_creates_and_reuses_supplied_absolute_deadlines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage([_word("bounded")])
    _install_pdfplumber(monkeypatch, [page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    page_deadlines: dict[int, float] = {}

    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1)]},
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
    )

    assert observed[1][0]["text"] == "bounded"
    assert page_deadlines == {1: 0.5}

    second_page = _FakePage([_word("same-deadline")])
    _install_pdfplumber(monkeypatch, [second_page])
    pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1)]},
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
    )
    assert page_deadlines == {1: 0.5}


def test_owned_budget_excludes_only_suspended_work_without_resetting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: now[0])
    page_deadlines = {1: 0.5}
    state: dict[str, Any] = {}

    document_deadline = pipeline._resume_table_span_fidelity_budget(
        5.0,
        page_deadlines,
        state,
    )
    assert document_deadline == 5.0
    now[0] = 0.1
    pipeline._suspend_table_span_fidelity_budget(state)

    now[0] = 2.1
    document_deadline = pipeline._resume_table_span_fidelity_budget(
        document_deadline,
        page_deadlines,
        state,
    )
    assert document_deadline == 7.0
    assert page_deadlines == {1: 2.5}
    assert page_deadlines[1] - now[0] == pytest.approx(0.4)
    now[0] = 2.3
    pipeline._suspend_table_span_fidelity_budget(state)

    now[0] = 5.3
    document_deadline = pipeline._resume_table_span_fidelity_budget(
        document_deadline,
        page_deadlines,
        state,
    )
    assert document_deadline == 10.0
    assert page_deadlines == {1: 5.5}
    assert page_deadlines[1] - now[0] == pytest.approx(0.2)
    assert document_deadline - now[0] == pytest.approx(4.7)

    pipeline._finish_table_span_fidelity_budget(state)
    assert state == {}


def test_timed_out_word_segment_credits_every_independent_page() -> None:
    page_deadlines = {1: 100.5, 2: 100.5, 3: 100.5}

    with pytest.raises(TimeoutError, match="page deadline exceeded"):
        pipeline._complete_table_span_fidelity_page_segment(  # noqa: SLF001
            page_deadlines,
            2,
            100.0,
            100.500001,
            105.0,
        )

    assert page_deadlines[1] == pytest.approx(101.000001)
    assert page_deadlines[2] == 100.5
    assert page_deadlines[3] == pytest.approx(101.000001)


def test_partitioned_extraction_suspends_exact_legacy_only_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_page = _FakePage([_word("legacy")])
    recovery_page = _FakePage([_word("recovery")])
    _install_pdfplumber(monkeypatch, [legacy_page, recovery_page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    legacy_table = _table(
        1,
        mixed_row=True,
        row_count=33,
        column_count=16,
    )
    raw = {"tables": [legacy_table, _table(2)]}
    state: dict[str, Any] = {}

    observed, deadline, warning_type = (
        pipeline._extract_partitioned_table_repair_words(  # noqa: SLF001
            b"pdf",
            raw,
            5.0,
            {},
            state,
        )
    )

    assert deadline == 5.0
    assert warning_type is None
    assert observed[1] == [
        {
            "text": "legacy",
            "x0": 1.0,
            "x1": 2.0,
            "top": 3.0,
            "bottom": 4.0,
        }
    ]
    assert observed[2][0]["font_name"] == "must-not-leak"
    assert observed[2][0]["bold"] is False
    assert legacy_page.calls == [_EXTRACTION_ARGUMENTS]
    assert recovery_page.calls == [_FLAG_ON_EXTRACTION_ARGUMENTS]
    assert state.get("span_fidelity_disabled") is not True
    assert pipeline._TABLE_SPAN_FIDELITY_SUSPENDED_AT_KEY in state


@pytest.mark.parametrize(
    ("strict_failure", "timed_out"),
    [(ValueError("malformed typography"), False), (TimeoutError("late"), True)],
)
def test_partitioned_extraction_failure_retries_exact_predecessor_without_warning(
    monkeypatch: pytest.MonkeyPatch,
    strict_failure: Exception,
    timed_out: bool,
) -> None:
    class PolicyPage(_FakePage):
        def extract_words(self, **kwargs: Any) -> list[Any]:
            self.calls.append(dict(kwargs))
            if "extra_attrs" in kwargs:
                raise strict_failure
            return self.words

    page = PolicyPage([_word("fallback")])
    _install_pdfplumber(monkeypatch, [page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    state: dict[str, Any] = {}

    observed, _deadline, warning_type = (
        pipeline._extract_partitioned_table_repair_words(  # noqa: SLF001
            b"pdf",
            {"tables": [_table(1, mixed_row=True)]},
            5.0,
            {},
            state,
        )
    )

    assert observed == {
        1: [
            {
                "text": "fallback",
                "x0": 1.0,
                "x1": 2.0,
                "top": 3.0,
                "bottom": 4.0,
            }
        ]
    }
    assert warning_type is None
    assert page.calls == [
        _FLAG_ON_EXTRACTION_ARGUMENTS,
        _EXTRACTION_ARGUMENTS,
    ]
    assert state["span_fidelity_disabled"] is True
    assert state["span_fidelity_failure_reason"] == (
        "table_word_geometry_unavailable"
    )
    assert (state.get("timed_out") is True) is timed_out


def test_partitioned_extraction_reports_only_exact_predecessor_failure_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PolicyPage(_FakePage):
        def extract_words(self, **kwargs: Any) -> list[Any]:
            self.calls.append(dict(kwargs))
            if "extra_attrs" in kwargs:
                raise ValueError("strict path refused")
            raise KeyError("predecessor path refused")

    page = PolicyPage([_word("never-retained")])
    _install_pdfplumber(monkeypatch, [page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    state: dict[str, Any] = {}

    observed, _deadline, warning_type = (
        pipeline._extract_partitioned_table_repair_words(  # noqa: SLF001
            b"pdf",
            {"tables": [_table(1, mixed_row=True)]},
            5.0,
            {},
            state,
        )
    )

    assert observed == {}
    assert warning_type == "KeyError"
    assert page.calls == [
        _FLAG_ON_EXTRACTION_ARGUMENTS,
        _EXTRACTION_ARGUMENTS,
    ]
    assert state["span_fidelity_disabled"] is True
    assert state["span_fidelity_failure_reason"] == (
        "table_word_geometry_unavailable"
    )
    assert state.get("timed_out") is not True


def test_flag_on_word_count_boundaries_are_inclusive_and_document_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_word = _word("bounded")
    exact_pages = [_FakePage([shared_word] * 16_384) for _ in range(4)]
    _install_pdfplumber(monkeypatch, exact_pages)
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    raw = {"tables": [_table(index) for index in range(1, 5)]}

    exact = pipeline._extract_table_repair_words(
        b"pdf",
        raw,
        table_span_fidelity_enabled=True,
    )
    assert list(exact) == [1, 2, 3, 4]
    assert sum(len(words) for words in exact.values()) == 65_536

    page_overflow = _FakePage([shared_word] * 16_385)
    _install_pdfplumber(monkeypatch, [page_overflow])
    with pytest.raises(ValueError, match="word page limit exceeded"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


def test_exact_document_word_cap_materializes_below_allocation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_word = _word("bounded")
    pages = [_FakePage([shared_word] * 16_384) for _ in range(4)]
    _install_pdfplumber(monkeypatch, pages)
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)

    tracemalloc.start()
    try:
        observed = pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(index) for index in range(1, 5)]},
            table_span_fidelity_enabled=True,
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert sum(len(words) for words in observed.values()) == 65_536
    assert peak_bytes <= 64 * 1_048_576

    document_overflow_pages = [
        *[_FakePage([shared_word] * 16_384) for _ in range(4)],
        _FakePage([shared_word]),
    ]
    _install_pdfplumber(monkeypatch, document_overflow_pages)
    with pytest.raises(ValueError, match="word document limit exceeded"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(index) for index in range(1, 6)]},
            table_span_fidelity_enabled=True,
        )


def test_flag_on_rejects_list_subclasses_with_dishonest_lengths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    words = _DishonestWords(1)
    words.extend([_word("bypass")] * 65_537)
    _install_pdfplumber(monkeypatch, [_FakePage(words)])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)

    with pytest.raises(ValueError, match="word records are not sized"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


def test_flag_on_table_and_page_boundaries_fail_closed() -> None:
    exact = {"tables": [_table(1) for _ in range(4_096)]}
    assert pipeline._table_repair_page_indexes(
        exact,
        table_span_fidelity_enabled=True,
    ) == {1}

    with pytest.raises(ValueError, match="table limit exceeded"):
        pipeline._table_repair_page_indexes(
            {"tables": [*_table_list(4_096), _table(1)]},
            table_span_fidelity_enabled=True,
        )
    assert pipeline._table_repair_page_indexes(
        {"tables": [_table(100)]},
        table_span_fidelity_enabled=True,
    ) == {100}
    assert pipeline._table_repair_page_indexes(
        {"tables": [_table(101)]},
        table_span_fidelity_enabled=True,
    ) == set()


def test_flag_on_requires_one_primary_provenance_and_bounded_nonempty_grid() -> None:
    multi_page = _table(1)
    multi_page["prov"].append({"page_no": 2})
    assert pipeline._table_repair_page_indexes(
        {"tables": [multi_page]},
        table_span_fidelity_enabled=True,
    ) == set()

    sparse = _table(1)
    sparse["data"]["table_cells"].pop()
    too_wide = _table(1, column_count=17)
    one_row = _table(1, row_count=1)

    assert pipeline._table_repair_page_indexes(
        {
            "tables": [
                sparse,
                too_wide,
                one_row,
            ]
        },
        table_span_fidelity_enabled=True,
    ) == {1}

    empty = _table(2)
    empty["data"]["table_cells"] = []
    overfull = _table(2)
    overfull["data"]["table_cells"].append(
        dict(overfull["data"]["table_cells"][0])
    )
    assert pipeline._table_repair_page_indexes(
        {"tables": [empty, overfull]},
        table_span_fidelity_enabled=True,
    ) == set()

    one_column_header_candidate = _table(3, column_count=1)
    assert pipeline._table_repair_page_indexes(
        {"tables": [one_column_header_candidate]},
        table_span_fidelity_enabled=True,
    ) == {3}


def test_optional_recovery_slot_cap_is_exact_and_mixed_rows_are_preserved() -> None:
    exact = _table(1, row_count=32, column_count=16)
    over = _table(2, row_count=33, column_count=16)
    over_mixed = _table(3, mixed_row=True, row_count=33, column_count=16)

    assert pipeline._table_repair_page_indexes(
        {"tables": [exact, over]},
        table_span_fidelity_enabled=True,
    ) == {1}
    assert pipeline._table_repair_page_indexes(
        {"tables": [over_mixed]},
        table_span_fidelity_enabled=True,
    ) == {3}
    assert pipeline._table_repair_recovery_page_index(exact) == 1
    assert pipeline._table_repair_recovery_page_index(over) is None
    assert pipeline._table_repair_recovery_page_index(over_mixed) is None


def test_over_recovery_cap_mixed_row_keeps_exact_predecessor_word_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_table = _table(1, mixed_row=True, row_count=33, column_count=16)
    raw_table["self_ref"] = "#/tables/over-cap-mixed"
    source_words = [
        _word("Header", x0=1.0, x1=20.0, top=3.0, bottom=8.0),
        _word("Body", x0=25.0, x1=40.0, top=3.0, bottom=8.0),
    ]
    predecessor_page = _FakePage(source_words)
    _install_pdfplumber(monkeypatch, [predecessor_page])
    predecessor_words = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [raw_table]},
        table_span_fidelity_enabled=False,
    )
    enabled_page = _FakePage(source_words)
    _install_pdfplumber(monkeypatch, [enabled_page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    enabled_words = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [raw_table]},
        table_span_fidelity_enabled=True,
    )

    assert enabled_words == predecessor_words
    assert predecessor_page.calls == [_EXTRACTION_ARGUMENTS]
    assert enabled_page.calls == [_EXTRACTION_ARGUMENTS]

    _page_index, predecessor = pipeline._docling_table_item(  # noqa: SLF001
        raw_table,
        {1: 100.0},
        predecessor_words,
        table_span_fidelity_enabled=False,
    )
    _page_index, observed = pipeline._docling_table_item(  # noqa: SLF001
        raw_table,
        {1: 100.0},
        enabled_words,
        table_span_fidelity_enabled=True,
    )

    assert observed == predecessor
    assert "table_evidence" not in observed


def test_flag_on_cell_semantics_stay_in_deadline_bound_local_validation() -> None:
    spanned = _table(3)
    spanned["data"]["table_cells"][0].update(
        {"col_span": 2, "end_col_offset_idx": 2}
    )
    duplicate = _table(3)
    duplicate["data"]["table_cells"][1].update(
        {
            "start_col_offset_idx": 0,
            "end_col_offset_idx": 1,
        }
    )
    boolean_span = _table(3)
    boolean_span["data"]["table_cells"][0]["row_span"] = True
    omitted_booleans = _table(3)
    for name in ("column_header", "row_header", "row_section"):
        omitted_booleans["data"]["table_cells"][0].pop(name)

    # Page discovery proves only the bounded recovery envelope. Exact cell
    # semantics remain owned by the existing deadline-bound table validator,
    # so this preflight cannot become stricter or unbounded.
    assert pipeline._table_repair_page_indexes(
        {
            "tables": [
                spanned,
                duplicate,
                boolean_span,
                omitted_booleans,
            ]
        },
        table_span_fidelity_enabled=True,
    ) == {3}


def test_flag_on_cumulative_page_discovery_never_walks_candidate_cells() -> None:
    maximum = _table(1, row_count=4_096, column_count=16)
    later_eligible = _table(2)

    # The 4,096-table input owns 268,369,920 addressable cell slots. Reusing
    # one shared test grid keeps the test allocation bounded while an
    # accidental per-table cell walk would still repeat all 65,536 entries.
    tables = [maximum] * 4_095 + [later_eligible]
    assert pipeline._table_repair_page_indexes(
        {"tables": tables},
        table_span_fidelity_enabled=True,
    ) == {1, 2}

    out_of_envelope = {
        **maximum,
        "data": {
            **maximum["data"],
            "num_rows": 4_097,
        },
    }
    assert pipeline._table_repair_page_indexes(
        {"tables": [out_of_envelope] * 4_095 + [later_eligible]},
        table_span_fidelity_enabled=True,
    ) == {2}


def test_flag_on_ineligible_tables_do_not_consume_or_suppress_eligible_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skipped_first = _FakePage([_word("must-not-be-read")])
    retained_second = _FakePage([_word("eligible")])
    skipped_third = _FakePage([_word("must-not-be-read-either")])
    _install_pdfplumber(
        monkeypatch,
        [skipped_first, retained_second, skipped_third],
    )
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)

    malformed = {"prov": [{"page_no": "1"}]}
    too_wide = _table(1, column_count=17)
    multi_page = _table(3)
    multi_page["prov"].append({"page_no": 1})
    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {
            "tables": [
                malformed,
                too_wide,
                multi_page,
                _table(2),
            ]
        },
        table_span_fidelity_enabled=True,
    )

    assert list(observed) == [2]
    assert observed[2][0]["text"] == "eligible"
    assert skipped_first.calls == []
    assert retained_second.calls == [_FLAG_ON_EXTRACTION_ARGUMENTS]
    assert skipped_third.calls == []


def _table_list(count: int) -> list[dict[str, Any]]:
    return [_table(1) for _ in range(count)]


def test_flag_on_deadline_spans_third_party_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage([_word("sensitive-value-must-not-appear")])
    _install_pdfplumber(monkeypatch, [page])
    clocks = iter((0.0, 0.0, 6.0))
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: next(clocks))

    with pytest.raises(TimeoutError) as raised:
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )

    assert "sensitive-value" not in str(raised.value)
    assert page.calls == [_FLAG_ON_EXTRACTION_ARGUMENTS]


def test_flag_on_page_deadline_is_inclusive_and_refuses_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_page = _FakePage([_word("exact")])
    _install_pdfplumber(monkeypatch, [exact_page])
    exact_clocks = iter((0.0, 0.0, 0.5, 0.5, 0.5))
    monkeypatch.setattr(
        pipeline.time,
        "perf_counter",
        lambda: next(exact_clocks, 0.5),
    )
    assert pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1)]},
        table_span_fidelity_enabled=True,
    )[1][0]["text"] == "exact"

    overflow_page = _FakePage([_word("overflow")])
    _install_pdfplumber(monkeypatch, [overflow_page])
    overflow_clocks = iter((0.0, 0.0, 0.500_001))
    monkeypatch.setattr(
        pipeline.time,
        "perf_counter",
        lambda: next(overflow_clocks, 0.500_001),
    )
    with pytest.raises(TimeoutError, match="page deadline exceeded"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize(
    "words",
    [
        ("not-a-list",),
        ["not-a-mapping"],
        [{"text": 7, "x0": 1, "x1": 2, "top": 3, "bottom": 4}],
        [_word(x0=True)],
        [_word(x1=float("nan"))],
        [_word(x0=3, x1=2)],
        [_word(x0=2, x1=2)],
        [_word(top=5, bottom=4)],
        [_word(top=4, bottom=4)],
        [{**_word(), "fontname": ""}],
        [{**_word(), "fontname": "Bad\tFont"}],
        [{**_word(), "fontname": "Bad\nFont"}],
        [{**_word(), "fontname": "Bad\x7fFont"}],
        [{**_word(), "fontname": "é" * 129}],
    ],
)
def test_flag_on_malformed_word_records_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    words: Any,
) -> None:
    page = _FakePage(words)
    _install_pdfplumber(monkeypatch, [page])
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)

    with pytest.raises(ValueError, match="table repair word"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


def test_flag_on_text_byte_boundary_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    exact_page = _FakePage([_word("x" * 16_384)])
    _install_pdfplumber(monkeypatch, [exact_page])
    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1)]},
        table_span_fidelity_enabled=True,
    )
    assert len(observed[1][0]["text"].encode("utf-8")) == 16_384

    overflow_page = _FakePage([_word("x" * 16_385)])
    _install_pdfplumber(monkeypatch, [overflow_page])
    with pytest.raises(ValueError, match="word text limit exceeded"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


def test_flag_on_aggregate_text_byte_boundary_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    full_word = _word("x" * 16_384)
    exact_page = _FakePage([full_word] * 512)
    _install_pdfplumber(monkeypatch, [exact_page])
    observed = pipeline._extract_table_repair_words(
        b"pdf",
        {"tables": [_table(1)]},
        table_span_fidelity_enabled=True,
    )
    assert sum(
        len(word["text"].encode("utf-8")) for word in observed[1]
    ) == 8_388_608

    overflow_page = _FakePage([*([full_word] * 512), _word("x")])
    _install_pdfplumber(monkeypatch, [overflow_page])
    with pytest.raises(ValueError, match="text document limit exceeded"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize(
    "text",
    [
        " " * 16_385,
        "A\x00B",
        "A\x1fB",
        "A\x7fB",
        "A\nB",
        "A\tB",
    ],
)
def test_flag_on_rejects_unbounded_blank_or_control_text(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
) -> None:
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: 0.0)
    _install_pdfplumber(monkeypatch, [_FakePage([_word(text)])])

    with pytest.raises(ValueError, match="word text"):
        pipeline._extract_table_repair_words(
            b"pdf",
            {"tables": [_table(1)]},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize(
    "candidate",
    [
        None,
        {"prov": []},
        {"prov": [None]},
        {"prov": [{"page_no": True}]},
        {"prov": [{"page_no": 1.5}]},
        {"prov": [{"page_no": "1"}]},
        {"prov": [{"page_no": "unknown"}]},
    ],
)
def test_flag_on_malformed_table_record_is_isolated(candidate: Any) -> None:
    assert pipeline._table_repair_page_indexes(
        {"tables": [candidate, _table(2)]},
        table_span_fidelity_enabled=True,
    ) == {2}


def test_flag_on_malformed_table_container_fails_closed() -> None:
    with pytest.raises(ValueError, match="table limit exceeded"):
        pipeline._table_repair_page_indexes(
            {"tables": "not-a-list"},
            table_span_fidelity_enabled=True,
        )
