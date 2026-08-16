from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.config import Settings
from tests.benchmarks import latency_prewarm_production_runner as production_runner
from tests.benchmarks.latency_prewarm_contracts import (
    AttemptStatus,
    FailureCode,
    FailureRecord,
    SourceIdentity,
    rollback_output_configuration_identity,
    runtime_artifact_set,
    sanitized_configuration_projection,
    ArtifactIdentity,
    ExecutionIdentity,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _write_private(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        assert os.write(descriptor, raw) == len(raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _execution() -> ExecutionIdentity:
    return ExecutionIdentity(
        application_code_sha256=_sha("app"),
        dependency_manifest_sha256=_sha("lock"),
        parser_runtime_sha256=_sha("python"),
        runtime_artifacts=runtime_artifact_set(
            (
                ArtifactIdentity(
                    path="approved/docling/model.bin",
                    sha256=_sha("model"),
                    size_bytes=1,
                ),
            )
        ),
        harness_sha256=_sha("harness"),
    )


def _configuration():
    settings = asdict(Settings())
    settings.update(
        {
            "max_pages": 100,
            "parser_latency_prewarm_artifacts_sha256": None,
            "parser_latency_prewarm_dependency_sha256": None,
            "parser_latency_prewarm_enabled": False,
            "parser_latency_prewarm_shutdown_grace_seconds": 2.0,
            "parser_latency_prewarm_timeout_seconds": 300.0,
        }
    )
    return rollback_output_configuration_identity(
        startup_timeout_ns=300_000_000_000,
        application_settings_sha256=_sha("settings"),
        worker_environment_sha256=_sha("environment"),
        application_settings_projection=sanitized_configuration_projection(
            domain="application_settings", values=settings
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


def test_direct_rollback_failure_receipt_is_typed_and_self_hashed() -> None:
    source = SourceIdentity(
        case_id="insurance-acord",
        path="fixtures/insurance-acord.pdf",
        filename="insurance-acord.pdf",
        sha256=_sha("source"),
        size_bytes=1,
        page_count=1,
    )
    now = datetime.now(UTC)
    receipt = production_runner._direct_rollback_failure_receipt(
        attempt_id="lat-us02-rollback-insurance-acord",
        source=source,
        execution=_execution(),
        configuration=_configuration(),
        started_at_utc=now,
        completed_at_utc=now,
        controller_elapsed_ns=1,
        worker_return_code=None,
        stdout_size_bytes=0,
        stdout_sha256=hashlib.sha256(b"").hexdigest(),
        stderr_size_bytes=0,
        stderr_sha256=hashlib.sha256(b"").hexdigest(),
        launch_intent_sha256=None,
        launch_record_sha256=None,
        phase_deadline_log_sha256=None,
        phase_ack_log_sha256=None,
        watchdog_terminal_sha256=None,
        watchdog_terminal=None,
        launcher_terminal_evidence=None,
        cleanup_attempted=True,
        worker_process_group_gone=False,
        watchdog_reaped=False,
        watchdog_process_group_gone=False,
        controller_resources=None,
        controller_resources_validation_failed=True,
        status=AttemptStatus.ERROR,
        failure=FailureRecord(
            code=FailureCode.WORKER_PROTOCOL_FAILED,
            stage="shutdown",
            detail_sha256=_sha("failure"),
        ),
    )
    assert receipt.status is AttemptStatus.ERROR
    assert receipt.record_sha256 == production_runner._canonical_sha256(
        receipt.model_dump(mode="json", exclude={"record_sha256"})
    )


def test_campaign_failure_writes_nonfinal_prefix_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"

    class InjectedFailure(RuntimeError):
        pass

    def fail_after_retaining_prefix(**_fields: object) -> object:
        output.mkdir(mode=0o700)
        terminal = output / "terminal"
        terminal.mkdir(mode=0o700)
        _write_private(output / "lat-us02-production-plan.json", b"{}")
        _write_private(terminal / "attempt-launch-intent.json", b"{}")
        raise InjectedFailure("stop after the retained prefix")

    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_after_retaining_prefix,
    )
    with pytest.raises(InjectedFailure):
        production_runner.run_production_campaign(
            workspace=tmp_path,
            output_directory=output,
            registry_path=tmp_path / "registry.json",
            llama_reference_path=tmp_path / "reference.json",
            artifacts_path=tmp_path / "artifacts",
            artifacts_label="artifacts",
            workspace_model_source=tmp_path / "model.py",
            classifier_source=tmp_path / "classifier.py",
            tesseract_executable=tmp_path / "tesseract",
            tesseract_data_path=tmp_path / "tessdata",
        )
    marker = production_runner.CampaignFailureMarker.model_validate_json(
        (output / "campaign-failure-marker.json").read_bytes()
    )
    assert marker.status == "incomplete_custody"
    assert not marker.producer_groups_esrch
    assert not marker.writer_fds_closed
    assert not marker.final_closure_claimed
    assert tuple(item.relative_path for item in marker.entries) == (
        "lat-us02-production-plan.json",
        "terminal/attempt-launch-intent.json",
    )
    assert tuple(sorted(path.name for path in output.iterdir())) == (
        "campaign-failure-marker.json",
        "lat-us02-production-plan.json",
        "terminal",
    )


def test_post_plan_no_launch_failure_commits_quiescent_final_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"

    class InjectedFailure(RuntimeError):
        pass

    def fail_after_plan(**_fields: object) -> object:
        output.mkdir(mode=0o700)
        (output / "terminal").mkdir(mode=0o700)
        _write_private(output / "lat-us02-production-plan.json", b"{}")
        raise InjectedFailure("stop after plan, before any launch intent")

    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_after_plan,
    )
    with pytest.raises(InjectedFailure):
        production_runner.run_production_campaign(
            workspace=tmp_path,
            output_directory=output,
            registry_path=tmp_path / "registry.json",
            llama_reference_path=tmp_path / "reference.json",
            artifacts_path=tmp_path / "artifacts",
            artifacts_label="artifacts",
            workspace_model_source=tmp_path / "model.py",
            classifier_source=tmp_path / "classifier.py",
            tesseract_executable=tmp_path / "tesseract",
            tesseract_data_path=tmp_path / "tessdata",
        )
    closure = production_runner.CampaignClosureManifest.model_validate_json(
        (output / "campaign-closure.json").read_bytes()
    )
    assert closure.status == "failure"
    assert closure.failure is not None
    assert closure.failure_quiescence is not None
    assert closure.failure_quiescence.launch_intent_count == 0
    assert closure.failure_quiescence.launch_dispositions == ()
    assert (
        closure.failure_quiescence.barrier_entry_thread_inventory.thread_count
        == 1
    )
    assert closure.failure_quiescence.precommit_thread_inventory.thread_count == 1
    assert (
        closure.failure_quiescence.writable_output_prefix_descriptor_fds == ()
    )
    assert not (output / "campaign-failure-marker.json").exists()
    assert tuple(item.relative_path for item in closure.entries) == (
        "lat-us02-production-plan.json",
    )


@pytest.mark.parametrize(
    "orphan_name",
    (
        "orphan-launch-record.json",
        "orphan-watchdog-launcher.jsonl",
        "orphan-watchdog-terminal.json",
        "orphan-receipt.json",
    ),
)
def test_post_plan_orphan_terminal_artifact_remains_nonfinal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    orphan_name: str,
) -> None:
    output = tmp_path / "campaign"

    class InjectedFailure(RuntimeError):
        pass

    def fail_after_orphan(**_fields: object) -> object:
        output.mkdir(mode=0o700)
        terminal = output / "terminal"
        terminal.mkdir(mode=0o700)
        _write_private(output / "lat-us02-production-plan.json", b"{}")
        _write_private(terminal / orphan_name, b"{}")
        raise InjectedFailure("stop after retaining an orphan terminal artifact")

    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_after_orphan,
    )
    with pytest.raises(InjectedFailure):
        production_runner.run_production_campaign(
            workspace=tmp_path,
            output_directory=output,
            registry_path=tmp_path / "registry.json",
            llama_reference_path=tmp_path / "reference.json",
            artifacts_path=tmp_path / "artifacts",
            artifacts_label="artifacts",
            workspace_model_source=tmp_path / "model.py",
            classifier_source=tmp_path / "classifier.py",
            tesseract_executable=tmp_path / "tesseract",
            tesseract_data_path=tmp_path / "tessdata",
        )
    assert not (output / "campaign-closure.json").exists()
    marker = production_runner.CampaignFailureMarker.model_validate_json(
        (output / "campaign-failure-marker.json").read_bytes()
    )
    assert marker.status == "incomplete_custody"
    assert f"terminal/{orphan_name}" in {
        item.relative_path for item in marker.entries
    }


def test_failure_closure_with_held_output_writer_remains_nonfinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    held_writer: int | None = None

    class InjectedFailure(RuntimeError):
        pass

    def fail_with_writer(**_fields: object) -> object:
        nonlocal held_writer
        output.mkdir(mode=0o700)
        (output / "terminal").mkdir(mode=0o700)
        plan = output / "lat-us02-production-plan.json"
        _write_private(plan, b"{}")
        held_writer = os.open(
            plan,
            os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        raise InjectedFailure("retain a writable output descriptor")

    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_with_writer,
    )
    try:
        with pytest.raises(InjectedFailure):
            production_runner.run_production_campaign(
                workspace=tmp_path,
                output_directory=output,
                registry_path=tmp_path / "registry.json",
                llama_reference_path=tmp_path / "reference.json",
                artifacts_path=tmp_path / "artifacts",
                artifacts_label="artifacts",
                workspace_model_source=tmp_path / "model.py",
                classifier_source=tmp_path / "classifier.py",
                tesseract_executable=tmp_path / "tesseract",
                tesseract_data_path=tmp_path / "tessdata",
            )
    finally:
        if held_writer is not None:
            os.close(held_writer)
    assert not (output / "campaign-closure.json").exists()
    marker = production_runner.CampaignFailureMarker.model_validate_json(
        (output / "campaign-failure-marker.json").read_bytes()
    )
    assert marker.status == "incomplete_custody"


def test_failure_closure_with_second_controller_thread_remains_nonfinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"
    thread_started = threading.Event()
    release_thread = threading.Event()

    class InjectedFailure(RuntimeError):
        pass

    def hold_second_thread() -> None:
        thread_started.set()
        release_thread.wait(timeout=10)

    def fail_with_thread(**_fields: object) -> object:
        output.mkdir(mode=0o700)
        (output / "terminal").mkdir(mode=0o700)
        _write_private(output / "lat-us02-production-plan.json", b"{}")
        raise InjectedFailure("retain a second controller thread")

    thread = threading.Thread(target=hold_second_thread, daemon=True)
    thread.start()
    assert thread_started.wait(timeout=2)
    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_with_thread,
    )
    try:
        with pytest.raises(InjectedFailure):
            production_runner.run_production_campaign(
                workspace=tmp_path,
                output_directory=output,
                registry_path=tmp_path / "registry.json",
                llama_reference_path=tmp_path / "reference.json",
                artifacts_path=tmp_path / "artifacts",
                artifacts_label="artifacts",
                workspace_model_source=tmp_path / "model.py",
                classifier_source=tmp_path / "classifier.py",
                tesseract_executable=tmp_path / "tesseract",
                tesseract_data_path=tmp_path / "tessdata",
            )
    finally:
        release_thread.set()
        thread.join(timeout=2)
    assert not (output / "campaign-closure.json").exists()
    marker = production_runner.CampaignFailureMarker.model_validate_json(
        (output / "campaign-failure-marker.json").read_bytes()
    )
    assert marker.status == "incomplete_custody"


def test_typed_intent_without_authoritative_terminal_receipt_remains_nonfinal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "campaign"

    class InjectedFailure(RuntimeError):
        pass

    def fail_after_legacy_rootless_failure(**_fields: object) -> object:
        output.mkdir(mode=0o700)
        terminal = output / "terminal"
        terminal.mkdir(mode=0o700)
        _write_private(output / "lat-us02-production-plan.json", b"{}")
        attempt_id = "lat-us02-rollback-insurance-acord"
        intent_fields = {
            "schema_id": "phase-latency-prewarm-launch-intent-v1",
            "attempt_id": attempt_id,
            "retained_at_utc": datetime.now(UTC),
            "controller": production_runner._process_identity(os.getpid()),
            "absolute_deadline_monotonic_ns": max(
                1, production_runner.time.monotonic_ns() + 1_000_000_000
            ),
            "worker_command_sha256": _sha("worker-command"),
            "worker_environment_sha256": _sha("worker-environment"),
            "broker_command_template_sha256": None,
            "broker_environment_sha256": None,
            "capability_scope_sha256": None,
            "capability_nonce_sha256": None,
            "managed_group_policy": "direct-worker-default-off-v1",
            "release_policy": (
                "o-excl-intent-then-watchdog-ready-then-one-byte-release-v1"
            ),
            "watchdog_policy": (
                "separate-session-exact-identity-absolute-deadline-term-kill-v1"
            ),
        }
        intent = production_runner.ProductionLaunchIntent(
            **intent_fields,
            intent_sha256=production_runner._canonical_sha256(intent_fields),
        )
        production_runner.write_private_canonical(
            terminal / f"{attempt_id}-launch-intent.json", intent
        )
        failure_fields = {
            "schema_id": "phase-latency-prewarm-launch-failure-v1",
            "attempt_id": attempt_id,
            "intent_sha256": intent.intent_sha256,
            "retained_monotonic_ns": max(
                1, production_runner.time.monotonic_ns()
            ),
            "controller": intent.controller,
            "worker_started": False,
            "broker_started": False,
            "watchdog_started": True,
            "launch_record_retained": False,
            "error_type_sha256": _sha("rootless-launch-failure"),
        }
        launch_failure = production_runner.ProductionLaunchFailureRecord(
            **failure_fields,
            record_sha256=production_runner._canonical_sha256(failure_fields),
        )
        production_runner.write_private_canonical(
            terminal / f"{attempt_id}-launch-failure.json", launch_failure
        )
        raise InjectedFailure("legacy failure lacks ECHILD/no-group proof")

    monkeypatch.setattr(
        production_runner,
        "_run_production_campaign_with_success_closure",
        fail_after_legacy_rootless_failure,
    )
    with pytest.raises(InjectedFailure):
        production_runner.run_production_campaign(
            workspace=tmp_path,
            output_directory=output,
            registry_path=tmp_path / "registry.json",
            llama_reference_path=tmp_path / "reference.json",
            artifacts_path=tmp_path / "artifacts",
            artifacts_label="artifacts",
            workspace_model_source=tmp_path / "model.py",
            classifier_source=tmp_path / "classifier.py",
            tesseract_executable=tmp_path / "tesseract",
            tesseract_data_path=tmp_path / "tessdata",
        )
    assert not (output / "campaign-closure.json").exists()
    marker = production_runner.CampaignFailureMarker.model_validate_json(
        (output / "campaign-failure-marker.json").read_bytes()
    )
    assert marker.status == "incomplete_custody"
