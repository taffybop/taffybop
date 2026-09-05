"""Source-oracle checks for nested content in the ACORD COVERAGES grid."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pytest

from tests.regression.phase_03.test_p03_us06_acord_form_read_order import (
    _release_payload,
)


def _coverage_owner(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    owners = [
        item
        for page in payload["pages"]
        for item in page["items"]
        if isinstance(item.get("form_group"), Mapping)
        and isinstance(item["form_group"].get("form_grid"), Mapping)
    ]
    assert len(owners) == 1
    return owners[0]


def _bbox(value: Mapping[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def _cell(
    grid: Mapping[str, Any],
    row: int,
    column: int,
) -> Mapping[str, Any]:
    matches = [
        cell
        for cell in grid["cells"]
        if cell["row"] == row and cell["column"] == column
    ]
    assert len(matches) == 1
    return matches[0]


def _fragment(
    cell: Mapping[str, Any],
    *,
    text: str | None = None,
    control_id: str | None = None,
) -> Mapping[str, Any]:
    matches = [
        fragment
        for fragment in cell["content_fragments"]
        if (text is None or fragment.get("text") == text)
        and (control_id is None or fragment.get("control_id") == control_id)
    ]
    assert len(matches) == 1
    return matches[0]


def _canonical_grid_html(
    payload: Mapping[str, Any],
    owner: Mapping[str, Any],
) -> str:
    anchor_id = owner["form_group"]["anchor_element_id"]
    matches = [
        block["markdown"]
        for page in payload["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block["primary_element_id"] == anchor_id
    ]
    assert len(matches) == 1
    return str(matches[0])


def _rendered_cell(markdown: str, reading_order: int) -> str:
    match = re.search(
        rf'<(th|td) [^>]*data-reading-order="{reading_order}"[^>]*>'
        rf"(.*?)</\1>",
        markdown,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(2)


@pytest.mark.integration
def test_acord_nested_option_geometry_matches_the_visible_source() -> None:
    payload = _release_payload()
    owner = _coverage_owner(payload)
    group = owner["form_group"]
    grid = group["form_grid"]

    # The outer policy grid remains nine columns.  The second column contains
    # four independently ruled option subforms, not a paragraph of labels.
    assert tuple(grid["column_boundaries"]) == (
        18.0,
        36.0,
        176.4,
        194.4,
        212.4,
        331.2,
        378.0,
        424.8,
        514.8,
        594.0,
    )
    section_oracle = {
        (1, 1): ((36.0, 300.0, 140.4, 84.0), 7),
        (8, 1): ((36.0, 384.0, 140.4, 60.0), 5),
        (13, 1): ((36.0, 444.0, 140.4, 36.0), 3),
        (16, 1): ((36.0, 480.0, 140.4, 48.0), 4),
    }
    for position, (expected_bbox, expected_row_span) in section_oracle.items():
        section = _cell(grid, *position)
        assert _bbox(section["bbox"]) == pytest.approx(expected_bbox, abs=0.001)
        assert section["row_span"] == expected_row_span
        assert section["static_kind"] == "section_header"

    controls = {control["id"]: control for control in owner["form_controls"]}
    labels = {label["id"]: label for label in owner["form_labels"]}

    # These pairs are visually side-by-side in the original, including the
    # two-column automobile and umbrella option rows.
    paired_controls = (
        ((50.4, 324.0), "CLAIMS-MADE", (68.4, 329.202)),
        ((115.2, 324.0), "OCCUR", (133.2, 329.202)),
        ((36.0, 408.0), "ALL OWNED AUTOS", (54.0, 408.762)),
        ((104.4, 408.0), "SCHEDULED AUTOS", (122.4, 408.762)),
        ((36.0, 420.0), "HIRED AUTOS", (54.0, 425.682)),
        ((104.4, 420.0), "NON-OWNED AUTOS", (122.4, 420.642)),
        ((36.0, 444.0), "UMBRELLA LIAB", (54.0, 447.241)),
        ((115.2, 444.0), "OCCUR", (133.2, 449.682)),
        ((36.0, 456.0), "EXCESS LIAB", (54.0, 459.241)),
        ((115.2, 456.0), "CLAIMS-MADE", (133.2, 461.202)),
    )
    for control_xy, label_text, label_xy in paired_controls:
        candidates = [
            control
            for control in controls.values()
            if _bbox(control["bbox"])[:2] == control_xy
        ]
        assert len(candidates) == 1
        control = candidates[0]
        assert control["label_id"] in labels
        label = labels[control["label_id"]]
        assert label["text"] == label_text
        assert _bbox(label["bbox"])[:2] == pytest.approx(label_xy, abs=0.001)

    # The four source-visible option boxes remain explicit even when their
    # labels cannot be recovered. Their empty interiors still prove that the
    # controls are unchecked rather than state-ambiguous.
    unlabeled_oracle = {
        (36.0, 336.0),
        (36.0, 348.0),
        (36.0, 432.0),
        (104.4, 432.0),
    }
    unlabeled = {
        _bbox(control["bbox"])[:2]
        for control in controls.values()
        if control["label_id"] is None
    }
    assert unlabeled == unlabeled_oracle
    assert all(
        control["state"] == "unchecked" and control["concern_codes"] == []
        for control in controls.values()
        if control["label_id"] is None
    )
    yn_controls = [
        control
        for control in controls.values()
        if control.get("label_id") in labels
        and labels[control["label_id"]]["text"] == "Y / N"
    ]
    assert len(yn_controls) == 1
    assert _bbox(yn_controls[0]["bbox"]) == (158.4, 498.0, 14.4, 12.0)
    assert yn_controls[0]["state"] == "unchecked"
    assert yn_controls[0]["concern_codes"] == []

    # Every paired label/control remains in its section cell as independent,
    # positioned evidence; no composite label is synthesized from row text.
    general = _cell(grid, 1, 1)
    claims = next(
        control
        for control in controls.values()
        if _bbox(control["bbox"])[:2] == (50.4, 324.0)
    )
    assert _bbox(_fragment(general, control_id=claims["id"])["bbox"]) == (
        50.4,
        324.0,
        14.4,
        12.0,
    )
    assert _bbox(_fragment(general, text="CLAIMS-MADE")["bbox"]) == pytest.approx(
        (68.4, 329.202, 41.67, 6.0),
        abs=0.001,
    )


@pytest.mark.integration
def test_acord_canonical_grid_serializes_nested_rows_and_fragment_bboxes() -> None:
    payload = _release_payload()
    owner = _coverage_owner(payload)
    grid = owner["form_group"]["form_grid"]
    markdown = _canonical_grid_html(payload, owner)

    composite_cells = [_cell(grid, row, 1) for row in (1, 8, 13, 16)]
    assert markdown.count('data-form-fragment-layout="source-rows"') == 4
    for cell in composite_cells:
        rendered = _rendered_cell(markdown, cell["reading_order"])
        assert 'data-form-fragment-layout="source-rows"' in rendered
        assert 'data-form-fragment-row="0"' in rendered
        assert "<br>" not in rendered

    general = _rendered_cell(markdown, composite_cells[0]["reading_order"])
    general_sequence = (
        'data-source-bbox="50.4 324 14.4 12"',
        "CLAIMS-MADE",
        'data-source-bbox="115.2 324 14.4 12"',
        "OCCUR",
    )
    positions = [general.index(value) for value in general_sequence]
    assert positions == sorted(positions)

    automobile = _rendered_cell(markdown, composite_cells[1]["reading_order"])
    assert 'data-source-bbox="36 408 14.4 12"' in automobile
    assert 'data-source-bbox="104.4 408 14.4 12"' in automobile
    assert automobile.index("ALL OWNED AUTOS") < automobile.index("SCHEDULED AUTOS")

    workers = _rendered_cell(markdown, composite_cells[3]["reading_order"])
    assert 'data-source-bbox="159.36 491.562 13.338 6"' in workers
    assert 'data-source-bbox="158.4 498 14.4 12"' in workers
    assert 'aria-checked="false" data-state="unchecked"' in workers
