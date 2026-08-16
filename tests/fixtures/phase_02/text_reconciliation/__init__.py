"""Deterministic candidate controls for P02-US04 text reconciliation."""

from .builder import (
    SOURCE_SHA256,
    candidate,
    dependent_bad_layer_case,
    deterministic_font_case,
    group,
    healthy_native_case,
    independent_ocr_case,
    low_margin_case,
    mixed_script_case,
    partial_overlap_case,
    reconciliation_cases,
)

__all__ = [
    "SOURCE_SHA256",
    "candidate",
    "dependent_bad_layer_case",
    "deterministic_font_case",
    "group",
    "healthy_native_case",
    "independent_ocr_case",
    "low_margin_case",
    "mixed_script_case",
    "partial_overlap_case",
    "reconciliation_cases",
]
