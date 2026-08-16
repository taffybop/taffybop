from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

import pytest

import app.services.source_text_alignment as alignment


def _empty_evidence(*, elapsed_ms: float) -> alignment.SourceTextEvidence:
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
        elapsed_ms=elapsed_ms,
    )


def _empty_page() -> dict[str, Any]:
    return {
        "page_index": 1,
        "page_width": 100.0,
        "page_height": 100.0,
        "items": [],
    }


@pytest.mark.parametrize(
    "pdf_bytes",
    (
        (
            b"<< "
            b"/#44#69#66#66#65#72#65#6E#63#65#73 "
            b"[ 1 /#6F#6E#65#2E#6E#75#6D#72 ] "
            b">>"
        ),
        (
            b"<< /Differences "
            b"[ 1 /#66#5F#6C ] >>"
        ),
        b"<< /Type /#4F#62#6A#53#74#6D >>",
        b"<< /#45#6E#63#72#79#70#74 << >> >>",
    ),
)
def test_type1_preflight_decodes_fully_escaped_relevant_pdf_names(
    pdf_bytes: bytes,
) -> None:
    assert (
        alignment._requires_type1_interpretation(
            pdf_bytes,
            deadline=math.inf,
        )
        is True
    )


@pytest.mark.parametrize(
    "pdf_bytes",
    (
        b"ordinary prose mentions one.numr Differences ObjStm Encrypt",
        b"<< /Comment (one.numr Differences ObjStm Encrypt) >>",
        b"<< /#6F#6E#65#2E#6E#75#6D#72 /Meaning (numerator) >>",
        b"<< /Differences [ 1 (one.numr) ] >>",
    ),
)
def test_marker_like_prose_without_relevant_pdf_name_pair_stays_negative(
    pdf_bytes: bytes,
) -> None:
    assert (
        alignment._requires_type1_interpretation(
            pdf_bytes,
            deadline=math.inf,
        )
        is False
    )


def test_type1_preflight_bounds_long_names_and_honors_deadline() -> None:
    oversized_name = b"a" * (alignment.MAX_GLYPH_NAME_BYTES + 1)
    assert (
        alignment._requires_type1_interpretation(
            b"<< /Differences [ 1 /" + oversized_name + b" ] >>",
            deadline=math.inf,
        )
        is False
    )

    with pytest.raises(alignment._Refusal) as raised:
        alignment._requires_type1_interpretation(
            b"/A " * 128,
            deadline=-math.inf,
        )
    assert raised.value.code == "source_alignment_deadline"


def test_noncandidate_table_cells_cannot_bypass_owner_scan_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(alignment, "MAX_OWNERS", 3)
    monkeypatch.setattr(
        alignment,
        "MAX_SCANNED_OWNERS",
        3,
        raising=False,
    )
    cells = [
        {
            "row": 0,
            "column": column,
            "text": f"ordinary noncandidate cell {column}",
            "bbox": {
                "x": float(column),
                "y": 10.0,
                "width": 1.0,
                "height": 1.0,
            },
        }
        for column in range(8)
    ]
    pages = [
        {
            **_empty_page(),
            "items": [
                {
                    "id": "p1-table",
                    "type": "table",
                    "bbox": {
                        "x": 0.0,
                        "y": 0.0,
                        "width": 20.0,
                        "height": 20.0,
                    },
                    "cells": cells,
                    "rows": [[cell["text"] for cell in cells]],
                }
            ],
        }
    ]
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(
        pages,
        _empty_evidence(elapsed_ms=0.0),
    )

    assert summary.status == "refused"
    assert summary.concerns[0]["reason"] == (
        "source_alignment_owner_scan_limit"
    )
    assert pages == before


@pytest.mark.parametrize(
    ("elapsed_ms", "reason"),
    (
        (math.nan, "source_alignment_evidence_elapsed_invalid"),
        (-0.001, "source_alignment_evidence_elapsed_invalid"),
        (2_000.001, "source_alignment_deadline"),
    ),
)
def test_invalid_or_exhausted_evidence_elapsed_refuses_atomically(
    elapsed_ms: float,
    reason: str,
) -> None:
    pages = [
        {
            **_empty_page(),
            "items": [
                {
                    "id": "sentinel",
                    "type": "text",
                    "value": "must remain unchanged",
                    "bbox": {
                        "x": 1.0,
                        "y": 1.0,
                        "width": 20.0,
                        "height": 5.0,
                    },
                }
            ],
        }
    ]
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(
        pages,
        _empty_evidence(elapsed_ms=elapsed_ms),
    )

    assert summary.status == "refused"
    assert summary.concerns[0]["reason"] == reason
    assert pages == before


def _candidate_selection() -> alignment.SourceTextSelection:
    return alignment.SourceTextSelection(
        text="source candidate",
        raw_text="source raw candidate",
        bbox=alignment.SourceBBox(
            x=1.0,
            y=1.0,
            width=20.0,
            height=5.0,
        ),
        source_line_ids=("synthetic-line",),
        source_character_ids=(),
        source_character_indexes=(),
        type1_evidence_ids=(),
        source_roles=(),
        checks={"bounded_candidate": True},
    )


def _candidate_pages(count: int) -> list[dict[str, Any]]:
    return [
        {
            **_empty_page(),
            "items": [
                {
                    "id": f"owner-{index}",
                    "type": "text",
                    "value": f"original owner {index}",
                    "bbox": {
                        "x": 1.0,
                        "y": 1.0,
                        "width": 20.0,
                        "height": 5.0,
                    },
                }
                for index in range(count)
            ],
        }
    ]


def _install_candidate_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    reserve_count: int,
) -> None:
    selection = _candidate_selection()
    monkeypatch.setattr(
        alignment,
        "text_for_bbox",
        lambda *_args, **_kwargs: selection,
    )
    monkeypatch.setattr(
        alignment,
        "_layout_projection_text",
        lambda *_args, **_kwargs: "source projection candidate",
    )

    def unique_candidate(
        _page: alignment.SourcePageEvidence,
        _original: str,
        _selection: alignment.SourceTextSelection,
        _projection: str,
        *,
        reserve_candidates: Any,
    ) -> bool:
        reserve_candidates(reserve_count)
        return True

    monkeypatch.setattr(
        alignment,
        "_selection_unique_on_page",
        unique_candidate,
    )
    monkeypatch.setattr(
        alignment,
        "_selection_method",
        lambda *_args, **_kwargs: (
            "pdfium_native_text",
            {"synthetic_candidate": True},
        ),
    )


def test_per_owner_candidate_overflow_refuses_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(alignment, "MAX_CANDIDATES_PER_OWNER", 1)
    monkeypatch.setattr(alignment, "MAX_TOTAL_CANDIDATES", 10)
    _install_candidate_path(monkeypatch, reserve_count=2)
    pages = _candidate_pages(1)
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(
        pages,
        _empty_evidence(elapsed_ms=0.0),
    )

    assert summary.status == "refused"
    assert summary.concerns[0]["reason"] == (
        "source_alignment_owner_candidate_limit"
    )
    assert pages == before


def test_global_candidate_overflow_accumulates_across_owners_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(alignment, "MAX_CANDIDATES_PER_OWNER", 1)
    monkeypatch.setattr(alignment, "MAX_TOTAL_CANDIDATES", 1)
    _install_candidate_path(monkeypatch, reserve_count=1)
    pages = _candidate_pages(2)
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(
        pages,
        _empty_evidence(elapsed_ms=0.0),
    )

    assert summary.status == "refused"
    assert summary.concerns[0]["reason"] == (
        "source_alignment_total_candidate_limit"
    )
    assert pages == before


def test_supported_line_space_repair_polls_deadline_while_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_page = alignment.SourcePageEvidence(
        page_index=1,
        page_width=100.0,
        page_height=100.0,
        unit="pt",
        characters=(),
        lines=tuple(
            alignment.SourceTextLine(
                id=f"nonmatching-line-{index}",
                page_index=1,
                text="short",
                raw_text="short",
                bbox=alignment.SourceBBox(
                    x=0.0,
                    y=float(index % 100),
                    width=10.0,
                    height=1.0,
                ),
                source_character_ids=(),
                source_character_indexes=(),
                type1_evidence_ids=(),
                has_unsafe_character=False,
                terminal_semantic_hyphen=False,
            )
            for index in range(128)
        ),
    )
    clock_calls = 0

    def crossing_clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls == 1 else 2.0

    def reject_candidate_reservation(_count: int) -> None:
        raise AssertionError("nonmatching lines cannot reserve candidates")

    monkeypatch.setattr(alignment.time, "perf_counter", crossing_clock)

    with pytest.raises(alignment._Refusal) as raised:
        alignment._supported_line_space_repair(
            "unrelated original owner",
            alignment.SourceBBox(
                x=0.0,
                y=0.0,
                width=20.0,
                height=20.0,
            ),
            source_page,
            reserve_candidates=reject_candidate_reservation,
            deadline=1.0,
        )

    assert raised.value.code == "source_alignment_deadline"
    assert clock_calls == 2


def test_bounded_json_size_observes_exact_utf8_report_limit() -> None:
    limit = alignment.MAX_REPORT_BYTES
    deadline = alignment.time.perf_counter() + 60.0

    for expected_size in (limit - 1, limit):
        value = "é" + ("x" * (expected_size - 4))
        assert (
            alignment._bounded_json_size(
                value,
                max_bytes=limit,
                deadline=deadline,
            )
            == expected_size
        )

    oversized = "é" + ("x" * (limit - 3))
    with pytest.raises(alignment._Refusal) as raised:
        alignment._bounded_json_size(
            oversized,
            max_bytes=limit,
            deadline=deadline,
        )
    assert raised.value.code == "source_alignment_report_size_limit"


@pytest.mark.parametrize(
    "value",
    (
        1e-09,
        2.297681667e-05,
        math.inf,
        -math.inf,
        math.nan,
    ),
    ids=(
        "small-exponent",
        "long-mantissa-exponent",
        "positive-infinity",
        "negative-infinity",
        "nan",
    ),
)
def test_bounded_json_size_matches_public_float_spelling(
    value: float,
) -> None:
    public_size = len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert alignment._bounded_json_size(
        value,
        max_bytes=alignment.MAX_REPORT_BYTES,
        deadline=alignment.time.perf_counter() + 5.0,
    ) == public_size


def test_bounded_json_size_matches_nested_escaped_unicode_mapping() -> None:
    value = {
        "clé\n\"\\": [
            "Babeș-Bolyai",
            {
                "emoji😀": (
                    "\x00\t\r\n\b\f\"\\/ — e\u0301 \u2028 \u2029 雪"
                ),
            },
        ],
    }
    public_size = len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert alignment._bounded_json_size(
        value,
        max_bytes=alignment.MAX_REPORT_BYTES,
        deadline=alignment.time.perf_counter() + 5.0,
    ) == public_size


def test_forged_source_character_uses_exact_bounded_fallback() -> None:
    character = alignment.SourceCharacterEvidence(
        id="source-character-forged",
        page_index=1,
        character_index=0,
        raw_code_point=ord("x"),
        raw_text="x",
        text="é" * (alignment._JSON_STRING_CHUNK_CODEPOINTS + 1),
        bbox=None,
        fill_rgba=None,
        font_ref=None,
        font_size=None,
        baseline=None,
        pdfium_is_hyphen=False,
        space_supported=False,
        excluded_reason=None,
    )
    public_size = len(
        json.dumps(
            character.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert alignment._is_bounded_atomic_json_record(character) is False
    assert alignment._bounded_json_size(
        character,
        max_bytes=public_size,
        deadline=alignment.time.perf_counter() + 5.0,
    ) == public_size
    with pytest.raises(alignment._Refusal) as raised:
        alignment._bounded_json_size(
            character,
            max_bytes=public_size - 1,
            deadline=alignment.time.perf_counter() + 5.0,
        )
    assert raised.value.code == "source_alignment_report_size_limit"


def test_bounded_json_size_refuses_when_encoding_crosses_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock_calls = 0

    def crossing_clock() -> float:
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls == 1 else 2.0

    monkeypatch.setattr(alignment.time, "perf_counter", crossing_clock)

    with pytest.raises(alignment._Refusal) as raised:
        alignment._bounded_json_size(
            list(range(512)),
            max_bytes=alignment.MAX_REPORT_BYTES,
            deadline=1.0,
        )

    assert raised.value.code == "source_alignment_deadline"
    assert clock_calls >= 2


def test_alignment_report_refusal_occurs_before_transaction_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, float, str]] = []

    def delayed_report(
        value: Any,
        *,
        max_bytes: int,
        deadline: float,
        refusal_code: str = "source_alignment_report_size_limit",
    ) -> int:
        calls.append((max_bytes, deadline, refusal_code))
        raise alignment._Refusal("source_alignment_deadline")

    monkeypatch.setattr(alignment, "_bounded_json_size", delayed_report)
    pages = [_empty_page()]
    before = deepcopy(pages)

    summary = alignment.align_pages_to_source(
        pages,
        _empty_evidence(elapsed_ms=0.0),
    )

    assert calls
    assert calls[0][0] == alignment.MAX_REPORT_BYTES
    assert summary.status == "refused"
    assert summary.concerns[0]["reason"] == "source_alignment_deadline"
    assert pages == before
