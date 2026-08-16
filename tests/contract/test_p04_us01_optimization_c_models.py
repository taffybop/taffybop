"""Focused allocation and trust-boundary checks for the US01 C optimizations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.models import PageResult, ParseResult, _trusted_table_validation_context
from app.services import ir as ir_service
from app.services import presentation
from app.services.ir import DocumentIR
from tests.contract.test_p04_us01_p03_boundary import (
    _trusted_terminal_candidate,
)
from tests.fixtures.phase_03.running_regions.contract import strict_json_bytes


@pytest.fixture(scope="module")
def trusted_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the bounded synthetic terminal pair once, before test spies."""

    return _trusted_terminal_candidate()


def _validate_trusted_pair(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> ParseResult:
    baseline_result = ParseResult.model_validate(deepcopy(baseline))
    return ParseResult.model_validate(
        deepcopy(candidate),
        context=_trusted_table_validation_context(baseline_result),
    )


def test_reconstructed_public_ir_uses_one_direct_validated_builder_path(
    monkeypatch: pytest.MonkeyPatch,
    trusted_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    baseline, candidate = trusted_pair
    original_ir_builder = ir_service.build_document_ir
    original_ir_dump = DocumentIR.model_dump
    original_private_builder = (
        presentation._build_canonical_presentation_from_validated
    )
    produced: list[DocumentIR] = []
    received: list[DocumentIR] = []
    document_ir_dump_count = 0

    def build_spy(*args: Any, **kwargs: Any) -> DocumentIR:
        value = original_ir_builder(*args, **kwargs)
        assert type(value) is DocumentIR
        produced.append(value)
        return value

    def dump_spy(self: DocumentIR, *args: Any, **kwargs: Any) -> Any:
        nonlocal document_ir_dump_count
        document_ir_dump_count += 1
        return original_ir_dump(self, *args, **kwargs)

    def private_spy(value: DocumentIR) -> Any:
        assert produced and value is produced[-1]
        assert type(value) is DocumentIR
        identity_before = (
            value.id,
            tuple(page.id for page in value.pages),
            tuple(element.id for element in value.elements),
            tuple(relationship.id for relationship in value.relationships),
        )
        result = original_private_builder(value)
        assert (
            value.id,
            tuple(page.id for page in value.pages),
            tuple(element.id for element in value.elements),
            tuple(relationship.id for relationship in value.relationships),
        ) == identity_before
        received.append(value)
        return result

    monkeypatch.setattr(ir_service, "build_document_ir", build_spy)
    monkeypatch.setattr(DocumentIR, "model_dump", dump_spy)
    monkeypatch.setattr(
        presentation,
        "_build_canonical_presentation_from_validated",
        private_spy,
    )
    monkeypatch.setattr(
        presentation,
        "build_canonical_presentation",
        lambda *_args, **_kwargs: pytest.fail(
            "reconstructed validated IR re-entered the public builder"
        ),
    )

    validated = _validate_trusted_pair(baseline, candidate)

    assert len(produced) == len(received) == 1
    # This direct producer validates while constructing the model. The
    # presentation path must not allocate a JSON graph merely to validate it
    # a second time.
    assert document_ir_dump_count == 0
    assert strict_json_bytes(
        validated.model_dump(mode="json", exclude_unset=True)
    ) == strict_json_bytes(candidate)


def test_non_outline_table_validation_does_not_dump_whole_parse_result(
    monkeypatch: pytest.MonkeyPatch,
    trusted_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    baseline, candidate = trusted_pair
    baseline_result = ParseResult.model_validate(deepcopy(baseline))

    monkeypatch.setattr(
        ParseResult,
        "model_dump",
        lambda *_args, **_kwargs: pytest.fail(
            "non-outline table validation dumped the whole ParseResult"
        ),
    )

    validated = ParseResult.model_validate(
        deepcopy(candidate),
        context=_trusted_table_validation_context(baseline_result),
    )

    assert isinstance(validated, ParseResult)


def test_reconstructed_public_ir_rejects_nonexact_direct_result(
    monkeypatch: pytest.MonkeyPatch,
    trusted_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    baseline, candidate = trusted_pair
    baseline_result = ParseResult.model_validate(deepcopy(baseline))
    monkeypatch.setattr(
        ir_service,
        "build_document_ir",
        lambda *_args, **_kwargs: object(),
    )

    with pytest.raises(ValueError, match="marked table canonical IR binding differs"):
        ParseResult.model_validate(
            deepcopy(candidate),
            context=_trusted_table_validation_context(baseline_result),
        )


def test_trusted_page_comparison_excludes_items_before_serialization(
    monkeypatch: pytest.MonkeyPatch,
    trusted_pair: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    baseline, candidate = trusted_pair
    baseline_result = ParseResult.model_validate(deepcopy(baseline))
    original_dump = PageResult.model_dump
    exclusions: list[Any] = []

    def page_dump_spy(
        self: PageResult,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        exclusions.append(kwargs.get("exclude"))
        return original_dump(self, *args, **kwargs)

    monkeypatch.setattr(PageResult, "model_dump", page_dump_spy)

    validated = ParseResult.model_validate(
        deepcopy(candidate),
        context=_trusted_table_validation_context(baseline_result),
    )

    assert isinstance(validated, ParseResult)
    assert exclusions
    assert all(exclusion == {"items"} for exclusion in exclusions)


def test_public_presentation_builder_still_revalidates_hostile_models() -> None:
    public_ir = ir_service.build_document_ir(
        {
            "document": {"sha256": "a" * 64},
            "pages": [
                {
                    "page_index": 1,
                    "page_number": 1,
                    "page_width": 612.0,
                    "page_height": 792.0,
                    "unit": "pt",
                    "success": True,
                    "items": [
                        {
                            "id": "p1-text",
                            "type": "text",
                            "reading_order": 0,
                            "value": "grounded",
                            "md": "grounded",
                            "source": "native",
                        }
                    ],
                    "warnings": [],
                }
            ],
        }
    )
    public_ir.pages[0].presentation_element_ids.append("el-hostile-missing")

    with pytest.raises(ValueError, match="presentation element"):
        presentation.build_canonical_presentation(public_ir)
