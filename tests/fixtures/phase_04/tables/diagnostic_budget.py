"""Process-local P04 document-budget override for diagnostic test runs only.

This module deliberately lives under ``tests``.  Importing it has no effect;
callers must enter :func:`diagnostic_table_document_budget` explicitly in an
isolated diagnostic process.  It does not add a Settings field, environment
variable, API parameter, or persistent production feature flag.

The override changes both P04 document-deadline enforcement points while it is
active.  It intentionally leaves the independently governed 500 ms page limit
unchanged.  Elevated-budget output is diagnostic and cannot be used as release
or closure evidence for the production five-second contract.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from math import isfinite
import threading
from time import perf_counter as diagnostic_perf_counter
from typing import Any, Callable, Iterator, Mapping


PRODUCTION_DOCUMENT_SECONDS = 5.0
DIAGNOSTIC_MAX_DOCUMENT_SECONDS = 30.0
DIAGNOSTIC_CLASSIFICATION = "diagnostic_non_closure"
DIAGNOSTIC_TIMING_RECORD_LIMIT = 4_096

_ACTIVATION_LOCK = threading.Lock()
_TIMING_LOCK = threading.Lock()


def _validated_document_seconds(value: object) -> float:
    if type(value) not in (int, float):
        raise TypeError("diagnostic table document budget must be numeric")
    seconds = float(value)
    if (
        not isfinite(seconds)
        or seconds < PRODUCTION_DOCUMENT_SECONDS
        or seconds > DIAGNOSTIC_MAX_DOCUMENT_SECONDS
    ):
        raise ValueError("diagnostic table document budget is out of bounds")
    return seconds


@contextmanager
def diagnostic_table_document_budget(seconds: object) -> Iterator[dict[str, object]]:
    """Temporarily widen P04's document clock in one isolated test process.

    The global patch is guarded and non-reentrant because the production
    deadline functions are module globals.  The context always restores their
    exact identities, including when parsing or an assertion raises.
    """

    budget_seconds = _validated_document_seconds(seconds)
    if not _ACTIVATION_LOCK.acquire(blocking=False):
        raise RuntimeError("diagnostic table document budget is already active")

    from app.services import pipeline, table_semantics

    original_deadline = table_semantics.table_span_fidelity_document_deadline
    original_resolver = table_semantics._resolve_table_document_deadline
    original_repair_extractor = pipeline._extract_table_repair_words

    def diagnostic_deadline() -> float:
        return table_semantics.perf_counter() + budget_seconds

    def diagnostic_resolver(value: object) -> float:
        now = table_semantics.perf_counter()
        if value is None:
            return now + budget_seconds
        if (
            type(value) not in (int, float)
            or type(value) is bool
            or not isfinite(float(value))
            or float(value) > now + budget_seconds
        ):
            raise ValueError("diagnostic table document deadline differs")
        if float(value) <= now:
            raise TimeoutError("table operation deadline exceeded")
        return float(value)

    def diagnostic_repair_extractor(
        pdf_bytes: bytes,
        raw: object,
        *,
        table_span_fidelity_enabled: bool = False,
        table_span_fidelity_document_deadline: float | None = None,
        table_span_fidelity_page_deadlines: dict[int, float] | None = None,
    ) -> dict[int, list[dict[str, object]]]:
        local_deadline = table_span_fidelity_document_deadline
        if table_span_fidelity_enabled and local_deadline is not None:
            # Word repair retains its production-owned five-second local cap;
            # only the outer cumulative P04 document clock is diagnostic.
            diagnostic_resolver(local_deadline)
            local_deadline = min(
                float(local_deadline),
                pipeline.time.perf_counter() + PRODUCTION_DOCUMENT_SECONDS,
            )
        return original_repair_extractor(
            pdf_bytes,
            raw,
            table_span_fidelity_enabled=table_span_fidelity_enabled,
            table_span_fidelity_document_deadline=local_deadline,
            table_span_fidelity_page_deadlines=(
                table_span_fidelity_page_deadlines
            ),
        )

    activation: dict[str, object] = {
        "schema_version": "1.0",
        "policy_id": "p04-diagnostic-document-budget-v1",
        "classification": DIAGNOSTIC_CLASSIFICATION,
        "production_document_seconds": PRODUCTION_DOCUMENT_SECONDS,
        "diagnostic_document_seconds": budget_seconds,
        "page_seconds": 0.5,
        "public_request_control": False,
        "closure_evidence": False,
    }
    try:
        table_semantics.table_span_fidelity_document_deadline = diagnostic_deadline
        table_semantics._resolve_table_document_deadline = diagnostic_resolver
        pipeline._extract_table_repair_words = diagnostic_repair_extractor
        yield activation
    finally:
        table_semantics.table_span_fidelity_document_deadline = original_deadline
        table_semantics._resolve_table_document_deadline = original_resolver
        pipeline._extract_table_repair_words = original_repair_extractor
        _ACTIVATION_LOCK.release()


@contextmanager
def capture_p04_diagnostic_timings() -> Iterator[list[dict[str, object]]]:
    """Capture observational P04 stage timings outside the public result.

    Timings are diagnostic rather than performance-gate evidence: wrappers add
    small overhead and nested stage durations overlap.  Exact production
    callable identities are restored on every exit path.
    """

    if not _TIMING_LOCK.acquire(blocking=False):
        raise RuntimeError("P04 diagnostic stage timing is already active")

    from app.services import (
        ir,
        opaque_group_custody,
        pipeline,
        presentation,
        table_semantics,
    )

    targets: tuple[tuple[str, object, str], ...] = (
        (
            "pipeline.partitioned_table_repair_words",
            pipeline,
            "_extract_partitioned_table_repair_words",
        ),
        ("pipeline.normalize_docling_body", pipeline, "_normalize_docling_body"),
        ("pipeline.docling_table_item", pipeline, "_docling_table_item"),
        ("pipeline.shared_page_analysis", pipeline, "_analyze_shared_pages"),
        (
            "pipeline.table_custody_document_segment",
            pipeline,
            "_run_table_custody_document_segment",
        ),
        (
            "pipeline.terminal_table_authority",
            pipeline,
            "_apply_terminal_table_authority",
        ),
        (
            "pipeline.shared_ir_compatibility_projection",
            pipeline,
            "_apply_shared_ir_compatibility_projection",
        ),
        (
            "pipeline.terminal_source_text_alignment",
            pipeline,
            "_apply_terminal_source_text_alignment",
        ),
        (
            "pipeline.terminal_table_canonical_splice",
            pipeline,
            "_splice_terminal_table_canonical",
        ),
        (
            "pipeline.terminal_non_target_visual_overlay_rebind",
            pipeline,
            "_rebind_terminal_non_target_visual_overlay",
        ),
        ("table.seal_pages", table_semantics, "seal_table_pages"),
        (
            "table.orchestrate_docling_projection",
            table_semantics,
            "_orchestrate_docling_table_projection",
        ),
        ("table.finalize_pages", table_semantics, "finalize_table_pages"),
        (
            "table.detach_overlays",
            table_semantics,
            "detach_table_overlays_for_phase03",
        ),
        (
            "table.rebind_overlays",
            table_semantics,
            "rebind_table_overlays_after_phase03",
        ),
        (
            "custody.capture_opaque_edges",
            opaque_group_custody,
            "capture_opaque_group_edges",
        ),
        (
            "custody.seal_diagnostic",
            opaque_group_custody,
            "seal_diagnostic_custody",
        ),
        ("ir.build_document", ir, "build_document_ir"),
        (
            "presentation.build_canonical",
            presentation,
            "build_canonical_presentation",
        ),
    )
    records: list[dict[str, object]] = []
    originals: list[tuple[object, str, Callable[..., Any]]] = []

    def append_record(record: dict[str, object]) -> None:
        if len(records) < DIAGNOSTIC_TIMING_RECORD_LIMIT:
            record["sequence"] = len(records)
            records.append(record)
            return
        if (
            records
            and records[-1].get("stage") == "diagnostic.record_limit"
        ):
            return
        records[-1] = {
            "sequence": DIAGNOSTIC_TIMING_RECORD_LIMIT - 1,
            "stage": "diagnostic.record_limit",
            "status": "truncated",
            "elapsed_ms": 0.0,
        }

    def bounded_error(failure: BaseException) -> str:
        value = " ".join(str(failure).split())
        encoded = value.encode("utf-8", errors="replace")[:512]
        return encoded.decode("utf-8", errors="ignore")

    def state_projection(value: object) -> dict[str, object]:
        if type(value) is not dict:
            return {}
        state = value
        projected: dict[str, object] = {}
        for key in (
            "timed_out",
            "span_fidelity_disabled",
            "span_fidelity_failure_reason",
            "custody_rejected",
        ):
            member = state.get(key)
            if type(member) in (bool, str, int, float) and not isinstance(
                member, complex
            ):
                projected[key] = member
        validated = state.get("_p04_validated_parse_result")
        if validated is not None:
            projected["validated_parse_result_type"] = type(validated).__name__
        return projected

    def timed(stage: str, function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            started = diagnostic_perf_counter()
            status = "ok"
            error_message: str | None = None
            try:
                return function(*args, **kwargs)
            except BaseException as failure:
                status = f"error:{type(failure).__name__}"
                error_message = bounded_error(failure)
                raise
            finally:
                record: dict[str, object] = {
                    "stage": stage,
                    "status": status,
                    "elapsed_ms": max(
                        (diagnostic_perf_counter() - started) * 1000.0,
                        0.0,
                    ),
                }
                if error_message:
                    record["error"] = error_message
                if stage == "pipeline.table_custody_document_segment":
                    operation = args[3] if len(args) > 3 else None
                    record["operation"] = str(
                        getattr(operation, "__qualname__", type(operation).__name__)
                    )[:256]
                    state = args[2] if len(args) > 2 else None
                    record["state_after"] = state_projection(state)
                    if args and type(args[0]) in (int, float):
                        record["passed_document_deadline"] = float(args[0])
                        record["remaining_ms_at_start"] = (
                            float(args[0]) - started
                        ) * 1000.0
                    if len(args) > 1 and type(args[1]) is dict:
                        record["page_deadline_count"] = len(args[1])
                elif stage == "pipeline.terminal_table_authority":
                    state = kwargs.get("state")
                    record["state_after"] = state_projection(state)
                elif stage in {
                    "pipeline.docling_table_item",
                    "table.orchestrate_docling_projection",
                }:
                    raw_item = args[0] if args else None
                    if isinstance(raw_item, Mapping):
                        provenance = raw_item.get("prov")
                        if (
                            type(provenance) is list
                            and provenance
                            and isinstance(provenance[0], Mapping)
                            and type(provenance[0].get("page_no")) is int
                        ):
                            record["source_page_index"] = provenance[0]["page_no"]
                    page_deadline = kwargs.get("table_span_fidelity_deadline")
                    document_deadline = kwargs.get(
                        "table_span_fidelity_document_deadline"
                    )
                    if type(page_deadline) in (int, float):
                        record["passed_page_deadline"] = float(page_deadline)
                        record["page_remaining_ms_at_start"] = (
                            float(page_deadline) - started
                        ) * 1000.0
                    if type(document_deadline) in (int, float):
                        record["passed_document_deadline"] = float(
                            document_deadline
                        )
                        record["document_remaining_ms_at_start"] = (
                            float(document_deadline) - started
                        ) * 1000.0
                append_record(record)

        return wrapper

    try:
        for stage, module, attribute in targets:
            function = getattr(module, attribute)
            if not callable(function):
                raise TypeError("P04 diagnostic timing target is not callable")
            originals.append((module, attribute, function))
            setattr(module, attribute, timed(stage, function))

        finish_attribute = "_finish_table_span_fidelity_budget"
        finish_function = getattr(pipeline, finish_attribute)
        originals.append((pipeline, finish_attribute, finish_function))

        @wraps(finish_function)
        def finish_wrapper(state: object) -> Any:
            append_record(
                {
                    "stage": "pipeline.table_budget_pre_cleanup_state",
                    "status": "observed",
                    "elapsed_ms": 0.0,
                    "state": state_projection(state),
                }
            )
            return finish_function(state)

        setattr(pipeline, finish_attribute, finish_wrapper)
        yield records
    finally:
        for module, attribute, function in reversed(originals):
            setattr(module, attribute, function)
        _TIMING_LOCK.release()
