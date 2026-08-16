"""Bounded source-extraction assurance for P03-US06."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pdfplumber
import pytest

from app.services import form_semantics
from app.services.acroform_raw import RawAcroFormAuditError
from app.services.form_semantics import (
    FormEvidenceReport,
    FormSourcePage,
    SourceChar,
    SourceInteractiveControl,
    SourceVector,
    SourceWord,
    extract_form_evidence,
    project_form_semantics,
)
from app.services.ir import DocumentIR


def _word(index: int) -> SourceWord:
    return SourceWord(
        index=index,
        text="x",
        x0=200,
        top=20,
        x1=210,
        bottom=30,
        font_name="Helvetica",
        size=10,
        char_start=index,
        char_end=index + 1,
    )


def test_word_fragment_grouping_retains_wide_visible_space_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "HELLO WORLD"
    chars = tuple(
        SourceChar(
            index=index,
            text=character,
            x0=(12.0 + 3.0 * index if index < 5 else 27.0 if index == 5 else 36.0 + 3.0 * (index - 6)),
            top=10.0,
            x1=(15.0 + 3.0 * index if index < 5 else 36.0 if index == 5 else 39.0 + 3.0 * (index - 6)),
            bottom=28.0,
            font_name="Helvetica",
            size=18.0,
        )
        for index, character in enumerate(text)
    )
    page = FormSourcePage(
        page_index=1,
        width=100.0,
        height=100.0,
        chars=chars,
        words=(
            SourceWord(0, "HELLO", 12.0, 10.0, 27.0, 28.0, "Helvetica", 18.0, 0, 5),
            SourceWord(1, "WORLD", 36.0, 10.0, 51.0, 28.0, "Helvetica", 18.0, 6, 11),
        ),
        vectors=(),
        annotations=(),
        interactivity="static",
    )
    monkeypatch.setattr(
        form_semantics,
        "_spatial_chars",
        lambda _page, bbox: (
            text,
            text,
            bbox,
            (("character_range", 0, len(text)),),
        ),
    )

    fragments = form_semantics._text_fragments(page)  # noqa: SLF001
    label = form_semantics._control_label_for_box(  # noqa: SLF001
        page,
        form_semantics._ControlBox(  # noqa: SLF001
            bbox=(0.0, 9.0, 10.0, 20.0),
            source_objects=(("rect", 0, None),),
        ),
        fragments,
    )

    assert [fragment.text for fragment in fragments] == [text]
    assert label is not None and label[0] == text


def test_word_fragment_trailing_marker_preserves_a_dollar_label() -> None:
    chars = (
        SourceChar(0, "$", 0, 0, 1, 1, "F", 10),
        SourceChar(1, " ", 1, 0, 8, 1, "F", 10),
        SourceChar(2, "$", 8, 0, 9, 1, "F", 10),
    )
    page = FormSourcePage(
        page_index=1,
        width=20,
        height=20,
        chars=chars,
        words=(
            SourceWord(0, "$", 0, 0, 1, 1, "F", 10, 0, 1),
            SourceWord(1, "$", 8, 0, 9, 1, "F", 10, 2, 3),
        ),
        vectors=(),
        annotations=(),
        interactivity="static",
    )

    assert form_semantics._text_fragments(page) == (  # noqa: SLF001
        form_semantics._TextFragment(  # noqa: SLF001
            text="$",
            bbox=(0.0, 0.0, 1.0, 1.0),
        ),
    )


def test_public_sidecar_size_matches_compact_json_at_its_limit() -> None:
    sidecar = {
        "layout_forms_projected": True,
        "form_policy": "unicode-\u03bb-and-escaped-\"text\"",
        "form_group": {
            "id": "form_group:p1:g0",
            "page_index": 1,
            "bbox": [1.25, 2.5, 30.0, 40.0],
        },
        "form_labels": [
            {"id": "label:0", "text": "Name"},
            {"id": "label:1", "text": "Caf\u00e9\nline"},
        ],
        "form_controls": [],
        "relationships": [
            {
                "id": "relationship:0",
                "source_id": "label:0",
                "target_id": "control:0",
            }
        ],
    }
    expected = len(
        json.dumps(
            sidecar,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert (
        form_semantics._compact_public_sidecar_size(  # noqa: SLF001
            sidecar,
            limit=expected,
        )
        == expected
    )
    assert form_semantics._compact_public_sidecar_size(  # noqa: SLF001
        sidecar,
        limit=expected - 1,
    ) > (expected - 1)


def test_static_evidence_comparison_limit_is_inclusive() -> None:
    exact_word_count = (
        form_semantics.MAX_COMPARISONS_PER_PAGE - 2
    ) // 2
    vectors = (
        SourceVector(
            kind="rect",
            index=0,
            x0=10,
            top=10,
            x1=20,
            bottom=20,
            fill=False,
        ),
        SourceVector(
            kind="line",
            index=0,
            x0=0,
            top=0,
            x1=1,
            bottom=0,
            fill=False,
        ),
    )
    words = tuple(_word(index) for index in range(exact_word_count))
    exact_budget = form_semantics._ExtractionBudget(  # noqa: SLF001
        form_semantics.time.perf_counter()
    )

    assert (
        form_semantics._page_has_static_form_evidence(  # noqa: SLF001
            words,
            vectors,
            budget=exact_budget,
        )
        is False
    )
    assert (
        exact_budget.comparisons
        == form_semantics.MAX_COMPARISONS_PER_PAGE
    )

    over_budget = form_semantics._ExtractionBudget(  # noqa: SLF001
        form_semantics.time.perf_counter()
    )
    with pytest.raises(
        ValueError,
        match="comparison limit exceeded",
    ):
        form_semantics._page_has_static_form_evidence(  # noqa: SLF001
            (*words, _word(exact_word_count)),
            vectors,
            budget=over_budget,
        )


def test_static_evidence_rechecks_deadline_during_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vectors = tuple(
        SourceVector(
            kind="line",
            index=index,
            x0=0,
            top=0,
            x1=1,
            bottom=0,
            fill=False,
        )
        for index in range(256)
    )
    monkeypatch.setattr(
        form_semantics.time,
        "perf_counter",
        lambda: 3.0,
    )

    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        form_semantics._page_has_static_form_evidence(  # noqa: SLF001
            (),
            vectors,
            budget=form_semantics._ExtractionBudget(0.0),  # noqa: SLF001
        )


class _FakePage:
    def __init__(
        self,
        *,
        chars: list[dict[str, object]] | None = None,
        words: list[dict[str, object]] | None = None,
        curves: list[dict[str, object]] | None = None,
        edges: list[object] | None = None,
    ) -> None:
        self.width = 100.0
        self.height = 100.0
        self.rotation = 0
        self.page_obj = SimpleNamespace(attrs={}, pageid=1)
        self.chars = chars or []
        self.lines: list[dict[str, object]] = []
        self.rects: list[dict[str, object]] = []
        self.curves = curves or []
        self.edges = edges or []
        self._words = words or []

    def extract_words(self, **_kwargs: object) -> list[dict[str, object]]:
        return self._words


class _FakePdf:
    def __init__(self, page: _FakePage) -> None:
        self.pages = [page]
        self.doc = SimpleNamespace(catalog={})

    def close(self) -> None:
        return None


def _extract_fake(
    monkeypatch: pytest.MonkeyPatch,
    page: _FakePage,
) -> FormEvidenceReport:
    monkeypatch.setattr(
        form_semantics,
        "audit_acroform_raw",
        lambda _source, **_kwargs: None,
    )
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: _FakePdf(page),
    )
    return extract_form_evidence(b"%PDF-fake")


def test_raw_audit_runs_before_lossy_pdfplumber_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []

    def audited(source: bytes, **_kwargs: object) -> None:
        calls.append(source)

    monkeypatch.setattr(form_semantics, "audit_acroform_raw", audited)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: _FakePdf(_FakePage()),
    )

    report = extract_form_evidence(b"%PDF-production-order")

    assert calls == [b"%PDF-production-order"]
    assert report.interactivity == "none"


def test_raw_audit_refusal_prevents_lossy_parser_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_source: bytes, **_kwargs: object) -> None:
        raise RawAcroFormAuditError("malformed_pdf_structure")

    monkeypatch.setattr(form_semantics, "audit_acroform_raw", refuse)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: pytest.fail("pdfplumber must not run after refusal"),
    )

    with pytest.raises(
        RawAcroFormAuditError,
        match="structural audit failed closed",
    ):
        extract_form_evidence(b"%PDF-refused")


def test_raw_and_decoded_inspection_share_the_extraction_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"seconds": 0.0}
    raw_deadlines: list[float] = []
    decoded_deadlines: list[float] = []
    original_inspect = form_semantics.inspect_acroform

    def audited(
        _source: bytes,
        *,
        deadline_seconds: float,
    ) -> None:
        raw_deadlines.append(deadline_seconds)
        clock["seconds"] = 0.75

    def opened(_source: object) -> _FakePdf:
        clock["seconds"] = 1.0
        return _FakePdf(_FakePage())

    def inspected(**kwargs: object) -> object:
        decoded_deadlines.append(float(kwargs["deadline_seconds"]))
        return original_inspect(**kwargs)

    monkeypatch.setattr(
        form_semantics.time,
        "perf_counter",
        lambda: clock["seconds"],
    )
    monkeypatch.setattr(form_semantics, "audit_acroform_raw", audited)
    monkeypatch.setattr(pdfplumber, "open", opened)
    monkeypatch.setattr(form_semantics, "inspect_acroform", inspected)

    report = extract_form_evidence(b"%PDF-shared-deadline")

    assert report.interactivity == "none"
    assert raw_deadlines == [pytest.approx(2.0)]
    assert decoded_deadlines == [pytest.approx(1.0)]


def test_raw_audit_consuming_the_shared_deadline_stops_lossy_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"seconds": 0.0}

    def audited(
        _source: bytes,
        *,
        deadline_seconds: float,
    ) -> None:
        assert deadline_seconds == pytest.approx(2.0)
        clock["seconds"] = 2.001

    monkeypatch.setattr(
        form_semantics.time,
        "perf_counter",
        lambda: clock["seconds"],
    )
    monkeypatch.setattr(form_semantics, "audit_acroform_raw", audited)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda _source: pytest.fail(
            "lossy parser must not open after the shared deadline"
        ),
    )

    with pytest.raises(TimeoutError, match="exceeded its deadline"):
        extract_form_evidence(b"%PDF-expired-deadline")


def test_curve_point_limit_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_curve: dict[str, Any] = {
        "x0": 0,
        "top": 0,
        "x1": 10,
        "bottom": 10,
        "fill": False,
        "path": [("l", 0, 0)] * form_semantics.MAX_CURVE_POINTS_PER_OBJECT,
    }
    report = _extract_fake(
        monkeypatch,
        _FakePage(curves=[exact_curve]),
    )
    assert report.interactivity == "none"

    over_curve = {
        **exact_curve,
        "path": [
            ("l", 0, 0)
        ]
        * (form_semantics.MAX_CURVE_POINTS_PER_OBJECT + 1),
    }
    with pytest.raises(
        ValueError,
        match="curve object limit exceeded",
    ):
        _extract_fake(
            monkeypatch,
            _FakePage(curves=[over_curve]),
        )


def test_edge_objects_are_included_in_vector_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        ValueError,
        match="vector page limit exceeded",
    ):
        _extract_fake(
            monkeypatch,
            _FakePage(
                edges=[
                    object()
                    for _ in range(
                        form_semantics.MAX_VECTOR_OBJECTS_PER_PAGE + 1
                    )
                ]
            ),
        )


def test_word_without_character_provenance_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    word = {
        "text": "unowned",
        "x0": 10,
        "top": 10,
        "x1": 30,
        "bottom": 20,
        "fontname": "Helvetica",
        "size": 10,
    }
    with pytest.raises(
        ValueError,
        match="word provenance is unavailable",
    ):
        _extract_fake(
            monkeypatch,
            _FakePage(words=[word]),
        )


def test_source_text_encoding_errors_are_sanitized() -> None:
    with pytest.raises(ValueError, match="not encodable"):
        form_semantics._bounded_source_text("\ud800")  # noqa: SLF001


def test_projector_interactive_comparison_limit_is_inclusive() -> None:
    page = FormSourcePage(
        page_index=1,
        width=100,
        height=100,
        chars=(),
        words=(),
        vectors=(),
        annotations=(),
        interactivity="interactive",
    )
    control = SourceInteractiveControl(
        annotation_index=0,
        bbox=(10, 10, 10, 10),
        widget_ref_digest="a" * 64,
        field_ref_digest="b" * 64,
        field_name=None,
        control_type="checkbox",
        state="unchecked",
    )
    fragment = form_semantics._TextFragment(  # noqa: SLF001
        text="outside",
        bbox=(500, 500, 10, 10),
    )

    exact_budget = form_semantics._ProjectionBudget(  # noqa: SLF001
        started_at=form_semantics.time.perf_counter(),
        comparisons_by_page={},
    )
    exact_token = form_semantics._PROJECTION_BUDGET.set(  # noqa: SLF001
        exact_budget
    )
    try:
        assert (
            form_semantics._interactive_control_label(  # noqa: SLF001
                page,
                control,
                (fragment,) * form_semantics.MAX_COMPARISONS_PER_PAGE,
            )
            is None
        )
    finally:
        form_semantics._PROJECTION_BUDGET.reset(  # noqa: SLF001
            exact_token
        )
    assert exact_budget.comparisons_by_page == {
        1: form_semantics.MAX_COMPARISONS_PER_PAGE
    }

    over_budget = form_semantics._ProjectionBudget(  # noqa: SLF001
        started_at=form_semantics.time.perf_counter(),
        comparisons_by_page={},
    )
    over_token = form_semantics._PROJECTION_BUDGET.set(  # noqa: SLF001
        over_budget
    )
    try:
        with pytest.raises(
            form_semantics._ProjectionPageLimitError,  # noqa: SLF001
        ):
            form_semantics._interactive_control_label(  # noqa: SLF001
                page,
                control,
                (fragment,)
                * (form_semantics.MAX_COMPARISONS_PER_PAGE + 1),
            )
    finally:
        form_semantics._PROJECTION_BUDGET.reset(  # noqa: SLF001
            over_token
        )


def test_projector_deadline_rolls_back_the_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = DocumentIR(
        id="document",
        source_sha256="c" * 64,
        coordinate_systems=[],
        bboxes=[],
        pages=[],
        regions=[],
        elements=[],
        evidence=[],
    )
    report = FormEvidenceReport(
        report_version="p03-form-source-evidence-v1",
        policy_id="p03-form-semantics-v1",
        source_sha256=predecessor.source_sha256,
        pages=(),
        interactivity="none",
        concern_codes=(),
        extraction_ms=0,
    )
    monkeypatch.setattr(form_semantics, "DEADLINE_SECONDS", -1.0)

    projected = project_form_semantics(predecessor, report)

    assert predecessor.concerns == []
    assert projected is not predecessor
    assert tuple(concern.code for concern in projected.concerns) == (
        "form_projection_failed_closed",
    )


def test_projector_comparison_refusal_is_page_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = DocumentIR(
        id="document",
        source_sha256="d" * 64,
        coordinate_systems=[],
        bboxes=[],
        pages=[],
        regions=[],
        elements=[],
        evidence=[],
    )
    pages = tuple(
        FormSourcePage(
            page_index=page_index,
            width=100,
            height=100,
            chars=(),
            words=(),
            vectors=(),
            annotations=(),
            interactivity="none",
        )
        for page_index in (1, 2)
    )
    report = FormEvidenceReport(
        report_version="p03-form-source-evidence-v1",
        policy_id="p03-form-semantics-v1",
        source_sha256=predecessor.source_sha256,
        pages=pages,
        interactivity="none",
        concern_codes=(),
        extraction_ms=0,
    )

    def page_limited(
        _ir: DocumentIR,
        page_report: FormEvidenceReport,
        **_kwargs: object,
    ) -> tuple[object, ...]:
        page_index = page_report.pages[0].page_index
        if page_index == 1:
            raise form_semantics._ProjectionPageLimitError(1)  # noqa: SLF001
        return ()

    monkeypatch.setattr(
        form_semantics,
        "_key_value_candidates",
        page_limited,
    )

    projected = project_form_semantics(predecessor, report)

    assert predecessor.concerns == []
    assert tuple(
        (concern.code, concern.source_ref)
        for concern in projected.concerns
    ) == (("form_projection_failed_closed", "page:1"),)
