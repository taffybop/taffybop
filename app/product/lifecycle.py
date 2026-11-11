"""Private durable provider lifecycle. All claims are fenced; no network here.

One global provider slot is intentionally shared across every owner. A lease is
permission to write, never evidence that the upstream job has stopped. Unknown
submission retains the slot indefinitely, pending operator reconciliation.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import UUID, uuid4

from app.product.allowance import AllowanceError, TestAllowance, registered_allowance, reserve_allowance, validated_allowance
from app.product.contracts import Artifact, Job, ParseResult, PublicError, Usage
from app.product.repository import ProductRepository, PersistenceConflict, ResourceNotFound, _json, _owner, _reject_json_constant


class StaleClaim(PersistenceConflict):
    def __init__(self):
        super().__init__("Worker claim is no longer current")


@dataclass(frozen=True)
class Claim:
    job: Job
    owner: str
    token: UUID
    provider_job_id: str | None


class WorkerRepository:
    def __init__(self, repository: ProductRepository, *, lease_seconds: int = 180,
                 allowance: TestAllowance | None = None):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("Invalid lease duration")
        self.repository = repository
        self.database = repository.database
        self.lease_seconds = lease_seconds
        self.allowance = validated_allowance(allowance) if allowance is not None else None

    @staticmethod
    def _serialize(conn):
        conn.execute("SELECT pg_advisory_xact_lock(729041, 103)")

    @staticmethod
    def _job(conn, identity):
        row = conn.execute("SELECT * FROM product.jobs WHERE id=%s FOR UPDATE", (identity,)).fetchone()
        return row, Job.model_validate(row["payload"])

    @staticmethod
    def _update_job(conn, job):
        conn.execute("UPDATE product.jobs SET payload=%s,result_id=%s,raw_artifact_id=%s WHERE id=%s",
                     (_json(job), job.result_id, job.raw_response.id if job.raw_response else None, job.id))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def _allowance_domain(self, conn, job_id):
        reservation = conn.execute("SELECT allowance_id FROM product.test_allowance_reservations WHERE job_id=%s", (job_id,)).fetchone()
        if self.allowance is None:
            if reservation is not None:
                raise AllowanceError()
        else:
            registered_allowance(conn, self.allowance)
            if reservation is None or reservation["allowance_id"] != self.allowance.id:
                raise AllowanceError()

    def claim(self) -> Claim | None:
        """Commit submission intent before returning a new job; resume only IDs."""
        with self.database.connect() as conn:
            self._serialize(conn)
            if self.allowance is not None:
                registered_allowance(conn, self.allowance)
            active = conn.execute("SELECT * FROM product.worker_executions WHERE capacity_slot=1 FOR UPDATE").fetchone()
            if active:
                # Expiry/exhaustion never blocks recovery, but an execution may
                # only be recovered by its original simulated allowance domain.
                self._allowance_domain(conn, active["job_id"])
                due = conn.execute("SELECT (%s::timestamptz <= clock_timestamp()) AND (%s::timestamptz IS NULL OR %s::timestamptz <= clock_timestamp()) AS due",
                    (active["next_poll_at"], active["lease_until"], active["lease_until"])).fetchone()["due"]
                if not due:
                    return None
                row, job = self._job(conn, active["job_id"])
                if active["provider_job_id"] is None:
                    if job.status == "submitting":
                        now = max(self._now(), job.updated_at)
                        job = Job.model_validate({**job.model_dump(), "status": "submission_unknown", "updated_at": now})
                        self._update_job(conn, job)
                        conn.execute("UPDATE product.worker_executions SET claim_token=NULL,lease_until=NULL WHERE job_id=%s", (job.id,))
                    return None
                token = uuid4()
                conn.execute("UPDATE product.worker_executions SET claim_token=%s,lease_until=clock_timestamp() + %s * interval '1 second' WHERE job_id=%s",
                             (token, self.lease_seconds, job.id))
                return Claim(job, row["owner_key"], token, active["provider_job_id"])
            control = conn.execute("SELECT admission_paused FROM product.worker_control WHERE singleton").fetchone()
            if control["admission_paused"]:
                return None
            # Lock the source before the job, like the owner-facing repository.
            allowed = ""
            parameters = ()
            if self.allowance is not None:
                allowed = " AND j.id = ANY(%s::uuid[]) AND j.payload->'settings'=%s"
                parameters = (list(self.allowance.job_ids), _json(self.allowance.settings))
            row = conn.execute("""SELECT j.id,j.owner_key FROM product.jobs j JOIN product.documents d
                ON d.id=j.document_id WHERE j.payload->>'status'='queued' AND d.state='active'
                AND (d.expires_at IS NULL OR d.expires_at > clock_timestamp())
                """ + allowed + " ORDER BY j.payload->>'created_at',j.id LIMIT 1 FOR UPDATE OF d,j", parameters).fetchone()
            if row is None:
                return None
            _, job = self._job(conn, row["id"])
            if self.allowance is not None and not reserve_allowance(conn, self.allowance, job):
                return None
            token = uuid4()
            now = max(self._now(), job.updated_at)
            job = Job.model_validate({**job.model_dump(), "status": "submitting", "started_at": now, "updated_at": now})
            conn.execute("""INSERT INTO product.worker_executions(job_id,capacity_slot,claim_token,lease_until)
                VALUES (%s,1,%s,clock_timestamp() + %s * interval '1 second')""", (job.id, token, self.lease_seconds))
            self._update_job(conn, job)
            return Claim(job, row["owner_key"], token, None)

    def _fenced(self, conn, claim):
        self._serialize(conn)
        execution = conn.execute("""SELECT * FROM product.worker_executions WHERE job_id=%s
            AND claim_token=%s AND lease_until > clock_timestamp() AND capacity_slot=1 FOR UPDATE""",
            (claim.job.id, claim.token)).fetchone()
        if execution is None:
            raise StaleClaim()
        self._allowance_domain(conn, claim.job.id)
        row, job = self._job(conn, claim.job.id)
        return execution, row, job

    def source(self, claim: Claim):
        """Validate current claim and active source immediately before create."""
        with self.database.connect() as conn:
            _, _, job = self._fenced(conn, claim)
            document = self.repository._document_model(self.repository._document(conn, claim.owner, job.document_id, lock=True))
            data = self.repository.storage.get(document.source.id, sha256=document.source.sha256, size_bytes=document.source.size_bytes)
            return document, data

    def accepted(self, claim: Claim, provider_job_id: str):
        if not isinstance(provider_job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", provider_job_id) is None:
            raise ValueError("Invalid provider job identity")
        with self.database.connect() as conn:
            execution, _, job = self._fenced(conn, claim)
            if execution["provider_job_id"] is not None or job.status != "submitting":
                raise PersistenceConflict("Job was already submitted")
            now = max(self._now(), job.updated_at)
            status = "cancel_requested" if job.cancellation_requested_at else "running"
            self._update_job(conn, Job.model_validate({**job.model_dump(), "status": status, "updated_at": now}))
            conn.execute("UPDATE product.worker_executions SET provider_job_id=%s,claim_token=NULL,lease_until=NULL WHERE job_id=%s", (provider_job_id, job.id))

    def unknown(self, claim: Claim):
        with self.database.connect() as conn:
            execution, _, job = self._fenced(conn, claim)
            if execution["provider_job_id"] is not None or job.status != "submitting":
                raise PersistenceConflict("Only submitting jobs can become uncertain")
            now = max(self._now(), job.updated_at)
            self._update_job(conn, Job.model_validate({**job.model_dump(), "status": "submission_unknown", "updated_at": now}))
            conn.execute("UPDATE product.worker_executions SET claim_token=NULL,lease_until=NULL WHERE job_id=%s", (job.id,))

    def request_cancel(self, owner: str, job_id: UUID) -> Job:
        """Queued cancellation is local; accepted/unknown work keeps its slot.

        There is no upstream cancellation endpoint in this adapter. A request
        therefore keeps polling known IDs until the provider reports terminal.
        """
        owner = _owner(owner)
        with self.database.connect() as conn:
            self._serialize(conn)
            row = conn.execute("SELECT document_id FROM product.jobs WHERE owner_key=%s AND id=%s", (owner, job_id)).fetchone()
            if row is None:
                raise ResourceNotFound()
            self.repository._document(conn, owner, row["document_id"], lock=True)
            _, job = self._job(conn, job_id)
            if job.status in {"succeeded", "failed", "cancelled"} or job.cancellation_requested_at:
                return job
            now = max(self._now(), job.updated_at)
            values = {**job.model_dump(), "cancellation_requested_at": now, "updated_at": now}
            if job.status == "queued":
                values.update(status="cancelled", finished_at=now, cancellation_confirmed=True)
            elif job.status == "running":
                values.update(status="cancel_requested")
            # Submitting/unknown retain truthful uncertainty until an ID or
            # terminal response exists; a request is never a confirmation.
            updated = Job.model_validate(values)
            self._update_job(conn, updated)
            return updated

    def poll_later(self, claim: Claim, *, error: bool = False, delay_seconds: float = 5):
        if not 0 <= delay_seconds <= 300:
            raise ValueError("Invalid poll delay")
        with self.database.connect() as conn:
            execution, _, job = self._fenced(conn, claim)
            if execution["provider_job_id"] is None:
                raise PersistenceConflict("Polling requires a provider identity")
            failures = execution["poll_failures"] + 1 if error else 0
            # Persist bounded exponential backoff. Jitter is supplied by worker.
            delay = min(300, max(delay_seconds, 2 ** min(failures, 8))) if error else delay_seconds
            conn.execute("""UPDATE product.worker_executions SET claim_token=NULL,lease_until=NULL,
                next_poll_at=clock_timestamp() + %s * interval '1 second',poll_failures=%s,last_poll_error=%s WHERE job_id=%s""",
                (delay, failures, "provider_poll_unavailable" if error else None, job.id))

    def reject(self, claim: Claim, *, pause: bool = False):
        """A definite pre-acceptance rejection; uncertain outcomes use unknown()."""
        with self.database.connect() as conn:
            execution, _, job = self._fenced(conn, claim)
            if execution["provider_job_id"] is not None or job.status != "submitting":
                raise PersistenceConflict("Accepted jobs require terminal provider evidence")
            now = max(self._now(), job.updated_at)
            self._update_job(conn, Job.model_validate({**job.model_dump(), "status": "failed", "updated_at": now, "finished_at": now,
                "error": PublicError(code="provider_submission_rejected", message="The provider submission was rejected.")}))
            conn.execute("UPDATE product.worker_executions SET capacity_slot=NULL,claim_token=NULL,lease_until=NULL WHERE job_id=%s", (job.id,))
            if pause:
                conn.execute("UPDATE product.worker_control SET admission_paused=true,pause_reason='provider_submission_rejected' WHERE singleton")

    def complete(self, claim: Claim, observation) -> Job:
        """Atomically publish exact terminal bytes/results and release capacity."""
        if observation.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("Terminal provider evidence is required")
        raw = observation.raw
        if not isinstance(raw, bytes) or not raw:
            raise PersistenceConflict("Terminal raw response is required")
        try:
            raw_value = json.loads(raw, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError) as exc:
            raise PersistenceConflict("Terminal raw response must be JSON") from exc
        with self.database.connect() as conn:
            execution, row, job = self._fenced(conn, claim)
            if execution["provider_job_id"] is None or job.status not in {"running", "cancel_requested"}:
                raise PersistenceConflict("Terminal capture requires an accepted job")
            raw_job = raw_value.get("job") if isinstance(raw_value, dict) else None
            if (not isinstance(raw_job, dict) or raw_job.get("id") != execution["provider_job_id"]
                    or raw_job.get("status") != observation.status):
                raise PersistenceConflict("Terminal raw response does not match the accepted job")
            artifact = Artifact(id=uuid4(), sha256=sha256(raw).hexdigest(), size_bytes=len(raw), media_type="application/json")
            self.repository.storage.put(artifact.id, raw)
            # Large/fsynced writes can outlive a lease. Do not publish using an
            # expired capability even when no replacement worker claimed yet.
            self._fenced(conn, claim)
            self.repository._insert_artifact(conn, row["owner_key"], job.document_id, artifact)
            now = max(self._now(), job.updated_at)
            usage = Usage(estimated_credits=job.usage.estimated_credits, estimate_price_version=job.usage.estimate_price_version,
                          actual_credits=observation.usage.actual_credits, reconciliation=observation.usage.reconciliation)
            values = {**job.model_dump(), "updated_at": now, "finished_at": now, "raw_response": artifact, "usage": usage}
            if observation.status == "COMPLETED":
                result = ParseResult(id=uuid4(), document_id=job.document_id, job_id=job.id, created_at=now,
                    settings=job.settings, provider_version=observation.provider_version, raw=artifact,
                    markdown=observation.markdown, text=observation.text, warnings=observation.warnings, usage=usage)
                conn.execute("""INSERT INTO product.parse_results(id,owner_key,document_id,job_id,raw_artifact_id,payload)
                    VALUES (%s,%s,%s,%s,%s,%s)""", (result.id,row["owner_key"],job.document_id,job.id,artifact.id,_json(result)))
                values.update(status="succeeded", result_id=result.id)
            elif observation.status == "FAILED":
                values.update(status="failed", error=PublicError(code="provider_parse_failed", message="The provider could not parse this document."))
            else:
                values.update(status="cancelled", cancellation_confirmed=True)
            completed = Job.model_validate(values)
            self._update_job(conn, completed)
            conn.execute("UPDATE product.worker_executions SET capacity_slot=NULL,claim_token=NULL,lease_until=NULL WHERE job_id=%s", (job.id,))
            return completed
