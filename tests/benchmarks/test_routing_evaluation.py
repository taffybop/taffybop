"""Synthetic checks for omissions, false alarms, and harmful fallback changes."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.benchmarks.routing_evaluation import (
    Check,
    Expectations,
    Measurements,
    compare_responses,
    evaluate_manifest,
    evaluate_response,
    main,
)


SOURCE = b"synthetic reviewed source: SKU A 12.00; SKU B 20.00"
SHA = hashlib.sha256(SOURCE).hexdigest()


def confidence(decision="accept"):
    level = {"accept": "supported", "concern": "guarded", "fallback": "unsupported"}[decision]
    return {
        "schema_version": "1.0", "policy_id": "p08-release-confidence-v1",
        "basis": "deterministic_rules", "value_semantics": "categorical_not_probability",
        "overall_decision": decision,
        "dimensions": [
            {"dimension": name, "applicability": "applicable", "level": level,
             "decision": decision, "reason_codes": ["explicit_concern_reported" if decision != "accept" else "native_text_source"]}
            for name in ("text", "layout", "table")
        ],
    }


def item(kind, value, **extras):
    return {
        "id": f"{kind}-1", "type": kind, "value": value,
        "source": "native", "reading_order": 0,
        "bbox": {"x": 1, "y": 1, "width": 90, "height": 90, "unit": "pt"},
        **extras,
    }


def response(*items, decision="accept"):
    return {
        "schema_version": "1.0",
        "document": {"sha256": SHA, "page_count": 1},
        "pages": [{"page_index": 1, "page_number": 1, "page_width": 100,
                   "page_height": 100, "unit": "pt", "success": True,
                   "items": list(items), "warnings": []}],
        "processing": {"duration_ms": 12}, "warnings": [],
        "deterministic_confidence": confidence(decision),
    }


def field_check(**changes):
    return {
        "check_id": "total", "kind": "field",
        "selector": {"item_type": "key_value", "match": {"key": "total"}},
        "pointer": "/value", "expected": "32.00",
        "truth_class": "visible_text", "evidence_ref": "synthetic source, total field",
        **changes,
    }


def row_check(**changes):
    return {
        "check_id": "line_items", "kind": "rows",
        "selector": {"item_type": ["table", "table_candidate"]},
        "pointer": "/rows", "expected": [["SKU", "Price"], ["A", "12.00"], ["B", "20.00"]],
        "truth_class": "visible_text", "evidence_ref": "synthetic source, full table",
        **changes,
    }


def expectations(*checks, coverage="selected_claims"):
    return Expectations.model_validate({
        "schema_version": "1.0", "source_sha256": SHA, "reviewer": "synthetic-test-author",
        "coverage": coverage, "checks": list(checks),
    })


def evaluate(raw, expected=None, **kwargs):
    return evaluate_response(raw, source_sha256=SHA, expected=expected, **kwargs)


def test_high_confidence_wrong_number_is_an_unflagged_miss():
    result = evaluate(response(item("key_value", "320.00", key="total", confidence=0.999)), expectations(field_check()))
    assert result["routing"]["decision"] == "accept"
    assert result["routing_evaluation"] == "unflagged_error"
    assert result["quality"]["checks"][0]["missing"] == [{"value": "32.00", "count": 1}]


def test_column_swap_preserves_tokens_but_fails_row_relationships():
    rows = [["SKU", "Price"], ["12.00", "A"], ["20.00", "B"]]
    result = evaluate(response(item("table", rows, rows=rows)), expectations(row_check()))
    check = result["quality"]["checks"][0]
    assert check["missing_count"] == 2
    assert check["extra_count"] == 2
    assert result["routing_evaluation"] == "unflagged_error"


def test_rows_keep_order_and_multiplicity():
    expected = row_check()["expected"]
    rows = [expected[0], expected[2], expected[1]]
    result = evaluate(response(item("table", rows, rows=rows)), expectations(row_check()))
    check = result["quality"]["checks"][0]
    assert check["row_order_matches"] is False
    assert check["missing_count"] == check["extra_count"] == 0
    assert check["status"] == "fail"
    rows = [expected[0], expected[1], expected[1]]
    result = evaluate(response(item("table", rows, rows=rows)), expectations(row_check()))
    check = result["quality"]["checks"][0]
    assert (check["missing_count"], check["extra_count"], check["duplicate_extra_count"]) == (1, 1, 1)
    result = evaluate(response(item("table", rows, rows=rows)), expectations(row_check(expected=rows)))
    assert result["quality"]["checks"][0]["status"] == "pass"


def test_missing_and_duplicate_fields_are_distinct_from_null_values():
    missing = evaluate(response(item("key_value", "other", key="different")), expectations(field_check()))
    assert missing["quality"]["checks"][0]["missing_count"] == 1
    duplicate = evaluate(response(item("key_value", "32.00", key="total"), item("key_value", "32.00", key="total")), expectations(field_check()))
    assert duplicate["quality"]["checks"][0]["duplicate_extra_count"] == 1
    null_expected = expectations(field_check(expected=None))
    assert evaluate(response(item("key_value", None, key="total")), null_expected)["quality"]["failed"] == 0
    raw = response(item("key_value", None, key="total"))
    del raw["pages"][0]["items"][0]["value"]
    assert evaluate(raw, null_expected)["quality"]["failed"] == 1


def test_flags_on_correct_checked_content_are_false_positive_candidates():
    result = evaluate(response(item("key_value", "32.00", key="total"), decision="concern"), expectations(field_check(), coverage="complete_for_case"))
    assert result["routing_evaluation"] == "flagged_no_checked_error"
    assert result["quality"]["coverage"] == "complete_for_case"


def test_missing_truth_never_passes_and_absent_sidecar_never_accepts():
    raw = response(item("text", "body"))
    del raw["deterministic_confidence"]
    raw["pages"][0]["items"][0]["parse_concerns"] = ["ocr_text_limited"]
    result = evaluate(raw)
    assert result["quality"]["status"] == "unevaluated"
    assert result["routing_evaluation"] == "unevaluated"
    assert result["routing"]["status"] == "unobserved"
    assert result["routing"]["decision"] is result["routing"]["flagged"] is None
    assert result["routing"]["has_review_signals"] is True


def test_malformed_sidecar_is_invalid_not_accepted():
    raw = response(item("text", "body"))
    raw["deterministic_confidence"]["overall_decision"] = "fallback"
    assert evaluate(raw)["routing"]["status"] == "invalid"


def test_candidate_correction_and_fallback_regression_are_both_reported():
    rows = row_check()["expected"]
    before = response(item("table_candidate", rows, rows=rows), item("key_value", "320", key="total"), decision="fallback")
    after = response(item("table", rows[:1], rows=rows[:1]), item("key_value", "32.00", key="total"))
    truth = expectations(row_check(), field_check())
    pair = compare_responses(evaluate(before, truth), evaluate(after, truth))
    assert pair["corrected"] == ["total"]
    assert pair["harmed"] == ["line_items"]
    assert pair["baseline_decision"] == "fallback"
    assert pair["candidate_decision"] == "accept"
    assert pair["measurement_delta_candidate_minus_baseline"]["cost_usd"] is None


def test_cost_missing_is_null_and_only_measured_latency_is_reported():
    raw = response(item("text", "body"))
    result = evaluate(raw)
    assert result["measurements"]["latency_ms"] == 12
    assert result["measurements"]["cost_usd"] is None
    del raw["processing"]
    before = evaluate(raw)
    assert before["measurements"]["latency_ms"] is None
    after = evaluate(raw, measurements=Measurements(latency_ms=30.0, cost_usd=0.02, method="measured request and invoice"))
    assert compare_responses(before, after)["measurement_delta_candidate_minus_baseline"] == {"latency_ms": None, "cost_usd": None}


def test_evidence_geometry_and_identity_gaps_do_not_claim_value_accuracy():
    raw = response(item("text", "body"), item("text", "other"))
    raw["pages"][0]["items"][0]["bbox"]["width"] = 101
    result = evaluate(raw)
    codes = [gap["code"] for gap in result["evidence"]["gaps"]]
    assert "item_identity_missing_or_duplicate" in codes
    assert "physical_geometry_missing_or_invalid" in codes
    assert result["quality"]["status"] == "unevaluated"
    raw["pages"][0]["unit"] = "logical"
    result = evaluate(raw)
    assert result["evidence"]["counts"]["items_with_logical_coordinates"] == 2


def write_manifest(root: Path):
    (root / "source.txt").write_bytes(SOURCE)
    (root / "response.json").write_text(json.dumps(response(item("key_value", "32.00", key="total"), decision="concern")))
    (root / "expected.json").write_text(expectations(field_check(), coverage="complete_for_case").model_dump_json())
    payload = {"schema_version": "1.0", "cases": [{"case_id": "synthetic", "source": {"path": "source.txt", "sha256": SHA}, "baseline": {"path": "response.json"}, "expected_path": "expected.json"}]}
    path = root / "manifest.json"
    path.write_text(json.dumps(payload))
    return path, payload


def test_cli_report_is_deterministic_and_does_not_write_inputs(tmp_path, capsys):
    path, _ = write_manifest(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert main(["--manifest", str(path), "--workspace", str(tmp_path)]) == 0
    first = capsys.readouterr().out
    assert main(["--manifest", str(path), "--workspace", str(tmp_path)]) == 0
    assert capsys.readouterr().out == first
    report = json.loads(first)
    assert report["summary"]["baseline"]["false_positive_candidates_complete_cases"] == 1
    assert report["summary"]["baseline"]["cost_usd"]["observed_sum"] is None
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("surface", ["source", "response", "expected"])
def test_source_identity_drift_fails_closed(tmp_path, surface):
    path, payload = write_manifest(tmp_path)
    if surface == "source":
        (tmp_path / "source.txt").write_bytes(b"changed source")
    else:
        target = tmp_path / f"{surface}.json"
        raw = json.loads(target.read_text())
        if surface == "response":
            raw["document"]["sha256"] = "0" * 64
        else:
            raw["source_sha256"] = "0" * 64
        target.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="hash|sha256"):
        evaluate_manifest(path, tmp_path)


def test_path_escape_and_duplicate_json_keys_fail_closed(tmp_path):
    path, payload = write_manifest(tmp_path)
    payload["cases"][0]["baseline"]["path"] = "../outside.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="outside workspace"):
        evaluate_manifest(path, tmp_path)
    path.write_text('{"schema_version":"1.0","schema_version":"2.0"}')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        evaluate_manifest(path, tmp_path)


def test_unknown_truth_classes_and_nonfinite_measurements_rejected():
    with pytest.raises(ValueError):
        Check.model_validate(field_check(truth_class="inferred"))
    with pytest.raises(ValueError):
        Measurements(latency_ms=float("nan"), method="invalid")


def test_overflowed_json_number_is_a_structured_input_error(tmp_path, capsys):
    path, _ = write_manifest(tmp_path)
    (tmp_path / "response.json").write_text('{"processing":{"duration_ms":1e999}}')
    assert main(["--manifest", str(path), "--workspace", str(tmp_path)]) == 2
    assert "non-finite JSON number" in json.loads(capsys.readouterr().err)["error"]


def test_partial_coverage_is_not_counted_as_false_positive(tmp_path):
    path, _ = write_manifest(tmp_path)
    (tmp_path / "expected.json").write_text(expectations(field_check()).model_dump_json())
    report = evaluate_manifest(path, tmp_path)
    assert report["summary"]["baseline"]["classification_counts"] == {"flagged_no_checked_error": 1}
    assert report["summary"]["baseline"]["false_positive_candidates_complete_cases"] == 0


def test_invalid_cell_reference_type_is_not_counted_as_evidence():
    rows = [["A", "12.00"]]
    raw = response(item("table", rows, rows=rows, cells=[{"evidence_ids": "not-an-array", "source_object_ids": ["source-1"]}]))
    evidence = evaluate(raw)["evidence"]
    assert evidence["counts"].get("cells_with_evidence_references", 0) == 0
    assert "cell_evidence_reference_missing" in [gap["code"] for gap in evidence["gaps"]]


def test_row_order_uses_exact_json_types_not_python_bool_number_equality():
    rows = [[True], [1]]
    result = evaluate(
        response(item("table", rows, rows=rows)),
        expectations(row_check(expected=[[1], [True]])),
    )
    check = result["quality"]["checks"][0]
    assert check["missing_count"] == check["extra_count"] == 0
    assert check["row_order_matches"] is False
    assert check["status"] == "fail"
