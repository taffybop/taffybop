from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import ocr as ocr_module
from app.services.ocr import (
    OCRLine,
    _build_lines,
    _clean_ocr_line,
    _merge_sparse_ocr_lines_with_diagnostics,
    _ocr_png_lines,
)
from tests.benchmarks.numeric_cleanup_metrics import (
    OBSERVED_LEGACY_FALSE_JOIN,
    OBSERVED_YEAR_LINE,
    OBSERVED_YEAR_TOKENS,
    SEQUENTIAL_LEGACY_FALSE_JOIN,
    SEQUENTIAL_YEAR_LINE,
    SEQUENTIAL_YEAR_TOKENS,
    bound_cases,
    digest_cases,
    numeric_control_cases,
)


def _tsv(words: tuple[str, ...], *, confidence: int = 95) -> str:
    header = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
        "left\ttop\twidth\theight\tconf\ttext"
    )
    rows = [header]
    left = 10
    for word_number, word in enumerate(words, 1):
        width = max(len(word) * 6, 6)
        rows.append(
            "5\t1\t1\t1\t1\t"
            f"{word_number}\t{left}\t20\t{width}\t12\t"
            f"{confidence}\t{word}"
        )
        left += width + 4
    return "\n".join(rows)


def _build(
    words: tuple[str, ...],
    *,
    enabled: bool,
) -> OCRLine:
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


def test_retained_catastrophe_years_remain_twelve_tokens() -> None:
    cleaned = _clean_ocr_line(
        OBSERVED_YEAR_LINE,
        numeric_cleanup_v2_enabled=True,
    )

    assert cleaned.split() == list(OBSERVED_YEAR_TOKENS)
    assert len(cleaned.split()) == 12
    assert OBSERVED_LEGACY_FALSE_JOIN not in cleaned


def test_flag_off_restores_the_exact_observed_48_digit_join() -> None:
    assert _clean_ocr_line(OBSERVED_YEAR_LINE) == (
        OBSERVED_LEGACY_FALSE_JOIN
    )
    assert len(OBSERVED_LEGACY_FALSE_JOIN) == 48


def test_sequential_2010_through_2021_remains_a_synthetic_negative() -> None:
    enabled = _clean_ocr_line(
        SEQUENTIAL_YEAR_LINE,
        numeric_cleanup_v2_enabled=True,
    )

    assert enabled.split() == list(SEQUENTIAL_YEAR_TOKENS)
    assert len(enabled.split()) == 12
    assert _clean_ocr_line(SEQUENTIAL_YEAR_LINE) == (
        SEQUENTIAL_LEGACY_FALSE_JOIN
    )


@pytest.mark.parametrize(
    "case",
    digest_cases(),
    ids=lambda case: str(case["case_id"]),
)
def test_every_allowlisted_digest_label_and_length_joins(
    case: dict[str, object],
) -> None:
    enabled = _clean_ocr_line(
        str(case["input"]),
        numeric_cleanup_v2_enabled=True,
    )

    assert enabled == case["expected"]
    assert _clean_ocr_line(str(case["input"])) == case["expected"]
    assert len(str(case["value"])) == case["length"]


@pytest.mark.parametrize(
    ("label", "length"),
    (
        ("md5", 32),
        ("sHa1", 40),
        ("Sha-224", 56),
        ("sha256", 64),
        ("ShA-384", 96),
        ("sha512", 128),
        ("hash", 32),
        ("CheckSum", 40),
        ("dIgEsT", 56),
        ("fingerPRINT", 64),
    ),
)
def test_identifier_labels_are_ascii_case_insensitive(
    label: str,
    length: int,
) -> None:
    value = ("ABCDEF0123456789" * 8)[:length]
    source = f"{label}: {' '.join(value[i:i + 4] for i in range(0, length, 4))}"

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == f"{label}: {value}"


@pytest.mark.parametrize(
    "case",
    numeric_control_cases(),
    ids=lambda case: case["case_id"],
)
def test_numeric_and_ambiguous_non_targets_are_not_joined(
    case: dict[str, str],
) -> None:
    expected = " ".join(case["input"].split())

    assert _clean_ocr_line(
        case["input"],
        numeric_cleanup_v2_enabled=True,
    ) == expected


def test_decimal_only_digest_length_is_ineligible_even_with_context() -> None:
    source = (
        "SHA-256: "
        "0000 1111 2222 3333 4444 5555 6666 7777 "
        "8888 9999 0000 1111 2222 3333 4444 5555"
    )

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == source


@pytest.mark.parametrize("punctuation", (";", "::", ":=", ","))
def test_only_one_trailing_colon_or_equals_is_removed_from_label(
    punctuation: str,
) -> None:
    value = "ABCDEF0123456789" * 4
    fragments = " ".join(
        value[index : index + 4] for index in range(0, len(value), 4)
    )
    source = f"SHA256{punctuation} {fragments}"

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == source


def test_complete_maximal_run_must_match_declared_length() -> None:
    value = "ABCDEF0123456789" * 4
    fragments = [
        value[index : index + 4]
        for index in range(0, len(value), 4)
    ]
    source = f"SHA-256: {' '.join((*fragments, 'AB'))}"

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == source
    assert value not in _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    )


def test_signature_cleanup_rules_are_identical_on_both_paths() -> None:
    samples = (
        "| Signed by Alice",
        "¦ Signer: Alice",
        "! Signing complete",
        "Signed: l approve",
    )

    for source in samples:
        assert _clean_ocr_line(
            source,
            numeric_cleanup_v2_enabled=True,
        ) == _clean_ocr_line(source)


def test_tsv_integration_preserves_year_text_and_token_evidence() -> None:
    line = _build(OBSERVED_YEAR_TOKENS, enabled=True)
    evidence = line.to_evidence_dict()

    assert line.text == OBSERVED_YEAR_LINE
    assert line.word_count == 12
    assert [token.text for token in line.tokens] == list(
        OBSERVED_YEAR_TOKENS
    )
    assert [token.word_index for token in line.tokens] == list(range(12))
    assert all(token.ocr_pass == "standard" for token in line.tokens)
    assert [token["text"] for token in evidence["tokens"]] == list(
        OBSERVED_YEAR_TOKENS
    )
    assert all(token["bbox"]["w"] > 0 for token in evidence["tokens"])
    assert all(
        token["crop_pixel_bbox"]["w"] > 0
        for token in evidence["tokens"]
    )


def test_flag_off_tsv_integration_preserves_token_evidence_but_fuses_text() -> None:
    line = _build(OBSERVED_YEAR_TOKENS, enabled=False)

    assert line.text == OBSERVED_LEGACY_FALSE_JOIN
    assert line.word_count == 12
    assert [token.text for token in line.tokens] == list(
        OBSERVED_YEAR_TOKENS
    )


def test_digest_cleanup_changes_only_line_text_not_fragment_evidence() -> None:
    value = "ABCDEF0123456789" * 4
    fragments = tuple(
        value[index : index + 4]
        for index in range(0, len(value), 4)
    )
    words = ("SHA-256:", *fragments)
    line = _build(words, enabled=True)

    assert line.text == f"SHA-256: {value}"
    assert line.word_count == len(words)
    assert [token.text for token in line.tokens] == list(words)
    assert len({token.word_index for token in line.tokens}) == len(words)


def test_standard_and_sparse_passes_receive_numeric_safe_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    standard = _tsv(OBSERVED_YEAR_TOKENS, confidence=96)
    sparse = _tsv(OBSERVED_YEAR_TOKENS, confidence=95)

    def run(
        _executable: str,
        _png_bytes: bytes,
        _languages: tuple[str, ...],
        _timeout_seconds: float,
        _tessdata_path: str | None,
        *,
        page_segmentation_mode: int = 3,
    ) -> str:
        calls.append(page_segmentation_mode)
        return sparse if page_segmentation_mode == 11 else standard

    monkeypatch.setattr(ocr_module, "_run_tesseract_tsv", run)

    lines, rejected, warnings = _ocr_png_lines(
        "/tesseract",
        b"png",
        ("eng",),
        30.0,
        None,
        crop_bounds=(0.0, 0.0, 612.0, 792.0),
        scale=1.0,
        page_width=612.0,
        page_height=792.0,
        numeric_cleanup_v2_enabled=True,
    )

    assert calls == [3, 11]
    assert [line.text for line in lines] == [OBSERVED_YEAR_LINE]
    assert [token.text for token in lines[0].tokens] == list(
        OBSERVED_YEAR_TOKENS
    )
    assert len(rejected) == 1
    assert rejected[0]["text"] == OBSERVED_YEAR_LINE
    assert warnings == []


def test_sparse_reconciliation_recleans_both_candidates_with_v2() -> None:
    bbox = {"x": 10.0, "y": 20.0, "w": 100.0, "h": 10.0}
    primary = OCRLine(
        text=OBSERVED_YEAR_LINE,
        bbox=dict(bbox),
        confidence=0.96,
        word_count=12,
    )
    sparse = OCRLine(
        text=OBSERVED_YEAR_LINE,
        bbox=dict(bbox),
        confidence=0.95,
        word_count=12,
        ocr_pass="sparse",
    )

    merged, rejected = _merge_sparse_ocr_lines_with_diagnostics(
        [deepcopy(primary)],
        [deepcopy(sparse)],
        numeric_cleanup_v2_enabled=True,
    )

    assert [line.text for line in merged] == [OBSERVED_YEAR_LINE]
    assert len(rejected) == 1
    assert rejected[0]["text"] == OBSERVED_YEAR_LINE


@pytest.mark.parametrize(
    "case",
    bound_cases(),
    ids=lambda case: case["case_id"],
)
def test_bound_excess_fails_closed_without_partial_join(
    case: dict[str, str],
) -> None:
    expected = " ".join(case["input"].split())

    assert _clean_ocr_line(
        case["input"],
        numeric_cleanup_v2_enabled=True,
    ) == expected


def test_exact_fragment_and_candidate_bounds_remain_eligible() -> None:
    fragments = tuple("AB" for _ in range(64))
    source = f"HASH: {' '.join(fragments)}"

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == f"HASH: {''.join(fragments)}"


def test_exact_line_and_token_bounds_are_inclusive() -> None:
    fragments = tuple("AB" for _ in range(64))
    hash_tail = f" SHA512: {' '.join(fragments)}"
    exact_line = ("x" * (65_536 - len(hash_tail))) + hash_tail
    filler_count = 4_096 - 1 - 16
    digest = "ABCDEF0123456789" * 4
    exact_tokens = (
        ("x " * filler_count)
        + "SHA256: "
        + " ".join(
            digest[index : index + 4]
            for index in range(0, len(digest), 4)
        )
    )

    line_output = _clean_ocr_line(
        exact_line,
        numeric_cleanup_v2_enabled=True,
    )
    token_output = _clean_ocr_line(
        exact_tokens,
        numeric_cleanup_v2_enabled=True,
    )

    assert len(exact_line) == 65_536
    assert line_output.endswith(f"SHA512: {''.join(fragments)}")
    assert len(exact_tokens.split()) == 4_096
    assert token_output.endswith(f"SHA256: {digest}")


def test_numeric_safe_cleanup_is_deterministic_and_idempotent() -> None:
    values = (
        OBSERVED_YEAR_LINE,
        SEQUENTIAL_YEAR_LINE,
        *(str(case["input"]) for case in digest_cases()),
        *(case["input"] for case in numeric_control_cases()),
    )

    first = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in values
    ]
    second = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in values
    ]
    reentered = [
        _clean_ocr_line(value, numeric_cleanup_v2_enabled=True)
        for value in first
    ]

    assert first == second == reentered
