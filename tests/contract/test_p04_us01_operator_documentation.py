"""Operator-contract checks for the default-off P04-US01 preview."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, get_settings


WORKSPACE = Path(__file__).resolve().parents[2]
README_PATH = WORKSPACE / "README.md"
ENV_EXAMPLE_PATH = WORKSPACE / ".env.example"
TABLE_ENVIRONMENT_LINES = (
    "PARSER_TABLES_SPAN_FIDELITY_ENABLED=false",
    "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED=false",
    "PARSER_TABLES_CANDIDATE_GATE_ENABLED=false",
    "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED=false",
)


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


def test_operator_docs_match_exact_default_off_configuration() -> None:
    settings = Settings()
    assert settings.table_span_fidelity_enabled is False
    assert settings.table_evidence_reconciliation_enabled is False
    assert settings.table_candidate_gate_enabled is False
    assert settings.table_multi_page_merge_enabled is False

    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    table_block = "\n".join(TABLE_ENVIRONMENT_LINES) + "\n"
    assert table_block in env_example
    assert env_example.count(table_block) == 1

    readme = _readme()
    assert "PARSER_TABLES_SPAN_FIDELITY_ENABLED=false" in readme
    assert "local-only, default-off preview" in readme
    assert "production enablement\nstill requires separate approval" in readme


def test_operator_docs_and_config_require_exact_us01_predecessors() -> None:
    with pytest.raises(ValueError, match="requires PARSER_SHARED_IR_ENABLED"):
        Settings(table_span_fidelity_enabled=True)

    enabled = Settings(
        shared_ir_enabled=True,
        shared_ir_normalization_enabled=True,
        canonical_serialization_enabled=True,
        table_span_fidelity_enabled=True,
    )
    assert enabled.table_span_fidelity_enabled is True
    assert enabled.table_evidence_reconciliation_enabled is False
    assert enabled.table_candidate_gate_enabled is False
    assert enabled.table_multi_page_merge_enabled is False

    readme = _readme()
    for flag in (
        "PARSER_SHARED_IR_ENABLED=true",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED=true",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED=true",
        "PARSER_TABLES_SPAN_FIDELITY_ENABLED=true",
    ):
        assert flag in readme
    assert "eligible already-selected Docling table" in readme
    assert "successfully admitted overlay adds" in readme
    assert "does not reconcile table engines" in readme
    assert "charts/forms/aligned prose" in readme
    assert "or merge tables across pages" in readme


def test_operator_docs_define_valid_only_authority_and_complete_rollback() -> None:
    readme = _readme()
    normalized = " ".join(readme.split())
    required = (
        "table_evidence.status` is exactly `valid`",
        "the exact predecessor table remains authoritative",
        "inclusive `0.500 pt` edge-rounding tolerance",
        "establishes table ownership only",
        "every affected table candidate is quarantined",
        "operation raises instead of returning a mutated projection",
        "set `PARSER_TABLES_SPAN_FIDELITY_ENABLED=false`",
        "restart every application worker",
        "cached settings are rebuilt",
        "With all four table flags off",
        "without a Phase 04 table sidecar",
        "does not add hosted inference or a network path",
    )
    for fragment in required:
        assert fragment in normalized

    for later_flag in TABLE_ENVIRONMENT_LINES[1:]:
        assert later_flag.removesuffix("=false") in readme

    assert get_settings.cache_info().maxsize == 1
