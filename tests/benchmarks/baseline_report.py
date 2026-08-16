"""P00-US03 catastrophe-only baseline capture and report contracts.

This module is test/reporting tooling.  It deliberately does not implement the
15-case corpus runner owned by P00-US05 and must never be imported by ``app``.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import resource
import subprocess
import sys
import time
import traceback
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, model_validator

from tests.benchmarks.contracts import (
    ContractModel,
    FixtureManifest,
    MetricRecord,
    MetricUnit,
    NonEmptyString,
    RunRecord,
    SchemaVersion,
    Sha256,
    TruthClass,
)
from tests.benchmarks.source_truth import (
    ArtifactRole,
    CatastropheSourceTruth,
    load_catastrophe_source_truth,
)


WORKSPACE = Path(__file__).resolve().parents[2]
RUNNER_VERSION = "P00-US03-1.0"
VOLATILE_JSON_POINTERS = ("/processing/duration_ms",)
QualityCategory = Literal[
    "text",
    "layout",
    "table",
    "chart",
    "visual",
    "page_identity",
    "diagnostics",
    "serialization",
]
REQUIRED_QUALITY_IDS = {
    "exhibit_7_table_exact",
    "damaged_sentence_exact",
    "exhibit_7_caption_separate",
    "exhibit_8_title_separate",
    "chart_source_note_present",
    "chart_routed_as_chart",
    "chart_year_anchors_structured",
    "chart_1h_legend_present",
    "chart_series_structured",
    "unsupported_chart_values_withheld",
    "logo_aon_retained_in_json",
    "logo_aon_present_in_markdown",
    "printed_page_identity_distinct",
    "targeted_defect_diagnostics",
    "backend_frontend_markdown_parity",
}
REQUIRED_COMPATIBILITY_GATES = {
    "backend_api_schema_serializer",
    "backend_full_regression",
    "frontend_typecheck",
    "frontend_lint",
    "frontend_unit",
}
EXPECTED_API_SCHEMA_HASHES = {
    "openapi": (
        "3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a"
    ),
    "parse_result": (
        "706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f"
    ),
    "error_response": (
        "3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6"
    ),
}
EXPECTED_GATE_COMMANDS = {
    "backend_api_schema_serializer": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
        "tests/test_api.py",
        "tests/test_serializer.py",
        "tests/contract",
    ),
    "backend_full_regression": (
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
    ),
    "frontend_typecheck": (
        "/opt/homebrew/opt/node@24/bin/node",
        "node_modules/typescript/bin/tsc",
        "--noEmit",
        "--pretty",
        "false",
    ),
    "frontend_lint": (
        "/opt/homebrew/opt/node@24/bin/node",
        "node_modules/eslint/bin/eslint.js",
        ".",
        "--ignore-pattern",
        "dist",
        "--ignore-pattern",
        ".next",
        "--ignore-pattern",
        "public/pdf.worker.min.mjs",
    ),
    "frontend_unit": (
        "/opt/homebrew/opt/node@24/bin/node",
        "--experimental-strip-types",
        "--test",
        "tests/*.test.mts",
    ),
}
EXPECTED_FULL_REGRESSION_SKIPS = {
    (
        "tests/test_image_integration.py::"
        "test_real_text_form_and_table_image_preserves_available_content"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_image_integration.py::"
        "test_real_http_endpoint_accepts_image_multipart"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_image_integration.py::"
        "test_real_visual_classification_is_confidence_gated_and_"
        "non_fabricating[chart-chart]"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_image_integration.py::"
        "test_real_visual_classification_is_confidence_gated_and_"
        "non_fabricating[diagram-diagram]"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_image_integration.py::"
        "test_real_multipage_tiff_keeps_frame_order_and_markdown"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_image_integration.py::"
        "test_supplied_photo_cover_has_clean_primary_output_and_region_roles"
    ): (
        "image-pipeline-maintainers",
        "Set RUN_IMAGE_INTEGRATION=1 to run real image models.",
        "RUN_IMAGE_INTEGRATION=1",
    ),
    (
        "tests/test_sample_integration.py::"
        "test_full_sample_pipeline_matches_reference_invariants"
    ): (
        "backend-parser-maintainers",
        "Set RUN_INTEGRATION=1 to run the Docling sample pipeline.",
        "RUN_INTEGRATION=1",
    ),
    (
        "tests/test_sample_integration.py::"
        "test_generic_workaround_page_seven_preserves_complete_paragraph"
    ): (
        "backend-parser-maintainers",
        "Set RUN_INTEGRATION=1 to run the Docling regression pipeline.",
        "RUN_INTEGRATION=1",
    ),
    (
        "tests/test_sample_integration.py::"
        "test_finance_pdf_retains_reference_pages_headings_and_tables"
    ): (
        "backend-parser-maintainers",
        "Set RUN_INTEGRATION=1 to run the finance PDF regression.",
        "RUN_INTEGRATION=1",
    ),
    (
        "tests/test_shared_analysis_pipeline.py::"
        "test_real_direct_image_and_full_page_pdf_preserve_unique_title"
    ): (
        "shared-analysis-maintainers",
        (
            "Set RUN_SHARED_ANALYSIS_INTEGRATION=1 to run real cross-format "
            "OCR/layout parity."
        ),
        "RUN_SHARED_ANALYSIS_INTEGRATION=1",
    ),
}
REQUIRED_ENVIRONMENT_FIELDS = {
    "platform",
    "machine",
    "processor",
    "logical_cpu_count",
    "python",
    "python_executable",
    "node",
    "application",
    "pytest",
    "pydantic",
    "docling",
    "docling-core",
    "pdfplumber",
    "pypdfium2",
    "pillow",
    "tesseract",
    "source_tree_sha256",
}
REQUIRED_VERSION_FIELDS = {
    "application",
    "docling",
    "docling-core",
    "pdfplumber",
    "pypdfium2",
    "pillow",
    "tesseract",
    "node",
    "source_tree_sha256",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "max_upload_bytes": 25 * 1024 * 1024,
    "max_pages": 100,
    "max_image_pixels": 50_000_000,
    "max_image_total_pixels": 100_000_000,
    "document_timeout_seconds": 300.0,
    "ocr_languages": ("eng",),
    "tesseract_cmd": "tesseract",
    "tesseract_data_path": None,
    "targeted_ocr_timeout_seconds": 30.0,
    "targeted_ocr_scale": 5.0,
    "targeted_ocr_max_pixels": 16_000_000,
    "docling_artifacts_path": None,
    "image_primary_ocr_min_confidence": 0.45,
    "image_low_confidence_min_alnum_chars": 8,
    "image_heading_min_confidence": 0.75,
    "image_heading_height_ratio": 1.8,
    "image_heading_min_page_height_ratio": 0.025,
    "image_picture_classification_threshold": 0.6,
    "image_captioning_enabled": False,
    "image_captioning_prompt": (
        "Describe this visible image faithfully in one concise sentence. "
        "Do not infer hidden text, values, or relationships."
    ),
    "pdf_visual_analysis_enabled": True,
    "pdf_render_ocr_min_native_alnum_chars": 24,
    "pdf_render_ocr_min_layout_coverage": 0.55,
}
DEFAULT_EXECUTION_POLICY: dict[str, object] = {
    "hosted_services": "disabled",
    "image_captioning": False,
    "optional_models": "disabled",
    "hf_hub_offline": True,
    "transformers_offline": True,
    "tokenizers_parallelism": False,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_utc_timestamp(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def require_supported_node(value: str, *, label: str) -> None:
    match = re.search(
        r"(?:^|\s)v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:$|\s)",
        value,
    )
    if match is None:
        raise ValueError(f"{label} requires a recorded Node.js version")
    version = tuple(
        int(match.group(part)) for part in ("major", "minor", "patch")
    )
    if version < (22, 13, 0):
        raise ValueError(f"{label} requires Node.js >=22.13.0")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_payload_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def semantic_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Hashable output projection with one declared volatile field removed."""

    projected = json.loads(json.dumps(payload, allow_nan=False))
    processing = projected.get("processing")
    if isinstance(processing, dict):
        processing.pop("duration_ms", None)
    return canonical_payload_bytes(projected)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def portable_workspace_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(WORKSPACE).as_posix()
    except ValueError:
        return resolved.as_posix()


def validate_portable_path(value: str, *, label: str) -> None:
    pure_path = PurePosixPath(value)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise ValueError(f"{label} must be a portable workspace path")


def validate_registered_artifacts(
    truth: CatastropheSourceTruth,
) -> None:
    """Fail closed if any immutable source/expert artifact changed."""

    for artifact in truth.artifacts:
        validate_portable_path(artifact.path, label=f"{artifact.role} path")
        path = WORKSPACE / artifact.path
        if not path.is_file():
            raise ValueError(f"registered artifact is missing: {artifact.path}")
        if path.stat().st_size != artifact.size_bytes:
            raise ValueError(
                f"registered artifact size changed: {artifact.path}"
            )
        if sha256_path(path) != artifact.sha256:
            raise ValueError(
                f"registered artifact hash changed: {artifact.path}"
            )


def normalized_peak_rss_bytes() -> int:
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def command_version(command: str, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            [command, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (completed.stdout or completed.stderr).splitlines()
    return lines[0].strip() if lines else None


def source_tree_hash() -> str:
    digest = hashlib.sha256()
    paths = list((WORKSPACE / "app").rglob("*.py"))
    paths.extend(
        WORKSPACE / path
        for path in (
            "frontend/lib/normalize-document-json.ts",
            "frontend/lib/serialize-output.ts",
            "frontend/lib/types.ts",
            "tests/benchmarks/baseline_report.py",
            "tests/benchmarks/contracts.py",
            "tests/benchmarks/frontend_projection.mts",
            "tests/benchmarks/source_truth.py",
            "pyproject.toml",
            "uv.lock",
            "frontend/package.json",
            "frontend/package-lock.json",
        )
        if (WORKSPACE / path).is_file()
    )
    paths.sort()
    for path in paths:
        relative = path.relative_to(WORKSPACE).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def environment_metadata(node_command: str) -> dict[str, str]:
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "logical_cpu_count": str(os.cpu_count() or "unknown"),
        "python": sys.version,
        "python_executable": sys.executable,
        "node": command_version(node_command, "--version") or "unavailable",
        "application": package_version("document-parse-api") or "unavailable",
        "pytest": package_version("pytest") or "unavailable",
        "pydantic": package_version("pydantic") or "unavailable",
        "docling": package_version("docling") or "unavailable",
        "docling-core": package_version("docling-core") or "unavailable",
        "pdfplumber": package_version("pdfplumber") or "unavailable",
        "pypdfium2": package_version("pypdfium2") or "unavailable",
        "pillow": package_version("Pillow") or "unavailable",
        "tesseract": (
            command_version(DEFAULT_SETTINGS["tesseract_cmd"], "--version")
            or "unavailable"
        ),
        "source_tree_sha256": source_tree_hash(),
    }
    return dict(sorted(metadata.items()))


class OutputEvidence(ContractModel):
    raw_json_path: NonEmptyString
    raw_json_sha256: Sha256
    raw_json_size_bytes: int = Field(gt=0)
    semantic_json_sha256: Sha256
    semantic_json_size_bytes: int = Field(gt=0)
    backend_markdown_path: NonEmptyString
    backend_markdown_sha256: Sha256
    backend_markdown_size_bytes: int = Field(gt=0)
    frontend_normalized_json_path: NonEmptyString
    frontend_normalized_json_sha256: Sha256
    frontend_normalized_json_size_bytes: int = Field(gt=0)
    frontend_markdown_path: NonEmptyString
    frontend_markdown_sha256: Sha256
    frontend_markdown_size_bytes: int = Field(gt=0)
    frontend_text_path: NonEmptyString
    frontend_text_sha256: Sha256
    frontend_text_size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def require_portable_paths(self) -> "OutputEvidence":
        for field_name in (
            "raw_json_path",
            "backend_markdown_path",
            "frontend_normalized_json_path",
            "frontend_markdown_path",
            "frontend_text_path",
        ):
            validate_portable_path(
                str(getattr(self, field_name)),
                label=field_name,
            )
        return self


class QualityCheck(ContractModel):
    check_id: NonEmptyString
    gap_id: NonEmptyString
    category: QualityCategory
    passed: bool
    expected: NonEmptyString
    observed: NonEmptyString
    evidence_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    safety_guardrail: bool = False


class ExecutionPolicy(ContractModel):
    hosted_services: Literal["disabled"]
    image_captioning: Literal[False]
    optional_models: Literal["disabled"]
    hf_hub_offline: Literal[True]
    transformers_offline: Literal[True]
    tokenizers_parallelism: Literal[False]


class ReferenceRun(ContractModel):
    schema_version: SchemaVersion
    runner_version: NonEmptyString
    run_id: NonEmptyString
    status: Literal["success", "error", "timeout"]
    fixture_id: NonEmptyString
    source_sha256: Sha256
    expert_markdown_sha256: Sha256
    expert_json_sha256: Sha256
    truth_sha256: Sha256
    started_at_utc: NonEmptyString
    completed_at_utc: NonEmptyString
    command: tuple[NonEmptyString, ...] = Field(min_length=1)
    cwd: NonEmptyString
    settings_sha256: Sha256
    execution_policy: ExecutionPolicy
    environment: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    versions: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    cpu_ms: float = Field(ge=0)
    peak_rss_bytes: int = Field(gt=0)
    output: OutputEvidence | None
    quality_checks: tuple[QualityCheck, ...] = ()
    error: dict[NonEmptyString, object] | None = Field(
        default=None,
        min_length=1,
    )

    @model_validator(mode="after")
    def require_complete_success_or_explicit_failure(self) -> "ReferenceRun":
        validate_portable_path(self.cwd, label="cwd")
        started_at = validate_utc_timestamp(
            self.started_at_utc,
            label="started_at_utc",
        )
        completed_at = validate_utc_timestamp(
            self.completed_at_utc,
            label="completed_at_utc",
        )
        if completed_at < started_at:
            raise ValueError("run completion cannot precede its start")
        missing_environment = REQUIRED_ENVIRONMENT_FIELDS - self.environment.keys()
        if missing_environment:
            raise ValueError(
                "run environment is missing required fields: "
                + ", ".join(sorted(missing_environment))
            )
        missing_versions = REQUIRED_VERSION_FIELDS - self.versions.keys()
        if missing_versions:
            raise ValueError(
                "run versions are missing required fields: "
                + ", ".join(sorted(missing_versions))
            )
        if (
            self.versions["source_tree_sha256"]
            != self.environment["source_tree_sha256"]
        ):
            raise ValueError("run source-tree identities must agree")
        require_supported_node(
            self.environment["node"],
            label="run",
        )
        if self.status == "success":
            if self.output is None:
                raise ValueError("successful runs require complete output evidence")
            if self.error is not None:
                raise ValueError("successful runs cannot retain an error")
            quality_ids = {check.check_id for check in self.quality_checks}
            if quality_ids != REQUIRED_QUALITY_IDS:
                raise ValueError(
                    "successful runs require every registered quality check"
                )
            if len(quality_ids) != len(self.quality_checks):
                raise ValueError("quality check IDs must be unique")
        else:
            if self.error is None:
                raise ValueError("failed or timed-out runs require explicit error")
        return self

    def run_contract(self) -> RunRecord:
        if self.output is None:
            raise ValueError("failed runs cannot project to RunRecord")
        parser_version = self.versions.get("application")
        if not parser_version:
            raise ValueError("application version is required")
        model_versions = {
            key: value
            for key, value in self.versions.items()
            if key in {"docling", "docling-core", "tesseract", "pypdfium2"}
        }
        metrics = (
            MetricRecord(
                schema_version=self.schema_version,
                metric_name="parse_duration",
                measurement_method="isolated cold worker wall clock",
                fixture_id=self.fixture_id,
                value=self.duration_ms,
                unit=MetricUnit.MILLISECONDS,
                tolerance=0,
                evidence_class=TruthClass.MEASURED,
            ),
            MetricRecord(
                schema_version=self.schema_version,
                metric_name="worker_cpu",
                measurement_method="isolated worker process CPU clock",
                fixture_id=self.fixture_id,
                value=self.cpu_ms,
                unit=MetricUnit.MILLISECONDS,
                tolerance=0,
                evidence_class=TruthClass.MEASURED,
            ),
            MetricRecord(
                schema_version=self.schema_version,
                metric_name="worker_peak_rss",
                measurement_method="isolated worker ru_maxrss",
                fixture_id=self.fixture_id,
                value=self.peak_rss_bytes / (1024 * 1024),
                unit=MetricUnit.MEBIBYTES,
                tolerance=0,
                evidence_class=TruthClass.MEASURED,
            ),
            MetricRecord(
                schema_version=self.schema_version,
                metric_name="raw_json_size",
                measurement_method="UTF-8 artifact byte count",
                fixture_id=self.fixture_id,
                value=self.output.raw_json_size_bytes,
                unit=MetricUnit.BYTES,
                tolerance=0,
                evidence_class=TruthClass.MEASURED,
            ),
            MetricRecord(
                schema_version=self.schema_version,
                metric_name="backend_markdown_size",
                measurement_method="UTF-8 artifact byte count",
                fixture_id=self.fixture_id,
                value=self.output.backend_markdown_size_bytes,
                unit=MetricUnit.BYTES,
                tolerance=0,
                evidence_class=TruthClass.MEASURED,
            ),
        )
        return RunRecord(
            schema_version=self.schema_version,
            run_id=self.run_id,
            parser_version=parser_version,
            model_versions=model_versions,
            commands=(" ".join(self.command),),
            hardware={
                "platform": self.environment["platform"],
                "machine": self.environment["machine"],
                "logical_cpu_count": self.environment["logical_cpu_count"],
            },
            fixture_hashes={
                "source_pdf": self.source_sha256,
                "expert_markdown": self.expert_markdown_sha256,
                "expert_json": self.expert_json_sha256,
                "source_truth": self.truth_sha256,
            },
            output_hashes={
                "raw_json": self.output.raw_json_sha256,
                "semantic_json": self.output.semantic_json_sha256,
                "backend_markdown": self.output.backend_markdown_sha256,
                "frontend_normalized_json": (
                    self.output.frontend_normalized_json_sha256
                ),
                "frontend_markdown": self.output.frontend_markdown_sha256,
                "frontend_text": self.output.frontend_text_sha256,
            },
            duration_ms=self.duration_ms,
            metrics=metrics,
        )


class DistributionSummary(ContractModel):
    count: int = Field(ge=1)
    minimum: float = Field(ge=0)
    p50: float = Field(ge=0)
    p95: float = Field(ge=0)
    maximum: float = Field(ge=0)
    mean: float = Field(ge=0)
    unit: MetricUnit
    percentile_method: Literal["nearest_rank"]


class SkipRecord(ContractModel):
    node_id: NonEmptyString
    owner_role: NonEmptyString
    reason: NonEmptyString
    opt_in_condition: NonEmptyString


class VerificationGate(ContractModel):
    gate_id: NonEmptyString
    command: tuple[NonEmptyString, ...] = Field(min_length=1)
    cwd: NonEmptyString
    runtime: NonEmptyString
    status: Literal["pass", "fail"]
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    skip_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    skip_records: tuple[SkipRecord, ...] = ()
    evidence: NonEmptyString

    @model_validator(mode="after")
    def require_honest_gate_status(self) -> "VerificationGate":
        validate_portable_path(self.cwd, label="gate cwd")
        if self.status == "pass" and self.fail_count != 0:
            raise ValueError("passing gates cannot hide failures")
        if self.status == "pass" and self.pass_count == 0:
            raise ValueError("passing gates require a successful assertion count")
        if self.status == "fail" and self.fail_count == 0:
            raise ValueError("failing gates require a nonzero failure count")
        if self.skip_count != len(self.skip_records):
            raise ValueError("gate skip count must equal explicit skip records")
        node_ids = [record.node_id for record in self.skip_records]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("skip node IDs must be unique within a gate")
        return self


class CompatibilityEvidence(ContractModel):
    schema_version: SchemaVersion
    captured_at_utc: NonEmptyString
    api_schema_hashes: dict[NonEmptyString, Sha256] = Field(min_length=3)
    gates: tuple[VerificationGate, ...] = Field(min_length=5)

    @model_validator(mode="after")
    def require_compatibility_gates(self) -> "CompatibilityEvidence":
        validate_utc_timestamp(
            self.captured_at_utc,
            label="captured_at_utc",
        )
        gate_ids = {gate.gate_id for gate in self.gates}
        if len(gate_ids) != len(self.gates):
            raise ValueError("compatibility gate IDs must be unique")
        if not REQUIRED_COMPATIBILITY_GATES <= gate_ids:
            raise ValueError("required API and frontend gates are missing")
        if self.api_schema_hashes != EXPECTED_API_SCHEMA_HASHES:
            raise ValueError("API schema hashes must match the captured contract")
        if any(gate.status != "pass" for gate in self.gates):
            raise ValueError("compatibility evidence cannot normalize failures")
        gates = {gate.gate_id: gate for gate in self.gates}
        for gate_id, expected_command in EXPECTED_GATE_COMMANDS.items():
            gate = gates[gate_id]
            if gate.command != expected_command:
                raise ValueError(f"{gate_id} command does not match the gate")
            expected_cwd = "frontend" if gate_id.startswith("frontend_") else "."
            if gate.cwd != expected_cwd:
                raise ValueError(f"{gate_id} cwd does not match the gate")
            if gate_id.startswith("frontend_"):
                require_supported_node(gate.runtime, label=gate_id)
            elif "Python " not in gate.runtime:
                raise ValueError(f"{gate_id} requires a recorded Python runtime")

        full_gate = gates["backend_full_regression"]
        skip_payload = {
            record.node_id: (
                record.owner_role,
                record.reason,
                record.opt_in_condition,
            )
            for record in full_gate.skip_records
        }
        if skip_payload != EXPECTED_FULL_REGRESSION_SKIPS:
            raise ValueError(
                "backend full regression requires the exact active skip inventory"
            )
        for gate_id, gate in gates.items():
            if gate_id != "backend_full_regression" and gate.skip_count != 0:
                raise ValueError(
                    "active skips belong only to backend_full_regression"
                )
        return self


class StabilitySummary(ContractModel):
    fixture_hashes_stable: bool
    quality_outcomes_stable: bool
    semantic_json_hashes_stable: bool
    backend_markdown_hashes_stable: bool
    frontend_markdown_hashes_stable: bool
    frontend_text_hashes_stable: bool
    raw_json_unique_hash_count: int = Field(ge=1)
    frontend_normalized_json_unique_hash_count: int = Field(ge=1)
    volatility_allowlist: tuple[NonEmptyString, ...]


class BaselineReport(ContractModel):
    schema_version: SchemaVersion
    report_id: NonEmptyString
    runner_version: NonEmptyString
    fixture: FixtureManifest
    expert_markdown_sha256: Sha256
    expert_json_sha256: Sha256
    truth_sha256: Sha256
    source_rights_sha256: Sha256
    generated_from_run_set: NonEmptyString
    reference_command: tuple[NonEmptyString, ...] = Field(min_length=1)
    settings: dict[NonEmptyString, object] = Field(min_length=1)
    settings_sha256: Sha256
    execution_policy: ExecutionPolicy
    environment: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    run_count: int = Field(ge=5)
    runs: tuple[ReferenceRun, ...] = Field(min_length=5)
    duration_ms: DistributionSummary
    peak_rss_mib: DistributionSummary
    quality_pass_count: int = Field(ge=0)
    quality_fail_count: int = Field(ge=0)
    quality_signature: Sha256
    stability: StabilitySummary
    compatibility: CompatibilityEvidence

    @model_validator(mode="after")
    def require_complete_reproducible_report(self) -> "BaselineReport":
        validate_portable_path(
            self.generated_from_run_set,
            label="generated_from_run_set",
        )
        if self.fixture.fixture_id != "catastrophe-recap":
            raise ValueError("P00-US03 is limited to catastrophe-recap")
        if self.fixture.custody != "public-redistributable":
            raise ValueError("P00-US03 requires approved source custody")
        if self.fixture.source_format != "PDF":
            raise ValueError("P00-US03 requires the registered PDF fixture")
        if (
            sha256_bytes(canonical_payload_bytes(self.settings))
            != self.settings_sha256
        ):
            raise ValueError("report settings hash must match its payload")
        if self.run_count != len(self.runs):
            raise ValueError("run_count must match the retained run records")
        run_ids = [run.run_id for run in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("reference run IDs must be unique")
        if any(run.status != "success" for run in self.runs):
            raise ValueError("partial, failed, or timed-out runs fail closed")
        for run in self.runs:
            if (
                run.runner_version != self.runner_version
                or run.fixture_id != self.fixture.fixture_id
                or run.source_sha256 != self.fixture.source_sha256
                or run.expert_markdown_sha256 != self.expert_markdown_sha256
                or run.expert_json_sha256 != self.expert_json_sha256
                or run.truth_sha256 != self.truth_sha256
                or run.settings_sha256 != self.settings_sha256
                or run.execution_policy != self.execution_policy
            ):
                raise ValueError("run fixture/settings identities must match")
            if run.environment != self.environment:
                raise ValueError(
                    "every run must retain the report environment identity"
                )
            run.run_contract()

        expected_duration = summarize_distribution(
            [run.duration_ms for run in self.runs],
            MetricUnit.MILLISECONDS,
        )
        expected_rss = summarize_distribution(
            [run.peak_rss_bytes / (1024 * 1024) for run in self.runs],
            MetricUnit.MEBIBYTES,
        )
        if self.duration_ms != expected_duration:
            raise ValueError("duration distribution must match raw runs")
        if self.peak_rss_mib != expected_rss:
            raise ValueError("RSS distribution must match raw runs")

        first_outcomes = quality_outcome_payload(self.runs[0].quality_checks)
        if any(
            quality_outcome_payload(run.quality_checks) != first_outcomes
            for run in self.runs[1:]
        ):
            raise ValueError("quality outcomes must reproduce across every run")
        pass_count = sum(check.passed for check in self.runs[0].quality_checks)
        fail_count = len(self.runs[0].quality_checks) - pass_count
        if (
            self.quality_pass_count != pass_count
            or self.quality_fail_count != fail_count
        ):
            raise ValueError("quality counts must match the atomic findings")
        expected_signature = sha256_bytes(
            canonical_payload_bytes(first_outcomes)
        )
        if self.quality_signature != expected_signature:
            raise ValueError("quality signature must match atomic outcomes")

        expected_stability = summarize_stability(self.runs)
        if self.stability != expected_stability:
            raise ValueError("stability summary must match the raw runs")
        stable_flags = (
            self.stability.fixture_hashes_stable,
            self.stability.quality_outcomes_stable,
            self.stability.semantic_json_hashes_stable,
            self.stability.backend_markdown_hashes_stable,
            self.stability.frontend_markdown_hashes_stable,
            self.stability.frontend_text_hashes_stable,
        )
        if not all(stable_flags):
            raise ValueError(
                "fixture, quality, semantic, Markdown, and text evidence "
                "must remain stable"
            )
        if self.stability.volatility_allowlist != VOLATILE_JSON_POINTERS:
            raise ValueError("only the declared duration field may be volatile")
        return self


def nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(float(value) for value in values)
    if not all(math.isfinite(value) and value >= 0 for value in ordered):
        raise ValueError("distribution values must be finite and non-negative")
    index = max(math.ceil(percentile * len(ordered)) - 1, 0)
    return ordered[index]


def summarize_distribution(
    values: Sequence[float],
    unit: MetricUnit,
) -> DistributionSummary:
    finite_values = [float(value) for value in values]
    if not finite_values:
        raise ValueError("distribution requires samples")
    return DistributionSummary(
        count=len(finite_values),
        minimum=min(finite_values),
        p50=nearest_rank(finite_values, 0.50),
        p95=nearest_rank(finite_values, 0.95),
        maximum=max(finite_values),
        mean=sum(finite_values) / len(finite_values),
        unit=unit,
        percentile_method="nearest_rank",
    )


def _primary_item_text(item: Mapping[str, Any]) -> str:
    value = item.get("value")
    if isinstance(value, str):
        return value
    markdown = item.get("md")
    return markdown if isinstance(markdown, str) else ""


def _all_string_evidence(item: Mapping[str, Any]) -> list[str]:
    """Return selected top-level and accepted child evidence, never raw OCR."""

    values: list[str] = []
    for key in ("value", "md", "ocr_text", "caption"):
        value = item.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    for child in item.get("items") or []:
        if isinstance(child, Mapping) and child.get("accepted") is True:
            for key in ("text", "value"):
                value = child.get(key)
                if isinstance(value, str) and value:
                    values.append(value)
    return values


def _reading_order(item: Mapping[str, Any]) -> int | None:
    value = item.get("reading_order")
    return value if isinstance(value, int) and value >= 0 else None


def _separate_ordered_item(
    items: Sequence[Mapping[str, Any]],
    expected_text: str,
    *,
    relative_to: Mapping[str, Any],
    position: Literal["before", "after"],
) -> bool:
    """Require one standalone text-like item on the correct side of a target."""

    target_order = _reading_order(relative_to)
    if target_order is None:
        return False
    candidates = [
        item
        for item in items
        if item.get("type") not in {"table", "chart", "image", "header", "footer"}
        and _primary_item_text(item).strip() == expected_text
        and _reading_order(item) is not None
    ]
    if len(candidates) != 1:
        return False
    candidate_order = _reading_order(candidates[0])
    assert candidate_order is not None
    if position == "before":
        return candidate_order < target_order
    return candidate_order > target_order


def _normalized_header(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _is_chart_value_table(item: Mapping[str, Any]) -> bool:
    if item.get("type") != "table":
        return False
    value = item.get("value")
    if not isinstance(value, list) or not value or not isinstance(value[0], list):
        return False
    headers = {_normalized_header(column) for column in value[0]}
    has_region = "region" in headers
    has_year = "year" in headers
    has_annual = any(header in {"annual", "annualtotal"} for header in headers)
    has_first_half = any(
        header in {"1h", "firsthalf", "firsthalftotal"} for header in headers
    )
    return has_region and has_year and has_annual and has_first_half


def evaluate_catastrophe_quality(
    payload: Mapping[str, Any],
    backend_markdown: str,
    frontend_markdown: str,
    truth: CatastropheSourceTruth,
) -> tuple[QualityCheck, ...]:
    pages = payload.get("pages")
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError("catastrophe baseline requires exactly one output page")
    page = pages[0]
    if not isinstance(page, Mapping):
        raise ValueError("output page must be an object")
    items = page.get("items")
    if not isinstance(items, list):
        raise ValueError("output page items must be a list")
    typed_items = [item for item in items if isinstance(item, Mapping)]
    elements = {element.element_id: element for element in truth.elements}
    primary_evidence = "\n".join(
        _primary_item_text(item)
        for item in typed_items
        if item.get("type") in {"text", "paragraph", "heading", "list_item"}
    )

    expected_table = [
        [
            cell.text
            for cell in sorted(
                (
                    cell
                    for cell in truth.table_cells
                    if cell.row == row
                ),
                key=lambda cell: cell.column,
            )
        ]
        for row in range(truth.table.row_count)
    ]
    actual_tables = [
        item.get("value")
        for item in typed_items
        if item.get("type") == "table"
    ]
    table_exact = expected_table in actual_tables
    exhibit7_table_item = next(
        (
            item
            for item in typed_items
            if item.get("type") == "table"
            and item.get("value") == expected_table
        ),
        None,
    )

    damaged_sentence = elements["damaged-sentence"].text or ""
    exhibit7_title = elements["exhibit-7-title"].text or ""
    exhibit8_title = elements["exhibit-8-title"].text or ""
    source_note = elements["chart-source-note"].text or ""
    chart_items = [item for item in typed_items if item.get("type") == "chart"]
    chart = chart_items[0] if len(chart_items) == 1 else {}
    chart_children = [
        child
        for child in chart.get("items") or []
        if isinstance(child, Mapping) and child.get("accepted") is True
    ]
    child_texts = [
        str(child.get("text") or child.get("value") or "")
        for child in chart_children
    ]
    expected_chart_labels = {label.text for label in truth.chart_labels}
    exact_chart_labels = expected_chart_labels & set(child_texts)
    year_anchor_count = sum(
        text in {"2015", "2020", "2025"} for text in child_texts
    )
    fused_year_anchors = "201520202025" * 4
    year_anchors_structured = (
        year_anchor_count == 12 and fused_year_anchors not in child_texts
    )
    separate_exhibit7 = bool(
        exhibit7_table_item
        and _separate_ordered_item(
            typed_items,
            exhibit7_title,
            relative_to=exhibit7_table_item,
            position="before",
        )
    )
    separate_exhibit8 = bool(
        chart
        and _separate_ordered_item(
            typed_items,
            exhibit8_title,
            relative_to=chart,
            position="before",
        )
        and exhibit8_title not in "\n".join(_all_string_evidence(chart))
    )
    separate_source_note = bool(
        chart
        and _separate_ordered_item(
            typed_items,
            source_note,
            relative_to=chart,
            position="after",
        )
    )
    chart_series_structured = bool(
        chart.get("series")
        or chart.get("structured_values")
        or chart.get("data_points")
    )
    unsupported_values_withheld = not chart_series_structured and not any(
        _is_chart_value_table(item) for item in typed_items
    )
    logo_json = any(
        item.get("type") == "image"
        and any(
            isinstance(child, Mapping)
            and child.get("accepted") is True
            and "AON"
            in str(child.get("text") or child.get("value") or "")
            for child in item.get("items") or []
        )
        for item in typed_items
    )
    printed_identity = (
        page.get("page_index") == truth.page.physical_page
        and str(page.get("page_label")) == truth.page.printed_page
    )
    item_concerns = sum(
        len(item.get("parse_concerns") or []) for item in typed_items
    )
    document_warnings = payload.get("warnings") or []

    def check(
        check_id: str,
        gap_id: str,
        category: QualityCategory,
        passed: bool,
        expected: str,
        observed: str,
        evidence_ids: tuple[str, ...],
        *,
        safety_guardrail: bool = False,
    ) -> QualityCheck:
        return QualityCheck(
            check_id=check_id,
            gap_id=gap_id,
            category=category,
            passed=passed,
            expected=expected,
            observed=observed,
            evidence_ids=evidence_ids,
            safety_guardrail=safety_guardrail,
        )

    checks = (
        check(
            "exhibit_7_table_exact",
            "catastrophe-positive-table",
            "table",
            table_exact,
            "One exact 6x5 Exhibit 7 table with 30 explicit cells.",
            f"exact_table_match={table_exact}; table_count={len(actual_tables)}",
            ("exhibit-7-table",),
            safety_guardrail=True,
        ),
        check(
            "damaged_sentence_exact",
            "GAP-UNICODE-001",
            "text",
            damaged_sentence in primary_evidence,
            damaged_sentence,
            (
                "exact damaged sentence present"
                if damaged_sentence in primary_evidence
                else "output retains the corrupted 'É w' / '€ ' fragments"
            ),
            ("damaged-sentence",),
        ),
        check(
            "exhibit_7_caption_separate",
            "GAP-LAYOUT-001",
            "layout",
            separate_exhibit7,
            "Exhibit 7 title is a separate ordered caption.",
            (
                "separate caption present"
                if separate_exhibit7
                else "Exhibit 7 title omitted"
            ),
            ("exhibit-7-title", "exhibit-7-table"),
        ),
        check(
            "exhibit_8_title_separate",
            "GAP-LAYOUT-001",
            "layout",
            separate_exhibit8,
            "Exhibit 8 title is separate from chart-internal OCR.",
            (
                "separate title present"
                if separate_exhibit8
                else "title is merged into the chart item with internal noise"
            ),
            ("exhibit-8-title", "exhibit-8-chart"),
        ),
        check(
            "chart_source_note_present",
            "GAP-LAYOUT-001",
            "layout",
            separate_source_note,
            f"{source_note} appears as a separate item after Exhibit 8.",
            (
                "separate ordered source note present"
                if separate_source_note
                else "separate ordered source note omitted"
            ),
            ("chart-source-note", "exhibit-8-chart"),
        ),
        check(
            "chart_routed_as_chart",
            "GAP-CHART-001",
            "chart",
            len(chart_items) == 1,
            "Exactly one chart-typed Exhibit 8 item.",
            f"chart_item_count={len(chart_items)}",
            ("exhibit-8-chart",),
            safety_guardrail=True,
        ),
        check(
            "chart_year_anchors_structured",
            "GAP-CHART-001",
            "chart",
            year_anchors_structured,
            (
                "Twelve year anchors remain individually represented without "
                "a fused duplicate label stream."
            ),
            (
                f"individual_year_anchor_count={year_anchor_count}; "
                f"fused_duplicate_present={fused_year_anchors in child_texts}"
            ),
            tuple(
                label.annotation_id
                for label in truth.chart_labels
                if label.label_type == "year_anchor"
            ),
        ),
        check(
            "chart_1h_legend_present",
            "GAP-CHART-001",
            "chart",
            "1H" in child_texts,
            "The literal 1H legend label is retained.",
            (
                "1H retained"
                if "1H" in child_texts
                else "1H is absent; rejected raw OCR contains 'iH'"
            ),
            (
                next(
                    label.annotation_id
                    for label in truth.chart_labels
                    if label.label_type == "legend" and label.text == "1H"
                ),
            ),
        ),
        check(
            "chart_series_structured",
            "GAP-CHART-001",
            "chart",
            chart_series_structured,
            "Chart labels, series, and marks expose structured associations.",
            (
                "structured chart series present"
                if chart_series_structured
                else (
                    f"0 structured series; {len(exact_chart_labels)}/"
                    f"{len(expected_chart_labels)} printed labels survive as "
                    "exact child strings"
                )
            ),
            ("exhibit-8-chart",),
        ),
        check(
            "unsupported_chart_values_withheld",
            "catastrophe-safer-than-expert",
            "chart",
            unsupported_values_withheld,
            "No unsupported exact Exhibit 8 value table or series is emitted.",
            (
                "0 unsupported structured chart values emitted"
                if unsupported_values_withheld
                else "unsupported structured chart values were emitted"
            ),
            ("negative-unsupported-exact-value",),
            safety_guardrail=True,
        ),
        check(
            "logo_aon_retained_in_json",
            "GAP-VISUAL-001",
            "visual",
            logo_json,
            "Accepted AON OCR remains available in JSON evidence.",
            (
                "AON retained as image-level JSON evidence"
                if logo_json
                else "AON missing from JSON evidence"
            ),
            ("logo-aon",),
            safety_guardrail=True,
        ),
        check(
            "logo_aon_present_in_markdown",
            "GAP-VISUAL-001",
            "visual",
            "AON" in backend_markdown,
            "Primary Markdown preserves source-visible AON.",
            (
                "AON present"
                if "AON" in backend_markdown
                else "generic image placeholder hides accepted AON OCR"
            ),
            ("logo-aon",),
        ),
        check(
            "printed_page_identity_distinct",
            "GAP-PAGE-001",
            "page_identity",
            printed_identity,
            "Physical page 1 and printed page 7 are distinct structured fields.",
            (
                f"page_index={page.get('page_index')}; "
                f"page_label={page.get('page_label')}; printed 7 remains footer text"
            ),
            ("printed-page-label",),
        ),
        check(
            "targeted_defect_diagnostics",
            "GAP-DIAGNOSTICS-001",
            "diagnostics",
            bool(document_warnings) and item_concerns >= 2,
            "Material reviewed defects have localized structured diagnostics.",
            (
                f"document_warning_count={len(document_warnings)}; "
                f"item_concern_count={item_concerns}"
            ),
            (
                "damaged-sentence",
                "exhibit-7-title",
                "chart-source-note",
                "exhibit-8-chart",
            ),
        ),
        check(
            "backend_frontend_markdown_parity",
            "serializer-compatibility",
            "serialization",
            backend_markdown == frontend_markdown,
            "Frontend document Markdown is byte-identical to backend Markdown.",
            (
                "byte-identical"
                if backend_markdown == frontend_markdown
                else "backend/frontend Markdown differs"
            ),
            ("catastrophe-recap",),
            safety_guardrail=True,
        ),
    )
    return checks


def quality_outcome_payload(
    checks: Iterable[QualityCheck],
) -> list[dict[str, object]]:
    return [
        {
            "check_id": check.check_id,
            "gap_id": check.gap_id,
            "passed": check.passed,
            "safety_guardrail": check.safety_guardrail,
        }
        for check in sorted(checks, key=lambda item: item.check_id)
    ]


def summarize_stability(runs: Sequence[ReferenceRun]) -> StabilitySummary:
    if not runs or any(run.output is None for run in runs):
        raise ValueError("stability requires successful output evidence")
    outputs = [run.output for run in runs if run.output is not None]
    fixture_identities = {
        (
            run.source_sha256,
            run.expert_markdown_sha256,
            run.expert_json_sha256,
            run.truth_sha256,
        )
        for run in runs
    }
    quality_payloads = {
        json.dumps(
            quality_outcome_payload(run.quality_checks),
            sort_keys=True,
            separators=(",", ":"),
        )
        for run in runs
    }
    return StabilitySummary(
        fixture_hashes_stable=len(fixture_identities) == 1,
        quality_outcomes_stable=len(quality_payloads) == 1,
        semantic_json_hashes_stable=(
            len({output.semantic_json_sha256 for output in outputs}) == 1
        ),
        backend_markdown_hashes_stable=(
            len({output.backend_markdown_sha256 for output in outputs}) == 1
        ),
        frontend_markdown_hashes_stable=(
            len({output.frontend_markdown_sha256 for output in outputs}) == 1
        ),
        frontend_text_hashes_stable=(
            len({output.frontend_text_sha256 for output in outputs}) == 1
        ),
        raw_json_unique_hash_count=len(
            {output.raw_json_sha256 for output in outputs}
        ),
        frontend_normalized_json_unique_hash_count=len(
            {
                output.frontend_normalized_json_sha256
                for output in outputs
            }
        ),
        volatility_allowlist=VOLATILE_JSON_POINTERS,
    )


def load_reference_run(path: Path) -> ReferenceRun:
    return ReferenceRun.model_validate_json(path.read_bytes())


def load_compatibility(path: Path) -> CompatibilityEvidence:
    return CompatibilityEvidence.model_validate_json(path.read_bytes())


def validate_reference_run_artifacts(
    run: ReferenceRun,
    run_record_path: Path,
    truth: CatastropheSourceTruth,
) -> None:
    """Recompute every retained output claim from immutable run bytes."""

    if run.output is None:
        raise ValueError("successful run is missing output evidence")
    output = run.output
    expected_artifacts = (
        (
            output.raw_json_path,
            "our-output.json",
            output.raw_json_sha256,
            output.raw_json_size_bytes,
        ),
        (
            output.backend_markdown_path,
            "our-output.md",
            output.backend_markdown_sha256,
            output.backend_markdown_size_bytes,
        ),
        (
            output.frontend_normalized_json_path,
            "frontend-normalized.json",
            output.frontend_normalized_json_sha256,
            output.frontend_normalized_json_size_bytes,
        ),
        (
            output.frontend_markdown_path,
            "frontend-markdown.md",
            output.frontend_markdown_sha256,
            output.frontend_markdown_size_bytes,
        ),
        (
            output.frontend_text_path,
            "frontend-text.txt",
            output.frontend_text_sha256,
            output.frontend_text_size_bytes,
        ),
    )
    artifact_paths: dict[str, Path] = {}
    for path_value, basename, expected_hash, expected_size in expected_artifacts:
        path = (WORKSPACE / path_value).resolve()
        expected_path = run_record_path.parent / basename
        if path != expected_path:
            raise ValueError(
                f"{run.run_id} output path is not its fixed {basename} artifact"
            )
        if not path.is_file():
            raise ValueError(f"{run.run_id} output is missing: {basename}")
        data = path.read_bytes()
        if len(data) != expected_size:
            raise ValueError(f"{run.run_id} output size changed: {basename}")
        if sha256_bytes(data) != expected_hash:
            raise ValueError(f"{run.run_id} output hash changed: {basename}")
        artifact_paths[basename] = path

    raw_payload = json.loads(
        artifact_paths["our-output.json"].read_text(encoding="utf-8")
    )
    if not isinstance(raw_payload, Mapping):
        raise ValueError(f"{run.run_id} raw output must be a JSON object")
    document = raw_payload.get("document")
    if (
        not isinstance(document, Mapping)
        or document.get("sha256") != truth.fixture.source_sha256
    ):
        raise ValueError(f"{run.run_id} raw output source identity changed")
    semantic_bytes = semantic_json_bytes(raw_payload)
    if (
        len(semantic_bytes) != output.semantic_json_size_bytes
        or sha256_bytes(semantic_bytes) != output.semantic_json_sha256
    ):
        raise ValueError(f"{run.run_id} semantic output evidence changed")
    normalized_payload = json.loads(
        artifact_paths["frontend-normalized.json"].read_text(encoding="utf-8")
    )
    if not isinstance(normalized_payload, Mapping):
        raise ValueError(
            f"{run.run_id} frontend-normalized output must be an object"
        )
    backend_markdown = artifact_paths["our-output.md"].read_text(
        encoding="utf-8"
    )
    frontend_markdown = artifact_paths["frontend-markdown.md"].read_text(
        encoding="utf-8"
    )
    expected_checks = evaluate_catastrophe_quality(
        raw_payload,
        backend_markdown,
        frontend_markdown,
        truth,
    )
    if expected_checks != run.quality_checks:
        raise ValueError(
            f"{run.run_id} stored quality evidence does not match its outputs"
        )


def build_report(
    *,
    runs_root: Path,
    truth_path: Path,
    source_rights_path: Path,
    compatibility: CompatibilityEvidence,
) -> BaselineReport:
    truth = load_catastrophe_source_truth(truth_path)
    validate_registered_artifacts(truth)
    if (
        portable_workspace_path(source_rights_path)
        != truth.source_use_decision.evidence_path
    ):
        raise ValueError(
            "source-rights evidence does not match the approved truth record"
        )
    run_set_path = runs_root / "run-set.json"
    run_set = json.loads(run_set_path.read_text(encoding="utf-8"))
    if run_set.get("status") != "success":
        raise ValueError("partial or failed run sets fail closed")
    if run_set.get("schema_version") != "1.0":
        raise ValueError("run-set schema version does not match")
    if run_set.get("runner_version") != RUNNER_VERSION:
        raise ValueError("run-set runner version does not match")
    if run_set.get("fixture_id") != truth.fixture.fixture_id:
        raise ValueError("run-set fixture identity does not match")
    if run_set.get("source_sha256") != truth.fixture.source_sha256:
        raise ValueError("run-set source identity does not match")
    if run_set.get("truth_sha256") != sha256_path(truth_path):
        raise ValueError("run-set truth identity does not match")
    raw_run_record_paths = run_set.get("run_record_paths") or []
    if not isinstance(raw_run_record_paths, list):
        raise ValueError("run record paths must be a list")
    if len(raw_run_record_paths) != len(set(raw_run_record_paths)):
        raise ValueError("run record paths must be unique")
    run_record_paths: list[Path] = []
    resolved_runs_root = runs_root.resolve()
    for value in raw_run_record_paths:
        path_value = str(value)
        validate_portable_path(path_value, label="run record path")
        path = (WORKSPACE / path_value).resolve()
        if not path.is_relative_to(resolved_runs_root):
            raise ValueError("run records must remain within the runs root")
        run_record_paths.append(path)
    runs = tuple(load_reference_run(path) for path in run_record_paths)
    if len(runs) < 5:
        raise ValueError("P00-US03 requires at least five retained runs")
    if run_set.get("repeat") != len(runs):
        raise ValueError("run-set repeat count must match retained runs")
    for path, run in zip(run_record_paths, runs, strict=True):
        expected_path = resolved_runs_root / run.run_id / "run-record.json"
        if path != expected_path:
            raise ValueError(
                "run record path must match its immutable run directory"
            )
        validate_reference_run_artifacts(run, path, truth)
    execution_policy = ExecutionPolicy.model_validate(
        run_set.get("execution_policy")
    )
    if execution_policy.model_dump(mode="json") != DEFAULT_EXECUTION_POLICY:
        raise ValueError("run-set execution policy does not match")
    coordinator_results = run_set.get("coordinator_results")
    if (
        not isinstance(coordinator_results, list)
        or len(coordinator_results) != len(runs)
    ):
        raise ValueError("run-set coordinator evidence is incomplete")
    expected_run_ids = [run.run_id for run in runs]
    actual_run_ids: list[str] = []
    for result in coordinator_results:
        if not isinstance(result, dict):
            raise ValueError("coordinator evidence entries must be objects")
        actual_run_ids.append(str(result.get("run_id")))
        if (
            result.get("status") != "success"
            or result.get("worker_exit_code") != 0
            or result.get("run_record_present") is not True
        ):
            raise ValueError("coordinator evidence contains a failed run")
        coordinator_started = validate_utc_timestamp(
            str(result.get("started_at_utc")),
            label="coordinator started_at_utc",
        )
        coordinator_completed = validate_utc_timestamp(
            str(result.get("completed_at_utc")),
            label="coordinator completed_at_utc",
        )
        if coordinator_completed < coordinator_started:
            raise ValueError(
                "coordinator completion cannot precede its start"
            )
    if actual_run_ids != expected_run_ids:
        raise ValueError("coordinator run IDs must match retained run order")
    artifacts = {artifact.role: artifact for artifact in truth.artifacts}
    settings = run_set.get("settings")
    environment = run_set.get("environment")
    reference_command = run_set.get("portable_command")
    if not isinstance(settings, dict) or not settings:
        raise ValueError("run set is missing settings")
    if not isinstance(environment, dict) or not environment:
        raise ValueError("run set is missing environment")
    if environment.get("source_tree_sha256") != source_tree_hash():
        raise ValueError(
            "current source tree does not match the captured runner environment"
        )
    if not isinstance(reference_command, list) or not reference_command:
        raise ValueError("run set is missing its portable command")
    settings_hash = sha256_bytes(canonical_payload_bytes(settings))
    if run_set.get("settings_sha256") != settings_hash:
        raise ValueError("run-set settings hash does not match its payload")
    first_outcomes = quality_outcome_payload(runs[0].quality_checks)
    pass_count = sum(check.passed for check in runs[0].quality_checks)
    return BaselineReport(
        schema_version="1.0",
        report_id="P00-US03-catastrophe-baseline",
        runner_version=RUNNER_VERSION,
        fixture=truth.fixture,
        expert_markdown_sha256=artifacts[
            ArtifactRole.EXPERT_MARKDOWN
        ].sha256,
        expert_json_sha256=artifacts[ArtifactRole.EXPERT_JSON].sha256,
        truth_sha256=sha256_path(truth_path),
        source_rights_sha256=sha256_path(source_rights_path),
        generated_from_run_set=portable_workspace_path(run_set_path),
        reference_command=tuple(str(value) for value in reference_command),
        settings=settings,
        settings_sha256=settings_hash,
        execution_policy=execution_policy,
        environment={str(key): str(value) for key, value in environment.items()},
        run_count=len(runs),
        runs=runs,
        duration_ms=summarize_distribution(
            [run.duration_ms for run in runs],
            MetricUnit.MILLISECONDS,
        ),
        peak_rss_mib=summarize_distribution(
            [run.peak_rss_bytes / (1024 * 1024) for run in runs],
            MetricUnit.MEBIBYTES,
        ),
        quality_pass_count=pass_count,
        quality_fail_count=len(runs[0].quality_checks) - pass_count,
        quality_signature=sha256_bytes(
            canonical_payload_bytes(first_outcomes)
        ),
        stability=summarize_stability(runs),
        compatibility=compatibility,
    )


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def report_markdown(report: BaselineReport) -> str:
    first_run = report.runs[0]
    output = first_run.output
    if output is None:
        raise ValueError("report Markdown requires successful output")
    lines = [
        "# P00-US03 Catastrophe Baseline",
        "",
        f"Report: `{report.report_id}`  ",
        f"Runs: {report.run_count} isolated cold workers  ",
        f"Fixture: `{report.fixture.fixture_id}` / `{report.fixture.source_sha256}`  ",
        f"Truth: `{report.truth_sha256}`",
        "",
        "## Identity and environment",
        "",
        "| Evidence | SHA-256 |",
        "|---|---|",
        f"| Source PDF | `{report.fixture.source_sha256}` |",
        f"| Expert Markdown | `{report.expert_markdown_sha256}` |",
        f"| Expert JSON | `{report.expert_json_sha256}` |",
        f"| Source truth | `{report.truth_sha256}` |",
        f"| Source-rights record | `{report.source_rights_sha256}` |",
        f"| Settings | `{report.settings_sha256}` |",
        "",
        "| Environment field | Recorded value |",
        "|---|---|",
    ]
    for key, value in sorted(report.environment.items()):
        lines.append(f"| `{key}` | {markdown_cell(value)} |")
    lines.extend(
        [
            "",
            "The full settings payload and this environment map are retained "
            "in the JSON report. Hosted services, optional models, and image "
            "captioning were disabled; Hugging Face and Transformers were "
            "forced offline.",
            "",
            "## Reference output identities",
            "",
            "| Projection | Size (bytes) | SHA-256 |",
            "|---|---:|---|",
            (
                f"| Raw JSON | {output.raw_json_size_bytes} | "
                f"`{output.raw_json_sha256}` |"
            ),
            (
                f"| Duration-masked semantic JSON | "
                f"{output.semantic_json_size_bytes} | "
                f"`{output.semantic_json_sha256}` |"
            ),
            (
                f"| Backend Markdown | {output.backend_markdown_size_bytes} | "
                f"`{output.backend_markdown_sha256}` |"
            ),
            (
                f"| Frontend normalized JSON | "
                f"{output.frontend_normalized_json_size_bytes} | "
                f"`{output.frontend_normalized_json_sha256}` |"
            ),
            (
                f"| Frontend Markdown | "
                f"{output.frontend_markdown_size_bytes} | "
                f"`{output.frontend_markdown_sha256}` |"
            ),
            (
                f"| Frontend text | {output.frontend_text_size_bytes} | "
                f"`{output.frontend_text_sha256}` |"
            ),
            "",
            "## Repeated-run distribution",
            "",
            "| Metric | Min | p50 | p95 | Max | Mean |",
            "|---|---:|---:|---:|---:|---:|",
            (
                "| Duration (ms) | "
                f"{report.duration_ms.minimum:.3f} | "
                f"{report.duration_ms.p50:.3f} | "
                f"{report.duration_ms.p95:.3f} | "
                f"{report.duration_ms.maximum:.3f} | "
                f"{report.duration_ms.mean:.3f} |"
            ),
            (
                "| Peak RSS (MiB) | "
                f"{report.peak_rss_mib.minimum:.2f} | "
                f"{report.peak_rss_mib.p50:.2f} | "
                f"{report.peak_rss_mib.p95:.2f} | "
                f"{report.peak_rss_mib.maximum:.2f} | "
                f"{report.peak_rss_mib.mean:.2f} |"
            ),
            "",
            "Percentiles use nearest rank; with five samples p50 is the third "
            "ordered value and p95 is the fifth (maximum).",
            "",
            "## Per-run evidence",
            "",
            (
                "| Run | Duration (ms) | CPU (ms) | Peak RSS (MiB) | "
                "Raw JSON SHA |"
            ),
            "|---|---:|---:|---:|---|",
        ]
    )
    for run in report.runs:
        assert run.output is not None
        lines.append(
            f"| {run.run_id} | {run.duration_ms:.3f} | {run.cpu_ms:.3f} | "
            f"{run.peak_rss_bytes / (1024 * 1024):.2f} | "
            f"`{run.output.raw_json_sha256}` |"
        )
    lines.extend(
        [
            "",
            "## Stability",
            "",
            "- Fixture hashes stable: "
            f"`{report.stability.fixture_hashes_stable}`",
            "- Atomic quality outcomes stable: "
            f"`{report.stability.quality_outcomes_stable}`",
            "- Duration-masked semantic JSON stable: "
            f"`{report.stability.semantic_json_hashes_stable}`",
            "- Backend Markdown stable: "
            f"`{report.stability.backend_markdown_hashes_stable}`",
            "- Frontend Markdown stable: "
            f"`{report.stability.frontend_markdown_hashes_stable}`",
            "- Frontend text stable: "
            f"`{report.stability.frontend_text_hashes_stable}`",
            "- Unique raw JSON hashes: "
            f"`{report.stability.raw_json_unique_hash_count}`",
            "- Unique frontend normalized JSON hashes: "
            f"`{report.stability.frontend_normalized_json_unique_hash_count}`",
            "",
            "Raw and frontend-normalized JSON retain the measured "
            "`processing.duration_ms` and may differ. The only semantic-hash "
            "volatility exclusion is `/processing/duration_ms`; raw artifacts "
            "and hashes are retained.",
            "",
            "## Source-grounded quality",
            "",
            f"Stable atomic outcomes: {report.quality_pass_count} pass / "
            f"{report.quality_fail_count} fail.",
            "",
            "| Check | Gap/category | Result | Observation |",
            "|---|---|---|---|",
        ]
    )
    for check in first_run.quality_checks:
        outcome = "Pass" if check.passed else "Fail"
        observed = check.observed.replace("|", "\\|")
        lines.append(
            f"| `{check.check_id}` | `{check.gap_id}` | {outcome} | "
            f"{observed} |"
        )
    lines.extend(
        [
            "",
            "The pass rows include positive/safer behavior; failures are "
            "baseline defects, not story regressions. Stale expert duplicate-"
            "title, false-span, and annual-below-1H shapes are not attributed "
            "to the current parser.",
            "",
            "## Compatibility and skips",
            "",
            "| Gate | Runtime | Pass | Skip | Warning |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for gate in report.compatibility.gates:
        lines.append(
            f"| `{gate.gate_id}` | {gate.runtime} | {gate.pass_count} | "
            f"{gate.skip_count} | {gate.warning_count} |"
        )
    all_skips = [
        record
        for gate in report.compatibility.gates
        for record in gate.skip_records
    ]
    lines.extend(
        [
            "",
            "### API schema identities",
            "",
            "| Schema | SHA-256 |",
            "|---|---|",
        ]
    )
    for name, value in sorted(report.compatibility.api_schema_hashes.items()):
        lines.append(f"| `{name}` | `{value}` |")
    lines.extend(
        [
            "",
            f"### Explicit skips ({len(all_skips)})",
            "",
            "| Test node | Owner | Reason | Opt-in |",
            "|---|---|---|---|",
        ]
    )
    for record in all_skips:
        lines.append(
            f"| `{record.node_id}` | `{record.owner_role}` | "
            f"{markdown_cell(record.reason)} | "
            f"`{record.opt_in_condition}` |"
        )
    lines.extend(
        [
            "",
            "Every active skip is explicit above and in the JSON report; none "
            "is counted as a pass.",
            "",
            "## Reproduction",
            "",
            "```text",
            " ".join(report.reference_command),
            "```",
            "",
            "The capture refuses to overwrite an existing run directory. "
            "Rebuilding this summary from the same immutable raw inputs is "
            "canonical and byte-deterministic.",
            "",
        ]
    )
    return "\n".join(lines)


def _artifact_hashes(
    truth: CatastropheSourceTruth,
) -> tuple[str, str, str]:
    artifacts = {artifact.role: artifact for artifact in truth.artifacts}
    return (
        artifacts[ArtifactRole.SOURCE].sha256,
        artifacts[ArtifactRole.EXPERT_MARKDOWN].sha256,
        artifacts[ArtifactRole.EXPERT_JSON].sha256,
    )


def run_worker(
    *,
    source_path: Path,
    truth_path: Path,
    output_dir: Path,
    run_id: str,
    node_command: str,
) -> int:
    from app.config import Settings
    from app.services.pipeline import parse_document
    from app.services.serializer import to_markdown

    required_environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    if any(
        os.environ.get(name) != value
        for name, value in required_environment.items()
    ):
        raise ValueError(
            "worker requires the recorded offline execution environment"
        )
    truth = load_catastrophe_source_truth(truth_path)
    validate_registered_artifacts(truth)
    source_hash, expert_md_hash, expert_json_hash = _artifact_hashes(truth)
    source_bytes = source_path.read_bytes()
    if sha256_bytes(source_bytes) != source_hash:
        raise ValueError("worker source bytes do not match the registered fixture")
    output_dir.mkdir(parents=True, exist_ok=False)
    settings = Settings(**DEFAULT_SETTINGS)
    settings_payload = dataclasses.asdict(settings)
    settings_hash = sha256_bytes(canonical_payload_bytes(settings_payload))
    environment = environment_metadata(node_command)
    versions = {
        key: value
        for key, value in environment.items()
        if key
        in {
            "application",
            "docling",
            "docling-core",
            "pdfplumber",
            "pypdfium2",
            "pillow",
            "tesseract",
            "node",
            "source_tree_sha256",
        }
    }
    portable_command = (
        ".venv/bin/python",
        "-m",
        "tests.benchmarks.baseline_report",
        "worker",
        "--source",
        portable_workspace_path(source_path),
        "--truth",
        portable_workspace_path(truth_path),
        "--output-dir",
        portable_workspace_path(output_dir),
        "--run-id",
        run_id,
        "--node",
        node_command,
    )
    started_at = utc_now()
    started_perf = time.perf_counter()
    started_cpu = time.process_time()
    duration_ms = 0.0
    cpu_ms = 0.0
    error: dict[str, object] | None = None
    output_evidence: OutputEvidence | None = None
    checks: tuple[QualityCheck, ...] = ()
    status: Literal["success", "error", "timeout"] = "success"
    try:
        result = parse_document(source_bytes, source_path.name, settings)
        duration_ms = (time.perf_counter() - started_perf) * 1000
        cpu_ms = (time.process_time() - started_cpu) * 1000
        payload = result.model_dump(mode="json")
        backend_markdown = to_markdown(result)

        raw_json_path = output_dir / "our-output.json"
        backend_markdown_path = output_dir / "our-output.md"
        write_json(raw_json_path, payload)
        backend_markdown_path.write_text(backend_markdown, encoding="utf-8")
        semantic_bytes = semantic_json_bytes(payload)

        projection_command = [
            node_command,
            "--experimental-strip-types",
            str(WORKSPACE / "tests/benchmarks/frontend_projection.mts"),
            str(raw_json_path),
            str(output_dir),
        ]
        projection = subprocess.run(
            projection_command,
            cwd=WORKSPACE,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        (output_dir / "frontend-stdout.log").write_text(
            projection.stdout,
            encoding="utf-8",
        )
        (output_dir / "frontend-stderr.log").write_text(
            projection.stderr,
            encoding="utf-8",
        )
        if projection.returncode != 0:
            raise RuntimeError(
                "frontend projection failed with exit "
                f"{projection.returncode}: {projection.stderr[-1000:]}"
            )
        projection_metadata = json.loads(projection.stdout)
        frontend_markdown_path = output_dir / "frontend-markdown.md"
        frontend_text_path = output_dir / "frontend-text.txt"
        frontend_json_path = output_dir / "frontend-normalized.json"
        frontend_markdown = frontend_markdown_path.read_text(encoding="utf-8")
        checks = evaluate_catastrophe_quality(
            payload,
            backend_markdown,
            frontend_markdown,
            truth,
        )
        raw_json_bytes = raw_json_path.read_bytes()
        backend_markdown_bytes = backend_markdown_path.read_bytes()
        frontend_json_bytes = frontend_json_path.read_bytes()
        frontend_markdown_bytes = frontend_markdown_path.read_bytes()
        frontend_text_bytes = frontend_text_path.read_bytes()
        measured_projection = {
            "normalized_json_sha256": sha256_bytes(frontend_json_bytes),
            "normalized_json_size_bytes": len(frontend_json_bytes),
            "markdown_sha256": sha256_bytes(frontend_markdown_bytes),
            "markdown_size_bytes": len(frontend_markdown_bytes),
            "text_sha256": sha256_bytes(frontend_text_bytes),
            "text_size_bytes": len(frontend_text_bytes),
        }
        for key, value in measured_projection.items():
            if projection_metadata.get(key) != value:
                raise ValueError(
                    f"frontend projection metadata mismatch for {key}"
                )
        output_evidence = OutputEvidence(
            raw_json_path=portable_workspace_path(raw_json_path),
            raw_json_sha256=sha256_bytes(raw_json_bytes),
            raw_json_size_bytes=len(raw_json_bytes),
            semantic_json_sha256=sha256_bytes(semantic_bytes),
            semantic_json_size_bytes=len(semantic_bytes),
            backend_markdown_path=portable_workspace_path(
                backend_markdown_path
            ),
            backend_markdown_sha256=sha256_bytes(backend_markdown_bytes),
            backend_markdown_size_bytes=len(backend_markdown_bytes),
            frontend_normalized_json_path=portable_workspace_path(
                frontend_json_path
            ),
            frontend_normalized_json_sha256=measured_projection[
                "normalized_json_sha256"
            ],
            frontend_normalized_json_size_bytes=len(frontend_json_bytes),
            frontend_markdown_path=portable_workspace_path(
                frontend_markdown_path
            ),
            frontend_markdown_sha256=measured_projection["markdown_sha256"],
            frontend_markdown_size_bytes=len(frontend_markdown_bytes),
            frontend_text_path=portable_workspace_path(frontend_text_path),
            frontend_text_sha256=measured_projection["text_sha256"],
            frontend_text_size_bytes=len(frontend_text_bytes),
        )
    except Exception as exc:  # noqa: BLE001 - evidence must retain every failure.
        status = "error"
        if duration_ms == 0:
            duration_ms = (time.perf_counter() - started_perf) * 1000
            cpu_ms = (time.process_time() - started_cpu) * 1000
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    run = ReferenceRun(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        status=status,
        fixture_id=truth.fixture.fixture_id,
        source_sha256=source_hash,
        expert_markdown_sha256=expert_md_hash,
        expert_json_sha256=expert_json_hash,
        truth_sha256=sha256_path(truth_path),
        started_at_utc=started_at,
        completed_at_utc=utc_now(),
        command=portable_command,
        cwd=".",
        settings_sha256=settings_hash,
        execution_policy=ExecutionPolicy.model_validate(
            DEFAULT_EXECUTION_POLICY
        ),
        environment=environment,
        versions=versions,
        duration_ms=duration_ms,
        cpu_ms=cpu_ms,
        peak_rss_bytes=normalized_peak_rss_bytes(),
        output=output_evidence,
        quality_checks=checks,
        error=error,
    )
    write_json(
        output_dir / "run-record.json",
        run.model_dump(mode="json"),
    )
    return 0 if status == "success" else 1


def capture_runs(
    *,
    source_path: Path,
    truth_path: Path,
    runs_root: Path,
    repeat: int,
    node_command: str,
) -> int:
    if repeat < 5:
        raise SystemExit("P00-US03 requires --repeat >= 5")
    truth = load_catastrophe_source_truth(truth_path)
    validate_registered_artifacts(truth)
    source_hash, _, _ = _artifact_hashes(truth)
    if sha256_path(source_path) != source_hash:
        raise SystemExit("source bytes do not match the registered fixture")
    try:
        runs_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(
            f"refusing to overwrite immutable runs root: {runs_root}"
        ) from exc
    environment = environment_metadata(node_command)
    settings_payload = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in DEFAULT_SETTINGS.items()
    }
    portable_command = [
        ".venv/bin/python",
        "-m",
        "tests.benchmarks.baseline_report",
        "capture",
        "--source",
        portable_workspace_path(source_path),
        "--truth",
        portable_workspace_path(truth_path),
        "--runs-root",
        portable_workspace_path(runs_root),
        "--repeat",
        str(repeat),
        "--node",
        node_command,
    ]
    run_records: list[str] = []
    coordinator_results: list[dict[str, object]] = []
    overall_status = 0
    for index in range(1, repeat + 1):
        run_id = f"catastrophe-cold-{index:02d}"
        run_dir = runs_root / run_id
        command = [
            sys.executable,
            "-m",
            "tests.benchmarks.baseline_report",
            "worker",
            "--source",
            str(source_path.resolve()),
            "--truth",
            str(truth_path.resolve()),
            "--output-dir",
            str(run_dir.resolve()),
            "--run-id",
            run_id,
            "--node",
            node_command,
        ]
        child_environment = os.environ.copy()
        child_environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        started = utc_now()
        try:
            completed = subprocess.run(
                command,
                cwd=WORKSPACE,
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=DEFAULT_SETTINGS["document_timeout_seconds"] + 120,
            )
            return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            coordinator_status = "success" if return_code == 0 else "error"
        except subprocess.TimeoutExpired as exc:
            return_code = 124
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            coordinator_status = "timeout"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "worker-stdout.log").write_text(
            stdout if isinstance(stdout, str) else stdout.decode(),
            encoding="utf-8",
        )
        (run_dir / "worker-stderr.log").write_text(
            stderr if isinstance(stderr, str) else stderr.decode(),
            encoding="utf-8",
        )
        run_record_path = run_dir / "run-record.json"
        coordinator_results.append(
            {
                "run_id": run_id,
                "started_at_utc": started,
                "completed_at_utc": utc_now(),
                "status": coordinator_status,
                "worker_exit_code": return_code,
                "run_record_present": run_record_path.is_file(),
            }
        )
        if return_code != 0 or not run_record_path.is_file():
            overall_status = 1
        else:
            run_records.append(portable_workspace_path(run_record_path))
    run_set = {
        "schema_version": "1.0",
        "runner_version": RUNNER_VERSION,
        "fixture_id": truth.fixture.fixture_id,
        "source_sha256": source_hash,
        "truth_sha256": sha256_path(truth_path),
        "status": "success" if overall_status == 0 else "completed_with_errors",
        "repeat": repeat,
        "portable_command": portable_command,
        "settings": settings_payload,
        "settings_sha256": sha256_bytes(
            canonical_payload_bytes(settings_payload)
        ),
        "environment": environment,
        "execution_policy": DEFAULT_EXECUTION_POLICY,
        "coordinator_results": coordinator_results,
        "run_record_paths": run_records,
    }
    write_json(runs_root / "run-set.json", run_set)
    (runs_root / "command.txt").write_text(
        " ".join(portable_command) + "\n",
        encoding="utf-8",
    )
    return overall_status


def summarize_existing(
    *,
    runs_root: Path,
    truth_path: Path,
    source_rights_path: Path,
    compatibility_path: Path,
    report_json_path: Path,
    report_markdown_path: Path,
) -> int:
    if report_json_path.exists() or report_markdown_path.exists():
        raise SystemExit("refusing to overwrite an existing baseline report")
    compatibility = load_compatibility(compatibility_path)
    report = build_report(
        runs_root=runs_root,
        truth_path=truth_path,
        source_rights_path=source_rights_path,
        compatibility=compatibility,
    )
    write_json(report_json_path, report.model_dump(mode="json"))
    report_markdown_path.write_text(
        report_markdown(report),
        encoding="utf-8",
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker")
    worker.add_argument("--source", required=True, type=Path)
    worker.add_argument("--truth", required=True, type=Path)
    worker.add_argument("--output-dir", required=True, type=Path)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--node", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--source", required=True, type=Path)
    capture.add_argument("--truth", required=True, type=Path)
    capture.add_argument("--runs-root", required=True, type=Path)
    capture.add_argument("--repeat", required=True, type=int)
    capture.add_argument("--node", required=True)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--runs-root", required=True, type=Path)
    summarize.add_argument("--truth", required=True, type=Path)
    summarize.add_argument("--source-rights", required=True, type=Path)
    summarize.add_argument("--compatibility", required=True, type=Path)
    summarize.add_argument("--report-json", required=True, type=Path)
    summarize.add_argument("--report-markdown", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "worker":
        raise SystemExit(
            run_worker(
                source_path=args.source.resolve(),
                truth_path=args.truth.resolve(),
                output_dir=args.output_dir.resolve(),
                run_id=args.run_id,
                node_command=args.node,
            )
        )
    if args.command == "capture":
        raise SystemExit(
            capture_runs(
                source_path=args.source.resolve(),
                truth_path=args.truth.resolve(),
                runs_root=args.runs_root.resolve(),
                repeat=args.repeat,
                node_command=args.node,
            )
        )
    raise SystemExit(
        summarize_existing(
            runs_root=args.runs_root.resolve(),
            truth_path=args.truth.resolve(),
            source_rights_path=args.source_rights.resolve(),
            compatibility_path=args.compatibility.resolve(),
            report_json_path=args.report_json.resolve(),
            report_markdown_path=args.report_markdown.resolve(),
        )
    )


if __name__ == "__main__":
    main()
