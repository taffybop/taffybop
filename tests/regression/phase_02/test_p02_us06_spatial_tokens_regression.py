from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.services.ocr import ImageRegion, OCRLine, OCRToken
from app.services.pipeline import _image_item, _visual_item
from app.services.serializer import to_markdown
from app.services import spatial_tokens as spatial_module
from app.services.spatial_tokens import (
    MAX_SPATIAL_OCCURRENCE_JSON_BYTES,
    MAX_SPATIAL_SHORT_ALTERNATIVES,
    MAX_SPATIAL_TOKEN_OCCURRENCES,
    MAX_SPATIAL_TOKEN_TEXT_CHARS,
    project_ocr_token_occurrences,
)
from tests.benchmarks.numeric_cleanup_metrics import (
    EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256,
    EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256,
    RETAINED_CATASTROPHE_OUTPUT,
)
from tests.stories.phase_02.test_p02_us06_spatial_tokens import (
    _bbox,
    _diagnostic,
    _line,
    _project,
    _token,
)


WORKSPACE = Path(__file__).resolve().parents[3]


def _settings() -> Settings:
    return Settings(
        ocr_numeric_cleanup_v2_enabled=True,
        ocr_spatial_token_preservation_enabled=True,
    )


def _region(
    *,
    content_type: str,
    area_ratio: float,
    line_bbox: dict[str, float],
    token_bbox: dict[str, float],
    confidence: float,
) -> ImageRegion:
    line = _line(
        "iH",
        line_bbox,
        confidence=confidence,
        tokens=[
            _token(
                "iH",
                token_bbox,
                confidence=confidence,
            )
        ],
    )
    return ImageRegion(
        page_index=1,
        object_index=1,
        bbox=_bbox(0.0, 0.0, 200.0, 100.0),
        pixel_width=800,
        pixel_height=400,
        area_ratio=area_ratio,
        text="iH",
        lines=[line],
        confidence=confidence,
        content_type=content_type,
        region_role=None,
        region_origin="fixture",
        coordinate_unit="pt",
    )


def test_retained_catastrophe_ih_evidence_is_hash_path_and_value_exact() -> (
    None
):
    artifact = WORKSPACE / RETAINED_CATASTROPHE_OUTPUT
    content = artifact.read_bytes()
    payload = json.loads(content)
    detected = payload["pages"][0]["detected_images"][1]["items"][20]
    shared_ir = payload["pages"][0]["items"][4]["items"][20]
    expected = {
        "accepted": False,
        "bbox": {
            "x": 157.421,
            "y": 575.71,
            "w": 14.6,
            "h": 5.8,
            "width": 14.6,
            "height": 5.8,
            "unit": "pt",
        },
        "confidence": 0.4437,
        "rejection_reason": "low_confidence",
        "source": "ocr",
        "text": "iH",
        "value": "iH",
        "word_count": 1,
    }

    assert hashlib.sha256(content).hexdigest() == (
        EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    )
    assert payload["document"]["sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256
    )
    assert detected == shared_ir == expected

    occurrences, summary = project_ocr_token_occurrences(
        page_index=1,
        owner_identity={
            "source_document_identity": payload["document"]["sha256"],
            "region": "exhibit-8",
        },
        owner_bbox=_bbox(100.0, 500.0, 200.0, 150.0),
        owner_content_type="chart",
        coordinate_unit="pt",
        lines=[detected],
        line_diagnostics=[detected],
        include_ocr_in_primary=False,
        primary_confidence_threshold=0.45,
    )

    assert len(occurrences) == 1
    assert occurrences[0]["text"] == "iH"
    assert occurrences[0]["bbox"] == expected["bbox"]
    assert occurrences[0]["confidence"] == 0.4437
    assert occurrences[0]["short_alternative"] is True
    assert occurrences[0]["primary_selected"] is False
    assert "1H" not in str(occurrences)
    assert summary["short_alternative_occurrences"] == 1


@pytest.mark.parametrize(
    ("case_id", "region"),
    (
        (
            "generic_photo",
            _region(
                content_type="image",
                area_ratio=0.20,
                line_bbox=_bbox(20.0),
                token_bbox=_bbox(20.0),
                confidence=0.4437,
            ),
        ),
        (
            "page_source",
            _region(
                content_type="image",
                area_ratio=0.95,
                line_bbox=_bbox(20.0),
                token_bbox=_bbox(20.0),
                confidence=0.4437,
            ),
        ),
        (
            "outside_chart",
            _region(
                content_type="chart",
                area_ratio=0.20,
                line_bbox=_bbox(250.0),
                token_bbox=_bbox(250.0),
                confidence=0.4437,
            ),
        ),
        (
            "below_short_floor",
            _region(
                content_type="chart",
                area_ratio=0.20,
                line_bbox=_bbox(20.0),
                token_bbox=_bbox(20.0),
                confidence=0.2924,
            ),
        ),
    ),
)
def test_unsupported_short_noise_is_neither_flagged_nor_canonical(
    case_id: str,
    region: ImageRegion,
) -> None:
    item = _image_item(
        deepcopy(region),
        _settings(),
        source_document_identity=f"sha256:{case_id}",
    )

    assert item["ocr_occurrence_summary"][
        "short_alternative_occurrences"
    ] == 0
    assert all(
        not occurrence["short_alternative"]
        for occurrence in item["ocr_token_occurrences"]
    )
    assert item["value"] == item["md"] == item["ocr_text"] == ""
    assert "iH" not in to_markdown({"pages": [{"items": [item]}]})


def test_invalid_short_token_geometry_is_omitted_and_counted() -> None:
    item = _image_item(
        _region(
            content_type="chart",
            area_ratio=0.20,
            line_bbox=_bbox(20.0),
            token_bbox=_bbox(math.nan),
            confidence=0.4437,
        ),
        _settings(),
        source_document_identity="sha256:invalid-geometry",
    )

    assert item["ocr_token_occurrences"] == []
    assert item["ocr_occurrence_summary"]["invalid_occurrences"] == 1
    assert item["ocr_occurrence_summary"][
        "short_alternative_occurrences"
    ] == 0
    assert item["value"] == item["md"] == item["ocr_text"] == ""
    assert "iH" not in to_markdown({"pages": [{"items": [item]}]})


def test_only_low_confidence_rejection_can_ground_a_short_alternative() -> (
    None
):
    line = _line("iH", _bbox(20.0), confidence=0.4437)

    occurrences, summary = _project(
        [line],
        [
            _diagnostic(
                accepted=False,
                rejection_reason="unsupported_glyph_only",
            )
        ],
    )

    assert len(occurrences) == 1
    assert occurrences[0]["short_alternative"] is False
    assert occurrences[0]["retention_reason"] == (
        "quality_rejected_diagnostic"
    )
    assert summary["short_alternative_occurrences"] == 0


def test_short_grounding_requires_exact_source_match_and_token_confidence() -> (
    None
):
    whitespace_source = _line(
        " iH ",
        _bbox(20.0),
        confidence=0.4437,
    )
    missing_token_confidence = _line(
        "1H",
        _bbox(60.0),
        confidence=0.4437,
        tokens=[
            _token(
                "1H",
                _bbox(60.0),
                confidence=None,
            )
        ],
    )

    occurrences, summary = _project(
        [whitespace_source, missing_token_confidence],
        [
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
        ],
    )
    by_text = {occurrence["text"]: occurrence for occurrence in occurrences}

    assert by_text[" iH "]["short_alternative"] is False
    assert by_text["1H"]["confidence"] is None
    assert by_text["1H"]["short_alternative"] is False
    assert summary["short_alternative_occurrences"] == 0


def test_short_confidence_and_owner_containment_boundaries_are_inclusive() -> (
    None
):
    confidence_boundary = _line(
        "iH",
        _bbox(20.0),
        confidence=0.2925,
    )
    containment_boundary = _line(
        "1H",
        _bbox(-1.0, width=20.0),
        confidence=0.4437,
    )
    below_containment = _line(
        "2H",
        _bbox(-1.001, width=20.0),
        confidence=0.4437,
    )

    occurrences, summary = _project(
        [
            confidence_boundary,
            containment_boundary,
            below_containment,
        ],
        [
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
        ],
        owner_bbox=_bbox(0.0, 0.0, 200.0, 100.0),
    )
    by_text = {occurrence["text"]: occurrence for occurrence in occurrences}

    assert by_text["iH"]["short_alternative"] is True
    assert by_text["1H"]["short_alternative"] is True
    assert by_text["2H"]["short_alternative"] is False
    assert summary["short_alternative_occurrences"] == 2


def test_accepted_line_beats_quality_rejected_overlap_when_not_primary() -> (
    None
):
    accepted = _line("2025", _bbox(20.0), confidence=0.80)
    quality_rejected = _line("2025", _bbox(20.0), confidence=0.99)

    occurrences, summary = _project(
        [accepted, quality_rejected],
        [
            _diagnostic(accepted=True),
            _diagnostic(
                accepted=False,
                rejection_reason="quality_rejected",
            ),
        ],
        include_ocr_in_primary=False,
    )

    assert occurrences[0]["selected"] is True
    assert occurrences[0].get("duplicate_of") is None
    assert occurrences[1]["selected"] is False
    assert occurrences[1]["duplicate_of"] == (
        occurrences[0]["occurrence_id"]
    )
    assert summary["selected_occurrences"] == 1
    assert summary["duplicate_occurrences"] == 1


def test_reciprocal_overlap_requires_eighty_percent_of_both_boxes() -> None:
    first = _line("2025", _bbox(0.0, width=10.0, height=10.0))
    exact_boundary = _line(
        "2025",
        _bbox(2.0, width=8.0, height=10.0),
    )
    overlap_of_smaller_only = _line(
        "2025",
        _bbox(4.0, width=2.0, height=10.0),
    )

    boundary_occurrences, boundary_summary = _project(
        [first, exact_boundary],
        [_diagnostic(), _diagnostic()],
    )
    smaller_occurrences, smaller_summary = _project(
        [first, overlap_of_smaller_only],
        [_diagnostic(), _diagnostic()],
    )

    assert boundary_summary["duplicate_occurrences"] == 1
    assert sum(
        occurrence["selected"] for occurrence in boundary_occurrences
    ) == 1
    assert smaller_summary["duplicate_occurrences"] == 0
    assert all(
        occurrence["selected"] for occurrence in smaller_occurrences
    )


def test_decimal_overlap_boundary_is_inclusive_for_lines_and_tokens() -> None:
    first_bbox = _bbox(0.0, 0.0, 0.1, 0.1)
    boundary_bbox = _bbox(0.02, 0.0, 0.1, 0.1)

    assert spatial_module.geometry_aware_unique_line_values(
        [("2025", first_bbox), ("2025", boundary_bbox)],
    ) == ["2025"]

    occurrences, summary = _project(
        [
            _line("2025", first_bbox),
            _line("2025", boundary_bbox),
        ],
        [_diagnostic(), _diagnostic()],
    )

    assert summary["duplicate_occurrences"] == 1
    assert sum(item["selected"] for item in occurrences) == 1


def test_decimal_owner_containment_boundary_is_inclusive() -> None:
    exact_boundary = _line(
        "1H",
        _bbox(-0.859, 10.0, 17.18, 8.0),
        confidence=0.4437,
    )
    below_boundary = _line(
        "2H",
        _bbox(-0.860, 30.0, 17.18, 8.0),
        confidence=0.4437,
    )

    occurrences, summary = _project(
        [exact_boundary, below_boundary],
        [
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
            _diagnostic(accepted=False, rejection_reason="low_confidence"),
        ],
        owner_bbox=_bbox(0.0, 0.0, 200.0, 100.0),
    )
    by_text = {item["text"]: item for item in occurrences}

    assert by_text["1H"]["short_alternative"] is True
    assert by_text["2H"]["short_alternative"] is False
    assert summary["short_alternative_occurrences"] == 1


def test_occurrence_ids_are_stable_and_bind_every_document_scope_dimension() -> (
    None
):
    base_line = _line("2025", _bbox(20.0), confidence=0.95)

    def occurrence_id(
        *,
        page_index: int = 1,
        owner_identity: Any = None,
        owner_bbox: dict[str, float] | None = None,
        line: OCRLine | None = None,
    ) -> str:
        occurrences, _summary = _project(
            [deepcopy(line or base_line)],
            [_diagnostic()],
            page_index=page_index,
            owner_identity=(
                {
                    "region": "chart-1",
                    "source_document_identity": "sha256:source-a",
                }
                if owner_identity is None
                else owner_identity
            ),
            owner_bbox=owner_bbox or _bbox(0.0, 0.0, 200.0, 100.0),
        )
        return str(occurrences[0]["occurrence_id"])

    first = occurrence_id()
    reordered_owner = occurrence_id(
        owner_identity={
            "source_document_identity": "sha256:source-a",
            "region": "chart-1",
        }
    )
    different_text = deepcopy(base_line)
    different_text.text = "2026"
    different_text.tokens[0].text = "2026"
    different_bbox = deepcopy(base_line)
    different_bbox.tokens[0].bbox["x"] = 21.0
    different_word = deepcopy(base_line)
    different_word.tokens[0].word_index = 1
    different_crop = deepcopy(base_line)
    different_crop.tokens[0].crop_pixel_bbox["x"] = 21.0

    assert first == occurrence_id()
    assert first == reordered_owner
    assert len(first) == len("ocr-token-") + 64
    distinct = {
        occurrence_id(page_index=2),
        occurrence_id(
            owner_identity={
                "region": "chart-1",
                "source_document_identity": "sha256:source-b",
            }
        ),
        occurrence_id(owner_bbox=_bbox(1.0, 0.0, 200.0, 100.0)),
        occurrence_id(line=different_text),
        occurrence_id(line=different_bbox),
        occurrence_id(line=different_word),
        occurrence_id(line=different_crop),
    }
    assert first not in distinct
    assert len(distinct) == 7


def test_occurrence_id_is_stable_across_fresh_python_processes() -> None:
    script = """
from app.services.spatial_tokens import project_ocr_token_occurrences
bbox = {"x": 20.0, "y": 10.0, "w": 24.0, "h": 8.0}
line = {
    "text": "2025",
    "bbox": bbox,
    "confidence": 0.95,
    "ocr_pass": "standard",
    "tokens": [{
        "text": "2025",
        "bbox": bbox,
        "crop_pixel_bbox": bbox,
        "confidence": 0.95,
        "ocr_pass": "standard",
        "word_index": 0,
    }],
}
occurrences, _summary = project_ocr_token_occurrences(
    page_index=1,
    owner_identity={
        "source_document_identity": "sha256:source-a",
        "region": "chart-1",
    },
    owner_bbox={"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0},
    owner_content_type="chart",
    coordinate_unit="pt",
    lines=[line],
    line_diagnostics=[{"accepted": True, "rejection_reason": None}],
    include_ocr_in_primary=True,
    primary_confidence_threshold=0.45,
)
print(occurrences[0]["occurrence_id"])
"""
    first = subprocess.check_output(
        [sys.executable, "-c", script],
        cwd=WORKSPACE,
        text=True,
    ).strip()
    second = subprocess.check_output(
        [sys.executable, "-c", script],
        cwd=WORKSPACE,
        text=True,
    ).strip()

    assert first == second
    assert first.startswith("ocr-token-")
    assert len(first) == len("ocr-token-") + 64


@pytest.mark.parametrize(
    "invalid_bbox",
    (
        {"x": math.nan, "y": 0.0, "w": 10.0, "h": 10.0},
        {"x": 0.0, "y": math.inf, "w": 10.0, "h": 10.0},
        {"x": 0.0, "y": 0.0, "w": 0.0, "h": 10.0},
        {"x": 0.0, "y": 0.0, "w": -1.0, "h": 10.0},
        {"x": 0.0, "y": 0.0, "w": 10.0, "h": -1.0},
        {"x": "not-a-number", "y": 0.0, "w": 10.0, "h": 10.0},
    ),
)
def test_malformed_and_nonfinite_token_geometry_fails_closed(
    invalid_bbox: dict[str, Any],
) -> None:
    line = _line(
        "Token",
        _bbox(0.0),
        tokens=[
            OCRToken(
                text="Token",
                bbox=invalid_bbox,
                crop_pixel_bbox=_bbox(0.0),
                confidence=0.95,
                ocr_pass="standard",
                word_index=0,
            )
        ],
    )

    occurrences, summary = _project([line], [_diagnostic()])

    assert occurrences == []
    assert summary["invalid_occurrences"] == 1
    assert summary["total_occurrences"] == 0
    assert summary["selected_occurrences"] == 0


def test_positive_geometry_that_rounds_to_zero_fails_closed() -> None:
    line = _line(
        "Token",
        _bbox(0.0),
        tokens=[
            _token(
                "Token",
                _bbox(0.0, width=0.0004, height=0.0004),
            )
        ],
    )

    occurrences, summary = _project([line], [_diagnostic()])

    assert occurrences == []
    assert summary["invalid_occurrences"] == 1
    assert summary["total_occurrences"] == 0


def test_invalid_coordinate_unit_fails_closed_instead_of_relabeling() -> None:
    line = _line("Token", _bbox(20.0))

    occurrences, summary = project_ocr_token_occurrences(
        page_index=1,
        owner_identity={
            "source_document_identity": "sha256:source",
            "region": "chart-1",
        },
        owner_bbox=_bbox(0.0, 0.0, 200.0, 100.0),
        owner_content_type="chart",
        coordinate_unit="cm",
        lines=[line],
        line_diagnostics=[_diagnostic()],
        include_ocr_in_primary=True,
        primary_confidence_threshold=0.45,
    )

    assert occurrences == []
    assert summary["invalid_occurrences"] == 1
    assert summary["total_occurrences"] == 0


def test_invalid_line_geometry_omits_every_token_without_partial_promotion() -> (
    None
):
    tokens = [
        _token("A", _bbox(1.0), word_index=0),
        _token("B", _bbox(20.0), word_index=1),
    ]
    line = _line(
        "A B",
        {"x": 0.0, "y": 0.0, "w": math.inf, "h": 10.0},
        tokens=tokens,
    )

    occurrences, summary = _project([line], [_diagnostic()])

    assert occurrences == []
    assert summary["invalid_occurrences"] == 2
    assert summary["primary_selected_occurrences"] == 0


def test_primary_selected_tracks_the_actual_retained_overlapping_line() -> (
    None
):
    retained = _line(
        "AB",
        _bbox(20.0, 20.0, 20.0, 10.0),
        confidence=0.95,
        tokens=[
            _token(
                "AB",
                _bbox(20.0, 20.0, 20.0, 10.0),
                confidence=0.95,
            )
        ],
    )
    line_deduplicated = _line(
        "AB",
        _bbox(20.0, 20.0, 20.0, 10.0),
        confidence=0.94,
        tokens=[
            _token(
                "A",
                _bbox(20.0, 20.0, 10.0, 10.0),
                confidence=0.94,
                word_index=0,
            ),
            _token(
                "B",
                _bbox(30.0, 20.0, 10.0, 10.0),
                confidence=0.94,
                word_index=1,
            ),
        ],
    )
    region = ImageRegion(
        page_index=1,
        object_index=1,
        bbox=_bbox(0.0, 0.0, 100.0, 100.0),
        pixel_width=400,
        pixel_height=400,
        area_ratio=0.25,
        lines=[retained, line_deduplicated],
        content_type="chart",
        region_role="content_region",
        coordinate_unit="pt",
    )
    raw_item = {
        "self_ref": "#/pictures/0",
        "label": "chart",
        "prov": [
            {
                "page_no": 1,
                "bbox": {
                    "l": 0.0,
                    "t": 0.0,
                    "r": 100.0,
                    "b": 100.0,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }

    _page_index, item = _visual_item(
        raw_item,
        "chart",
        {},
        {1: 200.0},
        {1: [region]},
        _settings(),
        source_document_identity="sha256:source",
    )
    by_text = {
        occurrence["text"]: occurrence
        for occurrence in item["ocr_token_occurrences"]
    }

    assert item["value"] == item["ocr_text"] == "AB"
    assert by_text["AB"]["primary_selected"] is True
    assert by_text["A"]["primary_selected"] is False
    assert by_text["B"]["primary_selected"] is False
    assert item["ocr_occurrence_summary"][
        "primary_selected_occurrences"
    ] == 1


def test_nonfinite_document_identity_fails_closed_before_id_generation() -> (
    None
):
    occurrences, summary = _project(
        [_line("2025", _bbox(20.0))],
        [_diagnostic()],
        owner_identity={
            "source_document_identity": "sha256:source",
            "score": math.nan,
        },
    )

    assert occurrences == []
    assert summary["invalid_occurrences"] == 1
    assert summary["total_occurrences"] == 0


def test_token_text_bound_keeps_256_codepoints_and_omits_257() -> None:
    exact = "A" * MAX_SPATIAL_TOKEN_TEXT_CHARS
    oversized = "B" * (MAX_SPATIAL_TOKEN_TEXT_CHARS + 1)
    line = _line(
        "bounded tokens",
        _bbox(0.0, width=100.0),
        tokens=[
            _token(exact, _bbox(0.0), word_index=0),
            _token(oversized, _bbox(40.0), word_index=1),
        ],
    )

    occurrences, summary = _project([line], [_diagnostic()])

    assert [occurrence["text"] for occurrence in occurrences] == [exact]
    assert len(occurrences[0]["text"]) == 256
    assert summary["oversized_text_occurrences"] == 1
    assert summary["truncated_occurrences"] == 0


def test_short_alternative_bound_retains_exactly_256() -> None:
    tokens = [
        _token(
            "iH",
            _bbox(float(index * 4), width=3.0),
            confidence=0.4437,
            word_index=index,
        )
        for index in range(MAX_SPATIAL_SHORT_ALTERNATIVES + 1)
    ]
    line = _line(
        "short alternatives",
        _bbox(0.0, width=2_000.0),
        confidence=0.4437,
        tokens=tokens,
    )

    occurrences, summary = _project(
        [line],
        [_diagnostic(accepted=False, rejection_reason="low_confidence")],
        owner_bbox=_bbox(0.0, 0.0, 2_000.0, 100.0),
    )

    assert len(occurrences) == MAX_SPATIAL_SHORT_ALTERNATIVES
    assert all(item["short_alternative"] for item in occurrences)
    assert summary["short_alternative_occurrences"] == 256
    assert summary["short_alternative_limit_reached"] is True
    assert summary["truncated_occurrences"] == 1


def test_occurrence_bound_retains_exactly_2048_when_measured_in_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        spatial_module,
        "MAX_SPATIAL_OCCURRENCE_JSON_BYTES",
        4 * MAX_SPATIAL_OCCURRENCE_JSON_BYTES,
    )
    tokens = [
        _token(
            f"T{index:04d}",
            _bbox(float(index * 2), width=1.0),
            word_index=index,
        )
        for index in range(MAX_SPATIAL_TOKEN_OCCURRENCES + 2)
    ]
    line = _line(
        "bounded occurrences",
        _bbox(0.0, width=5_000.0),
        tokens=tokens,
    )

    occurrences, summary = _project(
        [line],
        [_diagnostic()],
        owner_bbox=_bbox(0.0, 0.0, 5_000.0, 100.0),
    )

    assert len(occurrences) == MAX_SPATIAL_TOKEN_OCCURRENCES
    assert summary["total_occurrences"] == 2_048
    assert summary["occurrence_limit_reached"] is True
    assert summary["truncated_occurrences"] == 2


def test_one_mib_payload_bound_truncates_deterministically() -> None:
    tokens = [
        _token(
            f"{index:04d}" + ("X" * 252),
            _bbox(float(index * 2), width=1.0),
            word_index=index,
        )
        for index in range(2_000)
    ]
    line = _line(
        "serialized payload bound",
        _bbox(0.0, width=5_000.0),
        tokens=tokens,
    )

    first_occurrences, first_summary = _project(
        [line],
        [_diagnostic()],
        owner_bbox=_bbox(0.0, 0.0, 5_000.0, 100.0),
    )
    second_occurrences, second_summary = _project(
        [deepcopy(line)],
        [_diagnostic()],
        owner_bbox=_bbox(0.0, 0.0, 5_000.0, 100.0),
    )
    serialized = json.dumps(
        first_occurrences,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert 0 < len(first_occurrences) < len(tokens)
    assert first_summary["serialized_byte_limit_reached"] is True
    assert first_summary["truncated_occurrences"] > 0
    assert first_summary["fail_closed_overflow"] is False
    assert first_summary["serialized_occurrence_bytes"] == len(serialized)
    assert len(serialized) <= MAX_SPATIAL_OCCURRENCE_JSON_BYTES
    assert first_occurrences == second_occurrences
    assert first_summary == second_summary


def test_forced_final_overflow_omits_item_array_and_keeps_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dumps = spatial_module.json.dumps

    def undercount_probe(value: Any, *args: Any, **kwargs: Any) -> str:
        if (
            isinstance(value, dict)
            and "occurrence_id" in value
            and value.get("retention_reason")
            == "overlapping_equivalent_ocr_diagnostic"
        ):
            return "{}"
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(spatial_module.json, "dumps", undercount_probe)
    monkeypatch.setattr(
        spatial_module,
        "MAX_SPATIAL_OCCURRENCE_JSON_BYTES",
        1_000,
    )
    tokens = [
        _token(
            f"T{index}",
            _bbox(float(20 + index * 30)),
            word_index=index,
        )
        for index in range(4)
    ]
    region = ImageRegion(
        page_index=1,
        object_index=1,
        bbox=_bbox(0.0, 0.0, 200.0, 100.0),
        pixel_width=800,
        pixel_height=400,
        area_ratio=0.25,
        text="T0 T1 T2 T3",
        lines=[
            _line(
                "T0 T1 T2 T3",
                _bbox(20.0, width=120.0),
                tokens=tokens,
            )
        ],
        content_type="chart",
        region_role="content_region",
        coordinate_unit="pt",
    )

    item = _image_item(
        region,
        _settings(),
        source_document_identity="sha256:overflow",
    )

    assert "ocr_token_occurrences" not in item
    assert item["ocr_occurrence_summary"]["fail_closed_overflow"] is True
    assert item["ocr_occurrence_summary"]["overflow_reason"] == (
        "serialized_payload_exceeded"
    )
    assert item["ocr_occurrence_summary"][
        "serialized_byte_limit_reached"
    ] is True
    assert item["value"] == item["md"] == item["ocr_text"] == "T0 T1 T2 T3"
