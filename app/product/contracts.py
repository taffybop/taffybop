"""PX1 v2 wire contracts. These models do not register routes or run jobs.

Only public resource snapshots belong here. Ownership, storage paths, provider
credentials/IDs and worker leases are server-side records, never upload inputs.
Raw provider JSON is a separate byte artifact, not a serialized model dump.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints,
    field_validator, model_validator,
)

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
SHA256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
Mode = Literal["fast", "cost_effective", "agentic"]
JobStatus = Literal[
    "queued", "submitting", "submission_unknown", "running", "succeeded",
    "failed", "cancel_requested", "cancelled",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Resource(Contract):
    schema_version: Literal["2.0"] = "2.0"


class Artifact(Contract):
    """Opaque reference; retrieval must check the resource's owner and retention."""

    id: UUID
    sha256: SHA256
    size_bytes: NonnegativeInt
    media_type: Literal["application/pdf", "image/png", "image/jpeg", "application/json"]


class ParseSettings(Contract):
    provider: Literal["llamaparse"] = "llamaparse"
    adapter_version: Literal["llamaparse-v2/1"] = "llamaparse-v2/1"
    mode: Mode
    requested_version: Annotated[str, StringConstraints(strict=True, pattern=r"^\d{4}-\d{2}-\d{2}$")]
    max_pages: Annotated[int, Field(strict=True, ge=1, le=10)] = 10

    @field_validator("requested_version")
    @classmethod
    def dated_version(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class ParseRequest(Contract):
    """Body of POST /v2/documents/{id}/parse; idempotency is a header."""

    mode: Mode


class Document(Resource):
    id: UUID
    display_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=180)]
    source: Artifact
    page_count: Annotated[int, Field(strict=True, ge=1, le=10)]
    created_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    state: Literal["active", "deleted", "expired"] = "active"
    deleted_at: AwareDatetime | None = None

    @field_validator("display_name")
    @classmethod
    def safe_display_name(cls, value: str) -> str:
        if value in {".", ".."} or any(char in '/\\"' or not char.isprintable() for char in value):
            raise ValueError("display_name must be a safe filename, without a path or controls")
        return value

    @model_validator(mode="after")
    def consistent_document(self) -> Self:
        if self.source.media_type == "application/json" or self.source.size_bytes == 0:
            raise ValueError("source must be a nonempty PDF, PNG or JPEG")
        if self.source.size_bytes > 10 * 1024 * 1024:
            raise ValueError("source exceeds the initial 10 MiB limit")
        if self.source.media_type != "application/pdf" and self.page_count != 1:
            raise ValueError("an image has one page")
        if (self.state == "deleted") != (self.deleted_at is not None):
            raise ValueError("only a deleted document has deleted_at")
        if self.state == "expired" and self.expires_at is None:
            raise ValueError("an expired document needs expires_at")
        for timestamp in (self.expires_at, self.deleted_at):
            if timestamp is not None and timestamp < self.created_at:
                raise ValueError("document timestamps precede creation")
        return self


class DocumentList(Resource):
    documents: tuple[Document, ...]
    next_cursor: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)] | None = None


class Usage(Contract):
    """Null means unknown; zero is an observed/estimated numeric zero only."""

    estimated_credits: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    estimate_price_version: Annotated[str, StringConstraints(strict=True, min_length=1)] | None = None
    actual_credits: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    reconciliation: Literal["pending", "observed", "unavailable"] = "pending"

    @model_validator(mode="after")
    def separate_estimate_and_actual(self) -> Self:
        if (self.estimated_credits is None) != (self.estimate_price_version is None):
            raise ValueError("an estimate requires its price version")
        if (self.reconciliation == "observed") != (self.actual_credits is not None):
            raise ValueError("actual credits require an observed provider usage value")
        return self


class PublicError(Contract):
    code: Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_]{0,79}$")]
    message: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]


class Job(Resource):
    id: UUID
    document_id: UUID
    stage: Literal["parse"] = "parse"
    status: JobStatus
    settings: ParseSettings
    attempt: PositiveInt = 1
    created_at: AwareDatetime
    updated_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    cancellation_requested_at: AwareDatetime | None = None
    cancellation_confirmed: bool = Field(default=False, strict=True)
    result_id: UUID | None = None
    # Terminal provider replies remain inspectable even when parsing failed or
    # was cancelled. A successful result references these same original bytes.
    raw_response: Artifact | None = None
    error: PublicError | None = None
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def consistent_job(self) -> Self:
        terminal = self.status in {"succeeded", "failed", "cancelled"}
        if terminal != (self.finished_at is not None):
            raise ValueError("only terminal jobs have finished_at")
        if (self.status == "succeeded") != (self.result_id is not None):
            raise ValueError("only succeeded jobs reference a persisted result")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("only failed jobs have a terminal error")
        if (self.status == "cancelled") != self.cancellation_confirmed:
            raise ValueError("cancelled requires confirmed cancellation")
        if self.status == "cancel_requested" and self.cancellation_requested_at is None:
            raise ValueError("cancellation needs its request timestamp")
        if self.raw_response is not None and (not terminal or self.raw_response.media_type != "application/json" or self.raw_response.size_bytes == 0):
            raise ValueError("raw_response must be a nonempty terminal provider JSON artifact")
        if self.status in {"submitting", "submission_unknown", "running", "succeeded"} and self.started_at is None:
            raise ValueError("a provider attempt needs started_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at precedes creation")
        for timestamp in (self.started_at, self.finished_at, self.cancellation_requested_at):
            if timestamp is not None and not self.created_at <= timestamp <= self.updated_at:
                raise ValueError("job timestamps must be between creation and update")
        if self.finished_at is not None and self.started_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        return self


class Page(Contract):
    page_number: PositiveInt
    content: Annotated[str, StringConstraints(strict=True)]


class PageSection(Contract):
    """Formats retain independent source order, including repeated page IDs."""

    state: Literal["available", "empty", "not_returned", "unsupported"]
    pages: tuple[Page, ...] = ()

    @model_validator(mode="after")
    def available_has_pages(self) -> Self:
        if (self.state == "available") != bool(self.pages):
            raise ValueError("only available sections contain pages")
        return self


class ParseResult(Resource):
    id: UUID
    document_id: UUID
    job_id: UUID
    created_at: AwareDatetime
    settings: ParseSettings
    # Set only when returned by the provider, never copied from requested_version.
    provider_version: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)] | None = None
    raw: Artifact
    markdown: PageSection
    text: PageSection
    warnings: tuple[str, ...] = ()
    usage: Usage = Field(default_factory=Usage)

    @model_validator(mode="after")
    def raw_is_json(self) -> Self:
        if self.raw.media_type != "application/json" or self.raw.size_bytes == 0:
            raise ValueError("raw must reference the nonempty original JSON bytes")
        return self


def contract_schema() -> dict:
    """Deterministic schema snapshot for consumers before routes are wired."""
    from pydantic.json_schema import models_json_schema

    models = (ParseRequest, Document, DocumentList, Job, ParseResult)
    _, schema = models_json_schema(
        [(model, "validation") for model in models],
        title="TaffyBop product API v2.0 (PX1 contracts; routes pending)",
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
