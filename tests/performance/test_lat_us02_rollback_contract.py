"""Closed single-flag rollback evidence contracts for LAT-US02."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import Settings

from tests.benchmarks.latency_prewarm_contracts import (
    ArtifactIdentity,
    BROKERED_TERMINAL_RECORD_KINDS,
    CROSS_INPUT_TERMINAL_RECORD_KINDS,
    CleanupEvidence,
    CurrentRuntimeOutputExpectation,
    ExecutionIdentity,
    FileTreeIdentityEvidence,
    OutputIdentity,
    PRODUCTION_CASE_IDS,
    SourceIdentity,
    TerminalRecordDescriptor,
    UninstrumentedRollbackEvidence,
    UninstrumentedRollbackObservation,
    normalized_parse_result_witness,
    rollback_output_configuration_identity,
    runtime_artifact_set,
    sanitized_configuration_projection,
    terminal_record_descriptor,
    terminal_record_manifest,
    terminal_record_submanifest,
    _require_production_terminal_manifest_tail,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _execution() -> ExecutionIdentity:
    artifacts = runtime_artifact_set(
        (
            ArtifactIdentity(
                path="approved/docling/model.bin",
                sha256=_sha("model"),
                size_bytes=1,
            ),
        )
    )
    return ExecutionIdentity(
        application_code_sha256=_sha("app"),
        dependency_manifest_sha256=_sha("lock"),
        parser_runtime_sha256=_sha("python"),
        runtime_artifacts=artifacts,
        harness_sha256=_sha("harness"),
    )


def _rollback_receipt_jsonl(
    *,
    case_id: str,
    source: SourceIdentity,
    configuration: object,
    output: OutputIdentity,
    witness: object,
    boundary: FileTreeIdentityEvidence,
) -> str:
    attempt_id = f"lat-us02-rollback-{case_id}"
    raw_worker: dict[str, object] = {
        "schema_id": "phase-latency-direct-rollback-raw-worker-v1",
        "attempt_id": attempt_id,
        "source": source.model_dump(mode="json"),
        "configuration_sha256": configuration.sha256,
        "output": output.model_dump(mode="json"),
        "normalized_output_witness": witness.model_dump(mode="json"),
        "response_content_type_sha256": _sha("content-type"),
        "request_started_monotonic_ns": 1,
        "request_completed_monotonic_ns": 2,
        "startup_duration_ns": 1,
        "shutdown_duration_ns": 1,
        "cold_resource": {},
        "shutdown_resource": {},
        "runtime_artifact_before_requests": boundary.model_dump(mode="json"),
        "runtime_artifact_after_shutdown": boundary.model_dump(mode="json"),
        "application_identity_validated": True,
        "dependency_identity_validated": True,
        "parser_runtime_identity_validated": True,
        "runtime_artifact_identity_validated": True,
        "configuration_identity_validated": True,
        "feature_flag_disabled": True,
        "private_broker_capability_present": False,
        "broker_started": False,
        "worker_fork_denial_installed": False,
        "supervisor_bypassed_to_exact_target": True,
        "production_asgi_lifespan_exercised": True,
        "network_isolation_validated": True,
        "hosted_calls": 0,
        "egress_bytes": 0,
    }
    raw_worker["record_sha256"] = hashlib.sha256(
        json.dumps(
            raw_worker,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    stdout = (
        json.dumps(
            raw_worker,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    receipt: dict[str, object] = {
        "schema_id": "phase-latency-direct-rollback-attempt-receipt-v1",
        "attempt_id": attempt_id,
        "source": source.model_dump(mode="json"),
        "execution": _execution().model_dump(mode="json"),
        "configuration": configuration.model_dump(mode="json"),
        "started_at_utc": "2026-08-10T00:00:00Z",
        "completed_at_utc": "2026-08-10T00:00:01Z",
        "controller_elapsed_ns": 1,
        "worker_return_code": 0,
        "stdout_size_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_size_bytes": 0,
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "launch_intent_sha256": _sha("intent"),
        "launch_record_sha256": _sha("launch"),
        "phase_deadline_log_sha256": _sha("phase-deadlines"),
        "phase_ack_log_sha256": _sha("phase-acks"),
        "phase_sequence_count": 3,
        "watchdog_terminal_sha256": _sha("watchdog"),
        "watchdog_terminal_observed_sha256": _sha("watchdog"),
        "watchdog_terminal": {},
        "launcher_terminal_evidence": {},
        "watchdog_reaped": True,
        "watchdog_process_group_gone": True,
        "worker_reaped": True,
        "worker_process_group_gone": True,
        "forced_group_cleanup_required": False,
        "controller_resources": {},
        "raw_worker": raw_worker,
        "status": "success",
    }
    receipt["record_sha256"] = hashlib.sha256(
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return (
        json.dumps(
            receipt,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
def _observation(case_id: str, index: int) -> UninstrumentedRollbackObservation:
    source = SourceIdentity(
        case_id=case_id,
        path=f"fixtures/{case_id}.pdf",
        filename=f"{case_id}.pdf",
        sha256=_sha(f"source-{case_id}"),
        size_bytes=1,
        page_count=1,
    )
    witness = normalized_parse_result_witness(
        {
            "document": {
                "filename": f"{case_id}.pdf",
                "sha256": source.sha256,
            },
            "pages": [],
            "processing": {
                "engine": "local",
                "ocr_engine": "tesseract",
                "ocr_languages": ["eng"],
            },
            "schema_version": "1.0",
            "warnings": [],
        }
    )
    semantic = witness.normalized_sha256
    output = OutputIdentity(
        sha256=_sha(f"raw-{case_id}"),
        normalized_sha256=semantic,
        semantic_sha256=semantic,
        api_contract_sha256=witness.api_contract_sha256,
        provenance_sha256=witness.provenance_sha256,
        concerns_sha256=witness.concerns_sha256,
        deterministic_ids_sha256=witness.deterministic_ids_sha256,
        size_bytes=1,
        media_type="application/json",
        validation="ParseResult",
        normalization_policy="json_exclude_processing_duration_ms_v1",
    )
    boundary = FileTreeIdentityEvidence(
        sha256=_sha("artifact-content"),
        metadata_sha256=_sha("artifact-metadata"),
        file_count=1,
        aggregate_bytes=1,
    )
    configuration = rollback_output_configuration_identity(
        startup_timeout_ns=300_000_000_000,
        application_settings_sha256=_sha("settings-off"),
        worker_environment_sha256=_sha("environment-direct"),
        application_settings_projection=sanitized_configuration_projection(
            domain="application_settings",
            values={
                **asdict(Settings()),
                "max_pages": 100,
                "parser_latency_prewarm_artifacts_sha256": None,
                "parser_latency_prewarm_dependency_sha256": None,
                "parser_latency_prewarm_enabled": False,
                "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
                "parser_latency_prewarm_timeout_seconds": 300.0,
            },
        ),
        worker_environment_projection=sanitized_configuration_projection(
            domain="worker_environment",
            values={
                "PATH": "/usr/bin",
                "PARSER_LATENCY_PREWARM_ENABLED": "false",
            },
        ),
        artifacts_path="approved/docling",
        artifacts_path_identity_sha256=_sha("artifact-path"),
        tesseract_executable="/opt/tesseract",
        tesseract_data_path="/opt/tessdata",
    )
    receipt_jsonl = _rollback_receipt_jsonl(
        case_id=case_id,
        source=source,
        configuration=configuration,
        output=output,
        witness=witness,
        boundary=boundary,
    )
    return UninstrumentedRollbackObservation(
        case_id=case_id,
        source=source,
        expectation=CurrentRuntimeOutputExpectation(
            case_id=case_id,
            source_sha256=source.sha256,
            semantic_sha256=semantic,
        ),
        configuration=configuration,
        output=output,
        normalized_output_witness=witness,
        runtime_artifact_before_requests=boundary,
        runtime_artifact_after_shutdown=boundary,
        cleanup=CleanupEvidence(
            shutdown_duration_ns=1,
            cleanup_completed=True,
            worker_exited=True,
            worker_reaped=True,
            exit_code=0,
            owned_process_count_after_shutdown=0,
            all_owned_processes_reaped=True,
            threads_returned_to_baseline=True,
            file_descriptors_returned_to_baseline=True,
            state_retention_detected=False,
            oom_observed=False,
            unbounded_rss_growth_observed=False,
            worker_process_group_count=1,
            broker_process_group_count=0,
            controller_watchdog_process_group_count=1,
            owned_process_group_count=2,
        ),
        canonical_receipt_jsonl=receipt_jsonl,
        receipt_sha256=hashlib.sha256(receipt_jsonl.encode()).hexdigest(),
        artifact_observation_sha256=_sha(f"artifact-observation-{index}"),
    )


def _evidence() -> UninstrumentedRollbackEvidence:
    observations = tuple(
        _observation(case_id, index)
        for index, case_id in enumerate(PRODUCTION_CASE_IDS, start=1)
    )
    entries: list[TerminalRecordDescriptor] = []
    previous = "0" * 64
    sequence = 0
    for ordinal, observation in enumerate(observations, start=1):
        attempt_id = f"lat-us02-rollback-{observation.case_id}"
        for kind, content_sha256, status in (
            ("launch-intent", _sha(f"intent-{ordinal}"), None),
            ("launch-record", _sha(f"launch-{ordinal}"), None),
            ("phase-deadlines", _sha(f"phase-deadlines-{ordinal}"), None),
            ("phase-acks", _sha(f"phase-acks-{ordinal}"), None),
            ("watchdog-terminal", _sha(f"watchdog-terminal-{ordinal}"), None),
            ("launcher-ledger", _sha(f"launcher-ledger-{ordinal}"), None),
            ("attempt-receipt", observation.receipt_sha256, "success"),
            (
                "artifact-observation",
                observation.artifact_observation_sha256,
                None,
            ),
        ):
            sequence += 1
            entry = terminal_record_descriptor(
                sequence=sequence,
                previous_entry_sha256=previous,
                retained_monotonic_ns=sequence,
                segment="rollback",
                record_kind=kind,
                relative_path=f"terminal/{sequence:04d}-{kind}.json",
                topology="direct-default-off-v1",
                attempt_id=attempt_id,
                case_id=observation.case_id,
                case_ordinal=ordinal,
                attempt_status=status,
                content_sha256=content_sha256,
                size_bytes=1,
                file_mode=0o600,
                reopened_no_follow_after_fsync=True,
            )
            entries.append(entry)
            previous = entry.entry_sha256
    terminal_records = terminal_record_submanifest(tuple(entries))
    return UninstrumentedRollbackEvidence(
        schema_id="phase-latency-prewarm-rollback-output-gate-v1",
        generated_at_utc=datetime(2026, 8, 10, tzinfo=UTC),
        execution=_execution(),
        observations=observations,
        terminal_records=terminal_records,
        terminal_record_manifest_sha256=terminal_records.manifest_sha256,
    )


def test_direct_rollback_gate_covers_all_cases_without_broker() -> None:
    evidence = _evidence()

    assert tuple(item.case_id for item in evidence.observations) == (
        PRODUCTION_CASE_IDS
    )
    assert all(not item.broker_started for item in evidence.observations)
    assert all(
        item.configuration.execution_topology == "direct-default-off-v1"
        for item in evidence.observations
    )


def test_direct_rollback_receipt_bytes_bind_the_retained_output_witness() -> None:
    evidence = _evidence()
    first, second = evidence.observations[:2]
    with pytest.raises(ValidationError, match="rollback output"):
        UninstrumentedRollbackObservation.model_validate(
            {
                **first.model_dump(mode="python"),
                "canonical_receipt_jsonl": second.canonical_receipt_jsonl,
                "receipt_sha256": second.receipt_sha256,
            }
        )


def test_rollback_gate_rejects_missing_or_reordered_case() -> None:
    evidence = _evidence()
    with pytest.raises(ValidationError, match="all 15 cases in order"):
        UninstrumentedRollbackEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "observations": tuple(reversed(evidence.observations)),
            }
        )


def test_rollback_observation_rejects_semantic_or_broker_drift() -> None:
    observation = _evidence().observations[0]
    changed_output = observation.output.model_copy(
        update={"semantic_sha256": _sha("changed")}
    )
    with pytest.raises(ValidationError):
        UninstrumentedRollbackObservation.model_validate(
            {
                **observation.model_dump(mode="python"),
                "output": changed_output,
            }
        )
    with pytest.raises(ValidationError):
        UninstrumentedRollbackObservation.model_validate(
            {**observation.model_dump(mode="python"), "broker_started": True}
        )


@pytest.mark.parametrize(
    "field",
    (
        "normalized_sha256",
        "api_contract_sha256",
        "provenance_sha256",
        "concerns_sha256",
        "deterministic_ids_sha256",
    ),
)
def test_rollback_witness_rejects_every_component_mutation(field: str) -> None:
    observation = _evidence().observations[0]
    changed_output = observation.output.model_copy(
        update={field: _sha(f"changed-{field}")}
    )
    with pytest.raises(ValidationError):
        UninstrumentedRollbackObservation.model_validate(
            {
                **observation.model_dump(mode="python"),
                "output": changed_output,
            }
        )


def test_rollback_witness_rejects_mutated_normalized_bytes() -> None:
    observation = _evidence().observations[0]
    changed = observation.normalized_output_witness.model_copy(
        update={"canonical_json_base64": "e30="}
    )
    with pytest.raises(ValidationError):
        UninstrumentedRollbackObservation.model_validate(
            {
                **observation.model_dump(mode="python"),
                "normalized_output_witness": changed,
            }
        )


def test_rollback_terminal_manifest_is_recomputed_and_temporally_closed() -> None:
    evidence = _evidence()
    with pytest.raises(ValidationError, match="manifest"):
        UninstrumentedRollbackEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "terminal_record_manifest_sha256": _sha("fabricated"),
            }
        )


def test_full_terminal_manifest_binds_exact_rollback_gate_after_120_rows() -> None:
    evidence = _evidence()
    entries = list(evidence.terminal_records.entries)
    previous = entries[-1].entry_sha256
    for kind in ("rollback-evidence", "rollback-submanifest"):
        sequence = len(entries) + 1
        entry = terminal_record_descriptor(
            sequence=sequence,
            previous_entry_sha256=previous,
            retained_monotonic_ns=sequence,
            segment="rollback_gate",
            record_kind=kind,
            relative_path=f"terminal/{sequence:04d}-{kind}.json",
            topology="campaign-controller-v1",
            content_sha256=_sha(kind),
            size_bytes=1,
            file_mode=0o600,
            reopened_no_follow_after_fsync=True,
        )
        entries.append(entry)
        previous = entry.entry_sha256
    manifest = terminal_record_manifest(
        entries=tuple(entries), rollback_prefix=evidence.terminal_records
    )
    assert manifest.rollback_prefix_entry_count == 120
    assert tuple(item.record_kind for item in manifest.entries[-2:]) == (
        "rollback-evidence",
        "rollback-submanifest",
    )
    with pytest.raises(ValidationError):
        type(manifest).model_validate(
            {
                **manifest.model_dump(mode="python"),
                "entries": (*manifest.entries[:-2], *reversed(manifest.entries[-2:])),
            }
        )
    entries = evidence.terminal_records.entries
    with pytest.raises(ValidationError):
        UninstrumentedRollbackEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "terminal_records": {
                    **evidence.terminal_records.model_dump(mode="python"),
                    "entries": (*entries[:3], *entries[6:]),
                    "entry_count": len(entries) - 3,
                },
            }
        )


def test_production_terminal_tail_rejects_missing_swapped_or_extra_records() -> None:
    entries: list[TerminalRecordDescriptor] = []
    sequence = 123
    previous = _sha("rollback-gate-head")

    def append(
        *,
        segment: str,
        kind: str,
        topology: str,
        attempt_id: str | None,
        case_id: str | None = None,
        case_ordinal: int | None = None,
    ) -> None:
        nonlocal sequence, previous
        entry = terminal_record_descriptor(
            sequence=sequence,
            previous_entry_sha256=previous,
            retained_monotonic_ns=sequence,
            segment=segment,
            record_kind=kind,
            relative_path=f"terminal/tail-{sequence:04d}-{kind}.json",
            topology=topology,
            attempt_id=attempt_id,
            case_id=case_id,
            case_ordinal=case_ordinal,
            attempt_status=(
                "success"
                if kind in {"attempt-receipt", "cross-input-receipt"}
                else None
            ),
            content_sha256=_sha(f"tail-content-{sequence}"),
            size_bytes=1,
        )
        entries.append(entry)
        previous = entry.entry_sha256
        sequence += 1

    for kind in CROSS_INPUT_TERMINAL_RECORD_KINDS:
        append(
            segment="cross_input",
            kind=kind,
            topology="fork-denied-worker-external-tesseract-broker-v1",
            attempt_id="lat-us02-cross-input-isolation",
        )
    attempts: list[SimpleNamespace] = []
    indexes: list[SimpleNamespace] = []
    for ordinal, case_id in enumerate(PRODUCTION_CASE_IDS, 1):
        predecessor_ids: list[str] = []
        enabled_ids: list[str] = []
        for repetition in (1, 2):
            for mode, retained in (
                ("predecessor", predecessor_ids),
                ("enabled", enabled_ids),
            ):
                attempt_id = (
                    f"lat-us02-{case_id}-{mode}-r{repetition:02d}"
                )
                retained.append(attempt_id)
                attempts.append(
                    SimpleNamespace(attempt_id=attempt_id, case_id=case_id)
                )
                for kind in BROKERED_TERMINAL_RECORD_KINDS:
                    append(
                        segment="paired",
                        kind=kind,
                        topology=(
                            "fork-denied-worker-external-tesseract-broker-v1"
                        ),
                        attempt_id=attempt_id,
                        case_id=case_id,
                        case_ordinal=ordinal,
                    )
        indexes.append(
            SimpleNamespace(
                case_id=case_id,
                predecessor_attempt_ids=tuple(predecessor_ids),
                enabled_attempt_ids=tuple(enabled_ids),
            )
        )
    append(
        segment="campaign_final",
        kind="artifact-observation",
        topology="campaign-controller-v1",
        attempt_id=None,
    )
    prefix = (None,) * 122
    manifest = SimpleNamespace(
        rollback_prefix_entry_count=120,
        entries=(*prefix, *entries),
    )
    _require_production_terminal_manifest_tail(
        manifest,
        attempts=tuple(attempts),
        case_indexes=tuple(indexes),
    )
    for changed in (
        (*prefix, *entries[:20], *entries[21:]),
        (*prefix, entries[0], entries[2], entries[1], *entries[3:]),
        (*prefix, *entries, entries[-1]),
    ):
        with pytest.raises(ValueError):
            _require_production_terminal_manifest_tail(
                SimpleNamespace(
                    rollback_prefix_entry_count=120,
                    entries=changed,
                ),
                attempts=tuple(attempts),
                case_indexes=tuple(indexes),
            )


def test_rollback_observation_rejects_broker_group_cleanup_claim() -> None:
    observation = _evidence().observations[0]
    changed_cleanup = observation.cleanup.model_copy(
        update={
            "broker_process_group_count": 1,
            "owned_process_group_count": 3,
        }
    )
    with pytest.raises(ValidationError, match="cleanup is blocking"):
        UninstrumentedRollbackObservation.model_validate(
            {
                **observation.model_dump(mode="python"),
                "cleanup": changed_cleanup,
            }
        )
