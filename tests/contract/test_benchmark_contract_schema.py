"""Regression-facing schema contract for P00-US01 benchmark artifacts."""

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import (
    CONTRACT_VERSION,
    Annotation,
    FixtureManifest,
    MetricRecord,
    MetricUnit,
    RunRecord,
    json_schema,
)


def test_benchmark_contract_schemas_are_versioned_and_self_describing() -> None:
    manifest_schema = json_schema(FixtureManifest)
    annotation_schema = json_schema(Annotation)
    run_schema = json_schema(RunRecord)
    metric_schema = json_schema(MetricRecord)

    for schema in (
        manifest_schema,
        annotation_schema,
        metric_schema,
        run_schema,
    ):
        assert schema["properties"]["schema_version"]["const"] == CONTRACT_VERSION
        assert "schema_version" in schema["required"]
        assert schema["additionalProperties"] is False

    assert manifest_schema["properties"]["source_sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert {
        "parser_version",
        "commands",
        "hardware",
        "fixture_hashes",
        "output_hashes",
    } <= set(run_schema["required"])
    assert run_schema["properties"]["commands"]["items"]["minLength"] == 1
    assert (
        run_schema["properties"]["fixture_hashes"]["additionalProperties"]["pattern"]
        == "^[0-9a-f]{64}$"
    )
    assert (
        run_schema["properties"]["output_hashes"]["additionalProperties"]["pattern"]
        == "^[0-9a-f]{64}$"
    )
    assert metric_schema["$defs"]["MetricUnit"]["enum"] == [
        unit.value for unit in MetricUnit
    ]
    assert "measurement_method" in metric_schema["required"]
    assert metric_schema["properties"]["tolerance"]["minimum"] == 0
    exact_parity_rule = annotation_schema["allOf"][0]
    assert exact_parity_rule["if"]["properties"]["include_in_exact_parity"]["const"] is True
    assert set(exact_parity_rule["then"]["properties"]["truth_class"]["enum"]) == {
        "visible_text",
        "native_data",
        "embedded_data",
    }


@pytest.mark.parametrize("field", ["value", "tolerance"])
def test_metric_contract_rejects_nonfinite_json_numbers(field: str) -> None:
    payload = (
        '{"schema_version":"1.0","metric_name":"invalid",'
        '"measurement_method":"contract-test","value":1,"unit":"count",'
        '"tolerance":0,"evidence_class":"measured"}'
    ).replace(f'"{field}":1', f'"{field}":Infinity').replace(
        f'"{field}":0', f'"{field}":Infinity'
    )

    with pytest.raises(ValidationError, match="finite number"):
        MetricRecord.model_validate_json(payload)
