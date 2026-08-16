from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.services.ir import DocumentIR, build_document_ir
from app.services.presentation import build_canonical_presentation
from app.services.serializer import to_markdown


FROZEN_CORPUS_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "p00-us10-corpus-20260729-03"
)

CASE_IDS = (
    "catastrophe-recap",
    "clean-energy",
    "clinical-study",
    "component-datasheet",
    "egov-survey",
    "esg-metrics",
    "finance-10k",
    "health-report",
    "insurance-acord",
    "manufacturing-report",
    "ny-timetable",
    "postal-10k",
    "purchase-agreement",
    "settlement-agreement",
    "uber-earnings",
)

CONTROL_BODY_SIGNALS = (
    ("postal-10k", "GLOSSARY OF ACRONYMS AND DEFINED TERMS"),
    (
        "egov-survey",
        "For the first time, Member States with very high EGDI values",
    ),
    ("purchase-agreement", "EXECUTION VERSION"),
    (
        "component-datasheet",
        "Chapter 1. About Raspberry Pi Pico",
    ),
    ("clean-energy", "IEA 2024. CC BY 4.0."),
    (
        "health-report",
        "The red bubble signals an increase in mortality",
    ),
    ("esg-metrics", "TABLE OF CONTENTS"),
    ("uber-earnings", "17% YoY merchant growth"),
)


def _load_frozen_json(case_id: str) -> dict[str, Any]:
    return json.loads(
        (FROZEN_CORPUS_ROOT / case_id / "our-output.json").read_text(
            encoding="utf-8"
        )
    )


def _frozen_markdown_bytes(case_id: str) -> bytes:
    return (FROZEN_CORPUS_ROOT / case_id / "our-output.md").read_bytes()


def _page_blocks(presentation: Any) -> list[Any]:
    return [block for page in presentation.pages for block in page.blocks]


def _block_by_primary_id(presentation: Any) -> dict[str, Any]:
    return {
        block.primary_element_id: block
        for block in _page_blocks(presentation)
    }


def _included(block: Any) -> bool:
    return block.omission_reason is None


@pytest.fixture(scope="module")
def frozen_cases() -> dict[str, dict[str, Any]]:
    discovered = {
        path.name
        for path in FROZEN_CORPUS_ROOT.iterdir()
        if path.is_dir()
    }
    assert discovered == set(CASE_IDS)
    return {case_id: _load_frozen_json(case_id) for case_id in CASE_IDS}


@pytest.fixture(scope="module")
def canonical_cases(
    frozen_cases: dict[str, dict[str, Any]],
) -> dict[str, tuple[DocumentIR, Any]]:
    built: dict[str, tuple[DocumentIR, Any]] = {}
    for case_id, document in frozen_cases.items():
        ir = build_document_ir(document)
        built[case_id] = (ir, build_canonical_presentation(ir))
    return built


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_frozen_corpus_canonical_build_is_deterministic_and_claims_once(
    case_id: str,
    frozen_cases: dict[str, dict[str, Any]],
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    ir, first = canonical_cases[case_id]
    repeated = build_canonical_presentation(
        build_document_ir(deepcopy(frozen_cases[case_id]))
    )

    assert repeated.model_dump(mode="json") == first.model_dump(mode="json")

    blocks = _page_blocks(first)
    expected_primary_ids = [
        element_id
        for page in ir.pages
        for element_id in page.presentation_element_ids
    ]
    assert [block.primary_element_id for block in blocks] == (
        expected_primary_ids
    )
    assert len({block.id for block in blocks}) == len(blocks)

    claimed_element_ids: set[str] = set()
    for block in blocks:
        assert len(block.contributing_element_ids) == len(
            set(block.contributing_element_ids)
        )
        if _included(block):
            assert block.contributing_element_ids[0] == (
                block.primary_element_id
            )
        else:
            assert block.contributing_element_ids == []
            continue

        block_claims = set(block.contributing_element_ids)
        assert claimed_element_ids.isdisjoint(block_claims)
        claimed_element_ids.update(block_claims)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_flag_off_frozen_corpus_keeps_exact_legacy_serializer_output(
    case_id: str,
    frozen_cases: dict[str, dict[str, Any]],
) -> None:
    document = frozen_cases[case_id]

    assert "canonical_presentation" not in document
    assert to_markdown(document).encode("utf-8") == _frozen_markdown_bytes(
        case_id
    )


@pytest.mark.parametrize(
    "case_id",
    ("finance-10k", "settlement-agreement"),
)
def test_reviewed_positive_canonical_markdown_is_byte_equal_to_frozen(
    case_id: str,
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    _ir, presentation = canonical_cases[case_id]

    assert presentation.full.markdown.encode(
        "utf-8"
    ) == _frozen_markdown_bytes(case_id)


def test_finance_tables_retain_span_capable_html(
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    ir, presentation = canonical_cases["finance-10k"]
    blocks = _block_by_primary_id(presentation)
    table_elements = [
        element
        for element in ir.elements
        if element.presentation_role == "primary" and element.type == "table"
    ]

    assert len(table_elements) == 3
    assert any(
        'colspan="3"' in element.properties["legacy_item"]["html"]
        for element in table_elements
    )
    for element in table_elements:
        block = blocks[element.id]
        expected_html = element.properties["legacy_item"]["html"].strip()
        assert _included(block)
        assert block.markdown == expected_html
        assert block.markdown.startswith("<table>")
        assert not block.markdown.startswith("|")


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_full_body_header_and_footer_views_follow_declared_scopes(
    case_id: str,
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    _ir, presentation = canonical_cases[case_id]

    for page in presentation.pages:
        included = [block for block in page.blocks if _included(block)]
        expected_by_view = {
            "full": [block.id for block in included],
            "body": [
                block.id for block in included if block.scope == "body"
            ],
            "header": [
                block.id for block in included if block.scope == "header"
            ],
            "footer": [
                block.id for block in included if block.scope == "footer"
            ],
        }
        for view_name, expected_ids in expected_by_view.items():
            view = getattr(page, view_name)
            assert view.block_ids == expected_ids
            assert len(view.block_ids) == len(set(view.block_ids))
            if view.block_ids:
                assert view.markdown.endswith("\n")
                assert not view.markdown.endswith("\n\n")
                assert view.text.endswith("\n")
                assert not view.text.endswith("\n\n")
            else:
                assert view.markdown == ""
                assert view.text == ""

        assert set(page.full.block_ids) == (
            set(page.body.block_ids)
            | set(page.header.block_ids)
            | set(page.footer.block_ids)
        )
        assert set(page.body.block_ids).isdisjoint(page.header.block_ids)
        assert set(page.body.block_ids).isdisjoint(page.footer.block_ids)
        assert set(page.header.block_ids).isdisjoint(page.footer.block_ids)

    for view_name in ("full", "body", "header", "footer"):
        document_view = getattr(presentation, view_name)
        assert document_view.block_ids == [
            block_id
            for page in presentation.pages
            for block_id in getattr(page, view_name).block_ids
        ]


@pytest.mark.parametrize(
    ("case_id", "signal"),
    CONTROL_BODY_SIGNALS,
)
def test_reviewed_controls_preserve_retained_primary_body_identity(
    case_id: str,
    signal: str,
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    ir, presentation = canonical_cases[case_id]
    blocks = _block_by_primary_id(presentation)
    matching_primary_ids = [
        element.id
        for element in ir.elements
        if element.presentation_role == "primary"
        and element.type not in {"header", "footer"}
        and signal
        in str(element.properties.get("legacy_item", {}).get("value", ""))
    ]

    # Phase 0 did not retain a raw Docling graph. These controls deliberately
    # pin only identities and values that are present in normalized v1; they do
    # not infer cross-primary caption, logo, or chart equivalence.
    assert matching_primary_ids
    for element_id in matching_primary_ids:
        block = blocks[element_id]
        assert _included(block)
        assert block.scope == "body"
        assert block.id in presentation.body.block_ids
    assert signal in presentation.body.text


def test_equal_text_primary_elements_are_not_globally_deduplicated(
    canonical_cases: dict[str, tuple[DocumentIR, Any]],
) -> None:
    ir, presentation = canonical_cases["uber-earnings"]
    blocks = _block_by_primary_id(presentation)
    zero_text_ids = [
        element.id
        for element in ir.elements
        if element.presentation_role == "primary"
        and element.type == "text"
        and element.value == "0"
    ]

    assert len(zero_text_ids) == 2
    assert len(set(zero_text_ids)) == 2
    assert [blocks[element_id].text for element_id in zero_text_ids] == [
        "0",
        "0",
    ]
    assert all(_included(blocks[element_id]) for element_id in zero_text_ids)
    assert all(
        blocks[element_id].id in presentation.body.block_ids
        for element_id in zero_text_ids
    )


def _health_table_block(document: dict[str, Any]) -> tuple[DocumentIR, Any, Any]:
    ir = build_document_ir(document)
    presentation = build_canonical_presentation(ir)
    table = next(
        element
        for element in ir.elements
        if element.presentation_role == "primary" and element.type == "table"
    )
    return ir, presentation, _block_by_primary_id(presentation)[table.id]


def test_health_diagnosed_overlapping_table_uses_only_the_narrow_rule(
    frozen_cases: dict[str, dict[str, Any]],
) -> None:
    diagnosed = deepcopy(frozen_cases["health-report"])
    table_item = next(
        item
        for page in diagnosed["pages"]
        for item in page["items"]
        if item["type"] == "table"
    )
    assert "contains_empty_visual_rows" in table_item["parse_concerns"]

    diagnosed_ir, diagnosed_presentation, diagnosed_block = _health_table_block(
        diagnosed
    )
    suppressor = next(
        element
        for element in diagnosed_ir.elements
        if element.id == diagnosed_block.suppressed_by_element_id
    )
    assert diagnosed_block.omission_reason == "overlapping_visual_table"
    assert suppressor.type == "chart"
    assert suppressor.reading_order < next(
        element.reading_order
        for element in diagnosed_ir.elements
        if element.id == diagnosed_block.primary_element_id
    )
    assert diagnosed_block.id not in diagnosed_presentation.full.block_ids

    not_diagnosed = deepcopy(diagnosed)
    plain_table = next(
        item
        for page in not_diagnosed["pages"]
        for item in page["items"]
        if item["type"] == "table"
    )
    plain_table["parse_concerns"] = []
    _ir, plain_presentation, plain_block = _health_table_block(not_diagnosed)
    assert plain_block.omission_reason is None
    assert plain_block.id in plain_presentation.full.block_ids

    diagnosed_without_overlap = deepcopy(diagnosed)
    moved_table = next(
        item
        for page in diagnosed_without_overlap["pages"]
        for item in page["items"]
        if item["type"] == "table"
    )
    moved_table["bbox"] = {
        **moved_table["bbox"],
        "x": 0.0,
        "y": 0.0,
        "width": 10.0,
        "height": 10.0,
        "w": 10.0,
        "h": 10.0,
    }
    _ir, moved_presentation, moved_block = _health_table_block(
        diagnosed_without_overlap
    )
    assert moved_block.omission_reason is None
    assert moved_block.id in moved_presentation.full.block_ids
