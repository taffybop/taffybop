"""Strict, source-qualified table-readiness fixtures for Phase 04."""

from tests.fixtures.phase_04.tables.contract import (
    CONCERN_CODES,
    POLICY_ID,
    SIDECAR_VERSION,
    TABLE_LIMITS,
    CellTruth,
    ExactTableTruth,
    FailClosedConcern,
    FiniteBBox,
    P04Us01Oracle,
    QualifiedTableDenominator,
    ReviewedDenominator,
    ReviewedRowTruth,
    SourceIdentity,
    validate_oracle,
)

__all__ = (
    "CONCERN_CODES",
    "POLICY_ID",
    "SIDECAR_VERSION",
    "TABLE_LIMITS",
    "CellTruth",
    "ExactTableTruth",
    "FailClosedConcern",
    "FiniteBBox",
    "P04Us01Oracle",
    "QualifiedTableDenominator",
    "ReviewedDenominator",
    "ReviewedRowTruth",
    "SourceIdentity",
    "validate_oracle",
)
