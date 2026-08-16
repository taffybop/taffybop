"""Closed local-evidence contracts for LAT-US02 worker prewarming.

This module is test/reporting infrastructure only.  It does not import the
application and cannot invoke a hosted parser.  Numerical RSS is deliberately
retained as owner-deferred observational evidence for LAT-US02; cleanup,
leakage, OOM, unbounded growth, orphan, and cross-request-state failures remain
blocking and are evaluated independently.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import signal
import socket
import stat
import struct
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import ceil
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    create_model,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0"
MINIMUM_LOCAL_REPETITIONS = 2
MAXIMUM_ATTEMPTS = 512
MAXIMUM_REQUESTS_PER_ATTEMPT = 32
REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES = 32 * 1024 * 1024
REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BASE64_CHARACTERS = (
    (REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES + 2) // 3
) * 4
MAXIMUM_CONTROLLER_RESOURCE_SAMPLES = 8_192
MAXIMUM_CONTROLLER_RESOURCE_SAMPLE_LOG_BYTES = 16_777_216
MAXIMUM_CHILD_WATCH_LOG_BYTES = 4_194_304
MAXIMUM_OUTPUT_BYTES = 67_108_864
PRODUCTION_MINIMUM_REQUESTS = 4
PEAK_SAMPLE_TARGET_INTERVAL_NS = 10_000_000
PEAK_SAMPLE_MAXIMUM_GAP_NS = 100_000_000
PEAK_SAMPLE_EDGE_TOLERANCE_NS = 50_000_000
RSS_DISPOSITION = "owner_deferred_observational"
PREWARM_FEATURE_FLAG = "parser.latency.prewarm.enabled"
PRODUCTION_CASE_IDS = (
    "catastrophe-recap",
    "clean-energy",
    "clinical-study",
    "component-datasheet",
    "egov-survey",
    "esg-metrics",
    "finance-10k",
    "health-report",
    "insurance-acord",
    "manufacturing-report",
    "ny-timetable",
    "postal-10k",
    "purchase-agreement",
    "settlement-agreement",
    "uber-earnings",
)
PREWARM_HARNESS_PATHS = (
    "tests/benchmarks/latency_prewarm_contracts.py",
    "tests/benchmarks/latency_prewarm_worker.py",
    "tests/benchmarks/latency_prewarm_runner.py",
    "tests/benchmarks/latency_prewarm_production_worker.py",
    "tests/benchmarks/latency_prewarm_production_runner.py",
    "tests/benchmarks/latency_prewarm_cpu.py",
    "tests/benchmarks/latency_watchdog.py",
    "tests/benchmarks/latency_prewarm_watchdog.py",
    "tests/benchmarks/latency_isolation.py",
    "tests/benchmarks/latency_child_guard/sitecustomize.py",
    "tests/benchmarks/latency_profile_set.py",
    "tests/contract/test_lat_us02_worker_prewarm_contract.py",
    "tests/stories/phase_latency/test_lat_us02_worker_prewarm.py",
    "tests/performance/test_lat_us02_cpu_v2_contract.py",
    "tests/performance/test_lat_us02_native_cpu_counter.py",
    "tests/performance/test_lat_us02_production_adapter_contract.py",
    "tests/performance/test_lat_us02_rollback_contract.py",
)
LIFECYCLE_CLEANUP_TEST_PATHS = (
    "tests/contract/test_lat_us02_worker_prewarm_contract.py",
    "tests/stories/phase_latency/test_lat_us02_worker_prewarm.py",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[a-z0-9]+(?:[a-z0-9._-]*[a-z0-9])?$")

Sha256 = Annotated[str, Field(pattern=_SHA256.pattern)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
StableId = Annotated[str, Field(min_length=1, max_length=128)]


class ContractModel(BaseModel):
    """Immutable, finite, and closed evidence base model."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _stable_id(value: str, *, label: str) -> str:
    if not _STABLE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a stable lowercase identifier")
    return value


def _portable_path(value: str) -> str:
    path = PurePosixPath(value)
    parts = value.split("/")
    if (
        not value
        or value != value.strip()
        or "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in parts)
        or parts[0].startswith("~")
        or ":" in parts[0]
        or any(ord(char) < 0x20 or ord(char) > 0x7E for char in value)
    ):
        raise ValueError("path must be canonical workspace-relative POSIX text")
    return value


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be UTC")
    return value.astimezone(UTC)


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _semantic_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _output_projection_hash(
    value: object,
    *,
    projection: Literal["provenance", "concerns", "deterministic_ids"],
) -> str:
    records: list[dict[str, object]] = []

    def selected(key: str) -> bool:
        if projection == "provenance":
            return (
                "source" in key
                or "evidence" in key
                or "provenance" in key
                or key in {"bbox", "confidence", "engine", "ocr_engine"}
            )
        if projection == "concerns":
            return (
                "concern" in key
                or "warning" in key
                or key in {"status", "success"}
            )
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

    def visit(member: object, path: tuple[str, ...]) -> None:
        if type(member) is dict:
            for key in sorted(member):
                if type(key) is not str:
                    raise ValueError("normalized ParseResult has a non-string key")
                child = member[key]
                child_path = (*path, key)
                if selected(key):
                    records.append({"path": list(child_path), "value": child})
                else:
                    visit(child, child_path)
        elif type(member) is list:
            for index, child in enumerate(member):
                visit(child, (*path, str(index)))

    visit(value, ())
    return _canonical_hash(records)


def derive_prewarm_harness_sha256(workspace: Path) -> str:
    """Hash every executable evidence component in canonical path order."""

    root = workspace.resolve()
    records: list[dict[str, object]] = []
    for relative in PREWARM_HARNESS_PATHS:
        path = root / _portable_path(relative)
        resolved = path.resolve(strict=True)
        if resolved.relative_to(root).as_posix() != relative or path.is_symlink():
            raise ValueError("prewarm harness path escaped frozen custody")
        data = resolved.read_bytes()
        if not data or len(data) > 2 * 1024 * 1024:
            raise ValueError("prewarm harness file is empty or oversized")
        records.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return _canonical_hash(records)


def derive_lifecycle_cleanup_tests_sha256(workspace: Path) -> str:
    """Bind the direct lifecycle thread/FD/orphan cleanup test authority."""

    root = workspace.resolve()
    records = []
    for relative in LIFECYCLE_CLEANUP_TEST_PATHS:
        path = root / _portable_path(relative)
        resolved = path.resolve(strict=True)
        if resolved.relative_to(root).as_posix() != relative or path.is_symlink():
            raise ValueError("lifecycle cleanup test escaped frozen custody")
        data = resolved.read_bytes()
        if not data or len(data) > 2 * 1024 * 1024:
            raise ValueError("lifecycle cleanup test is empty or oversized")
        records.append(
            {
                "path": relative,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return _canonical_hash(records)


class RunMode(StrEnum):
    PREDECESSOR = "predecessor_lazy"
    ENABLED = "prewarm_enabled"


class AttemptStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FailureCode(StrEnum):
    STARTUP_TIMEOUT = "startup_timeout"
    STARTUP_CANCELLED = "startup_cancelled"
    DEPENDENCY_MISMATCH = "dependency_mismatch"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_CORRUPT = "artifact_corrupt"
    IDENTITY_VALIDATION_FAILED = "identity_validation_failed"
    REQUEST_FAILED = "request_failed"
    WORKER_PROTOCOL_FAILED = "worker_protocol_failed"
    WORKER_OOM = "worker_oom"
    UNBOUNDED_RSS_GROWTH = "unbounded_rss_growth"
    ORPHANED_PROCESS = "orphaned_process"
    CLEANUP_FAILED = "cleanup_failed"
    THREAD_LEAK = "thread_leak"
    FILE_DESCRIPTOR_LEAK = "file_descriptor_leak"
    CROSS_REQUEST_STATE_RETAINED = "cross_request_state_retained"


class EvaluationFailureCode(StrEnum):
    ATTEMPT_FAILED = "attempt_failed"
    IDENTITY_VALIDATION_FAILED = "identity_validation_failed"
    WORKER_BECAME_READY_EARLY = "worker_became_ready_early"
    SOURCE_IDENTITY_MISMATCH = "source_identity_mismatch"
    EXECUTION_IDENTITY_MISMATCH = "execution_identity_mismatch"
    CONFIGURATION_PAIR_MISMATCH = "configuration_pair_mismatch"
    OUTPUT_BYTE_PARITY_FAILED = "output_byte_parity_failed"
    OUTPUT_SEMANTIC_PARITY_FAILED = "output_semantic_parity_failed"
    API_CONTRACT_PARITY_FAILED = "api_contract_parity_failed"
    PROVENANCE_PARITY_FAILED = "provenance_parity_failed"
    CONCERNS_PARITY_FAILED = "concerns_parity_failed"
    DETERMINISTIC_ID_PARITY_FAILED = "deterministic_id_parity_failed"
    NETWORK_ISOLATION_FAILED = "network_isolation_failed"
    PRODUCTION_LIFESPAN_NOT_EXERCISED = "production_lifespan_not_exercised"
    RUNTIME_ARTIFACT_BOUNDARY_FAILED = "runtime_artifact_boundary_failed"
    FORK_DENIAL_FAILED = "fork_denial_failed"
    BROKER_CUSTODY_FAILED = "broker_custody_failed"
    REQUEST_CPU_BOUNDARY_FAILED = "request_cpu_boundary_failed"
    DESCENDANT_SAMPLING_FAILED = "descendant_sampling_failed"
    OWNED_PROCESS_GROUP_MISMATCH = "owned_process_group_mismatch"
    OUTPUT_SIZE_EXCEEDED = "output_size_exceeded"
    R34_ARTIFACT_SCOPE_INCOMPARABLE = "r34_artifact_scope_incomparable"
    CURRENT_RUNTIME_OUTPUT_IDENTITY_MISMATCH = (
        "current_runtime_output_identity_mismatch"
    )
    ROLLBACK_OUTPUT_GATE_FAILED = "rollback_output_gate_failed"
    CROSS_INPUT_ISOLATION_FAILED = "cross_input_isolation_failed"
    LATENCY_REGRESSION = "latency_regression"
    CLEANUP_FAILED = "cleanup_failed"
    ORPHANED_PROCESS = "orphaned_process"
    THREAD_LEAK = "thread_leak"
    FILE_DESCRIPTOR_LEAK = "file_descriptor_leak"
    WORKER_OOM = "worker_oom"
    UNBOUNDED_RSS_GROWTH = "unbounded_rss_growth"
    CROSS_REQUEST_STATE_RETAINED = "cross_request_state_retained"
    RETAINED_RECEIPT_CUSTODY_FAILED = "retained_receipt_custody_failed"


class ResourcePhase(StrEnum):
    COLD_INITIALIZATION = "cold_initialization"
    PREWARMED_IDLE = "prewarmed_idle"
    REQUEST_PEAK = "request_peak"
    REPEATED_REQUEST = "repeated_request"
    SHUTDOWN = "shutdown"


class ArtifactIdentity(ContractModel):
    path: str
    sha256: Sha256
    size_bytes: PositiveInt

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _portable_path(value)


class FileTreeIdentityEvidence(ContractModel):
    """Full content and metadata identity retained around production requests."""

    sha256: Sha256
    metadata_sha256: Sha256
    file_count: PositiveInt
    aggregate_bytes: PositiveInt


class ImmutableRuntimeInputRootAuthority(ContractModel):
    """One held immutable tree or individual native-image authority."""

    role: Annotated[str, Field(pattern=r"^[a-z0-9_:-]{1,128}$")]
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True)]
    inode: NonNegativeInt
    kind: Literal["directory", "file"]
    content_manifest_sha256: Sha256
    file_count: NonNegativeInt
    aggregate_bytes: NonNegativeInt

    @model_validator(mode="after")
    def validate_root_authority(self) -> "ImmutableRuntimeInputRootAuthority":
        path = PurePosixPath(self.resolved_path)
        if (
            not path.is_absolute()
            or self.resolved_path == "/"
            or "\x00" in self.resolved_path
            or "\n" in self.resolved_path
            or ".." in path.parts
            or (self.kind == "file" and self.file_count != 1)
        ):
            raise ValueError("immutable runtime input root authority differs")
        return self


class ImmutableRuntimeInputPathIdentity(ContractModel):
    role: Annotated[str, Field(pattern=r"^[a-z0-9_:-]{1,128}$")]
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True)]
    inode: NonNegativeInt
    kind: Literal["directory", "file"]


class ImmutableRuntimeInputEntry(ContractModel):
    """One canonical held-vnode entry retained by the custody producer."""

    role: Annotated[str, Field(pattern=r"^[a-z0-9_:-]{1,128}$")]
    root: Annotated[str, Field(min_length=1, max_length=4_096)]
    vnode_filter_registered_at_monotonic_ns: PositiveInt
    relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    kind: Literal["directory", "file"]
    device: Annotated[int, Field(strict=True)]
    inode: NonNegativeInt
    mode: NonNegativeInt
    uid: NonNegativeInt
    gid: NonNegativeInt
    nlink: NonNegativeInt
    size_bytes: NonNegativeInt
    content_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_entry(self) -> "ImmutableRuntimeInputEntry":
        root = PurePosixPath(self.root)
        relative = PurePosixPath(self.relative_path)
        if (
            not root.is_absolute()
            or self.root == "/"
            or "\x00" in self.root
            or "\n" in self.root
            or "\x00" in self.relative_path
            or "\n" in self.relative_path
            or ".." in relative.parts
            or (self.relative_path.startswith("/") and self.relative_path != ".")
            or (self.kind == "file") != (self.content_sha256 is not None)
        ):
            raise ValueError("immutable runtime input entry differs")
        return self


class ImmutableRuntimeInputDirectoryMember(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    kind: Literal["directory", "file"]
    device: Annotated[int, Field(strict=True)]
    inode: NonNegativeInt

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\x00" in value:
            raise ValueError("immutable directory member name differs")
        return value


class ImmutableRuntimeInputDirectoryMembership(ContractModel):
    role: Annotated[str, Field(pattern=r"^[a-z0-9_:-]{1,128}$")]
    root: Annotated[str, Field(min_length=1, max_length=4_096)]
    relative_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    device: Annotated[int, Field(strict=True)]
    inode: NonNegativeInt
    members: Annotated[
        tuple[ImmutableRuntimeInputDirectoryMember, ...],
        Field(max_length=4_096),
    ]

    @model_validator(mode="after")
    def validate_membership(self) -> "ImmutableRuntimeInputDirectoryMembership":
        names = tuple(item.name for item in self.members)
        if names != tuple(sorted(names)) or len(set(names)) != len(names):
            raise ValueError("immutable directory membership order differs")
        return self


class ImmutableRuntimeInputCustodyEvidence(ContractModel):
    """Continuous held-vnode custody from pre-release through terminal reap."""

    schema_id: Literal["parser-darwin-immutable-tree-custody-v1"]
    attempt_id: Annotated[str, Field(min_length=1, max_length=256)]
    event_authority: Literal["darwin-kqueue-EVFILT_VNODE-held-fd-v1"]
    monitored_note_flags: tuple[
        Literal["WRITE"],
        Literal["EXTEND"],
        Literal["ATTRIB"],
        Literal["LINK"],
        Literal["RENAME"],
        Literal["DELETE"],
        Literal["REVOKE"],
    ]
    armed_at_monotonic_ns: PositiveInt
    completed_at_monotonic_ns: PositiveInt
    maximum_entries: Literal[4_096]
    maximum_bytes: Literal[17_179_869_184]
    entry_count: PositiveInt
    aggregate_file_bytes: NonNegativeInt
    root_authorities: Annotated[
        tuple[ImmutableRuntimeInputRootAuthority, ...],
        Field(min_length=3, max_length=512),
    ]
    root_path_identities_before: Annotated[
        tuple[ImmutableRuntimeInputPathIdentity, ...],
        Field(min_length=3, max_length=512),
    ]
    root_path_identities_after: Annotated[
        tuple[ImmutableRuntimeInputPathIdentity, ...],
        Field(min_length=3, max_length=512),
    ]
    entry_projection: Annotated[
        tuple[ImmutableRuntimeInputEntry, ...],
        Field(min_length=3, max_length=4_096),
    ]
    directory_membership_projection: Annotated[
        tuple[ImmutableRuntimeInputDirectoryMembership, ...],
        Field(min_length=3, max_length=4_096),
    ]
    initial_projection_sha256: Sha256
    final_projection_sha256: Sha256
    event_count: Literal[0]
    events: tuple[()] = ()
    root_paths_stable: Literal[True]
    held_vnodes_unchanged: Literal[True]
    no_relevant_vnode_events: Literal[True]
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_input_custody(self) -> "ImmutableRuntimeInputCustodyEvidence":
        before = tuple(
            (
                item.role,
                item.resolved_path,
                item.device,
                item.inode,
                item.kind,
            )
            for item in self.root_path_identities_before
        )
        after = tuple(
            (
                item.role,
                item.resolved_path,
                item.device,
                item.inode,
                item.kind,
            )
            for item in self.root_path_identities_after
        )
        authorities = tuple(
            (
                item.role,
                item.resolved_path,
                item.device,
                item.inode,
                item.kind,
            )
            for item in self.root_authorities
        )
        entry_projection = tuple(
            item.model_dump(mode="json") for item in self.entry_projection
        )
        entry_projection_sha256 = _canonical_hash(entry_projection)
        entry_keys = tuple(
            (item.role, item.root, item.relative_path)
            for item in self.entry_projection
        )
        authority_by_role = {
            item.role: item for item in self.root_authorities
        }
        root_entries = {
            (item.role, item.root): item
            for item in self.entry_projection
            if item.relative_path == "."
        }
        root_manifests_match = True
        for role, authority in authority_by_role.items():
            files = tuple(
                sorted(
                    (
                        item
                        for item in self.entry_projection
                        if item.role == role and item.kind == "file"
                    ),
                    key=lambda item: item.relative_path,
                )
            )
            records = tuple(
                {
                    "path": item.relative_path,
                    "sha256": item.content_sha256,
                    "size_bytes": item.size_bytes,
                }
                for item in files
            )
            root_entry = root_entries.get((role, authority.resolved_path))
            root_manifests_match = root_manifests_match and (
                root_entry is not None
                and root_entry.device == authority.device
                and root_entry.inode == authority.inode
                and root_entry.kind == authority.kind
                and authority.content_manifest_sha256
                == _canonical_hash(records)
                and authority.file_count == len(records)
                and authority.aggregate_bytes
                == sum(item.size_bytes for item in files)
            )
        membership_by_key = {
            (item.role, item.root, item.relative_path): item
            for item in self.directory_membership_projection
        }
        expected_membership: dict[
            tuple[str, str, str], list[ImmutableRuntimeInputDirectoryMember]
        ] = {}
        for item in self.entry_projection:
            if item.relative_path == "." or item.relative_path.startswith(
                "@ancestor/"
            ):
                continue
            parent = (
                "."
                if "/" not in item.relative_path
                else item.relative_path.rsplit("/", 1)[0]
            )
            expected_membership.setdefault(
                (item.role, item.root, parent), []
            ).append(
                ImmutableRuntimeInputDirectoryMember(
                    name=item.relative_path.rsplit("/", 1)[-1],
                    kind=item.kind,
                    device=item.device,
                    inode=item.inode,
                )
            )
        directory_entries = tuple(
            item
            for item in self.entry_projection
            if item.kind == "directory"
            and not item.relative_path.startswith("@ancestor/")
        )
        membership_matches = (
            len(membership_by_key)
            == len(self.directory_membership_projection)
            == len(directory_entries)
        )
        for directory in directory_entries:
            key = (
                directory.role,
                directory.root,
                directory.relative_path,
            )
            retained = membership_by_key.get(key)
            expected = tuple(
                sorted(
                    expected_membership.get(key, []),
                    key=lambda item: item.name,
                )
            )
            membership_matches = membership_matches and (
                retained is not None
                and retained.device == directory.device
                and retained.inode == directory.inode
                and retained.members == expected
            )
        if (
            self.completed_at_monotonic_ns < self.armed_at_monotonic_ns
            or any(
                item.vnode_filter_registered_at_monotonic_ns
                > self.armed_at_monotonic_ns
                for item in self.entry_projection
            )
            or self.initial_projection_sha256 != entry_projection_sha256
            or self.final_projection_sha256 != entry_projection_sha256
            or before != after
            or before != authorities
            or tuple(item.role for item in self.root_authorities)
            != tuple(sorted(item.role for item in self.root_authorities))
            or len(set(before)) != len(before)
            or len(set(entry_keys)) != len(entry_keys)
            or not root_manifests_match
            or not membership_matches
            or self.entry_count != len(self.entry_projection)
            or self.aggregate_file_bytes
            != sum(
                item.size_bytes
                for item in self.entry_projection
                if item.kind == "file"
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("immutable runtime input custody differs")
        return self


class SourceIdentity(ArtifactIdentity):
    case_id: StableId
    filename: str
    page_count: PositiveInt

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _stable_id(value, label="case_id")

    @model_validator(mode="after")
    def validate_filename(self) -> "SourceIdentity":
        if self.filename != PurePosixPath(self.path).name:
            raise ValueError("source filename must equal the path basename")
        return self


class RuntimeArtifactSetIdentity(ContractModel):
    artifacts: Annotated[tuple[ArtifactIdentity, ...], Field(min_length=1, max_length=512)]
    aggregate_sha256: Sha256

    @model_validator(mode="after")
    def validate_artifacts(self) -> "RuntimeArtifactSetIdentity":
        paths = tuple(item.path for item in self.artifacts)
        if paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
            raise ValueError("runtime artifacts must be unique and path-sorted")
        expected = _canonical_hash(
            [item.model_dump(mode="json") for item in self.artifacts]
        )
        if self.aggregate_sha256 != expected:
            raise ValueError("runtime artifact aggregate identity differs")
        return self


def runtime_artifact_set(
    artifacts: tuple[ArtifactIdentity, ...],
) -> RuntimeArtifactSetIdentity:
    ordered = tuple(sorted(artifacts, key=lambda item: item.path))
    return RuntimeArtifactSetIdentity(
        artifacts=ordered,
        aggregate_sha256=_canonical_hash(
            [item.model_dump(mode="json") for item in ordered]
        ),
    )


class DependencyRuntimeIdentity(ContractModel):
    """Observed local parser dependency closure from the production validator."""

    sha256: Sha256
    distribution_count: PositiveInt
    verified_file_count: PositiveInt
    verified_aggregate_bytes: PositiveInt
    tesseract_version: Annotated[str, Field(min_length=1, max_length=512)]
    language_count: PositiveInt


class ExecutionIdentity(ContractModel):
    application_code_sha256: Sha256
    dependency_manifest_sha256: Sha256
    dependency_runtime_sha256: Sha256 | None = None
    dependency_runtime: DependencyRuntimeIdentity | None = None
    parser_runtime_sha256: Sha256
    runtime_artifacts: RuntimeArtifactSetIdentity
    harness_sha256: Sha256
    lifecycle_cleanup_tests_sha256: Sha256 | None = None
    network_isolation_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_dependency_runtime(self) -> "ExecutionIdentity":
        if (self.dependency_runtime_sha256 is None) != (
            self.dependency_runtime is None
        ):
            raise ValueError("dependency runtime detail/hash custody differs")
        if (
            self.dependency_runtime is not None
            and self.dependency_runtime.sha256 != self.dependency_runtime_sha256
        ):
            raise ValueError("dependency runtime detail identity differs")
        return self


PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS = (
    "parser_latency_prewarm_artifacts_sha256",
    "parser_latency_prewarm_dependency_sha256",
    "parser_latency_prewarm_enabled",
)
PAIRING_SETTINGS_FIXED_INSTRUMENTATION_KEYS = (
    "parser_latency_prewarm_shutdown_grace_seconds",
    "parser_latency_prewarm_timeout_seconds",
)
PAIRING_SETTINGS_DYNAMIC_CAPABILITY_KEYS: tuple[str, ...] = ()
PAIRING_SETTINGS_INSTRUMENTATION_KEYS = tuple(
    sorted(
        {
            *PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS,
            *PAIRING_SETTINGS_FIXED_INSTRUMENTATION_KEYS,
            *PAIRING_SETTINGS_DYNAMIC_CAPABILITY_KEYS,
        }
    )
)
PAIRING_APPLICATION_SETTINGS_KEYS = (
    "canonical_serialization_enabled",
    "docling_artifacts_path",
    "document_timeout_seconds",
    "image_captioning_enabled",
    "image_captioning_prompt",
    "image_heading_height_ratio",
    "image_heading_min_confidence",
    "image_heading_min_page_height_ratio",
    "image_low_confidence_min_alnum_chars",
    "image_picture_classification_threshold",
    "image_primary_ocr_min_confidence",
    "layout_forms_enabled",
    "layout_outline_structure_enabled",
    "layout_relationship_order_enabled",
    "layout_running_regions_enabled",
    "layout_source_notes_enabled",
    "layout_table_captions_enabled",
    "layout_text_run_semantics_enabled",
    "layout_visual_relationships_enabled",
    "max_image_pixels",
    "max_image_total_pixels",
    "max_pages",
    "max_upload_bytes",
    "ocr_languages",
    "ocr_numeric_cleanup_v2_enabled",
    "ocr_spatial_token_preservation_enabled",
    "parser_latency_prewarm_artifacts_sha256",
    "parser_latency_prewarm_dependency_sha256",
    "parser_latency_prewarm_enabled",
    "parser_latency_prewarm_shutdown_grace_seconds",
    "parser_latency_prewarm_timeout_seconds",
    "pdf_render_ocr_min_layout_coverage",
    "pdf_render_ocr_min_native_alnum_chars",
    "pdf_visual_analysis_enabled",
    "shared_ir_enabled",
    "shared_ir_normalization_enabled",
    "table_candidate_gate_enabled",
    "table_evidence_reconciliation_enabled",
    "table_multi_page_merge_enabled",
    "table_span_fidelity_enabled",
    "targeted_ocr_max_pixels",
    "targeted_ocr_scale",
    "targeted_ocr_timeout_seconds",
    "tesseract_cmd",
    "tesseract_data_path",
    "text_integrity_font_audit_enabled",
    "text_integrity_font_recovery_enabled",
    "text_integrity_selective_span_ocr_enabled",
    "text_integrity_source_alignment_enabled",
    "text_reconciliation_enabled",
)
PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS = (
    "PARSER_LATENCY_PREWARM_ENABLED",
    "PARSER_LATENCY_PRIVATE_BROKER_PREDECESSOR",
)
PAIRING_ENVIRONMENT_FIXED_INSTRUMENTATION_KEYS = (
    "PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256",
    "PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256",
    "PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS",
    "PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS",
    "PARSER_TESSERACT_EXECUTABLE",
    "PARSER_TESSERACT_EXECUTABLE_SHA256",
    "PARSER_TESSERACT_EXTERNAL_BARRIERS",
    "PARSER_TESSERACT_GUARD_PYTHON_MODULE_TREE_SHA256",
    "PARSER_TESSERACT_GUARD_PYTHON_NATIVE_CLOSURE_SHA256",
    "PARSER_TESSERACT_GUARD_PYTHON_PATH_CUSTODY_SHA256",
    "PARSER_TESSERACT_GUARD_PYTHON_SHA256",
    "PARSER_TESSERACT_GUARD_WRAPPER_SOURCE_SHA256",
    "PARSER_TESSERACT_LANGUAGES",
    "PARSER_TESSERACT_NATIVE_CLOSURE_SHA256",
    "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_SOURCE_SHA256",
    "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SOURCE_SHA256",
    "PARSER_TESSERACT_SEATBELT_EXECUTABLE_SHA256",
    "PARSER_TESSERACT_STAGED_EXECUTABLE_SHA256",
    "PARSER_TESSERACT_TESSDATA_ROOT",
    "PARSER_TESSERACT_TESSDATA_SHA256",
    "PARSER_TESSERACT_BROKER_PROFILE_SHA256",
    "PARSER_TESSERACT_WATCHDOG_LEDGER_SCHEMA_SHA256",
    "PARSER_TESSERACT_WATCHDOG_PROTOCOL_SHA256",
    "PARSER_TESSERACT_WORKER_PROFILE_SHA256",
)
PAIRING_ENVIRONMENT_DYNAMIC_CAPABILITY_KEYS = tuple(
    sorted(
        {
            "PARSER_WORKER_SUPERVISOR_CAPABILITY",
            "PARSER_TESSERACT_ATTEMPT_DEADLINE_MONOTONIC_NS",
            "PARSER_TESSERACT_ATTEMPT_ID",
            "PARSER_TESSERACT_BROKER_CONFIG_SHA256",
            "PARSER_TESSERACT_BROKER_FD",
            "PARSER_TESSERACT_BROKER_NONCE_SHA256",
            "PARSER_TESSERACT_BROKER_PGID",
            "PARSER_TESSERACT_BROKER_PID",
            "PARSER_TESSERACT_BROKER_SCOPE_SHA256",
            "PARSER_TESSERACT_BROKER_SID",
            "PARSER_TESSERACT_BROKER_START_ABSTIME",
            "PARSER_TESSERACT_CONTROLLER_PID",
            "PARSER_TESSERACT_CONTROLLER_START_ABSTIME",
            "PARSER_TESSERACT_PHASE_CONTROL_FD",
            "PARSER_TESSERACT_EXPECTED_REQUEST_COUNT",
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_PATH",
            "PARSER_TESSERACT_NATIVE_FORK_PROBE_SHA256",
            "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_LIBRARY_SHA256",
            "PARSER_TESSERACT_NATIVE_RUNTIME_GATE_RECORD_SHA256",
            "PARSER_TESSERACT_NATIVE_SPAWN_GUARD_SHA256",
            "PARSER_TESSERACT_REQUEST_CONTROL_FD",
            "PARSER_TESSERACT_REQUEST_ROOT",
            "PARSER_TESSERACT_REQUEST_ROOT_FD",
            "PARSER_TESSERACT_STAGED_EXECUTABLE",
            "PARSER_TESSERACT_SUPERVISOR_CAPABILITY_SHA256",
            "PARSER_TESSERACT_WATCHDOG_FD",
            "PARSER_TESSERACT_WORKER_SCRATCH",
            "PARSER_TESSERACT_WORKER_SCRATCH_FD",
            "PARSER_TESSERACT_WORKER_SCRATCH_IDENTITY_SHA256",
            "TEMP",
            "TMP",
            "TMPDIR",
            "PYTHONPATH",
        }
    )
)
PAIRING_ENVIRONMENT_INSTRUMENTATION_KEYS = tuple(
    sorted(
        {
            *PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS,
            *PAIRING_ENVIRONMENT_FIXED_INSTRUMENTATION_KEYS,
            *PAIRING_ENVIRONMENT_DYNAMIC_CAPABILITY_KEYS,
        }
    )
)
PAIRING_PROJECTION_POLICY = "closed-sanitized-key-manifest-v2"
PAIRING_PROJECTION_POLICY_SHA256 = _canonical_hash(
    {
        "policy": PAIRING_PROJECTION_POLICY,
        "settings_mode_difference_keys": PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS,
        "settings_fixed_instrumentation_keys": (
            PAIRING_SETTINGS_FIXED_INSTRUMENTATION_KEYS
        ),
        "settings_dynamic_capability_keys": (
            PAIRING_SETTINGS_DYNAMIC_CAPABILITY_KEYS
        ),
        "environment_mode_difference_keys": (
            PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS
        ),
        "environment_fixed_instrumentation_keys": (
            PAIRING_ENVIRONMENT_FIXED_INSTRUMENTATION_KEYS
        ),
        "environment_dynamic_capability_keys": (
            PAIRING_ENVIRONMENT_DYNAMIC_CAPABILITY_KEYS
        ),
    }
)
_SECRET_BEARING_KEY = re.compile(
    r"(?:^|_)(?:PASSWORD|PASSWD|SECRET|CREDENTIAL|AUTHORIZATION|COOKIE|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|BEARER_TOKEN)(?:_|$)",
    re.IGNORECASE,
)


class ConfigurationValueIdentity(ContractModel):
    key: Annotated[str, Field(min_length=1, max_length=256)]
    value_sha256: Sha256


class InstrumentationValueIdentity(ConfigurationValueIdentity):
    classification: Literal[
        "mode_difference",
        "fixed_instrumentation",
        "dynamic_capability",
    ]


class SanitizedConfigurationProjection(ContractModel):
    """Closed key manifest containing hashes only, never configuration values."""

    schema_id: Literal["phase-latency-sanitized-config-projection-v2"]
    domain: Literal["application_settings", "worker_environment"]
    behavior_values: Annotated[
        tuple[ConfigurationValueIdentity, ...], Field(max_length=512)
    ] = ()
    instrumentation_values: Annotated[
        tuple[InstrumentationValueIdentity, ...], Field(max_length=128)
    ] = ()
    key_count: PositiveInt
    behavior_sha256: Sha256
    instrumentation_sha256: Sha256
    policy_sha256: Literal[PAIRING_PROJECTION_POLICY_SHA256] = (
        PAIRING_PROJECTION_POLICY_SHA256
    )
    projection_sha256: Sha256
    secret_bearing_keys_absent: Literal[True] = True
    closed_key_set: Literal[True] = True

    @model_validator(mode="after")
    def validate_projection(self) -> "SanitizedConfigurationProjection":
        behavior_keys = tuple(item.key for item in self.behavior_values)
        if behavior_keys != tuple(sorted(behavior_keys)) or any(
            _SECRET_BEARING_KEY.search(key)
            for key in behavior_keys
        ) or len(set(behavior_keys)) != len(behavior_keys):
            raise ValueError("sanitized behavior projection keys differ")
        instrumentation_keys = tuple(
            item.key for item in self.instrumentation_values
        )
        if instrumentation_keys != tuple(sorted(instrumentation_keys)) or len(
            set(instrumentation_keys)
        ) != len(instrumentation_keys):
            raise ValueError("instrumentation projection keys differ")
        allowed = (
            PAIRING_SETTINGS_INSTRUMENTATION_KEYS
            if self.domain == "application_settings"
            else PAIRING_ENVIRONMENT_INSTRUMENTATION_KEYS
        )
        mode_keys = (
            PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS
            if self.domain == "application_settings"
            else PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS
        )
        fixed_keys = (
            PAIRING_SETTINGS_FIXED_INSTRUMENTATION_KEYS
            if self.domain == "application_settings"
            else PAIRING_ENVIRONMENT_FIXED_INSTRUMENTATION_KEYS
        )
        dynamic_keys = (
            PAIRING_SETTINGS_DYNAMIC_CAPABILITY_KEYS
            if self.domain == "application_settings"
            else PAIRING_ENVIRONMENT_DYNAMIC_CAPABILITY_KEYS
        )
        if (
            not set(instrumentation_keys).issubset(allowed)
            or set(behavior_keys).intersection(allowed)
        ):
            raise ValueError("instrumentation projection escaped its allowlist")
        if self.domain == "application_settings":
            if set(instrumentation_keys) != set(
                PAIRING_SETTINGS_INSTRUMENTATION_KEYS
            ):
                raise ValueError(
                    "application settings instrumentation keys are incomplete"
                )
            retained_keys = set(behavior_keys).union(instrumentation_keys)
            if retained_keys != set(PAIRING_APPLICATION_SETTINGS_KEYS):
                raise ValueError("application settings closed key set differs")
        if self.key_count != len(behavior_keys) + len(instrumentation_keys):
            raise ValueError("sanitized projection key count differs")
        for item in self.instrumentation_values:
            expected_classification = (
                "mode_difference"
                if item.key in mode_keys
                else "fixed_instrumentation"
                if item.key in fixed_keys
                else "dynamic_capability"
                if item.key in dynamic_keys
                else None
            )
            if item.classification != expected_classification:
                raise ValueError("instrumentation projection classification differs")
        behavior_sha256 = _canonical_hash(
            [item.model_dump(mode="json") for item in self.behavior_values]
        )
        instrumentation_sha256 = _canonical_hash(
            [item.model_dump(mode="json") for item in self.instrumentation_values]
        )
        if (
            self.behavior_sha256 != behavior_sha256
            or self.instrumentation_sha256 != instrumentation_sha256
        ):
            raise ValueError("sanitized projection component identity differs")
        fields = self.model_dump(mode="json", exclude={"projection_sha256"})
        if self.projection_sha256 != _canonical_hash(fields):
            raise ValueError("sanitized configuration projection identity differs")
        return self


def sanitized_configuration_projection(
    *,
    domain: Literal["application_settings", "worker_environment"],
    values: Mapping[str, object],
) -> SanitizedConfigurationProjection:
    if not values:
        raise ValueError("sanitized configuration projection cannot be empty")
    if any(type(key) is not str for key in values):
        raise ValueError("sanitized configuration keys must be strings")
    allowed = (
        PAIRING_SETTINGS_INSTRUMENTATION_KEYS
        if domain == "application_settings"
        else PAIRING_ENVIRONMENT_INSTRUMENTATION_KEYS
    )
    behavior = {
        key: values[key]
        for key in sorted(values)
        if key not in allowed
    }
    behavior_values = tuple(
        ConfigurationValueIdentity(key=key, value_sha256=_canonical_hash(value))
        for key, value in behavior.items()
    )
    mode_keys = (
        PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS
        if domain == "application_settings"
        else PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS
    )
    fixed_keys = (
        PAIRING_SETTINGS_FIXED_INSTRUMENTATION_KEYS
        if domain == "application_settings"
        else PAIRING_ENVIRONMENT_FIXED_INSTRUMENTATION_KEYS
    )
    instrumentation = tuple(
        InstrumentationValueIdentity(
            key=key,
            value_sha256=_canonical_hash(values[key]),
            classification=(
                "mode_difference"
                if key in mode_keys
                else "fixed_instrumentation"
                if key in fixed_keys
                else "dynamic_capability"
            ),
        )
        for key in sorted(values)
        if key in allowed
    )
    fields = {
        "schema_id": "phase-latency-sanitized-config-projection-v2",
        "domain": domain,
        "behavior_values": behavior_values,
        "instrumentation_values": instrumentation,
        "key_count": len(values),
        "behavior_sha256": _canonical_hash(
            [item.model_dump(mode="json") for item in behavior_values]
        ),
        "instrumentation_sha256": _canonical_hash(
            [item.model_dump(mode="json") for item in instrumentation]
        ),
        "policy_sha256": PAIRING_PROJECTION_POLICY_SHA256,
        "secret_bearing_keys_absent": True,
        "closed_key_set": True,
    }
    dumped = {
        key: (
            [item.model_dump(mode="json") for item in value]
            if key in {"behavior_values", "instrumentation_values"}
            else value
        )
        for key, value in fields.items()
    }
    return SanitizedConfigurationProjection(
        **fields, projection_sha256=_canonical_hash(dumped)  # type: ignore[arg-type]
    )


class ConfigurationIdentity(ContractModel):
    feature_flag: Literal["parser.latency.prewarm.enabled"] = PREWARM_FEATURE_FLAG
    prewarm_enabled: StrictBool
    startup_timeout_ns: PositiveInt
    request_timeout_ns: PositiveInt | None = None
    shutdown_timeout_ns: PositiveInt | None = None
    reuse_scope: Literal["single_owned_worker"] = "single_owned_worker"
    runtime_downloads_allowed: Literal[False] = False
    mutable_cross_request_state_allowed: Literal[False] = False
    endpoint: Literal["/v1/parse"] | None = None
    output_format: Literal["json"] | None = None
    measurement_kind: Literal[
        "paired_case",
        "cross_input_aba",
        "rollback_output_gate",
    ] | None = None
    execution_topology: Literal[
        "direct-default-off-v1",
        "fork-denied-worker-external-tesseract-broker-v1",
    ] | None = None
    broker_evidence_capability: Literal["absent", "private-harness-v1"] | None = (
        None
    )
    broker_external_barriers_required: StrictBool | None = None
    worker_fork_denial_required: StrictBool | None = None
    request_count: PositiveInt | None = None
    application_settings_sha256: Sha256 | None = None
    worker_environment_sha256: Sha256 | None = None
    application_settings_projection: SanitizedConfigurationProjection | None = None
    worker_environment_projection: SanitizedConfigurationProjection | None = None
    pairing_projection_policy_sha256: Sha256 | None = None
    pairing_sha256: Sha256 | None = None
    artifacts_path: str | None = None
    artifacts_path_identity_sha256: Sha256 | None = None
    tesseract_executable: str | None = None
    tesseract_data_path: str | None = None
    network_isolation_policy: Literal[
        "python-and-darwin-process-tree-deny-v1",
        "dual-seatbelt-fork-denied-worker-broker-network-deny-v2",
    ] | None = None
    sha256: Sha256

    @field_validator("artifacts_path")
    @classmethod
    def validate_optional_artifact_path(cls, value: str | None) -> str | None:
        return None if value is None else _portable_path(value)

    @field_validator("tesseract_executable", "tesseract_data_path")
    @classmethod
    def validate_optional_absolute_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            not value.startswith("/")
            or len(value.encode("utf-8")) > 4_096
            or value != value.strip()
            or "\\" in value
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])
            or any(ord(character) < 0x20 for character in value)
        ):
            raise ValueError("runtime dependency path must be canonical absolute text")
        return value

    @model_validator(mode="after")
    def validate_sha256(self) -> "ConfigurationIdentity":
        fields = self.model_dump(
            mode="json", exclude={"sha256"}, exclude_none=True
        )
        if self.sha256 != _canonical_hash(fields):
            raise ValueError("configuration identity differs")
        if self.endpoint == "/v1/parse":
            if (
                self.application_settings_projection is None
                or self.application_settings_projection.domain
                != "application_settings"
                or self.worker_environment_projection is None
                or self.worker_environment_projection.domain
                != "worker_environment"
                or self.pairing_projection_policy_sha256
                != PAIRING_PROJECTION_POLICY_SHA256
            ):
                raise ValueError("production configuration projection custody differs")
            if self.pairing_sha256 != _canonical_hash(
                configuration_pairing_projection(self)
            ):
                raise ValueError("configuration pairing projection identity differs")
            environment_instrumentation = {
                item.key: item.value_sha256
                for item in self.worker_environment_projection.instrumentation_values
            }
            alias_groups = (
                (
                    "PARSER_TESSERACT_WORKER_SCRATCH",
                    "PARSER_TESSERACT_REQUEST_ROOT",
                    "TMPDIR",
                    "TMP",
                    "TEMP",
                ),
                (
                    "PARSER_TESSERACT_WORKER_SCRATCH_FD",
                    "PARSER_TESSERACT_REQUEST_ROOT_FD",
                ),
            )
            for aliases in alias_groups:
                observed = tuple(
                    environment_instrumentation.get(key) for key in aliases
                )
                if any(value is not None for value in observed) and (
                    any(value is None for value in observed)
                    or len(set(observed)) != 1
                ):
                    raise ValueError("worker scratch/request-root alias differs")
            if (
                self.request_timeout_ns != 330_000_000_000
                or self.shutdown_timeout_ns != 30_000_000_000
            ):
                raise ValueError("production phase timeouts differ")
            if self.measurement_kind == "rollback_output_gate":
                if (
                    self.prewarm_enabled
                    or self.request_count != 1
                    or self.execution_topology != "direct-default-off-v1"
                    or self.broker_evidence_capability != "absent"
                    or self.broker_external_barriers_required is not False
                    or self.worker_fork_denial_required is not False
                    or self.network_isolation_policy
                    != "python-and-darwin-process-tree-deny-v1"
                ):
                    raise ValueError("rollback output-gate topology differs")
                return self
            if (
                self.execution_topology
                != "fork-denied-worker-external-tesseract-broker-v1"
                or self.broker_evidence_capability != "private-harness-v1"
                or self.broker_external_barriers_required is not True
                or self.worker_fork_denial_required is not True
                or self.network_isolation_policy
                != "dual-seatbelt-fork-denied-worker-broker-network-deny-v2"
            ):
                raise ValueError("production evidence topology differs")
            if self.measurement_kind == "cross_input_aba":
                if self.request_count != 3:
                    raise ValueError("cross-input configuration requires A-B-A")
            elif (
                self.measurement_kind != "paired_case"
                or self.request_count is None
                or self.request_count < PRODUCTION_MINIMUM_REQUESTS
            ):
                raise ValueError("paired production configuration requires four requests")
        return self


def configuration_pairing_projection(
    configuration: ConfigurationIdentity,
) -> dict[str, object]:
    """Canonical behavior-equality projection for paired/cross attempts."""

    if (
        configuration.application_settings_projection is None
        or configuration.worker_environment_projection is None
    ):
        raise ValueError("configuration lacks sanitized pairing projections")
    fields = configuration.model_dump(
        mode="json",
        exclude={
            "prewarm_enabled",
            "measurement_kind",
            "request_count",
            "application_settings_sha256",
            "worker_environment_sha256",
            "application_settings_projection",
            "worker_environment_projection",
            "pairing_sha256",
            "sha256",
        },
        exclude_none=True,
    )
    for label, projection in (
        ("application_settings", configuration.application_settings_projection),
        ("worker_environment", configuration.worker_environment_projection),
    ):
        fields[f"{label}_behavior_values"] = [
            item.model_dump(mode="json") for item in projection.behavior_values
        ]
        fields[f"{label}_fixed_instrumentation_values"] = [
            item.model_dump(mode="json")
            for item in projection.instrumentation_values
            if item.classification == "fixed_instrumentation"
        ]
        fields[f"{label}_mode_difference_policy_keys"] = list(
            PAIRING_SETTINGS_MODE_DIFFERENCE_KEYS
            if projection.domain == "application_settings"
            else PAIRING_ENVIRONMENT_MODE_DIFFERENCE_KEYS
        )
        fields[f"{label}_dynamic_capability_keys"] = [
            item.key
            for item in projection.instrumentation_values
            if item.classification == "dynamic_capability"
        ]
    return fields


def configuration_rollback_equivalence_projection(
    configuration: ConfigurationIdentity,
) -> dict[str, object]:
    """Behavior-equivalence projection for direct and brokered flag-off runs.

    The direct topology has no private dynamic capability.  Every application
    setting, every ordinary environment value, and every fixed instrumentation
    value must nevertheless match exactly.  Only the closed private-harness
    mode/dynamic environment allowlist is omitted.
    """

    settings = configuration.application_settings_projection
    environment = configuration.worker_environment_projection
    if settings is None or environment is None:
        raise ValueError("configuration lacks rollback equivalence projections")
    fields = configuration.model_dump(
        mode="json",
        exclude={
            "application_settings_sha256",
            "worker_environment_sha256",
            "application_settings_projection",
            "worker_environment_projection",
            "execution_topology",
            "broker_evidence_capability",
            "broker_external_barriers_required",
            "worker_fork_denial_required",
            "network_isolation_policy",
            "measurement_kind",
            "request_count",
            "pairing_sha256",
            "sha256",
        },
        exclude_none=True,
    )
    fields["application_settings_values"] = [
        item.model_dump(mode="json")
        for item in (*settings.behavior_values, *settings.instrumentation_values)
    ]
    fields["worker_environment_behavior_values"] = [
        item.model_dump(mode="json") for item in environment.behavior_values
    ]
    fields["worker_environment_fixed_instrumentation_values"] = [
        item.model_dump(mode="json")
        for item in environment.instrumentation_values
        if item.classification == "fixed_instrumentation"
    ]
    fields["permitted_environment_difference_policy_sha256"] = (
        PAIRING_PROJECTION_POLICY_SHA256
    )
    return fields


def configuration_identity(
    *, prewarm_enabled: bool, startup_timeout_ns: int
) -> ConfigurationIdentity:
    fields = {
        "feature_flag": PREWARM_FEATURE_FLAG,
        "prewarm_enabled": prewarm_enabled,
        "startup_timeout_ns": startup_timeout_ns,
        "reuse_scope": "single_owned_worker",
        "runtime_downloads_allowed": False,
        "mutable_cross_request_state_allowed": False,
    }
    return ConfigurationIdentity(**fields, sha256=_canonical_hash(fields))


def production_configuration_identity(
    *,
    prewarm_enabled: bool,
    startup_timeout_ns: int,
    request_count: int,
    application_settings_sha256: str,
    worker_environment_sha256: str,
    application_settings_projection: SanitizedConfigurationProjection,
    worker_environment_projection: SanitizedConfigurationProjection,
    artifacts_path: str,
    artifacts_path_identity_sha256: str,
    tesseract_executable: str,
    tesseract_data_path: str,
) -> ConfigurationIdentity:
    fields = {
        "feature_flag": PREWARM_FEATURE_FLAG,
        "prewarm_enabled": prewarm_enabled,
        "startup_timeout_ns": startup_timeout_ns,
        "request_timeout_ns": 330_000_000_000,
        "shutdown_timeout_ns": 30_000_000_000,
        "reuse_scope": "single_owned_worker",
        "runtime_downloads_allowed": False,
        "mutable_cross_request_state_allowed": False,
        "endpoint": "/v1/parse",
        "output_format": "json",
        "measurement_kind": "paired_case",
        "execution_topology": (
            "fork-denied-worker-external-tesseract-broker-v1"
        ),
        "broker_evidence_capability": "private-harness-v1",
        "broker_external_barriers_required": True,
        "worker_fork_denial_required": True,
        "request_count": request_count,
        "application_settings_sha256": application_settings_sha256,
        "worker_environment_sha256": worker_environment_sha256,
        "application_settings_projection": application_settings_projection,
        "worker_environment_projection": worker_environment_projection,
        "pairing_projection_policy_sha256": PAIRING_PROJECTION_POLICY_SHA256,
        "artifacts_path": artifacts_path,
        "artifacts_path_identity_sha256": artifacts_path_identity_sha256,
        "tesseract_executable": tesseract_executable,
        "tesseract_data_path": tesseract_data_path,
        "network_isolation_policy": (
            "dual-seatbelt-fork-denied-worker-broker-network-deny-v2"
        ),
    }
    provisional = ConfigurationIdentity.model_construct(
        **fields, pairing_sha256="0" * 64, sha256="0" * 64
    )
    fields["pairing_sha256"] = _canonical_hash(
        configuration_pairing_projection(provisional)
    )
    dumped = {
        key: value.model_dump(mode="json")
        if isinstance(value, ContractModel)
        else value
        for key, value in fields.items()
    }
    return ConfigurationIdentity(**fields, sha256=_canonical_hash(dumped))


def cross_input_configuration_identity(
    *,
    application_settings_sha256: str,
    worker_environment_sha256: str,
    application_settings_projection: SanitizedConfigurationProjection,
    worker_environment_projection: SanitizedConfigurationProjection,
    artifacts_path: str,
    artifacts_path_identity_sha256: str,
    tesseract_executable: str,
    tesseract_data_path: str,
) -> ConfigurationIdentity:
    fields = {
        "feature_flag": PREWARM_FEATURE_FLAG,
        "prewarm_enabled": True,
        "startup_timeout_ns": 300_000_000_000,
        "request_timeout_ns": 330_000_000_000,
        "shutdown_timeout_ns": 30_000_000_000,
        "reuse_scope": "single_owned_worker",
        "runtime_downloads_allowed": False,
        "mutable_cross_request_state_allowed": False,
        "endpoint": "/v1/parse",
        "output_format": "json",
        "measurement_kind": "cross_input_aba",
        "execution_topology": (
            "fork-denied-worker-external-tesseract-broker-v1"
        ),
        "broker_evidence_capability": "private-harness-v1",
        "broker_external_barriers_required": True,
        "worker_fork_denial_required": True,
        "request_count": 3,
        "application_settings_sha256": application_settings_sha256,
        "worker_environment_sha256": worker_environment_sha256,
        "application_settings_projection": application_settings_projection,
        "worker_environment_projection": worker_environment_projection,
        "pairing_projection_policy_sha256": PAIRING_PROJECTION_POLICY_SHA256,
        "artifacts_path": artifacts_path,
        "artifacts_path_identity_sha256": artifacts_path_identity_sha256,
        "tesseract_executable": tesseract_executable,
        "tesseract_data_path": tesseract_data_path,
        "network_isolation_policy": (
            "dual-seatbelt-fork-denied-worker-broker-network-deny-v2"
        ),
    }
    provisional = ConfigurationIdentity.model_construct(
        **fields, pairing_sha256="0" * 64, sha256="0" * 64
    )
    fields["pairing_sha256"] = _canonical_hash(
        configuration_pairing_projection(provisional)
    )
    dumped = {
        key: value.model_dump(mode="json")
        if isinstance(value, ContractModel)
        else value
        for key, value in fields.items()
    }
    return ConfigurationIdentity(**fields, sha256=_canonical_hash(dumped))


def rollback_output_configuration_identity(
    *,
    startup_timeout_ns: int,
    application_settings_sha256: str,
    worker_environment_sha256: str,
    application_settings_projection: SanitizedConfigurationProjection,
    worker_environment_projection: SanitizedConfigurationProjection,
    artifacts_path: str,
    artifacts_path_identity_sha256: str,
    tesseract_executable: str,
    tesseract_data_path: str,
) -> ConfigurationIdentity:
    """Exact flag-off, brokerless topology used only for rollback parity."""

    fields = {
        "feature_flag": PREWARM_FEATURE_FLAG,
        "prewarm_enabled": False,
        "startup_timeout_ns": startup_timeout_ns,
        "request_timeout_ns": 330_000_000_000,
        "shutdown_timeout_ns": 30_000_000_000,
        "reuse_scope": "single_owned_worker",
        "runtime_downloads_allowed": False,
        "mutable_cross_request_state_allowed": False,
        "endpoint": "/v1/parse",
        "output_format": "json",
        "measurement_kind": "rollback_output_gate",
        "execution_topology": "direct-default-off-v1",
        "broker_evidence_capability": "absent",
        "broker_external_barriers_required": False,
        "worker_fork_denial_required": False,
        "request_count": 1,
        "application_settings_sha256": application_settings_sha256,
        "worker_environment_sha256": worker_environment_sha256,
        "application_settings_projection": application_settings_projection,
        "worker_environment_projection": worker_environment_projection,
        "pairing_projection_policy_sha256": PAIRING_PROJECTION_POLICY_SHA256,
        "artifacts_path": artifacts_path,
        "artifacts_path_identity_sha256": artifacts_path_identity_sha256,
        "tesseract_executable": tesseract_executable,
        "tesseract_data_path": tesseract_data_path,
        "network_isolation_policy": "python-and-darwin-process-tree-deny-v1",
    }
    provisional = ConfigurationIdentity.model_construct(
        **fields, pairing_sha256="0" * 64, sha256="0" * 64
    )
    fields["pairing_sha256"] = _canonical_hash(
        configuration_pairing_projection(provisional)
    )
    dumped = {
        key: value.model_dump(mode="json")
        if isinstance(value, ContractModel)
        else value
        for key, value in fields.items()
    }
    return ConfigurationIdentity(**fields, sha256=_canonical_hash(dumped))


class OutputIdentity(ContractModel):
    sha256: Sha256
    normalized_sha256: Sha256
    semantic_sha256: Sha256
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=MAXIMUM_OUTPUT_BYTES)]
    media_type: Literal["application/json", "text/markdown"]
    validation: Literal["synthetic_contract_control", "ParseResult"]
    normalization_policy: Literal[
        "json_exclude_processing_duration_ms_v1", "raw_bytes_exact_v1"
    ]
    api_contract_sha256: Sha256 | None = None
    provenance_sha256: Sha256 | None = None
    concerns_sha256: Sha256 | None = None
    deterministic_ids_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_normalization(self) -> "OutputIdentity":
        if self.media_type == "text/markdown" and (
            self.normalization_policy != "raw_bytes_exact_v1"
            or self.normalized_sha256 != self.sha256
        ):
            raise ValueError("Markdown normalization must preserve exact raw bytes")
        if self.media_type == "application/json" and self.normalization_policy != (
            "json_exclude_processing_duration_ms_v1"
        ):
            raise ValueError("JSON parity may exclude only processing duration")
        component_hashes = (
            self.api_contract_sha256,
            self.provenance_sha256,
            self.concerns_sha256,
            self.deterministic_ids_sha256,
        )
        if self.validation == "ParseResult" and any(
            value is None for value in component_hashes
        ):
            raise ValueError("ParseResult output component identities are incomplete")
        if self.validation == "ParseResult" and self.media_type == "application/json":
            if not (
                self.normalized_sha256
                == self.semantic_sha256
                == self.api_contract_sha256
            ):
                raise ValueError(
                    "ParseResult normalized, semantic, and API identities must agree"
                )
        if self.validation == "synthetic_contract_control" and any(
            value is not None for value in component_hashes
        ):
            raise ValueError("synthetic output cannot claim production components")
        return self


class NormalizedParseResultWitness(ContractModel):
    """Bounded canonical bytes used to recompute every output component hash."""

    encoding: Literal["canonical-json-utf8-base64-v1"] = (
        "canonical-json-utf8-base64-v1"
    )
    canonical_json_base64: Annotated[
        str, Field(min_length=4, max_length=5_592_408)
    ]
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=4_194_304)]
    normalized_sha256: Sha256
    api_contract_sha256: Sha256
    provenance_sha256: Sha256
    concerns_sha256: Sha256
    deterministic_ids_sha256: Sha256

    @model_validator(mode="after")
    def validate_witness(self) -> "NormalizedParseResultWitness":
        try:
            raw = base64.b64decode(
                self.canonical_json_base64.encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("normalized ParseResult witness is not strict base64") from exc
        if (
            not raw
            or len(raw) != self.size_bytes
            or len(raw) > 4_194_304
            or base64.b64encode(raw).decode("ascii")
            != self.canonical_json_base64
        ):
            raise ValueError("normalized ParseResult witness size/encoding differs")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("normalized ParseResult witness is not JSON") from exc
        if type(value) is not dict or _semantic_json_bytes(value) != raw:
            raise ValueError("normalized ParseResult witness is not canonical JSON")
        processing = value.get("processing")
        if type(processing) is not dict or "duration_ms" in processing:
            raise ValueError("normalized ParseResult witness duration exclusion differs")
        normalized = hashlib.sha256(raw).hexdigest()
        expected = (
            normalized,
            normalized,
            _output_projection_hash(value, projection="provenance"),
            _output_projection_hash(value, projection="concerns"),
            _output_projection_hash(value, projection="deterministic_ids"),
        )
        observed = (
            self.normalized_sha256,
            self.api_contract_sha256,
            self.provenance_sha256,
            self.concerns_sha256,
            self.deterministic_ids_sha256,
        )
        if observed != expected:
            raise ValueError("normalized ParseResult witness projections differ")
        return self


def normalized_parse_result_witness(
    normalized_parse_result: object,
) -> NormalizedParseResultWitness:
    """Build the self-verifying normalized witness used by the rollback gate."""

    raw = _semantic_json_bytes(normalized_parse_result)
    if not raw or len(raw) > 4_194_304:
        raise ValueError("normalized ParseResult witness exceeds its evidence bound")
    if type(normalized_parse_result) is not dict:
        raise ValueError("normalized ParseResult witness must be an object")
    normalized_sha256 = hashlib.sha256(raw).hexdigest()
    return NormalizedParseResultWitness(
        canonical_json_base64=base64.b64encode(raw).decode("ascii"),
        size_bytes=len(raw),
        normalized_sha256=normalized_sha256,
        api_contract_sha256=normalized_sha256,
        provenance_sha256=_output_projection_hash(
            normalized_parse_result, projection="provenance"
        ),
        concerns_sha256=_output_projection_hash(
            normalized_parse_result, projection="concerns"
        ),
        deterministic_ids_sha256=_output_projection_hash(
            normalized_parse_result, projection="deterministic_ids"
        ),
    )


class FailureRecord(ContractModel):
    code: FailureCode
    stage: Literal["startup", "identity_validation", "request", "shutdown"]
    detail_sha256: Sha256 | None = None
    retryable: StrictBool = False


class ResourceSample(ContractModel):
    phase: ResourcePhase
    observed_monotonic_ns: NonNegativeInt
    rss_bytes: PositiveInt
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt
    process_count: PositiveInt
    thread_count: PositiveInt
    file_descriptor_count: NonNegativeInt


class ProcessCpuCounter(ContractModel):
    """One cumulative CPU counter bound to a PID-reuse-safe identity."""

    pid: PositiveInt
    create_time_ns: PositiveInt
    ownership: Literal["worker", "descendant"]
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt


class ProcessCpuSnapshot(ContractModel):
    """Exact request-edge CPU inputs retained for independent recomputation."""

    observed_monotonic_ns: NonNegativeInt
    rusage_self_user_cpu_ns: NonNegativeInt
    rusage_self_system_cpu_ns: NonNegativeInt
    rusage_reaped_child_user_cpu_ns: NonNegativeInt
    rusage_reaped_child_system_cpu_ns: NonNegativeInt
    members: Annotated[
        tuple[ProcessCpuCounter, ...], Field(min_length=1, max_length=128)
    ]

    @model_validator(mode="after")
    def validate_members(self) -> "ProcessCpuSnapshot":
        identities = tuple((item.pid, item.create_time_ns) for item in self.members)
        if len(identities) != len(set(identities)):
            raise ValueError("process CPU identities must be unique")
        pids = tuple(item.pid for item in self.members)
        if len(pids) != len(set(pids)):
            raise ValueError("one process CPU snapshot cannot contain PID reuse")
        if self.members[0].ownership != "worker":
            raise ValueError("worker CPU counter must be first")
        if any(item.ownership != "descendant" for item in self.members[1:]):
            raise ValueError("non-root CPU counters must be owned descendants")
        if identities[1:] != tuple(sorted(identities[1:])):
            raise ValueError("descendant CPU counters must be canonical")
        return self


class ExactProcessIdentity(ContractModel):
    """One frozen process identity used by the broker CPU-v2 boundary."""

    role: Literal["parser_worker", "tesseract_broker"]
    pid: PositiveInt
    start_abstime: PositiveInt
    parent_pid: PositiveInt
    process_group_id: PositiveInt
    session_id: PositiveInt

    @model_validator(mode="after")
    def validate_fresh_group_root(self) -> "ExactProcessIdentity":
        if self.pid != self.process_group_id or self.pid != self.session_id:
            raise ValueError("CPU-v2 process must lead its fresh group and session")
        return self


class BrokerPostReleaseBaseline(ContractModel):
    """Typed retirement of broker bootstrap FDs before request admission."""

    schema_id: Literal[
        "parser-tesseract-broker-post-release-baseline-v1"
    ] = "parser-tesseract-broker-post-release-baseline-v1"
    broker: "NativeKernelProcessIdentity"
    pre_release_ready_sha256: Sha256
    retired_descriptor_fds: Annotated[
        tuple[Annotated[int, Field(strict=True, ge=3)], ...],
        Field(min_length=2, max_length=2),
    ]
    pre_release_thread_inventory: "NativeThreadInventory"
    pre_release_file_descriptor_inventory: "NativeFileDescriptorInventory"
    post_release_thread_inventory: "NativeThreadInventory"
    post_release_file_descriptor_inventory: "NativeFileDescriptorInventory"
    transition_observed_at_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_transition(self) -> "BrokerPostReleaseBaseline":
        if (
            self.retired_descriptor_fds
            != tuple(sorted(set(self.retired_descriptor_fds)))
            or self.pre_release_thread_inventory.process != self.broker
            or self.post_release_thread_inventory.process != self.broker
            or self.pre_release_file_descriptor_inventory.process != self.broker
            or self.post_release_file_descriptor_inventory.process != self.broker
            or self.pre_release_thread_inventory.thread_count != 1
            or self.post_release_thread_inventory.thread_count != 1
            or self.pre_release_thread_inventory.thread_ids
            != self.post_release_thread_inventory.thread_ids
            or self.post_release_file_descriptor_inventory.second_scan_completed_monotonic_ns
            > self.transition_observed_at_monotonic_ns
        ):
            raise ValueError("broker post-release inventory differs")
        retired = set(self.retired_descriptor_fds)
        pre_by_fd = {
            item.fd: item
            for item in self.pre_release_file_descriptor_inventory.descriptors
        }
        post_by_fd = {
            item.fd: item
            for item in self.post_release_file_descriptor_inventory.descriptors
        }
        if (
            not retired.issubset(pre_by_fd)
            or retired.intersection(post_by_fd)
            or set(pre_by_fd).difference(retired) != set(post_by_fd)
            or any(pre_by_fd[fd] != post_by_fd[fd] for fd in post_by_fd)
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("broker descriptor retirement differs")
        return self


def broker_post_release_baseline(**fields: object) -> BrokerPostReleaseBaseline:
    if "record_sha256" in fields:
        raise ValueError("broker post-release baseline identity is derived")
    provisional = BrokerPostReleaseBaseline.model_construct(
        **fields, record_sha256="0" * 64
    )
    return BrokerPostReleaseBaseline(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class FrameworkThreadBaseline(ContractModel):
    """Complete worker thread/FD baseline created before request READY."""

    schema_id: Literal["parser-framework-thread-baseline-v2"] = (
        "parser-framework-thread-baseline-v2"
    )
    worker_pid: PositiveInt
    worker_start_abstime: PositiveInt
    worker_ppid: PositiveInt
    worker_pgid: PositiveInt
    worker_sid: PositiveInt
    event_loop_python_thread_id: PositiveInt
    event_loop_native_thread_id: PositiveInt
    asyncio_executor_python_thread_id: PositiveInt
    asyncio_executor_native_thread_id: PositiveInt
    anyio_worker_python_thread_id: PositiveInt
    anyio_worker_native_thread_id: PositiveInt
    selected_python_native_thread_identity_basis: Literal[
        "python-threading-get_native_id-pthread_threadid_np-v1"
    ] = "python-threading-get_native_id-pthread_threadid_np-v1"
    full_worker_thread_inventory_identity_basis: Literal[
        "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    ] = "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    full_worker_proc_thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=4_096)
    ]
    full_worker_proc_thread_count: PositiveInt
    full_worker_proc_thread_inventory_sha256: Sha256
    first_full_inventory_observed_at_monotonic_ns: PositiveInt
    second_full_inventory_observed_at_monotonic_ns: PositiveInt
    full_worker_file_descriptor_inventory: "NativeFileDescriptorInventory"
    broker_post_release_baseline: BrokerPostReleaseBaseline
    observed_at_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_baseline(self) -> "FrameworkThreadBaseline":
        if len(
            {
                self.event_loop_python_thread_id,
                self.asyncio_executor_python_thread_id,
                self.anyio_worker_python_thread_id,
            }
        ) != 3 or len(
            {
                self.event_loop_native_thread_id,
                self.asyncio_executor_native_thread_id,
                self.anyio_worker_native_thread_id,
            }
        ) != 3:
            raise ValueError("framework thread baseline is not distinct")
        process = {
            "pid": self.worker_pid,
            "start_abstime": self.worker_start_abstime,
            "ppid": self.worker_ppid,
            "pgid": self.worker_pgid,
            "sid": self.worker_sid,
        }
        if (
            self.worker_pid != self.worker_pgid
            or self.worker_pid != self.worker_sid
            or self.full_worker_proc_thread_ids
            != tuple(sorted(set(self.full_worker_proc_thread_ids)))
            or self.full_worker_proc_thread_count
            != len(self.full_worker_proc_thread_ids)
            or self.first_full_inventory_observed_at_monotonic_ns
            > self.second_full_inventory_observed_at_monotonic_ns
            or self.second_full_inventory_observed_at_monotonic_ns
            > self.observed_at_monotonic_ns
            or self.full_worker_proc_thread_inventory_sha256
            != _canonical_hash(
                {
                    "schema_id": "darwin-detailed-thread-inventory-v1",
                    "process": process,
                    "identity_basis": (
                        self.full_worker_thread_inventory_identity_basis
                    ),
                    "thread_ids": list(self.full_worker_proc_thread_ids),
                    "thread_count": self.full_worker_proc_thread_count,
                }
            )
            or self.full_worker_file_descriptor_inventory.process.model_dump(
                mode="json"
            )
            != process
            or self.broker_post_release_baseline.broker.pid == self.worker_pid
        ):
            raise ValueError("complete framework resource baseline differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("framework thread baseline identity differs")
        return self


def framework_thread_baseline(**fields: object) -> FrameworkThreadBaseline:
    if "record_sha256" in fields:
        raise ValueError("framework thread baseline identity is derived")
    provisional = FrameworkThreadBaseline.model_construct(
        **fields, record_sha256="0" * 64
    )
    return FrameworkThreadBaseline(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),  # type: ignore[arg-type]
    )


class RequestControlReadinessEvidence(ContractModel):
    """Controller-retained READY binding after supervised thread preseed."""

    schema_id: Literal["phase-latency-request-control-readiness-v1"] = (
        "phase-latency-request-control-readiness-v1"
    )
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    worker: ExactProcessIdentity
    broker: ExactProcessIdentity
    expected_request_count: PositiveInt
    framework_thread_baseline: FrameworkThreadBaseline
    controller_worker_thread_inventory: "NativeThreadInventory"
    controller_worker_file_descriptor_inventory: "NativeFileDescriptorInventory"
    controller_broker_thread_inventory: "NativeThreadInventory"
    controller_broker_file_descriptor_inventory: "NativeFileDescriptorInventory"
    ready_at_monotonic_ns: PositiveInt
    previous_record_sha256: Literal[
        "0000000000000000000000000000000000000000000000000000000000000000"
    ] = "0" * 64
    ready_record_sha256: Sha256
    transcript_row_sha256: Sha256
    record_sha256: Sha256

    @staticmethod
    def _identity_mapping(value: ExactProcessIdentity) -> dict[str, int]:
        return {
            "pid": value.pid,
            "start_abstime": value.start_abstime,
            "ppid": value.parent_pid,
            "pgid": value.process_group_id,
            "sid": value.session_id,
        }

    @model_validator(mode="after")
    def validate_ready(self) -> "RequestControlReadinessEvidence":
        worker_mapping = self._identity_mapping(self.worker)
        broker_mapping = self._identity_mapping(self.broker)
        if (
            self.worker.role != "parser_worker"
            or self.broker.role != "tesseract_broker"
            or {
                "pid": self.framework_thread_baseline.worker_pid,
                "start_abstime": self.framework_thread_baseline.worker_start_abstime,
                "ppid": self.framework_thread_baseline.worker_ppid,
                "pgid": self.framework_thread_baseline.worker_pgid,
                "sid": self.framework_thread_baseline.worker_sid,
            }
            != worker_mapping
            or self.controller_worker_thread_inventory.process.model_dump(
                mode="json"
            )
            != worker_mapping
            or self.controller_worker_file_descriptor_inventory.process.model_dump(
                mode="json"
            )
            != worker_mapping
            or self.controller_broker_thread_inventory.process.model_dump(
                mode="json"
            )
            != broker_mapping
            or self.framework_thread_baseline.broker_post_release_baseline.broker.model_dump(
                mode="json"
            )
            != broker_mapping
            or self.controller_broker_file_descriptor_inventory.process.model_dump(
                mode="json"
            )
            != broker_mapping
            or self.controller_worker_thread_inventory.thread_ids
            != self.framework_thread_baseline.full_worker_proc_thread_ids
            or self.controller_worker_thread_inventory.inventory_sha256
            != self.framework_thread_baseline.full_worker_proc_thread_inventory_sha256
            or self.controller_worker_file_descriptor_inventory.inventory_sha256
            != self.framework_thread_baseline.full_worker_file_descriptor_inventory.inventory_sha256
            or self.controller_broker_thread_inventory.thread_count != 1
            or self.controller_broker_thread_inventory.inventory_sha256
            != self.framework_thread_baseline.broker_post_release_baseline.post_release_thread_inventory.inventory_sha256
            or self.controller_broker_file_descriptor_inventory.inventory_sha256
            != self.framework_thread_baseline.broker_post_release_baseline.post_release_file_descriptor_inventory.inventory_sha256
            or self.framework_thread_baseline.observed_at_monotonic_ns
            > self.ready_at_monotonic_ns
            or self.ready_at_monotonic_ns
            > min(
                self.controller_worker_thread_inventory.first_scan_started_monotonic_ns,
                self.controller_worker_file_descriptor_inventory.first_scan_started_monotonic_ns,
                self.controller_broker_thread_inventory.first_scan_started_monotonic_ns,
                self.controller_broker_file_descriptor_inventory.first_scan_started_monotonic_ns,
            )
        ):
            raise ValueError("request-control readiness binding differs")
        ready_payload = {
            "schema_id": "parser-request-control-ready-v1",
            "attempt_id": self.attempt_id,
            "attempt_nonce_sha256": self.attempt_nonce_sha256,
            "scope_sha256": self.scope_sha256,
            "worker": self._identity_mapping(self.worker),
            "broker": self._identity_mapping(self.broker),
            "expected_request_count": self.expected_request_count,
            "framework_thread_baseline": self.framework_thread_baseline.model_dump(
                mode="json"
            ),
            "ready_at_monotonic_ns": self.ready_at_monotonic_ns,
            "previous_record_sha256": self.previous_record_sha256,
        }
        if self.ready_record_sha256 != _canonical_hash(ready_payload):
            raise ValueError("request-control READY record identity differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("request-control readiness evidence differs")
        return self


def request_control_readiness_evidence(
    **fields: object,
) -> RequestControlReadinessEvidence:
    if "ready_record_sha256" in fields or "record_sha256" in fields:
        raise ValueError("request-control readiness identities are derived")
    worker = fields.get("worker")
    broker = fields.get("broker")
    framework = fields.get("framework_thread_baseline")
    if (
        type(worker) is not ExactProcessIdentity
        or type(broker) is not ExactProcessIdentity
        or type(framework) is not FrameworkThreadBaseline
        or type(fields.get("controller_worker_thread_inventory"))
        is not NativeThreadInventory
        or type(fields.get("controller_worker_file_descriptor_inventory"))
        is not NativeFileDescriptorInventory
        or type(fields.get("controller_broker_thread_inventory"))
        is not NativeThreadInventory
        or type(fields.get("controller_broker_file_descriptor_inventory"))
        is not NativeFileDescriptorInventory
    ):
        raise ValueError("request-control readiness inputs differ")
    previous = str(fields.get("previous_record_sha256", "0" * 64))
    normalized = {
        **fields,
        "previous_record_sha256": previous,
    }
    ready_payload = {
        "schema_id": "parser-request-control-ready-v1",
        "attempt_id": normalized["attempt_id"],
        "attempt_nonce_sha256": normalized["attempt_nonce_sha256"],
        "scope_sha256": normalized["scope_sha256"],
        "worker": RequestControlReadinessEvidence._identity_mapping(worker),
        "broker": RequestControlReadinessEvidence._identity_mapping(broker),
        "expected_request_count": normalized["expected_request_count"],
        "framework_thread_baseline": framework.model_dump(mode="json"),
        "ready_at_monotonic_ns": normalized["ready_at_monotonic_ns"],
        "previous_record_sha256": previous,
    }
    normalized["ready_record_sha256"] = _canonical_hash(ready_payload)
    provisional = RequestControlReadinessEvidence.model_construct(
        **normalized, record_sha256="0" * 64
    )
    return RequestControlReadinessEvidence(
        **normalized,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),  # type: ignore[arg-type]
    )


KernelSandboxRole = Literal[
    "parser_worker", "tesseract_broker", "tesseract_child"
]
KernelSandboxProbeOperation = Literal[
    "ipv4_tcp_connect",
    "ipv6_tcp_connect",
    "ipv4_udp_sendto",
    "ipv6_udp_sendto",
    "unix_connect",
    "ipv4_bind_listen",
    "ipv6_bind_listen",
    "unix_bind",
    "hostname_resolution",
    "outside_create",
    "outside_truncate",
    "outside_rename",
    "outside_unlink",
    "outside_mkdir",
    "artifact_write",
    "artifact_truncate",
    "artifact_unlink",
    "tessdata_write",
    "tessdata_truncate",
    "tessdata_unlink",
    "staged_executable_write",
    "staged_executable_truncate",
    "staged_executable_unlink",
    "worker_broker_rpc_roundtrip",
    "worker_request_control_roundtrip",
    "worker_phase_control_roundtrip",
    "broker_worker_rpc_roundtrip",
    "broker_watchdog_roundtrip",
    "child_stdin_roundtrip",
    "child_stdout_roundtrip",
    "child_stderr_roundtrip",
    "child_ready_roundtrip",
    "child_release_roundtrip",
    "staged_executable_read",
    "tessdata_read",
    "input_read",
    "artifact_read",
    "worker_scratch_roundtrip",
]

KERNEL_SANDBOX_DENIED_OPERATIONS: tuple[str, ...] = (
    "ipv4_tcp_connect",
    "ipv6_tcp_connect",
    "ipv4_udp_sendto",
    "ipv6_udp_sendto",
    "unix_connect",
    "ipv4_bind_listen",
    "ipv6_bind_listen",
    "unix_bind",
    "hostname_resolution",
    "outside_create",
    "outside_truncate",
    "outside_rename",
    "outside_unlink",
    "outside_mkdir",
    "artifact_write",
    "artifact_truncate",
    "artifact_unlink",
    "tessdata_write",
    "tessdata_truncate",
    "tessdata_unlink",
    "staged_executable_write",
    "staged_executable_truncate",
    "staged_executable_unlink",
)
KERNEL_SANDBOX_ALLOWED_OPERATIONS: Mapping[str, tuple[str, ...]] = {
    "parser_worker": (
        "worker_broker_rpc_roundtrip",
        "worker_request_control_roundtrip",
        "worker_phase_control_roundtrip",
        "staged_executable_read",
        "tessdata_read",
        "input_read",
        "artifact_read",
        "worker_scratch_roundtrip",
    ),
    "tesseract_broker": (
        "broker_worker_rpc_roundtrip",
        "broker_watchdog_roundtrip",
        "staged_executable_read",
        "tessdata_read",
        "input_read",
        "artifact_read",
    ),
    "tesseract_child": (
        "staged_executable_read",
        "tessdata_read",
        "input_read",
        "artifact_read",
        "child_stdin_roundtrip",
        "child_stdout_roundtrip",
        "child_stderr_roundtrip",
        "child_ready_roundtrip",
        "child_release_roundtrip",
    ),
}
KERNEL_SANDBOX_NETWORK_OPERATIONS = frozenset(
    KERNEL_SANDBOX_DENIED_OPERATIONS[:9]
)
KERNEL_SANDBOX_TRAP_OPERATIONS = frozenset(
    {
        "ipv4_tcp_connect",
        "ipv6_tcp_connect",
        "ipv4_udp_sendto",
        "ipv6_udp_sendto",
        "unix_connect",
    }
)
KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS = frozenset(
    KERNEL_SANDBOX_DENIED_OPERATIONS[9:]
)
KERNEL_SANDBOX_ALLOWED_POLICY_ERRNOS = frozenset((1, 13))


def _kernel_sandbox_operations(role: str) -> tuple[str, ...]:
    allowed = KERNEL_SANDBOX_ALLOWED_OPERATIONS.get(role)
    if allowed is None:
        raise ValueError("kernel sandbox role differs")
    return KERNEL_SANDBOX_DENIED_OPERATIONS + allowed


def _kernel_sandbox_matrix_sha256(role: str) -> str:
    return _canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-matrix-v1",
            "role": role,
            "operations": _kernel_sandbox_operations(role),
        }
    )


class KernelSandboxProcessIdentity(ContractModel):
    role: KernelSandboxRole
    pid: PositiveInt
    start_abstime: PositiveInt
    parent_pid: PositiveInt
    process_group_id: PositiveInt
    session_id: PositiveInt
    real_uid: NonNegativeInt
    effective_uid: NonNegativeInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_identity(self) -> "KernelSandboxProcessIdentity":
        if self.real_uid == 0 or self.effective_uid == 0:
            raise ValueError("kernel sandbox process must be non-root")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox process identity differs")
        return self


class KernelSandboxAuthorityIdentity(ContractModel):
    role: Literal["logical_controller", "watchdog_launcher"]
    pid: PositiveInt
    start_abstime: PositiveInt
    parent_pid: PositiveInt
    process_group_id: PositiveInt
    session_id: PositiveInt
    real_uid: PositiveInt
    effective_uid: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_authority(self) -> "KernelSandboxAuthorityIdentity":
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox authority identity differs")
        return self


class KernelSandboxFileIdentity(ContractModel):
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    resolved_path_sha256: Sha256
    content_sha256: Sha256
    device: NonNegativeInt
    inode: PositiveInt
    mode: NonNegativeInt
    uid: NonNegativeInt
    effective_uid: PositiveInt
    nlink: Literal[1] = 1
    size_bytes: PositiveInt
    mtime_ns: PositiveInt
    ctime_ns: PositiveInt
    first_descriptor: NonNegativeInt
    first_open_flags: PositiveInt
    first_observed_at_monotonic_ns: PositiveInt
    second_descriptor: NonNegativeInt
    second_open_flags: PositiveInt
    second_observed_at_monotonic_ns: PositiveInt
    observations_used_nofollow: Literal[True] = True
    observations_hashed_open_descriptor: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_file(self) -> "KernelSandboxFileIdentity":
        if (
            not self.resolved_path.startswith("/")
            or os.path.normpath(self.resolved_path) != self.resolved_path
            or self.resolved_path_sha256
            != hashlib.sha256(self.resolved_path.encode("utf-8")).hexdigest()
            or (self.mode & 0o170000) != 0o100000
            or self.mode & (0o4000 | 0o2000)
            or stat.S_IMODE(self.mode) & 0o022
            or self.uid not in {0, self.effective_uid}
            or self.first_observed_at_monotonic_ns
            > self.second_observed_at_monotonic_ns
            or (self.first_open_flags & os.O_ACCMODE) != os.O_RDONLY
            or (self.second_open_flags & os.O_ACCMODE) != os.O_RDONLY
            or self.first_open_flags
            & (getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            != (getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            or self.second_open_flags
            & (getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            != (getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox file identity differs")
        return self


class KernelSandboxDirectoryIdentity(ContractModel):
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    resolved_path_sha256: Sha256
    device: NonNegativeInt
    inode: PositiveInt
    mode: NonNegativeInt
    uid: NonNegativeInt
    controller_euid: PositiveInt
    holder_pid: PositiveInt
    holder_start_abstime: PositiveInt
    nlink: PositiveInt
    held_directory_fd: NonNegativeInt
    held_open_flags: PositiveInt
    opened_at_monotonic_ns: PositiveInt
    first_path_observed_at_monotonic_ns: PositiveInt
    first_fstat_observed_at_monotonic_ns: PositiveInt
    second_fstat_observed_at_monotonic_ns: PositiveInt
    second_path_observed_at_monotonic_ns: PositiveInt
    closed_at_monotonic_ns: PositiveInt
    opened_fstat_sha256: Sha256
    final_fstat_sha256: Sha256
    first_path_identity_sha256: Sha256
    second_path_identity_sha256: Sha256
    campaign_private: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_directory(self) -> "KernelSandboxDirectoryIdentity":
        fstat_identity = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-held-directory-fstat-v1",
                "device": self.device,
                "inode": self.inode,
                "mode": self.mode,
                "uid": self.uid,
                "nlink": self.nlink,
            }
        )
        required_flags = (
            getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        if (
            not self.resolved_path.startswith("/")
            or os.path.normpath(self.resolved_path) != self.resolved_path
            or self.resolved_path_sha256
            != hashlib.sha256(self.resolved_path.encode("utf-8")).hexdigest()
            or stat.S_IFMT(self.mode) != stat.S_IFDIR
            or self.mode & (stat.S_ISUID | stat.S_ISGID)
            or stat.S_IMODE(self.mode) != 0o700
            or self.uid != self.controller_euid
            or required_flags == 0
            or self.held_open_flags & required_flags != required_flags
            or (self.held_open_flags & os.O_ACCMODE) != os.O_RDONLY
            or not (
                self.opened_at_monotonic_ns
                <= self.first_path_observed_at_monotonic_ns
                <= self.first_fstat_observed_at_monotonic_ns
                <= self.second_fstat_observed_at_monotonic_ns
                <= self.second_path_observed_at_monotonic_ns
                <= self.closed_at_monotonic_ns
            )
            or self.opened_fstat_sha256 != fstat_identity
            or self.final_fstat_sha256 != fstat_identity
            or self.first_path_identity_sha256 != fstat_identity
            or self.second_path_identity_sha256 != fstat_identity
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox directory identity differs")
        return self


class KernelSandboxDirectoryOperationAnchor(ContractModel):
    """Trusted-helper proof that a pathname syscall was anchored to a held dirfd."""

    root: KernelSandboxDirectoryIdentity
    helper_thread_count: Literal[1] = 1
    anchoring_kind: Literal["single-thread-fchdir-held-root-relative-v1"] = (
        "single-thread-fchdir-held-root-relative-v1"
    )
    held_directory_fd: NonNegativeInt
    primary_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    primary_path_bytes_hex: Annotated[str, Field(min_length=2, max_length=1_024)]
    primary_path_bytes_sha256: Sha256
    secondary_relative_path: Annotated[
        str | None, Field(default=None, max_length=512)
    ] = None
    secondary_path_bytes_hex: Annotated[
        str | None, Field(default=None, max_length=1_024)
    ] = None
    secondary_path_bytes_sha256: Sha256 | None = None
    fchdir_to_held_root_syscall_return: Literal[0] = 0
    operation_used_only_relative_paths: Literal[True] = True
    fchdir_restore_syscall_return: Literal[0] = 0
    anchored_at_monotonic_ns: PositiveInt
    restored_at_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_anchor(self) -> "KernelSandboxDirectoryOperationAnchor":
        primary = _portable_path(self.primary_relative_path)
        try:
            primary_bytes = primary.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ValueError("kernel sandbox relative target is not UTF-8") from error
        secondary = self.secondary_relative_path
        secondary_bytes = (
            _portable_path(secondary).encode("utf-8", errors="strict")
            if secondary is not None
            else None
        )
        if (
            len(PurePosixPath(primary).parts) != 1
            or self.held_directory_fd != self.root.held_directory_fd
            or self.primary_path_bytes_hex != primary_bytes.hex()
            or self.primary_path_bytes_sha256
            != hashlib.sha256(primary_bytes).hexdigest()
            or (secondary is None)
            != (self.secondary_path_bytes_hex is None)
            or (secondary is None)
            != (self.secondary_path_bytes_sha256 is None)
            or (
                secondary is not None
                and (
                    len(PurePosixPath(_portable_path(secondary)).parts) != 1
                    or self.secondary_path_bytes_hex != secondary_bytes.hex()
                    or self.secondary_path_bytes_sha256
                    != hashlib.sha256(secondary_bytes).hexdigest()
                )
            )
            or self.root.opened_at_monotonic_ns
            > self.anchored_at_monotonic_ns
            or self.anchored_at_monotonic_ns > self.restored_at_monotonic_ns
            or self.root.closed_at_monotonic_ns < self.restored_at_monotonic_ns
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox directory operation anchor differs")
        return self


def _kernel_sandbox_directory_inventory(
    raw: str,
) -> tuple[dict[str, object], ...]:
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("kernel sandbox directory inventory is not UTF-8") from error
    if len(encoded) > 1_048_576 or (encoded and not encoded.endswith(b"\n")):
        raise ValueError("kernel sandbox directory inventory framing differs")
    entries: list[dict[str, object]] = []
    for line in encoded.splitlines(keepends=True):
        try:
            value = json.loads(line)
        except (TypeError, ValueError) as error:
            raise ValueError("kernel sandbox directory inventory is invalid") from error
        expected = {
            "name",
            "device",
            "inode",
            "mode",
            "uid",
            "nlink",
            "size_bytes",
            "content_sha256",
        }
        if type(value) is not dict or set(value) != expected:
            raise ValueError("kernel sandbox directory inventory fields differ")
        name = value["name"]
        mode = value["mode"]
        content = value["content_sha256"]
        if (
            type(name) is not str
            or not name
            or "/" in name
            or name in {".", ".."}
            or type(value["device"]) is not int
            or type(value["inode"]) is not int
            or value["inode"] <= 0
            or type(mode) is not int
            or type(value["uid"]) is not int
            or value["uid"] < 0
            or type(value["nlink"]) is not int
            or value["nlink"] <= 0
            or type(value["size_bytes"]) is not int
            or value["size_bytes"] < 0
            or (
                stat.S_IFMT(mode) == stat.S_IFREG
                and (type(content) is not str or _SHA256.fullmatch(content) is None)
            )
            or (stat.S_IFMT(mode) != stat.S_IFREG and content is not None)
            or _semantic_json_bytes(value) + b"\n" != line
        ):
            raise ValueError("kernel sandbox directory inventory entry differs")
        entries.append(dict(value))
    names = tuple(str(item["name"]) for item in entries)
    if names != tuple(sorted(names)) or len(set(names)) != len(names):
        raise ValueError("kernel sandbox directory inventory order differs")
    return tuple(entries)


class KernelSandboxSentinelObservation(ContractModel):
    target_sha256: Sha256
    parent_directory_record_sha256: Sha256
    parent_directory_inventory_jsonl: Annotated[
        str, Field(max_length=1_048_576)
    ] = ""
    parent_directory_inventory_entry_count: NonNegativeInt
    parent_directory_inventory_sha256: Sha256
    observed_at_monotonic_ns: PositiveInt
    observed_by_controller: Literal[True] = True
    dac_write_authority_required: StrictBool
    parent_writable_by_effective_uid: StrictBool
    target_writable_by_effective_uid: StrictBool | None = None
    exists: StrictBool
    device: NonNegativeInt | None = None
    inode: PositiveInt | None = None
    mode: NonNegativeInt | None = None
    uid: NonNegativeInt | None = None
    nlink: PositiveInt | None = None
    size_bytes: NonNegativeInt | None = None
    content_sha256: Sha256 | None = None
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_sentinel(self) -> "KernelSandboxSentinelObservation":
        entries = _kernel_sandbox_directory_inventory(
            self.parent_directory_inventory_jsonl
        )
        identity = (
            self.device,
            self.inode,
            self.mode,
            self.uid,
            self.nlink,
            self.size_bytes,
            self.content_sha256,
        )
        if self.exists != all(value is not None for value in identity):
            raise ValueError("kernel sandbox sentinel existence differs")
        if (
            self.parent_directory_inventory_entry_count != len(entries)
            or self.parent_directory_inventory_sha256
            != hashlib.sha256(
                self.parent_directory_inventory_jsonl.encode("utf-8")
            ).hexdigest()
        ):
            raise ValueError("kernel sandbox parent inventory identity differs")
        if self.dac_write_authority_required:
            if (
                not self.parent_writable_by_effective_uid
                or (
                    self.exists
                    and self.target_writable_by_effective_uid is not True
                )
                or (
                    not self.exists
                    and self.target_writable_by_effective_uid is not None
                )
            ):
                raise ValueError("kernel sandbox DAC-positive authority differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox sentinel identity differs")
        return self


class KernelSandboxNetworkPositiveControl(ContractModel):
    """Controller-run same-EUID success transcript for one denied network syscall."""

    target_kind: Literal[
        "tcp_ipv4",
        "tcp_ipv6",
        "udp_ipv4",
        "udp_ipv6",
        "unix_stream",
        "bind_ipv4",
        "bind_ipv6",
        "bind_unix",
        "hostname",
    ]
    endpoint_sha256: Sha256
    target_sockaddr_hex: Annotated[str | None, Field(default=None, max_length=212)] = None
    target_sockaddr_length: Annotated[
        int | None, Field(default=None, strict=True, ge=3, le=106)
    ] = None
    target_sockaddr_sha256: Sha256 | None = None
    controller: NativeKernelProcessIdentity
    controller_effective_uid: PositiveInt
    control_nonce_sha256: Sha256
    syscall_stage: Literal["connect", "sendto", "bind", "getaddrinfo"]
    client_descriptor: NativeFileDescriptorIdentity | None = None
    server_descriptor: NativeFileDescriptorIdentity | None = None
    accepted_descriptor: NativeFileDescriptorIdentity | None = None
    controller_fd_inventory_during_control: NativeFileDescriptorInventory
    syscall_return: NonNegativeInt
    secondary_syscall_return: NonNegativeInt | None = None
    getsockname_syscall_return: Literal[0] | None = None
    listen_syscall_return: Literal[0] | None = None
    raw_errno: Literal[0] = 0
    payload_sha256: Sha256 | None = None
    payload_hex: Annotated[str | None, Field(default=None, max_length=256)] = None
    received_payload_sha256: Sha256 | None = None
    received_source_endpoint_sha256: Sha256 | None = None
    payload_size_bytes: NonNegativeInt
    bytes_sent: NonNegativeInt
    bytes_received: NonNegativeInt
    accept_count: NonNegativeInt
    datagram_count: NonNegativeInt
    getaddrinfo_results_jsonl: Annotated[
        str, Field(max_length=65_536)
    ] = ""
    getaddrinfo_result_count: NonNegativeInt
    getaddrinfo_results_sha256: Sha256
    started_monotonic_ns: PositiveInt
    completed_monotonic_ns: PositiveInt
    observed_by_controller: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_control(self) -> "KernelSandboxNetworkPositiveControl":
        expected_payload = b"KSNP1" + bytes.fromhex(self.control_nonce_sha256)
        if self.target_sockaddr_hex is None:
            target_sockaddr = None
        else:
            try:
                target_sockaddr = bytes.fromhex(self.target_sockaddr_hex)
            except ValueError as error:
                raise ValueError(
                    "kernel sandbox positive-control sockaddr is invalid"
                ) from error
        if (
            (self.target_kind == "hostname")
            != (target_sockaddr is None)
            or (
                target_sockaddr is None
                and (
                    self.target_sockaddr_length is not None
                    or self.target_sockaddr_sha256 is not None
                )
            )
            or (
                target_sockaddr is not None
                and (
                    self.target_sockaddr_length != len(target_sockaddr)
                    or self.target_sockaddr_sha256
                    != hashlib.sha256(target_sockaddr).hexdigest()
                )
            )
        ):
            raise ValueError("kernel sandbox positive-control sockaddr differs")
        try:
            result_bytes = self.getaddrinfo_results_jsonl.encode(
                "utf-8", errors="strict"
            )
        except UnicodeError as error:
            raise ValueError("kernel sandbox addrinfo control is not UTF-8") from error
        result_lines = result_bytes.splitlines(keepends=True)
        if (
            (result_bytes and not result_bytes.endswith(b"\n"))
            or self.getaddrinfo_result_count != len(result_lines)
            or self.getaddrinfo_results_sha256
            != hashlib.sha256(result_bytes).hexdigest()
            or self.started_monotonic_ns > self.completed_monotonic_ns
        ):
            raise ValueError("kernel sandbox positive-control framing differs")
        for line in result_lines:
            try:
                value = json.loads(line)
            except (TypeError, ValueError) as error:
                raise ValueError("kernel sandbox addrinfo control is invalid") from error
            if (
                type(value) is not dict
                or set(value)
                != {"family", "socket_type", "protocol", "address", "port"}
                or type(value["family"]) is not int
                or type(value["socket_type"]) is not int
                or type(value["protocol"]) is not int
                or type(value["address"]) is not str
                or not value["address"]
                or type(value["port"]) is not int
                or not 0 <= value["port"] <= 65_535
                or _semantic_json_bytes(value) + b"\n" != line
            ):
                raise ValueError("kernel sandbox addrinfo result differs")
        stream = self.target_kind in {"tcp_ipv4", "tcp_ipv6", "unix_stream"}
        datagram = self.target_kind in {"udp_ipv4", "udp_ipv6"}
        bind = self.target_kind in {"bind_ipv4", "bind_ipv6", "bind_unix"}
        hostname = self.target_kind == "hostname"
        descriptors = (
            self.client_descriptor,
            self.server_descriptor,
            self.accepted_descriptor,
        )
        retained_descriptors = tuple(
            item for item in descriptors if item is not None
        )
        inventory_by_fd = {
            item.fd: item
            for item in self.controller_fd_inventory_during_control.descriptors
        }
        if (
            self.controller_fd_inventory_during_control.process != self.controller
            or any(inventory_by_fd.get(item.fd) != item for item in retained_descriptors)
            or self.started_monotonic_ns
            > self.controller_fd_inventory_during_control.first_scan_started_monotonic_ns
            or self.controller_fd_inventory_during_control.second_scan_completed_monotonic_ns
            > self.completed_monotonic_ns
            or (
                self.payload_sha256 is None
                and (
                    self.payload_hex is not None
                    or self.received_payload_sha256 is not None
                )
            )
            or (
                self.payload_sha256 is not None
                and (
                    self.payload_hex != expected_payload.hex()
                    or self.payload_sha256
                    != hashlib.sha256(expected_payload).hexdigest()
                    or self.received_payload_sha256 != self.payload_sha256
                )
            )
        ):
            raise ValueError("kernel sandbox positive-control FD/payload differs")
        if hostname:
            valid = (
                self.syscall_stage == "getaddrinfo"
                and all(item is None for item in descriptors)
                and self.syscall_return == 0
                and self.secondary_syscall_return is None
                and self.getsockname_syscall_return is None
                and self.listen_syscall_return is None
                and self.payload_sha256 is None
                and self.payload_hex is None
                and self.received_payload_sha256 is None
                and self.received_source_endpoint_sha256 is None
                and self.payload_size_bytes == 0
                and self.bytes_sent == 0
                and self.bytes_received == 0
                and self.accept_count == 0
                and self.datagram_count == 0
                and self.getaddrinfo_result_count > 0
            )
        elif bind:
            valid = (
                self.syscall_stage == "bind"
                and self.client_descriptor is not None
                and self.client_descriptor.socket is not None
                and self.server_descriptor is None
                and self.accepted_descriptor is None
                and self.syscall_return == 0
                and self.secondary_syscall_return is None
                and self.getsockname_syscall_return == 0
                and self.listen_syscall_return == 0
                and self.payload_sha256 is None
                and self.payload_hex is None
                and self.received_payload_sha256 is None
                and self.received_source_endpoint_sha256 is None
                and self.payload_size_bytes == 0
                and self.bytes_sent == 0
                and self.bytes_received == 0
                and self.accept_count == 0
                and self.datagram_count == 0
                and self.getaddrinfo_result_count == 0
            )
        elif datagram:
            valid = (
                self.syscall_stage == "sendto"
                and self.client_descriptor is not None
                and self.client_descriptor.socket is not None
                and self.server_descriptor is not None
                and self.server_descriptor.socket is not None
                and self.accepted_descriptor is None
                and self.syscall_return > 0
                and self.secondary_syscall_return == self.syscall_return
                and self.getsockname_syscall_return is None
                and self.listen_syscall_return is None
                and self.payload_sha256 is not None
                and self.client_descriptor.socket is not None
                and self.received_source_endpoint_sha256
                == self.client_descriptor.socket.local_identity_sha256
                and self.payload_size_bytes == self.syscall_return
                and self.bytes_sent == self.syscall_return
                and self.bytes_received == self.syscall_return
                and self.accept_count == 0
                and self.datagram_count == 1
                and self.getaddrinfo_result_count == 0
            )
        else:
            valid = (
                stream
                and self.syscall_stage == "connect"
                and self.client_descriptor is not None
                and self.client_descriptor.socket is not None
                and self.server_descriptor is not None
                and self.server_descriptor.socket is not None
                and self.accepted_descriptor is not None
                and self.accepted_descriptor.socket is not None
                and self.syscall_return == 0
                and self.secondary_syscall_return
                == self.accepted_descriptor.fd
                and self.getsockname_syscall_return is None
                and self.listen_syscall_return is None
                and self.payload_sha256 is not None
                and self.client_descriptor.socket is not None
                and self.accepted_descriptor.socket is not None
                and self.client_descriptor.socket.local_identity_sha256
                == self.accepted_descriptor.socket.peer_identity_sha256
                and self.client_descriptor.socket.peer_identity_sha256
                == self.accepted_descriptor.socket.local_identity_sha256
                and self.received_source_endpoint_sha256
                == self.client_descriptor.socket.local_identity_sha256
                and self.payload_size_bytes > 0
                and self.bytes_sent == self.payload_size_bytes
                and self.bytes_received == self.payload_size_bytes
                and self.accept_count == 1
                and self.datagram_count == 0
                and self.getaddrinfo_result_count == 0
            )
        if (
            not valid
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox network positive control differs")
        return self


class KernelSandboxNetworkTarget(ContractModel):
    target_kind: Literal[
        "tcp_ipv4",
        "tcp_ipv6",
        "udp_ipv4",
        "udp_ipv6",
        "unix_stream",
        "bind_ipv4",
        "bind_ipv6",
        "bind_unix",
        "hostname",
    ]
    address_family: Literal["none", "AF_INET", "AF_INET6", "AF_UNIX"]
    ip_literal: Annotated[str | None, Field(default=None, max_length=64)] = None
    port: Annotated[int | None, Field(default=None, strict=True, ge=0, le=65_535)] = None
    unix_root: KernelSandboxDirectoryIdentity | None = None
    unix_relative_path: Annotated[
        str | None, Field(default=None, max_length=128)
    ] = None
    unix_sockaddr_hex: Annotated[
        str | None, Field(default=None, max_length=212)
    ] = None
    unix_sockaddr_length: Annotated[
        int | None, Field(default=None, strict=True, ge=3, le=106)
    ] = None
    unix_sockaddr_sha256: Sha256 | None = None
    hostname: Annotated[str | None, Field(default=None, max_length=253)] = None
    endpoint_sha256: Sha256
    positive_control: KernelSandboxNetworkPositiveControl
    controller_prebound: StrictBool
    positive_control_started_monotonic_ns: PositiveInt
    positive_control_completed_monotonic_ns: PositiveInt
    positive_control_syscall_stage: Literal[
        "connect", "sendto", "bind", "getaddrinfo"
    ]
    positive_control_syscall_return: NonNegativeInt
    positive_control_raw_errno: Literal[0] = 0
    positive_control_bytes_sent: NonNegativeInt
    positive_control_bytes_received: NonNegativeInt
    positive_control_succeeded: Literal[True] = True
    target_sha256: Sha256

    @model_validator(mode="after")
    def validate_target(self) -> "KernelSandboxNetworkTarget":
        expected_sockaddr: bytes | None
        if self.address_family == "AF_INET" and self.ip_literal is not None:
            expected_sockaddr = (
                bytes((16, int(socket.AF_INET)))
                + int(self.port or 0).to_bytes(2, "big")
                + socket.inet_pton(socket.AF_INET, self.ip_literal)
                + b"\0" * 8
            )
        elif self.address_family == "AF_INET6" and self.ip_literal is not None:
            expected_sockaddr = (
                bytes((28, int(socket.AF_INET6)))
                + int(self.port or 0).to_bytes(2, "big")
                + b"\0" * 4
                + socket.inet_pton(socket.AF_INET6, self.ip_literal)
                + b"\0" * 4
            )
        elif (
            self.address_family == "AF_UNIX"
            and self.unix_relative_path is not None
        ):
            path_bytes = self.unix_relative_path.encode("utf-8", errors="strict")
            expected_sockaddr = bytes((3 + len(path_bytes), int(socket.AF_UNIX))) + (
                path_bytes + b"\0"
            )
        else:
            expected_sockaddr = None
        expected_endpoint = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-network-endpoint-v1",
                "target_kind": self.target_kind,
                "address_family": self.address_family,
                "ip_literal": self.ip_literal,
                "port": self.port,
                "unix_root_record_sha256": (
                    self.unix_root.record_sha256
                    if self.unix_root is not None
                    else None
                ),
                "unix_relative_path": self.unix_relative_path,
                "unix_sockaddr_sha256": self.unix_sockaddr_sha256,
                "hostname": self.hostname,
            }
        )
        if self.positive_control_started_monotonic_ns > (
            self.positive_control_completed_monotonic_ns
        ):
            raise ValueError("kernel sandbox network positive control differs")
        if self.target_kind in {"tcp_ipv4", "udp_ipv4", "bind_ipv4"}:
            if (
                self.address_family != "AF_INET"
                or self.ip_literal != "127.0.0.1"
                or self.port is None
                or self.unix_root is not None
                or self.unix_relative_path is not None
                or self.hostname is not None
            ):
                raise ValueError("kernel sandbox IPv4 target differs")
        elif self.target_kind in {"tcp_ipv6", "udp_ipv6", "bind_ipv6"}:
            if (
                self.address_family != "AF_INET6"
                or self.ip_literal != "::1"
                or self.port is None
                or self.unix_root is not None
                or self.unix_relative_path is not None
                or self.hostname is not None
            ):
                raise ValueError("kernel sandbox IPv6 target differs")
        elif self.target_kind in {"unix_stream", "bind_unix"}:
            assert self.unix_root is not None
            assert self.unix_relative_path is not None
            # The trusted helper first fchdir(2)s to unix_root's held fd, so
            # the actual sockaddr contains only this single relative name.
            path_bytes = self.unix_relative_path.encode("utf-8", errors="strict")
            raw_sockaddr = expected_sockaddr
            assert raw_sockaddr is not None
            if (
                self.address_family != "AF_UNIX"
                or self.ip_literal is not None
                or self.port is not None
                or self.unix_root is None
                or self.unix_relative_path is None
                or len(PurePosixPath(_portable_path(self.unix_relative_path)).parts)
                != 1
                or self.hostname is not None
                or self.controller_prebound
                != (self.target_kind == "unix_stream")
                or len(path_bytes) > 103
                or self.unix_sockaddr_hex != raw_sockaddr.hex()
                or self.unix_sockaddr_length != len(raw_sockaddr)
                or self.unix_sockaddr_sha256
                != hashlib.sha256(raw_sockaddr).hexdigest()
            ):
                raise ValueError("kernel sandbox AF_UNIX target differs")
        elif (
            self.target_kind != "hostname"
            or self.address_family != "none"
            or self.ip_literal is not None
            or self.port is not None
            or self.unix_root is not None
            or self.unix_relative_path is not None
            or self.unix_sockaddr_hex is not None
            or self.unix_sockaddr_length is not None
            or self.unix_sockaddr_sha256 is not None
            or self.hostname is None
            or not self.hostname.endswith(".local")
            or not re.fullmatch(r"[a-z0-9-]{1,63}\.local", self.hostname)
            or self.controller_prebound
        ):
            raise ValueError("kernel sandbox hostname target differs")
        if self.target_kind not in {"unix_stream", "bind_unix"} and any(
            value is not None
            for value in (
                self.unix_sockaddr_hex,
                self.unix_sockaddr_length,
                self.unix_sockaddr_sha256,
            )
        ):
            raise ValueError("non-AF_UNIX target retained raw sockaddr")
        bind_inet = self.target_kind in {"bind_ipv4", "bind_ipv6"}
        bind = bind_inet or self.target_kind == "bind_unix"
        stream = self.target_kind in {"tcp_ipv4", "tcp_ipv6", "unix_stream"}
        expected_positive_stage = (
            "sendto"
            if self.target_kind in {"udp_ipv4", "udp_ipv6"}
            else "bind"
            if bind
            else "getaddrinfo"
            if self.target_kind == "hostname"
            else "connect"
        )
        if (
            bind_inet != (self.port == 0)
            or (self.target_kind == "bind_unix" and self.port is not None)
            or (
                self.target_kind
                in {"tcp_ipv4", "tcp_ipv6", "udp_ipv4", "udp_ipv6"}
                and (self.port is None or self.port < 1_024)
            )
            or self.controller_prebound
            != (not bind and self.target_kind != "hostname")
            or self.positive_control_syscall_stage != expected_positive_stage
            or self.endpoint_sha256 != expected_endpoint
            or self.positive_control.target_kind != self.target_kind
            or self.positive_control.endpoint_sha256 != expected_endpoint
            or (
                expected_sockaddr is None
                and (
                    self.positive_control.target_sockaddr_hex is not None
                    or self.positive_control.target_sockaddr_length is not None
                    or self.positive_control.target_sockaddr_sha256 is not None
                )
            )
            or (
                expected_sockaddr is not None
                and (
                    self.positive_control.target_sockaddr_hex
                    != expected_sockaddr.hex()
                    or self.positive_control.target_sockaddr_length
                    != len(expected_sockaddr)
                    or self.positive_control.target_sockaddr_sha256
                    != hashlib.sha256(expected_sockaddr).hexdigest()
                )
            )
            or self.positive_control.started_monotonic_ns
            != self.positive_control_started_monotonic_ns
            or self.positive_control.completed_monotonic_ns
            != self.positive_control_completed_monotonic_ns
            or self.positive_control.syscall_stage
            != self.positive_control_syscall_stage
            or self.positive_control.syscall_return
            != self.positive_control_syscall_return
            or self.positive_control.bytes_sent
            != self.positive_control_bytes_sent
            or self.positive_control.bytes_received
            != self.positive_control_bytes_received
            or (
                self.target_kind in {"udp_ipv4", "udp_ipv6"}
                and (
                    self.positive_control_syscall_return <= 0
                    or self.positive_control_bytes_sent
                    != self.positive_control_syscall_return
                    or self.positive_control_bytes_received
                    != self.positive_control_syscall_return
                )
            )
            or (
                stream
                and (
                    self.positive_control_syscall_return != 0
                    or self.positive_control_bytes_sent <= 0
                    or self.positive_control_bytes_received
                    != self.positive_control_bytes_sent
                )
            )
            or (
                not stream
                and self.target_kind not in {"udp_ipv4", "udp_ipv6"}
                and (
                    self.positive_control_syscall_return != 0
                    or self.positive_control_bytes_sent
                    or self.positive_control_bytes_received
                )
            )
        ):
            raise ValueError("kernel sandbox network target authority differs")
        if self.target_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"target_sha256"})
        ):
            raise ValueError("kernel sandbox network target identity differs")
        return self


class KernelSandboxTrapObservation(ContractModel):
    trap_kind: Literal[
        "tcp_ipv4", "tcp_ipv6", "udp_ipv4", "udp_ipv6", "unix_stream"
    ]
    trap_nonce_sha256: Sha256
    target_sha256: Sha256
    target: KernelSandboxNetworkTarget
    address_family: Literal["AF_INET", "AF_INET6", "AF_UNIX"]
    socket_type: PositiveInt
    socket_protocol: NonNegativeInt
    controller_descriptor: NativeFileDescriptorIdentity
    # Darwin's socket fstat identity is not vnode-shaped: AF_INET/AF_INET6
    # commonly report (st_dev, st_ino) == (0, 0), while AF_UNIX can report a
    # negative st_dev.  Preserve those raw signed/nonnegative kernel values.
    device: int
    inode: NonNegativeInt
    getsockname_syscall_return: Literal[0] = 0
    getsockname_sockaddr_hex: Annotated[str, Field(max_length=212)]
    getsockname_sockaddr_length: Annotated[int, Field(strict=True, ge=3, le=106)]
    getsockname_sockaddr_sha256: Sha256
    getsockname_endpoint_sha256: Sha256
    socket_identity_sha256: Sha256
    bound_at_monotonic_ns: PositiveInt
    observed_at_monotonic_ns: PositiveInt
    accept_count: NonNegativeInt
    datagram_count: NonNegativeInt
    byte_count: NonNegativeInt
    observed_by_controller: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_trap(self) -> "KernelSandboxTrapObservation":
        if self.address_family == "AF_INET":
            expected_sockaddr = (
                bytes((16, int(socket.AF_INET)))
                + int(self.target.port or 0).to_bytes(2, "big")
                + socket.inet_pton(socket.AF_INET, str(self.target.ip_literal))
                + b"\0" * 8
            )
        elif self.address_family == "AF_INET6":
            expected_sockaddr = (
                bytes((28, int(socket.AF_INET6)))
                + int(self.target.port or 0).to_bytes(2, "big")
                + b"\0" * 4
                + socket.inet_pton(socket.AF_INET6, str(self.target.ip_literal))
                + b"\0" * 4
            )
        else:
            assert self.target.unix_relative_path is not None
            path_bytes = self.target.unix_relative_path.encode(
                "utf-8", errors="strict"
            )
            expected_sockaddr = bytes((3 + len(path_bytes), int(socket.AF_UNIX))) + (
                path_bytes + b"\0"
            )
        expected_endpoint = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-socket-endpoint-v1",
                "address_family": self.target.address_family,
                "ip_literal": self.target.ip_literal,
                "port": self.target.port,
                "unix_root_record_sha256": (
                    self.target.unix_root.record_sha256
                    if self.target.unix_root is not None
                    else None
                ),
                "unix_relative_path": self.target.unix_relative_path,
            }
        )
        expected_socket = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-trap-socket-v1",
                "trap_nonce_sha256": self.trap_nonce_sha256,
                "endpoint_sha256": expected_endpoint,
                "address_family": self.address_family,
                "socket_type": self.socket_type,
                "socket_protocol": self.socket_protocol,
                "device": self.device,
                "inode": self.inode,
                "controller_descriptor_record_sha256": (
                    self.controller_descriptor.record_sha256
                ),
            }
        )
        descriptor_socket = self.controller_descriptor.socket
        expected_family = {
            "AF_INET": int(socket.AF_INET),
            "AF_INET6": int(socket.AF_INET6),
            "AF_UNIX": int(socket.AF_UNIX),
        }[self.address_family]
        if (
            self.bound_at_monotonic_ns > self.observed_at_monotonic_ns
            or self.target.target_sha256 != self.target_sha256
            or self.target.target_kind != self.trap_kind
            or self.target.address_family != self.address_family
            or self.getsockname_sockaddr_hex != expected_sockaddr.hex()
            or self.getsockname_sockaddr_length != len(expected_sockaddr)
            or self.getsockname_sockaddr_sha256
            != hashlib.sha256(expected_sockaddr).hexdigest()
            or self.getsockname_endpoint_sha256 != expected_endpoint
            or self.socket_identity_sha256 != expected_socket
            or self.target.positive_control.server_descriptor
            != self.controller_descriptor
            or descriptor_socket is None
            or self.controller_descriptor.kernel_type != 2
            or not self.controller_descriptor.close_on_exec
            or descriptor_socket.family != expected_family
            or (descriptor_socket.socket_type & 0xF)
            != (self.socket_type & 0xF)
            or descriptor_socket.protocol != self.socket_protocol
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox trap identity differs")
        return self


class KernelSandboxCapabilityTranscriptRow(ContractModel):
    row_sequence: PositiveInt
    previous_row_sha256: Sha256
    owner_role: KernelSandboxRole
    capability_kind: Literal[
        "worker_broker_rpc",
        "request_control",
        "phase_control",
        "broker_watchdog",
        "child_stdin_pipe",
        "child_stdout_pipe",
        "child_stderr_pipe",
        "child_ready_pipe",
        "child_release_pipe",
    ]
    capability_record_sha256: Sha256
    channel_binding_sha256: Sha256
    owner_pid: PositiveInt
    owner_start_abstime: PositiveInt
    peer_pid: PositiveInt
    peer_start_abstime: PositiveInt
    controller_issued_nonce_sha256: Sha256
    peer_ack_sha256: Sha256
    bytes_sent: NonNegativeInt
    bytes_received: NonNegativeInt
    issued_at_monotonic_ns: PositiveInt
    acknowledged_at_monotonic_ns: PositiveInt
    retained_at_monotonic_ns: PositiveInt
    observed_by_controller: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_transcript(self) -> "KernelSandboxCapabilityTranscriptRow":
        expected_ack = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-capability-ack-v1",
                "channel_binding_sha256": self.channel_binding_sha256,
                "nonce_sha256": self.controller_issued_nonce_sha256,
                "owner_pid": self.owner_pid,
                "owner_start_abstime": self.owner_start_abstime,
                "peer_pid": self.peer_pid,
                "peer_start_abstime": self.peer_start_abstime,
            }
        )
        receive_only = self.capability_kind in {
            "child_stdin_pipe",
            "child_release_pipe",
        }
        send_only = self.capability_kind in {
            "child_stdout_pipe",
            "child_stderr_pipe",
            "child_ready_pipe",
        }
        if (
            self.peer_ack_sha256 != expected_ack
            or self.issued_at_monotonic_ns > self.acknowledged_at_monotonic_ns
            or self.acknowledged_at_monotonic_ns > self.retained_at_monotonic_ns
            or (
                receive_only
                and (self.bytes_sent != 0 or self.bytes_received <= 0)
            )
            or (
                send_only
                and (self.bytes_sent <= 0 or self.bytes_received != 0)
            )
            or (
                not receive_only
                and not send_only
                and (self.bytes_sent <= 0 or self.bytes_received <= 0)
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox capability transcript differs")
        return self


class KernelSandboxCapabilityIdentity(ContractModel):
    capability_kind: Literal[
        "worker_broker_rpc",
        "request_control",
        "phase_control",
        "broker_watchdog",
        "child_stdin_pipe",
        "child_stdout_pipe",
        "child_stderr_pipe",
        "child_ready_pipe",
        "child_release_pipe",
    ]
    descriptor: NonNegativeInt
    owner_descriptor: NativeFileDescriptorIdentity
    peer_descriptor: NativeFileDescriptorIdentity
    descriptor_kind: Literal["socket", "pipe"]
    close_on_exec: StrictBool
    owner_role: KernelSandboxRole
    peer_role: Literal[
        "logical_controller",
        "watchdog_launcher",
        "parser_worker",
        "tesseract_broker",
    ]
    owner_pid: PositiveInt
    owner_start_abstime: PositiveInt
    peer_pid: PositiveInt
    peer_start_abstime: PositiveInt
    channel_binding_sha256: Sha256
    peer_binding_sha256: Sha256
    controller_issued_nonce_sha256: Sha256
    controller_peer_ack_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_capability(self) -> "KernelSandboxCapabilityIdentity":
        owner_endpoint = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-capability-endpoint-v1",
                "role": self.owner_role,
                "pid": self.owner_pid,
                "start_abstime": self.owner_start_abstime,
                "descriptor": self.owner_descriptor.model_dump(mode="json"),
            }
        )
        peer_endpoint = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-capability-endpoint-v1",
                "role": self.peer_role,
                "pid": self.peer_pid,
                "start_abstime": self.peer_start_abstime,
                "descriptor": self.peer_descriptor.model_dump(mode="json"),
            }
        )
        expected_channel = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-capability-channel-v1",
                "capability_kind": self.capability_kind,
                "endpoint_sha256s": sorted((owner_endpoint, peer_endpoint)),
            }
        )
        expected_ack = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-capability-ack-v1",
                "channel_binding_sha256": self.channel_binding_sha256,
                "nonce_sha256": self.controller_issued_nonce_sha256,
                "owner_pid": self.owner_pid,
                "owner_start_abstime": self.owner_start_abstime,
                "peer_pid": self.peer_pid,
                "peer_start_abstime": self.peer_start_abstime,
            }
        )
        pipe_kinds = {
            "child_stdin_pipe",
            "child_stdout_pipe",
            "child_stderr_pipe",
            "child_ready_pipe",
            "child_release_pipe",
        }
        if (
            self.descriptor != self.owner_descriptor.fd
            or self.close_on_exec != self.owner_descriptor.close_on_exec
            or self.peer_binding_sha256 != peer_endpoint
            or self.channel_binding_sha256 != expected_channel
            or self.controller_peer_ack_sha256 != expected_ack
            or self.owner_role == self.peer_role
            or (self.capability_kind in pipe_kinds)
            != (self.descriptor_kind == "pipe")
            or (self.owner_descriptor.pipe is not None)
            != (self.descriptor_kind == "pipe")
            or (self.peer_descriptor.pipe is not None)
            != (self.descriptor_kind == "pipe")
            or (
                self.descriptor_kind == "socket"
                and (
                    self.owner_descriptor.socket is None
                    or self.peer_descriptor.socket is None
                    or self.owner_descriptor.socket.family != int(socket.AF_UNIX)
                    or self.peer_descriptor.socket.family != int(socket.AF_UNIX)
                    or (self.owner_descriptor.socket.socket_type & 0xF)
                    != int(socket.SOCK_STREAM)
                    or (self.peer_descriptor.socket.socket_type & 0xF)
                    != int(socket.SOCK_STREAM)
                    or self.owner_descriptor.socket.local_identity_sha256
                    != self.peer_descriptor.socket.peer_identity_sha256
                    or self.owner_descriptor.socket.peer_identity_sha256
                    != self.peer_descriptor.socket.local_identity_sha256
                )
            )
            or (
                self.descriptor_kind == "pipe"
                and (
                    self.owner_descriptor.pipe is None
                    or self.peer_descriptor.pipe is None
                    or self.owner_descriptor.pipe.local_handle_sha256
                    != self.peer_descriptor.pipe.peer_handle_sha256
                    or self.owner_descriptor.pipe.peer_handle_sha256
                    != self.peer_descriptor.pipe.local_handle_sha256
                )
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox capability identity differs")
        return self


class KernelSandboxNativeProbeInvocation(ContractModel):
    """Exact fixed-ABI arguments supplied to the pinned native helper."""

    schema_id: Literal["phase-latency-kernel-sandbox-native-invocation-v1"] = (
        "phase-latency-kernel-sandbox-native-invocation-v1"
    )
    abi_version: Literal[2] = 2
    helper_function: Literal[
        "lat_us02_sandbox_probe_path",
        "lat_us02_sandbox_probe_network",
    ]
    operation_code: Annotated[int, Field(strict=True, ge=1, le=6)]
    held_directory_fd: Annotated[int, Field(strict=True, ge=-1)]
    primary_relative_path_hex: Annotated[
        str | None, Field(default=None, max_length=1_024)
    ] = None
    secondary_relative_path_hex: Annotated[
        str | None, Field(default=None, max_length=1_024)
    ] = None
    open_flags: NonNegativeInt | None = None
    create_mode: NonNegativeInt | None = None
    domain: Annotated[int | None, Field(default=None, strict=True, ge=0)] = None
    socket_type: NonNegativeInt | None = None
    protocol: NonNegativeInt | None = None
    sockaddr_hex: Annotated[
        str | None, Field(default=None, max_length=212)
    ] = None
    payload_hex: Annotated[str, Field(max_length=512)]
    payload_size_bytes: NonNegativeInt
    payload_sha256: Sha256
    native_thread_identity_basis: Literal[
        "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    ] = "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    native_thread_ids_before: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=1)
    ]
    native_thread_ids_after: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=1)
    ]
    prior_signal_mask: tuple[PositiveInt, ...]
    blocked_signal_mask: tuple[PositiveInt, ...]
    restored_signal_mask: tuple[PositiveInt, ...]
    signals_blocked_at_monotonic_ns: PositiveInt
    syscall_returned_at_monotonic_ns: PositiveInt
    signals_restored_at_monotonic_ns: PositiveInt
    invocation_sha256: Sha256

    @model_validator(mode="after")
    def validate_invocation(self) -> "KernelSandboxNativeProbeInvocation":
        try:
            payload = bytes.fromhex(self.payload_hex)
            primary = (
                bytes.fromhex(self.primary_relative_path_hex)
                if self.primary_relative_path_hex is not None
                else None
            )
            secondary = (
                bytes.fromhex(self.secondary_relative_path_hex)
                if self.secondary_relative_path_hex is not None
                else None
            )
            sockaddr = (
                bytes.fromhex(self.sockaddr_hex)
                if self.sockaddr_hex is not None
                else None
            )
        except ValueError as error:
            raise ValueError("native sandbox invocation hex differs") from error
        path = self.helper_function == "lat_us02_sandbox_probe_path"
        blockable_signals = tuple(
            sorted(
                int(value)
                for value in signal.valid_signals()
                if value not in {signal.SIGKILL, signal.SIGSTOP}
            )
        )
        if (
            self.payload_size_bytes != len(payload)
            or self.payload_sha256 != hashlib.sha256(payload).hexdigest()
            or self.native_thread_ids_before != self.native_thread_ids_after
            or self.prior_signal_mask != self.restored_signal_mask
            or tuple(sorted(set(self.prior_signal_mask)))
            != self.prior_signal_mask
            or tuple(sorted(set(self.blocked_signal_mask)))
            != self.blocked_signal_mask
            or tuple(sorted(set(self.restored_signal_mask)))
            != self.restored_signal_mask
            or not set(self.prior_signal_mask).issubset(
                self.blocked_signal_mask
            )
            or self.blocked_signal_mask != blockable_signals
            or self.signals_blocked_at_monotonic_ns
            >= self.syscall_returned_at_monotonic_ns
            or self.syscall_returned_at_monotonic_ns
            >= self.signals_restored_at_monotonic_ns
            or path != (primary is not None)
            or path != (sockaddr is None)
            or path != (self.domain is None)
            or path != (self.socket_type is None)
            or path != (self.protocol is None)
            or (path and self.held_directory_fd < 0)
            or (
                not path
                and (
                    self.open_flags is not None
                    or self.create_mode is not None
                    or secondary is not None
                    or self.domain is None
                    or self.socket_type is None
                    or self.protocol is None
                    or self.operation_code > 3
                )
            )
            or self.invocation_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"invocation_sha256"})
            )
        ):
            raise ValueError("native sandbox invocation differs")
        return self


class KernelSandboxNativeProbeResult(ContractModel):
    """Lossless 48-byte little-endian native helper result."""

    schema_id: Literal["phase-latency-kernel-sandbox-native-result-v1"] = (
        "phase-latency-kernel-sandbox-native-result-v1"
    )
    abi_version: Literal[2] = 2
    byte_order: Literal["little-endian-darwin-v1"] = (
        "little-endian-darwin-v1"
    )
    struct_size_bytes: Literal[48] = 48
    raw_struct_hex: Annotated[str, Field(min_length=96, max_length=96)]
    raw_struct_sha256: Sha256
    operation_code: Annotated[int, Field(strict=True, ge=1, le=6)]
    terminal_stage_code: Annotated[int, Field(strict=True, ge=0, le=14)]
    raw_errno: NonNegativeInt
    syscall_return: Annotated[int, Field(strict=True)]
    bytes_sent: NonNegativeInt
    bytes_received: NonNegativeInt
    cwd_restore_return: Literal[0] = 0
    cwd_restore_errno: Literal[0] = 0
    top_level_return: Literal[0] = 0
    top_level_errno: NonNegativeInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_native_result(self) -> "KernelSandboxNativeProbeResult":
        try:
            raw = bytes.fromhex(self.raw_struct_hex)
            unpacked = struct.unpack("<iiiiqqqii", raw)
        except (ValueError, struct.error) as error:
            raise ValueError("native sandbox result bytes differ") from error
        expected = (
            self.abi_version,
            self.operation_code,
            self.terminal_stage_code,
            self.raw_errno,
            self.syscall_return,
            self.bytes_sent,
            self.bytes_received,
            self.cwd_restore_return,
            self.cwd_restore_errno,
        )
        if (
            unpacked != expected
            or self.raw_struct_sha256 != hashlib.sha256(raw).hexdigest()
            or self.top_level_errno != self.raw_errno
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("native sandbox result differs")
        return self


class KernelSandboxProbeRow(ContractModel):
    schema_id: Literal["phase-latency-kernel-sandbox-probe-row-v1"] = (
        "phase-latency-kernel-sandbox-probe-row-v1"
    )
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    role: KernelSandboxRole
    profile_sha256: Sha256
    profile_policy_sha256: Sha256
    helper_source_sha256: Sha256
    helper_executable_sha256: Sha256
    process: KernelSandboxProcessIdentity
    probe_sequence: PositiveInt
    previous_probe_record_sha256: Sha256
    probe_id: StableId
    probe_nonce_sha256: Sha256
    probe_capability_sha256: Sha256
    expected_operation_matrix_sha256: Sha256
    operation: KernelSandboxProbeOperation
    syscall_stage: Literal[
        "socket",
        "connect",
        "sendto",
        "bind",
        "listen",
        "getaddrinfo",
        "open",
        "write",
        "ftruncate",
        "rename",
        "unlink",
        "mkdir",
        "read",
        "fsync",
        "send",
        "recv",
        "complete",
    ]
    address_family: Literal["none", "AF_INET", "AF_INET6", "AF_UNIX"]
    socket_type: NonNegativeInt | None = None
    socket_protocol: NonNegativeInt | None = None
    open_flags: NonNegativeInt | None = None
    create_mode: NonNegativeInt | None = None
    target_sha256: Sha256
    network_target: KernelSandboxNetworkTarget | None = None
    directory_operation_anchor: KernelSandboxDirectoryOperationAnchor | None = None
    secondary_target_sha256: Sha256 | None = None
    policy_target_fixture_sha256: Sha256 | None = None
    known_read_fixture_sha256: Sha256 | None = None
    syscall_parameters_sha256: Sha256
    started_monotonic_ns: PositiveInt
    completed_monotonic_ns: PositiveInt
    errno_initialized_zero: Literal[True] = True
    syscall_return: Annotated[int, Field(strict=True)] | None = None
    raw_errno: NonNegativeInt
    getaddrinfo_return_eai: Annotated[int, Field(strict=True)] | None = None
    bytes_sent: NonNegativeInt
    bytes_received: NonNegativeInt
    trap_before: KernelSandboxTrapObservation | None = None
    trap_after: KernelSandboxTrapObservation | None = None
    target_before: KernelSandboxSentinelObservation | None = None
    target_after: KernelSandboxSentinelObservation | None = None
    secondary_target_before: KernelSandboxSentinelObservation | None = None
    secondary_target_after: KernelSandboxSentinelObservation | None = None
    allowed_read_sha256: Sha256 | None = None
    allowed_read_bytes: NonNegativeInt | None = None
    intermediate_identity_sha256: Sha256 | None = None
    capability_identity: KernelSandboxCapabilityIdentity | None = None
    frame_nonce_sha256: Sha256 | None = None
    peer_ack_nonce_sha256: Sha256 | None = None
    controller_observation_sha256: Sha256
    native_invocation: KernelSandboxNativeProbeInvocation | None = None
    native_result: KernelSandboxNativeProbeResult | None = None
    disposition: Literal["denied", "allowed"]
    authoritative_kernel_probe: StrictBool
    record_sha256: Sha256

    @staticmethod
    def _sentinel_state(value: KernelSandboxSentinelObservation) -> tuple[object, ...]:
        return (
            value.target_sha256,
            value.parent_directory_record_sha256,
            value.parent_directory_inventory_jsonl,
            value.parent_directory_inventory_entry_count,
            value.parent_directory_inventory_sha256,
            value.dac_write_authority_required,
            value.parent_writable_by_effective_uid,
            value.target_writable_by_effective_uid,
            value.exists,
            value.device,
            value.inode,
            value.mode,
            value.uid,
            value.nlink,
            value.size_bytes,
            value.content_sha256,
        )

    @staticmethod
    def _trap_state(value: KernelSandboxTrapObservation) -> tuple[object, ...]:
        return (
            value.trap_kind,
            value.trap_nonce_sha256,
            value.target_sha256,
            value.target,
            value.address_family,
            value.socket_type,
            value.socket_protocol,
            value.device,
            value.inode,
            value.bound_at_monotonic_ns,
            value.accept_count,
            value.datagram_count,
            value.byte_count,
        )

    @model_validator(mode="after")
    def validate_probe(self) -> "KernelSandboxProbeRow":
        if (
            self.process.role != self.role
            or self.expected_operation_matrix_sha256
            != _kernel_sandbox_matrix_sha256(self.role)
            or self.probe_id
            != f"{self.role}-probe-{self.probe_sequence}-{self.operation}"
            or self.started_monotonic_ns > self.completed_monotonic_ns
        ):
            raise ValueError("kernel sandbox probe binding differs")
        if self.directory_operation_anchor is not None and not (
            self.started_monotonic_ns
            <= self.directory_operation_anchor.anchored_at_monotonic_ns
            <= self.directory_operation_anchor.restored_at_monotonic_ns
            <= self.completed_monotonic_ns
        ):
            raise ValueError("kernel sandbox directory anchor timing differs")
        cloexec = getattr(os, "O_CLOEXEC", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        network_grammar: dict[str, tuple[str, str, int, int, bool, str]] = {
            "ipv4_tcp_connect": (
                "connect",
                "AF_INET",
                int(socket.SOCK_STREAM),
                int(socket.IPPROTO_TCP),
                True,
                "tcp_ipv4",
            ),
            "ipv6_tcp_connect": (
                "connect",
                "AF_INET6",
                int(socket.SOCK_STREAM),
                int(socket.IPPROTO_TCP),
                True,
                "tcp_ipv6",
            ),
            "ipv4_udp_sendto": (
                "sendto",
                "AF_INET",
                int(socket.SOCK_DGRAM),
                int(socket.IPPROTO_UDP),
                True,
                "udp_ipv4",
            ),
            "ipv6_udp_sendto": (
                "sendto",
                "AF_INET6",
                int(socket.SOCK_DGRAM),
                int(socket.IPPROTO_UDP),
                True,
                "udp_ipv6",
            ),
            "unix_connect": (
                "connect",
                "AF_UNIX",
                int(socket.SOCK_STREAM),
                0,
                True,
                "unix_stream",
            ),
            "ipv4_bind_listen": (
                "bind",
                "AF_INET",
                int(socket.SOCK_STREAM),
                int(socket.IPPROTO_TCP),
                False,
                "bind_ipv4",
            ),
            "ipv6_bind_listen": (
                "bind",
                "AF_INET6",
                int(socket.SOCK_STREAM),
                int(socket.IPPROTO_TCP),
                False,
                "bind_ipv6",
            ),
            "unix_bind": (
                "bind",
                "AF_UNIX",
                int(socket.SOCK_STREAM),
                0,
                False,
                "bind_unix",
            ),
        }
        file_grammar: dict[str, tuple[str, int | None, int | None, bool, bool]] = {
            "outside_create": (
                "open",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | cloexec | nofollow,
                0o600,
                False,
                False,
            ),
            "outside_truncate": (
                "open",
                os.O_WRONLY | os.O_TRUNC | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "outside_rename": ("rename", None, None, True, True),
            "outside_unlink": ("unlink", None, None, True, False),
            "outside_mkdir": ("mkdir", None, 0o700, False, False),
            "artifact_write": (
                "open",
                os.O_WRONLY | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "artifact_truncate": (
                "open",
                os.O_WRONLY | os.O_TRUNC | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "artifact_unlink": ("unlink", None, None, True, False),
            "tessdata_write": (
                "open",
                os.O_WRONLY | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "tessdata_truncate": (
                "open",
                os.O_WRONLY | os.O_TRUNC | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "tessdata_unlink": ("unlink", None, None, True, False),
            "staged_executable_write": (
                "open",
                os.O_WRONLY | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "staged_executable_truncate": (
                "open",
                os.O_WRONLY | os.O_TRUNC | cloexec | nofollow,
                None,
                True,
                False,
            ),
            "staged_executable_unlink": ("unlink", None, None, True, False),
        }
        if self.operation in network_grammar:
            stage, family, sock_type, protocol, requires_trap, target_kind = network_grammar[
                self.operation
            ]
            if (
                self.syscall_stage != stage
                or self.address_family != family
                or self.socket_type != sock_type
                or self.socket_protocol != protocol
                or self.open_flags is not None
                or self.create_mode is not None
                or self.secondary_target_sha256 is not None
                or self.policy_target_fixture_sha256 is not None
                or self.known_read_fixture_sha256 is not None
                or self.network_target is None
                or self.network_target.target_kind != target_kind
                or self.network_target.address_family != family
                or self.network_target.target_sha256 != self.target_sha256
                or self.network_target.positive_control_completed_monotonic_ns
                >= self.started_monotonic_ns
                or requires_trap != (self.operation in KERNEL_SANDBOX_TRAP_OPERATIONS)
            ):
                raise ValueError("kernel sandbox network operation grammar differs")
            if self.operation in {"unix_connect", "unix_bind"}:
                target = self.network_target
                anchor = self.directory_operation_anchor
                if (
                    target.unix_root is None
                    or target.unix_relative_path is None
                    or anchor is None
                    or anchor.root != target.unix_root
                    or anchor.primary_relative_path != target.unix_relative_path
                    or anchor.secondary_relative_path is not None
                ):
                    raise ValueError("kernel sandbox AF_UNIX dirfd anchor differs")
            elif self.directory_operation_anchor is not None:
                raise ValueError("inet sandbox operation retained a dirfd anchor")
        elif self.operation == "hostname_resolution":
            if any(
                value is not None
                for value in (
                    self.socket_type,
                    self.socket_protocol,
                    self.open_flags,
                    self.create_mode,
                    self.secondary_target_sha256,
                    self.policy_target_fixture_sha256,
                    self.known_read_fixture_sha256,
                )
            ) or (
                self.syscall_stage != "getaddrinfo"
                or self.address_family != "none"
                or self.network_target is None
                or self.network_target.target_kind != "hostname"
                or self.network_target.target_sha256 != self.target_sha256
                or self.network_target.positive_control_completed_monotonic_ns
                >= self.started_monotonic_ns
            ):
                raise ValueError("kernel sandbox DNS operation grammar differs")
        elif self.operation in file_grammar:
            stage, flags, mode, target_exists, secondary_required = file_grammar[
                self.operation
            ]
            if (
                self.syscall_stage != stage
                or self.address_family != "none"
                or self.socket_type is not None
                or self.socket_protocol is not None
                or self.open_flags != flags
                or self.create_mode != mode
                or self.known_read_fixture_sha256 is not None
                or secondary_required
                != (self.secondary_target_sha256 is not None)
            ):
                raise ValueError("kernel sandbox file operation grammar differs")
            if (
                self.target_before is None
                or self.target_after is None
                or self.target_before.exists != target_exists
                or self.target_before.target_sha256 != self.target_sha256
                or self.target_after.target_sha256 != self.target_sha256
                or not self.target_before.dac_write_authority_required
                or not self.target_after.dac_write_authority_required
            ):
                raise ValueError("kernel sandbox file target authority differs")
            if secondary_required:
                if (
                    self.secondary_target_before is None
                    or self.secondary_target_after is None
                    or self.secondary_target_before.exists
                    or self.secondary_target_after.exists
                    or self.secondary_target_before.target_sha256
                    != self.secondary_target_sha256
                    or self.secondary_target_after.target_sha256
                    != self.secondary_target_sha256
                    or not self.secondary_target_before.dac_write_authority_required
                    or not self.secondary_target_after.dac_write_authority_required
                ):
                    raise ValueError("kernel sandbox rename authority differs")
            elif (
                self.secondary_target_before is not None
                or self.secondary_target_after is not None
            ):
                raise ValueError("non-rename probe retained secondary sentinels")
            if self.policy_target_fixture_sha256 is None:
                raise ValueError("kernel sandbox file target fixture is absent")
            anchor = self.directory_operation_anchor
            if (
                anchor is None
                or anchor.primary_path_bytes_sha256
                != hashlib.sha256(
                    anchor.primary_relative_path.encode("utf-8")
                ).hexdigest()
                or secondary_required
                != (anchor.secondary_relative_path is not None)
            ):
                raise ValueError("kernel sandbox file dirfd anchor differs")
        read_operations = {
            "staged_executable_read",
            "tessdata_read",
            "input_read",
            "artifact_read",
        }
        capability_operations = {
            "worker_broker_rpc_roundtrip": "worker_broker_rpc",
            "worker_request_control_roundtrip": "request_control",
            "worker_phase_control_roundtrip": "phase_control",
            "broker_worker_rpc_roundtrip": "worker_broker_rpc",
            "broker_watchdog_roundtrip": "broker_watchdog",
            "child_stdin_roundtrip": "child_stdin_pipe",
            "child_stdout_roundtrip": "child_stdout_pipe",
            "child_stderr_roundtrip": "child_stderr_pipe",
            "child_ready_roundtrip": "child_ready_pipe",
            "child_release_roundtrip": "child_release_pipe",
        }
        if self.operation in read_operations:
            if (
                self.syscall_stage != "read"
                or self.address_family != "none"
                or self.socket_type is not None
                or self.socket_protocol is not None
                or self.open_flags != (os.O_RDONLY | cloexec | nofollow)
                or self.create_mode is not None
                or self.secondary_target_sha256 is not None
                or self.policy_target_fixture_sha256 is not None
                or self.known_read_fixture_sha256 is None
            ):
                raise ValueError("kernel sandbox read operation grammar differs")
            if self.directory_operation_anchor is None:
                raise ValueError("kernel sandbox read dirfd anchor is absent")
        elif self.operation in capability_operations:
            expected_descriptor_kind = (
                "pipe"
                if capability_operations[self.operation].startswith("child_")
                else "socket"
            )
            if (
                self.syscall_stage != "complete"
                or (
                    expected_descriptor_kind == "socket"
                    and (
                        self.address_family != "AF_UNIX"
                        or self.socket_type != int(socket.SOCK_STREAM)
                        or self.socket_protocol != 0
                    )
                )
                or (
                    expected_descriptor_kind == "pipe"
                    and (
                        self.address_family != "none"
                        or self.socket_type is not None
                        or self.socket_protocol is not None
                    )
                )
                or self.open_flags is not None
                or self.create_mode is not None
                or self.secondary_target_sha256 is not None
                or self.policy_target_fixture_sha256 is not None
                or self.known_read_fixture_sha256 is not None
            ):
                raise ValueError("kernel sandbox capability grammar differs")
        elif self.operation == "worker_scratch_roundtrip":
            if (
                self.syscall_stage != "complete"
                or self.address_family != "none"
                or self.socket_type is not None
                or self.socket_protocol is not None
                or self.open_flags
                != (os.O_RDWR | os.O_CREAT | os.O_EXCL | cloexec | nofollow)
                or self.create_mode != 0o600
                or self.secondary_target_sha256 is not None
                or self.policy_target_fixture_sha256 is None
                or self.known_read_fixture_sha256 is not None
            ):
                raise ValueError("kernel sandbox scratch grammar differs")
            if self.directory_operation_anchor is None:
                raise ValueError("kernel sandbox scratch dirfd anchor is absent")
        elif (
            self.operation not in file_grammar
            and self.operation not in {"unix_connect", "unix_bind"}
            and self.directory_operation_anchor is not None
        ):
            raise ValueError("non-path probe retained a directory anchor")
        if self.operation not in {*network_grammar, "hostname_resolution"} and (
            self.network_target is not None
        ):
            raise ValueError("non-network probe retained a network target")
        parameters = {
            "syscall_stage": self.syscall_stage,
            "address_family": self.address_family,
            "socket_type": self.socket_type,
            "socket_protocol": self.socket_protocol,
            "open_flags": self.open_flags,
            "create_mode": self.create_mode,
            "target_sha256": self.target_sha256,
            "directory_operation_anchor_sha256": (
                self.directory_operation_anchor.record_sha256
                if self.directory_operation_anchor is not None
                else None
            ),
            "secondary_target_sha256": self.secondary_target_sha256,
            "policy_target_fixture_sha256": self.policy_target_fixture_sha256,
            "known_read_fixture_sha256": self.known_read_fixture_sha256,
        }
        if self.syscall_parameters_sha256 != _canonical_hash(parameters):
            raise ValueError("kernel sandbox syscall parameters differ")
        native_path_codes = {
            "outside_create": 1,
            "outside_truncate": 1,
            "outside_rename": 2,
            "outside_unlink": 3,
            "outside_mkdir": 4,
            "artifact_write": 1,
            "artifact_truncate": 1,
            "artifact_unlink": 3,
            "tessdata_write": 1,
            "tessdata_truncate": 1,
            "tessdata_unlink": 3,
            "staged_executable_write": 1,
            "staged_executable_truncate": 1,
            "staged_executable_unlink": 3,
            "staged_executable_read": 5,
            "tessdata_read": 5,
            "input_read": 5,
            "artifact_read": 5,
            "worker_scratch_roundtrip": 6,
        }
        native_network_codes = {
            "ipv4_tcp_connect": 1,
            "ipv6_tcp_connect": 1,
            "unix_connect": 1,
            "ipv4_udp_sendto": 2,
            "ipv6_udp_sendto": 2,
            "ipv4_bind_listen": 3,
            "ipv6_bind_listen": 3,
            "unix_bind": 3,
        }
        native_stage_codes = {
            "outside_create": 2,
            "outside_truncate": 2,
            "outside_rename": 6,
            "outside_unlink": 7,
            "outside_mkdir": 8,
            "artifact_write": 2,
            "artifact_truncate": 2,
            "artifact_unlink": 7,
            "tessdata_write": 2,
            "tessdata_truncate": 2,
            "tessdata_unlink": 7,
            "staged_executable_write": 2,
            "staged_executable_truncate": 2,
            "staged_executable_unlink": 7,
            "staged_executable_read": 5,
            "tessdata_read": 5,
            "input_read": 5,
            "artifact_read": 5,
            "worker_scratch_roundtrip": 7,
            "ipv4_tcp_connect": 10,
            "ipv6_tcp_connect": 10,
            "unix_connect": 10,
            "ipv4_udp_sendto": 11,
            "ipv6_udp_sendto": 11,
            "ipv4_bind_listen": 12,
            "ipv6_bind_listen": 12,
            "unix_bind": 12,
        }
        native_required = self.operation in {
            *native_path_codes,
            *native_network_codes,
        }
        if native_required != (self.native_invocation is not None) or (
            native_required != (self.native_result is not None)
        ):
            raise ValueError("kernel sandbox native helper evidence differs")
        if native_required:
            invocation = self.native_invocation
            result = self.native_result
            assert invocation is not None and result is not None
            path_probe = self.operation in native_path_codes
            operation_code = (
                native_path_codes[self.operation]
                if path_probe
                else native_network_codes[self.operation]
            )
            anchor = self.directory_operation_anchor
            target_sockaddr_hex = (
                self.network_target.positive_control.target_sockaddr_hex
                if self.network_target is not None
                else None
            )
            if (
                invocation.helper_function
                != (
                    "lat_us02_sandbox_probe_path"
                    if path_probe
                    else "lat_us02_sandbox_probe_network"
                )
                or invocation.operation_code != operation_code
                or result.operation_code != operation_code
                or result.terminal_stage_code
                != native_stage_codes[self.operation]
                or result.raw_errno != self.raw_errno
                or result.syscall_return != self.syscall_return
                or result.bytes_sent != self.bytes_sent
                or result.bytes_received != self.bytes_received
                or invocation.held_directory_fd
                != (
                    anchor.held_directory_fd
                    if anchor is not None
                    else -1
                )
                or invocation.primary_relative_path_hex
                != (
                    anchor.primary_path_bytes_hex
                    if path_probe and anchor is not None
                    else None
                )
                or invocation.secondary_relative_path_hex
                != (
                    anchor.secondary_path_bytes_hex
                    if path_probe and anchor is not None
                    else None
                )
                or invocation.open_flags
                != (self.open_flags if path_probe else None)
                or invocation.create_mode
                != (self.create_mode if path_probe else None)
                or invocation.domain
                != (
                    None
                    if path_probe
                    else {
                        "AF_INET": int(socket.AF_INET),
                        "AF_INET6": int(socket.AF_INET6),
                        "AF_UNIX": int(socket.AF_UNIX),
                    }[self.address_family]
                )
                or invocation.socket_type
                != (None if path_probe else self.socket_type)
                or invocation.protocol
                != (None if path_probe else self.socket_protocol)
                or invocation.sockaddr_hex
                != (None if path_probe else target_sockaddr_hex)
                or not (
                    self.started_monotonic_ns
                    <= invocation.signals_blocked_at_monotonic_ns
                    < invocation.syscall_returned_at_monotonic_ns
                    < invocation.signals_restored_at_monotonic_ns
                    <= self.completed_monotonic_ns
                )
                or (
                    anchor is not None
                    and anchor.helper_thread_count
                    != len(invocation.native_thread_ids_before)
                )
                or (
                    self.operation
                    in {"worker_scratch_roundtrip", "ipv4_udp_sendto", "ipv6_udp_sendto"}
                    and invocation.payload_size_bytes <= 0
                )
                or (
                    self.operation
                    not in {"worker_scratch_roundtrip", "ipv4_udp_sendto", "ipv6_udp_sendto"}
                    and invocation.payload_size_bytes != 0
                )
            ):
                raise ValueError("kernel sandbox native helper join differs")
        expected_probe_capability = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-probe-capability-v1",
                "attempt_nonce_sha256": self.attempt_nonce_sha256,
                "scope_sha256": self.scope_sha256,
                "role": self.role,
                "probe_sequence": self.probe_sequence,
                "probe_nonce_sha256": self.probe_nonce_sha256,
                "process_record_sha256": self.process.record_sha256,
                "helper_executable_sha256": self.helper_executable_sha256,
                "expected_operation_matrix_sha256": (
                    self.expected_operation_matrix_sha256
                ),
            }
        )
        if self.probe_capability_sha256 != expected_probe_capability:
            raise ValueError("kernel sandbox probe capability differs")
        denied = self.operation in KERNEL_SANDBOX_DENIED_OPERATIONS
        if denied != (self.disposition == "denied"):
            raise ValueError("kernel sandbox probe disposition differs")
        if self.operation == "hostname_resolution":
            if (
                self.getaddrinfo_return_eai in (None, 0)
                or self.syscall_return is not None
                or self.raw_errno != 0
                or self.authoritative_kernel_probe
            ):
                raise ValueError("supporting DNS denial evidence differs")
        elif denied:
            if (
                self.syscall_return != -1
                or self.raw_errno not in KERNEL_SANDBOX_ALLOWED_POLICY_ERRNOS
                or self.getaddrinfo_return_eai is not None
                or not self.authoritative_kernel_probe
                or self.bytes_sent
                or self.bytes_received
            ):
                raise ValueError("kernel sandbox syscall denial differs")
        elif (
            self.syscall_return is None
            or self.syscall_return < 0
            or self.raw_errno != 0
            or self.getaddrinfo_return_eai is not None
            or not self.authoritative_kernel_probe
        ):
            raise ValueError("kernel sandbox allowed control differs")
        if self.operation in KERNEL_SANDBOX_TRAP_OPERATIONS:
            if self.trap_before is None or self.trap_after is None:
                raise ValueError("kernel sandbox network probe lacks trap custody")
            if (
                self.trap_before.target_sha256 != self.target_sha256
                or self.trap_after.target_sha256 != self.target_sha256
                or self.trap_before.target != self.network_target
                or self.trap_after.target != self.network_target
                or self.trap_before.address_family != self.address_family
                or self.trap_before.socket_type != self.socket_type
                or self.trap_before.socket_protocol != self.socket_protocol
                or self.trap_before.observed_at_monotonic_ns
                > self.started_monotonic_ns
                or self.trap_after.observed_at_monotonic_ns
                < self.completed_monotonic_ns
                or self._trap_state(self.trap_before)
                != self._trap_state(self.trap_after)
                or any(
                    (
                        self.trap_after.accept_count,
                        self.trap_after.datagram_count,
                        self.trap_after.byte_count,
                    )
                )
            ):
                raise ValueError("kernel sandbox network trap observed traffic")
        elif self.trap_before is not None or self.trap_after is not None:
            raise ValueError("non-network probe retained a network trap")
        if self.operation == "unix_bind":
            if (
                self.network_target is None
                or self.network_target.unix_root is None
                or self.network_target.unix_relative_path is None
                or self.target_before is None
                or self.target_after is None
                or self.target_before.target_sha256 != self.target_sha256
                or self.target_after.target_sha256 != self.target_sha256
                or self.target_before.parent_directory_record_sha256
                != self.network_target.unix_root.record_sha256
                or self.target_after.parent_directory_record_sha256
                != self.network_target.unix_root.record_sha256
                or self.target_before.exists
                or self.target_after.exists
                or not self.target_before.parent_writable_by_effective_uid
                or not self.target_after.parent_writable_by_effective_uid
                or self._sentinel_state(self.target_before)
                != self._sentinel_state(self.target_after)
                or self.target_before.observed_at_monotonic_ns
                > self.started_monotonic_ns
                or self.target_after.observed_at_monotonic_ns
                < self.completed_monotonic_ns
            ):
                raise ValueError("kernel sandbox AF_UNIX bind target changed")
        if self.operation in KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS:
            if self.target_before is None or self.target_after is None:
                raise ValueError("kernel sandbox file denial lacks sentinels")
            if self._sentinel_state(self.target_before) != self._sentinel_state(
                self.target_after
            ) or (
                self.target_before.observed_at_monotonic_ns
                > self.started_monotonic_ns
                or self.target_after.observed_at_monotonic_ns
                < self.completed_monotonic_ns
            ):
                raise ValueError("kernel sandbox denied target changed")
            secondary = (
                self.secondary_target_before,
                self.secondary_target_after,
            )
            if (secondary[0] is None) != (secondary[1] is None) or (
                secondary[0] is not None
                and secondary[1] is not None
                and self._sentinel_state(secondary[0])
                != self._sentinel_state(secondary[1])
            ):
                raise ValueError("kernel sandbox denied secondary target changed")
        if self.operation in read_operations:
            if (
                self.allowed_read_sha256 is None
                or not self.allowed_read_bytes
                or self.syscall_return != self.allowed_read_bytes
                or self.bytes_received != self.allowed_read_bytes
                or self.bytes_sent
                or self.target_before is None
                or self.target_after is None
                or not self.target_before.exists
                or self._sentinel_state(self.target_before)
                != self._sentinel_state(self.target_after)
                or self.target_before.target_sha256 != self.target_sha256
                or self.target_before.content_sha256 != self.allowed_read_sha256
                or self.target_before.size_bytes != self.allowed_read_bytes
            ):
                raise ValueError("kernel sandbox allowed read lacks byte identity")
        elif self.allowed_read_sha256 is not None or self.allowed_read_bytes is not None:
            raise ValueError("non-read probe retained an allowed read identity")
        expected_capability = capability_operations.get(self.operation)
        if expected_capability is not None:
            receive_only = expected_capability in {
                "child_stdin_pipe",
                "child_release_pipe",
            }
            send_only = expected_capability in {
                "child_stdout_pipe",
                "child_stderr_pipe",
                "child_ready_pipe",
            }
            if (
                self.capability_identity is None
                or self.capability_identity.capability_kind != expected_capability
                or self.frame_nonce_sha256 is None
                or self.peer_ack_nonce_sha256 != self.frame_nonce_sha256
                or self.frame_nonce_sha256
                != self.capability_identity.controller_issued_nonce_sha256
                or (
                    receive_only
                    and (self.bytes_sent != 0 or self.bytes_received <= 0)
                )
                or (
                    send_only
                    and (self.bytes_sent <= 0 or self.bytes_received != 0)
                )
                or (
                    not receive_only
                    and not send_only
                    and (self.bytes_sent <= 0 or self.bytes_received <= 0)
                )
                or self.syscall_return != 0
                or self.target_sha256
                != self.capability_identity.record_sha256
            ):
                raise ValueError("kernel sandbox capability control differs")
        elif any(
            value is not None
            for value in (
                self.capability_identity,
                self.frame_nonce_sha256,
                self.peer_ack_nonce_sha256,
            )
        ):
            raise ValueError("non-capability probe retained capability identity")
        if self.operation == "worker_scratch_roundtrip":
            if (
                self.role != "parser_worker"
                or self.intermediate_identity_sha256 is None
                or self.target_before is None
                or self.target_after is None
                or self.target_before.exists
                or self.target_after.exists
                or self.syscall_return != 0
                or self.bytes_sent <= 0
                or self.bytes_received != self.bytes_sent
            ):
                raise ValueError("kernel sandbox scratch control differs")
        elif self.intermediate_identity_sha256 is not None:
            raise ValueError("non-scratch probe retained intermediate identity")
        expected_controller_observation = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-controller-observation-v1",
                "attempt_id": self.attempt_id,
                "role": self.role,
                "probe_sequence": self.probe_sequence,
                "probe_nonce_sha256": self.probe_nonce_sha256,
                "process_record_sha256": self.process.record_sha256,
                "started_monotonic_ns": self.started_monotonic_ns,
                "completed_monotonic_ns": self.completed_monotonic_ns,
                "syscall_parameters_sha256": self.syscall_parameters_sha256,
                "syscall_return": self.syscall_return,
                "raw_errno": self.raw_errno,
                "getaddrinfo_return_eai": self.getaddrinfo_return_eai,
                "bytes_sent": self.bytes_sent,
                "bytes_received": self.bytes_received,
                "native_invocation_sha256": (
                    self.native_invocation.invocation_sha256
                    if self.native_invocation is not None
                    else None
                ),
                "native_result_sha256": (
                    self.native_result.record_sha256
                    if self.native_result is not None
                    else None
                ),
                "trap_after_sha256": (
                    self.trap_after.record_sha256
                    if self.trap_after is not None
                    else None
                ),
                "target_after_sha256": (
                    self.target_after.record_sha256
                    if self.target_after is not None
                    else None
                ),
                "secondary_target_after_sha256": (
                    self.secondary_target_after.record_sha256
                    if self.secondary_target_after is not None
                    else None
                ),
                "capability_record_sha256": (
                    self.capability_identity.record_sha256
                    if self.capability_identity is not None
                    else None
                ),
            }
        )
        if self.controller_observation_sha256 != expected_controller_observation:
            raise ValueError("kernel sandbox controller observation differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox probe identity differs")
        return self


class KernelSandboxProfilePolicy(ContractModel):
    """Closed projection from which the exact Seatbelt profile is rendered."""

    schema_id: Literal["phase-latency-kernel-sandbox-profile-policy-v1"] = (
        "phase-latency-kernel-sandbox-profile-policy-v1"
    )
    role: KernelSandboxRole
    artifact_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    tessdata_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    request_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    input_probe_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    artifact_read_relative_path: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    tessdata_read_relative_path: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    input_probe_relative_path: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ] = "input.bin"
    immutable_executable: Annotated[str, Field(min_length=1, max_length=4_096)]
    outside_probe_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    network_trap_root: Annotated[str, Field(min_length=1, max_length=4_096)]
    artifact_probe_clone_root: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    tessdata_probe_clone_root: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    staged_executable_probe_clone_root: Annotated[
        str, Field(min_length=1, max_length=4_096)
    ]
    worker_scratch_root: Annotated[
        str | None, Field(default=None, max_length=4_096)
    ] = None
    artifact_root_sha256: Sha256
    tessdata_root_sha256: Sha256
    request_root_sha256: Sha256
    input_probe_root_sha256: Sha256
    immutable_executable_sha256: Sha256
    outside_probe_root_sha256: Sha256
    network_trap_root_sha256: Sha256
    artifact_probe_clone_root_sha256: Sha256
    tessdata_probe_clone_root_sha256: Sha256
    staged_executable_probe_clone_root_sha256: Sha256
    worker_scratch_root_sha256: Sha256 | None = None
    network_outbound_denied: Literal[True] = True
    network_inbound_denied: Literal[True] = True
    process_fork_denied: StrictBool
    deny_all_file_writes: StrictBool
    template_sha256: Sha256
    record_sha256: Sha256

    @staticmethod
    def _literal(path: str) -> str:
        if (
            not path.startswith("/")
            or "\x00" in path
            or "\n" in path
            or "\r" in path
        ):
            raise ValueError("kernel sandbox profile path differs")
        return json.dumps(path, ensure_ascii=True)

    def render_profile(self) -> str:
        clauses = [
            "(version 1)",
            "(allow default)",
            "(deny network-outbound)",
            "(deny network-inbound)",
        ]
        if self.process_fork_denied:
            clauses.append("(deny process-fork)")
        clauses.append(
            "(deny file-write* "
            f"(subpath {self._literal(self.artifact_root)}) "
            f"(subpath {self._literal(self.tessdata_root)}) "
            f"(literal {self._literal(self.immutable_executable)}))"
        )
        clauses.append(
            "(deny file-write* "
            f"(subpath {self._literal(self.artifact_probe_clone_root)}) "
            f"(subpath {self._literal(self.tessdata_probe_clone_root)}) "
            "(subpath "
            f"{self._literal(self.staged_executable_probe_clone_root)}))"
        )
        clauses.append(
            "(deny file-write* "
            f"(subpath {self._literal(self.input_probe_root)}) "
            f"(subpath {self._literal(self.network_trap_root)}))"
        )
        if self.deny_all_file_writes:
            clauses.extend(
                (
                    "(deny file-write* "
                    f"(subpath {self._literal(self.request_root)}))",
                    "(deny file-write*)",
                )
            )
        else:
            assert self.worker_scratch_root is not None
            clauses.append(
                "(deny file-write* (require-not "
                f"(subpath {self._literal(self.worker_scratch_root)})))"
            )
        rendered = "".join(clauses)
        if not rendered.isascii() or len(rendered.encode("ascii")) > 16 * 1024:
            raise ValueError("kernel sandbox profile exceeds its bound")
        return rendered

    @model_validator(mode="after")
    def validate_policy(self) -> "KernelSandboxProfilePolicy":
        path_fields = (
            (self.artifact_root, self.artifact_root_sha256),
            (self.tessdata_root, self.tessdata_root_sha256),
            (self.request_root, self.request_root_sha256),
            (self.input_probe_root, self.input_probe_root_sha256),
            (self.immutable_executable, self.immutable_executable_sha256),
            (self.outside_probe_root, self.outside_probe_root_sha256),
            (self.network_trap_root, self.network_trap_root_sha256),
            (
                self.artifact_probe_clone_root,
                self.artifact_probe_clone_root_sha256,
            ),
            (
                self.tessdata_probe_clone_root,
                self.tessdata_probe_clone_root_sha256,
            ),
            (
                self.staged_executable_probe_clone_root,
                self.staged_executable_probe_clone_root_sha256,
            ),
        )
        relative_paths = (
            self.artifact_read_relative_path,
            self.tessdata_read_relative_path,
            self.input_probe_relative_path,
        )
        if any(
            digest != hashlib.sha256(path.encode("utf-8")).hexdigest()
            for path, digest in path_fields
        ) or any(
            os.path.normpath(path) != path for path, _digest in path_fields
        ) or len({path for path, _digest in path_fields}) != len(path_fields) or any(
            PurePosixPath(path).is_absolute()
            or str(PurePosixPath(path)) != path
            or path in {".", ".."}
            or ".." in PurePosixPath(path).parts
            or "\x00" in path
            or "\n" in path
            for path in relative_paths
        ):
            raise ValueError("kernel sandbox profile path identity differs")
        protected_roots = (
            PurePosixPath(self.artifact_root),
            PurePosixPath(self.tessdata_root),
            PurePosixPath(self.request_root),
            PurePosixPath(self.input_probe_root),
            PurePosixPath(self.immutable_executable).parent,
            PurePosixPath(self.outside_probe_root),
            PurePosixPath(self.network_trap_root),
            PurePosixPath(self.artifact_probe_clone_root),
            PurePosixPath(self.tessdata_probe_clone_root),
            PurePosixPath(self.staged_executable_probe_clone_root),
        )
        if any(
            left == right or left in right.parents or right in left.parents
            for index, left in enumerate(protected_roots)
            for right in protected_roots[index + 1 :]
        ):
            raise ValueError("kernel sandbox profile roots overlap")
        if self.role == "parser_worker":
            if (
                not self.process_fork_denied
                or self.deny_all_file_writes
                or self.worker_scratch_root is None
                or self.worker_scratch_root != self.request_root
                or self.worker_scratch_root == "/"
                or os.path.normpath(self.worker_scratch_root)
                != self.worker_scratch_root
                or self.worker_scratch_root_sha256
                != hashlib.sha256(
                    self.worker_scratch_root.encode("utf-8")
                ).hexdigest()
            ):
                raise ValueError("worker sandbox policy differs")
        elif (
            self.process_fork_denied
            or not self.deny_all_file_writes
            or self.worker_scratch_root is not None
            or self.worker_scratch_root_sha256 is not None
        ):
            raise ValueError("broker/child sandbox policy differs")
        expected_template = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-profile-template-v1",
                "role": self.role,
                "network_outbound_denied": True,
                "network_inbound_denied": True,
                "process_fork_denied": self.process_fork_denied,
                "deny_all_file_writes": self.deny_all_file_writes,
                "worker_scratch_exception_count": int(
                    self.worker_scratch_root is not None
                ),
                "artifact_subpath_denied": True,
                "tessdata_subpath_denied": True,
                "immutable_executable_literal_denied": True,
                "request_root_subpath_denied": self.deny_all_file_writes,
                "outside_probe_root_bound": True,
                "network_trap_root_bound": True,
                "input_probe_root_denied": True,
                "private_probe_clone_count": 3,
                "artifact_probe_clone_denied": True,
                "tessdata_probe_clone_denied": True,
                "staged_executable_probe_clone_denied": True,
            }
        )
        if self.template_sha256 != expected_template:
            raise ValueError("kernel sandbox profile template differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox profile policy identity differs")
        return self


class KernelSandboxPolicyTargetFixture(ContractModel):
    """Disposable, DAC-positive target covered by the exact final profile."""

    operation: KernelSandboxProbeOperation
    root: KernelSandboxDirectoryIdentity
    target_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    target_sha256: Sha256
    secondary_target_relative_path: Annotated[
        str | None, Field(default=None, max_length=512)
    ] = None
    secondary_target_sha256: Sha256 | None = None
    policy_binding_kind: Literal[
        "outside_probe_root",
        "artifact_private_clone",
        "tessdata_private_clone",
        "staged_executable_private_clone",
    ]
    policy_binding_sha256: Sha256
    configured_custody_sha256: Sha256
    controller_uid: PositiveInt
    controller_euid: PositiveInt
    control_started_monotonic_ns: PositiveInt
    control_completed_monotonic_ns: PositiveInt
    target_before: KernelSandboxSentinelObservation
    target_after: KernelSandboxSentinelObservation
    secondary_target_before: KernelSandboxSentinelObservation | None = None
    secondary_target_after: KernelSandboxSentinelObservation | None = None
    same_operation_syscall_stage: Literal["open", "rename", "unlink", "mkdir"]
    same_operation_syscall_return: NonNegativeInt
    same_operation_raw_errno: Literal[0] = 0
    same_operation_opened_fd: NonNegativeInt | None = None
    same_operation_write_return: NonNegativeInt | None = None
    control_bytes_written: NonNegativeInt
    control_fsync_succeeded: Literal[True] = True
    control_close_succeeded: Literal[True] = True
    original_state_restored: Literal[True] = True
    disposable_campaign_private_target: Literal[True] = True
    record_sha256: Sha256

    @staticmethod
    def _state(value: KernelSandboxSentinelObservation) -> tuple[object, ...]:
        return (
            value.target_sha256,
            value.parent_directory_record_sha256,
            value.parent_directory_inventory_jsonl,
            value.parent_directory_inventory_entry_count,
            value.parent_directory_inventory_sha256,
            value.dac_write_authority_required,
            value.parent_writable_by_effective_uid,
            value.target_writable_by_effective_uid,
            value.exists,
            value.device,
            value.inode,
            value.mode,
            value.uid,
            value.nlink,
            value.size_bytes,
            value.content_sha256,
        )

    @model_validator(mode="after")
    def validate_fixture(self) -> "KernelSandboxPolicyTargetFixture":
        if self.operation not in KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS:
            raise ValueError("kernel sandbox target fixture operation differs")
        relative_target = _portable_path(self.target_relative_path)
        if len(PurePosixPath(relative_target).parts) != 1:
            raise ValueError("kernel sandbox target is not root-relative")
        target_path = str(PurePosixPath(self.root.resolved_path) / relative_target)
        if self.target_sha256 != hashlib.sha256(
            target_path.encode("utf-8")
        ).hexdigest():
            raise ValueError("kernel sandbox target escaped its held root")
        target_exists = self.operation not in {
            "outside_create",
            "outside_mkdir",
        }
        secondary_required = self.operation == "outside_rename"
        def require_inventory_target(
            observation: KernelSandboxSentinelObservation,
            *,
            name: str,
            exists: bool,
        ) -> None:
            entries = {
                str(item["name"]): item
                for item in _kernel_sandbox_directory_inventory(
                    observation.parent_directory_inventory_jsonl
                )
            }
            retained = entries.get(name)
            expected = (
                {
                    "name": name,
                    "device": observation.device,
                    "inode": observation.inode,
                    "mode": observation.mode,
                    "uid": observation.uid,
                    "nlink": observation.nlink,
                    "size_bytes": observation.size_bytes,
                    "content_sha256": observation.content_sha256,
                }
                if exists
                else None
            )
            if (
                observation.parent_directory_record_sha256
                != self.root.record_sha256
                or retained != expected
            ):
                raise ValueError(
                    "kernel sandbox sentinel parent inventory differs"
                )
        if (
            self.root.controller_euid != self.controller_euid
            or self.root.opened_at_monotonic_ns
            > self.control_started_monotonic_ns
            or self.root.first_fstat_observed_at_monotonic_ns
            > self.control_started_monotonic_ns
            or self.root.second_fstat_observed_at_monotonic_ns
            < self.control_completed_monotonic_ns
            or self.root.closed_at_monotonic_ns
            < self.control_completed_monotonic_ns
            or
            self.target_before.target_sha256 != self.target_sha256
            or self.target_after.target_sha256 != self.target_sha256
            or self.target_before.exists != target_exists
            or self.target_before.observed_at_monotonic_ns
            > self.control_started_monotonic_ns
            or self.target_after.observed_at_monotonic_ns
            < self.control_completed_monotonic_ns
            or self.control_started_monotonic_ns
            > self.control_completed_monotonic_ns
            or not self.target_before.dac_write_authority_required
            or not self.target_after.dac_write_authority_required
            or self._state(self.target_before) != self._state(self.target_after)
        ):
            raise ValueError("kernel sandbox DAC-positive target control differs")
        require_inventory_target(
            self.target_before, name=relative_target, exists=target_exists
        )
        require_inventory_target(
            self.target_after, name=relative_target, exists=target_exists
        )
        if secondary_required:
            assert self.secondary_target_relative_path is not None
            relative_secondary = _portable_path(self.secondary_target_relative_path)
            secondary_path = str(
                PurePosixPath(self.root.resolved_path) / relative_secondary
            )
            if (
                self.secondary_target_sha256 is None
                or self.secondary_target_before is None
                or self.secondary_target_after is None
                or self.secondary_target_before.target_sha256
                != self.secondary_target_sha256
                or self.secondary_target_after.target_sha256
                != self.secondary_target_sha256
                or self.secondary_target_sha256
                != hashlib.sha256(secondary_path.encode("utf-8")).hexdigest()
                or self.secondary_target_before.exists
                or self.secondary_target_after.exists
                or not self.secondary_target_before.dac_write_authority_required
                or not self.secondary_target_after.dac_write_authority_required
                or self._state(self.secondary_target_before)
                != self._state(self.secondary_target_after)
            ):
                raise ValueError("kernel sandbox rename target control differs")
            assert self.secondary_target_before is not None
            assert self.secondary_target_after is not None
            assert self.secondary_target_relative_path is not None
            require_inventory_target(
                self.secondary_target_before,
                name=self.secondary_target_relative_path,
                exists=False,
            )
            require_inventory_target(
                self.secondary_target_after,
                name=self.secondary_target_relative_path,
                exists=False,
            )
        elif any(
            value is not None
            for value in (
                self.secondary_target_sha256,
                self.secondary_target_relative_path,
                self.secondary_target_before,
                self.secondary_target_after,
            )
        ):
            raise ValueError("non-rename target retained secondary control")
        if self.operation in {
            "outside_create",
            "outside_rename",
            "outside_unlink",
            "outside_mkdir",
        } and self.control_bytes_written:
            raise ValueError("non-write DAC control retained write bytes")
        if self.operation in {
            "outside_truncate",
            "artifact_write",
            "artifact_truncate",
            "tessdata_write",
            "tessdata_truncate",
            "staged_executable_write",
            "staged_executable_truncate",
        } and not self.control_bytes_written:
            raise ValueError("write DAC control omitted written bytes")
        expected_stage = (
            "rename"
            if self.operation == "outside_rename"
            else "unlink"
            if self.operation.endswith("unlink")
            else "mkdir"
            if self.operation == "outside_mkdir"
            else "open"
        )
        if self.same_operation_syscall_stage != expected_stage:
            raise ValueError("kernel sandbox DAC control syscall differs")
        if expected_stage == "open":
            if (
                self.same_operation_opened_fd is None
                or self.same_operation_syscall_return
                != self.same_operation_opened_fd
                or self.same_operation_opened_fd < 3
                or self.same_operation_write_return
                != self.control_bytes_written
            ):
                raise ValueError("kernel sandbox DAC open control differs")
        elif (
            self.same_operation_syscall_return != 0
            or self.same_operation_opened_fd is not None
            or self.same_operation_write_return is not None
        ):
            raise ValueError("kernel sandbox DAC non-open control differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox target fixture identity differs")
        return self


class KernelSandboxScratchFixture(ContractModel):
    root: KernelSandboxDirectoryIdentity
    target_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    target_sha256: Sha256
    inventory_before_sha256: Sha256
    inventory_after_sha256: Sha256
    entry_count_before: Literal[0] = 0
    entry_count_after: Literal[0] = 0
    intermediate_file_identity_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_scratch(self) -> "KernelSandboxScratchFixture":
        target_path = str(
            PurePosixPath(self.root.resolved_path)
            / _portable_path(self.target_relative_path)
        )
        if (
            self.target_sha256
            != hashlib.sha256(target_path.encode("utf-8")).hexdigest()
            or self.inventory_before_sha256 != self.inventory_after_sha256
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox scratch fixture differs")
        return self


class KernelSandboxReadFixture(ContractModel):
    operation: Literal[
        "staged_executable_read", "tessdata_read", "input_read", "artifact_read"
    ]
    root: KernelSandboxDirectoryIdentity
    target_relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    target_sha256: Sha256
    file_identity: KernelSandboxFileIdentity
    configured_custody_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_fixture(self) -> "KernelSandboxReadFixture":
        relative = _portable_path(self.target_relative_path)
        if (
            len(PurePosixPath(relative).parts) != 1
            or self.target_sha256
            != hashlib.sha256(
                str(PurePosixPath(self.root.resolved_path) / relative).encode(
                    "utf-8"
                )
            ).hexdigest()
            or self.target_sha256 != self.file_identity.resolved_path_sha256
            or self.root.controller_euid != self.file_identity.effective_uid
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox read fixture differs")
        return self


class KernelSandboxTerminalTrapObservation(ContractModel):
    """Fresh controller reread of one trap after child wait4 terminality."""

    terminal_sequence: PositiveInt
    previous_terminal_record_sha256: Sha256
    source_probe_record_sha256: Sha256
    source_trap_record_sha256: Sha256
    attempt_terminal_record_sha256: Sha256
    attempt_terminal_observed_monotonic_ns: PositiveInt
    trap: KernelSandboxTrapObservation
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_terminal_trap(self) -> "KernelSandboxTerminalTrapObservation":
        if (
            self.trap.observed_at_monotonic_ns
            < self.attempt_terminal_observed_monotonic_ns
            or self.trap.accept_count
            or self.trap.datagram_count
            or self.trap.byte_count
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox terminal trap identity differs")
        return self


class KernelSandboxAttemptTerminalCustody(ContractModel):
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    worker: KernelSandboxProcessIdentity
    broker: KernelSandboxProcessIdentity
    worker_wait_record_sha256: Sha256
    broker_wait_record_sha256: Sha256
    worker_reaped_at_monotonic_ns: PositiveInt
    broker_reaped_at_monotonic_ns: PositiveInt
    worker_group_esrch_at_monotonic_ns: PositiveInt
    broker_group_esrch_at_monotonic_ns: PositiveInt
    registered_child_count: PositiveInt
    last_child_wait4_record_sha256: Sha256
    last_child_wait4_observed_monotonic_ns: PositiveInt
    open_child_registration_count: Literal[0] = 0
    child_audit_closed: Literal[True] = True
    child_audit_channel_eof: Literal[True] = True
    watchdog_terminal_record_sha256: Sha256
    terminal_observed_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_terminal(self) -> "KernelSandboxAttemptTerminalCustody":
        if (
            self.worker.role != "parser_worker"
            or self.broker.role != "tesseract_broker"
            or self.terminal_observed_monotonic_ns
            < max(
                self.worker_reaped_at_monotonic_ns,
                self.broker_reaped_at_monotonic_ns,
                self.worker_group_esrch_at_monotonic_ns,
                self.broker_group_esrch_at_monotonic_ns,
                self.last_child_wait4_observed_monotonic_ns,
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("kernel sandbox terminal custody differs")
        return self


class KernelSandboxRoleEvidence(ContractModel):
    schema_id: Literal["phase-latency-kernel-sandbox-role-v1"] = (
        "phase-latency-kernel-sandbox-role-v1"
    )
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    role: KernelSandboxRole
    policy_application_kind: Literal[
        "direct_sandbox_exec", "inherited_broker_profile"
    ]
    final_profile_utf8: Annotated[str, Field(min_length=1, max_length=524_288)]
    final_profile_sha256: Sha256
    profile_policy_sha256: Sha256
    profile_policy: KernelSandboxProfilePolicy
    sandbox_exec_identity: KernelSandboxFileIdentity
    platform_release: Annotated[str, Field(min_length=1, max_length=256)]
    platform_build: Annotated[str, Field(min_length=1, max_length=256)]
    machine_architecture: Annotated[str, Field(min_length=1, max_length=64)]
    process_before: KernelSandboxProcessIdentity
    process_after: KernelSandboxProcessIdentity
    parent_broker: KernelSandboxProcessIdentity | None = None
    inherited_broker_profile_sha256: Sha256 | None = None
    executable_identity: KernelSandboxFileIdentity
    helper_source_identity: KernelSandboxFileIdentity
    helper_executable_identity: KernelSandboxFileIdentity
    helper_argv_sha256: Sha256
    helper_environment_sha256: Sha256
    helper_same_process_identity: Literal[True] = True
    guard_to_exec_transition_sha256: Sha256 | None = None
    native_closure_sha256: Sha256
    native_trust_model: Literal["frozen-native-closure-trusted-v1"] = (
        "frozen-native-closure-trusted-v1"
    )
    native_containment_claim: Literal[
        "none-trusted-pinned-native-computation"
    ] = "none-trusted-pinned-native-computation"
    read_fixtures: Annotated[
        tuple[KernelSandboxReadFixture, ...], Field(min_length=4, max_length=4)
    ]
    policy_target_fixtures: Annotated[
        tuple[KernelSandboxPolicyTargetFixture, ...],
        Field(min_length=14, max_length=14),
    ]
    worker_scratch_fixture: KernelSandboxScratchFixture | None = None
    capabilities: Annotated[
        tuple[KernelSandboxCapabilityIdentity, ...],
        Field(min_length=2, max_length=5),
    ]
    file_descriptor_inventory_before_probes: NativeFileDescriptorInventory
    file_descriptor_inventory_after_probes: NativeFileDescriptorInventory
    sandbox_applied_at_monotonic_ns: PositiveInt
    rlimit_nproc_soft: NonNegativeInt | None = None
    rlimit_nproc_hard: NonNegativeInt | None = None
    nproc_applied_at_monotonic_ns: PositiveInt | None = None
    ready_published_at_monotonic_ns: PositiveInt | None = None
    exec_release_e_monotonic_ns: PositiveInt | None = None
    rows: Annotated[
        tuple[KernelSandboxProbeRow, ...], Field(min_length=1, max_length=128)
    ]
    expected_operation_matrix_sha256: Sha256
    row_log_sha256: Sha256
    row_log_count: PositiveInt
    row_log_size_bytes: PositiveInt
    pre_ready: Literal[True] = True
    pre_exec_release_e: StrictBool
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_role(self) -> "KernelSandboxRoleEvidence":
        if (
            self.final_profile_sha256
            != hashlib.sha256(self.final_profile_utf8.encode("utf-8")).hexdigest()
            or self.profile_policy.role != self.role
            or self.profile_policy_sha256 != self.profile_policy.record_sha256
            or self.final_profile_utf8 != self.profile_policy.render_profile()
            or self.expected_operation_matrix_sha256
            != _kernel_sandbox_matrix_sha256(self.role)
            or self.process_before != self.process_after
            or self.process_before.role != self.role
        ):
            raise ValueError("kernel sandbox role binding differs")
        if self.role == "tesseract_child":
            if (
                self.policy_application_kind != "inherited_broker_profile"
                or self.parent_broker is None
                or self.parent_broker.role != "tesseract_broker"
                or self.inherited_broker_profile_sha256 != self.final_profile_sha256
                or (self.rlimit_nproc_soft, self.rlimit_nproc_hard) != (0, 0)
                or self.nproc_applied_at_monotonic_ns is None
                or self.ready_published_at_monotonic_ns is not None
                or self.exec_release_e_monotonic_ns is None
                or not self.pre_exec_release_e
                or self.guard_to_exec_transition_sha256 is None
                or self.process_before.parent_pid != self.parent_broker.pid
                or self.process_before.process_group_id
                != self.parent_broker.process_group_id
                or self.process_before.session_id != self.parent_broker.session_id
            ):
                raise ValueError("child sandbox inheritance differs")
        elif (
            self.policy_application_kind != "direct_sandbox_exec"
            or self.parent_broker is not None
            or self.inherited_broker_profile_sha256 is not None
            or self.pre_exec_release_e
            or self.guard_to_exec_transition_sha256 is not None
            or self.ready_published_at_monotonic_ns is None
            or self.exec_release_e_monotonic_ns is not None
            or self.process_before.pid != self.process_before.process_group_id
            or self.process_before.pid != self.process_before.session_id
        ):
            raise ValueError("root sandbox application differs")
        if self.role == "parser_worker" and (
            self.rlimit_nproc_soft,
            self.rlimit_nproc_hard,
        ) != (0, 0):
            raise ValueError("worker sandbox lacks hard fork denial")
        if self.role == "tesseract_broker" and any(
            value is not None
            for value in (
                self.rlimit_nproc_soft,
                self.rlimit_nproc_hard,
                self.nproc_applied_at_monotonic_ns,
            )
        ):
            raise ValueError("active broker cannot claim terminal fork denial")
        if self.role == "parser_worker" and self.nproc_applied_at_monotonic_ns is None:
            raise ValueError("worker fork-denial application time is absent")
        operations = tuple(row.operation for row in self.rows)
        if operations != _kernel_sandbox_operations(self.role):
            raise ValueError("kernel sandbox role matrix differs")
        expected_read_operations = (
            "staged_executable_read",
            "tessdata_read",
            "input_read",
            "artifact_read",
        )
        if tuple(item.operation for item in self.read_fixtures) != (
            expected_read_operations
        ) or len({item.record_sha256 for item in self.read_fixtures}) != 4:
            raise ValueError("kernel sandbox read fixture set differs")
        if tuple(item.operation for item in self.policy_target_fixtures) != tuple(
            KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS
        ) or len(
            {item.record_sha256 for item in self.policy_target_fixtures}
        ) != len(self.policy_target_fixtures):
            raise ValueError("kernel sandbox target fixture set differs")
        for fixture in self.policy_target_fixtures:
            if (
                fixture.controller_uid != self.process_before.real_uid
                or fixture.controller_euid != self.process_before.effective_uid
                or fixture.control_completed_monotonic_ns
                >= self.sandbox_applied_at_monotonic_ns
            ):
                raise ValueError("kernel sandbox DAC control custody differs")
            if fixture.operation.startswith("artifact_"):
                expected_kind = "artifact_private_clone"
                expected_binding = (
                    self.profile_policy.artifact_probe_clone_root_sha256
                )
            elif fixture.operation.startswith("tessdata_"):
                expected_kind = "tessdata_private_clone"
                expected_binding = (
                    self.profile_policy.tessdata_probe_clone_root_sha256
                )
            elif fixture.operation.startswith("staged_executable_"):
                expected_kind = "staged_executable_private_clone"
                expected_binding = (
                    self.profile_policy.staged_executable_probe_clone_root_sha256
                )
            else:
                expected_kind = "outside_probe_root"
                expected_binding = self.profile_policy.outside_probe_root_sha256
            expected_root = (
                self.profile_policy.artifact_probe_clone_root
                if expected_kind == "artifact_private_clone"
                else self.profile_policy.tessdata_probe_clone_root
                if expected_kind == "tessdata_private_clone"
                else self.profile_policy.staged_executable_probe_clone_root
                if expected_kind == "staged_executable_private_clone"
                else self.profile_policy.outside_probe_root
            )
            if (
                fixture.policy_binding_kind != expected_kind
                or fixture.policy_binding_sha256 != expected_binding
                or fixture.root.resolved_path != expected_root
            ):
                raise ValueError("kernel sandbox target crossed profile custody")
        if self.role == "parser_worker":
            if (
                self.worker_scratch_fixture is None
                or self.profile_policy.worker_scratch_root is None
                or self.worker_scratch_fixture.root.resolved_path
                != self.profile_policy.worker_scratch_root
            ):
                raise ValueError("worker sandbox scratch fixture differs")
        elif self.worker_scratch_fixture is not None:
            raise ValueError("non-worker role retained a scratch fixture")
        expected_capability_kinds: Mapping[str, tuple[str, ...]] = {
            "parser_worker": (
                "worker_broker_rpc",
                "request_control",
                "phase_control",
            ),
            "tesseract_broker": ("worker_broker_rpc", "broker_watchdog"),
            "tesseract_child": (
                "child_stdin_pipe",
                "child_stdout_pipe",
                "child_stderr_pipe",
                "child_ready_pipe",
                "child_release_pipe",
            ),
        }
        if tuple(item.capability_kind for item in self.capabilities) != (
            expected_capability_kinds[self.role]
        ) or len({item.record_sha256 for item in self.capabilities}) != len(
            self.capabilities
        ):
            raise ValueError("kernel sandbox capability set differs")
        fixture_by_operation = {
            item.operation: item for item in self.read_fixtures
        }
        expected_read_paths = {
            "staged_executable_read": self.profile_policy.immutable_executable,
            "tessdata_read": str(
                PurePosixPath(self.profile_policy.tessdata_root)
                / self.profile_policy.tessdata_read_relative_path
            ),
            "input_read": str(
                PurePosixPath(self.profile_policy.input_probe_root)
                / self.profile_policy.input_probe_relative_path
            ),
            "artifact_read": str(
                PurePosixPath(self.profile_policy.artifact_root)
                / self.profile_policy.artifact_read_relative_path
            ),
        }
        if any(
            fixture.file_identity.resolved_path
            != expected_read_paths[fixture.operation]
            for fixture in self.read_fixtures
        ):
            raise ValueError("kernel sandbox read fixture path custody differs")
        unix_network_rows = tuple(
            row
            for row in self.rows
            if row.network_target is not None
            and row.network_target.unix_root is not None
        )
        if any(
            row.network_target.unix_root.resolved_path
            != self.profile_policy.network_trap_root
            or row.network_target.unix_root.resolved_path_sha256
            != self.profile_policy.network_trap_root_sha256
            for row in unix_network_rows
        ):
            raise ValueError("kernel sandbox network trap root crossed profile custody")
        capability_by_sha = {
            item.record_sha256: item for item in self.capabilities
        }
        target_fixture_by_sha = {
            item.record_sha256: item for item in self.policy_target_fixtures
        }
        for row in self.rows:
            fixture = fixture_by_operation.get(row.operation)
            if fixture is not None and (
                row.known_read_fixture_sha256 != fixture.record_sha256
                or row.target_sha256 != fixture.target_sha256
                or row.allowed_read_sha256 != fixture.file_identity.content_sha256
                or row.allowed_read_bytes != fixture.file_identity.size_bytes
                or row.directory_operation_anchor is None
                or row.directory_operation_anchor.root != fixture.root
                or row.directory_operation_anchor.primary_relative_path
                != fixture.target_relative_path
                or row.directory_operation_anchor.secondary_relative_path
                is not None
            ):
                raise ValueError("kernel sandbox allowed read crossed fixture custody")
            if row.capability_identity is not None and (
                capability_by_sha.get(row.capability_identity.record_sha256)
                != row.capability_identity
            ):
                raise ValueError("kernel sandbox capability crossed role custody")
            target_fixture = target_fixture_by_sha.get(
                row.policy_target_fixture_sha256 or ""
            )
            if row.operation in KERNEL_SANDBOX_FILE_DENIAL_OPERATIONS and (
                target_fixture is None
                or target_fixture.operation != row.operation
                or target_fixture.target_sha256 != row.target_sha256
                or target_fixture.secondary_target_sha256
                != row.secondary_target_sha256
                or row.directory_operation_anchor is None
                or row.directory_operation_anchor.root != target_fixture.root
                or row.directory_operation_anchor.primary_relative_path
                != target_fixture.target_relative_path
                or row.directory_operation_anchor.secondary_relative_path
                != target_fixture.secondary_target_relative_path
                or KernelSandboxProbeRow._sentinel_state(
                    target_fixture.target_after
                )
                != KernelSandboxProbeRow._sentinel_state(row.target_before)
            ):
                raise ValueError("kernel sandbox denied row crossed target fixture")
            if row.operation == "worker_scratch_roundtrip" and (
                self.worker_scratch_fixture is None
                or row.policy_target_fixture_sha256
                != self.worker_scratch_fixture.record_sha256
                or row.target_sha256
                != self.worker_scratch_fixture.target_sha256
                or row.intermediate_identity_sha256
                != self.worker_scratch_fixture.intermediate_file_identity_sha256
                or row.directory_operation_anchor is None
                or row.directory_operation_anchor.root
                != self.worker_scratch_fixture.root
                or row.directory_operation_anchor.primary_relative_path
                != self.worker_scratch_fixture.target_relative_path
                or row.directory_operation_anchor.secondary_relative_path
                is not None
            ):
                raise ValueError("kernel sandbox scratch row crossed fixture")
            if row.operation in {"unix_connect", "unix_bind"}:
                target = row.network_target
                if (
                    target is None
                    or target.unix_root is None
                    or target.unix_relative_path is None
                    or row.directory_operation_anchor is None
                    or row.directory_operation_anchor.root != target.unix_root
                    or row.directory_operation_anchor.primary_relative_path
                    != target.unix_relative_path
                ):
                    raise ValueError("kernel sandbox AF_UNIX row crossed held root")
        for capability in self.capabilities:
            expected_cloexec = capability.capability_kind not in {
                "child_stdin_pipe",
                "child_stdout_pipe",
                "child_stderr_pipe",
            }
            if (
                capability.owner_role != self.role
                or capability.owner_pid != self.process_before.pid
                or capability.owner_start_abstime
                != self.process_before.start_abstime
                or capability.close_on_exec != expected_cloexec
            ):
                raise ValueError("kernel sandbox capability owner custody differs")
        expected_native_process = (
            self.process_before.pid,
            self.process_before.start_abstime,
            self.process_before.parent_pid,
            self.process_before.process_group_id,
            self.process_before.session_id,
        )
        before_inventory = self.file_descriptor_inventory_before_probes
        after_inventory = self.file_descriptor_inventory_after_probes
        before_by_fd = {item.fd: item for item in before_inventory.descriptors}
        after_by_fd = {item.fd: item for item in after_inventory.descriptors}
        if (
            (
                before_inventory.process.pid,
                before_inventory.process.start_abstime,
                before_inventory.process.ppid,
                before_inventory.process.pgid,
                before_inventory.process.sid,
            )
            != expected_native_process
            or before_inventory.process != after_inventory.process
            or before_inventory.inventory_sha256
            != after_inventory.inventory_sha256
            or before_inventory.descriptors != after_inventory.descriptors
            or before_inventory.second_scan_completed_monotonic_ns
            >= self.rows[0].started_monotonic_ns
            or after_inventory.first_scan_started_monotonic_ns
            <= self.rows[-1].completed_monotonic_ns
            or (
                self.ready_published_at_monotonic_ns is not None
                and after_inventory.second_scan_completed_monotonic_ns
                >= self.ready_published_at_monotonic_ns
            )
            or (
                self.exec_release_e_monotonic_ns is not None
                and after_inventory.second_scan_completed_monotonic_ns
                >= self.exec_release_e_monotonic_ns
            )
            or any(
                before_by_fd.get(capability.descriptor)
                != capability.owner_descriptor
                or after_by_fd.get(capability.descriptor)
                != capability.owner_descriptor
                for capability in self.capabilities
            )
        ):
            raise ValueError("kernel sandbox capability FD inventory differs")
        if tuple(row.probe_sequence for row in self.rows) != tuple(
            range(1, len(self.rows) + 1)
        ) or any(
            later.previous_probe_record_sha256 != earlier.record_sha256
            for earlier, later in zip(self.rows, self.rows[1:], strict=False)
        ) or self.rows[0].previous_probe_record_sha256 != "0" * 64:
            raise ValueError("kernel sandbox probe chain differs")
        if len({row.probe_nonce_sha256 for row in self.rows}) != len(self.rows) or len(
            {row.probe_capability_sha256 for row in self.rows}
        ) != len(self.rows):
            raise ValueError("kernel sandbox probe capability was reused")
        common = (
            self.attempt_id,
            self.attempt_nonce_sha256,
            self.scope_sha256,
            self.role,
            self.final_profile_sha256,
            self.profile_policy_sha256,
            self.helper_source_identity.content_sha256,
            self.helper_executable_identity.content_sha256,
            self.process_before,
            self.expected_operation_matrix_sha256,
        )
        if any(
            (
                row.attempt_id,
                row.attempt_nonce_sha256,
                row.scope_sha256,
                row.role,
                row.profile_sha256,
                row.profile_policy_sha256,
                row.helper_source_sha256,
                row.helper_executable_sha256,
                row.process,
                row.expected_operation_matrix_sha256,
            )
            != common
            for row in self.rows
        ):
            raise ValueError("kernel sandbox probe crossed role custody")
        lower_bound = max(
            self.sandbox_applied_at_monotonic_ns,
            self.nproc_applied_at_monotonic_ns or 0,
        )
        if any(row.started_monotonic_ns < lower_bound for row in self.rows):
            raise ValueError("kernel sandbox probe preceded policy application")
        if any(
            row.network_target is not None
            and row.network_target.positive_control_completed_monotonic_ns
            >= self.sandbox_applied_at_monotonic_ns
            for row in self.rows
        ):
            raise ValueError(
                "kernel sandbox network positive control followed policy application"
            )
        upper_bound = (
            self.exec_release_e_monotonic_ns
            if self.role == "tesseract_child"
            else self.ready_published_at_monotonic_ns
        )
        assert upper_bound is not None
        if any(row.completed_monotonic_ns >= upper_bound for row in self.rows):
            raise ValueError("kernel sandbox probe followed READY/exec release")
        immutable_files = (
            self.sandbox_exec_identity,
            self.executable_identity,
            self.helper_source_identity,
            self.helper_executable_identity,
            *(fixture.file_identity for fixture in self.read_fixtures),
        )
        if any(
            file.effective_uid != self.process_before.effective_uid
            or file.first_observed_at_monotonic_ns
            > self.sandbox_applied_at_monotonic_ns
            or file.second_observed_at_monotonic_ns < upper_bound
            for file in immutable_files
        ):
            raise ValueError(
                "kernel sandbox immutable file observation window differs"
            )
        held_root_candidates = [
            *(fixture.root for fixture in self.policy_target_fixtures),
            *(fixture.root for fixture in self.read_fixtures),
            *(
                (self.worker_scratch_fixture.root,)
                if self.worker_scratch_fixture is not None
                else ()
            ),
            *(
                (row.network_target.unix_root,)
                if row.network_target is not None
                and row.network_target.unix_root is not None
                else ()
                for row in self.rows
            ),
        ]
        flattened_roots = tuple(
            root
            for candidate in held_root_candidates
            for root in (
                candidate if isinstance(candidate, tuple) else (candidate,)
            )
        )
        held_roots = tuple(
            {root.record_sha256: root for root in flattened_roots}.values()
        )
        if any(
            root.controller_euid != self.process_before.effective_uid
            or root.first_fstat_observed_at_monotonic_ns
            > self.sandbox_applied_at_monotonic_ns
            or root.second_fstat_observed_at_monotonic_ns < upper_bound
            or root.closed_at_monotonic_ns < upper_bound
            for root in held_roots
        ):
            raise ValueError("kernel sandbox held root observation window differs")
        row_bytes = b"".join(
            canonical_model_bytes(row) + b"\n" for row in self.rows
        )
        if (
            self.row_log_count != len(self.rows)
            or self.row_log_size_bytes != len(row_bytes)
            or self.row_log_sha256 != hashlib.sha256(row_bytes).hexdigest()
        ):
            raise ValueError("kernel sandbox role log differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox role identity differs")
        return self


class KernelSandboxEvidence(ContractModel):
    """Controller-owned, actual-profile sandbox proof for one managed attempt."""

    schema_id: Literal["phase-latency-kernel-sandbox-evidence-v1"] = (
        "phase-latency-kernel-sandbox-evidence-v1"
    )
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    logical_controller: KernelSandboxAuthorityIdentity
    watchdog_launcher: KernelSandboxAuthorityIdentity
    logical_controller_fd_inventory_before_probes: NativeFileDescriptorInventory
    logical_controller_fd_inventory_after_probes: NativeFileDescriptorInventory
    watchdog_launcher_fd_inventory_before_probes: NativeFileDescriptorInventory
    watchdog_launcher_fd_inventory_after_probes: NativeFileDescriptorInventory
    source_custody_sha256: Sha256
    production_artifact_custody_sha256: Sha256
    production_tessdata_custody_sha256: Sha256
    production_staged_executable_custody_sha256: Sha256
    artifact_private_clone_custody_sha256: Sha256
    tessdata_private_clone_custody_sha256: Sha256
    staged_executable_private_clone_custody_sha256: Sha256
    outside_probe_root_custody_sha256: Sha256
    approved_sandbox_exec_sha256: Sha256
    approved_helper_source_sha256: Sha256
    approved_helper_executable_sha256: Sha256
    approved_worker_executable_sha256: Sha256
    approved_broker_executable_sha256: Sha256
    approved_child_executable_sha256: Sha256
    worker: KernelSandboxRoleEvidence
    broker: KernelSandboxRoleEvidence
    child: KernelSandboxRoleEvidence
    attempt_terminal: KernelSandboxAttemptTerminalCustody
    capability_transcript_rows: Annotated[
        tuple[KernelSandboxCapabilityTranscriptRow, ...],
        Field(min_length=10, max_length=10),
    ]
    terminal_trap_observations: Annotated[
        tuple[KernelSandboxTerminalTrapObservation, ...],
        Field(min_length=5, max_length=64),
    ]
    capability_transcript_log_sha256: Sha256
    capability_transcript_log_count: PositiveInt
    capability_transcript_log_size_bytes: PositiveInt
    terminal_trap_log_sha256: Sha256
    terminal_trap_log_count: PositiveInt
    terminal_trap_log_size_bytes: PositiveInt
    pairing_projection_sha256: Sha256
    hosted_calls: Literal[0] = 0
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_evidence(self) -> "KernelSandboxEvidence":
        roles = (self.worker, self.broker, self.child)
        if tuple(item.role for item in roles) != (
            "parser_worker",
            "tesseract_broker",
            "tesseract_child",
        ) or any(
            (
                item.attempt_id,
                item.attempt_nonce_sha256,
                item.scope_sha256,
            )
            != (self.attempt_id, self.attempt_nonce_sha256, self.scope_sha256)
            for item in roles
        ):
            raise ValueError("kernel sandbox role set differs")
        if (
            self.logical_controller.role != "logical_controller"
            or self.watchdog_launcher.role != "watchdog_launcher"
            or self.logical_controller.pid == self.watchdog_launcher.pid
            or self.watchdog_launcher.parent_pid != self.logical_controller.pid
            or self.watchdog_launcher.pid
            != self.watchdog_launcher.process_group_id
            or self.watchdog_launcher.pid != self.watchdog_launcher.session_id
            or self.watchdog_launcher.real_uid
            != self.logical_controller.real_uid
            or self.watchdog_launcher.effective_uid
            != self.logical_controller.effective_uid
            or self.worker.process_before.parent_pid
            != self.watchdog_launcher.pid
            or self.broker.process_before.parent_pid
            != self.watchdog_launcher.pid
            or any(
                item.process_before.real_uid
                != self.watchdog_launcher.real_uid
                or item.process_before.effective_uid
                != self.watchdog_launcher.effective_uid
                for item in roles
            )
            or self.worker.sandbox_exec_identity.content_sha256
            != self.approved_sandbox_exec_sha256
            or self.broker.sandbox_exec_identity.content_sha256
            != self.approved_sandbox_exec_sha256
            or self.child.sandbox_exec_identity.content_sha256
            != self.approved_sandbox_exec_sha256
            or any(
                item.helper_source_identity.content_sha256
                != self.approved_helper_source_sha256
                or item.helper_executable_identity.content_sha256
                != self.approved_helper_executable_sha256
                for item in roles
            )
            or self.worker.executable_identity.content_sha256
            != self.approved_worker_executable_sha256
            or self.broker.executable_identity.content_sha256
            != self.approved_broker_executable_sha256
            or self.child.executable_identity.content_sha256
            != self.approved_child_executable_sha256
            or
            self.child.parent_broker != self.broker.process_before
            or self.child.final_profile_sha256 != self.broker.final_profile_sha256
            or self.child.native_closure_sha256
            != self.broker.native_closure_sha256
            or self.worker.native_closure_sha256
            != self.broker.native_closure_sha256
            or self.worker.process_before.process_group_id
            == self.broker.process_before.process_group_id
            or self.child.process_before.pid
            in {self.worker.process_before.pid, self.broker.process_before.pid}
            or self.attempt_terminal.attempt_id != self.attempt_id
            or self.attempt_terminal.attempt_nonce_sha256
            != self.attempt_nonce_sha256
            or self.attempt_terminal.scope_sha256 != self.scope_sha256
            or self.attempt_terminal.worker != self.worker.process_before
            or self.attempt_terminal.broker != self.broker.process_before
        ):
            raise ValueError("kernel sandbox child/profile closure differs")
        expected_pairing = _canonical_hash(
            {
                "schema_id": "phase-latency-kernel-sandbox-pairing-v1",
                "roles": tuple(
                    {
                        "role": item.role,
                        "policy_application_kind": item.policy_application_kind,
                        "profile_template_sha256": item.profile_policy.template_sha256,
                        "sandbox_exec_sha256": item.sandbox_exec_identity.content_sha256,
                        "helper_source_sha256": item.helper_source_identity.content_sha256,
                        "helper_executable_sha256": item.helper_executable_identity.content_sha256,
                        "native_closure_sha256": item.native_closure_sha256,
                        "native_trust_model": item.native_trust_model,
                        "native_containment_claim": item.native_containment_claim,
                        "matrix_sha256": item.expected_operation_matrix_sha256,
                    }
                    for item in roles
                ),
            }
        )
        if self.pairing_projection_sha256 != expected_pairing:
            raise ValueError("kernel sandbox pairing projection differs")
        held_roots = tuple(
            {
                root.record_sha256: root
                for item in roles
                for root in (
                    *(fixture.root for fixture in item.policy_target_fixtures),
                    *(fixture.root for fixture in item.read_fixtures),
                    *(
                        (item.worker_scratch_fixture.root,)
                        if item.worker_scratch_fixture is not None
                        else ()
                    ),
                    *(
                        row.network_target.unix_root
                        for row in item.rows
                        if row.network_target is not None
                        and row.network_target.unix_root is not None
                    ),
                )
            }.values()
        )
        if any(
            root.holder_pid != self.logical_controller.pid
            or root.holder_start_abstime
            != self.logical_controller.start_abstime
            for root in held_roots
        ):
            raise ValueError("kernel sandbox held root controller differs")
        network_targets = tuple(
            row.network_target
            for item in roles
            for row in item.rows
            if row.network_target is not None
        )
        if any(
            (
                target.positive_control.controller.pid,
                target.positive_control.controller.start_abstime,
                target.positive_control.controller.ppid,
                target.positive_control.controller.pgid,
                target.positive_control.controller.sid,
            )
            != (
                self.logical_controller.pid,
                self.logical_controller.start_abstime,
                self.logical_controller.parent_pid,
                self.logical_controller.process_group_id,
                self.logical_controller.session_id,
            )
            or target.positive_control.controller_effective_uid
            != self.logical_controller.effective_uid
            for target in network_targets
        ):
            raise ValueError("kernel sandbox network control authority differs")
        custody_by_operation = {
            "staged_executable_read": (
                self.production_staged_executable_custody_sha256
            ),
            "tessdata_read": self.production_tessdata_custody_sha256,
            "input_read": self.source_custody_sha256,
            "artifact_read": self.production_artifact_custody_sha256,
        }
        target_custody_by_kind = {
            "outside_probe_root": self.outside_probe_root_custody_sha256,
            "artifact_private_clone": (
                self.artifact_private_clone_custody_sha256
            ),
            "tessdata_private_clone": self.tessdata_private_clone_custody_sha256,
            "staged_executable_private_clone": (
                self.staged_executable_private_clone_custody_sha256
            ),
        }
        if any(
            fixture.configured_custody_sha256
            != custody_by_operation[fixture.operation]
            for item in roles
            for fixture in item.read_fixtures
        ) or any(
            fixture.configured_custody_sha256
            != target_custody_by_kind[fixture.policy_binding_kind]
            for item in roles
            for fixture in item.policy_target_fixtures
        ):
            raise ValueError("kernel sandbox fixture crossed configured custody")
        expected_peers = {
            "request_control": self.logical_controller,
            "phase_control": self.logical_controller,
            "broker_watchdog": self.watchdog_launcher,
            "child_stdin_pipe": self.broker.process_before,
            "child_stdout_pipe": self.broker.process_before,
            "child_stderr_pipe": self.broker.process_before,
            "child_ready_pipe": self.broker.process_before,
            "child_release_pipe": self.broker.process_before,
        }
        authority_inventories = {
            "logical_controller": (
                self.logical_controller_fd_inventory_before_probes,
                self.logical_controller_fd_inventory_after_probes,
            ),
            "watchdog_launcher": (
                self.watchdog_launcher_fd_inventory_before_probes,
                self.watchdog_launcher_fd_inventory_after_probes,
            ),
        }
        role_inventories = {
            item.role: (
                item.file_descriptor_inventory_before_probes,
                item.file_descriptor_inventory_after_probes,
            )
            for item in roles
        }
        authority_by_role = {
            "logical_controller": self.logical_controller,
            "watchdog_launcher": self.watchdog_launcher,
        }
        for authority_role, inventories in authority_inventories.items():
            authority = authority_by_role[authority_role]
            before_inventory, after_inventory = inventories
            expected_process = (
                authority.pid,
                authority.start_abstime,
                authority.parent_pid,
                authority.process_group_id,
                authority.session_id,
            )
            if (
                (
                    before_inventory.process.pid,
                    before_inventory.process.start_abstime,
                    before_inventory.process.ppid,
                    before_inventory.process.pgid,
                    before_inventory.process.sid,
                )
                != expected_process
                or before_inventory.process != after_inventory.process
                or before_inventory.inventory_sha256
                != after_inventory.inventory_sha256
                or before_inventory.descriptors != after_inventory.descriptors
            ):
                raise ValueError("kernel sandbox authority FD inventory differs")
        for item in roles:
            for capability in item.capabilities:
                peer = (
                    self.broker.process_before
                    if capability.capability_kind == "worker_broker_rpc"
                    and item.role == "parser_worker"
                    else self.worker.process_before
                    if capability.capability_kind == "worker_broker_rpc"
                    else expected_peers[capability.capability_kind]
                )
                expected_peer_role = (
                    peer.role
                    if isinstance(peer, KernelSandboxAuthorityIdentity)
                    else peer.role
                )
                if (
                    capability.peer_role != expected_peer_role
                    or capability.peer_pid != peer.pid
                    or capability.peer_start_abstime != peer.start_abstime
                ):
                    raise ValueError("kernel sandbox capability peer differs")
                peer_inventories = (
                    authority_inventories[capability.peer_role]
                    if capability.peer_role in authority_inventories
                    else role_inventories[capability.peer_role]
                )
                peer_before, peer_after = peer_inventories
                peer_before_by_fd = {
                    descriptor.fd: descriptor
                    for descriptor in peer_before.descriptors
                }
                peer_after_by_fd = {
                    descriptor.fd: descriptor
                    for descriptor in peer_after.descriptors
                }
                probe_row = next(
                    row
                    for row in item.rows
                    if row.capability_identity == capability
                )
                if (
                    peer_before.process.pid != capability.peer_pid
                    or peer_before.process.start_abstime
                    != capability.peer_start_abstime
                    or peer_before.process != peer_after.process
                    or peer_before_by_fd.get(capability.peer_descriptor.fd)
                    != capability.peer_descriptor
                    or peer_after_by_fd.get(capability.peer_descriptor.fd)
                    != capability.peer_descriptor
                    or peer_before.second_scan_completed_monotonic_ns
                    >= probe_row.started_monotonic_ns
                    or peer_after.first_scan_started_monotonic_ns
                    <= probe_row.completed_monotonic_ns
                ):
                    raise ValueError(
                        "kernel sandbox capability peer FD differs: "
                        f"{item.role}/{capability.capability_kind}"
                    )
        worker_rpc = next(
            item
            for item in self.worker.capabilities
            if item.capability_kind == "worker_broker_rpc"
        )
        broker_rpc = next(
            item
            for item in self.broker.capabilities
            if item.capability_kind == "worker_broker_rpc"
        )
        if (
            worker_rpc.channel_binding_sha256
            != broker_rpc.channel_binding_sha256
            or worker_rpc.owner_pid != broker_rpc.peer_pid
            or worker_rpc.peer_pid != broker_rpc.owner_pid
            or worker_rpc.owner_start_abstime != broker_rpc.peer_start_abstime
            or worker_rpc.peer_start_abstime != broker_rpc.owner_start_abstime
        ):
            raise ValueError("kernel sandbox worker/broker channel differs")
        capabilities = tuple(capability for item in roles for capability in item.capabilities)
        transcript_by_capability = {
            item.capability_record_sha256: item
            for item in self.capability_transcript_rows
        }
        if (
            tuple(item.row_sequence for item in self.capability_transcript_rows)
            != tuple(range(1, len(self.capability_transcript_rows) + 1))
            or self.capability_transcript_rows[0].previous_row_sha256 != "0" * 64
            or any(
                later.previous_row_sha256 != earlier.record_sha256
                for earlier, later in zip(
                    self.capability_transcript_rows,
                    self.capability_transcript_rows[1:],
                    strict=False,
                )
            )
            or set(transcript_by_capability)
            != {item.record_sha256 for item in capabilities}
        ):
            raise ValueError("kernel sandbox capability transcript set differs")
        for capability in capabilities:
            transcript = transcript_by_capability[capability.record_sha256]
            probe_rows = tuple(
                row
                for item in roles
                for row in item.rows
                if row.capability_identity == capability
            )
            if (
                len(probe_rows) != 1
                or
                transcript.owner_role != capability.owner_role
                or transcript.capability_kind != capability.capability_kind
                or transcript.channel_binding_sha256
                != capability.channel_binding_sha256
                or transcript.owner_pid != capability.owner_pid
                or transcript.owner_start_abstime
                != capability.owner_start_abstime
                or transcript.peer_pid != capability.peer_pid
                or transcript.peer_start_abstime
                != capability.peer_start_abstime
                or transcript.controller_issued_nonce_sha256
                != capability.controller_issued_nonce_sha256
                or transcript.peer_ack_sha256
                != capability.controller_peer_ack_sha256
                or probe_rows[0].bytes_sent != transcript.bytes_sent
                or probe_rows[0].bytes_received != transcript.bytes_received
            ):
                raise ValueError("kernel sandbox capability transcript join differs")
        capability_bytes = b"".join(
            canonical_model_bytes(item) + b"\n"
            for item in self.capability_transcript_rows
        )
        if (
            self.capability_transcript_log_count
            != len(self.capability_transcript_rows)
            or self.capability_transcript_log_size_bytes != len(capability_bytes)
            or self.capability_transcript_log_sha256
            != hashlib.sha256(capability_bytes).hexdigest()
        ):
            raise ValueError("kernel sandbox capability transcript differs")
        row_traps = {
            row.trap_after.record_sha256: (row, row.trap_after)
            for item in roles
            for row in item.rows
            if row.trap_after is not None
        }
        controller_before_descriptors = {
            item.fd: item
            for item in self.logical_controller_fd_inventory_before_probes.descriptors
        }
        controller_after_descriptors = {
            item.fd: item
            for item in self.logical_controller_fd_inventory_after_probes.descriptors
        }
        if any(
            controller_before_descriptors.get(trap.controller_descriptor.fd)
            != trap.controller_descriptor
            or controller_after_descriptors.get(trap.controller_descriptor.fd)
            != trap.controller_descriptor
            for _row, trap in row_traps.values()
        ):
            raise ValueError("kernel sandbox trap controller FD differs")
        terminal_sources = {
            item.source_trap_record_sha256 for item in self.terminal_trap_observations
        }
        attempt_terminal_records = {
            (
                item.attempt_terminal_record_sha256,
                item.attempt_terminal_observed_monotonic_ns,
            )
            for item in self.terminal_trap_observations
        }
        if (
            set(row_traps) != terminal_sources
            or len(terminal_sources) != len(self.terminal_trap_observations)
            or attempt_terminal_records
            != {
                (
                    self.attempt_terminal.record_sha256,
                    self.attempt_terminal.terminal_observed_monotonic_ns,
                )
            }
            or next(iter(attempt_terminal_records))[1]
            < max(row.completed_monotonic_ns for item in roles for row in item.rows)
            or tuple(
                item.terminal_sequence for item in self.terminal_trap_observations
            )
            != tuple(range(1, len(self.terminal_trap_observations) + 1))
            or self.terminal_trap_observations[0].previous_terminal_record_sha256
            != "0" * 64
            or any(
                later.previous_terminal_record_sha256 != earlier.record_sha256
                for earlier, later in zip(
                    self.terminal_trap_observations,
                    self.terminal_trap_observations[1:],
                    strict=False,
                )
            )
        ):
            raise ValueError("kernel sandbox terminal trap custody differs")
        for terminal in self.terminal_trap_observations:
            source_row, source_trap = row_traps[terminal.source_trap_record_sha256]
            unix_root = terminal.trap.target.unix_root
            if (
                terminal.source_probe_record_sha256 != source_row.record_sha256
                or terminal.trap.observed_at_monotonic_ns
                <= source_trap.observed_at_monotonic_ns
                or KernelSandboxProbeRow._trap_state(terminal.trap)
                != KernelSandboxProbeRow._trap_state(source_trap)
                or terminal.trap.controller_descriptor
                != source_trap.controller_descriptor
                or controller_after_descriptors.get(
                    terminal.trap.controller_descriptor.fd
                )
                != terminal.trap.controller_descriptor
                or self.logical_controller_fd_inventory_after_probes.first_scan_started_monotonic_ns
                <= terminal.trap.observed_at_monotonic_ns
                or (
                    unix_root is not None
                    and (
                        unix_root.second_fstat_observed_at_monotonic_ns
                        < terminal.trap.observed_at_monotonic_ns
                        or unix_root.closed_at_monotonic_ns
                        < terminal.trap.observed_at_monotonic_ns
                    )
                )
            ):
                raise ValueError("kernel sandbox terminal trap is not a fresh reread")
        terminal_bytes = b"".join(
            canonical_model_bytes(item) + b"\n"
            for item in self.terminal_trap_observations
        )
        if (
            self.terminal_trap_log_count != len(self.terminal_trap_observations)
            or self.terminal_trap_log_size_bytes != len(terminal_bytes)
            or self.terminal_trap_log_sha256
            != hashlib.sha256(terminal_bytes).hexdigest()
        ):
            raise ValueError("kernel sandbox terminal trap log differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("kernel sandbox evidence identity differs")
        return self


def _kernel_sandbox_root_custody_sha256(
    authority: ImmutableRuntimeInputRootAuthority,
) -> str:
    """Bind one sandbox custody label to its retained held-vnode authority."""

    return _canonical_hash(
        {
            "schema_id": "phase-latency-kernel-sandbox-root-custody-v1",
            "root_authority": authority.model_dump(mode="json"),
        }
    )


def require_kernel_sandbox_immutable_input_custody(
    sandbox: KernelSandboxEvidence,
    custody: ImmutableRuntimeInputCustodyEvidence,
) -> None:
    """Cross-bind production reads and disposable probes to distinct roots."""

    authorities = {item.role: item for item in custody.root_authorities}
    expected_fields = {
        "docling_artifacts": sandbox.production_artifact_custody_sha256,
        "tessdata": sandbox.production_tessdata_custody_sha256,
        "staged_execution_inputs": (
            sandbox.production_staged_executable_custody_sha256
        ),
        "request_input_probe": sandbox.source_custody_sha256,
        "artifact_probe_clone": (
            sandbox.artifact_private_clone_custody_sha256
        ),
        "tessdata_probe_clone": (
            sandbox.tessdata_private_clone_custody_sha256
        ),
        "staged_executable_probe_clone": (
            sandbox.staged_executable_private_clone_custody_sha256
        ),
        "outside_probe_root": sandbox.outside_probe_root_custody_sha256,
    }
    if set(expected_fields) - set(authorities) or any(
        _kernel_sandbox_root_custody_sha256(authorities[role]) != expected
        for role, expected in expected_fields.items()
    ):
        raise ValueError("kernel sandbox immutable root custody differs")
    policy = sandbox.worker.profile_policy
    expected_paths = {
        "docling_artifacts": policy.artifact_root,
        "tessdata": policy.tessdata_root,
        "staged_execution_inputs": str(
            PurePosixPath(policy.immutable_executable).parent
        ),
        "request_input_probe": str(
            PurePosixPath(policy.input_probe_root)
            / policy.input_probe_relative_path
        ),
        "artifact_probe_clone": policy.artifact_probe_clone_root,
        "tessdata_probe_clone": policy.tessdata_probe_clone_root,
        "staged_executable_probe_clone": (
            policy.staged_executable_probe_clone_root
        ),
        "outside_probe_root": policy.outside_probe_root,
    }
    if any(
        authorities[role].resolved_path != path
        or authorities[role].kind
        != ("file" if role == "request_input_probe" else "directory")
        for role, path in expected_paths.items()
    ):
        raise ValueError("kernel sandbox immutable root path differs")


class NativeSelfCpuCounter(ContractModel):
    """Integral Darwin ``proc_pid_rusage`` self counters at one barrier."""

    identity: ExactProcessIdentity
    observed_monotonic_ns: PositiveInt
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt
    counter_source: Literal["darwin-proc-pid-rusage-v4-uint64-ns-v1"] = (
        "darwin-proc-pid-rusage-v4-uint64-ns-v1"
    )
    sampled_while_broker_armed_and_blocked: Literal[True] = True


class NativeKernelProcessIdentity(ContractModel):
    pid: PositiveInt
    start_abstime: PositiveInt
    ppid: PositiveInt
    pgid: PositiveInt
    sid: PositiveInt


class NativeThreadInventory(ContractModel):
    schema_id: Literal["darwin-detailed-thread-inventory-v1"] = (
        "darwin-detailed-thread-inventory-v1"
    )
    process: NativeKernelProcessIdentity
    identity_basis: Literal[
        "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    ] = "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
    first_scan_started_monotonic_ns: PositiveInt
    first_scan_completed_monotonic_ns: PositiveInt
    second_scan_started_monotonic_ns: PositiveInt
    second_scan_completed_monotonic_ns: PositiveInt
    thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=4_096)
    ]
    thread_count: PositiveInt
    inventory_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> "NativeThreadInventory":
        times = (
            self.first_scan_started_monotonic_ns,
            self.first_scan_completed_monotonic_ns,
            self.second_scan_started_monotonic_ns,
            self.second_scan_completed_monotonic_ns,
        )
        if (
            times != tuple(sorted(times))
            or self.thread_ids != tuple(sorted(set(self.thread_ids)))
            or self.thread_count != len(self.thread_ids)
            or self.inventory_sha256
            != _canonical_hash(
                {
                    "schema_id": self.schema_id,
                    "process": self.process.model_dump(mode="json"),
                    "identity_basis": self.identity_basis,
                    "thread_ids": list(self.thread_ids),
                    "thread_count": self.thread_count,
                }
            )
        ):
            raise ValueError("native thread inventory differs")
        return self


def native_thread_inventory(**fields: object) -> NativeThreadInventory:
    if "inventory_sha256" in fields:
        raise ValueError("native thread inventory identity is derived")
    process = fields.get("process")
    thread_ids = fields.get("thread_ids")
    if type(process) is not NativeKernelProcessIdentity or not isinstance(
        thread_ids, tuple
    ):
        raise ValueError("native thread inventory inputs differ")
    normalized = {
        **fields,
        "schema_id": "darwin-detailed-thread-inventory-v1",
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "thread_count": len(thread_ids),
    }
    return NativeThreadInventory(
        **normalized,
        inventory_sha256=_canonical_hash(
            {
                "schema_id": normalized["schema_id"],
                "process": process.model_dump(mode="json"),
                "identity_basis": normalized["identity_basis"],
                "thread_ids": list(thread_ids),
                "thread_count": len(thread_ids),
            }
        ),
    )


class NativeVnodeFileDescriptorIdentity(ContractModel):
    device: NonNegativeInt
    inode: NonNegativeInt
    mode: NonNegativeInt
    nlink: NonNegativeInt
    uid: NonNegativeInt
    gid: NonNegativeInt
    size: NonNegativeInt
    vnode_type: PositiveInt
    resolved_path_sha256: Sha256


class NativeSocketFileDescriptorIdentity(ContractModel):
    family: NonNegativeInt
    socket_type: NonNegativeInt
    protocol: NonNegativeInt
    socket_kind: NonNegativeInt
    socket_state: NonNegativeInt
    local_identity_sha256: Sha256
    peer_identity_sha256: Sha256


class NativePipeFileDescriptorIdentity(ContractModel):
    device: NonNegativeInt
    inode: NonNegativeInt
    mode: NonNegativeInt
    nlink: NonNegativeInt
    uid: NonNegativeInt
    gid: NonNegativeInt
    pipe_status: NonNegativeInt
    local_handle_sha256: Sha256
    peer_handle_sha256: Sha256


class NativeKqueueFileDescriptorIdentity(ContractModel):
    device: NonNegativeInt
    inode: NonNegativeInt
    mode: NonNegativeInt
    nlink: NonNegativeInt
    uid: NonNegativeInt
    gid: NonNegativeInt
    kqueue_state: NonNegativeInt


class NativeFileDescriptorIdentity(ContractModel):
    fd: NonNegativeInt
    kernel_type: Literal[1, 2, 5, 6]
    open_flags: NonNegativeInt
    kernel_status_flags: NonNegativeInt
    descriptor_offset: int
    descriptor_type: Literal[1, 2, 5, 6]
    guard_flags: NonNegativeInt
    close_on_exec: StrictBool
    close_on_fork: StrictBool
    guarded: StrictBool
    shared: StrictBool
    vnode: NativeVnodeFileDescriptorIdentity | None = None
    socket: NativeSocketFileDescriptorIdentity | None = None
    pipe: NativePipeFileDescriptorIdentity | None = None
    kqueue: NativeKqueueFileDescriptorIdentity | None = None
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_descriptor(self) -> "NativeFileDescriptorIdentity":
        variants = (self.vnode, self.socket, self.pipe, self.kqueue)
        expected_position = {1: 0, 2: 1, 6: 2, 5: 3}[self.kernel_type]
        if (
            self.descriptor_type != self.kernel_type
            or sum(item is not None for item in variants) != 1
            or variants[expected_position] is None
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("native file-descriptor identity differs")
        return self


class NativeFileDescriptorInventory(ContractModel):
    schema_id: Literal["darwin-detailed-file-descriptor-inventory-v1"] = (
        "darwin-detailed-file-descriptor-inventory-v1"
    )
    process: NativeKernelProcessIdentity
    first_scan_started_monotonic_ns: PositiveInt
    first_scan_completed_monotonic_ns: PositiveInt
    second_scan_started_monotonic_ns: PositiveInt
    second_scan_completed_monotonic_ns: PositiveInt
    descriptors: Annotated[
        tuple[NativeFileDescriptorIdentity, ...],
        Field(min_length=1, max_length=4_096),
    ]
    inventory_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> "NativeFileDescriptorInventory":
        times = (
            self.first_scan_started_monotonic_ns,
            self.first_scan_completed_monotonic_ns,
            self.second_scan_started_monotonic_ns,
            self.second_scan_completed_monotonic_ns,
        )
        descriptor_ids = tuple(item.fd for item in self.descriptors)
        if (
            times != tuple(sorted(times))
            or descriptor_ids != tuple(sorted(set(descriptor_ids)))
            or self.inventory_sha256
            != _canonical_hash(
                {
                    "schema_id": self.schema_id,
                    "process": self.process.model_dump(mode="json"),
                    "descriptors": [
                        item.model_dump(mode="json")
                        for item in self.descriptors
                    ],
                }
            )
        ):
            raise ValueError("native file-descriptor inventory differs")
        return self


def native_file_descriptor_identity(
    **fields: object,
) -> NativeFileDescriptorIdentity:
    if "record_sha256" in fields:
        raise ValueError("native file-descriptor record identity is derived")
    provisional = NativeFileDescriptorIdentity.model_construct(
        **fields, record_sha256="0" * 64
    )
    return NativeFileDescriptorIdentity(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


def native_file_descriptor_inventory(
    **fields: object,
) -> NativeFileDescriptorInventory:
    if "inventory_sha256" in fields:
        raise ValueError("native file-descriptor inventory identity is derived")
    process = fields["process"]
    descriptors = fields["descriptors"]
    if not isinstance(process, NativeKernelProcessIdentity) or not isinstance(
        descriptors, tuple
    ):
        raise ValueError("native file-descriptor inventory inputs differ")
    return NativeFileDescriptorInventory(
        **fields,
        inventory_sha256=_canonical_hash(
            {
                "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
                "process": process.model_dump(mode="json"),
                "descriptors": [
                    item.model_dump(mode="json") for item in descriptors
                ],
            }
        ),
    )


class NativeProcessResourceSample(ContractModel):
    """One controller-owned root CPU/RSS/thread/FD observation."""

    cpu: NativeSelfCpuCounter
    rss_bytes: NonNegativeInt
    thread_count: PositiveInt
    native_thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=4_096)
    ]
    file_descriptor_count: NonNegativeInt
    file_descriptor_inventory: NativeFileDescriptorInventory
    process_group_root_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_threads(self) -> "NativeProcessResourceSample":
        if (
            self.native_thread_ids != tuple(sorted(set(self.native_thread_ids)))
            or len(self.native_thread_ids) != self.thread_count
            or self.file_descriptor_count
            != len(self.file_descriptor_inventory.descriptors)
            or (
                self.file_descriptor_inventory.process.pid,
                self.file_descriptor_inventory.process.start_abstime,
                self.file_descriptor_inventory.process.ppid,
                self.file_descriptor_inventory.process.pgid,
                self.file_descriptor_inventory.process.sid,
            )
            != (
                self.cpu.identity.pid,
                self.cpu.identity.start_abstime,
                self.cpu.identity.parent_pid,
                self.cpu.identity.process_group_id,
                self.cpu.identity.session_id,
            )
        ):
            raise ValueError("native process thread/FD inventory differs")
        return self


# These readiness models are declared before the native inventory models to
# keep the request-control protocol definitions together. Resolve their strict
# forward references only after both complete inventory schemas exist.
BrokerPostReleaseBaseline.model_rebuild()
FrameworkThreadBaseline.model_rebuild()
RequestControlReadinessEvidence.model_rebuild()
KernelSandboxNetworkPositiveControl.model_rebuild()
KernelSandboxCapabilityIdentity.model_rebuild()
KernelSandboxTrapObservation.model_rebuild()
KernelSandboxRoleEvidence.model_rebuild()
KernelSandboxEvidence.model_rebuild()


class ExternalCpuStableEdgeRecord(ContractModel):
    """Controller-owned raw CPU/scratch sample at one blocked request edge."""

    schema_id: Literal["phase-latency-external-cpu-stable-edge-v1"] = (
        "phase-latency-external-cpu-stable-edge-v1"
    )
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    request_deadline_monotonic_ns: PositiveInt
    edge: Literal["begin", "end"]
    sample_order: Literal["broker-then-worker-stable-edge-v1"] = (
        "broker-then-worker-stable-edge-v1"
    )
    broker_sample: NativeProcessResourceSample
    worker_sample: NativeProcessResourceSample
    post_sample_scratch_inventory: "BrokerScratchInventory"
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_stable_edge(self) -> "ExternalCpuStableEdgeRecord":
        if (
            self.request_epoch != self.request_sequence + 1
            or self.broker_sample.cpu.identity.role != "tesseract_broker"
            or self.worker_sample.cpu.identity.role != "parser_worker"
            or not (
                self.broker_sample.cpu.observed_monotonic_ns
                <= self.worker_sample.cpu.observed_monotonic_ns
                <= self.post_sample_scratch_inventory.scan_started_monotonic_ns
                <= self.post_sample_scratch_inventory.scan_completed_monotonic_ns
                < self.request_deadline_monotonic_ns
            )
        ):
            raise ValueError("external stable-edge sample custody differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("external stable-edge sample identity differs")
        return self


def external_cpu_stable_edge_record(**fields: object) -> ExternalCpuStableEdgeRecord:
    if "record_sha256" in fields:
        raise ValueError("external CPU sample identity is derived")
    provisional = ExternalCpuStableEdgeRecord.model_construct(
        **fields, record_sha256="0" * 64
    )
    return ExternalCpuStableEdgeRecord(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),  # type: ignore[arg-type]
    )


class RawTimeval(ContractModel):
    """Integral native timeval retained without float reconstruction."""

    seconds: NonNegativeInt
    microseconds: Annotated[int, Field(strict=True, ge=0, le=999_999)]
    derived_ns: NonNegativeInt

    @model_validator(mode="after")
    def validate_timeval(self) -> "RawTimeval":
        if self.derived_ns != self.seconds * 1_000_000_000 + self.microseconds * 1_000:
            raise ValueError("native timeval nanoseconds must be recomputed")
        return self


class RawRUsage(ContractModel):
    user: RawTimeval
    system: RawTimeval
    source: Literal["native-wait4-timeval-v1"] = "native-wait4-timeval-v1"
    resolution_ns: Literal[1_000] = 1_000
    rounding_applied: Literal[False] = False


class BrokerExecutableIdentity(ContractModel):
    resolved_path: Annotated[str, Field(min_length=1, max_length=4_096)]
    sha256: Sha256
    device: NonNegativeInt
    inode: PositiveInt
    mode: NonNegativeInt
    uid: NonNegativeInt
    nlink: Literal[1] = 1
    size: PositiveInt

    @model_validator(mode="after")
    def validate_executable(self) -> "BrokerExecutableIdentity":
        if (
            not self.resolved_path.startswith("/")
            or PurePosixPath(self.resolved_path).as_posix() != self.resolved_path
            or any(part in {"", ".", ".."} for part in self.resolved_path.split("/")[1:])
            or (self.mode & 0o170000) != 0o100000
            or self.mode & (0o4000 | 0o2000)
        ):
            raise ValueError("broker executable identity differs")
        return self


class BrokerForkDenialIdentity(ContractModel):
    platform: Literal["darwin"] = "darwin"
    profile_sha256: Sha256
    wrapper_sha256: Sha256
    native_spawn_guard_source_sha256: Sha256
    native_spawn_guard_sha256: Sha256
    native_spawn_guard_kind: Literal[
        "darwin-__fork-child-nproc0-before-python-v1"
    ] = "darwin-__fork-child-nproc0-before-python-v1"
    guard_python_sha256: Sha256
    guard_python_path_custody_sha256: Sha256
    guard_python_native_closure_sha256: Sha256
    guard_python_module_tree_sha256: Sha256
    guard_python_path_exec_trust_model: Annotated[str, Field(min_length=1, max_length=128)]
    guard_python_path_exec_containment_claim: Annotated[str, Field(min_length=1, max_length=128)]
    guard_wrapper_delivery_basis: Literal[
        "execve-python-c-embedded-source-v1"
    ] = "execve-python-c-embedded-source-v1"
    guard_exec_argv_sha256: Sha256
    guard_exec_environment_sha256: Sha256
    guard_post_exec_environment_sha256: Sha256
    native_child_config_sha256: Sha256
    rlimit_nproc_soft: Literal[0] = 0
    rlimit_nproc_hard: Literal[0] = 0
    real_uid: PositiveInt
    effective_uid: PositiveInt
    applied_at_monotonic_ns: PositiveInt
    child_guard_applied_clock_authority: Annotated[
        str, Field(min_length=1, max_length=128)
    ]
    child_reported_guard_release_a_monotonic_ns: PositiveInt
    child_guard_release_a_record_sha256: Sha256
    child_guard_ready_observed_monotonic_ns: PositiveInt
    native_child_limit_applied_monotonic_ns: PositiveInt
    native_child_limit_applied_clock_authority: Literal[
        "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
    ] = "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
    native_child_limit_ack_authority: Literal[
        "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
    ] = "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
    native_child_limit_ack_pid: PositiveInt
    native_child_limit_ack_sha256: Sha256
    native_fork_parent_returned_monotonic_ns: PositiveInt
    native_child_limit_acknowledged_monotonic_ns: PositiveInt
    native_python_release_n_monotonic_ns: PositiveInt
    hard_limit_installed_before_python_return: Literal[True] = True
    pthread_atfork_callbacks_bypassed: Literal[True] = True
    prior_signal_mask: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=128)
    ]
    prior_signal_mask_sha256: Sha256
    restored_signal_mask: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=128)
    ]
    restored_signal_mask_sha256: Sha256
    exact_prior_signal_mask_restored_before_ready: Literal[True] = True
    ready_record_sha256: Sha256

    @model_validator(mode="after")
    def validate_native_spawn_guard(self) -> "BrokerForkDenialIdentity":
        from app.services.tesseract_broker_protocol import fork_denial_from_mapping

        try:
            fork_denial_from_mapping(self.model_dump(mode="json"))
        except Exception as error:
            raise ValueError("native child spawn denial differs") from error
        return self


class BrokerChildFileDescriptorIdentity(ContractModel):
    fd: NonNegativeInt
    kernel_fd_type: PositiveInt
    role: Literal[
        "stdin_pipe",
        "stdout_pipe",
        "stderr_pipe",
        "ready_pipe",
        "release_pipe",
        "staged_executable",
    ]
    close_on_exec: StrictBool
    stat_device: NonNegativeInt
    stat_inode: PositiveInt
    stat_mode: PositiveInt
    stat_mode_type: PositiveInt

    @model_validator(mode="after")
    def validate_descriptor(self) -> "BrokerChildFileDescriptorIdentity":
        if stat.S_IFMT(self.stat_mode) != self.stat_mode_type:
            raise ValueError("child descriptor mode identity differs")
        return self


_BROKER_CHILD_BIRTH_COMMITMENT_FIELDS = frozenset(
    {
        "schema_id",
        "request_id",
        "request_epoch",
        "request_sequence",
        "spawn_sequence",
        "spawn_nonce_sha256",
        "pid",
        "start_abstime",
        "ppid",
        "pgid",
        "sid",
        "broker_pid",
        "broker_start_abstime",
        "operation",
        "logical_argv_sha256",
        "actual_argv_sha256",
        "logical_environment_sha256",
        "actual_environment_projection_sha256",
        "input_sha256",
        "input_bytes",
        "executable_sha256",
        "native_closure_sha256",
        "native_trust_model",
        "native_containment_claim",
        "native_runtime_attestation_required",
        "native_runtime_scan_interval_ns",
        "native_runtime_gate_authority",
        "native_runtime_gate_initializer_order_limitation",
        "native_runtime_gate_source_sha256",
        "native_runtime_gate_library_sha256",
        "native_runtime_gate_record_sha256",
        "runtime_gate_nonce_sha256",
        "runtime_gate_ack_authority",
        "watchdog_registration_sha256",
        "watchdog_registration_ack_sha256",
        "broker_thread_count_before_fork",
        "broker_thread_inventory_sha256",
        "broker_thread_observed_at_monotonic_ns",
        "broker_thread_count_immediately_before_fork",
        "broker_thread_inventory_immediately_before_fork_sha256",
        "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
        "born_monotonic_ns",
        "blocked_signals_across_fork",
        "blocked_signals_across_fork_sha256",
        "blockable_signals_masked_across_fork",
        "registration_acknowledged_monotonic_ns",
        "guard_release_a_monotonic_ns",
        "spawn_intent_sha256",
        "spawn_intent_ledger_row_sha256",
        "spawn_intent_durable_acknowledged_monotonic_ns",
        "provisional_record_sha256",
        "provisional_child_ledger_row_sha256",
        "provisional_observed_monotonic_ns",
        "child_ready_sha256",
        "child_ready_intent_ledger_row_sha256",
        "open_fd_count",
        "open_file_descriptors",
        "open_fd_inventory_sha256",
        "native_thread_count",
        "native_thread_ids",
        "native_thread_inventory_sha256",
        "native_spawn_guard_sha256",
        "native_spawn_guard_source_sha256",
        "native_spawn_guard_kind",
        "guard_python_sha256",
        "guard_python_path_custody_sha256",
        "guard_python_native_closure_sha256",
        "guard_python_module_tree_sha256",
        "guard_python_path_exec_trust_model",
        "guard_python_path_exec_containment_claim",
        "guard_wrapper_delivery_basis",
        "guard_config_fd",
        "guard_ready_fd",
        "guard_exec_argv_sha256",
        "guard_exec_environment_sha256",
        "guard_post_exec_environment_sha256",
        "native_child_config_sha256",
        "native_child_config_projection",
        "native_child_config_projection_sha256",
        "native_child_limit_applied_monotonic_ns",
        "native_child_limit_applied_clock_authority",
        "native_child_limit_ack_authority",
        "native_child_limit_ack_pid",
        "native_child_limit_ack_sha256",
        "native_fork_parent_returned_monotonic_ns",
        "native_child_limit_acknowledged_monotonic_ns",
        "native_python_release_n_monotonic_ns",
        "child_guard_applied_at_monotonic_ns",
        "child_guard_applied_clock_authority",
        "child_reported_guard_release_a_monotonic_ns",
        "child_guard_release_a_record_sha256",
        "child_guard_ready_observed_monotonic_ns",
        "hard_limit_installed_before_python_return",
        "pthread_atfork_callbacks_bypassed",
        "prior_signal_mask",
        "prior_signal_mask_sha256",
        "restored_signal_mask",
        "restored_signal_mask_sha256",
        "exact_prior_signal_mask_restored_before_ready",
        "birth_commitment_sha256",
    }
)


def _validate_shared_child_birth_commitment(
    value: object,
) -> object:
    from app.services.tesseract_broker_protocol import (
        child_birth_commitment_from_mapping,
    )

    try:
        child_birth_commitment_from_mapping(value.model_dump(mode="python"))
    except Exception as error:
        raise ValueError("broker child birth commitment differs") from error
    return value


BrokerChildBirthCommitment = create_model(
    "BrokerChildBirthCommitment",
    __base__=ContractModel,
    __validators__={
        "validate_commitment": model_validator(mode="after")(
            _validate_shared_child_birth_commitment
        )
    },
    **{name: (object, ...) for name in _BROKER_CHILD_BIRTH_COMMITMENT_FIELDS},
)
BrokerChildBirthCommitment.__module__ = __name__


class BrokerChildBirth(ContractModel):
    """Exact app-protocol birth row with distinct guard-A and exec-E gates."""

    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    spawn_sequence: PositiveInt
    spawn_nonce_sha256: Sha256
    record_sequence: PositiveInt
    previous_record_sha256: Sha256
    pid: PositiveInt
    start_abstime: PositiveInt
    ppid: PositiveInt
    pgid: PositiveInt
    sid: PositiveInt
    broker_pid: PositiveInt
    broker_start_abstime: PositiveInt
    identity_basis: Literal["direct-parent-unreaped-spawn-token-v1"] = (
        "direct-parent-unreaped-spawn-token-v1"
    )
    born_monotonic_ns: PositiveInt
    spawn_intent_sha256: Sha256
    spawn_intent_ledger_row_sha256: Sha256
    spawn_intent_durable_acknowledged_monotonic_ns: PositiveInt
    provisional_record_sha256: Sha256
    provisional_child_ledger_row_sha256: Sha256
    provisional_observed_monotonic_ns: PositiveInt
    child_ready_sha256: Sha256
    child_ready_intent_ledger_row_sha256: Sha256
    open_fd_count: Literal[6] = 6
    open_file_descriptors: Annotated[
        tuple[BrokerChildFileDescriptorIdentity, ...],
        Field(min_length=6, max_length=6),
    ]
    open_fd_inventory_sha256: Sha256
    native_thread_count: Literal[1] = 1
    native_thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=1)
    ]
    native_thread_inventory_sha256: Sha256
    broker_thread_count_before_fork: Literal[1] = 1
    broker_thread_inventory_sha256: Sha256
    broker_thread_observed_at_monotonic_ns: PositiveInt
    broker_thread_count_immediately_before_fork: Literal[1] = 1
    broker_thread_inventory_immediately_before_fork_sha256: Sha256
    broker_thread_immediately_before_fork_observed_at_monotonic_ns: PositiveInt
    blocked_signals_across_fork: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=128)
    ]
    blocked_signals_across_fork_sha256: Sha256
    blockable_signals_masked_across_fork: Literal[True] = True
    registration_acknowledged_monotonic_ns: PositiveInt
    guard_release_a_monotonic_ns: PositiveInt
    child_reported_guard_release_a_monotonic_ns: PositiveInt
    child_guard_release_a_record_sha256: Sha256
    birth_durable_acknowledged_monotonic_ns: PositiveInt
    exec_release_e_monotonic_ns: PositiveInt
    operation: Literal["version", "list_languages", "ocr_tsv", "ocr_text", "osd"]
    logical_argv_sha256: Sha256
    actual_argv_sha256: Sha256
    logical_environment_sha256: Sha256
    actual_environment_projection_sha256: Sha256
    input_sha256: Sha256
    input_bytes: NonNegativeInt
    executable: BrokerExecutableIdentity
    native_closure_sha256: Sha256
    native_trust_model: Literal["frozen-native-closure-trusted-v1"] = (
        "frozen-native-closure-trusted-v1"
    )
    native_containment_claim: Literal[
        "none-trusted-pinned-native-computation"
    ] = "none-trusted-pinned-native-computation"
    native_runtime_attestation_required: Literal[True] = True
    native_runtime_scan_interval_ns: Literal[100_000_000] = 100_000_000
    native_runtime_gate_authority: Annotated[str, Field(min_length=1, max_length=128)]
    native_runtime_gate_initializer_order_limitation: Annotated[
        str, Field(min_length=1, max_length=256)
    ]
    native_runtime_gate_source_sha256: Sha256
    native_runtime_gate_library_sha256: Sha256
    native_runtime_gate_record_sha256: Sha256
    runtime_gate_nonce_sha256: Sha256
    runtime_gate_ack_authority: Annotated[str, Field(min_length=1, max_length=128)]
    guard_python_sha256: Sha256
    guard_python_path_custody_sha256: Sha256
    guard_python_native_closure_sha256: Sha256
    guard_python_module_tree_sha256: Sha256
    guard_python_path_exec_trust_model: Annotated[str, Field(min_length=1, max_length=128)]
    guard_python_path_exec_containment_claim: Annotated[str, Field(min_length=1, max_length=128)]
    guard_wrapper_delivery_basis: Literal[
        "execve-python-c-embedded-source-v1"
    ] = "execve-python-c-embedded-source-v1"
    guard_config_fd: NonNegativeInt
    guard_ready_fd: NonNegativeInt
    guard_exec_argv_sha256: Sha256
    guard_exec_environment_sha256: Sha256
    guard_post_exec_environment_sha256: Sha256
    native_child_config_sha256: Sha256
    native_child_config_projection: dict[str, object]
    native_child_config_projection_sha256: Sha256
    fork_denial: BrokerForkDenialIdentity
    child_reported_identity_matched: Literal[True] = True
    registration_durable_before_guard_release_a: Literal[True] = True
    birth_durable_before_exec_release_e: Literal[True] = True
    pre_exec_gate_closed_before_custody: Literal[True] = True
    hard_nproc_zero_before_exec: Literal[True] = True
    watchdog_registration_sha256: Sha256
    watchdog_registration_ack_sha256: Sha256
    birth_commitment_sha256: Sha256
    birth_ledger_row_sha256: Sha256
    watchdog_birth_sha256: Sha256
    watchdog_birth_ack_sha256: Sha256
    exec_release_ledger_row_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_birth(self) -> "BrokerChildBirth":
        from app.services.tesseract_broker_protocol import child_birth_from_mapping

        try:
            child_birth_from_mapping(self.model_dump(mode="json"))
        except Exception as error:
            raise ValueError("broker child birth/lineage chronology differs") from error
        if self.birth_commitment_sha256 != broker_child_birth_commitment_sha256(
            self
        ):
            raise ValueError("broker child birth commitment differs")
        return self

        # Kept below as documentation of the shared projection's local shape;
        # the frozen application parser above is the byte-identical authority.
        expected_descriptors = (
            (0, 6, "stdin_pipe", False, stat.S_IFIFO),
            (1, 6, "stdout_pipe", False, stat.S_IFIFO),
            (2, 6, "stderr_pipe", False, stat.S_IFIFO),
            (3, 6, "ready_pipe", True, stat.S_IFIFO),
            (4, 6, "release_pipe", True, stat.S_IFIFO),
            (5, 1, "staged_executable", True, stat.S_IFREG),
        )
        observed_descriptors = tuple(
            (
                item.fd,
                item.kernel_fd_type,
                item.role,
                item.close_on_exec,
                item.stat_mode_type,
            )
            for item in self.open_file_descriptors
        )
        if (
            self.ppid != self.broker_pid
            or self.pgid != self.broker_pid
            or self.sid != self.broker_pid
            or self.fork_denial.ready_record_sha256 != self.child_ready_sha256
            or self.fork_denial.native_child_limit_ack_pid != self.pid
            or observed_descriptors != expected_descriptors
            or self.native_thread_ids != tuple(sorted(set(self.native_thread_ids)))
            or self.open_fd_inventory_sha256
            != _canonical_hash(
                {
                    "open_file_descriptors": [
                        item.model_dump(mode="json")
                        for item in self.open_file_descriptors
                    ]
                }
            )
            or self.native_thread_inventory_sha256
            != _canonical_hash({"native_thread_ids": list(self.native_thread_ids)})
            or self.broker_thread_inventory_immediately_before_fork_sha256
            != self.broker_thread_inventory_sha256
            or self.blocked_signals_across_fork
            != tuple(sorted(set(self.blocked_signals_across_fork)))
            or self.blocked_signals_across_fork_sha256
            != _canonical_hash(
                {
                    "blocked_signals": list(
                        self.blocked_signals_across_fork
                    )
                }
            )
            or self.birth_commitment_sha256
            != broker_child_birth_commitment_sha256(self)
            or not (
                self.broker_thread_observed_at_monotonic_ns
                <= self.spawn_intent_durable_acknowledged_monotonic_ns
                <= self.broker_thread_immediately_before_fork_observed_at_monotonic_ns
                <= self.born_monotonic_ns
                <= self.fork_denial.native_fork_parent_returned_monotonic_ns
                <= self.fork_denial.native_child_limit_acknowledged_monotonic_ns
                <= self.provisional_observed_monotonic_ns
                <= self.registration_acknowledged_monotonic_ns
                <= self.fork_denial.native_python_release_n_monotonic_ns
                <= self.fork_denial.applied_at_monotonic_ns
                <= self.guard_release_a_monotonic_ns
                <= self.birth_durable_acknowledged_monotonic_ns
                <= self.exec_release_e_monotonic_ns
            )
        ):
            raise ValueError("broker child birth/lineage chronology differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("broker child birth record identity differs")
        return self


def broker_child_birth_commitment_sha256(value: BrokerChildBirth) -> str:
    """Reconstruct the broker's exact durable birth-commitment projection."""

    from dataclasses import fields as dataclass_fields

    from app.services.tesseract_broker_protocol import (
        BrokerChildBirthCommitment as AppBrokerChildBirthCommitment,
        child_birth_commitment_from_mapping,
    )

    direct = value.model_dump(mode="json")
    raw_fork_denial = direct.get("fork_denial")
    raw_executable = direct.get("executable")
    if not isinstance(raw_fork_denial, dict) or not isinstance(
        raw_executable, dict
    ):
        raise ValueError("broker child birth commitment projection differs")
    fork_denial = raw_fork_denial
    commitment: dict[str, object] = {
        "schema_id": "parser-tesseract-child-birth-commitment-v1"
    }
    commitment_fields = frozenset(
        item.name for item in dataclass_fields(AppBrokerChildBirthCommitment)
    )
    for field in commitment_fields - {
        "schema_id",
        "birth_commitment_sha256",
    }:
        if field == "executable_sha256":
            commitment[field] = raw_executable.get("sha256")
        elif field == "child_guard_applied_at_monotonic_ns":
            commitment[field] = fork_denial.get("applied_at_monotonic_ns")
        elif field in direct:
            commitment[field] = direct[field]
        elif field in fork_denial:
            commitment[field] = fork_denial[field]
        else:  # pragma: no cover - field set is deliberately closed above.
            raise ValueError("broker child birth commitment projection differs")
    expected = _canonical_hash(commitment)
    child_birth_commitment_from_mapping(
        {**commitment, "birth_commitment_sha256": expected}
    )
    return expected


_NATIVE_RUNTIME_SCAN_FIELDS = frozenset(
    {
        "schema_id",
        "authority",
        "process",
        "native_closure_sha256",
        "system_cache_sha256",
        "staged_executable_sha256",
        "staged_executable_device",
        "staged_executable_inode",
        "staged_executable_content_stable",
        "bracket_started_monotonic_ns",
        "kernel_scan_started_monotonic_ns",
        "kernel_scan_completed_monotonic_ns",
        "bracket_completed_monotonic_ns",
        "total_region_count",
        "executable_region_count",
        "mapped_image_count",
        "mapped_images",
        "expected_non_system_image_count",
        "expected_non_system_projection_sha256",
        "observed_non_system_image_count",
        "observed_non_system_projection_sha256",
        "raw_kernel_inventory_sha256",
        "all_non_system_images_in_frozen_closure",
        "sealed_system_images_bound_to_cache",
        "record_sha256",
    }
)
_NATIVE_RUNTIME_IMAGE_FIELDS = frozenset(
    {
        "resolved_path",
        "device",
        "inode",
        "mode",
        "uid",
        "gid",
        "nlink",
        "size",
        "mtime_ns",
        "ctime_ns",
        "system_image",
        "closure_image_sha256",
        "executable_regions",
        "executable_region_count",
        "record_sha256",
    }
)
_NATIVE_RUNTIME_REGION_FIELDS = frozenset(
    {
        "address",
        "size",
        "file_offset",
        "protection",
        "maximum_protection",
        "user_tag",
        "object_id",
        "resolved_path",
        "device",
        "inode",
        "mode",
        "uid",
        "gid",
        "nlink",
        "file_size",
        "mtime_ns",
        "ctime_ns",
        "vnode_type",
    }
)


def _require_native_runtime_scan(value: object) -> dict[str, object]:
    """Replay the bounded canonical libproc executable-region scan."""

    if not isinstance(value, dict) or set(value) != _NATIVE_RUNTIME_SCAN_FIELDS:
        raise ValueError("native runtime scan fields differ")
    scan = dict(value)
    if (
        scan["schema_id"] != "parser-tesseract-native-runtime-scan-v1"
        or scan["authority"] != "darwin-libproc-executable-regions-v1"
    ):
        raise ValueError("native runtime scan authority differs")
    process = scan["process"]
    if (
        not isinstance(process, dict)
        or set(process) != {"pid", "start_abstime", "ppid", "pgid", "sid"}
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item <= 0
            for item in process.values()
        )
    ):
        raise ValueError("native runtime process identity differs")
    for name in (
        "native_closure_sha256",
        "system_cache_sha256",
        "staged_executable_sha256",
        "raw_kernel_inventory_sha256",
        "expected_non_system_projection_sha256",
        "observed_non_system_projection_sha256",
        "record_sha256",
    ):
        if not isinstance(scan[name], str) or _SHA256.fullmatch(scan[name]) is None:
            raise ValueError(f"native runtime {name} differs")
    for name in (
        "staged_executable_device",
        "staged_executable_inode",
        "bracket_started_monotonic_ns",
        "kernel_scan_started_monotonic_ns",
        "kernel_scan_completed_monotonic_ns",
        "bracket_completed_monotonic_ns",
        "total_region_count",
        "executable_region_count",
        "mapped_image_count",
        "expected_non_system_image_count",
        "observed_non_system_image_count",
    ):
        item = scan[name]
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError(f"native runtime {name} differs")
    if any(
        scan[name] is not True
        for name in (
            "staged_executable_content_stable",
            "all_non_system_images_in_frozen_closure",
            "sealed_system_images_bound_to_cache",
        )
    ) or not (
        scan["bracket_started_monotonic_ns"]
        <= scan["kernel_scan_started_monotonic_ns"]
        <= scan["kernel_scan_completed_monotonic_ns"]
        <= scan["bracket_completed_monotonic_ns"]
    ):
        raise ValueError("native runtime scan chronology differs")
    images = scan["mapped_images"]
    if not isinstance(images, list) or len(images) != scan["mapped_image_count"]:
        raise ValueError("native runtime mapped-image count differs")
    region_count = 0
    staged_count = 0
    seen_paths: set[str] = set()
    kernel_regions: list[dict[str, object]] = []
    for raw_image in images:
        if (
            not isinstance(raw_image, dict)
            or set(raw_image) != _NATIVE_RUNTIME_IMAGE_FIELDS
        ):
            raise ValueError("native runtime image fields differ")
        image = dict(raw_image)
        path = image["resolved_path"]
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path in seen_paths
        ):
            raise ValueError("native runtime mapped-image path differs")
        seen_paths.add(path)
        if type(image["system_image"]) is not bool:
            raise ValueError("native runtime system-image disposition differs")
        for name in ("closure_image_sha256", "record_sha256"):
            if (
                not isinstance(image[name], str)
                or _SHA256.fullmatch(image[name]) is None
            ):
                raise ValueError(f"native runtime image {name} differs")
        for name in (
            "device",
            "inode",
            "mode",
            "nlink",
            "size",
            "mtime_ns",
            "ctime_ns",
            "executable_region_count",
        ):
            item = image[name]
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ValueError(f"native runtime image {name} differs")
        for name in ("uid", "gid"):
            item = image[name]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ValueError(f"native runtime image {name} differs")
        regions = image["executable_regions"]
        if (
            not isinstance(regions, list)
            or not regions
            or len(regions) != image["executable_region_count"]
        ):
            raise ValueError("native runtime executable-region count differs")
        previous_end = 0
        for raw_region in regions:
            if (
                not isinstance(raw_region, dict)
                or set(raw_region) != _NATIVE_RUNTIME_REGION_FIELDS
            ):
                raise ValueError("native runtime region fields differ")
            region = dict(raw_region)
            for name in (
                "address",
                "size",
                "protection",
                "maximum_protection",
                "device",
                "inode",
                "mode",
                "nlink",
                "file_size",
                "mtime_ns",
                "ctime_ns",
                "vnode_type",
            ):
                item = region[name]
                if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                    raise ValueError(f"native runtime region {name} differs")
            for name in ("file_offset", "user_tag", "object_id", "uid", "gid"):
                item = region[name]
                if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                    raise ValueError(f"native runtime region {name} differs")
            if (
                region["resolved_path"] != path
                or region["device"] != image["device"]
                or region["inode"] != image["inode"]
                or region["mode"] != image["mode"]
                or region["uid"] != image["uid"]
                or region["gid"] != image["gid"]
                or region["nlink"] != image["nlink"]
                or region["file_size"] != image["size"]
                or region["mtime_ns"] != image["mtime_ns"]
                or region["ctime_ns"] != image["ctime_ns"]
                or int(region["protection"]) & 0x04 == 0
                or int(region["address"]) < previous_end
            ):
                raise ValueError("native runtime executable-region identity differs")
            previous_end = int(region["address"]) + int(region["size"])
            kernel_regions.append(region)
        if image["record_sha256"] != _canonical_hash(
            {key: item for key, item in image.items() if key != "record_sha256"}
        ):
            raise ValueError("native runtime mapped-image digest differs")
        region_count += len(regions)
        if (
            image["device"] == scan["staged_executable_device"]
            and image["inode"] == scan["staged_executable_inode"]
            and image["closure_image_sha256"]
            == scan["staged_executable_sha256"]
        ):
            staged_count += 1
    kernel_regions.sort(key=lambda item: int(item["address"]))
    if (
        region_count != scan["executable_region_count"]
        or staged_count != 1
        or scan["expected_non_system_image_count"]
        != scan["observed_non_system_image_count"]
        or scan["expected_non_system_projection_sha256"]
        != scan["observed_non_system_projection_sha256"]
        or len({item["address"] for item in kernel_regions})
        != len(kernel_regions)
        or scan["raw_kernel_inventory_sha256"]
        != _canonical_hash({"process": process, "regions": kernel_regions})
        or scan["record_sha256"]
        != _canonical_hash(
            {key: item for key, item in scan.items() if key != "record_sha256"}
        )
    ):
        raise ValueError("native runtime scan identity differs")
    return scan


class NativeRuntimeScanSample(ContractModel):
    scan_sequence: PositiveInt
    bracket_started_monotonic_ns: PositiveInt
    kernel_scan_started_monotonic_ns: PositiveInt
    kernel_scan_completed_monotonic_ns: PositiveInt
    bracket_completed_monotonic_ns: PositiveInt
    total_region_count: PositiveInt
    raw_kernel_inventory_sha256: Sha256
    full_scan_record_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_sample(self) -> "NativeRuntimeScanSample":
        if not (
            self.bracket_started_monotonic_ns
            <= self.kernel_scan_started_monotonic_ns
            <= self.kernel_scan_completed_monotonic_ns
            <= self.bracket_completed_monotonic_ns
        ) or self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("native runtime scan-sample identity differs")
        return self


class NativeRuntimeImageAttestation(ContractModel):
    schema_id: Literal["parser-tesseract-native-runtime-attestation-v1"]
    authority: Literal["darwin-libproc-executable-regions-v1"]
    operation: Literal["version", "list_languages", "ocr_tsv", "ocr_text", "osd"]
    operation_family_sha256: Sha256
    logical_environment_sha256: Sha256
    actual_environment_projection: dict[str, object]
    actual_environment_projection_sha256: Sha256
    native_closure_sha256: Sha256
    expected_non_system_image_count: PositiveInt
    expected_non_system_projection_sha256: Sha256
    observed_non_system_image_count: PositiveInt
    observed_non_system_projection_sha256: Sha256
    system_cache_sha256: Sha256
    dynamic_loader_imports_sha256: Sha256
    dynamic_loader_importing_image_count: NonNegativeInt
    native_trust_model: Literal["frozen-native-closure-trusted-v1"]
    native_containment_claim: Literal[
        "none-trusted-pinned-native-computation"
    ]
    polling_completeness: Literal[
        "bounded-100ms-not-event-complete-trusted-pinned-code-v1"
    ]
    scan_interval_limit_ns: Literal[100_000_000]
    native_runtime_gate_authority: Annotated[str, Field(min_length=1, max_length=128)]
    native_runtime_gate_initializer_order_limitation: Annotated[
        str, Field(min_length=1, max_length=256)
    ]
    native_runtime_gate_source_sha256: Sha256
    native_runtime_gate_library_sha256: Sha256
    native_runtime_gate_record_sha256: Sha256
    runtime_gate_nonce_sha256: Sha256
    runtime_gate_ack_authority: Annotated[str, Field(min_length=1, max_length=128)]
    runtime_gate_ack_c_clock_authority: Annotated[
        str, Field(min_length=1, max_length=128)
    ]
    runtime_gate_ack_pid: PositiveInt
    runtime_gate_ack_c_monotonic_ns: PositiveInt
    runtime_gate_raw_ack_hex: Annotated[str, Field(min_length=2, max_length=256)]
    runtime_gate_raw_ack_sha256: Sha256
    runtime_gate_ack_sha256: Sha256
    exec_release_e_monotonic_ns: PositiveInt
    runtime_gate_ack_observed_monotonic_ns: PositiveInt
    runtime_gate_fd_eof_observed_monotonic_ns: PositiveInt
    same_pid_exec_observed_monotonic_ns: PositiveInt
    constructor_stop_observed_monotonic_ns: PositiveInt
    stopped_signal_number: PositiveInt
    stopped_thread_inventory: dict[str, object]
    stopped_file_descriptor_inventory: dict[str, object]
    runtime_gate_transition_sha256: Sha256
    runtime_gate_transition_ledger_row_sha256: Sha256
    guard_to_exec_transition_sha256: Sha256
    continued_signal_sent_monotonic_ns: PositiveInt
    continued_observed_monotonic_ns: PositiveInt
    actual_child_stop_gated: Literal[True]
    initial_scan: dict[str, object]
    scan_samples: Annotated[
        tuple[NativeRuntimeScanSample, ...], Field(min_length=2, max_length=4096)
    ]
    scan_count: Annotated[int, Field(strict=True, ge=2, le=4096)]
    stopped_scan_count: PositiveInt
    post_continue_scan_count: NonNegativeInt
    fast_terminal_after_gate: StrictBool
    scan_log_sha256: Sha256
    first_scan_started_monotonic_ns: PositiveInt
    double_stable_completed_monotonic_ns: PositiveInt
    first_input_write_monotonic_ns: NonNegativeInt
    last_scan_completed_monotonic_ns: PositiveInt
    terminal_waitid_code: NonNegativeInt
    terminal_waitid_status: NonNegativeInt
    terminal_nonreaping_observed_monotonic_ns: PositiveInt
    maximum_scan_gap_ns: NonNegativeInt
    all_scans_same_inventory: Literal[True]
    instrumentation_through_terminal: Literal[True]
    static_closure_revalidated_after_wait4: Literal[True]
    static_closure_post_wait4_sha256: Sha256
    transient_dlopen_polling_gap_disclosed: Literal[True]
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_attestation(self) -> "NativeRuntimeImageAttestation":
        from app.services.tesseract_broker_protocol import (
            NativeRuntimeImageAttestation as AppNativeRuntimeImageAttestation,
            NativeRuntimeScanSample as AppNativeRuntimeScanSample,
        )

        mapping = self.model_dump(mode="python")
        mapping["scan_samples"] = tuple(
            AppNativeRuntimeScanSample(**item.model_dump(mode="python"))
            for item in self.scan_samples
        )
        try:
            AppNativeRuntimeImageAttestation(**mapping)
        except Exception as error:
            raise ValueError("native runtime attestation differs") from error
        return self

        initial = _require_native_runtime_scan(self.initial_scan)
        samples = self.scan_samples
        if (
            initial["native_closure_sha256"] != self.native_closure_sha256
            or initial["expected_non_system_image_count"]
            != self.expected_non_system_image_count
            or initial["observed_non_system_image_count"]
            != self.observed_non_system_image_count
            or initial["expected_non_system_projection_sha256"]
            != self.expected_non_system_projection_sha256
            or initial["observed_non_system_projection_sha256"]
            != self.observed_non_system_projection_sha256
            or self.expected_non_system_image_count
            != self.observed_non_system_image_count
            or self.expected_non_system_projection_sha256
            != self.observed_non_system_projection_sha256
            or initial["system_cache_sha256"] != self.system_cache_sha256
            or self.static_closure_post_wait4_sha256 != self.native_closure_sha256
            or len(samples) != self.scan_count
            or tuple(item.scan_sequence for item in samples)
            != tuple(range(1, len(samples) + 1))
        ):
            raise ValueError("native runtime scan/closure binding differs")
        first, second = samples[:2]
        if (
            first.bracket_started_monotonic_ns
            != initial["bracket_started_monotonic_ns"]
            or first.full_scan_record_sha256 != initial["record_sha256"]
            or first.raw_kernel_inventory_sha256
            != initial["raw_kernel_inventory_sha256"]
            or any(
                sample.raw_kernel_inventory_sha256
                != first.raw_kernel_inventory_sha256
                for sample in samples
            )
            or self.first_scan_started_monotonic_ns
            != first.bracket_started_monotonic_ns
            or self.double_stable_completed_monotonic_ns
            != second.bracket_completed_monotonic_ns
            or self.last_scan_completed_monotonic_ns
            != samples[-1].bracket_completed_monotonic_ns
        ):
            raise ValueError("native runtime double-stable scan binding differs")
        gaps = tuple(
            current.bracket_started_monotonic_ns
            - previous.bracket_completed_monotonic_ns
            for previous, current in zip(samples, samples[1:], strict=False)
        )
        if (
            any(gap < 0 or gap > self.scan_interval_limit_ns for gap in gaps)
            or self.maximum_scan_gap_ns != (max(gaps) if gaps else 0)
            or any(
                item.bracket_completed_monotonic_ns
                - item.bracket_started_monotonic_ns
                > self.scan_interval_limit_ns
                for item in samples
            )
            or not (
                self.same_pid_exec_observed_monotonic_ns
                <= self.stop_signal_sent_monotonic_ns
                <= self.stop_observed_monotonic_ns
                <= self.first_scan_started_monotonic_ns
                <= self.double_stable_completed_monotonic_ns
                <= self.continued_signal_sent_monotonic_ns
                <= self.continued_observed_monotonic_ns
                <= self.last_scan_completed_monotonic_ns
                <= self.terminal_nonreaping_observed_monotonic_ns
            )
            or self.terminal_nonreaping_observed_monotonic_ns
            - self.last_scan_completed_monotonic_ns
            > self.scan_interval_limit_ns
            or (
                self.first_input_write_monotonic_ns
                and self.first_input_write_monotonic_ns
                < samples[2].bracket_completed_monotonic_ns
            )
            or self.scan_log_sha256
            != _canonical_hash(
                {"scan_samples": [item.model_dump(mode="json") for item in samples]}
            )
        ):
            raise ValueError("native runtime scan chronology/cadence differs")
        for sample in samples:
            reconstructed = {
                key: item for key, item in initial.items() if key != "record_sha256"
            }
            reconstructed.update(
                {
                    "bracket_started_monotonic_ns": sample.bracket_started_monotonic_ns,
                    "kernel_scan_started_monotonic_ns": sample.kernel_scan_started_monotonic_ns,
                    "kernel_scan_completed_monotonic_ns": sample.kernel_scan_completed_monotonic_ns,
                    "bracket_completed_monotonic_ns": sample.bracket_completed_monotonic_ns,
                    "total_region_count": sample.total_region_count,
                    "raw_kernel_inventory_sha256": sample.raw_kernel_inventory_sha256,
                }
            )
            reconstructed["record_sha256"] = _canonical_hash(reconstructed)
            if (
                _require_native_runtime_scan(reconstructed)["record_sha256"]
                != sample.full_scan_record_sha256
            ):
                raise ValueError("native runtime scan delta differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("native runtime attestation identity differs")
        return self


class BrokerChildWait4Tombstone(ContractModel):
    """Exact raw native wait4 result for one unreaped birth identity."""

    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    spawn_sequence: PositiveInt
    spawn_nonce_sha256: Sha256
    record_sequence: PositiveInt
    previous_record_sha256: Sha256
    birth_record_sha256: Sha256
    pid: PositiveInt
    start_abstime: PositiveInt
    raw_wait_status: NonNegativeInt
    exited: StrictBool
    exit_code: Annotated[int, Field(strict=True, ge=0, le=255)] | None
    signaled: StrictBool
    signal_number: PositiveInt | None
    core_dumped: StrictBool
    rusage: RawRUsage
    stdout_bytes: NonNegativeInt
    stdout_retained_bytes: NonNegativeInt
    stdout_sha256: Sha256
    stdout_disposition: Literal["captured", "discarded"]
    stderr_bytes: NonNegativeInt
    stderr_retained_bytes: NonNegativeInt
    stderr_sha256: Sha256
    stderr_disposition: Literal["captured", "discarded"]
    overflowed: StrictBool
    observed_monotonic_ns: PositiveInt
    maximum_resident_set_size_bytes: NonNegativeInt
    minor_faults: NonNegativeInt
    major_faults: NonNegativeInt
    voluntary_context_switches: NonNegativeInt
    involuntary_context_switches: NonNegativeInt
    nonreaping_wait4_probe_count: NonNegativeInt
    terminal_wait4_reap_count: Literal[1] = 1
    direct_parent_waited: Literal[True] = True
    native_runtime_attestation: NativeRuntimeImageAttestation
    record_sha256: Sha256

    @property
    def user_cpu_ns(self) -> int:
        return self.rusage.user.derived_ns

    @property
    def system_cpu_ns(self) -> int:
        return self.rusage.system.derived_ns

    @property
    def maximum_resident_set_bytes(self) -> int:
        return self.maximum_resident_set_size_bytes

    @model_validator(mode="after")
    def validate_tombstone(self) -> "BrokerChildWait4Tombstone":
        expected_exited = os.WIFEXITED(self.raw_wait_status)
        expected_signaled = os.WIFSIGNALED(self.raw_wait_status)
        expected_exit = os.WEXITSTATUS(self.raw_wait_status) if expected_exited else None
        expected_signal = os.WTERMSIG(self.raw_wait_status) if expected_signaled else None
        expected_core = (
            bool(os.WCOREDUMP(self.raw_wait_status))
            if expected_signaled and hasattr(os, "WCOREDUMP")
            else False
        )
        if (
            self.request_epoch != self.request_sequence + 1
            or self.exited != expected_exited
            or self.signaled != expected_signaled
            or self.exited == self.signaled
            or self.exit_code != expected_exit
            or self.signal_number != expected_signal
            or self.core_dumped != expected_core
            or self.native_runtime_attestation.last_scan_completed_monotonic_ns
            > self.native_runtime_attestation.terminal_nonreaping_observed_monotonic_ns
            or self.native_runtime_attestation.terminal_nonreaping_observed_monotonic_ns
            > self.observed_monotonic_ns
            or self.stdout_retained_bytes > self.stdout_bytes
            or self.stderr_retained_bytes > self.stderr_bytes
            or (
                self.stdout_disposition == "discarded"
                and self.stdout_retained_bytes != 0
            )
            or (
                self.stderr_disposition == "discarded"
                and self.stderr_retained_bytes != 0
            )
            or (
                not self.overflowed
                and self.stdout_disposition == "captured"
                and self.stdout_retained_bytes != self.stdout_bytes
            )
            or (
                not self.overflowed
                and self.stderr_disposition == "captured"
                and self.stderr_retained_bytes != self.stderr_bytes
            )
        ):
            raise ValueError("wait4 tombstone status/stream custody differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("wait4 tombstone record identity differs")
        return self


class BrokerChildCpuReceipt(ContractModel):
    birth: BrokerChildBirth
    tombstone: BrokerChildWait4Tombstone
    watchdog_closure_record_sha256: Sha256
    watchdog_exact_pid_closure_confirmed: Literal[True] = True
    identity_or_group_drift_observed: Literal[False] = False

    @model_validator(mode="after")
    def validate_join(self) -> "BrokerChildCpuReceipt":
        birth_key = (
            self.birth.request_id,
            self.birth.request_epoch,
            self.birth.request_sequence,
            self.birth.spawn_sequence,
            self.birth.spawn_nonce_sha256,
            self.birth.pid,
            self.birth.start_abstime,
            self.birth.record_sha256,
        )
        tombstone_key = (
            self.tombstone.request_id,
            self.tombstone.request_epoch,
            self.tombstone.request_sequence,
            self.tombstone.spawn_sequence,
            self.tombstone.spawn_nonce_sha256,
            self.tombstone.pid,
            self.tombstone.start_abstime,
            self.tombstone.birth_record_sha256,
        )
        if birth_key != tombstone_key:
            raise ValueError("broker child birth/wait4 tombstone identity differs")
        attestation = self.tombstone.native_runtime_attestation
        if (
            self.tombstone.record_sequence <= self.birth.record_sequence
            or self.tombstone.previous_record_sha256 != self.birth.record_sha256
            or self.tombstone.observed_monotonic_ns
            < self.birth.exec_release_e_monotonic_ns
            or self.birth.native_runtime_attestation_required is not True
            or self.birth.native_runtime_scan_interval_ns
            != attestation.scan_interval_limit_ns
            or self.birth.native_closure_sha256
            != attestation.native_closure_sha256
            or self.birth.native_trust_model != attestation.native_trust_model
            or self.birth.native_containment_claim
            != attestation.native_containment_claim
            or self.birth.operation != attestation.operation
            or self.birth.logical_environment_sha256
            != attestation.logical_environment_sha256
            or self.birth.actual_environment_projection_sha256
            != attestation.actual_environment_projection_sha256
            or self.birth.native_runtime_gate_authority
            != attestation.native_runtime_gate_authority
            or self.birth.native_runtime_gate_initializer_order_limitation
            != attestation.native_runtime_gate_initializer_order_limitation
            or self.birth.native_runtime_gate_source_sha256
            != attestation.native_runtime_gate_source_sha256
            or self.birth.native_runtime_gate_library_sha256
            != attestation.native_runtime_gate_library_sha256
            or self.birth.native_runtime_gate_record_sha256
            != attestation.native_runtime_gate_record_sha256
            or self.birth.runtime_gate_nonce_sha256
            != attestation.runtime_gate_nonce_sha256
            or self.birth.runtime_gate_ack_authority
            != attestation.runtime_gate_ack_authority
            or self.birth.pid != attestation.runtime_gate_ack_pid
            or self.birth.exec_release_e_monotonic_ns
            != attestation.exec_release_e_monotonic_ns
            or (
                attestation.terminal_waitid_code == os.CLD_EXITED
                and (
                    not self.tombstone.exited
                    or self.tombstone.exit_code
                    != attestation.terminal_waitid_status
                )
            )
            or (
                attestation.terminal_waitid_code
                in {os.CLD_KILLED, os.CLD_DUMPED}
                and (
                    not self.tombstone.signaled
                    or self.tombstone.signal_number
                    != attestation.terminal_waitid_status
                )
            )
        ):
            raise ValueError("broker child birth/tombstone custody join differs")
        return self


class SampledProcessIdentity(ContractModel):
    """PID-reuse-safe identity observed by the concurrent peak sampler."""

    role: Literal["parser_worker", "tesseract_broker", "tesseract_child"]
    pid: PositiveInt
    start_abstime: PositiveInt
    parent_pid: PositiveInt
    process_group_id: PositiveInt
    session_id: PositiveInt


class BrokerScratchInventory(ContractModel):
    """Descriptor-bound empty worker scratch observation at one stable edge."""

    schema_id: Literal["parser-broker-scratch-inventory-v1"] = (
        "parser-broker-scratch-inventory-v1"
    )
    root_device: PositiveInt
    root_inode: PositiveInt
    root_mode: Literal[0o700] = 0o700
    root_uid: NonNegativeInt
    entry_count: Literal[0] = 0
    aggregate_bytes: Literal[0] = 0
    empty: Literal[True] = True
    scan_started_monotonic_ns: PositiveInt
    scan_completed_monotonic_ns: PositiveInt
    scan_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_inventory(self) -> "BrokerScratchInventory":
        if self.scan_completed_monotonic_ns < self.scan_started_monotonic_ns:
            raise ValueError("scratch inventory chronology differs")
        if self.scan_sha256 != _canonical_hash(
            {
                "schema_id": "parser-broker-scratch-empty-scan-v1",
                "root_device": self.root_device,
                "root_inode": self.root_inode,
                "entries": [],
            }
        ):
            raise ValueError("scratch empty-scan identity differs")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("scratch inventory record identity differs")
        return self


def broker_scratch_inventory(**fields: object) -> BrokerScratchInventory:
    """Build a canonical empty scratch inventory without caller-supplied hashes."""

    if "scan_sha256" in fields or "record_sha256" in fields:
        raise ValueError("scratch inventory identities are derived")
    scan_sha256 = _canonical_hash(
        {
            "schema_id": "parser-broker-scratch-empty-scan-v1",
            "root_device": fields["root_device"],
            "root_inode": fields["root_inode"],
            "entries": [],
        }
    )
    provisional = BrokerScratchInventory.model_construct(
        **fields,
        scan_sha256=scan_sha256,
        record_sha256="0" * 64,
    )
    return BrokerScratchInventory(
        **fields,
        scan_sha256=scan_sha256,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class BrokerQuiescenceReceipt(ContractModel):
    """Race-closed BEGIN/END state while broker admission is blocked."""

    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    edge: Literal["begin", "end"]
    observed_monotonic_ns: PositiveInt
    worker: ExactProcessIdentity
    broker: ExactProcessIdentity
    ledger_head_sha256: Sha256
    completed_spawn_count: NonNegativeInt
    open_spawn_count: Literal[0] = 0
    wait4_nohang_disposition: Literal["echild"] = "echild"
    ipc_pending_bytes: Literal[0] = 0
    worker_group_member_pids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=2)
    ]
    broker_group_member_pids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=2)
    ]
    broker_thread_count: Literal[1] = 1
    broker_thread_inventory_sha256: Sha256
    broker_thread_observed_at_monotonic_ns: PositiveInt
    request_root_inventory: BrokerScratchInventory
    process_group_scan_complete: Literal[True] = True
    admission_lock_held: Literal[True] = True
    broker_armed_and_blocked: Literal[True] = True
    worker_fork_denial_active: Literal[True] = True

    @model_validator(mode="after")
    def validate_quiescence(self) -> "BrokerQuiescenceReceipt":
        if self.worker.role != "parser_worker" or self.broker.role != (
            "tesseract_broker"
        ):
            raise ValueError("broker quiescence process roles differ")
        if self.worker.process_group_id == self.broker.process_group_id:
            raise ValueError("worker and broker require separate process groups")
        if self.worker_group_member_pids != (self.worker.pid,):
            raise ValueError("worker group is not root-only at quiescence")
        if self.broker_group_member_pids != (self.broker.pid,):
            raise ValueError("broker group is not root-only at quiescence")
        if self.broker_thread_observed_at_monotonic_ns > self.observed_monotonic_ns:
            raise ValueError("broker thread inventory follows quiescence")
        inventory = self.request_root_inventory
        if inventory.scan_completed_monotonic_ns > self.observed_monotonic_ns:
            raise ValueError("scratch inventory follows quiescence observation")
        return self


class BrokerRequestBindingEvidence(ContractModel):
    """Actual ASGI request identity matched to the one-shot ARM record."""

    schema_id: Literal["parser-broker-request-binding-v2"] = (
        "parser-broker-request-binding-v2"
    )
    method: Literal["POST"] = "POST"
    path: Literal["/v1/parse"] = "/v1/parse"
    query_sha256: Sha256
    output_format: Literal["json", "markdown"]
    source_sha256: Sha256
    source_bytes: PositiveInt
    safe_filename_sha256: Sha256
    upload_content_type_sha256: Sha256
    binding_record_sha256: Sha256
    actual_request_matched: Literal[True] = True
    matched_at_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_binding(self) -> "BrokerRequestBindingEvidence":
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("request-binding evidence identity differs")
        return self


def broker_request_binding_evidence(
    **fields: object,
) -> BrokerRequestBindingEvidence:
    if "record_sha256" in fields:
        raise ValueError("request-binding record identity is derived")
    provisional = BrokerRequestBindingEvidence.model_construct(
        **fields, record_sha256="0" * 64
    )
    dumped = provisional.model_dump(mode="json", exclude={"record_sha256"})
    return BrokerRequestBindingEvidence(
        **fields,
        record_sha256=_canonical_hash(dumped),  # type: ignore[arg-type]
    )


class AsgiResponseHeader(ContractModel):
    name_hex: Annotated[str, Field(min_length=2, max_length=16_384)]
    value_hex: Annotated[str, Field(max_length=131_072)]

    @model_validator(mode="after")
    def validate_header(self) -> "AsgiResponseHeader":
        try:
            name = bytes.fromhex(self.name_hex)
            bytes.fromhex(self.value_hex)
        except ValueError as error:
            raise ValueError("ASGI response header encoding differs") from error
        if not name or name != name.lower() or b"\x00" in name:
            raise ValueError("ASGI response header name differs")
        return self


class AsgiResponseWitness(ContractModel):
    schema_id: Literal["parser-asgi-response-witness-v1"] = (
        "parser-asgi-response-witness-v1"
    )
    status_code: Literal[200] = 200
    response_start_message_keys: tuple[
        Literal["headers"], Literal["status"], Literal["type"]
    ] = (
        "headers",
        "status",
        "type",
    )
    ordered_headers: Annotated[
        tuple[AsgiResponseHeader, ...], Field(max_length=512)
    ]
    headers_sha256: Sha256
    response_start_send_completed_monotonic_ns: PositiveInt
    response_body_message_keys: (
        tuple[Literal["body"], Literal["type"]]
        | tuple[Literal["body"], Literal["more_body"], Literal["type"]]
    )
    body_sha256: Sha256
    body_bytes: Annotated[int, Field(strict=True, gt=0, le=MAXIMUM_OUTPUT_BYTES)]
    response_body_send_completed_monotonic_ns: PositiveInt
    inner_asgi_returned_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_witness(self) -> "AsgiResponseWitness":
        headers = [item.model_dump(mode="json") for item in self.ordered_headers]
        if (
            self.headers_sha256
            != _canonical_hash({"ordered_headers": headers})
            or not (
                self.response_start_send_completed_monotonic_ns
                <= self.response_body_send_completed_monotonic_ns
                <= self.inner_asgi_returned_monotonic_ns
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("ASGI response witness differs")
        return self


def asgi_response_witness(**fields: object) -> AsgiResponseWitness:
    if "headers_sha256" in fields or "record_sha256" in fields:
        raise ValueError("ASGI response witness identities are derived")
    raw_headers = fields.get("ordered_headers")
    if not isinstance(raw_headers, (tuple, list)):
        raise ValueError("ASGI response headers differ")
    headers = [
        item.model_dump(mode="json")
        if isinstance(item, AsgiResponseHeader)
        else dict(item)  # type: ignore[arg-type]
        for item in raw_headers
    ]
    complete = {
        **fields,
        "headers_sha256": _canonical_hash({"ordered_headers": headers}),
    }
    provisional = AsgiResponseWitness.model_construct(
        **complete,
        record_sha256="0" * 64,
    )
    return AsgiResponseWitness(
        **complete,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


_BROKER_LIFECYCLE_RECEIPT_FIELDS = frozenset(
    {
        "schema_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "request_id",
        "request_epoch",
        "request_sequence",
        "worker_thread_id",
        "arm_capability_sha256",
        "arm_issued_at_monotonic_ns",
        "arm_consumed_at_monotonic_ns",
        "arm_terminal_disposition",
        "thread_transfer_required",
        "logical_phase",
        "terminal_kind",
        "phase_deadline_monotonic_ns",
        "binding_sha256",
        "request_binding",
        "thread_claim_count",
        "failure_reason_sha256",
        "native_closure_sha256",
        "native_closure",
        "guard_python",
        "guard_python_path_custody",
        "guard_python_native_closure",
        "guard_python_module_tree_custody",
        "guard_wrapper_source_hex",
        "guard_wrapper_source_sha256",
        "guard_wrapper_delivery_basis",
        "begin",
        "thread_transfers",
        "births",
        "tombstones",
        "end",
        "previous_receipt_sha256",
        "receipt_sha256",
    }
)


def _lifecycle_quiescence_matches(
    raw: object,
    retained: BrokerQuiescenceReceipt,
    *,
    phase: Literal["begin", "end"],
) -> bool:
    if not isinstance(raw, dict):
        return False
    worker = raw.get("worker_identity")
    broker = raw.get("broker_identity")
    worker_members = raw.get("worker_group_members")
    broker_members = raw.get("broker_group_members")
    return bool(
        raw.get("request_id") == retained.request_id
        and raw.get("request_epoch") == retained.request_epoch
        and raw.get("request_sequence") == retained.request_sequence
        and raw.get("phase") == phase
        and raw.get("active_job_count") == 0
        and raw.get("protocol_pending_bytes") == 0
        and raw.get("ledger_head_sha256") == retained.ledger_head_sha256
        and raw.get("completed_spawn_count") == retained.completed_spawn_count
        and raw.get("wait4_echild") is True
        and raw.get("recursive_descendants") == []
        and isinstance(worker, dict)
        and (
            worker.get("pid"),
            worker.get("start_abstime"),
            worker.get("ppid"),
            worker.get("pgid"),
            worker.get("sid"),
        )
        == (
            retained.worker.pid,
            retained.worker.start_abstime,
            retained.worker.parent_pid,
            retained.worker.process_group_id,
            retained.worker.session_id,
        )
        and isinstance(broker, dict)
        and (
            broker.get("pid"),
            broker.get("start_abstime"),
            broker.get("ppid"),
            broker.get("pgid"),
            broker.get("sid"),
        )
        == (
            retained.broker.pid,
            retained.broker.start_abstime,
            retained.broker.parent_pid,
            retained.broker.process_group_id,
            retained.broker.session_id,
        )
        and isinstance(worker_members, list)
        and all(isinstance(item, dict) for item in worker_members)
        and tuple(item.get("pid") for item in worker_members)
        == retained.worker_group_member_pids
        and isinstance(broker_members, list)
        and all(isinstance(item, dict) for item in broker_members)
        and tuple(item.get("pid") for item in broker_members)
        == retained.broker_group_member_pids
        and raw.get("broker_thread_count") == retained.broker_thread_count
        and raw.get("broker_thread_inventory_sha256")
        == retained.broker_thread_inventory_sha256
        and raw.get("broker_thread_observed_at_monotonic_ns")
        == retained.broker_thread_observed_at_monotonic_ns
        and raw.get("request_root_inventory")
        == retained.request_root_inventory.model_dump(mode="json")
        and raw.get("process_group_scan_complete") is True
        and raw.get("admission_lock_held") is True
        and raw.get("broker_armed_and_blocked") is True
        and raw.get("worker_fork_denial_active") is True
    )


class BrokerLifecycleReceiptEvidence(ContractModel):
    """Canonical startup/shutdown receipt with every child lineage retained."""

    schema_id: Literal["phase-latency-broker-lifecycle-receipt-v1"] = (
        "phase-latency-broker-lifecycle-receipt-v1"
    )
    logical_phase: Literal["startup", "shutdown"]
    canonical_receipt_json: Annotated[
        str, Field(min_length=1, max_length=16_777_216)
    ]
    canonical_receipt_sha256: Sha256
    receipt_sha256: Sha256
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    phase_deadline_monotonic_ns: PositiveInt
    arm_issued_at_monotonic_ns: PositiveInt
    arm_consumed_at_monotonic_ns: PositiveInt
    native_closure_sha256: Sha256
    native_closure: dict[str, object]
    guard_python: dict[str, object]
    guard_python_path_custody: dict[str, object]
    guard_python_native_closure: dict[str, object]
    guard_python_module_tree_custody: dict[str, object]
    guard_wrapper_source_hex: Annotated[
        str, Field(min_length=2, max_length=1_048_576)
    ]
    guard_wrapper_source_sha256: Sha256
    guard_wrapper_delivery_basis: Literal[
        "execve-python-c-embedded-source-v1"
    ] = "execve-python-c-embedded-source-v1"
    previous_receipt_sha256: Sha256
    begin: BrokerQuiescenceReceipt
    end: BrokerQuiescenceReceipt
    children: Annotated[
        tuple[BrokerChildCpuReceipt, ...], Field(max_length=4096)
    ] = ()
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_lifecycle_receipt(self) -> "BrokerLifecycleReceiptEvidence":
        try:
            encoded = self.canonical_receipt_json.encode("utf-8", errors="strict")
            raw = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("lifecycle receipt is not canonical JSON") from error
        empty_failure_sha256 = hashlib.sha256(b"").hexdigest()
        births = [item.birth.model_dump(mode="json") for item in self.children]
        tombstones = [
            item.tombstone.model_dump(mode="json") for item in self.children
        ]
        from app.services.tesseract_broker_protocol import (
            request_receipt_from_mapping,
        )

        try:
            request_receipt_from_mapping(raw)
        except Exception as error:
            raise ValueError(
                "lifecycle receipt native authority differs"
            ) from error
        if (
            not isinstance(raw, dict)
            or set(raw) != _BROKER_LIFECYCLE_RECEIPT_FIELDS
            or encoded != _semantic_json_bytes(raw)
            or self.canonical_receipt_sha256
            != hashlib.sha256(encoded).hexdigest()
            or raw.get("schema_id") != "parser-tesseract-broker-v1"
            or raw.get("logical_phase") != self.logical_phase
            or raw.get("terminal_kind") != "end"
            or raw.get("arm_terminal_disposition") != "ended"
            or raw.get("thread_transfer_required") is not False
            or raw.get("request_binding") is not None
            or raw.get("thread_claim_count") != 0
            or raw.get("thread_transfers") != []
            or raw.get("failure_reason_sha256") != empty_failure_sha256
            or raw.get("attempt_nonce_sha256") != self.attempt_nonce_sha256
            or raw.get("scope_sha256") != self.scope_sha256
            or raw.get("request_id") != self.request_id
            or raw.get("request_epoch") != self.request_epoch
            or raw.get("request_sequence") != self.request_sequence
            or raw.get("phase_deadline_monotonic_ns")
            != self.phase_deadline_monotonic_ns
            or raw.get("arm_issued_at_monotonic_ns")
            != self.arm_issued_at_monotonic_ns
            or raw.get("arm_consumed_at_monotonic_ns")
            != self.arm_consumed_at_monotonic_ns
            or self.arm_issued_at_monotonic_ns
            > self.arm_consumed_at_monotonic_ns
            or raw.get("native_closure_sha256")
            != self.native_closure_sha256
            or raw.get("native_closure") != self.native_closure
            or self.native_closure.get("closure_sha256")
            != self.native_closure_sha256
            or raw.get("guard_python") != self.guard_python
            or raw.get("guard_python_path_custody")
            != self.guard_python_path_custody
            or raw.get("guard_python_native_closure")
            != self.guard_python_native_closure
            or raw.get("guard_python_module_tree_custody")
            != self.guard_python_module_tree_custody
            or raw.get("guard_wrapper_source_hex")
            != self.guard_wrapper_source_hex
            or raw.get("guard_wrapper_source_sha256")
            != self.guard_wrapper_source_sha256
            or hashlib.sha256(
                bytes.fromhex(self.guard_wrapper_source_hex)
            ).hexdigest()
            != self.guard_wrapper_source_sha256
            or raw.get("guard_wrapper_delivery_basis")
            != self.guard_wrapper_delivery_basis
            or raw.get("previous_receipt_sha256")
            != self.previous_receipt_sha256
            or raw.get("receipt_sha256") != self.receipt_sha256
            or self.receipt_sha256
            != hashlib.sha256(
                _semantic_json_bytes(
                    {key: item for key, item in raw.items() if key != "receipt_sha256"}
                )
            ).hexdigest()
            or raw.get("births") != births
            or raw.get("tombstones") != tombstones
            or not _lifecycle_quiescence_matches(
                raw.get("begin"), self.begin, phase="begin"
            )
            or not _lifecycle_quiescence_matches(
                raw.get("end"), self.end, phase="end"
            )
            or any(
                child.birth.request_id != self.request_id
                or child.birth.request_epoch != self.request_epoch
                or child.birth.request_sequence != self.request_sequence
                or child.tombstone.request_id != self.request_id
                or child.tombstone.request_epoch != self.request_epoch
                or child.tombstone.request_sequence != self.request_sequence
                for child in self.children
            )
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("broker lifecycle receipt evidence differs")
        return self


def broker_lifecycle_receipt_evidence(
    **fields: object,
) -> BrokerLifecycleReceiptEvidence:
    if "record_sha256" in fields:
        raise ValueError("broker lifecycle receipt identity is derived")
    provisional = BrokerLifecycleReceiptEvidence.model_construct(
        **fields, record_sha256="0" * 64
    )
    return BrokerLifecycleReceiptEvidence(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


class ExactBrokerRequestCpuEvidence(ContractModel):
    """One-owner request CPU proof for the fork-denied worker architecture."""

    attempt_id: StableId
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    request_deadline_monotonic_ns: PositiveInt
    arm_capability_sha256: Sha256
    arm_issued_at_monotonic_ns: PositiveInt
    arm_consumed_at_monotonic_ns: PositiveInt
    binding_sha256: Sha256
    request_binding: BrokerRequestBindingEvidence
    asgi_response_witness: AsgiResponseWitness
    asgi_response_witness_sha256: Sha256
    thread_claim_count: Literal[1] = 1
    thread_transfer_record_sha256s: tuple[Sha256, Sha256]
    begin: BrokerQuiescenceReceipt
    end: BrokerQuiescenceReceipt
    worker_before: NativeSelfCpuCounter
    worker_after: NativeSelfCpuCounter
    broker_before: NativeSelfCpuCounter
    broker_after: NativeSelfCpuCounter
    begin_post_sample_scratch_inventory: BrokerScratchInventory
    end_post_sample_scratch_inventory: BrokerScratchInventory
    begin_external_sample: ExternalCpuStableEdgeRecord
    end_external_sample: ExternalCpuStableEdgeRecord
    begin_external_sample_row_sha256: Sha256
    end_external_sample_row_sha256: Sha256
    request_control_arm_record_sha256: Sha256
    request_control_begin_blocked_record_sha256: Sha256
    request_control_begin_release_record_sha256: Sha256
    request_control_end_blocked_record_sha256: Sha256
    request_control_receipt_release_record_sha256: Sha256
    request_control_result_record_sha256: Sha256
    request_control_result_ack_record_sha256: Sha256
    request_control_transcript_row_sha256s: tuple[
        Sha256, Sha256, Sha256, Sha256, Sha256, Sha256, Sha256
    ]
    begin_release_monotonic_ns: PositiveInt
    receipt_release_monotonic_ns: PositiveInt
    broker_request_receipt_sha256: Sha256
    pre_exec_gated_child_samples: Annotated[
        tuple[ControllerPreExecGatedChildSample, ...], Field(max_length=4_096)
    ] = ()
    children: Annotated[
        tuple[BrokerChildCpuReceipt, ...], Field(max_length=4_096)
    ] = ()
    worker_user_cpu_delta_ns: NonNegativeInt
    worker_system_cpu_delta_ns: NonNegativeInt
    broker_user_cpu_delta_ns: NonNegativeInt
    broker_system_cpu_delta_ns: NonNegativeInt
    tesseract_user_cpu_delta_ns: NonNegativeInt
    tesseract_system_cpu_delta_ns: NonNegativeInt
    total_cpu_delta_ns: NonNegativeInt
    sampled_process_identities: Annotated[
        tuple[SampledProcessIdentity, ...], Field(min_length=2, max_length=4_098)
    ]
    unmatched_sampled_process_identities: tuple[SampledProcessIdentity, ...] = ()
    begin_sample_order: Literal["broker-then-worker-stable-edge-v1"] = (
        "broker-then-worker-stable-edge-v1"
    )
    end_sample_order: Literal["broker-then-worker-stable-edge-v1"] = (
        "broker-then-worker-stable-edge-v1"
    )
    asgi_request_claimed_once: Literal[True] = True
    full_inner_asgi_returned_before_end: Literal[True] = True
    request_task_blocked_during_end_samples: Literal[True] = True
    receipt_release_outside_cpu_boundary: Literal[True] = True
    accounting_basis: Literal[
        "fork-denied-worker-broker-self-plus-exact-wait4-v2"
    ] = "fork-denied-worker-broker-self-plus-exact-wait4-v2"
    post_ack_samples_complete: Literal[True] = True
    legacy_rusage_children_used: Literal[False] = False
    float_or_rounded_counter_used: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_cpu(self) -> "ExactBrokerRequestCpuEvidence":
        if self.request_epoch != self.request_sequence + 1:
            raise ValueError("broker request epoch does not follow startup")
        if (
            self.binding_sha256
            != self.request_binding.binding_record_sha256
            or self.asgi_response_witness_sha256
            != self.asgi_response_witness.record_sha256
            or not (
                self.arm_issued_at_monotonic_ns
                <= self.arm_consumed_at_monotonic_ns
                <= self.begin.observed_monotonic_ns
                <= self.request_binding.matched_at_monotonic_ns
                <= self.end.observed_monotonic_ns
            )
            or not (
                self.begin_release_monotonic_ns
                <= self.asgi_response_witness.response_start_send_completed_monotonic_ns
                <= self.asgi_response_witness.response_body_send_completed_monotonic_ns
                <= self.asgi_response_witness.inner_asgi_returned_monotonic_ns
                <= self.end.observed_monotonic_ns
            )
            or len(set(self.thread_transfer_record_sha256s)) != 2
        ):
            raise ValueError("broker ARM/request binding custody differs")
        external_common = (
            self.attempt_id,
            self.attempt_nonce_sha256,
            self.scope_sha256,
            self.request_id,
            self.request_epoch,
            self.request_sequence,
            self.request_deadline_monotonic_ns,
        )
        if (
            self.begin_external_sample.edge != "begin"
            or self.end_external_sample.edge != "end"
            or any(
                (
                    item.attempt_id,
                    item.attempt_nonce_sha256,
                    item.scope_sha256,
                    item.request_id,
                    item.request_epoch,
                    item.request_sequence,
                    item.request_deadline_monotonic_ns,
                )
                != external_common
                for item in (
                    self.begin_external_sample,
                    self.end_external_sample,
                )
            )
            or self.begin_external_sample.broker_sample.cpu != self.broker_before
            or self.begin_external_sample.worker_sample.cpu != self.worker_before
            or self.end_external_sample.broker_sample.cpu != self.broker_after
            or self.end_external_sample.worker_sample.cpu != self.worker_after
            or self.begin_external_sample.post_sample_scratch_inventory
            != self.begin_post_sample_scratch_inventory
            or self.end_external_sample.post_sample_scratch_inventory
            != self.end_post_sample_scratch_inventory
        ):
            raise ValueError("external CPU sample projection differs")
        if any(
            before != after
            for before, after in (
                (
                    self.begin_external_sample.worker_sample.native_thread_ids,
                    self.end_external_sample.worker_sample.native_thread_ids,
                ),
                (
                    self.begin_external_sample.worker_sample.file_descriptor_inventory.inventory_sha256,
                    self.end_external_sample.worker_sample.file_descriptor_inventory.inventory_sha256,
                ),
                (
                    self.begin_external_sample.broker_sample.native_thread_ids,
                    self.end_external_sample.broker_sample.native_thread_ids,
                ),
                (
                    self.begin_external_sample.broker_sample.file_descriptor_inventory.inventory_sha256,
                    self.end_external_sample.broker_sample.file_descriptor_inventory.inventory_sha256,
                ),
            )
        ):
            raise ValueError(
                "request root thread/FD baseline drifted: exact identities differ"
            )
        frame_sha256s = (
            self.request_control_arm_record_sha256,
            self.request_control_begin_blocked_record_sha256,
            self.request_control_begin_release_record_sha256,
            self.request_control_end_blocked_record_sha256,
            self.request_control_receipt_release_record_sha256,
            self.request_control_result_record_sha256,
            self.request_control_result_ack_record_sha256,
        )
        if (
            len(set(frame_sha256s)) != len(frame_sha256s)
            or len(set(self.request_control_transcript_row_sha256s))
            != len(self.request_control_transcript_row_sha256s)
            or self.begin_external_sample_row_sha256
            == self.end_external_sample_row_sha256
        ):
            raise ValueError("request-control durable record custody differs")
        for edge in (self.begin, self.end):
            if (
                edge.request_id != self.request_id
                or edge.attempt_nonce_sha256 != self.attempt_nonce_sha256
                or edge.scope_sha256 != self.scope_sha256
                or edge.request_epoch != self.request_epoch
                or edge.request_sequence != self.request_sequence
            ):
                raise ValueError("broker quiescence request binding differs")
        if self.begin.edge != "begin" or self.end.edge != "end":
            raise ValueError("broker quiescence edges differ")
        if self.begin.worker != self.end.worker or self.begin.broker != self.end.broker:
            raise ValueError("broker request process identity changed")
        counters = (
            (self.worker_before, self.worker_after, self.begin.worker, "parser_worker"),
            (
                self.broker_before,
                self.broker_after,
                self.begin.broker,
                "tesseract_broker",
            ),
        )
        for before, after, identity, role in counters:
            if before.identity != identity or after.identity != identity:
                raise ValueError("exact CPU counter process identity differs")
            if before.identity.role != role:
                raise ValueError("exact CPU counter role differs")
            if before.observed_monotonic_ns < self.begin.observed_monotonic_ns:
                raise ValueError("exact CPU begin sample predates broker ACK")
            if after.observed_monotonic_ns < self.end.observed_monotonic_ns:
                raise ValueError("exact CPU end sample predates broker ACK")
            if (
                after.user_cpu_ns < before.user_cpu_ns
                or after.system_cpu_ns < before.system_cpu_ns
            ):
                raise ValueError("exact CPU counter regressed")
        expected_deltas = (
            self.worker_after.user_cpu_ns - self.worker_before.user_cpu_ns,
            self.worker_after.system_cpu_ns - self.worker_before.system_cpu_ns,
            self.broker_after.user_cpu_ns - self.broker_before.user_cpu_ns,
            self.broker_after.system_cpu_ns - self.broker_before.system_cpu_ns,
            sum(item.tombstone.user_cpu_ns for item in self.children),
            sum(item.tombstone.system_cpu_ns for item in self.children),
        )
        retained_deltas = (
            self.worker_user_cpu_delta_ns,
            self.worker_system_cpu_delta_ns,
            self.broker_user_cpu_delta_ns,
            self.broker_system_cpu_delta_ns,
            self.tesseract_user_cpu_delta_ns,
            self.tesseract_system_cpu_delta_ns,
        )
        if retained_deltas != expected_deltas:
            raise ValueError("exact broker CPU deltas must be recomputed")
        if self.total_cpu_delta_ns != sum(expected_deltas):
            raise ValueError("exact broker CPU total must be recomputed")
        before_samples_complete = max(
            self.worker_before.observed_monotonic_ns,
            self.broker_before.observed_monotonic_ns,
        )
        after_samples_complete = max(
            self.worker_after.observed_monotonic_ns,
            self.broker_after.observed_monotonic_ns,
        )
        if self.begin_release_monotonic_ns < before_samples_complete:
            raise ValueError("broker BEGIN was released before CPU samples")
        if self.receipt_release_monotonic_ns <= after_samples_complete:
            raise ValueError("broker receipt was released before CPU samples")
        if not (
            self.begin.observed_monotonic_ns
            <= self.broker_before.observed_monotonic_ns
            <= self.worker_before.observed_monotonic_ns
            <= self.begin_release_monotonic_ns
            <= self.end.observed_monotonic_ns
            <= self.broker_after.observed_monotonic_ns
            <= self.worker_after.observed_monotonic_ns
            < self.receipt_release_monotonic_ns
        ):
            raise ValueError("broker stable-edge sample chronology differs")
        inventories = (
            self.begin.request_root_inventory,
            self.begin_post_sample_scratch_inventory,
            self.end.request_root_inventory,
            self.end_post_sample_scratch_inventory,
        )
        root_identities = {
            (
                item.root_device,
                item.root_inode,
                item.root_mode,
                item.root_uid,
            )
            for item in inventories
        }
        if len(root_identities) != 1:
            raise ValueError("worker scratch-root identity changed")
        if not (
            self.worker_before.observed_monotonic_ns
            <= self.begin_post_sample_scratch_inventory.scan_started_monotonic_ns
            <= self.begin_post_sample_scratch_inventory.scan_completed_monotonic_ns
            <= self.begin_release_monotonic_ns
            and self.worker_after.observed_monotonic_ns
            <= self.end_post_sample_scratch_inventory.scan_started_monotonic_ns
            <= self.end_post_sample_scratch_inventory.scan_completed_monotonic_ns
            < self.receipt_release_monotonic_ns
        ):
            raise ValueError("controller scratch scan escaped a stable CPU edge")
        child_keys = tuple(
            (
                item.birth.spawn_sequence,
                item.birth.spawn_nonce_sha256,
                item.birth.pid,
            )
            for item in self.children
        )
        if child_keys != tuple(sorted(child_keys)) or len(child_keys) != len(
            set(child_keys)
        ):
            raise ValueError("broker child CPU receipts must be canonical and unique")
        gated_sample_keys = tuple(
            (item.pid, item.start_abstime)
            for item in self.pre_exec_gated_child_samples
        )
        birth_identity_keys = tuple(
            (item.birth.pid, item.birth.start_abstime) for item in self.children
        )
        if (
            gated_sample_keys != tuple(sorted(set(gated_sample_keys)))
            or gated_sample_keys != tuple(sorted(birth_identity_keys))
        ):
            raise ValueError("pre-exec gated sample/birth identity set differs")
        birth_by_identity = {
            (item.birth.pid, item.birth.start_abstime): item.birth
            for item in self.children
        }
        for sample in self.pre_exec_gated_child_samples:
            birth = birth_by_identity[(sample.pid, sample.start_abstime)]
            if (
                (sample.ppid, sample.pgid, sample.sid)
                != (birth.ppid, birth.pgid, birth.sid)
                or sample.native_thread_ids != birth.native_thread_ids
                or sample.open_fd_inventory_sha256
                != birth.open_fd_inventory_sha256
                or sample.native_thread_inventory_sha256
                != birth.native_thread_inventory_sha256
                or sample.child_ready_sha256 != birth.child_ready_sha256
                or not (
                    birth.guard_release_a_monotonic_ns
                    <= sample.observed_monotonic_ns
                    <= birth.exec_release_e_monotonic_ns
                )
            ):
                raise ValueError("pre-exec gated child sample lineage differs")
        if any(
            item.birth.request_id != self.request_id
            or item.birth.request_epoch != self.request_epoch
            or item.birth.request_sequence != self.request_sequence
            for item in self.children
        ):
            raise ValueError("broker child CPU receipt crossed a request")
        for item in self.children:
            if (
                item.birth.ppid != self.begin.broker.pid
                or item.birth.pgid
                != self.begin.broker.process_group_id
                or item.birth.sid != self.begin.broker.session_id
            ):
                raise ValueError("broker child lineage differs from frozen broker")
            if item.birth.born_monotonic_ns < max(
                before_samples_complete,
                self.begin_release_monotonic_ns,
            ):
                raise ValueError("broker child birth predates BEGIN CPU samples")
            if item.tombstone.observed_monotonic_ns > self.end.observed_monotonic_ns:
                raise ValueError("broker child tombstone follows END quiescence")
        if self.end.completed_spawn_count != (
            self.begin.completed_spawn_count + len(self.children)
        ):
            raise ValueError("broker completed-spawn count must be recomputed")
        sampled_keys = tuple(
            (item.pid, item.start_abstime)
            for item in self.sampled_process_identities
        )
        if sampled_keys != tuple(sorted(set(sampled_keys))):
            raise ValueError("sampled process identities must be canonical and unique")
        worker_samples = tuple(
            item
            for item in self.sampled_process_identities
            if item.role == "parser_worker"
        )
        broker_samples = tuple(
            item
            for item in self.sampled_process_identities
            if item.role == "tesseract_broker"
        )
        if (
            len(worker_samples) != 1
            or len(broker_samples) != 1
            or (
                worker_samples[0].pid,
                worker_samples[0].start_abstime,
                worker_samples[0].parent_pid,
                worker_samples[0].process_group_id,
                worker_samples[0].session_id,
            )
            != (
                self.begin.worker.pid,
                self.begin.worker.start_abstime,
                self.begin.worker.parent_pid,
                self.begin.worker.process_group_id,
                self.begin.worker.session_id,
            )
            or (
                broker_samples[0].pid,
                broker_samples[0].start_abstime,
                broker_samples[0].parent_pid,
                broker_samples[0].process_group_id,
                broker_samples[0].session_id,
            )
            != (
                self.begin.broker.pid,
                self.begin.broker.start_abstime,
                self.begin.broker.parent_pid,
                self.begin.broker.process_group_id,
                self.begin.broker.session_id,
            )
        ):
            raise ValueError("worker and broker were not both sampled")
        child_by_identity = {
            (item.birth.pid, item.birth.start_abstime): item.birth
            for item in self.children
        }
        for sampled in self.sampled_process_identities:
            if sampled.role != "tesseract_child":
                continue
            birth = child_by_identity.get((sampled.pid, sampled.start_abstime))
            if birth is None or (
                sampled.parent_pid,
                sampled.process_group_id,
                sampled.session_id,
            ) != (
                birth.ppid,
                birth.pgid,
                birth.sid,
            ):
                raise ValueError("sampled process lacks broker lineage custody")
        sampled_child_identity_keys = {
            (item.pid, item.start_abstime)
            for item in self.sampled_process_identities
            if item.role == "tesseract_child"
        }
        if sampled_child_identity_keys != set(birth_identity_keys):
            raise ValueError("sampled process set omits a broker birth")
        if self.unmatched_sampled_process_identities:
            raise ValueError("sampled process lacks broker lineage custody")
        return self


class RequestControlReceiptBlobDescriptor(ContractModel):
    """Typed custody of one separately retained canonical broker receipt."""

    schema_id: Literal["phase-latency-request-control-receipt-blob-v1"] = (
        "phase-latency-request-control-receipt-blob-v1"
    )
    attempt_id: StableId
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    manifest_record_sha256: Sha256
    receipt_sha256: Sha256
    receipt_blob_sha256: Sha256
    receipt_blob_bytes: Annotated[int, Field(strict=True, gt=0, le=536_870_912)]
    chunk_count: Annotated[int, Field(strict=True, gt=0, le=512)]
    terminal_chunk_commitment_sha256: Sha256
    chunk_frame_sha256s: Annotated[tuple[Sha256, ...], Field(max_length=512)]
    chunk_transcript_row_sha256s: Annotated[
        tuple[Sha256, ...], Field(max_length=512)
    ]
    file_device: NonNegativeInt
    file_inode: PositiveInt
    file_mode: Literal[0o600] = 0o600
    file_uid: NonNegativeInt
    file_nlink: Literal[1] = 1
    o_excl_created: Literal[True] = True
    fsynced_before_close: Literal[True] = True
    reopened_no_follow_after_fsync: Literal[True] = True
    retained_transcript_row_sha256: Sha256
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_receipt_blob(self) -> "RequestControlReceiptBlobDescriptor":
        expected_chunks = (self.receipt_blob_bytes + 1_048_575) // 1_048_576
        if (
            self.request_epoch != self.request_sequence + 1
            or self.request_id
            != f"{self.attempt_id}-q{self.request_sequence:04d}"
            or self.relative_path
            != (
                f"{self.attempt_id}-request-{self.request_sequence:04d}"
                "-broker-receipt.json"
            )
            or Path(self.relative_path).name != self.relative_path
            or self.chunk_count != expected_chunks
            or len(self.chunk_frame_sha256s) != self.chunk_count
            or len(self.chunk_transcript_row_sha256s) != self.chunk_count
            or len(set(self.chunk_frame_sha256s)) != self.chunk_count
            or len(set(self.chunk_transcript_row_sha256s)) != self.chunk_count
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(
                    mode="json",
                    exclude={
                        "record_sha256",
                        "retained_transcript_row_sha256",
                    },
                )
            )
        ):
            raise ValueError("request-control receipt blob custody differs")
        return self


_REQUEST_CONTROL_DIRECTION_BY_KIND = {
    "request_control_ready": "worker_to_controller",
    "request_control_arm": "controller_to_worker",
    "request_control_begin_blocked": "worker_to_controller",
    "request_control_begin_release": "controller_to_worker",
    "request_control_end_blocked": "worker_to_controller",
    "request_control_receipt_chunk": "worker_to_controller",
    "request_control_receipt_release": "controller_to_worker",
    "request_control_result": "worker_to_controller",
    "request_control_result_ack": "controller_to_worker",
    "request_control_close": "worker_to_controller",
    "request_control_close_ack": "controller_to_worker",
}
_REQUEST_CONTROL_SCHEMA_BY_KIND = {
    "request_control_ready": "parser-request-control-ready-v1",
    "request_control_arm": "parser-request-control-arm-v1",
    "request_control_begin_blocked": (
        "parser-request-control-begin-blocked-v1"
    ),
    "request_control_begin_release": (
        "parser-request-control-begin-release-v1"
    ),
    "request_control_end_blocked": "parser-request-control-end-blocked-v1",
    "request_control_receipt_release": (
        "parser-request-control-receipt-release-v1"
    ),
    "request_control_result": "parser-request-control-result-v1",
    "request_control_result_ack": "parser-request-control-result-ack-v1",
    "request_control_close": "parser-request-control-close-v1",
    "request_control_close_ack": "parser-request-control-close-ack-v1",
}
_REQUEST_CONTROL_COMMON_KEYS = {
    "attempt_id",
    "attempt_nonce_sha256",
    "scope_sha256",
    "request_id",
    "request_epoch",
    "request_sequence",
    "worker",
    "broker",
    "request_deadline_monotonic_ns",
    "previous_record_sha256",
}
_REQUEST_CONTROL_PAYLOAD_KEYS = {
    "request_control_ready": {
        "schema_id",
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "worker",
        "broker",
        "expected_request_count",
        "framework_thread_baseline",
        "ready_at_monotonic_ns",
        "previous_record_sha256",
        "record_sha256",
    },
    "request_control_arm": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "binding",
        "binding_sha256",
        "arm_issued_at_monotonic_ns",
        "record_sha256",
    },
    "request_control_begin_blocked": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "arm_record_sha256",
        "arm_capability_sha256",
        "arm_consumed_at_monotonic_ns",
        "begin_barrier",
        "record_sha256",
    },
    "request_control_begin_release": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "begin_blocked_record_sha256",
        "begin_sample_record_sha256",
        "begin_samples_completed_monotonic_ns",
        "begin_release_monotonic_ns",
        "record_sha256",
    },
    "request_control_end_blocked": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "begin_release_record_sha256",
        "end_barrier",
        "broker_request_receipt_manifest",
        "broker_request_receipt_sha256",
        "request_binding_record_sha256",
        "thread_transfer_record_sha256s",
        "asgi_response_witness",
        "asgi_response_witness_sha256",
        "full_inner_asgi_returned",
        "request_task_blocked",
        "record_sha256",
    },
    "request_control_receipt_release": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "end_blocked_record_sha256",
        "end_sample_record_sha256",
        "end_samples_completed_monotonic_ns",
        "broker_request_receipt_sha256",
        "receipt_release_monotonic_ns",
        "record_sha256",
    },
    "request_control_result": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "receipt_release_record_sha256",
        "worker_result",
        "record_sha256",
    },
    "request_control_result_ack": {
        "schema_id",
        *_REQUEST_CONTROL_COMMON_KEYS,
        "result_record_sha256",
        "retained_at_monotonic_ns",
        "record_sha256",
    },
    "request_control_close": {
        "schema_id",
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "worker",
        "broker",
        "completed_request_count",
        "last_request_sequence",
        "previous_record_sha256",
        "record_sha256",
    },
    "request_control_close_ack": {
        "schema_id",
        "attempt_id",
        "attempt_nonce_sha256",
        "scope_sha256",
        "worker",
        "broker",
        "completed_request_count",
        "close_record_sha256",
        "closed_at_monotonic_ns",
        "previous_record_sha256",
        "record_sha256",
    },
}
_REQUEST_CONTROL_LEGACY_INLINE_END_KEYS = {
    *(_REQUEST_CONTROL_PAYLOAD_KEYS["request_control_end_blocked"]),
}
_REQUEST_CONTROL_LEGACY_INLINE_END_KEYS.remove(
    "broker_request_receipt_manifest"
)
_REQUEST_CONTROL_LEGACY_INLINE_END_KEYS.add("broker_request_receipt")
_REQUEST_CONTROL_REQUEST_KINDS = (
    "request_control_arm",
    "request_control_begin_blocked",
    "request_control_begin_release",
    "request_control_end_blocked",
    "request_control_receipt_release",
    "request_control_result",
    "request_control_result_ack",
)


def _request_control_frame_sha256(
    *,
    sequence: int,
    previous_sha256: str,
    kind: str,
    payload: Mapping[str, object],
    body_bytes: int = 0,
    body_sha256: str | None = None,
) -> str:
    if body_sha256 is None:
        body_sha256 = hashlib.sha256(b"").hexdigest()
    envelope = {
        "schema_id": "parser-tesseract-broker-v1",
        "sequence": sequence,
        "previous_sha256": previous_sha256,
        "kind": kind,
        "body_bytes": body_bytes,
        "body_sha256": body_sha256,
        "payload": dict(payload),
    }
    return hashlib.sha256(_semantic_json_bytes(envelope)).hexdigest()


def _request_control_expected_tokens(
    request_count: int,
    receipt_chunk_counts: Mapping[int, int | None] | None = None,
) -> tuple[tuple[str, str, str | None, int | None], ...]:
    tokens: list[tuple[str, str, str | None, int | None]] = [
        ("frame", "request_control_ready", "worker_to_controller", None)
    ]
    for sequence in range(1, request_count + 1):
        for kind in _REQUEST_CONTROL_REQUEST_KINDS[:4]:
            direction = _REQUEST_CONTROL_DIRECTION_BY_KIND[kind]
            tokens.append(("frame", kind, direction, sequence))
            if direction == "controller_to_worker":
                tokens.append(("send_completed", kind, None, sequence))
        if receipt_chunk_counts is not None:
            if sequence not in receipt_chunk_counts:
                break
            chunk_count = receipt_chunk_counts[sequence]
            if chunk_count is not None:
                for _ in range(chunk_count):
                    tokens.append(
                        (
                            "frame",
                            "request_control_receipt_chunk",
                            "worker_to_controller",
                            sequence,
                        )
                    )
                tokens.append(
                    (
                        "receipt_blob",
                        "request_control_receipt_blob_retained",
                        None,
                        sequence,
                    )
                )
        for kind in _REQUEST_CONTROL_REQUEST_KINDS[4:]:
            direction = _REQUEST_CONTROL_DIRECTION_BY_KIND[kind]
            tokens.append(("frame", kind, direction, sequence))
            if direction == "controller_to_worker":
                tokens.append(("send_completed", kind, None, sequence))
    if receipt_chunk_counts is not None and len(receipt_chunk_counts) != request_count:
        return tuple(tokens)
    tokens.extend(
        (
            ("frame", "request_control_close", "worker_to_controller", None),
            ("frame", "request_control_close_ack", "controller_to_worker", None),
            ("send_completed", "request_control_close_ack", None, None),
        )
    )
    return tuple(tokens)


def _request_control_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _request_control_log_json_bytes(value: object) -> bytes:
    """Match the controller-owned durable JSONL writer byte-for-byte."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _replay_request_control_transcript_jsonl(raw: bytes) -> dict[str, object]:
    if (
        not raw
        or len(raw) > REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES
        or not raw.endswith(b"\n")
    ):
        raise ValueError("terminal request-control transcript framing differs")
    outer_previous = "0" * 64
    payload_previous = "0" * 64
    wire_previous = "0" * 64
    wire_sequence = 0
    prior_retained_ns = 0
    rows: list[dict[str, object]] = []
    tokens: list[tuple[str, str, str | None, int | None]] = []
    frame_events: list[dict[str, object]] = []
    pending_authorization: dict[str, object] | None = None
    pending_receipt_transport: dict[str, object] | None = None
    receipt_blob_descriptors: list[RequestControlReceiptBlobDescriptor] = []
    receipt_chunk_frame_count = 0
    terminal: dict[str, object] | None = None
    terminal_is_control_failure = False
    terminal_row_sha256: str | None = None

    for row_sequence, encoded in enumerate(raw.splitlines(), 1):
        try:
            loaded = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "terminal request-control transcript JSON differs"
            ) from error
        if (
            type(loaded) is not dict
            or set(loaded)
            != {
                "schema_id",
                "row_sequence",
                "previous_row_sha256",
                "kind",
                "record",
                "retained_monotonic_ns",
                "row_sha256",
            }
            or encoded != _request_control_log_json_bytes(loaded)
        ):
            raise ValueError("terminal request-control row fields differ")
        row = dict(loaded)
        row_sha256 = row.pop("row_sha256")
        retained_ns = _request_control_positive_int(
            row.get("retained_monotonic_ns"), "transcript retained time"
        )
        if (
            row.get("schema_id")
            != "phase-latency-request-control-transcript-row-v1"
            or row.get("row_sequence") != row_sequence
            or row.get("previous_row_sha256") != outer_previous
            or type(row_sha256) is not str
            or _SHA256.fullmatch(row_sha256) is None
            or row_sha256
            != hashlib.sha256(_request_control_log_json_bytes(row)).hexdigest()
            or retained_ns < prior_retained_ns
            or type(row.get("kind")) is not str
            or type(row.get("record")) is not dict
            or terminal is not None
        ):
            raise ValueError("terminal request-control row chain differs")
        row["row_sha256"] = row_sha256
        rows.append(row)
        outer_previous = row_sha256
        prior_retained_ns = retained_ns
        kind = str(row["kind"])
        record = dict(row["record"])

        if kind == "request_control_send_completed":
            if (
                set(record)
                != {
                    "direction",
                    "authorization_row_sha256",
                    "message_kind",
                    "frame_sha256",
                    "payload_record_sha256",
                    "deadline_monotonic_ns",
                    "send_completed_monotonic_ns",
                }
                or pending_authorization is None
                or record.get("direction") != "controller_to_worker"
                or record.get("authorization_row_sha256")
                != pending_authorization["row_sha256"]
                or record.get("message_kind") != pending_authorization["kind"]
                or record.get("frame_sha256")
                != pending_authorization["frame_sha256"]
                or record.get("payload_record_sha256")
                != pending_authorization["payload_record_sha256"]
            ):
                raise ValueError("request-control send completion join differs")
            deadline = _request_control_positive_int(
                record.get("deadline_monotonic_ns"), "send deadline"
            )
            completed = _request_control_positive_int(
                record.get("send_completed_monotonic_ns"), "send completion"
            )
            payload = pending_authorization["payload"]
            assert isinstance(payload, dict)
            payload_deadline = payload.get("request_deadline_monotonic_ns")
            if (
                completed < pending_authorization["retained_monotonic_ns"]
                or completed >= deadline
                or completed > retained_ns
                or (
                    payload_deadline is not None
                    and deadline != payload_deadline
                )
            ):
                raise ValueError("request-control send completion time differs")
            request_sequence = payload.get("request_sequence")
            tokens.append(
                (
                    "send_completed",
                    str(pending_authorization["kind"]),
                    None,
                    request_sequence if isinstance(request_sequence, int) else None,
                )
            )
            wire_sequence += 1
            wire_previous = str(pending_authorization["frame_sha256"])
            payload_previous = str(
                pending_authorization["payload_record_sha256"]
            )
            pending_authorization = None
            continue

        if kind == "request_control_terminal_failure":
            if (
                set(record)
                != {
                    "attempt_id",
                    "attempt_nonce_sha256",
                    "scope_sha256",
                    "stage",
                    "failure_code",
                    "broker_request_receipt_sha256",
                    "failure_reason_sha256",
                    "request_id",
                    "request_epoch",
                    "request_sequence",
                    "request_deadline_monotonic_ns",
                    "last_payload_record_sha256",
                    "last_wire_frame_sha256",
                    "last_transcript_row_sha256",
                    "observed_monotonic_ns",
                }
                or pending_authorization is not None
                or record.get("stage") not in {"ready", "request", "close"}
                or record.get("failure_code")
                not in {
                    "peer_aborted_request",
                    "peer_protocol_or_eof_failure",
                    "controller_custody_failure",
                }
                or (
                    record.get("failure_code") == "peer_aborted_request"
                    and (
                        type(record.get("broker_request_receipt_sha256"))
                        is not str
                        or _SHA256.fullmatch(
                            str(record.get("broker_request_receipt_sha256"))
                        )
                        is None
                        or type(record.get("failure_reason_sha256")) is not str
                        or _SHA256.fullmatch(
                            str(record.get("failure_reason_sha256"))
                        )
                        is None
                    )
                )
                or (
                    record.get("failure_code") != "peer_aborted_request"
                    and (
                        record.get("broker_request_receipt_sha256") is not None
                        or record.get("failure_reason_sha256") is not None
                    )
                )
                or record.get("last_payload_record_sha256")
                != payload_previous
                or record.get("last_wire_frame_sha256") != wire_previous
                or record.get("last_transcript_row_sha256")
                != (rows[-2]["row_sha256"] if len(rows) >= 2 else "0" * 64)
                or _request_control_positive_int(
                    record.get("observed_monotonic_ns"),
                    "terminal failure observation",
                )
                > retained_ns
            ):
                raise ValueError("request-control terminal failure differs")
            terminal = record
            terminal_is_control_failure = True
            terminal_row_sha256 = row_sha256
            continue

        if kind == "request_control_send_terminal":
            if (
                set(record)
                != {
                    "attempt_id",
                    "attempt_nonce_sha256",
                    "scope_sha256",
                    "message_kind",
                    "frame_sha256",
                    "payload",
                    "payload_record_sha256",
                    "authorization_row_sha256",
                    "send_completion_row_sha256",
                    "deadline_monotonic_ns",
                    "failure_code",
                    "observed_monotonic_ns",
                }
                or terminal is not None
                or type(record.get("payload")) is not dict
            ):
                raise ValueError("request-control send terminal fields differ")
            payload = dict(record["payload"])
            payload_sha256 = payload.get("record_sha256")
            deadline = _request_control_positive_int(
                record.get("deadline_monotonic_ns"), "terminal deadline"
            )
            observed = _request_control_positive_int(
                record.get("observed_monotonic_ns"), "terminal observation"
            )
            if (
                type(payload_sha256) is not str
                or _SHA256.fullmatch(payload_sha256) is None
                or payload_sha256
                != hashlib.sha256(
                    _semantic_json_bytes(
                        {
                            key: item
                            for key, item in payload.items()
                            if key != "record_sha256"
                        }
                    )
                ).hexdigest()
                or record.get("payload_record_sha256") != payload_sha256
                or observed > retained_ns
            ):
                raise ValueError("request-control send terminal identity differs")
            failure_code = record.get("failure_code")
            authorization_sha256 = record.get("authorization_row_sha256")
            completion_sha256 = record.get("send_completion_row_sha256")
            completion_event = (
                rows[-2]
                if completion_sha256 is not None and len(rows) >= 2
                else None
            )
            if completion_event is not None:
                completion_record = completion_event.get("record")
                authorization_event = next(
                    (
                        item
                        for item in reversed(rows[:-2])
                        if item.get("row_sha256") == authorization_sha256
                    ),
                    None,
                )
                authorization_record = (
                    authorization_event.get("record")
                    if authorization_event is not None
                    else None
                )
                if (
                    completion_event.get("kind")
                    != "request_control_send_completed"
                    or type(completion_record) is not dict
                    or completion_sha256 != completion_event.get("row_sha256")
                    or record.get("message_kind")
                    != completion_record.get("message_kind")
                    or record.get("frame_sha256")
                    != completion_record.get("frame_sha256")
                    or record.get("payload_record_sha256")
                    != completion_record.get("payload_record_sha256")
                    or authorization_sha256
                    != completion_record.get("authorization_row_sha256")
                    or type(authorization_record) is not dict
                    or authorization_event.get("kind")
                    != record.get("message_kind")
                    or authorization_record.get("payload") != payload
                    or authorization_record.get("frame_sha256")
                    != record.get("frame_sha256")
                    or deadline != completion_record.get("deadline_monotonic_ns")
                    or observed
                    < completion_record.get("send_completed_monotonic_ns")
                    or failure_code
                    != "send_completion_retained_after_deadline"
                ):
                    raise ValueError(
                        "request-control completed-send terminal differs"
                    )
            elif pending_authorization is not None:
                if (
                    authorization_sha256
                    != pending_authorization["row_sha256"]
                    or record.get("message_kind")
                    != pending_authorization["kind"]
                    or record.get("frame_sha256")
                    != pending_authorization["frame_sha256"]
                    or record.get("payload_record_sha256")
                    != pending_authorization["payload_record_sha256"]
                    or payload != pending_authorization["payload"]
                    or deadline
                    != (
                        payload.get("request_deadline_monotonic_ns")
                        or deadline
                    )
                    or observed
                    < pending_authorization["retained_monotonic_ns"]
                    or failure_code
                    not in {
                        "deadline_expired_after_authorization",
                        "deadline_expired_during_send",
                        "authorized_send_failed",
                        "authorized_frame_digest_mismatch",
                    }
                ):
                    raise ValueError(
                        "request-control authorized-send terminal differs"
                    )
            elif (
                authorization_sha256 is not None
                or completion_sha256 is not None
                or failure_code != "deadline_expired_before_authorization"
                or payload.get("previous_record_sha256") != payload_previous
                or record.get("frame_sha256")
                != _request_control_frame_sha256(
                    sequence=wire_sequence + 1,
                    previous_sha256=wire_previous,
                    kind=str(record.get("message_kind")),
                    payload=payload,
                )
                or deadline
                != (payload.get("request_deadline_monotonic_ns") or deadline)
            ):
                raise ValueError(
                    "request-control preauthorization terminal differs"
                )
            terminal = record
            terminal_row_sha256 = row_sha256
            continue

        if kind == "request_control_receipt_chunk":
            if (
                pending_authorization is not None
                or pending_receipt_transport is None
                or set(record)
                != {
                    "direction",
                    "frame_sha256",
                    "payload",
                    "body_bytes",
                    "body_sha256",
                }
                or record.get("direction") != "worker_to_controller"
                or type(record.get("payload")) is not dict
            ):
                raise ValueError("request-control receipt chunk fields differ")
            chunk_payload = dict(record["payload"])
            if set(chunk_payload) != {
                "manifest_sha256",
                "chunk_commitment",
            }:
                raise ValueError("request-control receipt chunk payload differs")
            try:
                from app.services.tesseract_broker_protocol import (
                    request_receipt_chunk_commitment_from_mapping,
                )

                commitment = request_receipt_chunk_commitment_from_mapping(
                    chunk_payload["chunk_commitment"]
                )
            except Exception as error:
                raise ValueError(
                    "request-control receipt chunk commitment differs"
                ) from error
            manifest = pending_receipt_transport["manifest"]
            receipt_deadline = pending_receipt_transport["deadline_monotonic_ns"]
            prior_commitment = pending_receipt_transport[
                "previous_commitment_sha256"
            ]
            retained_bytes = pending_receipt_transport["retained_bytes"]
            expected_index = pending_receipt_transport["next_chunk_index"]
            body_bytes = _request_control_positive_int(
                record.get("body_bytes"), "receipt chunk body bytes"
            )
            body_sha256 = record.get("body_sha256")
            assert hasattr(manifest, "record_sha256")
            if (
                chunk_payload.get("manifest_sha256")
                != manifest.record_sha256
                or commitment.chunk_index != expected_index
                or commitment.chunk_offset != retained_bytes
                or commitment.receipt_sha256 != manifest.receipt_sha256
                or commitment.receipt_blob_sha256
                != manifest.receipt_blob_sha256
                or commitment.previous_chunk_commitment_sha256
                != prior_commitment
                or commitment.body_bytes != body_bytes
                or commitment.body_sha256 != body_sha256
                or retained_bytes + body_bytes > manifest.receipt_blob_bytes
                or retained_ns >= receipt_deadline
            ):
                raise ValueError("request-control receipt chunk chain differs")
            frame_sha256 = _request_control_frame_sha256(
                sequence=wire_sequence + 1,
                previous_sha256=wire_previous,
                kind=kind,
                payload=chunk_payload,
                body_bytes=body_bytes,
                body_sha256=str(body_sha256),
            )
            if record.get("frame_sha256") != frame_sha256:
                raise ValueError("request-control receipt chunk frame differs")
            request_sequence = int(
                pending_receipt_transport["request_sequence"]
            )
            tokens.append(("frame", kind, "worker_to_controller", request_sequence))
            pending_receipt_transport["next_chunk_index"] = expected_index + 1
            pending_receipt_transport["retained_bytes"] = retained_bytes + body_bytes
            pending_receipt_transport["previous_commitment_sha256"] = (
                commitment.commitment_sha256
            )
            pending_receipt_transport["chunk_frame_sha256s"].append(
                frame_sha256
            )
            pending_receipt_transport["chunk_transcript_row_sha256s"].append(
                row_sha256
            )
            wire_sequence += 1
            wire_previous = frame_sha256
            receipt_chunk_frame_count += 1
            continue

        if kind == "request_control_receipt_blob_retained":
            if pending_authorization is not None or pending_receipt_transport is None:
                raise ValueError("request-control receipt blob lacked transport")
            try:
                descriptor = RequestControlReceiptBlobDescriptor.model_validate(
                    {
                        **record,
                        "retained_transcript_row_sha256": row_sha256,
                    }
                )
            except Exception as error:
                raise ValueError(
                    "request-control receipt blob descriptor differs"
                ) from error
            manifest = pending_receipt_transport["manifest"]
            if (
                descriptor.request_sequence
                != pending_receipt_transport["request_sequence"]
                or descriptor.manifest_record_sha256
                != manifest.record_sha256
                or descriptor.receipt_sha256 != manifest.receipt_sha256
                or descriptor.receipt_blob_sha256
                != manifest.receipt_blob_sha256
                or descriptor.receipt_blob_bytes != manifest.receipt_blob_bytes
                or descriptor.chunk_count != manifest.chunk_count
                or descriptor.terminal_chunk_commitment_sha256
                != manifest.terminal_chunk_commitment_sha256
                or descriptor.chunk_frame_sha256s
                != tuple(pending_receipt_transport["chunk_frame_sha256s"])
                or descriptor.chunk_transcript_row_sha256s
                != tuple(
                    pending_receipt_transport[
                        "chunk_transcript_row_sha256s"
                    ]
                )
                or pending_receipt_transport["retained_bytes"]
                != manifest.receipt_blob_bytes
                or pending_receipt_transport["next_chunk_index"]
                != manifest.chunk_count + 1
                or pending_receipt_transport["previous_commitment_sha256"]
                != manifest.terminal_chunk_commitment_sha256
                or retained_ns
                >= pending_receipt_transport["deadline_monotonic_ns"]
            ):
                raise ValueError("request-control receipt blob join differs")
            tokens.append(
                (
                    "receipt_blob",
                    kind,
                    None,
                    descriptor.request_sequence,
                )
            )
            receipt_blob_descriptors.append(descriptor)
            pending_receipt_transport = None
            continue

        if pending_receipt_transport is not None:
            raise ValueError("request-control receipt transport ended early")
        if kind not in _REQUEST_CONTROL_DIRECTION_BY_KIND:
            raise ValueError("request-control wire kind differs")
        if (
            set(record) != {"direction", "frame_sha256", "payload"}
            or record.get("direction") != _REQUEST_CONTROL_DIRECTION_BY_KIND[kind]
            or type(record.get("payload")) is not dict
        ):
            raise ValueError("request-control retained frame fields differ")
        payload = dict(record["payload"])
        expected_payload_keys = _REQUEST_CONTROL_PAYLOAD_KEYS[kind]
        if kind == "request_control_end_blocked" and set(payload) == (
            _REQUEST_CONTROL_LEGACY_INLINE_END_KEYS
        ):
            expected_payload_keys = _REQUEST_CONTROL_LEGACY_INLINE_END_KEYS
        if set(payload) != expected_payload_keys:
            raise ValueError("request-control payload fields differ")
        record_sha256 = payload.get("record_sha256")
        if (
            payload.get("schema_id") != _REQUEST_CONTROL_SCHEMA_BY_KIND[kind]
            or type(record_sha256) is not str
            or _SHA256.fullmatch(record_sha256) is None
            or record_sha256
            != hashlib.sha256(
                _semantic_json_bytes(
                    {
                        key: item
                        for key, item in payload.items()
                        if key != "record_sha256"
                    }
                )
            ).hexdigest()
            or payload.get("previous_record_sha256") != payload_previous
        ):
            raise ValueError("request-control payload identity differs")
        frame_sha256 = _request_control_frame_sha256(
            sequence=wire_sequence + 1,
            previous_sha256=wire_previous,
            kind=kind,
            payload=payload,
        )
        if record.get("frame_sha256") != frame_sha256:
            raise ValueError("request-control frame identity differs")
        direction = str(record["direction"])
        request_sequence = payload.get("request_sequence")
        sequence_value = (
            request_sequence if isinstance(request_sequence, int) else None
        )
        tokens.append(("frame", kind, direction, sequence_value))
        event = {
            "kind": kind,
            "direction": direction,
            "payload": payload,
            "frame_sha256": frame_sha256,
            "row_sha256": row_sha256,
            "payload_record_sha256": record_sha256,
            "retained_monotonic_ns": retained_ns,
        }
        frame_events.append(event)
        if kind == "request_control_end_blocked" and (
            "broker_request_receipt_manifest" in payload
        ):
            if pending_receipt_transport is not None:
                raise ValueError("request-control receipt transports overlapped")
            try:
                from app.services.tesseract_broker_protocol import (
                    request_receipt_manifest_from_mapping,
                )

                manifest = request_receipt_manifest_from_mapping(
                    payload["broker_request_receipt_manifest"]
                )
            except Exception as error:
                raise ValueError(
                    "request-control receipt manifest differs"
                ) from error
            if (
                manifest.request_id != payload.get("request_id")
                or manifest.request_epoch != payload.get("request_epoch")
                or manifest.request_sequence != payload.get("request_sequence")
                or manifest.logical_phase != "request"
                or manifest.receipt_sha256
                != payload.get("broker_request_receipt_sha256")
            ):
                raise ValueError("request-control receipt manifest join differs")
            pending_receipt_transport = {
                "manifest": manifest,
                "request_sequence": payload["request_sequence"],
                "next_chunk_index": 1,
                "retained_bytes": 0,
                "previous_commitment_sha256": "0" * 64,
                "chunk_frame_sha256s": [],
                "chunk_transcript_row_sha256s": [],
                "deadline_monotonic_ns": payload[
                    "request_deadline_monotonic_ns"
                ],
            }
        if direction == "controller_to_worker":
            if pending_authorization is not None:
                raise ValueError("request-control authorization overlapped")
            pending_authorization = event
        else:
            if pending_authorization is not None:
                raise ValueError("request-control peer frame preceded send completion")
            wire_sequence += 1
            wire_previous = frame_sha256
            payload_previous = record_sha256

    if not frame_events or frame_events[0]["kind"] != "request_control_ready":
        raise ValueError("request-control transcript lacks first READY")
    ready = frame_events[0]["payload"]
    assert isinstance(ready, dict)
    expected_request_count = _request_control_positive_int(
        ready.get("expected_request_count"), "expected request count"
    )
    if expected_request_count > MAXIMUM_REQUESTS_PER_ATTEMPT:
        raise ValueError("request-control expected request count exceeds bound")
    attempt_id = ready.get("attempt_id")
    attempt_nonce_sha256 = ready.get("attempt_nonce_sha256")
    scope_sha256 = ready.get("scope_sha256")
    worker = ready.get("worker")
    broker = ready.get("broker")
    if (
        type(attempt_id) is not str
        or not attempt_id
        or type(attempt_nonce_sha256) is not str
        or _SHA256.fullmatch(attempt_nonce_sha256) is None
        or type(scope_sha256) is not str
        or _SHA256.fullmatch(scope_sha256) is None
        or type(worker) is not dict
        or type(broker) is not dict
        or ready.get("previous_record_sha256") != "0" * 64
    ):
        raise ValueError("request-control READY authority differs")

    events_by_request: dict[int, dict[str, dict[str, object]]] = {}
    for event in frame_events[1:]:
        kind = str(event["kind"])
        payload = event["payload"]
        assert isinstance(payload, dict)
        if kind in _REQUEST_CONTROL_REQUEST_KINDS:
            sequence = _request_control_positive_int(
                payload.get("request_sequence"), "request sequence"
            )
            deadline = _request_control_positive_int(
                payload.get("request_deadline_monotonic_ns"),
                "request deadline",
            )
            if (
                sequence > expected_request_count
                or payload.get("request_epoch") != sequence + 1
                or payload.get("request_id")
                != f"{attempt_id}-q{sequence:04d}"
                or payload.get("attempt_id") != attempt_id
                or payload.get("attempt_nonce_sha256")
                != attempt_nonce_sha256
                or payload.get("scope_sha256") != scope_sha256
                or payload.get("worker") != worker
                or payload.get("broker") != broker
                or deadline <= 0
            ):
                raise ValueError("request-control request authority differs")
            current = events_by_request.setdefault(sequence, {})
            if kind in current:
                raise ValueError("request-control request frame repeated")
            current[kind] = event
        elif kind in {"request_control_close", "request_control_close_ack"}:
            if (
                payload.get("attempt_id") != attempt_id
                or payload.get("attempt_nonce_sha256")
                != attempt_nonce_sha256
                or payload.get("scope_sha256") != scope_sha256
                or payload.get("worker") != worker
                or payload.get("broker") != broker
            ):
                raise ValueError("request-control close authority differs")

    receipt_chunk_counts: dict[int, int | None] = {}
    descriptor_by_sequence = {
        item.request_sequence: item for item in receipt_blob_descriptors
    }
    if len(descriptor_by_sequence) != len(receipt_blob_descriptors):
        raise ValueError("request-control receipt blob sequence repeated")
    for sequence in range(1, expected_request_count + 1):
        end_event = events_by_request.get(sequence, {}).get(
            "request_control_end_blocked"
        )
        if end_event is None:
            break
        end_payload = end_event.get("payload")
        assert isinstance(end_payload, dict)
        manifest_mapping = end_payload.get("broker_request_receipt_manifest")
        if manifest_mapping is None:
            receipt_chunk_counts[sequence] = None
        else:
            try:
                from app.services.tesseract_broker_protocol import (
                    request_receipt_manifest_from_mapping,
                )

                manifest = request_receipt_manifest_from_mapping(
                    manifest_mapping
                )
            except Exception as error:
                raise ValueError(
                    "request-control receipt manifest differs"
                ) from error
            receipt_chunk_counts[sequence] = manifest.chunk_count
    expected_tokens = _request_control_expected_tokens(
        expected_request_count,
        receipt_chunk_counts,
    )
    if tuple(tokens) != expected_tokens[: len(tokens)]:
        raise ValueError("request-control terminal grammar differs")
    if len(tokens) > len(expected_tokens):
        raise ValueError("request-control transcript exceeded terminal grammar")

    completed_request_count = 0
    request_records: list[dict[str, object]] = []
    for sequence in range(1, expected_request_count + 1):
        current = events_by_request.get(sequence, {})
        if not all(kind in current for kind in _REQUEST_CONTROL_REQUEST_KINDS):
            break
        payloads = {
            kind: current[kind]["payload"]
            for kind in _REQUEST_CONTROL_REQUEST_KINDS
        }
        arm = payloads["request_control_arm"]
        begin = payloads["request_control_begin_blocked"]
        begin_release = payloads["request_control_begin_release"]
        end = payloads["request_control_end_blocked"]
        receipt_release = payloads["request_control_receipt_release"]
        result = payloads["request_control_result"]
        ack = payloads["request_control_result_ack"]
        assert all(isinstance(item, dict) for item in payloads.values())
        end_has_manifest = "broker_request_receipt_manifest" in end
        request_wire_completed = (
            (
                not end_has_manifest
                or sequence in descriptor_by_sequence
            )
            and (
                "send_completed",
                "request_control_result_ack",
                None,
                sequence,
            )
            in tokens
        )
        binding = arm.get("binding")
        broker_receipt = end.get("broker_request_receipt")
        broker_receipt_manifest = end.get(
            "broker_request_receipt_manifest"
        )
        broker_receipt_identity = (
            broker_receipt
            if isinstance(broker_receipt, dict)
            else broker_receipt_manifest
        )
        response_witness = end.get("asgi_response_witness")
        try:
            typed_response_witness = AsgiResponseWitness.model_validate(
                response_witness
            )
        except Exception as error:
            raise ValueError(
                "request-control ASGI response witness differs"
            ) from error
        if (
            type(binding) is not dict
            or arm.get("binding_sha256")
            != hashlib.sha256(_semantic_json_bytes(binding)).hexdigest()
            or begin.get("arm_record_sha256") != arm.get("record_sha256")
            or begin_release.get("begin_blocked_record_sha256")
            != begin.get("record_sha256")
            or end.get("begin_release_record_sha256")
            != begin_release.get("record_sha256")
            or (
                type(broker_receipt) is not dict
                and type(broker_receipt_manifest) is not dict
            )
            or type(response_witness) is not dict
            or end.get("asgi_response_witness_sha256")
            != typed_response_witness.record_sha256
            or end.get("broker_request_receipt_sha256")
            != broker_receipt_identity.get("receipt_sha256")
            or end.get("full_inner_asgi_returned") is not True
            or end.get("request_task_blocked") is not True
            or receipt_release.get("end_blocked_record_sha256")
            != end.get("record_sha256")
            or receipt_release.get("broker_request_receipt_sha256")
            != end.get("broker_request_receipt_sha256")
            or result.get("receipt_release_record_sha256")
            != receipt_release.get("record_sha256")
            or type(result.get("worker_result")) is not dict
            or ack.get("result_record_sha256") != result.get("record_sha256")
        ):
            raise ValueError("request-control request frame join differs")
        deadline = int(arm["request_deadline_monotonic_ns"])
        if (
            _request_control_positive_int(
                arm.get("arm_issued_at_monotonic_ns"), "ARM issue time"
            )
            >= deadline
            or _request_control_positive_int(
                begin.get("arm_consumed_at_monotonic_ns"), "ARM consumed time"
            )
            >= deadline
            or _request_control_positive_int(
                begin_release.get("begin_release_monotonic_ns"),
                "BEGIN release time",
            )
            >= deadline
            or _request_control_positive_int(
                receipt_release.get("receipt_release_monotonic_ns"),
                "receipt release time",
            )
            >= deadline
            or _request_control_positive_int(
                ack.get("retained_at_monotonic_ns"), "result ACK time"
            )
            >= deadline
        ):
            raise ValueError("request-control request deadline escaped")
        if request_wire_completed:
            completed_request_count += 1
            request_records.append(
                {
                    "request_sequence": sequence,
                    "record_sha256s": tuple(
                        str(current[kind]["payload_record_sha256"])
                        for kind in _REQUEST_CONTROL_REQUEST_KINDS
                    ),
                    "transcript_row_sha256s": tuple(
                        str(current[kind]["row_sha256"])
                        for kind in _REQUEST_CONTROL_REQUEST_KINDS
                    ),
                    "arm_binding": binding,
                    "broker_request_receipt": broker_receipt,
                    "broker_request_receipt_manifest": (
                        broker_receipt_manifest
                    ),
                    "broker_request_receipt_blob": (
                        descriptor_by_sequence.get(sequence)
                    ),
                    "asgi_response_witness": response_witness,
                    "worker_result": result["worker_result"],
                }
            )
        else:
            break

    success = len(tokens) == len(expected_tokens) and terminal is None
    if success:
        close = frame_events[-2]["payload"]
        close_ack = frame_events[-1]["payload"]
        assert isinstance(close, dict) and isinstance(close_ack, dict)
        if (
            completed_request_count != expected_request_count
            or close.get("completed_request_count") != expected_request_count
            or close.get("last_request_sequence") != expected_request_count
            or close_ack.get("completed_request_count")
            != expected_request_count
            or close_ack.get("close_record_sha256")
            != close.get("record_sha256")
        ):
            raise ValueError("request-control successful close differs")
        disposition = "success"
    elif terminal is not None:
        if terminal_is_control_failure:
            if (
                terminal.get("attempt_id") != attempt_id
                or terminal.get("attempt_nonce_sha256")
                != attempt_nonce_sha256
                or terminal.get("scope_sha256") != scope_sha256
            ):
                raise ValueError(
                    "request-control terminal failure authority differs"
                )
            last_request_payload = next(
                (
                    event["payload"]
                    for event in reversed(frame_events)
                    if event["kind"] in _REQUEST_CONTROL_REQUEST_KINDS
                ),
                None,
            )
            if last_request_payload is None:
                expected_request = (None, None, None, None)
            else:
                assert isinstance(last_request_payload, dict)
                expected_request = (
                    last_request_payload.get("request_id"),
                    last_request_payload.get("request_epoch"),
                    last_request_payload.get("request_sequence"),
                    last_request_payload.get("request_deadline_monotonic_ns"),
                )
            if (
                (
                    terminal.get("request_id"),
                    terminal.get("request_epoch"),
                    terminal.get("request_sequence"),
                    terminal.get("request_deadline_monotonic_ns"),
                )
                != expected_request
            ):
                raise ValueError(
                    "request-control terminal failure request differs"
                )
            if terminal.get("failure_code") == "peer_aborted_request":
                if (
                    not frame_events
                    or frame_events[-1]["kind"]
                    != "request_control_end_blocked"
                ):
                    raise ValueError(
                        "request-control aborted END frame is absent"
                    )
                aborted_event = frame_events[-1]
                aborted_end = aborted_event["payload"]
                assert isinstance(aborted_end, dict)
                raw_receipt = aborted_end.get("broker_request_receipt")
                raw_barrier = aborted_end.get("end_barrier")
                if not isinstance(raw_receipt, dict) or not isinstance(
                    raw_barrier, dict
                ):
                    raise ValueError(
                        "request-control aborted END evidence differs"
                    )
                try:
                    from app.services.tesseract_broker_protocol import (
                        BrokerBarrierSnapshot,
                        process_identity_from_mapping,
                        quiescence_from_mapping,
                        request_receipt_from_mapping,
                    )

                    receipt = request_receipt_from_mapping(raw_receipt)
                    barrier_keys = {
                        "kind",
                        "request_id",
                        "request_epoch",
                        "request_sequence",
                        "broker_identity",
                        "quiescence",
                        "client_protocol_pending_bytes",
                        "transcript_next_sequence",
                        "transcript_head_sha256",
                        "receipt_sha256",
                    }
                    if set(raw_barrier) != barrier_keys:
                        raise ValueError("abort barrier fields differ")
                    barrier = BrokerBarrierSnapshot(
                        kind=raw_barrier["kind"],
                        request_id=raw_barrier["request_id"],
                        request_epoch=raw_barrier["request_epoch"],
                        request_sequence=raw_barrier["request_sequence"],
                        broker_identity=process_identity_from_mapping(
                            raw_barrier["broker_identity"]
                        ),
                        quiescence=quiescence_from_mapping(
                            raw_barrier["quiescence"]
                        ),
                        client_protocol_pending_bytes=raw_barrier[
                            "client_protocol_pending_bytes"
                        ],
                        transcript_next_sequence=raw_barrier[
                            "transcript_next_sequence"
                        ],
                        transcript_head_sha256=raw_barrier[
                            "transcript_head_sha256"
                        ],
                        receipt_sha256=raw_barrier["receipt_sha256"],
                    )
                except Exception as error:
                    raise ValueError(
                        "request-control aborted END typed evidence differs"
                    ) from error
                request_events = events_by_request.get(
                    int(aborted_end["request_sequence"]), {}
                )
                arm_event = request_events.get("request_control_arm")
                begin_event = request_events.get(
                    "request_control_begin_blocked"
                )
                arm_payload = (
                    arm_event.get("payload")
                    if isinstance(arm_event, dict)
                    else None
                )
                begin_payload = (
                    begin_event.get("payload")
                    if isinstance(begin_event, dict)
                    else None
                )
                request_binding = receipt.request_binding
                expected_binding_sha256 = (
                    request_binding.record_sha256
                    if request_binding is not None
                    else "0" * 64
                )
                empty_failure_sha256 = hashlib.sha256(b"").hexdigest()
                if (
                    not isinstance(arm_payload, dict)
                    or not isinstance(begin_payload, dict)
                    or receipt.logical_phase != "request"
                    or receipt.terminal_kind != "abort"
                    or receipt.arm_terminal_disposition != "aborted"
                    or receipt.failure_reason_sha256
                    == empty_failure_sha256
                    or receipt.request_id != aborted_end.get("request_id")
                    or receipt.request_epoch
                    != aborted_end.get("request_epoch")
                    or receipt.request_sequence
                    != aborted_end.get("request_sequence")
                    or receipt.attempt_nonce_sha256
                    != aborted_end.get("attempt_nonce_sha256")
                    or receipt.scope_sha256
                    != aborted_end.get("scope_sha256")
                    or receipt.phase_deadline_monotonic_ns
                    != aborted_end.get("request_deadline_monotonic_ns")
                    or receipt.arm_issued_at_monotonic_ns
                    != arm_payload.get("arm_issued_at_monotonic_ns")
                    or receipt.arm_consumed_at_monotonic_ns
                    != begin_payload.get("arm_consumed_at_monotonic_ns")
                    or receipt.arm_capability_sha256
                    != begin_payload.get("arm_capability_sha256")
                    or request_binding is None
                    or receipt.binding_sha256
                    != arm_payload.get("binding_sha256")
                    or (
                        request_binding is not None
                        and (
                            request_binding.binding_record_sha256
                            != receipt.binding_sha256
                            or {
                                "schema_id": request_binding.schema_id,
                                "method": request_binding.method,
                                "path": request_binding.path,
                                "query_sha256": request_binding.query_sha256,
                                "output_format": request_binding.output_format,
                                "source_sha256": request_binding.source_sha256,
                                "source_bytes": request_binding.source_bytes,
                                "safe_filename_sha256": (
                                    request_binding.safe_filename_sha256
                                ),
                                "upload_content_type_sha256": (
                                    request_binding.upload_content_type_sha256
                                ),
                            }
                            != arm_payload.get("binding")
                        )
                    )
                    or aborted_end.get("broker_request_receipt_sha256")
                    != receipt.receipt_sha256
                    or terminal.get("broker_request_receipt_sha256")
                    != receipt.receipt_sha256
                    or terminal.get("failure_reason_sha256")
                    != receipt.failure_reason_sha256
                    or aborted_end.get("request_binding_record_sha256")
                    != expected_binding_sha256
                    or tuple(
                        aborted_end.get("thread_transfer_record_sha256s", ())
                    )
                    != tuple(
                        item.record_sha256 for item in receipt.thread_transfers
                    )
                    or aborted_end.get("asgi_response_witness") is not None
                    or aborted_end.get("asgi_response_witness_sha256")
                    != "0" * 64
                    or aborted_end.get("full_inner_asgi_returned") is not False
                    or aborted_end.get("request_task_blocked") is not True
                    or barrier.kind != "END"
                    or barrier.request_id != receipt.request_id
                    or barrier.request_epoch != receipt.request_epoch
                    or barrier.request_sequence != receipt.request_sequence
                    or barrier.broker_identity != receipt.end.broker_identity
                    or barrier.quiescence != receipt.end
                    or barrier.receipt_sha256 != receipt.receipt_sha256
                    or terminal.get("observed_monotonic_ns")
                    >= receipt.phase_deadline_monotonic_ns
                    or aborted_event["retained_monotonic_ns"]
                    >= receipt.phase_deadline_monotonic_ns
                ):
                    raise ValueError(
                        "request-control aborted END custody differs"
                    )
            disposition = "peer_terminal_failure"
        else:
            message_kind = terminal.get("message_kind")
            authorization_sha = terminal.get("authorization_row_sha256")
            completion_sha = terminal.get("send_completion_row_sha256")
            if pending_authorization is not None:
                expected_kind = pending_authorization["kind"]
                expected_authorization = pending_authorization["row_sha256"]
            elif completion_sha is not None and tokens:
                expected_kind = tokens[-1][1]
                completion_record = rows[-2]["record"]
                assert isinstance(completion_record, dict)
                expected_authorization = completion_record[
                    "authorization_row_sha256"
                ]
            else:
                next_token = (
                    expected_tokens[len(tokens)]
                    if len(tokens) < len(expected_tokens)
                    else None
                )
                expected_kind = next_token[1] if next_token is not None else None
                expected_authorization = None
            if (
                message_kind != expected_kind
                or authorization_sha != expected_authorization
                or (
                    completion_sha is not None
                    and (
                        not tokens
                        or tokens[-1][0] != "send_completed"
                        or completion_sha != rows[-2]["row_sha256"]
                    )
                )
            ):
                raise ValueError("request-control send terminal join differs")
            failure_code = terminal.get("failure_code")
            if failure_code == "deadline_expired_after_authorization":
                disposition = "authorized_unsent"
            elif completion_sha is not None:
                disposition = "sent_no_peer"
            elif authorization_sha is not None:
                disposition = "authorized_delivery_unknown"
            else:
                disposition = "controller_send_terminal"
    elif tokens and tokens[-1][0] == "frame" and tokens[-1][2] == (
        "controller_to_worker"
    ):
        disposition = "authorized_delivery_unknown"
    elif tokens and tokens[-1][0] == "send_completed":
        disposition = "sent_no_peer"
    else:
        raise ValueError("request-control terminal failure prefix differs")

    return {
        "attempt_id": attempt_id,
        "attempt_nonce_sha256": attempt_nonce_sha256,
        "scope_sha256": scope_sha256,
        "worker": worker,
        "broker": broker,
        "expected_request_count": expected_request_count,
        "completed_request_count": completed_request_count,
        "outcome": "success" if success else "failure",
        "failure_disposition": disposition,
        "row_count": len(rows),
        "head_sha256": outer_previous,
        "wire_frame_count": len(frame_events) + receipt_chunk_frame_count,
        "authorization_count": sum(
            1
            for event in frame_events
            if event["direction"] == "controller_to_worker"
        ),
        "send_completion_count": sum(
            1 for token in tokens if token[0] == "send_completed"
        ),
        "received_frame_count": sum(
            1
            for event in frame_events
            if event["direction"] == "worker_to_controller"
        )
        + receipt_chunk_frame_count,
        "last_wire_frame_sha256": wire_previous,
        "terminal_row_sha256": terminal_row_sha256,
        "ready_record_sha256": ready["record_sha256"],
        "ready_transcript_row_sha256": frame_events[0]["row_sha256"],
        "request_records": tuple(request_records),
        "receipt_blob_descriptors": tuple(receipt_blob_descriptors),
    }


class TerminalRequestControlTranscriptEvidence(ContractModel):
    """Closed raw request-control authorization and delivery transcript."""

    schema_id: Literal["phase-latency-terminal-request-control-transcript-v1"] = (
        "phase-latency-terminal-request-control-transcript-v1"
    )
    encoding: Literal["canonical-jsonl-utf8-base64-v1"] = (
        "canonical-jsonl-utf8-base64-v1"
    )
    canonical_jsonl_base64: Annotated[
        str, Field(max_length=REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BASE64_CHARACTERS)
    ]
    size_bytes: Annotated[
        int,
        Field(strict=True, gt=0, le=REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES),
    ]
    sha256: Sha256
    row_count: PositiveInt
    head_sha256: Sha256
    attempt_id: StableId
    attempt_nonce_sha256: Sha256
    scope_sha256: Sha256
    worker: ExactProcessIdentity
    broker: ExactProcessIdentity
    expected_request_count: PositiveInt
    completed_request_count: NonNegativeInt
    outcome: Literal["success", "failure"]
    failure_disposition: Literal[
        "success",
        "authorized_unsent",
        "authorized_delivery_unknown",
        "sent_no_peer",
        "controller_send_terminal",
        "peer_terminal_failure",
    ]
    wire_frame_count: PositiveInt
    authorization_count: NonNegativeInt
    send_completion_count: NonNegativeInt
    received_frame_count: PositiveInt
    last_wire_frame_sha256: Sha256
    terminal_row_sha256: Sha256 | None = None
    receipt_blobs: Annotated[
        tuple[RequestControlReceiptBlobDescriptor, ...], Field(max_length=32)
    ] = ()
    file_device: NonNegativeInt
    file_inode: PositiveInt
    file_mode: Literal[0o600] = 0o600
    file_uid: NonNegativeInt
    file_nlink: Literal[1] = 1
    o_excl_created: Literal[True] = True
    fsynced_before_close: Literal[True] = True
    reopened_no_follow_after_fsync: Literal[True] = True
    record_sha256: Sha256

    def raw_bytes(self) -> bytes:
        try:
            return base64.b64decode(
                self.canonical_jsonl_base64.encode("ascii"), validate=True
            )
        except (UnicodeEncodeError, ValueError) as error:
            raise ValueError(
                "terminal request-control transcript is not strict base64"
            ) from error

    @model_validator(mode="after")
    def validate_terminal_transcript(
        self,
    ) -> "TerminalRequestControlTranscriptEvidence":
        raw = self.raw_bytes()
        replay = _replay_request_control_transcript_jsonl(raw)
        worker = replay["worker"]
        broker = replay["broker"]
        assert isinstance(worker, dict) and isinstance(broker, dict)
        retained = (
            self.attempt_id,
            self.attempt_nonce_sha256,
            self.scope_sha256,
            self.expected_request_count,
            self.completed_request_count,
            self.outcome,
            self.failure_disposition,
            self.row_count,
            self.head_sha256,
            self.wire_frame_count,
            self.authorization_count,
            self.send_completion_count,
            self.received_frame_count,
            self.last_wire_frame_sha256,
            self.terminal_row_sha256,
        )
        expected = tuple(
            replay[name]
            for name in (
                "attempt_id",
                "attempt_nonce_sha256",
                "scope_sha256",
                "expected_request_count",
                "completed_request_count",
                "outcome",
                "failure_disposition",
                "row_count",
                "head_sha256",
                "wire_frame_count",
                "authorization_count",
                "send_completion_count",
                "received_frame_count",
                "last_wire_frame_sha256",
                "terminal_row_sha256",
            )
        )
        if (
            len(raw) != self.size_bytes
            or hashlib.sha256(raw).hexdigest() != self.sha256
            or base64.b64encode(raw).decode("ascii")
            != self.canonical_jsonl_base64
            or retained != expected
            or RequestControlReadinessEvidence._identity_mapping(self.worker)
            != worker
            or RequestControlReadinessEvidence._identity_mapping(self.broker)
            != broker
            or self.receipt_blobs != replay["receipt_blob_descriptors"]
            or self.worker.role != "parser_worker"
            or self.broker.role != "tesseract_broker"
            or self.completed_request_count > self.expected_request_count
            or (self.outcome == "success")
            != (self.failure_disposition == "success")
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("terminal request-control transcript differs")
        return self


def terminal_request_control_transcript_evidence(
    raw: bytes,
    *,
    file_device: int,
    file_inode: int,
    file_uid: int,
) -> TerminalRequestControlTranscriptEvidence:
    replay = _replay_request_control_transcript_jsonl(raw)

    def identity(role: Literal["parser_worker", "tesseract_broker"]):
        key = "worker" if role == "parser_worker" else "broker"
        value = replay[key]
        assert isinstance(value, dict)
        return ExactProcessIdentity(
            role=role,
            pid=value["pid"],
            start_abstime=value["start_abstime"],
            parent_pid=value["ppid"],
            process_group_id=value["pgid"],
            session_id=value["sid"],
        )

    fields = {
        "schema_id": "phase-latency-terminal-request-control-transcript-v1",
        "encoding": "canonical-jsonl-utf8-base64-v1",
        "canonical_jsonl_base64": base64.b64encode(raw).decode("ascii"),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "row_count": replay["row_count"],
        "head_sha256": replay["head_sha256"],
        "attempt_id": replay["attempt_id"],
        "attempt_nonce_sha256": replay["attempt_nonce_sha256"],
        "scope_sha256": replay["scope_sha256"],
        "worker": identity("parser_worker"),
        "broker": identity("tesseract_broker"),
        "expected_request_count": replay["expected_request_count"],
        "completed_request_count": replay["completed_request_count"],
        "outcome": replay["outcome"],
        "failure_disposition": replay["failure_disposition"],
        "wire_frame_count": replay["wire_frame_count"],
        "authorization_count": replay["authorization_count"],
        "send_completion_count": replay["send_completion_count"],
        "received_frame_count": replay["received_frame_count"],
        "last_wire_frame_sha256": replay["last_wire_frame_sha256"],
        "terminal_row_sha256": replay["terminal_row_sha256"],
        "receipt_blobs": replay["receipt_blob_descriptors"],
        "file_device": file_device,
        "file_inode": file_inode,
        "file_mode": 0o600,
        "file_uid": file_uid,
        "file_nlink": 1,
        "o_excl_created": True,
        "fsynced_before_close": True,
        "reopened_no_follow_after_fsync": True,
    }
    provisional = TerminalRequestControlTranscriptEvidence.model_construct(
        **fields,
        record_sha256="0" * 64,
    )
    return TerminalRequestControlTranscriptEvidence(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),
    )


def _request_control_receipt_blob_mapping(
    *,
    root: Path,
    descriptor: RequestControlReceiptBlobDescriptor,
    manifest_mapping: object,
) -> dict[str, object]:
    """Descriptor-relative reread and frozen parse of one retained receipt."""

    try:
        from app.services.tesseract_broker_protocol import (
            request_receipt_from_blob,
            request_receipt_manifest_from_mapping,
        )

        manifest = request_receipt_manifest_from_mapping(manifest_mapping)
    except Exception as error:
        raise ValueError("request-control retained manifest differs") from error
    root_path = root.resolve(strict=True)
    root_stat = root_path.lstat()
    if (
        root_path != root
        or root_path.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.geteuid()
        or root_stat.st_mode & 0o077
    ):
        raise ValueError("request-control receipt root custody differs")
    root_fd = os.open(
        root_path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    file_fd = -1
    try:
        file_fd = os.open(
            descriptor.relative_path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root_fd,
        )
        observed = os.fstat(file_fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_dev != descriptor.file_device
            or observed.st_ino != descriptor.file_inode
            or stat.S_IMODE(observed.st_mode) != descriptor.file_mode
            or observed.st_uid != descriptor.file_uid
            or observed.st_nlink != descriptor.file_nlink
            or observed.st_size != descriptor.receipt_blob_bytes
        ):
            raise ValueError("request-control receipt file identity differs")
        chunks: list[bytes] = []
        retained_bytes = 0
        while retained_bytes < observed.st_size:
            chunk = os.read(
                file_fd,
                min(1_048_576, observed.st_size - retained_bytes),
            )
            if not chunk:
                raise ValueError("request-control receipt file ended early")
            chunks.append(chunk)
            retained_bytes += len(chunk)
        after = os.fstat(file_fd)
        if any(
            getattr(after, field) != getattr(observed, field)
            for field in (
                "st_dev",
                "st_ino",
                "st_mode",
                "st_uid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
            )
        ):
            raise ValueError("request-control receipt changed during reread")
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(root_fd)
    raw = b"".join(chunks)
    if (
        hashlib.sha256(raw).hexdigest() != descriptor.receipt_blob_sha256
        or descriptor.manifest_record_sha256 != manifest.record_sha256
        or descriptor.receipt_sha256 != manifest.receipt_sha256
        or descriptor.receipt_blob_sha256 != manifest.receipt_blob_sha256
        or descriptor.receipt_blob_bytes != manifest.receipt_blob_bytes
    ):
        raise ValueError("request-control receipt blob digest differs")
    try:
        receipt = request_receipt_from_blob(manifest, raw)
        mapping = json.loads(raw)
    except Exception as error:
        raise ValueError("request-control retained receipt differs") from error
    if not isinstance(mapping, dict) or receipt.receipt_sha256 != descriptor.receipt_sha256:
        raise ValueError("request-control retained receipt identity differs")
    return mapping


def _require_request_control_receipt_blob_membership(
    *,
    root: Path,
    attempt_id: str,
    descriptors: tuple[RequestControlReceiptBlobDescriptor, ...],
) -> None:
    """Require exact per-attempt membership before any receipt reread."""

    expected_blob_names = {
        descriptor.relative_path for descriptor in descriptors
    }
    prefix = f"{attempt_id}-request-"
    root_path = root.resolve(strict=True)
    root_stat = root_path.lstat()
    if (
        root_path != root
        or root_path.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.geteuid()
        or root_stat.st_mode & 0o077
    ):
        raise ValueError("request-control receipt root custody differs")
    root_descriptor = os.open(
        root_path,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        observed_blob_names = {
            name
            for name in os.listdir(root_descriptor)
            if name.startswith(prefix)
            and name.endswith("-broker-receipt.json")
        }
    finally:
        os.close(root_descriptor)
    if observed_blob_names != expected_blob_names:
        raise ValueError("request-control receipt blob membership differs")


def require_terminal_request_control_transcript(
    terminal: TerminalRequestControlTranscriptEvidence,
    readiness: RequestControlReadinessEvidence,
    exact_requests: tuple[ExactBrokerRequestCpuEvidence, ...],
    *,
    request_sources: tuple[SourceIdentity, ...],
    request_outputs: tuple[OutputIdentity, ...],
    receipt_blob_root: Path | None = None,
) -> None:
    replay = _replay_request_control_transcript_jsonl(terminal.raw_bytes())
    if (
        terminal.outcome != "success"
        or terminal.attempt_id != readiness.attempt_id
        or terminal.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
        or terminal.scope_sha256 != readiness.scope_sha256
        or terminal.worker != readiness.worker
        or terminal.broker != readiness.broker
        or terminal.expected_request_count != readiness.expected_request_count
        or terminal.expected_request_count != len(exact_requests)
        or len(request_sources) != len(exact_requests)
        or len(request_outputs) != len(exact_requests)
        or replay["ready_record_sha256"] != readiness.ready_record_sha256
        or replay["ready_transcript_row_sha256"]
        != readiness.transcript_row_sha256
    ):
        raise ValueError("terminal request-control READY custody differs")
    request_records = replay["request_records"]
    assert isinstance(request_records, tuple)
    if len(request_records) != len(exact_requests):
        raise ValueError("terminal request-control request count differs")
    if receipt_blob_root is not None:
        _require_request_control_receipt_blob_membership(
            root=receipt_blob_root,
            attempt_id=terminal.attempt_id,
            descriptors=terminal.receipt_blobs,
        )
    from app.services.tesseract_broker_protocol import (
        request_receipt_from_mapping,
    )
    from tests.benchmarks.latency_prewarm_production_worker import (
        ProductionRawRequestObservation,
    )

    for replayed, exact, source, output in zip(
        request_records,
        exact_requests,
        request_sources,
        request_outputs,
        strict=True,
    ):
        assert isinstance(replayed, dict)
        raw_receipt = replayed["broker_request_receipt"]
        raw_receipt_manifest = replayed["broker_request_receipt_manifest"]
        receipt_blob = replayed["broker_request_receipt_blob"]
        raw_worker_result = replayed["worker_result"]
        raw_response_witness = replayed["asgi_response_witness"]
        if not isinstance(raw_worker_result, dict) or not isinstance(
            raw_response_witness, dict
        ):
            raise ValueError("terminal request-control typed payload differs")
        try:
            worker_result = ProductionRawRequestObservation.model_validate(
                raw_worker_result
            )
            response_witness = AsgiResponseWitness.model_validate(
                raw_response_witness
            )
        except Exception as error:
            raise ValueError(
                "terminal request-control typed payload differs"
            ) from error
        exact_births = tuple(
            child.birth.model_dump(mode="json") for child in exact.children
        )
        exact_tombstones = tuple(
            child.tombstone.model_dump(mode="json")
            for child in exact.children
        )
        if not isinstance(raw_receipt, dict) and receipt_blob_root is not None:
            if not isinstance(
                receipt_blob, RequestControlReceiptBlobDescriptor
            ):
                raise ValueError(
                    "terminal request-control receipt blob differs"
                )
            raw_receipt = _request_control_receipt_blob_mapping(
                root=receipt_blob_root,
                descriptor=receipt_blob,
                manifest_mapping=raw_receipt_manifest,
            )
        if isinstance(raw_receipt, dict):
            try:
                request_receipt_from_mapping(raw_receipt)
            except Exception as error:
                raise ValueError(
                    "terminal request-control typed receipt differs"
                ) from error
            receipt_projection_differs = (
                raw_receipt.get("request_id") != exact.request_id
                or raw_receipt.get("request_epoch") != exact.request_epoch
                or raw_receipt.get("request_sequence") != exact.request_sequence
                or raw_receipt.get("attempt_nonce_sha256")
                != exact.attempt_nonce_sha256
                or raw_receipt.get("scope_sha256") != exact.scope_sha256
                or raw_receipt.get("phase_deadline_monotonic_ns")
                != exact.request_deadline_monotonic_ns
                or raw_receipt.get("arm_capability_sha256")
                != exact.arm_capability_sha256
                or raw_receipt.get("arm_issued_at_monotonic_ns")
                != exact.arm_issued_at_monotonic_ns
                or raw_receipt.get("arm_consumed_at_monotonic_ns")
                != exact.arm_consumed_at_monotonic_ns
                or raw_receipt.get("arm_terminal_disposition") != "ended"
                or raw_receipt.get("logical_phase") != "request"
                or raw_receipt.get("terminal_kind") != "end"
                or raw_receipt.get("thread_transfer_required") is not True
                or raw_receipt.get("binding_sha256") != exact.binding_sha256
                or raw_receipt.get("request_binding")
                != exact.request_binding.model_dump(mode="json")
                or raw_receipt.get("thread_claim_count")
                != exact.thread_claim_count
                or tuple(
                    item.get("record_sha256")
                    for item in raw_receipt.get("thread_transfers", ())
                    if isinstance(item, dict)
                )
                != exact.thread_transfer_record_sha256s
                or tuple(raw_receipt.get("births", ())) != exact_births
                or tuple(raw_receipt.get("tombstones", ()))
                != exact_tombstones
                or not _lifecycle_quiescence_matches(
                    raw_receipt.get("begin"), exact.begin, phase="begin"
                )
                or not _lifecycle_quiescence_matches(
                    raw_receipt.get("end"), exact.end, phase="end"
                )
                or raw_receipt.get("previous_receipt_sha256")
                != exact.begin.ledger_head_sha256
                or raw_receipt.get("receipt_sha256")
                != exact.broker_request_receipt_sha256
            )
        else:
            try:
                from app.services.tesseract_broker_protocol import (
                    request_receipt_manifest_from_mapping,
                )

                manifest = request_receipt_manifest_from_mapping(
                    raw_receipt_manifest
                )
            except Exception as error:
                raise ValueError(
                    "terminal request-control typed manifest differs"
                ) from error
            receipt_projection_differs = (
                not isinstance(receipt_blob, RequestControlReceiptBlobDescriptor)
                or manifest.request_id != exact.request_id
                or manifest.request_epoch != exact.request_epoch
                or manifest.request_sequence != exact.request_sequence
                or manifest.logical_phase != "request"
                or manifest.terminal_kind != "end"
                or manifest.receipt_sha256
                != exact.broker_request_receipt_sha256
                or receipt_blob.manifest_record_sha256
                != manifest.record_sha256
                or receipt_blob.receipt_sha256 != manifest.receipt_sha256
                or receipt_blob.receipt_blob_sha256
                != manifest.receipt_blob_sha256
                or receipt_blob.receipt_blob_bytes
                != manifest.receipt_blob_bytes
            )
        content_type_values = tuple(
            bytes.fromhex(item.value_hex)
            for item in response_witness.ordered_headers
            if bytes.fromhex(item.name_hex) == b"content-type"
        )
        if (
            replayed["request_sequence"] != exact.request_sequence
            or replayed["record_sha256s"]
            != (
                exact.request_control_arm_record_sha256,
                exact.request_control_begin_blocked_record_sha256,
                exact.request_control_begin_release_record_sha256,
                exact.request_control_end_blocked_record_sha256,
                exact.request_control_receipt_release_record_sha256,
                exact.request_control_result_record_sha256,
                exact.request_control_result_ack_record_sha256,
            )
            or replayed["transcript_row_sha256s"]
            != exact.request_control_transcript_row_sha256s
            or replayed["arm_binding"]
            != {
                "schema_id": "parser-broker-request-binding-v2",
                "method": exact.request_binding.method,
                "path": exact.request_binding.path,
                "query_sha256": exact.request_binding.query_sha256,
                "output_format": exact.request_binding.output_format,
                "source_sha256": exact.request_binding.source_sha256,
                "source_bytes": exact.request_binding.source_bytes,
                "safe_filename_sha256": (
                    exact.request_binding.safe_filename_sha256
                ),
                "upload_content_type_sha256": (
                    exact.request_binding.upload_content_type_sha256
                ),
            }
            or receipt_projection_differs
            or response_witness != exact.asgi_response_witness
            or response_witness.record_sha256
            != exact.asgi_response_witness_sha256
            or worker_result.asgi_response_witness_sha256
            != response_witness.record_sha256
            or worker_result.http_status_code != response_witness.status_code
            or response_witness.body_sha256 != worker_result.response_body_sha256
            or response_witness.body_bytes != worker_result.response_size_bytes
            or len(content_type_values) != 1
            or hashlib.sha256(content_type_values[0]).hexdigest()
            != worker_result.response_content_type_sha256
            or worker_result.attempt_id != exact.attempt_id
            or worker_result.request_id != exact.request_id
            or worker_result.request_index != exact.request_sequence
            or worker_result.request_epoch != exact.request_epoch
            or worker_result.source != source
            or worker_result.output != output
            or worker_result.broker_request_receipt_sha256
            != exact.broker_request_receipt_sha256
            or worker_result.request_binding_record_sha256
            != exact.request_binding.record_sha256
            or worker_result.materialized_at_monotonic_ns
            >= exact.request_deadline_monotonic_ns
        ):
            raise ValueError("terminal request-control request custody differs")


class TrustedLauncherIdentity(ContractModel):
    """Stable kernel identity of the watchdog that owns both managed roots."""

    pid: PositiveInt
    start_abstime: PositiveInt
    ppid: PositiveInt
    pgid: PositiveInt
    sid: PositiveInt
    uid: PositiveInt
    euid: PositiveInt

    @model_validator(mode="after")
    def validate_launcher(self) -> "TrustedLauncherIdentity":
        if self.pid != self.pgid or self.pid != self.sid:
            raise ValueError("trusted launcher must lead its fresh group/session")
        return self


class WorkerForkDenialEvidence(ContractModel):
    """Kernel and capability proof installed before parser imports."""

    schema_id: Literal["parser-fork-denied-worker-ready-v1"] = (
        "parser-fork-denied-worker-ready-v1"
    )
    platform_system: Literal["Darwin"] = "Darwin"
    effective_uid: PositiveInt
    real_uid: PositiveInt
    broker_effective_uid: PositiveInt
    broker_real_uid: PositiveInt
    non_root: Literal[True] = True
    installed_before_parser_import: Literal[True] = True
    hard_limit_before_first_app_import: Literal[True] = True
    hard_limit_installed_at_monotonic_ns: PositiveInt
    first_app_import_started_at_monotonic_ns: PositiveInt
    rlimit_nproc_soft: Literal[0] = 0
    rlimit_nproc_hard: Literal[0] = 0
    seatbelt_executable_sha256: Sha256
    seatbelt_profile_sha256: Sha256
    native_exec_guard_sha256: Sha256
    supervisor_capability_sha256: Sha256
    broker_protocol_sha256: Sha256
    broker_client_sha256: Sha256
    request_control_sha256: Sha256
    supervisor_sha256: Sha256
    broker_server_sha256: Sha256
    broker_native_sha256: Sha256
    broker_native_spawn_guard_source_sha256: Sha256
    broker_native_spawn_guard_library_sha256: Sha256
    native_runtime_gate_source_sha256: Sha256
    native_runtime_gate_library_sha256: Sha256
    native_runtime_gate_record_sha256: Sha256
    python_executable_sha256: Sha256
    watchdog_protocol_sha256: Sha256
    watchdog_ledger_schema_sha256: Sha256
    broker_profile_sha256: Sha256
    worker_profile_sha256: Sha256
    native_closure_sha256: Sha256
    native_trust_model: Literal["frozen-native-closure-trusted-v1"] = (
        "frozen-native-closure-trusted-v1"
    )
    native_containment_claim: Literal[
        "none-trusted-pinned-native-computation"
    ] = "none-trusted-pinned-native-computation"
    platform_release: Annotated[str, Field(min_length=1, max_length=256)]
    machine_architecture: Annotated[str, Field(min_length=1, max_length=256)]
    kernel_identity_sha256: Sha256
    native_fork_probe_source_sha256: Sha256
    native_fork_probe_library_sha256: Sha256
    native_fork_probe_device: NonNegativeInt
    native_fork_probe_inode: PositiveInt
    native_fork_probe_mode: PositiveInt
    native_fork_probe_uid: PositiveInt
    native_fork_probe_kind: Literal["pinned-darwin-c-vfork-safe-v1"] = (
        "pinned-darwin-c-vfork-safe-v1"
    )
    native_fork_probe_loaded_after_hard_limit: Literal[True] = True
    native_fork_probe_loaded_at_monotonic_ns: PositiveInt
    child_exec_guard_kind: Literal["python-source-same-pid-exec-v1"] = (
        "python-source-same-pid-exec-v1"
    )
    python_implementation: Annotated[str, Field(min_length=1, max_length=256)]
    python_version: Annotated[str, Field(min_length=1, max_length=256)]
    raw_fork_errno: PositiveInt
    raw_vfork_errno: PositiveInt
    raw_posix_spawn_errno: PositiveInt
    python_subprocess_errno: PositiveInt
    native_import_time_fork_errno: PositiveInt
    thread_creation_succeeded: Literal[True] = True
    worker: ExactProcessIdentity
    broker: ExactProcessIdentity
    one_to_one_broker_binding: Literal[True] = True
    launcher: TrustedLauncherIdentity
    controller_pid: PositiveInt
    controller_start_abstime: PositiveInt
    launcher_pid: PositiveInt
    launcher_start_abstime: PositiveInt
    worker_parent_is_launcher: Literal[True] = True
    broker_parent_is_launcher: Literal[True] = True
    capability_device: Annotated[int, Field(strict=True)]
    capability_inode: NonNegativeInt
    capability_family: PositiveInt
    capability_socket_type: PositiveInt
    capability_peer_binding: Literal[
        "supervisor-pass-fds-nonce-handshake-v1"
    ] = "supervisor-pass-fds-nonce-handshake-v1"
    request_control_device: Annotated[int, Field(strict=True)]
    request_control_inode: NonNegativeInt
    request_control_family: PositiveInt
    request_control_socket_type: PositiveInt
    request_control_peer_binding: Literal[
        "controller-pass-fds-transcript-v1"
    ] = "controller-pass-fds-transcript-v1"
    expected_request_count: PositiveInt
    worker_scratch_path_sha256: Sha256
    worker_scratch_device: PositiveInt
    worker_scratch_inode: PositiveInt
    worker_scratch_mode: Literal[0o700] = 0o700
    worker_scratch_uid: PositiveInt
    worker_tmpdir_bound: Literal[True] = True
    worker_scratch_root_empty_at_ready: Literal[True] = True
    installed_at_monotonic_ns: PositiveInt
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_fork_denial(self) -> "WorkerForkDenialEvidence":
        if self.effective_uid == 0:
            raise ValueError("root cannot claim authoritative RLIMIT_NPROC denial")
        if (
            stat.S_IFMT(self.native_fork_probe_mode) != stat.S_IFREG
            or self.native_fork_probe_mode & (stat.S_ISUID | stat.S_ISGID)
            or self.native_fork_probe_uid != self.effective_uid
            or self.hard_limit_installed_at_monotonic_ns
            > self.first_app_import_started_at_monotonic_ns
            or self.native_fork_probe_loaded_at_monotonic_ns
            < self.hard_limit_installed_at_monotonic_ns
            or self.native_fork_probe_loaded_at_monotonic_ns
            > self.installed_at_monotonic_ns
        ):
            raise ValueError("native fork-denial probe custody differs")
        if self.worker.role != "parser_worker" or self.broker.role != (
            "tesseract_broker"
        ):
            raise ValueError("fork-denial process roles differ")
        if self.worker.process_group_id == self.broker.process_group_id:
            raise ValueError("fork-denied worker and broker groups must differ")
        if (
            self.worker.parent_pid != self.launcher_pid
            or self.broker.parent_pid != self.launcher_pid
            or self.launcher.pid != self.launcher_pid
            or self.launcher.start_abstime != self.launcher_start_abstime
            or self.launcher.ppid != self.controller_pid
            or self.launcher.uid != self.real_uid
            or self.launcher.euid != self.effective_uid
            or self.broker_real_uid != self.real_uid
            or self.broker_effective_uid != self.effective_uid
            or self.launcher_pid == self.controller_pid
            or self.launcher_pid in {self.worker.pid, self.broker.pid}
        ):
            raise ValueError("fork-denial launcher parent binding differs")
        if self.worker_scratch_uid != self.effective_uid:
            raise ValueError("fork-denial worker scratch ownership differs")
        if self.capability_family != int(socket.AF_UNIX) or (
            self.capability_socket_type & 0xF
        ) != int(socket.SOCK_STREAM):
            raise ValueError("fork-denial broker capability kind differs")
        if self.request_control_family != int(socket.AF_UNIX) or (
            self.request_control_socket_type & 0xF
        ) != int(socket.SOCK_STREAM):
            raise ValueError("fork-denial request-control capability kind differs")
        accepted_denials = {1, 35}  # Darwin EPERM and EAGAIN.
        if any(
            value not in accepted_denials
            for value in (
                self.raw_fork_errno,
                self.raw_vfork_errno,
                self.raw_posix_spawn_errno,
                self.python_subprocess_errno,
                self.native_import_time_fork_errno,
            )
        ):
            raise ValueError("fork-denial probe returned an unexpected errno")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("fork-denial evidence identity differs")
        return self


def worker_fork_denial_evidence(**fields: object) -> WorkerForkDenialEvidence:
    """Create the exact app-protocol fork-denial evidence projection."""

    if "record_sha256" in fields:
        raise ValueError("fork-denial record identity is derived")
    provisional = WorkerForkDenialEvidence.model_construct(
        **fields, record_sha256="0" * 64
    )
    dumped = provisional.model_dump(mode="json", exclude={"record_sha256"})
    return WorkerForkDenialEvidence(
        **fields,
        record_sha256=_canonical_hash(dumped),  # type: ignore[arg-type]
    )


class LifecycleResourceEvidence(ContractModel):
    cold_initialization: ResourceSample
    prewarmed_idle: ResourceSample | None
    request_peak: ResourceSample
    repeated_request: ResourceSample
    shutdown: ResourceSample

    @model_validator(mode="after")
    def validate_phases_and_order(self) -> "LifecycleResourceEvidence":
        expected = (
            (self.cold_initialization, ResourcePhase.COLD_INITIALIZATION),
            (self.request_peak, ResourcePhase.REQUEST_PEAK),
            (self.repeated_request, ResourcePhase.REPEATED_REQUEST),
            (self.shutdown, ResourcePhase.SHUTDOWN),
        )
        for sample, phase in expected:
            if sample.phase is not phase:
                raise ValueError(f"{phase.value} resource phase differs")
        ordered = [self.cold_initialization]
        if self.prewarmed_idle is not None:
            if self.prewarmed_idle.phase is not ResourcePhase.PREWARMED_IDLE:
                raise ValueError("prewarmed idle resource phase differs")
            ordered.append(self.prewarmed_idle)
        ordered.extend((self.request_peak, self.repeated_request, self.shutdown))
        timestamps = tuple(item.observed_monotonic_ns for item in ordered)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("resource samples must be monotonic")
        return self


class ControllerResourceProcessSample(ContractModel):
    """One controller-read integral process sample in a request window."""

    role: Literal["parser_worker", "tesseract_broker", "tesseract_child"]
    pid: PositiveInt
    start_abstime: PositiveInt
    ppid: PositiveInt
    pgid: PositiveInt
    sid: PositiveInt
    sample_started_monotonic_ns: PositiveInt
    observed_monotonic_ns: PositiveInt
    sample_completed_monotonic_ns: PositiveInt
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt
    rss_bytes: NonNegativeInt
    thread_count: PositiveInt
    native_thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=4_096)
    ]
    file_descriptor_count: NonNegativeInt

    @model_validator(mode="after")
    def validate_threads(self) -> "ControllerResourceProcessSample":
        if (
            self.native_thread_ids != tuple(sorted(set(self.native_thread_ids)))
            or len(self.native_thread_ids) != self.thread_count
            or not (
                self.sample_started_monotonic_ns
                <= self.observed_monotonic_ns
                <= self.sample_completed_monotonic_ns
            )
        ):
            raise ValueError("controller resource process bracket/inventory differs")
        return self


class ControllerResourceAggregate(ContractModel):
    process_count: PositiveInt
    rss_bytes: NonNegativeInt
    thread_count: PositiveInt
    file_descriptor_count: NonNegativeInt


class ControllerChildWatchPrefix(ContractModel):
    size_bytes: NonNegativeInt
    sha256: Sha256
    broker_row_count: NonNegativeInt
    broker_head_sha256: Sha256
    record_blob_count: NonNegativeInt
    record_blob_size_bytes: NonNegativeInt
    record_blob_head_sha256: Sha256
    record_blob_root_sha256: Sha256
    event_count: NonNegativeInt
    event_blob_size_bytes: NonNegativeInt
    event_blob_root_sha256: Sha256
    event_head_sha256: Sha256
    open_registration_count: NonNegativeInt
    terminal_wait4_count: NonNegativeInt
    current_request_pre_exec_gated_sample_record_sha256s: Annotated[
        tuple[Sha256, ...], Field(max_length=4_096)
    ] = ()

    @model_validator(mode="after")
    def validate_gated_samples(self) -> "ControllerChildWatchPrefix":
        values = self.current_request_pre_exec_gated_sample_record_sha256s
        if values != tuple(
            sorted(set(values))
        ):
            raise ValueError("pre-exec gated sample identities differ")
        return self


def _child_watch_spawn_token(record: Mapping[str, object]) -> tuple[object, ...]:
    values = tuple(
        record.get(name)
        for name in (
            "request_id",
            "request_epoch",
            "request_sequence",
            "spawn_sequence",
            "spawn_nonce_sha256",
        )
    )
    request_id, request_epoch, request_sequence, spawn_sequence, nonce = values
    if (
        type(request_id) is not str
        or not request_id
        or len(request_id) > 256
        or any(
            type(value) is not int or value <= 0
            for value in (request_epoch, request_sequence, spawn_sequence)
        )
        or type(nonce) is not str
        or _SHA256.fullmatch(nonce) is None
    ):
        raise ValueError("child-watch spawn token differs")
    return values


def _child_watch_process_key(record: Mapping[str, object]) -> tuple[int, int]:
    pid = record.get("pid")
    start_abstime = record.get("start_abstime")
    if (
        type(pid) is not int
        or pid <= 0
        or type(start_abstime) is not int
        or start_abstime <= 0
    ):
        raise ValueError("child-watch process identity differs")
    return pid, start_abstime


def _child_watch_record_hash(
    record: Mapping[str, object], field: str
) -> str:
    retained = record.get(field)
    if type(retained) is not str or _SHA256.fullmatch(retained) is None:
        raise ValueError(f"child-watch {field} differs")
    projection = dict(record)
    projection.pop(field)
    if retained != hashlib.sha256(_semantic_json_bytes(projection)).hexdigest():
        raise ValueError(f"child-watch {field} identity differs")
    return retained


_CHILD_WATCH_TOKEN_FIELDS = (
    "request_id",
    "request_epoch",
    "request_sequence",
    "spawn_sequence",
    "spawn_nonce_sha256",
)
_CHILD_WATCH_PROCESS_FIELDS = (*_CHILD_WATCH_TOKEN_FIELDS, "pid", "start_abstime")
_CHILD_WATCH_NATIVE_ACK_FIELDS = (
    "native_child_limit_ack_authority",
    "native_child_limit_applied_clock_authority",
    "native_child_limit_ack_pid",
    "native_child_limit_applied_monotonic_ns",
    "native_child_limit_ack_sha256",
    "native_fork_parent_returned_monotonic_ns",
    "native_child_limit_acknowledged_monotonic_ns",
)


def _child_watch_exact_record(
    value: object, expected: set[str], label: str
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"child-watch {label} fields differ")
    return dict(value)


def _child_watch_token(record: Mapping[str, object]) -> tuple[object, ...]:
    token = tuple(record.get(name) for name in _CHILD_WATCH_TOKEN_FIELDS)
    request_id, epoch, sequence, spawn_sequence, nonce = token
    if (
        type(request_id) is not str
        or not request_id
        or type(epoch) is not int
        or epoch <= 0
        or type(sequence) is not int
        or sequence <= 0
        or epoch - sequence not in {0, 1, 2}
        or type(spawn_sequence) is not int
        or spawn_sequence <= 0
        or type(nonce) is not str
        or _SHA256.fullmatch(nonce) is None
    ):
        raise ValueError("child-watch spawn token differs")
    return token


def _child_watch_process(
    record: Mapping[str, object]
) -> tuple[object, ...]:
    token = _child_watch_token(record)
    pid = record.get("pid")
    start_abstime = record.get("start_abstime")
    if (
        type(pid) is not int
        or pid <= 0
        or type(start_abstime) is not int
        or start_abstime <= 0
    ):
        raise ValueError("child-watch process identity differs")
    return (*token, pid, start_abstime)


def _child_watch_sha_fields(
    record: Mapping[str, object], fields: tuple[str, ...]
) -> None:
    if any(
        type(record.get(field)) is not str
        or _SHA256.fullmatch(str(record.get(field))) is None
        for field in fields
    ):
        raise ValueError("child-watch digest field differs")


def _child_watch_native_ack(
    record: Mapping[str, object], *, provisional_monotonic_ns: int
) -> None:
    pid = record.get("pid")
    applied = record.get("native_child_limit_applied_monotonic_ns")
    parent_returned = record.get("native_fork_parent_returned_monotonic_ns")
    acknowledged = record.get("native_child_limit_acknowledged_monotonic_ns")
    if (
        type(pid) is not int
        or pid <= 0
        or record.get("native_child_limit_ack_authority")
        != "native-fixed-binary-pipe-PN0ACK1-big-endian-v1"
        or record.get("native_child_limit_applied_clock_authority")
        != "darwin-clock_gettime-CLOCK_MONOTONIC-nanoseconds-v1"
        or record.get("native_child_limit_ack_pid") != pid
        or type(applied) is not int
        or applied <= 0
        or type(parent_returned) is not int
        or parent_returned <= 0
        or type(acknowledged) is not int
        or acknowledged <= 0
        or parent_returned > acknowledged
        or acknowledged > provisional_monotonic_ns
        or record.get("native_child_limit_ack_sha256")
        != hashlib.sha256(
            struct.pack("!8sQQQQ", b"PN0ACK1!", pid, applied, 0, 0)
        ).hexdigest()
    ):
        raise ValueError("child-watch native limit ACK authority differs")


def _strict_child_watch_lineage(raw: bytes) -> dict[str, object]:
    """Replay the same one-way child lifecycle grammar as the live watcher."""

    stage = "idle"
    active: dict[str, object] = {}
    seen_tokens: set[tuple[object, ...]] = set()
    seen_processes: set[tuple[int, int]] = set()
    closed: list[dict[str, object]] = []

    def require_stage(expected: str, label: str) -> None:
        nonlocal stage
        if stage != expected:
            raise ValueError(f"child-watch {label} lifecycle order differs")

    def require_join(record: Mapping[str, object], *, process: bool = True) -> None:
        expected = active.get("process" if process else "token")
        observed = (
            _child_watch_process(record)
            if process
            else _child_watch_token(record)
        )
        if observed != expected:
            raise ValueError("child-watch lifecycle identity join differs")

    for line in raw.splitlines():
        parsed = json.loads(line)
        assert type(parsed) is dict
        schema_id = parsed.get("schema_id")
        kind = parsed.get("kind")
        if schema_id == "parser-tesseract-broker-ledger-row-v2":
            record = dict(parsed["record"])
            row_sha256 = str(parsed["row_sha256"])
            if kind == "spawn_intent":
                require_stage("idle", "spawn intent")
                record = _child_watch_exact_record(
                    record,
                    {
                        "schema_id",
                        *_CHILD_WATCH_TOKEN_FIELDS,
                        "broker_pid",
                        "broker_start_abstime",
                        "broker_pgid",
                        "broker_sid",
                        "child_deadline_monotonic_ns",
                        "broker_thread_count_before_fork",
                        "broker_thread_inventory_sha256",
                        "broker_thread_observed_at_monotonic_ns",
                        "intent_created_monotonic_ns",
                        "spawn_intent_sha256",
                    },
                    "spawn intent",
                )
                token = _child_watch_token(record)
                _child_watch_record_hash(record, "spawn_intent_sha256")
                _child_watch_sha_fields(
                    record,
                    (
                        "spawn_nonce_sha256",
                        "broker_thread_inventory_sha256",
                    ),
                )
                for field in (
                    "broker_pid",
                    "broker_start_abstime",
                    "broker_pgid",
                    "broker_sid",
                    "child_deadline_monotonic_ns",
                    "broker_thread_observed_at_monotonic_ns",
                    "intent_created_monotonic_ns",
                ):
                    if type(record[field]) is not int or int(record[field]) <= 0:
                        raise ValueError("child-watch spawn intent value differs")
                if (
                    record["schema_id"] != "parser-tesseract-spawn-intent-v1"
                    or record["broker_thread_count_before_fork"] != 1
                    or record["broker_pgid"] != record["broker_pid"]
                    or record["broker_sid"] != record["broker_pid"]
                    or int(record["broker_thread_observed_at_monotonic_ns"])
                    > int(record["intent_created_monotonic_ns"])
                    or int(record["intent_created_monotonic_ns"])
                    >= int(record["child_deadline_monotonic_ns"])
                    or token in seen_tokens
                ):
                    raise ValueError("child-watch spawn intent binding differs")
                seen_tokens.add(token)
                active = {
                    "token": token,
                    "spawn_intent": record,
                    "spawn_intent_row_sha256": row_sha256,
                }
                stage = "spawn_intent"
            elif kind == "child_provisional":
                require_stage("spawn_intent", "provisional")
                record = _child_watch_exact_record(
                    record,
                    {
                        "schema_id",
                        *_CHILD_WATCH_PROCESS_FIELDS,
                        "ppid",
                        "pgid",
                        "sid",
                        "spawn_intent_sha256",
                        "spawn_intent_ledger_row_sha256",
                        "broker_thread_count_immediately_before_fork",
                        "broker_thread_inventory_immediately_before_fork_sha256",
                        "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
                        "blocked_signals_across_fork",
                        "blocked_signals_across_fork_sha256",
                        "blockable_signals_masked_across_fork",
                        *_CHILD_WATCH_NATIVE_ACK_FIELDS,
                        "provisional_observed_monotonic_ns",
                        "provisional_record_sha256",
                    },
                    "provisional",
                )
                require_join(record, process=False)
                process = _child_watch_process(record)
                process_key = (int(record["pid"]), int(record["start_abstime"]))
                _child_watch_record_hash(record, "provisional_record_sha256")
                _child_watch_sha_fields(
                    record,
                    (
                        "spawn_intent_sha256",
                        "spawn_intent_ledger_row_sha256",
                        "broker_thread_inventory_immediately_before_fork_sha256",
                        "blocked_signals_across_fork_sha256",
                        "native_child_limit_ack_sha256",
                    ),
                )
                blocked = record["blocked_signals_across_fork"]
                _child_watch_native_ack(
                    record,
                    provisional_monotonic_ns=int(
                        record["provisional_observed_monotonic_ns"]
                    ),
                )
                if (
                    record["schema_id"]
                    != "parser-tesseract-child-provisional-v1"
                    or record["spawn_intent_sha256"]
                    != active["spawn_intent"]["spawn_intent_sha256"]
                    or record["spawn_intent_ledger_row_sha256"]
                    != active["spawn_intent_row_sha256"]
                    or record["ppid"] != active["spawn_intent"]["broker_pid"]
                    or record["pgid"] != active["spawn_intent"]["broker_pid"]
                    or record["sid"] != active["spawn_intent"]["broker_pid"]
                    or record["broker_thread_count_immediately_before_fork"] != 1
                    or record["broker_thread_inventory_immediately_before_fork_sha256"]
                    != active["spawn_intent"]["broker_thread_inventory_sha256"]
                    or type(blocked) is not list
                    or not blocked
                    or blocked != sorted(set(blocked))
                    or record["blocked_signals_across_fork_sha256"]
                    != _canonical_hash({"blocked_signals": blocked})
                    or record["blockable_signals_masked_across_fork"] is not True
                    or int(record["broker_thread_immediately_before_fork_observed_at_monotonic_ns"])
                    < int(active["spawn_intent"]["intent_created_monotonic_ns"])
                    or int(record["broker_thread_immediately_before_fork_observed_at_monotonic_ns"])
                    > int(record["provisional_observed_monotonic_ns"])
                    or int(record["provisional_observed_monotonic_ns"])
                    >= int(active["spawn_intent"]["child_deadline_monotonic_ns"])
                    or process_key in seen_processes
                ):
                    raise ValueError("child-watch provisional binding differs")
                seen_processes.add(process_key)
                active.update(
                    {
                        "process": process,
                        "provisional": record,
                        "provisional_row_sha256": row_sha256,
                    }
                )
                stage = "provisional"
            elif kind == "watchdog_register_ack":
                require_stage("registered", "register ACK")
                ack = dict(record)
                ack_sha = _child_watch_record_hash(ack, "watchdog_record_sha256")
                required = {
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "ppid",
                    "pgid",
                    "sid",
                    "spawn_intent_sha256",
                    "spawn_intent_ledger_row_sha256",
                    "provisional_child_ledger_row_sha256",
                    *_CHILD_WATCH_NATIVE_ACK_FIELDS,
                    "registration_sha256",
                    "watchdog_observed_monotonic_ns",
                    "watchdog_record_sha256",
                }
                if set(ack) != required:
                    raise ValueError("child-watch register ACK fields differ")
                require_join(ack)
                _child_watch_native_ack(
                    ack,
                    provisional_monotonic_ns=int(
                        active["provisional"]["provisional_observed_monotonic_ns"]
                    ),
                )
                if (
                    ack["registration_sha256"] != active["registration_sha256"]
                    or ack["spawn_intent_sha256"]
                    != active["spawn_intent"]["spawn_intent_sha256"]
                    or ack["spawn_intent_ledger_row_sha256"]
                    != active["spawn_intent_row_sha256"]
                    or ack["provisional_child_ledger_row_sha256"]
                    != active["provisional_row_sha256"]
                    or any(
                        ack[field] != active["registration"][field]
                        for field in _CHILD_WATCH_NATIVE_ACK_FIELDS
                    )
                    or int(ack["watchdog_observed_monotonic_ns"])
                    < int(
                        active["provisional"]["provisional_observed_monotonic_ns"]
                    )
                ):
                    raise ValueError("child-watch register ACK join differs")
                active.update(
                    {
                        "registration_ack_sha256": ack_sha,
                        "registration_ack_row_sha256": row_sha256,
                        "registration_ack": ack,
                    }
                )
                stage = "register_ack"
            elif kind == "child_intent":
                require_stage("register_ack", "child READY intent")
                record = _child_watch_exact_record(
                    record,
                    {
                        *_CHILD_WATCH_PROCESS_FIELDS,
                        "child_ready_sha256",
                        "spawn_intent_sha256",
                        "spawn_intent_ledger_row_sha256",
                        "provisional_child_ledger_row_sha256",
                        "provisional_record_sha256",
                        "watchdog_registration_sha256",
                        "watchdog_registration_ack_sha256",
                    },
                    "child READY intent",
                )
                require_join(record)
                _child_watch_sha_fields(
                    record,
                    (
                        "child_ready_sha256",
                        "spawn_intent_sha256",
                        "spawn_intent_ledger_row_sha256",
                        "provisional_child_ledger_row_sha256",
                        "provisional_record_sha256",
                        "watchdog_registration_sha256",
                        "watchdog_registration_ack_sha256",
                    ),
                )
                if (
                    record["watchdog_registration_sha256"]
                    != active["registration_sha256"]
                    or record["watchdog_registration_ack_sha256"]
                    != active["registration_ack_sha256"]
                    or record["spawn_intent_sha256"]
                    != active["spawn_intent"]["spawn_intent_sha256"]
                    or record["spawn_intent_ledger_row_sha256"]
                    != active["spawn_intent_row_sha256"]
                    or record["provisional_child_ledger_row_sha256"]
                    != active["provisional_row_sha256"]
                    or record["provisional_record_sha256"]
                    != active["provisional"]["provisional_record_sha256"]
                ):
                    raise ValueError("child-watch READY intent join differs")
                active.update(
                    {
                        "child_intent": record,
                        "child_intent_row_sha256": row_sha256,
                    }
                )
                stage = "child_intent"
            elif kind == "child_birth":
                require_stage("child_intent", "birth commitment")
                record = dict(record)
                required = {
                    "schema_id",
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "ppid",
                    "pgid",
                    "sid",
                    "broker_pid",
                    "broker_start_abstime",
                    "operation",
                    "logical_argv_sha256",
                    "actual_argv_sha256",
                    "environment_sha256",
                    "input_sha256",
                    "input_bytes",
                    "executable_sha256",
                    "watchdog_registration_sha256",
                    "watchdog_registration_ack_sha256",
                    "registration_acknowledged_monotonic_ns",
                    "broker_thread_count_before_fork",
                    "broker_thread_inventory_sha256",
                    "broker_thread_observed_at_monotonic_ns",
                    "broker_thread_count_immediately_before_fork",
                    "broker_thread_inventory_immediately_before_fork_sha256",
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
                    "blocked_signals_across_fork",
                    "blocked_signals_across_fork_sha256",
                    "blockable_signals_masked_across_fork",
                    "native_closure_sha256",
                    "native_trust_model",
                    "native_containment_claim",
                    "native_runtime_attestation_required",
                    "native_runtime_scan_interval_ns",
                    "child_ready_sha256",
                    "open_file_descriptors",
                    "open_fd_inventory_sha256",
                    "native_thread_count",
                    "native_thread_ids",
                    "native_thread_inventory_sha256",
                    "spawn_intent_sha256",
                    "spawn_intent_ledger_row_sha256",
                    "spawn_intent_durable_acknowledged_monotonic_ns",
                    "provisional_record_sha256",
                    "provisional_child_ledger_row_sha256",
                    "provisional_observed_monotonic_ns",
                    "child_ready_intent_ledger_row_sha256",
                    "guard_release_a_monotonic_ns",
                    "birth_commitment_sha256",
                }
                if set(record) != required:
                    raise ValueError("child-watch birth commitment fields differ")
                require_join(record)
                commitment_sha = _child_watch_record_hash(
                    record, "birth_commitment_sha256"
                )
                _child_watch_sha_fields(
                    record,
                    tuple(
                        field
                        for field in required
                        if field.endswith("sha256")
                    ),
                )
                if (
                    record["schema_id"]
                    != "parser-tesseract-child-birth-commitment-v1"
                    or record["watchdog_registration_sha256"]
                    != active["registration_sha256"]
                    or record["watchdog_registration_ack_sha256"]
                    != active["registration_ack_sha256"]
                    or record["child_ready_sha256"]
                    != active["child_intent"]["child_ready_sha256"]
                    or record["child_ready_intent_ledger_row_sha256"]
                    != active["child_intent_row_sha256"]
                    or record["spawn_intent_sha256"]
                    != active["spawn_intent"]["spawn_intent_sha256"]
                    or record["spawn_intent_ledger_row_sha256"]
                    != active["spawn_intent_row_sha256"]
                    or record["provisional_record_sha256"]
                    != active["provisional"]["provisional_record_sha256"]
                    or record["provisional_child_ledger_row_sha256"]
                    != active["provisional_row_sha256"]
                    or record["native_runtime_attestation_required"] is not True
                    or record["native_runtime_scan_interval_ns"] != 100_000_000
                    or record["native_trust_model"]
                    != "frozen-native-closure-trusted-v1"
                    or record["native_containment_claim"]
                    != "none-trusted-pinned-native-computation"
                    or record["broker_thread_count_before_fork"] != 1
                    or record["broker_thread_count_immediately_before_fork"] != 1
                    or record["broker_thread_inventory_immediately_before_fork_sha256"]
                    != record["broker_thread_inventory_sha256"]
                    or record["blockable_signals_masked_across_fork"] is not True
                ):
                    raise ValueError("child-watch birth commitment join differs")
                active.update(
                    {
                        "birth_commitment": record,
                        "birth_commitment_sha256": commitment_sha,
                        "birth_ledger_row_sha256": row_sha256,
                    }
                )
                stage = "birth_commitment"
            elif kind == "watchdog_birth_ack":
                require_stage("born", "birth ACK")
                ack = dict(record)
                ack_sha = _child_watch_record_hash(ack, "watchdog_record_sha256")
                required = {
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "registration_sha256",
                    "birth_record_sha256",
                    "watch_birth_sha256",
                    "watchdog_observed_monotonic_ns",
                    "watchdog_record_sha256",
                }
                if set(ack) != required:
                    raise ValueError("child-watch birth ACK fields differ")
                require_join(ack)
                if (
                    ack["registration_sha256"] != active["registration_sha256"]
                    or ack["birth_record_sha256"]
                    != active["birth_commitment_sha256"]
                    or ack["watch_birth_sha256"] != active["watch_birth_sha256"]
                ):
                    raise ValueError("child-watch birth ACK join differs")
                active.update(
                    {
                        "birth_ack_sha256": ack_sha,
                        "birth_ack_row_sha256": row_sha256,
                    }
                )
                stage = "birth_ack"
            elif kind == "child_exec_release":
                require_stage("birth_ack", "exec release")
                record = _child_watch_exact_record(
                    record,
                    {
                        *_CHILD_WATCH_PROCESS_FIELDS,
                        "birth_commitment_sha256",
                        "watchdog_birth_ack_sha256",
                        "exec_release_e_monotonic_ns",
                    },
                    "exec release",
                )
                require_join(record)
                if (
                    record["birth_commitment_sha256"]
                    != active["birth_commitment_sha256"]
                    or record["watchdog_birth_ack_sha256"]
                    != active["birth_ack_sha256"]
                    or type(record["exec_release_e_monotonic_ns"]) is not int
                    or int(record["exec_release_e_monotonic_ns"]) <= 0
                ):
                    raise ValueError("child-watch exec release join differs")
                active.update(
                    {
                        "exec_release": record,
                        "exec_release_row_sha256": row_sha256,
                    }
                )
                stage = "exec_release"
            elif kind == "child_wait4":
                require_stage("exec_release", "wait4")
                required = set(BrokerChildWait4Tombstone.model_fields)
                extra = set(record) - required
                if (
                    not required.issubset(record)
                    or extra not in ({"native_runtime_attestation"}, set())
                    or "native_runtime_attestation" not in record
                ):
                    raise ValueError("child-watch wait4 tombstone fields differ")
                require_join(record)
                _child_watch_record_hash(record, "record_sha256")
                if (
                    record["terminal_wait4_reap_count"] != 1
                    or record["direct_parent_waited"] is not True
                    or type(record.get("native_runtime_attestation")) is not dict
                ):
                    raise ValueError("child-watch wait4 tombstone join differs")
                active.update(
                    {
                        "tombstone": record,
                        "tombstone_record_sha256": record["record_sha256"],
                        "wait4_row_sha256": row_sha256,
                    }
                )
                stage = "wait4"
            elif kind == "watchdog_reaped_ack":
                require_stage("reaped", "reaped ACK")
                ack = dict(record)
                ack_sha = _child_watch_record_hash(ack, "watchdog_record_sha256")
                required = {
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "registration_sha256",
                    "tombstone_record_sha256",
                    "watchdog_observed_monotonic_ns",
                    "watchdog_record_sha256",
                }
                if set(ack) != required:
                    raise ValueError("child-watch reaped ACK fields differ")
                require_join(ack)
                if (
                    ack["registration_sha256"] != active["registration_sha256"]
                    or ack["tombstone_record_sha256"]
                    != active["tombstone_record_sha256"]
                ):
                    raise ValueError("child-watch reaped ACK join differs")
                active.update(
                    {
                        "reaped_ack_row_sha256": row_sha256,
                        "reaped_ack_sha256": ack_sha,
                    }
                )
                closed.append(dict(active))
                active = {}
                stage = "idle"
            elif stage != "idle":
                raise ValueError("child-watch lifecycle row interleaved")
        elif schema_id == "phase-latency-prewarm-child-watch-event-v1":
            payload = dict(parsed["payload"])
            if kind == "child_watch_register":
                require_stage("provisional", "registration")
                required = {
                    "attempt_nonce_sha256",
                    "scope_sha256",
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "ppid",
                    "pgid",
                    "sid",
                    "child_deadline_monotonic_ns",
                    "spawn_intent_sha256",
                    "spawn_intent_ledger_row_sha256",
                    "provisional_child_ledger_row_sha256",
                    *_CHILD_WATCH_NATIVE_ACK_FIELDS,
                    "registration_sha256",
                }
                if set(payload) != required:
                    raise ValueError("child-watch registration fields differ")
                require_join(payload)
                registration_sha = _child_watch_record_hash(
                    payload, "registration_sha256"
                )
                _child_watch_native_ack(
                    payload,
                    provisional_monotonic_ns=int(
                        active["provisional"]["provisional_observed_monotonic_ns"]
                    ),
                )
                if (
                    payload["spawn_intent_sha256"]
                    != active["spawn_intent"]["spawn_intent_sha256"]
                    or payload["spawn_intent_ledger_row_sha256"]
                    != active["spawn_intent_row_sha256"]
                    or payload["provisional_child_ledger_row_sha256"]
                    != active["provisional_row_sha256"]
                    or payload["ppid"] != active["provisional"]["ppid"]
                    or payload["pgid"] != active["provisional"]["pgid"]
                    or payload["sid"] != active["provisional"]["sid"]
                    or any(
                        payload[field] != active["provisional"][field]
                        for field in _CHILD_WATCH_NATIVE_ACK_FIELDS
                    )
                ):
                    raise ValueError("child-watch registration join differs")
                active.update(
                    {
                        "registration": payload,
                        "registration_sha256": registration_sha,
                        "registration_event_record_sha256": parsed["record_sha256"],
                    }
                )
                stage = "registered"
            elif kind == "child_watch_birth":
                require_stage("birth_commitment", "birth event")
                required = {
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "registration_sha256",
                    "birth_record_sha256",
                    "birth_ledger_row_sha256",
                    "released_monotonic_ns",
                    "executable_sha256",
                    "logical_argv_sha256",
                    "actual_argv_sha256",
                    "environment_sha256",
                    "native_closure_sha256",
                    "native_trust_model",
                    "native_containment_claim",
                    "native_runtime_attestation_required",
                    "native_runtime_scan_interval_ns",
                    "child_ready_sha256",
                    "open_file_descriptors",
                    "open_fd_inventory_sha256",
                    "native_thread_count",
                    "native_thread_ids",
                    "native_thread_inventory_sha256",
                    "broker_thread_count_immediately_before_fork",
                    "broker_thread_inventory_immediately_before_fork_sha256",
                    "broker_thread_immediately_before_fork_observed_at_monotonic_ns",
                    "blocked_signals_across_fork",
                    "blocked_signals_across_fork_sha256",
                    "blockable_signals_masked_across_fork",
                    "spawn_intent_sha256",
                    "spawn_intent_ledger_row_sha256",
                    "provisional_record_sha256",
                    "provisional_child_ledger_row_sha256",
                    "child_ready_intent_ledger_row_sha256",
                    "watch_birth_sha256",
                    "pre_exec_gated_child_sample",
                }
                if set(payload) != required:
                    raise ValueError("child-watch birth event fields differ")
                require_join(payload)
                watch_birth_sha = _child_watch_record_hash(
                    payload, "watch_birth_sha256"
                )
                sample = ControllerPreExecGatedChildSample.model_validate(
                    payload["pre_exec_gated_child_sample"]
                )
                commitment = active["birth_commitment"]
                if (
                    payload["registration_sha256"]
                    != active["registration_sha256"]
                    or payload["birth_record_sha256"]
                    != active["birth_commitment_sha256"]
                    or payload["birth_ledger_row_sha256"]
                    != active["birth_ledger_row_sha256"]
                    or sample.pid != payload["pid"]
                    or sample.start_abstime != payload["start_abstime"]
                    or sample.child_ready_sha256
                    != commitment["child_ready_sha256"]
                    or any(
                        payload[field] != commitment[field]
                        for field in (
                            "logical_argv_sha256",
                            "actual_argv_sha256",
                            "environment_sha256",
                            "native_closure_sha256",
                            "child_ready_sha256",
                            "open_file_descriptors",
                            "open_fd_inventory_sha256",
                            "native_thread_count",
                            "native_thread_ids",
                            "native_thread_inventory_sha256",
                            "spawn_intent_sha256",
                            "spawn_intent_ledger_row_sha256",
                            "provisional_record_sha256",
                            "provisional_child_ledger_row_sha256",
                            "child_ready_intent_ledger_row_sha256",
                        )
                    )
                ):
                    raise ValueError("child-watch birth event join differs")
                active.update(
                    {
                        "birth_event": payload,
                        "watch_birth_sha256": watch_birth_sha,
                        "pre_exec_gated_child_sample": sample,
                        "birth_event_record_sha256": parsed["record_sha256"],
                    }
                )
                stage = "born"
            elif kind == "child_watch_reaped":
                require_stage("wait4", "reaped event")
                required = {
                    *_CHILD_WATCH_PROCESS_FIELDS,
                    "registration_sha256",
                    "birth_record_sha256",
                    "tombstone_record_sha256",
                    "raw_wait_status",
                    "wait4_observed_monotonic_ns",
                    "tombstone_ledger_row_sha256",
                    "native_runtime_attestation_sha256",
                    "native_runtime_scan_log_sha256",
                    "native_closure_post_wait4_sha256",
                    "reaped_record_sha256",
                }
                if set(payload) != required:
                    raise ValueError("child-watch reaped event fields differ")
                require_join(payload)
                reaped_sha = _child_watch_record_hash(
                    payload, "reaped_record_sha256"
                )
                attestation = active["tombstone"]["native_runtime_attestation"]
                if (
                    payload["registration_sha256"]
                    != active["registration_sha256"]
                    or payload["birth_record_sha256"]
                    != active["birth_commitment_sha256"]
                    or payload["tombstone_record_sha256"]
                    != active["tombstone_record_sha256"]
                    or payload["raw_wait_status"]
                    != active["tombstone"]["raw_wait_status"]
                    or payload["wait4_observed_monotonic_ns"]
                    != active["tombstone"]["observed_monotonic_ns"]
                    or payload["tombstone_ledger_row_sha256"]
                    != active["wait4_row_sha256"]
                    or payload["native_runtime_attestation_sha256"]
                    != attestation.get("record_sha256")
                    or payload["native_runtime_scan_log_sha256"]
                    != attestation.get("scan_log_sha256")
                    or payload["native_closure_post_wait4_sha256"]
                    != attestation.get("static_closure_post_wait4_sha256")
                ):
                    raise ValueError("child-watch reaped event join differs")
                active.update(
                    {
                        "reaped_record_sha256": reaped_sha,
                        "reaped_event_record_sha256": parsed["record_sha256"],
                        "reaped_ack_sha256": None,
                    }
                )
                # The broker's following ACK row must carry this event ACK hash.
                active["reaped_ack_sha256"] = None
                stage = "reaped"
            else:
                raise ValueError("child-watch event kind differs")

            # Every event payload is itself hash-bound when the protocol defines
            # a final digest; the outer canonical event row was checked by the
            # ordinary replay above.
            if kind == "child_watch_reaped":
                active["reaped_ack_sha256"] = None
        else:
            raise ValueError("child-watch row schema differs")

        if stage == "reaped" and kind == "child_watch_reaped":
            # The watchdog ACK is not a distinct event row. Its digest is
            # retained in the next broker audit row, so the exact value is
            # learned there and validated by that row's self-hash.
            pass

    if stage != "idle" or active:
        raise ValueError("child-watch terminal lineage is incomplete")
    return {
        "closed_children": tuple(closed),
        "closed_child_count": len(closed),
    }


def _replay_child_watch_jsonl(
    raw: bytes,
    *,
    request_id: str | None = None,
    request_epoch: int | None = None,
    request_sequence: int | None = None,
) -> dict[str, object]:
    """Replay one exact, complete-line prefix of the watchdog-owned ledger."""

    if len(raw) > MAXIMUM_CHILD_WATCH_LOG_BYTES or (raw and not raw.endswith(b"\n")):
        raise ValueError("child-watch bytes are not a complete bounded prefix")
    selector_missing = (
        request_id is None,
        request_epoch is None,
        request_sequence is None,
    )
    if any(selector_missing) and not all(selector_missing):
        raise ValueError("child-watch request selector is incomplete")
    if request_id is not None and (
        not request_id
        or type(request_epoch) is not int
        or request_epoch <= 0
        or type(request_sequence) is not int
        or request_sequence <= 0
    ):
        raise ValueError("child-watch request selector differs")

    broker_count = 0
    broker_head = "0" * 64
    event_count = 0
    event_head = "0" * 64
    pending_intents: dict[tuple[object, ...], dict[str, object]] = {}
    pending_provisionals: dict[tuple[int, int], dict[str, object]] = {}
    spawn_token_by_key: dict[tuple[int, int], tuple[object, ...]] = {}
    registration_by_sha: dict[str, tuple[int, int]] = {}
    registration_by_key: dict[tuple[int, int], str] = {}
    open_registrations: set[str] = set()
    born_registrations: set[str] = set()
    terminal_wait4_keys: set[tuple[int, int]] = set()
    reaped_registrations: set[str] = set()
    gated_by_request: dict[tuple[object, ...], set[str]] = {}

    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("child-watch line is not JSON") from exc
        if type(parsed) is not dict or _semantic_json_bytes(parsed) != line:
            raise ValueError("child-watch line is not canonical JSON")
        value = dict(parsed)
        schema_id = value.get("schema_id")
        if schema_id == "parser-tesseract-broker-ledger-row-v2":
            from app.services.tesseract_broker_protocol import (
                BrokerProtocolError,
                broker_audit_row_from_mapping,
            )

            try:
                broker_audit_row_from_mapping(value)
            except BrokerProtocolError as error:
                raise ValueError("child-watch broker row fields differ") from error
            row_sha256 = value["row_sha256"]
            if (
                value["row_sequence"] != broker_count + 1
                or value["previous_row_sha256"] != broker_head
            ):
                raise ValueError("child-watch broker row chain differs")
            broker_count += 1
            broker_head = row_sha256
            kind = value["kind"]
            record = dict(value["record"])
            if kind == "spawn_intent":
                token = _child_watch_spawn_token(record)
                _child_watch_record_hash(record, "spawn_intent_sha256")
                if token in pending_intents:
                    raise ValueError("child-watch spawn intent was reused")
                pending_intents[token] = {
                    "record": record,
                    "row_sha256": row_sha256,
                }
            elif kind == "child_provisional":
                token = _child_watch_spawn_token(record)
                key = _child_watch_process_key(record)
                pending = pending_intents.pop(token, None)
                _child_watch_record_hash(record, "provisional_record_sha256")
                if (
                    pending is None
                    or key in pending_provisionals
                    or key in registration_by_key
                    or record.get("spawn_intent_sha256")
                    != pending["record"].get("spawn_intent_sha256")
                    or record.get("spawn_intent_ledger_row_sha256")
                    != pending["row_sha256"]
                ):
                    raise ValueError("child-watch provisional join differs")
                pending_provisionals[key] = {
                    "record": record,
                    "row_sha256": row_sha256,
                    "token": token,
                }
                spawn_token_by_key[key] = token
            elif kind == "child_wait4":
                token = _child_watch_spawn_token(record)
                key = _child_watch_process_key(record)
                _child_watch_record_hash(record, "record_sha256")
                registration_sha256 = registration_by_key.get(key)
                if (
                    registration_sha256 is None
                    or token != spawn_token_by_key.get(key)
                    or key in terminal_wait4_keys
                ):
                    raise ValueError("child-watch wait4 join differs")
                terminal_wait4_keys.add(key)
            elif kind not in {
                "quiescence",
                "thread_transfer",
                "begin_release",
                "request_match",
                "phase_terminal",
                "phase_release",
                "shutdown_immutable_inputs",
                "shutdown",
                "child_intent",
                "watchdog_register_ack",
                "child_birth",
                "watchdog_birth_ack",
                "child_exec_release",
                "watchdog_reaped_ack",
            }:
                raise ValueError("child-watch broker row kind differs")
        elif schema_id == "phase-latency-prewarm-child-watch-event-v1":
            if set(value) != {
                "schema_id",
                "event_sequence",
                "previous_event_sha256",
                "kind",
                "frame_sha256",
                "payload",
                "observed_monotonic_ns",
                "record_sha256",
            }:
                raise ValueError("child-watch event fields differ")
            record_sha256 = value.pop("record_sha256")
            if (
                type(record_sha256) is not str
                or _SHA256.fullmatch(record_sha256) is None
                or value["event_sequence"] != event_count + 1
                or value["previous_event_sha256"] != event_head
                or record_sha256
                != hashlib.sha256(_semantic_json_bytes(value)).hexdigest()
                or type(value["kind"]) is not str
                or type(value["payload"]) is not dict
            ):
                raise ValueError("child-watch event chain differs")
            event_count += 1
            event_head = record_sha256
            kind = value["kind"]
            payload = dict(value["payload"])
            if kind == "child_watch_register":
                token = _child_watch_spawn_token(payload)
                key = _child_watch_process_key(payload)
                registration_sha256 = payload.get("registration_sha256")
                if type(registration_sha256) is not str:
                    raise ValueError("child-watch registration identity differs")
                candidate = dict(payload)
                candidate.pop("registration_sha256", None)
                provisional = pending_provisionals.pop(key, None)
                if (
                    _SHA256.fullmatch(registration_sha256) is None
                    or registration_sha256
                    != hashlib.sha256(_semantic_json_bytes(candidate)).hexdigest()
                    or provisional is None
                    or token != provisional["token"]
                    or registration_sha256 in registration_by_sha
                    or key in registration_by_key
                ):
                    raise ValueError("child-watch registration join differs")
                registration_by_sha[registration_sha256] = key
                registration_by_key[key] = registration_sha256
                open_registrations.add(registration_sha256)
            elif kind == "child_watch_birth":
                registration_sha256 = payload.get("registration_sha256")
                if (
                    type(registration_sha256) is not str
                    or registration_sha256 not in open_registrations
                    or registration_sha256 in born_registrations
                ):
                    raise ValueError("child-watch birth registration differs")
                key = registration_by_sha[registration_sha256]
                sample = payload.get("pre_exec_gated_child_sample")
                if type(sample) is not dict:
                    raise ValueError("child-watch birth lacks gated sample")
                sample_value = dict(sample)
                sample_sha256 = sample_value.pop("record_sha256", None)
                if (
                    type(sample_sha256) is not str
                    or _SHA256.fullmatch(sample_sha256) is None
                    or sample_sha256
                    != hashlib.sha256(
                        _semantic_json_bytes(sample_value)
                    ).hexdigest()
                    or (
                        sample_value.get("pid"),
                        sample_value.get("start_abstime"),
                    )
                    != key
                    or sample_value.get("sampled_before_exec_release_e") is not True
                ):
                    raise ValueError("child-watch gated sample differs")
                request_key = _child_watch_spawn_token(payload)[:3]
                gated_by_request.setdefault(request_key, set()).add(sample_sha256)
                born_registrations.add(registration_sha256)
            elif kind == "child_watch_reaped":
                registration_sha256 = payload.get("registration_sha256")
                if (
                    type(registration_sha256) is not str
                    or registration_sha256 not in open_registrations
                    or registration_by_sha[registration_sha256]
                    not in terminal_wait4_keys
                    or registration_sha256 in reaped_registrations
                ):
                    raise ValueError("child-watch reaped join differs")
                open_registrations.remove(registration_sha256)
                reaped_registrations.add(registration_sha256)
            else:
                raise ValueError("child-watch event kind differs")
        else:
            raise ValueError("child-watch row schema differs")

    selector = (request_id, request_epoch, request_sequence)
    result = {
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "broker_row_count": broker_count,
        "broker_head_sha256": broker_head,
        "event_count": event_count,
        "event_head_sha256": event_head,
        "open_registration_count": len(open_registrations),
        "terminal_wait4_count": len(terminal_wait4_keys),
        "current_request_pre_exec_gated_sample_record_sha256s": tuple(
            sorted(gated_by_request.get(selector, set()))
        )
        if request_id is not None
        else (),
        "pending_spawn_intent_count": len(pending_intents),
        "pending_provisional_count": len(pending_provisionals),
        "registered_child_count": len(registration_by_sha),
        "born_child_count": len(born_registrations),
        "reaped_child_count": len(reaped_registrations),
        "pre_exec_gated_child_count": sum(
            len(values) for values in gated_by_request.values()
        ),
    }
    if request_id is None:
        result.update(_strict_child_watch_lineage(raw))
    return result


def _terminal_child_watch_bundle_replay(encoded: str) -> dict[str, object]:
    from app.services.tesseract_broker_protocol import (
        MAX_BROKER_AUDIT_BLOB_BYTES,
        BrokerProtocolError,
        canonical_sha256,
        replay_broker_audit_blob_bundle,
    )

    try:
        bundle_raw = base64.b64decode(encoded.encode("ascii"), validate=True)
        bundle = json.loads(bundle_raw.decode("ascii"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("terminal child-watch bundle encoding differs") from exc
    if (
        type(bundle) is not dict
        or _semantic_json_bytes(bundle) != bundle_raw
        or set(bundle) != {
            "schema_id", "compact_ledger_base64", "record_blob_root",
            "record_blobs", "event_blob_root", "event_blobs",
        }
        or bundle["schema_id"] != "phase-latency-child-watch-audit-bundle-v2"
        or type(bundle["record_blobs"]) is not list
        or type(bundle["event_blobs"]) is not list
    ):
        raise ValueError("terminal child-watch bundle fields differ")

    def decode_blobs(values: list[object], prefix: str) -> tuple[dict[str, bytes], dict[str, dict[str, int]]]:
        blobs: dict[str, bytes] = {}
        identities: dict[str, dict[str, int]] = {}
        for item in values:
            if type(item) is not dict or set(item) != {
                "name", "content_base64", "size_bytes", "sha256",
                "device", "inode", "mode", "uid", "nlink",
            }:
                raise ValueError("terminal child-watch blob fields differ")
            name = item["name"]
            try:
                content = base64.b64decode(
                    str(item["content_base64"]).encode("ascii"), validate=True
                )
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError("terminal child-watch blob encoding differs") from exc
            if (
                type(name) is not str
                or not name.startswith(prefix)
                or name in blobs
                or item["size_bytes"] != len(content)
                or item["sha256"] != hashlib.sha256(content).hexdigest()
                or not isinstance(item["device"], int)
                or not isinstance(item["inode"], int)
                or item["inode"] <= 0
                or not isinstance(item["mode"], int)
                or not stat.S_ISREG(item["mode"])
                or stat.S_IMODE(item["mode"]) != 0o600
                or not isinstance(item["uid"], int)
                or item["uid"] < 0
                or item["nlink"] != 1
            ):
                raise ValueError("terminal child-watch blob identity differs")
            blobs[name] = content
            identities[name] = {
                key: int(item[key])
                for key in ("device", "inode", "mode", "uid", "nlink")
            }
        if sum(map(len, blobs.values())) > MAX_BROKER_AUDIT_BLOB_BYTES:
            raise ValueError("terminal child-watch blob aggregate differs")
        return blobs, identities

    try:
        compact = base64.b64decode(
            str(bundle["compact_ledger_base64"]).encode("ascii"), validate=True
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("terminal child-watch compact ledger encoding differs") from exc
    record_blobs, record_identities = decode_blobs(bundle["record_blobs"], "r")
    event_blobs, event_identities = decode_blobs(bundle["event_blobs"], "e")
    try:
        replay = replay_broker_audit_blob_bundle(
            compact_ledger=compact,
            record_blobs=record_blobs,
            event_blobs=event_blobs,
        )
    except BrokerProtocolError as exc:
        raise ValueError("terminal child-watch bundle replay differs") from exc

    def require_root(value: object, schema_id: str) -> dict[str, object]:
        if type(value) is not dict or set(value) != {
            "schema_id", "resolved_path", "device", "inode", "mode", "uid",
            "nlink", "entry_count", "aggregate_bytes", "head_sha256",
            "record_sha256",
        }:
            raise ValueError("terminal child-watch blob root fields differ")
        root = dict(value)
        digest = root.pop("record_sha256")
        if (
            root["schema_id"] != schema_id
            or type(root["resolved_path"]) is not str
            or not os.path.isabs(root["resolved_path"])
            or not isinstance(root["device"], int)
            or not isinstance(root["inode"], int)
            or root["inode"] <= 0
            or not isinstance(root["mode"], int)
            or not stat.S_ISDIR(root["mode"])
            or stat.S_IMODE(root["mode"]) != 0o700
            or not isinstance(root["uid"], int)
            or root["uid"] < 0
            or not isinstance(root["nlink"], int)
            or root["nlink"] < 2
            or digest != canonical_sha256(root)
        ):
            raise ValueError("terminal child-watch blob root identity differs")
        root["record_sha256"] = digest
        return root

    record_root = require_root(
        bundle["record_blob_root"],
        "parser-tesseract-broker-audit-record-blob-root-v1",
    )
    event_root = require_root(
        bundle["event_blob_root"],
        "parser-tesseract-watch-event-blob-root-v1",
    )
    previous_blob_sha256 = "0" * 64
    for row in replay["rows"]:
        name = f"r{row['row_sequence']:08d}-{row['record_sha256'][:16]}.json"
        identity = record_identities[name]
        blob = {
            "schema_id": "parser-tesseract-broker-audit-record-blob-v1",
            "row_sequence": row["row_sequence"],
            "kind": row["kind"],
            "record_bytes": row["record_bytes"],
            "record_sha256": row["record_sha256"],
            "resolved_path": str(Path(str(record_root["resolved_path"])) / name),
            **identity,
            "previous_blob_record_sha256": previous_blob_sha256,
        }
        previous_blob_sha256 = canonical_sha256(blob)
    if (
        record_root["entry_count"] != replay["record_blob_count"]
        or record_root["aggregate_bytes"] != replay["record_blob_size_bytes"]
        or record_root["head_sha256"] != previous_blob_sha256
        or event_root["entry_count"] != replay["event_count"]
        or event_root["aggregate_bytes"] != replay["event_blob_size_bytes"]
        or event_root["head_sha256"] != replay["event_head_sha256"]
    ):
        raise ValueError("terminal child-watch blob root aggregate differs")
    merged_raw = b"".join(
        _semantic_json_bytes(entry) + b"\n"
        for entry in replay["merged_entries"]
    )
    semantic = _replay_child_watch_jsonl(merged_raw)
    return {
        "bundle_raw": bundle_raw,
        "bundle": bundle,
        "compact": compact,
        "record_blobs": record_blobs,
        "record_identities": record_identities,
        "event_blobs": event_blobs,
        "event_identities": event_identities,
        "record_root": record_root,
        "event_root": event_root,
        "replay": replay,
        "semantic": semantic,
    }


class TerminalChildWatchLogEvidence(ContractModel):
    """Closed compact ledger plus every O_EXCL broker/event record blob."""

    schema_id: Literal["phase-latency-terminal-child-watch-log-v2"] = (
        "phase-latency-terminal-child-watch-log-v2"
    )
    encoding: Literal["canonical-audit-bundle-json-base64-v2"] = (
        "canonical-audit-bundle-json-base64-v2"
    )
    canonical_bundle_base64: str
    bundle_size_bytes: PositiveInt
    bundle_sha256: Sha256
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=4_194_304)]
    sha256: Sha256
    broker_row_count: PositiveInt
    broker_head_sha256: Sha256
    record_blob_count: PositiveInt
    record_blob_size_bytes: PositiveInt
    record_blob_head_sha256: Sha256
    record_blob_root_sha256: Sha256
    event_count: NonNegativeInt
    event_blob_size_bytes: NonNegativeInt
    event_blob_root_sha256: Sha256
    event_head_sha256: Sha256
    registered_child_count: NonNegativeInt
    born_child_count: NonNegativeInt
    terminal_wait4_count: NonNegativeInt
    reaped_child_count: NonNegativeInt
    pre_exec_gated_child_count: NonNegativeInt
    pending_spawn_intent_count: Literal[0] = 0
    pending_provisional_count: Literal[0] = 0
    open_registration_count: Literal[0] = 0
    file_device: NonNegativeInt
    file_inode: PositiveInt
    file_mode: Literal[0o600] = 0o600
    file_uid: NonNegativeInt
    file_nlink: Literal[1] = 1
    o_excl_created: Literal[True] = True
    fsynced_before_close: Literal[True] = True
    reopened_no_follow_after_fsync: Literal[True] = True
    record_sha256: Sha256

    def _decoded(self) -> dict[str, object]:
        return _terminal_child_watch_bundle_replay(self.canonical_bundle_base64)

    def raw_bytes(self) -> bytes:
        return self._decoded()["compact"]  # type: ignore[return-value]

    @model_validator(mode="after")
    def validate_terminal_log(self) -> "TerminalChildWatchLogEvidence":
        decoded = self._decoded()
        replay = decoded["replay"]
        semantic = decoded["semantic"]
        record_root = decoded["record_root"]
        event_root = decoded["event_root"]
        expected = (
            len(decoded["bundle_raw"]), hashlib.sha256(decoded["bundle_raw"]).hexdigest(),
            replay["compact_ledger_size_bytes"], replay["compact_ledger_sha256"],
            replay["broker_row_count"], replay["broker_head_sha256"],
            replay["record_blob_count"], replay["record_blob_size_bytes"],
            record_root["head_sha256"], record_root["record_sha256"],
            replay["event_count"], replay["event_blob_size_bytes"],
            event_root["record_sha256"], replay["event_head_sha256"],
            semantic["registered_child_count"], semantic["born_child_count"],
            semantic["terminal_wait4_count"], semantic["reaped_child_count"],
            semantic["pre_exec_gated_child_count"],
            semantic["pending_spawn_intent_count"],
            semantic["pending_provisional_count"], semantic["open_registration_count"],
        )
        retained = (
            self.bundle_size_bytes, self.bundle_sha256, self.size_bytes, self.sha256,
            self.broker_row_count, self.broker_head_sha256, self.record_blob_count,
            self.record_blob_size_bytes, self.record_blob_head_sha256,
            self.record_blob_root_sha256, self.event_count,
            self.event_blob_size_bytes, self.event_blob_root_sha256,
            self.event_head_sha256, self.registered_child_count,
            self.born_child_count, self.terminal_wait4_count,
            self.reaped_child_count, self.pre_exec_gated_child_count,
            self.pending_spawn_intent_count, self.pending_provisional_count,
            self.open_registration_count,
        )
        if expected != retained:
            raise ValueError("terminal child-watch replay differs")
        if not (
            self.registered_child_count == self.born_child_count
            == self.terminal_wait4_count == self.reaped_child_count
            == self.pre_exec_gated_child_count == semantic["closed_child_count"]
        ):
            raise ValueError("terminal child-watch lineage did not close")
        if self.record_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"record_sha256"})
        ):
            raise ValueError("terminal child-watch evidence identity differs")
        return self


def terminal_child_watch_log_evidence(
    raw: bytes,
    *,
    file_device: int,
    file_inode: int,
    file_uid: int,
    record_blob_root: Mapping[str, object],
    record_blobs: Mapping[str, bytes],
    record_blob_identities: Mapping[str, Mapping[str, int]],
    event_blob_root: Mapping[str, object],
    event_blobs: Mapping[str, bytes],
    event_blob_identities: Mapping[str, Mapping[str, int]],
) -> TerminalChildWatchLogEvidence:
    blob_entry_keys = ("device", "inode", "mode", "uid", "nlink")
    def entries(
        blobs: Mapping[str, bytes],
        identities: Mapping[str, Mapping[str, int]],
    ) -> list[dict[str, object]]:
        if set(blobs) != set(identities):
            raise ValueError("terminal child-watch blob inventory differs")
        return [
            {
                "name": name,
                "content_base64": base64.b64encode(blobs[name]).decode("ascii"),
                "size_bytes": len(blobs[name]),
                "sha256": hashlib.sha256(blobs[name]).hexdigest(),
                **{key: identities[name][key] for key in blob_entry_keys},
            }
            for name in sorted(blobs)
        ]
    bundle = {
        "schema_id": "phase-latency-child-watch-audit-bundle-v2",
        "compact_ledger_base64": base64.b64encode(raw).decode("ascii"),
        "record_blob_root": dict(record_blob_root),
        "record_blobs": entries(record_blobs, record_blob_identities),
        "event_blob_root": dict(event_blob_root),
        "event_blobs": entries(event_blobs, event_blob_identities),
    }
    bundle_raw = _semantic_json_bytes(bundle)
    encoded = base64.b64encode(bundle_raw).decode("ascii")
    decoded = _terminal_child_watch_bundle_replay(encoded)
    replay = decoded["replay"]
    semantic = decoded["semantic"]
    fields = {
        "schema_id": "phase-latency-terminal-child-watch-log-v2",
        "encoding": "canonical-audit-bundle-json-base64-v2",
        "canonical_bundle_base64": encoded,
        "bundle_size_bytes": len(bundle_raw),
        "bundle_sha256": hashlib.sha256(bundle_raw).hexdigest(),
        "size_bytes": replay["compact_ledger_size_bytes"],
        "sha256": replay["compact_ledger_sha256"],
        "broker_row_count": replay["broker_row_count"],
        "broker_head_sha256": replay["broker_head_sha256"],
        "record_blob_count": replay["record_blob_count"],
        "record_blob_size_bytes": replay["record_blob_size_bytes"],
        "record_blob_head_sha256": record_blob_root["head_sha256"],
        "record_blob_root_sha256": record_blob_root["record_sha256"],
        "event_count": replay["event_count"],
        "event_blob_size_bytes": replay["event_blob_size_bytes"],
        "event_blob_root_sha256": event_blob_root["record_sha256"],
        "event_head_sha256": replay["event_head_sha256"],
        "registered_child_count": semantic["registered_child_count"],
        "born_child_count": semantic["born_child_count"],
        "terminal_wait4_count": semantic["terminal_wait4_count"],
        "reaped_child_count": semantic["reaped_child_count"],
        "pre_exec_gated_child_count": semantic["pre_exec_gated_child_count"],
        "pending_spawn_intent_count": semantic["pending_spawn_intent_count"],
        "pending_provisional_count": semantic["pending_provisional_count"],
        "open_registration_count": semantic["open_registration_count"],
        "file_device": file_device, "file_inode": file_inode,
        "file_mode": 0o600, "file_uid": file_uid, "file_nlink": 1,
        "o_excl_created": True, "fsynced_before_close": True,
        "reopened_no_follow_after_fsync": True,
    }
    return TerminalChildWatchLogEvidence(
        **fields, record_sha256=_canonical_hash(fields)  # type: ignore[arg-type]
    )


def _terminal_shutdown_immutable_input_observation(
    terminal: TerminalChildWatchLogEvidence,
) -> dict[str, object]:
    from app.services.tesseract_broker_protocol import (
        BrokerProtocolError,
        immutable_input_observation_from_mapping,
    )

    retained: list[dict[str, object]] = []
    for row in terminal._decoded()["replay"]["rows"]:
        if row.get("kind") != "shutdown_immutable_inputs":
            continue
        try:
            record = immutable_input_observation_from_mapping(
                row.get("record")
            )
        except BrokerProtocolError as error:
            raise ValueError(
                "shutdown immutable-input observation differs"
            ) from error
        retained.append(record)
    if len(retained) != 1:
        raise ValueError("shutdown immutable-input observation count differs")
    return retained[0]


def _terminal_child_watch_semantic_raw(
    terminal: TerminalChildWatchLogEvidence,
) -> bytes:
    """Reconstruct the canonical semantic row/event stream from v2 blobs."""

    return b"".join(
        _semantic_json_bytes(entry) + b"\n"
        for entry in terminal._decoded()["replay"]["merged_entries"]
    )


def require_terminal_child_watch_prefix(
    terminal: TerminalChildWatchLogEvidence,
    prefix: ControllerChildWatchPrefix,
    *,
    request_id: str,
    request_epoch: int,
    request_sequence: int,
) -> None:
    from app.services.tesseract_broker_protocol import (
        BROKER_AUDIT_COMMITMENT_BYTES,
        canonical_sha256,
        replay_broker_audit_blob_bundle,
    )

    decoded = terminal._decoded()
    raw = decoded["compact"]
    if (
        prefix.size_bytes > len(raw)
        or prefix.size_bytes % BROKER_AUDIT_COMMITMENT_BYTES
    ):
        raise ValueError("controller child-watch prefix is not a complete bounded prefix")
    actual_broker_row_count = prefix.size_bytes // BROKER_AUDIT_COMMITMENT_BYTES
    full_replay = decoded["replay"]
    prefix_rows = full_replay["rows"][:actual_broker_row_count]
    record_names = {
        f"r{row['row_sequence']:08d}-{row['record_sha256'][:16]}.json"
        for row in prefix_rows
    }
    event_names = tuple(sorted(decoded["event_blobs"]))[: prefix.event_count]
    try:
        replay = replay_broker_audit_blob_bundle(
            compact_ledger=raw[: prefix.size_bytes],
            record_blobs={
                name: decoded["record_blobs"][name] for name in record_names
            },
            event_blobs={
                name: decoded["event_blobs"][name] for name in event_names
            },
        )
    except (KeyError, ValueError, RuntimeError) as exc:
        raise ValueError("controller child-watch prefix does not replay") from exc
    merged_raw = b"".join(
        _semantic_json_bytes(entry) + b"\n"
        for entry in replay["merged_entries"]
    )
    semantic = _replay_child_watch_jsonl(
        merged_raw,
        request_id=request_id,
        request_epoch=request_epoch,
        request_sequence=request_sequence,
    )
    previous_blob_sha256 = "0" * 64
    record_root = dict(decoded["record_root"])
    for row in replay["rows"]:
        name = f"r{row['row_sequence']:08d}-{row['record_sha256'][:16]}.json"
        identity = decoded["record_identities"][name]
        blob = {
            "schema_id": "parser-tesseract-broker-audit-record-blob-v1",
            "row_sequence": row["row_sequence"], "kind": row["kind"],
            "record_bytes": row["record_bytes"],
            "record_sha256": row["record_sha256"],
            "resolved_path": str(Path(str(record_root["resolved_path"])) / name),
            **identity,
            "previous_blob_record_sha256": previous_blob_sha256,
        }
        previous_blob_sha256 = canonical_sha256(blob)
    record_root.update(
        entry_count=replay["record_blob_count"],
        aggregate_bytes=replay["record_blob_size_bytes"],
        head_sha256=previous_blob_sha256,
    )
    record_root.pop("record_sha256", None)
    record_root_sha256 = canonical_sha256(record_root)
    event_root = dict(decoded["event_root"])
    event_root.update(
        entry_count=replay["event_count"],
        aggregate_bytes=replay["event_blob_size_bytes"],
        head_sha256=replay["event_head_sha256"],
    )
    event_root.pop("record_sha256", None)
    event_root_sha256 = canonical_sha256(event_root)
    expected = ControllerChildWatchPrefix(
        size_bytes=replay["compact_ledger_size_bytes"],
        sha256=replay["compact_ledger_sha256"],
        broker_row_count=replay["broker_row_count"],
        broker_head_sha256=replay["broker_head_sha256"],
        record_blob_count=replay["record_blob_count"],
        record_blob_size_bytes=replay["record_blob_size_bytes"],
        record_blob_head_sha256=previous_blob_sha256,
        record_blob_root_sha256=record_root_sha256,
        event_count=replay["event_count"],
        event_blob_size_bytes=replay["event_blob_size_bytes"],
        event_blob_root_sha256=event_root_sha256,
        event_head_sha256=replay["event_head_sha256"],
        open_registration_count=semantic["open_registration_count"],
        terminal_wait4_count=semantic["terminal_wait4_count"],
        current_request_pre_exec_gated_sample_record_sha256s=semantic[
            "current_request_pre_exec_gated_sample_record_sha256s"
        ],
    )
    if prefix != expected:
        raise ValueError("controller child-watch prefix does not replay")


class ControllerPreExecGatedChildSample(ContractModel):
    """Watchdog-owned exact child observation before exec gate E opens."""

    schema_id: Literal["phase-latency-pre-exec-gated-child-sample-v1"] = (
        "phase-latency-pre-exec-gated-child-sample-v1"
    )
    pid: PositiveInt
    start_abstime: PositiveInt
    ppid: PositiveInt
    pgid: PositiveInt
    sid: PositiveInt
    observed_monotonic_ns: PositiveInt
    user_cpu_ns: NonNegativeInt
    system_cpu_ns: NonNegativeInt
    rss_bytes: NonNegativeInt
    thread_count: Literal[1] = 1
    file_descriptor_count: Literal[6] = 6
    native_thread_ids: Annotated[
        tuple[PositiveInt, ...], Field(min_length=1, max_length=1)
    ]
    open_fd_inventory_sha256: Sha256
    native_thread_inventory_sha256: Sha256
    child_ready_sha256: Sha256
    sampled_before_exec_release_e: Literal[True] = True
    record_sha256: Sha256

    @model_validator(mode="after")
    def validate_sample(self) -> "ControllerPreExecGatedChildSample":
        if (
            self.native_thread_ids
            != tuple(sorted(set(self.native_thread_ids)))
            or self.record_sha256
            != _canonical_hash(
                self.model_dump(mode="json", exclude={"record_sha256"})
            )
        ):
            raise ValueError("pre-exec gated child sample identity differs")
        return self


def controller_pre_exec_gated_child_sample(
    **fields: object,
) -> ControllerPreExecGatedChildSample:
    if "record_sha256" in fields:
        raise ValueError("pre-exec gated sample identity is derived")
    provisional = ControllerPreExecGatedChildSample.model_construct(
        **fields, record_sha256="0" * 64
    )
    return ControllerPreExecGatedChildSample(
        **fields,
        record_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"record_sha256"})
        ),  # type: ignore[arg-type]
    )


class ControllerRequestResourceSample(ContractModel):
    """Closed raw sampler payload retained by the controller."""

    schema_id: Literal["phase-latency-controller-resource-sample-v1"] = (
        "phase-latency-controller-resource-sample-v1"
    )
    attempt_id: StableId
    request_id: Annotated[str, Field(min_length=1, max_length=256)]
    request_epoch: PositiveInt
    request_sequence: PositiveInt
    observed_monotonic_ns: PositiveInt
    sweep_started_monotonic_ns: PositiveInt
    sweep_completed_monotonic_ns: PositiveInt
    sweep_span_ns: NonNegativeInt
    maximum_sweep_span_ns: Literal[PEAK_SAMPLE_EDGE_TOLERANCE_NS] = (
        PEAK_SAMPLE_EDGE_TOLERANCE_NS
    )
    sample_order: Literal[
        "worker-root-broker-root-registered-children-v1"
    ] = "worker-root-broker-root-registered-children-v1"
    boundary_membership: Literal[
        "coverage_only", "boundary_begin", "boundary_interior", "boundary_end"
    ]
    processes: Annotated[
        tuple[ControllerResourceProcessSample, ...],
        Field(min_length=2, max_length=4_098),
    ]
    aggregate: ControllerResourceAggregate
    child_watch_prefix: ControllerChildWatchPrefix

    @model_validator(mode="after")
    def validate_sample(self) -> "ControllerRequestResourceSample":
        if self.request_epoch != self.request_sequence + 1:
            raise ValueError("controller resource request epoch differs")
        if (
            self.processes[0].role != "parser_worker"
            or self.processes[1].role != "tesseract_broker"
            or any(item.role != "tesseract_child" for item in self.processes[2:])
        ):
            raise ValueError("controller resource process order differs")
        identities = tuple(
            (item.pid, item.start_abstime) for item in self.processes
        )
        if (
            len(identities) != len(set(identities))
            or identities[2:] != tuple(sorted(identities[2:]))
        ):
            raise ValueError("controller resource identities differ")
        worker, broker = self.processes[:2]
        if (
            worker.pid != worker.pgid
            or worker.pid != worker.sid
            or broker.pid != broker.pgid
            or broker.pid != broker.sid
            or worker.pgid == broker.pgid
            or any(
                (item.ppid, item.pgid, item.sid)
                != (broker.pid, broker.pgid, broker.sid)
                for item in self.processes[2:]
            )
        ):
            raise ValueError("controller resource lineage differs")
        expected_aggregate = (
            len(self.processes),
            sum(item.rss_bytes for item in self.processes),
            sum(item.thread_count for item in self.processes),
            sum(item.file_descriptor_count for item in self.processes),
        )
        retained_aggregate = (
            self.aggregate.process_count,
            self.aggregate.rss_bytes,
            self.aggregate.thread_count,
            self.aggregate.file_descriptor_count,
        )
        sweep_started = min(
            item.sample_started_monotonic_ns for item in self.processes
        )
        sweep_completed = max(
            item.sample_completed_monotonic_ns for item in self.processes
        )
        sweep_span = sweep_completed - sweep_started
        if (
            retained_aggregate != expected_aggregate
            or self.observed_monotonic_ns != sweep_completed
            or self.sweep_started_monotonic_ns != sweep_started
            or self.sweep_completed_monotonic_ns != sweep_completed
            or self.sweep_span_ns != sweep_span
            or sweep_span > self.maximum_sweep_span_ns
        ):
            raise ValueError("controller resource sweep/aggregate differs")
        return self


class ControllerResourceSampleLogRow(ContractModel):
    """One complete fsynced JSONL row; its digest is independently derived."""

    schema_id: Literal["phase-latency-controller-resource-sample-row-v1"] = (
        "phase-latency-controller-resource-sample-row-v1"
    )
    row_sequence: PositiveInt
    previous_row_sha256: Sha256
    kind: Literal["controller-resource-sample"] = "controller-resource-sample"
    record: ControllerRequestResourceSample
    retained_monotonic_ns: PositiveInt
    row_sha256: Sha256

    @model_validator(mode="after")
    def validate_row(self) -> "ControllerResourceSampleLogRow":
        if self.retained_monotonic_ns < self.record.observed_monotonic_ns:
            raise ValueError("controller resource row predates its observation")
        if self.row_sha256 != _canonical_hash(
            self.model_dump(mode="json", exclude={"row_sha256"})
        ):
            raise ValueError("controller resource row identity differs")
        return self


def controller_resource_sample_log_row(
    **fields: object,
) -> ControllerResourceSampleLogRow:
    if "row_sha256" in fields:
        raise ValueError("controller resource row identity is derived")
    provisional = ControllerResourceSampleLogRow.model_construct(
        **fields, row_sha256="0" * 64
    )
    return ControllerResourceSampleLogRow(
        **fields,
        row_sha256=_canonical_hash(
            provisional.model_dump(mode="json", exclude={"row_sha256"})
        ),  # type: ignore[arg-type]
    )


class RequestResourceBoundary(ContractModel):
    boundary_started_monotonic_ns: NonNegativeInt
    boundary_ended_monotonic_ns: PositiveInt
    self_user_cpu_delta_ns: NonNegativeInt
    self_system_cpu_delta_ns: NonNegativeInt
    reaped_child_user_cpu_delta_ns: NonNegativeInt
    reaped_child_system_cpu_delta_ns: NonNegativeInt
    live_descendant_user_cpu_delta_ns: NonNegativeInt
    live_descendant_system_cpu_delta_ns: NonNegativeInt
    live_descendant_process_count: NonNegativeInt
    total_cpu_delta_ns: NonNegativeInt
    host_logical_cpu_count: PositiveInt
    wall_cpu_capacity_ns: PositiveInt
    descendant_peak_process_count: PositiveInt
    descendant_peak_rss_bytes: PositiveInt
    process_tree_peak_thread_count: PositiveInt
    process_tree_peak_file_descriptor_count: NonNegativeInt
    cpu_before: ProcessCpuSnapshot | None = None
    cpu_after: ProcessCpuSnapshot | None = None
    exact_broker_cpu: ExactBrokerRequestCpuEvidence | None = None
    controller_resource_sample_rows: Annotated[
        tuple[ControllerResourceSampleLogRow, ...],
        Field(max_length=MAXIMUM_CONTROLLER_RESOURCE_SAMPLES),
    ] = ()
    cpu_accounting_basis: Literal[
        "rusage-self-reaped-plus-identity-keyed-live-descendants-v1",
        "fork-denied-worker-broker-self-plus-exact-wait4-v2",
    ] = "rusage-self-reaped-plus-identity-keyed-live-descendants-v1"
    sampled_concurrently: StrictBool
    descendant_sample_count: NonNegativeInt = 0
    descendant_first_sample_monotonic_ns: NonNegativeInt | None = None
    descendant_last_sample_monotonic_ns: NonNegativeInt | None = None
    descendant_maximum_gap_ns: NonNegativeInt | None = None
    descendant_target_interval_ns: PositiveInt | None = None
    descendant_edge_tolerance_ns: PositiveInt | None = None
    request_boundary_covered: StrictBool = False
    sampled_late: StrictBool = False
    cumulative_contamination_detected: StrictBool = False

    @model_validator(mode="after")
    def validate_boundary(self) -> "RequestResourceBoundary":
        wall_ns = (
            self.boundary_ended_monotonic_ns
            - self.boundary_started_monotonic_ns
        )
        if wall_ns <= 0:
            raise ValueError("request CPU boundary must be positive")
        if self.cpu_accounting_basis == (
            "fork-denied-worker-broker-self-plus-exact-wait4-v2"
        ):
            exact = self.exact_broker_cpu
            if exact is None or self.cpu_before is not None or self.cpu_after is not None:
                raise ValueError("CPU-v2 requires only exact broker CPU evidence")
            if any(
                (
                    self.self_user_cpu_delta_ns,
                    self.self_system_cpu_delta_ns,
                    self.reaped_child_user_cpu_delta_ns,
                    self.reaped_child_system_cpu_delta_ns,
                    self.live_descendant_user_cpu_delta_ns,
                    self.live_descendant_system_cpu_delta_ns,
                    self.live_descendant_process_count,
                )
            ):
                raise ValueError("CPU-v2 cannot populate legacy aggregate fields")
            in_boundary_timestamps = (
                exact.worker_before.observed_monotonic_ns,
                exact.end.observed_monotonic_ns,
                exact.worker_after.observed_monotonic_ns,
                exact.broker_after.observed_monotonic_ns,
                exact.begin_release_monotonic_ns,
            )
            if any(
                value < self.boundary_started_monotonic_ns
                or value > self.boundary_ended_monotonic_ns
                for value in in_boundary_timestamps
            ):
                raise ValueError("exact broker CPU samples escaped request boundary")
            if (
                self.boundary_started_monotonic_ns
                != exact.worker_before.observed_monotonic_ns
                or self.boundary_ended_monotonic_ns
                != exact.worker_after.observed_monotonic_ns
                or exact.begin.observed_monotonic_ns
                > self.boundary_started_monotonic_ns
                or exact.broker_before.observed_monotonic_ns
                > self.boundary_started_monotonic_ns
                or exact.receipt_release_monotonic_ns
                <= self.boundary_ended_monotonic_ns
            ):
                raise ValueError("exact broker CPU wall-edge binding differs")
            if exact.end.observed_monotonic_ns < max(
                exact.worker_before.observed_monotonic_ns,
                exact.broker_before.observed_monotonic_ns,
            ):
                raise ValueError("exact broker END ACK predates BEGIN samples")
            if self.total_cpu_delta_ns != exact.total_cpu_delta_ns:
                raise ValueError("request CPU-v2 total differs from exact evidence")
            child_peak_rss = max(
                (
                    item.tombstone.maximum_resident_set_bytes
                    for item in exact.children
                ),
                default=0,
            )
            if self.descendant_peak_rss_bytes < child_peak_rss:
                raise ValueError("request peak RSS omits a wait4 child maximum")
            if self.cumulative_contamination_detected:
                raise ValueError("successful CPU-v2 evidence cannot be contaminated")
            if self.wall_cpu_capacity_ns != wall_ns * self.host_logical_cpu_count:
                raise ValueError("request wall/CPU capacity must be recomputed")
            rows = self.controller_resource_sample_rows
            if len(rows) < 2:
                raise ValueError("CPU-v2 lacks raw controller resource rows")
            row_sequences = tuple(item.row_sequence for item in rows)
            if row_sequences != tuple(
                range(row_sequences[0], row_sequences[0] + len(rows))
            ) or any(
                later.previous_row_sha256 != earlier.row_sha256
                for earlier, later in zip(rows, rows[1:], strict=False)
            ):
                raise ValueError("controller resource row chain differs")
            if any(
                row.record.attempt_id != exact.attempt_id
                or row.record.request_id != exact.request_id
                or row.record.request_epoch != exact.request_epoch
                or row.record.request_sequence != exact.request_sequence
                for row in rows
            ):
                raise ValueError("controller resource row crossed a request")
            row_intervals = tuple(
                (
                    row.record.sweep_started_monotonic_ns,
                    row.record.sweep_completed_monotonic_ns,
                )
                for row in rows
            )
            if any(
                later_start < earlier_completed
                for (_, earlier_completed), (later_start, _) in zip(
                    row_intervals, row_intervals[1:], strict=False
                )
            ):
                raise ValueError("controller resource rows are not monotonic")
            prefixes = tuple(row.record.child_watch_prefix for row in rows)
            if prefixes[0].current_request_pre_exec_gated_sample_record_sha256s:
                raise ValueError("controller child prefix did not reset per request")
            for earlier, later in zip(prefixes, prefixes[1:], strict=False):
                if (
                    later.size_bytes < earlier.size_bytes
                    or later.broker_row_count < earlier.broker_row_count
                    or later.event_count < earlier.event_count
                    or later.terminal_wait4_count < earlier.terminal_wait4_count
                ):
                    raise ValueError("controller child-watch prefix regressed")
                if (later.size_bytes == earlier.size_bytes) != (
                    later.sha256 == earlier.sha256
                ):
                    raise ValueError("controller child-watch byte prefix differs")
                for earlier_count, later_count, earlier_head, later_head in (
                    (
                        earlier.broker_row_count,
                        later.broker_row_count,
                        earlier.broker_head_sha256,
                        later.broker_head_sha256,
                    ),
                    (
                        earlier.event_count,
                        later.event_count,
                        earlier.event_head_sha256,
                        later.event_head_sha256,
                    ),
                ):
                    if (later_count == earlier_count) != (
                        later_head == earlier_head
                    ):
                        raise ValueError("controller child-watch chain head differs")
                earlier_gated = set(
                    earlier.current_request_pre_exec_gated_sample_record_sha256s
                )
                later_gated = set(
                    later.current_request_pre_exec_gated_sample_record_sha256s
                )
                if not earlier_gated.issubset(later_gated):
                    raise ValueError("current-request gated sample prefix regressed")
            boundary_rows = tuple(
                row
                for row in rows
                if row.record.boundary_membership != "coverage_only"
            )
            if len(boundary_rows) < 2:
                raise ValueError("controller resource boundary coverage is insufficient")
            memberships = tuple(
                row.record.boundary_membership for row in boundary_rows
            )
            if (
                memberships[0] != "boundary_begin"
                or memberships[-1] != "boundary_end"
                or any(
                    value != "boundary_interior" for value in memberships[1:-1]
                )
            ):
                raise ValueError("controller resource boundary grammar differs")
            for row in boundary_rows:
                worker_sample, broker_sample = row.record.processes[:2]
                if (
                    (
                        worker_sample.pid,
                        worker_sample.start_abstime,
                        worker_sample.ppid,
                        worker_sample.pgid,
                        worker_sample.sid,
                    )
                    != (
                        exact.begin.worker.pid,
                        exact.begin.worker.start_abstime,
                        exact.begin.worker.parent_pid,
                        exact.begin.worker.process_group_id,
                        exact.begin.worker.session_id,
                    )
                    or (
                        broker_sample.pid,
                        broker_sample.start_abstime,
                        broker_sample.ppid,
                        broker_sample.pgid,
                        broker_sample.sid,
                    )
                    != (
                        exact.begin.broker.pid,
                        exact.begin.broker.start_abstime,
                        exact.begin.broker.parent_pid,
                        exact.begin.broker.process_group_id,
                        exact.begin.broker.session_id,
                    )
                ):
                    raise ValueError("controller resource root identity differs")
            sampled_identities = {
                (item.pid, item.start_abstime): SampledProcessIdentity(
                    role=item.role,
                    pid=item.pid,
                    start_abstime=item.start_abstime,
                    parent_pid=item.ppid,
                    process_group_id=item.pgid,
                    session_id=item.sid,
                )
                for row in boundary_rows
                for item in row.record.processes
            }
            for sample in exact.pre_exec_gated_child_samples:
                sampled_identities[(sample.pid, sample.start_abstime)] = (
                    SampledProcessIdentity(
                        role="tesseract_child",
                        pid=sample.pid,
                        start_abstime=sample.start_abstime,
                        parent_pid=sample.ppid,
                        process_group_id=sample.pgid,
                        session_id=sample.sid,
                    )
                )
            ordered_sampled_identities = tuple(
                sampled_identities[key] for key in sorted(sampled_identities)
            )
            if ordered_sampled_identities != exact.sampled_process_identities:
                raise ValueError("controller resource sampled identity set differs")
            birth_keys = {
                (item.birth.pid, item.birth.start_abstime)
                for item in exact.children
            }
            gated_keys = {
                (item.pid, item.start_abstime)
                for item in exact.pre_exec_gated_child_samples
            }
            gated_sha256s = tuple(
                sorted(
                    item.record_sha256
                    for item in exact.pre_exec_gated_child_samples
                )
            )
            retained_gated_sha256s = {
                value
                for row in boundary_rows
                for value in row.record.child_watch_prefix.current_request_pre_exec_gated_sample_record_sha256s
            }
            if (
                gated_keys != birth_keys
                or retained_gated_sha256s != set(gated_sha256s)
                or boundary_rows[-1]
                .record.child_watch_prefix.current_request_pre_exec_gated_sample_record_sha256s
                != gated_sha256s
            ):
                raise ValueError("controller resource rows omit a broker child")
            boundary_intervals = tuple(
                (
                    row.record.sweep_started_monotonic_ns,
                    row.record.sweep_completed_monotonic_ns,
                )
                for row in boundary_rows
            )
            maximum_gap_ns = max(
                later_start - earlier_completed
                for (_, earlier_completed), (later_start, _) in zip(
                    boundary_intervals,
                    boundary_intervals[1:],
                    strict=False,
                )
            )
            expected_peak_processes = max(
                max(row.record.aggregate.process_count for row in boundary_rows),
                2 + (1 if exact.pre_exec_gated_child_samples else 0),
            )
            root_rss_at_begin = (
                exact.begin_external_sample.worker_sample.rss_bytes
                + exact.begin_external_sample.broker_sample.rss_bytes
            )
            expected_peak_rss = max(
                max(row.record.aggregate.rss_bytes for row in boundary_rows),
                child_peak_rss,
                *(
                    root_rss_at_begin + item.rss_bytes
                    for item in exact.pre_exec_gated_child_samples
                ),
            )
            root_threads_at_begin = (
                exact.begin_external_sample.worker_sample.thread_count
                + exact.begin_external_sample.broker_sample.thread_count
            )
            expected_peak_threads = max(
                max(
                    row.record.aggregate.thread_count for row in boundary_rows
                ),
                0,
                *(
                    root_threads_at_begin + item.thread_count
                    for item in exact.pre_exec_gated_child_samples
                ),
            )
            root_fds_at_begin = (
                exact.begin_external_sample.worker_sample.file_descriptor_count
                + exact.begin_external_sample.broker_sample.file_descriptor_count
            )
            expected_peak_fds = max(
                max(
                    row.record.aggregate.file_descriptor_count
                    for row in boundary_rows
                ),
                0,
                *(
                    root_fds_at_begin + item.file_descriptor_count
                    for item in exact.pre_exec_gated_child_samples
                ),
            )
            if (
                self.descendant_peak_process_count != expected_peak_processes
                or self.descendant_peak_rss_bytes != expected_peak_rss
                or self.process_tree_peak_thread_count != expected_peak_threads
                or self.process_tree_peak_file_descriptor_count != expected_peak_fds
                or self.descendant_sample_count != len(boundary_rows)
                or self.descendant_first_sample_monotonic_ns
                != boundary_intervals[0][0]
                or self.descendant_last_sample_monotonic_ns
                != boundary_intervals[-1][1]
                or self.descendant_maximum_gap_ns != maximum_gap_ns
            ):
                raise ValueError("controller resource aggregates must be recomputed")
            sampling_values = (
                self.descendant_first_sample_monotonic_ns,
                self.descendant_last_sample_monotonic_ns,
                self.descendant_maximum_gap_ns,
                self.descendant_target_interval_ns,
                self.descendant_edge_tolerance_ns,
            )
            if self.descendant_sample_count == 0:
                if any(value is not None for value in sampling_values):
                    raise ValueError("empty descendant sampling cannot retain coverage")
                if self.request_boundary_covered:
                    raise ValueError("empty descendant sampling cannot cover a request")
            else:
                if any(value is None for value in sampling_values):
                    raise ValueError("descendant sampling coverage is incomplete")
                assert self.descendant_first_sample_monotonic_ns is not None
                assert self.descendant_last_sample_monotonic_ns is not None
                if (
                    self.descendant_sample_count < 2
                    or self.descendant_first_sample_monotonic_ns
                    > self.descendant_last_sample_monotonic_ns
                ):
                    raise ValueError("descendant sampling coverage is insufficient")
                assert self.descendant_edge_tolerance_ns is not None
                if (
                    self.descendant_first_sample_monotonic_ns
                    > self.boundary_started_monotonic_ns
                    + self.descendant_edge_tolerance_ns
                    or self.descendant_last_sample_monotonic_ns
                    < self.boundary_ended_monotonic_ns
                    - self.descendant_edge_tolerance_ns
                ):
                    raise ValueError("controller resource rows do not cover both edges")
                if not self.request_boundary_covered:
                    raise ValueError("controller resource rows must cover the request")
            return self
        if self.controller_resource_sample_rows:
            raise ValueError("legacy CPU-v1 cannot retain controller resource rows")
        if self.exact_broker_cpu is not None:
            raise ValueError("legacy CPU-v1 cannot retain broker CPU-v2 evidence")
        if self.cpu_before is None or self.cpu_after is None:
            raise ValueError("legacy CPU-v1 requires both cumulative snapshots")
        if not (
            self.boundary_started_monotonic_ns
            <= self.cpu_before.observed_monotonic_ns
            <= self.cpu_after.observed_monotonic_ns
            <= self.boundary_ended_monotonic_ns
        ):
            raise ValueError("CPU snapshots must be inside the request boundary")
        before_root = self.cpu_before.members[0]
        after_root = self.cpu_after.members[0]
        if (before_root.pid, before_root.create_time_ns) != (
            after_root.pid,
            after_root.create_time_ns,
        ):
            raise ValueError("request CPU root identity changed")

        cumulative_pairs = (
            (
                self.cpu_before.rusage_self_user_cpu_ns,
                self.cpu_after.rusage_self_user_cpu_ns,
                self.self_user_cpu_delta_ns,
            ),
            (
                self.cpu_before.rusage_self_system_cpu_ns,
                self.cpu_after.rusage_self_system_cpu_ns,
                self.self_system_cpu_delta_ns,
            ),
            (
                self.cpu_before.rusage_reaped_child_user_cpu_ns,
                self.cpu_after.rusage_reaped_child_user_cpu_ns,
                self.reaped_child_user_cpu_delta_ns,
            ),
            (
                self.cpu_before.rusage_reaped_child_system_cpu_ns,
                self.cpu_after.rusage_reaped_child_system_cpu_ns,
                self.reaped_child_system_cpu_delta_ns,
            ),
        )
        counter_regression = False
        for before_value, after_value, retained_delta in cumulative_pairs:
            if after_value < before_value:
                counter_regression = True
            if retained_delta != max(0, after_value - before_value):
                raise ValueError("RUSAGE CPU delta must be recomputed")

        before_descendants = {
            (item.pid, item.create_time_ns): item
            for item in self.cpu_before.members[1:]
        }
        after_descendants = {
            (item.pid, item.create_time_ns): item
            for item in self.cpu_after.members[1:]
        }
        disappeared = set(before_descendants) - set(after_descendants)
        live_user_delta = 0
        live_system_delta = 0
        live_regression = False
        for identity, after_counter in after_descendants.items():
            before_counter = before_descendants.get(identity)
            before_user = before_counter.user_cpu_ns if before_counter else 0
            before_system = before_counter.system_cpu_ns if before_counter else 0
            if (
                after_counter.user_cpu_ns < before_user
                or after_counter.system_cpu_ns < before_system
            ):
                live_regression = True
            live_user_delta += max(0, after_counter.user_cpu_ns - before_user)
            live_system_delta += max(
                0, after_counter.system_cpu_ns - before_system
            )
        if self.live_descendant_user_cpu_delta_ns != live_user_delta or (
            self.live_descendant_system_cpu_delta_ns != live_system_delta
        ):
            raise ValueError("live-descendant CPU delta must be recomputed per process")
        if self.live_descendant_process_count != len(after_descendants):
            raise ValueError("live-descendant CPU process count differs")
        expected_contamination = bool(
            counter_regression or live_regression or disappeared
        )
        if self.cumulative_contamination_detected != expected_contamination:
            raise ValueError("request CPU contamination claim must be recomputed")

        expected_cpu = sum(
            (
                self.self_user_cpu_delta_ns,
                self.self_system_cpu_delta_ns,
                self.reaped_child_user_cpu_delta_ns,
                self.reaped_child_system_cpu_delta_ns,
                self.live_descendant_user_cpu_delta_ns,
                self.live_descendant_system_cpu_delta_ns,
            )
        )
        if self.total_cpu_delta_ns != expected_cpu:
            raise ValueError("request CPU total must be recomputed")
        if self.wall_cpu_capacity_ns != wall_ns * self.host_logical_cpu_count:
            raise ValueError("request wall/CPU capacity must be recomputed")
        sampling_values = (
            self.descendant_first_sample_monotonic_ns,
            self.descendant_last_sample_monotonic_ns,
            self.descendant_maximum_gap_ns,
            self.descendant_target_interval_ns,
            self.descendant_edge_tolerance_ns,
        )
        if self.descendant_sample_count == 0:
            if any(value is not None for value in sampling_values):
                raise ValueError("empty descendant sampling cannot retain coverage")
            if self.request_boundary_covered:
                raise ValueError("empty descendant sampling cannot cover a request")
        else:
            if any(value is None for value in sampling_values):
                raise ValueError("descendant sampling coverage is incomplete")
            assert self.descendant_first_sample_monotonic_ns is not None
            assert self.descendant_last_sample_monotonic_ns is not None
            if (
                self.descendant_sample_count < 2
                or self.descendant_first_sample_monotonic_ns
                > self.descendant_last_sample_monotonic_ns
            ):
                raise ValueError("descendant sampling coverage is insufficient")
        return self


class RequestObservation(ContractModel):
    request_index: PositiveInt
    latency_ns: NonNegativeInt
    status: AttemptStatus
    output: OutputIdentity | None
    failure: FailureRecord | None
    resource_boundary: RequestResourceBoundary | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "RequestObservation":
        if self.status is AttemptStatus.SUCCESS:
            if self.output is None or self.failure is not None or self.latency_ns <= 0:
                raise ValueError("successful request outcome is incomplete")
        elif self.failure is None or self.output is not None:
            raise ValueError("failed request must retain one failure and no output")
        return self


class CleanupEvidence(ContractModel):
    shutdown_duration_ns: NonNegativeInt
    cleanup_completed: StrictBool
    worker_exited: StrictBool
    worker_reaped: StrictBool
    exit_code: int | None
    owned_process_count_after_shutdown: NonNegativeInt
    all_owned_processes_reaped: StrictBool
    threads_returned_to_baseline: StrictBool
    file_descriptors_returned_to_baseline: StrictBool
    state_retention_detected: StrictBool
    oom_observed: StrictBool
    unbounded_rss_growth_observed: StrictBool
    worker_process_group_count: Literal[1] = 1
    broker_process_group_count: NonNegativeInt = 0
    controller_watchdog_process_group_count: NonNegativeInt = 0
    owned_process_group_count: PositiveInt = 1

    @model_validator(mode="after")
    def validate_claims(self) -> "CleanupEvidence":
        if self.all_owned_processes_reaped != (
            self.owned_process_count_after_shutdown == 0
        ):
            raise ValueError("owned-process cleanup claim differs")
        if self.worker_reaped and not self.worker_exited:
            raise ValueError("reaped worker must have exited")
        if self.owned_process_group_count != (
            self.worker_process_group_count
            + self.broker_process_group_count
            + self.controller_watchdog_process_group_count
        ):
            raise ValueError("owned process-group total must be recomputed")
        if self.cleanup_completed and not (
            self.worker_exited and self.worker_reaped and self.all_owned_processes_reaped
        ):
            raise ValueError("complete cleanup claim lacks process closure")
        return self


class WorkerMeasurementEnvelope(ContractModel):
    """Bounded worker-to-runner payload; it is not acceptance evidence alone."""

    schema_id: Literal["phase-latency-prewarm-worker-envelope-v1"]
    case_id: StableId
    mode: RunMode
    source: SourceIdentity
    startup_duration_ns: NonNegativeInt
    shutdown_duration_ns: NonNegativeInt = 0
    application_identity_validated: StrictBool
    dependency_identity_validated: StrictBool
    parser_runtime_identity_validated: StrictBool
    runtime_artifact_identity_validated: StrictBool
    configuration_identity_validated: StrictBool
    converter_identity_validated: StrictBool
    ready_after_identity_validation: StrictBool
    prewarm_completed: StrictBool
    requests: Annotated[
        tuple[RequestObservation, ...], Field(max_length=MAXIMUM_REQUESTS_PER_ATTEMPT)
    ]
    resources: LifecycleResourceEvidence
    state_retention_detected: StrictBool
    production_asgi_lifespan_exercised: StrictBool = False
    network_isolation_validated: StrictBool = False
    runtime_before_requests_sha256: Sha256 | None = None
    runtime_after_requests_sha256: Sha256 | None = None
    runtime_after_shutdown_sha256: Sha256 | None = None
    runtime_artifact_before_requests: FileTreeIdentityEvidence | None = None
    runtime_artifact_after_shutdown: FileTreeIdentityEvidence | None = None
    fork_denial_evidence: WorkerForkDenialEvidence | None = None
    request_control_readiness: RequestControlReadinessEvidence | None = None
    terminal_request_control_transcript: (
        TerminalRequestControlTranscriptEvidence | None
    ) = None
    kernel_sandbox_evidence: KernelSandboxEvidence | None = None
    immutable_runtime_input_custody: (
        ImmutableRuntimeInputCustodyEvidence | None
    ) = None
    startup_broker_receipt: BrokerLifecycleReceiptEvidence | None = None
    shutdown_broker_receipt: BrokerLifecycleReceiptEvidence | None = None
    oom_observed: StrictBool = False
    unbounded_rss_growth_observed: StrictBool = False
    concurrent_descendant_sampling_validated: StrictBool = False
    controller_resource_sample_log_sha256: Sha256 | None = None
    controller_resource_sample_log_row_count: NonNegativeInt | None = None
    controller_resource_sample_log_size_bytes: NonNegativeInt | None = None
    terminal_child_watch_log: TerminalChildWatchLogEvidence | None = None
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    rss_disposition: Literal["owner_deferred_observational"] = RSS_DISPOSITION
    strict_rss_gate_pass_claimed: Literal[False] = False

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _stable_id(value, label="case_id")

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "WorkerMeasurementEnvelope":
        if self.case_id != self.source.case_id:
            raise ValueError("worker case/source identity differs")
        indexes = tuple(item.request_index for item in self.requests)
        if indexes != tuple(range(1, len(indexes) + 1)):
            raise ValueError("request indexes must be complete and ordered")
        identities_valid = all(
            (
                self.dependency_identity_validated,
                self.application_identity_validated,
                self.parser_runtime_identity_validated,
                self.runtime_artifact_identity_validated,
                self.configuration_identity_validated,
                self.converter_identity_validated,
            )
        )
        if self.ready_after_identity_validation and not identities_valid:
            raise ValueError("worker cannot become ready before exact validation")
        if self.mode is RunMode.ENABLED:
            if not self.prewarm_completed or self.resources.prewarmed_idle is None:
                raise ValueError("enabled worker lacks completed prewarm evidence")
        elif self.prewarm_completed or self.resources.prewarmed_idle is not None:
            raise ValueError("predecessor worker cannot claim prewarming")
        if self.production_asgi_lifespan_exercised:
            if (
                self.runtime_artifact_before_requests is None
                or self.runtime_artifact_after_shutdown is None
            ):
                raise ValueError("production worker lacks artifact boundary custody")
            if (
                self.runtime_artifact_before_requests
                != self.runtime_artifact_after_shutdown
            ):
                raise ValueError("runtime artifact changed across the ASGI lifecycle")
            if self.fork_denial_evidence is None:
                raise ValueError("production worker lacks kernel fork-denial evidence")
            if self.request_control_readiness is None:
                raise ValueError("production worker lacks request-control readiness")
            if self.terminal_request_control_transcript is None:
                raise ValueError(
                    "production worker lacks terminal request-control bytes"
                )
            if self.immutable_runtime_input_custody is None:
                raise ValueError(
                    "production worker lacks immutable runtime input custody"
                )
            if (
                self.startup_broker_receipt is None
                or self.shutdown_broker_receipt is None
            ):
                raise ValueError("production worker lacks broker lifecycle receipts")
            if not self.concurrent_descendant_sampling_validated:
                raise ValueError("production worker lacks controller sampling custody")
            if self.terminal_child_watch_log is None:
                raise ValueError("production worker lacks terminal child-watch bytes")
            if self.fork_denial_evidence.expected_request_count != len(
                self.requests
            ):
                raise ValueError("request-control expected count differs")
            readiness = self.request_control_readiness
            sandbox = self.kernel_sandbox_evidence
            if sandbox is not None and (
                sandbox.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
                or sandbox.scope_sha256 != readiness.scope_sha256
                or sandbox.logical_controller.pid
                != self.fork_denial_evidence.controller_pid
                or sandbox.logical_controller.start_abstime
                != self.fork_denial_evidence.controller_start_abstime
                or (
                    sandbox.watchdog_launcher.pid,
                    sandbox.watchdog_launcher.start_abstime,
                    sandbox.watchdog_launcher.parent_pid,
                    sandbox.watchdog_launcher.process_group_id,
                    sandbox.watchdog_launcher.session_id,
                )
                != (
                    self.fork_denial_evidence.launcher.pid,
                    self.fork_denial_evidence.launcher.start_abstime,
                    self.fork_denial_evidence.launcher.ppid,
                    self.fork_denial_evidence.launcher.pgid,
                    self.fork_denial_evidence.launcher.sid,
                )
                or (
                    sandbox.worker.process_before.pid,
                    sandbox.worker.process_before.start_abstime,
                    sandbox.worker.process_before.parent_pid,
                    sandbox.worker.process_before.process_group_id,
                    sandbox.worker.process_before.session_id,
                )
                != (
                    readiness.worker.pid,
                    readiness.worker.start_abstime,
                    readiness.worker.parent_pid,
                    readiness.worker.process_group_id,
                    readiness.worker.session_id,
                )
                or (
                    sandbox.broker.process_before.pid,
                    sandbox.broker.process_before.start_abstime,
                    sandbox.broker.process_before.parent_pid,
                    sandbox.broker.process_before.process_group_id,
                    sandbox.broker.process_before.session_id,
                )
                != (
                    readiness.broker.pid,
                    readiness.broker.start_abstime,
                    readiness.broker.parent_pid,
                    readiness.broker.process_group_id,
                    readiness.broker.session_id,
                )
                or sandbox.worker.native_closure_sha256
                != self.fork_denial_evidence.native_closure_sha256
            ):
                raise ValueError("kernel sandbox production custody differs")
            worker_ready_thread_ids = (
                readiness.controller_worker_thread_inventory.thread_ids
            )
            worker_ready_fd_sha256 = (
                readiness.controller_worker_file_descriptor_inventory.inventory_sha256
            )
            broker_ready_thread_ids = (
                readiness.controller_broker_thread_inventory.thread_ids
            )
            broker_ready_fd_sha256 = (
                readiness.controller_broker_file_descriptor_inventory.inventory_sha256
            )
            if (
                readiness.worker != self.fork_denial_evidence.worker
                or readiness.broker != self.fork_denial_evidence.broker
                or readiness.expected_request_count != len(self.requests)
            ):
                raise ValueError("request-control readiness topology differs")
            for request in self.requests:
                boundary = request.resource_boundary
                if request.status is AttemptStatus.SUCCESS and (
                    boundary is None
                    or boundary.cpu_accounting_basis
                    != "fork-denied-worker-broker-self-plus-exact-wait4-v2"
                    or boundary.exact_broker_cpu is None
                ):
                    raise ValueError("production request lacks exact broker CPU-v2 evidence")
                if (
                    request.status is AttemptStatus.SUCCESS
                    and boundary is not None
                    and boundary.exact_broker_cpu is not None
                    and (
                        boundary.exact_broker_cpu.begin.worker
                        != self.fork_denial_evidence.worker
                        or boundary.exact_broker_cpu.begin.broker
                        != self.fork_denial_evidence.broker
                        or boundary.exact_broker_cpu.request_sequence
                        != request.request_index
                        or any(
                            (
                                inventory.root_device,
                                inventory.root_inode,
                                inventory.root_mode,
                                inventory.root_uid,
                            )
                            != (
                                self.fork_denial_evidence.worker_scratch_device,
                                self.fork_denial_evidence.worker_scratch_inode,
                                self.fork_denial_evidence.worker_scratch_mode,
                                self.fork_denial_evidence.worker_scratch_uid,
                            )
                            for inventory in (
                                boundary.exact_broker_cpu.begin.request_root_inventory,
                                boundary.exact_broker_cpu.begin_post_sample_scratch_inventory,
                                boundary.exact_broker_cpu.end.request_root_inventory,
                                boundary.exact_broker_cpu.end_post_sample_scratch_inventory,
                            )
                        )
                        or boundary.exact_broker_cpu.request_binding.source_sha256
                        != self.source.sha256
                        or boundary.exact_broker_cpu.request_binding.source_bytes
                        != self.source.size_bytes
                        or boundary.exact_broker_cpu.request_binding.safe_filename_sha256
                        != hashlib.sha256(
                            self.source.filename.encode("utf-8")
                        ).hexdigest()
                        or (
                            request.output is not None
                            and boundary.exact_broker_cpu.request_binding.output_format
                            != (
                                "json"
                                if request.output.media_type == "application/json"
                                else "markdown"
                            )
                        )
                    )
                ):
                    raise ValueError(
                        "request CPU/request identity differs from worker custody"
                    )
                if (
                    request.status is AttemptStatus.SUCCESS
                    and boundary is not None
                    and boundary.exact_broker_cpu is not None
                    and (
                        readiness.ready_at_monotonic_ns
                        > boundary.exact_broker_cpu.arm_issued_at_monotonic_ns
                        or any(
                            sample.native_thread_ids != worker_ready_thread_ids
                            or sample.file_descriptor_inventory.inventory_sha256
                            != worker_ready_fd_sha256
                            for sample in (
                                boundary.exact_broker_cpu.begin_external_sample.worker_sample,
                                boundary.exact_broker_cpu.end_external_sample.worker_sample,
                            )
                        )
                        or any(
                            sample.native_thread_ids != broker_ready_thread_ids
                            or sample.file_descriptor_inventory.inventory_sha256
                            != broker_ready_fd_sha256
                            for sample in (
                                boundary.exact_broker_cpu.begin_external_sample.broker_sample,
                                boundary.exact_broker_cpu.end_external_sample.broker_sample,
                            )
                        )
                    )
                ):
                    raise ValueError("READY thread/FD baseline escaped request custody")
            exact_requests = tuple(
                request.resource_boundary.exact_broker_cpu
                for request in self.requests
                if request.status is AttemptStatus.SUCCESS
                and request.resource_boundary is not None
                and request.resource_boundary.exact_broker_cpu is not None
            )
            custody = self.immutable_runtime_input_custody
            assert custody is not None
            custody_by_role = {
                item.role: item for item in custody.root_authorities
            }
            if sandbox is not None:
                require_kernel_sandbox_immutable_input_custody(
                    sandbox,
                    custody,
                )
            shutdown_inputs = _terminal_shutdown_immutable_input_observation(
                self.terminal_child_watch_log
            )
            all_custodied_file_sha256s = {
                item.content_sha256
                for item in custody.entry_projection
                if item.kind == "file" and item.content_sha256 is not None
            }
            staged_file_sha256s = {
                item.content_sha256
                for item in custody.entry_projection
                if item.role == "staged_execution_inputs"
                and item.kind == "file"
                and item.content_sha256 is not None
            }
            startup_receipt = self.startup_broker_receipt
            assert startup_receipt is not None
            closure_images = startup_receipt.native_closure.get("images")
            if type(closure_images) is not list:
                raise ValueError("immutable runtime native closure differs")
            closure_image_sha256s = {
                str(item.get("sha256"))
                for item in closure_images
                if type(item) is dict and type(item.get("sha256")) is str
            }
            required_staged_sha256s = {
                str(shutdown_inputs["staged_executable_sha256"]),
                self.fork_denial_evidence.native_fork_probe_source_sha256,
                self.fork_denial_evidence.native_fork_probe_library_sha256,
                self.fork_denial_evidence.broker_native_spawn_guard_source_sha256,
                self.fork_denial_evidence.broker_native_spawn_guard_library_sha256,
                self.fork_denial_evidence.native_runtime_gate_source_sha256,
                self.fork_denial_evidence.native_runtime_gate_library_sha256,
            }
            if (
                "docling_artifacts" not in custody_by_role
                or "staged_execution_inputs" not in custody_by_role
                or "tessdata" not in custody_by_role
                or custody_by_role["docling_artifacts"].kind != "directory"
                or custody_by_role["staged_execution_inputs"].kind
                != "directory"
                or custody_by_role["tessdata"].kind != "directory"
                or custody_by_role["docling_artifacts"].content_manifest_sha256
                != self.runtime_artifact_before_requests.sha256
                or shutdown_inputs["native_closure_sha256"]
                != self.fork_denial_evidence.native_closure_sha256
                or shutdown_inputs["native_spawn_guard_sha256"]
                != self.fork_denial_evidence.broker_native_spawn_guard_library_sha256
                or shutdown_inputs["native_spawn_guard_source_sha256"]
                != self.fork_denial_evidence.broker_native_spawn_guard_source_sha256
                or shutdown_inputs["native_runtime_gate_source_sha256"]
                != self.fork_denial_evidence.native_runtime_gate_source_sha256
                or shutdown_inputs["native_runtime_gate_library_sha256"]
                != self.fork_denial_evidence.native_runtime_gate_library_sha256
                or shutdown_inputs["native_runtime_gate_record_sha256"]
                != self.fork_denial_evidence.native_runtime_gate_record_sha256
                or shutdown_inputs["guard_python_sha256"]
                != startup_receipt.guard_python.get("sha256")
                or shutdown_inputs["guard_python_path_custody_sha256"]
                != startup_receipt.guard_python_path_custody.get("record_sha256")
                or shutdown_inputs["guard_python_native_closure_sha256"]
                != startup_receipt.guard_python_native_closure.get("closure_sha256")
                or shutdown_inputs["guard_python_module_tree_sha256"]
                != startup_receipt.guard_python_module_tree_custody.get("record_sha256")
                or shutdown_inputs["guard_wrapper_source_sha256"]
                != startup_receipt.guard_wrapper_source_sha256
                or shutdown_inputs["guard_wrapper_delivery_basis"]
                != startup_receipt.guard_wrapper_delivery_basis
                or shutdown_inputs["tessdata_sha256"]
                != custody_by_role["tessdata"].content_manifest_sha256
                or not required_staged_sha256s.issubset(staged_file_sha256s)
                or str(shutdown_inputs["source_executable_sha256"])
                not in all_custodied_file_sha256s
                or not closure_image_sha256s
                or not closure_image_sha256s.issubset(
                    all_custodied_file_sha256s
                )
                or (
                    exact_requests
                    and custody.attempt_id != exact_requests[0].attempt_id
                )
            ):
                raise ValueError("immutable runtime input authority differs")
            require_terminal_request_control_transcript(
                self.terminal_request_control_transcript,
                readiness,
                exact_requests,
                request_sources=tuple(self.source for _ in exact_requests),
                request_outputs=tuple(
                    request.output
                    for request in self.requests
                    if request.status is AttemptStatus.SUCCESS
                    and request.resource_boundary is not None
                    and request.resource_boundary.exact_broker_cpu is not None
                    and request.output is not None
                ),
            )
            if exact_requests:
                resource_rows = tuple(
                    row
                    for request in self.requests
                    if request.status is AttemptStatus.SUCCESS
                    and request.resource_boundary is not None
                    for row in request.resource_boundary.controller_resource_sample_rows
                )
                if (
                    not resource_rows
                    or self.controller_resource_sample_log_sha256 is None
                    or self.controller_resource_sample_log_row_count
                    != len(resource_rows)
                    or tuple(item.row_sequence for item in resource_rows)
                    != tuple(range(1, len(resource_rows) + 1))
                    or resource_rows[0].previous_row_sha256 != "0" * 64
                    or any(
                        later.previous_row_sha256 != earlier.row_sha256
                        for earlier, later in zip(
                            resource_rows, resource_rows[1:], strict=False
                        )
                    )
                ):
                    raise ValueError("controller resource log chain differs")
                resource_log_bytes = b"".join(
                    _semantic_json_bytes(row.model_dump(mode="json")) + b"\n"
                    for row in resource_rows
                )
                if (
                    not resource_log_bytes
                    or len(resource_log_bytes)
                    > MAXIMUM_CONTROLLER_RESOURCE_SAMPLE_LOG_BYTES
                    or self.controller_resource_sample_log_size_bytes
                    != len(resource_log_bytes)
                    or self.controller_resource_sample_log_sha256
                    != hashlib.sha256(resource_log_bytes).hexdigest()
                ):
                    raise ValueError("controller resource log bytes differ")
                child_watch_raw = self.terminal_child_watch_log.raw_bytes()
                previous_child_prefix_size = -1
                for row in resource_rows:
                    prefix = row.record.child_watch_prefix
                    if (
                        prefix.size_bytes < previous_child_prefix_size
                        or prefix.size_bytes > len(child_watch_raw)
                    ):
                        raise ValueError(
                            "controller child-watch prefix regressed across requests"
                        )
                    require_terminal_child_watch_prefix(
                        self.terminal_child_watch_log,
                        prefix,
                        request_id=row.record.request_id,
                        request_epoch=row.record.request_epoch,
                        request_sequence=row.record.request_sequence,
                    )
                    previous_child_prefix_size = prefix.size_bytes
                terminal_lineage = _strict_child_watch_lineage(
                    _terminal_child_watch_semantic_raw(
                        self.terminal_child_watch_log
                    )
                )["closed_children"]
                assert isinstance(terminal_lineage, tuple)
                retained_children = tuple(
                    child
                    for exact in exact_requests
                    for child in exact.children
                )
                retained_by_process = {
                    (
                        child.birth.request_id,
                        child.birth.request_epoch,
                        child.birth.request_sequence,
                        child.birth.spawn_sequence,
                        child.birth.spawn_nonce_sha256,
                        child.birth.pid,
                        child.birth.start_abstime,
                    ): child
                    for child in retained_children
                }
                request_tokens = {
                    (exact.request_id, exact.request_epoch, exact.request_sequence)
                    for exact in exact_requests
                }
                replayed_by_process = {
                    tuple(item["process"]): item
                    for item in terminal_lineage
                    if tuple(item["process"][:3]) in request_tokens
                }
                auxiliary_lineage = tuple(
                    item
                    for item in terminal_lineage
                    if tuple(item["process"][:3]) not in request_tokens
                )
                if (
                    len(retained_by_process) != len(retained_children)
                    or set(retained_by_process) != set(replayed_by_process)
                    or any(
                        int(item["process"][1])
                        - int(item["process"][2])
                        not in {0, 2}
                        for item in auxiliary_lineage
                    )
                ):
                    raise ValueError(
                        "terminal child-watch CPU lineage membership differs"
                    )
                for process, child in retained_by_process.items():
                    replayed = replayed_by_process[process]
                    birth = child.birth
                    tombstone = child.tombstone
                    birth_projection = (
                        birth.spawn_intent_sha256,
                        birth.spawn_intent_ledger_row_sha256,
                        birth.provisional_record_sha256,
                        birth.provisional_child_ledger_row_sha256,
                        birth.child_ready_sha256,
                        birth.child_ready_intent_ledger_row_sha256,
                        birth.watchdog_registration_sha256,
                        birth.watchdog_registration_ack_sha256,
                        birth.birth_commitment_sha256,
                        birth.birth_ledger_row_sha256,
                        birth.watchdog_birth_sha256,
                        birth.watchdog_birth_ack_sha256,
                        birth.exec_release_ledger_row_sha256,
                    )
                    replayed_birth_projection = (
                        replayed["spawn_intent"]["spawn_intent_sha256"],
                        replayed["spawn_intent_row_sha256"],
                        replayed["provisional"]["provisional_record_sha256"],
                        replayed["provisional_row_sha256"],
                        replayed["child_intent"]["child_ready_sha256"],
                        replayed["child_intent_row_sha256"],
                        replayed["registration_sha256"],
                        replayed["registration_ack_sha256"],
                        replayed["birth_commitment_sha256"],
                        replayed["birth_ledger_row_sha256"],
                        replayed["watch_birth_sha256"],
                        replayed["birth_ack_sha256"],
                        replayed["exec_release_row_sha256"],
                    )
                    raw_tombstone = dict(replayed["tombstone"])
                    raw_tombstone_projection = {
                        name: raw_tombstone[name]
                        for name in BrokerChildWait4Tombstone.model_fields
                    }
                    if (
                        birth_projection != replayed_birth_projection
                        or tombstone.model_dump(mode="json")
                        != raw_tombstone_projection
                        or child.watchdog_closure_record_sha256
                        != replayed["reaped_ack_sha256"]
                        or child.birth.record_sha256
                        != tombstone.birth_record_sha256
                        or child.birth.record_sha256
                        != replayed["tombstone"]["birth_record_sha256"]
                        or child.birth.open_fd_inventory_sha256
                        != replayed["pre_exec_gated_child_sample"].open_fd_inventory_sha256
                        or child.birth.native_thread_inventory_sha256
                        != replayed["pre_exec_gated_child_sample"].native_thread_inventory_sha256
                    ):
                        raise ValueError(
                            "terminal child-watch CPU lineage projection differs"
                        )
                _require_broker_lifecycle_chain(
                    terminal=self.terminal_child_watch_log,
                    readiness=readiness,
                    exact_requests=exact_requests,
                    startup=self.startup_broker_receipt,
                    shutdown=self.shutdown_broker_receipt,
                    native_closure_sha256=(
                        self.fork_denial_evidence.native_closure_sha256
                    ),
                )
                root_resource_baseline = (
                    exact_requests[0].begin_external_sample.worker_sample.thread_count,
                    exact_requests[0].begin_external_sample.worker_sample.file_descriptor_count,
                    exact_requests[0].begin_external_sample.broker_sample.thread_count,
                    exact_requests[0].begin_external_sample.broker_sample.file_descriptor_count,
                )
                for exact in exact_requests:
                    for edge in (
                        exact.begin_external_sample,
                        exact.end_external_sample,
                    ):
                        if (
                            edge.worker_sample.thread_count,
                            edge.worker_sample.file_descriptor_count,
                            edge.broker_sample.thread_count,
                            edge.broker_sample.file_descriptor_count,
                        ) != root_resource_baseline:
                            raise ValueError(
                                "worker/broker thread or FD baseline changed across requests"
                            )
        elif any(
            value is not None
            for value in (
                self.controller_resource_sample_log_sha256,
                self.controller_resource_sample_log_row_count,
                self.controller_resource_sample_log_size_bytes,
                self.terminal_child_watch_log,
                self.terminal_request_control_transcript,
                self.startup_broker_receipt,
                self.shutdown_broker_receipt,
                self.kernel_sandbox_evidence,
            )
        ):
            raise ValueError("synthetic worker cannot claim controller resource log")
        return self


class LocalPrewarmAttempt(ContractModel):
    schema_id: Literal["phase-latency-prewarm-attempt-v1"]
    attempt_id: StableId
    case_id: StableId
    repetition_index: PositiveInt
    mode: RunMode
    started_at_utc: datetime
    completed_at_utc: datetime
    source: SourceIdentity
    execution: ExecutionIdentity
    configuration: ConfigurationIdentity
    worker: WorkerMeasurementEnvelope
    cleanup: CleanupEvidence
    status: AttemptStatus
    failure: FailureRecord | None
    rss_disposition: Literal["owner_deferred_observational"] = RSS_DISPOSITION
    strict_rss_gate_pass_claimed: Literal[False] = False
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @field_validator("attempt_id", "case_id")
    @classmethod
    def validate_ids(cls, value: str, info: object) -> str:
        return _stable_id(value, label=getattr(info, "field_name", "identifier"))

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def validate_utc(cls, value: datetime, info: object) -> datetime:
        return _utc(value, label=getattr(info, "field_name", "timestamp"))

    @model_validator(mode="after")
    def validate_attempt(self) -> "LocalPrewarmAttempt":
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("attempt completion precedes start")
        if not (
            self.case_id == self.source.case_id == self.worker.case_id
            and self.source == self.worker.source
            and self.mode is self.worker.mode
        ):
            raise ValueError("attempt identity differs from worker evidence")
        if self.configuration.prewarm_enabled != (self.mode is RunMode.ENABLED):
            raise ValueError("attempt mode differs from feature-flag identity")
        if (
            self.worker.kernel_sandbox_evidence is not None
            and self.worker.kernel_sandbox_evidence.attempt_id != self.attempt_id
        ):
            raise ValueError("kernel sandbox attempt identity differs")
        if self.status is AttemptStatus.SUCCESS:
            if self.failure is not None:
                raise ValueError("successful attempt cannot retain a failure")
            if len(self.worker.requests) < 2 or any(
                item.status is not AttemptStatus.SUCCESS for item in self.worker.requests
            ):
                raise ValueError("successful attempt requires repeated successful requests")
        elif self.failure is None:
            raise ValueError("failed attempt must retain a failure")
        return self


class CaseAttemptIndex(ContractModel):
    case_id: StableId
    predecessor_attempt_ids: Annotated[
        tuple[StableId, ...], Field(min_length=MINIMUM_LOCAL_REPETITIONS)
    ]
    enabled_attempt_ids: Annotated[
        tuple[StableId, ...], Field(min_length=MINIMUM_LOCAL_REPETITIONS)
    ]

    @field_validator("case_id")
    @classmethod
    def validate_case_id(cls, value: str) -> str:
        return _stable_id(value, label="case_id")

    @model_validator(mode="after")
    def validate_ids(self) -> "CaseAttemptIndex":
        if len(self.predecessor_attempt_ids) != len(self.enabled_attempt_ids):
            raise ValueError("enabled/predecessor repetition counts differ")
        ids = self.predecessor_attempt_ids + self.enabled_attempt_ids
        if len(set(ids)) != len(ids):
            raise ValueError("case attempt IDs must be unique")
        return self


class DirectionalLlamaReference(ContractModel):
    case_id: StableId
    source_sha256: Sha256
    provider_total_latency_ms: PositiveInt
    source: Literal["retained_one_sample_llamaparse_v1"]
    sample_count: Literal[1] = 1
    directional_only: Literal[True] = True
    qualification_claimed: Literal[False] = False


class CurrentRuntimeOutputExpectation(ContractModel):
    case_id: StableId
    source_sha256: Sha256
    semantic_sha256: Sha256
    source: Literal["CURRENT_RUNTIME_OUTPUT_IDENTITIES"] = (
        "CURRENT_RUNTIME_OUTPUT_IDENTITIES"
    )


class TerminalRecordDescriptor(ContractModel):
    """One controller-reread durable record in the campaign hash chain."""

    sequence: PositiveInt
    previous_entry_sha256: Sha256
    retained_monotonic_ns: PositiveInt
    segment: Literal[
        "rollback",
        "rollback_gate",
        "cross_input",
        "paired",
        "campaign_final",
    ]
    record_kind: StableId
    relative_path: str
    topology: Literal[
        "direct-default-off-v1",
        "fork-denied-worker-external-tesseract-broker-v1",
        "campaign-controller-v1",
    ]
    attempt_id: StableId | None = None
    case_id: StableId | None = None
    case_ordinal: Annotated[int, Field(strict=True, ge=1, le=15)] | None = None
    attempt_status: AttemptStatus | None = None
    content_sha256: Sha256
    size_bytes: PositiveInt
    file_mode: Literal[0o600] = 0o600
    reopened_no_follow_after_fsync: Literal[True] = True
    entry_sha256: Sha256

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _portable_path(value)

    @field_validator("record_kind")
    @classmethod
    def validate_record_kind(cls, value: str) -> str:
        return _stable_id(value, label="terminal record kind")

    @model_validator(mode="after")
    def validate_descriptor(self) -> "TerminalRecordDescriptor":
        if (self.case_id is None) != (self.case_ordinal is None):
            raise ValueError("terminal record case identity is incomplete")
        if self.segment == "rollback" and (
            self.topology != "direct-default-off-v1"
            or self.attempt_id is None
            or self.case_id is None
        ):
            raise ValueError("rollback terminal record topology differs")
        if self.segment == "rollback_gate" and (
            self.topology != "campaign-controller-v1"
            or self.attempt_id is not None
            or self.case_id is not None
            or self.record_kind
            not in {"rollback-evidence", "rollback-submanifest"}
        ):
            raise ValueError("rollback-gate terminal record topology differs")
        if self.segment in {"cross_input", "paired"} and self.topology != (
            "fork-denied-worker-external-tesseract-broker-v1"
        ):
            raise ValueError("brokered terminal record topology differs")
        if self.record_kind in {"attempt-receipt", "cross-input-receipt"}:
            if self.attempt_status is None:
                raise ValueError("terminal receipt lacks status")
        elif self.attempt_status is not None:
            raise ValueError("non-receipt terminal record cannot carry status")
        fields = self.model_dump(mode="json", exclude={"entry_sha256"})
        if self.entry_sha256 != _canonical_hash(fields):
            raise ValueError("terminal record descriptor identity differs")
        return self


TERMINAL_RECORD_POLICY = (
    "o-excl-fsync-reread-hash-chain-prebundle-terminal-records-v2"
)
ROLLBACK_TERMINAL_RECORD_KINDS = (
    "launch-intent",
    "launch-record",
    "phase-deadlines",
    "phase-acks",
    "watchdog-terminal",
    "launcher-ledger",
    "attempt-receipt",
    "artifact-observation",
)
ROLLBACK_TERMINAL_RECORD_COUNT = len(PRODUCTION_CASE_IDS) * len(
    ROLLBACK_TERMINAL_RECORD_KINDS
)
BROKERED_TERMINAL_RECORD_KINDS = (
    "launch-intent",
    "launch-record",
    "phase-deadlines",
    "phase-acks",
    "watchdog-terminal",
    "launcher-ledger",
    "broker-launch-template",
    "broker-ready",
    "supervisor-ready",
    "child-watch-ledger",
    "request-control-ledger",
    "external-cpu-samples",
    "controller-resource-samples",
    "kernel-sandbox-evidence",
    "native-closure-post-observation",
    "attempt-receipt",
    "artifact-observation",
)
CROSS_INPUT_TERMINAL_RECORD_KINDS = (
    *BROKERED_TERMINAL_RECORD_KINDS[:-2],
    "cross-input-receipt",
    "artifact-observation",
)


def _terminal_kinds_with_request_receipts(
    base: tuple[str, ...], receipt_count: int
) -> tuple[str, ...]:
    if receipt_count < 0 or receipt_count > MAXIMUM_REQUESTS_PER_ATTEMPT:
        raise ValueError("terminal request receipt count exceeds bound")
    insertion = base.index("request-control-ledger") + 1
    return (
        *base[:insertion],
        *("broker-request-receipt" for _ in range(receipt_count)),
        *base[insertion:],
    )


def _terminal_record_manifest_sha256(
    entries: tuple[TerminalRecordDescriptor, ...],
) -> str:
    return _canonical_hash(
        {
            "policy": TERMINAL_RECORD_POLICY,
            "entries": [entry.model_dump(mode="json") for entry in entries],
        }
    )


def _validate_terminal_record_chain(
    entries: tuple[TerminalRecordDescriptor, ...],
) -> None:
    if tuple(entry.sequence for entry in entries) != tuple(
        range(1, len(entries) + 1)
    ):
        raise ValueError("terminal record sequence is incomplete")
    previous = "0" * 64
    last_monotonic_ns = 0
    paths: set[str] = set()
    for entry in entries:
        if entry.previous_entry_sha256 != previous:
            raise ValueError("terminal record hash chain differs")
        if entry.retained_monotonic_ns <= last_monotonic_ns:
            raise ValueError("terminal record chronology is not strictly increasing")
        if entry.relative_path in paths:
            raise ValueError("terminal record path is duplicated")
        paths.add(entry.relative_path)
        previous = entry.entry_sha256
        last_monotonic_ns = entry.retained_monotonic_ns


def _require_production_terminal_manifest_tail(
    manifest: "TerminalRecordManifest",
    *,
    attempts: tuple["LocalPrewarmAttempt", ...],
    case_indexes: tuple["CaseAttemptIndex", ...],
    cross_input: "CrossInputIsolationEvidence",
) -> None:
    """Require the exact successful cross/paired/final execution tail."""

    offset = manifest.rollback_prefix_entry_count + 2
    tail = manifest.entries[offset:]
    cross_receipt_count = len(
        cross_input.terminal_request_control_transcript.receipt_blobs
    )
    expected_cross_kinds = _terminal_kinds_with_request_receipts(
        CROSS_INPUT_TERMINAL_RECORD_KINDS,
        cross_receipt_count,
    )
    cross_count = len(expected_cross_kinds)
    cross = tail[:cross_count]
    if (
        len(cross) != cross_count
        or tuple(item.record_kind for item in cross)
        != expected_cross_kinds
        or any(
            item.segment != "cross_input"
            or item.topology
            != "fork-denied-worker-external-tesseract-broker-v1"
            or item.attempt_id != "lat-us02-cross-input-isolation"
            or item.case_id is not None
            or item.case_ordinal is not None
            for item in cross
        )
        or next(
            item for item in cross if item.record_kind == "cross-input-receipt"
        ).attempt_status
        is not AttemptStatus.SUCCESS
    ):
        raise ValueError("terminal cross-input membership differs")
    cursor = cross_count
    by_id = {item.attempt_id: item for item in attempts}
    expected_attempt_ids: list[str] = []
    for case in case_indexes:
        if len(case.predecessor_attempt_ids) != len(case.enabled_attempt_ids):
            raise ValueError("terminal paired repetition membership differs")
        for predecessor, enabled in zip(
            case.predecessor_attempt_ids,
            case.enabled_attempt_ids,
            strict=True,
        ):
            expected_attempt_ids.extend((predecessor, enabled))
    if tuple(item.attempt_id for item in attempts) != tuple(expected_attempt_ids):
        raise ValueError("terminal paired attempt chronology differs")
    for attempt_id in expected_attempt_ids:
        attempt = by_id[attempt_id]
        receipt_count = len(
            attempt.worker.terminal_request_control_transcript.receipt_blobs
        )
        expected_kinds = _terminal_kinds_with_request_receipts(
            BROKERED_TERMINAL_RECORD_KINDS,
            receipt_count,
        )
        count = len(expected_kinds)
        records = tail[cursor : cursor + count]
        expected_ordinal = PRODUCTION_CASE_IDS.index(attempt.case_id) + 1
        if (
            len(records) != count
            or tuple(item.record_kind for item in records)
            != expected_kinds
            or any(
                item.segment != "paired"
                or item.topology
                != "fork-denied-worker-external-tesseract-broker-v1"
                or item.attempt_id != attempt_id
                or item.case_id != attempt.case_id
                or item.case_ordinal != expected_ordinal
                for item in records
            )
            or next(
                item for item in records if item.record_kind == "attempt-receipt"
            ).attempt_status
            is not AttemptStatus.SUCCESS
        ):
            raise ValueError("terminal paired attempt membership differs")
        cursor += count
    campaign_final = tail[cursor:]
    if (
        len(campaign_final) != 1
        or campaign_final[0].segment != "campaign_final"
        or campaign_final[0].record_kind != "artifact-observation"
        or campaign_final[0].topology != "campaign-controller-v1"
        or campaign_final[0].attempt_id is not None
        or campaign_final[0].case_id is not None
        or campaign_final[0].case_ordinal is not None
    ):
        raise ValueError("terminal campaign-final membership differs")


class TerminalRecordSubmanifest(ContractModel):
    """Durable direct-rollback prefix that must close before paired launch."""

    schema_id: Literal["phase-latency-prewarm-terminal-submanifest-v2"]
    policy: Literal[
        "o-excl-fsync-reread-hash-chain-prebundle-terminal-records-v2"
    ] = TERMINAL_RECORD_POLICY
    entries: Annotated[
        tuple[TerminalRecordDescriptor, ...],
        Field(
            min_length=ROLLBACK_TERMINAL_RECORD_COUNT,
            max_length=ROLLBACK_TERMINAL_RECORD_COUNT,
        ),
    ]
    entry_count: PositiveInt
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def validate_submanifest(self) -> "TerminalRecordSubmanifest":
        _validate_terminal_record_chain(self.entries)
        if self.entry_count != len(self.entries):
            raise ValueError("rollback terminal record count differs")
        if self.manifest_sha256 != _terminal_record_manifest_sha256(self.entries):
            raise ValueError("rollback terminal record manifest identity differs")
        if any(entry.segment != "rollback" for entry in self.entries):
            raise ValueError("rollback prefix contains a later campaign record")

        previous_end = 0
        for ordinal, case_id in enumerate(PRODUCTION_CASE_IDS, start=1):
            indexed = tuple(
                (index, entry)
                for index, entry in enumerate(self.entries)
                if entry.case_id == case_id and entry.case_ordinal == ordinal
            )
            kinds = tuple(entry.record_kind for _, entry in indexed)
            if kinds != ROLLBACK_TERMINAL_RECORD_KINDS:
                raise ValueError("rollback terminal case membership differs")
            intent_index = next(
                index for index, entry in indexed if entry.record_kind == "launch-intent"
            )
            receipt_index = next(
                index for index, entry in indexed if entry.record_kind == "attempt-receipt"
            )
            artifact_index = next(
                index
                for index, entry in indexed
                if entry.record_kind == "artifact-observation"
            )
            receipt = self.entries[receipt_index]
            if not (
                previous_end == intent_index < receipt_index < artifact_index
                and receipt.attempt_status is AttemptStatus.SUCCESS
                and all(
                    entry.attempt_id == self.entries[intent_index].attempt_id
                    for _, entry in indexed
                )
                and tuple(index for index, _ in indexed)
                == tuple(range(intent_index, artifact_index + 1))
            ):
                raise ValueError("rollback intent/terminal chronology differs")
            previous_end = artifact_index + 1
        if previous_end != len(self.entries):
            raise ValueError("rollback prefix contains unbound terminal records")
        return self


class TerminalRecordManifest(ContractModel):
    """Closed manifest of every durable record written before the bundle."""

    schema_id: Literal["phase-latency-prewarm-terminal-manifest-v2"]
    policy: Literal[
        "o-excl-fsync-reread-hash-chain-prebundle-terminal-records-v2"
    ] = TERMINAL_RECORD_POLICY
    entries: Annotated[
        tuple[TerminalRecordDescriptor, ...],
        Field(min_length=ROLLBACK_TERMINAL_RECORD_COUNT + 2, max_length=4096),
    ]
    entry_count: PositiveInt
    rollback_prefix_entry_count: PositiveInt
    rollback_prefix_manifest_sha256: Sha256
    directory_mode: Literal[0o700] = 0o700
    no_unindexed_prebundle_regular_files: Literal[True] = True
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> "TerminalRecordManifest":
        _validate_terminal_record_chain(self.entries)
        if self.entry_count != len(self.entries):
            raise ValueError("terminal record manifest count differs")
        if self.rollback_prefix_entry_count != ROLLBACK_TERMINAL_RECORD_COUNT:
            raise ValueError("terminal rollback prefix count differs")
        prefix = self.entries[: self.rollback_prefix_entry_count]
        TerminalRecordSubmanifest(
            schema_id="phase-latency-prewarm-terminal-submanifest-v2",
            entries=prefix,
            entry_count=len(prefix),
            manifest_sha256=_terminal_record_manifest_sha256(prefix),
        )
        if any(entry.segment != "rollback" for entry in prefix) or any(
            entry.segment == "rollback"
            for entry in self.entries[self.rollback_prefix_entry_count :]
        ):
            raise ValueError("terminal rollback prefix is not exact")
        rollback_gate = self.entries[
            self.rollback_prefix_entry_count : self.rollback_prefix_entry_count + 2
        ]
        if tuple(entry.record_kind for entry in rollback_gate) != (
            "rollback-evidence",
            "rollback-submanifest",
        ) or any(entry.segment != "rollback_gate" for entry in rollback_gate):
            raise ValueError("terminal rollback gate membership differs")
        if self.rollback_prefix_manifest_sha256 != (
            _terminal_record_manifest_sha256(prefix)
        ):
            raise ValueError("terminal rollback prefix identity differs")
        expected = _canonical_hash(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        )
        if self.manifest_sha256 != expected:
            raise ValueError("terminal record manifest identity differs")
        return self


def terminal_record_descriptor(**fields: object) -> TerminalRecordDescriptor:
    """Create one canonical hash-chain entry after its target file is reread."""

    if "entry_sha256" in fields:
        raise ValueError("terminal descriptor identity is derived")
    normalized = dict(fields)
    for name in ("attempt_id", "case_id", "case_ordinal", "attempt_status"):
        normalized.setdefault(name, None)
    normalized.setdefault("file_mode", 0o600)
    normalized.setdefault("reopened_no_follow_after_fsync", True)
    if type(normalized["attempt_status"]) is str:
        normalized["attempt_status"] = AttemptStatus(normalized["attempt_status"])
    return TerminalRecordDescriptor(
        **normalized,
        entry_sha256=_canonical_hash(normalized),  # type: ignore[arg-type]
    )


def terminal_record_submanifest(
    entries: tuple[TerminalRecordDescriptor, ...],
) -> TerminalRecordSubmanifest:
    return TerminalRecordSubmanifest(
        schema_id="phase-latency-prewarm-terminal-submanifest-v2",
        entries=entries,
        entry_count=len(entries),
        manifest_sha256=_terminal_record_manifest_sha256(entries),
    )


def terminal_record_manifest(
    *,
    entries: tuple[TerminalRecordDescriptor, ...],
    rollback_prefix: TerminalRecordSubmanifest,
) -> TerminalRecordManifest:
    fields = {
        "schema_id": "phase-latency-prewarm-terminal-manifest-v2",
        "policy": TERMINAL_RECORD_POLICY,
        "entries": entries,
        "entry_count": len(entries),
        "rollback_prefix_entry_count": rollback_prefix.entry_count,
        "rollback_prefix_manifest_sha256": rollback_prefix.manifest_sha256,
        "directory_mode": 0o700,
        "no_unindexed_prebundle_regular_files": True,
    }
    dumped = {
        key: (
            [item.model_dump(mode="json") for item in value]
            if key == "entries"
            else value
        )
        for key, value in fields.items()
    }
    return TerminalRecordManifest(
        **fields, manifest_sha256=_canonical_hash(dumped)  # type: ignore[arg-type]
    )


_DIRECT_ROLLBACK_RECEIPT_FIELDS = frozenset(
    {
        "schema_id",
        "attempt_id",
        "source",
        "execution",
        "configuration",
        "started_at_utc",
        "completed_at_utc",
        "controller_elapsed_ns",
        "worker_return_code",
        "stdout_size_bytes",
        "stdout_sha256",
        "stderr_size_bytes",
        "stderr_sha256",
        "launch_intent_sha256",
        "launch_record_sha256",
        "phase_deadline_log_sha256",
        "phase_ack_log_sha256",
        "phase_sequence_count",
        "watchdog_terminal_sha256",
        "watchdog_terminal_observed_sha256",
        "watchdog_terminal",
        "launcher_terminal_evidence",
        "watchdog_reaped",
        "watchdog_process_group_gone",
        "worker_reaped",
        "worker_process_group_gone",
        "forced_group_cleanup_required",
        "controller_resources",
        "raw_worker",
        "status",
        "record_sha256",
    }
)
_DIRECT_ROLLBACK_RAW_WORKER_FIELDS = frozenset(
    {
        "schema_id",
        "attempt_id",
        "source",
        "configuration_sha256",
        "output",
        "normalized_output_witness",
        "response_content_type_sha256",
        "request_started_monotonic_ns",
        "request_completed_monotonic_ns",
        "startup_duration_ns",
        "shutdown_duration_ns",
        "cold_resource",
        "shutdown_resource",
        "runtime_artifact_before_requests",
        "runtime_artifact_after_shutdown",
        "application_identity_validated",
        "dependency_identity_validated",
        "parser_runtime_identity_validated",
        "runtime_artifact_identity_validated",
        "configuration_identity_validated",
        "feature_flag_disabled",
        "private_broker_capability_present",
        "broker_started",
        "worker_fork_denial_installed",
        "supervisor_bypassed_to_exact_target",
        "production_asgi_lifespan_exercised",
        "network_isolation_validated",
        "hosted_calls",
        "egress_bytes",
        "record_sha256",
    }
)


class UninstrumentedRollbackObservation(ContractModel):
    """One brokerless flag-off output used only to prove exact rollback."""

    case_id: StableId
    source: SourceIdentity
    expectation: CurrentRuntimeOutputExpectation
    configuration: ConfigurationIdentity
    output: OutputIdentity
    normalized_output_witness: NormalizedParseResultWitness
    runtime_artifact_before_requests: FileTreeIdentityEvidence
    runtime_artifact_after_shutdown: FileTreeIdentityEvidence
    cleanup: CleanupEvidence
    canonical_receipt_jsonl: Annotated[
        str, Field(min_length=2, max_length=16_777_216)
    ]
    receipt_sha256: Sha256
    artifact_observation_sha256: Sha256
    feature_flag_disabled: Literal[True] = True
    private_broker_capability_present: Literal[False] = False
    broker_started: Literal[False] = False
    worker_fork_denial_installed: Literal[False] = False
    supervisor_bypassed_to_exact_target: Literal[True] = True
    production_asgi_lifespan_exercised: Literal[True] = True
    network_isolation_validated: Literal[True] = True
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @model_validator(mode="after")
    def validate_rollback_observation(self) -> "UninstrumentedRollbackObservation":
        witness = self.normalized_output_witness
        try:
            receipt_bytes = self.canonical_receipt_jsonl.encode(
                "utf-8", errors="strict"
            )
            raw_receipt = json.loads(receipt_bytes)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("rollback receipt is not canonical JSON") from error
        raw_worker = (
            raw_receipt.get("raw_worker")
            if isinstance(raw_receipt, dict)
            else None
        )
        expected_receipt_bytes = (
            json.dumps(
                raw_receipt,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
        raw_worker_bytes = (
            json.dumps(
                raw_worker,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
            if isinstance(raw_worker, dict)
            else b""
        )
        if (
            self.case_id != self.source.case_id
            or self.expectation.case_id != self.case_id
            or self.expectation.source_sha256 != self.source.sha256
            or self.output.semantic_sha256 != self.expectation.semantic_sha256
            or self.output.media_type != "application/json"
            or self.output.validation != "ParseResult"
            or self.output.normalization_policy
            != "json_exclude_processing_duration_ms_v1"
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
            or not isinstance(raw_receipt, dict)
            or set(raw_receipt) != _DIRECT_ROLLBACK_RECEIPT_FIELDS
            or receipt_bytes != expected_receipt_bytes
            or hashlib.sha256(receipt_bytes).hexdigest() != self.receipt_sha256
            or raw_receipt.get("schema_id")
            != "phase-latency-direct-rollback-attempt-receipt-v1"
            or raw_receipt.get("status") != "success"
            or raw_receipt.get("source") != self.source.model_dump(mode="json")
            or raw_receipt.get("configuration")
            != self.configuration.model_dump(mode="json")
            or raw_receipt.get("record_sha256")
            != _canonical_hash(
                {
                    key: value
                    for key, value in raw_receipt.items()
                    if key != "record_sha256"
                }
            )
            or not isinstance(raw_worker, dict)
            or set(raw_worker) != _DIRECT_ROLLBACK_RAW_WORKER_FIELDS
            or raw_worker.get("schema_id")
            != "phase-latency-direct-rollback-raw-worker-v1"
            or raw_worker.get("attempt_id") != raw_receipt.get("attempt_id")
            or raw_worker.get("source") != self.source.model_dump(mode="json")
            or raw_worker.get("configuration_sha256") != self.configuration.sha256
            or raw_worker.get("output") != self.output.model_dump(mode="json")
            or raw_worker.get("normalized_output_witness")
            != self.normalized_output_witness.model_dump(mode="json")
            or raw_worker.get("runtime_artifact_before_requests")
            != self.runtime_artifact_before_requests.model_dump(mode="json")
            or raw_worker.get("runtime_artifact_after_shutdown")
            != self.runtime_artifact_after_shutdown.model_dump(mode="json")
            or any(
                raw_worker.get(name) is not expected
                for name, expected in (
                    ("feature_flag_disabled", True),
                    ("private_broker_capability_present", False),
                    ("broker_started", False),
                    ("worker_fork_denial_installed", False),
                    ("supervisor_bypassed_to_exact_target", True),
                    ("production_asgi_lifespan_exercised", True),
                    ("network_isolation_validated", True),
                )
            )
            or raw_worker.get("record_sha256")
            != _canonical_hash(
                {
                    key: value
                    for key, value in raw_worker.items()
                    if key != "record_sha256"
                }
            )
            or raw_receipt.get("stdout_size_bytes")
            != len(raw_worker_bytes)
            or raw_receipt.get("stdout_sha256")
            != hashlib.sha256(raw_worker_bytes).hexdigest()
        ):
            raise ValueError("rollback output differs from retained current runtime")
        if (
            self.configuration.prewarm_enabled
            or self.configuration.measurement_kind != "rollback_output_gate"
            or self.configuration.execution_topology != "direct-default-off-v1"
            or self.configuration.broker_evidence_capability != "absent"
        ):
            raise ValueError("rollback observation configuration differs")
        if self.runtime_artifact_before_requests != (
            self.runtime_artifact_after_shutdown
        ):
            raise ValueError("rollback observation changed runtime artifacts")
        cleanup = self.cleanup
        if not (
            cleanup.cleanup_completed
            and cleanup.worker_exited
            and cleanup.worker_reaped
            and cleanup.all_owned_processes_reaped
            and cleanup.threads_returned_to_baseline
            and cleanup.file_descriptors_returned_to_baseline
            and not cleanup.state_retention_detected
            and not cleanup.oom_observed
            and not cleanup.unbounded_rss_growth_observed
            and cleanup.worker_process_group_count == 1
            and cleanup.broker_process_group_count == 0
            and cleanup.controller_watchdog_process_group_count == 1
            and cleanup.owned_process_group_count == 2
        ):
            raise ValueError("rollback observation cleanup is blocking")
        return self


class UninstrumentedRollbackEvidence(ContractModel):
    """All-15 direct flag-off gate preceding any paired brokered attempt."""

    schema_id: Literal["phase-latency-prewarm-rollback-output-gate-v1"]
    generated_at_utc: datetime
    execution: ExecutionIdentity
    observations: Annotated[
        tuple[UninstrumentedRollbackObservation, ...],
        Field(min_length=len(PRODUCTION_CASE_IDS), max_length=len(PRODUCTION_CASE_IDS)),
    ]
    terminal_records: TerminalRecordSubmanifest
    terminal_record_manifest_sha256: Sha256
    all_registered_outputs_matched: Literal[True] = True
    stop_first_mismatch_enforced: Literal[True] = True
    campaign_pairs_not_started_before_gate: Literal[True] = True
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @field_validator("generated_at_utc")
    @classmethod
    def validate_generated_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="generated_at_utc")

    @model_validator(mode="after")
    def validate_full_rollback_gate(self) -> "UninstrumentedRollbackEvidence":
        case_ids = tuple(item.case_id for item in self.observations)
        if case_ids != PRODUCTION_CASE_IDS:
            raise ValueError("rollback output gate must cover all 15 cases in order")
        if len({item.receipt_sha256 for item in self.observations}) != len(
            self.observations
        ):
            raise ValueError("rollback receipts must be unique")
        if self.terminal_record_manifest_sha256 != (
            self.terminal_records.manifest_sha256
        ):
            raise ValueError("rollback terminal manifest binding differs")
        by_case: dict[str, tuple[TerminalRecordDescriptor, ...]] = {
            case_id: tuple(
                entry
                for entry in self.terminal_records.entries
                if entry.case_id == case_id
            )
            for case_id in PRODUCTION_CASE_IDS
        }
        for observation in self.observations:
            records = by_case[observation.case_id]
            receipt = tuple(
                entry for entry in records if entry.record_kind == "attempt-receipt"
            )
            artifact = tuple(
                entry
                for entry in records
                if entry.record_kind == "artifact-observation"
            )
            if (
                len(receipt) != 1
                or len(artifact) != 1
                or receipt[0].content_sha256 != observation.receipt_sha256
                or artifact[0].content_sha256
                != observation.artifact_observation_sha256
            ):
                raise ValueError("rollback observation terminal custody differs")
        return self


class CrossInputRequestObservation(ContractModel):
    sequence_index: Annotated[int, Field(strict=True, ge=1, le=3)]
    source: SourceIdentity
    latency_ns: PositiveInt
    output: OutputIdentity
    runtime_snapshot_sha256: Sha256
    converter_sha256: Sha256
    resource_boundary: RequestResourceBoundary
    worker_state: Literal["ready"] = "ready"
    active_leases: Literal[0] = 0


def _require_terminal_child_watch_cpu_children(
    terminal: TerminalChildWatchLogEvidence,
    exact_requests: tuple[ExactBrokerRequestCpuEvidence, ...],
    *,
    startup: BrokerLifecycleReceiptEvidence,
    shutdown: BrokerLifecycleReceiptEvidence,
) -> None:
    replayed_children = _strict_child_watch_lineage(
        _terminal_child_watch_semantic_raw(terminal)
    )["closed_children"]
    assert isinstance(replayed_children, tuple)
    retained = tuple(
        child
        for group in (
            startup.children,
            *(exact.children for exact in exact_requests),
            shutdown.children,
        )
        for child in group
    )
    retained_by_process = {
        (
            child.birth.request_id,
            child.birth.request_epoch,
            child.birth.request_sequence,
            child.birth.spawn_sequence,
            child.birth.spawn_nonce_sha256,
            child.birth.pid,
            child.birth.start_abstime,
        ): child
        for child in retained
    }
    replayed_by_process = {
        tuple(child["process"]): child
        for child in replayed_children
    }
    if (
        len(retained_by_process) != len(retained)
        or set(retained_by_process) != set(replayed_by_process)
    ):
        raise ValueError("terminal child-watch CPU lineage membership differs")
    for process, child in retained_by_process.items():
        replayed = replayed_by_process[process]
        birth = child.birth
        raw_tombstone = dict(replayed["tombstone"])
        if (
            (
                birth.spawn_intent_sha256,
                birth.spawn_intent_ledger_row_sha256,
                birth.provisional_record_sha256,
                birth.provisional_child_ledger_row_sha256,
                birth.child_ready_sha256,
                birth.child_ready_intent_ledger_row_sha256,
                birth.watchdog_registration_sha256,
                birth.watchdog_registration_ack_sha256,
                birth.birth_commitment_sha256,
                birth.birth_ledger_row_sha256,
                birth.watchdog_birth_sha256,
                birth.watchdog_birth_ack_sha256,
                birth.exec_release_ledger_row_sha256,
            )
            != (
                replayed["spawn_intent"]["spawn_intent_sha256"],
                replayed["spawn_intent_row_sha256"],
                replayed["provisional"]["provisional_record_sha256"],
                replayed["provisional_row_sha256"],
                replayed["child_intent"]["child_ready_sha256"],
                replayed["child_intent_row_sha256"],
                replayed["registration_sha256"],
                replayed["registration_ack_sha256"],
                replayed["birth_commitment_sha256"],
                replayed["birth_ledger_row_sha256"],
                replayed["watch_birth_sha256"],
                replayed["birth_ack_sha256"],
                replayed["exec_release_row_sha256"],
            )
            or child.tombstone.model_dump(mode="json")
            != {
                name: raw_tombstone[name]
                for name in BrokerChildWait4Tombstone.model_fields
            }
            or child.watchdog_closure_record_sha256
            != replayed["reaped_ack_sha256"]
            or birth.record_sha256 != raw_tombstone["birth_record_sha256"]
            or birth.open_fd_inventory_sha256
            != replayed["pre_exec_gated_child_sample"].open_fd_inventory_sha256
            or birth.native_thread_inventory_sha256
            != replayed[
                "pre_exec_gated_child_sample"
            ].native_thread_inventory_sha256
        ):
            raise ValueError("terminal child-watch CPU lineage projection differs")


def _require_broker_lifecycle_chain(
    *,
    terminal: TerminalChildWatchLogEvidence,
    readiness: RequestControlReadinessEvidence,
    exact_requests: tuple[ExactBrokerRequestCpuEvidence, ...],
    startup: BrokerLifecycleReceiptEvidence,
    shutdown: BrokerLifecycleReceiptEvidence,
    native_closure_sha256: str,
) -> None:
    if not exact_requests:
        raise ValueError("broker lifecycle chain lacks request receipts")
    expected_sequences = tuple(range(1, len(exact_requests) + 1))
    previous_receipt_sha256 = startup.receipt_sha256
    if (
        startup.logical_phase != "startup"
        or startup.request_epoch != 1
        or startup.request_sequence != 1
        or startup.previous_receipt_sha256 != "0" * 64
        or startup.begin.ledger_head_sha256 != "0" * 64
        or startup.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
        or startup.scope_sha256 != readiness.scope_sha256
        or startup.begin.worker != readiness.worker
        or startup.begin.broker != readiness.broker
        or startup.end.worker != readiness.worker
        or startup.end.broker != readiness.broker
        or startup.native_closure_sha256 != native_closure_sha256
        or tuple(item.request_sequence for item in exact_requests)
        != expected_sequences
    ):
        raise ValueError("startup broker lifecycle custody differs")
    for sequence, exact in enumerate(exact_requests, 1):
        if (
            exact.request_sequence != sequence
            or exact.request_epoch != sequence + 1
            or exact.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
            or exact.scope_sha256 != readiness.scope_sha256
            or exact.begin.ledger_head_sha256 != previous_receipt_sha256
            or exact.begin.worker != readiness.worker
            or exact.begin.broker != readiness.broker
            or exact.end.worker != readiness.worker
            or exact.end.broker != readiness.broker
        ):
            raise ValueError("request broker lifecycle receipt chain differs")
        previous_receipt_sha256 = exact.broker_request_receipt_sha256
    if (
        shutdown.logical_phase != "shutdown"
        or shutdown.request_epoch != len(exact_requests) + 2
        or shutdown.request_sequence != len(exact_requests)
        or shutdown.previous_receipt_sha256 != previous_receipt_sha256
        or shutdown.begin.ledger_head_sha256 != previous_receipt_sha256
        or shutdown.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
        or shutdown.scope_sha256 != readiness.scope_sha256
        or shutdown.begin.worker != readiness.worker
        or shutdown.begin.broker != readiness.broker
        or shutdown.end.worker != readiness.worker
        or shutdown.end.broker != readiness.broker
        or shutdown.native_closure_sha256 != native_closure_sha256
        or startup.native_closure != shutdown.native_closure
        or startup.request_id == shutdown.request_id
        or startup.request_id in {item.request_id for item in exact_requests}
        or shutdown.request_id in {item.request_id for item in exact_requests}
    ):
        raise ValueError("shutdown broker lifecycle custody differs")
    from app.services.tesseract_broker_protocol import (
        KernelProcessIdentity as AppKernelProcessIdentity,
        NativeRuntimeScanSample as AppNativeRuntimeScanSample,
        runtime_scan_from_sample,
    )
    from app.services.tesseract_native_closure import (
        validate_native_closure,
        validate_runtime_native_scan,
    )

    try:
        frozen_closure = validate_native_closure(
            startup.native_closure, reobserve=False
        )
        for child in (
            *startup.children,
            *(item for exact in exact_requests for item in exact.children),
            *shutdown.children,
        ):
            birth = child.birth
            attestation = child.tombstone.native_runtime_attestation
            if (
                birth.native_closure_sha256 != native_closure_sha256
                or attestation.native_closure_sha256
                != native_closure_sha256
                or birth.operation != attestation.operation
                or birth.logical_environment_sha256
                != attestation.logical_environment_sha256
                or birth.actual_environment_projection_sha256
                != attestation.actual_environment_projection_sha256
                or birth.native_runtime_gate_authority
                != attestation.native_runtime_gate_authority
                or birth.native_runtime_gate_initializer_order_limitation
                != attestation.native_runtime_gate_initializer_order_limitation
                or birth.native_runtime_gate_source_sha256
                != attestation.native_runtime_gate_source_sha256
                or birth.native_runtime_gate_library_sha256
                != attestation.native_runtime_gate_library_sha256
                or birth.native_runtime_gate_record_sha256
                != attestation.native_runtime_gate_record_sha256
                or birth.runtime_gate_nonce_sha256
                != attestation.runtime_gate_nonce_sha256
                or birth.runtime_gate_ack_authority
                != attestation.runtime_gate_ack_authority
                or birth.pid != attestation.runtime_gate_ack_pid
                or birth.exec_release_e_monotonic_ns
                != attestation.exec_release_e_monotonic_ns
            ):
                raise ValueError("child runtime native custody join differs")
            expected_process = AppKernelProcessIdentity(
                pid=birth.pid,
                start_abstime=birth.start_abstime,
                ppid=birth.ppid,
                pgid=birth.pgid,
                sid=birth.sid,
            )
            for sample in attestation.scan_samples:
                app_sample = AppNativeRuntimeScanSample(
                    **sample.model_dump(mode="python")
                )
                validate_runtime_native_scan(
                    runtime_scan_from_sample(
                        attestation.initial_scan, app_sample
                    ),
                    frozen_closure,
                    expected_process,
                )
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("child runtime native closure differs") from error
    _require_terminal_child_watch_cpu_children(
        terminal,
        exact_requests,
        startup=startup,
        shutdown=shutdown,
    )


class CrossInputIsolationEvidence(ContractModel):
    schema_id: Literal["phase-latency-prewarm-cross-input-isolation-v1"]
    source_a: SourceIdentity
    source_b: SourceIdentity
    execution: ExecutionIdentity
    application_settings_sha256: Sha256
    worker_environment_sha256: Sha256
    pairing_sha256: Sha256
    expected_a_semantic_sha256: Sha256
    expected_b_semantic_sha256: Sha256
    measurement_request_count: Literal[3] = 3
    observations: Annotated[
        tuple[CrossInputRequestObservation, ...], Field(min_length=3, max_length=3)
    ]
    controller_resource_sample_log_sha256: Sha256
    controller_resource_sample_log_row_count: PositiveInt
    controller_resource_sample_log_size_bytes: PositiveInt
    terminal_child_watch_log: TerminalChildWatchLogEvidence
    artifact_before_requests: FileTreeIdentityEvidence
    artifact_after_shutdown: FileTreeIdentityEvidence
    startup_duration_ns: NonNegativeInt
    shutdown_duration_ns: NonNegativeInt
    cleanup: CleanupEvidence
    fork_denial_evidence: WorkerForkDenialEvidence
    request_control_readiness: RequestControlReadinessEvidence
    terminal_request_control_transcript: TerminalRequestControlTranscriptEvidence
    kernel_sandbox_evidence: KernelSandboxEvidence | None = None
    immutable_runtime_input_custody: ImmutableRuntimeInputCustodyEvidence
    startup_broker_receipt: BrokerLifecycleReceiptEvidence
    shutdown_broker_receipt: BrokerLifecycleReceiptEvidence
    production_asgi_lifespan_exercised: Literal[True] = True
    prewarm_enabled: Literal[True] = True
    network_isolation_validated: Literal[True] = True
    runtime_identity_stable: Literal[True] = True
    converter_identity_stable: Literal[True] = True
    output_isolation_validated: Literal[True] = True
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0

    @model_validator(mode="after")
    def validate_cross_input_isolation(self) -> "CrossInputIsolationEvidence":
        sandbox = self.kernel_sandbox_evidence
        if sandbox is not None and (
            sandbox.attempt_id != "lat-us02-cross-input-isolation"
            or sandbox.attempt_nonce_sha256
            != self.request_control_readiness.attempt_nonce_sha256
            or sandbox.scope_sha256
            != self.request_control_readiness.scope_sha256
            or sandbox.logical_controller.pid
            != self.fork_denial_evidence.controller_pid
            or sandbox.logical_controller.start_abstime
            != self.fork_denial_evidence.controller_start_abstime
            or (
                sandbox.watchdog_launcher.pid,
                sandbox.watchdog_launcher.start_abstime,
                sandbox.watchdog_launcher.parent_pid,
                sandbox.watchdog_launcher.process_group_id,
                sandbox.watchdog_launcher.session_id,
            )
            != (
                self.fork_denial_evidence.launcher.pid,
                self.fork_denial_evidence.launcher.start_abstime,
                self.fork_denial_evidence.launcher.ppid,
                self.fork_denial_evidence.launcher.pgid,
                self.fork_denial_evidence.launcher.sid,
            )
            or sandbox.worker.native_closure_sha256
            != self.fork_denial_evidence.native_closure_sha256
        ):
            raise ValueError("cross-input kernel sandbox custody differs")
        if self.source_a.case_id == self.source_b.case_id:
            raise ValueError("cross-input control requires two distinct sources")
        if tuple(item.sequence_index for item in self.observations) != (1, 2, 3):
            raise ValueError("cross-input request indexes differ")
        if tuple(item.source for item in self.observations) != (
            self.source_a,
            self.source_b,
            self.source_a,
        ):
            raise ValueError("cross-input sequence must be A-B-A")
        first, middle, last = self.observations

        def signature(item: CrossInputRequestObservation) -> tuple[object, ...]:
            output = item.output
            return (
                output.normalized_sha256,
                output.semantic_sha256,
                output.api_contract_sha256,
                output.provenance_sha256,
                output.concerns_sha256,
                output.deterministic_ids_sha256,
                output.media_type,
            )

        if (
            signature(first) != signature(last)
            or first.output.semantic_sha256 != self.expected_a_semantic_sha256
            or last.output.semantic_sha256 != self.expected_a_semantic_sha256
            or middle.output.semantic_sha256 != self.expected_b_semantic_sha256
        ):
            raise ValueError("cross-input output isolation identity differs")
        if len({item.runtime_snapshot_sha256 for item in self.observations}) != 1:
            raise ValueError("cross-input runtime identity changed")
        if len({item.converter_sha256 for item in self.observations}) != 1:
            raise ValueError("cross-input converter identity changed")
        exact_cpu = tuple(
            item.resource_boundary.exact_broker_cpu for item in self.observations
        )
        if any(
            item is None
            or observation.resource_boundary.cpu_accounting_basis
            != "fork-denied-worker-broker-self-plus-exact-wait4-v2"
            for observation, item in zip(
                self.observations, exact_cpu, strict=True
            )
        ):
            raise ValueError("cross-input control lacks exact broker CPU-v2")
        assert all(item is not None for item in exact_cpu)
        retained_exact = tuple(item for item in exact_cpu if item is not None)
        readiness = self.request_control_readiness
        custody_by_role = {
            item.role: item
            for item in self.immutable_runtime_input_custody.root_authorities
        }
        if sandbox is not None:
            require_kernel_sandbox_immutable_input_custody(
                sandbox,
                self.immutable_runtime_input_custody,
            )
        shutdown_inputs = _terminal_shutdown_immutable_input_observation(
            self.terminal_child_watch_log
        )
        all_custodied_file_sha256s = {
            item.content_sha256
            for item in self.immutable_runtime_input_custody.entry_projection
            if item.kind == "file" and item.content_sha256 is not None
        }
        staged_file_sha256s = {
            item.content_sha256
            for item in self.immutable_runtime_input_custody.entry_projection
            if item.role == "staged_execution_inputs"
            and item.kind == "file"
            and item.content_sha256 is not None
        }
        closure_images = self.startup_broker_receipt.native_closure.get(
            "images"
        )
        if type(closure_images) is not list:
            raise ValueError("cross-input immutable native closure differs")
        closure_image_sha256s = {
            str(item.get("sha256"))
            for item in closure_images
            if type(item) is dict and type(item.get("sha256")) is str
        }
        required_staged_sha256s = {
            str(shutdown_inputs["staged_executable_sha256"]),
            self.fork_denial_evidence.native_fork_probe_source_sha256,
            self.fork_denial_evidence.native_fork_probe_library_sha256,
            self.fork_denial_evidence.broker_native_spawn_guard_source_sha256,
            self.fork_denial_evidence.broker_native_spawn_guard_library_sha256,
            self.fork_denial_evidence.native_runtime_gate_source_sha256,
            self.fork_denial_evidence.native_runtime_gate_library_sha256,
        }
        if (
            readiness.worker != self.fork_denial_evidence.worker
            or readiness.broker != self.fork_denial_evidence.broker
            or readiness.expected_request_count != 3
            or len({item.request_id for item in retained_exact}) != 3
            or tuple(item.request_sequence for item in retained_exact)
            != tuple(sorted(item.request_sequence for item in retained_exact))
            or any(
                item.begin.worker != self.fork_denial_evidence.worker
                or item.begin.broker != self.fork_denial_evidence.broker
                or item.attempt_id != readiness.attempt_id
                or item.attempt_nonce_sha256 != readiness.attempt_nonce_sha256
                or item.scope_sha256 != readiness.scope_sha256
                or readiness.ready_at_monotonic_ns
                > item.arm_issued_at_monotonic_ns
                or any(
                    sample.native_thread_ids
                    != readiness.controller_worker_thread_inventory.thread_ids
                    or sample.file_descriptor_inventory.inventory_sha256
                    != readiness.controller_worker_file_descriptor_inventory.inventory_sha256
                    for sample in (
                        item.begin_external_sample.worker_sample,
                        item.end_external_sample.worker_sample,
                    )
                )
                or any(
                    sample.native_thread_ids
                    != readiness.controller_broker_thread_inventory.thread_ids
                    or sample.file_descriptor_inventory.inventory_sha256
                    != readiness.controller_broker_file_descriptor_inventory.inventory_sha256
                    for sample in (
                        item.begin_external_sample.broker_sample,
                        item.end_external_sample.broker_sample,
                    )
                )
                for item in retained_exact
            )
        ):
            raise ValueError("cross-input CPU request/identity custody differs")
        if (
            self.immutable_runtime_input_custody.attempt_id
            != readiness.attempt_id
            or "docling_artifacts" not in custody_by_role
            or "staged_execution_inputs" not in custody_by_role
            or "tessdata" not in custody_by_role
            or custody_by_role["docling_artifacts"].content_manifest_sha256
            != self.artifact_before_requests.sha256
            or shutdown_inputs["native_closure_sha256"]
            != self.fork_denial_evidence.native_closure_sha256
            or shutdown_inputs["native_spawn_guard_sha256"]
            != self.fork_denial_evidence.broker_native_spawn_guard_library_sha256
            or shutdown_inputs["native_spawn_guard_source_sha256"]
            != self.fork_denial_evidence.broker_native_spawn_guard_source_sha256
            or shutdown_inputs["native_runtime_gate_source_sha256"]
            != self.fork_denial_evidence.native_runtime_gate_source_sha256
            or shutdown_inputs["native_runtime_gate_library_sha256"]
            != self.fork_denial_evidence.native_runtime_gate_library_sha256
            or shutdown_inputs["native_runtime_gate_record_sha256"]
            != self.fork_denial_evidence.native_runtime_gate_record_sha256
            or shutdown_inputs["guard_python_sha256"]
            != self.startup_broker_receipt.guard_python.get("sha256")
            or shutdown_inputs["guard_python_path_custody_sha256"]
            != self.startup_broker_receipt.guard_python_path_custody.get("record_sha256")
            or shutdown_inputs["guard_python_native_closure_sha256"]
            != self.startup_broker_receipt.guard_python_native_closure.get("closure_sha256")
            or shutdown_inputs["guard_python_module_tree_sha256"]
            != self.startup_broker_receipt.guard_python_module_tree_custody.get("record_sha256")
            or shutdown_inputs["guard_wrapper_source_sha256"]
            != self.startup_broker_receipt.guard_wrapper_source_sha256
            or shutdown_inputs["guard_wrapper_delivery_basis"]
            != self.startup_broker_receipt.guard_wrapper_delivery_basis
            or shutdown_inputs["tessdata_sha256"]
            != custody_by_role["tessdata"].content_manifest_sha256
            or not required_staged_sha256s.issubset(staged_file_sha256s)
            or str(shutdown_inputs["source_executable_sha256"])
            not in all_custodied_file_sha256s
            or not closure_image_sha256s
            or not closure_image_sha256s.issubset(
                all_custodied_file_sha256s
            )
        ):
            raise ValueError("cross-input immutable input authority differs")
        require_terminal_request_control_transcript(
            self.terminal_request_control_transcript,
            readiness,
            retained_exact,
            request_sources=tuple(item.source for item in self.observations),
            request_outputs=tuple(item.output for item in self.observations),
        )
        resource_rows = tuple(
            row
            for observation in self.observations
            for row in observation.resource_boundary.controller_resource_sample_rows
        )
        if (
            not resource_rows
            or self.controller_resource_sample_log_row_count != len(resource_rows)
            or tuple(item.row_sequence for item in resource_rows)
            != tuple(range(1, len(resource_rows) + 1))
            or resource_rows[0].previous_row_sha256 != "0" * 64
            or any(
                later.previous_row_sha256 != earlier.row_sha256
                for earlier, later in zip(
                    resource_rows, resource_rows[1:], strict=False
                )
            )
        ):
            raise ValueError("cross-input controller resource log chain differs")
        resource_log_bytes = b"".join(
            _semantic_json_bytes(row.model_dump(mode="json")) + b"\n"
            for row in resource_rows
        )
        if (
            len(resource_log_bytes)
            > MAXIMUM_CONTROLLER_RESOURCE_SAMPLE_LOG_BYTES
            or self.controller_resource_sample_log_size_bytes
            != len(resource_log_bytes)
            or self.controller_resource_sample_log_sha256
            != hashlib.sha256(resource_log_bytes).hexdigest()
        ):
            raise ValueError("cross-input controller resource log bytes differ")
        previous_prefix_size = -1
        for row in resource_rows:
            prefix = row.record.child_watch_prefix
            if prefix.size_bytes < previous_prefix_size:
                raise ValueError(
                    "cross-input child-watch prefix regressed across requests"
                )
            require_terminal_child_watch_prefix(
                self.terminal_child_watch_log,
                prefix,
                request_id=row.record.request_id,
                request_epoch=row.record.request_epoch,
                request_sequence=row.record.request_sequence,
            )
            previous_prefix_size = prefix.size_bytes
        _require_broker_lifecycle_chain(
            terminal=self.terminal_child_watch_log,
            readiness=readiness,
            exact_requests=retained_exact,
            startup=self.startup_broker_receipt,
            shutdown=self.shutdown_broker_receipt,
            native_closure_sha256=self.fork_denial_evidence.native_closure_sha256,
        )
        if self.artifact_before_requests != self.artifact_after_shutdown:
            raise ValueError("cross-input artifact identity changed")
        if not (
            self.cleanup.cleanup_completed
            and self.cleanup.worker_exited
            and self.cleanup.worker_reaped
            and self.cleanup.all_owned_processes_reaped
            and self.cleanup.threads_returned_to_baseline
            and self.cleanup.file_descriptors_returned_to_baseline
            and not self.cleanup.state_retention_detected
            and not self.cleanup.oom_observed
            and not self.cleanup.unbounded_rss_growth_observed
            and self.cleanup.worker_process_group_count == 1
            and self.cleanup.broker_process_group_count == 1
            and self.cleanup.controller_watchdog_process_group_count == 1
            and self.cleanup.owned_process_group_count == 3
        ):
            raise ValueError("cross-input cleanup evidence is blocking")
        return self


class LocalPrewarmEvidenceBundle(ContractModel):
    schema_id: Literal["phase-latency-prewarm-evidence-v1"]
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    evidence_scope: Literal["synthetic_contract_control", "local_story_evidence"]
    generated_at_utc: datetime
    attempts: Annotated[
        tuple[LocalPrewarmAttempt, ...], Field(min_length=1, max_length=MAXIMUM_ATTEMPTS)
    ]
    case_indexes: Annotated[tuple[CaseAttemptIndex, ...], Field(min_length=1)]
    directional_llama_references: tuple[DirectionalLlamaReference, ...] = ()
    current_runtime_output_expectations: tuple[
        CurrentRuntimeOutputExpectation, ...
    ] = ()
    corpus_registry: ArtifactIdentity | None = None
    campaign_plan_sha256: Sha256 | None = None
    final_artifact_materialization_sha256: Sha256 | None = None
    terminal_record_manifest: TerminalRecordManifest | None = None
    terminal_record_manifest_sha256: Sha256 | None = None
    terminal_record_manifest_entry_count: PositiveInt | None = None
    terminal_record_manifest_policy: Literal[
        "o-excl-fsync-reread-hash-chain-prebundle-terminal-records-v2"
    ] | None = None
    uninstrumented_rollback: UninstrumentedRollbackEvidence | None = None
    cross_input_isolation: CrossInputIsolationEvidence | None = None
    failure_retention_policy: Literal[
        "retain_every_local_attempt_no_selection_or_retry_masking_v1"
    ] = "retain_every_local_attempt_no_selection_or_retry_masking_v1"
    hosted_campaign_invoked: Literal[False] = False
    hosted_calls: Literal[0] = 0
    hosted_credits: Literal[0] = 0
    prompt_tokens: Literal[0] = 0
    completion_tokens: Literal[0] = 0
    billed_cost_microusd: Literal[0] = 0
    egress_bytes: Literal[0] = 0
    rss_disposition: Literal["owner_deferred_observational"] = RSS_DISPOSITION
    strict_rss_gate_pass_claimed: Literal[False] = False
    llamaparse_qualification_claimed: Literal[False] = False
    r34_configuration_comparable: Literal[False] = False
    r34_exact_output_identity_claimed: StrictBool = False
    r34_artifact_scope_disposition: Literal[
        "pending_approved_combined_tree_full_15_output_gate",
        "approved_combined_tree_full_15_output_verified",
    ] | None = None

    @field_validator("generated_at_utc")
    @classmethod
    def validate_generated_utc(cls, value: datetime) -> datetime:
        return _utc(value, label="generated_at_utc")

    @model_validator(mode="after")
    def validate_complete_attempt_custody(self) -> "LocalPrewarmEvidenceBundle":
        by_id = {item.attempt_id: item for item in self.attempts}
        if len(by_id) != len(self.attempts):
            raise ValueError("attempt IDs must be unique")
        case_ids = tuple(item.case_id for item in self.case_indexes)
        if case_ids != tuple(sorted(case_ids)) or len(set(case_ids)) != len(case_ids):
            raise ValueError("case indexes must be unique and case-sorted")
        referenced: list[str] = []
        for case in self.case_indexes:
            predecessor = tuple(by_id.get(item) for item in case.predecessor_attempt_ids)
            enabled = tuple(by_id.get(item) for item in case.enabled_attempt_ids)
            if any(item is None for item in predecessor + enabled):
                raise ValueError("case index references an unknown attempt")
            assert all(item is not None for item in predecessor + enabled)
            if any(
                item.case_id != case.case_id or item.mode is not RunMode.PREDECESSOR
                for item in predecessor
            ) or any(
                item.case_id != case.case_id or item.mode is not RunMode.ENABLED
                for item in enabled
            ):
                raise ValueError("case index mode/case binding differs")
            expected_repetitions = tuple(range(1, len(predecessor) + 1))
            if tuple(item.repetition_index for item in predecessor) != expected_repetitions:
                raise ValueError("predecessor repetitions must be complete and ordered")
            if tuple(item.repetition_index for item in enabled) != expected_repetitions:
                raise ValueError("enabled repetitions must be complete and ordered")
            referenced.extend(case.predecessor_attempt_ids + case.enabled_attempt_ids)
        if len(referenced) != len(set(referenced)) or set(referenced) != set(by_id):
            raise ValueError("every retained attempt must be indexed exactly once")
        reference_cases = tuple(item.case_id for item in self.directional_llama_references)
        if len(reference_cases) != len(set(reference_cases)):
            raise ValueError("directional Llama references must be unique per case")
        if not set(reference_cases).issubset(set(case_ids)):
            raise ValueError("directional Llama reference has no local case")
        if self.evidence_scope == "local_story_evidence":
            if case_ids != PRODUCTION_CASE_IDS:
                raise ValueError("production evidence must cover all 15 registered cases")
            if (
                self.corpus_registry is None
                or self.campaign_plan_sha256 is None
                or self.final_artifact_materialization_sha256 is None
                or self.terminal_record_manifest is None
                or self.terminal_record_manifest_sha256 is None
                or self.terminal_record_manifest_entry_count is None
                or self.terminal_record_manifest_policy
                != TERMINAL_RECORD_POLICY
            ):
                raise ValueError("production evidence lacks frozen registry/plan custody")
            if self.r34_artifact_scope_disposition is None:
                raise ValueError("production evidence lacks the r34 scope limitation")
            if self.uninstrumented_rollback is None:
                raise ValueError("production evidence lacks the exact flag-off rollback gate")
            if self.cross_input_isolation is None:
                raise ValueError("production evidence lacks cross-input isolation")
            if any(
                item.execution.dependency_runtime_sha256 is None
                or item.execution.dependency_runtime is None
                or item.execution.lifecycle_cleanup_tests_sha256 is None
                or item.execution.network_isolation_sha256 is None
                or item.configuration.application_settings_sha256 is None
                or item.configuration.worker_environment_sha256 is None
                or item.configuration.pairing_sha256 is None
                or item.configuration.artifacts_path is None
                or item.configuration.artifacts_path_identity_sha256 is None
                or item.configuration.tesseract_executable is None
                or item.configuration.tesseract_data_path is None
                for item in self.attempts
            ):
                raise ValueError("production attempt identity custody is incomplete")
            if any(
                request.resource_boundary is None
                for item in self.attempts
                for request in item.worker.requests
            ):
                raise ValueError("production request CPU boundary is incomplete")
            if any(
                not item.worker.production_asgi_lifespan_exercised
                for item in self.attempts
            ):
                raise ValueError("production evidence must exercise the ASGI lifespan")
            expectations = {
                item.case_id: item
                for item in self.current_runtime_output_expectations
            }
            if tuple(expectations) != PRODUCTION_CASE_IDS:
                raise ValueError("production evidence lacks current-runtime expectations")
            assert self.cross_input_isolation is not None
            assert self.uninstrumented_rollback is not None
            assert self.terminal_record_manifest is not None
            rollback = self.uninstrumented_rollback
            terminal_manifest = self.terminal_record_manifest
            control = self.cross_input_isolation
            if (
                self.terminal_record_manifest_sha256
                != terminal_manifest.manifest_sha256
                or self.terminal_record_manifest_entry_count
                != terminal_manifest.entry_count
                or self.terminal_record_manifest_policy != terminal_manifest.policy
                or terminal_manifest.rollback_prefix_entry_count
                != rollback.terminal_records.entry_count
                or terminal_manifest.rollback_prefix_manifest_sha256
                != rollback.terminal_records.manifest_sha256
                or terminal_manifest.entries[
                    : terminal_manifest.rollback_prefix_entry_count
                ]
                != rollback.terminal_records.entries
            ):
                raise ValueError("terminal record manifest custody differs")
            rollback_gate = terminal_manifest.entries[
                terminal_manifest.rollback_prefix_entry_count :
                terminal_manifest.rollback_prefix_entry_count + 2
            ]
            if tuple(entry.content_sha256 for entry in rollback_gate) != (
                _canonical_hash(rollback.model_dump(mode="json")),
                _canonical_hash(rollback.terminal_records.model_dump(mode="json")),
            ):
                raise ValueError("terminal rollback gate content custody differs")
            _require_production_terminal_manifest_tail(
                terminal_manifest,
                attempts=self.attempts,
                case_indexes=self.case_indexes,
                cross_input=control,
            )
            if (
                any(item.execution != control.execution for item in self.attempts)
                or any(item.execution != rollback.execution for item in self.attempts)
                or control.source_a
                not in {item.source for item in self.attempts}
                or control.source_b
                not in {item.source for item in self.attempts}
                or control.expected_a_semantic_sha256
                != expectations[control.source_a.case_id].semantic_sha256
                or control.expected_b_semantic_sha256
                != expectations[control.source_b.case_id].semantic_sha256
                or control.pairing_sha256
                not in {item.configuration.pairing_sha256 for item in self.attempts}
            ):
                raise ValueError("cross-input isolation custody differs from campaign")
            rollback_by_case = {
                item.case_id: item for item in rollback.observations
            }
            if tuple(rollback_by_case) != PRODUCTION_CASE_IDS:
                raise ValueError("rollback gate case custody differs")

            def output_signature(output: OutputIdentity) -> tuple[object, ...]:
                return (
                    output.normalized_sha256,
                    output.semantic_sha256,
                    output.api_contract_sha256,
                    output.provenance_sha256,
                    output.concerns_sha256,
                    output.deterministic_ids_sha256,
                    output.media_type,
                    output.validation,
                    output.normalization_policy,
                )

            for attempt in self.attempts:
                if attempt.mode is not RunMode.PREDECESSOR:
                    continue
                direct = rollback_by_case[attempt.case_id]
                if any(
                    request.output is None
                    or output_signature(request.output)
                    != output_signature(direct.output)
                    for request in attempt.worker.requests
                ):
                    raise ValueError(
                        "brokered predecessor differs from direct flag-off output"
                    )
                if (
                    configuration_rollback_equivalence_projection(
                        attempt.configuration
                    )
                    != configuration_rollback_equivalence_projection(
                        direct.configuration
                    )
                    or attempt.configuration.artifacts_path
                    != direct.configuration.artifacts_path
                    or attempt.configuration.artifacts_path_identity_sha256
                    != direct.configuration.artifacts_path_identity_sha256
                    or attempt.configuration.tesseract_executable
                    != direct.configuration.tesseract_executable
                    or attempt.configuration.tesseract_data_path
                    != direct.configuration.tesseract_data_path
                ):
                    raise ValueError(
                        "brokered predecessor differs from rollback behavior settings"
                    )
            exact_match = all(
                attempt.source.sha256 == expectations[attempt.case_id].source_sha256
                and all(
                    request.output is not None
                    and request.output.semantic_sha256
                    == expectations[attempt.case_id].semantic_sha256
                    for request in attempt.worker.requests
                )
                for attempt in self.attempts
            )
            if self.r34_exact_output_identity_claimed != exact_match:
                raise ValueError("r34 exact-output claim differs from retained rows")
            expected_disposition = (
                "approved_combined_tree_full_15_output_verified"
                if exact_match
                else "pending_approved_combined_tree_full_15_output_gate"
            )
            if self.r34_artifact_scope_disposition != expected_disposition:
                raise ValueError("r34 artifact-scope disposition differs from rows")
        return self


class CaseComparisonEvaluation(ContractModel):
    case_id: StableId
    repetition_count: PositiveInt
    predecessor_first_request_p50_ns: NonNegativeInt | None
    predecessor_first_request_p95_ns: NonNegativeInt | None
    enabled_first_request_p50_ns: NonNegativeInt | None
    enabled_first_request_p95_ns: NonNegativeInt | None
    byte_output_parity: StrictBool
    semantic_output_parity: StrictBool
    api_contract_parity: StrictBool
    provenance_parity: StrictBool
    concerns_parity: StrictBool
    deterministic_id_parity: StrictBool
    predecessor_current_runtime_identity_match: StrictBool
    enabled_current_runtime_identity_match: StrictBool
    latency_improved_or_preserved: StrictBool


class LocalPrewarmEvaluation(ContractModel):
    schema_id: Literal["phase-latency-prewarm-evaluation-v1"]
    bundle_sha256: Sha256
    attempt_count: PositiveInt
    case_count: PositiveInt
    non_rss_blocking_gates_passed: StrictBool
    completion_eligible_under_owner_rss_deferral: StrictBool
    failure_codes: tuple[EvaluationFailureCode, ...]
    cases: tuple[CaseComparisonEvaluation, ...]
    retained_receipt_authority_sha256: Sha256 | None = None
    rss_disposition: Literal["owner_deferred_observational"] = RSS_DISPOSITION
    strict_rss_gate_pass_claimed: Literal[False] = False
    hosted_campaign_invoked: Literal[False] = False
    llamaparse_qualification_claimed: Literal[False] = False

    @model_validator(mode="after")
    def validate_disposition(self) -> "LocalPrewarmEvaluation":
        passed = not self.failure_codes
        if self.non_rss_blocking_gates_passed != passed:
            raise ValueError("non-RSS gate result differs from failures")
        if self.completion_eligible_under_owner_rss_deferral != passed:
            raise ValueError("owner-deferral completion result differs")
        if self.failure_codes != tuple(sorted(set(self.failure_codes), key=str)):
            raise ValueError("evaluation failure codes must be unique and sorted")
        return self


def canonical_model_bytes(model: ContractModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _nearest_rank(values: tuple[int, ...], percentile: float) -> int:
    if not values:
        raise ValueError("percentile requires observations")
    ordered = sorted(values)
    return ordered[max(0, ceil(percentile * len(ordered)) - 1)]


def _median_ns(values: tuple[int, ...]) -> int:
    return int(median(values))


def evaluate_local_prewarm_attempt_blocking_failures(
    attempt: LocalPrewarmAttempt,
    *,
    production_required: bool,
) -> tuple[EvaluationFailureCode, ...]:
    """Return the same attempt-level blocking gates used by retained evaluation."""

    failures: set[EvaluationFailureCode] = set()
    worker = attempt.worker
    cleanup = attempt.cleanup
    if attempt.status is not AttemptStatus.SUCCESS:
        failures.add(EvaluationFailureCode.ATTEMPT_FAILED)
    if not all(
        (
            worker.dependency_identity_validated,
            worker.application_identity_validated,
            worker.parser_runtime_identity_validated,
            worker.runtime_artifact_identity_validated,
            worker.configuration_identity_validated,
            worker.converter_identity_validated,
        )
    ):
        failures.add(EvaluationFailureCode.IDENTITY_VALIDATION_FAILED)
    production_gates = (
        production_required or worker.production_asgi_lifespan_exercised
    )
    if production_required and not worker.production_asgi_lifespan_exercised:
        failures.add(EvaluationFailureCode.PRODUCTION_LIFESPAN_NOT_EXERCISED)
    if production_gates and (
        not worker.network_isolation_validated
        or worker.kernel_sandbox_evidence is None
    ):
        failures.add(EvaluationFailureCode.NETWORK_ISOLATION_FAILED)
    if production_gates and not worker.concurrent_descendant_sampling_validated:
        failures.add(EvaluationFailureCode.DESCENDANT_SAMPLING_FAILED)
    if production_gates and (
        worker.runtime_artifact_before_requests is None
        or worker.runtime_artifact_after_shutdown is None
        or worker.runtime_artifact_before_requests
        != worker.runtime_artifact_after_shutdown
    ):
        failures.add(EvaluationFailureCode.RUNTIME_ARTIFACT_BOUNDARY_FAILED)
    if production_gates and worker.fork_denial_evidence is None:
        failures.add(EvaluationFailureCode.FORK_DENIAL_FAILED)
    expected_owned_groups = 3 if production_gates else 1
    expected_broker_groups = 1 if production_gates else 0
    expected_watchdog_groups = 1 if production_gates else 0
    if (
        cleanup.worker_process_group_count != 1
        or cleanup.broker_process_group_count != expected_broker_groups
        or cleanup.controller_watchdog_process_group_count
        != expected_watchdog_groups
        or cleanup.owned_process_group_count != expected_owned_groups
    ):
        failures.add(EvaluationFailureCode.OWNED_PROCESS_GROUP_MISMATCH)
    for request in worker.requests:
        boundary = request.resource_boundary
        if request.output is not None and request.output.size_bytes > (
            MAXIMUM_OUTPUT_BYTES
        ):
            failures.add(EvaluationFailureCode.OUTPUT_SIZE_EXCEEDED)
        if production_gates and (
            boundary is None
            or boundary.cpu_accounting_basis
            != "fork-denied-worker-broker-self-plus-exact-wait4-v2"
            or boundary.exact_broker_cpu is None
            or not boundary.sampled_concurrently
            or boundary.sampled_late
            or boundary.cumulative_contamination_detected
            or boundary.descendant_sample_count < 2
            or boundary.descendant_first_sample_monotonic_ns is None
            or boundary.descendant_last_sample_monotonic_ns is None
            or boundary.descendant_maximum_gap_ns is None
            or boundary.descendant_target_interval_ns
            != PEAK_SAMPLE_TARGET_INTERVAL_NS
            or boundary.descendant_edge_tolerance_ns
            != PEAK_SAMPLE_EDGE_TOLERANCE_NS
            or not boundary.request_boundary_covered
            or boundary.descendant_first_sample_monotonic_ns
            > boundary.boundary_started_monotonic_ns
            + PEAK_SAMPLE_EDGE_TOLERANCE_NS
            or boundary.descendant_last_sample_monotonic_ns
            < boundary.boundary_ended_monotonic_ns
            - PEAK_SAMPLE_EDGE_TOLERANCE_NS
            or boundary.descendant_maximum_gap_ns
            > PEAK_SAMPLE_MAXIMUM_GAP_NS
            or boundary.boundary_ended_monotonic_ns
            - boundary.boundary_started_monotonic_ns
            != request.latency_ns
            or boundary.total_cpu_delta_ns > boundary.wall_cpu_capacity_ns
        ):
            failures.add(EvaluationFailureCode.REQUEST_CPU_BOUNDARY_FAILED)
    if not worker.ready_after_identity_validation:
        failures.add(EvaluationFailureCode.WORKER_BECAME_READY_EARLY)
    if not cleanup.cleanup_completed:
        failures.add(EvaluationFailureCode.CLEANUP_FAILED)
    if not cleanup.all_owned_processes_reaped:
        failures.add(EvaluationFailureCode.ORPHANED_PROCESS)
    if not cleanup.threads_returned_to_baseline:
        failures.add(EvaluationFailureCode.THREAD_LEAK)
    if not cleanup.file_descriptors_returned_to_baseline:
        failures.add(EvaluationFailureCode.FILE_DESCRIPTOR_LEAK)
    if cleanup.oom_observed or worker.oom_observed:
        failures.add(EvaluationFailureCode.WORKER_OOM)
    if cleanup.unbounded_rss_growth_observed or worker.unbounded_rss_growth_observed:
        failures.add(EvaluationFailureCode.UNBOUNDED_RSS_GROWTH)
    if cleanup.state_retention_detected or worker.state_retention_detected:
        failures.add(EvaluationFailureCode.CROSS_REQUEST_STATE_RETAINED)
    return tuple(sorted(failures, key=str))


def evaluate_local_prewarm_bundle(
    bundle: LocalPrewarmEvidenceBundle,
    *,
    retained_output_root: Path | None = None,
) -> LocalPrewarmEvaluation:
    """Evaluate all blocking LAT-US02 local gates except deferred numerical RSS."""

    failures: set[EvaluationFailureCode] = set()
    retained_receipt_authority_sha256: str | None = None
    if bundle.evidence_scope == "local_story_evidence":
        if retained_output_root is None:
            failures.add(
                EvaluationFailureCode.RETAINED_RECEIPT_CUSTODY_FAILED
            )
        else:
            try:
                retained_receipt_authority_sha256 = (
                    _retained_request_control_authority_sha256(
                        bundle,
                        output_root=retained_output_root,
                    )
                )
            except (OSError, ValueError):
                failures.add(
                    EvaluationFailureCode.RETAINED_RECEIPT_CUSTODY_FAILED
                )
    by_id = {item.attempt_id: item for item in bundle.attempts}
    case_results: list[CaseComparisonEvaluation] = []

    expectation_by_case = {
        item.case_id: item for item in bundle.current_runtime_output_expectations
    }

    for attempt in bundle.attempts:
        failures.update(
            evaluate_local_prewarm_attempt_blocking_failures(
                attempt,
                production_required=bundle.evidence_scope == "local_story_evidence",
            )
        )
    if bundle.evidence_scope == "local_story_evidence":
        if bundle.uninstrumented_rollback is None:
            failures.add(EvaluationFailureCode.ROLLBACK_OUTPUT_GATE_FAILED)
        else:
            try:
                UninstrumentedRollbackEvidence.model_validate(
                    bundle.uninstrumented_rollback.model_dump(mode="python")
                )
            except ValueError:
                failures.add(EvaluationFailureCode.ROLLBACK_OUTPUT_GATE_FAILED)
            else:
                direct_by_case = {
                    item.case_id: item.output
                    for item in bundle.uninstrumented_rollback.observations
                }

                def rollback_signature(output: OutputIdentity) -> tuple[object, ...]:
                    return (
                        output.normalized_sha256,
                        output.semantic_sha256,
                        output.api_contract_sha256,
                        output.provenance_sha256,
                        output.concerns_sha256,
                        output.deterministic_ids_sha256,
                    )

                if any(
                    attempt.mode is RunMode.PREDECESSOR
                    and (
                        attempt.case_id not in direct_by_case
                        or any(
                            request.output is None
                            or rollback_signature(request.output)
                            != rollback_signature(direct_by_case[attempt.case_id])
                            for request in attempt.worker.requests
                        )
                    )
                    for attempt in bundle.attempts
                ):
                    failures.add(EvaluationFailureCode.ROLLBACK_OUTPUT_GATE_FAILED)
        if bundle.cross_input_isolation is None:
            failures.add(EvaluationFailureCode.CROSS_INPUT_ISOLATION_FAILED)
        else:
            try:
                CrossInputIsolationEvidence.model_validate(
                    bundle.cross_input_isolation.model_dump(mode="python")
                )
            except ValueError:
                failures.add(EvaluationFailureCode.CROSS_INPUT_ISOLATION_FAILED)
            if bundle.cross_input_isolation.kernel_sandbox_evidence is None:
                failures.add(EvaluationFailureCode.CROSS_INPUT_ISOLATION_FAILED)
                failures.add(EvaluationFailureCode.NETWORK_ISOLATION_FAILED)

    for index in bundle.case_indexes:
        predecessor = tuple(by_id[item] for item in index.predecessor_attempt_ids)
        enabled = tuple(by_id[item] for item in index.enabled_attempt_ids)
        all_attempts = predecessor + enabled
        sources = {item.source for item in all_attempts}
        executions = {item.execution for item in all_attempts}
        if len(sources) != 1:
            failures.add(EvaluationFailureCode.SOURCE_IDENTITY_MISMATCH)
        if len(executions) != 1:
            failures.add(EvaluationFailureCode.EXECUTION_IDENTITY_MISMATCH)
        pairing_hashes = {
            item.configuration.pairing_sha256 for item in all_attempts
        }
        if pairing_hashes != {None}:
            pairing_projections = {
                json.dumps(
                    configuration_pairing_projection(item.configuration),
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                for item in all_attempts
            }
            configurations_match = (
                None not in pairing_hashes
                and len(pairing_hashes) == 1
                and len(pairing_projections) == 1
            )
        else:
            predecessor_configs = {
                json.dumps(
                    item.configuration.model_dump(
                        mode="json", exclude={"prewarm_enabled", "sha256"}
                    ),
                    sort_keys=True,
                )
                for item in predecessor
            }
            enabled_configs = {
                json.dumps(
                    item.configuration.model_dump(
                        mode="json", exclude={"prewarm_enabled", "sha256"}
                    ),
                    sort_keys=True,
                )
                for item in enabled
            }
            configurations_match = (
                predecessor_configs == enabled_configs
                and len(predecessor_configs) == 1
            )
        if not configurations_match:
            failures.add(EvaluationFailureCode.CONFIGURATION_PAIR_MISMATCH)

        successful = tuple(
            item
            for item in all_attempts
            if item.status is AttemptStatus.SUCCESS and item.worker.requests
        )
        outputs = tuple(
            request.output
            for attempt in successful
            for request in attempt.worker.requests
            if request.output is not None
        )
        byte_parity = bool(outputs) and len(
            {(item.normalized_sha256, item.media_type) for item in outputs}
        ) == 1
        semantic_parity = bool(outputs) and len(
            {item.semantic_sha256 for item in outputs}
        ) == 1
        component_values = {
            "api_contract": tuple(item.api_contract_sha256 for item in outputs),
            "provenance": tuple(item.provenance_sha256 for item in outputs),
            "concerns": tuple(item.concerns_sha256 for item in outputs),
            "deterministic_id": tuple(
                item.deterministic_ids_sha256 for item in outputs
            ),
        }

        def component_parity(name: str) -> bool:
            values = component_values[name]
            return bool(values) and (
                all(value is None for value in values)
                or (all(value is not None for value in values) and len(set(values)) == 1)
            )

        api_contract_parity = component_parity("api_contract")
        provenance_parity = component_parity("provenance")
        concerns_parity = component_parity("concerns")
        deterministic_id_parity = component_parity("deterministic_id")
        expected_output = expectation_by_case.get(index.case_id)

        def runtime_identity_match(attempts: tuple[LocalPrewarmAttempt, ...]) -> bool:
            return bool(expected_output) and all(
                attempt.source.sha256 == expected_output.source_sha256
                and attempt.worker.requests
                and all(
                    request.output is not None
                    and request.output.semantic_sha256
                    == expected_output.semantic_sha256
                    for request in attempt.worker.requests
                )
                for attempt in attempts
            )

        predecessor_runtime_match = (
            True
            if bundle.evidence_scope == "synthetic_contract_control"
            else runtime_identity_match(predecessor)
        )
        enabled_runtime_match = (
            True
            if bundle.evidence_scope == "synthetic_contract_control"
            else runtime_identity_match(enabled)
        )
        if not byte_parity:
            failures.add(EvaluationFailureCode.OUTPUT_BYTE_PARITY_FAILED)
        if not semantic_parity:
            failures.add(EvaluationFailureCode.OUTPUT_SEMANTIC_PARITY_FAILED)
        if not api_contract_parity:
            failures.add(EvaluationFailureCode.API_CONTRACT_PARITY_FAILED)
        if not provenance_parity:
            failures.add(EvaluationFailureCode.PROVENANCE_PARITY_FAILED)
        if not concerns_parity:
            failures.add(EvaluationFailureCode.CONCERNS_PARITY_FAILED)
        if not deterministic_id_parity:
            failures.add(EvaluationFailureCode.DETERMINISTIC_ID_PARITY_FAILED)
        if not predecessor_runtime_match or not enabled_runtime_match:
            failures.add(
                EvaluationFailureCode.CURRENT_RUNTIME_OUTPUT_IDENTITY_MISMATCH
            )

        predecessor_latencies = tuple(
            item.worker.requests[0].latency_ns
            for item in predecessor
            if item.status is AttemptStatus.SUCCESS and item.worker.requests
        )
        enabled_latencies = tuple(
            item.worker.requests[0].latency_ns
            for item in enabled
            if item.status is AttemptStatus.SUCCESS and item.worker.requests
        )
        complete_latency = (
            len(predecessor_latencies) == len(predecessor)
            and len(enabled_latencies) == len(enabled)
        )
        predecessor_p50 = _median_ns(predecessor_latencies) if complete_latency else None
        predecessor_p95 = (
            _nearest_rank(predecessor_latencies, 0.95) if complete_latency else None
        )
        enabled_p50 = _median_ns(enabled_latencies) if complete_latency else None
        enabled_p95 = _nearest_rank(enabled_latencies, 0.95) if complete_latency else None
        latency_pass = bool(
            complete_latency
            and enabled_p50 is not None
            and enabled_p95 is not None
            and predecessor_p50 is not None
            and predecessor_p95 is not None
            and enabled_p50 <= predecessor_p50
            and enabled_p95 <= predecessor_p95
        )
        if not latency_pass:
            failures.add(EvaluationFailureCode.LATENCY_REGRESSION)
        case_results.append(
            CaseComparisonEvaluation(
                case_id=index.case_id,
                repetition_count=len(predecessor),
                predecessor_first_request_p50_ns=predecessor_p50,
                predecessor_first_request_p95_ns=predecessor_p95,
                enabled_first_request_p50_ns=enabled_p50,
                enabled_first_request_p95_ns=enabled_p95,
                byte_output_parity=byte_parity,
                semantic_output_parity=semantic_parity,
                api_contract_parity=api_contract_parity,
                provenance_parity=provenance_parity,
                concerns_parity=concerns_parity,
                deterministic_id_parity=deterministic_id_parity,
                predecessor_current_runtime_identity_match=(
                    predecessor_runtime_match
                ),
                enabled_current_runtime_identity_match=enabled_runtime_match,
                latency_improved_or_preserved=latency_pass,
            )
        )

    failure_codes = tuple(sorted(failures, key=str))
    passed = not failure_codes
    return LocalPrewarmEvaluation(
        schema_id="phase-latency-prewarm-evaluation-v1",
        bundle_sha256=hashlib.sha256(canonical_model_bytes(bundle)).hexdigest(),
        attempt_count=len(bundle.attempts),
        case_count=len(bundle.case_indexes),
        non_rss_blocking_gates_passed=passed,
        completion_eligible_under_owner_rss_deferral=passed,
        failure_codes=failure_codes,
        cases=tuple(case_results),
        retained_receipt_authority_sha256=(
            retained_receipt_authority_sha256
        ),
    )


def _retained_request_control_authority_sha256(
    bundle: LocalPrewarmEvidenceBundle,
    *,
    output_root: Path,
) -> str:
    """Evaluate production evidence only after reopening every receipt blob.

    The ordinary model/evaluator remains usable for synthetic, context-free
    contract controls.  A production campaign must use this retained-root
    entry point so a manifest or descriptor can never substitute for the
    canonical broker receipt bytes.
    """

    if bundle.evidence_scope != "local_story_evidence":
        raise ValueError("retained receipt authority requires production evidence")
    manifest = bundle.terminal_record_manifest
    cross = bundle.cross_input_isolation
    if manifest is None or cross is None:
        raise ValueError("retained production evidence is incomplete")
    resolved_output = output_root.resolve(strict=True)
    output_stat = resolved_output.lstat()
    if (
        resolved_output != output_root
        or resolved_output.is_symlink()
        or not stat.S_ISDIR(output_stat.st_mode)
        or output_stat.st_uid != os.geteuid()
        or output_stat.st_mode & 0o077
    ):
        raise ValueError("retained production output root custody differs")

    authority_records: list[dict[str, object]] = []

    def require_one(
        *,
        terminal: TerminalRequestControlTranscriptEvidence,
        readiness: RequestControlReadinessEvidence,
        exact_requests: tuple[ExactBrokerRequestCpuEvidence, ...],
        request_sources: tuple[SourceIdentity, ...],
        request_outputs: tuple[OutputIdentity, ...],
    ) -> None:
        if (
            len(terminal.receipt_blobs) != len(exact_requests)
            or not terminal.receipt_blobs
        ):
            raise ValueError("production request receipt blobs are incomplete")
        retained_entries: list[TerminalRecordDescriptor] = []
        parent_paths: set[PurePosixPath] = set()
        for descriptor in terminal.receipt_blobs:
            candidates = tuple(
                entry
                for entry in manifest.entries
                if entry.attempt_id == terminal.attempt_id
                and entry.record_kind == "broker-request-receipt"
                and PurePosixPath(entry.relative_path).name
                == descriptor.relative_path
            )
            if len(candidates) != 1:
                raise ValueError(
                    "terminal request receipt manifest membership differs"
                )
            entry = candidates[0]
            if (
                entry.content_sha256 != descriptor.receipt_blob_sha256
                or entry.size_bytes != descriptor.receipt_blob_bytes
                or entry.file_mode != descriptor.file_mode
            ):
                raise ValueError(
                    "terminal request receipt descriptor differs"
                )
            retained_entries.append(entry)
            parent_paths.add(PurePosixPath(entry.relative_path).parent)
        if (
            len(retained_entries) != len(terminal.receipt_blobs)
            or len(parent_paths) != 1
        ):
            raise ValueError("terminal request receipt root differs")
        parent = next(iter(parent_paths))
        receipt_root = resolved_output.joinpath(*parent.parts)
        require_terminal_request_control_transcript(
            terminal,
            readiness,
            exact_requests,
            request_sources=request_sources,
            request_outputs=request_outputs,
            receipt_blob_root=receipt_root,
        )
        authority_records.append(
            {
                "attempt_id": terminal.attempt_id,
                "terminal_transcript_sha256": terminal.sha256,
                "terminal_transcript_record_sha256": terminal.record_sha256,
                "terminal_manifest_entry_sha256s": [
                    entry.entry_sha256 for entry in retained_entries
                ],
                "receipt_blob_record_sha256s": [
                    descriptor.record_sha256
                    for descriptor in terminal.receipt_blobs
                ],
                "receipt_blob_sha256s": [
                    descriptor.receipt_blob_sha256
                    for descriptor in terminal.receipt_blobs
                ],
            }
        )

    for attempt in bundle.attempts:
        terminal = attempt.worker.terminal_request_control_transcript
        readiness = attempt.worker.request_control_readiness
        if terminal is None or readiness is None:
            raise ValueError("production request-control evidence is absent")
        exact_requests: list[ExactBrokerRequestCpuEvidence] = []
        outputs: list[OutputIdentity] = []
        for request in attempt.worker.requests:
            if (
                request.resource_boundary is None
                or request.resource_boundary.exact_broker_cpu is None
                or request.output is None
            ):
                raise ValueError("production request evidence is incomplete")
            exact_requests.append(request.resource_boundary.exact_broker_cpu)
            outputs.append(request.output)
        require_one(
            terminal=terminal,
            readiness=readiness,
            exact_requests=tuple(exact_requests),
            request_sources=tuple(
                attempt.source for _request in attempt.worker.requests
            ),
            request_outputs=tuple(outputs),
        )

    cross_terminal = cross.terminal_request_control_transcript
    cross_readiness = cross.request_control_readiness
    cross_exact = tuple(
        observation.resource_boundary.exact_broker_cpu
        for observation in cross.observations
    )
    require_one(
        terminal=cross_terminal,
        readiness=cross_readiness,
        exact_requests=cross_exact,
        request_sources=tuple(
            observation.source for observation in cross.observations
        ),
        request_outputs=tuple(
            observation.output for observation in cross.observations
        ),
    )
    return _canonical_hash(
        {
            "schema_id": (
                "phase-latency-retained-request-receipt-authority-v1"
            ),
            "output_root": {
                "device": output_stat.st_dev,
                "inode": output_stat.st_ino,
                "mode": stat.S_IMODE(output_stat.st_mode),
                "uid": output_stat.st_uid,
            },
            "terminal_manifest_sha256": manifest.manifest_sha256,
            "attempts": authority_records,
            "descriptor_relative_o_nofollow_reread": True,
            "frozen_receipt_parse_and_exact_cpu_join": True,
        }
    )


def evaluate_retained_local_prewarm_bundle(
    bundle: LocalPrewarmEvidenceBundle,
    *,
    output_root: Path,
) -> LocalPrewarmEvaluation:
    """Run the production evaluator with mandatory retained-root authority."""

    return evaluate_local_prewarm_bundle(
        bundle,
        retained_output_root=output_root,
    )


__all__ = [
    "ArtifactIdentity",
    "AsgiResponseHeader",
    "AsgiResponseWitness",
    "AttemptStatus",
    "BrokerChildBirth",
    "BrokerChildBirthCommitment",
    "BrokerChildCpuReceipt",
    "BrokerChildFileDescriptorIdentity",
    "BrokerChildWait4Tombstone",
    "BrokerExecutableIdentity",
    "BrokerForkDenialIdentity",
    "BrokerLifecycleReceiptEvidence",
    "BrokerQuiescenceReceipt",
    "BrokerPostReleaseBaseline",
    "BrokerRequestBindingEvidence",
    "BrokerScratchInventory",
    "CaseAttemptIndex",
    "CleanupEvidence",
    "ConfigurationValueIdentity",
    "ConfigurationIdentity",
    "ControllerChildWatchPrefix",
    "ControllerPreExecGatedChildSample",
    "ControllerRequestResourceSample",
    "ControllerResourceAggregate",
    "ControllerResourceProcessSample",
    "ControllerResourceSampleLogRow",
    "CurrentRuntimeOutputExpectation",
    "DirectionalLlamaReference",
    "EvaluationFailureCode",
    "ExecutionIdentity",
    "ExactBrokerRequestCpuEvidence",
    "ExactProcessIdentity",
    "ExternalCpuStableEdgeRecord",
    "FrameworkThreadBaseline",
    "KERNEL_SANDBOX_ALLOWED_OPERATIONS",
    "KERNEL_SANDBOX_ALLOWED_POLICY_ERRNOS",
    "KERNEL_SANDBOX_DENIED_OPERATIONS",
    "KernelSandboxAttemptTerminalCustody",
    "KernelSandboxAuthorityIdentity",
    "KernelSandboxCapabilityIdentity",
    "KernelSandboxCapabilityTranscriptRow",
    "KernelSandboxDirectoryIdentity",
    "KernelSandboxEvidence",
    "KernelSandboxFileIdentity",
    "KernelSandboxPolicyTargetFixture",
    "KernelSandboxProbeRow",
    "KernelSandboxProcessIdentity",
    "KernelSandboxProfilePolicy",
    "KernelSandboxReadFixture",
    "KernelSandboxRoleEvidence",
    "KernelSandboxScratchFixture",
    "KernelSandboxSentinelObservation",
    "KernelSandboxTerminalTrapObservation",
    "KernelSandboxTrapObservation",
    "ImmutableRuntimeInputCustodyEvidence",
    "ImmutableRuntimeInputDirectoryMember",
    "ImmutableRuntimeInputDirectoryMembership",
    "ImmutableRuntimeInputEntry",
    "ImmutableRuntimeInputPathIdentity",
    "ImmutableRuntimeInputRootAuthority",
    "FailureCode",
    "FailureRecord",
    "LifecycleResourceEvidence",
    "LocalPrewarmAttempt",
    "LocalPrewarmEvaluation",
    "LocalPrewarmEvidenceBundle",
    "NormalizedParseResultWitness",
    "PAIRING_PROJECTION_POLICY_SHA256",
    "SanitizedConfigurationProjection",
    "TerminalRecordDescriptor",
    "TerminalChildWatchLogEvidence",
    "TerminalRequestControlTranscriptEvidence",
    "TerminalRecordManifest",
    "TerminalRecordSubmanifest",
    "TERMINAL_RECORD_POLICY",
    "UninstrumentedRollbackEvidence",
    "UninstrumentedRollbackObservation",
    "MINIMUM_LOCAL_REPETITIONS",
    "NativeSelfCpuCounter",
    "NativeProcessResourceSample",
    "NativeKernelProcessIdentity",
    "NativeVnodeFileDescriptorIdentity",
    "NativeSocketFileDescriptorIdentity",
    "NativePipeFileDescriptorIdentity",
    "NativeKqueueFileDescriptorIdentity",
    "NativeFileDescriptorIdentity",
    "NativeFileDescriptorInventory",
    "NativeThreadInventory",
    "NativeRuntimeImageAttestation",
    "NativeRuntimeScanSample",
    "RawRUsage",
    "RawTimeval",
    "OutputIdentity",
    "PREWARM_FEATURE_FLAG",
    "ProcessCpuCounter",
    "ProcessCpuSnapshot",
    "PRODUCTION_CASE_IDS",
    "ROLLBACK_TERMINAL_RECORD_COUNT",
    "ROLLBACK_TERMINAL_RECORD_KINDS",
    "RSS_DISPOSITION",
    "RequestObservation",
    "RequestControlReadinessEvidence",
    "REQUEST_CONTROL_TRANSCRIPT_MAXIMUM_BYTES",
    "RequestControlReceiptBlobDescriptor",
    "RequestResourceBoundary",
    "ResourcePhase",
    "ResourceSample",
    "RunMode",
    "SampledProcessIdentity",
    "RuntimeArtifactSetIdentity",
    "SourceIdentity",
    "TrustedLauncherIdentity",
    "WorkerMeasurementEnvelope",
    "WorkerForkDenialEvidence",
    "canonical_model_bytes",
    "asgi_response_witness",
    "broker_request_binding_evidence",
    "broker_child_birth_commitment_sha256",
    "broker_lifecycle_receipt_evidence",
    "broker_post_release_baseline",
    "broker_scratch_inventory",
    "configuration_identity",
    "configuration_pairing_projection",
    "configuration_rollback_equivalence_projection",
    "controller_pre_exec_gated_child_sample",
    "controller_resource_sample_log_row",
    "cross_input_configuration_identity",
    "derive_prewarm_harness_sha256",
    "evaluate_local_prewarm_bundle",
    "evaluate_retained_local_prewarm_bundle",
    "external_cpu_stable_edge_record",
    "framework_thread_baseline",
    "request_control_readiness_evidence",
    "require_terminal_child_watch_prefix",
    "require_terminal_request_control_transcript",
    "production_configuration_identity",
    "normalized_parse_result_witness",
    "native_file_descriptor_identity",
    "native_file_descriptor_inventory",
    "native_thread_inventory",
    "rollback_output_configuration_identity",
    "runtime_artifact_set",
    "sanitized_configuration_projection",
    "terminal_record_descriptor",
    "terminal_child_watch_log_evidence",
    "terminal_request_control_transcript_evidence",
    "terminal_record_manifest",
    "terminal_record_submanifest",
    "worker_fork_denial_evidence",
]
