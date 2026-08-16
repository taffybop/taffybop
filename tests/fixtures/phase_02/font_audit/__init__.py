"""Synthetic PDF fixtures for Phase 2 font-audit tests."""

from .builder import (
    FixtureIntegrityError,
    build_all_fixtures,
    build_fixture,
    fixture_hashes,
    self_check,
)
from .registry import FIXTURES, FIXTURES_BY_ID, FontAuditFixture

__all__ = [
    "FIXTURES",
    "FIXTURES_BY_ID",
    "FixtureIntegrityError",
    "FontAuditFixture",
    "build_all_fixtures",
    "build_fixture",
    "fixture_hashes",
    "self_check",
]

