"""Separate product worker with an explicitly simulated, finite local runner.

Live execution stays closed until account conditions and enforceable provider
charge bounds are verified. Simulation never consults a key or network transport.
"""

import argparse
import asyncio
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import random

import psycopg
from pydantic import ValidationError

from app.product.allowance import AllowanceError, TestAllowance, allowance_summary, register_allowance
from app.product.database import Database, MigrationError
from app.product.lifecycle import StaleClaim, WorkerRepository
from app.product.provider import ParseProvider, ProviderError
from app.product.repository import ProductRepository, ResourceNotFound
from app.product.runtime_profile import LocalProviderLock, RuntimeProfile, RuntimeProfileError
from app.product.simulated_provider import SIMULATION_OUTCOMES, SimulatedParseProvider
from app.product.storage import ArtifactStorageError, LocalArtifactStore


class Worker:
    def __init__(self, repository: WorkerRepository, provider: ParseProvider):
        self.repository = repository
        self.provider = provider

    async def step(self) -> str:
        """Private injected-dispatch step; process runners must hold admission."""
        claim = self.repository.claim()
        if claim is None:
            return "idle"
        if claim.provider_job_id is None:
            try:
                document, data = self.repository.source(claim)
            except (ResourceNotFound, ArtifactStorageError, OSError):
                self.repository.reject(claim, pause=True)
                return "source_unavailable"
            try:
                submission = await self.provider.submit(data, document.display_name, document.source.media_type, claim.job.settings)
            except ProviderError as exc:
                if exc.ambiguous:
                    self.repository.unknown(claim)
                    return "submission_unknown"
                # Stop backlog admission on definitive rejection. An operator
                # must address configuration/credits; no automatic POST retry.
                self.repository.reject(claim, pause=True)
                return "submission_rejected"
            except BaseException:
                # Includes task cancellation after send. A killed process is
                # recovered by lease expiry into the same uncertain state.
                self.repository.unknown(claim)
                raise
            self.repository.accepted(claim, submission.provider_job_id)
            return "accepted"
        try:
            observation = await self.provider.poll(claim.provider_job_id)
        except ProviderError:
            self.repository.poll_later(claim, error=True, delay_seconds=random.uniform(2, 5))
            return "poll_unavailable"
        if observation.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            completed = self.repository.complete(claim, observation)
            return completed.status
        if observation.status not in {"PENDING", "RUNNING"}:
            self.repository.poll_later(claim, error=True)
            return "poll_unavailable"
        self.repository.poll_later(claim, delay_seconds=random.uniform(3, 7))
        return "running"

    async def run(self, *, idle_seconds: float = 1):
        if not 0.1 <= idle_seconds <= 30:
            raise ValueError("Invalid worker idle interval")
        if RuntimeProfile.from_env() is not RuntimeProfile.PRODUCT_WORKER_LOCAL:
            raise RuntimeProfileError()
        with LocalProviderLock(RuntimeProfile.PRODUCT_WORKER_LOCAL):
            while True:
                try:
                    await self.step()
                except StaleClaim:
                    # A stale worker cannot overwrite a later claim or free a slot.
                    pass
                await asyncio.sleep(idle_seconds)


def _preflight():
    if RuntimeProfile.from_env() is not RuntimeProfile.PRODUCT_WORKER_LOCAL:
        raise RuntimeProfileError()
    dsn = os.environ.get("TAFFYBOP_DATABASE_URL")
    storage_root = os.environ.get("TAFFYBOP_ARTIFACT_ROOT")
    if not dsn or not storage_root or not Path(storage_root).is_absolute():
        raise ValueError("Private database URL and absolute artifact root are required")
    database = Database(dsn)
    # Read-only verification, including checksums; no implicit migrations,
    # storage creation, allowance registration or profile-journal mutations.
    with database.connect() as conn:
        installed = {row["version"]: row["sha256"] for row in conn.execute(
            "SELECT version,sha256 FROM product.schema_migrations")}
        expected = {path.name: sha256(path.read_bytes()).hexdigest()
                    for path in Path(__file__).with_name("migrations").glob("[0-9][0-9][0-9]_*.sql")}
        if not expected or installed != expected:
            raise MigrationError("Apply and verify product migrations explicitly")
        for table in ("worker_executions", "test_allowances", "test_allowance_reservations"):
            if conn.execute("SELECT to_regclass(%s) AS name", ("product." + table,)).fetchone()["name"] is None:
                raise MigrationError("Required worker table is missing")
    return database, Path(storage_root)


async def run_simulated(database, storage_root, allowance, *, steps=4, idle_seconds=0.1, outcome="completed"):
    """Bounded packaged dispatch, with lock and durable admission before work."""
    if type(steps) is not int or not 1 <= steps <= 1000 or not 0.1 <= idle_seconds <= 30:
        raise ValueError("Invalid finite worker interval or step count")
    if RuntimeProfile.from_env() is not RuntimeProfile.PRODUCT_WORKER_LOCAL:
        raise RuntimeProfileError()
    allowance = TestAllowance.model_validate(allowance.model_dump())
    provider = SimulatedParseProvider(outcome)
    with LocalProviderLock(RuntimeProfile.PRODUCT_WORKER_LOCAL):
        register_allowance(database, allowance)
        repository = WorkerRepository(ProductRepository(database, LocalArtifactStore(storage_root)), allowance=allowance)
        worker = Worker(repository, provider)
        outcomes = Counter()
        for index in range(steps):
            try:
                outcomes[await worker.step()] += 1
            except StaleClaim:
                outcomes["stale_claim"] += 1
            if index + 1 < steps:
                await asyncio.sleep(idle_seconds)
        return {"evidence_kind": "authored simulation only; not a live parse", "worker_pid": os.getpid(),
            "steps": steps, "outcomes": dict(outcomes), "simulated_submit_calls": provider.submissions,
            "simulated_poll_calls": provider.polls, "real_provider_http_calls": 0,
            "allowance": allowance_summary(database, allowance)}


def main():
    parser = argparse.ArgumentParser(description="Private product-worker preflight or bounded simulation (live calls disabled)")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--run-simulated", action="store_true")
    action.add_argument("--run-live", action="store_true", help="Unavailable until account conditions and hard charge bounds are verified")
    parser.add_argument("--allowance", type=Path, help="Explicit finite simulated allowance JSON")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--idle-seconds", type=float, default=0.1)
    parser.add_argument("--simulation-outcome", choices=SIMULATION_OUTCOMES, default="completed")
    args = parser.parse_args()
    if args.run_live:
        parser.exit(2, "Live execution is unavailable: verify account/free-credit conditions and enforceable credit/USD charge bounds first. Base price estimates are insufficient.\n")
    if args.check and args.allowance is not None:
        parser.error("--allowance belongs to --run-simulated")
    if args.run_simulated and args.allowance is None:
        parser.error("--run-simulated requires --allowance")
    try:
        allowance = None
        if args.run_simulated:
            # Bound input even for a mistakenly selected large local file.
            with args.allowance.open("rb") as handle:
                raw = handle.read(65537)
            if len(raw) > 65536:
                raise ValueError("Allowance file exceeds limit")
            allowance = TestAllowance.model_validate_json(raw)
            if not 1 <= args.steps <= 1000 or not 0.1 <= args.idle_seconds <= 30:
                raise ValueError("Invalid finite runner bounds")
        database, storage_root = _preflight()
        if args.check:
            print("Product worker profile/database preflight passed; storage, allowance and admission lock not exercised. Live execution disabled.")
        else:
            result = asyncio.run(run_simulated(database, storage_root, allowance, steps=args.steps,
                idle_seconds=args.idle_seconds, outcome=args.simulation_outcome))
            print(json.dumps(result, default=str, sort_keys=True))
    except (psycopg.Error, MigrationError, RuntimeProfileError, AllowanceError, ArtifactStorageError,
            OSError, ValueError, ValidationError):
        parser.exit(1, "Worker command failed; inspect private profile/database/storage and finite simulated allowance configuration.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Worker stopped; durable capacity and allowance reservations are retained.\n")


if __name__ == "__main__":
    main()
