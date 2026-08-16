"""Focused algorithm-hardening checks for P03-US05 text-run semantics."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import pdfplumber
import pytest
from pydantic import ValidationError

from app.services.ir import build_document_ir
from app.services import source_text_alignment as alignment
import app.services.text_run_semantics as semantics


SOURCE_BYTES = b"%PDF-1.4\np03-us05-algorithm-hardening"
PAGE_WIDTH = 100.0
PAGE_HEIGHT = 100.0


def _bbox(
    *,
    x: float = 10.0,
    y: float = 10.0,
    width: float = 10.0,
    height: float = 10.0,
) -> semantics.SourceBBox:
    return semantics.SourceBBox(
        x=x,
        y=y,
        width=width,
        height=height,
    )


def _source_run(
    text: str,
    *,
    identifier: str = "source-run",
    bbox: semantics.SourceBBox | None = None,
) -> semantics.SourceRunEvidence:
    return semantics.SourceRunEvidence(
        id=identifier,
        page_index=1,
        line_index=0,
        text=text,
        bbox=bbox or _bbox(),
        font_name="Helvetica-Oblique",
        font_size=10.0,
        bold=False,
        italic=True,
        color=semantics.SourceColor(
            space="gray",
            components=(0.0,),
            raw_value=0.0,
        ),
        source_character_indexes=tuple(range(len(text))),
        change_state="unchanged",
        semantic_derivation="source_style",
    )


def _slot(
    text: str,
    *,
    target_path: tuple[str | int, ...] = ("value",),
    bbox: semantics.SourceBBox | None = None,
) -> semantics._TargetSlot:
    return semantics._TargetSlot(
        page_id="page-1",
        element_id="element-1",
        target_path=target_path,
        text=text,
        bbox=bbox or _bbox(x=8.0, y=8.0, width=20.0, height=20.0),
    )


def _assert_alignment_refused(
    run: semantics.SourceRunEvidence,
    slots: list[semantics._TargetSlot],
) -> None:
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_ambiguous",
    ) as caught:
        semantics._align_source_runs([run], slots)
    assert caught.value.code == "text_run_alignment_ambiguous"


@pytest.mark.parametrize(
    ("target", "expected_text"),
    [
        ('"', '"'),
        ("'", "'"),
    ],
)
def test_source_curly_double_quote_has_strict_and_adapter_fallback(
    target: str,
    expected_text: str,
) -> None:
    assert semantics._source_comparison_variants("\u201c") == ('"', "'")

    [mapped] = semantics._align_source_runs(
        [_source_run("\u201c")],
        [_slot(target)],
    )

    assert mapped.start == 0
    assert mapped.end == 1
    assert mapped.text == expected_text


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ('"', "'"),
        ("'", '"'),
    ],
)
def test_already_ascii_quote_kinds_remain_distinct(
    source: str,
    target: str,
) -> None:
    assert semantics._source_comparison_variants(source) == (source,)
    _assert_alignment_refused(_source_run(source), [_slot(target)])


def test_source_curly_fallback_union_refuses_competing_intervals() -> None:
    _assert_alignment_refused(
        _source_run("\u201c"),
        [_slot("\"'")],
    )


def test_nfkc_expansion_requires_a_complete_raw_character_boundary() -> None:
    [complete] = semantics._align_source_runs(
        [_source_run("fi")],
        [_slot("\ufb01")],
    )
    assert (complete.start, complete.end, complete.text) == (0, 1, "\ufb01")

    _assert_alignment_refused(
        _source_run("f"),
        [_slot("\ufb01")],
    )


def _public_bbox(
    *,
    x: float = 10.0,
    y: float = 10.0,
    width: float = 60.0,
    height: float = 20.0,
) -> dict[str, Any]:
    return {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "unit": "pt",
    }


def _document_with_scalar_and_child(
    *,
    scalar_text: str,
    child_text: str,
    scalar_bbox: dict[str, Any],
    child_bbox: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "hardening.pdf",
            "mime_type": "application/pdf",
            "sha256": hashlib.sha256(SOURCE_BYTES).hexdigest(),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": PAGE_WIDTH,
                "page_height": PAGE_HEIGHT,
                "unit": "pt",
                "success": True,
                "items": [
                    {
                        "id": "owner",
                        "type": "text",
                        "reading_order": 0,
                        "value": scalar_text,
                        "md": scalar_text,
                        "bbox": scalar_bbox,
                        "source": "native",
                        "confidence": 0.99,
                        "items": [
                            {
                                "text": child_text,
                                "bbox": child_bbox,
                            }
                        ],
                    }
                ],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
            "warnings": [],
        },
        "warnings": [],
    }


def _target_slots(
    *,
    scalar_text: str,
    child_text: str,
    scalar_bbox: dict[str, Any],
    child_bbox: dict[str, Any],
) -> list[semantics._TargetSlot]:
    ir = build_document_ir(
        _document_with_scalar_and_child(
            scalar_text=scalar_text,
            child_text=child_text,
            scalar_bbox=scalar_bbox,
            child_bbox=child_bbox,
        )
    )
    return semantics._target_slots_for_page(ir, ir.pages[0])


def test_exact_scalar_child_alias_canonicalizes_to_explicit_child() -> None:
    shared_bbox = _public_bbox()
    slots = _target_slots(
        scalar_text="Alias",
        child_text="Alias",
        scalar_bbox=shared_bbox,
        child_bbox=shared_bbox,
    )

    assert [slot.target_path for slot in slots] == [
        ("items", 0, "text")
    ]
    [mapped] = semantics._align_source_runs(
        [
            _source_run(
                "Alias",
                bbox=_bbox(x=12.0, y=12.0, width=20.0, height=8.0),
            )
        ],
        slots,
    )
    assert mapped.slot.target_path == ("items", 0, "text")


@pytest.mark.parametrize(
    ("child_text", "child_bbox"),
    [
        ("Alias child", _public_bbox()),
        (
            "Alias",
            _public_bbox(x=9.5, y=9.5, width=61.0, height=21.0),
        ),
    ],
)
def test_nonidentical_scalar_child_competition_fails_closed(
    child_text: str,
    child_bbox: dict[str, Any],
) -> None:
    slots = _target_slots(
        scalar_text="Alias",
        child_text=child_text,
        scalar_bbox=_public_bbox(),
        child_bbox=child_bbox,
    )
    assert {slot.target_path for slot in slots} == {
        ("value",),
        ("items", 0, "text"),
    }

    _assert_alignment_refused(
        _source_run(
            "Alias",
            bbox=_bbox(x=12.0, y=12.0, width=20.0, height=8.0),
        ),
        slots,
    )


@pytest.mark.parametrize("marker", ["-", "--", "=", "=="])
def test_one_and_two_character_setext_markers_are_escaped(
    marker: str,
) -> None:
    assert semantics._markdown_escape(f"label\n{marker}") == (
        f"label\n\\{marker}"
    )


class _FakePage:
    def __init__(
        self,
        *,
        chars: list[dict[str, Any]],
        rects: list[dict[str, Any]] | None = None,
        lines: list[dict[str, Any]] | None = None,
    ) -> None:
        self.width = PAGE_WIDTH
        self.height = PAGE_HEIGHT
        self.rotation = 0
        self.chars = chars
        self.rects = rects or []
        self.lines = lines or []


class _FakeDocument:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakeDocument:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None


def _fake_glyph(
    text: str,
    *,
    x0: float = 10.0,
    x1: float = 16.0,
    matrix: tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 10.0, 80.0),
) -> dict[str, Any]:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": 10.0,
        "bottom": 20.0,
        "size": 10.0,
        "fontname": "Helvetica-Oblique",
        "upright": True,
        "matrix": matrix,
        "non_stroking_color": 0.0,
    }


def _fake_rule(*, y: float) -> dict[str, Any]:
    return {
        "x0": 30.0,
        "x1": 60.0,
        "top": y,
        "bottom": y + 0.5,
        "fill": True,
        "non_stroking_color": 0.0,
    }


@pytest.mark.parametrize(
    ("failure_kind", "expected_concern"),
    [
        ("transform", "text_run_transform_unavailable"),
        ("geometry", "text_run_source_invalid"),
        ("rule_limit", "text_run_rule_limit"),
    ],
)
def test_extraction_rolls_back_only_the_bad_page(
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_concern: str,
) -> None:
    good_page = _FakePage(chars=[_fake_glyph("A")])
    if failure_kind == "transform":
        bad_page = _FakePage(
            chars=[
                _fake_glyph(
                    "B",
                    matrix=(1.0, 0.1, 0.0, 1.0, 10.0, 80.0),
                )
            ]
        )
    elif failure_kind == "geometry":
        bad_page = _FakePage(
            chars=[_fake_glyph("B", x0=10.0, x1=10.0)]
        )
    else:
        monkeypatch.setattr(semantics, "MAX_RULES_PER_PAGE", 1)
        bad_page = _FakePage(
            chars=[_fake_glyph("B")],
            rects=[_fake_rule(y=30.0), _fake_rule(y=40.0)],
        )

    fake_document = _FakeDocument([good_page, bad_page])
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: fake_document,
    )
    report = semantics.extract_text_run_evidence(
        SOURCE_BYTES,
        max_pages=2,
    )

    assert report.usable is True
    assert [page.status for page in report.pages] == [
        "projectable",
        "unavailable",
    ]
    assert report.pages[1].concern_code == expected_concern
    assert report.pages[1].run_ids == ()
    assert report.pages[1].rule_ids == ()
    assert report.runs
    assert {run.page_index for run in report.runs} == {1}
    assert {rule.page_index for rule in report.rules} <= {1}


def test_projection_concern_is_idempotent_across_reentry() -> None:
    predecessor = build_document_ir(
        _document_with_scalar_and_child(
            scalar_text="Plain",
            child_text="Child",
            scalar_bbox=_public_bbox(),
            child_bbox=_public_bbox(
                x=20.0,
                y=40.0,
                width=30.0,
                height=10.0,
            ),
        )
    )
    first = semantics.project_text_run_semantics(predecessor, None)
    second = semantics.project_text_run_semantics(first, None)

    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert [
        concern.code
        for concern in second.concerns
        if concern.code == "text_run_source_unsupported"
    ] == ["text_run_source_unsupported"]


def test_frozen_document_and_work_budget_constants_are_exact() -> None:
    assert semantics.MAX_SOURCE_CHARACTERS == 500_000
    assert semantics.MAX_RUNS_PER_DOCUMENT == 10_000
    assert semantics.MAX_RULES_PER_DOCUMENT == 10_000
    assert semantics.MAX_TARGET_CANDIDATES_PER_PAGE == 8_192
    assert semantics.MAX_TARGET_CANDIDATES_PER_DOCUMENT == 65_536
    assert semantics.MAX_TARGET_TRAVERSAL_PER_PAGE == 65_536
    assert semantics.MAX_TARGET_TEXT_BYTES_PER_PAGE == 1024 * 1024
    assert semantics.MAX_TARGET_TEXT_BYTES_PER_DOCUMENT == 8 * 1024 * 1024
    assert semantics.MAX_ALIGNMENT_COMPARISONS_PER_PAGE == 65_536
    assert semantics.MAX_ASSOCIATIONS_PER_PAGE == 65_536
    assert semantics.MAX_ALIGNMENT_TEXT_WORK_PER_PAGE == 8 * 1024 * 1024
    assert semantics.MAX_TEXT_BYTES_PER_RUN == 16 * 1024
    assert semantics.MAX_RUNS_PER_RULE == 64
    assert semantics.MAX_REPORT_BYTES == 8 * 1024 * 1024
    assert semantics.MAX_FONT_NAME_BYTES == 256


def _unusable_report_payload(*, character_count: int) -> dict[str, Any]:
    return {
        "source_sha256": hashlib.sha256(SOURCE_BYTES).hexdigest(),
        "usable": False,
        "refusal_code": "text_run_source_limit",
        "page_count": 0,
        "character_count": character_count,
        "candidate_rule_count": 0,
        "concerns": [
            {
                "code": "text_run_source_limit",
                "policy_id": semantics.TEXT_RUN_POLICY_ID,
            }
        ],
        "elapsed_ms": 0.0,
    }


def test_character_and_font_validators_accept_exact_frozen_maxima() -> None:
    exact_character_report = semantics.TextRunEvidence.model_validate(
        _unusable_report_payload(
            character_count=semantics.MAX_SOURCE_CHARACTERS,
        )
    )
    assert (
        exact_character_report.character_count
        == semantics.MAX_SOURCE_CHARACTERS
    )
    with pytest.raises(ValidationError):
        semantics.TextRunEvidence.model_validate(
            _unusable_report_payload(
                character_count=semantics.MAX_SOURCE_CHARACTERS + 1,
            )
        )

    run_payload = _source_run("A").model_dump(mode="json")
    exact_font_name = "\u00e9" * 128
    assert len(exact_font_name.encode("utf-8")) == 256
    run_payload["font_name"] = exact_font_name
    assert (
        semantics.SourceRunEvidence.model_validate(run_payload).font_name
        == exact_font_name
    )
    run_payload["font_name"] = f"{exact_font_name}x"
    with pytest.raises(ValidationError, match="font name"):
        semantics.SourceRunEvidence.model_validate(run_payload)


def _extract_from_fake_pages(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[_FakePage],
) -> semantics.TextRunEvidence:
    fake_document = _FakeDocument(pages)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: fake_document,
    )
    return semantics.extract_text_run_evidence(
        SOURCE_BYTES,
        max_pages=len(pages),
    )


def _glyph_pages(count: int) -> list[_FakePage]:
    return [
        _FakePage(chars=[_fake_glyph(chr(ord("A") + index))])
        for index in range(count)
    ]


def _rule_pages(count: int) -> list[_FakePage]:
    return [
        _FakePage(
            chars=[],
            rects=[_fake_rule(y=30.0)],
        )
        for _index in range(count)
    ]


def test_source_character_document_sum_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_SOURCE_CHARACTERS", 2)

    exact = _extract_from_fake_pages(monkeypatch, _glyph_pages(2))
    assert exact.usable is True
    assert exact.character_count == 2
    assert len(exact.runs) == 2

    overflow = _extract_from_fake_pages(monkeypatch, _glyph_pages(3))
    assert overflow.usable is False
    assert overflow.refusal_code == "text_run_source_limit"
    assert overflow.character_count == 2
    assert overflow.pages == ()
    assert overflow.runs == ()


def test_document_run_sum_exact_and_plus_one_is_page_transactional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_RUNS_PER_DOCUMENT", 2)

    exact = _extract_from_fake_pages(monkeypatch, _glyph_pages(2))
    assert exact.usable is True
    assert len(exact.runs) == 2
    assert {run.page_index for run in exact.runs} == {1, 2}

    overflow = _extract_from_fake_pages(monkeypatch, _glyph_pages(3))
    assert overflow.usable is True
    assert len(overflow.runs) == 2
    assert {run.page_index for run in overflow.runs} == {1, 2}
    assert overflow.pages[2].status == "unavailable"
    assert overflow.pages[2].concern_code == "text_run_source_limit"
    assert overflow.pages[2].run_ids == ()


def test_document_rule_sum_exact_and_plus_one_is_page_transactional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_RULES_PER_DOCUMENT", 2)

    exact = _extract_from_fake_pages(monkeypatch, _rule_pages(2))
    assert exact.usable is True
    assert len(exact.rules) == 2
    assert {rule.page_index for rule in exact.rules} == {1, 2}

    overflow = _extract_from_fake_pages(monkeypatch, _rule_pages(3))
    assert overflow.usable is True
    assert len(overflow.rules) == 2
    assert {rule.page_index for rule in overflow.rules} == {1, 2}
    assert overflow.pages[2].status == "unavailable"
    assert overflow.pages[2].concern_code == "text_run_rule_limit"
    assert overflow.pages[2].rule_ids == ()


def _document_with_scalar_values(
    values_by_page: list[list[str]],
) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for page_index, values in enumerate(values_by_page, 1):
        items = [
            {
                "id": f"p{page_index}-i{item_index}",
                "type": "text",
                "reading_order": item_index,
                "value": value,
                "md": value,
                "bbox": _public_bbox(),
                "source": "native",
                "confidence": 0.99,
            }
            for item_index, value in enumerate(values)
        ]
        pages.append(
            {
                "page_index": page_index,
                "page_number": page_index,
                "page_label": str(page_index),
                "page_width": PAGE_WIDTH,
                "page_height": PAGE_HEIGHT,
                "unit": "pt",
                "success": True,
                "items": items,
                "warnings": [],
            }
        )
    return {
        "schema_version": "1.0",
        "document": {
            "filename": "hardening.pdf",
            "mime_type": "application/pdf",
            "sha256": hashlib.sha256(SOURCE_BYTES).hexdigest(),
            "page_count": len(pages),
        },
        "pages": pages,
        "processing": {
            "engine": "fixture",
            "ocr_engine": "none",
            "ocr_languages": [],
            "duration_ms": 1,
            "warnings": [],
        },
        "warnings": [],
    }


def test_target_slot_page_count_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_TARGET_CANDIDATES_PER_PAGE", 2)

    exact_ir = build_document_ir(
        _document_with_scalar_values([["A", "B"]])
    )
    assert len(
        semantics._target_slots_for_page(exact_ir, exact_ir.pages[0])
    ) == 2

    overflow_ir = build_document_ir(
        _document_with_scalar_values([["A", "B", "C"]])
    )
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_limit",
    ):
        semantics._target_slots_for_page(
            overflow_ir,
            overflow_ir.pages[0],
        )


def test_attributable_supplemental_ocr_cannot_compete_for_native_runs() -> None:
    document = _document_with_scalar_values([["Styled value"]])
    bbox = _public_bbox()
    source_sha256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
    contributor = alignment.build_supplemental_ocr_contributor(
        source_document_identity=source_sha256,
        page_index=1,
        region_object_index=0,
        region_origin="pdf_page_render",
        region_role="page_source",
        line_index=0,
        ocr_pass="standard",
        coordinate_unit="pt",
        bbox=bbox,
        raw_text="Styled value",
        confidence=0.96,
    )
    assert contributor is not None
    document["pages"][0]["items"].append(
        {
            "id": "p1-i1",
            "type": "text",
            "reading_order": 1,
            "value": "Styled value",
            "md": "Styled value",
            "bbox": bbox,
            "source": "ocr",
            "confidence": 0.96,
            "label": "ocr_text",
            "raw_ocr_text": "Styled value",
            "parse_concerns": ["layout_omission_recovered_by_ocr"],
            "ocr_contributor": contributor,
        }
    )

    ir = build_document_ir(document)
    slots = semantics._target_slots_for_page(ir, ir.pages[0])
    assert len(slots) == 1
    native_legacy = next(
        element.properties["legacy_item"]
        for element in ir.elements
        if element.id == slots[0].element_id
    )
    assert native_legacy["source"] == "native"

    document["pages"][0]["items"][1]["ocr_contributor"]["id"] = (
        "ocr-contributor-" + "0" * 64
    )
    tampered_ir = build_document_ir(document)
    tampered_slots = semantics._target_slots_for_page(
        tampered_ir,
        tampered_ir.pages[0],
    )
    assert len(tampered_slots) == 2


def test_target_traversal_page_count_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_TARGET_TRAVERSAL_PER_PAGE", 2)

    exact_ir = build_document_ir(
        _document_with_scalar_values([["A", "B"]])
    )
    assert len(
        semantics._target_slots_for_page(exact_ir, exact_ir.pages[0])
    ) == 2

    overflow_ir = build_document_ir(
        _document_with_scalar_values([["A", "B", "C"]])
    )
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_limit",
    ):
        semantics._target_slots_for_page(
            overflow_ir,
            overflow_ir.pages[0],
        )


def test_target_text_page_sum_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_TARGET_TEXT_BYTES_PER_PAGE", 2)

    exact_ir = build_document_ir(
        _document_with_scalar_values([["a", "b"]])
    )
    exact_slots = semantics._target_slots_for_page(
        exact_ir,
        exact_ir.pages[0],
    )
    assert sum(len(slot.text.encode("utf-8")) for slot in exact_slots) == 2

    overflow_ir = build_document_ir(
        _document_with_scalar_values([["a", "bc"]])
    )
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_limit",
    ):
        semantics._target_slots_for_page(
            overflow_ir,
            overflow_ir.pages[0],
        )


def _project_scalar_pages(
    monkeypatch: pytest.MonkeyPatch,
    values: list[str],
) -> Any:
    evidence = _extract_from_fake_pages(
        monkeypatch,
        _glyph_pages(len(values)),
    )
    assert evidence.usable is True
    predecessor = build_document_ir(
        _document_with_scalar_values([[value] for value in values])
    )
    return semantics.project_text_run_semantics(predecessor, evidence)


@pytest.mark.parametrize(
    "limit_name",
    [
        "MAX_TARGET_CANDIDATES_PER_DOCUMENT",
        "MAX_TARGET_TEXT_BYTES_PER_DOCUMENT",
    ],
)
def test_target_document_sums_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
) -> None:
    monkeypatch.setattr(semantics, limit_name, 2)

    exact = _project_scalar_pages(monkeypatch, ["A", "B"])
    assert len(exact.text_runs) == 2
    assert not any(
        concern.code == "text_run_alignment_limit"
        for concern in exact.concerns
    )

    overflow = _project_scalar_pages(monkeypatch, ["A", "B", "C"])
    assert overflow.text_runs == []
    assert [
        concern.code
        for concern in overflow.concerns
        if concern.code == "text_run_alignment_limit"
    ] == ["text_run_alignment_limit"]


def test_alignment_comparison_budget_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        semantics,
        "MAX_ALIGNMENT_COMPARISONS_PER_PAGE",
        2,
    )
    budget = semantics._AlignmentBudget(started=time.perf_counter())

    budget.add_comparisons(2)
    assert budget.comparisons == 2
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_limit",
    ):
        budget.add_comparisons()


def test_alignment_text_work_budget_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        semantics,
        "MAX_ALIGNMENT_TEXT_WORK_PER_PAGE",
        2,
    )
    budget = semantics._AlignmentBudget(started=time.perf_counter())

    budget.add_text_work(2)
    assert budget.text_work == 2
    with pytest.raises(
        semantics._Refusal,
        match="text_run_alignment_limit",
    ):
        budget.add_text_work(1)


def test_source_run_text_byte_limit_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_TEXT_BYTES_PER_RUN", 2)

    exact = _source_run("ab")
    assert len(exact.text.encode("utf-8")) == 2

    with pytest.raises(ValidationError, match="text exceeds"):
        _source_run("abc")


def _association_glyph(index: int) -> semantics._Glyph:
    return semantics._Glyph(
        source_index=index,
        text=chr(ord("A") + index),
        x0=10.0,
        top=10.0,
        x1=16.0,
        bottom=20.0,
        baseline=20.0,
        font_name="Helvetica-Oblique",
        font_size=10.0,
        bold=False,
        italic=True,
        color=semantics.SourceColor(
            space="gray",
            components=(0.0,),
            raw_value=0.0,
        ),
    )


def _association_rule() -> semantics.SourceRuleEvidence:
    return semantics.SourceRuleEvidence(
        id="association-rule",
        page_index=1,
        source_object_kind="rect",
        source_object_index=0,
        bbox=_bbox(x=10.0, y=14.75, width=6.0, height=0.5),
        color=semantics.SourceColor(
            space="gray",
            components=(0.0,),
            raw_value=0.0,
        ),
        width=6.0,
        thickness=0.5,
    )


def test_rule_association_budget_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_ASSOCIATIONS_PER_PAGE", 2)
    exact_lines = [[_association_glyph(index)] for index in range(2)]

    runs, ambiguous = semantics._semantic_runs_for_page(
        source_sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
        page_index=1,
        lines=exact_lines,
        rules=[_association_rule()],
        started=time.perf_counter(),
    )
    assert len(runs) == 2
    assert ambiguous is True

    with pytest.raises(
        semantics._Refusal,
        match="text_run_rule_limit",
    ):
        semantics._semantic_runs_for_page(
            source_sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
            page_index=1,
            lines=[
                [_association_glyph(index)]
                for index in range(3)
            ],
            rules=[_association_rule()],
            started=time.perf_counter(),
        )


def _shared_rule_report(run_count: int) -> semantics.TextRunEvidence:
    source_sha256 = hashlib.sha256(SOURCE_BYTES).hexdigest()
    color = semantics.SourceColor(
        space="gray",
        components=(0.0,),
        raw_value=0.0,
    )
    rule = semantics.SourceRuleEvidence(
        id="shared-rule",
        page_index=1,
        source_object_kind="rect",
        source_object_index=0,
        bbox=_bbox(x=10.0, y=14.75, width=6.0, height=0.5),
        color=color,
        width=6.0,
        thickness=0.5,
    )
    runs = tuple(
        semantics.SourceRunEvidence(
            id=f"shared-rule-run-{index}",
            page_index=1,
            line_index=index,
            text=chr(ord("A") + index),
            bbox=_bbox(x=10.0, y=10.0, width=6.0, height=10.0),
            font_name="Helvetica",
            font_size=10.0,
            bold=False,
            italic=False,
            color=color,
            source_character_indexes=(index,),
            change_group_id=f"change-group-{index}",
            change_state="deleted",
            decorations=("strikethrough",),
            rule_ids=(rule.id,),
            semantic_derivation="same_color_midline_rule",
        )
        for index in range(run_count)
    )
    return semantics.TextRunEvidence(
        source_sha256=source_sha256,
        usable=True,
        page_count=1,
        character_count=run_count,
        candidate_rule_count=1,
        pages=(
            semantics.SourceSemanticsPage(
                page_index=1,
                page_width=PAGE_WIDTH,
                page_height=PAGE_HEIGHT,
                status="projectable",
                run_ids=tuple(run.id for run in runs),
                rule_ids=(rule.id,),
            ),
        ),
        runs=runs,
        rules=(rule,),
        elapsed_ms=0.0,
    )


def test_runs_per_rule_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(semantics, "MAX_RUNS_PER_RULE", 2)

    assert len(_shared_rule_report(2).runs) == 2
    with pytest.raises(ValidationError, match="per-rule run limit"):
        _shared_rule_report(3)


def _report_size_estimate(report: semantics.TextRunEvidence) -> int:
    return semantics._estimated_report_size(
        source_sha256=report.source_sha256,
        page_count=report.page_count,
        character_count=report.character_count,
        candidate_rule_count=report.candidate_rule_count,
        page_payload_bytes=sum(
            len(page.model_dump_json(exclude_none=True).encode("utf-8"))
            for page in report.pages
        ),
        page_item_count=len(report.pages),
        run_payload_bytes=sum(
            len(run.model_dump_json(exclude_none=True).encode("utf-8"))
            for run in report.runs
        ),
        run_item_count=len(report.runs),
        rule_payload_bytes=sum(
            len(rule.model_dump_json(exclude_none=True).encode("utf-8"))
            for rule in report.rules
        ),
        rule_item_count=len(report.rules),
    )


def test_report_document_byte_sum_exact_and_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = semantics.TextRunEvidence(
        source_sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
        usable=True,
        page_count=2,
        character_count=0,
        candidate_rule_count=0,
        pages=(
            semantics.SourceSemanticsPage(
                page_index=1,
                page_width=PAGE_WIDTH,
                page_height=PAGE_HEIGHT,
                status="unavailable",
                concern_code="text_run_source_unsupported",
            ),
            semantics.SourceSemanticsPage(
                page_index=2,
                page_width=PAGE_WIDTH,
                page_height=PAGE_HEIGHT,
                status="unavailable",
                concern_code="text_run_source_unsupported",
            ),
        ),
        elapsed_ms=0.0,
    )
    payload = report.model_dump(mode="json")
    exact_estimate = _report_size_estimate(report)
    one_page = report.model_copy(
        update={
            "page_count": 1,
            "pages": report.pages[:1],
        }
    )
    assert exact_estimate > _report_size_estimate(one_page)

    monkeypatch.setattr(semantics, "MAX_REPORT_BYTES", exact_estimate)
    assert semantics.TextRunEvidence.model_validate(payload).page_count == 2

    monkeypatch.setattr(semantics, "MAX_REPORT_BYTES", exact_estimate - 1)
    with pytest.raises(ValidationError, match="byte limit"):
        semantics.TextRunEvidence.model_validate(payload)


def test_line_overlap_uses_complete_maintained_interval_beyond_eight_glyphs(
) -> None:
    color = semantics.SourceColor(
        space="gray",
        components=(0.0,),
        raw_value=0.0,
    )

    def glyph(
        index: int,
        *,
        top: float,
        bottom: float,
    ) -> semantics._Glyph:
        return semantics._Glyph(
            source_index=index,
            text=chr(ord("A") + index),
            x0=10.0 + index * 2.0,
            top=top,
            x1=11.0 + index * 2.0,
            bottom=bottom,
            baseline=50.0,
            font_name="Helvetica",
            font_size=10.0,
            bold=False,
            italic=False,
            color=color,
        )

    glyphs = [
        glyph(index, top=40.0 + index * 5.0, bottom=50.0 + index * 5.0)
        for index in range(10)
    ]
    glyphs.append(glyph(10, top=40.0, bottom=45.0))

    lines = semantics._cluster_lines(
        glyphs,
        started=semantics.time.perf_counter(),
    )

    assert len(lines) == 1
    assert [item.source_index for item in lines[0]] == list(range(11))
