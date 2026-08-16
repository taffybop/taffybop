"""P00-US03 repeated-run baseline and fail-closed reporting contracts."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.benchmarks.baseline_report import (
    DEFAULT_EXECUTION_POLICY,
    EXPECTED_API_SCHEMA_HASHES,
    EXPECTED_FULL_REGRESSION_SKIPS,
    EXPECTED_GATE_COMMANDS,
    RUNNER_VERSION,
    BaselineReport,
    CompatibilityEvidence,
    ExecutionPolicy,
    OutputEvidence,
    QualityCheck,
    ReferenceRun,
    SkipRecord,
    VerificationGate,
    capture_runs,
    canonical_payload_bytes,
    evaluate_catastrophe_quality,
    load_reference_run,
    nearest_rank,
    quality_outcome_payload,
    semantic_json_bytes,
    sha256_path,
    sha256_bytes,
    summarize_stability,
    summarize_distribution,
    validate_reference_run_artifacts,
)
from tests.benchmarks.contracts import (
    FixtureManifest,
    MetricUnit,
    canonical_json,
)
from tests.benchmarks.source_truth import load_catastrophe_source_truth


WORKSPACE = Path(__file__).resolve().parents[3]
TRUTH_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US02-catastrophe-truth.json"
)
CURRENT_OUTPUT_ROOT = (
    WORKSPACE
    / "tracker"
    / "benchmarks"
    / "llamaparse-15"
    / "runs"
    / "baseline-20260728-current"
    / "catastrophe-recap"
)
NODE = Path("/opt/homebrew/opt/node@24/bin/node")
RUNS_ROOT = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US03-baseline-runs-20260728"
)
EXPECTED_RUN_SET_SHA256 = (
    "a87053e9c3e019ff1aab98c3c73bb8247654c49ac14faa1237f9503dc519ac0d"
)
EXPECTED_RUN_RECORD_HASHES = {
    "catastrophe-cold-01": (
        "d57000465eeaa64c82e6612cf2a4641c83df175cb922787331b439f191fc07c2"
    ),
    "catastrophe-cold-02": (
        "15fd130045a881f6f21cb8acb7973c787bf7c45c94d5f8b0094a867a25d25906"
    ),
    "catastrophe-cold-03": (
        "eba219572b2cf0f8b9cf8228551ff9303ba1f8d8e722e6e9643946e75d40d68b"
    ),
    "catastrophe-cold-04": (
        "8eec670acca339f8b0f34d97ab9e8365e4d237158b7c4dec3d039d0d50b1e1cb"
    ),
    "catastrophe-cold-05": (
        "4642f2251d2b2ff13acff0542bb5a5c8ae54fc2cd6016cc1f0ba5347f20d352a"
    ),
}
EXPECTED_SEMANTIC_SHA256 = (
    "0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9"
)
EXPECTED_MARKDOWN_SHA256 = (
    "9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1"
)
EXPECTED_FRONTEND_TEXT_SHA256 = (
    "8e6cdbc380d86ebcfd0e3d79ee61cc76b584aea4c959078b5d4cdad1fd18eb45"
)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _environment() -> dict[str, str]:
    return {
        "platform": "test-platform",
        "machine": "test-machine",
        "processor": "test-processor",
        "logical_cpu_count": "8",
        "python": "3.13.5",
        "python_executable": ".venv/bin/python",
        "node": "v24.18.0",
        "application": "0.1.0",
        "pytest": "8.4.1",
        "pydantic": "2.11.7",
        "docling": "2.43.0",
        "docling-core": "2.44.0",
        "pdfplumber": "0.11.7",
        "pypdfium2": "4.30.0",
        "pillow": "11.3.0",
        "tesseract": "tesseract 5.5.1",
        "source_tree_sha256": SHA_D,
    }


def _versions() -> dict[str, str]:
    environment = _environment()
    return {
        key: environment[key]
        for key in (
            "application",
            "docling",
            "docling-core",
            "pdfplumber",
            "pypdfium2",
            "pillow",
            "tesseract",
            "node",
            "source_tree_sha256",
        )
    }


def _quality_checks() -> tuple[QualityCheck, ...]:
    from tests.benchmarks.baseline_report import REQUIRED_QUALITY_IDS

    return tuple(
        QualityCheck(
            check_id=check_id,
            gap_id=f"gap-{index:02d}",
            category="text",
            passed=index < 5,
            expected="registered expectation",
            observed="registered observation",
            evidence_ids=(f"evidence-{index:02d}",),
            safety_guardrail=index < 5,
        )
        for index, check_id in enumerate(sorted(REQUIRED_QUALITY_IDS))
    )


def _output() -> OutputEvidence:
    return OutputEvidence(
        raw_json_path="evidence/run/our-output.json",
        raw_json_sha256=SHA_A,
        raw_json_size_bytes=100,
        semantic_json_sha256=SHA_B,
        semantic_json_size_bytes=90,
        backend_markdown_path="evidence/run/our-output.md",
        backend_markdown_sha256=SHA_C,
        backend_markdown_size_bytes=50,
        frontend_normalized_json_path=(
            "evidence/run/frontend-normalized.json"
        ),
        frontend_normalized_json_sha256=SHA_A,
        frontend_normalized_json_size_bytes=120,
        frontend_markdown_path="evidence/run/frontend-markdown.md",
        frontend_markdown_sha256=SHA_C,
        frontend_markdown_size_bytes=50,
        frontend_text_path="evidence/run/frontend-text.txt",
        frontend_text_sha256=SHA_D,
        frontend_text_size_bytes=40,
    )


def _run(index: int) -> ReferenceRun:
    return ReferenceRun(
        schema_version="1.0",
        runner_version=RUNNER_VERSION,
        run_id=f"run-{index:02d}",
        status="success",
        fixture_id="catastrophe-recap",
        source_sha256=SHA_A,
        expert_markdown_sha256=SHA_B,
        expert_json_sha256=SHA_C,
        truth_sha256=SHA_D,
        started_at_utc="2026-07-28T00:00:00+00:00",
        completed_at_utc="2026-07-28T00:00:10+00:00",
        command=("python", "worker", f"--run={index}"),
        cwd=".",
        settings_sha256=_settings_hash(),
        execution_policy=ExecutionPolicy.model_validate(
            DEFAULT_EXECUTION_POLICY
        ),
        environment=_environment(),
        versions=_versions(),
        duration_ms=float(index * 100),
        cpu_ms=float(index * 80),
        peak_rss_bytes=index * 100 * 1024 * 1024,
        output=_output(),
        quality_checks=_quality_checks(),
    )


def _gate(gate_id: str) -> VerificationGate:
    skip_records: tuple[SkipRecord, ...] = ()
    if gate_id == "backend_full_regression":
        skip_records = tuple(
            SkipRecord(
                node_id=node_id,
                owner_role=values[0],
                reason=values[1],
                opt_in_condition=values[2],
            )
            for node_id, values in EXPECTED_FULL_REGRESSION_SKIPS.items()
        )
    return VerificationGate(
        gate_id=gate_id,
        command=EXPECTED_GATE_COMMANDS[gate_id],
        cwd="frontend" if gate_id.startswith("frontend_") else ".",
        runtime=(
            "Node.js v24.18.0"
            if gate_id.startswith("frontend_")
            else "Python 3.13.5 / pytest 9.1.1"
        ),
        status="pass",
        pass_count=1,
        fail_count=0,
        skip_count=len(skip_records),
        warning_count=0,
        skip_records=skip_records,
        evidence=f"{gate_id} passed",
    )


def _compatibility() -> CompatibilityEvidence:
    return CompatibilityEvidence(
        schema_version="1.0",
        captured_at_utc="2026-07-28T00:01:00+00:00",
        api_schema_hashes=EXPECTED_API_SCHEMA_HASHES,
        gates=tuple(
            _gate(gate_id)
            for gate_id in (
                "backend_api_schema_serializer",
                "backend_full_regression",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_unit",
            )
        ),
    )


def _report() -> BaselineReport:
    runs = tuple(_run(index) for index in range(1, 6))
    quality_payload = quality_outcome_payload(runs[0].quality_checks)
    return BaselineReport(
        schema_version="1.0",
        report_id="P00-US03-catastrophe-baseline",
        runner_version=RUNNER_VERSION,
        fixture=FixtureManifest(
            schema_version="1.0",
            fixture_id="catastrophe-recap",
            source_sha256=SHA_A,
            source_format="PDF",
            custody="public-redistributable",
        ),
        expert_markdown_sha256=SHA_B,
        expert_json_sha256=SHA_C,
        truth_sha256=SHA_D,
        source_rights_sha256=SHA_A,
        generated_from_run_set="evidence/run-set.json",
        reference_command=("python", "capture"),
        settings=_settings(),
        settings_sha256=_settings_hash(),
        execution_policy=ExecutionPolicy.model_validate(
            DEFAULT_EXECUTION_POLICY
        ),
        environment=_environment(),
        run_count=5,
        runs=runs,
        duration_ms=summarize_distribution(
            [run.duration_ms for run in runs],
            MetricUnit.MILLISECONDS,
        ),
        peak_rss_mib=summarize_distribution(
            [run.peak_rss_bytes / (1024 * 1024) for run in runs],
            MetricUnit.MEBIBYTES,
        ),
        quality_pass_count=5,
        quality_fail_count=10,
        quality_signature=sha256_bytes(
            canonical_payload_bytes(quality_payload)
        ),
        stability=summarize_stability(runs),
        compatibility=_compatibility(),
    )


def _settings() -> dict[str, object]:
    return {"image_captioning_enabled": False}


def _settings_hash() -> str:
    return sha256_bytes(canonical_payload_bytes(_settings()))


def _mutated_payload(model: object, **changes: object) -> dict[str, object]:
    payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    payload.update(changes)
    return payload


def test_nearest_rank_p50_and_p95_are_explicit_for_five_runs() -> None:
    samples = [500.0, 100.0, 300.0, 200.0, 400.0]

    summary = summarize_distribution(samples, MetricUnit.MILLISECONDS)

    assert nearest_rank(samples, 0.50) == 300.0
    assert nearest_rank(samples, 0.95) == 500.0
    assert summary.p50 == 300.0
    assert summary.p95 == 500.0
    assert summary.percentile_method == "nearest_rank"
    with pytest.raises(ValueError, match="at least one"):
        nearest_rank([], 0.50)


def test_semantic_hash_masks_only_processing_duration() -> None:
    first = {
        "processing": {"duration_ms": 100, "engine": "docling"},
        "pages": [{"items": [{"value": "source text"}]}],
    }
    duration_only = {
        "processing": {"duration_ms": 200, "engine": "docling"},
        "pages": [{"items": [{"value": "source text"}]}],
    }
    content_change = {
        "processing": {"duration_ms": 100, "engine": "docling"},
        "pages": [{"items": [{"value": "changed"}]}],
    }

    assert semantic_json_bytes(first) == semantic_json_bytes(duration_only)
    assert semantic_json_bytes(first) != semantic_json_bytes(content_change)
    assert first["processing"]["duration_ms"] == 100


def test_frontend_projection_uses_supported_runtime_and_real_serializers(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            str(NODE),
            "--experimental-strip-types",
            str(WORKSPACE / "tests/benchmarks/frontend_projection.mts"),
            str(CURRENT_OUTPUT_ROOT / "our-output.json"),
            str(tmp_path),
        ],
        cwd=WORKSPACE,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    metadata = json.loads(completed.stdout)

    assert metadata["node"] == "v24.18.0"
    assert (
        (tmp_path / "frontend-markdown.md").read_bytes()
        == (CURRENT_OUTPUT_ROOT / "our-output.md").read_bytes()
    )
    for name, key in (
        ("frontend-normalized.json", "normalized_json_sha256"),
        ("frontend-markdown.md", "markdown_sha256"),
        ("frontend-text.txt", "text_sha256"),
    ):
        assert sha256_bytes((tmp_path / name).read_bytes()) == metadata[key]


def test_current_catastrophe_quality_vector_is_complete_and_source_grounded() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    payload = json.loads(
        (CURRENT_OUTPUT_ROOT / "our-output.json").read_text(encoding="utf-8")
    )
    markdown = (CURRENT_OUTPUT_ROOT / "our-output.md").read_text(
        encoding="utf-8"
    )

    checks = evaluate_catastrophe_quality(
        payload,
        markdown,
        markdown,
        truth,
    )
    outcomes = {check.check_id: check.passed for check in checks}

    assert len(outcomes) == 15
    assert {key for key, passed in outcomes.items() if passed} == {
        "backend_frontend_markdown_parity",
        "chart_routed_as_chart",
        "exhibit_7_table_exact",
        "logo_aon_retained_in_json",
        "unsupported_chart_values_withheld",
    }
    assert sum(outcomes.values()) == 5
    assert sum(not value for value in outcomes.values()) == 10


def test_quality_checks_reject_raw_rejected_misordered_and_fabricated_evidence(
) -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    original = json.loads(
        (CURRENT_OUTPUT_ROOT / "our-output.json").read_text(encoding="utf-8")
    )
    markdown = (CURRENT_OUTPUT_ROOT / "our-output.md").read_text(
        encoding="utf-8"
    )
    truth_elements = {element.element_id: element for element in truth.elements}

    payload = deepcopy(original)
    damaged_sentence = truth_elements["damaged-sentence"].text
    payload["pages"][0]["items"].append(
        {
            "type": "footer",
            "reading_order": 99,
            "value": damaged_sentence,
            "md": damaged_sentence,
        }
    )
    payload["pages"][0]["items"][0]["raw_ocr_text"] = damaged_sentence
    outcomes = {
        check.check_id: check.passed
        for check in evaluate_catastrophe_quality(
            payload,
            markdown,
            markdown,
            truth,
        )
    }
    assert not outcomes["damaged_sentence_exact"]

    payload = deepcopy(original)
    chart = next(
        item
        for item in payload["pages"][0]["items"]
        if item["type"] == "chart"
    )
    chart["raw_ocr_text"] += (
        "\n" + truth_elements["chart-source-note"].text
    )
    outcomes = {
        check.check_id: check.passed
        for check in evaluate_catastrophe_quality(
            payload,
            markdown,
            markdown,
            truth,
        )
    }
    assert not outcomes["chart_source_note_present"]

    payload = deepcopy(original)
    image = next(
        item
        for item in payload["pages"][0]["items"]
        if item["type"] == "image"
    )
    for child in image["items"]:
        child["accepted"] = False
    outcomes = {
        check.check_id: check.passed
        for check in evaluate_catastrophe_quality(
            payload,
            markdown,
            markdown,
            truth,
        )
    }
    assert not outcomes["logo_aon_retained_in_json"]

    payload = deepcopy(original)
    exhibit7_title = truth_elements["exhibit-7-title"].text
    payload["pages"][0]["items"].append(
        {
            "type": "text",
            "reading_order": 99,
            "value": exhibit7_title,
            "md": exhibit7_title,
        }
    )
    outcomes = {
        check.check_id: check.passed
        for check in evaluate_catastrophe_quality(
            payload,
            markdown,
            markdown,
            truth,
        )
    }
    assert not outcomes["exhibit_7_caption_separate"]

    payload = deepcopy(original)
    payload["pages"][0]["items"].append(
        {
            "type": "table",
            "reading_order": 99,
            "value": [
                ["region", "year", "annual", "first half"],
                ["USA", "2025", "125", "92"],
            ],
            "md": "| region | year | annual | first half |",
        }
    )
    outcomes = {
        check.check_id: check.passed
        for check in evaluate_catastrophe_quality(
            payload,
            markdown,
            markdown,
            truth,
        )
    }
    assert not outcomes["unsupported_chart_values_withheld"]


def test_capture_refuses_overwrite_and_rejects_changed_source(
    tmp_path: Path,
) -> None:
    source = (
        WORKSPACE
        / "benchmark-expertmodeldata"
        / "catastrophe-recap.pdf"
    )
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        capture_runs(
            source_path=source,
            truth_path=TRUTH_PATH,
            runs_root=tmp_path,
            repeat=5,
            node_command=str(NODE),
        )

    altered = tmp_path / "altered.pdf"
    altered.write_bytes(source.read_bytes() + b"altered")
    target = tmp_path / "new-run-root"
    with pytest.raises(SystemExit, match="source bytes do not match"):
        capture_runs(
            source_path=altered,
            truth_path=TRUTH_PATH,
            runs_root=target,
            repeat=5,
            node_command=str(NODE),
        )
    assert not target.exists()


def test_registered_five_run_capture_is_complete_stable_and_immutable() -> None:
    truth = load_catastrophe_source_truth(TRUTH_PATH)
    run_set_path = RUNS_ROOT / "run-set.json"
    run_set = json.loads(run_set_path.read_text(encoding="utf-8"))

    assert sha256_path(run_set_path) == EXPECTED_RUN_SET_SHA256
    assert run_set["status"] == "success"
    assert run_set["repeat"] == 5
    assert run_set["environment"]["source_tree_sha256"] == (
        "1a24a65b5a9cca959d1d805e8dc169714e0a67a84e0c4cf47c7cb9154ef4bfd7"
    )
    assert run_set["settings_sha256"] == (
        "27931e7bf4a5a04afcaa4c6139f35dadb7dc18a7ed16b2121c41b4e72d69e2e3"
    )
    assert run_set["execution_policy"] == DEFAULT_EXECUTION_POLICY

    runs = []
    for record_value in run_set["run_record_paths"]:
        record_path = WORKSPACE / record_value
        run = load_reference_run(record_path)
        runs.append(run)
        assert (
            sha256_path(record_path)
            == EXPECTED_RUN_RECORD_HASHES[run.run_id]
        )
        validate_reference_run_artifacts(run, record_path, truth)
        assert run.output is not None
        assert run.output.semantic_json_sha256 == EXPECTED_SEMANTIC_SHA256
        assert run.output.backend_markdown_sha256 == EXPECTED_MARKDOWN_SHA256
        assert run.output.frontend_markdown_sha256 == EXPECTED_MARKDOWN_SHA256
        assert (
            run.output.frontend_text_sha256
            == EXPECTED_FRONTEND_TEXT_SHA256
        )
        contract = run.run_contract()
        assert contract.duration_ms == run.duration_ms
        assert len(contract.metrics) == 5

    assert [run.run_id for run in runs] == [
        f"catastrophe-cold-{index:02d}" for index in range(1, 6)
    ]
    assert {run.status for run in runs} == {"success"}
    assert len({run.output.raw_json_sha256 for run in runs}) == 5
    assert {sum(check.passed for check in run.quality_checks) for run in runs} == {
        5
    }
    assert {
        sum(not check.passed for check in run.quality_checks) for run in runs
    } == {10}
    stability = summarize_stability(runs)
    assert stability.fixture_hashes_stable
    assert stability.quality_outcomes_stable
    assert stability.semantic_json_hashes_stable
    assert stability.backend_markdown_hashes_stable
    assert stability.frontend_markdown_hashes_stable
    assert stability.frontend_text_hashes_stable
    assert stability.raw_json_unique_hash_count == 5
    assert stability.frontend_normalized_json_unique_hash_count == 5


def test_every_retained_frontend_projection_rebuilds_byte_identically(
    tmp_path: Path,
) -> None:
    for run_id in EXPECTED_RUN_RECORD_HASHES:
        run_root = RUNS_ROOT / run_id
        rebuilt_root = tmp_path / run_id
        rebuilt_root.mkdir()
        completed = subprocess.run(
            [
                str(NODE),
                "--experimental-strip-types",
                str(WORKSPACE / "tests/benchmarks/frontend_projection.mts"),
                str(run_root / "our-output.json"),
                str(rebuilt_root),
            ],
            cwd=WORKSPACE,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert json.loads(completed.stdout)["node"] == "v24.18.0"
        for name in (
            "frontend-normalized.json",
            "frontend-markdown.md",
            "frontend-text.txt",
        ):
            assert (rebuilt_root / name).read_bytes() == (
                run_root / name
            ).read_bytes()


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("environment", "run environment is missing"),
        ("versions", "run versions are missing"),
        ("output", "successful runs require complete output"),
    ],
)
def test_successful_run_rejects_missing_reproducibility_evidence(
    field: str,
    message: str,
) -> None:
    run = _run(1)
    value: object
    if field == "environment":
        value = {"platform": "only-one-field"}
    elif field == "versions":
        value = {"application": "0.1.0"}
    else:
        value = None

    with pytest.raises(ValidationError, match=message):
        ReferenceRun.model_validate(_mutated_payload(run, **{field: value}))


def test_successful_run_rejects_duplicate_or_missing_quality_checks() -> None:
    run = _run(1)
    checks = run.model_dump(mode="json")["quality_checks"]
    checks[-1] = checks[0]

    with pytest.raises(
        ValidationError,
        match="every registered quality check|must be unique",
    ):
        ReferenceRun.model_validate(
            _mutated_payload(run, quality_checks=checks)
        )


def test_run_rejects_invalid_time_runtime_and_execution_policy() -> None:
    run = _run(1)

    with pytest.raises(ValidationError, match="ISO-8601"):
        ReferenceRun.model_validate(
            _mutated_payload(run, started_at_utc="not-a-timestamp")
        )

    payload = run.model_dump(mode="json")
    payload["environment"]["node"] = "v22.0.0"
    with pytest.raises(ValidationError, match=">=22.13.0"):
        ReferenceRun.model_validate(payload)

    payload = run.model_dump(mode="json")
    payload["execution_policy"]["hf_hub_offline"] = False
    with pytest.raises(ValidationError, match="Input should be True"):
        ReferenceRun.model_validate(payload)


def test_compatibility_rejects_hidden_failures_and_undocumented_skips() -> None:
    gate = _gate("backend_api_schema_serializer")
    hidden_failure = _mutated_payload(gate, fail_count=1)
    with pytest.raises(ValidationError, match="cannot hide failures"):
        VerificationGate.model_validate(hidden_failure)

    undocumented_skip = _mutated_payload(gate, skip_count=1)
    with pytest.raises(ValidationError, match="explicit skip records"):
        VerificationGate.model_validate(undocumented_skip)

    documented = _mutated_payload(
        gate,
        skip_count=1,
        skip_records=[
            SkipRecord(
                node_id="tests/test_example.py::test_model",
                owner_role="model-maintainers",
                reason="Opt-in local model is intentionally disabled.",
                opt_in_condition="Set RUN_MODEL_INTEGRATION=1.",
            ).model_dump(mode="json")
        ],
    )
    assert VerificationGate.model_validate(documented).skip_count == 1

    zero_passes = _mutated_payload(gate, pass_count=0)
    with pytest.raises(ValidationError, match="successful assertion count"):
        VerificationGate.model_validate(zero_passes)


def test_compatibility_requires_all_gates_and_api_schema_hashes() -> None:
    compatibility = _compatibility()
    payload = compatibility.model_dump(mode="json")
    payload["gates"] = payload["gates"][:-1]
    with pytest.raises(ValidationError, match="at least 5|gates are missing"):
        CompatibilityEvidence.model_validate(payload)

    payload = compatibility.model_dump(mode="json")
    payload["api_schema_hashes"].pop("error_response")
    with pytest.raises(
        ValidationError,
        match="at least 3|schema hashes are missing",
    ):
        CompatibilityEvidence.model_validate(payload)

    payload = compatibility.model_dump(mode="json")
    payload["api_schema_hashes"] = {
        name: "0" * 64 for name in EXPECTED_API_SCHEMA_HASHES
    }
    with pytest.raises(ValidationError, match="captured contract"):
        CompatibilityEvidence.model_validate(payload)

    payload = compatibility.model_dump(mode="json")
    frontend_gate = next(
        gate
        for gate in payload["gates"]
        if gate["gate_id"] == "frontend_typecheck"
    )
    frontend_gate["runtime"] = "Node.js v22.0.0"
    with pytest.raises(ValidationError, match=">=22.13.0"):
        CompatibilityEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("fixture_drift", "fixture/settings identities"),
        ("partial_run", "fail closed"),
        ("timeout_run", "fail closed"),
        ("semantic_drift", "stability summary|must remain stable"),
        ("quality_drift", "quality outcomes must reproduce"),
        ("environment_drift", "report environment identity"),
    ],
)
def test_report_rejects_drift_and_partial_evidence(
    mutation: str,
    message: str,
) -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    last_run = payload["runs"][-1]

    if mutation == "fixture_drift":
        last_run["source_sha256"] = SHA_B
    elif mutation in {"partial_run", "timeout_run"}:
        last_run["status"] = (
            "timeout" if mutation == "timeout_run" else "error"
        )
        last_run["error"] = {
            "type": "TimeoutExpired" if mutation == "timeout_run" else "RuntimeError",
            "message": "failed",
        }
    elif mutation == "semantic_drift":
        last_run["output"]["semantic_json_sha256"] = SHA_C
    elif mutation == "quality_drift":
        last_run["quality_checks"][0]["passed"] = not last_run[
            "quality_checks"
        ][0]["passed"]
    else:
        last_run["environment"]["machine"] = "different-machine"

    with pytest.raises(ValidationError, match=message):
        BaselineReport.model_validate(payload)


def test_report_requires_five_unique_runs_and_declared_volatility() -> None:
    report = _report()
    payload = report.model_dump(mode="json")
    payload["run_count"] = 4
    payload["runs"] = payload["runs"][:4]
    with pytest.raises(ValidationError, match="greater than or equal to 5"):
        BaselineReport.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["runs"][-1]["run_id"] = payload["runs"][0]["run_id"]
    with pytest.raises(ValidationError, match="run IDs must be unique"):
        BaselineReport.model_validate(payload)

    payload = report.model_dump(mode="json")
    payload["stability"]["volatility_allowlist"] = [
        "/processing/duration_ms",
        "/document/sha256",
    ]
    with pytest.raises(
        ValidationError,
        match="stability summary|declared duration",
    ):
        BaselineReport.model_validate(payload)


def test_run_record_projection_and_report_serialization_are_deterministic() -> None:
    run_record = _run(1).run_contract()
    report = _report()

    assert run_record.fixture_hashes == {
        "source_pdf": SHA_A,
        "expert_markdown": SHA_B,
        "expert_json": SHA_C,
        "source_truth": SHA_D,
    }
    assert run_record.output_hashes["semantic_json"] == SHA_B
    assert len(run_record.metrics) == 5
    assert canonical_json(run_record) == canonical_json(run_record)
    assert canonical_json(report) == canonical_json(
        BaselineReport.model_validate_json(canonical_json(report))
    )
