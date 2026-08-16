"""P04-US01 table metrics harness and retained-artifact contract.

The expensive measurements in this module run in fresh local subprocesses.
That keeps process high-water RSS meaningful and prevents a flag-off sample
from warming the corresponding flag-on sample.  The module is deliberately
test-only: it neither changes parser behavior nor adds benchmark truth.

Only dimensions already qualified by :mod:`oracle` are admitted to the
quality denominator.  A dimension that cannot be observed mechanically must
be supplied as a separately reviewed observation with an exact evidence-file
identity; it is never inferred from nearby text.
"""

from __future__ import annotations

import argparse
import ast
import csv
import gc
import hashlib
import html
import io
import json
import math
import os
import re
import resource
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from pydantic_core import SchemaValidator

from tests.fixtures.phase_03.running_regions.contract import (
    OFFLINE_ENVIRONMENT,
)
from tests.fixtures.phase_03.running_regions.oracle import (
    PREDECESSOR_CONFIGURATION,
)
from tests.fixtures.phase_04.tables.content_bbox_oracle import (
    EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION,
    NUMERIC_COMPARISON_SLACK_PT,
    NORMALIZED_BBOX_KEYS,
    source_content_bbox_oracle_metadata,
)
from tests.fixtures.phase_04.tables.contract import CONCERN_CODES, TABLE_LIMITS
from tests.fixtures.phase_04.tables.oracle import (
    P04_US01_REAL_ORACLE,
    oracle_sha256,
)
from tests.fixtures.phase_04.tables import rss_lane


WORKSPACE = Path(__file__).resolve().parents[4]
SCHEMA_ID = "p04-us01-table-metrics-v13"
STORY_ID = "P04-US01"
FINAL_METRICS_RELATIVE_PATH = (
    "tracker/phase-04-tables/evidence/P04-US01-final-metrics.json"
)
REPORT_SEMANTIC_PROJECTION_ID = (
    "p04-us01-final-metrics-semantic-projection-v13"
)
PAIRED_PERFORMANCE_SCHEMA_ID = "p04-us01-paired-performance-v12"
TABLE_STAGE_OVERHEAD_FORMULA_ID = (
    "p04-us01-paired-nonnegative-additive-table-stage-over-flag-off-wall-v1"
)
PHASE04_STAGE_RSS_SOURCE = "resource.getrusage(RUSAGE_SELF).ru_maxrss"
PHASE04_STAGE_RSS_NORMALIZATION = (
    "bytes_on_darwin_else_kibibytes_times_1024"
)
PHASE04_STAGE_RSS_SAMPLING_SCOPE = (
    "controller_owned_observer_process_with_dedicated_single_thread_"
    "current_rss_lane_process_targeting_exact_"
    "fresh_worker_pid_and_create_time_from_first_measured_phase04_table_"
    "stage_pre_entry_through_"
    "production_json_and_markdown_output_completion_with_independent_"
    "continuous_current_rss_timed_select_deadline_or_forced_handoff_lane_"
    "and_live_"
    "recursive_child_observer_with_forced_"
    "request_completion_generation_handoffs_around_every_active_fifo_"
    "serialized_recursive_child_scan_plus_worker_acknowledged_synchronous_"
    "bracketed_path_boundary_samples_and_worker_supplied_hwm_rusage"
)
PHASE04_STAGE_CURRENT_RSS_SOURCE = (
    "psutil.Process(exact_worker_pid_create_time).memory_info().rss"
)
PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION = "7.2.2"
PHASE04_STAGE_RSS_CHILD_SCOPE = (
    "exact_worker_process_only_live_recursive_children_forbidden_by_parent_"
    "observer_and_bracketed_boundaries_with_reaped_children_full_rusage_"
    "fingerprint_unchanged_and_detached_double_fork_escape_not_guaranteed"
)
PHASE04_STAGE_RSS_TARGET_INTERVAL_NS = 1_000_000
PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS = 10_000_000
PHASE04_STAGE_DARWIN_QOS_CLASS = 0x21
PHASE04_STAGE_DARWIN_QOS_CLASS_NAME = "QOS_CLASS_USER_INTERACTIVE"
PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY = 0
PHASE04_STAGE_THREAD_QOS_POLICY = (
    "darwin_pthread_set_and_get_qos_class_self_np_user_interactive_zero_"
    "relative_priority_verified_per_observer_main_and_child_thread;_"
    "current_rss_lane_main_thread_has_separate_verified_qos_custody;_"
    "non_darwin_explicitly_unapplied_with_unchanged_hard_gap_fail_closed"
)
PHASE04_STAGE_CHILD_OBSERVER_SOURCE = (
    "psutil.Process(exact_worker_pid_create_time).children(recursive=True)"
)
PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION = "7.2.2"
PHASE04_STAGE_CHILD_OBSERVER_TARGET_INTERVAL_NS = 25_000_000
PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS = 100_000_000
PHASE04_STAGE_CHILD_OBSERVER_RESIDUAL = (
    "detached_setsid_or_double_fork_escape_and_pid_reparenting_are_not_"
    "guaranteed_observable_by_recursive_child_polling_or_rusage"
)
PHASE04_STAGE_FIRST_OBSERVATION_READY_SECONDS = 1.0
PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID = (
    "p04-us01-worker-max-parse-and-output-current-hwm-growth-v3"
)
PAIRED_PHASE04_STAGE_PEAK_RSS_DELTA_FORMULA_ID = (
    "p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-"
    "output-complete-peak-rss-increment-v3"
)
PHASE04_STAGE_OUTPUT_PROBE_SCHEMA_ID = "p04-us01-production-output-probe-v1"
PHASE04_STAGE_OUTPUT_PATH = (
    "jsonable_encoder_then_ParseResult_validate_then_exclude_unset_dump_then_"
    "JSONResponse_body_release_then_markdown_serializer_and_Response_body"
)
PHASE04_STAGE_OUTPUT_BOUNDARIES = (
    "source_result_identity_pre",
    "source_result_identity_post",
    "source_result_identity_release_post",
    "jsonable_encoder_pre",
    "jsonable_encoder_post",
    "jsonable_streaming_identity_post",
    "parse_result_validate_post",
    "public_result_dump_post",
    "public_result_streaming_identity_post",
    "json_response_pre",
    "json_response_body_post",
    "json_response_streaming_identity_post",
    "json_response_release_post",
    "markdown_serializer_pre",
    "markdown_serializer_post",
    "markdown_response_pre",
    "markdown_response_body_post",
    "public_result_after_streaming_identity_post",
)
PHASE04_STAGE_OUTPUT_PROBE_FIELDS = (
    "schema_id",
    "production_output_path",
    "output_boundary_names",
    "output_boundary_count",
    "source_result_before_size_bytes",
    "source_result_before_sha256",
    "source_result_after_size_bytes",
    "source_result_after_sha256",
    "source_result_unchanged",
    "jsonable_result_size_bytes",
    "jsonable_result_sha256",
    "public_result_size_bytes",
    "public_result_sha256",
    "public_result_after_size_bytes",
    "public_result_after_sha256",
    "public_result_unchanged",
    "json_response_body_size_bytes",
    "json_response_body_sha256",
    "json_response_decodes_to_public_result",
    "json_response_media_type",
    "json_response_released_before_markdown",
    "markdown_utf8_size_bytes",
    "markdown_utf8_sha256",
    "markdown_response_body_size_bytes",
    "markdown_response_body_sha256",
    "markdown_response_matches_utf8",
    "markdown_response_media_type",
)
PHASE04_STAGE_CHILDREN_HWM_SOURCE = (
    "resource.getrusage(RUSAGE_CHILDREN).ru_maxrss"
)
PHASE04_STAGE_CHILDREN_RUSAGE_SOURCE = (
    "resource.getrusage(resource.RUSAGE_CHILDREN)"
)
PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID = (
    "p04-us01-children-rusage-fingerprint-v1"
)
PHASE04_STAGE_CHILDREN_RUSAGE_COUNTER_FIELDS = (
    "ru_ixrss",
    "ru_idrss",
    "ru_isrss",
    "ru_minflt",
    "ru_majflt",
    "ru_nswap",
    "ru_inblock",
    "ru_oublock",
    "ru_msgsnd",
    "ru_msgrcv",
    "ru_nsignals",
    "ru_nvcsw",
    "ru_nivcsw",
)
PHASE04_NO_SPAWN_SCHEMA_ID = "p04-us01-worker-no-spawn-static-guard-v1"
DEADLINE_PROBE_SCHEMA_ID = "p04-us01-deadline-probes-v1"
DENSE_SCALING_SCHEMA_ID = "p04-us01-dense-scaling-v1"
QUALITY_EVIDENCE_SCHEMA_ID = "p04-us01-quality-evidence-v9"
TERMINAL_APPROVAL_BINDING = "semantic_projection_sha256"
TERMINAL_CHAIN_BINDING = (
    "validated_phase03_exception_chain_and_exact_us01_story_gate_"
    "preapproval_bytes"
)
PAIR_COUNT = 5
PERFORMANCE_CASES = ("ny-timetable", "postal-10k", "finance-10k")
QUALITY_CASES = tuple(source.case_id for source in P04_US01_REAL_ORACLE.sources)
REAL_METRICS_ENVIRONMENT = "P04_US01_RUN_REAL_METRICS"
WORKER_TIMEOUT_SECONDS = 360
MAXIMUM_RETAINED_METRICS_BYTES = 64 * 1024 * 1024
MAXIMUM_IDENTITY_FILE_BYTES = 16 * 1024 * 1024
MAXIMUM_DISCOVERED_PATHS = 512
MAXIMUM_DISCOVERED_TOTAL_BYTES = 128 * 1024 * 1024
MAXIMUM_RELATIVE_PATH_DEPTH = 24
MAXIMUM_JSON_DEPTH = 64
MAXIMUM_JSON_NODES = 1_000_000
MAXIMUM_JSON_STRING_BYTES = 32 * 1024 * 1024
MAXIMUM_WORKER_DIAGNOSTIC_BYTES = 256 * 1024
WORKER_DIAGNOSTIC_SCHEMA_ID = "p04-us01-worker-diagnostics-v1"
MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES = 64 * 1024
OBSERVER_DIAGNOSTIC_SCHEMA_ID = "p04-us01-observer-diagnostics-v1"
WORKER_GROUP_IDENTITY_SCHEMA_ID = "p04-us01-worker-process-group-v1"
EXTERNAL_RSS_MONITOR_SCHEMA_ID = "p04-us01-external-rss-monitor-v1"
EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID = (
    "p04-us01-external-rss-monitor-attestation-v9"
)
EXTERNAL_RSS_OBSERVER_SCHEMA_ID = "p04-us01-controller-observer-process-v5"
CURRENT_RSS_LANE_FAILURE_CUSTODY_SCHEMA_ID = (
    "p04-us01-current-rss-lane-failure-custody-v1"
)
EXTERNAL_RSS_MONITOR_FAILURE_CUSTODY_SCHEMA_ID = (
    "p04-us01-external-rss-monitor-failure-custody-v1"
)
EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID = (
    "p04-us01-external-rss-failure-transaction-v1"
)
EXTERNAL_RSS_OBSERVER_OPERATIONS = (
    "BIND",
    "PREPARE",
    "START",
    "BOUNDARY",
    "PARSE",
    "OUTPUT",
    "FINISH",
    "ABORT",
)
EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE = (
    "dedicated_controller_owned_observer_process_only_from_pre_bind_"
    "collection_through_sampler_quiescence_and_runtime_restoration;_"
    "controller_and_fresh_worker_runtime_unchanged_by_observer"
)
EXTERNAL_RSS_MONITOR_CONTROLLER_IDENTITY_SOURCE = (
    "psutil.Process(controller_pid).create_time_plus_posix_getpgrp_getsid"
)
EXTERNAL_RSS_MONITOR_FRAMING = (
    "af_unix_stream_socketpair_four_byte_unsigned_big_endian_length_then_"
    "canonical_json"
)
EXTERNAL_RSS_MONITOR_SCHEDULER_SCOPE = (
    "controller_process_only_exclusive_lock_from_worker_identity_binding_"
    "through_worker_process_and_monitor_cleanup;_fresh_worker_runtime_"
    "switch_interval_unchanged"
)
EXTERNAL_RSS_MONITOR_GC_SCOPE = (
    "controller_process_only_exclusive_pre_window_collection_then_automatic_"
    "cyclic_gc_disabled_from_worker_identity_binding_through_sampler_"
    "quiescence_and_restored_before_worker_release;_fresh_worker_gc_unchanged"
)
EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES = 64 * 1024
EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES = 1024 * 1024
MAXIMUM_EXTERNAL_RSS_FAILURE_CUSTODY_BYTES = 2 * 1024 * 1024
EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES = 65_536
EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES = 16 * 1024 * 1024
EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS = 5.0
EXTERNAL_RSS_OBSERVER_QUALIFICATION_TIMEOUT_SECONDS = (
    rss_lane.QUALIFICATION_RESPONSE_TIMEOUT_SECONDS + 1.0
)
EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS = 0.00025
EXTERNAL_RSS_MONITOR_OPERATIONS = (
    "PREPARE",
    "START",
    "BOUNDARY",
    "PARSE",
    "OUTPUT",
    "FINISH",
    "ABORT",
)
_EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK = threading.Lock()
WORKER_BOOTSTRAP_READY_SECONDS = 1.0
WORKER_GROUP_TERM_GRACE_SECONDS = 0.250
WORKER_GROUP_KILL_GRACE_SECONDS = 1.0
_WORKER_EXEC_BOOTSTRAP = (
    "import os,sys\n"
    "ready=int(sys.argv[1]); release=int(sys.argv[2]); command=sys.argv[3:]\n"
    "os.write(ready,b'R'); os.close(ready)\n"
    "permission=os.read(release,1); os.close(release)\n"
    "if permission != b'G': os._exit(126)\n"
    "os.execvpe(command[0],command,os.environ)\n"
)


class _WorkerProcessControlError(RuntimeError):
    """Private marker for fixed, content-free worker control failures."""


WORKER_LIFETIME_LEASE_SCHEMA_ID = "p04-us01-worker-lifetime-lease-v1"
WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS = (
    "poll",
    "wait",
    "reap",
    "ownership_release",
    "process_group_cleanup",
)


def _sigchld_disposition_name(value: Any) -> str:
    if value is signal.SIG_DFL or value == signal.SIG_DFL:
        return "SIG_DFL"
    if value is signal.SIG_IGN or value == signal.SIG_IGN:
        return "SIG_IGN"
    return "custom_handler"


class _WorkerLifetimeLease:
    """Forbid PID release or reaping until both sampling lanes are quiescent."""

    def __init__(self) -> None:
        self._state = "created"
        self._process: Any | None = None
        self._ownership: dict[str, Any] | None = None
        self._worker_identity: dict[str, Any] | None = None
        self._sigchld_disposition: str | None = None
        self._events: list[str] = []
        self._forbidden_attempt_counts = {
            operation: 0
            for operation in WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS
        }
        self._monitor_bound = False
        self._worker_bootstrap_released = False
        self._observer_sampling_quiesced = False
        self._current_rss_lane_quiesced = False
        self._failure_preserved_unreaped = False

    @staticmethod
    def require_default_sigchld() -> str:
        if not hasattr(signal, "SIGCHLD"):
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=sigchld_policy_failure"
            )
        observed = _sigchld_disposition_name(signal.getsignal(signal.SIGCHLD))
        if observed != "SIG_DFL":
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=sigchld_policy_failure "
                f"observed_disposition={observed}"
            )
        return observed

    @property
    def active(self) -> bool:
        return self._state == "active"

    @property
    def released(self) -> bool:
        return self._state in {
            "released_after_sampling_quiescence",
            "released_after_failed_setup_quiescence",
        }

    @property
    def worker_bootstrap_released(self) -> bool:
        return self._worker_bootstrap_released

    def acquire(self, process: Any, ownership: Mapping[str, Any]) -> None:
        if self._state != "created":
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_state_failure"
            )
        self._sigchld_disposition = self.require_default_sigchld()
        # The blocked bootstrap cannot execute user code yet. Bind its complete
        # kernel and psutil identity without poll()/wait(), which could reap it.
        _validate_worker_group_identity_without_reap(process, ownership)
        import psutil

        target = psutil.Process(ownership["leader_pid"])
        parent_pid = target.ppid()
        create_time_ns = int(round(float(target.create_time()) * 1e9))
        pgid = os.getpgid(target.pid)
        sid = os.getsid(target.pid)
        if (
            parent_pid != ownership["owner_pid"]
            or create_time_ns != ownership["leader_create_time_ns"]
            or pgid != ownership["pgid"]
            or sid != ownership["sid"]
        ):
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_identity_failure"
            )
        self._process = process
        self._ownership = deepcopy(dict(ownership))
        self._worker_identity = {
            "pid": ownership["leader_pid"],
            "process_create_time_ns": ownership["leader_create_time_ns"],
            "parent_pid": ownership["owner_pid"],
            "pgid": ownership["pgid"],
            "sid": ownership["sid"],
        }
        self._state = "active"
        self._events.append("lease_acquired")

    def bind_monitor(self, process: Any, ownership: Mapping[str, Any]) -> None:
        self.require_active_identity(process, ownership)
        if self._monitor_bound:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_state_failure"
            )
        self._monitor_bound = True
        self._events.append("monitor_bound")

    def record_worker_bootstrap_released(self) -> None:
        if not self.active or not self._monitor_bound or self._worker_bootstrap_released:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_order_failure"
            )
        self._worker_bootstrap_released = True
        self._events.append("worker_bootstrap_released")

    def require_active_identity(
        self,
        process: Any,
        ownership: Mapping[str, Any],
    ) -> None:
        if (
            not self.active
            or process is not self._process
            or self._ownership is None
            or _canonical_bytes(dict(ownership))
            != _canonical_bytes(self._ownership)
        ):
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_identity_failure"
            )
        _validate_worker_group_identity_without_reap(process, ownership)

    def require_operation_allowed(self, operation: str) -> None:
        if operation not in self._forbidden_attempt_counts:
            raise ValueError("worker lifetime lease operation differs")
        if self.active:
            self._forbidden_attempt_counts[operation] += 1
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_early_operation "
                f"operation={operation}"
            )

    def release_after_sampling_quiescence(
        self,
        *,
        observer_quiesced: bool,
        current_rss_lane_quiesced: bool,
    ) -> None:
        if self.released:
            return
        if (
            not self.active
            or not self._monitor_bound
            or not self._worker_bootstrap_released
            or observer_quiesced is not True
            or current_rss_lane_quiesced is not True
        ):
            self.require_operation_allowed("ownership_release")
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_order_failure"
            )
        self._observer_sampling_quiesced = True
        self._events.append("observer_sampling_quiesced")
        self._current_rss_lane_quiesced = True
        self._events.append("current_rss_lane_quiesced")
        self._state = "released_after_sampling_quiescence"
        self._events.append("lease_released")

    def preserve_unreaped_after_monitor_failure(self) -> None:
        if not self.active:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_state_failure"
            )
        self._failure_preserved_unreaped = True
        self._state = "failure_preserved_unreaped"
        self._events.append("failure_preserved_unreaped")

    def release_after_failed_setup_quiescence(
        self,
        *,
        observer_quiesced: bool,
        current_rss_lane_quiesced: bool,
    ) -> None:
        if self.released:
            return
        if (
            not self.active
            or self._worker_bootstrap_released
            or observer_quiesced is not True
            or current_rss_lane_quiesced is not True
        ):
            self.require_operation_allowed("ownership_release")
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=lifetime_lease_order_failure"
            )
        self._observer_sampling_quiesced = True
        self._events.append("observer_sampling_quiesced")
        self._current_rss_lane_quiesced = True
        self._events.append("current_rss_lane_quiesced")
        self._state = "released_after_failed_setup_quiescence"
        self._events.append("failed_setup_lease_released")

    def record(self, *, require_success: bool) -> dict[str, Any]:
        if self._worker_identity is None or self._sigchld_disposition is None:
            raise RuntimeError("worker lifetime lease evidence is incomplete")
        if require_success and (
            not self.released
            or self._events
            != [
                "lease_acquired",
                "monitor_bound",
                "worker_bootstrap_released",
                "observer_sampling_quiesced",
                "current_rss_lane_quiesced",
                "lease_released",
            ]
            or any(self._forbidden_attempt_counts.values())
        ):
            raise RuntimeError("worker lifetime lease success evidence differs")
        return {
            "schema_id": WORKER_LIFETIME_LEASE_SCHEMA_ID,
            "state": self._state,
            "worker_identity": deepcopy(self._worker_identity),
            "sigchld": {
                "required_disposition": "SIG_DFL",
                "observed_disposition": self._sigchld_disposition,
                "safe_default": self._sigchld_disposition == "SIG_DFL",
            },
            "events": list(self._events),
            "monitor_bound_before_worker_bootstrap_release": (
                self._monitor_bound and self._worker_bootstrap_released
            ),
            "observer_sampling_quiesced_before_release": (
                self._observer_sampling_quiesced and self.released
            ),
            "current_rss_lane_quiesced_before_release": (
                self._current_rss_lane_quiesced and self.released
            ),
            "forbidden_while_active_attempt_counts": dict(
                self._forbidden_attempt_counts
            ),
            "failure_preserved_unreaped": self._failure_preserved_unreaped,
        }


EXECUTION_ACCOUNTING_SCHEMA_ID = "p04-us01-execution-accounting-v3"
PREAPPROVAL_EXECUTION_BINDING_SCHEMA_ID = (
    "p04-us01-retained-metrics-preapproval-binding-v1"
)
WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT = {
    "DOCLING_LOG_LEVEL": "ERROR",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "TRANSFORMERS_VERBOSITY": "error",
    "TQDM_DISABLE": "1",
}
HOSTED_USAGE = {
    "hosted_requests": 0,
    "hosted_tokens": 0,
    "hosted_cost_usd": 0,
}

FINAL_CODE_IDENTITY_FIELDS = ("path", "size_bytes", "sha256")
DOWNSTREAM_EVIDENCE_MANIFEST_SCHEMA_ID = (
    "p04-us01-downstream-evidence-manifest-v1"
)
DOWNSTREAM_EVIDENCE_MANIFEST_PATH = (
    "tracker/phase-04-tables/evidence/"
    "P04-US01-downstream-evidence-manifest.json"
)
MUTABLE_TERMINAL_STATUS_OWNER_PATHS = (
    "tracker/phase-04-tables/stories/P04-US01.md",
    "tracker/phase-04-tables/metrics.md",
    "tracker/phase-04-tables/phase-regression.md",
)
UPSTREAM_APPROVAL_EVIDENCE_PATHS = (
    "tracker/phase-04-tables/evidence/P04-US01-external-rss-lane-final-code-amendment-independent-review.md",
    "tracker/phase-04-tables/evidence/P04-US01-conditional-stage-reachability-final-code-amendment-independent-review.md",
    "tracker/phase-04-tables/evidence/P04-US01-v13-compact-transport-monitor-controlled-supersession-independent-review.md",
)
_REQUIRED_FINAL_CODE_EXPLICIT_PATHS = (
    ".env.example",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "app/api.py",
    "app/config.py",
    "app/models.py",
    "app/services/ir.py",
    "app/services/opaque_group_custody.py",
    "app/services/pipeline.py",
    "app/services/presentation.py",
    "app/services/serializer.py",
    "app/services/source_text_alignment.py",
    "app/services/text_reconciliation.py",
    "frontend/app/clearleaf-workspace.tsx",
    "frontend/eslint.config.mjs",
    "frontend/lib/types.ts",
    "frontend/next.config.ts",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/tests/p04-us01-table-readiness.test.mts",
    "frontend/tests/p04-us01-table-span-fidelity.test.mts",
    "frontend/tests/workspace-canonical-ui.test.mts",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "tests/fixtures/phase_03/running_regions/performance_exception.py",
    "tests/fixtures/phase_04/__init__.py",
    "tests/contract/test_p04_us01_opaque_group_custody.py",
    "tests/contract/test_p04_us01_operator_documentation.py",
    "tests/contract/test_p04_us01_p03_boundary.py",
    "tests/contract/test_p04_us01_table_api_schema.py",
    "tests/contract/test_p04_us01_table_contract.py",
    "tests/contract/test_p04_us01_table_semantics_runtime_contract.py",
    "tests/contract/test_p04_us01_terminal_alignment_contract.py",
    "tests/fixtures/phase_04/tables/__init__.py",
    "tests/fixtures/phase_04/tables/contract.py",
    "tests/fixtures/phase_04/tables/metrics.py",
    "tests/fixtures/phase_04/tables/oracle.py",
    "tests/fixtures/phase_04/tables/synthetic.py",
    "tests/performance/test_p03_us08_provisional_latency_exception.py",
    "tests/performance/test_p04_us01_table_metrics.py",
    "tests/regression/phase_04/test_p04_us01_all_corpus_drift.py",
    "tests/stories/phase_04/__init__.py",
    "tests/stories/phase_04/test_p04_us01_production_benchmarks.py",
    "tests/stories/phase_04/test_p04_us01_span_fidelity.py",
    "tests/stories/phase_04/test_p04_us01_table_input_recovery.py",
    "tests/stories/phase_04/test_p04_us01_table_repair_word_bounds.py",
    "tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md",
    "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json",
    "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-implementation-state-amendment.md",
    "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-hardened-renewal-implementation-state-amendment-approval.md",
    "tracker/phase-03-layout/decisions/P03-US08-phase04-tables-latency-exception-operative-administrative-renewal.md",
    "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-latency-waiver-operative-administrative-renewal.json",
    "tracker/phase-03-layout/evidence/P03-US08-phase04-tables-operative-administrative-renewal-independent-review.md",
    "tracker/phase-04-tables/evidence/P04-US01-external-rss-lane-final-code-amendment-independent-review.md",
    "tracker/phase-04-tables/evidence/P04-US01-conditional-stage-reachability-final-code-amendment-independent-review.md",
    "tracker/phase-04-tables/evidence/P04-US01-v13-compact-transport-monitor-controlled-supersession-independent-review.md",
    "tracker/phase-04-tables/decisions/P04-US01-source-bound-recovery-amendment.md",
    "tracker/phase-04-tables/decisions/P04-US01-valid-only-table-authority.md",
    "tracker/phase-04-tables/decisions/P04-table-evidence-policy.md",
)
_REQUIRED_FINAL_CODE_PATTERNS = (
    # A later US01 recovery/provenance module must become manifest-required
    # without relying on somebody remembering to update this harness.
    "app/services/*table*.py",
    "frontend/app/**/*table*.tsx",
    "frontend/lib/*table*.ts",
    "frontend/lib/*table*.tsx",
    "frontend/tests/p04-us01-*.test.mts",
    "tests/contract/test_p04_us01_*.py",
    "tests/fixtures/phase_04/tables/**/*",
    "tests/performance/test_p04_us01_*.py",
    "tests/regression/phase_04/test_p04_us01_*.py",
    "tests/stories/phase_04/test_p04_us01_*.py",
    # Decisions are execution inputs to the final story/renewal gates.  Keep
    # discovery recursive so a narrowly organized subdecision cannot escape
    # final-code identity custody.  Evidence/reports remain downstream and
    # deliberately have no matching final-code pattern.
    "tracker/phase-04-tables/decisions/**/*.md",
)
_DOWNSTREAM_EVIDENCE_PATTERNS = (
    "tracker/phase-04-tables/evidence/P04-US01*",
    "tracker/phase-04-tables/reports/P04-US01*",
)
TABLE_STAGE_COMPONENTS = (
    "budget_start",
    "repair_extraction",
    "docling_projection",
    "seal",
    "table_transaction_detach",
    "terminal_authority",
    "document_custody_transaction",
    "table_transaction_rebind",
    "finalize_replay",
    "budget_finish",
    "parse_result_custody",
)
TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS = (
    "repair_extraction",
    "docling_projection",
    "seal",
    "budget_finish",
    "parse_result_custody",
)
TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS = ("budget_start",)
TABLE_STAGE_ENABLED_ONLY_COMPONENTS = tuple(
    component
    for component in TABLE_STAGE_COMPONENTS
    if component not in TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
)
TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS = tuple(
    component
    for component in TABLE_STAGE_ENABLED_ONLY_COMPONENTS
    if component not in TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS
)
TABLE_STAGE_COMPONENT_FIELDS = ("elapsed_seconds", "call_count")
TABLE_STATUS_VALUES = frozenset(
    {"valid", "unresolved", "structural_failure"}
)
REVIEWED_OBSERVATION_FIELDS = (
    "denominator_id",
    "observed",
    "evidence_identity",
)
SNAPSHOT_FIELDS = (
    "case_id",
    "enabled",
    "source_identity",
    "wall_seconds",
    "table_stage_seconds",
    "table_stage_call_count",
    "table_stage_components",
    "peak_rss_bytes",
    "rss_source",
    "rss_normalization",
    "phase04_stage_current_rss_baseline_bytes",
    "phase04_stage_current_rss_peak_bytes",
    "phase04_stage_current_rss_end_bytes",
    "phase04_stage_current_rss_increment_bytes",
    "phase04_stage_hwm_baseline_bytes",
    "phase04_stage_hwm_end_bytes",
    "phase04_stage_hwm_increment_bytes",
    "phase04_stage_children_hwm_baseline_bytes",
    "phase04_stage_children_hwm_end_bytes",
    "phase04_stage_children_hwm_delta_bytes",
    "phase04_stage_children_hwm_source",
    "phase04_stage_children_rusage_baseline",
    "phase04_stage_children_rusage_end",
    "phase04_stage_children_rusage_unchanged",
    "phase04_stage_children_rusage_source",
    "phase04_stage_parse_checkpoint_monotonic_ns",
    "phase04_stage_parse_checkpoint_offset_ns",
    "phase04_stage_parse_current_rss_peak_bytes",
    "phase04_stage_parse_current_rss_end_bytes",
    "phase04_stage_parse_current_rss_increment_bytes",
    "phase04_stage_parse_hwm_end_bytes",
    "phase04_stage_parse_hwm_increment_bytes",
    "phase04_stage_parse_peak_rss_increment_bytes",
    "phase04_stage_api_peak_rss_increment_bytes",
    "phase04_stage_peak_rss_increment_bytes",
    "phase04_stage_current_rss_source",
    "phase04_stage_current_rss_source_version",
    "phase04_stage_hwm_source",
    "phase04_stage_rss_normalization",
    "phase04_stage_rss_sampling_scope",
    "phase04_stage_rss_child_scope",
    "phase04_stage_rss_first_boundary_component",
    "phase04_stage_rss_first_boundary_kind",
    "phase04_stage_rss_worker_pid",
    "phase04_stage_rss_process_create_time_ns",
    "phase04_stage_rss_platform",
    "phase04_stage_rss_started_monotonic_ns",
    "phase04_stage_rss_api_ended_monotonic_ns",
    "phase04_stage_rss_duration_ns",
    "phase04_stage_rss_first_async_offset_ns",
    "phase04_stage_rss_last_async_offset_ns",
    "phase04_stage_rss_sampling_target_interval_ns",
    "phase04_stage_rss_continuous_maximum_gap_ns",
    "phase04_stage_rss_sampling_hard_maximum_gap_ns",
    "phase04_stage_rss_sample_count",
    "phase04_stage_rss_continuous_sample_count",
    "phase04_stage_rss_synchronous_sample_count",
    "phase04_stage_rss_output_synchronous_boundary_count",
    "phase04_stage_rss_sampler_ready",
    "phase04_stage_rss_sampling_completed",
    "phase04_stage_rss_child_processes_observed",
    "phase04_stage_rss_sampler_error",
    "phase04_stage_child_observer_source",
    "phase04_stage_child_observer_source_version",
    "phase04_stage_child_observer_target_interval_ns",
    "phase04_stage_child_observer_hard_maximum_gap_ns",
    "phase04_stage_child_observer_first_offset_ns",
    "phase04_stage_child_observer_last_offset_ns",
    "phase04_stage_child_observer_continuous_maximum_gap_ns",
    "phase04_stage_child_observer_sample_count",
    "phase04_stage_child_boundary_check_count",
    "phase04_stage_child_observer_ready",
    "phase04_stage_child_observer_completed",
    "phase04_stage_child_observer_error",
    "phase04_stage_child_observer_residual",
    "phase04_stage_peak_rss_increment_formula_id",
    "phase04_stage_output_probe",
    "phase04_stage_no_spawn_policy",
    "semantic_json_sha256",
    "semantic_json_size_bytes",
    "marked_table_count",
    "maximum_marked_table_bytes",
    "document_sidecar_bytes",
    "table_status_counts",
    "quality",
    "external_rss_monitor_attestation",
    "worker_diagnostics",
    *HOSTED_USAGE,
)
PHASE04_STAGE_RSS_RECORD_FIELDS = SNAPSHOT_FIELDS[
    SNAPSHOT_FIELDS.index("phase04_stage_current_rss_baseline_bytes") :
    SNAPSHOT_FIELDS.index("phase04_stage_peak_rss_increment_formula_id") + 1
]
EXACT_REPRESENTATION_KEYS = (
    "rows",
    "value",
    "cells",
    "html",
    "markdown",
    "csv",
)
EXACT_SELECTION_ERRORS = (None, "missing_table", "ambiguous_table_selection")
EXACT_RESULT_FIELDS = frozenset(
    {
        "oracle_id",
        "case_id",
        "selection_error",
        "table_row_count_observed",
        "table_row_count_expected",
        "table_column_count_observed",
        "table_column_count_expected",
        "table_shape_matches",
        "cell_record_count_observed",
        "unique_cell_position_count_observed",
        "exact_cell_numerator",
        "exact_cell_denominator",
        "span_fidelity_numerator",
        "span_fidelity_denominator",
        "header_fidelity_numerator",
        "header_fidelity_denominator",
        "repeated_value_observed",
        "repeated_value_expected",
        "representation_results",
        "representation_numerator",
        "representation_denominator",
        "bbox_role_oracle",
        "source_content_bbox_numerator",
        "source_content_bbox_denominator",
        "structural_grid_containment_numerator",
        "structural_grid_containment_denominator",
        "exact_match_implied_teds",
        "exact_match_implied_grits",
        "passed",
    }
)
REVIEWED_DENOMINATOR_RESULT_FIELDS = frozenset(
    {
        "oracle_id",
        "case_id",
        "physical_page",
        "denominator_id",
        "dimension",
        "expected",
        "members",
        "observed",
        "observed_members",
        "observation_method",
        "review_evidence_identity",
        "selection_error",
        "accuracy_denominator_inclusion",
        "passed",
    }
)
UNRESOLVED_EXCLUSION_RESULT_FIELDS = frozenset(
    {
        "oracle_id",
        "case_id",
        "physical_page",
        "dimension",
        "required_concern",
        "observed_concern_codes",
        "concern_observed",
        "accuracy_denominator_inclusion",
        "reason",
    }
)
QUALITY_SUMMARY_FIELDS = frozenset(
    {
        "oracle",
        "exact_tables",
        "reviewed_denominators",
        "unresolved_exclusions",
        "exact_cell_numerator",
        "exact_cell_denominator",
        "exact_cell_accuracy",
        "representation_numerator",
        "representation_denominator",
        "representation_accuracy",
        "exact_match_implied_teds",
        "exact_match_implied_grits",
        "reviewed_dimension_numerator",
        "reviewed_dimension_denominator",
        "required_concern_numerator",
        "required_concern_denominator",
        "all_required_concerns_observed",
        "pending_independent_review_denominator_ids",
        "all_exact_and_reviewed_dimensions_passed",
    }
)


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


def _canonical_relative_path(value: Any, *, label: str) -> str:
    encoded = value.encode("utf-8") if type(value) is str else b""
    if (
        type(value) is not str
        or not value
        or len(encoded) > 256
        or any(byte < 0x20 or byte > 0x7E for byte in encoded)
        or re.fullmatch(r"[A-Za-z0-9._/-]+", value) is None
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or Path(value).as_posix() != value
        or len(Path(value).parts) > MAXIMUM_RELATIVE_PATH_DEPTH
    ):
        raise ValueError(f"{label} must be canonical, bounded, and relative")
    return value


def _canonical_relative_pattern(value: Any, *, label: str) -> str:
    encoded = value.encode("utf-8") if type(value) is str else b""
    if (
        type(value) is not str
        or not value
        or len(encoded) > 256
        or any(byte < 0x20 or byte > 0x7E for byte in encoded)
        or re.fullmatch(r"[A-Za-z0-9._/*?-]+", value) is None
        or Path(value).is_absolute()
        or ".." in Path(value).parts
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or Path(value).as_posix() != value
        or len(Path(value).parts) > MAXIMUM_RELATIVE_PATH_DEPTH
    ):
        raise ValueError(f"{label} must be canonical, bounded, and relative")
    return value


def _stat_binding(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _trusted_workspace_root(workspace: Path, *, label: str) -> Path:
    """Resolve one caller-supplied directory without accepting a root link."""

    supplied = Path(workspace)
    try:
        initial = supplied.lstat()
    except OSError as error:
        raise ValueError(f"{label} repository root differs") from error
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISDIR(initial.st_mode):
        raise ValueError(f"{label} repository root differs")
    try:
        root = supplied.resolve(strict=True)
        final = supplied.lstat()
    except OSError as error:
        raise ValueError(f"{label} repository root differs") from error
    if _stat_binding(initial) != _stat_binding(final):
        raise ValueError(f"{label} repository root changed before use")
    return root


def _read_bounded_regular_file(
    workspace: Path,
    relative_path: str,
    *,
    maximum_bytes: int,
    label: str,
) -> bytes:
    """Read one repository file without following links or accepting drift."""

    relative_path = _canonical_relative_path(relative_path, label=label)
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise ValueError(f"{label} byte bound differs")
    root = _trusted_workspace_root(workspace, label=label)
    root_path_binding = _stat_binding(root.lstat())
    if not stat.S_ISDIR(root_path_binding[2]) or stat.S_ISLNK(root_path_binding[2]):
        raise ValueError(f"{label} repository root differs")
    parts = Path(relative_path).parts
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    leaf_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors: list[int] = []
    try:
        current_descriptor = os.open(root, directory_flags)
    except OSError as error:
        raise ValueError(f"{label} repository root differs") from error
    descriptors.append(current_descriptor)
    root_binding = _stat_binding(os.fstat(current_descriptor))
    if root_binding != root_path_binding:
        os.close(current_descriptor)
        raise ValueError(f"{label} repository root changed before reading")
    try:
        directory_bindings: list[tuple[int, str, tuple[int, ...]]] = []
        for part in parts[:-1]:
            try:
                before = _stat_binding(
                    os.stat(part, dir_fd=current_descriptor, follow_symlinks=False)
                )
                next_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=current_descriptor,
                )
            except OSError as error:
                raise ValueError(
                    f"{label} cannot traverse a repository component"
                ) from error
            opened_directory = _stat_binding(os.fstat(next_descriptor))
            if before != opened_directory or not stat.S_ISDIR(before[2]):
                os.close(next_descriptor)
                raise ValueError(f"{label} directory changed before reading")
            directory_bindings.append((current_descriptor, part, before))
            descriptors.append(next_descriptor)
            current_descriptor = next_descriptor
        leaf = parts[-1]
        try:
            initial = _stat_binding(
                os.stat(leaf, dir_fd=current_descriptor, follow_symlinks=False)
            )
            descriptor = os.open(leaf, leaf_flags, dir_fd=current_descriptor)
        except OSError as error:
            raise ValueError(
                f"{label} cannot be opened without following links"
            ) from error
        descriptors.append(descriptor)
        opened = _stat_binding(os.fstat(descriptor))
        if opened != initial:
            raise ValueError(f"{label} changed before reading")
        if not stat.S_ISREG(opened[2]) or opened[6] > maximum_bytes:
            raise ValueError(f"{label} is not a stable bounded regular file")
        chunks: list[bytes] = []
        observed_bytes = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1))
            if not chunk:
                break
            observed_bytes += len(chunk)
            if observed_bytes > maximum_bytes:
                raise ValueError(f"{label} exceeds its byte bound")
            chunks.append(chunk)
        final_opened = _stat_binding(os.fstat(descriptor))
        if final_opened != opened or observed_bytes != opened[6]:
            raise ValueError(f"{label} changed while reading")
        final_leaf = _stat_binding(
            os.stat(leaf, dir_fd=current_descriptor, follow_symlinks=False)
        )
        if final_leaf != initial:
            raise ValueError(f"{label} changed after reading")
        for parent_descriptor, part, before in directory_bindings:
            after = _stat_binding(
                os.stat(part, dir_fd=parent_descriptor, follow_symlinks=False)
            )
            if after != before:
                raise ValueError(f"{label} directory changed after reading")
        if _stat_binding(os.fstat(descriptors[0])) != root_binding:
            raise ValueError(f"{label} repository root changed while reading")
        if _stat_binding(root.lstat()) != root_path_binding:
            raise ValueError(f"{label} repository root changed after reading")
    finally:
        for open_descriptor in reversed(descriptors):
            try:
                os.close(open_descriptor)
            except OSError:
                pass
    return b"".join(chunks)


def _validate_json_tree(value: Any, *, label: str) -> None:
    stack: list[tuple[Any, int, bool]] = [(value, 0, False)]
    active_containers: set[int] = set()
    nodes = 0
    string_bytes = 0
    while stack:
        current, depth, exiting = stack.pop()
        if exiting:
            active_containers.remove(id(current))
            continue
        nodes += 1
        if nodes > MAXIMUM_JSON_NODES or depth > MAXIMUM_JSON_DEPTH:
            raise ValueError(f"{label} exceeds its JSON structure bound")
        if type(current) is dict:
            identity = id(current)
            if identity in active_containers:
                raise ValueError(f"{label} contains a cyclic container")
            active_containers.add(identity)
            stack.append((current, depth, True))
            for key, member in current.items():
                if type(key) is not str:
                    raise ValueError(f"{label} has a non-text JSON key")
                string_bytes += len(key.encode("utf-8"))
                stack.append((member, depth + 1, False))
        elif type(current) is list:
            identity = id(current)
            if identity in active_containers:
                raise ValueError(f"{label} contains a cyclic container")
            active_containers.add(identity)
            stack.append((current, depth, True))
            stack.extend((member, depth + 1, False) for member in current)
        elif type(current) is str:
            string_bytes += len(current.encode("utf-8"))
        elif current is None or type(current) in {bool, int}:
            pass
        elif type(current) is float and math.isfinite(current):
            pass
        else:
            raise ValueError(f"{label} contains a noncanonical JSON value")
        if string_bytes > MAXIMUM_JSON_STRING_BYTES:
            raise ValueError(f"{label} exceeds its JSON text bound")


def _load_strict_bounded_json(raw: bytes, *, label: str) -> dict[str, Any]:
    if len(raw) > MAXIMUM_RETAINED_METRICS_BYTES:
        raise ValueError(f"{label} exceeds its byte bound")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, member in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate JSON keys")
            result[key] = member
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=object_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"{label} is not strict JSON") from error
    if type(value) is not dict:
        raise ValueError(f"{label} root differs")
    _validate_json_tree(value, label=label)
    return value


def file_identity(workspace: Path, relative_path: str) -> dict[str, Any]:
    """Return one exact, portable workspace-file identity."""

    relative_path = _canonical_relative_path(
        relative_path,
        label="final-code identity path",
    )
    raw = _read_bounded_regular_file(
        workspace,
        relative_path,
        maximum_bytes=MAXIMUM_IDENTITY_FILE_BYTES,
        label="final-code identity",
    )
    return {
        "path": relative_path,
        "size_bytes": len(raw),
        "sha256": _sha256_bytes(raw),
    }


def _discover_regular_path(
    root: Path,
    candidate: Path,
    *,
    label: str,
) -> tuple[str, int]:
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"{label} escapes the workspace") from error
    relative = _canonical_relative_path(relative, label=label)
    current = root
    observed: os.stat_result | None = None
    for part in Path(relative).parts:
        current /= part
        try:
            observed = current.lstat()
        except OSError as error:
            raise ValueError(f"{label} is absent or unreadable") from error
        if stat.S_ISLNK(observed.st_mode):
            raise ValueError(f"{label} cannot traverse a symbolic link")
    if observed is None or not stat.S_ISREG(observed.st_mode):
        raise ValueError(f"{label} must name a regular file")
    if observed.st_size > MAXIMUM_IDENTITY_FILE_BYTES:
        raise ValueError(f"{label} exceeds its per-file byte bound")
    raw = _read_bounded_regular_file(
        root,
        relative,
        maximum_bytes=MAXIMUM_IDENTITY_FILE_BYTES,
        label=label,
    )
    return relative, len(raw)


def required_final_code_paths(
    workspace: Path = WORKSPACE,
    *,
    explicit_paths: Sequence[str] = _REQUIRED_FINAL_CODE_EXPLICIT_PATHS,
    patterns: Sequence[str] = _REQUIRED_FINAL_CODE_PATTERNS,
) -> tuple[str, ...]:
    """Discover the closed current US01 executable and policy surface.

    Explicit cross-cutting parser and frontend files stay reviewable here,
    while narrowly scoped patterns make any later US01 table-recovery module,
    fixture, or gate test automatically mandatory for final-code custody.
    Generated US01 evidence and completion reports are intentionally excluded:
    they are sealed in a separate, downstream manifest so that a retained
    metrics artifact never depends on a report which in turn cites that
    metrics artifact.
    """

    root = _trusted_workspace_root(
        workspace,
        label="required final-code discovery",
    )
    required: set[str] = set()
    total_bytes = 0
    traversed_matches = 0

    def add(candidate: Path, *, label: str) -> None:
        nonlocal total_bytes
        relative_path, size_bytes = _discover_regular_path(
            root,
            candidate,
            label=label,
        )
        if relative_path in required:
            return
        if len(required) >= MAXIMUM_DISCOVERED_PATHS:
            raise ValueError("required final-code path count exceeds its bound")
        total_bytes += size_bytes
        if total_bytes > MAXIMUM_DISCOVERED_TOTAL_BYTES:
            raise ValueError("required final-code bytes exceed their bound")
        required.add(relative_path)

    for relative_path in explicit_paths:
        relative_path = _canonical_relative_path(
            relative_path,
            label="required final-code path",
        )
        try:
            (root / relative_path).lstat()
        except OSError as error:
            raise ValueError(
                f"required final-code path is absent: {relative_path}"
            ) from error
        add(root / relative_path, label="required final-code path")
    for pattern in patterns:
        pattern = _canonical_relative_pattern(
            pattern,
            label="required final-code pattern",
        )
        for candidate in root.glob(pattern):
            traversed_matches += 1
            if traversed_matches > MAXIMUM_DISCOVERED_PATHS:
                raise ValueError(
                    "required final-code pattern traversal exceeds its bound"
                )
            if "__pycache__" in candidate.parts:
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                raise ValueError("required final-code pattern changed") from error
            if stat.S_ISDIR(mode):
                continue
            add(candidate, label="required final-code pattern result")
    if not required:
        raise ValueError("required final-code path discovery is empty")
    return tuple(sorted(required))


REQUIRED_FINAL_CODE_PATHS = required_final_code_paths()


def required_downstream_evidence_paths(
    workspace: Path = WORKSPACE,
    *,
    patterns: Sequence[str] = _DOWNSTREAM_EVIDENCE_PATTERNS,
    manifest_path: str = DOWNSTREAM_EVIDENCE_MANIFEST_PATH,
    upstream_approval_paths: Sequence[str] = UPSTREAM_APPROVAL_EVIDENCE_PATHS,
) -> tuple[str, ...]:
    """Discover generated US01 evidence without ever selecting this manifest.

    The returned paths are deliberately downstream of final-code custody.
    Exact independent approvals that authorize a run are upstream final-code
    inputs and are excluded explicitly. ``manifest_path`` may exist in the
    workspace; it is also excluded so the aggregate identity cannot become a
    self-hash.
    """

    validate_file_identity_path(manifest_path, field_name="manifest path")
    upstream_approvals = {
        validate_file_identity_path(path, field_name="upstream approval path")
        for path in upstream_approval_paths
    }
    root = _trusted_workspace_root(
        workspace,
        label="downstream-evidence discovery",
    )
    required: set[str] = set()
    total_bytes = 0
    traversed_matches = 0
    for pattern in patterns:
        pattern = _canonical_relative_pattern(
            pattern,
            label="required downstream-evidence pattern",
        )
        for candidate in root.glob(pattern):
            traversed_matches += 1
            if traversed_matches > MAXIMUM_DISCOVERED_PATHS:
                raise ValueError(
                    "required downstream-evidence traversal exceeds its bound"
                )
            if "__pycache__" in candidate.parts:
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as error:
                raise ValueError("downstream-evidence path changed") from error
            if stat.S_ISDIR(mode):
                continue
            relative_path, size_bytes = _discover_regular_path(
                root,
                candidate,
                label="downstream-evidence path",
            )
            if (
                relative_path != manifest_path
                and relative_path not in upstream_approvals
            ):
                if relative_path not in required:
                    total_bytes += size_bytes
                if (
                    len(required) >= MAXIMUM_DISCOVERED_PATHS
                    or total_bytes > MAXIMUM_DISCOVERED_TOTAL_BYTES
                ):
                    raise ValueError(
                        "downstream-evidence discovery exceeds its bound"
                    )
                required.add(relative_path)
    return tuple(sorted(required))


def validate_file_identity_path(
    value: Any,
    *,
    field_name: str = "file identity path",
) -> str:
    """Return one canonical relative path used by custody manifests."""

    return _canonical_relative_path(value, label=field_name)


def validate_file_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(FINAL_CODE_IDENTITY_FIELDS):
        raise ValueError("file identity has unexpected fields")
    path = value.get("path")
    size = value.get("size_bytes")
    digest = value.get("sha256")
    path = _canonical_relative_path(path, label="file identity path")
    if (
        type(size) is not int
        or size <= 0
        or size > MAXIMUM_IDENTITY_FILE_BYTES
    ):
        raise ValueError("file identity size must be a positive integer")
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("file identity requires lowercase SHA-256")
    return {field: value[field] for field in FINAL_CODE_IDENTITY_FIELDS}


def build_downstream_evidence_manifest(
    workspace: Path = WORKSPACE,
    *,
    evidence_identities: Sequence[Mapping[str, Any]] | None = None,
    patterns: Sequence[str] = _DOWNSTREAM_EVIDENCE_PATTERNS,
    manifest_path: str = DOWNSTREAM_EVIDENCE_MANIFEST_PATH,
) -> dict[str, Any]:
    """Bind generated US01 evidence after final-code metrics are sealed.

    The manifest path is a declared destination, never one of its inputs.  An
    explicit identity sequence is accepted for retained-artifact validation;
    omission, insertion, byte drift, duplicate paths, and self-inclusion all
    fail closed.
    """

    manifest_path = validate_file_identity_path(
        manifest_path,
        field_name="manifest path",
    )
    required_paths = required_downstream_evidence_paths(
        workspace,
        patterns=patterns,
        manifest_path=manifest_path,
    )
    if not required_paths:
        raise ValueError("downstream-evidence path discovery is empty")
    if evidence_identities is None:
        identities = [file_identity(workspace, path) for path in required_paths]
    else:
        identities = [
            validate_file_identity(value) for value in evidence_identities
        ]
    identity_paths = [record["path"] for record in identities]
    if len(set(identity_paths)) != len(identity_paths):
        raise ValueError("downstream-evidence identity paths must be unique")
    if manifest_path in identity_paths:
        raise ValueError("downstream-evidence manifest cannot include itself")
    if set(identity_paths) != set(required_paths):
        raise ValueError(
            "downstream-evidence identity manifest differs from required US01 paths"
        )
    for identity in identities:
        if file_identity(workspace, identity["path"]) != identity:
            raise ValueError(
                "downstream-evidence identity differs from current workspace bytes"
            )
    identities.sort(key=lambda record: record["path"])
    aggregate_sha256 = _sha256_bytes(_canonical_bytes(identities))
    return {
        "schema_id": DOWNSTREAM_EVIDENCE_MANIFEST_SCHEMA_ID,
        "story_id": STORY_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_path": manifest_path,
        "self_identity_included": False,
        "required_evidence_paths": list(required_paths),
        "evidence_identities": identities,
        "evidence_identity_aggregate_sha256": aggregate_sha256,
    }


def validate_downstream_evidence_manifest(
    value: Mapping[str, Any],
    workspace: Path = WORKSPACE,
    *,
    patterns: Sequence[str] = _DOWNSTREAM_EVIDENCE_PATTERNS,
) -> dict[str, Any]:
    """Validate one retained downstream manifest against current exact bytes."""

    expected_fields = {
        "schema_id",
        "story_id",
        "generated_at",
        "manifest_path",
        "self_identity_included",
        "required_evidence_paths",
        "evidence_identities",
        "evidence_identity_aggregate_sha256",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError("downstream-evidence manifest fields differ")
    if value.get("schema_id") != DOWNSTREAM_EVIDENCE_MANIFEST_SCHEMA_ID:
        raise ValueError("downstream-evidence manifest schema differs")
    if value.get("story_id") != STORY_ID:
        raise ValueError("downstream-evidence manifest story differs")
    generated_at = value.get("generated_at")
    if type(generated_at) is not str:
        raise ValueError("downstream-evidence manifest timestamp differs")
    try:
        parsed_at = datetime.fromisoformat(generated_at)
    except ValueError as error:
        raise ValueError(
            "downstream-evidence manifest timestamp differs"
        ) from error
    if parsed_at.tzinfo is None:
        raise ValueError("downstream-evidence manifest timestamp differs")
    if value.get("self_identity_included") is not False:
        raise ValueError("downstream-evidence manifest cannot include itself")
    manifest_path = validate_file_identity_path(
        value.get("manifest_path"),
        field_name="manifest path",
    )
    identities = value.get("evidence_identities")
    if type(identities) is not list:
        raise ValueError("downstream-evidence identities differ")
    rebuilt = build_downstream_evidence_manifest(
        workspace,
        evidence_identities=identities,
        patterns=patterns,
        manifest_path=manifest_path,
    )
    for field in (
        "manifest_path",
        "self_identity_included",
        "required_evidence_paths",
        "evidence_identities",
        "evidence_identity_aggregate_sha256",
    ):
        if value.get(field) != rebuilt[field]:
            raise ValueError(f"downstream-evidence manifest {field} differs")
    return dict(value)


def _source_identity(case_id: str) -> dict[str, Any]:
    source = next(
        (item for item in P04_US01_REAL_ORACLE.sources if item.case_id == case_id),
        None,
    )
    if source is None:
        raise KeyError(f"unknown P04-US01 source: {case_id}")
    return {
        "case_id": source.case_id,
        "path": source.path,
        "size_bytes": source.size_bytes,
        "sha256": source.sha256,
        "page_count": source.page_count,
    }


def _verified_source_bytes(workspace: Path, case_id: str) -> bytes:
    identity = _source_identity(case_id)
    source = _read_bounded_regular_file(
        workspace,
        identity["path"],
        maximum_bytes=identity["size_bytes"],
        label=f"P04-US01 source {case_id}",
    )
    if len(source) != identity["size_bytes"]:
        raise ValueError(f"P04-US01 source size drifted: {case_id}")
    if _sha256_bytes(source) != identity["sha256"]:
        raise ValueError(f"P04-US01 source SHA-256 drifted: {case_id}")
    return source


def inclusive_nearest_rank(values: Sequence[float], quantile: float) -> float:
    """Return the empirical inclusive nearest-rank quantile."""

    if not values:
        raise ValueError("quantile requires at least one sample")
    if not 0.0 < quantile <= 1.0:
        raise ValueError("quantile must be in (0, 1]")
    numbers = [float(value) for value in values]
    if any(not math.isfinite(value) for value in numbers):
        raise ValueError("quantile samples must be finite")
    ordered = sorted(numbers)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def paired_states(pair_index: int) -> tuple[bool, bool]:
    """Alternate order without changing the off/on pairing."""

    if type(pair_index) is not int or pair_index < 0:
        raise ValueError("pair index must be a nonnegative integer")
    return (False, True) if pair_index % 2 == 0 else (True, False)


def rss_bytes_from_maxrss(value: int, *, platform_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("ru_maxrss must be a nonnegative integer")
    return value if platform_name == "darwin" else value * 1024


def _rss_bytes() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss_bytes_from_maxrss(int(maximum), platform_name=sys.platform)


def _children_rusage_fingerprint(
    usage: Any | None = None,
    *,
    platform_name: str | None = None,
) -> dict[str, Any]:
    if usage is None:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    platform_value = platform_name or sys.platform
    times: dict[str, str] = {}
    for field in ("ru_utime", "ru_stime"):
        raw = getattr(usage, field, None)
        if (
            type(raw) not in (int, float)
            or type(raw) is bool
            or not math.isfinite(float(raw))
            or raw < 0
        ):
            raise RuntimeError("Phase04-stage child rusage time differs")
        times[f"{field}_seconds_hex"] = float(raw).hex()
    raw_maxrss = getattr(usage, "ru_maxrss", None)
    if type(raw_maxrss) is not int or raw_maxrss < 0:
        raise RuntimeError("Phase04-stage child rusage maxrss differs")
    counters: dict[str, int] = {}
    for field in PHASE04_STAGE_CHILDREN_RUSAGE_COUNTER_FIELDS:
        raw = getattr(usage, field, None)
        if type(raw) is not int or raw < 0:
            raise RuntimeError("Phase04-stage child rusage counter differs")
        counters[field] = raw
    return {
        "schema_id": PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID,
        **times,
        "ru_maxrss_bytes": rss_bytes_from_maxrss(
            raw_maxrss,
            platform_name=platform_value,
        ),
        **counters,
    }


def _validate_children_rusage_fingerprint(value: Any) -> dict[str, Any]:
    expected_fields = {
        "schema_id",
        "ru_utime_seconds_hex",
        "ru_stime_seconds_hex",
        "ru_maxrss_bytes",
        *PHASE04_STAGE_CHILDREN_RUSAGE_COUNTER_FIELDS,
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError("Phase04-stage child rusage fields differ")
    if value["schema_id"] != PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID:
        raise ValueError("Phase04-stage child rusage schema differs")
    for field in ("ru_utime_seconds_hex", "ru_stime_seconds_hex"):
        encoded = value[field]
        try:
            decoded = float.fromhex(encoded) if type(encoded) is str else -1.0
        except ValueError as error:
            raise ValueError("Phase04-stage child rusage time differs") from error
        if (
            not math.isfinite(decoded)
            or decoded < 0
            or decoded.hex() != encoded
        ):
            raise ValueError("Phase04-stage child rusage time differs")
    for field in ("ru_maxrss_bytes", *PHASE04_STAGE_CHILDREN_RUSAGE_COUNTER_FIELDS):
        if type(value[field]) is not int or value[field] < 0:
            raise ValueError("Phase04-stage child rusage counter differs")
    return deepcopy(value)


def _current_rss_source_version() -> str:
    import psutil

    version = getattr(psutil, "__version__", None)
    if version != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION:
        raise RuntimeError("Phase04-stage current RSS source version differs")
    return version


def _phase04_stage_rss_record(
    *,
    current_baseline_bytes: Any,
    current_peak_bytes: Any,
    current_end_bytes: Any,
    hwm_baseline_bytes: Any,
    hwm_end_bytes: Any,
    children_rusage_baseline: Any,
    children_rusage_end: Any,
    current_rss_source_version: Any,
    first_boundary_component: Any,
    worker_pid: Any,
    process_create_time_ns: Any,
    platform_name: Any,
    started_monotonic_ns: Any,
    parse_checkpoint_monotonic_ns: Any,
    parse_current_peak_bytes: Any,
    parse_current_end_bytes: Any,
    parse_hwm_end_bytes: Any,
    ended_monotonic_ns: Any,
    sampling_maximum_gap_ns: Any,
    sample_count: Any,
    continuous_sample_count: Any,
    synchronous_sample_count: Any,
    output_synchronous_boundary_count: Any,
    first_async_offset_ns: Any,
    last_async_offset_ns: Any,
    child_observer_maximum_gap_ns: Any,
    child_observer_sample_count: Any,
    child_boundary_check_count: Any,
    child_observer_first_offset_ns: Any,
    child_observer_last_offset_ns: Any,
) -> dict[str, Any]:
    """Build the strict self-normalized Phase04-stage RSS measurement."""

    byte_values = (
        current_baseline_bytes,
        current_peak_bytes,
        current_end_bytes,
        hwm_baseline_bytes,
        hwm_end_bytes,
        parse_current_peak_bytes,
        parse_current_end_bytes,
        parse_hwm_end_bytes,
    )
    if any(type(value) is not int or value < 0 for value in byte_values):
        raise ValueError("Phase04-stage RSS values must be nonnegative integers")
    if current_peak_bytes < max(current_baseline_bytes, current_end_bytes):
        raise ValueError("Phase04-stage current RSS peak is incoherent")
    if hwm_end_bytes < hwm_baseline_bytes:
        raise ValueError("Phase04-stage HWM end precedes its baseline")
    validated_children_baseline = _validate_children_rusage_fingerprint(
        children_rusage_baseline
    )
    validated_children_end = _validate_children_rusage_fingerprint(
        children_rusage_end
    )
    if validated_children_end != validated_children_baseline:
        raise ValueError("Phase04-stage child rusage fingerprint changed")
    children_hwm_baseline_bytes = validated_children_baseline[
        "ru_maxrss_bytes"
    ]
    children_hwm_end_bytes = validated_children_end["ru_maxrss_bytes"]
    if (
        parse_current_peak_bytes
        < max(current_baseline_bytes, parse_current_end_bytes)
        or parse_current_peak_bytes > current_peak_bytes
        or parse_hwm_end_bytes < hwm_baseline_bytes
        or parse_hwm_end_bytes > hwm_end_bytes
    ):
        raise ValueError("Phase04-stage parse RSS checkpoint is incoherent")
    if current_rss_source_version != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION:
        raise ValueError("Phase04-stage current RSS source version differs")
    if first_boundary_component not in TABLE_STAGE_COMPONENTS:
        raise ValueError("Phase04-stage first RSS boundary differs")
    if type(worker_pid) is not int or worker_pid < 1:
        raise ValueError("Phase04-stage worker PID differs")
    if type(process_create_time_ns) is not int or process_create_time_ns < 1:
        raise ValueError("Phase04-stage process-create identity differs")
    if platform_name not in {"darwin", "linux"}:
        raise ValueError("Phase04-stage RSS platform differs")
    timeline_values = (
        started_monotonic_ns,
        parse_checkpoint_monotonic_ns,
        ended_monotonic_ns,
        sampling_maximum_gap_ns,
        first_async_offset_ns,
        last_async_offset_ns,
        child_observer_maximum_gap_ns,
        child_observer_first_offset_ns,
        child_observer_last_offset_ns,
    )
    if any(type(value) is not int or value < 0 for value in timeline_values):
        raise ValueError("Phase04-stage RSS timeline differs")
    if ended_monotonic_ns <= started_monotonic_ns:
        raise ValueError("Phase04-stage RSS window is incoherent")
    if not started_monotonic_ns < parse_checkpoint_monotonic_ns < ended_monotonic_ns:
        raise ValueError("Phase04-stage parse checkpoint order differs")
    duration_ns = ended_monotonic_ns - started_monotonic_ns
    parse_checkpoint_offset_ns = (
        parse_checkpoint_monotonic_ns - started_monotonic_ns
    )
    if (
        sampling_maximum_gap_ns > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        or sampling_maximum_gap_ns > duration_ns
        or first_async_offset_ns > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        or first_async_offset_ns > last_async_offset_ns
        or last_async_offset_ns > duration_ns
        or duration_ns - last_async_offset_ns
        > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        or first_async_offset_ns > sampling_maximum_gap_ns
        or duration_ns - last_async_offset_ns > sampling_maximum_gap_ns
    ):
        raise ValueError("Phase04-stage RSS sampling cadence differs")
    if (
        child_observer_maximum_gap_ns
        > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        or child_observer_maximum_gap_ns > duration_ns
        or child_observer_first_offset_ns
        > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        or child_observer_first_offset_ns > child_observer_last_offset_ns
        or child_observer_last_offset_ns > duration_ns
        or duration_ns - child_observer_last_offset_ns
        > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        or child_observer_first_offset_ns > child_observer_maximum_gap_ns
        or duration_ns - child_observer_last_offset_ns
        > child_observer_maximum_gap_ns
    ):
        raise ValueError("Phase04-stage child-observer cadence differs")
    count_values = (
        sample_count,
        continuous_sample_count,
        synchronous_sample_count,
        output_synchronous_boundary_count,
        child_observer_sample_count,
        child_boundary_check_count,
    )
    if any(type(value) is not int or value < 1 for value in count_values):
        raise ValueError("Phase04-stage RSS sample counts differ")
    if (
        sample_count != continuous_sample_count + synchronous_sample_count
        or synchronous_sample_count < 3
        or child_observer_sample_count < 1
        or child_boundary_check_count != synchronous_sample_count
        or duration_ns
        > (continuous_sample_count + 1)
        * PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        or duration_ns
        > (child_observer_sample_count + 1)
        * PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
    ):
        raise ValueError("Phase04-stage RSS sample accounting differs")
    current_increment_bytes = max(
        0,
        current_peak_bytes - current_baseline_bytes,
    )
    hwm_increment_bytes = max(0, hwm_end_bytes - hwm_baseline_bytes)
    parse_current_increment_bytes = max(
        0,
        parse_current_peak_bytes - current_baseline_bytes,
    )
    parse_hwm_increment_bytes = max(
        0,
        parse_hwm_end_bytes - hwm_baseline_bytes,
    )
    parse_peak_increment_bytes = max(
        parse_current_increment_bytes,
        parse_hwm_increment_bytes,
    )
    api_peak_increment_bytes = max(
        current_increment_bytes,
        hwm_increment_bytes,
    )
    return {
        "phase04_stage_current_rss_baseline_bytes": current_baseline_bytes,
        "phase04_stage_current_rss_peak_bytes": current_peak_bytes,
        "phase04_stage_current_rss_end_bytes": current_end_bytes,
        "phase04_stage_current_rss_increment_bytes": current_increment_bytes,
        "phase04_stage_hwm_baseline_bytes": hwm_baseline_bytes,
        "phase04_stage_hwm_end_bytes": hwm_end_bytes,
        "phase04_stage_hwm_increment_bytes": hwm_increment_bytes,
        "phase04_stage_children_hwm_baseline_bytes": (
            children_hwm_baseline_bytes
        ),
        "phase04_stage_children_hwm_end_bytes": children_hwm_end_bytes,
        "phase04_stage_children_hwm_delta_bytes": (
            children_hwm_end_bytes - children_hwm_baseline_bytes
        ),
        "phase04_stage_children_hwm_source": (
            PHASE04_STAGE_CHILDREN_HWM_SOURCE
        ),
        "phase04_stage_children_rusage_baseline": (
            validated_children_baseline
        ),
        "phase04_stage_children_rusage_end": validated_children_end,
        "phase04_stage_children_rusage_unchanged": True,
        "phase04_stage_children_rusage_source": (
            PHASE04_STAGE_CHILDREN_RUSAGE_SOURCE
        ),
        "phase04_stage_parse_checkpoint_monotonic_ns": (
            parse_checkpoint_monotonic_ns
        ),
        "phase04_stage_parse_checkpoint_offset_ns": parse_checkpoint_offset_ns,
        "phase04_stage_parse_current_rss_peak_bytes": parse_current_peak_bytes,
        "phase04_stage_parse_current_rss_end_bytes": parse_current_end_bytes,
        "phase04_stage_parse_current_rss_increment_bytes": (
            parse_current_increment_bytes
        ),
        "phase04_stage_parse_hwm_end_bytes": parse_hwm_end_bytes,
        "phase04_stage_parse_hwm_increment_bytes": parse_hwm_increment_bytes,
        "phase04_stage_parse_peak_rss_increment_bytes": (
            parse_peak_increment_bytes
        ),
        "phase04_stage_api_peak_rss_increment_bytes": api_peak_increment_bytes,
        "phase04_stage_peak_rss_increment_bytes": max(
            parse_peak_increment_bytes,
            api_peak_increment_bytes,
        ),
        "phase04_stage_current_rss_source": PHASE04_STAGE_CURRENT_RSS_SOURCE,
        "phase04_stage_current_rss_source_version": (
            current_rss_source_version
        ),
        "phase04_stage_hwm_source": PHASE04_STAGE_RSS_SOURCE,
        "phase04_stage_rss_normalization": PHASE04_STAGE_RSS_NORMALIZATION,
        "phase04_stage_rss_sampling_scope": PHASE04_STAGE_RSS_SAMPLING_SCOPE,
        "phase04_stage_rss_child_scope": PHASE04_STAGE_RSS_CHILD_SCOPE,
        "phase04_stage_rss_first_boundary_component": (
            first_boundary_component
        ),
        "phase04_stage_rss_first_boundary_kind": "outermost_hook_pre_entry",
        "phase04_stage_rss_worker_pid": worker_pid,
        "phase04_stage_rss_process_create_time_ns": process_create_time_ns,
        "phase04_stage_rss_platform": platform_name,
        "phase04_stage_rss_started_monotonic_ns": started_monotonic_ns,
        "phase04_stage_rss_api_ended_monotonic_ns": ended_monotonic_ns,
        "phase04_stage_rss_duration_ns": duration_ns,
        "phase04_stage_rss_first_async_offset_ns": first_async_offset_ns,
        "phase04_stage_rss_last_async_offset_ns": last_async_offset_ns,
        "phase04_stage_rss_sampling_target_interval_ns": (
            PHASE04_STAGE_RSS_TARGET_INTERVAL_NS
        ),
        "phase04_stage_rss_continuous_maximum_gap_ns": (
            sampling_maximum_gap_ns
        ),
        "phase04_stage_rss_sampling_hard_maximum_gap_ns": (
            PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        ),
        "phase04_stage_rss_sample_count": sample_count,
        "phase04_stage_rss_continuous_sample_count": continuous_sample_count,
        "phase04_stage_rss_synchronous_sample_count": synchronous_sample_count,
        "phase04_stage_rss_output_synchronous_boundary_count": (
            output_synchronous_boundary_count
        ),
        "phase04_stage_rss_sampler_ready": True,
        "phase04_stage_rss_sampling_completed": True,
        "phase04_stage_rss_child_processes_observed": 0,
        "phase04_stage_rss_sampler_error": None,
        "phase04_stage_child_observer_source": (
            PHASE04_STAGE_CHILD_OBSERVER_SOURCE
        ),
        "phase04_stage_child_observer_source_version": (
            PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION
        ),
        "phase04_stage_child_observer_target_interval_ns": (
            PHASE04_STAGE_CHILD_OBSERVER_TARGET_INTERVAL_NS
        ),
        "phase04_stage_child_observer_hard_maximum_gap_ns": (
            PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        ),
        "phase04_stage_child_observer_first_offset_ns": (
            child_observer_first_offset_ns
        ),
        "phase04_stage_child_observer_last_offset_ns": (
            child_observer_last_offset_ns
        ),
        "phase04_stage_child_observer_continuous_maximum_gap_ns": (
            child_observer_maximum_gap_ns
        ),
        "phase04_stage_child_observer_sample_count": (
            child_observer_sample_count
        ),
        "phase04_stage_child_boundary_check_count": child_boundary_check_count,
        "phase04_stage_child_observer_ready": True,
        "phase04_stage_child_observer_completed": True,
        "phase04_stage_child_observer_error": None,
        "phase04_stage_child_observer_residual": (
            PHASE04_STAGE_CHILD_OBSERVER_RESIDUAL
        ),
        "phase04_stage_peak_rss_increment_formula_id": (
            PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID
        ),
    }


def _validate_phase04_stage_output_probe(value: Any) -> dict[str, Any]:
    """Validate the exact JSON/Markdown materialization evidence."""

    if type(value) is not dict or set(value) != set(
        PHASE04_STAGE_OUTPUT_PROBE_FIELDS
    ):
        raise ValueError("Phase04-stage output probe fields differ")
    if (
        value["schema_id"] != PHASE04_STAGE_OUTPUT_PROBE_SCHEMA_ID
        or value["production_output_path"] != PHASE04_STAGE_OUTPUT_PATH
        or value["output_boundary_names"]
        != list(PHASE04_STAGE_OUTPUT_BOUNDARIES)
        or value["output_boundary_count"]
        != len(PHASE04_STAGE_OUTPUT_BOUNDARIES)
    ):
        raise ValueError("Phase04-stage output probe policy differs")
    size_fields = (
        "source_result_before_size_bytes",
        "source_result_after_size_bytes",
        "jsonable_result_size_bytes",
        "public_result_size_bytes",
        "public_result_after_size_bytes",
        "json_response_body_size_bytes",
        "markdown_utf8_size_bytes",
        "markdown_response_body_size_bytes",
    )
    if any(type(value[field]) is not int or value[field] < 0 for field in size_fields):
        raise ValueError("Phase04-stage output probe sizes differ")
    digest_fields = (
        "source_result_before_sha256",
        "source_result_after_sha256",
        "jsonable_result_sha256",
        "public_result_sha256",
        "public_result_after_sha256",
        "json_response_body_sha256",
        "markdown_utf8_sha256",
        "markdown_response_body_sha256",
    )
    if any(
        type(value[field]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None
        for field in digest_fields
    ):
        raise ValueError("Phase04-stage output probe digests differ")
    if (
        value["source_result_unchanged"] is not True
        or value["source_result_before_size_bytes"]
        != value["source_result_after_size_bytes"]
        or value["source_result_before_sha256"]
        != value["source_result_after_sha256"]
        or value["public_result_unchanged"] is not True
        or value["public_result_size_bytes"]
        != value["public_result_after_size_bytes"]
        or value["public_result_sha256"]
        != value["public_result_after_sha256"]
        or value["json_response_decodes_to_public_result"] is not True
        or value["json_response_media_type"] != "application/json"
        or value["json_response_released_before_markdown"] is not True
        or value["markdown_response_matches_utf8"] is not True
        or value["markdown_response_media_type"] != "text/markdown"
        or value["markdown_utf8_size_bytes"]
        != value["markdown_response_body_size_bytes"]
        or value["markdown_utf8_sha256"]
        != value["markdown_response_body_sha256"]
    ):
        raise ValueError("Phase04-stage output probe parity differs")
    return deepcopy(value)


def _phase04_worker_no_spawn_paths(
    required_paths: Sequence[str] = REQUIRED_FINAL_CODE_PATHS,
) -> tuple[str, ...]:
    paths = tuple(
        sorted(
            path
            for path in required_paths
            if path.startswith("app/") and path.endswith(".py")
        )
    )
    if not paths:
        raise ValueError("Phase04 worker no-spawn path set is empty")
    return paths


def _resolve_ast_reference(
    node: ast.AST,
    aliases: Mapping[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        owner = _resolve_ast_reference(node.value, aliases)
        return f"{owner}.{node.attr}" if owner is not None else None
    if not isinstance(node, ast.Call):
        return None
    called = _resolve_ast_reference(node.func, aliases)
    if called in {"__import__", "importlib.import_module"} and node.args:
        module = node.args[0]
        if isinstance(module, ast.Constant) and isinstance(module.value, str):
            return module.value
    if called == "getattr" and len(node.args) >= 2:
        owner = _resolve_ast_reference(node.args[0], aliases)
        member = node.args[1]
        if (
            owner is not None
            and isinstance(member, ast.Constant)
            and isinstance(member.value, str)
        ):
            return f"{owner}.{member.value}"
    return None


def _phase04_no_spawn_policy(
    workspace: Path = WORKSPACE,
    *,
    paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Reject child APIs from the exact bound P04-owned app file set."""

    root = _trusted_workspace_root(workspace, label="Phase04 no-spawn policy")
    selected = (
        _phase04_worker_no_spawn_paths()
        if paths is None
        else tuple(sorted(paths))
    )
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Phase04 worker no-spawn path set differs")
    forbidden_import_roots = {
        "subprocess",
        "multiprocessing",
        "asyncio.subprocess",
    }
    forbidden_import_members = {
        "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
        "concurrent.futures": {"ProcessPoolExecutor"},
        "os": {
            "fork",
            "forkpty",
            "popen",
            "posix_spawn",
            "posix_spawnp",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "system",
        },
    }
    forbidden_calls = {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "concurrent.futures.ProcessPoolExecutor",
        "os.fork",
        "os.forkpty",
        "os.popen",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.system",
    }
    identities: list[dict[str, Any]] = []
    for raw_path in selected:
        path = _canonical_relative_path(
            raw_path,
            label="Phase04 no-spawn path",
        )
        if not path.startswith("app/") or not path.endswith(".py"):
            raise ValueError("Phase04 worker no-spawn path scope differs")
        source = _read_bounded_regular_file(
            root,
            path,
            maximum_bytes=MAXIMUM_IDENTITY_FILE_BYTES,
            label="Phase04 no-spawn source",
        )
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as error:
            raise ValueError("Phase04 no-spawn source cannot be parsed") from error
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for imported_alias in node.names:
                    name = imported_alias.name
                    if any(
                        name == root_name or name.startswith(f"{root_name}.")
                        for root_name in forbidden_import_roots
                    ):
                        raise ValueError(
                            "Phase04 worker child-process import observed"
                        )
                    local_name = imported_alias.asname or name.split(".")[0]
                    aliases[local_name] = name if imported_alias.asname else local_name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == root_name or module.startswith(f"{root_name}.")
                    for root_name in forbidden_import_roots
                ):
                    raise ValueError("Phase04 worker child-process import observed")
                forbidden_members = forbidden_import_members.get(module, set())
                for imported_alias in node.names:
                    if (
                        imported_alias.name in forbidden_members
                        or (
                            imported_alias.name == "*"
                            and module in forbidden_import_members
                        )
                    ):
                        raise ValueError(
                            "Phase04 worker child-process import observed"
                        )
                    local_name = imported_alias.asname or imported_alias.name
                    aliases[local_name] = f"{module}.{imported_alias.name}"
        assignments: list[tuple[str, ast.AST]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                assignments.extend(
                    (target.id, node.value)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Name
            ) and node.value is not None:
                assignments.append((node.target.id, node.value))
            elif isinstance(node, ast.NamedExpr) and isinstance(
                node.target, ast.Name
            ):
                assignments.append((node.target.id, node.value))
        for _pass in range(len(assignments) + 1):
            changed = False
            for target, expression in assignments:
                resolved = _resolve_ast_reference(expression, aliases)
                if resolved is not None and aliases.get(target) != resolved:
                    aliases[target] = resolved
                    changed = True
            if not changed:
                break
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            resolved_called = _resolve_ast_reference(node.func, aliases)
            if (
                resolved_called in forbidden_calls
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"subprocess_exec", "subprocess_shell"}
                )
                or (
                    resolved_called is not None
                    and (
                        resolved_called.startswith("subprocess.")
                        or resolved_called.startswith("multiprocessing.")
                        or resolved_called.startswith("asyncio.subprocess.")
                        or resolved_called.endswith(".subprocess_exec")
                        or resolved_called.endswith(".subprocess_shell")
                    )
                )
            ):
                raise ValueError("Phase04 worker child-process call observed")
            if resolved_called in {"__import__", "importlib.import_module"} and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    imported = argument.value
                    if any(
                        imported == root_name
                        or imported.startswith(f"{root_name}.")
                        for root_name in forbidden_import_roots
                    ) or imported in {"asyncio", "concurrent.futures"}:
                        raise ValueError(
                            "Phase04 worker dynamic child-process import observed"
                        )
        identities.append(
            {
                "path": path,
                "size_bytes": len(source),
                "sha256": _sha256_bytes(source),
            }
        )
    return {
        "schema_id": PHASE04_NO_SPAWN_SCHEMA_ID,
        "paths": [identity["path"] for identity in identities],
        "source_identities_sha256": _sha256_bytes(_canonical_bytes(identities)),
        "forbidden_child_process_apis_observed": 0,
    }


def _validate_phase04_no_spawn_policy(value: Any) -> dict[str, Any]:
    expected = _current_phase04_no_spawn_policy()
    if type(value) is not dict or any(
        value.get(field) != expected_value
        or type(value.get(field)) is not type(expected_value)
        for field, expected_value in expected.items()
    ) or set(value) != set(expected):
        raise ValueError("Phase04 worker no-spawn policy differs")
    return deepcopy(value)


@lru_cache(maxsize=1)
def _current_phase04_no_spawn_policy() -> dict[str, Any]:
    return _phase04_no_spawn_policy()


def _validate_worker_diagnostics(value: Any) -> dict[str, Any]:
    expected_stream_fields = {
        "size_bytes",
        "sha256",
        "line_count",
        "nonempty_line_count",
        "classifications",
    }
    classification_fields = {
        "informational",
        "progress",
        "warning",
        "phase04_warning",
        "unexpected",
    }
    if type(value) is not dict or set(value) != {
        "schema_id",
        "maximum_stream_bytes",
        "suppression_environment",
        "stdout",
        "stderr",
    }:
        raise ValueError("worker diagnostic fields differ")
    if (
        value.get("schema_id") != WORKER_DIAGNOSTIC_SCHEMA_ID
        or value.get("maximum_stream_bytes") != MAXIMUM_WORKER_DIAGNOSTIC_BYTES
        or value.get("suppression_environment")
        != WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT
    ):
        raise ValueError("worker diagnostic policy differs")
    for stream_name in ("stdout", "stderr"):
        record = value.get(stream_name)
        if type(record) is not dict or set(record) != expected_stream_fields:
            raise ValueError("worker diagnostic stream fields differ")
        size_bytes = record.get("size_bytes")
        line_count = record.get("line_count")
        nonempty = record.get("nonempty_line_count")
        digest = record.get("sha256")
        classifications = record.get("classifications")
        if (
            type(size_bytes) is not int
            or not 0 <= size_bytes <= MAXIMUM_WORKER_DIAGNOSTIC_BYTES
            or type(line_count) is not int
            or line_count < 0
            or type(nonempty) is not int
            or not 0 <= nonempty <= line_count
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(classifications) is not dict
            or set(classifications) != classification_fields
            or any(
                type(count) is not int or count < 0
                for count in classifications.values()
            )
            or sum(classifications.values()) != nonempty
            or classifications["warning"] != 0
            or classifications["phase04_warning"] != 0
            or classifications["unexpected"] != 0
            or size_bytes != 0
            or digest != _sha256_bytes(b"")
            or line_count != 0
            or nonempty != 0
            or any(classifications.values())
        ):
            raise ValueError("worker diagnostic stream evidence differs")
    return deepcopy(value)


def _external_monitor_worker_identity_from_ownership(
    ownership: Mapping[str, Any],
    *,
    platform_name: str = sys.platform,
) -> dict[str, Any]:
    return {
        "worker_pid": ownership["leader_pid"],
        "process_create_time_ns": ownership["leader_create_time_ns"],
        "source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        "platform": platform_name,
    }


def _external_monitor_worker_resource_payload(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "absolute_peak_rss_bytes": snapshot["peak_rss_bytes"],
        "start_hwm_bytes": snapshot["phase04_stage_hwm_baseline_bytes"],
        "start_children_rusage": snapshot[
            "phase04_stage_children_rusage_baseline"
        ],
        "parse_hwm_bytes": snapshot["phase04_stage_parse_hwm_end_bytes"],
        "finish_hwm_bytes": snapshot["phase04_stage_hwm_end_bytes"],
        "finish_children_rusage": snapshot[
            "phase04_stage_children_rusage_end"
        ],
    }


def _external_monitor_protocol_duplex(
    snapshot: Mapping[str, Any],
    ownership: Mapping[str, Any],
    exchanges: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    parse_record_fields = (
        "phase04_stage_parse_checkpoint_monotonic_ns",
        "phase04_stage_parse_current_rss_peak_bytes",
        "phase04_stage_parse_current_rss_end_bytes",
        "phase04_stage_parse_hwm_end_bytes",
    )
    final_record = {
        field: snapshot[field] for field in PHASE04_STAGE_RSS_RECORD_FIELDS
    }
    duplex: list[dict[str, Any]] = []
    for exchange in exchanges:
        sequence = exchange["sequence"]
        operation = exchange["operation"]
        if operation == "PREPARE":
            payload = _external_monitor_worker_identity_from_ownership(
                ownership,
                platform_name=snapshot["phase04_stage_rss_platform"],
            )
            response_record: dict[str, Any] | None = None
        elif operation == "START":
            payload = {
                "first_boundary_component": snapshot[
                    "phase04_stage_rss_first_boundary_component"
                ],
                "hwm_bytes": snapshot["phase04_stage_hwm_baseline_bytes"],
                "children_rusage": snapshot[
                    "phase04_stage_children_rusage_baseline"
                ],
            }
            response_record = None
        elif operation in {"BOUNDARY", "OUTPUT"}:
            payload = {}
            response_record = None
        elif operation == "PARSE":
            payload = {
                "hwm_bytes": snapshot["phase04_stage_parse_hwm_end_bytes"]
            }
            response_record = {
                field: snapshot[field] for field in parse_record_fields
            }
        elif operation == "FINISH":
            payload = {
                "hwm_bytes": snapshot["phase04_stage_hwm_end_bytes"],
                "children_rusage": snapshot[
                    "phase04_stage_children_rusage_end"
                ],
            }
            response_record = deepcopy(final_record)
        else:
            raise ValueError("external RSS monitor attestation operation differs")
        request = {
            "schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "payload": payload,
        }
        response = {
            "schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "status": "ok",
            "record": response_record,
        }
        duplex.append({"request": request, "response": response})
    return duplex


def _validate_retained_worker_ownership(value: Any) -> dict[str, Any]:
    fields = {
        "schema_id",
        "owner_pid",
        "owner_pgid",
        "owner_sid",
        "leader_pid",
        "leader_create_time_ns",
        "pgid",
        "sid",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("external RSS monitor worker ownership differs")
    if (
        value.get("schema_id") != WORKER_GROUP_IDENTITY_SCHEMA_ID
        or any(
            type(value.get(field)) is not int or value[field] < 1
            for field in fields - {"schema_id"}
        )
        or value["leader_pid"] <= 1
        or value["owner_pid"] == value["leader_pid"]
        or value["pgid"] != value["leader_pid"]
        or value["sid"] != value["leader_pid"]
        or value["pgid"] == value["owner_pgid"]
        or value["sid"] == value["owner_sid"]
    ):
        raise ValueError("external RSS monitor worker ownership differs")
    return deepcopy(value)


def _validate_worker_lifetime_lease(
    value: Any,
    *,
    ownership: Mapping[str, Any],
    require_success: bool,
) -> dict[str, Any]:
    fields = {
        "schema_id",
        "state",
        "worker_identity",
        "sigchld",
        "events",
        "monitor_bound_before_worker_bootstrap_release",
        "observer_sampling_quiesced_before_release",
        "current_rss_lane_quiesced_before_release",
        "forbidden_while_active_attempt_counts",
        "failure_preserved_unreaped",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("worker lifetime lease fields differ")
    worker_identity = value.get("worker_identity")
    sigchld = value.get("sigchld")
    attempts = value.get("forbidden_while_active_attempt_counts")
    events = value.get("events")
    if (
        value.get("schema_id") != WORKER_LIFETIME_LEASE_SCHEMA_ID
        or type(worker_identity) is not dict
        or set(worker_identity)
        != {"pid", "process_create_time_ns", "parent_pid", "pgid", "sid"}
        or worker_identity
        != {
            "pid": ownership["leader_pid"],
            "process_create_time_ns": ownership["leader_create_time_ns"],
            "parent_pid": ownership["owner_pid"],
            "pgid": ownership["pgid"],
            "sid": ownership["sid"],
        }
        or type(sigchld) is not dict
        or sigchld
        != {
            "required_disposition": "SIG_DFL",
            "observed_disposition": "SIG_DFL",
            "safe_default": True,
        }
        or type(attempts) is not dict
        or set(attempts) != set(WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS)
        or any(type(count) is not int or count < 0 for count in attempts.values())
        or type(events) is not list
        or any(type(event) is not str for event in events)
        or type(value.get("monitor_bound_before_worker_bootstrap_release"))
        is not bool
        or type(value.get("observer_sampling_quiesced_before_release"))
        is not bool
        or type(value.get("current_rss_lane_quiesced_before_release"))
        is not bool
        or type(value.get("failure_preserved_unreaped")) is not bool
    ):
        raise ValueError("worker lifetime lease custody differs")
    if require_success and (
        value.get("state") != "released_after_sampling_quiescence"
        or events
        != [
            "lease_acquired",
            "monitor_bound",
            "worker_bootstrap_released",
            "observer_sampling_quiesced",
            "current_rss_lane_quiesced",
            "lease_released",
        ]
        or value.get("monitor_bound_before_worker_bootstrap_release") is not True
        or value.get("observer_sampling_quiesced_before_release") is not True
        or value.get("current_rss_lane_quiesced_before_release") is not True
        or value.get("failure_preserved_unreaped") is not False
        or any(attempts.values())
    ):
        raise ValueError("worker lifetime lease success custody differs")
    return deepcopy(value)


def _active_worker_lifetime_lease_binding(
    value: Mapping[str, Any],
    *,
    ownership: Mapping[str, Any],
) -> dict[str, Any]:
    retained = _validate_worker_lifetime_lease(
        dict(value),
        ownership=ownership,
        require_success=True,
    )
    retained["state"] = "active"
    retained["events"] = ["lease_acquired", "monitor_bound"]
    retained["monitor_bound_before_worker_bootstrap_release"] = False
    retained["observer_sampling_quiesced_before_release"] = False
    retained["current_rss_lane_quiesced_before_release"] = False
    retained["failure_preserved_unreaped"] = False
    if any(retained["forbidden_while_active_attempt_counts"].values()):
        raise ValueError("worker lifetime lease active binding differs")
    return retained


def _validate_phase04_thread_qos_record(
    value: Any,
    *,
    platform_name: str,
) -> dict[str, Any]:
    fields = {
        "policy",
        "platform",
        "requested_class_name",
        "requested_class_value",
        "requested_relative_priority",
        "applied",
        "observed_class_value",
        "observed_relative_priority",
    }
    if type(value) is not dict or set(value) != fields:
        raise ValueError("external RSS monitor observer thread QoS fields differ")
    applied = platform_name == "darwin"
    if (
        type(value.get("requested_class_value")) is not int
        or type(value.get("requested_relative_priority")) is not int
        or type(value.get("applied")) is not bool
        or (
            applied
            and (
                type(value.get("observed_class_value")) is not int
                or type(value.get("observed_relative_priority")) is not int
            )
        )
        or (
            not applied
            and (
                value.get("observed_class_value") is not None
                or value.get("observed_relative_priority") is not None
            )
        )
        or value.get("policy") != PHASE04_STAGE_THREAD_QOS_POLICY
        or value.get("platform") != platform_name
        or value.get("requested_class_name")
        != PHASE04_STAGE_DARWIN_QOS_CLASS_NAME
        or value.get("requested_class_value")
        != PHASE04_STAGE_DARWIN_QOS_CLASS
        or value.get("requested_relative_priority")
        != PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY
        or value.get("applied") is not applied
        or value.get("observed_class_value")
        != (PHASE04_STAGE_DARWIN_QOS_CLASS if applied else None)
        or value.get("observed_relative_priority")
        != (PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY if applied else None)
    ):
        raise ValueError("external RSS monitor observer thread QoS custody differs")
    return deepcopy(value)


def _validate_current_rss_lane_custody(
    value: Any,
    *,
    snapshot: Mapping[str, Any],
    controller: Mapping[str, Any],
    observer: Mapping[str, Any],
    ownership: Mapping[str, Any],
    worker_lifetime_lease: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the nested current-RSS process as closed retained evidence."""

    if type(value) is not dict or set(value) != {
        "summary",
        "identity",
        "lifecycle",
        "runtime",
        "protocol",
    }:
        raise ValueError("external RSS monitor current-RSS lane fields differ")

    try:
        identity = rss_lane.validate_lane_identity(value.get("identity"))
        summary = rss_lane.validate_summary(value.get("summary"))
        lifecycle = rss_lane.validate_lifecycle(value.get("lifecycle"))
        runtime = rss_lane.validate_runtime(
            value.get("runtime"),
            summary=summary,
        )
        protocol = rss_lane.validate_protocol_custody(value.get("protocol"))
        transcript = rss_lane._decode_protocol_transcript(protocol)
    except rss_lane.LaneProtocolError as error:
        raise ValueError(
            "external RSS monitor current-RSS lane local custody differs"
        ) from error

    if (
        identity["parent_pid"] != observer["pid"]
        or identity["pid"]
        in {
            controller["pid"],
            observer["pid"],
            ownership["leader_pid"],
        }
        or identity["pgid"] != observer["pid"]
        or identity["sid"] != observer["pid"]
        or identity["platform"] != observer["platform"]
        or identity["source_version"]
        != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        or identity["process_create_time_ns"]
        < observer["process_create_time_ns"]
    ):
        raise ValueError("external RSS monitor current-RSS lane identity differs")

    worker_identity = {
        "worker_pid": ownership["leader_pid"],
        "process_create_time_ns": ownership["leader_create_time_ns"],
        "source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        "platform": observer["platform"],
    }
    active_lifetime_lease = _active_worker_lifetime_lease_binding(
        worker_lifetime_lease,
        ownership=ownership,
    )
    try:
        lease_identity_sha256 = rss_lane._lease_identity_sha256(
            active_lifetime_lease
        )
        if (
            len(transcript) < 2
            or transcript[1].get("request", {}).get("operation")
            != "PREPARE"
            or transcript[1].get("response", {}).get("status") != "ok"
        ):
            raise rss_lane.LaneProtocolError(
                "current-RSS PREPARE transcript differs"
            )
        qualification = rss_lane.validate_qualification(
            transcript[1]["response"].get("record"),
            worker_identity=worker_identity,
            lease_identity_sha256=lease_identity_sha256,
        )
        runtime = rss_lane.validate_runtime(
            runtime,
            summary=summary,
            qualification_attempt=qualification,
        )
    except rss_lane.LaneProtocolError as error:
        raise ValueError(
            "external RSS monitor current-RSS qualification differs"
        ) from error
    started_ns = snapshot["phase04_stage_rss_started_monotonic_ns"]
    expected_progress_count = (
        4 * (snapshot["phase04_stage_rss_synchronous_sample_count"] - 1)
        + 2 * snapshot["phase04_stage_child_observer_sample_count"]
    )
    if (
        summary["state"] != "finished"
        or summary["worker_identity"] != worker_identity
        or summary["lease_identity_sha256"] != lease_identity_sha256
        or summary["started_monotonic_ns"] != started_ns
        or summary["current_baseline_bytes"]
        != snapshot["phase04_stage_current_rss_baseline_bytes"]
        or summary["current_peak_bytes"]
        != snapshot["phase04_stage_current_rss_peak_bytes"]
        or summary["current_end_bytes"]
        != snapshot["phase04_stage_current_rss_end_bytes"]
        or summary["first_async_monotonic_ns"]
        != started_ns + snapshot["phase04_stage_rss_first_async_offset_ns"]
        or summary["last_async_monotonic_ns"]
        != started_ns + snapshot["phase04_stage_rss_last_async_offset_ns"]
        or summary["last_async_monotonic_ns"]
        != snapshot["phase04_stage_rss_api_ended_monotonic_ns"]
        or summary["maximum_gap_ns"]
        != snapshot["phase04_stage_rss_continuous_maximum_gap_ns"]
        or summary["continuous_sample_count"]
        != snapshot["phase04_stage_rss_continuous_sample_count"]
        or summary["completed_generation"] != expected_progress_count
        or qualification["ended_monotonic_ns"] > started_ns
    ):
        raise ValueError("external RSS monitor current-RSS lane summary differs")

    if (
        lifecycle["expected_return_code"] != 0
        or lifecycle["observed_return_code"] != 0
        or lifecycle.get("termination_mode") != "protocol_exit"
        or lifecycle.get("process_reaped") is not True
        or lifecycle.get("exit_status_validated") is not True
        or lifecycle.get("controller_channel_closed") is not True
        or lifecycle.get("diagnostic_streams_closed") is not True
    ):
        raise ValueError("external RSS monitor current-RSS lane lifecycle differs")
    resource_record = runtime.get("resource")
    expected_target_read_count = (
        qualification["resource"]["target_read_count"]
        + summary["continuous_sample_count"]
        + snapshot["phase04_stage_rss_synchronous_sample_count"]
    )
    expected_exchange_count = (
        5
        + snapshot["phase04_stage_rss_synchronous_sample_count"]
        + expected_progress_count
    )
    expected_full_identity_validation_count = expected_exchange_count + 2
    if (
        resource_record["wall_duration_ns"]
        < snapshot["phase04_stage_rss_duration_ns"]
        or resource_record["target_read_count"]
        != expected_target_read_count
        or resource_record["active_started_monotonic_ns"]
        - snapshot["phase04_stage_rss_started_monotonic_ns"]
        > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        or resource_record["active_ended_monotonic_ns"]
        < snapshot["phase04_stage_rss_api_ended_monotonic_ns"]
        or resource_record["full_identity_validation_count"]
        != expected_full_identity_validation_count
        or summary["full_identity_validation_count"]
        != expected_full_identity_validation_count
        or resource_record["leased_rss_only_read_count"]
        != (
            qualification["sampling"]["continuous_sample_count"]
            + summary["continuous_sample_count"]
        )
        or resource_record[
            "qualification_and_measurement_wall_duration_ns"
        ]
        != (
            qualification["wall_duration_ns"]
            + resource_record["active_wall_duration_ns"]
        )
        or resource_record[
            "qualification_and_measurement_cpu_duration_ns"
        ]
        != (
            qualification["cpu"]["duration_ns"]
            + resource_record["active_cpu_duration_ns"]
        )
    ):
        raise ValueError("external RSS monitor current-RSS lane resource differs")

    operations = protocol.get("operations")
    transcript_budget = rss_lane._CanonicalTranscriptBudget()
    try:
        for exchange in transcript:
            response = exchange.get("response")
            request = exchange.get("request")
            if type(response) is not dict or type(request) is not dict:
                raise rss_lane.LaneProtocolError(
                    "current-RSS transcript fields differ"
                )
            budget_token = transcript_budget.trial(
                exchange,
                terminal=(
                    response.get("status") == "error"
                    or request.get("operation") in {"FINISH", "ABORT"}
                ),
            )
            transcript_budget.commit(budget_token)
        budget_raw_bytes, budget_compressed_bytes = (
            transcript_budget.closed_sizes()
        )
    except rss_lane.LaneProtocolError as error:
        raise ValueError(
            "external RSS monitor current-RSS transcript budget differs"
        ) from error
    if (
        protocol["exchange_count"] != expected_exchange_count
        or transcript_budget.exchange_count != protocol["exchange_count"]
        or budget_raw_bytes != protocol["duplex_bytes"]
        or budget_compressed_bytes != protocol["duplex_compressed_bytes"]
        or operations[:4] != ["BIND", "PREPARE", "READ", "START"]
        or operations[-1] != "FINISH"
        or operations.count("BIND") != 1
        or operations.count("PREPARE") != 1
        or operations.count("START") != 1
        or operations.count("READ")
        != snapshot["phase04_stage_rss_synchronous_sample_count"]
        or operations.count("PROGRESS") != expected_progress_count
        or operations.count("CHECKPOINT") != 1
        or operations.count("FINISH") != 1
        or "ABORT" in operations
        or any(
            exchange["response"]["status"] != "ok"
            for exchange in transcript
        )
    ):
        raise ValueError("external RSS monitor current-RSS lane protocol differs")
    expected_parent_identity = {
        field: observer[field]
        for field in (
            "pid",
            "process_create_time_ns",
            "pgid",
            "sid",
            "platform",
            "source_version",
        )
    }
    expected_bind_response = {
        "lane_identity": identity,
        "worker_identity": worker_identity,
        "lease_identity_sha256": lease_identity_sha256,
    }
    bind_exchange = transcript[0]
    qualification_exchange = transcript[1]
    baseline_read_exchange = transcript[2]
    start_exchange = transcript[3]
    finish_exchange = transcript[-1]
    if (
        bind_exchange["request"]["payload"]
        != {
            "parent_identity": expected_parent_identity,
            "worker_ownership": ownership,
            "worker_lifetime_lease": active_lifetime_lease,
        }
        or bind_exchange["response"]["record"] != expected_bind_response
        or qualification_exchange["request"]["payload"] != {}
        or qualification_exchange["response"]["record"] != qualification
        or baseline_read_exchange["response"]["record"]
        != {
            "rss_bytes": snapshot[
                "phase04_stage_current_rss_baseline_bytes"
            ],
            "observed_monotonic_ns": baseline_read_exchange["response"][
                "record"
            ]["observed_monotonic_ns"],
            "lease_identity_sha256": lease_identity_sha256,
        }
        or baseline_read_exchange["response"]["record"][
            "observed_monotonic_ns"
        ]
        < qualification["ended_monotonic_ns"]
        or baseline_read_exchange["response"]["record"][
            "observed_monotonic_ns"
        ]
        > started_ns
        or start_exchange["request"]["payload"]
        != {
            "started_monotonic_ns": started_ns,
            "current_baseline_bytes": snapshot[
                "phase04_stage_current_rss_baseline_bytes"
            ],
        }
        or finish_exchange["request"]["payload"] != {}
        or finish_exchange["response"]["record"]
        != {"summary": summary, "runtime": runtime}
    ):
        raise ValueError(
            "external RSS monitor current-RSS lane transcript binding differs"
        )
    return deepcopy(value)


def _validate_external_rss_monitor_attestation(
    value: Any,
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_id",
        "controller_observer",
        "observer_process",
        "observer_lifecycle",
        "observer_runtime",
        "worker_ownership",
        "worker_lifetime_lease",
        "protocol",
        "scheduler",
        "cyclic_gc",
        "measurement_custody",
    }:
        raise ValueError("external RSS monitor attestation fields differ")
    if value.get("schema_id") != EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID:
        raise ValueError("external RSS monitor attestation identity differs")
    # Reject impossible outer-protocol geometry before decoding nested lane
    # custody so an attacker-controlled count cannot trigger avoidable work.
    table_stage_call_count = snapshot.get("table_stage_call_count")
    output_count = snapshot.get(
        "phase04_stage_rss_output_synchronous_boundary_count"
    )
    if (
        type(table_stage_call_count) is not int
        or table_stage_call_count < 1
        or type(output_count) is not int
        or output_count < 0
        or (2 * table_stage_call_count - 1 + output_count + 4)
        > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
    ):
        raise ValueError("external RSS monitor expected operation count differs")

    controller = value.get("controller_observer")
    controller_fields = {
        "pid",
        "process_create_time_ns",
        "pgid",
        "sid",
        "platform",
        "identity_source",
        "identity_source_version",
    }
    if (
        type(controller) is not dict
        or set(controller) != controller_fields
        or any(
            type(controller.get(field)) is not int or controller[field] < 1
            for field in ("pid", "process_create_time_ns", "pgid", "sid")
        )
        or controller.get("platform") != snapshot["phase04_stage_rss_platform"]
        or controller.get("identity_source")
        != EXTERNAL_RSS_MONITOR_CONTROLLER_IDENTITY_SOURCE
        or controller.get("identity_source_version")
        != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
    ):
        raise ValueError("external RSS monitor controller identity differs")

    observer = value.get("observer_process")
    observer_fields = {
        "pid",
        "parent_pid",
        "process_create_time_ns",
        "pgid",
        "sid",
        "platform",
        "source_version",
    }
    if (
        type(observer) is not dict
        or set(observer) != observer_fields
        or any(
            type(observer.get(field)) is not int or observer[field] < 1
            for field in (
                "pid",
                "parent_pid",
                "process_create_time_ns",
                "pgid",
                "sid",
            )
        )
        or observer["parent_pid"] != controller["pid"]
        or observer["pid"] == controller["pid"]
        or observer["pgid"] != observer["pid"]
        or observer["sid"] != observer["pid"]
        or observer["platform"] != controller["platform"]
        or observer["source_version"]
        != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        or observer["process_create_time_ns"]
        < controller["process_create_time_ns"]
    ):
        raise ValueError("external RSS monitor observer process identity differs")

    observer_lifecycle = value.get("observer_lifecycle")
    if (
        type(observer_lifecycle) is not dict
        or set(observer_lifecycle) != {
            "expected_return_code",
            "observed_return_code",
            "termination_mode",
            "process_reaped",
            "process_group_absent",
            "exit_status_validated",
            "diagnostics",
        }
        or type(observer_lifecycle.get("expected_return_code")) is not int
        or observer_lifecycle["expected_return_code"] != 0
        or type(observer_lifecycle.get("observed_return_code")) is not int
        or observer_lifecycle["observed_return_code"] != 0
        or observer_lifecycle.get("termination_mode") != "protocol_exit"
        or observer_lifecycle.get("process_reaped") is not True
        or observer_lifecycle.get("process_group_absent") is not True
        or observer_lifecycle.get("exit_status_validated") is not True
    ):
        raise ValueError("external RSS monitor observer lifecycle differs")
    observer_diagnostics = observer_lifecycle.get("diagnostics")
    if (
        type(observer_diagnostics) is not dict
        or set(observer_diagnostics) != {
            "schema_id",
            "maximum_stream_bytes",
            "capture_mode",
            "streams_closed",
            "stdout",
            "stderr",
        }
        or observer_diagnostics.get("schema_id")
        != OBSERVER_DIAGNOSTIC_SCHEMA_ID
        or type(observer_diagnostics.get("maximum_stream_bytes")) is not int
        or observer_diagnostics["maximum_stream_bytes"]
        != MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES
        or observer_diagnostics.get("capture_mode")
        != "kernel_pipes_bounded_backpressure_read_after_reap"
        or observer_diagnostics.get("streams_closed") is not True
    ):
        raise ValueError("external RSS monitor observer diagnostics differ")
    for stream_name in ("stdout", "stderr"):
        stream = observer_diagnostics.get(stream_name)
        if (
            type(stream) is not dict
            or set(stream) != {
                "size_bytes",
                "sha256",
                "line_count",
                "capture_complete",
            }
            or type(stream.get("size_bytes")) is not int
            or stream["size_bytes"] != 0
            or stream.get("sha256") != _sha256_bytes(b"")
            or type(stream.get("line_count")) is not int
            or stream["line_count"] != 0
            or stream.get("capture_complete") is not True
        ):
            raise ValueError("external RSS monitor observer diagnostics differ")

    observer_runtime = value.get("observer_runtime")
    if type(observer_runtime) is not dict or set(observer_runtime) != {
        "scope",
        "main_thread_qos",
        "sampler_thread_qos",
        "current_rss_lane",
        "scheduler",
        "cyclic_gc",
    }:
        raise ValueError("external RSS monitor observer runtime fields differ")
    _validate_phase04_thread_qos_record(
        observer_runtime.get("main_thread_qos"),
        platform_name=observer["platform"],
    )
    sampler_thread_qos = observer_runtime.get("sampler_thread_qos")
    if type(sampler_thread_qos) is not dict or set(sampler_thread_qos) != {
        "policy",
        "child_observer_thread",
    }:
        raise ValueError("external RSS monitor observer sampler QoS fields differ")
    if sampler_thread_qos.get("policy") != PHASE04_STAGE_THREAD_QOS_POLICY:
        raise ValueError("external RSS monitor observer sampler QoS custody differs")
    _validate_phase04_thread_qos_record(
        sampler_thread_qos.get("child_observer_thread"),
        platform_name=observer["platform"],
    )
    observer_scheduler = observer_runtime.get("scheduler")
    if type(observer_scheduler) is not dict or set(observer_scheduler) != {
        "requested_interval_hex",
        "original_interval_hex",
        "effective_interval_hex",
        "restored_interval_hex",
        "restoration_completed",
        "external_mutation_observed",
    }:
        raise ValueError("external RSS monitor observer scheduler fields differ")
    try:
        observer_intervals = {
            field: float.fromhex(observer_scheduler[field])
            for field in (
                "requested_interval_hex",
                "original_interval_hex",
                "effective_interval_hex",
                "restored_interval_hex",
            )
        }
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("external RSS monitor observer scheduler differs") from error
    if (
        any(
            type(observer_scheduler.get(field)) is not str
            or observer_scheduler[field] != interval.hex()
            for field, interval in observer_intervals.items()
        )
        or
        observer_runtime.get("scope") != EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE
        or observer_intervals["requested_interval_hex"]
        != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        or observer_intervals["effective_interval_hex"]
        != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        or observer_intervals["restored_interval_hex"]
        != observer_intervals["original_interval_hex"]
        or any(
            not math.isfinite(interval) or interval <= 0
            for interval in observer_intervals.values()
        )
        or observer_scheduler.get("restoration_completed") is not True
        or observer_scheduler.get("external_mutation_observed") is not False
    ):
        raise ValueError("external RSS monitor observer scheduler custody differs")
    observer_gc = observer_runtime.get("cyclic_gc")
    observer_original_gc = (
        observer_gc.get("original_enabled")
        if type(observer_gc) is dict
        else None
    )
    if (
        type(observer_gc) is not dict
        or set(observer_gc) != {
            "original_enabled",
            "effective_enabled",
            "restored_enabled",
            "pre_window_collection_performed",
            "pre_window_collected_objects",
            "restoration_completed",
            "external_mutation_observed",
        }
        or type(observer_original_gc) is not bool
        or observer_gc.get("effective_enabled") is not False
        or observer_gc.get("restored_enabled") is not observer_original_gc
        or observer_gc.get("pre_window_collection_performed")
        is not observer_original_gc
        or type(observer_gc.get("pre_window_collected_objects")) is not int
        or observer_gc["pre_window_collected_objects"] < 0
        or (
            not observer_original_gc
            and observer_gc["pre_window_collected_objects"] != 0
        )
        or observer_gc.get("restoration_completed") is not True
        or observer_gc.get("external_mutation_observed") is not False
    ):
        raise ValueError("external RSS monitor observer GC custody differs")

    ownership = _validate_retained_worker_ownership(
        value.get("worker_ownership")
    )
    if (
        ownership["owner_pid"] != controller["pid"]
        or ownership["owner_pgid"] != controller["pgid"]
        or ownership["owner_sid"] != controller["sid"]
        or ownership["leader_pid"]
        != snapshot["phase04_stage_rss_worker_pid"]
        or ownership["leader_create_time_ns"]
        != snapshot["phase04_stage_rss_process_create_time_ns"]
        or ownership["leader_pid"] == observer["pid"]
        or controller["process_create_time_ns"]
        > ownership["leader_create_time_ns"]
        or ownership["leader_create_time_ns"]
        > observer["process_create_time_ns"]
    ):
        raise ValueError("external RSS monitor ownership custody differs")
    try:
        validated_worker_lifetime_lease = _validate_worker_lifetime_lease(
            value.get("worker_lifetime_lease"),
            ownership=ownership,
            require_success=True,
        )
    except ValueError as error:
        raise ValueError(
            "external RSS monitor worker lifetime lease differs"
        ) from error
    _validate_current_rss_lane_custody(
        observer_runtime.get("current_rss_lane"),
        snapshot=snapshot,
        controller=controller,
        observer=observer,
        ownership=ownership,
        worker_lifetime_lease=validated_worker_lifetime_lease,
    )

    protocol = value.get("protocol")
    if type(protocol) is not dict or set(protocol) != {
        "wire_schema_id",
        "framing",
        "maximum_exchange_count",
        "maximum_duplex_exchange_bytes",
        "exchange_count",
        "duplex_exchange_bytes",
        "exchanges",
        "duplex_transcript_sha256",
    }:
        raise ValueError("external RSS monitor protocol fields differ")
    exchanges = protocol.get("exchanges")
    if type(exchanges) is not list or any(
        type(exchange) is not dict
        or set(exchange) != {"sequence", "operation"}
        or type(exchange.get("sequence")) is not int
        or exchange["sequence"] < 1
        or exchange.get("operation") not in EXTERNAL_RSS_MONITOR_OPERATIONS
        for exchange in exchanges
    ):
        raise ValueError("external RSS monitor exchanges differ")
    operations = [exchange["operation"] for exchange in exchanges]
    parse_indexes = [
        index for index, operation in enumerate(operations) if operation == "PARSE"
    ]
    table_stage_call_count = snapshot["table_stage_call_count"]
    expected_output_count = snapshot[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]
    if (
        type(table_stage_call_count) is not int
        or table_stage_call_count < 1
        or type(expected_output_count) is not int
        or expected_output_count < 0
    ):
        raise ValueError("external RSS monitor expected operation count differs")
    expected_boundary_count = 2 * table_stage_call_count - 1
    expected_exchange_count = (
        expected_boundary_count + expected_output_count + 4
    )
    if expected_exchange_count > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES:
        raise ValueError("external RSS monitor expected operation count differs")
    if (
        protocol.get("wire_schema_id") != EXTERNAL_RSS_MONITOR_SCHEMA_ID
        or protocol.get("framing") != EXTERNAL_RSS_MONITOR_FRAMING
        or type(protocol.get("maximum_exchange_count")) is not int
        or protocol.get("maximum_exchange_count")
        != EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
        or type(protocol.get("maximum_duplex_exchange_bytes")) is not int
        or protocol.get("maximum_duplex_exchange_bytes")
        != EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
        or type(protocol.get("exchange_count")) is not int
        or protocol.get("exchange_count") != len(exchanges)
        or len(exchanges) > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
        or [exchange["sequence"] for exchange in exchanges]
        != list(range(1, len(exchanges) + 1))
        or len(parse_indexes) != 1
        or operations[:2] != ["PREPARE", "START"]
        or not operations
        or operations[-1] != "FINISH"
        or "ABORT" in operations
        or len(exchanges) != expected_exchange_count
        or parse_indexes[0] != expected_boundary_count + 2
        or not all(
            operation == "BOUNDARY"
            for operation in operations[2 : parse_indexes[0]]
        )
        or len(operations[parse_indexes[0] + 1 : -1])
        != expected_output_count
        or not all(
            operation == "OUTPUT"
            for operation in operations[parse_indexes[0] + 1 : -1]
        )
        or snapshot["phase04_stage_rss_synchronous_sample_count"]
        != expected_boundary_count + expected_output_count + 3
    ):
        raise ValueError("external RSS monitor protocol sequence differs")
    duplex = _external_monitor_protocol_duplex(
        snapshot,
        ownership,
        exchanges,
    )
    duplex_exchange_bytes = sum(
        len(_canonical_bytes(exchange)) for exchange in duplex
    )
    if (
        type(protocol.get("duplex_exchange_bytes")) is not int
        or protocol.get("duplex_exchange_bytes") != duplex_exchange_bytes
        or duplex_exchange_bytes
        > EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
    ):
        raise ValueError("external RSS monitor transcript bound differs")
    if protocol.get("duplex_transcript_sha256") != _sha256_bytes(
        _canonical_bytes(duplex)
    ):
        raise ValueError("external RSS monitor transcript custody differs")

    scheduler = value.get("scheduler")
    if type(scheduler) is not dict or set(scheduler) != {
        "scope",
        "requested_interval_hex",
        "original_interval_hex",
        "effective_interval_hex",
        "restored_interval_hex",
        "restoration_completed",
        "external_mutation_observed",
    }:
        raise ValueError("external RSS monitor scheduler fields differ")
    interval_fields = (
        "requested_interval_hex",
        "original_interval_hex",
        "effective_interval_hex",
        "restored_interval_hex",
    )
    intervals: dict[str, float] = {}
    try:
        for field in interval_fields:
            encoded = scheduler[field]
            if type(encoded) is not str:
                raise ValueError
            decoded = float.fromhex(encoded)
            if (
                not math.isfinite(decoded)
                or decoded <= 0
                or decoded.hex() != encoded
            ):
                raise ValueError
            intervals[field] = decoded
    except (KeyError, ValueError, OverflowError) as error:
        raise ValueError("external RSS monitor scheduler interval differs") from error
    if (
        scheduler.get("scope") != EXTERNAL_RSS_MONITOR_SCHEDULER_SCOPE
        or intervals["requested_interval_hex"]
        != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        or intervals["effective_interval_hex"]
        != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
        or intervals["restored_interval_hex"]
        != intervals["original_interval_hex"]
        or scheduler.get("restoration_completed") is not True
        or scheduler.get("external_mutation_observed") is not False
    ):
        raise ValueError("external RSS monitor scheduler custody differs")

    cyclic_gc = value.get("cyclic_gc")
    if type(cyclic_gc) is not dict or set(cyclic_gc) != {
        "scope",
        "original_enabled",
        "effective_enabled",
        "restored_enabled",
        "pre_window_collection_performed",
        "pre_window_collected_objects",
        "restoration_completed",
        "external_mutation_observed",
    }:
        raise ValueError("external RSS monitor GC fields differ")
    original_gc_enabled = cyclic_gc.get("original_enabled")
    if (
        cyclic_gc.get("scope") != EXTERNAL_RSS_MONITOR_GC_SCOPE
        or type(original_gc_enabled) is not bool
        or cyclic_gc.get("effective_enabled") is not False
        or cyclic_gc.get("restored_enabled") is not original_gc_enabled
        or cyclic_gc.get("pre_window_collection_performed")
        is not original_gc_enabled
        or type(cyclic_gc.get("pre_window_collected_objects")) is not int
        or cyclic_gc["pre_window_collected_objects"] < 0
        or (
            not original_gc_enabled
            and cyclic_gc["pre_window_collected_objects"] != 0
        )
        or cyclic_gc.get("restoration_completed") is not True
        or cyclic_gc.get("external_mutation_observed") is not False
    ):
        raise ValueError("external RSS monitor GC custody differs")

    rss_record = {
        field: snapshot[field] for field in PHASE04_STAGE_RSS_RECORD_FIELDS
    }
    rss_digest = _sha256_bytes(_canonical_bytes(rss_record))
    resource_payload_digest = _sha256_bytes(
        _canonical_bytes(_external_monitor_worker_resource_payload(snapshot))
    )
    expected_custody = {
        "current_rss_owner": (
            "controller_owned_dedicated_current_rss_lane_process"
        ),
        "child_observer_owner": "controller_owned_observer_process",
        "current_rss_source": PHASE04_STAGE_CURRENT_RSS_SOURCE,
        "current_rss_source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
        "sampling_scope": PHASE04_STAGE_RSS_SAMPLING_SCOPE,
        "child_observer_source": PHASE04_STAGE_CHILD_OBSERVER_SOURCE,
        "child_observer_source_version": (
            PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION
        ),
        "child_scope": PHASE04_STAGE_RSS_CHILD_SCOPE,
        "high_water_measurement_owner": "fresh_worker",
        "high_water_custody_path": "worker_payload_controller_round_trip",
        "children_rusage_measurement_owner": "fresh_worker",
        "children_rusage_custody_path": (
            "worker_payload_controller_round_trip"
        ),
        "controller_monitor_allocations_in_worker_g": False,
        "worker_proxy_executes_in_worker_process": True,
        "worker_proxy_resource_credit_bytes": 0,
        "controller_gc_custody_outside_worker_g": True,
        "worker_release_after_monitor_quiescence": True,
        "observer_process_is_worker_descendant": False,
        "observer_process_allocations_in_worker_g": False,
        "current_rss_lane_process_is_observer_descendant": True,
        "current_rss_lane_process_is_worker_descendant": False,
        "current_rss_lane_process_allocations_in_worker_g": False,
        "current_rss_lane_resource_credit_bytes": 0,
        "worker_release_after_current_rss_lane_quiescence": True,
        "controller_rss_record_sha256": rss_digest,
        "worker_retained_rss_record_sha256": rss_digest,
        "records_match": True,
        "worker_resource_payload_sha256": resource_payload_digest,
        "worker_absolute_peak_rss_bytes_at_snapshot": snapshot["peak_rss_bytes"],
        "covers_hwm_end": (
            snapshot["peak_rss_bytes"]
            >= snapshot["phase04_stage_hwm_end_bytes"]
        ),
    }
    measurement_custody = value.get("measurement_custody")
    if (
        type(measurement_custody) is not dict
        or _canonical_bytes(measurement_custody)
        != _canonical_bytes(expected_custody)
    ):
        raise ValueError("external RSS monitor measurement custody differs")
    return deepcopy(value)


def _validate_snapshot(
    value: Mapping[str, Any],
    *,
    case_id: str,
    enabled: bool,
    allow_unattached_diagnostics: bool = False,
    allow_unattached_external_attestation: bool = False,
) -> None:
    if set(value) != set(SNAPSHOT_FIELDS):
        raise ValueError("table metrics worker snapshot fields differ")
    if value["case_id"] != case_id or value["enabled"] is not enabled:
        raise ValueError("table metrics worker state differs")
    if value["source_identity"] != _source_identity(case_id):
        raise ValueError("table metrics worker source custody differs")
    if (
        type(value["wall_seconds"]) not in (int, float)
        or type(value["wall_seconds"]) is bool
        or not math.isfinite(float(value["wall_seconds"]))
        or value["wall_seconds"] <= 0
    ):
        raise ValueError("worker latency must be a positive finite value")
    if (
        type(value["table_stage_seconds"]) not in (int, float)
        or type(value["table_stage_seconds"]) is bool
        or not math.isfinite(float(value["table_stage_seconds"]))
        or value["table_stage_seconds"] <= 0
        or value["table_stage_seconds"] > value["wall_seconds"]
    ):
        raise ValueError("worker table-stage latency must be positive and bounded")
    components = value.get("table_stage_components")
    if type(components) is not dict or set(components) != set(
        TABLE_STAGE_COMPONENTS
    ):
        raise ValueError("worker table-stage components differ")
    component_seconds = 0.0
    component_call_count = 0
    for component in TABLE_STAGE_COMPONENTS:
        record = components.get(component)
        if type(record) is not dict or set(record) != set(
            TABLE_STAGE_COMPONENT_FIELDS
        ):
            raise ValueError("worker table-stage component fields differ")
        seconds = record.get("elapsed_seconds")
        call_count = record.get("call_count")
        required_reachable = (
            component in TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
            or (
                enabled
                and component in TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS
            )
        )
        forbidden_by_flag = (
            not enabled and component in TABLE_STAGE_ENABLED_ONLY_COMPONENTS
        )
        if (
            type(seconds) not in (int, float)
            or type(seconds) is bool
            or not math.isfinite(float(seconds))
            or seconds < 0
            or seconds > value["wall_seconds"]
            or type(call_count) is not int
            or call_count < 0
            or call_count > 1_000_000
            or (required_reachable and call_count < 1)
            or (forbidden_by_flag and call_count != 0)
            or (call_count == 0 and seconds != 0)
        ):
            raise ValueError("worker table-stage component measurement differs")
        component_seconds += float(seconds)
        component_call_count += call_count
    if not math.isclose(
        float(value["table_stage_seconds"]),
        round(component_seconds, 9),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise ValueError("worker table-stage component latency sum differs")
    if value["table_stage_call_count"] != component_call_count:
        raise ValueError("worker table-stage component call-count sum differs")
    for field in (
        "peak_rss_bytes",
        "semantic_json_size_bytes",
        "table_stage_call_count",
        "marked_table_count",
        "maximum_marked_table_bytes",
        "document_sidecar_bytes",
    ):
        if type(value[field]) is not int or value[field] < 0:
            raise ValueError(f"worker {field} must be a nonnegative integer")
    digest = value["semantic_json_sha256"]
    if (
        type(digest) is not str
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("worker semantic digest is invalid")
    if any(
        value[field] != expected or type(value[field]) is not type(expected)
        for field, expected in HOSTED_USAGE.items()
    ):
        raise ValueError("hosted use is forbidden for table metrics")
    if value["rss_source"] != PHASE04_STAGE_RSS_SOURCE:
        raise ValueError("worker RSS source differs")
    if value["rss_normalization"] != PHASE04_STAGE_RSS_NORMALIZATION:
        raise ValueError("worker RSS normalization differs")
    expected_stage_rss = _phase04_stage_rss_record(
        current_baseline_bytes=value.get(
            "phase04_stage_current_rss_baseline_bytes"
        ),
        current_peak_bytes=value.get("phase04_stage_current_rss_peak_bytes"),
        current_end_bytes=value.get("phase04_stage_current_rss_end_bytes"),
        hwm_baseline_bytes=value.get("phase04_stage_hwm_baseline_bytes"),
        hwm_end_bytes=value.get("phase04_stage_hwm_end_bytes"),
        children_rusage_baseline=value.get(
            "phase04_stage_children_rusage_baseline"
        ),
        children_rusage_end=value.get(
            "phase04_stage_children_rusage_end"
        ),
        current_rss_source_version=value.get(
            "phase04_stage_current_rss_source_version"
        ),
        first_boundary_component=value.get(
            "phase04_stage_rss_first_boundary_component"
        ),
        worker_pid=value.get("phase04_stage_rss_worker_pid"),
        process_create_time_ns=value.get(
            "phase04_stage_rss_process_create_time_ns"
        ),
        platform_name=value.get("phase04_stage_rss_platform"),
        started_monotonic_ns=value.get(
            "phase04_stage_rss_started_monotonic_ns"
        ),
        parse_checkpoint_monotonic_ns=value.get(
            "phase04_stage_parse_checkpoint_monotonic_ns"
        ),
        parse_current_peak_bytes=value.get(
            "phase04_stage_parse_current_rss_peak_bytes"
        ),
        parse_current_end_bytes=value.get(
            "phase04_stage_parse_current_rss_end_bytes"
        ),
        parse_hwm_end_bytes=value.get("phase04_stage_parse_hwm_end_bytes"),
        ended_monotonic_ns=value.get(
            "phase04_stage_rss_api_ended_monotonic_ns"
        ),
        sampling_maximum_gap_ns=value.get(
            "phase04_stage_rss_continuous_maximum_gap_ns"
        ),
        sample_count=value.get("phase04_stage_rss_sample_count"),
        continuous_sample_count=value.get(
            "phase04_stage_rss_continuous_sample_count"
        ),
        synchronous_sample_count=value.get(
            "phase04_stage_rss_synchronous_sample_count"
        ),
        output_synchronous_boundary_count=value.get(
            "phase04_stage_rss_output_synchronous_boundary_count"
        ),
        first_async_offset_ns=value.get(
            "phase04_stage_rss_first_async_offset_ns"
        ),
        last_async_offset_ns=value.get(
            "phase04_stage_rss_last_async_offset_ns"
        ),
        child_observer_maximum_gap_ns=value.get(
            "phase04_stage_child_observer_continuous_maximum_gap_ns"
        ),
        child_observer_sample_count=value.get(
            "phase04_stage_child_observer_sample_count"
        ),
        child_boundary_check_count=value.get(
            "phase04_stage_child_boundary_check_count"
        ),
        child_observer_first_offset_ns=value.get(
            "phase04_stage_child_observer_first_offset_ns"
        ),
        child_observer_last_offset_ns=value.get(
            "phase04_stage_child_observer_last_offset_ns"
        ),
    )
    if any(
        value.get(field) != expected
        or type(value.get(field)) is not type(expected)
        for field, expected in expected_stage_rss.items()
    ):
        raise ValueError("worker Phase04-stage RSS measurement differs")
    if (
        value["phase04_stage_current_rss_source_version"]
        != _current_rss_source_version()
    ):
        raise ValueError("worker Phase04-stage RSS source version differs")
    if value["peak_rss_bytes"] < value["phase04_stage_hwm_end_bytes"]:
        raise ValueError("worker absolute peak RSS precedes Phase04-stage RSS end")
    if value["phase04_stage_rss_synchronous_sample_count"] != (
        2 * value["table_stage_call_count"]
        + value["phase04_stage_rss_output_synchronous_boundary_count"]
        + 2
    ):
        raise ValueError("worker Phase04-stage RSS boundary coverage differs")
    output_probe = _validate_phase04_stage_output_probe(
        value.get("phase04_stage_output_probe")
    )
    if output_probe["output_boundary_count"] != value[
        "phase04_stage_rss_output_synchronous_boundary_count"
    ]:
        raise ValueError("worker Phase04-stage output boundary coverage differs")
    _validate_phase04_no_spawn_policy(value.get("phase04_stage_no_spawn_policy"))
    if components[
        value["phase04_stage_rss_first_boundary_component"]
    ]["call_count"] < 1:
        raise ValueError("worker Phase04-stage first RSS boundary was not reached")
    status_counts = value.get("table_status_counts")
    if (
        type(status_counts) is not dict
        or not set(status_counts) <= TABLE_STATUS_VALUES
        or any(
            type(count) is not int
            or not 0 <= count <= value["marked_table_count"]
            for count in status_counts.values()
        )
        or sum(status_counts.values()) != value["marked_table_count"]
    ):
        raise ValueError("worker table status counts differ")
    _validate_worker_quality(
        value.get("quality"),
        case_id=case_id,
    )
    external_attestation = value.get("external_rss_monitor_attestation")
    if allow_unattached_external_attestation:
        if external_attestation is not None:
            raise ValueError(
                "raw worker external RSS monitor attestation must be absent"
            )
    elif external_attestation is None:
        raise ValueError("external RSS monitor attestation is absent")
    else:
        _validate_external_rss_monitor_attestation(
            external_attestation,
            value,
        )
    diagnostics = value.get("worker_diagnostics")
    if diagnostics is None and allow_unattached_diagnostics:
        return
    _validate_worker_diagnostics(diagnostics)


def paired_performance_summary(
    case_id: str,
    flag_off_samples: Sequence[Mapping[str, Any]],
    flag_on_samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply paired latency, RSS, and output gates to exact worker samples."""

    if len(flag_off_samples) != PAIR_COUNT or len(flag_on_samples) != PAIR_COUNT:
        raise ValueError("paired table metrics require exactly five pairs")
    for sample in flag_off_samples:
        _validate_snapshot(sample, case_id=case_id, enabled=False)
    for sample in flag_on_samples:
        _validate_snapshot(sample, case_id=case_id, enabled=True)
    worker_identities = [
        (
            sample["phase04_stage_rss_worker_pid"],
            sample["phase04_stage_rss_process_create_time_ns"],
        )
        for sample in (*flag_off_samples, *flag_on_samples)
    ]
    if len(set(worker_identities)) != 2 * PAIR_COUNT:
        raise ValueError("paired table metrics require distinct fresh workers")
    observer_identities = [
        (
            sample["external_rss_monitor_attestation"]["observer_process"][
                "pid"
            ],
            sample["external_rss_monitor_attestation"]["observer_process"][
                "process_create_time_ns"
            ],
        )
        for sample in (*flag_off_samples, *flag_on_samples)
    ]
    if len(set(observer_identities)) != 2 * PAIR_COUNT:
        raise ValueError(
            "paired table metrics require distinct fresh observer processes"
        )
    first_boundaries = {
        enabled: {
            sample["phase04_stage_rss_first_boundary_component"]
            for sample in samples
        }
        for enabled, samples in (
            (False, flag_off_samples),
            (True, flag_on_samples),
        )
    }
    if first_boundaries != {
        False: {"repair_extraction"},
        True: {"budget_start"},
    }:
        raise ValueError("paired table metrics first RSS boundaries differ")

    off_seconds = [float(sample["wall_seconds"]) for sample in flag_off_samples]
    on_seconds = [float(sample["wall_seconds"]) for sample in flag_on_samples]
    whole_parser_overhead_ratios = [
        max(0.0, on - off) / off
        for off, on in zip(off_seconds, on_seconds, strict=True)
    ]
    off_stage_seconds = [
        float(sample["table_stage_seconds"]) for sample in flag_off_samples
    ]
    on_stage_seconds = [
        float(sample["table_stage_seconds"]) for sample in flag_on_samples
    ]
    signed_deltas = [
        on - off
        for off, on in zip(off_stage_seconds, on_stage_seconds, strict=True)
    ]
    nonnegative_deltas = [max(0.0, value) for value in signed_deltas]
    table_stage_additive_overhead_ratios = [
        delta / off_wall
        for delta, off_wall in zip(
            nonnegative_deltas,
            off_seconds,
            strict=True,
        )
    ]
    observational_absolute_rss_deltas = [
        int(on["peak_rss_bytes"]) - int(off["peak_rss_bytes"])
        for off, on in zip(flag_off_samples, flag_on_samples, strict=True)
    ]
    off_stage_rss_increments = [
        int(sample["phase04_stage_peak_rss_increment_bytes"])
        for sample in flag_off_samples
    ]
    on_stage_rss_increments = [
        int(sample["phase04_stage_peak_rss_increment_bytes"])
        for sample in flag_on_samples
    ]
    paired_stage_rss_increment_deltas = [
        on - off
        for off, on in zip(
            off_stage_rss_increments,
            on_stage_rss_increments,
            strict=True,
        )
    ]
    paired_nonnegative_stage_rss_increment_deltas = [
        max(0, value) for value in paired_stage_rss_increment_deltas
    ]
    p50_ratio = inclusive_nearest_rank(
        table_stage_additive_overhead_ratios,
        0.50,
    )
    p95_ratio = inclusive_nearest_rank(
        table_stage_additive_overhead_ratios,
        0.95,
    )
    whole_parser_p50_ratio = inclusive_nearest_rank(
        whole_parser_overhead_ratios,
        0.50,
    )
    whole_parser_p95_ratio = inclusive_nearest_rank(
        whole_parser_overhead_ratios,
        0.95,
    )
    component_latency = {}
    for component in TABLE_STAGE_COMPONENTS:
        off_component_seconds = [
            float(sample["table_stage_components"][component]["elapsed_seconds"])
            for sample in flag_off_samples
        ]
        on_component_seconds = [
            float(sample["table_stage_components"][component]["elapsed_seconds"])
            for sample in flag_on_samples
        ]
        component_latency[component] = {
            "flag_off_p50_seconds": inclusive_nearest_rank(
                off_component_seconds, 0.50
            ),
            "flag_off_p95_seconds": inclusive_nearest_rank(
                off_component_seconds, 0.95
            ),
            "flag_on_p50_seconds": inclusive_nearest_rank(
                on_component_seconds, 0.50
            ),
            "flag_on_p95_seconds": inclusive_nearest_rank(
                on_component_seconds, 0.95
            ),
            "paired_signed_deltas_seconds": [
                on - off
                for off, on in zip(
                    off_component_seconds,
                    on_component_seconds,
                    strict=True,
                )
            ],
        }
    ratio_ceiling = float(TABLE_LIMITS["maximum_table_stage_p95_overhead_ratio"])
    rss_ceiling = int(TABLE_LIMITS["maximum_peak_rss_delta_bytes"])
    table_output_ceiling = int(TABLE_LIMITS["maximum_table_sidecar_bytes"])
    document_output_ceiling = int(
        TABLE_LIMITS["maximum_phase04_sidecars_per_document_bytes"]
    )
    return {
        "schema_id": PAIRED_PERFORMANCE_SCHEMA_ID,
        "table_stage_overhead_formula_id": TABLE_STAGE_OVERHEAD_FORMULA_ID,
        "phase04_stage_peak_rss_increment_formula_id": (
            PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID
        ),
        "paired_phase04_stage_peak_rss_delta_formula_id": (
            PAIRED_PHASE04_STAGE_PEAK_RSS_DELTA_FORMULA_ID
        ),
        "case_id": case_id,
        "pair_count": PAIR_COUNT,
        "quantile_method": "empirical_inclusive_nearest_rank",
        "execution_order": [
            ["on" if state else "off" for state in paired_states(index)]
            for index in range(PAIR_COUNT)
        ],
        "flag_off_samples": [dict(sample) for sample in flag_off_samples],
        "flag_on_samples": [dict(sample) for sample in flag_on_samples],
        "flag_off_p50_seconds": inclusive_nearest_rank(off_seconds, 0.50),
        "flag_off_p95_seconds": inclusive_nearest_rank(off_seconds, 0.95),
        "flag_on_p50_seconds": inclusive_nearest_rank(on_seconds, 0.50),
        "flag_on_p95_seconds": inclusive_nearest_rank(on_seconds, 0.95),
        "paired_nonnegative_whole_parser_overhead_ratios": (
            whole_parser_overhead_ratios
        ),
        "whole_parser_p50_overhead_ratio": whole_parser_p50_ratio,
        "whole_parser_p95_overhead_ratio": whole_parser_p95_ratio,
        "whole_parser_overhead_ratio_ceiling": ratio_ceiling,
        "within_whole_parser_p50_overhead_ratio_ceiling": (
            whole_parser_p50_ratio <= ratio_ceiling
        ),
        "within_whole_parser_p95_overhead_ratio_ceiling": (
            whole_parser_p95_ratio <= ratio_ceiling
        ),
        "flag_off_table_stage_p50_seconds": inclusive_nearest_rank(
            off_stage_seconds, 0.50
        ),
        "flag_off_table_stage_p95_seconds": inclusive_nearest_rank(
            off_stage_seconds, 0.95
        ),
        "flag_on_table_stage_p50_seconds": inclusive_nearest_rank(
            on_stage_seconds, 0.50
        ),
        "flag_on_table_stage_p95_seconds": inclusive_nearest_rank(
            on_stage_seconds, 0.95
        ),
        "paired_signed_table_stage_deltas_seconds": signed_deltas,
        "paired_nonnegative_table_stage_deltas_seconds": nonnegative_deltas,
        "paired_nonnegative_table_stage_additive_overhead_ratios": (
            table_stage_additive_overhead_ratios
        ),
        "component_latency": component_latency,
        "p50_overhead_ratio": p50_ratio,
        "p95_overhead_ratio": p95_ratio,
        "overhead_ratio_ceiling": ratio_ceiling,
        "within_p50_overhead_ratio_ceiling": p50_ratio <= ratio_ceiling,
        "within_p95_overhead_ratio_ceiling": p95_ratio <= ratio_ceiling,
        "observational_paired_absolute_peak_rss_deltas_bytes": (
            observational_absolute_rss_deltas
        ),
        "absolute_peak_rss_delta_interpretation": (
            "observational_only_not_gated"
        ),
        "paired_phase04_stage_peak_rss_increment_deltas_bytes": (
            paired_stage_rss_increment_deltas
        ),
        "paired_nonnegative_phase04_stage_peak_rss_increment_deltas_bytes": (
            paired_nonnegative_stage_rss_increment_deltas
        ),
        "maximum_paired_phase04_stage_peak_rss_increment_delta_bytes": max(
            paired_nonnegative_stage_rss_increment_deltas
        ),
        "phase04_stage_peak_rss_increment_delta_ceiling_bytes": rss_ceiling,
        "within_phase04_stage_peak_rss_increment_delta_ceiling": (
            max(paired_nonnegative_stage_rss_increment_deltas) <= rss_ceiling
        ),
        "maximum_marked_table_bytes": max(
            int(sample["maximum_marked_table_bytes"])
            for sample in flag_on_samples
        ),
        "marked_table_output_ceiling_bytes": table_output_ceiling,
        "within_marked_table_output_ceiling": all(
            int(sample["maximum_marked_table_bytes"]) <= table_output_ceiling
            for sample in flag_on_samples
        ),
        "maximum_document_sidecar_bytes": max(
            int(sample["document_sidecar_bytes"]) for sample in flag_on_samples
        ),
        "document_sidecar_output_ceiling_bytes": document_output_ceiling,
        "within_document_sidecar_output_ceiling": all(
            int(sample["document_sidecar_bytes"]) <= document_output_ceiling
            for sample in flag_on_samples
        ),
        "all_flag_off_markers_absent": all(
            sample["marked_table_count"] == 0
            and sample["maximum_marked_table_bytes"] == 0
            and sample["document_sidecar_bytes"] == 0
            for sample in flag_off_samples
        ),
        "all_flag_on_marked_tables_present": all(
            sample["marked_table_count"] > 0 for sample in flag_on_samples
        ),
        "flag_off_semantic_deterministic": len(
            {sample["semantic_json_sha256"] for sample in flag_off_samples}
        )
        == 1,
        "flag_on_semantic_deterministic": len(
            {sample["semantic_json_sha256"] for sample in flag_on_samples}
        )
        == 1,
    }


def _table_items(payload: Mapping[str, Any], physical_page: int) -> list[dict[str, Any]]:
    return [
        item
        for page in payload.get("pages", [])
        if type(page) is dict and page.get("page_index") == physical_page
        for item in page.get("items", [])
        if type(item) is dict and item.get("type") == "table"
    ]


def _one_unambiguous_table(
    payload: Mapping[str, Any], physical_page: int
) -> tuple[dict[str, Any] | None, str | None]:
    tables = _table_items(payload, physical_page)
    if len(tables) != 1:
        return None, "missing_table" if not tables else "ambiguous_table_selection"
    return tables[0], None


def _expected_rows(exact_table: Any) -> list[list[str]]:
    rows = [
        ["" for _column in range(exact_table.column_count)]
        for _row in range(exact_table.row_count)
    ]
    for cell in exact_table.cells:
        rows[cell.row][cell.column] = cell.text
    return rows


def _expected_csv(rows: Sequence[Sequence[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().rstrip("\n")


def _expected_html(exact_table: Any) -> str:
    by_position = {(cell.row, cell.column): cell for cell in exact_table.cells}
    occupied: dict[tuple[int, int], Any] = {}
    for cell in exact_table.cells:
        for row in range(cell.row, cell.row + cell.row_span):
            for column in range(cell.column, cell.column + cell.col_span):
                if (row, column) in occupied:
                    raise ValueError("expected HTML contains overlapping cells")
                occupied[(row, column)] = cell
    expected_slots = {
        (row, column)
        for row in range(exact_table.row_count)
        for column in range(exact_table.column_count)
    }
    if set(occupied) != expected_slots:
        raise ValueError("expected HTML contains uncovered slots")

    leading_header_rows = 0
    for row in range(exact_table.row_count):
        anchors = [
            cell
            for (cell_row, _column), cell in by_position.items()
            if cell_row == row
        ]
        header_count = sum(cell.column_header is True for cell in anchors)
        non_header_count = sum(cell.column_header is not True for cell in anchors)
        if header_count and not non_header_count:
            leading_header_rows += 1
        else:
            break

    lines = ["<table>"]
    for row in range(exact_table.row_count):
        if row == 0 and leading_header_rows:
            lines.append("  <thead>")
        if row == leading_header_rows:
            if leading_header_rows:
                lines.append("  </thead>")
            lines.append("  <tbody>")
        lines.append("    <tr>")
        for column in range(exact_table.column_count):
            cell = by_position.get((row, column))
            if cell is None:
                # A covered slot is represented only by its source-supported
                # anchor; emitting a fabricated duplicate would flatten spans.
                if (row, column) in occupied:
                    continue
                raise ValueError("expected HTML slot ownership differs")
            tag = "td"
            attributes = ""
            if cell.column_header is True:
                tag = "th"
                attributes += ' scope="col"'
            elif cell.row_header is True:
                tag = "th"
                attributes += ' scope="row"'
            if cell.row_span > 1:
                attributes += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                attributes += f' colspan="{cell.col_span}"'
            escaped = html.escape(cell.text, quote=True).replace(chr(10), "<br>")
            lines.append(
                f"      <{tag}{attributes}>{escaped}</{tag}>"
            )
        lines.append("    </tr>")
    if leading_header_rows == exact_table.row_count:
        lines.append("  </thead>")
    else:
        lines.append("  </tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def _bbox_matches(actual: object, expected: Any) -> bool:
    if type(actual) is not dict or set(actual) != set(NORMALIZED_BBOX_KEYS):
        return False
    tolerance = float(getattr(expected, "tolerance_pt", 0.0))
    values = {
        "x": expected.x,
        "y": expected.y,
        "width": expected.width,
        "height": expected.height,
    }
    return actual.get("unit") == "pt" and all(
        type(actual.get(field)) in (int, float)
        and type(actual.get(field)) is not bool
        and math.isfinite(float(actual[field]))
        and abs(float(actual[field]) - float(target))
        <= tolerance + NUMERIC_COMPARISON_SLACK_PT
        for field, target in values.items()
    )


def _bbox_contained_by_grid(actual: object, structural: Any) -> bool:
    if type(actual) is not dict or set(actual) != set(NORMALIZED_BBOX_KEYS):
        return False
    values = [actual.get(field) for field in ("x", "y", "width", "height")]
    if (
        actual.get("unit") != "pt"
        or any(
            type(value) not in (int, float)
            or type(value) is bool
            or not math.isfinite(float(value))
            for value in values
        )
    ):
        return False
    x, y, width, height = (float(value) for value in values)
    if width <= 0 or height <= 0:
        return False
    slack = float(getattr(structural, "tolerance_pt", 0.0))
    slack += NUMERIC_COMPARISON_SLACK_PT
    return (
        x >= float(structural.x) - slack
        and y >= float(structural.y) - slack
        and x + width <= float(structural.x) + float(structural.width) + slack
        and y + height <= float(structural.y) + float(structural.height) + slack
    )


def _bbox_role_metadata() -> dict[str, Any]:
    metadata = source_content_bbox_oracle_metadata()
    metadata["structural_oracle_semantic_sha256"] = oracle_sha256()
    metadata["comparison_slack_pt"] = NUMERIC_COMPARISON_SLACK_PT
    metadata["exact_cell_denominator"] = 30
    return metadata


def _score_exact_table(payload: Mapping[str, Any], truth: Any) -> dict[str, Any]:
    table, selection_error = _one_unambiguous_table(payload, truth.physical_page)
    if table is None:
        return {
            "oracle_id": truth.oracle_id,
            "case_id": truth.case_id,
            "selection_error": selection_error,
            "table_row_count_observed": None,
            "table_row_count_expected": truth.row_count,
            "table_column_count_observed": None,
            "table_column_count_expected": truth.column_count,
            "table_shape_matches": False,
            "cell_record_count_observed": None,
            "unique_cell_position_count_observed": 0,
            "exact_cell_numerator": 0,
            "exact_cell_denominator": truth.cell_count,
            "span_fidelity_numerator": 0,
            "span_fidelity_denominator": truth.cell_count,
            "header_fidelity_numerator": 0,
            "header_fidelity_denominator": truth.cell_count,
            "repeated_value_observed": 0,
            "repeated_value_expected": truth.repeated_value_count,
            "representation_results": {
                key: False for key in EXACT_REPRESENTATION_KEYS
            },
            "representation_numerator": 0,
            "representation_denominator": len(EXACT_REPRESENTATION_KEYS),
            "bbox_role_oracle": _bbox_role_metadata(),
            "source_content_bbox_numerator": 0,
            "source_content_bbox_denominator": truth.cell_count,
            "structural_grid_containment_numerator": 0,
            "structural_grid_containment_denominator": truth.cell_count,
            "exact_match_implied_teds": None,
            "exact_match_implied_grits": None,
            "passed": False,
        }
    row_count = table.get("row_count")
    column_count = table.get("column_count")
    row_count_observed = (
        row_count
        if type(row_count) is int
        and 1 <= row_count <= TABLE_LIMITS["maximum_rows_per_table"]
        else None
    )
    column_count_observed = (
        column_count
        if type(column_count) is int
        and 1 <= column_count <= TABLE_LIMITS["maximum_columns_per_table"]
        else None
    )
    table_shape_matches = (
        row_count_observed == truth.row_count
        and column_count_observed == truth.column_count
    )
    cells = table.get("cells")
    actual_by_position = (
        {
            (cell.get("row"), cell.get("column")): cell
            for cell in cells
            if type(cell) is dict
            and type(cell.get("row")) is int
            and type(cell.get("column")) is int
        }
        if type(cells) is list
        else {}
    )
    exact_cells = 0
    span_matches = 0
    header_matches = 0
    source_content_bbox_matches = 0
    structural_grid_containments = 0
    for expected in truth.cells:
        actual = actual_by_position.get((expected.row, expected.column))
        if type(actual) is not dict:
            continue
        content_bbox_truth = EXHIBIT7_SOURCE_CONTENT_BBOX_BY_POSITION.get(
            (expected.row, expected.column)
        )
        content_bbox_matches = (
            content_bbox_truth is not None
            and content_bbox_truth.text == expected.text
            and _bbox_matches(actual.get("bbox"), content_bbox_truth.bbox)
        )
        structural_grid_contains = _bbox_contained_by_grid(
            actual.get("bbox"), expected.bbox
        )
        span_matches_exactly = (
            type(actual.get("row_span")) is int
            and type(actual.get("col_span")) is int
            and actual["row_span"] == expected.row_span
            and actual["col_span"] == expected.col_span
        )
        headers_match_exactly = (
            actual.get("column_header") is expected.column_header
            and actual.get("row_header") is expected.row_header
        )
        span_matches += int(span_matches_exactly)
        header_matches += int(headers_match_exactly)
        source_content_bbox_matches += int(content_bbox_matches)
        structural_grid_containments += int(structural_grid_contains)
        if (
            span_matches_exactly
            and actual.get("text") == expected.text
            and headers_match_exactly
            and content_bbox_matches
            and structural_grid_contains
        ):
            exact_cells += 1
    rows = _expected_rows(truth)
    expected_html = _expected_html(truth)
    expected_csv = _expected_csv(rows)
    cell_shape_exact = (
        table_shape_matches
        and type(cells) is list
        and len(actual_by_position) == truth.cell_count
        and len(cells) == truth.cell_count
        and exact_cells == truth.cell_count
    )
    representations = {
        "rows": table.get("rows") == rows,
        "value": table.get("value") == rows,
        "cells": cell_shape_exact,
        "html": table.get("html") == expected_html,
        "markdown": table.get("md") == expected_html,
        "csv": table.get("csv") == expected_csv,
    }
    passed = (
        table_shape_matches
        and exact_cells == truth.cell_count
        and span_matches == truth.cell_count
        and header_matches == truth.cell_count
        and source_content_bbox_matches == truth.cell_count
        and structural_grid_containments == truth.cell_count
        and all(representations.values())
        and sum(
            cell.get("text") == truth.repeated_value
            for cell in actual_by_position.values()
        )
        == truth.repeated_value_count
    )
    return {
        "oracle_id": truth.oracle_id,
        "case_id": truth.case_id,
        "selection_error": None,
        "table_row_count_observed": row_count_observed,
        "table_row_count_expected": truth.row_count,
        "table_column_count_observed": column_count_observed,
        "table_column_count_expected": truth.column_count,
        "table_shape_matches": table_shape_matches,
        "cell_record_count_observed": len(cells) if type(cells) is list else None,
        "unique_cell_position_count_observed": len(actual_by_position),
        "exact_cell_numerator": exact_cells,
        "exact_cell_denominator": truth.cell_count,
        "span_fidelity_numerator": span_matches,
        "span_fidelity_denominator": truth.cell_count,
        "header_fidelity_numerator": header_matches,
        "header_fidelity_denominator": truth.cell_count,
        "repeated_value_observed": sum(
            cell.get("text") == truth.repeated_value
            for cell in actual_by_position.values()
        ),
        "repeated_value_expected": truth.repeated_value_count,
        "representation_results": representations,
        "representation_numerator": sum(representations.values()),
        "representation_denominator": len(representations),
        "bbox_role_oracle": _bbox_role_metadata(),
        "source_content_bbox_numerator": source_content_bbox_matches,
        "source_content_bbox_denominator": truth.cell_count,
        "structural_grid_containment_numerator": structural_grid_containments,
        "structural_grid_containment_denominator": truth.cell_count,
        # Exact equality of the complete source-qualified tree/grid implies a
        # normalized TEDS/GriTS score of 1.0 without approximating a partial
        # score.  Non-exact cases remain unscored rather than being called 0.
        "exact_match_implied_teds": 1.0 if passed else None,
        "exact_match_implied_grits": 1.0 if passed else None,
        "passed": passed,
    }


def _header_leaf_slot_count(table: Mapping[str, Any]) -> int | None:
    cells = table.get("cells")
    if type(cells) is not list:
        return None
    header_cells = [
        cell
        for cell in cells
        if type(cell) is dict
        and cell.get("column_header") is True
        and type(cell.get("row")) is int
        and type(cell.get("column")) is int
        and type(cell.get("col_span")) is int
    ]
    if not header_cells:
        return 0
    leaf_row = max(cell["row"] for cell in header_cells)
    slots = {
        column
        for cell in header_cells
        if cell["row"] == leaf_row
        for column in range(cell["column"], cell["column"] + cell["col_span"])
    }
    return len(slots)


def _stub_only_rows(table: Mapping[str, Any]) -> list[int] | None:
    rows = table.get("rows")
    if type(rows) is not list:
        return None
    indexes: list[int] = []
    for index, row in enumerate(rows):
        if type(row) is not list or not row:
            return None
        if str(row[0]).strip() and all(not str(value).strip() for value in row[1:]):
            indexes.append(index)
    return indexes


def _automatic_denominator_observation(
    table: Mapping[str, Any],
    denominator: Any,
    qualified: Any,
) -> tuple[int | None, tuple[int, ...], str]:
    dimension = denominator.dimension
    if dimension == "column_count":
        value = table.get("column_count")
        return (value if type(value) is int else None), (), "public_column_count"
    if dimension in {"row_count_including_header", "visual_row_count"}:
        value = table.get("row_count")
        return (value if type(value) is int else None), (), "public_row_count"
    if dimension == "cell_count":
        cells = table.get("cells")
        return (len(cells) if type(cells) is list else None), (), "explicit_cells"
    if dimension == "data_row_count":
        row_count = table.get("row_count")
        cells = table.get("cells")
        if type(row_count) is not int or type(cells) is not list:
            return None, (), "explicit_non_header_rows"
        header_rows = {
            cell.get("row")
            for cell in cells
            if type(cell) is dict and cell.get("column_header") is True
        }
        return row_count - len(header_rows), (), "explicit_non_header_rows"
    if dimension == "supported_col_span":
        cells = table.get("cells")
        if type(cells) is not list:
            return None, (), "explicit_supported_col_spans"
        span_cells = [
            cell
            for cell in cells
            if type(cell) is dict
            and type(cell.get("row")) is int
            and type(cell.get("column")) is int
            and type(cell.get("col_span")) is int
            and cell["col_span"] > 1
        ]
        span_cells.sort(key=lambda cell: (cell["row"], cell["column"]))
        members = tuple(int(cell["col_span"]) for cell in span_cells)
        return len(members), members, "explicit_supported_col_spans"
    if dimension == "supported_row_span":
        cells = table.get("cells")
        if type(cells) is not list:
            return None, (), "explicit_supported_row_spans"
        span_cells = [
            cell
            for cell in cells
            if type(cell) is dict
            and type(cell.get("row")) is int
            and type(cell.get("column")) is int
            and type(cell.get("row_span")) is int
            and cell["row_span"] > 1
        ]
        span_cells.sort(key=lambda cell: (cell["row"], cell["column"]))
        members = tuple(int(cell["row_span"]) for cell in span_cells)
        return len(members), members, "explicit_supported_row_spans"
    if dimension == "header_ownership":
        return _header_leaf_slot_count(table), (), "deepest_explicit_header_slots"
    if dimension == "stub_only_section_row_count":
        rows = _stub_only_rows(table)
        return (len(rows) if rows is not None else None), (), "explicit_stub_only_rows"
    if dimension == "false_span_count":
        rows = _stub_only_rows(table)
        cells = table.get("cells")
        if rows is None or type(cells) is not list:
            return None, (), "stub_rows_with_emitted_span"
        count = sum(
            type(cell) is dict
            and cell.get("row") in rows
            and (
                (type(cell.get("row_span")) is int and cell["row_span"] > 1)
                or (type(cell.get("col_span")) is int and cell["col_span"] > 1)
            )
            for cell in cells
        )
        return count, (), "stub_rows_with_emitted_span"
    if dimension == "row_boundary":
        rows = table.get("rows")
        if type(rows) is not list:
            return None, (), "reviewed_terminal_rows"
        terminal = [
            row
            for row in qualified.reviewed_rows
            if row.source_table_row_index == len(rows) - 1
        ]
        observed = sum(
            list(row.values) == rows[row.source_table_row_index]
            for row in terminal
            if row.source_table_row_index < len(rows)
        )
        return observed, (), "reviewed_terminal_rows"
    # In particular, logical visual wrapping cannot be inferred safely from a
    # flattened cell string.  It requires an independently retained review.
    return None, (), "independent_review_required"


def _validate_reviewed_observations(
    values: Mapping[str, Mapping[str, Any]] | None,
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    if values is None:
        return {}
    observed: dict[str, dict[str, Any]] = {}
    for denominator_id, value in values.items():
        if type(denominator_id) is not str or not denominator_id:
            raise ValueError("reviewed denominator identity is invalid")
        if type(value) is not dict or set(value) != set(REVIEWED_OBSERVATION_FIELDS):
            raise ValueError("reviewed observation fields differ")
        if value["denominator_id"] != denominator_id:
            raise ValueError("reviewed observation identity differs")
        if type(value["observed"]) is not int or value["observed"] < 0:
            raise ValueError("reviewed observation must be a nonnegative integer")
        identity = validate_file_identity(value["evidence_identity"])
        if file_identity(workspace, identity["path"]) != identity:
            raise ValueError("reviewed observation evidence identity differs")
        observed[denominator_id] = {
            "denominator_id": denominator_id,
            "observed": value["observed"],
            "evidence_identity": identity,
        }
    return observed


def _strict_bounded_integer(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    label: str,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a bounded integer")
    return value


def _validated_exact_quality_records(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if type(values) is not list:
        raise ValueError("exact table quality records must be a list")
    truth_by_id = {
        truth.oracle_id: truth for truth in P04_US01_REAL_ORACLE.exact_tables
    }
    if len(values) != len(truth_by_id):
        raise ValueError("exact table quality partition differs")
    validated_by_id: dict[str, dict[str, Any]] = {}
    for value in values:
        if type(value) is not dict or set(value) != EXACT_RESULT_FIELDS:
            raise ValueError("exact table quality fields differ")
        oracle_id = value.get("oracle_id")
        truth = truth_by_id.get(oracle_id) if type(oracle_id) is str else None
        if (
            truth is None
            or type(oracle_id) is not str
            or type(value.get("case_id")) is not str
            or value["case_id"] != truth.case_id
            or oracle_id in validated_by_id
        ):
            raise ValueError("exact table quality identity differs")
        selection_error = value.get("selection_error")
        if selection_error not in EXACT_SELECTION_ERRORS or (
            selection_error is not None and type(selection_error) is not str
        ):
            raise ValueError("exact table selection result differs")

        expected_integer_fields = {
            "table_row_count_expected": truth.row_count,
            "table_column_count_expected": truth.column_count,
            "exact_cell_denominator": truth.cell_count,
            "span_fidelity_denominator": truth.cell_count,
            "header_fidelity_denominator": truth.cell_count,
            "repeated_value_expected": truth.repeated_value_count,
            "representation_denominator": len(EXACT_REPRESENTATION_KEYS),
            "source_content_bbox_denominator": truth.cell_count,
            "structural_grid_containment_denominator": truth.cell_count,
        }
        if any(
            type(value.get(field)) is not int or value[field] != expected
            for field, expected in expected_integer_fields.items()
        ):
            raise ValueError("exact table quality denominator or expectation differs")

        row_count = value.get("table_row_count_observed")
        if row_count is not None:
            _strict_bounded_integer(
                row_count,
                minimum=1,
                maximum=TABLE_LIMITS["maximum_rows_per_table"],
                label="exact table observed row count",
            )
        column_count = value.get("table_column_count_observed")
        if column_count is not None:
            _strict_bounded_integer(
                column_count,
                minimum=1,
                maximum=TABLE_LIMITS["maximum_columns_per_table"],
                label="exact table observed column count",
            )
        shape_matches = (
            row_count == truth.row_count
            and column_count == truth.column_count
        )
        if (
            type(value.get("table_shape_matches")) is not bool
            or value["table_shape_matches"] is not shape_matches
        ):
            raise ValueError("exact table shape result differs")

        record_count = value.get("cell_record_count_observed")
        if record_count is not None:
            _strict_bounded_integer(
                record_count,
                minimum=0,
                maximum=TABLE_LIMITS["maximum_cells_per_table"],
                label="exact table cell-record count",
            )
        unique_count = _strict_bounded_integer(
            value.get("unique_cell_position_count_observed"),
            minimum=0,
            maximum=TABLE_LIMITS["maximum_cells_per_table"],
            label="exact table unique-cell-position count",
        )
        if record_count is not None and unique_count > record_count:
            raise ValueError("exact table cell-position count exceeds cell records")
        if record_count is None and unique_count != 0:
            raise ValueError("absent exact table cells retained positions")

        numerator_to_denominator = {
            "exact_cell_numerator": "exact_cell_denominator",
            "span_fidelity_numerator": "span_fidelity_denominator",
            "header_fidelity_numerator": "header_fidelity_denominator",
            "source_content_bbox_numerator": "source_content_bbox_denominator",
            "structural_grid_containment_numerator": (
                "structural_grid_containment_denominator"
            ),
        }
        for numerator_field, denominator_field in numerator_to_denominator.items():
            _strict_bounded_integer(
                value.get(numerator_field),
                minimum=0,
                maximum=value[denominator_field],
                label=f"exact table {numerator_field}",
            )
        if any(
            value["exact_cell_numerator"] > value[field]
            for field in (
                "span_fidelity_numerator",
                "header_fidelity_numerator",
                "source_content_bbox_numerator",
                "structural_grid_containment_numerator",
            )
        ):
            raise ValueError("exact cell result exceeds a required component")
        if any(
            value[field] > unique_count for field in numerator_to_denominator
        ):
            raise ValueError("exact table component exceeds observed positions")
        repeated_value_observed = _strict_bounded_integer(
            value.get("repeated_value_observed"),
            minimum=0,
            maximum=TABLE_LIMITS["maximum_cells_per_table"],
            label="exact table repeated-value observation",
        )
        if repeated_value_observed > unique_count:
            raise ValueError("exact table repetition exceeds observed positions")

        representations = value.get("representation_results")
        if (
            type(representations) is not dict
            or set(representations) != set(EXACT_REPRESENTATION_KEYS)
            or any(type(result) is not bool for result in representations.values())
        ):
            raise ValueError("exact table representation results differ")
        representation_numerator = _strict_bounded_integer(
            value.get("representation_numerator"),
            minimum=0,
            maximum=len(EXACT_REPRESENTATION_KEYS),
            label="exact table representation numerator",
        )
        if representation_numerator != sum(representations.values()):
            raise ValueError("exact table representation numerator differs")
        derived_cells_representation = (
            shape_matches
            and record_count == truth.cell_count
            and unique_count == truth.cell_count
            and value["exact_cell_numerator"] == truth.cell_count
        )
        if representations["cells"] is not derived_cells_representation:
            raise ValueError("exact table cells representation result differs")

        try:
            metadata_matches = (
                type(value.get("bbox_role_oracle")) is dict
                and _canonical_bytes(value["bbox_role_oracle"])
                == _canonical_bytes(_bbox_role_metadata())
            )
        except (TypeError, ValueError):
            metadata_matches = False
        if not metadata_matches:
            raise ValueError("exact table bbox-role oracle differs")

        if selection_error is not None and (
            row_count is not None
            or column_count is not None
            or record_count is not None
            or unique_count != 0
            or value["repeated_value_observed"] != 0
            or any(value[field] != 0 for field in numerator_to_denominator)
            or any(representations.values())
        ):
            raise ValueError("failed exact table selection retained observations")
        derived_pass = (
            selection_error is None
            and shape_matches
            and record_count == truth.cell_count
            and unique_count == truth.cell_count
            and all(
                value[numerator] == value[denominator]
                for numerator, denominator in numerator_to_denominator.items()
            )
            and value["repeated_value_observed"]
            == value["repeated_value_expected"]
            and representation_numerator == len(EXACT_REPRESENTATION_KEYS)
        )
        if type(value.get("passed")) is not bool or value["passed"] is not derived_pass:
            raise ValueError("exact table pass result differs")
        for field in ("exact_match_implied_teds", "exact_match_implied_grits"):
            expected_score = 1.0 if derived_pass else None
            if expected_score is None:
                score_matches = value.get(field) is None
            else:
                score_matches = type(value.get(field)) is float and value[field] == 1.0
            if not score_matches:
                raise ValueError("exact table implied metric differs")
        validated_by_id[oracle_id] = deepcopy(value)
    return [
        validated_by_id[truth.oracle_id]
        for truth in P04_US01_REAL_ORACLE.exact_tables
    ]


def _reviewed_observation_bound(dimension: str) -> int:
    if dimension == "column_count":
        return int(TABLE_LIMITS["maximum_columns_per_table"])
    if dimension in {
        "row_count_including_header",
        "visual_row_count",
        "data_row_count",
        "stub_only_section_row_count",
        "logical_wrapped_row_count",
        "row_boundary",
    }:
        return int(TABLE_LIMITS["maximum_rows_per_table"])
    return int(TABLE_LIMITS["maximum_cells_per_table"])


def _validated_reviewed_denominator_records(
    values: Sequence[Mapping[str, Any]],
    workspace: Path,
) -> list[dict[str, Any]]:
    if type(values) is not list:
        raise ValueError("reviewed denominator records must be a list")
    truth_records = [
        (qualified, denominator)
        for qualified in P04_US01_REAL_ORACLE.qualified_tables
        for denominator in qualified.denominators
    ]
    truth_by_id = {
        denominator.denominator_id: (qualified, denominator)
        for qualified, denominator in truth_records
    }
    if len(values) != len(truth_by_id):
        raise ValueError("reviewed denominator partition differs")
    expected_method_by_dimension = {
        "column_count": "public_column_count",
        "row_count_including_header": "public_row_count",
        "visual_row_count": "public_row_count",
        "data_row_count": "explicit_non_header_rows",
        "cell_count": "explicit_cells",
        "supported_col_span": "explicit_supported_col_spans",
        "supported_row_span": "explicit_supported_row_spans",
        "header_ownership": "deepest_explicit_header_slots",
        "stub_only_section_row_count": "explicit_stub_only_rows",
        "false_span_count": "stub_rows_with_emitted_span",
        "row_boundary": "reviewed_terminal_rows",
        "logical_wrapped_row_count": "independent_review_required",
    }
    validated_by_id: dict[str, dict[str, Any]] = {}
    for value in values:
        if (
            type(value) is not dict
            or set(value) != REVIEWED_DENOMINATOR_RESULT_FIELDS
        ):
            raise ValueError("reviewed denominator fields differ")
        denominator_id = value.get("denominator_id")
        truth_record = (
            truth_by_id.get(denominator_id)
            if type(denominator_id) is str
            else None
        )
        if (
            truth_record is None
            or type(denominator_id) is not str
            or denominator_id in validated_by_id
        ):
            raise ValueError("reviewed denominator identity differs")
        qualified, denominator = truth_record
        expected_values = {
            "oracle_id": qualified.oracle_id,
            "case_id": qualified.case_id,
            "physical_page": qualified.physical_page,
            "dimension": denominator.dimension,
            "expected": denominator.expected,
            "members": list(denominator.members),
            "accuracy_denominator_inclusion": (
                qualified.review_state == "source_qualified"
            ),
        }
        for field, expected in expected_values.items():
            if value.get(field) != expected or type(value.get(field)) is not type(expected):
                raise ValueError("reviewed denominator frozen truth differs")
        if type(value.get("members")) is not list or any(
            type(member) is not int for member in value["members"]
        ):
            raise ValueError("reviewed denominator members differ")
        selection_error = value.get("selection_error")
        if selection_error not in EXACT_SELECTION_ERRORS or (
            selection_error is not None and type(selection_error) is not str
        ):
            raise ValueError("reviewed denominator selection result differs")
        observed = value.get("observed")
        if observed is not None:
            _strict_bounded_integer(
                observed,
                minimum=0,
                maximum=_reviewed_observation_bound(denominator.dimension),
                label="reviewed denominator observation",
            )
        observed_members = value.get("observed_members")
        if type(observed_members) is not list or any(
            type(member) is not int or member < 1
            for member in observed_members
        ):
            raise ValueError("reviewed denominator observed members differ")
        if len(observed_members) > TABLE_LIMITS["maximum_cells_per_table"]:
            raise ValueError("reviewed denominator observed members exceed limits")
        if denominator.dimension == "supported_col_span":
            member_bound = TABLE_LIMITS["maximum_columns_per_table"]
        else:
            member_bound = TABLE_LIMITS["maximum_rows_per_table"]
        if any(member > member_bound for member in observed_members):
            raise ValueError("reviewed denominator observed member exceeds limits")
        if not denominator.members and observed_members:
            raise ValueError("reviewed denominator retained unexpected members")
        if observed is None and observed_members:
            raise ValueError("unobserved denominator retained members")
        if (
            denominator.dimension in {"supported_col_span", "supported_row_span"}
            and observed is not None
            and observed != len(observed_members)
        ):
            raise ValueError("reviewed denominator observation/member count differs")

        method = value.get("observation_method")
        if type(method) is not str:
            raise ValueError("reviewed denominator observation method differs")
        identity = value.get("review_evidence_identity")
        if qualified.review_state == "unresolved":
            if (
                method != "observation_only_unresolved_candidate"
                or observed is not None
                or observed_members
                or identity is not None
                or value.get("passed") is not None
            ):
                raise ValueError("unresolved denominator result differs")
            validated_by_id[denominator_id] = deepcopy(value)
            continue

        expected_method = expected_method_by_dimension.get(denominator.dimension)
        allowed_method = expected_method
        if selection_error is not None:
            allowed_method = "table_selection_failed"
        if method == "independently_reviewed_observation":
            if denominator.dimension != "logical_wrapped_row_count":
                raise ValueError("review evidence targets a mechanical denominator")
            reviewed_identity = validate_file_identity(identity)
            if (
                reviewed_identity["path"] != qualified.evidence_path
                or file_identity(workspace, reviewed_identity["path"])
                != reviewed_identity
            ):
                raise ValueError("reviewed denominator evidence identity differs")
            if observed is None or observed_members:
                raise ValueError("reviewed denominator manual observation differs")
        else:
            if identity is not None or method != allowed_method:
                raise ValueError("reviewed denominator observation method differs")
            if method in {"independent_review_required", "table_selection_failed"}:
                if observed is not None or observed_members:
                    raise ValueError("pending denominator retained an observation")
        derived_pass = (
            observed is not None
            and observed == denominator.expected
            and (
                not denominator.members
                or tuple(observed_members) == denominator.members
            )
        )
        if type(value.get("passed")) is not bool or value["passed"] is not derived_pass:
            raise ValueError("reviewed denominator pass result differs")
        validated_by_id[denominator_id] = deepcopy(value)
    return [
        validated_by_id[denominator.denominator_id]
        for _qualified, denominator in truth_records
    ]


def _validated_unresolved_exclusion_records(
    values: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if type(values) is not list:
        raise ValueError("unresolved exclusion records must be a list")
    truth_records = [
        (qualified, concern)
        for qualified in P04_US01_REAL_ORACLE.qualified_tables
        for concern in qualified.required_concerns
    ]
    truth_by_key = {
        (qualified.oracle_id, concern.dimension): (qualified, concern)
        for qualified, concern in truth_records
    }
    if len(values) != len(truth_by_key):
        raise ValueError("unresolved exclusion partition differs")
    validated_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    codes_by_oracle: dict[str, tuple[str, ...]] = {}
    for value in values:
        if (
            type(value) is not dict
            or set(value) != UNRESOLVED_EXCLUSION_RESULT_FIELDS
        ):
            raise ValueError("unresolved exclusion fields differ")
        oracle_id = value.get("oracle_id")
        dimension = value.get("dimension")
        if type(oracle_id) is not str or type(dimension) is not str:
            raise ValueError("unresolved exclusion identity differs")
        key = (oracle_id, dimension)
        truth_record = truth_by_key.get(key)
        if truth_record is None or key in validated_by_key:
            raise ValueError("unresolved exclusion identity differs")
        qualified, concern = truth_record
        expected_values = {
            "oracle_id": qualified.oracle_id,
            "case_id": qualified.case_id,
            "physical_page": qualified.physical_page,
            "dimension": concern.dimension,
            "required_concern": concern.code,
            "accuracy_denominator_inclusion": False,
            "reason": "source_truth_unresolved",
        }
        for field, expected in expected_values.items():
            if value.get(field) != expected or type(value.get(field)) is not type(expected):
                raise ValueError("unresolved exclusion frozen truth differs")
        codes = value.get("observed_concern_codes")
        if (
            type(codes) is not list
            or any(type(code) is not str or code not in CONCERN_CODES for code in codes)
            or codes != sorted(set(codes))
            or len(codes) > TABLE_LIMITS["maximum_concerns_per_table"]
        ):
            raise ValueError("unresolved exclusion observed concerns differ")
        prior_codes = codes_by_oracle.setdefault(qualified.oracle_id, tuple(codes))
        if tuple(codes) != prior_codes:
            raise ValueError("unresolved exclusion concern presence is inconsistent")
        derived_observed = concern.code in codes
        if (
            type(value.get("concern_observed")) is not bool
            or value["concern_observed"] is not derived_observed
        ):
            raise ValueError("unresolved exclusion concern result differs")
        validated_by_key[key] = deepcopy(value)
    return [
        validated_by_key[(qualified.oracle_id, concern.dimension)]
        for qualified, concern in truth_records
    ]


def score_quality(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    reviewed_observations: Mapping[str, Mapping[str, Any]] | None = None,
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    """Score only the frozen exact/source-qualified oracle dimensions."""

    reviewed = _validate_reviewed_observations(reviewed_observations, workspace)
    independently_reviewed_ids = {
        denominator.denominator_id
        for qualified in P04_US01_REAL_ORACLE.qualified_tables
        if qualified.review_state == "source_qualified"
        for denominator in qualified.denominators
        if denominator.dimension == "logical_wrapped_row_count"
    }
    if not set(reviewed) <= independently_reviewed_ids:
        raise ValueError(
            "reviewed observations may only fill nonmechanical frozen denominators"
        )
    unexpected_cases = set(payloads) - set(QUALITY_CASES)
    if unexpected_cases:
        raise ValueError(f"quality payload contains unknown cases: {sorted(unexpected_cases)}")
    exact_results = [
        _score_exact_table(payloads.get(truth.case_id, {}), truth)
        for truth in P04_US01_REAL_ORACLE.exact_tables
    ]
    denominator_results: list[dict[str, Any]] = []
    unresolved_exclusions: list[dict[str, Any]] = []
    for qualified in P04_US01_REAL_ORACLE.qualified_tables:
        payload = payloads.get(qualified.case_id, {})
        table, selection_error = _one_unambiguous_table(
            payload, qualified.physical_page
        )
        sidecar = table.get("table_evidence") if table is not None else None
        concerns = (
            sidecar.get("concerns", []) if type(sidecar) is dict else []
        )
        observed_concern_codes = sorted(
            {
                code
                for code in concerns
                if type(code) is str and code in CONCERN_CODES
            }
        )
        for concern in qualified.required_concerns:
            unresolved_exclusions.append(
                {
                    "oracle_id": qualified.oracle_id,
                    "case_id": qualified.case_id,
                    "physical_page": qualified.physical_page,
                    "dimension": concern.dimension,
                    "required_concern": concern.code,
                    "observed_concern_codes": list(observed_concern_codes),
                    "concern_observed": concern.code in observed_concern_codes,
                    "accuracy_denominator_inclusion": False,
                    "reason": "source_truth_unresolved",
                }
            )
        for denominator in qualified.denominators:
            if qualified.review_state == "unresolved":
                denominator_results.append(
                    {
                        "oracle_id": qualified.oracle_id,
                        "case_id": qualified.case_id,
                        "physical_page": qualified.physical_page,
                        "denominator_id": denominator.denominator_id,
                        "dimension": denominator.dimension,
                        "expected": denominator.expected,
                        "members": list(denominator.members),
                        "observed": None,
                        "observed_members": [],
                        "observation_method": "observation_only_unresolved_candidate",
                        "review_evidence_identity": None,
                        "selection_error": selection_error,
                        "accuracy_denominator_inclusion": False,
                        "passed": None,
                    }
                )
                continue
            if table is None:
                observed, members, method = None, (), "table_selection_failed"
            else:
                observed, members, method = _automatic_denominator_observation(
                    table, denominator, qualified
                )
            evidence_identity = None
            if observed is None and denominator.denominator_id in reviewed:
                record = reviewed[denominator.denominator_id]
                observed = record["observed"]
                evidence_identity = record["evidence_identity"]
                method = "independently_reviewed_observation"
            passed = (
                observed == denominator.expected
                and (not denominator.members or tuple(members) == denominator.members)
            ) if observed is not None else False
            denominator_results.append(
                {
                    "oracle_id": qualified.oracle_id,
                    "case_id": qualified.case_id,
                    "physical_page": qualified.physical_page,
                    "denominator_id": denominator.denominator_id,
                    "dimension": denominator.dimension,
                    "expected": denominator.expected,
                    "members": list(denominator.members),
                    "observed": observed,
                    "observed_members": list(members),
                    "observation_method": method,
                    "review_evidence_identity": evidence_identity,
                    "selection_error": selection_error,
                    "accuracy_denominator_inclusion": True,
                    "passed": passed,
                }
            )
    return _quality_summary(
        exact_results,
        denominator_results,
        unresolved_exclusions,
        workspace=workspace,
    )


def _quality_summary(
    exact_results: Sequence[Mapping[str, Any]],
    denominator_results: Sequence[Mapping[str, Any]],
    unresolved_exclusions: Sequence[Mapping[str, Any]],
    *,
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    exact_records = _validated_exact_quality_records(exact_results)
    denominator_records = _validated_reviewed_denominator_records(
        denominator_results,
        workspace,
    )
    exclusion_records = _validated_unresolved_exclusion_records(
        unresolved_exclusions
    )
    eligible = [
        record
        for record in denominator_records
        if record["accuracy_denominator_inclusion"]
    ]
    exact_cell_numerator = sum(
        record["exact_cell_numerator"] for record in exact_records
    )
    exact_cell_denominator = sum(
        record["exact_cell_denominator"] for record in exact_records
    )
    representation_numerator = sum(
        record["representation_numerator"] for record in exact_records
    )
    representation_denominator = sum(
        record["representation_denominator"] for record in exact_records
    )
    return {
        "oracle": {
            "policy_id": P04_US01_REAL_ORACLE.policy_id,
            "story_id": P04_US01_REAL_ORACLE.story_id,
            "semantic_sha256": oracle_sha256(),
            "bbox_role_oracle": _bbox_role_metadata(),
            "source_case_count": len(P04_US01_REAL_ORACLE.sources),
            "exact_table_count": len(P04_US01_REAL_ORACLE.exact_tables),
            "qualified_table_count": len(P04_US01_REAL_ORACLE.qualified_tables),
        },
        "exact_tables": exact_records,
        "reviewed_denominators": denominator_records,
        "unresolved_exclusions": exclusion_records,
        "exact_cell_numerator": exact_cell_numerator,
        "exact_cell_denominator": exact_cell_denominator,
        "exact_cell_accuracy": (
            exact_cell_numerator / exact_cell_denominator
            if exact_cell_denominator
            else 0.0
        ),
        "representation_numerator": representation_numerator,
        "representation_denominator": representation_denominator,
        "representation_accuracy": (
            representation_numerator / representation_denominator
            if representation_denominator
            else 0.0
        ),
        "exact_match_implied_teds": (
            1.0
            if exact_records
            and all(
                record["exact_match_implied_teds"] == 1.0
                for record in exact_records
            )
            else None
        ),
        "exact_match_implied_grits": (
            1.0
            if exact_records
            and all(
                record["exact_match_implied_grits"] == 1.0
                for record in exact_records
            )
            else None
        ),
        "reviewed_dimension_numerator": sum(record["passed"] is True for record in eligible),
        "reviewed_dimension_denominator": len(eligible),
        "required_concern_numerator": sum(
            record["concern_observed"] is True for record in exclusion_records
        ),
        "required_concern_denominator": len(exclusion_records),
        "all_required_concerns_observed": bool(exclusion_records)
        and all(record["concern_observed"] is True for record in exclusion_records),
        "pending_independent_review_denominator_ids": sorted(
            record["denominator_id"]
            for record in eligible
            if record["observed"] is None
        ),
        "all_exact_and_reviewed_dimensions_passed": bool(exact_records)
        and all(record["passed"] for record in exact_records)
        and bool(eligible)
        and all(record["passed"] is True for record in eligible)
        and bool(exclusion_records)
        and all(
            record["concern_observed"] is True
            for record in exclusion_records
        ),
    }


def _validate_worker_quality(
    value: Any,
    workspace: Path = WORKSPACE,
    *,
    case_id: str | None = None,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != QUALITY_SUMMARY_FIELDS:
        raise ValueError("isolated worker quality fields differ")
    rebuilt = _quality_summary(
        value.get("exact_tables"),
        value.get("reviewed_denominators"),
        value.get("unresolved_exclusions"),
        workspace=workspace,
    )
    try:
        summary_matches = _canonical_bytes(value) == _canonical_bytes(rebuilt)
    except (TypeError, ValueError):
        summary_matches = False
    if not summary_matches:
        raise ValueError("isolated worker quality summary differs")
    if case_id is not None:
        if case_id not in QUALITY_CASES:
            raise ValueError("isolated worker quality case differs")
        if any(
            record["observation_method"]
            == "independently_reviewed_observation"
            for record in rebuilt["reviewed_denominators"]
        ):
            raise ValueError(
                "isolated worker cannot retain an independent review"
            )
        neutral = quality_denominator_manifest()
        for field in (
            "exact_tables",
            "reviewed_denominators",
            "unresolved_exclusions",
        ):
            nonowned = [
                record for record in rebuilt[field] if record["case_id"] != case_id
            ]
            expected_nonowned = [
                record for record in neutral[field] if record["case_id"] != case_id
            ]
            if _canonical_bytes(nonowned) != _canonical_bytes(expected_nonowned):
                raise ValueError("isolated worker retained nonowned quality evidence")
    return deepcopy(value)


def merge_isolated_quality(
    snapshots: Mapping[str, Mapping[str, Any]],
    *,
    reviewed_observations: Mapping[str, Mapping[str, Any]] | None = None,
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    """Merge exactly one enabled isolated quality snapshot per reviewed case."""

    if set(snapshots) != set(QUALITY_CASES):
        raise ValueError("isolated quality requires all six reviewed cases")
    reviewed = _validate_reviewed_observations(reviewed_observations, workspace)
    exact_results: list[dict[str, Any]] = []
    denominator_results: list[dict[str, Any]] = []
    unresolved_exclusions: list[dict[str, Any]] = []
    for case_id in QUALITY_CASES:
        snapshot = snapshots[case_id]
        _validate_snapshot(snapshot, case_id=case_id, enabled=True)
        quality = _validate_worker_quality(
            snapshot.get("quality"),
            workspace,
            case_id=case_id,
        )
        exact_results.extend(
            dict(record)
            for record in quality.get("exact_tables", [])
            if type(record) is dict and record.get("case_id") == case_id
        )
        denominator_results.extend(
            dict(record)
            for record in quality.get("reviewed_denominators", [])
            if type(record) is dict and record.get("case_id") == case_id
        )
        unresolved_exclusions.extend(
            dict(record)
            for record in quality.get("unresolved_exclusions", [])
            if type(record) is dict and record.get("case_id") == case_id
        )
    known_manual_ids = {
        record["denominator_id"]
        for record in denominator_results
        if record.get("observation_method") == "independent_review_required"
    }
    if not set(reviewed) <= known_manual_ids:
        raise ValueError("reviewed observation does not match a pending denominator")
    for record in denominator_results:
        reviewed_record = reviewed.get(record["denominator_id"])
        if reviewed_record is None:
            continue
        record["observed"] = reviewed_record["observed"]
        record["observation_method"] = "independently_reviewed_observation"
        record["review_evidence_identity"] = reviewed_record["evidence_identity"]
        record["passed"] = reviewed_record["observed"] == record["expected"]
    return _quality_summary(
        exact_results,
        denominator_results,
        unresolved_exclusions,
        workspace=workspace,
    )


def quality_denominator_manifest() -> dict[str, Any]:
    """Expose the frozen denominator partition without inventing observations."""

    return score_quality({})


def _stable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    stable = deepcopy(dict(payload))
    processing = stable.get("processing")
    if type(processing) is dict:
        processing.pop("duration_ms", None)
        for summary_name in ("form_semantics", "outline_structure"):
            summary = processing.get(summary_name)
            if type(summary) is dict:
                for key in ("extraction_ms", "projection_ms", "total_ms"):
                    summary.pop(key, None)
    return stable


def _sidecar_sizes(payload: Mapping[str, Any]) -> tuple[int, int, int, dict[str, int]]:
    """Measure full marked-table output and aggregate sidecars separately."""

    marked_table_sizes: list[int] = []
    sidecar_sizes: list[int] = []
    statuses: dict[str, int] = {}
    for page in payload.get("pages", []):
        if type(page) is not dict:
            continue
        for item in page.get("items", []):
            if type(item) is not dict or item.get("type") != "table":
                continue
            sidecar = item.get("table_evidence")
            if type(sidecar) is not dict:
                continue
            marked_table_sizes.append(len(_canonical_bytes(item)))
            sidecar_sizes.append(len(_canonical_bytes(sidecar)))
            status = sidecar.get("status")
            label = status if type(status) is str else "invalid"
            statuses[label] = statuses.get(label, 0) + 1
    return (
        len(marked_table_sizes),
        max(marked_table_sizes, default=0),
        sum(sidecar_sizes),
        statuses,
    )


def _phase04_stage_thread_qos_record() -> dict[str, Any]:
    """Set and verify the current observer thread's bounded Darwin QoS."""

    record: dict[str, Any] = {
        "policy": PHASE04_STAGE_THREAD_QOS_POLICY,
        "platform": sys.platform,
        "requested_class_name": PHASE04_STAGE_DARWIN_QOS_CLASS_NAME,
        "requested_class_value": PHASE04_STAGE_DARWIN_QOS_CLASS,
        "requested_relative_priority": (
            PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY
        ),
        "applied": False,
        "observed_class_value": None,
        "observed_relative_priority": None,
    }
    if sys.platform != "darwin":
        return record
    try:
        import ctypes

        library = ctypes.CDLL(None)
        set_qos = library.pthread_set_qos_class_self_np
        set_qos.argtypes = [ctypes.c_uint, ctypes.c_int]
        set_qos.restype = ctypes.c_int
        pthread_self = library.pthread_self
        pthread_self.argtypes = []
        pthread_self.restype = ctypes.c_void_p
        get_qos = library.pthread_get_qos_class_np
        get_qos.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_int),
        ]
        get_qos.restype = ctypes.c_int
        set_result = set_qos(
            PHASE04_STAGE_DARWIN_QOS_CLASS,
            PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY,
        )
        observed_class = ctypes.c_uint()
        observed_relative_priority = ctypes.c_int()
        get_result = get_qos(
            pthread_self(),
            ctypes.byref(observed_class),
            ctypes.byref(observed_relative_priority),
        )
    except Exception as error:
        raise RuntimeError(
            "Phase04-stage observer thread QoS setup failed "
            f"error_type={type(error).__name__}"
        ) from None
    if (
        set_result != 0
        or get_result != 0
        or observed_class.value != PHASE04_STAGE_DARWIN_QOS_CLASS
        or observed_relative_priority.value
        != PHASE04_STAGE_DARWIN_QOS_RELATIVE_PRIORITY
    ):
        raise RuntimeError("Phase04-stage observer thread QoS differs")
    record.update(
        {
            "applied": True,
            "observed_class_value": observed_class.value,
            "observed_relative_priority": observed_relative_priority.value,
        }
    )
    return record


class _Phase04StageSamplerFailure(RuntimeError):
    """Carry bounded controller evidence without exposing private details."""

    def __init__(
        self,
        message: str,
        *,
        cause_code: str,
        observed_gap_ns: int | None = None,
        hard_gap_ns: int | None = None,
    ) -> None:
        super().__init__(message)
        if (
            type(cause_code) is not str
            or not cause_code
            or len(cause_code) > 128
            or not re.fullmatch(r"[a-z0-9_]+", cause_code)
            or (
                observed_gap_ns is not None
                and (type(observed_gap_ns) is not int or observed_gap_ns < 0)
            )
            or (
                hard_gap_ns is not None
                and (type(hard_gap_ns) is not int or hard_gap_ns < 0)
            )
        ):
            raise ValueError("Phase04-stage sampler failure evidence differs")
        self.cause_code = cause_code
        self.observed_gap_ns = observed_gap_ns
        self.hard_gap_ns = hard_gap_ns


class _Phase04StageRSSSampler:
    """Measure RSS and live descendants in independent fail-closed lanes."""

    def __init__(
        self,
        *,
        process: Any | None = None,
        source_version: str | None = None,
        clock_ns: Any | None = None,
        hwm_reader: Any | None = None,
        children_rusage_reader: Any | None = None,
        external_target: bool = False,
        current_rss_lane: rss_lane.CurrentRSSLaneProcess | None = None,
    ) -> None:
        if type(external_target) is not bool:
            raise ValueError("Phase04-stage external-target mode differs")
        if current_rss_lane is not None and not external_target:
            raise ValueError("Phase04-stage current-RSS lane mode differs")
        if process is None:
            if external_target:
                raise ValueError("Phase04-stage external target is absent")
            import psutil

            process = psutil.Process(os.getpid())
            source_version = _current_rss_source_version()
        if source_version != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION:
            raise ValueError("Phase04-stage RSS source version differs")
        self._process = process
        self._source_version = source_version
        self._clock_ns = clock_ns or time.monotonic_ns
        self._hwm_reader = hwm_reader or _rss_bytes
        self._children_rusage_reader = (
            children_rusage_reader or _children_rusage_fingerprint
        )
        self._external_target = external_target
        self._current_rss_lane = current_rss_lane
        self._current_lane_summary: dict[str, Any] | None = None
        self._current_lane_qualification: dict[str, Any] | None = None
        self._current_lane_end_bytes: int | None = None
        self._current_lane_transaction_issued_count = 0
        self._current_lane_transaction_completed_count = 0
        self._current_lane_active_transaction: dict[str, Any] | None = None
        self._current_lane_first_failed_transaction: dict[str, Any] | None = None
        self._worker_pid = getattr(process, "pid", None)
        if type(self._worker_pid) is not int or self._worker_pid < 1:
            raise ValueError("Phase04-stage RSS worker identity differs")
        if getattr(process, "pid", None) != self._worker_pid:
            raise ValueError("Phase04-stage RSS process identity differs")
        if not external_target and self._worker_pid != os.getpid():
            raise ValueError("Phase04-stage RSS process identity differs")
        create_time = process.create_time()
        if (
            type(create_time) not in (int, float)
            or type(create_time) is bool
            or not math.isfinite(float(create_time))
            or create_time <= 0
        ):
            raise ValueError("Phase04-stage process-create identity differs")
        self._process_create_time_ns = int(round(float(create_time) * 1e9))
        # The sampler records fail-closed errors from code which can raise
        # while already inside this lock; reentrancy prevents that cleanup
        # path from deadlocking the worker.
        self._lock = threading.RLock()
        self._rss_progress = threading.Condition(self._lock)
        self._child_scan_lock = threading.Lock()
        self._child_scan_queue = threading.Condition()
        self._child_scan_waiters: deque[object] = deque()
        self._rss_progress_request_generation = 0
        self._rss_progress_completed_generation = 0
        self._rss_handoff_request = threading.Event()
        self._rss_prepared_ready = threading.Event()
        self._child_prepared_ready = threading.Event()
        self._arm = threading.Event()
        self._first_async_ready = threading.Event()
        self._first_child_observer_ready = threading.Event()
        self._stop = threading.Event()
        self._rss_thread: threading.Thread | None = None
        self._child_thread: threading.Thread | None = None
        self._rss_thread_qos_record: dict[str, Any] | None = None
        self._child_thread_qos_record: dict[str, Any] | None = None
        # Retain the private alias used by older non-retained diagnostics.
        self._thread: threading.Thread | None = None
        self._sampler_error_type: str | None = None
        self._sampler_error_lane: str | None = None
        self._sampler_error_cause_code: str | None = None
        self._sampler_error_observed_gap_ns: int | None = None
        self._sampler_error_hard_gap_ns: int | None = None
        self._sampler_error_accepted_continuous_count: int | None = None
        self._sampler_error_last_accepted_async_ns: int | None = None
        self._sampler_error_classified_lane_failure: dict[str, Any] | None = None
        self._child_observer_error_type: str | None = None
        self._prepared = False
        self._started = False
        self._ended = False
        self._first_boundary_component: str | None = None
        self._started_ns: int | None = None
        self._ended_ns: int | None = None
        self._last_sample_ns: int | None = None
        self._maximum_async_gap_ns = 0
        self._current_baseline_bytes: int | None = None
        self._current_peak_bytes: int | None = None
        self._current_end_bytes: int | None = None
        self._hwm_baseline_bytes: int | None = None
        self._hwm_end_bytes: int | None = None
        self._children_rusage_baseline: dict[str, Any] | None = None
        self._children_rusage_end: dict[str, Any] | None = None
        self._parse_checkpoint_ns: int | None = None
        self._parse_current_peak_bytes: int | None = None
        self._parse_current_end_bytes: int | None = None
        self._parse_hwm_end_bytes: int | None = None
        self._sample_count = 0
        self._continuous_sample_count = 0
        self._synchronous_sample_count = 0
        self._output_synchronous_boundary_count = 0
        self._first_async_ns: int | None = None
        self._last_async_ns: int | None = None
        self._first_child_observer_ns: int | None = None
        self._last_child_observer_ns: int | None = None
        self._child_observer_maximum_gap_ns = 0
        self._child_observer_sample_count = 0
        self._child_boundary_check_count = 0

    def _call_current_rss_lane(self, operation: str, callback: Any) -> Any:
        """Track a bounded lane request even when no response can be retained."""

        lane = self._current_rss_lane
        if lane is None or operation not in rss_lane.OPERATIONS:
            raise RuntimeError("Phase04-stage current-RSS lane operation differs")
        with self._lock:
            if self._current_lane_active_transaction is not None:
                raise RuntimeError(
                    "Phase04-stage current-RSS lane transaction overlapped"
                )
            self._current_lane_transaction_issued_count += 1
            transaction = {
                "sequence": self._current_lane_transaction_issued_count,
                "operation": operation,
            }
            self._current_lane_active_transaction = transaction
            completed_before = len(getattr(lane, "_duplex", ()))
        try:
            result = callback()
        except BaseException:
            completed_after = len(getattr(lane, "_duplex", ()))
            committed = completed_after == completed_before + 1
            failed = {
                **transaction,
                "state": (
                    "committed_error_response"
                    if committed and lane.failure_summary is not None
                    else (
                        "committed_invalid_response"
                        if committed
                        else "request_in_flight_or_partial"
                    )
                ),
                "completed_exchange_count_before": completed_before,
                "completed_exchange_count_after": completed_after,
            }
            with self._lock:
                if committed:
                    self._current_lane_transaction_completed_count += 1
                if self._current_lane_first_failed_transaction is None:
                    self._current_lane_first_failed_transaction = failed
                self._current_lane_active_transaction = None
            raise
        else:
            completed_after = len(getattr(lane, "_duplex", ()))
            if completed_after != completed_before + 1:
                with self._lock:
                    self._current_lane_active_transaction = None
                raise RuntimeError(
                    "Phase04-stage current-RSS lane transaction custody differs"
                )
            with self._lock:
                self._current_lane_transaction_completed_count += 1
                self._current_lane_active_transaction = None
            return result

    @staticmethod
    def _nonnegative_int(value: Any, *, label: str) -> int:
        if type(value) is not int or value < 0:
            raise RuntimeError(f"Phase04-stage RSS {label} differs")
        return value

    def _validate_process_identity(self) -> None:
        if not self._external_target and os.getpid() != self._worker_pid:
            raise RuntimeError("Phase04-stage RSS worker identity changed")
        if getattr(self._process, "pid", None) != self._worker_pid:
            raise RuntimeError("Phase04-stage RSS process identity changed")
        create_time = self._process.create_time()
        if (
            type(create_time) not in (int, float)
            or type(create_time) is bool
            or not math.isfinite(float(create_time))
            or int(round(float(create_time) * 1e9))
            != self._process_create_time_ns
        ):
            raise RuntimeError("Phase04-stage process-create identity changed")

    def _read_current_rss(self) -> int:
        """Read only identity and current RSS; never enumerate children."""

        self._validate_process_identity()
        if self._current_rss_lane is not None:
            record = self._call_current_rss_lane(
                "READ",
                self._current_rss_lane.read_current,
            )
            if (
                type(record) is not dict
                or set(record)
                != {
                    "rss_bytes",
                    "observed_monotonic_ns",
                    "lease_identity_sha256",
                }
                or type(record.get("rss_bytes")) is not int
                or record["rss_bytes"] < 0
                or type(record.get("observed_monotonic_ns")) is not int
                or record["observed_monotonic_ns"] < 0
                or self._current_lane_qualification is None
                or record.get("lease_identity_sha256")
                != self._current_lane_qualification.get(
                    "lease_identity_sha256"
                )
            ):
                raise RuntimeError("Phase04-stage current-RSS lane read differs")
            return record["rss_bytes"]
        memory = self._process.memory_info()
        return self._nonnegative_int(
            getattr(memory, "rss", None),
            label="current value",
        )

    def _observe_no_recursive_children_unserialized(self) -> None:
        """Perform exactly one live-recursive-child observation."""

        self._validate_process_identity()
        if self._process.children(recursive=True):
            raise RuntimeError("Phase04-stage RSS child process observed")

    def _record_current_lane_failure(self, error: BaseException) -> None:
        summary = (
            error.failure_summary
            if isinstance(error, rss_lane.LaneOperationError)
            else (
                self._current_rss_lane.failure_summary
                if self._current_rss_lane is not None
                else None
            )
        )
        if type(summary) is dict:
            try:
                validated = rss_lane.validate_failure_summary(summary)
            except Exception:
                validated = None
            if validated is not None:
                with self._rss_progress:
                    if self._sampler_error_type is None:
                        self._sampler_error_type = validated["error_type"]
                        self._sampler_error_lane = validated["lane"]
                        self._sampler_error_cause_code = validated["cause_code"]
                        self._sampler_error_observed_gap_ns = validated[
                            "observed_gap_ns"
                        ]
                        self._sampler_error_hard_gap_ns = validated["hard_gap_ns"]
                        self._sampler_error_accepted_continuous_count = validated[
                            "accepted_continuous_count"
                        ]
                        self._sampler_error_last_accepted_async_ns = validated[
                            "last_accepted_async_ns"
                        ]
                        self._sampler_error_classified_lane_failure = deepcopy(
                            validated
                        )
                    self._stop.set()
                    self._arm.set()
                    self._rss_progress.notify_all()
                with self._child_scan_queue:
                    self._child_scan_queue.notify_all()
                self._first_async_ready.set()
                self._first_child_observer_ready.set()
                return
        self._record_sampler_error(error, lane="current_rss")

    def _merge_current_lane_summary_locked(
        self,
        value: Mapping[str, Any],
        *,
        minimum_generation: int = 0,
    ) -> None:
        summary = (
            rss_lane.validate_compact_summary(value)
            if value.get("schema_id") == rss_lane.COMPACT_SUMMARY_SCHEMA_ID
            else rss_lane.validate_summary(value)
        )
        expected_identity = {
            "worker_pid": self._worker_pid,
            "process_create_time_ns": self._process_create_time_ns,
            "source_version": self._source_version,
            "platform": sys.platform,
        }
        previous = self._current_lane_summary
        if (
            summary["worker_identity"] != expected_identity
            or self._started_ns is None
            or summary["started_monotonic_ns"] != self._started_ns
            or self._current_baseline_bytes is None
            or summary["current_baseline_bytes"] != self._current_baseline_bytes
            or summary["completed_generation"] < minimum_generation
            or summary.get("failure_summary") is not None
        ):
            raise RuntimeError("Phase04-stage current-RSS lane summary differs")
        if previous is not None and (
            summary["started_monotonic_ns"]
            != previous["started_monotonic_ns"]
            or summary["first_async_monotonic_ns"]
            != previous["first_async_monotonic_ns"]
            or summary["continuous_sample_count"]
            < previous["continuous_sample_count"]
            or summary["last_async_monotonic_ns"]
            < previous["last_async_monotonic_ns"]
            or summary["maximum_gap_ns"] < previous["maximum_gap_ns"]
            or summary["maximum_scheduler_delay_ns"]
            < previous["maximum_scheduler_delay_ns"]
            or summary["maximum_sampling_call_duration_ns"]
            < previous["maximum_sampling_call_duration_ns"]
            or summary["current_peak_bytes"] < previous["current_peak_bytes"]
            or summary["completed_generation"]
            < previous["completed_generation"]
        ):
            raise RuntimeError("Phase04-stage current-RSS lane regressed")
        self._current_lane_summary = deepcopy(summary)
        self._current_lane_end_bytes = summary["current_end_bytes"]
        self._current_peak_bytes = max(
            int(self._current_peak_bytes),
            summary["current_peak_bytes"],
        )
        self._continuous_sample_count = summary["continuous_sample_count"]
        self._sample_count = (
            self._synchronous_sample_count + self._continuous_sample_count
        )
        self._first_async_ns = summary["first_async_monotonic_ns"]
        self._last_async_ns = summary["last_async_monotonic_ns"]
        self._maximum_async_gap_ns = summary["maximum_gap_ns"]
        self._rss_progress_completed_generation = summary[
            "completed_generation"
        ]
        self._last_sample_ns = max(
            int(self._last_sample_ns),
            summary["last_async_monotonic_ns"],
        )
        self._first_async_ready.set()

    def _request_rss_progress(self) -> int | None:
        """Require a read which begins after this exact request generation."""

        if self._current_rss_lane is not None:
            with self._rss_progress:
                self._raise_sampler_error_locked()
                if self._stop.is_set() or self._ended:
                    return None
                self._rss_progress_request_generation += 1
                request_generation = self._rss_progress_request_generation
            try:
                summary = self._call_current_rss_lane(
                    "PROGRESS",
                    lambda: self._current_rss_lane.progress(request_generation),
                )
                with self._rss_progress:
                    self._merge_current_lane_summary_locked(
                        summary,
                        minimum_generation=request_generation,
                    )
                    self._rss_progress.notify_all()
                return request_generation
            except BaseException as error:
                self._record_current_lane_failure(error)
                with self._lock:
                    self._raise_sampler_error_locked()
                raise RuntimeError(
                    "Phase04-stage current-RSS lane handoff failed"
                ) from None

        deadline = (
            time.monotonic()
            + PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS / 1e9
        )
        timed_out = False
        with self._rss_progress:
            self._raise_sampler_error_locked()
            if self._stop.is_set() or self._ended:
                return None
            self._rss_progress_request_generation += 1
            request_generation = self._rss_progress_request_generation
            self._rss_handoff_request.set()
            while (
                self._rss_progress_completed_generation < request_generation
            ):
                self._raise_sampler_error_locked()
                if self._stop.is_set() or self._ended:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                self._rss_progress.wait(timeout=remaining)
            if not timed_out:
                self._raise_sampler_error_locked()
                return request_generation
        self._record_sampler_error(
            RuntimeError("Phase04-stage RSS progress handoff timed out"),
            lane="current_rss_handoff",
        )
        with self._lock:
            self._raise_sampler_error_locked()
        raise RuntimeError(  # pragma: no cover - preceding raise is required
            "Phase04-stage RSS progress handoff failed"
        ) from None

    def _reserve_child_scan_token(self) -> object | None:
        token = object()
        with self._child_scan_queue:
            self._child_scan_waiters.append(token)
            try:
                while self._child_scan_waiters[0] is not token:
                    if self._stop.is_set():
                        self._child_scan_waiters.remove(token)
                        self._child_scan_queue.notify_all()
                        return None
                    self._child_scan_queue.wait(timeout=0.100)
                if self._stop.is_set():
                    stopped_token = self._child_scan_waiters.popleft()
                    if stopped_token is not token:
                        raise RuntimeError(
                            "Phase04-stage child-scan FIFO order differs"
                        )
                    self._child_scan_queue.notify_all()
                    return None
                return token
            except BaseException:
                if token in self._child_scan_waiters:
                    self._child_scan_waiters.remove(token)
                    self._child_scan_queue.notify_all()
                raise

    def _release_child_scan_token(self, token: object) -> None:
        with self._child_scan_queue:
            if (
                not self._child_scan_waiters
                or self._child_scan_waiters[0] is not token
            ):
                raise RuntimeError("Phase04-stage child-scan FIFO order differs")
            self._child_scan_waiters.popleft()
            self._child_scan_queue.notify_all()

    @contextmanager
    def _child_scan_barrier(self) -> Iterator[None]:
        """Hold the next FIFO turn without performing a recursive scan."""

        token: object | None = None
        try:
            token = self._reserve_child_scan_token()
            if token is None:
                raise RuntimeError("Phase04-stage child-scan barrier stopped")
            yield
        finally:
            if token is not None:
                self._release_child_scan_token(token)

    def _active_serialized_child_scan(
        self,
        *,
        record_child_observation: bool = False,
    ) -> bool:
        """Bracket one FIFO-serialized child scan by two forced RSS reads."""

        token: object | None = None
        try:
            token = self._reserve_child_scan_token()
            if token is None:
                return False
            with self._lock:
                active = (
                    self._started
                    and not self._ended
                    and not self._stop.is_set()
                )
            if not active:
                return False
            with self._child_scan_lock:
                if self._request_rss_progress() is None:
                    return False
                scan_started_ns = time.monotonic_ns()
                scan_error: BaseException | None = None
                child_observed_ns: int | None = None
                try:
                    self._observe_no_recursive_children_unserialized()
                    if record_child_observation:
                        child_observed_ns = self._nonnegative_int(
                            self._clock_ns(),
                            label="child-observer monotonic timestamp",
                        )
                except BaseException as error:
                    scan_error = error
                scan_elapsed_ns = time.monotonic_ns() - scan_started_ns
                if self._request_rss_progress() is None:
                    return False
                if scan_error is not None:
                    raise scan_error
                # Recursive-child work has its own independent hard cadence.
                # The RSS-only lane continues throughout the scan and proves
                # its unchanged 10 ms bound from actual appended timestamps.
                # This same-bound check is only a redundant early failure;
                # source-observation and terminal gaps remain authoritative.
                if (
                    scan_elapsed_ns
                    > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
                ):
                    raise _Phase04StageSamplerFailure(
                        "Phase04-stage child scan duration exceeded",
                        cause_code="child_observer_scan_duration_exceeded",
                        observed_gap_ns=scan_elapsed_ns,
                        hard_gap_ns=(
                            PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
                        ),
                    )
                if record_child_observation:
                    if child_observed_ns is None:
                        raise RuntimeError(
                            "Phase04-stage child observation timestamp is absent"
                        )
                    with self._lock:
                        if (
                            self._append_child_observation_locked(
                                child_observed_ns
                            )
                            is None
                        ):
                            return False
        finally:
            if token is not None:
                self._release_child_scan_token(token)
        return True

    def _read_bracketed_current_rss(self) -> int:
        """Bracket one synchronous RSS boundary outside the state lock."""

        with self._lock:
            started = self._started
        if not started:
            # The t0 baseline is deliberately outside the measured cadence.
            with self._child_scan_lock:
                self._observe_no_recursive_children_unserialized()
                rss_bytes = self._read_current_rss()
                self._observe_no_recursive_children_unserialized()
                return rss_bytes
        if not self._active_serialized_child_scan():
            raise RuntimeError("Phase04-stage first child boundary scan stopped")
        rss_bytes = self._read_current_rss()
        if not self._active_serialized_child_scan():
            raise RuntimeError("Phase04-stage second child boundary scan stopped")
        return rss_bytes

    def _read_bracketed_current_rss_fail_closed(self) -> int:
        try:
            return self._read_bracketed_current_rss()
        except Exception as error:
            lane = "synchronous_boundary"
            if isinstance(error, _Phase04StageSamplerFailure) and (
                error.cause_code.startswith("child_observer_")
            ):
                lane = "child_observer"
            self._record_sampler_error(error, lane=lane)
            with self._lock:
                self._raise_sampler_error_locked()
            raise RuntimeError(  # pragma: no cover - preceding raise is required
                "Phase04-stage synchronous RSS boundary failed"
            ) from None

    def _read_hwm(self) -> int:
        return self._nonnegative_int(
            self._hwm_reader(),
            label="high-water value",
        )

    def _read_children_rusage(self) -> dict[str, Any]:
        return _validate_children_rusage_fingerprint(
            self._children_rusage_reader()
        )

    def _append_sample_locked(
        self,
        rss_bytes: int,
        *,
        kind: str,
    ) -> tuple[int, int] | None:
        if not self._started or self._ended:
            if self._ended and kind == "continuous":
                return None
            raise RuntimeError("Phase04-stage RSS sample window differs")
        observed_ns = self._nonnegative_int(
            self._clock_ns(),
            label="monotonic timestamp",
        )
        if self._last_sample_ns is None or observed_ns < self._last_sample_ns:
            raise RuntimeError("Phase04-stage RSS sample order differs")
        async_gap_ns: int | None = None
        if kind == "continuous":
            previous_async_ns = (
                self._last_async_ns
                if self._last_async_ns is not None
                else self._started_ns
            )
            assert previous_async_ns is not None
            async_gap_ns = observed_ns - previous_async_ns
            if async_gap_ns > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS:
                raise _Phase04StageSamplerFailure(
                    "Phase04-stage RSS sampling cadence exceeded",
                    cause_code="rss_sampling_cadence_exceeded",
                    observed_gap_ns=async_gap_ns,
                    hard_gap_ns=PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS,
                )
        elif kind != "synchronous":  # pragma: no cover - private invariant
            raise RuntimeError("Phase04-stage RSS sample kind differs")
        # Commit only after every observation-specific invariant passes. A
        # rejected cadence observation cannot become a peak, endpoint, or
        # accepted sample merely because it was the first failing read.
        self._last_sample_ns = observed_ns
        self._current_peak_bytes = max(
            int(self._current_peak_bytes),
            rss_bytes,
        )
        self._sample_count += 1
        if kind == "continuous":
            assert async_gap_ns is not None
            self._maximum_async_gap_ns = max(
                self._maximum_async_gap_ns,
                async_gap_ns,
            )
            self._continuous_sample_count += 1
            if self._first_async_ns is None:
                self._first_async_ns = observed_ns
            self._last_async_ns = observed_ns
        else:
            self._synchronous_sample_count += 1
        return rss_bytes, observed_ns

    def _append_child_observation_locked(
        self,
        observed_ns: int,
    ) -> int | None:
        if not self._started or self._ended:
            if self._ended:
                return None
            raise RuntimeError("Phase04-stage child-observer window differs")
        observed_ns = self._nonnegative_int(
            observed_ns,
            label="child-observer monotonic timestamp",
        )
        previous_ns = (
            self._last_child_observer_ns
            if self._last_child_observer_ns is not None
            else self._started_ns
        )
        assert previous_ns is not None
        if observed_ns < previous_ns:
            raise RuntimeError("Phase04-stage child-observer order differs")
        gap_ns = observed_ns - previous_ns
        if gap_ns > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS:
            raise _Phase04StageSamplerFailure(
                "Phase04-stage child-observer cadence exceeded",
                cause_code="child_observer_cadence_exceeded",
                observed_gap_ns=gap_ns,
                hard_gap_ns=(
                    PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
                ),
            )
        self._child_observer_maximum_gap_ns = max(
            self._child_observer_maximum_gap_ns,
            gap_ns,
        )
        self._child_observer_sample_count += 1
        if self._first_child_observer_ns is None:
            self._first_child_observer_ns = observed_ns
        self._last_child_observer_ns = observed_ns
        return observed_ns

    def _record_sampler_error(self, error: BaseException, *, lane: str) -> None:
        with self._rss_progress:
            if self._sampler_error_type is None:
                self._sampler_error_type = (
                    "RuntimeError"
                    if isinstance(error, _Phase04StageSamplerFailure)
                    else type(error).__name__
                )
                self._sampler_error_lane = lane
                if isinstance(error, _Phase04StageSamplerFailure):
                    cause_code = error.cause_code
                    observed_gap_ns = error.observed_gap_ns
                    hard_gap_ns = error.hard_gap_ns
                else:
                    cause_code = {
                        "child_observer": "child_observer_operation_failed",
                        "current_rss": "current_rss_operation_failed",
                        "current_rss_handoff": "current_rss_handoff_failed",
                        "synchronous_boundary": (
                            "synchronous_boundary_operation_failed"
                        ),
                        "thread_start": "sampler_thread_start_failed",
                    }.get(lane, "sampler_operation_failed")
                    observed_gap_ns = None
                    hard_gap_ns = None
                self._sampler_error_cause_code = cause_code
                self._sampler_error_observed_gap_ns = observed_gap_ns
                self._sampler_error_hard_gap_ns = hard_gap_ns
                self._sampler_error_accepted_continuous_count = (
                    self._continuous_sample_count
                )
                self._sampler_error_last_accepted_async_ns = self._last_async_ns
            if lane == "child_observer" and self._child_observer_error_type is None:
                self._child_observer_error_type = type(error).__name__
            self._stop.set()
            self._arm.set()
            self._rss_handoff_request.set()
            self._rss_progress.notify_all()
        with self._child_scan_queue:
            self._child_scan_queue.notify_all()
        self._rss_prepared_ready.set()
        self._child_prepared_ready.set()
        self._first_async_ready.set()
        self._first_child_observer_ready.set()

    @property
    def failure_summary(self) -> dict[str, Any] | None:
        """Return the immutable, bounded first sampler failure classification."""

        with self._lock:
            if self._sampler_error_type is None:
                return None
            if (
                self._sampler_error_lane is None
                or self._sampler_error_cause_code is None
                or self._sampler_error_accepted_continuous_count is None
            ):
                raise RuntimeError("Phase04-stage sampler failure evidence differs")
            return {
                "lane": self._sampler_error_lane,
                "cause_code": self._sampler_error_cause_code,
                "error_type": self._sampler_error_type,
                "observed_gap_ns": self._sampler_error_observed_gap_ns,
                "hard_gap_ns": self._sampler_error_hard_gap_ns,
                "accepted_continuous_count": (
                    self._sampler_error_accepted_continuous_count
                ),
                "last_accepted_async_ns": (
                    self._sampler_error_last_accepted_async_ns
                ),
                "classified_lane_failure": deepcopy(
                    self._sampler_error_classified_lane_failure
                ),
            }

    def _signal_stop(self) -> None:
        with self._rss_progress:
            self._stop.set()
            self._arm.set()
            self._rss_handoff_request.set()
            self._rss_progress.notify_all()
        with self._child_scan_queue:
            self._child_scan_queue.notify_all()

    def _read_current_rss_with_captured_generation(
        self,
    ) -> tuple[int, int] | None:
        """Snapshot requests immediately before a current-RSS read begins."""

        self._rss_handoff_request.clear()
        with self._lock:
            if self._stop.is_set() or self._ended:
                return None
            request_generation = self._rss_progress_request_generation
        rss_bytes = self._read_current_rss()
        return request_generation, rss_bytes

    def _append_continuous_progress_sample(
        self,
        request_generation: int,
        rss_bytes: int,
    ) -> tuple[int, int] | None:
        with self._rss_progress:
            appended = self._append_sample_locked(
                rss_bytes,
                kind="continuous",
            )
            if appended is not None:
                self._rss_progress_completed_generation = max(
                    self._rss_progress_completed_generation,
                    request_generation,
                )
                self._rss_progress.notify_all()
            return appended

    def _next_child_observer_cycle_start(
        self,
        cycle_started_ns: int,
    ) -> int | None:
        """Wait only the unused portion of one fixed-rate child cycle."""

        cycle_started_ns = self._nonnegative_int(
            cycle_started_ns,
            label="child-observer cycle timestamp",
        )
        now_ns = self._nonnegative_int(
            self._clock_ns(),
            label="child-observer scheduler timestamp",
        )
        if now_ns < cycle_started_ns:
            raise RuntimeError("Phase04-stage child-observer cycle order differs")
        next_deadline_ns = (
            cycle_started_ns
            + PHASE04_STAGE_CHILD_OBSERVER_TARGET_INTERVAL_NS
        )
        remaining_seconds = max(0, next_deadline_ns - now_ns) / 1e9
        if self._stop.wait(remaining_seconds):
            return None
        next_started_ns = self._nonnegative_int(
            self._clock_ns(),
            label="child-observer cycle timestamp",
        )
        if next_started_ns < now_ns:
            raise RuntimeError("Phase04-stage child-observer cycle order differs")
        return next_started_ns

    def _sample_continuously(self) -> None:
        try:
            self._rss_thread_qos_record = _phase04_stage_thread_qos_record()
            # Warm only the exact identity/current-RSS lane before B. Recursive
            # child enumeration is deliberately owned by the other lane.
            self._read_current_rss()
            self._rss_prepared_ready.set()
            while not self._stop.is_set():
                if self._arm.wait(0.100):
                    break
            if self._stop.is_set():
                return
            captured = self._read_current_rss_with_captured_generation()
            if captured is None:
                return
            request_generation, rss_bytes = captured
            appended = self._append_continuous_progress_sample(
                request_generation,
                rss_bytes,
            )
            if appended is None:
                return
            self._first_async_ready.set()
            while not self._stop.is_set():
                with self._lock:
                    assert self._last_async_ns is not None
                    next_deadline_ns = (
                        self._last_async_ns
                        + PHASE04_STAGE_RSS_TARGET_INTERVAL_NS
                    )
                now_ns = self._nonnegative_int(
                    self._clock_ns(),
                    label="scheduler timestamp",
                )
                # Remain runnable in the dedicated observer process instead
                # of depending on a kernel timer wakeup whose best-effort
                # latency can itself exceed the unchanged 10 ms evidence
                # ceiling. Python's verified 0.25 ms switch interval still
                # schedules the observer's main and child lanes. The loop
                # ends at the 1 ms target, an exact forced handoff, or stop.
                while (
                    now_ns < next_deadline_ns
                    and not self._rss_handoff_request.is_set()
                    and not self._stop.is_set()
                ):
                    now_ns = self._nonnegative_int(
                        self._clock_ns(),
                        label="scheduler timestamp",
                    )
                if self._stop.is_set():
                    return
                captured = self._read_current_rss_with_captured_generation()
                if captured is None:
                    return
                request_generation, rss_bytes = captured
                if self._append_continuous_progress_sample(
                    request_generation,
                    rss_bytes,
                ) is None:
                    return
        except BaseException as error:  # pragma: no cover - boundary exercised
            self._record_sampler_error(error, lane="current_rss")

    def _observe_children_continuously(self) -> None:
        try:
            self._child_thread_qos_record = _phase04_stage_thread_qos_record()
            # A single native recursive scan is one observation. Short-lived
            # reaped children remain independently covered by RUSAGE_CHILDREN.
            with self._child_scan_lock:
                self._observe_no_recursive_children_unserialized()
            self._child_prepared_ready.set()
            while not self._stop.is_set():
                if self._arm.wait(0.100):
                    break
            if self._stop.is_set():
                return
            observer_cycle_started_ns = self._nonnegative_int(
                self._clock_ns(),
                label="child-observer cycle timestamp",
            )
            if not self._active_serialized_child_scan(
                record_child_observation=True,
            ):
                return
            self._first_child_observer_ready.set()
            while not self._stop.is_set():
                next_cycle_started_ns = (
                    self._next_child_observer_cycle_start(
                        observer_cycle_started_ns
                    )
                )
                if next_cycle_started_ns is None:
                    return
                observer_cycle_started_ns = next_cycle_started_ns
                if not self._active_serialized_child_scan(
                    record_child_observation=True,
                ):
                    return
        except BaseException as error:  # pragma: no cover - boundary exercised
            self._record_sampler_error(error, lane="child_observer")

    def _raise_sampler_error_locked(self) -> None:
        if self._sampler_error_type is not None:
            raise RuntimeError(
                "Phase04-stage RSS sampler failed "
                f"lane={self._sampler_error_lane} "
                f"error_type={self._sampler_error_type}"
            ) from None

    @staticmethod
    def _wait_until(event: threading.Event, deadline: float) -> bool:
        return event.wait(max(0.0, deadline - time.monotonic()))

    def _join_threads(self, *, label: str) -> None:
        deadline = time.monotonic() + 1.0
        alive: list[str] = []
        for lane, thread in (
            ("current_rss", self._rss_thread),
            ("child_observer", self._child_thread),
        ):
            if thread is None:
                continue
            try:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            except RuntimeError:
                if thread.is_alive():
                    alive.append(lane)
                continue
            if thread.is_alive():
                alive.append(lane)
        if alive:
            raise RuntimeError(
                f"Phase04-stage RSS sampler {label} did not terminate "
                f"lanes={','.join(alive)}"
            )

    def prepare(self) -> None:
        if (
            self._prepared
            or self._rss_thread is not None
            or self._child_thread is not None
        ):
            raise RuntimeError("Phase04-stage RSS sampler already prepared")
        if self._current_rss_lane is None:
            self._rss_thread = threading.Thread(
                target=self._sample_continuously,
                name="p04-us01-current-rss",
                daemon=True,
            )
            self._thread = self._rss_thread
        self._child_thread = threading.Thread(
            target=self._observe_children_continuously,
            name="p04-us01-live-recursive-children",
            daemon=True,
        )
        try:
            try:
                if self._current_rss_lane is None:
                    assert self._rss_thread is not None
                    self._rss_thread.start()
                else:
                    qualification = self._call_current_rss_lane(
                        "PREPARE",
                        self._current_rss_lane.prepare,
                    )
                    if type(qualification) is not dict:
                        raise RuntimeError(
                            "Phase04-stage current-RSS lane qualification differs"
                        )
                    self._current_lane_qualification = deepcopy(qualification)
                    self._rss_prepared_ready.set()
                self._child_thread.start()
            except Exception as error:
                if (
                    self._current_rss_lane is not None
                    and (
                        isinstance(error, rss_lane.LaneOperationError)
                        or self._current_rss_lane.failure_summary is not None
                    )
                ):
                    self._record_current_lane_failure(error)
                else:
                    self._record_sampler_error(error, lane="thread_start")
                raise RuntimeError(
                    "Phase04-stage RSS sampler failed to start"
                ) from None
            deadline = time.monotonic() + 1.0
            if not self._wait_until(self._rss_prepared_ready, deadline):
                raise RuntimeError("Phase04-stage RSS lane readiness timed out")
            if not self._wait_until(self._child_prepared_ready, deadline):
                raise RuntimeError(
                    "Phase04-stage child-observer readiness timed out"
                )
            with self._lock:
                self._raise_sampler_error_locked()
            rss_ready = (
                self._current_rss_lane is not None
                or (
                    self._rss_thread is not None
                    and self._rss_thread.is_alive()
                )
            )
            if not rss_ready or not self._child_thread.is_alive():
                raise RuntimeError(
                    "Phase04-stage RSS sampler ended before arming"
                )
            self._prepared = True
        except Exception as primary_error:
            if not (
                isinstance(primary_error, RuntimeError)
                and str(primary_error).startswith("Phase04-stage ")
            ):
                primary_error = RuntimeError(
                    "Phase04-stage RSS prepare failed "
                    f"error_type={type(primary_error).__name__}"
                )
            try:
                self.abort()
            except Exception as cleanup_error:
                sanitized_cleanup = RuntimeError(
                    "Phase04-stage RSS prepare cleanup failed "
                    f"error_type={type(cleanup_error).__name__}"
                )
                raise ExceptionGroup(
                    "Phase04-stage RSS prepare and cleanup failed",
                    [primary_error, sanitized_cleanup],
                ) from None
            raise primary_error from None

    def start(self, first_boundary_component: str) -> None:
        if first_boundary_component not in TABLE_STAGE_COMPONENTS:
            raise RuntimeError("Phase04-stage first RSS boundary differs")
        if (
            not self._prepared
            or self._child_thread is None
            or not self._child_thread.is_alive()
            or (
                self._current_rss_lane is None
                and (
                    self._rss_thread is None
                    or not self._rss_thread.is_alive()
                )
            )
        ):
            raise RuntimeError("Phase04-stage RSS sampler is not prepared")
        try:
            # Complete all slow baseline/child work before t0. The first
            # measured component cannot enter until both lanes prove a first
            # post-t0 observation below.
            current_baseline = self._read_bracketed_current_rss_fail_closed()
            hwm_baseline = self._read_hwm()
            children_rusage_baseline = self._read_children_rusage()
            with self._lock:
                self._raise_sampler_error_locked()
                if self._started:
                    raise RuntimeError("Phase04-stage RSS sampler already started")
                started_ns = self._nonnegative_int(
                    self._clock_ns(),
                    label="start timestamp",
                )
                self._started = True
                self._first_boundary_component = first_boundary_component
                self._started_ns = started_ns
                self._last_sample_ns = started_ns
                self._current_baseline_bytes = current_baseline
                self._current_peak_bytes = current_baseline
                self._hwm_baseline_bytes = hwm_baseline
                self._children_rusage_baseline = children_rusage_baseline
                self._sample_count = 1
                self._synchronous_sample_count = 1
                self._child_boundary_check_count = 1
                if self._current_rss_lane is None:
                    self._arm.set()
            if self._current_rss_lane is not None:
                try:
                    lane_summary = self._call_current_rss_lane(
                        "START",
                        lambda: self._current_rss_lane.start(
                            started_monotonic_ns=started_ns,
                            current_baseline_bytes=current_baseline,
                        ),
                    )
                    with self._rss_progress:
                        self._merge_current_lane_summary_locked(lane_summary)
                        self._arm.set()
                        self._rss_progress.notify_all()
                except BaseException as error:
                    self._record_current_lane_failure(error)
                    with self._lock:
                        self._raise_sampler_error_locked()
            deadline = (
                time.monotonic()
                + PHASE04_STAGE_FIRST_OBSERVATION_READY_SECONDS
            )
            if not self._wait_until(self._first_async_ready, deadline):
                raise RuntimeError(
                    "Phase04-stage RSS first observation readiness timed out"
                )
            if not self._wait_until(
                self._first_child_observer_ready,
                deadline,
            ):
                raise RuntimeError(
                    "Phase04-stage child first observation readiness timed out"
                )
            with self._lock:
                self._raise_sampler_error_locked()
                if (
                    self._first_async_ns is None
                    or self._first_child_observer_ns is None
                ):
                    raise RuntimeError(
                        "Phase04-stage first observations are absent"
                    )
        except Exception:
            self.abort()
            raise

    def sample_synchronous_boundary(self) -> None:
        rss_bytes = self._read_bracketed_current_rss_fail_closed()
        with self._lock:
            self._raise_sampler_error_locked()
            appended = self._append_sample_locked(
                rss_bytes,
                kind="synchronous"
            )
            if appended is None:  # pragma: no cover - synchronous invariant
                raise RuntimeError("Phase04-stage RSS boundary sample is absent")
            self._child_boundary_check_count += 1

    def record_parse_checkpoint(self) -> dict[str, int]:
        """Record parse-return RSS without ending the output-complete window."""

        current_end = self._read_bracketed_current_rss_fail_closed()
        hwm_end = self._read_hwm()
        lane_summary: dict[str, Any] | None = None
        if self._current_rss_lane is not None:
            try:
                lane_summary = self._call_current_rss_lane(
                    "CHECKPOINT",
                    self._current_rss_lane.checkpoint,
                )
            except BaseException as error:
                self._record_current_lane_failure(error)
                with self._lock:
                    self._raise_sampler_error_locked()
        with self._lock:
            self._raise_sampler_error_locked()
            if (
                not self._started
                or self._ended
                or self._parse_checkpoint_ns is not None
            ):
                raise RuntimeError("Phase04-stage parse RSS checkpoint state differs")
            if lane_summary is not None:
                self._merge_current_lane_summary_locked(lane_summary)
                assert self._current_lane_end_bytes is not None
                current_end = self._current_lane_end_bytes
            self._current_peak_bytes = max(
                int(self._current_peak_bytes),
                current_end,
            )
            self._sample_count += 1
            self._synchronous_sample_count += 1
            checkpoint_ns = self._nonnegative_int(
                self._clock_ns(),
                label="parse checkpoint timestamp",
            )
            if (
                self._last_sample_ns is None
                or checkpoint_ns < self._last_sample_ns
            ):
                raise RuntimeError("Phase04-stage parse checkpoint order differs")
            self._last_sample_ns = checkpoint_ns
            self._child_boundary_check_count += 1
            self._parse_checkpoint_ns = checkpoint_ns
            self._parse_current_peak_bytes = self._current_peak_bytes
            self._parse_current_end_bytes = current_end
            self._parse_hwm_end_bytes = hwm_end
            return {
                "phase04_stage_parse_checkpoint_monotonic_ns": checkpoint_ns,
                "phase04_stage_parse_current_rss_peak_bytes": int(
                    self._current_peak_bytes
                ),
                "phase04_stage_parse_current_rss_end_bytes": current_end,
                "phase04_stage_parse_hwm_end_bytes": hwm_end,
            }

    def sample_output_boundary(self) -> None:
        rss_bytes = self._read_bracketed_current_rss_fail_closed()
        with self._lock:
            self._raise_sampler_error_locked()
            if self._parse_checkpoint_ns is None:
                raise RuntimeError("Phase04-stage output preceded parse checkpoint")
            appended = self._append_sample_locked(
                rss_bytes,
                kind="synchronous",
            )
            if appended is None:  # pragma: no cover - synchronous invariant
                raise RuntimeError("Phase04-stage output RSS sample is absent")
            self._output_synchronous_boundary_count += 1
            self._child_boundary_check_count += 1

    def finish(self) -> dict[str, Any]:
        try:
            current_end = self._read_bracketed_current_rss_fail_closed()
            hwm_end = self._read_hwm()
            children_rusage_end = self._read_children_rusage()
            with self._child_scan_barrier():
                lane_summary: dict[str, Any] | None = None
                if self._current_rss_lane is not None:
                    try:
                        lane_result = self._call_current_rss_lane(
                            "FINISH",
                            self._current_rss_lane.finish,
                        )
                        if (
                            type(lane_result) is not dict
                            or set(lane_result) != {"summary", "runtime"}
                        ):
                            raise RuntimeError(
                                "Phase04-stage current-RSS lane finish differs"
                            )
                        lane_summary = lane_result["summary"]
                    except BaseException as error:
                        self._record_current_lane_failure(error)
                        with self._lock:
                            self._raise_sampler_error_locked()
                with self._rss_progress:
                    self._raise_sampler_error_locked()
                    if (
                        not self._started
                        or self._ended
                        or self._parse_checkpoint_ns is None
                        or self._output_synchronous_boundary_count < 1
                    ):
                        raise RuntimeError(
                            "Phase04-stage RSS completion state differs"
                        )
                    if lane_summary is not None:
                        self._merge_current_lane_summary_locked(lane_summary)
                        assert self._current_lane_end_bytes is not None
                        current_end = self._current_lane_end_bytes
                        ended_ns = lane_summary["last_async_monotonic_ns"]
                    else:
                        ended_ns = self._nonnegative_int(
                            self._clock_ns(),
                            label="end timestamp",
                        )
                    self._current_peak_bytes = max(
                        int(self._current_peak_bytes),
                        current_end,
                    )
                    self._synchronous_sample_count += 1
                    self._sample_count = (
                        self._synchronous_sample_count
                        + self._continuous_sample_count
                    )
                    if children_rusage_end != self._children_rusage_baseline:
                        raise RuntimeError(
                            "Phase04-stage child rusage fingerprint changed"
                        )
                    if (
                        self._last_sample_ns is None
                        or ended_ns < self._last_sample_ns
                    ):
                        raise RuntimeError("Phase04-stage RSS end order differs")
                    self._last_sample_ns = ended_ns
                    self._child_boundary_check_count += 1
                    self._current_end_bytes = current_end
                    self._hwm_end_bytes = hwm_end
                    self._children_rusage_end = children_rusage_end
                    self._ended_ns = ended_ns
                    self._ended = True
                    self._rss_progress.notify_all()
                    if self._last_async_ns is None:
                        raise RuntimeError(
                            "Phase04-stage RSS async samples are absent"
                        )
                    terminal_async_gap_ns = ended_ns - self._last_async_ns
                    self._maximum_async_gap_ns = max(
                        self._maximum_async_gap_ns,
                        terminal_async_gap_ns,
                    )
                    if (
                        terminal_async_gap_ns
                        > PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
                    ):
                        raise _Phase04StageSamplerFailure(
                            "Phase04-stage RSS terminal async cadence exceeded",
                            cause_code="rss_terminal_cadence_exceeded",
                            observed_gap_ns=terminal_async_gap_ns,
                            hard_gap_ns=PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS,
                        )
                    if self._last_child_observer_ns is None:
                        raise RuntimeError(
                            "Phase04-stage child-observer samples are absent"
                        )
                    terminal_child_gap_ns = (
                        ended_ns - self._last_child_observer_ns
                    )
                    self._child_observer_maximum_gap_ns = max(
                        self._child_observer_maximum_gap_ns,
                        terminal_child_gap_ns,
                    )
                    if (
                        terminal_child_gap_ns
                        > PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
                    ):
                        raise _Phase04StageSamplerFailure(
                            "Phase04-stage child-observer terminal cadence exceeded",
                            cause_code="child_observer_terminal_cadence_exceeded",
                            observed_gap_ns=terminal_child_gap_ns,
                            hard_gap_ns=(
                                PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
                            ),
                        )
        except Exception as error:
            with self._lock:
                already_recorded = self._sampler_error_type is not None
            if not already_recorded:
                lane = "current_rss"
                if isinstance(error, _Phase04StageSamplerFailure) and (
                    error.cause_code.startswith("child_observer_")
                ):
                    lane = "child_observer"
                self._record_sampler_error(error, lane=lane)
            self.abort()
            raise
        self._signal_stop()
        if self._child_thread is None or (
            self._current_rss_lane is None and self._rss_thread is None
        ):
            raise RuntimeError("Phase04-stage RSS sampler threads are absent")
        self._join_threads(label="finish")
        if self._current_rss_lane is not None:
            self._current_rss_lane.quiesce()
            self._current_rss_lane.require_quiesced()
        with self._lock:
            self._raise_sampler_error_locked()
            if self._first_async_ns is None or self._last_async_ns is None:
                raise RuntimeError("Phase04-stage RSS async samples are absent")
            assert self._started_ns is not None
            return _phase04_stage_rss_record(
                current_baseline_bytes=self._current_baseline_bytes,
                current_peak_bytes=self._current_peak_bytes,
                current_end_bytes=self._current_end_bytes,
                hwm_baseline_bytes=self._hwm_baseline_bytes,
                hwm_end_bytes=self._hwm_end_bytes,
                children_rusage_baseline=self._children_rusage_baseline,
                children_rusage_end=self._children_rusage_end,
                current_rss_source_version=self._source_version,
                first_boundary_component=self._first_boundary_component,
                worker_pid=self._worker_pid,
                process_create_time_ns=self._process_create_time_ns,
                platform_name=sys.platform,
                started_monotonic_ns=self._started_ns,
                parse_checkpoint_monotonic_ns=self._parse_checkpoint_ns,
                parse_current_peak_bytes=self._parse_current_peak_bytes,
                parse_current_end_bytes=self._parse_current_end_bytes,
                parse_hwm_end_bytes=self._parse_hwm_end_bytes,
                ended_monotonic_ns=self._ended_ns,
                sampling_maximum_gap_ns=self._maximum_async_gap_ns,
                sample_count=self._sample_count,
                continuous_sample_count=self._continuous_sample_count,
                synchronous_sample_count=self._synchronous_sample_count,
                output_synchronous_boundary_count=(
                    self._output_synchronous_boundary_count
                ),
                first_async_offset_ns=self._first_async_ns - self._started_ns,
                last_async_offset_ns=self._last_async_ns - self._started_ns,
                child_observer_maximum_gap_ns=(
                    self._child_observer_maximum_gap_ns
                ),
                child_observer_sample_count=(
                    self._child_observer_sample_count
                ),
                child_boundary_check_count=self._child_boundary_check_count,
                child_observer_first_offset_ns=(
                    self._first_child_observer_ns - self._started_ns
                ),
                child_observer_last_offset_ns=(
                    self._last_child_observer_ns - self._started_ns
                ),
            )

    def abort(self) -> None:
        self._signal_stop()
        current = threading.current_thread()
        if current in {self._rss_thread, self._child_thread}:
            return
        primary_error: Exception | None = None
        if self._current_rss_lane is not None:
            try:
                if (
                    self._current_rss_lane.quiesced
                    or getattr(self._current_rss_lane, "_terminal", False)
                ):
                    self._current_rss_lane.abort()
                else:
                    self._call_current_rss_lane(
                        "ABORT",
                        self._current_rss_lane.abort,
                    )
            except Exception as error:
                primary_error = error
            try:
                self._current_rss_lane.quiesce()
            except Exception as error:
                primary_error = primary_error or error
        try:
            self._join_threads(label="abort")
        except Exception as error:
            primary_error = primary_error or error
        if primary_error is not None:
            raise RuntimeError(
                "Phase04-stage RSS abort failed "
                f"error_type={type(primary_error).__name__}"
            ) from None

    def require_quiesced(self) -> None:
        """Prove no sampler lane can issue another process observation."""

        alive = [
            lane
            for lane, thread in (
                ("current_rss", self._rss_thread),
                ("child_observer", self._child_thread),
            )
            if thread is not None and thread.is_alive()
        ]
        if alive:
            raise RuntimeError(
                "Phase04-stage RSS sampler is not quiesced "
                f"lanes={','.join(alive)}"
            )
        if self._current_rss_lane is None and (
            (self._rss_thread is None) != (self._child_thread is None)
        ):
            raise RuntimeError("Phase04-stage RSS sampler quiescence state differs")
        if self._current_rss_lane is not None:
            self._current_rss_lane.require_quiesced()
            if self._rss_thread is not None or self._child_thread is None:
                raise RuntimeError(
                    "Phase04-stage RSS remote-lane quiescence state differs"
                )
        if self._child_thread is not None and not (
            self._stop.is_set() or self._ended
        ):
            raise RuntimeError(
                "Phase04-stage RSS sampler quiescence state differs"
            )

    @property
    def thread_qos_record(self) -> dict[str, Any]:
        self.require_quiesced()
        if self._current_rss_lane is not None:
            if self._child_thread_qos_record is None:
                raise RuntimeError(
                    "Phase04-stage child-observer thread QoS is absent"
                )
            return {
                "policy": PHASE04_STAGE_THREAD_QOS_POLICY,
                "child_observer_thread": deepcopy(
                    self._child_thread_qos_record
                ),
            }
        if (
            self._rss_thread_qos_record is None
            or self._child_thread_qos_record is None
        ):
            raise RuntimeError("Phase04-stage sampler thread QoS is absent")
        return {
            "policy": PHASE04_STAGE_THREAD_QOS_POLICY,
            "current_rss_thread": deepcopy(self._rss_thread_qos_record),
            "child_observer_thread": deepcopy(
                self._child_thread_qos_record
            ),
        }

    @property
    def current_rss_lane_custody(self) -> dict[str, Any] | None:
        if self._current_rss_lane is None:
            return None
        self.require_quiesced()
        runtime = self._current_rss_lane.runtime
        if (
            self._current_lane_qualification is None
            or type(runtime.get("qualification_commitment")) is not dict
            or runtime["qualification_commitment"]
            != rss_lane.qualification_runtime_commitment(
                self._current_lane_qualification
            )
        ):
            raise RuntimeError(
                "Phase04-stage current-RSS lane qualification custody differs"
            )
        return {
            "summary": deepcopy(self._current_lane_summary),
            "identity": self._current_rss_lane.identity,
            "lifecycle": self._current_rss_lane.lifecycle,
            "runtime": runtime,
            "protocol": self._current_rss_lane.protocol_custody,
        }

    def failed_current_rss_lane_custody(
        self,
        *,
        sampler_abort_completed: bool,
        sampler_quiescence_proved: bool,
        cleanup_error_types: Sequence[str],
    ) -> dict[str, Any] | None:
        """Retain one post-cleanup lane bundle, including partial IPC custody."""

        lane = self._current_rss_lane
        if lane is None:
            return None
        protocol = lane.protocol_custody
        classified = lane.failure_summary
        runtime_commitment: dict[str, Any] | None = None
        classified_count = 0
        classified_sha256: str | None = None
        if classified is not None:
            classified = rss_lane.validate_failure_summary(
                classified,
                require_runtime=True,
            )
            runtime_commitment = deepcopy(
                classified["runtime"]["qualification_commitment"]
            )
            classified_count = 1
            classified_sha256 = _sha256_bytes(_canonical_bytes(classified))
        elif self._current_lane_qualification is not None:
            runtime_commitment = rss_lane.qualification_runtime_commitment(
                self._current_lane_qualification
            )
        lifecycle: dict[str, Any] | None = None
        lifecycle_error_type: str | None = None
        if lane.quiesced:
            try:
                lifecycle = lane.lifecycle
            except Exception as error:
                lifecycle_error_type = type(error).__name__
        with self._lock:
            transaction = {
                "schema_id": EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID,
                "issued_operation_count": (
                    self._current_lane_transaction_issued_count
                ),
                "completed_operation_count": (
                    self._current_lane_transaction_completed_count
                ),
                "protocol_exchange_count": protocol["exchange_count"],
                "bootstrap_bind_exchange_count": 1,
                "first_failed_transaction": deepcopy(
                    self._current_lane_first_failed_transaction
                ),
                "active_transaction_at_seal": deepcopy(
                    self._current_lane_active_transaction
                ),
            }
            last_summary_sha256 = (
                None
                if self._current_lane_summary is None
                else _sha256_bytes(_canonical_bytes(self._current_lane_summary))
            )
            qualification_sha256 = (
                None
                if self._current_lane_qualification is None
                else _sha256_bytes(
                    _canonical_bytes(self._current_lane_qualification)
                )
            )
            child_threads_quiesced = not any(
                thread is not None and thread.is_alive()
                for thread in (self._rss_thread, self._child_thread)
            )
        return _validate_current_rss_lane_failure_custody(
            {
                "schema_id": CURRENT_RSS_LANE_FAILURE_CUSTODY_SCHEMA_ID,
                "classification": {
                    "primary_classified_failure_count": classified_count,
                    "primary_classified_failure_location": (
                        "lane_protocol.terminal_error_response.failure_summary"
                        if classified_count == 1
                        else None
                    ),
                    "primary_classified_failure_sha256": classified_sha256,
                },
                "lane_identity": lane.identity,
                "lane_lifecycle": lifecycle,
                "lane_protocol": protocol,
                "qualification_runtime_commitment": runtime_commitment,
                "transaction_custody": transaction,
                "partial_state": {
                    "qualification_committed": (
                        self._current_lane_qualification is not None
                    ),
                    "qualification_sha256": qualification_sha256,
                    "last_committed_summary_sha256": last_summary_sha256,
                },
                "cleanup": {
                    "sampler_abort_completed": sampler_abort_completed,
                    "sampler_quiescence_proved": sampler_quiescence_proved,
                    "child_threads_quiesced": child_threads_quiesced,
                    "lane_process_quiesced": lane.quiesced,
                    "lane_lifecycle_error_type": lifecycle_error_type,
                    "cleanup_error_types": list(cleanup_error_types),
                },
            }
        )


def _external_monitor_frame(
    value: Mapping[str, Any],
    *,
    maximum_frame_bytes: int = EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES,
) -> bytes:
    payload = _canonical_bytes(value)
    if not 0 < len(payload) <= maximum_frame_bytes:
        raise RuntimeError("Phase04-stage monitor frame size differs")
    return struct.pack("!I", len(payload)) + payload


def _external_monitor_message(
    raw: bytes,
    *,
    label: str,
    maximum_frame_bytes: int = EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES,
) -> dict[str, Any]:
    if not 0 < len(raw) <= maximum_frame_bytes:
        raise RuntimeError(f"Phase04-stage monitor {label} size differs")
    try:
        value = _load_strict_bounded_json(raw, label=f"monitor {label}")
    except (TypeError, ValueError) as error:
        raise RuntimeError(
            f"Phase04-stage monitor {label} JSON differs"
        ) from error
    if _canonical_bytes(value) != raw:
        raise RuntimeError(f"Phase04-stage monitor {label} bytes differ")
    return value


def _recv_external_monitor_frame(
    channel: socket.socket,
    *,
    maximum_frame_bytes: int = EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES,
) -> bytes:
    def receive_exact(size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = channel.recv(size - len(chunks))
            except (OSError, socket.timeout) as error:
                raise RuntimeError(
                    "Phase04-stage monitor receive failed "
                    f"error_type={type(error).__name__}"
                ) from None
            if not chunk:
                raise RuntimeError("Phase04-stage monitor unexpected EOF")
            chunks.extend(chunk)
        return bytes(chunks)

    header = receive_exact(4)
    (size,) = struct.unpack("!I", header)
    if not 0 < size <= maximum_frame_bytes:
        raise RuntimeError("Phase04-stage monitor frame size differs")
    return receive_exact(size)


def _worker_monitor_identity() -> dict[str, Any]:
    import psutil

    source_version = _current_rss_source_version()
    process = psutil.Process(os.getpid())
    create_time = process.create_time()
    if (
        type(create_time) not in {int, float}
        or type(create_time) is bool
        or not math.isfinite(float(create_time))
        or create_time <= 0
    ):
        raise RuntimeError("Phase04-stage monitor worker identity differs")
    return {
        "worker_pid": os.getpid(),
        "process_create_time_ns": int(round(float(create_time) * 1e9)),
        "source_version": source_version,
        "platform": sys.platform,
    }


def _controller_monitor_identity() -> dict[str, Any]:
    import psutil

    if psutil.__version__ != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION:
        raise RuntimeError("Phase04-stage monitor controller source differs")
    process = psutil.Process(os.getpid())
    create_time = process.create_time()
    if (
        type(create_time) not in {int, float}
        or type(create_time) is bool
        or not math.isfinite(float(create_time))
        or create_time <= 0
    ):
        raise RuntimeError("Phase04-stage monitor controller identity differs")
    return {
        "pid": os.getpid(),
        "process_create_time_ns": int(round(float(create_time) * 1e9)),
        "pgid": os.getpgrp(),
        "sid": os.getsid(0),
        "platform": sys.platform,
        "identity_source": EXTERNAL_RSS_MONITOR_CONTROLLER_IDENTITY_SOURCE,
        "identity_source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
    }


class _ExternalRSSSamplerProxy:
    """Synchronous worker-side proxy for the parent-owned sampler."""

    def __init__(self, descriptor: int) -> None:
        if type(descriptor) is not int or descriptor <= 2:
            raise RuntimeError("Phase04-stage monitor descriptor differs")
        try:
            os.set_inheritable(descriptor, False)
            if os.get_inheritable(descriptor):
                raise RuntimeError(
                    "Phase04-stage monitor descriptor remains inheritable"
                )
            self._channel = socket.socket(fileno=descriptor)
            if (
                self._channel.family != socket.AF_UNIX
                or self._channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                != socket.SOCK_STREAM
            ):
                raise RuntimeError("Phase04-stage monitor socket type differs")
            self._channel.settimeout(
                EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
            )
        except Exception as error:
            try:
                self._channel.close()
            except (AttributeError, OSError):
                pass
            if isinstance(error, RuntimeError):
                raise
            raise RuntimeError(
                "Phase04-stage monitor socket setup failed "
                f"error_type={type(error).__name__}"
            ) from None
        self._sequence = 0
        self._prepared = False
        self._started = False
        self._parse_recorded = False
        self._finished = False
        self._aborted = False
        self._closed = False

    def _request(
        self,
        operation: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if self._closed:
            raise RuntimeError("Phase04-stage monitor channel is closed")
        if operation not in EXTERNAL_RSS_MONITOR_OPERATIONS:
            raise RuntimeError("Phase04-stage monitor operation differs")
        self._sequence += 1
        request = {
            "schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
            "sequence": self._sequence,
            "operation": operation,
            "payload": dict(payload),
        }
        try:
            self._channel.sendall(_external_monitor_frame(request))
        except (OSError, socket.timeout) as error:
            raise RuntimeError(
                "Phase04-stage monitor send failed "
                f"error_type={type(error).__name__}"
            ) from None
        response = _external_monitor_message(
            _recv_external_monitor_frame(self._channel),
            label="response",
        )
        if set(response) != {
            "schema_id",
            "sequence",
            "operation",
            "status",
            "record",
        } or any(
            (
                response.get("schema_id") != EXTERNAL_RSS_MONITOR_SCHEMA_ID,
                response.get("sequence") != self._sequence,
                response.get("operation") != operation,
                response.get("status") not in {"ok", "error"},
            )
        ):
            raise RuntimeError("Phase04-stage monitor response differs")
        if response["status"] != "ok":
            raise RuntimeError("Phase04-stage parent monitor rejected operation")
        record = response["record"]
        if record is not None and type(record) is not dict:
            raise RuntimeError("Phase04-stage monitor response record differs")
        return deepcopy(record)

    def _close(self) -> None:
        if self._closed:
            return
        deferred_cancellations: list[BaseException] = []
        try:
            _call_deferring_cancellation(
                lambda: self._channel.shutdown(socket.SHUT_RDWR),
                deferred_cancellations,
            )
        except OSError:
            pass
        close_error: Exception | None = None
        try:
            _call_deferring_cancellation(
                self._channel.close,
                deferred_cancellations,
            )
        except Exception as error:
            close_error = error
        finally:
            self._closed = self._channel.fileno() == -1
        if close_error is not None:
            raise RuntimeError(
                "Phase04-stage monitor close failed "
                f"error_type={type(close_error).__name__}"
            ) from None
        if not self._closed:
            raise RuntimeError("Phase04-stage monitor close is incomplete")
        if deferred_cancellations:
            raise deferred_cancellations[0]

    def prepare(self) -> None:
        if self._prepared or self._finished or self._aborted:
            raise RuntimeError("Phase04-stage monitor prepare state differs")
        self._channel.settimeout(
            EXTERNAL_RSS_OBSERVER_QUALIFICATION_TIMEOUT_SECONDS
        )
        try:
            record = self._request("PREPARE", _worker_monitor_identity())
        finally:
            self._channel.settimeout(
                EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
            )
        if record is not None:
            raise RuntimeError("Phase04-stage monitor prepare response differs")
        self._prepared = True

    def start(self, first_boundary_component: str) -> None:
        if not self._prepared or self._started or self._finished or self._aborted:
            raise RuntimeError("Phase04-stage monitor start state differs")
        record = self._request(
            "START",
            {
                "first_boundary_component": first_boundary_component,
                "hwm_bytes": _rss_bytes(),
                "children_rusage": _children_rusage_fingerprint(),
            },
        )
        if record is not None:
            raise RuntimeError("Phase04-stage monitor start response differs")
        self._started = True

    def sample_synchronous_boundary(self) -> None:
        if not self._started or self._parse_recorded or self._finished:
            raise RuntimeError("Phase04-stage monitor boundary state differs")
        if self._request("BOUNDARY", {}) is not None:
            raise RuntimeError("Phase04-stage monitor boundary response differs")

    def record_parse_checkpoint(self) -> dict[str, int]:
        if not self._started or self._parse_recorded or self._finished:
            raise RuntimeError("Phase04-stage monitor parse state differs")
        record = self._request("PARSE", {"hwm_bytes": _rss_bytes()})
        if type(record) is not dict:
            raise RuntimeError("Phase04-stage monitor parse response differs")
        self._parse_recorded = True
        return record

    def sample_output_boundary(self) -> None:
        if not self._parse_recorded or self._finished or self._aborted:
            raise RuntimeError("Phase04-stage monitor output state differs")
        if self._request("OUTPUT", {}) is not None:
            raise RuntimeError("Phase04-stage monitor output response differs")

    def finish(self) -> dict[str, Any]:
        if not self._parse_recorded or self._finished or self._aborted:
            raise RuntimeError("Phase04-stage monitor finish state differs")
        record = self._request(
            "FINISH",
            {
                "hwm_bytes": _rss_bytes(),
                "children_rusage": _children_rusage_fingerprint(),
            },
        )
        if type(record) is not dict:
            raise RuntimeError("Phase04-stage monitor finish response differs")
        self._finished = True
        self._close()
        return record

    def abort(self) -> None:
        if (self._finished or self._aborted) and self._closed:
            return
        if self._finished:
            self._close()
            return
        primary_error: BaseException | None = None
        try:
            if not self._aborted:
                try:
                    if self._request("ABORT", {}) is not None:
                        raise RuntimeError(
                            "Phase04-stage monitor abort response differs"
                        )
                except BaseException as error:
                    primary_error = error
            self._aborted = True
        finally:
            try:
                self._close()
            except BaseException as cleanup_error:
                if primary_error is None:
                    raise
                if isinstance(primary_error, Exception) and isinstance(
                    cleanup_error, Exception
                ):
                    raise ExceptionGroup(
                        "Phase04-stage monitor abort and close failed",
                        [primary_error, cleanup_error],
                    ) from None
                raise BaseExceptionGroup(
                    "Phase04-stage monitor abort and close failed",
                    [primary_error, cleanup_error],
                ) from None
        if primary_error is not None:
            raise primary_error


class _ExternalRSSObserverRuntime:
    """Own scheduler and cyclic-GC state inside the observer process."""

    def __init__(self) -> None:
        self._owned = False
        self._original_interval: float | None = None
        self._effective_interval: float | None = None
        self._restored_interval: float | None = None
        self._original_gc_enabled: bool | None = None
        self._effective_gc_enabled: bool | None = None
        self._restored_gc_enabled: bool | None = None
        self._collected_objects: int | None = None
        self._scheduler_mutated = False
        self._gc_mutated = False
        self._main_thread_qos_record: dict[str, Any] | None = None

    def acquire(self) -> None:
        if self._owned or not _EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK.acquire(False):
            raise RuntimeError("Phase04-stage observer runtime is already owned")
        self._owned = True
        try:
            self._main_thread_qos_record = _phase04_stage_thread_qos_record()
            original_interval = sys.getswitchinterval()
            if (
                type(original_interval) is not float
                or not math.isfinite(original_interval)
                or original_interval <= 0
            ):
                raise RuntimeError("Phase04-stage observer scheduler differs")
            self._original_interval = original_interval
            sys.setswitchinterval(
                EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
            )
            effective_interval = sys.getswitchinterval()
            if (
                effective_interval
                != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
            ):
                raise RuntimeError("Phase04-stage observer scheduler differs")
            self._effective_interval = effective_interval
            original_gc_enabled = gc.isenabled()
            if type(original_gc_enabled) is not bool:
                raise RuntimeError("Phase04-stage observer GC differs")
            self._original_gc_enabled = original_gc_enabled
            collected = gc.collect() if original_gc_enabled else 0
            if type(collected) is not int or collected < 0:
                raise RuntimeError("Phase04-stage observer GC differs")
            self._collected_objects = collected
            gc.disable()
            self._effective_gc_enabled = gc.isenabled()
            if self._effective_gc_enabled is not False:
                raise RuntimeError("Phase04-stage observer GC differs")
        except BaseException:
            try:
                self.restore(require_unchanged=False)
            except BaseException:
                pass
            raise

    def restore(self, *, require_unchanged: bool = True) -> None:
        if not self._owned:
            return
        error: Exception | None = None
        try:
            observed_interval = sys.getswitchinterval()
            self._scheduler_mutated = (
                require_unchanged
                and self._effective_interval is not None
                and observed_interval != self._effective_interval
            )
            if self._original_interval is None:
                raise RuntimeError("Phase04-stage observer scheduler differs")
            sys.setswitchinterval(self._original_interval)
            self._restored_interval = sys.getswitchinterval()
            if self._restored_interval != self._original_interval:
                raise RuntimeError("Phase04-stage observer scheduler differs")
        except Exception as caught:
            error = caught
        try:
            observed_gc_enabled = gc.isenabled()
            self._gc_mutated = (
                require_unchanged
                and self._effective_gc_enabled is not None
                and observed_gc_enabled is not self._effective_gc_enabled
            )
            if self._original_gc_enabled is None:
                raise RuntimeError("Phase04-stage observer GC differs")
            if self._original_gc_enabled:
                gc.enable()
            else:
                gc.disable()
            self._restored_gc_enabled = gc.isenabled()
            if self._restored_gc_enabled is not self._original_gc_enabled:
                raise RuntimeError("Phase04-stage observer GC differs")
        except Exception as caught:
            error = error or caught
        try:
            _EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK.release()
            self._owned = False
        except Exception as caught:
            error = error or caught
        if error is not None:
            raise RuntimeError(
                "Phase04-stage observer runtime restoration failed "
                f"error_type={type(error).__name__}"
            ) from None
        if self._scheduler_mutated or self._gc_mutated:
            raise RuntimeError("Phase04-stage observer runtime changed externally")

    @property
    def record(self) -> dict[str, Any]:
        if (
            self._owned
            or self._original_interval is None
            or self._effective_interval is None
            or self._restored_interval is None
            or self._original_gc_enabled is None
            or self._effective_gc_enabled is not False
            or self._restored_gc_enabled is not self._original_gc_enabled
            or self._collected_objects is None
            or self._main_thread_qos_record is None
        ):
            raise RuntimeError("Phase04-stage observer runtime is incomplete")
        return {
            "scope": EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE,
            "main_thread_qos": deepcopy(self._main_thread_qos_record),
            "scheduler": {
                "requested_interval_hex": (
                    EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
                ),
                "original_interval_hex": self._original_interval.hex(),
                "effective_interval_hex": self._effective_interval.hex(),
                "restored_interval_hex": self._restored_interval.hex(),
                "restoration_completed": True,
                "external_mutation_observed": self._scheduler_mutated,
            },
            "cyclic_gc": {
                "original_enabled": self._original_gc_enabled,
                "effective_enabled": self._effective_gc_enabled,
                "restored_enabled": self._restored_gc_enabled,
                "pre_window_collection_performed": self._original_gc_enabled,
                "pre_window_collected_objects": self._collected_objects,
                "restoration_completed": True,
                "external_mutation_observed": self._gc_mutated,
            },
        }


def _external_rss_observer_identity() -> dict[str, Any]:
    import psutil

    process = psutil.Process(os.getpid())
    create_time = process.create_time()
    if (
        psutil.__version__ != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        or type(create_time) not in {int, float}
        or type(create_time) is bool
        or not math.isfinite(float(create_time))
        or create_time <= 0
    ):
        raise RuntimeError("Phase04-stage observer identity differs")
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "process_create_time_ns": int(round(float(create_time) * 1e9)),
        "pgid": os.getpgrp(),
        "sid": os.getsid(0),
        "platform": sys.platform,
        "source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
    }


def _observer_generic_failure_summary(
    sampler: _Phase04StageRSSSampler | None,
) -> dict[str, Any]:
    if sampler is not None:
        summary = sampler.failure_summary
        if summary is not None:
            return summary
    return {
        "lane": "observer_process",
        "cause_code": "observer_operation_failed",
        "error_type": "RuntimeError",
        "observed_gap_ns": None,
        "hard_gap_ns": None,
        "accepted_continuous_count": 0,
        "last_accepted_async_ns": None,
        "classified_lane_failure": None,
    }


def _validate_observer_failure_summary(
    value: Any,
    *,
    retained_classified_lane_failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "lane",
        "cause_code",
        "error_type",
        "observed_gap_ns",
        "hard_gap_ns",
        "accepted_continuous_count",
        "last_accepted_async_ns",
        "classified_lane_failure",
    }
    allowed_lanes = {
        "observer_process",
        "current_rss",
        "child_observer",
        "current_rss_handoff",
        "synchronous_boundary",
        "thread_start",
    }
    if type(value) is not dict or set(value) != fields:
        raise RuntimeError("Phase04-stage observer failure fields differ")
    lane = value.get("lane")
    cause_code = value.get("cause_code")
    error_type = value.get("error_type")
    observed_gap_ns = value.get("observed_gap_ns")
    hard_gap_ns = value.get("hard_gap_ns")
    accepted_count = value.get("accepted_continuous_count")
    last_accepted_ns = value.get("last_accepted_async_ns")
    embedded_classified_lane_failure = value.get("classified_lane_failure")
    if (
        embedded_classified_lane_failure is not None
        and retained_classified_lane_failure is not None
    ):
        raise RuntimeError(
            "Phase04-stage observer classified failure is duplicated"
        )
    classified_lane_failure = (
        retained_classified_lane_failure
        if retained_classified_lane_failure is not None
        else embedded_classified_lane_failure
    )
    if (
        lane not in allowed_lanes
        or type(cause_code) is not str
        or not re.fullmatch(r"[a-z0-9_]{1,128}", cause_code)
        or type(error_type) is not str
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", error_type)
        or type(accepted_count) is not int
        or not 0 <= accepted_count <= 1_000_000_000
        or (
            last_accepted_ns is not None
            and (type(last_accepted_ns) is not int or last_accepted_ns < 0)
        )
        or (accepted_count == 0 and last_accepted_ns is not None)
        or (accepted_count > 0 and last_accepted_ns is None)
    ):
        raise RuntimeError("Phase04-stage observer failure custody differs")
    if classified_lane_failure is not None:
        try:
            classified_lane_failure = rss_lane.validate_failure_summary(
                classified_lane_failure
            )
        except Exception as error:
            raise RuntimeError(
                "Phase04-stage observer classified failure differs"
            ) from error
        if (
            classified_lane_failure["lane"] != lane
            or classified_lane_failure["cause_code"] != cause_code
            or classified_lane_failure["error_type"] != error_type
            or classified_lane_failure["observed_gap_ns"] != observed_gap_ns
            or classified_lane_failure["hard_gap_ns"] != hard_gap_ns
            or classified_lane_failure["accepted_continuous_count"]
            != accepted_count
            or classified_lane_failure["last_accepted_async_ns"]
            != last_accepted_ns
            or type(classified_lane_failure.get("runtime")) is not dict
        ):
            raise RuntimeError(
                "Phase04-stage observer classified failure custody differs"
            )
    if (observed_gap_ns is None) != (hard_gap_ns is None):
        raise RuntimeError("Phase04-stage observer failure gap differs")
    if observed_gap_ns is not None and (
        type(observed_gap_ns) is not int
        or type(hard_gap_ns) is not int
        or observed_gap_ns <= hard_gap_ns
    ):
        raise RuntimeError("Phase04-stage observer failure gap differs")
    if classified_lane_failure is not None:
        return deepcopy(value)
    gap_causes = {
        (
            "current_rss",
            "rss_sampling_cadence_exceeded",
        ): PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS,
        (
            "current_rss",
            "rss_terminal_cadence_exceeded",
        ): PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS,
        (
            "child_observer",
            "child_observer_cadence_exceeded",
        ): PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS,
        (
            "child_observer",
            "child_observer_scan_duration_exceeded",
        ): PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS,
        (
            "child_observer",
            "child_observer_terminal_cadence_exceeded",
        ): PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS,
    }
    nongap_causes = {
        ("observer_process", "observer_operation_failed"),
        ("current_rss", "current_rss_operation_failed"),
        ("child_observer", "child_observer_operation_failed"),
        ("current_rss_handoff", "current_rss_handoff_failed"),
        (
            "synchronous_boundary",
            "synchronous_boundary_operation_failed",
        ),
        ("thread_start", "sampler_thread_start_failed"),
    }
    semantic_key = (lane, cause_code)
    if semantic_key in gap_causes:
        if hard_gap_ns != gap_causes[semantic_key]:
            raise RuntimeError("Phase04-stage observer failure gap differs")
    elif semantic_key in nongap_causes:
        if observed_gap_ns is not None or hard_gap_ns is not None:
            raise RuntimeError("Phase04-stage observer failure gap differs")
    else:
        raise RuntimeError("Phase04-stage observer failure cause differs")
    return deepcopy(value)


def _validate_current_rss_lane_failure_custody(
    value: Any,
) -> dict[str, Any]:
    """Validate one bounded lane bundle without duplicating its failure body."""

    fields = {
        "schema_id",
        "classification",
        "lane_identity",
        "lane_lifecycle",
        "lane_protocol",
        "qualification_runtime_commitment",
        "transaction_custody",
        "partial_state",
        "cleanup",
    }
    if type(value) is not dict or set(value) != fields:
        raise RuntimeError("Phase04-stage lane failure custody fields differ")
    if value.get("schema_id") != CURRENT_RSS_LANE_FAILURE_CUSTODY_SCHEMA_ID:
        raise RuntimeError("Phase04-stage lane failure custody schema differs")
    try:
        identity = rss_lane.validate_lane_identity(value.get("lane_identity"))
        protocol = rss_lane.validate_protocol_custody(
            value.get("lane_protocol")
        )
    except Exception as error:
        raise RuntimeError(
            "Phase04-stage lane failure custody proof differs"
        ) from error
    lifecycle = value.get("lane_lifecycle")
    if lifecycle is not None:
        try:
            lifecycle = rss_lane.validate_lifecycle(lifecycle)
        except Exception as error:
            raise RuntimeError(
                "Phase04-stage lane failure lifecycle differs"
            ) from error
    classification = value.get("classification")
    if type(classification) is not dict or set(classification) != {
        "primary_classified_failure_count",
        "primary_classified_failure_location",
        "primary_classified_failure_sha256",
    }:
        raise RuntimeError("Phase04-stage lane failure classification differs")
    classified_count = classification.get(
        "primary_classified_failure_count"
    )
    if classified_count not in {0, 1} or type(classified_count) is not int:
        raise RuntimeError("Phase04-stage lane failure classification differs")
    try:
        transcript = rss_lane._decode_protocol_transcript(protocol)
    except Exception as error:
        raise RuntimeError(
            "Phase04-stage lane failure transcript differs"
        ) from error
    error_responses = [
        exchange["response"]
        for exchange in transcript
        if exchange["response"].get("status") == "error"
    ]
    if len(error_responses) != classified_count:
        raise RuntimeError("Phase04-stage lane failure count differs")
    classified_failure: dict[str, Any] | None = None
    if classified_count == 1:
        try:
            classified_failure = rss_lane.validate_failure_summary(
                error_responses[0].get("failure_summary"),
                require_runtime=True,
            )
        except Exception as error:
            raise RuntimeError(
                "Phase04-stage lane classified failure differs"
            ) from error
        if (
            classification.get("primary_classified_failure_location")
            != "lane_protocol.terminal_error_response.failure_summary"
            or classification.get("primary_classified_failure_sha256")
            != _sha256_bytes(_canonical_bytes(classified_failure))
        ):
            raise RuntimeError(
                "Phase04-stage lane classified failure custody differs"
            )
    elif (
        classification.get("primary_classified_failure_location") is not None
        or classification.get("primary_classified_failure_sha256") is not None
    ):
        raise RuntimeError("Phase04-stage lane failure absence differs")

    transaction = value.get("transaction_custody")
    transaction_fields = {
        "schema_id",
        "issued_operation_count",
        "completed_operation_count",
        "protocol_exchange_count",
        "bootstrap_bind_exchange_count",
        "first_failed_transaction",
        "active_transaction_at_seal",
    }
    if type(transaction) is not dict or set(transaction) != transaction_fields:
        raise RuntimeError("Phase04-stage lane transaction custody differs")
    issued = transaction.get("issued_operation_count")
    completed = transaction.get("completed_operation_count")
    if (
        transaction.get("schema_id")
        != EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID
        or type(issued) is not int
        or type(completed) is not int
        or not 0 <= completed <= issued <= rss_lane.MAXIMUM_EXCHANGES - 1
        or transaction.get("bootstrap_bind_exchange_count") != 1
        or type(transaction.get("bootstrap_bind_exchange_count")) is not int
        or transaction.get("protocol_exchange_count")
        != protocol["exchange_count"]
        or protocol["exchange_count"] != completed + 1
        or transaction.get("active_transaction_at_seal") is not None
    ):
        raise RuntimeError("Phase04-stage lane transaction custody differs")
    failed_transaction = transaction.get("first_failed_transaction")
    if failed_transaction is not None:
        if type(failed_transaction) is not dict or set(failed_transaction) != {
            "sequence",
            "operation",
            "state",
            "completed_exchange_count_before",
            "completed_exchange_count_after",
        }:
            raise RuntimeError("Phase04-stage lane failed transaction differs")
        before = failed_transaction.get("completed_exchange_count_before")
        after = failed_transaction.get("completed_exchange_count_after")
        state = failed_transaction.get("state")
        if (
            type(failed_transaction.get("sequence")) is not int
            or not 1 <= failed_transaction["sequence"] <= issued
            or failed_transaction.get("operation") not in rss_lane.OPERATIONS
            or state
            not in {
                "committed_error_response",
                "committed_invalid_response",
                "request_in_flight_or_partial",
            }
            or type(before) is not int
            or type(after) is not int
            or not 1 <= before <= after <= protocol["exchange_count"]
            or (state.startswith("committed_") and after != before + 1)
            or (state == "request_in_flight_or_partial" and after != before)
        ):
            raise RuntimeError("Phase04-stage lane failed transaction differs")
    elif issued != completed:
        raise RuntimeError("Phase04-stage lane partial transaction is absent")

    partial = value.get("partial_state")
    if type(partial) is not dict or set(partial) != {
        "qualification_committed",
        "qualification_sha256",
        "last_committed_summary_sha256",
    }:
        raise RuntimeError("Phase04-stage lane partial state differs")
    qualification_committed = partial.get("qualification_committed")
    qualification_sha256 = partial.get("qualification_sha256")
    last_summary_sha256 = partial.get("last_committed_summary_sha256")
    if (
        type(qualification_committed) is not bool
        or (qualification_committed and type(qualification_sha256) is not str)
        or (not qualification_committed and qualification_sha256 is not None)
        or (
            qualification_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", qualification_sha256) is None
        )
        or (
            last_summary_sha256 is not None
            and (
                type(last_summary_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", last_summary_sha256) is None
            )
        )
    ):
        raise RuntimeError("Phase04-stage lane partial state differs")
    retained_qualification: dict[str, Any] | None = None
    for exchange in transcript:
        if (
            exchange["request"]["operation"] == "PREPARE"
            and exchange["response"]["status"] == "ok"
        ):
            retained_qualification = rss_lane.validate_qualification(
                exchange["response"]["record"]
            )
            break
    if retained_qualification is None and classified_failure is not None:
        retained_qualification = classified_failure["qualification_attempt"]
    commitment = value.get("qualification_runtime_commitment")
    if retained_qualification is None:
        if commitment is not None:
            raise RuntimeError(
                "Phase04-stage lane runtime commitment differs"
            )
    else:
        try:
            validated_commitment = (
                rss_lane.validate_qualification_runtime_commitment(
                    commitment,
                    qualification=retained_qualification,
                )
            )
        except Exception as error:
            raise RuntimeError(
                "Phase04-stage lane runtime commitment differs"
            ) from error
        if (
            qualification_committed
            != any(
                exchange["request"]["operation"] == "PREPARE"
                and exchange["response"]["status"] == "ok"
                for exchange in transcript
            )
            or (
                qualification_committed
                and qualification_sha256
                != validated_commitment["qualification_sha256"]
            )
        ):
            raise RuntimeError(
                "Phase04-stage lane qualification custody differs"
            )

    cleanup = value.get("cleanup")
    if type(cleanup) is not dict or set(cleanup) != {
        "sampler_abort_completed",
        "sampler_quiescence_proved",
        "child_threads_quiesced",
        "lane_process_quiesced",
        "lane_lifecycle_error_type",
        "cleanup_error_types",
    }:
        raise RuntimeError("Phase04-stage lane cleanup custody differs")
    cleanup_error_types = cleanup.get("cleanup_error_types")
    if (
        any(
            type(cleanup.get(field)) is not bool
            for field in (
                "sampler_abort_completed",
                "sampler_quiescence_proved",
                "child_threads_quiesced",
                "lane_process_quiesced",
            )
        )
        or type(cleanup_error_types) is not list
        or len(cleanup_error_types) > 8
        or any(
            type(name) is not str
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name) is None
            for name in cleanup_error_types
        )
        or (
            cleanup.get("lane_lifecycle_error_type") is not None
            and (
                type(cleanup["lane_lifecycle_error_type"]) is not str
                or re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_]{0,127}",
                    cleanup["lane_lifecycle_error_type"],
                )
                is None
            )
        )
        or (
            lifecycle is not None
            and cleanup["lane_process_quiesced"] is not True
        )
        or (
            lifecycle is None
            and cleanup["lane_process_quiesced"] is True
            and cleanup.get("lane_lifecycle_error_type") is None
        )
        or identity["pid"] <= 1
    ):
        raise RuntimeError("Phase04-stage lane cleanup custody differs")
    return deepcopy(value)


def _classified_failure_from_lane_custody(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    custody = _validate_current_rss_lane_failure_custody(dict(value))
    if custody["classification"]["primary_classified_failure_count"] == 0:
        return None
    transcript = rss_lane._decode_protocol_transcript(
        custody["lane_protocol"]
    )
    failures = [
        exchange["response"]["failure_summary"]
        for exchange in transcript
        if exchange["response"].get("status") == "error"
    ]
    if len(failures) != 1:
        raise RuntimeError("Phase04-stage lane classified failure count differs")
    return rss_lane.validate_failure_summary(
        failures[0],
        require_runtime=True,
    )


def _validate_observer_bind_payload(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
    import psutil

    if type(payload) is not dict or set(payload) != {
        "controller_identity",
        "worker_ownership",
        "worker_lifetime_lease",
    }:
        raise RuntimeError("Phase04-stage observer BIND payload differs")
    controller = payload["controller_identity"]
    ownership = payload["worker_ownership"]
    lifetime_lease = payload["worker_lifetime_lease"]
    controller_fields = {
        "pid",
        "process_create_time_ns",
        "pgid",
        "sid",
        "platform",
        "identity_source",
        "identity_source_version",
    }
    ownership_fields = {
        "schema_id",
        "owner_pid",
        "owner_pgid",
        "owner_sid",
        "leader_pid",
        "leader_create_time_ns",
        "pgid",
        "sid",
    }
    if (
        type(controller) is not dict
        or set(controller) != controller_fields
        or type(ownership) is not dict
        or set(ownership) != ownership_fields
        or any(
            type(controller.get(field)) is not int
            or controller[field] < 1
            for field in (
                "pid",
                "process_create_time_ns",
                "pgid",
                "sid",
            )
        )
        or any(
            type(ownership.get(field)) is not int
            or ownership[field] < 1
            for field in ownership_fields - {"schema_id"}
        )
        or controller.get("pid") != os.getppid()
        or controller.get("platform") != sys.platform
        or controller.get("identity_source")
        != EXTERNAL_RSS_MONITOR_CONTROLLER_IDENTITY_SOURCE
        or controller.get("identity_source_version")
        != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
        or ownership.get("schema_id") != WORKER_GROUP_IDENTITY_SCHEMA_ID
        or ownership.get("owner_pid") != controller["pid"]
        or ownership.get("owner_pgid") != controller["pgid"]
        or ownership.get("owner_sid") != controller["sid"]
        or ownership.get("leader_pid") <= 1
        or ownership.get("leader_pid") == controller["pid"]
        or ownership.get("pgid") != ownership.get("leader_pid")
        or ownership.get("sid") != ownership.get("leader_pid")
    ):
        raise RuntimeError("Phase04-stage observer BIND custody differs")
    parent = psutil.Process(controller["pid"])
    target = psutil.Process(ownership["leader_pid"])
    if (
        int(round(float(parent.create_time()) * 1e9))
        != controller["process_create_time_ns"]
        or os.getpgid(parent.pid) != controller["pgid"]
        or os.getsid(parent.pid) != controller["sid"]
        or int(round(float(target.create_time()) * 1e9))
        != ownership["leader_create_time_ns"]
        or target.ppid() != ownership["owner_pid"]
        or os.getpgid(target.pid) != ownership["pgid"]
        or os.getsid(target.pid) != ownership["sid"]
    ):
        raise RuntimeError("Phase04-stage observer BIND identity differs")
    try:
        validated_lease = _validate_worker_lifetime_lease(
            lifetime_lease,
            ownership=ownership,
            require_success=False,
        )
    except ValueError as error:
        raise RuntimeError(
            "Phase04-stage observer BIND lifetime lease differs"
        ) from error
    if (
        validated_lease["state"] != "active"
        or validated_lease["events"]
        != ["lease_acquired", "monitor_bound"]
        or validated_lease[
            "monitor_bound_before_worker_bootstrap_release"
        ]
        is not False
        or validated_lease["failure_preserved_unreaped"] is not False
        or any(
            validated_lease["forbidden_while_active_attempt_counts"].values()
        )
    ):
        raise RuntimeError("Phase04-stage observer BIND lifetime lease differs")
    return (
        deepcopy(controller),
        deepcopy(ownership),
        validated_lease,
        target,
    )


def _run_external_rss_observer(descriptor: int) -> int:
    """Serve one exact-worker sampler in a dedicated controller-owned process."""

    channel: socket.socket | None = None
    runtime = _ExternalRSSObserverRuntime()
    sampler: _Phase04StageRSSSampler | None = None
    current_lane: rss_lane.CurrentRSSLaneProcess | None = None
    worker_identity: dict[str, Any] | None = None
    state = "created"
    expected_sequence = 1
    exchange_count = 0
    duplex_exchange_bytes = 0
    runtime_restored = False
    try:
        if type(descriptor) is not int or descriptor <= 2:
            return 1
        os.set_inheritable(descriptor, False)
        channel = socket.socket(fileno=descriptor)
        if (
            channel.family != socket.AF_UNIX
            or channel.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
            != socket.SOCK_STREAM
        ):
            return 1
        runtime.acquire()
        observer_identity = _external_rss_observer_identity()
        while True:
            # The worker's overall deadline and exact ownership cleanup bound
            # lifetime.  PREPARE-to-START can include legitimate document load
            # work, so an idle service read must not impose a shorter deadline.
            channel.settimeout(None)
            request = _external_monitor_message(
                _recv_external_monitor_frame(
                    channel,
                    maximum_frame_bytes=(
                        EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                ),
                label="observer request",
                maximum_frame_bytes=(
                    EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                ),
            )
            if set(request) != {"schema_id", "sequence", "operation", "payload"}:
                raise RuntimeError("Phase04-stage observer request fields differ")
            sequence = request.get("sequence")
            operation = request.get("operation")
            payload = request.get("payload")
            if (
                request.get("schema_id") != EXTERNAL_RSS_OBSERVER_SCHEMA_ID
                or type(sequence) is not int
                or sequence != expected_sequence
                or sequence > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
                or operation not in EXTERNAL_RSS_OBSERVER_OPERATIONS
                or type(payload) is not dict
            ):
                raise RuntimeError("Phase04-stage observer request differs")
            expected_sequence += 1
            # Response transmission is still an individually bounded IPC step.
            channel.settimeout(EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS)
            record: dict[str, Any] | None = None
            try:
                if operation == "BIND":
                    if state != "created":
                        raise RuntimeError("Phase04-stage observer BIND differs")
                    _controller, ownership, lifetime_lease, target = (
                        _validate_observer_bind_payload(payload)
                    )
                    worker_identity = (
                        _external_monitor_worker_identity_from_ownership(
                            ownership
                        )
                    )
                    lane_environment = os.environ.copy()
                    lane_environment.update(OFFLINE_ENVIRONMENT)
                    lane_environment.update(
                        WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT
                    )
                    lane_environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    current_lane = rss_lane.CurrentRSSLaneProcess.spawn(
                        worker_ownership=ownership,
                        worker_lifetime_lease=lifetime_lease,
                        parent_identity={
                            field: observer_identity[field]
                            for field in (
                                "pid",
                                "process_create_time_ns",
                                "pgid",
                                "sid",
                                "platform",
                                "source_version",
                            )
                        },
                        cwd=WORKSPACE,
                        environment=lane_environment,
                    )
                    sampler = _Phase04StageRSSSampler(
                        process=target,
                        source_version=PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
                        external_target=True,
                        current_rss_lane=current_lane,
                    )
                    state = "bound"
                    record = {
                        "observer_identity": observer_identity,
                        "worker_identity": worker_identity,
                    }
                elif operation == "PREPARE":
                    if (
                        sampler is None
                        or state != "bound"
                        or payload != worker_identity
                    ):
                        raise RuntimeError("Phase04-stage observer PREPARE differs")
                    sampler.prepare()
                    state = "prepared"
                elif operation == "START":
                    if sampler is None or state != "prepared" or set(payload) != {
                        "first_boundary_component",
                        "hwm_bytes",
                        "children_rusage",
                    }:
                        raise RuntimeError("Phase04-stage observer START differs")
                    hwm_value = payload["hwm_bytes"]
                    children_value = payload["children_rusage"]
                    sampler._hwm_reader = lambda value=hwm_value: value
                    sampler._children_rusage_reader = (
                        lambda value=deepcopy(children_value): deepcopy(value)
                    )
                    sampler.start(payload["first_boundary_component"])
                    state = "started"
                elif operation == "BOUNDARY":
                    if sampler is None or state != "started" or payload:
                        raise RuntimeError("Phase04-stage observer BOUNDARY differs")
                    sampler.sample_synchronous_boundary()
                elif operation == "PARSE":
                    if sampler is None or state != "started" or set(payload) != {
                        "hwm_bytes"
                    }:
                        raise RuntimeError("Phase04-stage observer PARSE differs")
                    sampler._hwm_reader = lambda value=payload["hwm_bytes"]: value
                    record = sampler.record_parse_checkpoint()
                    state = "parsed"
                elif operation == "OUTPUT":
                    if sampler is None or state != "parsed" or payload:
                        raise RuntimeError("Phase04-stage observer OUTPUT differs")
                    sampler.sample_output_boundary()
                elif operation == "FINISH":
                    if sampler is None or state != "parsed" or set(payload) != {
                        "hwm_bytes",
                        "children_rusage",
                    }:
                        raise RuntimeError("Phase04-stage observer FINISH differs")
                    hwm_value = payload["hwm_bytes"]
                    children_value = payload["children_rusage"]
                    sampler._hwm_reader = lambda value=hwm_value: value
                    sampler._children_rusage_reader = (
                        lambda value=deepcopy(children_value): deepcopy(value)
                    )
                    rss_record = sampler.finish()
                    sampler.require_quiesced()
                    runtime.restore()
                    runtime_restored = True
                    state = "finished"
                    runtime_custody = runtime.record
                    runtime_custody["sampler_thread_qos"] = (
                        sampler.thread_qos_record
                    )
                    runtime_custody["current_rss_lane"] = (
                        sampler.current_rss_lane_custody
                    )
                    record = {
                        "observer_identity": observer_identity,
                        "rss_record": rss_record,
                        "runtime_custody": runtime_custody,
                    }
                elif operation == "ABORT":
                    if state in {"finished", "aborted"} or payload:
                        raise RuntimeError("Phase04-stage observer ABORT differs")
                    if sampler is not None:
                        sampler.abort()
                        sampler.require_quiesced()
                    runtime.restore()
                    runtime_restored = True
                    state = "aborted"
                else:
                    raise RuntimeError("Phase04-stage observer operation differs")
            except Exception:
                # Custody is serialized only after every sampler lane has had
                # its bounded cleanup opportunity.  This prevents a PREPARE
                # or measurement failure from racing a later lane read while
                # its evidence is being materialized.
                cleanup_error_types: list[str] = []
                sampler_abort_completed = sampler is None
                sampler_quiescence_proved = sampler is None
                if sampler is not None:
                    try:
                        sampler.abort()
                        sampler_abort_completed = True
                    except Exception as cleanup_error:
                        cleanup_error_types.append(type(cleanup_error).__name__)
                    try:
                        sampler.require_quiesced()
                        sampler_quiescence_proved = True
                    except Exception as cleanup_error:
                        cleanup_error_types.append(type(cleanup_error).__name__)
                try:
                    runtime.restore()
                    runtime_restored = True
                except Exception as cleanup_error:
                    cleanup_error_types.append(type(cleanup_error).__name__)
                failure_record = (
                    None
                    if sampler is None
                    else sampler.failed_current_rss_lane_custody(
                        sampler_abort_completed=sampler_abort_completed,
                        sampler_quiescence_proved=sampler_quiescence_proved,
                        cleanup_error_types=cleanup_error_types,
                    )
                )
                retained_classified = _classified_failure_from_lane_custody(
                    failure_record
                )
                projected_summary = _observer_generic_failure_summary(sampler)
                embedded_classified = projected_summary.get(
                    "classified_lane_failure"
                )
                if retained_classified is not None:
                    if (
                        type(embedded_classified) is not dict
                        or _canonical_bytes(embedded_classified)
                        != _canonical_bytes(retained_classified)
                    ):
                        raise RuntimeError(
                            "Phase04-stage observer failure projection differs"
                        )
                    projected_summary = deepcopy(projected_summary)
                    projected_summary["classified_lane_failure"] = None
                failure_summary = _validate_observer_failure_summary(
                    projected_summary,
                    retained_classified_lane_failure=retained_classified,
                )
                response = {
                    "schema_id": EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
                    "sequence": sequence,
                    "operation": operation,
                    "status": "error",
                    "record": failure_record,
                    "failure_summary": failure_summary,
                }
                exchange_count += 1
                duplex_exchange_bytes += len(
                    _canonical_bytes({"request": request, "response": response})
                )
                if (
                    exchange_count > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
                    or duplex_exchange_bytes
                    > EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
                ):
                    return 1
                channel.sendall(
                    _external_monitor_frame(
                        response,
                        maximum_frame_bytes=(
                            EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                        ),
                    )
                )
                return 1
            response = {
                "schema_id": EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
                "sequence": sequence,
                "operation": operation,
                "status": "ok",
                "record": record,
                "failure_summary": None,
            }
            exchange_count += 1
            duplex_exchange_bytes += len(
                _canonical_bytes({"request": request, "response": response})
            )
            if (
                exchange_count > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
                or duplex_exchange_bytes
                > EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
            ):
                return 1
            channel.sendall(
                _external_monitor_frame(
                    response,
                    maximum_frame_bytes=(
                        EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                )
            )
            if operation in {"FINISH", "ABORT"}:
                return 0
    except BaseException:
        return 1
    finally:
        if sampler is not None:
            try:
                sampler.abort()
            except BaseException:
                pass
        if current_lane is not None and not current_lane.quiesced:
            try:
                current_lane.abort()
                current_lane.quiesce()
            except BaseException:
                pass
        if not runtime_restored:
            try:
                runtime.restore(require_unchanged=False)
            except BaseException:
                pass
        if channel is not None:
            try:
                channel.close()
            except OSError:
                pass


class _ExternalRSSObserverSpawnFailure(RuntimeError):
    """Classify whether a failed observer launch is safe for worker release."""

    def __init__(self, *, worker_release_safe: bool) -> None:
        super().__init__("Phase04-stage observer spawn failed")
        self.worker_release_safe = worker_release_safe


class _ExternalRSSObserverProcess:
    """Controller-side bounded client for one dedicated observer process."""

    def __init__(
        self,
        channel: socket.socket,
        process: Any,
        identity: Mapping[str, Any],
        stdout_file: Any,
        stderr_file: Any,
    ) -> None:
        self._channel: socket.socket | None = channel
        self._process = process
        self._identity = deepcopy(dict(identity))
        self._stdout_file: Any | None = stdout_file
        self._stderr_file: Any | None = stderr_file
        self._sequence = 0
        self._terminal = False
        self._quiesced = False
        self._expected_return_code: int | None = None
        self._observed_return_code: int | None = None
        self._termination_mode: str | None = None
        self._process_group_absent = False
        self._exit_status_validated = False
        self._failure_summary: dict[str, Any] | None = None
        self._failure_record: dict[str, Any] | None = None
        self._runtime_custody: dict[str, Any] | None = None
        self._diagnostics: dict[str, Any] | None = None
        self._diagnostic_streams_closed = False
        self._completed_response_count = 0
        self._active_transaction: dict[str, Any] | None = None
        self._first_partial_transaction: dict[str, Any] | None = None

    @classmethod
    def spawn(
        cls,
        ownership: Mapping[str, Any],
        controller_identity: Mapping[str, Any],
        worker_lifetime_lease: Mapping[str, Any],
    ) -> _ExternalRSSObserverProcess:
        import psutil

        controller_channel: socket.socket | None = None
        observer_channel: socket.socket | None = None
        stdout_file: Any | None = None
        stderr_file: Any | None = None
        process: Any | None = None
        client: _ExternalRSSObserverProcess | None = None
        try:
            controller_channel, observer_channel = socket.socketpair(
                socket.AF_UNIX,
                socket.SOCK_STREAM,
            )
            descriptor = observer_channel.fileno()
            environment = os.environ.copy()
            environment.update(OFFLINE_ENVIRONMENT)
            environment.update(WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "tests.fixtures.phase_04.tables.metrics",
                    "--rss-observer-fd",
                    str(descriptor),
                ],
                cwd=WORKSPACE,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(descriptor,),
                start_new_session=True,
            )
            stdout_file = process.stdout
            stderr_file = process.stderr
            if stdout_file is None or stderr_file is None:
                raise RuntimeError(
                    "Phase04-stage observer diagnostic pipes are absent"
                )
            observer_channel.close()
            if observer_channel.fileno() == -1:
                observer_channel = None
            else:  # pragma: no cover - socket contract guard
                raise RuntimeError(
                    "Phase04-stage observer inherited channel remained open"
                )
            controller_channel.settimeout(
                EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
            )
            observed = psutil.Process(process.pid)
            identity = {
                "pid": process.pid,
                "parent_pid": observed.ppid(),
                "process_create_time_ns": int(
                    round(float(observed.create_time()) * 1e9)
                ),
                "pgid": os.getpgid(process.pid),
                "sid": os.getsid(process.pid),
                "platform": sys.platform,
                "source_version": PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION,
            }
            if (
                identity["parent_pid"] != os.getpid()
                or identity["pgid"] != process.pid
                or identity["sid"] != process.pid
            ):
                raise RuntimeError("Phase04-stage observer ownership differs")
            client = cls(
                controller_channel,
                process,
                identity,
                stdout_file,
                stderr_file,
            )
            bind_record = client.request(
                "BIND",
                {
                    "controller_identity": dict(controller_identity),
                    "worker_ownership": dict(ownership),
                    "worker_lifetime_lease": dict(worker_lifetime_lease),
                },
            )
            if (
                type(bind_record) is not dict
                or set(bind_record) != {"observer_identity", "worker_identity"}
                or bind_record["observer_identity"] != identity
                or bind_record["worker_identity"]
                != _external_monitor_worker_identity_from_ownership(ownership)
            ):
                raise RuntimeError("Phase04-stage observer BIND response differs")
            return client
        except BaseException as primary_error:
            cleanup_safe = process is None
            cleanup_error: BaseException | None = None
            deferred_cancellations: list[BaseException] = []
            if observer_channel is not None:
                try:
                    _call_deferring_cancellation(
                        observer_channel.close,
                        deferred_cancellations,
                    )
                except OSError as error:
                    cleanup_error = error
            if client is not None:
                try:
                    _call_deferring_cancellation(
                        client.quiesce,
                        deferred_cancellations,
                    )
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                cleanup_safe = client.quiesced
            else:
                if controller_channel is not None:
                    try:
                        _call_deferring_cancellation(
                            controller_channel.close,
                            deferred_cancellations,
                        )
                    except OSError as error:
                        cleanup_error = cleanup_error or error
                if process is not None:
                    try:
                        _call_deferring_cancellation(
                            lambda: os.killpg(process.pid, signal.SIGKILL),
                            deferred_cancellations,
                        )
                    except ProcessLookupError:
                        pass
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                    try:
                        _call_deferring_cancellation(
                            lambda: process.wait(timeout=1.0),
                            deferred_cancellations,
                        )
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                    try:
                        cleanup_safe = not _owned_worker_group_exists(
                            {"pgid": process.pid}
                        )
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                        cleanup_safe = False
                stream_close_complete = True
                for stream in (stdout_file, stderr_file):
                    if stream is None:
                        continue
                    try:
                        _call_deferring_cancellation(
                            stream.close,
                            deferred_cancellations,
                        )
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                    stream_close_complete = (
                        stream_close_complete and stream.closed
                    )
                cleanup_safe = cleanup_safe and stream_close_complete
            cancellation = (
                primary_error
                if not isinstance(primary_error, Exception)
                else (
                    deferred_cancellations[0]
                    if deferred_cancellations
                    else None
                )
            )
            if cancellation is not None:
                try:
                    setattr(
                        cancellation,
                        "worker_release_safe",
                        cleanup_safe,
                    )
                except Exception:
                    pass
                raise cancellation
            if cleanup_error is not None and not cleanup_safe:
                raise _ExternalRSSObserverSpawnFailure(
                    worker_release_safe=False
                ) from None
            raise _ExternalRSSObserverSpawnFailure(
                worker_release_safe=cleanup_safe
            ) from None

    @property
    def identity(self) -> dict[str, Any]:
        return deepcopy(self._identity)

    @property
    def failure_summary(self) -> dict[str, Any] | None:
        return deepcopy(self._failure_summary)

    @property
    def failure_record(self) -> dict[str, Any] | None:
        return deepcopy(self._failure_record)

    @property
    def transaction_custody(self) -> dict[str, Any]:
        partial = deepcopy(self._first_partial_transaction)
        active = deepcopy(self._active_transaction)
        if active is not None and partial is None:
            partial = {
                **active,
                "state": "request_in_flight_or_partial",
            }
        return {
            "schema_id": EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID,
            "issued_operation_count": self._sequence,
            "completed_operation_count": self._completed_response_count,
            "first_partial_transaction": partial,
            "active_transaction_at_snapshot": active,
        }

    @property
    def runtime_custody(self) -> dict[str, Any]:
        if self._runtime_custody is None:
            raise RuntimeError("Phase04-stage observer runtime custody is absent")
        return deepcopy(self._runtime_custody)

    @property
    def quiesced(self) -> bool:
        return self._quiesced

    @property
    def lifecycle_record(self) -> dict[str, Any]:
        if (
            not self._quiesced
            or self._observed_return_code is None
            or self._termination_mode is None
            or not self._process_group_absent
            or self._diagnostics is None
            or not self._diagnostic_streams_closed
        ):
            raise RuntimeError(
                "Phase04-stage observer lifecycle custody is incomplete"
            )
        return {
            "expected_return_code": self._expected_return_code,
            "observed_return_code": self._observed_return_code,
            "termination_mode": self._termination_mode,
            "process_reaped": True,
            "process_group_absent": self._process_group_absent,
            "exit_status_validated": self._exit_status_validated,
            "diagnostics": deepcopy(self._diagnostics),
        }

    def request(
        self,
        operation: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if (
            self._terminal
            or self._channel is None
            or operation not in EXTERNAL_RSS_OBSERVER_OPERATIONS
            or self._sequence >= EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
        ):
            raise RuntimeError("Phase04-stage observer request state differs")
        self._sequence += 1
        request = {
            "schema_id": EXTERNAL_RSS_OBSERVER_SCHEMA_ID,
            "sequence": self._sequence,
            "operation": operation,
            "payload": dict(payload),
        }
        transaction = {
            "sequence": self._sequence,
            "operation": operation,
        }
        self._active_transaction = transaction
        operation_timeout = (
            EXTERNAL_RSS_OBSERVER_QUALIFICATION_TIMEOUT_SECONDS
            if operation == "PREPARE"
            else EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
        )
        try:
            self._channel.settimeout(operation_timeout)
            self._channel.sendall(
                _external_monitor_frame(
                    request,
                    maximum_frame_bytes=(
                        EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                )
            )
            response = _external_monitor_message(
                _recv_external_monitor_frame(
                    self._channel,
                    maximum_frame_bytes=(
                        EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                    ),
                ),
                label="observer response",
                maximum_frame_bytes=(
                    EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
                ),
            )
        except Exception as error:
            if self._first_partial_transaction is None:
                self._first_partial_transaction = {
                    **transaction,
                    "state": "request_in_flight_or_partial",
                }
            self._active_transaction = None
            raise RuntimeError(
                "Phase04-stage observer IPC failed "
                f"error_type={type(error).__name__}"
            ) from None
        finally:
            if self._channel is not None:
                self._channel.settimeout(
                    EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
                )
        if (
            set(response) != {
                "schema_id",
                "sequence",
                "operation",
                "status",
                "record",
                "failure_summary",
            }
            or response.get("schema_id") != EXTERNAL_RSS_OBSERVER_SCHEMA_ID
            or response.get("sequence") != self._sequence
            or response.get("operation") != operation
            or response.get("status") not in {"ok", "error"}
        ):
            if self._first_partial_transaction is None:
                self._first_partial_transaction = {
                    **transaction,
                    "state": "response_received_invalid",
                }
            self._active_transaction = None
            raise RuntimeError("Phase04-stage observer response differs")
        self._completed_response_count += 1
        self._active_transaction = None
        if response["status"] == "error":
            try:
                failure_record = response.get("record")
                if failure_record is not None:
                    failure_record = _validate_current_rss_lane_failure_custody(
                        failure_record
                    )
                retained_classified = _classified_failure_from_lane_custody(
                    failure_record
                )
                summary = _validate_observer_failure_summary(
                    response.get("failure_summary"),
                    retained_classified_lane_failure=retained_classified,
                )
            except Exception:
                if self._first_partial_transaction is None:
                    self._first_partial_transaction = {
                        **transaction,
                        "state": "response_received_invalid",
                    }
                raise
            self._failure_summary = summary
            self._failure_record = failure_record
            self._terminal = True
            self._expected_return_code = 1
            raise RuntimeError(
                "Phase04-stage observer failed "
                f"failure_code={summary.get('cause_code')}"
            ) from None
        if response.get("failure_summary") is not None:
            raise RuntimeError("Phase04-stage observer success differs")
        record = response.get("record")
        if operation in {"PREPARE", "START", "BOUNDARY", "OUTPUT", "ABORT"}:
            if record is not None:
                raise RuntimeError("Phase04-stage observer success record differs")
        elif operation in {"BIND", "PARSE"} and type(record) is not dict:
            raise RuntimeError("Phase04-stage observer success record differs")
        if operation == "FINISH":
            if type(record) is not dict or set(record) != {
                "observer_identity",
                "rss_record",
                "runtime_custody",
            }:
                raise RuntimeError("Phase04-stage observer FINISH differs")
            if record["observer_identity"] != self._identity:
                raise RuntimeError("Phase04-stage observer identity changed")
            self._runtime_custody = deepcopy(record["runtime_custody"])
            self._terminal = True
            self._expected_return_code = 0
            return deepcopy(record["rss_record"])
        if operation == "ABORT":
            self._terminal = True
            self._expected_return_code = 0
        return deepcopy(record)

    def _collect_and_close_diagnostics(
        self,
        deferred_cancellations: list[BaseException],
    ) -> None:
        diagnostic_error: Exception | None = None
        if self._diagnostics is None:
            values: dict[str, Any] = {}
            for name, stream in (
                ("stdout", self._stdout_file),
                ("stderr", self._stderr_file),
            ):
                if stream is None or stream.closed:
                    raise RuntimeError(
                        "Phase04-stage observer diagnostic custody differs"
                    )
                def read_from_start(value: Any = stream) -> bytes:
                    if value.seekable():
                        value.seek(0)
                    return value.read(
                        MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES + 1
                    )

                raw = _call_deferring_cancellation(
                    read_from_start,
                    deferred_cancellations,
                )
                if type(raw) is not bytes:
                    raise RuntimeError(
                        "Phase04-stage observer diagnostic stream differs"
                    )
                capture_complete = (
                    len(raw) <= MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES
                )
                values[name] = {
                    "size_bytes": len(raw),
                    "sha256": _sha256_bytes(raw),
                    "line_count": len(raw.splitlines()),
                    "capture_complete": capture_complete,
                }
                if not capture_complete or raw:
                    diagnostic_error = diagnostic_error or RuntimeError(
                        "observer diagnostics were nonempty or exceeded"
                    )
            self._diagnostics = {
                "schema_id": OBSERVER_DIAGNOSTIC_SCHEMA_ID,
                "maximum_stream_bytes": MAXIMUM_OBSERVER_DIAGNOSTIC_BYTES,
                "capture_mode": (
                    "kernel_pipes_bounded_backpressure_read_after_reap"
                ),
                "streams_closed": False,
                **values,
            }
        for attribute in ("_stdout_file", "_stderr_file"):
            stream = getattr(self, attribute)
            if stream is None:
                continue
            try:
                _call_deferring_cancellation(
                    stream.close,
                    deferred_cancellations,
                )
            except Exception as error:
                diagnostic_error = diagnostic_error or error
            if stream.closed:
                setattr(self, attribute, None)
        self._diagnostic_streams_closed = (
            self._stdout_file is None and self._stderr_file is None
        )
        if self._diagnostics is not None:
            self._diagnostics["streams_closed"] = (
                self._diagnostic_streams_closed
            )
        if not self._diagnostic_streams_closed:
            diagnostic_error = diagnostic_error or RuntimeError(
                "observer diagnostic streams remained open"
            )
        if diagnostic_error is not None:
            raise diagnostic_error

    def quiesce(self) -> None:
        if self._quiesced:
            if not self._exit_status_validated:
                raise RuntimeError(
                    "Phase04-stage observer exit status differs"
                )
            return
        error: Exception | None = None
        deferred_cancellations: list[BaseException] = []
        if not self._terminal:
            try:
                self.request("ABORT", {})
            except Exception as caught:
                controlled_observer_failure = (
                    self._terminal
                    and self._expected_return_code == 1
                    and self._failure_summary is not None
                )
                if not controlled_observer_failure:
                    error = caught
            except BaseException as caught:
                deferred_cancellations.append(caught)
        if self._channel is not None:
            try:
                _call_deferring_cancellation(
                    self._channel.close,
                    deferred_cancellations,
                )
            except BaseException as caught:
                if isinstance(caught, Exception):
                    error = error or caught
                else:
                    deferred_cancellations.append(caught)
            descriptor: int | None = None
            try:
                descriptor = _call_deferring_cancellation(
                    self._channel.fileno,
                    deferred_cancellations,
                )
            except BaseException as caught:
                if isinstance(caught, Exception):
                    error = error or caught
                else:
                    deferred_cancellations.append(caught)
            if descriptor == -1:
                self._channel = None
        forced_termination = False
        retry_wait_before_signal = False
        return_code: int | None = None
        try:
            return_code = _call_deferring_cancellation(
                lambda: self._process.wait(timeout=2.0),
                deferred_cancellations,
            )
        except subprocess.TimeoutExpired:
            forced_termination = True
        except BaseException as caught:
            if isinstance(caught, Exception):
                error = error or caught
                retry_wait_before_signal = True
            else:
                deferred_cancellations.append(caught)
        if return_code is None and retry_wait_before_signal:
            try:
                return_code = _call_deferring_cancellation(
                    lambda: self._process.wait(timeout=1.0),
                    deferred_cancellations,
                )
            except subprocess.TimeoutExpired:
                forced_termination = True
            except BaseException as caught:
                forced_termination = True
                if isinstance(caught, Exception):
                    error = error or caught
                else:
                    deferred_cancellations.append(caught)
        if return_code is None:
            forced_termination = True
            try:
                _call_deferring_cancellation(
                    lambda: os.killpg(
                        self._identity["pgid"], signal.SIGKILL
                    ),
                    deferred_cancellations,
                )
                return_code = _call_deferring_cancellation(
                    lambda: self._process.wait(timeout=1.0),
                    deferred_cancellations,
                )
            except ProcessLookupError:
                try:
                    return_code = _call_deferring_cancellation(
                        lambda: self._process.wait(timeout=1.0),
                        deferred_cancellations,
                    )
                except BaseException as caught:
                    if isinstance(caught, Exception):
                        error = error or caught
                    else:
                        deferred_cancellations.append(caught)
            except Exception as caught:
                error = error or caught
                return_code = None
        if return_code is None:
            error = error or RuntimeError("observer process was not reaped")
        else:
            self._observed_return_code = return_code
            self._termination_mode = (
                "forced_sigkill" if forced_termination else "protocol_exit"
            )
            self._exit_status_validated = (
                not forced_termination
                and self._expected_return_code is not None
                and return_code == self._expected_return_code
            )
            if not self._exit_status_validated:
                error = error or RuntimeError("observer exit status differs")
        group_absent = False
        try:
            if _call_deferring_cancellation(
                lambda: _owned_worker_group_exists(
                    {"pgid": self._identity["pgid"]}
                ),
                deferred_cancellations,
            ):
                forced_termination = True
                self._termination_mode = "forced_descendant_cleanup"
                _call_deferring_cancellation(
                    lambda: os.killpg(
                        self._identity["pgid"], signal.SIGKILL
                    ),
                    deferred_cancellations,
                )
                deadline = time.monotonic() + 1.0
                while _call_deferring_cancellation(
                    lambda: _owned_worker_group_exists(
                        {"pgid": self._identity["pgid"]}
                    ),
                    deferred_cancellations,
                ):
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "observer process group remained present"
                        )
                    _call_deferring_cancellation(
                        lambda: threading.Event().wait(0.010),
                        deferred_cancellations,
                    )
                error = error or RuntimeError(
                    "observer descendant process was terminated"
                )
            group_absent = True
        except Exception as caught:
            error = error or caught
        try:
            self._collect_and_close_diagnostics(deferred_cancellations)
        except Exception as caught:
            error = error or caught
        self._process_group_absent = group_absent
        self._quiesced = (
            return_code is not None
            and group_absent
            and self._channel is None
            and self._diagnostic_streams_closed
        )
        if error is not None:
            cleanup_error = RuntimeError(
                "Phase04-stage observer cleanup failed "
                f"error_type={type(error).__name__}"
            )
            if deferred_cancellations:
                raise BaseExceptionGroup(
                    "Phase04-stage observer cancellation and cleanup failed",
                    [deferred_cancellations[0], cleanup_error],
                ) from None
            raise cleanup_error from None
        if not self._quiesced:
            cleanup_error = RuntimeError(
                "Phase04-stage observer cleanup failed "
                "error_type=RuntimeError"
            )
            if deferred_cancellations:
                raise BaseExceptionGroup(
                    "Phase04-stage observer cancellation and cleanup failed",
                    [deferred_cancellations[0], cleanup_error],
                ) from None
            raise cleanup_error from None
        if deferred_cancellations:
            raise deferred_cancellations[0]


def _seal_external_rss_failure_custody(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    retained = deepcopy(dict(payload))
    raw = _canonical_bytes(retained)
    if not 0 < len(raw) <= MAXIMUM_EXTERNAL_RSS_FAILURE_CUSTODY_BYTES:
        raise RuntimeError("Phase04-stage failure custody size differs")
    return _validate_external_rss_failure_custody(
        {
            "schema_id": EXTERNAL_RSS_MONITOR_FAILURE_CUSTODY_SCHEMA_ID,
            "payload_size_bytes": len(raw),
            "payload_sha256": _sha256_bytes(raw),
            "payload": retained,
        }
    )


def _validate_external_rss_failure_custody(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_id",
        "payload_size_bytes",
        "payload_sha256",
        "payload",
    }:
        raise RuntimeError("Phase04-stage failure custody fields differ")
    payload = value.get("payload")
    if type(payload) is not dict or set(payload) != {
        "failure_summary",
        "failed_lane",
        "controller_identity",
        "observer_identity",
        "observer_lifecycle",
        "observer_transaction",
        "worker_ownership",
        "worker_lifetime_lease",
        "controller_cleanup",
        "worker_cleanup",
    }:
        raise RuntimeError("Phase04-stage failure custody payload differs")
    raw = _canonical_bytes(payload)
    if (
        value.get("schema_id")
        != EXTERNAL_RSS_MONITOR_FAILURE_CUSTODY_SCHEMA_ID
        or type(value.get("payload_size_bytes")) is not int
        or value["payload_size_bytes"] != len(raw)
        or not 0 < len(raw) <= MAXIMUM_EXTERNAL_RSS_FAILURE_CUSTODY_BYTES
        or value.get("payload_sha256") != _sha256_bytes(raw)
    ):
        raise RuntimeError("Phase04-stage failure custody seal differs")
    failed_lane = payload.get("failed_lane")
    retained_classified = _classified_failure_from_lane_custody(failed_lane)
    summary = _validate_observer_failure_summary(
        payload.get("failure_summary"),
        retained_classified_lane_failure=retained_classified,
    )
    if retained_classified is not None and summary.get(
        "classified_lane_failure"
    ) is not None:
        raise RuntimeError("Phase04-stage failure custody duplicated failure")
    controller_identity = payload.get("controller_identity")
    observer_identity = payload.get("observer_identity")
    observer_lifecycle = payload.get("observer_lifecycle")
    if (
        type(controller_identity) is not dict
        or set(controller_identity)
        != {
            "pid",
            "process_create_time_ns",
            "pgid",
            "sid",
            "platform",
            "identity_source",
            "identity_source_version",
        }
        or observer_identity is not None
        and type(observer_identity) is not dict
        or observer_lifecycle is not None
        and type(observer_lifecycle) is not dict
    ):
        raise RuntimeError("Phase04-stage failure identity custody differs")
    if observer_lifecycle is not None:
        required_lifecycle = {
            "expected_return_code",
            "observed_return_code",
            "termination_mode",
            "process_reaped",
            "process_group_absent",
            "exit_status_validated",
            "diagnostics",
        }
        if (
            set(observer_lifecycle) != required_lifecycle
            or observer_lifecycle.get("process_reaped") is not True
            or observer_lifecycle.get("process_group_absent") is not True
        ):
            raise RuntimeError("Phase04-stage failure observer lifecycle differs")
    transaction = payload.get("observer_transaction")
    if transaction is not None:
        if type(transaction) is not dict or set(transaction) != {
            "schema_id",
            "issued_operation_count",
            "completed_operation_count",
            "first_partial_transaction",
            "active_transaction_at_snapshot",
        }:
            raise RuntimeError("Phase04-stage failure observer transaction differs")
        issued = transaction.get("issued_operation_count")
        completed = transaction.get("completed_operation_count")
        if (
            transaction.get("schema_id")
            != EXTERNAL_RSS_FAILURE_TRANSACTION_SCHEMA_ID
            or type(issued) is not int
            or type(completed) is not int
            or not 0 <= completed <= issued <= EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
        ):
            raise RuntimeError("Phase04-stage failure observer transaction differs")
    ownership = payload.get("worker_ownership")
    lease = payload.get("worker_lifetime_lease")
    if ownership is not None:
        ownership = _validate_retained_worker_ownership(ownership)
        if lease is None:
            raise RuntimeError("Phase04-stage failure lease custody is absent")
        _validate_worker_lifetime_lease(
            lease,
            ownership=ownership,
            require_success=False,
        )
    elif lease is not None:
        raise RuntimeError("Phase04-stage failure ownership custody is absent")
    cleanup = payload.get("controller_cleanup")
    if type(cleanup) is not dict or set(cleanup) != {
        "monitor_failure_observed",
        "sampling_quiesced",
        "pre_release_quiesce_completed",
        "cleanup_complete",
        "controller_channels_closed",
        "controller_scheduler_restored",
        "cleanup_error_types",
    }:
        raise RuntimeError("Phase04-stage failure cleanup custody differs")
    if any(
        type(cleanup.get(field)) is not bool
        for field in (
            "monitor_failure_observed",
            "sampling_quiesced",
            "pre_release_quiesce_completed",
            "cleanup_complete",
            "controller_channels_closed",
            "controller_scheduler_restored",
        )
    ):
        raise RuntimeError("Phase04-stage failure cleanup custody differs")
    error_types = cleanup.get("cleanup_error_types")
    if (
        type(error_types) is not list
        or len(error_types) > 8
        or any(
            type(name) is not str
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name) is None
            for name in error_types
        )
    ):
        raise RuntimeError("Phase04-stage failure cleanup errors differ")
    worker_cleanup = payload.get("worker_cleanup")
    if worker_cleanup is not None and (
        type(worker_cleanup) is not dict
        or set(worker_cleanup)
        != {
            "termination_attempted",
            "process_reaped",
            "process_group_absent",
            "stdout_closed",
            "stderr_closed",
        }
        or any(type(item) is not bool for item in worker_cleanup.values())
    ):
        raise RuntimeError("Phase04-stage failure worker cleanup differs")
    return deepcopy(value)


class _ExternalRSSMonitorBinding:
    """Own one controller socket and one exact external worker sampler."""

    def __init__(
        self,
        controller_channel: socket.socket,
        worker_channel: socket.socket,
    ) -> None:
        if controller_channel is worker_channel:
            raise ValueError("Phase04-stage monitor socket ownership differs")
        self._controller_channel = controller_channel
        self._controller_channel.settimeout(
            EXTERNAL_RSS_MONITOR_OPERATION_TIMEOUT_SECONDS
        )
        self._worker_channel: socket.socket | None = worker_channel
        self._buffer = bytearray()
        self._expected_sequence = 1
        self._sampler: _Phase04StageRSSSampler | None = None
        self._observer: _ExternalRSSObserverProcess | None = None
        self._observer_spawn_release_safe = True
        self._observer_identity: dict[str, Any] | None = None
        self._observer_runtime_custody: dict[str, Any] | None = None
        self._observer_failure_summary: dict[str, Any] | None = None
        self._observer_failure_record: dict[str, Any] | None = None
        self._monitor_failure_observed = False
        self._cleanup_error_types: list[str] = []
        self._worker_identity: dict[str, Any] | None = None
        self._worker_ownership: dict[str, Any] | None = None
        self._worker_lifetime_lease: _WorkerLifetimeLease | None = None
        self._controller_identity = _controller_monitor_identity()
        self._duplex_transcript: list[dict[str, Any]] = []
        self._duplex_exchange_bytes = 0
        self._hwm_value: int | None = None
        self._children_rusage_value: dict[str, Any] | None = None
        self._state = "created"
        self._record: dict[str, Any] | None = None
        self._registered = False
        self._scheduler_owned = False
        self._scheduler_original_seconds: float | None = None
        self._scheduler_effective_seconds: float | None = None
        self._scheduler_restored_seconds: float | None = None
        self._scheduler_external_mutation_observed = False
        self._gc_original_enabled: bool | None = None
        self._gc_effective_enabled: bool | None = None
        self._gc_restored_enabled: bool | None = None
        self._gc_pre_window_collected_objects: int | None = None
        self._gc_external_mutation_observed = False
        self._sampling_quiesced = False
        self._pre_release_quiesce_completed = False
        self._cleanup_complete = False

    @classmethod
    def create(cls) -> _ExternalRSSMonitorBinding:
        controller, worker = socket.socketpair(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )
        try:
            return cls(controller, worker)
        except BaseException:
            controller.close()
            worker.close()
            raise

    @property
    def worker_descriptor(self) -> int:
        if self._worker_channel is None:
            raise RuntimeError("Phase04-stage monitor worker descriptor is closed")
        descriptor = self._worker_channel.fileno()
        if descriptor <= 2:
            raise RuntimeError("Phase04-stage monitor worker descriptor differs")
        return descriptor

    @property
    def record(self) -> dict[str, Any]:
        if self._state != "finished" or self._record is None:
            raise RuntimeError("Phase04-stage parent monitor is incomplete")
        return deepcopy(self._record)

    @property
    def failure_summary(self) -> dict[str, Any] | None:
        if self._observer_failure_summary is not None:
            return deepcopy(self._observer_failure_summary)
        if self._observer is not None:
            summary = self._observer.failure_summary
            if summary is not None:
                return summary
        sampler = self._sampler
        if sampler is None or not hasattr(sampler, "failure_summary"):
            return None
        summary = sampler.failure_summary
        if summary is None:
            return None
        if type(summary) is not dict:
            raise RuntimeError("Phase04-stage monitor failure summary differs")
        return deepcopy(summary)

    def note_monitor_failure(self, error: BaseException) -> None:
        self._monitor_failure_observed = True
        error_type = type(error).__name__
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", error_type)
            and error_type not in self._cleanup_error_types
            and len(self._cleanup_error_types) < 8
        ):
            self._cleanup_error_types.append(error_type)

    def failure_custody(
        self,
        *,
        worker_cleanup: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Seal available failure, lifecycle, lease, and cleanup custody."""

        observer = self._observer
        failed_lane = self._observer_failure_record
        if failed_lane is None and observer is not None:
            failed_lane = observer.failure_record
        retained_classified = _classified_failure_from_lane_custody(
            failed_lane
        )
        summary = self.failure_summary
        if summary is None:
            summary = _observer_generic_failure_summary(None)
        elif retained_classified is not None:
            embedded = summary.get("classified_lane_failure")
            if embedded is not None:
                if _canonical_bytes(embedded) != _canonical_bytes(
                    retained_classified
                ):
                    raise RuntimeError(
                        "Phase04-stage failure custody projection differs"
                    )
                summary = deepcopy(summary)
                summary["classified_lane_failure"] = None
        observer_lifecycle: dict[str, Any] | None = None
        if observer is not None and observer.quiesced:
            observer_lifecycle = observer.lifecycle_record
        ownership = (
            None
            if self._worker_ownership is None
            else deepcopy(self._worker_ownership)
        )
        lease = (
            None
            if self._worker_lifetime_lease is None
            else self._worker_lifetime_lease.record(require_success=False)
        )
        return _seal_external_rss_failure_custody(
            {
                "failure_summary": summary,
                "failed_lane": failed_lane,
                "controller_identity": deepcopy(self._controller_identity),
                "observer_identity": (
                    None
                    if self._observer_identity is None
                    else deepcopy(self._observer_identity)
                ),
                "observer_lifecycle": observer_lifecycle,
                "observer_transaction": (
                    None if observer is None else observer.transaction_custody
                ),
                "worker_ownership": ownership,
                "worker_lifetime_lease": lease,
                "controller_cleanup": {
                    "monitor_failure_observed": (
                        self._monitor_failure_observed
                        or self.failure_summary is not None
                    ),
                    "sampling_quiesced": self._sampling_quiesced,
                    "pre_release_quiesce_completed": (
                        self._pre_release_quiesce_completed
                    ),
                    "cleanup_complete": self._cleanup_complete,
                    "controller_channels_closed": (
                        self._worker_channel is None
                        and self._controller_channel is None
                    ),
                    "controller_scheduler_restored": not self._scheduler_owned,
                    "cleanup_error_types": list(self._cleanup_error_types),
                },
                "worker_cleanup": (
                    None if worker_cleanup is None else dict(worker_cleanup)
                ),
            }
        )

    def _read_hwm(self) -> int:
        if type(self._hwm_value) is not int or self._hwm_value < 0:
            raise RuntimeError("Phase04-stage monitor HWM value differs")
        return self._hwm_value

    def _read_children_rusage(self) -> dict[str, Any]:
        if self._children_rusage_value is None:
            raise RuntimeError("Phase04-stage monitor child rusage is absent")
        return deepcopy(self._children_rusage_value)

    def _acquire_controller_scheduler(self) -> None:
        if self._scheduler_owned:
            raise RuntimeError(
                "Phase04-stage monitor scheduler ownership differs"
            )
        if not _EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK.acquire(blocking=False):
            raise RuntimeError(
                "Phase04-stage monitor scheduler is already owned"
            )
        self._scheduler_owned = True
        try:
            original = sys.getswitchinterval()
            if (
                type(original) is not float
                or not math.isfinite(original)
                or original <= 0
            ):
                raise RuntimeError(
                    "Phase04-stage monitor scheduler baseline differs"
                )
            self._scheduler_original_seconds = original
            sys.setswitchinterval(
                EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
            )
            effective = sys.getswitchinterval()
            if (
                type(effective) is not float
                or effective
                != EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS
            ):
                raise RuntimeError(
                    "Phase04-stage monitor scheduler setting differs"
                )
            self._scheduler_effective_seconds = effective
            original_gc_enabled = gc.isenabled()
            if type(original_gc_enabled) is not bool:
                raise RuntimeError(
                    "Phase04-stage monitor GC baseline differs"
                )
            self._gc_original_enabled = original_gc_enabled
            if original_gc_enabled:
                collected = gc.collect()
                if type(collected) is not int or collected < 0:
                    raise RuntimeError(
                        "Phase04-stage monitor GC collection differs"
                    )
                self._gc_pre_window_collected_objects = collected
            else:
                self._gc_pre_window_collected_objects = 0
            gc.disable()
            effective_gc_enabled = gc.isenabled()
            if effective_gc_enabled is not False:
                raise RuntimeError(
                    "Phase04-stage monitor GC setting differs"
                )
            self._gc_effective_enabled = effective_gc_enabled
        except BaseException:
            self._restore_controller_scheduler(require_unchanged=False)
            raise

    def _restore_controller_scheduler(
        self,
        *,
        require_unchanged: bool = True,
        deferred_cancellations: list[BaseException] | None = None,
    ) -> None:
        if not self._scheduler_owned:
            return
        local_cancellations: list[BaseException] = []
        cancellations = (
            deferred_cancellations
            if deferred_cancellations is not None
            else local_cancellations
        )
        original = self._scheduler_original_seconds
        effective = self._scheduler_effective_seconds
        original_gc_enabled = self._gc_original_enabled
        effective_gc_enabled = self._gc_effective_enabled
        scheduler_mutation_observed = False
        gc_mutation_observed = False
        restoration_error: Exception | None = None
        scheduler_restoration_proved = False
        gc_restoration_proved = False
        try:
            if original is None:
                raise RuntimeError(
                    "Phase04-stage monitor scheduler baseline is absent"
                )
            observed = _call_deferring_cancellation(
                sys.getswitchinterval,
                cancellations,
            )
            scheduler_mutation_observed = (
                require_unchanged
                and effective is not None
                and observed != effective
            )
            self._scheduler_external_mutation_observed = (
                scheduler_mutation_observed
            )
            _call_deferring_cancellation(
                lambda: sys.setswitchinterval(original),
                cancellations,
            )
            restored = _call_deferring_cancellation(
                sys.getswitchinterval,
                cancellations,
            )
            self._scheduler_restored_seconds = restored
            if restored != original:
                raise RuntimeError(
                    "Phase04-stage monitor scheduler restoration differs"
                )
            scheduler_restoration_proved = True
        except Exception as error:
            restoration_error = error
        try:
            if original_gc_enabled is None:
                # Acquisition failed before this process-global setting was
                # observed or changed; there is no GC state to restore.
                gc_restoration_proved = True
                raise StopIteration
            observed_gc_enabled = _call_deferring_cancellation(
                gc.isenabled,
                cancellations,
            )
            gc_mutation_observed = (
                require_unchanged
                and effective_gc_enabled is not None
                and observed_gc_enabled is not effective_gc_enabled
            )
            self._gc_external_mutation_observed = gc_mutation_observed
            if original_gc_enabled:
                _call_deferring_cancellation(gc.enable, cancellations)
            else:
                _call_deferring_cancellation(gc.disable, cancellations)
            restored_gc_enabled = _call_deferring_cancellation(
                gc.isenabled,
                cancellations,
            )
            self._gc_restored_enabled = restored_gc_enabled
            if restored_gc_enabled is not original_gc_enabled:
                raise RuntimeError(
                    "Phase04-stage monitor GC restoration differs"
                )
            gc_restoration_proved = True
        except StopIteration:
            pass
        except Exception as error:
            restoration_error = restoration_error or error
        if scheduler_restoration_proved and gc_restoration_proved:
            while self._scheduler_owned:
                try:
                    _EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK.release()
                except BaseException as error:
                    if not _EXTERNAL_RSS_MONITOR_SCHEDULER_LOCK.locked():
                        self._scheduler_owned = False
                    if isinstance(error, Exception):
                        restoration_error = restoration_error or error
                        break
                    cancellations.append(error)
                    if self._scheduler_owned:
                        continue
                else:
                    self._scheduler_owned = False
        if restoration_error is not None:
            raise RuntimeError(
                "Phase04-stage monitor controller-state restoration failed "
                f"error_type={type(restoration_error).__name__}"
            ) from None
        if scheduler_mutation_observed:
            raise RuntimeError(
                "Phase04-stage monitor scheduler changed externally"
            )
        if gc_mutation_observed:
            raise RuntimeError(
                "Phase04-stage monitor GC changed externally"
            )
        if deferred_cancellations is None and local_cancellations:
            raise local_cancellations[0]

    def bind(
        self,
        process: Any,
        ownership: Mapping[str, Any],
        *,
        lifetime_lease: _WorkerLifetimeLease | None = None,
    ) -> None:
        if self._state != "created":
            raise RuntimeError("Phase04-stage monitor binding state differs")
        lease = lifetime_lease or _WorkerLifetimeLease()
        if lifetime_lease is None:
            lease.acquire(process, ownership)
        else:
            lease.require_active_identity(process, ownership)
        self._worker_lifetime_lease = lease
        self._acquire_controller_scheduler()
        try:
            if _controller_monitor_identity() != self._controller_identity:
                raise RuntimeError(
                    "Phase04-stage monitor controller identity changed"
                )
            _validate_worker_group_identity_without_reap(process, ownership)
            import psutil

            target = psutil.Process(ownership["leader_pid"])
            if (
                int(round(float(target.create_time()) * 1e9))
                != ownership["leader_create_time_ns"]
                or target.ppid() != ownership["owner_pid"]
                or os.getpgid(target.pid) != ownership["pgid"]
                or os.getsid(target.pid) != ownership["sid"]
            ):
                raise RuntimeError(
                    "Phase04-stage monitor target identity differs"
                )
            self._worker_ownership = deepcopy(dict(ownership))
            self._worker_identity = {
                "worker_pid": ownership["leader_pid"],
                "process_create_time_ns": ownership["leader_create_time_ns"],
                "source_version": _current_rss_source_version(),
                "platform": sys.platform,
            }
            lease.bind_monitor(process, ownership)
            self._observer_spawn_release_safe = False
            try:
                self._observer = _ExternalRSSObserverProcess.spawn(
                    ownership,
                    self._controller_identity,
                    lease.record(require_success=False),
                )
            except _ExternalRSSObserverSpawnFailure as error:
                self._observer_spawn_release_safe = error.worker_release_safe
                raise
            except BaseException as error:
                self._observer_spawn_release_safe = bool(
                    getattr(error, "worker_release_safe", False)
                )
                raise
            self._observer_spawn_release_safe = True
            self._observer_identity = self._observer.identity
            self._state = "bound"
            worker_channel = self._worker_channel
            if worker_channel is not None:
                worker_channel.close()
                if worker_channel.fileno() == -1:
                    self._worker_channel = None
                else:  # pragma: no cover - socket contract guard
                    raise RuntimeError(
                        "Phase04-stage monitor worker channel remained open"
                    )
        except BaseException as primary_error:
            deferred_cancellations: list[BaseException] = []
            if self._observer is not None:
                try:
                    _call_deferring_cancellation(
                        self._observer.quiesce,
                        deferred_cancellations,
                    )
                except BaseException:
                    if not self._observer.quiesced:
                        self._observer_spawn_release_safe = False
                else:
                    self._observer_spawn_release_safe = True
            self._restore_controller_scheduler(
                require_unchanged=False,
                deferred_cancellations=deferred_cancellations,
            )
            if isinstance(primary_error, Exception) and deferred_cancellations:
                raise deferred_cancellations[0]
            raise

    def register(self, selector: selectors.BaseSelector) -> None:
        if self._state != "bound" or self._registered:
            raise RuntimeError("Phase04-stage monitor registration state differs")
        selector.register(
            self._controller_channel,
            selectors.EVENT_READ,
            data="external_rss_monitor",
        )
        self._registered = True

    def _validate_request(
        self,
        raw: bytes,
    ) -> tuple[dict[str, Any], int, str, dict[str, Any]]:
        request = _external_monitor_message(raw, label="request")
        if set(request) != {"schema_id", "sequence", "operation", "payload"}:
            raise RuntimeError("Phase04-stage monitor request fields differ")
        sequence = request.get("sequence")
        operation = request.get("operation")
        payload = request.get("payload")
        if (
            request.get("schema_id") != EXTERNAL_RSS_MONITOR_SCHEMA_ID
            or type(sequence) is not int
            or sequence != self._expected_sequence
            or sequence > EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
            or operation not in EXTERNAL_RSS_MONITOR_OPERATIONS
            or type(payload) is not dict
        ):
            raise RuntimeError("Phase04-stage monitor request differs")
        self._expected_sequence += 1
        return request, sequence, operation, payload

    def _append_duplex_exchange(
        self,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> None:
        if len(self._duplex_transcript) >= EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES:
            raise RuntimeError("Phase04-stage monitor exchange count exceeded")
        exchange = {
            "request": deepcopy(dict(request)),
            "response": deepcopy(dict(response)),
        }
        exchange_bytes = len(_canonical_bytes(exchange))
        if (
            self._duplex_exchange_bytes + exchange_bytes
            > EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
        ):
            raise RuntimeError("Phase04-stage monitor transcript bytes exceeded")
        self._duplex_transcript.append(exchange)
        self._duplex_exchange_bytes += exchange_bytes

    def _set_hwm(self, value: Any) -> None:
        if type(value) is not int or value < 0:
            raise RuntimeError("Phase04-stage monitor HWM value differs")
        self._hwm_value = value

    def _set_children_rusage(self, value: Any) -> None:
        try:
            self._children_rusage_value = _validate_children_rusage_fingerprint(
                value
            )
        except ValueError as error:
            raise RuntimeError(
                "Phase04-stage monitor child rusage differs"
            ) from error

    def _dispatch_observer(
        self,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        observer = self._observer
        if observer is None:
            raise RuntimeError("Phase04-stage monitor observer is absent")
        try:
            if operation == "PREPARE":
                if self._state != "bound" or payload != self._worker_identity:
                    raise RuntimeError("Phase04-stage monitor PREPARE differs")
                observer.request(operation, payload)
                self._state = "prepared"
                return None
            if operation == "START":
                if self._state != "prepared" or set(payload) != {
                    "first_boundary_component",
                    "hwm_bytes",
                    "children_rusage",
                }:
                    raise RuntimeError("Phase04-stage monitor START differs")
                observer.request(operation, payload)
                self._state = "started"
                return None
            if operation == "BOUNDARY":
                if self._state != "started" or payload:
                    raise RuntimeError("Phase04-stage monitor BOUNDARY differs")
                observer.request(operation, payload)
                return None
            if operation == "PARSE":
                if self._state != "started" or set(payload) != {"hwm_bytes"}:
                    raise RuntimeError("Phase04-stage monitor PARSE differs")
                record = observer.request(operation, payload)
                if type(record) is not dict:
                    raise RuntimeError("Phase04-stage monitor PARSE record differs")
                self._state = "parsed"
                return record
            if operation == "OUTPUT":
                if self._state != "parsed" or payload:
                    raise RuntimeError("Phase04-stage monitor OUTPUT differs")
                observer.request(operation, payload)
                return None
            if operation == "FINISH":
                if self._state != "parsed" or set(payload) != {
                    "hwm_bytes",
                    "children_rusage",
                }:
                    raise RuntimeError("Phase04-stage monitor FINISH differs")
                record = observer.request(operation, payload)
                if type(record) is not dict:
                    raise RuntimeError("Phase04-stage monitor FINISH record differs")
                self._record = deepcopy(record)
                self._observer_runtime_custody = observer.runtime_custody
                self._state = "finished"
                return deepcopy(record)
            if operation == "ABORT":
                if self._state in {"finished", "aborted"} or payload:
                    raise RuntimeError("Phase04-stage monitor ABORT differs")
                observer.request(operation, payload)
                self._state = "aborted"
                return None
            raise RuntimeError("Phase04-stage monitor operation differs")
        except Exception as error:
            self.note_monitor_failure(error)
            summary = observer.failure_summary
            if summary is not None:
                self._observer_failure_summary = summary
            record = observer.failure_record
            if record is not None:
                self._observer_failure_record = record
            raise

    def _dispatch(self, operation: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self._observer is not None:
            return self._dispatch_observer(operation, payload)
        sampler = self._sampler
        if sampler is None:
            raise RuntimeError("Phase04-stage monitor sampler is absent")
        if operation == "PREPARE":
            if self._state != "bound" or payload != self._worker_identity:
                raise RuntimeError("Phase04-stage monitor PREPARE differs")
            sampler.prepare()
            self._state = "prepared"
            return None
        if operation == "START":
            if self._state != "prepared" or set(payload) != {
                "first_boundary_component",
                "hwm_bytes",
                "children_rusage",
            }:
                raise RuntimeError("Phase04-stage monitor START differs")
            self._set_hwm(payload["hwm_bytes"])
            self._set_children_rusage(payload["children_rusage"])
            sampler.start(payload["first_boundary_component"])
            self._state = "started"
            return None
        if operation == "BOUNDARY":
            if self._state != "started" or payload:
                raise RuntimeError("Phase04-stage monitor BOUNDARY differs")
            sampler.sample_synchronous_boundary()
            return None
        if operation == "PARSE":
            if self._state != "started" or set(payload) != {"hwm_bytes"}:
                raise RuntimeError("Phase04-stage monitor PARSE differs")
            self._set_hwm(payload["hwm_bytes"])
            record = sampler.record_parse_checkpoint()
            self._state = "parsed"
            return record
        if operation == "OUTPUT":
            if self._state != "parsed" or payload:
                raise RuntimeError("Phase04-stage monitor OUTPUT differs")
            sampler.sample_output_boundary()
            return None
        if operation == "FINISH":
            if self._state != "parsed" or set(payload) != {
                "hwm_bytes",
                "children_rusage",
            }:
                raise RuntimeError("Phase04-stage monitor FINISH differs")
            self._set_hwm(payload["hwm_bytes"])
            self._set_children_rusage(payload["children_rusage"])
            self._record = sampler.finish()
            self._state = "finished"
            return deepcopy(self._record)
        if operation == "ABORT":
            if self._state in {"finished", "aborted"} or payload:
                raise RuntimeError("Phase04-stage monitor ABORT differs")
            sampler.abort()
            self._state = "aborted"
            return None
        raise RuntimeError("Phase04-stage monitor operation differs")

    def _send_response(
        self,
        sequence: int,
        operation: str,
        *,
        status: str,
        record: dict[str, Any] | None,
    ) -> dict[str, Any]:
        response = {
            "schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
            "sequence": sequence,
            "operation": operation,
            "status": status,
            "record": record,
        }
        try:
            self._controller_channel.sendall(_external_monitor_frame(response))
        except (OSError, socket.timeout) as error:
            raise RuntimeError(
                "Phase04-stage monitor response send failed "
                f"error_type={type(error).__name__}"
            ) from None
        return response

    def _handle_frame(self, raw: bytes) -> None:
        sequence = 0
        operation = "ABORT"
        request: dict[str, Any] | None = None
        try:
            request, sequence, operation, payload = self._validate_request(raw)
            record = self._dispatch(operation, payload)
        except Exception:
            if sequence > 0:
                response = self._send_response(
                    sequence,
                    operation,
                    status="error",
                    record=None,
                )
                assert request is not None
                self._append_duplex_exchange(request, response)
            raise
        response = self._send_response(
            sequence,
            operation,
            status="ok",
            record=record,
        )
        assert request is not None
        self._append_duplex_exchange(request, response)

    def consume_ready(self, selector: selectors.BaseSelector) -> None:
        if not self._registered:
            raise RuntimeError("Phase04-stage monitor is not registered")
        try:
            chunk = os.read(
                self._controller_channel.fileno(),
                EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES + 4,
            )
        except BlockingIOError:
            return
        except OSError as error:
            raise RuntimeError(
                "Phase04-stage monitor read failed "
                f"error_type={type(error).__name__}"
            ) from None
        if not chunk:
            try:
                selector.unregister(self._controller_channel)
            except (KeyError, ValueError):
                pass
            self._registered = False
            if self._buffer:
                raise RuntimeError("Phase04-stage monitor truncated frame")
            if self._state not in {"finished", "aborted"}:
                raise RuntimeError("Phase04-stage monitor unexpected EOF")
            return
        self._buffer.extend(chunk)
        if len(self._buffer) > EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES + 4:
            raise RuntimeError("Phase04-stage monitor buffered frame differs")
        while len(self._buffer) >= 4:
            (size,) = struct.unpack("!I", self._buffer[:4])
            if not 0 < size <= EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES:
                raise RuntimeError("Phase04-stage monitor frame size differs")
            frame_end = 4 + size
            if len(self._buffer) < frame_end:
                return
            raw = bytes(self._buffer[4:frame_end])
            del self._buffer[:frame_end]
            self._handle_frame(raw)

    def require_complete(self) -> dict[str, Any]:
        if self._state != "finished" or self._record is None or self._buffer:
            raise RuntimeError("Phase04-stage parent monitor is incomplete")
        return deepcopy(self._record)

    def attestation(
        self,
        snapshot: Mapping[str, Any],
        worker_rss_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            not self._cleanup_complete
            or self._state != "finished"
            or self._record is None
            or self._worker_ownership is None
            or self._worker_identity
            != _external_monitor_worker_identity_from_ownership(
                self._worker_ownership
            )
            or self._scheduler_owned
            or self._scheduler_original_seconds is None
            or self._scheduler_effective_seconds is None
            or self._scheduler_restored_seconds is None
            or self._gc_original_enabled is None
            or self._gc_effective_enabled is not False
            or self._gc_restored_enabled is not self._gc_original_enabled
            or self._gc_pre_window_collected_objects is None
            or not self._sampling_quiesced
            or not self._pre_release_quiesce_completed
            or self._observer is None
            or not self._observer.quiesced
            or self._observer_identity is None
            or self._observer_runtime_custody is None
            or self._worker_lifetime_lease is None
            or not self._worker_lifetime_lease.released
            or _controller_monitor_identity() != self._controller_identity
        ):
            raise RuntimeError("Phase04-stage monitor attestation state differs")
        parent_record = deepcopy(self._record)
        retained_record = dict(worker_rss_record)
        if (
            set(parent_record) != set(PHASE04_STAGE_RSS_RECORD_FIELDS)
            or set(retained_record) != set(PHASE04_STAGE_RSS_RECORD_FIELDS)
            or _canonical_bytes(parent_record)
            != _canonical_bytes(retained_record)
        ):
            raise RuntimeError("Phase04-stage monitor attestation record differs")
        exchanges = [
            {
                "sequence": item["request"]["sequence"],
                "operation": item["request"]["operation"],
            }
            for item in self._duplex_transcript
        ]
        attestation = {
            "schema_id": EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID,
            "controller_observer": deepcopy(self._controller_identity),
            "observer_process": deepcopy(self._observer_identity),
            "observer_lifecycle": self._observer.lifecycle_record,
            "observer_runtime": deepcopy(self._observer_runtime_custody),
            "worker_ownership": deepcopy(self._worker_ownership),
            "worker_lifetime_lease": self._worker_lifetime_lease.record(
                require_success=True
            ),
            "protocol": {
                "wire_schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
                "framing": EXTERNAL_RSS_MONITOR_FRAMING,
                "maximum_exchange_count": (
                    EXTERNAL_RSS_MONITOR_MAXIMUM_EXCHANGES
                ),
                "maximum_duplex_exchange_bytes": (
                    EXTERNAL_RSS_MONITOR_MAXIMUM_DUPLEX_EXCHANGE_BYTES
                ),
                "exchange_count": len(exchanges),
                "duplex_exchange_bytes": self._duplex_exchange_bytes,
                "exchanges": exchanges,
                "duplex_transcript_sha256": _sha256_bytes(
                    _canonical_bytes(self._duplex_transcript)
                ),
            },
            "scheduler": {
                "scope": EXTERNAL_RSS_MONITOR_SCHEDULER_SCOPE,
                "requested_interval_hex": (
                    EXTERNAL_RSS_MONITOR_CONTROLLER_SWITCH_INTERVAL_SECONDS.hex()
                ),
                "original_interval_hex": (
                    self._scheduler_original_seconds.hex()
                ),
                "effective_interval_hex": (
                    self._scheduler_effective_seconds.hex()
                ),
                "restored_interval_hex": (
                    self._scheduler_restored_seconds.hex()
                ),
                "restoration_completed": True,
                "external_mutation_observed": (
                    self._scheduler_external_mutation_observed
                ),
            },
            "cyclic_gc": {
                "scope": EXTERNAL_RSS_MONITOR_GC_SCOPE,
                "original_enabled": self._gc_original_enabled,
                "effective_enabled": self._gc_effective_enabled,
                "restored_enabled": self._gc_restored_enabled,
                "pre_window_collection_performed": (
                    self._gc_original_enabled
                ),
                "pre_window_collected_objects": (
                    self._gc_pre_window_collected_objects
                ),
                "restoration_completed": True,
                "external_mutation_observed": (
                    self._gc_external_mutation_observed
                ),
            },
            "measurement_custody": {
                "current_rss_owner": (
                    "controller_owned_dedicated_current_rss_lane_process"
                ),
                "child_observer_owner": "controller_owned_observer_process",
                "current_rss_source": PHASE04_STAGE_CURRENT_RSS_SOURCE,
                "current_rss_source_version": (
                    PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION
                ),
                "sampling_scope": PHASE04_STAGE_RSS_SAMPLING_SCOPE,
                "child_observer_source": PHASE04_STAGE_CHILD_OBSERVER_SOURCE,
                "child_observer_source_version": (
                    PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION
                ),
                "child_scope": PHASE04_STAGE_RSS_CHILD_SCOPE,
                "high_water_measurement_owner": "fresh_worker",
                "high_water_custody_path": (
                    "worker_payload_controller_round_trip"
                ),
                "children_rusage_measurement_owner": "fresh_worker",
                "children_rusage_custody_path": (
                    "worker_payload_controller_round_trip"
                ),
                "controller_monitor_allocations_in_worker_g": False,
                "worker_proxy_executes_in_worker_process": True,
                "worker_proxy_resource_credit_bytes": 0,
                "controller_gc_custody_outside_worker_g": True,
                "worker_release_after_monitor_quiescence": True,
                "observer_process_is_worker_descendant": False,
                "observer_process_allocations_in_worker_g": False,
                "current_rss_lane_process_is_observer_descendant": True,
                "current_rss_lane_process_is_worker_descendant": False,
                "current_rss_lane_process_allocations_in_worker_g": False,
                "current_rss_lane_resource_credit_bytes": 0,
                "worker_release_after_current_rss_lane_quiescence": True,
                "controller_rss_record_sha256": _sha256_bytes(
                    _canonical_bytes(parent_record)
                ),
                "worker_retained_rss_record_sha256": _sha256_bytes(
                    _canonical_bytes(retained_record)
                ),
                "records_match": True,
                "worker_resource_payload_sha256": _sha256_bytes(
                    _canonical_bytes(
                        _external_monitor_worker_resource_payload(snapshot)
                    )
                ),
                "worker_absolute_peak_rss_bytes_at_snapshot": snapshot[
                    "peak_rss_bytes"
                ],
                "covers_hwm_end": (
                    snapshot["peak_rss_bytes"]
                    >= snapshot["phase04_stage_hwm_end_bytes"]
                ),
            },
        }
        _validate_external_rss_monitor_attestation(attestation, snapshot)
        return attestation

    def abort(self) -> None:
        if self._cleanup_complete:
            return
        cleanup_error: Exception | None = None
        deferred_cancellations: list[BaseException] = []
        if self._observer is not None:
            try:
                _call_deferring_cancellation(
                    self._observer.quiesce,
                    deferred_cancellations,
                )
                if not self._observer.quiesced:
                    raise RuntimeError(
                        "Phase04-stage observer process is not quiesced"
                    )
                if self._state != "finished":
                    self._state = "aborted"
            except Exception as error:
                cleanup_error = error
        if self._sampler is not None and self._state not in {
            "finished",
            "aborted",
        }:
            try:
                _call_deferring_cancellation(
                    self._sampler.abort,
                    deferred_cancellations,
                )
                self._state = "aborted"
            except Exception as error:
                cleanup_error = error
        if self._sampler is not None:
            try:
                self._sampler.require_quiesced()
                self._sampling_quiesced = True
            except Exception as error:
                cleanup_error = cleanup_error or error
        else:
            self._sampling_quiesced = (
                (
                    self._observer is None
                    and self._observer_spawn_release_safe
                )
                or (
                    self._observer is not None
                    and self._observer.quiesced
                )
            )
        for attribute in ("_worker_channel", "_controller_channel"):
            channel = getattr(self, attribute)
            if channel is None:
                continue
            try:
                _call_deferring_cancellation(
                    channel.close,
                    deferred_cancellations,
                )
            except Exception as error:
                cleanup_error = cleanup_error or error
            finally:
                if channel.fileno() == -1:
                    setattr(self, attribute, None)
        self._registered = False
        try:
            self._restore_controller_scheduler(
                deferred_cancellations=deferred_cancellations,
            )
        except Exception as error:
            cleanup_error = cleanup_error or error
        self._cleanup_complete = (
            self._worker_channel is None
            and self._controller_channel is None
            and not self._scheduler_owned
            and self._sampling_quiesced
            and (self._observer is None or self._observer.quiesced)
            and (
                self._gc_original_enabled is None
                or self._gc_restored_enabled is self._gc_original_enabled
            )
            and (
                self._sampler is None
                or self._state in {"finished", "aborted"}
            )
        )
        if cleanup_error is not None:
            self.note_monitor_failure(cleanup_error)
            raise RuntimeError(
                "Phase04-stage monitor cleanup failed "
                f"error_type={type(cleanup_error).__name__}"
            ) from None
        if not self._cleanup_complete:
            raise RuntimeError("Phase04-stage monitor cleanup is incomplete")
        if deferred_cancellations:
            raise deferred_cancellations[0]

    def require_sampling_quiesced(self) -> None:
        """Prove worker PID release cannot race a later sampler read."""

        if not self._sampling_quiesced:
            raise RuntimeError("Phase04-stage monitor sampling is not quiesced")
        if self._observer is not None and not self._observer.quiesced:
            raise RuntimeError("Phase04-stage observer process is not quiesced")
        if self._sampler is not None:
            self._sampler.require_quiesced()

    def quiesce_before_worker_release(
        self,
        selector: selectors.BaseSelector | None,
    ) -> None:
        """Stop observation and restore controller state before any reap."""

        unregister_error: Exception | None = None
        if self._registered and selector is not None:
            try:
                selector.unregister(self._controller_channel)
            except (KeyError, ValueError):
                pass
            except Exception as error:
                unregister_error = error
            self._registered = False
        try:
            self.abort()
        except Exception as error:
            unregister_error = unregister_error or error
            self.note_monitor_failure(error)
        self.require_sampling_quiesced()
        # Physical observer/lane quiescence is the release prerequisite.  A
        # separate cleanup-quality error (for example an unexpected but reaped
        # exit status) remains fatal evidence, but cannot strand the lease or
        # prevent exact worker termination once no sampler can reuse its PID.
        self._pre_release_quiesce_completed = True
        lease = self._worker_lifetime_lease
        if lease is None:
            raise RuntimeError("Phase04-stage worker lifetime lease is absent")
        observer_quiesced = (
            self._observer is None or self._observer.quiesced
        )
        current_lane_quiesced = self._sampling_quiesced
        if self._observer_runtime_custody is not None:
            lane_custody = self._observer_runtime_custody.get(
                "current_rss_lane"
            )
            if type(lane_custody) is dict:
                lifecycle = lane_custody.get("lifecycle")
                current_lane_quiesced = (
                    current_lane_quiesced
                    and type(lifecycle) is dict
                    and lifecycle.get("process_reaped") is True
                    and lifecycle.get("exit_status_validated") is True
                )
        if lease.worker_bootstrap_released:
            lease.release_after_sampling_quiescence(
                observer_quiesced=observer_quiesced,
                current_rss_lane_quiesced=current_lane_quiesced,
            )
        else:
            lease.release_after_failed_setup_quiescence(
                observer_quiesced=observer_quiesced,
                current_rss_lane_quiesced=current_lane_quiesced,
            )
        if unregister_error is not None:
            raise RuntimeError(
                "Phase04-stage monitor pre-release cleanup failed "
                f"error_type={type(unregister_error).__name__}"
            ) from None


class _SpanStageMeasurement:
    """Measure the non-overlapping union of every US01-owned runtime stage."""

    def __init__(
        self,
        pipeline_module: Any,
        table_semantics_module: Any,
        *,
        clock_ns: Any | None = None,
        rss_sampler: Any | None = None,
    ) -> None:
        self._pipeline = pipeline_module
        self._table_semantics = table_semantics_module
        self._clock_ns = clock_ns or time.perf_counter_ns
        self._rss_sampler = rss_sampler or _Phase04StageRSSSampler()
        self._elapsed_ns = {component: 0 for component in TABLE_STAGE_COMPONENTS}
        self._call_counts = {component: 0 for component in TABLE_STAGE_COMPONENTS}
        self._component_depths = {
            component: 0 for component in TABLE_STAGE_COMPONENTS
        }
        self._stage_stack: list[str] = []
        self._active_started_ns: int | None = None
        self._rss_started = False
        self._parse_rss_checkpoint: dict[str, int] | None = None
        self._phase04_stage_rss: dict[str, Any] | None = None
        self._originals: list[tuple[Any, str, Any]] = []
        self._entered = False
        self._original_pydantic_validator = (
            pipeline_module.ParseResult.__pydantic_validator__
        )
        core_schema = dict(pipeline_module.ParseResult.__pydantic_core_schema__)
        function_schema = dict(core_schema.get("function") or {})
        custody_function = function_schema.get("function")
        if (
            function_schema.get("type") != "with-info"
            or custody_function
            is not pipeline_module.ParseResult.validate_table_evidence_custody
        ):
            raise ValueError("ParseResult table-custody validator shape differs")

        @wraps(custody_function)
        def measured_custody(value: Any, info: Any) -> Any:
            return self._invoke(
                "parse_result_custody",
                custody_function,
                (value, info),
                {},
            )

        function_schema["function"] = measured_custody
        core_schema["function"] = function_schema
        self._measured_pydantic_validator = SchemaValidator(core_schema)

    def prepare_rss_sampler(self) -> None:
        """Prepare the dormant sampler before whole-parser timing begins."""

        if self._entered or self._rss_started:
            raise RuntimeError("Phase04-stage RSS preparation order differs")
        self._rss_sampler.prepare()

    def _invoke(self, component: str, function: Any, args: Any, kwargs: Any) -> Any:
        if (
            self._parse_rss_checkpoint is not None
            or self._phase04_stage_rss is not None
        ):
            raise RuntimeError(
                "Phase04-stage invocation followed the parse RSS checkpoint"
            )
        component_outermost = self._component_depths[component] == 0
        if not self._rss_started:
            if not component_outermost or self._stage_stack:
                raise RuntimeError("Phase04-stage first RSS boundary differs")
            self._rss_sampler.start(component)
            self._rss_started = True
        elif component_outermost:
            self._rss_sampler.sample_synchronous_boundary()
        started_ns = self._clock_ns()
        if self._stage_stack:
            if self._active_started_ns is None:
                raise RuntimeError("span-stage active clock differs")
            active_component = self._stage_stack[-1]
            self._elapsed_ns[active_component] += max(
                started_ns - self._active_started_ns,
                0,
            )
        if component_outermost:
            self._call_counts[component] += 1
        self._stage_stack.append(component)
        self._component_depths[component] += 1
        self._active_started_ns = started_ns
        try:
            return function(*args, **kwargs)
        finally:
            finished_ns = self._clock_ns()
            if self._active_started_ns is None:
                raise RuntimeError("span-stage active clock differs")
            self._elapsed_ns[component] += max(
                finished_ns - self._active_started_ns,
                0,
            )
            self._component_depths[component] -= 1
            observed = self._stage_stack.pop()
            if observed != component:
                raise RuntimeError("span-stage measurement stack differs")
            self._active_started_ns = (
                finished_ns if self._stage_stack else None
            )
            if component_outermost:
                self._rss_sampler.sample_synchronous_boundary()

    def record_parse_rss_checkpoint(self) -> dict[str, int]:
        """Checkpoint parse RSS while keeping the sampler alive for outputs."""

        if not self._entered or self._stage_stack:
            raise RuntimeError("Phase04-stage parse RSS checkpoint state differs")
        if not self._rss_started:
            raise RuntimeError("Phase04-stage RSS baseline is absent")
        if self._parse_rss_checkpoint is not None:
            raise RuntimeError("Phase04-stage parse RSS checkpoint already exists")
        self._parse_rss_checkpoint = self._rss_sampler.record_parse_checkpoint()
        return deepcopy(self._parse_rss_checkpoint)

    def sample_output_boundary(self) -> None:
        """Sample an exact production output materialization boundary."""

        if self._entered or self._stage_stack:
            raise RuntimeError("Phase04-stage output sampling state differs")
        if self._parse_rss_checkpoint is None:
            raise RuntimeError("Phase04-stage output preceded parse checkpoint")
        if self._phase04_stage_rss is not None:
            raise RuntimeError("Phase04-stage output followed RSS completion")
        self._rss_sampler.sample_output_boundary()

    def finish_rss_measurement(self) -> dict[str, Any]:
        """Complete RSS sampling only after both production outputs exist."""

        if self._entered or self._stage_stack:
            raise RuntimeError("Phase04-stage RSS end sampling state differs")
        if not self._rss_started or self._parse_rss_checkpoint is None:
            raise RuntimeError("Phase04-stage RSS parse checkpoint is absent")
        if self._phase04_stage_rss is not None:
            raise RuntimeError("Phase04-stage RSS end is already recorded")
        self._phase04_stage_rss = self._rss_sampler.finish()
        return deepcopy(self._phase04_stage_rss)

    def abort_rss_measurement(self) -> None:
        """Fail-closed cleanup for a parse or output-probe failure."""

        if self._phase04_stage_rss is None:
            self._rss_sampler.abort()

    def phase04_stage_rss_record(self) -> dict[str, Any]:
        """Return the completed RSS record or fail closed when incomplete."""

        if self._phase04_stage_rss is None:
            raise RuntimeError("Phase04-stage RSS measurement is incomplete")
        return deepcopy(self._phase04_stage_rss)

    def _restore_installation(self, *, preserve_sampler: bool = False) -> None:
        failures: list[Exception] = []
        if self._phase04_stage_rss is None and not preserve_sampler:
            try:
                self._rss_sampler.abort()
            except Exception as error:  # pragma: no cover - defensive cleanup
                failures.append(error)
        try:
            self._pipeline.ParseResult.__pydantic_validator__ = (
                self._original_pydantic_validator
            )
        except Exception as error:  # pragma: no cover - defensive fail-closed path
            failures.append(error)
        for owner, attribute, original in reversed(self._originals):
            try:
                setattr(owner, attribute, original)
            except Exception as error:  # pragma: no cover - defensive fail-closed path
                failures.append(error)
        self._originals.clear()
        self._entered = False
        if failures:
            raise ExceptionGroup(
                "span-stage instrumentation rollback failed",
                failures,
            )

    def __enter__(self) -> _SpanStageMeasurement:
        if self._entered:
            raise RuntimeError("span-stage measurement cannot be re-entered")
        self._entered = True
        targets = (
            (
                "budget_start",
                self._table_semantics,
                "table_span_fidelity_document_deadline",
            ),
            (
                "repair_extraction",
                self._pipeline,
                "_extract_partitioned_table_repair_words",
            ),
            (
                "repair_extraction",
                self._pipeline,
                "_extract_table_repair_words",
            ),
            ("docling_projection", self._pipeline, "_docling_table_item"),
            ("seal", self._table_semantics, "seal_table_pages"),
            (
                "table_transaction_detach",
                self._table_semantics,
                "detach_table_overlays_for_phase03",
            ),
            (
                "terminal_authority",
                self._pipeline,
                "_apply_terminal_table_authority",
            ),
            (
                "document_custody_transaction",
                self._pipeline,
                "_run_table_custody_document_segment",
            ),
            (
                "table_transaction_rebind",
                self._table_semantics,
                "rebind_table_overlays_after_phase03",
            ),
            (
                "finalize_replay",
                self._table_semantics,
                "finalize_table_pages",
            ),
            (
                "budget_finish",
                self._pipeline,
                "_finish_table_span_fidelity_budget",
            ),
        )
        try:
            for component, owner, attribute in targets:
                original = getattr(owner, attribute)
                self._originals.append((owner, attribute, original))

                @wraps(original)
                def measured(
                    *args: Any,
                    _component: str = component,
                    _original: Any = original,
                    **kwargs: Any,
                ) -> Any:
                    return self._invoke(_component, _original, args, kwargs)

                setattr(owner, attribute, measured)
            self._pipeline.ParseResult.__pydantic_validator__ = (
                self._measured_pydantic_validator
            )
        except Exception as installation_error:
            try:
                self._restore_installation()
            except ExceptionGroup as rollback_error:  # pragma: no cover
                raise ExceptionGroup(
                    "span-stage instrumentation installation and rollback failed",
                    [installation_error, rollback_error],
                ) from installation_error
            raise
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        preserve_sampler = (
            _type is None
            and self._parse_rss_checkpoint is not None
            and self._phase04_stage_rss is None
        )
        self._restore_installation(preserve_sampler=preserve_sampler)

    def component_records(self) -> dict[str, dict[str, Any]]:
        return {
            component: {
                "elapsed_seconds": round(
                    self._elapsed_ns[component] / 1_000_000_000,
                    9,
                ),
                "call_count": self._call_counts[component],
            }
            for component in TABLE_STAGE_COMPONENTS
        }


def _warm_production_output_path() -> dict[str, Any]:
    """Import and warm every production output callable before measurement."""

    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse, Response

    from app import api as api_module
    from app.models import ParseResult

    warm_result = ParseResult.model_validate(
        {
            "schema_version": "1.0",
            "document": {
                "filename": "p04-us01-output-warm.pdf",
                "mime_type": "application/pdf",
                "sha256": "0" * 64,
                "page_count": 1,
            },
            "pages": [
                {
                    "page_index": 1,
                    "page_number": 1,
                    "page_label": "1",
                    "page_width": 1.0,
                    "page_height": 1.0,
                    "unit": "pt",
                    "success": True,
                    "items": [],
                    "warnings": [],
                }
            ],
            "processing": {
                "engine": "p04-us01-output-warm",
                "ocr_engine": "none",
                "ocr_languages": [],
                "duration_ms": 0,
            },
            "warnings": [],
        }
    )
    public_result = jsonable_encoder(warm_result)
    _streaming_canonical_identity(public_result)
    validated_result = ParseResult.model_validate(public_result)
    public_result = validated_result.model_dump(mode="json", exclude_unset=True)
    _streaming_canonical_identity(public_result)
    json_response = JSONResponse(content=public_result)
    json_body = json_response.body
    _sha256_bytes(json_body)
    if json.loads(json_body) != public_result:
        raise RuntimeError("Phase04-stage warmed JSON output parity differs")
    markdown = api_module._serialize_markdown(public_result)
    markdown_response = Response(content=markdown, media_type="text/markdown")
    if markdown_response.body != markdown.encode("utf-8"):
        raise RuntimeError("Phase04-stage warmed Markdown output parity differs")
    return {
        "jsonable_encoder": jsonable_encoder,
        "json_response_class": JSONResponse,
        "response_class": Response,
        "parse_result_class": ParseResult,
        "serialize_markdown": api_module._serialize_markdown,
    }


def _streaming_canonical_identity(value: Any) -> tuple[int, str]:
    """Hash canonical JSON incrementally without a document-sized copy."""

    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256()
    size_bytes = 0
    for fragment in encoder.iterencode(value):
        encoded = fragment.encode("utf-8")
        size_bytes += len(encoded)
        digest.update(encoded)
    return size_bytes, digest.hexdigest()


def _materialize_production_outputs_and_finish_rss(
    result: Any,
    measurement: _SpanStageMeasurement,
    output_tools: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Materialize exact production bodies, then take t1 immediately."""

    expected_tools = {
        "jsonable_encoder",
        "json_response_class",
        "response_class",
        "parse_result_class",
        "serialize_markdown",
    }
    if type(output_tools) is not dict or set(output_tools) != expected_tools:
        raise RuntimeError("Phase04-stage output tool binding differs")
    observed_boundaries: list[str] = []

    def boundary(name: str) -> None:
        expected = PHASE04_STAGE_OUTPUT_BOUNDARIES[len(observed_boundaries)]
        if name != expected:
            raise RuntimeError("Phase04-stage output boundary order differs")
        measurement.sample_output_boundary()
        observed_boundaries.append(name)

    boundary("source_result_identity_pre")
    source_projection = result.model_dump(
        mode="json",
        exclude_unset=False,
    )
    source_before_size, source_before_sha256 = (
        _streaming_canonical_identity(source_projection)
    )
    boundary("source_result_identity_post")
    del source_projection
    boundary("source_result_identity_release_post")

    boundary("jsonable_encoder_pre")
    public_result = output_tools["jsonable_encoder"](result)
    boundary("jsonable_encoder_post")
    jsonable_size, jsonable_sha256 = _streaming_canonical_identity(
        public_result
    )
    boundary("jsonable_streaming_identity_post")

    validated_result = output_tools["parse_result_class"].model_validate(
        public_result
    )
    boundary("parse_result_validate_post")
    public_result = validated_result.model_dump(
        mode="json",
        exclude_unset=True,
    )
    boundary("public_result_dump_post")
    public_size, public_sha256 = _streaming_canonical_identity(public_result)
    boundary("public_result_streaming_identity_post")

    boundary("json_response_pre")
    json_response = output_tools["json_response_class"](content=public_result)
    json_body = json_response.body
    boundary("json_response_body_post")
    json_body_size = len(json_body)
    json_body_sha256 = _sha256_bytes(json_body)
    json_media_type = json_response.media_type
    boundary("json_response_streaming_identity_post")
    del json_body, json_response
    boundary("json_response_release_post")

    boundary("markdown_serializer_pre")
    markdown = output_tools["serialize_markdown"](public_result)
    if type(markdown) is not str:
        raise RuntimeError("Phase04-stage Markdown output type differs")
    boundary("markdown_serializer_post")

    boundary("markdown_response_pre")
    markdown_response = output_tools["response_class"](
        content=markdown,
        media_type="text/markdown",
    )
    markdown_body = markdown_response.body
    markdown_media_type = markdown_response.media_type
    boundary("markdown_response_body_post")
    public_after_size, public_after_sha256 = _streaming_canonical_identity(
        public_result
    )
    public_unchanged = (
        public_after_size == public_size
        and public_after_sha256 == public_sha256
    )
    boundary("public_result_after_streaming_identity_post")
    phase04_stage_rss = measurement.finish_rss_measurement()
    del validated_result
    capture = {
        "observed_boundaries": observed_boundaries,
        "jsonable_size": jsonable_size,
        "jsonable_sha256": jsonable_sha256,
        "source_before_size": source_before_size,
        "source_before_sha256": source_before_sha256,
        "public_result": public_result,
        "public_size": public_size,
        "public_sha256": public_sha256,
        "public_after_size": public_after_size,
        "public_after_sha256": public_after_sha256,
        "public_unchanged": public_unchanged,
        "json_body_size": json_body_size,
        "json_body_sha256": json_body_sha256,
        "json_media_type": json_media_type,
        "markdown": markdown,
        "markdown_body": markdown_body,
        "markdown_media_type": markdown_media_type,
        "markdown_response": markdown_response,
    }
    return phase04_stage_rss, capture


def _finalize_production_output_probe(
    result: Any,
    capture: Mapping[str, Any],
    output_tools: Mapping[str, Any],
) -> dict[str, Any]:
    """Run allocation-heavy parity diagnostics strictly after RSS t1."""

    public_result = capture["public_result"]
    source_after = result.model_dump(mode="json", exclude_unset=False)
    source_after_size, source_after_sha256 = _streaming_canonical_identity(
        source_after
    )
    source_unchanged = (
        source_after_size == capture["source_before_size"]
        and source_after_sha256 == capture["source_before_sha256"]
    )
    replayed_json_response = output_tools["json_response_class"](
        content=public_result
    )
    replayed_json_body = replayed_json_response.body
    json_parity = (
        len(replayed_json_body) == capture["json_body_size"]
        and _sha256_bytes(replayed_json_body) == capture["json_body_sha256"]
        and json.loads(replayed_json_body) == public_result
    )
    markdown = capture["markdown"]
    markdown_body = capture["markdown_body"]
    markdown_utf8 = markdown.encode("utf-8")
    markdown_size = len(markdown_utf8)
    markdown_sha256 = _sha256_bytes(markdown_utf8)
    markdown_body_size = len(markdown_body)
    markdown_body_sha256 = _sha256_bytes(markdown_body)
    markdown_parity = markdown_body == markdown_utf8
    record = {
        "schema_id": PHASE04_STAGE_OUTPUT_PROBE_SCHEMA_ID,
        "production_output_path": PHASE04_STAGE_OUTPUT_PATH,
        "output_boundary_names": capture["observed_boundaries"],
        "output_boundary_count": len(capture["observed_boundaries"]),
        "source_result_before_size_bytes": capture["source_before_size"],
        "source_result_before_sha256": capture["source_before_sha256"],
        "source_result_after_size_bytes": source_after_size,
        "source_result_after_sha256": source_after_sha256,
        "source_result_unchanged": source_unchanged,
        "jsonable_result_size_bytes": capture["jsonable_size"],
        "jsonable_result_sha256": capture["jsonable_sha256"],
        "public_result_size_bytes": capture["public_size"],
        "public_result_sha256": capture["public_sha256"],
        "public_result_after_size_bytes": capture["public_after_size"],
        "public_result_after_sha256": capture["public_after_sha256"],
        "public_result_unchanged": capture["public_unchanged"],
        "json_response_body_size_bytes": capture["json_body_size"],
        "json_response_body_sha256": capture["json_body_sha256"],
        "json_response_decodes_to_public_result": json_parity,
        "json_response_media_type": capture["json_media_type"],
        "json_response_released_before_markdown": True,
        "markdown_utf8_size_bytes": markdown_size,
        "markdown_utf8_sha256": markdown_sha256,
        "markdown_response_body_size_bytes": markdown_body_size,
        "markdown_response_body_sha256": markdown_body_sha256,
        "markdown_response_matches_utf8": markdown_parity,
        "markdown_response_media_type": capture["markdown_media_type"],
    }
    return _validate_phase04_stage_output_probe(record)


def worker_snapshot(
    workspace: Path,
    case_id: str,
    enabled: bool,
    *,
    rss_sampler: Any | None = None,
) -> dict[str, Any]:
    """Parse one reviewed source once in the current isolated process."""

    from app.config import Settings
    from app.services import pipeline
    from app.services import table_semantics

    source = _verified_source_bytes(workspace, case_id)
    settings = Settings(
        **PREDECESSOR_CONFIGURATION,
        table_span_fidelity_enabled=enabled,
    )
    no_spawn_policy = _phase04_no_spawn_policy(workspace)
    output_tools = _warm_production_output_path()
    measurement = _SpanStageMeasurement(
        pipeline,
        table_semantics,
        rss_sampler=rss_sampler,
    )
    measurement.prepare_rss_sampler()
    started_ns = time.perf_counter_ns()
    try:
        with measurement:
            result = pipeline.parse_document(source, f"{case_id}.pdf", settings)
            parse_ended_ns = time.perf_counter_ns()
            measurement.record_parse_rss_checkpoint()
        elapsed_seconds = (parse_ended_ns - started_ns) / 1_000_000_000
        phase04_stage_rss, output_capture = (
            _materialize_production_outputs_and_finish_rss(
                result,
                measurement,
                output_tools,
            )
        )
        output_probe = _finalize_production_output_probe(
            result,
            output_capture,
            output_tools,
        )
        del output_capture
    except Exception as primary_error:
        try:
            measurement.abort_rss_measurement()
        except Exception as cleanup_error:
            raise ExceptionGroup(
                "Phase04-stage worker and RSS cleanup failed",
                [primary_error, cleanup_error],
            ) from primary_error
        raise
    table_stage_components = measurement.component_records()
    table_stage_seconds = round(
        sum(
            record["elapsed_seconds"]
            for record in table_stage_components.values()
        ),
        9,
    )
    table_stage_call_count = sum(
        record["call_count"] for record in table_stage_components.values()
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    stable_json = _canonical_bytes(_stable_payload(payload))
    marked_count, maximum_table, document_bytes, statuses = _sidecar_sizes(payload)
    return {
        "case_id": case_id,
        "enabled": enabled,
        "source_identity": _source_identity(case_id),
        "wall_seconds": round(elapsed_seconds, 9),
        "table_stage_seconds": table_stage_seconds,
        "table_stage_call_count": table_stage_call_count,
        "table_stage_components": table_stage_components,
        "peak_rss_bytes": _rss_bytes(),
        "rss_source": PHASE04_STAGE_RSS_SOURCE,
        "rss_normalization": PHASE04_STAGE_RSS_NORMALIZATION,
        **phase04_stage_rss,
        "phase04_stage_output_probe": output_probe,
        "phase04_stage_no_spawn_policy": no_spawn_policy,
        "semantic_json_sha256": _sha256_bytes(stable_json),
        "semantic_json_size_bytes": len(stable_json),
        "marked_table_count": marked_count,
        "maximum_marked_table_bytes": maximum_table,
        "document_sidecar_bytes": document_bytes,
        "table_status_counts": statuses,
        "quality": score_quality({case_id: payload}, workspace=workspace),
        # Only the controller parent can attach this after the worker and
        # monitor have completed and the controller scheduler is restored.
        "external_rss_monitor_attestation": None,
        "worker_diagnostics": None,
        **HOSTED_USAGE,
    }


def _write_json_atomic(
    path: Path,
    value: Mapping[str, Any],
    *,
    trusted_root: Path | None = None,
) -> None:
    """Atomically write canonical JSON through bound no-follow directories."""

    serialized = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(serialized) > MAXIMUM_RETAINED_METRICS_BYTES:
        raise ValueError("atomic JSON output exceeds its byte bound")
    destination = Path(os.path.abspath(path))
    root_input = trusted_root if trusted_root is not None else destination.parent
    lexical_root = Path(os.path.abspath(root_input))
    try:
        relative_path = destination.relative_to(lexical_root).as_posix()
    except ValueError as error:
        raise ValueError("atomic JSON output escapes its trusted root") from error
    root = _trusted_workspace_root(
        Path(root_input),
        label="atomic JSON output",
    )
    relative_path = _canonical_relative_path(
        relative_path,
        label="atomic JSON output path",
    )
    parts = Path(relative_path).parts
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    temporary_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )

    def directory_identity(observed: os.stat_result) -> tuple[int, ...]:
        # File creation necessarily changes directory size/timestamps.  Bind
        # the ownership and inode identity that prevents traversal switches.
        binding = _stat_binding(observed)
        return (binding[0], binding[1], binding[2], binding[4], binding[5])

    descriptors: list[int] = []
    temporary_descriptor: int | None = None
    temporary_leaf: str | None = None
    try:
        try:
            current_descriptor = os.open(root, directory_flags)
        except OSError as error:
            raise ValueError("atomic JSON output root cannot be opened") from error
        descriptors.append(current_descriptor)
        root_identity = directory_identity(os.fstat(current_descriptor))
        if root_identity != directory_identity(root.lstat()):
            raise ValueError("atomic JSON output root changed before writing")

        directory_entries: list[tuple[int, str, int]] = []
        for part in parts[:-1]:
            try:
                before = os.stat(
                    part,
                    dir_fd=current_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current_descriptor)
                    before = os.stat(
                        part,
                        dir_fd=current_descriptor,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise ValueError(
                        "atomic JSON output directory cannot be created"
                    ) from error
            except OSError as error:
                raise ValueError(
                    "atomic JSON output directory cannot be inspected"
                ) from error
            try:
                next_descriptor = os.open(
                    part,
                    directory_flags,
                    dir_fd=current_descriptor,
                )
            except OSError as error:
                raise ValueError(
                    "atomic JSON output cannot traverse a directory link"
                ) from error
            opened = os.fstat(next_descriptor)
            if (
                not stat.S_ISDIR(before.st_mode)
                or directory_identity(before) != directory_identity(opened)
            ):
                os.close(next_descriptor)
                raise ValueError("atomic JSON output directory changed")
            descriptors.append(next_descriptor)
            directory_entries.append(
                (current_descriptor, part, next_descriptor)
            )
            current_descriptor = next_descriptor

        # Refresh directory identities after any directories created by this
        # call, then require those exact inode bindings through replacement.
        root_identity = directory_identity(os.fstat(descriptors[0]))
        if root_identity != directory_identity(root.lstat()):
            raise ValueError("atomic JSON output root changed before writing")
        directory_bindings: list[tuple[int, str, int, tuple[int, ...]]] = []
        for parent_descriptor, part, child_descriptor in directory_entries:
            entry = os.stat(
                part,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            identity = directory_identity(entry)
            if identity != directory_identity(os.fstat(child_descriptor)):
                raise ValueError("atomic JSON output directory changed")
            directory_bindings.append(
                (parent_descriptor, part, child_descriptor, identity)
            )

        leaf = parts[-1]
        try:
            existing_binding: tuple[int, ...] | None = _stat_binding(
                os.stat(
                    leaf,
                    dir_fd=current_descriptor,
                    follow_symlinks=False,
                )
            )
        except FileNotFoundError:
            existing_binding = None
        except OSError as error:
            raise ValueError("atomic JSON output leaf cannot be inspected") from error
        if existing_binding is not None and not stat.S_ISREG(existing_binding[2]):
            raise ValueError("atomic JSON output leaf must be a regular file")

        for _attempt in range(100):
            candidate = f".{leaf}.{os.urandom(12).hex()}.tmp"
            try:
                temporary_descriptor = os.open(
                    candidate,
                    temporary_flags,
                    0o600,
                    dir_fd=current_descriptor,
                )
            except FileExistsError:
                continue
            except OSError as error:
                raise ValueError("atomic JSON temporary file cannot be created") from error
            temporary_leaf = candidate
            break
        if temporary_descriptor is None or temporary_leaf is None:
            raise ValueError("atomic JSON temporary namespace is exhausted")

        view = memoryview(serialized)
        written_bytes = 0
        while written_bytes < len(serialized):
            written = os.write(temporary_descriptor, view[written_bytes:])
            if written <= 0:
                raise ValueError("atomic JSON temporary write was incomplete")
            written_bytes += written
        os.fsync(temporary_descriptor)
        temporary_binding = os.fstat(temporary_descriptor)
        if (
            not stat.S_ISREG(temporary_binding.st_mode)
            or temporary_binding.st_size != len(serialized)
        ):
            raise ValueError("atomic JSON temporary file differs")
        os.close(temporary_descriptor)
        temporary_descriptor = None

        try:
            current_leaf_binding: tuple[int, ...] | None = _stat_binding(
                os.stat(
                    leaf,
                    dir_fd=current_descriptor,
                    follow_symlinks=False,
                )
            )
        except FileNotFoundError:
            current_leaf_binding = None
        if current_leaf_binding != existing_binding:
            raise ValueError("atomic JSON output leaf changed before replacement")
        if directory_identity(os.fstat(descriptors[0])) != root_identity:
            raise ValueError("atomic JSON output root changed while writing")
        if directory_identity(root.lstat()) != root_identity:
            raise ValueError("atomic JSON output root path changed while writing")
        for parent_descriptor, part, child_descriptor, identity in (
            directory_bindings
        ):
            entry = os.stat(
                part,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                directory_identity(entry) != identity
                or directory_identity(os.fstat(child_descriptor)) != identity
            ):
                raise ValueError("atomic JSON output directory changed while writing")
        os.replace(
            temporary_leaf,
            leaf,
            src_dir_fd=current_descriptor,
            dst_dir_fd=current_descriptor,
        )
        temporary_leaf = None
        os.fsync(current_descriptor)
    finally:
        if temporary_descriptor is not None:
            try:
                os.close(temporary_descriptor)
            except OSError:
                pass
        if temporary_leaf is not None and descriptors:
            try:
                os.unlink(
                    temporary_leaf,
                    dir_fd=descriptors[-1],
                )
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
    if _read_bounded_regular_file(
        root,
        relative_path,
        maximum_bytes=MAXIMUM_RETAINED_METRICS_BYTES,
        label="atomic JSON output verification",
    ) != serialized:
        raise ValueError("atomic JSON output verification differs")


def worker_command(
    workspace: Path,
    case_id: str,
    enabled: bool,
    output: Path,
    *,
    monitor_fd: int,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "tests.fixtures.phase_04.tables.metrics",
        "--workspace",
        str(workspace),
        "--worker-case",
        case_id,
        "--worker-enabled",
        "true" if enabled else "false",
        "--output",
        str(output),
    ]
    if type(monitor_fd) is not int or monitor_fd <= 2:
        raise ValueError("worker monitor descriptor differs")
    command.extend(("--rss-monitor-fd", str(monitor_fd)))
    return command


def _diagnostic_stream_record(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    classifications = {
        "informational": 0,
        "progress": 0,
        "warning": 0,
        "phase04_warning": 0,
        "unexpected": 0,
    }
    nonempty = 0
    for line in lines:
        normalized = line.strip()
        if not normalized:
            continue
        nonempty += 1
        folded = normalized.casefold()
        warning = "warning" in folded or re.search(r"\bwarn\b", folded)
        phase04 = any(
            token in folded
            for token in ("phase 04", "phase04", "p04", "table span")
        )
        if warning and phase04:
            classifications["phase04_warning"] += 1
        elif warning:
            classifications["warning"] += 1
        elif (
            re.search(r"(?:^|\s)\d{1,3}%\|", normalized) is not None
            or "it/s" in folded
            or "progress" in folded
        ):
            classifications["progress"] += 1
        elif re.match(
            r"^(?:DEBUG|INFO|NOTICE|Loading|Loaded|Processing|Converting|Docling)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            classifications["informational"] += 1
        else:
            classifications["unexpected"] += 1
    return {
        "size_bytes": len(raw),
        "sha256": _sha256_bytes(raw),
        "line_count": len(lines),
        "nonempty_line_count": nonempty,
        "classifications": classifications,
    }


def _bind_worker_group_ownership(process: Any) -> dict[str, Any]:
    if sys.platform not in {"darwin", "linux"}:
        raise RuntimeError("worker process-group platform differs")
    import psutil

    if psutil.__version__ != PHASE04_STAGE_CURRENT_RSS_SOURCE_VERSION:
        raise RuntimeError("worker process-group identity source differs")
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid < 1 or pid == os.getpid():
        raise RuntimeError("worker process-group PID differs")
    owner_pid = os.getpid()
    owner_pgid = os.getpgrp()
    owner_sid = os.getsid(0)
    pgid = os.getpgid(pid)
    sid = os.getsid(pid)
    create_time = psutil.Process(pid).create_time()
    if (
        type(create_time) not in {int, float}
        or type(create_time) is bool
        or not math.isfinite(float(create_time))
        or create_time <= 0
    ):
        raise RuntimeError("worker process-group create identity differs")
    create_time_ns = int(round(float(create_time) * 1e9))
    ownership = {
        "schema_id": WORKER_GROUP_IDENTITY_SCHEMA_ID,
        "owner_pid": owner_pid,
        "owner_pgid": owner_pgid,
        "owner_sid": owner_sid,
        "leader_pid": pid,
        "leader_create_time_ns": create_time_ns,
        "pgid": pgid,
        "sid": sid,
    }
    _validate_worker_group_ownership(process, ownership)
    return ownership


def _validate_worker_group_identity_without_reap(
    process: Any,
    ownership: Mapping[str, Any],
) -> None:
    expected_fields = {
        "schema_id",
        "owner_pid",
        "owner_pgid",
        "owner_sid",
        "leader_pid",
        "leader_create_time_ns",
        "pgid",
        "sid",
    }
    if type(ownership) is not dict or set(ownership) != expected_fields:
        raise RuntimeError("worker process-group ownership differs")
    integer_fields = expected_fields - {"schema_id"}
    if (
        ownership["schema_id"] != WORKER_GROUP_IDENTITY_SCHEMA_ID
        or any(
            type(ownership[field]) is not int or ownership[field] < 1
            for field in integer_fields
        )
        or ownership["owner_pid"] != os.getpid()
        or ownership["owner_pgid"] != os.getpgrp()
        or ownership["owner_sid"] != os.getsid(0)
        or getattr(process, "pid", None) != ownership["leader_pid"]
        or ownership["pgid"] != ownership["leader_pid"]
        or ownership["sid"] != ownership["leader_pid"]
        or ownership["pgid"] == ownership["owner_pgid"]
        or ownership["sid"] == ownership["owner_sid"]
    ):
        raise RuntimeError("worker process-group ownership differs")
    import psutil

    try:
        target = psutil.Process(process.pid)
        current_create_time_ns = int(
            round(float(target.create_time()) * 1e9)
        )
        current_parent_pid = target.ppid()
        current_pgid = os.getpgid(process.pid)
        current_sid = os.getsid(process.pid)
    except (OSError, psutil.Error) as error:
        raise RuntimeError("worker process-group identity changed") from error
    if (
        current_create_time_ns != ownership["leader_create_time_ns"]
        or current_parent_pid != ownership["owner_pid"]
        or current_pgid != ownership["pgid"]
        or current_sid != ownership["sid"]
    ):
        raise RuntimeError("worker process-group identity changed")


def _validate_worker_group_ownership(
    process: Any,
    ownership: Mapping[str, Any],
    *,
    lifetime_lease: _WorkerLifetimeLease | None = None,
) -> None:
    if lifetime_lease is not None:
        lifetime_lease.require_operation_allowed("poll")
    try:
        return_code = process.poll()
    except BaseException:
        raise
    if return_code is None:
        _validate_worker_group_identity_without_reap(process, ownership)
        return
    # Once the exact Popen object has observed/reaped termination, retain the
    # immutable ownership fields but do not attempt PID-based identity reads.
    expected_fields = {
        "schema_id",
        "owner_pid",
        "owner_pgid",
        "owner_sid",
        "leader_pid",
        "leader_create_time_ns",
        "pgid",
        "sid",
    }
    if (
        type(ownership) is not dict
        or set(ownership) != expected_fields
        or ownership.get("schema_id") != WORKER_GROUP_IDENTITY_SCHEMA_ID
        or getattr(process, "pid", None) != ownership.get("leader_pid")
    ):
        raise RuntimeError("worker process-group ownership differs")


def _owned_worker_group_exists(ownership: Mapping[str, Any]) -> bool:
    pgid = ownership["pgid"]
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # A just-signalled group can transiently be visible but no longer
        # signalable while the kernel/reaper completes teardown.  Callers may
        # retry this exact, sanitized condition, but may never treat it as an
        # absence proof.
        raise PermissionError("worker process-group cleanup proof denied") from None
    return True


def _drain_worker_cleanup_pipes(
    selector: selectors.BaseSelector | None,
    *,
    wait_seconds: float,
) -> None:
    if selector is None:
        threading.Event().wait(wait_seconds)
        return
    try:
        events = selector.select(timeout=wait_seconds)
    except (OSError, ValueError):
        return
    for key, _mask in events:
        try:
            chunk = os.read(key.fileobj.fileno(), 64 * 1024)
        except (BlockingIOError, OSError, ValueError):
            continue
        if chunk:
            continue
        try:
            selector.unregister(key.fileobj)
        except (KeyError, ValueError):
            pass
        try:
            key.fileobj.close()
        except OSError:
            pass


def _wait_owned_worker_group_dead(
    process: Any,
    ownership: Mapping[str, Any],
    selector: selectors.BaseSelector | None,
    *,
    timeout_seconds: float,
    deferred_cancellations: list[BaseException],
) -> tuple[bool, bool]:
    deadline = time.monotonic() + timeout_seconds
    permission_uncertain = False
    while True:
        _call_deferring_cancellation(process.poll, deferred_cancellations)
        try:
            exists = _call_deferring_cancellation(
                lambda: _owned_worker_group_exists(ownership),
                deferred_cancellations,
            )
            if not exists:
                return True, permission_uncertain
        except PermissionError:
            # Permission is not absence.  Keep polling to the hard deadline;
            # success still requires an observable ESRCH/ProcessLookupError.
            permission_uncertain = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, permission_uncertain
        try:
            _drain_worker_cleanup_pipes(
                selector,
                wait_seconds=min(remaining, 0.020),
            )
        except BaseException as error:
            if isinstance(error, Exception):
                raise
            deferred_cancellations.append(error)


def _call_deferring_cancellation(
    operation: Any,
    deferred_cancellations: list[BaseException],
) -> Any:
    """Retry an idempotent cleanup operation after deferred cancellation."""

    while True:
        try:
            return operation()
        except BaseException as error:
            if isinstance(error, Exception):
                raise
            deferred_cancellations.append(error)


def _terminate_worker(
    process: Any,
    ownership: Mapping[str, Any],
    selector: selectors.BaseSelector | None = None,
    *,
    deferred_cancellations: list[BaseException] | None = None,
) -> bool:
    """Idempotently terminate and prove death of one exact owned session."""

    local_cancellations: list[BaseException] = []
    cleanup_error: Exception | None = None
    phase = "validate"
    initial_group_existed = False
    term_signal_observed_esrch = False
    kill_signal_observed_esrch = False
    kill_attempt_cancelled = False
    kill_attempt_count = 0
    reap_deadline: float | None = None
    while phase != "done" and cleanup_error is None:
        current_phase = phase
        try:
            if phase == "validate":
                _validate_worker_group_ownership(process, ownership)
                phase = "initial_probe"
            elif phase == "initial_probe":
                initial_group_existed = _owned_worker_group_exists(ownership)
                if initial_group_existed:
                    phase = "term_signal"
                else:
                    phase = "final_probe"
            elif phase == "term_signal":
                # Advance before the syscall.  Cancellation can be delivered
                # immediately before or after the kernel operation; either
                # way cleanup resumes with proof-only TERM grace and then an
                # identity-bound KILL when the exact group remains.
                phase = "term_wait"
                term_signal_observed_esrch = False
                try:
                    os.killpg(ownership["pgid"], signal.SIGTERM)
                except ProcessLookupError:
                    term_signal_observed_esrch = True
            elif phase == "term_wait":
                term_dead, term_permission_uncertain = (
                    _wait_owned_worker_group_dead(
                        process,
                        ownership,
                        selector,
                        timeout_seconds=WORKER_GROUP_TERM_GRACE_SECONDS,
                        deferred_cancellations=local_cancellations,
                    )
                )
                if term_dead:
                    phase = "final_probe"
                elif term_permission_uncertain or term_signal_observed_esrch:
                    raise RuntimeError(
                        "worker process-group cleanup authority became uncertain"
                    )
                else:
                    phase = "kill_signal"
            elif phase == "kill_signal":
                kill_attempt_count += 1
                kill_attempt_cancelled = False
                kill_signal_observed_esrch = False
                phase = "kill_wait"
                try:
                    os.killpg(ownership["pgid"], signal.SIGKILL)
                except ProcessLookupError:
                    kill_signal_observed_esrch = True
            elif phase == "kill_wait":
                kill_dead, kill_permission_uncertain = (
                    _wait_owned_worker_group_dead(
                        process,
                        ownership,
                        selector,
                        timeout_seconds=WORKER_GROUP_KILL_GRACE_SECONDS,
                        deferred_cancellations=local_cancellations,
                    )
                )
                if kill_dead:
                    phase = "final_probe"
                elif kill_permission_uncertain or kill_signal_observed_esrch:
                    raise RuntimeError(
                        "worker process-group kill authority became uncertain"
                    )
                elif kill_attempt_cancelled and kill_attempt_count < 2:
                    # A cancellation raised by the signal wrapper does not
                    # prove delivery.  The completed KILL wait continuously
                    # observed this already-bound group without EPERM or
                    # ESRCH, so one bounded retry is safe even when TERM has
                    # reaped the leader but left a stubborn owned descendant.
                    # Any permission/absence observation takes the branches
                    # above and permanently forbids the retry.
                    phase = "kill_signal"
                else:
                    raise RuntimeError(
                        "worker process-group cleanup did not prove death"
                    )
            elif phase == "final_probe":
                if _owned_worker_group_exists(ownership):
                    raise RuntimeError(
                        "worker process-group cleanup proof failed"
                    )
                phase = "reap"
            elif phase == "reap":
                if process.poll() is not None:
                    phase = "done"
                    continue
                if reap_deadline is None:
                    reap_deadline = time.monotonic() + 0.100
                remaining = reap_deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "worker process-group leader was not reaped"
                    )
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(
                        "worker process-group leader was not reaped"
                    ) from error
            else:  # pragma: no cover - private state invariant
                raise RuntimeError(
                    "worker process-group cleanup state differs"
                )
        except Exception as error:
            cleanup_error = error
        except BaseException as error:
            local_cancellations.append(error)
            if current_phase == "term_signal":
                phase = "term_wait"
            elif current_phase == "kill_signal":
                kill_attempt_cancelled = True
                phase = "kill_wait"
    if cleanup_error is not None:
        raise _WorkerProcessControlError(
            "fresh P04-US01 worker category=process_group_cleanup_failure "
            f"error_type={type(cleanup_error).__name__}"
        ) from None
    if deferred_cancellations is not None:
        deferred_cancellations.extend(local_cancellations)
    elif local_cancellations:
        raise local_cancellations[0]
    return initial_group_existed


def _spawn_owned_worker_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    ownership_registration: Any | None = None,
    pre_release_callback: Any | None = None,
    inherited_fds: Sequence[int] = (),
) -> tuple[Any, dict[str, Any]]:
    ready_read = -1
    ready_write = -1
    release_read = -1
    release_write = -1
    open_control_descriptors: set[int] = set()
    process: Any | None = None
    ownership: dict[str, Any] | None = None
    ownership_transferred = False
    inherited_descriptors = tuple(inherited_fds)
    if (
        len(inherited_descriptors) > 16
        or any(
            type(descriptor) is not int or descriptor <= 2
            for descriptor in inherited_descriptors
        )
        or len(set(inherited_descriptors)) != len(inherited_descriptors)
    ):
        raise ValueError("worker inherited descriptor policy differs")
    if pre_release_callback is not None and ownership_registration is None:
        raise ValueError(
            "worker pre-release callback requires registered ownership"
        )

    def close_control_descriptors(
        descriptors: Sequence[int],
    ) -> BaseException | None:
        first_error: BaseException | None = None
        for descriptor in descriptors:
            if descriptor < 0 or descriptor not in open_control_descriptors:
                continue
            # Remove before close: POSIX leaves an EINTR close state
            # unspecified, so retrying that numeric descriptor could target a
            # subsequently reused resource.
            open_control_descriptors.remove(descriptor)
            try:
                os.close(descriptor)
            except BaseException as error:  # pragma: no cover - defensive
                first_error = first_error or error
        return first_error

    try:
        try:
            ready_read, ready_write = os.pipe()
            open_control_descriptors.update((ready_read, ready_write))
            release_read, release_write = os.pipe()
            open_control_descriptors.update((release_read, release_write))
        except OSError as error:
            error_number = error.errno if type(error.errno) is int else "unknown"
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=process_group_setup_failure "
                f"error_type={type(error).__name__} errno={error_number}"
            ) from None
        popen_error: BaseException | None = None
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _WORKER_EXEC_BOOTSTRAP,
                    str(ready_write),
                    str(release_read),
                    *list(command),
                ],
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                close_fds=True,
                pass_fds=(
                    ready_write,
                    release_read,
                    *inherited_descriptors,
                ),
                start_new_session=True,
            )
        except BaseException as error:
            popen_error = error
        finally:
            descriptor_error = close_control_descriptors(
                (ready_write, release_read)
            )
        if descriptor_error is not None:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=process_group_setup_failure "
                f"error_type={type(descriptor_error).__name__}"
            ) from None
        if popen_error is not None:
            if isinstance(popen_error, OSError):
                error_number = (
                    popen_error.errno
                    if type(popen_error.errno) is int
                    else "unknown"
                )
                raise _WorkerProcessControlError(
                    "fresh P04-US01 worker category=spawn_failure "
                    f"error_type={type(popen_error).__name__} "
                    f"errno={error_number}"
                ) from None
            raise popen_error
        ownership = _bind_worker_group_ownership(process)
        ready_selector = selectors.DefaultSelector()
        selector_error: BaseException | None = None
        try:
            ready_selector.register(ready_read, selectors.EVENT_READ)
            events = ready_selector.select(timeout=WORKER_BOOTSTRAP_READY_SECONDS)
            ready = os.read(ready_read, 1) if events else b""
        finally:
            try:
                ready_selector.close()
            except BaseException as error:  # pragma: no cover - defensive
                selector_error = error
            selector_error = selector_error or close_control_descriptors(
                (ready_read,)
            )
        if selector_error is not None:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=process_group_setup_failure "
                f"error_type={type(selector_error).__name__}"
            ) from None
        if ready != b"R":
            raise _WorkerProcessControlError(
                "worker process bootstrap readiness differs"
            )
        if ownership_registration is not None:
            setattr(
                process,
                "_phase04_bootstrap_release_write_fd",
                release_write,
            )
            open_control_descriptors.remove(release_write)
            # Invocation transfers blocked-bootstrap custody to the caller.
            # The internal guard registers identity before it can raise, so a
            # cancellation delivered on callback return cannot create an
            # unowned process or close the release pipe behind cleanup.
            ownership_transferred = True
            ownership_registration(process, ownership)
        if pre_release_callback is not None:
            pre_release_callback(process, ownership)
        if os.write(release_write, b"G") != 1:
            raise _WorkerProcessControlError(
                "worker process bootstrap release differs"
            )
        if ownership_transferred:
            setattr(process, "_phase04_bootstrap_release_write_fd", None)
            try:
                os.close(release_write)
            except BaseException as error:
                descriptor_error = error
        else:
            descriptor_error = close_control_descriptors((release_write,))
        if descriptor_error is not None:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker category=process_group_setup_failure "
                f"error_type={type(descriptor_error).__name__}"
            ) from None
        return process, ownership
    except BaseException as setup_error:
        setup_cleanup_cancellations: list[BaseException] = []
        cleanup_error = close_control_descriptors(
            tuple(open_control_descriptors)
        )
        if process is not None and not ownership_transferred:
            try:
                if ownership is not None:
                    _call_deferring_cancellation(
                        lambda: _terminate_worker(
                            process,
                            ownership,
                            deferred_cancellations=(
                                setup_cleanup_cancellations
                            ),
                        ),
                        setup_cleanup_cancellations,
                    )
                else:
                    # The bootstrap cannot execute the requested command until
                    # the release pipe receives ``G``.  If ownership binding
                    # failed, closing that pipe leaves only the isolated
                    # bootstrap itself to terminate and reap.
                    if _call_deferring_cancellation(
                        process.poll,
                        setup_cleanup_cancellations,
                    ) is None:
                        try:
                            process.terminate()
                        except ProcessLookupError:
                            pass
                        except BaseException as error:
                            if isinstance(error, Exception):
                                raise
                            setup_cleanup_cancellations.append(error)
                        try:
                            _call_deferring_cancellation(
                                lambda: process.wait(
                                    timeout=WORKER_GROUP_TERM_GRACE_SECONDS
                                ),
                                setup_cleanup_cancellations,
                            )
                        except subprocess.TimeoutExpired:
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                            except BaseException as error:
                                if isinstance(error, Exception):
                                    raise
                                setup_cleanup_cancellations.append(error)
                            _call_deferring_cancellation(
                                lambda: process.wait(
                                    timeout=WORKER_GROUP_KILL_GRACE_SECONDS
                                ),
                                setup_cleanup_cancellations,
                            )
            except BaseException as error:  # pragma: no cover - fail-closed
                cleanup_error = cleanup_error or error
            finally:
                for stream in (process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        try:
                            _call_deferring_cancellation(
                                stream.close,
                                setup_cleanup_cancellations,
                            )
                        except Exception as error:  # pragma: no cover
                            cleanup_error = cleanup_error or error
        if cleanup_error is not None:
            raise RuntimeError(
                "fresh P04-US01 worker category=process_group_cleanup_failure "
                f"error_type={type(cleanup_error).__name__}"
            ) from None
        if not isinstance(setup_error, Exception):
            raise setup_error
        if isinstance(setup_error, _WorkerProcessControlError):
            raise
        raise RuntimeError(
            "fresh P04-US01 worker category=process_group_setup_failure "
            f"error_type={type(setup_error).__name__}"
        ) from None


class _OwnedWorkerProcessGuard:
    """Own the worker from pre-spawn through explicit release or cleanup."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        inherited_fds: Sequence[int] = (),
        monitor_binding: _ExternalRSSMonitorBinding | None = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._environment = environment
        self._inherited_fds = tuple(inherited_fds)
        self._monitor_binding = monitor_binding
        self._lifetime_lease = (
            _WorkerLifetimeLease() if monitor_binding is not None else None
        )
        self._owned: tuple[Any, dict[str, Any]] | None = None
        self._termination_attempted = False
        self._termination_proved = False
        self._released = False

    def _register(self, process: Any, ownership: dict[str, Any]) -> None:
        if self._owned is not None or self._released:
            raise RuntimeError("worker ownership registration differs")
        self._owned = (process, ownership)

    def _bind_monitor_before_release(
        self,
        process: Any,
        ownership: dict[str, Any],
    ) -> None:
        if self._monitor_binding is None:
            return
        try:
            lease = self._lifetime_lease
            if lease is None:
                raise RuntimeError("worker lifetime lease is absent")
            lease.acquire(process, ownership)
            self._monitor_binding.bind(
                process,
                ownership,
                lifetime_lease=lease,
            )
        except BaseException as error:
            if not isinstance(error, Exception):
                raise
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker "
                "category=external_monitor_bind_failure "
                f"error_type={type(error).__name__}"
            ) from None

    def __enter__(self) -> tuple[Any, dict[str, Any]]:
        try:
            if self._lifetime_lease is not None:
                self._lifetime_lease.require_default_sigchld()
            owned = _spawn_owned_worker_process(
                self._command,
                cwd=self._cwd,
                environment=self._environment,
                ownership_registration=self._register,
                pre_release_callback=(
                    self._bind_monitor_before_release
                    if self._monitor_binding is not None
                    else None
                ),
                inherited_fds=self._inherited_fds,
            )
            if (
                self._owned is None
                or owned[0] is not self._owned[0]
                or owned[1] is not self._owned[1]
            ):
                raise RuntimeError("worker ownership handoff differs")
            if self._lifetime_lease is not None:
                self._lifetime_lease.record_worker_bootstrap_released()
            return owned
        except BaseException as primary_failure:
            if self._owned is not None:
                self._cleanup(primary_failure=primary_failure)
            raise

    def mark_released(self) -> None:
        if (
            self._owned is None
            or self._released
            or not self._termination_proved
        ):
            raise RuntimeError("worker ownership release differs")
        self._released = True

    def preserve_unreaped_identity_after_monitor_failure(self) -> None:
        """Reject abandonment: exact monitor and worker cleanup must complete."""

        if (
            self._owned is None
            or self._released
            or self._termination_attempted
        ):
            raise RuntimeError("worker unreaped custody state differs")
        raise RuntimeError(
            "worker ownership cannot be released while monitor cleanup is unproved"
        )

    def terminate(
        self,
        selector: selectors.BaseSelector | None,
        deferred_cancellations: list[BaseException],
    ) -> bool:
        if self._owned is None or self._released:
            raise RuntimeError("worker ownership termination differs")
        process, ownership = self._owned
        if self._lifetime_lease is not None:
            self._lifetime_lease.require_operation_allowed(
                "process_group_cleanup"
            )

        def terminate_registered_worker() -> bool:
            self._termination_attempted = True
            return _terminate_worker(
                process,
                ownership,
                selector,
                deferred_cancellations=deferred_cancellations,
            )

        group_existed = _call_deferring_cancellation(
            terminate_registered_worker,
            deferred_cancellations,
        )
        self._termination_proved = True
        return group_existed

    def worker_cleanup_custody(self) -> dict[str, Any]:
        if self._owned is None:
            raise RuntimeError("worker cleanup custody is absent")
        process, ownership = self._owned
        streams = (getattr(process, "stdout", None), getattr(process, "stderr", None))
        return {
            "termination_attempted": self._termination_attempted,
            "process_reaped": self._termination_proved,
            "process_group_absent": self._termination_proved,
            "stdout_closed": streams[0] is None or streams[0].closed,
            "stderr_closed": streams[1] is None or streams[1].closed,
        }

    def _cleanup(self, *, primary_failure: BaseException | None) -> None:
        if self._owned is None or self._released:
            return
        process, ownership = self._owned
        cleanup_cancellations: list[BaseException] = []
        cleanup_error: Exception | None = None
        worker_release_safe = self._monitor_binding is None
        if self._monitor_binding is not None:
            for _attempt in range(3):
                try:
                    self._monitor_binding.quiesce_before_worker_release(None)
                except Exception as error:
                    cleanup_error = cleanup_error or error
                try:
                    self._monitor_binding.require_sampling_quiesced()
                except Exception as error:
                    cleanup_error = cleanup_error or error
                    continue
                lease = self._lifetime_lease
                if lease is not None and lease.active:
                    # A pre-bind failure can leave release ownership with this
                    # guard.  Transition it only after the binding proves both
                    # sampling lanes physically quiescent.
                    if lease.worker_bootstrap_released:
                        lease.release_after_sampling_quiescence(
                            observer_quiesced=True,
                            current_rss_lane_quiesced=True,
                        )
                    else:
                        lease.release_after_failed_setup_quiescence(
                            observer_quiesced=True,
                            current_rss_lane_quiesced=True,
                        )
                worker_release_safe = True
                break
        if not self._termination_attempted and worker_release_safe:
            try:
                already_reaped = (
                    not _owned_worker_group_exists(ownership)
                    and _call_deferring_cancellation(
                        lambda: (
                            self._lifetime_lease.require_operation_allowed(
                                "poll"
                            )
                            if self._lifetime_lease is not None
                            else None
                        )
                        or process.poll(),
                        cleanup_cancellations,
                    )
                    is not None
                )
                if already_reaped:
                    self._termination_attempted = True
                    self._termination_proved = True
                else:
                    self.terminate(None, cleanup_cancellations)
            except Exception as error:
                cleanup_error = cleanup_error or error
        elif not worker_release_safe:
            cleanup_error = cleanup_error or RuntimeError(
                "monitor sampling quiescence was not proved"
            )
        if worker_release_safe:
            release_descriptor = getattr(
                process,
                "_phase04_bootstrap_release_write_fd",
                None,
            )
            if release_descriptor is not None:
                setattr(process, "_phase04_bootstrap_release_write_fd", None)
                try:
                    os.close(release_descriptor)
                except OSError as error:
                    cleanup_error = cleanup_error or error
                except BaseException as error:
                    cleanup_cancellations.append(error)
        for stream_name in ("stdout", "stderr"):
            try:
                stream = _call_deferring_cancellation(
                    lambda name=stream_name: getattr(process, name),
                    cleanup_cancellations,
                )
                if stream is not None and not stream.closed:
                    _call_deferring_cancellation(
                        stream.close,
                        cleanup_cancellations,
                    )
            except Exception as error:
                cleanup_error = cleanup_error or error
        if self._termination_proved:
            self._released = True
        if cleanup_error is not None:
            raise _WorkerProcessControlError(
                "fresh P04-US01 worker "
                "category=process_group_cleanup_failure "
                f"error_type={type(cleanup_error).__name__}"
            ) from None
        self._released = True
        if cleanup_cancellations and (
            primary_failure is None or isinstance(primary_failure, Exception)
        ):
            raise cleanup_cancellations[0]

    def __exit__(
        self,
        exception_type: Any,
        exception: BaseException | None,
        traceback: Any,
    ) -> bool:
        del exception_type, traceback
        self._cleanup(primary_failure=exception)
        return False


def _run_acquired_worker_process_bounded(
    guard: _OwnedWorkerProcessGuard,
    process: Any,
    ownership: Mapping[str, Any],
    *,
    timeout_seconds: float,
    maximum_stream_bytes: int,
    monitor_binding: _ExternalRSSMonitorBinding | None = None,
) -> tuple[int, bytes, bytes]:
    """Run one already-guarded worker; every exit releases exact ownership."""

    streams = {
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    selector: selectors.BaseSelector | None = None
    active_failure = False
    primary_failure: BaseException | None = None
    lingering_group = False
    cleanup_error: Exception | None = None
    cleanup_cancellations: list[BaseException] = []
    try:
        if any(stream is None for stream in streams.values()):
            raise RuntimeError("fresh P04-US01 worker pipe setup failed")
        selector = selectors.DefaultSelector()
        for name, stream in streams.items():
            assert stream is not None
            selector.register(stream, selectors.EVENT_READ, data=name)
        if monitor_binding is not None:
            monitor_binding.register(selector)
        deadline = time.monotonic() + float(timeout_seconds)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("fresh P04-US01 worker category=timeout")
            events = selector.select(timeout=min(remaining, 0.100))
            if (
                monitor_binding is None
                and not events
                and process.poll() is not None
            ):
                # Unmonitored workers have no live sampler which could race
                # this reap. A final nonblocking iteration observes pipe EOF
                # or classifies a descendant-owned lingering group.
                events = selector.select(timeout=0)
                if (
                    not events
                    and selector.get_map()
                    and _owned_worker_group_exists(ownership)
                ):
                    raise RuntimeError(
                        "fresh P04-US01 worker "
                        "category=lingering_process_group"
                    )
            for key, _mask in events:
                name = key.data
                if name == "external_rss_monitor":
                    try:
                        monitor_binding.consume_ready(selector)
                    except Exception as error:
                        monitor_binding.note_monitor_failure(error)
                        failure_summary = monitor_binding.failure_summary
                        if failure_summary is None:
                            safe_failure = "failure_code=monitor_operation_failed"
                        else:
                            classified = failure_summary.get(
                                "classified_lane_failure"
                            )
                            classified_suffix = ""
                            if type(classified) is dict:
                                classified_suffix = (
                                    " phase="
                                    f"{classified['phase']}"
                                    " operation_context="
                                    f"{classified['operation_context']}"
                                    " scheduler_delay_ns="
                                    f"{classified['scheduler_delay_ns']}"
                                    " sampling_call_duration_ns="
                                    f"{classified['sampling_call_duration_ns']}"
                                    " cadence_classification="
                                    f"{classified['cadence_classification']}"
                                )
                            safe_failure = (
                                f"failure_code={failure_summary['cause_code']} "
                                "observed_gap_ns="
                                f"{failure_summary['observed_gap_ns']} "
                                "hard_gap_ns="
                                f"{failure_summary['hard_gap_ns']} "
                                "accepted_continuous_count="
                                f"{failure_summary['accepted_continuous_count']}"
                                f"{classified_suffix}"
                            )
                        raise RuntimeError(
                            "fresh P04-US01 worker "
                            "category=external_monitor_failure "
                            f"error_type={type(error).__name__} "
                            f"{safe_failure}"
                        ) from None
                    continue
                try:
                    chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                updated_size = len(buffers[name]) + len(chunk)
                if updated_size > maximum_stream_bytes:
                    partial = bytes(buffers[name])
                    raise RuntimeError(
                        "fresh P04-US01 worker category=diagnostic_overflow "
                        f"stream={name} retained_bytes={len(partial)} "
                        f"retained_sha256={_sha256_bytes(partial)}"
                    )
                buffers[name].extend(chunk)
        if monitor_binding is not None:
            try:
                monitor_binding.require_complete()
                monitor_binding.quiesce_before_worker_release(selector)
            except Exception as error:
                raise RuntimeError(
                    "fresh P04-US01 worker "
                    "category=external_monitor_incomplete "
                    f"error_type={type(error).__name__}"
                ) from None
        remaining = max(deadline - time.monotonic(), 0.001)
        try:
            if guard._lifetime_lease is not None:
                guard._lifetime_lease.require_operation_allowed("wait")
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "fresh P04-US01 worker category=timeout"
            ) from None
    except BaseException as error:
        active_failure = True
        primary_failure = error
        raise
    finally:
        worker_release_safe = monitor_binding is None
        if monitor_binding is not None:
            for _attempt in range(3):
                try:
                    monitor_binding.quiesce_before_worker_release(selector)
                except Exception as error:
                    monitor_binding.note_monitor_failure(error)
                    cleanup_error = cleanup_error or error
                try:
                    monitor_binding.require_sampling_quiesced()
                except Exception as error:
                    monitor_binding.note_monitor_failure(error)
                    cleanup_error = cleanup_error or error
                    continue
                lease = guard._lifetime_lease
                if lease is not None and lease.active:
                    if lease.worker_bootstrap_released:
                        lease.release_after_sampling_quiescence(
                            observer_quiesced=True,
                            current_rss_lane_quiesced=True,
                        )
                    else:
                        lease.release_after_failed_setup_quiescence(
                            observer_quiesced=True,
                            current_rss_lane_quiesced=True,
                        )
                worker_release_safe = True
                break
        try:
            if worker_release_safe:
                group_existed = guard.terminate(
                    selector,
                    cleanup_cancellations,
                )
                lingering_group = group_existed and not active_failure
            else:
                cleanup_error = cleanup_error or RuntimeError(
                    "monitor sampling quiescence was not proved"
                )
        except Exception as error:
            cleanup_error = cleanup_error or error
        finally:
            if selector is not None:
                try:
                    _call_deferring_cancellation(
                        selector.close,
                        cleanup_cancellations,
                    )
                except Exception as error:  # pragma: no cover - defensive
                    cleanup_error = cleanup_error or error
            for stream in streams.values():
                if stream is not None and not stream.closed:
                    try:
                        _call_deferring_cancellation(
                            stream.close,
                            cleanup_cancellations,
                        )
                    except Exception as error:  # pragma: no cover - defensive
                        cleanup_error = cleanup_error or error
        if monitor_binding is not None and primary_failure is not None:
            try:
                setattr(
                    primary_failure,
                    "failure_custody",
                    monitor_binding.failure_custody(
                        worker_cleanup=guard.worker_cleanup_custody()
                    ),
                )
            except Exception as error:
                cleanup_error = cleanup_error or error
        if worker_release_safe and guard._termination_proved:
            guard.mark_released()
        if cleanup_error is not None:
            if isinstance(cleanup_error, _WorkerProcessControlError):
                raise cleanup_error
            raise RuntimeError(
                "fresh P04-US01 worker category=process_group_cleanup_failure "
                f"error_type={type(cleanup_error).__name__}"
            ) from None
        if lingering_group:
            raise RuntimeError(
                "fresh P04-US01 worker category=lingering_process_group"
            )
        if cleanup_cancellations and primary_failure is None:
            raise cleanup_cancellations[0]
    return return_code, bytes(buffers["stdout"]), bytes(buffers["stderr"])


def _run_worker_process_bounded(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float = WORKER_TIMEOUT_SECONDS,
    maximum_stream_bytes: int = MAXIMUM_WORKER_DIAGNOSTIC_BYTES,
    inherited_fds: Sequence[int] = (),
    monitor_binding: _ExternalRSSMonitorBinding | None = None,
) -> tuple[int, bytes, bytes]:
    """Drain both worker pipes concurrently and stop at either hard cap."""

    if (
        type(timeout_seconds) not in {int, float}
        or type(timeout_seconds) is bool
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
        or type(maximum_stream_bytes) is not int
        or maximum_stream_bytes < 1
        or maximum_stream_bytes > MAXIMUM_WORKER_DIAGNOSTIC_BYTES
    ):
        raise ValueError("worker process resource policy differs")
    if (
        isinstance(command, (str, bytes))
        or not command
        or len(command) > 256
        or any(
            type(argument) is not str
            or not argument
            or "\x00" in argument
            or len(argument.encode("utf-8")) > 16 * 1024
            for argument in command
        )
    ):
        raise ValueError("worker process command policy differs")
    normalized_inherited_fds = tuple(inherited_fds)
    if (
        len(normalized_inherited_fds) > 16
        or any(
            type(descriptor) is not int or descriptor <= 2
            for descriptor in normalized_inherited_fds
        )
        or len(set(normalized_inherited_fds)) != len(normalized_inherited_fds)
        or (monitor_binding is None) != (len(normalized_inherited_fds) == 0)
        or (
            monitor_binding is not None
            and normalized_inherited_fds
            != (monitor_binding.worker_descriptor,)
        )
    ):
        raise ValueError("worker inherited descriptor policy differs")
    guard = _OwnedWorkerProcessGuard(
        command,
        cwd=cwd,
        environment=environment,
        inherited_fds=normalized_inherited_fds,
        monitor_binding=monitor_binding,
    )
    try:
        with guard as owned_worker:
            process, ownership = owned_worker
            return _run_acquired_worker_process_bounded(
                guard,
                process,
                ownership,
                timeout_seconds=float(timeout_seconds),
                maximum_stream_bytes=maximum_stream_bytes,
                monitor_binding=monitor_binding,
            )
    finally:
        if monitor_binding is not None:
            monitor_binding.abort()


def fresh_snapshot(
    workspace: Path, case_id: str, enabled: bool
) -> dict[str, Any]:
    """Run one sample in a new process under the exact offline environment."""

    workspace = _trusted_workspace_root(
        workspace,
        label="fresh worker workspace",
    )
    with tempfile.TemporaryDirectory(prefix=f"p04-us01-{case_id}-") as directory:
        output = Path(directory) / "snapshot.json"
        environment = os.environ.copy()
        environment.update(OFFLINE_ENVIRONMENT)
        environment.update(WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT)
        monitor_binding = _ExternalRSSMonitorBinding.create()
        worker_descriptor = monitor_binding.worker_descriptor
        try:
            return_code, stdout_raw, stderr_raw = _run_worker_process_bounded(
                worker_command(
                    workspace,
                    case_id,
                    enabled,
                    output,
                    monitor_fd=worker_descriptor,
                ),
                cwd=workspace,
                environment=environment,
                inherited_fds=(worker_descriptor,),
                monitor_binding=monitor_binding,
            )
            parent_rss_record = monitor_binding.record
        finally:
            monitor_binding.abort()
        diagnostics = {
            "schema_id": WORKER_DIAGNOSTIC_SCHEMA_ID,
            "maximum_stream_bytes": MAXIMUM_WORKER_DIAGNOSTIC_BYTES,
            "suppression_environment": dict(
                WORKER_DIAGNOSTIC_SUPPRESSION_ENVIRONMENT
            ),
            "stdout": _diagnostic_stream_record(stdout_raw),
            "stderr": _diagnostic_stream_record(stderr_raw),
        }
        if return_code != 0:
            diagnostic_identity = {
                stream: {
                    "size_bytes": diagnostics[stream]["size_bytes"],
                    "sha256": diagnostics[stream]["sha256"],
                    "line_count": diagnostics[stream]["line_count"],
                }
                for stream in ("stdout", "stderr")
            }
            raise RuntimeError(
                "fresh P04-US01 metrics worker category=nonzero_exit "
                f"case={case_id} enabled={enabled} exit_code={return_code} "
                f"diagnostics={_canonical_bytes(diagnostic_identity).decode('ascii')}"
            )
        _validate_worker_diagnostics(diagnostics)
        snapshot_raw = _read_bounded_regular_file(
            Path(directory),
            "snapshot.json",
            maximum_bytes=MAXIMUM_RETAINED_METRICS_BYTES,
            label="fresh worker snapshot",
        )
        snapshot = _load_strict_bounded_json(
            snapshot_raw,
            label="fresh worker snapshot",
        )
        if snapshot_raw != _pretty_report_bytes(snapshot):
            raise ValueError("fresh worker snapshot bytes are not canonical")
        _validate_snapshot(
            snapshot,
            case_id=case_id,
            enabled=enabled,
            allow_unattached_diagnostics=True,
            allow_unattached_external_attestation=True,
        )
        worker_rss_record = {
            field: snapshot.get(field)
            for field in parent_rss_record
        }
        if (
            set(worker_rss_record) != set(parent_rss_record)
            or _canonical_bytes(worker_rss_record)
            != _canonical_bytes(parent_rss_record)
        ):
            raise ValueError(
                "fresh worker parent-monitor RSS custody differs"
            )
        snapshot["external_rss_monitor_attestation"] = (
            monitor_binding.attestation(snapshot, worker_rss_record)
        )
        snapshot["worker_diagnostics"] = diagnostics
        _validate_snapshot(snapshot, case_id=case_id, enabled=enabled)
        return snapshot


def generate_paired_metrics(
    workspace: Path = WORKSPACE,
    *,
    cases: Sequence[str] = PERFORMANCE_CASES,
    pair_count: int = PAIR_COUNT,
) -> dict[str, Any]:
    if pair_count != PAIR_COUNT:
        raise ValueError("P04-US01 metrics require exactly five isolated pairs")
    if tuple(cases) != PERFORMANCE_CASES:
        raise ValueError("P04-US01 performance cases differ from the reviewed plan")
    results: dict[str, Any] = {}
    for case_id in cases:
        off: list[dict[str, Any]] = []
        on: list[dict[str, Any]] = []
        for pair_index in range(pair_count):
            pair: dict[bool, dict[str, Any]] = {}
            for state in paired_states(pair_index):
                pair[state] = fresh_snapshot(workspace, case_id, state)
            off.append(pair[False])
            on.append(pair[True])
        results[case_id] = paired_performance_summary(case_id, off, on)
    return results


def generate_reviewed_quality_metrics(
    workspace: Path = WORKSPACE,
    *,
    reviewed_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one fresh enabled worker per source and merge frozen denominators."""

    snapshots = {
        case_id: fresh_snapshot(workspace, case_id, True)
        for case_id in QUALITY_CASES
    }
    return merge_isolated_quality(
        snapshots,
        reviewed_observations=reviewed_observations,
        workspace=workspace,
    )


def default_reviewed_observations(
    workspace: Path = WORKSPACE,
) -> dict[str, dict[str, Any]]:
    """Return the one independently source-reviewed, nonmechanical fact.

    The observation is not inferred by the parser.  Its evidence identity is
    the frozen source-review record used by the existing opt-in quality gate.
    """

    denominator_id = "finance-p2-wrapped-row"
    return {
        denominator_id: {
            "denominator_id": denominator_id,
            "observed": 1,
            "evidence_identity": file_identity(
                workspace,
                "tracker/benchmarks/llamaparse-15/cases/finance-10k.md",
            ),
        }
    }


def build_quality_evidence(
    snapshots: Mapping[str, Mapping[str, Any]],
    *,
    reviewed_observations: Mapping[str, Mapping[str, Any]] | None = None,
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    """Retain all six enabled worker snapshots and their recomputable merge."""

    if set(snapshots) != set(QUALITY_CASES):
        raise ValueError("quality evidence requires all six enabled cases")
    retained: dict[str, dict[str, Any]] = {}
    for case_id in QUALITY_CASES:
        snapshot = snapshots[case_id]
        _validate_snapshot(snapshot, case_id=case_id, enabled=True)
        _validate_worker_quality(
            snapshot.get("quality"),
            workspace,
            case_id=case_id,
        )
        retained[case_id] = deepcopy(dict(snapshot))
    reviewed = _validate_reviewed_observations(reviewed_observations, workspace)
    summary = merge_isolated_quality(
        retained,
        reviewed_observations=reviewed,
        workspace=workspace,
    )
    return {
        "schema_id": QUALITY_EVIDENCE_SCHEMA_ID,
        "enabled_case_order": list(QUALITY_CASES),
        "enabled_samples": retained,
        "reviewed_observations": reviewed,
        "summary": summary,
    }


def _validate_quality_partition(summary: Mapping[str, Any]) -> None:
    """Reject inserted, omitted, or relabelled frozen quality denominators."""

    expected = quality_denominator_manifest()
    if summary.get("oracle") != expected["oracle"]:
        raise ValueError("retained quality oracle identity differs")
    exact_fields = (
        "oracle_id",
        "case_id",
        "exact_cell_denominator",
        "representation_denominator",
    )
    denominator_fields = (
        "oracle_id",
        "case_id",
        "physical_page",
        "denominator_id",
        "dimension",
        "expected",
        "members",
        "accuracy_denominator_inclusion",
    )
    exclusion_fields = (
        "oracle_id",
        "case_id",
        "physical_page",
        "dimension",
        "required_concern",
        "accuracy_denominator_inclusion",
        "reason",
    )

    def projections(
        records: Any,
        fields: Sequence[str],
        label: str,
    ) -> list[bytes]:
        if type(records) is not list or any(
            type(record) is not dict for record in records
        ):
            raise ValueError(f"retained quality {label} records differ")
        return sorted(
            _canonical_bytes({field: record.get(field) for field in fields})
            for record in records
        )

    for field, projection_fields, label in (
        ("exact_tables", exact_fields, "exact-table"),
        ("reviewed_denominators", denominator_fields, "denominator"),
        ("unresolved_exclusions", exclusion_fields, "exclusion"),
    ):
        actual_projection = projections(
            summary.get(field), projection_fields, label
        )
        expected_projection = projections(
            expected[field], projection_fields, label
        )
        if actual_projection != expected_projection:
            raise ValueError(f"retained quality {label} partition differs")


def validate_quality_evidence(
    value: Mapping[str, Any],
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    """Recompute one retained quality record from its six raw snapshots."""

    expected_fields = {
        "schema_id",
        "enabled_case_order",
        "enabled_samples",
        "reviewed_observations",
        "summary",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError("retained quality evidence fields differ")
    if value.get("schema_id") != QUALITY_EVIDENCE_SCHEMA_ID:
        raise ValueError("retained quality evidence schema differs")
    if value.get("enabled_case_order") != list(QUALITY_CASES):
        raise ValueError("retained quality case order differs")
    snapshots = value.get("enabled_samples")
    reviewed = value.get("reviewed_observations")
    if type(snapshots) is not dict or type(reviewed) is not dict:
        raise ValueError("retained quality samples differ")
    rebuilt = build_quality_evidence(
        snapshots,
        reviewed_observations=reviewed,
        workspace=workspace,
    )
    _validate_quality_partition(rebuilt["summary"])
    try:
        evidence_matches = _canonical_bytes(value) == _canonical_bytes(rebuilt)
    except (TypeError, ValueError):
        evidence_matches = False
    if not evidence_matches:
        raise ValueError("retained quality evidence differs from raw samples")
    return deepcopy(dict(value))


def generate_reviewed_quality_evidence(
    workspace: Path = WORKSPACE,
    *,
    reviewed_observations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run and retain one fresh enabled worker for every reviewed case."""

    reviewed = (
        default_reviewed_observations(workspace)
        if reviewed_observations is None
        else reviewed_observations
    )
    snapshots = {
        case_id: fresh_snapshot(workspace, case_id, True)
        for case_id in QUALITY_CASES
    }
    return build_quality_evidence(
        snapshots,
        reviewed_observations=reviewed,
        workspace=workspace,
    )


def _probe_raw_table(index: int, *, page: int = 1) -> dict[str, Any]:
    return {
        "self_ref": f"#/tables/{index}",
        "label": "table",
        "prov": [
            {
                "page_no": page,
                "bbox": {
                    "l": 0.0,
                    "t": 20.0,
                    "r": 20.0,
                    "b": 0.0,
                    "coord_origin": "BOTTOMLEFT",
                },
            }
        ],
        "data": {
            "num_rows": 1,
            "num_cols": 1,
            "table_cells": [
                {
                    "start_row_offset_idx": 0,
                    "end_row_offset_idx": 1,
                    "start_col_offset_idx": 0,
                    "end_col_offset_idx": 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": f"table-{index}",
                    "column_header": True,
                    "row_header": False,
                    "row_section": False,
                    "ref": {"$ref": f"#/texts/table-{index}"},
                    "bbox": {
                        "l": 0.0,
                        "t": 0.0,
                        "r": 20.0,
                        "b": 20.0,
                        "coord_origin": "TOPLEFT",
                    },
                }
            ],
        },
    }


def _probe_raw_document(*tables: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "body": {
            "children": [{"$ref": table["self_ref"]} for table in tables]
        },
        "groups": [],
        "texts": [],
        "pictures": [],
        "tables": [deepcopy(dict(table)) for table in tables],
        "key_value_items": [],
        "form_items": [],
    }


def _deadline_probe_gates(value: Mapping[str, Any]) -> dict[str, bool]:
    page = value.get("same_page")
    document = value.get("document_wide")
    if type(page) is not dict or type(document) is not dict:
        return {
            "same_page_shared_deadline_passed": False,
            "document_wide_shared_deadline_passed": False,
        }
    final_items = page.get("final_items")
    final_rows = (
        [item.get("rows") for item in final_items]
        if type(final_items) is list
        and all(type(item) is dict for item in final_items)
        else None
    )
    markers_absent = (
        type(final_items) is list
        and all(
            type(item) is dict
            and "table_evidence" not in item
            and "_p04_predecessor_snapshot" not in item
            for item in final_items
        )
    )
    page_passed = (
        page.get("limit_seconds") == 0.5
        and page.get("observed_page_deadlines") == [100.5, 100.5]
        and page.get("observed_document_deadlines") == [105.0, 105.0]
        and page.get("enabled_table_refs") == ["#/tables/0", "#/tables/1"]
        and page.get("rollback_disabled_table_refs")
        == ["#/tables/0", "#/tables/1"]
        and page.get("simulated_elapsed_seconds") == 0.6
        and final_rows
        == [
            [["predecessor:#/tables/0"]],
            [["predecessor:#/tables/1"]],
        ]
        and markers_absent
    )
    document_passed = (
        document.get("limit_seconds") == 5.0
        and document.get("observed_deadlines") == [205.0, 205.0]
        and document.get("simulated_elapsed_seconds") == 6.0
        and document.get("final_pages")
        == [
            {
                "page_index": 1,
                "items": [{"type": "table", "rows": [["predecessor-1"]]}],
            },
            {
                "page_index": 2,
                "items": [{"type": "table", "rows": [["predecessor-2"]]}],
            },
        ]
    )
    return {
        "same_page_shared_deadline_passed": page_passed,
        "document_wide_shared_deadline_passed": document_passed,
    }


def generate_deadline_probes() -> dict[str, Any]:
    """Exercise the real shared-deadline callers with deterministic clocks."""

    from app.services import pipeline
    from app.services import table_semantics

    simulated_now = [100.0]
    page_deadlines: list[float] = []
    document_deadlines: list[float] = []
    enabled_refs: list[str] = []
    disabled_refs: list[str] = []
    original_page_deadline = table_semantics.table_span_fidelity_page_deadline
    original_table_item = pipeline._docling_table_item
    original_pipeline_clock = pipeline.time.perf_counter

    def fake_page_deadline(document_deadline: float | None = None) -> float:
        if document_deadline != 105.0:
            raise AssertionError("page probe document deadline differs")
        return simulated_now[0] + 0.5

    def fake_table_item(*args: Any, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        reference = args[0]["self_ref"]
        if kwargs.get("table_span_fidelity_enabled") is not True:
            disabled_refs.append(reference)
            return 1, {
                "type": "table",
                "rows": [[f"predecessor:{reference}"]],
            }
        enabled_refs.append(reference)
        deadline = kwargs.get("table_span_fidelity_deadline")
        document_deadline = kwargs.get("table_span_fidelity_document_deadline")
        if type(deadline) is not float or type(document_deadline) is not float:
            raise AssertionError("page probe deadline was not caller-owned")
        page_deadlines.append(deadline)
        document_deadlines.append(document_deadline)
        simulated_now[0] += 0.3
        if simulated_now[0] > deadline:
            raise TimeoutError("table operation deadline exceeded")
        return 1, {
            "type": "table",
            "rows": [[f"overlay:{reference}"]],
            "table_evidence": {"status": "partial"},
            "_p04_predecessor_snapshot": {
                "type": "table",
                "rows": [[f"predecessor:{reference}"]],
            },
        }

    try:
        table_semantics.table_span_fidelity_page_deadline = fake_page_deadline
        pipeline._docling_table_item = fake_table_item
        pipeline.time.perf_counter = lambda: simulated_now[0]
        _body, tables = pipeline._normalize_docling_body(
            _probe_raw_document(_probe_raw_table(0), _probe_raw_table(1)),
            {1: 100.0},
            ["table-0 table-1"],
            {},
            {},
            source_document_identity="a" * 64,
            table_span_fidelity_enabled=True,
            table_span_fidelity_document_deadline=105.0,
        )
    finally:
        table_semantics.table_span_fidelity_page_deadline = original_page_deadline
        pipeline._docling_table_item = original_table_item
        pipeline.time.perf_counter = original_pipeline_clock

    document_now = [200.0]
    observed_seal_deadlines: list[float] = []
    original_semantics_clock = table_semantics.perf_counter
    original_seal = table_semantics._seal_table_page_overlays

    def fake_seal_pages(
        pages: Any,
        _source_sha256: str,
        deadline: float,
        _retain_snapshot: bool,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        for page in pages:
            observed_seal_deadlines.append(deadline)
            page["items"][0]["rows"] = [["partially-mutated"]]
            document_now[0] += 3.0
            table_semantics._check_table_deadline(deadline)

    pages = [
        {
            "page_index": page_index,
            "items": [
                {
                    "type": "table",
                    "rows": [[f"overlay-{page_index}"]],
                    "table_evidence": {"status": "partial"},
                    "_p04_predecessor_snapshot": {
                        "type": "table",
                        "rows": [[f"predecessor-{page_index}"]],
                    },
                }
            ],
        }
        for page_index in (1, 2)
    ]
    try:
        table_semantics.perf_counter = lambda: document_now[0]
        table_semantics._seal_table_page_overlays = fake_seal_pages
        table_semantics.seal_table_pages(
            pages,
            "a" * 64,
            ["one", "two"],
            table_span_fidelity_enabled=True,
        )
    finally:
        table_semantics.perf_counter = original_semantics_clock
        table_semantics._seal_table_page_overlays = original_seal

    probe: dict[str, Any] = {
        "schema_id": DEADLINE_PROBE_SCHEMA_ID,
        "same_page": {
            "limit_seconds": 0.5,
            "observed_page_deadlines": page_deadlines,
            "observed_document_deadlines": document_deadlines,
            "enabled_table_refs": enabled_refs,
            "rollback_disabled_table_refs": disabled_refs,
            "simulated_elapsed_seconds": round(simulated_now[0] - 100.0, 9),
            "final_items": deepcopy(tables[1]),
        },
        "document_wide": {
            "limit_seconds": 5.0,
            "observed_deadlines": observed_seal_deadlines,
            "simulated_elapsed_seconds": round(document_now[0] - 200.0, 9),
            "final_pages": pages,
        },
    }
    probe["gates"] = _deadline_probe_gates(probe)
    return probe


def validate_deadline_probes(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_fields = {"schema_id", "same_page", "document_wide", "gates"}
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError("deadline probe fields differ")
    if value.get("schema_id") != DEADLINE_PROBE_SCHEMA_ID:
        raise ValueError("deadline probe schema differs")
    same_page = value.get("same_page")
    document = value.get("document_wide")
    if type(same_page) is not dict or set(same_page) != {
        "limit_seconds",
        "observed_page_deadlines",
        "observed_document_deadlines",
        "enabled_table_refs",
        "rollback_disabled_table_refs",
        "simulated_elapsed_seconds",
        "final_items",
    }:
        raise ValueError("same-page deadline probe fields differ")
    if type(document) is not dict or set(document) != {
        "limit_seconds",
        "observed_deadlines",
        "simulated_elapsed_seconds",
        "final_pages",
    }:
        raise ValueError("document deadline probe fields differ")
    gates = _deadline_probe_gates(value)
    if value.get("gates") != gates:
        raise ValueError("deadline probe gates differ from raw observations")
    return deepcopy(dict(value))


def _dense_probe_table(row_count: int, column_count: int) -> dict[str, Any]:
    table = _probe_raw_table(0)
    cells: list[dict[str, Any]] = []
    for row in range(row_count):
        for column in range(column_count):
            cells.append(
                {
                    "start_row_offset_idx": row,
                    "end_row_offset_idx": row + 1,
                    "start_col_offset_idx": column,
                    "end_col_offset_idx": column + 1,
                    "row_span": 1,
                    "col_span": 1,
                    "text": f"r{row}-c{column}",
                    "column_header": row == 0,
                    "row_header": False,
                    "row_section": False,
                    "ref": {"$ref": f"#/texts/r{row}-c{column}"},
                    "bbox": {
                        "l": float(column * 5),
                        "t": float(row * 3),
                        "r": float((column + 1) * 5),
                        "b": float((row + 1) * 3),
                        "coord_origin": "TOPLEFT",
                    },
                }
            )
    table["data"] = {
        "num_rows": row_count,
        "num_cols": column_count,
        "table_cells": cells,
    }
    table["prov"][0]["bbox"] = {
        "l": 0.0,
        "t": float(row_count * 3),
        "r": float(column_count * 5),
        "b": 0.0,
        "coord_origin": "BOTTOMLEFT",
    }
    return table


def _measure_dense_probe(row_count: int, column_count: int) -> dict[str, Any]:
    from app.services import pipeline
    from app.services import table_semantics

    raw = _dense_probe_table(row_count, column_count)
    text = " ".join(cell["text"] for cell in raw["data"]["table_cells"])
    elapsed: list[float] = []
    output_counts: list[int] = []
    semantic_digests: list[str] = []
    for _sample in range(3):
        started = table_semantics.perf_counter()
        _page, item = pipeline._docling_table_item(
            raw,
            {1: 1000.0},
            {},
            [text],
            "a" * 64,
            table_span_fidelity_enabled=True,
        )
        duration = table_semantics.perf_counter() - started
        elapsed.append(round(duration, 9))
        output_counts.append(len(item.get("cells", [])))
        semantic_digests.append(_sha256_bytes(_canonical_bytes(item)))
    return {
        "row_count": row_count,
        "column_count": column_count,
        "input_cell_count": row_count * column_count,
        "elapsed_seconds": elapsed,
        "p50_elapsed_seconds": inclusive_nearest_rank(elapsed, 0.5),
        "output_cell_counts": output_counts,
        "semantic_json_sha256": semantic_digests,
    }


def _dense_scaling_gate(cases: Sequence[Mapping[str, Any]]) -> bool:
    if len(cases) != 2:
        return False
    small, large = cases
    return (
        small.get("row_count") == 4
        and small.get("column_count") == 8
        and small.get("input_cell_count") == 32
        and small.get("output_cell_counts") == [32, 32, 32]
        and len(set(small.get("semantic_json_sha256", []))) == 1
        and large.get("row_count") == 8
        and large.get("column_count") == 16
        and large.get("input_cell_count") == 128
        and large.get("output_cell_counts") == [128, 128, 128]
        and len(set(large.get("semantic_json_sha256", []))) == 1
        and type(small.get("p50_elapsed_seconds")) in (int, float)
        and type(large.get("p50_elapsed_seconds")) in (int, float)
        and large["p50_elapsed_seconds"]
        <= small["p50_elapsed_seconds"] * 6.0 + 0.05
        and large["p50_elapsed_seconds"]
        <= TABLE_LIMITS["maximum_span_fidelity_page_seconds"]
    )


def generate_dense_scaling_probe() -> dict[str, Any]:
    cases = [_measure_dense_probe(4, 8), _measure_dense_probe(8, 16)]
    return {
        "schema_id": DENSE_SCALING_SCHEMA_ID,
        "sample_count_per_case": 3,
        "quantile_method": "empirical_inclusive_nearest_rank",
        "cases": cases,
        "maximum_growth_factor": 6.0,
        "fixed_slack_seconds": 0.05,
        "page_deadline_seconds": TABLE_LIMITS[
            "maximum_span_fidelity_page_seconds"
        ],
        "within_scaling_ceiling": _dense_scaling_gate(cases),
    }


def validate_dense_scaling_probe(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_id",
        "sample_count_per_case",
        "quantile_method",
        "cases",
        "maximum_growth_factor",
        "fixed_slack_seconds",
        "page_deadline_seconds",
        "within_scaling_ceiling",
    }:
        raise ValueError("dense-scaling probe fields differ")
    if (
        value.get("schema_id") != DENSE_SCALING_SCHEMA_ID
        or value.get("sample_count_per_case") != 3
        or value.get("quantile_method")
        != "empirical_inclusive_nearest_rank"
        or value.get("maximum_growth_factor") != 6.0
        or value.get("fixed_slack_seconds") != 0.05
        or value.get("page_deadline_seconds")
        != TABLE_LIMITS["maximum_span_fidelity_page_seconds"]
    ):
        raise ValueError("dense-scaling probe policy differs")
    cases = value.get("cases")
    if type(cases) is not list or len(cases) != 2:
        raise ValueError("dense-scaling probe cases differ")
    for record in cases:
        if type(record) is not dict or set(record) != {
            "row_count",
            "column_count",
            "input_cell_count",
            "elapsed_seconds",
            "p50_elapsed_seconds",
            "output_cell_counts",
            "semantic_json_sha256",
        }:
            raise ValueError("dense-scaling case fields differ")
        samples = record.get("elapsed_seconds")
        digests = record.get("semantic_json_sha256")
        if (
            type(samples) is not list
            or len(samples) != 3
            or any(
                type(sample) not in (int, float)
                or type(sample) is bool
                or not math.isfinite(float(sample))
                or sample <= 0
                for sample in samples
            )
            or record.get("p50_elapsed_seconds")
            != inclusive_nearest_rank(samples, 0.5)
            or type(digests) is not list
            or len(digests) != 3
            or any(
                type(digest) is not str
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                for digest in digests
            )
        ):
            raise ValueError("dense-scaling raw samples differ")
    expected_gate = _dense_scaling_gate(cases)
    if value.get("within_scaling_ceiling") is not expected_gate:
        raise ValueError("dense-scaling gate differs from raw samples")
    return deepcopy(dict(value))


def _execution_accounting(
    paired: Mapping[str, Mapping[str, Any]],
    quality: Mapping[str, Any],
) -> dict[str, Any]:
    expected_worker_count = (
        len(PERFORMANCE_CASES) * PAIR_COUNT * 2 + len(QUALITY_CASES)
    )
    retained: list[dict[str, Any]] = []

    def process_identity(
        value: Any,
        *,
        label: str,
    ) -> dict[str, int]:
        if (
            type(value) is not dict
            or type(value.get("pid")) is not int
            or value["pid"] < 1
            or type(value.get("process_create_time_ns")) is not int
            or value["process_create_time_ns"] < 1
        ):
            raise ValueError(
                f"retained metrics campaign {label} identity differs"
            )
        return {
            "pid": value["pid"],
            "process_create_time_ns": value["process_create_time_ns"],
        }

    def execution_identities(sample: Mapping[str, Any]) -> dict[str, Any]:
        worker = process_identity(
            {
                "pid": sample.get("phase04_stage_rss_worker_pid"),
                "process_create_time_ns": sample.get(
                    "phase04_stage_rss_process_create_time_ns"
                ),
            },
            label="fresh worker process",
        )
        attestation = sample.get("external_rss_monitor_attestation")
        if type(attestation) is not dict:
            raise ValueError(
                "retained metrics campaign external RSS attestation differs"
            )
        observer = process_identity(
            attestation.get("observer_process"),
            label="fresh outer observer process",
        )
        observer_runtime = attestation.get("observer_runtime")
        lane_custody = (
            observer_runtime.get("current_rss_lane")
            if type(observer_runtime) is dict
            else None
        )
        lane = process_identity(
            lane_custody.get("identity")
            if type(lane_custody) is dict
            else None,
            label="fresh current-RSS lane process",
        )
        return {
            "worker_process": worker,
            "outer_observer_process": observer,
            "current_rss_lane_process": lane,
        }

    def append_execution(
        *,
        execution_kind: str,
        case_id: str,
        enabled: bool,
        sample_index: int,
        sample: Mapping[str, Any],
    ) -> None:
        diagnostics = _validate_worker_diagnostics(
            sample.get("worker_diagnostics")
        )
        retained.append(
            {
                "execution_kind": execution_kind,
                "case_id": case_id,
                "enabled": enabled,
                "sample_index": sample_index,
                "process_identities": execution_identities(sample),
                "worker_diagnostics": diagnostics,
            }
        )

    for case_id in PERFORMANCE_CASES:
        record = paired.get(case_id)
        if type(record) is not dict:
            continue
        for enabled, field in (
            (False, "flag_off_samples"),
            (True, "flag_on_samples"),
        ):
            samples = record.get(field)
            if type(samples) is not list:
                continue
            for sample_index, sample in enumerate(samples):
                if type(sample) is not dict:
                    continue
                append_execution(
                    execution_kind="paired_performance",
                    case_id=case_id,
                    enabled=enabled,
                    sample_index=sample_index,
                    sample=sample,
                )
    enabled_samples = (
        quality.get("enabled_samples")
        if quality.get("schema_id") == QUALITY_EVIDENCE_SCHEMA_ID
        else None
    )
    if type(enabled_samples) is dict:
        for case_id in QUALITY_CASES:
            sample = enabled_samples.get(case_id)
            if type(sample) is not dict:
                continue
            append_execution(
                execution_kind="enabled_quality",
                case_id=case_id,
                enabled=True,
                sample_index=0,
                sample=sample,
            )
    warnings = 0
    phase04_warnings = 0
    unexpected = 0
    informational = 0
    progress = 0
    stdout_bytes = 0
    stderr_bytes = 0
    for execution in retained:
        diagnostics = execution["worker_diagnostics"]
        stdout_bytes += diagnostics["stdout"]["size_bytes"]
        stderr_bytes += diagnostics["stderr"]["size_bytes"]
        for stream_name in ("stdout", "stderr"):
            classifications = diagnostics[stream_name]["classifications"]
            warnings += classifications["warning"]
            phase04_warnings += classifications["phase04_warning"]
            unexpected += classifications["unexpected"]
            informational += classifications["informational"]
            progress += classifications["progress"]
    retained_count = len(retained)
    identity_records = [
        {
            field: execution[field]
            for field in (
                "execution_kind",
                "case_id",
                "enabled",
                "sample_index",
                "process_identities",
            )
        }
        for execution in retained
    ]
    identity_counts: dict[str, int] = {}
    for field, label in (
        ("worker_process", "worker"),
        ("outer_observer_process", "outer observer"),
        ("current_rss_lane_process", "current-RSS lane"),
    ):
        identities = [
            (
                execution["process_identities"][field]["pid"],
                execution["process_identities"][field][
                    "process_create_time_ns"
                ],
            )
            for execution in retained
        ]
        unique_count = len(set(identities))
        identity_counts[field] = unique_count
        if unique_count != retained_count:
            raise ValueError(
                "retained metrics campaign requires distinct fresh "
                f"{label} processes across every execution"
            )
    global_identity_records = []
    global_identities: list[tuple[int, int]] = []
    for execution in retained:
        for role in (
            "worker_process",
            "outer_observer_process",
            "current_rss_lane_process",
        ):
            identity = execution["process_identities"][role]
            global_identities.append(
                (identity["pid"], identity["process_create_time_ns"])
            )
            global_identity_records.append(
                {
                    "execution_kind": execution["execution_kind"],
                    "case_id": execution["case_id"],
                    "enabled": execution["enabled"],
                    "sample_index": execution["sample_index"],
                    "role": role,
                    "pid": identity["pid"],
                    "process_create_time_ns": identity[
                        "process_create_time_ns"
                    ],
                }
            )
    global_unique_count = len(set(global_identities))
    expected_global_count = 3 * retained_count
    if global_unique_count != expected_global_count:
        raise ValueError(
            "retained metrics campaign requires globally distinct fresh "
            "process identities across every role and execution"
        )
    skipped = max(expected_worker_count - retained_count, 0)
    return {
        "schema_id": EXECUTION_ACCOUNTING_SCHEMA_ID,
        "expected_worker_count": expected_worker_count,
        "retained_worker_count": retained_count,
        "skipped_worker_count": skipped,
        "unexpected_extra_worker_count": max(
            retained_count - expected_worker_count,
            0,
        ),
        "warning_line_count": warnings,
        "phase04_warning_line_count": phase04_warnings,
        "unexpected_line_count": unexpected,
        "informational_line_count": informational,
        "progress_line_count": progress,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "fresh_worker_process_count": identity_counts["worker_process"],
        "fresh_outer_observer_process_count": identity_counts[
            "outer_observer_process"
        ],
        "fresh_current_rss_lane_process_count": identity_counts[
            "current_rss_lane_process"
        ],
        "expected_global_process_identity_count": expected_global_count,
        "fresh_global_process_identity_count": global_unique_count,
        "global_process_identities_distinct": (
            global_unique_count == expected_global_count
        ),
        "fresh_process_counts_match_retained_worker_count": all(
            count == retained_count for count in identity_counts.values()
        ),
        "fresh_process_counts_match_expected_worker_count": (
            retained_count == expected_worker_count
            and all(
                count == expected_worker_count
                for count in identity_counts.values()
            )
        ),
        "process_identity_manifest_sha256": _sha256_bytes(
            _canonical_bytes(identity_records)
        ),
        "global_process_identity_manifest_sha256": _sha256_bytes(
            _canonical_bytes(global_identity_records)
        ),
        "diagnostic_manifest_sha256": _sha256_bytes(
            _canonical_bytes(
                [
                    {
                        field: execution[field]
                        for field in (
                            "execution_kind",
                            "case_id",
                            "enabled",
                            "sample_index",
                            "worker_diagnostics",
                        )
                    }
                    for execution in retained
                ]
            )
        ),
    }


def _measurement_policy(required_paths: Sequence[str]) -> dict[str, Any]:
    return {
        "scope": (
            "named_non_overlapping_phase04_hooks_inside_paired_full_local_parser"
        ),
        "table_stage_components": list(TABLE_STAGE_COMPONENTS),
        "table_stage_always_reachable_components": list(
            TABLE_STAGE_ALWAYS_REACHABLE_COMPONENTS
        ),
        "table_stage_required_when_enabled_components": list(
            TABLE_STAGE_REQUIRED_WHEN_ENABLED_COMPONENTS
        ),
        "table_stage_conditional_when_enabled_components": list(
            TABLE_STAGE_CONDITIONAL_WHEN_ENABLED_COMPONENTS
        ),
        "table_stage_completeness_claimed": False,
        "unmeasured_work_guard": (
            "paired_whole_parser_p50_and_p95_overhead_at_same_10_percent_ceiling"
        ),
        "paired_performance_schema_id": PAIRED_PERFORMANCE_SCHEMA_ID,
        "table_stage_overhead_formula_id": TABLE_STAGE_OVERHEAD_FORMULA_ID,
        "phase04_stage_peak_rss_increment_formula_id": (
            PHASE04_STAGE_PEAK_RSS_INCREMENT_FORMULA_ID
        ),
        "paired_phase04_stage_peak_rss_delta_formula_id": (
            PAIRED_PHASE04_STAGE_PEAK_RSS_DELTA_FORMULA_ID
        ),
        "overhead_numerator": (
            "paired_nonnegative_enabled_minus_disabled_named_stage_union_seconds"
        ),
        "overhead_denominator": "paired_flag_off_whole_parser_wall_seconds",
        "whole_parser_latency_reported_separately": True,
        "pair_count": PAIR_COUNT,
        "performance_cases": list(PERFORMANCE_CASES),
        "quality_cases": list(QUALITY_CASES),
        "required_final_code_paths": list(required_paths),
        "required_final_code_patterns": list(_REQUIRED_FINAL_CODE_PATTERNS),
        "downstream_evidence_patterns_excluded": list(
            _DOWNSTREAM_EVIDENCE_PATTERNS
        ),
        "upstream_approval_evidence_paths": list(
            UPSTREAM_APPROVAL_EVIDENCE_PATHS
        ),
        "downstream_evidence_manifest_path": DOWNSTREAM_EVIDENCE_MANIFEST_PATH,
        "retained_metrics_path": FINAL_METRICS_RELATIVE_PATH,
        "downstream_evidence_sealed_separately": True,
        "mutable_terminal_status_owner_paths_excluded": list(
            MUTABLE_TERMINAL_STATUS_OWNER_PATHS
        ),
        "mutable_status_owner_custody": (
            "fixed_phase03_terminal_chain_exact_identity"
        ),
        "clock": "time.perf_counter_ns",
        "rss_clock": "time.monotonic_ns",
        "process_isolation": "fresh_process_per_state_per_pair",
        "execution_order": "alternating_off_on_then_on_off",
        "external_rss_monitor_wire_schema_id": EXTERNAL_RSS_MONITOR_SCHEMA_ID,
        "external_rss_observer_process_schema_id": (
            EXTERNAL_RSS_OBSERVER_SCHEMA_ID
        ),
        "external_rss_worker_frame_maximum_bytes": (
            EXTERNAL_RSS_MONITOR_MAXIMUM_FRAME_BYTES
        ),
        "external_rss_observer_frame_maximum_bytes": (
            EXTERNAL_RSS_OBSERVER_MAXIMUM_FRAME_BYTES
        ),
        "external_rss_observer_diagnostic_capture_mode": (
            "kernel_pipes_bounded_backpressure_read_after_reap"
        ),
        "current_rss_lane_wire_schema_id": rss_lane.SCHEMA_ID,
        "current_rss_lane_frame_maximum_bytes": rss_lane.MAXIMUM_FRAME_BYTES,
        "current_rss_lane_protocol_custody_schema_id": (
            rss_lane.PROTOCOL_CUSTODY_SCHEMA_ID
        ),
        "current_rss_lane_protocol_maximum_exchange_count": (
            rss_lane.MAXIMUM_EXCHANGES
        ),
        "current_rss_lane_protocol_maximum_duplex_bytes": (
            rss_lane.MAXIMUM_DUPLEX_BYTES
        ),
        "current_rss_lane_protocol_maximum_compressed_duplex_bytes": (
            rss_lane.MAXIMUM_COMPRESSED_DUPLEX_BYTES
        ),
        "current_rss_lane_terminal_exchange_raw_reservation_bytes": (
            rss_lane.TERMINAL_EXCHANGE_RAW_RESERVATION_BYTES
        ),
        "current_rss_lane_terminal_exchange_compressed_reservation_bytes": (
            rss_lane.TERMINAL_EXCHANGE_COMPRESSED_RESERVATION_BYTES
        ),
        "current_rss_lane_transcript_budget_policy": (
            "incremental_canonical_list_with_brackets_and_commas;_"
            "zlib_compressobj_copy_trial_and_exact_terminal_close;_"
            "nonterminal_fixed_worst_case_terminal_reserve;_"
            "commit_only_after_successful_transport"
        ),
        "current_rss_lane_protocol_maximum_nesting_depth": (
            rss_lane.MAXIMUM_TRANSCRIPT_NESTING_DEPTH
        ),
        "current_rss_lane_protocol_maximum_structural_tokens": (
            rss_lane.MAXIMUM_TRANSCRIPT_STRUCTURAL_TOKENS
        ),
        "current_rss_lane_protocol_compression": rss_lane.DUPLEX_COMPRESSION,
        "current_rss_lane_summary_schema_id": rss_lane.SUMMARY_SCHEMA_ID,
        "current_rss_lane_compact_summary_schema_id": (
            rss_lane.COMPACT_SUMMARY_SCHEMA_ID
        ),
        "current_rss_lane_runtime_schema_id": rss_lane.RUNTIME_SCHEMA_ID,
        "current_rss_lane_failure_schema_id": rss_lane.FAILURE_SCHEMA_ID,
        "current_rss_lane_qualification_schema_id": (
            rss_lane.QUALIFICATION_SCHEMA_ID
        ),
        "current_rss_lane_qualification_runtime_commitment_schema_id": (
            rss_lane.QUALIFICATION_RUNTIME_COMMITMENT_SCHEMA_ID
        ),
        "current_rss_lane_cadence_timing_schema_id": (
            rss_lane.CADENCE_TIMING_SCHEMA_ID
        ),
        "current_rss_lane_cadence_ring_entry_schema_id": (
            rss_lane.CADENCE_RING_ENTRY_SCHEMA_ID
        ),
        "current_rss_lane_qualification_duration_ns": (
            rss_lane.QUALIFICATION_DURATION_NS
        ),
        "current_rss_lane_qualification_operation_timeout_seconds": (
            rss_lane.QUALIFICATION_OPERATION_TIMEOUT_SECONDS
        ),
        "current_rss_lane_qualification_finalizer_deadline_seconds": (
            rss_lane.QUALIFICATION_FAILURE_FINALIZER_DEADLINE_SECONDS
        ),
        "current_rss_lane_qualification_response_ready_deadline_seconds": (
            rss_lane.QUALIFICATION_RESPONSE_READY_DEADLINE_SECONDS
        ),
        "current_rss_lane_qualification_response_timeout_seconds": (
            rss_lane.QUALIFICATION_RESPONSE_TIMEOUT_SECONDS
        ),
        "current_rss_lane_qualification_attempt_failure_codes": list(
            rss_lane.QUALIFICATION_ATTEMPT_FAILURE_CODES
        ),
        "current_rss_lane_qualification_finalization_failure_code": (
            rss_lane.QUALIFICATION_FINALIZATION_FAILURE_CODE
        ),
        "external_rss_qualification_round_trip_timeout_seconds": (
            EXTERNAL_RSS_OBSERVER_QUALIFICATION_TIMEOUT_SECONDS
        ),
        "current_rss_lane_cadence_timing_ring_capacity": (
            rss_lane.CADENCE_TIMING_RING_CAPACITY
        ),
        "worker_lifetime_lease_schema_id": WORKER_LIFETIME_LEASE_SCHEMA_ID,
        "worker_lifetime_lease_sigchld_policy": "safe_default_SIG_DFL_only",
        "worker_lifetime_lease_forbidden_operations": list(
            WORKER_LIFETIME_LEASE_FORBIDDEN_OPERATIONS
        ),
        "current_rss_lane_active_cpu_fixed_slack_ns": (
            rss_lane.ACTIVE_CPU_FIXED_SLACK_NS
        ),
        "current_rss_lane_active_cpu_steady_state_maximum_duty_ppm": (
            rss_lane.ACTIVE_CPU_STEADY_STATE_MAXIMUM_DUTY_PPM
        ),
        "current_rss_lane_lifecycle_schema_id": rss_lane.LIFECYCLE_SCHEMA_ID,
        "external_rss_monitor_attestation_schema_id": (
            EXTERNAL_RSS_MONITOR_ATTESTATION_SCHEMA_ID
        ),
        "execution_accounting_schema_id": EXECUTION_ACCOUNTING_SCHEMA_ID,
        "expected_campaign_execution_count": (
            len(PERFORMANCE_CASES) * PAIR_COUNT * 2 + len(QUALITY_CASES)
        ),
        "expected_campaign_global_process_identity_count": 3
        * (len(PERFORMANCE_CASES) * PAIR_COUNT * 2 + len(QUALITY_CASES)),
        "campaign_process_identity_policy": (
            "worker_observer_and_lane_pid_create_time_pairs_globally_"
            "distinct_across_every_role_and_execution"
        ),
        "external_rss_monitor_framing": EXTERNAL_RSS_MONITOR_FRAMING,
        "external_rss_monitor_scheduler_scope": (
            EXTERNAL_RSS_MONITOR_SCHEDULER_SCOPE
        ),
        "external_rss_monitor_gc_scope": EXTERNAL_RSS_MONITOR_GC_SCOPE,
        "external_rss_observer_runtime_scope": (
            EXTERNAL_RSS_OBSERVER_RUNTIME_SCOPE
        ),
        "external_rss_observer_thread_qos_policy": (
            PHASE04_STAGE_THREAD_QOS_POLICY
        ),
        "rss_monitor_owner": (
            "dedicated_controller_owned_observer_process_bound_to_exact_"
            "worker_pid_create_time_and_owned_process_group_with_nested_"
            "single_thread_current_rss_lane_and_observer_both_quiesced_"
            "before_any_worker_release_or_reap"
        ),
        "rss_monitor_allocation_scope": (
            "controller_recursive_child_observer_allocations_are_outside_"
            "worker_G_in_a_dedicated_observer_process;_current_rss_timed_"
            "select_deadline_allocations_are_outside_worker_G_in_a_nested_"
            "dedicated_single_thread_process;_neither_is_subtracted_or_"
            "claimed_as_worker_RSS"
        ),
        "rss_worker_proxy_allocation_scope": (
            "proxy_executes_only_in_worker_with_zero_manual_resource_credit;_"
            "pre_t0_work_can_affect_inherited_B_H0;_intermediate_boundary_"
            "IPC_and_production_output_are_inside_G;_finish_response_decode_"
            "and_close_are_post_t1"
        ),
        "rss_parent_worker_record_comparison": (
            "exact_round_trip_custody_match_not_independent_duplicate_"
            "measurement"
        ),
        "rss_semantics": (
            "worker_G=max(G_parse,G_api)_where_each_G=max(C,Q),_"
            "C=max(0,current_peak_P-current_baseline_B),_"
            "Q=max(0,hwm_end_H1-hwm_baseline_H0);_"
            "paired_D=max(0,G_on-G_off);_gate=max_five_D"
        ),
        "rss_current_source": PHASE04_STAGE_CURRENT_RSS_SOURCE,
        "rss_current_source_version": _current_rss_source_version(),
        "rss_hwm_source": PHASE04_STAGE_RSS_SOURCE,
        "rss_normalization": PHASE04_STAGE_RSS_NORMALIZATION,
        "rss_sampling_scope": PHASE04_STAGE_RSS_SAMPLING_SCOPE,
        "rss_sampling_boundaries": (
            "continuous_plus_every_outermost_hook_entry_exit_plus_parse_return_"
            "plus_exact_output_boundaries_plus_terminal_api_output_sample"
        ),
        "rss_instrumentation_restoration": (
            "after_parse_wall_clock_and_parse_checkpoint_but_conservatively_"
            "inside_G_before_production_output_materialization"
        ),
        "rss_production_output_path": PHASE04_STAGE_OUTPUT_PATH,
        "rss_output_boundary_names": list(PHASE04_STAGE_OUTPUT_BOUNDARIES),
        "rss_in_window_diagnostic_overhead": (
            "one_released_parsed_result_model_dump_identity_plus_bounded_"
            "streaming_json_identities_and_sha256_of_existing_json_body;_"
            "all_listed_worker_in_window_overhead_is_included_and_never_"
            "subtracted;_controller_monitor_allocations_are_out_of_process;_"
            "decode_replay_and_markdown_parity_run_strictly_after_t1"
        ),
        "rss_sampler_noop_overhead_evidence": (
            "synthetic_inclusion_arithmetic_only_no_empirical_bound_and_"
            "subtraction_bytes_equal_zero"
        ),
        "rss_non_real_allocation_probe_design": (
            "isolated_fresh_subprocess_short_lived_and_sustained_16MiB_"
            "page_touched;_minimum_observed_growth_8MiB;_maximum_64MiB;_"
            "no_child_adapter_for_portable_current_rss_hwm_sensitivity_only;_"
            "does_not_exercise_recursive_child_polling;_defense_in_depth_"
            "only_not_canonical_3x5_evidence"
        ),
        "rss_production_child_polling_permission_policy": (
            "real_recursive_psutil_inspection_required_in_controller_owned_"
            "observer_process_targeting_campaign_workers;_permission_failure_"
            "is_fail_closed_and_never_bypassed"
        ),
        "rss_continuous_gap_formula": (
            "max(t0_to_first_async,consecutive_async_gaps,last_async_to_t1);_"
            "synchronous_samples_do_not_subdivide_cadence"
        ),
        "rss_sampling_target_interval_ns": PHASE04_STAGE_RSS_TARGET_INTERVAL_NS,
        "rss_sampling_hard_maximum_gap_ns": (
            PHASE04_STAGE_RSS_HARD_MAXIMUM_GAP_NS
        ),
        "rss_child_observer_source": PHASE04_STAGE_CHILD_OBSERVER_SOURCE,
        "rss_child_observer_source_version": (
            PHASE04_STAGE_CHILD_OBSERVER_SOURCE_VERSION
        ),
        "rss_child_observer_gap_formula": (
            "max(t0_to_first_child_observation,consecutive_child_observation_"
            "gaps,last_child_observation_to_t1);_bracketed_boundary_checks_do_"
            "not_subdivide_observer_cadence"
        ),
        "rss_child_observer_target_interval_ns": (
            PHASE04_STAGE_CHILD_OBSERVER_TARGET_INTERVAL_NS
        ),
        "rss_child_observer_hard_maximum_gap_ns": (
            PHASE04_STAGE_CHILD_OBSERVER_HARD_MAXIMUM_GAP_NS
        ),
        "rss_child_observer_residual": PHASE04_STAGE_CHILD_OBSERVER_RESIDUAL,
        "rss_child_scope": PHASE04_STAGE_RSS_CHILD_SCOPE,
        "rss_children_hwm_source": PHASE04_STAGE_CHILDREN_HWM_SOURCE,
        "rss_children_rusage_source": PHASE04_STAGE_CHILDREN_RUSAGE_SOURCE,
        "rss_children_rusage_schema_id": (
            PHASE04_STAGE_CHILDREN_RUSAGE_SCHEMA_ID
        ),
        "rss_children_rusage_policy": (
            "exact_full_platform_fingerprint_t0_equals_t1;_inherited_pre_t0_"
            "activity_allowed;_not_event_perfect_process_observation"
        ),
        "rss_no_spawn_scope": (
            "exact_manifest_bound_p04_owned_app_paths_only_not_transitive_"
            "dependency_closure"
        ),
        "rss_no_spawn_policy": deepcopy(_current_phase04_no_spawn_policy()),
        "rss_sampler_anomaly_policy": "fail_closed",
        "absolute_peak_rss_deltas": "retained_observational_only_not_gated",
        "p50_p95_semantics": (
            "empirical_inclusive_nearest_rank_of_paired_nonnegative_"
            "table_stage_additive_overhead_ratio"
        ),
        "changed_settings": ["table_span_fidelity_enabled"],
        "offline_environment": dict(OFFLINE_ENVIRONMENT),
    }


def build_metrics_report(
    paired: Mapping[str, Mapping[str, Any]],
    quality: Mapping[str, Any],
    deadline_probes: Mapping[str, Any],
    dense_scaling: Mapping[str, Any],
    *,
    final_code_identities: Sequence[Mapping[str, Any]] = (),
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    required_paths = required_final_code_paths(workspace)
    identities = [validate_file_identity(value) for value in final_code_identities]
    if len({record["path"] for record in identities}) != len(identities):
        raise ValueError("final-code identity paths must be unique")
    for identity in identities:
        if file_identity(workspace, identity["path"]) != identity:
            raise ValueError("final-code identity differs from current workspace bytes")
    identity_paths = {record["path"] for record in identities}
    if identities and identity_paths != set(required_paths):
        missing = sorted(set(required_paths) - identity_paths)
        unexpected = sorted(identity_paths - set(required_paths))
        if missing:
            raise ValueError("final-code identity manifest omits required US01 paths")
        raise ValueError(
            "final-code identity manifest includes downstream or unexpected paths: "
            f"{unexpected}"
        )
    identities.sort(key=lambda record: record["path"])
    evidence_state = "final_code_bound" if identities else "pending_final_code"
    final_code_identity_aggregate_sha256 = _sha256_bytes(
        _canonical_bytes(identities)
    )
    performance_complete = set(paired) == set(PERFORMANCE_CASES)
    performance_first_rss_boundaries = {
        field: {
            sample.get("phase04_stage_rss_first_boundary_component")
            for record in paired.values()
            if type(record) is dict
            for sample in record.get(field, [])
            if type(sample) is dict
        }
        for field in ("flag_off_samples", "flag_on_samples")
    }
    if performance_complete and performance_first_rss_boundaries != {
        "flag_off_samples": {"repair_extraction"},
        "flag_on_samples": {"budget_start"},
    }:
        raise ValueError("performance RSS first-boundary consistency differs")
    named_stage_latency_passed = performance_complete and all(
        record.get("within_p50_overhead_ratio_ceiling") is True
        and record.get("within_p95_overhead_ratio_ceiling") is True
        for record in paired.values()
    )
    whole_parser_latency_passed = performance_complete and all(
        record.get("within_whole_parser_p50_overhead_ratio_ceiling") is True
        and record.get("within_whole_parser_p95_overhead_ratio_ceiling") is True
        for record in paired.values()
    )
    latency_passed = named_stage_latency_passed and whole_parser_latency_passed
    rss_passed = performance_complete and all(
        record.get(
            "within_phase04_stage_peak_rss_increment_delta_ceiling"
        )
        is True
        for record in paired.values()
    )
    output_passed = performance_complete and all(
        record.get("within_marked_table_output_ceiling") is True
        and record.get("within_document_sidecar_output_ceiling") is True
        and record.get("all_flag_off_markers_absent") is True
        and record.get("all_flag_on_marked_tables_present") is True
        for record in paired.values()
    )
    determinism_passed = performance_complete and all(
        record.get("flag_off_semantic_deterministic") is True
        and record.get("flag_on_semantic_deterministic") is True
        for record in paired.values()
    )
    quality_summary = (
        quality.get("summary", {})
        if quality.get("schema_id") == QUALITY_EVIDENCE_SCHEMA_ID
        else quality
    )
    if deadline_probes:
        validated_deadlines = validate_deadline_probes(deadline_probes)
        deadline_gates = validated_deadlines["gates"]
    else:
        validated_deadlines = {}
        deadline_gates = {}
    if dense_scaling:
        validated_dense = validate_dense_scaling_probe(dense_scaling)
    else:
        validated_dense = {}
    execution_accounting = _execution_accounting(paired, quality)
    warning_count = (
        execution_accounting["warning_line_count"]
        + execution_accounting["phase04_warning_line_count"]
    )
    skip_count = execution_accounting["skipped_worker_count"]
    diagnostics_clean = (
        warning_count == 0
        and execution_accounting["unexpected_line_count"] == 0
        and execution_accounting["unexpected_extra_worker_count"] == 0
    )
    retention: dict[str, Any] = {
        "state": "preapproval",
        "terminal_approval_expected": True,
        "binding_basis": TERMINAL_APPROVAL_BINDING,
    }
    gates = {
        "paired_latency_passed": latency_passed,
        "paired_named_stage_latency_passed": named_stage_latency_passed,
        "paired_whole_parser_latency_passed": whole_parser_latency_passed,
        "paired_peak_rss_passed": rss_passed,
        "output_bounds_passed": output_passed,
        "semantic_determinism_passed": determinism_passed,
        "quality_passed": quality_summary.get(
            "all_exact_and_reviewed_dimensions_passed"
        )
        is True,
        "page_deadline_passed": deadline_gates.get(
            "same_page_shared_deadline_passed"
        )
        is True,
        "document_deadline_passed": deadline_gates.get(
            "document_wide_shared_deadline_passed"
        )
        is True,
        "dense_scaling_passed": validated_dense.get(
            "within_scaling_ceiling"
        )
        is True,
        "final_code_bound": evidence_state == "final_code_bound",
        "worker_diagnostics_passed": diagnostics_clean,
        "warnings_zero": warning_count == 0,
        "skips_zero": skip_count == 0,
        "hosted_use_zero": True,
        "terminal_approval_bound": False,
    }
    measurement_gate_names = tuple(
        name for name in gates if name != "terminal_approval_bound"
    )
    gates["all_measurement_gates_passed"] = all(
        gates[name] for name in measurement_gate_names
    )
    gates["all_passed"] = False
    report: dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "story_id": STORY_ID,
        "artifact_path": FINAL_METRICS_RELATIVE_PATH,
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_state": evidence_state,
        "final_code_identities": identities,
        "final_code_identity_aggregate_sha256": (
            final_code_identity_aggregate_sha256
        ),
        "measurement_policy": _measurement_policy(required_paths),
        "limits": dict(TABLE_LIMITS),
        "paired_performance": dict(paired),
        "quality": dict(quality),
        "deadline_probes": validated_deadlines,
        "dense_scaling": validated_dense,
        "execution_accounting": execution_accounting,
        "warnings": warning_count,
        "skips": skip_count,
        "hosted_usage": dict(HOSTED_USAGE),
        "retention": retention,
        "gates": gates,
    }
    report["semantic_identity"] = _build_report_semantic_identity(report)
    return report


def _report_semantic_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the approval-safe projection whose digest survives final binding.

    Timestamp and approval-envelope bytes are intentionally excluded.  The two
    approval-dependent gates are normalized out as well, so a terminal review
    can cite this digest before its own file identity is added without a hash
    cycle.  All measurements, raw samples, limits, code identities, and
    non-approval gates remain inside the projection.
    """

    projected = deepcopy(dict(value))
    projected.pop("generated_at", None)
    projected.pop("semantic_identity", None)
    projected.pop("retention", None)
    gates = projected.get("gates")
    if type(gates) is dict:
        gates.pop("terminal_approval_bound", None)
        gates.pop("all_passed", None)
    return projected


def _build_report_semantic_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    projection = _report_semantic_projection(value)
    return {
        "algorithm": "sha256",
        "projection_id": REPORT_SEMANTIC_PROJECTION_ID,
        "excluded_top_level_fields": [
            "generated_at",
            "retention",
            "semantic_identity",
        ],
        "excluded_approval_gate_fields": [
            "terminal_approval_bound",
            "all_passed",
        ],
        "sha256": _sha256_bytes(_canonical_bytes(projection)),
    }


def _phase03_exception_guard() -> Any:
    """Import the guard lazily; it imports this module for US01 gate custody."""

    import importlib

    canonical_name = "tests.fixtures.phase_04.tables.metrics"
    current = sys.modules.get(__name__)
    if current is None:
        raise ValueError("Phase03 exception guard metrics module is unavailable")
    canonical = sys.modules.get(canonical_name)
    if canonical is None:
        # ``python -m`` executes this file as ``__main__``.  Install the
        # already-running object under its import name before the guard's
        # reciprocal import so it cannot create a second metrics module.
        sys.modules[canonical_name] = current
    elif canonical is not current:
        raise ValueError("Phase03 exception guard metrics binding differs")
    guard = importlib.import_module(
        "tests.fixtures.phase_03.running_regions.performance_exception"
    )
    if getattr(guard, "table_metrics", None) is not current:
        raise ValueError("Phase03 exception guard metrics binding differs")
    return guard


def fixed_terminal_approval_path() -> str:
    guard = _phase03_exception_guard()
    return str(guard.SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH)


def _pretty_report_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def build_preapproval_execution_binding(
    preapproval_report: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        type(preapproval_report) is not dict
        or type(preapproval_report.get("retention")) is not dict
        or preapproval_report["retention"].get("state") != "preapproval"
    ):
        raise ValueError("preapproval execution binding requires preapproval metrics")
    raw = _pretty_report_bytes(preapproval_report)
    return {
        "schema_id": PREAPPROVAL_EXECUTION_BINDING_SCHEMA_ID,
        "story_id": STORY_ID,
        "downstream_artifact_path": FINAL_METRICS_RELATIVE_PATH,
        "downstream_artifact_in_story_gate": False,
        "preapproval_report_size_bytes": len(raw),
        "preapproval_report_sha256": _sha256_bytes(raw),
        "report_semantic_identity": deepcopy(
            preapproval_report["semantic_identity"]
        ),
        "final_code_identity_aggregate_sha256": preapproval_report[
            "final_code_identity_aggregate_sha256"
        ],
        "execution_accounting": deepcopy(
            preapproval_report["execution_accounting"]
        ),
        "measurement_gates": {
            key: member
            for key, member in preapproval_report["gates"].items()
            if key not in {"terminal_approval_bound", "all_passed"}
        },
    }


def _preapproval_report_from_terminal(value: Mapping[str, Any]) -> dict[str, Any]:
    preapproval = deepcopy(dict(value))
    preapproval["retention"] = {
        "state": "preapproval",
        "terminal_approval_expected": True,
        "binding_basis": TERMINAL_APPROVAL_BINDING,
    }
    preapproval["gates"]["terminal_approval_bound"] = False
    preapproval["gates"]["all_passed"] = False
    return preapproval


def _json_contains_text(value: Any, target: str) -> bool:
    stack = [value]
    while stack:
        current = stack.pop()
        if type(current) is str and target in current:
            return True
        if type(current) is dict:
            if any(target in key for key in current):
                return True
            stack.extend(current.values())
        elif type(current) is list:
            stack.extend(current)
    return False


def _validate_fixed_terminal_chain(
    preapproval_report: Mapping[str, Any],
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    """Validate P03's full chain and its exact compact metrics execution leaf."""

    guard = _phase03_exception_guard()
    fixed_approval_path = str(
        guard.SEMANTIC_ISOLATION_PHASE04_TERMINAL_APPROVAL_PATH
    )
    story_gate_path = str(guard.SEMANTIC_ISOLATION_PHASE04_US01_STORY_GATE_PATH)
    preapproval_root = str(
        guard.SEMANTIC_ISOLATION_PHASE04_US01_PREAPPROVAL_EVIDENCE_ROOT
    )
    guard.validate_performance_exception(
        workspace,
        today=datetime.now(tz=UTC).date(),
    )
    gate_raw = _read_bounded_regular_file(
        workspace,
        story_gate_path,
        maximum_bytes=64 * 1024,
        label="fixed P04-US01 story gate",
    )
    story_gate = _load_strict_bounded_json(
        gate_raw,
        label="fixed P04-US01 story gate",
    )
    if gate_raw != _pretty_report_bytes(story_gate):
        raise ValueError("fixed P04-US01 story gate bytes differ")
    gate_inputs = (
        (story_gate.get("environment") or {}).get("us01_gate_input_identities")
        if type(story_gate.get("environment")) is dict
        else None
    )
    if type(gate_inputs) is not dict or _json_contains_text(
        story_gate,
        FINAL_METRICS_RELATIVE_PATH,
    ):
        raise ValueError("downstream final metrics entered the story-gate cycle")
    paired_gate = (
        (story_gate.get("gates") or {}).get("paired_latency_rss")
        if type(story_gate.get("gates")) is dict
        else None
    )
    if type(paired_gate) is not dict:
        raise ValueError("paired-latency story gate is absent")
    expected_binding = build_preapproval_execution_binding(preapproval_report)
    expected_raw = _pretty_report_bytes(expected_binding)
    if len(expected_raw) > 2 * 1024 * 1024:
        raise ValueError("preapproval execution binding exceeds the story-gate cap")
    expected_sha256 = _sha256_bytes(expected_raw)
    matching_identities: list[dict[str, Any]] = []
    artifacts = paired_gate.get("artifact_identities")
    commands = paired_gate.get("commands")
    if type(artifacts) is not list or type(commands) is not list:
        raise ValueError("paired-latency story-gate evidence differs")
    for record in artifacts:
        if type(record) is not dict:
            continue
        path = record.get("path")
        if (
            type(path) is not str
            or not path.startswith(f"{preapproval_root}/")
            or record.get("size_bytes") != len(expected_raw)
            or record.get("raw_sha256") != expected_sha256
        ):
            continue
        raw = _read_bounded_regular_file(
            workspace,
            path,
            maximum_bytes=2 * 1024 * 1024,
            label="story-gated preapproval metrics execution",
        )
        if raw != expected_raw:
            continue
        if not any(
            type(command) is dict
            and command.get("output_artifact_identity") == record
            and command.get("output_sha256") == expected_sha256
            for command in commands
        ):
            continue
        matching_identities.append(file_identity(workspace, path))
    if len(matching_identities) != 1:
        raise ValueError(
            "story gate does not bind exactly one preapproval metrics execution"
        )
    return {
        "preapproval_execution_identity": matching_identities[0],
        "story_gate_identity": file_identity(workspace, story_gate_path),
        "terminal_approval_identity": file_identity(
            workspace,
            fixed_approval_path,
        ),
    }


def _validate_paired_evidence(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(PERFORMANCE_CASES):
        raise ValueError("retained paired performance cases differ")
    rebuilt: dict[str, Any] = {}
    for case_id in PERFORMANCE_CASES:
        record = value.get(case_id)
        if type(record) is not dict:
            raise ValueError("retained paired performance record differs")
        off = record.get("flag_off_samples")
        on = record.get("flag_on_samples")
        if type(off) is not list or type(on) is not list:
            raise ValueError("retained paired raw samples are absent")
        rebuilt[case_id] = paired_performance_summary(case_id, off, on)
        if record != rebuilt[case_id]:
            raise ValueError(
                "retained paired summary differs from raw samples and gates"
            )
    return rebuilt


def validate_metrics_report(
    value: Mapping[str, Any],
    workspace: Path = WORKSPACE,
    *,
    require_terminal_approval: bool = False,
    require_all_measurement_gates: bool = False,
) -> dict[str, Any]:
    """Strictly validate a canonical report against current workspace bytes."""

    _validate_json_tree(value, label="retained metrics report")
    expected_fields = {
        "schema_id",
        "story_id",
        "artifact_path",
        "generated_at",
        "evidence_state",
        "final_code_identities",
        "final_code_identity_aggregate_sha256",
        "measurement_policy",
        "limits",
        "paired_performance",
        "quality",
        "deadline_probes",
        "dense_scaling",
        "execution_accounting",
        "warnings",
        "skips",
        "hosted_usage",
        "retention",
        "gates",
        "semantic_identity",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise ValueError("retained metrics report fields differ")
    if value.get("schema_id") != SCHEMA_ID or value.get("story_id") != STORY_ID:
        raise ValueError("retained metrics report identity differs")
    if value.get("artifact_path") != FINAL_METRICS_RELATIVE_PATH:
        raise ValueError("retained metrics artifact path differs")
    generated_at = value.get("generated_at")
    if type(generated_at) is not str:
        raise ValueError("retained metrics timestamp differs")
    try:
        parsed_at = datetime.fromisoformat(generated_at)
    except ValueError as error:
        raise ValueError("retained metrics timestamp differs") from error
    if parsed_at.tzinfo is None:
        raise ValueError("retained metrics timestamp differs")
    if value.get("limits") != dict(TABLE_LIMITS):
        raise ValueError("retained metrics limits differ")
    if value.get("warnings") != 0 or type(value.get("warnings")) is not int:
        raise ValueError("retained metrics warnings must be exact zero")
    if value.get("skips") != 0 or type(value.get("skips")) is not int:
        raise ValueError("retained metrics skips must be exact zero")
    if type(value.get("hosted_usage")) is not dict or set(
        value["hosted_usage"]
    ) != set(HOSTED_USAGE) or any(
        value["hosted_usage"].get(field) != expected
        or type(value["hosted_usage"].get(field)) is not type(expected)
        for field, expected in HOSTED_USAGE.items()
    ):
        raise ValueError("retained metrics hosted use must be exact zero")

    required_paths = required_final_code_paths(workspace)
    if value.get("measurement_policy") != _measurement_policy(required_paths):
        raise ValueError("retained metrics measurement policy differs")
    identities_value = value.get("final_code_identities")
    if type(identities_value) is not list:
        raise ValueError("retained final-code identities differ")
    identities = [validate_file_identity(record) for record in identities_value]
    identity_paths = [record["path"] for record in identities]
    if len(set(identity_paths)) != len(identity_paths):
        raise ValueError("retained final-code identity paths are duplicated")
    if set(identity_paths) != set(required_paths):
        raise ValueError("retained final-code identities differ from required paths")
    if identities != sorted(identities, key=lambda record: record["path"]):
        raise ValueError("retained final-code identities are not canonical")
    for identity in identities:
        if file_identity(workspace, identity["path"]) != identity:
            raise ValueError("retained final-code identity differs from current bytes")
    expected_aggregate = _sha256_bytes(_canonical_bytes(identities))
    if value.get("final_code_identity_aggregate_sha256") != expected_aggregate:
        raise ValueError("retained final-code identity aggregate differs")
    if value.get("evidence_state") != "final_code_bound":
        raise ValueError("retained metrics are not final-code bound")

    paired = _validate_paired_evidence(value.get("paired_performance"))
    retained_first_rss_boundaries = {
        field: {
            sample["phase04_stage_rss_first_boundary_component"]
            for record in paired.values()
            for sample in record[field]
        }
        for field in ("flag_off_samples", "flag_on_samples")
    }
    if retained_first_rss_boundaries != {
        "flag_off_samples": {"repair_extraction"},
        "flag_on_samples": {"budget_start"},
    }:
        raise ValueError("retained RSS first-boundary consistency differs")
    quality = validate_quality_evidence(value.get("quality"), workspace)
    deadlines = validate_deadline_probes(value.get("deadline_probes"))
    dense = validate_dense_scaling_probe(value.get("dense_scaling"))
    execution_accounting = _execution_accounting(
        value.get("paired_performance"),
        value.get("quality"),
    )
    if value.get("execution_accounting") != execution_accounting:
        raise ValueError("retained metrics execution accounting differs")
    if (
        value["warnings"]
        != execution_accounting["warning_line_count"]
        + execution_accounting["phase04_warning_line_count"]
        or value["skips"] != execution_accounting["skipped_worker_count"]
    ):
        raise ValueError("retained metrics warnings/skips accounting differs")
    quality_summary = quality["summary"]
    named_stage_latency_passed = all(
            record["within_p50_overhead_ratio_ceiling"] is True
            and record["within_p95_overhead_ratio_ceiling"] is True
            for record in paired.values()
    )
    whole_parser_latency_passed = all(
        record["within_whole_parser_p50_overhead_ratio_ceiling"] is True
        and record["within_whole_parser_p95_overhead_ratio_ceiling"] is True
        for record in paired.values()
    )
    expected_gates = {
        "paired_latency_passed": (
            named_stage_latency_passed and whole_parser_latency_passed
        ),
        "paired_named_stage_latency_passed": named_stage_latency_passed,
        "paired_whole_parser_latency_passed": whole_parser_latency_passed,
        "paired_peak_rss_passed": all(
            record[
                "within_phase04_stage_peak_rss_increment_delta_ceiling"
            ]
            is True
            for record in paired.values()
        ),
        "output_bounds_passed": all(
            record["within_marked_table_output_ceiling"] is True
            and record["within_document_sidecar_output_ceiling"] is True
            and record["all_flag_off_markers_absent"] is True
            and record["all_flag_on_marked_tables_present"] is True
            for record in paired.values()
        ),
        "semantic_determinism_passed": all(
            record["flag_off_semantic_deterministic"] is True
            and record["flag_on_semantic_deterministic"] is True
            for record in paired.values()
        ),
        "quality_passed": quality_summary.get(
            "all_exact_and_reviewed_dimensions_passed"
        )
        is True,
        "page_deadline_passed": deadlines["gates"][
            "same_page_shared_deadline_passed"
        ],
        "document_deadline_passed": deadlines["gates"][
            "document_wide_shared_deadline_passed"
        ],
        "dense_scaling_passed": dense["within_scaling_ceiling"],
        "final_code_bound": True,
        "worker_diagnostics_passed": (
            execution_accounting["warning_line_count"] == 0
            and execution_accounting["phase04_warning_line_count"] == 0
            and execution_accounting["unexpected_line_count"] == 0
            and execution_accounting["unexpected_extra_worker_count"] == 0
        ),
        "warnings_zero": True,
        "skips_zero": True,
        "hosted_use_zero": True,
    }
    expected_gates["all_measurement_gates_passed"] = all(
        expected_gates.values()
    )

    semantic_identity = value.get("semantic_identity")
    expected_semantic_identity = _build_report_semantic_identity(value)
    if semantic_identity != expected_semantic_identity:
        raise ValueError("retained metrics semantic projection digest differs")
    retention = value.get("retention")
    if type(retention) is not dict:
        raise ValueError("retained metrics approval state differs")
    if retention.get("state") == "preapproval":
        if set(retention) != {
            "state",
            "terminal_approval_expected",
            "binding_basis",
        } or retention != {
            "state": "preapproval",
            "terminal_approval_expected": True,
            "binding_basis": TERMINAL_APPROVAL_BINDING,
        }:
            raise ValueError("preapproval state fields differ")
        terminal_bound = False
    elif retention.get("state") == "terminal_approval_bound":
        if set(retention) != {
            "state",
            "binding_basis",
            "preapproval_execution_identity",
            "story_gate_identity",
            "terminal_approval_identity",
        } or retention.get("binding_basis") != TERMINAL_CHAIN_BINDING:
            raise ValueError("terminal approval state fields differ")
        expected_chain = _validate_fixed_terminal_chain(
            _preapproval_report_from_terminal(value),
            workspace,
        )
        if retention != {
            "state": "terminal_approval_bound",
            "binding_basis": TERMINAL_CHAIN_BINDING,
            **expected_chain,
        }:
            raise ValueError("terminal approval chain identities differ")
        terminal_bound = True
    else:
        raise ValueError("retained metrics approval state differs")
    expected_gates["terminal_approval_bound"] = terminal_bound
    expected_gates["all_passed"] = (
        expected_gates["all_measurement_gates_passed"] and terminal_bound
    )
    if value.get("gates") != expected_gates:
        raise ValueError("retained metrics gates differ from raw evidence")
    if require_terminal_approval and not terminal_bound:
        raise ValueError("terminal approval is required for final downstream state")
    if (
        require_all_measurement_gates
        and not expected_gates["all_measurement_gates_passed"]
    ):
        raise ValueError("one or more retained measurement gates failed")
    for case_id in QUALITY_CASES:
        _verified_source_bytes(workspace, case_id)
    return deepcopy(dict(value))


def validate_retained_metrics_artifact(
    workspace: Path = WORKSPACE,
    *,
    require_terminal_approval: bool = False,
    require_all_measurement_gates: bool = False,
) -> dict[str, Any]:
    """Load the fixed artifact and reject noncanonical or stale bytes."""

    workspace = _trusted_workspace_root(
        workspace,
        label="retained metrics workspace",
    )
    raw = _read_bounded_regular_file(
        workspace,
        FINAL_METRICS_RELATIVE_PATH,
        maximum_bytes=MAXIMUM_RETAINED_METRICS_BYTES,
        label="retained metrics artifact",
    )
    value = _load_strict_bounded_json(raw, label="retained metrics artifact")
    canonical = _pretty_report_bytes(value)
    if raw != canonical:
        raise ValueError("retained metrics artifact bytes are not canonical")
    return validate_metrics_report(
        value,
        workspace,
        require_terminal_approval=require_terminal_approval,
        require_all_measurement_gates=require_all_measurement_gates,
    )


def bind_terminal_approval(
    preapproval_report: Mapping[str, Any],
    terminal_approval_path: str,
    workspace: Path = WORKSPACE,
) -> dict[str, Any]:
    """Bind an approval to already-measured bytes without rerunning metrics."""

    workspace = _trusted_workspace_root(
        workspace,
        label="terminal-binding workspace",
    )
    validated = validate_metrics_report(
        preapproval_report,
        workspace,
        require_terminal_approval=False,
        require_all_measurement_gates=True,
    )
    if validated["retention"]["state"] != "preapproval":
        raise ValueError("terminal approval can only bind a preapproval artifact")
    approval_path = validate_file_identity_path(
        terminal_approval_path,
        field_name="terminal approval path",
    )
    if approval_path != fixed_terminal_approval_path():
        raise ValueError("terminal approval path is not the fixed Phase03 leaf")
    chain = _validate_fixed_terminal_chain(validated, workspace)
    final = deepcopy(validated)
    final["retention"] = {
        "state": "terminal_approval_bound",
        "binding_basis": TERMINAL_CHAIN_BINDING,
        **chain,
    }
    final["gates"]["terminal_approval_bound"] = True
    final["gates"]["all_passed"] = final["gates"][
        "all_measurement_gates_passed"
    ]
    if final["semantic_identity"] != _build_report_semantic_identity(final):
        raise ValueError("terminal approval changed the semantic projection")
    return validate_metrics_report(
        final,
        workspace,
        require_terminal_approval=True,
        require_all_measurement_gates=True,
    )


def generate_retained_metrics_report(
    workspace: Path = WORKSPACE,
    *,
    terminal_approval_path: str | None = None,
) -> dict[str, Any]:
    """Run the complete real retained flow; no gate booleans are injectable."""

    workspace = _trusted_workspace_root(
        workspace,
        label="retained-generation workspace",
    )
    if terminal_approval_path is not None:
        preapproval = validate_retained_metrics_artifact(
            workspace,
            require_terminal_approval=False,
            require_all_measurement_gates=True,
        )
        return bind_terminal_approval(
            preapproval,
            terminal_approval_path,
            workspace,
        )
    paired = generate_paired_metrics(workspace)
    quality = generate_reviewed_quality_evidence(workspace)
    deadlines = generate_deadline_probes()
    dense = generate_dense_scaling_probe()
    identities = [
        file_identity(workspace, path)
        for path in required_final_code_paths(workspace)
    ]
    report = build_metrics_report(
        paired,
        quality,
        deadlines,
        dense,
        final_code_identities=identities,
        workspace=workspace,
    )
    validate_metrics_report(
        report,
        workspace,
        require_terminal_approval=False,
        require_all_measurement_gates=True,
    )
    return report


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P04-US01 table metrics worker")
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--worker-case", choices=QUALITY_CASES)
    parser.add_argument("--worker-enabled", choices=("true", "false"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rss-monitor-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--rss-observer-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--generate-retained-report", action="store_true")
    parser.add_argument("--terminal-approval-path")
    parser.add_argument(
        "--probe-phase03-guard-binding",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    workspace = _trusted_workspace_root(
        arguments.workspace,
        label="metrics CLI workspace",
    )
    if arguments.rss_observer_fd is not None:
        if (
            arguments.generate_retained_report
            or arguments.worker_case is not None
            or arguments.worker_enabled is not None
            or arguments.output is not None
            or arguments.rss_monitor_fd is not None
            or arguments.terminal_approval_path is not None
            or arguments.probe_phase03_guard_binding
        ):
            raise SystemExit(
                "RSS observer mode cannot be combined with another mode"
            )
        return _run_external_rss_observer(arguments.rss_observer_fd)
    if arguments.probe_phase03_guard_binding:
        if (
            arguments.generate_retained_report
            or arguments.worker_case is not None
            or arguments.worker_enabled is not None
            or arguments.output is not None
            or arguments.rss_monitor_fd is not None
            or arguments.rss_observer_fd is not None
            or arguments.terminal_approval_path is not None
        ):
            raise SystemExit("guard-binding probe cannot be combined with another mode")
        _phase03_exception_guard()
        return 0
    if arguments.generate_retained_report:
        if (
            arguments.worker_case is not None
            or arguments.worker_enabled is not None
            or arguments.rss_monitor_fd is not None
            or arguments.rss_observer_fd is not None
        ):
            raise SystemExit("retained-report mode cannot also be worker mode")
        destination = workspace / FINAL_METRICS_RELATIVE_PATH
        if arguments.output is not None and Path(
            os.path.abspath(arguments.output)
        ) != destination:
            raise SystemExit(
                "retained metrics output is fixed at "
                f"{FINAL_METRICS_RELATIVE_PATH}"
            )
        report = generate_retained_metrics_report(
            workspace,
            terminal_approval_path=arguments.terminal_approval_path,
        )
        _write_json_atomic(
            destination,
            report,
            trusted_root=workspace,
        )
        validate_retained_metrics_artifact(
            workspace,
            require_terminal_approval=arguments.terminal_approval_path is not None,
            require_all_measurement_gates=True,
        )
        return 0
    if (
        arguments.worker_case is None
        or arguments.worker_enabled is None
        or arguments.output is None
        or arguments.rss_monitor_fd is None
        or arguments.rss_observer_fd is not None
        or arguments.terminal_approval_path is not None
    ):
        raise SystemExit(
            "worker case, enabled state, output, and parent RSS monitor are "
            "required in worker mode"
        )
    rss_sampler = _ExternalRSSSamplerProxy(arguments.rss_monitor_fd)
    snapshot = worker_snapshot(
        workspace,
        arguments.worker_case,
        arguments.worker_enabled == "true",
        rss_sampler=rss_sampler,
    )
    _write_json_atomic(
        arguments.output,
        snapshot,
        trusted_root=arguments.output.parent,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
