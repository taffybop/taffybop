"""Explicit executable test double. Never reads credentials or uses HTTP.

It does not parse source content. Its labelled, authored output only exercises
worker admission, persistence and recovery; it is not provider qualification.
"""

import json
import re
from uuid import uuid4

from app.product.contracts import Page, PageSection
from app.product.provider import ProviderError, ProviderObservation, ProviderSubmission


SIMULATION_OUTCOMES = (
    "completed", "submission_unknown", "submission_rejected", "running", "poll_unavailable",
)
SIMULATED_CONTENT = "Simulated worker output; no document parsing or live provider call occurred.\n"


class SimulatedParseProvider:
    def __init__(self, outcome: str = "completed"):
        if outcome not in SIMULATION_OUTCOMES:
            raise ValueError("Invalid simulated outcome")
        self.outcome = outcome
        self.submissions = 0
        self.polls = 0

    async def submit(self, data, filename, media_type, settings):
        self.submissions += 1
        if self.outcome == "submission_unknown":
            raise ProviderError("simulated_unknown", "Simulated acceptance uncertainty.", ambiguous=True)
        if self.outcome == "submission_rejected":
            raise ProviderError("simulated_rejection", "Simulated submission rejection.")
        return ProviderSubmission("simulated-" + uuid4().hex, "PENDING")

    async def poll(self, provider_job_id):
        if re.fullmatch(r"simulated-[a-f0-9]{32}", provider_job_id) is None:
            raise ValueError("Only simulated provider identities are permitted")
        self.polls += 1
        if self.outcome == "poll_unavailable":
            raise ProviderError("simulated_poll_unavailable", "Simulated polling failure.")
        status = "RUNNING" if self.outcome == "running" else "COMPLETED"
        raw = (json.dumps({"simulation": True, "job": {"id": provider_job_id, "status": status},
            "markdown": {"pages": [{"page_number": 1, "markdown": SIMULATED_CONTENT}]}}, indent=2) + "\n").encode()
        return ProviderObservation(status, raw,
            markdown=PageSection(state="available", pages=(Page(page_number=1, content=SIMULATED_CONTENT),)),
            text=PageSection(state="not_returned"),
            warnings=("Authored simulation; no live provider call or accuracy evidence.",))
