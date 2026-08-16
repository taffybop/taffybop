"""Independent adversarial regressions for P02-US05 numeric-safe cleanup."""

from __future__ import annotations

import pytest

from app.services.ocr import _clean_ocr_line


def _split_digest() -> str:
    value = "ABCDEF0123456789" * 4
    return " ".join(
        value[index : index + 4] for index in range(0, len(value), 4)
    )


@pytest.mark.parametrize(
    "label",
    (
        "\N{LATIN SMALL LETTER LONG S}ha256:",
        "d\N{LATIN SMALL LETTER DOTLESS I}gest:",
        "f\N{LATIN SMALL LETTER DOTLESS I}ngerpr"
        "\N{LATIN SMALL LETTER DOTLESS I}nt:",
    ),
)
def test_unicode_labels_cannot_be_normalized_into_ascii_allowlist(
    label: str,
) -> None:
    """Only ASCII case folding may authorize a digest join."""

    split_digest = _split_digest()

    assert _clean_ocr_line(
        f"{label} {split_digest}",
        numeric_cleanup_v2_enabled=True,
    ) == f"{label} {split_digest}"


def test_ascii_lowercase_label_remains_case_insensitively_allowlisted() -> None:
    split_digest = _split_digest()

    assert _clean_ocr_line(
        f"sha256: {split_digest}",
        numeric_cleanup_v2_enabled=True,
    ) == f"sha256: {split_digest.replace(' ', '')}"


def test_late_candidate_bound_failure_rolls_back_an_earlier_valid_join() -> None:
    """A bound failure must return the whole normalized line unmodified."""

    split_digest = _split_digest()
    overlong_candidate = " ".join("AB" for _ in range(65))
    source = (
        f"SHA256: {split_digest} ordinary HASH: {overlong_candidate}"
    )

    assert _clean_ocr_line(
        source,
        numeric_cleanup_v2_enabled=True,
    ) == source
