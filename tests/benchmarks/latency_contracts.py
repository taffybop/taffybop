"""Strict evidence contracts for the latency-improvement campaign.

These models are test/reporting infrastructure.  Production code must not
import them.  They deliberately distinguish authoritative end-to-end latency
from diagnostic stage spans and reject incomplete schedules, cache hits,
inexact provider inputs, and process-resource summaries that cannot be
recomputed from their retained samples.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from itertools import pairwise
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"
CAMPAIGN_SCHEMA_ID = "phase-latency-campaign-v1"
STAGE_TRACE_SCHEMA_ID = "phase-latency-stage-trace-v1"
PROCESS_TREE_SCHEMA_ID = "phase-latency-process-tree-metrics-v1"
MINIMUM_PAIRED_SAMPLES = 5
MAXIMUM_CAMPAIGN_ATTEMPTS = 1_000
MAXIMUM_STAGE_SPANS = 1_024
MAXIMUM_PROCESS_SNAPSHOTS = 10_000
MAXIMUM_PROCESSES_PER_SNAPSHOT = 128
PHASE_EXIT_CASE_COUNT = 15
PHASE_EXIT_PAGE_COUNT = 30
PHASE_EXIT_PROVIDER_SAMPLE_COUNT = 5
PHASE_EXIT_AGENTIC_CREDIT_LIMIT = 1_500

PHASE_EXIT_CASE_PAGE_COUNTS = {
    "catastrophe-recap": 1,
    "clean-energy": 1,
    "clinical-study": 4,
    "component-datasheet": 3,
    "egov-survey": 1,
    "esg-metrics": 1,
    "finance-10k": 3,
    "health-report": 1,
    "insurance-acord": 1,
    "manufacturing-report": 3,
    "ny-timetable": 3,
    "postal-10k": 3,
    "purchase-agreement": 1,
    "settlement-agreement": 1,
    "uber-earnings": 3,
}
PHASE_EXIT_CASE_IDS = tuple(PHASE_EXIT_CASE_PAGE_COUNTS)
PHASE_EXIT_CORPUS_REGISTRY = {
    "path": "tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json",
    "sha256": "f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb",
    "size_bytes": 20_744,
}
PHASE_EXIT_ORACLE_ARTIFACT = {
    "path": "tests/fixtures/phase_03/running_regions/oracle.py",
    "sha256": "5e70b5df58284f544b43a6189055044c80c2a9a6404f143758be550e3879b563",
    "size_bytes": 160_147,
}
PHASE_EXIT_SOURCE_REGISTRY_SHA256 = (
    "0fe1648db893170c6584246e553afbc2939f70ed72d3ea15ec1a1d4fe6d05b5a"
)


_STABLE_ID = re.compile(r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_LLAMA_JOB_ID = re.compile(r"^pjb-[a-z0-9]+$")
_LLAMA_DISPLAY = re.compile(r"^(0|[1-9][0-9]*)(?:\.([0-9]{1,3}))?([sm])$")


StableId = Annotated[str, Field(min_length=1, max_length=128)]
Sha256 = Annotated[str, Field(pattern=_SHA256.pattern)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class ContractModel(BaseModel):
    """Closed, immutable and finite evidence model."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _require_stable_id(value: str, *, label: str) -> str:
    if not _STABLE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a stable lowercase identifier")
    return value


def _require_portable_path(value: str) -> str:
    if (
        value != value.strip()
        or "\\" in value
        or any(ord(character) < 0x20 or ord(character) > 0x7E for character in value)
    ):
        raise ValueError("source path must be printable canonical ASCII POSIX text")
    path = PurePosixPath(value)
    parts = value.split("/")
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].startswith("~")
        or ":" in parts[0]
    ):
        raise ValueError("source path must be canonical and workspace-relative")
    return value


def _require_utc_datetime(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be UTC")
    return value.astimezone(UTC)


class SystemName(str, Enum):
    CANDIDATE = "candidate"
    LLAMAPARSE = "llamaparse"


class AttemptStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class StageStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class StageName(str, Enum):
    """Closed v1 stage vocabulary; stages are diagnostic, never comparators."""

    REQUEST_TOTAL = "request_total"
    QUEUE_WAIT = "queue_wait"
    PIPELINE_IMPORT_RESOLUTION = "harness.pipeline_import_resolution"
    API_INPUT_VALIDATION = "api.input_validation"
    UPLOAD_READ = "api.upload_read"
    API_PARSE_DISPATCH = "api.parse_dispatch"
    JSON_ENCODING = "api.jsonable_encoder"
    RESULT_VALIDATION = "api.result_validation"
    API_MODEL_DUMP = "api.model_dump"
    MARKDOWN_SERIALIZATION = "api.markdown_serialization"
    RESPONSE_MATERIALIZATION = "api.response_build"
    LOAD_DOCUMENT = "pipeline.input_load"
    PIPELINE_PARSE_LOADED = "pipeline.parse_loaded"
    FONT_AUDIT = "pipeline.font_audit"
    FONT_RECOVERY = "pipeline.font_recovery"
    NATIVE_PDF = "pipeline.native_page_extraction"
    SELECTIVE_SPAN_OCR = "pipeline.selective_span_ocr"
    DOCLING_CONVERSION = "pipeline.docling_conversion"
    DOCLING_CONVERTER_ACQUISITION = "pipeline.docling_converter_acquisition"
    DOCLING_LOCK_WAIT = "pipeline.docling_lock_wait"
    DOCLING_PIPELINE_INITIALIZATION = "pipeline.docling_pipeline_initialization"
    DOCLING_CONVERT = "pipeline.docling_convert"
    TEXT_RUN_EVIDENCE = "pipeline.text_run_evidence"
    FORM_EVIDENCE = "pipeline.form_evidence"
    OUTLINE_EVIDENCE = "pipeline.outline_evidence"
    SOURCE_TEXT_EVIDENCE = "pipeline.source_text_evidence"
    IMAGE_OCR = "pipeline.embedded_image_ocr"
    RENDER_REQUEST_PLANNING = "pipeline.render_request_planning"
    RENDERED_PDF_OCR = "pipeline.rendered_region_ocr"
    SOURCE_NOTE_AUGMENTATION = "pipeline.source_note_augmentation"
    RASTER_OCR = "pipeline.raster_ocr"
    VECTOR_TABLES = "pipeline.vector_table_extraction"
    TABLE_REPAIR = "pipeline.table_repair_extraction"
    SHARED_ANALYSIS = "pipeline.shared_page_analysis"
    COMPATIBILITY_PROJECTION = "pipeline.compatibility_projection"
    TERMINAL_ALIGNMENT = "pipeline.terminal_source_alignment"
    TABLE_AUTHORITY = "pipeline.terminal_table_authority"
    PIPELINE_RESULT_VALIDATION = "pipeline.parse_result_validation"
    HARNESS_RESPONSE_VALIDATION = "harness.post_response_validation"


class SourceBinding(str, Enum):
    WORKSPACE_BYTES = "workspace_bytes"
    EXACT_BYTE_UPLOAD = "exact_byte_upload"


class OutputFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"


class ProcessRole(str, Enum):
    CANDIDATE_WORKER = "candidate_worker"
    RESOURCE_TRACKER = "resource_tracker"
    TESSERACT = "tesseract"
    DOCLING_CHILD = "docling_child"
    OTHER_PARSER_CHILD = "other_parser_child"


class CampaignScope(str, Enum):
    SYNTHETIC_CONTROL = "synthetic_control"
    PHASE_EXIT_ALL_15 = "phase_exit_all_15"


class WorkerLifecycle(str, Enum):
    FRESH_PROCESS_REQUEST_COLD = "fresh_process_request_cold_after_app_startup"
    FRESH_PROCESS_REQUEST_PREWARMED = (
        "fresh_process_request_prewarmed_after_app_startup"
    )
    REUSED_PROCESS_WARM = "reused_process_warm"
    HOSTED_EXACT_UPLOAD = "hosted_exact_upload"


class FailureType(str, Enum):
    """Closed, content-free failure classification retained by the harness."""

    REQUEST_EXCEPTION = "RequestException"
    HTTP_STATUS_ERROR = "HTTPStatusError"
    RESPONSE_VALIDATION_ERROR = "ResponseValidationError"
    TELEMETRY_ERROR = "TelemetryError"
    EVIDENCE_ERROR = "EvidenceError"
    WORKER_CRASH = "WorkerCrash"
    WORKER_SIGNAL = "WorkerSignal"
    WORKER_TIMEOUT = "WorkerTimeout"
    WORKER_CANCELLED = "WorkerCancelled"
    WORKER_PROTOCOL_ERROR = "WorkerProtocolError"
    NETWORK_EGRESS_ATTEMPT = "NetworkEgressAttempt"


class SourceIdentity(ContractModel):
    case_id: StableId
    path: Annotated[str, Field(min_length=1, max_length=512)]
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    sha256: Sha256
    size_bytes: PositiveInt
    page_count: PositiveInt

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _require_stable_id(value, label="case_id")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _require_portable_path(value)

    @model_validator(mode="after")
    def bind_filename_to_path(self) -> SourceIdentity:
        if PurePosixPath(self.path).name != self.filename:
            raise ValueError("source filename must be the final path component")
        return self


def _canonical_identity_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def configuration_identity_sha256(value: dict[str, Any]) -> str:
    """Derive the closed system-configuration identity from raw/model data."""

    required = {
        "api_version",
        "bounded_concurrency",
        "cache_disabled",
        "cache_scope",
        "cost_optimizer",
        "credits_per_page",
        "model_artifacts_sha256",
        "internal_reuse_state",
        "prewarm_completed_before_request",
        "required_stage_inventory",
        "stage_cardinality_policies",
        "runtime_sha256",
        "service",
        "settings_sha256",
        "system",
        "tier",
        "total_latency_metric",
        "worker_lifecycle",
        "application_startup_completed_before_request",
        "pipeline_import_state_at_request_start",
        "engine_cache_state_at_request_start",
        "filesystem_cache_state",
        "content_result_cache_proof_sha256",
    }
    if not required.issubset(value):
        raise ValueError("configuration hash input is incomplete")
    payload = {field: value[field] for field in required}
    payload["required_stage_inventory"] = sorted(
        stage.value if isinstance(stage, StageName) else str(stage)
        for stage in payload["required_stage_inventory"]
    )
    payload["stage_cardinality_policies"] = [
        item.model_dump(mode="json") if isinstance(item, BaseModel) else item
        for item in payload["stage_cardinality_policies"]
    ]
    for field in ("system", "worker_lifecycle"):
        candidate = payload[field]
        payload[field] = candidate.value if isinstance(candidate, Enum) else candidate
    return _canonical_identity_hash(payload)


class StageCardinalityPolicy(ContractModel):
    """Resolved per-request invocation policy for one diagnostic stage."""

    policy_id: StableId
    stage: StageName
    minimum_calls: NonNegativeInt
    maximum_calls: Annotated[int, Field(strict=True, ge=0, le=512)]
    condition_id: StableId
    exclusive_group: StableId | None = None
    allow_degraded_on_success: StrictBool
    target_ids: Annotated[tuple[StableId, ...], Field(min_length=1, max_length=16)]

    @field_validator("policy_id", "condition_id", "exclusive_group")
    @classmethod
    def validate_policy_ids(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_stable_id(value, label=info.field_name)

    @field_validator("target_ids")
    @classmethod
    def validate_targets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _require_stable_id(item, label="target_id")
        if value != tuple(sorted(set(value))):
            raise ValueError("cardinality target IDs must be unique and sorted")
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> StageCardinalityPolicy:
        if self.minimum_calls > self.maximum_calls:
            raise ValueError("stage minimum calls cannot exceed maximum calls")
        if self.stage is StageName.REQUEST_TOTAL:
            raise ValueError("request root cannot use a child policy")
        return self


class ConfigurationIdentity(ContractModel):
    system: SystemName
    system_configuration_sha256: Sha256
    semantic_request_sha256: Sha256
    output_format: OutputFormat
    cache_disabled: StrictBool
    service: Literal["document-parse-api", "LlamaCloud Parse"]
    api_version: Literal["v1", "v2"]
    tier: Literal["Agentic"] | None = None
    cost_optimizer: StrictBool | None = None
    credits_per_page: Annotated[int, Field(strict=True, gt=0)] | None = None
    total_latency_metric: Literal[
        "asgi_complete_response_bytes",
        "provider_ui_total_latency",
    ]
    cache_scope: Literal["content_and_result_cache"]
    worker_lifecycle: WorkerLifecycle
    prewarm_completed_before_request: StrictBool
    bounded_concurrency: PositiveInt
    settings_sha256: Sha256 | None = None
    runtime_sha256: Sha256 | None = None
    model_artifacts_sha256: Sha256 | None = None
    required_stage_inventory: tuple[StageName, ...]
    stage_cardinality_policies: tuple[StageCardinalityPolicy, ...]
    internal_reuse_state: Literal[
        "process_engine_cache_empty_at_request_start",
        "prewarmed_before_request",
        "warm_reused_process",
        "provider_cache_disabled",
    ]
    application_startup_completed_before_request: StrictBool
    pipeline_import_state_at_request_start: Literal[
        "not_loaded",
        "loaded_by_controlled_prewarm",
        "provider_not_applicable",
    ]
    engine_cache_state_at_request_start: Literal[
        "module_not_loaded_process_cache_empty",
        "prewarmed_process_cache",
        "provider_cache_disabled",
    ]
    filesystem_cache_state: Literal[
        "uncontrolled_shared_host_cache",
        "provider_not_observable",
    ]
    content_result_cache_proof_sha256: Sha256 | None

    def derived_system_configuration_sha256(self) -> str:
        """Hash every execution-affecting setting except request semantics."""

        return configuration_identity_sha256(self.model_dump(mode="python"))

    @model_validator(mode="after")
    def require_exact_system_configuration(self) -> ConfigurationIdentity:
        if self.cache_disabled is not True:
            raise ValueError("content/result cache must be disabled")
        inventory = tuple(self.required_stage_inventory)
        if inventory != tuple(sorted(set(inventory), key=lambda item: item.value)):
            raise ValueError("required stage inventory must be unique and sorted")
        if any(stage is StageName.REQUEST_TOTAL for stage in inventory):
            raise ValueError("required stage inventory must contain production stages")
        policies = tuple(self.stage_cardinality_policies)
        if policies != tuple(sorted(policies, key=lambda item: item.policy_id)):
            raise ValueError("stage cardinality policies must be canonical")
        if len({item.policy_id for item in policies}) != len(policies):
            raise ValueError("stage cardinality policy IDs must be unique")
        if len({item.stage for item in policies}) != len(policies):
            raise ValueError("one stage must have exactly one cardinality policy")
        required_from_policies = tuple(
            sorted(
                (item.stage for item in policies if item.minimum_calls > 0),
                key=lambda item: item.value,
            )
        )
        if inventory != required_from_policies:
            raise ValueError("required stage inventory must derive from cardinalities")
        if self.system is SystemName.CANDIDATE:
            if (
                self.service != "document-parse-api"
                or self.api_version != "v1"
                or self.tier is not None
                or self.cost_optimizer is not None
                or self.credits_per_page is not None
                or self.total_latency_metric != "asgi_complete_response_bytes"
                or self.worker_lifecycle is WorkerLifecycle.HOSTED_EXACT_UPLOAD
                or self.settings_sha256 is None
                or self.runtime_sha256 is None
                or self.model_artifacts_sha256 is None
                or not policies
                or self.application_startup_completed_before_request is not True
                or self.pipeline_import_state_at_request_start
                not in {"not_loaded", "loaded_by_controlled_prewarm"}
                or self.engine_cache_state_at_request_start
                not in {
                    "module_not_loaded_process_cache_empty",
                    "prewarmed_process_cache",
                }
                or self.filesystem_cache_state != "uncontrolled_shared_host_cache"
                or self.content_result_cache_proof_sha256 is None
                or self.bounded_concurrency > 4
            ):
                raise ValueError("candidate configuration identity is inconsistent")
        elif (
            self.service != "LlamaCloud Parse"
            or self.api_version != "v2"
            or self.tier != "Agentic"
            or self.cost_optimizer is not False
            or self.credits_per_page != 10
            or self.total_latency_metric != "provider_ui_total_latency"
            or self.worker_lifecycle is not WorkerLifecycle.HOSTED_EXACT_UPLOAD
            or self.prewarm_completed_before_request is not False
            or self.bounded_concurrency != 1
            or self.settings_sha256 is not None
            or self.runtime_sha256 is not None
            or self.model_artifacts_sha256 is not None
            or inventory
            or policies
            or self.internal_reuse_state != "provider_cache_disabled"
            or self.application_startup_completed_before_request is not False
            or self.pipeline_import_state_at_request_start != "provider_not_applicable"
            or self.engine_cache_state_at_request_start != "provider_cache_disabled"
            or self.filesystem_cache_state != "provider_not_observable"
            or self.content_result_cache_proof_sha256 is not None
        ):
            raise ValueError("LlamaParse configuration must use the canonical profile")
        if self.worker_lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD:
            if (
                self.prewarm_completed_before_request is not False
                or self.internal_reuse_state
                != "process_engine_cache_empty_at_request_start"
                or self.pipeline_import_state_at_request_start != "not_loaded"
                or self.engine_cache_state_at_request_start
                != "module_not_loaded_process_cache_empty"
            ):
                raise ValueError("cold worker cannot claim completed prewarm")
        elif self.worker_lifecycle is WorkerLifecycle.FRESH_PROCESS_REQUEST_PREWARMED:
            if (
                self.prewarm_completed_before_request is not True
                or self.internal_reuse_state != "prewarmed_before_request"
                or self.pipeline_import_state_at_request_start
                != "loaded_by_controlled_prewarm"
                or self.engine_cache_state_at_request_start != "prewarmed_process_cache"
            ):
                raise ValueError("prewarmed worker must retain completed prewarm")
        elif (
            self.worker_lifecycle is WorkerLifecycle.REUSED_PROCESS_WARM
            and self.internal_reuse_state != "warm_reused_process"
        ):
            raise ValueError("warm worker must retain internal reuse state")
        if self.system_configuration_sha256 != (
            self.derived_system_configuration_sha256()
        ):
            raise ValueError("system configuration hash must be derived")
        return self


class ArtifactIdentity(ContractModel):
    """Content identity for one retained, reviewable evidence artifact."""

    path: Annotated[str, Field(min_length=1, max_length=512)]
    sha256: Sha256
    size_bytes: PositiveInt

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _require_portable_path(value)


class InstalledDistributionIdentity(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    version: Annotated[str, Field(min_length=1, max_length=64)] | None
    verified_file_count: NonNegativeInt
    verified_aggregate_bytes: NonNegativeInt
    installed_files_sha256: Sha256
    identity_basis: Literal[
        "all-record-hashed-installed-files-with-declared-digests-v1",
        "distribution-absent-from-locked-runtime-v1",
    ]

    @field_validator("name")
    @classmethod
    def validate_distribution_name(cls, value: str) -> str:
        normalized = value.casefold().replace("_", "-")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
            raise ValueError("distribution name is not canonical")
        return normalized

    @model_validator(mode="after")
    def validate_distribution_disposition(self) -> InstalledDistributionIdentity:
        absent = self.identity_basis == "distribution-absent-from-locked-runtime-v1"
        if absent != (self.version is None):
            raise ValueError("distribution presence/version disposition differs")
        if absent and (
            self.verified_file_count != 0
            or self.verified_aggregate_bytes != 0
            or self.installed_files_sha256 != hashlib.sha256(b"[]").hexdigest()
        ):
            raise ValueError("absent distribution cannot claim installed files")
        if not absent and (
            self.verified_file_count <= 0 or self.verified_aggregate_bytes <= 0
        ):
            raise ValueError("installed distribution requires verified files")
        return self


class RuntimeBinaryIdentity(ContractModel):
    role: Literal["python", "tesseract", "eng-traineddata"]
    resolved_path_sha256: Sha256
    size_bytes: PositiveInt
    content_sha256: Sha256
    version: Annotated[str, Field(min_length=1, max_length=256)] | None = None


class EnvironmentIdentityEvidence(ContractModel):
    schema_id: Literal["phase-latency-environment-identity-v1"]
    python_implementation: Literal["CPython"]
    python_version: Annotated[str, Field(min_length=3, max_length=32)]
    python_cache_tag: Annotated[str, Field(min_length=3, max_length=64)]
    system: Annotated[str, Field(min_length=1, max_length=64)]
    release: Annotated[str, Field(min_length=1, max_length=128)]
    machine: Annotated[str, Field(min_length=1, max_length=64)]
    cpu_model_sha256: Sha256
    logical_cpu_count: PositiveInt
    physical_cpu_count: PositiveInt
    total_memory_bytes: PositiveInt
    power_thermal_state: Literal["unavailable_uncontrolled"]
    sanitized_worker_environment_sha256: Sha256
    distributions: Annotated[
        tuple[InstalledDistributionIdentity, ...], Field(min_length=15, max_length=32)
    ]
    binaries: Annotated[
        tuple[RuntimeBinaryIdentity, ...], Field(min_length=3, max_length=3)
    ]
    p00_reference_docling_core_version: Literal["2.87.1"]
    observed_docling_core_version: Literal["2.88.0"]
    p00_comparable: Literal[False]
    noncomparability_reason: Literal["docling-core-2.88.0-vs-p00-2.87.1"]
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def validate_environment_identity(self) -> EnvironmentIdentityEvidence:
        names = tuple(item.name for item in self.distributions)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise ValueError("environment distributions must be unique and canonical")
        versions = {item.name: item.version for item in self.distributions}
        if versions.get("docling-core") != self.observed_docling_core_version:
            raise ValueError("observed Docling Core version differs")
        if tuple(item.role for item in self.binaries) != (
            "python",
            "tesseract",
            "eng-traineddata",
        ):
            raise ValueError("runtime binary inventory differs")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != _canonical_identity_hash(payload):
            raise ValueError("environment manifest digest must be recomputed")
        return self


class OutputIdentity(ContractModel):
    sha256: Sha256
    semantic_sha256: Sha256
    size_bytes: PositiveInt
    media_type: Literal[
        "application/json",
        "text/markdown",
        "application/octet-stream",
    ]
    validation: Literal["ParseResult", "Markdown", "provider_retained_artifact"]
    semantic_exclusions: tuple[Literal["/processing/duration_ms"], ...]
    retained_artifact: ArtifactIdentity | None = None

    @model_validator(mode="after")
    def bind_retained_output(self) -> OutputIdentity:
        if self.validation == "provider_retained_artifact":
            if self.retained_artifact is None:
                raise ValueError("provider output must retain a reviewable artifact")
            if (
                self.retained_artifact.sha256 != self.sha256
                or self.retained_artifact.size_bytes != self.size_bytes
            ):
                raise ValueError("provider output identity must match retained bytes")
            if self.semantic_sha256 != self.sha256 or self.semantic_exclusions:
                raise ValueError("provider output cannot invent a semantic projection")
        elif self.retained_artifact is not None:
            raise ValueError(
                "local response identity cannot claim a retained provider artifact"
            )
        if self.validation == "Markdown" and (
            self.semantic_sha256 != self.sha256 or self.semantic_exclusions
        ):
            raise ValueError("Markdown output parity must use exact bytes")
        if self.validation == "ParseResult" and self.semantic_exclusions != (
            "/processing/duration_ms",
        ):
            raise ValueError("JSON parity may exclude only processing.duration_ms")
        return self


class ErrorResponseIdentity(ContractModel):
    sha256: Sha256
    size_bytes: PositiveInt
    media_type: Literal["application/json"]
    validation: Literal["ErrorResponse"]


class ProviderTotalLatencyEvidence(ContractModel):
    """Exact binding for LlamaParse's rounded UI Total Latency value.

    ``normalized_display_ns`` is the unit conversion of the displayed value,
    not a claim of hidden precision.  The half-open interval retains the full
    uncertainty implied by the UI's last displayed digit.
    """

    metric: Literal["provider_ui_total_latency"]
    status: Literal["COMPLETED"]
    job_id: Annotated[str, Field(min_length=5, max_length=128)]
    display_value: Annotated[str, Field(min_length=2, max_length=32)]
    observed_at_utc: datetime
    retained_ui_evidence: ArtifactIdentity
    normalized_display_ns: PositiveInt
    rounding_quantum_ns: PositiveInt
    lower_bound_inclusive_ns: NonNegativeInt
    upper_bound_exclusive_ns: PositiveInt
    rounding_rule: Literal["nearest_display_quantum_half_open"]
    reviewed_sidecar: ArtifactIdentity | None = None

    @field_validator("job_id")
    @classmethod
    def validate_provider_job_id(cls, value: str) -> str:
        if not _LLAMA_JOB_ID.fullmatch(value):
            raise ValueError("provider job ID must use the pjb-* form")
        return value

    @field_validator("observed_at_utc")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc_datetime(value, label="provider observation timestamp")

    @model_validator(mode="after")
    def bind_display_value_and_rounding_interval(self) -> ProviderTotalLatencyEvidence:
        match = _LLAMA_DISPLAY.fullmatch(self.display_value)
        if match is None:
            raise ValueError("provider display must be canonical seconds/minutes text")
        whole, fractional, unit = match.groups()
        try:
            displayed = Decimal(
                whole if fractional is None else f"{whole}.{fractional}"
            )
        except InvalidOperation as error:  # pragma: no cover - regex is definitive
            raise ValueError("provider display is not numeric") from error
        if displayed <= 0:
            raise ValueError("provider Total Latency must be positive")
        unit_ns = 1_000_000_000 if unit == "s" else 60_000_000_000
        decimal_places = len(fractional or "")
        quantum_ns = unit_ns // (10**decimal_places)
        normalized = displayed * unit_ns
        if normalized != normalized.to_integral_value():
            raise ValueError(
                "provider display cannot be represented as integer nanoseconds"
            )
        normalized_ns = int(normalized)
        lower = max(0, normalized_ns - quantum_ns // 2)
        upper = normalized_ns + quantum_ns // 2
        expected = (
            normalized_ns,
            quantum_ns,
            lower,
            upper,
        )
        observed = (
            self.normalized_display_ns,
            self.rounding_quantum_ns,
            self.lower_bound_inclusive_ns,
            self.upper_bound_exclusive_ns,
        )
        if observed != expected:
            raise ValueError(
                "provider numeric value and rounding bounds must derive from the UI display"
            )
        return self


class ProviderEvidenceSidecar(ContractModel):
    schema_id: Literal["phase-latency-provider-reviewed-sidecar-v1"]
    source: SourceIdentity
    project_id: Literal["ec7edb70-8bec-4b1b-9a17-451533884780"]
    account_identifier_sha256: Sha256
    job_id: Annotated[str, Field(min_length=5, max_length=128)]
    status: Literal["COMPLETED"]
    display_value: Annotated[str, Field(min_length=2, max_length=32)]
    observed_at_utc: datetime
    parser_version: Literal["v2"]
    tier: Literal["Agentic"]
    credits_per_page: Literal[10]
    cost_optimization: Literal[False]
    cache_disabled: Literal[True]
    screenshot: ArtifactIdentity
    structured_capture: ArtifactIdentity | None = None
    structured_capture_disposition: Literal[
        "sanitized-provider-export-retained",
        "provider-ui-dom-export-unavailable",
    ]
    provider_output: OutputIdentity
    capture_operator_id: StableId
    independent_reviewer_id: StableId
    reviewed_at_utc: datetime
    secret_scan_passed: Literal[True]
    payload_sha256: Sha256

    @field_validator("job_id")
    @classmethod
    def validate_sidecar_job_id(cls, value: str) -> str:
        if not _LLAMA_JOB_ID.fullmatch(value):
            raise ValueError("provider sidecar job ID is invalid")
        return value

    @field_validator("capture_operator_id", "independent_reviewer_id")
    @classmethod
    def validate_sidecar_reviewer_id(cls, value: str, info: Any) -> str:
        return _require_stable_id(value, label=info.field_name)

    @field_validator("observed_at_utc", "reviewed_at_utc")
    @classmethod
    def validate_sidecar_time(cls, value: datetime, info: Any) -> datetime:
        return _require_utc_datetime(value, label=info.field_name)

    @model_validator(mode="after")
    def validate_sidecar(self) -> ProviderEvidenceSidecar:
        if self.capture_operator_id == self.independent_reviewer_id:
            raise ValueError("provider sidecar requires independent reviewers")
        if self.reviewed_at_utc < self.observed_at_utc:
            raise ValueError("provider review cannot precede capture")
        if (self.structured_capture is None) != (
            self.structured_capture_disposition == "provider-ui-dom-export-unavailable"
        ):
            raise ValueError("provider structured-capture disposition differs")
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        if self.payload_sha256 != _canonical_identity_hash(payload):
            raise ValueError("provider sidecar payload digest must be recomputed")
        return self


class ProviderEvidenceRegistry(ContractModel):
    schema_id: Literal["phase-latency-provider-evidence-registry-v1"]
    sidecars: Annotated[
        tuple[ArtifactIdentity, ...], Field(min_length=1, max_length=75)
    ]
    payload_sha256: Sha256

    @model_validator(mode="after")
    def validate_provider_registry(self) -> ProviderEvidenceRegistry:
        if self.sidecars != tuple(sorted(self.sidecars, key=lambda item: item.path)):
            raise ValueError("provider sidecar registry must be canonical")
        if len({item.path for item in self.sidecars}) != len(self.sidecars):
            raise ValueError("provider sidecar registry paths must be unique")
        payload = self.model_dump(mode="json", exclude={"payload_sha256"})
        if self.payload_sha256 != _canonical_identity_hash(payload):
            raise ValueError("provider sidecar registry digest must be recomputed")
        return self


class FailureCode(StrEnum):
    """Closed, content-free failure labels emitted by the latency harness."""

    CANDIDATE_PROFILE_INCOMPLETE = "candidate_profile_incomplete"
    CALLER_CONFIGURATION_MISMATCH = "caller_configuration_mismatch"
    CLASSIFIER_EXTERNAL_STAGE_CANCELLED = "classifier_external_stage_cancelled"
    CLASSIFIER_EXTERNAL_STAGE_ERROR = "classifier_external_stage_error"
    CLASSIFIER_EXTERNAL_STAGE_TIMEOUT = "classifier_external_stage_timeout"
    CONTROLLER_EXECUTION_IDENTITY_DRIFT = "controller_execution_identity_drift"
    DOCLING_CONVERSION_STATUS_FAILURE = "docling_conversion_status_failure"
    EXTERNAL_STAGE_CANCELLED = "external_stage_cancelled"
    EXTERNAL_STAGE_ERROR = "external_stage_error"
    EXTERNAL_STAGE_TIMEOUT = "external_stage_timeout"
    HTTP_ERROR = "http_error"
    NETWORK_EGRESS_ATTEMPT = "network_egress_attempt"
    PARSE_FAILED = "parse_failed"
    REQUEST_CANCELLED = "request_cancelled"
    REQUEST_EXCEPTION = "request_exception"
    REQUEST_FAILURE = "request_failure"
    REQUEST_TIMEOUT = "request_timeout"
    RESPONSE_VALIDATION_ERROR = "response_validation_error"
    SOURCE_ALIGNMENT_FAILED_CLOSED = "source_alignment_failed_closed"
    SYNTHETIC_QUEUE_FAILURE = "synthetic_queue_failure"
    TABLE_AUTHORITY_FAILED_CLOSED = "table_authority_failed_closed"
    THREADPOOL_CALLABLE_NOT_ENTERED = "threadpool_callable_not_entered"
    WORKER_ACK_EXIT_TIMEOUT = "worker_ack_exit_timeout"
    WORKER_CANCELLED = "worker_cancelled"
    WORKER_EVIDENCE_ERROR = "worker_evidence_error"
    WORKER_EVIDENCE_REJECTED = "worker_evidence_rejected"
    WORKER_EXITED_BEFORE_READY = "worker_exited_before_ready"
    WORKER_EXITED_DURING_REQUEST = "worker_exited_during_request"
    WORKER_FATAL_ENVELOPE_INVALID = "worker_fatal_envelope_invalid"
    WORKER_FATAL_ENVELOPE_WRITE_FAILED = "worker_fatal_envelope_write_failed"
    WORKER_HARD_TIMEOUT = "worker_hard_timeout"
    WORKER_IDENTITY_MISMATCH = "worker_identity_mismatch"
    WORKER_NONZERO_AFTER_FINAL_ACK = "worker_nonzero_after_final_ack"
    WORKER_PROTOCOL_ERROR = "worker_protocol_error"
    WORKER_STARTUP_OR_PREWARM_TIMEOUT = "worker_startup_or_prewarm_timeout"


class FailureRecord(ContractModel):
    code: FailureCode
    stage: StageName
    exception_type: FailureType


class WorkerFatalEnvelope(ContractModel):
    """Bounded, content-free classification for a controlled worker fatal exit."""

    schema_id: Literal["phase-latency-worker-fatal-envelope-v1"]
    checkpoint: Literal[
        "bootstrap",
        "argument_validation",
        "os_network_attestation",
        "source_and_identity_validation",
        "application_startup",
        "testclient_startup",
        "prewarm_request",
        "pre_request_validation",
        "measured_request",
        "post_request_resource_snapshot",
        "post_request_resource_tracker_inspection",
        "response_boundary_handshake",
        "response_validation",
        "testclient_shutdown",
        "post_shutdown_network_check",
        "disposable_parser_state_release",
        "disposable_tqdm_lock_release",
        "disposable_environment_restore",
        "resource_tracker_cleanup",
        "resource_tracker_cleanup_identity",
        "resource_tracker_private_stop",
        "resource_tracker_cleanup_proof",
        "resource_tracker_cleanup_private_state",
        "resource_tracker_cleanup_exit_code",
        "resource_tracker_cleanup_process_absence",
        "resource_tracker_cleanup_no_relaunch",
        "resource_tracker_relaunch_register",
        "resource_tracker_relaunch_unregister",
        "resource_tracker_relaunch_other",
        "resource_closure_handshake",
        "resource_closure_signal",
        "resource_closure_ack_wait",
        "resource_closure_post_tracker",
        "resource_closure_environment",
        "resource_closure_network",
        "evidence_construction",
        "evidence_identity_derivation",
        "evidence_configuration",
        "evidence_cache_state",
        "evidence_stage_trace",
        "evidence_instrumentation_manifest",
        "evidence_instrumentation_harness_files",
        "evidence_instrumentation_overhead",
        "evidence_instrumentation_bindings",
        "evidence_environment_manifest",
        "evidence_contract_validation",
        "evidence_post_validation",
        "evidence_post_tracker",
        "evidence_post_network",
        "evidence_serialization",
        "evidence_done_marker",
        "final_ack",
        "guard_close",
    ]
    exception_family: Literal[
        "network_isolation",
        "memory",
        "timeout",
        "permission",
        "os",
        "validation",
        "assertion",
        "runtime",
        "cancellation",
        "system_exit",
        "unexpected_exception",
        "unexpected_base_exception",
    ]
    exit_code: Literal[88]


class StageSpan(ContractModel):
    span_id: StableId
    name: StageName
    parent_span_id: StableId | None = None
    started_monotonic_ns: NonNegativeInt
    ended_monotonic_ns: NonNegativeInt
    status: StageStatus
    failure_code: FailureCode | None = None
    execution_context_id: StableId = "context-main"
    parent_relation: Literal["root", "causal_stack", "request_scope"] = "root"

    @model_validator(mode="before")
    @classmethod
    def derive_parent_relation(cls, value: Any) -> Any:
        if isinstance(value, dict) and "parent_relation" not in value:
            value = dict(value)
            value["parent_relation"] = (
                "root" if value.get("parent_span_id") is None else "causal_stack"
            )
        return value

    @field_validator("span_id", "parent_span_id", "execution_context_id")
    @classmethod
    def validate_ids(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_stable_id(value, label=info.field_name)

    @model_validator(mode="after")
    def validate_interval_and_status(self) -> StageSpan:
        if self.ended_monotonic_ns < self.started_monotonic_ns:
            raise ValueError("stage span end cannot precede its start")
        if self.status is StageStatus.SUCCESS and self.failure_code is not None:
            raise ValueError("successful stage cannot retain a failure code")
        if self.status is not StageStatus.SUCCESS and self.failure_code is None:
            raise ValueError("failed stage must retain a content-free failure code")
        if self.parent_span_id is None and self.parent_relation != "root":
            raise ValueError("root stage must use the root parent relation")
        if self.parent_span_id is not None and self.parent_relation == "root":
            raise ValueError("child stage must retain its causal parent relation")
        return self


class StageTrace(ContractModel):
    schema_id: Literal["phase-latency-stage-trace-v1"]
    status: StageStatus
    authoritative_total_ns: PositiveInt
    collector_started_monotonic_ns: NonNegativeInt | None = None
    collector_finished_monotonic_ns: NonNegativeInt | None = None
    pre_collector_duration_ns: NonNegativeInt | None = None
    post_collector_duration_ns: NonNegativeInt | None = None
    attributed_top_level_union_ns: NonNegativeInt
    unattributed_remainder_ns: NonNegativeInt
    spans: Annotated[
        tuple[StageSpan, ...],
        Field(min_length=1, max_length=MAXIMUM_STAGE_SPANS),
    ]

    @model_validator(mode="after")
    def validate_closed_tree(self) -> StageTrace:
        ids = tuple(span.span_id for span in self.spans)
        if len(ids) != len(set(ids)):
            raise ValueError("stage span IDs must be unique")
        roots = tuple(span for span in self.spans if span.parent_span_id is None)
        if len(roots) != 1 or roots[0] != self.spans[0]:
            raise ValueError("stage trace requires exactly one first root")
        root = roots[0]
        if root.name is not StageName.REQUEST_TOTAL:
            raise ValueError("stage trace root must be request_total")
        if root.status is not self.status:
            raise ValueError("stage trace status must equal root status")
        if (
            root.ended_monotonic_ns - root.started_monotonic_ns
            != self.authoritative_total_ns
        ):
            raise ValueError("root duration must equal authoritative total")
        collector_values = (
            self.collector_started_monotonic_ns,
            self.collector_finished_monotonic_ns,
            self.pre_collector_duration_ns,
            self.post_collector_duration_ns,
        )
        if any(value is None for value in collector_values):
            if any(value is not None for value in collector_values):
                raise ValueError("collector boundary evidence must be all-or-none")
        else:
            collector_started = int(self.collector_started_monotonic_ns or 0)
            collector_finished = int(self.collector_finished_monotonic_ns or 0)
            if not (
                root.started_monotonic_ns
                <= collector_started
                <= collector_finished
                <= root.ended_monotonic_ns
            ):
                raise ValueError("collector interval must remain inside request")
            if self.pre_collector_duration_ns != (
                collector_started - root.started_monotonic_ns
            ):
                raise ValueError("pre-collector duration must be recomputed")
            if self.post_collector_duration_ns != (
                root.ended_monotonic_ns - collector_finished
            ):
                raise ValueError("post-collector duration must be recomputed")

        by_id: dict[str, StageSpan] = {}
        for span in self.spans:
            if span.parent_span_id is not None:
                parent = by_id.get(span.parent_span_id)
                if parent is None:
                    raise ValueError("stage parent must precede its child")
                if (
                    span.started_monotonic_ns < parent.started_monotonic_ns
                    or span.ended_monotonic_ns > parent.ended_monotonic_ns
                ):
                    raise ValueError("child stage must remain inside its parent")
            by_id[span.span_id] = span
        top_level_intervals = sorted(
            (
                span.started_monotonic_ns,
                span.ended_monotonic_ns,
            )
            for span in self.spans[1:]
            if span.parent_span_id == root.span_id
        )
        union_ns = 0
        union_start: int | None = None
        union_end: int | None = None
        for started, ended in top_level_intervals:
            if union_start is None:
                union_start, union_end = started, ended
            elif started <= int(union_end or 0):
                union_end = max(int(union_end or 0), ended)
            else:
                union_ns += int(union_end or 0) - union_start
                union_start, union_end = started, ended
        if union_start is not None:
            union_ns += int(union_end or 0) - union_start
        if self.attributed_top_level_union_ns != union_ns:
            raise ValueError("top-level attributed union must be recomputed")
        if self.unattributed_remainder_ns != self.authoritative_total_ns - union_ns:
            raise ValueError("unattributed remainder must be recomputed")
        return self


class CallableTargetEvidence(ContractModel):
    target_id: StableId
    stage: StageName
    module: Annotated[str, Field(min_length=1, max_length=256)]
    attribute: Annotated[str, Field(min_length=1, max_length=256)]
    qualname: Annotated[str, Field(min_length=1, max_length=512)]
    source: ArtifactIdentity
    signature: Annotated[str, Field(min_length=1, max_length=32_768)]
    signature_sha256: Sha256
    callable_kind: Literal[
        "sync_function",
        "async_function",
        "class_binding",
        "bound_method",
    ]
    code_sha256: Sha256
    wrapper_strategy: Literal[
        "exception_only_sync",
        "exception_only_async",
        "response_constructor",
        "parse_result_binding_proxy",
        "natural_instance_get_pipeline",
        "lazy_import_module_patch",
        "load_callable_resolution",
    ]
    classifier_id: Literal[
        "exception_only",
        "docling_conversion_status_v1",
        "source_alignment_fail_closed_v1",
        "table_authority_state_v1",
        "none",
    ]
    cardinality_policy_id: StableId
    installed: StrictBool
    invocation_count: NonNegativeInt
    pre_binding_sha256: Sha256 | None
    installed_binding_sha256: Sha256 | None
    post_restore_binding_sha256: Sha256 | None
    restored_exact_binding: StrictBool | None

    @field_validator("target_id", "cardinality_policy_id")
    @classmethod
    def validate_target_ids(cls, value: str, info: Any) -> str:
        return _require_stable_id(value, label=info.field_name)

    @model_validator(mode="after")
    def bind_installation_evidence(self) -> CallableTargetEvidence:
        if hashlib.sha256(self.signature.encode("utf-8")).hexdigest() != (
            self.signature_sha256
        ):
            raise ValueError("callable signature digest must be recomputed")
        bindings = (
            self.pre_binding_sha256,
            self.installed_binding_sha256,
            self.post_restore_binding_sha256,
            self.restored_exact_binding,
        )
        if self.installed:
            if any(value is None for value in bindings):
                raise ValueError("installed target requires complete binding evidence")
            if self.pre_binding_sha256 != self.post_restore_binding_sha256:
                raise ValueError("target binding was not restored byte-identically")
            if self.restored_exact_binding is not True:
                raise ValueError("target binding must restore the exact prior object")
        elif any(value is not None for value in bindings) or self.invocation_count:
            raise ValueError(
                "uninstalled target cannot claim binding/invocation evidence"
            )
        return self


class ObserverOverheadEvidence(ContractModel):
    calibration_id: Literal["external_exception_wrapper_noop_v1"]
    call_count: Literal[256]
    unwrapped_total_ns: NonNegativeInt
    wrapped_total_ns: NonNegativeInt
    absolute_delta_ns: NonNegativeInt
    adjustment_applied: Literal[False]

    @model_validator(mode="after")
    def recompute_delta(self) -> ObserverOverheadEvidence:
        if self.absolute_delta_ns != abs(
            self.wrapped_total_ns - self.unwrapped_total_ns
        ):
            raise ValueError("observer calibration delta must be recomputed")
        return self


class InstrumentationManifest(ContractModel):
    schema_id: Literal["phase-latency-external-observer-manifest-v1"]
    schema_version: Literal["1.0"]
    observer_mode: Literal["diagnostic_external_test_instrumentation"]
    observer_version: Literal["lat-us01-v1"]
    authoritative_total_policy: Literal[
        "separate_uninstrumented_twin_no_observer_subtraction"
    ]
    harness_files: Annotated[
        tuple[ArtifactIdentity, ...], Field(min_length=9, max_length=9)
    ]
    targets: Annotated[
        tuple[CallableTargetEvidence, ...], Field(min_length=1, max_length=64)
    ]
    installed_target_count: NonNegativeInt
    request_collector_id: Literal["external-request-scoped-perf-counter-ns-v1"]
    import_hook_finder_id: Literal["phase-latency-scoped-meta-path-finder-v1"]
    import_hook_loader_id: Literal["phase-latency-scoped-loader-v1"]
    python_implementation: Literal["CPython"]
    python_version: Annotated[str, Field(min_length=3, max_length=32)]
    runtime_sha256: Sha256
    dependency_lock_sha256: Sha256
    docling_version: Annotated[str, Field(min_length=1, max_length=64)] | None
    docling_get_pipeline_signature_sha256: Sha256 | None
    docling_get_pipeline_disposition: Literal[
        "initialized",
        "reused",
        "mixed",
        "not_observed",
    ]
    observer_overhead: ObserverOverheadEvidence
    hosted_calls: Literal[0]
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def recompute_manifest(self) -> InstrumentationManifest:
        expected_harness_paths = (
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
        if self.harness_files != tuple(
            sorted(self.harness_files, key=lambda item: item.path)
        ):
            raise ValueError("harness file identities must be canonical")
        if len({item.path for item in self.harness_files}) != len(self.harness_files):
            raise ValueError("harness file paths must be unique")
        if tuple(item.path for item in self.harness_files) != expected_harness_paths:
            raise ValueError("instrumentation harness inventory differs")
        if self.targets != tuple(sorted(self.targets, key=lambda item: item.target_id)):
            raise ValueError("instrumentation targets must be canonical")
        if len({item.target_id for item in self.targets}) != len(self.targets):
            raise ValueError("instrumentation target IDs must be unique")
        from tests.benchmarks.latency_instrumentation import TARGETS

        expected_targets = {
            item.target_id: (
                item.stage,
                item.source_module,
                item.attribute,
                item.source_attribute,
                item.strategy,
                item.classifier_id,
                item.policy_id,
            )
            for item in TARGETS
        }
        observed_targets = {
            item.target_id: (
                item.stage,
                item.module,
                item.attribute,
                item.qualname,
                item.wrapper_strategy,
                item.classifier_id,
                item.cardinality_policy_id,
            )
            for item in self.targets
        }
        if observed_targets != expected_targets:
            raise ValueError("instrumentation target inventory differs")
        if self.installed_target_count != sum(item.installed for item in self.targets):
            raise ValueError("installed target count must be recomputed")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != _canonical_identity_hash(payload):
            raise ValueError("observer manifest digest must be recomputed")
        return self


class PrewarmEvidence(ContractModel):
    policy: Literal["separate-pinned-route-equivalent-source-v1"]
    source: SourceIdentity
    output: OutputIdentity
    duration_ns: PositiveInt
    worker_self_cpu_ns: NonNegativeInt
    reaped_children_cpu_ns: NonNegativeInt
    worker_process_lifetime_hwm_bytes: PositiveInt
    reaped_children_process_lifetime_hwm_bytes: NonNegativeInt
    content_result_cache_observed: Literal[False]


class CacheStateEvidence(ContractModel):
    profile: Literal[
        "request_cold_after_app_startup",
        "request_prewarmed_after_app_startup",
    ]
    application_startup_completed: Literal[True]
    pipeline_loaded_at_request_start: StrictBool
    converter_cache_entries_at_request_start: NonNegativeInt
    converter_cache_entries_after_request: NonNegativeInt
    prewarm_request_completed: StrictBool
    prewarm_evidence: PrewarmEvidence | None = None
    content_result_cache_observed: Literal[False]
    content_result_cache_proof_sha256: Sha256
    filesystem_cache_state: Literal["uncontrolled_shared_host_cache"]

    @model_validator(mode="after")
    def bind_profile_state(self) -> CacheStateEvidence:
        if self.profile == "request_cold_after_app_startup":
            if (
                self.pipeline_loaded_at_request_start is not False
                or self.converter_cache_entries_at_request_start != 0
                or self.prewarm_request_completed is not False
                or self.prewarm_evidence is not None
            ):
                raise ValueError("cold request cache proof differs")
        elif (
            self.pipeline_loaded_at_request_start is not True
            or self.converter_cache_entries_at_request_start <= 0
            or self.prewarm_request_completed is not True
            or self.prewarm_evidence is None
        ):
            raise ValueError("prewarmed request cache proof differs")
        return self


class WorkerResourceBoundaryEvidence(ContractModel):
    basis: Literal[
        "exact-rusage-self-and-reaped-children-before-validation-v1",
        "response-boundary-plus-post-response-reaped-lifecycle-v2",
    ]
    worker_self_user_cpu_delta_ns: NonNegativeInt
    worker_self_system_cpu_delta_ns: NonNegativeInt
    reaped_children_user_cpu_delta_ns: NonNegativeInt
    reaped_children_system_cpu_delta_ns: NonNegativeInt
    worker_process_lifetime_hwm_bytes: PositiveInt
    reaped_children_process_lifetime_hwm_bytes: NonNegativeInt
    conservative_root_plus_reaped_children_hwm_bytes: PositiveInt | None = None
    lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes: PositiveInt | None = (
        None
    )
    response_boundary_worker_self_user_cpu_delta_ns: NonNegativeInt | None = None
    response_boundary_worker_self_system_cpu_delta_ns: NonNegativeInt | None = None
    response_boundary_reaped_children_user_cpu_delta_ns: NonNegativeInt | None = None
    response_boundary_reaped_children_system_cpu_delta_ns: NonNegativeInt | None = None
    response_boundary_worker_process_lifetime_hwm_bytes: PositiveInt | None = None
    response_boundary_reaped_children_process_lifetime_hwm_bytes: (
        NonNegativeInt | None
    ) = None
    post_response_cleanup_cpu_and_hwm_included: StrictBool | None = None

    @model_validator(mode="after")
    def recompute_resource_boundary(self) -> WorkerResourceBoundaryEvidence:
        response_fields = (
            self.response_boundary_worker_self_user_cpu_delta_ns,
            self.response_boundary_worker_self_system_cpu_delta_ns,
            self.response_boundary_reaped_children_user_cpu_delta_ns,
            self.response_boundary_reaped_children_system_cpu_delta_ns,
            self.response_boundary_worker_process_lifetime_hwm_bytes,
            self.response_boundary_reaped_children_process_lifetime_hwm_bytes,
            self.post_response_cleanup_cpu_and_hwm_included,
        )
        if self.basis == "response-boundary-plus-post-response-reaped-lifecycle-v2":
            if any(value is None for value in response_fields):
                raise ValueError("v2 resource boundary evidence is incomplete")
            if self.post_response_cleanup_cpu_and_hwm_included is not True:
                raise ValueError("v2 lifecycle resources must be conservative")
            if (
                self.conservative_root_plus_reaped_children_hwm_bytes is not None
                or self.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
                != self.worker_process_lifetime_hwm_bytes
                + self.reaped_children_process_lifetime_hwm_bytes
            ):
                raise ValueError("v2 lifecycle HWM component must be recomputed")
            if (
                self.worker_self_user_cpu_delta_ns
                < int(self.response_boundary_worker_self_user_cpu_delta_ns or 0)
                or self.worker_self_system_cpu_delta_ns
                < int(self.response_boundary_worker_self_system_cpu_delta_ns or 0)
                or self.reaped_children_user_cpu_delta_ns
                < int(self.response_boundary_reaped_children_user_cpu_delta_ns or 0)
                or self.reaped_children_system_cpu_delta_ns
                < int(self.response_boundary_reaped_children_system_cpu_delta_ns or 0)
                or self.worker_process_lifetime_hwm_bytes
                < int(self.response_boundary_worker_process_lifetime_hwm_bytes or 0)
                or self.reaped_children_process_lifetime_hwm_bytes
                < int(
                    self.response_boundary_reaped_children_process_lifetime_hwm_bytes
                    or 0
                )
            ):
                raise ValueError("post-response lifecycle resources were understated")
        else:
            if any(value is not None for value in response_fields):
                raise ValueError(
                    "v1 resource boundary cannot claim v2 lifecycle evidence"
                )
            if (
                self.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
                is not None
                or self.conservative_root_plus_reaped_children_hwm_bytes
                != self.worker_process_lifetime_hwm_bytes
                + self.reaped_children_process_lifetime_hwm_bytes
            ):
                raise ValueError("legacy process-lifetime HWM must be recomputed")
        return self


class OSNetworkSandboxEvidence(ContractModel):
    policy: Literal["macos-sandbox-exec-deny-inet-process-tree-v1"]
    platform: Literal["Darwin"]
    executable_path: Literal["/usr/bin/sandbox-exec"]
    executable_size_bytes: PositiveInt
    executable_sha256: Sha256
    profile_size_bytes: PositiveInt
    profile_sha256: Sha256
    child_guard_size_bytes: PositiveInt
    child_guard_sha256: Sha256
    inherited_by_descendants: Literal[True]
    fresh_subprocess_exit_code: Literal[0]
    nested_subprocess_exit_code: Literal[0]
    ipv4_tcp_connect: Literal["EPERM"]
    ipv4_tcp_bind: Literal["EPERM"]
    ipv4_udp_send: Literal["EPERM"]
    ipv6_tcp_connect: Literal["EPERM"]
    ipv6_tcp_bind: Literal["EPERM"]
    ipv6_udp_send: Literal["EPERM"]
    filesystem_unix_connect: Literal["EPERM"]
    unix_socketpair_roundtrip: Literal[True]
    child_guard_subprocess_exit_code: Literal[0]
    child_guard_bindings_exact: Literal[True]
    child_guard_ipv4_socket_create: Literal["EPERM"]
    child_guard_ipv6_socket_create: Literal["EPERM"]
    child_guard_getaddrinfo: Literal["EPERM"]
    child_guard_gethostbyaddr: Literal["EPERM"]
    child_guard_gethostbyname: Literal["EPERM"]
    child_guard_gethostbyname_ex: Literal["EPERM"]
    child_guard_getnameinfo: Literal["EPERM"]
    child_guard_getfqdn_denied_via_guarded_primitive: Literal[True]
    child_guard_ipv6_capability_suppressed: Literal[True]
    child_guard_unix_socketpair_roundtrip: Literal[True]
    child_guard_denied_attempt_count: Annotated[
        int,
        Field(strict=True, ge=7, le=16),
    ]


class NetworkIsolationEvidence(ContractModel):
    policy: Literal[
        "sanitized-offline-env-and-python-af-inet-deny-v1",
        "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2",
    ]
    worker_environment_sha256: Sha256
    inherited_sensitive_variable_count: Literal[0]
    offline_environment_applied: Literal[True]
    python_socket_guard_installed: Literal[True]
    denied_network_attempt_count: NonNegativeInt
    hosted_calls_completed: Literal[0]
    source_bytecode_policy: Literal["fresh-empty-pycache-prefix-source-import-v1"]
    ipv6_capability_suppressed_with_zero_exit_restore_requirement: StrictBool | None = (
        None
    )
    python_guard_restore_disposition: (
        Literal[
            "pending-worker-zero-exit",
            "controller-verified-worker-zero-exit",
        ]
        | None
    ) = None
    os_process_tree_sandbox: OSNetworkSandboxEvidence | None = None

    @model_validator(mode="after")
    def bind_process_tree_network_isolation(self) -> NetworkIsolationEvidence:
        if self.policy == (
            "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
        ):
            if (
                self.ipv6_capability_suppressed_with_zero_exit_restore_requirement
                is not True
                or self.python_guard_restore_disposition
                not in {
                    "pending-worker-zero-exit",
                    "controller-verified-worker-zero-exit",
                }
                or self.os_process_tree_sandbox is None
            ):
                raise ValueError("v2 process-tree network isolation is incomplete")
        elif (
            self.ipv6_capability_suppressed_with_zero_exit_restore_requirement
            is not None
            or self.python_guard_restore_disposition is not None
            or self.os_process_tree_sandbox is not None
        ):
            raise ValueError("v1 network isolation cannot claim v2 evidence")
        return self


class WorkerWatchdogEvidence(ContractModel):
    schema_id: Literal["phase-latency-worker-watchdog-v1"]
    exit_code: Literal[0]
    outcome: Literal["worker_exited"]
    worker_kill_attempted: Literal[False]
    worker_kill_confirmed: Literal[False]


class ProcessIdentity(ContractModel):
    pid: PositiveInt
    create_time_ns: PositiveInt
    role: ProcessRole


class ResourceTrackerDisposition(ContractModel):
    policy: Literal["disposable-worker-resource-tracker-reap-v1"]
    disposition: Literal[
        "absent_at_response_boundary",
        "started_during_request_reaped_after_response",
        "preexisting_at_baseline_reaped_after_response",
    ]
    identity: ProcessIdentity | None = None
    tracker_fd: NonNegativeInt | None = None
    worker_write_fd: NonNegativeInt | None = None
    cleanup_started_monotonic_ns: NonNegativeInt | None = None
    cleanup_ended_monotonic_ns: NonNegativeInt | None = None
    shutdown_api: (
        Literal["cpython-multiprocessing-resource-tracker-private-stop"] | None
    ) = None
    exit_code: Literal[0] | None = None
    no_relaunch_immediately_after_cleanup_verified: StrictBool
    controller_no_relaunch_through_zero_exit_verified: StrictBool | None = None
    latency_adjustment_applied: Literal[False]

    @model_validator(mode="after")
    def bind_resource_tracker_lifecycle(self) -> ResourceTrackerDisposition:
        lifecycle = (
            self.identity,
            self.tracker_fd,
            self.worker_write_fd,
            self.cleanup_started_monotonic_ns,
            self.cleanup_ended_monotonic_ns,
            self.shutdown_api,
            self.exit_code,
        )
        if self.disposition == "absent_at_response_boundary":
            if any(value is not None for value in lifecycle):
                raise ValueError("absent resource tracker cannot claim cleanup")
        else:
            if any(value is None for value in lifecycle):
                raise ValueError("resource tracker cleanup evidence is incomplete")
            if self.identity is None or self.identity.role is not (
                ProcessRole.RESOURCE_TRACKER
            ):
                raise ValueError("resource tracker identity role differs")
            if self.tracker_fd == self.worker_write_fd:
                raise ValueError("resource tracker pipe endpoints must differ")
            if int(self.cleanup_ended_monotonic_ns or 0) <= int(
                self.cleanup_started_monotonic_ns or 0
            ):
                raise ValueError("resource tracker cleanup interval is not positive")
        if self.no_relaunch_immediately_after_cleanup_verified is not True:
            raise ValueError("immediate tracker relaunch proof is absent")
        return self


class ProcessMetric(ContractModel):
    identity: ProcessIdentity
    rss_bytes: PositiveInt
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt
    thread_count: PositiveInt
    fd_count: NonNegativeInt
    self_hwm_bytes: PositiveInt | None = None

    @model_validator(mode="after")
    def require_worker_hwm_only(self) -> ProcessMetric:
        if self.identity.role is ProcessRole.CANDIDATE_WORKER:
            if self.self_hwm_bytes is None or self.self_hwm_bytes < self.rss_bytes:
                raise ValueError("worker HWM must be present and no smaller than RSS")
        elif self.self_hwm_bytes is not None:
            raise ValueError("descendant HWM cannot be invented")
        return self


class ProcessTreeSnapshot(ContractModel):
    observed_monotonic_ns: NonNegativeInt
    members: Annotated[
        tuple[ProcessMetric, ...],
        Field(min_length=1, max_length=MAXIMUM_PROCESSES_PER_SNAPSHOT),
    ]
    total_rss_bytes: PositiveInt
    total_user_cpu_ns: NonNegativeInt
    total_system_cpu_ns: NonNegativeInt
    total_thread_count: PositiveInt
    total_fd_count: NonNegativeInt

    @model_validator(mode="after")
    def recompute_totals_and_order(self) -> ProcessTreeSnapshot:
        identities = tuple(
            (member.identity.pid, member.identity.create_time_ns)
            for member in self.members
        )
        if len(identities) != len(set(identities)):
            raise ValueError("process snapshot identities must be unique")
        if self.members[0].identity.role is not ProcessRole.CANDIDATE_WORKER:
            raise ValueError("worker must be the first process-tree member")
        descendants = identities[1:]
        if descendants != tuple(sorted(descendants)):
            raise ValueError("descendant process identities must be canonical")
        expected = {
            "total_rss_bytes": sum(item.rss_bytes for item in self.members),
            "total_user_cpu_ns": sum(item.user_cpu_ns for item in self.members),
            "total_system_cpu_ns": sum(item.system_cpu_ns for item in self.members),
            "total_thread_count": sum(item.thread_count for item in self.members),
            "total_fd_count": sum(item.fd_count for item in self.members),
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"{field} must be recomputed from members")
        return self


class ProcessTreeMetrics(ContractModel):
    schema_id: Literal["phase-latency-process-tree-metrics-v1"]
    scope: Literal["candidate_worker_and_descendants"]
    request_started_monotonic_ns: NonNegativeInt
    request_ended_monotonic_ns: NonNegativeInt
    sampling_interval_target_ns: PositiveInt
    hard_maximum_gap_ns: PositiveInt
    maximum_observed_gap_ns: PositiveInt
    snapshots: Annotated[
        tuple[ProcessTreeSnapshot, ...],
        Field(min_length=2, max_length=MAXIMUM_PROCESS_SNAPSHOTS),
    ]
    peak_total_rss_bytes: PositiveInt
    peak_worker_hwm_bytes: PositiveInt
    maximum_observed_process_cpu_ns: NonNegativeInt
    exact_worker_self_cpu_ns: NonNegativeInt
    exact_reaped_children_cpu_ns: NonNegativeInt
    conservative_frozen_response_boundary_descendant_cpu_ns: NonNegativeInt = 0
    post_response_lifecycle_cpu_ns: NonNegativeInt | None = None
    baseline_descendant_cumulative_cpu_ns: NonNegativeInt | None = None
    response_boundary_descendant_cumulative_cpu_ns: NonNegativeInt | None = None
    lifecycle_exact_worker_self_cpu_ns: NonNegativeInt | None = None
    lifecycle_reaped_children_cpu_ns: NonNegativeInt | None = None
    reaped_children_hwm_bytes: NonNegativeInt
    conservative_process_lifetime_hwm_bytes: PositiveInt | None = None
    lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes: PositiveInt | None = (
        None
    )
    resource_boundary_basis: Literal[
        "same-process-rusage-self-v1",
        "exact-rusage-self-and-reaped-children-before-validation-v1",
        "response-boundary-plus-post-response-reaped-lifecycle-v2",
    ]
    resource_boundary_complete: StrictBool
    response_boundary_snapshot: ProcessTreeSnapshot | None = None
    response_boundary_snapshot_index: NonNegativeInt | None = None
    resource_closure_snapshot: ProcessTreeSnapshot | None = None
    response_boundary_descendant_count: NonNegativeInt | None = None
    response_boundary_descendant_roles: tuple[ProcessRole, ...] | None = None
    resource_closure_complete: StrictBool | None = None
    resource_tracker_freeze_disposition: (
        Literal[
            "not_required_root_only",
            "controller-sigstop-snapshot-sigcont-v1",
        ]
        | None
    ) = None
    resource_tracker_command_fd: NonNegativeInt | None = None
    resource_tracker_worker_write_fd: NonNegativeInt | None = None
    resource_tracker_stopped_state_verified: StrictBool | None = None
    resource_tracker_resumed_state_verified: StrictBool | None = None
    response_through_resource_closure_peak_total_rss_bytes: PositiveInt | None = None
    worker_reported_hwm_bytes_at_response_boundary: PositiveInt | None = None
    worker_lifetime_hwm_bytes_at_resource_closure: PositiveInt | None = None
    rss_measurement_basis: Literal[
        "sampled_process_tree_lower_bound_at_bounded_cadence"
    ]
    cpu_measurement_basis: Literal["sum_of_per_process_request_cumulative_deltas"]
    worker_hwm_measurement_basis: Literal[
        "worker_reported_ru_maxrss",
        "same_process_ru_maxrss",
    ]
    descendant_observation_basis: Literal[
        "recursive_psutil",
        "synthetic_worker_declared_no_children",
    ]
    cleanup_disposition: Literal[
        "same_process_restored",
        "external_worker_reaped",
    ]
    worker_reaped: StrictBool
    observed_descendants_reaped: StrictBool

    @model_validator(mode="after")
    def recompute_process_tree_summary(self) -> ProcessTreeMetrics:
        if self.request_ended_monotonic_ns <= self.request_started_monotonic_ns:
            raise ValueError("process-tree request interval must be positive")
        if self.sampling_interval_target_ns > self.hard_maximum_gap_ns:
            raise ValueError(
                "process-tree target cadence cannot exceed its hard maximum"
            )
        timestamps = tuple(item.observed_monotonic_ns for item in self.snapshots)
        if any(current <= previous for previous, current in pairwise(timestamps)):
            raise ValueError("process-tree timestamps must increase strictly")
        gaps = tuple(current - previous for previous, current in pairwise(timestamps))
        observed_gap = max(gaps)
        if self.maximum_observed_gap_ns != observed_gap:
            raise ValueError("maximum process-tree gap must be recomputed")
        if observed_gap > self.hard_maximum_gap_ns:
            raise ValueError("process-tree sampling cadence exceeded")
        if timestamps[0] > self.request_started_monotonic_ns:
            raise ValueError("process-tree sampling must retain a pre-request baseline")
        if timestamps[-1] < self.request_ended_monotonic_ns:
            raise ValueError("process-tree sampling must retain a terminal snapshot")
        if not any(
            self.request_started_monotonic_ns
            <= timestamp
            <= self.request_ended_monotonic_ns
            for timestamp in timestamps
        ) and (
            self.request_ended_monotonic_ns - self.request_started_monotonic_ns
            > self.sampling_interval_target_ns
        ):
            raise ValueError("process-tree sampling must cover the request interval")
        root = self.snapshots[0].members[0].identity
        for snapshot in self.snapshots:
            if snapshot.members[0].identity != root:
                raise ValueError("worker identity changed during process-tree sampling")
        baseline = self.snapshots[0]
        terminal = self.snapshots[-1]
        v2_closure = self.response_boundary_snapshot is not None
        if v2_closure != (
            self.resource_boundary_basis
            == "response-boundary-plus-post-response-reaped-lifecycle-v2"
        ):
            raise ValueError("process resource basis/closure shape differs")
        if len(baseline.members) != 1 and (
            not v2_closure
            or len(baseline.members) != 2
            or baseline.members[1].identity.role is not ProcessRole.RESOURCE_TRACKER
        ):
            raise ValueError("process-tree baseline has an unsupported descendant")
        if self.cleanup_disposition == "same_process_restored":
            if len(terminal.members) != 1:
                raise ValueError(
                    "same-process terminal sample must have no descendants"
                )
            if self.worker_reaped is not False:
                raise ValueError("same-process evidence cannot claim worker reaping")
            if terminal.members[0].thread_count != baseline.members[0].thread_count:
                raise ValueError("terminal worker threads must return to baseline")
            if terminal.members[0].fd_count != baseline.members[0].fd_count:
                raise ValueError(
                    "terminal worker file descriptors must return to baseline"
                )
        elif self.worker_reaped is not True:
            raise ValueError("external worker cleanup must retain reap proof")
        if self.observed_descendants_reaped is not True:
            raise ValueError("observed descendants must be reaped")
        closure_fields = (
            self.response_boundary_snapshot,
            self.response_boundary_snapshot_index,
            self.resource_closure_snapshot,
            self.response_boundary_descendant_count,
            self.response_boundary_descendant_roles,
            self.resource_closure_complete,
            self.resource_tracker_freeze_disposition,
            self.response_through_resource_closure_peak_total_rss_bytes,
            self.worker_lifetime_hwm_bytes_at_resource_closure,
        )
        if any(value is not None for value in closure_fields):
            if any(value is None for value in closure_fields):
                raise ValueError("v2 process resource closure evidence is incomplete")
            assert self.response_boundary_snapshot is not None
            assert self.resource_closure_snapshot is not None
            if (
                int(self.response_boundary_snapshot_index or 0) >= len(self.snapshots)
                or self.snapshots[int(self.response_boundary_snapshot_index or 0)]
                != self.response_boundary_snapshot
            ):
                raise ValueError("response boundary snapshot index differs")
            if self.resource_closure_snapshot != self.snapshots[-1]:
                raise ValueError("resource closure must be the terminal snapshot")
            if self.response_boundary_snapshot.observed_monotonic_ns < (
                self.request_ended_monotonic_ns
            ):
                raise ValueError("response resource boundary precedes request end")
            roles = tuple(
                member.identity.role
                for member in self.response_boundary_snapshot.members[1:]
            )
            baseline_descendants = tuple(
                member.identity for member in baseline.members[1:]
            )
            response_descendants = tuple(
                member.identity
                for member in self.response_boundary_snapshot.members[1:]
            )
            if baseline_descendants and baseline_descendants != response_descendants:
                raise ValueError("prewarmed tracker identity changed during request")
            tracker_identities = {
                (member.identity.pid, member.identity.create_time_ns)
                for snapshot in self.snapshots
                for member in snapshot.members[1:]
                if member.identity.role is ProcessRole.RESOURCE_TRACKER
            }
            if len(tracker_identities) > 1:
                raise ValueError("multiple resource tracker identities were observed")
            if (
                self.response_boundary_descendant_count != len(roles)
                or self.response_boundary_descendant_roles != roles
            ):
                raise ValueError("response boundary descendant summary differs")
            if len(self.resource_closure_snapshot.members) != 1:
                raise ValueError("resource closure retained a descendant")
            if (
                self.resource_closure_complete is not True
                or self.resource_boundary_complete is not True
            ):
                raise ValueError("post-response resource closure is incomplete")
            for snapshot in self.snapshots[
                int(self.response_boundary_snapshot_index or 0) : -1
            ]:
                if any(
                    member.identity.role is not ProcessRole.RESOURCE_TRACKER
                    for member in snapshot.members[1:]
                ):
                    raise ValueError(
                        "post-response snapshot retained a non-tracker child"
                    )
            if not roles:
                if self.resource_tracker_freeze_disposition != (
                    "not_required_root_only"
                ):
                    raise ValueError("root-only boundary cannot claim tracker freeze")
            elif (
                roles != (ProcessRole.RESOURCE_TRACKER,)
                or self.resource_tracker_freeze_disposition
                != "controller-sigstop-snapshot-sigcont-v1"
            ):
                raise ValueError("response boundary descendant is not a frozen tracker")
            if roles:
                if (
                    self.resource_tracker_command_fd is None
                    or self.resource_tracker_worker_write_fd is None
                    or self.resource_tracker_command_fd
                    == self.resource_tracker_worker_write_fd
                    or self.resource_tracker_stopped_state_verified is not True
                    or self.resource_tracker_resumed_state_verified is not True
                ):
                    raise ValueError("resource tracker freeze proof is incomplete")
            elif any(
                value is not None
                for value in (
                    self.resource_tracker_command_fd,
                    self.resource_tracker_worker_write_fd,
                    self.resource_tracker_stopped_state_verified,
                    self.resource_tracker_resumed_state_verified,
                )
            ):
                raise ValueError("root-only response cannot claim tracker freeze proof")
        elif self.resource_boundary_complete is not True:
            # Legacy failed evidence can still be constructed and rejected by
            # its enclosing attempt; it cannot claim v2 closure semantics.
            pass
        if not v2_closure and any(
            value is not None
            for value in (
                self.resource_tracker_command_fd,
                self.resource_tracker_worker_write_fd,
                self.resource_tracker_stopped_state_verified,
                self.resource_tracker_resumed_state_verified,
            )
        ):
            raise ValueError("non-v2 process tree cannot claim tracker freeze proof")
        request_snapshots = (
            self.snapshots[: int(self.response_boundary_snapshot_index or 0) + 1]
            if self.response_boundary_snapshot is not None
            else self.snapshots
        )
        if self.peak_total_rss_bytes != max(
            item.total_rss_bytes for item in request_snapshots
        ):
            raise ValueError("process-tree RSS peak must be recomputed")
        if self.peak_worker_hwm_bytes != max(
            int(item.members[0].self_hwm_bytes or 0) for item in request_snapshots
        ):
            raise ValueError("worker HWM peak must be recomputed")
        if self.response_boundary_snapshot is not None:
            if self.worker_reported_hwm_bytes_at_response_boundary is not None and (
                self.worker_hwm_measurement_basis != "worker_reported_ru_maxrss"
                or self.peak_worker_hwm_bytes
                < self.worker_reported_hwm_bytes_at_response_boundary
            ):
                raise ValueError("reported response HWM exceeds conservative HWM")
            response_through_closure = self.snapshots[
                int(self.response_boundary_snapshot_index or 0) :
            ]
            if self.response_through_resource_closure_peak_total_rss_bytes != max(
                item.total_rss_bytes for item in response_through_closure
            ):
                raise ValueError("response-through-closure RSS peak must be recomputed")
            if self.worker_lifetime_hwm_bytes_at_resource_closure != int(
                self.resource_closure_snapshot.members[0].self_hwm_bytes or 0
            ):
                raise ValueError("closure worker lifetime HWM differs")
        elif self.worker_reported_hwm_bytes_at_response_boundary is not None:
            raise ValueError("reported response HWM requires a v2 boundary")
        if self.response_boundary_snapshot is not None:
            if (
                self.conservative_process_lifetime_hwm_bytes is not None
                or self.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
                != int(self.worker_lifetime_hwm_bytes_at_resource_closure or 0)
                + self.reaped_children_hwm_bytes
            ):
                raise ValueError("lifecycle HWM component must be recomputed")
        elif (
            self.lifecycle_root_hwm_plus_max_reaped_child_hwm_component_bytes
            is not None
            or self.conservative_process_lifetime_hwm_bytes
            != self.peak_worker_hwm_bytes + self.reaped_children_hwm_bytes
        ):
            raise ValueError("legacy process-lifetime HWM must be recomputed")
        if self.cleanup_disposition == "external_worker_reaped" and (
            self.resource_boundary_basis
            not in {
                "exact-rusage-self-and-reaped-children-before-validation-v1",
                "response-boundary-plus-post-response-reaped-lifecycle-v2",
            }
        ):
            raise ValueError("external worker requires exact rusage boundary evidence")
        request_cpu_snapshots = (
            request_snapshots
            if self.response_boundary_snapshot is not None
            else self.snapshots
        )
        baselines: dict[tuple[int, int], int] = {}
        maxima: dict[tuple[int, int], int] = {}
        for snapshot in request_cpu_snapshots:
            for member in snapshot.members:
                identity = (
                    member.identity.pid,
                    member.identity.create_time_ns,
                )
                cumulative = member.user_cpu_ns + member.system_cpu_ns
                if identity not in baselines:
                    baselines[identity] = (
                        cumulative
                        if snapshot.observed_monotonic_ns
                        <= self.request_started_monotonic_ns
                        else 0
                    )
                maxima[identity] = max(maxima.get(identity, cumulative), cumulative)
        request_cpu = sum(
            max(0, maximum - baselines[identity])
            for identity, maximum in maxima.items()
        )
        if self.maximum_observed_process_cpu_ns != request_cpu:
            raise ValueError("request process CPU deltas must be recomputed")
        if self.response_boundary_snapshot is not None:
            baseline_cpu = {
                (member.identity.pid, member.identity.create_time_ns): (
                    member.user_cpu_ns + member.system_cpu_ns
                )
                for member in self.snapshots[0].members[1:]
            }
            frozen_descendant_cpu = sum(
                max(
                    0,
                    member.user_cpu_ns
                    + member.system_cpu_ns
                    - baseline_cpu.get(
                        (member.identity.pid, member.identity.create_time_ns),
                        0,
                    ),
                )
                for member in self.response_boundary_snapshot.members[1:]
            )
            if self.conservative_frozen_response_boundary_descendant_cpu_ns != (
                frozen_descendant_cpu
            ):
                raise ValueError("frozen response descendant CPU differs")
            response_descendant_cumulative = sum(
                member.user_cpu_ns + member.system_cpu_ns
                for member in self.response_boundary_snapshot.members[1:]
            )
            baseline_descendant_cumulative = sum(
                member.user_cpu_ns + member.system_cpu_ns
                for member in self.snapshots[0].members[1:]
            )
            if (
                self.response_boundary_descendant_cumulative_cpu_ns
                != response_descendant_cumulative
                or self.baseline_descendant_cumulative_cpu_ns
                != baseline_descendant_cumulative
                or self.lifecycle_exact_worker_self_cpu_ns is None
                or self.lifecycle_reaped_children_cpu_ns is None
                or self.post_response_lifecycle_cpu_ns is None
            ):
                raise ValueError("v2 lifecycle CPU components are incomplete")
            root_post_response = (
                self.lifecycle_exact_worker_self_cpu_ns - self.exact_worker_self_cpu_ns
            )
            child_post_response = (
                self.lifecycle_reaped_children_cpu_ns
                - self.exact_reaped_children_cpu_ns
                - response_descendant_cumulative
            )
            if (
                root_post_response < 0
                or child_post_response < 0
                or self.post_response_lifecycle_cpu_ns
                != root_post_response + child_post_response
            ):
                raise ValueError("v2 post-response lifecycle CPU differs")
        elif (
            self.conservative_frozen_response_boundary_descendant_cpu_ns != 0
            or self.post_response_lifecycle_cpu_ns is not None
            or self.baseline_descendant_cumulative_cpu_ns is not None
            or self.response_boundary_descendant_cumulative_cpu_ns is not None
            or self.lifecycle_exact_worker_self_cpu_ns is not None
            or self.lifecycle_reaped_children_cpu_ns is not None
        ):
            raise ValueError("v1 process tree cannot claim v2 lifecycle CPU")
        return self


class PartialProcessTreeEvidence(ContractModel):
    schema_id: Literal["phase-latency-partial-process-tree-v1"]
    request_started_monotonic_ns: NonNegativeInt
    observation_ended_monotonic_ns: NonNegativeInt
    snapshots: Annotated[
        tuple[ProcessTreeSnapshot, ...],
        Field(min_length=1, max_length=MAXIMUM_PROCESS_SNAPSHOTS),
    ]
    peak_sampled_total_rss_bytes: PositiveInt
    measurement_disposition: Literal[
        "incomplete-worker-terminated-before-response-boundary-v1"
    ]
    failure_code: FailureCode
    cleanup_disposition: Literal["external_worker_group_reaped"]

    @model_validator(mode="after")
    def validate_partial_process_evidence(self) -> PartialProcessTreeEvidence:
        timestamps = tuple(item.observed_monotonic_ns for item in self.snapshots)
        if any(current <= previous for previous, current in pairwise(timestamps)):
            raise ValueError("partial process timestamps must increase strictly")
        if self.observation_ended_monotonic_ns < timestamps[-1]:
            raise ValueError("partial process observation boundary differs")
        if self.peak_sampled_total_rss_bytes != max(
            item.total_rss_bytes for item in self.snapshots
        ):
            raise ValueError("partial sampled RSS peak must be recomputed")
        return self


class AttemptSlot(ContractModel):
    slot_id: StableId
    order_index: PositiveInt
    case_id: StableId
    pair_index: PositiveInt
    system: SystemName

    @field_validator("slot_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return _require_stable_id(value, label=info.field_name)


class WorkerExecutionEvidence(ContractModel):
    """Bounded parser-worker result consumed by the external controller."""

    schema_id: Literal[
        "phase-latency-external-worker-v1",
        "phase-latency-external-worker-v2",
    ]
    measurement_role: Literal[
        "authoritative_uninstrumented",
        "diagnostic_instrumented",
    ]
    telemetry_source: Literal["none", "external_test_instrumentation"]
    source: SourceIdentity
    configuration: ConfigurationIdentity
    candidate_code_sha256: Sha256
    dependency_lock_sha256: Sha256
    environment_sha256: Sha256
    exact_supplied_environment_sha256: Sha256 | None = None
    environment_manifest: EnvironmentIdentityEvidence | None = None
    model_artifacts_sha256: Sha256
    post_request_candidate_code_sha256: Sha256
    post_request_dependency_lock_sha256: Sha256
    post_request_environment_sha256: Sha256
    post_request_model_artifacts_sha256: Sha256
    status: AttemptStatus
    started_at_utc: datetime
    completed_at_utc: datetime
    request_started_monotonic_ns: NonNegativeInt
    request_ended_monotonic_ns: NonNegativeInt
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None
    cache_hit: Literal[False]
    evidence_complete: StrictBool
    output: OutputIdentity | None
    error_response: ErrorResponseIdentity | None
    failure: FailureRecord | None
    stage_trace: StageTrace
    cache_state: CacheStateEvidence
    network_isolation: NetworkIsolationEvidence
    instrumentation_manifest: InstrumentationManifest | None
    response_boundary_protocol: Literal[
        "controller-terminal-sample-before-post-response-validation-v1",
        "controller-response-freeze-and-post-response-resource-closure-v2",
    ]
    response_boundary_signal_monotonic_ns: NonNegativeInt
    response_boundary_ack_monotonic_ns: NonNegativeInt
    resource_closure_signal_monotonic_ns: NonNegativeInt | None = None
    resource_closure_ack_monotonic_ns: NonNegativeInt | None = None
    resource_tracker_disposition: ResourceTrackerDisposition | None = None
    resource_boundary: WorkerResourceBoundaryEvidence
    post_response_validation_duration_ns: NonNegativeInt
    worker_hwm_bytes_at_response_boundary: PositiveInt
    worker_hwm_bytes_at_resource_closure: PositiveInt | None = None

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def validate_worker_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _require_utc_datetime(value, label=info.field_name)

    @model_validator(mode="after")
    def validate_worker_result(self) -> WorkerExecutionEvidence:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("worker completion cannot precede start")
        if self.request_ended_monotonic_ns <= self.request_started_monotonic_ns:
            raise ValueError("worker request interval must be positive")
        if not (
            self.request_ended_monotonic_ns
            <= self.response_boundary_signal_monotonic_ns
            <= self.response_boundary_ack_monotonic_ns
        ):
            raise ValueError("worker response-boundary handshake is invalid")
        if self.response_boundary_protocol == (
            "controller-response-freeze-and-post-response-resource-closure-v2"
        ):
            if (
                self.resource_closure_signal_monotonic_ns is None
                or self.resource_closure_ack_monotonic_ns is None
                or self.resource_tracker_disposition is None
                or self.worker_hwm_bytes_at_resource_closure is None
                or self.resource_boundary.basis
                != "response-boundary-plus-post-response-reaped-lifecycle-v2"
                or self.network_isolation.policy
                != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                or self.exact_supplied_environment_sha256 is None
            ):
                raise ValueError("v2 worker resource closure evidence is incomplete")
            if self.schema_id != "phase-latency-external-worker-v2":
                raise ValueError("v2 worker protocol requires the v2 schema")
            if not (
                self.response_boundary_ack_monotonic_ns
                <= self.resource_closure_signal_monotonic_ns
                <= self.resource_closure_ack_monotonic_ns
            ):
                raise ValueError("worker resource closure handshake is invalid")
            if self.resource_tracker_disposition.disposition != (
                "absent_at_response_boundary"
            ):
                if (
                    int(
                        self.resource_tracker_disposition.cleanup_started_monotonic_ns
                        or 0
                    )
                    < self.response_boundary_ack_monotonic_ns
                ):
                    raise ValueError(
                        "resource tracker cleanup entered measured latency"
                    )
                if (
                    int(
                        self.resource_tracker_disposition.cleanup_ended_monotonic_ns
                        or 0
                    )
                    > self.resource_closure_signal_monotonic_ns
                ):
                    raise ValueError(
                        "resource tracker cleanup ended after the closure signal"
                    )
        elif any(
            value is not None
            for value in (
                self.resource_closure_signal_monotonic_ns,
                self.resource_closure_ack_monotonic_ns,
                self.resource_tracker_disposition,
                self.worker_hwm_bytes_at_resource_closure,
                self.exact_supplied_environment_sha256,
            )
        ):
            raise ValueError("v1 worker cannot claim v2 resource closure evidence")
        elif self.schema_id != "phase-latency-external-worker-v1":
            raise ValueError("v1 worker protocol requires the v1 schema")
        root = self.stage_trace.spans[0]
        if (
            root.started_monotonic_ns != self.request_started_monotonic_ns
            or root.ended_monotonic_ns != self.request_ended_monotonic_ns
        ):
            raise ValueError("worker trace must bind its absolute request interval")
        if self.stage_trace.status.value != self.status.value:
            raise ValueError("worker trace status must bind worker outcome")
        if self.measurement_role == "authoritative_uninstrumented":
            if (
                self.telemetry_source != "none"
                or self.instrumentation_manifest is not None
                or len(self.stage_trace.spans) != 1
                or self.stage_trace.collector_started_monotonic_ns is not None
            ):
                raise ValueError("authoritative worker must remain uninstrumented")
        elif (
            self.telemetry_source != "external_test_instrumentation"
            or self.instrumentation_manifest is None
            or len(self.stage_trace.spans) <= 1
            or self.stage_trace.collector_started_monotonic_ns is None
        ):
            raise ValueError("diagnostic worker requires external observer evidence")
        if self.status is AttemptStatus.SUCCESS:
            if (
                self.http_status != 200
                or self.output is None
                or self.error_response is not None
                or self.failure is not None
                or self.evidence_complete is not True
            ):
                raise ValueError("successful worker result is incomplete")
        elif self.failure is None or self.output is not None:
            raise ValueError("failed worker result must retain closed failure data")
        if self.error_response is not None and (
            self.http_status is None or self.http_status < 400
        ):
            raise ValueError("error response evidence requires an HTTP error status")
        if self.configuration.runtime_sha256 != self.environment_sha256:
            raise ValueError("worker configuration/runtime identity differs")
        if (
            self.environment_manifest is None
            or self.environment_manifest.manifest_sha256 != self.environment_sha256
        ):
            raise ValueError("worker environment manifest identity differs")
        if self.configuration.model_artifacts_sha256 != self.model_artifacts_sha256:
            raise ValueError("worker configuration/model identity differs")
        if (
            self.candidate_code_sha256 != self.post_request_candidate_code_sha256
            or self.dependency_lock_sha256 != self.post_request_dependency_lock_sha256
            or self.environment_sha256 != self.post_request_environment_sha256
            or self.model_artifacts_sha256 != self.post_request_model_artifacts_sha256
        ):
            raise ValueError("worker execution identity changed during request")
        if (
            self.status is AttemptStatus.SUCCESS
            and self.network_isolation.denied_network_attempt_count
        ):
            raise ValueError("successful worker attempted network egress")
        expected_worker_hwm = (
            self.worker_hwm_bytes_at_resource_closure
            if self.response_boundary_protocol
            == "controller-response-freeze-and-post-response-resource-closure-v2"
            else self.worker_hwm_bytes_at_response_boundary
        )
        if self.resource_boundary.worker_process_lifetime_hwm_bytes != (
            expected_worker_hwm
        ):
            raise ValueError("worker HWM/resource boundary differs")
        if (
            self.resource_boundary.response_boundary_worker_process_lifetime_hwm_bytes
            is not None
            and self.resource_boundary.response_boundary_worker_process_lifetime_hwm_bytes
            != self.worker_hwm_bytes_at_response_boundary
        ):
            raise ValueError("response-boundary worker HWM differs")
        if self.resource_boundary.basis == (
            "response-boundary-plus-post-response-reaped-lifecycle-v2"
        ):
            cpu_ns = sum(
                int(value or 0)
                for value in (
                    self.resource_boundary.response_boundary_worker_self_user_cpu_delta_ns,
                    self.resource_boundary.response_boundary_worker_self_system_cpu_delta_ns,
                    self.resource_boundary.response_boundary_reaped_children_user_cpu_delta_ns,
                    self.resource_boundary.response_boundary_reaped_children_system_cpu_delta_ns,
                )
            )
        else:
            cpu_ns = sum(
                (
                    self.resource_boundary.worker_self_user_cpu_delta_ns,
                    self.resource_boundary.worker_self_system_cpu_delta_ns,
                    self.resource_boundary.reaped_children_user_cpu_delta_ns,
                    self.resource_boundary.reaped_children_system_cpu_delta_ns,
                )
            )
        wall_ns = self.request_ended_monotonic_ns - self.request_started_monotonic_ns
        if cpu_ns > wall_ns * self.environment_manifest.logical_cpu_count:
            raise ValueError("request CPU exceeds wall-time logical-CPU bound")
        cold = self.configuration.worker_lifecycle is (
            WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
        )
        if cold != (self.cache_state.profile == "request_cold_after_app_startup"):
            raise ValueError("worker lifecycle/cache proof differs")
        if self.configuration.content_result_cache_proof_sha256 != (
            self.cache_state.content_result_cache_proof_sha256
        ):
            raise ValueError("configuration cache proof differs from observation")
        if (
            self.cache_state.prewarm_evidence is not None
            and self.cache_state.prewarm_evidence.source.sha256 == self.source.sha256
        ):
            raise ValueError("prewarm source must differ from measured source bytes")
        return self


class LatencyAttempt(ContractModel):
    attempt_id: StableId
    slot_id: StableId
    order_index: PositiveInt
    case_id: StableId
    pair_index: PositiveInt
    system: SystemName
    source: SourceIdentity
    source_binding: SourceBinding
    configuration: ConfigurationIdentity
    candidate_code_sha256: Sha256 | None = None
    dependency_lock_sha256: Sha256 | None = None
    environment_sha256: Sha256 | None = None
    model_artifacts_sha256: Sha256 | None = None
    status: AttemptStatus
    started_at_utc: datetime
    completed_at_utc: datetime
    total_latency_ns: PositiveInt
    cache_hit: StrictBool
    evidence_complete: StrictBool
    output: OutputIdentity | None = None
    failure: FailureRecord | None = None
    worker_fatal_envelope: WorkerFatalEnvelope | None = None
    diagnostic_failure: FailureRecord | None = None
    failure_stage_parity_policy: (
        Literal["authoritative-root-versus-diagnostic-first-failed-stage-v1"] | None
    ) = None
    error_response: ErrorResponseIdentity | None = None
    stage_trace: StageTrace | None = None
    process_tree: ProcessTreeMetrics | None = None
    diagnostic_process_tree: ProcessTreeMetrics | None = None
    partial_process_tree: PartialProcessTreeEvidence | None = None
    diagnostic_total_latency_ns: PositiveInt | None = None
    diagnostic_output: OutputIdentity | None = None
    diagnostic_error_response: ErrorResponseIdentity | None = None
    twin_order: (
        Literal[
            "authoritative_then_diagnostic",
            "diagnostic_then_authoritative",
        ]
        | None
    ) = None
    observer_delta_ns: Annotated[int, Field(strict=True)] | None = None
    observer_adjustment_applied: Literal[False] | None = None
    instrumentation_manifest: InstrumentationManifest | None = None
    authoritative_cache_state: CacheStateEvidence | None = None
    diagnostic_cache_state: CacheStateEvidence | None = None
    authoritative_network_isolation: NetworkIsolationEvidence | None = None
    diagnostic_network_isolation: NetworkIsolationEvidence | None = None
    authoritative_post_response_validation_duration_ns: NonNegativeInt | None = None
    diagnostic_post_response_validation_duration_ns: NonNegativeInt | None = None
    authoritative_response_boundary_protocol: (
        Literal[
            "controller-terminal-sample-before-post-response-validation-v1",
            "controller-response-freeze-and-post-response-resource-closure-v2",
        ]
        | None
    ) = None
    diagnostic_response_boundary_protocol: (
        Literal[
            "controller-terminal-sample-before-post-response-validation-v1",
            "controller-response-freeze-and-post-response-resource-closure-v2",
        ]
        | None
    ) = None
    authoritative_watchdog: WorkerWatchdogEvidence | None = None
    diagnostic_watchdog: WorkerWatchdogEvidence | None = None
    authoritative_resource_tracker_disposition: ResourceTrackerDisposition | None = None
    diagnostic_resource_tracker_disposition: ResourceTrackerDisposition | None = None
    provider_total_latency: ProviderTotalLatencyEvidence | None = None
    legacy_v1_authorization: Literal["synthetic-control-only-v1"] | None = None

    @field_validator("attempt_id", "slot_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info: Any) -> str:
        return _require_stable_id(value, label=info.field_name)

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def validate_attempt_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _require_utc_datetime(value, label=info.field_name)

    @model_validator(mode="after")
    def validate_attempt_state(self) -> LatencyAttempt:
        def cache_state_parity(
            left: CacheStateEvidence | None,
            right: CacheStateEvidence | None,
        ) -> bool:
            if left is None or right is None:
                return left is right
            if left.model_dump(exclude={"prewarm_evidence"}) != right.model_dump(
                exclude={"prewarm_evidence"}
            ):
                return False
            if left.prewarm_evidence is None or right.prewarm_evidence is None:
                return left.prewarm_evidence is right.prewarm_evidence
            return (
                left.prewarm_evidence.source == right.prewarm_evidence.source
                and left.prewarm_evidence.output.semantic_sha256
                == right.prewarm_evidence.output.semantic_sha256
                and left.prewarm_evidence.output.validation
                == right.prewarm_evidence.output.validation
            )

        if self.completed_at_utc <= self.started_at_utc:
            raise ValueError("attempt must retain a positive UTC execution interval")
        elapsed_ns = int(
            (self.completed_at_utc - self.started_at_utc).total_seconds()
            * 1_000_000_000
        )
        if elapsed_ns > 900_000_000_000:
            raise ValueError("attempt UTC execution interval exceeds 15 minutes")
        if self.source.case_id != self.case_id:
            raise ValueError("attempt case must match source identity")
        if self.configuration.system is not self.system:
            raise ValueError("attempt system must match configuration")
        if self.cache_hit is not False:
            raise ValueError("content/result cache hits are forbidden")
        if self.status is AttemptStatus.SUCCESS:
            if self.output is None or self.failure is not None:
                raise ValueError("successful attempt requires output and no failure")
        elif self.failure is None:
            raise ValueError("non-success attempt must retain its failure")
        if self.worker_fatal_envelope is not None and (
            self.system is not SystemName.CANDIDATE
            or self.status is AttemptStatus.SUCCESS
            or self.evidence_complete is not False
            or self.failure is None
            or self.failure.exception_type
            not in {FailureType.WORKER_CRASH, FailureType.WORKER_PROTOCOL_ERROR}
        ):
            raise ValueError(
                "worker fatal envelope is inconsistent with attempt failure"
            )

        if self.system is SystemName.CANDIDATE:
            if self.total_latency_ns > elapsed_ns:
                raise ValueError("authoritative latency exceeds attempt UTC interval")
            if any(
                value is None
                for value in (
                    self.candidate_code_sha256,
                    self.dependency_lock_sha256,
                    self.environment_sha256,
                    self.model_artifacts_sha256,
                )
            ):
                raise ValueError("candidate attempt requires execution identities")
            if (
                self.configuration.runtime_sha256 != self.environment_sha256
                or self.configuration.model_artifacts_sha256
                != self.model_artifacts_sha256
            ):
                raise ValueError("candidate attempt/configuration identity differs")
            if self.instrumentation_manifest is not None:
                if (
                    self.instrumentation_manifest.runtime_sha256
                    != self.environment_sha256
                    or self.instrumentation_manifest.dependency_lock_sha256
                    != self.dependency_lock_sha256
                ):
                    raise ValueError("observer manifest execution identity differs")
                policies = {
                    item.policy_id: item
                    for item in self.configuration.stage_cardinality_policies
                }
                for target in self.instrumentation_manifest.targets:
                    if target.invocation_count == 0:
                        continue
                    policy = policies.get(target.cardinality_policy_id)
                    if (
                        policy is None
                        or target.target_id not in policy.target_ids
                        or target.stage is not policy.stage
                    ):
                        raise ValueError("observer target/cardinality policy differs")
            if self.source_binding is not SourceBinding.WORKSPACE_BYTES:
                raise ValueError("candidate must bind direct workspace bytes")
            if self.stage_trace is None:
                raise ValueError("candidate attempt requires a complete-boundary trace")
            if self.status is AttemptStatus.SUCCESS and (
                self.process_tree is None or self.evidence_complete is not True
            ):
                raise ValueError(
                    "successful candidate requires complete process evidence"
                )
            if (
                self.status is AttemptStatus.SUCCESS
                and self.partial_process_tree is not None
            ):
                raise ValueError(
                    "successful candidate cannot retain partial process evidence"
                )
            if self.process_tree is not None and (
                self.process_tree.request_ended_monotonic_ns
                - self.process_tree.request_started_monotonic_ns
                != self.total_latency_ns
            ):
                raise ValueError(
                    "candidate process samples must bind authoritative total"
                )
            if self.provider_total_latency is not None:
                raise ValueError("candidate cannot claim provider evidence")
            expected_stage_status = StageStatus(self.status.value)
            if self.stage_trace.status is not expected_stage_status:
                raise ValueError("candidate attempt and trace statuses must match")
            if self.output is not None and self.output.validation == (
                "provider_retained_artifact"
            ):
                raise ValueError(
                    "candidate output must be validated at the HTTP boundary"
                )
            v2_network = (
                self.authoritative_network_isolation is not None
                and self.authoritative_network_isolation.policy
                == "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
            )
            if (
                self.status is AttemptStatus.SUCCESS
                and self.legacy_v1_authorization is None
                and not v2_network
            ):
                raise ValueError("nonsynthetic candidate requires v2 isolation")
            if v2_network and self.legacy_v1_authorization is not None:
                raise ValueError("v2 candidate cannot claim legacy authorization")
            if (
                self.status is AttemptStatus.SUCCESS
                and not v2_network
                and self.legacy_v1_authorization != "synthetic-control-only-v1"
            ):
                raise ValueError("v1 candidate requires explicit legacy authorization")
            if v2_network:
                if (
                    self.diagnostic_network_isolation is None
                    or self.diagnostic_network_isolation.policy
                    != "sanitized-offline-env-python-deny-and-os-process-tree-deny-v2"
                    or self.process_tree is None
                    or self.diagnostic_process_tree is None
                    or self.authoritative_resource_tracker_disposition is None
                    or self.diagnostic_resource_tracker_disposition is None
                    or self.authoritative_response_boundary_protocol
                    != "controller-response-freeze-and-post-response-resource-closure-v2"
                    or self.diagnostic_response_boundary_protocol
                    != "controller-response-freeze-and-post-response-resource-closure-v2"
                    or self.authoritative_network_isolation.python_guard_restore_disposition
                    != "controller-verified-worker-zero-exit"
                    or self.diagnostic_network_isolation.python_guard_restore_disposition
                    != "controller-verified-worker-zero-exit"
                ):
                    raise ValueError(
                        "v2 twin resource lifecycle evidence is incomplete"
                    )
                for tree, disposition in (
                    (
                        self.process_tree,
                        self.authoritative_resource_tracker_disposition,
                    ),
                    (
                        self.diagnostic_process_tree,
                        self.diagnostic_resource_tracker_disposition,
                    ),
                ):
                    if (
                        tree.resource_boundary_basis
                        != "response-boundary-plus-post-response-reaped-lifecycle-v2"
                        or disposition.controller_no_relaunch_through_zero_exit_verified
                        is not True
                    ):
                        raise ValueError("v2 controller lifecycle proof is incomplete")
                    response = tree.response_boundary_snapshot
                    if response is None:
                        raise ValueError("v2 response resource boundary is absent")
                    descendants = tuple(
                        member.identity for member in response.members[1:]
                    )
                    baseline_descendants = tuple(
                        member.identity for member in tree.snapshots[0].members[1:]
                    )
                    cold_lifecycle = self.configuration.worker_lifecycle is (
                        WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
                    )
                    if cold_lifecycle:
                        if baseline_descendants or disposition.disposition == (
                            "preexisting_at_baseline_reaped_after_response"
                        ):
                            raise ValueError("cold lifecycle tracker baseline differs")
                    elif (
                        disposition.disposition
                        != "preexisting_at_baseline_reaped_after_response"
                        or disposition.identity is None
                        or baseline_descendants != (disposition.identity,)
                    ):
                        raise ValueError("prewarmed lifecycle tracker baseline differs")
                    if disposition.disposition == "absent_at_response_boundary":
                        if descendants or baseline_descendants:
                            raise ValueError("absent tracker retained a descendant")
                    elif disposition.identity is None or descendants != (
                        disposition.identity,
                    ):
                        raise ValueError("tracker identity/resource boundary differs")
                    elif disposition.tracker_fd != tree.resource_tracker_command_fd:
                        raise ValueError("tracker command FD/resource boundary differs")
                    elif disposition.worker_write_fd != (
                        tree.resource_tracker_worker_write_fd
                    ):
                        raise ValueError("tracker worker FD/resource boundary differs")
                    elif disposition.disposition == (
                        "started_during_request_reaped_after_response"
                    ):
                        if baseline_descendants:
                            raise ValueError("request tracker existed at cold baseline")
                    elif (
                        disposition.disposition
                        == "preexisting_at_baseline_reaped_after_response"
                        and baseline_descendants != (disposition.identity,)
                    ):
                        raise ValueError("prewarm tracker baseline identity differs")
                if (
                    self.authoritative_resource_tracker_disposition.disposition
                    != self.diagnostic_resource_tracker_disposition.disposition
                ):
                    raise ValueError(
                        "authoritative/diagnostic tracker lifecycle differs"
                    )
            elif any(
                value is not None
                for value in (
                    self.authoritative_resource_tracker_disposition,
                    self.diagnostic_resource_tracker_disposition,
                )
            ):
                raise ValueError("v1 attempt cannot claim v2 tracker lifecycle")
            if self.status is AttemptStatus.SUCCESS:
                twin_fields = (
                    self.diagnostic_total_latency_ns,
                    self.diagnostic_process_tree,
                    self.diagnostic_output,
                    self.twin_order,
                    self.observer_delta_ns,
                    self.observer_adjustment_applied,
                    self.instrumentation_manifest,
                    self.authoritative_cache_state,
                    self.diagnostic_cache_state,
                    self.authoritative_network_isolation,
                    self.diagnostic_network_isolation,
                    self.authoritative_post_response_validation_duration_ns,
                    self.diagnostic_post_response_validation_duration_ns,
                    self.authoritative_response_boundary_protocol,
                    self.diagnostic_response_boundary_protocol,
                    self.authoritative_watchdog,
                    self.diagnostic_watchdog,
                )
                if any(value is None for value in twin_fields):
                    raise ValueError(
                        "successful candidate requires complete twin evidence"
                    )
                if self.stage_trace.authoritative_total_ns != (
                    self.diagnostic_total_latency_ns
                ):
                    raise ValueError("diagnostic trace must bind diagnostic total")
                if (
                    self.process_tree is None
                    or self.diagnostic_process_tree is None
                    or self.process_tree.resource_boundary_complete is not True
                    or self.diagnostic_process_tree.resource_boundary_complete
                    is not True
                ):
                    raise ValueError("successful twin resource boundary is incomplete")
                if (
                    self.diagnostic_process_tree.request_ended_monotonic_ns
                    - self.diagnostic_process_tree.request_started_monotonic_ns
                    != self.diagnostic_total_latency_ns
                ):
                    raise ValueError("diagnostic process evidence must bind its total")
                if self.observer_delta_ns != (
                    int(self.diagnostic_total_latency_ns or 0) - self.total_latency_ns
                ):
                    raise ValueError(
                        "observer delta must be recomputed without adjustment"
                    )
                if self.observer_adjustment_applied is not False:
                    raise ValueError(
                        "observer overhead cannot adjust authoritative latency"
                    )
                if (
                    self.output is None
                    or self.diagnostic_output is None
                    or (
                        self.output.semantic_sha256
                        != self.diagnostic_output.semantic_sha256
                        or self.output.validation != self.diagnostic_output.validation
                        or self.output.media_type != self.diagnostic_output.media_type
                    )
                ):
                    raise ValueError(
                        "authoritative/diagnostic semantic output parity differs"
                    )
                if (
                    self.error_response is not None
                    or self.diagnostic_error_response is not None
                    or self.diagnostic_failure is not None
                    or self.failure_stage_parity_policy is not None
                ):
                    raise ValueError("successful twin cannot retain an error response")
                if not cache_state_parity(
                    self.authoritative_cache_state, self.diagnostic_cache_state
                ):
                    raise ValueError("authoritative/diagnostic cache state differs")
                if (
                    self.authoritative_network_isolation
                    != self.diagnostic_network_isolation
                    or self.authoritative_network_isolation is None
                    or self.authoritative_network_isolation.hosted_calls_completed != 0
                ):
                    raise ValueError(
                        "authoritative/diagnostic network isolation differs"
                    )
                if self.authoritative_response_boundary_protocol != (
                    self.diagnostic_response_boundary_protocol
                ):
                    raise ValueError(
                        "authoritative/diagnostic boundary protocol differs"
                    )
                if self.authoritative_watchdog != self.diagnostic_watchdog:
                    raise ValueError(
                        "authoritative/diagnostic watchdog evidence differs"
                    )
                get_pipeline_policy = next(
                    (
                        item
                        for item in self.configuration.stage_cardinality_policies
                        if item.stage is StageName.DOCLING_PIPELINE_INITIALIZATION
                    ),
                    None,
                )
                if (
                    get_pipeline_policy is not None
                    and get_pipeline_policy.maximum_calls > 0
                ):
                    disposition = (
                        self.instrumentation_manifest.docling_get_pipeline_disposition
                    )
                    expected_disposition = (
                        "initialized"
                        if self.configuration.worker_lifecycle
                        is WorkerLifecycle.FRESH_PROCESS_REQUEST_COLD
                        else "reused"
                    )
                    if disposition != expected_disposition:
                        raise ValueError(
                            "Docling get-or-initialize disposition differs"
                        )
                counts: dict[StageName, int] = {}
                for span in self.stage_trace.spans[1:]:
                    counts[span.name] = counts.get(span.name, 0) + 1
                policies = {
                    item.stage: item
                    for item in self.configuration.stage_cardinality_policies
                }
                if set(counts) - set(policies):
                    raise ValueError("diagnostic trace contains an undeclared stage")
                for stage, policy in policies.items():
                    count = counts.get(stage, 0)
                    if not policy.minimum_calls <= count <= policy.maximum_calls:
                        raise ValueError(
                            "successful candidate stage cardinality policy differs"
                        )
                    if not policy.allow_degraded_on_success and any(
                        span.status is not StageStatus.SUCCESS
                        for span in self.stage_trace.spans[1:]
                        if span.name is stage
                    ):
                        raise ValueError("core diagnostic stage was degraded")
                manifest_counts: dict[str, int] = {}
                for target in self.instrumentation_manifest.targets:
                    manifest_counts[target.cardinality_policy_id] = (
                        manifest_counts.get(target.cardinality_policy_id, 0)
                        + target.invocation_count
                    )
                for policy in policies.values():
                    if manifest_counts.get(policy.policy_id, 0) != counts.get(
                        policy.stage, 0
                    ):
                        raise ValueError("manifest invocation count differs from trace")
            elif self.instrumentation_manifest is not None:
                # Failed twin evidence may retain the diagnostic manifest, but
                # it must never be mistaken for a successful comparator.
                if self.observer_adjustment_applied is not False:
                    raise ValueError("failed twin cannot apply observer adjustment")
                retained_twin_fields = (
                    self.diagnostic_total_latency_ns,
                    self.diagnostic_process_tree,
                    self.twin_order,
                    self.observer_delta_ns,
                    self.authoritative_cache_state,
                    self.diagnostic_cache_state,
                    self.authoritative_network_isolation,
                    self.diagnostic_network_isolation,
                    self.authoritative_post_response_validation_duration_ns,
                    self.diagnostic_post_response_validation_duration_ns,
                    self.authoritative_response_boundary_protocol,
                    self.diagnostic_response_boundary_protocol,
                    self.authoritative_watchdog,
                    self.diagnostic_watchdog,
                )
                if any(value is None for value in retained_twin_fields):
                    raise ValueError("failed twin evidence is incomplete")
                if (
                    self.process_tree is None
                    or self.diagnostic_process_tree is None
                    or self.process_tree.resource_boundary_complete is not True
                    or self.diagnostic_process_tree.resource_boundary_complete
                    is not True
                ):
                    raise ValueError("failed twin resource boundary is incomplete")
                if (
                    self.diagnostic_process_tree.request_ended_monotonic_ns
                    - self.diagnostic_process_tree.request_started_monotonic_ns
                    != self.diagnostic_total_latency_ns
                ):
                    raise ValueError("failed diagnostic process evidence differs")
                if (
                    self.diagnostic_failure is None
                    or self.failure_stage_parity_policy
                    != "authoritative-root-versus-diagnostic-first-failed-stage-v1"
                    or self.failure is None
                    or self.failure.code != self.diagnostic_failure.code
                    or self.failure.exception_type
                    is not self.diagnostic_failure.exception_type
                ):
                    raise ValueError("failed twin outcome parity differs")
                if self.stage_trace.authoritative_total_ns != (
                    self.diagnostic_total_latency_ns
                ):
                    raise ValueError("failed diagnostic trace must bind its total")
                if self.observer_delta_ns != (
                    int(self.diagnostic_total_latency_ns or 0) - self.total_latency_ns
                ):
                    raise ValueError("failed observer delta must be recomputed")
                if not cache_state_parity(
                    self.authoritative_cache_state, self.diagnostic_cache_state
                ):
                    raise ValueError("failed twin cache state differs")
                if (
                    self.authoritative_network_isolation
                    != self.diagnostic_network_isolation
                ):
                    raise ValueError("failed twin network isolation differs")
                if self.authoritative_response_boundary_protocol != (
                    self.diagnostic_response_boundary_protocol
                ):
                    raise ValueError("failed twin boundary protocol differs")
                if self.authoritative_watchdog != self.diagnostic_watchdog:
                    raise ValueError("failed twin watchdog evidence differs")
                if (self.error_response is None) != (
                    self.diagnostic_error_response is None
                ):
                    raise ValueError("failed twin error-response presence differs")
                if self.error_response is not None and (
                    self.diagnostic_error_response is None
                    or self.error_response != self.diagnostic_error_response
                ):
                    raise ValueError("failed twin error-response parity differs")
        else:
            if self.legacy_v1_authorization is not None:
                raise ValueError("provider cannot claim local legacy authorization")
            if self.source_binding is not SourceBinding.EXACT_BYTE_UPLOAD:
                raise ValueError("LlamaParse must use an exact-byte upload")
            if self.stage_trace is not None or self.process_tree is not None:
                raise ValueError(
                    "provider attempt cannot invent local stage or RSS data"
                )
            if any(
                value is not None
                for value in (
                    self.error_response,
                    self.diagnostic_failure,
                    self.failure_stage_parity_policy,
                    self.diagnostic_total_latency_ns,
                    self.diagnostic_process_tree,
                    self.diagnostic_output,
                    self.diagnostic_error_response,
                    self.candidate_code_sha256,
                    self.dependency_lock_sha256,
                    self.environment_sha256,
                    self.model_artifacts_sha256,
                    self.twin_order,
                    self.observer_delta_ns,
                    self.observer_adjustment_applied,
                    self.instrumentation_manifest,
                    self.authoritative_cache_state,
                    self.diagnostic_cache_state,
                    self.authoritative_network_isolation,
                    self.diagnostic_network_isolation,
                    self.authoritative_post_response_validation_duration_ns,
                    self.diagnostic_post_response_validation_duration_ns,
                    self.authoritative_response_boundary_protocol,
                    self.diagnostic_response_boundary_protocol,
                    self.authoritative_watchdog,
                    self.diagnostic_watchdog,
                    self.authoritative_resource_tracker_disposition,
                    self.diagnostic_resource_tracker_disposition,
                )
            ):
                raise ValueError("provider attempt cannot claim local twin evidence")
            if self.status is AttemptStatus.SUCCESS:
                if self.evidence_complete is not True:
                    raise ValueError(
                        "successful provider attempt requires complete evidence"
                    )
                if self.provider_total_latency is None:
                    raise ValueError(
                        "successful provider attempt requires UI/job evidence"
                    )
                if (
                    self.provider_total_latency.normalized_display_ns
                    != self.total_latency_ns
                ):
                    raise ValueError(
                        "provider Total Latency must equal its normalized UI display"
                    )
                if self.provider_total_latency.observed_at_utc < self.completed_at_utc:
                    raise ValueError(
                        "provider UI capture cannot precede attempt completion"
                    )
                if (
                    self.output is None
                    or self.output.validation != "provider_retained_artifact"
                ):
                    raise ValueError("provider output must be retained and verified")
            elif self.provider_total_latency is not None:
                raise ValueError(
                    "failed provider attempt cannot claim completed UI evidence"
                )
        return self


class LatencyCampaign(ContractModel):
    schema_version: Literal["1.0"]
    schema_id: Literal["phase-latency-campaign-v1"]
    campaign_id: StableId
    scope: CampaignScope
    candidate_code_sha256: Sha256
    dependency_lock_sha256: Sha256
    environment_sha256: Sha256
    environment_manifest: EnvironmentIdentityEvidence | None = None
    model_artifacts_sha256: Sha256
    corpus_registry: ArtifactIdentity | None = None
    phase03_oracle_artifact: ArtifactIdentity | None = None
    source_registry_sha256: Sha256 | None = None
    provider_evidence_registry: ArtifactIdentity | None = None
    authorized_hosted_credit_limit: Literal[1500]
    hosted_credits_used: NonNegativeInt
    minimum_samples_per_case_per_system: Annotated[
        int,
        Field(strict=True, ge=MINIMUM_PAIRED_SAMPLES, le=50),
    ]
    plan: Annotated[
        tuple[AttemptSlot, ...],
        Field(
            min_length=2 * MINIMUM_PAIRED_SAMPLES, max_length=MAXIMUM_CAMPAIGN_ATTEMPTS
        ),
    ]
    attempts: Annotated[
        tuple[LatencyAttempt, ...],
        Field(
            min_length=2 * MINIMUM_PAIRED_SAMPLES, max_length=MAXIMUM_CAMPAIGN_ATTEMPTS
        ),
    ]

    @field_validator("campaign_id")
    @classmethod
    def validate_campaign_id(cls, value: str) -> str:
        return _require_stable_id(value, label="campaign_id")

    @model_validator(mode="after")
    def validate_complete_comparable_campaign(self) -> LatencyCampaign:
        if (
            any(
                attempt.legacy_v1_authorization is not None for attempt in self.attempts
            )
            and self.scope is not CampaignScope.SYNTHETIC_CONTROL
        ):
            raise ValueError("legacy v1 evidence is synthetic-control only")
        if len(self.plan) != len(self.attempts):
            raise ValueError("every planned slot must retain exactly one attempt")
        expected_orders = tuple(range(1, len(self.plan) + 1))
        if tuple(slot.order_index for slot in self.plan) != expected_orders:
            raise ValueError("campaign plan order must be contiguous and canonical")
        if tuple(attempt.order_index for attempt in self.attempts) != expected_orders:
            raise ValueError("attempt order must match the complete plan")
        if any(
            current.started_at_utc < previous.completed_at_utc
            for previous, current in zip(self.attempts, self.attempts[1:])
        ):
            raise ValueError(
                "attempt UTC chronology must be non-overlapping in plan order"
            )
        if (
            self.attempts[-1].completed_at_utc - self.attempts[0].started_at_utc
        ).total_seconds() > 7 * 24 * 60 * 60:
            raise ValueError("campaign chronology exceeds seven days")
        slot_ids = tuple(slot.slot_id for slot in self.plan)
        attempt_ids = tuple(attempt.attempt_id for attempt in self.attempts)
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("planned slot IDs must be unique")
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("attempt IDs must be unique")
        for slot, attempt in zip(self.plan, self.attempts, strict=True):
            if (
                slot.slot_id,
                slot.order_index,
                slot.case_id,
                slot.pair_index,
                slot.system,
            ) != (
                attempt.slot_id,
                attempt.order_index,
                attempt.case_id,
                attempt.pair_index,
                attempt.system,
            ):
                raise ValueError("attempt identity must match its immutable plan slot")

        case_ids = tuple(dict.fromkeys(slot.case_id for slot in self.plan))
        sample_counts = {
            len(tuple(slot for slot in self.plan if slot.case_id == case_id)) // 2
            for case_id in case_ids
        }
        if len(sample_counts) != 1:
            raise ValueError(
                "every campaign case must use the same paired sample count"
            )
        sample_count = next(iter(sample_counts))
        first_system = self.plan[0].system
        second_system = (
            SystemName.LLAMAPARSE
            if first_system is SystemName.CANDIDATE
            else SystemName.CANDIDATE
        )
        expected_schedule = tuple(
            (case_id, pair_index, system)
            for pair_index in range(1, sample_count + 1)
            for system in (first_system, second_system)
            for case_id in case_ids
        )
        observed_schedule = tuple(
            (slot.case_id, slot.pair_index, slot.system) for slot in self.plan
        )
        if observed_schedule != expected_schedule:
            raise ValueError(
                "campaign plan must use round-major batches and alternate each case"
            )
        for case_id in case_ids:
            case_slots = tuple(slot for slot in self.plan if slot.case_id == case_id)
            case_attempts = tuple(
                item for item in self.attempts if item.case_id == case_id
            )
            by_system = {
                system: tuple(item for item in case_attempts if item.system is system)
                for system in SystemName
            }
            counts = {system: len(items) for system, items in by_system.items()}
            if len(set(counts.values())) != 1 or any(
                count < self.minimum_samples_per_case_per_system
                for count in counts.values()
            ):
                raise ValueError("each case requires equal minimum paired samples")
            pair_indices = tuple(range(1, counts[SystemName.CANDIDATE] + 1))
            if tuple(slot.system for slot in case_slots) != tuple(
                system
                for _pair_index in pair_indices
                for system in (first_system, second_system)
            ):
                raise ValueError(
                    "each case's campaign subsequence must alternate systems"
                )
            for pair_index in pair_indices:
                pair_slots = tuple(
                    slot for slot in case_slots if slot.pair_index == pair_index
                )
                if {slot.system for slot in pair_slots} != set(SystemName):
                    raise ValueError("each campaign pair must contain both systems")
                for slot in pair_slots:
                    expected_slot_id = (
                        f"{case_id}-p{pair_index:02d}-{slot.system.value}"
                    )
                    if slot.slot_id != expected_slot_id:
                        raise ValueError("campaign slot ID must be canonical")
            for system, items in by_system.items():
                if tuple(sorted(item.pair_index for item in items)) != pair_indices:
                    raise ValueError(f"{system.value} pair indices must be contiguous")

            sources = {item.source for item in case_attempts}
            if len(sources) != 1:
                raise ValueError("paired systems must use one exact source identity")
            semantic_requests = {
                (
                    item.configuration.semantic_request_sha256,
                    item.configuration.output_format,
                )
                for item in case_attempts
            }
            if len(semantic_requests) != 1:
                raise ValueError(
                    "paired systems must use one semantic request identity"
                )

        global_semantic_requests = {
            (
                item.configuration.semantic_request_sha256,
                item.configuration.output_format,
            )
            for item in self.attempts
        }
        if len(global_semantic_requests) != 1:
            raise ValueError("campaign must use one global semantic request identity")
        provider_job_ids = tuple(
            item.provider_total_latency.job_id
            for item in self.attempts
            if item.provider_total_latency is not None
        )
        if len(provider_job_ids) != len(set(provider_job_ids)):
            raise ValueError("provider job IDs must be globally unique")

        expected_candidate_identity = (
            self.candidate_code_sha256,
            self.dependency_lock_sha256,
            self.environment_sha256,
            self.model_artifacts_sha256,
        )
        for attempt in self.attempts:
            if attempt.system is not SystemName.CANDIDATE:
                continue
            if (
                attempt.candidate_code_sha256,
                attempt.dependency_lock_sha256,
                attempt.environment_sha256,
                attempt.model_artifacts_sha256,
            ) != expected_candidate_identity:
                raise ValueError(
                    "candidate attempt execution identity differs from campaign"
                )

        for system in SystemName:
            identities = {
                item.configuration.system_configuration_sha256
                for item in self.attempts
                if item.system is system
            }
            if len(identities) != 1:
                raise ValueError(
                    "system configuration must remain fixed for the campaign"
                )
        candidate_configurations = tuple(
            item.configuration
            for item in self.attempts
            if item.system is SystemName.CANDIDATE
        )
        if any(
            configuration.runtime_sha256 != self.environment_sha256
            or configuration.model_artifacts_sha256 != self.model_artifacts_sha256
            for configuration in candidate_configurations
        ):
            raise ValueError("candidate configuration must bind campaign identities")

        computed_credits = sum(
            item.source.page_count * int(item.configuration.credits_per_page or 0)
            for item in self.attempts
            if item.system is SystemName.LLAMAPARSE
        )
        if self.hosted_credits_used != computed_credits:
            raise ValueError("hosted Agentic credits must be recomputed")
        if computed_credits > self.authorized_hosted_credit_limit:
            raise ValueError("hosted Agentic campaign exceeds its authorized limit")

        if self.scope is CampaignScope.PHASE_EXIT_ALL_15:
            if (
                case_ids != PHASE_EXIT_CASE_IDS
                or len(case_ids) != PHASE_EXIT_CASE_COUNT
                or sample_count != PHASE_EXIT_PROVIDER_SAMPLE_COUNT
                or self.minimum_samples_per_case_per_system
                != PHASE_EXIT_PROVIDER_SAMPLE_COUNT
                or len(self.attempts) != 150
                or computed_credits != PHASE_EXIT_AGENTIC_CREDIT_LIMIT
            ):
                raise ValueError(
                    "phase-exit campaign must close exact all-15/5-sample/1500-credit scope"
                )
            if (
                self.corpus_registry is None
                or self.corpus_registry.model_dump(mode="json")
                != PHASE_EXIT_CORPUS_REGISTRY
                or self.phase03_oracle_artifact is None
                or self.phase03_oracle_artifact.model_dump(mode="json")
                != PHASE_EXIT_ORACLE_ARTIFACT
                or self.source_registry_sha256 != PHASE_EXIT_SOURCE_REGISTRY_SHA256
            ):
                raise ValueError("phase-exit corpus custody identity differs")
            if self.provider_evidence_registry is None or any(
                item.provider_total_latency is not None
                and item.provider_total_latency.reviewed_sidecar is None
                for item in self.attempts
            ):
                raise ValueError("phase-exit provider reviewed custody is incomplete")
            if (
                self.environment_manifest is None
                or self.environment_manifest.manifest_sha256 != self.environment_sha256
            ):
                raise ValueError("phase-exit environment manifest identity differs")
            from tests.fixtures.phase_03.running_regions.oracle import (
                SOURCE_IDENTITIES,
            )

            if tuple(SOURCE_IDENTITIES) != PHASE_EXIT_CASE_IDS:
                raise ValueError("frozen all-15 source registry order differs")
            if _canonical_identity_hash(SOURCE_IDENTITIES) != (
                PHASE_EXIT_SOURCE_REGISTRY_SHA256
            ):
                raise ValueError("frozen all-15 source registry identity differs")
            for item in self.attempts:
                registered = SOURCE_IDENTITIES[item.case_id]
                expected = {
                    "case_id": item.case_id,
                    "path": registered["path"],
                    "filename": PurePosixPath(registered["path"]).name,
                    "sha256": registered["sha256"],
                    "size_bytes": registered["size_bytes"],
                    "page_count": registered["page_count"],
                }
                if item.source.model_dump(mode="json") != expected:
                    raise ValueError("phase-exit source identity differs from registry")
            if sum(PHASE_EXIT_CASE_PAGE_COUNTS.values()) != PHASE_EXIT_PAGE_COUNT:
                raise ValueError("phase-exit page registry differs")
        elif any(
            value is not None
            for value in (
                self.corpus_registry,
                self.phase03_oracle_artifact,
                self.source_registry_sha256,
                self.provider_evidence_registry,
            )
        ):
            raise ValueError("non-exit campaign cannot claim frozen corpus custody")
        if self.scope is CampaignScope.SYNTHETIC_CONTROL:
            if self.environment_manifest is not None:
                raise ValueError("synthetic campaign cannot claim a host environment")
        elif (
            self.environment_manifest is None
            or self.environment_manifest.manifest_sha256 != self.environment_sha256
        ):
            raise ValueError("campaign environment manifest identity differs")
        return self


class LatencyDistribution(ContractModel):
    count: PositiveInt
    minimum_ns: PositiveInt
    p50_ns: PositiveInt
    p95_ns: PositiveInt
    maximum_ns: PositiveInt

    @model_validator(mode="after")
    def require_ordered_values(self) -> LatencyDistribution:
        if not self.minimum_ns <= self.p50_ns <= self.p95_ns <= self.maximum_ns:
            raise ValueError("latency distribution must be ordered")
        return self


class CaseLatencyGate(ContractModel):
    case_id: StableId
    sample_count_per_system: PositiveInt
    candidate_failure_count: NonNegativeInt
    llamaparse_failure_count: NonNegativeInt
    candidate: LatencyDistribution | None
    llamaparse: LatencyDistribution | None
    failure_codes: tuple[
        Literal[
            "candidate_attempt_failed",
            "llamaparse_attempt_failed",
            "candidate_p50_exceeds_llamaparse",
            "candidate_p95_exceeds_llamaparse",
        ],
        ...,
    ]
    passed: StrictBool

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _require_stable_id(value, label="case_id")

    @model_validator(mode="after")
    def recompute_gate(self) -> CaseLatencyGate:
        codes: list[str] = []
        if self.candidate_failure_count:
            codes.append("candidate_attempt_failed")
        if self.llamaparse_failure_count:
            codes.append("llamaparse_attempt_failed")
        if not self.candidate_failure_count and not self.llamaparse_failure_count:
            if self.candidate is None or self.llamaparse is None:
                raise ValueError("successful paired gate requires both distributions")
            if self.candidate.count != self.sample_count_per_system:
                raise ValueError("candidate distribution count differs")
            if self.llamaparse.count != self.sample_count_per_system:
                raise ValueError("LlamaParse distribution count differs")
            if self.candidate.p50_ns > self.llamaparse.p50_ns:
                codes.append("candidate_p50_exceeds_llamaparse")
            if self.candidate.p95_ns > self.llamaparse.p95_ns:
                codes.append("candidate_p95_exceeds_llamaparse")
        elif self.candidate is not None or self.llamaparse is not None:
            raise ValueError(
                "failed attempts cannot be hidden by success-only quantiles"
            )
        if tuple(codes) != self.failure_codes:
            raise ValueError("case failure codes must be recomputed")
        if self.passed is not (not codes):
            raise ValueError("case pass must be recomputed")
        return self


class CampaignLatencyGate(ContractModel):
    schema_version: Literal["1.0"]
    campaign_sha256: Sha256
    cases: Annotated[tuple[CaseLatencyGate, ...], Field(min_length=1, max_length=100)]
    passed: StrictBool

    @model_validator(mode="after")
    def recompute_campaign_gate(self) -> CampaignLatencyGate:
        case_ids = tuple(case.case_id for case in self.cases)
        if case_ids != tuple(sorted(case_ids)) or len(case_ids) != len(set(case_ids)):
            raise ValueError("campaign cases must be unique and sorted")
        if self.passed is not all(case.passed for case in self.cases):
            raise ValueError("campaign pass must equal every per-case gate")
        return self


def canonical_model_bytes(model: ContractModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def model_sha256(model: ContractModel) -> str:
    return hashlib.sha256(canonical_model_bytes(model)).hexdigest()


def read_latency_campaign(data: str | bytes | bytearray) -> LatencyCampaign:
    encoded = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if len(encoded) > 64 * 1024 * 1024:
        raise ValueError("latency campaign exceeds its byte bound")
    return LatencyCampaign.model_validate_json(encoded)
