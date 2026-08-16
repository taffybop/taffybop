"""Strict immutable offline runner for the registered LlamaParse-15 corpus.

This module is Phase 0 test/reporting infrastructure.  It invokes the existing
production parser through its public service boundary, but it is deliberately
isolated under ``tests`` and must never be imported by ``app``.

The reviewed rows are source-grounded classifications, not executable expected
value predicates.  Consequently this runner preserves the complete reviewed
mask ledger and exact source locators while reporting unevaluated eligible
claims as diagnostic-only.  It never turns token similarity into semantic
pass/fail evidence and never promotes unsupported expert content into truth.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import time
import traceback
from typing import Any, Literal

import psutil
from pydantic import Field, field_validator, model_validator

from tests.benchmarks.baseline_report import (
    DEFAULT_SETTINGS,
    normalized_peak_rss_bytes,
    semantic_json_bytes,
)
from tests.benchmarks.contracts import (
    ContractModel,
    NonEmptyString,
    SchemaVersion,
    Sha256,
)
from tests.benchmarks.control_registry import (
    CONTROL_REGISTRY_EVIDENCE_PATH,
    BenchmarkControlRegistry,
    ControlRole,
    control_registry_sha256,
    load_benchmark_control_registry,
)
from tests.benchmarks.corpus_registry import (
    EXPECTED_CASE_IDS,
    PortableCorpusRegistry,
    RegistryCase,
    canonical_registry_json,
    load_corpus_registry,
    resolve_portable_path,
    sha256_file,
    verify_current_artifacts,
)
from tests.benchmarks.reviewed_claim_inventory import (
    BATCH_A_EVIDENCE_PATH,
    BATCH_B_EVIDENCE_PATH,
    BATCH_C_EVIDENCE_PATH,
    load_reviewed_claim_batch_a,
    load_reviewed_claim_batch_b,
    load_reviewed_claim_batch_c,
)
from tests.benchmarks.reviewed_claims import (
    ClaimReviewStatus,
    ClaimType,
    ReviewBatch,
    ReviewedClaimRecord,
    SourceLocator,
    corpus_registry_sha256,
    review_batch_sha256,
)


WORKSPACE = Path(__file__).resolve().parents[2]
RUNNER_VERSION = "P00-US10-1.0"
RECORD_KIND = "p00-us10-corpus-run"
REPORT_KIND = "p00-us10-corpus-semantic-report"
CORPUS_REGISTRY_PATH = (
    "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json"
)
LEGACY_M0_RUN_ROOT = (
    "tracker/benchmarks/llamaparse-15/runs/baseline-20260728-current"
)
LEGACY_M0_METADATA_SHA256 = (
    "386c333bff8ec0678d1194fff5899f82ec9475d29be7d72999a58c3817e3128f"
)
LEGACY_M0_COMPARISON_SHA256 = (
    "2a23aabc812e6723621174f9c66027c2cf3e852de31a8481262e7a2708710e7b"
)
VOLATILE_JSON_POINTERS = ("/processing/duration_ms",)
PERFORMANCE_TOLERANCE_PERCENT = 25.0

REQUIRED_ENGINE_NAMES = (
    "docling",
    "docling-core",
    "pdfplumber",
    "pypdfium2",
    "pillow",
    "tesseract",
)

REFERENCE_PERFORMANCE = {
    "latency_p50_ms": 9061.990999965928,
    "latency_p95_ms": 46758.3517919993,
    "rss_p50_bytes": 1506803712.0,
    "rss_max_bytes": 2715254784.0,
}

# Duration-masked JSON and exact Markdown identities from the frozen M0 run.
REFERENCE_OUTPUT_IDENTITIES: dict[str, tuple[str, str]] = {
    "catastrophe-recap": (
        "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9",
        "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1",
    ),
    "clean-energy": (
        "26f222c20ddd2298bb6e37a3bb52f1b9476ff86a6cc04e8638d3ccac45f1c21a",
        "e94fdcfd242a09cd33cc2198e7fca7bbea3e9abd3ef006eeaa833adf7c5264f3",
    ),
    "clinical-study": (
        "2fb9508e6027b1c2f88341ce92445e5da56bdf805a71a9563b768cbe59bbf863",
        "11a5339797e1ed41a164b23ada5386dc7220d32e10633181a76323f06271a160",
    ),
    "component-datasheet": (
        "5be1be6bfbdede05a7c29a24d88ee41ed6b9e2b20dd3aa76966a571c9f463204",
        "76baf4c7ce7206f3adb36427bfa5593e0d72675276d8c0d5d20e74fdd6e081a7",
    ),
    "egov-survey": (
        "c47d41c7cb9bf0c27ed1eb13c63a8c71c4778888dbe4fd5b95ab33d5b589c5d4",
        "273f2a1256285e0068b7dc3afdc0de9a7001d9c79ccf43ef81dd67ae44c32e09",
    ),
    "esg-metrics": (
        "46a10fc5b9324a72e1b681d90d9e70f02ea61df7bab17fc76e5d1a5f330e7a02",
        "67efecc558dfbdd15f84eede895e3d4339e9bab39c8e8293bc21d4065586544b",
    ),
    "finance-10k": (
        "ec1d4b327bd0542b8e76e1a9517b8d940df2692f20bf59476536284298ad5abe",
        "c09584ed42ed53f0cf2287bb3bb82e0c4f35d5fe0237e0c8785fc765f9026b3b",
    ),
    "health-report": (
        "c532e241bad95695c337f2b4aad2b81a27b801ae466a3c6f1f82ed572ef353ba",
        "4a1ba6026b146bd7996bf81d592f3e9f47901bf096073afccb100717187e752a",
    ),
    "insurance-acord": (
        "1ce18508462dee0fd90821d4e1d974f77bed9e733c3f82954986efdd08b46432",
        "e1b2e3601f507ce75317b727e682a62616b81ce2868f49740a1967d02680250c",
    ),
    "manufacturing-report": (
        "eece6c9fe1b35e77a404e5a989c0396db14cf349da432cfc76fef21851abf1a7",
        "5825a6f58b1b59197ea287c5838258c2419519ef1068482176da3c5f981d19a8",
    ),
    "ny-timetable": (
        "ebdc1985c66a590a0085e07cb9fa4d1cdf5b1b2cbd7731c412371488b2a06e56",
        "f8c2a61c0e795e16bc4022e153ee89e96a5b2c37ff7b8b1e217a3a794fd4823e",
    ),
    "postal-10k": (
        "ea51e1fd5dbb8b9c0dc0d1ef46033f7d808c5daf8092fe4f4daccc5495752524",
        "3288912afb3677a846dd6ac190e40e2b015122292564a038031e85b9759a9f87",
    ),
    "purchase-agreement": (
        "64b7e33c88ba63223eb860cd0c550768aa52659ab47a92e008f52282c8879bf6",
        "51c10e783da3400010151f11ea6cb7120513561c3b68f2ddebe869574852a7ce",
    ),
    "settlement-agreement": (
        "acb56e5c38c208d9a6b84a4be71711e2aeb807e7b3e3e79a205a59d0099a2491",
        "6fe637d18229a5ab90b501b687d41902335c70a41d39d410e4fa41015c0f3305",
    ),
    "uber-earnings": (
        "b4d3afe7b93370a97b96aee04416497baa93b52bfefcbecd48074971859219e3",
        "9beb6dc3d71d0ff97718df827390831e0e4942e88f1399a24d17fc8823c799df",
    ),
}


class MetricDimension(str, Enum):
    TEXT = "text"
    LAYOUT = "layout"
    READING_ORDER = "reading_order"
    TABLE = "table"
    CHART = "chart"
    DIAGRAM = "diagram"
    MARKDOWN = "markdown"
    JSON = "json"
    HALLUCINATION = "hallucination"
    DIAGNOSTICS = "diagnostics"
    PERFORMANCE = "performance"
    COST = "cost"


DIMENSION_ORDER = tuple(MetricDimension)


class CaseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ClaimTreatment(str, Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    EXCLUDED_UNSUPPORTED = "excluded_unsupported"


CLAIM_DIMENSION = {
    ClaimType.PAGE_IDENTITY: MetricDimension.LAYOUT,
    ClaimType.TEXT: MetricDimension.TEXT,
    ClaimType.TEXT_STYLE: MetricDimension.TEXT,
    ClaimType.STRUCTURE: MetricDimension.READING_ORDER,
    ClaimType.RELATIONSHIP: MetricDimension.DIAGRAM,
    ClaimType.GEOMETRY: MetricDimension.LAYOUT,
    ClaimType.TABLE: MetricDimension.TABLE,
    ClaimType.CHART: MetricDimension.CHART,
    ClaimType.IMAGE: MetricDimension.LAYOUT,
    ClaimType.DIAGRAM: MetricDimension.DIAGRAM,
    ClaimType.FORM: MetricDimension.LAYOUT,
    ClaimType.LINK: MetricDimension.LAYOUT,
    ClaimType.METADATA: MetricDimension.JSON,
    ClaimType.ARTIFACT_INVENTORY: MetricDimension.JSON,
    ClaimType.CONTROL: MetricDimension.JSON,
}

GAP_DIMENSION: dict[str, MetricDimension] = {
    "GAP-BENCHMARK-001": MetricDimension.JSON,
    "GAP-BENCHMARK-002": MetricDimension.DIAGNOSTICS,
    "GAP-COVERAGE-001": MetricDimension.DIAGNOSTICS,
    "GAP-UNICODE-001": MetricDimension.TEXT,
    "GAP-TEXT-001": MetricDimension.TEXT,
    "GAP-OCR-001": MetricDimension.TEXT,
    "GAP-LAYOUT-001": MetricDimension.LAYOUT,
    "GAP-ORDER-001": MetricDimension.READING_ORDER,
    "GAP-PAGE-001": MetricDimension.LAYOUT,
    "GAP-REDLINE-001": MetricDimension.TEXT,
    "GAP-FORM-001": MetricDimension.LAYOUT,
    "GAP-LIST-001": MetricDimension.READING_ORDER,
    "GAP-LINK-001": MetricDimension.LAYOUT,
    "GAP-BBOX-001": MetricDimension.LAYOUT,
    "GAP-TABLE-001": MetricDimension.TABLE,
    "GAP-TABLE-002": MetricDimension.TABLE,
    "GAP-TABLE-003": MetricDimension.TABLE,
    "GAP-CHART-001": MetricDimension.CHART,
    "GAP-CHART-002": MetricDimension.CHART,
    "GAP-DIAGRAM-001": MetricDimension.DIAGRAM,
    "GAP-VISUAL-001": MetricDimension.LAYOUT,
    "GAP-SERIALIZATION-001": MetricDimension.MARKDOWN,
    "GAP-PROVENANCE-001": MetricDimension.JSON,
    "GAP-DIAGNOSTICS-001": MetricDimension.DIAGNOSTICS,
    "GAP-PERFORMANCE-001": MetricDimension.PERFORMANCE,
}

_RUN_ID = re.compile(r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
_UNAVAILABLE_VALUES = {"", "unknown", "unavailable", "none", "null"}
_UNSUPPORTED_STATUSES = {
    ClaimReviewStatus.INCORRECT,
    ClaimReviewStatus.NOT_INDEPENDENTLY_VERIFIABLE,
    ClaimReviewStatus.POTENTIALLY_INFERRED,
}


def _require_portable_path(value: str) -> str:
    if value != value.strip() or "\\" in value or "\x00" in value:
        raise ValueError("artifact paths must be trimmed portable POSIX paths")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or value.split("/", 1)[0].startswith("~")
        or ":" in value.split("/", 1)[0]
    ):
        raise ValueError("artifact paths must be canonical workspace-relative paths")
    return value


def _utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{label} must use UTC")
    return parsed


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_payload_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_model_bytes(model: ContractModel) -> bytes:
    return canonical_payload_bytes(model.model_dump(mode="json"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class ArtifactEvidence(ContractModel):
    role: NonEmptyString
    path: NonEmptyString
    sha256: Sha256
    size_bytes: int = Field(ge=0)
    derivation: NonEmptyString | None = None

    @field_validator("path")
    @classmethod
    def require_portable_path(cls, value: str) -> str:
        return _require_portable_path(value)


class InputBinding(ContractModel):
    identity: NonEmptyString
    path: NonEmptyString
    file_sha256: Sha256
    semantic_sha256: Sha256

    @field_validator("path")
    @classmethod
    def require_portable_path(cls, value: str) -> str:
        return _require_portable_path(value)


class FrozenInputIdentity(ContractModel):
    corpus_registry: InputBinding
    control_registry: InputBinding
    review_batches: tuple[InputBinding, ...] = Field(min_length=3, max_length=3)
    legacy_metadata_sha256: Sha256
    legacy_comparison_sha256: Sha256

    @model_validator(mode="after")
    def require_unique_canonical_batches(self) -> "FrozenInputIdentity":
        identities = tuple(item.identity for item in self.review_batches)
        if len(identities) != len(set(identities)):
            raise ValueError("review batch identities must be unique")
        if identities != tuple(sorted(identities)):
            raise ValueError("review batch identities must use canonical order")
        return self


class EngineIdentity(ContractModel):
    name: NonEmptyString
    version: NonEmptyString

    @field_validator("name", "version")
    @classmethod
    def reject_missing_identity(cls, value: str) -> str:
        if value != value.strip() or value.lower() in _UNAVAILABLE_VALUES:
            raise ValueError("engine name and version must be explicit")
        return value


class EnvironmentIdentity(ContractModel):
    application_version: NonEmptyString
    application_source_sha256: Sha256
    runner_source_sha256: Sha256
    python_version: NonEmptyString
    python_executable: NonEmptyString
    platform: NonEmptyString
    machine: NonEmptyString
    processor: NonEmptyString
    logical_cpu_count: int = Field(gt=0)
    physical_cpu_count: int = Field(gt=0)
    total_memory_bytes: int = Field(gt=0)
    engines: tuple[EngineIdentity, ...] = Field(
        min_length=len(REQUIRED_ENGINE_NAMES),
        max_length=len(REQUIRED_ENGINE_NAMES),
    )

    @model_validator(mode="after")
    def require_complete_engine_identity(self) -> "EnvironmentIdentity":
        if self.application_version.lower() in _UNAVAILABLE_VALUES:
            raise ValueError("application version must be explicit")
        names = tuple(engine.name for engine in self.engines)
        if names != REQUIRED_ENGINE_NAMES:
            raise ValueError("engines must contain every required engine in order")
        return self


class ExecutionPolicy(ContractModel):
    network_access: Literal["disabled"]
    hosted_services: Literal["disabled"]
    image_captioning: Literal[False]
    optional_models: Literal["disabled"]
    hf_hub_offline: Literal[True]
    transformers_offline: Literal[True]
    tokenizers_parallelism: Literal[False]


FIXED_EXECUTION_POLICY = ExecutionPolicy(
    network_access="disabled",
    hosted_services="disabled",
    image_captioning=False,
    optional_models="disabled",
    hf_hub_offline=True,
    transformers_offline=True,
    tokenizers_parallelism=False,
)


class DiagnosticRecord(ContractModel):
    code: NonEmptyString
    stage: NonEmptyString
    message: NonEmptyString
    remediation: NonEmptyString
    case_id: NonEmptyString | None = None


class ErrorRecord(ContractModel):
    code: NonEmptyString
    stage: NonEmptyString
    exception_type: NonEmptyString
    message: NonEmptyString
    remediation: NonEmptyString
    traceback: NonEmptyString


class SkipRecord(ContractModel):
    owner: NonEmptyString
    reason: NonEmptyString
    opt_in_condition: NonEmptyString


class OutputComparison(ContractModel):
    case_id: NonEmptyString
    current_semantic_json_sha256: Sha256
    reference_semantic_json_sha256: Sha256
    semantic_json_stable: bool
    current_markdown_sha256: Sha256
    reference_markdown_sha256: Sha256
    markdown_stable: bool

    @model_validator(mode="after")
    def recompute_stability(self) -> "OutputComparison":
        if self.semantic_json_stable != (
            self.current_semantic_json_sha256
            == self.reference_semantic_json_sha256
        ):
            raise ValueError("semantic_json_stable does not match the hashes")
        if self.markdown_stable != (
            self.current_markdown_sha256 == self.reference_markdown_sha256
        ):
            raise ValueError("markdown_stable does not match the hashes")
        return self


class CaseOutputEvidence(ContractModel):
    raw_json: ArtifactEvidence
    semantic_json: ArtifactEvidence
    markdown: ArtifactEvidence
    expected_page_count: int = Field(gt=0)
    observed_page_count: int = Field(ge=0)
    successful_page_count: int = Field(ge=0)
    document_warnings: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def require_recognized_output_roles(self) -> "CaseOutputEvidence":
        if (
            self.raw_json.role,
            self.semantic_json.role,
            self.markdown.role,
        ) != ("raw_json", "semantic_json", "markdown"):
            raise ValueError("case output artifacts must use canonical roles")
        if self.semantic_json.path != self.raw_json.path:
            raise ValueError("semantic JSON must be derived from the raw JSON path")
        if self.semantic_json.derivation != (
            "canonical JSON excluding /processing/duration_ms"
        ):
            raise ValueError("semantic JSON must declare its volatility mask")
        if self.successful_page_count > self.observed_page_count:
            raise ValueError("successful pages cannot exceed observed pages")
        return self


class CaseExecution(ContractModel):
    schema_version: SchemaVersion
    runner_version: Literal["P00-US10-1.0"]
    run_id: NonEmptyString
    case_id: NonEmptyString
    order: int = Field(gt=0)
    status: CaseStatus
    registered_page_count: int = Field(gt=0)
    source_triplet: tuple[ArtifactEvidence, ...] = Field(
        min_length=3,
        max_length=3,
    )
    started_at_utc: NonEmptyString
    completed_at_utc: NonEmptyString
    command: tuple[NonEmptyString, ...] = Field(min_length=1)
    worker_exit_code: int
    parse_latency_ms: float = Field(ge=0)
    case_latency_ms: float = Field(ge=0)
    cpu_ms: float = Field(ge=0)
    peak_rss_bytes: int = Field(gt=0)
    settings_sha256: Sha256
    environment_sha256: Sha256
    warnings: tuple[NonEmptyString, ...] = ()
    output: CaseOutputEvidence | None = None
    reference_comparison: OutputComparison | None = None
    error: ErrorRecord | None = None
    skip: SkipRecord | None = None

    @model_validator(mode="after")
    def require_coherent_case_state(self) -> "CaseExecution":
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must be a stable lowercase identifier")
        if _utc(self.completed_at_utc, "completed_at_utc") < _utc(
            self.started_at_utc,
            "started_at_utc",
        ):
            raise ValueError("case completion cannot precede its start")
        if tuple(item.role for item in self.source_triplet) != (
            "source",
            "expert_markdown",
            "expert_json",
        ):
            raise ValueError("source triplet must use canonical roles")

        if self.status is CaseStatus.SUCCESS:
            if self.worker_exit_code != 0:
                raise ValueError("successful cases require exit code zero")
            if (
                self.output is None
                or self.reference_comparison is None
                or self.error is not None
                or self.skip is not None
            ):
                raise ValueError("successful cases require complete clean evidence")
            if (
                self.output.expected_page_count != self.registered_page_count
                or self.output.observed_page_count != self.registered_page_count
                or self.output.successful_page_count != self.registered_page_count
            ):
                raise ValueError("successful cases require every registered page")
        elif self.status is CaseStatus.SKIPPED:
            if self.skip is None or self.error is not None or self.output is not None:
                raise ValueError("skipped cases require only explicit skip evidence")
        elif self.error is None:
            raise ValueError("partial, error, and timeout cases require an error")
        return self


class CaseRecordEvidence(ContractModel):
    """Immutable raw-worker and coordinator projections for one case."""

    case_id: NonEmptyString
    worker_record: ArtifactEvidence
    coordinator_record: ArtifactEvidence

    @model_validator(mode="after")
    def require_canonical_record_roles(self) -> "CaseRecordEvidence":
        if (
            self.worker_record.role,
            self.coordinator_record.role,
        ) != ("worker_case_record", "coordinator_case_record"):
            raise ValueError("case records must use canonical evidence roles")
        return self


class ReviewedClaimResult(ContractModel):
    claim_id: NonEmptyString
    case_id: NonEmptyString
    claim_type: ClaimType
    dimension: MetricDimension
    review_status: ClaimReviewStatus
    source_locators: tuple[SourceLocator, ...] = Field(min_length=1)
    literal_eligible: bool
    semantic_eligible: bool
    treatment: ClaimTreatment
    diagnostic_reason: NonEmptyString
    evaluator_id: NonEmptyString | None = None
    output_artifact_sha256: Sha256

    @model_validator(mode="after")
    def preserve_review_masks(self) -> "ReviewedClaimResult":
        if self.dimension is not CLAIM_DIMENSION[self.claim_type]:
            raise ValueError("claim dimension must match the versioned type map")
        if any(locator.case_id != self.case_id for locator in self.source_locators):
            raise ValueError("all source locators must use the claim case")
        if self.literal_eligible and not self.semantic_eligible:
            raise ValueError("literal eligibility requires semantic eligibility")
        if self.review_status in _UNSUPPORTED_STATUSES:
            if self.literal_eligible or self.semantic_eligible:
                raise ValueError("unsupported claims cannot enter a denominator")
            if self.treatment is not ClaimTreatment.EXCLUDED_UNSUPPORTED:
                raise ValueError("unsupported claims must remain explicit exclusions")
        elif self.semantic_eligible:
            if self.treatment not in {
                ClaimTreatment.PASS,
                ClaimTreatment.PARTIAL,
                ClaimTreatment.FAIL,
                ClaimTreatment.DIAGNOSTIC_ONLY,
            }:
                raise ValueError("eligible claims need an explicit treatment")
        if self.treatment in {
            ClaimTreatment.PASS,
            ClaimTreatment.PARTIAL,
            ClaimTreatment.FAIL,
        } and self.evaluator_id is None:
            raise ValueError("scored claims require a versioned evaluator")
        if self.treatment in {
            ClaimTreatment.DIAGNOSTIC_ONLY,
            ClaimTreatment.EXCLUDED_UNSUPPORTED,
        } and self.evaluator_id is not None:
            raise ValueError("unscored claims cannot name a scoring evaluator")
        if self.literal_eligible and self.treatment is ClaimTreatment.PARTIAL:
            raise ValueError("literal parity cannot be partially scored")
        return self


class DimensionReport(ContractModel):
    dimension: MetricDimension
    claim_ids: tuple[NonEmptyString, ...] = ()
    cross_cutting_claim_ids: tuple[NonEmptyString, ...] = ()
    eligible_literal_count: int = Field(ge=0)
    eligible_semantic_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    diagnostic_only_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    gap_row_ids: tuple[NonEmptyString, ...] = ()
    control_assignment_ids: tuple[NonEmptyString, ...] = ()
    safety_control_assignment_ids: tuple[NonEmptyString, ...] = ()
    output_comparisons: tuple[OutputComparison, ...] = ()
    observation: NonEmptyString

    @model_validator(mode="after")
    def reconcile_dimension_counts(self) -> "DimensionReport":
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("dimension claim IDs must be unique")
        if len(self.cross_cutting_claim_ids) != len(
            set(self.cross_cutting_claim_ids)
        ):
            raise ValueError("cross-cutting claim IDs must be unique")
        if self.scored_count != (
            self.pass_count + self.partial_count + self.fail_count
        ):
            raise ValueError("scored_count must match pass/partial/fail counts")
        if len(self.output_comparisons) != len(
            {item.case_id for item in self.output_comparisons}
        ):
            raise ValueError("output comparisons must be unique by case")
        return self


class MetricDistribution(ContractModel):
    count: int = Field(gt=0)
    minimum: float = Field(ge=0)
    p50: float = Field(ge=0)
    p95: float = Field(ge=0)
    maximum: float = Field(ge=0)
    mean: float = Field(ge=0)

    @model_validator(mode="after")
    def require_ordered_distribution(self) -> "MetricDistribution":
        if not self.minimum <= self.p50 <= self.p95 <= self.maximum:
            raise ValueError("distribution quantiles must be ordered")
        return self


class PerformanceReport(ContractModel):
    case_count: int = Field(gt=0)
    case_latency_ms: MetricDistribution
    parse_latency_ms: MetricDistribution
    cpu_ms: MetricDistribution
    peak_rss_bytes: MetricDistribution
    total_raw_json_bytes: int = Field(ge=0)
    total_markdown_bytes: int = Field(ge=0)
    reference_latency_p50_ms: float = Field(gt=0)
    reference_latency_p95_ms: float = Field(gt=0)
    reference_rss_p50_bytes: float = Field(gt=0)
    reference_rss_max_bytes: float = Field(gt=0)
    tolerance_percent: float = Field(ge=0)
    environment_comparable: bool
    within_tolerance: bool | None

    @model_validator(mode="after")
    def recompute_tolerance(self) -> "PerformanceReport":
        if self.case_count != self.case_latency_ms.count:
            raise ValueError("performance case_count must match distributions")
        if not all(
            summary.count == self.case_count
            for summary in (
                self.parse_latency_ms,
                self.cpu_ms,
                self.peak_rss_bytes,
            )
        ):
            raise ValueError("every distribution must cover every case")
        if not self.environment_comparable:
            if self.within_tolerance is not None:
                raise ValueError(
                    "non-comparable environments cannot claim tolerance status"
                )
            return self
        factor = 1 + self.tolerance_percent / 100
        expected = all(
            (
                self.case_latency_ms.p50
                <= self.reference_latency_p50_ms * factor,
                self.case_latency_ms.p95
                <= self.reference_latency_p95_ms * factor,
                self.peak_rss_bytes.p50
                <= self.reference_rss_p50_bytes * factor,
                self.peak_rss_bytes.maximum
                <= self.reference_rss_max_bytes * factor,
            )
        )
        if self.within_tolerance is not expected:
            raise ValueError("within_tolerance does not match declared bounds")
        return self


class OfflineCostReport(ContractModel):
    hosted_requests: Literal[0]
    prompt_tokens: Literal[0]
    completion_tokens: Literal[0]
    billed_usd: Literal[0.0]
    method: Literal["fixed offline execution policy"]


class CorpusRunRecord(ContractModel):
    schema_version: SchemaVersion
    record_kind: Literal["p00-us10-corpus-run"]
    runner_version: Literal["P00-US10-1.0"]
    run_id: NonEmptyString
    run_dir: NonEmptyString
    status: Literal["success", "completed_with_errors"]
    started_at_utc: NonEmptyString
    completed_at_utc: NonEmptyString
    command: tuple[NonEmptyString, ...] = Field(min_length=1)
    cwd: Literal["."]
    settings: dict[NonEmptyString, Any] = Field(min_length=1)
    settings_sha256: Sha256
    execution_policy: ExecutionPolicy
    environment: EnvironmentIdentity
    environment_sha256: Sha256
    frozen_inputs: FrozenInputIdentity
    selected_case_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    requested_case_count: int = Field(gt=0)
    attempted_case_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    partial_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    expected_page_count: int = Field(gt=0)
    successful_page_count: int = Field(ge=0)
    cases: tuple[CaseExecution, ...] = Field(min_length=1)
    case_record_evidence: tuple[CaseRecordEvidence, ...] = Field(min_length=1)
    diagnostics: tuple[DiagnosticRecord, ...] = ()

    @field_validator("run_dir")
    @classmethod
    def require_portable_run_dir(cls, value: str) -> str:
        return _require_portable_path(value)

    @model_validator(mode="after")
    def reconcile_run(self) -> "CorpusRunRecord":
        if not _RUN_ID.fullmatch(self.run_id):
            raise ValueError("run_id must be a stable lowercase identifier")
        if _utc(self.completed_at_utc, "completed_at_utc") < _utc(
            self.started_at_utc,
            "started_at_utc",
        ):
            raise ValueError("run completion cannot precede its start")
        if self.settings_sha256 != sha256_bytes(
            canonical_payload_bytes(self.settings)
        ):
            raise ValueError("settings_sha256 does not match settings")
        if self.environment_sha256 != sha256_bytes(
            canonical_model_bytes(self.environment)
        ):
            raise ValueError("environment_sha256 does not match environment")
        if len(self.selected_case_ids) != len(set(self.selected_case_ids)):
            raise ValueError("selected case IDs must be unique")
        canonical_selected = tuple(
            case_id
            for case_id in EXPECTED_CASE_IDS
            if case_id in self.selected_case_ids
        )
        if self.selected_case_ids != canonical_selected:
            raise ValueError("selected cases must use canonical registry order")
        run_path = PurePosixPath(self.run_dir)
        if (
            run_path.parent.as_posix()
            != "tracker/phase-00-baseline/evidence"
            or run_path.name != self.run_id
        ):
            raise ValueError(
                "run_dir must be the canonical evidence child named by run_id"
            )
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != self.selected_case_ids:
            raise ValueError("case records must exactly match selected cases")
        evidence_ids = tuple(
            evidence.case_id for evidence in self.case_record_evidence
        )
        if evidence_ids != self.selected_case_ids:
            raise ValueError(
                "case record evidence must exactly match selected cases"
            )
        for evidence in self.case_record_evidence:
            case_root = f"{self.run_dir}/{evidence.case_id}"
            if (
                evidence.worker_record.path
                != f"{case_root}/case-record.json"
                or evidence.coordinator_record.path
                != f"{case_root}/coordinator-case-record.json"
            ):
                raise ValueError(
                    "case record evidence paths must match the immutable run"
                )
        if tuple(case.order for case in self.cases) != tuple(
            range(1, len(self.cases) + 1)
        ):
            raise ValueError("case records must use contiguous order")
        if any(case.run_id != self.run_id for case in self.cases):
            raise ValueError("all cases must use the top-level run ID")
        if any(case.settings_sha256 != self.settings_sha256 for case in self.cases):
            raise ValueError("all cases must bind the top-level settings")
        if any(
            case.environment_sha256 != self.environment_sha256
            for case in self.cases
        ):
            raise ValueError("all cases must bind the top-level environment")

        counts = Counter(case.status for case in self.cases)
        expected_counts = (
            len(self.selected_case_ids),
            len(self.cases),
            counts[CaseStatus.SUCCESS],
            counts[CaseStatus.PARTIAL],
            counts[CaseStatus.ERROR],
            counts[CaseStatus.TIMEOUT],
            counts[CaseStatus.SKIPPED],
            sum(case.registered_page_count for case in self.cases),
            sum(
                case.output.successful_page_count
                for case in self.cases
                if case.output is not None
            ),
        )
        actual_counts = (
            self.requested_case_count,
            self.attempted_case_count,
            self.success_count,
            self.partial_count,
            self.error_count,
            self.timeout_count,
            self.skipped_count,
            self.expected_page_count,
            self.successful_page_count,
        )
        if actual_counts != expected_counts:
            raise ValueError("top-level case/page counts do not reconcile")
        all_success = (
            self.success_count == self.requested_case_count
            and self.successful_page_count == self.expected_page_count
            and not any(
                (
                    self.partial_count,
                    self.error_count,
                    self.timeout_count,
                    self.skipped_count,
                )
            )
        )
        expected_status = "success" if all_success else "completed_with_errors"
        if self.status != expected_status:
            raise ValueError("run status does not match case/page completion")
        return self


class LegacyM0Run(ContractModel):
    schema_version: SchemaVersion
    case_ids: tuple[NonEmptyString, ...] = Field(min_length=15, max_length=15)
    case_count: Literal[15]
    page_count: Literal[30]
    status: Literal["success"]
    metadata_sha256: Sha256
    comparison_sha256: Sha256
    performance_environment_fingerprint: Sha256


class CorpusSemanticReport(ContractModel):
    schema_version: SchemaVersion
    report_kind: Literal["p00-us10-corpus-semantic-report"]
    runner_version: Literal["P00-US10-1.0"]
    run_id: NonEmptyString
    run_record: ArtifactEvidence
    run_semantic_sha256: Sha256
    frozen_inputs: FrozenInputIdentity
    selected_case_ids: tuple[NonEmptyString, ...] = Field(min_length=1)
    case_count: int = Field(gt=0)
    page_count: int = Field(gt=0)
    reviewed_claim_count: int = Field(gt=0)
    literal_eligible_count: int = Field(ge=0)
    semantic_eligible_count: int = Field(ge=0)
    excluded_unsupported_count: int = Field(ge=0)
    scored_claim_count: int = Field(ge=0)
    diagnostic_only_count: int = Field(ge=0)
    claim_ledger: tuple[ReviewedClaimResult, ...] = Field(min_length=1)
    dimensions: tuple[DimensionReport, ...] = Field(
        min_length=len(DIMENSION_ORDER),
        max_length=len(DIMENSION_ORDER),
    )
    performance: PerformanceReport
    cost: OfflineCostReport
    quality_signature_sha256: Sha256
    stable_output_signature_sha256: Sha256
    all_outputs_stable: bool
    diagnostics: tuple[DiagnosticRecord, ...] = ()

    @model_validator(mode="after")
    def reconcile_semantic_report(self) -> "CorpusSemanticReport":
        if self.run_record.role != "corpus_run_record":
            raise ValueError("report must bind a corpus run record artifact")
        if tuple(report.dimension for report in self.dimensions) != DIMENSION_ORDER:
            raise ValueError("all 12 dimensions must appear in canonical order")
        claim_ids = tuple(claim.claim_id for claim in self.claim_ledger)
        if len(claim_ids) != len(set(claim_ids)) or claim_ids != tuple(
            sorted(claim_ids)
        ):
            raise ValueError("claim ledger IDs must be unique and canonical")
        primary_ids = tuple(
            claim_id for report in self.dimensions for claim_id in report.claim_ids
        )
        if len(primary_ids) != len(set(primary_ids)):
            raise ValueError("claims must have exactly one primary dimension")
        if set(primary_ids) != set(claim_ids):
            raise ValueError("dimension claims must exactly cover the ledger")
        counts = (
            len(self.claim_ledger),
            sum(claim.literal_eligible for claim in self.claim_ledger),
            sum(claim.semantic_eligible for claim in self.claim_ledger),
            sum(
                claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
                for claim in self.claim_ledger
            ),
            sum(
                claim.treatment
                in {
                    ClaimTreatment.PASS,
                    ClaimTreatment.PARTIAL,
                    ClaimTreatment.FAIL,
                }
                for claim in self.claim_ledger
            ),
            sum(
                claim.treatment is ClaimTreatment.DIAGNOSTIC_ONLY
                for claim in self.claim_ledger
            ),
        )
        declared = (
            self.reviewed_claim_count,
            self.literal_eligible_count,
            self.semantic_eligible_count,
            self.excluded_unsupported_count,
            self.scored_claim_count,
            self.diagnostic_only_count,
        )
        if counts != declared:
            raise ValueError("semantic report claim counts do not reconcile")
        if self.case_count != len(self.selected_case_ids):
            raise ValueError("case_count must match selected cases")
        if self.performance.case_count != self.case_count:
            raise ValueError("performance must cover every selected case")
        if self.case_count == 15 and (
            self.page_count,
            self.reviewed_claim_count,
            self.literal_eligible_count,
            self.semantic_eligible_count,
            self.excluded_unsupported_count,
        ) != (30, 210, 109, 162, 48):
            raise ValueError("full-corpus reviewed totals changed")
        comparisons = {
            item.case_id: item
            for report in self.dimensions
            for item in report.output_comparisons
        }
        stable = bool(comparisons) and all(
            item.semantic_json_stable and item.markdown_stable
            for item in comparisons.values()
        )
        if self.all_outputs_stable is not stable:
            raise ValueError("all_outputs_stable does not match comparisons")
        if self.quality_signature_sha256 != _quality_signature(
            self.claim_ledger,
            self.dimensions,
        ):
            raise ValueError("quality signature does not match report counts")
        if self.stable_output_signature_sha256 != _stable_output_signature(
            tuple(comparisons[case_id] for case_id in sorted(comparisons))
        ):
            raise ValueError("stable output signature does not match comparisons")
        return self


def _write_json_exclusive(path: Path, payload: Any) -> None:
    """Write one immutable JSON artifact, refusing any existing path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            payload,
            stream,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")


def _write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(value)


def _workspace_path(path: Path, workspace_root: Path = WORKSPACE) -> str:
    resolved = path.resolve()
    root = workspace_root.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("evidence paths must remain inside the workspace") from exc


def _package_version(name: str) -> str:
    try:
        value = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError(f"required engine version is missing: {name}") from exc
    if value.lower() in _UNAVAILABLE_VALUES:
        raise ValueError(f"required engine version is missing: {name}")
    return value


def _command_version(command: str, *args: str) -> str:
    try:
        completed = subprocess.run(
            [command, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"required engine is unavailable: {command}") from exc
    lines = (completed.stdout or completed.stderr).splitlines()
    if completed.returncode != 0 or not lines:
        raise ValueError(f"required engine version is missing: {command}")
    return lines[0].strip()


def _tree_sha256(paths: Sequence[Path], workspace_root: Path = WORKSPACE) -> str:
    digest = hashlib.sha256()
    for path in sorted({item.resolve() for item in paths}):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(workspace_root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("identity inputs must remain in the workspace") from exc
        relative_bytes = relative.encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative_bytes).to_bytes(4, "big"))
        digest.update(relative_bytes)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def application_source_sha256(workspace_root: Path = WORKSPACE) -> str:
    paths = list((workspace_root / "app").rglob("*.py"))
    paths.extend(
        workspace_root / name
        for name in ("pyproject.toml", "uv.lock")
        if (workspace_root / name).is_file()
    )
    return _tree_sha256(paths, workspace_root)


def runner_source_sha256(workspace_root: Path = WORKSPACE) -> str:
    names = (
        "tests/benchmarks/corpus_runner.py",
        "tests/benchmarks/contracts.py",
        "tests/benchmarks/corpus_registry.py",
        "tests/benchmarks/reviewed_claims.py",
        "tests/benchmarks/reviewed_claim_inventory.py",
        "tests/benchmarks/control_registry.py",
    )
    return _tree_sha256(
        [workspace_root / name for name in names],
        workspace_root,
    )


def collect_environment(workspace_root: Path = WORKSPACE) -> EnvironmentIdentity:
    application_version = _package_version("document-parse-api")
    engines = (
        EngineIdentity(name="docling", version=_package_version("docling")),
        EngineIdentity(
            name="docling-core",
            version=_package_version("docling-core"),
        ),
        EngineIdentity(
            name="pdfplumber",
            version=_package_version("pdfplumber"),
        ),
        EngineIdentity(
            name="pypdfium2",
            version=_package_version("pypdfium2"),
        ),
        EngineIdentity(name="pillow", version=_package_version("Pillow")),
        EngineIdentity(
            name="tesseract",
            version=_command_version(
                str(DEFAULT_SETTINGS["tesseract_cmd"]),
                "--version",
            ),
        ),
    )
    physical = psutil.cpu_count(logical=False)
    if physical is None:
        raise ValueError("physical CPU count is unavailable")
    processor = platform.processor() or platform.machine()
    return EnvironmentIdentity(
        application_version=application_version,
        application_source_sha256=application_source_sha256(workspace_root),
        runner_source_sha256=runner_source_sha256(workspace_root),
        python_version=sys.version,
        # Resolve venv aliases (for example ``python`` versus ``python3``) so
        # equivalent invocations have one reproducible interpreter identity.
        python_executable=Path(sys.executable).resolve().as_posix(),
        platform=platform.platform(),
        machine=platform.machine(),
        processor=processor,
        logical_cpu_count=os.cpu_count() or 1,
        physical_cpu_count=physical,
        total_memory_bytes=int(psutil.virtual_memory().total),
        engines=engines,
    )


def _settings_payload() -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in DEFAULT_SETTINGS.items()
    }


def _artifact_from_registered(artifact: Any) -> ArtifactEvidence:
    return ArtifactEvidence(
        role=artifact.role.value,
        path=artifact.path,
        sha256=artifact.sha256,
        size_bytes=artifact.size_bytes,
    )


def _case_triplet(case: RegistryCase) -> tuple[ArtifactEvidence, ...]:
    return tuple(_artifact_from_registered(item) for item in case.artifacts)


def _review_batch_loaders() -> tuple[
    tuple[str, str, Callable[[str | Path, str | Path, PortableCorpusRegistry], ReviewBatch]],
    ...,
]:
    return (
        (
            "p00-us06-reviewed-claims-batch-a",
            BATCH_A_EVIDENCE_PATH,
            load_reviewed_claim_batch_a,
        ),
        (
            "p00-us07-reviewed-claims-batch-b",
            BATCH_B_EVIDENCE_PATH,
            load_reviewed_claim_batch_b,
        ),
        (
            "p00-us08-reviewed-claims-batch-c",
            BATCH_C_EVIDENCE_PATH,
            load_reviewed_claim_batch_c,
        ),
    )


@dataclass(frozen=True)
class BenchmarkContext:
    workspace_root: Path
    corpus_registry: PortableCorpusRegistry
    review_batches: tuple[ReviewBatch, ...]
    control_registry: BenchmarkControlRegistry
    frozen_inputs: FrozenInputIdentity
    environment: EnvironmentIdentity
    environment_sha256: str
    settings: dict[str, Any]
    settings_sha256: str
    legacy: LegacyM0Run


def _performance_environment_payload(
    *,
    platform_value: str,
    machine: str,
    python_version: str,
    logical_cpu_count: int,
    physical_cpu_count: int,
    total_memory_bytes: int,
    application_version: str,
    engines: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "platform": platform_value,
        "machine": machine,
        "python": python_version.split()[0],
        "logical_cpu_count": logical_cpu_count,
        "physical_cpu_count": physical_cpu_count,
        "total_memory_bytes": total_memory_bytes,
        "application_version": application_version,
        "engines": dict(sorted(engines.items())),
    }


def performance_environment_fingerprint(
    environment: EnvironmentIdentity,
) -> str:
    return sha256_bytes(
        canonical_payload_bytes(
            _performance_environment_payload(
                platform_value=environment.platform,
                machine=environment.machine,
                python_version=environment.python_version,
                logical_cpu_count=environment.logical_cpu_count,
                physical_cpu_count=environment.physical_cpu_count,
                total_memory_bytes=environment.total_memory_bytes,
                application_version=environment.application_version,
                engines={
                    engine.name: engine.version for engine in environment.engines
                },
            )
        )
    )


def read_legacy_m0_run(
    workspace_root: str | Path = WORKSPACE,
) -> LegacyM0Run:
    """Read and strictly project the frozen analysis run without rewriting it."""

    root = Path(workspace_root).resolve()
    run_root = resolve_portable_path(root, LEGACY_M0_RUN_ROOT)
    metadata_path = run_root / "run-metadata.json"
    comparison_path = run_root / "comparison-summary.json"
    if sha256_file(metadata_path) != LEGACY_M0_METADATA_SHA256:
        raise ValueError("legacy M0 run metadata identity changed")
    if sha256_file(comparison_path) != LEGACY_M0_COMPARISON_SHA256:
        raise ValueError("legacy M0 comparison identity changed")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    case_ids = tuple(metadata.get("case_ids") or ())
    if (
        metadata.get("schema_version") != "1.0"
        or metadata.get("status") != "success"
        or metadata.get("case_count") != 15
        or case_ids != EXPECTED_CASE_IDS
        or any(case.get("status") != "success" for case in metadata.get("cases", ()))
    ):
        raise ValueError("legacy M0 metadata is incomplete or unsupported")
    if isinstance(comparison, list):
        if tuple(item.get("case_id") for item in comparison) != EXPECTED_CASE_IDS:
            raise ValueError("legacy M0 comparison case order changed")
        page_count = sum(int(item.get("our_pages", 0)) for item in comparison)
    elif isinstance(comparison, dict):
        summary = comparison.get("summary") or comparison
        page_count = summary.get("our_page_count")
    else:
        raise ValueError("legacy M0 comparison schema is unsupported")
    if page_count is None:
        page_count = sum(
            json.loads(
                (run_root / case_id / "diagnostics.json").read_text(
                    encoding="utf-8"
                )
            )
            .get("output", {})
            .get("page_count", 0)
            for case_id in case_ids
        )
    if page_count != 30:
        raise ValueError("legacy M0 comparison does not cover 30 pages")
    environment = metadata.get("environment") or {}
    packages = environment.get("packages") or {}
    engine_versions = {
        "docling": packages.get("docling"),
        "docling-core": packages.get("docling-core"),
        "pdfplumber": packages.get("pdfplumber"),
        "pypdfium2": packages.get("pypdfium2"),
        "pillow": packages.get("Pillow"),
        "tesseract": environment.get("tesseract"),
    }
    if any(
        not isinstance(value, str) or value.lower() in _UNAVAILABLE_VALUES
        for value in engine_versions.values()
    ):
        raise ValueError("legacy M0 engine identity is incomplete")
    fingerprint = sha256_bytes(
        canonical_payload_bytes(
            _performance_environment_payload(
                platform_value=str(environment["platform"]),
                machine=str(environment["machine"]),
                python_version=str(environment["python_version"]),
                logical_cpu_count=int(environment["logical_cpu_count"]),
                physical_cpu_count=int(environment["physical_cpu_count"]),
                total_memory_bytes=int(environment["total_memory_bytes"]),
                application_version=str(environment["application_version"]),
                engines=engine_versions,
            )
        )
    )
    return LegacyM0Run(
        schema_version="1.0",
        case_ids=case_ids,
        case_count=15,
        page_count=30,
        status="success",
        metadata_sha256=LEGACY_M0_METADATA_SHA256,
        comparison_sha256=LEGACY_M0_COMPARISON_SHA256,
        performance_environment_fingerprint=fingerprint,
    )


def _verify_reference_outputs(workspace_root: Path) -> None:
    if tuple(REFERENCE_OUTPUT_IDENTITIES) != EXPECTED_CASE_IDS:
        raise ValueError("reference output identity table is incomplete")
    run_root = resolve_portable_path(workspace_root, LEGACY_M0_RUN_ROOT)
    for case_id, (expected_semantic, expected_markdown) in (
        REFERENCE_OUTPUT_IDENTITIES.items()
    ):
        json_path = run_root / case_id / "our-output.json"
        markdown_path = run_root / case_id / "our-output.md"
        if not json_path.is_file() or not markdown_path.is_file():
            raise ValueError(f"legacy reference output is missing for {case_id}")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        semantic_sha = sha256_bytes(semantic_json_bytes(payload))
        markdown_sha = sha256_file(markdown_path)
        if (semantic_sha, markdown_sha) != (
            expected_semantic,
            expected_markdown,
        ):
            raise ValueError(f"legacy reference output identity changed for {case_id}")


def load_benchmark_context(
    workspace_root: str | Path = WORKSPACE,
    *,
    corpus_registry_path: str = CORPUS_REGISTRY_PATH,
    control_registry_path: str = CONTROL_REGISTRY_EVIDENCE_PATH,
    historical_environment: EnvironmentIdentity | None = None,
    historical_settings: Mapping[str, Any] | None = None,
) -> BenchmarkContext:
    """Validate every frozen input and required version before reserving a run."""

    root = Path(workspace_root).resolve()
    registry_path = resolve_portable_path(root, corpus_registry_path)
    registry = load_corpus_registry(registry_path)
    verify_current_artifacts(registry, root)

    batches: list[ReviewBatch] = []
    batch_bindings: list[InputBinding] = []
    for expected_id, path, loader in _review_batch_loaders():
        resolved = resolve_portable_path(root, path)
        batch = loader(resolved, root, registry)
        if batch.batch_id != expected_id:
            raise ValueError("review batch identity changed")
        batches.append(batch)
        batch_bindings.append(
            InputBinding(
                identity=batch.batch_id,
                path=path,
                file_sha256=sha256_file(resolved),
                semantic_sha256=review_batch_sha256(batch),
            )
        )
    review_batches = tuple(batches)
    control_path = resolve_portable_path(root, control_registry_path)
    control = load_benchmark_control_registry(
        control_path,
        root,
        registry,
        review_batches,
    )
    _verify_reference_outputs(root)
    legacy = read_legacy_m0_run(root)
    frozen_inputs = FrozenInputIdentity(
        corpus_registry=InputBinding(
            identity=registry.registry_id,
            path=corpus_registry_path,
            file_sha256=sha256_file(registry_path),
            semantic_sha256=corpus_registry_sha256(registry),
        ),
        control_registry=InputBinding(
            identity=control.registry_id,
            path=control_registry_path,
            file_sha256=sha256_file(control_path),
            semantic_sha256=control_registry_sha256(control),
        ),
        review_batches=tuple(batch_bindings),
        legacy_metadata_sha256=legacy.metadata_sha256,
        legacy_comparison_sha256=legacy.comparison_sha256,
    )
    environment = historical_environment or collect_environment(root)
    environment_sha = sha256_bytes(canonical_model_bytes(environment))
    settings = (
        dict(historical_settings)
        if historical_settings is not None
        else _settings_payload()
    )
    settings_sha = sha256_bytes(canonical_payload_bytes(settings))
    return BenchmarkContext(
        workspace_root=root,
        corpus_registry=registry,
        review_batches=review_batches,
        control_registry=control,
        frozen_inputs=frozen_inputs,
        environment=environment,
        environment_sha256=environment_sha,
        settings=settings,
        settings_sha256=settings_sha,
        legacy=legacy,
    )


def normalize_case_selection(
    registry: PortableCorpusRegistry,
    selected_case_ids: Sequence[str] | None,
) -> tuple[str, ...]:
    if selected_case_ids is None:
        return tuple(case.case_id for case in registry.cases)
    selected = tuple(selected_case_ids)
    if not selected:
        raise ValueError("explicit case selection must not be empty")
    if len(selected) != len(set(selected)):
        raise ValueError("explicit case selection contains duplicates")
    known = {case.case_id for case in registry.cases}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ValueError("unknown corpus cases: " + ", ".join(unknown))
    return tuple(case.case_id for case in registry.cases if case.case_id in selected)


def _normalize_warning(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _verify_case_triplet(
    case: RegistryCase,
    workspace_root: Path,
) -> tuple[ArtifactEvidence, ...]:
    evidence = _case_triplet(case)
    for artifact in evidence:
        path = resolve_portable_path(workspace_root, artifact.path)
        if not path.is_file():
            raise ValueError(f"registered artifact is missing: {artifact.path}")
        if path.stat().st_size != artifact.size_bytes:
            raise ValueError(f"registered artifact size changed: {artifact.path}")
        if sha256_file(path) != artifact.sha256:
            raise ValueError(f"registered artifact hash changed: {artifact.path}")
    return evidence


def _reference_comparison(
    *,
    case_id: str,
    semantic_json_sha256: str,
    markdown_sha256: str,
) -> OutputComparison:
    try:
        reference_semantic, reference_markdown = REFERENCE_OUTPUT_IDENTITIES[
            case_id
        ]
    except KeyError as exc:
        raise ValueError(f"missing frozen output identity for {case_id}") from exc
    return OutputComparison(
        case_id=case_id,
        current_semantic_json_sha256=semantic_json_sha256,
        reference_semantic_json_sha256=reference_semantic,
        semantic_json_stable=semantic_json_sha256 == reference_semantic,
        current_markdown_sha256=markdown_sha256,
        reference_markdown_sha256=reference_markdown,
        markdown_stable=markdown_sha256 == reference_markdown,
    )


def _case_error(
    *,
    code: str,
    stage: str,
    exc: BaseException,
    remediation: str,
) -> ErrorRecord:
    rendered = traceback.format_exc()
    if rendered.strip() == "NoneType: None":
        rendered = f"{type(exc).__name__}: {exc}"
    return ErrorRecord(
        code=code,
        stage=stage,
        exception_type=type(exc).__name__,
        message=str(exc) or type(exc).__name__,
        remediation=remediation,
        traceback=rendered,
    )


def _require_offline_worker_environment() -> None:
    expected = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    changed = {
        name: os.environ.get(name)
        for name, value in expected.items()
        if os.environ.get(name) != value
    }
    if changed:
        raise ValueError(
            "worker requires HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, "
            "and TOKENIZERS_PARALLELISM=false"
        )


def run_case_worker(
    *,
    workspace_root: Path,
    corpus_registry_path: str,
    case_id: str,
    output_dir: Path,
    run_id: str,
    order: int,
    expected_settings_sha256: str,
    expected_environment_sha256: str,
) -> int:
    """Run one registered PDF in a fresh process and immutable child directory."""

    _require_offline_worker_environment()
    registry_path = resolve_portable_path(workspace_root, corpus_registry_path)
    registry = load_corpus_registry(registry_path)
    case = registry.case_by_id(case_id)
    triplet = _verify_case_triplet(case, workspace_root)
    settings_payload = _settings_payload()
    settings_sha = sha256_bytes(canonical_payload_bytes(settings_payload))
    if settings_sha != expected_settings_sha256:
        raise ValueError("worker settings identity differs from the coordinator")
    environment = collect_environment(workspace_root)
    environment_sha = sha256_bytes(canonical_model_bytes(environment))
    if environment_sha != expected_environment_sha256:
        raise ValueError("worker environment identity differs from the coordinator")
    output_dir.mkdir(parents=True, exist_ok=False)

    from app.config import Settings
    from app.services.pipeline import parse_document
    from app.services.serializer import to_markdown

    source_artifact = triplet[0]
    source_path = resolve_portable_path(workspace_root, source_artifact.path)
    source_bytes = source_path.read_bytes()
    command = (
        ".venv/bin/python3",
        "-m",
        "tests.benchmarks.corpus_runner",
        "worker",
        "--workspace",
        ".",
        "--corpus-registry",
        corpus_registry_path,
        "--case-id",
        case_id,
        "--output-dir",
        _workspace_path(output_dir, workspace_root),
        "--run-id",
        run_id,
        "--order",
        str(order),
        "--settings-sha256",
        expected_settings_sha256,
        "--environment-sha256",
        expected_environment_sha256,
    )
    started_at = utc_now()
    started_perf = time.perf_counter()
    started_cpu = time.process_time()
    status = CaseStatus.ERROR
    worker_exit_code = 1
    output: CaseOutputEvidence | None = None
    comparison: OutputComparison | None = None
    error: ErrorRecord | None = None
    warnings: tuple[str, ...] = ()
    parse_latency_ms = 0.0
    try:
        settings = Settings(**DEFAULT_SETTINGS)
        parse_started = time.perf_counter()
        result = parse_document(source_bytes, source_path.name, settings)
        parse_latency_ms = (time.perf_counter() - parse_started) * 1000
        payload = result.model_dump(mode="json")
        markdown = to_markdown(result)

        raw_path = output_dir / "our-output.json"
        markdown_path = output_dir / "our-output.md"
        _write_json_exclusive(raw_path, payload)
        _write_text_exclusive(markdown_path, markdown)
        raw_bytes = raw_path.read_bytes()
        markdown_bytes = markdown_path.read_bytes()
        semantic_bytes = semantic_json_bytes(payload)

        pages = payload.get("pages")
        if not isinstance(pages, list):
            raise ValueError("parser output pages must be a list")
        successful_pages = sum(
            isinstance(page, dict) and page.get("success") is True
            for page in pages
        )
        document_warnings = tuple(
            _normalize_warning(item) for item in (payload.get("warnings") or ())
        )
        page_warnings = tuple(
            _normalize_warning(item)
            for page in pages
            if isinstance(page, dict)
            for item in (page.get("warnings") or ())
        )
        warnings = document_warnings + page_warnings
        output = CaseOutputEvidence(
            raw_json=ArtifactEvidence(
                role="raw_json",
                path=_workspace_path(raw_path, workspace_root),
                sha256=sha256_bytes(raw_bytes),
                size_bytes=len(raw_bytes),
            ),
            semantic_json=ArtifactEvidence(
                role="semantic_json",
                path=_workspace_path(raw_path, workspace_root),
                sha256=sha256_bytes(semantic_bytes),
                size_bytes=len(semantic_bytes),
                derivation="canonical JSON excluding /processing/duration_ms",
            ),
            markdown=ArtifactEvidence(
                role="markdown",
                path=_workspace_path(markdown_path, workspace_root),
                sha256=sha256_bytes(markdown_bytes),
                size_bytes=len(markdown_bytes),
            ),
            expected_page_count=case.page_count,
            observed_page_count=len(pages),
            successful_page_count=successful_pages,
            document_warnings=document_warnings,
        )
        comparison = _reference_comparison(
            case_id=case_id,
            semantic_json_sha256=output.semantic_json.sha256,
            markdown_sha256=output.markdown.sha256,
        )
        if len(pages) != case.page_count or successful_pages != case.page_count:
            status = CaseStatus.PARTIAL
            error = ErrorRecord(
                code="partial-page-output",
                stage="output-validation",
                exception_type="IncompleteCaseOutput",
                message=(
                    f"{case_id} produced {successful_pages}/{len(pages)} successful "
                    f"pages; {case.page_count} registered pages were required"
                ),
                remediation=(
                    "Inspect the retained raw output and worker logs; do not score "
                    "or promote this partial run."
                ),
                traceback="IncompleteCaseOutput: registered page coverage failed",
            )
        else:
            status = CaseStatus.SUCCESS
            worker_exit_code = 0
    except Exception as exc:  # noqa: BLE001 - failures are retained evidence.
        if output is not None:
            status = CaseStatus.PARTIAL
        error = _case_error(
            code="case-worker-failure",
            stage="parse-or-output",
            exc=exc,
            remediation=(
                "Inspect the retained case output and traceback, correct the "
                "environment or input issue, and use a new run ID."
            ),
        )
    completed_at = utc_now()
    case_latency_ms = (time.perf_counter() - started_perf) * 1000
    record = CaseExecution(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        case_id=case_id,
        order=order,
        status=status,
        registered_page_count=case.page_count,
        source_triplet=triplet,
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        command=command,
        worker_exit_code=worker_exit_code,
        parse_latency_ms=parse_latency_ms,
        case_latency_ms=case_latency_ms,
        cpu_ms=(time.process_time() - started_cpu) * 1000,
        peak_rss_bytes=max(normalized_peak_rss_bytes(), 1),
        settings_sha256=settings_sha,
        environment_sha256=environment_sha,
        warnings=warnings,
        output=output,
        reference_comparison=comparison,
        error=error,
    )
    _write_json_exclusive(
        output_dir / "case-record.json",
        record.model_dump(mode="json"),
    )
    return worker_exit_code


def load_case_execution(path: str | Path) -> CaseExecution:
    return CaseExecution.model_validate_json(Path(path).read_bytes())


def _verify_artifact_file(
    artifact: ArtifactEvidence,
    workspace_root: Path,
) -> None:
    path = resolve_portable_path(workspace_root, artifact.path)
    if not path.is_file():
        raise ValueError(f"retained artifact is missing: {artifact.path}")
    if artifact.role == "semantic_json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = semantic_json_bytes(payload)
        if len(value) != artifact.size_bytes or sha256_bytes(value) != artifact.sha256:
            raise ValueError("retained semantic JSON projection changed")
        return
    if path.stat().st_size != artifact.size_bytes:
        raise ValueError(f"retained artifact size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"retained artifact hash changed: {artifact.path}")


def _file_artifact(
    *,
    role: str,
    path: Path,
    workspace_root: Path,
) -> ArtifactEvidence:
    data = path.read_bytes()
    return ArtifactEvidence(
        role=role,
        path=_workspace_path(path, workspace_root),
        sha256=sha256_bytes(data),
        size_bytes=len(data),
    )


def verify_case_execution(
    case: CaseExecution,
    workspace_root: Path,
) -> CaseExecution:
    for artifact in case.source_triplet:
        _verify_artifact_file(artifact, workspace_root)
    if case.output is not None:
        _verify_artifact_file(case.output.raw_json, workspace_root)
        _verify_artifact_file(case.output.semantic_json, workspace_root)
        _verify_artifact_file(case.output.markdown, workspace_root)
    return case


def _decode_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else value.decode(errors="replace")


def _synthetic_case_failure(
    *,
    context: BenchmarkContext,
    case: RegistryCase,
    run_id: str,
    order: int,
    command: Sequence[str],
    started_at: str,
    completed_at: str,
    case_latency_ms: float,
    status: CaseStatus,
    exit_code: int,
    error: ErrorRecord,
) -> CaseExecution:
    return CaseExecution(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        case_id=case.case_id,
        order=order,
        status=status,
        registered_page_count=case.page_count,
        source_triplet=_case_triplet(case),
        started_at_utc=started_at,
        completed_at_utc=completed_at,
        command=tuple(command),
        worker_exit_code=exit_code,
        parse_latency_ms=0,
        case_latency_ms=max(case_latency_ms, 0),
        cpu_ms=0,
        peak_rss_bytes=max(normalized_peak_rss_bytes(), 1),
        settings_sha256=context.settings_sha256,
        environment_sha256=context.environment_sha256,
        error=error,
    )


def _coordinator_error(
    *,
    code: str,
    stage: str,
    exception_type: str,
    message: str,
    remediation: str,
    trace: str,
) -> ErrorRecord:
    return ErrorRecord(
        code=code,
        stage=stage,
        exception_type=exception_type,
        message=message,
        remediation=remediation,
        traceback=trace,
    )


SubprocessExecutor = Callable[..., subprocess.CompletedProcess[str]]


def capture_corpus(
    *,
    run_dir: str | Path,
    run_id: str,
    selected_case_ids: Sequence[str] | None = None,
    workspace_root: str | Path = WORKSPACE,
    corpus_registry_path: str = CORPUS_REGISTRY_PATH,
    control_registry_path: str = CONTROL_REGISTRY_EVIDENCE_PATH,
    timeout_seconds: float = 420.0,
    executor: SubprocessExecutor | None = None,
) -> CorpusRunRecord:
    """Capture an immutable selected-corpus run after a complete preflight."""

    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a stable lowercase identifier")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = load_benchmark_context(
        workspace_root,
        corpus_registry_path=corpus_registry_path,
        control_registry_path=control_registry_path,
    )
    selected = normalize_case_selection(
        context.corpus_registry,
        selected_case_ids,
    )
    root = context.workspace_root
    candidate = Path(run_dir)
    resolved_run_dir = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    portable_run_dir = _workspace_path(resolved_run_dir, root)
    required_parent = resolve_portable_path(
        root,
        "tracker/phase-00-baseline/evidence",
    )
    if (
        resolved_run_dir.parent != required_parent
        or resolved_run_dir.name != run_id
    ):
        raise ValueError(
            "run directory must be the canonical evidence child named by run_id"
        )

    # This is deliberately after every registry/hash/version/reference check.
    try:
        resolved_run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(
            f"refusing to overwrite immutable run directory: {portable_run_dir}"
        ) from exc

    command = (
        ".venv/bin/python3",
        "-m",
        "tests.benchmarks.corpus_runner",
        "capture",
        "--workspace",
        ".",
        "--run-dir",
        portable_run_dir,
        "--run-id",
        run_id,
        "--corpus-registry",
        corpus_registry_path,
        "--control-registry",
        control_registry_path,
        "--timeout-seconds",
        str(timeout_seconds),
        *(("--cases", *selected) if selected_case_ids is not None else ()),
    )
    _write_text_exclusive(
        resolved_run_dir / "command.txt",
        " ".join(command) + "\n",
    )
    run_started = utc_now()
    execute = executor or subprocess.run
    records: list[CaseExecution] = []
    record_evidence: list[CaseRecordEvidence] = []
    diagnostics: list[DiagnosticRecord] = []
    child_environment = os.environ.copy()
    child_environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    cases_by_id = {
        case.case_id: case for case in context.corpus_registry.cases
    }
    for order, case_id in enumerate(selected, start=1):
        case = cases_by_id[case_id]
        case_dir = resolved_run_dir / case_id
        worker_command = [
            sys.executable,
            "-m",
            "tests.benchmarks.corpus_runner",
            "worker",
            "--workspace",
            str(root),
            "--corpus-registry",
            corpus_registry_path,
            "--case-id",
            case_id,
            "--output-dir",
            str(case_dir),
            "--run-id",
            run_id,
            "--order",
            str(order),
            "--settings-sha256",
            context.settings_sha256,
            "--environment-sha256",
            context.environment_sha256,
        ]
        case_started = utc_now()
        case_perf = time.perf_counter()
        stdout = ""
        stderr = ""
        completed_at = case_started
        record: CaseExecution | None = None
        try:
            completed = execute(
                worker_command,
                cwd=root,
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            stdout = _decode_subprocess_output(completed.stdout)
            stderr = _decode_subprocess_output(completed.stderr)
            completed_at = utc_now()
            elapsed_ms = (time.perf_counter() - case_perf) * 1000
            case_record_path = case_dir / "case-record.json"
            if not case_record_path.is_file():
                error = _coordinator_error(
                    code="missing-case-record",
                    stage="coordinator",
                    exception_type="MissingCaseRecord",
                    message=(
                        f"{case_id} worker exited {completed.returncode} without "
                        "a case-record.json"
                    ),
                    remediation=(
                        "Inspect worker logs and rerun with a new run ID after "
                        "correcting the worker failure."
                    ),
                    trace="MissingCaseRecord: worker produced no final record",
                )
                record = _synthetic_case_failure(
                    context=context,
                    case=case,
                    run_id=run_id,
                    order=order,
                    command=worker_command,
                    started_at=case_started,
                    completed_at=completed_at,
                    case_latency_ms=elapsed_ms,
                    status=CaseStatus.ERROR,
                    exit_code=completed.returncode,
                    error=error,
                )
                case_dir.mkdir(parents=True, exist_ok=True)
                _write_json_exclusive(
                    case_record_path,
                    record.model_dump(mode="json"),
                )
            else:
                try:
                    loaded = verify_case_execution(
                        load_case_execution(case_record_path),
                        root,
                    )
                    if (
                        loaded.case_id != case_id
                        or loaded.order != order
                        or loaded.run_id != run_id
                    ):
                        raise ValueError("worker case identity differs from request")
                    if (completed.returncode == 0) != (
                        loaded.status is CaseStatus.SUCCESS
                    ):
                        raise ValueError(
                            "worker exit code and final case status disagree"
                        )
                    record = CaseExecution.model_validate(
                        {
                            **loaded.model_dump(mode="json"),
                            "case_latency_ms": elapsed_ms,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    record = _synthetic_case_failure(
                        context=context,
                        case=case,
                        run_id=run_id,
                        order=order,
                        command=worker_command,
                        started_at=case_started,
                        completed_at=completed_at,
                        case_latency_ms=elapsed_ms,
                        status=CaseStatus.ERROR,
                        exit_code=completed.returncode,
                        error=_case_error(
                            code="invalid-case-record",
                            stage="coordinator-validation",
                            exc=exc,
                            remediation=(
                                "Retain this run as failed; inspect the worker "
                                "record and use a new run ID after correction."
                            ),
                        ),
                    )
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_subprocess_output(exc.stdout)
            stderr = _decode_subprocess_output(exc.stderr)
            completed_at = utc_now()
            elapsed_ms = (time.perf_counter() - case_perf) * 1000
            record = _synthetic_case_failure(
                context=context,
                case=case,
                run_id=run_id,
                order=order,
                command=worker_command,
                started_at=case_started,
                completed_at=completed_at,
                case_latency_ms=elapsed_ms,
                status=CaseStatus.TIMEOUT,
                exit_code=124,
                error=_coordinator_error(
                    code="case-timeout",
                    stage="coordinator-timeout",
                    exception_type="TimeoutExpired",
                    message=f"{case_id} exceeded {timeout_seconds:.3f} seconds",
                    remediation=(
                        "Inspect worker logs and resource evidence; retain this "
                        "failed run and use a new run ID for any retry."
                    ),
                    trace=f"TimeoutExpired: {case_id} exceeded declared timeout",
                ),
            )
            case_dir.mkdir(parents=True, exist_ok=True)
            case_record_path = case_dir / "case-record.json"
            if not case_record_path.exists():
                _write_json_exclusive(
                    case_record_path,
                    record.model_dump(mode="json"),
                )
        except Exception as exc:  # noqa: BLE001
            completed_at = utc_now()
            elapsed_ms = (time.perf_counter() - case_perf) * 1000
            record = _synthetic_case_failure(
                context=context,
                case=case,
                run_id=run_id,
                order=order,
                command=worker_command,
                started_at=case_started,
                completed_at=completed_at,
                case_latency_ms=elapsed_ms,
                status=CaseStatus.ERROR,
                exit_code=1,
                error=_case_error(
                    code="coordinator-executor-failure",
                    stage="coordinator",
                    exc=exc,
                    remediation=(
                        "Inspect the coordinator traceback and rerun with a new "
                        "run ID after correcting the execution environment."
                    ),
                ),
            )
            case_dir.mkdir(parents=True, exist_ok=True)
            case_record_path = case_dir / "case-record.json"
            if not case_record_path.exists():
                _write_json_exclusive(
                    case_record_path,
                    record.model_dump(mode="json"),
                )
        assert record is not None
        if not (case_dir / "worker-stdout.log").exists():
            _write_text_exclusive(case_dir / "worker-stdout.log", stdout)
        if not (case_dir / "worker-stderr.log").exists():
            _write_text_exclusive(case_dir / "worker-stderr.log", stderr)
        coordinator_record_path = case_dir / "coordinator-case-record.json"
        _write_json_exclusive(
            coordinator_record_path,
            record.model_dump(mode="json"),
        )
        worker_record_path = case_dir / "case-record.json"
        if not worker_record_path.is_file():
            raise ValueError(
                f"{case_id} has no retained worker case record after coordination"
            )
        record_evidence.append(
            CaseRecordEvidence(
                case_id=case_id,
                worker_record=_file_artifact(
                    role="worker_case_record",
                    path=worker_record_path,
                    workspace_root=root,
                ),
                coordinator_record=_file_artifact(
                    role="coordinator_case_record",
                    path=coordinator_record_path,
                    workspace_root=root,
                ),
            )
        )
        records.append(record)
        if record.status is not CaseStatus.SUCCESS:
            diagnostics.append(
                DiagnosticRecord(
                    code=f"case-{record.status.value}",
                    stage="case-execution",
                    case_id=case_id,
                    message=(
                        record.error.message
                        if record.error is not None
                        else record.skip.reason
                    ),
                    remediation=(
                        record.error.remediation
                        if record.error is not None
                        else record.skip.opt_in_condition
                    ),
                )
            )

    counts = Counter(record.status for record in records)
    expected_pages = sum(record.registered_page_count for record in records)
    successful_pages = sum(
        record.output.successful_page_count
        for record in records
        if record.output is not None
    )
    run = CorpusRunRecord(
        schema_version="1.0",
        record_kind=RECORD_KIND,
        runner_version=RUNNER_VERSION,
        run_id=run_id,
        run_dir=portable_run_dir,
        status=(
            "success"
            if counts[CaseStatus.SUCCESS] == len(records)
            and successful_pages == expected_pages
            else "completed_with_errors"
        ),
        started_at_utc=run_started,
        completed_at_utc=utc_now(),
        command=command,
        cwd=".",
        settings=context.settings,
        settings_sha256=context.settings_sha256,
        execution_policy=FIXED_EXECUTION_POLICY,
        environment=context.environment,
        environment_sha256=context.environment_sha256,
        frozen_inputs=context.frozen_inputs,
        selected_case_ids=selected,
        requested_case_count=len(selected),
        attempted_case_count=len(records),
        success_count=counts[CaseStatus.SUCCESS],
        partial_count=counts[CaseStatus.PARTIAL],
        error_count=counts[CaseStatus.ERROR],
        timeout_count=counts[CaseStatus.TIMEOUT],
        skipped_count=counts[CaseStatus.SKIPPED],
        expected_page_count=expected_pages,
        successful_page_count=successful_pages,
        cases=tuple(records),
        case_record_evidence=tuple(record_evidence),
        diagnostics=tuple(diagnostics),
    )
    run_record_path = resolved_run_dir / "run-record.json"
    _write_json_exclusive(
        run_record_path,
        run.model_dump(mode="json"),
    )
    if run.status == "success":
        report = build_semantic_report(
            run,
            run_record_path=run_record_path,
            context=context,
        )
        _write_json_exclusive(
            resolved_run_dir / "semantic-report.json",
            report.model_dump(mode="json"),
        )
        _write_text_exclusive(
            resolved_run_dir / "semantic-report.md",
            semantic_report_markdown(report),
        )
    return run


def _distribution(values: Sequence[float]) -> MetricDistribution:
    if not values:
        raise ValueError("cannot summarize an empty distribution")
    ordered = sorted(float(value) for value in values)

    def nearest_rank(percentile: float) -> float:
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]

    return MetricDistribution(
        count=len(ordered),
        minimum=ordered[0],
        p50=nearest_rank(0.50),
        p95=nearest_rank(0.95),
        maximum=ordered[-1],
        mean=sum(ordered) / len(ordered),
    )


def _performance_report(
    run: CorpusRunRecord,
    legacy: LegacyM0Run,
) -> PerformanceReport:
    if run.status != "success":
        raise ValueError("performance report requires a successful corpus run")
    outputs = [case.output for case in run.cases]
    if any(output is None for output in outputs):
        raise ValueError("successful corpus run is missing output evidence")
    typed_outputs = [output for output in outputs if output is not None]
    comparable = (
        performance_environment_fingerprint(run.environment)
        == legacy.performance_environment_fingerprint
    )
    latency = _distribution([case.case_latency_ms for case in run.cases])
    parse_latency = _distribution([case.parse_latency_ms for case in run.cases])
    cpu = _distribution([case.cpu_ms for case in run.cases])
    rss = _distribution([float(case.peak_rss_bytes) for case in run.cases])
    factor = 1 + PERFORMANCE_TOLERANCE_PERCENT / 100
    within = (
        all(
            (
                latency.p50 <= REFERENCE_PERFORMANCE["latency_p50_ms"] * factor,
                latency.p95 <= REFERENCE_PERFORMANCE["latency_p95_ms"] * factor,
                rss.p50 <= REFERENCE_PERFORMANCE["rss_p50_bytes"] * factor,
                rss.maximum <= REFERENCE_PERFORMANCE["rss_max_bytes"] * factor,
            )
        )
        if comparable
        else None
    )
    return PerformanceReport(
        case_count=len(run.cases),
        case_latency_ms=latency,
        parse_latency_ms=parse_latency,
        cpu_ms=cpu,
        peak_rss_bytes=rss,
        total_raw_json_bytes=sum(
            output.raw_json.size_bytes for output in typed_outputs
        ),
        total_markdown_bytes=sum(
            output.markdown.size_bytes for output in typed_outputs
        ),
        reference_latency_p50_ms=REFERENCE_PERFORMANCE["latency_p50_ms"],
        reference_latency_p95_ms=REFERENCE_PERFORMANCE["latency_p95_ms"],
        reference_rss_p50_bytes=REFERENCE_PERFORMANCE["rss_p50_bytes"],
        reference_rss_max_bytes=REFERENCE_PERFORMANCE["rss_max_bytes"],
        tolerance_percent=PERFORMANCE_TOLERANCE_PERCENT,
        environment_comparable=comparable,
        within_tolerance=within,
    )


def _claims_for_cases(
    batches: Sequence[ReviewBatch],
    selected_case_ids: Sequence[str],
) -> tuple[ReviewedClaimRecord, ...]:
    selected = set(selected_case_ids)
    claims = tuple(
        sorted(
            (
                claim
                for batch in batches
                for claim in batch.claims
                if claim.case_id in selected
            ),
            key=lambda claim: claim.claim_id,
        )
    )
    ids = [claim.claim_id for claim in claims]
    if len(ids) != len(set(ids)):
        raise ValueError("review batches contain duplicate claim IDs")
    return claims


def _build_claim_ledger(
    run: CorpusRunRecord,
    batches: Sequence[ReviewBatch],
) -> tuple[ReviewedClaimResult, ...]:
    output_hashes = {
        case.case_id: case.output.semantic_json.sha256
        for case in run.cases
        if case.output is not None
    }
    claims = _claims_for_cases(batches, run.selected_case_ids)
    results: list[ReviewedClaimResult] = []
    for claim in claims:
        unsupported = claim.review_status in _UNSUPPORTED_STATUSES
        if not claim.inclusion_mask.semantic_parity and not unsupported:
            raise ValueError(
                f"{claim.claim_id} has no semantic mask but is not unsupported"
            )
        if unsupported and (
            claim.inclusion_mask.literal_parity
            or claim.inclusion_mask.semantic_parity
        ):
            raise ValueError(
                f"{claim.claim_id} promotes unsupported expert content"
            )
        results.append(
            ReviewedClaimResult(
                claim_id=claim.claim_id,
                case_id=claim.case_id,
                claim_type=claim.claim_type,
                dimension=CLAIM_DIMENSION[claim.claim_type],
                review_status=claim.review_status,
                source_locators=claim.locators,
                literal_eligible=claim.inclusion_mask.literal_parity,
                semantic_eligible=claim.inclusion_mask.semantic_parity,
                treatment=(
                    ClaimTreatment.EXCLUDED_UNSUPPORTED
                    if unsupported
                    else ClaimTreatment.DIAGNOSTIC_ONLY
                ),
                diagnostic_reason=(
                    "Source review rejects or cannot independently verify this "
                    "expert claim; it is excluded from literal and semantic "
                    "denominators and retained as a safer-disagreement control."
                    if unsupported
                    else "This source-supported narrative claim has no "
                    "versioned executable candidate evaluator in Phase 0; it is "
                    "retained with exact provenance as diagnostic-only evidence."
                ),
                evaluator_id=None,
                output_artifact_sha256=output_hashes[claim.case_id],
            )
        )
    return tuple(results)


def _dimension_observation(
    dimension: MetricDimension,
    *,
    claims: Sequence[ReviewedClaimResult],
    comparisons: Sequence[OutputComparison],
    safety_claim_count: int,
    safety_control_count: int,
) -> str:
    if dimension is MetricDimension.MARKDOWN:
        stable = sum(item.markdown_stable for item in comparisons)
        return (
            f"Exact Markdown identities stable for {stable}/{len(comparisons)} "
            "selected cases; semantic claim scoring is not inferred from strings."
        )
    if dimension is MetricDimension.JSON:
        stable = sum(item.semantic_json_stable for item in comparisons)
        return (
            f"Duration-masked JSON identities stable for {stable}/"
            f"{len(comparisons)} selected cases."
        )
    if dimension is MetricDimension.HALLUCINATION:
        return (
            f"{safety_claim_count} unsupported reviewed claims and "
            f"{safety_control_count} negative/ambiguous controls remain explicit "
            "cross-cutting exclusions."
        )
    if dimension is MetricDimension.PERFORMANCE:
        return "Latency, CPU, RSS, and output sizes are reported without quality weighting."
    if dimension is MetricDimension.COST:
        return "Offline execution made zero hosted requests and incurred zero billed cost."
    if dimension is MetricDimension.DIAGNOSTICS:
        return (
            "Case errors, partial outputs, timeouts, skips, and parser warnings "
            "remain separate from content quality."
        )
    return (
        f"{len(claims)} reviewed claims retain exact masks and source locators; "
        "eligible narrative claims without an evaluator are diagnostic-only."
    )


def _build_dimensions(
    run: CorpusRunRecord,
    ledger: tuple[ReviewedClaimResult, ...],
    controls: BenchmarkControlRegistry,
) -> tuple[DimensionReport, ...]:
    selected = set(run.selected_case_ids)
    comparisons = tuple(
        case.reference_comparison
        for case in run.cases
        if case.reference_comparison is not None
    )
    unsupported_ids = tuple(
        claim.claim_id
        for claim in ledger
        if claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
    )
    negative_controls = tuple(
        assignment.assignment_id
        for control in controls.gap_controls
        for assignment in control.assignments
        if assignment.role is ControlRole.NEGATIVE_OR_AMBIGUOUS
        and assignment.evidence.case_id in selected
    )
    reports: list[DimensionReport] = []
    for dimension in DIMENSION_ORDER:
        claims = tuple(claim for claim in ledger if claim.dimension is dimension)
        gap_rows = tuple(
            row.row_id
            for row in controls.case_gap_rows
            if row.case_id in selected and GAP_DIMENSION[row.gap_id] is dimension
        )
        assignments = tuple(
            assignment.assignment_id
            for control in controls.gap_controls
            if GAP_DIMENSION[control.gap_id] is dimension
            for assignment in control.assignments
            if assignment.evidence.case_id in selected
        )
        scored = tuple(
            claim
            for claim in claims
            if claim.treatment
            in {
                ClaimTreatment.PASS,
                ClaimTreatment.PARTIAL,
                ClaimTreatment.FAIL,
            }
        )
        dimension_comparisons = (
            comparisons
            if dimension in {MetricDimension.MARKDOWN, MetricDimension.JSON}
            else ()
        )
        reports.append(
            DimensionReport(
                dimension=dimension,
                claim_ids=tuple(claim.claim_id for claim in claims),
                cross_cutting_claim_ids=(
                    unsupported_ids
                    if dimension is MetricDimension.HALLUCINATION
                    else ()
                ),
                eligible_literal_count=sum(
                    claim.literal_eligible for claim in claims
                ),
                eligible_semantic_count=sum(
                    claim.semantic_eligible for claim in claims
                ),
                scored_count=len(scored),
                pass_count=sum(
                    claim.treatment is ClaimTreatment.PASS for claim in claims
                ),
                partial_count=sum(
                    claim.treatment is ClaimTreatment.PARTIAL for claim in claims
                ),
                fail_count=sum(
                    claim.treatment is ClaimTreatment.FAIL for claim in claims
                ),
                diagnostic_only_count=sum(
                    claim.treatment is ClaimTreatment.DIAGNOSTIC_ONLY
                    for claim in claims
                ),
                excluded_count=sum(
                    claim.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
                    for claim in claims
                ),
                gap_row_ids=gap_rows,
                control_assignment_ids=assignments,
                safety_control_assignment_ids=(
                    negative_controls
                    if dimension is MetricDimension.HALLUCINATION
                    else ()
                ),
                output_comparisons=dimension_comparisons,
                observation=_dimension_observation(
                    dimension,
                    claims=claims,
                    comparisons=comparisons,
                    safety_claim_count=len(unsupported_ids),
                    safety_control_count=len(negative_controls),
                ),
            )
        )
    return tuple(reports)


def _quality_signature(
    ledger: Sequence[ReviewedClaimResult],
    dimensions: Sequence[DimensionReport],
) -> str:
    payload = {
        "claim_ledger": [
            {
                "claim_id": claim.claim_id,
                "case_id": claim.case_id,
                "claim_type": claim.claim_type.value,
                "dimension": claim.dimension.value,
                "review_status": claim.review_status.value,
                "literal_eligible": claim.literal_eligible,
                "semantic_eligible": claim.semantic_eligible,
                "treatment": claim.treatment.value,
                "source_regions": [
                    {
                        "physical_page": locator.physical_page,
                        "printed_page": locator.printed_page,
                        "region_id": locator.region_id,
                    }
                    for locator in claim.source_locators
                ],
            }
            for claim in ledger
        ],
        "dimensions": [
            {
                "dimension": report.dimension.value,
                "claim_ids": list(report.claim_ids),
                "cross_cutting_claim_ids": list(report.cross_cutting_claim_ids),
                "eligible_literal_count": report.eligible_literal_count,
                "eligible_semantic_count": report.eligible_semantic_count,
                "scored_count": report.scored_count,
                "diagnostic_only_count": report.diagnostic_only_count,
                "excluded_count": report.excluded_count,
                "gap_row_ids": list(report.gap_row_ids),
                "control_assignment_ids": list(report.control_assignment_ids),
                "safety_control_assignment_ids": list(
                    report.safety_control_assignment_ids
                ),
            }
            for report in dimensions
        ],
    }
    return sha256_bytes(canonical_payload_bytes(payload))


def _stable_output_signature(
    comparisons: Sequence[OutputComparison],
) -> str:
    payload = [
        {
            "case_id": item.case_id,
            "current_semantic_json_sha256": item.current_semantic_json_sha256,
            "reference_semantic_json_sha256": (
                item.reference_semantic_json_sha256
            ),
            "semantic_json_stable": item.semantic_json_stable,
            "current_markdown_sha256": item.current_markdown_sha256,
            "reference_markdown_sha256": item.reference_markdown_sha256,
            "markdown_stable": item.markdown_stable,
        }
        for item in sorted(comparisons, key=lambda value: value.case_id)
    ]
    return sha256_bytes(canonical_payload_bytes(payload))


def build_semantic_report(
    run: CorpusRunRecord,
    *,
    run_record_path: Path,
    context: BenchmarkContext,
) -> CorpusSemanticReport:
    if run.status != "success":
        raise ValueError("semantic report requires a fully successful source run")
    if run.frozen_inputs != context.frozen_inputs:
        raise ValueError("run frozen-input identity differs from current context")
    if run.environment_sha256 != context.environment_sha256:
        raise ValueError("run environment identity differs from current context")
    if run.settings_sha256 != context.settings_sha256:
        raise ValueError("run settings identity differs from current context")
    ledger = _build_claim_ledger(run, context.review_batches)
    dimensions = _build_dimensions(run, ledger, context.control_registry)
    unique_comparisons = tuple(
        case.reference_comparison
        for case in run.cases
        if case.reference_comparison is not None
    )
    if len(unique_comparisons) != len(run.cases):
        raise ValueError("every successful case requires a reference comparison")
    run_bytes = run_record_path.read_bytes()
    report = CorpusSemanticReport(
        schema_version="1.0",
        report_kind=REPORT_KIND,
        runner_version=RUNNER_VERSION,
        run_id=run.run_id,
        run_record=ArtifactEvidence(
            role="corpus_run_record",
            path=_workspace_path(run_record_path, context.workspace_root),
            sha256=sha256_bytes(run_bytes),
            size_bytes=len(run_bytes),
        ),
        run_semantic_sha256=sha256_bytes(canonical_model_bytes(run)),
        frozen_inputs=context.frozen_inputs,
        selected_case_ids=run.selected_case_ids,
        case_count=len(run.cases),
        page_count=run.expected_page_count,
        reviewed_claim_count=len(ledger),
        literal_eligible_count=sum(item.literal_eligible for item in ledger),
        semantic_eligible_count=sum(item.semantic_eligible for item in ledger),
        excluded_unsupported_count=sum(
            item.treatment is ClaimTreatment.EXCLUDED_UNSUPPORTED
            for item in ledger
        ),
        scored_claim_count=sum(
            item.treatment
            in {
                ClaimTreatment.PASS,
                ClaimTreatment.PARTIAL,
                ClaimTreatment.FAIL,
            }
            for item in ledger
        ),
        diagnostic_only_count=sum(
            item.treatment is ClaimTreatment.DIAGNOSTIC_ONLY for item in ledger
        ),
        claim_ledger=ledger,
        dimensions=dimensions,
        performance=_performance_report(run, context.legacy),
        cost=OfflineCostReport(
            hosted_requests=0,
            prompt_tokens=0,
            completion_tokens=0,
            billed_usd=0.0,
            method="fixed offline execution policy",
        ),
        quality_signature_sha256=_quality_signature(ledger, dimensions),
        stable_output_signature_sha256=_stable_output_signature(
            unique_comparisons
        ),
        all_outputs_stable=all(
            item.semantic_json_stable and item.markdown_stable
            for item in unique_comparisons
        ),
        diagnostics=(
            DiagnosticRecord(
                code="eligible-claims-diagnostic-only",
                stage="semantic-report",
                message=(
                    "Reviewed narrative claims have no versioned executable "
                    "candidate evaluators in Phase 0 and are not counted as passes."
                ),
                remediation=(
                    "Future stories may add claim-specific evaluators without "
                    "changing these frozen masks or source locators."
                ),
            ),
            DiagnosticRecord(
                code="legacy-token-metrics-diagnostic-only",
                stage="legacy-comparison",
                message=(
                    "Frozen token/string similarity remains a drift diagnostic "
                    "and is excluded from semantic pass/fail counts."
                ),
                remediation=(
                    "Use source-grounded versioned evaluators for any future "
                    "automatic semantic scoring."
                ),
            ),
        ),
    )
    return report


def semantic_report_markdown(report: CorpusSemanticReport) -> str:
    performance = report.performance
    lines = [
        "# P00-US10 Immutable Corpus Semantic Report",
        "",
        f"- Run: `{report.run_id}`",
        f"- Cases/pages: {report.case_count}/{report.page_count}",
        (
            "- Reviewed masks: "
            f"{report.reviewed_claim_count} claims; "
            f"{report.literal_eligible_count} literal; "
            f"{report.semantic_eligible_count} semantic; "
            f"{report.excluded_unsupported_count} unsupported exclusions"
        ),
        (
            "- Automated semantic scoring: "
            f"{report.scored_claim_count}; diagnostic-only eligible claims: "
            f"{report.diagnostic_only_count}"
        ),
        f"- Stable JSON/Markdown outputs: `{report.all_outputs_stable}`",
        "- Hosted/model cost: 0 requests, 0 tokens, USD 0.00",
        "",
        "No single aggregate quality score is produced.",
        "",
        "## Dimensions",
        "",
        "| Dimension | Claims | Semantic eligible | Scored | Diagnostic | Excluded |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for dimension in report.dimensions:
        lines.append(
            f"| {dimension.dimension.value} | {len(dimension.claim_ids)} | "
            f"{dimension.eligible_semantic_count} | {dimension.scored_count} | "
            f"{dimension.diagnostic_only_count} | {dimension.excluded_count} |"
        )
    lines.extend(
        [
            "",
            "## Performance",
            "",
            (
                "- Case latency p50/p95: "
                f"{performance.case_latency_ms.p50:.3f}/"
                f"{performance.case_latency_ms.p95:.3f} ms"
            ),
            (
                "- Peak RSS p50/max: "
                f"{performance.peak_rss_bytes.p50 / (1024 * 1024):.2f}/"
                f"{performance.peak_rss_bytes.maximum / (1024 * 1024):.2f} MiB"
            ),
            (
                "- Frozen-environment comparable / within 25% tolerance: "
                f"`{performance.environment_comparable}` / "
                f"`{performance.within_tolerance}`"
            ),
            "",
            "## Semantic boundary",
            "",
            (
                "Eligible narrative review rows remain diagnostic-only because "
                "they do not yet contain executable expected-value predicates. "
                "Incorrect, inferred, and unverifiable expert claims remain "
                "explicitly excluded and cannot enter a scored denominator."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def load_corpus_run(path: str | Path) -> CorpusRunRecord:
    return CorpusRunRecord.model_validate_json(Path(path).read_bytes())


def load_semantic_report(path: str | Path) -> CorpusSemanticReport:
    return CorpusSemanticReport.model_validate_json(Path(path).read_bytes())


def verify_corpus_run(
    run_record_path: str | Path,
    *,
    workspace_root: str | Path = WORKSPACE,
) -> tuple[CorpusRunRecord, CorpusSemanticReport]:
    """Read-only verification of a finalized successful immutable run."""

    root = Path(workspace_root).resolve()
    record_path = Path(run_record_path).resolve()
    run = load_corpus_run(record_path)
    context = load_benchmark_context(
        root,
        historical_environment=run.environment,
        historical_settings=run.settings,
    )
    if run.status != "success":
        raise ValueError("completed-with-errors runs cannot be semantic baselines")
    if run.frozen_inputs != context.frozen_inputs:
        raise ValueError("run frozen-input identities no longer validate")
    # The environment embedded in an immutable run is historical evidence.
    # Production and benchmark-runner source hashes are expected to advance in
    # later authorized phases; requiring them to equal the live checkout would
    # make all behavior work after Phase 0 unverifiable. Rebuild the retained
    # report against its recorded environment while independently validating
    # current frozen inputs, settings, artifact hashes, schemas, and report
    # determinism below.
    historical_context = context
    expected_record_path = (
        resolve_portable_path(root, run.run_dir) / "run-record.json"
    )
    if record_path != expected_record_path:
        raise ValueError("run record path does not match its immutable run directory")
    evidence_by_case = {
        evidence.case_id: evidence for evidence in run.case_record_evidence
    }
    for case in run.cases:
        verify_case_execution(case, root)
        case_root = resolve_portable_path(root, run.run_dir) / case.case_id
        evidence = evidence_by_case[case.case_id]
        _verify_artifact_file(evidence.worker_record, root)
        _verify_artifact_file(evidence.coordinator_record, root)
        coordinator_case = load_case_execution(
            resolve_portable_path(root, evidence.coordinator_record.path)
        )
        if canonical_model_bytes(coordinator_case) != canonical_model_bytes(case):
            raise ValueError(
                f"{case.case_id} coordinator record differs from the corpus run"
            )
        worker_case = load_case_execution(
            resolve_portable_path(root, evidence.worker_record.path)
        )
        comparable_top = CaseExecution.model_validate(
            {
                **case.model_dump(mode="json"),
                "case_latency_ms": worker_case.case_latency_ms,
            }
        )
        if canonical_model_bytes(worker_case) != canonical_model_bytes(
            comparable_top
        ):
            raise ValueError(
                f"{case.case_id} worker record differs beyond coordinator latency"
            )
        for name in ("worker-stdout.log", "worker-stderr.log"):
            if not (case_root / name).is_file():
                raise ValueError(f"{case.case_id} retained artifact is missing: {name}")

    run_root = resolve_portable_path(root, run.run_dir)
    report_path = run_root / "semantic-report.json"
    markdown_path = run_root / "semantic-report.md"
    report = load_semantic_report(report_path)
    if report.run_id != run.run_id or report.frozen_inputs != run.frozen_inputs:
        raise ValueError("semantic report identity differs from its source run")
    _verify_artifact_file(report.run_record, root)
    if report.run_semantic_sha256 != sha256_bytes(canonical_model_bytes(run)):
        raise ValueError("semantic report run binding changed")
    rebuilt = build_semantic_report(
        run,
        run_record_path=record_path,
        context=historical_context,
    )
    if canonical_model_bytes(report) != canonical_model_bytes(rebuilt):
        raise ValueError("semantic report does not deterministically rebuild")
    if not markdown_path.is_file():
        raise ValueError("semantic report Markdown is missing")
    expected_markdown = semantic_report_markdown(report).encode("utf-8")
    if markdown_path.read_bytes() != expected_markdown:
        raise ValueError("semantic report Markdown changed")
    return run, report


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Immutable offline LlamaParse-15 benchmark runner",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker")
    worker.add_argument("--workspace", required=True, type=Path)
    worker.add_argument("--corpus-registry", required=True)
    worker.add_argument("--case-id", required=True)
    worker.add_argument("--output-dir", required=True, type=Path)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--order", required=True, type=int)
    worker.add_argument("--settings-sha256", required=True)
    worker.add_argument("--environment-sha256", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--workspace", default=WORKSPACE, type=Path)
    capture.add_argument("--corpus-registry", default=CORPUS_REGISTRY_PATH)
    capture.add_argument(
        "--control-registry",
        default=CONTROL_REGISTRY_EVIDENCE_PATH,
    )
    capture.add_argument("--run-dir", required=True, type=Path)
    capture.add_argument("--run-id", required=True)
    capture.add_argument("--cases", nargs="*")
    capture.add_argument("--timeout-seconds", type=float, default=420.0)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--workspace", default=WORKSPACE, type=Path)
    verify.add_argument("--run-record", required=True, type=Path)
    return parser


def main() -> None:
    args = _cli().parse_args()
    if args.command == "worker":
        raise SystemExit(
            run_case_worker(
                workspace_root=args.workspace.resolve(),
                corpus_registry_path=args.corpus_registry,
                case_id=args.case_id,
                output_dir=args.output_dir.resolve(),
                run_id=args.run_id,
                order=args.order,
                expected_settings_sha256=args.settings_sha256,
                expected_environment_sha256=args.environment_sha256,
            )
        )
    if args.command == "capture":
        run = capture_corpus(
            run_dir=args.run_dir,
            run_id=args.run_id,
            selected_case_ids=args.cases,
            workspace_root=args.workspace,
            corpus_registry_path=args.corpus_registry,
            control_registry_path=args.control_registry,
            timeout_seconds=args.timeout_seconds,
        )
        raise SystemExit(0 if run.status == "success" else 1)
    verify_corpus_run(
        args.run_record,
        workspace_root=args.workspace,
    )


if __name__ == "__main__":
    main()
