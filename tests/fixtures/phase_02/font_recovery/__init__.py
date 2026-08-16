"""Deterministic, generated-only fixtures for Phase 2 font recovery."""

from .builder import (
    FIXTURE_IDS,
    EXPECTED_RECOVERED_TEXT,
    FixtureIntegrityError,
    build_all_fixtures,
    build_fixture,
    build_synthetic_truetype,
    fixture_hashes,
    self_check,
)

__all__ = [
    "EXPECTED_RECOVERED_TEXT",
    "FIXTURE_IDS",
    "FixtureIntegrityError",
    "build_all_fixtures",
    "build_fixture",
    "build_synthetic_truetype",
    "fixture_hashes",
    "self_check",
]
