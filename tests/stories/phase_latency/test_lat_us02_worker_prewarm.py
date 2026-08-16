"""LAT-US02 owned parser-worker startup, reuse, and shutdown behavior."""

from __future__ import annotations

import asyncio
import contextlib
import gc
import hashlib
import os
import subprocess
import sys
import textwrap
import threading
import time
import weakref
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil
import pytest
from fastapi.testclient import TestClient

import app.api as api_module
import app.services.parser_worker as worker_module
from app.config import Settings, get_settings
from app.errors import ExtractionEngineUnavailableError
from app.main import create_app
from app.services.input_documents import InputKind
from app.services.parser_worker import (
    DependencyIdentity,
    FileTreeIdentity,
    OwnedConverters,
    ParserWorkerRuntime,
    WorkerState,
    artifact_identity,
)
from app.services.tesseract_broker_native import (
    NativeFileDescriptorIdentity,
    NativeFileDescriptorInventory,
    NativePipeFileDescriptorIdentity,
    NativeThreadInventory,
)
from app.services.tesseract_broker_protocol import (
    BrokerPostReleaseBaseline,
    KernelProcessIdentity,
    canonical_sha256,
)


VALID_PDF = b"%PDF-1.7\n% LAT-US02 bounded control\n"
ARTIFACT_IDENTITY = FileTreeIdentity(
    sha256="a" * 64,
    metadata_sha256="c" * 64,
    file_count=2,
    aggregate_bytes=32,
)
DEPENDENCY_IDENTITY = DependencyIdentity(
    sha256="b" * 64,
    distribution_count=15,
    verified_file_count=30,
    verified_aggregate_bytes=64,
    tesseract_version="tesseract 5.test",
    language_count=1,
)
CONVERTER_IDENTITY = "d" * 64
OFFLINE_IDENTITY = "e" * 64


class _FakeConverter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.initialized_pipelines: dict[object, object] = {name: object()}
        self.natural_initializations: list[object] = []

    def initialize_pipeline(self, input_format: object) -> None:
        self.natural_initializations.append(input_format)


@dataclass(slots=True)
class _OwnedFixture:
    owned: OwnedConverters
    pdf: _FakeConverter
    image: _FakeConverter


def _owned_fixture(
    *,
    classifier: bool = False,
    description: bool = False,
    lock: threading.Lock | None = None,
) -> _OwnedFixture:
    pdf = _FakeConverter("pdf")
    image = _FakeConverter("image")
    owned = OwnedConverters(
        pdf=pdf,
        image=image,
        conversion_lock=lock or threading.Lock(),
        picture_classifier_enabled=classifier,
        picture_description_enabled=description,
    )
    return _OwnedFixture(owned=owned, pdf=pdf, image=image)


class _UnitPhaseControl:
    def __init__(self, owner_pid: int, deadline_ns: int) -> None:
        self.attempt_id = "unit-attempt"
        self.worker_pid = owner_pid
        self._deadline_ns = deadline_ns
        self._phase = "startup"

    def snapshot(self) -> Any:
        return SimpleNamespace(
            phase_record=SimpleNamespace(
                phase=self._phase,
                attempt_id=self.attempt_id,
                deadline_monotonic_ns=self._deadline_ns,
            )
        )

    def advance(self, phase: str, deadline_monotonic_ns: int) -> Any:
        self._phase = phase
        self._deadline_ns = deadline_monotonic_ns
        return self.snapshot()

    def close(self) -> None:
        return None


class _UnitRequestControl:
    def __init__(
        self,
        owner_pid: int,
        broker_pid: int,
        broker_start_abstime: int,
        attempt_nonce_sha256: str,
        scope_sha256: str,
    ) -> None:
        self.worker_identity = SimpleNamespace(pid=owner_pid)
        self.broker_identity = SimpleNamespace(
            pid=broker_pid,
            start_abstime=broker_start_abstime,
        )
        self.attempt_nonce_sha256 = attempt_nonce_sha256
        self.scope_sha256 = scope_sha256
        self.runtime: Any | None = None

    def bind_runtime(self, runtime: Any) -> None:
        baseline = runtime.framework_thread_baseline()
        assert baseline.anyio_worker_native_thread_id > 0
        assert baseline.asyncio_executor_native_thread_id > 0
        assert (
            baseline.anyio_worker_native_thread_id
            != baseline.asyncio_executor_native_thread_id
        )
        self.runtime = runtime

    def close(self) -> None:
        return None


def _unit_broker_post_release_baseline(
    broker_pid: int,
    broker_start_abstime: int,
) -> BrokerPostReleaseBaseline:
    process = KernelProcessIdentity(
        broker_pid,
        broker_start_abstime,
        os.getpid(),
        broker_pid,
        broker_pid,
    )
    thread_digest_mapping = {
        "schema_id": "darwin-detailed-thread-inventory-v1",
        "process": asdict(process),
        "identity_basis": (
            "darwin-proc_pidinfo-PROC_PIDLISTTHREADS-uint64-v1"
        ),
        "thread_ids": [9001],
        "thread_count": 1,
    }

    def thread_inventory(started: int) -> NativeThreadInventory:
        return NativeThreadInventory(
            schema_id=thread_digest_mapping["schema_id"],
            process=process,
            identity_basis=thread_digest_mapping["identity_basis"],
            first_scan_started_monotonic_ns=started,
            first_scan_completed_monotonic_ns=started + 1,
            second_scan_started_monotonic_ns=started + 2,
            second_scan_completed_monotonic_ns=started + 3,
            thread_ids=(9001,),
            thread_count=1,
            inventory_sha256=canonical_sha256(thread_digest_mapping),
        )

    pipe = NativePipeFileDescriptorIdentity(
        device=1,
        inode=2,
        mode=0o10600,
        nlink=1,
        uid=os.getuid(),
        gid=os.getgid(),
        pipe_status=0,
        local_handle_sha256="7" * 64,
        peer_handle_sha256="8" * 64,
    )

    def descriptor(fd: int) -> NativeFileDescriptorIdentity:
        mapping = {
            "fd": fd,
            "kernel_type": 6,
            "open_flags": 0,
            "kernel_status_flags": 0,
            "descriptor_offset": 0,
            "descriptor_type": 6,
            "guard_flags": 0,
            "close_on_exec": False,
            "close_on_fork": False,
            "guarded": False,
            "shared": False,
            "vnode": None,
            "socket": None,
            "pipe": asdict(pipe),
            "kqueue": None,
        }
        return NativeFileDescriptorIdentity(
            **{
                **mapping,
                "pipe": pipe,
                "record_sha256": canonical_sha256(mapping),
            }
        )

    pre_descriptors = tuple(descriptor(fd) for fd in (0, 7, 8))
    post_descriptors = (pre_descriptors[0],)

    def descriptor_inventory(
        descriptors: tuple[NativeFileDescriptorIdentity, ...],
        started: int,
    ) -> NativeFileDescriptorInventory:
        digest_mapping = {
            "schema_id": "darwin-detailed-file-descriptor-inventory-v1",
            "process": asdict(process),
            "descriptors": [asdict(value) for value in descriptors],
        }
        return NativeFileDescriptorInventory(
            schema_id=digest_mapping["schema_id"],
            process=process,
            first_scan_started_monotonic_ns=started,
            first_scan_completed_monotonic_ns=started + 1,
            second_scan_started_monotonic_ns=started + 2,
            second_scan_completed_monotonic_ns=started + 3,
            descriptors=descriptors,
            inventory_sha256=canonical_sha256(digest_mapping),
        )

    pre_threads = thread_inventory(100)
    post_threads = thread_inventory(200)
    pre_fds = descriptor_inventory(pre_descriptors, 300)
    post_fds = descriptor_inventory(post_descriptors, 400)
    mapping = {
        "schema_id": "parser-tesseract-broker-post-release-baseline-v1",
        "broker": process,
        "pre_release_ready_sha256": "9" * 64,
        "retired_descriptor_fds": (7, 8),
        "pre_release_thread_inventory": pre_threads,
        "pre_release_file_descriptor_inventory": pre_fds,
        "post_release_thread_inventory": post_threads,
        "post_release_file_descriptor_inventory": post_fds,
        "transition_observed_at_monotonic_ns": 500,
    }
    mapping["record_sha256"] = canonical_sha256(
        {
            key: asdict(value)
            if hasattr(value, "__dataclass_fields__")
            else value
            for key, value in mapping.items()
        }
    )
    return BrokerPostReleaseBaseline(**mapping)


class _UnitBrokerClient:
    def __init__(self, settings: Settings, deadline_ns: int) -> None:
        owner_pid = os.getpid()
        broker_pid = owner_pid + 100_000
        self.config = SimpleNamespace(
            attempt_deadline_monotonic_ns=deadline_ns,
            attempt_nonce_sha256="1" * 64,
            scope_sha256="2" * 64,
            broker_pid=broker_pid,
            broker_start_abstime=123,
            broker_pgid=broker_pid,
            broker_sid=broker_pid,
            executable=settings.tesseract_cmd,
            native_closure_sha256="4" * 64,
            native_spawn_guard_sha256="5" * 64,
            native_spawn_guard_source_sha256="6" * 64,
            native_runtime_gate_source_sha256="7" * 64,
            native_runtime_gate_library_sha256="8" * 64,
            native_runtime_gate_record_sha256="9" * 64,
            tessdata_root=settings.tesseract_data_path,
            languages=tuple(sorted(settings.ocr_languages)),
        )
        self._epoch = 0
        self.closed = False
        self._last_receipt: Any | None = None
        self._post_release_baseline = _unit_broker_post_release_baseline(
            broker_pid,
            self.config.broker_start_abstime,
        )

    def post_release_baseline(self) -> BrokerPostReleaseBaseline:
        return self._post_release_baseline

    def begin_phase(self, phase: str, request_id: str, *_args: Any, **_kwargs: Any) -> Any:
        self._epoch += 1
        return SimpleNamespace(
            phase=phase,
            request_id=request_id,
            request_epoch=self._epoch,
            request_sequence=max(1, self._epoch - 1),
        )

    def end_phase(self, lease: Any) -> Any:
        self._last_receipt = SimpleNamespace(
            request_id=lease.request_id,
            request_epoch=lease.request_epoch,
            receipt_sha256="3" * 64,
            logical_phase=lease.phase,
            terminal_kind="end",
        )
        return self._last_receipt

    def abort_phase(self, lease: Any, _failure: BaseException | None = None) -> Any:
        return self.end_phase(lease)

    @contextlib.contextmanager
    def phase(self, phase: str, request_id: str, *_args: Any, **kwargs: Any):
        lease = self.begin_phase(phase, request_id, **kwargs)
        try:
            yield lease
        except BaseException as exc:
            self.abort_phase(lease, exc)
            raise
        else:
            self.end_phase(lease)

    def barrier_snapshot(self) -> None:
        return None

    def last_receipt(self) -> Any | None:
        return self._last_receipt

    def close(self) -> None:
        self.closed = True


def _test_broker_runtime_overrides(settings: Settings) -> dict[str, Any]:
    """Explicit supervised-capability fakes for pre-broker lifecycle tests."""

    owner_pid = os.getpid()
    deadline_ns = time.monotonic_ns() + 3_600_000_000_000
    client = _UnitBrokerClient(settings, deadline_ns)
    phase_control = _UnitPhaseControl(owner_pid, deadline_ns)
    request_control = _UnitRequestControl(
        owner_pid,
        client.config.broker_pid,
        client.config.broker_start_abstime,
        client.config.attempt_nonce_sha256,
        client.config.scope_sha256,
    )
    evidence = SimpleNamespace(
        worker=SimpleNamespace(
            pid=owner_pid,
            process_group_id=owner_pid,
            session_id=owner_pid,
        ),
        broker=SimpleNamespace(
            pid=client.config.broker_pid,
            start_abstime=client.config.broker_start_abstime,
            process_group_id=client.config.broker_pgid,
            session_id=client.config.broker_sid,
        ),
        native_closure_sha256=client.config.native_closure_sha256,
        broker_native_spawn_guard_library_sha256=(
            client.config.native_spawn_guard_sha256
        ),
        broker_native_spawn_guard_source_sha256=(
            client.config.native_spawn_guard_source_sha256
        ),
        native_runtime_gate_source_sha256=(
            client.config.native_runtime_gate_source_sha256
        ),
        native_runtime_gate_library_sha256=(
            client.config.native_runtime_gate_library_sha256
        ),
        native_runtime_gate_record_sha256=(
            client.config.native_runtime_gate_record_sha256
        ),
        native_trust_model="frozen-native-closure-trusted-v1",
        native_containment_claim="none-trusted-pinned-native-computation",
    )
    return {
        "broker_client_resolver": lambda: client,
        "fork_denial_resolver": lambda: evidence,
        "phase_control_resolver": lambda: phase_control,
        "request_control_resolver": lambda: request_control,
    }


def _unit_lease(runtime: ParserWorkerRuntime, settings: Settings):
    return runtime.lease(
        settings,
        request_id="unit-request",
        binding={"schema_id": "unit-request-v1"},
    )


def _enabled_settings(
    artifacts_path: str = "/deployment/models",
    *,
    artifact_sha256: str = ARTIFACT_IDENTITY.sha256,
    dependency_sha256: str = DEPENDENCY_IDENTITY.sha256,
    timeout_seconds: float = 2.0,
    shutdown_grace_seconds: float = 1.0,
) -> Settings:
    return Settings(
        docling_artifacts_path=artifacts_path,
        tesseract_cmd="/runtime/tesseract",
        tesseract_data_path="/runtime/tessdata",
        parser_latency_prewarm_enabled=True,
        parser_latency_prewarm_timeout_seconds=timeout_seconds,
        parser_latency_prewarm_shutdown_grace_seconds=shutdown_grace_seconds,
        parser_latency_prewarm_artifacts_sha256=artifact_sha256,
        parser_latency_prewarm_dependency_sha256=dependency_sha256,
    )


def _runtime(
    settings: Settings,
    owned_fixture: _OwnedFixture | None = None,
    **overrides: Any,
) -> tuple[ParserWorkerRuntime, _OwnedFixture, list[int]]:
    fixture = owned_fixture or _owned_fixture()
    fatal_exit_codes: list[int] = []
    arguments: dict[str, Any] = {
        "initializer": lambda _settings: fixture.owned,
        "artifact_validator": lambda _path: ARTIFACT_IDENTITY,
        "dependency_validator": lambda _settings: DEPENDENCY_IDENTITY,
        "metadata_validator": lambda _path: ARTIFACT_IDENTITY.metadata_sha256,
        "converter_validator": lambda _owned, _settings: CONVERTER_IDENTITY,
        "offline_validator": lambda: OFFLINE_IDENTITY,
        "fatal_exit": fatal_exit_codes.append,
        **_test_broker_runtime_overrides(settings),
    }
    arguments.update(overrides)
    return ParserWorkerRuntime(settings, **arguments), fixture, fatal_exit_codes


def _start(runtime: ParserWorkerRuntime):
    return asyncio.run(runtime.start())


def _shutdown(runtime: ParserWorkerRuntime):
    return asyncio.run(runtime.shutdown())


def _parsed_document(filename: str = "sample.pdf") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document": {
            "filename": filename,
            "mime_type": "application/pdf",
            "sha256": hashlib.sha256(VALID_PDF).hexdigest(),
            "page_count": 1,
        },
        "pages": [
            {
                "page_index": 1,
                "page_number": 1,
                "page_label": "1",
                "page_width": 612.0,
                "page_height": 792.0,
                "unit": "pt",
                "success": True,
                "items": [],
                "warnings": [],
            }
        ],
        "processing": {
            "engine": "test-double",
            "ocr_engine": "test-double",
            "ocr_languages": ["eng"],
            "duration_ms": 1,
        },
        "warnings": [],
    }


def _upload(client: TestClient, *, output_format: str = "json"):
    return client.post(
        f"/v1/parse?output_format={output_format}",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )


def _assert_unavailable(response: Any) -> None:
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "details"}
    assert payload["error"]["code"] == "extraction_engine_unavailable"
    assert payload["error"]["details"] == {
        "component": "parser_worker",
        "reason": "unavailable",
    }


def test_runtime_publishes_ready_atomically_and_reuses_exact_owned_converters() -> (
    None
):
    settings = _enabled_settings()
    ticks = iter((101, 202))
    runtime, fixture, fatal_codes = _runtime(
        settings,
        clock_ns=lambda: next(ticks),
    )

    created = runtime.snapshot()
    assert created.state is WorkerState.CREATED
    assert created.owner_pid == os.getpid()
    assert created.initialization_started_ns is None
    assert created.ready_at_ns is None
    assert created.active_leases == 0

    ready = _start(runtime)
    assert ready.state is WorkerState.READY
    assert ready.initialization_started_ns == 101
    assert ready.ready_at_ns == 202
    assert ready.artifacts_sha256 == ARTIFACT_IDENTITY.sha256
    assert ready.artifact_metadata_sha256 == ARTIFACT_IDENTITY.metadata_sha256
    assert ready.dependency_sha256 == DEPENDENCY_IDENTITY.sha256
    assert ready.converter_sha256 == CONVERTER_IDENTITY
    assert ready.offline_environment_sha256 == OFFLINE_IDENTITY
    assert ready.failure_code is None

    with _unit_lease(runtime, settings) as leased:
        assert leased is runtime
        assert runtime.snapshot().active_leases == 1
        assert runtime.converter_for(InputKind.PDF) == (
            fixture.pdf,
            fixture.owned.conversion_lock,
        )
        assert runtime.converter_for(InputKind.IMAGE) == (
            fixture.image,
            fixture.owned.conversion_lock,
        )
        assert runtime.optional_model_decisions() == (False, False)
        assert runtime.converter_for(InputKind.PDF)[0] is fixture.pdf
        assert runtime.converter_for(InputKind.IMAGE)[0] is fixture.image

    assert runtime.snapshot().active_leases == 0
    with pytest.raises(ExtractionEngineUnavailableError):
        runtime.converter_for(InputKind.PDF)

    closed = _shutdown(runtime)
    assert closed.state is WorkerState.CLOSED
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert fixture.pdf.initialized_pipelines == {}
    assert fixture.image.initialized_pipelines == {}
    assert fatal_codes == []


def test_natural_pdf_and_image_pipeline_initialization_uses_one_owned_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docling.datamodel.base_models import InputFormat
    from app.services import pipeline

    settings = _enabled_settings()
    lock = pipeline._DOCLING_CONVERSION_LOCK
    pdf = _FakeConverter("pdf")
    image = _FakeConverter("image")
    builds: list[tuple[str, dict[str, Any]]] = []

    def build_pdf(**kwargs: Any):
        builds.append(("pdf", kwargs))
        return pdf, lock

    def build_image(**kwargs: Any):
        builds.append(("image", kwargs))
        return image, lock

    monkeypatch.setattr(pipeline, "_picture_classifier_model_available", lambda _: False)
    monkeypatch.setattr(pipeline, "_picture_description_model_available", lambda _: False)
    monkeypatch.setattr(pipeline, "_build_pdf_converter", build_pdf)
    monkeypatch.setattr(pipeline, "_build_image_converter", build_image)

    owned = worker_module._initialize_owned_converters(settings)

    assert [name for name, _kwargs in builds] == ["pdf", "image"]
    assert builds[0][1] == builds[1][1]
    assert builds[0][1]["artifacts_path"] == settings.docling_artifacts_path
    assert builds[0][1]["classify_pictures"] is False
    assert pdf.natural_initializations == [InputFormat.PDF]
    assert image.natural_initializations == [InputFormat.IMAGE]
    assert owned.pdf is pdf
    assert owned.image is image
    assert owned.conversion_lock is lock


def test_enabled_runtime_requires_a_stable_process_offline_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    with pytest.raises(RuntimeError, match="HF_HUB_OFFLINE must be enabled"):
        worker_module.offline_environment_identity()

    monkeypatch.setenv("HF_HUB_OFFLINE", "true")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "false")
    with pytest.raises(RuntimeError, match="TRANSFORMERS_OFFLINE must be enabled"):
        worker_module.offline_environment_identity()

    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "yes")
    first = worker_module.offline_environment_identity()
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "on")
    assert worker_module.offline_environment_identity() == first
    assert len(first) == 64


def test_artifact_identity_is_content_bound_and_rejects_missing_empty_or_symlinks(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "models"
    nested = artifact_root / "layout"
    nested.mkdir(parents=True)
    model = nested / "weights.bin"
    model.write_bytes(b"approved-model")

    first = artifact_identity(artifact_root)
    model.write_bytes(b"corrupted-model")
    second = artifact_identity(artifact_root)

    assert first.file_count == second.file_count == 1
    assert first.sha256 != second.sha256
    assert first.metadata_sha256 != second.metadata_sha256

    with pytest.raises(FileNotFoundError):
        artifact_identity(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="cannot be empty"):
        artifact_identity(empty)

    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    (artifact_root / "linked.bin").symlink_to(target)
    with pytest.raises(RuntimeError, match="cannot contain symlinks"):
        artifact_identity(artifact_root)

    root_link = tmp_path / "models-link"
    root_link.symlink_to(artifact_root, target_is_directory=True)
    with pytest.raises(RuntimeError, match="non-symlink directory"):
        artifact_identity(root_link)


@pytest.mark.parametrize("failure", ("missing", "empty", "symlink", "corrupt"))
def test_missing_corrupt_or_symlinked_artifacts_fail_start_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    artifact_root = tmp_path / "models"
    if failure != "missing":
        artifact_root.mkdir()
    expected = "0" * 64
    if failure == "symlink":
        target = tmp_path / "target.bin"
        target.write_bytes(b"model")
        (artifact_root / "linked.bin").symlink_to(target)
    elif failure == "corrupt":
        (artifact_root / "model.bin").write_bytes(b"different-than-pin")
    settings = _enabled_settings(str(artifact_root), artifact_sha256=expected)
    initializer_calls: list[Settings] = []
    runtime, _fixture, _fatal_codes = _runtime(
        settings,
        initializer=lambda value: initializer_calls.append(value),
        artifact_validator=artifact_identity,
    )

    with pytest.raises(ExtractionEngineUnavailableError) as error:
        _start(runtime)

    assert isinstance(error.value.__cause__, (FileNotFoundError, RuntimeError))
    assert runtime.snapshot().state is WorkerState.UNAVAILABLE
    assert runtime.snapshot().failure_code == "initialization_failed"
    assert initializer_calls == []
    assert _shutdown(runtime).state is WorkerState.CLOSED


@pytest.mark.parametrize("mismatch", ("artifact", "dependency"))
def test_pinned_artifact_and_dependency_mismatch_never_reaches_initialization(
    mismatch: str,
) -> None:
    settings = _enabled_settings(
        artifact_sha256=("0" * 64 if mismatch == "artifact" else "a" * 64),
        dependency_sha256=("0" * 64 if mismatch == "dependency" else "b" * 64),
    )
    initializer_calls: list[Settings] = []
    runtime, _fixture, _fatal_codes = _runtime(
        settings,
        initializer=lambda value: initializer_calls.append(value),
    )

    with pytest.raises(ExtractionEngineUnavailableError) as error:
        _start(runtime)

    assert isinstance(error.value.__cause__, RuntimeError)
    assert f"configured {mismatch} identity differs" in str(error.value.__cause__)
    assert initializer_calls == []
    assert runtime.snapshot().state is WorkerState.UNAVAILABLE
    _shutdown(runtime)


@pytest.mark.parametrize("mutation", ("artifact", "dependency", "offline"))
def test_identity_mutation_during_initialization_clears_partial_converters(
    mutation: str,
) -> None:
    settings = _enabled_settings()
    fixture = _owned_fixture()
    artifact_calls = 0
    dependency_calls = 0
    offline_calls = 0

    def artifacts(_path: object) -> FileTreeIdentity:
        nonlocal artifact_calls
        artifact_calls += 1
        if mutation == "artifact" and artifact_calls == 2:
            return replace(ARTIFACT_IDENTITY, sha256="0" * 64)
        return ARTIFACT_IDENTITY

    def dependencies(_settings: Settings) -> DependencyIdentity:
        nonlocal dependency_calls
        dependency_calls += 1
        if mutation == "dependency" and dependency_calls == 2:
            return replace(DEPENDENCY_IDENTITY, sha256="0" * 64)
        return DEPENDENCY_IDENTITY

    def offline() -> str:
        nonlocal offline_calls
        offline_calls += 1
        return "0" * 64 if mutation == "offline" and offline_calls == 2 else OFFLINE_IDENTITY

    runtime, _fixture, _fatal_codes = _runtime(
        settings,
        fixture,
        artifact_validator=artifacts,
        dependency_validator=dependencies,
        offline_validator=offline,
    )

    with pytest.raises(ExtractionEngineUnavailableError):
        _start(runtime)

    assert runtime.snapshot().state is WorkerState.UNAVAILABLE
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert fixture.pdf.initialized_pipelines == {}
    assert fixture.image.initialized_pipelines == {}
    _shutdown(runtime)


def test_base_exception_after_partial_initialization_clears_every_owned_reference() -> (
    None
):
    class InitializationAbort(BaseException):
        pass

    settings = _enabled_settings()
    fixture = _owned_fixture()
    validations = 0

    def artifacts(_path: object) -> FileTreeIdentity:
        nonlocal validations
        validations += 1
        if validations == 2:
            raise InitializationAbort("cancelled after converter construction")
        return ARTIFACT_IDENTITY

    runtime, _fixture, _fatal_codes = _runtime(
        settings,
        fixture,
        artifact_validator=artifacts,
    )

    with pytest.raises(ExtractionEngineUnavailableError) as error:
        _start(runtime)

    assert isinstance(error.value.__cause__, InitializationAbort)
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert fixture.pdf.initialized_pipelines == {}
    assert fixture.image.initialized_pipelines == {}
    assert runtime.snapshot().state is WorkerState.UNAVAILABLE
    _shutdown(runtime)


def test_ready_worker_fails_closed_after_artifact_metadata_mutation() -> None:
    settings = _enabled_settings()
    current_metadata = [ARTIFACT_IDENTITY.metadata_sha256]
    runtime, fixture, _fatal_codes = _runtime(
        settings,
        metadata_validator=lambda _path: current_metadata[0],
    )
    _start(runtime)
    current_metadata[0] = "0" * 64

    with pytest.raises(ExtractionEngineUnavailableError):
        with _unit_lease(runtime, settings):
            pytest.fail("a mutated artifact tree was admitted")

    snapshot = runtime.snapshot()
    assert snapshot.state is WorkerState.UNAVAILABLE
    assert snapshot.failure_code == "artifact_metadata_changed"
    with pytest.raises(ExtractionEngineUnavailableError):
        _unit_lease(runtime, settings).__enter__()
    _shutdown(runtime)
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None


@pytest.mark.parametrize(
    ("identity", "failure_code"),
    (
        ("converter", "converter_identity_changed"),
        ("offline", "offline_environment_changed"),
    ),
)
def test_ready_worker_fails_closed_after_converter_or_offline_identity_mutation(
    identity: str,
    failure_code: str,
) -> None:
    settings = _enabled_settings()
    converter = [CONVERTER_IDENTITY]
    offline = [OFFLINE_IDENTITY]
    runtime, _fixture, _fatal_codes = _runtime(
        settings,
        converter_validator=lambda _owned, _settings: converter[0],
        offline_validator=lambda: offline[0],
    )
    _start(runtime)
    if identity == "converter":
        converter[0] = "0" * 64
    else:
        offline[0] = "0" * 64

    with pytest.raises(ExtractionEngineUnavailableError):
        with _unit_lease(runtime, settings):
            pytest.fail("a mutated runtime identity was admitted")

    assert runtime.snapshot().state is WorkerState.UNAVAILABLE
    assert runtime.snapshot().failure_code == failure_code
    _shutdown(runtime)


def test_nonready_pid_and_settings_mismatch_are_never_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _enabled_settings()
    created, _fixture, _fatal_codes = _runtime(settings)
    with pytest.raises(ExtractionEngineUnavailableError):
        _unit_lease(created, settings).__enter__()
    _shutdown(created)

    settings_runtime, _fixture, _fatal_codes = _runtime(settings)
    _start(settings_runtime)
    with pytest.raises(ExtractionEngineUnavailableError):
        _unit_lease(
            settings_runtime, replace(settings, max_pages=99)
        ).__enter__()
    _shutdown(settings_runtime)

    pid_runtime, _fixture, _fatal_codes = _runtime(settings)
    _start(pid_runtime)
    owner_pid = pid_runtime.snapshot().owner_pid
    monkeypatch.setattr(worker_module.os, "getpid", lambda: owner_pid + 1)
    with pytest.raises(ExtractionEngineUnavailableError):
        _unit_lease(pid_runtime, settings).__enter__()
    monkeypatch.undo()
    _shutdown(pid_runtime)


def test_shutdown_during_initialization_never_publishes_partial_ready() -> None:
    settings = _enabled_settings(shutdown_grace_seconds=1.0)
    started = threading.Event()
    release = threading.Event()
    fixture = _owned_fixture()

    def initialize(_settings: Settings) -> OwnedConverters:
        started.set()
        assert release.wait(2.0)
        return fixture.owned

    runtime, _fixture, fatal_codes = _runtime(
        settings,
        fixture,
        initializer=initialize,
    )
    startup_errors: list[BaseException] = []

    def start_runtime() -> None:
        try:
            asyncio.run(runtime.start())
        except BaseException as exc:
            startup_errors.append(exc)

    startup_thread = threading.Thread(target=start_runtime, name="lat-us02-start")
    startup_thread.start()
    assert started.wait(1.0)
    assert runtime.snapshot().state is WorkerState.INITIALIZING
    threading.Timer(0.05, release.set).start()

    closed = _shutdown(runtime)
    startup_thread.join(2.0)

    assert not startup_thread.is_alive()
    assert closed.state is WorkerState.CLOSED
    assert all(snapshot is not WorkerState.READY for snapshot in (closed.state,))
    assert len(startup_errors) == 1
    assert isinstance(startup_errors[0], ExtractionEngineUnavailableError)
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert fatal_codes == []


def test_cancelled_initialization_stays_unavailable_and_discards_late_result() -> (
    None
):
    settings = _enabled_settings(
        timeout_seconds=2.0,
        shutdown_grace_seconds=0.1,
    )
    started = threading.Event()
    release = threading.Event()
    fixture = _owned_fixture()
    fatal_codes: list[int] = []

    def initialize(_settings: Settings) -> OwnedConverters:
        started.set()
        assert release.wait(2.0)
        return fixture.owned

    def fatal_exit(code: int) -> None:
        fatal_codes.append(code)
        release.set()

    runtime, _fixture, _unused_codes = _runtime(
        settings,
        fixture,
        initializer=initialize,
        fatal_exit=fatal_exit,
    )

    async def cancel_startup() -> None:
        task = asyncio.create_task(runtime.start())
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 1.0
        while not fatal_codes and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        while runtime._future is not None and not runtime._future.done():
            await asyncio.sleep(0.005)

    asyncio.run(cancel_startup())

    assert fatal_codes == [worker_module.STARTUP_TIMEOUT_EXIT_CODE]
    snapshot = runtime.snapshot()
    assert snapshot.state is WorkerState.UNAVAILABLE
    assert snapshot.failure_code == "startup_cancelled"
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert _shutdown(runtime).state is WorkerState.CLOSED


def test_shutdown_drains_existing_lease_rejects_new_work_and_is_idempotent() -> None:
    settings = _enabled_settings(shutdown_grace_seconds=1.0)
    runtime, fixture, fatal_codes = _runtime(settings)
    _start(runtime)
    lease_entered = threading.Event()
    release_lease = threading.Event()
    shutdown_result: list[Any] = []

    def hold_lease() -> None:
        with _unit_lease(runtime, settings):
            lease_entered.set()
            assert release_lease.wait(2.0)

    def shut_down() -> None:
        shutdown_result.append(asyncio.run(runtime.shutdown()))

    lease_thread = threading.Thread(target=hold_lease, name="lat-us02-lease")
    lease_thread.start()
    assert lease_entered.wait(1.0)
    shutdown_thread = threading.Thread(target=shut_down, name="lat-us02-shutdown")
    shutdown_thread.start()
    deadline = time.monotonic() + 1.0
    while runtime.snapshot().state is not WorkerState.STOPPING:
        assert time.monotonic() < deadline
        threading.Event().wait(0.005)

    with pytest.raises(ExtractionEngineUnavailableError):
        _unit_lease(runtime, settings).__enter__()
    release_lease.set()
    lease_thread.join(2.0)
    shutdown_thread.join(2.0)

    assert not lease_thread.is_alive()
    assert not shutdown_thread.is_alive()
    assert shutdown_result[0].state is WorkerState.CLOSED
    assert runtime.snapshot().active_leases == 0
    assert _shutdown(runtime).state is WorkerState.CLOSED
    assert fixture.owned.pdf is None
    assert fixture.owned.image is None
    assert fatal_codes == []


def test_fake_lifecycle_leaves_no_init_thread_child_process_or_fd_growth() -> None:
    settings = _enabled_settings()
    process = psutil.Process()
    try:
        before_children = {child.pid for child in process.children(recursive=True)}
    except (PermissionError, psutil.AccessDenied):
        # Hardened macOS runners can deny the system-wide PID inventory that
        # psutil needs for recursive children. The subprocess-fatal tests below
        # still prove process reaping; retain thread and descriptor checks here.
        before_children = None
    before_fds = process.num_fds()
    runtime, _fixture, fatal_codes = _runtime(settings)

    _start(runtime)
    _shutdown(runtime)
    gc.collect()

    assert not any(
        thread.name.startswith(("parser-prewarm-init", "parser-prewarm-fatal"))
        for thread in threading.enumerate()
    )
    if before_children is not None:
        assert {
            child.pid for child in process.children(recursive=True)
        } <= before_children
    assert process.num_fds() <= before_fds + 1
    assert fatal_codes == []


def test_cpu_and_all_required_rss_phases_are_observed_without_a_numeric_gate() -> (
    None
):
    settings = _enabled_settings()
    process = psutil.Process()
    observations: dict[str, tuple[int, float]] = {}

    def observe(label: str) -> None:
        memory = process.memory_info()
        cpu = process.cpu_times()
        observations[label] = (memory.rss, cpu.user + cpu.system)

    fixture = _stateless_owned_fixture()
    runtime, _fixture, _fatal_codes = _runtime(settings, fixture)
    observe("cold_initialization")
    _start(runtime)
    observe("prewarmed_idle")
    for index in range(16):
        _fake_request(
            runtime,
            settings,
            InputKind.PDF if index % 2 == 0 else InputKind.IMAGE,
            _RequestPayload(f"bounded-{index}".encode()),
        )
        if index == 0:
            observe("request_peak")
    observe("repeated_request")
    _shutdown(runtime)
    observe("shutdown")

    assert tuple(observations) == (
        "cold_initialization",
        "prewarmed_idle",
        "request_peak",
        "repeated_request",
        "shutdown",
    )
    assert all(rss_bytes > 0 for rss_bytes, _cpu_seconds in observations.values())
    cpu_values = tuple(cpu_seconds for _rss_bytes, cpu_seconds in observations.values())
    assert cpu_values == tuple(sorted(cpu_values))


@dataclass(slots=True, weakref_slot=True)
class _RequestPayload:
    data: bytes


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _RequestResult:
    route: str
    sha256: str


class _StatelessRequestConverter(_FakeConverter):
    def convert_payload(self, payload: _RequestPayload) -> _RequestResult:
        if payload.data == b"FAIL":
            raise RuntimeError("synthetic request failure")
        return _RequestResult(
            route=self.name,
            sha256=hashlib.sha256(payload.data).hexdigest(),
        )


def _stateless_owned_fixture() -> _OwnedFixture:
    pdf = _StatelessRequestConverter("pdf")
    image = _StatelessRequestConverter("image")
    owned = OwnedConverters(
        pdf=pdf,
        image=image,
        conversion_lock=threading.Lock(),
        picture_classifier_enabled=False,
        picture_description_enabled=False,
    )
    return _OwnedFixture(owned=owned, pdf=pdf, image=image)


def _fake_request(
    runtime: ParserWorkerRuntime,
    settings: Settings,
    kind: InputKind,
    payload: _RequestPayload,
) -> _RequestResult:
    with _unit_lease(runtime, settings):
        converter, _lock = runtime.converter_for(kind)
        return converter.convert_payload(payload)


def test_a_b_a_cross_format_reuse_retains_no_request_or_result_objects() -> None:
    settings = _enabled_settings()
    fixture = _stateless_owned_fixture()
    runtime, _fixture, _fatal_codes = _runtime(settings, fixture)
    _start(runtime)

    first_payload = _RequestPayload(b"A-private-request")
    first = _fake_request(runtime, settings, InputKind.PDF, first_payload)
    first_digest = first.sha256
    payload_reference = weakref.ref(first_payload)
    result_reference = weakref.ref(first)
    del first_payload, first
    gc.collect()
    assert payload_reference() is None
    assert result_reference() is None

    middle = _fake_request(
        runtime,
        settings,
        InputKind.IMAGE,
        _RequestPayload(b"B-other-tenant"),
    )
    last = _fake_request(
        runtime,
        settings,
        InputKind.PDF,
        _RequestPayload(b"A-private-request"),
    )

    assert middle.route == "image"
    assert last == _RequestResult(route="pdf", sha256=first_digest)
    assert runtime.snapshot().state is WorkerState.READY
    _shutdown(runtime)


def test_success_failure_success_does_not_poison_reused_worker() -> None:
    settings = _enabled_settings()
    fixture = _stateless_owned_fixture()
    runtime, _fixture, _fatal_codes = _runtime(settings, fixture)
    _start(runtime)

    first = _fake_request(
        runtime,
        settings,
        InputKind.PDF,
        _RequestPayload(b"SUCCESS"),
    )
    with pytest.raises(RuntimeError, match="synthetic request failure"):
        _fake_request(
            runtime,
            settings,
            InputKind.PDF,
            _RequestPayload(b"FAIL"),
        )
    final = _fake_request(
        runtime,
        settings,
        InputKind.PDF,
        _RequestPayload(b"SUCCESS"),
    )

    assert final == first
    assert runtime.snapshot().state is WorkerState.READY
    assert runtime.snapshot().active_leases == 0
    _shutdown(runtime)


@pytest.mark.parametrize("termination", ("timeout", "cancellation", "shutdown"))
def test_stuck_startup_is_process_fatal_and_never_admits_partial_worker(
    termination: str,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    script = textwrap.dedent(
        """
        import asyncio
        import os
        import threading

        from app.config import Settings
        from app.errors import ExtractionEngineUnavailableError
        from app.services.parser_worker import (
            DependencyIdentity,
            FileTreeIdentity,
            ParserWorkerRuntime,
        )
        from tests.stories.phase_latency.test_lat_us02_worker_prewarm import (
            _test_broker_runtime_overrides,
            _unit_lease,
        )

        artifacts = FileTreeIdentity('a' * 64, 'c' * 64, 1, 1)
        dependencies = DependencyIdentity('b' * 64, 1, 1, 1, 'test', 1)
        settings = Settings(
            docling_artifacts_path='/deployment/models',
            tesseract_cmd='/runtime/tesseract',
            tesseract_data_path='/runtime/tessdata',
            parser_latency_prewarm_enabled=True,
            parser_latency_prewarm_timeout_seconds=1.0,
            parser_latency_prewarm_shutdown_grace_seconds=0.1,
            parser_latency_prewarm_artifacts_sha256='a' * 64,
            parser_latency_prewarm_dependency_sha256='b' * 64,
        )

        initializer_started = threading.Event()

        def blocked(_settings):
            os.write(1, b'initializer-started\\n')
            initializer_started.set()
            threading.Event().wait()

        runtime = ParserWorkerRuntime(
            settings,
            initializer=blocked,
            artifact_validator=lambda _path: artifacts,
            dependency_validator=lambda _settings: dependencies,
            metadata_validator=lambda _path: artifacts.metadata_sha256,
            converter_validator=lambda _owned, _settings: 'd' * 64,
            offline_validator=lambda: 'e' * 64,
            fatal_exit=os._exit,
            **_test_broker_runtime_overrides(settings),
        )

        async def assert_fail_closed():
            try:
                with _unit_lease(runtime, settings):
                    os.write(1, b'partial-serving\\n')
            except ExtractionEngineUnavailableError:
                os.write(1, b'fail-closed\\n')

        async def main():
            mode = os.environ['LAT_US02_TERMINATION']
            if mode in {'cancellation', 'shutdown'}:
                task = asyncio.create_task(runtime.start())
                while not initializer_started.is_set():
                    await asyncio.sleep(0.001)
                if mode == 'shutdown':
                    await assert_fail_closed()
                    await runtime.shutdown()
                    os.write(1, b'shutdown-returned\\n')
                    return
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    await assert_fail_closed()
                    await asyncio.Event().wait()
                return
            try:
                await runtime.start()
            except ExtractionEngineUnavailableError:
                await assert_fail_closed()
                await asyncio.Event().wait()

        asyncio.run(main())
        """
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["LAT_US02_TERMINATION"] = termination
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5.0,
        check=False,
    )
    elapsed = time.monotonic() - started

    expected_exit_code = (
        worker_module.SHUTDOWN_TIMEOUT_EXIT_CODE
        if termination == "shutdown"
        else worker_module.STARTUP_TIMEOUT_EXIT_CODE
    )
    assert completed.returncode == expected_exit_code
    assert completed.stdout.splitlines() == [b"initializer-started", b"fail-closed"]
    assert b"partial-serving" not in completed.stdout
    assert elapsed < 3.0


def test_cancelled_shutdown_with_stuck_lease_is_process_fatal() -> None:
    repository = Path(__file__).resolve().parents[3]
    script = textwrap.dedent(
        """
        import asyncio
        import os
        import threading

        from app.config import Settings
        from app.services.parser_worker import (
            DependencyIdentity,
            FileTreeIdentity,
            OwnedConverters,
            ParserWorkerRuntime,
            WorkerState,
        )
        from tests.stories.phase_latency.test_lat_us02_worker_prewarm import (
            _test_broker_runtime_overrides,
            _unit_lease,
        )

        class Converter:
            def __init__(self):
                self.initialized_pipelines = {'ready': object()}

        artifacts = FileTreeIdentity('a' * 64, 'c' * 64, 1, 1)
        dependencies = DependencyIdentity('b' * 64, 1, 1, 1, 'test', 1)
        owned = OwnedConverters(
            Converter(), Converter(), threading.Lock(), False, False
        )
        settings = Settings(
            docling_artifacts_path='/deployment/models',
            tesseract_cmd='/runtime/tesseract',
            tesseract_data_path='/runtime/tessdata',
            parser_latency_prewarm_enabled=True,
            parser_latency_prewarm_timeout_seconds=1.0,
            parser_latency_prewarm_shutdown_grace_seconds=1.0,
            parser_latency_prewarm_artifacts_sha256='a' * 64,
            parser_latency_prewarm_dependency_sha256='b' * 64,
        )
        runtime = ParserWorkerRuntime(
            settings,
            initializer=lambda _settings: owned,
            artifact_validator=lambda _path: artifacts,
            dependency_validator=lambda _settings: dependencies,
            metadata_validator=lambda _path: artifacts.metadata_sha256,
            converter_validator=lambda _owned, _settings: 'd' * 64,
            offline_validator=lambda: 'e' * 64,
            **_test_broker_runtime_overrides(settings),
        )
        lease_entered = threading.Event()
        release_lease = threading.Event()

        def hold_lease():
            with _unit_lease(runtime, settings):
                lease_entered.set()
                release_lease.wait()

        async def main():
            await runtime.start()
            holder = threading.Thread(target=hold_lease)
            holder.start()
            while not lease_entered.is_set():
                await asyncio.sleep(0.001)
            os.write(1, b'lease-held\\n')
            shutdown_task = asyncio.create_task(runtime.shutdown())
            while runtime.snapshot().state is not WorkerState.STOPPING:
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.02)
            shutdown_task.cancel()
            try:
                await shutdown_task
            except asyncio.CancelledError:
                os.write(1, b'shutdown-cancellation-returned\\n')
                release_lease.set()
                holder.join()

        asyncio.run(main())
        """
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5.0,
        check=False,
    )

    assert completed.returncode == worker_module.SHUTDOWN_TIMEOUT_EXIT_CODE
    assert completed.stdout.splitlines() == [b"lease-held"]


def test_default_and_explicit_off_use_exact_three_argument_lazy_api_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS", "malformed")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256", "stale")
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256", "stale")
    get_settings.cache_clear()
    application = create_app()
    settings = Settings.from_env()
    application.dependency_overrides[get_settings] = lambda: settings
    calls: list[tuple[bytes, str, Settings]] = []

    def predecessor_parse(
        data: bytes,
        filename: str,
        predecessor_settings: Settings,
    ) -> dict[str, Any]:
        calls.append((data, filename, predecessor_settings))
        return _parsed_document(filename)

    def load_callable(module: str, function: str):
        assert (module, function) == ("app.services.pipeline", "parse_document")
        return predecessor_parse

    monkeypatch.setattr(api_module, "_load_callable", load_callable)
    monkeypatch.setattr(
        worker_module,
        "_initialize_owned_converters",
        lambda _settings: pytest.fail("disabled startup initialized a converter"),
    )

    with TestClient(application) as client:
        response = _upload(client)

    assert response.status_code == 200
    assert calls == [(VALID_PDF, "sample.pdf", settings)]
    assert not hasattr(application.state, worker_module.PREWARM_RUNTIME_STATE_KEY)
    application.dependency_overrides.clear()
    get_settings.cache_clear()


def test_enabled_api_ready_lease_runs_in_dispatch_thread_and_passes_exact_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    application = create_app()
    settings = _enabled_settings()
    runtime, fixture, _fatal_codes = _runtime(settings)
    _start(runtime)
    setattr(application.state, worker_module.PREWARM_RUNTIME_STATE_KEY, runtime)
    application.dependency_overrides[get_settings] = lambda: settings
    observations: list[tuple[int, Any, Any]] = []

    def enabled_parse(
        data: bytes,
        filename: str,
        enabled_settings: Settings,
        *,
        parser_worker: ParserWorkerRuntime,
    ) -> dict[str, Any]:
        converter, _lock = parser_worker.converter_for(InputKind.PDF)
        observations.append((threading.get_ident(), parser_worker, converter))
        assert data == VALID_PDF
        assert enabled_settings is settings
        return _parsed_document(filename)

    monkeypatch.setattr(api_module, "_load_callable", lambda *_args: enabled_parse)
    calling_thread = threading.get_ident()

    with TestClient(application) as client:
        response = _upload(client)

    assert response.status_code == 200
    assert len(observations) == 1
    assert observations[0][0] != calling_thread
    assert observations[0][1] is runtime
    assert observations[0][2] is fixture.pdf
    assert runtime.snapshot().active_leases == 0
    _shutdown(runtime)
    application.dependency_overrides.clear()


@pytest.mark.parametrize("condition", ("missing", "nonready", "pid", "settings", "artifact"))
def test_enabled_api_returns_existing_503_envelope_for_every_unready_condition(
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
) -> None:
    monkeypatch.setenv("PARSER_LATENCY_PREWARM_ENABLED", "false")
    application = create_app()
    runtime_settings = _enabled_settings()
    request_settings = runtime_settings
    runtime: ParserWorkerRuntime | None = None
    metadata = [ARTIFACT_IDENTITY.metadata_sha256]

    if condition != "missing":
        runtime, _fixture, _fatal_codes = _runtime(
            runtime_settings,
            metadata_validator=lambda _path: metadata[0],
        )
        if condition != "nonready":
            _start(runtime)
        setattr(application.state, worker_module.PREWARM_RUNTIME_STATE_KEY, runtime)
    if condition == "pid":
        assert runtime is not None
        owner_pid = runtime.snapshot().owner_pid
        monkeypatch.setattr(worker_module.os, "getpid", lambda: owner_pid + 1)
    elif condition == "settings":
        request_settings = replace(runtime_settings, max_pages=99)
    elif condition == "artifact":
        metadata[0] = "0" * 64

    application.dependency_overrides[get_settings] = lambda: request_settings
    parser_calls: list[object] = []

    def unavailable_parse(*_args: object, **_kwargs: object) -> object:
        parser_calls.append(object())
        pytest.fail("an unavailable worker invoked the parser")

    monkeypatch.setattr(
        api_module,
        "_load_callable",
        lambda *_args: unavailable_parse,
    )

    client = TestClient(application)
    try:
        response = _upload(client)
    finally:
        client.close()

    _assert_unavailable(response)
    assert parser_calls == []
    application.dependency_overrides.clear()
    if condition == "pid":
        monkeypatch.undo()
    if runtime is not None:
        _shutdown(runtime)
