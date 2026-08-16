"""Process-isolated cold/warm stage diagnostic for the NY timetable fixture.

This is evidence tooling, not a production execution path.  It deliberately:

* uses the real in-process ASGI application without opening a TCP listener;
* loads the same exported feature profile used by the local UI backend;
* preserves the production P04 5.000 s/document and 0.500 s/page budgets;
* issues exactly two requests (cold, then warm) without retrying either one;
* reuses the reviewed external latency observer for its closed stage trace;
* adds small, separately identified wrappers only for visual/IR/canonical work;
* records the bounded canonical OCR omission and its independent replay;
* retains raw responses, hashes, host/resource context, and mutation evidence.

The lane is process-isolated but intentionally *not* claimed to be host-
exclusive.  Other user processes and local backend listeners may remain live.
"""

from __future__ import annotations

import argparse
import contextvars
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import functools
import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import threading
import time
import traceback
import types
from typing import Any, Callable, Mapping

import psutil


WORKSPACE = Path(__file__).resolve().parents[2]
SCHEMA_ID = "ny-timetable-cold-warm-stage-diagnostic-v2"
EXPECTED_SOURCE_SHA256 = (
    "f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30"
)
EXPECTED_SOURCE_BYTES = 26_109
EXPECTED_PAGE_COUNT = 3
EXPECTED_TABLE_ROW_SHA256 = (
    "08a23117540bc200d4ca8c5bd80340db8aeef186843592f469c84a589a44bb3a",
    "095590b16e3e96079d76d151e4166a5294e407d26d32ee320ec17051ed566fcd",
    "1eb9f2cff9fe121930c19acbfb740ec66a9d2f4993150c157a3ae53aef97cace",
)
EXPECTED_TERMINAL_RESIDUALS = (
    (1, "p1-i114", "text", "ew"),
    (1, "p1-i215", "text", "i"),
    (1, "p1-i270", "heading", "12:58 | 1:04"),
    (2, "p2-i103", "text", "ew"),
    (2, "p2-i202", "text", "i"),
    (3, "p3-i205", "text", "i"),
    (3, "p3-i357", "text", ">| 00"),
)
EXPECTED_TERMINAL_FOOTERS = (
    (1, "p1-i599", "Page 2 of 28"),
    (2, "p2-i580", "Page 3 of 28"),
    (3, "p3-i599", "Page 4 of 28"),
)
EXPECTED_SELECTED_VECTOR_DUPLICATE_COUNT = 1_765
EXPECTED_CANONICAL_OCR_OMISSION_COUNT = 7
EXPECTED_TOTAL_SELECTED_COUNT = (
    EXPECTED_SELECTED_VECTOR_DUPLICATE_COUNT
    + EXPECTED_CANONICAL_OCR_OMISSION_COUNT
)
EXPECTED_CANONICAL_PAGE_MARKDOWN_SHA256 = (
    "c31024c10c1df3b354964d7b9e11d6bfceecc73465f24046f538a206473dab5c",
    "faac1256e14f2dcc782d86a8430e542aecc6b522435d12268f95f2eb364ec40c",
    "c8276d0a08f3f9c562e15db7b8eadb2a71b4a18845dfc3ba6dfad658538ed31f",
)
EXPECTED_CANONICAL_DOCUMENT_MARKDOWN_SHA256 = (
    "16848d306917f37b27d89125328b2c8563e6cf9cb1727d2200a0f8013a95fcef"
)
EXPECTED_CANONICAL_OMISSION_BLOCK_IDS = (
    "pb-ff0b78ed285377229837",
    "pb-3f1cf8a21a1254e325d9",
    "pb-68f07cc9ae328ce862a1",
    "pb-f724c8061184f5b4ec76",
    "pb-fa0c5e4914d2e5a80e35",
    "pb-d8aefd9b78b9eeee2c7c",
    "pb-f646034b6a4abfc37e35",
)
EXPECTED_CANONICAL_EXPLICIT_NULL_COUNT = 22
FIDELITY_BASELINE = WORKSPACE / (
    "tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/"
    "service-final-source-grounded-20260813-v2/ny-timetable/response.json"
)
EXPECTED_FIDELITY_BASELINE_SHA256 = (
    "30dd5861ba8fb3b1b2f60c6282c4120b6467dce4191e845be924029207a6cb54"
)
EXPECTED_FIDELITY_BASELINE_BYTES = 2_670_237
PROFILE_KEY = re.compile(
    r"^(?:PARSER_|HF_HUB_|TRANSFORMERS_|TOKENIZERS_|DOCLING_|"
    r"DOCUMENT_TIMEOUT_SECONDS$|TARGETED_OCR_|OCR_|TESSERACT_|MAX_)"
)
PROFILE_EXPORT = re.compile(r"^export\s+([A-Z][A-Z0-9_]*)=(.*)$")
WORKSPACE_ASSIGNMENT = re.compile(r"^workspace=(.*)$")
SUPPLEMENTAL_TARGETS = {
    "app.services.pipeline": {
        "_merge_tables": "selected_vector.preliminary_authority",
        "_bind_selected_vector_terminal_representations": (
            "selected_vector.terminal_binding"
        ),
        "_apply_terminal_source_text_alignment": "source_alignment.terminal_apply",
        "_apply_terminal_canonical_ocr_omission": (
            "canonical_ocr_omission.terminal_commit"
        ),
        "_validate_selected_vector_ir_transition": (
            "selected_vector.ir_transition_validation"
        ),
        "_terminal_running_alignment_dependencies_are_closed": (
            "running_regions.terminal_dependencies"
        ),
        "_terminal_running_alignment_identity_matches": (
            "running_regions.terminal_identity_match"
        ),
    },
    "app.services.table_semantics": {
        "finalize_selected_vector_representations": (
            "selected_vector.final_authority"
        ),
    },
    "app.services.source_text_alignment": {
        "align_pages_to_source": "source_alignment.align_pages",
        "validate_selected_vector_suppressions": (
            "selected_vector.fresh_replay_validation"
        ),
    },
    "app.services.running_regions": {
        "replay_running_regions_identity_locked": (
            "running_regions.identity_locked_replay"
        ),
        "running_region_replay_identity": "running_regions.replay_identity",
    },
    "app.services.ocr": {
        "_run_tesseract_tsv": "ocr.tesseract_pass",
    },
    "app.services.visual_semantics": {
        "apply_visual_semantics": "pipeline.visual_semantics",
        "_declared_visual_kind": "visual.declared_kind",
    },
    "app.services.visual_source_text": {
        "recover_pdf_visual_source_text": "visual.recover_pdf_visual_source_text",
    },
    "app.services.ir": {
        "round_trip_document": "pipeline.shared_ir_round_trip",
        "build_document_ir": "pipeline.build_document_ir",
    },
    "app.services.presentation": {
        "build_canonical_presentation": "pipeline.canonical_presentation_build",
    },
    "app.services.canonical_ocr_omission": {
        "apply_source_contradicted_primary_ocr_omissions": (
            "canonical_ocr_omission.apply"
        ),
        "validate_source_contradicted_primary_ocr_omissions": (
            "canonical_ocr_omission.replay_validation"
        ),
    },
}
PACKAGE_NAMES = (
    "docling",
    "docling-core",
    "fastapi",
    "httpx",
    "numpy",
    "pdfplumber",
    "pydantic",
    "pypdfium2",
    "psutil",
    "starlette",
    "torch",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def _write_text(path: Path, value: str) -> None:
    _atomic_write(path, value.encode("utf-8"))


def _file_identity(path: Path, *, relative_to: Path = WORKSPACE) -> dict[str, Any]:
    value = path.read_bytes()
    try:
        relative = path.resolve().relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        relative = str(path.resolve())
    return {
        "path": relative,
        "size_bytes": len(value),
        "sha256": _sha256_bytes(value),
    }


def _app_tree_identity() -> dict[str, Any]:
    records = []
    for path in sorted(WORKSPACE.joinpath("app").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        records.append(_file_identity(path))
    # This matches the independent review command: sorted sha256sum-style
    # per-file records, then SHA-256 over their UTF-8 bytes.
    aggregate_bytes = "".join(
        f"{record['sha256']}  {record['path']}\n" for record in records
    ).encode("utf-8")
    return {
        "basis": "sorted-sha256sum-style-per-file-records-v1",
        "file_count": len(records),
        "aggregate_sha256": _sha256_bytes(aggregate_bytes),
        "files": records,
    }


def _tree_stat_identity(root: Path) -> dict[str, Any]:
    records = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                stat = path.stat()
                records.append(
                    {
                        "path": path.relative_to(WORKSPACE).as_posix(),
                        "size_bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
    return {
        "basis": "path-size-mtime-inventory-v1",
        "file_count": len(records),
        "aggregate_sha256": _sha256_json(records),
        "files": records,
    }


def _strip_shell_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_profile(path: Path) -> dict[str, str]:
    workspace_value: str | None = None
    exports: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        workspace_match = WORKSPACE_ASSIGNMENT.fullmatch(line)
        if workspace_match:
            workspace_value = _strip_shell_quotes(workspace_match.group(1))
            continue
        export_match = PROFILE_EXPORT.fullmatch(line)
        if not export_match:
            continue
        key, raw_value = export_match.groups()
        if PROFILE_KEY.match(key) is None:
            raise ValueError(f"profile export is outside diagnostic allowlist: {key}")
        value = _strip_shell_quotes(raw_value)
        if workspace_value is not None:
            value = value.replace("${workspace}", workspace_value).replace(
                "$workspace", workspace_value
            )
        exports[key] = value
    if not exports:
        raise ValueError("profile supplied no allowlisted exports")
    for key, value in exports.items():
        os.environ[key] = value
    return dict(sorted(exports.items()))


def _run_context_command(command: tuple[str, ...], timeout: float = 10.0) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "command": list(command),
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ns": time.perf_counter_ns() - started,
        }
    except Exception as error:  # evidence capture must fail open
        return {
            "command": list(command),
            "error": type(error).__name__,
            "duration_ns": time.perf_counter_ns() - started,
        }


def _host_snapshot(label: str) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    try:
        swap: dict[str, Any] = psutil.swap_memory()._asdict()
    except (OSError, psutil.Error) as error:
        swap = {"unavailable": True, "error_type": type(error).__name__}
    process = psutil.Process()
    try:
        load = list(os.getloadavg())
    except OSError:
        load = []
    return {
        "label": label,
        "captured_at": _utc_now(),
        "monotonic_ns": time.perf_counter_ns(),
        "host": {
            "load_average": load,
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "memory": memory._asdict(),
            "swap": swap,
            "cpu_times": psutil.cpu_times()._asdict(),
        },
        "worker": {
            "pid": process.pid,
            "ppid": process.ppid(),
            "create_time": process.create_time(),
            "rss_bytes": process.memory_info().rss,
            "thread_count": process.num_threads(),
            "cpu_times": process.cpu_times()._asdict(),
        },
        "listeners": _run_context_command(
            ("lsof", "-nP", "-iTCP", "-sTCP:LISTEN")
        ),
        "top_processes": _run_context_command(
            (
                "ps",
                "-axo",
                "pid,ppid,state,%cpu,%mem,rss,etime,command",
                "-r",
            )
        ),
        "vm_stat": _run_context_command(("vm_stat",)),
        "memory_pressure": _run_context_command(("memory_pressure",)),
        "swap_usage": _run_context_command(("sysctl", "vm.swapusage")),
        "hostinfo": _run_context_command(("hostinfo",)),
    }


def _rusage_snapshot() -> dict[str, Any]:
    def one(who: int) -> dict[str, int]:
        value = resource.getrusage(who)
        maxrss_multiplier = 1 if sys.platform == "darwin" else 1024
        return {
            "user_cpu_ns": int(value.ru_utime * 1_000_000_000),
            "system_cpu_ns": int(value.ru_stime * 1_000_000_000),
            "max_rss_bytes": int(value.ru_maxrss) * maxrss_multiplier,
            "minor_faults": int(value.ru_minflt),
            "major_faults": int(value.ru_majflt),
            "voluntary_context_switches": int(value.ru_nvcsw),
            "involuntary_context_switches": int(value.ru_nivcsw),
        }

    return {"self": one(resource.RUSAGE_SELF), "children": one(resource.RUSAGE_CHILDREN)}


def _rusage_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for owner in ("self", "children"):
        result[owner] = {
            key: int(after[owner][key]) - int(before[owner][key])
            for key in before[owner]
            if key != "max_rss_bytes"
        }
        result[owner]["max_rss_before_bytes"] = before[owner]["max_rss_bytes"]
        result[owner]["max_rss_after_bytes"] = after[owner]["max_rss_bytes"]
    result["total_cpu_ns"] = sum(
        result[owner][key]
        for owner in ("self", "children")
        for key in ("user_cpu_ns", "system_cpu_ns")
    )
    return result


class ResourceSampler:
    def __init__(self, path: Path, *, interval_seconds: float = 1.0) -> None:
        self.path = path
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._attempt = "bootstrap"
        self._lock = threading.Lock()

    def set_attempt(self, value: str) -> None:
        with self._lock:
            self._attempt = value

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._run,
            name="ny-diagnostic-resource-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval_seconds * 3))

    def _sample(self) -> dict[str, Any]:
        process = psutil.Process()
        children = []
        try:
            descendants = process.children(recursive=True)
        except (psutil.Error, OSError):
            descendants = []
        for child in descendants:
            try:
                children.append(
                    {
                        "pid": child.pid,
                        "name": child.name(),
                        "status": child.status(),
                        "rss_bytes": child.memory_info().rss,
                        "cpu_times": child.cpu_times()._asdict(),
                    }
                )
            except (psutil.Error, OSError):
                continue
        with self._lock:
            attempt = self._attempt
        memory = psutil.virtual_memory()
        try:
            swap: dict[str, Any] = psutil.swap_memory()._asdict()
        except (OSError, psutil.Error) as error:
            swap = {"unavailable": True, "error_type": type(error).__name__}
        return {
            "captured_at": _utc_now(),
            "monotonic_ns": time.perf_counter_ns(),
            "attempt": attempt,
            "load_average": list(os.getloadavg()),
            "memory_available_bytes": memory.available,
            "memory_used_bytes": memory.used,
            "memory_percent": memory.percent,
            "swap": swap,
            "host_cpu_times": psutil.cpu_times()._asdict(),
            "worker": {
                "pid": process.pid,
                "rss_bytes": process.memory_info().rss,
                "thread_count": process.num_threads(),
                "cpu_times": process.cpu_times()._asdict(),
            },
            "children": children,
        }

    def _run(self) -> None:
        with self.path.open("a", encoding="utf-8") as stream:
            while not self._stop.is_set():
                try:
                    stream.write(json.dumps(self._sample(), sort_keys=True) + "\n")
                    stream.flush()
                except Exception as error:
                    stream.write(
                        json.dumps(
                            {
                                "captured_at": _utc_now(),
                                "sampling_error": type(error).__name__,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    stream.flush()
                self._stop.wait(self.interval_seconds)


@dataclass(slots=True)
class _DetailOpen:
    ordinal: int
    name: str
    started_ns: int
    parent_ordinal: int | None
    token: contextvars.Token[tuple[int, ...]]


def _selected_vector_authority_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "present": False,
            "value_type": type(value).__name__,
            "page_count": 0,
            "record_count": 0,
            "pages": [],
        }
    encoded = _canonical_bytes(value)
    pages = []
    total_records = 0
    for page_index, page_records in sorted(value.items(), key=lambda item: item[0]):
        if not isinstance(page_records, (list, tuple)):
            raise TypeError("selected-vector page records differ")
        records = []
        for record_index, record in enumerate(page_records):
            if not isinstance(record, Mapping):
                raise TypeError("selected-vector record differs")
            rows = record.get("rows") or []
            terminal_binding = record.get("terminal_binding")
            records.append(
                {
                    "record_index": record_index,
                    "candidate_id": record.get("candidate_id"),
                    "content_sha256": record.get("content_sha256"),
                    "source_sha256": record.get("source_sha256"),
                    "vector_sha256": record.get("vector_sha256"),
                    "post_gate_table_sha256": record.get(
                        "post_gate_table_sha256"
                    ),
                    "post_gate_authority_sha256": record.get(
                        "post_gate_authority_sha256"
                    ),
                    "terminal_authority_sha256": record.get(
                        "terminal_authority_sha256"
                    ),
                    "output_position": record.get("output_position"),
                    "row_count": len(rows) if isinstance(rows, list) else None,
                    "column_count": (
                        max(
                            (
                                len(row)
                                for row in rows
                                if isinstance(row, (list, tuple))
                            ),
                            default=0,
                        )
                        if isinstance(rows, list)
                        else None
                    ),
                    "terminal_binding_sha256": (
                        _sha256_json(terminal_binding)
                        if isinstance(terminal_binding, Mapping)
                        else None
                    ),
                    "record_sha256": _sha256_json(record),
                    "record_canonical_json_bytes": len(_canonical_bytes(record)),
                }
            )
        total_records += len(records)
        pages.append(
            {
                "page_index": page_index,
                "record_count": len(records),
                "records": records,
            }
        )
    return {
        "present": bool(total_records),
        "value_type": type(value).__name__,
        "page_count": len(pages),
        "record_count": total_records,
        "canonical_json_bytes": len(encoded),
        "sha256": _sha256_bytes(encoded),
        "pages": pages,
    }


def _canonical_omission_state_summary(
    payload: Any,
    internal_ir: Any,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not hasattr(internal_ir, "model_dump"):
        raise TypeError("canonical OCR omission state differs")
    pages = payload.get("pages")
    canonical = payload.get("canonical_presentation")
    if not isinstance(pages, list) or not isinstance(canonical, Mapping):
        raise TypeError("canonical OCR omission payload differs")
    ir_dump = internal_ir.model_dump(mode="json")
    pages_encoded = _canonical_bytes(pages)
    ir_encoded = _canonical_bytes(ir_dump)
    canonical_encoded = _canonical_bytes(canonical)
    return {
        "pages_sha256": _sha256_bytes(pages_encoded),
        "pages_canonical_json_bytes": len(pages_encoded),
        "page_item_counts": [
            len(page.get("items") or [])
            for page in pages
            if isinstance(page, Mapping)
        ],
        "internal_ir_sha256": _sha256_bytes(ir_encoded),
        "internal_ir_canonical_json_bytes": len(ir_encoded),
        "canonical_presentation_sha256": _sha256_bytes(canonical_encoded),
        "canonical_presentation_canonical_json_bytes": len(canonical_encoded),
    }


def _canonical_omission_selection_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, Mapping):
        raise TypeError("canonical OCR omission summary differs")
    selections = summary.get("selections")
    if not isinstance(selections, list):
        raise TypeError("canonical OCR omission selections differ")
    reason_counts: dict[str, int] = {}
    omission_records = []
    for selection in selections:
        if not isinstance(selection, Mapping):
            raise TypeError("canonical OCR omission selection differs")
        reason = str(selection.get("terminal_reason") or "missing")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason != "source_contradicted_primary_ocr":
            continue
        rejected = selection.get("rejected_ocr_alternative")
        canonical_owner = (
            rejected.get("canonical_owner")
            if isinstance(rejected, Mapping)
            else None
        )
        if not isinstance(canonical_owner, Mapping):
            raise TypeError("canonical OCR omission owner proof differs")
        null_paths = canonical_owner.get(
            "canonical_predecessor_explicit_null_paths"
        )
        omission_records.append(
            {
                "selection_id": selection.get("id"),
                "page_index": selection.get("page_index"),
                "owner_id": selection.get("owner_id"),
                "owner_type": selection.get("owner_type"),
                "original_text": selection.get("original_text"),
                "ir_element_id": canonical_owner.get("ir_element_id"),
                "canonical_block_id": canonical_owner.get(
                    "canonical_block_id"
                ),
                "pdf_object_count": canonical_owner.get("pdf_object_count"),
                "pdf_object_manifest_sha256": canonical_owner.get(
                    "pdf_object_manifest_sha256"
                ),
                "source_separator_count": canonical_owner.get(
                    "source_separator_count"
                ),
                "source_separator_manifest_sha256": canonical_owner.get(
                    "source_separator_manifest_sha256"
                ),
                "canonical_omission_proof_sha256": canonical_owner.get(
                    "canonical_omission_proof_sha256"
                ),
                "explicit_null_path_count": (
                    len(null_paths) if isinstance(null_paths, list) else None
                ),
                "explicit_null_paths_sha256": canonical_owner.get(
                    "canonical_predecessor_explicit_null_paths_sha256"
                ),
                "owner_snapshot_sha256": (
                    _sha256_json(rejected.get("owner_snapshot"))
                    if isinstance(rejected, Mapping)
                    else None
                ),
            }
        )
    encoded = _canonical_bytes(summary)
    semantic_summary = dict(summary)
    semantic_summary.pop("elapsed_ms", None)
    return {
        "status": summary.get("status"),
        "reason": summary.get("reason"),
        "source_sha256": summary.get("source_sha256"),
        "considered_count": summary.get("considered_count"),
        "selected_count": summary.get("selected_count"),
        "unchanged_count": summary.get("unchanged_count"),
        "unresolved_count": summary.get("unresolved_count"),
        "selection_count": len(selections),
        "selection_ids": [
            value.get("id") for value in selections if isinstance(value, Mapping)
        ],
        "selections_sha256": _sha256_json(selections),
        "terminal_reason_counts": dict(sorted(reason_counts.items())),
        "canonical_ocr_omission_count": len(omission_records),
        "canonical_ocr_omissions": omission_records,
        "reported_elapsed_ms": summary.get("elapsed_ms"),
        "evidence_elapsed_ms": summary.get("evidence_elapsed_ms"),
        "report_canonical_json_bytes": len(encoded),
        "report_sha256": _sha256_bytes(encoded),
        "semantic_report_sha256": _sha256_json(semantic_summary),
    }


def _call_argument(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    position: int,
    name: str,
    default: Any = None,
) -> Any:
    return args[position] if len(args) > position else kwargs.get(name, default)


def _selected_vector_binder_input_summary(
    payload: Any,
    internal_ir: Any,
    representations: Any,
    source_sha256: Any,
    trace_state: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not hasattr(internal_ir, "model_dump"):
        raise TypeError("selected-vector binder inputs differ")
    ir_dump = internal_ir.model_dump(mode="json", exclude_none=True)
    pages = payload.get("pages") or []
    canonical = payload.get("canonical_presentation")
    canonical_pages = (
        canonical.get("pages") if isinstance(canonical, Mapping) else []
    ) or []
    elements = list(getattr(internal_ir, "elements", ()) or ())
    evidence = list(getattr(internal_ir, "evidence", ()) or ())
    bboxes = list(getattr(internal_ir, "bboxes", ()) or ())
    regions = list(getattr(internal_ir, "regions", ()) or ())
    relationships = list(getattr(internal_ir, "relationships", ()) or ())
    concerns = list(getattr(internal_ir, "concerns", ()) or ())
    ir_pages = list(getattr(internal_ir, "pages", ()) or ())
    elements_by_id = {getattr(value, "id", None): value for value in elements}
    evidence_by_id = {getattr(value, "id", None): value for value in evidence}
    bboxes_by_id = {getattr(value, "id", None): value for value in bboxes}
    page_by_index = {
        page.get("page_index"): page
        for page in pages
        if isinstance(page, Mapping)
    }
    canonical_by_index = {
        page.get("page_index"): page
        for page in canonical_pages
        if isinstance(page, Mapping)
    }
    ir_page_by_index = {
        getattr(page, "page_index", None): page for page in ir_pages
    }
    table_records = []
    for page_index, page_representations in (
        representations.items() if isinstance(representations, Mapping) else ()
    ):
        page = page_by_index.get(page_index)
        canonical_page = canonical_by_index.get(page_index)
        ir_page = ir_page_by_index.get(page_index)
        items = page.get("items") or [] if isinstance(page, Mapping) else []
        blocks = (
            canonical_page.get("blocks") or []
            if isinstance(canonical_page, Mapping)
            else []
        )
        for representation_index, representation in enumerate(
            page_representations or ()
        ):
            candidate_id = (
                representation.get("candidate_id")
                if isinstance(representation, Mapping)
                else None
            )
            public_matches = [
                (item_index, item)
                for item_index, item in enumerate(items)
                if isinstance(item, Mapping)
                and item.get("type") == "table"
                and isinstance(item.get("table_reconciliation"), Mapping)
                and item["table_reconciliation"].get("selected_candidate_id")
                == candidate_id
            ]
            public_table = public_matches[0][1] if len(public_matches) == 1 else None
            public_id = (
                public_table.get("id")
                if isinstance(public_table, Mapping)
                else None
            )
            element_matches = [
                element
                for element in elements
                if isinstance(getattr(element, "properties", None), Mapping)
                and isinstance(element.properties.get("legacy_item"), Mapping)
                and element.properties["legacy_item"].get("id") == public_id
            ]
            element_summaries = []
            for element in element_matches:
                element_evidence = [
                    evidence_by_id.get(identifier)
                    for identifier in (getattr(element, "evidence_ids", ()) or ())
                ]
                incident = [
                    relationship
                    for relationship in relationships
                    if getattr(element, "id", None)
                    in {
                        getattr(relationship, "source_id", None),
                        getattr(relationship, "target_id", None),
                    }
                ]
                owning_regions = [
                    region
                    for region in regions
                    if getattr(element, "id", None)
                    in (getattr(region, "element_ids", ()) or ())
                ]
                element_bbox_ids = list(getattr(element, "bbox_ids", ()) or ())
                element_bbox = (
                    bboxes_by_id.get(element_bbox_ids[0])
                    if len(element_bbox_ids) == 1
                    else None
                )
                matching_blocks = [
                    block
                    for block in blocks
                    if isinstance(block, Mapping)
                    and block.get("primary_element_id")
                    == getattr(element, "id", None)
                ]
                element_summaries.append(
                    {
                        "id": getattr(element, "id", None),
                        "type": getattr(element, "type", None),
                        "page_id": getattr(element, "page_id", None),
                        "reading_order": getattr(element, "reading_order", None),
                        "source_position": element.properties.get(
                            "source_position"
                        ),
                        "property_keys": sorted(element.properties),
                        "legacy_item_sha256": _sha256_json(
                            element.properties.get("legacy_item")
                        ),
                        "bbox_ids": element_bbox_ids,
                        "bbox_sha256": (
                            _sha256_json(element_bbox.model_dump(mode="json"))
                            if element_bbox is not None
                            else None
                        ),
                        "text_run_id_count": len(
                            getattr(element, "text_run_ids", ()) or ()
                        ),
                        "running_region_present": (
                            getattr(element, "running_region", None) is not None
                        ),
                        "form_semantics_present": (
                            getattr(element, "form_semantics", None) is not None
                        ),
                        "outline_group_present": (
                            getattr(element, "outline_group", None) is not None
                        ),
                        "outline_item_present": (
                            getattr(element, "outline_item", None) is not None
                        ),
                        "visual_model_evidence_present": (
                            getattr(element, "visual_model_evidence", None) is not None
                        ),
                        "evidence": [
                            (
                                {
                                    "id": getattr(value, "id", None),
                                    "method": str(getattr(value.method, "value", None)),
                                    "element_id": getattr(value, "element_id", None),
                                    "bbox_id": getattr(value, "bbox_id", None),
                                    "value_sha256": _sha256_json(
                                        getattr(value, "value", None)
                                    ),
                                    "confidence": value.confidence.model_dump(
                                        mode="json"
                                    ),
                                    "metadata": getattr(value, "metadata", None),
                                }
                                if value is not None
                                else None
                            )
                            for value in element_evidence
                        ],
                        "incident_relationships": [
                            {
                                "id": getattr(value, "id", None),
                                "type": str(getattr(value.type, "value", None)),
                                "source_id": getattr(value, "source_id", None),
                                "target_id": getattr(value, "target_id", None),
                                "evidence_id_count": len(
                                    getattr(value, "evidence_ids", ()) or ()
                                ),
                                "metadata": getattr(value, "metadata", None),
                            }
                            for value in incident
                        ],
                        "owning_regions": [
                            {
                                "id": getattr(value, "id", None),
                                "page_id": getattr(value, "page_id", None),
                                "role": getattr(value, "role", None),
                                "element_occurrences": list(
                                    getattr(value, "element_ids", ()) or ()
                                ).count(getattr(element, "id", None)),
                            }
                            for value in owning_regions
                        ],
                        "canonical_block_count": len(matching_blocks),
                        "canonical_block_sha256": (
                            _sha256_json(matching_blocks[0])
                            if len(matching_blocks) == 1
                            else None
                        ),
                        "concern_reference_count": sum(
                            getattr(concern, "source_ref", None)
                            in {
                                getattr(element, "id", None),
                                *element_bbox_ids,
                                *(getattr(element, "evidence_ids", ()) or ()),
                            }
                            or getattr(concern, "target_ref", None)
                            in {
                                getattr(element, "id", None),
                                *element_bbox_ids,
                                *(getattr(element, "evidence_ids", ()) or ()),
                            }
                            for concern in concerns
                        ),
                    }
                )
            table_records.append(
                {
                    "page_index": page_index,
                    "representation_index": representation_index,
                    "candidate_id": candidate_id,
                    "representation_sha256": _sha256_json(representation),
                    "public_match_count": len(public_matches),
                    "public_item_position": (
                        public_matches[0][0] if len(public_matches) == 1 else None
                    ),
                    "public_table_id": public_id,
                    "public_table_sha256": (
                        _sha256_json(public_table)
                        if isinstance(public_table, Mapping)
                        else None
                    ),
                    "ir_element_match_count": len(element_matches),
                    "ir_elements": element_summaries,
                    "ir_page_id": getattr(ir_page, "id", None),
                }
            )

    expected_reading_pairs = set()
    for ir_page in ir_pages:
        ordered = []
        for element_id in getattr(ir_page, "presentation_element_ids", ()) or ():
            element = elements_by_id.get(element_id)
            properties = getattr(element, "properties", None)
            if element is None or not isinstance(properties, Mapping):
                continue
            ordered.append(
                (
                    getattr(element, "reading_order", None),
                    properties.get("source_position"),
                    getattr(element, "id", None),
                )
            )
        try:
            ordered.sort()
        except TypeError:
            continue
        expected_reading_pairs.update(
            (first[2], second[2])
            for first, second in zip(ordered, ordered[1:])
        )
    observed_reading_pairs = [
        (getattr(value, "source_id", None), getattr(value, "target_id", None))
        for value in relationships
        if str(getattr(value.type, "value", None)) == "reading_before"
        and getattr(value, "metadata", None) == {"basis": "legacy_reading_order"}
    ]
    missing_reading_pairs = sorted(
        expected_reading_pairs.difference(observed_reading_pairs)
    )
    extra_reading_pairs = sorted(
        set(observed_reading_pairs).difference(expected_reading_pairs)
    )
    return {
        "source_sha256_argument": source_sha256,
        "payload_source_sha256": (payload.get("document") or {}).get("sha256"),
        "ir_source_sha256": getattr(internal_ir, "source_sha256", None),
        "payload_pages_sha256": _sha256_json(pages),
        "canonical_sha256": _sha256_json(canonical),
        "internal_ir_sha256": _sha256_json(ir_dump),
        "ir_counts": {
            name: len(getattr(internal_ir, name, ()) or ())
            for name in (
                "coordinate_systems",
                "pages",
                "regions",
                "elements",
                "evidence",
                "bboxes",
                "text_rules",
                "text_runs",
                "relationships",
                "concerns",
            )
        },
        "reading_pair_closure": {
            "expected_count": len(expected_reading_pairs),
            "observed_count": len(observed_reading_pairs),
            "observed_unique_count": len(set(observed_reading_pairs)),
            "missing_count": len(missing_reading_pairs),
            "missing_sha256": _sha256_json(missing_reading_pairs),
            "extra_count": len(extra_reading_pairs),
            "extra_sha256": _sha256_json(extra_reading_pairs),
        },
        "authority": _selected_vector_authority_summary(representations),
        "tables": table_records,
        "trace": dict(trace_state),
    }


class DetailCollector:
    """Small supplemental observer for stages absent from the closed v1 enum."""

    def __init__(self) -> None:
        self._stack: contextvars.ContextVar[tuple[int, ...]] = contextvars.ContextVar(
            "ny_diagnostic_detail_stack", default=()
        )
        self._next = 0
        self._lock = threading.RLock()
        self.events: list[dict[str, Any]] = []
        self.planned_render_requests: list[dict[str, Any]] = []
        self.executed_render_regions: list[dict[str, Any]] = []
        self.vector_authority_events: list[dict[str, Any]] = []
        self.alignment_events: list[dict[str, Any]] = []
        self.validation_events: list[dict[str, Any]] = []
        self.running_region_events: list[dict[str, Any]] = []
        self.binder_trace_events: list[dict[str, Any]] = []
        self.canonical_ocr_omission_events: list[dict[str, Any]] = []

    def invoke(
        self,
        name: str,
        function: Callable[[], Any],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        started_ns = time.perf_counter_ns()
        cpu_started_ns = time.process_time_ns()
        with self._lock:
            ordinal = self._next
            self._next += 1
            stack = self._stack.get()
            token = self._stack.set((*stack, ordinal))
        opened = _DetailOpen(
            ordinal=ordinal,
            name=name,
            started_ns=started_ns,
            parent_ordinal=stack[-1] if stack else None,
            token=token,
        )
        status = "success"
        error_type = None
        try:
            return function()
        except BaseException as error:
            status = (
                "timeout"
                if isinstance(error, subprocess.TimeoutExpired)
                or "timeout" in type(error).__name__.casefold()
                else "error"
            )
            error_type = type(error).__name__
            raise
        finally:
            ended_ns = time.perf_counter_ns()
            cpu_ended_ns = time.process_time_ns()
            with self._lock:
                self._stack.reset(opened.token)
                self.events.append(
                    {
                        "span_id": f"supplemental-{ordinal:03d}",
                        "name": name,
                        "parent_supplemental_span_id": (
                            f"supplemental-{opened.parent_ordinal:03d}"
                            if opened.parent_ordinal is not None
                            else None
                        ),
                        "started_monotonic_ns": started_ns,
                        "ended_monotonic_ns": ended_ns,
                        "inclusive_wall_ns": ended_ns - started_ns,
                        "inclusive_process_cpu_ns": cpu_ended_ns - cpu_started_ns,
                        "status": status,
                        "error_type": error_type,
                        "metadata": dict(metadata or {}),
                    }
                )

    def record_render_plan(self, requests: Any) -> None:
        retained = []
        for object_index, request in enumerate(tuple(requests or ())):
            request_metadata = getattr(request, "metadata", {})
            retained.append(
                {
                    "object_index": object_index,
                    "page_index": getattr(request, "page_index", None),
                    "region_role": getattr(request, "region_role", None),
                    "content_type": getattr(request, "content_type", None),
                    "render_reason": (
                        request_metadata.get("render_reason")
                        if isinstance(request_metadata, Mapping)
                        else None
                    ),
                    "layout_source_note_zone": (
                        request_metadata.get("layout_source_note_zone")
                        if isinstance(request_metadata, Mapping)
                        else None
                    ),
                }
            )
        with self._lock:
            self.planned_render_requests.extend(retained)

    def record_render_results(self, result: Any) -> None:
        retained = []
        if isinstance(result, Mapping):
            for page_index, regions in result.items():
                for region in tuple(regions or ()):
                    metadata = getattr(region, "metadata", {})
                    retained.append(
                        {
                            "page_index": page_index,
                            "object_index": getattr(region, "object_index", None),
                            "region_role": getattr(region, "region_role", None),
                            "content_type": getattr(region, "content_type", None),
                            "render_reason": (
                                metadata.get("render_reason")
                                if isinstance(metadata, Mapping)
                                else None
                            ),
                            "ocr_profile": (
                                metadata.get("ocr_profile")
                                if isinstance(metadata, Mapping)
                                else None
                            ),
                            "ocr_pass_statuses": dict(
                                getattr(region, "ocr_pass_statuses", {}) or {}
                            ),
                            "render_pixel_width": getattr(
                                region, "render_pixel_width", None
                            ),
                            "render_pixel_height": getattr(
                                region, "render_pixel_height", None
                            ),
                        }
                    )
        with self._lock:
            self.executed_render_regions.extend(retained)

    def record_vector_authority(
        self,
        stage: str,
        value: Any,
        *,
        function_wall_ns: int,
    ) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            summary = _selected_vector_authority_summary(value)
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            summary = None
            error = type(exc).__name__
        record = {
            "ordinal": len(self.vector_authority_events),
            "stage": stage,
            "function_wall_ns": function_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "summary": summary,
            "capture_error": error,
        }
        with self._lock:
            self.vector_authority_events.append(record)

    def record_alignment(self, result: Any, *, function_wall_ns: int) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            raw_summary = result.to_dict() if hasattr(result, "to_dict") else result
            if not isinstance(raw_summary, Mapping):
                raise TypeError("alignment summary is not a mapping")
            selections = list(raw_summary.get("selections") or [])
            reason_counts: dict[str, int] = {}
            page_counts: dict[str, int] = {}
            owner_type_counts: dict[str, int] = {}
            for selection in selections:
                if not isinstance(selection, Mapping):
                    continue
                reason = str(selection.get("terminal_reason") or "missing")
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                page = str(selection.get("page_index") or "missing")
                page_counts[page] = page_counts.get(page, 0) + 1
                owner_type = str(selection.get("owner_type") or "missing")
                owner_type_counts[owner_type] = (
                    owner_type_counts.get(owner_type, 0) + 1
                )
            encoded = _canonical_bytes(raw_summary)
            summary = {
                "status": raw_summary.get("status"),
                "reason": raw_summary.get("reason"),
                "source_sha256": raw_summary.get("source_sha256"),
                "selected_count": raw_summary.get("selected_count"),
                "selection_count": len(selections),
                "terminal_reason_counts": dict(sorted(reason_counts.items())),
                "page_selection_counts": dict(sorted(page_counts.items())),
                "owner_type_counts": dict(sorted(owner_type_counts.items())),
                "reported_elapsed_ms": raw_summary.get("elapsed_ms"),
                "evidence_elapsed_ms": raw_summary.get("evidence_elapsed_ms"),
                "report_canonical_json_bytes": len(encoded),
                "report_sha256": _sha256_bytes(encoded),
            }
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            summary = None
            error = type(exc).__name__
        record = {
            "ordinal": len(self.alignment_events),
            "function_wall_ns": function_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "summary": summary,
            "capture_error": error,
        }
        with self._lock:
            self.alignment_events.append(record)

    def record_validation(
        self,
        name: str,
        result: Any,
        *,
        function_wall_ns: int,
        selection_count: int | None = None,
    ) -> None:
        record = {
            "ordinal": len(self.validation_events),
            "name": name,
            "function_wall_ns": function_wall_ns,
            "result": result if type(result) in (bool, int, float, str) else None,
            "result_type": type(result).__name__,
            "selection_count": selection_count,
        }
        with self._lock:
            self.validation_events.append(record)

    def record_running_replay(
        self,
        result: Any,
        *,
        function_wall_ns: int,
        baseline_identity: Any,
        authorized_owner_ids_by_page: Any,
        alignment_selections: Any,
    ) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            public, internal_ir = result
            pages = public.get("pages") or []
            descriptors = []
            for page_index, page in enumerate(pages, start=1):
                for item_index, item in enumerate(page.get("items") or []):
                    if not isinstance(item, Mapping):
                        continue
                    descriptor = item.get("running_region")
                    if isinstance(descriptor, Mapping):
                        descriptors.append(
                            {
                                "page_index": page_index,
                                "item_index": item_index,
                                "item_id": item.get("id"),
                                "descriptor_id": descriptor.get("id"),
                                "source_public_path": descriptor.get(
                                    "source_public_path"
                                ),
                                "predecessor_item_sha256": descriptor.get(
                                    "predecessor_item_sha256"
                                ),
                            }
                        )
            dumped_ir = (
                internal_ir.model_dump(mode="json", exclude_none=True)
                if hasattr(internal_ir, "model_dump")
                else None
            )
            authorized_counts = {
                str(key): len(value)
                for key, value in (
                    authorized_owner_ids_by_page.items()
                    if isinstance(authorized_owner_ids_by_page, Mapping)
                    else ()
                )
            }
            summary = {
                "page_item_counts": [
                    len(page.get("items") or [])
                    for page in pages
                    if isinstance(page, Mapping)
                ],
                "pages_sha256": _sha256_json(pages),
                "internal_ir_sha256": (
                    _sha256_json(dumped_ir) if dumped_ir is not None else None
                ),
                "processing_summary": (public.get("processing") or {}).get(
                    "running_regions"
                ),
                "baseline_identity_sha256": _sha256_json(baseline_identity),
                "authorized_owner_counts_by_page": dict(
                    sorted(authorized_counts.items())
                ),
                "alignment_selection_count": (
                    len(alignment_selections)
                    if isinstance(alignment_selections, (list, tuple))
                    else None
                ),
                "projected_descriptors": descriptors,
            }
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            summary = None
            error = type(exc).__name__
        record = {
            "ordinal": len(self.running_region_events),
            "kind": "identity_locked_replay",
            "function_wall_ns": function_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "summary": summary,
            "capture_error": error,
        }
        with self._lock:
            self.running_region_events.append(record)

    def record_running_identity(
        self,
        result: Any,
        *,
        function_wall_ns: int,
        baseline_identity: Any,
    ) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            result_sha256 = _sha256_json(result)
            baseline_sha256 = (
                _sha256_json(baseline_identity)
                if isinstance(baseline_identity, Mapping)
                else None
            )
            summary = {
                "identity_sha256": result_sha256,
                "baseline_identity_sha256": baseline_sha256,
                "equals_supplied_baseline": (
                    result == baseline_identity
                    if isinstance(baseline_identity, Mapping)
                    else None
                ),
            }
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            summary = None
            error = type(exc).__name__
        record = {
            "ordinal": len(self.running_region_events),
            "kind": "identity",
            "function_wall_ns": function_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "summary": summary,
            "capture_error": error,
        }
        with self._lock:
            self.running_region_events.append(record)

    def record_binder_trace(
        self,
        *,
        result: Any,
        function_wall_ns: int,
        trace_state: Mapping[str, Any],
        payload: Any,
        internal_ir: Any,
        representations: Any,
        source_sha256: Any,
        prior_trace_present: bool,
    ) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            summary = _selected_vector_binder_input_summary(
                payload,
                internal_ir,
                representations,
                source_sha256,
                trace_state,
            )
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            summary = None
            error = type(exc).__name__
        record = {
            "ordinal": len(self.binder_trace_events),
            "function_wall_ns": function_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "returned_empty": result == {},
            "result_page_count": len(result) if isinstance(result, Mapping) else None,
            "prior_trace_present": prior_trace_present,
            "summary": summary,
            "capture_error": error,
        }
        with self._lock:
            self.binder_trace_events.append(record)

    def record_binder_observer_error(
        self,
        *,
        result: Any,
        function_wall_ns: int,
        trace_state: Mapping[str, Any],
        error: BaseException,
    ) -> None:
        """Record a post-call observer failure without altering production flow."""

        try:
            record = {
                "ordinal": len(self.binder_trace_events),
                "function_wall_ns": function_wall_ns,
                "capture_wall_ns": 0,
                "returned_empty": result == {},
                "result_page_count": (
                    len(result) if isinstance(result, Mapping) else None
                ),
                "prior_trace_present": False,
                "summary": {"trace": dict(trace_state)},
                "capture_error": type(error).__name__,
                "observer_failure_phase": "post_call_evidence_capture",
            }
            with self._lock:
                self.binder_trace_events.append(record)
        except BaseException:
            # Diagnostic recording must never replace an authentic result.
            return

    def record_canonical_ocr_omission(
        self,
        name: str,
        result: Any,
        *,
        function_wall_ns: int,
        pre_capture_wall_ns: int,
        pre_state: Mapping[str, Any] | None,
        pre_capture_error: str | None,
        payload: Any,
        internal_ir: Any,
        summary: Any,
    ) -> None:
        capture_started_ns = time.perf_counter_ns()
        try:
            post_state = _canonical_omission_state_summary(payload, internal_ir)
            input_summary = _canonical_omission_selection_summary(summary)
            output_state = None
            output_summary = None
            canonical_summary = None
            processing_summary_exact = None
            output_pages_same_object = None
            result_value = None
            if name == "canonical_ocr_omission.apply":
                if (
                    not isinstance(result, tuple)
                    or len(result) != 2
                    or not isinstance(result[0], Mapping)
                    or not isinstance(result[1], Mapping)
                ):
                    raise TypeError("canonical OCR omission result differs")
                output_payload, output_alignment = result
                output_state = _canonical_omission_state_summary(
                    output_payload, internal_ir
                )
                output_summary = _canonical_omission_selection_summary(
                    output_alignment
                )
                canonical_summary = _canonical_output_summary(
                    output_payload.get("canonical_presentation")
                )
                processing = output_payload.get("processing")
                processing_summary_exact = (
                    isinstance(processing, Mapping)
                    and processing.get("source_text_alignment")
                    == output_alignment
                )
                output_pages_same_object = (
                    output_payload.get("pages") is payload.get("pages")
                )
            else:
                result_value = result if type(result) is bool else None
            record_summary = {
                "pre_state": dict(pre_state) if pre_state is not None else None,
                "post_input_state": post_state,
                "input_state_unchanged": (
                    pre_state == post_state if pre_state is not None else None
                ),
                "input_summary": input_summary,
                "output_state": output_state,
                "output_summary": output_summary,
                "canonical_summary": canonical_summary,
                "processing_summary_exact": processing_summary_exact,
                "output_pages_same_object": output_pages_same_object,
                "result": result_value,
            }
            error = None
        except BaseException as exc:  # evidence must never alter production flow
            record_summary = None
            error = type(exc).__name__
        stack = self._stack.get()
        record = {
            "ordinal": len(self.canonical_ocr_omission_events),
            "name": name,
            "supplemental_span_id": (
                f"supplemental-{stack[-1]:03d}" if stack else None
            ),
            "function_wall_ns": function_wall_ns,
            "pre_capture_wall_ns": pre_capture_wall_ns,
            "capture_wall_ns": time.perf_counter_ns() - capture_started_ns,
            "pre_capture_error": pre_capture_error,
            "summary": record_summary,
            "capture_error": error,
        }
        with self._lock:
            self.canonical_ocr_omission_events.append(record)


def _tesseract_call_metadata(
    args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> dict[str, Any]:
    psm = kwargs.get("page_segmentation_mode", 3)
    timeout_seconds = args[3] if len(args) > 3 else kwargs.get("timeout_seconds")
    png_bytes = args[1] if len(args) > 1 else b""
    metadata: dict[str, Any] = {
        "page_segmentation_mode": psm,
        "timeout_seconds": timeout_seconds,
        "input_png_bytes": len(png_bytes) if isinstance(png_bytes, bytes) else None,
        "page_index": None,
        "object_index": None,
        "region_role": None,
        "content_type": None,
        "render_reason": None,
        "layout_source_note_zone": None,
    }
    # The private pass function intentionally does not accept source-region
    # identity. Recover only bounded, content-free request metadata from its
    # reviewed adapter frame; never retain PNG bytes, TSV, or recognized text.
    frame = sys._getframe(1)
    for _ in range(12):
        if frame is None:
            break
        if (
            frame.f_globals.get("__name__") == "app.services.ocr"
            and frame.f_code.co_name == "extract_rendered_pdf_ocr"
        ):
            request = frame.f_locals.get("request")
            request_metadata = getattr(request, "metadata", {})
            metadata.update(
                {
                    "page_index": getattr(request, "page_index", None),
                    "object_index": frame.f_locals.get("object_index"),
                    "region_role": getattr(request, "region_role", None),
                    "content_type": getattr(request, "content_type", None),
                    "render_reason": (
                        request_metadata.get("render_reason")
                        if isinstance(request_metadata, Mapping)
                        else None
                    ),
                    "layout_source_note_zone": (
                        request_metadata.get("layout_source_note_zone")
                        if isinstance(request_metadata, Mapping)
                        else None
                    ),
                }
            )
            break
        frame = frame.f_back
    return metadata


@dataclass(slots=True)
class _SupplementalBinding:
    owner: Any
    attribute: str
    original: Any
    wrapper: Any


class _SupplementalLoader(importlib.abc.Loader):
    def __init__(self, loader: Any, manager: "SupplementalInstrumentation") -> None:
        self.loader = loader
        self.manager = manager

    def create_module(self, spec: Any) -> Any:
        creator = getattr(self.loader, "create_module", None)
        return creator(spec) if creator is not None else None

    def exec_module(self, module: types.ModuleType) -> None:
        executor = getattr(self.loader, "exec_module", None)
        if executor is None:
            raise ImportError("supplemental target loader is unavailable")
        spec = module.__spec__
        spec.loader = self.loader
        module.__loader__ = self.loader
        executor(module)
        self.manager.install_module(module)


class _SupplementalFinder(importlib.abc.MetaPathFinder):
    def __init__(self, manager: "SupplementalInstrumentation") -> None:
        self.manager = manager

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname not in SUPPLEMENTAL_TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"supplemental observer target unavailable: {fullname}")
        spec.loader = _SupplementalLoader(spec.loader, self.manager)
        return spec


class SupplementalInstrumentation:
    def __init__(self, collector: DetailCollector) -> None:
        self.collector = collector
        self.bindings: list[_SupplementalBinding] = []
        self.finder = _SupplementalFinder(self)
        self.closed = False

    def install(self) -> None:
        for module_name in SUPPLEMENTAL_TARGETS:
            module = sys.modules.get(module_name)
            if module is not None:
                self.install_module(module)
        models_module = sys.modules.get("app.models")
        if models_module is not None:
            self._install_owner_target(
                models_module.ParseResult,
                "_validate_table_evidence_custody_impl",
                "model.table_evidence_custody_validation",
            )
        sys.meta_path.insert(0, self.finder)

    def _install_owner_target(self, owner: Any, attribute: str, name: str) -> None:
        if any(
            binding.owner is owner and binding.attribute == attribute
            for binding in self.bindings
        ):
            return
        original = getattr(owner, attribute)

        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.collector.invoke(
                name,
                lambda: original(*args, **kwargs),
            )

        setattr(owner, attribute, wrapper)
        self.bindings.append(_SupplementalBinding(owner, attribute, original, wrapper))

    def install_module(self, module: types.ModuleType) -> None:
        targets = SUPPLEMENTAL_TARGETS.get(module.__name__, {})
        installed_keys = {(id(item.owner), item.attribute) for item in self.bindings}
        for attribute, name in targets.items():
            if (id(module), attribute) in installed_keys:
                continue
            original = getattr(module, attribute)

            if module.__name__ == "app.services.ocr" and attribute == "_run_tesseract_tsv":
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    metadata = _tesseract_call_metadata(args, kwargs)
                    return self.collector.invoke(
                        __name,
                        lambda: __original(*args, **kwargs),
                        metadata=metadata,
                    )
            elif module.__name__ == "app.services.pipeline" and attribute == "_merge_tables":
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_vector_authority(
                            "preliminary_after_merge",
                            kwargs.get("selected_vector_sink"),
                            function_wall_ns=function_wall_ns,
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.table_semantics"
                and attribute == "finalize_selected_vector_representations"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    preliminary = _call_argument(
                        args, kwargs, 1, "preliminary_representations"
                    )
                    sink = _call_argument(args, kwargs, 3, "selected_vector_sink")

                    def invoke_original() -> Any:
                        capture_started_ns = time.perf_counter_ns()
                        self.collector.record_vector_authority(
                            "preliminary_at_finalize",
                            preliminary,
                            function_wall_ns=0,
                        )
                        capture_wall_ns = time.perf_counter_ns() - capture_started_ns
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_vector_authority(
                            "final_after_gate",
                            sink,
                            function_wall_ns=function_wall_ns,
                        )
                        # The preliminary capture is explicitly diagnostic
                        # overhead and occurs before the production call.
                        self.collector.record_validation(
                            "selected_vector.preliminary_capture_overhead",
                            True,
                            function_wall_ns=capture_wall_ns,
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.pipeline"
                and attribute == "_bind_selected_vector_terminal_representations"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        target_code = __original.__code__
                        active_trace = sys.gettrace()
                        active_profile = sys.getprofile()
                        trace_state: dict[str, Any] = {
                            "target_file": target_code.co_filename,
                            "target_first_line": target_code.co_firstlineno,
                            "line_tracing_enabled": False,
                            "active_trace_before_call": active_trace is not None,
                            "active_profile_before_call": active_profile is not None,
                            "observation_mode": (
                                "outer-timing-and-post-call-summary-only"
                            ),
                        }
                        if active_trace is not None or active_profile is not None:
                            raise RuntimeError(
                                "production-equivalent binder observer requires "
                                "tracing and profiling to be disabled"
                            )
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        trace_state["return_value_empty"] = result == {}
                        trace_state["result_page_count"] = (
                            len(result) if isinstance(result, Mapping) else None
                        )
                        try:
                            self.collector.record_vector_authority(
                                "terminal_bound",
                                result,
                                function_wall_ns=function_wall_ns,
                            )
                            self.collector.record_binder_trace(
                                result=result,
                                function_wall_ns=function_wall_ns,
                                trace_state=trace_state,
                                payload=_call_argument(
                                    args, kwargs, 0, "payload"
                                ),
                                internal_ir=_call_argument(
                                    args, kwargs, 1, "internal_ir"
                                ),
                                representations=_call_argument(
                                    args, kwargs, 2, "representations"
                                ),
                                source_sha256=_call_argument(
                                    args, kwargs, 3, "source_sha256"
                                ),
                                prior_trace_present=False,
                            )
                        except BaseException as exc:
                            self.collector.record_binder_observer_error(
                                result=result,
                                function_wall_ns=function_wall_ns,
                                trace_state=trace_state,
                                error=exc,
                            )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.source_text_alignment"
                and attribute == "align_pages_to_source"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_alignment(
                            result, function_wall_ns=function_wall_ns
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.source_text_alignment"
                and attribute == "validate_selected_vector_suppressions"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        selections = _call_argument(args, kwargs, 0, "selections", ())
                        self.collector.record_validation(
                            __name,
                            result,
                            function_wall_ns=function_wall_ns,
                            selection_count=(
                                len(selections)
                                if isinstance(selections, (list, tuple))
                                else None
                            ),
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.canonical_ocr_omission"
                and attribute
                in {
                    "apply_source_contradicted_primary_ocr_omissions",
                    "validate_source_contradicted_primary_ocr_omissions",
                }
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        payload = _call_argument(args, kwargs, 0, "payload")
                        internal_ir = _call_argument(
                            args, kwargs, 1, "ir"
                        )
                        summary = _call_argument(args, kwargs, 2, "summary")
                        pre_capture_started_ns = time.perf_counter_ns()
                        try:
                            pre_state = _canonical_omission_state_summary(
                                payload, internal_ir
                            )
                            pre_capture_error = None
                        except BaseException as exc:
                            pre_state = None
                            pre_capture_error = type(exc).__name__
                        pre_capture_wall_ns = (
                            time.perf_counter_ns() - pre_capture_started_ns
                        )
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_canonical_ocr_omission(
                            __name,
                            result,
                            function_wall_ns=function_wall_ns,
                            pre_capture_wall_ns=pre_capture_wall_ns,
                            pre_state=pre_state,
                            pre_capture_error=pre_capture_error,
                            payload=payload,
                            internal_ir=internal_ir,
                            summary=summary,
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.running_regions"
                and attribute == "replay_running_regions_identity_locked"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_running_replay(
                            result,
                            function_wall_ns=function_wall_ns,
                            baseline_identity=kwargs.get("baseline_identity"),
                            authorized_owner_ids_by_page=kwargs.get(
                                "alignment_authorized_owner_ids_by_page"
                            ),
                            alignment_selections=kwargs.get("alignment_selections"),
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif (
                module.__name__ == "app.services.running_regions"
                and attribute == "running_region_replay_identity"
            ):
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        self.collector.record_running_identity(
                            result,
                            function_wall_ns=function_wall_ns,
                            baseline_identity=kwargs.get("baseline_identity"),
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            elif module.__name__ == "app.services.pipeline" and attribute in {
                "_validate_selected_vector_ir_transition",
                "_terminal_running_alignment_dependencies_are_closed",
                "_terminal_running_alignment_identity_matches",
            }:
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    __attribute: str = attribute,
                    **kwargs: Any,
                ) -> Any:
                    def invoke_original() -> Any:
                        started_ns = time.perf_counter_ns()
                        result = __original(*args, **kwargs)
                        function_wall_ns = time.perf_counter_ns() - started_ns
                        selection_count = None
                        if __attribute == "_validate_selected_vector_ir_transition":
                            selections = _call_argument(
                                args, kwargs, 2, "selections", ()
                            )
                            if isinstance(selections, (list, tuple)):
                                selection_count = len(selections)
                        self.collector.record_validation(
                            __name,
                            True if result is None else result,
                            function_wall_ns=function_wall_ns,
                            selection_count=selection_count,
                        )
                        return result

                    return self.collector.invoke(__name, invoke_original)
            else:
                @functools.wraps(original)
                def wrapper(
                    *args: Any,
                    __original: Any = original,
                    __name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    return self.collector.invoke(
                        __name,
                        lambda: __original(*args, **kwargs),
                    )

            setattr(module, attribute, wrapper)
            self.bindings.append(
                _SupplementalBinding(module, attribute, original, wrapper)
            )

    def close(self) -> dict[str, Any]:
        if self.closed:
            raise RuntimeError("supplemental observer closed twice")
        if self.finder in sys.meta_path:
            sys.meta_path.remove(self.finder)
        restored = []
        for binding in reversed(self.bindings):
            exact_installed = getattr(binding.owner, binding.attribute) is binding.wrapper
            if exact_installed:
                setattr(binding.owner, binding.attribute, binding.original)
            restored.append(
                {
                    "owner": (
                        binding.owner.__name__
                        if isinstance(binding.owner, types.ModuleType)
                        else f"{binding.owner.__module__}.{binding.owner.__qualname__}"
                    ),
                    "attribute": binding.attribute,
                    "installed_binding_intact": exact_installed,
                    "restored_exact": (
                        getattr(binding.owner, binding.attribute) is binding.original
                    ),
                }
            )
        self.closed = True
        return {
            "method": "lightweight-perf-counter-wrapper-with-scoped-import-loader-v1",
            "target_count": len(self.bindings),
            "bindings": list(reversed(restored)),
        }


def _calibrate_detail_overhead() -> dict[str, Any]:
    call_count = 64

    def noop() -> None:
        return None

    started = time.perf_counter_ns()
    for _ in range(call_count):
        noop()
    direct_ns = time.perf_counter_ns() - started
    collector = DetailCollector()
    started = time.perf_counter_ns()
    for _ in range(call_count):
        collector.invoke("calibration.noop", noop)
    wrapped_ns = time.perf_counter_ns() - started
    return {
        "calibration_id": "supplemental-detail-collector-noop-v1",
        "call_count": call_count,
        "direct_total_ns": direct_ns,
        "wrapped_total_ns": wrapped_ns,
        "absolute_delta_ns": abs(wrapped_ns - direct_ns),
        "adjustment_applied": False,
    }


def _interval_union(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    total = 0
    left, right = sorted(intervals)[0]
    for start, end in sorted(intervals)[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def _summarize_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    spans = list(trace.get("spans") or [])
    children: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        parent = span.get("parent_span_id")
        if parent is not None:
            children.setdefault(str(parent), []).append(span)
    rows = []
    for span in spans:
        inclusive = int(span["ended_monotonic_ns"]) - int(
            span["started_monotonic_ns"]
        )
        direct_children = children.get(str(span["span_id"]), [])
        child_union = _interval_union(
            [
                (
                    max(int(child["started_monotonic_ns"]), int(span["started_monotonic_ns"])),
                    min(int(child["ended_monotonic_ns"]), int(span["ended_monotonic_ns"])),
                )
                for child in direct_children
            ]
        )
        rows.append(
            {
                **span,
                "inclusive_wall_ns": inclusive,
                "direct_child_union_ns": child_union,
                "exclusive_wall_ns": max(0, inclusive - child_union),
                "inclusive_is_additive": False,
            }
        )
    stage_aggregates: dict[str, dict[str, Any]] = {}
    for row in rows:
        aggregate = stage_aggregates.setdefault(
            str(row["name"]),
            {
                "invocation_count": 0,
                "inclusive_wall_ns": 0,
                "exclusive_wall_ns": 0,
                "inclusive_is_additive_across_hierarchy": False,
            },
        )
        aggregate["invocation_count"] += 1
        aggregate["inclusive_wall_ns"] += row["inclusive_wall_ns"]
        aggregate["exclusive_wall_ns"] += row["exclusive_wall_ns"]
    top_level = [row for row in rows if row.get("parent_span_id") == "request"]
    top_union = _interval_union(
        [
            (int(row["started_monotonic_ns"]), int(row["ended_monotonic_ns"]))
            for row in top_level
        ]
    )
    request_total = int(trace["authoritative_total_ns"])
    request_span = next(
        (row for row in rows if row.get("span_id") == "request"), None
    )
    spans_bounded_by_request = bool(request_span) and all(
        int(request_span["started_monotonic_ns"])
        <= int(row["started_monotonic_ns"])
        <= int(row["ended_monotonic_ns"])
        <= int(request_span["ended_monotonic_ns"])
        for row in rows
        if row.get("span_id") != "request"
    )
    observer_union = trace.get("attributed_top_level_union_ns")
    observer_residual = trace.get("unattributed_remainder_ns")
    computed_residual = request_total - top_union
    closure_checks = {
        "computed_union_matches_observer": top_union == observer_union,
        "computed_residual_matches_observer": computed_residual == observer_residual,
        "residual_nonnegative": computed_residual >= 0,
        "all_nonroot_spans_bounded_by_request": spans_bounded_by_request,
        "union_plus_residual_equals_total": (
            top_union + computed_residual == request_total
        ),
    }
    return {
        "timing_policy": {
            "wall_clock": "perf_counter_ns",
            "inclusive_rows_are_nested_and_must_not_be_summed": True,
            "exclusive_wall_ns": "inclusive minus union of direct child wall intervals",
            "closure": "disjoint top-level union plus explicit residual",
        },
        "spans": rows,
        "stage_aggregates": stage_aggregates,
        "closure": {
            "request_total_ns": request_total,
            "disjoint_top_level_union_ns": top_union,
            "explicit_residual_ns": computed_residual,
            "observer_reported_top_level_union_ns": observer_union,
            "observer_reported_residual_ns": observer_residual,
            "checks": closure_checks,
            "valid": all(closure_checks.values()),
        },
    }


def _attach_supplemental_parents(
    events: list[dict[str, Any]], base_spans: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    attached = []
    for event in sorted(events, key=lambda item: item["started_monotonic_ns"]):
        containing = [
            span
            for span in base_spans
            if int(span["started_monotonic_ns"])
            <= int(event["started_monotonic_ns"])
            <= int(event["ended_monotonic_ns"])
            <= int(span["ended_monotonic_ns"])
        ]
        owner = min(
            containing,
            key=lambda span: int(span["ended_monotonic_ns"])
            - int(span["started_monotonic_ns"]),
            default=None,
        )
        attached.append(
            {
                **event,
                "containing_base_span_id": owner.get("span_id") if owner else None,
                "containing_base_stage": owner.get("name") if owner else None,
                "inclusive_is_additive": False,
            }
        )
    return attached


def _detail_aggregates(events: list[Mapping[str, Any]]) -> dict[str, Any]:
    aggregates: dict[str, dict[str, Any]] = {}
    for event in events:
        name = str(event.get("name"))
        aggregate = aggregates.setdefault(
            name,
            {
                "invocation_count": 0,
                "inclusive_wall_ns": 0,
                "inclusive_process_cpu_ns": 0,
                "success_count": 0,
                "timeout_count": 0,
                "error_count": 0,
                "inclusive_is_additive_across_hierarchy": False,
            },
        )
        aggregate["invocation_count"] += 1
        aggregate["inclusive_wall_ns"] += int(event.get("inclusive_wall_ns") or 0)
        aggregate["inclusive_process_cpu_ns"] += int(
            event.get("inclusive_process_cpu_ns") or 0
        )
        status = str(event.get("status") or "error")
        counter = f"{status}_count"
        if counter not in aggregate:
            counter = "error_count"
        aggregate[counter] += 1
    return dict(sorted(aggregates.items()))


def _semantic_projection(payload: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    projected = json.loads(json.dumps(payload, ensure_ascii=False))
    processing = projected.get("processing")
    excluded: list[str] = []
    if isinstance(processing, dict):
        def strip_timings(value: Any, pointer: str) -> None:
            if isinstance(value, dict):
                for key in tuple(value):
                    child_pointer = f"{pointer}/{key}"
                    if key == "duration_ms" or key == "elapsed_ms" or key.endswith("_ms"):
                        value.pop(key)
                        excluded.append(child_pointer)
                    else:
                        strip_timings(value[key], child_pointer)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    strip_timings(item, f"{pointer}/{index}")

        strip_timings(processing, "/processing")
    return projected, sorted(excluded)


def _response_alignment_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    processing = payload.get("processing")
    alignment = (
        processing.get("source_text_alignment")
        if isinstance(processing, Mapping)
        else None
    )
    if not isinstance(alignment, Mapping):
        return {"present": False}
    summary = _canonical_omission_selection_summary(alignment)
    page_counts: dict[str, int] = {}
    for selection in alignment.get("selections") or []:
        if isinstance(selection, Mapping):
            page = str(selection.get("page_index") or "missing")
            page_counts[page] = page_counts.get(page, 0) + 1
    return {
        "present": True,
        **summary,
        "page_selection_counts": dict(sorted(page_counts.items())),
    }


def _explicit_null_path_summary(value: Any) -> dict[str, Any]:
    paths: list[list[str | int]] = []
    stack: list[tuple[Any, list[str | int]]] = [(value, [])]
    while stack:
        current, path = stack.pop()
        if current is None:
            paths.append(path)
        elif isinstance(current, Mapping):
            for key in sorted(current, reverse=True):
                stack.append((current[key], [*path, str(key)]))
        elif isinstance(current, list):
            for index in range(len(current) - 1, -1, -1):
                stack.append((current[index], [*path, index]))
    paths.sort(key=lambda item: _canonical_bytes(item))
    return {
        "count": len(paths),
        "paths_sha256": _sha256_json(paths),
    }


def _canonical_output_summary(canonical: Any) -> dict[str, Any]:
    if not isinstance(canonical, Mapping):
        return {"present": False}
    page_block_counts = []
    page_summaries = []
    scope_counts: dict[str, int] = {}
    omission_reason_counts: dict[str, int] = {}
    table_blocks = []
    omitted_blocks = []
    visible_blocks = []
    for page_index, page in enumerate(canonical.get("pages") or [], start=1):
        blocks = page.get("blocks") or [] if isinstance(page, Mapping) else []
        page_block_counts.append(len(blocks))
        blocks_by_id = {
            block.get("id"): block
            for block in blocks
            if isinstance(block, Mapping)
        }
        full = page.get("full") if isinstance(page, Mapping) else None
        full_block_ids = (
            list(full.get("block_ids") or [])
            if isinstance(full, Mapping)
            else []
        )
        page_markdown = (
            str(full.get("markdown") or "")
            if isinstance(full, Mapping)
            else ""
        )
        page_visible = []
        for block_id in full_block_ids:
            block = blocks_by_id.get(block_id)
            if not isinstance(block, Mapping):
                page_visible.append(
                    {"block_id": block_id, "block_missing": True}
                )
                continue
            markdown = str(block.get("markdown") or "")
            text = str(block.get("text") or "")
            retained = {
                "block_id": block_id,
                "primary_element_id": block.get("primary_element_id"),
                "primary_element_type": block.get("primary_element_type"),
                "scope": block.get("scope"),
                "markdown_bytes": len(markdown.encode("utf-8")),
                "markdown_sha256": _sha256_bytes(markdown.encode("utf-8")),
                "text_bytes": len(text.encode("utf-8")),
                "text_sha256": _sha256_bytes(text.encode("utf-8")),
            }
            page_visible.append(retained)
            visible_blocks.append({"page_index": page_index, **retained})
        page_summaries.append(
            {
                "page_index": page_index,
                "page_id": page.get("page_id") if isinstance(page, Mapping) else None,
                "block_count": len(blocks),
                "included_full_block_ids": full_block_ids,
                "included_full_block_count": len(full_block_ids),
                "included_full_blocks": page_visible,
                "full_markdown_bytes": len(page_markdown.encode("utf-8")),
                "full_markdown_sha256": _sha256_bytes(
                    page_markdown.encode("utf-8")
                ),
            }
        )
        for block_index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                continue
            scope = str(block.get("scope") or "missing")
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
            omission_reason = block.get("omission_reason")
            if omission_reason is not None:
                reason = str(omission_reason)
                omission_reason_counts[reason] = (
                    omission_reason_counts.get(reason, 0) + 1
                )
                omitted_blocks.append(
                    {
                        "page_index": page_index,
                        "block_index": block_index,
                        "block_id": block.get("id"),
                        "primary_element_id": block.get("primary_element_id"),
                        "primary_element_type": block.get(
                            "primary_element_type"
                        ),
                        "scope": block.get("scope"),
                        "omission_reason": omission_reason,
                        "markdown": block.get("markdown"),
                        "text": block.get("text"),
                        "contributing_element_ids": block.get(
                            "contributing_element_ids"
                        ),
                    }
                )
            if block.get("primary_element_type") == "table":
                markdown = str(block.get("markdown") or "")
                table_blocks.append(
                    {
                        "page_index": page_index,
                        "block_index": block_index,
                        "block_id": block.get("id"),
                        "primary_element_id": block.get("primary_element_id"),
                        "markdown_bytes": len(markdown.encode("utf-8")),
                        "markdown_sha256": _sha256_bytes(
                            markdown.encode("utf-8")
                        ),
                    }
                )
    sections = {}
    for name in ("full", "body", "header", "footer"):
        section = canonical.get(name)
        markdown = (
            str(section.get("markdown") or "")
            if isinstance(section, Mapping)
            else ""
        )
        sections[name] = {
            "markdown_bytes": len(markdown.encode("utf-8")),
            "markdown_sha256": _sha256_bytes(markdown.encode("utf-8")),
        }
    return {
        "present": True,
        "sha256": _sha256_json(canonical),
        "page_block_counts": page_block_counts,
        "pages": page_summaries,
        "total_block_count": sum(page_block_counts),
        "scope_counts": dict(sorted(scope_counts.items())),
        "omission_reason_counts": dict(sorted(omission_reason_counts.items())),
        "omitted_block_count": len(omitted_blocks),
        "omitted_blocks": omitted_blocks,
        "visible_block_count": len(visible_blocks),
        "visible_blocks": visible_blocks,
        "table_blocks": table_blocks,
        "explicit_nulls": _explicit_null_path_summary(canonical),
        "sections": sections,
    }


def _terminal_output_inventory(payload: Mapping[str, Any]) -> dict[str, Any]:
    page_summaries = []
    residual_items = []
    footers = []
    for page_index, page in enumerate(payload.get("pages") or [], start=1):
        items = page.get("items") or [] if isinstance(page, Mapping) else []
        type_counts: dict[str, int] = {}
        for item_index, item in enumerate(items):
            if not isinstance(item, Mapping):
                continue
            item_type = str(item.get("type") or "missing")
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
            retained = {
                "page_index": page_index,
                "item_index": item_index,
                "id": item.get("id"),
                "type": item.get("type"),
                "label": item.get("label"),
                "value": item.get("value"),
                "md": item.get("md"),
                "source": item.get("source"),
                "bbox": item.get("bbox"),
                "reading_order": item.get("reading_order"),
                "parse_concerns": item.get("parse_concerns"),
            }
            if item_type == "footer":
                footers.append(retained)
            elif item_type != "table":
                residual_items.append(retained)
        page_summaries.append(
            {
                "page_index": page_index,
                "item_count": len(items),
                "type_counts": dict(sorted(type_counts.items())),
            }
        )
    return {
        "pages": page_summaries,
        "residual_non_table_non_footer_count": len(residual_items),
        "residual_non_table_non_footer_items": residual_items,
        "footer_count": len(footers),
        "footers": footers,
    }


def _processing_timing_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    retained: dict[str, Any] = {}

    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_pointer = f"{pointer}/{key}"
                if (
                    key == "duration_ms"
                    or key == "elapsed_ms"
                    or str(key).endswith("_ms")
                ) and type(child) in (int, float):
                    retained[child_pointer] = child
                else:
                    visit(child, child_pointer)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{pointer}/{index}")

    processing = payload.get("processing")
    if isinstance(processing, Mapping):
        visit(processing, "/processing")
    return dict(sorted(retained.items()))


def _output_evidence(payload: Mapping[str, Any], markdown: str) -> dict[str, Any]:
    tables = [
        item
        for page in payload.get("pages") or []
        if isinstance(page, Mapping)
        for item in page.get("items") or []
        if isinstance(item, Mapping) and item.get("type") == "table"
    ]
    row_hashes = tuple(_sha256_json(table.get("rows") or []) for table in tables)
    table_shapes = [
        {
            "row_count": len(table.get("rows") or []),
            "column_count": max(
                (len(row) for row in table.get("rows") or [] if isinstance(row, list)),
                default=0,
            ),
            "cell_count": len(table.get("cells") or []),
            "rows_sha256": row_hash,
            "markdown_sha256": _sha256_bytes(
                str(table.get("md") or "").encode("utf-8")
            ),
        }
        for table, row_hash in zip(tables, row_hashes)
    ]
    canonical = payload.get("canonical_presentation")
    alignment_summary = _response_alignment_summary(payload)
    terminal_inventory = _terminal_output_inventory(payload)
    canonical_summary = _canonical_output_summary(canonical)
    actual_residuals = tuple(
        (
            item.get("page_index"),
            item.get("id"),
            item.get("type"),
            item.get("value"),
        )
        for item in terminal_inventory["residual_non_table_non_footer_items"]
    )
    actual_footers = tuple(
        (item.get("page_index"), item.get("id"), item.get("value"))
        for item in terminal_inventory["footers"]
    )
    actual_omission_block_ids = tuple(
        item.get("block_id")
        for item in canonical_summary.get("omitted_blocks") or []
        if item.get("omission_reason") == "source_contradicted_primary_ocr"
    )
    canonical_page_markdown_sha256 = tuple(
        item.get("full_markdown_sha256")
        for item in canonical_summary.get("pages") or []
    )
    visible_types_by_page = [
        [
            block.get("primary_element_type")
            for block in page.get("included_full_blocks") or []
        ]
        for page in canonical_summary.get("pages") or []
    ]
    semantic_projection, timing_exclusions = _semantic_projection(payload)
    checks = {
        "page_count_is_3": len(payload.get("pages") or []) == EXPECTED_PAGE_COUNT,
        "document_page_count_is_3": (
            isinstance(payload.get("document"), Mapping)
            and payload["document"].get("page_count") == EXPECTED_PAGE_COUNT
        ),
        "three_tables": len(tables) == 3,
        "all_tables_52_by_13": all(
            item["row_count"] == 52 and item["column_count"] == 13
            for item in table_shapes
        ),
        "source_grounded_row_hashes_match": row_hashes == EXPECTED_TABLE_ROW_SHA256,
        "canonical_presentation_present": isinstance(canonical, Mapping),
        "markdown_nonempty": bool(markdown.strip()),
        "source_alignment_selected": alignment_summary.get("status") == "selected",
        "source_alignment_counts_are_1775_1772_3_0": (
            alignment_summary.get("considered_count") == 1_775
            and alignment_summary.get("selected_count")
            == EXPECTED_TOTAL_SELECTED_COUNT
            and alignment_summary.get("unchanged_count") == 3
            and alignment_summary.get("unresolved_count") == 0
            and alignment_summary.get("selection_count")
            == EXPECTED_TOTAL_SELECTED_COUNT
        ),
        "selected_vector_and_canonical_omission_counts_match": (
            alignment_summary.get("terminal_reason_counts")
            == {
                "selected_vector_source_owned_table_duplicate": (
                    EXPECTED_SELECTED_VECTOR_DUPLICATE_COUNT
                ),
                "source_contradicted_primary_ocr": (
                    EXPECTED_CANONICAL_OCR_OMISSION_COUNT
                ),
            }
        ),
        "exact_seven_raw_public_residuals_retained": (
            actual_residuals == EXPECTED_TERMINAL_RESIDUALS
        ),
        "exact_three_page_footers": actual_footers == EXPECTED_TERMINAL_FOOTERS,
        "canonical_page_block_counts_are_5_4_4": (
            canonical_summary.get("page_block_counts") == [5, 4, 4]
        ),
        "canonical_has_three_table_blocks": (
            len(canonical_summary.get("table_blocks") or []) == 3
        ),
        "canonical_omits_exact_seven_source_contradictions": (
            actual_omission_block_ids == EXPECTED_CANONICAL_OMISSION_BLOCK_IDS
            and canonical_summary.get("omission_reason_counts")
            == {
                "source_contradicted_primary_ocr": (
                    EXPECTED_CANONICAL_OCR_OMISSION_COUNT
                )
            }
        ),
        "ui_visible_blocks_are_table_then_footer_per_page": (
            visible_types_by_page
            == [["table", "footer"], ["table", "footer"], ["table", "footer"]]
        ),
        "canonical_page_markdown_hashes_match": (
            canonical_page_markdown_sha256
            == EXPECTED_CANONICAL_PAGE_MARKDOWN_SHA256
        ),
        "canonical_document_markdown_hash_matches": (
            (canonical_summary.get("sections") or {}).get("full", {}).get(
                "markdown_sha256"
            )
            == EXPECTED_CANONICAL_DOCUMENT_MARKDOWN_SHA256
        ),
        "canonical_explicit_null_shape_retained": (
            (canonical_summary.get("explicit_nulls") or {}).get("count")
            == EXPECTED_CANONICAL_EXPLICIT_NULL_COUNT
        ),
    }
    return {
        "valid": all(checks.values()),
        "checks": checks,
        "raw_payload_sha256": _sha256_json(payload),
        "stable_semantic_sha256": _sha256_json(semantic_projection),
        "stable_semantic_policy": {
            "basis": "exact-payload-with-recursive-processing-timing-leaves-removed-v1",
            "scope": "/processing only",
            "excluded_key_rule": "duration_ms, elapsed_ms, or any key ending _ms",
            "excluded_pointers": timing_exclusions,
        },
        "pages_sha256": _sha256_json(payload.get("pages") or []),
        "canonical_presentation_sha256": (
            _sha256_json(canonical) if isinstance(canonical, Mapping) else None
        ),
        "markdown_sha256": _sha256_bytes(markdown.encode("utf-8")),
        "markdown_bytes": len(markdown.encode("utf-8")),
        "table_row_sha256": list(row_hashes),
        "tables": table_shapes,
        "source_text_alignment": alignment_summary,
        "terminal_output_inventory": terminal_inventory,
        "canonical_summary": canonical_summary,
        "processing_timing_values": _processing_timing_values(payload),
    }


def _table_row_hashes(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        _sha256_json(item.get("rows") or [])
        for page in payload.get("pages") or []
        if isinstance(page, Mapping)
        for item in page.get("items") or []
        if isinstance(item, Mapping) and item.get("type") == "table"
    )


def _attempt(
    *,
    client: Any,
    lane: str,
    index: int,
    source: bytes,
    output_root: Path,
    sampler: ResourceSampler,
    runtime_sha256: str,
    dependency_sha256: str,
) -> dict[str, Any]:
    from app import api
    from app.models import ParseResult
    from app.services.serializer import to_markdown
    from tests.benchmarks.latency_contracts import StageStatus
    from tests.benchmarks.latency_instrumentation import (
        DiagnosticInstrumentation,
        ExternalStageCollector,
        calibrate_observer_overhead,
        harness_file_identities,
        verify_instrumentation_manifest,
    )

    class EvidenceStageCollector(ExternalStageCollector):
        """Retain bounded rendered-request facts around the reviewed span."""

        def wrap(self, target: Any, function: Callable[..., Any]) -> Callable[..., Any]:
            if target.target_id != "pipeline-rendered-ocr":
                return super().wrap(target, function)

            @functools.wraps(function)
            def with_request_evidence(*args: Any, **kwargs: Any) -> Any:
                requests = args[1] if len(args) > 1 else kwargs.get("requests", ())
                details.record_render_plan(requests)
                result = function(*args, **kwargs)
                details.record_render_results(result)
                return result

            return super().wrap(target, with_request_evidence)

    attempt_id = f"attempt-{index:02d}-{lane}"
    attempt_dir = output_root / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=False)
    sampler.set_attempt(attempt_id)
    _write_json(attempt_dir / "host-start.json", _host_snapshot(f"{attempt_id}-start"))
    details = DetailCollector()
    collector = EvidenceStageCollector()
    observer = DiagnosticInstrumentation(collector, workspace=WORKSPACE)
    supplemental = SupplementalInstrumentation(details)
    setup_error: BaseException | None = None
    observer_close_error: BaseException | None = None
    supplemental_close_error: BaseException | None = None
    supplemental_manifest: dict[str, Any] | None = None
    response = None
    request_error: BaseException | None = None
    trace_payload: dict[str, Any] | None = None
    trace_summary: dict[str, Any] | None = None
    observer_manifest: dict[str, Any] | None = None
    attached_details: list[dict[str, Any]] = []
    request_started_ns = 0
    request_ended_ns = 0
    rusage_before: dict[str, Any] = {}
    rusage_after: dict[str, Any] = {}
    try:
        observer.install(api, allow_preloaded_pipeline=(lane == "warm"))
        supplemental.install()
    except BaseException as error:
        setup_error = error

    if setup_error is None:
        rusage_before = _rusage_snapshot()
        request_started_ns = time.perf_counter_ns()
        collector.start(started_ns=request_started_ns)
        try:
            response = client.post(
                "/v1/parse",
                params={"output_format": "json"},
                files={"file": ("ny-timetable.pdf", source, "application/pdf")},
            )
        except BaseException as error:
            request_error = error
        request_ended_ns = time.perf_counter_ns()
        rusage_after = _rusage_snapshot()
        collector.finish(finished_ns=request_ended_ns)

    try:
        if setup_error is None:
            supplemental_manifest = supplemental.close()
    except BaseException as error:
        supplemental_close_error = error
    try:
        if setup_error is None:
            observer.close()
    except BaseException as error:
        observer_close_error = error

    status = (
        StageStatus.SUCCESS
        if setup_error is None
        and request_error is None
        and response is not None
        and response.status_code == 200
        else StageStatus.ERROR
    )
    if setup_error is None:
        trace = collector.trace(
            request_started_ns=request_started_ns,
            request_ended_ns=request_ended_ns,
            status=status,
            root_failure_code=(
                None if status is StageStatus.SUCCESS else "request_failure"
            ),
        )
        trace_payload = trace.model_dump(mode="json")
        trace_summary = _summarize_trace(trace_payload)
        _write_json(attempt_dir / "stage-trace.json", trace_payload)
        _write_json(attempt_dir / "stage-summary.json", trace_summary)
        attached_details = _attach_supplemental_parents(
            details.events, trace_summary["spans"]
        )
        _write_json(
            attempt_dir / "supplemental-stage-trace.json",
            {
                "method": supplemental_manifest,
                "observer_overhead": _calibrate_detail_overhead(),
                "events": attached_details,
                "stage_aggregates": _detail_aggregates(attached_details),
                "rendered_ocr": {
                    "planned_request_count": len(details.planned_render_requests),
                    "planned_requests": details.planned_render_requests,
                    "executed_region_count": len(details.executed_render_regions),
                    "executed_regions": details.executed_render_regions,
                    "tesseract_pass_count": sum(
                        event.get("name") == "ocr.tesseract_pass"
                        for event in attached_details
                    ),
                    "tesseract_passes": [
                        event
                        for event in attached_details
                        if event.get("name") == "ocr.tesseract_pass"
                    ],
                    "content_retained": False,
                },
                "timing_policy": {
                    "inclusive_rows_are_not_additive": True,
                    "cpu_clock": "process_time_ns",
                    "cpu_scope": "whole diagnostic process, not thread-exclusive",
                    "observer_adjustment_applied": False,
                },
            },
        )
        try:
            manifest = observer.build_manifest(
                harness_files=harness_file_identities(WORKSPACE),
                runtime_sha256=runtime_sha256,
                dependency_lock_sha256=dependency_sha256,
                overhead=calibrate_observer_overhead(),
            )
            verify_instrumentation_manifest(manifest, workspace=WORKSPACE)
            observer_manifest = manifest.model_dump(mode="json")
            observer_manifest["verified_against_final_source"] = True
            _write_json(attempt_dir / "observer-manifest.json", observer_manifest)
        except BaseException as error:
            _write_text(
                attempt_dir / "observer-manifest-error.txt",
                "".join(traceback.format_exception(error)),
            )

    response_evidence = None
    validation_error: BaseException | None = None
    if response is not None:
        _atomic_write(attempt_dir / "response.json", bytes(response.content))
        try:
            payload = json.loads(response.content)
            validated = ParseResult.model_validate(payload)
            markdown_started_ns = time.perf_counter_ns()
            markdown = to_markdown(validated)
            markdown_ended_ns = time.perf_counter_ns()
            _write_text(attempt_dir / "response.md", markdown)
            response_evidence = _output_evidence(payload, markdown)
            response_evidence["http_status"] = response.status_code
            response_evidence["content_type"] = response.headers.get("content-type")
            response_evidence["response_bytes"] = len(response.content)
            response_evidence["post_response_markdown_validation_ns"] = (
                markdown_ended_ns - markdown_started_ns
            )
            response_evidence["processing_duration_ms"] = (
                payload.get("processing", {}).get("duration_ms")
                if isinstance(payload.get("processing"), Mapping)
                else None
            )
        except BaseException as error:
            validation_error = error

    omission_apply_events = [
        event
        for event in details.canonical_ocr_omission_events
        if event.get("name") == "canonical_ocr_omission.apply"
    ]
    omission_replay_events = [
        event
        for event in details.canonical_ocr_omission_events
        if event.get("name") == "canonical_ocr_omission.replay_validation"
    ]
    omission_terminal_commit_events = [
        event
        for event in attached_details
        if event.get("name") == "canonical_ocr_omission.terminal_commit"
    ]
    omission_instrumentation_checks = {
        "exactly_one_terminal_commit_call": len(
            omission_terminal_commit_events
        )
        == 1,
        "terminal_commit_succeeded": all(
            event.get("status") == "success"
            for event in omission_terminal_commit_events
        ),
        "exactly_two_apply_calls_live_and_replay": len(omission_apply_events) == 2,
        "exactly_one_independent_replay_validation": len(omission_replay_events)
        == 1,
        "all_captures_succeeded": all(
            event.get("pre_capture_error") is None
            and event.get("capture_error") is None
            and isinstance(event.get("summary"), Mapping)
            for event in details.canonical_ocr_omission_events
        ),
        "every_apply_selected_exact_seven": all(
            ((event.get("summary") or {}).get("output_summary") or {}).get(
                "canonical_ocr_omission_count"
            )
            == EXPECTED_CANONICAL_OCR_OMISSION_COUNT
            for event in omission_apply_events
        ),
        "every_apply_input_public_and_ir_unchanged": all(
            (event.get("summary") or {}).get("input_state_unchanged") is True
            and (event.get("summary") or {}).get("output_pages_same_object") is True
            for event in omission_apply_events
        ),
        "every_apply_within_two_second_budget": all(
            0 < int(event.get("function_wall_ns") or 0) < 2_000_000_000
            for event in omission_apply_events
        ),
        "independent_replay_true": all(
            (event.get("summary") or {}).get("result") is True
            for event in omission_replay_events
        ),
        "independent_replay_within_two_seconds": all(
            0 < int(event.get("function_wall_ns") or 0) < 2_000_000_000
            for event in omission_replay_events
        ),
        "replay_input_public_and_ir_unchanged": all(
            (event.get("summary") or {}).get("input_state_unchanged") is True
            for event in omission_replay_events
        ),
    }
    omission_instrumentation = {
        "valid": all(omission_instrumentation_checks.values()),
        "checks": omission_instrumentation_checks,
        "event_count": len(details.canonical_ocr_omission_events),
        "apply_count": len(omission_apply_events),
        "replay_validation_count": len(omission_replay_events),
        "terminal_commit_count": len(omission_terminal_commit_events),
        "terminal_commit_events": omission_terminal_commit_events,
        "events": details.canonical_ocr_omission_events,
    }
    if isinstance(response_evidence, dict):
        response_evidence["canonical_ocr_omission_instrumentation"] = (
            omission_instrumentation
        )
        response_evidence["checks"][
            "canonical_ocr_omission_instrumentation_closed"
        ] = omission_instrumentation["valid"]
        response_evidence["valid"] = all(response_evidence["checks"].values())

    visual_recovery_events = [
        event
        for event in attached_details
        if event.get("name") == "visual.recover_pdf_visual_source_text"
    ]
    tesseract_events = [
        event
        for event in attached_details
        if event.get("name") == "ocr.tesseract_pass"
    ]
    _write_json(
        attempt_dir / "terminal-evidence.json",
        {
            "schema_id": "ny-timetable-terminal-evidence-v2",
            "attempt_id": attempt_id,
            "capture_policy": {
                "production_source_modified": False,
                "diagnostic_wrappers_fail_open": True,
                "authority_content_retained": False,
                "authority_hashes_and_shape_retained": True,
                "alignment_full_report_location": "response.json",
            },
            "rendered_ocr": {
                "planned_request_count": len(details.planned_render_requests),
                "planned_requests": details.planned_render_requests,
                "executed_region_count": len(details.executed_render_regions),
                "executed_regions": details.executed_render_regions,
                "tesseract_pass_count": len(tesseract_events),
                "tesseract_passes": tesseract_events,
            },
            "visual_source_recovery": {
                "call_count": len(visual_recovery_events),
                "inclusive_wall_ns": sum(
                    int(event.get("inclusive_wall_ns") or 0)
                    for event in visual_recovery_events
                ),
                "inclusive_process_cpu_ns": sum(
                    int(event.get("inclusive_process_cpu_ns") or 0)
                    for event in visual_recovery_events
                ),
                "success_count": sum(
                    event.get("status") == "success"
                    for event in visual_recovery_events
                ),
                "timeout_count": sum(
                    event.get("status") == "timeout"
                    for event in visual_recovery_events
                ),
                "error_count": sum(
                    event.get("status") == "error"
                    for event in visual_recovery_events
                ),
            },
            "selected_vector_authorities": details.vector_authority_events,
            "selected_vector_binder_traces": details.binder_trace_events,
            "source_alignment_calls": details.alignment_events,
            "canonical_ocr_omission": omission_instrumentation,
            "terminal_validations": details.validation_events,
            "running_region_replay": details.running_region_events,
            "response_evidence": (
                {
                    "source_text_alignment": response_evidence.get(
                        "source_text_alignment"
                    ),
                    "terminal_output_inventory": response_evidence.get(
                        "terminal_output_inventory"
                    ),
                    "tables": response_evidence.get("tables"),
                    "canonical_summary": response_evidence.get(
                        "canonical_summary"
                    ),
                    "processing_timing_values": response_evidence.get(
                        "processing_timing_values"
                    ),
                }
                if isinstance(response_evidence, Mapping)
                else None
            ),
        },
    )

    errors = {
        name: (
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": "".join(traceback.format_exception(error)),
            }
            if error is not None
            else None
        )
        for name, error in (
            ("setup", setup_error),
            ("request", request_error),
            ("supplemental_close", supplemental_close_error),
            ("observer_close", observer_close_error),
            ("validation", validation_error),
        )
    }
    success = (
        status is StageStatus.SUCCESS
        and response_evidence is not None
        and response_evidence["valid"]
        and trace_summary is not None
        and trace_summary["closure"]["valid"]
        and not any(errors.values())
    )
    attempt = {
        "schema_id": SCHEMA_ID,
        "attempt_id": attempt_id,
        "lane": lane,
        "no_retry": True,
        "success": success,
        "started_monotonic_ns": request_started_ns or None,
        "ended_monotonic_ns": request_ended_ns or None,
        "request_wall_ns": (
            request_ended_ns - request_started_ns if request_started_ns else None
        ),
        "request_resource_delta": (
            _rusage_delta(rusage_before, rusage_after) if rusage_before else None
        ),
        "response_evidence": response_evidence,
        "timing_closure": trace_summary.get("closure") if trace_summary else None,
        "observer_manifest_sha256": (
            observer_manifest.get("manifest_sha256") if observer_manifest else None
        ),
        "errors": errors,
    }
    _write_json(attempt_dir / "attempt.json", attempt)
    _write_json(attempt_dir / "host-end.json", _host_snapshot(f"{attempt_id}-end"))
    return attempt


def _artifact_manifest(root: Path) -> dict[str, Any]:
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.json":
            records.append(_file_identity(path, relative_to=root))
    return {
        "schema_id": "ny-timetable-diagnostic-artifact-manifest-v1",
        "generated_at": _utc_now(),
        "artifact_count": len(records),
        "artifacts": records,
        "aggregate_sha256": _sha256_json(records),
    }


def _report(
    attempts: list[Mapping[str, Any]], comparison: Mapping[str, Any], mutation: Mapping[str, Any]
) -> str:
    lines = [
        "# NY timetable cold/warm stage diagnostic",
        "",
        "This is diagnostic evidence only. The worker was process-isolated and used the real in-process ASGI application, but the host was not exclusive or quiet. It did not contact ports 8042/8043/3000/3002 and did not open a listener.",
        "",
        "The production P04 limits remained 5.000 seconds per document and 0.500 seconds per page; the isolated canonical OCR omission limit remained 2.000 seconds. No production setting or application source file was edited by the run.",
        "",
        "## Evidence scope",
        "",
        "The original observation is limited to the frontend development log line `POST /api/parse?output_format=json 200 in 315.9s`. That event has no retained response body, stage trace, request timestamp, or code/configuration fingerprint. This controlled run is a current-tree reproduction. A matching stage shape is consistent with an explanation for the earlier event, but cannot prove its root cause retroactively.",
        "",
        "## Attempts",
        "",
        "| Lane | Status | Wall seconds | CPU seconds | processing.duration_ms | Stable output |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for attempt in attempts:
        response = attempt.get("response_evidence") or {}
        resource_delta = attempt.get("request_resource_delta") or {}
        lines.append(
            "| {lane} | {status} | {wall:.3f} | {cpu:.3f} | {processing} | `{digest}` |".format(
                lane=attempt.get("lane"),
                status="success" if attempt.get("success") else "failed",
                wall=float(attempt.get("request_wall_ns") or 0) / 1e9,
                cpu=float(resource_delta.get("total_cpu_ns") or 0) / 1e9,
                processing=response.get("processing_duration_ms"),
                digest=response.get("stable_semantic_sha256") or "missing",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation boundaries",
            "",
            "- `processing.duration_ms` starts inside `_parse_loaded_document`; it excludes input loading and the outer API/request path and ends before visual semantics, shared-IR projection, canonical construction, terminal alignment/authority, and final response serialization.",
            "- Stage spans are nested. Inclusive stage durations must not be summed. `stage-summary.json` closes the request using the disjoint top-level union plus an explicit residual and gives direct-child-subtracted exclusive values.",
            "- Canonical OCR omission records separate the production function wall from diagnostic pre/post hashing. The enclosing terminal-commit span includes that observer overhead; `pre_capture_wall_ns` and `capture_wall_ns` are retained and never subtracted silently.",
            "- Request CPU includes worker self plus reaped child CPU. Stage supplemental CPU uses the process clock and is not thread-exclusive. Observer overhead is recorded and never subtracted.",
            "- The host retained other applications and both local backend/UI pairs, so this run can identify where this request spent time but cannot establish a clean production latency baseline from one pair.",
            "- The shared latency observer has a repository-wide contract drift for the Office-only `_parse_document_without_stage_telemetry` `ParseResult.model_validate` caller. That branch is unreachable for this PDF. NY attribution remains conditional on the retained invocation counts, parentage, and exact timing closure.",
            "",
            "## Pair comparison",
            "",
            f"- Stable semantic output equal: `{comparison.get('stable_semantic_equal')}`",
            f"- Table row identities equal: `{comparison.get('table_rows_equal')}`",
            f"- Canonical identities equal: `{comparison.get('canonical_equal')}`",
            f"- Cold/warm wall ratio: `{comparison.get('cold_to_warm_wall_ratio')}`",
            "",
            "## Mutation audit",
            "",
            f"- `app/` unchanged: `{mutation.get('app_tree_unchanged')}`",
            f"- `.models/` path/size/mtime inventory unchanged: `{mutation.get('model_tree_stat_unchanged')}`",
            f"- Pre-run app aggregate: `{mutation.get('app_before_sha256')}`",
            f"- Post-run app aggregate: `{mutation.get('app_after_sha256')}`",
            "",
            "See each attempt's `stage-summary.json`, `stage-trace.json`, `supplemental-stage-trace.json`, `observer-manifest.json`, `response.json`, and `host-*.json`; continuous resource evidence is in `resource-samples.ndjson`.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    startup_observer_state = {
        "sys_trace_present": sys.gettrace() is not None,
        "sys_profile_present": sys.getprofile() is not None,
    }
    if any(startup_observer_state.values()):
        raise RuntimeError(
            "production-equivalent diagnostic requires tracing and profiling "
            "to be disabled at startup"
        )
    output_root = Path(args.output_dir).resolve()
    if output_root.exists():
        raise FileExistsError("output directory already exists")
    output_root.mkdir(parents=True)
    source_path = Path(args.source).resolve()
    profile_path = Path(args.profile_script).resolve()
    harness_path = Path(__file__).resolve()
    source = source_path.read_bytes()
    source_sha = _sha256_bytes(source)
    if source_sha != EXPECTED_SOURCE_SHA256 or len(source) != EXPECTED_SOURCE_BYTES:
        raise ValueError("NY source identity differs from reviewed fixture")
    baseline_bytes = FIDELITY_BASELINE.read_bytes()
    if (
        _sha256_bytes(baseline_bytes) != EXPECTED_FIDELITY_BASELINE_SHA256
        or len(baseline_bytes) != EXPECTED_FIDELITY_BASELINE_BYTES
    ):
        raise ValueError("retained NY fidelity baseline identity differs")
    baseline_payload = json.loads(baseline_bytes)
    baseline_row_hashes = _table_row_hashes(baseline_payload)
    if baseline_row_hashes != EXPECTED_TABLE_ROW_SHA256:
        raise ValueError("retained NY fidelity baseline row identities differ")
    predecessor_bootstrap = (
        Path(args.predecessor_bootstrap_failure).resolve()
        if args.predecessor_bootstrap_failure
        else None
    )
    predecessor_bootstrap_identity = (
        _file_identity(predecessor_bootstrap)
        if predecessor_bootstrap is not None
        else None
    )
    predecessor_traced_e2e_manifest = (
        Path(args.predecessor_traced_e2e_manifest).resolve()
        if args.predecessor_traced_e2e_manifest
        else None
    )
    predecessor_traced_e2e_identity = (
        _file_identity(predecessor_traced_e2e_manifest)
        if predecessor_traced_e2e_manifest is not None
        else None
    )
    planned_attempts = ["cold"] if args.cold_only else ["cold", "warm"]

    started_at = _utc_now()
    profile_exports = _load_profile(profile_path)
    source_before = _file_identity(source_path)
    profile_before = _file_identity(profile_path)
    harness_before = _file_identity(harness_path)
    app_before = _app_tree_identity()
    model_stat_before = _tree_stat_identity(WORKSPACE / ".models")
    initial_host = _host_snapshot("pre-run")
    _write_json(output_root / "host-pre.json", initial_host)
    _write_text(output_root / "profile-script.txt", profile_path.read_text(encoding="utf-8"))
    selected_files = (
        source_path,
        profile_path,
        WORKSPACE / "app/config.py",
        WORKSPACE / "app/api.py",
        WORKSPACE / "app/models.py",
        WORKSPACE / "app/services/pipeline.py",
        WORKSPACE / "app/services/table_semantics.py",
        WORKSPACE / "app/services/source_text_alignment.py",
        WORKSPACE / "app/services/canonical_ocr_omission.py",
        WORKSPACE / "app/services/presentation.py",
        WORKSPACE / "app/services/running_regions.py",
        WORKSPACE / "app/services/serializer.py",
        WORKSPACE / "tests/benchmarks/latency_contracts.py",
        WORKSPACE / "tests/benchmarks/latency_instrumentation.py",
        harness_path,
        WORKSPACE / "pyproject.toml",
        WORKSPACE / "uv.lock",
        FIDELITY_BASELINE,
    )
    protected_paths = [
        source_path,
        profile_path,
        harness_path,
        WORKSPACE / "pyproject.toml",
        WORKSPACE / "uv.lock",
    ]
    frontend_vars = WORKSPACE / "frontend/.dev.vars"
    if frontend_vars.is_file():
        protected_paths.append(frontend_vars)
    protected_before = {
        _file_identity(path)["path"]: _file_identity(path)
        for path in protected_paths
    }
    package_versions = {}
    for name in PACKAGE_NAMES:
        try:
            package_versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            package_versions[name] = None
    identity = {
        "schema_id": SCHEMA_ID,
        "classification": "diagnostic-only-non-release-non-closure",
        "started_at": started_at,
        "workspace": str(WORKSPACE),
        "command": [sys.executable, *sys.argv],
        "worker": {
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "python": sys.version,
            "executable": str(Path(sys.executable).resolve()),
            "platform": platform.platform(),
        },
        "runtime_observers_at_startup": startup_observer_state,
        "execution_lane": {
            "process_isolated": True,
            "host_exclusive": False,
            "transport": "in-process FastAPI TestClient; no TCP listener",
            "live_service_targeted": False,
            "ports_touched": [],
            "attempts": planned_attempts,
            "retry_policy": "none",
            "network_policy": "offline environment flags; no OS-level denial claimed",
        },
        "source": source_before,
        "fidelity_baseline": {
            **_file_identity(FIDELITY_BASELINE),
            "classification": "retained-prior-source-grounded-fidelity-evidence",
            "table_row_sha256_derived_at_runtime": list(baseline_row_hashes),
            "is_original_uncaptured_315_9_second_response": False,
        },
        "predecessor_bootstrap_failure": (
            {
                **predecessor_bootstrap_identity,
                "relationship": (
                    "replacement after evidence-capture failure; not a parse retry"
                ),
            }
            if predecessor_bootstrap_identity is not None
            else None
        ),
        "predecessor_traced_e2e_manifest": (
            {
                **predecessor_traced_e2e_identity,
                "relationship": (
                    "replacement after in-deadline diagnostic line tracing "
                    "invalidated production-equivalent binder timing; not a "
                    "parse retry"
                ),
            }
            if predecessor_traced_e2e_identity is not None
            else None
        ),
        "profile": {
            "script": profile_before,
            "applied_exports": profile_exports,
        },
        "selected_files": [_file_identity(path) for path in selected_files],
        "protected_files_before": protected_before,
        "app_tree_before": app_before,
        "model_tree_stat_before": model_stat_before,
        "package_versions": package_versions,
        "production_budgets": {
            "p04_document_seconds": 5.0,
            "p04_page_seconds": 0.5,
            "canonical_ocr_omission_seconds": 2.0,
            "budget_override_applied": False,
            "document_timeout_seconds_expected": 300.0,
            "sources": [
                "app/services/table_semantics.py:192-242",
                "app/services/canonical_ocr_omission.py",
            ],
        },
        "observer_contract_limitations": {
            "global_contract_green": False,
            "failing_test": "tests/performance/test_latency_instrumentation_adversarial.py::test_real_parse_result_callers_are_exhaustively_routed",
            "extra_caller": "app.services.pipeline._parse_document_without_stage_telemetry",
            "caller_location": "resolved by qualname; numeric source lines are intentionally not sealed",
            "ny_pdf_reachable": False,
            "impact": "global release observer contract red; Office-only result-validation cardinality drift does not omit NY PDF Docling/shared/visual/IR/canonical stages",
        },
    }
    _write_json(output_root / "identity.json", identity)
    runtime_sha256 = _sha256_json(
        {
            "python": identity["worker"],
            "packages": package_versions,
            "profile": profile_exports,
        }
    )
    dependency_sha256 = _sha256_json(
        [_file_identity(WORKSPACE / name) for name in ("pyproject.toml", "uv.lock")]
    )

    sampler = ResourceSampler(output_root / "resource-samples.ndjson")
    sampler.start()
    attempts: list[dict[str, Any]] = []
    try:
        # Imports happen only after profile application and identity capture.
        from fastapi.testclient import TestClient
        from app.config import get_settings
        from app.main import app

        settings = get_settings()
        settings_payload = asdict(settings)
        _write_json(
            output_root / "effective-settings.json",
            {
                "settings": settings_payload,
                "settings_sha256": _sha256_json(settings_payload),
                "document_timeout_seconds": settings.document_timeout_seconds,
                "table_budget_override_applied": False,
            },
        )
        if settings.document_timeout_seconds != 300.0:
            raise ValueError("diagnostic profile changed production document timeout")
        with TestClient(app) as client:
            attempts.append(
                _attempt(
                    client=client,
                    lane="cold",
                    index=1,
                    source=source,
                    output_root=output_root,
                    sampler=sampler,
                    runtime_sha256=runtime_sha256,
                    dependency_sha256=dependency_sha256,
                )
            )
            if not args.cold_only:
                attempts.append(
                    _attempt(
                        client=client,
                        lane="warm",
                        index=2,
                        source=source,
                        output_root=output_root,
                        sampler=sampler,
                        runtime_sha256=runtime_sha256,
                        dependency_sha256=dependency_sha256,
                    )
                )
    finally:
        sampler.set_attempt("post-run")
        sampler.stop()

    cold = attempts[0].get("response_evidence") or {}
    pair_available = len(attempts) == 2
    warm = attempts[1].get("response_evidence") or {} if pair_available else {}
    cold_wall = int(attempts[0].get("request_wall_ns") or 0)
    warm_wall = (
        int(attempts[1].get("request_wall_ns") or 0)
        if pair_available
        else None
    )
    comparison = {
        "stable_semantic_equal": (
            bool(cold.get("stable_semantic_sha256"))
            and cold.get("stable_semantic_sha256") == warm.get("stable_semantic_sha256")
        ) if pair_available else None,
        "table_rows_equal": (
            bool(cold.get("table_row_sha256"))
            and cold.get("table_row_sha256") == warm.get("table_row_sha256")
        ) if pair_available else None,
        "canonical_equal": (
            bool(cold.get("canonical_presentation_sha256"))
            and cold.get("canonical_presentation_sha256")
            == warm.get("canonical_presentation_sha256")
        ) if pair_available else None,
        "cold_wall_ns": cold_wall,
        "warm_wall_ns": warm_wall,
        "cold_to_warm_wall_ratio": (
            round(cold_wall / warm_wall, 6) if warm_wall else None
        ),
        "attempt_count": len(attempts),
        "retry_count": 0,
    }
    _write_json(output_root / "cold-warm-comparison.json", comparison)

    app_after = _app_tree_identity()
    source_after = _file_identity(source_path)
    profile_after = _file_identity(profile_path)
    harness_after = _file_identity(harness_path)
    model_stat_after = _tree_stat_identity(WORKSPACE / ".models")
    protected_after = {
        _file_identity(path)["path"]: _file_identity(path)
        for path in protected_paths
    }
    try:
        from tests.benchmarks.latency_runner import derive_model_artifacts_sha256

        model_artifacts_sha256_post = derive_model_artifacts_sha256(WORKSPACE)
        model_artifacts_identity_error = None
    except BaseException as error:
        model_artifacts_sha256_post = None
        model_artifacts_identity_error = type(error).__name__
    mutation = {
        "app_tree_unchanged": app_before["aggregate_sha256"]
        == app_after["aggregate_sha256"],
        "app_before_sha256": app_before["aggregate_sha256"],
        "app_after_sha256": app_after["aggregate_sha256"],
        "app_before_file_count": app_before["file_count"],
        "app_after_file_count": app_after["file_count"],
        "source_unchanged": source_before == source_after,
        "source_before": source_before,
        "source_after": source_after,
        "profile_unchanged": profile_before == profile_after,
        "profile_before": profile_before,
        "profile_after": profile_after,
        "diagnostic_harness_unchanged": harness_before == harness_after,
        "diagnostic_harness_before": harness_before,
        "diagnostic_harness_after": harness_after,
        "model_tree_stat_unchanged": model_stat_before["aggregate_sha256"]
        == model_stat_after["aggregate_sha256"],
        "model_before_stat_sha256": model_stat_before["aggregate_sha256"],
        "model_after_stat_sha256": model_stat_after["aggregate_sha256"],
        "model_artifacts_sha256_post": model_artifacts_sha256_post,
        "model_artifacts_identity_error": model_artifacts_identity_error,
        "protected_files_unchanged": protected_before == protected_after,
        "protected_files_before": protected_before,
        "protected_files_after": protected_after,
        "authored_harness": harness_after,
        "generated_artifact_root": str(output_root),
        "production_app_files_written_by_harness": [],
    }
    _write_json(output_root / "mutation-audit.json", mutation)
    _write_json(output_root / "host-post.json", _host_snapshot("post-run"))
    _write_text(output_root / "report.md", _report(attempts, comparison, mutation))
    _write_json(output_root / "artifact-manifest.json", _artifact_manifest(output_root))
    return 0 if all(attempt.get("success") for attempt in attempts) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default=str(WORKSPACE / "benchmark-expertmodeldata/ny-timetable.pdf"),
    )
    parser.add_argument(
        "--profile-script",
        default=str(WORKSPACE / "start-ui-backend-8042.sh"),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--predecessor-bootstrap-failure")
    parser.add_argument("--predecessor-traced-e2e-manifest")
    parser.add_argument(
        "--cold-only",
        action="store_true",
        help="issue one cold request only for a scoped failure diagnostic",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
