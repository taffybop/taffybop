"""Focused fail-closed contracts for source-grounded visual text."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from app.services.layout import _grounded_primary_visual_source_text
from app.services.visual_source_text import (
    attach_visual_source_text,
    derive_colored_node_topology_evidence,
    infer_source_grounded_chart,
    visual_source_text_primary_eligible,
)


def _source_owner(*, owner_type: str = "chart") -> dict[str, Any]:
    text = "2022 40%\n2023 60%"
    occurrences = [
        {
            "id": "source-token-1",
            "occurrence_id": "source-token-1",
            "text": "2022 40%",
            "bbox": {
                "x": 10.0,
                "y": 20.0,
                "width": 30.0,
                "height": 8.0,
                "unit": "pt",
            },
            "accepted": True,
            "selected": True,
            "source": "native",
        },
        {
            "id": "source-token-2",
            "occurrence_id": "source-token-2",
            "text": "2023 60%",
            "bbox": {
                "x": 10.0,
                "y": 40.0,
                "width": 30.0,
                "height": 8.0,
                "unit": "pt",
            },
            "accepted": True,
            "selected": True,
            "source": "native",
        },
    ]
    return {
        "id": "visual-1",
        "type": owner_type,
        "content_type": owner_type,
        "bbox": {
            "x": 0.0,
            "y": 0.0,
            "width": 100.0,
            "height": 100.0,
            "unit": "pt",
        },
        "visual_structure": {"region": {"kind": owner_type}},
        "visual_source_text": text,
        "visual_source_text_occurrences": occurrences,
        "visual_source_text_lines": [
            {
                "text": "2022 40%",
                "bbox": deepcopy(occurrences[0]["bbox"]),
                "source_token_ids": ["source-token-1"],
            },
            {
                "text": "2023 60%",
                "bbox": deepcopy(occurrences[1]["bbox"]),
                "source_token_ids": ["source-token-2"],
            },
        ],
        "meta": {
            "phase05_visual_source_text": {
                "method": "pdf_text_layer_inside_visual_bbox",
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "occurrence_count": 2,
                "promoted_primary": True,
            }
        },
    }


def test_layout_admits_complete_hashed_same_unit_visual_source_text() -> None:
    owner = _source_owner()

    assert _grounded_primary_visual_source_text(owner) == (
        owner["visual_source_text"],
        None,
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda owner: owner["meta"]["phase05_visual_source_text"].update(
                {"text_sha256": "0" * 64}
            ),
            "visual_source_metadata_mismatch",
        ),
        (
            lambda owner: owner["visual_source_text_occurrences"][0]["bbox"].update(
                {"x": 99.0, "width": 2.0}
            ),
            "visual_source_occurrence_invalid",
        ),
        (
            lambda owner: owner["visual_source_text_lines"][1].update(
                {"source_token_ids": ["source-token-1"]}
            ),
            "visual_source_lineage_mismatch",
        ),
        (
            lambda owner: owner["visual_source_text_lines"].pop(),
            "visual_source_lineage_mismatch",
        ),
    ],
)
def test_layout_rejects_forged_unbounded_or_incomplete_visual_source_lineage(
    mutation: Any,
    reason: str,
) -> None:
    owner = _source_owner()
    mutation(owner)

    assert _grounded_primary_visual_source_text(owner) == ("", reason)


def test_layout_never_promotes_visual_source_text_for_an_arbitrary_image() -> None:
    owner = _source_owner(owner_type="image")

    assert _grounded_primary_visual_source_text(owner) == (
        "",
        "visual_source_owner_not_routed",
    )


def test_promoted_visual_source_text_preserves_boolean_detection_contract() -> None:
    text = "Exact native chart text"
    projected = attach_visual_source_text(
        {
            "type": "chart",
            "value": "noisy OCR",
            "md": "noisy OCR",
            "detected_text": True,
            "source": "ocr",
        },
        {
            "method": "pdf_text_layer_inside_visual_bbox",
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "occurrences": [],
            "lines": [],
        },
        promote_primary=True,
    )

    assert projected["value"] == projected["md"] == text
    assert projected["detected_text"] is True
    assert type(projected["detected_text"]) is bool
    assert projected["visual_source_text"] == text


def _image_with_source_text(text: str, *, ocr_text: str = "") -> dict[str, Any]:
    return {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": {"x": 0, "y": 0, "width": 200, "height": 100, "unit": "pt"},
        "visual_source_text": text,
        "ocr_text": ocr_text,
    }


def test_source_chart_signatures_are_explicit_and_keep_photos_forms_tables_out() -> None:
    assert infer_source_grounded_chart(
        _image_with_source_text(
            "Purchased cooling <1% electricity 7% Purchased steam <1% Fuel 21%"
        )
    )
    assert infer_source_grounded_chart(
        _image_with_source_text(
            "FY24 0.2 2.4 8.4 0.8 11.8\n"
            "CY23 0.2 2.4 8.4 0.4 11.4\n"
            "CY22 0.2 2.4 8.3 0.2 11.1\n"
            "CY21 0.2 2.3 7.5 0.0 10.0"
        )
    )
    assert infer_source_grounded_chart(
        _image_with_source_text(
            "$82B\n$56B\n1",
            ocr_text="2022 2023 2024 Q1'25 ARR",
        )
    )

    natural_photo = _image_with_source_text(
        "Board meeting photo 2022 2023 with $82B and $56B signs"
    )
    board = _image_with_source_text(
        "TP1 TP2 TP3 D1 D2 1 2 3 4 5 36 37 38 39 40"
    )
    form = {
        **_image_with_source_text("Policy 2022 2023 Total $82B $56B"),
        "fields": [{"name": "policy"}],
    }
    table = {
        **_image_with_source_text("2022 2023 2024 Total 10 20 30"),
        "rows": [["2022", "10"]],
    }
    assert not infer_source_grounded_chart(natural_photo)
    assert not infer_source_grounded_chart(board)
    assert not infer_source_grounded_chart(form)
    assert not infer_source_grounded_chart(table)


def test_native_primary_is_withheld_when_ocr_has_missing_year_categories() -> None:
    source = {
        "text": "$82B\n$56B\n1",
        "occurrences": [{"text": "$82B"}] * 4,
    }
    item = {"ocr_text": "2022 2023 2024 Q1'25 ARR"}

    assert visual_source_text_primary_eligible(item, source) is False


def test_native_primary_is_withheld_for_a_fused_fiscal_year_footnote() -> None:
    source = {
        "text": "FY245 0.2 2.4 8.4\nCY23 0.2 2.4 8.4",
        "occurrences": [{"text": "FY245"}] * 4,
    }

    assert visual_source_text_primary_eligible({}, source) is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: item.update({"type": "chart", "content_type": "chart"}),
        lambda item: item.update({"region_role": "decorative"}),
        lambda item: item.update({"fields": [{"name": "policy"}]}),
        lambda item: item.update({"rows": [["2022", "10"]]}),
    ],
)
def test_colored_node_routing_rejects_nonimage_decorative_form_and_table_owners(
    mutation: Any,
) -> None:
    item = {
        "type": "image",
        "content_type": "image",
        "region_role": "content_region",
        "bbox": {"x": 0, "y": 0, "width": 100, "height": 100, "unit": "pt"},
        "visual_source_text_occurrences": [
            {
                "id": "token-1",
                "occurrence_id": "token-1",
                "text": "Node",
                "bbox": {"x": 10, "y": 10, "width": 10, "height": 10, "unit": "pt"},
            }
        ],
    }
    mutation(item)

    assert derive_colored_node_topology_evidence(
        item,
        source_pdf_bytes=b"not-a-pdf",
        page_index=1,
    ) is None
