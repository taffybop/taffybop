"""Unit checks for the out-of-band P04 deadline diagnostic runner."""

from __future__ import annotations

from copy import deepcopy

from tests.benchmarks.p04_deadline_diagnostic import (
    _state_outcome,
    _table_summaries,
)


def _payload() -> dict[str, object]:
    table = {
        "id": "p1-i2",
        "type": "table",
        "reading_order": 1,
        "value": [["A", "B"]],
        "rows": [["A", "B"]],
        "cells": [
            {"id": "c1", "row": 0, "col": 0, "text": "A"},
            {"id": "c2", "row": 0, "col": 1, "text": "B"},
        ],
        "row_count": 1,
        "column_count": 2,
        "html": "<table><tr><td>A</td><td>B</td></tr></table>",
        "md": "| A | B |",
    }
    return {
        "pages": [
            {
                "page_index": 1,
                "items": [
                    {"id": "p1-i1", "type": "text", "value": "Intro"},
                    table,
                ],
            }
        ]
    }


def test_table_summary_separates_sidecar_and_order_drift_from_content() -> None:
    predecessor = _payload()
    current = deepcopy(predecessor)
    table = current["pages"][0]["items"][1]  # type: ignore[index]
    table["reading_order"] = 0
    table["table_evidence"] = {
        "policy_id": "p04-table-evidence-v1",
        "version": "1.1",
        "status": "unresolved",
        "concerns": ["table_source_cell_grid_unresolved"],
        "source_objects": [{"id": "source"}],
        "evidence": [{"id": "evidence"}],
        "gate": None,
    }

    summaries = _table_summaries(current, predecessor)
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["predecessor_projection_exact"] is False
    assert summary["predecessor_content_exact"] is True
    assert summary["table_evidence"] == {
        "policy_id": "p04-table-evidence-v1",
        "version": "1.1",
        "status": "unresolved",
        "concerns": ["table_source_cell_grid_unresolved"],
        "source_object_count": 1,
        "evidence_count": 1,
        "gate_outcome": None,
    }


def test_terminal_outcome_uses_private_precleanup_state_not_public_guessing() -> None:
    timeout = _state_outcome(
        [
            {
                "stage": "pipeline.table_budget_pre_cleanup_state",
                "state": {"timed_out": True},
            },
            {
                "stage": "pipeline.table_custody_document_segment",
                "status": "error:OpaqueGroupCustodyTimeoutError",
                "error": "deadline exceeded",
            },
        ],
        custody_present=False,
    )
    assert timeout["outcome"] == "rolled_back_timeout"
    assert timeout["errors"] == [
        {
            "stage": "pipeline.table_custody_document_segment",
            "status": "error:OpaqueGroupCustodyTimeoutError",
            "error": "deadline exceeded",
        }
    ]

    integrity = _state_outcome(
        [
            {
                "stage": "pipeline.table_budget_pre_cleanup_state",
                "state": {"custody_rejected": True},
            }
        ],
        custody_present=False,
    )
    assert integrity["outcome"] == "rolled_back_integrity_or_resource"

    committed = _state_outcome([], custody_present=True)
    assert committed["outcome"] == "committed_with_custody"

