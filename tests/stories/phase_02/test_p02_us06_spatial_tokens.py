from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config import Settings
from app.services.ocr import (
    ImageRegion,
    OCRLine,
    OCRToken,
    _merge_sparse_ocr_lines_with_diagnostics,
)
from app.services.pipeline import _image_item
from app.services.serializer import to_markdown
from app.services.spatial_tokens import (
    geometry_aware_unique_line_values,
    project_ocr_token_occurrences,
)


YEAR_LABELS = (
    "2015",
    "2020",
    "2025",
    "2015",
    "2020",
    "2025",
    "2015",
    "2020",
    "2025",
    "2015",
    "2020",
    "2025",
)


def _bbox(
    x: float,
    y: float = 10.0,
    width: float = 24.0,
    height: float = 8.0,
) -> dict[str, float]:
    return {"x": x, "y": y, "w": width, "h": height}


def _token(
    text: str,
    bbox: dict[str, float],
    *,
    confidence: float | None = 0.95,
    ocr_pass: str = "standard",
    word_index: int = 0,
) -> OCRToken:
    return OCRToken(
        text=text,
        bbox=dict(bbox),
        crop_pixel_bbox=dict(bbox),
        confidence=confidence,
        ocr_pass=ocr_pass,
        word_index=word_index,
    )


def _line(
    text: str,
    bbox: dict[str, float],
    *,
    confidence: float | None = 0.95,
    ocr_pass: str = "standard",
    tokens: list[OCRToken] | None = None,
) -> OCRLine:
    return OCRLine(
        text=text,
        bbox=dict(bbox),
        confidence=confidence,
        word_count=len(tokens or []) or 1,
        ocr_pass=ocr_pass,
        tokens=(
            tokens
            if tokens is not None
            else [
                _token(
                    text,
                    bbox,
                    confidence=confidence,
                    ocr_pass=ocr_pass,
                )
            ]
        ),
    )


def _diagnostic(
    *,
    accepted: bool = True,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "rejection_reason": rejection_reason,
    }


def _project(
    lines: list[OCRLine],
    diagnostics: list[dict[str, Any]],
    *,
    rejected_lines: list[dict[str, Any]] | None = None,
    page_index: int = 1,
    owner_identity: Any = None,
    owner_bbox: dict[str, float] | None = None,
    owner_content_type: str = "chart",
    include_ocr_in_primary: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return project_ocr_token_occurrences(
        page_index=page_index,
        owner_identity=(
            {
                "source_document_identity": "sha256:catastrophe",
                "region": "exhibit-8",
            }
            if owner_identity is None
            else owner_identity
        ),
        owner_bbox=owner_bbox or _bbox(0.0, 0.0, 600.0, 100.0),
        owner_content_type=owner_content_type,
        coordinate_unit="pt",
        lines=lines,
        line_diagnostics=diagnostics,
        rejected_lines=rejected_lines or [],
        include_ocr_in_primary=include_ocr_in_primary,
        primary_confidence_threshold=0.45,
    )


def test_all_twelve_year_positions_remain_addressable() -> None:
    tokens = [
        _token(
            year,
            _bbox(10.0 + index * 38.0),
            word_index=index,
        )
        for index, year in enumerate(YEAR_LABELS)
    ]
    line = _line(
        " ".join(YEAR_LABELS),
        _bbox(10.0, 10.0, 440.0, 8.0),
        tokens=tokens,
    )

    occurrences, summary = _project([line], [_diagnostic()])

    assert len(occurrences) == 12
    assert [item["text"] for item in occurrences] == list(YEAR_LABELS)
    assert len({item["occurrence_id"] for item in occurrences}) == 12
    assert len({tuple(item["bbox"].values()) for item in occurrences}) == 12
    assert all(item["selected"] for item in occurrences)
    assert all(item["primary_selected"] for item in occurrences)
    assert all(item.get("duplicate_of") is None for item in occurrences)
    assert summary["total_occurrences"] == 12
    assert summary["selected_occurrences"] == 12
    assert summary["duplicate_occurrences"] == 0


def test_overlapping_exact_psm_alternative_has_one_winner_and_diagnostic() -> (
    None
):
    standard = _line("2025", _bbox(40.0), confidence=0.96)
    sparse = _line(
        "2025",
        _bbox(40.5, width=23.5),
        confidence=0.94,
        ocr_pass="sparse",
    )
    rejected = {
        **sparse.to_evidence_dict(),
        "accepted": False,
        "rejection_reason": "overlapping_ocr_candidate",
        "replaced_by": standard.text,
    }

    occurrences, summary = _project(
        [standard],
        [_diagnostic()],
        rejected_lines=[rejected],
    )

    assert len(occurrences) == 2
    winner, loser = occurrences
    assert winner["text"] == loser["text"] == "2025"
    assert winner["selected"] is True
    assert winner["primary_selected"] is True
    assert winner.get("duplicate_of") is None
    assert loser["selected"] is False
    assert loser["primary_selected"] is False
    assert loser["duplicate_of"] == winner["occurrence_id"]
    assert loser["retention_reason"] == (
        "overlapping_equivalent_ocr_diagnostic"
    )
    assert summary["selected_occurrences"] == 1
    assert summary["duplicate_occurrences"] == 1


def test_distant_equal_headers_and_chart_labels_are_not_merged() -> None:
    lines = [
        _line("FY2025", _bbox(10.0, 5.0, 40.0, 8.0)),
        _line("FY2025", _bbox(10.0, 75.0, 40.0, 8.0)),
    ]

    occurrences, summary = _project(
        lines,
        [_diagnostic(), _diagnostic()],
    )
    values = geometry_aware_unique_line_values(
        [(line.text, line.bbox) for line in lines]
    )

    assert values == ["FY2025", "FY2025"]
    assert len(occurrences) == 2
    assert all(item["selected"] for item in occurrences)
    assert all(item.get("duplicate_of") is None for item in occurrences)
    assert summary["duplicate_occurrences"] == 0


def test_equivalence_is_nfc_and_whitespace_only() -> None:
    shared_bbox = _bbox(20.0)
    lines = [
        _line("e\u0301", shared_bbox, confidence=0.97),
        _line("\u00e9", shared_bbox, confidence=0.96),
        _line("A   B", shared_bbox, confidence=0.95),
        _line("A B", shared_bbox, confidence=0.94),
        _line("A", shared_bbox, confidence=0.93),
        _line("\uff21", shared_bbox, confidence=0.92),
        _line("iH", shared_bbox, confidence=0.91),
        _line("IH", shared_bbox, confidence=0.90),
        _line("\u0456H", shared_bbox, confidence=0.89),
    ]

    occurrences, summary = _project(
        lines,
        [_diagnostic() for _line_value in lines],
    )
    by_text = {item["text"]: item for item in occurrences}

    assert by_text["e\u0301"]["selected"] is True
    assert by_text["\u00e9"]["duplicate_of"] == (
        by_text["e\u0301"]["occurrence_id"]
    )
    assert by_text["A   B"]["selected"] is True
    assert by_text["A B"]["duplicate_of"] == (
        by_text["A   B"]["occurrence_id"]
    )
    for distinct in ("A", "\uff21", "iH", "IH", "\u0456H"):
        assert by_text[distinct]["selected"] is True
        assert by_text[distinct].get("duplicate_of") is None
    assert summary["duplicate_occurrences"] == 2


def test_exact_ih_and_1h_grounded_hypotheses_remain_independent_evidence() -> (
    None
):
    lines = [
        _line("iH", _bbox(157.421, 20.0, 14.6, 5.8), confidence=0.4437),
        _line("1H", _bbox(180.0, 20.0, 14.6, 5.8), confidence=0.41),
    ]
    diagnostics = [
        _diagnostic(accepted=False, rejection_reason="low_confidence"),
        _diagnostic(accepted=False, rejection_reason="low_confidence"),
    ]

    for owner_content_type in ("chart", "diagram"):
        occurrences, summary = _project(
            lines,
            diagnostics,
            owner_content_type=owner_content_type,
        )

        assert [item["text"] for item in occurrences] == ["iH", "1H"]
        assert [item["confidence"] for item in occurrences] == [
            0.4437,
            0.41,
        ]
        assert all(item["short_alternative"] for item in occurrences)
        assert all(not item["primary_selected"] for item in occurrences)
        assert all(
            item["retention_reason"] == "grounded_short_alternative"
            for item in occurrences
        )
        assert occurrences[0]["bbox"]["x"] == 157.421
        assert occurrences[0]["bbox"]["w"] == 14.6
        assert (
            occurrences[0]["occurrence_id"]
            != occurrences[1]["occurrence_id"]
        )
        assert summary["short_alternative_occurrences"] == 2


def test_short_alternative_is_presentation_inert_in_image_projection() -> None:
    line = _line(
        "iH",
        _bbox(157.421, 20.0, 14.6, 5.8),
        confidence=0.4437,
    )
    region = ImageRegion(
        page_index=1,
        object_index=8,
        bbox=_bbox(100.0, 0.0, 200.0, 100.0),
        pixel_width=1_000,
        pixel_height=500,
        area_ratio=0.25,
        text="iH",
        lines=[line],
        confidence=0.4437,
        content_type="chart",
        region_role="content_region",
        region_origin="pdf_page_render",
        coordinate_unit="pt",
    )
    settings = Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
    )

    item = _image_item(
        region,
        settings,
        source_document_identity="sha256:catastrophe",
    )
    markdown = to_markdown({"pages": [{"items": [item]}]})

    assert item["value"] == item["md"] == item["ocr_text"] == ""
    assert item["items"][0]["accepted"] is False
    assert item["items"][0]["rejection_reason"] == "low_confidence"
    assert item["ocr_token_occurrences"][0]["text"] == "iH"
    assert item["ocr_token_occurrences"][0]["short_alternative"] is True
    assert item["ocr_token_occurrences"][0]["primary_selected"] is False
    assert "1H" not in str(item)
    assert "iH" not in markdown


def test_rejected_psm_tokens_survive_only_on_enabled_diagnostic_path() -> None:
    standard = _line("Revenue", _bbox(20.0), confidence=0.96)
    sparse = deepcopy(standard)
    sparse.confidence = 0.94
    sparse.ocr_pass = "sparse"
    for token in sparse.tokens:
        token.confidence = 0.94
        token.ocr_pass = "sparse"

    _legacy_merged, legacy_rejected = (
        _merge_sparse_ocr_lines_with_diagnostics([standard], [sparse])
    )
    merged, rejected = _merge_sparse_ocr_lines_with_diagnostics(
        [standard],
        [sparse],
        spatial_token_preservation_enabled=True,
    )
    occurrences, summary = _project(
        merged,
        [_diagnostic()],
        rejected_lines=rejected,
    )

    assert "tokens" not in legacy_rejected[0]
    assert rejected[0]["tokens"][0]["text"] == "Revenue"
    assert rejected[0]["tokens"][0]["ocr_pass"] == "sparse"
    assert len(occurrences) == 2
    assert occurrences[1]["selected"] is False
    assert occurrences[1]["duplicate_of"] == occurrences[0]["occurrence_id"]
    assert summary["duplicate_occurrences"] == 1
