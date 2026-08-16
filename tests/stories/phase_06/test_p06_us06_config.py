"""P06-US06 release-first configuration and rollback-boundary checks."""

from __future__ import annotations

import pytest

from app.config import MEBIBYTE, Settings


_MERGE_ENV_NAMES = (
    "PARSER_VISUAL_MODELS_MERGE_ENABLED",
    "PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS",
    "PARSER_VISUAL_MODELS_MERGE_MAX_ADDED_BYTES",
)


def _clear_merge_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _MERGE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _enabled_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "visual_structure_schema_enabled": True,
        "visual_models_contract_enabled": True,
        "visual_models_routing_enabled": True,
        "visual_models_grounding_enabled": True,
        "shared_ir_enabled": True,
        "shared_ir_normalization_enabled": True,
        "canonical_serialization_enabled": True,
        "visual_models_merge_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_merge_defaults_off_with_bounded_release_defaults() -> None:
    settings = Settings()

    assert settings.visual_models_merge_enabled is False
    assert settings.visual_models_merge_max_observations == 32
    assert settings.visual_models_merge_max_added_bytes == 262_144


@pytest.mark.parametrize(
    "dependency",
    (
        "visual_models_contract_enabled",
        "visual_models_routing_enabled",
        "visual_models_grounding_enabled",
        "shared_ir_enabled",
        "shared_ir_normalization_enabled",
        "canonical_serialization_enabled",
    ),
)
def test_enabled_merge_requires_every_predecessor(dependency: str) -> None:
    with pytest.raises(ValueError):
        _enabled_settings(**{dependency: False})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("visual_models_merge_max_observations", 0),
        ("visual_models_merge_max_observations", 257),
        ("visual_models_merge_max_observations", True),
        ("visual_models_merge_max_added_bytes", 0),
        ("visual_models_merge_max_added_bytes", MEBIBYTE + 1),
        ("visual_models_merge_max_added_bytes", True),
    ),
)
def test_enabled_merge_rejects_invalid_resource_bounds(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        _enabled_settings(**{field: value})


def test_disabled_merge_lazily_ignores_malformed_auxiliary_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_merge_env(monkeypatch)
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_ENABLED", "false")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS", "broken")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_MAX_ADDED_BYTES", "also-broken")

    settings = Settings.from_env()

    assert settings.visual_models_merge_enabled is False
    assert settings.visual_models_merge_max_observations == 32
    assert settings.visual_models_merge_max_added_bytes == 262_144


def test_enabled_merge_reads_explicit_resource_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_merge_env(monkeypatch)
    for name in (
        "PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED",
        "PARSER_VISUAL_MODELS_CONTRACT_ENABLED",
        "PARSER_VISUAL_MODELS_ROUTING_ENABLED",
        "PARSER_VISUAL_MODELS_GROUNDING_ENABLED",
        "PARSER_SHARED_IR_ENABLED",
        "PARSER_SHARED_IR_NORMALIZATION_ENABLED",
        "PARSER_CANONICAL_SERIALIZATION_ENABLED",
        "PARSER_VISUAL_MODELS_MERGE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS", "7")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_MAX_ADDED_BYTES", "4096")

    settings = Settings.from_env()

    assert settings.visual_models_merge_enabled is True
    assert settings.visual_models_merge_max_observations == 7
    assert settings.visual_models_merge_max_added_bytes == 4_096


def test_enabled_merge_rejects_malformed_auxiliary_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_merge_env(monkeypatch)
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_ENABLED", "true")
    monkeypatch.setenv("PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS", "broken")

    with pytest.raises(
        ValueError,
        match="PARSER_VISUAL_MODELS_MERGE_MAX_OBSERVATIONS must be an integer",
    ):
        Settings.from_env()
