"""P03-US08 source-truth, readiness-contract, and fixture acceptance tests."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pdfplumber
import pypdfium2 as pdfium
import pytest

from tests.fixtures.phase_03.running_regions.contract import (
    COORDINATE_SYSTEM_ID,
    DISPLAY_SOURCES,
    POLICY_ID,
    RESOURCE_LIMITS,
    SOURCE_METHODS,
    ReadinessContractError,
    build_extracted_contribution_plan,
    combine_terminal_processing_summaries,
    contract_self_check,
    extracted_plan_json_bytes,
    label_candidate_id,
    normalize_detected_label,
    normalize_embedded_label,
    predecessor_item_sha256,
    stable_id,
    strip_complete_running_region_sidecars,
    validate_boundary_method_proof,
    validate_extracted_plan_ledger,
    validate_ir_bindings,
    validate_page_identity,
    validate_processing_summary,
    validate_projected_document,
    validate_rendered_label_visibility,
    validate_source_report,
)
from tests.fixtures.phase_03.running_regions.oracle import (
    ACCEPTED_RUNNING_REGIONS,
    BEFORE_RUNNING_REGIONS,
    BOUNDARY_METHOD_PROOFS,
    CORPUS_REGISTRY_CUSTODY,
    EXPECTED_ORACLE_SHA256,
    FROZEN_AGGREGATES,
    MANUFACTURING_P2_EXTRACTION_PLAN,
    PAGE_IDENTITIES,
    PREDECESSOR_OUTPUT_IDENTITIES,
    PREDECESSOR_OUTPUT_ROOT,
    PRINTED_LABEL_VISIBILITY_CONTRACT,
    REQUIRED_CORRECTIONS,
    SOURCE_IDENTITIES,
    SOURCE_REPORTS,
    SOURCE_VISIBILITY_CONTROLS,
    assert_oracle_integrity,
    oracle_sha256,
)
from tests.fixtures.phase_03.running_regions.synthetic import (
    FROZEN_FIXTURE_SHA256,
    FROZEN_REGISTRY_SHA256,
    REQUIRED_SYNTHETIC_COVERAGE,
    SYNTHETIC_FIXTURE_IDS,
    SYNTHETIC_FIXTURES,
    build_deadline_witness,
    build_resource_boundary_witness,
    build_state_machine_witnesses,
    fixture_hashes,
    registry_sha256,
    synthetic_self_check,
    verify_pdf_readers,
)

WORKSPACE = Path(__file__).resolve().parents[3]
POLICY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-03-layout"
    / "decisions"
    / "P03-running-regions-and-page-identity-policy.md"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _round_bbox(box: dict[str, Any]) -> dict[str, float | str]:
    return {
        "x": round(float(box["x0"]), 3),
        "y": round(float(box["top"]), 3),
        "width": round(float(box["x1"]) - float(box["x0"]), 3),
        "height": round(float(box["bottom"]) - float(box["top"]), 3),
        "unit": "pt",
    }


def _source_words_for_label(
    page: pdfplumber.page.Page,
    expected_bbox: dict[str, Any],
) -> list[dict[str, Any]]:
    x0 = float(expected_bbox["x"])
    y0 = float(expected_bbox["y"])
    x1 = x0 + float(expected_bbox["width"])
    y1 = y0 + float(expected_bbox["height"])
    selected = []
    for word in page.extract_words():
        center_x = (float(word["x0"]) + float(word["x1"])) / 2
        center_y = (float(word["top"]) + float(word["bottom"])) / 2
        if x0 - 0.02 <= center_x <= x1 + 0.02 and y0 - 0.02 <= center_y <= y1 + 0.02:
            selected.append(word)
    return sorted(selected, key=lambda word: (round(float(word["top"]), 2), word["x0"]))


def _available_source_report() -> dict[str, Any]:
    return {
        "report_version": "1.0",
        "policy_id": POLICY_ID,
        "source_sha256": "0" * 64,
        "status": "available",
        "pages": [
            {
                "page_index": 1,
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "coordinate_system_id": COORDINATE_SYSTEM_ID,
                "source_character_count": 0,
                "source_word_count": 0,
                "embedded_label": None,
                "label_candidates": [],
                "boundary_candidates": [],
                "concern_codes": [],
            }
        ],
        "counts": {
            "page_count": 1,
            "source_character_count": 0,
            "source_word_count": 0,
            "embedded_label_count": 0,
            "label_candidate_count": 0,
            "boundary_candidate_count": 0,
            "concern_count": 0,
        },
        "concern_codes": [],
        "extraction_ms": 0.0,
    }


def _source_boundary_candidate(
    candidate_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    for report in SOURCE_REPORTS.values():
        for page in report["pages"]:
            for candidate in page["boundary_candidates"]:
                if candidate["id"] == candidate_id:
                    return page, candidate
    raise AssertionError(f"unknown oracle boundary candidate: {candidate_id}")


def _manufacturing_oracle_extracted_plan() -> Any:
    plan = MANUFACTURING_P2_EXTRACTION_PLAN
    return build_extracted_contribution_plan(
        physical_page_index=plan["physical_page_index"],
        owner_public_item_id=plan["owner_public_item_id"],
        owner_sha256=plan["owner_sha256_before"],
        predecessor_canonical=plan["predecessor_canonical"],
        source_text=plan["source_text"],
        presentation_fragments=plan["presentation_fragments"],
        delimiters=plan["delimiters"],
        predecessor_intervals=plan["predecessor_intervals"],
        source_span_groups=plan["source_span_groups"],
    )


def _processing_summary(
    *,
    status: str = "projected",
    reason: str | None = None,
) -> dict[str, Any]:
    projected = status == "projected"
    return {
        "policy_id": POLICY_ID,
        "status": status,
        "reason": reason,
        "source_page_count": int(projected),
        "identity_count": int(projected),
        "detected_label_count": 0,
        "embedded_label_count": 0,
        "legacy_fallback_count": int(projected),
        "candidate_count": 0,
        "comparison_count": 0,
        "running_region_count": 0,
        "header_count": 0,
        "footer_count": 0,
        "top_navigation_count": 0,
        "bottom_navigation_count": 0,
        "concern_count": 0,
        "extraction_ms": 0.0,
        "projection_ms": 0.0,
        "total_ms": 0.0,
    }


def _identity(
    *,
    public_page: dict[str, Any],
    display_source: str,
    display_label: str,
    embedded_label: str | None = None,
    detected_printed_label: str | None = None,
    visible_text: str | None = None,
    concern_codes: list[str] | None = None,
) -> dict[str, Any]:
    detected = detected_printed_label is not None
    physical = display_source == "physical"
    if detected:
        evidence_bbox: dict[str, Any] | None = {
            "x": 300.0,
            "y": 760.0,
            "width": 8.0,
            "height": 10.0,
            "unit": "pt",
        }
        evidence_source = {
            "method": "native_printed_label",
            "reader": "pdfplumber",
            "page_index": 1,
            "public_item_id": "p1-i1",
            "public_path": ["pages", 0, "items", 0],
            "element_id": "el-1",
            "bbox_id": "bbox-1",
            "evidence_ids": [
                label_candidate_id(
                    source_sha256="1" * 64,
                    physical_page_index=1,
                    source_object_ids=["word-1"],
                    bbox=evidence_bbox,
                )
            ],
            "source_object_ids": ["word-1"],
        }
    elif display_source == "embedded_label":
        evidence_source = {
            "method": "embedded_pdf_label",
            "reader": "pypdfium2",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": ["page-label-1"],
            "source_object_ids": ["page-label-tree-1"],
        }
        evidence_bbox = None
    elif physical:
        evidence_source = {
            "method": "physical_page_index",
            "reader": "configured_predecessor",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": [],
            "source_object_ids": [],
        }
        evidence_bbox = None
    else:
        evidence_source = {
            "method": "legacy_display_fallback",
            "reader": "configured_predecessor",
            "page_index": 1,
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
            "evidence_ids": [],
            "source_object_ids": ["predecessor-page-1"],
        }
        evidence_bbox = None
    confidence_scope = (
        "source_metadata"
        if display_source == "embedded_label"
        else "deterministic_rule"
        if detected
        else "unavailable"
    )
    unavailable_reason = (
        "page_identity_display_fallback_physical"
        if physical
        else "page_identity_source_unavailable"
        if confidence_scope == "unavailable"
        else None
    )
    return {
        "schema_version": "1.0",
        "policy_id": POLICY_ID,
        "page_id": "page-1",
        "physical_page_index": 1,
        "embedded_label": embedded_label,
        "detected_printed_label": detected_printed_label,
        "visible_text": visible_text,
        "display_label": display_label,
        "display_source": display_source,
        "evidence_bbox": evidence_bbox,
        "evidence_source": evidence_source,
        "confidence": {
            "scope": confidence_scope,
            "score": None if confidence_scope == "unavailable" else 1.0,
            "unavailable_reason": unavailable_reason,
        },
        "concern_codes": concern_codes or [],
    }


def _direct_projected_witness() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    source_sha256 = "1" * 64
    bbox = {
        "x": 300.0,
        "y": 760.0,
        "width": 8.0,
        "height": 10.0,
        "unit": "pt",
    }
    predecessor_item = {
        "id": "p1-i1",
        "type": "text",
        "reading_order": 0,
        "value": "7",
        "md": "7",
        "bbox": bbox,
        "source": "native",
        "confidence": 1.0,
    }
    public_page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "page_width": 612.0,
        "page_height": 792.0,
        "unit": "pt",
        "success": True,
        "items": [],
        "warnings": [],
    }
    identity = _identity(
        public_page=public_page,
        display_source="detected_printed_label",
        display_label="7",
        detected_printed_label="7",
        visible_text="7",
    )
    descriptor = {
        "id": stable_id(
            "running-region",
            POLICY_ID,
            source_sha256,
            1,
            "el-1",
            "bbox-1",
            "footer",
        ),
        "page_id": "page-1",
        "physical_page_index": 1,
        "role": "footer",
        "canonical_scope": "footer",
        "source_public_item_id": "p1-i1",
        "source_public_path": ["pages", 0, "items", 0],
        "source_element_id": "el-1",
        "predecessor_type": "text",
        "predecessor_item_sha256": predecessor_item_sha256(predecessor_item, "text"),
        "bbox_id": "bbox-1",
        "bbox": bbox,
        "evidence_ids": ["evidence-1"],
        "source_object_ids": ["word-1"],
        "source_method": "printed_label_boundary",
        "repetition_group_id": None,
        "repetition_page_indexes": [],
        "confidence": {
            "scope": "deterministic_rule",
            "score": 1.0,
            "unavailable_reason": None,
        },
        "concern_codes": [],
        "canonical_block_id": "canonical-block-1",
    }
    projected_item = {
        **predecessor_item,
        "type": "footer",
        "layout_running_region_projected": True,
        "running_region_policy": POLICY_ID,
        "running_region": descriptor,
    }
    public_page["items"] = [projected_item]
    public_page["page_identity"] = identity
    canonical_block = {
        "id": "canonical-block-1",
        "page_id": "page-1",
        "primary_element_id": "el-1",
        "primary_element_type": "footer",
        "scope": "footer",
        "markdown": "7",
        "text": "7",
        "contributing_element_ids": ["el-1"],
        "relationship_ids": [],
        "excluded_contributions": [],
        "omission_reason": None,
    }
    empty_view = {"block_ids": [], "markdown": "", "text": ""}
    footer_view = {
        "block_ids": ["canonical-block-1"],
        "markdown": "7\n",
        "text": "7\n",
    }
    canonical_page = {
        "page_id": "page-1",
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "page_identity": identity,
        "blocks": [canonical_block],
        "full": footer_view,
        "body": empty_view,
        "header": empty_view,
        "footer": footer_view,
    }
    document = {
        "document": {"sha256": source_sha256},
        "pages": [public_page],
        "processing": {
            "running_regions": {
                **_processing_summary(),
                "detected_label_count": 1,
                "legacy_fallback_count": 0,
                "candidate_count": 1,
                "running_region_count": 1,
                "footer_count": 1,
            }
        },
        "canonical_presentation": {
            "pages": [canonical_page],
            "full": footer_view,
            "body": empty_view,
            "header": empty_view,
            "footer": footer_view,
        },
    }
    ir_document = {
        "pages": [
            {
                "id": "page-1",
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "coordinate_system_id": "coord-1",
                "region_ids": [],
                "element_ids": ["el-1"],
                "presentation_element_ids": ["el-1"],
                "page_identity": identity,
            }
        ],
        "elements": [
            {
                "id": "el-1",
                "page_id": "page-1",
                "type": "footer",
                "reading_order": 0,
                "value": "7",
                "markdown": "7",
                "bbox_ids": ["bbox-1"],
                "evidence_ids": ["evidence-1"],
                "presentation_role": "primary",
                "running_region": descriptor,
            }
        ],
        "bboxes": [
            {
                "id": "bbox-1",
                "coordinate_system_id": "coord-1",
                "x": 300.0,
                "y": 760.0,
                "width": 8.0,
                "height": 10.0,
            }
        ],
        "evidence": [
            {
                "id": "evidence-1",
                "element_id": "el-1",
                "bbox_id": "bbox-1",
            }
        ],
        "coordinate_systems": [
            {
                "id": "coord-1",
                "page_id": "page-1",
                "unit": "pt",
                "origin": "top_left",
            }
        ],
    }
    predecessor_document = deepcopy(document)
    predecessor_page = predecessor_document["pages"][0]
    predecessor_page.pop("page_identity")
    predecessor_page["items"] = [deepcopy(predecessor_item)]
    predecessor_canonical_page = predecessor_document["canonical_presentation"][
        "pages"
    ][0]
    predecessor_canonical_page.pop("page_identity")
    predecessor_block = predecessor_canonical_page["blocks"][0]
    predecessor_block["primary_element_type"] = "text"
    predecessor_block["scope"] = "body"
    body_view = {
        "block_ids": ["canonical-block-1"],
        "markdown": "7\n",
        "text": "7\n",
    }
    predecessor_canonical_page["full"] = deepcopy(body_view)
    predecessor_canonical_page["body"] = deepcopy(body_view)
    predecessor_canonical_page["header"] = deepcopy(empty_view)
    predecessor_canonical_page["footer"] = deepcopy(empty_view)
    predecessor_document["canonical_presentation"]["full"] = deepcopy(body_view)
    predecessor_document["canonical_presentation"]["body"] = deepcopy(body_view)
    predecessor_document["canonical_presentation"]["header"] = deepcopy(empty_view)
    predecessor_document["canonical_presentation"]["footer"] = deepcopy(empty_view)
    predecessor_document.pop("processing")

    predecessor_ir = deepcopy(ir_document)
    predecessor_ir["pages"][0].pop("page_identity")
    predecessor_ir["elements"][0]["type"] = "text"
    predecessor_ir["elements"][0].pop("running_region")
    return document, ir_document, predecessor_document, predecessor_ir


def test_oracle_and_all_source_custody_are_sealed() -> None:
    assert_oracle_integrity()
    assert oracle_sha256() == EXPECTED_ORACLE_SHA256
    registry = WORKSPACE / CORPUS_REGISTRY_CUSTODY["path"]
    assert registry.stat().st_size == CORPUS_REGISTRY_CUSTODY["size_bytes"]
    assert _sha256(registry) == CORPUS_REGISTRY_CUSTODY["sha256"]
    for identity in SOURCE_IDENTITIES.values():
        path = WORKSPACE / identity["path"]
        assert path.stat().st_size == identity["size_bytes"]
        assert _sha256(path) == identity["sha256"]
        with pdfplumber.open(path) as document:
            assert len(document.pages) == identity["page_count"]
    predecessor_root = WORKSPACE / PREDECESSOR_OUTPUT_ROOT
    for case_id, identity in PREDECESSOR_OUTPUT_IDENTITIES.items():
        path = predecessor_root / case_id / "our-output.json"
        assert path.stat().st_size == identity["size_bytes"]
        assert _sha256(path) == identity["sha256"]


def test_reviewed_page_identity_denominator_is_complete_and_exact() -> None:
    expected = {
        "catastrophe-recap": ["7"],
        "clean-energy": ["11"],
        "clinical-study": ["1/21", "7/21", "10/21", "11/21"],
        "component-datasheet": ["3", "7", "11"],
        "egov-survey": ["37"],
        "esg-metrics": ["80"],
        "finance-10k": ["28", "30", "32"],
        "health-report": ["103"],
        "insurance-acord": [None],
        "manufacturing-report": ["11", "15", "38"],
        "ny-timetable": ["2 of 28", "3 of 28", "4 of 28"],
        "postal-10k": ["2", "46", "49"],
        "purchase-agreement": [None],
        "settlement-agreement": ["24"],
        "uber-earnings": [None, "5", "6"],
    }
    actual: dict[str, list[str | None]] = {}
    for entry in PAGE_IDENTITIES:
        actual.setdefault(entry["case_id"], []).append(entry["detected_printed_label"])
        assert entry["embedded_label"] is None
        assert entry["physical_page"] >= 1
    assert actual == expected
    assert len(PAGE_IDENTITIES) == 30
    assert (
        sum(value is not None for values in actual.values() for value in values) == 27
    )
    assert sum(value is None for values in actual.values() for value in values) == 3
    assert (
        sum(bool(entry["legacy_navigation_conflict"]) for entry in PAGE_IDENTITIES) == 3
    )


def test_all_27_native_label_spans_and_bboxes_match_the_sources() -> None:
    documents: dict[str, pdfplumber.pdf.PDF] = {}
    source_bytes_by_case: dict[str, bytes] = {}
    try:
        for entry in PAGE_IDENTITIES:
            expected_bbox = entry["label_bbox"]
            if expected_bbox is None:
                continue
            case_id = entry["case_id"]
            if case_id not in documents:
                source_path = WORKSPACE / SOURCE_IDENTITIES[case_id]["path"]
                source_bytes_by_case[case_id] = source_path.read_bytes()
                documents[case_id] = pdfplumber.open(source_path)
            page = documents[case_id].pages[entry["physical_page"] - 1]
            selected = _source_words_for_label(page, expected_bbox)
            assert selected
            visible = " ".join(str(word["text"]) for word in selected)
            assert visible == entry["visible_text"]
            union = {
                "x0": min(float(word["x0"]) for word in selected),
                "top": min(float(word["top"]) for word in selected),
                "x1": max(float(word["x1"]) for word in selected),
                "bottom": max(float(word["bottom"]) for word in selected),
            }
            assert _round_bbox(union) == expected_bbox
            source_characters = tuple(
                page.chars[index]
                for index in entry["source_character_indexes"]
            )
            assert "".join(
                str(character["text"]) for character in source_characters
            ) == entry["visible_text"]
            non_stroking_fills = tuple(
                character["non_stroking_color"]
                for character in source_characters
            )
            assert all(fill is not None for fill in non_stroking_fills)
            assert (
                validate_rendered_label_visibility(
                    source_bytes_by_case[case_id],
                    physical_page_index=entry["physical_page"],
                    candidate_visible_text=entry["visible_text"],
                    candidate_bbox=expected_bbox,
                    non_stroking_fills=non_stroking_fills,
                )
                is None
            )
    finally:
        for document in documents.values():
            document.close()


def test_uber_page_one_hidden_glyph_is_not_a_label_or_running_region() -> None:
    source_path = WORKSPACE / SOURCE_IDENTITIES["uber-earnings"]["path"]
    hidden_bbox = {
        "x": 1841.616,
        "y": 1025.407,
        "width": 7.884,
        "height": 18.0,
        "unit": "pt",
    }
    with pdfplumber.open(source_path) as source:
        hidden = source.pages[0].chars[69]
        assert hidden["text"] == "1"
        assert _round_bbox(
            {
                "x0": hidden["x0"],
                "top": hidden["top"],
                "x1": hidden["x1"],
                "bottom": hidden["bottom"],
            }
        ) == hidden_bbox
        assert tuple(hidden["non_stroking_color"]) == pytest.approx(
            (0.9999966, 1.0, 1.0)
        )

    source_bytes = source_path.read_bytes()
    assert PRINTED_LABEL_VISIBILITY_CONTRACT == {
        "method": "pdfium_candidate_bbox_modal_rgb_v1",
        "render_scale_pixels_per_point": 4.0,
        "render_background_rgb": (255, 255, 255),
        "forms_rendered": False,
        "annotations_rendered": False,
        "minimum_channel_delta": 16,
        "maximum_render_dimension_pixels": 2_048,
        "maximum_render_pixels": 262_144,
        "maximum_non_stroking_fills": 256,
        "painted_fill_render_modes": (0, 2, 4, 6),
        "minimum_non_stroking_fill_alpha": 1,
        "fill_custody": (
            "gray_rgb_exact_cmyk_bidirectional_max_channel_delta"
        ),
        "maximum_cmyk_custody_channel_delta": 36,
        "candidate_object_binding": (
            "unique_compacted_sequence_or_delimiter_bounded_exact_suffix"
        ),
        "candidate_object_suffix_delimiters": (
            "whitespace",
            "|",
            ":",
            "/",
            "-",
        ),
        "selected_pdfium_rgb_is_contrast_authority": True,
        "maximum_text_objects": 256,
        "maximum_text_object_scan": 10_000,
        "maximum_form_depth": 8,
        "degenerate_finite_text_objects": "skipped",
        "nonfinite_text_object_bounds": "rejected",
        "minimum_intersecting_painted_text_objects": 1,
        "maximum_page_dimension_points": 20_000.0,
        "modal_tie_break": (
            "highest_count_then_lexicographically_smallest_rgb"
        ),
        "candidate_pixel_edges": "nearest_integer_ties_to_even",
        "retention": "ephemeral_gate_only",
    }
    document = pdfium.PdfDocument(source_bytes)
    try:
        for control in SOURCE_VISIBILITY_CONTROLS:
            bbox = control["bbox"]
            page = document[control["physical_page"] - 1]
            scale = PRINTED_LABEL_VISIBILITY_CONTRACT[
                "render_scale_pixels_per_point"
            ]
            page_width, page_height = page.get_size()
            left_px, top_px, right_px, bottom_px = (
                round(float(value) * scale)
                for value in (
                    bbox["x"],
                    bbox["y"],
                    float(bbox["x"]) + float(bbox["width"]),
                    float(bbox["y"]) + float(bbox["height"]),
                )
            )
            bitmap = page.render(
                scale=scale,
                rotation=0,
                crop=(
                    left_px / scale,
                    page_height - bottom_px / scale,
                    page_width - right_px / scale,
                    top_px / scale,
                ),
                may_draw_forms=False,
                fill_color=(255, 255, 255, 255),
                rev_byteorder=True,
                prefer_bgrx=False,
                maybe_alpha=False,
                draw_annots=False,
            )
            rendered = bitmap.to_pil()
            pixel_count = rendered.width * rendered.height
            assert rendered.mode == "RGB"
            assert (rendered.width, rendered.height, pixel_count) == (
                control["width_pixels"],
                control["height_pixels"],
                control["pixel_count"],
            )
            assert hashlib.sha256(rendered.tobytes()).hexdigest() == (
                control["render_rgb_sha256"]
            )
            colors = rendered.getcolors(maxcolors=pixel_count)
            assert colors
            modal_count, modal_rgb = min(
                colors,
                key=lambda record: (-record[0], record[1]),
            )
            render_delta = max(
                max(
                    abs(color[channel] - modal_rgb[channel])
                    for channel in range(3)
                )
                for _count, color in colors
            )
            assert (modal_rgb, modal_count, render_delta) == (
                control["modal_rgb"],
                control["modal_pixel_count"],
                control["render_max_channel_delta"],
            )
            if control["visible"]:
                assert (
                    validate_rendered_label_visibility(
                        source_bytes,
                        physical_page_index=control["physical_page"],
                        candidate_visible_text=control["text_layer_text"],
                        candidate_bbox=bbox,
                        non_stroking_fills=(
                            control["raw_non_stroking_fill"],
                        ),
                    )
                    is None
                )
            else:
                with pytest.raises(
                    ReadinessContractError,
                    match="render/fill contrast",
                ):
                    validate_rendered_label_visibility(
                        source_bytes,
                        physical_page_index=control["physical_page"],
                        candidate_visible_text=control["text_layer_text"],
                        candidate_bbox=bbox,
                        non_stroking_fills=(
                            control["raw_non_stroking_fill"],
                        ),
                    )
            rendered.close()
            bitmap.close()
            page.close()
    finally:
        document.close()

    identity = next(
        entry
        for entry in PAGE_IDENTITIES
        if entry["case_id"] == "uber-earnings"
        and entry["physical_page"] == 1
    )
    assert identity["detected_printed_label"] is None
    assert identity["display_source"] == "legacy_display_fallback"
    assert identity["display_label"] == "1"
    assert identity["null_control_item_id"] == "p1-i4"
    source_page = SOURCE_REPORTS["uber-earnings"]["pages"][0]
    assert source_page["label_candidates"] == ()
    assert source_page["boundary_candidates"] == ()
    assert not any(
        entry["case_id"] == "uber-earnings"
        and entry["physical_page"] == 1
        and entry["source_public_item_id"] == "p1-i4"
        for entry in ACCEPTED_RUNNING_REGIONS
    )
    assert "boundary-candidate-3f80eac2c9792554e1df" not in (
        BOUNDARY_METHOD_PROOFS
    )


def test_all_real_pdfs_have_no_embedded_page_labels() -> None:
    for identity in SOURCE_IDENTITIES.values():
        document = pdfium.PdfDocument(WORKSPACE / identity["path"])
        try:
            assert [
                document.get_page_label(index) or "" for index in range(len(document))
            ] == [""] * identity["page_count"]
        finally:
            document.close()


def test_running_region_denominator_is_41_plus_6_equals_47() -> None:
    assert len(BEFORE_RUNNING_REGIONS) == 41
    assert Counter(
        entry["before_inventory_type"] for entry in BEFORE_RUNNING_REGIONS
    ) == {
        "header": 13,
        "footer": 28,
    }
    assert len(REQUIRED_CORRECTIONS) == 6
    assert {
        (entry["case_id"], entry["physical_page"], entry["predecessor_item_id"])
        for entry in REQUIRED_CORRECTIONS
    } == {
        ("finance-10k", 2, "p2-i1"),
        ("finance-10k", 3, "p3-i1"),
        ("manufacturing-report", 2, "p2-i1"),
        ("esg-metrics", 1, "p1-i11"),
        ("esg-metrics", 1, "p1-i19"),
        ("esg-metrics", 1, "p1-i20"),
    }
    assert len(ACCEPTED_RUNNING_REGIONS) == 47
    assert Counter(entry["role"] for entry in ACCEPTED_RUNNING_REGIONS) == {
        "header": 16,
        "footer": 30,
        "navigation_bottom": 1,
    }
    assert Counter(entry["canonical_scope"] for entry in ACCEPTED_RUNNING_REGIONS) == {
        "header": 16,
        "footer": 31,
    }
    assert all(entry["expected_body_count"] == 0 for entry in ACCEPTED_RUNNING_REGIONS)
    assert all(entry["expected_full_count"] == 1 for entry in ACCEPTED_RUNNING_REGIONS)
    assert all("order_neighbors" in entry for entry in ACCEPTED_RUNNING_REGIONS)
    assert FROZEN_AGGREGATES["accepted_running_region_count"] == 47


def test_policy_freezes_stage_order_security_rollback_and_performance() -> None:
    policy = POLICY_PATH.read_text()
    for required in (
        "p03-running-regions-page-identity-v1",
        "detected_printed_label",
        "embedded_label",
        "legacy_display_fallback",
        "physical",
        "extracted_source_contribution",
        "effective-content-bottom cluster",
        "PARSER_LAYOUT_RUNNING_REGIONS_ENABLED",
        "64 MiB",
        "250 ms/document",
        "50 ms/document",
        "8 MiB",
        "production React renderer",
    ):
        assert required in policy
    assert policy.index("P03-US07 outlines") < policy.index(
        "P03-US08 running regions and page identity"
    )
    assert "29.15 s × 5% = 1.4575 s" in policy
    assert "46.76 s × 5% = 2.3380 s" in policy
    assert "129.475 MiB" not in policy
    assert "97.200 MiB" not in policy


def test_closed_contract_enums_and_extracted_limits_match_policy() -> None:
    assert set(DISPLAY_SOURCES) == {
        "detected_printed_label",
        "embedded_label",
        "legacy_display_fallback",
        "physical",
    }
    assert set(SOURCE_METHODS) == {
        "trusted_layout_role",
        "cross_page_repetition",
        "boundary_navigation",
        "printed_label_boundary",
        "effective_boundary_cluster",
        "extracted_source_contribution",
    }
    assert RESOURCE_LIMITS["extracted_contribution_utf8_bytes"] == 4 * 1024
    assert RESOURCE_LIMITS["extracted_contributions_per_page"] == 8
    assert RESOURCE_LIMITS["extracted_contributions_per_document"] == 64
    assert RESOURCE_LIMITS["extracted_intervals_per_contribution"] == 8
    assert RESOURCE_LIMITS["extracted_residual_plan_bytes_per_page"] == 16 * 1024
    assert RESOURCE_LIMITS["extracted_residual_plan_bytes_per_document"] == 256 * 1024
    assert RESOURCE_LIMITS["report_json_bytes"] == 8 * 1024 * 1024


def test_label_grammar_and_safe_embedded_normalization_are_closed() -> None:
    assert normalize_detected_label("7") == "7"
    assert normalize_detected_label("10 / 21") == "10/21"
    assert normalize_detected_label("Page 2 of 28") == "2 of 28"
    assert normalize_detected_label("PAGE | 11") == "11"
    assert normalize_embedded_label("  A-3  ") == "A-3"


def test_identity_precedence_conflict_legacy_and_physical_fallbacks() -> None:
    public_page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "Legacy 9",
        "items": [{"id": "p1-i1"}],
    }
    conflict = _identity(
        public_page=public_page,
        display_source="embedded_label",
        display_label="8",
        embedded_label="8",
        detected_printed_label="7",
        visible_text="7",
        concern_codes=["page_identity_source_conflict"],
    )
    validate_page_identity(conflict, public_page=public_page)
    assert conflict["confidence"]["scope"] == "source_metadata"

    legacy = _identity(
        public_page=public_page,
        display_source="legacy_display_fallback",
        display_label="Legacy 9",
    )
    validate_page_identity(legacy, public_page=public_page)

    unsafe_page = {**public_page, "page_label": "<script>"}
    physical = _identity(
        public_page=unsafe_page,
        display_source="physical",
        display_label="1",
        concern_codes=["page_identity_display_unsafe"],
    )
    validate_page_identity(physical, public_page=unsafe_page)


def test_detected_native_evidence_allows_only_complete_attached_or_detached_custody() -> (
    None
):
    public_page = {
        "page_index": 1,
        "page_number": 1,
        "page_label": "1",
        "items": [{"id": "p1-i1"}],
    }
    attached = _identity(
        public_page=public_page,
        display_source="detected_printed_label",
        display_label="7",
        detected_printed_label="7",
        visible_text="7",
    )
    validate_page_identity(attached, public_page=public_page)

    detached = json.loads(json.dumps(attached))
    detached_source = detached["evidence_source"]
    detached_source.update(
        {
            "public_item_id": None,
            "public_path": [],
            "element_id": None,
            "bbox_id": None,
        }
    )
    validate_page_identity(detached, public_page=public_page)

    missing_candidate = json.loads(json.dumps(detached))
    missing_candidate["evidence_source"]["evidence_ids"] = []
    with pytest.raises(ReadinessContractError, match="provenance"):
        validate_page_identity(missing_candidate, public_page=public_page)

    partial = json.loads(json.dumps(detached))
    partial["evidence_source"]["public_item_id"] = "p1-i1"
    with pytest.raises(ReadinessContractError, match="partially bound"):
        validate_page_identity(partial, public_page=public_page)


def test_real_manufacturing_split_source_plan_is_exact_bounded_and_reversible() -> None:
    output_path = (
        WORKSPACE
        / PREDECESSOR_OUTPUT_ROOT
        / "manufacturing-report"
        / "our-output.json"
    )
    predecessor = json.loads(output_path.read_text())
    owner = next(
        item for item in predecessor["pages"][1]["items"] if item["id"] == "p2-i1"
    )
    owner_block = next(
        block
        for block in predecessor["canonical_presentation"]["pages"][1]["blocks"]
        if block["primary_element_type"] == "chart"
        and block["text"] == owner["value"]
    )
    predecessor_canonical = owner_block["text"]
    fragments = ("NIST AMS 100-76", "February 2026")
    removed = tuple(f"{fragment}\n" for fragment in fragments)
    intervals = tuple(
        (
            predecessor_canonical.encode().index(value.encode()),
            predecessor_canonical.encode().index(value.encode()) + len(value.encode()),
        )
        for value in removed
    )
    source_text = "NIST AMS 100-76 February 2026"
    second_start = len(fragments[0].encode()) + 1
    plan = build_extracted_contribution_plan(
        physical_page_index=2,
        owner_public_item_id="p2-i1",
        owner_sha256=predecessor_item_sha256(owner, "chart"),
        predecessor_canonical=predecessor_canonical,
        source_text=source_text,
        presentation_fragments=fragments,
        delimiters=("\n", "\n"),
        predecessor_intervals=intervals,
        source_span_groups=(
            ((0, len(fragments[0].encode())),),
            ((second_start, len(source_text.encode())),),
        ),
    )
    residual = plan.execute()
    validate_extracted_plan_ledger([plan])
    assert len(extracted_plan_json_bytes(plan)) <= RESOURCE_LIMITS[
        "extracted_residual_plan_bytes_per_page"
    ]
    assert plan.presentation_text == "NIST AMS 100-76\nFebruary 2026"
    assert owner["value"] == predecessor_canonical
    assert owner["md"] == predecessor_canonical

    predecessor_bytes = predecessor_canonical.encode()
    removed_bytes = [predecessor_bytes[start:end] for start, end in intervals]
    residual_bytes = residual.encode()
    rebuilt: list[bytes] = []
    cursor = 0
    for insertion_offset, contribution in zip(
        plan.residual_insertion_offsets,
        removed_bytes,
        strict=True,
    ):
        rebuilt.extend((residual_bytes[cursor:insertion_offset], contribution))
        cursor = insertion_offset
    rebuilt.append(residual_bytes[cursor:])
    assert b"".join(rebuilt) == predecessor_bytes

    overlapping = replace(
        plan,
        predecessor_intervals=(plan.predecessor_intervals[0],) * 2,
    )
    with pytest.raises(ReadinessContractError, match="overlap/reorder"):
        overlapping.execute()

    reordered = replace(
        plan,
        predecessor_intervals=tuple(reversed(plan.predecessor_intervals)),
    )
    with pytest.raises(ReadinessContractError, match="overlap/reorder"):
        reordered.execute()

    nine_fragments = tuple(f"region-{index}" for index in range(9))
    nine_source = " ".join(nine_fragments)
    nine_predecessor = "".join(
        f"{fragment}\nbody-{index}\n"
        for index, fragment in enumerate(nine_fragments)
    )
    nine_intervals = []
    search_from = 0
    for fragment in nine_fragments:
        encoded = f"{fragment}\n".encode()
        start = nine_predecessor.encode().index(encoded, search_from)
        nine_intervals.append((start, start + len(encoded)))
        search_from = start + len(encoded)
    source_groups = []
    search_from = 0
    for fragment in nine_fragments:
        start = nine_source.encode().index(fragment.encode(), search_from)
        source_groups.append(((start, start + len(fragment.encode())),))
        search_from = start + len(fragment.encode())
    with pytest.raises(ReadinessContractError, match="parallel arrays"):
        build_extracted_contribution_plan(
            physical_page_index=1,
            owner_public_item_id="p1-i1",
            owner_sha256="a" * 64,
            predecessor_canonical=nine_predecessor,
            source_text=nine_source,
            presentation_fragments=nine_fragments,
            delimiters=("\n",) * 9,
            predecessor_intervals=nine_intervals,
            source_span_groups=source_groups,
        )


def test_source_report_and_all_processing_statuses_are_executable() -> None:
    validate_source_report(_available_source_report())
    validate_processing_summary(_processing_summary())
    validate_processing_summary(
        _processing_summary(
            status="unavailable",
            reason="running_region_source_evidence_unavailable",
        )
    )
    validate_processing_summary(
        _processing_summary(status="unavailable", reason="running_region_source_limit")
    )
    validate_processing_summary(
        _processing_summary(
            status="not_applicable",
            reason="running_region_input_not_applicable",
        )
    )
    validate_processing_summary(
        _processing_summary(
            status="failed_closed",
            reason="running_region_projection_failed_closed",
        )
    )


def test_all_real_source_reports_and_boundary_method_proofs_execute() -> None:
    for report in SOURCE_REPORTS.values():
        candidate_ids = {
            candidate["id"]
            for page in report["pages"]
            for candidate in page["boundary_candidates"]
        }
        report_proofs = {
            candidate_id: BOUNDARY_METHOD_PROOFS[candidate_id]
            for candidate_id in candidate_ids & set(BOUNDARY_METHOD_PROOFS)
        }
        validate_source_report(report, method_proofs=report_proofs)

    extracted_plan = _manufacturing_oracle_extracted_plan()
    assert extracted_plan.execute() == MANUFACTURING_P2_EXTRACTION_PLAN[
        "residual_canonical"
    ]
    for candidate_id, proof in BOUNDARY_METHOD_PROOFS.items():
        page, candidate = _source_boundary_candidate(candidate_id)
        expected_repetition_page_indexes = (
            tuple(proof["repetition_page_indexes"])
            if proof.get("evidence_mode") == "exact_repetition"
            else None
        )
        validate_boundary_method_proof(
            candidate,
            proof,
            page_width=page["page_width"],
            page_height=page["page_height"],
            label_candidate_ids=tuple(
                label["id"] for label in page["label_candidates"]
            ),
            label_candidates=page["label_candidates"],
            extracted_plan=(
                extracted_plan
                if candidate["source_method"]
                == "extracted_source_contribution"
                else None
            ),
            expected_repetition_page_indexes=(
                expected_repetition_page_indexes
            ),
        )

        if expected_repetition_page_indexes is not None:
            for fabricated_membership in ((1, 2), (1, 2, 4)):
                fabricated_proof = deepcopy(proof)
                fabricated_proof["repetition_page_indexes"] = (
                    fabricated_membership
                )
                with pytest.raises(
                    ReadinessContractError,
                    match="repetition expected membership",
                ):
                    validate_boundary_method_proof(
                        candidate,
                        fabricated_proof,
                        page_width=page["page_width"],
                        page_height=page["page_height"],
                        label_candidate_ids=tuple(
                            label["id"]
                            for label in page["label_candidates"]
                        ),
                        label_candidates=page["label_candidates"],
                        extracted_plan=extracted_plan,
                        expected_repetition_page_indexes=(
                            expected_repetition_page_indexes
                        ),
                    )


def test_real_effective_cluster_proof_rejects_adversarial_mutations() -> None:
    report = SOURCE_REPORTS["esg-metrics"]
    page = report["pages"][0]
    proofs = {
        candidate_id: deepcopy(proof)
        for candidate_id, proof in BOUNDARY_METHOD_PROOFS.items()
        if candidate_id
        in {
            candidate["id"] for candidate in page["boundary_candidates"]
        }
    }
    for missing_id in tuple(proofs):
        missing = deepcopy(proofs)
        missing.pop(missing_id)
        with pytest.raises(
            ReadinessContractError,
            match="effective boundary extension proof is absent",
        ):
            validate_source_report(report, method_proofs=missing)

    navigation_id = "boundary-candidate-08250274384c8509de06"
    navigation = next(
        candidate
        for candidate in page["boundary_candidates"]
        if candidate["id"] == navigation_id
    )
    label_ids = tuple(label["id"] for label in page["label_candidates"])

    duplicate = deepcopy(proofs[navigation_id])
    duplicate["effective_cluster"]["items"][1]["id"] = "p1-i11"
    bad_cue = deepcopy(proofs[navigation_id])
    bad_cue["navigation_cue"] = "INDEX"
    body_gap = deepcopy(proofs[navigation_id])
    body_gap["effective_cluster"]["remaining_body_bboxes"] = (
        *body_gap["effective_cluster"]["remaining_body_bboxes"][:-1],
        {
            "x": 389.55,
            "y": 450.0,
            "width": 114.83,
            "height": 4.0,
            "unit": "pt",
        },
    )
    extra_cut = deepcopy(proofs[navigation_id])
    extra_cut["effective_cluster"]["candidate_cut_count"] = 2
    for hostile_proof in (duplicate, bad_cue, body_gap, extra_cut):
        with pytest.raises(ReadinessContractError):
            validate_boundary_method_proof(
                navigation,
                hostile_proof,
                page_width=page["page_width"],
                page_height=page["page_height"],
                label_candidate_ids=label_ids,
                label_candidates=page["label_candidates"],
            )

    label_id = "boundary-candidate-b1588836d411b6d58339"
    _, label_candidate = _source_boundary_candidate(label_id)
    bad_label = deepcopy(proofs[label_id])
    bad_label["label_candidate_id"] = "label-candidate-unknown"
    with pytest.raises(ReadinessContractError, match="printed-label"):
        validate_boundary_method_proof(
            label_candidate,
            bad_label,
            page_width=page["page_width"],
            page_height=page["page_height"],
            label_candidate_ids=label_ids,
            label_candidates=page["label_candidates"],
        )


def test_nonprojecting_summary_preserves_legitimate_post_us07_furniture() -> None:
    predecessor_path = (
        WORKSPACE / PREDECESSOR_OUTPUT_ROOT / "clinical-study" / "our-output.json"
    )
    predecessor = json.loads(predecessor_path.read_text())
    assert any(
        item.get("type") in {"header", "footer"}
        for page in predecessor["pages"]
        for item in page["items"]
    )
    assert any(
        block["scope"] in {"header", "footer"}
        for page in predecessor["canonical_presentation"]["pages"]
        for block in page["blocks"]
        if block.get("omission_reason") is None
    )
    predecessor["processing"]["running_regions"] = _processing_summary(
        status="unavailable",
        reason="running_region_source_evidence_unavailable",
    )
    validate_projected_document(predecessor)


def test_projected_public_canonical_ir_and_reverse_projection_are_bound() -> None:
    document, ir_document, predecessor_document, predecessor_ir = (
        _direct_projected_witness()
    )
    validate_projected_document(document)
    validate_ir_bindings(ir_document, public_document=document)
    stripped = strip_complete_running_region_sidecars(
        document,
        predecessor_document=predecessor_document,
        ir_document=ir_document,
        predecessor_ir=predecessor_ir,
    )
    assert stripped == predecessor_document


def test_terminal_timing_combination_charges_extraction_once() -> None:
    initial = _processing_summary()
    initial.update({"extraction_ms": 4.125, "projection_ms": 2.25, "total_ms": 6.375})
    terminal = _processing_summary()
    terminal.update({"projection_ms": 1.5, "total_ms": 1.5})
    combined = combine_terminal_processing_summaries(initial, terminal)
    assert combined["extraction_ms"] == 4.125
    assert combined["projection_ms"] == 3.75
    assert combined["total_ms"] == 7.875


def test_synthetic_registry_is_complete_deterministic_and_sealed() -> None:
    coverage = {
        capability
        for definition in SYNTHETIC_FIXTURES
        for capability in definition.covers
    }
    assert coverage == set(REQUIRED_SYNTHETIC_COVERAGE)
    required_families = {
        "effective_bottom_cluster_positive",
        "extracted_contribution_positive",
        "empty_legacy_physical_fallback",
        "hostile_legacy_physical_fallback",
        "direct_strip_refusal",
        "extracted_strip_refusal",
        "terminal_residual_drift_rollback",
        "ir_binding_validation",
    }
    assert required_families <= coverage
    assert set(FROZEN_FIXTURE_SHA256) == set(SYNTHETIC_FIXTURE_IDS)
    assert FROZEN_REGISTRY_SHA256
    assert fixture_hashes() == dict(FROZEN_FIXTURE_SHA256)
    assert registry_sha256() == FROZEN_REGISTRY_SHA256
    assert synthetic_self_check() == dict(FROZEN_FIXTURE_SHA256)
    assert contract_self_check()


def test_every_synthetic_pdf_opens_in_both_required_readers() -> None:
    verified = verify_pdf_readers()
    assert verified
    assert set(verified) == {
        definition.fixture_id
        for definition in SYNTHETIC_FIXTURES
        if definition.kind == "pdf"
    }


def test_every_integer_and_byte_limit_has_exact_and_maximum_plus_one_witnesses() -> (
    None
):
    deadline_keys = {
        "source_extraction_seconds",
        "projection_page_seconds",
        "projection_document_seconds",
    }
    for counter, limit in RESOURCE_LIMITS.items():
        if counter in deadline_keys:
            continue
        assert isinstance(limit, int) and not isinstance(limit, bool)
        exact = build_resource_boundary_witness(counter)
        over = build_resource_boundary_witness(counter, maximum_plus_one=True)
        assert exact.measure() == limit
        assert exact.execute() is True
        assert over.measure() == limit + 1
        assert over.execute() is False


def test_all_injected_deadlines_accept_exact_and_refuse_overflow() -> None:
    for name in (
        "source_extraction_deadline",
        "projection_page_deadline",
        "projection_document_deadline",
    ):
        assert build_deadline_witness(name).execute() is True
        assert build_deadline_witness(name, maximum_plus_one=True).execute() is False


def test_flag_off_rollback_idempotence_and_terminal_state_witnesses_execute() -> None:
    witnesses = build_state_machine_witnesses()
    assert witnesses
    names = {witness.name for witness in witnesses}
    assert {
        "flag_off",
        "idempotence",
        "page_rollback",
        "document_rollback",
        "canonical_rollback",
        "terminal_replay",
        "terminal_identity_mismatch",
        "terminal_replay_failure",
    } <= names
    for witness in witnesses:
        assert witness.execute() is witness.committed


def test_phase04_release_first_completion_is_recorded_after_us08() -> None:
    phase04 = WORKSPACE / "tracker" / "phase-04-tables"
    assert "Status: Complete — release-first core functionality validated" in (
        phase04 / "README.md"
    ).read_text()
    for story in sorted((phase04 / "stories").glob("P04-US*.md")):
        text = story.read_text()
        assert "Status: Done — release-first core functionality validated" in text
        assert "## Release-first completion comment" in text


def test_oracle_payload_is_strict_json_and_has_no_runtime_hook() -> None:
    encoded = json.dumps(
        {
            "pages": PAGE_IDENTITIES,
            "regions": ACCEPTED_RUNNING_REGIONS,
        },
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert encoded
    for path in (WORKSPACE / "app").rglob("*.py"):
        assert "tests.fixtures.phase_03.running_regions" not in path.read_text()
