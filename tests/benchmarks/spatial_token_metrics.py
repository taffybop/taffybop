"""Deterministic P02-US06 spatial OCR token preservation metrics.

The runner exercises the bounded production occurrence projection and item
projection without invoking Tesseract, PDFium, Docling, the document parser,
or a hosted model.  The real target is bound to the immutable catastrophe
baseline and source PDF.  Synthetic controls cover overlapping OCR passes,
distant equal text, grounded short alternatives, negative corroboration, and
every public resource bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import resource
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar


RETAINED_CATASTROPHE_OUTPUT = (
    "tracker/benchmarks/llamaparse-15/runs/"
    "baseline-20260728-current/catastrophe-recap/our-output.json"
)
RETAINED_CATASTROPHE_SOURCE = (
    "benchmark-expertmodeldata/catastrophe-recap.pdf"
)
RETAINED_P02_US05_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US05-numeric-cleanup-metrics.json"
)
SPATIAL_TOKEN_POLICY = (
    "tracker/phase-02-text-integrity/decisions/"
    "P02-spatial-token-preservation-policy.md"
)
DEFAULT_OUTPUT = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US06-spatial-token-metrics.json"
)

EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256 = (
    "3f1f0d9b7768e119d65a887e73f54173df633eeca004e9296bcfeb6aebc91abe"
)
EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256 = (
    "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
)
EXPECTED_RETAINED_P02_US05_METRICS_SHA256 = (
    "5b347a6f98c47d9df3b52cfef40bb5c6bb5824f149cc8da6806cc23d5e3a174c"
)
EXPECTED_SPATIAL_TOKEN_POLICY_SHA256 = (
    "1d0544f55df543ea010a22ef0379e90abb13256df4c2388032cd975715e10741"
)

P00_US10_HEALTHY_P95_MS = 46_760.0
HEALTHY_OVERHEAD_TARGET_PERCENT = 10.0

EXPECTED_CHART_BBOX = {
    "x": 100.221,
    "y": 437.31,
    "w": 444.032,
    "h": 149.057,
    "width": 444.032,
    "height": 149.057,
    "unit": "pt",
}
EXPECTED_YEAR_ROWS: tuple[
    tuple[str, float, float, float, float, float], ...
] = (
    ("2015", 125.021, 562.51, 13.4, 4.6, 0.9633),
    ("2020", 165.421, 562.51, 14.6, 4.4, 0.9666),
    ("2025", 206.621, 562.51, 14.4, 4.6, 0.9650),
    ("2015", 232.021, 562.51, 13.4, 4.6, 0.9620),
    ("2020", 272.421, 562.51, 14.6, 4.4, 0.9685),
    ("2025", 313.621, 562.51, 14.6, 4.6, 0.9654),
    ("2015", 339.021, 562.51, 13.4, 4.6, 0.9618),
    ("2020", 379.621, 562.51, 14.6, 4.4, 0.9689),
    ("2025", 420.621, 562.51, 14.6, 4.6, 0.9657),
    ("2015", 446.221, 562.51, 13.4, 4.6, 0.9633),
    ("2020", 486.621, 562.51, 14.6, 4.4, 0.9666),
    ("2025", 527.621, 562.51, 14.6, 4.6, 0.9688),
)
EXPECTED_IH_ROW = {
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

PRODUCTION_AND_CUSTODY_INPUTS = (
    "app/services/spatial_tokens.py",
    "app/services/ocr.py",
    "app/services/selective_span_ocr.py",
    "app/services/pipeline.py",
    "app/config.py",
    ".env.example",
    "README.md",
    SPATIAL_TOKEN_POLICY,
    RETAINED_CATASTROPHE_OUTPUT,
    RETAINED_CATASTROPHE_SOURCE,
    RETAINED_P02_US05_METRICS,
    "tests/benchmarks/spatial_token_metrics.py",
)

_PayloadT = TypeVar("_PayloadT", bound=Mapping[str, Any])


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_identity(workspace: Path, relative_path: str) -> dict[str, Any]:
    content = (workspace / relative_path).read_bytes()
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _input_paths(workspace: Path) -> tuple[str, ...]:
    """Return fixed inputs plus every P02-US06 test present at collection time."""

    fixed = list(PRODUCTION_AND_CUSTODY_INPUTS)
    discovered: set[str] = set()
    tests_root = workspace / "tests"
    for pattern in (
        "**/test_p02_us06*.py",
        "**/test_*spatial_token*.py",
    ):
        for path in tests_root.glob(pattern):
            relative_path = path.relative_to(workspace).as_posix()
            # The retained-artifact contract necessarily authenticates the
            # artifact after collection; including it here would create a
            # self-referential artifact/test hash cycle.
            if (
                path.is_file()
                and "retained_metrics_artifact" not in relative_path
            ):
                discovered.add(relative_path)
    return tuple(dict.fromkeys((*fixed, *sorted(discovered))))


def _input_identities(workspace: Path) -> dict[str, dict[str, Any]]:
    return {
        relative_path: _file_identity(workspace, relative_path)
        for relative_path in _input_paths(workspace)
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _json_pointer(value: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with '/'")
    current = value
    for encoded_part in pointer[1:].split("/"):
        part = encoded_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise TypeError(f"cannot traverse {pointer!r}")
    return current


def _matching_text_pointers(value: Any, expected: str) -> list[str]:
    pointers: list[str] = []

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            if node.get("text") == expected:
                escaped = tuple(
                    part.replace("~", "~0").replace("/", "~1")
                    for part in path
                )
                pointers.append("/" + "/".join(escaped))
            for key, child in node.items():
                walk(child, (*path, str(key)))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, (*path, str(index)))

    walk(value, ())
    return sorted(pointers)


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one observation is required")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("observations must be finite and non-negative")
    ordered = sorted(values)
    return ordered[max(math.ceil(percentile * len(ordered)), 1) - 1]


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "p50": _nearest_rank(values, 0.50),
        "p95": _nearest_rank(values, 0.95),
        "max": max(values),
    }


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _measure_deterministic(
    operation: Callable[[], _PayloadT],
    *,
    warmups: int,
    samples: int,
) -> tuple[_PayloadT, list[float], int]:
    if warmups < 0 or samples < 1:
        raise ValueError("warmups must be non-negative and samples positive")
    for _ in range(warmups):
        operation()
    expected: _PayloadT | None = None
    durations: list[float] = []
    peak_before = _peak_rss_bytes()
    for _ in range(samples):
        started = perf_counter()
        payload = operation()
        durations.append(max((perf_counter() - started) * 1000.0, 0.0))
        if expected is None:
            expected = payload
        elif _canonical_json(payload) != _canonical_json(expected):
            raise RuntimeError("measured samples produced structural drift")
    assert expected is not None
    return expected, durations, max(_peak_rss_bytes() - peak_before, 0)


def _bbox(
    x: float,
    y: float,
    width: float,
    height: float,
) -> dict[str, float]:
    return {"x": x, "y": y, "w": width, "h": height}


def _expected_year_record(
    row: tuple[str, float, float, float, float, float],
) -> dict[str, Any]:
    text, x, y, width, height, confidence = row
    return {
        "accepted": True,
        "bbox": {
            "x": x,
            "y": y,
            "w": width,
            "h": height,
            "width": width,
            "height": height,
            "unit": "pt",
        },
        "confidence": confidence,
        "rejection_reason": None,
        "source": "ocr",
        "text": text,
        "value": text,
        "word_count": 1,
    }


def retained_catastrophe_binding(workspace: Path) -> dict[str, Any]:
    output_identity = _file_identity(workspace, RETAINED_CATASTROPHE_OUTPUT)
    source_identity = _file_identity(workspace, RETAINED_CATASTROPHE_SOURCE)
    if (
        output_identity["sha256"]
        != EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256
    ):
        raise RuntimeError("retained catastrophe parser output identity drifted")
    if (
        source_identity["sha256"]
        != EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256
    ):
        raise RuntimeError("retained catastrophe source identity drifted")

    payload = _load_json(workspace / RETAINED_CATASTROPHE_OUTPUT)
    if (
        str(payload["document"]["sha256"])
        != EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256
    ):
        raise RuntimeError("retained output no longer binds the source PDF")
    if (
        _json_pointer(payload, "/pages/0/detected_images/1/bbox")
        != EXPECTED_CHART_BBOX
    ):
        raise RuntimeError("retained catastrophe chart owner bbox drifted")

    detected_paths = tuple(
        f"/pages/0/detected_images/1/items/{index}"
        for index in range(8, 20)
    )
    shared_paths = tuple(
        f"/pages/0/items/4/items/{index}" for index in range(8, 20)
    )
    expected_records = tuple(
        _expected_year_record(row) for row in EXPECTED_YEAR_ROWS
    )
    detected_records = tuple(
        _json_pointer(payload, pointer) for pointer in detected_paths
    )
    shared_records = tuple(
        _json_pointer(payload, pointer) for pointer in shared_paths
    )
    if (
        detected_records != expected_records
        or shared_records != expected_records
    ):
        raise RuntimeError("retained catastrophe year evidence drifted")

    expected_year_pointers = sorted((*detected_paths, *shared_paths))
    actual_year_pointers = sorted(
        pointer
        for text in ("2015", "2020", "2025")
        for pointer in _matching_text_pointers(payload, text)
    )
    if actual_year_pointers != expected_year_pointers:
        raise RuntimeError("retained catastrophe year pointer set drifted")

    ih_paths = (
        "/pages/0/detected_images/1/items/20",
        "/pages/0/items/4/items/20",
    )
    ih_records = tuple(
        _json_pointer(payload, pointer) for pointer in ih_paths
    )
    if (
        ih_records != (EXPECTED_IH_ROW, EXPECTED_IH_ROW)
        or _matching_text_pointers(payload, "iH") != sorted(ih_paths)
    ):
        raise RuntimeError("retained catastrophe iH evidence drifted")

    year_evidence = [
        {
            "path": pointer,
            "text": record["text"],
            "bbox": record["bbox"],
            "confidence": record["confidence"],
            "word_count": record["word_count"],
        }
        for pointer, record in zip(
            detected_paths,
            detected_records,
            strict=True,
        )
    ]
    return {
        "artifact": output_identity,
        "source": source_identity,
        "document_sha256": str(payload["document"]["sha256"]),
        "chart_owner_bbox": dict(EXPECTED_CHART_BBOX),
        "year_source_projection": "detected_images",
        "year_mirror_projection": "shared_ir_item",
        "year_occurrence_count": len(year_evidence),
        "year_evidence": year_evidence,
        "year_mirror_paths": list(shared_paths),
        "ih_evidence": {
            "source_path": ih_paths[0],
            "mirror_path": ih_paths[1],
            "record": dict(EXPECTED_IH_ROW),
        },
    }


def _retained_us05_ceiling(workspace: Path) -> dict[str, Any]:
    identity = _file_identity(workspace, RETAINED_P02_US05_METRICS)
    if identity["sha256"] != EXPECTED_RETAINED_P02_US05_METRICS_SHA256:
        raise RuntimeError("retained P02-US05 metrics identity drifted")
    payload = _load_json(workspace / RETAINED_P02_US05_METRICS)
    ceiling = payload["metrics"]["combined_healthy_p95_ceiling_reference"]
    if not isinstance(ceiling, dict):
        raise TypeError("retained P02-US05 ceiling must be an object")
    if not bool(ceiling["passes_target"]):
        raise RuntimeError("retained P02-US05 ceiling did not pass")
    return {
        "artifact": identity,
        "arithmetic_ceiling_percent": float(
            ceiling["arithmetic_ceiling_percent"]
        ),
        "observed_paired_full_parser_percentile": bool(
            ceiling["observed_paired_full_parser_percentile"]
        ),
    }


def _line_from_record(record: Mapping[str, Any], *, ocr_pass: str = "standard"):
    from app.services.ocr import OCRLine

    return OCRLine(
        text=str(record["text"]),
        bbox=dict(record["bbox"]),
        confidence=float(record["confidence"]),
        word_count=int(record["word_count"]),
        ocr_pass=ocr_pass,
    )


def _target_region(binding: Mapping[str, Any]):
    from app.services.ocr import ImageRegion

    years = [
        _line_from_record(evidence)
        for evidence in binding["year_evidence"]
    ]
    ih = _line_from_record(binding["ih_evidence"]["record"])
    return ImageRegion(
        page_index=1,
        object_index=1,
        bbox=dict(binding["chart_owner_bbox"]),
        pixel_width=2250,
        pixel_height=775,
        area_ratio=0.136549,
        text="\n".join((*[line.text for line in years], ih.text)),
        lines=[*years, ih],
        confidence=0.8357,
        content_type="chart",
        region_role="content_region",
        region_origin="retained_baseline",
        coordinate_unit="pt",
    )


def _canonical_surfaces(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "value",
            "md",
            "ocr_text",
            "cleaned_ocr_text",
        )
    }


def _target_payload(binding: Mapping[str, Any]) -> dict[str, Any]:
    from app.config import Settings
    from app.services.pipeline import _image_item

    region = _target_region(binding)
    enabled = _image_item(
        region,
        Settings(
            ocr_numeric_cleanup_v2_enabled=True,
            ocr_spatial_token_preservation_enabled=True,
        ),
        str(binding["document_sha256"]),
    )
    disabled = _image_item(
        region,
        Settings(ocr_numeric_cleanup_v2_enabled=True),
        str(binding["document_sha256"]),
    )
    enabled_bytes = len(_canonical_json(enabled))
    disabled_bytes = len(_canonical_json(disabled))
    occurrences = list(enabled["ocr_token_occurrences"])
    years = [
        occurrence
        for occurrence in occurrences
        if occurrence["text"] in {"2015", "2020", "2025"}
    ]
    ih = [
        occurrence
        for occurrence in occurrences
        if occurrence["text"] == "iH"
    ]
    surfaces = _canonical_surfaces(enabled)
    forbidden = {"iH", "1H"}
    return {
        "occurrences": occurrences,
        "year_occurrences": years,
        "ih_occurrences": ih,
        "summary": enabled["ocr_occurrence_summary"],
        "canonical_surfaces": surfaces,
        "canonical_flag_off_surfaces": _canonical_surfaces(disabled),
        "canonical_surface_parity": (
            surfaces == _canonical_surfaces(disabled)
        ),
        "unsupported_short_primary_surface_count": sum(
            token in forbidden
            for surface in surfaces.values()
            for token in str(surface or "").split()
        ),
        "flag_off_additive_keys_absent": (
            "ocr_token_occurrences" not in disabled
            and "ocr_occurrence_summary" not in disabled
        ),
        "enabled_item_size_bytes": enabled_bytes,
        "disabled_item_size_bytes": disabled_bytes,
        "additive_item_size_delta_bytes": enabled_bytes - disabled_bytes,
    }


def _token(
    text: str,
    bbox: Mapping[str, Any],
    confidence: float,
    *,
    ocr_pass: str = "standard",
    word_index: int = 0,
):
    from app.services.ocr import OCRToken

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
    bbox: Mapping[str, Any],
    confidence: float,
    *,
    ocr_pass: str = "standard",
    tokens: Sequence[Any] | None = None,
):
    from app.services.ocr import OCRLine

    return OCRLine(
        text=text,
        bbox=dict(bbox),
        confidence=confidence,
        word_count=len(tokens) if tokens is not None else 1,
        ocr_pass=ocr_pass,
        tokens=list(tokens or ()),
    )


def _diagnostic(
    *,
    accepted: bool,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "rejection_reason": rejection_reason,
    }


def _project(
    *,
    lines: Sequence[Any],
    diagnostics: Sequence[Mapping[str, Any]],
    rejected_lines: Sequence[Mapping[str, Any]] = (),
    owner_content_type: str = "chart",
    owner_bbox: Mapping[str, Any] | None = None,
    include_ocr_in_primary: bool = True,
    owner_case: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.services.spatial_tokens import project_ocr_token_occurrences

    return project_ocr_token_occurrences(
        page_index=1,
        owner_identity={
            "kind": "p02_us06_metric_control",
            "case_id": owner_case,
            "source_document_identity": "synthetic",
        },
        owner_bbox=owner_bbox or _bbox(0, 0, 600, 800),
        owner_content_type=owner_content_type,
        coordinate_unit="pt",
        lines=lines,
        line_diagnostics=diagnostics,
        rejected_lines=rejected_lines,
        include_ocr_in_primary=include_ocr_in_primary,
        primary_confidence_threshold=0.45,
    )


def _rejected_evidence(line: Any) -> dict[str, Any]:
    return {
        **line.to_evidence_dict(),
        "accepted": False,
        "rejection_reason": "overlapping_ocr_candidate",
    }


def _synthetic_payload() -> dict[str, Any]:
    from app.config import Settings
    from app.services.ocr import ImageRegion
    from app.services.pipeline import _image_item
    from app.services.spatial_tokens import geometry_aware_unique_line_values

    accepted = _line(
        "2025",
        _bbox(10, 10, 20, 10),
        0.94,
        tokens=[
            _token("2025", _bbox(10, 10, 20, 10), 0.94)
        ],
    )
    rejected = _line(
        "2025",
        _bbox(10.5, 10.2, 20, 10),
        0.99,
        ocr_pass="sparse",
        tokens=[
            _token(
                "2025",
                _bbox(10.5, 10.2, 20, 10),
                0.99,
                ocr_pass="sparse",
            )
        ],
    )
    overlap_occurrences, overlap_summary = _project(
        lines=[accepted],
        diagnostics=[_diagnostic(accepted=True)],
        rejected_lines=[_rejected_evidence(rejected)],
        owner_case="overlapping_psm",
    )

    header = _line(
        "Quarterly update",
        _bbox(20, 10, 120, 12),
        0.98,
        tokens=[
            _token("Quarterly", _bbox(20, 10, 60, 12), 0.98),
            _token(
                "update",
                _bbox(84, 10, 50, 12),
                0.98,
                word_index=1,
            ),
        ],
    )
    footer = _line(
        "Quarterly update",
        _bbox(20, 750, 120, 12),
        0.98,
        tokens=[
            _token("Quarterly", _bbox(20, 750, 60, 12), 0.98),
            _token(
                "update",
                _bbox(84, 750, 50, 12),
                0.98,
                word_index=1,
            ),
        ],
    )
    distant_occurrences, distant_summary = _project(
        lines=[header, footer],
        diagnostics=[
            _diagnostic(accepted=True),
            _diagnostic(accepted=True),
        ],
        owner_case="distant_repeated_text",
    )
    distant_line_values = geometry_aware_unique_line_values(
        ((header.text, header.bbox), (footer.text, footer.bbox))
    )

    short_lines = [
        _line(
            "iH",
            _bbox(20, 20, 12, 8),
            0.4437,
            tokens=[
                _token("iH", _bbox(20, 20, 12, 8), 0.4437)
            ],
        ),
        _line(
            "1H",
            _bbox(50, 20, 12, 8),
            0.41,
            tokens=[
                _token("1H", _bbox(50, 20, 12, 8), 0.41)
            ],
        ),
    ]
    short_diagnostics = [
        _diagnostic(accepted=False, rejection_reason="low_confidence"),
        _diagnostic(accepted=False, rejection_reason="low_confidence"),
    ]
    short_occurrences, short_summary = _project(
        lines=short_lines,
        diagnostics=short_diagnostics,
        owner_case="grounded_short_alternatives",
    )
    short_region = ImageRegion(
        page_index=1,
        object_index=7,
        bbox=_bbox(0, 0, 100, 100),
        pixel_width=100,
        pixel_height=100,
        area_ratio=0.1,
        text="iH\n1H",
        lines=short_lines,
        confidence=0.42,
        content_type="chart",
        region_role="content_region",
        coordinate_unit="pt",
    )
    short_item = _image_item(
        short_region,
        Settings(
            ocr_numeric_cleanup_v2_enabled=True,
            ocr_spatial_token_preservation_enabled=True,
        ),
        "synthetic-short-document",
    )

    negative_cases: list[dict[str, Any]] = []
    for case_id, text, confidence, content_type, bbox in (
        (
            "photo_role",
            "iH",
            0.4437,
            "image",
            _bbox(20, 20, 12, 8),
        ),
        (
            "below_confidence_floor",
            "1H",
            0.20,
            "chart",
            _bbox(20, 20, 12, 8),
        ),
        (
            "unsupported_punctuation",
            "I?",
            0.4437,
            "diagram",
            _bbox(20, 20, 12, 8),
        ),
        (
            "invalid_geometry",
            "iH",
            0.4437,
            "chart",
            _bbox(20, 20, 0, 8),
        ),
    ):
        line = _line(
            text,
            bbox,
            confidence,
            tokens=[_token(text, bbox, confidence)],
        )
        occurrences, summary = _project(
            lines=[line],
            diagnostics=[
                _diagnostic(
                    accepted=False,
                    rejection_reason="low_confidence",
                )
            ],
            owner_content_type=content_type,
            owner_case=case_id,
        )
        negative_cases.append(
            {
                "case_id": case_id,
                "occurrence_count": len(occurrences),
                "short_alternative_count": sum(
                    bool(item["short_alternative"])
                    for item in occurrences
                ),
                "invalid_occurrence_count": summary[
                    "invalid_occurrences"
                ],
                "occurrence_sha256": _sha256_json(occurrences),
            }
        )

    return {
        "overlap": {
            "occurrences": overlap_occurrences,
            "summary": overlap_summary,
        },
        "distant_repetition": {
            "occurrences": distant_occurrences,
            "summary": distant_summary,
            "geometry_aware_line_values": distant_line_values,
        },
        "grounded_short_alternatives": {
            "occurrences": short_occurrences,
            "summary": short_summary,
            "canonical_surfaces": _canonical_surfaces(short_item),
        },
        "negative_cases": negative_cases,
    }


def _base36(value: int) -> str:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if value == 0:
        return "0"
    output = ""
    while value:
        value, remainder = divmod(value, len(alphabet))
        output = alphabet[remainder] + output
    return output


def _bound_payload() -> dict[str, Any]:
    from app.services.spatial_tokens import (
        MAX_SPATIAL_OCCURRENCE_JSON_BYTES,
        MAX_SPATIAL_SHORT_ALTERNATIVES,
        MAX_SPATIAL_SOURCE_TOKENS,
        MAX_SPATIAL_TOKEN_OCCURRENCES,
        MAX_SPATIAL_TOKEN_TEXT_CHARS,
    )

    valid = _line(
        "OK",
        _bbox(10, 10, 5, 5),
        0.9,
        tokens=[_token("OK", _bbox(10, 10, 5, 5), 0.9)],
    )
    invalid = _line(
        "bad",
        _bbox(20, 10, 0, 5),
        0.9,
        tokens=[_token("bad", _bbox(20, 10, 0, 5), 0.9)],
    )
    oversized_text = "X" * (MAX_SPATIAL_TOKEN_TEXT_CHARS + 1)
    oversized = _line(
        oversized_text,
        _bbox(30, 10, 5, 5),
        0.9,
        tokens=[
            _token(oversized_text, _bbox(30, 10, 5, 5), 0.9)
        ],
    )
    invalid_occurrences, invalid_summary = _project(
        lines=[valid, invalid, oversized],
        diagnostics=[
            _diagnostic(accepted=True),
            _diagnostic(accepted=True),
            _diagnostic(accepted=True),
        ],
        owner_case="invalid_and_oversized",
    )

    short_lines = []
    short_diagnostics = []
    for index in range(MAX_SPATIAL_SHORT_ALTERNATIVES + 1):
        text = _base36(index)
        x = float((index % 32) * 2)
        y = float((index // 32) * 2)
        bbox = _bbox(x, y, 1, 1)
        short_lines.append(
            _line(
                text,
                bbox,
                0.4,
                tokens=[_token(text, bbox, 0.4)],
            )
        )
        short_diagnostics.append(
            _diagnostic(
                accepted=False,
                rejection_reason="low_confidence",
            )
        )
    short_occurrences, short_summary = _project(
        lines=short_lines,
        diagnostics=short_diagnostics,
        owner_bbox=_bbox(0, 0, 100, 100),
        owner_case="short_alternative_limit",
    )

    serialized_tokens = []
    for index in range(MAX_SPATIAL_TOKEN_OCCURRENCES):
        text = ("S" * 250) + f"{index:06d}"
        serialized_tokens.append(
            _token(
                text,
                _bbox(
                    float(index % 64),
                    float(index // 64),
                    0.5,
                    0.5,
                ),
                0.9,
                word_index=index,
            )
        )
    serialized_line = _line(
        "bounded serialized payload",
        _bbox(0, 0, 100, 100),
        0.9,
        tokens=serialized_tokens,
    )
    serialized_occurrences, serialized_summary = _project(
        lines=[serialized_line],
        diagnostics=[_diagnostic(accepted=True)],
        owner_bbox=_bbox(0, 0, 100, 100),
        owner_case="serialized_byte_limit",
    )

    source_tokens = [
        _token(
            oversized_text,
            _bbox(1, 1, 1, 1),
            0.9,
            word_index=index,
        )
        for index in range(MAX_SPATIAL_SOURCE_TOKENS + 1)
    ]
    source_line = _line(
        "bounded source traversal",
        _bbox(0, 0, 10, 10),
        0.9,
        tokens=source_tokens,
    )
    source_occurrences, source_summary = _project(
        lines=[source_line],
        diagnostics=[_diagnostic(accepted=True)],
        owner_bbox=_bbox(0, 0, 10, 10),
        owner_case="source_token_limit",
    )

    return {
        "declared_bounds": {
            "max_source_tokens": MAX_SPATIAL_SOURCE_TOKENS,
            "max_occurrences": MAX_SPATIAL_TOKEN_OCCURRENCES,
            "max_short_alternatives": MAX_SPATIAL_SHORT_ALTERNATIVES,
            "max_token_text_chars": MAX_SPATIAL_TOKEN_TEXT_CHARS,
            "max_serialized_occurrence_json_bytes": (
                MAX_SPATIAL_OCCURRENCE_JSON_BYTES
            ),
        },
        "invalid_and_oversized": {
            "summary": invalid_summary,
            "occurrence_sha256": _sha256_json(invalid_occurrences),
        },
        "short_alternative_limit": {
            "summary": short_summary,
            "occurrence_sha256": _sha256_json(short_occurrences),
        },
        "serialized_byte_limit": {
            "summary": serialized_summary,
            "occurrence_sha256": _sha256_json(serialized_occurrences),
        },
        "source_token_limit": {
            "summary": source_summary,
            "occurrence_sha256": _sha256_json(source_occurrences),
        },
    }


def _healthy_payload() -> dict[str, Any]:
    tokens = [
        _token(
            f"word{index:02d}",
            _bbox(float(index * 12), 10, 10, 6),
            0.98,
            word_index=index,
        )
        for index in range(20)
    ]
    line = _line(
        " ".join(token.text for token in tokens),
        _bbox(0, 10, 240, 6),
        0.98,
        tokens=tokens,
    )
    occurrences, summary = _project(
        lines=[line],
        diagnostics=[_diagnostic(accepted=True)],
        owner_content_type="image",
        include_ocr_in_primary=False,
        owner_bbox=_bbox(0, 0, 300, 200),
        owner_case="healthy_ordinary_ocr",
    )
    return {
        "summary": summary,
        "occurrence_sha256": _sha256_json(occurrences),
    }


def _validate_semantics(
    target: Mapping[str, Any],
    synthetic: Mapping[str, Any],
    bounds: Mapping[str, Any],
    healthy: Mapping[str, Any],
) -> dict[str, Any]:
    target_occurrences = list(target["occurrences"])
    year_occurrences = list(target["year_occurrences"])
    year_records = [
        (item["text"], item["bbox"], item["confidence"])
        for item in year_occurrences
    ]
    expected_records = [
        (record["text"], record["bbox"], record["confidence"])
        for record in (
            _expected_year_record(row) for row in EXPECTED_YEAR_ROWS
        )
    ]
    ih_occurrences = list(target["ih_occurrences"])
    ih = ih_occurrences[0] if len(ih_occurrences) == 1 else {}

    overlap_occurrences = list(
        synthetic["overlap"]["occurrences"]
    )
    overlap_selected = [
        item for item in overlap_occurrences if item["selected"]
    ]
    overlap_duplicates = [
        item
        for item in overlap_occurrences
        if item.get("duplicate_of") is not None
    ]
    distant_occurrences = list(
        synthetic["distant_repetition"]["occurrences"]
    )
    short_occurrences = list(
        synthetic["grounded_short_alternatives"]["occurrences"]
    )
    short_surfaces = synthetic[
        "grounded_short_alternatives"
    ]["canonical_surfaces"]
    negative_cases = list(synthetic["negative_cases"])

    invalid_summary = bounds["invalid_and_oversized"]["summary"]
    short_limit_summary = bounds["short_alternative_limit"]["summary"]
    serialized_summary = bounds["serialized_byte_limit"]["summary"]
    source_summary = bounds["source_token_limit"]["summary"]
    declared = bounds["declared_bounds"]
    target_summary = target["summary"]
    target_summary_exact = bool(
        target_summary["schema_version"] == "1.0"
        and target_summary["total_occurrences"] == 13
        and target_summary["selected_occurrences"] == 13
        and target_summary["primary_selected_occurrences"] == 12
        and target_summary["duplicate_occurrences"] == 0
        and target_summary["short_alternative_occurrences"] == 1
        and target_summary["invalid_occurrences"] == 0
        and target_summary["oversized_text_occurrences"] == 0
        and target_summary["truncated_occurrences"] == 0
        and target_summary["occurrence_limit_reached"] is False
        and target_summary["short_alternative_limit_reached"] is False
        and target_summary["source_token_limit_reached"] is False
        and target_summary["serialized_byte_limit_reached"] is False
        and target_summary["fail_closed_overflow"] is False
        and target_summary["overflow_reason"] is None
    )

    metrics = {
        "retained_target_occurrence_count": len(target_occurrences),
        "retained_target_partition_exact": (
            target_occurrences == [*year_occurrences, *ih_occurrences]
        ),
        "retained_target_summary_exact": target_summary_exact,
        "retained_year_occurrence_count": len(year_occurrences),
        "retained_year_text_bbox_confidence_exact_count": sum(
            actual == expected
            for actual, expected in zip(
                year_records,
                expected_records,
                strict=True,
            )
        )
        if len(year_records) == len(expected_records)
        else 0,
        "retained_year_unique_occurrence_id_count": len(
            {item["occurrence_id"] for item in year_occurrences}
        ),
        "retained_year_selected_count": sum(
            bool(item["selected"]) for item in year_occurrences
        ),
        "retained_year_primary_selected_count": sum(
            bool(item["primary_selected"]) for item in year_occurrences
        ),
        "retained_ih_occurrence_count": len(ih_occurrences),
        "retained_ih_exact": bool(
            ih
            and ih["text"] == "iH"
            and ih["bbox"] == EXPECTED_IH_ROW["bbox"]
            and ih["confidence"] == 0.4437
        ),
        "retained_ih_grounded_short_alternative": bool(
            ih.get("short_alternative")
        ),
        "retained_ih_selected": bool(ih.get("selected")),
        "retained_ih_primary_selected": bool(
            ih.get("primary_selected")
        ),
        "overlap_candidate_count": len(overlap_occurrences),
        "overlap_selected_representative_count": len(overlap_selected),
        "overlap_duplicate_diagnostic_count": len(overlap_duplicates),
        "overlap_primary_selected_token_count": sum(
            bool(item["primary_selected"]) for item in overlap_occurrences
        ),
        "overlap_duplicate_primary_token_count": sum(
            bool(item["primary_selected"])
            for item in overlap_duplicates
        ),
        "overlap_duplicate_points_to_winner": bool(
            len(overlap_selected) == 1
            and len(overlap_duplicates) == 1
            and overlap_duplicates[0]["duplicate_of"]
            == overlap_selected[0]["occurrence_id"]
        ),
        "distant_repeated_token_occurrence_count": len(
            distant_occurrences
        ),
        "distant_repeated_selected_token_count": sum(
            bool(item["selected"]) for item in distant_occurrences
        ),
        "distant_repeated_line_value_count": len(
            synthetic["distant_repetition"][
                "geometry_aware_line_values"
            ]
        ),
        "grounded_short_case_count": len(short_occurrences),
        "grounded_short_alternative_count": sum(
            bool(item["short_alternative"])
            for item in short_occurrences
        ),
        "grounded_short_bbox_confidence_complete_count": sum(
            bool(item["short_alternative"])
            and isinstance(item.get("bbox"), Mapping)
            and isinstance(item.get("confidence"), (int, float))
            for item in short_occurrences
        ),
        "grounded_short_primary_selected_count": sum(
            bool(item["primary_selected"])
            for item in short_occurrences
        ),
        "negative_case_count": len(negative_cases),
        "negative_short_alternative_count": sum(
            int(case["short_alternative_count"])
            for case in negative_cases
        ),
        "canonical_unsupported_short_noise_count": (
            int(target["unsupported_short_primary_surface_count"])
            + sum(
                token in {"iH", "1H"}
                for surface in short_surfaces.values()
                for token in str(surface or "").split()
            )
        ),
        "target_canonical_flag_on_off_parity": bool(
            target["canonical_surface_parity"]
        ),
        "target_flag_off_additive_keys_absent": bool(
            target["flag_off_additive_keys_absent"]
        ),
        "stable_target_occurrence_id_count": len(
            {
                item["occurrence_id"]
                for item in (
                    *year_occurrences,
                    *ih_occurrences,
                )
            }
        ),
        "invalid_geometry_omitted_count": int(
            invalid_summary["invalid_occurrences"]
        ),
        "oversized_text_omitted_count": int(
            invalid_summary["oversized_text_occurrences"]
        ),
        "short_alternative_bound_exact": (
            short_limit_summary["short_alternative_occurrences"]
            == declared["max_short_alternatives"]
            and bool(
                short_limit_summary[
                    "short_alternative_limit_reached"
                ]
            )
        ),
        "serialized_payload_bound_respected": (
            bool(
                serialized_summary["serialized_byte_limit_reached"]
            )
            and serialized_summary["serialized_occurrence_bytes"]
            <= declared["max_serialized_occurrence_json_bytes"]
            and serialized_summary["total_occurrences"]
            <= declared["max_occurrences"]
        ),
        "source_token_bound_exact": (
            bool(source_summary["source_token_limit_reached"])
            and source_summary["oversized_text_occurrences"]
            == declared["max_source_tokens"]
            and source_summary["total_occurrences"] == 0
        ),
        "healthy_occurrence_count": int(
            healthy["summary"]["total_occurrences"]
        ),
        "target_enabled_item_size_bytes": int(
            target["enabled_item_size_bytes"]
        ),
        "target_disabled_item_size_bytes": int(
            target["disabled_item_size_bytes"]
        ),
        "target_additive_item_size_delta_bytes": int(
            target["additive_item_size_delta_bytes"]
        ),
    }
    if not (
        metrics["retained_target_occurrence_count"] == 13
        and metrics["retained_target_partition_exact"]
        and metrics["retained_target_summary_exact"]
        and metrics["retained_year_occurrence_count"] == 12
        and metrics[
            "retained_year_text_bbox_confidence_exact_count"
        ] == 12
        and metrics["retained_year_unique_occurrence_id_count"] == 12
        and metrics["retained_year_selected_count"] == 12
        and metrics["retained_year_primary_selected_count"] == 12
        and metrics["retained_ih_occurrence_count"] == 1
        and metrics["retained_ih_exact"]
        and metrics["retained_ih_grounded_short_alternative"]
        and metrics["retained_ih_selected"]
        and not metrics["retained_ih_primary_selected"]
        and metrics["overlap_candidate_count"] == 2
        and metrics["overlap_selected_representative_count"] == 1
        and metrics["overlap_duplicate_diagnostic_count"] == 1
        and metrics["overlap_primary_selected_token_count"] == 1
        and metrics["overlap_duplicate_primary_token_count"] == 0
        and metrics["overlap_duplicate_points_to_winner"]
        and metrics["distant_repeated_token_occurrence_count"] == 4
        and metrics["distant_repeated_selected_token_count"] == 4
        and metrics["distant_repeated_line_value_count"] == 2
        and metrics["grounded_short_case_count"] == 2
        and metrics["grounded_short_alternative_count"] == 2
        and metrics["grounded_short_bbox_confidence_complete_count"] == 2
        and metrics["grounded_short_primary_selected_count"] == 0
        and metrics["negative_case_count"] == 4
        and metrics["negative_short_alternative_count"] == 0
        and metrics["canonical_unsupported_short_noise_count"] == 0
        and metrics["target_canonical_flag_on_off_parity"]
        and metrics["target_flag_off_additive_keys_absent"]
        and metrics["stable_target_occurrence_id_count"] == 13
        and metrics["invalid_geometry_omitted_count"] == 1
        and metrics["oversized_text_omitted_count"] == 1
        and metrics["short_alternative_bound_exact"]
        and metrics["serialized_payload_bound_respected"]
        and metrics["source_token_bound_exact"]
        and metrics["healthy_occurrence_count"] == 20
        and metrics["target_additive_item_size_delta_bytes"] > 0
    ):
        raise RuntimeError("spatial-token acceptance metrics failed")
    return metrics


def _collect(
    workspace: Path,
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    identities_before = _input_identities(workspace)
    policy_sha256 = identities_before[SPATIAL_TOKEN_POLICY]["sha256"]
    if policy_sha256 != EXPECTED_SPATIAL_TOKEN_POLICY_SHA256:
        raise RuntimeError(
            "accepted spatial-token policy identity mismatch: "
            f"{policy_sha256}"
        )
    catastrophe = retained_catastrophe_binding(workspace)

    target, target_durations, target_rss = _measure_deterministic(
        lambda: _target_payload(catastrophe),
        warmups=warmups,
        samples=samples,
    )
    synthetic, synthetic_durations, synthetic_rss = _measure_deterministic(
        _synthetic_payload,
        warmups=warmups,
        samples=samples,
    )
    bounds, bound_durations, bound_rss = _measure_deterministic(
        _bound_payload,
        warmups=warmups,
        samples=samples,
    )
    healthy, healthy_durations, healthy_rss = _measure_deterministic(
        _healthy_payload,
        warmups=warmups,
        samples=samples,
    )
    semantics = _validate_semantics(target, synthetic, bounds, healthy)

    retained_ceiling = _retained_us05_ceiling(workspace)
    healthy_latency = _distribution(healthy_durations)
    additive_percent = (
        healthy_latency["p95"] / P00_US10_HEALTHY_P95_MS * 100.0
    )
    combined_ceiling = (
        retained_ceiling["arithmetic_ceiling_percent"] + additive_percent
    )
    if combined_ceiling > HEALTHY_OVERHEAD_TARGET_PERCENT:
        raise RuntimeError("cumulative healthy p95 ceiling exceeds target")

    identities_after = _input_identities(workspace)
    custody_match = identities_after == identities_before
    if not custody_match:
        raise RuntimeError("metric inputs changed during collection")

    semantic_payload = {
        "target": target,
        "synthetic_controls": synthetic,
        "resource_bounds": bounds,
        "healthy_control": healthy,
    }
    return {
        "schema_version": "1.0",
        "record_kind": "p02_us06_spatial_token_component_metrics",
        "measurement_scope": (
            "pure production spatial-token and item projection over exact "
            "retained catastrophe evidence plus deterministic synthetic "
            "overlap, distant-repetition, grounded-short, negative, healthy, "
            "and resource-bound controls; no OCR engine, renderer, document "
            "pipeline, layout model, or hosted model is invoked"
        ),
        "workspace": str(workspace),
        "warmups": warmups,
        "samples": samples,
        "run_inputs": identities_before,
        "custody": {
            "pre_post_input_identity_match": custody_match,
            "retained_catastrophe": catastrophe,
            "accepted_policy": identities_before[SPATIAL_TOKEN_POLICY],
            "retained_p02_us05": retained_ceiling,
        },
        "metrics": {
            **semantics,
            "target_projection_latency_ms": _distribution(
                target_durations
            ),
            "synthetic_control_latency_ms": _distribution(
                synthetic_durations
            ),
            "resource_bound_latency_ms": _distribution(bound_durations),
            "healthy_spatial_projection_latency_ms": healthy_latency,
            "healthy_spatial_projection_additive_overhead_percent": (
                additive_percent
            ),
            "combined_healthy_p95_ceiling_reference": {
                "retained_p02_us05_arithmetic_ceiling_percent": (
                    retained_ceiling["arithmetic_ceiling_percent"]
                ),
                "spatial_projection_p95_percent": additive_percent,
                "arithmetic_ceiling_percent": combined_ceiling,
                "target_percent": HEALTHY_OVERHEAD_TARGET_PERCENT,
                "passes_target": (
                    combined_ceiling <= HEALTHY_OVERHEAD_TARGET_PERCENT
                ),
                "observed_paired_full_parser_percentile": False,
            },
            "max_isolated_peak_rss_increment_bytes": max(
                target_rss,
                synthetic_rss,
                bound_rss,
                healthy_rss,
            ),
            "semantic_output_size_bytes": len(
                _canonical_json(semantic_payload)
            ),
            "semantic_output_sha256": _sha256_json(semantic_payload),
            "hosted_model_request_count": 0,
            "hosted_model_token_count": 0,
            "hosted_model_cost_usd": 0.0,
        },
        "semantic_results": semantic_payload,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--output", type=Path)
    return parser


def _validated_output_path(
    workspace: Path,
    requested: Path | None,
) -> Path | None:
    if requested is None:
        return None
    output = requested if requested.is_absolute() else workspace / requested
    output = output.resolve()
    input_paths = {
        (workspace / relative_path).resolve()
        for relative_path in _input_paths(workspace)
    }
    if output in input_paths:
        raise ValueError(f"output collides with a metric input: {output}")
    return output


def _atomic_write_text(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> int:
    args = _parser().parse_args()
    workspace = args.workspace.resolve()
    output = _validated_output_path(workspace, args.output)
    result = _collect(
        workspace,
        warmups=args.warmups,
        samples=args.samples,
    )
    serialized = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if output is not None:
        _atomic_write_text(output, f"{serialized}\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
