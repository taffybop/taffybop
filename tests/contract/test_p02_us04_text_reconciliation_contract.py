from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import text_reconciliation as reconciliation
from tests.fixtures.phase_02.text_reconciliation import (
    SOURCE_SHA256,
    candidate,
    deterministic_font_case,
    group,
    low_margin_case,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "text_integrity_font_audit_enabled": True,
        "text_integrity_font_recovery_enabled": True,
        "text_integrity_selective_span_ocr_enabled": True,
        "pdf_visual_analysis_enabled": True,
        "text_reconciliation_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def _report(*groups: dict[str, Any]) -> Any:
    return reconciliation.reconcile_text_candidates(
        list(groups),
        source_sha256=SOURCE_SHA256,
    )


def test_text_reconciliation_flag_defaults_off_and_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().text_reconciliation_enabled is False

    monkeypatch.setenv("PARSER_SHARED_IR_ENABLED", "true")
    monkeypatch.setenv("PARSER_SHARED_IR_NORMALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_CANONICAL_SERIALIZATION_ENABLED", "true")
    monkeypatch.setenv("PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED", "true")
    monkeypatch.setenv("PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED",
        "true",
    )
    monkeypatch.setenv("PARSER_TEXT_RECONCILIATION_ENABLED", "true")

    assert Settings.from_env().text_reconciliation_enabled is True


@pytest.mark.parametrize(
    "overrides",
    (
        {
            "shared_ir_enabled": False,
            "shared_ir_normalization_enabled": False,
            "canonical_serialization_enabled": False,
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
            "text_integrity_selective_span_ocr_enabled": False,
        },
        {
            "shared_ir_normalization_enabled": False,
            "canonical_serialization_enabled": False,
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
            "text_integrity_selective_span_ocr_enabled": False,
        },
        {
            "text_integrity_font_audit_enabled": False,
            "text_integrity_font_recovery_enabled": False,
            "text_integrity_selective_span_ocr_enabled": False,
        },
        {
            "text_integrity_font_recovery_enabled": False,
            "text_integrity_selective_span_ocr_enabled": False,
        },
        {"text_integrity_selective_span_ocr_enabled": False},
    ),
)
def test_text_reconciliation_requires_the_complete_evidence_pipeline(
    overrides: dict[str, bool],
) -> None:
    with pytest.raises(
        ValueError,
        match="PARSER_TEXT_RECONCILIATION_ENABLED requires",
    ):
        replace(_settings(), **overrides)


def test_text_reconciliation_does_not_add_a_canonical_serializer_dependency() -> (
    None
):
    settings = replace(
        _settings(),
        canonical_serialization_enabled=False,
    )

    assert settings.text_reconciliation_enabled is True
    assert settings.canonical_serialization_enabled is False


def test_reconciliation_report_is_strict_versioned_and_round_trippable() -> None:
    report = _report(deterministic_font_case())
    payload = report.model_dump(mode="json", exclude_none=True)

    assert payload["schema_version"] == "1.0"
    assert payload["policy_id"] == "text-reconciliation-v1"
    assert payload["source_sha256"] == SOURCE_SHA256
    assert set(payload) == {
        "schema_version",
        "policy_id",
        "source_sha256",
        "status",
        "candidate_count",
        "group_count",
        "selected_count",
        "unresolved_count",
        "unchanged_count",
        "elapsed_ms",
        "outcomes",
        "concerns",
    }
    assert (
        reconciliation.TextReconciliationReport.model_validate(payload)
        == report
    )

    with pytest.raises(ValidationError, match="Extra inputs"):
        reconciliation.TextReconciliationReport.model_validate(
            {**payload, "unexpected": True}
        )
    with pytest.raises(ValidationError):
        reconciliation.TextReconciliationReport.model_validate(
            {**payload, "schema_version": "2.0"}
        )


def test_group_candidate_and_provenance_models_are_strict_and_bounded() -> None:
    fixture = deterministic_font_case()
    validated = reconciliation.TextCandidateGroup.model_validate(fixture)
    serialized = validated.model_dump(mode="json", exclude_none=True)
    assert (
        reconciliation.TextCandidateGroup.model_validate(serialized)
        == validated
    )

    for required_field in (
        "source_sha256",
        "lineage_family",
        "origin_asset_id",
        "method",
    ):
        invalid = deepcopy(fixture["candidates"][0])
        invalid["provenance"].pop(required_field)
        with pytest.raises(ValidationError):
            reconciliation.TextCandidate.model_validate(invalid)

    extra = deepcopy(fixture["candidates"][0])
    extra["semantic_plausibility"] = 1.0
    with pytest.raises(ValidationError, match="Extra inputs"):
        reconciliation.TextCandidate.model_validate(extra)

    too_long = deepcopy(fixture["candidates"][0])
    too_long["text"] = "x" * 4097
    with pytest.raises(ValidationError):
        reconciliation.TextCandidate.model_validate(too_long)

    too_many_evidence = deepcopy(fixture["candidates"][0])
    too_many_evidence["evidence_ids"] = [
        f"ev-{index}" for index in range(65)
    ]
    with pytest.raises(ValidationError):
        reconciliation.TextCandidate.model_validate(too_many_evidence)

    nonfinite = deepcopy(fixture["candidates"][0])
    nonfinite["bbox"]["x"] = float("nan")
    with pytest.raises(ValidationError):
        reconciliation.TextCandidate.model_validate(nonfinite)

    oversized_group = deepcopy(fixture)
    template = oversized_group["candidates"][0]
    oversized_group["candidates"] = [
        {
            **deepcopy(template),
            "candidate_id": f"candidate-{index}",
            "evidence_ids": [f"ev-{index}"],
        }
        for index in range(17)
    ]
    with pytest.raises(ValidationError):
        reconciliation.TextCandidateGroup.model_validate(oversized_group)


def test_selected_trace_has_exact_candidate_and_evidence_provenance() -> None:
    source_group = deterministic_font_case()
    payload = _report(source_group).model_dump(
        mode="json",
        exclude_none=False,
    )
    outcome = payload["outcomes"][0]

    assert outcome["rule_version"] == "1.0"
    assert set(outcome) == {
        "group_id",
        "span_id",
        "owner_element_id",
        "page_index",
        "target_bbox",
        "rule_version",
        "status",
        "reason_code",
        "selected_text",
        "selected_candidate_ids",
        "margin",
        "replacement_mode",
        "decisions",
    }
    selected_decisions = [
        decision for decision in outcome["decisions"] if decision["selected"]
    ]
    assert len(selected_decisions) == 1
    selected = selected_decisions[0]
    assert set(selected) == {
        "candidate_id",
        "text",
        "bbox",
        "source_kind",
        "mapping_safety",
        "method",
        "lineage_family",
        "origin_asset_id",
        "evidence_ids",
        "confidence",
        "eligible",
        "selected",
        "component_scores",
        "total_score",
        "candidate_target_overlap",
        "target_candidate_overlap",
        "owner_target_overlap",
        "target_owner_overlap",
        "observed_scripts",
        "independent_support_count",
        "reason_codes",
    }
    source_candidates = source_group["candidates"]
    source_selected = next(
        row for row in source_candidates
        if row["candidate_id"] == selected["candidate_id"]
    )
    assert outcome["selected_text"] == source_selected["text"]
    assert selected["bbox"] == source_selected["bbox"]
    assert selected["evidence_ids"] == source_selected["evidence_ids"]
    assert selected["source_kind"] == source_selected["source_kind"]
    assert selected["lineage_family"] == source_selected["provenance"][
        "lineage_family"
    ]
    assert selected["origin_asset_id"] == source_selected["provenance"][
        "origin_asset_id"
    ]
    assert set(selected["component_scores"]) == {
        "authority",
        "independence",
        "mapping_safety",
        "geometry",
        "replacement_scope",
        "completeness",
        "script",
        "confidence",
    }
    assert all(
        0 <= score <= 1
        for score in selected["component_scores"].values()
    )
    assert selected["total_score"] >= 0
    assert selected["reason_codes"]
    assert set(selected["evidence_ids"]).isdisjoint(
        evidence_id
        for decision in outcome["decisions"]
        if not decision["selected"]
        for evidence_id in decision["evidence_ids"]
    )


def test_report_invariants_reject_fabricated_text_and_inconsistent_counts() -> None:
    report = _report(deterministic_font_case())
    payload = report.model_dump(mode="json", exclude_none=True)

    fabricated = deepcopy(payload)
    fabricated["outcomes"][0]["selected_text"] = "invented completion"
    with pytest.raises(ValidationError, match="selected"):
        reconciliation.TextReconciliationReport.model_validate(fabricated)

    inconsistent = deepcopy(payload)
    inconsistent["selected_count"] = 0
    with pytest.raises(ValidationError, match="selected_count"):
        reconciliation.TextReconciliationReport.model_validate(inconsistent)

    duplicate_evidence = deepcopy(payload)
    selected = next(
        decision
        for decision in duplicate_evidence["outcomes"][0]["decisions"]
        if decision["selected"]
    )
    unselected = next(
        decision
        for decision in duplicate_evidence["outcomes"][0]["decisions"]
        if not decision["selected"]
    )
    unselected["evidence_ids"] = selected["evidence_ids"]
    with pytest.raises(ValidationError, match="evidence"):
        reconciliation.TextReconciliationReport.model_validate(
            duplicate_evidence
        )

    selection_disagreement = deepcopy(payload)
    selected = next(
        decision
        for decision in selection_disagreement["outcomes"][0]["decisions"]
        if decision["selected"]
    )
    selected["selected"] = False
    with pytest.raises(ValidationError, match="selected"):
        reconciliation.TextReconciliationReport.model_validate(
            selection_disagreement
        )

    dangling_selection = deepcopy(payload)
    dangling_selection["outcomes"][0]["selected_candidate_ids"] = [
        "candidate-that-does-not-exist"
    ]
    with pytest.raises(ValidationError, match="selected"):
        reconciliation.TextReconciliationReport.model_validate(
            dangling_selection
        )

    contradictory_terminal = deepcopy(payload)
    contradictory_terminal["outcomes"][0]["status"] = "unresolved"
    with pytest.raises(ValidationError):
        reconciliation.TextReconciliationReport.model_validate(
            contradictory_terminal
        )


def test_unresolved_trace_retains_every_candidate_and_a_reasoned_concern() -> None:
    fixture = low_margin_case()
    payload = _report(fixture).model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]

    assert outcome["status"] == "unresolved"
    assert outcome["selected_candidate_ids"] == []
    assert "selected_text" not in outcome
    assert {
        row["candidate_id"] for row in outcome["decisions"]
    } == {row["candidate_id"] for row in fixture["candidates"]}
    assert {
        row["evidence_ids"][0] for row in outcome["decisions"]
    } == {
        row["evidence_ids"][0] for row in fixture["candidates"]
    }
    assert len(payload["concerns"]) == 1
    concern = payload["concerns"][0]
    assert concern["span_id"] == "span-1"
    assert concern["group_id"] == "group-1"
    assert set(concern["candidate_ids"]) == {
        "ocr-low-margin-a",
        "ocr-low-margin-b",
    }


def test_caller_inputs_are_never_mutated() -> None:
    fixture = deterministic_font_case()
    original = deepcopy(fixture)

    _report(fixture)

    assert fixture == original


def test_nfc_is_comparison_only_and_never_changes_emitted_candidate_bytes() -> (
    None
):
    decomposed = "Cafe\u0301"
    rows = [
        candidate(
            "native-nfc",
            decomposed,
            source_kind="native",
            lineage_family="pdf_text_layer",
            method="pdf_text_layer",
            origin_asset_id="pdf-text-layer:nfc",
            evidence_ids=("ev-native-nfc",),
            mapping_safety="healthy",
        ),
        candidate(
            "ocr-nfc",
            "Café",
            source_kind="selective_ocr",
            lineage_family="rendered_pixels",
            method="selective_pdf_tesseract_tsv",
            origin_asset_id="raster:nfc",
            evidence_ids=("ev-ocr-nfc",),
            confidence=0.99,
        ),
    ]
    fixture = group(rows, owner_text=decomposed)

    payload = _report(fixture).model_dump(mode="json", exclude_none=True)
    outcome = payload["outcomes"][0]

    assert outcome["status"] == "unchanged"
    assert outcome["selected_text"] == decomposed
    assert outcome["selected_text"].encode("utf-8") == decomposed.encode(
        "utf-8"
    )
    assert outcome["selected_text"] != "Café"
