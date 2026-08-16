from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import pytest

from app.services import text_reconciliation as reconciliation
from tests.fixtures.phase_02.text_reconciliation import (
    SOURCE_SHA256,
    candidate,
    dependent_bad_layer_case,
    deterministic_font_case,
    group,
    independent_ocr_case,
    low_margin_case,
    mixed_script_case,
    partial_overlap_case,
)


def _reconcile(*groups: dict[str, Any], clock: Any = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"source_sha256": SOURCE_SHA256}
    if clock is not None:
        kwargs["clock"] = clock
    report = reconciliation.reconcile_text_candidates(list(groups), **kwargs)
    return report.model_dump(mode="json", exclude_none=True)


def _single_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["group_count"] == 1
    assert len(payload["outcomes"]) == 1
    return payload["outcomes"][0]


def _decision(
    outcome: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    return next(
        decision
        for decision in outcome["decisions"]
        if decision["candidate_id"] == candidate_id
    )


def _stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stable = deepcopy(payload)
    stable.pop("elapsed_ms", None)
    return stable


def test_deterministic_font_evidence_wins_the_catastrophe_span() -> None:
    fixture = deterministic_font_case()
    payload = _reconcile(fixture)
    outcome = _single_outcome(payload)
    font = _decision(outcome, "font-catastrophe")
    native = _decision(outcome, "native-catastrophe")

    assert payload["schema_version"] == "1.0"
    assert payload["policy_id"] == "text-reconciliation-v1"
    assert payload["status"] == "complete"
    assert payload["candidate_count"] == 2
    assert payload["selected_count"] == 1
    assert outcome["status"] == "selected"
    assert outcome["selected_text"] == "Equity (US$)"
    assert outcome["selected_candidate_ids"] == ["font-catastrophe"]
    assert outcome["reason_code"] == "deterministic_font_evidence"
    assert outcome["target_bbox"] == fixture["target_bbox"]
    assert font["selected"] is True
    assert font["eligible"] is True
    assert font["lineage_family"] == "embedded_font_program"
    assert font["evidence_ids"] == [
        "ev-font-run-catastrophe",
        "ev-font-glyph-1",
        "ev-font-glyph-2",
    ]
    assert font["component_scores"]["mapping_safety"] > 0
    assert font["total_score"] > native["total_score"]
    assert payload["concerns"] == []


def test_independent_high_confidence_ocr_wins_over_unsafe_text_sources() -> None:
    payload = _reconcile(independent_ocr_case())
    outcome = _single_outcome(payload)
    ocr = _decision(outcome, "ocr-independent")

    assert outcome["status"] == "selected"
    assert outcome["selected_text"] == "CIO"
    assert outcome["selected_candidate_ids"] == ["ocr-independent"]
    assert outcome["reason_code"] == "independent_high_confidence_ocr"
    assert outcome["margin"] >= reconciliation.MIN_SELECTION_MARGIN
    assert ocr["selected"] is True
    assert ocr["eligible"] is True
    assert ocr["confidence"] == 0.99
    assert ocr["lineage_family"] == "rendered_pixels"
    assert ocr["candidate_target_overlap"] == 1.0
    assert ocr["target_candidate_overlap"] == 1.0
    assert ocr["evidence_ids"] == [
        "ev-ocr-independent",
        "ev-ocr-token-cio",
    ]
    assert payload["selected_count"] == 1
    assert payload["unresolved_count"] == 0


def test_two_engines_reading_one_bad_layer_never_create_two_votes() -> None:
    payload = _reconcile(dependent_bad_layer_case())
    outcome = _single_outcome(payload)
    native = _decision(outcome, "native-dependent")
    layout = _decision(outcome, "layout-dependent")

    assert outcome["status"] == "unresolved"
    assert outcome["selected_candidate_ids"] == []
    assert native["lineage_family"] == layout["lineage_family"] == (
        "pdf_text_layer"
    )
    assert native["origin_asset_id"] == layout["origin_asset_id"]
    assert native["independent_support_count"] == 1
    assert layout["independent_support_count"] == 1
    assert native["selected"] is layout["selected"] is False
    assert {
        decision["candidate_id"] for decision in outcome["decisions"]
    } == {
        "native-dependent",
        "layout-dependent",
        "ocr-counterevidence",
    }
    assert payload["selected_count"] == 0
    assert payload["unresolved_count"] == 1
    assert len(payload["concerns"]) == 1
    assert payload["concerns"][0]["group_id"] == "group-1"


def test_psm3_and_psm11_from_one_crop_are_one_lineage_observation() -> None:
    rows = [
        candidate(
            "ocr-psm3",
            "40 AO",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:chart-7:crop-1",
            evidence_ids=("ev-psm3",),
            confidence=0.96,
        ),
        candidate(
            "ocr-psm11",
            "40 AO",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:chart-7:crop-1",
            evidence_ids=("ev-psm11",),
            confidence=0.95,
        ),
        candidate(
            "ocr-independent-counterreading",
            "40 40",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="synthetic-raster:chart-7:capture-2",
            evidence_ids=("ev-independent-counterreading",),
            confidence=0.90,
        ),
    ]
    baseline = _reconcile(
        group(
            [rows[0], rows[2]],
            owner_text="damaged",
        )
    )
    payload = _reconcile(group(rows, owner_text="damaged"))
    outcome = _single_outcome(payload)
    baseline_outcome = _single_outcome(baseline)

    assert outcome["status"] == "unresolved"
    assert (
        outcome["status"],
        outcome["reason_code"],
        outcome["selected_candidate_ids"],
        outcome["margin"],
    ) == (
        baseline_outcome["status"],
        baseline_outcome["reason_code"],
        baseline_outcome["selected_candidate_ids"],
        baseline_outcome["margin"],
    )
    assert {
        _decision(outcome, candidate_id)["independent_support_count"]
        for candidate_id in ("ocr-psm3", "ocr-psm11")
    } == {1}
    assert all(
        not _decision(outcome, candidate_id)["selected"]
        for candidate_id in ("ocr-psm3", "ocr-psm11")
    )


def test_equal_overlapping_healthy_native_is_unchanged_and_not_duplicated() -> (
    None
):
    rows = [
        candidate(
            "native-overlap",
            "Settlement amount",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:settlement",
            evidence_ids=("ev-native-overlap",),
            mapping_safety="healthy",
        ),
        candidate(
            "ocr-overlap",
            "Settlement amount",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:settlement",
            evidence_ids=("ev-ocr-overlap",),
            confidence=0.99,
        ),
    ]
    payload = _reconcile(group(rows, owner_text="Settlement amount"))
    outcome = _single_outcome(payload)

    assert outcome["status"] == "unchanged"
    assert outcome["selected_text"] == "Settlement amount"
    assert outcome["reason_code"] == "healthy_native_authoritative"
    assert outcome["replacement_mode"] == "none"
    assert outcome["selected_candidate_ids"] == ["native-overlap"]
    assert outcome["selected_text"].count("Settlement amount") == 1
    assert _decision(outcome, "ocr-overlap")["selected"] is False


@pytest.mark.parametrize(
    ("factory", "reason_code"),
    (
        (low_margin_case, "low_margin_conflict"),
        (partial_overlap_case, "partial_overlap_conflict"),
        (mixed_script_case, "mixed_script_conflict"),
    ),
)
def test_policy_conflicts_remain_unresolved_with_every_decision(
    factory: Any,
    reason_code: str,
) -> None:
    fixture = factory()
    payload = _reconcile(fixture)
    outcome = _single_outcome(payload)

    assert outcome["status"] == "unresolved"
    assert outcome["selected_candidate_ids"] == []
    assert outcome["reason_code"] == reason_code
    assert {
        decision["candidate_id"] for decision in outcome["decisions"]
    } == {
        row["candidate_id"] for row in fixture["candidates"]
    }
    assert all(
        decision["bbox"] and decision["evidence_ids"]
        for decision in outcome["decisions"]
    )
    assert len(payload["concerns"]) == 1
    assert payload["selected_count"] == 0
    assert payload["unresolved_count"] == 1


def test_group_and_candidate_order_do_not_change_structural_decisions() -> None:
    first = deterministic_font_case()
    second = independent_ocr_case()
    second["group_id"] = "group-2"
    second["span_id"] = "span-2"
    second["owner_element_id"] = "owner-2"
    for row in second["candidates"]:
        row["span_id"] = "span-2"
        provenance = row["provenance"]
        if "audit_finding_id" in provenance:
            provenance["audit_finding_id"] = "audit-finding:span-2"
        if row["source_kind"] == "selective_ocr":
            provenance["selective_span_id"] = "span-2"
            provenance["selective_outcome_id"] = "selective-outcome:span-2"

    baseline = _stable_payload(_reconcile(first, second))
    reordered_first = deepcopy(first)
    reordered_first["candidates"].reverse()
    reordered_second = deepcopy(second)
    reordered_second["candidates"] = [
        reordered_second["candidates"][1],
        reordered_second["candidates"][2],
        reordered_second["candidates"][0],
    ]
    reordered = _stable_payload(
        _reconcile(reordered_second, reordered_first)
    )

    assert baseline == reordered
    assert json.dumps(baseline, sort_keys=True, ensure_ascii=False) == (
        json.dumps(reordered, sort_keys=True, ensure_ascii=False)
    )


def test_exact_resource_constants_match_the_accepted_policy() -> None:
    assert reconciliation.MAX_RECONCILIATION_GROUPS == 512
    assert reconciliation.MAX_RECONCILIATION_CANDIDATES_PER_GROUP == 16
    assert reconciliation.MAX_RECONCILIATION_CANDIDATES == 4096
    assert reconciliation.MAX_RECONCILIATION_EVIDENCE_IDS == 64
    assert reconciliation.MAX_RECONCILIATION_TEXT_CODEPOINTS == 4096
    assert reconciliation.MAX_RECONCILIATION_CONCERNS == 512
    assert reconciliation.MAX_RECONCILIATION_REPORT_BYTES == 8 * 1024 * 1024
    assert reconciliation.MAX_RECONCILIATION_SECONDS == 2.0
    assert reconciliation.OCR_CONFIDENCE_FLOOR == 0.90
    assert reconciliation.CANDIDATE_TARGET_RECIPROCAL_OVERLAP == 0.80
    assert reconciliation.OWNER_TARGET_RECIPROCAL_OVERLAP == 0.90
    assert reconciliation.MINIMUM_SELECTION_MARGIN == 0.10
