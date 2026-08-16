from __future__ import annotations

import math
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from app.services import selective_span_ocr as selective_ocr
from app.services.font_audit import audit_pdf_fonts
from app.services.font_recovery import recover_pdf_font_text
from app.services.ocr import (
    OCRLine,
    OCRToken,
    OCRUnavailableError,
    ImageRegion,
)
from app.services.selective_span_ocr import run_selective_span_ocr
from tests.fixtures.phase_02.font_recovery import build_fixture


PAGE_SIZES = {1: (612.0, 792.0)}


@dataclass
class _TickingClock:
    value: float = 0.0
    step: float = 0.001

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def _refused_case() -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    pdf_bytes = build_fixture("missing-program")
    audit = audit_pdf_fonts(pdf_bytes)
    recovery = recover_pdf_font_text(pdf_bytes, audit)
    return (
        pdf_bytes,
        audit.model_dump(mode="json", exclude_none=True),
        recovery.model_dump(mode="json", exclude_none=True),
    )


def _run(
    pdf_bytes: bytes,
    audit: dict[str, Any],
    recovery: dict[str, Any],
    *,
    page_sizes: dict[int, tuple[float, float]] | None = None,
    render_function: Callable[..., dict[int, list[ImageRegion]]],
    clock: Callable[[], float] | None = None,
):
    arguments: dict[str, Any] = {
        "tesseract_cmd": "test-tesseract-that-does-not-exist",
        "languages": ("eng",),
        "render_function": render_function,
    }
    if clock is not None:
        arguments["clock"] = clock
    return run_selective_span_ocr(
        pdf_bytes,
        audit,
        recovery,
        page_sizes or PAGE_SIZES,
        **arguments,
    )


def _render_factory(
    *,
    lines: list[OCRLine] | None = None,
    pixel_width: int = 470,
    pixel_height: int = 130,
    warnings: list[str] | None = None,
    calls: list[Any] | None = None,
) -> Callable[..., dict[int, list[ImageRegion]]]:
    def render(
        _pdf_bytes: bytes,
        requests: list[Any],
        **kwargs: Any,
    ) -> dict[int, list[ImageRegion]]:
        assert len(requests) == 1
        request = requests[0]
        if calls is not None:
            calls.append((request, kwargs))
        return {
            request.page_index: [
                ImageRegion(
                    page_index=request.page_index,
                    object_index=0,
                    bbox=dict(request.bbox),
                    pixel_width=pixel_width,
                    pixel_height=pixel_height,
                    area_ratio=0.01,
                    lines=deepcopy(lines or []),
                    warnings=list(warnings or []),
                    content_type="text",
                    region_role="content_region",
                    region_origin="pdf_page_render",
                    coordinate_unit="pt",
                )
            ]
        }

    return render


def _must_not_render(*_args: Any, **_kwargs: Any) -> dict[int, list[ImageRegion]]:
    raise AssertionError("selective renderer must not be called")


def _set_runs(
    audit: dict[str, Any],
    bboxes: list[dict[str, float]],
    *,
    page_indexes: list[int] | None = None,
) -> None:
    template = audit["findings"][0]["runs"][0]
    pages = page_indexes or [1] * len(bboxes)
    audit["findings"][0]["runs"] = [
        {
            **deepcopy(template),
            "page_index": page_index,
            "bbox": {**bbox, "unit": "pt"},
        }
        for page_index, bbox in zip(pages, bboxes, strict=True)
    ]


def test_only_refused_runs_route_while_recovered_and_healthy_neighbors_do_not() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    refused_finding = audit["findings"][0]
    recovered_finding = deepcopy(refused_finding)
    recovered_finding.update(
        {
            "font_ref": "object:6",
            "font_object_id": 6,
            "runs": [
                {
                    **deepcopy(refused_finding["runs"][0]),
                    "bbox": {
                        "x": 220.0,
                        "y": 56.0,
                        "width": 88.0,
                        "height": 20.0,
                        "unit": "pt",
                    },
                }
            ],
        }
    )
    audit["findings"].append(recovered_finding)

    recovered_font = deepcopy(audit["fonts"][0])
    recovered_font.update(
        {
            "font_ref": "object:6",
            "font_object_id": 6,
            "classification": "suspicious",
        }
    )
    healthy_font = deepcopy(audit["fonts"][0])
    healthy_font.update(
        {
            "font_ref": "object:7",
            "font_object_id": 7,
            "classification": "healthy",
        }
    )
    audit["fonts"].extend((recovered_font, healthy_font))
    recovery["fonts_recovered"] = 1
    recovery["runs"].append(
        {
            "evidence_id": "safe-neighbor",
            "page_index": 1,
            "run_index": 1,
            "font_ref": "object:6",
            "font_object_id": 6,
            "bbox": deepcopy(recovered_finding["runs"][0]["bbox"]),
            "original_text": "    ",
            "recovered_text": "SAFE",
            "glyphs": [],
            "confidence_basis": {"semantic_completion": False},
            "method": "embedded_truetype_cmap_identity",
        }
    )

    calls: list[Any] = []
    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(calls=calls),
    )

    assert len(calls) == 1
    request = calls[0][0]
    assert request.metadata == {
        "render_reason": "unresolved_font_span",
        "selective_span_id": report.outcomes[0].span_id,
        "font_ref": "object:5",
        "audit_run_index": 1,
    }
    assert report.known_span_count == report.terminal_outcome_count == 1
    assert report.outcomes[0].font_ref == "object:5"
    assert report.outcomes[0].refusal_reason_code == "embedded_program_missing"
    assert report.outcomes[0].status == "no_text"
    assert report.outcomes[0].reason_code == "selective_ocr_no_text"


def test_explicitly_unresolved_audit_run_routes_when_recovery_refused_it() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    audit["fonts"][0]["classification"] = "unresolved"
    audit["findings"][0]["health"] = "unresolved"
    calls: list[Any] = []

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(calls=calls),
    )

    assert len(calls) == 1
    assert report.known_span_count == report.terminal_outcome_count == 1
    assert report.outcomes[0].font_ref == audit["findings"][0]["font_ref"]
    assert report.outcomes[0].refusal_reason_code == (
        recovery["refusals"][0]["reason_code"]
    )


@pytest.mark.parametrize(
    "contradiction",
    (
        "recovered_and_refused",
        "conflicting_refusals",
        "object_identity_mismatch",
        "page_scope_mismatch",
    ),
)
def test_semantically_inconsistent_recovery_provenance_never_routes(
    contradiction: str,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    refusal = recovery["refusals"][0]
    if contradiction == "recovered_and_refused":
        recovery["runs"].append(
            {
                "evidence_id": "contradictory-safe-run",
                "page_index": 1,
                "run_index": 1,
                "font_ref": refusal["font_ref"],
                "font_object_id": refusal["font_object_id"],
                "bbox": deepcopy(audit["findings"][0]["runs"][0]["bbox"]),
                "original_text": "    ",
                "recovered_text": "SAFE",
                "glyphs": [],
                "confidence_basis": {"semantic_completion": False},
                "method": "embedded_truetype_cmap_identity",
            }
        )
    elif contradiction == "conflicting_refusals":
        conflicting = deepcopy(refusal)
        conflicting["reason_code"] = "different_refusal_authority"
        recovery["refusals"].append(conflicting)
    elif contradiction == "object_identity_mismatch":
        refusal["font_object_id"] += 100
    else:
        refusal["page_indexes"] = [2]

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_must_not_render,
    )

    assert report.status == "unavailable"
    assert report.known_span_count == report.terminal_outcome_count == 0
    assert report.rendered_span_count == report.rendered_pixel_count == 0
    assert [concern.code for concern in report.concerns] == [
        "invalid_source_report"
    ]


def test_audit_must_bind_to_the_exact_pdf_before_any_geometry_is_trusted() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    audit_before = deepcopy(audit)
    recovery_before = deepcopy(recovery)

    report = _run(
        pdf_bytes + b"\n% different exact source",
        audit,
        recovery,
        render_function=_must_not_render,
    )

    assert report.status == "unavailable"
    assert report.known_span_count == report.terminal_outcome_count == 0
    assert report.rendered_span_count == report.rendered_pixel_count == 0
    assert [concern.code for concern in report.concerns] == [
        "audit_source_mismatch"
    ]
    assert audit == audit_before
    assert recovery == recovery_before


def test_recovery_report_must_also_bind_to_the_exact_pdf() -> None:
    first_pdf, _first_audit, stale_recovery = _refused_case()
    second_pdf = first_pdf + b"\n% exact recovery binding control"
    matching_audit = audit_pdf_fonts(second_pdf).model_dump(
        mode="json",
        exclude_none=True,
    )

    report = _run(
        second_pdf,
        matching_audit,
        stale_recovery,
        render_function=_must_not_render,
    )

    assert report.status == "unavailable"
    assert report.known_span_count == report.terminal_outcome_count == 0
    assert [concern.code for concern in report.concerns] == [
        "recovery_source_mismatch"
    ]


def test_span_evidence_identity_is_scoped_to_the_exact_pdf() -> None:
    first_pdf, first_audit, first_recovery = _refused_case()
    second_pdf = first_pdf + b"\n% distinct exact PDF identity"
    second_audit_model = audit_pdf_fonts(second_pdf)
    second_recovery_model = recover_pdf_font_text(
        second_pdf,
        second_audit_model,
    )

    first = _run(
        first_pdf,
        first_audit,
        first_recovery,
        render_function=_render_factory(),
    )
    second = _run(
        second_pdf,
        second_audit_model.model_dump(mode="json", exclude_none=True),
        second_recovery_model.model_dump(mode="json", exclude_none=True),
        render_function=_render_factory(),
    )

    assert first.source_sha256 != second.source_sha256
    assert first.outcomes[0].source_bbox == second.outcomes[0].source_bbox
    assert first.outcomes[0].span_id != second.outcomes[0].span_id


def test_identical_targets_are_deduplicated_without_widening_or_extra_ocr() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    original_run = deepcopy(audit["findings"][0]["runs"][0])
    audit["findings"][0]["runs"] = [original_run, deepcopy(original_run)]
    calls: list[Any] = []

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(calls=calls),
    )

    assert len(calls) == 1
    assert report.known_span_count == report.terminal_outcome_count == 2
    assert report.rendered_span_count == 1
    assert [outcome.reason_code for outcome in report.outcomes] == [
        "selective_ocr_no_text",
        "duplicate_target",
    ]
    assert report.outcomes[1].status == "refused"
    assert report.outcomes[0].span_id in report.outcomes[1].reason_message
    assert calls[0][0].bbox == report.outcomes[0].source_bbox.model_dump(
        mode="json"
    )
    assert calls[0][0].bbox != report.outcomes[0].crop_bbox.model_dump(
        mode="json"
    )


@pytest.mark.parametrize(
    ("bbox", "reason_code"),
    (
        (
            {"x": 72.0, "y": 56.0, "width": 0.0, "height": 20.0},
            "invalid_source_bbox",
        ),
        (
            {"x": math.nan, "y": 56.0, "width": 88.0, "height": 20.0},
            "invalid_source_bbox",
        ),
        (
            {"x": 700.0, "y": 56.0, "width": 10.0, "height": 20.0},
            "source_bbox_off_page",
        ),
    ),
    ids=("zero-area", "non-finite", "off-page"),
)
def test_invalid_nonfinite_and_off_page_spans_are_terminal_concerns(
    bbox: dict[str, float],
    reason_code: str,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    _set_runs(audit, [bbox])

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_must_not_render,
    )

    assert report.status == "partial"
    assert report.known_span_count == report.terminal_outcome_count == 1
    assert report.rendered_span_count == report.candidate_count == 0
    assert report.outcomes[0].status == "refused"
    assert report.outcomes[0].reason_code == reason_code
    assert [concern.code for concern in report.concerns] == [reason_code]


@pytest.mark.parametrize("page_index", (0, -1))
def test_malformed_page_index_is_a_terminal_invalid_bbox_not_an_exception(
    page_index: int,
) -> None:
    _pdf_bytes, audit, recovery = _refused_case()
    audit["findings"][0]["runs"][0]["page_index"] = page_index

    outcomes, planned, concerns, known_span_count = selective_ocr._plan_targets(
        source_sha256=audit["source_sha256"],
        audit=audit,
        recovery=recovery,
        page_sizes=PAGE_SIZES,
    )

    assert known_span_count == 1
    assert planned == []
    assert len(outcomes) == 1
    assert outcomes[0].page_index == 1
    assert outcomes[0].status == "refused"
    assert outcomes[0].reason_code == "invalid_source_bbox"
    assert [concern.code for concern in concerns] == ["invalid_source_bbox"]


@pytest.mark.parametrize(
    ("bbox", "reason_code"),
    (
        (
            {"x": 50.0, "y": 50.0, "width": 500.0, "height": 500.0},
            "crop_pixel_limit",
        ),
        (
            {"x": 100.0, "y": 100.0, "width": 300.0, "height": 100.0},
            "page_area_limit",
        ),
    ),
    ids=("oversized-pixel-crop", "page-area"),
)
def test_oversized_crop_and_page_area_are_refused_before_allocation(
    bbox: dict[str, float],
    reason_code: str,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    _set_runs(audit, [bbox])

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_must_not_render,
    )

    outcome = report.outcomes[0]
    assert outcome.status == "refused"
    assert outcome.reason_code == reason_code
    assert outcome.cost is None
    assert outcome.candidates == []
    assert report.rendered_pixel_count == 0
    assert [concern.code for concern in report.concerns] == [reason_code]


def test_page_area_budget_is_cumulative_across_distinct_targets() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    _set_runs(
        audit,
        [
            {"x": 50.0, "y": 100.0, "width": 120.0, "height": 100.0},
            {"x": 250.0, "y": 100.0, "width": 120.0, "height": 100.0},
        ],
    )
    calls: list[Any] = []

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(calls=calls),
    )

    assert len(calls) == 1
    assert report.outcomes[0].cost.page_area_ratio < 0.05
    assert report.outcomes[1].status == "refused"
    assert report.outcomes[1].reason_code == "page_area_limit"


def test_realized_fractional_crop_cannot_exceed_page_area_budget() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    page_width = 612.37
    page_height = 792.29
    ideal_crop = {
        "x": 233.796,
        "y": 275.997,
        "width": 197.375,
        "height": 122.906,
    }
    _set_runs(
        audit,
        [
            {
                "x": ideal_crop["x"] + 3.0,
                "y": ideal_crop["y"] + 3.0,
                "width": ideal_crop["width"] - 6.0,
                "height": ideal_crop["height"] - 6.0,
            }
        ],
    )
    realized = {
        "x": 233.8,
        "y": 276.0,
        "w": 197.4,
        "h": 123.0,
    }

    def render(
        _pdf_bytes: bytes,
        requests: list[Any],
        **_kwargs: Any,
    ) -> dict[int, list[ImageRegion]]:
        request = requests[0]
        return {
            1: [
                ImageRegion(
                    page_index=1,
                    object_index=0,
                    bbox=dict(request.bbox),
                    pixel_width=987,
                    pixel_height=615,
                    render_pixel_width=987,
                    render_pixel_height=615,
                    rendered_crop_bbox=realized,
                    rendered_page_size=(page_width, page_height),
                    pixel_to_page_transform=(
                        realized["w"] / 987,
                        0.0,
                        0.0,
                        realized["h"] / 615,
                        realized["x"],
                        realized["y"],
                    ),
                    area_ratio=0.05,
                    lines=[],
                    content_type="text",
                    region_role="content_region",
                    region_origin="pdf_page_render",
                    coordinate_unit="pt",
                )
            ]
        }

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        page_sizes={1: (page_width, page_height)},
        render_function=render,
    )

    outcome = report.outcomes[0]
    assert outcome.status == "failed"
    assert outcome.reason_code == "actual_page_area_limit"
    assert outcome.cost is not None
    assert outcome.cost.rendered_area_points2 == pytest.approx(
        realized["w"] * realized["h"]
    )
    assert outcome.attempt is not None
    assert outcome.attempt.rendered_area_points2 == pytest.approx(
        realized["w"] * realized["h"]
    )
    assert report.rendered_span_count == 1
    assert report.rendered_area_points2 == pytest.approx(
        realized["w"] * realized["h"]
    )
    assert [concern.code for concern in report.concerns] == [
        "actual_page_area_limit"
    ]


def test_actual_per_page_target_bound_refuses_only_the_seventeenth_span() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    _set_runs(
        audit,
        [
            {
                "x": 10.0 + index * 10.0,
                "y": 10.0,
                "width": 1.0,
                "height": 1.0,
            }
            for index in range(17)
        ],
    )
    calls: list[Any] = []

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(
            pixel_width=35,
            pixel_height=35,
            calls=calls,
        ),
    )

    assert len(calls) == selective_ocr.MAX_SELECTIVE_PAGE_TARGETS == 16
    assert report.known_span_count == report.terminal_outcome_count == 17
    assert report.rendered_span_count == 16
    assert report.outcomes[-1].status == "refused"
    assert report.outcomes[-1].reason_code == "page_target_limit"


def test_document_target_and_total_pixel_budgets_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    small_boxes = [
        {"x": 10.0 + index * 20.0, "y": 10.0, "width": 1.0, "height": 1.0}
        for index in range(3)
    ]

    target_audit = deepcopy(audit)
    _set_runs(target_audit, small_boxes)
    monkeypatch.setattr(selective_ocr, "MAX_SELECTIVE_DOCUMENT_TARGETS", 2)
    target_calls: list[Any] = []
    target_report = _run(
        pdf_bytes,
        target_audit,
        recovery,
        render_function=_render_factory(
            pixel_width=35,
            pixel_height=35,
            calls=target_calls,
        ),
    )
    assert len(target_calls) == 2
    assert target_report.outcomes[-1].reason_code == "document_target_limit"

    monkeypatch.setattr(selective_ocr, "MAX_SELECTIVE_DOCUMENT_TARGETS", 64)
    monkeypatch.setattr(selective_ocr, "MAX_SELECTIVE_DOCUMENT_PIXELS", 2_000)
    pixel_audit = deepcopy(audit)
    _set_runs(pixel_audit, small_boxes[:2])
    pixel_calls: list[Any] = []
    pixel_report = _run(
        pdf_bytes,
        pixel_audit,
        recovery,
        render_function=_render_factory(
            pixel_width=35,
            pixel_height=35,
            calls=pixel_calls,
        ),
    )
    assert len(pixel_calls) == 1
    assert pixel_report.outcomes[-1].reason_code == "document_pixel_limit"
    assert {
        concern.code for concern in pixel_report.concerns
    } >= {"document_pixel_limit"}


def test_document_deadline_refuses_without_starting_a_crop() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    clock_values = iter((0.0, 61.0, 61.0))

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_must_not_render,
        clock=lambda: next(clock_values),
    )

    assert report.status == "partial"
    assert report.outcomes[0].status == "refused"
    assert report.outcomes[0].reason_code == "selective_ocr_deadline"
    assert report.rendered_span_count == report.rendered_pixel_count == 0
    assert [concern.code for concern in report.concerns] == [
        "selective_ocr_deadline"
    ]


@pytest.mark.parametrize(
    ("error_factory", "reason_code"),
    (
        (
            lambda: OCRUnavailableError("binary disappeared"),
            "selective_ocr_unavailable",
        ),
        (
            lambda: subprocess.TimeoutExpired(cmd="tesseract", timeout=15.0),
            "selective_ocr_timeout",
        ),
    ),
    ids=("unavailable", "timeout"),
)
def test_unavailable_and_timeout_fail_soft_with_terminal_concerns(
    error_factory: Callable[[], BaseException],
    reason_code: str,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    audit_before = deepcopy(audit)
    recovery_before = deepcopy(recovery)

    def fail(*_args: Any, **_kwargs: Any) -> dict[int, list[ImageRegion]]:
        raise error_factory()

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=fail,
    )

    assert report.status == "partial"
    assert report.outcomes[0].status == "failed"
    assert report.outcomes[0].reason_code == reason_code
    assert report.outcomes[0].cost is None
    assert report.outcomes[0].candidates == []
    assert report.rendered_span_count == report.candidate_count == 0
    assert [concern.code for concern in report.concerns] == [reason_code]
    assert audit == audit_before
    assert recovery == recovery_before


def test_actual_render_pixel_overrun_fails_soft_before_cost_or_candidates() -> None:
    pdf_bytes, audit, recovery = _refused_case()

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(
            pixel_width=4_001,
            pixel_height=1_000,
        ),
    )

    assert report.status == "partial"
    assert report.outcomes[0].status == "failed"
    assert report.outcomes[0].reason_code == "actual_render_pixel_limit"
    assert report.outcomes[0].cost is not None
    assert report.outcomes[0].cost.pixel_count == 4_001_000
    assert report.outcomes[0].candidates == []
    assert report.rendered_span_count == 1
    assert report.rendered_pixel_count == 4_001_000
    attempt = report.outcomes[0].attempt
    assert attempt is not None
    assert attempt.actual_pixel_count == 4_001_000
    assert attempt.status == "failed"
    assert [concern.code for concern in report.concerns] == [
        "actual_render_pixel_limit"
    ]


def test_post_render_timeout_retains_truthful_cost_and_pass_evidence() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    clock_values = iter((0.0, 0.0, 0.0, 31.0, 31.0))

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(),
        clock=lambda: next(clock_values),
    )

    outcome = report.outcomes[0]
    assert report.status == "partial"
    assert outcome.status == "failed"
    assert outcome.reason_code == "selective_ocr_timeout"
    assert outcome.cost is not None
    assert outcome.cost.elapsed_ms == pytest.approx(31_000.0)
    assert outcome.cost.passes_attempted == ["standard", "sparse"]
    assert outcome.cost.passes_completed == ["standard", "sparse"]
    assert outcome.attempt is not None
    assert outcome.attempt.status == "timed_out"
    assert [entry.status for entry in outcome.attempt.passes] == [
        "completed",
        "completed",
    ]


def test_malformed_ocr_candidate_is_discarded_to_concerns_without_escaping() -> None:
    pdf_bytes, audit, recovery = _refused_case()

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(lines=[object()]),  # type: ignore[list-item]
    )

    assert report.outcomes[0].status == "no_text"
    assert report.outcomes[0].candidates == []
    assert report.candidate_count == report.token_count == 0
    assert {concern.code for concern in report.concerns} >= {
        "invalid_ocr_candidate",
        "selective_ocr_no_text",
    }


def test_sparse_pass_failure_is_an_explicit_partial_candidate_concern() -> None:
    pdf_bytes, audit, recovery = _refused_case()
    line = OCRLine(
        text="STANDARD",
        bbox={"x": 72.0, "y": 56.0, "w": 20.0, "h": 8.0},
        confidence=0.91,
        word_count=1,
        ocr_pass="standard",
    )

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(
            lines=[line],
            warnings=[
                (
                    "Sparse-text OCR failed; standard OCR was retained: "
                    "malformed TSV"
                )
            ],
        ),
    )

    outcome = report.outcomes[0]
    assert report.status == "partial"
    assert outcome.status == "candidate"
    assert outcome.reason_code == "selective_ocr_partial_failure"
    assert [concern.code for concern in report.concerns] == [
        "selective_ocr_partial_failure"
    ]
    assert outcome.cost is not None
    assert outcome.cost.passes_attempted == ["standard", "sparse"]
    assert outcome.cost.passes_completed == ["standard"]
    assert outcome.attempt is not None
    assert [entry.status for entry in outcome.attempt.passes] == [
        "completed",
        "failed",
    ]


def test_primary_ocr_failure_does_not_claim_sparse_was_attempted() -> None:
    pdf_bytes, audit, recovery = _refused_case()

    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(
            warnings=["Rendered-region OCR failed: malformed TSV"],
        ),
    )

    outcome = report.outcomes[0]
    assert report.status == "partial"
    assert outcome.status == "failed"
    assert outcome.reason_code == "selective_ocr_failed"
    assert outcome.cost is not None
    assert outcome.cost.passes_attempted == ["standard"]
    assert outcome.cost.passes_completed == []
    assert outcome.attempt is not None
    assert [entry.status for entry in outcome.attempt.passes] == [
        "failed",
        "not_run",
    ]


def test_transform_mismatch_discards_candidates_and_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    line = OCRLine(
        text="must be discarded",
        bbox={"x": 75.0, "y": 58.0, "w": 60.0, "h": 9.0},
        confidence=0.99,
        word_count=3,
    )

    def invalid_transform(*_args: Any, **_kwargs: Any):
        raise ValueError("transform_mismatch")

    monkeypatch.setattr(selective_ocr, "_transforms", invalid_transform)
    report = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(lines=[line]),
    )

    assert report.status == "partial"
    assert report.outcomes[0].status == "failed"
    assert report.outcomes[0].reason_code == "transform_mismatch"
    assert report.outcomes[0].candidates == []
    assert report.candidate_count == report.token_count == 0
    assert [concern.code for concern in report.concerns] == [
        "transform_mismatch"
    ]


def test_success_records_crop_affines_dpi_pixels_pass_confidence_tokens_and_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_bytes, audit, recovery = _refused_case()
    token = OCRToken(
        text="SAFE",
        bbox={"x": 72.4, "y": 56.2, "w": 20.0, "h": 8.0},
        crop_pixel_bbox={"x": 17.0, "y": 16.0, "w": 100.0, "h": 40.0},
        confidence=0.93,
        ocr_pass="sparse",
        word_index=0,
    )
    line = OCRLine(
        text="SAFE",
        bbox={"x": 72.4, "y": 56.2, "w": 20.0, "h": 8.0},
        confidence=0.93,
        word_count=1,
        ocr_pass="sparse",
        tokens=[token],
    )
    monkeypatch.setattr(
        selective_ocr,
        "_engine_version",
        lambda _command: "tesseract 5.5.3",
    )
    calls: list[Any] = []

    first = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(lines=[line], calls=calls),
        clock=_TickingClock(),
    )
    second = _run(
        pdf_bytes,
        audit,
        recovery,
        render_function=_render_factory(lines=[line]),
        clock=_TickingClock(),
    )

    assert first == second
    assert first.status == "complete"
    assert first.known_span_count == first.terminal_outcome_count == 1
    assert first.rendered_span_count == first.candidate_count == 1
    assert first.token_count == 1
    outcome = first.outcomes[0]
    assert outcome.status == "candidate"
    assert outcome.reason_code is None
    assert outcome.source_bbox.model_dump(mode="json") == {
        "x": 72.0,
        "y": 56.0,
        "width": 88.0,
        "height": 20.0,
        "unit": "pt",
    }
    assert outcome.crop_bbox.model_dump(mode="json") == {
        "x": 69.0,
        "y": 53.0,
        "width": 94.0,
        "height": 26.0,
        "unit": "pt",
    }

    cost = outcome.cost
    assert cost is not None
    assert cost.requested_scale == 5.0
    assert cost.requested_dpi == cost.actual_dpi_x == cost.actual_dpi_y == 360.0
    assert (cost.page_width_points, cost.page_height_points) == (
        612.0,
        792.0,
    )
    assert (cost.pixel_width, cost.pixel_height, cost.pixel_count) == (
        470,
        130,
        61_100,
    )
    assert first.rendered_pixel_count == cost.pixel_count
    assert cost.rendered_area_points2 == 94.0 * 26.0
    assert first.rendered_area_points2 == cost.rendered_area_points2
    assert cost.page_area_ratio == pytest.approx((94.0 * 26.0) / (612.0 * 792.0))
    assert cost.requested_page_area_ratio == cost.page_area_ratio
    assert cost.realized_crop_bbox == outcome.crop_bbox
    assert cost.timeout_budget_seconds == 30.0
    assert cost.elapsed_ms == pytest.approx(1.0)
    assert cost.padding_points == 3.0
    assert cost.padding_clipped is False
    assert cost.engine == "tesseract"
    assert cost.engine_version == "tesseract 5.5.3"
    assert cost.languages == ["eng"]
    assert cost.passes_attempted == ["standard", "sparse"]
    assert cost.passes_completed == ["standard", "sparse"]
    assert cost.psm_by_pass == {"standard": 3, "sparse": 11}
    assert cost.transform_valid is True
    assert cost.crop_to_page_transform == [0.2, 0.0, 0.0, 0.2, 69.0, 53.0]
    assert cost.page_to_crop_transform == [5.0, 0.0, 0.0, 5.0, -345.0, -265.0]

    for corner in ((0.0, 0.0), (470.0, 0.0), (0.0, 130.0), (470.0, 130.0)):
        page_point = selective_ocr._apply_affine(
            cost.crop_to_page_transform,
            *corner,
        )
        round_trip = selective_ocr._apply_affine(
            cost.page_to_crop_transform,
            *page_point,
        )
        assert round_trip == pytest.approx(corner, abs=0.01)

    candidate = outcome.candidates[0]
    assert candidate.span_id == outcome.span_id
    assert candidate.text == "SAFE"
    assert candidate.confidence == 0.93
    assert candidate.word_count == 1
    assert candidate.ocr_pass == "sparse"
    assert candidate.selected is False
    assert candidate.method == "selective_pdf_tesseract_tsv"
    assert candidate.crop_pixel_bbox.model_dump(mode="json") == {
        "x": 17.0,
        "y": 16.0,
        "w": 100.0,
        "h": 40.0,
        "unit": "px",
    }
    assert len(candidate.tokens) == 1
    assert candidate.tokens[0].text == "SAFE"
    assert candidate.tokens[0].confidence == 0.93
    assert candidate.tokens[0].ocr_pass == "sparse"
    assert candidate.tokens[0].crop_pixel_bbox.model_dump(mode="json") == {
        **token.crop_pixel_bbox,
        "unit": "px",
    }
    assert candidate.tokens[0].method == "tesseract_tsv"

    request, kwargs = calls[0]
    # The shared PDF renderer accepts the source region and applies its own
    # 3-point padding once. The recorded crop and actual dimensions must agree
    # with that single padded render.
    assert request.bbox == outcome.source_bbox.model_dump(mode="json")
    assert request.bbox != outcome.crop_bbox.model_dump(mode="json")
    assert outcome.crop_bbox.width == outcome.source_bbox.width + 6.0
    assert outcome.crop_bbox.height == outcome.source_bbox.height + 6.0
    assert cost.pixel_width == outcome.crop_bbox.width * 5.0
    assert cost.pixel_height == outcome.crop_bbox.height * 5.0
    assert kwargs["render_scale"] == 5.0
    assert kwargs["max_render_pixels"] == 4_000_000
    assert kwargs["timeout_seconds"] == 15.0
    assert kwargs["languages"] == ["eng"]
