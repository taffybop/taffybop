"""Real-corpus production regressions for P03-US08 running regions."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from app.services import running_regions
from app.services.ir import DocumentIR, build_document_ir
from tests.fixtures.phase_03.running_regions.contract import (
    source_report_semantic_payload,
    strict_json_bytes,
)
from tests.fixtures.phase_03.running_regions.oracle import (
    ACCEPTED_RUNNING_REGIONS,
    BOUNDARY_METHOD_PROOFS,
    CANONICAL_PAGE_MEMBERSHIP,
    FROZEN_AGGREGATES,
    MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID,
    PAGE_IDENTITY_DESCRIPTORS,
    PREDECESSOR_OUTPUT_ROOT,
    RUNNING_REGION_DESCRIPTORS,
    SOURCE_IDENTITIES,
    SOURCE_REPORTS,
    SOURCE_VISIBILITY_CONTROLS,
)

WORKSPACE = Path(__file__).resolve().parents[3]
CASE_IDS = tuple(SOURCE_IDENTITIES)


@cache
def _source(case_id: str) -> bytes:
    return (WORKSPACE / SOURCE_IDENTITIES[case_id]["path"]).read_bytes()


@cache
def _predecessor(case_id: str) -> tuple[dict[str, Any], DocumentIR]:
    public = json.loads(
        (WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case_id / "our-output.json").read_text()
    )
    return public, build_document_ir(deepcopy(public))


@cache
def _source_envelope(case_id: str) -> Mapping[str, Any]:
    predecessor, ir_document = _predecessor(case_id)
    envelope = running_regions.extract_running_region_source_projection(
        _source(case_id),
        predecessor,
        ir_document,
    )
    assert isinstance(envelope, Mapping)
    assert set(envelope) == {
        "source_report",
        "extracted_plans",
        "comparison_ledger",
        "method_proofs",
    }
    return envelope


@cache
def _projected(
    case_id: str,
) -> tuple[dict[str, Any], DocumentIR, dict[str, Any]]:
    predecessor, predecessor_ir = _predecessor(case_id)
    predecessor_public_bytes = strict_json_bytes(predecessor)
    predecessor_ir_bytes = strict_json_bytes(
        predecessor_ir.model_dump(mode="json", exclude_none=True)
    )
    authority = running_regions.prepare_source_projection_authority(
        {
            "public": predecessor,
            "ir": predecessor_ir.model_dump(mode="json", exclude_none=True),
        },
        _source(case_id),
    )
    metrics: dict[str, Any] = {}
    public, ir_document = running_regions.project_running_regions(
        predecessor,
        predecessor_ir,
        authority,
        metrics=metrics,
    )
    assert ir_document.validate_graph() is ir_document
    assert strict_json_bytes(predecessor) == predecessor_public_bytes
    assert (
        strict_json_bytes(predecessor_ir.model_dump(mode="json", exclude_none=True))
        == predecessor_ir_bytes
    )
    return public, ir_document, metrics


def _strict_equal(actual: Any, expected: Any) -> None:
    assert strict_json_bytes(actual) == strict_json_bytes(expected)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_real_source_report_matches_every_sealed_page_and_candidate(
    case_id: str,
) -> None:
    actual = _source_envelope(case_id)["source_report"]
    expected = SOURCE_REPORTS[case_id]
    _strict_equal(
        source_report_semantic_payload(actual),
        source_report_semantic_payload(expected),
    )


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_real_projection_matches_identity_region_and_canonical_oracles(
    case_id: str,
) -> None:
    predecessor, _predecessor_ir = _predecessor(case_id)
    public, ir_document, metrics = _projected(case_id)
    assert metrics["status"] == "projected"
    summary = public["processing"]["running_regions"]
    assert set(summary) == {
        "policy_id",
        "status",
        "reason",
        "source_page_count",
        "identity_count",
        "detected_label_count",
        "embedded_label_count",
        "legacy_fallback_count",
        "candidate_count",
        "comparison_count",
        "running_region_count",
        "header_count",
        "footer_count",
        "top_navigation_count",
        "bottom_navigation_count",
        "concern_count",
        "extraction_ms",
        "projection_ms",
        "total_ms",
    }
    assert summary["status"] == "projected"
    assert summary["reason"] is None
    assert summary["concern_count"] == 0
    assert public.get("running_region_concerns", []) == []
    assert 0 <= summary["extraction_ms"] <= 2_000
    assert 0 <= summary["projection_ms"] <= 2_000
    assert summary["total_ms"] == round(
        summary["extraction_ms"] + summary["projection_ms"],
        3,
    )
    for field, value in summary.items():
        if field != "policy_id":
            assert metrics[field] == value
    source_envelope = _source_envelope(case_id)
    assert (
        summary["source_page_count"]
        == source_envelope["source_report"]["counts"]["page_count"]
    )
    assert (
        summary["candidate_count"]
        == source_envelope["source_report"]["counts"]["boundary_candidate_count"]
    )
    assert summary["comparison_count"] == sum(
        entry["comparison_count"] for entry in source_envelope["comparison_ledger"]
    )

    expected_identities = {
        page_index: descriptor
        for (candidate_case, page_index), descriptor in (
            PAGE_IDENTITY_DESCRIPTORS.items()
        )
        if candidate_case == case_id
    }
    public_pages = {page["page_index"]: page for page in public["pages"]}
    predecessor_pages = {page["page_index"]: page for page in predecessor["pages"]}
    canonical_pages = {
        page["page_index"]: page for page in public["canonical_presentation"]["pages"]
    }
    ir_pages = {page.page_index: page for page in ir_document.pages}
    assert set(public_pages) == set(expected_identities)
    for page_index, expected_identity in expected_identities.items():
        page = public_pages[page_index]
        predecessor_page = predecessor_pages[page_index]
        for field in ("page_index", "page_number", "page_label"):
            assert page[field] == predecessor_page[field]
        _strict_equal(page["page_identity"], expected_identity)
        _strict_equal(canonical_pages[page_index]["page_identity"], expected_identity)
        _strict_equal(
            ir_pages[page_index].page_identity.model_dump(mode="json"),
            expected_identity,
        )

        membership = CANONICAL_PAGE_MEMBERSHIP[(case_id, page_index)]
        for view in ("body", "header", "footer", "full"):
            assert canonical_pages[page_index][view]["block_ids"] == list(
                membership[f"{view}_block_ids"]
            )

    actual_descriptors = {
        item["running_region"]["id"]: item["running_region"]
        for page in public["pages"]
        for item in page["items"]
        if item.get("layout_running_region_projected") is True
    }
    expected_descriptors = {
        descriptor_id: descriptor
        for descriptor_id, descriptor in RUNNING_REGION_DESCRIPTORS.items()
        if any(
            region["case_id"] == case_id and region["region_id"] == descriptor_id
            for region in ACCEPTED_RUNNING_REGIONS
        )
    }
    assert set(actual_descriptors) == set(expected_descriptors)
    for descriptor_id, expected in expected_descriptors.items():
        _strict_equal(actual_descriptors[descriptor_id], expected)

    ir_descriptors = {
        element.running_region.id: element.running_region.model_dump(mode="json")
        for element in ir_document.elements
        if element.running_region is not None
    }
    assert set(ir_descriptors) == set(expected_descriptors)
    for descriptor_id, expected in expected_descriptors.items():
        _strict_equal(ir_descriptors[descriptor_id], expected)


def test_finance_retyped_company_headers_drop_only_serializer_markers() -> None:
    public, ir_document, _metrics = _projected("finance-10k")
    company_items = [
        item
        for page in public["pages"]
        for item in page["items"]
        if item.get("value") == "Apple Inc."
    ]

    assert len(company_items) == 3
    assert all(item["type"] == "header" for item in company_items)
    assert company_items[0]["md"] == "Apple Inc."
    assert [item["md"] for item in company_items[1:]] == [
        "# Apple Inc.",
        "# Apple Inc.",
    ]
    canonical_blocks = [
        block
        for page in public["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block.get("primary_element_id")
        in {
            item["running_region"]["source_element_id"]
            for item in company_items
        }
    ]
    assert len(canonical_blocks) == 3
    assert all(block["scope"] == "header" for block in canonical_blocks)
    assert all(block["markdown"] == "Apple Inc." for block in canonical_blocks)

    statement_headings = [
        item
        for page in public["pages"]
        for item in page["items"]
        if isinstance(item.get("value"), str)
        and item["value"].startswith("CONSOLIDATED STATEMENTS")
    ]
    assert statement_headings
    assert all(item["type"] == "heading" for item in statement_headings)
    assert all(item["md"].startswith("# ") for item in statement_headings)

    predecessor_public, predecessor_ir = _predecessor("finance-10k")
    restored_public, restored_ir = running_regions.strip_running_regions(
        public,
        ir_document,
    )
    _strict_equal(restored_public, predecessor_public)
    _strict_equal(
        restored_ir.model_dump(mode="json", exclude_none=True),
        predecessor_ir.model_dump(mode="json", exclude_none=True),
    )


def test_real_projection_meets_the_complete_reviewed_denominator() -> None:
    projected = [_projected(case_id)[0] for case_id in CASE_IDS]
    pages = [page for document in projected for page in document["pages"]]
    canonical_pages = [
        page
        for document in projected
        for page in document["canonical_presentation"]["pages"]
    ]
    regions = [
        item["running_region"]
        for page in pages
        for item in page["items"]
        if item.get("layout_running_region_projected") is True
    ]
    identities = [page["page_identity"] for page in pages]
    role_counts = Counter(region["role"] for region in regions)
    method_counts = Counter(region["source_method"] for region in regions)
    region_block_ids = {region["canonical_block_id"] for region in regions}
    full_membership = Counter(
        block_id
        for page in canonical_pages
        for block_id in page["full"]["block_ids"]
        if block_id in region_block_ids
    )

    assert len(pages) == FROZEN_AGGREGATES["physical_page_count"] == 30
    assert (
        sum(identity["detected_printed_label"] is not None for identity in identities)
        == FROZEN_AGGREGATES["detected_printed_label_positive_count"]
        == 27
    )
    assert len(regions) == FROZEN_AGGREGATES["accepted_running_region_count"] == 47
    assert role_counts == {
        "header": 16,
        "footer": 30,
        "navigation_bottom": 1,
    }
    assert method_counts == {
        "trusted_layout_role": 41,
        "cross_page_repetition": 2,
        "extracted_source_contribution": 1,
        "boundary_navigation": 1,
        "effective_boundary_cluster": 1,
        "printed_label_boundary": 1,
    }
    assert (
        sum(region["repetition_group_id"] is not None for region in regions)
        == FROZEN_AGGREGATES["repeated_region_count"]
        == 28
    )
    assert len(region_block_ids) == 47
    assert full_membership == Counter({block_id: 1 for block_id in region_block_ids})
    assert (
        sum(len(page["body"]["block_ids"]) for page in canonical_pages)
        == FROZEN_AGGREGATES["canonical_body_block_count"]
        == 223
    )
    assert (
        sum(len(page["header"]["block_ids"]) for page in canonical_pages)
        == FROZEN_AGGREGATES["canonical_header_block_count"]
        == 16
    )
    assert (
        sum(len(page["footer"]["block_ids"]) for page in canonical_pages)
        == FROZEN_AGGREGATES["canonical_footer_block_count"]
        == 31
    )
    assert (
        sum(len(page["full"]["block_ids"]) for page in canonical_pages)
        == FROZEN_AGGREGATES["canonical_full_block_count"]
        == 270
    )
    for page in canonical_pages:
        body_ids = page["body"]["block_ids"]
        full_ids = page["full"]["block_ids"]
        page_region_ids = region_block_ids.intersection(full_ids)
        assert region_block_ids.isdisjoint(body_ids)
        assert all(full_ids.count(block_id) == 1 for block_id in page_region_ids)


def test_real_source_reports_meet_every_reviewed_source_denominator() -> None:
    reports = [_source_envelope(case_id)["source_report"] for case_id in CASE_IDS]
    report_pages = [page for report in reports for page in report["pages"]]
    assert len(reports) == FROZEN_AGGREGATES["source_report_count"] == 15
    assert len(report_pages) == FROZEN_AGGREGATES["source_report_page_count"] == 30
    assert (
        sum(page["source_character_count"] for page in report_pages)
        == FROZEN_AGGREGATES["source_report_character_count"]
        == 52_861
    )
    assert (
        sum(page["source_word_count"] for page in report_pages)
        == FROZEN_AGGREGATES["source_report_word_count"]
        == 8_080
    )
    assert (
        sum(len(page["label_candidates"]) for page in report_pages)
        == FROZEN_AGGREGATES["source_report_label_candidate_count"]
        == 27
    )
    assert (
        sum(len(page["boundary_candidates"]) for page in report_pages)
        == FROZEN_AGGREGATES["source_report_boundary_candidate_count"]
        == 47
    )


@pytest.mark.parametrize(
    "control",
    SOURCE_VISIBILITY_CONTROLS,
    ids=lambda value: (
        f"{value['case_id']}-page-{value['physical_page']}-"
        f"{'visible' if value['visible'] else 'hidden'}"
    ),
)
def test_production_rendered_visibility_matches_every_sealed_control(
    control: Mapping[str, Any],
) -> None:
    arguments = {
        "physical_page_index": control["physical_page"],
        "candidate_visible_text": control["text_layer_text"],
        "candidate_bbox": control["bbox"],
        "non_stroking_fills": (control["raw_non_stroking_fill"],),
    }
    if control["visible"]:
        assert (
            running_regions.validate_rendered_label_visibility(
                _source(str(control["case_id"])),
                **arguments,
            )
            is None
        )
    else:
        with pytest.raises(
            running_regions.RunningRegionError,
            match="render/fill contrast",
        ):
            running_regions.validate_rendered_label_visibility(
                _source(str(control["case_id"])),
                **arguments,
            )


def test_real_private_authority_ledgers_match_reviewed_proofs_and_plans() -> None:
    actual_proofs: dict[str, Any] = {}
    expected_proofs: dict[str, Any] = {}
    total_comparisons = 0
    for case_id in CASE_IDS:
        envelope = _source_envelope(case_id)
        report = SOURCE_REPORTS[case_id]
        expected_candidate_ids = {
            candidate["id"]
            for page in report["pages"]
            for candidate in page["boundary_candidates"]
        }
        case_expected_proofs = {
            candidate_id: proof
            for candidate_id, proof in BOUNDARY_METHOD_PROOFS.items()
            if candidate_id in expected_candidate_ids
        }
        _strict_equal(envelope["method_proofs"], case_expected_proofs)
        assert actual_proofs.keys().isdisjoint(envelope["method_proofs"])
        actual_proofs.update(envelope["method_proofs"])
        expected_proofs.update(case_expected_proofs)

        expected_plans = [
            region["extraction_plan"]
            for region in ACCEPTED_RUNNING_REGIONS
            if region["case_id"] == case_id
            and region.get("extraction_plan") is not None
        ]
        _strict_equal(envelope["extracted_plans"], expected_plans)

        ledger = envelope["comparison_ledger"]
        assert [entry["page_index"] for entry in ledger] == [
            page["page_index"] for page in report["pages"]
        ]
        assert all(
            set(entry) == {"page_index", "comparison_count"}
            and isinstance(entry["comparison_count"], int)
            and not isinstance(entry["comparison_count"], bool)
            and 1 <= entry["comparison_count"] <= 4_096
            for entry in ledger
        )
        total_comparisons += sum(entry["comparison_count"] for entry in ledger)

    _strict_equal(actual_proofs, expected_proofs)
    _strict_equal(actual_proofs, BOUNDARY_METHOD_PROOFS)
    assert len(actual_proofs) == FROZEN_AGGREGATES["boundary_method_proof_count"] == 4
    assert total_comparisons <= 65_536


def test_production_descriptor_derivation_matches_all_47_reviewed_regions() -> None:
    expected_by_source = {
        (
            region["case_id"],
            region["physical_page"],
            region["source_public_item_id"],
            region["source_method"],
            region["bbox_id"],
        ): RUNNING_REGION_DESCRIPTORS[region["region_id"]]
        for region in ACCEPTED_RUNNING_REGIONS
    }
    assert len(expected_by_source) == 47
    observed = 0
    for case_id in CASE_IDS:
        predecessor, ir_document = _predecessor(case_id)
        envelope = _source_envelope(case_id)
        source_sha256 = SOURCE_IDENTITIES[case_id]["sha256"]
        repetitions = running_regions._repetition_memberships(
            envelope["source_report"], source_sha256
        )
        ir_pages = {page.page_index: page for page in ir_document.pages}
        for report_page in envelope["source_report"]["pages"]:
            page_index = report_page["page_index"]
            for candidate in report_page["boundary_candidates"]:
                expected = expected_by_source[
                    (
                        case_id,
                        page_index,
                        candidate["public_item_id"],
                        candidate["source_method"],
                        candidate["bbox_id"],
                    )
                ]
                owner = running_regions._resolve_path(
                    predecessor,
                    candidate["public_path"],
                )
                actual = running_regions._descriptor_for_candidate(
                    candidate=candidate,
                    owner=owner,
                    page_id=ir_pages[page_index].id,
                    page_index=page_index,
                    source_sha256=source_sha256,
                    repetitions=repetitions,
                ).model_dump(mode="json")
                _strict_equal(actual, expected)
                observed += 1
    assert observed == 47


def test_uber_hidden_glyph_stays_null_while_pages_two_and_three_are_controls() -> None:
    public, _ir, _metrics = _projected("uber-earnings")
    identities = [page["page_identity"] for page in public["pages"]]
    assert [value["detected_printed_label"] for value in identities] == [
        None,
        "5",
        "6",
    ]
    assert identities[0]["display_source"] == "legacy_display_fallback"
    assert identities[0]["display_label"] == "1"
    assert all(
        item.get("id") != "p1-i4"
        or item.get("layout_running_region_projected") is not True
        for item in public["pages"][0]["items"]
    )


def test_manufacturing_extracted_owner_is_unchanged_and_strip_is_exact_inverse() -> (
    None
):
    predecessor, predecessor_ir = _predecessor("manufacturing-report")
    public, ir_document, _metrics = _projected("manufacturing-report")
    predecessor_owner = predecessor["pages"][1]["items"][0]
    projected_owner = public["pages"][1]["items"][0]
    _strict_equal(projected_owner, predecessor_owner)
    synthetic = [
        item
        for item in public["pages"][1]["items"]
        if item.get("id") == MANUFACTURING_P2_SYNTHETIC_PUBLIC_ITEM_ID
    ]
    assert len(synthetic) == 1
    assert (
        synthetic[0]["running_region"]["source_method"]
        == "extracted_source_contribution"
    )

    projected_public_bytes = strict_json_bytes(public)
    projected_ir_bytes = strict_json_bytes(ir_document.model_dump(mode="json"))
    stripped_public, stripped_ir = running_regions.strip_running_regions(
        public,
        ir_document,
    )
    assert strict_json_bytes(public) == projected_public_bytes
    assert strict_json_bytes(ir_document.model_dump(mode="json")) == (
        projected_ir_bytes
    )
    _strict_equal(stripped_public, predecessor)
    _strict_equal(
        stripped_ir.model_dump(mode="json", exclude_none=True),
        predecessor_ir.model_dump(mode="json", exclude_none=True),
    )
