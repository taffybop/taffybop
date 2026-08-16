"""Guardrails for the non-production P04 deadline diagnostic harness."""

from __future__ import annotations

import inspect
import math
import time

import pytest

from app.config import Settings
from app.services import pipeline, table_semantics
from tests.fixtures.phase_04.tables.diagnostic_budget import (
    capture_p04_diagnostic_timings,
    DIAGNOSTIC_CLASSIFICATION,
    DIAGNOSTIC_MAX_DOCUMENT_SECONDS,
    PRODUCTION_DOCUMENT_SECONDS,
    diagnostic_table_document_budget,
)


def test_diagnostic_budget_changes_both_document_enforcement_points_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: 100.0)
    original_deadline = table_semantics.table_span_fidelity_document_deadline
    original_resolver = table_semantics._resolve_table_document_deadline

    assert original_deadline() == 105.0
    with diagnostic_table_document_budget(15.0) as activation:
        assert table_semantics.table_span_fidelity_document_deadline() == 115.0
        assert table_semantics._resolve_table_document_deadline(None) == 115.0
        assert table_semantics._resolve_table_document_deadline(115.0) == 115.0
        with pytest.raises(ValueError, match="diagnostic table document deadline"):
            table_semantics._resolve_table_document_deadline(115.001)

        # The diagnostic experiment is document-only.  The independently
        # governed page budget remains exactly 500 ms.
        assert table_semantics.table_span_fidelity_page_deadline() == 100.5
        assert activation == {
            "schema_version": "1.0",
            "policy_id": "p04-diagnostic-document-budget-v1",
            "classification": DIAGNOSTIC_CLASSIFICATION,
            "production_document_seconds": PRODUCTION_DOCUMENT_SECONDS,
            "diagnostic_document_seconds": 15.0,
            "page_seconds": 0.5,
            "public_request_control": False,
            "closure_evidence": False,
        }

    assert table_semantics.table_span_fidelity_document_deadline is original_deadline
    assert table_semantics._resolve_table_document_deadline is original_resolver
    assert table_semantics.table_span_fidelity_document_deadline() == 105.0


def test_diagnostic_budget_preserves_table_repair_local_five_second_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float | None] = []

    def repair_spy(*_args: object, **kwargs: object) -> dict[int, list[object]]:
        value = kwargs.get("table_span_fidelity_document_deadline")
        observed.append(float(value) if isinstance(value, (int, float)) else None)
        return {}

    monkeypatch.setattr(pipeline, "_extract_table_repair_words", repair_spy)
    patched_original = pipeline._extract_table_repair_words
    started = time.perf_counter()
    with diagnostic_table_document_budget(30.0):
        outer_deadline = table_semantics.table_span_fidelity_document_deadline()
        pipeline._extract_table_repair_words(
            b"pdf",
            {},
            table_span_fidelity_enabled=True,
            table_span_fidelity_document_deadline=outer_deadline,
            table_span_fidelity_page_deadlines={},
        )

    assert len(observed) == 1
    assert observed[0] is not None
    assert started < observed[0] <= time.perf_counter() + PRODUCTION_DOCUMENT_SECONDS
    assert pipeline._extract_table_repair_words is patched_original


def test_diagnostic_budget_does_not_widen_page_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(table_semantics, "perf_counter", lambda: 100.0)
    original_page_resolver = table_semantics._resolve_table_page_deadline

    with diagnostic_table_document_budget(30.0):
        assert table_semantics._resolve_table_page_deadline(100.5, 130.0) == 100.5
        with pytest.raises(ValueError, match="table page deadline differs"):
            table_semantics._resolve_table_page_deadline(100.501, 130.0)

    assert table_semantics._resolve_table_page_deadline is original_page_resolver


@pytest.mark.parametrize(
    "value",
    (
        None,
        True,
        False,
        "15",
        4.999,
        DIAGNOSTIC_MAX_DOCUMENT_SECONDS + 0.001,
        math.nan,
        math.inf,
        -math.inf,
    ),
)
def test_diagnostic_budget_rejects_invalid_or_unbounded_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="diagnostic table document budget"):
        with diagnostic_table_document_budget(value):
            pytest.fail("invalid diagnostic budget activated")


def test_diagnostic_budget_is_non_reentrant_and_restores_after_failure() -> None:
    original_deadline = table_semantics.table_span_fidelity_document_deadline
    original_resolver = table_semantics._resolve_table_document_deadline

    with pytest.raises(RuntimeError, match="already active"):
        with diagnostic_table_document_budget(10.0):
            with diagnostic_table_document_budget(15.0):
                pytest.fail("nested diagnostic budget activated")

    assert table_semantics.table_span_fidelity_document_deadline is original_deadline
    assert table_semantics._resolve_table_document_deadline is original_resolver


@pytest.mark.parametrize("seconds", (5.0, 10.0, 15.0, 30.0))
def test_declared_sweep_budgets_activate_and_restore(seconds: float) -> None:
    original_deadline = table_semantics.table_span_fidelity_document_deadline
    with diagnostic_table_document_budget(seconds) as activation:
        assert activation["diagnostic_document_seconds"] == seconds
        assert activation["closure_evidence"] is False
    assert table_semantics.table_span_fidelity_document_deadline is original_deadline


def test_diagnostic_budget_has_no_settings_or_public_parse_switch() -> None:
    forbidden = "table_span_fidelity_diagnostic_document_seconds"
    assert forbidden not in inspect.signature(Settings).parameters
    assert forbidden not in inspect.signature(pipeline.parse_document).parameters
    assert "diagnostic_table_document_budget" not in inspect.getsource(pipeline)


def test_diagnostic_stage_timing_is_external_and_restores_exact_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def segment(
        _document_deadline: float,
        _page_deadlines: dict[int, float],
        _state: dict[str, object],
        operation: object,
    ) -> object:
        return operation(123.0)  # type: ignore[operator]

    monkeypatch.setattr(pipeline, "_run_table_custody_document_segment", segment)
    exact_original = pipeline._run_table_custody_document_segment
    with capture_p04_diagnostic_timings() as records:
        assert pipeline._run_table_custody_document_segment(
            5.0,
            {},
            {},
            lambda deadline: {"deadline": deadline},
        ) == {"deadline": 123.0}

    assert pipeline._run_table_custody_document_segment is exact_original
    matched = [
        record
        for record in records
        if record["stage"] == "pipeline.table_custody_document_segment"
    ]
    assert len(matched) == 1
    assert matched[0]["status"] == "ok"
    assert isinstance(matched[0]["elapsed_ms"], float)
    assert matched[0]["elapsed_ms"] >= 0.0


def test_diagnostic_timing_retains_inner_integrity_reason_and_precleanup_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_splice(*_args: object, **_kwargs: object) -> object:
        raise ValueError("terminal table visual overlay block shape differs")

    monkeypatch.setattr(pipeline, "_splice_terminal_table_canonical", failing_splice)
    with capture_p04_diagnostic_timings() as records:
        with pytest.raises(ValueError, match="visual overlay"):
            pipeline._splice_terminal_table_canonical()
        pipeline._finish_table_span_fidelity_budget(
            {
                "custody_rejected": True,
                "timed_out": False,
                "unbounded_private_value": ["must not escape"],
            }
        )

    splice = next(
        record
        for record in records
        if record["stage"] == "pipeline.terminal_table_canonical_splice"
    )
    assert splice["status"] == "error:ValueError"
    assert splice["error"] == "terminal table visual overlay block shape differs"
    cleanup = next(
        record
        for record in records
        if record["stage"] == "pipeline.table_budget_pre_cleanup_state"
    )
    assert cleanup["state"] == {
        "timed_out": False,
        "custody_rejected": True,
    }
