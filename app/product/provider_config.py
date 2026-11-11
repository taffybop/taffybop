"""Secret-free, dated LlamaParse configuration for the future product worker.

This does not change the compatibility client or enable a product submitter.
Published prices are versioned estimates, never account balances or actual use.
"""

from collections.abc import Mapping
from decimal import Decimal
import os

from pydantic import Field

from app.product.contracts import Contract, Mode, ParseSettings

PRICE_VERSION = "llamaparse-public-base-credits-2026-11-11"
PUBLISHED_MODES: tuple[tuple[Mode, str, Decimal], ...] = (
    ("fast", "2026-06-15", Decimal("1")),
    ("cost_effective", "2026-09-28", Decimal("3")),
    ("agentic", "2026-09-29", Decimal("10")),
)


class ProviderConfiguration(Contract):
    default_settings: ParseSettings
    # Keep the initial worker conservative. Shared coordination is PX1-03/PX2.
    max_active_jobs: int = Field(default=1, strict=True, ge=1, le=1)
    live_qualified: bool = Field(default=False, strict=True)


def load_provider_configuration(environ: Mapping[str, str] | None = None) -> ProviderConfiguration:
    """Read only allowlisted settings; never load a key into a public model."""
    values = os.environ if environ is None else environ
    mode = values.get("TAFFYBOP_PARSE_MODE", "cost_effective")
    versions = {tier: version for tier, version, _ in PUBLISHED_MODES}
    if mode not in versions:
        raise ValueError("TAFFYBOP_PARSE_MODE must be fast, cost_effective or agentic")
    version = values.get("TAFFYBOP_LLAMA_PARSE_VERSION", versions[mode])
    return ProviderConfiguration(default_settings=ParseSettings(mode=mode, requested_version=version))


def estimate_base_credits(settings: ParseSettings, page_count: int) -> Decimal:
    """Base estimate only; options, retries and account terms can add charges."""
    if isinstance(page_count, bool) or not isinstance(page_count, int) or not 1 <= page_count <= settings.max_pages:
        raise ValueError("page_count must be an integer within the configured page limit")
    for mode, version, credits in PUBLISHED_MODES:
        if mode == settings.mode and version == settings.requested_version:
            return credits * page_count
    raise ValueError("no reviewed price snapshot for this mode/version")
