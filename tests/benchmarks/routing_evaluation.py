"""Offline, source-bound audit of saved parser responses; never calls a model.

Run with ``python -m tests.benchmarks.routing_evaluation --manifest ...``.
This is benchmark infrastructure, not a production router or accuracy score.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.deterministic_confidence import DeterministicConfidence


VERSION = "1.0"
MAX_JSON_BYTES = 32 * 1024 * 1024
_MISSING = object()
LIMITATIONS = [
    "Rule outcomes and OCR confidence are not calibrated probabilities or proof of correctness.",
    "No expectation means unevaluated, never a pass. Passing checks cover only the supplied claims.",
    "Source hashes bind artifacts; this tool does not visually verify reviewer-authored ground truth.",
    "Evidence audits check top-level page items and table cells, not every nested semantic sidecar.",
    "Geometry and source labels establish traceability presence, not text or table accuracy.",
    "Comparisons are exact typed JSON values; no fuzzy text, numeric tolerance, or semantic equivalence is inferred.",
    "No OCR, model, network, or parser execution occurs; performance and cost are only supplied measurements.",
    "Paired improvement does not prove causality, generalization, or production routing safety.",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class Source(Contract):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Measurements(Contract):
    latency_ms: float | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    method: str = Field(min_length=1)


class ResponseArtifact(Contract):
    path: str = Field(min_length=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    measurements: Measurements | None = None


class Case(Contract):
    case_id: str = Field(min_length=1)
    source: Source
    baseline: ResponseArtifact
    candidate: ResponseArtifact | None = None
    expected_path: str | None = Field(default=None, min_length=1)


class Manifest(Contract):
    schema_version: Literal["1.0"]
    cases: list[Case] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_cases(self) -> Manifest:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        return self


class Selector(Contract):
    page_index: int | None = Field(default=None, ge=1)
    item_type: str | list[str] = Field(min_length=1)
    match: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def nonempty_types(self) -> Selector:
        if isinstance(self.item_type, list) and any(not value for value in self.item_type):
            raise ValueError("item types must be nonempty")
        return self


class Check(Contract):
    check_id: str = Field(min_length=1)
    kind: Literal["field", "rows"]
    selector: Selector
    pointer: str = Field(pattern=r"^(?:/.*)?$")
    expected: Any
    expected_count: int = Field(default=1, ge=1, le=10000)
    ordered: bool = True
    truth_class: Literal["visible_text", "native_data", "embedded_data"]
    evidence_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_rows(self) -> Check:
        if self.kind == "rows":
            if not isinstance(self.expected, list) or any(
                not isinstance(row, list) for row in self.expected
            ):
                raise ValueError("row expectations must be arrays of complete rows")
            if self.expected_count != 1:
                raise ValueError("row multiplicity belongs in expected rows")
        if re.search(r"~(?![01])", self.pointer):
            raise ValueError("invalid JSON pointer escape")
        return self


class Expectations(Contract):
    schema_version: Literal["1.0"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1)
    coverage: Literal["selected_claims", "complete_for_case"] = "selected_claims"
    checks: list[Check] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def unique_checks(self) -> Expectations:
        if len({check.check_id for check in self.checks}) != len(self.checks):
            raise ValueError("check IDs must be unique")
        return self


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON exceeds {MAX_JSON_BYTES} bytes: {path.name}")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant, parse_float=_finite_float)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value, hashlib.sha256(raw).hexdigest()


def _path(root: Path, value: str) -> Path:
    requested = Path(value)
    if requested.is_absolute():
        raise ValueError("artifact paths must be workspace-relative")
    resolved = (root / requested).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"artifact missing or outside workspace: {value}")
    return resolved


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(token, _MISSING)
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            index = int(token)
            value = value[index] if index < len(value) else _MISSING
        else:
            return _MISSING
        if value is _MISSING:
            return value
    return value


def _items(response: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (page, item)
        for page in response["pages"]
        for item in page["items"]
    ]


def _shape(response: dict[str, Any], source_sha256: str) -> None:
    if response.get("schema_version") != VERSION:
        raise ValueError("unsupported raw API schema version")
    document = response.get("document")
    if not isinstance(document, dict) or document.get("sha256") != source_sha256:
        raise ValueError("response document.sha256 does not match the source")
    pages = response.get("pages")
    if not isinstance(pages, list):
        raise ValueError("raw API response requires pages array")
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ValueError("raw API pages require items arrays")
        if any(not isinstance(item, dict) for item in page["items"]):
            raise ValueError("raw API items must be objects")


def _box_present(value: Any, page: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    coordinates = [value.get("x"), value.get("y"), value.get("width", value.get("w")), value.get("height", value.get("h"))]
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in coordinates):
        return False
    x, y, width, height = coordinates
    if min(x, y) < 0 or width <= 0 or height <= 0:
        return False
    if value.get("unit", page.get("unit")) != page.get("unit"):
        return False
    page_width, page_height = page.get("page_width"), page.get("page_height")
    return (
        type(page_width) in (int, float)
        and type(page_height) in (int, float)
        and math.isfinite(page_width) and math.isfinite(page_height)
        and x + width <= page_width + 0.01 and y + height <= page_height + 0.01
    )


def audit_evidence(response: dict[str, Any]) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    page_ids: list[Any] = []
    for position, page in enumerate(response["pages"], 1):
        index = page.get("page_index")
        page_ids.append(index)
        if type(index) is not int or index != position:
            gaps.append({"code": "physical_page_identity_invalid", "page_position": position})
        if type(page.get("success")) is not bool:
            gaps.append({"code": "page_completion_unreported", "page_position": position})
        seen: set[str] = set()
        for item_position, item in enumerate(page["items"]):
            counts["items"] += 1
            location = {"page_position": position, "item_position": item_position, "item_id": item.get("id")}
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id or item_id in seen:
                gaps.append({"code": "item_identity_missing_or_duplicate", **location})
            else:
                counts["items_with_unique_id"] += 1
                seen.add(item_id)
            if item.get("source") in ("native", "ocr", "mixed", "derived"):
                counts["items_with_source_label"] += 1
            else:
                gaps.append({"code": "source_label_missing", **location})
            if page.get("unit") == "logical":
                counts["items_with_logical_coordinates"] += 1
            elif _box_present(item.get("bbox"), page):
                counts["items_with_physical_geometry"] += 1
            else:
                gaps.append({"code": "physical_geometry_missing_or_invalid", **location})
            if item.get("type") in ("table", "table_candidate"):
                cells = item.get("cells")
                if not isinstance(cells, list) or not cells:
                    gaps.append({"code": "cell_evidence_unavailable", **location})
                else:
                    for cell in cells:
                        counts["table_cells"] += 1
                        if isinstance(cell, dict) and all(
                            isinstance(cell.get(key), list)
                            and bool(cell[key])
                            and all(isinstance(value, str) and value for value in cell[key])
                            for key in ("evidence_ids", "source_object_ids")
                        ):
                            counts["cells_with_evidence_references"] += 1
                        else:
                            gaps.append({"code": "cell_evidence_reference_missing", **location})
    if response["document"].get("page_count") != len(page_ids):
        gaps.append({"code": "document_page_count_mismatch"})
    if not page_ids:
        gaps.append({"code": "no_pages_returned"})
    elif not counts["items"]:
        gaps.append({"code": "no_items_returned"})
    return {"counts": dict(counts), "gaps": gaps, "scope": "traceability_presence_only"}


def audit_routing(response: dict[str, Any]) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    for scope, node in [("document", response), *[(f"page:{i}", page) for i, page in enumerate(response["pages"], 1)]]:
        if node.get("warnings"):
            signals.append({"scope": scope, "kind": "warnings", "value": node["warnings"]})
        if node.get("success") is False:
            signals.append({"scope": scope, "kind": "page_failure"})
    for page, item in _items(response):
        for key in ("parse_concerns", "concern_codes"):
            if item.get(key):
                signals.append({"scope": f"page:{page.get('page_index')}/item:{item.get('id')}", "kind": key, "value": item[key]})
    raw = response.get("deterministic_confidence")
    if raw is None:
        return {"status": "unobserved", "decision": None, "flagged": None, "has_review_signals": bool(signals), "signals": signals, "dimensions": None}
    try:
        sidecar = DeterministicConfidence.model_validate(raw)
    except ValueError:
        return {"status": "invalid", "decision": None, "flagged": None, "has_review_signals": bool(signals), "signals": signals, "dimensions": None}
    return {
        "status": "observed",
        "decision": sidecar.overall_decision,
        "flagged": sidecar.overall_decision != "accept" or bool(signals),
        "has_review_signals": bool(signals),
        "signals": signals,
        "dimensions": [dimension.model_dump(mode="json") for dimension in sidecar.dimensions],
        "policy_id": sidecar.policy_id,
        "value_semantics": sidecar.value_semantics,
    }


def evaluate_check(response: dict[str, Any], check: Check) -> dict[str, Any]:
    values: list[Any] = []
    matched = 0
    invalid = 0
    for page, item in _items(response):
        selector = check.selector
        if selector.page_index is not None and page.get("page_index") != selector.page_index:
            continue
        types = [selector.item_type] if isinstance(selector.item_type, str) else selector.item_type
        if item.get("type") not in types or any(
            key not in item or _canonical(item[key]) != _canonical(value)
            for key, value in selector.match.items()
        ):
            continue
        matched += 1
        observed = _pointer(item, check.pointer)
        if observed is _MISSING:
            invalid += 1
        elif check.kind == "rows":
            if not isinstance(observed, list) or any(not isinstance(row, list) for row in observed):
                invalid += 1
            else:
                values.extend(observed)
        else:
            values.append(observed)
    expected = check.expected if check.kind == "rows" else [check.expected] * check.expected_count
    actual_counts = Counter(map(_canonical, values))
    expected_counts = Counter(map(_canonical, expected))
    missing = expected_counts - actual_counts
    extra = actual_counts - expected_counts
    duplicate_extras = sum(
        min(extra[key], max(0, count - 1)) for key, count in actual_counts.items()
    )
    order_matches = (
        list(map(_canonical, values)) == list(map(_canonical, expected))
        if check.kind == "rows" and check.ordered else None
    )
    passed = not missing and not extra and invalid == 0 and matched > 0 and order_matches is not False
    return {
        "check_id": check.check_id,
        "kind": check.kind,
        "status": "pass" if passed else "fail",
        "matched_items": matched,
        "missing_or_invalid_value_paths": invalid,
        "expected_count": len(expected),
        "observed_count": len(values),
        "missing_count": sum(missing.values()),
        "extra_count": sum(extra.values()),
        "duplicate_extra_count": duplicate_extras,
        "row_order_matches": order_matches,
        "missing": [{"value": json.loads(value), "count": count} for value, count in sorted(missing.items())],
        "extra": [{"value": json.loads(value), "count": count} for value, count in sorted(extra.items())],
        "truth_class": check.truth_class,
        "evidence_ref": check.evidence_ref,
    }


def _measurements(response: dict[str, Any], provided: Measurements | None) -> dict[str, Any]:
    if provided is not None:
        return {**provided.model_dump(), "basis": "manifest_measurement"}
    processing = response.get("processing")
    latency = processing.get("duration_ms") if isinstance(processing, dict) else None
    if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
        latency = None
    return {"latency_ms": latency, "cost_usd": None, "method": "API processing.duration_ms" if latency is not None else None, "basis": "api_reported" if latency is not None else "unavailable"}


def evaluate_response(response: dict[str, Any], *, source_sha256: str, expected: Expectations | None = None, measurements: Measurements | None = None) -> dict[str, Any]:
    _shape(response, source_sha256)
    if expected is not None and expected.source_sha256 != source_sha256:
        raise ValueError("ground-truth source hash differs")
    checks = [evaluate_check(response, check) for check in expected.checks] if expected else []
    routing = audit_routing(response)
    failures = sum(check["status"] == "fail" for check in checks)
    if not checks:
        classification = "unevaluated"
    elif routing["flagged"] is None:
        classification = "routing_unobserved"
    else:
        classification = ("flagged" if routing["flagged"] else "unflagged") + ("_error" if failures else "_no_checked_error")
    return {
        "routing": routing,
        "evidence": audit_evidence(response),
        "quality": {"status": "unevaluated" if not checks else "checked_errors" if failures else "checked_claims_pass", "coverage": expected.coverage if expected else None, "reviewer": expected.reviewer if expected else None, "checked": len(checks), "failed": failures, "checks": checks},
        "routing_evaluation": classification,
        "measurements": _measurements(response, measurements),
    }


def compare_responses(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    before = {check["check_id"]: check for check in baseline["quality"]["checks"]}
    after = {check["check_id"]: check for check in candidate["quality"]["checks"]}
    if before.keys() != after.keys():
        raise ValueError("paired responses must use identical expected check IDs")
    categories: dict[str, list[str]] = {key: [] for key in ("corrected", "harmed", "still_failing", "preserved")}
    for key in before:
        left, right = before[key]["status"], after[key]["status"]
        category = "corrected" if (left, right) == ("fail", "pass") else "harmed" if (left, right) == ("pass", "fail") else "preserved" if right == "pass" else "still_failing"
        categories[category].append(key)
    deltas: dict[str, float | None] = {}
    for metric in ("latency_ms", "cost_usd"):
        left, right = baseline["measurements"][metric], candidate["measurements"][metric]
        deltas[metric] = right - left if left is not None and right is not None else None
    return {"status": "evaluated" if before else "unevaluated", **categories, "measurement_delta_candidate_minus_baseline": deltas, "baseline_decision": baseline["routing"]["decision"], "candidate_decision": candidate["routing"]["decision"]}


def evaluate_manifest(manifest_path: Path, workspace: Path) -> dict[str, Any]:
    payload, manifest_sha = _read_json(manifest_path)
    manifest = Manifest.model_validate(payload)
    cases: list[dict[str, Any]] = []
    for case in manifest.cases:
        source = _path(workspace, case.source.path)
        if _source_hash(source) != case.source.sha256:
            raise ValueError(f"source hash differs: {case.case_id}")
        expected = None
        expected_sha = None
        if case.expected_path:
            expected_payload, expected_sha = _read_json(_path(workspace, case.expected_path))
            expected = Expectations.model_validate(expected_payload)
        record: dict[str, Any] = {"case_id": case.case_id, "source": case.source.model_dump(), "expected_sha256": expected_sha}
        for role in ("baseline", "candidate"):
            artifact = getattr(case, role)
            if artifact is None:
                record[role] = None
                continue
            response, response_sha = _read_json(_path(workspace, artifact.path))
            if artifact.sha256 is not None and artifact.sha256 != response_sha:
                raise ValueError(f"response hash differs: {case.case_id}/{role}")
            record[role] = {"response_path": artifact.path, "response_sha256": response_sha, **evaluate_response(response, source_sha256=case.source.sha256, expected=expected, measurements=artifact.measurements)}
        record["comparison"] = compare_responses(record["baseline"], record["candidate"]) if record["candidate"] else None
        cases.append(record)
    summary: dict[str, Any] = {"cases": len(cases)}
    for role in ("baseline", "candidate"):
        results = [case[role] for case in cases if case[role] is not None]
        summary[role] = {
            "cases": len(results),
            "routing_status_counts": dict(Counter(result["routing"]["status"] for result in results)),
            "classification_counts": dict(Counter(result["routing_evaluation"] for result in results)),
            "checked_claims": sum(result["quality"]["checked"] for result in results),
            "failed_claims": sum(result["quality"]["failed"] for result in results),
            "false_positive_candidates_complete_cases": sum(result["routing_evaluation"] == "flagged_no_checked_error" and result["quality"]["coverage"] == "complete_for_case" for result in results),
        }
        for metric in ("latency_ms", "cost_usd"):
            values = [result["measurements"][metric] for result in results if result["measurements"][metric] is not None]
            summary[role][metric] = {"observed_cases": len(values), "missing_cases": len(results) - len(values), "observed_sum": sum(values) if values else None, "observed_mean": sum(values) / len(values) if values else None}
    summary["paired_checks"] = {name: sum(len(case["comparison"][name]) for case in cases if case["comparison"]) for name in ("corrected", "harmed", "still_failing", "preserved")}
    return {"schema_version": VERSION, "report_kind": "offline_routing_evaluation", "manifest_sha256": manifest_sha, "limitations": LIMITATIONS, "summary": summary, "cases": cases}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        report = evaluate_manifest(args.manifest, args.workspace.resolve())
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error), "report_kind": "offline_routing_evaluation"}), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
