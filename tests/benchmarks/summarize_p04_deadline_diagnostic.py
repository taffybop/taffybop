"""Validate and summarize one immutable P04 deadline diagnostic sweep."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from app.models import ParseResult


EXPECTED_BUDGETS = (5.0, 10.0, 15.0, 30.0)
EXPECTED_CASES = ("clinical-study", "ny-timetable")
DIAGNOSTIC_POLICY = "p04-diagnostic-document-budget-v1"


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_sha256(value: object) -> str:
    return _bytes_sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _one_table(payload: Mapping[str, Any], page_index: int) -> Mapping[str, Any]:
    matches = [
        item
        for page in payload.get("pages") or []
        if isinstance(page, Mapping) and page.get("page_index") == page_index
        for item in page.get("items") or []
        if isinstance(item, Mapping) and item.get("type") == "table"
    ]
    if len(matches) != 1:
        raise ValueError("expected one diagnostic table on the reviewed page")
    return matches[0]


def _reviewed_invariants(case_id: str, payload: Mapping[str, Any]) -> dict[str, bool]:
    if case_id == "clinical-study":
        first = _one_table(payload, 2)
        second = _one_table(payload, 4)
        first_headers = [
            cell
            for cell in first.get("cells") or []
            if isinstance(cell, Mapping)
            and cell.get("row") == 0
            and cell.get("text")
        ]
        sections = {
            str(cell.get("text")): (cell.get("row_span"), cell.get("col_span"))
            for cell in first.get("cells") or []
            if isinstance(cell, Mapping)
            and cell.get("text") in {"M(SD)", "Marital status", "Occupation"}
        }
        group_spans = sorted(
            int(cell["col_span"])
            for cell in second.get("cells") or []
            if isinstance(cell, Mapping)
            and cell.get("row") == 0
            and type(cell.get("col_span")) is int
            and cell["col_span"] > 1
        )
        return {
            "page_2_column_count_is_6": first.get("column_count") == 6,
            "page_2_has_5_first_row_headers": len(first_headers) == 5,
            "page_2_first_row_headers_are_owned": bool(first_headers)
            and all(cell.get("column_header") is True for cell in first_headers),
            "page_2_section_spans_are_1x1": sections
            == {
                "M(SD)": (1, 1),
                "Marital status": (1, 1),
                "Occupation": (1, 1),
            },
            "page_4_column_count_is_9": second.get("column_count") == 9,
            "page_4_group_spans_are_3_and_4": group_spans == [3, 4],
        }
    if case_id == "ny-timetable":
        tables = [_one_table(payload, page) for page in (1, 2, 3)]
        expected_row = [
            "",
            "2:55 3:01",
            "3:05",
            "3:18",
            "3:24",
            "3:30",
            "3:32 3:32 3:38",
            "3:43",
            "3:48",
            "3:51",
            "3:55",
            "3:57",
        ]
        return {
            "one_table_on_each_page": len(tables) == 3,
            "page_3_reviewed_row_is_exact": tables[2]["rows"][28] == expected_row,
            "all_rows_retain_12_columns": all(
                len(row) == 12
                for table in tables
                for row in table.get("rows") or []
            ),
        }
    raise ValueError("unsupported reviewed diagnostic case")


def _render_validation(
    case_dir: Path,
    page_count: int,
    table_count: int,
    table_evidence_count: int,
) -> dict[str, Any]:
    manifest_path = case_dir / "rendered-capture.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("page_count") != page_count:
        raise ValueError("rendered diagnostic page count differs")
    response_bytes = (case_dir / "response.json").read_bytes()
    if manifest.get("source_response_sha256") != _bytes_sha256(response_bytes):
        raise ValueError("rendered diagnostic source response differs")
    rendered_table_count = 0
    for page in manifest.get("pages") or []:
        artifact = case_dir / str(page["artifact"])
        artifact_bytes = artifact.read_bytes()
        if page.get("artifact_sha256") != _bytes_sha256(artifact_bytes):
            raise ValueError("rendered diagnostic artifact hash differs")
        rendered = json.loads(artifact_bytes)
        rendered_table_count += len(
            re.findall(r'<table class="parsed-table">', rendered.get("html") or "")
        )
    return {
        "renderer": manifest.get("renderer"),
        "presentation_view": manifest.get("presentation_view"),
        "page_count": manifest.get("page_count"),
        "public_json_table_count": table_count,
        "rendered_table_count": rendered_table_count,
        "rendered_table_count_matches_table_evidence": (
            rendered_table_count == table_evidence_count
        ),
    }


def _major_timings(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    retained_stages = {
        "pipeline.partitioned_table_repair_words",
        "pipeline.normalize_docling_body",
        "pipeline.shared_page_analysis",
        "pipeline.shared_ir_compatibility_projection",
        "pipeline.terminal_table_authority",
        "pipeline.table_custody_document_segment",
    }
    return [
        {
            key: record.get(key)
            for key in (
                "sequence",
                "stage",
                "operation",
                "status",
                "elapsed_ms",
                "remaining_ms_at_start",
                "error",
            )
            if record.get(key) is not None
        }
        for record in records
        if record.get("stage") in retained_stages
    ]


def summarize(run_root: Path) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    code_identity_sha256: str | None = None
    process_ids: set[int] = set()
    stable_hashes: dict[str, set[str]] = defaultdict(set)

    for budget in EXPECTED_BUDGETS:
        budget_dir = f"budget-{int(budget):03d}"
        for case_id in EXPECTED_CASES:
            case_dir = run_root / "sweep" / budget_dir / case_id
            diagnostic = json.loads(
                (case_dir / "diagnostic.json").read_text(encoding="utf-8")
            )
            if diagnostic.get("requested_document_seconds") != budget:
                raise ValueError("diagnostic budget identity differs")
            if diagnostic.get("classification") != "diagnostic_non_closure":
                raise ValueError("diagnostic classification differs")
            if any(
                diagnostic.get(key) is not expected
                for key, expected in (
                    ("diagnostic_only", True),
                    ("release_eligible", False),
                    ("closure_evidence", False),
                )
            ):
                raise ValueError("diagnostic release guard differs")
            if diagnostic["budget_policy"]["policy_id"] != DIAGNOSTIC_POLICY:
                raise ValueError("diagnostic budget policy differs")
            pid = diagnostic["process_isolation"]["pid"]
            if type(pid) is not int or pid in process_ids:
                raise ValueError("diagnostic pair did not use a fresh process")
            process_ids.add(pid)
            code_sha = _json_sha256(diagnostic["code_identity"])
            if code_identity_sha256 is None:
                code_identity_sha256 = code_sha
            elif code_sha != code_identity_sha256:
                raise ValueError("diagnostic harness code changed during sweep")

            response_bytes = (case_dir / "response.json").read_bytes()
            if DIAGNOSTIC_POLICY.encode("utf-8") in response_bytes:
                raise ValueError("diagnostic policy leaked into public JSON")
            validated = ParseResult.model_validate_json(response_bytes)
            payload = validated.model_dump(mode="json", exclude_none=True)
            markdown_bytes = (case_dir / "response.md").read_bytes()
            canonical_bytes = (case_dir / "canonical-full.md").read_bytes()
            result = diagnostic["result"]
            if _bytes_sha256(response_bytes) != result["response_json_sha256"]:
                raise ValueError("diagnostic response hash differs")
            if markdown_bytes != canonical_bytes:
                raise ValueError("diagnostic raw/canonical Markdown differs")
            if _bytes_sha256(markdown_bytes) != result["response_markdown_sha256"]:
                raise ValueError("diagnostic Markdown hash differs")
            if not result["parse_result_valid"] or not result[
                "context_free_json_round_trip_exact"
            ]:
                raise ValueError("diagnostic public model validation differs")
            if not result["all_table_content_matches_predecessor"]:
                raise ValueError("diagnostic table content drifted from predecessor")
            if result["canonical_source_custody_present"]:
                if result["table_evidence_count"] < 1:
                    raise ValueError("diagnostic custody has no table evidence")
            elif result["table_evidence_count"] != 0:
                raise ValueError("diagnostic table evidence lacks document custody")

            invariants = _reviewed_invariants(case_id, payload)
            if not all(invariants.values()):
                raise ValueError("reviewed diagnostic content invariant differs")
            render = _render_validation(
                case_dir,
                result["page_count"],
                result["table_count"],
                result["table_evidence_count"],
            )
            if not render["rendered_table_count_matches_table_evidence"]:
                raise ValueError("diagnostic rendered table authority differs")
            stable_hashes[case_id].add(result["stable_payload_sha256"])
            observations.append(
                {
                    "case_id": case_id,
                    "budget_seconds": budget,
                    "pid": pid,
                    "wall_ms": diagnostic["wall_ms"],
                    "terminal": diagnostic["terminal"],
                    "table_count": result["table_count"],
                    "table_evidence_count": result["table_evidence_count"],
                    "sidecar_statuses": [
                        table["table_evidence"]["status"]
                        for table in result["tables"]
                        if table["table_evidence"] is not None
                    ],
                    "canonical_source_custody_present": result[
                        "canonical_source_custody_present"
                    ],
                    "all_table_content_matches_predecessor": result[
                        "all_table_content_matches_predecessor"
                    ],
                    "all_table_projections_match_predecessor": result[
                        "all_table_projections_match_predecessor"
                    ],
                    "raw_canonical_markdown_byte_identical": result[
                        "raw_canonical_markdown_byte_identical"
                    ],
                    "stable_payload_sha256": result["stable_payload_sha256"],
                    "reviewed_invariants": invariants,
                    "render": render,
                    "major_stage_timings": _major_timings(
                        diagnostic["stage_timings"]
                    ),
                }
            )

    by_case: dict[str, dict[str, Any]] = {}
    for case_id in EXPECTED_CASES:
        selected = [row for row in observations if row["case_id"] == case_id]
        full_successes = [
            row["budget_seconds"]
            for row in selected
            if row["canonical_source_custody_present"]
            and row["table_evidence_count"] == row["table_count"]
        ]
        custody_successes = [
            row["budget_seconds"]
            for row in selected
            if row["canonical_source_custody_present"]
        ]
        by_case[case_id] = {
            "first_observed_custody_budget_seconds": (
                min(custody_successes) if custody_successes else None
            ),
            "first_observed_full_table_evidence_budget_seconds": (
                min(full_successes) if full_successes else None
            ),
            "stable_payload_variant_count": len(stable_hashes[case_id]),
            "all_reviewed_content_invariants_pass": all(
                all(row["reviewed_invariants"].values()) for row in selected
            ),
        }

    summary = {
        "schema_version": "p04-document-budget-diagnostic-summary-v1",
        "classification": "diagnostic_non_closure",
        "diagnostic_only": True,
        "release_eligible": False,
        "closure_evidence": False,
        "production_document_seconds": 5.0,
        "page_seconds": 0.5,
        "budgets_seconds": list(EXPECTED_BUDGETS),
        "case_ids": list(EXPECTED_CASES),
        "fresh_process_count": len(process_ids),
        "code_identity_sha256": code_identity_sha256,
        "observations": observations,
        "case_conclusions": by_case,
        "interpretation": {
            "clinical_study": (
                "Increasing the document clock does not commit Clinical custody. "
                "Every lane reaches the same terminal visual-overlay canonical-splice "
                "integrity rejection and restores exact table content."
            ),
            "ny_timetable": (
                "The 5-second lane times out in terminal custody. Longer document "
                "lanes can commit custody, but the unchanged 500 ms page clock can "
                "still withhold one or all table sidecars near its boundary."
            ),
            "closure": (
                "No elevated-budget artifact is release or FFD-011 closure evidence. "
                "The experiment identifies separate P04 integrity and performance/page-"
                "budget work; production remains at 5.0 seconds per document and "
                "0.5 seconds per page."
            ),
        },
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    return summary


def _report(summary: Mapping[str, Any]) -> str:
    rows = []
    for observation in summary["observations"]:
        rows.append(
            "| {case_id} | {budget_seconds:g} | {outcome} | {evidence}/{tables} | "
            "{custody} | {content} |".format(
                case_id=observation["case_id"],
                budget_seconds=observation["budget_seconds"],
                outcome=observation["terminal"]["outcome"],
                evidence=observation["table_evidence_count"],
                tables=observation["table_count"],
                custody="yes"
                if observation["canonical_source_custody_present"]
                else "no",
                content="pass"
                if observation["all_table_content_matches_predecessor"]
                else "FAIL",
            )
        )
    interpretation = summary["interpretation"]
    return "\n".join(
        (
            "# P04 document-deadline diagnostic",
            "",
            "**Classification:** diagnostic only; not release or FFD-011 closure evidence.",
            "",
            "Production remained unchanged at 5.0 seconds/document and "
            "0.5 seconds/page. Each row ran in a fresh process; only the test harness "
            "temporarily widened the cumulative document clock.",
            "",
            "| Case | Document budget (s) | Terminal outcome | Table sidecars | Custody | Reviewed content |",
            "| --- | ---: | --- | ---: | --- | --- |",
            *rows,
            "",
            "## Findings",
            "",
            f"- Clinical: {interpretation['clinical_study']}",
            f"- NY timetable: {interpretation['ny_timetable']}",
            f"- Closure: {interpretation['closure']}",
            "",
        )
    )


def _artifact_manifest(run_root: Path) -> dict[str, Any]:
    excluded = {"artifact-manifest.json"}
    artifacts = []
    for path in sorted(value for value in run_root.rglob("*") if value.is_file()):
        relative = str(path.relative_to(run_root))
        if relative in excluded:
            continue
        value = path.read_bytes()
        artifacts.append(
            {
                "path": relative,
                "size_bytes": len(value),
                "sha256": _bytes_sha256(value),
            }
        )
    return {
        "schema_version": "p04-document-budget-diagnostic-artifact-manifest-v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    arguments = parser.parse_args(argv)
    run_root = arguments.run_root.resolve()
    summary = summarize(run_root)
    _write_json(run_root / "sweep-summary.json", summary)
    (run_root / "report.md").write_text(_report(summary), encoding="utf-8")
    _write_json(
        run_root / "attempt-status.json",
        {
            "schema_version": "p04-document-budget-diagnostic-attempt-status-v1",
            "status": "diagnostic_complete_non_closure",
            "diagnostic_only": True,
            "release_eligible": False,
            "closure_evidence": False,
            "summary": "sweep-summary.json",
            "report": "report.md",
        },
    )
    _write_json(run_root / "artifact-manifest.json", _artifact_manifest(run_root))
    print(json.dumps(summary["case_conclusions"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
