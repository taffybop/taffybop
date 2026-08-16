"""External-only, request-scoped stage observer for LAT-US01 diagnostics.

The authoritative comparator never imports or installs this observer.  A
separate diagnostic worker uses it to wrap fixed call sites after their natural
imports, records every invocation, and restores the exact prior bindings.
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import functools
import hashlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import inspect
import json
import os
import stat as stat_module
import sys
import textwrap
import threading
import time
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from tests.benchmarks.latency_contracts import (
    MAXIMUM_STAGE_SPANS,
    STAGE_TRACE_SCHEMA_ID,
    ArtifactIdentity,
    CallableTargetEvidence,
    InstrumentationManifest,
    ObserverOverheadEvidence,
    StageCardinalityPolicy,
    StageName,
    StageSpan,
    StageStatus,
    StageTrace,
)

OBSERVER_VERSION = "lat-us01-v1"
MAXIMUM_TARGET_SOURCE_BYTES = 8 * 1024 * 1024


def _bounded_file_bytes(
    path: Path,
    *,
    maximum_bytes: int = MAXIMUM_TARGET_SOURCE_BYTES,
    allowed_root: Path | None = None,
) -> bytes:
    """Read observer-owned source evidence without an unbounded allocation."""

    root = allowed_root.resolve() if allowed_root is not None else None
    candidate = path
    if root is not None:
        candidate = path if path.is_absolute() else root / path
        try:
            relative = candidate.relative_to(root)
        except ValueError as error:
            raise RuntimeError("observer source escaped its allowed root") from error
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError("observer source path contains a symlink")
    if candidate.is_symlink():
        raise RuntimeError("observer source cannot be a symlink")
    file_stat = candidate.lstat()
    if not stat_module.S_ISREG(file_stat.st_mode):
        raise RuntimeError("observer source must be a regular file")
    descriptor = os.open(
        candidate,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    opened_stat = os.fstat(descriptor)
    if (
        opened_stat.st_dev != file_stat.st_dev
        or opened_stat.st_ino != file_stat.st_ino
        or not stat_module.S_ISREG(opened_stat.st_mode)
    ):
        os.close(descriptor)
        raise RuntimeError("observer source changed before open")
    with os.fdopen(descriptor, "rb") as stream:
        data = stream.read(maximum_bytes + 1)
        final_stat = os.fstat(stream.fileno())
    if len(data) > maximum_bytes:
        raise RuntimeError("observer source evidence exceeds its byte bound")
    if (
        len(data) != file_stat.st_size
        or final_stat.st_dev != opened_stat.st_dev
        or final_stat.st_ino != opened_stat.st_ino
        or final_stat.st_size != opened_stat.st_size
        or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
    ):
        raise RuntimeError("observer source changed while reading")
    return data


@dataclass(frozen=True, slots=True)
class TargetDefinition:
    target_id: str
    module: str
    attribute: str
    stage: StageName
    policy_id: str
    source_module: str
    source_attribute: str
    strategy: Literal[
        "exception_only_sync",
        "exception_only_async",
        "response_constructor",
        "parse_result_binding_proxy",
        "natural_instance_get_pipeline",
        "lazy_import_module_patch",
        "load_callable_resolution",
    ] = "exception_only_sync"
    classifier_id: Literal[
        "exception_only",
        "docling_conversion_status_v1",
        "source_alignment_fail_closed_v1",
        "table_authority_state_v1",
        "none",
    ] = "exception_only"


TARGETS: tuple[TargetDefinition, ...] = (
    TargetDefinition("api-input-validation", "app.api", "_validate_declared_type", StageName.API_INPUT_VALIDATION, "api-input-validation", "app.api", "_validate_declared_type"),
    TargetDefinition("api-upload-read", "app.api", "_read_bounded_upload", StageName.UPLOAD_READ, "api-upload-read", "app.api", "_read_bounded_upload", "exception_only_async"),
    TargetDefinition("api-parse-dispatch", "app.api", "_parse_document", StageName.API_PARSE_DISPATCH, "api-parse-dispatch", "app.api", "_parse_document"),
    TargetDefinition("api-json-encoding", "app.api", "jsonable_encoder", StageName.JSON_ENCODING, "api-json-encoding", "fastapi.encoders", "jsonable_encoder"),
    TargetDefinition("api-markdown-serialization", "app.api", "_serialize_markdown", StageName.MARKDOWN_SERIALIZATION, "api-markdown-serialization", "app.api", "_serialize_markdown"),
    TargetDefinition("api-json-response", "app.api", "JSONResponse", StageName.RESPONSE_MATERIALIZATION, "api-response-construction", "starlette.responses", "JSONResponse", "response_constructor"),
    TargetDefinition("api-markdown-response", "app.api", "Response", StageName.RESPONSE_MATERIALIZATION, "api-response-construction", "starlette.responses", "Response", "response_constructor"),
    TargetDefinition("api-error-response", "app.errors", "JSONResponse", StageName.RESPONSE_MATERIALIZATION, "api-response-construction", "starlette.responses", "JSONResponse", "response_constructor"),
    TargetDefinition("api-threadpool-queue", "app.api", "run_in_threadpool", StageName.QUEUE_WAIT, "api-threadpool-queue", "starlette.concurrency", "run_in_threadpool", "exception_only_async"),
    TargetDefinition("api-result-validation", "app.models.ParseResult", "model_validate", StageName.RESULT_VALIDATION, "api-result-validation", "pydantic.main", "BaseModel.model_validate", "parse_result_binding_proxy"),
    TargetDefinition("api-model-dump", "app.models.ParseResult", "model_dump", StageName.API_MODEL_DUMP, "api-model-dump", "pydantic.main", "BaseModel.model_dump", "parse_result_binding_proxy"),
    TargetDefinition("pipeline-result-validation", "app.models.ParseResult", "model_validate", StageName.PIPELINE_RESULT_VALIDATION, "pipeline-result-validation", "pydantic.main", "BaseModel.model_validate", "parse_result_binding_proxy"),
    TargetDefinition("pipeline-import-resolution", "app.api", "_load_callable", StageName.PIPELINE_IMPORT_RESOLUTION, "pipeline-import-resolution", "app.api", "_load_callable", "load_callable_resolution"),
    TargetDefinition("pipeline-input-load", "app.services.pipeline", "load_document", StageName.LOAD_DOCUMENT, "pipeline-input-load", "app.services.input_documents", "load_document", "lazy_import_module_patch"),
    TargetDefinition("pipeline-parse-loaded", "app.services.pipeline", "_parse_loaded_document", StageName.PIPELINE_PARSE_LOADED, "pipeline-parse-loaded", "app.services.pipeline", "_parse_loaded_document", "lazy_import_module_patch"),
    TargetDefinition("pipeline-native-pdf", "app.services.pipeline", "_native_pdf_pages", StageName.NATIVE_PDF, "pipeline-native-pdf", "app.services.pipeline", "_native_pdf_pages", "lazy_import_module_patch"),
    TargetDefinition("pipeline-docling-conversion", "app.services.pipeline", "_convert_with_docling", StageName.DOCLING_CONVERSION, "pipeline-docling-conversion", "app.services.pipeline", "_convert_with_docling", "lazy_import_module_patch"),
    TargetDefinition("pipeline-pdf-converter-acquisition", "app.services.pipeline", "_converter_and_lock", StageName.DOCLING_CONVERTER_ACQUISITION, "pipeline-converter-acquisition", "app.services.pipeline", "_converter_and_lock", "lazy_import_module_patch"),
    TargetDefinition("pipeline-image-converter-acquisition", "app.services.pipeline", "_image_converter_and_lock", StageName.DOCLING_CONVERTER_ACQUISITION, "pipeline-converter-acquisition", "app.services.pipeline", "_image_converter_and_lock", "lazy_import_module_patch"),
    TargetDefinition("docling-lock-wait", "app.services.pipeline", "converter_lock.__enter__", StageName.DOCLING_LOCK_WAIT, "docling-lock-wait", "tests.benchmarks.latency_instrumentation", "_MeasuredLock.__enter__", "exception_only_sync"),
    TargetDefinition("docling-convert", "docling.document_converter.DocumentConverter", "convert", StageName.DOCLING_CONVERT, "docling-convert", "docling.document_converter", "DocumentConverter.convert", "exception_only_sync", "docling_conversion_status_v1"),
    TargetDefinition("docling-get-pipeline", "docling.document_converter.DocumentConverter", "_get_pipeline", StageName.DOCLING_PIPELINE_INITIALIZATION, "docling-get-pipeline", "docling.document_converter", "DocumentConverter._get_pipeline", "natural_instance_get_pipeline"),
    TargetDefinition("pipeline-image-ocr", "app.services.pipeline", "extract_image_ocr", StageName.IMAGE_OCR, "pipeline-image-ocr", "app.services.ocr", "extract_image_ocr", "lazy_import_module_patch"),
    TargetDefinition("pipeline-render-planning", "app.services.pipeline", "_select_pdf_render_requests", StageName.RENDER_REQUEST_PLANNING, "pipeline-render-planning", "app.services.pipeline", "_select_pdf_render_requests", "lazy_import_module_patch"),
    TargetDefinition("pipeline-rendered-ocr", "app.services.pipeline", "extract_rendered_pdf_ocr", StageName.RENDERED_PDF_OCR, "pipeline-rendered-ocr", "app.services.ocr", "extract_rendered_pdf_ocr", "lazy_import_module_patch"),
    TargetDefinition("pipeline-raster-ocr", "app.services.pipeline", "extract_raster_ocr", StageName.RASTER_OCR, "pipeline-raster-ocr", "app.services.ocr", "extract_raster_ocr", "lazy_import_module_patch"),
    TargetDefinition("pipeline-vector-tables", "app.services.pipeline", "extract_vector_tables", StageName.VECTOR_TABLES, "pipeline-vector-tables", "app.services.tables", "extract_vector_tables", "lazy_import_module_patch"),
    TargetDefinition("pipeline-table-repair", "app.services.pipeline", "_extract_table_repair_words", StageName.TABLE_REPAIR, "pipeline-table-repair", "app.services.pipeline", "_extract_table_repair_words", "lazy_import_module_patch"),
    TargetDefinition("pipeline-partitioned-table-repair", "app.services.pipeline", "_extract_partitioned_table_repair_words", StageName.TABLE_REPAIR, "pipeline-table-repair", "app.services.pipeline", "_extract_partitioned_table_repair_words", "lazy_import_module_patch"),
    TargetDefinition("pipeline-shared-analysis", "app.services.pipeline", "_analyze_shared_pages", StageName.SHARED_ANALYSIS, "pipeline-shared-analysis", "app.services.pipeline", "_analyze_shared_pages", "lazy_import_module_patch"),
    TargetDefinition("pipeline-compatibility", "app.services.pipeline", "_apply_shared_ir_compatibility_projection", StageName.COMPATIBILITY_PROJECTION, "pipeline-compatibility", "app.services.pipeline", "_apply_shared_ir_compatibility_projection", "lazy_import_module_patch"),
    TargetDefinition("pipeline-terminal-alignment", "app.services.pipeline", "_apply_terminal_source_text_alignment", StageName.TERMINAL_ALIGNMENT, "pipeline-terminal-alignment", "app.services.pipeline", "_apply_terminal_source_text_alignment", "lazy_import_module_patch", "source_alignment_fail_closed_v1"),
    TargetDefinition("pipeline-table-authority", "app.services.pipeline", "_apply_terminal_table_authority", StageName.TABLE_AUTHORITY, "pipeline-table-authority", "app.services.pipeline", "_apply_terminal_table_authority", "lazy_import_module_patch", "table_authority_state_v1"),
    TargetDefinition("font-audit", "app.services.font_audit", "audit_pdf_fonts", StageName.FONT_AUDIT, "font-audit", "app.services.font_audit", "audit_pdf_fonts", "lazy_import_module_patch"),
    TargetDefinition("font-recovery", "app.services.font_recovery", "recover_pdf_font_text", StageName.FONT_RECOVERY, "font-recovery", "app.services.font_recovery", "recover_pdf_font_text", "lazy_import_module_patch"),
    TargetDefinition("selective-span-ocr", "app.services.selective_span_ocr", "run_selective_span_ocr", StageName.SELECTIVE_SPAN_OCR, "selective-span-ocr", "app.services.selective_span_ocr", "run_selective_span_ocr", "lazy_import_module_patch"),
    TargetDefinition("text-run-evidence", "app.services.text_run_semantics", "extract_text_run_evidence", StageName.TEXT_RUN_EVIDENCE, "text-run-evidence", "app.services.text_run_semantics", "extract_text_run_evidence", "lazy_import_module_patch"),
    TargetDefinition("form-evidence", "app.services.form_semantics", "extract_form_evidence", StageName.FORM_EVIDENCE, "form-evidence", "app.services.form_semantics", "extract_form_evidence", "lazy_import_module_patch"),
    TargetDefinition("outline-evidence", "app.services.outline_structure", "extract_outline_evidence", StageName.OUTLINE_EVIDENCE, "outline-evidence", "app.services.outline_structure", "extract_outline_evidence", "lazy_import_module_patch"),
    TargetDefinition("source-text-evidence", "app.services.source_text_alignment", "extract_source_text_evidence", StageName.SOURCE_TEXT_EVIDENCE, "source-text-evidence", "app.services.source_text_alignment", "extract_source_text_evidence", "lazy_import_module_patch"),
    TargetDefinition("source-note-augmentation", "app.services.layout_source_notes", "augment_source_note_evidence", StageName.SOURCE_NOTE_AUGMENTATION, "source-note-augmentation", "app.services.layout_source_notes", "augment_source_note_evidence", "lazy_import_module_patch"),
)

TARGET_BY_ID = {item.target_id: item for item in TARGETS}
TARGETS_BY_MODULE: dict[str, tuple[TargetDefinition, ...]] = {}
for _target in TARGETS:
    TARGETS_BY_MODULE.setdefault(_target.module, ())
    TARGETS_BY_MODULE[_target.module] = (*TARGETS_BY_MODULE[_target.module], _target)


def _parse_result_validation_target(
    caller_module: str, caller_qualname: str
) -> TargetDefinition | None:
    """Route only the reviewed API/pipeline validation code objects."""

    if caller_module == "app.api" and caller_qualname == "parse_document_endpoint":
        return TARGET_BY_ID["api-result-validation"]
    if caller_module == "app.services.pipeline" and caller_qualname in {
        "_apply_terminal_table_authority",
        "_apply_terminal_table_authority.<locals>.commit",
        "_parse_loaded_document",
    }:
        return TARGET_BY_ID["pipeline-result-validation"]
    return None


def _setting(settings: Any, name: str) -> bool:
    value = getattr(settings, name)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a strict boolean")
    return value


def resolved_stage_cardinality_policies(
    *, settings: Any, source_suffix: str, output_format: str
) -> tuple[StageCardinalityPolicy, ...]:
    """Resolve closed 0/1/many bounds from the exact request path."""

    suffix = source_suffix.casefold()
    is_pdf = suffix == ".pdf"
    if not (is_pdf or suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}):
        raise ValueError("unsupported latency input path")
    if output_format not in {"json", "markdown"}:
        raise ValueError("unsupported latency output format")
    definitions: dict[StageName, tuple[int, int, str, bool, tuple[str, ...]]] = {}

    def add(
        stage: StageName,
        minimum: int,
        maximum: int,
        condition: str,
        targets: tuple[str, ...],
        *,
        degraded: bool = False,
    ) -> None:
        definitions[stage] = (minimum, maximum, condition, degraded, targets)

    mandatory = (
        (StageName.API_INPUT_VALIDATION, "api-input-validation", ("api-input-validation",)),
        (StageName.UPLOAD_READ, "api-upload-read", ("api-upload-read",)),
        (StageName.API_PARSE_DISPATCH, "api-parse-dispatch", ("api-parse-dispatch",)),
        (StageName.PIPELINE_IMPORT_RESOLUTION, "pipeline-import-resolution", ("pipeline-import-resolution",)),
        (StageName.JSON_ENCODING, "api-json-encoding", ("api-json-encoding",)),
        (StageName.RESULT_VALIDATION, "api-result-validation", ("api-result-validation",)),
        (StageName.API_MODEL_DUMP, "api-model-dump", ("api-model-dump",)),
        (StageName.RESPONSE_MATERIALIZATION, "api-response-construction", ("api-error-response", "api-json-response", "api-markdown-response")),
        (StageName.LOAD_DOCUMENT, "pipeline-input-load", ("pipeline-input-load",)),
        (StageName.PIPELINE_PARSE_LOADED, "pipeline-parse-loaded", ("pipeline-parse-loaded",)),
        (StageName.DOCLING_CONVERSION, "pipeline-docling-conversion", ("pipeline-docling-conversion",)),
        (StageName.DOCLING_CONVERTER_ACQUISITION, "pipeline-converter-acquisition", ("pipeline-pdf-converter-acquisition", "pipeline-image-converter-acquisition")),
        (StageName.DOCLING_LOCK_WAIT, "docling-lock-wait", ("docling-lock-wait",)),
        (StageName.DOCLING_CONVERT, "docling-convert", ("docling-convert",)),
        (StageName.SHARED_ANALYSIS, "pipeline-shared-analysis", ("pipeline-shared-analysis",)),
        (StageName.COMPATIBILITY_PROJECTION, "pipeline-compatibility", ("pipeline-compatibility",)),
        (StageName.TERMINAL_ALIGNMENT, "pipeline-terminal-alignment", ("pipeline-terminal-alignment",)),
    )
    for stage, policy, targets in mandatory:
        add(stage, 1, 1, "always", targets)
    add(
        StageName.TERMINAL_ALIGNMENT,
        1,
        1,
        "always-fail-closed",
        ("pipeline-terminal-alignment",),
        degraded=True,
    )
    queue_calls = 2 if output_format == "markdown" else 1
    add(
        StageName.QUEUE_WAIT,
        queue_calls,
        queue_calls,
        "threadpool-submission-route",
        ("api-threadpool-queue",),
    )
    add(
        StageName.PIPELINE_RESULT_VALIDATION,
        1,
        2 if _setting(settings, "table_span_fidelity_enabled") else 1,
        "pipeline-validation-path",
        ("pipeline-result-validation",),
    )
    add(
        StageName.DOCLING_PIPELINE_INITIALIZATION,
        1,
        1,
        "natural-docling-pipeline-resolution",
        ("docling-get-pipeline",),
    )
    add(
        StageName.MARKDOWN_SERIALIZATION,
        int(output_format == "markdown"),
        int(output_format == "markdown"),
        "markdown-output-only",
        ("api-markdown-serialization",),
    )
    pdf_stages = (
        (StageName.NATIVE_PDF, "pipeline-native-pdf", ("pipeline-native-pdf",), False),
        (StageName.IMAGE_OCR, "pipeline-image-ocr", ("pipeline-image-ocr",), False),
        (StageName.RENDER_REQUEST_PLANNING, "pipeline-render-planning", ("pipeline-render-planning",), False),
        (StageName.RENDERED_PDF_OCR, "pipeline-rendered-ocr", ("pipeline-rendered-ocr",), False),
        (StageName.VECTOR_TABLES, "pipeline-vector-tables", ("pipeline-vector-tables",), True),
    )
    for stage, policy, targets, degraded in pdf_stages:
        add(stage, int(is_pdf), int(is_pdf), "pdf-only", targets, degraded=degraded)
    add(StageName.RASTER_OCR, int(not is_pdf), int(not is_pdf), "image-only", ("pipeline-raster-ocr",))
    table_enabled = _setting(settings, "table_span_fidelity_enabled")
    add(
        StageName.TABLE_REPAIR,
        int(is_pdf),
        (3 if table_enabled else 1) if is_pdf else 0,
        "pdf-table-repair-family",
        ("pipeline-partitioned-table-repair", "pipeline-table-repair"),
        degraded=True,
    )

    optional = (
        (StageName.FONT_AUDIT, "font-audit", "text_integrity_font_audit_enabled", ("font-audit",), False),
        (StageName.FONT_RECOVERY, "font-recovery", "text_integrity_font_recovery_enabled", ("font-recovery",), True),
        (StageName.SELECTIVE_SPAN_OCR, "selective-span-ocr", "text_integrity_selective_span_ocr_enabled", ("selective-span-ocr",), True),
        (StageName.TEXT_RUN_EVIDENCE, "text-run-evidence", "layout_text_run_semantics_enabled", ("text-run-evidence",), True),
        (StageName.FORM_EVIDENCE, "form-evidence", "layout_forms_enabled", ("form-evidence",), True),
        (StageName.OUTLINE_EVIDENCE, "outline-evidence", "layout_outline_structure_enabled", ("outline-evidence",), True),
        (StageName.SOURCE_TEXT_EVIDENCE, "source-text-evidence", "text_integrity_source_alignment_enabled", ("source-text-evidence",), True),
        (StageName.SOURCE_NOTE_AUGMENTATION, "source-note-augmentation", "layout_source_notes_enabled", ("source-note-augmentation",), True),
    )
    for stage, policy, setting_name, targets, degraded in optional:
        enabled = is_pdf and _setting(settings, setting_name)
        minimum = int(enabled and stage in {StageName.FONT_AUDIT, StageName.TEXT_RUN_EVIDENCE, StageName.FORM_EVIDENCE, StageName.OUTLINE_EVIDENCE, StageName.SOURCE_TEXT_EVIDENCE, StageName.SOURCE_NOTE_AUGMENTATION})
        add(stage, minimum, int(enabled), f"setting-{setting_name.replace('_', '-')}", targets, degraded=degraded)
    add(StageName.TABLE_AUTHORITY, 0, int(table_enabled), "table-authority-data-conditional", ("pipeline-table-authority",), degraded=True)

    policies = []
    for stage, (minimum, maximum, condition, degraded, targets) in definitions.items():
        policy_id = TARGET_BY_ID[targets[0]].policy_id
        policies.append(
            StageCardinalityPolicy(
                policy_id=policy_id,
                stage=stage,
                minimum_calls=minimum,
                maximum_calls=maximum,
                condition_id=condition,
                exclusive_group=(
                    "response-format-route"
                    if stage is StageName.RESPONSE_MATERIALIZATION
                    else "converter-input-route"
                    if stage is StageName.DOCLING_CONVERTER_ACQUISITION
                    else None
                ),
                allow_degraded_on_success=degraded,
                target_ids=tuple(sorted(targets)),
            )
        )
    return tuple(sorted(policies, key=lambda item: item.policy_id))


def content_result_cache_proof_sha256(workspace: Path) -> str:
    """Bind the reviewed request path and its absence of a result-cache layer."""

    identities = []
    for relative in ("app/api.py", "app/services/pipeline.py"):
        data = _bounded_file_bytes(workspace / relative, allowed_root=workspace)
        identities.append((relative, len(data), hashlib.sha256(data).hexdigest()))
    return hashlib.sha256(
        json.dumps(identities, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _OpenedSpan:
    ordinal: int
    target_id: str
    stage: StageName
    started_ns: int
    parent_ordinal: int | None
    token: contextvars.Token[tuple[int, ...]]
    context_id: str


@dataclass(frozen=True, slots=True)
class _ClosedSpan:
    ordinal: int
    target_id: str
    stage: StageName
    started_ns: int
    ended_ns: int
    parent_ordinal: int | None
    context_id: str
    status: StageStatus
    failure_code: str | None


class ExternalStageCollector:
    """Strict request-scoped collector; every begin has exactly one close."""

    def __init__(self, *, clock: Callable[[], int] = time.perf_counter_ns) -> None:
        self._clock = clock
        self.started_ns: int | None = None
        self.finished_ns: int | None = None
        self._next_ordinal = 0
        self._open: dict[int, _OpenedSpan] = {}
        self._closed: dict[int, _ClosedSpan] = {}
        self._counts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._stack: contextvars.ContextVar[tuple[int, ...]] = contextvars.ContextVar(
            "phase_latency_external_stage_stack", default=()
        )
        self._context_ids: dict[tuple[int, int | None], str] = {}

    def _now(self) -> int:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeError("observer clock returned an invalid value")
        return value

    def start(self, *, started_ns: int | None = None) -> None:
        with self._lock:
            if self.started_ns is not None:
                raise RuntimeError("collector is single-use")
            self.started_ns = self._now() if started_ns is None else started_ns

    def _context_id(self) -> str:
        thread = threading.get_ident()
        try:
            task = asyncio.current_task()
        except RuntimeError:
            task = None
        key = (thread, id(task) if task is not None else None)
        with self._lock:
            retained = self._context_ids.get(key)
            if retained is None:
                retained = f"context-{len(self._context_ids) + 1:03d}"
                self._context_ids[key] = retained
            return retained

    def begin(self, target_id: str, stage: StageName) -> _OpenedSpan:
        started = self._now()
        with self._lock:
            if self.started_ns is None or self.finished_ns is not None:
                raise RuntimeError("stage opened outside the collector lifecycle")
            if started < self.started_ns:
                raise RuntimeError("observer clock regressed before stage start")
            if self._next_ordinal >= MAXIMUM_STAGE_SPANS - 1:
                raise RuntimeError("external stage span cap exceeded")
            stack = self._stack.get()
            ordinal = self._next_ordinal
            self._next_ordinal += 1
            token = self._stack.set((*stack, ordinal))
            opened = _OpenedSpan(
                ordinal=ordinal,
                target_id=target_id,
                stage=stage,
                started_ns=started,
                parent_ordinal=stack[-1] if stack else None,
                token=token,
                context_id=self._context_id(),
            )
            self._open[ordinal] = opened
            return opened

    def record_detached_interval(
        self,
        target_id: str,
        stage: StageName,
        *,
        started_ns: int,
        ended_ns: int,
        status: StageStatus = StageStatus.SUCCESS,
        failure_code: str | None = None,
    ) -> None:
        """Retain submit-to-entry queue time without including callable work."""

        with self._lock:
            if self.started_ns is None or self.finished_ns is not None:
                raise RuntimeError("detached interval lies outside collector lifecycle")
            if not self.started_ns <= started_ns <= ended_ns:
                raise RuntimeError("detached interval clock/order differs")
            if self._next_ordinal >= MAXIMUM_STAGE_SPANS - 1:
                raise RuntimeError("external stage span cap exceeded")
            ordinal = self._next_ordinal
            self._next_ordinal += 1
            self._closed[ordinal] = _ClosedSpan(
                ordinal=ordinal,
                target_id=target_id,
                stage=stage,
                started_ns=started_ns,
                ended_ns=ended_ns,
                parent_ordinal=None,
                context_id=self._context_id(),
                status=status,
                failure_code=failure_code,
            )
            self._counts[target_id] = self._counts.get(target_id, 0) + 1

    def close(
        self,
        opened: _OpenedSpan,
        *,
        ended_ns: int | None = None,
        status: StageStatus = StageStatus.SUCCESS,
        failure_code: str | None = None,
    ) -> None:
        ended = self._now() if ended_ns is None else ended_ns
        with self._lock:
            retained = self._open.get(opened.ordinal)
            if retained is None or retained is not opened:
                raise RuntimeError("stage was missing or closed more than once")
            if ended < opened.started_ns:
                raise RuntimeError("observer clock regressed inside a stage")
            stack = self._stack.get()
            if not stack or stack[-1] != opened.ordinal:
                raise RuntimeError("stage close order differs from causal stack")
            self._stack.reset(opened.token)
            del self._open[opened.ordinal]
            self._closed[opened.ordinal] = _ClosedSpan(
                ordinal=opened.ordinal,
                target_id=opened.target_id,
                stage=opened.stage,
                started_ns=opened.started_ns,
                ended_ns=ended,
                parent_ordinal=opened.parent_ordinal,
                context_id=opened.context_id,
                status=status,
                failure_code=failure_code,
            )
            self._counts[opened.target_id] = self._counts.get(opened.target_id, 0) + 1

    @staticmethod
    def _exception_status(error: BaseException) -> tuple[StageStatus, str]:
        name = type(error).__name__.casefold()
        if "timeout" in name:
            return StageStatus.TIMEOUT, "external_stage_timeout"
        if "cancel" in name or name in {"keyboardinterrupt", "systemexit"}:
            return StageStatus.CANCELLED, "external_stage_cancelled"
        return StageStatus.ERROR, "external_stage_error"

    def invoke(
        self,
        target_id: str,
        stage: StageName,
        function: Callable[[], Any],
        *,
        classifier: Callable[[Any], tuple[StageStatus, str | None]] | None = None,
    ) -> Any:
        opened = self.begin(target_id, stage)
        try:
            result = function()
        except BaseException as error:
            ended = self._now()
            status, code = self._exception_status(error)
            self.close(opened, ended_ns=ended, status=status, failure_code=code)
            raise
        ended = self._now()
        try:
            status, code = (
                classifier(result)
                if classifier is not None
                else (StageStatus.SUCCESS, None)
            )
        except BaseException as error:
            failure_status, failure_code = self._exception_status(error)
            self.close(
                opened,
                ended_ns=ended,
                status=failure_status,
                failure_code=f"classifier_{failure_code}",
            )
            raise
        self.close(opened, ended_ns=ended, status=status, failure_code=code)
        return result

    async def invoke_async(
        self,
        target_id: str,
        stage: StageName,
        function: Callable[[], Any],
    ) -> Any:
        opened = self.begin(target_id, stage)
        try:
            result = await function()
        except BaseException as error:
            ended = self._now()
            status, code = self._exception_status(error)
            self.close(opened, ended_ns=ended, status=status, failure_code=code)
            raise
        ended = self._now()
        self.close(opened, ended_ns=ended)
        return result

    def wrap(self, target: TargetDefinition, function: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.invoke_async(
                    target.target_id,
                    target.stage,
                    lambda: function(*args, **kwargs),
                )

            return async_wrapper

        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.invoke(
                target.target_id,
                target.stage,
                lambda: function(*args, **kwargs),
            )

        return wrapper

    def finish(self, *, finished_ns: int) -> None:
        with self._lock:
            if self.started_ns is None or self.finished_ns is not None:
                raise RuntimeError("collector finish lifecycle differs")
            if finished_ns < self.started_ns:
                raise RuntimeError("observer clock regressed at request end")
            if self._open:
                raise RuntimeError("collector retained unclosed spans")
            self.finished_ns = finished_ns

    def invocation_count(self, target_id: str) -> int:
        return self._counts.get(target_id, 0)

    def first_failure(self) -> _ClosedSpan | None:
        return next(
            (
                item
                for item in sorted(self._closed.values(), key=lambda value: value.ordinal)
                if item.status is not StageStatus.SUCCESS
            ),
            None,
        )

    def trace(
        self,
        *,
        request_started_ns: int,
        request_ended_ns: int,
        status: StageStatus,
        root_failure_code: str | None,
    ) -> StageTrace:
        if self.started_ns is None or self.finished_ns is None:
            raise RuntimeError("collector did not close")
        if self.finished_ns != request_ended_ns:
            raise RuntimeError("collector end must be the complete-response boundary")
        spans = [
            StageSpan(
                span_id="request",
                name=StageName.REQUEST_TOTAL,
                parent_span_id=None,
                started_monotonic_ns=request_started_ns,
                ended_monotonic_ns=request_ended_ns,
                status=status,
                failure_code=root_failure_code,
                execution_context_id="context-request",
                parent_relation="root",
            )
        ]
        by_ordinal: dict[int, _ClosedSpan] = {}
        for item in sorted(self._closed.values(), key=lambda value: value.ordinal):
            if item.parent_ordinal is not None and item.parent_ordinal not in by_ordinal:
                raise RuntimeError("diagnostic span parent is missing")
            parent_id = (
                "request"
                if item.parent_ordinal is None
                else f"external-{item.parent_ordinal:03d}"
            )
            spans.append(
                StageSpan(
                    span_id=f"external-{item.ordinal:03d}",
                    name=item.stage,
                    parent_span_id=parent_id,
                    started_monotonic_ns=item.started_ns,
                    ended_monotonic_ns=item.ended_ns,
                    status=item.status,
                    failure_code=item.failure_code,
                    execution_context_id=item.context_id,
                    parent_relation=(
                        "request_scope"
                        if item.parent_ordinal is None
                        else "causal_stack"
                    ),
                )
            )
            by_ordinal[item.ordinal] = item
        top_level = sorted(
            (span.started_monotonic_ns, span.ended_monotonic_ns)
            for span in spans[1:]
            if span.parent_span_id == "request"
        )
        union = 0
        left: int | None = None
        right: int | None = None
        for started, ended in top_level:
            if left is None:
                left, right = started, ended
            elif started <= int(right or 0):
                right = max(int(right or 0), ended)
            else:
                union += int(right or 0) - left
                left, right = started, ended
        if left is not None:
            union += int(right or 0) - left
        total = request_ended_ns - request_started_ns
        return StageTrace(
            schema_id=STAGE_TRACE_SCHEMA_ID,
            status=status,
            authoritative_total_ns=total,
            collector_started_monotonic_ns=self.started_ns,
            collector_finished_monotonic_ns=self.finished_ns,
            pre_collector_duration_ns=self.started_ns - request_started_ns,
            post_collector_duration_ns=request_ended_ns - self.finished_ns,
            attributed_top_level_union_ns=union,
            unattributed_remainder_ns=total - union,
            spans=tuple(spans),
        )


def root_only_trace(
    *,
    request_started_ns: int,
    request_ended_ns: int,
    status: StageStatus,
    failure_code: str | None,
) -> StageTrace:
    total = request_ended_ns - request_started_ns
    return StageTrace(
        schema_id=STAGE_TRACE_SCHEMA_ID,
        status=status,
        authoritative_total_ns=total,
        collector_started_monotonic_ns=None,
        collector_finished_monotonic_ns=None,
        pre_collector_duration_ns=None,
        post_collector_duration_ns=None,
        attributed_top_level_union_ns=0,
        unattributed_remainder_ns=total,
        spans=(
            StageSpan(
                span_id="request",
                name=StageName.REQUEST_TOTAL,
                parent_span_id=None,
                started_monotonic_ns=request_started_ns,
                ended_monotonic_ns=request_ended_ns,
                status=status,
                failure_code=failure_code,
                execution_context_id="context-request",
                parent_relation="root",
            ),
        ),
    )


def _binding_key(value: Any) -> tuple[int, int | None]:
    function = getattr(value, "__func__", value)
    owner = getattr(value, "__self__", None)
    return id(function), id(owner) if owner is not None else None


def _callable_payload(value: Any) -> tuple[str, str, str, str]:
    unwrapped = inspect.unwrap(getattr(value, "__func__", value))
    signature = str(inspect.signature(value))
    module = str(getattr(unwrapped, "__module__", type(unwrapped).__module__))
    qualname = str(getattr(unwrapped, "__qualname__", type(unwrapped).__qualname__))
    try:
        source = textwrap.dedent(inspect.getsource(unwrapped))
        normalized = ast.dump(ast.parse(source), include_attributes=False)
    except (OSError, TypeError, IndentationError, SyntaxError):
        code = getattr(unwrapped, "__code__", None)
        normalized = repr(
            (
                getattr(code, "co_code", b"").hex(),
                getattr(code, "co_names", ()),
                getattr(code, "co_varnames", ()),
                getattr(code, "co_argcount", 0),
            )
        )
    return (
        module,
        qualname,
        signature,
        hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def _binding_sha256(value: Any) -> str:
    module, qualname, signature, code = _callable_payload(value)
    return hashlib.sha256(
        json.dumps(
            (module, qualname, signature, code), separators=(",", ":")
        ).encode()
    ).hexdigest()


def _source_artifact(value: Any, workspace: Path) -> ArtifactIdentity:
    unwrapped = inspect.unwrap(getattr(value, "__func__", value))
    source_path = inspect.getsourcefile(unwrapped) or inspect.getfile(unwrapped)
    candidate = Path(source_path)
    resolved = candidate.resolve()
    relative = resolved.relative_to(workspace).as_posix()
    data = _bounded_file_bytes(candidate, allowed_root=workspace)
    if not data or len(data) > MAXIMUM_TARGET_SOURCE_BYTES:
        raise RuntimeError("observer target source exceeds its bound")
    return ArtifactIdentity(
        path=relative,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _ast_target_metadata(
    definition: TargetDefinition, workspace: Path
) -> tuple[ArtifactIdentity, str, str, str, str]:
    """Derive immutable target metadata from final source bytes only."""

    spec = importlib.util.find_spec(definition.source_module)
    if spec is None or not spec.origin:
        raise RuntimeError("observer target source is unavailable")
    candidate = Path(spec.origin)
    path = candidate.resolve()
    data = _bounded_file_bytes(candidate, allowed_root=workspace)
    if not data:
        raise RuntimeError("observer target source is empty")
    relative = path.relative_to(workspace).as_posix()
    tree = ast.parse(data, filename=str(path))
    parts = definition.source_attribute.split(".")
    nodes: list[ast.AST] = list(tree.body)
    found: ast.AST | None = None
    for part in parts:
        found = next(
            (
                node
                for node in nodes
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                )
                and node.name == part
            ),
            None,
        )
        if found is None:
            break
        nodes = list(getattr(found, "body", ()))
    if found is None:
        raise RuntimeError("observer target AST is unavailable")
    signature = (
        f"ast:{ast.dump(getattr(found, 'args', found), include_attributes=False)}"
    )
    code_sha = hashlib.sha256(
        ast.dump(found, include_attributes=False).encode("utf-8")
    ).hexdigest()
    artifact = ArtifactIdentity(
        path=relative,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    return (
        artifact,
        definition.source_module,
        definition.source_attribute,
        signature,
        code_sha,
    )


@dataclass(slots=True)
class _InstalledBinding:
    definitions: tuple[TargetDefinition, ...]
    owner: Any
    attribute: str
    original: Any
    wrapper: Any
    had_own_attribute: bool
    original_key: tuple[int, int | None]
    installed_key: tuple[int, int | None]
    pre_sha256: str
    installed_sha256: str
    restored_sha256: str | None = None
    restored_exact: bool | None = None


class _ConversionScope:
    def __init__(self) -> None:
        self.owner_thread: int | None = None

    def enter(self) -> None:
        if self.owner_thread is not None:
            raise RuntimeError("conversion scope cannot be entered twice")
        self.owner_thread = threading.get_ident()

    def exit(self) -> None:
        if self.owner_thread != threading.get_ident():
            raise RuntimeError("conversion scope owner changed")
        self.owner_thread = None

    def require_owner(self) -> None:
        if self.owner_thread != threading.get_ident():
            raise RuntimeError("Docling private hook must be installed under its lock")


class _MeasuredLock:
    def __init__(self, lock: Any, collector: ExternalStageCollector, scope: _ConversionScope) -> None:
        self._lock = lock
        self._collector = collector
        self._scope = scope

    def __enter__(self) -> Any:
        result = self._collector.invoke(
            "docling-lock-wait", StageName.DOCLING_LOCK_WAIT, self._lock.__enter__
        )
        self._scope.enter()
        return result

    def __exit__(self, *args: Any) -> Any:
        self._scope.exit()
        return self._lock.__exit__(*args)


def _docling_status(result: Any) -> tuple[StageStatus, str | None]:
    status = getattr(result, "status", None)
    normalized = str(getattr(status, "value", status)).casefold()
    if normalized in {"success", "partial_success"}:
        return StageStatus.SUCCESS, None
    return StageStatus.ERROR, "docling_conversion_status_failure"


def _source_alignment_status(result: Any) -> tuple[StageStatus, str | None]:
    if not isinstance(result, dict):
        return StageStatus.SUCCESS, None
    processing = result.get("processing")
    alignment = (
        processing.get("source_text_alignment")
        if isinstance(processing, dict)
        else None
    )
    reason = alignment.get("reason") if isinstance(alignment, dict) else None
    if reason == "source_alignment_failed_closed":
        return StageStatus.ERROR, "source_alignment_failed_closed"
    return StageStatus.SUCCESS, None


class _MeasuredConverter:
    def __init__(
        self,
        converter: Any,
        collector: ExternalStageCollector,
        manager: DiagnosticInstrumentation,
        scope: _ConversionScope,
    ) -> None:
        self._converter = converter
        self._collector = collector
        self._manager = manager
        self._scope = scope

    def convert(self, *args: Any, **kwargs: Any) -> Any:
        def operation() -> Any:
            self._scope.require_owner()
            return self._manager.invoke_with_natural_get_pipeline(
                self._converter,
                lambda: self._converter.convert(*args, **kwargs),
            )

        return self._collector.invoke(
            "docling-convert",
            StageName.DOCLING_CONVERT,
            operation,
            classifier=_docling_status,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._converter, name)


class _ScopedLoader(importlib.abc.Loader):
    def __init__(self, loader: importlib.abc.Loader, manager: DiagnosticInstrumentation) -> None:
        self._loader = loader
        self._manager = manager

    def create_module(self, spec: Any) -> Any:
        creator = getattr(self._loader, "create_module", None)
        return creator(spec) if creator is not None else None

    def exec_module(self, module: types.ModuleType) -> None:
        executor = getattr(self._loader, "exec_module", None)
        if executor is None:
            raise ImportError("instrumented module loader lacks exec_module")
        spec = getattr(module, "__spec__", None)
        if spec is None or spec.loader is not self:
            raise ImportError("instrumented module loader binding drifted")
        # The finder wrapper is needed only to observe the natural import.  Run
        # the real loader with the exact bindings an unobserved import would
        # expose, and leave those bindings in place on success *and* on every
        # BaseException path.  This prevents a retained loader from holding the
        # manager/collector graph after the request.
        spec.loader = self._loader
        module.__loader__ = self._loader
        executor(module)
        self._manager.install_module_targets(module)
        if spec.loader is self or module.__loader__ is self:
            raise RuntimeError("scoped import loader survived natural import")


class _ScopedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, modules: frozenset[str], manager: DiagnosticInstrumentation) -> None:
        self._modules = modules
        self._manager = manager

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname not in self._modules:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"observer target module is unavailable: {fullname}")
        spec.loader = _ScopedLoader(spec.loader, self._manager)
        return spec


class DiagnosticInstrumentation:
    """Install, verify, and restore the diagnostic observer exactly once."""

    def __init__(self, collector: ExternalStageCollector, *, workspace: Path) -> None:
        self.collector = collector
        self.workspace = workspace.resolve()
        self._installed: list[_InstalledBinding] = []
        self._by_target: dict[str, _InstalledBinding] = {}
        self._finder: _ScopedFinder | None = None
        self._closed = False
        self._docling_dispositions: list[str] = []

    def _install(
        self,
        owner: Any,
        attribute: str,
        definitions: tuple[TargetDefinition, ...],
        wrapper: Any,
    ) -> None:
        if any(item.target_id in self._by_target for item in definitions):
            raise RuntimeError("observer target was patched more than once")
        original = getattr(owner, attribute)
        had_own = attribute in vars(owner)
        setattr(owner, attribute, wrapper)
        installed = getattr(owner, attribute)
        if installed is not wrapper and not inspect.ismethod(installed):
            raise RuntimeError("observer target installation drifted")
        record = _InstalledBinding(
            definitions=definitions,
            owner=owner,
            attribute=attribute,
            original=original,
            wrapper=wrapper,
            had_own_attribute=had_own,
            original_key=_binding_key(original),
            installed_key=_binding_key(installed),
            pre_sha256=_binding_sha256(original),
            installed_sha256=_binding_sha256(installed),
        )
        self._installed.append(record)
        for definition in definitions:
            self._by_target[definition.target_id] = record

    def _register_proxy_target(
        self,
        definition: TargetDefinition,
        *,
        original: Any,
        wrapper: Any,
    ) -> None:
        existing = self._by_target.get(definition.target_id)
        if existing is not None:
            if existing.pre_sha256 != _binding_sha256(original):
                raise RuntimeError("proxy target identity changed between invocations")
            return
        digest = _binding_sha256(original)
        record = _InstalledBinding(
            definitions=(definition,),
            owner=None,
            attribute=definition.attribute,
            original=original,
            wrapper=wrapper,
            had_own_attribute=False,
            original_key=_binding_key(original),
            installed_key=_binding_key(wrapper),
            pre_sha256=digest,
            installed_sha256=_binding_sha256(wrapper),
            restored_sha256=digest,
            restored_exact=True,
        )
        self._installed.append(record)
        self._by_target[definition.target_id] = record

    def install(
        self, api: types.ModuleType, *, allow_preloaded_pipeline: bool = False
    ) -> None:
        if self._finder is not None or self._closed:
            raise RuntimeError("diagnostic instrumentation is single-use")
        optional_modules = frozenset(
            {
                "app.services.font_audit",
                "app.services.font_recovery",
                "app.services.selective_span_ocr",
                "app.services.text_run_semantics",
                "app.services.form_semantics",
                "app.services.outline_structure",
                "app.services.source_text_alignment",
                "app.services.layout_source_notes",
            }
        )
        preloaded_optional = tuple(
            name for name in optional_modules if name in sys.modules
        )
        pipeline_preloaded = "app.services.pipeline" in sys.modules
        if (preloaded_optional or pipeline_preloaded) and not allow_preloaded_pipeline:
            raise RuntimeError("diagnostic pipeline target was imported before cold request")
        error_module = sys.modules.get("app.errors")
        if error_module is None:
            raise RuntimeError("API error module was not loaded with the application")
        direct_ids = (
            "api-input-validation",
            "api-upload-read",
            "api-parse-dispatch",
            "api-json-encoding",
            "api-markdown-serialization",
            "api-json-response",
            "api-markdown-response",
        )
        for target_id in direct_ids:
            definition = TARGET_BY_ID[target_id]
            original = getattr(api, definition.attribute)
            self._install(
                api,
                definition.attribute,
                (definition,),
                self.collector.wrap(definition, original),
            )

        error_definition = TARGET_BY_ID["api-error-response"]
        original_error_response = getattr(error_module, "JSONResponse")
        self._install(
            error_module,
            "JSONResponse",
            (error_definition,),
            self.collector.wrap(error_definition, original_error_response),
        )

        queue_definition = TARGET_BY_ID["api-threadpool-queue"]
        original_threadpool = getattr(api, "run_in_threadpool")

        @functools.wraps(original_threadpool)
        async def observed_threadpool(
            function: Callable[..., Any], *args: Any, **kwargs: Any
        ) -> Any:
            return await self._invoke_threadpool_with_queue_observation(
                original_threadpool,
                function,
                args,
                kwargs,
            )

        self._install(
            api,
            "run_in_threadpool",
            (queue_definition,),
            observed_threadpool,
        )

        original_load = getattr(api, "_load_callable")
        load_definition = TARGET_BY_ID["pipeline-import-resolution"]

        @functools.wraps(original_load)
        def load_callable(module_name: str, function_name: str) -> Any:
            if (module_name, function_name) != (
                "app.services.pipeline",
                "parse_document",
            ):
                return original_load(module_name, function_name)

            return self._resolve_and_patch_pipeline_callable(
                original_load,
                module_name,
                function_name,
            )

        self._install(api, "_load_callable", (load_definition,), load_callable)
        self._install_parse_result_bindings(api.ParseResult)

        for name in preloaded_optional:
            self.install_module_targets(sys.modules[name])
        if pipeline_preloaded:
            self.install_module_targets(sys.modules["app.services.pipeline"])
        self._finder = _ScopedFinder(optional_modules, self)
        sys.meta_path.insert(0, self._finder)

    async def _invoke_threadpool_with_queue_observation(
        self,
        original_threadpool: Callable[..., Any],
        function: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> Any:
        definition = TARGET_BY_ID["api-threadpool-queue"]
        submitted_ns = self.collector._now()
        state_lock = threading.Lock()
        entered_once = False
        ledger_closed = False

        def close_ledger(
            *,
            ended_ns: int,
            status: StageStatus,
            failure_code: str | None,
        ) -> bool:
            nonlocal ledger_closed
            with state_lock:
                if ledger_closed:
                    return False
                ledger_closed = True
            self.collector.record_detached_interval(
                definition.target_id,
                definition.stage,
                started_ns=submitted_ns,
                ended_ns=ended_ns,
                status=status,
                failure_code=failure_code,
            )
            return True

        @functools.wraps(function)
        def entered() -> Any:
            nonlocal entered_once
            with state_lock:
                if entered_once:
                    raise RuntimeError("threadpool callable entered more than once")
                entered_once = True
            entered_ns = self.collector._now()
            if not close_ledger(
                ended_ns=entered_ns,
                status=StageStatus.SUCCESS,
                failure_code=None,
            ):
                raise RuntimeError("threadpool callable entered after queue closure")
            return function(*args, **dict(kwargs))

        try:
            result = await original_threadpool(entered)
        except BaseException as error:
            status, failure_code = self.collector._exception_status(error)
            close_ledger(
                ended_ns=self.collector._now(),
                status=status,
                failure_code=failure_code,
            )
            raise
        if not entered_once:
            close_ledger(
                ended_ns=self.collector._now(),
                status=StageStatus.ERROR,
                failure_code="threadpool_callable_not_entered",
            )
            raise RuntimeError("threadpool callable was never entered")
        return result

    def _resolve_and_patch_pipeline_callable(
        self,
        original_load: Callable[[str, str], Any],
        module_name: str,
        function_name: str,
    ) -> Any:
        definition = TARGET_BY_ID["pipeline-import-resolution"]
        self.collector.invoke(
            definition.target_id,
            definition.stage,
            lambda: original_load(module_name, function_name),
        )
        module = sys.modules.get(module_name)
        if module is None:
            raise RuntimeError("pipeline import did not retain its module")
        self.install_module_targets(module)
        return getattr(module, function_name)

    def _install_parse_result_bindings(self, parse_result: type[Any]) -> None:
        validate_definitions = (
            TARGET_BY_ID["api-result-validation"],
            TARGET_BY_ID["pipeline-result-validation"],
        )
        original_validate = getattr(parse_result, "model_validate")

        def observed_validate(_class: type[Any], *args: Any, **kwargs: Any) -> Any:
            caller = sys._getframe(1)
            definition = _parse_result_validation_target(
                str(caller.f_globals.get("__name__", "")),
                caller.f_code.co_qualname,
            )
            if definition is None:
                return original_validate(*args, **kwargs)
            return self.collector.invoke(
                definition.target_id,
                definition.stage,
                lambda: original_validate(*args, **kwargs),
            )

        self._install(
            parse_result,
            "model_validate",
            validate_definitions,
            classmethod(observed_validate),
        )

        dump_definition = TARGET_BY_ID["api-model-dump"]
        original_dump = getattr(parse_result, "model_dump")

        @functools.wraps(original_dump)
        def observed_dump(instance: Any, *args: Any, **kwargs: Any) -> Any:
            caller = sys._getframe(1)
            if not (
                caller.f_globals.get("__name__") == "app.api"
                and caller.f_code.co_name == "parse_document_endpoint"
            ):
                return original_dump(instance, *args, **kwargs)
            return self.collector.invoke(
                dump_definition.target_id,
                dump_definition.stage,
                lambda: original_dump(instance, *args, **kwargs),
            )

        self._install(
            parse_result,
            "model_dump",
            (dump_definition,),
            observed_dump,
        )

    def install_module_targets(self, module: types.ModuleType) -> None:
        if self._closed:
            raise RuntimeError("observer cannot patch after restoration")
        definitions = TARGETS_BY_MODULE.get(module.__name__, ())
        for definition in definitions:
            if definition.target_id in {
                "docling-lock-wait",
                "docling-convert",
                "docling-get-pipeline",
            }:
                continue
            if definition.target_id in self._by_target:
                continue
            original = getattr(module, definition.attribute)
            if definition.target_id in {
                "pipeline-pdf-converter-acquisition",
                "pipeline-image-converter-acquisition",
            }:
                @functools.wraps(original)
                def acquire(
                    *args: Any,
                    __original: Any = original,
                    __definition: TargetDefinition = definition,
                    **kwargs: Any,
                ) -> tuple[Any, Any]:
                    converter, lock = self.collector.invoke(
                        __definition.target_id,
                        __definition.stage,
                        lambda: __original(*args, **kwargs),
                    )
                    scope = _ConversionScope()
                    measured_converter = _MeasuredConverter(
                        converter, self.collector, self, scope
                    )
                    measured_lock = _MeasuredLock(lock, self.collector, scope)
                    self._register_proxy_target(
                        TARGET_BY_ID["docling-convert"],
                        original=converter.convert,
                        wrapper=measured_converter.convert,
                    )
                    self._register_proxy_target(
                        TARGET_BY_ID["docling-lock-wait"],
                        original=lock.__enter__,
                        wrapper=measured_lock.__enter__,
                    )
                    return (
                        measured_converter,
                        measured_lock,
                    )

                wrapper = acquire
            elif definition.target_id == "pipeline-terminal-alignment":
                @functools.wraps(original)
                def terminal_alignment(
                    *args: Any,
                    __original: Any = original,
                    __definition: TargetDefinition = definition,
                    **kwargs: Any,
                ) -> Any:
                    return self.collector.invoke(
                        __definition.target_id,
                        __definition.stage,
                        lambda: __original(*args, **kwargs),
                        classifier=_source_alignment_status,
                    )

                wrapper = terminal_alignment
            elif definition.target_id == "pipeline-table-authority":
                signature = inspect.signature(original)

                @functools.wraps(original)
                def table_authority(
                    *args: Any,
                    __original: Any = original,
                    __definition: TargetDefinition = definition,
                    __signature: inspect.Signature = signature,
                    **kwargs: Any,
                ) -> Any:
                    arguments = __signature.bind_partial(*args, **kwargs).arguments
                    state = arguments.get("state")
                    before = (
                        bool(state.get("timed_out")),
                        bool(state.get("custody_rejected")),
                    ) if isinstance(state, dict) else (False, False)

                    def classify(_result: Any) -> tuple[StageStatus, str | None]:
                        after = (
                            bool(state.get("timed_out")),
                            bool(state.get("custody_rejected")),
                        ) if isinstance(state, dict) else before
                        if after[0] and not before[0]:
                            return StageStatus.TIMEOUT, "table_authority_failed_closed"
                        if after[1] and not before[1]:
                            return StageStatus.ERROR, "table_authority_failed_closed"
                        return StageStatus.SUCCESS, None

                    return self.collector.invoke(
                        __definition.target_id,
                        __definition.stage,
                        lambda: __original(*args, **kwargs),
                        classifier=classify,
                    )

                wrapper = table_authority
            else:
                wrapper = self.collector.wrap(definition, original)
            self._install(module, definition.attribute, (definition,), wrapper)

    def invoke_with_natural_get_pipeline(
        self, converter: Any, operation: Callable[[], Any]
    ) -> Any:
        definition = TARGET_BY_ID["docling-get-pipeline"]
        original = getattr(converter, "_get_pipeline")
        had_own = "_get_pipeline" in vars(converter)
        original_key = _binding_key(original)
        pre_sha = _binding_sha256(original)

        @functools.wraps(original)
        def measured(_instance: Any, *args: Any, **kwargs: Any) -> Any:
            initialized = getattr(converter, "initialized_pipelines", None)
            if not isinstance(initialized, dict):
                raise RuntimeError("Docling initialized-pipeline cache capability differs")
            before = len(initialized)
            result = self.collector.invoke(
                definition.target_id,
                definition.stage,
                lambda: original(*args, **kwargs),
            )
            after = len(initialized)
            self._docling_dispositions.append(
                "initialized" if after > before else "reused"
            )
            return result

        bound = types.MethodType(measured, converter)
        setattr(converter, "_get_pipeline", bound)
        record = _InstalledBinding(
            definitions=(definition,),
            owner=converter,
            attribute="_get_pipeline",
            original=original,
            wrapper=bound,
            had_own_attribute=had_own,
            original_key=original_key,
            installed_key=_binding_key(bound),
            pre_sha256=pre_sha,
            installed_sha256=_binding_sha256(getattr(converter, "_get_pipeline")),
        )
        self._installed.append(record)
        self._by_target[definition.target_id] = record
        try:
            return operation()
        finally:
            if _binding_key(getattr(converter, "_get_pipeline")) != _binding_key(bound):
                raise RuntimeError("Docling private binding drifted during conversion")
            if had_own:
                setattr(converter, "_get_pipeline", original)
            else:
                delattr(converter, "_get_pipeline")
            restored = getattr(converter, "_get_pipeline")
            record.restored_sha256 = _binding_sha256(restored)
            record.restored_exact = _binding_key(restored) == original_key

    def close(self) -> None:
        if self._closed:
            raise RuntimeError("observer restoration cannot run twice")
        if self._finder is not None:
            if self._finder not in sys.meta_path:
                raise RuntimeError("observer import hook disappeared before restoration")
            sys.meta_path.remove(self._finder)
        for record in reversed(self._installed):
            if record.restored_exact is not None:
                continue
            installed = getattr(record.owner, record.attribute)
            if (
                _binding_key(installed) != record.installed_key
                or _binding_sha256(installed) != record.installed_sha256
            ):
                raise RuntimeError("observer target changed while installed")
            if record.had_own_attribute:
                setattr(record.owner, record.attribute, record.original)
            else:
                delattr(record.owner, record.attribute)
            restored = getattr(record.owner, record.attribute)
            record.restored_sha256 = _binding_sha256(restored)
            record.restored_exact = _binding_key(restored) == record.original_key
            if not record.restored_exact or record.restored_sha256 != record.pre_sha256:
                raise RuntimeError("observer failed exact binding restoration")
        self._closed = True

    def _definition_metadata(
        self, definition: TargetDefinition
    ) -> tuple[Any, ArtifactIdentity, str, str, str, str]:
        # Manifest identity deliberately does not trust the patched runtime
        # binding.  It is recomputable from the final, retained source bytes.
        return self._definition_metadata_from_ast(definition)

    def _definition_metadata_from_ast(
        self, definition: TargetDefinition
    ) -> tuple[Any, ArtifactIdentity, str, str, str, str]:

        artifact, module, qualname, signature, code_sha = _ast_target_metadata(
            definition, self.workspace
        )
        return (
            definition,
            artifact,
            module,
            qualname,
            signature,
            code_sha,
        )

    def build_manifest(
        self,
        *,
        harness_files: tuple[ArtifactIdentity, ...],
        runtime_sha256: str,
        dependency_lock_sha256: str,
        overhead: ObserverOverheadEvidence,
    ) -> InstrumentationManifest:
        if not self._closed:
            raise RuntimeError("manifest requires completed restoration")
        targets = []
        docling_signature_sha: str | None = None
        for definition in TARGETS:
            _, source, module, qualname, signature, code_sha = self._definition_metadata(definition)
            record = self._by_target.get(definition.target_id)
            installed = record is not None
            if definition.target_id == "docling-get-pipeline":
                docling_signature_sha = hashlib.sha256(signature.encode()).hexdigest()
            callable_kind: Literal["sync_function", "async_function", "class_binding", "bound_method"]
            if definition.strategy == "response_constructor":
                callable_kind = "class_binding"
            elif definition.strategy == "natural_instance_get_pipeline":
                callable_kind = "bound_method"
            elif definition.strategy == "exception_only_async":
                callable_kind = "async_function"
            else:
                callable_kind = "sync_function"
            targets.append(
                CallableTargetEvidence(
                    target_id=definition.target_id,
                    stage=definition.stage,
                    module=module,
                    attribute=definition.attribute,
                    qualname=qualname,
                    source=source,
                    signature=signature,
                    signature_sha256=hashlib.sha256(signature.encode()).hexdigest(),
                    callable_kind=callable_kind,
                    code_sha256=code_sha,
                    wrapper_strategy=definition.strategy,
                    classifier_id=definition.classifier_id,
                    cardinality_policy_id=definition.policy_id,
                    installed=installed,
                    invocation_count=self.collector.invocation_count(definition.target_id),
                    pre_binding_sha256=record.pre_sha256 if record else None,
                    installed_binding_sha256=record.installed_sha256 if record else None,
                    post_restore_binding_sha256=record.restored_sha256 if record else None,
                    restored_exact_binding=record.restored_exact if record else None,
                )
            )
        payload = {
            "schema_id": "phase-latency-external-observer-manifest-v1",
            "schema_version": "1.0",
            "observer_mode": "diagnostic_external_test_instrumentation",
            "observer_version": OBSERVER_VERSION,
            "authoritative_total_policy": "separate_uninstrumented_twin_no_observer_subtraction",
            "harness_files": tuple(sorted(harness_files, key=lambda item: item.path)),
            "targets": tuple(sorted(targets, key=lambda item: item.target_id)),
            "installed_target_count": sum(item.installed for item in targets),
            "request_collector_id": "external-request-scoped-perf-counter-ns-v1",
            "import_hook_finder_id": "phase-latency-scoped-meta-path-finder-v1",
            "import_hook_loader_id": "phase-latency-scoped-loader-v1",
            "python_implementation": "CPython",
            "python_version": sys.version.split()[0],
            "runtime_sha256": runtime_sha256,
            "dependency_lock_sha256": dependency_lock_sha256,
            "docling_version": importlib.metadata.version("docling"),
            "docling_get_pipeline_signature_sha256": docling_signature_sha,
            "docling_get_pipeline_disposition": (
                "not_observed"
                if not self._docling_dispositions
                else self._docling_dispositions[0]
                if len(set(self._docling_dispositions)) == 1
                else "mixed"
            ),
            "observer_overhead": overhead,
            "hosted_calls": 0,
        }
        canonical = json.loads(
            json.dumps(
                {
                    key: (
                        [item.model_dump(mode="json") for item in value]
                        if isinstance(value, tuple) and value and hasattr(value[0], "model_dump")
                        else value.model_dump(mode="json")
                        if hasattr(value, "model_dump")
                        else value
                    )
                    for key, value in payload.items()
                },
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        payload["manifest_sha256"] = hashlib.sha256(
            json.dumps(canonical, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return InstrumentationManifest.model_validate(payload)


def calibrate_observer_overhead() -> ObserverOverheadEvidence:
    """Measure but never subtract a bounded no-op wrapper calibration."""

    def noop() -> None:
        return None

    started = time.perf_counter_ns()
    for _ in range(256):
        noop()
    unwrapped = time.perf_counter_ns() - started

    @functools.wraps(noop)
    def wrapped() -> None:
        return noop()

    started = time.perf_counter_ns()
    for _ in range(256):
        wrapped()
    observed = time.perf_counter_ns() - started
    return ObserverOverheadEvidence(
        calibration_id="external_exception_wrapper_noop_v1",
        call_count=256,
        unwrapped_total_ns=unwrapped,
        wrapped_total_ns=observed,
        absolute_delta_ns=abs(observed - unwrapped),
        adjustment_applied=False,
    )


def harness_file_identities(workspace: Path) -> tuple[ArtifactIdentity, ...]:
    paths = (
        "tests/benchmarks/latency_campaign.py",
        "tests/benchmarks/latency_child_guard/sitecustomize.py",
        "tests/benchmarks/latency_contracts.py",
        "tests/benchmarks/latency_instrumentation.py",
        "tests/benchmarks/latency_isolation.py",
        "tests/benchmarks/latency_network_probe.py",
        "tests/benchmarks/latency_runner.py",
        "tests/benchmarks/latency_watchdog.py",
        "tests/benchmarks/latency_worker.py",
    )
    retained = []
    for relative in paths:
        data = _bounded_file_bytes(workspace / relative, allowed_root=workspace)
        retained.append(
            ArtifactIdentity(
                path=relative,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return tuple(sorted(retained, key=lambda item: item.path))


def _expected_callable_kind(definition: TargetDefinition) -> str:
    if definition.strategy == "response_constructor":
        return "class_binding"
    if definition.strategy == "natural_instance_get_pipeline":
        return "bound_method"
    if definition.strategy == "exception_only_async":
        return "async_function"
    return "sync_function"


def verify_instrumentation_manifest(
    manifest: InstrumentationManifest, *, workspace: Path
) -> None:
    """Recompute every immutable observer field from independently read bytes."""

    root = workspace.resolve()
    if manifest.harness_files != harness_file_identities(root):
        raise ValueError("observer harness-file inventory differs")
    observed = {item.target_id: item for item in manifest.targets}
    if set(observed) != {item.target_id for item in TARGETS}:
        raise ValueError("observer target inventory differs")
    for definition in TARGETS:
        target = observed[definition.target_id]
        source, module, qualname, signature, code_sha = _ast_target_metadata(
            definition, root
        )
        immutable = (
            target.stage,
            target.module,
            target.attribute,
            target.qualname,
            target.source,
            target.signature,
            target.signature_sha256,
            target.callable_kind,
            target.code_sha256,
            target.wrapper_strategy,
            target.classifier_id,
            target.cardinality_policy_id,
        )
        expected = (
            definition.stage,
            module,
            definition.attribute,
            qualname,
            source,
            signature,
            hashlib.sha256(signature.encode("utf-8")).hexdigest(),
            _expected_callable_kind(definition),
            code_sha,
            definition.strategy,
            definition.classifier_id,
            definition.policy_id,
        )
        if immutable != expected:
            raise ValueError("observer target metadata differs from final source")
    get_pipeline = observed["docling-get-pipeline"]
    if manifest.docling_get_pipeline_signature_sha256 != (
        get_pipeline.signature_sha256
    ):
        raise ValueError("Docling pipeline signature identity differs")
