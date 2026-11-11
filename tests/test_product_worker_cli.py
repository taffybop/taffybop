"""Packaged guarded runner checks; all results are explicitly authored simulation."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.product.allowance import TestAllowance, allowance_summary
from app.product.contracts import ParseSettings
from app.product.database import Database
from app.product.repository import ProductRepository
from app.product.runtime_profile import LocalProviderLock
from app.product.storage import LocalArtifactStore
from app.product import worker


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ParseSettings(mode="cost_effective", requested_version="2026-09-28")


@pytest.fixture
def runtime(tmp_path):
    administrative_dsn = os.environ.get("TAFFYBOP_TEST_DATABASE_URL")
    if not administrative_dsn:
        pytest.skip("real PostgreSQL: TAFFYBOP_TEST_DATABASE_URL is not configured")
    name = "px1_worker_cli_" + uuid4().hex
    with psycopg.connect(administrative_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = make_conninfo(administrative_dsn, dbname=name)
        database = Database(dsn)
        database.migrate()
        store = (tmp_path / "artifacts").resolve()
        repo = ProductRepository(database, LocalArtifactStore(store))
        yield SimpleNamespace(database=database, repo=repo, dsn=dsn, store=store,
            root=tmp_path.resolve(), lock=(tmp_path / "runtime/provider.lock").resolve(), owner=uuid4().hex)
    finally:
        with psycopg.connect(administrative_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def enqueue(runtime, source="dev-invoice-104.pdf"):
    document = runtime.repo.create_document(runtime.owner, display_name=source,
        media_type="application/pdf" if source.endswith("pdf") else "image/png",
        data=(ROOT / "tests/fixtures/parse_extract_v1" / source).read_bytes(), page_count=1)
    return runtime.repo.enqueue_parse(runtime.owner, document.id, settings=SETTINGS, idempotency_key=uuid4().hex)


def allowance_file(runtime, jobs):
    allowance = TestAllowance(id=uuid4(), job_ids=tuple(job.id for job in jobs), settings=SETTINGS,
        max_jobs=1, max_pages=10, credit_limit=Decimal("30"), usd_limit=Decimal("0.045"),
        credits_per_page=Decimal("3"), usd_per_credit=Decimal("0.0015"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    path = runtime.root / "allowance.json"
    path.write_text(allowance.model_dump_json())
    return path, allowance


def command(runtime, *args, overrides=None):
    env = os.environ.copy()
    env.pop("LLAMA_CLOUD_API_KEY", None)
    env.update(TAFFYBOP_DATABASE_URL=runtime.dsn, TAFFYBOP_ARTIFACT_ROOT=str(runtime.store),
        TAFFYBOP_RUNTIME_PROFILE="product_worker_local", TAFFYBOP_PROVIDER_LOCK_PATH=str(runtime.lock))
    env.update(overrides or {})
    return subprocess.run([sys.executable, "-m", "app.product.worker", *args], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("args", [[], ["--run-simulated"], ["--check", "--run-simulated"]])
def test_invalid_command_arguments_never_reach_preflight(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["worker", *args])
    monkeypatch.setattr(worker, "_preflight", lambda: pytest.fail("Must reject before database access"))
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 2


def test_live_command_is_denied_before_config_key_or_transport(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["worker", "--run-live"])
    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "private-sentinel-never-print")
    monkeypatch.setattr(worker, "_preflight", lambda: pytest.fail("Live command must not inspect database"))
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Base price estimates are insufficient" in captured.err
    assert "private-sentinel" not in captured.err + captured.out


@pytest.mark.parametrize("raw", [b"{}", b"not-json", b"x" * 65537])
def test_bad_allowance_rejects_before_preflight(tmp_path, monkeypatch, raw, capsys):
    path = tmp_path / "bad-allowance.json"
    path.write_bytes(raw)
    monkeypatch.setattr(sys, "argv", ["worker", "--run-simulated", "--allowance", str(path)])
    monkeypatch.setattr(worker, "_preflight", lambda: pytest.fail("Invalid allowance must not reach database"))
    with pytest.raises(SystemExit) as exc:
        worker.main()
    assert exc.value.code == 1
    assert "Worker command failed" in capsys.readouterr().err


def test_readonly_preflight_creates_no_storage_lock_or_allowance(runtime):
    absent = runtime.root / "uncreated-artifacts"
    result = command(runtime, "--check", overrides={"TAFFYBOP_ARTIFACT_ROOT": str(absent)})
    assert result.returncode == 0, result.stderr
    assert "preflight passed" in result.stdout
    assert not absent.exists() and not runtime.lock.exists() and not runtime.lock.parent.exists()
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.test_allowances").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM product.worker_executions").fetchone()["n"] == 0


def test_preflight_rejects_migration_drift_without_mutation(runtime):
    with runtime.database.connect() as conn:
        conn.execute("UPDATE product.schema_migrations SET sha256=%s WHERE version='003_test_allowance.sql'", ("0" * 64,))
    result = command(runtime, "--check")
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert not runtime.lock.exists()


def test_packaged_worker_restart_recovers_known_id_and_preserves_exhausted_allowance(runtime):
    jobs = [enqueue(runtime), enqueue(runtime, "dev-invoice-104.png")]
    path, allowance = allowance_file(runtime, jobs)
    first = command(runtime, "--run-simulated", "--allowance", str(path), "--steps", "1")
    assert first.returncode == 0, first.stderr
    accepted = json.loads(first.stdout)
    assert accepted["outcomes"] == {"accepted": 1}
    assert accepted["simulated_submit_calls"] == 1 and accepted["real_provider_http_calls"] == 0
    with runtime.database.connect() as conn:
        provider_id = conn.execute("SELECT provider_job_id FROM product.worker_executions WHERE job_id=%s", (jobs[0].id,)).fetchone()["provider_job_id"]
    second = command(runtime, "--run-simulated", "--allowance", str(path), "--steps", "3")
    assert second.returncode == 0, second.stderr
    recovered = json.loads(second.stdout)
    assert recovered["worker_pid"] != accepted["worker_pid"]
    assert recovered["outcomes"] == {"succeeded": 1, "idle": 2}
    assert recovered["simulated_submit_calls"] == 0 and recovered["simulated_poll_calls"] == 1
    persisted = runtime.repo.get_job(runtime.owner, jobs[0].id)
    raw = runtime.repo.read_artifact(runtime.owner, persisted.raw_response.id)
    assert json.loads(raw)["job"]["id"] == provider_id and json.loads(raw)["simulation"] is True
    assert runtime.repo.get_job(runtime.owner, jobs[1].id).status == "queued"
    totals = allowance_summary(runtime.database, allowance)
    assert totals["reserved_jobs"] == 1 and totals["reserved_pages"] == 10
    assert totals["reserved_credits"] == 30 and totals["reserved_usd"] == Decimal("0.045")
    assert persisted.usage.actual_credits is None


def test_packaged_worker_unknown_retains_capacity_and_allowance_across_fresh_process(runtime):
    jobs = [enqueue(runtime), enqueue(runtime, "dev-invoice-104.png")]
    path, allowance = allowance_file(runtime, jobs)
    first = command(runtime, "--run-simulated", "--allowance", str(path), "--steps", "1",
        "--simulation-outcome", "submission_unknown")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["outcomes"] == {"submission_unknown": 1}
    second = command(runtime, "--run-simulated", "--allowance", str(path), "--steps", "2")
    assert second.returncode == 0, second.stderr
    recovered = json.loads(second.stdout)
    assert recovered["outcomes"] == {"idle": 2} and recovered["simulated_submit_calls"] == 0
    assert runtime.repo.get_job(runtime.owner, jobs[0].id).status == "submission_unknown"
    assert runtime.repo.get_job(runtime.owner, jobs[1].id).status == "queued"
    assert allowance_summary(runtime.database, allowance)["reserved_jobs"] == 1
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.worker_executions WHERE capacity_slot=1").fetchone()["n"] == 1


def test_second_executable_cannot_dispatch_while_profile_lock_is_held(runtime):
    jobs = [enqueue(runtime)]
    path, _ = allowance_file(runtime, jobs)
    with LocalProviderLock("product_worker_local", runtime.lock):
        result = command(runtime, "--run-simulated", "--allowance", str(path), "--steps", "1")
        assert result.returncode == 1 and "Traceback" not in result.stderr
    assert runtime.repo.get_job(runtime.owner, jobs[0].id).status == "queued"
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.test_allowances").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM product.worker_executions").fetchone()["n"] == 0


@pytest.mark.parametrize("option,value", [("--steps", "0"), ("--steps", "1001"), ("--idle-seconds", "nan")])
def test_invalid_finite_run_bounds_have_no_admission_effect(runtime, option, value):
    path, _ = allowance_file(runtime, [enqueue(runtime)])
    result = command(runtime, "--run-simulated", "--allowance", str(path), option, value)
    assert result.returncode == 1 and not runtime.lock.exists()
    with runtime.database.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM product.test_allowances").fetchone()["n"] == 0
