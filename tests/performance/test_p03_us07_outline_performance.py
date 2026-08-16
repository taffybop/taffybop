"""Performance, resource, and evidence-contract checks for P03-US07."""

from __future__ import annotations

import gc
import hashlib
import tracemalloc
import weakref
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Self

import pdfplumber
import pytest
from pydantic import ValidationError

from app.services import outline_structure as outlines
from tests.benchmarks import outline_structure_metrics as metrics
from tests.fixtures.phase_03.outline_structure import synthetic as synthetic_fixtures


def test_fixed_sources_settings_and_local_only_policy_are_exact() -> None:
    custody = metrics._source_custody(metrics.WORKSPACE)

    assert set(custody) == {
        "component-datasheet",
        "settlement-agreement",
    }
    assert all(record["exact_match"] for record in custody.values())
    assert metrics.M0_REFERENCES == {
        "component-datasheet": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 10.56,
            "peak_rss_mib": 1_840.3,
        },
        "settlement-agreement": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 6.48,
            "peak_rss_mib": 1_410.7,
        },
    }
    assert metrics.HOSTED_USAGE == {
        "hosted_requests": 0,
        "hosted_tokens": 0,
        "hosted_cost_usd": 0,
    }
    assert metrics._settings_delta() == {
        "changed_fields": ["layout_outline_structure_enabled"],
        "flag_off": {"layout_outline_structure_enabled": False},
        "flag_on": {"layout_outline_structure_enabled": True},
        "accepted_predecessor_flags_enabled": True,
    }
    disabled = metrics._settings(False)
    enabled = metrics._settings(True)
    assert disabled.layout_table_captions_enabled is True
    assert disabled.layout_visual_relationships_enabled is True
    assert disabled.layout_source_notes_enabled is True
    assert disabled.layout_relationship_order_enabled is True
    assert disabled.layout_text_run_semantics_enabled is True
    assert disabled.layout_forms_enabled is True
    assert disabled.layout_outline_structure_enabled is False
    assert enabled.layout_outline_structure_enabled is True


def test_source_custody_observes_page_count_instead_of_copying_expected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "_observed_pdf_page_count", lambda _source: 99)

    custody = metrics._source_custody(
        metrics.WORKSPACE,
        ("component-datasheet",),
    )["component-datasheet"]

    assert custody["expected"]["page_count"] == 3
    assert custody["observed"]["page_count"] == 99
    assert custody["exact_match"] is False


def test_inclusive_p95_is_the_policy_nearest_rank_not_interpolation() -> None:
    assert metrics._inclusive_p95(list(range(1, 21))) == 19
    assert metrics._inclusive_p95([1, 2, 3, 4, 5]) == 5
    assert metrics._inclusive_p95([4.0]) == 4.0
    with pytest.raises(ValueError, match="p95 requires"):
        metrics._inclusive_p95([])


def test_semantic_determinism_removes_exactly_seven_timing_paths() -> None:
    payload = {
        "processing": {
            "duration_ms": 12,
            "form_semantics": {
                "extraction_ms": 1.0,
                "projection_ms": 2.0,
                "total_ms": 3.0,
                "preserved": "form",
            },
            "outline_structure": {
                "extraction_ms": 4.0,
                "projection_ms": 5.0,
                "total_ms": 9.0,
                "preserved": "outline",
            },
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }

    assert metrics._semantic_payload(payload) == {
        "processing": {
            "form_semantics": {"preserved": "form"},
            "outline_structure": {"preserved": "outline"},
            "other": {"duration_ms": 99},
        },
        "duration_ms": 88,
    }
    assert metrics.TIMING_PATHS_REMOVED == (
        "processing.duration_ms",
        "processing.form_semantics.extraction_ms",
        "processing.form_semantics.projection_ms",
        "processing.form_semantics.total_ms",
        "processing.outline_structure.extraction_ms",
        "processing.outline_structure.projection_ms",
        "processing.outline_structure.total_ms",
    )


def test_timing_profile_verifies_tracing_and_releases_sample_outputs() -> None:
    class Payload:
        pass

    references: list[weakref.ReferenceType[Payload]] = []
    samples = metrics._profile_timing(
        Payload,
        warmup_count=0,
        sample_count=3,
        after_sample=lambda result: references.append(weakref.ref(result)),
    )
    gc.collect()

    assert len(samples) == 3
    assert all(reference() is None for reference in references)

    tracemalloc.start()
    try:
        with pytest.raises(RuntimeError, match="requires tracemalloc"):
            metrics._profile_timing(
                Payload,
                warmup_count=0,
                sample_count=1,
            )
    finally:
        tracemalloc.stop()


def test_rss_normalization_is_platform_exact() -> None:
    assert metrics._rss_bytes_from_maxrss(123, platform_name="darwin") == 123
    assert metrics._rss_bytes_from_maxrss(123, platform_name="linux") == (123 * 1_024)


def test_paired_gate_uses_current_predecessor_dual_ceilings_and_rss() -> None:
    off = [{"wall_seconds": 10.0, "peak_rss_bytes": 1_000} for _ in range(5)]
    on = [
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 9.0, "peak_rss_bytes": 900},
        {"wall_seconds": 10.7, "peak_rss_bytes": 1_100},
    ]

    summary = metrics._paired_performance_summary(
        "component-datasheet",
        off,
        on,
    )

    assert summary["pair_count"] == 5
    assert summary["quantile_method"] == ("empirical_p95_inclusive_nearest_rank")
    assert summary["gate_value"] == ("p95_of_clipped_nonnegative_paired_overhead")
    assert summary["paired_signed_wall_seconds_deltas"] == [
        -1.0,
        -1.0,
        -1.0,
        -1.0,
        0.7,
    ]
    assert summary["paired_nonnegative_overhead_seconds"] == [
        0.0,
        0.0,
        0.0,
        0.0,
        0.7,
    ]
    assert summary["p95_signed_delta_seconds"] == pytest.approx(0.7)
    assert summary["p95_nonnegative_overhead_seconds"] == pytest.approx(0.7)
    assert summary["current_paired_predecessor_p95_seconds"] == 10.0
    assert summary["five_percent_ceiling_seconds"] == 0.5
    assert summary["absolute_ceiling_seconds"] == 0.528
    assert summary["effective_ceiling_seconds"] == 0.5
    assert summary["within_both_ceilings"] is False
    assert summary["maximum_peak_rss_delta_bytes"] == 100
    assert summary["within_peak_rss_delta_ceiling"] is True
    assert [metrics._paired_states(index) for index in range(5)] == [
        (False, True),
        (True, False),
        (False, True),
        (True, False),
        (False, True),
    ]

    with pytest.raises(ValueError, match="exactly 5 pairs"):
        metrics._paired_performance_summary(
            "component-datasheet",
            off[:-1],
            on[:-1],
        )
    with pytest.raises(ValueError, match="exactly 5 pairs"):
        metrics._paired_performance_summary(
            "component-datasheet",
            [*off, off[0]],
            [*on, on[0]],
        )


def test_comparison_capture_uses_production_metrics_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = object()
    evidence = object()

    def project(
        candidate: object,
        _evidence: object,
        metrics: dict[str, Any] | None = None,
    ) -> object:
        assert metrics is not None
        metrics["comparisons_by_page"] = {1: 7}
        return candidate

    monkeypatch.setattr(outlines, "project_outline_structure", project)
    comparisons, projected = metrics._capture_projection_comparisons(
        predecessor,  # type: ignore[arg-type]
        evidence,
    )

    assert comparisons == {1: 7}
    assert projected is predecessor


@pytest.mark.parametrize(
    ("case", "ceiling"),
    [
        ("component-datasheet", 0.250),
        ("settlement-agreement", 0.150),
    ],
)
def test_real_extraction_meets_latency_allocation_size_and_oracle_gates(
    case: str,
    ceiling: float,
) -> None:
    measured = metrics.generate_extraction_metrics(case)

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["clock"] == "time.perf_counter_ns"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["timing_tracemalloc_state_verified"] is True
    assert measured["timing_results_retained"] is False
    assert measured["gc_collection_outside_timed_interval"] is True
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["allocation_warmup_count"] == 1
    assert measured["allocation_sample_count"] == 5
    assert len(measured["peak_allocated_samples_bytes"]) == 5
    assert measured["tracemalloc_reset_between_samples"] is True
    assert 0 < measured["p50_seconds"] <= measured["p95_seconds"]
    assert measured["p95_seconds"] <= measured["max_seconds"]
    assert measured["p95_ceiling_seconds"] == ceiling
    assert measured["within_p95_ceiling"] is True, {
        "p95_seconds": measured["p95_seconds"],
        "samples_seconds": measured["samples_seconds"],
    }
    assert measured["peak_allocation_ceiling_bytes"] == 64 * 1024 * 1024
    assert measured["within_peak_allocation_ceiling"] is True
    assert measured["report_size_ceiling_bytes"] == 8 * 1024 * 1024
    assert measured["within_report_size_ceiling"] is True
    assert measured["semantic_deterministic"] is True
    assert measured["source_sha256_exact"] is True
    assert measured["source_report_exact"] is True
    assert measured["reviewed_counts"] == metrics.SOURCE_REPORTS[case]["counts"]
    assert {key: measured[key] for key in metrics.HOSTED_USAGE} == metrics.HOSTED_USAGE


@pytest.mark.parametrize(
    "case",
    ["component-datasheet", "settlement-agreement"],
)
def test_real_projection_meets_latency_allocation_and_comparison_gates(
    case: str,
) -> None:
    measured = metrics.generate_projection_metrics(case)

    assert measured["warmup_count"] == 2
    assert measured["sample_count"] == 20
    assert len(measured["samples_seconds"]) == 20
    assert measured["clock"] == "time.perf_counter_ns"
    assert measured["timing_tracemalloc_enabled"] is False
    assert measured["timing_tracemalloc_state_verified"] is True
    assert measured["timing_results_retained"] is False
    assert measured["allocation_measured_in_separate_call"] is True
    assert measured["allocation_warmup_count"] == 1
    assert measured["allocation_sample_count"] == 5
    assert len(measured["peak_allocated_samples_bytes"]) == 5
    assert measured["p95_ceiling_seconds"] == 0.050
    assert measured["within_p95_ceiling"] is True, {
        "p95_seconds": measured["p95_seconds"],
        "samples_seconds": measured["samples_seconds"],
    }
    assert measured["peak_allocation_ceiling_bytes"] == 64 * 1024 * 1024
    assert measured["within_peak_allocation_ceiling"] is True
    assert measured["semantic_deterministic"] is True
    assert measured["predecessor_unmodified"] is True
    assert measured["repeated_projection_idempotent"] is True
    assert measured["comparison_instrumentation_separate_from_timing"] is True
    assert measured["comparison_ceiling_per_page"] == 65_536
    assert measured["within_comparison_ceiling"] is True
    assert measured["maximum_comparisons_on_page"] > 0
    assert all(
        0 <= count <= 65_536 for count in measured["comparisons_by_page"].values()
    )
    assert measured["instrumented_projection_semantically_equal"] is True
    assert measured["outline_summary_exact"] is True
    assert measured["outline_summary"] == (metrics.EXPECTED_OUTLINE_SUMMARIES[case])
    assert {key: measured[key] for key in metrics.HOSTED_USAGE} == metrics.HOSTED_USAGE


def _source_observations(source: bytes) -> dict[str, int]:
    with pdfplumber.open(BytesIO(source)) as document:
        characters = [len(page.chars) for page in document.pages]
        words = [len(page.extract_words()) for page in document.pages]
    report = outlines.extract_outline_evidence(source, max_pages=100)
    return {
        "MAX_SOURCE_CHARACTERS_PER_PAGE": max(characters),
        "MAX_SOURCE_CHARACTERS_PER_DOCUMENT": sum(characters),
        "MAX_SOURCE_WORDS_PER_PAGE": max(words),
        "MAX_SOURCE_WORDS_PER_DOCUMENT": sum(words),
        "MAX_MARKER_CANDIDATES_PER_PAGE": max(
            (len(page.markers) for page in report.pages),
            default=0,
        ),
        "MAX_MARKER_CANDIDATES_PER_DOCUMENT": report.counts.marker_candidates,
    }


def _two_page_outline_pdf() -> bytes:
    def content(lines: tuple[tuple[float, float, str], ...]) -> bytes:
        commands = [b"BT /F1 12 Tf"]
        for x, y, value in lines:
            commands.append(
                f"1 0 0 1 {x:.3f} {y:.3f} Tm (".encode("ascii")
                + synthetic_fixtures._pdf_escape(value)
                + b") Tj"
            )
        commands.append(b"ET")
        return b"\n".join(commands)

    first_page = content(
        (
            (72, 720, "- Root one with deliberately longer source text"),
            (90, 700, "* Child one"),
            (90, 680, "* Child two"),
            (72, 660, "- Root two"),
        )
    )
    second_page = content(
        (
            (72, 720, "1. First"),
            (72, 700, "2. Second"),
            (72, 680, "3. Third"),
        )
    )
    return synthetic_fixtures._assemble_pdf(
        (
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>"
            ),
            synthetic_fixtures._stream(first_page),
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>"
            ),
            synthetic_fixtures._stream(second_page),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        )
    )


@pytest.mark.parametrize(
    ("attribute", "scope"),
    [
        ("MAX_SOURCE_CHARACTERS_PER_PAGE", "page"),
        ("MAX_SOURCE_CHARACTERS_PER_DOCUMENT", "document"),
        ("MAX_SOURCE_WORDS_PER_PAGE", "page"),
        ("MAX_SOURCE_WORDS_PER_DOCUMENT", "document"),
        ("MAX_MARKER_CANDIDATES_PER_PAGE", "page"),
        ("MAX_MARKER_CANDIDATES_PER_DOCUMENT", "document"),
    ],
)
def test_production_source_count_limits_accept_exact_and_refuse_plus_one(
    attribute: str,
    scope: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = metrics._verified_source_bytes(
        metrics.WORKSPACE,
        "component-datasheet",
    )
    observed = _source_observations(source)[attribute]
    assert observed > 0

    monkeypatch.setattr(outlines, attribute, observed)
    exact = outlines.extract_outline_evidence(source, max_pages=100)
    assert exact.status == "available"

    monkeypatch.setattr(outlines, attribute, observed - 1)
    maximum_plus_one = outlines.extract_outline_evidence(source, max_pages=100)
    if scope == "page":
        assert maximum_plus_one.status == "available"
        assert any(
            "outline_source_limit" in page.concern_codes
            for page in maximum_plus_one.pages
        )
    else:
        assert maximum_plus_one.status == "refused"
        assert maximum_plus_one.concern_codes == ("outline_source_limit",)


def test_page_local_source_overflow_preserves_and_projects_other_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _two_page_outline_pdf()
    with pdfplumber.open(BytesIO(source)) as document:
        character_counts = [len(page.chars) for page in document.pages]
    assert character_counts[0] > character_counts[1] > 0

    parsed = metrics.parse_document(
        source,
        "two-page-outline.pdf",
        metrics._settings(False),
    )
    predecessor = metrics.build_document_ir(
        parsed.model_dump(mode="json", exclude_none=True)
    )
    page_limit = character_counts[0] - 1
    assert character_counts[1] <= page_limit
    monkeypatch.setattr(outlines, "MAX_SOURCE_CHARACTERS_PER_PAGE", page_limit)

    report = outlines.extract_outline_evidence(source, max_pages=100)
    assert report.status == "available"
    first_page, second_page = report.pages
    assert first_page.page_index == 1
    assert first_page.markers == ()
    assert first_page.concern_codes == ("outline_source_limit",)
    assert second_page.page_index == 2
    assert len(second_page.markers) == 3
    assert second_page.concern_codes == ()

    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        report,
        metrics=projection_metrics,
    )
    assert projection_metrics["status"] == "projected"
    assert metrics._outline_ir_summary(projected) == {
        "group_count": 1,
        "node_count": 3,
        "relationship_count": 5,
    }
    page_ids = {page.page_index: page.id for page in projected.pages}
    projected_members = [
        element
        for element in projected.elements
        if element.outline_group is not None or element.outline_item is not None
    ]
    assert projected_members
    assert all(element.page_id == page_ids[2] for element in projected_members)
    assert any(
        concern.code == "outline_source_limit" and concern.source_ref == "page:1"
        for concern in projected.concerns
    )


def test_production_source_comparison_limit_is_page_local_and_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingComparisonLimit:
        def __init__(self) -> None:
            self.observed: list[int] = []

        def __lt__(self, value: object) -> bool:
            self.observed.append(int(value))
            return False

    source = metrics._verified_source_bytes(
        metrics.WORKSPACE,
        "component-datasheet",
    )
    recorder = RecordingComparisonLimit()
    monkeypatch.setattr(outlines, "MAX_COMPARISONS_PER_PAGE", recorder)
    baseline = outlines.extract_outline_evidence(source, max_pages=100)
    assert baseline.status == "available"
    observed = max(recorder.observed)

    monkeypatch.setattr(outlines, "MAX_COMPARISONS_PER_PAGE", observed)
    exact = outlines.extract_outline_evidence(source, max_pages=100)
    assert exact.status == "available"

    monkeypatch.setattr(outlines, "MAX_COMPARISONS_PER_PAGE", observed - 1)
    overflow = outlines.extract_outline_evidence(source, max_pages=100)
    assert overflow.status == "available"
    assert any("outline_source_limit" in page.concern_codes for page in overflow.pages)


def test_production_source_geometry_failure_is_page_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_document = outlines.pdfium.PdfDocument

    class InvalidGeometryPage:
        def get_size(self) -> tuple[float, float]:
            return float("nan"), float("nan")

    class InvalidGeometryDocument:
        def __init__(self, source: bytes) -> None:
            self.document = original_document(source)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            self.document.close()

        def __len__(self) -> int:
            return len(self.document)

        def __getitem__(self, _index: int) -> InvalidGeometryPage:
            return InvalidGeometryPage()

    source = metrics._verified_source_bytes(
        metrics.WORKSPACE,
        "component-datasheet",
    )
    monkeypatch.setattr(outlines.pdfium, "PdfDocument", InvalidGeometryDocument)
    report = outlines.extract_outline_evidence(source, max_pages=100)

    assert report.status == "available"
    assert (
        len(report.pages)
        == metrics.SOURCE_IDENTITIES["component-datasheet"]["page_count"]
    )
    assert all(page.markers == () for page in report.pages)
    assert all(
        page.concern_codes == ("outline_geometry_ambiguous",) for page in report.pages
    )


def _public_item_payload(
    *,
    raw_marker: str = "-",
    body_text: str = "body",
    level: int = 0,
) -> dict[str, Any]:
    return {
        "id": "outline-item:test",
        "element_id": "element:test",
        "source_public_item_id": "item:test",
        "source_public_path": ["pages", 0, "items", 0],
        "source_bbox_id": "bbox:source",
        "source_evidence_ids": ["evidence:source"],
        "source_object": {
            "reader": "pdfplumber",
            "page_index": 1,
            "word_index": 0,
        },
        "sequence_kind": "unordered",
        "marker_style": "bullet",
        "raw_marker": raw_marker,
        "marker_bbox": {
            "x": 1.0,
            "y": 1.0,
            "width": 1.0,
            "height": 1.0,
            "unit": "pt",
        },
        "marker_ownership": "value_prefix",
        "marker_separator": " ",
        "body_text": body_text,
        "predecessor_value_sha256": "a" * 64,
        "level": level,
        "ordinal": 1,
        "parent_id": None,
        "marker_bbox_id": "bbox:marker",
        "marker_evidence_id": "evidence:marker",
        "source_method": "native",
        "confidence": {
            "scope": "evidence",
            "score": None,
            "unavailable_reason": "not_calibrated",
        },
        "concern_codes": [],
        "relationship_ids": [],
        "continuation_ids": [],
    }


def test_production_marker_and_item_byte_limits_are_inclusive() -> None:
    outlines.PublicOutlineItem.model_validate(
        _public_item_payload(raw_marker="x" * outlines.MAX_MARKER_BYTES)
    )
    with pytest.raises(ValidationError, match="marker exceeds"):
        outlines.PublicOutlineItem.model_validate(
            _public_item_payload(raw_marker="x" * (outlines.MAX_MARKER_BYTES + 1))
        )

    outlines.PublicOutlineItem.model_validate(
        _public_item_payload(body_text="x" * outlines.MAX_ITEM_TEXT_BYTES)
    )
    with pytest.raises(ValidationError, match="body exceeds"):
        outlines.PublicOutlineItem.model_validate(
            _public_item_payload(body_text="x" * (outlines.MAX_ITEM_TEXT_BYTES + 1))
        )


def _project_with_metrics(
    case: str,
) -> tuple[Any, dict[str, Any]]:
    predecessor, evidence = metrics._projection_inputs(case)
    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        evidence,
        metrics=projection_metrics,
    )
    return projected, projection_metrics


@pytest.mark.parametrize(
    ("attribute", "case", "observed", "overflow_status"),
    [
        ("MAX_DEPTH", "component-datasheet", 2, "no_candidates"),
        ("MAX_NODES_PER_GROUP", "settlement-agreement", 3, "no_candidates"),
        ("MAX_GROUPS_PER_PAGE", "component-datasheet", 2, "no_candidates"),
        ("MAX_GROUPS_PER_DOCUMENT", "component-datasheet", 2, "failed_closed"),
        ("MAX_NODES_PER_PAGE", "component-datasheet", 16, "no_candidates"),
        ("MAX_NODES_PER_DOCUMENT", "component-datasheet", 16, "failed_closed"),
        ("MAX_INTERSTITIALS_PER_GROUP", "settlement-agreement", 1, "no_candidates"),
        ("MAX_RELATIONSHIPS_PER_PAGE", "settlement-agreement", 6, "no_candidates"),
        (
            "MAX_RELATIONSHIPS_PER_DOCUMENT",
            "component-datasheet",
            32,
            "failed_closed",
        ),
    ],
)
def test_production_projection_count_limits_accept_exact_and_fail_closed_above(
    attribute: str,
    case: str,
    observed: int,
    overflow_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(outlines, attribute, observed)
    exact, exact_metrics = _project_with_metrics(case)
    assert exact_metrics["status"] == "projected"
    assert (
        metrics._outline_ir_summary(exact) == (metrics.EXPECTED_OUTLINE_SUMMARIES[case])
    )

    monkeypatch.setattr(outlines, attribute, observed - 1)
    maximum_plus_one, overflow_metrics = _project_with_metrics(case)
    assert overflow_metrics["status"] == overflow_status
    assert metrics._outline_ir_summary(maximum_plus_one) == {
        "group_count": 0,
        "node_count": 0,
        "relationship_count": 0,
    }


def test_production_comparison_limit_is_charged_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact_projection, baseline = _project_with_metrics("component-datasheet")
    assert baseline["status"] == "projected"
    observed = max(baseline["comparisons_by_page"].values())
    assert observed > 0

    monkeypatch.setattr(outlines, "MAX_COMPARISONS_PER_PAGE", observed)
    exact, exact_metrics = _project_with_metrics("component-datasheet")
    assert exact_metrics["status"] == "projected"
    assert exact.model_dump(mode="json") == exact_projection.model_dump(mode="json")

    monkeypatch.setattr(outlines, "MAX_COMPARISONS_PER_PAGE", observed - 1)
    overflow, overflow_metrics = _project_with_metrics("component-datasheet")
    assert overflow_metrics["status"] == "no_candidates"
    assert metrics._outline_ir_summary(overflow)["group_count"] == 0


class _RecordingLimit:
    def __init__(self) -> None:
        self.observed: list[int] = []

    def __lt__(self, value: object) -> bool:
        self.observed.append(int(value))
        return False


def test_production_public_group_byte_limit_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RecordingLimit()
    monkeypatch.setattr(outlines, "MAX_PUBLIC_GROUP_BYTES", recorder)
    _projected, baseline = _project_with_metrics("component-datasheet")
    assert baseline["status"] == "projected"
    observed = max(recorder.observed)

    monkeypatch.setattr(outlines, "MAX_PUBLIC_GROUP_BYTES", observed)
    _exact, exact_metrics = _project_with_metrics("component-datasheet")
    assert exact_metrics["status"] == "projected"

    monkeypatch.setattr(outlines, "MAX_PUBLIC_GROUP_BYTES", observed - 1)
    overflow, overflow_metrics = _project_with_metrics("component-datasheet")
    assert overflow_metrics["status"] == "no_candidates"
    assert metrics._outline_ir_summary(overflow)["group_count"] == 0


def test_production_report_byte_limit_is_inclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = metrics._verified_source_bytes(
        metrics.WORKSPACE,
        "component-datasheet",
    )
    monkeypatch.setattr(outlines.time, "perf_counter", lambda: 0.0)
    recorder = _RecordingLimit()
    monkeypatch.setattr(outlines, "MAX_REPORT_BYTES", recorder)
    baseline = outlines.extract_outline_evidence(source, max_pages=100)
    assert baseline.status == "available"
    observed = max(recorder.observed)

    monkeypatch.setattr(outlines, "MAX_REPORT_BYTES", observed)
    exact = outlines.extract_outline_evidence(source, max_pages=100)
    assert exact.status == "available"

    monkeypatch.setattr(outlines, "MAX_REPORT_BYTES", observed - 1)
    overflow = outlines.extract_outline_evidence(source, max_pages=100)
    assert overflow.status == "refused"
    assert overflow.concern_codes == ("outline_source_limit",)


@pytest.mark.parametrize(
    ("attribute", "source_ref"),
    [
        ("MAX_CONCERNS_PER_PAGE", "page:1"),
        ("MAX_CONCERNS_PER_DOCUMENT", None),
    ],
)
def test_production_concern_limits_accept_exact_and_suppress_plus_one(
    attribute: str,
    source_ref: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor, _evidence = metrics._projection_inputs("component-datasheet")
    predecessor.concerns = []
    monkeypatch.setattr(outlines, attribute, 2)
    if attribute == "MAX_CONCERNS_PER_PAGE":
        monkeypatch.setattr(outlines, "MAX_CONCERNS_PER_DOCUMENT", 256)
    else:
        monkeypatch.setattr(outlines, "MAX_CONCERNS_PER_PAGE", 64)

    outlines._append_outline_concern(
        predecessor,
        "outline_geometry_ambiguous",
        source_ref=source_ref or "page:1",
    )
    outlines._append_outline_concern(
        predecessor,
        "outline_marker_ambiguous",
        source_ref=source_ref or "page:2",
    )
    assert len(predecessor.concerns) == 2

    outlines._append_outline_concern(
        predecessor,
        "outline_sequence_invalid",
        source_ref=source_ref or "page:3",
    )
    assert len(predecessor.concerns) == 3
    assert predecessor.concerns[-1].code == "outline_concerns_truncated"
    assert not any(
        concern.code == "outline_sequence_invalid" for concern in predecessor.concerns
    )


class _ElapsedClock:
    def __init__(self, elapsed: float) -> None:
        self.elapsed = elapsed
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 0.0 if self.calls == 1 else self.elapsed


class _IncrementingClock:
    def __init__(self, step: float = 0.000_001) -> None:
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        value = self.calls * self.step
        self.calls += 1
        return value


class _ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_production_source_deadline_is_inclusive_and_refuses_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = metrics._verified_source_bytes(
        metrics.WORKSPACE,
        "component-datasheet",
    )
    limit = outlines.SOURCE_EXTRACTION_DEADLINE_SECONDS
    monkeypatch.setattr(outlines.time, "perf_counter", _ElapsedClock(limit))
    exact = outlines.extract_outline_evidence(source, max_pages=100)
    assert exact.status == "available"

    monkeypatch.setattr(
        outlines.time,
        "perf_counter",
        _ElapsedClock(limit + 0.000_001),
    )
    overflow = outlines.extract_outline_evidence(source, max_pages=100)
    assert overflow.status == "refused"
    assert overflow.concern_codes == ("outline_source_limit",)


@pytest.mark.parametrize(
    "deadline",
    ["page", "document"],
)
def test_production_projection_deadlines_accept_exact_and_fail_closed_overflow(
    deadline: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if deadline == "page":
        monkeypatch.setattr(outlines, "PROJECTION_PAGE_DEADLINE_SECONDS", 0.0)
        monkeypatch.setattr(
            outlines,
            "PROJECTION_DOCUMENT_DEADLINE_SECONDS",
            2.0,
        )
    else:
        monkeypatch.setattr(outlines, "PROJECTION_PAGE_DEADLINE_SECONDS", 0.25)
        monkeypatch.setattr(
            outlines,
            "PROJECTION_DOCUMENT_DEADLINE_SECONDS",
            0.0,
        )

    monkeypatch.setattr(outlines.time, "perf_counter", lambda: 0.0)
    _exact, exact_metrics = _project_with_metrics("component-datasheet")
    assert exact_metrics["status"] == "projected"

    monkeypatch.setattr(
        outlines.time,
        "perf_counter",
        _IncrementingClock(),
    )
    overflow, overflow_metrics = _project_with_metrics("component-datasheet")
    assert overflow_metrics["status"] in {
        "no_candidates" if deadline == "page" else "failed_closed"
    }
    assert metrics._outline_ir_summary(overflow)["group_count"] == 0


def test_projection_page_deadline_spans_matching_planning_and_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor, evidence = metrics._projection_inputs("component-datasheet")
    clock = _ManualClock()
    original_match = outlines._match_markers
    original_plan = outlines._build_group_plans
    original_materialize = outlines._materialize_group
    charged: set[str] = set()

    def charge_once(phase: str) -> None:
        if phase not in charged:
            charged.add(phase)
            clock.now += 0.100

    def delayed_match(*args: Any, **kwargs: Any) -> Any:
        result = original_match(*args, **kwargs)
        charge_once("matching")
        return result

    def delayed_plan(*args: Any, **kwargs: Any) -> Any:
        result = original_plan(*args, **kwargs)
        charge_once("planning")
        return result

    def delayed_materialize(*args: Any, **kwargs: Any) -> Any:
        result = original_materialize(*args, **kwargs)
        charge_once("materialization")
        return result

    monkeypatch.setattr(outlines.time, "perf_counter", clock)
    monkeypatch.setattr(outlines, "PROJECTION_PAGE_DEADLINE_SECONDS", 0.250)
    monkeypatch.setattr(outlines, "PROJECTION_DOCUMENT_DEADLINE_SECONDS", 2.0)
    monkeypatch.setattr(outlines, "_match_markers", delayed_match)
    monkeypatch.setattr(outlines, "_build_group_plans", delayed_plan)
    monkeypatch.setattr(outlines, "_materialize_group", delayed_materialize)

    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        evidence,
        metrics=projection_metrics,
    )

    assert charged == {"matching", "planning", "materialization"}
    assert clock.now == pytest.approx(0.300)
    assert projection_metrics["status"] == "no_candidates"
    assert metrics._outline_ir_summary(projected) == {
        "group_count": 0,
        "node_count": 0,
        "relationship_count": 0,
    }
    assert any(
        concern.code == "outline_projection_failed_closed"
        and concern.source_ref == "page:1"
        for concern in projected.concerns
    )


def test_single_group_materialization_still_closes_the_page_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor, evidence = metrics._projection_inputs("settlement-agreement")
    clock = _ManualClock()
    original_materialize = outlines._materialize_group
    materialize_calls = 0

    def delayed_materialize(*args: Any, **kwargs: Any) -> Any:
        nonlocal materialize_calls
        result = original_materialize(*args, **kwargs)
        materialize_calls += 1
        clock.now = 0.251
        return result

    monkeypatch.setattr(outlines.time, "perf_counter", clock)
    monkeypatch.setattr(outlines, "PROJECTION_PAGE_DEADLINE_SECONDS", 0.250)
    monkeypatch.setattr(outlines, "PROJECTION_DOCUMENT_DEADLINE_SECONDS", 2.0)
    monkeypatch.setattr(outlines, "_materialize_group", delayed_materialize)

    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        evidence,
        metrics=projection_metrics,
    )

    assert materialize_calls == 1
    assert projection_metrics["status"] == "no_candidates"
    assert metrics._outline_ir_summary(projected) == {
        "group_count": 0,
        "node_count": 0,
        "relationship_count": 0,
    }
    assert any(
        concern.code == "outline_projection_failed_closed"
        and concern.source_ref == "page:1"
        for concern in projected.concerns
    )


@pytest.mark.parametrize(
    ("validation_elapsed", "expected_status", "expected_group_count"),
    [
        (0.251, "projected", 2),
        (2.001, "failed_closed", 0),
    ],
)
def test_full_ir_validation_is_charged_to_the_document_deadline(
    validation_elapsed: float,
    expected_status: str,
    expected_group_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor, evidence = metrics._projection_inputs("component-datasheet")
    clock = _ManualClock()
    original_validate = outlines.DocumentIR.model_validate

    def delayed_validate(
        cls: type[outlines.DocumentIR],
        value: Any,
        *args: Any,
        **kwargs: Any,
    ) -> outlines.DocumentIR:
        del cls
        result = original_validate(value, *args, **kwargs)
        if any(element.outline_group is not None for element in result.elements):
            clock.now = validation_elapsed
        return result

    monkeypatch.setattr(outlines.time, "perf_counter", clock)
    monkeypatch.setattr(
        outlines.DocumentIR,
        "model_validate",
        classmethod(delayed_validate),
    )

    projection_metrics: dict[str, Any] = {}
    projected = outlines.project_outline_structure(
        predecessor,
        evidence,
        metrics=projection_metrics,
    )

    assert clock.now == validation_elapsed
    assert projection_metrics["status"] == expected_status
    assert metrics._outline_ir_summary(projected)["group_count"] == (
        expected_group_count
    )


def test_resource_and_deadline_registries_bind_every_production_constant() -> None:
    resources = metrics.generate_resource_boundary_metrics()
    assert resources["boundary_count"] == 22
    assert set(resources["boundaries"]) == set(metrics._PRODUCTION_LIMIT_ATTRIBUTES)
    assert resources["all_exact_accepted"] is True
    assert resources["all_maximum_plus_one_refused"] is True
    assert resources["all_production_limits_exact"] is True
    assert resources["all_within_boundary_ceiling"] is True
    for name, record in resources["boundaries"].items():
        assert record["production_limit"] == record["registry_limit"]
        assert record["exact_observed"] == record["registry_limit"]
        assert record["maximum_plus_one_observed"] == (record["registry_limit"] + 1)
        assert record["boundary_ceiling_seconds_each"] == 0.250
        assert record["within_boundary_ceiling"] is True
        assert name in metrics._PRODUCTION_LIMIT_ATTRIBUTES

    deadlines = metrics.generate_deadline_metrics()
    assert deadlines["deadline_count"] == 3
    assert set(deadlines["deadlines"]) == set(metrics._PRODUCTION_DEADLINE_ATTRIBUTES)
    assert deadlines["all_exact_accepted"] is True
    assert deadlines["all_maximum_plus_one_refused"] is True
    assert deadlines["all_production_limits_exact"] is True


def _fake_snapshot(
    calls: list[tuple[str, bool]],
    case: str,
    enabled: bool,
) -> dict[str, Any]:
    calls.append((case, enabled))
    base_seconds = 10.0 if case == "component-datasheet" else 6.0
    base_rss = 1_000_000 if case == "component-datasheet" else 2_000_000
    zero_outline = {
        "group_count": 0,
        "node_count": 0,
        "continuation_count": 0,
        "relationship_count": 0,
    }
    expected_outline = {
        **metrics.EXPECTED_OUTLINE_SUMMARIES[case],
        "continuation_count": 1 if case == "settlement-agreement" else 0,
    }
    return {
        "case": case,
        "enabled": enabled,
        "wall_seconds": base_seconds + (0.1 if enabled else 0.0),
        "peak_rss_bytes": base_rss + (10_000 if enabled else 0),
        "extractor_call_count": 1 if enabled else 0,
        "semantic_json_sha256": hashlib.sha256(
            f"{case}:{enabled}".encode()
        ).hexdigest(),
        "semantic_json_size_bytes": 100 + int(enabled),
        "outline_semantic_sha256": hashlib.sha256(
            f"outline:{case}:{enabled}".encode()
        ).hexdigest(),
        "outline_semantic_size_bytes": 105 + int(enabled),
        "raw_json_sha256": hashlib.sha256(f"raw:{case}:{enabled}".encode()).hexdigest(),
        "raw_json_size_bytes": 110 + int(enabled),
        "markdown_sha256": hashlib.sha256(
            f"markdown:{case}:{enabled}".encode()
        ).hexdigest(),
        "markdown_size_bytes": 120 + int(enabled),
        "flag_off_projection_absent": not enabled,
        "processing_has_outline_summary": enabled,
        "outline_summary": expected_outline if enabled else zero_outline,
        "form_summary": deepcopy(metrics.EXPECTED_FORM_SUMMARIES[case]),
        **metrics.HOSTED_USAGE,
    }


def test_paired_harness_runs_five_alternating_pairs_for_both_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def snapshot(
        _workspace: Path,
        case: str,
        enabled: bool,
    ) -> dict[str, Any]:
        return _fake_snapshot(calls, case, enabled)

    monkeypatch.setattr(metrics, "_fresh_snapshot", snapshot)
    measured = metrics.generate_paired_parser_metrics(repeats=5)

    assert measured["pair_count_per_case"] == 5
    assert measured["performance_cases"] == list(metrics.PAIRED_CASES)
    expected_order = [
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
        ["on", "off"],
        ["off", "on"],
    ]
    for case in metrics.PAIRED_CASES:
        record = measured["cases"][case]
        assert record["execution_order"] == expected_order
        assert record["all_flag_off_extractor_counts_zero"] is True
        assert record["all_flag_on_extractor_counts_one"] is True
        assert record["all_flag_off_projection_absent"] is True
        assert record["all_flag_on_processing_summaries_present"] is True
        assert record["all_flag_on_outline_summaries_exact"] is True
        assert record["flag_off_semantic_deterministic"] is True
        assert record["flag_on_first_three_semantic_deterministic"] is True
        assert record["flag_on_all_semantic_deterministic"] is True
        assert record["flag_on_outline_semantic_deterministic"] is True
        assert record["all_samples_forms_predecessor_present"] is True
        assert record["all_samples_zero_hosted_usage"] is True
        paired = record["paired_performance"]
        assert paired["pair_count"] == 5
        assert paired["p95_nonnegative_overhead_seconds"] == 0.1
        assert paired["within_five_percent_ceiling"] is True
        assert paired["within_absolute_ceiling"] is True
        assert paired["within_both_ceilings"] is True
        assert paired["within_peak_rss_delta_ceiling"] is True
    assert len(calls) == 20


def test_paired_harness_rejects_any_count_other_than_exactly_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_snapshot(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("invalid pair count must fail before workers run")

    monkeypatch.setattr(metrics, "_fresh_snapshot", unexpected_snapshot)
    for repeats in (4, 6):
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_paired_parser_metrics(repeats=repeats)
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_preliminary_metrics(repeats=repeats)
        with pytest.raises(ValueError, match="exactly 5 repeats"):
            metrics.generate_artifact(repeats=repeats)


def test_final_artifact_custody_collectors_bind_live_inputs() -> None:
    code = metrics._code_custody()
    predecessor = metrics._predecessor_custody()
    m0 = metrics._m0_custody()
    oracle = metrics._oracle_custody()
    contract = metrics._contract_custody()
    synthetic = metrics._synthetic_fixture_custody()
    dependency = metrics._dependency_custody()

    assert tuple(code) == metrics.FINAL_CODE_PATHS
    assert all(len(record["sha256"]) == 64 for record in code.values())
    assert predecessor["p03_us06_artifact"]["sha256"] == (
        metrics.PREDECESSOR_ARTIFACT_RAW_SHA256
    )
    assert predecessor["p03_us06_artifact"]["semantic_sha256"] == (
        metrics.PREDECESSOR_ARTIFACT_SEMANTIC_SHA256
    )
    assert m0["sha256"] == metrics.M0_ARTIFACT_RAW_SHA256
    assert oracle["source_identities_exact"] is True
    assert oracle["reviewed_counts"] == metrics.REVIEWED_COUNTS
    assert contract["policy_id"] == outlines.POLICY_ID
    assert synthetic["fixture_count"] == len(synthetic["fixture_hashes"])
    assert synthetic["required_capability_count"] >= 37
    assert synthetic["self_check_passed"] is True
    assert dependency["python_packages"]["docling"]
    assert dependency["python_packages"]["pdfplumber"]
    assert dependency["local_tool_identity"]["tesseract"]["version"].startswith(
        "tesseract "
    )


def test_final_artifact_envelope_binds_rollback_and_semantic_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def snapshot(
        _workspace: Path,
        case: str,
        enabled: bool,
    ) -> dict[str, Any]:
        return _fake_snapshot(calls, case, enabled)

    monkeypatch.setattr(metrics, "_fresh_snapshot", snapshot)
    paired = metrics.generate_paired_parser_metrics()
    extraction = {
        case: {
            "source_report_exact": True,
            "within_p95_ceiling": True,
            "within_peak_allocation_ceiling": True,
            "within_report_size_ceiling": True,
        }
        for case in metrics.PAIRED_CASES
    }
    projection = {
        case: {
            "within_p95_ceiling": True,
            "within_peak_allocation_ceiling": True,
            "within_comparison_ceiling": True,
            "outline_summary_exact": True,
            "repeated_projection_idempotent": True,
        }
        for case in metrics.PAIRED_CASES
    }
    resources = {
        "all_exact_accepted": True,
        "all_maximum_plus_one_refused": True,
        "all_production_limits_exact": True,
        "all_within_boundary_ceiling": True,
    }
    deadlines = deepcopy(resources)
    preliminary = {
        "input_custody": {case: {"exact_match": True} for case in metrics.PAIRED_CASES},
        "settings_delta": metrics._settings_delta(),
        "isolated_extraction": extraction,
        "isolated_projection": projection,
        "resource_boundaries": resources,
        "deadline_boundaries": deadlines,
        "paired_parser": paired,
        "control_matrix": {"all_real_controls_pass": True},
        "relationship_order_retention": {
            "all_pass": True,
            "total_expected": 41,
            "total_matched": 41,
        },
    }

    artifact = metrics._build_final_artifact_envelope(
        preliminary,
        code_custody={"code.py": {"sha256": "a" * 64}},
        dependency_custody={"python_packages": {"example": "1"}},
        predecessor_custody={"semantic_sha256": "b" * 64},
        m0_custody={"sha256": "c" * 64},
        oracle_custody={"oracle_payload_sha256": "d" * 64},
        contract_custody={"policy_id": outlines.POLICY_ID},
        synthetic_fixture_custody={"registry_sha256": "e" * 64},
        generated_at="2026-08-01T00:00:00+00:00",
    )

    assert artifact["schema_version"] == "1.0"
    assert artifact["record_kind"] == "p03_us07_outline_metrics"
    assert artifact["measurement"]["pair_count_per_case"] == 5
    assert artifact["measurement"]["worker_process_count"] == 20
    assert artifact["code_sha256"] == {"code.py": {"sha256": "a" * 64}}
    assert artifact["rollback"] == {
        "rollback_value": False,
        "only_us07_setting_toggled": True,
        "all_flag_off_extractor_counts_zero": True,
        "all_flag_off_projection_absent": True,
        "all_repeated_projections_idempotent": True,
        "configured_predecessor_flags_unchanged": True,
    }
    assert artifact["aggregate"]["paired_parser_within_both_ceilings"] is True
    assert artifact["aggregate"]["flag_on_extractor_count_one"] is True
    assert artifact["aggregate"]["forms_predecessor_summaries_exact"] is True
    assert artifact["aggregate"]["relationship_order_matched"] == 41
    assert len(artifact["output_sizes"]["component-datasheet"]["off"]) == 5
    assert (
        artifact["semantic_sha256"]
        == hashlib.sha256(
            metrics._canonical_json(
                metrics._artifact_semantic_payload(artifact)
            ).encode("utf-8")
        ).hexdigest()
    )
    changed_time = deepcopy(artifact)
    changed_time["generated_at"] = "2099-01-01T00:00:00+00:00"
    assert metrics._artifact_semantic_payload(changed_time) == (
        metrics._artifact_semantic_payload(artifact)
    )


def test_worker_cli_and_atomic_preliminary_output(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "preliminary.json"
    metrics._write_json_atomic(output, {"answer": 41})
    assert output.read_text(encoding="utf-8") == ('{\n  "answer": 41\n}\n')
    assert not list(output.parent.glob("*.tmp"))

    command = metrics._worker_command(
        metrics.WORKSPACE,
        "component-datasheet",
        True,
        output,
    )
    assert command[-8:] == [
        "--workspace",
        str(metrics.WORKSPACE),
        "--worker-case",
        "component-datasheet",
        "--worker-enabled",
        "true",
        "--output",
        str(output),
    ]
    parsed = metrics._parse_args(
        [
            "--worker-case",
            "settlement-agreement",
            "--worker-enabled",
            "false",
            "--output",
            str(output),
        ]
    )
    assert parsed.worker_case == "settlement-agreement"
    assert parsed.worker_enabled == "false"
    assert parsed.output == output
    assert metrics.DEFAULT_ARTIFACT_RELATIVE_PATH == Path(
        "tracker/phase-03-layout/evidence/P03-US07-outline-metrics.json"
    )

    final = metrics._parse_args(["--final-artifact", "--output", str(output)])
    assert final.final_artifact is True
    assert final.repeats == 5


def test_worker_cli_rejects_incomplete_or_implicit_output_modes() -> None:
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-case", "component-datasheet"])
    with pytest.raises(SystemExit):
        metrics._parse_args(["--worker-enabled", "true"])
    with pytest.raises(SystemExit):
        metrics._parse_args([])
    with pytest.raises(SystemExit):
        metrics._parse_args(["--repeats", "6", "--output", "candidate.json"])
    with pytest.raises(SystemExit):
        metrics._parse_args(
            [
                "--worker-case",
                "component-datasheet",
                "--worker-enabled",
                "true",
                "--final-artifact",
                "--output",
                "worker.json",
            ]
        )
