"""Adversarial custody and comparability controls for LAT-US01.

These tests are deliberately deterministic and never invoke the parser or a
hosted service.  They protect the benchmark evidence itself: import-hook
restoration, bounded identity traversal, chronology, closed failure labels,
and the independently frozen all-corpus source oracle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.machinery
import json
from pathlib import Path
import types
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.latency_contracts import (
    ArtifactIdentity,
    AttemptStatus,
    CallableTargetEvidence,
    FailureRecord,
    FailureType,
    EnvironmentIdentityEvidence,
    InstrumentationManifest,
    LatencyAttempt,
    ObserverOverheadEvidence,
    LatencyCampaign,
    StageName,
    StageSpan,
    StageStatus,
    configuration_identity_sha256,
)
from tests.benchmarks.latency_instrumentation import _ScopedLoader
from tests.benchmarks import latency_instrumentation, latency_runner
from tests.benchmarks.latency_runner import (
    _tree_identity,
    derive_environment_manifest,
    derive_environment_sha256,
)
from tests.fixtures.phase_latency.factory import (
    campaign,
    phase_exit_campaign,
    stage_trace,
)


class _RecordingManager:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.installed: list[types.ModuleType] = []

    def install_module_targets(self, module: types.ModuleType) -> None:
        self.installed.append(module)
        if self.failure is not None:
            raise self.failure


class _RecordingLoader:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.observed: tuple[Any, Any] | None = None

    def exec_module(self, module: types.ModuleType) -> None:
        self.observed = (module.__spec__.loader, module.__loader__)
        if self.failure is not None:
            raise self.failure
        module.loaded = True


def _module_for_scoped_loader(
    loader: _RecordingLoader,
    manager: _RecordingManager,
) -> tuple[_ScopedLoader, types.ModuleType]:
    scoped = _ScopedLoader(loader, manager)  # type: ignore[arg-type]
    spec = importlib.machinery.ModuleSpec("lat_us01_optional", scoped)
    module = types.ModuleType(spec.name)
    module.__spec__ = spec
    module.__loader__ = scoped
    return scoped, module


def _rehash_manifest(value: dict[str, Any]) -> None:
    payload = {key: item for key, item in value.items() if key != "manifest_sha256"}
    value["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _synthetic_manifest() -> InstrumentationManifest:
    signature = "(*args: Any, **kwargs: Any) -> Any"
    signature_sha = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    source_artifact = ArtifactIdentity(
        path="tests/performance/test_latency_custody_adversarial.py",
        sha256="a" * 64,
        size_bytes=1,
    )
    targets = tuple(
        sorted(
            (
                CallableTargetEvidence(
                    target_id=definition.target_id,
                    stage=definition.stage,
                    module=definition.source_module,
                    attribute=definition.attribute,
                    qualname=definition.source_attribute,
                    source=source_artifact,
                    signature=signature,
                    signature_sha256=signature_sha,
                    callable_kind=latency_instrumentation._expected_callable_kind(
                        definition
                    ),
                    code_sha256="b" * 64,
                    wrapper_strategy=definition.strategy,
                    classifier_id=definition.classifier_id,
                    cardinality_policy_id=definition.policy_id,
                    installed=False,
                    invocation_count=0,
                    pre_binding_sha256=None,
                    installed_binding_sha256=None,
                    post_restore_binding_sha256=None,
                    restored_exact_binding=None,
                )
                for definition in latency_instrumentation.TARGETS
            ),
            key=lambda item: item.target_id,
        )
    )
    harness_files = tuple(
        ArtifactIdentity(path=path, sha256="c" * 64, size_bytes=1)
        for path in (
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
    )
    value: dict[str, Any] = {
        "schema_id": "phase-latency-external-observer-manifest-v1",
        "schema_version": "1.0",
        "observer_mode": "diagnostic_external_test_instrumentation",
        "observer_version": "lat-us01-v1",
        "authoritative_total_policy": (
            "separate_uninstrumented_twin_no_observer_subtraction"
        ),
        "harness_files": [item.model_dump(mode="json") for item in harness_files],
        "targets": [item.model_dump(mode="json") for item in targets],
        "installed_target_count": 0,
        "request_collector_id": "external-request-scoped-perf-counter-ns-v1",
        "import_hook_finder_id": "phase-latency-scoped-meta-path-finder-v1",
        "import_hook_loader_id": "phase-latency-scoped-loader-v1",
        "python_implementation": "CPython",
        "python_version": "3.13.0",
        "runtime_sha256": "d" * 64,
        "dependency_lock_sha256": "e" * 64,
        "docling_version": "2.114.0",
        "docling_get_pipeline_signature_sha256": signature_sha,
        "docling_get_pipeline_disposition": "not_observed",
        "observer_overhead": ObserverOverheadEvidence(
            calibration_id="external_exception_wrapper_noop_v1",
            call_count=256,
            unwrapped_total_ns=100,
            wrapped_total_ns=120,
            absolute_delta_ns=20,
            adjustment_applied=False,
        ).model_dump(mode="json"),
        "hosted_calls": 0,
    }
    _rehash_manifest(value)
    return InstrumentationManifest.model_validate(value)


def test_optional_module_exec_uses_and_retains_exact_natural_loader() -> None:
    loader = _RecordingLoader()
    manager = _RecordingManager()
    scoped, module = _module_for_scoped_loader(loader, manager)
    natural_spec = module.__spec__

    scoped.exec_module(module)

    assert loader.observed == (loader, loader)
    assert module.__spec__ is natural_spec
    assert module.__spec__ is not None
    assert module.__spec__.loader is loader
    assert module.__loader__ is loader
    assert manager.installed == [module]
    assert module.loaded is True


@pytest.mark.parametrize("failure_owner", ("loader", "observer"))
@pytest.mark.parametrize("failure", (RuntimeError("closed"), KeyboardInterrupt()))
def test_optional_module_failure_never_retains_scoped_loader_or_manager(
    failure_owner: str,
    failure: BaseException,
) -> None:
    loader = _RecordingLoader(failure if failure_owner == "loader" else None)
    manager = _RecordingManager(failure if failure_owner == "observer" else None)
    scoped, module = _module_for_scoped_loader(loader, manager)
    natural_spec = module.__spec__

    with pytest.raises(type(failure)):
        scoped.exec_module(module)

    assert loader.observed == (loader, loader)
    assert module.__spec__ is natural_spec
    assert module.__spec__ is not None
    assert module.__spec__.loader is loader
    assert module.__loader__ is loader
    assert manager.installed == ([] if failure_owner == "loader" else [module])


def test_campaign_rejects_zero_duration_backdating_and_utc_overlap() -> None:
    zero_duration = campaign().model_dump(mode="python")
    zero_duration["attempts"][0]["completed_at_utc"] = zero_duration["attempts"][0][
        "started_at_utc"
    ]
    with pytest.raises(ValidationError, match="duration|interval|completion"):
        LatencyCampaign.model_validate(zero_duration)

    backdated = campaign().model_dump(mode="python")
    started = backdated["attempts"][0]["started_at_utc"]
    backdated["attempts"][0]["completed_at_utc"] = started - timedelta(microseconds=1)
    with pytest.raises(ValidationError, match="duration|interval|completion"):
        LatencyCampaign.model_validate(backdated)

    overlapping = campaign().model_dump(mode="python")
    first_completed = overlapping["attempts"][0]["completed_at_utc"]
    overlapping["attempts"][1]["started_at_utc"] = first_completed - timedelta(
        milliseconds=1
    )
    overlapping["attempts"][1]["completed_at_utc"] = first_completed + timedelta(
        milliseconds=199
    )
    with pytest.raises(ValidationError, match="overlap|non-overlap"):
        LatencyCampaign.model_validate(overlapping)


def test_campaign_rejects_non_interleaved_execution_even_if_slots_are_relabelled() -> (
    None
):
    value = campaign().model_dump(mode="python")
    value["plan"] = list(value["plan"])
    value["attempts"] = list(value["attempts"])
    second = deepcopy(value["plan"][1])
    third = deepcopy(value["plan"][2])
    value["plan"][1], value["plan"][2] = third, second
    value["attempts"][1], value["attempts"][2] = (
        deepcopy(value["attempts"][2]),
        deepcopy(value["attempts"][1]),
    )
    base_started = value["attempts"][0]["started_at_utc"]
    for order_index, (slot, attempt) in enumerate(
        zip(value["plan"], value["attempts"], strict=True),
        start=1,
    ):
        slot["order_index"] = order_index
        attempt["order_index"] = order_index
        started = base_started + timedelta(seconds=order_index)
        attempt["started_at_utc"] = started
        attempt["completed_at_utc"] = started + timedelta(milliseconds=500)
        provider = attempt["provider_total_latency"]
        if provider is not None:
            provider["observed_at_utc"] = started + timedelta(seconds=1)

    with pytest.raises(ValidationError, match="round-major|alternate"):
        LatencyCampaign.model_validate(value)


def test_failure_codes_use_a_closed_content_free_vocabulary() -> None:
    with pytest.raises(ValidationError, match="failure code|closed"):
        FailureRecord(
            code="customer_account_8675309",
            stage=StageName.REQUEST_TOTAL,
            exception_type=FailureType.REQUEST_EXCEPTION,
        )

    with pytest.raises(ValidationError, match="failure code|closed"):
        StageSpan(
            span_id="request",
            name=StageName.REQUEST_TOTAL,
            parent_span_id=None,
            started_monotonic_ns=1,
            ended_monotonic_ns=2,
            status=StageStatus.ERROR,
            failure_code="document_title_secret",
        )


def test_manifest_verifier_recomputes_hostile_callable_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_value = _synthetic_manifest().model_dump(mode="json")
    baseline_targets = {
        item["target_id"]: deepcopy(item) for item in baseline_value["targets"]
    }
    baseline = InstrumentationManifest.model_validate(baseline_value)

    monkeypatch.setattr(
        latency_instrumentation,
        "harness_file_identities",
        lambda _workspace: baseline.harness_files,
    )

    def retained_source_metadata(definition: Any, _workspace: Path):
        target = baseline_targets[definition.target_id]
        return (
            baseline.targets[0].source.model_validate(target["source"]),
            target["module"],
            target["qualname"],
            target["signature"],
            target["code_sha256"],
        )

    monkeypatch.setattr(
        latency_instrumentation,
        "_ast_target_metadata",
        retained_source_metadata,
    )
    latency_instrumentation.verify_instrumentation_manifest(
        baseline,
        workspace=tmp_path,
    )

    hostile_routing = baseline.model_dump(mode="json")
    routing_target = next(
        item
        for item in hostile_routing["targets"]
        if item["target_id"] == "api-parse-dispatch"
    )
    routing_target["module"] = "hostile.source.derived"
    routing_target["qualname"] = "PatientName.run"
    _rehash_manifest(hostile_routing)
    with pytest.raises(ValidationError, match="target inventory"):
        InstrumentationManifest.model_validate(hostile_routing)

    hostile_code = baseline.model_dump(mode="json")
    target = next(
        item
        for item in hostile_code["targets"]
        if item["target_id"] == "api-parse-dispatch"
    )
    target["signature"] = "(patient_name: str) -> str"
    target["signature_sha256"] = hashlib.sha256(
        target["signature"].encode("utf-8")
    ).hexdigest()
    target["code_sha256"] = "0" * 64
    _rehash_manifest(hostile_code)
    forged = InstrumentationManifest.model_validate(hostile_code)

    with pytest.raises(ValueError, match="metadata differs"):
        latency_instrumentation.verify_instrumentation_manifest(
            forged,
            workspace=tmp_path,
        )


def test_current_environment_is_explicitly_noncomparable_with_p00() -> None:
    retained = derive_environment_manifest()
    assert retained.observed_docling_core_version == "2.88.0"
    assert retained.p00_reference_docling_core_version == "2.87.1"
    assert retained.p00_comparable is False
    assert retained.noncomparability_reason == ("docling-core-2.88.0-vs-p00-2.87.1")
    assert derive_environment_sha256() == retained.manifest_sha256

    forged = retained.model_dump(mode="json")
    forged["p00_comparable"] = True
    _rehash_manifest(forged)
    with pytest.raises(ValidationError, match="p00_comparable|False"):
        EnvironmentIdentityEvidence.model_validate(forged)


def _failed_twin_attempt(
    *, status: AttemptStatus, exception_type: FailureType
) -> dict[str, Any]:
    value = campaign().attempts[0].model_dump(mode="json")
    value["status"] = status.value
    value["evidence_complete"] = False
    value["output"] = None
    value["diagnostic_output"] = None
    value["stage_trace"] = stage_trace(
        value["diagnostic_total_latency_ns"],
        status=status,
    ).model_dump(mode="json")
    failure = {
        "code": "parse_failed",
        "stage": "pipeline.docling_conversion",
        "exception_type": exception_type.value,
    }
    value["failure"] = failure
    value["diagnostic_failure"] = deepcopy(failure)
    value["failure_stage_parity_policy"] = (
        "authoritative-root-versus-diagnostic-first-failed-stage-v1"
    )
    return value


@pytest.mark.parametrize(
    ("status", "exception_type"),
    (
        (AttemptStatus.ERROR, FailureType.REQUEST_EXCEPTION),
        (AttemptStatus.TIMEOUT, FailureType.WORKER_TIMEOUT),
        (AttemptStatus.ERROR, FailureType.WORKER_CRASH),
    ),
)
def test_failed_timeout_and_crash_twins_retain_available_process_evidence(
    status: AttemptStatus,
    exception_type: FailureType,
) -> None:
    retained = _failed_twin_attempt(status=status, exception_type=exception_type)
    accepted = LatencyAttempt.model_validate(retained)
    assert accepted.process_tree is not None
    assert accepted.diagnostic_process_tree is not None
    assert accepted.process_tree.resource_boundary_complete is True
    assert accepted.diagnostic_process_tree.resource_boundary_complete is True

    for field in ("process_tree", "diagnostic_process_tree"):
        missing = deepcopy(retained)
        missing[field] = None
        with pytest.raises(ValidationError, match="process|resource|twin evidence"):
            LatencyAttempt.model_validate(missing)

    incomplete = deepcopy(retained)
    incomplete["process_tree"]["resource_boundary_complete"] = False
    with pytest.raises(ValidationError, match="resource|process"):
        LatencyAttempt.model_validate(incomplete)


def test_prewarmed_twin_retains_both_request_resource_boundaries() -> None:
    value = campaign().attempts[0].model_dump(mode="json")
    configuration = value["configuration"]
    configuration.update(
        {
            "worker_lifecycle": ("fresh_process_request_prewarmed_after_app_startup"),
            "prewarm_completed_before_request": True,
            "internal_reuse_state": "prewarmed_before_request",
            "pipeline_import_state_at_request_start": "loaded_by_controlled_prewarm",
            "engine_cache_state_at_request_start": "prewarmed_process_cache",
        }
    )
    configuration["system_configuration_sha256"] = configuration_identity_sha256(
        configuration
    )
    for field in ("authoritative_cache_state", "diagnostic_cache_state"):
        cache = value[field]
        cache.update(
            {
                "profile": "request_prewarmed_after_app_startup",
                "pipeline_loaded_at_request_start": True,
                "converter_cache_entries_at_request_start": 1,
                "converter_cache_entries_after_request": 1,
                "prewarm_request_completed": True,
                "prewarm_evidence": {
                    "policy": "separate-pinned-route-equivalent-source-v1",
                    "source": {
                        "case_id": "synthetic-prewarm",
                        "path": (
                            "tests/fixtures/phase_latency/synthetic-prewarm.pdf"
                        ),
                        "filename": "synthetic-prewarm.pdf",
                        "sha256": "b" * 64,
                        "size_bytes": 1,
                        "page_count": 1,
                    },
                    "output": value["output"],
                    "duration_ns": 1,
                    "worker_self_cpu_ns": 0,
                    "reaped_children_cpu_ns": 0,
                    "worker_process_lifetime_hwm_bytes": 1,
                    "reaped_children_process_lifetime_hwm_bytes": 0,
                    "content_result_cache_observed": False,
                },
            }
        )

    retained = LatencyAttempt.model_validate(value)
    assert retained.authoritative_cache_state is not None
    assert retained.authoritative_cache_state.prewarm_request_completed is True
    assert retained.process_tree is not None
    assert retained.diagnostic_process_tree is not None
    assert retained.process_tree.resource_boundary_complete is True
    assert retained.diagnostic_process_tree.resource_boundary_complete is True

    incomplete = deepcopy(value)
    incomplete["diagnostic_process_tree"]["resource_boundary_complete"] = False
    with pytest.raises(ValidationError, match="resource boundary"):
        LatencyAttempt.model_validate(incomplete)


def test_identity_tree_stops_at_bound_before_materializing_the_full_walk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "app").mkdir()
    yielded = 0

    class HostileEntry:
        path = str(tmp_path / "unreached.py")

        @staticmethod
        def is_symlink() -> bool:
            return False

        @staticmethod
        def is_dir(*, follow_symlinks: bool) -> bool:
            assert follow_symlinks is False
            return False

        @staticmethod
        def is_file(*, follow_symlinks: bool) -> bool:
            assert follow_symlinks is False
            return True

    class HostileScandir:
        def __enter__(self):
            def entries():
                nonlocal yielded
                for _index in range(100_000):
                    yielded += 1
                    if yielded > 8_193:
                        raise AssertionError(
                            "identity traversal consumed beyond its hard bound"
                        )
                    yield HostileEntry()

            return entries()

        def __exit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(latency_runner.os, "scandir", lambda _path: HostileScandir())
    with pytest.raises(ValueError, match="entry-count bound"):
        _tree_identity(tmp_path, "app", suffixes=(".py",))
    assert yielded == 8_193


def test_phase_exit_rejects_coordinated_campaign_and_runtime_oracle_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.phase_03.running_regions import oracle

    value = phase_exit_campaign().model_dump(mode="json")
    hostile_oracle = deepcopy(oracle.SOURCE_IDENTITIES)
    hostile_oracle["catastrophe-recap"]["sha256"] = "0" * 64
    for attempt in value["attempts"]:
        if attempt["case_id"] == "catastrophe-recap":
            attempt["source"]["sha256"] = "0" * 64
    monkeypatch.setattr(oracle, "SOURCE_IDENTITIES", hostile_oracle)

    with pytest.raises(ValidationError, match="oracle|registry|source custody"):
        LatencyCampaign.model_validate(value)
