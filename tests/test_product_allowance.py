"""Finite simulated-worker admission against real, isolated PostgreSQL databases.

The charges below are authored simulation units, never provider prices or usage.
No provider connection or credential is consulted by these checks.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
from uuid import uuid4

import pytest
from pydantic import ValidationError

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.product.allowance import (
    AllowanceError, TestAllowance as Allowance, allowance_summary, register_allowance,
)
from app.product.contracts import PageSection, ParseSettings, Usage
from app.product.database import Database
from app.product.lifecycle import WorkerRepository
from app.product.provider import ProviderObservation
from app.product.repository import ProductRepository
from app.product.storage import LocalArtifactStore


SOURCE = Path(__file__).parent / "fixtures/parse_extract_v1/dev-invoice-104.pdf"
SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28", max_pages=10)


def allowance_values(*jobs, **changes):
    values = dict(
        id=uuid4(), provider="simulated", job_ids=tuple(job.id for job in jobs) or (uuid4(),),
        settings=SETTINGS, max_jobs=2, max_pages=20, credit_limit=Decimal("60"),
        usd_limit=Decimal("0.09"), credits_per_page=Decimal("3"),
        usd_per_credit=Decimal("0.0015"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return {**values, **changes}


@pytest.fixture
def runtime(tmp_path):
    administrative_dsn = os.environ.get("TAFFYBOP_TEST_DATABASE_URL")
    if not administrative_dsn:
        pytest.skip("real PostgreSQL: TAFFYBOP_TEST_DATABASE_URL is not configured")
    name = "px1_allowance_test_" + uuid4().hex
    with psycopg.connect(administrative_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        database = Database(make_conninfo(administrative_dsn, dbname=name))
        database.migrate()
        repo = ProductRepository(database, LocalArtifactStore((tmp_path / "artifacts").resolve()))
        yield SimpleNamespace(database=database, repo=repo, owner="allowance-" + uuid4().hex)
    finally:
        with psycopg.connect(administrative_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def enqueue(runtime, *, settings=SETTINGS):
    document = runtime.repo.create_document(runtime.owner, display_name="authored-test.pdf",
        media_type="application/pdf", data=SOURCE.read_bytes(), page_count=1)
    return runtime.repo.enqueue_parse(runtime.owner, document.id, settings=settings,
        idempotency_key=uuid4().hex, usage=Usage(estimated_credits=Decimal("1"),
            estimate_price_version="authored-estimate-not-a-bound"))


def governed(runtime, *jobs, **changes):
    allowance = Allowance(**allowance_values(*jobs, **changes))
    register_allowance(runtime.database, allowance)
    return allowance, WorkerRepository(runtime.repo, allowance=allowance)


def finish(worker, claim, *, actual_credits=None):
    identity = "sim-" + claim.job.id.hex
    worker.accepted(claim, identity)
    poll = worker.claim()
    assert poll.provider_job_id == identity
    raw = (json.dumps({"job": {"id": identity, "status": "COMPLETED"},
        "evidence": "authored simulation; no real provider call"}) + "\n").encode()
    usage = Usage() if actual_credits is None else Usage(actual_credits=actual_credits, reconciliation="observed")
    return worker.complete(poll, ProviderObservation(status="COMPLETED", raw=raw,
        markdown=PageSection(state="not_returned"), text=PageSection(state="not_returned"), usage=usage))


def totals(runtime, allowance):
    value = allowance_summary(runtime.database, allowance)
    return tuple(value[key] for key in ("reserved_jobs", "reserved_pages", "reserved_credits", "reserved_usd"))


@pytest.mark.parametrize("change", [
    {"provider": "live"}, {"max_jobs": True}, {"max_jobs": 0}, {"max_jobs": 101},
    {"max_pages": 0}, {"max_pages": 1001}, {"credit_limit": "NaN"},
    {"credit_limit": "Infinity"}, {"credit_limit": "0"}, {"usd_limit": "-0.1"},
    {"credits_per_page": "0"}, {"usd_per_credit": "NaN"},
    {"job_ids": ()}, {"expires_at": datetime(2026, 11, 11)}, {"unexpected": "reject"},
])
def test_allowance_rejects_nonfinite_unbounded_and_unsupported_configuration(change):
    with pytest.raises(ValidationError):
        Allowance(**allowance_values(**change))


def test_allowance_rejects_duplicate_job_ids():
    identity = uuid4()
    with pytest.raises(ValidationError):
        Allowance(**allowance_values(job_ids=(identity, identity)))


def test_registration_is_idempotent_but_cannot_replenish_existing_identity(runtime):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job)
    worker.claim()
    register_allowance(runtime.database, Allowance.model_validate_json(allowance.model_dump_json()))
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))
    increased = Allowance(**{**allowance.model_dump(), "max_jobs": 3})
    with pytest.raises(AllowanceError):
        register_allowance(runtime.database, increased)
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


@pytest.mark.parametrize("limits", [
    {"max_jobs": 1}, {"max_pages": 10}, {"credit_limit": Decimal("30")},
    {"usd_limit": Decimal("0.045")},
])
def test_each_exact_cap_prevents_next_attempt_without_refunding_terminal_usage(runtime, limits):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting, **limits)
    claim = worker.claim()
    assert claim.job.id == first.id
    completed = finish(worker, claim, actual_credits=Decimal("0"))
    assert completed.status == "succeeded" and completed.usage.actual_credits == 0
    assert WorkerRepository(runtime.repo, allowance=allowance).claim() is None
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


@pytest.mark.parametrize("limits", [
    {"max_pages": 9}, {"credit_limit": Decimal("29.9999")},
    {"usd_limit": Decimal("0.0449999")},
])
def test_insufficient_first_reservation_keeps_job_queued_and_creates_no_intent(runtime, limits):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job, **limits)
    assert worker.claim() is None
    assert runtime.repo.get_job(runtime.owner, job.id).status == "queued"
    assert totals(runtime, allowance) == (0, 0, Decimal("0"), Decimal("0"))
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.worker_executions").fetchone()["n"] == 0


def test_simultaneous_claims_consume_final_unit_once_and_survive_fresh_repository(runtime):
    jobs = [enqueue(runtime), enqueue(runtime)]
    allowance, _ = governed(runtime, *jobs, max_jobs=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: WorkerRepository(runtime.repo, allowance=allowance).claim(), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    admitted = next(claim for claim in claims if claim is not None)
    finish(WorkerRepository(runtime.repo, allowance=allowance), admitted)
    assert WorkerRepository(runtime.repo, allowance=allowance).claim() is None
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_allowlist_and_exact_settings_skip_older_unqualified_backlog(runtime):
    outside = enqueue(runtime)
    mismatch = enqueue(runtime, settings=ParseSettings(mode="fast", requested_version="2026-06-15"))
    wanted = enqueue(runtime)
    allowance, worker = governed(runtime, mismatch, wanted)
    claim = worker.claim()
    assert claim.job.id == wanted.id
    assert runtime.repo.get_job(runtime.owner, outside.id).status == "queued"
    assert runtime.repo.get_job(runtime.owner, mismatch.id).status == "queued"
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_expired_allowance_refuses_new_submission(runtime):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert worker.claim() is None
    assert runtime.repo.get_job(runtime.owner, job.id).status == "queued"
    assert totals(runtime, allowance) == (0, 0, Decimal("0"), Decimal("0"))


def test_expiry_after_acceptance_does_not_strand_known_id(runtime):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=0.5))
    claim = worker.claim()
    worker.accepted(claim, "sim-expiry-id")
    # Let the real database clock pass the immutable deadline, then recover from
    # the same serialized manifest as a restarted process would.
    time.sleep(max(0.01, (allowance.expires_at-datetime.now(timezone.utc)).total_seconds()+0.02))
    restored = Allowance.model_validate_json(allowance.model_dump_json())
    fresh = WorkerRepository(runtime.repo, allowance=restored)
    poll = fresh.claim()
    assert poll.provider_job_id == "sim-expiry-id"
    raw = b'{"job":{"id":"sim-expiry-id","status":"COMPLETED"},"simulation":true}'
    fresh.complete(poll, ProviderObservation(status="COMPLETED", raw=raw,
        markdown=PageSection(state="not_returned"), text=PageSection(state="not_returned")))
    assert fresh.claim() is None
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_crash_before_send_consumes_allowance_and_retains_unknown_slot(runtime):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting)
    worker.claim()
    with runtime.database.connect() as conn:
        conn.execute("UPDATE product.worker_executions SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s", (first.id,))
    assert WorkerRepository(runtime.repo, allowance=allowance).claim() is None
    assert runtime.repo.get_job(runtime.owner, first.id).status == "submission_unknown"
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_rejection_keeps_reservation_consumed_even_without_pause(runtime):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting, max_jobs=1)
    worker.reject(worker.claim(), pause=False)
    assert worker.claim() is None
    assert runtime.repo.get_job(runtime.owner, first.id).status == "failed"
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_missing_terminal_usage_keeps_reservation_consumed(runtime):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting, max_jobs=1)
    completed = finish(worker, worker.claim())
    assert completed.usage.actual_credits is None and completed.usage.reconciliation == "pending"
    assert worker.claim() is None
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


def test_foreign_allowance_cannot_poll_or_complete_governed_active_execution(runtime):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job)
    claim = worker.claim()
    worker.accepted(claim, "sim-owned-id")
    _, foreign = governed(runtime, job)
    with pytest.raises(AllowanceError):
        foreign.claim()
    with pytest.raises(AllowanceError):
        WorkerRepository(runtime.repo).claim()
    assert worker.claim().provider_job_id == "sim-owned-id"
    assert totals(runtime, allowance)[0] == 1


def test_simulator_refuses_to_recover_unbudgeted_accepted_execution(runtime):
    job = enqueue(runtime)
    private = WorkerRepository(runtime.repo)
    private.accepted(private.claim(), "possible-real-id")
    _, simulator = governed(runtime, job)
    with pytest.raises(AllowanceError):
        simulator.claim()
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT provider_job_id FROM product.worker_executions WHERE job_id=%s", (job.id,)).fetchone()["provider_job_id"] == "possible-real-id"


def test_reservation_rolls_back_with_failed_submission_intent(runtime, monkeypatch):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job)

    def fail(*_args):
        raise RuntimeError("authored transaction failure")

    monkeypatch.setattr(worker, "_update_job", fail)
    with pytest.raises(RuntimeError, match="authored transaction failure"):
        worker.claim()
    assert totals(runtime, allowance) == (0, 0, Decimal("0"), Decimal("0"))
    assert runtime.repo.get_job(runtime.owner, job.id).status == "queued"
    assert WorkerRepository(runtime.repo, allowance=allowance).claim().job.id == job.id


@pytest.mark.parametrize("limits", [
    {"max_jobs": 1}, {"max_pages": 10}, {"credit_limit": Decimal("30")},
    {"usd_limit": Decimal("0.045")},
])
def test_database_insert_cannot_bypass_any_total_cap(runtime, limits):
    first, waiting = enqueue(runtime), enqueue(runtime)
    allowance, worker = governed(runtime, first, waiting, **limits)
    finish(worker, worker.claim())
    # A valid-looking append that bypasses the Python availability check still
    # fails the SQL trigger before the deferred execution FK is considered.
    with pytest.raises(psycopg.errors.CheckViolation, match="finite test allowance exhausted"):
        with runtime.database.connect() as conn:
            conn.execute("""INSERT INTO product.test_allowance_reservations
                (job_id,allowance_id,reserved_pages,reserved_credits,reserved_usd)
                VALUES (%s,%s,10,30,0.045)""", (waiting.id, allowance.id))
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))


@pytest.mark.parametrize("bound, fits", [
    ("1.234567890123456789012345678901234567890", True),
    ("1.234567890123456789012345678901234567889", False),
])
def test_numeric_boundary_preserves_digits_beyond_python_decimal_context(runtime, bound, fits):
    job = enqueue(runtime)
    exact = Decimal("1.234567890123456789012345678901234567890")
    allowance, worker = governed(runtime, job,
        credits_per_page=Decimal("0.123456789012345678901234567890123456789"),
        usd_per_credit=Decimal("1"), credit_limit=Decimal(bound), usd_limit=exact)
    claim = worker.claim()
    assert (claim is not None) is fits
    assert totals(runtime, allowance) == ((1, 10, exact, exact) if fits else (0, 0, Decimal("0"), Decimal("0")))


@pytest.mark.parametrize("statement", [
    "UPDATE product.test_allowances SET max_jobs=max_jobs+1",
    "DELETE FROM product.test_allowances",
    "UPDATE product.test_allowance_reservations SET reserved_credits=0",
    "DELETE FROM product.test_allowance_reservations",
])
def test_database_rejects_allowance_or_reservation_replenishment(runtime, statement):
    job = enqueue(runtime)
    allowance, worker = governed(runtime, job)
    worker.claim()
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.database.connect() as conn:
            conn.execute(statement)
    assert totals(runtime, allowance) == (1, 10, Decimal("30"), Decimal("0.045"))
