"""Immutable, finite admission allowances for explicitly simulated local runs.

These amounts are authored simulation bounds, not provider prices or permission
to spend money. Reservations are consumed forever, including failed/unknown
attempts. Expiry stops new admission without preventing known-ID recovery.
"""

from datetime import timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator
from psycopg.types.json import Jsonb

from app.product.contracts import Contract, ParseSettings
from app.product.database import Database


PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class AllowanceError(RuntimeError):
    def __init__(self):
        super().__init__("Local test allowance is unavailable or does not match the durable execution.")


class TestAllowance(Contract):
    __test__: ClassVar[bool] = False

    id: UUID
    provider: Literal["simulated"] = "simulated"
    job_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=100)]
    settings: ParseSettings
    max_jobs: Annotated[int, Field(strict=True, ge=1, le=100)]
    max_pages: Annotated[int, Field(strict=True, ge=1, le=1000)]
    credit_limit: PositiveDecimal
    usd_limit: PositiveDecimal
    credits_per_page: PositiveDecimal
    usd_per_credit: PositiveDecimal
    expires_at: AwareDatetime

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def unique_jobs(self) -> Self:
        if len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError("Test allowance job IDs must be unique")
        return self


def validated_allowance(allowance: TestAllowance) -> TestAllowance:
    """Reject model_construct()/copy bypasses at trusted persistence boundaries."""
    return TestAllowance.model_validate(allowance.model_dump(mode="json"))


def _manifest(allowance: TestAllowance):
    payload = allowance.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return payload, sha256(encoded).hexdigest()


def registered_allowance(conn, allowance: TestAllowance):
    payload, fingerprint = _manifest(allowance)
    row = conn.execute("SELECT * FROM product.test_allowances WHERE id=%s", (allowance.id,)).fetchone()
    if row is None or row["manifest_sha256"] != fingerprint or row["payload"] != payload:
        raise AllowanceError()
    return row


def register_allowance(database: Database, allowance: TestAllowance) -> None:
    """Explicit, idempotent registration; the same ID cannot reset any limits."""
    allowance = validated_allowance(allowance)
    payload, fingerprint = _manifest(allowance)
    with database.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(729041, 103)")
        conn.execute("""INSERT INTO product.test_allowances
            (id,manifest_sha256,payload,max_jobs,max_pages,credit_limit,usd_limit,
             credits_per_page,usd_per_credit,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            (allowance.id, fingerprint, Jsonb(payload), allowance.max_jobs, allowance.max_pages,
             allowance.credit_limit, allowance.usd_limit, allowance.credits_per_page,
             allowance.usd_per_credit, allowance.expires_at))
        registered_allowance(conn, allowance)


def allowance_summary(database: Database, allowance: TestAllowance) -> dict:
    allowance = validated_allowance(allowance)
    with database.connect() as conn:
        registered_allowance(conn, allowance)
        totals = conn.execute("""SELECT count(*) AS reserved_jobs,
            coalesce(sum(reserved_pages),0) AS reserved_pages,
            coalesce(sum(reserved_credits),0) AS reserved_credits,
            coalesce(sum(reserved_usd),0) AS reserved_usd
            FROM product.test_allowance_reservations WHERE allowance_id=%s""", (allowance.id,)).fetchone()
    return {"allowance_id": allowance.id, **totals}


def reserve_allowance(conn, allowance: TestAllowance, job) -> bool:
    """Called under the worker admission lock, in its intent/slot transaction."""
    registered = registered_allowance(conn, allowance)
    if job.id not in allowance.job_ids or job.settings != allowance.settings:
        return False
    # PostgreSQL numeric arithmetic is exact here; do not round a tiny bound
    # upward through Python's ambient Decimal arithmetic precision.
    available = conn.execute("""SELECT clock_timestamp() < %s AS unexpired,
        %s::numeric * %s::numeric AS credits,
        %s::numeric * %s::numeric * %s::numeric AS usd""",
        (registered["expires_at"], job.settings.max_pages, allowance.credits_per_page,
         job.settings.max_pages, allowance.credits_per_page, allowance.usd_per_credit)).fetchone()
    fits = conn.execute("""SELECT count(*) < %s
        AND coalesce(sum(reserved_pages),0) + %s <= %s
        AND coalesce(sum(reserved_credits),0) + %s::numeric <= %s::numeric
        AND coalesce(sum(reserved_usd),0) + %s::numeric <= %s::numeric AS fits
        FROM product.test_allowance_reservations WHERE allowance_id=%s""",
        (allowance.max_jobs, job.settings.max_pages, allowance.max_pages,
         available["credits"], allowance.credit_limit, available["usd"], allowance.usd_limit,
         allowance.id)).fetchone()["fits"]
    if not available["unexpired"] or not fits:
        return False
    conn.execute("""INSERT INTO product.test_allowance_reservations
        (job_id,allowance_id,reserved_pages,reserved_credits,reserved_usd)
        VALUES (%s,%s,%s,%s,%s)""",
        (job.id, allowance.id, job.settings.max_pages, available["credits"], available["usd"]))
    return True
