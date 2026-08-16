"""P00-US01 tests for versioned benchmark and metric contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    Annotation,
    FixtureManifest,
    MetricRecord,
    MetricUnit,
    RunRecord,
    TruthClass,
    canonical_json,
    json_schema,
    read_initial_run_record,
)


HASH = "a" * 64
OUTPUT_HASH = "b" * 64
PINNED_V1_RUN_JSON = (
    '{"commands":[".venv/bin/pytest tests/stories/phase_00/"],'
    '"duration_ms":12.5,"fixture_hashes":{"synthetic-source":"'
    + HASH
    + '"},"hardware":{"cpu":"synthetic","memory":"synthetic"},'
    '"metrics":[{"annotation_id":"claim-1","evidence_class":"visible_text",'
    '"fixture_id":"synthetic-source","measurement_method":"synthetic-control",'
    '"metric_name":"contract_validation","schema_version":"1.0",'
    '"tolerance":0.0,"unit":"ratio","value":1.0}],'
    '"model_versions":{"layout":"not-used"},"output_hashes":{"result.json":"'
    + OUTPUT_HASH
    + '"},"parser_version":"test-parser-1.0","run_id":"synthetic-p00-us01",'
    '"schema_version":"1.0"}'
)


def synthetic_run_record() -> RunRecord:
    """Minimal complete fixture: no external document or licensed corpus needed."""

    metric = MetricRecord(
        schema_version=CONTRACT_VERSION,
        metric_name="contract_validation",
        measurement_method="synthetic-control",
        fixture_id="synthetic-source",
        annotation_id="claim-1",
        value=1,
        unit=MetricUnit.RATIO,
        tolerance=0,
        evidence_class=TruthClass.VISIBLE_TEXT,
    )
    return RunRecord(
        schema_version=CONTRACT_VERSION,
        run_id="synthetic-p00-us01",
        parser_version="test-parser-1.0",
        model_versions={"layout": "not-used"},
        commands=(".venv/bin/pytest tests/stories/phase_00/",),
        hardware={"cpu": "synthetic", "memory": "synthetic"},
        fixture_hashes={"synthetic-source": HASH},
        output_hashes={"result.json": OUTPUT_HASH},
        duration_ms=12.5,
        metrics=(metric,),
    )


def test_complete_synthetic_run_record_round_trips_deterministically() -> None:
    record = synthetic_run_record()

    first = canonical_json(record)
    reloaded = read_initial_run_record(first)

    assert canonical_json(reloaded) == first
    assert reloaded.schema_version == CONTRACT_VERSION
    assert reloaded.fixture_hashes == {"synthetic-source": HASH}
    assert reloaded.output_hashes == {"result.json": OUTPUT_HASH}
    assert reloaded.commands == (".venv/bin/pytest tests/stories/phase_00/",)
    assert reloaded.hardware["memory"] == "synthetic"


def test_initial_schema_is_backward_readable_and_machine_readable() -> None:
    payload = json.loads(PINNED_V1_RUN_JSON)
    schema = json_schema(RunRecord)

    assert read_initial_run_record(PINNED_V1_RUN_JSON).model_dump(mode="json") == payload
    assert canonical_json(read_initial_run_record(PINNED_V1_RUN_JSON)) == PINNED_V1_RUN_JSON
    assert schema["properties"]["schema_version"]["const"] == CONTRACT_VERSION
    assert "schema_version" in schema["required"]
    assert "fixture_hashes" in schema["required"]
    assert "output_hashes" in schema["required"]


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: FixtureManifest(schema_version=CONTRACT_VERSION, fixture_id="x", source_sha256="bad", source_format="pdf", custody="private"), "pattern"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=1, unit="seconds", tolerance=0, evidence_class=TruthClass.MEASURED), "Input should be"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=1, unit="ms", tolerance=-0.1, evidence_class=TruthClass.MEASURED), "greater than or equal"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=-1, unit="count", tolerance=0, evidence_class=TruthClass.MEASURED), "greater than or equal"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=float("inf"), unit="count", tolerance=0, evidence_class=TruthClass.MEASURED), "finite number"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=1, unit="count", tolerance=float("inf"), evidence_class=TruthClass.MEASURED), "finite number"),
        (lambda: MetricRecord(schema_version=CONTRACT_VERSION, metric_name="x", measurement_method="test", value=float("nan"), unit="count", tolerance=0, evidence_class=TruthClass.MEASURED), "finite number"),
        (lambda: RunRecord.model_validate({**synthetic_run_record().model_dump(mode="json"), "schema_version": "v2"}), "Input should be '1.0'"),
        (lambda: RunRecord.model_validate({**synthetic_run_record().model_dump(mode="json"), "duration_ms": -1}), "greater than or equal"),
        (lambda: RunRecord.model_validate({**synthetic_run_record().model_dump(mode="json"), "duration_ms": float("inf")}), "finite number"),
        (lambda: RunRecord.model_validate({**synthetic_run_record().model_dump(mode="json"), "commands": [""]}), "at least 1 character"),
    ],
)
def test_malformed_contracts_fail_with_actionable_errors(factory: object, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        factory()  # type: ignore[operator]


def test_every_contract_requires_an_explicit_schema_version() -> None:
    records = (
        FixtureManifest(
            schema_version=CONTRACT_VERSION,
            fixture_id="synthetic-pdf",
            source_sha256=HASH,
            source_format="pdf",
            custody="synthetic-unrestricted",
        ),
        Annotation(
            schema_version=CONTRACT_VERSION,
            annotation_id="claim-1",
            fixture_id="synthetic-pdf",
            truth_class=TruthClass.VISIBLE_TEXT,
            claim="Visible claim",
        ),
        synthetic_run_record().metrics[0],
        synthetic_run_record(),
    )

    for record in records:
        payload = record.model_dump(mode="json")
        payload.pop("schema_version")
        with pytest.raises(ValidationError, match="Field required"):
            type(record).model_validate(payload)


def test_fixture_manifest_rejects_a_missing_source_hash() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        FixtureManifest.model_validate(
            {
                "schema_version": CONTRACT_VERSION,
                "fixture_id": "missing-source-hash",
                "source_format": "pdf",
                "custody": "synthetic-unrestricted",
            }
        )


@pytest.mark.parametrize("field", ["fixture_hashes", "output_hashes"])
def test_run_record_rejects_missing_hash_mappings(field: str) -> None:
    payload = synthetic_run_record().model_dump(mode="json")
    payload.pop(field)

    with pytest.raises(ValidationError, match="Field required"):
        RunRecord.model_validate(payload)


def test_unknown_truth_class_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        Annotation(
            schema_version=CONTRACT_VERSION,
            annotation_id="a1",
            fixture_id="fixture",
            truth_class="invented",  # type: ignore[arg-type]
            claim="Unsupported class",
        )


@pytest.mark.parametrize(
    "truth_class",
    [TruthClass.MEASURED, TruthClass.INFERRED, TruthClass.UNKNOWABLE],
)
def test_nonliteral_truth_classes_cannot_enter_exact_parity(
    truth_class: TruthClass,
) -> None:
    with pytest.raises(ValidationError, match="cannot enter exact parity"):
        Annotation(
            schema_version=CONTRACT_VERSION,
            annotation_id="a2",
            fixture_id="fixture",
            truth_class=truth_class,
            claim="Nonliteral evidence",
            include_in_exact_parity=True,
        )


def test_annotation_and_fixture_contracts_preserve_evidence_class_and_hash() -> None:
    manifest = FixtureManifest(
        schema_version=CONTRACT_VERSION,
        fixture_id="synthetic-pdf",
        source_sha256=HASH,
        source_format="pdf",
        custody="synthetic-unrestricted",
    )
    annotation = Annotation(
        schema_version=CONTRACT_VERSION,
        annotation_id="claim-1",
        fixture_id=manifest.fixture_id,
        truth_class=TruthClass.MEASURED,
        claim="A measured value is not literal visible text.",
    )
    metric = MetricRecord(
        schema_version=CONTRACT_VERSION,
        metric_name="measured_height",
        measurement_method="vector-axis-calibration",
        fixture_id=manifest.fixture_id,
        annotation_id=annotation.annotation_id,
        value=10.5,
        unit=MetricUnit.COUNT,
        tolerance=0.5,
        evidence_class=TruthClass.MEASURED,
    )

    for record in (manifest, annotation, metric):
        serialized = canonical_json(record)
        reloaded = type(record).model_validate_json(serialized)
        assert canonical_json(reloaded) == serialized

    assert json.loads(canonical_json(manifest))["source_sha256"] == HASH
    assert json.loads(canonical_json(annotation))["truth_class"] == "measured"
    assert json.loads(canonical_json(metric))["tolerance"] == 0.5
    assert json.loads(canonical_json(metric))["measurement_method"] == "vector-axis-calibration"
    assert json.loads(canonical_json(metric))["annotation_id"] == annotation.annotation_id


def test_canonical_json_rejects_nonfinite_values_even_for_unvalidated_models() -> None:
    bypassed_validation = MetricRecord.model_construct(
        schema_version=CONTRACT_VERSION,
        metric_name="invalid",
        measurement_method="bypassed",
        value=float("inf"),
        unit=MetricUnit.COUNT,
        tolerance=0,
        evidence_class=TruthClass.MEASURED,
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_json(bypassed_validation)
