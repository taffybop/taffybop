"""Run one isolated, non-closure P04 document-budget diagnostic.

Invoke this module once per ``(source, budget)`` pair.  The caller is expected
to launch a fresh Python process for every pair so parser caches and patched
module globals cannot cross-contaminate observations.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any, Mapping, Sequence

import psutil

from app.config import Settings
from app.models import ParseResult
from app.services.pipeline import parse_document
from app.services.serializer import to_markdown
from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_CONFIGURATION,
    PREDECESSOR_OUTPUT_ROOT,
)
from tests.fixtures.phase_04.tables.diagnostic_budget import (
    DIAGNOSTIC_CLASSIFICATION,
    DIAGNOSTIC_MAX_DOCUMENT_SECONDS,
    PRODUCTION_DOCUMENT_SECONDS,
    capture_p04_diagnostic_timings,
    diagnostic_table_document_budget,
)
from tests.fixtures.phase_04.tables.oracle import P04_US01_REAL_ORACLE


WORKSPACE = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "p04-document-budget-diagnostic-run-v1"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, value: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def _source(case_id: str) -> Any:
    matches = [
        source
        for source in P04_US01_REAL_ORACLE.sources
        if source.case_id == case_id
    ]
    if len(matches) != 1:
        raise ValueError("case must identify one reviewed P04 source")
    return matches[0]


def _tables(payload: Mapping[str, Any]) -> list[tuple[int, int, Mapping[str, Any]]]:
    tables: list[tuple[int, int, Mapping[str, Any]]] = []
    for page in payload.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_index = page.get("page_index")
        if type(page_index) is not int:
            continue
        ordinal = 0
        for item in page.get("items") or []:
            if isinstance(item, Mapping) and item.get("type") == "table":
                tables.append((page_index, ordinal, item))
                ordinal += 1
    return tables


def _table_projection(table: Mapping[str, Any]) -> dict[str, Any]:
    projection = deepcopy(dict(table))
    projection.pop("table_evidence", None)
    return projection


def _stable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = json.loads(json.dumps(payload, ensure_ascii=False))
    processing = stable.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
        for summary_name in ("form_semantics", "outline_structure"):
            summary = processing.get(summary_name)
            if isinstance(summary, dict):
                for key in ("extraction_ms", "projection_ms", "total_ms"):
                    summary.pop(key, None)
    return stable


def _sidecar_summary(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    gate = value.get("gate")
    return {
        "policy_id": value.get("policy_id"),
        "version": value.get("version"),
        "status": value.get("status"),
        "concerns": list(value.get("concerns") or []),
        "source_object_count": len(value.get("source_objects") or []),
        "evidence_count": len(value.get("evidence") or []),
        "gate_outcome": gate.get("outcome") if isinstance(gate, Mapping) else None,
    }


def _table_summaries(
    payload: Mapping[str, Any],
    predecessor: Mapping[str, Any],
) -> list[dict[str, Any]]:
    current = _tables(payload)
    frozen = _tables(predecessor)
    frozen_by_key = {(page, ordinal): table for page, ordinal, table in frozen}
    summaries: list[dict[str, Any]] = []
    for page, ordinal, table in current:
        previous = frozen_by_key.get((page, ordinal))
        projection = _table_projection(table)
        previous_projection = (
            _table_projection(previous) if isinstance(previous, Mapping) else None
        )
        content_keys = (
            "value",
            "rows",
            "cells",
            "row_count",
            "column_count",
            "html",
            "md",
        )
        content_projection = {key: table.get(key) for key in content_keys}
        previous_content_projection = (
            {key: previous.get(key) for key in content_keys}
            if isinstance(previous, Mapping)
            else None
        )
        summaries.append(
            {
                "page_index": page,
                "table_ordinal": ordinal,
                "item_id": table.get("id"),
                "reading_order": table.get("reading_order"),
                "row_count": table.get("row_count"),
                "column_count": table.get("column_count"),
                "cell_count": len(table.get("cells") or []),
                "rows_sha256": _sha256_json(table.get("rows") or []),
                "cells_sha256": _sha256_json(table.get("cells") or []),
                "markdown_sha256": _sha256_bytes(
                    str(table.get("md") or "").encode("utf-8")
                ),
                "html_sha256": _sha256_bytes(
                    str(table.get("html") or "").encode("utf-8")
                ),
                "projection_sha256": _sha256_json(projection),
                "predecessor_projection_sha256": (
                    _sha256_json(previous_projection)
                    if previous_projection is not None
                    else None
                ),
                "predecessor_projection_exact": (
                    projection == previous_projection
                    if previous_projection is not None
                    else False
                ),
                "predecessor_content_exact": (
                    content_projection == previous_content_projection
                    if previous_content_projection is not None
                    else False
                ),
                "table_evidence": _sidecar_summary(table.get("table_evidence")),
            }
        )
    return summaries


def _state_outcome(
    records: Sequence[Mapping[str, object]],
    *,
    custody_present: bool,
) -> dict[str, object]:
    snapshots = [
        record.get("state")
        for record in records
        if record.get("stage") == "pipeline.table_budget_pre_cleanup_state"
        and isinstance(record.get("state"), Mapping)
    ]
    state = dict(snapshots[-1]) if snapshots else {}
    if state.get("timed_out") is True:
        outcome = "rolled_back_timeout"
    elif state.get("custody_rejected") is True:
        outcome = "rolled_back_integrity_or_resource"
    elif state.get("span_fidelity_disabled") is True:
        outcome = "rolled_back_span_fidelity_disabled"
    elif custody_present:
        outcome = "committed_with_custody"
    else:
        outcome = "completed_without_custody_or_state"
    errors = [
        {
            "stage": record.get("stage"),
            "status": record.get("status"),
            "error": record.get("error"),
        }
        for record in records
        if str(record.get("status") or "").startswith("error:")
    ]
    return {"outcome": outcome, "pre_cleanup_state": state, "errors": errors}


def _code_identity(paths: Sequence[Path]) -> list[dict[str, object]]:
    identities = []
    for path in paths:
        value = path.read_bytes()
        identities.append(
            {
                "path": str(path.relative_to(WORKSPACE)),
                "size_bytes": len(value),
                "sha256": _sha256_bytes(value),
            }
        )
    return identities


def run(case_id: str, seconds: float, output_dir: Path) -> dict[str, Any]:
    source = _source(case_id)
    source_path = WORKSPACE / source.path
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != source.size_bytes:
        raise ValueError("reviewed source size differs")
    source_sha256 = _sha256_bytes(source_bytes)
    if source_sha256 != source.sha256:
        raise ValueError("reviewed source hash differs")

    predecessor_path = WORKSPACE / PREDECESSOR_OUTPUT_ROOT / case_id / "our-output.json"
    predecessor = json.loads(predecessor_path.read_text(encoding="utf-8"))
    if output_dir.exists():
        raise FileExistsError("diagnostic output directory already exists")
    output_dir.mkdir(parents=True)

    process = psutil.Process()
    started_at = _utc_now()
    started = time.perf_counter()
    rss_before = process.memory_info().rss
    hwm_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    settings = Settings(
        **PREDECESSOR_CONFIGURATION,
        table_span_fidelity_enabled=True,
    )

    code_identity = _code_identity(
        (
            WORKSPACE / "app/services/pipeline.py",
            WORKSPACE / "app/services/table_semantics.py",
            WORKSPACE / "app/services/opaque_group_custody.py",
            WORKSPACE / "app/services/ir.py",
            WORKSPACE / "app/services/presentation.py",
            WORKSPACE / "app/models.py",
            WORKSPACE / "app/config.py",
            WORKSPACE / "tests/fixtures/phase_04/tables/diagnostic_budget.py",
            Path(__file__).resolve(),
        )
    )
    command = " ".join(
        (
            ".venv/bin/python",
            "-m",
            "tests.benchmarks.p04_deadline_diagnostic",
            "--case",
            case_id,
            "--budget-seconds",
            str(seconds),
            "--output-dir",
            str(output_dir),
        )
    )
    activation_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "diagnostic_only": True,
        "release_eligible": False,
        "closure_evidence": False,
        "source": {
            "case_id": case_id,
            "path": source.path,
            "size_bytes": len(source_bytes),
            "sha256": source_sha256,
            "page_count": source.page_count,
        },
        "requested_document_seconds": seconds,
        "production_document_seconds": PRODUCTION_DOCUMENT_SECONDS,
        "page_seconds": 0.5,
        "hard_max_document_seconds": DIAGNOSTIC_MAX_DOCUMENT_SECONDS,
        "public_request_control": False,
        "process_isolation": {
            "pid": process.pid,
            "single_case_budget_pair": True,
            "parser_cache_shared_across_pairs": False,
        },
        "settings": {
            "table_span_fidelity_enabled": True,
            "text_integrity_source_alignment_enabled": (
                settings.text_integrity_source_alignment_enabled
            ),
            "predecessor_configuration": dict(PREDECESSOR_CONFIGURATION),
        },
        "code_identity": code_identity,
        "started_at_utc": started_at,
        "command": command,
    }
    _write_json(output_dir / "activation.json", activation_record)
    _atomic_write(output_dir / "command.txt", f"{command}\n".encode("utf-8"))

    timing_records: list[dict[str, object]] = []
    try:
        with diagnostic_table_document_budget(seconds) as budget_policy:
            with capture_p04_diagnostic_timings() as timing_records:
                result = parse_document(source_bytes, source_path.name, settings)
        payload = result.model_dump(mode="json", exclude_none=True)
        response_bytes = (
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        independently_validated = ParseResult.model_validate_json(response_bytes)
        round_trip = independently_validated.model_dump(
            mode="json", exclude_none=True
        )
        markdown = to_markdown(independently_validated)
        canonical_markdown = str(
            ((payload.get("canonical_presentation") or {}).get("full") or {}).get(
                "markdown"
            )
            or ""
        )
        _atomic_write(output_dir / "response.json", response_bytes)
        _atomic_write(output_dir / "response.md", markdown.encode("utf-8"))
        _atomic_write(
            output_dir / "canonical-full.md",
            canonical_markdown.encode("utf-8"),
        )

        table_summaries = _table_summaries(payload, predecessor)
        custody = payload.get("canonical_source_custody")
        custody_present = isinstance(custody, Mapping)
        stable_payload_sha256 = _sha256_json(_stable_payload(payload))
        result_summary = {
            "parse_result_valid": True,
            "context_free_json_round_trip_exact": round_trip == payload,
            "response_json_sha256": _sha256_bytes(response_bytes),
            "response_markdown_sha256": _sha256_bytes(markdown.encode("utf-8")),
            "canonical_markdown_sha256": _sha256_bytes(
                canonical_markdown.encode("utf-8")
            ),
            "raw_canonical_markdown_byte_identical": markdown == canonical_markdown,
            "stable_payload_sha256": stable_payload_sha256,
            "warnings": list(payload.get("warnings") or []),
            "page_count": len(payload.get("pages") or []),
            "table_count": len(table_summaries),
            "predecessor_table_count": len(_tables(predecessor)),
            "all_table_projections_match_predecessor": (
                len(table_summaries) == len(_tables(predecessor))
                and all(
                    summary["predecessor_projection_exact"]
                    for summary in table_summaries
                )
            ),
            "all_table_content_matches_predecessor": (
                len(table_summaries) == len(_tables(predecessor))
                and all(
                    summary["predecessor_content_exact"]
                    for summary in table_summaries
                )
            ),
            "table_evidence_count": sum(
                summary["table_evidence"] is not None
                for summary in table_summaries
            ),
            "canonical_source_custody_present": custody_present,
            "canonical_source_custody_sha256": (
                _sha256_json(custody) if custody_present else None
            ),
            "tables": table_summaries,
        }
        completed_at = _utc_now()
        wall_ms = max((time.perf_counter() - started) * 1000.0, 0.0)
        diagnostic = {
            **activation_record,
            "budget_policy": budget_policy,
            "completed_at_utc": completed_at,
            "wall_ms": wall_ms,
            "memory": {
                "rss_before_bytes": rss_before,
                "rss_after_bytes": process.memory_info().rss,
                "ru_maxrss_before": hwm_before,
                "ru_maxrss_after": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss,
                "ru_maxrss_platform_semantics": (
                    "bytes" if sys.platform == "darwin" else "platform_defined"
                ),
            },
            "result": result_summary,
            "terminal": _state_outcome(
                timing_records,
                custody_present=custody_present,
            ),
            "stage_timings": timing_records,
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "psutil": psutil.__version__,
            },
        }
        _write_json(output_dir / "diagnostic.json", diagnostic)
        return diagnostic
    except BaseException as failure:
        failure_record = {
            **activation_record,
            "completed_at_utc": _utc_now(),
            "wall_ms": max((time.perf_counter() - started) * 1000.0, 0.0),
            "status": "runner_error",
            "error_type": type(failure).__name__,
            "error": " ".join(str(failure).split())[:512],
            "stage_timings": timing_records,
        }
        _write_json(output_dir / "diagnostic.json", failure_record)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--budget-seconds", required=True, type=float)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    diagnostic = run(
        arguments.case,
        arguments.budget_seconds,
        arguments.output_dir.resolve(),
    )
    result = diagnostic["result"]
    terminal = diagnostic["terminal"]
    print(
        json.dumps(
            {
                "case": arguments.case,
                "budget_seconds": arguments.budget_seconds,
                "terminal_outcome": terminal["outcome"],
                "table_evidence_count": result["table_evidence_count"],
                "canonical_source_custody_present": result[
                    "canonical_source_custody_present"
                ],
                "all_table_projections_match_predecessor": result[
                    "all_table_projections_match_predecessor"
                ],
                "wall_ms": diagnostic["wall_ms"],
                "output_dir": str(arguments.output_dir.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
