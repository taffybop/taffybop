"""Versioned, deterministic contracts for benchmark reporting only.

These models intentionally live under ``tests``: they must not be imported by
the production parser or its public API.  They describe evidence submitted to
benchmark reports, not parser output.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTRACT_VERSION = "1.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SchemaVersion = Literal["1.0"]
NonEmptyString = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN.pattern)]


class ContractModel(BaseModel):
    """Base class that rejects ambiguous or silently ignored contract fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class TruthClass(str, Enum):
    """How a benchmark assertion is supported by the source material."""

    VISIBLE_TEXT = "visible_text"
    NATIVE_DATA = "native_data"
    EMBEDDED_DATA = "embedded_data"
    MEASURED = "measured"
    INFERRED = "inferred"
    UNKNOWABLE = "unknowable"


class MetricUnit(str, Enum):
    """Units supported by the initial benchmark metric contract."""

    BILLIONS_2025_USD = "2025_USD_billions"
    BYTES = "bytes"
    COUNT = "count"
    MEBIBYTES = "MiB"
    MILLISECONDS = "ms"
    PERCENT = "percent"
    RATIO = "ratio"


LITERAL_EXACT_PARITY_CLASSES = {
    TruthClass.VISIBLE_TEXT,
    TruthClass.NATIVE_DATA,
    TruthClass.EMBEDDED_DATA,
}


class FixtureManifest(ContractModel):
    """Immutable identity and custody state for one benchmark fixture."""

    schema_version: SchemaVersion
    fixture_id: NonEmptyString
    source_sha256: Sha256
    source_format: NonEmptyString
    custody: NonEmptyString


class Annotation(ContractModel):
    """A source-grounded claim, kept separate from parser output snapshots."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "include_in_exact_parity": {"const": True},
                        },
                        "required": ["include_in_exact_parity"],
                    },
                    "then": {
                        "properties": {
                            "truth_class": {
                                "enum": sorted(
                                    item.value for item in LITERAL_EXACT_PARITY_CLASSES
                                )
                            }
                        }
                    },
                }
            ]
        },
    )

    schema_version: SchemaVersion
    annotation_id: NonEmptyString
    fixture_id: NonEmptyString
    truth_class: TruthClass
    claim: NonEmptyString
    include_in_exact_parity: bool = False

    @model_validator(mode="after")
    def prevent_nonliteral_exact_parity(self) -> "Annotation":
        if (
            self.include_in_exact_parity
            and self.truth_class not in LITERAL_EXACT_PARITY_CLASSES
        ):
            raise ValueError(
                "measured, inferred, or unknowable annotations cannot enter exact parity"
            )
        return self


class MetricRecord(ContractModel):
    """One non-negative measurement with explicit unit and tolerance semantics."""

    schema_version: SchemaVersion
    metric_name: NonEmptyString
    measurement_method: NonEmptyString
    fixture_id: NonEmptyString | None = None
    annotation_id: NonEmptyString | None = None
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: MetricUnit
    tolerance: float = Field(ge=0, allow_inf_nan=False)
    evidence_class: TruthClass


class RunRecord(ContractModel):
    """Reproducibility record for a benchmark execution and its artifacts."""

    schema_version: SchemaVersion
    run_id: NonEmptyString
    parser_version: NonEmptyString
    model_versions: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    commands: tuple[NonEmptyString, ...] = Field(min_length=1)
    hardware: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    fixture_hashes: dict[NonEmptyString, Sha256] = Field(min_length=1)
    output_hashes: dict[NonEmptyString, Sha256] = Field(min_length=1)
    duration_ms: float = Field(ge=0, allow_inf_nan=False)
    metrics: tuple[MetricRecord, ...] = Field(min_length=1)


def canonical_json(record: ContractModel) -> str:
    """Serialize a validated contract deterministically for test/reporting use."""

    return json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def read_initial_run_record(payload: str | bytes | bytearray) -> RunRecord:
    """Backward-read the initial 1.0 run-record wire format without migration."""

    return RunRecord.model_validate_json(payload)


def json_schema(model: type[ContractModel]) -> dict[str, Any]:
    """Expose the machine-readable JSON schema for reporting tooling."""

    return model.model_json_schema()
