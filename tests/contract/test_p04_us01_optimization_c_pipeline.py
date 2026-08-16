"""Pipeline-only closure tests for the bounded P04-US01 C optimization."""

from __future__ import annotations

from copy import deepcopy
import time
from typing import Any, Mapping

import pytest

from app.models import CanonicalSourceCustody, ParseResult
from app.services import ir as ir_service
from app.services import opaque_group_custody as custody
from app.services import pipeline, presentation
from app.services.input_documents import InputKind
from app.services.ir import DocumentIR
from tests.contract.test_p04_us01_p03_boundary import (
    _grandfathered_non_target_splice_case,
    _p03_settings,
    _projected_predecessor,
)
from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes


def _terminal_commit(
    baseline: dict[str, Any],
    baseline_ir: DocumentIR,
    transaction: tuple[Any, ...],
    *,
    fixture: Any,
    state: dict[str, Any],
) -> dict[str, Any]:
    now = time.perf_counter()
    return pipeline._apply_terminal_table_authority(
        baseline,
        baseline_ir,
        transaction,
        _p03_settings(table_enabled=True),
        raw_graph=fixture.raw_graph,
        native_texts=fixture.native_texts,
        text_run_evidence=None,
        form_evidence=None,
        outline_evidence=None,
        source_pdf_bytes=fixture.source_pdf_bytes,
        input_kind=InputKind.PDF,
        document_deadline=now + 5.0,
        page_deadlines={1: now + 0.5},
        state=state,
    )


def test_splice_private_builder_uses_exact_direct_validated_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, candidate, canonical, transaction = (
        _grandfathered_non_target_splice_case()
    )
    baseline_before = strict_json_bytes(baseline)
    candidate_before = strict_json_bytes(candidate)
    original_ir_builder = ir_service.build_document_ir
    original_private_builder = (
        presentation._build_canonical_presentation_from_validated
    )
    direct_results: list[DocumentIR] = []
    private_inputs: list[DocumentIR] = []

    def direct_builder(*args: Any, **kwargs: Any) -> DocumentIR:
        result = original_ir_builder(*args, **kwargs)
        direct_results.append(result)
        return result

    def private_builder(value: DocumentIR) -> Any:
        assert type(value) is DocumentIR
        assert direct_results and value is direct_results[-1]
        before = strict_json_bytes(value.model_dump(mode="json"))
        result = original_private_builder(value)
        assert strict_json_bytes(value.model_dump(mode="json")) == before
        private_inputs.append(value)
        return result

    monkeypatch.setattr(ir_service, "build_document_ir", direct_builder)
    monkeypatch.setattr(
        presentation,
        "_build_canonical_presentation_from_validated",
        private_builder,
    )
    monkeypatch.setattr(
        presentation,
        "build_canonical_presentation",
        lambda *_args, **_kwargs: pytest.fail(
            "splice repeated public DocumentIR validation"
        ),
    )

    result = pipeline._splice_terminal_table_canonical(
        baseline,
        candidate,
        canonical,
        transaction,
    )

    assert len(direct_results) == 1
    assert private_inputs == direct_results
    assert strict_json_bytes(baseline) == baseline_before
    assert strict_json_bytes(candidate) == candidate_before
    assert strict_json_bytes(result["pages"][0]["blocks"][0]) == (
        strict_json_bytes(
            baseline["canonical_presentation"]["pages"][0]["blocks"][0]
        )
    )


def test_splice_rejects_nonexact_direct_ir_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, candidate, canonical, transaction = (
        _grandfathered_non_target_splice_case()
    )
    monkeypatch.setattr(
        ir_service,
        "build_document_ir",
        lambda *_args, **_kwargs: object(),
    )

    with pytest.raises(
        ValueError,
        match="terminal table canonical predecessor reconstruction differs",
    ):
        pipeline._splice_terminal_table_canonical(
            baseline,
            candidate,
            canonical,
            transaction,
        )


def test_mutated_direct_predecessor_ir_fails_closed_to_p03(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    baseline_before = strict_json_bytes(baseline)
    original_ir_builder = ir_service.build_document_ir
    build_calls = 0

    def hostile_second_builder(*args: Any, **kwargs: Any) -> DocumentIR:
        nonlocal build_calls
        build_calls += 1
        result = original_ir_builder(*args, **kwargs)
        if build_calls == 2:
            result.pages[0].presentation_element_ids.append(
                "el-hostile-missing-primary"
            )
        return result

    monkeypatch.setattr(ir_service, "build_document_ir", hostile_second_builder)
    state: dict[str, Any] = {}

    actual = _terminal_commit(
        baseline,
        baseline_ir,
        transaction,
        fixture=fixture,
        state=state,
    )

    assert build_calls == 2
    assert strict_json_bytes(actual) == baseline_before
    assert strict_json_bytes(baseline) == baseline_before
    assert state.get("custody_rejected") is True
    assert state.get("timed_out") is not True
    assert not custody.has_literal_table_marker(actual)


def test_private_predecessor_builder_timeout_rolls_back_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    baseline_before = strict_json_bytes(baseline)
    original_private_builder = (
        presentation._build_canonical_presentation_from_validated
    )
    builder_calls = 0

    def timeout_second_builder(value: DocumentIR) -> Any:
        nonlocal builder_calls
        builder_calls += 1
        if builder_calls == 2:
            raise TimeoutError(
                "injected private predecessor presentation timeout"
            )
        return original_private_builder(value)

    monkeypatch.setattr(
        presentation,
        "_build_canonical_presentation_from_validated",
        timeout_second_builder,
    )
    state: dict[str, Any] = {}

    actual = _terminal_commit(
        baseline,
        baseline_ir,
        transaction,
        fixture=fixture,
        state=state,
    )

    assert builder_calls == 2
    assert strict_json_bytes(actual) == baseline_before
    assert strict_json_bytes(baseline) == baseline_before
    assert state.get("timed_out") is True
    assert state.get("custody_rejected") is not True
    assert not custody.has_literal_table_marker(actual)


def test_terminal_sidecar_has_only_seal_and_post_digest_model_validations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, transaction, baseline, baseline_ir = _projected_predecessor()
    original_validate = CanonicalSourceCustody.model_validate
    observed_digests: list[Any] = []

    def counted_validate(value: Any, *args: Any, **kwargs: Any) -> Any:
        observed_digests.append(
            value.get("canonical_presentation_sha256")
            if isinstance(value, Mapping)
            else getattr(value, "canonical_presentation_sha256", None)
        )
        return original_validate(value, *args, **kwargs)

    monkeypatch.setattr(
        CanonicalSourceCustody,
        "model_validate",
        staticmethod(counted_validate),
    )
    state: dict[str, Any] = {}

    actual = _terminal_commit(
        baseline,
        baseline_ir,
        transaction,
        fixture=fixture,
        state=state,
    )

    assert len(observed_digests) == 2
    assert observed_digests[0] is None
    assert isinstance(observed_digests[1], str)
    assert len(observed_digests[1]) == 64
    assert state.get("timed_out") is not True
    assert state.get("custody_rejected") is not True
    encoded = strict_json_bytes(actual)
    validated = ParseResult.model_validate_json(encoded)
    assert strict_json_bytes(
        validated.model_dump(mode="json", exclude_unset=True)
    ) == encoded
