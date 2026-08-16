from __future__ import annotations

from copy import deepcopy
from itertools import count
import json
from typing import Any

import pytest

from app.services import text_reconciliation as reconciliation
from tests.fixtures.phase_02.text_reconciliation import (
    SOURCE_SHA256,
    candidate,
    deterministic_font_case,
    group,
    independent_ocr_case,
    low_margin_case,
    mixed_script_case,
)


def _reconcile(
    *groups: dict[str, Any],
    source_sha256: str = SOURCE_SHA256,
    clock: Any = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"source_sha256": source_sha256}
    if clock is not None:
        kwargs["clock"] = clock
    return reconciliation.reconcile_text_candidates(
        list(groups),
        **kwargs,
    ).model_dump(mode="json", exclude_none=True)


def _outcome(payload: dict[str, Any]) -> dict[str, Any]:
    assert len(payload["outcomes"]) == 1
    return payload["outcomes"][0]


def _decision(
    payload: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    return next(
        decision
        for decision in _outcome(payload)["decisions"]
        if decision["candidate_id"] == candidate_id
    )


def _ocr(group_payload: dict[str, Any]) -> dict[str, Any]:
    return next(
        row
        for row in group_payload["candidates"]
        if row["source_kind"] == "selective_ocr"
    )


@pytest.mark.parametrize(
    ("confidence", "status", "eligible"),
    (
        (0.90, "selected", True),
        (0.899999, "unresolved", False),
        (None, "unresolved", False),
    ),
)
def test_ocr_confidence_boundary_is_exact(
    confidence: float | None,
    status: str,
    eligible: bool,
) -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["confidence"] = confidence

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == status
    assert _decision(payload, "ocr-independent")["eligible"] is eligible


@pytest.mark.parametrize(
    ("width", "status", "eligible"),
    (
        (144.0, "selected", True),
        (143.999, "unresolved", False),
    ),
)
def test_candidate_target_reciprocal_overlap_boundary_is_exact(
    width: float,
    status: str,
    eligible: bool,
) -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["bbox"]["width"] = width

    payload = _reconcile(fixture)
    decision = _decision(payload, "ocr-independent")

    assert _outcome(payload)["status"] == status
    assert decision["eligible"] is eligible
    assert decision["candidate_target_overlap"] == 1.0
    assert decision["target_candidate_overlap"] == pytest.approx(
        min(width, 180.0) / 180.0
    )


@pytest.mark.parametrize(
    ("owner_width", "status"),
    (
        (200.0, "selected"),
        (200.001, "unresolved"),
    ),
)
def test_whole_owner_overlap_boundary_is_exact(
    owner_width: float,
    status: str,
) -> None:
    fixture = independent_ocr_case()
    fixture["owner_bbox"]["width"] = owner_width
    # Exercise the whole-owner geometry gate itself.  A unique substring is
    # an independent policy-authorized replacement path, so use a real but
    # repeated source substring to make that fallback deliberately ambiguous.
    fixture["owner_text"] = fixture["owner_markdown"] = "ClO and ClO"
    fixture["replacement_original_text"] = "ClO"

    payload = _reconcile(fixture)
    decision = _decision(payload, "ocr-independent")

    assert _outcome(payload)["status"] == status
    assert decision["owner_target_overlap"] == pytest.approx(
        180.0 / owner_width
    )
    assert decision["target_owner_overlap"] == 1.0


@pytest.mark.parametrize(
    ("runner_up", "status"),
    (
        (0.90, "selected"),
        (0.900001, "unresolved"),
    ),
)
def test_selection_margin_boundary_is_exact(
    runner_up: float,
    status: str,
) -> None:
    fixture = low_margin_case()
    fixture["candidates"][0]["confidence"] = 1.0
    fixture["candidates"][1]["confidence"] = runner_up

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == status
    if status == "selected":
        assert _outcome(payload)["margin"] == pytest.approx(0.10)
    else:
        assert _outcome(payload)["margin"] < 0.10


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        ("transform_valid", False, "transform_invalid"),
        ("pass_completed", False, "ocr_pass_incomplete"),
        ("candidate_complete", False, "ocr_candidate_incomplete"),
        ("candidate_truncated", True, "ocr_candidate_truncated"),
        ("token_truncated", True, "ocr_token_truncated"),
        (
            "malformed_output_concern",
            True,
            "ocr_malformed_output_concern",
        ),
    ),
)
def test_incomplete_ocr_evidence_is_ineligible(
    field: str,
    value: bool,
    reason_code: str,
) -> None:
    fixture = independent_ocr_case()
    provenance = _ocr(fixture)["provenance"]
    provenance[field] = value

    payload = _reconcile(fixture)
    decision = _decision(payload, "ocr-independent")

    assert _outcome(payload)["status"] == "unresolved"
    assert decision["eligible"] is False
    assert reason_code in decision["reason_codes"]


def test_declared_word_count_must_equal_retained_token_count() -> None:
    fixture = independent_ocr_case()
    provenance = _ocr(fixture)["provenance"]
    provenance["word_count"] = 2
    provenance["retained_token_count"] = 1

    payload = _reconcile(fixture)
    decision = _decision(payload, "ocr-independent")

    assert _outcome(payload)["status"] == "unresolved"
    assert decision["eligible"] is False
    assert "ocr_token_count_mismatch" in decision["reason_codes"]


@pytest.mark.parametrize(
    "field",
    (
        "audit_source_sha256",
        "audit_finding_id",
        "audit_run_index",
        "font_ref",
        "font_object_id",
        "recovery_source_sha256",
        "selective_ocr_source_sha256",
        "selective_span_id",
        "selective_outcome_id",
        "recovery_refusal_reason_code",
    ),
)
def test_ocr_requires_complete_audit_recovery_and_selective_lineage(
    field: str,
) -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["provenance"].pop(field)

    payload = _reconcile(fixture)
    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert payload["outcomes"] == []
    assert {
        concern["code"] for concern in payload["concerns"]
    } == {"text_reconciliation_invalid_group"}


@pytest.mark.parametrize(
    "field",
    (
        "audit_source_sha256",
        "audit_finding_id",
        "audit_run_index",
        "font_ref",
        "font_object_id",
        "recovery_source_sha256",
        "run_evidence_id",
    ),
)
def test_font_recovery_requires_complete_audit_and_run_lineage(
    field: str,
) -> None:
    fixture = deterministic_font_case()
    font = next(
        row
        for row in fixture["candidates"]
        if row["source_kind"] == "font_recovery"
    )
    font["provenance"].pop(field)

    payload = _reconcile(fixture)

    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert payload["outcomes"] == []
    assert {
        concern["code"] for concern in payload["concerns"]
    } == {"text_reconciliation_invalid_group"}


@pytest.mark.parametrize(
    "field",
    (
        "source_sha256",
        "audit_source_sha256",
        "recovery_source_sha256",
        "selective_ocr_source_sha256",
    ),
)
def test_cross_pdf_lineage_fails_closed(field: str) -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["provenance"][field] = "b" * 64

    payload = _reconcile(fixture)

    assert payload["status"] == "partial"
    assert payload["outcomes"] == []
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } == {"text_reconciliation_source_mismatch"}


def test_replayed_candidate_identity_across_groups_is_transactional() -> None:
    first = independent_ocr_case()
    second = deepcopy(first)
    second["group_id"] = "group-2"
    second["span_id"] = "span-2"
    second["owner_element_id"] = "owner-2"
    for row in second["candidates"]:
        row["span_id"] = "span-2"
        row["evidence_ids"] = [
            f"{evidence_id}-second" for evidence_id in row["evidence_ids"]
        ]
        provenance = row["provenance"]
        if "audit_finding_id" in provenance:
            provenance["audit_finding_id"] = "audit-finding:span-2"
        if "run_evidence_id" in provenance:
            provenance["run_evidence_id"] = (
                f"{provenance['run_evidence_id']}-second"
            )
        if row["source_kind"] == "selective_ocr":
            provenance["selective_span_id"] = "span-2"
            provenance["selective_outcome_id"] = "selective-outcome:span-2"

    payload = _reconcile(first, second)

    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } >= {"text_reconciliation_replayed_candidate_id"}


def test_replayed_evidence_identity_across_groups_is_transactional() -> None:
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

    _ocr(second)["evidence_ids"][0] = "ev-font-glyph-1"
    payload = _reconcile(first, second)

    assert payload["status"] == "partial"
    assert payload["outcomes"] == []
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } >= {"text_reconciliation_replayed_evidence_id"}


def test_cross_page_candidate_identity_fails_closed() -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["page_index"] = 2

    payload = _reconcile(fixture)

    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } >= {"text_reconciliation_cross_page_candidate"}


def test_safe_recovery_and_refused_ocr_for_one_span_are_contradictory() -> None:
    fixture = deterministic_font_case()
    fixture["candidates"].append(
        candidate(
            "ocr-contradictory-refusal",
            "Equity (USS)",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:page-1:contradictory-crop",
            evidence_ids=(
                "ev-ocr-contradictory",
                "ev-ocr-contradictory-token",
            ),
            confidence=0.97,
            word_count=2,
            retained_token_count=2,
        )
    )

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == "unresolved"
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } >= {"text_reconciliation_contradictory_provenance"}


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "abc\u202edef",
        "abc\ufdd0def",
        "abc\ue000def",
        "abc\u0378def",
        "abc\ud800def",
    ),
)
def test_unsafe_unicode_can_never_gain_text_authority(
    unsafe_text: str,
) -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["text"] = unsafe_text

    payload = _reconcile(fixture)
    decision = _decision(payload, "ocr-independent")

    assert _outcome(payload)["status"] == "unresolved"
    assert decision["eligible"] is False
    assert "unsafe_unicode" in decision["reason_codes"]


def test_unknown_expected_script_never_enables_a_script_guess() -> None:
    fixture = independent_ocr_case()
    fixture["expected_scripts"] = []

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == "unresolved"
    assert "script_unsupported" in _decision(
        payload,
        "ocr-independent",
    )["reason_codes"]


def test_healthy_native_cannot_be_displaced_by_mixed_script_ocr() -> None:
    fixture = mixed_script_case()
    native = next(
        row for row in fixture["candidates"] if row["source_kind"] == "native"
    )
    native["mapping_safety"] = "healthy"

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == "unchanged"
    assert _outcome(payload)["selected_text"] == "paypal total"
    assert _outcome(payload)["selected_candidate_ids"] == ["native-latin"]
    assert _decision(payload, "ocr-cyrillic")["selected"] is False


def test_unique_source_substring_allows_bounded_partial_replacement() -> None:
    target = {
        "x": 72.0,
        "y": 120.0,
        "width": 70.0,
        "height": 12.0,
        "unit": "pt",
    }
    rows = [
        candidate(
            "native-substring",
            "ClO",
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:substring",
            evidence_ids=("ev-native-substring",),
            bbox=target,
        ),
        candidate(
            "ocr-substring",
            "CIO",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:substring",
            evidence_ids=("ev-ocr-substring",),
            confidence=0.99,
            bbox=target,
        ),
    ]
    fixture = group(
        rows,
        owner_text="prefix ClO suffix",
        target_bbox=target,
        replacement_original_text="ClO",
    )

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == "selected"
    assert _outcome(payload)["replacement_mode"] == "unique_substring"
    assert _outcome(payload)["selected_text"] == "CIO"


def test_repeated_source_substring_is_never_replaced_by_guessing() -> None:
    fixture = independent_ocr_case()
    fixture["owner_text"] = fixture["owner_markdown"] = "ClO and ClO"
    fixture["replacement_original_text"] = "ClO"
    fixture["owner_bbox"]["width"] = 400.0

    payload = _reconcile(fixture)

    assert _outcome(payload)["status"] == "unresolved"
    assert _outcome(payload)["reason_code"] == "replacement_range_ambiguous"


def test_two_spans_touching_one_owner_replacement_range_are_unresolved() -> None:
    first = independent_ocr_case()
    first["owner_text"] = first["owner_markdown"] = "prefix ClO suffix"
    first["replacement_original_text"] = "ClO"
    first["owner_bbox"]["width"] = 400.0
    second = deepcopy(first)
    second["group_id"] = "group-2"
    second["span_id"] = "span-2"
    for index, row in enumerate(second["candidates"]):
        row["candidate_id"] = f"{row['candidate_id']}-second"
        row["span_id"] = "span-2"
        row["evidence_ids"] = [
            f"{evidence_id}-second" for evidence_id in row["evidence_ids"]
        ]
        row["provenance"]["origin_asset_id"] = (
            f"{row['provenance']['origin_asset_id']}:second:{index}"
        )
        if "audit_finding_id" in row["provenance"]:
            row["provenance"]["audit_finding_id"] = "audit-finding:span-2"
        if "run_evidence_id" in row["provenance"]:
            row["provenance"]["run_evidence_id"] = (
                f"{row['provenance']['run_evidence_id']}-second"
            )
        if row["source_kind"] == "selective_ocr":
            row["provenance"]["selective_span_id"] = "span-2"
            row["provenance"]["selective_outcome_id"] = (
                "selective-outcome:span-2"
            )

    payload = _reconcile(first, second)

    assert payload["selected_count"] == 0
    assert payload["unresolved_count"] == 2
    assert {
        outcome["reason_code"] for outcome in payload["outcomes"]
    } == {"replacement_range_conflict"}


def test_deadline_is_checked_inside_work_and_returns_one_bounded_concern() -> None:
    ticks = count()

    def clock() -> float:
        return next(ticks) * 0.75

    first = deterministic_font_case()
    second = independent_ocr_case()
    second["group_id"] = "group-2"
    second["span_id"] = "span-2"
    second["owner_element_id"] = "owner-2"
    for index, row in enumerate(second["candidates"]):
        row["candidate_id"] = f"{row['candidate_id']}-second"
        row["span_id"] = "span-2"
        row["evidence_ids"] = [
            f"{evidence_id}-second" for evidence_id in row["evidence_ids"]
        ]
        row["provenance"]["origin_asset_id"] = (
            f"{row['provenance']['origin_asset_id']}:second:{index}"
        )
        if "audit_finding_id" in row["provenance"]:
            row["provenance"]["audit_finding_id"] = "audit-finding:span-2"
        if "run_evidence_id" in row["provenance"]:
            row["provenance"]["run_evidence_id"] = (
                f"{row['provenance']['run_evidence_id']}-second"
            )
        if row["source_kind"] == "selective_ocr":
            row["provenance"]["selective_span_id"] = "span-2"
            row["provenance"]["selective_outcome_id"] = (
                "selective-outcome:span-2"
            )

    payload = _reconcile(first, second, clock=clock)

    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } == {"text_reconciliation_deadline"}


def test_document_group_and_candidate_caps_discard_all_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = deterministic_font_case()
    second = independent_ocr_case()
    second["group_id"] = "group-2"
    second["span_id"] = "span-2"
    second["owner_element_id"] = "owner-2"
    for index, row in enumerate(second["candidates"]):
        row["candidate_id"] = f"{row['candidate_id']}-second"
        row["span_id"] = "span-2"
        row["evidence_ids"] = [
            f"{evidence_id}-second" for evidence_id in row["evidence_ids"]
        ]
        row["provenance"]["origin_asset_id"] = (
            f"{row['provenance']['origin_asset_id']}:second:{index}"
        )
        if "audit_finding_id" in row["provenance"]:
            row["provenance"]["audit_finding_id"] = "audit-finding:span-2"
        if "run_evidence_id" in row["provenance"]:
            row["provenance"]["run_evidence_id"] = (
                f"{row['provenance']['run_evidence_id']}-second"
            )
        if row["source_kind"] == "selective_ocr":
            row["provenance"]["selective_span_id"] = "span-2"
            row["provenance"]["selective_outcome_id"] = (
                "selective-outcome:span-2"
            )

    monkeypatch.setattr(reconciliation, "MAX_RECONCILIATION_GROUPS", 1)
    group_limited = _reconcile(first, second)
    assert group_limited["status"] == "partial"
    assert group_limited["outcomes"] == []
    assert group_limited["selected_count"] == 0
    assert {
        concern["code"] for concern in group_limited["concerns"]
    } == {"text_reconciliation_group_limit"}

    monkeypatch.setattr(reconciliation, "MAX_RECONCILIATION_GROUPS", 512)
    monkeypatch.setattr(reconciliation, "MAX_RECONCILIATION_CANDIDATES", 1)
    candidate_limited = _reconcile(first)
    assert candidate_limited["status"] == "partial"
    assert candidate_limited["outcomes"] == []
    assert candidate_limited["selected_count"] == 0
    assert {
        concern["code"] for concern in candidate_limited["concerns"]
    } == {"text_reconciliation_candidate_limit"}


def test_report_size_exhaustion_discards_all_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconciliation,
        "MAX_RECONCILIATION_REPORT_BYTES",
        512,
    )

    payload = _reconcile(independent_ocr_case())

    assert payload["status"] == "partial"
    assert payload["selected_count"] == 0
    assert {
        concern["code"] for concern in payload["concerns"]
    } == {"text_reconciliation_output_limit"}
    assert len(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ) <= 512


def test_fail_soft_concerns_are_capped_before_report_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reconciliation,
        "MAX_RECONCILIATION_CONCERNS",
        1,
    )
    invalid_groups = [
        {"group_id": "invalid-group-1"},
        {"group_id": "invalid-group-2"},
    ]

    payload = _reconcile(*invalid_groups)

    assert payload["status"] == "partial"
    assert payload["outcomes"] == []
    assert payload["selected_count"] == 0
    assert len(payload["concerns"]) == 1
    assert payload["concerns"][0]["code"] == (
        "text_reconciliation_invalid_group"
    )


@pytest.mark.parametrize("duplicate_count", (1, 2, 3, 4))
def test_same_lineage_ocr_duplicates_never_toggle_selection(
    duplicate_count: int,
) -> None:
    fixture = independent_ocr_case()
    original = _ocr(fixture)
    duplicates = [original]
    for index in range(1, duplicate_count):
        duplicate = deepcopy(original)
        duplicate["candidate_id"] = f"ocr-independent-duplicate-{index}"
        duplicate["evidence_ids"] = [
            f"{evidence_id}-duplicate-{index}"
            for evidence_id in duplicate["evidence_ids"]
        ]
        duplicates.append(duplicate)
    fixture["candidates"] = [
        row
        for row in fixture["candidates"]
        if row["source_kind"] != "selective_ocr"
    ] + duplicates

    payload = _reconcile(fixture)
    outcome = _outcome(payload)

    assert outcome["status"] == "selected"
    assert outcome["reason_code"] == "independent_high_confidence_ocr"
    assert outcome["selected_text"] == original["text"]
    assert len(outcome["selected_candidate_ids"]) == 1
    assert sum(
        decision["selected"] for decision in outcome["decisions"]
    ) == 1


def test_two_whole_owner_groups_cannot_both_select_the_same_range() -> None:
    first = independent_ocr_case()
    second = deepcopy(first)
    second["group_id"] = "whole-owner-group-2"
    second["span_id"] = "whole-owner-span-2"
    for index, row in enumerate(second["candidates"]):
        row["candidate_id"] = f"{row['candidate_id']}-whole-owner-2"
        row["span_id"] = second["span_id"]
        row["evidence_ids"] = [
            f"{evidence_id}-whole-owner-2"
            for evidence_id in row["evidence_ids"]
        ]
        provenance = row["provenance"]
        provenance["origin_asset_id"] = (
            f"{provenance['origin_asset_id']}:whole-owner-2:{index}"
        )
        if "audit_finding_id" in provenance:
            provenance["audit_finding_id"] = (
                "audit-finding:whole-owner-span-2"
            )
        if "run_evidence_id" in provenance:
            provenance["run_evidence_id"] = (
                f"{provenance['run_evidence_id']}-whole-owner-2"
            )
        if row["source_kind"] == "selective_ocr":
            provenance["selective_span_id"] = second["span_id"]
            provenance["selective_outcome_id"] = (
                "selective-outcome:whole-owner-span-2"
            )

    payload = _reconcile(first, second)

    assert payload["status"] == "complete"
    assert payload["selected_count"] == 0
    assert payload["unresolved_count"] == 2
    assert {
        outcome["reason_code"] for outcome in payload["outcomes"]
    } == {"replacement_range_conflict"}


def test_surrogate_evidence_is_unresolved_and_hashes_deterministically() -> None:
    fixture = independent_ocr_case()
    _ocr(fixture)["text"] = "\ud800"

    report = reconciliation.reconcile_text_candidates(
        [fixture],
        source_sha256=SOURCE_SHA256,
    )
    payload = report.model_dump(mode="json", exclude_none=True)

    assert _outcome(payload)["status"] == "unresolved"
    assert _outcome(payload)["reason_code"] == "unsafe_unicode"
    first = reconciliation.stable_reconciliation_sha256(report)
    second = reconciliation.stable_reconciliation_sha256(report)
    assert first == second
    assert len(first) == 64
