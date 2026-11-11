"""Secret-free configuration and reviewed estimates, not live qualification."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.product.contracts import ParseSettings
from app.product.provider_config import (
    PRICE_VERSION, estimate_base_credits, load_provider_configuration,
)


@pytest.mark.parametrize("mode,version,credits", [
    ("fast", "2026-06-15", "2"),
    ("cost_effective", "2026-09-28", "6"),
    ("agentic", "2026-09-29", "20"),
])
def test_config_pins_explicit_tiers_without_live_calls(mode, version, credits):
    config = load_provider_configuration({"TAFFYBOP_PARSE_MODE": mode})
    assert config.default_settings.requested_version == version
    assert estimate_base_credits(config.default_settings, 2) == Decimal(credits)
    assert config.max_active_jobs == 1
    assert config.live_qualified is False
    assert PRICE_VERSION == "llamaparse-public-base-credits-2026-11-11"


def test_keys_and_unrelated_environment_never_enter_configuration():
    key_marker = "private-placeholder-not-a-real-credential"
    config = load_provider_configuration({"LLAMA_CLOUD_API_KEY": key_marker,
        "TAFFYBOP_PROVIDER_MAX_ACTIVE": "20", "TAFFYBOP_LIVE_QUALIFIED": "true"})
    assert key_marker not in config.model_dump_json()
    assert config == load_provider_configuration({})


@pytest.mark.parametrize("values", [
    {"TAFFYBOP_PARSE_MODE": "agentic_plus"},
    {"TAFFYBOP_PARSE_MODE": ""},
    {"TAFFYBOP_LLAMA_PARSE_VERSION": "latest"},
    {"TAFFYBOP_LLAMA_PARSE_VERSION": "2026-02-30"},
])
def test_bad_configuration_fails_without_fallback(values):
    with pytest.raises(ValueError):
        load_provider_configuration(values)


def test_custom_pin_is_saved_but_unreviewed_pricing_fails_closed():
    config = load_provider_configuration({"TAFFYBOP_LLAMA_PARSE_VERSION": "2026-01-01"})
    assert config.default_settings.requested_version == "2026-01-01"
    with pytest.raises(ValueError, match="no reviewed price"):
        estimate_base_credits(config.default_settings, 1)


@pytest.mark.parametrize("pages", [True, 0, -1, 11, 1.5, "1"])
def test_estimation_validates_pages(pages):
    with pytest.raises(ValueError):
        estimate_base_credits(load_provider_configuration({}).default_settings, pages)


def test_configuration_cannot_claim_expanded_capacity():
    config = load_provider_configuration({})
    with pytest.raises(ValidationError):
        type(config)(default_settings=config.default_settings, max_active_jobs=2)
    with pytest.raises(ValidationError):
        ParseSettings(mode="fast", requested_version="2026-06-15", max_pages=True)
