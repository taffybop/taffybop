"""Local admission/fencing checks. Every provider transport is mocked."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

import app.llamaparse_api as api
from app.product.runtime_profile import (
    LocalProviderLock, RuntimeProfile, RuntimeProfileError,
    legacy_submission_enabled, require_legacy_submission,
)
from app.services.llamaparse_client import LlamaParseClient


@pytest.fixture
def path(monkeypatch, tmp_path):
    value = tmp_path / "admission/provider.lock"
    monkeypatch.setenv("TAFFYBOP_PROVIDER_LOCK_PATH", str(value))
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", "legacy_local")
    return value


def child_acquire(path, profile):
    source = """
from app.product.runtime_profile import LocalProviderLock, RuntimeProfileError
import sys
try:
    with LocalProviderLock(sys.argv[1], sys.argv[2]):
        print('acquired')
except RuntimeProfileError:
    print('denied')
    raise SystemExit(3)
"""
    return subprocess.run([sys.executable, "-c", source, profile, str(path)], capture_output=True, text=True, check=False)


def test_default_profile_preserves_local_legacy(monkeypatch):
    monkeypatch.delenv("TAFFYBOP_RUNTIME_PROFILE", raising=False)
    assert RuntimeProfile.from_env() is RuntimeProfile.LEGACY_LOCAL
    assert legacy_submission_enabled()


@pytest.mark.parametrize("value", ["", "production", "legacy", "PRODUCT_WORKER_LOCAL", " legacy_local", "../../secret"])
def test_invalid_profile_fails_closed(monkeypatch, value):
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", value)
    with pytest.raises(RuntimeProfileError) as error:
        RuntimeProfile.from_env()
    assert value not in str(error.value) if value else True
    assert not legacy_submission_enabled()
    with pytest.raises(RuntimeProfileError):
        require_legacy_submission()


@pytest.mark.parametrize("value", ["product_worker_local", "disabled", "bad-profile"])
def test_nonlegacy_api_has_disabled_config_and_rejects_before_upload_or_provider(path, monkeypatch, value):
    monkeypatch.setenv("TAFFYBOP_RUNTIME_PROFILE", value)
    calls = []
    app = FastAPI()
    app.state.llamaparse_service = api.LlamaParseService(LlamaParseClient(
        key_provider=lambda: "private-fake-key", transport=httpx.MockTransport(lambda request: calls.append(request)),
    ))
    app.include_router(api.router)
    with TestClient(app) as client:
        config = client.get("/v1/llamaparse/config")
        response = client.post("/v1/llamaparse/jobs", content=b"invalid-upload")
    assert config.json()["configured"] is True
    assert config.json()["submission_enabled"] is False
    assert "private-fake-key" not in config.text
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "provider_admission_unavailable"
    assert not calls and not path.exists()


@pytest.mark.parametrize("other", ["legacy_local", "product_worker_local"])
def test_separate_processes_cannot_overlap_legacy_holder(path, other):
    with LocalProviderLock("legacy_local", path):
        result = child_acquire(path, other)
        assert result.returncode == 3 and result.stdout.strip() == "denied"
    # No provider dispatch occurred, so handover is allowed after process release.
    result = child_acquire(path, "product_worker_local")
    assert result.returncode == 0 and result.stdout.strip() == "acquired"


def test_product_fence_survives_process_exit_and_allows_worker_restart(path):
    assert child_acquire(path, "product_worker_local").returncode == 0
    assert child_acquire(path, "legacy_local").returncode == 3
    assert child_acquire(path, "product_worker_local").returncode == 0
    value = json.loads(path.with_name(path.name + ".activity.json").read_text())
    assert value == {"version": 1, "product_owned": True, "legacy": {}}


def test_unknown_legacy_submission_survives_killed_process(path):
    source = """
from app.product.runtime_profile import LocalProviderLock
import sys
with LocalProviderLock('legacy_local', sys.argv[1]) as lock:
    lock.begin_legacy_submission()
    print('persisted', flush=True)
    sys.stdin.read()
"""
    process = subprocess.Popen([sys.executable, "-c", source, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "persisted"
        assert child_acquire(path, "product_worker_local").returncode == 3
        process.kill()
        process.communicate(timeout=10)
        assert child_acquire(path, "product_worker_local").returncode == 3
        # Legacy may continue under its own profile, preserving unknown activity.
        assert child_acquire(path, "legacy_local").returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_known_legacy_job_releases_handover_only_after_terminal_observation(path):
    with LocalProviderLock("legacy_local", path) as lock:
        identity = lock.begin_legacy_submission()
        lock.acknowledge_legacy_submission(identity, "provider-job")
        with pytest.raises(RuntimeProfileError):
            lock.finish_legacy_submission(identity, "wrong-job")
    assert child_acquire(path, "product_worker_local").returncode == 3
    with LocalProviderLock("legacy_local", path) as lock:
        lock.finish_legacy_submission(identity, "provider-job")
    assert child_acquire(path, "product_worker_local").returncode == 0


def test_legacy_api_keeps_raw_bytes_and_reconciles_activity_on_terminal_poll(path):
    raw = b'{ "job": {"id":"provider-job", "status":"COMPLETED"}, "unknown": [1,2] }\n'
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "provider-job", "status": "PENDING"})
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json"})
    app = FastAPI()
    service = api.LlamaParseService(LlamaParseClient(key_provider=lambda: "fake", transport=httpx.MockTransport(handler)))
    app.state.llamaparse_service = service
    app.include_router(api.router)
    source = Path(__file__).parent / "fixtures/parse_extract_v1/dev-invoice-104.pdf"
    with TestClient(app) as client:
        created = client.post("/v1/llamaparse/jobs", files={"file": ("sample.pdf", source.read_bytes(), "application/pdf")}, data={"mode": "cost_effective"})
        assert created.status_code == 202
        value = json.loads(service.admission.journal_path.read_text())
        assert len(value["legacy"]) == 1
        assert next(iter(value["legacy"].values())) == {"provider_id": "provider-job"}
        result = client.get("/v1/llamaparse/jobs/" + created.json()["job_id"])
        assert result.content == raw
        assert json.loads(service.admission.journal_path.read_text())["legacy"] == {}
    # Poll completion does not release the process-lifetime OS lock.
    assert child_acquire(path, "product_worker_local").returncode == 3


def test_legacy_api_submission_exception_keeps_unknown_activity(path):
    def handler(request):
        raise httpx.ReadTimeout("private transport details")
    app = FastAPI()
    service = api.LlamaParseService(LlamaParseClient(key_provider=lambda: "fake", transport=httpx.MockTransport(handler)))
    app.state.llamaparse_service = service
    app.include_router(api.router)
    source = Path(__file__).parent / "fixtures/parse_extract_v1/dev-invoice-104.pdf"
    with TestClient(app) as client:
        response = client.post("/v1/llamaparse/jobs", files={"file": ("sample.pdf", source.read_bytes(), "application/pdf")}, data={"mode": "cost_effective"})
    assert response.status_code == 504
    assert "private transport details" not in response.text
    assert next(iter(json.loads(service.admission.journal_path.read_text())["legacy"].values())) == {"provider_id": None}


@pytest.mark.parametrize("kind", ["lock_symlink", "parent_symlink", "lock_public", "parent_public", "journal_symlink", "journal_bad_json", "journal_public"])
def test_unsafe_lock_and_journal_paths_fail_closed(path, tmp_path, kind):
    path.parent.mkdir(mode=0o700)
    journal = path.with_name(path.name + ".activity.json")
    if kind == "parent_symlink":
        path.parent.rmdir()
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        path.parent.symlink_to(target, target_is_directory=True)
    elif kind == "parent_public":
        path.parent.chmod(0o755)
    elif kind == "lock_symlink":
        target = tmp_path / "target"
        target.write_text("")
        path.symlink_to(target)
    elif kind == "lock_public":
        path.touch(mode=0o644)
    elif kind == "journal_symlink":
        target = tmp_path / "target"
        target.write_text("{}")
        journal.symlink_to(target)
    else:
        journal.write_text("not-json" if kind == "journal_bad_json" else '{}')
        journal.chmod(0o644 if kind == "journal_public" else 0o600)
    with pytest.raises(RuntimeProfileError):
        LocalProviderLock("product_worker_local", path).acquire()


def test_lock_inode_replacement_prevents_dispatch(path):
    with LocalProviderLock("legacy_local", path) as lock:
        path.unlink()
        path.touch(mode=0o600)
        with pytest.raises(RuntimeProfileError):
            lock.begin_legacy_submission()


def test_relative_lock_path_is_rejected():
    with pytest.raises(RuntimeProfileError):
        LocalProviderLock("legacy_local", "relative/provider.lock")


def test_missing_lock_path_prevents_cached_legacy_dispatch(path):
    lock = require_legacy_submission()
    path.unlink()
    with pytest.raises(RuntimeProfileError):
        require_legacy_submission()
    lock.close()


def test_inherited_lock_identity_cannot_dispatch_under_a_different_pid(path, monkeypatch):
    with LocalProviderLock("legacy_local", path) as lock:
        # Forked children must not reuse a process-global admission capability.
        monkeypatch.setattr("app.product.runtime_profile.os.getpid", lambda: -1)
        with pytest.raises(RuntimeProfileError):
            lock.begin_legacy_submission()
