"""Contract and compatibility gates for the P00-US04 corpus registry."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.benchmarks.contracts import CONTRACT_VERSION, FixtureManifest
from tests.benchmarks.corpus_registry import (
    PERMITTED_USES,
    PortableCorpusRegistry,
    RegistryCase,
    RegistryCustody,
    RegistryPageIdentity,
    load_corpus_registry,
    resolve_portable_path,
)


WORKSPACE = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    WORKSPACE
    / "tracker"
    / "phase-00-baseline"
    / "evidence"
    / "P00-US04-corpus-registry.json"
)
SHA256_PATTERN = "^[0-9a-f]{64}$"
EXPECTED_SCHEMA_HASHES = {
    "FixtureManifest": (
        "dfdba13242b8c85eaa809de2c4f1e6a8961c2034f99e10e1fae3240513f4480a"
    ),
    "RegistryPageIdentity": (
        "284249e2c22c9c9c4f6a3ed8ca676c10bdd426253cec3b1635f5c1e44fe0e675"
    ),
    "RegistryCustody": (
        "46fcd834997efcd751b0e3daac1ffd98cd5f1b2c69da951d24ba2ee0783c1566"
    ),
    "RegistryCase": (
        "f5b6c62b7d04a583b26e3fa538e8fc906fb76d2bd64d851c0f939905ad49bac5"
    ),
    "PortableCorpusRegistry": (
        "ccf050234c7a483027f073cb84778c96cdf4c16ffce7d99ff86e5833fcb569e2"
    ),
}


def _payload() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _schema_hash(model: type[FixtureManifest]) -> str:
    payload = json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_registry_schemas_are_strict_versioned_and_hash_pinned() -> None:
    models = (
        FixtureManifest,
        RegistryPageIdentity,
        RegistryCustody,
        RegistryCase,
        PortableCorpusRegistry,
    )

    assert {model.__name__: _schema_hash(model) for model in models} == (
        EXPECTED_SCHEMA_HASHES
    )
    for model in models:
        assert model.model_json_schema()["additionalProperties"] is False

    registry = PortableCorpusRegistry.model_json_schema()
    assert registry["properties"]["schema_version"]["const"] == CONTRACT_VERSION
    assert registry["required"] == [
        "schema_version",
        "registry_id",
        "corpus_root",
        "source_files_immutable",
        "case_count",
        "page_count",
        "artifact_count",
        "inventory_manifest_path",
        "inventory_manifest_sha256",
        "custody",
        "cases",
    ]
    assert registry["properties"]["case_count"]["const"] == 15
    assert registry["properties"]["page_count"]["const"] == 30
    assert registry["properties"]["artifact_count"]["const"] == 45
    assert registry["properties"]["cases"]["minItems"] == 15
    assert registry["properties"]["cases"]["maxItems"] == 15
    assert (
        registry["properties"]["inventory_manifest_sha256"]["pattern"]
        == SHA256_PATTERN
    )


def test_nested_schema_constraints_cover_roles_pages_hashes_and_custody() -> None:
    schema = PortableCorpusRegistry.model_json_schema()
    defs = schema["$defs"]
    case = defs["RegistryCase"]
    artifact = defs["ArtifactIdentity"]
    page = defs["RegistryPageIdentity"]
    custody = defs["RegistryCustody"]

    assert all(
        definition["additionalProperties"] is False
        for definition in (case, artifact, page, custody)
    )
    assert case["properties"]["artifacts"]["minItems"] == 3
    assert case["properties"]["artifacts"]["maxItems"] == 3
    assert defs["ArtifactRole"]["enum"] == [
        "source",
        "expert_markdown",
        "expert_json",
    ]
    assert artifact["properties"]["sha256"]["pattern"] == SHA256_PATTERN
    assert artifact["properties"]["size_bytes"]["exclusiveMinimum"] == 0
    assert page["properties"]["physical_page"]["minimum"] == 1
    assert page["properties"]["source_rotation_deg"]["enum"] == [0, 90, 180, 270]
    assert {"type": "null"} in page["properties"]["printed_page"]["anyOf"]
    assert custody["properties"]["decision"]["const"] == "public-redistributable"
    assert custody["properties"]["no_exceptions"]["const"] is True
    assert custody["properties"]["derived_annotations_covered"]["const"] is True
    assert custody["properties"]["permitted_uses"]["minItems"] == len(PERMITTED_USES)
    assert custody["properties"]["permitted_uses"]["maxItems"] == len(PERMITTED_USES)
    assert custody["properties"]["permitted_uses"]["items"]["enum"] == list(
        PERMITTED_USES
    )
    assert custody["properties"]["decision_sha256"]["pattern"] == SHA256_PATTERN
    assert custody["properties"]["evidence_sha256"]["pattern"] == SHA256_PATTERN


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", "2.0"),
        ("case_count", 14),
        ("page_count", 29),
        ("artifact_count", 44),
        ("inventory_manifest_sha256", "A" * 64),
    ],
)
def test_registry_rejects_wrong_version_counts_and_hashes(
    field: str,
    invalid: object,
) -> None:
    payload = _payload()
    payload[field] = invalid

    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(payload)


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/catastrophe-recap.pdf",
        "../benchmark-expertmodeldata/catastrophe-recap.pdf",
        "benchmark-expertmodeldata/../catastrophe-recap.pdf",
        r"benchmark-expertmodeldata\catastrophe-recap.pdf",
    ],
)
def test_registry_rejects_nonportable_artifact_paths(path: str) -> None:
    payload = _payload()
    payload["cases"][0]["artifacts"][0]["path"] = path

    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(payload)
    with pytest.raises(ValueError):
        resolve_portable_path(WORKSPACE, path)


def test_extra_fields_and_malformed_nested_values_are_rejected() -> None:
    extra = _payload()
    extra["unexpected"] = True
    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(extra)

    nested_extra = _payload()
    nested_extra["cases"][0]["pages"][0]["rotation"] = 0
    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(nested_extra)

    bad_hash = _payload()
    bad_hash["cases"][0]["artifacts"][0]["sha256"] = "0" * 63
    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(bad_hash)

    missing_case = _payload()
    missing_case["cases"].pop()
    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(missing_case)

    duplicate_role = deepcopy(_payload())
    duplicate_role["cases"][0]["artifacts"][1]["role"] = "source"
    with pytest.raises(ValidationError):
        PortableCorpusRegistry.model_validate(duplicate_role)


def test_p00_us01_fixture_manifest_schema_and_projection_are_unchanged() -> None:
    fixture_schema = FixtureManifest.model_json_schema()
    assert fixture_schema["properties"]["schema_version"]["const"] == CONTRACT_VERSION
    assert fixture_schema["properties"]["source_sha256"]["pattern"] == SHA256_PATTERN
    assert fixture_schema["required"] == [
        "schema_version",
        "fixture_id",
        "source_sha256",
        "source_format",
        "custody",
    ]

    registry = load_corpus_registry(REGISTRY_PATH)
    for case in registry.cases:
        fixture = case.fixture_manifest()
        assert isinstance(fixture, FixtureManifest)
        assert fixture.schema_version == CONTRACT_VERSION
        assert fixture.fixture_id == case.case_id
        assert fixture.source_sha256 == case.artifacts[0].sha256
        assert fixture.source_format == "PDF"
        assert fixture.custody == "public-redistributable"
