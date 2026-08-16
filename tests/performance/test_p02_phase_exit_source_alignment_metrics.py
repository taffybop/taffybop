from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.source_text_alignment_metrics import (
    AFFECTED_CASE_IDS,
    CORE_PHASE_EXIT_REGRESSION,
    HEALTHY_CASE_IDS,
    REQUIRED_OFFLINE_ENVIRONMENT,
    _canonical_text,
    _canonical_markdown,
    _count_exact_targets,
    _distribution,
    _evaluate_case_targets,
    _input_paths,
    _load_full_results,
    _masked_full_result,
    _nearest_rank,
    _phase02_settings,
    _predecessor_projection,
    _public_table_rows,
    _settings_snapshot,
    _sha256_json,
    _validate_approved_owner_drift,
    _validate_retained_collection_request,
    _validate_worker_record,
    _with_canonical_presentation,
)


WORKSPACE = Path(__file__).resolve().parents[2]
FAKE_SOURCE_SHA256 = hashlib.sha256(b"metric-adversarial-source").hexdigest()


def _minimal_payload() -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "document": {
            "filename": "adversarial.pdf",
            "mime_type": "application/pdf",
            "sha256": FAKE_SOURCE_SHA256,
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "warnings": [],
                "items": [
                    {
                        "id": "p1-i1",
                        "type": "table",
                        "reading_order": 0,
                        "source": "native",
                        "value": [
                            ["CIO", "Chief Information Officer"],
                            ["FERS", "Federal Employees Retirement System"],
                        ],
                        "rows": [
                            ["CIO", "Chief Information Officer"],
                            ["FERS", "Federal Employees Retirement System"],
                        ],
                        "cells": [
                            {"row": 0, "column": 0, "text": "CIO"},
                            {
                                "row": 0,
                                "column": 1,
                                "text": "Chief Information Officer",
                            },
                            {"row": 1, "column": 0, "text": "FERS"},
                            {
                                "row": 1,
                                "column": 1,
                                "text": "Federal Employees Retirement System",
                            },
                        ],
                        "html": (
                            "<table><tr><td>CIO</td>"
                            "<td>Chief Information Officer</td></tr>"
                            "<tr><td>FERS</td>"
                            "<td>Federal Employees Retirement System</td>"
                            "</tr></table>"
                        ),
                        "md": (
                            "<table><tr><td>CIO</td>"
                            "<td>Chief Information Officer</td></tr>"
                            "<tr><td>FERS</td>"
                            "<td>Federal Employees Retirement System</td>"
                            "</tr></table>"
                        ),
                        "csv": (
                            "CIO,Chief Information Officer\n"
                            "FERS,Federal Employees Retirement System"
                        ),
                        "row_count": 2,
                        "column_count": 2,
                    },
                    {
                        "id": "p1-i2",
                        "type": "text",
                        "reading_order": 1,
                        "source": "ocr",
                        "value": "ClO ordinary paragraph",
                        "source_alignment_suppressed": True,
                    },
                ],
            }
        ],
        "processing": {
            "engine": "test",
            "ocr_engine": "test",
            "ocr_languages": ["eng"],
            "duration_ms": 0,
        },
        "warnings": [],
    }
    return _with_canonical_presentation(payload, rebuild=True)


def _page_with_item(
    item_id: str,
    value: str,
    *,
    item_type: str = "text",
) -> list[dict[str, Any]]:
    return [
        {
            "page_index": 1,
            "page_number": 1,
            "page_label": "1",
            "page_width": 612.0,
            "page_height": 792.0,
            "unit": "pt",
            "success": True,
            "warnings": [],
            "items": [
                {
                    "id": item_id,
                    "type": item_type,
                    "reading_order": 0,
                    "source": "native",
                    "value": value,
                    "bbox": {
                        "x": 10.0,
                        "y": 10.0,
                        "width": 100.0,
                        "height": 10.0,
                        "unit": "pt",
                    },
                }
            ],
        }
    ]


def test_source_alignment_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    assert _distribution(values) == {
        "p50": 3.0,
        "p95": 5.0,
        "max": 5.0,
    }
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
    with pytest.raises(ValueError, match="percentile"):
        _nearest_rank(values, 0.0)
    with pytest.raises(ValueError, match="finite"):
        _nearest_rank([math.inf], 0.95)
    with pytest.raises(ValueError, match="finite"):
        _nearest_rank([-0.01], 0.95)


def test_source_alignment_target_counter_is_literal_and_exact() -> None:
    text = (
        "Look-Back Date\n"
        "Look-Back Date\n"
        "CIO Chief Information Officer\n"
        "Freie Universität Berlin\n"
        "$ $"
    )
    rows = _count_exact_targets(
        text,
        {
            "settlement": ("Look-Back Date", 2),
            "forbid_fused": ("LookBack Date", 0),
            "postal_cio": ("CIO Chief Information Officer", 1),
            "clinical_nfc": ("Freie Universität Berlin", 1),
            "currency": ("$", 2),
            "case_sensitive_negative": ("look-back date", 0),
        },
    )

    assert all(row["passes"] for row in rows.values())
    assert rows["settlement"]["observed_count"] == 2
    assert rows["currency"]["observed_count"] == 2

    mismatch = _count_exact_targets(
        "LookBack Date",
        {"forbidden": ("LookBack Date", 0)},
    )
    assert mismatch["forbidden"]["observed_count"] == 1
    assert mismatch["forbidden"]["passes"] is False

    with pytest.raises(ValueError, match="non-empty"):
        _count_exact_targets("x", {"": ("x", 1)})
    with pytest.raises(ValueError, match="non-negative"):
        _count_exact_targets("x", {"x": ("x", -1)})


def test_all_case_target_results_are_json_round_trip_stable() -> None:
    payload = _minimal_payload()
    for page_index in (2, 3, 4):
        page = deepcopy(payload["pages"][0])
        page["page_index"] = page_index
        page["page_number"] = page_index
        page["page_label"] = str(page_index)
        page["items"] = []
        payload["pages"].append(page)
    payload = _with_canonical_presentation(payload, rebuild=True)
    case_ids = sorted(AFFECTED_CASE_IDS | set(HEALTHY_CASE_IDS))
    for case_id in case_ids:
        target = _evaluate_case_targets(
            case_id,
            payload,
            {"selections": [], "concerns": []},
        )
        assert json.loads(
            json.dumps(target, ensure_ascii=False)
        ) == target


def test_target_evaluation_uses_real_canonical_and_markdown_table_surfaces() -> (
    None
):
    payload = _minimal_payload()
    text = _canonical_text(payload)
    markdown = _canonical_markdown(payload)

    assert _public_table_rows(payload).count(
        ("CIO", "Chief Information Officer")
    ) == 1
    assert text.count("CIO\tChief Information Officer") == 1
    assert text.count("FERS\tFederal Employees Retirement System") == 1
    assert markdown.count("<td>CIO</td>") == 1
    assert markdown.count("<td>Chief Information Officer</td>") == 1
    # A marker in test data has no magic filtering semantics.  The public
    # builders still emit it; no test helper skips the non-empty value.
    assert "ClO ordinary paragraph" in text


def test_approved_owner_gate_rejects_unrelated_and_non_content_drift() -> None:
    before = _page_with_item("p1-i1", "original")
    unrelated = deepcopy(before)
    unrelated[0]["items"][0]["value"] = "changed"
    with pytest.raises(RuntimeError, match="unrelated public owner"):
        _validate_approved_owner_drift(
            "finance-10k",
            before,
            unrelated,
            {
                "selected_count": 1,
                "selections": [
                    {
                        "owner_id": "p1-i1",
                        "owner_type": "text",
                        "page_index": 1,
                    }
                ],
            },
        )

    purchase_before = _page_with_item("p1-i2", "original")
    purchase_after = deepcopy(purchase_before)
    purchase_after[0]["items"][0]["bbox"]["x"] = 11.0
    with pytest.raises(RuntimeError, match="non-content fields"):
        _validate_approved_owner_drift(
            "purchase-agreement",
            purchase_before,
            purchase_after,
            {
                "selected_count": 1,
                "selections": [
                    {
                        "owner_id": "p1-i2",
                        "owner_type": "text",
                        "page_index": 1,
                    }
                ],
            },
        )


def test_approved_table_owner_cannot_hide_unreviewed_cell_drift() -> None:
    before = _page_with_item("p4-i2", "", item_type="table")
    table = before[0]["items"][0]
    table.update(
        {
            "value": [["original"]],
            "rows": [["original"]],
            "cells": [{"row": 0, "column": 0, "text": "original"}],
            "html": "<table><tr><td>original</td></tr></table>",
            "md": "<table><tr><td>original</td></tr></table>",
            "csv": "original",
        }
    )
    after = deepcopy(before)
    after_table = after[0]["items"][0]
    after_table["value"][0][0] = "changed"
    after_table["rows"][0][0] = "changed"
    after_table["cells"][0]["text"] = "changed"
    after_table["html"] = "<table><tr><td>changed</td></tr></table>"
    after_table["md"] = "<table><tr><td>changed</td></tr></table>"
    after_table["csv"] = "changed"

    with pytest.raises(RuntimeError, match="changed cells"):
        _validate_approved_owner_drift(
            "clinical-study",
            before,
            after,
            {
                "selected_count": 1,
                "selections": [
                    {
                        "owner_id": "p4-i2:r0:c0",
                        "owner_type": "table_cell",
                        "page_index": 1,
                    }
                ],
            },
        )


def test_custody_binds_all_app_python_core_regression_and_pyproject() -> None:
    inputs = set(_input_paths(WORKSPACE))
    app_modules = {
        path.relative_to(WORKSPACE).as_posix()
        for path in (WORKSPACE / "app").rglob("*.py")
        if path.is_file()
    }

    assert app_modules
    assert app_modules <= inputs
    assert CORE_PHASE_EXIT_REGRESSION in inputs
    assert "pyproject.toml" in inputs


def test_retained_collection_requires_exact_protocol_and_full_pairs(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="all 15"):
        _validate_retained_collection_request(
            output=tmp_path / "retained.json",
            full_results=None,
            warmups=2,
            samples=10,
        )
    with pytest.raises(ValueError, match="exactly 2 warmups and 10 samples"):
        _validate_retained_collection_request(
            output=tmp_path / "retained.json",
            full_results=tmp_path,
            warmups=1,
            samples=10,
        )
    with pytest.raises(RuntimeError, match="enabled workers for all 15"):
        _load_full_results(WORKSPACE, tmp_path)


def _valid_predecessor_worker() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    payload = _minimal_payload()
    # Suppression markers are deliberately adversarial in the public-surface
    # test, but a worker record must contain only ordinary public state.
    payload["pages"][0]["items"][1].pop(
        "source_alignment_suppressed", None
    )
    payload = _with_canonical_presentation(payload, rebuild=True)
    markdown = _canonical_markdown(payload)
    binding = {
        "source": {
            "path": "benchmark-expertmodeldata/finance-10k.pdf",
            "sha256": FAKE_SOURCE_SHA256,
            "size_bytes": 123,
        },
        "retained_output": {
            "path": "retained.json",
            "sha256": "0" * 64,
            "size_bytes": 1,
        },
        "registered_page_count": 1,
    }
    run_inputs = {"pyproject.toml": {"sha256": "1" * 64, "size_bytes": 1}}
    target_results = {
        "applicable": False,
        "passes": True,
        "reason": "predecessor_worker_not_target_scored",
    }
    record = {
        "schema_version": "1.0",
        "record_kind": "p02_source_text_alignment_full_parse_worker",
        "case_id": "finance-10k",
        "variant": "predecessor",
        "source": binding["source"],
        "settings": _settings_snapshot(
            _phase02_settings(source_alignment_enabled=False)
        ),
        "run_inputs": run_inputs,
        "pre_post_input_identity_match": True,
        "pre_post_source_identity_match": True,
        "offline_environment": REQUIRED_OFFLINE_ENVIRONMENT,
        "latency_ms": 1.0,
        "peak_rss_increment_bytes": 0,
        "semantic_result_sha256": _sha256_json(
            _masked_full_result(payload)
        ),
        "predecessor_projection_sha256": _sha256_json(
            _predecessor_projection(payload)
        ),
        "canonical_text_sha256": hashlib.sha256(
            _canonical_text(payload).encode("utf-8")
        ).hexdigest(),
        "markdown_sha256": hashlib.sha256(
            markdown.encode("utf-8")
        ).hexdigest(),
        "summary": {},
        "target_results": target_results,
        "hosted_model_request_count": 0,
        "hosted_model_token_count": 0,
        "hosted_model_cost_usd": 0.0,
        "result": payload,
        "markdown": markdown,
    }
    return record, binding, run_inputs


@pytest.mark.parametrize(
    ("field_name", "tampered_value"),
    (
        ("semantic_result_sha256", "0" * 64),
        ("predecessor_projection_sha256", "0" * 64),
        ("canonical_text_sha256", "0" * 64),
        ("markdown_sha256", "0" * 64),
        ("markdown", "forged\n"),
        ("summary", {"selected_count": 0, "selections": []}),
        ("target_results", {"applicable": False, "passes": False}),
        ("offline_environment", {"HF_HUB_OFFLINE": "0"}),
        ("settings", {"text_integrity_source_alignment_enabled": False}),
    ),
)
def test_worker_verifier_recomputes_and_rejects_declared_evidence(
    field_name: str,
    tampered_value: Any,
) -> None:
    record, binding, run_inputs = _valid_predecessor_worker()
    _validate_worker_record(WORKSPACE, record, binding, run_inputs)

    record[field_name] = tampered_value
    with pytest.raises(RuntimeError):
        _validate_worker_record(WORKSPACE, record, binding, run_inputs)


def test_healthy_component_scope_is_all_non_affected_cases() -> None:
    assert len(HEALTHY_CASE_IDS) == 10
    assert set(HEALTHY_CASE_IDS).isdisjoint(AFFECTED_CASE_IDS)
    assert set(HEALTHY_CASE_IDS) | set(AFFECTED_CASE_IDS) == {
        "catastrophe-recap",
        "clean-energy",
        "clinical-study",
        "component-datasheet",
        "egov-survey",
        "esg-metrics",
        "finance-10k",
        "health-report",
        "insurance-acord",
        "manufacturing-report",
        "ny-timetable",
        "postal-10k",
        "purchase-agreement",
        "settlement-agreement",
        "uber-earnings",
    }
