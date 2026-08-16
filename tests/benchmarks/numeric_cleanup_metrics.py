"""Deterministic P02-US05 numeric-safe OCR cleanup metrics.

This runner measures the pure OCR line-cleanup component.  It does not invoke
Tesseract, PDFium, Docling, the document pipeline, or a model.  The historical
catastrophe failure is bound to the retained Phase 0 parser output, while
synthetic sequential years, digest identifiers, numeric non-targets, and
resource-bound controls exercise the accepted P02-US05 policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar


RETAINED_CATASTROPHE_OUTPUT = (
    "tracker/benchmarks/llamaparse-15/runs/"
    "baseline-20260728-current/catastrophe-recap/our-output.json"
)
RETAINED_P02_US04_METRICS = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US04-text-reconciliation-metrics.json"
)
NUMERIC_CLEANUP_POLICY = (
    "tracker/phase-02-text-integrity/decisions/"
    "P02-numeric-cleanup-policy.md"
)
DEFAULT_OUTPUT = (
    "tracker/phase-02-text-integrity/evidence/"
    "P02-US05-numeric-cleanup-metrics.json"
)

EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256 = (
    "3f1f0d9b7768e119d65a887e73f54173df633eeca004e9296bcfeb6aebc91abe"
)
EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256 = (
    "d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e"
)
EXPECTED_RETAINED_P02_US04_METRICS_SHA256 = (
    "e877a82921b16a071afaade99d4d72fdf6ebfc9e4bb49260bb9c7c08205c1479"
)
EXPECTED_NUMERIC_CLEANUP_POLICY_SHA256 = (
    "aac6e27ac01e81186d94735ca1a842123de86f6a1909565849997d6f60f66cd1"
)

P00_US10_HEALTHY_P95_MS = 46_760.0
HEALTHY_OVERHEAD_TARGET_PERCENT = 10.0

OBSERVED_YEAR_TOKENS = (
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
OBSERVED_YEAR_LINE = " ".join(OBSERVED_YEAR_TOKENS)
OBSERVED_LEGACY_FALSE_JOIN = "".join(OBSERVED_YEAR_TOKENS)
SEQUENTIAL_YEAR_TOKENS = tuple(str(year) for year in range(2010, 2022))
SEQUENTIAL_YEAR_LINE = " ".join(SEQUENTIAL_YEAR_TOKENS)
SEQUENTIAL_LEGACY_FALSE_JOIN = "".join(SEQUENTIAL_YEAR_TOKENS)
OBSERVED_YEAR_BBOX = {
    "x": 125.021,
    "y": 562.51,
    "w": 417.2,
    "h": 4.6,
    "width": 417.2,
    "height": 4.6,
    "unit": "pt",
}

DIGEST_LABEL_LENGTHS: tuple[tuple[str, int], ...] = (
    ("MD5", 32),
    ("SHA1", 40),
    ("SHA-1", 40),
    ("SHA224", 56),
    ("SHA-224", 56),
    ("SHA256", 64),
    ("SHA-256", 64),
    ("SHA384", 96),
    ("SHA-384", 96),
    ("SHA512", 128),
    ("SHA-512", 128),
)
GENERIC_DIGEST_LABELS = ("HASH", "CHECKSUM", "DIGEST", "FINGERPRINT")
STANDARD_DIGEST_LENGTHS = (32, 40, 56, 64, 96, 128)

PRODUCTION_AND_TEST_INPUTS = (
    "app/services/ocr.py",
    "app/services/selective_span_ocr.py",
    "app/services/pipeline.py",
    "app/config.py",
    ".env.example",
    "README.md",
    NUMERIC_CLEANUP_POLICY,
    RETAINED_CATASTROPHE_OUTPUT,
    RETAINED_P02_US04_METRICS,
    "tests/benchmarks/numeric_cleanup_metrics.py",
    "tests/stories/phase_02/test_p02_us05_numeric_cleanup.py",
    "tests/contract/test_p02_us05_numeric_cleanup_contract.py",
    (
        "tests/regression/phase_02/"
        "test_p02_us05_numeric_cleanup_adversarial_review.py"
    ),
    "tests/regression/phase_02/test_p02_us05_numeric_cleanup_regression.py",
    "tests/performance/test_p02_us05_numeric_cleanup_performance.py",
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


def _input_identities(workspace: Path) -> dict[str, dict[str, Any]]:
    return {
        relative_path: _file_identity(workspace, relative_path)
        for relative_path in PRODUCTION_AND_TEST_INPUTS
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("at least one observation is required")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("observations must be finite and non-negative")
    ordered = sorted(values)
    rank = max(math.ceil(percentile * len(ordered)), 1)
    return ordered[rank - 1]


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


def _digest_value(length: int) -> str:
    return ("ABCDEF0123456789" * 8)[:length]


def _fragments(value: str, width: int = 4) -> tuple[str, ...]:
    return tuple(
        value[index : index + width]
        for index in range(0, len(value), width)
    )


def digest_cases() -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    for label, length in DIGEST_LABEL_LENGTHS:
        value = _digest_value(length)
        separator = "=" if label in {"SHA1", "SHA224", "SHA384"} else ":"
        cases.append(
            {
                "case_id": f"{label.lower()}-{length}".replace("-", "_"),
                "label": label,
                "length": length,
                "input": f"{label}{separator} {' '.join(_fragments(value))}",
                "expected": f"{label}{separator} {value}",
                "value": value,
            }
        )
    for label in GENERIC_DIGEST_LABELS:
        for length in STANDARD_DIGEST_LENGTHS:
            value = _digest_value(length)
            cases.append(
                {
                    "case_id": f"{label.lower()}-{length}",
                    "label": label,
                    "length": length,
                    "input": f"{label}: {' '.join(_fragments(value))}",
                    "expected": f"{label}: {value}",
                    "value": value,
                }
            )
    return tuple(cases)


def numeric_control_cases() -> tuple[dict[str, str], ...]:
    digest_64 = _digest_value(64)
    digest_fragments = " ".join(_fragments(digest_64))
    lowercase_fragments = digest_fragments.lower()
    return (
        {
            "case_id": "iso_date_and_time",
            "input": "2026 07 30 12 45 59",
        },
        {
            "case_id": "money",
            "input": "$ 1250 2025 4500 10000 75000 250000",
        },
        {
            "case_id": "percentages",
            "input": "5 10 25 50 75 90 100",
        },
        {
            "case_id": "page_numbers",
            "input": "Page 20 21 22 23 24 25 of 120",
        },
        {
            "case_id": "ordinary_numeric_list",
            "input": "1000 2000 3000 4000 5000 6000",
        },
        {
            "case_id": "decimal_digest_length_after_hash_label",
            "input": (
                "SHA-256: "
                "0000 1111 2222 3333 4444 5555 6666 7777 "
                "8888 9999 0000 1111 2222 3333 4444 5555"
            ),
        },
        {
            "case_id": "bare_known_length_hex",
            "input": digest_fragments,
        },
        {
            "case_id": "generic_id",
            "input": f"ID: {digest_fragments}",
        },
        {
            "case_id": "invoice_identifier",
            "input": f"Invoice: {digest_fragments}",
        },
        {
            "case_id": "account_identifier",
            "input": f"Account: {digest_fragments}",
        },
        {
            "case_id": "serial_identifier",
            "input": f"Serial: {digest_fragments}",
        },
        {
            "case_id": "distant_digest_label",
            "input": f"SHA-256: verified value {digest_fragments}",
        },
        {
            "case_id": "lowercase_candidate",
            "input": f"SHA-256: {lowercase_fragments}",
        },
        {
            "case_id": "punctuated_candidate",
            "input": "SHA-256: " + " ".join(
                f"{fragment}," for fragment in _fragments(digest_64)
            ),
        },
        {
            "case_id": "unicode_confusable_candidate",
            "input": f"SHA-256: АBCD {digest_fragments[5:]}",
        },
        {
            "case_id": "mixed_ordinary_alphanumeric",
            "input": (
                "AB12 CD34 EF56 A789 BC01 DE23 F456 A789 "
                "BC01 DE23 F456 A789 BC01 DE23 F456 A789"
            ),
        },
    )


def bound_cases() -> tuple[dict[str, str], ...]:
    valid_value = _digest_value(64)
    return (
        {
            "case_id": "line_character_limit",
            "input": (
                ("ordinary " * 7_282)
                + "SHA-256: "
                + " ".join(_fragments(valid_value))
            ),
        },
        {
            "case_id": "line_token_limit",
            "input": (
                ("x " * 4_097)
                + "SHA-256: "
                + " ".join(_fragments(valid_value))
            ),
        },
        {
            "case_id": "fragment_count_limit",
            "input": "HASH: " + " ".join("AB" for _ in range(65)),
        },
        {
            "case_id": "candidate_character_limit",
            "input": "HASH: " + " ".join("ABCD" for _ in range(33)),
        },
    )


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _cleanup(value: str, *, enabled: bool) -> str:
    from app.services.ocr import _clean_ocr_line

    if enabled:
        return _clean_ocr_line(
            value,
            numeric_cleanup_v2_enabled=True,
        )
    return _clean_ocr_line(value)


def _target_payload() -> dict[str, Any]:
    return {
        "observed": {
            "input": OBSERVED_YEAR_LINE,
            "flag_on": _cleanup(OBSERVED_YEAR_LINE, enabled=True),
            "flag_off": _cleanup(OBSERVED_YEAR_LINE, enabled=False),
        },
        "sequential": {
            "input": SEQUENTIAL_YEAR_LINE,
            "flag_on": _cleanup(SEQUENTIAL_YEAR_LINE, enabled=True),
            "flag_off": _cleanup(SEQUENTIAL_YEAR_LINE, enabled=False),
        },
    }


def _digest_payload() -> dict[str, Any]:
    rows = [
        {
            "case_id": case["case_id"],
            "length": case["length"],
            "expected": case["expected"],
            "flag_on": _cleanup(str(case["input"]), enabled=True),
            "flag_off": _cleanup(str(case["input"]), enabled=False),
        }
        for case in digest_cases()
    ]
    return {"cases": rows}


def _control_payload() -> dict[str, Any]:
    rows = [
        {
            "case_id": case["case_id"],
            "expected": _normalized(case["input"]),
            "flag_on": _cleanup(case["input"], enabled=True),
        }
        for case in numeric_control_cases()
    ]
    return {"cases": rows}


def _bound_payload() -> dict[str, Any]:
    rows = [
        {
            "case_id": case["case_id"],
            "expected_sha256": hashlib.sha256(
                _normalized(case["input"]).encode("utf-8")
            ).hexdigest(),
            "flag_on_sha256": hashlib.sha256(
                _cleanup(case["input"], enabled=True).encode("utf-8")
            ).hexdigest(),
            "output_size_bytes": len(
                _cleanup(case["input"], enabled=True).encode("utf-8")
            ),
        }
        for case in bound_cases()
    ]
    return {"cases": rows}


def _walk_matches(value: Any, expected_text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("text") == expected_text:
            matches.append(value)
        for child in value.values():
            matches.extend(_walk_matches(child, expected_text))
    elif isinstance(value, list):
        for child in value:
            matches.extend(_walk_matches(child, expected_text))
    return matches


def retained_catastrophe_binding(workspace: Path) -> dict[str, Any]:
    identity = _file_identity(workspace, RETAINED_CATASTROPHE_OUTPUT)
    if identity["sha256"] != EXPECTED_RETAINED_CATASTROPHE_OUTPUT_SHA256:
        raise RuntimeError("retained catastrophe parser output identity drifted")
    payload = _load_json(workspace / RETAINED_CATASTROPHE_OUTPUT)
    source_sha256 = str(payload["document"]["sha256"])
    if source_sha256 != EXPECTED_RETAINED_CATASTROPHE_SOURCE_SHA256:
        raise RuntimeError("retained catastrophe source identity drifted")
    matches = _walk_matches(payload, OBSERVED_LEGACY_FALSE_JOIN)
    if (
        len(matches) != 2
        or any(row.get("word_count") != 12 for row in matches)
        or any(row.get("bbox") != OBSERVED_YEAR_BBOX for row in matches)
    ):
        raise RuntimeError(
            "retained catastrophe 12-label diagnostic binding drifted"
        )
    return {
        "artifact": identity,
        "source_sha256": source_sha256,
        "observed_source_tokens": list(OBSERVED_YEAR_TOKENS),
        "legacy_false_join": OBSERVED_LEGACY_FALSE_JOIN,
        "word_count": 12,
        "matching_diagnostic_surface_count": len(matches),
        "bbox": dict(OBSERVED_YEAR_BBOX),
    }


def _retained_us04_ceiling(workspace: Path) -> dict[str, Any]:
    identity = _file_identity(workspace, RETAINED_P02_US04_METRICS)
    if identity["sha256"] != EXPECTED_RETAINED_P02_US04_METRICS_SHA256:
        raise RuntimeError("retained P02-US04 metrics identity drifted")
    payload = _load_json(workspace / RETAINED_P02_US04_METRICS)
    ceiling = payload["summary"]["combined_healthy_p95_ceiling_reference"]
    if not isinstance(ceiling, dict):
        raise TypeError("retained P02-US04 ceiling must be an object")
    return {
        "artifact": identity,
        "arithmetic_ceiling_percent": float(
            ceiling["arithmetic_ceiling_percent"]
        ),
        "observed_paired_full_parser_percentile": bool(
            ceiling["observed_paired_full_parser_percentile"]
        ),
    }


def _validate_semantics(
    target: Mapping[str, Any],
    digests: Mapping[str, Any],
    controls: Mapping[str, Any],
    bounds: Mapping[str, Any],
) -> dict[str, Any]:
    observed = target["observed"]
    sequential = target["sequential"]
    digest_rows = list(digests["cases"])
    control_rows = list(controls["cases"])
    bound_rows = list(bounds["cases"])
    observed_retained = str(observed["flag_on"]).split()
    sequential_retained = str(sequential["flag_on"]).split()
    return {
        "observed_year_token_count": len(observed_retained),
        "observed_years_exact": observed_retained
        == list(OBSERVED_YEAR_TOKENS),
        "observed_48_digit_false_join_count": int(
            observed["flag_on"] == OBSERVED_LEGACY_FALSE_JOIN
        ),
        "flag_off_observed_legacy_exact": observed["flag_off"]
        == OBSERVED_LEGACY_FALSE_JOIN,
        "sequential_year_token_count": len(sequential_retained),
        "sequential_years_exact": sequential_retained
        == list(SEQUENTIAL_YEAR_TOKENS),
        "flag_off_sequential_legacy_exact": sequential["flag_off"]
        == SEQUENTIAL_LEGACY_FALSE_JOIN,
        "approved_digest_case_count": len(digest_rows),
        "approved_digest_join_count": sum(
            row["flag_on"] == row["expected"] for row in digest_rows
        ),
        "approved_digest_flag_off_compatibility_count": sum(
            row["flag_off"] == row["expected"] for row in digest_rows
        ),
        "numeric_control_case_count": len(control_rows),
        "numeric_control_exact_count": sum(
            row["flag_on"] == row["expected"] for row in control_rows
        ),
        "bound_case_count": len(bound_rows),
        "bound_fail_closed_count": sum(
            row["flag_on_sha256"] == row["expected_sha256"]
            for row in bound_rows
        ),
    }


def _collect(
    workspace: Path,
    *,
    warmups: int,
    samples: int,
) -> dict[str, Any]:
    workspace = workspace.resolve()
    identities_before = _input_identities(workspace)
    policy_identity = identities_before[NUMERIC_CLEANUP_POLICY]
    if policy_identity["sha256"] != EXPECTED_NUMERIC_CLEANUP_POLICY_SHA256:
        raise RuntimeError("accepted numeric-cleanup policy identity drifted")

    target, target_durations, target_rss = _measure_deterministic(
        _target_payload,
        warmups=warmups,
        samples=samples,
    )
    digests, digest_durations, digest_rss = _measure_deterministic(
        _digest_payload,
        warmups=warmups,
        samples=samples,
    )
    controls, control_durations, control_rss = _measure_deterministic(
        _control_payload,
        warmups=warmups,
        samples=samples,
    )
    bounds, bound_durations, bound_rss = _measure_deterministic(
        _bound_payload,
        warmups=warmups,
        samples=samples,
    )
    semantics = _validate_semantics(target, digests, controls, bounds)
    if not (
        semantics["observed_years_exact"]
        and semantics["observed_48_digit_false_join_count"] == 0
        and semantics["flag_off_observed_legacy_exact"]
        and semantics["sequential_years_exact"]
        and semantics["flag_off_sequential_legacy_exact"]
        and semantics["approved_digest_join_count"]
        == semantics["approved_digest_case_count"]
        and semantics["approved_digest_flag_off_compatibility_count"]
        == semantics["approved_digest_case_count"]
        and semantics["numeric_control_exact_count"]
        == semantics["numeric_control_case_count"]
        and semantics["bound_fail_closed_count"]
        == semantics["bound_case_count"]
    ):
        raise RuntimeError("numeric-cleanup acceptance metrics failed")

    retained_ceiling = _retained_us04_ceiling(workspace)
    healthy_latency = _distribution(control_durations)
    additive_percent = (
        healthy_latency["p95"] / P00_US10_HEALTHY_P95_MS * 100.0
    )
    combined_ceiling = (
        retained_ceiling["arithmetic_ceiling_percent"] + additive_percent
    )
    identities_after = _input_identities(workspace)
    custody_match = identities_after == identities_before
    if not custody_match:
        raise RuntimeError("metric inputs changed during collection")

    semantic_payload = {
        "target": target,
        "digests": digests,
        "controls": controls,
        "bounds": bounds,
    }
    return {
        "schema_version": "1.0",
        "record_kind": "p02_us05_numeric_cleanup_component_metrics",
        "measurement_scope": (
            "pure production OCR line cleanup over one exact retained "
            "catastrophe diagnostic binding plus deterministic synthetic "
            "digest, numeric non-target, and resource-bound controls; no "
            "OCR engine, renderer, document pipeline, layout model, or "
            "hosted model is invoked"
        ),
        "workspace": str(workspace),
        "warmups": warmups,
        "samples": samples,
        "run_inputs": identities_before,
        "custody": {
            "pre_post_input_identity_match": custody_match,
            "retained_catastrophe": retained_catastrophe_binding(workspace),
            "accepted_policy": policy_identity,
            "retained_p02_us04": retained_ceiling,
        },
        "metrics": {
            **semantics,
            "target_cleanup_latency_ms": _distribution(target_durations),
            "approved_digest_cleanup_latency_ms": _distribution(
                digest_durations
            ),
            "healthy_numeric_cleanup_latency_ms": healthy_latency,
            "resource_bound_cleanup_latency_ms": _distribution(
                bound_durations
            ),
            "healthy_numeric_cleanup_additive_overhead_percent": (
                additive_percent
            ),
            "combined_healthy_p95_ceiling_reference": {
                "retained_p02_us04_arithmetic_ceiling_percent": (
                    retained_ceiling["arithmetic_ceiling_percent"]
                ),
                "numeric_cleanup_p95_percent": additive_percent,
                "arithmetic_ceiling_percent": combined_ceiling,
                "target_percent": HEALTHY_OVERHEAD_TARGET_PERCENT,
                "passes_target": (
                    combined_ceiling <= HEALTHY_OVERHEAD_TARGET_PERCENT
                ),
                "observed_paired_full_parser_percentile": False,
            },
            "max_isolated_peak_rss_increment_bytes": max(
                target_rss,
                digest_rss,
                control_rss,
                bound_rss,
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


def main() -> int:
    args = _parser().parse_args()
    result = _collect(
        args.workspace,
        warmups=args.warmups,
        samples=args.samples,
    )
    serialized = json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{serialized}\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
