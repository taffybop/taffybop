"""Reusable metrics campaign primitives for P03-US08 running regions.

The readiness contract in :mod:`tests.fixtures.phase_03.running_regions.contract`
is the single source of truth for limits, formulas, worker order, semantic
normalization, and retained-artifact custody.  Production imports remain lazy
so importing this module still exercises only the frozen readiness machinery.
:func:`build_production_metrics_candidate` binds that machinery to the real
parser, extractor, projector, rollback, and resource/deadline hooks when the
retained campaign is explicitly requested.

Timing and traced allocation are separate protocols.  Retained artifacts are
validated by the closed readiness schema and are written with exclusive-create
semantics; this module never overwrites an existing candidate.
"""

from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import json
import math
import multiprocessing
import os
import platform
import resource
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, TypeVar
from unittest.mock import patch

from tests.fixtures.phase_03.running_regions import contract as readiness
from tests.fixtures.phase_03.running_regions import oracle as frozen_oracle
from tests.fixtures.phase_03.running_regions import synthetic as frozen_synthetic

# Re-export the authoritative readiness constants under stable benchmark names.
POLICY_ID = readiness.POLICY_ID
PERFORMANCE_TARGETS = readiness.PERFORMANCE_TARGETS
PAIRED_STATE_ORDER = readiness.PAIRED_STATE_ORDER
PAIRED_WORKER_PLAN = readiness.PAIRED_CASES
PAIRED_REPEAT_COUNT = len(PAIRED_STATE_ORDER)
PAIRED_WORKER_COUNT = readiness.PAIRED_WORKER_COUNT
PAIRED_WORKER_WIRE_CAP_BYTES = 256 * 1024
PAIRED_FIXED_CEILINGS_SECONDS = readiness.PAIRED_FIXED_CEILINGS_SECONDS
PEAK_RSS_DELTA_CEILING_BYTES = readiness.PEAK_MEMORY_DELTA_CEILING_BYTES
PEAK_ALLOCATION_CEILING_BYTES = readiness.PEAK_MEMORY_DELTA_CEILING_BYTES
ISOLATED_SOURCE_EXTRACTION_P95_SECONDS = (
    readiness.ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
)
ISOLATED_PROJECTION_P95_SECONDS = readiness.ISOLATED_PROJECTION_P95_SECONDS
ISOLATED_LATENCY_WARMUPS = readiness.ISOLATED_LATENCY_WARMUPS
ISOLATED_LATENCY_SAMPLES = readiness.ISOLATED_LATENCY_SAMPLES
ISOLATED_ALLOCATION_WARMUPS = readiness.ISOLATED_ALLOCATION_WARMUPS
ISOLATED_ALLOCATION_SAMPLES = readiness.ISOLATED_ALLOCATION_SAMPLES
TIMING_PATHS_REMOVED = readiness.WHOLE_OUTPUT_TIMING_PATHS
SOURCE_REPORT_TIMING_PATHS_REMOVED = ("extraction_ms",)
ARTIFACT_SEMANTIC_FIELDS_REMOVED = ("generated_at", "semantic_sha256")
FINAL_ARTIFACT_RELATIVE_PATH = Path(readiness.FINAL_METRICS_ARTIFACT_PATH)
FAILED_ARTIFACT_PATTERN = readiness.FAILED_METRICS_ARTIFACT_PATTERN
ARTIFACT_TOP_LEVEL_FIELDS = readiness.METRICS_ARTIFACT_FIELDS
ARTIFACT_FAILURE_FIELDS = readiness.METRICS_FAILURE_FIELDS
RESOURCE_LIMITS = readiness.RESOURCE_LIMITS

MAXIMUM_PAGE_FIXTURE_ID = readiness.MAXIMUM_PAGE_FIXTURE_ID
MAXIMUM_PAGE_WORKLOAD_FIELDS = readiness.MAXIMUM_PAGE_WORKLOAD_FIELDS
MAXIMUM_PAGE_WORKLOAD = readiness.MAXIMUM_PAGE_WORKLOAD

CODE_CUSTODY_FIELDS = readiness.CODE_CUSTODY_FIELDS
CODE_CUSTODY_RECORD_FIELDS = readiness.CODE_CUSTODY_RECORD_FIELDS
# Backwards-compatible benchmark name for the authoritative custody record.
CODE_FILE_IDENTITY_FIELDS = CODE_CUSTODY_RECORD_FIELDS
DEPENDENCY_CUSTODY_FIELDS = readiness.DEPENDENCY_CUSTODY_FIELDS
DEPENDENCY_MANIFEST_PATHS = readiness.DEPENDENCY_MANIFEST_PATHS
DEPENDENCY_PACKAGE_FIELDS = readiness.DEPENDENCY_PACKAGE_FIELDS
DEPENDENCY_REQUIRED_PYTHON_PACKAGES = readiness.DEPENDENCY_REQUIRED_PYTHON_PACKAGES
DEPENDENCY_LOCAL_TOOL_FIELDS = readiness.DEPENDENCY_LOCAL_TOOL_FIELDS
DEPENDENCY_REQUIRED_LOCAL_TOOLS = readiness.DEPENDENCY_REQUIRED_LOCAL_TOOLS
DEPENDENCY_RUNTIME_FIELDS = readiness.DEPENDENCY_RUNTIME_FIELDS
OFFLINE_ENVIRONMENT_FIELDS = readiness.OFFLINE_ENVIRONMENT_FIELDS
OFFLINE_ENVIRONMENT = readiness.OFFLINE_ENVIRONMENT
OUTPUT_SIZES_FIELDS = readiness.OUTPUT_SIZES_FIELDS
OUTPUT_SAMPLE_FIELDS = readiness.OUTPUT_SAMPLE_FIELDS
OUTPUT_VARIANTS = readiness.OUTPUT_VARIANTS
OUTPUT_IDENTITY_FIELDS = readiness.OUTPUT_IDENTITY_FIELDS

MEASUREMENT_FIELDS = (
    "performance_cases",
    "pair_count_per_case",
    "worker_process_count",
    "isolated_latency_warmups",
    "isolated_latency_samples",
    "isolated_allocation_warmups",
    "isolated_allocation_samples",
    "whole_parser_clock",
    "whole_parser_scope",
    "execution_order_policy",
    "cache_disclaimer",
    "maximum_page_workload",
)
POLICY_FIELDS = (
    "policy_id",
    "quantile_method",
    "quantile_formula",
    "paired_fixed_ceilings_seconds",
    "relative_ceiling_fraction",
    "peak_rss_delta_ceiling_bytes",
    "source_extraction_p95_ceiling_seconds",
    "projection_p95_ceiling_seconds",
    "peak_allocation_ceiling_bytes",
    "source_report_size_ceiling_bytes",
    "timing_paths_removed",
    "source_report_timing_paths_removed",
    "artifact_semantic_fields_removed",
)
SETTINGS_DELTA_FIELDS = (
    "changed_fields",
    "flag_off",
    "flag_on",
    "flag_off_sha256",
    "flag_on_sha256",
    "predecessor_flags_match",
)
M0_REFERENCE_FIELDS = ("path", "size_bytes", "sha256", "targets")
M0_TARGET_FIELDS = (
    "label",
    "wall_seconds",
    "peak_rss_mib",
    "five_percent_ceiling_seconds",
)
INPUT_CUSTODY_FIELDS = (
    "corpus_registry",
    "pre",
    "post",
    "source_count",
    "page_count",
    "total_size_bytes",
    "all_expected_match",
    "pre_post_match",
)
SOURCE_IDENTITY_FIELDS = ("path", "size_bytes", "sha256", "page_count")
PREDECESSOR_CUSTODY_FIELDS = (
    "root",
    "outputs",
    "configuration",
    "output_count",
    "total_size_bytes",
    "all_expected_match",
)
PREDECESSOR_OUTPUT_FIELDS = ("size_bytes", "sha256")
SEALED_COMPONENT_CUSTODY_FIELDS = (
    "path",
    "size_bytes",
    "sha256",
    "semantic_sha256",
    "expected_semantic_sha256",
    "match",
)
ISOLATED_STAGE_FIELDS = ("targets", "all_pass")
ISOLATED_TARGET_FIELDS = (
    "protocol",
    "latency_seconds",
    "allocation_bytes",
    "warmup_successes",
    "measured_output_successes",
    "measured_outputs",
    "report_sizes",
    "predecessor_unchanged",
    "idempotent",
    "retained_output",
    "summary",
)
ISOLATED_MEASURED_OUTPUT_FIELDS = (
    "measurement_kind",
    "sample_index",
    "output_identity",
    "maximum_page_identity_json_bytes",
    "maximum_running_descriptor_json_bytes",
)
ISOLATED_SUMMARY_FIELDS = (
    "stage",
    "target_id",
    "page_count",
    "comparison_count",
    "maximum_page_comparisons",
    "latency_p95_seconds",
    "peak_allocation_bytes",
    "passed",
)
RESOURCE_BOUNDARY_FIELDS = (
    "counter",
    "production_hook",
    "limit",
    "exact_observed",
    "exact_accepted",
    "maximum_plus_one_observed",
    "maximum_plus_one_refused",
    "exact_outcome",
    "maximum_plus_one_outcome",
    "passed",
)
RESOURCE_BOUNDARIES_FIELDS = ("cases", "maximum_page_execution", "all_pass")
DEADLINE_BOUNDARY_FIELDS = (
    "name",
    "production_hook",
    "limit_seconds",
    "limit_ns",
    "maximum_plus_one_delta_ns",
    "exact_accepted",
    "maximum_plus_one_refused",
    "exact_clock_calls",
    "maximum_plus_one_clock_calls",
    "exact_outcome",
    "maximum_plus_one_outcome",
    "passed",
)
DEADLINE_BOUNDARIES_FIELDS = ("cases", "all_pass")
MAXIMUM_PAGE_EXECUTION_FIELDS = (
    "workload",
    "resource_accounting_hook",
    "page_deadline_hook",
    "accounted_workload",
    "resource_accounting_accepted",
    "page_deadline",
    "passed",
)
PAIRED_CALLBACK_FIELDS = (
    "wall_seconds",
    "raw_ru_maxrss",
    "platform",
    "exit_code",
    "source_match",
    "code_match",
    "custody_match",
    "imports_loaded_before_timing",
    "settings_loaded_before_timing",
    "source_verified_before_timing",
    "timing_clock",
    "timing_scope",
    "output_variants",
)
PAIRED_WORKER_RECORD_FIELDS = (
    "worker_index",
    "target_id",
    "pair_index",
    "state",
    "pid",
    "parent_pid",
    *PAIRED_CALLBACK_FIELDS,
    "rss_bytes",
)
PAIRED_PARSER_FIELDS = (
    "runner_pid",
    "worker_plan",
    "workers",
    "targets",
    "all_pass",
)
QUALITY_FIELDS = (
    "reviewed_page_count",
    "page_identity_exact_count",
    "page_identity_denominator",
    "running_region_exact_count",
    "running_region_denominator",
    "pairwise_order_exact_count",
    "pairwise_order_denominator",
    "manufacturing_header_exact_count",
    "manufacturing_header_denominator",
    "manufacturing_fused_contribution_exact",
    "manufacturing_public_owner_unchanged",
    "manufacturing_source_reconstruction_exact",
    "esg_cluster_exact",
    "false_printed_label_promotions",
    "duplicate_canonical_contributions",
    "missing_canonical_contributions",
    "legacy_identity_mismatches",
    "determinism_failures",
    "all_pass",
)
CONTROL_MATRIX_FIELDS = ("cases", "all_pass")
CONTROL_CASE_FIELDS = (
    "case_id",
    "page_count",
    "expected_detected_labels",
    "observed_detected_labels",
    "expected_running_regions",
    "observed_running_regions",
    "legacy_identity_match",
    "flag_off_byte_match",
    "canonical_body_match",
    "canonical_full_match",
    "passed",
)
COMPARISON_LEDGERS_FIELDS = ("targets", "all_pass")
COMPARISON_LEDGER_FIELDS = (
    "target_id",
    "page_count",
    "comparison_count",
    "maximum_page_comparisons",
    "page_ceiling",
    "document_ceiling",
    "instrumentation_untimed",
    "indexed_algorithm",
    "passed",
)
ROLLBACK_FIELDS = (
    "flag_off_byte_identical",
    "stripped_projection_matches_predecessor",
    "direct_strip_refused",
    "extracted_strip_refused",
    "page_rollback_passed",
    "document_rollback_passed",
    "canonical_failure_rollback_passed",
    "terminal_replay_passed",
    "idempotence_passed",
    "all_pass",
)
PRIOR_FAILED_CANDIDATE_FIELDS = (
    "path",
    "size_bytes",
    "sha256",
    "status",
    "semantic_sha256",
)
OBSERVED_PRIOR_ARTIFACT_FIELDS = (
    "size_bytes",
    "sha256",
    "status",
    "semantic_sha256",
)
AGGREGATE_FIELDS = (
    "measurement_protocol",
    "policy_contract",
    "settings_custody",
    "m0_reference",
    "input_custody",
    "predecessor_custody",
    "fixture_custody",
    "code_custody",
    "dependency_custody",
    "source_extraction",
    "running_region_projection",
    "resource_boundaries",
    "deadline_boundaries",
    "paired_parser",
    "quality",
    "control_matrix",
    "comparison_ledgers",
    "output_sizes",
    "rollback",
    "failure_free",
    "hosted_usage",
    "all_pass",
)

FAILURE_TYPES = (
    "worker_timeout",
    "worker_exit",
    "worker_result_invalid",
    "stage_failed",
)
FAILURE_STAGES = tuple(
    field
    for field in AGGREGATE_FIELDS
    if field not in {"all_pass", "failure_free", "hosted_usage"}
)
PAIRED_FAILURE_TYPES = FAILURE_TYPES[:3]
TARGET_SCOPED_FAILURE_STAGES = frozenset(
    {
        "source_extraction",
        "running_region_projection",
        "paired_parser",
        "comparison_ledgers",
        "output_sizes",
    }
)
EXACT_ACCEPTANCE_OUTCOME = "accepted"
REFUSAL_OUTCOMES = frozenset(
    {"returned_false", f"refused:{readiness.ReadinessContractError.__name__}"}
)

QUANTILE_METHOD = "empirical_p95_inclusive_nearest_rank"
QUANTILE_FORMULA = "sorted(samples)[ceil(0.95 * n) - 1]"
WHOLE_PARSER_CLOCK = "time.perf_counter_ns"
WHOLE_PARSER_SCOPE = "parse_document(source_bytes, filename, settings)"
EXECUTION_ORDER_POLICY = "off/on alternates by pair index"
CACHE_DISCLAIMER = (
    "operating-system caches were not explicitly flushed; no cold-cache claim is made"
)
HOSTED_USAGE = {
    "hosted_requests": 0,
    "hosted_tokens": 0,
    "hosted_cost_usd": 0,
}

RESOURCE_COUNTERS = tuple(
    key
    for key, value in RESOURCE_LIMITS.items()
    if isinstance(value, int) and not isinstance(value, bool)
)
DEADLINE_LIMITS_SECONDS = MappingProxyType(
    {
        "source_extraction_deadline": float(
            readiness.SOURCE_EXTRACTION_DEADLINE_SECONDS
        ),
        "projection_page_deadline": float(readiness.PROJECTION_PAGE_DEADLINE_SECONDS),
        "projection_document_deadline": float(
            readiness.PROJECTION_DOCUMENT_DEADLINE_SECONDS
        ),
    }
)
M0_ARTIFACT = {
    "path": "tracker/benchmarks/llamaparse-15/baseline-summary.md",
    "size_bytes": 10_127,
    "sha256": "e4bf5583bfd7833d1f84fab631e6492e58699b8f26b03b3fcee37bf4a0e2a29a",
    "targets": {
        "uber-earnings": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 29.15,
            "peak_rss_mib": 2_589.5,
            "five_percent_ceiling_seconds": 1.4575,
        },
        "ny-timetable": {
            "label": "M0_reference_context_not_paired_predecessor",
            "wall_seconds": 46.76,
            "peak_rss_mib": 1_944.0,
            "five_percent_ceiling_seconds": 2.3380,
        },
    },
}
PREDECESSOR_FLAG_NAMES = tuple(frozen_oracle.PREDECESSOR_CONFIGURATION)
SETTINGS_FLAG_NAMES = (*PREDECESSOR_FLAG_NAMES, "layout_running_regions_enabled")
_EXPECTED_SETTINGS_OFF = MappingProxyType(
    {
        **frozen_oracle.PREDECESSOR_CONFIGURATION,
        "layout_running_regions_enabled": False,
    }
)
_EXPECTED_SETTINGS_ON = MappingProxyType(
    {
        **frozen_oracle.PREDECESSOR_CONFIGURATION,
        "layout_running_regions_enabled": True,
    }
)
COMPONENT_PATHS = MappingProxyType(
    {
        "oracle_custody": "tests/fixtures/phase_03/running_regions/oracle.py",
        "contract_custody": "tests/fixtures/phase_03/running_regions/contract.py",
        "synthetic_fixture_custody": (
            "tests/fixtures/phase_03/running_regions/synthetic.py"
        ),
    }
)
REQUIRED_CODE_PATHS = frozenset(
    {
        "app/__init__.py",
        "app/api.py",
        "app/config.py",
        "app/errors.py",
        "app/main.py",
        "app/models.py",
        "app/services/__init__.py",
        "app/services/acroform.py",
        "app/services/acroform_raw.py",
        "app/services/font_audit.py",
        "app/services/font_recovery.py",
        "app/services/form_semantics.py",
        "app/services/input_documents.py",
        "app/services/ir.py",
        "app/services/layout.py",
        "app/services/layout_order.py",
        "app/services/layout_source_notes.py",
        "app/services/ocr.py",
        "app/services/outline_structure.py",
        "app/services/pipeline.py",
        "app/services/presentation.py",
        "app/services/running_regions.py",
        "app/services/selective_span_ocr.py",
        "app/services/serializer.py",
        "app/services/source_text_alignment.py",
        "app/services/spatial_tokens.py",
        "app/services/tables.py",
        "app/services/text_reconciliation.py",
        "app/services/text_run_semantics.py",
        "frontend/app/api/parse/route.ts",
        "frontend/app/clearleaf-workspace.tsx",
        "frontend/app/globals.css",
        "frontend/app/image-page-preview.tsx",
        "frontend/app/json-document-view.tsx",
        "frontend/app/layout.tsx",
        "frontend/app/page.tsx",
        "frontend/app/pdf-page-preview.tsx",
        "frontend/build/sites-vite-plugin.ts",
        "frontend/eslint.config.mjs",
        "frontend/lib/canonical-presentation.ts",
        "frontend/lib/document-api.ts",
        "frontend/lib/form-semantics.ts",
        "frontend/lib/json-view-lines.ts",
        "frontend/lib/layout-relationships.ts",
        "frontend/lib/normalize-document-json.ts",
        "frontend/lib/outline-structure.ts",
        "frontend/lib/page-results.ts",
        "frontend/lib/primary-item-text.ts",
        "frontend/lib/running-regions.ts",
        "frontend/lib/serialize-output.ts",
        "frontend/lib/text-run-semantics.ts",
        "frontend/lib/types.ts",
        "frontend/next.config.ts",
        "frontend/postcss.config.mjs",
        "frontend/public/pdf.worker.min.mjs",
        "frontend/tests/built-output.test.mjs",
        "frontend/tests/document-api.test.mts",
        "frontend/tests/fixtures.mts",
        "frontend/tests/json-view-lines.test.mts",
        "frontend/tests/normalize-document-json.test.mts",
        "frontend/tests/p01-us04-serializer-parity.test.mts",
        "frontend/tests/p03-us01-table-captions.test.mts",
        "frontend/tests/p03-us02-visual-relationships.test.mts",
        "frontend/tests/p03-us03-source-notes.test.mts",
        "frontend/tests/p03-us04-reading-order.test.mts",
        "frontend/tests/p03-us05-redline-runs.test.mts",
        "frontend/tests/p03-us06-form-semantics.test.mts",
        "frontend/tests/p03-us07-outline-structure.test.mts",
        "frontend/tests/p03-us08-running-regions.test.mts",
        "frontend/tests/page-results.test.mts",
        "frontend/tests/parse-route.test.mts",
        "frontend/tests/serialize-output.test.mts",
        "frontend/tests/workspace-canonical-ui.test.mts",
        "frontend/tests/workspace-layout.test.mts",
        "frontend/vite.config.ts",
        "frontend/worker/index.ts",
        "tests/benchmarks/running_region_metrics.py",
        "tests/contract/test_p03_us08_api_model_strictness.py",
        "tests/contract/test_p03_us08_running_region_contract.py",
        "tests/performance/test_p03_us08_running_region_metrics_contract.py",
        "tests/regression/phase_03/test_p03_us08_real_running_regions.py",
        "tests/stories/phase_03/test_p03_us08_running_regions.py",
        "tracker/phase-03-layout/decisions/P03-running-regions-and-page-identity-policy.md",
        *COMPONENT_PATHS.values(),
    }
)
MAX_CODE_CUSTODY_FILES = 128
MAX_CODE_CUSTODY_FILE_BYTES = 4 * 1024 * 1024
MAX_CODE_CUSTODY_TOTAL_BYTES = 64 * 1024 * 1024
MAX_DEPENDENCY_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_DEPENDENCY_MANIFEST_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FAILED_ARTIFACT_ATTEMPTS = 99
PRIOR_ARTIFACT_READ_CAP_BYTES = int(RESOURCE_LIMITS["report_json_bytes"])
ARTIFACT_WRITE_CAP_BYTES = PRIOR_ARTIFACT_READ_CAP_BYTES
LOCAL_TOOL_PROBE_TIMEOUT_SECONDS = 5.0
LOCAL_TOOL_PROBE_OUTPUT_CAP_BYTES = 64 * 1024
COMPONENT_EXPECTED_SEMANTIC_SHA256 = MappingProxyType(
    {
        "oracle_custody": frozen_oracle.EXPECTED_ORACLE_SHA256,
        "contract_custody": readiness.contract_self_check(),
        "synthetic_fixture_custody": frozen_synthetic.FROZEN_REGISTRY_SHA256,
    }
)
_CONTROL_EXPECTATIONS = MappingProxyType(
    {
        case_id: {
            "page_count": int(source["page_count"]),
            "detected_labels": sum(
                identity["detected_printed_label"] is not None
                for identity in frozen_oracle.PAGE_IDENTITIES
                if identity["case_id"] == case_id
            ),
            "running_regions": sum(
                region["case_id"] == case_id
                for region in frozen_oracle.ACCEPTED_RUNNING_REGIONS
            ),
        }
        for case_id, source in frozen_oracle.SOURCE_IDENTITIES.items()
    }
)

_EVIDENCE_DIRECTORY = PurePosixPath("tracker/phase-03-layout/evidence")
_MAPPING_ARTIFACT_FIELDS = frozenset(
    {
        "measurement",
        "policy",
        "settings_delta",
        "m0_reference",
        "input_custody",
        "predecessor_custody",
        "oracle_custody",
        "contract_custody",
        "synthetic_fixture_custody",
        "code_sha256",
        "dependency_custody",
        "source_extraction",
        "running_region_projection",
        "resource_boundaries",
        "deadline_boundaries",
        "paired_parser",
        "quality",
        "control_matrix",
        "comparison_ledgers",
        "output_sizes",
        "rollback",
        "aggregate",
    }
)
_SEQUENCE_ARTIFACT_FIELDS = frozenset({"prior_failed_candidates", "failures"})
_HEX_DIGITS = frozenset("0123456789abcdef")


class MetricsExecutionError(RuntimeError):
    """Raised when the campaign machinery itself violates the frozen contract."""


class PairedCampaignFailure(MetricsExecutionError):
    """Structured first-failure custody plus the exact completed worker prefix."""

    def __init__(
        self,
        *,
        campaign: Mapping[str, Any],
        failure: Mapping[str, Any],
    ) -> None:
        self.campaign = _strict_detach(campaign)
        self.failure = _strict_detach(failure)
        super().__init__(f"paired campaign failed: {self.failure['type']}")


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
PayloadT = TypeVar("PayloadT")


class PreparedOperation(Protocol[InputT, OutputT]):
    """One production stage whose input was prepared before instrumentation."""

    def __call__(self, prepared: InputT, /) -> OutputT: ...


class ResultObserver(Protocol[OutputT]):
    """Validate/hash one result outside the measured interval."""

    def __call__(self, result: OutputT, /) -> Any: ...


class ProductionBoundaryValidator(Protocol[PayloadT]):
    """The real production validator/accounting hook for one bounded payload."""

    def __call__(self, payload: PayloadT, /) -> Any: ...


class InjectedDeadlineOperation(Protocol):
    """A production deadline hook accepting an injected monotonic-ns clock."""

    def __call__(self, monotonic_ns: Callable[[], int], /) -> Any: ...


class MaximumPageResourceAccountant(Protocol):
    """Production accounting hook for the exact named maximum-page workload."""

    def __call__(self, workload: Mapping[str, Any], /) -> Mapping[str, Any]: ...


class MaximumPageDeadlineOperation(Protocol):
    """Production page projector receiving the workload and injected clock."""

    def __call__(
        self,
        workload: Mapping[str, Any],
        monotonic_ns: Callable[[], int],
        /,
    ) -> Any: ...


class PairedWorker(Protocol):
    """Execute exactly one work record in a new process and return its result."""

    def __call__(self, work: Mapping[str, Any], /) -> Mapping[str, Any]: ...


def _canonical_json(value: Any) -> str:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return rendered.encode("utf-8").decode("utf-8")
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("canonical JSON encoding differs") from exc


def _strict_detach(value: Any) -> Any:
    def json_value(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: json_value(member) for key, member in item.items()}
        if isinstance(item, (list, tuple)):
            return [json_value(member) for member in item]
        return item

    try:
        return json.loads(_canonical_json(json_value(value)))
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("strict JSON detach differs") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    try:
        encoded = _canonical_json(value).encode("utf-8")
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("canonical JSON digest encoding differs") from exc
    return _sha256_bytes(encoded)


def _inclusive_p95(samples: Sequence[float]) -> float:
    """Delegate the exact non-interpolated p95 formula to readiness."""

    return readiness.inclusive_nearest_rank(samples, 0.95)


def _paired_states(pair_index: int) -> tuple[bool, bool]:
    """Return the exact flag order for one of the five frozen pair indexes."""

    if (
        isinstance(pair_index, bool)
        or not isinstance(pair_index, int)
        or not 0 <= pair_index < PAIRED_REPEAT_COUNT
    ):
        raise readiness.ReadinessContractError("paired index differs")
    return tuple(state == "on" for state in PAIRED_STATE_ORDER[pair_index])  # type: ignore[return-value]


def _rss_bytes_from_maxrss(raw_value: int, *, platform_name: str) -> int:
    """Delegate approved Darwin/Linux ``ru_maxrss`` normalization."""

    return readiness.normalize_ru_maxrss(raw_value, platform_name)


def _paired_performance_summary(
    target_id: str,
    *,
    off_seconds: Sequence[float],
    on_seconds: Sequence[float],
    off_rss_bytes: Sequence[int],
    on_rss_bytes: Sequence[int],
) -> dict[str, Any]:
    """Delegate clipped dual-ceiling latency and pairwise RSS gates."""

    return readiness.summarize_paired_performance(
        target_id,
        off_seconds=off_seconds,
        on_seconds=on_seconds,
        off_rss_bytes=off_rss_bytes,
        on_rss_bytes=on_rss_bytes,
    )


def _semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove exactly the ten whole-output timing paths."""

    try:
        return readiness.whole_output_semantic_payload(payload)
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("whole-output semantic JSON differs") from exc


def _report_semantic_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    """Remove exactly the private report's root extraction timing."""

    try:
        return readiness.source_report_semantic_payload(report)
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("source-report semantic JSON differs") from exc


def _artifact_semantic_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only artifact timestamp and self-referential semantic digest."""

    try:
        return readiness.metrics_artifact_semantic_payload(artifact)
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("artifact semantic JSON differs") from exc


def _artifact_semantic_sha256(artifact: Mapping[str, Any]) -> str:
    return _sha256_json(_artifact_semantic_payload(artifact))


@dataclass(frozen=True, slots=True)
class TimingProfile:
    """One exact 2+20 isolated latency profile."""

    warmup_count: int
    sample_count: int
    samples_seconds: tuple[float, ...]
    p95_seconds: float
    minimum_seconds: float
    maximum_seconds: float
    timing_tracemalloc_enabled: bool = False
    gc_collection_outside_timed_interval: bool = True
    outputs_released_outside_timed_interval: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "warmup_count": self.warmup_count,
            "sample_count": self.sample_count,
            "samples_seconds": list(self.samples_seconds),
            "p95_seconds": self.p95_seconds,
            "minimum_seconds": self.minimum_seconds,
            "maximum_seconds": self.maximum_seconds,
            "quantile_method": QUANTILE_METHOD,
            "quantile_formula": QUANTILE_FORMULA,
            "timing_tracemalloc_enabled": self.timing_tracemalloc_enabled,
            "gc_collection_outside_timed_interval": (
                self.gc_collection_outside_timed_interval
            ),
            "outputs_released_outside_timed_interval": (
                self.outputs_released_outside_timed_interval
            ),
        }


@dataclass(frozen=True, slots=True)
class AllocationProfile:
    """One separate exact 1+5 traced-allocation profile."""

    warmup_count: int
    sample_count: int
    peak_allocated_samples_bytes: tuple[int, ...]
    peak_allocated_bytes: int
    tracemalloc_reset_between_samples: bool = True
    timing_claim: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "warmup_count": self.warmup_count,
            "sample_count": self.sample_count,
            "peak_allocated_samples_bytes": list(self.peak_allocated_samples_bytes),
            "peak_allocated_bytes": self.peak_allocated_bytes,
            "tracemalloc_reset_between_samples": (
                self.tracemalloc_reset_between_samples
            ),
            "timing_claim": self.timing_claim,
        }


def _profile_timing(
    prepare: Callable[[], InputT],
    operation: PreparedOperation[InputT, OutputT],
    *,
    observe_result: ResultObserver[OutputT] | None = None,
    clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> TimingProfile:
    """Run the frozen isolated latency protocol with tracing always disabled."""

    if tracemalloc.is_tracing():
        raise MetricsExecutionError("latency profile requires tracemalloc disabled")

    for _ in range(ISOLATED_LATENCY_WARMUPS):
        prepared = prepare()
        result = operation(prepared)
        if tracemalloc.is_tracing():
            raise MetricsExecutionError("timed operation enabled tracemalloc")
        if observe_result is not None:
            observe_result(result)
        del result
        del prepared
        gc.collect()

    samples: list[float] = []
    for _ in range(ISOLATED_LATENCY_SAMPLES):
        if tracemalloc.is_tracing():
            raise MetricsExecutionError("latency profile tracing state drifted")
        prepared = prepare()
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            started_ns = clock_ns()
            result = operation(prepared)
            operation_gc_enabled = gc.isenabled()
            finished_ns = clock_ns()
        finally:
            if gc_was_enabled:
                gc.enable()
            else:
                gc.disable()
        if operation_gc_enabled:
            raise MetricsExecutionError(
                "timed operation enabled cyclic garbage collection"
            )
        if tracemalloc.is_tracing():
            raise MetricsExecutionError("timed operation enabled tracemalloc")
        elapsed_ns = finished_ns - started_ns
        elapsed_seconds = elapsed_ns / 1_000_000_000
        if elapsed_ns < 0 or not math.isfinite(elapsed_seconds):
            raise MetricsExecutionError("latency clock produced an invalid sample")
        samples.append(elapsed_seconds)
        if observe_result is not None:
            observe_result(result)
        del result
        del prepared
        gc.collect()

    sample_tuple = tuple(samples)
    return TimingProfile(
        warmup_count=ISOLATED_LATENCY_WARMUPS,
        sample_count=ISOLATED_LATENCY_SAMPLES,
        samples_seconds=sample_tuple,
        p95_seconds=_inclusive_p95(sample_tuple),
        minimum_seconds=min(sample_tuple),
        maximum_seconds=max(sample_tuple),
    )


def _profile_allocation(
    prepare: Callable[[], InputT],
    operation: PreparedOperation[InputT, OutputT],
    *,
    observe_result: ResultObserver[OutputT] | None = None,
) -> AllocationProfile:
    """Run the frozen allocation protocol independently of latency timing."""

    if tracemalloc.is_tracing():
        raise MetricsExecutionError(
            "allocation profile requires tracemalloc initially disabled"
        )

    for _ in range(ISOLATED_ALLOCATION_WARMUPS):
        prepared = prepare()
        result = operation(prepared)
        if tracemalloc.is_tracing():
            raise MetricsExecutionError("allocation warmup enabled tracemalloc")
        if observe_result is not None:
            observe_result(result)
        del result
        del prepared
        gc.collect()

    peaks: list[int] = []
    for _ in range(ISOLATED_ALLOCATION_SAMPLES):
        if tracemalloc.is_tracing():
            raise MetricsExecutionError("allocation tracing state drifted")
        prepared = prepare()
        result: OutputT
        tracemalloc.start()
        try:
            tracemalloc.reset_peak()
            result = operation(prepared)
            if not tracemalloc.is_tracing():
                raise MetricsExecutionError("allocation operation disabled tracemalloc")
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            if tracemalloc.is_tracing():
                tracemalloc.stop()
        peaks.append(peak)
        if observe_result is not None:
            observe_result(result)
        del result
        del prepared
        gc.collect()

    peak_tuple = tuple(peaks)
    return AllocationProfile(
        warmup_count=ISOLATED_ALLOCATION_WARMUPS,
        sample_count=ISOLATED_ALLOCATION_SAMPLES,
        peak_allocated_samples_bytes=peak_tuple,
        peak_allocated_bytes=max(peak_tuple),
    )


@dataclass(frozen=True, slots=True)
class ProductionBoundaryResult:
    """Recorded exact/max+1 outcomes from one real production callback."""

    counter: str
    production_hook: str
    limit: int
    exact_observed: int
    exact_accepted: bool
    maximum_plus_one_observed: int
    maximum_plus_one_refused: bool
    exact_outcome: str
    maximum_plus_one_outcome: str

    @property
    def passed(self) -> bool:
        return self.exact_accepted and self.maximum_plus_one_refused

    def as_dict(self) -> dict[str, Any]:
        return {
            "counter": self.counter,
            "production_hook": self.production_hook,
            "limit": self.limit,
            "exact_observed": self.exact_observed,
            "exact_accepted": self.exact_accepted,
            "maximum_plus_one_observed": self.maximum_plus_one_observed,
            "maximum_plus_one_refused": self.maximum_plus_one_refused,
            "exact_outcome": self.exact_outcome,
            "maximum_plus_one_outcome": self.maximum_plus_one_outcome,
            "passed": self.passed,
        }


def _invoke_production_validator(
    validator: ProductionBoundaryValidator[PayloadT],
    payload: PayloadT,
    *,
    is_expected_refusal: Callable[[Exception], bool],
) -> tuple[bool, str]:
    try:
        outcome = validator(payload)
    except Exception as exc:
        if not is_expected_refusal(exc):
            raise MetricsExecutionError(
                "production boundary hook raised a non-refusal error"
            ) from exc
        refusal = f"refused:{type(exc).__name__}"
        if refusal not in REFUSAL_OUTCOMES:
            raise MetricsExecutionError(
                "production boundary hook used an unfrozen refusal type"
            ) from exc
        return False, refusal
    if outcome is False:
        return False, "returned_false"
    return True, "accepted"


def exercise_production_boundary(
    counter: str,
    *,
    exact_payload: PayloadT,
    maximum_plus_one_payload: PayloadT,
    measure: Callable[[PayloadT], int],
    production_validator: ProductionBoundaryValidator[PayloadT],
    production_hook: str,
    is_expected_refusal: Callable[[Exception], bool],
) -> ProductionBoundaryResult:
    """Run exact and max+1 payloads through the same real production hook."""

    limit_value = RESOURCE_LIMITS.get(counter)
    if isinstance(limit_value, bool) or not isinstance(limit_value, int):
        raise MetricsExecutionError("resource boundary is not integral")
    if not isinstance(production_hook, str) or not production_hook.strip():
        raise MetricsExecutionError("production boundary hook name is empty")
    exact_observed = measure(exact_payload)
    overflow_observed = measure(maximum_plus_one_payload)
    if exact_observed != limit_value or overflow_observed != limit_value + 1:
        raise MetricsExecutionError("resource payload observations differ")

    exact_accepted, exact_outcome = _invoke_production_validator(
        production_validator,
        exact_payload,
        is_expected_refusal=is_expected_refusal,
    )
    overflow_accepted, overflow_outcome = _invoke_production_validator(
        production_validator,
        maximum_plus_one_payload,
        is_expected_refusal=is_expected_refusal,
    )
    return ProductionBoundaryResult(
        counter=counter,
        production_hook=production_hook,
        limit=limit_value,
        exact_observed=exact_observed,
        exact_accepted=exact_accepted,
        maximum_plus_one_observed=overflow_observed,
        maximum_plus_one_refused=not overflow_accepted,
        exact_outcome=exact_outcome,
        maximum_plus_one_outcome=overflow_outcome,
    )


@dataclass(slots=True)
class InjectedMonotonicClock:
    """Two-point monotonic-ns clock; later calls remain at the finish tick."""

    start_ns: int
    finish_ns: int
    calls: int = 0

    def __call__(self) -> int:
        tick = self.start_ns if self.calls == 0 else self.finish_ns
        self.calls += 1
        return tick


@dataclass(frozen=True, slots=True)
class ProductionDeadlineResult:
    """Recorded inclusive and one-microsecond-over deadline outcomes."""

    name: str
    production_hook: str
    limit_seconds: float
    limit_ns: int
    maximum_plus_one_delta_ns: int
    exact_accepted: bool
    maximum_plus_one_refused: bool
    exact_clock_calls: int
    maximum_plus_one_clock_calls: int
    exact_outcome: str
    maximum_plus_one_outcome: str

    @property
    def passed(self) -> bool:
        return self.exact_accepted and self.maximum_plus_one_refused

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "production_hook": self.production_hook,
            "limit_seconds": self.limit_seconds,
            "limit_ns": self.limit_ns,
            "maximum_plus_one_delta_ns": self.maximum_plus_one_delta_ns,
            "exact_accepted": self.exact_accepted,
            "maximum_plus_one_refused": self.maximum_plus_one_refused,
            "exact_clock_calls": self.exact_clock_calls,
            "maximum_plus_one_clock_calls": self.maximum_plus_one_clock_calls,
            "exact_outcome": self.exact_outcome,
            "maximum_plus_one_outcome": self.maximum_plus_one_outcome,
            "passed": self.passed,
        }


def _invoke_deadline_operation(
    operation: InjectedDeadlineOperation,
    clock: InjectedMonotonicClock,
    *,
    is_expected_refusal: Callable[[Exception], bool],
) -> tuple[bool, str]:
    try:
        outcome = operation(clock)
    except Exception as exc:
        if not is_expected_refusal(exc):
            raise MetricsExecutionError(
                "production deadline hook raised a non-refusal error"
            ) from exc
        accepted, label = False, f"refused:{type(exc).__name__}"
        if label not in REFUSAL_OUTCOMES:
            raise MetricsExecutionError(
                "production deadline hook used an unfrozen refusal type"
            ) from exc
    else:
        accepted = outcome is not False
        label = "accepted" if accepted else "returned_false"
    if clock.calls < 2:
        raise MetricsExecutionError("production deadline hook did not read two ticks")
    return accepted, label


def exercise_production_deadline(
    name: str,
    *,
    production_operation: InjectedDeadlineOperation,
    production_hook: str,
    is_expected_refusal: Callable[[Exception], bool],
) -> ProductionDeadlineResult:
    """Run exact and +1 microsecond injected clocks through a production hook."""

    limit_seconds = {
        "source_extraction_deadline": readiness.SOURCE_EXTRACTION_DEADLINE_SECONDS,
        "projection_page_deadline": readiness.PROJECTION_PAGE_DEADLINE_SECONDS,
        "projection_document_deadline": (
            readiness.PROJECTION_DOCUMENT_DEADLINE_SECONDS
        ),
    }.get(name)
    if limit_seconds is None:
        raise MetricsExecutionError("deadline name differs")
    if not isinstance(production_hook, str) or not production_hook.strip():
        raise MetricsExecutionError("production deadline hook name is empty")
    limit_ns = round(limit_seconds * 1_000_000_000)
    start_ns = 100_000_000_000
    exact_clock = InjectedMonotonicClock(start_ns, start_ns + limit_ns)
    overflow_clock = InjectedMonotonicClock(start_ns, start_ns + limit_ns + 1_000)
    exact_accepted, exact_outcome = _invoke_deadline_operation(
        production_operation,
        exact_clock,
        is_expected_refusal=is_expected_refusal,
    )
    overflow_accepted, overflow_outcome = _invoke_deadline_operation(
        production_operation,
        overflow_clock,
        is_expected_refusal=is_expected_refusal,
    )
    return ProductionDeadlineResult(
        name=name,
        production_hook=production_hook,
        limit_seconds=limit_seconds,
        limit_ns=limit_ns,
        maximum_plus_one_delta_ns=1_000,
        exact_accepted=exact_accepted,
        maximum_plus_one_refused=not overflow_accepted,
        exact_clock_calls=exact_clock.calls,
        maximum_plus_one_clock_calls=overflow_clock.calls,
        exact_outcome=exact_outcome,
        maximum_plus_one_outcome=overflow_outcome,
    )


@dataclass(frozen=True, slots=True)
class MaximumPageExecutionResult:
    """Auditable proof that the named workload reached both production hooks."""

    workload: Mapping[str, Any]
    resource_accounting_hook: str
    page_deadline_hook: str
    accounted_workload: Mapping[str, Any]
    resource_accounting_accepted: bool
    page_deadline: ProductionDeadlineResult

    @property
    def passed(self) -> bool:
        return self.resource_accounting_accepted and self.page_deadline.passed

    def as_dict(self) -> dict[str, Any]:
        return {
            "workload": _strict_detach(self.workload),
            "resource_accounting_hook": self.resource_accounting_hook,
            "page_deadline_hook": self.page_deadline_hook,
            "accounted_workload": _strict_detach(self.accounted_workload),
            "resource_accounting_accepted": self.resource_accounting_accepted,
            "page_deadline": self.page_deadline.as_dict(),
            "passed": self.passed,
        }


def execute_maximum_page_workload(
    *,
    resource_accountant: MaximumPageResourceAccountant,
    resource_accounting_hook: str,
    page_operation: MaximumPageDeadlineOperation,
    page_deadline_hook: str,
    is_expected_refusal: Callable[[Exception], bool],
) -> MaximumPageExecutionResult:
    """Pass the exact workload to accounting and exact/+1 page-deadline hooks."""

    for name, value in (
        ("resource accounting", resource_accounting_hook),
        ("page deadline", page_deadline_hook),
    ):
        if not isinstance(value, str) or not value.strip():
            raise MetricsExecutionError(f"maximum-page {name} hook name is empty")
    workload = _strict_detach(MAXIMUM_PAGE_WORKLOAD)
    validate_maximum_page_workload(workload)
    try:
        accounted = resource_accountant(_strict_detach(workload))
    except Exception as exc:
        raise MetricsExecutionError(
            "maximum-page production accounting hook raised"
        ) from exc
    if not isinstance(accounted, Mapping) or dict(accounted) != workload:
        raise MetricsExecutionError("maximum-page production accounting result differs")
    deadline = exercise_production_deadline(
        "projection_page_deadline",
        production_operation=lambda clock: page_operation(
            _strict_detach(workload), clock
        ),
        production_hook=page_deadline_hook,
        is_expected_refusal=is_expected_refusal,
    )
    return MaximumPageExecutionResult(
        workload=workload,
        resource_accounting_hook=resource_accounting_hook,
        page_deadline_hook=page_deadline_hook,
        accounted_workload=_strict_detach(accounted),
        resource_accounting_accepted=True,
        page_deadline=deadline,
    )


def _paired_worker_process_entry(
    wire_descriptor: int,
    worker: PairedWorker,
    work: Mapping[str, Any],
) -> None:
    try:
        os.setsid()
    except OSError:
        envelope = {
            "ok": False,
            "pid": os.getpid(),
            "error": "worker_isolation_failed",
        }
    else:
        try:
            raw_result = worker(_strict_detach(work))
        except Exception:  # noqa: BLE001 - fixed child failure only
            envelope = {
                "ok": False,
                "pid": os.getpid(),
                "error": "callback_error",
            }
        else:
            try:
                result = _prepare_paired_callback_wire_result(raw_result)
            except Exception:  # noqa: BLE001 - fixed invalid-result envelope
                envelope = {
                    "ok": False,
                    "pid": os.getpid(),
                    "error": "wire_invalid",
                }
            else:
                envelope = {
                    "ok": True,
                    "pid": os.getpid(),
                    "result": result,
                }
    try:
        try:
            payload = _bounded_canonical_json_bytes(
                envelope,
                maximum_bytes=PAIRED_WORKER_WIRE_CAP_BYTES,
            )
        except MetricsExecutionError:
            payload = _bounded_canonical_json_bytes(
                {
                    "ok": False,
                    "pid": os.getpid(),
                    "error": "wire_too_large",
                },
                maximum_bytes=PAIRED_WORKER_WIRE_CAP_BYTES,
            )
        except (TypeError, ValueError):
            payload = _bounded_canonical_json_bytes(
                {
                    "ok": False,
                    "pid": os.getpid(),
                    "error": "wire_invalid",
                },
                maximum_bytes=PAIRED_WORKER_WIRE_CAP_BYTES,
            )
        os.ftruncate(wire_descriptor, 0)
        offset = 0
        while offset < len(payload):
            written = os.pwrite(wire_descriptor, payload[offset:], offset)
            if written <= 0:
                raise MetricsExecutionError("paired worker wire write stalled")
            offset += written
    finally:
        os.close(wire_descriptor)


def _bounded_canonical_json_bytes(
    value: Any,
    *,
    maximum_bytes: int,
) -> bytes:
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    payload = bytearray()
    try:
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            if len(payload) + len(encoded) > maximum_bytes:
                raise MetricsExecutionError("canonical JSON exceeds byte cap")
            payload.extend(encoded)
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("canonical JSON encoding differs") from exc
    return bytes(payload)


def _prepare_paired_callback_wire_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise readiness.ReadinessContractError("paired worker result differs")
    _exact_keys(result, PAIRED_CALLBACK_FIELDS, "paired_worker.result")
    wall_seconds = _finite_nonnegative(result["wall_seconds"], "paired worker wall")
    raw_rss = result["raw_ru_maxrss"]
    platform_name = result["platform"]
    if (
        isinstance(raw_rss, bool)
        or not isinstance(raw_rss, int)
        or not 0 <= raw_rss < 2**63
    ):
        raise readiness.ReadinessContractError("paired worker raw RSS differs")
    _rss_bytes_from_maxrss(raw_rss, platform_name=platform_name)
    exit_code = result["exit_code"]
    if (
        isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or not -(2**31) <= exit_code < 2**31
    ):
        raise readiness.ReadinessContractError("paired worker exit code differs")
    boolean_fields = (
        "source_match",
        "code_match",
        "custody_match",
        "imports_loaded_before_timing",
        "settings_loaded_before_timing",
        "source_verified_before_timing",
    )
    for field in boolean_fields:
        _require_bool(result[field], f"paired_worker.result.{field}")
    if (
        result["timing_clock"] != WHOLE_PARSER_CLOCK
        or result["timing_scope"] != WHOLE_PARSER_SCOPE
    ):
        raise readiness.ReadinessContractError("paired worker timing identity differs")
    output_variants = result["output_variants"]
    if not isinstance(output_variants, Mapping) or set(output_variants) != set(
        OUTPUT_VARIANTS
    ):
        raise readiness.ReadinessContractError("paired worker output variants differ")
    normalized_variants: dict[str, dict[str, Any]] = {}
    for variant, identity in output_variants.items():
        _validate_output_identity(
            identity,
            f"paired_worker.output_variants.{variant}",
        )
        normalized_variants[variant] = dict(identity)
    return {
        "wall_seconds": wall_seconds,
        "raw_ru_maxrss": raw_rss,
        "platform": platform_name,
        "exit_code": exit_code,
        **{field: result[field] for field in boolean_fields},
        "timing_clock": WHOLE_PARSER_CLOCK,
        "timing_scope": WHOLE_PARSER_SCOPE,
        "output_variants": normalized_variants,
    }


def _signal_process_group(process_id: int, signal_number: int) -> None:
    try:
        os.killpg(process_id, signal_number)
    except (PermissionError, ProcessLookupError):
        pass


def _cleanup_process_group(process_id: int) -> None:
    _signal_process_group(process_id, signal.SIGTERM)
    _signal_process_group(process_id, signal.SIGKILL)


def _bounded_stop_process(process: Any) -> None:
    """Stop a child without any unbounded join, even if it ignores SIGTERM."""

    _signal_process_group(process.pid, signal.SIGTERM)
    if process.is_alive():
        process.terminate()
    process.join(timeout=1.0)
    _signal_process_group(process.pid, signal.SIGKILL)
    if process.is_alive():
        process.kill()
        process.join(timeout=1.0)


def _read_paired_worker_wire(descriptor: int) -> Mapping[str, Any]:
    before = _file_descriptor_snapshot(descriptor)
    if (
        not stat.S_ISREG(before[2])
        or before[4] <= 0
        or before[4] > PAIRED_WORKER_WIRE_CAP_BYTES
    ):
        raise MetricsExecutionError("paired worker wire size differs")
    payload = os.pread(descriptor, PAIRED_WORKER_WIRE_CAP_BYTES + 1, 0)
    after = _file_descriptor_snapshot(descriptor)
    if len(payload) != before[4] or before != after:
        raise MetricsExecutionError("paired worker wire changed during read")
    envelope = _load_strict_json(
        payload,
        error="paired worker wire strict JSON differs",
    )
    if not isinstance(envelope, Mapping) or payload != _canonical_json(envelope).encode(
        "utf-8"
    ):
        raise MetricsExecutionError("paired worker wire encoding differs")
    if envelope.get("ok") is True:
        _exact_keys(envelope, ("ok", "pid", "result"), "paired_worker.wire")
    elif envelope.get("ok") is False:
        _exact_keys(envelope, ("ok", "pid", "error"), "paired_worker.wire")
        if envelope["error"] not in {
            "callback_error",
            "wire_invalid",
            "wire_too_large",
            "worker_isolation_failed",
        }:
            raise MetricsExecutionError("paired worker wire error differs")
    else:
        raise MetricsExecutionError("paired worker wire status differs")
    return envelope


def _raise_paired_campaign_failure(
    failure_type: str,
    *,
    runner_pid: int,
    records: Sequence[Mapping[str, Any]],
    failed_work: Mapping[str, Any],
) -> None:
    completed_count = len(records)
    plan = readiness.paired_worker_plan()
    campaign = {
        "runner_pid": runner_pid,
        "worker_plan": [_strict_detach(work) for work in plan[:completed_count]],
        "workers": [_strict_detach(record) for record in records],
        "targets": {},
        "all_pass": False,
    }
    failure = {
        "type": failure_type,
        "stage": "paired_parser",
        "target_id": failed_work["target_id"],
        "pair_index": failed_work["pair_index"],
        "state": failed_work["state"],
    }
    raise PairedCampaignFailure(campaign=campaign, failure=failure)


def run_paired_campaign(
    worker: PairedWorker,
    *,
    worker_timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run every state in a distinct forked OS worker, sequentially, once."""

    if (
        isinstance(worker_timeout_seconds, bool)
        or not isinstance(worker_timeout_seconds, (int, float))
        or not math.isfinite(worker_timeout_seconds)
        or worker_timeout_seconds <= 0
    ):
        raise MetricsExecutionError("paired worker timeout differs")
    try:
        context = multiprocessing.get_context("fork")
    except ValueError as exc:  # pragma: no cover - supported release hosts are Unix
        raise MetricsExecutionError("paired campaign requires fork workers") from exc

    runner_pid = os.getpid()
    plan = tuple(readiness.paired_worker_plan())
    records: list[dict[str, Any]] = []
    seen_pids: set[int] = set()
    for work in plan:
        with tempfile.TemporaryFile() as wire:
            process = context.Process(
                target=_paired_worker_process_entry,
                args=(wire.fileno(), worker, work),
            )
            process.start()
            process.join(timeout=float(worker_timeout_seconds))
            if process.is_alive():
                _bounded_stop_process(process)
                _raise_paired_campaign_failure(
                    "worker_timeout",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
            _cleanup_process_group(process.pid)
            if process.exitcode != 0:
                _raise_paired_campaign_failure(
                    "worker_exit",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
            try:
                envelope = _read_paired_worker_wire(wire.fileno())
            except (MetricsExecutionError, readiness.ReadinessContractError):
                _raise_paired_campaign_failure(
                    "worker_result_invalid",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
        if not isinstance(envelope, Mapping):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        pid = envelope.get("pid")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid != process.pid
            or pid == runner_pid
            or pid in seen_pids
        ):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        if envelope.get("ok") is not True:
            failure_type = (
                "worker_exit"
                if envelope.get("error")
                in {"callback_error", "worker_isolation_failed"}
                else "worker_result_invalid"
            )
            _raise_paired_campaign_failure(
                failure_type,
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        result = envelope.get("result")
        if not isinstance(result, Mapping):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        try:
            _exact_keys(result, PAIRED_CALLBACK_FIELDS, "paired_worker.result")
            output_variants = result["output_variants"]
            if not isinstance(output_variants, Mapping) or set(output_variants) != set(
                OUTPUT_VARIANTS
            ):
                raise readiness.ReadinessContractError(
                    "paired worker output variants differ"
                )
            for variant, identity in output_variants.items():
                _validate_output_identity(
                    identity, f"paired_worker.output_variants.{variant}"
                )
            wall_seconds = result["wall_seconds"]
            exit_code = result["exit_code"]
        except (KeyError, readiness.ReadinessContractError):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        if exit_code != 0:
            _raise_paired_campaign_failure(
                "worker_exit",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(wall_seconds)
            or wall_seconds < 0
            or any(
                result[key] is not True
                for key in (
                    "source_match",
                    "code_match",
                    "custody_match",
                    "imports_loaded_before_timing",
                    "settings_loaded_before_timing",
                    "source_verified_before_timing",
                )
            )
            or result["timing_clock"] != WHOLE_PARSER_CLOCK
            or result["timing_scope"] != WHOLE_PARSER_SCOPE
        ):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        try:
            record = {
                **work,
                "pid": pid,
                "parent_pid": runner_pid,
                **dict(result),
                "wall_seconds": float(wall_seconds),
                "rss_bytes": _rss_bytes_from_maxrss(
                    result["raw_ru_maxrss"], platform_name=result["platform"]
                ),
            }
        except readiness.ReadinessContractError:
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        seen_pids.add(pid)
        records.append(record)

    target_summaries: dict[str, dict[str, Any]] = {}
    for target_id in PERFORMANCE_TARGETS:
        by_state = {
            state: [
                record
                for record in records
                if record["target_id"] == target_id and record["state"] == state
            ]
            for state in ("off", "on")
        }
        target_summaries[target_id] = _strict_detach(
            _paired_performance_summary(
                target_id,
                off_seconds=[item["wall_seconds"] for item in by_state["off"]],
                on_seconds=[item["wall_seconds"] for item in by_state["on"]],
                off_rss_bytes=[item["rss_bytes"] for item in by_state["off"]],
                on_rss_bytes=[item["rss_bytes"] for item in by_state["on"]],
            )
        )
    result = {
        "runner_pid": runner_pid,
        "worker_plan": [_strict_detach(work) for work in plan],
        "workers": records,
        "targets": target_summaries,
        "all_pass": all(
            summary["passed"] is True for summary in target_summaries.values()
        ),
    }
    validate_paired_parser(result, complete=True)
    return result


def _exact_keys(value: Mapping[str, Any], fields: Sequence[str], path: str) -> None:
    if set(value) != set(fields):
        raise readiness.ReadinessContractError(f"{path} keys differ")


def _validate_sha256(value: Any, path: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise readiness.ReadinessContractError(f"{path} SHA-256 differs")
    return value


def _validate_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise readiness.ReadinessContractError(f"{path} text differs")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise readiness.ReadinessContractError(f"{path} Boolean differs")
    return value


def _require_nullable_bool(value: Any, path: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise readiness.ReadinessContractError(f"{path} nullable Boolean differs")
    return value


def _validate_acceptance_outcome(
    accepted: Any,
    outcome: Any,
    path: str,
) -> bool:
    accepted_value = _require_bool(accepted, f"{path}.accepted")
    if not isinstance(outcome, str):
        raise readiness.ReadinessContractError(f"{path}.outcome differs")
    if accepted_value:
        valid = outcome == EXACT_ACCEPTANCE_OUTCOME
    else:
        valid = outcome in REFUSAL_OUTCOMES
    if not valid:
        raise readiness.ReadinessContractError(f"{path}.outcome differs")
    return accepted_value


def _validate_file_identity(
    key: str,
    value: Any,
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, CODE_FILE_IDENTITY_FIELDS, path)
    relative = _validate_nonempty_string(value["path"], f"{path}.path")
    normalized = PurePosixPath(relative)
    if (
        relative != key
        or normalized.is_absolute()
        or ".." in normalized.parts
        or str(normalized) != relative
    ):
        raise readiness.ReadinessContractError(f"{path}.path differs")
    size = value["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise readiness.ReadinessContractError(f"{path}.size_bytes differs")
    _validate_sha256(value["sha256"], f"{path}.sha256")
    return dict(value)


def validate_maximum_page_workload(workload: Mapping[str, Any]) -> None:
    """Validate the one named workload used for the 250 ms page gate."""

    if not isinstance(workload, Mapping):
        raise readiness.ReadinessContractError("maximum page workload is not an object")
    _exact_keys(
        workload,
        MAXIMUM_PAGE_WORKLOAD_FIELDS,
        "maximum_page_workload",
    )
    if dict(workload) != dict(MAXIMUM_PAGE_WORKLOAD):
        raise readiness.ReadinessContractError("maximum page workload differs")


def build_code_custody(
    pre: Mapping[str, Mapping[str, Any]],
    post: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a closed pre/post code manifest and its aggregate SHA-256."""

    detached_pre = _strict_detach(pre)
    detached_post = _strict_detach(post)
    custody = {
        "manifest_sha256": _sha256_json(detached_post),
        "pre": detached_pre,
        "post": detached_post,
        "pre_post_match": detached_pre == detached_post,
    }
    validate_code_custody(custody)
    return custody


def validate_code_custody(
    custody: Mapping[str, Any],
    *,
    observed_files: Mapping[str, Mapping[str, Any]] | None = None,
    require_observed: bool = False,
    required_paths: frozenset[str] | None = REQUIRED_CODE_PATHS,
) -> bool:
    """Validate required paths, manifest algebra, and observed file identities."""

    if not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("code custody is not an object")
    _exact_keys(custody, CODE_CUSTODY_FIELDS, "code_custody")
    pre = custody["pre"]
    post = custody["post"]
    if (
        not isinstance(pre, Mapping)
        or not isinstance(post, Mapping)
        or not pre
        or set(pre) != set(post)
        or len(post) > MAX_CODE_CUSTODY_FILES
        or (required_paths is not None and not required_paths <= set(post))
    ):
        raise readiness.ReadinessContractError("code custody file set differs")
    for phase, records in (("pre", pre), ("post", post)):
        for key, record in records.items():
            if not isinstance(key, str):
                raise readiness.ReadinessContractError("code custody path key differs")
            _validate_file_identity(key, record, f"code_custody.{phase}.{key}")
    expected_match = dict(pre) == dict(post)
    if (
        not isinstance(custody["pre_post_match"], bool)
        or custody["pre_post_match"] is not expected_match
    ):
        raise readiness.ReadinessContractError("code custody match flag differs")
    expected_manifest = _sha256_json(post)
    if custody["manifest_sha256"] != expected_manifest:
        raise readiness.ReadinessContractError("code manifest SHA-256 differs")
    if observed_files is None:
        if require_observed:
            raise readiness.ReadinessContractError(
                "observed code file custody is required"
            )
    else:
        if not isinstance(observed_files, Mapping) or set(observed_files) != set(post):
            raise readiness.ReadinessContractError("observed code file set differs")
        normalized_observed = {
            path: _validate_file_identity(
                path,
                identity,
                f"observed_code_files.{path}",
            )
            for path, identity in observed_files.items()
        }
        if normalized_observed != dict(post):
            raise readiness.ReadinessContractError(
                "observed code file identity differs"
            )
    return expected_match


def _resolve_repository_root(repository_root: Path) -> Path:
    if not isinstance(repository_root, Path) or repository_root.is_symlink():
        raise MetricsExecutionError("repository root differs")
    try:
        root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MetricsExecutionError("repository root differs") from exc
    if not root.is_dir():
        raise MetricsExecutionError("repository root differs")
    return root


def _file_descriptor_snapshot(
    descriptor: int,
) -> tuple[int, int, int, int, int, int, int]:
    status = os.fstat(descriptor)
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _open_repository_directory_chain(
    root: Path,
    relative: PurePosixPath,
    *,
    error: str,
) -> tuple[
    list[int],
    list[tuple[int, int, int, int, int, int, int]],
]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | nofollow | close_on_exec
    descriptors: list[int] = []
    snapshots: list[tuple[int, int, int, int, int, int, int]] = []
    try:
        descriptor = os.open(root, directory_flags)
        descriptors.append(descriptor)
        for part in relative.parts:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        for descriptor in descriptors:
            snapshot = _file_descriptor_snapshot(descriptor)
            if not stat.S_ISDIR(snapshot[2]) or snapshot[3] < 1:
                raise MetricsExecutionError(error)
            snapshots.append(snapshot)
    except MetricsExecutionError:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise
    except OSError as exc:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise MetricsExecutionError(error) from exc
    return descriptors, snapshots


def _open_regular_repository_file_descriptor(
    root: Path,
    relative: PurePosixPath,
    *,
    error: str,
) -> tuple[
    int,
    list[int],
    list[tuple[int, int, int, int, int, int, int]],
]:
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise MetricsExecutionError(error)
    parent = PurePosixPath(*relative.parts[:-1])
    directory_descriptors, directory_snapshots = _open_repository_directory_chain(
        root, parent, error=error
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    file_flags = os.O_RDONLY | os.O_NONBLOCK | nofollow | close_on_exec
    try:
        descriptor = os.open(
            relative.name,
            file_flags,
            dir_fd=directory_descriptors[-1],
        )
        status = os.fstat(descriptor)
    except OSError as exc:
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
        raise MetricsExecutionError(error) from exc
    if not stat.S_ISREG(status.st_mode) or status.st_nlink < 1:
        os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
        raise MetricsExecutionError(error)
    return descriptor, directory_descriptors, directory_snapshots


def _open_repository_directory_descriptor(
    root: Path,
    relative: PurePosixPath,
    *,
    error: str,
) -> int:
    """Open one repository directory through no-follow directory descriptors."""

    if relative.is_absolute() or ".." in relative.parts:
        raise MetricsExecutionError(error)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    flags = os.O_RDONLY | os.O_DIRECTORY | nofollow | close_on_exec
    descriptor: int | None = None
    try:
        descriptor = os.open(root, flags)
        status = os.fstat(descriptor)
        if not stat.S_ISDIR(status.st_mode) or status.st_nlink < 1:
            raise MetricsExecutionError(error)
        for part in relative.parts:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            try:
                next_status = os.fstat(next_descriptor)
                if not stat.S_ISDIR(next_status.st_mode) or next_status.st_nlink < 1:
                    raise MetricsExecutionError(error)
            except Exception:
                os.close(next_descriptor)
                raise
            os.close(descriptor)
            descriptor = next_descriptor
    except MetricsExecutionError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise MetricsExecutionError(error) from exc
    return descriptor


def _repository_directory_binding_matches(
    root: Path,
    relative: PurePosixPath,
    expected: tuple[int, int, int, int, int, int, int],
) -> bool:
    try:
        descriptor = _open_repository_directory_descriptor(
            root,
            relative,
            error="artifact destination directory binding differs",
        )
    except MetricsExecutionError:
        return False
    try:
        observed = _file_descriptor_snapshot(descriptor)
    finally:
        os.close(descriptor)
    return observed[:3] == expected[:3] and observed[3] >= 1 and expected[3] >= 1


def _read_bounded_regular_repository_file_with_binding(
    root: Path,
    relative: PurePosixPath,
    *,
    maximum_bytes: int,
    error: str,
) -> tuple[
    bytes,
    tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ],
]:
    descriptor, directory_descriptors, directory_snapshots = (
        _open_regular_repository_file_descriptor(root, relative, error=error)
    )
    try:
        before = _file_descriptor_snapshot(descriptor)
        if before[4] > maximum_bytes:
            raise MetricsExecutionError(f"{error} exceeds byte cap")
        payload = os.pread(descriptor, maximum_bytes + 1, 0)
        after = _file_descriptor_snapshot(descriptor)
        if len(payload) > maximum_bytes:
            raise MetricsExecutionError(f"{error} exceeds byte cap")
        if len(payload) != before[4] or before != after:
            raise MetricsExecutionError(f"{error} changed during read")

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        rebound = os.open(
            relative.name,
            os.O_RDONLY | os.O_NONBLOCK | nofollow | close_on_exec,
            dir_fd=directory_descriptors[-1],
        )
        try:
            rebound_snapshot = _file_descriptor_snapshot(rebound)
        finally:
            os.close(rebound)
        if rebound_snapshot != after or not stat.S_ISREG(rebound_snapshot[2]):
            raise MetricsExecutionError(f"{error} filename binding changed")

        held_directory_snapshots = [
            _file_descriptor_snapshot(directory_descriptor)
            for directory_descriptor in directory_descriptors
        ]
        if held_directory_snapshots != directory_snapshots:
            raise MetricsExecutionError(f"{error} directory chain changed")
        fresh_descriptors, fresh_snapshots = _open_repository_directory_chain(
            root,
            PurePosixPath(*relative.parts[:-1]),
            error=f"{error} directory binding changed",
        )
        try:
            if fresh_snapshots != directory_snapshots:
                raise MetricsExecutionError(f"{error} directory binding changed")
        finally:
            for fresh_descriptor in reversed(fresh_descriptors):
                os.close(fresh_descriptor)
    except OSError as exc:
        raise MetricsExecutionError(f"{error} read failed") from exc
    finally:
        os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
    return payload, (after, tuple(directory_snapshots))


def _read_bounded_regular_repository_file(
    root: Path,
    relative: PurePosixPath,
    *,
    maximum_bytes: int,
    error: str,
) -> bytes:
    payload, _ = _read_bounded_regular_repository_file_with_binding(
        root,
        relative,
        maximum_bytes=maximum_bytes,
        error=error,
    )
    return payload


def _collect_frozen_repository_file_identity(
    root: Path,
    *,
    path: str,
    expected_size: int,
    expected_sha256: str,
    error: str,
) -> dict[str, Any]:
    relative = PurePosixPath(path)
    payload = _read_bounded_regular_repository_file(
        root,
        relative,
        maximum_bytes=expected_size,
        error=error,
    )
    identity = {
        "path": path,
        "size_bytes": len(payload),
        "sha256": _sha256_bytes(payload),
    }
    if identity["size_bytes"] != expected_size or identity["sha256"] != expected_sha256:
        raise MetricsExecutionError(f"{error} identity differs")
    return identity


def collect_input_file_identities(repository_root: Path) -> dict[str, Any]:
    """Observe the frozen registry and every source PDF from regular files."""

    root = _resolve_repository_root(repository_root)
    registry_expected = frozen_oracle.CORPUS_REGISTRY_CUSTODY
    registry = _collect_frozen_repository_file_identity(
        root,
        path=registry_expected["path"],
        expected_size=registry_expected["size_bytes"],
        expected_sha256=registry_expected["sha256"],
        error="corpus registry file custody",
    )
    sources = {
        case_id: _collect_frozen_repository_file_identity(
            root,
            path=identity["path"],
            expected_size=identity["size_bytes"],
            expected_sha256=identity["sha256"],
            error=f"source PDF custody for {case_id}",
        )
        for case_id, identity in frozen_oracle.SOURCE_IDENTITIES.items()
    }
    return {"corpus_registry": registry, "sources": sources}


def collect_predecessor_output_identities(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    """Observe all frozen post-US07 JSON outputs from regular files."""

    root = _resolve_repository_root(repository_root)
    output_root = PurePosixPath(frozen_oracle.PREDECESSOR_OUTPUT_ROOT)
    observed: dict[str, dict[str, Any]] = {}
    for case_id, expected in frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES.items():
        path = str(output_root / case_id / "our-output.json")
        identity = _collect_frozen_repository_file_identity(
            root,
            path=path,
            expected_size=expected["size_bytes"],
            expected_sha256=expected["sha256"],
            error=f"predecessor output custody for {case_id}",
        )
        observed[case_id] = {
            "size_bytes": identity["size_bytes"],
            "sha256": identity["sha256"],
        }
    return observed


def collect_m0_reference_identity(repository_root: Path) -> dict[str, Any]:
    """Observe the frozen M0 baseline summary from exact regular-file bytes."""

    root = _resolve_repository_root(repository_root)
    return _collect_frozen_repository_file_identity(
        root,
        path=M0_ARTIFACT["path"],
        expected_size=M0_ARTIFACT["size_bytes"],
        expected_sha256=M0_ARTIFACT["sha256"],
        error="M0 baseline file custody",
    )


def collect_code_file_identities(
    repository_root: Path,
    *,
    paths: Sequence[str] = tuple(sorted(REQUIRED_CODE_PATHS)),
) -> dict[str, dict[str, Any]]:
    """Collect bounded raw identities for an explicit repository-relative set."""

    root = _resolve_repository_root(repository_root)
    if not isinstance(paths, (list, tuple)) or not paths:
        raise MetricsExecutionError("observed code path set differs")
    if (
        len(paths) > MAX_CODE_CUSTODY_FILES
        or len(paths) != len(set(paths))
        or not REQUIRED_CODE_PATHS <= set(paths)
    ):
        raise MetricsExecutionError("observed code path set differs")
    observed: dict[str, dict[str, Any]] = {}
    total_size = 0
    for path in paths:
        if not isinstance(path, str) or not path:
            raise MetricsExecutionError("observed code path differs")
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != path:
            raise MetricsExecutionError("observed code path differs")
        payload = _read_bounded_regular_repository_file(
            root,
            relative,
            maximum_bytes=MAX_CODE_CUSTODY_FILE_BYTES,
            error="observed code path is not a regular repository file",
        )
        total_size += len(payload)
        if total_size > MAX_CODE_CUSTODY_TOTAL_BYTES:
            raise MetricsExecutionError("observed code exceeds total byte cap")
        observed[path] = {
            "path": path,
            "size_bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }
    return observed


def _stop_subprocess_bounded(process: subprocess.Popen[bytes]) -> None:
    _signal_process_group(process.pid, signal.SIGTERM)
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass
    _signal_process_group(process.pid, signal.SIGKILL)
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired as exc:
        raise MetricsExecutionError(
            "local dependency tool could not be stopped"
        ) from exc


def _probe_local_tool_version(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise MetricsExecutionError("required local dependency tool is absent")
    try:
        process = subprocess.Popen(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise MetricsExecutionError("local dependency tool probe failed") from exc
    if process.stdout is None:
        _stop_subprocess_bounded(process)
        raise MetricsExecutionError("local dependency tool probe failed")
    output = bytearray()
    deadline = time.monotonic() + LOCAL_TOOL_PROBE_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_subprocess_bounded(process)
                raise MetricsExecutionError("local dependency tool probe timed out")
            events = selector.select(remaining)
            if not events:
                _stop_subprocess_bounded(process)
                raise MetricsExecutionError("local dependency tool probe timed out")
            chunk = os.read(
                process.stdout.fileno(),
                min(
                    8192,
                    LOCAL_TOOL_PROBE_OUTPUT_CAP_BYTES + 1 - len(output),
                ),
            )
            if not chunk:
                try:
                    return_code = process.wait(timeout=max(remaining, 0.001))
                except subprocess.TimeoutExpired as exc:
                    _stop_subprocess_bounded(process)
                    raise MetricsExecutionError(
                        "local dependency tool probe timed out after EOF"
                    ) from exc
                break
            output.extend(chunk)
            if len(output) > LOCAL_TOOL_PROBE_OUTPUT_CAP_BYTES:
                _stop_subprocess_bounded(process)
                raise MetricsExecutionError(
                    "local dependency tool probe exceeds output byte cap"
                )
    except (KeyError, OSError, ValueError) as exc:
        _stop_subprocess_bounded(process)
        raise MetricsExecutionError("local dependency tool probe failed") from exc
    finally:
        selector.close()
        process.stdout.close()
    _stop_subprocess_bounded(process)
    if return_code != 0 or not output:
        raise MetricsExecutionError("local dependency tool probe differs")
    payload = bytes(output)
    try:
        first_line = payload.decode("utf-8", errors="strict").splitlines()[0].strip()
    except (IndexError, UnicodeDecodeError) as exc:
        raise MetricsExecutionError("local dependency tool version differs") from exc
    prefix = f"{name} "
    version = first_line.removeprefix(prefix)
    if (
        not first_line.startswith(prefix)
        or not version
        or any(character.isspace() for character in version)
    ):
        raise MetricsExecutionError("local dependency tool version differs")
    return version


def collect_dependency_custody(repository_root: Path) -> dict[str, Any]:
    """Observe exact manifest bytes, installed dependencies, runtime, and env."""

    root = _resolve_repository_root(repository_root)
    manifests: dict[str, dict[str, Any]] = {}
    manifest_total_size = 0
    for path in DEPENDENCY_MANIFEST_PATHS:
        relative = PurePosixPath(path)
        payload = _read_bounded_regular_repository_file(
            root,
            relative,
            maximum_bytes=MAX_DEPENDENCY_MANIFEST_BYTES,
            error="dependency manifest is not a regular repository file",
        )
        manifest_total_size += len(payload)
        if manifest_total_size > MAX_DEPENDENCY_MANIFEST_TOTAL_BYTES:
            raise MetricsExecutionError("dependency manifests exceed total byte cap")
        manifests[path] = {
            "path": path,
            "size_bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }
    packages: dict[str, dict[str, str]] = {}
    for distribution in DEPENDENCY_REQUIRED_PYTHON_PACKAGES:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise MetricsExecutionError("required Python dependency is absent") from exc
        packages[distribution] = {
            "distribution": distribution,
            "version": version,
        }
    local_tools = {
        name: {"name": name, "version": _probe_local_tool_version(name)}
        for name in DEPENDENCY_REQUIRED_LOCAL_TOOLS
    }
    offline = {field: os.environ.get(field) for field in OFFLINE_ENVIRONMENT_FIELDS}
    if offline != dict(OFFLINE_ENVIRONMENT):
        raise MetricsExecutionError("offline dependency environment differs")
    custody = {
        "manifests": manifests,
        "python_packages": packages,
        "local_tools": local_tools,
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "offline_environment": offline,
    }
    validate_dependency_custody(custody)
    return custody


def validate_dependency_custody(
    custody: Mapping[str, Any],
    *,
    observed_custody: Mapping[str, Any] | None = None,
    require_observed: bool = False,
) -> None:
    """Validate the exact manifest/package/tool/runtime dependency schema."""

    if not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("dependency custody is not an object")
    _exact_keys(custody, DEPENDENCY_CUSTODY_FIELDS, "dependency_custody")
    manifests = custody["manifests"]
    if not isinstance(manifests, Mapping) or set(manifests) != set(
        DEPENDENCY_MANIFEST_PATHS
    ):
        raise readiness.ReadinessContractError("dependency manifest set differs")
    for key, record in manifests.items():
        _validate_file_identity(str(key), record, f"dependency_custody.manifests.{key}")

    packages = custody["python_packages"]
    if not isinstance(packages, Mapping) or set(packages) != set(
        DEPENDENCY_REQUIRED_PYTHON_PACKAGES
    ):
        raise readiness.ReadinessContractError("dependency Python package set differs")
    for key, record in packages.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("dependency package record differs")
        _exact_keys(
            record,
            DEPENDENCY_PACKAGE_FIELDS,
            f"dependency_custody.python_packages.{key}",
        )
        if record["distribution"] != key:
            raise readiness.ReadinessContractError(
                "dependency distribution identity differs"
            )
        _validate_nonempty_string(
            record["version"], f"dependency_custody.python_packages.{key}.version"
        )

    local_tools = custody["local_tools"]
    if not isinstance(local_tools, Mapping) or set(local_tools) != set(
        DEPENDENCY_REQUIRED_LOCAL_TOOLS
    ):
        raise readiness.ReadinessContractError("dependency local tools differ")
    for key, record in local_tools.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError(
                "dependency local tool record differs"
            )
        _exact_keys(
            record,
            DEPENDENCY_LOCAL_TOOL_FIELDS,
            f"dependency_custody.local_tools.{key}",
        )
        if record["name"] != key:
            raise readiness.ReadinessContractError(
                "dependency local tool identity differs"
            )
        _validate_nonempty_string(
            record["version"], f"dependency_custody.local_tools.{key}.version"
        )

    runtime = custody["runtime"]
    if not isinstance(runtime, Mapping):
        raise readiness.ReadinessContractError("dependency runtime differs")
    _exact_keys(runtime, DEPENDENCY_RUNTIME_FIELDS, "dependency_custody.runtime")
    for field in DEPENDENCY_RUNTIME_FIELDS:
        _validate_nonempty_string(runtime[field], f"dependency_custody.runtime.{field}")
    offline = custody["offline_environment"]
    if not isinstance(offline, Mapping) or dict(offline) != dict(OFFLINE_ENVIRONMENT):
        raise readiness.ReadinessContractError("dependency offline environment differs")
    if observed_custody is None:
        if require_observed:
            raise readiness.ReadinessContractError(
                "observed dependency custody is required"
            )
    elif _strict_detach(custody) != _strict_detach(observed_custody):
        raise readiness.ReadinessContractError("observed dependency custody differs")


def _validate_output_identity(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, OUTPUT_IDENTITY_FIELDS, path)
    size = value["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise readiness.ReadinessContractError(f"{path}.size_bytes differs")
    _validate_sha256(value["sha256"], f"{path}.sha256")


def validate_output_sizes(
    output_sizes: Mapping[str, Any],
    *,
    complete: bool,
) -> bool:
    """Validate every retained output/report size and hash record."""

    if not isinstance(output_sizes, Mapping):
        raise readiness.ReadinessContractError("output sizes is not an object")
    _exact_keys(output_sizes, OUTPUT_SIZES_FIELDS, "output_sizes")
    paired = output_sizes["paired_samples"]
    reports = output_sizes["source_reports"]
    projections = output_sizes["isolated_projection_outputs"]
    for field, value in (
        ("paired_samples", paired),
        ("source_reports", reports),
        ("isolated_projection_outputs", projections),
    ):
        if not isinstance(value, Mapping) or not set(value) <= set(PERFORMANCE_TARGETS):
            raise readiness.ReadinessContractError(
                f"output_sizes.{field} target set differs"
            )
        if complete and set(value) != set(PERFORMANCE_TARGETS):
            raise readiness.ReadinessContractError(
                f"output_sizes.{field} is incomplete"
            )

    for target_id, samples in paired.items():
        if not isinstance(samples, list):
            raise readiness.ReadinessContractError(
                "output paired samples are not ordered"
            )
        expected_order = tuple(
            (pair_index, state)
            for plan_target, pair_index, state in PAIRED_WORKER_PLAN
            if plan_target == target_id
        )
        observed_order: list[tuple[int, str]] = []
        for index, sample in enumerate(samples):
            if not isinstance(sample, Mapping):
                raise readiness.ReadinessContractError("output paired sample differs")
            _exact_keys(
                sample,
                OUTPUT_SAMPLE_FIELDS,
                f"output_sizes.paired_samples.{target_id}.{index}",
            )
            if sample["target_id"] != target_id:
                raise readiness.ReadinessContractError("output paired target differs")
            pair_index = sample["pair_index"]
            state = sample["state"]
            if (
                isinstance(pair_index, bool)
                or not isinstance(pair_index, int)
                or not 0 <= pair_index < PAIRED_REPEAT_COUNT
                or state not in {"off", "on"}
            ):
                raise readiness.ReadinessContractError("output paired identity differs")
            observed_order.append((pair_index, state))
            variants = sample["variants"]
            if not isinstance(variants, Mapping) or set(variants) != set(
                OUTPUT_VARIANTS
            ):
                raise readiness.ReadinessContractError("output variant set differs")
            for variant, identity in variants.items():
                _validate_output_identity(
                    identity,
                    f"output_sizes.paired_samples.{target_id}.{index}.{variant}",
                )
        if tuple(observed_order) != expected_order[: len(observed_order)]:
            raise readiness.ReadinessContractError("output paired sample order differs")
        if complete and tuple(observed_order) != expected_order:
            raise readiness.ReadinessContractError("output paired sample count differs")

    for field, records in (
        ("source_reports", reports),
        ("isolated_projection_outputs", projections),
    ):
        for target_id, identity in records.items():
            _validate_output_identity(identity, f"output_sizes.{field}.{target_id}")

    maximum_fields = {
        "maximum_page_identity_json_bytes": int(
            RESOURCE_LIMITS["page_identity_json_bytes"]
        ),
        "maximum_running_descriptor_json_bytes": int(
            RESOURCE_LIMITS["running_descriptor_json_bytes"]
        ),
        "maximum_source_report_json_bytes": int(RESOURCE_LIMITS["report_json_bytes"]),
    }
    computed_within = True
    for field, ceiling in maximum_fields.items():
        observed = output_sizes[field]
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            raise readiness.ReadinessContractError(f"output_sizes.{field} differs")
        computed_within = computed_within and observed <= ceiling
    if (
        not isinstance(output_sizes["all_within_limits"], bool)
        or output_sizes["all_within_limits"] is not computed_within
    ):
        raise readiness.ReadinessContractError("output size aggregate gate differs")
    if complete and not computed_within:
        raise readiness.ReadinessContractError(
            "final output sizes exceed a frozen limit"
        )
    collections_complete = all(
        set(output_sizes[field]) == set(PERFORMANCE_TARGETS)
        for field in (
            "paired_samples",
            "source_reports",
            "isolated_projection_outputs",
        )
    )
    samples_complete = collections_complete and all(
        len(output_sizes["paired_samples"][target_id]) == 2 * PAIRED_REPEAT_COUNT
        for target_id in PERFORMANCE_TARGETS
    )
    return collections_complete and samples_complete and computed_within


def _nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise readiness.ReadinessContractError(f"{path} differs")
    return value


def _positive_int(value: Any, path: str) -> int:
    result = _nonnegative_int(value, path)
    if result == 0:
        raise readiness.ReadinessContractError(f"{path} differs")
    return result


def _finite_nonnegative(value: Any, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise readiness.ReadinessContractError(f"{path} differs")
    return float(value)


def _comparison_counts_are_coherent(
    page_count: int,
    comparison_count: int,
    maximum_page_comparisons: int,
) -> bool:
    return (
        maximum_page_comparisons <= comparison_count
        and (comparison_count != 0 or maximum_page_comparisons == 0)
        and (
            page_count != 0 or (comparison_count == 0 and maximum_page_comparisons == 0)
        )
    )


def _closed_boolean_list(
    value: Any,
    path: str,
    *,
    maximum: int,
) -> list[bool]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(item is not True and item is not False for item in value)
    ):
        raise readiness.ReadinessContractError(f"{path} differs")
    return value


def validate_measurement(measurement: Mapping[str, Any]) -> bool:
    """Validate the complete invocation-count and named-workload declaration."""

    if not isinstance(measurement, Mapping):
        raise readiness.ReadinessContractError("measurement is not an object")
    _exact_keys(measurement, MEASUREMENT_FIELDS, "measurement")
    expected = {
        "performance_cases": list(PERFORMANCE_TARGETS),
        "pair_count_per_case": PAIRED_REPEAT_COUNT,
        "worker_process_count": PAIRED_WORKER_COUNT,
        "isolated_latency_warmups": ISOLATED_LATENCY_WARMUPS,
        "isolated_latency_samples": ISOLATED_LATENCY_SAMPLES,
        "isolated_allocation_warmups": ISOLATED_ALLOCATION_WARMUPS,
        "isolated_allocation_samples": ISOLATED_ALLOCATION_SAMPLES,
        "whole_parser_clock": WHOLE_PARSER_CLOCK,
        "whole_parser_scope": WHOLE_PARSER_SCOPE,
        "execution_order_policy": EXECUTION_ORDER_POLICY,
        "cache_disclaimer": CACHE_DISCLAIMER,
    }
    if any(measurement[field] != value for field, value in expected.items()):
        raise readiness.ReadinessContractError("measurement protocol differs")
    validate_maximum_page_workload(measurement["maximum_page_workload"])
    return True


def validate_policy(policy: Mapping[str, Any]) -> bool:
    """Validate all formulas, ceilings, and semantic-removal allowlists."""

    if not isinstance(policy, Mapping):
        raise readiness.ReadinessContractError("metrics policy is not an object")
    _exact_keys(policy, POLICY_FIELDS, "policy")
    expected = {
        "policy_id": POLICY_ID,
        "quantile_method": QUANTILE_METHOD,
        "quantile_formula": QUANTILE_FORMULA,
        "paired_fixed_ceilings_seconds": dict(PAIRED_FIXED_CEILINGS_SECONDS),
        "relative_ceiling_fraction": 0.05,
        "peak_rss_delta_ceiling_bytes": PEAK_RSS_DELTA_CEILING_BYTES,
        "source_extraction_p95_ceiling_seconds": (
            ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
        ),
        "projection_p95_ceiling_seconds": ISOLATED_PROJECTION_P95_SECONDS,
        "peak_allocation_ceiling_bytes": PEAK_ALLOCATION_CEILING_BYTES,
        "source_report_size_ceiling_bytes": int(RESOURCE_LIMITS["report_json_bytes"]),
        "timing_paths_removed": list(TIMING_PATHS_REMOVED),
        "source_report_timing_paths_removed": list(SOURCE_REPORT_TIMING_PATHS_REMOVED),
        "artifact_semantic_fields_removed": list(ARTIFACT_SEMANTIC_FIELDS_REMOVED),
    }
    if dict(policy) != expected:
        raise readiness.ReadinessContractError("metrics policy differs")
    return True


def validate_settings_delta(settings: Mapping[str, Any]) -> bool:
    """Validate exact flag-off/on objects, hashes, and one-field delta."""

    if not isinstance(settings, Mapping):
        raise readiness.ReadinessContractError("settings delta is not an object")
    _exact_keys(settings, SETTINGS_DELTA_FIELDS, "settings_delta")
    off = settings["flag_off"]
    on = settings["flag_on"]
    if (
        not isinstance(off, Mapping)
        or not isinstance(on, Mapping)
        or set(off) != set(SETTINGS_FLAG_NAMES)
        or set(on) != set(SETTINGS_FLAG_NAMES)
    ):
        raise readiness.ReadinessContractError("settings flag set differs")
    predecessor_match = all(
        off[name] is True and on[name] is True for name in PREDECESSOR_FLAG_NAMES
    )
    if (
        settings["changed_fields"] != ["layout_running_regions_enabled"]
        or dict(off) != dict(_EXPECTED_SETTINGS_OFF)
        or dict(on) != dict(_EXPECTED_SETTINGS_ON)
        or settings["flag_off_sha256"] != _sha256_json(off)
        or settings["flag_on_sha256"] != _sha256_json(on)
        or settings["predecessor_flags_match"] is not predecessor_match
    ):
        raise readiness.ReadinessContractError("settings custody differs")
    return predecessor_match


def validate_m0_reference(
    reference: Mapping[str, Any],
    *,
    observed_identity: Mapping[str, Any] | None = None,
    require_observed: bool = False,
) -> bool:
    """Validate the exact M0 source identity and both frozen target guards."""

    if not isinstance(reference, Mapping):
        raise readiness.ReadinessContractError("M0 reference is not an object")
    _exact_keys(reference, M0_REFERENCE_FIELDS, "m0_reference")
    targets = reference["targets"]
    if not isinstance(targets, Mapping) or set(targets) != set(PERFORMANCE_TARGETS):
        raise readiness.ReadinessContractError("M0 target set differs")
    for target_id, record in targets.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("M0 target differs")
        _exact_keys(record, M0_TARGET_FIELDS, f"m0_reference.{target_id}")
    if dict(reference) != _strict_detach(M0_ARTIFACT):
        raise readiness.ReadinessContractError("M0 reference differs")
    claimed_identity = {field: reference[field] for field in CODE_FILE_IDENTITY_FIELDS}
    if observed_identity is None:
        if require_observed:
            raise readiness.ReadinessContractError(
                "observed M0 baseline custody is required"
            )
    elif _strict_detach(observed_identity) != claimed_identity:
        raise readiness.ReadinessContractError("observed M0 baseline custody differs")
    return True


def _validate_source_identity(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError(f"{path} is not an object")
    _exact_keys(value, SOURCE_IDENTITY_FIELDS, path)
    relative = _validate_nonempty_string(value["path"], f"{path}.path")
    normalized = PurePosixPath(relative)
    if (
        normalized.is_absolute()
        or ".." in normalized.parts
        or str(normalized) != relative
    ):
        raise readiness.ReadinessContractError(f"{path}.path differs")
    _nonnegative_int(value["size_bytes"], f"{path}.size_bytes")
    _validate_sha256(value["sha256"], f"{path}.sha256")
    _positive_int(value["page_count"], f"{path}.page_count")
    return dict(value)


def _claimed_input_file_custody(custody: Mapping[str, Any]) -> dict[str, Any]:
    registry = custody["corpus_registry"]
    return {
        "corpus_registry": {
            field: registry[field] for field in CODE_FILE_IDENTITY_FIELDS
        },
        "sources": {
            case_id: {field: identity[field] for field in CODE_FILE_IDENTITY_FIELDS}
            for case_id, identity in custody["post"].items()
        },
    }


def validate_input_custody(
    custody: Mapping[str, Any],
    *,
    observed_custody: Mapping[str, Any] | None = None,
    require_observed: bool = False,
) -> bool:
    """Validate all 15 pre/post sources, exact derived totals, and registry seal."""

    if not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("input custody is not an object")
    _exact_keys(custody, INPUT_CUSTODY_FIELDS, "input_custody")
    if custody["corpus_registry"] != frozen_oracle.CORPUS_REGISTRY_CUSTODY:
        raise readiness.ReadinessContractError("corpus registry custody differs")
    pre = custody["pre"]
    post = custody["post"]
    expected_cases = set(frozen_oracle.SOURCE_IDENTITIES)
    if (
        not isinstance(pre, Mapping)
        or not isinstance(post, Mapping)
        or set(pre) != expected_cases
        or set(post) != expected_cases
    ):
        raise readiness.ReadinessContractError("input source set differs")
    for phase, records in (("pre", pre), ("post", post)):
        for case_id, identity in records.items():
            _validate_source_identity(identity, f"input_custody.{phase}.{case_id}")
    source_count = len(post)
    page_count = sum(record["page_count"] for record in post.values())
    total_size = sum(record["size_bytes"] for record in post.values())
    expected_match = (
        dict(pre) == frozen_oracle.SOURCE_IDENTITIES
        and dict(post) == frozen_oracle.SOURCE_IDENTITIES
    )
    pre_post_match = dict(pre) == dict(post)
    if (
        custody["source_count"] != source_count
        or custody["page_count"] != page_count
        or custody["total_size_bytes"] != total_size
        or custody["all_expected_match"] is not expected_match
        or custody["pre_post_match"] is not pre_post_match
    ):
        raise readiness.ReadinessContractError("input custody algebra differs")
    if observed_custody is None:
        if require_observed:
            raise readiness.ReadinessContractError(
                "observed input file custody is required"
            )
    elif _strict_detach(observed_custody) != _claimed_input_file_custody(custody):
        raise readiness.ReadinessContractError("observed input file custody differs")
    return expected_match and pre_post_match


def validate_predecessor_custody(
    custody: Mapping[str, Any],
    *,
    observed_outputs: Mapping[str, Mapping[str, Any]] | None = None,
    require_observed: bool = False,
) -> bool:
    """Validate all sealed post-US07 outputs, configuration, and totals."""

    if not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("predecessor custody is not an object")
    _exact_keys(custody, PREDECESSOR_CUSTODY_FIELDS, "predecessor_custody")
    outputs = custody["outputs"]
    configuration = custody["configuration"]
    if (
        not isinstance(outputs, Mapping)
        or set(outputs) != set(frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES)
        or not isinstance(configuration, Mapping)
        or set(configuration) != set(PREDECESSOR_FLAG_NAMES)
    ):
        raise readiness.ReadinessContractError("predecessor member set differs")
    for case_id, identity in outputs.items():
        if not isinstance(identity, Mapping):
            raise readiness.ReadinessContractError(
                "predecessor output identity differs"
            )
        _exact_keys(
            identity,
            PREDECESSOR_OUTPUT_FIELDS,
            f"predecessor_custody.outputs.{case_id}",
        )
        _nonnegative_int(identity["size_bytes"], "predecessor output size")
        _validate_sha256(identity["sha256"], "predecessor output SHA-256")
    output_count = len(outputs)
    total_size = sum(record["size_bytes"] for record in outputs.values())
    expected_match = (
        custody["root"] == frozen_oracle.PREDECESSOR_OUTPUT_ROOT
        and dict(outputs) == frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES
        and dict(configuration) == frozen_oracle.PREDECESSOR_CONFIGURATION
    )
    if (
        custody["output_count"] != output_count
        or custody["total_size_bytes"] != total_size
        or custody["all_expected_match"] is not expected_match
    ):
        raise readiness.ReadinessContractError("predecessor custody algebra differs")
    if observed_outputs is None:
        if require_observed:
            raise readiness.ReadinessContractError(
                "observed predecessor output custody is required"
            )
    elif _strict_detach(observed_outputs) != _strict_detach(outputs):
        raise readiness.ReadinessContractError(
            "observed predecessor output custody differs"
        )
    return expected_match


def validate_component_custody(
    name: str,
    custody: Mapping[str, Any],
    *,
    code_post: Mapping[str, Any],
) -> bool:
    """Bind one sealed oracle/contract/synthetic record to final code custody."""

    if name not in COMPONENT_PATHS or not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("component custody differs")
    _exact_keys(custody, SEALED_COMPONENT_CUSTODY_FIELDS, name)
    expected_path = COMPONENT_PATHS[name]
    file_identity = {
        "path": custody["path"],
        "size_bytes": custody["size_bytes"],
        "sha256": custody["sha256"],
    }
    _validate_file_identity(expected_path, file_identity, name)
    _validate_sha256(custody["semantic_sha256"], f"{name}.semantic_sha256")
    _validate_sha256(
        custody["expected_semantic_sha256"],
        f"{name}.expected_semantic_sha256",
    )
    if (
        expected_path not in code_post
        or dict(code_post[expected_path]) != file_identity
    ):
        raise readiness.ReadinessContractError(f"{name} is not bound to code custody")
    expected_semantic = COMPONENT_EXPECTED_SEMANTIC_SHA256[name]
    match = (
        custody["expected_semantic_sha256"] == expected_semantic
        and custody["semantic_sha256"] == expected_semantic
    )
    if custody["match"] is not match:
        raise readiness.ReadinessContractError(f"{name} match algebra differs")
    return match


def _validate_historical_component_custody(
    name: str,
    custody: Mapping[str, Any],
    *,
    code_post: Mapping[str, Any],
) -> bool:
    """Validate an immutable component against its own recorded code epoch."""

    if name not in COMPONENT_PATHS or not isinstance(custody, Mapping):
        raise readiness.ReadinessContractError("historical component custody differs")
    _exact_keys(custody, SEALED_COMPONENT_CUSTODY_FIELDS, name)
    expected_path = COMPONENT_PATHS[name]
    file_identity = {
        "path": custody["path"],
        "size_bytes": custody["size_bytes"],
        "sha256": custody["sha256"],
    }
    _validate_file_identity(expected_path, file_identity, name)
    _validate_sha256(custody["semantic_sha256"], f"{name}.semantic_sha256")
    _validate_sha256(
        custody["expected_semantic_sha256"],
        f"{name}.expected_semantic_sha256",
    )
    if (
        expected_path not in code_post
        or dict(code_post[expected_path]) != file_identity
    ):
        raise readiness.ReadinessContractError(
            f"historical {name} is not bound to code custody"
        )
    match = custody["semantic_sha256"] == custody["expected_semantic_sha256"]
    if custody["match"] is not match:
        raise readiness.ReadinessContractError(
            f"historical {name} match algebra differs"
        )
    return match


def validate_isolated_stage(
    value: Mapping[str, Any],
    *,
    stage: str,
    complete: bool,
    allow_successful_target_prefix: bool = False,
) -> bool:
    """Validate exact warmup/sample order, every output, summary, and custody."""

    if stage not in {"source_extraction", "running_region_projection"}:
        raise readiness.ReadinessContractError("isolated stage differs")
    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError(f"{stage} is not an object")
    _exact_keys(value, ISOLATED_STAGE_FIELDS, stage)
    targets = value["targets"]
    if not isinstance(targets, Mapping) or not set(targets) <= set(PERFORMANCE_TARGETS):
        raise readiness.ReadinessContractError(f"{stage} target set differs")
    expected_target_prefix = set(PERFORMANCE_TARGETS[: len(targets)])
    if set(targets) != expected_target_prefix:
        raise readiness.ReadinessContractError(f"{stage} target order/prefix differs")
    if complete and set(targets) != set(PERFORMANCE_TARGETS):
        raise readiness.ReadinessContractError(f"{stage} is incomplete")
    _require_bool(value["all_pass"], f"{stage}.all_pass")
    passed_targets: list[bool] = []
    for target_id, record in targets.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError(f"{stage} target differs")
        _exact_keys(record, ISOLATED_TARGET_FIELDS, f"{stage}.{target_id}")
        protocol = record["protocol"]
        readiness.validate_isolated_measurement_protocol(protocol)
        if protocol["stage"] != stage or protocol["target_id"] != target_id:
            raise readiness.ReadinessContractError(f"{stage} protocol identity differs")
        latency = record["latency_seconds"]
        allocations = record["allocation_bytes"]
        report_sizes = record["report_sizes"]
        measured_outputs = record["measured_outputs"]
        if (
            not isinstance(latency, list)
            or len(latency) > ISOLATED_LATENCY_SAMPLES
            or not isinstance(allocations, list)
            or len(allocations) > ISOLATED_ALLOCATION_SAMPLES
            or not isinstance(report_sizes, list)
            or not isinstance(measured_outputs, list)
            or len(measured_outputs)
            > ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES
        ):
            raise readiness.ReadinessContractError(f"{stage} sample collection differs")
        latency_values = [
            _finite_nonnegative(sample, f"{stage}.latency") for sample in latency
        ]
        allocation_values = [
            _nonnegative_int(sample, f"{stage}.allocation") for sample in allocations
        ]
        report_values = [
            _nonnegative_int(sample, f"{stage}.report_size") for sample in report_sizes
        ]
        warmups = _closed_boolean_list(
            record["warmup_successes"],
            f"{stage}.warmup_successes",
            maximum=ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS,
        )
        measured = _closed_boolean_list(
            record["measured_output_successes"],
            f"{stage}.measured_output_successes",
            maximum=ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES,
        )
        if allocation_values and len(latency_values) != ISOLATED_LATENCY_SAMPLES:
            raise readiness.ReadinessContractError(
                f"{stage} allocation samples precede latency completion"
            )
        expected_output_order = [
            ("latency", index) for index in range(len(latency_values))
        ] + [("allocation", index) for index in range(len(allocation_values))]
        if len(measured_outputs) != len(expected_output_order) or len(measured) != len(
            expected_output_order
        ):
            raise readiness.ReadinessContractError(
                f"{stage} measured output coverage differs"
            )
        normalized_outputs: list[dict[str, Any]] = []
        for output_index, (output, expected_order) in enumerate(
            zip(measured_outputs, expected_output_order)
        ):
            if not isinstance(output, Mapping):
                raise readiness.ReadinessContractError(
                    f"{stage} measured output differs"
                )
            _exact_keys(
                output,
                ISOLATED_MEASURED_OUTPUT_FIELDS,
                f"{stage}.measured_outputs.{output_index}",
            )
            sample_index = _nonnegative_int(
                output["sample_index"],
                f"{stage}.measured_outputs.{output_index}.sample_index",
            )
            if (
                output["measurement_kind"],
                sample_index,
            ) != expected_order:
                raise readiness.ReadinessContractError(
                    f"{stage} measured output order differs"
                )
            _validate_output_identity(
                output["output_identity"],
                f"{stage}.measured_outputs.{output_index}.output_identity",
            )
            if stage == "source_extraction":
                if (
                    output["maximum_page_identity_json_bytes"] is not None
                    or output["maximum_running_descriptor_json_bytes"] is not None
                ):
                    raise readiness.ReadinessContractError(
                        "source extraction measured output maxima differ"
                    )
            else:
                _nonnegative_int(
                    output["maximum_page_identity_json_bytes"],
                    f"{stage}.measured_outputs.{output_index}.page maximum",
                )
                _nonnegative_int(
                    output["maximum_running_descriptor_json_bytes"],
                    f"{stage}.measured_outputs.{output_index}.descriptor maximum",
                )
            normalized_outputs.append(dict(output))
        retained_output = record["retained_output"]
        _validate_output_identity(retained_output, f"{stage}.retained_output")
        if not normalized_outputs or dict(retained_output) != dict(
            normalized_outputs[-1]["output_identity"]
        ):
            raise readiness.ReadinessContractError(
                f"{stage} retained output identity differs"
            )
        if stage == "source_extraction":
            expected_report_sizes = [
                output["output_identity"]["size_bytes"] for output in normalized_outputs
            ]
            report_shape = report_values == expected_report_sizes
            report_gate = report_shape and all(
                size <= int(RESOURCE_LIMITS["report_json_bytes"])
                for size in report_values
            )
            predecessor_unchanged = _require_nullable_bool(
                record["predecessor_unchanged"],
                f"{stage}.predecessor_unchanged",
            )
            idempotent = _require_nullable_bool(
                record["idempotent"], f"{stage}.idempotent"
            )
            projection_custody = predecessor_unchanged is None and idempotent is None
        else:
            report_shape = report_values == []
            report_gate = report_shape
            predecessor_unchanged = _require_bool(
                record["predecessor_unchanged"],
                f"{stage}.predecessor_unchanged",
            )
            idempotent = _require_bool(record["idempotent"], f"{stage}.idempotent")
            projection_custody = predecessor_unchanged and idempotent
        if not report_shape:
            raise readiness.ReadinessContractError(f"{stage} report sizes differ")
        if len(latency_values) < ISOLATED_LATENCY_SAMPLES:
            valid_warmup_count = len(warmups) == ISOLATED_LATENCY_WARMUPS
        elif allocation_values:
            valid_warmup_count = len(warmups) == (
                ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS
            )
        else:
            valid_warmup_count = len(warmups) in {
                ISOLATED_LATENCY_WARMUPS,
                ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS,
            }
        successful_warmup_prefix = warmups[:ISOLATED_LATENCY_WARMUPS] == [
            True
        ] * ISOLATED_LATENCY_WARMUPS and (
            not allocation_values
            or warmups[-ISOLATED_ALLOCATION_WARMUPS:]
            == [True] * ISOLATED_ALLOCATION_WARMUPS
        )
        measured_failure_positions = [
            index for index, succeeded in enumerate(measured) if not succeeded
        ]
        if (
            normalized_outputs
            and (not valid_warmup_count or not successful_warmup_prefix)
        ) or (
            measured_failure_positions
            and measured_failure_positions != [len(measured) - 1]
        ):
            raise readiness.ReadinessContractError(
                f"{stage} warmup/output order differs"
            )
        sample_complete = (
            len(latency_values) == ISOLATED_LATENCY_SAMPLES
            and len(allocation_values) == ISOLATED_ALLOCATION_SAMPLES
            and len(warmups) == ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS
            and len(measured) == ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES
            and len(normalized_outputs)
            == ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES
        )
        p95 = _inclusive_p95(latency_values) if latency_values else None
        peak = max(allocation_values) if allocation_values else None
        latency_ceiling = (
            ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
            if stage == "source_extraction"
            else ISOLATED_PROJECTION_P95_SECONDS
        )
        summary = record["summary"]
        if not isinstance(summary, Mapping):
            raise readiness.ReadinessContractError(f"{stage} summary differs")
        _exact_keys(summary, ISOLATED_SUMMARY_FIELDS, f"{stage}.summary")
        page_count = _positive_int(summary["page_count"], f"{stage}.summary.page_count")
        expected_page_count = int(
            frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"]
        )
        if stage == "source_extraction":
            comparison_count = summary["comparison_count"]
            maximum_page_comparisons = summary["maximum_page_comparisons"]
            comparison_gate = (
                comparison_count is None and maximum_page_comparisons is None
            )
        else:
            comparison_count = _nonnegative_int(
                summary["comparison_count"],
                f"{stage}.summary.comparison_count",
            )
            maximum_page_comparisons = _nonnegative_int(
                summary["maximum_page_comparisons"],
                f"{stage}.summary.maximum_page_comparisons",
            )
            comparison_gate = _comparison_counts_are_coherent(
                page_count,
                comparison_count,
                maximum_page_comparisons,
            )
        passed = (
            sample_complete
            and all(warmups)
            and all(measured)
            and p95 is not None
            and p95 <= latency_ceiling
            and peak is not None
            and peak <= PEAK_ALLOCATION_CEILING_BYTES
            and report_gate
            and projection_custody
            and page_count == expected_page_count
            and comparison_gate
        )
        _require_bool(summary["passed"], f"{stage}.summary.passed")
        expected_summary = {
            "stage": stage,
            "target_id": target_id,
            "page_count": expected_page_count,
            "comparison_count": comparison_count,
            "maximum_page_comparisons": maximum_page_comparisons,
            "latency_p95_seconds": p95,
            "peak_allocation_bytes": peak,
            "passed": passed,
        }
        if dict(summary) != expected_summary:
            raise readiness.ReadinessContractError(f"{stage} summary algebra differs")
        passed_targets.append(passed)
    coverage_passed = set(targets) == set(PERFORMANCE_TARGETS)
    if allow_successful_target_prefix:
        coverage_passed = bool(targets)
    all_pass = coverage_passed and all(passed_targets)
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError(f"{stage} aggregate differs")
    return all_pass


def _validate_deadline_record(
    name: str,
    record: Any,
    path: str,
) -> bool:
    if not isinstance(record, Mapping):
        raise readiness.ReadinessContractError(f"{path} differs")
    _exact_keys(record, DEADLINE_BOUNDARY_FIELDS, path)
    limit_seconds = DEADLINE_LIMITS_SECONDS.get(name)
    if limit_seconds is None:
        raise readiness.ReadinessContractError(f"{path} identity differs")
    expected_limit_ns = round(limit_seconds * 1_000_000_000)
    exact_accepted = _validate_acceptance_outcome(
        record["exact_accepted"],
        record["exact_outcome"],
        f"{path}.exact",
    )
    maximum_plus_one_refused = _require_bool(
        record["maximum_plus_one_refused"],
        f"{path}.maximum_plus_one_refused",
    )
    _validate_acceptance_outcome(
        not maximum_plus_one_refused,
        record["maximum_plus_one_outcome"],
        f"{path}.maximum_plus_one",
    )
    passed = exact_accepted and maximum_plus_one_refused
    _require_bool(record["passed"], f"{path}.passed")
    if (
        record["name"] != name
        or not isinstance(record["production_hook"], str)
        or not record["production_hook"].strip()
        or record["limit_seconds"] != limit_seconds
        or record["limit_ns"] != expected_limit_ns
        or record["maximum_plus_one_delta_ns"] != 1_000
        or record["exact_clock_calls"] != 2
        or record["maximum_plus_one_clock_calls"] != 2
        or record["passed"] is not passed
    ):
        raise readiness.ReadinessContractError(f"{path} algebra differs")
    return passed


def validate_maximum_page_execution(value: Mapping[str, Any]) -> bool:
    """Validate proof that the named payload reached accounting and page timer."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError(
            "maximum page execution is not an object"
        )
    _exact_keys(value, MAXIMUM_PAGE_EXECUTION_FIELDS, "maximum_page_execution")
    validate_maximum_page_workload(value["workload"])
    validate_maximum_page_workload(value["accounted_workload"])
    for field in ("resource_accounting_hook", "page_deadline_hook"):
        _validate_nonempty_string(value[field], f"maximum_page_execution.{field}")
    resource_accounting_accepted = _require_bool(
        value["resource_accounting_accepted"],
        "maximum_page_execution.resource_accounting_accepted",
    )
    _require_bool(value["passed"], "maximum_page_execution.passed")
    deadline = value["page_deadline"]
    deadline_passed = _validate_deadline_record(
        "projection_page_deadline",
        deadline,
        "maximum_page_execution.page_deadline",
    )
    passed = (
        dict(value["workload"]) == dict(value["accounted_workload"])
        and resource_accounting_accepted
        and deadline_passed
        and deadline["production_hook"] == value["page_deadline_hook"]
    )
    if value["passed"] is not passed:
        raise readiness.ReadinessContractError("maximum page execution algebra differs")
    return passed


def validate_resource_boundaries(
    value: Mapping[str, Any],
    *,
    complete: bool,
) -> bool:
    """Validate exact/max+1 evidence for every integral resource counter."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("resource boundaries is not an object")
    _exact_keys(value, RESOURCE_BOUNDARIES_FIELDS, "resource_boundaries")
    _require_bool(value["all_pass"], "resource_boundaries.all_pass")
    cases = value["cases"]
    if not isinstance(cases, Mapping) or not set(cases) <= set(RESOURCE_COUNTERS):
        raise readiness.ReadinessContractError("resource boundary set differs")
    if complete and set(cases) != set(RESOURCE_COUNTERS):
        raise readiness.ReadinessContractError("resource boundaries are incomplete")
    case_passes: list[bool] = []
    for counter, record in cases.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("resource boundary differs")
        _exact_keys(
            record,
            RESOURCE_BOUNDARY_FIELDS,
            f"resource_boundaries.{counter}",
        )
        limit = int(RESOURCE_LIMITS[counter])
        exact_accepted = _validate_acceptance_outcome(
            record["exact_accepted"],
            record["exact_outcome"],
            f"resource_boundaries.{counter}.exact",
        )
        maximum_plus_one_refused = _require_bool(
            record["maximum_plus_one_refused"],
            f"resource_boundaries.{counter}.maximum_plus_one_refused",
        )
        _validate_acceptance_outcome(
            not maximum_plus_one_refused,
            record["maximum_plus_one_outcome"],
            f"resource_boundaries.{counter}.maximum_plus_one",
        )
        passed = exact_accepted and maximum_plus_one_refused
        _require_bool(record["passed"], f"resource_boundaries.{counter}.passed")
        if (
            record["counter"] != counter
            or not isinstance(record["production_hook"], str)
            or not record["production_hook"].strip()
            or record["limit"] != limit
            or record["exact_observed"] != limit
            or record["maximum_plus_one_observed"] != limit + 1
            or record["passed"] is not passed
        ):
            raise readiness.ReadinessContractError(
                f"resource boundary {counter} algebra differs"
            )
        case_passes.append(passed)
    maximum_page_passed = validate_maximum_page_execution(
        value["maximum_page_execution"]
    )
    all_pass = (
        set(cases) == set(RESOURCE_COUNTERS)
        and len(case_passes) == len(RESOURCE_COUNTERS)
        and all(case_passes)
        and maximum_page_passed
    )
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError("resource aggregate differs")
    return all_pass


def validate_deadline_boundaries(
    value: Mapping[str, Any],
    *,
    complete: bool,
) -> bool:
    """Validate every exact/+1 injected production deadline witness."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("deadline boundaries is not an object")
    _exact_keys(value, DEADLINE_BOUNDARIES_FIELDS, "deadline_boundaries")
    _require_bool(value["all_pass"], "deadline_boundaries.all_pass")
    cases = value["cases"]
    if not isinstance(cases, Mapping) or not set(cases) <= set(DEADLINE_LIMITS_SECONDS):
        raise readiness.ReadinessContractError("deadline boundary set differs")
    if complete and set(cases) != set(DEADLINE_LIMITS_SECONDS):
        raise readiness.ReadinessContractError("deadline boundaries are incomplete")
    passes = [
        _validate_deadline_record(name, record, f"deadline_boundaries.{name}")
        for name, record in cases.items()
    ]
    all_pass = (
        set(cases) == set(DEADLINE_LIMITS_SECONDS)
        and len(passes) == len(DEADLINE_LIMITS_SECONDS)
        and all(passes)
    )
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError("deadline aggregate differs")
    return all_pass


def validate_paired_parser(
    value: Mapping[str, Any],
    *,
    complete: bool,
    allow_successful_target_prefix: bool = False,
) -> bool:
    """Validate exact plan order, fresh PID custody, raw samples, and summaries."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("paired parser is not an object")
    _exact_keys(value, PAIRED_PARSER_FIELDS, "paired_parser")
    _require_bool(value["all_pass"], "paired_parser.all_pass")
    runner_pid = _positive_int(value["runner_pid"], "paired_parser.runner_pid")
    plan = value["worker_plan"]
    workers = value["workers"]
    targets = value["targets"]
    expected_plan = [_strict_detach(item) for item in readiness.paired_worker_plan()]
    if (
        not isinstance(plan, list)
        or plan != expected_plan[: len(plan)]
        or not isinstance(workers, list)
        or len(workers) != len(plan)
        or not isinstance(targets, Mapping)
        or not set(targets) <= set(PERFORMANCE_TARGETS)
    ):
        raise readiness.ReadinessContractError("paired parser plan differs")
    if complete and plan != expected_plan:
        raise readiness.ReadinessContractError("paired parser is incomplete")
    pids: set[int] = set()
    normalized_workers: list[Mapping[str, Any]] = []
    for index, (work, record) in enumerate(zip(plan, workers)):
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("paired worker record differs")
        _exact_keys(
            record,
            PAIRED_WORKER_RECORD_FIELDS,
            f"paired_parser.workers.{index}",
        )
        if any(record[field] != work[field] for field in work):
            raise readiness.ReadinessContractError("paired worker identity differs")
        pid = _positive_int(record["pid"], "paired worker PID")
        if pid == runner_pid or pid in pids or record["parent_pid"] != runner_pid:
            raise readiness.ReadinessContractError(
                "paired worker distinct process custody differs"
            )
        pids.add(pid)
        output_variants = record["output_variants"]
        if not isinstance(output_variants, Mapping) or set(output_variants) != set(
            OUTPUT_VARIANTS
        ):
            raise readiness.ReadinessContractError(
                "paired worker output variants differ"
            )
        for variant, identity in output_variants.items():
            _validate_output_identity(
                identity,
                f"paired_parser.workers.{index}.output_variants.{variant}",
            )
        wall = _finite_nonnegative(record["wall_seconds"], "paired worker wall")
        exit_code = record["exit_code"]
        if (
            isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code != 0
            or any(
                record[field] is not True
                for field in (
                    "source_match",
                    "code_match",
                    "custody_match",
                    "imports_loaded_before_timing",
                    "settings_loaded_before_timing",
                    "source_verified_before_timing",
                )
            )
            or record["timing_clock"] != WHOLE_PARSER_CLOCK
            or record["timing_scope"] != WHOLE_PARSER_SCOPE
            or record["rss_bytes"]
            != _rss_bytes_from_maxrss(
                record["raw_ru_maxrss"], platform_name=record["platform"]
            )
        ):
            raise readiness.ReadinessContractError(
                "paired worker sample/custody differs"
            )
        if record["wall_seconds"] != wall:
            raise readiness.ReadinessContractError("paired worker wall type differs")
        normalized_workers.append(record)
    complete_workers = plan == expected_plan and len(pids) == PAIRED_WORKER_COUNT
    completed_target_ids: tuple[str, ...] = (
        PERFORMANCE_TARGETS if complete_workers else ()
    )
    successful_workers = complete_workers
    if allow_successful_target_prefix and not complete_workers:
        for target_count in range(1, len(PERFORMANCE_TARGETS)):
            candidate_targets = PERFORMANCE_TARGETS[:target_count]
            candidate_plan = [
                work for work in expected_plan if work["target_id"] in candidate_targets
            ]
            if plan == candidate_plan and len(pids) == len(candidate_plan):
                completed_target_ids = candidate_targets
                successful_workers = True
                break
    expected_summaries: dict[str, dict[str, Any]] = {}
    if successful_workers:
        for target_id in completed_target_ids:
            by_state = {
                state: [
                    record
                    for record in normalized_workers
                    if record["target_id"] == target_id and record["state"] == state
                ]
                for state in ("off", "on")
            }
            expected_summaries[target_id] = _strict_detach(
                _paired_performance_summary(
                    target_id,
                    off_seconds=[item["wall_seconds"] for item in by_state["off"]],
                    on_seconds=[item["wall_seconds"] for item in by_state["on"]],
                    off_rss_bytes=[item["rss_bytes"] for item in by_state["off"]],
                    on_rss_bytes=[item["rss_bytes"] for item in by_state["on"]],
                )
            )
    if dict(targets) != expected_summaries:
        raise readiness.ReadinessContractError("paired summary algebra differs")
    all_pass = successful_workers and all(
        summary["passed"] is True for summary in expected_summaries.values()
    )
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError("paired aggregate differs")
    return all_pass


def validate_quality(value: Mapping[str, Any]) -> bool:
    """Validate the fixed reviewed denominators and every zero-defect gate."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("quality is not an object")
    _exact_keys(value, QUALITY_FIELDS, "quality")
    count_fields = QUALITY_FIELDS[:-1]
    quality_boolean_fields = {
        "manufacturing_fused_contribution_exact",
        "manufacturing_public_owner_unchanged",
        "manufacturing_source_reconstruction_exact",
        "esg_cluster_exact",
    }
    for field in count_fields:
        if field in quality_boolean_fields:
            _require_bool(value[field], f"quality.{field}")
        else:
            _nonnegative_int(value[field], f"quality.{field}")
    _require_bool(value["all_pass"], "quality.all_pass")
    passed = (
        value["reviewed_page_count"] == 30
        and value["page_identity_exact_count"]
        == value["page_identity_denominator"]
        == 30
        and value["running_region_exact_count"]
        == value["running_region_denominator"]
        == 47
        and value["pairwise_order_exact_count"]
        == value["pairwise_order_denominator"]
        == 47
        and value["manufacturing_header_exact_count"]
        == value["manufacturing_header_denominator"]
        == 3
        and value["manufacturing_fused_contribution_exact"] is True
        and value["manufacturing_public_owner_unchanged"] is True
        and value["manufacturing_source_reconstruction_exact"] is True
        and value["esg_cluster_exact"] is True
        and value["false_printed_label_promotions"] == 0
        and value["duplicate_canonical_contributions"] == 0
        and value["missing_canonical_contributions"] == 0
        and value["legacy_identity_mismatches"] == 0
        and value["determinism_failures"] == 0
    )
    if value["all_pass"] is not passed:
        raise readiness.ReadinessContractError("quality aggregate differs")
    return passed


def validate_control_matrix(
    value: Mapping[str, Any],
    *,
    complete: bool,
) -> bool:
    """Validate all-corpus observed counts against the frozen oracle matrix."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("control matrix is not an object")
    _exact_keys(value, CONTROL_MATRIX_FIELDS, "control_matrix")
    cases = value["cases"]
    if not isinstance(cases, Mapping) or not set(cases) <= set(_CONTROL_EXPECTATIONS):
        raise readiness.ReadinessContractError("control matrix case set differs")
    if complete and set(cases) != set(_CONTROL_EXPECTATIONS):
        raise readiness.ReadinessContractError("control matrix is incomplete")
    _require_bool(value["all_pass"], "control_matrix.all_pass")
    passes: list[bool] = []
    for case_id, record in cases.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("control case differs")
        _exact_keys(record, CONTROL_CASE_FIELDS, f"control_matrix.{case_id}")
        expected = _CONTROL_EXPECTATIONS[case_id]
        for field in (
            "page_count",
            "expected_detected_labels",
            "observed_detected_labels",
            "expected_running_regions",
            "observed_running_regions",
        ):
            _nonnegative_int(record[field], f"control_matrix.{case_id}.{field}")
        for field in (
            "legacy_identity_match",
            "flag_off_byte_match",
            "canonical_body_match",
            "canonical_full_match",
            "passed",
        ):
            _require_bool(record[field], f"control_matrix.{case_id}.{field}")
        passed = (
            record["case_id"] == case_id
            and record["page_count"] == expected["page_count"]
            and record["expected_detected_labels"] == expected["detected_labels"]
            and record["observed_detected_labels"] == expected["detected_labels"]
            and record["expected_running_regions"] == expected["running_regions"]
            and record["observed_running_regions"] == expected["running_regions"]
            and record["legacy_identity_match"] is True
            and record["flag_off_byte_match"] is True
            and record["canonical_body_match"] is True
            and record["canonical_full_match"] is True
        )
        if record["passed"] is not passed:
            raise readiness.ReadinessContractError(
                f"control matrix {case_id} algebra differs"
            )
        passes.append(passed)
    all_pass = (
        set(cases) == set(_CONTROL_EXPECTATIONS)
        and len(passes) == len(_CONTROL_EXPECTATIONS)
        and all(passes)
    )
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError("control matrix aggregate differs")
    return all_pass


def validate_comparison_ledgers(
    value: Mapping[str, Any],
    *,
    complete: bool,
    projection_targets: Mapping[str, Any],
    allow_successful_target_prefix: bool = False,
) -> bool:
    """Validate untimed counts and bind them to projection evidence."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("comparison ledgers is not an object")
    _exact_keys(value, COMPARISON_LEDGERS_FIELDS, "comparison_ledgers")
    targets = value["targets"]
    if not isinstance(targets, Mapping) or not set(targets) <= set(PERFORMANCE_TARGETS):
        raise readiness.ReadinessContractError("comparison target set differs")
    if complete and set(targets) != set(PERFORMANCE_TARGETS):
        raise readiness.ReadinessContractError("comparison ledgers are incomplete")
    if set(targets) != set(PERFORMANCE_TARGETS[: len(targets)]):
        raise readiness.ReadinessContractError("comparison target order/prefix differs")
    if not isinstance(projection_targets, Mapping) or not set(targets) <= set(
        projection_targets
    ):
        raise readiness.ReadinessContractError(
            "comparison/projection target coverage differs"
        )
    _require_bool(value["all_pass"], "comparison_ledgers.all_pass")
    passes: list[bool] = []
    for target_id, record in targets.items():
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("comparison ledger differs")
        _exact_keys(
            record,
            COMPARISON_LEDGER_FIELDS,
            f"comparison_ledgers.{target_id}",
        )
        page_count = int(frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"])
        observed_page_count = _nonnegative_int(
            record["page_count"], "comparison page count"
        )
        comparison_count = _nonnegative_int(
            record["comparison_count"], "comparison count"
        )
        maximum_page = _nonnegative_int(
            record["maximum_page_comparisons"], "maximum page comparisons"
        )
        page_ceiling = _positive_int(record["page_ceiling"], "comparison page ceiling")
        document_ceiling = _positive_int(
            record["document_ceiling"], "comparison document ceiling"
        )
        _require_bool(
            record["instrumentation_untimed"],
            f"comparison_ledgers.{target_id}.instrumentation_untimed",
        )
        _require_bool(
            record["indexed_algorithm"],
            f"comparison_ledgers.{target_id}.indexed_algorithm",
        )
        _require_bool(record["passed"], f"comparison_ledgers.{target_id}.passed")
        projection = projection_targets[target_id]
        if not isinstance(projection, Mapping) or not isinstance(
            projection.get("summary"), Mapping
        ):
            raise readiness.ReadinessContractError(
                "comparison projection evidence differs"
            )
        projection_summary = projection["summary"]
        cross_bound = (
            projection_summary.get("page_count") == record["page_count"]
            and projection_summary.get("comparison_count") == comparison_count
            and projection_summary.get("maximum_page_comparisons") == maximum_page
        )
        passed = (
            record["target_id"] == target_id
            and observed_page_count == page_count
            and page_ceiling == int(RESOURCE_LIMITS["comparisons_per_page"])
            and document_ceiling == int(RESOURCE_LIMITS["comparisons_per_document"])
            and comparison_count <= document_ceiling
            and maximum_page <= page_ceiling
            and _comparison_counts_are_coherent(
                page_count, comparison_count, maximum_page
            )
            and record["instrumentation_untimed"] is True
            and record["indexed_algorithm"] is True
            and cross_bound
        )
        if record["passed"] is not passed:
            raise readiness.ReadinessContractError(
                f"comparison ledger {target_id} algebra differs"
            )
        passes.append(passed)
    coverage_passed = set(targets) == set(PERFORMANCE_TARGETS)
    if allow_successful_target_prefix:
        coverage_passed = bool(targets)
    all_pass = coverage_passed and all(passes)
    if value["all_pass"] is not all_pass:
        raise readiness.ReadinessContractError("comparison aggregate differs")
    return all_pass


def validate_rollback(value: Mapping[str, Any]) -> bool:
    """Validate every feature-off, inverse-strip, rollback, and replay witness."""

    if not isinstance(value, Mapping):
        raise readiness.ReadinessContractError("rollback is not an object")
    _exact_keys(value, ROLLBACK_FIELDS, "rollback")
    witness_fields = ROLLBACK_FIELDS[:-1]
    for field in ROLLBACK_FIELDS:
        _require_bool(value[field], f"rollback.{field}")
    passed = all(value[field] is True for field in witness_fields)
    if value["all_pass"] is not passed:
        raise readiness.ReadinessContractError("rollback aggregate differs")
    return passed


def validate_prior_failed_candidates(
    value: Any,
    *,
    status: str,
    retained_path: str,
    observed_prior_artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate exact ordered coverage and observed identities of prior failures."""

    if not isinstance(value, list) or not isinstance(observed_prior_artifacts, Mapping):
        raise readiness.ReadinessContractError("prior failed candidate custody differs")
    observed: dict[str, dict[str, Any]] = {}
    observed_attempts: dict[str, int] = {}
    for path, identity in observed_prior_artifacts.items():
        match = (
            FAILED_ARTIFACT_PATTERN.fullmatch(path) if isinstance(path, str) else None
        )
        if match is None or not isinstance(identity, Mapping):
            raise readiness.ReadinessContractError(
                "observed prior failed candidate identity differs"
            )
        _exact_keys(
            identity,
            OBSERVED_PRIOR_ARTIFACT_FIELDS,
            f"observed_prior_artifacts.{path}",
        )
        if (
            identity["status"] != "failed_measurement_candidate"
            or isinstance(identity["size_bytes"], bool)
            or not isinstance(identity["size_bytes"], int)
            or identity["size_bytes"] <= 0
        ):
            raise readiness.ReadinessContractError(
                "observed prior failed candidate identity differs"
            )
        _validate_sha256(identity["sha256"], "observed prior raw SHA-256")
        _validate_sha256(identity["semantic_sha256"], "observed prior semantic SHA-256")
        observed[path] = dict(identity)
        observed_attempts[path] = int(match.group(1))
    expected_paths = sorted(observed, key=observed_attempts.__getitem__)
    expected_attempts = [observed_attempts[path] for path in expected_paths]
    if expected_attempts != list(range(1, len(expected_attempts) + 1)):
        raise readiness.ReadinessContractError(
            "observed prior failed candidate sequence differs"
        )

    records: list[dict[str, Any]] = []
    for index, record in enumerate(value):
        if not isinstance(record, Mapping):
            raise readiness.ReadinessContractError("prior failure differs")
        _exact_keys(
            record,
            PRIOR_FAILED_CANDIDATE_FIELDS,
            f"prior_failed_candidates.{index}",
        )
        path = record["path"]
        match = (
            FAILED_ARTIFACT_PATTERN.fullmatch(path) if isinstance(path, str) else None
        )
        if (
            match is None
            or record["status"] != "failed_measurement_candidate"
            or isinstance(record["size_bytes"], bool)
            or not isinstance(record["size_bytes"], int)
            or record["size_bytes"] <= 0
        ):
            raise readiness.ReadinessContractError(
                "prior failed candidate identity differs"
            )
        _validate_sha256(record["sha256"], "prior failure SHA-256")
        _validate_sha256(record["semantic_sha256"], "prior failure semantic SHA-256")
        records.append(dict(record))
    if [record["path"] for record in records] != expected_paths:
        raise readiness.ReadinessContractError(
            "prior failed candidate observed coverage differs"
        )
    for record in records:
        path = record["path"]
        if record != {"path": path, **observed[path]}:
            raise readiness.ReadinessContractError(
                "prior failed candidate observed identity differs"
            )
    if status == "failed_measurement_candidate":
        current = FAILED_ARTIFACT_PATTERN.fullmatch(retained_path)
        if current is None or int(current.group(1)) != len(expected_paths) + 1:
            raise readiness.ReadinessContractError(
                "current failed candidate sequence differs"
            )


def discover_existing_metrics_artifact_paths(
    repository_root: Path,
) -> tuple[str, ...]:
    """Discover the complete fixed-name final/prior metrics custody set."""

    root = _resolve_repository_root(repository_root)
    evidence_directory = root
    for part in _EVIDENCE_DIRECTORY.parts:
        evidence_directory = evidence_directory / part
        if evidence_directory.is_symlink():
            raise MetricsExecutionError("metrics evidence directory is a symlink")
        if not evidence_directory.exists():
            return ()
        if not evidence_directory.is_dir():
            raise MetricsExecutionError("metrics evidence directory differs")
    try:
        evidence_directory.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise MetricsExecutionError("metrics evidence directory escaped root") from exc

    failed: list[tuple[int, str]] = []
    final_path: str | None = None
    entry_count = 0
    for entry in evidence_directory.iterdir():
        entry_count += 1
        if entry_count > 4096:
            raise MetricsExecutionError("metrics evidence directory is unbounded")
        relative_path = str(_EVIDENCE_DIRECTORY / entry.name)
        failed_match = FAILED_ARTIFACT_PATTERN.fullmatch(relative_path)
        is_final = relative_path == str(FINAL_ARTIFACT_RELATIVE_PATH)
        if failed_match is None and not is_final:
            continue
        if entry.is_symlink() or not entry.is_file():
            raise MetricsExecutionError("metrics artifact is not a regular file")
        try:
            entry.resolve(strict=True).relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise MetricsExecutionError("metrics artifact escaped root") from exc
        if is_final:
            final_path = relative_path
        else:
            failed.append((int(failed_match.group(1)), relative_path))

    failed.sort()
    attempts = [attempt for attempt, _ in failed]
    if len(failed) > MAX_FAILED_ARTIFACT_ATTEMPTS or attempts != list(
        range(1, len(failed) + 1)
    ):
        raise MetricsExecutionError("failed artifact discovery sequence differs")
    paths = tuple(path for _, path in failed)
    if final_path is not None:
        paths = (*paths, final_path)
    return paths


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant: {value}")


def _closed_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_strict_json(
    raw: bytes,
    *,
    error: str = "prior artifact strict JSON differs",
) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_closed_json_object,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise MetricsExecutionError(error) from exc


def _collect_prior_artifact_identities_with_observations(
    root: Path,
    paths: Sequence[str],
    *,
    observed_code_files: Mapping[str, Mapping[str, Any]],
    observed_dependency_custody: Mapping[str, Any],
    observed_input_custody: Mapping[str, Any],
    observed_m0_identity: Mapping[str, Any],
    observed_predecessor_outputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Validate attempts in order against real code and the exact prior prefix."""

    if (
        not isinstance(paths, (list, tuple))
        or len(paths) > MAX_FAILED_ARTIFACT_ATTEMPTS
        or len(paths) != len(set(paths))
    ):
        raise MetricsExecutionError("prior artifact observation paths differ")
    attempts: list[int] = []
    for path in paths:
        match = (
            FAILED_ARTIFACT_PATTERN.fullmatch(path) if isinstance(path, str) else None
        )
        if match is None:
            raise MetricsExecutionError("prior artifact observation path differs")
        attempts.append(int(match.group(1)))
    if attempts != list(range(1, len(attempts) + 1)):
        raise MetricsExecutionError("prior artifact observation sequence differs")

    observed: dict[str, dict[str, Any]] = {}
    for path in paths:
        raw = _read_bounded_regular_repository_file(
            root,
            PurePosixPath(path),
            maximum_bytes=PRIOR_ARTIFACT_READ_CAP_BYTES,
            error="prior artifact observation is not a regular repository file",
        )
        artifact = _load_strict_json(raw)
        if not isinstance(artifact, Mapping) or raw != _artifact_bytes(artifact):
            raise MetricsExecutionError("prior artifact exclusive-writer bytes differ")
        try:
            semantic_matches = (
                isinstance(artifact, Mapping)
                and artifact.get("status") == "failed_measurement_candidate"
                and artifact.get("retained_path") == path
                and isinstance(artifact.get("semantic_sha256"), str)
                and artifact["semantic_sha256"] == _artifact_semantic_sha256(artifact)
            )
        except (KeyError, TypeError, ValueError, readiness.ReadinessContractError):
            semantic_matches = False
        if not semantic_matches:
            raise MetricsExecutionError("prior artifact semantic custody differs")
        _validate_metrics_artifact_with_observations(
            artifact,
            existing_paths=tuple(observed),
            observed_code_files=observed_code_files,
            observed_dependency_custody=observed_dependency_custody,
            observed_input_custody=observed_input_custody,
            observed_m0_identity=observed_m0_identity,
            observed_predecessor_outputs=observed_predecessor_outputs,
            observed_prior_artifacts=observed,
            historical_custody=True,
        )
        identity = {
            "size_bytes": len(raw),
            "sha256": _sha256_bytes(raw),
            "status": "failed_measurement_candidate",
            "semantic_sha256": artifact["semantic_sha256"],
        }
        observed[path] = identity
    return observed


def collect_prior_artifact_identities(
    repository_root: Path,
    paths: Sequence[str],
    *,
    code_paths: Sequence[str] = tuple(sorted(REQUIRED_CODE_PATHS)),
) -> dict[str, dict[str, Any]]:
    """Observe code and fully validate a bounded sequential failed-artifact set."""

    root = _resolve_repository_root(repository_root)
    observed_code_files = collect_code_file_identities(root, paths=code_paths)
    observed_dependency_custody = collect_dependency_custody(root)
    observed_input_custody = collect_input_file_identities(root)
    observed_m0_identity = collect_m0_reference_identity(root)
    observed_predecessor_outputs = collect_predecessor_output_identities(root)
    return _collect_prior_artifact_identities_with_observations(
        root,
        paths,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
    )


def _validate_failures(value: Any, *, complete: bool) -> bool:
    if not isinstance(value, list):
        raise readiness.ReadinessContractError("failures is not an array")
    for failure in value:
        if not isinstance(failure, Mapping):
            raise readiness.ReadinessContractError("failure record differs")
        _exact_keys(failure, ARTIFACT_FAILURE_FIELDS, "failure")
        failure_type = failure["type"]
        stage = failure["stage"]
        if failure_type not in FAILURE_TYPES or stage not in FAILURE_STAGES:
            raise readiness.ReadinessContractError("failure enum differs")
        if failure["target_id"] not in (*PERFORMANCE_TARGETS, None):
            raise readiness.ReadinessContractError("failure target differs")
        pair_index = failure["pair_index"]
        if pair_index is not None and (
            isinstance(pair_index, bool)
            or not isinstance(pair_index, int)
            or not 0 <= pair_index < PAIRED_REPEAT_COUNT
        ):
            raise readiness.ReadinessContractError("failure pair differs")
        if failure["state"] not in ("off", "on", None):
            raise readiness.ReadinessContractError("failure state differs")
        if failure_type in PAIRED_FAILURE_TYPES:
            if (
                stage != "paired_parser"
                or failure["target_id"] is None
                or pair_index is None
                or failure["state"] is None
            ):
                raise readiness.ReadinessContractError(
                    "paired failure identity differs"
                )
        elif (
            failure_type != "stage_failed"
            or pair_index is not None
            or failure["state"] is not None
            or (stage in TARGET_SCOPED_FAILURE_STAGES and failure["target_id"] is None)
            or (
                stage not in TARGET_SCOPED_FAILURE_STAGES
                and failure["target_id"] is not None
            )
        ):
            raise readiness.ReadinessContractError("stage failure identity differs")
    if complete and value:
        raise readiness.ReadinessContractError("final artifact retained failures")
    return not value


def _validate_target_failure_prefix(
    targets: Mapping[str, Any],
    *,
    expected_target: str,
    failed_target_retained: bool,
    stage: str,
) -> None:
    target_index = PERFORMANCE_TARGETS.index(expected_target)
    prefix_length = target_index + int(failed_target_retained)
    expected_prefix = PERFORMANCE_TARGETS[:prefix_length]
    if len(targets) != len(expected_prefix) or set(targets) != set(expected_prefix):
        raise readiness.ReadinessContractError(
            f"{stage} failure retained target prefix differs"
        )


def _first_output_size_failure_target(artifact: Mapping[str, Any]) -> str | None:
    source_targets = artifact["source_extraction"]["targets"]
    projection_targets = artifact["running_region_projection"]["targets"]
    report_limit = int(RESOURCE_LIMITS["report_json_bytes"])
    page_limit = int(RESOURCE_LIMITS["page_identity_json_bytes"])
    descriptor_limit = int(RESOURCE_LIMITS["running_descriptor_json_bytes"])
    for target_id in PERFORMANCE_TARGETS:
        source_failed = any(
            output["output_identity"]["size_bytes"] > report_limit
            for output in source_targets.get(target_id, {}).get("measured_outputs", ())
        )
        projection_failed = any(
            output["maximum_page_identity_json_bytes"] > page_limit
            or output["maximum_running_descriptor_json_bytes"] > descriptor_limit
            for output in projection_targets.get(target_id, {}).get(
                "measured_outputs", ()
            )
        )
        if source_failed or projection_failed:
            return target_id
    return None


def _validate_output_failure_target_prefix(
    artifact: Mapping[str, Any],
    *,
    failed_target: str,
) -> None:
    target_index = PERFORMANCE_TARGETS.index(failed_target)
    expected_targets = PERFORMANCE_TARGETS[: target_index + 1]
    target_mappings = (
        artifact["source_extraction"]["targets"],
        artifact["running_region_projection"]["targets"],
        artifact["comparison_ledgers"]["targets"],
        artifact["output_sizes"]["source_reports"],
        artifact["output_sizes"]["isolated_projection_outputs"],
        artifact["paired_parser"]["targets"],
        artifact["output_sizes"]["paired_samples"],
    )
    if any(
        len(mapping) != len(expected_targets) or set(mapping) != set(expected_targets)
        for mapping in target_mappings
    ):
        raise readiness.ReadinessContractError(
            "output size failure retained target prefix differs"
        )
    expected_plan = [
        _strict_detach(work)
        for work in readiness.paired_worker_plan()
        if work["target_id"] in expected_targets
    ]
    paired = artifact["paired_parser"]
    if paired["worker_plan"] != expected_plan or len(paired["workers"]) != len(
        expected_plan
    ):
        raise readiness.ReadinessContractError(
            "output size failure retained paired-work prefix differs"
        )


def validate_failure_coherence(
    artifact: Mapping[str, Any],
    *,
    expected_gates: Mapping[str, bool],
) -> None:
    """Bind the one closed failure to the first uncompleted/failed stage evidence."""

    failures = artifact["failures"]
    if artifact["status"] == "final_measurement_candidate":
        if failures:
            raise readiness.ReadinessContractError(
                "final artifact failure coherence differs"
            )
        return
    if len(failures) != 1:
        raise readiness.ReadinessContractError(
            "failed artifact must retain exactly one first failure"
        )
    failure = failures[0]
    stage = failure["stage"]
    if stage not in expected_gates or expected_gates[stage] is not False:
        raise readiness.ReadinessContractError(
            "failure contradicts successful stage evidence"
        )
    first_failed_stage = next(
        (
            candidate_stage
            for candidate_stage in FAILURE_STAGES
            if expected_gates.get(candidate_stage) is False
        ),
        None,
    )
    if first_failed_stage != stage:
        raise readiness.ReadinessContractError(
            "failure is not bound to the first failed stage"
        )
    if stage == "paired_parser":
        workers = artifact["paired_parser"]["workers"]
        expected_plan = [
            _strict_detach(work) for work in readiness.paired_worker_plan()
        ]
        paired = artifact["paired_parser"]
        if failure["type"] in PAIRED_FAILURE_TYPES:
            if len(workers) >= len(expected_plan):
                raise readiness.ReadinessContractError(
                    "paired failure follows a complete successful plan"
                )
            failed_work = expected_plan[len(workers)]
            if any(
                failure[field] != failed_work[field]
                for field in ("target_id", "pair_index", "state")
            ):
                raise readiness.ReadinessContractError(
                    "paired failure next-work identity differs"
                )
        else:
            failed_targets = [
                target_id
                for target_id in PERFORMANCE_TARGETS
                if target_id in paired["targets"]
                and paired["targets"][target_id]["passed"] is False
            ]
            if (
                paired["worker_plan"] != expected_plan
                or len(workers) != len(expected_plan)
                or set(paired["targets"]) != set(PERFORMANCE_TARGETS)
                or not failed_targets
            ):
                raise readiness.ReadinessContractError(
                    "paired stage failure lacks complete failed gate evidence"
                )
            if failure["target_id"] != failed_targets[0]:
                raise readiness.ReadinessContractError(
                    "paired stage failure target identity differs"
                )
    elif stage in {"source_extraction", "running_region_projection"}:
        targets = artifact[stage]["targets"]
        failed_targets = [
            target_id
            for target_id in PERFORMANCE_TARGETS
            if target_id in targets and targets[target_id]["summary"]["passed"] is False
        ]
        if failed_targets:
            expected_target = failed_targets[0]
            failed_target_retained = True
        elif len(targets) < len(PERFORMANCE_TARGETS):
            expected_target = PERFORMANCE_TARGETS[len(targets)]
            failed_target_retained = False
        else:
            raise readiness.ReadinessContractError(
                "isolated failure lacks failed target evidence"
            )
        if failure["target_id"] != expected_target:
            raise readiness.ReadinessContractError(
                "isolated failure target identity differs"
            )
        _validate_target_failure_prefix(
            targets,
            expected_target=expected_target,
            failed_target_retained=failed_target_retained,
            stage=stage,
        )
    elif stage == "comparison_ledgers":
        targets = artifact["comparison_ledgers"]["targets"]
        failed_targets = [
            target_id
            for target_id in PERFORMANCE_TARGETS
            if target_id in targets and targets[target_id]["passed"] is False
        ]
        if failed_targets:
            expected_target = failed_targets[0]
            failed_target_retained = True
        elif len(targets) < len(PERFORMANCE_TARGETS):
            expected_target = PERFORMANCE_TARGETS[len(targets)]
            failed_target_retained = False
        else:
            raise readiness.ReadinessContractError(
                "comparison failure lacks failed target evidence"
            )
        if failure["target_id"] != expected_target:
            raise readiness.ReadinessContractError(
                "comparison failure target identity differs"
            )
        _validate_target_failure_prefix(
            targets,
            expected_target=expected_target,
            failed_target_retained=failed_target_retained,
            stage=stage,
        )
    elif stage == "output_sizes":
        expected_target = _first_output_size_failure_target(artifact)
        if expected_target is None:
            raise readiness.ReadinessContractError(
                "output size failure lacks measured target evidence"
            )
        if failure["target_id"] != expected_target:
            raise readiness.ReadinessContractError(
                "output size failure target identity differs"
            )
        _validate_output_failure_target_prefix(
            artifact,
            failed_target=expected_target,
        )


def validate_aggregate(
    aggregate: Mapping[str, Any],
    *,
    expected_gates: Mapping[str, bool],
    complete: bool,
) -> bool:
    """Bind every named gate and all_pass to recomputed nested evidence."""

    if not isinstance(aggregate, Mapping):
        raise readiness.ReadinessContractError("aggregate is not an object")
    _exact_keys(aggregate, AGGREGATE_FIELDS, "aggregate")
    if set(expected_gates) != set(AGGREGATE_FIELDS) - {"all_pass"}:
        raise MetricsExecutionError("internal aggregate gate set differs")
    all_pass = all(expected_gates.values())
    expected = {**expected_gates, "all_pass": all_pass}
    if dict(aggregate) != expected:
        raise readiness.ReadinessContractError("aggregate algebra differs")
    if complete and not all_pass:
        raise readiness.ReadinessContractError("final aggregate gate failed")
    if not complete and all_pass:
        raise readiness.ReadinessContractError(
            "failed candidate claimed every aggregate gate"
        )
    return all_pass


def validate_output_cross_bindings(artifact: Mapping[str, Any]) -> bool:
    """Bind exact completed work/output coverage and grounded byte maxima."""

    output_sizes = artifact["output_sizes"]
    paired_samples = output_sizes["paired_samples"]
    workers = artifact["paired_parser"]["workers"]
    expected_paired_targets = {worker["target_id"] for worker in workers}
    if set(paired_samples) != expected_paired_targets:
        raise readiness.ReadinessContractError("paired output target coverage differs")
    observed_paired = [
        (
            sample["target_id"],
            sample["pair_index"],
            sample["state"],
            _strict_detach(sample["variants"]),
        )
        for target_id in PERFORMANCE_TARGETS
        for sample in paired_samples.get(target_id, [])
    ]
    expected_paired = [
        (
            worker["target_id"],
            worker["pair_index"],
            worker["state"],
            _strict_detach(worker["output_variants"]),
        )
        for worker in workers
    ]
    if observed_paired != expected_paired:
        raise readiness.ReadinessContractError(
            "paired output global-prefix binding differs"
        )

    source_targets = artifact["source_extraction"]["targets"]
    source_reports = output_sizes["source_reports"]
    if set(source_targets) != set(source_reports):
        raise readiness.ReadinessContractError(
            "source report output target coverage differs"
        )
    for target_id, record in source_targets.items():
        if dict(record["retained_output"]) != dict(source_reports[target_id]):
            raise readiness.ReadinessContractError(
                "source report output identity binding differs"
            )

    projection_targets = artifact["running_region_projection"]["targets"]
    projection_outputs = output_sizes["isolated_projection_outputs"]
    if set(projection_targets) != set(projection_outputs):
        raise readiness.ReadinessContractError(
            "projection output target coverage differs"
        )
    for target_id, record in projection_targets.items():
        if dict(record["retained_output"]) != dict(projection_outputs[target_id]):
            raise readiness.ReadinessContractError(
                "projection output identity binding differs"
            )

    source_report_sizes = [
        measured["output_identity"]["size_bytes"]
        for record in source_targets.values()
        for measured in record["measured_outputs"]
    ]
    page_identity_sizes = [
        measured["maximum_page_identity_json_bytes"]
        for record in projection_targets.values()
        for measured in record["measured_outputs"]
    ]
    descriptor_sizes = [
        measured["maximum_running_descriptor_json_bytes"]
        for record in projection_targets.values()
        for measured in record["measured_outputs"]
    ]
    grounded_maxima = {
        "maximum_source_report_json_bytes": max(source_report_sizes, default=0),
        "maximum_page_identity_json_bytes": max(page_identity_sizes, default=0),
        "maximum_running_descriptor_json_bytes": max(descriptor_sizes, default=0),
    }
    for field, grounded in grounded_maxima.items():
        if output_sizes[field] != grounded:
            raise readiness.ReadinessContractError(
                f"output_sizes.{field} grounded maximum differs"
            )
    return True


def _validate_artifact_value_shapes(
    artifact: Mapping[str, Any],
    *,
    observed_code_files: Mapping[str, Mapping[str, Any]] | None,
    observed_dependency_custody: Mapping[str, Any],
    observed_input_custody: Mapping[str, Any],
    observed_m0_identity: Mapping[str, Any],
    observed_predecessor_outputs: Mapping[str, Mapping[str, Any]],
    observed_prior_artifacts: Mapping[str, Mapping[str, Any]],
    historical_custody: bool = False,
) -> None:
    if not isinstance(artifact, Mapping):
        raise readiness.ReadinessContractError("metrics artifact is not an object")
    _exact_keys(artifact, ARTIFACT_TOP_LEVEL_FIELDS, "metrics_artifact")
    for field in _MAPPING_ARTIFACT_FIELDS:
        if not isinstance(artifact[field], Mapping):
            raise readiness.ReadinessContractError(
                f"metrics_artifact.{field} is not an object"
            )
    for field in _SEQUENCE_ARTIFACT_FIELDS:
        if not isinstance(artifact[field], list):
            raise readiness.ReadinessContractError(
                f"metrics_artifact.{field} is not an array"
            )
    status = artifact["status"]
    if status not in {
        "final_measurement_candidate",
        "failed_measurement_candidate",
    }:
        raise readiness.ReadinessContractError("metrics artifact status differs")
    complete = status == "final_measurement_candidate"
    retained_path = artifact["retained_path"]
    if not isinstance(retained_path, str):
        raise readiness.ReadinessContractError("retained path differs")
    validate_prior_failed_candidates(
        artifact["prior_failed_candidates"],
        status=status,
        retained_path=retained_path,
        observed_prior_artifacts=observed_prior_artifacts,
    )
    failure_free = _validate_failures(artifact["failures"], complete=complete)
    allow_successful_target_prefix = (
        not complete
        and len(artifact["failures"]) == 1
        and artifact["failures"][0]["stage"] == "output_sizes"
    )

    measurement_gate = validate_measurement(artifact["measurement"])
    policy_gate = validate_policy(artifact["policy"])
    settings_gate = validate_settings_delta(artifact["settings_delta"])
    m0_gate = validate_m0_reference(
        artifact["m0_reference"],
        observed_identity=observed_m0_identity,
        require_observed=True,
    )
    input_gate = validate_input_custody(
        artifact["input_custody"],
        observed_custody=observed_input_custody,
        require_observed=True,
    )
    predecessor_gate = validate_predecessor_custody(
        artifact["predecessor_custody"],
        observed_outputs=observed_predecessor_outputs,
        require_observed=True,
    )
    if historical_custody:
        historical_post = artifact["code_sha256"].get("post")
        if not isinstance(historical_post, Mapping):
            raise readiness.ReadinessContractError(
                "historical code custody post differs"
            )
        code_gate = validate_code_custody(
            artifact["code_sha256"],
            observed_files=historical_post,
            require_observed=True,
            required_paths=None,
        )
        validate_dependency_custody(artifact["dependency_custody"])
        component_gates = [
            _validate_historical_component_custody(
                name,
                artifact[name],
                code_post=historical_post,
            )
            for name in COMPONENT_PATHS
        ]
    else:
        code_gate = validate_code_custody(
            artifact["code_sha256"],
            observed_files=observed_code_files,
            require_observed=True,
        )
        validate_dependency_custody(
            artifact["dependency_custody"],
            observed_custody=observed_dependency_custody,
            require_observed=True,
        )
        component_gates = [
            validate_component_custody(
                name,
                artifact[name],
                code_post=artifact["code_sha256"]["post"],
            )
            for name in COMPONENT_PATHS
        ]
    source_extraction_gate = validate_isolated_stage(
        artifact["source_extraction"],
        stage="source_extraction",
        complete=complete,
        allow_successful_target_prefix=allow_successful_target_prefix,
    )
    projection_gate = validate_isolated_stage(
        artifact["running_region_projection"],
        stage="running_region_projection",
        complete=complete,
        allow_successful_target_prefix=allow_successful_target_prefix,
    )
    resource_gate = validate_resource_boundaries(
        artifact["resource_boundaries"], complete=complete
    )
    deadline_gate = validate_deadline_boundaries(
        artifact["deadline_boundaries"], complete=complete
    )
    paired_gate = validate_paired_parser(
        artifact["paired_parser"],
        complete=complete,
        allow_successful_target_prefix=allow_successful_target_prefix,
    )
    quality_gate = validate_quality(artifact["quality"])
    control_gate = validate_control_matrix(
        artifact["control_matrix"], complete=complete
    )
    comparison_gate = validate_comparison_ledgers(
        artifact["comparison_ledgers"],
        complete=complete,
        projection_targets=artifact["running_region_projection"]["targets"],
        allow_successful_target_prefix=allow_successful_target_prefix,
    )
    output_gate = validate_output_sizes(
        artifact["output_sizes"],
        complete=complete,
    )
    output_gate = validate_output_cross_bindings(artifact) and output_gate
    rollback_gate = validate_rollback(artifact["rollback"])
    hosted_gate = (
        not isinstance(artifact["hosted_requests"], bool)
        and isinstance(artifact["hosted_requests"], int)
        and artifact["hosted_requests"] == 0
        and not isinstance(artifact["hosted_tokens"], bool)
        and isinstance(artifact["hosted_tokens"], int)
        and artifact["hosted_tokens"] == 0
        and not isinstance(artifact["hosted_cost_usd"], bool)
        and isinstance(artifact["hosted_cost_usd"], (int, float))
        and math.isfinite(artifact["hosted_cost_usd"])
        and float(artifact["hosted_cost_usd"]) == 0.0
    )
    if not hosted_gate:
        raise readiness.ReadinessContractError("hosted usage differs")
    expected_gates = {
        "measurement_protocol": measurement_gate,
        "policy_contract": policy_gate,
        "settings_custody": settings_gate,
        "m0_reference": m0_gate,
        "input_custody": input_gate,
        "predecessor_custody": predecessor_gate,
        "fixture_custody": all(component_gates),
        "code_custody": code_gate,
        "dependency_custody": True,
        "source_extraction": source_extraction_gate,
        "running_region_projection": projection_gate,
        "resource_boundaries": resource_gate,
        "deadline_boundaries": deadline_gate,
        "paired_parser": paired_gate,
        "quality": quality_gate,
        "control_matrix": control_gate,
        "comparison_ledgers": comparison_gate,
        "output_sizes": output_gate,
        "rollback": rollback_gate,
        "failure_free": failure_free,
        "hosted_usage": hosted_gate,
    }
    validate_failure_coherence(artifact, expected_gates=expected_gates)
    validate_aggregate(
        artifact["aggregate"],
        expected_gates=expected_gates,
        complete=complete,
    )
    generated_at = artifact["generated_at"]
    try:
        timestamp = datetime.fromisoformat(generated_at)
    except (TypeError, ValueError) as exc:
        raise readiness.ReadinessContractError(
            "metrics_artifact.generated_at differs"
        ) from exc
    if timestamp.tzinfo is None:
        raise readiness.ReadinessContractError(
            "metrics_artifact.generated_at lacks timezone"
        )


def _effective_existing_paths(
    existing_paths: Sequence[str],
    observed_prior_artifacts: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    if (
        not isinstance(existing_paths, (list, tuple))
        or any(not isinstance(path, str) or not path for path in existing_paths)
        or len(existing_paths) != len(set(existing_paths))
    ):
        raise readiness.ReadinessContractError(
            "existing metrics artifact custody differs"
        )
    observed_paths = set(observed_prior_artifacts)
    existing_failed_paths = {
        path
        for path in existing_paths
        if FAILED_ARTIFACT_PATTERN.fullmatch(path) is not None
    }
    if not existing_failed_paths <= observed_paths:
        raise readiness.ReadinessContractError(
            "existing failed artifact lacks observed identity"
        )
    return tuple(dict.fromkeys((*existing_paths, *observed_prior_artifacts)))


def _cross_check_expected_existing_paths(
    expected_existing_paths: Sequence[str] | None,
    discovered_paths: Sequence[str],
) -> None:
    if expected_existing_paths is None:
        return
    if (
        not isinstance(expected_existing_paths, (list, tuple))
        or any(
            not isinstance(path, str) or not path for path in expected_existing_paths
        )
        or len(expected_existing_paths) != len(set(expected_existing_paths))
        or set(expected_existing_paths) != set(discovered_paths)
    ):
        raise readiness.ReadinessContractError(
            "expected metrics artifact discovery differs"
        )


def _collect_repository_custody(
    repository_root: Path,
    *,
    code_paths: Sequence[str],
    expected_existing_paths: Sequence[str] | None,
) -> tuple[
    Path,
    tuple[str, ...],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    root = _resolve_repository_root(repository_root)
    observed_input_custody = collect_input_file_identities(root)
    observed_m0_identity = collect_m0_reference_identity(root)
    observed_predecessor_outputs = collect_predecessor_output_identities(root)
    observed_code_files = collect_code_file_identities(root, paths=code_paths)
    observed_dependency_custody = collect_dependency_custody(root)
    discovered_paths = discover_existing_metrics_artifact_paths(root)
    _cross_check_expected_existing_paths(
        expected_existing_paths,
        discovered_paths,
    )
    failed_paths = tuple(
        path
        for path in discovered_paths
        if FAILED_ARTIFACT_PATTERN.fullmatch(path) is not None
    )
    observed_prior_artifacts = _collect_prior_artifact_identities_with_observations(
        root,
        failed_paths,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
    )
    return (
        root,
        discovered_paths,
        observed_input_custody,
        observed_m0_identity,
        observed_predecessor_outputs,
        observed_code_files,
        observed_dependency_custody,
        observed_prior_artifacts,
    )


def _seal_metrics_artifact_with_observations(
    candidate: Mapping[str, Any],
    *,
    existing_paths: Sequence[str] = (),
    observed_code_files: Mapping[str, Mapping[str, Any]],
    observed_dependency_custody: Mapping[str, Any],
    observed_input_custody: Mapping[str, Any],
    observed_m0_identity: Mapping[str, Any],
    observed_predecessor_outputs: Mapping[str, Mapping[str, Any]],
    observed_prior_artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Unit-only seam for validators with already collected observations."""

    artifact = _strict_detach(candidate)
    if not isinstance(artifact, dict):
        raise readiness.ReadinessContractError("metrics artifact is not an object")
    expected_without_digest = set(ARTIFACT_TOP_LEVEL_FIELDS) - {"semantic_sha256"}
    actual_without_digest = set(artifact) - {"semantic_sha256"}
    if actual_without_digest != expected_without_digest:
        raise readiness.ReadinessContractError("metrics artifact keys differ")
    artifact["semantic_sha256"] = "0" * 64
    artifact["semantic_sha256"] = _artifact_semantic_sha256(artifact)
    _validate_artifact_value_shapes(
        artifact,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
        observed_prior_artifacts=observed_prior_artifacts,
    )
    effective_existing_paths = _effective_existing_paths(
        existing_paths,
        observed_prior_artifacts,
    )
    readiness.validate_metrics_artifact_custody(
        artifact,
        existing_paths=effective_existing_paths,
    )
    return artifact


def seal_metrics_artifact(
    candidate: Mapping[str, Any],
    *,
    repository_root: Path,
    code_paths: Sequence[str] = tuple(sorted(REQUIRED_CODE_PATHS)),
    expected_existing_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Observe repository bytes, semantically seal, and validate one artifact."""

    (
        _,
        discovered_paths,
        observed_input_custody,
        observed_m0_identity,
        observed_predecessor_outputs,
        observed_code_files,
        observed_dependency_custody,
        observed_prior_artifacts,
    ) = _collect_repository_custody(
        repository_root,
        code_paths=code_paths,
        expected_existing_paths=expected_existing_paths,
    )
    return _seal_metrics_artifact_with_observations(
        candidate,
        existing_paths=discovered_paths,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
        observed_prior_artifacts=observed_prior_artifacts,
    )


def _validate_metrics_artifact_with_observations(
    artifact: Mapping[str, Any],
    *,
    existing_paths: Sequence[str] = (),
    observed_code_files: Mapping[str, Mapping[str, Any]],
    observed_dependency_custody: Mapping[str, Any],
    observed_input_custody: Mapping[str, Any],
    observed_m0_identity: Mapping[str, Any],
    observed_predecessor_outputs: Mapping[str, Mapping[str, Any]],
    observed_prior_artifacts: Mapping[str, Mapping[str, Any]],
    historical_custody: bool = False,
) -> None:
    """Unit-only seam for validating already observed artifact custody."""

    try:
        semantic_matches = (
            isinstance(artifact, Mapping)
            and isinstance(artifact.get("semantic_sha256"), str)
            and artifact["semantic_sha256"] == _artifact_semantic_sha256(artifact)
        )
    except (KeyError, TypeError, ValueError, readiness.ReadinessContractError):
        semantic_matches = False
    if not semantic_matches:
        raise readiness.ReadinessContractError(
            "metrics artifact semantic digest differs"
        )
    _validate_artifact_value_shapes(
        artifact,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
        observed_prior_artifacts=observed_prior_artifacts,
        historical_custody=historical_custody,
    )
    effective_existing_paths = _effective_existing_paths(
        existing_paths,
        observed_prior_artifacts,
    )
    readiness.validate_metrics_artifact_custody(
        artifact,
        existing_paths=effective_existing_paths,
    )


def validate_metrics_artifact(
    artifact: Mapping[str, Any],
    *,
    repository_root: Path,
    code_paths: Sequence[str] = tuple(sorted(REQUIRED_CODE_PATHS)),
    expected_existing_paths: Sequence[str] | None = None,
    allow_existing_retained: bool = True,
) -> None:
    """Observe repository bytes and validate the sealed artifact against them."""

    if not isinstance(allow_existing_retained, bool):
        raise readiness.ReadinessContractError(
            "existing retained artifact policy differs"
        )

    (
        root,
        discovered_paths,
        observed_input_custody,
        observed_m0_identity,
        observed_predecessor_outputs,
        observed_code_files,
        observed_dependency_custody,
        observed_prior_artifacts,
    ) = _collect_repository_custody(
        repository_root,
        code_paths=code_paths,
        expected_existing_paths=expected_existing_paths,
    )
    validation_paths = discovered_paths
    validation_prior_artifacts = observed_prior_artifacts
    retained_raw: bytes | None = None
    retained_binding: tuple[
        tuple[int, int, int, int, int, int, int],
        tuple[tuple[int, int, int, int, int, int, int], ...],
    ] | None = None
    retained_path = artifact.get("retained_path")
    if isinstance(retained_path, str) and retained_path in discovered_paths:
        if not allow_existing_retained:
            raise readiness.ReadinessContractError(
                "metrics artifact would overwrite custody"
            )
        relative_path = PurePosixPath(retained_path)
        raw, retained_binding = _read_bounded_regular_repository_file_with_binding(
            root,
            relative_path,
            maximum_bytes=ARTIFACT_WRITE_CAP_BYTES,
            error="retained metrics artifact binding differs",
        )
        retained_raw = raw
        loaded = _load_strict_json(
            raw,
            error="retained metrics artifact is not strict JSON",
        )
        if (
            not isinstance(loaded, Mapping)
            or raw != _artifact_bytes(artifact)
            or loaded != artifact
        ):
            raise readiness.ReadinessContractError(
                "retained metrics artifact binding differs"
            )
        validation_paths = tuple(
            path for path in discovered_paths if path != retained_path
        )
        validation_prior_artifacts = {
            path: identity
            for path, identity in observed_prior_artifacts.items()
            if path != retained_path
        }
    _validate_metrics_artifact_with_observations(
        artifact,
        existing_paths=validation_paths,
        observed_code_files=observed_code_files,
        observed_dependency_custody=observed_dependency_custody,
        observed_input_custody=observed_input_custody,
        observed_m0_identity=observed_m0_identity,
        observed_predecessor_outputs=observed_predecessor_outputs,
        observed_prior_artifacts=validation_prior_artifacts,
    )
    if retained_raw is not None and retained_binding is not None:
        final_raw, final_binding = _read_bounded_regular_repository_file_with_binding(
            root,
            PurePosixPath(str(retained_path)),
            maximum_bytes=ARTIFACT_WRITE_CAP_BYTES,
            error="retained metrics artifact changed during validation",
        )
        if final_raw != retained_raw or final_binding != retained_binding:
            raise readiness.ReadinessContractError(
                "retained metrics artifact changed during validation"
            )


def _artifact_bytes(artifact: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                artifact,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("artifact JSON encoding differs") from exc


def _bounded_artifact_bytes(
    artifact: Mapping[str, Any],
    *,
    maximum_bytes: int,
) -> bytes:
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    payload = bytearray()
    try:
        for chunk in encoder.iterencode(artifact):
            encoded = chunk.encode("utf-8")
            if len(payload) + len(encoded) + 1 > maximum_bytes:
                raise readiness.ReadinessContractError(
                    "artifact exceeds write byte cap"
                )
            payload.extend(encoded)
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("artifact JSON encoding differs") from exc
    payload.extend(b"\n")
    return bytes(payload)


def _unlink_if_matching_regular_file(
    directory_descriptor: int,
    name: str,
    expected_identity: tuple[int, int] | None,
) -> bool:
    if expected_identity is None:
        return False
    try:
        status = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except OSError:
        return False
    if (
        not stat.S_ISREG(status.st_mode)
        or (status.st_dev, status.st_ino) != expected_identity
    ):
        return False
    try:
        os.unlink(name, dir_fd=directory_descriptor)
    except OSError:
        return False
    return True


def write_artifact_exclusive(
    path: Path,
    artifact: Mapping[str, Any],
    *,
    repository_root: Path,
    code_paths: Sequence[str] = tuple(sorted(REQUIRED_CODE_PATHS)),
    expected_existing_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Create one capped artifact through stable directory descriptors only."""

    validate_metrics_artifact(
        artifact,
        repository_root=repository_root,
        code_paths=code_paths,
        expected_existing_paths=expected_existing_paths,
        allow_existing_retained=False,
    )
    root = _resolve_repository_root(repository_root)
    retained_path = PurePosixPath(str(artifact["retained_path"]))
    if retained_path.name != path.name or retained_path.parent != _EVIDENCE_DIRECTORY:
        raise readiness.ReadinessContractError(
            "artifact destination differs from retained custody"
        )
    expected_path = root.joinpath(*retained_path.parts)
    if not isinstance(path, Path) or path != expected_path:
        raise readiness.ReadinessContractError(
            "artifact destination differs from repository custody"
        )

    serialized = _bounded_artifact_bytes(
        artifact,
        maximum_bytes=ARTIFACT_WRITE_CAP_BYTES,
    )

    directory_descriptor = _open_repository_directory_descriptor(
        root,
        retained_path.parent,
        error="artifact destination directory differs",
    )
    directory_snapshot = _file_descriptor_snapshot(directory_descriptor)
    temporary_descriptor: int | None = None
    temporary_name: str | None = None
    temporary_identity: tuple[int, int] | None = None
    temporary_linked = False
    destination_linked = False
    completed = False
    try:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        temporary_flags = (
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | close_on_exec
        )
        for _ in range(32):
            temporary_name = f".{retained_path.name}.{secrets.token_hex(16)}.tmp"
            try:
                temporary_descriptor = os.open(
                    temporary_name,
                    temporary_flags,
                    0o600,
                    dir_fd=directory_descriptor,
                )
            except FileExistsError:
                continue
            except OSError as exc:
                raise MetricsExecutionError("artifact temporary create failed") from exc
            temporary_linked = True
            break
        if temporary_descriptor is None or temporary_name is None:
            raise MetricsExecutionError("artifact temporary name space exhausted")

        temporary_before = _file_descriptor_snapshot(temporary_descriptor)
        temporary_identity = temporary_before[:2]
        if (
            not stat.S_ISREG(temporary_before[2])
            or temporary_before[3] != 1
            or temporary_before[4] != 0
        ):
            raise MetricsExecutionError("artifact temporary file differs")
        offset = 0
        while offset < len(serialized):
            written = os.pwrite(
                temporary_descriptor,
                serialized[offset:],
                offset,
            )
            if written <= 0:
                raise MetricsExecutionError("artifact temporary write stalled")
            offset += written
        os.fsync(temporary_descriptor)
        temporary_after = _file_descriptor_snapshot(temporary_descriptor)
        if (
            temporary_after[:3] != temporary_before[:3]
            or temporary_after[3] != 1
            or temporary_after[4] != len(serialized)
        ):
            raise MetricsExecutionError("artifact temporary file changed")

        try:
            os.link(
                temporary_name,
                retained_path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise readiness.ReadinessContractError(
                "artifact writer refuses overwrite"
            ) from exc
        except OSError as exc:
            raise MetricsExecutionError("artifact exclusive link failed") from exc
        destination_linked = True
        destination_status = os.stat(
            retained_path.name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(destination_status.st_mode)
            or (destination_status.st_dev, destination_status.st_ino)
            != temporary_after[:2]
            or destination_status.st_nlink != 2
            or destination_status.st_size != len(serialized)
            or destination_status.st_mtime_ns != temporary_after[5]
        ):
            raise MetricsExecutionError("artifact destination identity differs")
        os.fsync(directory_descriptor)

        if not _unlink_if_matching_regular_file(
            directory_descriptor,
            temporary_name,
            temporary_identity,
        ):
            raise readiness.ReadinessContractError(
                "artifact temporary file binding changed"
            )
        temporary_linked = False
        os.fsync(directory_descriptor)
        final_temporary = _file_descriptor_snapshot(temporary_descriptor)
        if (
            final_temporary[:3] != temporary_before[:3]
            or final_temporary[3] != 1
            or final_temporary[4] != len(serialized)
            or final_temporary[5] != temporary_after[5]
        ):
            raise MetricsExecutionError("artifact destination changed")

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        close_on_exec = getattr(os, "O_CLOEXEC", 0)
        try:
            retained_descriptor = os.open(
                retained_path.name,
                os.O_RDONLY | os.O_NONBLOCK | nofollow | close_on_exec,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            raise MetricsExecutionError(
                "artifact retained destination open failed"
            ) from exc
        try:
            retained_before = _file_descriptor_snapshot(retained_descriptor)
            if (
                not stat.S_ISREG(retained_before[2])
                or retained_before[:3] != final_temporary[:3]
                or retained_before[3] != 1
                or retained_before[4] != len(serialized)
                or retained_before[5] != temporary_after[5]
            ):
                raise MetricsExecutionError(
                    "artifact retained destination identity differs"
                )
            retained_payload = os.pread(
                retained_descriptor,
                ARTIFACT_WRITE_CAP_BYTES + 1,
                0,
            )
            retained_after = _file_descriptor_snapshot(retained_descriptor)
        finally:
            os.close(retained_descriptor)
        if retained_before != retained_after or retained_payload != serialized:
            raise MetricsExecutionError("artifact retained destination bytes differ")
        try:
            retained_status = os.stat(
                retained_path.name,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise MetricsExecutionError(
                "artifact retained destination final binding differs"
            ) from exc
        retained_name_snapshot = (
            retained_status.st_dev,
            retained_status.st_ino,
            retained_status.st_mode,
            retained_status.st_nlink,
            retained_status.st_size,
            retained_status.st_mtime_ns,
            retained_status.st_ctime_ns,
        )
        if retained_name_snapshot != retained_after:
            raise MetricsExecutionError(
                "artifact retained destination final binding differs"
            )
        final_directory = _file_descriptor_snapshot(directory_descriptor)
        if final_directory[:3] != directory_snapshot[:3] or final_directory[3] < 1:
            raise readiness.ReadinessContractError(
                "artifact destination directory changed"
            )
        if not _repository_directory_binding_matches(
            root,
            retained_path.parent,
            directory_snapshot,
        ):
            raise readiness.ReadinessContractError(
                "artifact destination directory binding differs"
            )
        completed = True
    finally:
        if destination_linked and not completed:
            _unlink_if_matching_regular_file(
                directory_descriptor,
                retained_path.name,
                temporary_identity,
            )
        if temporary_linked and temporary_name is not None:
            _unlink_if_matching_regular_file(
                directory_descriptor,
                temporary_name,
                temporary_identity,
            )
        if destination_linked or temporary_linked:
            try:
                os.fsync(directory_descriptor)
            except OSError:
                pass
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        os.close(directory_descriptor)
    return {
        "path": str(artifact["retained_path"]),
        "size_bytes": len(serialized),
        "sha256": _sha256_bytes(serialized),
    }


def next_failed_artifact_relative_path(existing_paths: Sequence[str]) -> Path:
    """Return the next monotonic two-digit failed-candidate custody path."""

    attempts = [
        int(match.group(1))
        for path in existing_paths
        if (match := FAILED_ARTIFACT_PATTERN.fullmatch(path)) is not None
    ]
    next_attempt = max(attempts, default=0) + 1
    if next_attempt > MAX_FAILED_ARTIFACT_ATTEMPTS:
        raise MetricsExecutionError("failed artifact attempt space is exhausted")
    return Path(
        _EVIDENCE_DIRECTORY,
        f"P03-US08-running-region-metrics-attempt-{next_attempt:02d}-failed.json",
    )


def output_identity(value: Any) -> dict[str, Any]:
    """Return compact semantic JSON size and SHA-256 for output-size custody."""

    try:
        encoded = _canonical_json(value).encode("utf-8")
    except (RecursionError, UnicodeEncodeError) as exc:
        raise MetricsExecutionError("output identity JSON encoding differs") from exc
    return {"size_bytes": len(encoded), "sha256": _sha256_bytes(encoded)}


def _production_settings(*, enabled: bool) -> Any:
    """Construct the exact frozen predecessor settings plus the US08 delta."""

    from app.config import Settings

    return Settings(
        **frozen_oracle.PREDECESSOR_CONFIGURATION,
        layout_running_regions_enabled=enabled,
    )


def _restore_running_region_contract_surfaces(
    compact: dict[str, Any],
    complete: Mapping[str, Any],
) -> dict[str, Any]:
    """Restore explicit-null US08 surfaces onto compact predecessor JSON."""

    compact_processing = compact.get("processing")
    complete_processing = complete.get("processing")
    complete_summary = (
        complete_processing.get("running_regions")
        if isinstance(complete_processing, Mapping)
        else None
    )
    if complete_summary is None:
        return compact
    if not isinstance(compact_processing, dict) or not isinstance(
        complete_summary, Mapping
    ):
        raise MetricsExecutionError("production running-region summary differs")
    compact_processing["running_regions"] = deepcopy(dict(complete_summary))
    if "running_region_concerns" in complete:
        compact["running_region_concerns"] = deepcopy(
            complete["running_region_concerns"]
        )

    complete_pages = complete.get("pages")
    compact_pages = compact.get("pages")
    if (
        not isinstance(complete_pages, list)
        or not isinstance(compact_pages, list)
        or len(complete_pages) != len(compact_pages)
    ):
        raise MetricsExecutionError("production running-region pages differ")
    for complete_page, compact_page in zip(
        complete_pages,
        compact_pages,
        strict=True,
    ):
        if not isinstance(complete_page, Mapping) or not isinstance(compact_page, dict):
            raise MetricsExecutionError("production running-region page differs")
        if "page_identity" in complete_page:
            compact_page["page_identity"] = deepcopy(complete_page["page_identity"])
        complete_items = complete_page.get("items")
        compact_items = compact_page.get("items")
        if (
            not isinstance(complete_items, list)
            or not isinstance(compact_items, list)
            or len(complete_items) != len(compact_items)
        ):
            raise MetricsExecutionError("production running-region items differ")
        for complete_item, compact_item in zip(
            complete_items,
            compact_items,
            strict=True,
        ):
            if not isinstance(complete_item, Mapping) or not isinstance(
                compact_item, dict
            ):
                raise MetricsExecutionError("production running-region item differs")
            if "running_region" in complete_item:
                compact_item["running_region"] = deepcopy(
                    complete_item["running_region"]
                )

    complete_canonical = complete.get("canonical_presentation")
    compact_canonical = compact.get("canonical_presentation")
    if isinstance(complete_canonical, Mapping):
        complete_canonical_pages = complete_canonical.get("pages")
        compact_canonical_pages = (
            compact_canonical.get("pages")
            if isinstance(compact_canonical, Mapping)
            else None
        )
        if (
            not isinstance(complete_canonical_pages, list)
            or not isinstance(compact_canonical_pages, list)
            or len(complete_canonical_pages) != len(compact_canonical_pages)
        ):
            raise MetricsExecutionError(
                "production running-region canonical pages differ"
            )
        for complete_page, compact_page in zip(
            complete_canonical_pages,
            compact_canonical_pages,
            strict=True,
        ):
            if not isinstance(complete_page, Mapping) or not isinstance(
                compact_page, dict
            ):
                raise MetricsExecutionError(
                    "production running-region canonical page differs"
                )
            if "page_identity" in complete_page:
                compact_page["page_identity"] = deepcopy(complete_page["page_identity"])
    return compact


def _production_json(value: Any) -> dict[str, Any]:
    """Detach one parser/Pydantic output into a strict JSON object."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        compact = model_dump(mode="json", exclude_none=True)
        complete = model_dump(mode="json")
        value = _restore_running_region_contract_surfaces(
            compact,
            complete,
        )
    detached = _strict_detach(value)
    if not isinstance(detached, dict):
        raise MetricsExecutionError("production output is not a JSON object")
    return detached


def _load_production_case(
    repository_root: Path,
    case_id: str,
) -> tuple[bytes, dict[str, Any], Any]:
    """Read and verify one sealed PDF/predecessor pair and build its typed IR."""

    from app.services.ir import build_document_ir

    source, predecessor = _load_verified_source_and_predecessor(
        repository_root, case_id
    )
    return source, predecessor, build_document_ir(_strict_detach(predecessor))


def _load_verified_source_and_predecessor(
    repository_root: Path,
    case_id: str,
) -> tuple[bytes, dict[str, Any]]:
    """Load only sealed bytes/JSON; import no parser or US08 implementation."""

    if case_id not in frozen_oracle.SOURCE_IDENTITIES:
        raise MetricsExecutionError("production corpus case differs")
    root = _resolve_repository_root(repository_root)
    source_identity = frozen_oracle.SOURCE_IDENTITIES[case_id]
    source = _read_bounded_regular_repository_file(
        root,
        PurePosixPath(source_identity["path"]),
        maximum_bytes=int(RESOURCE_LIMITS["source_pdf_bytes"]),
        error=f"production source for {case_id} differs",
    )
    if (
        len(source) != source_identity["size_bytes"]
        or _sha256_bytes(source) != source_identity["sha256"]
    ):
        raise MetricsExecutionError(f"production source for {case_id} differs")
    predecessor_path = PurePosixPath(
        frozen_oracle.PREDECESSOR_OUTPUT_ROOT,
        case_id,
        "our-output.json",
    )
    predecessor_bytes = _read_bounded_regular_repository_file(
        root,
        predecessor_path,
        maximum_bytes=PRIOR_ARTIFACT_READ_CAP_BYTES,
        error=f"production predecessor for {case_id} differs",
    )
    expected_predecessor = frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES[case_id]
    if (
        len(predecessor_bytes) != expected_predecessor["size_bytes"]
        or _sha256_bytes(predecessor_bytes) != expected_predecessor["sha256"]
    ):
        raise MetricsExecutionError(f"production predecessor for {case_id} differs")
    predecessor = _load_strict_json(
        predecessor_bytes,
        error=f"production predecessor for {case_id} is not strict JSON",
    )
    if not isinstance(predecessor, dict):
        raise MetricsExecutionError("production predecessor is not an object")
    return source, predecessor


def _running_region_semantic_payload(document: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only deterministic US08 and canonical-view surfaces."""

    pages: list[dict[str, Any]] = []
    canonical = document.get("canonical_presentation")
    canonical_pages = (
        canonical.get("pages")
        if isinstance(canonical, Mapping) and isinstance(canonical.get("pages"), list)
        else []
    )
    canonical_by_index = {
        page.get("page_index"): page
        for page in canonical_pages
        if isinstance(page, Mapping)
    }
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_index = page.get("page_index")
        canonical_page = canonical_by_index.get(page_index)
        pages.append(
            {
                "page_index": page_index,
                "page_identity": page.get("page_identity"),
                "running_regions": [
                    item["running_region"]
                    for item in page.get("items") or []
                    if isinstance(item, Mapping)
                    and isinstance(item.get("running_region"), Mapping)
                ],
                "canonical_body": (
                    canonical_page.get("body")
                    if isinstance(canonical_page, Mapping)
                    else None
                ),
                "canonical_full": (
                    canonical_page.get("full")
                    if isinstance(canonical_page, Mapping)
                    else None
                ),
            }
        )
    summary = (document.get("processing") or {}).get("running_regions")
    if isinstance(summary, Mapping):
        summary = {
            key: value
            for key, value in summary.items()
            if key not in {"extraction_ms", "projection_ms", "total_ms"}
        }
    return {
        "pages": pages,
        "processing": summary,
        "concerns": document.get("running_region_concerns"),
        "canonical_body": (
            canonical.get("body") if isinstance(canonical, Mapping) else None
        ),
        "canonical_full": (
            canonical.get("full") if isinstance(canonical, Mapping) else None
        ),
    }


def _production_whole_output_semantic_payload(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove every approved timing path that exists in the parser state.

    A projected result contains all ten frozen paths and delegates to the
    authoritative normalizer.  The O(1) flag-off result intentionally has no
    running-region summary, so only the seven predecessor timing paths exist;
    their removal remains closed to the same frozen allowlist.
    """

    processing = document.get("processing")
    if not isinstance(processing, Mapping):
        raise MetricsExecutionError("production processing surface differs")
    if isinstance(processing.get("running_regions"), Mapping):
        return _semantic_payload(document)
    if "running_regions" in processing:
        raise MetricsExecutionError("production running-region summary differs")
    predecessor_paths = TIMING_PATHS_REMOVED[:-3]
    if TIMING_PATHS_REMOVED[-3:] != (
        "processing.running_regions.extraction_ms",
        "processing.running_regions.projection_ms",
        "processing.running_regions.total_ms",
    ):
        raise MetricsExecutionError("production timing allowlist differs")
    result = deepcopy(dict(document))
    for path in predecessor_paths:
        parts = path.split(".")
        cursor: Any = result
        for part in parts[:-1]:
            if not isinstance(cursor, dict) or part not in cursor:
                raise MetricsExecutionError(
                    "production predecessor timing path is absent"
                )
            cursor = cursor[part]
        if not isinstance(cursor, dict) or parts[-1] not in cursor:
            raise MetricsExecutionError("production predecessor timing path is absent")
        cursor.pop(parts[-1])
    return result


def production_output_variants(result: Any) -> dict[str, dict[str, Any]]:
    """Hash all eight retained output variants outside parser timing."""

    from app.services.serializer import to_markdown

    document = _production_json(result)
    canonical = document.get("canonical_presentation")
    if not isinstance(canonical, Mapping):
        raise MetricsExecutionError("production canonical presentation is absent")
    body = canonical.get("body")
    full = canonical.get("full")
    if not isinstance(body, Mapping) or not isinstance(full, Mapping):
        raise MetricsExecutionError("production canonical views are absent")
    values = {
        "raw_json": document,
        "semantic_json": _production_whole_output_semantic_payload(document),
        "running_region_semantic_json": _running_region_semantic_payload(document),
        "serialized_markdown": to_markdown(result),
        "canonical_body_text": body.get("text"),
        "canonical_body_markdown": body.get("markdown"),
        "canonical_full_text": full.get("text"),
        "canonical_full_markdown": full.get("markdown"),
    }
    if any(
        not isinstance(values[name], str)
        for name in OUTPUT_VARIANTS
        if name.startswith("canonical_") or name == "serialized_markdown"
    ):
        raise MetricsExecutionError("production output variant differs")
    return {name: output_identity(values[name]) for name in OUTPUT_VARIANTS}


def _assert_flag_off_has_no_running_region_surface(
    document: Mapping[str, Any],
) -> None:
    processing = document.get("processing")
    if not isinstance(processing, Mapping) or "running_regions" in processing:
        raise MetricsExecutionError("flag-off running-region summary exists")
    if "running_region_concerns" in document:
        raise MetricsExecutionError("flag-off running-region concerns exist")
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping) or "page_identity" in page:
            raise MetricsExecutionError("flag-off page identity exists")
        for item in page.get("items") or []:
            if isinstance(item, Mapping) and set(item).intersection(
                {
                    "layout_running_region_projected",
                    "running_region_policy",
                    "running_region",
                }
            ):
                raise MetricsExecutionError("flag-off running-region sidecar exists")
    canonical = document.get("canonical_presentation")
    if not isinstance(canonical, Mapping):
        raise MetricsExecutionError("flag-off canonical presentation is absent")
    if any(
        not isinstance(page, Mapping) or "page_identity" in page
        for page in canonical.get("pages") or []
    ):
        raise MetricsExecutionError("flag-off canonical page identity exists")


def _validate_flag_off_worker_output(
    document: Mapping[str, Any],
    predecessor: Mapping[str, Any],
) -> None:
    _assert_flag_off_has_no_running_region_surface(document)
    if _canonical_json(
        _production_whole_output_semantic_payload(document)
    ) != _canonical_json(_production_whole_output_semantic_payload(predecessor)):
        raise MetricsExecutionError("flag-off predecessor semantic bytes differ")


def _validate_flag_on_worker_output(
    document: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    *,
    case_id: str,
) -> None:
    from app.services import running_regions

    processing = document.get("processing")
    summary = (
        processing.get("running_regions") if isinstance(processing, Mapping) else None
    )
    if (
        not isinstance(summary, Mapping)
        or summary.get("status") != "projected"
        or summary.get("reason") is not None
        or summary.get("concern_count") != 0
        or document.get("running_region_concerns") not in (None, [])
    ):
        raise MetricsExecutionError("flag-on projection did not complete")
    try:
        readiness.validate_projected_document(document)
    except readiness.ReadinessContractError as exc:
        raise MetricsExecutionError(
            "flag-on projected document contract differs"
        ) from exc
    pages = {
        int(page["page_index"]): page
        for page in document.get("pages") or []
        if isinstance(page, Mapping)
    }
    expected_identities = {
        page_index: identity
        for (candidate_case, page_index), identity in (
            frozen_oracle.PAGE_IDENTITY_DESCRIPTORS.items()
        )
        if candidate_case == case_id
    }
    if set(pages) != set(expected_identities) or any(
        _canonical_json(pages[page_index].get("page_identity"))
        != _canonical_json(identity)
        for page_index, identity in expected_identities.items()
    ):
        raise MetricsExecutionError("flag-on page identity oracle differs")
    descriptors = _projected_region_descriptors(document)
    expected_descriptor_ids = {
        record["region_id"]
        for record in frozen_oracle.ACCEPTED_RUNNING_REGIONS
        if record["case_id"] == case_id
    }
    if set(descriptors) != expected_descriptor_ids or any(
        _canonical_json(descriptors[descriptor_id])
        != _canonical_json(frozen_oracle.RUNNING_REGION_DESCRIPTORS[descriptor_id])
        for descriptor_id in expected_descriptor_ids
    ):
        raise MetricsExecutionError("flag-on running-region oracle differs")
    canonical_pages = _canonical_page_map(document)
    expected_memberships = {
        page_index: membership
        for (candidate_case, page_index), membership in (
            frozen_oracle.CANONICAL_PAGE_MEMBERSHIP.items()
        )
        if candidate_case == case_id
    }
    if set(canonical_pages) != set(expected_memberships) or any(
        list(canonical_pages[page_index][view]["block_ids"])
        != list(membership[f"{view}_block_ids"])
        for page_index, membership in expected_memberships.items()
        for view in ("body", "full")
    ):
        raise MetricsExecutionError("flag-on canonical Body/Full oracle differs")
    stripped = running_regions.strip_running_regions(document)
    if _canonical_json(
        _production_whole_output_semantic_payload(stripped)
    ) != _canonical_json(_production_whole_output_semantic_payload(predecessor)):
        raise MetricsExecutionError("flag-on strip reconstruction differs")


def production_paired_worker(
    work: Mapping[str, Any],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Execute one exact whole-parser state in a fresh paired worker process."""

    from app.services.pipeline import parse_document

    root = (
        Path(__file__).resolve().parents[2]
        if repository_root is None
        else _resolve_repository_root(repository_root)
    )
    target_id = work.get("target_id")
    state = work.get("state")
    if target_id not in PERFORMANCE_TARGETS or state not in {"off", "on"}:
        raise MetricsExecutionError("paired production work differs")
    source, predecessor = _load_verified_source_and_predecessor(root, target_id)
    source_identity = frozen_oracle.SOURCE_IDENTITIES[target_id]
    code_before = collect_code_file_identities(root)
    settings = _production_settings(enabled=state == "on")
    filename = Path(source_identity["path"]).name
    running_region_module = "app.services.running_regions"
    running_region_loaded_before = running_region_module in sys.modules
    imports_ready = (
        "app.services.pipeline" in sys.modules
        and "app.config" in sys.modules
        and not running_region_loaded_before
    )
    if running_region_loaded_before:
        raise MetricsExecutionError(
            "paired worker inherited running-region production state"
        )
    started_ns = time.perf_counter_ns()
    result = parse_document(source, filename, settings)
    finished_ns = time.perf_counter_ns()
    raw_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    wall_seconds = (finished_ns - started_ns) / 1_000_000_000
    document = _production_json(result)
    if state == "off":
        if running_region_module in sys.modules:
            raise MetricsExecutionError("flag-off imported running-region module")
        _validate_flag_off_worker_output(document, predecessor)
    else:
        if running_region_module not in sys.modules:
            raise MetricsExecutionError("flag-on did not import running-region module")
        _validate_flag_on_worker_output(
            document,
            predecessor,
            case_id=target_id,
        )
    variants = production_output_variants(result)
    code_after = collect_code_file_identities(root)
    return {
        "wall_seconds": wall_seconds,
        "raw_ru_maxrss": int(raw_rss),
        "platform": sys.platform,
        "exit_code": 0,
        "source_match": (
            len(source) == source_identity["size_bytes"]
            and _sha256_bytes(source) == source_identity["sha256"]
        ),
        "code_match": code_before == code_after,
        "custody_match": (
            code_before == code_after
            and settings.layout_running_regions_enabled is (state == "on")
            and (running_region_module in sys.modules) is (state == "on")
        ),
        "imports_loaded_before_timing": imports_ready,
        "settings_loaded_before_timing": True,
        "source_verified_before_timing": True,
        "timing_clock": WHOLE_PARSER_CLOCK,
        "timing_scope": WHOLE_PARSER_SCOPE,
        "output_variants": variants,
    }


def _clean_worker_command(
    repository_root: Path,
    work: Mapping[str, Any],
    *,
    fail: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tests.benchmarks.running_region_metrics",
        "--repository-root",
        str(_resolve_repository_root(repository_root)),
        "--internal-paired-worker",
        _canonical_json(work),
    ]
    if fail:
        command.append("--internal-fail-worker")
    return command


def _read_clean_worker_result(
    descriptor: int,
    *,
    expected_pid: int,
) -> dict[str, Any]:
    snapshot = _file_descriptor_snapshot(descriptor)
    if (
        not stat.S_ISREG(snapshot[2])
        or snapshot[4] <= 0
        or snapshot[4] > PAIRED_WORKER_WIRE_CAP_BYTES
    ):
        raise MetricsExecutionError("clean paired worker wire size differs")
    raw = os.pread(descriptor, PAIRED_WORKER_WIRE_CAP_BYTES + 1, 0)
    if len(raw) != snapshot[4] or _file_descriptor_snapshot(descriptor) != snapshot:
        raise MetricsExecutionError("clean paired worker wire changed")
    envelope = _load_strict_json(
        raw,
        error="clean paired worker wire strict JSON differs",
    )
    if (
        not isinstance(envelope, Mapping)
        or set(envelope) != {"pid", "result"}
        or envelope.get("pid") != expected_pid
        or raw != _canonical_json(envelope).encode("utf-8")
    ):
        raise MetricsExecutionError("clean paired worker envelope differs")
    return _prepare_paired_callback_wire_result(envelope["result"])


def _finish_clean_paired_campaign(
    *,
    runner_pid: int,
    plan: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target_summaries: dict[str, dict[str, Any]] = {}
    for target_id in PERFORMANCE_TARGETS:
        by_state = {
            state: [
                record
                for record in records
                if record["target_id"] == target_id and record["state"] == state
            ]
            for state in ("off", "on")
        }
        target_summaries[target_id] = _strict_detach(
            _paired_performance_summary(
                target_id,
                off_seconds=[item["wall_seconds"] for item in by_state["off"]],
                on_seconds=[item["wall_seconds"] for item in by_state["on"]],
                off_rss_bytes=[item["rss_bytes"] for item in by_state["off"]],
                on_rss_bytes=[item["rss_bytes"] for item in by_state["on"]],
            )
        )
    campaign = {
        "runner_pid": runner_pid,
        "worker_plan": [_strict_detach(work) for work in plan],
        "workers": [_strict_detach(record) for record in records],
        "targets": target_summaries,
        "all_pass": all(
            summary["passed"] is True for summary in target_summaries.values()
        ),
    }
    validate_paired_parser(campaign, complete=True)
    return campaign


def run_clean_interpreter_paired_campaign(
    *,
    repository_root: Path,
    worker_timeout_seconds: float = 300.0,
    fail_worker_index: int | None = None,
) -> dict[str, Any]:
    """Run the paired plan through sequential exec-created Python processes."""

    if (
        isinstance(worker_timeout_seconds, bool)
        or not isinstance(worker_timeout_seconds, (int, float))
        or not math.isfinite(worker_timeout_seconds)
        or worker_timeout_seconds <= 0
    ):
        raise MetricsExecutionError("clean paired worker timeout differs")
    root = _resolve_repository_root(repository_root)
    runner_pid = os.getpid()
    plan = tuple(readiness.paired_worker_plan())
    records: list[dict[str, Any]] = []
    seen_pids: set[int] = set()
    for work in plan:
        with tempfile.TemporaryFile() as wire, tempfile.TemporaryFile() as errors:
            command = _clean_worker_command(
                root,
                work,
                fail=fail_worker_index == work["worker_index"],
            )
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = "0"
            try:
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=wire,
                    stderr=errors,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError:
                _raise_paired_campaign_failure(
                    "worker_exit",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
            try:
                process.wait(timeout=float(worker_timeout_seconds))
            except subprocess.TimeoutExpired:
                _stop_subprocess_bounded(process)
                _raise_paired_campaign_failure(
                    "worker_timeout",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
            _cleanup_process_group(process.pid)
            if process.returncode != 0:
                _raise_paired_campaign_failure(
                    "worker_exit",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
            try:
                result = _read_clean_worker_result(
                    wire.fileno(), expected_pid=process.pid
                )
            except (MetricsExecutionError, readiness.ReadinessContractError):
                _raise_paired_campaign_failure(
                    "worker_result_invalid",
                    runner_pid=runner_pid,
                    records=records,
                    failed_work=work,
                )
        if process.pid == runner_pid or process.pid in seen_pids:
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        if (
            result["exit_code"] != 0
            or any(
                result[field] is not True
                for field in (
                    "source_match",
                    "code_match",
                    "custody_match",
                    "imports_loaded_before_timing",
                    "settings_loaded_before_timing",
                    "source_verified_before_timing",
                )
            )
            or result["timing_clock"] != WHOLE_PARSER_CLOCK
            or result["timing_scope"] != WHOLE_PARSER_SCOPE
        ):
            _raise_paired_campaign_failure(
                "worker_result_invalid",
                runner_pid=runner_pid,
                records=records,
                failed_work=work,
            )
        record = {
            **_strict_detach(work),
            "pid": process.pid,
            "parent_pid": runner_pid,
            **result,
            "rss_bytes": _rss_bytes_from_maxrss(
                result["raw_ru_maxrss"], platform_name=result["platform"]
            ),
        }
        seen_pids.add(process.pid)
        records.append(record)
    return _finish_clean_paired_campaign(
        runner_pid=runner_pid,
        plan=plan,
        records=records,
    )


def _internal_clean_worker(
    payload: str,
    *,
    repository_root: Path,
    fail: bool,
) -> int:
    """Private CLI entrypoint for exactly one exec-created paired worker."""

    import contextlib

    if fail:
        return 2
    try:
        raw = payload.encode("utf-8")
        work = _load_strict_json(
            raw,
            error="internal paired worker payload differs",
        )
        if (
            not isinstance(work, Mapping)
            or raw != _canonical_json(work).encode("utf-8")
            or work not in readiness.paired_worker_plan()
        ):
            return 2
        with (
            open(os.devnull, "w", encoding="utf-8") as sink,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            result = production_paired_worker(
                work,
                repository_root=repository_root,
            )
        prepared = _prepare_paired_callback_wire_result(result)
        envelope = {"pid": os.getpid(), "result": prepared}
        encoded = _bounded_canonical_json_bytes(
            envelope,
            maximum_bytes=PAIRED_WORKER_WIRE_CAP_BYTES,
        )
    except Exception:  # noqa: BLE001 - content-free worker exit envelope
        return 2
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


def _measurement_record() -> dict[str, Any]:
    return {
        "performance_cases": list(PERFORMANCE_TARGETS),
        "pair_count_per_case": PAIRED_REPEAT_COUNT,
        "worker_process_count": PAIRED_WORKER_COUNT,
        "isolated_latency_warmups": ISOLATED_LATENCY_WARMUPS,
        "isolated_latency_samples": ISOLATED_LATENCY_SAMPLES,
        "isolated_allocation_warmups": ISOLATED_ALLOCATION_WARMUPS,
        "isolated_allocation_samples": ISOLATED_ALLOCATION_SAMPLES,
        "whole_parser_clock": WHOLE_PARSER_CLOCK,
        "whole_parser_scope": WHOLE_PARSER_SCOPE,
        "execution_order_policy": EXECUTION_ORDER_POLICY,
        "cache_disclaimer": CACHE_DISCLAIMER,
        "maximum_page_workload": _strict_detach(MAXIMUM_PAGE_WORKLOAD),
    }


def _policy_record() -> dict[str, Any]:
    return {
        "policy_id": POLICY_ID,
        "quantile_method": QUANTILE_METHOD,
        "quantile_formula": QUANTILE_FORMULA,
        "paired_fixed_ceilings_seconds": dict(PAIRED_FIXED_CEILINGS_SECONDS),
        "relative_ceiling_fraction": 0.05,
        "peak_rss_delta_ceiling_bytes": PEAK_RSS_DELTA_CEILING_BYTES,
        "source_extraction_p95_ceiling_seconds": (
            ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
        ),
        "projection_p95_ceiling_seconds": ISOLATED_PROJECTION_P95_SECONDS,
        "peak_allocation_ceiling_bytes": PEAK_ALLOCATION_CEILING_BYTES,
        "source_report_size_ceiling_bytes": int(RESOURCE_LIMITS["report_json_bytes"]),
        "timing_paths_removed": list(TIMING_PATHS_REMOVED),
        "source_report_timing_paths_removed": list(SOURCE_REPORT_TIMING_PATHS_REMOVED),
        "artifact_semantic_fields_removed": list(ARTIFACT_SEMANTIC_FIELDS_REMOVED),
    }


def _settings_delta_record() -> dict[str, Any]:
    off = dict(_EXPECTED_SETTINGS_OFF)
    on = dict(_EXPECTED_SETTINGS_ON)
    return {
        "changed_fields": ["layout_running_regions_enabled"],
        "flag_off": off,
        "flag_on": on,
        "flag_off_sha256": _sha256_json(off),
        "flag_on_sha256": _sha256_json(on),
        "predecessor_flags_match": True,
    }


def _input_custody_record(
    pre: Mapping[str, Any],
    post: Mapping[str, Any],
) -> dict[str, Any]:
    def source_records(observed: Mapping[str, Any]) -> dict[str, Any]:
        return {
            case_id: {
                **dict(observed["sources"][case_id]),
                "page_count": frozen_oracle.SOURCE_IDENTITIES[case_id]["page_count"],
            }
            for case_id in frozen_oracle.SOURCE_IDENTITIES
        }

    pre_sources = source_records(pre)
    post_sources = source_records(post)
    expected_match = (
        pre_sources == frozen_oracle.SOURCE_IDENTITIES
        and post_sources == frozen_oracle.SOURCE_IDENTITIES
    )
    return {
        "corpus_registry": _strict_detach(frozen_oracle.CORPUS_REGISTRY_CUSTODY),
        "pre": pre_sources,
        "post": post_sources,
        "source_count": len(post_sources),
        "page_count": sum(value["page_count"] for value in post_sources.values()),
        "total_size_bytes": sum(value["size_bytes"] for value in post_sources.values()),
        "all_expected_match": expected_match,
        "pre_post_match": pre_sources == post_sources,
    }


def _predecessor_custody_record(
    outputs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    detached = _strict_detach(outputs)
    return {
        "root": frozen_oracle.PREDECESSOR_OUTPUT_ROOT,
        "outputs": detached,
        "configuration": _strict_detach(frozen_oracle.PREDECESSOR_CONFIGURATION),
        "output_count": len(detached),
        "total_size_bytes": sum(value["size_bytes"] for value in detached.values()),
        "all_expected_match": detached == frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES,
    }


def _component_custody_records(
    code_custody: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for name, path in COMPONENT_PATHS.items():
        identity = code_custody["post"][path]
        semantic_sha256 = COMPONENT_EXPECTED_SEMANTIC_SHA256[name]
        records[name] = {
            **identity,
            "semantic_sha256": semantic_sha256,
            "expected_semantic_sha256": semantic_sha256,
            "match": True,
        }
    return records


def _projection_output_measurements(
    document: Mapping[str, Any],
) -> tuple[dict[str, Any], int, int]:
    identity = output_identity(document)
    page_identity_sizes: list[int] = []
    descriptor_sizes: list[int] = []
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        page_identity = page.get("page_identity")
        if isinstance(page_identity, Mapping):
            page_identity_sizes.append(output_identity(page_identity)["size_bytes"])
        for item in page.get("items") or []:
            if isinstance(item, Mapping) and isinstance(
                item.get("running_region"), Mapping
            ):
                descriptor_sizes.append(
                    output_identity(item["running_region"])["size_bytes"]
                )
    return (
        identity,
        max(page_identity_sizes, default=0),
        max(descriptor_sizes, default=0),
    )


def _isolated_output_observer(
    *,
    stage: str,
    measurement_kind: str,
    skip: int,
    measured_outputs: list[dict[str, Any]],
    report_sizes: list[int],
    expected_report: Mapping[str, Any] | None = None,
) -> Callable[[Any], None]:
    calls = 0

    def observe(result: Any) -> None:
        nonlocal calls
        calls += 1
        if stage == "source_extraction":
            if not isinstance(result, Mapping) or not isinstance(
                result.get("source_report"), Mapping
            ):
                raise MetricsExecutionError("production source report differs")
            report = _strict_detach(result["source_report"])
            readiness.validate_source_report(report)
            if expected_report is None or _canonical_json(
                _report_semantic_payload(report)
            ) != _canonical_json(_report_semantic_payload(expected_report)):
                raise MetricsExecutionError("production source report oracle differs")
            identity = output_identity(report)
            maximum_page = None
            maximum_descriptor = None
        else:
            if (
                not isinstance(result, tuple)
                or len(result) != 2
                or not isinstance(result[0], Mapping)
            ):
                raise MetricsExecutionError("production projection output differs")
            report = _production_json(result[0])
            readiness.validate_projected_document(report)
            identity, maximum_page, maximum_descriptor = (
                _projection_output_measurements(report)
            )
        if calls <= skip:
            return
        sample_index = calls - skip - 1
        measured_outputs.append(
            {
                "measurement_kind": measurement_kind,
                "sample_index": sample_index,
                "output_identity": identity,
                "maximum_page_identity_json_bytes": maximum_page,
                "maximum_running_descriptor_json_bytes": maximum_descriptor,
            }
        )
        if stage == "source_extraction":
            report_sizes.append(identity["size_bytes"])

    return observe


def _run_production_isolated_stages(
    repository_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run the exact isolated protocols and return their bound size evidence."""

    from app.services import running_regions

    source_targets: dict[str, Any] = {}
    projection_targets: dict[str, Any] = {}
    comparison_targets: dict[str, Any] = {}
    output_sizes = {
        "source_reports": {},
        "isolated_projection_outputs": {},
        "maximum_page_identity_json_bytes": 0,
        "maximum_running_descriptor_json_bytes": 0,
        "maximum_source_report_json_bytes": 0,
    }
    for target_id in PERFORMANCE_TARGETS:
        source, predecessor, predecessor_ir = _load_production_case(
            repository_root, target_id
        )
        expected_report = frozen_oracle.SOURCE_REPORTS[target_id]
        predecessor_ir_payload = predecessor_ir.model_dump(
            mode="json", exclude_none=True
        )
        source_predecessor_public_identity = output_identity(predecessor)
        source_predecessor_ir_identity = output_identity(predecessor_ir_payload)

        def source_prepare(
            _source: bytes = source,
            _predecessor: dict[str, Any] = predecessor,
            _predecessor_ir: dict[str, Any] = predecessor_ir_payload,
        ) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
            return _source, deepcopy(_predecessor), deepcopy(_predecessor_ir)

        def source_operation(
            prepared: tuple[bytes, dict[str, Any], dict[str, Any]],
        ) -> Mapping[str, Any]:
            source_bytes, public_document, ir_document = prepared
            return running_regions.extract_running_region_source_projection(
                source_bytes,
                public_document,
                ir_document,
            )

        source_outputs: list[dict[str, Any]] = []
        source_report_sizes: list[int] = []
        source_timing = _profile_timing(
            source_prepare,
            source_operation,
            observe_result=_isolated_output_observer(
                stage="source_extraction",
                measurement_kind="latency",
                skip=ISOLATED_LATENCY_WARMUPS,
                measured_outputs=source_outputs,
                report_sizes=source_report_sizes,
                expected_report=expected_report,
            ),
        )
        source_allocation = _profile_allocation(
            source_prepare,
            source_operation,
            observe_result=_isolated_output_observer(
                stage="source_extraction",
                measurement_kind="allocation",
                skip=ISOLATED_ALLOCATION_WARMUPS,
                measured_outputs=source_outputs,
                report_sizes=source_report_sizes,
                expected_report=expected_report,
            ),
        )
        ledger_envelope = source_operation(source_prepare())
        ledger_report = ledger_envelope.get("source_report")
        ledger = ledger_envelope.get("comparison_ledger")
        if (
            not isinstance(ledger_report, Mapping)
            or not isinstance(ledger, list)
            or not ledger
        ):
            raise MetricsExecutionError("production comparison ledger differs")
        readiness.validate_source_report(ledger_report)
        if _canonical_json(_report_semantic_payload(ledger_report)) != _canonical_json(
            _report_semantic_payload(expected_report)
        ):
            raise MetricsExecutionError("production ledger report oracle differs")
        comparison_count = sum(int(value["comparison_count"]) for value in ledger)
        maximum_page_comparisons = max(
            int(value["comparison_count"]) for value in ledger
        )
        del ledger_envelope, ledger_report, ledger
        gc.collect()
        if (
            output_identity(predecessor) != source_predecessor_public_identity
            or output_identity(predecessor_ir_payload) != source_predecessor_ir_identity
        ):
            raise MetricsExecutionError(
                "source extraction mutated its sealed predecessor"
            )
        source_retained_identity = source_outputs[-1]["output_identity"]
        source_passed = (
            source_timing.p95_seconds <= ISOLATED_SOURCE_EXTRACTION_P95_SECONDS
            and source_allocation.peak_allocated_bytes <= PEAK_ALLOCATION_CEILING_BYTES
            and all(
                size <= int(RESOURCE_LIMITS["report_json_bytes"])
                for size in source_report_sizes
            )
        )
        source_targets[target_id] = {
            "protocol": readiness.isolated_measurement_protocol(
                "source_extraction", target_id
            ),
            "latency_seconds": list(source_timing.samples_seconds),
            "allocation_bytes": list(source_allocation.peak_allocated_samples_bytes),
            "warmup_successes": [True]
            * (ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS),
            "measured_output_successes": [True]
            * (ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES),
            "measured_outputs": source_outputs,
            "report_sizes": source_report_sizes,
            "predecessor_unchanged": None,
            "idempotent": None,
            "retained_output": source_retained_identity,
            "summary": {
                "stage": "source_extraction",
                "target_id": target_id,
                "page_count": frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"],
                "comparison_count": None,
                "maximum_page_comparisons": None,
                "latency_p95_seconds": source_timing.p95_seconds,
                "peak_allocation_bytes": source_allocation.peak_allocated_bytes,
                "passed": source_passed,
            },
        }
        output_sizes["source_reports"][target_id] = source_retained_identity
        output_sizes["maximum_source_report_json_bytes"] = max(
            output_sizes["maximum_source_report_json_bytes"],
            max(source_report_sizes),
        )

        authority = running_regions.prepare_source_projection_authority(
            {
                "public": predecessor,
                "ir": predecessor_ir.model_dump(mode="json", exclude_none=True),
            },
            source,
        )
        predecessor_public_identity = output_identity(predecessor)
        predecessor_ir_identity = output_identity(
            predecessor_ir.model_dump(mode="json", exclude_none=True)
        )

        def projection_prepare(
            _predecessor: dict[str, Any] = predecessor,
            _predecessor_ir: Any = predecessor_ir,
        ) -> tuple[dict[str, Any], Any]:
            return deepcopy(_predecessor), deepcopy(_predecessor_ir)

        def projection_operation(
            prepared: tuple[dict[str, Any], Any],
            _authority: Any = authority,
        ) -> tuple[dict[str, Any], Any]:
            public_document, ir_document = prepared
            return running_regions.project_running_regions(
                public_document,
                ir_document,
                _authority,
            )

        projection_outputs: list[dict[str, Any]] = []
        projection_timing = _profile_timing(
            projection_prepare,
            projection_operation,
            observe_result=_isolated_output_observer(
                stage="running_region_projection",
                measurement_kind="latency",
                skip=ISOLATED_LATENCY_WARMUPS,
                measured_outputs=projection_outputs,
                report_sizes=[],
            ),
        )
        projection_allocation = _profile_allocation(
            projection_prepare,
            projection_operation,
            observe_result=_isolated_output_observer(
                stage="running_region_projection",
                measurement_kind="allocation",
                skip=ISOLATED_ALLOCATION_WARMUPS,
                measured_outputs=projection_outputs,
                report_sizes=[],
            ),
        )
        instrumented_metrics: dict[str, Any] = {}
        instrumented_public, instrumented_ir = running_regions.project_running_regions(
            deepcopy(predecessor),
            deepcopy(predecessor_ir),
            authority,
            metrics=instrumented_metrics,
        )
        repeated_public, repeated_ir = running_regions.project_running_regions(
            instrumented_public,
            instrumented_ir,
            authority,
        )
        predecessor_unchanged = (
            output_identity(predecessor) == predecessor_public_identity
            and output_identity(
                predecessor_ir.model_dump(mode="json", exclude_none=True)
            )
            == predecessor_ir_identity
        )
        idempotent = _semantic_payload(instrumented_public) == _semantic_payload(
            repeated_public
        ) and output_identity(
            instrumented_ir.model_dump(mode="json", exclude_none=True)
        ) == output_identity(repeated_ir.model_dump(mode="json", exclude_none=True))
        retained_projection_identity = projection_outputs[-1]["output_identity"]
        retained_maximum_page = max(
            output["maximum_page_identity_json_bytes"] for output in projection_outputs
        )
        retained_maximum_descriptor = max(
            output["maximum_running_descriptor_json_bytes"]
            for output in projection_outputs
        )
        projection_passed = (
            projection_timing.p95_seconds <= ISOLATED_PROJECTION_P95_SECONDS
            and projection_allocation.peak_allocated_bytes
            <= PEAK_ALLOCATION_CEILING_BYTES
            and predecessor_unchanged
            and idempotent
            and comparison_count == int(instrumented_metrics["comparison_count"])
        )
        projection_targets[target_id] = {
            "protocol": readiness.isolated_measurement_protocol(
                "running_region_projection", target_id
            ),
            "latency_seconds": list(projection_timing.samples_seconds),
            "allocation_bytes": list(
                projection_allocation.peak_allocated_samples_bytes
            ),
            "warmup_successes": [True]
            * (ISOLATED_LATENCY_WARMUPS + ISOLATED_ALLOCATION_WARMUPS),
            "measured_output_successes": [True]
            * (ISOLATED_LATENCY_SAMPLES + ISOLATED_ALLOCATION_SAMPLES),
            "measured_outputs": projection_outputs,
            "report_sizes": [],
            "predecessor_unchanged": predecessor_unchanged,
            "idempotent": idempotent,
            "retained_output": retained_projection_identity,
            "summary": {
                "stage": "running_region_projection",
                "target_id": target_id,
                "page_count": frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"],
                "comparison_count": comparison_count,
                "maximum_page_comparisons": maximum_page_comparisons,
                "latency_p95_seconds": projection_timing.p95_seconds,
                "peak_allocation_bytes": (projection_allocation.peak_allocated_bytes),
                "passed": projection_passed,
            },
        }
        comparison_targets[target_id] = {
            "target_id": target_id,
            "page_count": frozen_oracle.SOURCE_IDENTITIES[target_id]["page_count"],
            "comparison_count": comparison_count,
            "maximum_page_comparisons": maximum_page_comparisons,
            "page_ceiling": int(RESOURCE_LIMITS["comparisons_per_page"]),
            "document_ceiling": int(RESOURCE_LIMITS["comparisons_per_document"]),
            "instrumentation_untimed": True,
            "indexed_algorithm": True,
            "passed": (
                comparison_count <= int(RESOURCE_LIMITS["comparisons_per_document"])
                and maximum_page_comparisons
                <= int(RESOURCE_LIMITS["comparisons_per_page"])
            ),
        }
        output_sizes["isolated_projection_outputs"][target_id] = (
            retained_projection_identity
        )
        output_sizes["maximum_page_identity_json_bytes"] = max(
            output_sizes["maximum_page_identity_json_bytes"],
            retained_maximum_page,
        )
        output_sizes["maximum_running_descriptor_json_bytes"] = max(
            output_sizes["maximum_running_descriptor_json_bytes"],
            retained_maximum_descriptor,
        )

    source_stage = {
        "targets": source_targets,
        "all_pass": all(
            target["summary"]["passed"] for target in source_targets.values()
        ),
    }
    projection_stage = {
        "targets": projection_targets,
        "all_pass": all(
            target["summary"]["passed"] for target in projection_targets.values()
        ),
    }
    comparisons = {
        "targets": comparison_targets,
        "all_pass": all(target["passed"] for target in comparison_targets.values()),
    }
    return source_stage, projection_stage, comparisons, output_sizes


def _run_production_boundaries() -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind every exact/max+1 resource and deadline to production seams."""

    from app.services import running_regions

    if dict(running_regions.RESOURCE_LIMITS) != {
        key: RESOURCE_LIMITS[key] for key in running_regions.RESOURCE_LIMITS
    }:
        raise MetricsExecutionError("production resource limits differ")

    resource_cases: dict[str, Any] = {}
    for counter in RESOURCE_COUNTERS:
        exact = frozen_synthetic.build_resource_boundary_witness(counter)
        overflow = frozen_synthetic.build_resource_boundary_witness(
            counter, maximum_plus_one=True
        )

        def measure(
            payload: Any, *, _exact: Any = exact, _overflow: Any = overflow
        ) -> int:
            if payload is _exact.payload:
                return _exact.measure()
            if payload is _overflow.payload:
                return _overflow.measure()
            raise MetricsExecutionError("production resource witness differs")

        def validate_payload(
            payload: Any,
            *,
            _counter: str = counter,
            _measure: Callable[[Any], int] = measure,
        ) -> int | bool:
            try:
                return running_regions.validate_running_region_resource_count(
                    _counter, _measure(payload)
                )
            except running_regions.RunningRegionError:
                return False

        result = exercise_production_boundary(
            counter,
            exact_payload=exact.payload,
            maximum_plus_one_payload=overflow.payload,
            measure=measure,
            production_validator=validate_payload,
            production_hook=(
                "app.services.running_regions.validate_running_region_resource_count"
            ),
            is_expected_refusal=lambda exc: isinstance(
                exc, running_regions.RunningRegionError
            ),
        )
        resource_cases[counter] = result.as_dict()

    deadline_cases: dict[str, Any] = {}
    deadline_hook = "app.services.running_regions.validate_running_region_deadline"
    for name in DEADLINE_LIMITS_SECONDS:
        production_name = name.removesuffix("_deadline")

        def validate_deadline(
            clock: Callable[[], int],
            *,
            _name: str = production_name,
        ) -> float | bool:
            try:
                return running_regions.validate_running_region_deadline(
                    _name,
                    clock(),
                    monotonic_ns=clock,
                )
            except running_regions.RunningRegionError:
                return False

        deadline_cases[name] = exercise_production_deadline(
            name,
            production_operation=validate_deadline,
            production_hook=deadline_hook,
            is_expected_refusal=lambda exc: isinstance(
                exc, running_regions.RunningRegionError
            ),
        ).as_dict()

    def maximum_page_operation(
        workload: Mapping[str, Any],
        monotonic_ns: Callable[[], int],
    ) -> bool:
        try:
            return running_regions.project_maximum_page_workload(workload, monotonic_ns)
        except running_regions.RunningRegionError:
            return False

    maximum_page = execute_maximum_page_workload(
        resource_accountant=running_regions.account_maximum_page_workload,
        resource_accounting_hook=(
            "app.services.running_regions.account_maximum_page_workload"
        ),
        page_operation=maximum_page_operation,
        page_deadline_hook=(
            "app.services.running_regions.project_maximum_page_workload"
        ),
        is_expected_refusal=lambda exc: isinstance(
            exc, running_regions.RunningRegionError
        ),
    )
    resources = {
        "cases": resource_cases,
        "maximum_page_execution": maximum_page.as_dict(),
        "all_pass": (
            all(record["passed"] for record in resource_cases.values())
            and maximum_page.passed
        ),
    }
    deadlines = {
        "cases": deadline_cases,
        "all_pass": all(record["passed"] for record in deadline_cases.values()),
    }
    validate_resource_boundaries(resources, complete=True)
    validate_deadline_boundaries(deadlines, complete=True)
    return resources, deadlines


def _resolve_projection_path(document: Any, path: Sequence[Any]) -> Any:
    current = document
    for segment in path:
        if (
            isinstance(current, Mapping)
            and isinstance(segment, str)
            or isinstance(current, list)
            and isinstance(segment, int)
        ):
            current = current[segment]
        else:
            raise MetricsExecutionError("production projection path differs")
    return current


def _project_production_case(
    repository_root: Path,
    case_id: str,
) -> dict[str, Any]:
    from app.services import running_regions

    source, predecessor, predecessor_ir = _load_production_case(
        repository_root, case_id
    )
    first_envelope = running_regions.extract_running_region_source_projection(
        source,
        deepcopy(predecessor),
        deepcopy(predecessor_ir),
    )
    second_envelope = running_regions.extract_running_region_source_projection(
        source,
        deepcopy(predecessor),
        deepcopy(predecessor_ir),
    )
    authority = running_regions.prepare_source_projection_authority(
        {
            "public": predecessor,
            "ir": predecessor_ir.model_dump(mode="json", exclude_none=True),
        },
        source,
    )
    metrics: dict[str, Any] = {}
    projected, projected_ir = running_regions.project_running_regions(
        predecessor,
        predecessor_ir,
        authority,
        metrics=metrics,
    )
    repeated, repeated_ir = running_regions.project_running_regions(
        deepcopy(predecessor),
        deepcopy(predecessor_ir),
        authority,
    )
    stripped, stripped_ir = running_regions.strip_running_regions(
        projected,
        projected_ir,
    )
    replayed, replayed_ir = running_regions.replay_running_regions(
        stripped,
        stripped_ir,
        source,
        prior_summary=projected["processing"]["running_regions"],
    )
    return {
        "source": source,
        "predecessor": predecessor,
        "predecessor_ir": predecessor_ir,
        "authority": authority,
        "first_envelope": first_envelope,
        "second_envelope": second_envelope,
        "projected": projected,
        "projected_ir": projected_ir,
        "repeated": repeated,
        "repeated_ir": repeated_ir,
        "stripped": stripped,
        "stripped_ir": stripped_ir,
        "replayed": replayed,
        "replayed_ir": replayed_ir,
        "metrics": metrics,
    }


def _projected_region_descriptors(
    document: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    descriptors: dict[str, Mapping[str, Any]] = {}
    for page in document.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for item in page.get("items") or []:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("running_region"), Mapping
            ):
                continue
            descriptor = item["running_region"]
            descriptor_id = descriptor.get("id")
            if not isinstance(descriptor_id, str) or descriptor_id in descriptors:
                raise MetricsExecutionError(
                    "production running-region descriptor identity differs"
                )
            descriptors[descriptor_id] = descriptor
    return descriptors


def _canonical_page_map(document: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    canonical = document.get("canonical_presentation")
    if not isinstance(canonical, Mapping) or not isinstance(
        canonical.get("pages"), list
    ):
        raise MetricsExecutionError("production canonical pages differ")
    pages = {
        int(page["page_index"]): page
        for page in canonical["pages"]
        if isinstance(page, Mapping)
    }
    if len(pages) != len(canonical["pages"]):
        raise MetricsExecutionError("production canonical page identity differs")
    return pages


def _logical_page_items(items: Any) -> list[Mapping[str, Any]]:
    """Return stable header/body/footer layout order for oracle adjacency."""

    if not isinstance(items, list) or any(
        not isinstance(item, Mapping) for item in items
    ):
        raise MetricsExecutionError("production page items differ")

    def region_rank(item: Mapping[str, Any]) -> int:
        descriptor = item.get("running_region")
        role = descriptor.get("role") if isinstance(descriptor, Mapping) else None
        if role in {"header", "navigation_top"}:
            return 0
        if role in {"footer", "navigation_bottom"}:
            return 2
        return 1

    return [
        item
        for _offset, item in sorted(
            enumerate(items),
            key=lambda value: (region_rank(value[1]), value[0]),
        )
    ]


def _run_production_quality_and_controls(
    repository_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Execute all 15 sealed sources and derive quality/control/rollback data."""

    from app.services import running_regions

    projected_cases: dict[str, dict[str, Any]] = {}
    control_cases: dict[str, Any] = {}
    page_identity_exact_count = 0
    running_region_exact_count = 0
    pairwise_order_exact_count = 0
    manufacturing_header_exact_count = 0
    false_printed_label_promotions = 0
    duplicate_canonical_contributions = 0
    missing_canonical_contributions = 0
    legacy_identity_mismatches = 0
    determinism_failures = 0

    for case_id in frozen_oracle.SOURCE_IDENTITIES:
        evidence = _project_production_case(repository_root, case_id)
        if case_id in {"esg-metrics", "manufacturing-report"}:
            projected_cases[case_id] = evidence
        predecessor = evidence["predecessor"]
        projected = evidence["projected"]
        projected_ir = evidence["projected_ir"]
        readiness.validate_projected_document(projected)
        readiness.validate_ir_bindings(
            projected_ir.model_dump(mode="json"),
            public_document=projected,
        )
        pages = {
            int(page["page_index"]): page
            for page in projected.get("pages") or []
            if isinstance(page, Mapping)
        }
        predecessor_pages = {
            int(page["page_index"]): page
            for page in predecessor.get("pages") or []
            if isinstance(page, Mapping)
        }
        canonical_pages = _canonical_page_map(projected)
        descriptors = _projected_region_descriptors(projected)
        expected_descriptors = {
            descriptor_id: descriptor
            for descriptor_id, descriptor in (
                frozen_oracle.RUNNING_REGION_DESCRIPTORS.items()
            )
            if any(
                record["case_id"] == case_id and record["region_id"] == descriptor_id
                for record in frozen_oracle.ACCEPTED_RUNNING_REGIONS
            )
        }

        case_page_exact = 0
        for (
            candidate_case,
            page_index,
        ), expected in frozen_oracle.PAGE_IDENTITY_DESCRIPTORS.items():
            if candidate_case != case_id:
                continue
            actual = pages[page_index].get("page_identity")
            if _canonical_json(actual) == _canonical_json(expected):
                page_identity_exact_count += 1
                case_page_exact += 1
            expected_detected = expected["detected_printed_label"]
            if (
                actual.get("detected_printed_label") != expected_detected
                and actual.get("detected_printed_label") is not None
            ):
                false_printed_label_promotions += 1

        case_region_exact = 0
        for descriptor_id, expected in expected_descriptors.items():
            actual = descriptors.get(descriptor_id)
            if _canonical_json(actual) == _canonical_json(expected):
                running_region_exact_count += 1
                case_region_exact += 1
            record = next(
                value
                for value in frozen_oracle.ACCEPTED_RUNNING_REGIONS
                if value["region_id"] == descriptor_id
            )
            canonical_page = canonical_pages[record["physical_page"]]
            full_ids = list(canonical_page["full"]["block_ids"])
            body_ids = list(canonical_page["body"]["block_ids"])
            full_count = full_ids.count(expected["canonical_block_id"])
            body_count = body_ids.count(expected["canonical_block_id"])
            if full_count > int(record["expected_full_count"]) or body_count > int(
                record["expected_body_count"]
            ):
                duplicate_canonical_contributions += 1
            if full_count < int(record["expected_full_count"]) or body_count < int(
                record["expected_body_count"]
            ):
                missing_canonical_contributions += 1
            expected_neighbors = record["order_neighbors"]
            projected_items = _logical_page_items(
                pages[record["physical_page"]]["items"]
            )
            block_index = next(
                (
                    index
                    for index, item in enumerate(projected_items)
                    if isinstance(item.get("running_region"), Mapping)
                    and item["running_region"].get("id") == descriptor_id
                ),
                -1,
            )
            before_id = (
                projected_items[block_index - 1].get("id") if block_index > 0 else None
            )
            after_id = (
                projected_items[block_index + 1].get("id")
                if 0 <= block_index < len(projected_items) - 1
                else None
            )
            if (
                before_id == expected_neighbors["before_item_id"]
                and after_id == expected_neighbors["after_item_id"]
            ):
                pairwise_order_exact_count += 1
            if (
                case_id == "manufacturing-report"
                and record["normalized_signature"] == "nist ams 100-76 february 2026"
                and _canonical_json(actual) == _canonical_json(expected)
            ):
                manufacturing_header_exact_count += 1

        legacy_identity_match = True
        for page_index, page in pages.items():
            predecessor_page = predecessor_pages[page_index]
            for field in ("page_index", "page_number", "page_label"):
                if page.get(field) != predecessor_page.get(field):
                    legacy_identity_mismatches += 1
                    legacy_identity_match = False

        first_report = evidence["first_envelope"]["source_report"]
        second_report = evidence["second_envelope"]["source_report"]
        deterministic = (
            _report_semantic_payload(first_report)
            == _report_semantic_payload(second_report)
            and _semantic_payload(projected)
            == _semantic_payload(evidence["repeated"])
            == _semantic_payload(evidence["replayed"])
            and output_identity(projected_ir.model_dump(mode="json", exclude_none=True))
            == output_identity(
                evidence["repeated_ir"].model_dump(mode="json", exclude_none=True)
            )
            == output_identity(
                evidence["replayed_ir"].model_dump(mode="json", exclude_none=True)
            )
        )
        if not deterministic:
            determinism_failures += 1

        expected = _CONTROL_EXPECTATIONS[case_id]
        expected_memberships = {
            page_index: membership
            for (candidate_case, page_index), membership in (
                frozen_oracle.CANONICAL_PAGE_MEMBERSHIP.items()
            )
            if candidate_case == case_id
        }
        canonical_body_match = all(
            list(canonical_pages[page_index]["body"]["block_ids"])
            == list(membership["body_block_ids"])
            for page_index, membership in expected_memberships.items()
        )
        canonical_full_match = all(
            list(canonical_pages[page_index]["full"]["block_ids"])
            == list(membership["full_block_ids"])
            for page_index, membership in expected_memberships.items()
        )
        flag_off_public, flag_off_ir = running_regions.project_running_regions(
            predecessor,
            evidence["predecessor_ir"],
            enabled=False,
        )
        flag_off_byte_match = (
            flag_off_public is predecessor
            and flag_off_ir is evidence["predecessor_ir"]
            and output_identity(flag_off_public) == output_identity(predecessor)
        )
        observed_detected = sum(
            page["page_identity"]["detected_printed_label"] is not None
            for page in pages.values()
        )
        control_passed = (
            case_page_exact == expected["page_count"]
            and observed_detected == expected["detected_labels"]
            and case_region_exact == expected["running_regions"]
            and legacy_identity_match
            and flag_off_byte_match
            and canonical_body_match
            and canonical_full_match
        )
        control_cases[case_id] = {
            "case_id": case_id,
            "page_count": expected["page_count"],
            "expected_detected_labels": expected["detected_labels"],
            "observed_detected_labels": observed_detected,
            "expected_running_regions": expected["running_regions"],
            "observed_running_regions": len(descriptors),
            "legacy_identity_match": legacy_identity_match,
            "flag_off_byte_match": flag_off_byte_match,
            "canonical_body_match": canonical_body_match,
            "canonical_full_match": canonical_full_match,
            "passed": control_passed,
        }

    manufacturing = projected_cases["manufacturing-report"]
    manufacturing_expected = next(
        value
        for value in frozen_oracle.ACCEPTED_RUNNING_REGIONS
        if value["source_method"] == "extracted_source_contribution"
    )
    manufacturing_actual = _projected_region_descriptors(manufacturing["projected"])[
        manufacturing_expected["region_id"]
    ]
    projected_owner = _resolve_projection_path(
        manufacturing["projected"],
        manufacturing_expected["source_public_path"],
    )
    predecessor_owner = _resolve_projection_path(
        manufacturing["predecessor"],
        manufacturing_expected["source_public_path"],
    )
    manufacturing_fused_exact = _canonical_json(
        manufacturing_actual
    ) == _canonical_json(
        frozen_oracle.RUNNING_REGION_DESCRIPTORS[manufacturing_expected["region_id"]]
    )
    manufacturing_owner_unchanged = _canonical_json(projected_owner) == _canonical_json(
        predecessor_owner
    )
    manufacturing_reconstruction = _canonical_json(
        manufacturing["stripped"]
    ) == _canonical_json(manufacturing["predecessor"]) and output_identity(
        manufacturing["stripped_ir"].model_dump(mode="json", exclude_none=True)
    ) == output_identity(
        manufacturing["predecessor_ir"].model_dump(mode="json", exclude_none=True)
    )
    esg = projected_cases["esg-metrics"]
    esg_expected_ids = {
        record["region_id"]
        for record in frozen_oracle.ACCEPTED_RUNNING_REGIONS
        if record["case_id"] == "esg-metrics"
        and record["source_method"]
        in {
            "boundary_navigation",
            "effective_boundary_cluster",
            "printed_label_boundary",
        }
    }
    esg_actual = _projected_region_descriptors(esg["projected"])
    esg_cluster_exact = len(esg_expected_ids) == 3 and all(
        _canonical_json(esg_actual.get(descriptor_id))
        == _canonical_json(frozen_oracle.RUNNING_REGION_DESCRIPTORS[descriptor_id])
        for descriptor_id in esg_expected_ids
    )

    quality = {
        "reviewed_page_count": len(frozen_oracle.PAGE_IDENTITY_DESCRIPTORS),
        "page_identity_exact_count": page_identity_exact_count,
        "page_identity_denominator": len(frozen_oracle.PAGE_IDENTITY_DESCRIPTORS),
        "running_region_exact_count": running_region_exact_count,
        "running_region_denominator": len(frozen_oracle.RUNNING_REGION_DESCRIPTORS),
        "pairwise_order_exact_count": pairwise_order_exact_count,
        "pairwise_order_denominator": len(frozen_oracle.ACCEPTED_RUNNING_REGIONS),
        "manufacturing_header_exact_count": manufacturing_header_exact_count,
        "manufacturing_header_denominator": 3,
        "manufacturing_fused_contribution_exact": manufacturing_fused_exact,
        "manufacturing_public_owner_unchanged": manufacturing_owner_unchanged,
        "manufacturing_source_reconstruction_exact": (manufacturing_reconstruction),
        "esg_cluster_exact": esg_cluster_exact,
        "false_printed_label_promotions": false_printed_label_promotions,
        "duplicate_canonical_contributions": duplicate_canonical_contributions,
        "missing_canonical_contributions": missing_canonical_contributions,
        "legacy_identity_mismatches": legacy_identity_mismatches,
        "determinism_failures": determinism_failures,
        "all_pass": False,
    }
    quality["all_pass"] = (
        quality["page_identity_exact_count"]
        == quality["page_identity_denominator"]
        == 30
        and quality["running_region_exact_count"]
        == quality["running_region_denominator"]
        == 47
        and quality["pairwise_order_exact_count"]
        == quality["pairwise_order_denominator"]
        == 47
        and quality["manufacturing_header_exact_count"]
        == quality["manufacturing_header_denominator"]
        == 3
        and all(
            quality[field] is True
            for field in (
                "manufacturing_fused_contribution_exact",
                "manufacturing_public_owner_unchanged",
                "manufacturing_source_reconstruction_exact",
                "esg_cluster_exact",
            )
        )
        and all(
            quality[field] == 0
            for field in (
                "false_printed_label_promotions",
                "duplicate_canonical_contributions",
                "missing_canonical_contributions",
                "legacy_identity_mismatches",
                "determinism_failures",
            )
        )
    )
    controls = {
        "cases": control_cases,
        "all_pass": all(record["passed"] for record in control_cases.values()),
    }
    rollback = _run_production_rollback_witnesses(manufacturing)
    validate_quality(quality)
    validate_control_matrix(controls, complete=True)
    validate_rollback(rollback)
    return quality, controls, rollback


def _partial_sidecar_refused(
    projected: Mapping[str, Any],
    *,
    source_method: str,
) -> bool:
    from app.services import running_regions

    mutated = deepcopy(dict(projected))
    for page in mutated.get("pages") or []:
        for item in page.get("items") or []:
            descriptor = item.get("running_region") if isinstance(item, dict) else None
            if (
                isinstance(descriptor, Mapping)
                and descriptor.get("source_method") == source_method
            ):
                item.pop("running_region_policy", None)
                try:
                    running_regions.strip_running_regions(mutated)
                except running_regions.RunningRegionError:
                    return True
                return False
    raise MetricsExecutionError("rollback sidecar witness is absent")


def _run_production_rollback_witnesses(
    manufacturing: Mapping[str, Any],
) -> dict[str, Any]:
    from app.services import running_regions

    predecessor = manufacturing["predecessor"]
    predecessor_ir = manufacturing["predecessor_ir"]
    projected = manufacturing["projected"]
    projected_ir = manufacturing["projected_ir"]
    authority = manufacturing["authority"]
    flag_off_public, flag_off_ir = running_regions.project_running_regions(
        predecessor,
        predecessor_ir,
        enabled=False,
    )
    flag_off_exact = (
        flag_off_public is predecessor
        and flag_off_ir is predecessor_ir
        and _canonical_json(flag_off_public) == _canonical_json(predecessor)
    )
    stripped, stripped_ir = running_regions.strip_running_regions(
        projected, projected_ir
    )
    stripped_exact = _canonical_json(stripped) == _canonical_json(
        predecessor
    ) and output_identity(
        stripped_ir.model_dump(mode="json", exclude_none=True)
    ) == output_identity(predecessor_ir.model_dump(mode="json", exclude_none=True))

    original_public_identity = output_identity(predecessor)
    original_ir_identity = output_identity(
        predecessor_ir.model_dump(mode="json", exclude_none=True)
    )
    original_commit = running_regions._commit_projected_page

    def fail_second_page(
        page_index: int,
        public_page: Any,
        ir_page: Any,
    ) -> None:
        if page_index == 2:
            raise RuntimeError("metrics page rollback witness")
        original_commit(page_index, public_page, ir_page)

    with patch.object(
        running_regions,
        "_commit_projected_page",
        side_effect=fail_second_page,
    ):
        page_failed, _page_failed_ir = running_regions.project_running_regions(
            predecessor,
            predecessor_ir,
            authority,
        )
    page_two = next(page for page in page_failed["pages"] if page["page_index"] == 2)
    page_rollback = (
        "running_region_projection_failed_closed"
        in page_two["page_identity"]["concern_codes"]
        and output_identity(predecessor) == original_public_identity
        and output_identity(predecessor_ir.model_dump(mode="json", exclude_none=True))
        == original_ir_identity
    )

    document_rollback = False
    with patch.object(
        running_regions,
        "_repetition_memberships",
        side_effect=RuntimeError("metrics document rollback witness"),
    ):
        try:
            running_regions.project_running_regions(
                predecessor, predecessor_ir, authority
            )
        except RuntimeError:
            document_rollback = (
                output_identity(predecessor) == original_public_identity
                and output_identity(
                    predecessor_ir.model_dump(mode="json", exclude_none=True)
                )
                == original_ir_identity
            )

    canonical_rollback = False
    with patch.object(
        running_regions,
        "_build_projected_canonical",
        side_effect=RuntimeError("metrics canonical rollback witness"),
    ):
        try:
            running_regions.project_running_regions(
                predecessor, predecessor_ir, authority
            )
        except RuntimeError:
            canonical_rollback = (
                output_identity(predecessor) == original_public_identity
                and output_identity(
                    predecessor_ir.model_dump(mode="json", exclude_none=True)
                )
                == original_ir_identity
            )

    replayed = manufacturing["replayed"]
    replayed_ir = manufacturing["replayed_ir"]
    terminal_replay = _semantic_payload(replayed) == _semantic_payload(
        projected
    ) and output_identity(
        replayed_ir.model_dump(mode="json", exclude_none=True)
    ) == output_identity(projected_ir.model_dump(mode="json", exclude_none=True))
    repeated, repeated_ir = running_regions.project_running_regions(
        projected,
        projected_ir,
        authority,
    )
    idempotence = _semantic_payload(repeated) == _semantic_payload(
        projected
    ) and output_identity(
        repeated_ir.model_dump(mode="json", exclude_none=True)
    ) == output_identity(projected_ir.model_dump(mode="json", exclude_none=True))
    witnesses = {
        "flag_off_byte_identical": flag_off_exact,
        "stripped_projection_matches_predecessor": stripped_exact,
        "direct_strip_refused": _partial_sidecar_refused(
            projected, source_method="trusted_layout_role"
        ),
        "extracted_strip_refused": _partial_sidecar_refused(
            projected, source_method="extracted_source_contribution"
        ),
        "page_rollback_passed": page_rollback,
        "document_rollback_passed": document_rollback,
        "canonical_failure_rollback_passed": canonical_rollback,
        "terminal_replay_passed": terminal_replay,
        "idempotence_passed": idempotence,
    }
    return {**witnesses, "all_pass": all(witnesses.values())}


def _paired_output_size_records(
    paired_parser: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for worker in paired_parser["workers"]:
        records.setdefault(worker["target_id"], []).append(
            {
                "target_id": worker["target_id"],
                "pair_index": worker["pair_index"],
                "state": worker["state"],
                "variants": _strict_detach(worker["output_variants"]),
            }
        )
    return records


def _first_failed_stage_record(
    gates: Mapping[str, bool],
    *,
    source_extraction: Mapping[str, Any],
    running_region_projection: Mapping[str, Any],
    paired_parser: Mapping[str, Any],
    comparison_ledgers: Mapping[str, Any],
    output_sizes: Mapping[str, Any],
) -> dict[str, Any]:
    stage = next(name for name in FAILURE_STAGES if gates[name] is False)
    target_id: str | None = None
    if stage in {"source_extraction", "running_region_projection"}:
        targets = (
            source_extraction["targets"]
            if stage == "source_extraction"
            else running_region_projection["targets"]
        )
        target_id = next(
            (
                candidate
                for candidate in PERFORMANCE_TARGETS
                if candidate not in targets
                or targets[candidate]["summary"]["passed"] is False
            ),
            None,
        )
    elif stage == "paired_parser":
        target_id = next(
            (
                candidate
                for candidate in PERFORMANCE_TARGETS
                if paired_parser["targets"].get(candidate, {}).get("passed") is False
            ),
            None,
        )
    elif stage == "comparison_ledgers":
        target_id = next(
            (
                candidate
                for candidate in PERFORMANCE_TARGETS
                if candidate not in comparison_ledgers["targets"]
                or comparison_ledgers["targets"][candidate]["passed"] is False
            ),
            None,
        )
    elif stage == "output_sizes":
        report_limit = int(RESOURCE_LIMITS["report_json_bytes"])
        page_limit = int(RESOURCE_LIMITS["page_identity_json_bytes"])
        descriptor_limit = int(RESOURCE_LIMITS["running_descriptor_json_bytes"])
        for candidate in PERFORMANCE_TARGETS:
            source_record = source_extraction["targets"].get(candidate)
            projection_record = running_region_projection["targets"].get(candidate)
            if source_record is None or projection_record is None:
                continue
            if any(
                measured["output_identity"]["size_bytes"] > report_limit
                for measured in source_record["measured_outputs"]
            ) or any(
                measured["maximum_page_identity_json_bytes"] > page_limit
                or measured["maximum_running_descriptor_json_bytes"] > descriptor_limit
                for measured in projection_record["measured_outputs"]
            ):
                target_id = candidate
                break
        if target_id is None and output_sizes.get("all_within_limits") is False:
            raise MetricsExecutionError("output-size failure target differs")
    if stage in TARGET_SCOPED_FAILURE_STAGES and target_id is None:
        raise MetricsExecutionError("target-scoped production failure differs")
    return {
        "type": "stage_failed",
        "stage": stage,
        "target_id": target_id,
        "pair_index": None,
        "state": None,
    }


def _retain_first_failure_prefix(
    failure: Mapping[str, Any],
    *,
    source_extraction: dict[str, Any],
    running_region_projection: dict[str, Any],
    paired_parser: dict[str, Any],
    comparison_ledgers: dict[str, Any],
    output_sizes: dict[str, Any],
) -> None:
    """Discard target evidence collected after the frozen first failure."""

    stage = failure["stage"]
    target_id = failure["target_id"]
    if stage not in {
        "source_extraction",
        "running_region_projection",
        "comparison_ledgers",
        "output_sizes",
    }:
        return
    if target_id not in PERFORMANCE_TARGETS:
        raise MetricsExecutionError("target-scoped failure prefix differs")
    target_index = PERFORMANCE_TARGETS.index(target_id)
    retained_targets = PERFORMANCE_TARGETS[: target_index + 1]
    future_targets = PERFORMANCE_TARGETS[target_index + 1 :]

    if stage == "source_extraction":
        for candidate in future_targets:
            source_extraction["targets"].pop(candidate, None)
            output_sizes["source_reports"].pop(candidate, None)
    elif stage == "running_region_projection":
        for candidate in future_targets:
            running_region_projection["targets"].pop(candidate, None)
            output_sizes["isolated_projection_outputs"].pop(candidate, None)
            comparison_ledgers["targets"].pop(candidate, None)
        if future_targets:
            comparison_ledgers["all_pass"] = False
    elif stage == "comparison_ledgers":
        for candidate in future_targets:
            comparison_ledgers["targets"].pop(candidate, None)
    else:
        retained_target_set = set(retained_targets)
        for evidence in (source_extraction, running_region_projection):
            evidence["targets"] = {
                candidate: record
                for candidate, record in evidence["targets"].items()
                if candidate in retained_target_set
            }
        comparison_ledgers["targets"] = {
            candidate: record
            for candidate, record in comparison_ledgers["targets"].items()
            if candidate in retained_target_set
        }
        paired_parser["worker_plan"] = [
            work
            for work in paired_parser["worker_plan"]
            if work["target_id"] in retained_target_set
        ]
        paired_parser["workers"] = [
            record
            for record in paired_parser["workers"]
            if record["target_id"] in retained_target_set
        ]
        paired_parser["targets"] = {
            candidate: record
            for candidate, record in paired_parser["targets"].items()
            if candidate in retained_target_set
        }
        for field in (
            "paired_samples",
            "source_reports",
            "isolated_projection_outputs",
        ):
            output_sizes[field] = {
                candidate: record
                for candidate, record in output_sizes[field].items()
                if candidate in retained_target_set
            }

    source_sizes = [
        measured["output_identity"]["size_bytes"]
        for record in source_extraction["targets"].values()
        for measured in record["measured_outputs"]
    ]
    page_sizes = [
        measured["maximum_page_identity_json_bytes"]
        for record in running_region_projection["targets"].values()
        for measured in record["measured_outputs"]
    ]
    descriptor_sizes = [
        measured["maximum_running_descriptor_json_bytes"]
        for record in running_region_projection["targets"].values()
        for measured in record["measured_outputs"]
    ]
    output_sizes["maximum_source_report_json_bytes"] = max(
        source_sizes,
        default=0,
    )
    output_sizes["maximum_page_identity_json_bytes"] = max(
        page_sizes,
        default=0,
    )
    output_sizes["maximum_running_descriptor_json_bytes"] = max(
        descriptor_sizes,
        default=0,
    )
    output_sizes["all_within_limits"] = (
        output_sizes["maximum_source_report_json_bytes"]
        <= int(RESOURCE_LIMITS["report_json_bytes"])
        and output_sizes["maximum_page_identity_json_bytes"]
        <= int(RESOURCE_LIMITS["page_identity_json_bytes"])
        and output_sizes["maximum_running_descriptor_json_bytes"]
        <= int(RESOURCE_LIMITS["running_descriptor_json_bytes"])
    )


def build_production_metrics_candidate(
    repository_root: Path,
    *,
    paired_worker: PairedWorker | None = None,
    worker_timeout_seconds: float = 300.0,
    fail_worker_index: int | None = None,
) -> dict[str, Any]:
    """Run the real campaign and return one unsealed final/failed candidate.

    ``fail_worker_index`` is a deliberate diagnostic seam: all earlier work is
    real, then the selected fresh paired process raises before parsing so the
    retained failed-candidate prefix can be tested without fabricating data.
    """

    root = _resolve_repository_root(repository_root)
    if fail_worker_index is not None and (
        isinstance(fail_worker_index, bool)
        or not isinstance(fail_worker_index, int)
        or not 0 <= fail_worker_index < PAIRED_WORKER_COUNT
    ):
        raise MetricsExecutionError("diagnostic failed worker index differs")
    existing_paths = discover_existing_metrics_artifact_paths(root)
    failed_paths = tuple(
        path
        for path in existing_paths
        if FAILED_ARTIFACT_PATTERN.fullmatch(path) is not None
    )
    observed_prior = collect_prior_artifact_identities(root, failed_paths)
    prior_failed_candidates = [
        {"path": path, **observed_prior[path]} for path in failed_paths
    ]
    input_pre = collect_input_file_identities(root)
    code_pre = collect_code_file_identities(root)
    dependency_custody = collect_dependency_custody(root)
    predecessor_outputs = collect_predecessor_output_identities(root)
    m0_reference = collect_m0_reference_identity(root)

    source_extraction, projection, comparisons, isolated_sizes = (
        _run_production_isolated_stages(root)
    )
    resources, deadlines = _run_production_boundaries()
    quality, controls, rollback = _run_production_quality_and_controls(root)
    input_mid = collect_input_file_identities(root)
    code_mid = collect_code_file_identities(root)
    mid_code_custody = build_code_custody(code_pre, code_mid)
    mid_components = _component_custody_records(mid_code_custody)
    pre_paired_gates = {
        "measurement_protocol": True,
        "policy_contract": True,
        "settings_custody": True,
        "m0_reference": m0_reference
        == {field: M0_ARTIFACT[field] for field in CODE_FILE_IDENTITY_FIELDS},
        "input_custody": input_pre == input_mid,
        "predecessor_custody": predecessor_outputs
        == frozen_oracle.PREDECESSOR_OUTPUT_IDENTITIES,
        "fixture_custody": all(value["match"] for value in mid_components.values()),
        "code_custody": mid_code_custody["pre_post_match"],
        "dependency_custody": True,
        "source_extraction": source_extraction["all_pass"],
        "running_region_projection": projection["all_pass"],
        "resource_boundaries": resources["all_pass"],
        "deadline_boundaries": deadlines["all_pass"],
    }
    paired_failure: Mapping[str, Any] | None = None
    if all(pre_paired_gates.values()):
        try:
            if paired_worker is None:
                paired_parser = run_clean_interpreter_paired_campaign(
                    repository_root=root,
                    worker_timeout_seconds=worker_timeout_seconds,
                    fail_worker_index=fail_worker_index,
                )
            else:
                callback = paired_worker

                def diagnostic_callback(
                    work: Mapping[str, Any],
                ) -> Mapping[str, Any]:
                    if (
                        fail_worker_index is not None
                        and work.get("worker_index") == fail_worker_index
                    ):
                        raise MetricsExecutionError(
                            "diagnostic paired production worker failure"
                        )
                    return callback(work)

                paired_parser = run_paired_campaign(
                    diagnostic_callback,
                    worker_timeout_seconds=worker_timeout_seconds,
                )
        except PairedCampaignFailure as exc:
            paired_parser = exc.campaign
            paired_failure = exc.failure
    else:
        paired_parser = {
            "runner_pid": os.getpid(),
            "worker_plan": [],
            "workers": [],
            "targets": {},
            "all_pass": False,
        }

    input_post = collect_input_file_identities(root)
    code_post = collect_code_file_identities(root)
    code_custody = build_code_custody(code_pre, code_post)
    components = _component_custody_records(code_custody)
    output_sizes = {
        "paired_samples": _paired_output_size_records(paired_parser),
        "source_reports": isolated_sizes["source_reports"],
        "isolated_projection_outputs": isolated_sizes["isolated_projection_outputs"],
        "maximum_page_identity_json_bytes": isolated_sizes[
            "maximum_page_identity_json_bytes"
        ],
        "maximum_running_descriptor_json_bytes": isolated_sizes[
            "maximum_running_descriptor_json_bytes"
        ],
        "maximum_source_report_json_bytes": isolated_sizes[
            "maximum_source_report_json_bytes"
        ],
        "all_within_limits": (
            isolated_sizes["maximum_page_identity_json_bytes"]
            <= int(RESOURCE_LIMITS["page_identity_json_bytes"])
            and isolated_sizes["maximum_running_descriptor_json_bytes"]
            <= int(RESOURCE_LIMITS["running_descriptor_json_bytes"])
            and isolated_sizes["maximum_source_report_json_bytes"]
            <= int(RESOURCE_LIMITS["report_json_bytes"])
        ),
    }
    output_gate = validate_output_sizes(output_sizes, complete=False)
    gates = {
        **pre_paired_gates,
        "input_custody": input_pre == input_post,
        "fixture_custody": all(value["match"] for value in components.values()),
        "code_custody": code_custody["pre_post_match"],
        "paired_parser": paired_parser["all_pass"],
        "quality": quality["all_pass"],
        "control_matrix": controls["all_pass"],
        "comparison_ledgers": comparisons["all_pass"],
        "output_sizes": output_gate,
        "rollback": rollback["all_pass"],
        "failure_free": False,
        "hosted_usage": HOSTED_USAGE
        == {"hosted_requests": 0, "hosted_tokens": 0, "hosted_cost_usd": 0},
    }
    other_gates_pass = all(
        value for name, value in gates.items() if name != "failure_free"
    )
    failures: list[dict[str, Any]] = []
    first_failed_stage = next(
        (stage for stage in FAILURE_STAGES if gates.get(stage) is False),
        None,
    )
    if paired_failure is not None and first_failed_stage == "paired_parser":
        failures.append(_strict_detach(paired_failure))
    elif not other_gates_pass:
        failure = _first_failed_stage_record(
            gates,
            source_extraction=source_extraction,
            running_region_projection=projection,
            paired_parser=paired_parser,
            comparison_ledgers=comparisons,
            output_sizes=output_sizes,
        )
        failures.append(failure)
        _retain_first_failure_prefix(
            failure,
            source_extraction=source_extraction,
            running_region_projection=projection,
            paired_parser=paired_parser,
            comparison_ledgers=comparisons,
            output_sizes=output_sizes,
        )
        gates["comparison_ledgers"] = comparisons["all_pass"]
    gates["failure_free"] = not failures
    complete = all(gates.values())
    if complete and str(FINAL_ARTIFACT_RELATIVE_PATH) in existing_paths:
        raise MetricsExecutionError("final metrics artifact already exists")
    retained_path = (
        FINAL_ARTIFACT_RELATIVE_PATH
        if complete
        else next_failed_artifact_relative_path(existing_paths)
    )
    aggregate = {**gates, "all_pass": complete}
    candidate: dict[str, Any] = {
        "schema_version": "1.0",
        "record_kind": "p03_us08_running_region_metrics",
        "story": "P03-US08",
        "status": (
            "final_measurement_candidate"
            if complete
            else "failed_measurement_candidate"
        ),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "retained_path": str(retained_path),
        "measurement": _measurement_record(),
        "policy": _policy_record(),
        "settings_delta": _settings_delta_record(),
        "m0_reference": _strict_detach(M0_ARTIFACT),
        "input_custody": _input_custody_record(input_pre, input_post),
        "predecessor_custody": _predecessor_custody_record(predecessor_outputs),
        **components,
        "code_sha256": code_custody,
        "dependency_custody": dependency_custody,
        "source_extraction": source_extraction,
        "running_region_projection": projection,
        "resource_boundaries": resources,
        "deadline_boundaries": deadlines,
        "paired_parser": paired_parser,
        "quality": quality,
        "control_matrix": controls,
        "comparison_ledgers": comparisons,
        "output_sizes": output_sizes,
        "rollback": rollback,
        "prior_failed_candidates": prior_failed_candidates,
        "failures": failures,
        "aggregate": aggregate,
        **HOSTED_USAGE,
    }
    if set(candidate) != set(ARTIFACT_TOP_LEVEL_FIELDS) - {"semantic_sha256"}:
        raise MetricsExecutionError("production candidate field set differs")
    return candidate


def build_seal_and_optionally_write_production_metrics(
    repository_root: Path,
    *,
    write: bool = False,
    worker_timeout_seconds: float = 300.0,
    fail_worker_index: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run, seal, and optionally exclusive-create one retained artifact."""

    root = _resolve_repository_root(repository_root)
    existing_paths = discover_existing_metrics_artifact_paths(root)
    candidate = build_production_metrics_candidate(
        root,
        worker_timeout_seconds=worker_timeout_seconds,
        fail_worker_index=fail_worker_index,
    )
    sealed = seal_metrics_artifact(
        candidate,
        repository_root=root,
        expected_existing_paths=existing_paths,
    )
    identity = None
    if write:
        destination = root.joinpath(*PurePosixPath(sealed["retained_path"]).parts)
        identity = write_artifact_exclusive(
            destination,
            sealed,
            repository_root=root,
            expected_existing_paths=existing_paths,
        )
    return sealed, identity


def _production_cli(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the P03-US08 retained production metrics campaign."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--worker-timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--fail-worker-index",
        type=int,
        help="diagnostically fail this fresh paired worker and retain its prefix",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="exclusive-create the sealed candidate at its retained path",
    )
    parser.add_argument(
        "--internal-paired-worker",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--internal-fail-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    arguments = parser.parse_args(argv)
    if arguments.internal_paired_worker is not None:
        if arguments.write or arguments.fail_worker_index is not None:
            return 2
        return _internal_clean_worker(
            arguments.internal_paired_worker,
            repository_root=arguments.repository_root,
            fail=arguments.internal_fail_worker,
        )
    if arguments.internal_fail_worker:
        return 2
    sealed, identity = build_seal_and_optionally_write_production_metrics(
        arguments.repository_root,
        write=arguments.write,
        worker_timeout_seconds=arguments.worker_timeout_seconds,
        fail_worker_index=arguments.fail_worker_index,
    )
    print(
        _canonical_json(
            {
                "status": sealed["status"],
                "retained_path": sealed["retained_path"],
                "semantic_sha256": sealed["semantic_sha256"],
                "written_identity": identity,
            }
        )
    )
    return 0 if sealed["status"] == "final_measurement_candidate" else 1


__all__ = [
    "AGGREGATE_FIELDS",
    "ARTIFACT_FAILURE_FIELDS",
    "ARTIFACT_SEMANTIC_FIELDS_REMOVED",
    "ARTIFACT_TOP_LEVEL_FIELDS",
    "ARTIFACT_WRITE_CAP_BYTES",
    "CACHE_DISCLAIMER",
    "CODE_CUSTODY_FIELDS",
    "CODE_CUSTODY_RECORD_FIELDS",
    "CODE_FILE_IDENTITY_FIELDS",
    "COMPARISON_LEDGERS_FIELDS",
    "COMPARISON_LEDGER_FIELDS",
    "COMPONENT_EXPECTED_SEMANTIC_SHA256",
    "COMPONENT_PATHS",
    "CONTROL_CASE_FIELDS",
    "CONTROL_MATRIX_FIELDS",
    "DEADLINE_BOUNDARIES_FIELDS",
    "DEADLINE_BOUNDARY_FIELDS",
    "DEADLINE_LIMITS_SECONDS",
    "DEPENDENCY_CUSTODY_FIELDS",
    "DEPENDENCY_LOCAL_TOOL_FIELDS",
    "DEPENDENCY_MANIFEST_PATHS",
    "DEPENDENCY_PACKAGE_FIELDS",
    "DEPENDENCY_REQUIRED_LOCAL_TOOLS",
    "DEPENDENCY_REQUIRED_PYTHON_PACKAGES",
    "DEPENDENCY_RUNTIME_FIELDS",
    "EXACT_ACCEPTANCE_OUTCOME",
    "EXECUTION_ORDER_POLICY",
    "FAILED_ARTIFACT_PATTERN",
    "FAILURE_STAGES",
    "FAILURE_TYPES",
    "FINAL_ARTIFACT_RELATIVE_PATH",
    "HOSTED_USAGE",
    "INPUT_CUSTODY_FIELDS",
    "ISOLATED_ALLOCATION_SAMPLES",
    "ISOLATED_ALLOCATION_WARMUPS",
    "ISOLATED_LATENCY_SAMPLES",
    "ISOLATED_LATENCY_WARMUPS",
    "ISOLATED_MEASURED_OUTPUT_FIELDS",
    "ISOLATED_PROJECTION_P95_SECONDS",
    "ISOLATED_SOURCE_EXTRACTION_P95_SECONDS",
    "ISOLATED_STAGE_FIELDS",
    "ISOLATED_SUMMARY_FIELDS",
    "ISOLATED_TARGET_FIELDS",
    "LOCAL_TOOL_PROBE_OUTPUT_CAP_BYTES",
    "LOCAL_TOOL_PROBE_TIMEOUT_SECONDS",
    "M0_ARTIFACT",
    "M0_REFERENCE_FIELDS",
    "M0_TARGET_FIELDS",
    "MAXIMUM_PAGE_EXECUTION_FIELDS",
    "MAXIMUM_PAGE_FIXTURE_ID",
    "MAXIMUM_PAGE_WORKLOAD",
    "MAXIMUM_PAGE_WORKLOAD_FIELDS",
    "MAX_CODE_CUSTODY_FILES",
    "MAX_CODE_CUSTODY_FILE_BYTES",
    "MAX_CODE_CUSTODY_TOTAL_BYTES",
    "MAX_DEPENDENCY_MANIFEST_BYTES",
    "MAX_DEPENDENCY_MANIFEST_TOTAL_BYTES",
    "MAX_FAILED_ARTIFACT_ATTEMPTS",
    "MEASUREMENT_FIELDS",
    "OBSERVED_PRIOR_ARTIFACT_FIELDS",
    "OFFLINE_ENVIRONMENT",
    "OFFLINE_ENVIRONMENT_FIELDS",
    "OUTPUT_IDENTITY_FIELDS",
    "OUTPUT_SAMPLE_FIELDS",
    "OUTPUT_SIZES_FIELDS",
    "OUTPUT_VARIANTS",
    "PAIRED_CALLBACK_FIELDS",
    "PAIRED_FAILURE_TYPES",
    "PAIRED_FIXED_CEILINGS_SECONDS",
    "PAIRED_PARSER_FIELDS",
    "PAIRED_REPEAT_COUNT",
    "PAIRED_STATE_ORDER",
    "PAIRED_WORKER_COUNT",
    "PAIRED_WORKER_PLAN",
    "PAIRED_WORKER_RECORD_FIELDS",
    "PAIRED_WORKER_WIRE_CAP_BYTES",
    "PEAK_ALLOCATION_CEILING_BYTES",
    "PEAK_RSS_DELTA_CEILING_BYTES",
    "PERFORMANCE_TARGETS",
    "POLICY_FIELDS",
    "POLICY_ID",
    "PREDECESSOR_CUSTODY_FIELDS",
    "PREDECESSOR_FLAG_NAMES",
    "PREDECESSOR_OUTPUT_FIELDS",
    "PRIOR_ARTIFACT_READ_CAP_BYTES",
    "PRIOR_FAILED_CANDIDATE_FIELDS",
    "QUALITY_FIELDS",
    "QUANTILE_FORMULA",
    "QUANTILE_METHOD",
    "REFUSAL_OUTCOMES",
    "REQUIRED_CODE_PATHS",
    "RESOURCE_BOUNDARIES_FIELDS",
    "RESOURCE_BOUNDARY_FIELDS",
    "RESOURCE_COUNTERS",
    "RESOURCE_LIMITS",
    "ROLLBACK_FIELDS",
    "SEALED_COMPONENT_CUSTODY_FIELDS",
    "SETTINGS_DELTA_FIELDS",
    "SETTINGS_FLAG_NAMES",
    "SOURCE_IDENTITY_FIELDS",
    "SOURCE_REPORT_TIMING_PATHS_REMOVED",
    "TIMING_PATHS_REMOVED",
    "WHOLE_PARSER_CLOCK",
    "WHOLE_PARSER_SCOPE",
    "InjectedMonotonicClock",
    "MaximumPageExecutionResult",
    "MetricsExecutionError",
    "PairedCampaignFailure",
    "ProductionBoundaryResult",
    "ProductionDeadlineResult",
    "_artifact_semantic_payload",
    "_artifact_semantic_sha256",
    "_canonical_json",
    "_inclusive_p95",
    "_paired_performance_summary",
    "_paired_states",
    "_profile_allocation",
    "_profile_timing",
    "_report_semantic_payload",
    "_rss_bytes_from_maxrss",
    "_semantic_payload",
    "build_code_custody",
    "build_production_metrics_candidate",
    "build_seal_and_optionally_write_production_metrics",
    "collect_code_file_identities",
    "collect_dependency_custody",
    "collect_input_file_identities",
    "collect_m0_reference_identity",
    "collect_predecessor_output_identities",
    "collect_prior_artifact_identities",
    "discover_existing_metrics_artifact_paths",
    "execute_maximum_page_workload",
    "exercise_production_boundary",
    "exercise_production_deadline",
    "next_failed_artifact_relative_path",
    "output_identity",
    "production_output_variants",
    "production_paired_worker",
    "run_clean_interpreter_paired_campaign",
    "run_paired_campaign",
    "seal_metrics_artifact",
    "validate_aggregate",
    "validate_code_custody",
    "validate_comparison_ledgers",
    "validate_component_custody",
    "validate_control_matrix",
    "validate_deadline_boundaries",
    "validate_dependency_custody",
    "validate_failure_coherence",
    "validate_input_custody",
    "validate_isolated_stage",
    "validate_m0_reference",
    "validate_maximum_page_execution",
    "validate_maximum_page_workload",
    "validate_measurement",
    "validate_metrics_artifact",
    "validate_output_cross_bindings",
    "validate_output_sizes",
    "validate_paired_parser",
    "validate_policy",
    "validate_predecessor_custody",
    "validate_prior_failed_candidates",
    "validate_quality",
    "validate_resource_boundaries",
    "validate_rollback",
    "validate_settings_delta",
    "write_artifact_exclusive",
]


if __name__ == "__main__":  # pragma: no cover - exercised as a retained CLI
    raise SystemExit(_production_cli())
