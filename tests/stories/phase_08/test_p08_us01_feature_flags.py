"""P08-US01 centralized shipping flags and deterministic rollback."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.api as api_module
from app.config import Settings
from app.services.feature_flags import (
    FeatureFlagConfigurationError,
    shipping_flag_registry,
)


VALID_PDF = b"%PDF-1.7\n% release-first flag fixture\n"


def _table_chain(**updates: object) -> Settings:
    values: dict[str, object] = {
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "table_span_fidelity_enabled": True,
        "table_evidence_reconciliation_enabled": True,
        "table_candidate_gate_enabled": True,
        "table_multi_page_merge_enabled": True,
    }
    values.update(updates)
    return Settings(**values)


def test_registry_owns_safe_defaults_dependencies_and_rollback_metadata() -> None:
    settings = Settings()
    registry = shipping_flag_registry()

    registry.validate(settings)
    assert len(registry.flags) == 53
    assert {flag.setting for flag in registry.flags} >= {
        "shared_ir_enabled",
        "table_multi_page_merge_enabled",
        "visual_models_merge_enabled",
        "adapters_future_conformance_gate_enabled",
        "telemetry_enabled",
        "review_escalation_enabled",
    }
    assert all(getattr(settings, flag.setting) is flag.default for flag in registry.flags)
    assert all(flag.owner and flag.dependencies is not None for flag in registry.flags)
    assert all(flag.rollback.startswith("set PARSER_") for flag in registry.flags)


def test_existing_environment_names_load_one_valid_dependency_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_TABLES_SPAN_FIDELITY_ENABLED",
        "PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED",
        "PARSER_TABLES_CANDIDATE_GATE_ENABLED",
        "PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")

    settings = Settings.from_env()

    assert settings.table_multi_page_merge_enabled is True
    shipping_flag_registry().validate(settings)


def test_invalid_enabled_dependency_fails_with_actionable_environment_name() -> None:
    with pytest.raises(ValueError, match="PARSER_TABLES_SPAN_FIDELITY_ENABLED"):
        Settings(table_span_fidelity_enabled=True)


def test_global_kill_switch_cascades_to_local_core_without_changing_core_default() -> None:
    # Emergency rollback takes precedence even over a stale child-only value.
    configured = Settings(
        table_multi_page_merge_enabled=True,
        parser_shipping_kill_switch=True,
    )

    effective = shipping_flag_registry().resolve(configured)

    assert effective.pdf_visual_analysis_enabled is True
    assert all(getattr(effective, flag.setting) is False for flag in shipping_flag_registry().flags)
    assert effective.parser_shipping_kill_switch is True


def test_capability_rollback_disables_dependants_and_keeps_unrelated_flags() -> None:
    configured = _table_chain()

    effective = shipping_flag_registry().rollback(configured, "tables")

    assert effective.shared_ir_enabled is True
    assert effective.canonical_serialization_enabled is True
    assert effective.table_span_fidelity_enabled is False
    assert effective.table_evidence_reconciliation_enabled is False
    assert effective.table_candidate_gate_enabled is False
    assert effective.table_multi_page_merge_enabled is False


def test_unknown_capability_fails_closed_before_effective_configuration() -> None:
    with pytest.raises(
        FeatureFlagConfigurationError,
        match="PARSER_SHIPPING_DISABLED_CAPABILITIES",
    ):
        Settings(parser_shipping_disabled_capabilities=("unknown",))


def test_effective_configuration_is_bounded_and_contains_no_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canary = "release-first-secret-canary"
    monkeypatch.setenv("PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SOURCE", canary)
    settings = Settings.from_env()

    encoded = json.dumps(
        shipping_flag_registry().effective_configuration(settings),
        sort_keys=True,
    )

    assert canary not in encoded
    assert len(encoded.encode("utf-8")) < 32_000
    assert "PARSER_VISUAL_MODELS_LOCAL_ARTIFACT_SOURCE" not in encoded


def test_default_registry_is_inert_for_representative_public_json_flow(
    client: TestClient,
    parsed_document: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Settings] = []

    def parse(_data: bytes, _filename: str, settings: Settings) -> object:
        calls.append(settings)
        return parsed_document

    monkeypatch.setattr(api_module, "_parse_document", parse)

    response = client.post(
        "/v1/parse?output_format=json",
        files={"file": ("sample.pdf", VALID_PDF, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json() == parsed_document
    assert len(calls) == 1
    assert all(
        getattr(calls[0], flag.setting) is False
        for flag in shipping_flag_registry().flags
    )


def test_global_kill_ignores_malformed_stale_enabled_auxiliary_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_SHIPPING_KILL_SWITCH", "true")
    monkeypatch.setenv("PARSER_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("PARSER_TELEMETRY_QUEUE_SIZE", "not-an-integer")

    settings = Settings.from_env()

    assert settings.telemetry_enabled is False
    assert settings.telemetry_queue_size == 128


def test_disabled_dependency_cascade_ignores_child_auxiliary_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PARSER_SHIPPING_DISABLED_CAPABILITIES", "ir")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_ENABLED", "true")
    monkeypatch.setenv(
        "PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS",
        "not-an-integer",
    )

    settings = Settings.from_env()

    assert settings.visual_models_merge_enabled is False
    assert settings.visual_models_merge_max_observations == 32
