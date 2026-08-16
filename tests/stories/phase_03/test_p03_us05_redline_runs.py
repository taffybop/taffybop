"""P03-US05 source-grounded text-run and redline contracts."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any, Iterable

import pytest

from app.config import Settings
from app.services.ir import DocumentIR, build_document_ir
from app.services.pipeline import parse_document
import app.services.text_run_semantics as text_run_semantics


extract_text_run_evidence = text_run_semantics.extract_text_run_evidence
project_text_run_semantics = getattr(
    text_run_semantics,
    "project_text_run_semantics",
    None,
)

pytestmark = pytest.mark.skipif(
    project_text_run_semantics is None,
    reason="P03-US05 projector has not landed yet",
)


WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
LOCAL_FIDELITY_ARTIFACTS = WORKSPACE / ".models" / "docling"

SOURCE_IDENTITIES = {
    "purchase-agreement": (
        152_828,
        "00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14",
    ),
    "postal-10k": (
        83_589,
        "72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74",
    ),
    "finance-10k": (
        87_105,
        "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
    ),
}

PURCHASE_DELETED_GROUPS = {
    "Draft of 6/1/20",
    (
        "This is a draft document. Certain updates will be needed prior to "
        "finalizing this."
    ),
    (
        "In particular, bracketed items with '[ ]' indicate a known "
        "open/non-final item."
    ),
    "This is Confidential to The City of Johnstown",
    "June",
    "23",
}

POSTAL_ITALIC_TARGETS = {
    "CARES Act": ("cells", 20, "text"),
    "Coronavirus Aid, Relief, and Economic Security Act": (
        "cells",
        21,
        "text",
    ),
    "Exchange Act": ("cells", 66, "text"),
    "Securities and Exchange Act of 1934": (
        "cells",
        67,
        "text",
    ),
}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@lru_cache(maxsize=None)
def _source_bytes(case: str) -> bytes:
    source = (CORPUS / f"{case}.pdf").read_bytes()
    expected_size, expected_sha256 = SOURCE_IDENTITIES[case]
    assert len(source) == expected_size
    assert _sha256(source) == expected_sha256
    return source


def _predecessor_settings() -> Settings:
    return Settings(
        # An explicit local artifact root makes the real-corpus story tests
        # deterministic and tells Docling to skip its optional figure
        # classifier when that separate model is not installed.
        docling_artifacts_path=str(LOCAL_FIDELITY_ARTIFACTS),
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
    )


@lru_cache(maxsize=None)
def _predecessor_payload(case: str) -> dict[str, Any]:
    result = parse_document(
        _source_bytes(case),
        f"{case}.pdf",
        _predecessor_settings(),
    )
    return result.model_dump(mode="json", exclude_none=True)


@lru_cache(maxsize=None)
def _evidence(case: str) -> Any:
    payload = _predecessor_payload(case)
    report = extract_text_run_evidence(
        _source_bytes(case),
        max_pages=len(payload["pages"]),
    )
    assert report.usable is True
    return report


def _project(case: str) -> tuple[DocumentIR, DocumentIR]:
    predecessor = build_document_ir(deepcopy(_predecessor_payload(case)))
    before = predecessor.model_dump(mode="json")
    projected = project_text_run_semantics(predecessor, _evidence(case))
    assert predecessor.model_dump(mode="json") == before
    assert projected is not predecessor
    return predecessor, projected


def _legacy_item(element: Any) -> dict[str, Any]:
    item = element.properties.get("legacy_item")
    assert isinstance(item, dict)
    return item


def _element_by_public_id(ir: DocumentIR, public_id: str) -> Any:
    matches = [
        element
        for element in ir.elements
        if isinstance(element.properties.get("legacy_item"), dict)
        and element.properties["legacy_item"].get("id") == public_id
    ]
    assert len(matches) == 1
    return matches[0]


def _element_by_id(ir: DocumentIR, element_id: str) -> Any:
    matches = [
        element for element in ir.elements if element.id == element_id
    ]
    assert len(matches) == 1
    return matches[0]


def _target_path(run: Any) -> tuple[str | int, ...]:
    return tuple(run.target_path)


def _resolve_target(ir: DocumentIR, run: Any) -> str:
    current: Any = _legacy_item(_element_by_id(ir, run.element_id))
    for component in _target_path(run):
        current = current[component]
    assert isinstance(current, str)
    return current


def _assert_exact_offsets_and_digest(
    ir: DocumentIR,
    runs: Iterable[Any],
) -> None:
    intervals: dict[
        tuple[str, tuple[str | int, ...]],
        list[tuple[int, int]],
    ] = defaultdict(list)
    for run in runs:
        target = _resolve_target(ir, run)
        assert 0 <= run.start < run.end <= len(target)
        assert target[run.start : run.end] == run.text
        assert run.target_text_sha256 == _sha256(target.encode("utf-8"))
        assert run.source_sha256 == ir.source_sha256
        assert tuple(run.source_character_indexes) == tuple(
            sorted(run.source_character_indexes)
        )
        intervals[(run.element_id, _target_path(run))].append(
            (run.start, run.end)
        )

    for target_intervals in intervals.values():
        ordered = sorted(target_intervals)
        assert all(
            left_end <= right_start
            for (_left_start, left_end), (right_start, _right_end) in zip(
                ordered,
                ordered[1:],
                strict=False,
            )
        )


def _decorations(run: Any) -> set[str]:
    return {_enum_value(value) for value in run.decorations}


def _change_state(run: Any) -> str:
    return str(_enum_value(run.change_state))


def _runs_with_exact_text(ir: DocumentIR, text: str) -> list[Any]:
    return [run for run in ir.text_runs if run.text == text]


def _group_texts(ir: DocumentIR, runs: Iterable[Any]) -> set[str]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        assert run.change_group_id
        grouped[run.change_group_id].append(run)

    result: set[str] = set()
    for grouped_runs in grouped.values():
        target_keys = {
            (run.element_id, _target_path(run)) for run in grouped_runs
        }
        assert len(target_keys) == 1
        target = _resolve_target(ir, grouped_runs[0])
        start = min(run.start for run in grouped_runs)
        end = max(run.end for run in grouped_runs)
        result.add(_normalized(target[start:end]))
    return result


def test_purchase_exact_deletion_and_rule_denominators() -> None:
    _predecessor, projected = _project("purchase-agreement")
    assert len(_evidence("purchase-agreement").pages) == 1
    assert len(_evidence("purchase-agreement").rules) == 13

    deleted = [
        run
        for run in projected.text_runs
        if _change_state(run) == "deleted"
    ]
    assert _group_texts(projected, deleted) == PURCHASE_DELETED_GROUPS
    assert len({run.change_group_id for run in deleted}) == 6
    assert all("strikethrough" in _decorations(run) for run in deleted)

    group_rule_pairs = {
        (run.change_group_id, rule_id)
        for run in deleted
        for rule_id in run.rule_ids
    }
    run_rule_pairs = {
        (run.id, rule_id)
        for run in deleted
        for rule_id in run.rule_ids
    }
    assert len(group_rule_pairs) == 7
    assert len(run_rule_pairs) == 9

    repair_text = {
        _normalized(_resolve_target(projected, run)[run.start : run.end])
        for run in deleted
        if _normalized(run.text) in {"Draft of 6/1/20", "June", "23"}
    }
    assert repair_text == {"Draft of 6/1/20", "June", "23"}
    _assert_exact_offsets_and_digest(projected, projected.text_runs)


def test_purchase_blue_and_ordinary_underlines_never_become_deletions() -> None:
    _predecessor, projected = _project("purchase-agreement")

    execution = _runs_with_exact_text(projected, "EXECUTION VERSION")
    placeholder = _runs_with_exact_text(projected, "_______")
    assert len(execution) == 1
    assert len(placeholder) == 1

    execution_run = execution[0]
    placeholder_run = placeholder[0]
    assert _change_state(execution_run) == "unchanged"
    assert _decorations(execution_run) == {"underline"}
    assert len(execution_run.rule_ids) == 2
    assert execution_run.placeholder is False
    assert _change_state(placeholder_run) == "unknown"
    assert _decorations(placeholder_run) == {"underline"}
    assert len(placeholder_run.rule_ids) == 2
    assert placeholder_run.placeholder is True

    for text in ("Background", "Exhibit A"):
        runs = _runs_with_exact_text(projected, text)
        assert len(runs) == 1
        assert _change_state(runs[0]) != "deleted"
        assert "underline" in _decorations(runs[0])

    assert all(
        _change_state(run) not in {"inserted", "replacement"}
        for run in projected.text_runs
    )

    linked_to_23 = {
        rule_id
        for run in _runs_with_exact_text(projected, "23")
        for rule_id in run.rule_ids
    }
    linked_to_placeholder = set(placeholder_run.rule_ids)
    assert linked_to_23.isdisjoint(linked_to_placeholder)


def test_purchase_source_heading_active_and_idempotent_projections() -> None:
    predecessor, projected = _project("purchase-agreement")

    for public_id in ("p1-i9", "p1-i10", "p1-i11", "p1-i2"):
        before = _legacy_item(_element_by_public_id(predecessor, public_id))
        after = _legacy_item(_element_by_public_id(projected, public_id))
        assert after["value"] == before["value"]

    draft = _legacy_item(_element_by_public_id(projected, "p1-i9"))
    assert draft["type"] == "text"
    assert draft.get("level") is None
    assert draft["md"] == "~~Draft of 6/1/20~~"
    assert draft["redline_markdown"] == draft["md"]
    assert draft["active_text"] == ""
    assert draft["active_text_policy"] == "omit-proven-deletions-v1"
    assert draft["md"].count("# ") == 0
    assert draft["md"].count("~~") == 2

    title = _legacy_item(_element_by_public_id(projected, "p1-i1"))
    background = _legacy_item(_element_by_public_id(projected, "p1-i3"))
    execution = _legacy_item(_element_by_public_id(projected, "p1-i8"))
    assert (title["type"], title["level"], title["md"]) == (
        "heading",
        1,
        "# ASSET PURCHASE AGREEMENT",
    )
    assert (background["type"], background["level"], background["md"]) == (
        "heading",
        2,
        "## <u>Background</u>",
    )
    assert execution["type"] == "text"

    warning = _legacy_item(_element_by_public_id(projected, "p1-i10"))
    for deleted_text in PURCHASE_DELETED_GROUPS - {
        "Draft of 6/1/20",
        "June",
        "23",
    }:
        assert deleted_text not in warning["active_text"]
        escaped = (
            deleted_text.replace("[", r"\[").replace("]", r"\]")
        )
        assert f"~~{escaped}~~" in warning["redline_markdown"]

    opening = _legacy_item(_element_by_public_id(projected, "p1-i2"))
    assert "June" not in opening["active_text"]
    assert "23" not in opening["active_text"]
    assert "_______" in opening["active_text"]
    assert "[" in opening["active_text"]
    assert "]" in opening["active_text"]

    for public_id in ("p1-i9", "p1-i10", "p1-i2"):
        element = _element_by_public_id(projected, public_id)
        item = _legacy_item(element)
        expected_omissions = [
            run.id
            for run in projected.text_runs
            if run.element_id == element.id
            and _target_path(run) == ("value",)
            and _change_state(run) == "deleted"
        ]
        expected_omissions.sort(
            key=lambda run_id: next(
                run.start for run in projected.text_runs if run.id == run_id
            )
        )
        assert item["active_text_omitted_run_ids"] == expected_omissions

    repeated = project_text_run_semantics(projected, _evidence("purchase-agreement"))
    assert repeated.model_dump(mode="json") == projected.model_dump(mode="json")


def test_heading_refinement_rejects_partial_deletion_and_competing_h1s() -> None:
    heading = SimpleNamespace(type="heading")
    assert text_run_semantics._entire_heading_is_source_deleted(
        heading,
        "Legal heading",
        [SimpleNamespace(change_state="deleted", start=0, end=5)],
    ) is False
    assert text_run_semantics._entire_heading_is_source_deleted(
        heading,
        "Legal heading",
        [
            SimpleNamespace(
                change_state="unchanged",
                start=0,
                end=len("Legal heading"),
            )
        ],
    ) is False

    def element(identifier: str, value: str, y: float) -> Any:
        return SimpleNamespace(
            id=identifier,
            type="heading",
            markdown=f"# {value}",
            properties={
                "legacy_item": {
                    "type": "heading",
                    "level": 1,
                    "value": value,
                    "md": f"# {value}",
                    "bbox": {
                        "x": 10.0,
                        "y": y,
                        "width": 100.0,
                        "height": 10.0,
                    },
                }
            },
        )

    first = element("h1-a", "First agreement", 10.0)
    second = element("h1-b", "Second agreement", 30.0)
    candidate = element("h1-c", "Background", 50.0)
    elements = {value.id: value for value in (first, second, candidate)}

    def run(value: str, *decorations: str) -> Any:
        return SimpleNamespace(
            target_path=("value",),
            change_state="unchanged",
            start=0,
            end=len(value),
            decorations=decorations,
            font_size=11.52,
        )

    text_run_semantics._refine_underlined_subordinate_heading(
        SimpleNamespace(presentation_element_ids=list(elements)),
        elements,
        {
            first.id: [run("First agreement")],
            second.id: [run("Second agreement")],
            candidate.id: [run("Background", "underline")],
        },
    )

    assert candidate.properties["legacy_item"]["level"] == 1
    assert candidate.markdown == "# Background"

def test_postal_italic_runs_resolve_to_exact_table_cells() -> None:
    predecessor, projected = _project("postal-10k")
    table_before = _legacy_item(_element_by_public_id(predecessor, "p1-i3"))
    table_after = _legacy_item(_element_by_public_id(projected, "p1-i3"))
    assert table_after["value"] == table_before["value"]
    assert table_after["cells"] == table_before["cells"]
    assert "active_text" not in table_after
    assert "redline_markdown" not in table_after

    scored_runs: list[Any] = []
    for text, expected_path in POSTAL_ITALIC_TARGETS.items():
        matches = _runs_with_exact_text(projected, text)
        assert len(matches) == 1
        run = matches[0]
        scored_runs.append(run)
        assert _target_path(run) == expected_path
        assert run.italic is True
        assert _change_state(run) == "unchanged"
        assert _decorations(run) == set()
        assert run.element_id == _element_by_public_id(projected, "p1-i3").id

    _assert_exact_offsets_and_digest(projected, scored_runs)
    assert all(
        _change_state(run) != "deleted" for run in projected.text_runs
    )


def test_finance_style_control_preserves_text_order_and_no_false_deletion() -> None:
    predecessor, projected = _project("finance-10k")
    page_ids = {page.id: page.page_index for page in projected.pages}
    page_one_runs = [
        run
        for run in projected.text_runs
        if page_ids[_element_by_id(projected, run.element_id).page_id] == 1
    ]

    for text in ("Apple Inc.", "CONSOLIDATED STATEMENTS OF OPERATIONS"):
        matches = [run for run in page_one_runs if run.text == text]
        assert len(matches) == 1
        assert matches[0].bold is True
        assert _change_state(matches[0]) == "unchanged"

    assert all(
        _change_state(run) != "deleted" for run in projected.text_runs
    )
    assert all(
        "strikethrough" not in _decorations(run)
        for run in projected.text_runs
    )

    before_page_one = [
        _legacy_item(element)
        for element in predecessor.elements
        if page_ids[element.page_id] == 1
        and element.presentation_role == "primary"
    ]
    after_page_one = [
        _legacy_item(element)
        for element in projected.elements
        if page_ids[element.page_id] == 1
        and element.presentation_role == "primary"
    ]
    assert [
        (item["id"], item.get("value"), item.get("reading_order"))
        for item in after_page_one
    ] == [
        (item["id"], item.get("value"), item.get("reading_order"))
        for item in before_page_one
    ]
    units = _legacy_item(_element_by_public_id(projected, "p1-i3"))
    assert units["value"] == (
        "(In millions, except number of shares, which are reflected in "
        "thousands, and per-share amounts)"
    )
    _assert_exact_offsets_and_digest(projected, page_one_runs)
