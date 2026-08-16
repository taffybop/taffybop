"""P04-US01 isolation at the terminal source-alignment boundary."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import pipeline
from app.services import source_text_alignment as alignment


def _evidence() -> alignment.SourceTextEvidence:
    return alignment.SourceTextEvidence(
        schema_version=alignment.SOURCE_TEXT_ALIGNMENT_SCHEMA_VERSION,
        policy_id=alignment.SOURCE_TEXT_ALIGNMENT_POLICY_ID,
        source_sha256="a" * 64,
        usable=True,
        refusal_code=None,
        page_count=1,
        character_count=0,
        line_count=0,
        type1_glyph_count=0,
        pages=(
            alignment.SourcePageEvidence(
                page_index=1,
                page_width=100.0,
                page_height=100.0,
                unit="pt",
                characters=(),
                lines=(),
            ),
        ),
        type1_glyphs=(),
        diagnostics=(),
        elapsed_ms=0.0,
    )


@pytest.mark.parametrize(
    "terminal_reason",
    sorted(alignment.TABLE_OWNED_TERMINAL_REASONS),
)
def test_every_table_owned_terminal_reason_retains_table_dependency(
    terminal_reason: str,
) -> None:
    payload = {
        "processing": {
            "source_text_alignment": {
                "selections": [{"terminal_reason": terminal_reason}],
            }
        }
    }

    assert pipeline._has_table_owned_source_suppression(payload)
    payload["processing"]["source_text_alignment"]["selections"][0][
        "terminal_reason"
    ] = "selected_source_safe_candidate"
    assert not pipeline._has_table_owned_source_suppression(payload)


@pytest.mark.parametrize(
    "status",
    ["valid", "unresolved", "structural_failure", "unknown"],
)
def test_marked_table_never_enters_terminal_text_replacement(
    status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        {
            "page_index": 1,
            "page_width": 100.0,
            "page_height": 100.0,
            "items": [
                {
                    "id": "p1-i1",
                    "type": "table",
                    "bbox": {
                        "x": 0.0,
                        "y": 0.0,
                        "width": 80.0,
                        "height": 20.0,
                    },
                    "rows": [["- 1,234"]],
                    "cells": [
                        {
                            "row": 0,
                            "column": 0,
                            "text": "- 1,234",
                            "bbox": {
                                "x": 1.0,
                                "y": 1.0,
                                "width": 40.0,
                                "height": 10.0,
                            },
                        }
                    ],
                    "table_evidence": {"status": status},
                }
            ],
        }
    ]
    before = deepcopy(pages)

    def unexpected_alignment(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("marked table reached source text selection")

    monkeypatch.setattr(alignment, "text_for_bbox", unexpected_alignment)

    summary = alignment.align_pages_to_source(pages, _evidence())

    assert summary.selected_count == 0
    assert pages == before
