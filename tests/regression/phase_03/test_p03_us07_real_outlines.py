"""Real-corpus regression coverage for P03-US07 outline structure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.ir import build_document_ir
from app.services.outline_structure import (
    extract_outline_evidence,
    project_outline_structure,
)
from app.services.pipeline import parse_document
from app.services.presentation import build_canonical_presentation
from tests.benchmarks.form_semantics_metrics import _public_form_summary
from tests.fixtures.phase_03.outline_structure.contract import (
    POLICY_ID,
    validate_public_sidecar,
)
from tests.fixtures.phase_03.outline_structure.oracle import (
    CANONICAL_EXPECTATIONS,
    COMPONENT_GROUPS,
    REVIEWED_COUNTS,
    SETTLEMENT_GROUP,
    SOURCE_IDENTITIES,
)
from tests.fixtures.phase_03.outline_structure.synthetic import (
    SYNTHETIC_FIXTURES,
    build_synthetic_fixture,
)

WORKSPACE = Path(__file__).resolve().parents[3]
CORPUS = WORKSPACE / "benchmark-expertmodeldata"
FINANCE_IDENTITY = {
    "path": "benchmark-expertmodeldata/finance-10k.pdf",
    "size_bytes": 87_105,
    "sha256": "e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086",
}
PUBLIC_OUTLINE_KEYS = frozenset(
    {
        "layout_outline_structure_projected",
        "outline_policy",
        "outline_group",
        "outline_items",
        "outline_continuations",
    }
)
TIMING_PATHS_REMOVED = (
    "processing.duration_ms",
    "processing.form_semantics.extraction_ms",
    "processing.form_semantics.projection_ms",
    "processing.form_semantics.total_ms",
    "processing.outline_structure.extraction_ms",
    "processing.outline_structure.projection_ms",
    "processing.outline_structure.total_ms",
)


def _settings(enabled: bool) -> Settings:
    """Keep the accepted P03-US01-US06 predecessor enabled."""

    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=True,
        layout_outline_structure_enabled=enabled,
    )


def _predecessor_settings() -> Settings:
    """Return the configured predecessor without passing a US07 argument."""

    return Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        layout_table_captions_enabled=True,
        layout_visual_relationships_enabled=True,
        layout_source_notes_enabled=True,
        layout_relationship_order_enabled=True,
        layout_text_run_semantics_enabled=True,
        layout_forms_enabled=True,
    )


@cache
def _source(case: str) -> bytes:
    expected = SOURCE_IDENTITIES.get(case, FINANCE_IDENTITY)
    source = (WORKSPACE / str(expected["path"])).read_bytes()
    assert len(source) == expected["size_bytes"]
    assert hashlib.sha256(source).hexdigest() == expected["sha256"]
    return source


@cache
def _parse(case: str, enabled: bool) -> dict[str, Any]:
    return parse_document(
        _source(case),
        f"{case}.pdf",
        _settings(enabled),
    ).model_dump(mode="json", exclude_none=True)


@cache
def _predecessor(case: str) -> dict[str, Any]:
    return parse_document(
        _source(case),
        f"{case}.pdf",
        _predecessor_settings(),
    ).model_dump(mode="json", exclude_none=True)


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(payload))
    processing = stable.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
        for summary_name in ("form_semantics", "outline_structure"):
            summary = processing.get(summary_name)
            if isinstance(summary, dict):
                for key in ("extraction_ms", "projection_ms", "total_ms"):
                    summary.pop(key, None)
    return stable


def _pages(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    pages = payload.get("pages")
    assert isinstance(pages, list)
    return pages


def _page(payload: Mapping[str, Any], page_index: int) -> Mapping[str, Any]:
    matches = [page for page in _pages(payload) if page.get("page_index") == page_index]
    assert len(matches) == 1
    return matches[0]


def _item(
    payload: Mapping[str, Any],
    page_index: int,
    item_id: str,
) -> Mapping[str, Any]:
    items = _page(payload, page_index).get("items")
    assert isinstance(items, list)
    matches = [item for item in items if item.get("id") == item_id]
    assert len(matches) == 1
    return matches[0]


def _canonical_block(
    payload: Mapping[str, Any],
    block_id: str,
) -> Mapping[str, Any]:
    canonical = payload.get("canonical_presentation")
    assert isinstance(canonical, Mapping)
    matches = [
        block
        for page in canonical.get("pages", [])
        if isinstance(page, Mapping)
        for block in page.get("blocks", [])
        if isinstance(block, Mapping) and block.get("id") == block_id
    ]
    assert len(matches) == 1
    return matches[0]


def _outline_anchors(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        item
        for page in _pages(payload)
        for item in page.get("items", [])
        if isinstance(item, Mapping)
        and item.get("layout_outline_structure_projected") is True
    ]


def _assert_group_matches_oracle(
    payload: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    anchor = _item(
        payload,
        int(expected["page_index"]),
        str(expected["anchor_public_item_id"]),
    )
    group = anchor["outline_group"]
    items = anchor["outline_items"]
    continuations = anchor["outline_continuations"]
    assert isinstance(group, Mapping)
    assert isinstance(items, list)
    assert isinstance(continuations, list)
    assert anchor["outline_policy"] == POLICY_ID
    assert group["id"] == expected["id"]
    assert group["element_id"] == expected["element_id"]
    assert group["sequence_kind"] == expected["sequence_kind"]
    assert group["marker_style"] == expected["marker_style"]
    assert group["member_item_ids"] == list(expected["member_item_ids"])
    assert group["member_element_ids"] == list(expected["member_element_ids"])
    assert group["continuation_ids"] == list(expected["continuation_ids"])
    assert group["continuation_element_ids"] == list(
        expected["continuation_element_ids"]
    )
    assert group["relationship_ids"] == list(expected["relationship_ids"])
    assert group["relationship_cardinality"] == expected["relationship_cardinality"]

    expected_items = {node["id"]: node for node in expected["nodes"]}
    assert {item["id"] for item in items} == set(expected_items)
    for item in items:
        oracle_item = expected_items[item["id"]]
        assert item["element_id"] == oracle_item["element_id"]
        assert item["source_public_item_id"] == oracle_item["source_public_item_id"]
        assert item["source_public_path"] == list(oracle_item["source_public_path"])
        assert item["raw_marker"] == oracle_item["raw_marker"]
        assert item["marker_bbox"] == oracle_item["marker_bbox"]
        assert item["marker_ownership"] == oracle_item["marker_ownership"]
        assert item["marker_separator"] == oracle_item["marker_separator"]
        assert item["body_text"] == oracle_item["body_text"]
        assert item["level"] == oracle_item["level"]
        assert item["ordinal"] == oracle_item["ordinal"]
        assert item["parent_id"] == oracle_item["parent_id"]
        assert item["relationship_ids"] == list(oracle_item["relationship_ids"])

    expectation = CANONICAL_EXPECTATIONS[str(expected["oracle_id"])]
    block = _canonical_block(payload, str(expectation["block_id"]))
    validate_public_sidecar(anchor, block)
    assert block["primary_element_id"] == expectation["primary_element_id"]
    assert block["contributing_element_ids"] == list(
        expectation["contributing_element_ids"]
    )
    assert block["relationship_ids"] == list(expectation["relationship_ids"])
    assert (
        hashlib.sha256(str(block["markdown"]).encode()).hexdigest()
        == (expectation["markdown_sha256"])
    )
    assert (
        hashlib.sha256(str(block["text"]).encode()).hexdigest()
        == (expectation["text_sha256"])
    )


def test_target_source_custody_is_exact() -> None:
    for case in SOURCE_IDENTITIES:
        _source(case)


@pytest.mark.parametrize("case", tuple(SOURCE_IDENTITIES))
def test_flag_off_is_the_exact_configured_predecessor(case: str) -> None:
    disabled = _parse(case, False)
    predecessor = _predecessor(case)

    assert _semantic_payload(disabled) == _semantic_payload(predecessor)
    for value in _walk(disabled):
        if isinstance(value, Mapping):
            assert PUBLIC_OUTLINE_KEYS.isdisjoint(value)
    serialized = json.dumps(disabled, ensure_ascii=False, sort_keys=True)
    assert POLICY_ID not in serialized
    assert "outline_structure" not in disabled.get("processing", {})
    assert TIMING_PATHS_REMOVED == (
        "processing.duration_ms",
        "processing.form_semantics.extraction_ms",
        "processing.form_semantics.projection_ms",
        "processing.form_semantics.total_ms",
        "processing.outline_structure.extraction_ms",
        "processing.outline_structure.projection_ms",
        "processing.outline_structure.total_ms",
    )


def test_component_real_output_matches_both_frozen_groups() -> None:
    payload = _parse("component-datasheet", True)
    assert len(_outline_anchors(payload)) == 2
    for group in COMPONENT_GROUPS:
        _assert_group_matches_oracle(payload, group)

    expected = REVIEWED_COUNTS["component-datasheet"]
    anchors = _outline_anchors(payload)
    assert (
        sum(len(anchor["outline_items"]) for anchor in anchors)
        == expected["node_count"]
    )
    assert (
        sum(len(anchor["outline_group"]["relationship_ids"]) for anchor in anchors)
        == expected["total_relationship_count"]
    )


def test_missing_component_marker_rolls_back_page_and_preserves_canonical_bytes() -> (
    None
):
    source = _source("component-datasheet")
    parsed = parse_document(
        source,
        "component-datasheet.pdf",
        _settings(False),
    )
    predecessor = build_document_ir(parsed.model_dump(mode="json", exclude_none=True))
    predecessor_canonical_bytes = json.dumps(
        build_canonical_presentation(predecessor).model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    report = extract_outline_evidence(source, max_pages=100)
    assert report.status == "available"
    assert len(report.pages) == 1
    [source_page] = report.pages
    assert (
        len(source_page.markers) == REVIEWED_COUNTS["component-datasheet"]["node_count"]
    )
    partial_page = replace(source_page, markers=source_page.markers[1:])
    partial_report = replace(
        report,
        pages=(partial_page,),
        counts=replace(
            report.counts,
            marker_candidates=report.counts.marker_candidates - 1,
        ),
    )

    projection_metrics: dict[str, Any] = {}
    projected = project_outline_structure(
        predecessor,
        partial_report,
        metrics=projection_metrics,
    )
    projected_canonical_bytes = json.dumps(
        build_canonical_presentation(projected).model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert projection_metrics["status"] == "no_candidates"
    assert not any(element.outline_group is not None for element in projected.elements)
    assert not any(element.outline_item is not None for element in projected.elements)
    assert projected.pages == predecessor.pages
    assert projected.elements == predecessor.elements
    assert projected.bboxes == predecessor.bboxes
    assert projected.evidence == predecessor.evidence
    assert projected.relationships == predecessor.relationships
    assert projected_canonical_bytes == predecessor_canonical_bytes
    assert any(
        concern.code == "outline_projection_failed_closed"
        and concern.source_ref == "page:1"
        for concern in projected.concerns
    )


def test_settlement_real_output_matches_clause_and_table_oracle() -> None:
    payload = _parse("settlement-agreement", True)
    assert len(_outline_anchors(payload)) == 1
    _assert_group_matches_oracle(payload, SETTLEMENT_GROUP)

    anchor = _outline_anchors(payload)[0]
    [continuation] = anchor["outline_continuations"]
    [expected_continuation] = SETTLEMENT_GROUP["continuations"]
    assert continuation["id"] == expected_continuation["id"]
    assert continuation["element_id"] == expected_continuation["element_id"]
    assert continuation["target_node_id"] == expected_continuation["target_node_id"]
    table = _item(
        payload,
        int(SETTLEMENT_GROUP["page_index"]),
        str(expected_continuation["source_public_item_id"]),
    )
    assert table["type"] == "table"
    assert isinstance(table.get("rows"), list)
    assert table in _page(payload, 1)["items"]


def test_component_forms_remain_owned_and_disjoint() -> None:
    payload = _parse("component-datasheet", True)
    anchors = _outline_anchors(payload)
    outline_elements = {
        element_id
        for anchor in anchors
        for element_id in anchor["outline_group"]["canonical_contributor_element_ids"]
    }
    form_elements: set[str] = set()
    form_relationships: set[str] = set()
    for value in _walk(payload):
        if not isinstance(value, Mapping):
            continue
        group = value.get("form_group")
        if isinstance(group, Mapping):
            form_elements.update(
                str(element_id)
                for element_id in group.get("contributor_element_ids", ())
            )
            form_relationships.update(
                str(relationship["id"])
                for relationship in value.get("relationships", ())
                if isinstance(relationship, Mapping)
                and relationship.get("type") in {"contains", "key_of", "value_of"}
                and relationship.get("canonical_inert") is True
            )
    summary = _public_form_summary(payload)
    assert summary["group_count"] == 3
    assert summary["key_value_pair_count"] == 16
    assert len(form_relationships) == 80
    assert outline_elements.isdisjoint(form_elements)


def test_finance_real_corpus_control_projects_no_outline() -> None:
    payload = _parse("finance-10k", True)
    assert _outline_anchors(payload) == []
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert '"outline_group"' not in serialized
    assert '"outline_items"' not in serialized


@pytest.mark.parametrize(
    ("fixture_id", "expected_markers", "expected_style"),
    [
        (
            "synthetic:p03-us07:parenthesized-alpha-v1",
            ("(a)", "(b)", "(c)"),
            "lower_alpha",
        ),
        (
            "synthetic:p03-us07:marker-injection-v1",
            ("-", "-"),
            "bullet",
        ),
    ],
)
def test_projection_negative_controls_retain_exact_source_marker_evidence(
    fixture_id: str,
    expected_markers: tuple[str, ...],
    expected_style: str,
) -> None:
    fixture = build_synthetic_fixture(fixture_id)
    source = fixture["payload"]
    assert isinstance(source, bytes)
    report = extract_outline_evidence(source)
    markers = [marker for page in report.pages for marker in page.markers]

    assert report.status == "available"
    assert tuple(marker.raw_marker for marker in markers) == expected_markers
    assert {marker.marker_style for marker in markers} == {expected_style}
    assert tuple(marker.ordinal for marker in markers) == tuple(
        range(1, len(markers) + 1)
    )


@pytest.mark.parametrize(
    ("fixture_id", "expects_outline"),
    [
        (
            definition.fixture_id,
            definition.fixture_id.rsplit(":", 1)[-1]
            in {
                "nested-unordered-v1",
                "ordered-numeric-v1",
                "legal-table-interruption-v1",
            },
        )
        for definition in SYNTHETIC_FIXTURES
        if definition.kind == "pdf"
    ],
)
def test_synthetic_pdf_control_partition(
    fixture_id: str,
    expects_outline: bool,
) -> None:
    fixture = build_synthetic_fixture(fixture_id)
    source = fixture["payload"]
    assert isinstance(source, bytes)
    payload = parse_document(
        source,
        f"{fixture_id.rsplit(':', 1)[-1]}.pdf",
        _settings(True),
    ).model_dump(mode="json", exclude_none=True)
    anchors = _outline_anchors(payload)
    assert bool(anchors) is expects_outline
    if fixture_id.endswith("marker-injection-v1"):
        canonical = payload.get("canonical_presentation")
        assert isinstance(canonical, Mapping)
        outline_markdown = "\n".join(
            str(block.get("markdown") or "")
            for page in canonical.get("pages", ())
            if isinstance(page, Mapping)
            for block in page.get("blocks", ())
            if isinstance(block, Mapping)
            and (
                block.get("primary_element_type") == "outline_group"
                or "data-outline-policy" in str(block.get("markdown") or "")
            )
        )
        assert outline_markdown == ""
        assert "<script" not in outline_markdown.casefold()
        assert "javascript:" not in outline_markdown.casefold()
