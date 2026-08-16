from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from app.services import ocr as ocr_module
from app.services.ocr import (
    ImageRegion,
    OCRLine,
    _build_lines,
    _clean_ocr_line,
    _merge_sparse_ocr_lines_with_diagnostics,
    _set_region_text,
)
from tests.benchmarks.numeric_cleanup_metrics import (
    EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256,
    EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256,
    OBSERVED_LEGACY_FALSE_JOIN,
    OBSERVED_YEAR_BBOX,
    OBSERVED_YEAR_LINE,
    OBSERVED_YEAR_TOKENS,
    RETAINED_CATASTROPHE_OUTPUT,
    bound_cases,
    retained_catastrophe_binding,
)


WORKSPACE = Path(__file__).resolve().parents[3]


def _tsv(words: tuple[str, ...]) -> str:
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext"
    )
    return "\n".join(
        (
            header,
            *(
                "5\t1\t1\t1\t1\t"
                f"{index}\t{10 + index * 28}\t20\t24\t10\t95\t{word}"
                for index, word in enumerate(words, 1)
            ),
        )
    )


def _line(words: tuple[str, ...], *, enabled: bool = True) -> OCRLine:
    options = (
        {"numeric_cleanup_v2_enabled": True}
        if enabled
        else {}
    )
    return _build_lines(
        _tsv(words),
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
        **options,
    )[0]


def _recursive_matches(value: Any, expected: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("text") == expected:
            matches.append(value)
        for child in value.values():
            matches.extend(_recursive_matches(child, expected))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_recursive_matches(child, expected))
    return matches


def test_retained_catastrophe_binding_is_exact_and_not_synthetic() -> None:
    binding = retained_catastrophe_binding(WORKSPACE)

    assert binding["artifact"]["sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    )
    assert binding["source_sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256
    )
    assert binding["observed_source_tokens"] == list(OBSERVED_YEAR_TOKENS)
    assert binding["word_count"] == 12
    assert binding["matching_diagnostic_surface_count"] == 2
    assert binding["bbox"] == OBSERVED_YEAR_BBOX
    assert binding["legacy_false_join"] == OBSERVED_LEGACY_FALSE_JOIN


def test_retained_catastrophe_artifact_contains_two_identical_diagnostic_surfaces() -> (
    None
):
    path = WORKSPACE / RETAINED_CATASTROPHE_OUTPUT
    content = path.read_bytes()
    payload = json.loads(content)
    matches = _recursive_matches(payload, OBSERVED_LEGACY_FALSE_JOIN)

    assert hashlib.sha256(content).hexdigest() == (
        EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    )
    assert payload["document"]["sha256"] == (
        EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256
    )
    assert len(matches) == 2
    assert [row["word_count"] for row in matches] == [12, 12]
    assert [row["bbox"] for row in matches] == [
        OBSERVED_YEAR_BBOX,
        OBSERVED_YEAR_BBOX,
    ]


def test_catastrophe_line_and_region_aggregate_preserve_all_year_boundaries() -> (
    None
):
    line = _line(OBSERVED_YEAR_TOKENS)
    region = ImageRegion(
        page_index=1,
        object_index=1,
        bbox={"x": 100.0, "y": 437.0, "w": 444.0, "h": 149.0},
        pixel_width=2_250,
        pixel_height=775,
        area_ratio=0.14,
        lines=[line],
        content_type="chart",
        region_role="content_region",
        region_origin="pdf_page_render",
        coordinate_unit="pt",
    )

    _set_region_text(region)

    assert line.text == OBSERVED_YEAR_LINE
    assert region.text == OBSERVED_YEAR_LINE
    assert region.to_dict()["text"] == OBSERVED_YEAR_LINE
    assert OBSERVED_LEGACY_FALSE_JOIN not in region.text
    assert [token.text for token in line.tokens] == list(
        OBSERVED_YEAR_TOKENS
    )
    assert line.word_count == len(line.tokens) == 12


def test_duplicate_sparse_year_candidate_is_retained_without_refusion() -> None:
    standard = _line(OBSERVED_YEAR_TOKENS)
    sparse = deepcopy(standard)
    sparse.ocr_pass = "sparse"
    sparse.confidence = 0.94
    for token in sparse.tokens:
        token.ocr_pass = "sparse"

    merged, rejected = _merge_sparse_ocr_lines_with_diagnostics(
        [standard],
        [sparse],
        numeric_cleanup_v2_enabled=True,
    )

    assert len(merged) == len(rejected) == 1
    assert merged[0].text == OBSERVED_YEAR_LINE
    assert rejected[0]["text"] == OBSERVED_YEAR_LINE
    assert rejected[0]["ocr_pass"] == "sparse"
    assert rejected[0]["rejection_reason"] == (
        "overlapping_ocr_candidate"
    )
    assert OBSERVED_LEGACY_FALSE_JOIN not in json.dumps(
        [line.to_evidence_dict() for line in merged],
        sort_keys=True,
    )


def test_flag_off_internal_build_line_call_shape_is_legacy_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def strict_legacy(text: str) -> str:
        calls.append(text)
        return text

    monkeypatch.setattr(ocr_module, "_clean_ocr_line", strict_legacy)

    line = _build_lines(
        _tsv(("Alpha", "Beta")),
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
    )[0]

    assert calls == ["Alpha Beta"]
    assert line.text == "Alpha Beta"


def test_flag_on_internal_build_line_propagates_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def capture(
        text: str,
        *,
        numeric_cleanup_v2_enabled: bool = False,
    ) -> str:
        calls.append((text, numeric_cleanup_v2_enabled))
        return text

    monkeypatch.setattr(ocr_module, "_clean_ocr_line", capture)

    _build_lines(
        _tsv(("Alpha", "Beta")),
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
        numeric_cleanup_v2_enabled=True,
    )

    assert calls == [("Alpha Beta", True)]


def test_flag_off_sparse_merge_call_shape_is_legacy_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def strict_legacy(text: str) -> str:
        calls.append(text)
        return text

    monkeypatch.setattr(ocr_module, "_clean_ocr_line", strict_legacy)
    bbox = {"x": 10.0, "y": 10.0, "w": 50.0, "h": 10.0}
    first = OCRLine(
        text="Alpha Beta",
        bbox=dict(bbox),
        confidence=0.95,
        word_count=2,
    )
    second = OCRLine(
        text="Alpha Beta",
        bbox=dict(bbox),
        confidence=0.94,
        word_count=2,
        ocr_pass="sparse",
    )

    merged, rejected = _merge_sparse_ocr_lines_with_diagnostics(
        [first],
        [second],
    )

    assert len(merged) == len(rejected) == 1
    assert calls == ["Alpha Beta", "Alpha Beta"]


@pytest.mark.parametrize(
    "case",
    bound_cases(),
    ids=lambda case: case["case_id"],
)
def test_bounds_never_fall_back_to_legacy_join(
    case: dict[str, str],
) -> None:
    normalized = " ".join(case["input"].split())
    result = _clean_ocr_line(
        case["input"],
        numeric_cleanup_v2_enabled=True,
    )

    assert result == normalized
    assert len(result.encode("utf-8")) == len(normalized.encode("utf-8"))


def test_overlong_candidate_cannot_join_an_eligible_prefix() -> None:
    valid = "ABCDEF0123456789" * 4
    valid_fragments = [
        valid[index : index + 4]
        for index in range(0, len(valid), 4)
    ]
    suffix = ["AB"] * 49
    source = f"SHA-256: {' '.join((*valid_fragments, *suffix))}"

    result = _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    )

    assert result == source
    assert f"SHA-256: {valid}" not in result


def test_unicode_confusable_label_and_candidate_are_never_normalized() -> None:
    value = "ABCDEF0123456789" * 4
    fragments = " ".join(
        value[index : index + 4]
        for index in range(0, len(value), 4)
    )
    cases = (
        f"SHА-256: {fragments}",  # Cyrillic capital A in the label.
        f"SHA-256: АBCD {fragments[5:]}",  # Cyrillic A in the value.
        f"ＳＨＡ２５６: {fragments}",  # Full-width compatibility forms.
    )

    for source in cases:
        assert _clean_ocr_line(
            source,
            numeric_cleanup_v2_enabled=True,
        ) == source


def test_numeric_cleanup_does_not_change_bbox_confidence_or_pass() -> None:
    disabled = _line(OBSERVED_YEAR_TOKENS, enabled=False)
    enabled = _line(OBSERVED_YEAR_TOKENS, enabled=True)

    assert enabled.bbox == disabled.bbox
    assert enabled.confidence == disabled.confidence
    assert enabled.word_count == disabled.word_count
    assert enabled.ocr_pass == disabled.ocr_pass
    assert [
        (
            token.text,
            token.bbox,
            token.crop_pixel_bbox,
            token.confidence,
            token.ocr_pass,
            token.word_index,
        )
        for token in enabled.tokens
    ] == [
        (
            token.text,
            token.bbox,
            token.crop_pixel_bbox,
            token.confidence,
            token.ocr_pass,
            token.word_index,
        )
        for token in disabled.tokens
    ]
    assert enabled.text != disabled.text


def test_reentry_and_repeated_runs_are_byte_stable() -> None:
    cases = (
        OBSERVED_YEAR_LINE,
        "SHA256: "
        + " ".join(
            ("ABCDEF0123456789" * 4)[index : index + 4]
            for index in range(0, 64, 4)
        ),
        "Page 20 21 22 23 24 25 of 120",
    )

    first = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in cases
    ]
    second = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in cases
    ]
    reentered = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in first
    ]

    assert first == second == reentered
