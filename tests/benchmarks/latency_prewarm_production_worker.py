"""Fresh-process production ASGI adapter for LAT-US02 local evidence.

The module has no hosted-provider integration.  Its command-line entry point is
only launched inside the repository's Python and Darwin process-tree network
denials, imports the real application after the cold sample, enters the real
ASGI lifespan, and emits one bounded closed worker envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import select
import signal
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, model_validator
import psutil

from tests.benchmarks.latency_isolation import (
    child_network_guard_identity,
    exact_supplied_worker_environment_sha256,
    network_guard_implementation_identity,
    os_network_sandbox_identity,
)
from tests.benchmarks.latency_prewarm_contracts import (
    AttemptStatus,
    ConfigurationIdentity,
    ContractModel,
    CrossInputRequestObservation,
    FileTreeIdentityEvidence,
    LifecycleResourceEvidence,
    NormalizedParseResultWitness,
    OutputIdentity,
    PEAK_SAMPLE_EDGE_TOLERANCE_NS,
    PEAK_SAMPLE_MAXIMUM_GAP_NS,
    PEAK_SAMPLE_TARGET_INTERVAL_NS,
    ProcessCpuCounter,
    ProcessCpuSnapshot,
    PRODUCTION_MINIMUM_REQUESTS,
    RequestObservation,
    RequestResourceBoundary,
    ResourcePhase,
    ResourceSample,
    RunMode,
    SampledProcessIdentity,
    SourceIdentity,
    WorkerForkDenialEvidence,
    WorkerMeasurementEnvelope,
    canonical_model_bytes,
    derive_prewarm_harness_sha256,
    normalized_parse_result_witness,
)
from tests.benchmarks.latency_prewarm_cpu import (
    DarwinProcessMetricSample,
    sample_darwin_process_group_metrics,
)
from tests.benchmarks.latency_runner import (
    derive_candidate_code_sha256,
    derive_dependency_lock_sha256,
    read_process_tree_snapshot,
)
from tests.benchmarks.latency_prewarm_watchdog import (
    AppendOnlyLogSnapshot,
    PhaseDeadlineRecord,
    append_phase_deadline,
    read_phase_acks,
    read_phase_deadlines,
    wait_for_phase_ack,
)

MAXIMUM_SOURCE_BYTES = 32 * 1024 * 1024
MAXIMUM_RESPONSE_BYTES = 67_108_864
MAXIMUM_REQUEST_COUNT = 32
PEAK_SAMPLE_INTERVAL_SECONDS = PEAK_SAMPLE_TARGET_INTERVAL_NS / 1_000_000_000
MAXIMUM_ATTEMPT_RUNTIME_NS = 11_000_000_000_000


@dataclass(slots=True)
class _PhaseDeadlineClient:
    root: Path
    control_path: Path
    ack_path: Path
    attempt_id: str
    whole_deadline_monotonic_ns: int
    control_snapshot: AppendOnlyLogSnapshot | None = None
    ack_snapshot: AppendOnlyLogSnapshot | None = None
    latest: PhaseDeadlineRecord | None = None

    def bind_initial_startup(self) -> None:
        records, self.control_snapshot = read_phase_deadlines(
            root=self.root,
            path=self.control_path,
            attempt_id=self.attempt_id,
            whole_deadline_monotonic_ns=self.whole_deadline_monotonic_ns,
        )
        acks, self.ack_snapshot = read_phase_acks(
            root=self.root,
            path=self.ack_path,
            attempt_id=self.attempt_id,
        )
        if (
            len(records) != 1
            or records[0].phase != "startup"
            or len(acks) != 1
            or acks[0].phase_record_sha256 != records[0].record_sha256
            or acks[0].observed_monotonic_ns
            >= records[0].deadline_monotonic_ns
            or time.monotonic_ns() >= records[0].deadline_monotonic_ns
        ):
            raise RuntimeError("initial startup deadline ACK differs")
        self.latest = records[0]

    def advance(self, phase: Literal["request", "shutdown"], timeout_ns: int) -> None:
        if self.latest is None:
            raise RuntimeError("phase deadline client is not bound")
        record = append_phase_deadline(
            root=self.root,
            path=self.control_path,
            attempt_id=self.attempt_id,
            phase=phase,
            timeout_ns=timeout_ns,
            whole_deadline_monotonic_ns=self.whole_deadline_monotonic_ns,
        )
        if record.sequence != self.latest.sequence + 1:
            raise RuntimeError("phase deadline sequence differs")
        phase_ack = wait_for_phase_ack(
            root=self.root,
            path=self.ack_path,
            attempt_id=self.attempt_id,
            phase_record=record,
        )
        if (
            phase_ack.observed_monotonic_ns >= record.deadline_monotonic_ns
            or time.monotonic_ns() >= record.deadline_monotonic_ns
        ):
            raise TimeoutError("phase deadline elapsed before native entry")
        records, self.control_snapshot = read_phase_deadlines(
            root=self.root,
            path=self.control_path,
            attempt_id=self.attempt_id,
            whole_deadline_monotonic_ns=self.whole_deadline_monotonic_ns,
            previous=self.control_snapshot,
        )
        acks, self.ack_snapshot = read_phase_acks(
            root=self.root,
            path=self.ack_path,
            attempt_id=self.attempt_id,
            previous=self.ack_snapshot,
        )
        if (
            records[-1] != record
            or len(records) != record.sequence
            or len(acks) != record.sequence
            or acks[-1].phase_record_sha256 != record.record_sha256
            or acks[-1].observed_monotonic_ns
            >= record.deadline_monotonic_ns
            or time.monotonic_ns() >= record.deadline_monotonic_ns
        ):
            raise RuntimeError("phase deadline acknowledgement differs")
        self.latest = record


class PrebindFatalRecord(ContractModel):
    schema_id: Literal["phase-latency-prewarm-worker-prebind-fatal-v1"]
    attempt_id: str
    controller_pid: Annotated[int, Field(strict=True, gt=0)]
    controller_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    controller_pgid: Annotated[int, Field(strict=True, gt=0)]
    controller_sid: Annotated[int, Field(strict=True, gt=0)]
    worker_pid: Annotated[int, Field(strict=True, gt=0)]
    worker_create_time_ns: Annotated[int, Field(strict=True, gt=0)]
    worker_pgid: Annotated[int, Field(strict=True, gt=0)]
    worker_sid: Annotated[int, Field(strict=True, gt=0)]
    absolute_deadline_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    observed_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    reason: Literal[
        "controller_missing",
        "controller_reused",
        "controller_group_drift",
        "worker_group_drift",
        "absolute_deadline",
        "release_eof",
        "release_token_invalid",
        "prebind_internal_error",
    ]
    own_group_sigkill_attempted: Literal[True] = True
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record(self) -> "PrebindFatalRecord":
        fields = self.model_dump(mode="json", exclude={"record_sha256"})
        if self.record_sha256 != _canonical_sha256(fields):
            raise ValueError("worker prebind fatal identity differs")
        return self


class CrossInputWorkerEnvelope(ContractModel):
    schema_id: Literal["phase-latency-prewarm-cross-input-worker-v1"]
    source_a: SourceIdentity
    source_b: SourceIdentity
    measurement_request_count: Literal[3] = 3
    observations: Annotated[
        tuple[CrossInputRequestObservation, ...], Field(min_length=3, max_length=3)
    ]
    artifact_before_requests: FileTreeIdentityEvidence
    artifact_after_shutdown: FileTreeIdentityEvidence
    startup_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    shutdown_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    cold_resource: ResourceSample
    shutdown_resource: ResourceSample
    application_identity_validated: StrictBool
    dependency_identity_validated: StrictBool
    parser_runtime_identity_validated: StrictBool
    runtime_artifact_identity_validated: StrictBool
    configuration_identity_validated: StrictBool
    converter_identity_validated: StrictBool
    network_isolation_validated: StrictBool
    runtime_closed: StrictBool
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @model_validator(mode="after")
    def validate_control(self) -> "CrossInputWorkerEnvelope":
        if self.schema_id != "phase-latency-prewarm-cross-input-worker-v1":
            raise ValueError("cross-input worker schema differs")
        if tuple(item.source for item in self.observations) != (
            self.source_a,
            self.source_b,
            self.source_a,
        ):
            raise ValueError("cross-input worker sequence differs")
        if len(self.observations) != 3:
            raise ValueError("cross-input worker requires exactly three requests")
        return self


class ProductionRawRequestObservation(ContractModel):
    """CPU-free request result retained before controller evidence assembly.

    The fork-denied worker cannot sample its own request boundary without
    charging evidence work to the measured process.  It therefore emits only
    response/runtime facts here.  The controller joins this record to the
    independently retained BEGIN/END samples and broker wait4 receipt before a
    :class:`RequestObservation` can exist.
    """

    schema_id: Literal["phase-latency-production-raw-request-v1"] = (
        "phase-latency-production-raw-request-v1"
    )
    attempt_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_index: Annotated[int, Field(strict=True, ge=1, le=MAXIMUM_REQUEST_COUNT)]
    request_epoch: Annotated[int, Field(strict=True, ge=2)]
    source: SourceIdentity
    client_post_started_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    client_post_completed_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    client_post_elapsed_ns: Annotated[int, Field(strict=True, gt=0)]
    http_status_code: Literal[200] = 200
    response_media_type: Literal["application/json"] = "application/json"
    response_content_type_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    response_body_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    asgi_response_witness_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    response_size_bytes: Annotated[
        int, Field(strict=True, gt=0, le=MAXIMUM_RESPONSE_BYTES)
    ]
    output: OutputIdentity
    runtime_snapshot_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    converter_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ] | None = None
    broker_request_receipt_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    request_binding_record_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    materialized_at_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    status: Literal["success"] = "success"
    legacy_cpu_evidence_emitted: Literal[False] = False
    record_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_raw_request(self) -> "ProductionRawRequestObservation":
        if (
            self.request_id
            != f"{self.attempt_id}-q{self.request_index:04d}"
            or self.request_epoch != self.request_index + 1
            or self.client_post_completed_monotonic_ns
            < self.client_post_started_monotonic_ns
            or self.client_post_elapsed_ns
            != self.client_post_completed_monotonic_ns
            - self.client_post_started_monotonic_ns
            or self.materialized_at_monotonic_ns
            < self.client_post_completed_monotonic_ns
            or self.response_body_sha256 != self.output.sha256
            or self.response_size_bytes != self.output.size_bytes
            or self.output.media_type != self.response_media_type
        ):
            raise ValueError("raw production request custody differs")
        if self.record_sha256 != _canonical_sha256(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("raw production request identity differs")
        return self


def production_raw_request_observation(
    **fields: object,
) -> ProductionRawRequestObservation:
    """Build a raw request record whose digest cannot be caller supplied."""

    if "record_sha256" in fields:
        raise ValueError("raw request identity is derived")
    provisional = ProductionRawRequestObservation.model_construct(
        **fields, record_sha256="0" * 64
    )
    return ProductionRawRequestObservation(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class DirectRollbackRawWorkerEnvelope(ContractModel):
    """One CPU-free direct flag-off result retained before paired attempts."""

    schema_id: Literal["phase-latency-direct-rollback-raw-worker-v1"] = (
        "phase-latency-direct-rollback-raw-worker-v1"
    )
    attempt_id: Annotated[str, Field(min_length=1, max_length=256)]
    source: SourceIdentity
    configuration_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    output: OutputIdentity
    normalized_output_witness: NormalizedParseResultWitness
    response_content_type_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    request_started_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    request_completed_monotonic_ns: Annotated[int, Field(strict=True, gt=0)]
    startup_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    shutdown_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    cold_resource: ResourceSample
    shutdown_resource: ResourceSample
    runtime_artifact_before_requests: FileTreeIdentityEvidence
    runtime_artifact_after_shutdown: FileTreeIdentityEvidence
    application_identity_validated: Literal[True] = True
    dependency_identity_validated: Literal[True] = True
    parser_runtime_identity_validated: Literal[True] = True
    runtime_artifact_identity_validated: Literal[True] = True
    configuration_identity_validated: Literal[True] = True
    feature_flag_disabled: Literal[True] = True
    private_broker_capability_present: Literal[False] = False
    broker_started: Literal[False] = False
    worker_fork_denial_installed: Literal[False] = False
    supervisor_bypassed_to_exact_target: Literal[True] = True
    production_asgi_lifespan_exercised: Literal[True] = True
    network_isolation_validated: Literal[True] = True
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    record_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_direct_rollback(self) -> "DirectRollbackRawWorkerEnvelope":
        witness = self.normalized_output_witness
        if (
            self.attempt_id != f"lat-us02-rollback-{self.source.case_id}"
            or self.request_completed_monotonic_ns
            < self.request_started_monotonic_ns
            or self.runtime_artifact_before_requests
            != self.runtime_artifact_after_shutdown
            or (
                self.output.normalized_sha256,
                self.output.api_contract_sha256,
                self.output.provenance_sha256,
                self.output.concerns_sha256,
                self.output.deterministic_ids_sha256,
            )
            != (
                witness.normalized_sha256,
                witness.api_contract_sha256,
                witness.provenance_sha256,
                witness.concerns_sha256,
                witness.deterministic_ids_sha256,
            )
            or self.record_sha256
            != _canonical_sha256(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("direct rollback raw worker custody differs")
        return self


def direct_rollback_raw_worker_envelope(
    **fields: object,
) -> DirectRollbackRawWorkerEnvelope:
    if "record_sha256" in fields:
        raise ValueError("direct rollback raw identity is derived")
    provisional = DirectRollbackRawWorkerEnvelope.model_construct(
        **fields, record_sha256="0" * 64
    )
    return DirectRollbackRawWorkerEnvelope(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class ProductionRawWorkerEnvelope(ContractModel):
    """Bounded brokered worker output awaiting controller CPU-v2 injection."""

    schema_id: Literal["phase-latency-production-raw-worker-v1"] = (
        "phase-latency-production-raw-worker-v1"
    )
    case_id: Annotated[str, Field(min_length=1, max_length=128)]
    mode: RunMode
    source: SourceIdentity
    startup_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    shutdown_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    application_identity_validated: StrictBool
    dependency_identity_validated: StrictBool
    parser_runtime_identity_validated: StrictBool
    runtime_artifact_identity_validated: StrictBool
    configuration_identity_validated: StrictBool
    converter_identity_validated: StrictBool
    ready_after_identity_validation: Literal[True] = True
    prewarm_completed: StrictBool
    requests: Annotated[
        tuple[ProductionRawRequestObservation, ...],
        Field(min_length=PRODUCTION_MINIMUM_REQUESTS, max_length=MAXIMUM_REQUEST_COUNT),
    ]
    cold_resource: ResourceSample
    prewarmed_idle_resource: ResourceSample | None
    repeated_request_resource: ResourceSample
    shutdown_resource: ResourceSample
    state_retention_detected: StrictBool
    production_asgi_lifespan_exercised: Literal[True] = True
    network_isolation_validated: StrictBool
    runtime_before_requests_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    runtime_after_requests_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    runtime_after_shutdown_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    runtime_artifact_before_requests: FileTreeIdentityEvidence
    runtime_artifact_after_shutdown: FileTreeIdentityEvidence
    startup_broker_receipt: dict[str, Any]
    startup_broker_receipt_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    shutdown_broker_receipt: dict[str, Any]
    shutdown_broker_receipt_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    fork_denial_evidence: WorkerForkDenialEvidence
    request_control_completed_count: Annotated[
        int, Field(strict=True, ge=PRODUCTION_MINIMUM_REQUESTS, le=MAXIMUM_REQUEST_COUNT)
    ]
    request_control_final_state: Literal["closed"] = "closed"
    oom_observed: Literal[False] = False
    legacy_request_cpu_evidence_count: Literal[0] = 0
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    record_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_raw_worker(self) -> "ProductionRawWorkerEnvelope":
        from app.services.tesseract_broker_protocol import (
            request_receipt_from_mapping,
        )

        startup_receipt = request_receipt_from_mapping(
            self.startup_broker_receipt
        )
        shutdown_receipt = request_receipt_from_mapping(
            self.shutdown_broker_receipt
        )
        indexes = tuple(item.request_index for item in self.requests)
        if (
            self.case_id != self.source.case_id
            or indexes != tuple(range(1, len(self.requests) + 1))
            or any(item.source != self.source for item in self.requests)
            or any(item.attempt_id != self.requests[0].attempt_id for item in self.requests)
            or self.request_control_completed_count != len(self.requests)
            or self.fork_denial_evidence.expected_request_count != len(self.requests)
            or self.runtime_artifact_before_requests
            != self.runtime_artifact_after_shutdown
            or startup_receipt.logical_phase != "startup"
            or startup_receipt.terminal_kind != "end"
            or startup_receipt.receipt_sha256
            != self.startup_broker_receipt_sha256
            or shutdown_receipt.logical_phase != "shutdown"
            or shutdown_receipt.terminal_kind != "end"
            or shutdown_receipt.receipt_sha256
            != self.shutdown_broker_receipt_sha256
            or shutdown_receipt.attempt_nonce_sha256
            != startup_receipt.attempt_nonce_sha256
            or shutdown_receipt.scope_sha256 != startup_receipt.scope_sha256
            or self.requests[0].broker_request_receipt_sha256
            == self.startup_broker_receipt_sha256
            or shutdown_receipt.previous_receipt_sha256
            != self.requests[-1].broker_request_receipt_sha256
        ):
            raise ValueError("raw production worker custody differs")
        if self.mode is RunMode.ENABLED:
            if not self.prewarm_completed or self.prewarmed_idle_resource is None:
                raise ValueError("raw enabled worker lacks prewarm completion")
            if any(item.converter_sha256 is None for item in self.requests):
                raise ValueError("raw enabled request lacks converter identity")
        elif self.prewarm_completed or self.prewarmed_idle_resource is not None:
            raise ValueError("raw predecessor cannot claim prewarming")
        if self.record_sha256 != _canonical_sha256(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("raw production worker identity differs")
        return self


def production_raw_worker_envelope(**fields: object) -> ProductionRawWorkerEnvelope:
    if "record_sha256" in fields:
        raise ValueError("raw worker identity is derived")
    provisional = ProductionRawWorkerEnvelope.model_construct(
        **fields, record_sha256="0" * 64
    )
    return ProductionRawWorkerEnvelope(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class CrossInputRawWorkerEnvelope(ContractModel):
    """CPU-free A-B-A worker result awaiting controller evidence assembly."""

    schema_id: Literal["phase-latency-cross-input-raw-worker-v1"] = (
        "phase-latency-cross-input-raw-worker-v1"
    )
    source_a: SourceIdentity
    source_b: SourceIdentity
    measurement_request_count: Literal[3] = 3
    requests: Annotated[
        tuple[ProductionRawRequestObservation, ...], Field(min_length=3, max_length=3)
    ]
    artifact_before_requests: FileTreeIdentityEvidence
    artifact_after_shutdown: FileTreeIdentityEvidence
    startup_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    shutdown_duration_ns: Annotated[int, Field(strict=True, ge=0)]
    cold_resource: ResourceSample
    shutdown_resource: ResourceSample
    startup_broker_receipt: dict[str, Any]
    startup_broker_receipt_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    shutdown_broker_receipt: dict[str, Any]
    shutdown_broker_receipt_sha256: Annotated[
        str, Field(pattern=r"^[0-9a-f]{64}$")
    ]
    application_identity_validated: StrictBool
    dependency_identity_validated: StrictBool
    parser_runtime_identity_validated: StrictBool
    runtime_artifact_identity_validated: StrictBool
    configuration_identity_validated: StrictBool
    converter_identity_validated: StrictBool
    network_isolation_validated: StrictBool
    runtime_closed: StrictBool
    fork_denial_evidence: WorkerForkDenialEvidence
    request_control_completed_count: Literal[3] = 3
    request_control_final_state: Literal["closed"] = "closed"
    legacy_request_cpu_evidence_count: Literal[0] = 0
    hosted_calls: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    record_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_raw_control(self) -> "CrossInputRawWorkerEnvelope":
        from app.services.tesseract_broker_protocol import (
            request_receipt_from_mapping,
        )

        startup_receipt = request_receipt_from_mapping(
            self.startup_broker_receipt
        )
        shutdown_receipt = request_receipt_from_mapping(
            self.shutdown_broker_receipt
        )
        if (
            tuple(item.request_index for item in self.requests) != (1, 2, 3)
            or tuple(item.source for item in self.requests)
            != (self.source_a, self.source_b, self.source_a)
            or len({item.attempt_id for item in self.requests}) != 1
            or any(item.converter_sha256 is None for item in self.requests)
            or self.fork_denial_evidence.expected_request_count != 3
            or self.artifact_before_requests != self.artifact_after_shutdown
            or startup_receipt.logical_phase != "startup"
            or startup_receipt.terminal_kind != "end"
            or startup_receipt.receipt_sha256
            != self.startup_broker_receipt_sha256
            or shutdown_receipt.logical_phase != "shutdown"
            or shutdown_receipt.terminal_kind != "end"
            or shutdown_receipt.receipt_sha256
            != self.shutdown_broker_receipt_sha256
            or shutdown_receipt.attempt_nonce_sha256
            != startup_receipt.attempt_nonce_sha256
            or shutdown_receipt.scope_sha256 != startup_receipt.scope_sha256
            or shutdown_receipt.previous_receipt_sha256
            != self.requests[-1].broker_request_receipt_sha256
        ):
            raise ValueError("raw cross-input worker custody differs")
        if self.record_sha256 != _canonical_sha256(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("raw cross-input worker identity differs")
        return self


def cross_input_raw_worker_envelope(**fields: object) -> CrossInputRawWorkerEnvelope:
    if "record_sha256" in fields:
        raise ValueError("raw cross-input identity is derived")
    provisional = CrossInputRawWorkerEnvelope.model_construct(
        **fields, record_sha256="0" * 64
    )
    return CrossInputRawWorkerEnvelope(
        **fields,
        record_sha256=_canonical_sha256(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _broker_receipt_mapping(receipt: object) -> dict[str, Any]:
    """Normalize one app receipt to its exact JSON wire projection."""

    value = json.loads(_canonical_bytes(asdict(receipt)))
    from app.services.tesseract_broker_protocol import (
        request_receipt_from_mapping,
    )

    observed = request_receipt_from_mapping(value)
    if observed.receipt_sha256 != value.get("receipt_sha256"):
        raise RuntimeError("broker receipt JSON projection differs")
    return value


def _exact_process_identity(pid: int) -> tuple[int, int, int, bool] | None:
    try:
        process = psutil.Process(pid)
        with process.oneshot():
            create_time_ns = int(process.create_time() * 1_000_000_000)
            process_group_id = os.getpgid(pid)
            session_id = os.getsid(pid)
            terminal = process.status() in {
                psutil.STATUS_DEAD,
                psutil.STATUS_ZOMBIE,
            }
    except (ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess):
        return None
    return create_time_ns, process_group_id, session_id, terminal


def _private_prebind_fatal_write(path: Path, record: PrebindFatalRecord) -> None:
    resolved_parent = path.parent.resolve(strict=True)
    parent_stat = resolved_parent.lstat()
    if (
        resolved_parent.is_symlink()
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or parent_stat.st_mode & 0o077
    ):
        raise RuntimeError("prebind fatal parent custody differs")
    target = resolved_parent / path.name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(target, flags, 0o600)
    payload = canonical_model_bytes(record)
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("prebind fatal write made no progress")
            written += count
        os.fsync(descriptor)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_uid != os.getuid()
            or observed.st_nlink != 1
            or observed.st_size != len(payload)
        ):
            raise RuntimeError("prebind fatal file custody differs")
    finally:
        os.close(descriptor)


def _prebind_failure(
    *,
    attempt_id: str,
    controller_pid: int,
    controller_create_time_ns: int,
    controller_pgid: int,
    controller_sid: int,
    absolute_deadline_monotonic_ns: int,
    fatal_path: Path,
    reason: str,
) -> None:
    worker_pid = os.getpid()
    observed = _exact_process_identity(worker_pid)
    if observed is None:
        os._exit(70)
    worker_create_time_ns, worker_pgid, worker_sid, terminal = observed
    safe_group = bool(
        not terminal
        and worker_pid == worker_pgid == worker_sid
        and worker_pgid
        not in {controller_pid, controller_pgid, controller_sid, 0, 1}
    )
    if not safe_group:
        os._exit(71)
    fields = {
        "schema_id": "phase-latency-prewarm-worker-prebind-fatal-v1",
        "attempt_id": attempt_id,
        "controller_pid": controller_pid,
        "controller_create_time_ns": controller_create_time_ns,
        "controller_pgid": controller_pgid,
        "controller_sid": controller_sid,
        "worker_pid": worker_pid,
        "worker_create_time_ns": worker_create_time_ns,
        "worker_pgid": worker_pgid,
        "worker_sid": worker_sid,
        "absolute_deadline_monotonic_ns": absolute_deadline_monotonic_ns,
        "observed_monotonic_ns": max(1, time.monotonic_ns()),
        "reason": reason,
        "own_group_sigkill_attempted": True,
    }
    record = PrebindFatalRecord(
        **fields, record_sha256=_canonical_sha256(fields)
    )
    try:
        _private_prebind_fatal_write(fatal_path, record)
    except BaseException:
        os._exit(72)
    os.killpg(worker_pgid, signal.SIGKILL)
    os._exit(73)


def _await_controller_release(
    *,
    attempt_id: str,
    controller_pid: int,
    controller_create_time_ns: int,
    controller_pgid: int,
    controller_sid: int,
    absolute_deadline_monotonic_ns: int,
    release_fd: int,
    fatal_path: Path,
) -> None:
    if (
        any(
            type(value) is not int or value <= 0
            for value in (
                controller_pid,
                controller_create_time_ns,
                controller_pgid,
                controller_sid,
                absolute_deadline_monotonic_ns,
                release_fd,
            )
        )
        or not fatal_path.is_absolute()
    ):
        raise ValueError("worker prebind inputs differ")

    def failure(reason: str) -> None:
        _prebind_failure(
            attempt_id=attempt_id,
            controller_pid=controller_pid,
            controller_create_time_ns=controller_create_time_ns,
            controller_pgid=controller_pgid,
            controller_sid=controller_sid,
            absolute_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
            fatal_path=fatal_path,
            reason=reason,
        )

    started_ns = time.monotonic_ns()
    if (
        absolute_deadline_monotonic_ns <= started_ns
        or absolute_deadline_monotonic_ns - started_ns
        > MAXIMUM_ATTEMPT_RUNTIME_NS
    ):
        failure("absolute_deadline")
    while True:
        own = _exact_process_identity(os.getpid())
        if own is None:
            failure("worker_group_drift")
        own_create_ns, own_pgid, own_sid, own_terminal = own or (0, 0, 0, True)
        if (
            own_terminal
            or os.getpid() != own_pgid
            or os.getpid() != own_sid
            or own_pgid
            in {controller_pid, controller_pgid, controller_sid, 0, 1}
            or own_create_ns <= 0
        ):
            failure("worker_group_drift")
        controller = _exact_process_identity(controller_pid)
        if controller is None or os.getppid() != controller_pid:
            failure("controller_missing")
        observed_create, observed_pgid, observed_sid, terminal = controller or (
            0,
            0,
            0,
            True,
        )
        if terminal or observed_create != controller_create_time_ns:
            failure("controller_reused")
        if observed_pgid != controller_pgid or observed_sid != controller_sid:
            failure("controller_group_drift")
        now_ns = time.monotonic_ns()
        if now_ns >= absolute_deadline_monotonic_ns:
            failure("absolute_deadline")
        timeout = min(
            0.05,
            max(0.0, (absolute_deadline_monotonic_ns - now_ns) / 1e9),
        )
        readable, _, _ = select.select((release_fd,), (), (), timeout)
        if not readable:
            continue
        token = os.read(release_fd, 2)
        os.close(release_fd)
        if token == b"":
            failure("release_eof")
        if token != b"\x01":
            failure("release_token_invalid")
        controller = _exact_process_identity(controller_pid)
        own = _exact_process_identity(os.getpid())
        if controller is None or own is None or os.getppid() != controller_pid:
            failure("controller_missing")
        if controller != (
            controller_create_time_ns,
            controller_pgid,
            controller_sid,
            False,
        ):
            failure("controller_reused")
        if own[1] != os.getpid() or own[2] != os.getpid() or own[3]:
            failure("worker_group_drift")
        if time.monotonic_ns() >= absolute_deadline_monotonic_ns:
            failure("absolute_deadline")
        return


def _semantic_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.resolve(strict=True).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def derive_production_network_isolation_sha256(workspace: Path) -> str:
    """Bind both enforced network-denial layers to exact local bytes."""

    sandbox_size, sandbox_sha256 = os_network_sandbox_identity()
    child_size, child_sha256 = child_network_guard_identity(workspace)
    implementation_size, implementation_sha256 = (
        network_guard_implementation_identity(workspace)
    )
    return _canonical_sha256(
        {
            "policy": "python-and-darwin-process-tree-deny-v1",
            "sandbox": {"sha256": sandbox_sha256, "size_bytes": sandbox_size},
            "child_guard": {"sha256": child_sha256, "size_bytes": child_size},
            "implementation": {
                "sha256": implementation_sha256,
                "size_bytes": implementation_size,
            },
        }
    )


def _projection_hash(
    value: object,
    predicate: Callable[[str], bool],
) -> str:
    records: list[dict[str, object]] = []

    def visit(member: object, path: tuple[str, ...]) -> None:
        if type(member) is dict:
            for key in sorted(member):
                if type(key) is not str:
                    raise ValueError("ParseResult contains a non-string JSON key")
                child = member[key]
                child_path = (*path, key)
                if predicate(key):
                    records.append({"path": list(child_path), "value": child})
                else:
                    visit(child, child_path)
        elif type(member) is list:
            for index, child in enumerate(member):
                visit(child, (*path, str(index)))

    visit(value, ())
    return _canonical_sha256(records)


def output_identity_and_witness_from_json(
    raw: bytes,
) -> tuple[OutputIdentity, NormalizedParseResultWitness]:
    """Validate ParseResult once and retain its exact normalized witness."""

    if not raw or len(raw) > MAXIMUM_RESPONSE_BYTES:
        raise ValueError("production response is empty or exceeds its byte bound")
    parsed = json.loads(raw)
    if type(parsed) is not dict:
        raise ValueError("production JSON response must be an object")

    from app.models import ParseResult

    validated = ParseResult.model_validate(parsed).model_dump(
        mode="json", exclude_unset=True
    )
    if validated != parsed:
        raise ValueError("API bytes differ from the validated ParseResult projection")
    normalized = json.loads(_canonical_bytes(validated))
    processing = normalized.get("processing")
    if type(processing) is not dict or "duration_ms" not in processing:
        raise ValueError("ParseResult lacks processing.duration_ms")
    duration_ms = processing.pop("duration_ms")
    if type(duration_ms) is not int or duration_ms < 0:
        raise ValueError("processing.duration_ms is not a non-negative integer")
    normalized_bytes = _semantic_json_bytes(normalized)

    def provenance_key(key: str) -> bool:
        return (
            "source" in key
            or "evidence" in key
            or "provenance" in key
            or key in {"bbox", "confidence", "engine", "ocr_engine"}
        )

    def concern_key(key: str) -> bool:
        return (
            "concern" in key
            or "warning" in key
            or key in {"status", "success"}
        )

    def deterministic_id_key(key: str) -> bool:
        return (
            key == "id"
            or key.endswith("_id")
            or key.endswith("_ids")
            or key
            in {
                "sha256",
                "page_index",
                "page_number",
                "reading_order",
                "schema_version",
            }
        )

    normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    output = OutputIdentity(
        sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=normalized_sha256,
        semantic_sha256=normalized_sha256,
        api_contract_sha256=normalized_sha256,
        provenance_sha256=_projection_hash(normalized, provenance_key),
        concerns_sha256=_projection_hash(normalized, concern_key),
        deterministic_ids_sha256=_projection_hash(
            normalized, deterministic_id_key
        ),
        size_bytes=len(raw),
        media_type="application/json",
        validation="ParseResult",
        normalization_policy="json_exclude_processing_duration_ms_v1",
    )
    witness = normalized_parse_result_witness(normalized)
    if (
        output.normalized_sha256,
        output.api_contract_sha256,
        output.provenance_sha256,
        output.concerns_sha256,
        output.deterministic_ids_sha256,
    ) != (
        witness.normalized_sha256,
        witness.api_contract_sha256,
        witness.provenance_sha256,
        witness.concerns_sha256,
        witness.deterministic_ids_sha256,
    ):
        raise ValueError("ParseResult output/witness projection differs")
    return output, witness


def output_identity_from_json(raw: bytes) -> OutputIdentity:
    """Validate ParseResult and exclude only ``processing.duration_ms``."""

    output, _witness = output_identity_and_witness_from_json(raw)
    return output


def _resource_sample(phase: ResourcePhase) -> ResourceSample:
    snapshot = read_process_tree_snapshot(
        os.getpid(), observed_monotonic_ns=time.monotonic_ns()
    )
    return ResourceSample(
        phase=phase,
        observed_monotonic_ns=snapshot.observed_monotonic_ns,
        rss_bytes=snapshot.total_rss_bytes,
        user_cpu_ns=snapshot.total_user_cpu_ns,
        system_cpu_ns=snapshot.total_system_cpu_ns,
        process_count=len(snapshot.members),
        thread_count=snapshot.total_thread_count,
        file_descriptor_count=snapshot.total_fd_count,
    )


class _PeakSampler:
    """Bounded in-request process-tree peak sampler."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._samples: list[ResourceSample] = []
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="lat-us02-request-peak-sampler",
            daemon=True,
        )

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._samples.append(_resource_sample(ResourcePhase.REQUEST_PEAK))
                if len(self._samples) >= 60_000:
                    raise RuntimeError("request peak sample bound exceeded")
                self._stop.wait(PEAK_SAMPLE_INTERVAL_SECONDS)
        except BaseException as error:  # fail closed after joining the sampler
            self._error = error

    def __enter__(self) -> "_PeakSampler":
        self._samples.append(_resource_sample(ResourcePhase.REQUEST_PEAK))
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("request peak sampler did not stop")
        if self._error is not None:
            raise RuntimeError("request peak sampling failed") from self._error
        self._samples.append(_resource_sample(ResourcePhase.REQUEST_PEAK))

    def peak(self) -> ResourceSample:
        if not self._samples:
            raise RuntimeError("request peak sampling retained no samples")
        return max(self._samples, key=lambda item: item.rss_bytes)

    def peak_process_count(self) -> int:
        if not self._samples:
            raise RuntimeError("request descendant sampling retained no samples")
        return max(item.process_count for item in self._samples)

    def peak_thread_count(self) -> int:
        if not self._samples:
            raise RuntimeError("request thread sampling retained no samples")
        return max(item.thread_count for item in self._samples)

    def peak_file_descriptor_count(self) -> int:
        if not self._samples:
            raise RuntimeError("request FD sampling retained no samples")
        return max(item.file_descriptor_count for item in self._samples)

    def coverage(self, *, started_ns: int, ended_ns: int) -> dict[str, object]:
        timestamps = tuple(item.observed_monotonic_ns for item in self._samples)
        if len(timestamps) < 2 or timestamps != tuple(sorted(timestamps)):
            raise RuntimeError("request peak sampling lacks ordered coverage")
        maximum_gap_ns = max(
            later - earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        )
        covered = bool(
            timestamps[0] <= started_ns + PEAK_SAMPLE_EDGE_TOLERANCE_NS
            and timestamps[-1] >= ended_ns - PEAK_SAMPLE_EDGE_TOLERANCE_NS
            and maximum_gap_ns <= PEAK_SAMPLE_MAXIMUM_GAP_NS
        )
        return {
            "descendant_sample_count": len(timestamps),
            "descendant_first_sample_monotonic_ns": timestamps[0],
            "descendant_last_sample_monotonic_ns": timestamps[-1],
            "descendant_maximum_gap_ns": maximum_gap_ns,
            "descendant_target_interval_ns": PEAK_SAMPLE_TARGET_INTERVAL_NS,
            "descendant_edge_tolerance_ns": PEAK_SAMPLE_EDGE_TOLERANCE_NS,
            "request_boundary_covered": covered,
        }


@dataclass(frozen=True, slots=True)
class _DualGroupResourceObservation:
    resource: ResourceSample
    identities: tuple[SampledProcessIdentity, ...]


def _dual_group_resource_sample(
    phase: ResourcePhase,
    *,
    worker: object,
    broker: object,
) -> _DualGroupResourceObservation:
    """Observe the separate worker/broker groups with raw Darwin identities."""

    required = ("pid", "start_abstime", "process_group_id", "session_id")
    if any(not hasattr(worker, name) or not hasattr(broker, name) for name in required):
        raise TypeError("dual-group sample lacks frozen process identities")
    worker_metrics = sample_darwin_process_group_metrics(
        process_group_id=int(worker.process_group_id)
    )
    broker_metrics = sample_darwin_process_group_metrics(
        process_group_id=int(broker.process_group_id)
    )

    def root_matches(
        metric: DarwinProcessMetricSample,
        identity: object,
    ) -> bool:
        return (
            metric.cpu.pid == int(identity.pid)
            and metric.cpu.start_abstime == int(identity.start_abstime)
            and metric.cpu.process_group_id == int(identity.process_group_id)
            and metric.cpu.session_id == int(identity.session_id)
        )

    if len(worker_metrics) != 1 or not root_matches(worker_metrics[0], worker):
        raise RuntimeError("fork-denied worker group is not exact root-only")
    broker_roots = tuple(
        item for item in broker_metrics if item.cpu.pid == int(broker.pid)
    )
    if len(broker_roots) != 1 or not root_matches(broker_roots[0], broker):
        raise RuntimeError("broker group root identity differs")
    for item in broker_metrics:
        if item.cpu.pid == int(broker.pid):
            continue
        if (
            item.cpu.parent_pid != int(broker.pid)
            or item.cpu.process_group_id != int(broker.process_group_id)
            or item.cpu.session_id != int(broker.session_id)
        ):
            raise RuntimeError("broker child escaped direct frozen lineage")

    all_metrics = (*worker_metrics, *broker_metrics)
    identities = tuple(
        sorted(
            (
                SampledProcessIdentity(
                    role=(
                        "parser_worker"
                        if item.cpu.pid == int(worker.pid)
                        else "tesseract_broker"
                        if item.cpu.pid == int(broker.pid)
                        else "tesseract_child"
                    ),
                    pid=item.cpu.pid,
                    start_abstime=item.cpu.start_abstime,
                    parent_pid=item.cpu.parent_pid,
                    process_group_id=item.cpu.process_group_id,
                    session_id=item.cpu.session_id,
                )
                for item in all_metrics
            ),
            key=lambda item: (item.pid, item.start_abstime),
        )
    )
    observed_ns = max(item.cpu.observed_monotonic_ns for item in all_metrics)
    return _DualGroupResourceObservation(
        resource=ResourceSample(
            phase=phase,
            observed_monotonic_ns=observed_ns,
            rss_bytes=sum(item.rss_bytes for item in all_metrics),
            user_cpu_ns=sum(item.cpu.user_cpu_ns for item in all_metrics),
            system_cpu_ns=sum(item.cpu.system_cpu_ns for item in all_metrics),
            process_count=len(all_metrics),
            thread_count=sum(item.thread_count for item in all_metrics),
            file_descriptor_count=sum(
                item.file_descriptor_count for item in all_metrics
            ),
        ),
        identities=identities,
    )


class _DualGroupPeakSampler:
    """Concurrent raw-identity sampler for one worker and its 1:1 broker."""

    def __init__(self, *, worker: object, broker: object) -> None:
        self._worker = worker
        self._broker = broker
        self._stop = threading.Event()
        self._samples: list[_DualGroupResourceObservation] = []
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name="lat-us02-dual-group-peak-sampler",
            daemon=True,
        )

    def _sample(self) -> None:
        self._samples.append(
            _dual_group_resource_sample(
                ResourcePhase.REQUEST_PEAK,
                worker=self._worker,
                broker=self._broker,
            )
        )
        if len(self._samples) >= 60_000:
            raise RuntimeError("dual-group request peak sample bound exceeded")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._sample()
                self._stop.wait(PEAK_SAMPLE_INTERVAL_SECONDS)
        except BaseException as error:
            self._error = error

    def __enter__(self) -> "_DualGroupPeakSampler":
        self._sample()
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            raise RuntimeError("dual-group request peak sampler did not stop")
        if self._error is not None:
            raise RuntimeError("dual-group request peak sampling failed") from self._error
        self._sample()

    def peak(self) -> ResourceSample:
        if not self._samples:
            raise RuntimeError("dual-group peak sampling retained no samples")
        return max(self._samples, key=lambda item: item.resource.rss_bytes).resource

    def peak_process_count(self) -> int:
        return max(item.resource.process_count for item in self._samples)

    def peak_thread_count(self) -> int:
        return max(item.resource.thread_count for item in self._samples)

    def peak_file_descriptor_count(self) -> int:
        return max(item.resource.file_descriptor_count for item in self._samples)

    def sampled_process_identities(self) -> tuple[SampledProcessIdentity, ...]:
        identities = {
            (item.pid, item.start_abstime): item
            for sample in self._samples
            for item in sample.identities
        }
        return tuple(identities[key] for key in sorted(identities))

    def coverage(self, *, started_ns: int, ended_ns: int) -> dict[str, object]:
        timestamps = tuple(
            item.resource.observed_monotonic_ns for item in self._samples
        )
        if len(timestamps) < 2 or timestamps != tuple(sorted(timestamps)):
            raise RuntimeError("dual-group sampling lacks ordered coverage")
        maximum_gap_ns = max(
            later - earlier
            for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        )
        return {
            "descendant_sample_count": len(timestamps),
            "descendant_first_sample_monotonic_ns": timestamps[0],
            "descendant_last_sample_monotonic_ns": timestamps[-1],
            "descendant_maximum_gap_ns": maximum_gap_ns,
            "descendant_target_interval_ns": PEAK_SAMPLE_TARGET_INTERVAL_NS,
            "descendant_edge_tolerance_ns": PEAK_SAMPLE_EDGE_TOLERANCE_NS,
            "request_boundary_covered": bool(
                timestamps[0] <= started_ns + PEAK_SAMPLE_EDGE_TOLERANCE_NS
                and timestamps[-1] >= ended_ns - PEAK_SAMPLE_EDGE_TOLERANCE_NS
                and maximum_gap_ns <= PEAK_SAMPLE_MAXIMUM_GAP_NS
            ),
        }


def _cpu_cumulative_ns() -> ProcessCpuSnapshot:
    tree = read_process_tree_snapshot(
        os.getpid(), observed_monotonic_ns=time.monotonic_ns()
    )
    own = resource.getrusage(resource.RUSAGE_SELF)
    reaped = resource.getrusage(resource.RUSAGE_CHILDREN)
    members = tuple(
        ProcessCpuCounter(
            pid=member.identity.pid,
            create_time_ns=member.identity.create_time_ns,
            ownership="worker" if index == 0 else "descendant",
            user_cpu_ns=member.user_cpu_ns,
            system_cpu_ns=member.system_cpu_ns,
        )
        for index, member in enumerate(tree.members)
    )
    return ProcessCpuSnapshot(
        observed_monotonic_ns=time.monotonic_ns(),
        rusage_self_user_cpu_ns=max(0, int(own.ru_utime * 1_000_000_000)),
        rusage_self_system_cpu_ns=max(0, int(own.ru_stime * 1_000_000_000)),
        rusage_reaped_child_user_cpu_ns=max(
            0, int(reaped.ru_utime * 1_000_000_000)
        ),
        rusage_reaped_child_system_cpu_ns=max(
            0, int(reaped.ru_stime * 1_000_000_000)
        ),
        members=members,
    )


def _request_cpu_delta(
    before: ProcessCpuSnapshot,
    after: ProcessCpuSnapshot,
) -> tuple[tuple[int, int, int, int, int, int], bool]:
    cumulative_before = (
        before.rusage_self_user_cpu_ns,
        before.rusage_self_system_cpu_ns,
        before.rusage_reaped_child_user_cpu_ns,
        before.rusage_reaped_child_system_cpu_ns,
    )
    cumulative_after = (
        after.rusage_self_user_cpu_ns,
        after.rusage_self_system_cpu_ns,
        after.rusage_reaped_child_user_cpu_ns,
        after.rusage_reaped_child_system_cpu_ns,
    )
    contaminated = any(
        max(0, after_value - before_value)
        != after_value - before_value
        for before_value, after_value in zip(
            cumulative_before, cumulative_after, strict=True
        )
    )
    deltas = tuple(
        max(0, after_value - before_value)
        for before_value, after_value in zip(
            cumulative_before, cumulative_after, strict=True
        )
    )
    before_descendants = {
        (item.pid, item.create_time_ns): item for item in before.members[1:]
    }
    after_descendants = {
        (item.pid, item.create_time_ns): item for item in after.members[1:]
    }
    if set(before_descendants) - set(after_descendants):
        contaminated = True
    live_user_delta = 0
    live_system_delta = 0
    for identity, after_counter in after_descendants.items():
        before_counter = before_descendants.get(identity)
        before_user = before_counter.user_cpu_ns if before_counter else 0
        before_system = before_counter.system_cpu_ns if before_counter else 0
        if (
            after_counter.user_cpu_ns < before_user
            or after_counter.system_cpu_ns < before_system
        ):
            contaminated = True
        live_user_delta += max(0, after_counter.user_cpu_ns - before_user)
        live_system_delta += max(0, after_counter.system_cpu_ns - before_system)
    return (*deltas, live_user_delta, live_system_delta), contaminated


def _unbounded_rss_growth(request_rss: list[int]) -> bool:
    """Conservative repeated-tail leak signal; request one is warm-up noise."""

    if len(request_rss) < PRODUCTION_MINIMUM_REQUESTS:
        raise ValueError("RSS trend requires at least four repeated requests")
    tail = request_rss[1:]
    increase = tail[-1] - tail[0]
    large_endpoint_threshold = max(64 * 1024 * 1024, tail[0] // 10)
    sustained_threshold = max(4 * 1024 * 1024, tail[0] // 100)
    deltas = tuple(
        later - earlier for earlier, later in zip(tail, tail[1:], strict=False)
    )
    return bool(
        increase > large_endpoint_threshold
        or (all(delta > 0 for delta in deltas) and increase > sustained_threshold)
    )


def _settings_sha256(settings: object) -> str:
    return hashlib.sha256(
        json.dumps(
            asdict(settings),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _snapshot_sha256(snapshot: object) -> str:
    return _canonical_sha256(asdict(snapshot))


def _file_tree_identity_evidence(identity: object) -> FileTreeIdentityEvidence:
    return FileTreeIdentityEvidence(
        sha256=str(getattr(identity, "sha256")),
        metadata_sha256=str(getattr(identity, "metadata_sha256")),
        file_count=int(getattr(identity, "file_count")),
        aggregate_bytes=int(getattr(identity, "aggregate_bytes")),
    )


@contextmanager
def _artifact_lifecycle_boundary(
    path: Path,
) -> Iterator[dict[str, FileTreeIdentityEvidence | None]]:
    """Best-effort post-observe even when lifespan or request work raises."""

    from app.services.parser_worker import artifact_identity

    before = _file_tree_identity_evidence(artifact_identity(path))
    retained: dict[str, FileTreeIdentityEvidence | None] = {
        "before": before,
        "after": None,
    }
    try:
        yield retained
    finally:
        after = _file_tree_identity_evidence(artifact_identity(path))
        retained["after"] = after
        if after != before:
            raise RuntimeError("runtime artifact changed across the ASGI lifecycle")


def _predecessor_runtime_identity(settings: object) -> str:
    from app.services import pipeline

    cache = pipeline._converter_and_lock.cache_info()
    if cache.currsize == 0:
        return _canonical_sha256(
            {"mode": "predecessor_lazy", "pdf_converter": "uninitialized"}
        )
    classifier = pipeline._picture_classifier_model_available(
        settings.docling_artifacts_path
    )
    description = bool(
        settings.image_captioning_enabled
        and pipeline._picture_description_model_available(
            settings.docling_artifacts_path
        )
    )
    arguments = (
        tuple(settings.ocr_languages),
        settings.tesseract_cmd,
        settings.tesseract_data_path,
        settings.docling_artifacts_path,
        settings.document_timeout_seconds,
        classifier,
    )
    if description:
        converter, lock = pipeline._converter_and_lock(
            *arguments,
            describe_pictures=True,
            picture_description_prompt=settings.image_captioning_prompt,
        )
    else:
        converter, lock = pipeline._converter_and_lock(*arguments)
    records = []
    for input_format in tuple(converter.allowed_formats):
        option = converter.format_to_options[input_format]
        initialized = tuple(
            sorted(
                (
                    f"{pipeline_type.__module__}.{pipeline_type.__qualname__}",
                    options_hash,
                    f"{type(instance).__module__}.{type(instance).__qualname__}",
                )
                for (pipeline_type, options_hash), instance in (
                    converter.initialized_pipelines.items()
                )
            )
        )
        records.append(
            {
                "input_format": str(input_format),
                "option_type": f"{type(option).__module__}.{type(option).__qualname__}",
                "options": option.pipeline_options.model_dump(mode="json"),
                "initialized": initialized,
            }
        )
    return _canonical_sha256(
        {
            "mode": "predecessor_lazy",
            "cache_size": cache.currsize,
            "converter_type": f"{type(converter).__module__}.{type(converter).__qualname__}",
            "lock_is_owned_pipeline_lock": lock is pipeline._DOCLING_CONVERSION_LOCK,
            "records": records,
        }
    )


def _read_source(path: Path, identity: SourceIdentity) -> bytes:
    observed = path.lstat()
    if path.is_symlink() or not path.is_file():
        raise ValueError("source must be a non-symlink regular file")
    if observed.st_size != identity.size_bytes or not 0 < observed.st_size <= (
        MAXIMUM_SOURCE_BYTES
    ):
        raise ValueError("source size identity differs")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != identity.sha256:
        raise ValueError("source SHA-256 identity differs")
    return data


def execute_direct_rollback_attempt(
    *,
    workspace: Path,
    source_path: Path,
    source_identity: SourceIdentity,
    configuration: ConfigurationIdentity,
    mode: RunMode,
    expected_application_sha256: str,
    expected_dependency_manifest_sha256: str,
    expected_dependency_runtime_sha256: str,
    expected_parser_runtime_sha256: str,
    expected_runtime_artifacts_sha256: str,
    expected_harness_sha256: str,
    expected_network_isolation_sha256: str,
    phase_deadlines: _PhaseDeadlineClient,
) -> DirectRollbackRawWorkerEnvelope:
    """Exercise one exact brokerless flag-off ASGI request."""

    if (
        mode is not RunMode.PREDECESSOR
        or configuration.prewarm_enabled
        or configuration.request_count != 1
        or configuration.measurement_kind != "rollback_output_gate"
        or configuration.execution_topology != "direct-default-off-v1"
        or configuration.broker_evidence_capability != "absent"
        or configuration.broker_external_barriers_required
        or configuration.worker_fork_denial_required
    ):
        raise ValueError("direct rollback configuration differs")
    if any(
        name.startswith("PARSER_TESSERACT_")
        or name == "PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR"
        for name in os.environ
    ):
        raise ValueError("direct rollback inherited a private broker capability")

    source = _read_source(source_path, source_identity)
    cold = _resource_sample(ResourcePhase.COLD_INITIALIZATION)
    startup_started = time.monotonic_ns()

    import sitecustomize
    from app.config import get_settings
    from app.services.parser_worker import (
        PREWARM_RUNTIME_STATE_KEY,
        artifact_identity,
        dependency_identity,
    )

    guard = getattr(sitecustomize, "PHASE_LATENCY_NETWORK_GUARD", None)
    network_valid = bool(
        guard is not None
        and guard.bindings_exact
        and guard.denied_attempts == 0
        and exact_supplied_worker_environment_sha256(os.environ)
        == configuration.worker_environment_sha256
        and derive_production_network_isolation_sha256(workspace)
        == expected_network_isolation_sha256
    )
    settings = get_settings()
    configured_artifact_path = (
        Path(settings.docling_artifacts_path).resolve(strict=True)
        if settings.docling_artifacts_path is not None
        else None
    )
    settings_valid = bool(
        configured_artifact_path is not None
        and _canonical_sha256({"resolved_path": str(configured_artifact_path)})
        == configuration.artifacts_path_identity_sha256
        and settings.tesseract_cmd == configuration.tesseract_executable
        and settings.tesseract_data_path == configuration.tesseract_data_path
        and _settings_sha256(settings)
        == configuration.application_settings_sha256
    )
    application_valid = derive_candidate_code_sha256(workspace) == (
        expected_application_sha256
    )
    dependency_manifest_valid = derive_dependency_lock_sha256(workspace) == (
        expected_dependency_manifest_sha256
    )
    dependency_runtime_valid = dependency_identity(settings).sha256 == (
        expected_dependency_runtime_sha256
    )
    parser_runtime_valid = _file_sha256(Path(os.sys.executable)) == (
        expected_parser_runtime_sha256
    )
    harness_valid = derive_prewarm_harness_sha256(workspace) == (
        expected_harness_sha256
    )
    if configured_artifact_path is None:
        raise RuntimeError("direct rollback lacks a frozen artifact path")
    initial_artifact = _file_tree_identity_evidence(
        artifact_identity(configured_artifact_path)
    )
    artifact_valid = (
        initial_artifact.sha256 == expected_runtime_artifacts_sha256
    )
    if not all(
        (
            network_valid,
            settings_valid,
            application_valid,
            dependency_manifest_valid,
            dependency_runtime_valid,
            parser_runtime_valid,
            harness_valid,
            artifact_valid,
        )
    ):
        raise RuntimeError("direct rollback startup identity validation failed")

    from app.main import app as application
    from fastapi.testclient import TestClient

    artifact_before: FileTreeIdentityEvidence | None = None
    shutdown_started = 0
    with _artifact_lifecycle_boundary(
        configured_artifact_path
    ) as artifact_boundary, TestClient(application) as client:
        artifact_before = artifact_boundary["before"]
        if artifact_before is None or artifact_before != initial_artifact:
            raise RuntimeError("direct rollback artifact boundary differs")
        if getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None) is not None:
            raise RuntimeError("direct rollback unexpectedly started a parser runtime")
        startup_duration_ns = time.monotonic_ns() - startup_started
        if startup_duration_ns > int(configuration.startup_timeout_ns or 0):
            raise TimeoutError("direct rollback ASGI startup exceeded its bound")

        phase_deadlines.advance(
            "request", int(configuration.request_timeout_ns or 0)
        )
        request_started = time.monotonic_ns()
        response = client.post(
            "/v1/parse?output_format=json",
            files={
                "file": (
                    source_identity.filename,
                    source,
                    "application/pdf",
                )
            },
        )
        request_completed = time.monotonic_ns()
        raw_content_type = response.headers.get("content-type", "")
        response_media_type = raw_content_type.split(";", 1)[0].strip().casefold()
        if response.status_code != 200 or response_media_type != "application/json":
            raise RuntimeError("direct rollback ASGI request failed")
        output, witness = output_identity_and_witness_from_json(response.content)
        phase_deadlines.advance(
            "shutdown", int(configuration.shutdown_timeout_ns or 0)
        )
        shutdown_started = time.monotonic_ns()

    shutdown_duration_ns = time.monotonic_ns() - shutdown_started
    artifact_after = artifact_boundary["after"]
    if artifact_before is None or artifact_after is None:
        raise RuntimeError("direct rollback artifact lifecycle is incomplete")
    if getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None) is not None:
        raise RuntimeError("direct rollback retained a parser runtime after shutdown")
    shutdown = _resource_sample(ResourcePhase.SHUTDOWN)
    return direct_rollback_raw_worker_envelope(
        attempt_id=phase_deadlines.attempt_id,
        source=source_identity,
        configuration_sha256=configuration.sha256,
        output=output,
        normalized_output_witness=witness,
        response_content_type_sha256=hashlib.sha256(
            raw_content_type.encode("utf-8")
        ).hexdigest(),
        request_started_monotonic_ns=request_started,
        request_completed_monotonic_ns=request_completed,
        startup_duration_ns=startup_duration_ns,
        shutdown_duration_ns=shutdown_duration_ns,
        cold_resource=cold,
        shutdown_resource=shutdown,
        runtime_artifact_before_requests=artifact_before,
        runtime_artifact_after_shutdown=artifact_after,
        application_identity_validated=True,
        dependency_identity_validated=True,
        parser_runtime_identity_validated=True,
        runtime_artifact_identity_validated=True,
        configuration_identity_validated=True,
        network_isolation_validated=True,
    )


def execute_production_attempt(
    *,
    workspace: Path,
    source_path: Path,
    source_identity: SourceIdentity,
    configuration: ConfigurationIdentity,
    mode: RunMode,
    expected_application_sha256: str,
    expected_dependency_manifest_sha256: str,
    expected_dependency_runtime_sha256: str,
    expected_parser_runtime_sha256: str,
    expected_runtime_artifacts_sha256: str,
    expected_harness_sha256: str,
    expected_network_isolation_sha256: str,
    attempt_id: str,
) -> ProductionRawWorkerEnvelope:
    """Exercise one real application lifespan and repeated local requests."""

    if configuration.request_count is None or not (
        PRODUCTION_MINIMUM_REQUESTS
        <= configuration.request_count
        <= MAXIMUM_REQUEST_COUNT
    ) or configuration.measurement_kind != "paired_case":
        raise ValueError("production request count must be in [4, 32]")
    if configuration.prewarm_enabled != (mode is RunMode.ENABLED):
        raise ValueError("production mode/configuration binding differs")
    if (
        configuration.execution_topology
        != "fork-denied-worker-external-tesseract-broker-v1"
        or configuration.broker_evidence_capability != "private-harness-v1"
        or configuration.broker_external_barriers_required is not True
        or configuration.worker_fork_denial_required is not True
    ):
        raise ValueError("production attempt lacks the private broker topology")
    source = _read_source(source_path, source_identity)
    cold = _resource_sample(ResourcePhase.COLD_INITIALIZATION)
    startup_started = time.monotonic_ns()

    import sitecustomize
    from app.config import get_settings
    from app.services.parser_worker import (
        PREWARM_RUNTIME_STATE_KEY,
        WorkerState,
        dependency_identity,
    )

    guard = getattr(sitecustomize, "PHASE_LATENCY_NETWORK_GUARD", None)
    network_valid = bool(
        guard is not None
        and guard.bindings_exact
        and guard.denied_attempts == 0
        and exact_supplied_worker_environment_sha256(os.environ)
        == configuration.worker_environment_sha256
        and derive_production_network_isolation_sha256(workspace)
        == expected_network_isolation_sha256
    )
    settings = get_settings()
    configured_artifact_path = (
        Path(settings.docling_artifacts_path).resolve(strict=True)
        if settings.docling_artifacts_path is not None
        else None
    )
    settings_valid = bool(
        configured_artifact_path is not None
        and _canonical_sha256(
            {"resolved_path": str(configured_artifact_path)}
        )
        == configuration.artifacts_path_identity_sha256
        and settings.tesseract_cmd == configuration.tesseract_executable
        and settings.tesseract_data_path == configuration.tesseract_data_path
        and _settings_sha256(settings)
        == configuration.application_settings_sha256
    )
    application_valid = derive_candidate_code_sha256(workspace) == (
        expected_application_sha256
    )
    dependency_manifest_valid = derive_dependency_lock_sha256(workspace) == (
        expected_dependency_manifest_sha256
    )
    parser_runtime_valid = _file_sha256(Path(os.sys.executable)) == (
        expected_parser_runtime_sha256
    )
    harness_valid = derive_prewarm_harness_sha256(workspace) == (
        expected_harness_sha256
    )

    artifact_valid = False
    dependency_runtime_valid = False
    converter_valid = False
    runtime_before: str
    runtime_after_each_request: list[str] = []
    prewarmed_idle: ResourceSample | None = None
    observations: list[ProductionRawRequestObservation] = []
    fork_denial: WorkerForkDenialEvidence | None = None

    from app.main import app as application
    from fastapi.testclient import TestClient

    runtime: object | None = None
    artifact_before: FileTreeIdentityEvidence | None = None
    shutdown_started = 0
    if configured_artifact_path is None:
        raise RuntimeError("production worker lacks a frozen artifact path")
    with _artifact_lifecycle_boundary(
        configured_artifact_path
    ) as artifact_boundary, TestClient(application) as client:
        runtime = getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None)
        artifact_before = artifact_boundary["before"]
        assert artifact_before is not None
        if runtime is None:
            raise RuntimeError("brokered ASGI lifespan did not attach its runtime")
        ready = runtime.snapshot()
        if ready.state is not WorkerState.READY or ready.active_leases != 0:
            raise RuntimeError("brokered runtime was not atomically ready")
        fork_denial = WorkerForkDenialEvidence.model_validate(
            asdict(runtime.fork_denial_evidence())
        )
        if fork_denial.expected_request_count != configuration.request_count:
            raise RuntimeError("fork-denial request count differs")
        if mode is RunMode.ENABLED:
            artifact_valid = bool(
                artifact_before.sha256 == expected_runtime_artifacts_sha256
                and ready.artifacts_sha256 == artifact_before.sha256
                and ready.artifact_metadata_sha256
                == artifact_before.metadata_sha256
            )
            dependency_runtime_valid = ready.dependency_sha256 == (
                expected_dependency_runtime_sha256
            )
            converter_valid = bool(ready.converter_sha256)
            runtime_before = _snapshot_sha256(ready)
            prewarmed_idle = _resource_sample(ResourcePhase.PREWARMED_IDLE)
        else:
            if not bool(getattr(runtime, "instrument_only", False)):
                raise RuntimeError("predecessor lacks private lazy instrumentation")
            artifact_valid = (
                artifact_before.sha256 == expected_runtime_artifacts_sha256
            )
            dependency_runtime_valid = dependency_identity(settings).sha256 == (
                expected_dependency_runtime_sha256
            )
            runtime_before = _predecessor_runtime_identity(settings)

        identities_valid = all(
            (
                network_valid,
                settings_valid,
                application_valid,
                dependency_manifest_valid,
                parser_runtime_valid,
                harness_valid,
                artifact_valid,
                dependency_runtime_valid,
            )
        )
        if not identities_valid:
            raise RuntimeError("production startup identity validation failed")
        startup_duration_ns = time.monotonic_ns() - startup_started
        if startup_duration_ns > configuration.startup_timeout_ns:
            raise TimeoutError("production ASGI startup exceeded its bound")

        for request_index in range(1, configuration.request_count + 1):
            boundary_started = time.monotonic_ns()
            response = client.post(
                "/v1/parse?output_format=json",
                files={
                    "file": (
                        source_identity.filename,
                        source,
                        "application/pdf",
                    )
                },
            )
            boundary_ended = time.monotonic_ns()
            latency_ns = boundary_ended - boundary_started
            if latency_ns <= 0:
                raise RuntimeError("production ASGI request clock did not advance")
            if response.status_code != 200:
                raise RuntimeError("production ASGI request returned a non-200 status")
            raw_content_type = response.headers.get("content-type", "")
            response_media_type = raw_content_type.split(";", 1)[0].strip().casefold()
            if response_media_type != "application/json":
                raise RuntimeError("production ASGI response media type differs")
            output = output_identity_from_json(response.content)
            if mode is RunMode.ENABLED:
                current = runtime.snapshot()
                if current.state is not WorkerState.READY or current.active_leases != 0:
                    raise RuntimeError("enabled runtime did not return to ready/idle")
                runtime_identity = _snapshot_sha256(current)
                converter_sha256 = current.converter_sha256
            else:
                current = runtime.snapshot()
                if current.state is not WorkerState.READY or current.active_leases != 0:
                    raise RuntimeError("lazy runtime did not return to ready/idle")
                runtime_identity = _predecessor_runtime_identity(settings)
                converter_sha256 = None
            runtime_after_each_request.append(runtime_identity)
            receipt = runtime.last_broker_request_receipt()
            expected_request_id = (
                f"{attempt_id}-q{request_index:04d}"
            )
            if (
                receipt is None
                or receipt.request_id != expected_request_id
                or receipt.request_epoch != request_index + 1
                or receipt.request_sequence != request_index
                or receipt.request_binding is None
            ):
                raise RuntimeError("broker receipt/raw request binding differs")
            raw_observation = production_raw_request_observation(
                attempt_id=attempt_id,
                request_id=expected_request_id,
                request_index=request_index,
                request_epoch=request_index + 1,
                source=source_identity,
                client_post_started_monotonic_ns=boundary_started,
                client_post_completed_monotonic_ns=boundary_ended,
                client_post_elapsed_ns=latency_ns,
                response_content_type_sha256=hashlib.sha256(
                    raw_content_type.encode("utf-8")
                ).hexdigest(),
                response_body_sha256=hashlib.sha256(response.content).hexdigest(),
                asgi_response_witness_sha256=(
                    runtime.pending_asgi_response_witness() or {}
                ).get("record_sha256", ""),
                response_size_bytes=len(response.content),
                output=output,
                runtime_snapshot_sha256=runtime_identity,
                converter_sha256=converter_sha256,
                broker_request_receipt_sha256=receipt.receipt_sha256,
                request_binding_record_sha256=(
                    receipt.request_binding.record_sha256
                ),
                materialized_at_monotonic_ns=max(
                    boundary_ended, time.monotonic_ns()
                ),
            )
            runtime.publish_broker_request_result(
                raw_observation.model_dump(mode="json")
            )
            control_snapshot = runtime.request_control_snapshot()
            if (
                control_snapshot.completed_request_count != request_index
                or control_snapshot.state not in {"ready", "closed"}
            ):
                raise RuntimeError("request-control result ACK was not durable")
            observations.append(raw_observation)

        if mode is RunMode.PREDECESSOR:
            converter_valid = bool(runtime_after_each_request) and len(
                set(runtime_after_each_request)
            ) == 1
        runtime_after = runtime_after_each_request[-1]
        repeated = _resource_sample(ResourcePhase.REPEATED_REQUEST)
        shutdown_started = time.monotonic_ns()

    shutdown_duration_ns = time.monotonic_ns() - shutdown_started
    artifact_after = artifact_boundary["after"]
    if artifact_before is None or artifact_after != artifact_before:
        raise RuntimeError("runtime artifact changed across the ASGI lifecycle")
    startup_broker_receipt = _broker_receipt_mapping(
        runtime.startup_broker_receipt()
    )
    shutdown_broker_receipt = _broker_receipt_mapping(
        runtime.shutdown_broker_receipt()
    )
    if mode is RunMode.ENABLED:
        closed = runtime.snapshot()
        if closed.state is not WorkerState.CLOSED or closed.active_leases != 0:
            raise RuntimeError("enabled runtime did not close after ASGI shutdown")
        runtime_shutdown = _snapshot_sha256(closed)
    else:
        closed = runtime.snapshot()
        if closed.state is not WorkerState.CLOSED or closed.active_leases != 0:
            raise RuntimeError("lazy runtime did not close after ASGI shutdown")
        runtime_shutdown = _predecessor_runtime_identity(settings)
    request_control_final = runtime.request_control_snapshot()
    if (
        request_control_final.state != "closed"
        or request_control_final.completed_request_count != len(observations)
    ):
        raise RuntimeError("request-control lifecycle did not close")
    shutdown = _resource_sample(ResourcePhase.SHUTDOWN)
    output_signatures = {
        (
            item.output.normalized_sha256,
            item.output.semantic_sha256,
            item.output.api_contract_sha256,
            item.output.provenance_sha256,
            item.output.concerns_sha256,
            item.output.deterministic_ids_sha256,
        )
        for item in observations
        if item.output is not None
    }
    runtime_stable = len(set(runtime_after_each_request)) == 1
    if fork_denial is None:
        raise RuntimeError("fork-denial evidence disappeared")
    return production_raw_worker_envelope(
        case_id=source_identity.case_id,
        mode=mode,
        source=source_identity,
        startup_duration_ns=startup_duration_ns,
        shutdown_duration_ns=shutdown_duration_ns,
        application_identity_validated=application_valid and harness_valid,
        dependency_identity_validated=(
            dependency_manifest_valid and dependency_runtime_valid
        ),
        parser_runtime_identity_validated=parser_runtime_valid,
        runtime_artifact_identity_validated=artifact_valid,
        configuration_identity_validated=settings_valid,
        converter_identity_validated=converter_valid,
        ready_after_identity_validation=True,
        prewarm_completed=mode is RunMode.ENABLED,
        requests=tuple(observations),
        cold_resource=cold,
        prewarmed_idle_resource=prewarmed_idle,
        repeated_request_resource=repeated,
        shutdown_resource=shutdown,
        state_retention_detected=not (
            len(output_signatures) == 1 and runtime_stable
        ),
        production_asgi_lifespan_exercised=True,
        network_isolation_validated=network_valid and guard.denied_attempts == 0,
        runtime_before_requests_sha256=runtime_before,
        runtime_after_requests_sha256=runtime_after,
        runtime_after_shutdown_sha256=runtime_shutdown,
        runtime_artifact_before_requests=artifact_before,
        runtime_artifact_after_shutdown=artifact_after,
        startup_broker_receipt=startup_broker_receipt,
        startup_broker_receipt_sha256=startup_broker_receipt[
            "receipt_sha256"
        ],
        shutdown_broker_receipt=shutdown_broker_receipt,
        shutdown_broker_receipt_sha256=shutdown_broker_receipt[
            "receipt_sha256"
        ],
        fork_denial_evidence=fork_denial,
        request_control_completed_count=(
            request_control_final.completed_request_count
        ),
    )


def execute_cross_input_control(
    *,
    workspace: Path,
    source_a_path: Path,
    source_a: SourceIdentity,
    source_b_path: Path,
    source_b: SourceIdentity,
    configuration: ConfigurationIdentity,
    expected_application_sha256: str,
    expected_dependency_manifest_sha256: str,
    expected_dependency_runtime_sha256: str,
    expected_parser_runtime_sha256: str,
    expected_runtime_artifacts_sha256: str,
    expected_harness_sha256: str,
    expected_network_isolation_sha256: str,
    attempt_id: str,
) -> CrossInputRawWorkerEnvelope:
    """Run one real enabled A-B-A isolation sequence in a fresh lifespan."""

    if (
        not configuration.prewarm_enabled
        or configuration.measurement_kind != "cross_input_aba"
        or configuration.request_count != 3
    ):
        raise ValueError("cross-input isolation requires exact enabled A-B-A config")
    source_bytes = {
        source_a.case_id: _read_source(source_a_path, source_a),
        source_b.case_id: _read_source(source_b_path, source_b),
    }
    if source_a.case_id == source_b.case_id:
        raise ValueError("cross-input isolation sources must differ")
    cold = _resource_sample(ResourcePhase.COLD_INITIALIZATION)
    startup_started = time.monotonic_ns()

    import sitecustomize
    from app.config import get_settings
    from app.services.parser_worker import (
        PREWARM_RUNTIME_STATE_KEY,
        WorkerState,
    )

    guard = getattr(sitecustomize, "PHASE_LATENCY_NETWORK_GUARD", None)
    network_valid = bool(
        guard is not None
        and guard.bindings_exact
        and guard.denied_attempts == 0
        and exact_supplied_worker_environment_sha256(os.environ)
        == configuration.worker_environment_sha256
        and derive_production_network_isolation_sha256(workspace)
        == expected_network_isolation_sha256
    )
    settings = get_settings()
    configured_artifact_path = (
        Path(settings.docling_artifacts_path).resolve(strict=True)
        if settings.docling_artifacts_path is not None
        else None
    )
    if configured_artifact_path is None:
        raise RuntimeError("cross-input control lacks frozen artifacts")
    settings_valid = bool(
        _canonical_sha256({"resolved_path": str(configured_artifact_path)})
        == configuration.artifacts_path_identity_sha256
        and settings.tesseract_cmd == configuration.tesseract_executable
        and settings.tesseract_data_path == configuration.tesseract_data_path
        and _settings_sha256(settings) == configuration.application_settings_sha256
    )
    application_valid = (
        derive_candidate_code_sha256(workspace) == expected_application_sha256
    )
    dependency_manifest_valid = (
        derive_dependency_lock_sha256(workspace)
        == expected_dependency_manifest_sha256
    )
    parser_runtime_valid = (
        _file_sha256(Path(os.sys.executable)) == expected_parser_runtime_sha256
    )
    harness_valid = (
        derive_prewarm_harness_sha256(workspace) == expected_harness_sha256
    )

    from app.main import app as application
    from fastapi.testclient import TestClient

    observations: list[ProductionRawRequestObservation] = []
    artifact_before: FileTreeIdentityEvidence | None = None
    shutdown_started = 0
    runtime: object | None = None
    with _artifact_lifecycle_boundary(
        configured_artifact_path
    ) as artifact_boundary, TestClient(application) as client:
        artifact_before = artifact_boundary["before"]
        assert artifact_before is not None
        runtime = getattr(application.state, PREWARM_RUNTIME_STATE_KEY, None)
        if runtime is None:
            raise RuntimeError("cross-input enabled lifespan lacks runtime")
        ready = runtime.snapshot()
        artifact_valid = bool(
            artifact_before.sha256 == expected_runtime_artifacts_sha256
            and ready.artifacts_sha256 == artifact_before.sha256
            and ready.artifact_metadata_sha256 == artifact_before.metadata_sha256
        )
        dependency_valid = ready.dependency_sha256 == (
            expected_dependency_runtime_sha256
        )
        converter_valid = bool(ready.converter_sha256)
        if ready.state is not WorkerState.READY or ready.active_leases != 0:
            raise RuntimeError("cross-input runtime was not atomically ready")
        fork_denial = WorkerForkDenialEvidence.model_validate(
            asdict(runtime.fork_denial_evidence())
        )
        if fork_denial.expected_request_count != 3:
            raise RuntimeError("cross-input fork-denial request count differs")
        if not all(
            (
                network_valid,
                settings_valid,
                application_valid,
                dependency_manifest_valid,
                parser_runtime_valid,
                harness_valid,
                artifact_valid,
                dependency_valid,
                converter_valid,
            )
        ):
            raise RuntimeError("cross-input startup identity validation failed")
        startup_duration_ns = time.monotonic_ns() - startup_started
        if startup_duration_ns > int(configuration.startup_timeout_ns or 0):
            raise TimeoutError("cross-input ASGI startup exceeded its bound")
        for index, source in enumerate((source_a, source_b, source_a), start=1):
            started = time.monotonic_ns()
            response = client.post(
                "/v1/parse?output_format=json",
                files={
                    "file": (
                        source.filename,
                        source_bytes[source.case_id],
                        "application/pdf",
                    )
                },
            )
            completed = time.monotonic_ns()
            latency_ns = completed - started
            if latency_ns <= 0:
                raise RuntimeError("cross-input ASGI request clock did not advance")
            raw_content_type = response.headers.get("content-type", "")
            response_media_type = raw_content_type.split(";", 1)[0].strip().casefold()
            if response.status_code != 200 or response_media_type != "application/json":
                raise RuntimeError("cross-input request failed")
            current = runtime.snapshot()
            if (
                current.state is not WorkerState.READY
                or current.active_leases != 0
                or not current.converter_sha256
            ):
                raise RuntimeError("cross-input runtime did not return to ready")
            receipt = runtime.last_broker_request_receipt()
            expected_request_id = f"{attempt_id}-q{index:04d}"
            if (
                receipt is None
                or receipt.request_id != expected_request_id
                or receipt.request_epoch != index + 1
                or receipt.request_sequence != index
                or receipt.request_binding is None
            ):
                raise RuntimeError("cross-input broker receipt binding differs")
            raw_observation = production_raw_request_observation(
                attempt_id=attempt_id,
                request_id=expected_request_id,
                request_index=index,
                request_epoch=index + 1,
                source=source,
                client_post_started_monotonic_ns=started,
                client_post_completed_monotonic_ns=completed,
                client_post_elapsed_ns=latency_ns,
                response_content_type_sha256=hashlib.sha256(
                    raw_content_type.encode("utf-8")
                ).hexdigest(),
                response_body_sha256=hashlib.sha256(response.content).hexdigest(),
                asgi_response_witness_sha256=(
                    runtime.pending_asgi_response_witness() or {}
                ).get("record_sha256", ""),
                response_size_bytes=len(response.content),
                output=output_identity_from_json(response.content),
                runtime_snapshot_sha256=_snapshot_sha256(current),
                converter_sha256=current.converter_sha256,
                broker_request_receipt_sha256=receipt.receipt_sha256,
                request_binding_record_sha256=(
                    receipt.request_binding.record_sha256
                ),
                materialized_at_monotonic_ns=max(completed, time.monotonic_ns()),
            )
            runtime.publish_broker_request_result(
                raw_observation.model_dump(mode="json")
            )
            control_snapshot = runtime.request_control_snapshot()
            if (
                control_snapshot.completed_request_count != index
                or control_snapshot.state not in {"ready", "closed"}
            ):
                raise RuntimeError("cross-input result ACK was not durable")
            observations.append(raw_observation)
        shutdown_started = time.monotonic_ns()

    shutdown_duration_ns = time.monotonic_ns() - shutdown_started
    artifact_after = artifact_boundary["after"]
    if artifact_before is None or artifact_after is None:
        raise RuntimeError("cross-input artifact boundary is incomplete")
    startup_broker_receipt = _broker_receipt_mapping(
        runtime.startup_broker_receipt()
    )
    shutdown_broker_receipt = _broker_receipt_mapping(
        runtime.shutdown_broker_receipt()
    )
    closed = runtime.snapshot()
    runtime_closed = bool(
        closed.state is WorkerState.CLOSED and closed.active_leases == 0
    )
    request_control_final = runtime.request_control_snapshot()
    if (
        request_control_final.state != "closed"
        or request_control_final.completed_request_count != 3
    ):
        raise RuntimeError("cross-input request control did not close")
    shutdown = _resource_sample(ResourcePhase.SHUTDOWN)
    return cross_input_raw_worker_envelope(
        source_a=source_a,
        source_b=source_b,
        requests=tuple(observations),
        artifact_before_requests=artifact_before,
        artifact_after_shutdown=artifact_after,
        startup_duration_ns=startup_duration_ns,
        shutdown_duration_ns=shutdown_duration_ns,
        cold_resource=cold,
        shutdown_resource=shutdown,
        startup_broker_receipt=startup_broker_receipt,
        startup_broker_receipt_sha256=startup_broker_receipt[
            "receipt_sha256"
        ],
        shutdown_broker_receipt=shutdown_broker_receipt,
        shutdown_broker_receipt_sha256=shutdown_broker_receipt[
            "receipt_sha256"
        ],
        application_identity_validated=application_valid and harness_valid,
        dependency_identity_validated=(
            dependency_manifest_valid and dependency_valid
        ),
        parser_runtime_identity_validated=parser_runtime_valid,
        runtime_artifact_identity_validated=artifact_valid,
        configuration_identity_validated=settings_valid,
        converter_identity_validated=converter_valid,
        network_isolation_validated=(network_valid and guard.denied_attempts == 0),
        runtime_closed=runtime_closed,
        fork_denial_evidence=fork_denial,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-identity", required=True)
    parser.add_argument("--cross-input-secondary")
    parser.add_argument("--secondary-source-identity")
    parser.add_argument("--configuration", required=True)
    parser.add_argument("--mode", required=True, choices=tuple(RunMode))
    parser.add_argument("--application-sha256", required=True)
    parser.add_argument("--dependency-manifest-sha256", required=True)
    parser.add_argument("--dependency-runtime-sha256", required=True)
    parser.add_argument("--parser-runtime-sha256", required=True)
    parser.add_argument("--runtime-artifacts-sha256", required=True)
    parser.add_argument("--harness-sha256", required=True)
    parser.add_argument("--network-isolation-sha256", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--controller-pid", required=True, type=int)
    parser.add_argument("--controller-create-time-ns", required=True, type=int)
    parser.add_argument("--controller-pgid", required=True, type=int)
    parser.add_argument("--controller-sid", required=True, type=int)
    parser.add_argument(
        "--absolute-deadline-monotonic-ns", required=True, type=int
    )
    parser.add_argument("--controller-release-fd", required=True, type=int)
    parser.add_argument("--prebind-fatal", required=True)
    parser.add_argument("--phase-control")
    parser.add_argument("--phase-ack")
    return parser


def _load_canonical_model(path: Path, model: type[Any], maximum: int) -> Any:
    raw = path.read_bytes()
    if not raw or len(raw) > maximum:
        raise ValueError("worker input contract is empty or oversized")
    value = model.model_validate_json(raw)
    if canonical_model_bytes(value) != raw:
        raise ValueError("worker input contract is not canonical JSON")
    return value


def _bind_worker_phase_authority(
    *,
    configuration: ConfigurationIdentity,
    phase_control_argument: str | None,
    phase_ack_argument: str | None,
    attempt_id: str,
    absolute_deadline_monotonic_ns: int,
    socket_resolver: Callable[[], Any] | None = None,
) -> _PhaseDeadlineClient | None:
    """Bind exactly one phase writer for the selected execution topology."""

    arguments_paired = bool(phase_control_argument) == bool(phase_ack_argument)
    direct_rollback = configuration.measurement_kind == "rollback_output_gate"
    if (
        not arguments_paired
        or direct_rollback
        != (configuration.execution_topology == "direct-default-off-v1")
    ):
        raise ValueError("worker phase authority arguments differ")
    if direct_rollback:
        if not phase_control_argument or not phase_ack_argument:
            raise ValueError("direct rollback requires file phase authority")
        phase_control_path = Path(phase_control_argument)
        phase_ack_path = Path(phase_ack_argument)
        if (
            not phase_control_path.is_absolute()
            or not phase_ack_path.is_absolute()
            or phase_control_path.parent != phase_ack_path.parent
            or phase_control_path.parent
            != phase_control_path.parent.resolve(strict=True)
        ):
            raise ValueError("worker phase control paths differ")
        phase_deadlines = _PhaseDeadlineClient(
            root=phase_control_path.parent,
            control_path=phase_control_path,
            ack_path=phase_ack_path,
            attempt_id=attempt_id,
            whole_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
        )
        phase_deadlines.bind_initial_startup()
        return phase_deadlines
    if phase_control_argument is not None or phase_ack_argument is not None:
        raise ValueError("brokered worker forbids file phase authority")
    if socket_resolver is None:
        from app.services.parser_phase_control import (
            require_parser_phase_control,
        )

        socket_resolver = require_parser_phase_control
    socket_authority = socket_resolver()
    snapshot = socket_authority.snapshot()
    if (
        socket_authority.attempt_id != attempt_id
        or socket_authority.deadline_ns != absolute_deadline_monotonic_ns
        or snapshot.phase_record.attempt_id != attempt_id
        or snapshot.phase_record.phase != "startup"
        or snapshot.phase_record.sequence != 1
        or snapshot.phase_ack.sequence != 1
        or snapshot.phase_ack.phase_record_sha256
        != snapshot.phase_record.record_sha256
        or snapshot.phase_ack.observed_monotonic_ns
        >= snapshot.phase_record.deadline_monotonic_ns
        or time.monotonic_ns() >= snapshot.phase_record.deadline_monotonic_ns
    ):
        raise RuntimeError("brokered socket phase authority differs")
    return None


def main() -> int:
    args = _parser().parse_args()
    _await_controller_release(
        attempt_id=args.attempt_id,
        controller_pid=args.controller_pid,
        controller_create_time_ns=args.controller_create_time_ns,
        controller_pgid=args.controller_pgid,
        controller_sid=args.controller_sid,
        absolute_deadline_monotonic_ns=args.absolute_deadline_monotonic_ns,
        release_fd=args.controller_release_fd,
        fatal_path=Path(args.prebind_fatal),
    )
    source = _load_canonical_model(
        Path(args.source_identity), SourceIdentity, 64 * 1024
    )
    configuration = _load_canonical_model(
        Path(args.configuration), ConfigurationIdentity, 64 * 1024
    )
    phase_deadlines = _bind_worker_phase_authority(
        configuration=configuration,
        phase_control_argument=args.phase_control,
        phase_ack_argument=args.phase_ack,
        attempt_id=args.attempt_id,
        absolute_deadline_monotonic_ns=args.absolute_deadline_monotonic_ns,
    )
    common = {
        "workspace": Path(args.workspace).resolve(),
        "configuration": configuration,
        "expected_application_sha256": args.application_sha256,
        "expected_dependency_manifest_sha256": args.dependency_manifest_sha256,
        "expected_dependency_runtime_sha256": args.dependency_runtime_sha256,
        "expected_parser_runtime_sha256": args.parser_runtime_sha256,
        "expected_runtime_artifacts_sha256": args.runtime_artifacts_sha256,
        "expected_harness_sha256": args.harness_sha256,
        "expected_network_isolation_sha256": args.network_isolation_sha256,
    }
    if bool(args.cross_input_secondary) != bool(args.secondary_source_identity):
        raise ValueError("cross-input secondary arguments must be paired")
    if args.cross_input_secondary:
        if RunMode(args.mode) is not RunMode.ENABLED:
            raise ValueError("cross-input control must launch enabled mode")
        secondary = _load_canonical_model(
            Path(args.secondary_source_identity), SourceIdentity, 64 * 1024
        )
        envelope = execute_cross_input_control(
            source_a_path=Path(args.source).resolve(),
            source_a=source,
            source_b_path=Path(args.cross_input_secondary).resolve(),
            source_b=secondary,
            attempt_id=args.attempt_id,
            **common,
        )
    elif configuration.measurement_kind == "rollback_output_gate":
        if phase_deadlines is None:
            raise RuntimeError("direct rollback file phase authority is absent")
        envelope = execute_direct_rollback_attempt(
            source_path=Path(args.source).resolve(),
            source_identity=source,
            mode=RunMode(args.mode),
            phase_deadlines=phase_deadlines,
            **common,
        )
    else:
        envelope = execute_production_attempt(
            source_path=Path(args.source).resolve(),
            source_identity=source,
            mode=RunMode(args.mode),
            attempt_id=args.attempt_id,
            **common,
        )
    os.sys.stdout.buffer.write(canonical_model_bytes(envelope))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
