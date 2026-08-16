from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.services import pipeline as pipeline_service
from app.services.input_documents import InputKind
from app.services.pipeline import _apply_terminal_source_text_alignment
from app.services.source_text_alignment import (
    SOURCE_TEXT_ALIGNMENT_POLICY_ID,
)


WORKSPACE = Path(__file__).resolve().parents[2]
FLAG = "PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED"
PREREQUISITE_ENV = {
    "PARSER_SHARED_IR_ENABLED": "true",
    "PARSER_SHARED_IR_NORMALIZATION_ENABLED": "true",
    "PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED": "true",
    "PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED": "true",
    "PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED": "true",
    "PARSER_TEXT_RECONCILIATION_ENABLED": "true",
    "PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED": "true",
    "PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED": "true",
}


def _enabled_settings(**overrides: bool) -> Settings:
    values = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "text_integrity_font_audit_enabled": True,
        "text_integrity_font_recovery_enabled": True,
        "text_integrity_selective_span_ocr_enabled": True,
        "text_reconciliation_enabled": True,
        "ocr_numeric_cleanup_v2_enabled": True,
        "ocr_spatial_token_preservation_enabled": True,
        "text_integrity_source_alignment_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_source_alignment_flag_defaults_off_and_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().text_integrity_source_alignment_enabled is False

    for name, value in PREREQUISITE_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(FLAG, "true")

    loaded = Settings.from_env()

    assert loaded.text_integrity_source_alignment_enabled is True
    assert loaded.text_reconciliation_enabled is True
    assert loaded.ocr_numeric_cleanup_v2_enabled is True
    assert loaded.ocr_spatial_token_preservation_enabled is True


@pytest.mark.parametrize(
    "disabled_fields",
    (
        {"text_reconciliation_enabled": False},
        {
            "ocr_numeric_cleanup_v2_enabled": False,
            "ocr_spatial_token_preservation_enabled": False,
        },
        {"ocr_spatial_token_preservation_enabled": False},
    ),
)
def test_source_alignment_flag_requires_complete_phase_02_stack(
    disabled_fields: dict[str, bool],
) -> None:
    with pytest.raises(
        ValueError,
        match=FLAG,
    ):
        _enabled_settings(**disabled_fields)


def test_source_alignment_flag_rejects_invalid_environment_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FLAG, "sometimes")

    with pytest.raises(ValueError, match=FLAG):
        Settings.from_env()


def test_source_alignment_flag_is_documented_with_one_flag_rollback() -> None:
    readme = (WORKSPACE / "README.md").read_text(encoding="utf-8")
    example = (WORKSPACE / ".env.example").read_text(encoding="utf-8")

    assert readme.count(FLAG) >= 2
    assert f"{FLAG}=false" in example
    assert "Disable this single flag" in readme


def _terminal_payload() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "input.pdf",
            "mime_type": "application/pdf",
            "sha256": "a" * 64,
            "page_count": 1,
            "image_count": 0,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "warnings": [],
                "detected_images": [],
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "text",
                        "source": "native",
                        "value": "original",
                        "md": "original",
                        "reading_order": 0,
                        "bbox": {
                            "x": 10.0,
                            "y": 10.0,
                            "width": 40.0,
                            "height": 10.0,
                            "w": 40.0,
                            "h": 10.0,
                            "unit": "pt",
                        },
                    }
                ],
            }
        ],
        "processing": {},
        "warnings": [],
    }


def test_terminal_alignment_failure_rolls_back_partial_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import source_text_alignment

    payload = _terminal_payload()
    predecessor_pages = deepcopy(payload["pages"])

    def mutate_then_raise(
        pages: list[dict[str, Any]],
        _evidence: object,
    ) -> object:
        pages[0]["items"][0]["value"] = "partial mutation"
        raise RuntimeError("injected failure")

    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        mutate_then_raise,
    )
    projected = _apply_terminal_source_text_alignment(
        payload,
        _enabled_settings(),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert payload["pages"] == predecessor_pages
    assert projected["pages"] == predecessor_pages
    summary = projected["processing"]["source_text_alignment"]
    assert summary["policy_id"] == SOURCE_TEXT_ALIGNMENT_POLICY_ID
    assert summary["status"] == "unavailable"
    assert summary["unresolved_count"] == 1
    assert summary["concerns"] == [
        {
            "status": "unresolved",
            "reason": "source_alignment_failed_closed",
            "error_type": "RuntimeError",
        }
    ]


def test_unavailable_source_evidence_is_explicit_and_non_mutating() -> None:
    payload = _terminal_payload()

    projected = _apply_terminal_source_text_alignment(
        payload,
        _enabled_settings(),
        source_text_evidence=SimpleNamespace(
            usable=False,
            refusal_code="source_alignment_character_limit",
        ),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert projected["pages"] == payload["pages"]
    summary = projected["processing"]["source_text_alignment"]
    assert summary["status"] == "unavailable"
    assert summary["considered_count"] == 1
    assert summary["unresolved_count"] == 1
    assert summary["concerns"][0]["reason"] == (
        "source_alignment_character_limit"
    )


def test_zero_selection_preserves_predecessor_public_projection_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import ir, source_text_alignment

    payload = _terminal_payload()
    payload["canonical_presentation"] = {
        "sentinel": "predecessor-canonical-bytes"
    }
    predecessor = deepcopy(payload)
    summary = {
        "schema_version": "1.0",
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": "a" * 64,
        "status": "unchanged",
        "considered_count": 0,
        "selected_count": 0,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [],
        "concerns": [],
        "elapsed_ms": 0.1,
    }

    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        lambda _pages, _evidence: SimpleNamespace(
            to_dict=lambda: deepcopy(summary)
        ),
    )
    monkeypatch.setattr(
        ir,
        "round_trip_document",
        lambda _payload: pytest.fail(
            "zero-selection alignment must not rebuild canonical output"
        ),
    )

    projected = _apply_terminal_source_text_alignment(
        payload,
        _enabled_settings(canonical_serialization_enabled=True),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert payload == predecessor
    assert projected["pages"] == predecessor["pages"]
    assert (
        projected["canonical_presentation"]
        == predecessor["canonical_presentation"]
    )
    projected_without_summary = deepcopy(projected)
    projected_without_summary["processing"].pop("source_text_alignment")
    assert projected_without_summary == predecessor


@pytest.mark.parametrize(
    "summary_update",
    (
        {"schema_version": "2.0"},
        {"status": "selected"},
        {
            "considered_count": 1,
            "unresolved_count": 1,
            "concerns": [],
        },
        {
            "considered_count": 1,
            "unresolved_count": 1,
            "concerns": [{"status": "selected"}],
        },
        {
            "status": "refused",
            "considered_count": 1,
            "unchanged_count": 1,
        },
    ),
)
def test_malformed_source_alignment_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    summary_update: dict[str, Any],
) -> None:
    from app.services import source_text_alignment

    payload = _terminal_payload()
    predecessor = deepcopy(payload)
    summary = {
        "schema_version": "1.0",
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": "a" * 64,
        "status": "unchanged",
        "considered_count": 0,
        "selected_count": 0,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [],
        "concerns": [],
        "elapsed_ms": 0.1,
    }
    summary.update(summary_update)
    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        lambda _pages, _evidence: SimpleNamespace(
            to_dict=lambda: deepcopy(summary)
        ),
    )

    projected = _apply_terminal_source_text_alignment(
        payload,
        _enabled_settings(canonical_serialization_enabled=True),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert payload == predecessor
    assert projected["pages"] == predecessor["pages"]
    terminal = projected["processing"]["source_text_alignment"]
    assert terminal["status"] == "unavailable"
    assert terminal["concerns"] == [
        {
            "status": "unresolved",
            "reason": "source_alignment_failed_closed",
            "error_type": "ValueError",
        }
    ]


def test_valid_refused_source_alignment_metadata_remains_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import source_text_alignment

    payload = _terminal_payload()
    summary = {
        "schema_version": "1.0",
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": "a" * 64,
        "status": "refused",
        "considered_count": 1,
        "selected_count": 0,
        "unchanged_count": 0,
        "unresolved_count": 1,
        "selections": [],
        "concerns": [
            {
                "status": "unresolved",
                "reason": "source_alignment_deadline",
                "evidence_ids": [],
            }
        ],
        "elapsed_ms": 2_000.0,
    }
    monkeypatch.setattr(
        source_text_alignment,
        "align_pages_to_source",
        lambda _pages, _evidence: SimpleNamespace(
            to_dict=lambda: deepcopy(summary)
        ),
    )

    projected = _apply_terminal_source_text_alignment(
        payload,
        _enabled_settings(canonical_serialization_enabled=True),
        source_text_evidence=SimpleNamespace(usable=True),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert projected["pages"] == payload["pages"]
    assert projected["processing"]["source_text_alignment"] == summary


def test_terminal_alignment_default_off_returns_exact_payload() -> None:
    payload = _terminal_payload()

    projected = _apply_terminal_source_text_alignment(
        payload,
        Settings(),
        source_text_evidence=object(),
        source_sha256="a" * 64,
        input_kind=InputKind.PDF,
    )

    assert projected is payload
    assert "source_text_alignment" not in projected["processing"]


def _canonical_omission_contract_input() -> tuple[
    dict[str, Any], dict[str, Any], object, dict[int, list[dict[str, Any]]]
]:
    candidate = _terminal_payload()
    core_selection = {
        "owner_id": "already-proven-owner",
        "terminal_reason": "selected_vector_source_owned_table_duplicate",
    }
    summary = {
        "schema_version": "1.0",
        "policy_id": SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        "source_sha256": "a" * 64,
        "status": "selected",
        "considered_count": 1,
        "selected_count": 1,
        "unchanged_count": 0,
        "unresolved_count": 0,
        "selections": [core_selection],
        "concerns": [],
        "elapsed_ms": 1.0,
    }
    candidate["canonical_presentation"] = {"state": "core"}
    candidate["processing"] = {
        "source_text_alignment": deepcopy(summary),
        "core_cleanup": {"selected_count": 1_765},
    }
    return candidate, summary, object(), {1: [{"bound": True}]}


def _canonical_omission_projection(
    candidate: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = candidate["pages"][0]["items"][0]
    omission = {
        "owner_id": owner["id"],
        "owner_type": "TeXt",
        "page_index": 1,
        "original_text": "contradicted OCR",
        "selected_text": "",
        "terminal_reason": "source_contradicted_primary_ocr",
        "rejected_ocr_alternative": {
            "owner_snapshot": deepcopy(owner),
        },
    }
    projected_summary = deepcopy(summary)
    projected_summary["selections"].append(omission)
    projected_summary["selected_count"] += 1
    projected = deepcopy(candidate)
    projected["canonical_presentation"] = {"state": "omitted"}
    projected["processing"]["source_text_alignment"] = projected_summary
    return projected, projected_summary


def test_canonical_ocr_omission_commit_is_canonical_and_summary_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import canonical_ocr_omission

    candidate, summary, terminal_ir, bound = (
        _canonical_omission_contract_input()
    )
    candidate_before = deepcopy(candidate)
    summary_before = deepcopy(summary)
    ir_identity = id(terminal_ir)
    calls: list[str] = []

    def apply(*args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append("apply")
        assert args[0] is candidate
        assert id(args[1]) == ir_identity
        assert args[4] is bound
        assert args[5] == b"%PDF-1.7\nsource\n%%EOF"
        return _canonical_omission_projection(candidate, summary)

    def validate(*args: Any, **_kwargs: Any) -> bool:
        calls.append("replay")
        assert id(args[1]) == ir_identity
        return True

    monkeypatch.setattr(
        canonical_ocr_omission,
        "apply_source_contradicted_primary_ocr_omissions",
        apply,
    )
    monkeypatch.setattr(
        canonical_ocr_omission,
        "validate_source_contradicted_primary_ocr_omissions",
        validate,
    )

    projected, projected_summary = (
        pipeline_service._apply_terminal_canonical_ocr_omission(
            candidate,
            terminal_ir,
            summary,
            source_text_evidence=SimpleNamespace(usable=True),
            selected_vector_representations=bound,
            source_pdf_bytes=b"%PDF-1.7\nsource\n%%EOF",
        )
    )

    assert calls == ["apply", "replay"]
    assert candidate == candidate_before
    assert summary == summary_before
    assert projected["pages"] == candidate["pages"]
    assert projected["pages"] is candidate["pages"]
    assert projected["canonical_presentation"] == {"state": "omitted"}
    assert projected["processing"]["core_cleanup"] == {
        "selected_count": 1_765
    }
    assert projected["processing"]["source_text_alignment"] == (
        projected_summary
    )
    assert len(projected_summary["selections"]) == 2


@pytest.mark.parametrize(
    "mode",
    (
        "identity_noop",
        "apply_exception",
        "validator_false",
        "validator_exception",
        "public_mutation",
        "processing_mutation",
    ),
)
def test_canonical_ocr_omission_failure_keeps_validated_core_transaction(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    from app.services import canonical_ocr_omission

    candidate, summary, terminal_ir, bound = (
        _canonical_omission_contract_input()
    )
    candidate_before = deepcopy(candidate)
    summary_before = deepcopy(summary)

    def apply(*_args: Any, **_kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        if mode == "identity_noop":
            return candidate, summary
        if mode == "apply_exception":
            raise RuntimeError("optional omission failed")
        projected, projected_summary = _canonical_omission_projection(
            candidate, summary
        )
        if mode == "public_mutation":
            projected["pages"][0]["items"][0]["value"] = "tampered"
        if mode == "processing_mutation":
            projected["processing"]["core_cleanup"] = {
                "selected_count": 0
            }
        return projected, projected_summary

    def validate(*_args: Any, **_kwargs: Any) -> bool:
        if mode == "validator_exception":
            raise RuntimeError("optional replay failed")
        return mode != "validator_false"

    monkeypatch.setattr(
        canonical_ocr_omission,
        "apply_source_contradicted_primary_ocr_omissions",
        apply,
    )
    monkeypatch.setattr(
        canonical_ocr_omission,
        "validate_source_contradicted_primary_ocr_omissions",
        validate,
    )

    projected, projected_summary = (
        pipeline_service._apply_terminal_canonical_ocr_omission(
            candidate,
            terminal_ir,
            summary,
            source_text_evidence=SimpleNamespace(usable=True),
            selected_vector_representations=bound,
            source_pdf_bytes=b"%PDF-1.7\nsource\n%%EOF",
        )
    )

    assert projected is candidate
    assert projected_summary is summary
    assert candidate == candidate_before
    assert summary == summary_before


def test_canonical_ocr_omission_isolation_catches_recursive_report_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import canonical_ocr_omission

    candidate, summary, terminal_ir, bound = (
        _canonical_omission_contract_input()
    )
    recursive: dict[str, Any] = {}
    recursive["self"] = recursive
    summary["selections"] = [recursive]
    candidate["processing"]["source_text_alignment"] = summary

    monkeypatch.setattr(
        canonical_ocr_omission,
        "apply_source_contradicted_primary_ocr_omissions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RecursionError("optional report recursion")
        ),
    )

    projected, projected_summary = (
        pipeline_service._apply_terminal_canonical_ocr_omission(
            candidate,
            terminal_ir,
            summary,
            source_text_evidence=SimpleNamespace(usable=True),
            selected_vector_representations=bound,
            source_pdf_bytes=b"%PDF-1.7\nsource\n%%EOF",
        )
    )

    assert projected is candidate
    assert projected_summary is summary


def test_canonical_ocr_omission_rejects_generic_table_authority_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import canonical_ocr_omission

    candidate, summary, terminal_ir, bound = (
        _canonical_omission_contract_input()
    )
    monkeypatch.setattr(
        canonical_ocr_omission,
        "apply_source_contradicted_primary_ocr_omissions",
        lambda *_args, **_kwargs: pytest.fail("optional lane must not run"),
    )

    projected, projected_summary = (
        pipeline_service._apply_terminal_canonical_ocr_omission(
            candidate,
            terminal_ir,
            summary,
            source_text_evidence=SimpleNamespace(usable=True),
            selected_vector_representations=bound,
            source_pdf_bytes=b"%PDF-1.7\nsource\n%%EOF",
            authoritative_table_views={1: [{"table": "generic"}]},
        )
    )

    assert projected is candidate
    assert projected_summary is summary


@pytest.mark.parametrize(
    ("update", "owner_ids"),
    (
        ({"owner_type": "paragraph"}, ("p1-i1",)),
        ({"selected_text": "source"}, ("p1-i1",)),
        (
            {
                "rejected_ocr_alternative": {
                    "owner_snapshot": {"id": "p1-i1"}
                }
            },
            ("p1-i1",),
        ),
        ({}, ()),
        ({}, ("different-owner",)),
    ),
)
def test_terminal_validator_closes_retained_canonical_ocr_owner(
    update: dict[str, Any],
    owner_ids: tuple[str, ...],
) -> None:
    candidate, core_summary, _terminal_ir, _bound = (
        _canonical_omission_contract_input()
    )
    projected, summary = _canonical_omission_projection(
        candidate, core_summary
    )
    summary["selections"][-1].update(update)

    with pytest.raises(ValueError):
        pipeline_service._validate_terminal_source_alignment(
            projected,
            summary,
            prevalidated_selections=core_summary["selections"],
            canonical_ocr_omission_owner_ids=owner_ids,
        )


def test_terminal_validator_accepts_exact_retained_canonical_ocr_owner() -> None:
    candidate, core_summary, _terminal_ir, _bound = (
        _canonical_omission_contract_input()
    )
    projected, summary = _canonical_omission_projection(
        candidate, core_summary
    )

    pipeline_service._validate_terminal_source_alignment(
        projected,
        summary,
        prevalidated_selections=core_summary["selections"],
        canonical_ocr_omission_owner_ids=("p1-i1",),
    )
