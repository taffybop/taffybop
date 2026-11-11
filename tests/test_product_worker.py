"""Real PostgreSQL worker lifecycle checks with authored provider observations.

Each test creates and drops its own uniquely named database. No pre-existing
queued fixtures are consumed, and no provider connection or key is used.
"""

from concurrent.futures import ThreadPoolExecutor
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import time
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.product.contracts import Page, PageSection, ParseSettings, Usage
from app.product.database import Database
from app.product.lifecycle import StaleClaim, WorkerRepository
from app.product.provider import ProviderError, ProviderObservation, ProviderSubmission
from app.product.repository import PersistenceConflict, ProductRepository, ResourceNotFound
from app.product.runtime_profile import LocalProviderLock, RuntimeProfileError
from app.product.storage import LocalArtifactStore
from app.product.worker import Worker


SOURCE = Path(__file__).parent / "fixtures/parse_extract_v1/dev-invoice-104.pdf"
SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28")
RAW = b'{  "job": {"id": "synthetic-worker-id", "status": "COMPLETED"}, "unknown": [1, 2] }\n\n'


@pytest.fixture
def runtime(tmp_path):
    import os

    administrative_dsn = os.environ.get("TAFFYBOP_TEST_DATABASE_URL")
    if not administrative_dsn:
        pytest.skip("real PostgreSQL: TAFFYBOP_TEST_DATABASE_URL is not configured")
    name = "px1_worker_test_" + uuid4().hex
    with psycopg.connect(administrative_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        database = Database(make_conninfo(administrative_dsn, dbname=name))
        database.migrate()
        repo = ProductRepository(database, LocalArtifactStore((tmp_path / "artifacts").resolve()))
        yield SimpleNamespace(database=database, repo=repo, worker=WorkerRepository(repo), owner="worker-" + uuid4().hex)
    finally:
        with psycopg.connect(administrative_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def enqueue(runtime, *, owner=None, expires_at=None):
    owner = owner or runtime.owner
    document = runtime.repo.create_document(
        owner, display_name="synthetic-worker.pdf", media_type="application/pdf",
        data=SOURCE.read_bytes(), page_count=1, expires_at=expires_at,
    )
    job = runtime.repo.enqueue_parse(owner, document.id, settings=SETTINGS, idempotency_key=uuid4().hex,
        usage=Usage(estimated_credits=Decimal("3"), estimate_price_version="synthetic-estimate"))
    return document, job


def execution(runtime, job):
    with runtime.database.connect() as conn:
        return conn.execute("SELECT * FROM product.worker_executions WHERE job_id=%s", (job.id,)).fetchone()


def due(runtime, job, *, expire_lease=False):
    with runtime.database.connect() as conn:
        conn.execute("UPDATE product.worker_executions SET next_poll_at=clock_timestamp() - interval '1 second' WHERE job_id=%s", (job.id,))
        if expire_lease:
            conn.execute("UPDATE product.worker_executions SET lease_until=clock_timestamp() - interval '1 second' WHERE job_id=%s", (job.id,))


def accepted(runtime):
    document, job = enqueue(runtime)
    submit = runtime.worker.claim()
    assert submit.job.id == job.id and submit.provider_job_id is None
    runtime.worker.accepted(submit, "synthetic-worker-id")
    poll = runtime.worker.claim()
    assert poll.job.id == job.id and poll.provider_job_id == "synthetic-worker-id"
    return document, job, poll


def observation(status="COMPLETED", raw=None, usage=None):
    if raw is None:
        raw = RAW.replace(b'"COMPLETED"', ('"' + status + '"').encode())
    return ProviderObservation(
        status=status, raw=raw,
        markdown=PageSection(state="available", pages=(
            Page(page_number=2, content="  second\n"), Page(page_number=1, content="\tfirst "),
            Page(page_number=2, content=""),
        )), text=PageSection(state="not_returned"),
        warnings=("Authored worker test observation; no provider call",),
        usage=usage or Usage(),
    )


def test_two_concurrent_workers_admit_only_one_global_job(runtime):
    enqueue(runtime)
    enqueue(runtime, owner="other-" + uuid4().hex)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: WorkerRepository(runtime.repo).claim(), range(2)))
    assert sum(value is not None for value in claims) == 1
    claim = next(value for value in claims if value is not None)
    assert execution(runtime, claim.job)["capacity_slot"] == 1
    assert runtime.worker.claim() is None


def test_submission_intent_and_source_exist_before_network(runtime):
    document, job = enqueue(runtime)
    claim = runtime.worker.claim()
    persisted = runtime.repo.get_job(runtime.owner, job.id)
    assert persisted.status == "submitting" and persisted.started_at is not None
    assert execution(runtime, job)["provider_job_id"] is None
    assert runtime.worker.source(claim) == (document, SOURCE.read_bytes())


def test_expired_submitting_becomes_unknown_and_holds_capacity(runtime):
    _, job = enqueue(runtime)
    claim = runtime.worker.claim()
    _, waiting = enqueue(runtime)
    due(runtime, job, expire_lease=True)
    assert runtime.worker.claim() is None
    assert runtime.repo.get_job(runtime.owner, job.id).status == "submission_unknown"
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    assert execution(runtime, job)["capacity_slot"] == 1
    assert runtime.worker.claim() is None
    with pytest.raises(StaleClaim):
        runtime.worker.accepted(claim, "late-provider-ack")


def test_explicit_unknown_survives_fresh_repository_without_readmission(runtime):
    _, job = enqueue(runtime)
    claim = runtime.worker.claim()
    runtime.worker.unknown(claim)
    fresh = WorkerRepository(ProductRepository(runtime.database, runtime.repo.storage))
    assert fresh.claim() is None
    assert runtime.repo.get_job(runtime.owner, job.id).status == "submission_unknown"
    assert execution(runtime, job)["claim_token"] is None


def test_known_provider_id_resumes_after_lease_expiry_without_resubmission(runtime):
    _, job, old = accepted(runtime)
    due(runtime, job, expire_lease=True)
    recovered = WorkerRepository(runtime.repo).claim()
    assert recovered.provider_job_id == "synthetic-worker-id"
    assert recovered.job.id == old.job.id and recovered.token != old.token
    assert recovered.job.status == "running"
    with pytest.raises(StaleClaim):
        runtime.worker.complete(old, observation())
    completed = runtime.worker.complete(recovered, observation())
    assert completed.status == "succeeded"


def test_poll_error_retains_slot_and_persists_backoff(runtime):
    _, job, claim = accepted(runtime)
    runtime.worker.poll_later(claim, error=True, delay_seconds=0)
    first = execution(runtime, job)
    assert first["capacity_slot"] == 1 and first["poll_failures"] == 1
    assert first["last_poll_error"] == "provider_poll_unavailable"
    assert first["next_poll_at"] > datetime.now(timezone.utc)
    assert runtime.worker.claim() is None
    due(runtime, job)
    retry = runtime.worker.claim()
    runtime.worker.poll_later(retry, error=False, delay_seconds=0)
    assert execution(runtime, job)["poll_failures"] == 0
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"


def test_terminal_capture_preserves_bytes_pages_settings_and_unknown_usage(runtime):
    _, job, claim = accepted(runtime)
    reply = observation()
    completed = runtime.worker.complete(claim, reply)
    result = runtime.repo.get_parse_result(runtime.owner, completed.result_id)
    assert completed.status == "succeeded" and completed.raw_response == result.raw
    assert runtime.repo.read_artifact(runtime.owner, result.raw.id) == RAW
    assert result.markdown == reply.markdown and result.text == reply.text
    assert result.settings == job.settings and result.provider_version is None
    assert result.usage.estimated_credits == Decimal("3")
    assert result.usage.actual_credits is None and result.usage.reconciliation == "pending"
    assert execution(runtime, job)["capacity_slot"] is None
    _, waiting = enqueue(runtime)
    assert runtime.worker.claim().job.id == waiting.id


def test_observed_zero_usage_is_preserved_as_actual(runtime):
    _, job, claim = accepted(runtime)
    completed = runtime.worker.complete(claim, observation(usage=Usage(actual_credits=Decimal("0"), reconciliation="observed")))
    assert completed.usage.actual_credits == Decimal("0")
    assert completed.usage.reconciliation == "observed"
    assert completed.usage.estimated_credits == Decimal("3")


@pytest.mark.parametrize("status,expected", [("FAILED", "failed"), ("CANCELLED", "cancelled")])
def test_failed_and_cancelled_jobs_retain_raw_without_success_result(runtime, status, expected):
    _, job, claim = accepted(runtime)
    raw = b'{ "job": {"id": "synthetic-worker-id", "status": "' + status.encode() + b'"}, "unknown": 12 }\n'
    completed = runtime.worker.complete(claim, observation(status, raw))
    assert completed.status == expected and completed.result_id is None
    assert runtime.repo.read_artifact(runtime.owner, completed.raw_response.id) == raw
    assert completed.cancellation_confirmed is (status == "CANCELLED")
    assert (completed.error is not None) is (status == "FAILED")
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.parse_results WHERE job_id=%s", (job.id,)).fetchone()["n"] == 0
    assert execution(runtime, job)["capacity_slot"] is None


def test_disk_failure_rolls_back_terminal_metadata_and_slot_release(runtime, monkeypatch):
    _, job, claim = accepted(runtime)
    original = runtime.repo.storage.put
    def fail(*_args, **_kwargs):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(runtime.repo.storage, "put", fail)
    with pytest.raises(OSError):
        runtime.worker.complete(claim, observation())
    persisted = runtime.repo.get_job(runtime.owner, job.id)
    assert persisted.status == "running" and persisted.raw_response is None
    assert execution(runtime, job)["capacity_slot"] == 1
    monkeypatch.setattr(runtime.repo.storage, "put", original)
    assert runtime.worker.complete(claim, observation()).status == "succeeded"


def test_rejected_submission_releases_capacity_and_can_pause_admission(runtime):
    _, job = enqueue(runtime)
    submit = runtime.worker.claim()
    _, waiting = enqueue(runtime)
    runtime.worker.reject(submit, pause=True)
    rejected = runtime.repo.get_job(runtime.owner, job.id)
    assert rejected.status == "failed" and rejected.raw_response is None
    assert execution(runtime, job)["capacity_slot"] is None
    assert runtime.worker.claim() is None
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"


def test_revoked_queued_documents_are_never_admitted(runtime):
    revoked, job = enqueue(runtime)
    runtime.repo.delete_document(runtime.owner, revoked.id)
    _, next_job = enqueue(runtime)
    assert runtime.worker.claim().job.id == next_job.id
    assert execution(runtime, job) is None


def test_expired_queued_documents_are_never_admitted(runtime):
    document, job = enqueue(runtime, expires_at=datetime.now(timezone.utc) + timedelta(minutes=1))
    with runtime.database.connect() as conn:
        conn.execute("UPDATE product.documents SET expires_at=created_at WHERE id=%s", (document.id,))
    assert runtime.worker.claim() is None
    assert execution(runtime, job) is None


def test_revoked_active_job_is_reconciled_without_restoring_owner_reads(runtime):
    document, job, claim = accepted(runtime)
    runtime.repo.delete_document(runtime.owner, document.id)
    due(runtime, job, expire_lease=True)
    recovered = runtime.worker.claim()
    completed = runtime.worker.complete(recovered, observation())
    assert completed.status == "succeeded" and execution(runtime, job)["capacity_slot"] is None
    for read in (
        lambda: runtime.repo.get_job(runtime.owner, job.id),
        lambda: runtime.repo.get_parse_result(runtime.owner, completed.result_id),
        lambda: runtime.repo.read_artifact(runtime.owner, completed.raw_response.id),
    ):
        with pytest.raises(ResourceNotFound):
            read()


def test_source_fencing_and_revocation_are_checked_before_submission(runtime):
    document, job = enqueue(runtime)
    claim = runtime.worker.claim()
    runtime.repo.delete_document(runtime.owner, document.id)
    with pytest.raises(ResourceNotFound):
        runtime.worker.source(claim)
    assert execution(runtime, job)["capacity_slot"] == 1
    runtime.worker.reject(claim)


def test_direct_sql_cannot_release_capacity_without_terminal_state(runtime):
    _, job, _ = accepted(runtime)
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.database.connect() as conn:
            conn.execute("UPDATE product.worker_executions SET capacity_slot=NULL,claim_token=NULL,lease_until=NULL WHERE job_id=%s", (job.id,))
    assert execution(runtime, job)["capacity_slot"] == 1


def test_provider_identity_and_terminal_admission_are_immutable(runtime):
    _, job, claim = accepted(runtime)
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.database.connect() as conn:
            conn.execute("UPDATE product.worker_executions SET provider_job_id='different-upstream-job' WHERE job_id=%s", (job.id,))
    runtime.worker.complete(claim, observation())
    with pytest.raises(psycopg.errors.CheckViolation):
        with runtime.database.connect() as conn:
            conn.execute("UPDATE product.worker_executions SET capacity_slot=1 WHERE job_id=%s", (job.id,))


@pytest.mark.parametrize("raw", [b"", b"not JSON", b'{"nonfinite": NaN}'])
def test_invalid_terminal_bytes_never_release_capacity(runtime, raw):
    _, job, claim = accepted(runtime)
    with pytest.raises(PersistenceConflict):
        runtime.worker.complete(claim, observation(raw=raw))
    assert execution(runtime, job)["capacity_slot"] == 1
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"


@pytest.mark.parametrize("raw", [
    b'{"job":{"id":"different-provider-job","status":"COMPLETED"}}',
    b'{"job":{"id":"synthetic-worker-id","status":"FAILED"}}',
    b'{"status":"COMPLETED"}',
    b'[]',
])
def test_mismatched_terminal_envelope_is_rejected_before_artifact_writes(runtime, raw):
    _, job, claim = accepted(runtime)
    with pytest.raises(PersistenceConflict):
        runtime.worker.complete(claim, observation(raw=raw))
    assert execution(runtime, job)["capacity_slot"] == 1
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.artifacts").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM product.parse_results").fetchone()["n"] == 0


def test_nonterminal_observation_cannot_complete(runtime):
    _, job, claim = accepted(runtime)
    with pytest.raises(ValueError):
        runtime.worker.complete(claim, observation(status="RUNNING"))
    assert execution(runtime, job)["capacity_slot"] == 1


def test_stale_claim_cannot_read_or_change_submission_intent(runtime):
    _, job = enqueue(runtime)
    claim = runtime.worker.claim()
    stale = replace(claim, token=uuid4())
    for operation in (
        lambda: runtime.worker.source(stale), lambda: runtime.worker.accepted(stale, "unused"),
        lambda: runtime.worker.unknown(stale), lambda: runtime.worker.reject(stale),
    ):
        with pytest.raises(StaleClaim):
            operation()
    assert runtime.repo.get_job(runtime.owner, job.id).status == "submitting"


def test_queued_cancellation_is_confirmed_locally_and_never_submitted(runtime):
    _, job = enqueue(runtime)
    cancelled = runtime.worker.request_cancel(runtime.owner, job.id)
    assert cancelled.status == "cancelled" and cancelled.cancellation_confirmed is True
    assert cancelled.cancellation_requested_at is not None and cancelled.started_at is None
    assert execution(runtime, job) is None and runtime.worker.claim() is None
    assert runtime.worker.request_cancel(runtime.owner, job.id) == cancelled


def test_cancellation_checks_owner_and_revocation(runtime):
    document, job = enqueue(runtime)
    for identity in (job.id, uuid4()):
        with pytest.raises(ResourceNotFound):
            runtime.worker.request_cancel("other-owner", identity)
    runtime.repo.delete_document(runtime.owner, document.id)
    with pytest.raises(ResourceNotFound):
        runtime.worker.request_cancel(runtime.owner, job.id)


def test_cancel_during_submission_keeps_capacity_then_polls_known_id(runtime):
    _, job = enqueue(runtime)
    submit = runtime.worker.claim()
    requested = runtime.worker.request_cancel(runtime.owner, job.id)
    assert requested.status == "submitting" and requested.cancellation_confirmed is False
    assert requested.cancellation_requested_at is not None
    runtime.worker.accepted(submit, "synthetic-worker-id")
    poll = runtime.worker.claim()
    assert poll.job.status == "cancel_requested" and poll.provider_job_id == "synthetic-worker-id"
    assert execution(runtime, job)["capacity_slot"] == 1
    completed = runtime.worker.complete(poll, observation())
    assert completed.status == "succeeded" and completed.cancellation_confirmed is False
    assert completed.cancellation_requested_at == requested.cancellation_requested_at


def test_cancellation_of_unknown_submission_never_claims_it_stopped(runtime):
    _, job = enqueue(runtime)
    claim = runtime.worker.claim()
    runtime.worker.unknown(claim)
    requested = runtime.worker.request_cancel(runtime.owner, job.id)
    assert requested.status == "submission_unknown" and requested.cancellation_requested_at is not None
    assert requested.cancellation_confirmed is False and execution(runtime, job)["capacity_slot"] == 1
    assert runtime.worker.claim() is None


def test_running_cancellation_remains_requested_until_provider_confirmation(runtime):
    _, job, poll = accepted(runtime)
    requested = runtime.worker.request_cancel(runtime.owner, job.id)
    assert requested.status == "cancel_requested" and requested.cancellation_confirmed is False
    completed = runtime.worker.complete(poll, observation(status="CANCELLED"))
    assert completed.status == "cancelled" and completed.cancellation_confirmed is True
    assert completed.cancellation_requested_at == requested.cancellation_requested_at


class AuthoredProvider:
    """In-process authored outcomes; no HTTP transport or provider credential."""

    def __init__(self, *, submit_error=None, poll_error=None, response=None):
        self.submit_error = submit_error
        self.poll_error = poll_error
        self.response = response or observation()
        self.submissions = []
        self.polls = []

    async def submit(self, data, filename, media_type, settings):
        self.submissions.append((data, filename, media_type, settings))
        if self.submit_error is not None:
            raise self.submit_error
        return ProviderSubmission("synthetic-worker-id", "PENDING")

    async def poll(self, provider_job_id):
        self.polls.append(provider_job_id)
        if self.poll_error is not None:
            raise self.poll_error
        return self.response


def test_dispatcher_accepts_then_fresh_worker_completes_without_second_post(runtime):
    document, job = enqueue(runtime)
    provider = AuthoredProvider()
    assert asyncio.run(Worker(runtime.worker, provider).step()) == "accepted"
    assert len(provider.submissions) == 1 and provider.polls == []
    source, filename, media_type, settings = provider.submissions[0]
    assert source == SOURCE.read_bytes() and filename == document.display_name
    assert media_type == "application/pdf" and settings == job.settings
    fresh = Worker(WorkerRepository(ProductRepository(runtime.database, runtime.repo.storage)), provider)
    assert asyncio.run(fresh.step()) == "succeeded"
    assert len(provider.submissions) == 1 and provider.polls == ["synthetic-worker-id"]
    completed = runtime.repo.get_job(runtime.owner, job.id)
    assert runtime.repo.read_artifact(runtime.owner, completed.raw_response.id) == RAW


def test_dispatcher_definite_rejection_pauses_backlog(runtime):
    _, job = enqueue(runtime)
    _, waiting = enqueue(runtime)
    provider = AuthoredProvider(submit_error=ProviderError("provider_rate_limited", "Authored rate limit"))
    worker = Worker(runtime.worker, provider)
    assert asyncio.run(worker.step()) == "submission_rejected"
    assert asyncio.run(worker.step()) == "idle" and len(provider.submissions) == 1
    assert runtime.repo.get_job(runtime.owner, job.id).status == "failed"
    assert runtime.repo.get_job(runtime.owner, waiting.id).status == "queued"
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT admission_paused FROM product.worker_control WHERE singleton").fetchone()["admission_paused"] is True


def test_dispatcher_ambiguous_submission_never_recreates_job(runtime):
    _, job = enqueue(runtime)
    provider = AuthoredProvider(submit_error=ProviderError("provider_timeout", "Authored timeout", ambiguous=True))
    worker = Worker(runtime.worker, provider)
    assert asyncio.run(worker.step()) == "submission_unknown"
    assert asyncio.run(worker.step()) == "idle"
    assert len(provider.submissions) == 1 and provider.polls == []
    assert runtime.repo.get_job(runtime.owner, job.id).status == "submission_unknown"
    assert execution(runtime, job)["capacity_slot"] == 1


@pytest.mark.parametrize("failure", [asyncio.CancelledError(), RuntimeError("Authored unexpected submit failure")])
def test_dispatcher_interrupted_submit_retains_unknown_intent(runtime, failure):
    _, job = enqueue(runtime)
    provider = AuthoredProvider(submit_error=failure)
    with pytest.raises(type(failure)):
        asyncio.run(Worker(runtime.worker, provider).step())
    assert runtime.repo.get_job(runtime.owner, job.id).status == "submission_unknown"
    assert execution(runtime, job)["capacity_slot"] == 1
    assert asyncio.run(Worker(runtime.worker, provider).step()) == "idle"
    assert len(provider.submissions) == 1


def test_dispatcher_poll_failure_schedules_retry_without_new_submission(runtime):
    _, job = enqueue(runtime)
    provider = AuthoredProvider(poll_error=ProviderError("provider_unavailable", "Authored poll failure"))
    worker = Worker(runtime.worker, provider)
    assert asyncio.run(worker.step()) == "accepted"
    assert asyncio.run(worker.step()) == "poll_unavailable"
    assert len(provider.submissions) == 1 and len(provider.polls) == 1
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"
    assert execution(runtime, job)["capacity_slot"] == 1
    assert asyncio.run(worker.step()) == "idle"
    due(runtime, job)
    provider.poll_error = None
    assert asyncio.run(worker.step()) == "succeeded"
    assert len(provider.submissions) == 1 and len(provider.polls) == 2


@pytest.mark.parametrize("status,expected", [("RUNNING", "running"), ("UNRECOGNIZED", "poll_unavailable")])
def test_dispatcher_nonterminal_and_unknown_poll_states_retain_capacity(runtime, status, expected):
    _, job = enqueue(runtime)
    provider = AuthoredProvider(response=observation(status=status))
    worker = Worker(runtime.worker, provider)
    assert asyncio.run(worker.step()) == "accepted"
    assert asyncio.run(worker.step()) == expected
    assert execution(runtime, job)["capacity_slot"] == 1
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"
    assert len(provider.submissions) == 1


def test_dispatcher_source_revoked_after_claim_never_calls_provider(runtime, monkeypatch):
    document, job = enqueue(runtime)
    source = runtime.worker.source
    def revoke_before_source(claim):
        runtime.repo.delete_document(runtime.owner, document.id)
        return source(claim)
    monkeypatch.setattr(runtime.worker, "source", revoke_before_source)
    provider = AuthoredProvider()
    assert asyncio.run(Worker(runtime.worker, provider).step()) == "source_unavailable"
    assert provider.submissions == [] and provider.polls == []
    assert execution(runtime, job)["capacity_slot"] is None
    with runtime.database.connect() as conn:
        payload = conn.execute("SELECT payload FROM product.jobs WHERE id=%s", (job.id,)).fetchone()["payload"]
    assert payload["status"] == "failed"


def test_lease_expiry_during_artifact_publication_rolls_back_capture(runtime, monkeypatch):
    runtime.worker = WorkerRepository(runtime.repo, lease_seconds=1)
    _, job, claim = accepted(runtime)
    original = runtime.repo.storage.put
    def slow_put(*args, **kwargs):
        original(*args, **kwargs)
        time.sleep(1.05)
    monkeypatch.setattr(runtime.repo.storage, "put", slow_put)
    with pytest.raises(StaleClaim):
        runtime.worker.complete(claim, observation())
    assert runtime.repo.get_job(runtime.owner, job.id).status == "running"
    assert execution(runtime, job)["capacity_slot"] == 1
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.parse_results WHERE job_id=%s", (job.id,)).fetchone()["n"] == 0
    monkeypatch.setattr(runtime.repo.storage, "put", original)
    recovered = runtime.worker.claim()
    assert recovered.provider_job_id == "synthetic-worker-id"
    assert runtime.worker.complete(recovered, observation()).status == "succeeded"


def test_run_rejects_legacy_profile_before_claim(monkeypatch):
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", "legacy_local")
    calls = []
    def claim():
        calls.append("claim")
        raise AssertionError("Legacy profile must not reach worker admission")
    worker = Worker(SimpleNamespace(claim=claim), AuthoredProvider())
    with pytest.raises(RuntimeProfileError):
        asyncio.run(worker.run())
    assert calls == []


def test_run_holds_admission_lock_across_step_and_releases_on_cancellation(tmp_path, monkeypatch):
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", "product_worker_local")
    path = tmp_path / "worker-admission" / "provider.lock"
    monkeypatch.setenv("TAFFYBOP_PROVIDER_LOCK_PATH", str(path))
    worker = Worker(SimpleNamespace(), AuthoredProvider())
    calls = []
    async def step():
        calls.append("step")
        with pytest.raises(RuntimeProfileError):
            LocalProviderLock("product_worker_local", path).acquire()
        await asyncio.sleep(0)
        with pytest.raises(RuntimeProfileError):
            LocalProviderLock("product_worker_local", path).acquire()
        raise asyncio.CancelledError()
    monkeypatch.setattr(worker, "step", step)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run())
    assert calls == ["step"]
    with LocalProviderLock("product_worker_local", path):
        pass
