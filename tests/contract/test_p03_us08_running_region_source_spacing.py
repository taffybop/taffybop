"""Generic source-space repair contracts for running-region text owners."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.models import ParseResult
from app.config import Settings
from app.services import source_text_alignment as alignment
from app.services import pipeline as pipeline_service
from app.services import running_regions
from app.services.input_documents import InputKind
from app.services.ir import build_document_ir
from app.services.presentation import build_canonical_presentation
from tests.contract.test_p03_us08_running_region_contract import (
    _add_fake_running_projection,
    _pipeline_payload,
    _single_page_source_reader_pdf,
)


def _source_evidence(
    text: str,
    *,
    x: float = 20.0,
    y: float = 20.0,
    mediabox: bytes = b"[0 0 612 792]",
    repeated: bool = False,
) -> alignment.SourceTextEvidence:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    first = f"BT /F1 10 Tf {x:g} {y:g} Td ({escaped}) Tj ET".encode("ascii")
    content = first
    if repeated:
        content += (
            f"\nBT /F1 10 Tf {x:g} {y + 18:g} Td ({escaped}) Tj ET".encode(
                "ascii"
            )
        )
    evidence = alignment.extract_source_text_evidence(
        _single_page_source_reader_pdf(content, mediabox=mediabox)
    )
    assert evidence.usable is True
    assert evidence.refusal_code is None
    return evidence


def _page(
    evidence: alignment.SourceTextEvidence,
    value: str,
    *,
    item_type: str = "footer",
    bbox: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_page = evidence.pages[0]
    source_box = source_page.lines[0].bbox.to_dict()
    item: dict[str, Any] = {
        "id": "generic-running-owner",
        "type": item_type,
        "reading_order": 0,
        "value": value,
        "md": value,
        "bbox": source_box if bbox is None else bbox,
        "source": "native",
    }
    return [
        {
            "page_index": 1,
            "page_width": source_page.page_width,
            "page_height": source_page.page_height,
            "unit": "pt",
            "items": [item],
        }
    ]


def _span_bbox(
    evidence: alignment.SourceTextEvidence,
    start: int,
    end: int,
) -> dict[str, Any]:
    characters = [
        character
        for character in evidence.pages[0].characters[start:end]
        if character.bbox is not None
    ]
    left = min(character.bbox.x for character in characters if character.bbox)
    top = min(character.bbox.y for character in characters if character.bbox)
    right = max(
        character.bbox.x + character.bbox.width
        for character in characters
        if character.bbox
    )
    bottom = max(
        character.bbox.y + character.bbox.height
        for character in characters
        if character.bbox
    )
    return {
        "x": left,
        "y": top,
        "width": right - left,
        "height": bottom - top,
        "unit": "pt",
    }


def _nested_footer_page(
    evidence: alignment.SourceTextEvidence,
) -> list[dict[str, Any]]:
    pages = _page(evidence, "AlphaLedger |\n7 / 12")
    separator = "Alpha Ledger | 7 / 12".index("7")
    pages[0]["items"][0]["items"] = [
        {
            "type": "text",
            "value": "AlphaLedger |",
            "md": "AlphaLedger |",
            "bbox": _span_bbox(evidence, 0, separator),
            "source": "native",
        },
        {
            "type": "text",
            "value": "7 / 12",
            "md": "7 / 12",
            "bbox": _span_bbox(evidence, separator, len(evidence.pages[0].characters)),
            "source": "native",
        },
    ]
    return pages


@pytest.mark.parametrize(
    ("source_text", "owner_text", "expected", "x", "y", "mediabox"),
    (
        (
            "Alpha Ledger | https://example.test/r 7 / 12",
            "AlphaLedger | https://example.test/r\n7 / 12",
            "Alpha Ledger | https://example.test/r\n7 / 12",
            20.0,
            20.0,
            b"[0 0 612 792]",
        ),
        (
            "North Harbor Report 3 of 8",
            "NorthHarbor Report 3 of 8",
            "North Harbor Report 3 of 8",
            37.0,
            24.0,
            b"[0 0 720 900]",
        ),
    ),
)
def test_running_owner_recovers_only_source_proven_missing_word_boundaries(
    source_text: str,
    owner_text: str,
    expected: str,
    x: float,
    y: float,
    mediabox: bytes,
) -> None:
    evidence = _source_evidence(
        source_text,
        x=x,
        y=y,
        mediabox=mediabox,
    )
    pages = _page(evidence, owner_text)

    summary = alignment.align_pages_to_source(pages, evidence)

    item = pages[0]["items"][0]
    assert item["value"] == expected
    assert item["md"] == expected
    assert item["source"] == "native"
    assert summary.status == "selected"
    assert summary.selected_count == 1
    assert summary.selections[0].owner_type == "footer"
    assert summary.selections[0].method == "pdfium_source_space"
    assert summary.selections[0].selected_text == expected
    assert summary.selections[0].checks["encoded_u0020"] is True
    assert summary.selections[0].checks["space_geometry"] is True
    assert summary.selections[0].checks["same_page_coordinate_unit"] is True
    assert summary.selections[0].checks[
        "all_missing_spaces_encoded_u0020"
    ] is True
    assert summary.selections[0].checks["additive_whitespace_only"] is True
    assert summary.selections[0].checks["prior_whitespace_preserved"] is True
    assert item["source_alignment"]["source_sha256"] == evidence.source_sha256
    assert item["source_alignment"]["source_line_ids"]
    assert item["source_alignment"]["source_character_ids"]


@pytest.mark.parametrize(
    ("source_text", "owner_text", "item_type", "bbox_override", "repeated"),
    (
        # Partial source coverage is not a complete owner replacement.
        ("Alpha Ledger | 7 / 12", "AlphaLedger | 7 /", "footer", None, False),
        # Punctuation/codepoint differences are not whitespace repair.
        ("Alpha Ledger | 7 / 12", "AlphaLedger - 7 / 12", "footer", None, False),
        # Correct running text is already authoritative and remains unchanged.
        ("Alpha Ledger | 7 / 12", "Alpha Ledger | 7 / 12", "footer", None, False),
        # Non-running semantic owners do not enter this narrowly added path.
        ("Alpha Ledger | 7 / 12", "AlphaLedger | 7 / 12", "caption", None, False),
        # Two attributable identical source occurrences are ambiguous.
        ("Alpha Ledger | 7 / 12", "AlphaLedger | 7 / 12", "footer", None, True),
        # Missing geometry cannot prove ownership.
        ("Alpha Ledger | 7 / 12", "AlphaLedger | 7 / 12", "footer", {}, False),
        # A numerically similar bbox in another unit is not source geometry.
        (
            "Alpha Ledger | 7 / 12",
            "AlphaLedger | 7 / 12",
            "footer",
            {"x": 20.0, "y": 764.72, "width": 92.13, "height": 9.37, "unit": "px"},
            False,
        ),
        # Distant geometry cannot bind the source line to this owner.
        (
            "Alpha Ledger | 7 / 12",
            "AlphaLedger | 7 / 12",
            "footer",
            {"x": 400.0, "y": 300.0, "width": 50.0, "height": 10.0, "unit": "pt"},
            False,
        ),
    ),
)
def test_running_owner_spacing_uncertainty_fails_closed_without_content_loss(
    source_text: str,
    owner_text: str,
    item_type: str,
    bbox_override: dict[str, Any] | None,
    repeated: bool,
) -> None:
    evidence = _source_evidence(source_text, repeated=repeated)
    if repeated and bbox_override is None:
        boxes = [line.bbox for line in evidence.pages[0].lines]
        left = min(box.x for box in boxes)
        top = min(box.y for box in boxes)
        right = max(box.x + box.width for box in boxes)
        bottom = max(box.y + box.height for box in boxes)
        bbox_override = {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
            "unit": "pt",
        }
    pages = _page(
        evidence,
        owner_text,
        item_type=item_type,
        bbox=bbox_override,
    )
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 0
    assert pages == before
    assert pages[0]["items"][0]["value"] == owner_text
    assert "source_alignment" not in pages[0]["items"][0]


def test_running_owner_rejects_non_whitespace_source_selection_method() -> None:
    evidence = _source_evidence("Alpha Ledger")
    pages = _page(evidence, "Alpha-Ledger")
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 0
    assert pages == before


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("page_index", "1"),
        ("page_index", True),
        ("unit", "px"),
        ("page_width", float("nan")),
        ("page_height", 0.0),
    ),
)
def test_running_owner_requires_exact_page_and_coordinate_binding(
    field: str,
    value: Any,
) -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _page(evidence, "AlphaLedger | 7 / 12")
    pages[0][field] = value
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 0
    assert pages == before


def test_running_owner_requires_every_inserted_gap_to_have_encoded_space() -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    source_page = evidence.pages[0]
    characters = tuple(
        replace(character, space_supported=False)
        if character.raw_code_point == 0x20
        and character.character_index
        == next(
            candidate.character_index
            for candidate in source_page.characters
            if candidate.raw_code_point == 0x20
        )
        else character
        for character in source_page.characters
    )
    evidence = replace(
        evidence,
        pages=(replace(source_page, characters=characters),),
    )
    pages = _page(evidence, "AlphaLedger | 7 / 12")
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 0
    assert pages == before


def test_running_owner_never_enters_supplemental_deletion_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _page(evidence, "AlphaLedger | 7 / 12")

    def unexpected_suppression(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("running owner entered supplemental deletion logic")

    monkeypatch.setattr(
        alignment,
        "_supplemental_ocr_lineage_is_complete",
        unexpected_suppression,
    )

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 1
    assert pages[0]["items"][0]["value"] == "Alpha Ledger | 7 / 12"


def test_running_owner_repairs_only_the_unique_nested_native_fragment() -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _nested_footer_page(evidence)

    summary = alignment.align_pages_to_source(pages, evidence)

    owner = pages[0]["items"][0]
    assert summary.selected_count == 1
    assert owner["value"] == "Alpha Ledger |\n7 / 12"
    assert owner["md"] == "Alpha Ledger |\n7 / 12"
    assert [child["value"] for child in owner["items"]] == [
        "Alpha Ledger |",
        "7 / 12",
    ]
    assert [child["md"] for child in owner["items"]] == [
        "Alpha Ledger |",
        "7 / 12",
    ]
    assert summary.selections[0].checks["nested_contributor_closure"] is True
    assert owner["source_alignment"]["selection_id"] == summary.selections[0].id


@pytest.mark.parametrize(
    "mutation",
    (
        "conflicting-child",
        "stale-markdown",
        "non-native-child",
        "distant-child",
        "gap-at-child-boundary",
        "overbroad-child-geometry",
    ),
)
def test_running_owner_nested_partition_ambiguity_fails_closed(
    mutation: str,
) -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _nested_footer_page(evidence)
    owner = pages[0]["items"][0]
    first, second = owner["items"]
    if mutation == "conflicting-child":
        first["value"] = "AlphaXedger |"
        first["md"] = "AlphaXedger |"
    elif mutation == "stale-markdown":
        first["md"] = "stale child"
    elif mutation == "non-native-child":
        first["source"] = "ocr"
    elif mutation == "distant-child":
        first["bbox"] = {
            "x": 300.0,
            "y": 300.0,
            "width": 40.0,
            "height": 10.0,
            "unit": "pt",
        }
    elif mutation == "gap-at-child-boundary":
        first.update(value="Alpha", md="Alpha")
        second.update(value="Ledger |\n7 / 12", md="Ledger |\n7 / 12")
    elif mutation == "overbroad-child-geometry":
        first["bbox"] = deepcopy(owner["bbox"])
    else:  # pragma: no cover - closed parameter list
        raise AssertionError(mutation)
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.selected_count == 0
    assert pages == before


@pytest.mark.parametrize(
    "replay_mutation",
    (
        None,
        "drop-child",
        "add-child",
        "change-child",
        "change-unrelated-owner-field",
    ),
)
def test_terminal_running_replay_keeps_nested_footer_repair_and_identity(
    monkeypatch: pytest.MonkeyPatch,
    replay_mutation: str | None,
) -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    payload = _pipeline_payload()
    payload["document"]["sha256"] = evidence.source_sha256
    payload["pages"] = _nested_footer_page(evidence)
    payload["pages"][0].update(
        {
            "page_number": 1,
            "page_label": "1",
            "success": True,
            "warnings": [],
            "detected_images": [],
        }
    )
    payload["pages"][0]["items"][0]["id"] = "item-1"
    _add_fake_running_projection(payload)
    payload["pages"][0]["items"][0]["running_region"][
        "predecessor_type"
    ] = "footer"
    baseline_identity = running_regions.running_region_replay_identity(payload)
    prior_summary = deepcopy(payload["processing"]["running_regions"])
    observed: dict[str, Any] = {}

    def replay(
        candidate: dict[str, Any],
        candidate_ir: Any,
        _source_pdf_bytes: bytes,
        *,
        prior_summary: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], Any]:
        assert prior_summary == observed["prior_summary"]
        item = candidate["pages"][0]["items"][0]
        assert item["value"] == "Alpha Ledger |\n7 / 12"
        assert item["items"][0]["value"] == "Alpha Ledger |"
        committed = deepcopy(candidate)
        committed["processing"]["running_regions"] = deepcopy(
            observed["prior_summary"]
        )
        committed["pages"][0]["page_identity"] = deepcopy(
            payload["pages"][0]["page_identity"]
        )
        committed_item = committed["pages"][0]["items"][0]
        for key in (
            "layout_running_region_projected",
            "running_region_policy",
            "running_region",
        ):
            committed_item[key] = deepcopy(payload["pages"][0]["items"][0][key])
        committed_item["type"] = "footer"
        # A real terminal rebuild rekeys native evidence because the evidence
        # value changed.  Model that dependent identity transition instead of
        # copying a stale baseline sidecar unchanged.
        descriptor = committed_item["running_region"]
        descriptor["evidence_ids"] = ["aligned-evidence-1"]
        if replay_mutation == "drop-child":
            committed_item["items"].pop()
        elif replay_mutation == "add-child":
            extra = deepcopy(committed_item["items"][-1])
            extra.update(value="8 / 12", md="8 / 12")
            committed_item["items"].append(extra)
        elif replay_mutation == "change-child":
            committed_item["items"][0].update(
                value="Altered Ledger |",
                md="Altered Ledger |",
            )
        elif replay_mutation == "change-unrelated-owner-field":
            committed_item["parse_concerns"] = ["replay_changed_owner"]
        descriptor_model = SimpleNamespace(
            model_dump=lambda **_kwargs: deepcopy(descriptor)
        )
        rebuilt_ir = SimpleNamespace(
            elements=[
                SimpleNamespace(
                    id=descriptor["source_element_id"],
                    evidence_ids=[
                        *descriptor["evidence_ids"],
                        "owner-secondary-evidence",
                    ],
                    running_region=descriptor_model,
                    value=committed_item["value"],
                )
            ],
            evidence=[
                SimpleNamespace(
                    id="aligned-evidence-1",
                    element_id=descriptor["source_element_id"],
                    bbox_id=descriptor["bbox_id"],
                    value=committed_item["value"],
                    method=SimpleNamespace(value="native"),
                ),
                SimpleNamespace(
                    id="owner-secondary-evidence",
                    element_id=descriptor["source_element_id"],
                    bbox_id=descriptor["bbox_id"],
                    value="independent owner evidence",
                    method=SimpleNamespace(value="native"),
                ),
            ],
        )
        return committed, rebuilt_ir

    observed["prior_summary"] = prior_summary
    monkeypatch.setattr(running_regions, "replay_running_regions", replay)
    settings = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        text_integrity_font_audit_enabled=True,
        text_integrity_font_recovery_enabled=True,
        text_integrity_selective_span_ocr_enabled=True,
        text_reconciliation_enabled=True,
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
        text_integrity_source_alignment_enabled=True,
        layout_relationship_order_enabled=True,
        layout_running_regions_enabled=True,
    )
    ir_sink: dict[str, Any] = {}

    projected = pipeline_service._apply_terminal_source_text_alignment(
        payload,
        settings,
        source_pdf_bytes=b"%PDF-1.7\nsynthetic-running-replay\n%%EOF",
        source_text_evidence=evidence,
        source_sha256=evidence.source_sha256,
        input_kind=InputKind.PDF,
        internal_ir_sink=ir_sink,
    )

    if replay_mutation is not None:
        item = projected["pages"][0]["items"][0]
        assert projected["processing"]["source_text_alignment"]["status"] == (
            "unavailable"
        )
        assert item["value"] == "AlphaLedger |\n7 / 12"
        assert item["items"][0]["value"] == "AlphaLedger |"
        assert "source_alignment" not in item
        assert any(
            "Source text alignment failed closed" in warning
            for warning in projected["warnings"]
        )
        assert ir_sink == {}
        return

    item = projected["pages"][0]["items"][0]
    assert projected["processing"]["source_text_alignment"]["status"] == "selected"
    assert item["value"] == "Alpha Ledger |\n7 / 12"
    assert item["md"] == "Alpha Ledger |\n7 / 12"
    assert item["items"][0]["value"] == "Alpha Ledger |"
    assert projected["canonical_presentation"]["full"]["markdown"] == (
        "Alpha Ledger |\n\n7 / 12\n"
    )
    replay_identity = running_regions.running_region_replay_identity(
        projected,
        baseline_identity=baseline_identity,
        alignment_authorized_owner_ids=("item-1",),
    )
    assert replay_identity != baseline_identity
    assert item["running_region"]["evidence_ids"] == ["aligned-evidence-1"]
    assert pipeline_service._terminal_running_alignment_dependencies_are_closed(
        projected,
        ir_sink["ir"],
        ("item-1",),
    )
    assert pipeline_service._terminal_running_alignment_identity_matches(
        baseline_identity,
        replay_identity,
        ("item-1",),
    )
    assert ir_sink["ir"].elements[0].value == "Alpha Ledger |\n7 / 12"


def _repeated_running_identity_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = {
        "summary": {"status": "projected"},
        "regions": [
            {
                "page_offset": index,
                "item_offset": 0,
                "item_id": owner_id,
                "descriptor": {
                    "source_public_item_id": owner_id,
                    "evidence_ids": [f"evidence-old-{index}"],
                    "repetition_group_id": "running-repeat-old",
                    "repetition_page_indexes": [1, 2],
                    "role": "footer",
                },
            }
            for index, owner_id in enumerate(("footer-1", "footer-2"))
        ],
    }
    replayed = deepcopy(baseline)
    for index, region in enumerate(replayed["regions"]):
        descriptor = region["descriptor"]
        descriptor["evidence_ids"] = [f"evidence-new-{index}"]
        descriptor["repetition_group_id"] = "running-repeat-new"
    return baseline, replayed


def test_terminal_running_identity_accepts_closed_repeated_group_rekey() -> None:
    baseline, replayed = _repeated_running_identity_pair()

    assert pipeline_service._terminal_running_alignment_identity_matches(
        baseline,
        replayed,
        ("footer-1", "footer-2"),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "partial-authorization",
        "split-group",
        "changed-member-pages",
        "missing-owner",
    ),
)
def test_terminal_running_identity_rejects_open_repeated_group_rekey(
    mutation: str,
) -> None:
    baseline, replayed = _repeated_running_identity_pair()
    owner_ids = ("footer-1", "footer-2")
    if mutation == "partial-authorization":
        owner_ids = ("footer-1",)
    elif mutation == "split-group":
        replayed["regions"][1]["descriptor"]["repetition_group_id"] = (
            "running-repeat-split"
        )
    elif mutation == "changed-member-pages":
        replayed["regions"][1]["descriptor"]["repetition_page_indexes"] = [2]
    elif mutation == "missing-owner":
        owner_ids = ("footer-1", "footer-2", "footer-3")
    else:  # pragma: no cover - closed parameter list
        raise AssertionError(mutation)

    assert not pipeline_service._terminal_running_alignment_identity_matches(
        baseline,
        replayed,
        owner_ids,
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("too-many-children", "source_alignment_nested_items_limit"),
        ("oversized-child", "source_alignment_nested_items_size_limit"),
    ),
)
def test_running_owner_nested_preflight_refuses_before_transaction_copy(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    reason: str,
) -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _nested_footer_page(evidence)
    if mutation == "too-many-children":
        template = deepcopy(pages[0]["items"][0]["items"][0])
        pages[0]["items"][0]["items"] = [
            {**deepcopy(template), "value": f"child-{index}", "md": f"child-{index}"}
            for index in range(alignment.MAX_EVIDENCE_REFS + 1)
        ]
    elif mutation == "oversized-child":
        pages[0]["items"][0]["items"][0]["diagnostic"] = "x" * (
            alignment.MAX_REPORT_BYTES + 1
        )
    else:  # pragma: no cover - closed parameter list
        raise AssertionError(mutation)

    def unexpected_copy(_value: Any) -> Any:
        raise AssertionError("unbounded nested input reached transactional deepcopy")

    monkeypatch.setattr(alignment.copy, "deepcopy", unexpected_copy)

    summary = alignment.align_pages_to_source(pages, evidence)

    assert summary.status == "refused"
    assert summary.selected_count == 0
    assert summary.concerns[0]["reason"] == reason


def test_running_owner_spacing_reaches_public_ir_and_canonical_surfaces() -> None:
    evidence = _source_evidence("Alpha Ledger | 7 / 12")
    pages = _page(evidence, "AlphaLedger |\n7 / 12")

    summary = alignment.align_pages_to_source(pages, evidence)
    page = pages[0]
    page.update(
        {
            "page_number": 1,
            "page_label": "1",
            "success": True,
            "warnings": [],
            "detected_images": [],
        }
    )
    public: dict[str, Any] = {
        "schema_version": "1.0",
        "document": {
            "filename": "renamed-source.pdf",
            "mime_type": "application/pdf",
            "sha256": evidence.source_sha256,
            "page_count": 1,
            "image_count": 0,
        },
        "pages": pages,
        "processing": {
            "engine": "synthetic",
            "ocr_engine": "none",
            "ocr_languages": ["eng"],
            "duration_ms": 1.0,
            "source_text_alignment": summary.to_dict(),
        },
        "warnings": [],
    }
    ir_document = build_document_ir(deepcopy(public))
    public["canonical_presentation"] = build_canonical_presentation(
        ir_document
    ).model_dump(mode="json", exclude_none=True)

    validated = ParseResult.model_validate(public).model_dump(
        mode="json",
        exclude_none=True,
    )
    expected = "Alpha Ledger |\n7 / 12"
    owner = validated["pages"][0]["items"][0]
    assert owner["value"] == expected
    assert owner["md"] == expected
    assert owner["source_alignment"]["method"] == "pdfium_source_space"
    assert validated["canonical_presentation"]["full"]["markdown"] == (
        expected + "\n"
    )
    assert validated["canonical_presentation"]["full"]["text"] == expected + "\n"
    ir_owner = next(element for element in ir_document.elements if element.type == "footer")
    assert ir_owner.value == expected
    assert ir_owner.markdown == expected
