"""Real PostgreSQL persistence checks; synthetic results, never provider evidence.

Set TAFFYBOP_TEST_DATABASE_URL to a dedicated test database. These tests add
unique test owners and never truncate a pre-existing schema or data directory.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg", reason="install the pinned PostgreSQL driver")

from app.product.contracts import Artifact, Page, PageSection, ParseResult, ParseSettings, Usage
from app.product.database import Database, MigrationError
from app.product.repository import (
    IdempotencyConflict, PersistenceConflict, ProductRepository, ResourceNotFound,
)
from app.product.storage import LocalArtifactStore


SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28")
FAST = ParseSettings(mode="fast", requested_version="2026-06-15")
SOURCE = Path(__file__).parent / "fixtures/parse_extract_v1/dev-invoice-104.pdf"
RAW = b'{  "status": "COMPLETED", "unknown": {"keep": [1, 2]}, "pages": [] }\n\n'


@pytest.fixture(scope="module")
def database():
    dsn = os.environ.get("TAFFYBOP_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("real PostgreSQL: TAFFYBOP_TEST_DATABASE_URL is not configured")
    value = Database(dsn)
    value.migrate()
    return value


@pytest.fixture
def repo(database, tmp_path):
    return ProductRepository(database, LocalArtifactStore((tmp_path / "artifacts").resolve()))


@pytest.fixture
def owner():
    return f"test-{uuid4()}"


def upload(repo, owner, **changes):
    return repo.create_document(owner, **dict(
        display_name="synthetic-invoice.pdf", media_type="application/pdf",
        data=SOURCE.read_bytes(), page_count=1,
    ), **changes)


def enqueue(repo, owner, document, key=None, settings=SETTINGS):
    return repo.enqueue_parse(owner, document.id, idempotency_key=str(uuid4()) if key is None else key, settings=settings)


def synthetic_result(job, raw=RAW, **changes):
    """Deliberately authored storage test data; this is not a parse observation."""
    value = dict(
        id=uuid4(), document_id=job.document_id, job_id=job.id,
        created_at=datetime.now(timezone.utc), settings=job.settings,
        raw=Artifact(id=uuid4(), sha256=hashlib.sha256(raw).hexdigest(),
                     size_bytes=len(raw), media_type="application/json"),
        markdown=PageSection(state="available", pages=(
            Page(page_number=2, content="  second\n"),
            Page(page_number=1, content="\tfirst "),
            Page(page_number=2, content=""),
        )), text=PageSection(state="not_returned"),
        warnings=("Synthetic persistence fixture; no provider call",),
    )
    value.update(changes)
    return ParseResult(**value)


def test_migrations_are_repeatable(database):
    assert database.migrate() == ()
    with database.connect() as conn:
        rows = conn.execute("SELECT version, sha256 FROM product.schema_migrations ORDER BY version").fetchall()
    assert rows
    # Support both psycopg's tuple and mapping row factories.
    for row in rows:
        digest = row["sha256"] if isinstance(row, dict) else row[1]
        assert len(digest) == 64


def test_changed_migration_is_rejected_without_touching_rows(database, tmp_path):
    source = Path(__file__).parents[1] / "app/product/migrations"
    for path in source.glob("*.sql"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    first = sorted(tmp_path.glob("*.sql"))[0]
    first.write_text(first.read_text() + "\n-- deliberate checksum drift for test\n")
    with pytest.raises(MigrationError):
        database.migrate(tmp_path)
    assert database.migrate() == ()


def test_failed_migration_rolls_back_ddl_and_ledger(database, tmp_path):
    source = Path(__file__).parents[1] / "app/product/migrations"
    for path in source.glob("*.sql"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    object_name = "test_rollback_" + uuid4().hex
    bad = tmp_path / "999_test_failure.sql"
    bad.write_text(f"CREATE TABLE product.{object_name}(id integer);\nSELECT 1/0;\n")
    with pytest.raises((MigrationError, psycopg.Error)):
        database.migrate(tmp_path)
    with database.connect() as conn:
        assert conn.execute("SELECT to_regclass(%s)", (f"product.{object_name}",)).fetchone()["to_regclass"] is None
        assert not conn.execute("SELECT 1 FROM product.schema_migrations WHERE version=%s", (bad.name,)).fetchone()
    assert database.migrate() == ()


def test_document_and_source_reopen_through_fresh_repository(database, repo, owner, tmp_path):
    document = upload(repo, owner)
    reopened = ProductRepository(database, LocalArtifactStore((tmp_path / "artifacts").resolve()))
    assert reopened.get_document(owner, document.id) == document
    assert reopened.read_artifact(owner, document.source.id) == SOURCE.read_bytes()
    assert document.source.sha256 == hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    assert document.source.size_bytes == SOURCE.stat().st_size


def test_source_and_owned_metadata_are_not_bearer_capabilities(repo, owner):
    document = upload(repo, owner)
    other = f"test-{uuid4()}"
    for principal in (other, f"nonexistent-{uuid4()}"):
        with pytest.raises(ResourceNotFound):
            repo.get_document(principal, document.id)
        with pytest.raises(ResourceNotFound):
            repo.read_artifact(principal, document.source.id)
        with pytest.raises(ResourceNotFound):
            enqueue(repo, principal, document)
        with pytest.raises(ResourceNotFound):
            repo.delete_document(principal, document.id)
        assert repo.list_documents(principal) == ()


def test_identical_uploads_remain_distinct_across_owners(repo, owner):
    first = upload(repo, owner)
    other = f"test-{uuid4()}"
    second = upload(repo, other)
    assert first.source.sha256 == second.source.sha256
    assert first.id != second.id
    assert first.source.id != second.source.id
    with pytest.raises(ResourceNotFound):
        repo.read_artifact(owner, second.source.id)


def test_owned_list_paginates_without_duplicates(repo, owner):
    documents = [upload(repo, owner) for _ in range(5)]
    upload(repo, f"test-{uuid4()}")
    expected = tuple(sorted(documents, key=lambda doc: (doc.created_at, doc.id), reverse=True))
    first = repo.list_documents(owner, limit=2)
    second = repo.list_documents(owner, limit=2, before=(first[-1].created_at, first[-1].id))
    third = repo.list_documents(owner, limit=2, before=(second[-1].created_at, second[-1].id))
    assert first + second + third == expected


def test_parse_intent_is_durable_and_preserves_unknown_usage(repo, owner):
    document = upload(repo, owner)
    usage = Usage(estimated_credits=Decimal("3"), estimate_price_version="synthetic-test-price")
    job = repo.enqueue_parse(owner, document.id, idempotency_key="request-1", settings=SETTINGS, usage=usage)
    assert job.status == "queued"
    assert job.settings == SETTINGS
    assert job.started_at is None
    assert job.result_id is None
    assert job.raw_response is None
    assert job.usage.actual_credits is None
    assert job.usage.reconciliation == "pending"
    assert repo.get_job(owner, job.id) == job
    with pytest.raises(ResourceNotFound):
        repo.get_job(f"test-{uuid4()}", job.id)


def test_idempotency_reuses_same_intent_and_conflicts_for_changed_input(repo, owner):
    document = upload(repo, owner)
    other_document = upload(repo, owner)
    job = enqueue(repo, owner, document, key="request-1")
    assert enqueue(repo, owner, document, key="request-1") == job
    with pytest.raises(IdempotencyConflict):
        enqueue(repo, owner, document, key="request-1", settings=FAST)
    with pytest.raises(IdempotencyConflict):
        enqueue(repo, owner, other_document, key="request-1")
    other_owner = f"test-{uuid4()}"
    other = upload(repo, other_owner)
    assert enqueue(repo, other_owner, other, key="request-1").id != job.id


def test_concurrent_identical_requests_create_one_job(database, repo, owner):
    document = upload(repo, owner)
    barrier = Barrier(4)

    def submit(_):
        barrier.wait(timeout=10)
        return enqueue(repo, owner, document, key="concurrent-request")

    with ThreadPoolExecutor(max_workers=4) as executor:
        jobs = list(executor.map(submit, range(4)))
    assert len({job.id for job in jobs}) == 1
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM product.jobs WHERE owner_key=%s", (owner,)).fetchone()["count"] == 1


@pytest.mark.parametrize("key", ["", "\n", "a\tb", "é", "a" * 129])
def test_invalid_idempotency_keys_never_create_intent(repo, owner, key):
    document = upload(repo, owner)
    with pytest.raises(ValueError):
        enqueue(repo, owner, document, key=key)


def test_success_and_raw_bytes_are_committed_atomically(database, repo, owner):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job)
    assert repo.save_parse_result(owner, result, RAW) == result
    assert repo.get_parse_result(owner, result.id) == result
    assert repo.read_artifact(owner, result.raw.id) == RAW
    completed = repo.get_job(owner, job.id)
    assert completed.status == "succeeded"
    assert completed.result_id == result.id
    assert completed.raw_response == result.raw
    assert completed.settings == job.settings
    assert completed.usage.actual_credits is None
    assert completed.finished_at is not None
    assert repo.get_parse_result(owner, result.id).markdown.pages == result.markdown.pages
    assert repo.get_parse_result(owner, result.id).provider_version is None
    for resource_id, read in ((result.id, repo.get_parse_result), (result.raw.id, repo.read_artifact)):
        with pytest.raises(ResourceNotFound):
            read(f"test-{uuid4()}", resource_id)


def test_wrong_result_settings_leave_job_queued(repo, owner):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job, settings=FAST)
    with pytest.raises(PersistenceConflict):
        repo.save_parse_result(owner, result, RAW)
    assert repo.get_job(owner, job.id) == job
    with pytest.raises(ResourceNotFound):
        repo.get_parse_result(owner, result.id)
    with pytest.raises(ResourceNotFound):
        repo.read_artifact(owner, result.raw.id)


def test_wrong_raw_hash_never_exposes_result(repo, owner):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job)
    with pytest.raises((PersistenceConflict, ValueError)):
        repo.save_parse_result(owner, result, RAW + b" ")
    assert repo.get_job(owner, job.id).status == "queued"
    with pytest.raises(ResourceNotFound):
        repo.get_parse_result(owner, result.id)


def test_other_document_cannot_steal_a_jobs_result(repo, owner):
    document = upload(repo, owner)
    other = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job, document_id=other.id)
    with pytest.raises((PersistenceConflict, ResourceNotFound)):
        repo.save_parse_result(owner, result, RAW)
    assert repo.get_job(owner, job.id).status == "queued"


def test_result_and_artifact_metadata_are_database_immutable(database, repo, owner):
    document = upload(repo, owner)
    result = synthetic_result(enqueue(repo, owner, document))
    repo.save_parse_result(owner, result, RAW)
    for query, values in [
        ("UPDATE product.parse_results SET payload=jsonb_set(payload, '{warnings}', '[\"altered\"]') WHERE id=%s", (result.id,)),
        ("UPDATE product.artifacts SET sha256=%s WHERE id=%s", ("0" * 64, result.raw.id)),
    ]:
        with pytest.raises(psycopg.Error), database.connect() as conn:
            conn.execute(query, values)
    assert repo.get_parse_result(owner, result.id) == result
    assert repo.read_artifact(owner, result.raw.id) == RAW


def test_job_settings_are_database_immutable(database, repo, owner):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    with pytest.raises(psycopg.Error), database.connect() as conn:
        conn.execute("UPDATE product.jobs SET payload=jsonb_set(payload, '{settings,mode}', '\"fast\"') WHERE id=%s", (job.id,))
    assert repo.get_job(owner, job.id) == job


def test_database_rejects_cross_owner_artifact_relationship(database, repo, owner):
    document = upload(repo, owner)
    other_owner = f"test-{uuid4()}"
    other = upload(repo, other_owner)
    with pytest.raises(psycopg.Error), database.connect() as conn:
        conn.execute(
            "INSERT INTO product.artifacts(id, owner_key, document_id, sha256, size_bytes, media_type) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (uuid4(), other_owner, document.id, other.source.sha256, other.source.size_bytes, other.source.media_type),
        )


def test_deleted_document_revokes_entire_resource_graph(repo, owner):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job)
    repo.save_parse_result(owner, result, RAW)
    repo.delete_document(owner, document.id)
    for resource_id, read in (
        (document.id, repo.get_document), (document.source.id, repo.read_artifact),
        (job.id, repo.get_job), (result.id, repo.get_parse_result), (result.raw.id, repo.read_artifact),
    ):
        with pytest.raises(ResourceNotFound):
            read(owner, resource_id)
    assert repo.list_documents(owner) == ()
    with pytest.raises(ResourceNotFound):
        enqueue(repo, owner, document)


def test_expiry_revokes_source_job_and_result_reads(database, repo, owner):
    document = upload(repo, owner, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    job = enqueue(repo, owner, document)
    result = synthetic_result(job)
    repo.save_parse_result(owner, result, RAW)
    with database.connect() as conn:
        conn.execute("UPDATE product.documents SET expires_at=created_at WHERE id=%s", (document.id,))
    for resource_id, read in (
        (document.id, repo.get_document), (document.source.id, repo.read_artifact),
        (job.id, repo.get_job), (result.id, repo.get_parse_result), (result.raw.id, repo.read_artifact),
    ):
        with pytest.raises(ResourceNotFound):
            read(owner, resource_id)
    assert repo.list_documents(owner) == ()


def test_failed_source_write_cannot_create_accepted_document(database, repo, owner, monkeypatch):
    def disk_failure(*_args, **_kwargs):
        raise OSError("simulated full artifact volume")

    monkeypatch.setattr(LocalArtifactStore, "put", disk_failure)
    with pytest.raises(OSError, match="simulated full artifact volume"):
        upload(repo, owner)
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM product.documents WHERE owner_key=%s", (owner,)).fetchone()["count"] == 0
        assert conn.execute("SELECT count(*) FROM product.artifacts WHERE owner_key=%s", (owner,)).fetchone()["count"] == 0


def test_failed_raw_write_cannot_mark_job_succeeded(database, repo, owner, monkeypatch):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job)

    def disk_failure(*_args, **_kwargs):
        raise OSError("simulated full artifact volume")

    monkeypatch.setattr(LocalArtifactStore, "put", disk_failure)
    with pytest.raises(OSError, match="simulated full artifact volume"):
        repo.save_parse_result(owner, result, RAW)
    assert repo.get_job(owner, job.id) == job
    with pytest.raises(ResourceNotFound):
        repo.get_parse_result(owner, result.id)
    with database.connect() as conn:
        assert not conn.execute("SELECT id FROM product.artifacts WHERE id=%s", (result.raw.id,)).fetchone()


@pytest.mark.parametrize("raw", [b"{bad", b'{"x":NaN}', b'"\xff"'])
def test_invalid_raw_json_never_publishes_success(repo, owner, raw):
    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job, raw=raw)
    with pytest.raises(PersistenceConflict):
        repo.save_parse_result(owner, result, raw)
    assert repo.get_job(owner, job.id) == job
    with pytest.raises(ResourceNotFound):
        repo.get_parse_result(owner, result.id)
    with pytest.raises(ResourceNotFound):
        repo.read_artifact(owner, result.raw.id)


def test_missing_applied_migration_is_rejected(database, tmp_path):
    # Keep a candidate file so the runner must compare its applied ledger,
    # rather than rejecting only an empty migrations directory.
    (tmp_path / "999_candidate.sql").write_text("SELECT 1;\n")
    with pytest.raises(MigrationError):
        database.migrate(tmp_path)
    assert database.migrate() == ()


def test_concurrent_migration_checks_are_serialized_noops(database):
    barrier = Barrier(4)

    def migrate(_):
        barrier.wait(timeout=10)
        return database.migrate()

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(migrate, range(4))) == [(), (), (), ()]


@pytest.mark.parametrize("inconsistency", ["orphan_result", "raw_metadata", "settings"])
def test_database_rejects_inconsistent_deferred_capture(database, repo, owner, inconsistency):
    from psycopg.types.json import Jsonb

    document = upload(repo, owner)
    job = enqueue(repo, owner, document)
    result = synthetic_result(job, **({"settings": FAST} if inconsistency == "settings" else {}))
    raw_reference = result.raw
    if inconsistency == "raw_metadata":
        raw_reference = result.raw.model_copy(update={"sha256": "0" * 64})
    completed = job.model_copy(update={
        "status": "succeeded", "result_id": result.id, "raw_response": raw_reference,
        "started_at": job.created_at, "finished_at": result.created_at,
        "updated_at": result.created_at,
    })
    with pytest.raises(psycopg.Error), database.connect() as conn:
        conn.execute(
            "INSERT INTO product.artifacts(id,owner_key,document_id,sha256,size_bytes,media_type) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (result.raw.id, owner, document.id, result.raw.sha256, result.raw.size_bytes, result.raw.media_type),
        )
        conn.execute(
            "INSERT INTO product.parse_results(id,owner_key,document_id,job_id,raw_artifact_id,payload) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (result.id, owner, document.id, job.id, result.raw.id, Jsonb(result.model_dump(mode="json"))),
        )
        if inconsistency != "orphan_result":
            conn.execute(
                "UPDATE product.jobs SET result_id=%s,raw_artifact_id=%s,payload=%s WHERE id=%s",
                (result.id, result.raw.id, Jsonb(completed.model_dump(mode="json")), job.id),
            )
    assert repo.get_job(owner, job.id) == job
    with pytest.raises(ResourceNotFound):
        repo.get_parse_result(owner, result.id)
    with pytest.raises(ResourceNotFound):
        repo.read_artifact(owner, result.raw.id)
