"""Focused source-evidence tests for P04-US01 table input recovery."""

from __future__ import annotations

import ast
from collections import defaultdict
from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import pipeline, table_semantics
from app.services.pipeline import _docling_table_item


SOURCE_SHA256 = "a" * 64


def _cell(
    row: int,
    column: int,
    text: str,
    *,
    left: float,
    top: float,
    right: float,
    bottom: float,
    column_header: bool = False,
) -> dict[str, Any]:
    return {
        "bbox": {
            "l": left,
            "t": top,
            "r": right,
            "b": bottom,
            "coord_origin": "TOPLEFT",
        },
        "row_span": 1,
        "col_span": 1,
        "start_row_offset_idx": row,
        "end_row_offset_idx": row + 1,
        "start_col_offset_idx": column,
        "end_col_offset_idx": column + 1,
        "text": text,
        "column_header": column_header,
        "row_header": False,
        "row_section": False,
        "ref": {"$ref": f"#/texts/{row}-{column}"},
    }


def _table(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "self_ref": "#/tables/recovery",
        "label": "table",
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0.0,
                    "t": 100.0,
                    "r": 200.0,
                    "b": 0.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": 2,
            "num_cols": 2,
            "table_cells": cells,
        },
    }


def _header_table() -> dict[str, Any]:
    return _table(
        [
            _cell(0, 0, "Term", left=0, top=10, right=100, bottom=30),
            _cell(
                0,
                1,
                "Definition",
                left=100,
                top=10,
                right=200,
                bottom=30,
            ),
            _cell(1, 0, "FERS", left=0, top=30, right=100, bottom=50),
            _cell(
                1,
                1,
                "Federal Employees",
                left=100,
                top=30,
                right=200,
                bottom=50,
            ),
        ]
    )


def _bottom_table() -> dict[str, Any]:
    return _table(
        [
            _cell(
                0,
                0,
                "Term",
                left=0,
                top=10,
                right=100,
                bottom=25,
                column_header=True,
            ),
            _cell(
                0,
                1,
                "Definition",
                left=100,
                top=10,
                right=200,
                bottom=25,
                column_header=True,
            ),
            _cell(1, 0, "FEHB", left=0, top=30, right=100, bottom=45),
            _cell(
                1,
                1,
                "Federal Employees Health Benefits",
                left=100,
                top=30,
                right=200,
                bottom=45,
            ),
        ]
    )


def _word(
    text: str,
    *,
    x0: float,
    x1: float,
    top: float,
    bottom: float,
    bold: object,
) -> dict[str, Any]:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "font_name": (
            "Fixture-Bold" if bold is True else "Fixture-Regular"
        ),
        "bold": bold,
    }


def _header_words() -> list[dict[str, Any]]:
    return [
        _word("Term", x0=10, x1=50, top=15, bottom=25, bold=True),
        _word("Definition", x0=110, x1=180, top=15, bottom=25, bold=True),
        _word("FERS", x0=10, x1=50, top=35, bottom=45, bold=False),
        _word("Federal", x0=110, x1=140, top=35, bottom=45, bold=False),
        _word("Employees", x0=145, x1=190, top=35, bottom=45, bold=False),
    ]


def _bottom_words() -> list[dict[str, Any]]:
    return [
        _word("FERS", x0=5, x1=35, top=50, bottom=58, bold=False),
        _word("Federal", x0=105, x1=125, top=50, bottom=58, bold=False),
        _word("Employees", x0=128, x1=150, top=50, bottom=58, bold=False),
        _word("Retirement", x0=153, x1=175, top=50, bottom=58, bold=False),
        _word("System", x0=178, x1=195, top=50, bottom=58, bold=False),
    ]


def _prepare(
    raw: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    return table_semantics.prepare_docling_table_input(
        raw,
        {1: 100.0},
        {1: words},
        table_span_fidelity_enabled=True,
    )


def _project(
    raw: dict[str, Any],
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    return _docling_table_item(
        raw,
        {1: 100.0},
        {1: words},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )[1]


def test_bold_header_recovery_requires_matching_bold_to_regular_transition() -> None:
    raw = _header_table()
    before = deepcopy(raw)

    prepared = _prepare(raw, _header_words())
    plan = prepared["_p04_table_recovery_plan"]

    assert raw == before
    assert prepared is not raw
    assert prepared["data"] == before["data"]
    assert plan["predecessor_grid"] == {"row_count": 2, "column_count": 2}
    assert plan["bottom_row"] is None
    assert [entry["target_column"] for entry in plan["header"]] == [0, 1]
    assert all(
        word["bold"] is True
        for entry in plan["header"]
        for word in entry["header_words"]
    )
    assert all(
        word["bold"] is False
        for entry in plan["header"]
        for word in entry["body_control_words"]
    )

    _page_index, projected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    assert [cell["column_header"] for cell in projected["cells"]] == [
        True,
        True,
        False,
        False,
    ]
    pdf_sources = [
        source
        for source in projected["table_evidence"]["source_objects"]
        if source["engine"] == "pdfplumber"
    ]
    assert len(pdf_sources) == 4
    assert {source["role"] for source in pdf_sources} == {
        "header",
        "body_control",
    }
    assert table_semantics.validate_table_semantics(projected, SOURCE_SHA256)


@pytest.mark.parametrize(
    "mutation",
    [
        "positional_nonbold",
        "mixed_header_weight",
        "mixed_body_weight",
        "unsafe_font_evidence",
        "empty_font_evidence",
        "text_mismatch",
        "incomplete_column_evidence",
    ],
)
def test_header_recovery_refuses_insufficient_or_unsafe_evidence(
    mutation: str,
) -> None:
    raw = _header_table()
    words = _header_words()
    if mutation == "positional_nonbold":
        words[0]["bold"] = False
        words[1]["bold"] = False
    elif mutation == "mixed_header_weight":
        words[1]["bold"] = False
    elif mutation == "mixed_body_weight":
        words[2]["bold"] = True
    elif mutation == "unsafe_font_evidence":
        words[0]["font_name"] = "Bad\tBold"
    elif mutation == "empty_font_evidence":
        words[0]["font_name"] = ""
        words[0]["bold"] = False
    elif mutation == "text_mismatch":
        words[1]["text"] = "Definitions"
    else:
        words = [word for word in words if word["x0"] < 100 or word["top"] < 30]

    prepared = _prepare(raw, words)

    assert prepared == raw
    assert not any(
        cell.get("p04_header_evidence")
        for cell in prepared["data"]["table_cells"]
    )
    assert not any(
        cell["column_header"] for cell in prepared["data"]["table_cells"]
    )


def test_bottom_row_recovery_requires_complete_cadenced_source_line() -> None:
    raw = _bottom_table()
    before = deepcopy(raw)

    prepared = _prepare(raw, _bottom_words())
    plan = prepared["_p04_table_recovery_plan"]
    recovered = plan["bottom_row"]["cells"]

    assert raw == before
    assert prepared is not raw
    assert prepared["data"] == before["data"]
    assert [cell["text"] for cell in recovered] == [
        "FERS",
        "Federal Employees Retirement System",
    ]
    assert [(cell["target_row"], cell["target_column"]) for cell in recovered] == [
        (2, 0),
        (2, 1),
    ]
    assert [cell["bbox"] for cell in recovered] == [
        {
            "x": 5.0,
            "y": 50.0,
            "width": 30.0,
            "height": 8.0,
            "unit": "pt",
        },
        {
            "x": 105.0,
            "y": 50.0,
            "width": 90.0,
            "height": 8.0,
            "unit": "pt",
        },
    ]
    assert all("ref" not in cell for cell in recovered)

    _page_index, projected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    assert projected["row_count"] == 3
    assert [cell["text"] for cell in projected["cells"][-2:]] == [
        "FERS",
        "Federal Employees Retirement System",
    ]
    bottom_sources = [
        source
        for source in projected["table_evidence"]["source_objects"]
        if source.get("role") == "bottom_row"
    ]
    assert len(bottom_sources) == 2
    assert all(source["raw_ref"] is None for source in bottom_sources)
    assert table_semantics.validate_table_semantics(projected, SOURCE_SHA256)


def test_recovery_builds_one_exact_independent_ocr_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _bottom_table()
    raw_before = deepcopy(raw)
    line = SimpleNamespace(
        text="FEHB",
        bbox={"x": 0.0, "y": 30.0, "width": 100.0, "height": 15.0},
        confidence=0.93,
        word_count=1,
    )
    image_regions = {1: [SimpleNamespace(lines=[line])]}
    _expected_page, expected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        image_regions=image_regions,
        table_span_fidelity_enabled=False,
    )
    pipeline._enrich_ocr_confidence(  # noqa: SLF001
        [{"page_index": 1, "items": [expected]}],
        image_regions,
    )

    real_refresh = pipeline._refresh_table_serializations  # noqa: SLF001
    refresh_calls = [0]

    def counted_refresh(item: dict[str, Any]) -> None:
        refresh_calls[0] += 1
        real_refresh(item)

    monkeypatch.setattr(
        pipeline,
        "_refresh_table_serializations",
        counted_refresh,
    )
    _page_index, projected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        image_regions=image_regions,
        table_span_fidelity_enabled=True,
    )

    snapshot = projected["_p04_predecessor_snapshot"]
    assert refresh_calls == [1]
    assert snapshot == expected
    assert snapshot is not projected
    assert snapshot["rows"] is not projected["rows"]
    assert snapshot["cells"] is not projected["cells"]
    assert snapshot["cells"][2]["confidence"] == pytest.approx(0.93)
    projected["rows"][0][0] = "overlay-only mutation"
    projected["cells"][0]["text"] = "overlay-only mutation"
    assert snapshot == expected
    assert raw == raw_before


def test_shared_confidence_keeps_recovered_word_evidence_byte_exact() -> None:
    line = SimpleNamespace(
        text="FERS",
        bbox={"x": 5.0, "y": 50.0, "width": 30.0, "height": 8.0},
        confidence=0.97,
        word_count=1,
    )
    image_regions = {1: [SimpleNamespace(lines=[line])]}
    _page_index, projected = _docling_table_item(
        _bottom_table(),
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        image_regions=image_regions,
        table_span_fidelity_enabled=True,
    )
    sidecar_before = deepcopy(projected["table_evidence"])
    pages = [
        {
            "page_index": 1,
            "page_width": 200.0,
            "page_height": 100.0,
            "unit": "pt",
            "items": [projected],
        }
    ]

    pipeline._enrich_ocr_confidence(  # noqa: SLF001
        pages,
        image_regions,
    )

    assert projected["table_evidence"] == sidecar_before
    assert all(
        set(source_word) == {"id", "text", "bbox", "font_name", "bold"}
        for source in projected["table_evidence"]["source_objects"]
        if source.get("engine") == "pdfplumber"
        for source_word in source["words"]
    )
    table_semantics.replay_table_semantics(
        projected,
        projected["table_evidence"],
        source_sha256=SOURCE_SHA256,
    )
    assert projected["table_evidence"] == sidecar_before
    assert table_semantics.validate_table_semantics(projected, SOURCE_SHA256)


@pytest.mark.parametrize(
    "mutation",
    [
        "incomplete_columns",
        "bad_cadence",
        "outside_table_bbox",
        "past_table_bottom",
        "duplicate_word",
        "ambiguous_word",
    ],
)
def test_bottom_row_recovery_refuses_incomplete_ambiguous_or_bad_geometry(
    mutation: str,
) -> None:
    raw = _bottom_table()
    words = _bottom_words()
    if mutation == "incomplete_columns":
        words = [words[0]]
    elif mutation == "bad_cadence":
        raw["data"]["table_cells"][2]["bbox"].update({"t": 80, "b": 95})
        raw["data"]["table_cells"][3]["bbox"].update({"t": 80, "b": 95})
    elif mutation == "outside_table_bbox":
        words[0].update({"x0": -20, "x1": -5})
    elif mutation == "past_table_bottom":
        for word in words:
            word.update({"top": 99, "bottom": 102})
    elif mutation == "duplicate_word":
        words.insert(1, deepcopy(words[0]))
    else:
        competing = deepcopy(words[0])
        competing["text"] = "CSRS"
        words.insert(1, competing)

    before = deepcopy(raw)
    prepared = _prepare(raw, words)

    assert raw == before
    assert prepared == before
    assert prepared["data"]["num_rows"] == 2
    assert len(prepared["data"]["table_cells"]) == 4


def test_prepare_input_default_off_is_exact_identity_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _header_table()
    before = json.dumps(
        raw,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    def unexpected_clock() -> float:
        raise AssertionError("default-off input preparation must not start work")

    monkeypatch.setattr(table_semantics, "perf_counter", unexpected_clock)
    returned = table_semantics.prepare_docling_table_input(
        raw,
        {1: object()},
        {1: object()},
        table_span_fidelity_enabled=False,
    )
    after = json.dumps(
        raw,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert returned is raw
    assert after == before
    assert not any(
        key.startswith("p04_")
        for cell in raw["data"]["table_cells"]
        for key in cell
    )


def test_recovery_auxiliary_evidence_is_scoped_to_the_candidate_page() -> None:
    raw = _header_table()
    expected = _prepare(raw, _header_words())
    irrelevant_cycle: list[Any] = []
    irrelevant_cycle.append(irrelevant_cycle)

    actual = table_semantics.prepare_docling_table_input(
        raw,
        {1: 100.0, 999: object()},
        {1: _header_words(), 999: irrelevant_cycle},
        table_span_fidelity_enabled=True,
    )

    assert actual == expected
    assert actual is not raw


@pytest.mark.parametrize("mapping_name", ("heights", "words"))
def test_recovery_rejects_malformed_evidence_on_the_candidate_page(
    mapping_name: str,
) -> None:
    raw = _header_table()
    heights: dict[int, Any] = {1: 100.0}
    words: dict[int, Any] = {1: _header_words()}
    if mapping_name == "heights":
        heights[1] = object()
    else:
        words[1] = object()

    with pytest.raises(TypeError, match="table value must be exact plain data"):
        table_semantics.prepare_docling_table_input(
            raw,
            heights,
            words,
            table_span_fidelity_enabled=True,
        )


def test_recovery_page_mapping_limit_is_enforced_before_projection() -> None:
    raw = _header_table()
    heights = {page_index: 100.0 for page_index in range(1, 4098)}

    with pytest.raises(ValueError, match="page mapping limit"):
        table_semantics.prepare_docling_table_input(
            raw,
            heights,
            {1: _header_words()},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize("mapping_name", ("heights", "words"))
@pytest.mark.parametrize(
    "malformed_mapping",
    ([], (), defaultdict(list), object()),
    ids=("list", "tuple", "defaultdict", "object"),
)
def test_recovery_rejects_every_non_exact_page_mapping(
    mapping_name: str,
    malformed_mapping: object,
) -> None:
    raw = _header_table()
    heights: object = {1: 100.0}
    words: object = {1: _header_words()}
    if mapping_name == "heights":
        heights = malformed_mapping
    else:
        words = malformed_mapping

    with pytest.raises(
        TypeError, match="table recovery page mapping must be an exact dict"
    ):
        table_semantics.prepare_docling_table_input(
            raw,
            heights,
            words,
            table_span_fidelity_enabled=True,
        )


def test_prepare_pair_preserves_aliases_without_cross_output_aliasing() -> None:
    raw = _bottom_table()
    shared = [{"value": "source"}]
    raw["shared_left"] = shared
    raw["shared_right"] = shared

    predecessor, recovered = table_semantics.prepare_docling_table_inputs(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        table_span_fidelity_enabled=True,
    )

    assert predecessor is not raw
    assert recovered is not raw
    assert recovered is not predecessor
    assert raw["shared_left"] is raw["shared_right"]
    assert predecessor["shared_left"] is predecessor["shared_right"]
    assert recovered["shared_left"] is recovered["shared_right"]
    assert predecessor["shared_left"] is not raw["shared_left"]
    assert recovered["shared_left"] is not predecessor["shared_left"]

    recovered["shared_left"][0]["value"] = "recovered"
    assert recovered["shared_right"][0]["value"] == "recovered"
    assert predecessor["shared_left"][0]["value"] == "source"
    assert raw["shared_left"][0]["value"] == "source"


@pytest.mark.parametrize(
    ("attack", "error_type", "message"),
    (
        ("unused_object", TypeError, "exact plain data"),
        ("unused_cycle", ValueError, "cyclic table value"),
        ("unused_depth", ValueError, "table nesting limit exceeded"),
    ),
)
def test_initial_raw_admission_rejects_hostile_unused_graphs(
    attack: str,
    error_type: type[Exception],
    message: str,
) -> None:
    raw = _header_table()
    if attack == "unused_object":
        hostile: object = object()
    elif attack == "unused_cycle":
        cycle: list[Any] = []
        cycle.append(cycle)
        hostile = cycle
    else:
        hostile = None
        for _depth in range(32):
            hostile = [hostile]
    raw["zz_unused_hostile"] = hostile

    with pytest.raises(error_type, match=message):
        table_semantics.prepare_docling_table_inputs(
            raw,
            {1: 100.0},
            {1: _header_words()},
            table_span_fidelity_enabled=True,
        )


@pytest.mark.parametrize("attack", ("unused_object", "unused_cycle", "unused_depth"))
def test_public_owned_boolean_cannot_bypass_full_raw_admission(
    attack: str,
) -> None:
    raw = _header_table()
    if attack == "unused_object":
        hostile: object = object()
    elif attack == "unused_cycle":
        cycle: list[Any] = []
        cycle.append(cycle)
        hostile = cycle
    else:
        hostile = None
        for _depth in range(32):
            hostile = [hostile]
    raw["zz_unused_hostile"] = hostile
    _page_index, item = _docling_table_item(
        _header_table(),
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    item["source_document_identity"] = SOURCE_SHA256

    with pytest.raises((TypeError, ValueError)):
        table_semantics.prepare_docling_table(
            item,
            raw,
            predecessor_item=deepcopy(item),
            table_span_fidelity_enabled=True,
            table_inputs_are_owned=True,
        )


def test_public_ownership_keyword_is_compatibility_only_and_fails_closed() -> None:
    raw = _header_table()
    _page_index, item = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    item["source_document_identity"] = SOURCE_SHA256

    with pytest.raises(
        ValueError, match="table input ownership bypass is unavailable"
    ):
        table_semantics.prepare_docling_table(
            item,
            raw,
            predecessor_item=deepcopy(item),
            table_span_fidelity_enabled=True,
            table_inputs_are_owned=True,
        )
    with pytest.raises(TypeError, match="ownership policy differs"):
        table_semantics.prepare_docling_table(
            item,
            raw,
            predecessor_item=deepcopy(item),
            table_span_fidelity_enabled=True,
            table_inputs_are_owned=1,
        )


def test_pipeline_projection_has_no_public_raw_ownership_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _header_table()
    _expected_page, expected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    monkeypatch.setattr(
        table_semantics,
        "prepare_docling_table_inputs",
        lambda *_args, **_kwargs: pytest.fail(
            "pipeline must not receive prepared raw roots"
        ),
    )
    monkeypatch.setattr(
        table_semantics,
        "prepare_docling_table",
        lambda *_args, **_kwargs: pytest.fail(
            "pipeline must not invoke the public projection entry"
        ),
    )

    observed_page, observed = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert observed_page == _expected_page == 1
    assert observed["_p04_predecessor_snapshot"] == expected
    assert "table_evidence" in observed


def test_private_orchestration_exposes_no_caller_authority_seam() -> None:
    public_parameters = list(
        inspect.signature(table_semantics.prepare_docling_table).parameters
    )
    assert public_parameters == [
        "item",
        "raw_item",
        "predecessor_item",
        "table_span_fidelity_enabled",
        "table_span_fidelity_deadline",
        "table_span_fidelity_document_deadline",
        "table_inputs_are_owned",
    ]
    private_parameters = list(
        inspect.signature(
            table_semantics._orchestrate_docling_table_projection
        ).parameters
    )
    assert private_parameters == [
        "raw_item",
        "page_heights",
        "page_words_by_page",
        "native_texts",
        "source_document_identity",
        "image_regions",
        "table_span_fidelity_deadline",
        "table_span_fidelity_document_deadline",
    ]
    assert not any(
        fragment in parameter
        for parameter in private_parameters
        for fragment in ("owned", "trusted", "validated", "token", "callback")
    )

    pipeline_tree = ast.parse(inspect.getsource(pipeline._docling_table_item))
    called_names = {
        node.func.id
        for node in ast.walk(pipeline_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_orchestrate_docling_table_projection" in called_names
    assert "prepare_docling_table" not in called_names
    assert "prepare_docling_table_inputs" not in called_names


@pytest.mark.parametrize(
    ("local_rejection", "expected_owned_closures"),
    ((False, 1), (True, 0)),
)
def test_private_orchestration_has_exact_raw_root_traversal_and_copy_counts(
    monkeypatch: pytest.MonkeyPatch,
    local_rejection: bool,
    expected_owned_closures: int,
) -> None:
    raw = _bottom_table()
    if local_rejection:
        raw.pop("prov")
    raw_inspections = 0
    owned_root_closures = 0
    canonical_root_closures = 0
    raw_copy_count = 0
    original_inspect = table_semantics._inspect_plain_table_value
    original_owned_canonical = (
        table_semantics._assert_owned_canonical_table_json
    )
    original_canonical = table_semantics._assert_canonical_table_json
    original_deepcopy = table_semantics.deepcopy

    def is_raw_root(value: object) -> bool:
        return (
            type(value) is dict
            and value.get("self_ref") == raw.get("self_ref")
            and type(value.get("data")) is dict
        )

    def counted_inspect(*args: Any, **kwargs: Any) -> Any:
        nonlocal raw_inspections
        if args and is_raw_root(args[0]):
            raw_inspections += 1
        return original_inspect(*args, **kwargs)

    def counted_owned_canonical(*args: Any, **kwargs: Any) -> Any:
        nonlocal owned_root_closures
        if args and is_raw_root(getattr(args[0], "_root", None)):
            owned_root_closures += 1
        return original_owned_canonical(*args, **kwargs)

    def counted_canonical(*args: Any, **kwargs: Any) -> Any:
        nonlocal canonical_root_closures
        if args and is_raw_root(args[0]):
            canonical_root_closures += 1
        return original_canonical(*args, **kwargs)

    def counted_deepcopy(value: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal raw_copy_count
        if is_raw_root(value):
            raw_copy_count += 1
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(
        table_semantics, "_inspect_plain_table_value", counted_inspect
    )
    monkeypatch.setattr(
        table_semantics,
        "_assert_owned_canonical_table_json",
        counted_owned_canonical,
    )
    monkeypatch.setattr(
        table_semantics, "_assert_canonical_table_json", counted_canonical
    )
    monkeypatch.setattr(table_semantics, "deepcopy", counted_deepcopy)

    _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert raw_inspections == 1
    assert owned_root_closures == expected_owned_closures
    assert canonical_root_closures == 0
    assert raw_copy_count == 1


@pytest.mark.parametrize(
    ("attack", "error_type", "message"),
    (
        ("bytes", TypeError, "canonical table JSON must not contain bytes"),
        ("tuple", TypeError, "canonical table JSON must use lists"),
        ("key", TypeError, "canonical table JSON keys must be text"),
        ("nan", ValueError, "non-finite table value"),
        ("surrogate", ValueError, "table text must be valid UTF-8"),
        ("oversize", ValueError, "table string limit exceeded"),
    ),
)
def test_owned_root_rejects_every_json_shape_attack_before_fixed_builder(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
    error_type: type[Exception],
    message: str,
) -> None:
    raw = _header_table()
    if attack == "bytes":
        raw["zz_unused_hostile"] = b"hostile"
    elif attack == "tuple":
        raw["zz_unused_hostile"] = ("hostile",)
    elif attack == "key":
        raw[7] = "hostile"  # type: ignore[index]
    elif attack == "nan":
        raw["zz_unused_hostile"] = float("nan")
    elif attack == "surrogate":
        raw["zz_unused_hostile"] = "\ud800"
    else:
        raw["zz_unused_hostile"] = "x" * 1_048_577
    builder_calls = 0

    def forbidden_builder(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal builder_calls
        builder_calls += 1
        pytest.fail("builder observed a non-canonical admitted root")

    monkeypatch.setattr(
        pipeline,
        "_build_docling_table_predecessor",
        forbidden_builder,
    )

    with pytest.raises(error_type, match=message):
        _docling_table_item(
            raw,
            {1: 100.0},
            {1: _header_words()},
            None,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
        )

    assert builder_calls == 0


def test_owned_serializer_requires_private_admission_capability() -> None:
    with pytest.raises(
        TypeError, match="owned canonical table root differs"
    ):
        table_semantics._assert_owned_canonical_table_json(
            _header_table(),
            8_388_608,
            table_semantics.perf_counter() + 0.500,
        )


def test_owned_recovery_may_replace_only_its_scoped_json_failure() -> None:
    raw = _bottom_table()
    hostile_plan = (b"hostile",)
    raw["_p04_table_recovery_plan"] = hostile_plan

    _page_index, projected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert "table_evidence" in projected
    assert raw["_p04_table_recovery_plan"] is hostile_plan


@pytest.mark.parametrize("attack", ("object", "cycle", "depth"))
def test_hostile_raw_is_rejected_before_fixed_builder(
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    raw = _header_table()
    if attack == "object":
        hostile: object = object()
        error_type: type[Exception] = TypeError
    elif attack == "cycle":
        cycle: list[Any] = []
        cycle.append(cycle)
        hostile = cycle
        error_type = ValueError
    else:
        hostile = None
        for _depth in range(32):
            hostile = [hostile]
        error_type = ValueError
    raw["zz_unused_hostile"] = hostile
    builder_calls = 0

    def forbidden_builder(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal builder_calls
        builder_calls += 1
        pytest.fail("builder observed a hostile unadmitted root")

    monkeypatch.setattr(
        pipeline,
        "_build_docling_table_predecessor",
        forbidden_builder,
    )

    with pytest.raises(error_type):
        _docling_table_item(
            raw,
            {1: 100.0},
            {1: _header_words()},
            None,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
        )

    assert builder_calls == 0


def test_private_orchestrator_rejects_non_exact_raw_mapping() -> None:
    class RawMapping(dict[str, Any]):
        pass

    with pytest.raises(TypeError, match="source must be an exact dict"):
        _docling_table_item(
            RawMapping(_header_table()),
            {1: 100.0},
            {1: _header_words()},
            None,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
        )


def test_normalizer_replays_non_exact_raw_mapping_through_flag_off() -> None:
    class RawMapping(dict[str, Any]):
        pass

    raw_table = RawMapping(_header_table())
    raw_document = {
        "tables": [raw_table],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": raw_table["self_ref"]}]},
    }
    expected_body, expected_tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0},
        ["Term Definition FERS Federal Employees"],
        {},
        {1: _header_words()},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )

    body, tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0},
        ["Term Definition FERS Federal Employees"],
        {},
        {1: _header_words()},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() + 5.0
        ),
        table_span_fidelity_page_deadlines={},
        table_span_fidelity_state={},
    )

    assert (body, tables) == (expected_body, expected_tables)
    assert all(
        "table_evidence" not in table
        and "_p04_predecessor_snapshot" not in table
        for table in tables[1]
    )


def _plain_container_ids(value: object) -> set[int]:
    observed: set[int] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if type(current) not in (dict, list, tuple):
            continue
        identity = id(current)
        if identity in observed:
            continue
        observed.add(identity)
        pending.extend(
            current.values() if type(current) is dict else current
        )
    return observed


def test_fixed_builder_is_read_only_and_output_retains_no_input_container() -> None:
    raw = _bottom_table()
    raw_before = deepcopy(raw)
    page_words = {1: _bottom_words()}
    input_ids = _plain_container_ids(raw) | _plain_container_ids(page_words)

    page_index, item = pipeline._build_docling_table_predecessor(
        raw,
        {1: 100.0},
        page_words,
        None,
        None,
    )

    assert page_index == 1
    assert raw == raw_before
    assert not (input_ids & _plain_container_ids(item))


def test_projection_owns_raw_and_selected_word_aliases_without_output_alias() -> None:
    raw = _bottom_table()
    shared = [{"plain": ["source"]}]
    raw["shared_left"] = shared
    raw["shared_right"] = shared
    words = _bottom_words()
    word_mapping = {1: words}

    _page_index, projected = _docling_table_item(
        raw,
        {1: 100.0},
        word_mapping,
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )
    frozen = deepcopy(projected)
    raw["shared_left"][0]["plain"][0] = "caller mutation"
    raw["data"]["table_cells"][0]["text"] = "caller cell mutation"
    words[0]["text"] = "caller word mutation"

    assert projected == frozen
    assert raw["shared_left"] is raw["shared_right"]
    assert not (
        (_plain_container_ids(raw) | _plain_container_ids(word_mapping))
        & _plain_container_ids(projected)
    )


def test_local_source_rejection_is_exact_flag_off_predecessor() -> None:
    raw = _header_table()
    raw.pop("prov")

    off_page, predecessor = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    on_page, rejected = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _header_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert on_page == off_page == 1
    assert rejected == predecessor
    assert "table_evidence" not in rejected
    assert "_p04_predecessor_snapshot" not in rejected


def test_tuple_provenance_local_rejection_preserves_flag_off_page_two() -> None:
    raw = _header_table()
    raw["prov"] = tuple(raw["prov"])
    raw["prov"][0]["page_no"] = 2
    page_heights = {2: 100.0}
    page_words = {2: _header_words()}

    off_page, predecessor = _docling_table_item(
        raw,
        page_heights,
        page_words,
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    on_page, rejected = _docling_table_item(
        raw,
        page_heights,
        page_words,
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
    )

    assert on_page == off_page == 2
    assert rejected == predecessor
    assert "source_document_identity" not in rejected
    assert "table_evidence" not in rejected
    assert "_p04_predecessor_snapshot" not in rejected


@pytest.mark.parametrize(
    "malformed_provenance",
    (
        [None],
        [{"page_no": "not-an-integer"}],
    ),
)
def test_local_rejection_preserves_flag_off_malformed_provenance_failure(
    malformed_provenance: object,
) -> None:
    raw = _header_table()
    raw["prov"] = malformed_provenance

    def capture(*, enabled: bool) -> tuple[type[BaseException], tuple[object, ...]]:
        with pytest.raises(Exception) as caught:
            _docling_table_item(
                raw,
                {1: 100.0},
                {1: _header_words()},
                None,
                SOURCE_SHA256,
                table_span_fidelity_enabled=enabled,
            )
        return type(caught.value), caught.value.args

    assert capture(enabled=True) == capture(enabled=False)


def test_private_orchestrator_resolves_and_reuses_one_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _bottom_table()
    now = table_semantics.perf_counter()
    resolved: list[float] = []
    checked: list[float] = []
    original_resolve = table_semantics._resolve_table_page_deadline
    original_check = table_semantics._check_table_deadline

    def counted_resolve(*args: Any, **kwargs: Any) -> float:
        value = original_resolve(*args, **kwargs)
        resolved.append(value)
        return value

    def counted_check(value: float) -> None:
        checked.append(value)
        original_check(value)

    monkeypatch.setattr(
        table_semantics,
        "_resolve_table_page_deadline",
        counted_resolve,
    )
    monkeypatch.setattr(
        table_semantics,
        "_check_table_deadline",
        counted_check,
    )

    _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=now + 0.500,
        table_span_fidelity_document_deadline=now + 5.000,
    )

    assert resolved == [now + 0.500]
    assert checked
    assert set(checked) == {resolved[0]}


def test_orchestrator_timeout_replays_every_same_page_attempt_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _bottom_table()
    first["self_ref"] = "#/tables/first"
    second = deepcopy(first)
    second["self_ref"] = "#/tables/second"
    raw_document = {
        "tables": [first, second],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": first["self_ref"]},
                {"$ref": second["self_ref"]},
            ]
        },
    }
    arguments = (
        raw_document,
        {1: 100.0},
        ["FERS Federal Employees Retirement System"],
        {},
        {1: _bottom_words()},
    )
    expected = pipeline._normalize_docling_body(
        *arguments,
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=False,
    )
    original_owned_canonical = (
        table_semantics._assert_owned_canonical_table_json
    )

    def timeout_second_root(
        owned: Any,
        maximum_bytes: int,
        deadline: float,
    ) -> None:
        value = getattr(owned, "_root", None)
        if (
            type(value) is dict
            and value.get("self_ref") == second["self_ref"]
            and type(value.get("data")) is dict
        ):
            raise TimeoutError("forced second-table canonical timeout")
        original_owned_canonical(owned, maximum_bytes, deadline)

    monkeypatch.setattr(
        table_semantics,
        "_assert_owned_canonical_table_json",
        timeout_second_root,
    )
    observed = pipeline._normalize_docling_body(
        *arguments,
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() + 5.0
        ),
        table_span_fidelity_page_deadlines={},
        table_span_fidelity_state={},
    )

    assert observed == expected
    assert len(observed[1][1]) == 2
    assert all(
        "table_evidence" not in table
        and "_p04_predecessor_snapshot" not in table
        for table in observed[1][1]
    )


def test_allowed_bound_input_frontier_has_bounded_allocation_and_rss() -> None:
    root = Path(__file__).resolve().parents[3]
    script = r'''
import gc
import json
import resource
import sys
import tracemalloc

from app.services import table_semantics
from tests.stories.phase_04.test_p04_us01_table_input_recovery import (
    _bottom_table,
    _bottom_words,
)


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


raw = _bottom_table()
branch = None
for _depth in range(25):
    # Placing the next branch last is adversarial for a LIFO walker: an eager
    # implementation retains every 65,000-item sibling frontier at once.
    branch = [None] * 65_000 + [branch]
raw["allowed_padding"] = branch
source_bytes = len(
    json.dumps(
        raw,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
)

# Isolate allocation/resource behavior from the page clock. The production
# deadline validation still runs against these finite approved deadlines.
table_semantics.perf_counter = lambda: 0.0
gc.collect()
before_rss = rss_bytes()
tracemalloc.start()
predecessor, recovered = table_semantics.prepare_docling_table_inputs(
    raw,
    {1: 100.0},
    {1: _bottom_words()},
    table_span_fidelity_enabled=True,
    table_span_fidelity_deadline=0.5,
    table_span_fidelity_document_deadline=5.0,
)
_current_bytes, peak_allocated_bytes = tracemalloc.get_traced_memory()
tracemalloc.stop()
after_rss = rss_bytes()

print(json.dumps({
    "distinct_outputs": (
        predecessor is not raw
        and recovered is not raw
        and recovered is not predecessor
    ),
    "peak_allocated_bytes": peak_allocated_bytes,
    "recovery_retained": "_p04_table_recovery_plan" in recovered,
    "rss_delta_bytes": max(0, after_rss - before_rss),
    "source_bytes": source_bytes,
}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    measurement = json.loads(completed.stdout.strip().splitlines()[-1])

    assert 8_000_000 <= measurement["source_bytes"] <= 8_388_608
    assert measurement["distinct_outputs"] is True
    assert measurement["recovery_retained"] is True
    assert measurement["peak_allocated_bytes"] <= 67_108_864
    assert measurement["rss_delta_bytes"] <= 67_108_864


def test_pipeline_owned_root_meets_500ms_and_resource_bounds_under_forced_gc() -> None:
    root = Path(__file__).resolve().parents[3]
    script = r'''
import gc
import json
import resource
import sys
import time
import tracemalloc

from app.services import table_semantics
from app.services.pipeline import _docling_table_item
from tests.stories.phase_04.test_p04_us01_table_input_recovery import (
    SOURCE_SHA256,
    _bottom_table,
    _bottom_words,
)


def rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


raw = _bottom_table()
# 325,000 null leaves serialize to about 1.626 MB and account for roughly
# 10.4 MB under the strict admitted-graph accounting policy.
raw["allowed_padding"] = [[None] * 65_000 for _ in range(5)]
source_bytes = len(
    json.dumps(
        raw,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
)
latencies = []
for _attempt in range(5):
    gc.collect()
    started = time.perf_counter()
    _page_index, table = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=started + 0.500,
        table_span_fidelity_document_deadline=started + 5.000,
    )
    latencies.append(time.perf_counter() - started)
    assert "table_evidence" in table

gc.collect()
before_rss = rss_bytes()
tracemalloc.start()
original_perf_counter = table_semantics.perf_counter
table_semantics.perf_counter = lambda: 0.0
try:
    _page_index, measured = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=0.500,
        table_span_fidelity_document_deadline=5.000,
    )
finally:
    table_semantics.perf_counter = original_perf_counter
_current_bytes, peak_allocated_bytes = tracemalloc.get_traced_memory()
tracemalloc.stop()
after_rss = rss_bytes()

print(json.dumps({
    "all_marked": "table_evidence" in measured,
    "latencies": latencies,
    "peak_allocated_bytes": peak_allocated_bytes,
    "rss_delta_bytes": max(0, after_rss - before_rss),
    "source_bytes": source_bytes,
}, sort_keys=True))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    measurement = json.loads(completed.stdout.strip().splitlines()[-1])

    assert 1_500_000 <= measurement["source_bytes"] <= 1_750_000
    assert len(measurement["latencies"]) == 5
    assert max(measurement["latencies"]) < 0.500
    assert measurement["all_marked"] is True
    assert measurement["peak_allocated_bytes"] <= 67_108_864
    assert measurement["rss_delta_bytes"] <= 67_108_864


def test_recovery_ids_are_invariant_to_pdfplumber_input_array_order() -> None:
    first = _project(_bottom_table(), _bottom_words())
    second = _project(_bottom_table(), list(reversed(_bottom_words())))

    assert first["cells"] == second["cells"]
    assert first["rows"] == second["rows"]
    assert first["table_evidence"] == second["table_evidence"]


@pytest.mark.parametrize(
    "mutation",
    [
        "word_text",
        "word_order",
        "font_control",
        "source_collision",
        "method_flip",
        "cell_text",
    ],
)
def test_recovery_replay_rejects_every_source_or_method_tamper(
    mutation: str,
) -> None:
    table = _project(_bottom_table(), _bottom_words())
    predecessor = deepcopy(table["_p04_predecessor_snapshot"])
    sidecar = deepcopy(table["table_evidence"])
    bottom_sources = [
        source
        for source in sidecar["source_objects"]
        if source.get("role") == "bottom_row"
    ]
    if mutation == "word_text":
        bottom_sources[0]["words"][0]["text"] = "CSRS"
    elif mutation == "word_order":
        multiword = next(
            source for source in bottom_sources if len(source["words"]) > 1
        )
        multiword["words"].reverse()
    elif mutation == "font_control":
        bottom_sources[0]["words"][0]["font_name"] = "Bad\nFont"
    elif mutation == "source_collision":
        bottom_sources[1]["id"] = bottom_sources[0]["id"]
        sidecar["source_objects"].sort(key=lambda source: source["id"])
    elif mutation == "method_flip":
        structure = next(
            evidence
            for evidence in sidecar["evidence"]
            if evidence["dimension"] == "structure"
        )
        structure["method"] = "source_grid"
    else:
        table["cells"][-1]["text"] = "invented"
    table["table_evidence"] = sidecar

    assert table_semantics.validate_table_semantics(table, SOURCE_SHA256) is False
    table_semantics.replay_table_semantics(
        table,
        sidecar,
        source_sha256=SOURCE_SHA256,
    )

    assert table == predecessor


def test_recovery_accepts_exact_48_word_set_table_boundary() -> None:
    column_count = 16
    cells = [
        _cell(
            row,
            column,
            f"{'H' if row == 0 else 'B'}{column}",
            left=float(column * 10),
            top=10.0 if row == 0 else 30.0,
            right=float(column * 10 + 10),
            bottom=25.0 if row == 0 else 45.0,
        )
        for row in range(2)
        for column in range(column_count)
    ]
    raw = _table(cells)
    raw["prov"][0]["bbox"]["r"] = 160.0
    raw["data"]["num_cols"] = column_count
    words = []
    for column in range(column_count):
        left = float(column * 10 + 1)
        right = float(column * 10 + 4)
        words.extend(
            [
                _word(
                    f"H{column}",
                    x0=left,
                    x1=right,
                    top=15.0,
                    bottom=20.0,
                    bold=True,
                ),
                _word(
                    f"B{column}",
                    x0=left,
                    x1=right,
                    top=35.0,
                    bottom=40.0,
                    bold=False,
                ),
                _word(
                    f"C{column}",
                    x0=left,
                    x1=right,
                    top=50.0,
                    bottom=55.0,
                    bold=False,
                ),
            ]
        )

    prepared = _prepare(raw, words)
    plan = prepared["_p04_table_recovery_plan"]
    table = _project(raw, words)
    pdf_sources = [
        source
        for source in table["table_evidence"]["source_objects"]
        if source["engine"] == "pdfplumber"
    ]

    assert len(plan["header"]) == 16
    assert len(plan["bottom_row"]["cells"]) == 16
    assert len(pdf_sources) == 48
    assert table["row_count"] == 3
    assert table["column_count"] == 16
    assert table_semantics.validate_table_semantics(table, SOURCE_SHA256)


def test_projection_seal_and_finalize_reuse_one_physical_page_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    page_deadlines = {1: 0.5}
    state: dict[str, bool] = {}
    _page_index, table = _docling_table_item(
        _bottom_table(),
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=page_deadlines[1],
        table_span_fidelity_document_deadline=5.0,
    )
    pages = [
        {
            "page_index": 1,
            "page_width": 200.0,
            "page_height": 100.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    now[0] = 0.4
    table_semantics.seal_table_pages(
        pages,
        SOURCE_SHA256,
        [],
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
        table_span_fidelity_state=state,
    )
    now[0] = 0.49
    table_semantics.finalize_table_pages(
        pages,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
        table_span_fidelity_state=state,
    )

    assert table["row_count"] == 3
    assert table["table_evidence"]["status"] == "valid"
    assert "_p04_predecessor_snapshot" not in table
    assert page_deadlines == {1: 0.5}
    assert state == {}


def test_suspended_budget_exact_bound_commits_and_epsilon_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])

    def exercise(final_time: float) -> tuple[dict[str, Any], dict[str, Any]]:
        now[0] = 0.0
        page_deadlines = {1: 0.5}
        state: dict[str, Any] = {}
        document_deadline = pipeline._resume_table_span_fidelity_budget(
            5.0,
            page_deadlines,
            state,
        )

        # Repair extraction consumes 0.100s. A 100s unrelated parser interval
        # is excluded without replenishing the remaining 0.400s page budget.
        now[0] = 0.1
        pipeline._suspend_table_span_fidelity_budget(state)
        now[0] = 100.1
        document_deadline = pipeline._resume_table_span_fidelity_budget(
            document_deadline,
            page_deadlines,
            state,
        )
        _page_index, table = _docling_table_item(
            _bottom_table(),
            {1: 100.0},
            {1: _bottom_words()},
            None,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
            table_span_fidelity_deadline=page_deadlines[1],
            table_span_fidelity_document_deadline=document_deadline,
        )
        predecessor = deepcopy(table["_p04_predecessor_snapshot"])

        # Projection consumes 0.150s, seal consumes 0.100s, and another two
        # 100s unrelated intervals remain excluded. The finalizer receives
        # exactly the 0.150s that remains, never a reset 0.500s budget.
        now[0] = 100.25
        pipeline._suspend_table_span_fidelity_budget(state)
        now[0] = 200.25
        document_deadline = pipeline._resume_table_span_fidelity_budget(
            document_deadline,
            page_deadlines,
            state,
        )
        pages = [
            {
                "page_index": 1,
                "page_width": 200.0,
                "page_height": 100.0,
                "unit": "pt",
                "items": [table],
            }
        ]
        table_semantics.seal_table_pages(
            pages,
            SOURCE_SHA256,
            [],
            table_span_fidelity_enabled=True,
            table_span_fidelity_document_deadline=document_deadline,
            table_span_fidelity_page_deadlines=page_deadlines,
            table_span_fidelity_state=state,
        )
        now[0] = 200.35
        pipeline._suspend_table_span_fidelity_budget(state)
        now[0] = 300.35
        document_deadline = pipeline._resume_table_span_fidelity_budget(
            document_deadline,
            page_deadlines,
            state,
        )
        assert page_deadlines[1] == pytest.approx(300.5)
        assert document_deadline == pytest.approx(305.0)
        now[0] = final_time
        table_semantics.finalize_table_pages(
            pages,
            SOURCE_SHA256,
            table_span_fidelity_enabled=True,
            table_span_fidelity_document_deadline=document_deadline,
            table_span_fidelity_page_deadlines=page_deadlines,
            table_span_fidelity_state=state,
        )
        pipeline._finish_table_span_fidelity_budget(state)
        assert state == {}
        return table, predecessor

    exact, _exact_predecessor = exercise(300.5)
    assert exact["table_evidence"]["status"] == "valid"
    assert "_p04_predecessor_snapshot" not in exact

    overflow, overflow_predecessor = exercise(300.500001)
    assert overflow == overflow_predecessor
    assert "table_evidence" not in overflow
    assert "_p04_predecessor_snapshot" not in overflow


def test_document_timeout_is_one_way_and_restores_all_table_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    page_deadlines = {1: 0.5}
    state: dict[str, bool] = {}
    raw = _bottom_table()
    _page_index, table = _docling_table_item(
        raw,
        {1: 100.0},
        {1: _bottom_words()},
        None,
        SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_deadline=page_deadlines[1],
        table_span_fidelity_document_deadline=5.0,
    )
    predecessor = deepcopy(table["_p04_predecessor_snapshot"])
    pages = [
        {
            "page_index": 1,
            "page_width": 200.0,
            "page_height": 100.0,
            "unit": "pt",
            "items": [table],
        }
    ]

    now[0] = 5.1
    table_semantics.seal_table_pages(
        pages,
        SOURCE_SHA256,
        [],
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
        table_span_fidelity_state=state,
    )

    assert table == predecessor
    assert state == {"timed_out": True}

    now[0] = 0.0
    raw_document = {
        "tables": [raw],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": raw["self_ref"]}]},
    }
    _body, tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0},
        [""],
        {},
        {1: _bottom_words()},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=5.0,
        table_span_fidelity_page_deadlines=page_deadlines,
        table_span_fidelity_state=state,
    )
    assert all("table_evidence" not in item for item in tables[1])


def test_cross_page_segments_charge_document_without_spending_other_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    observed_page_deadlines: list[float] = []
    observed_document_deadlines: list[float] = []

    first = _bottom_table()
    first["self_ref"] = "#/tables/first"
    second = deepcopy(first)
    second["self_ref"] = "#/tables/second"
    second["prov"][0]["page_no"] = 2

    def fake_table_item(
        raw_item: dict[str, Any],
        *_args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        page_index = raw_item["prov"][0]["page_no"]
        if kwargs.get("table_span_fidelity_enabled") is not True:
            return page_index, {
                "type": "table",
                "rows": [[f"predecessor:{page_index}"]],
            }
        page_deadline = kwargs["table_span_fidelity_deadline"]
        document_deadline = kwargs["table_span_fidelity_document_deadline"]
        observed_page_deadlines.append(page_deadline)
        observed_document_deadlines.append(document_deadline)
        now[0] += 0.300
        if now[0] > page_deadline:
            raise TimeoutError("table operation deadline exceeded")
        return page_index, {
            "type": "table",
            "rows": [[f"overlay:{page_index}"]],
            "table_evidence": {"status": "diagnostic"},
            "_p04_predecessor_snapshot": {
                "type": "table",
                "rows": [[f"predecessor:{page_index}"]],
            },
        }

    monkeypatch.setattr(pipeline, "_docling_table_item", fake_table_item)
    page_deadlines: dict[int, float] = {}
    state: dict[str, Any] = {}
    raw_document = {
        "tables": [first, second],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {
            "children": [
                {"$ref": first["self_ref"]},
                {"$ref": second["self_ref"]},
            ]
        },
    }

    _body, tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0, 2: 100.0},
        ["", ""],
        {},
        {},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=105.0,
        table_span_fidelity_page_deadlines=page_deadlines,
        table_span_fidelity_state=state,
    )

    assert observed_page_deadlines == [100.5, 100.8]
    assert observed_document_deadlines == [105.0, 105.0]
    assert page_deadlines == {1: 100.8, 2: 100.8}
    assert page_deadlines[1] - now[0] == pytest.approx(0.2)
    assert page_deadlines[2] - now[0] == pytest.approx(0.2)
    assert [tables[page][0]["rows"] for page in (1, 2)] == [
        [["overlay:1"]],
        [["overlay:2"]],
    ]


@pytest.mark.parametrize(
    ("finished_at", "expected_text", "has_evidence"),
    [
        (100.5, "overlay", True),
        (100.500001, "predecessor", False),
    ],
)
def test_projection_completion_enforces_exact_page_deadline(
    monkeypatch: pytest.MonkeyPatch,
    finished_at: float,
    expected_text: str,
    has_evidence: bool,
) -> None:
    now = [100.0]
    monkeypatch.setattr(pipeline.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: now[0])
    raw = _bottom_table()

    def fake_table_item(
        raw_item: dict[str, Any],
        *_args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        page_index = raw_item["prov"][0]["page_no"]
        predecessor = {
            "type": "table",
            "rows": [["predecessor"]],
        }
        if kwargs.get("table_span_fidelity_enabled") is not True:
            return page_index, predecessor
        assert kwargs["table_span_fidelity_deadline"] == 100.5
        now[0] = finished_at
        return page_index, {
            "type": "table",
            "rows": [["overlay"]],
            "table_evidence": {"status": "diagnostic"},
            "_p04_predecessor_snapshot": predecessor,
        }

    monkeypatch.setattr(pipeline, "_docling_table_item", fake_table_item)
    raw_document = {
        "tables": [raw],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": raw["self_ref"]}]},
    }

    _body, tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0},
        [""],
        {},
        {},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=105.0,
        table_span_fidelity_page_deadlines={},
        table_span_fidelity_state={},
    )

    table = tables[1][0]
    assert table["rows"] == [[expected_text]]
    assert ("table_evidence" in table) is has_evidence
    assert ("_p04_predecessor_snapshot" in table) is has_evidence


def test_word_geometry_disable_state_emits_exact_predecessor_table_authority() -> None:
    raw = _bottom_table()
    raw_document = {
        "tables": [raw],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": raw["self_ref"]}]},
    }
    common = {
        "page_heights": {1: 100.0},
        "native_texts": [
            "Term Definition FEHB Federal Employees Health Benefits"
        ],
        "image_regions": {},
        "page_words_by_page": {},
        "source_document_identity": SOURCE_SHA256,
    }

    predecessor = pipeline._normalize_docling_body(  # noqa: SLF001
        raw_document,
        **common,
        table_span_fidelity_enabled=False,
    )
    disabled = pipeline._normalize_docling_body(  # noqa: SLF001
        raw_document,
        **common,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() + 5.0
        ),
        table_span_fidelity_page_deadlines={},
        table_span_fidelity_state={
            "span_fidelity_disabled": True,
            "span_fidelity_failure_reason": (
                "table_word_geometry_unavailable"
            ),
        },
    )

    assert disabled == predecessor
    assert all(
        "table_evidence" not in table
        and "_p04_predecessor_snapshot" not in table
        for tables in disabled[1].values()
        for table in tables
    )


def test_projection_cannot_relabel_source_page_to_obtain_another_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_table_item = pipeline._docling_table_item

    def relabeled_table_item(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[int, dict[str, Any]]:
        page_index, item = original_table_item(*args, **kwargs)
        if kwargs.get("table_span_fidelity_enabled") is True:
            return page_index + 1, item
        return page_index, item

    monkeypatch.setattr(
        pipeline,
        "_docling_table_item",
        relabeled_table_item,
    )
    raw = _bottom_table()
    raw_document = {
        "tables": [raw],
        "texts": [],
        "pictures": [],
        "groups": [],
        "key_value_items": [],
        "form_items": [],
        "body": {"children": [{"$ref": raw["self_ref"]}]},
    }

    _body, tables = pipeline._normalize_docling_body(
        raw_document,
        {1: 100.0, 2: 100.0},
        ["", ""],
        {},
        {1: _bottom_words()},
        source_document_identity=SOURCE_SHA256,
        table_span_fidelity_enabled=True,
        table_span_fidelity_document_deadline=(
            table_semantics.perf_counter() + 5.0
        ),
    )

    assert list(tables) == [1]
    assert len(tables[1]) == 1
    assert "table_evidence" not in tables[1][0]
    assert "_p04_predecessor_snapshot" not in tables[1][0]
