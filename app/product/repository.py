"""Owner-scoped PX1 persistence, deliberately not registered as HTTP routes.

Owners are trusted server-derived principals, not request-body fields. Storage
is private: every read first checks the document's owner, tombstone and expiry.
Bytes are durably published before database references commit. A crash between
those steps can leave an unreferenced immutable file, never an accepted missing
artifact; garbage collection is a later retention concern.
"""

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.product.contracts import Artifact, Document, Job, ParseResult, ParseSettings, Usage
from app.product.database import Database
from app.product.storage import LocalArtifactStore


class ResourceNotFound(LookupError):
    def __init__(self):
        super().__init__("Resource not found")


class IdempotencyConflict(ValueError):
    pass


class PersistenceConflict(ValueError):
    pass


def _owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner or len(owner) > 200 or any(
        not c.isprintable() for c in owner
    ):
        raise ValueError("Invalid server principal")
    return owner


def _json(model):
    return Jsonb(model.model_dump(mode="json"))


def _reject_json_constant(value: str):
    raise ValueError("Non-finite JSON constant")


class ProductRepository:
    def __init__(self, database: Database, storage: LocalArtifactStore):
        self.database = database
        self.storage = storage

    @staticmethod
    def _document(conn, owner: str, document_id: UUID, *, lock: bool = False):
        row = conn.execute(
            """SELECT d.*, a.sha256, a.size_bytes, a.media_type
               FROM product.documents d JOIN product.artifacts a
               ON (a.owner_key, a.document_id, a.id) =
                  (d.owner_key, d.id, d.source_artifact_id)
               WHERE d.owner_key = %s AND d.id = %s AND d.state = 'active'
               AND (d.expires_at IS NULL OR d.expires_at > clock_timestamp())"""
            + (" FOR UPDATE OF d" if lock else ""),
            (owner, document_id),
        ).fetchone()
        if row is None:
            raise ResourceNotFound()
        return row

    @staticmethod
    def _document_model(row) -> Document:
        # A PostgreSQL session's timezone must not change a document's public
        # timestamp representation between upload and subsequent list/reopen.
        def utc(value):
            return value.astimezone(timezone.utc) if value is not None else None
        return Document(
            id=row["id"], display_name=row["display_name"],
            page_count=row["page_count"], created_at=utc(row["created_at"]),
            expires_at=utc(row["expires_at"]), state=row["state"], deleted_at=utc(row["deleted_at"]),
            source=Artifact(id=row["source_artifact_id"], sha256=row["sha256"],
                            size_bytes=row["size_bytes"], media_type=row["media_type"]),
        )

    @staticmethod
    def _insert_artifact(conn, owner: str, document_id: UUID, artifact: Artifact):
        conn.execute(
            """INSERT INTO product.artifacts
               (id, owner_key, document_id, sha256, size_bytes, media_type)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (artifact.id, owner, document_id, artifact.sha256,
             artifact.size_bytes, artifact.media_type),
        )

    def create_document(self, owner: str, *, display_name: str, media_type: str,
                        data: bytes, page_count: int,
                        expires_at: datetime | None = None) -> Document:
        owner = _owner(owner)
        # Intake type/page/pixel detection remains the API validator's duty.
        # This trusted repository enforces the frozen metadata/size contracts.
        if not isinstance(data, bytes):
            raise TypeError("Document data must be bytes")
        document = Document(
            id=uuid4(), display_name=display_name, page_count=page_count,
            created_at=datetime.now(timezone.utc), expires_at=expires_at,
            source=Artifact(id=uuid4(), sha256=sha256(data).hexdigest(),
                            size_bytes=len(data), media_type=media_type),
        )
        self.storage.put(document.source.id, data)
        with self.database.connect() as conn:
            conn.execute("INSERT INTO product.owners(owner_key) VALUES (%s) ON CONFLICT DO NOTHING", (owner,))
            conn.execute(
                """INSERT INTO product.documents
                   (id,owner_key,display_name,page_count,created_at,expires_at,state,source_artifact_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (document.id, owner, document.display_name, page_count,
                 document.created_at, expires_at, document.state, document.source.id),
            )
            self._insert_artifact(conn, owner, document.id, document.source)
        return document

    def get_document(self, owner: str, document_id: UUID) -> Document:
        with self.database.connect() as conn:
            return self._document_model(self._document(conn, _owner(owner), document_id))

    def list_documents(self, owner: str, *, limit: int = 25,
                       before: tuple[datetime, UUID] | None = None) -> tuple[Document, ...]:
        owner = _owner(owner)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("List limit must be between 1 and 100")
        params = [owner]
        cursor_clause = ""
        if before is not None:
            created_at, identity = before
            if created_at.tzinfo is None or not isinstance(identity, UUID):
                raise ValueError("Invalid document cursor")
            cursor_clause = " AND (d.created_at, d.id) < (%s, %s)"
            params.extend((created_at, identity))
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                """SELECT d.*, a.sha256, a.size_bytes, a.media_type
                   FROM product.documents d JOIN product.artifacts a
                   ON (a.owner_key,a.document_id,a.id) = (d.owner_key,d.id,d.source_artifact_id)
                   WHERE d.owner_key=%s AND d.state='active'
                   AND (d.expires_at IS NULL OR d.expires_at > clock_timestamp())"""
                + cursor_clause + " ORDER BY d.created_at DESC, d.id DESC LIMIT %s", params,
            ).fetchall()
            return tuple(self._document_model(row) for row in rows)

    def enqueue_parse(self, owner: str, document_id: UUID, *, idempotency_key: str,
                      settings: ParseSettings, usage: Usage | None = None) -> Job:
        owner = _owner(owner)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128 or any(
            not 32 <= ord(c) <= 126 for c in idempotency_key
        ):
            raise ValueError("Invalid idempotency key")
        # Copy/revalidate to reject invalid model_construct() inputs at this boundary.
        settings = ParseSettings.model_validate(settings.model_dump(mode="json"))
        now = datetime.now(timezone.utc)
        job = Job(id=uuid4(), document_id=document_id, status="queued", settings=settings,
                  created_at=now, updated_at=now, usage=usage or Usage())
        with self.database.connect() as conn:
            document = self._document(conn, owner, document_id, lock=True)
            if document["page_count"] > settings.max_pages:
                raise ValueError("Document exceeds configured page limit")
            inserted = conn.execute(
                """INSERT INTO product.jobs(id,owner_key,document_id,idempotency_key,payload)
                   VALUES (%s,%s,%s,%s,%s) ON CONFLICT (owner_key,idempotency_key)
                   DO NOTHING RETURNING id""",
                (job.id, owner, document_id, idempotency_key, _json(job)),
            ).fetchone()
            if inserted:
                return job
            existing = Job.model_validate(conn.execute(
                "SELECT payload FROM product.jobs WHERE owner_key=%s AND idempotency_key=%s",
                (owner, idempotency_key),
            ).fetchone()["payload"])
            if existing.document_id != document_id or existing.settings != settings:
                raise IdempotencyConflict("Idempotency key already has different input")
            return existing

    def get_job(self, owner: str, job_id: UUID) -> Job:
        owner = _owner(owner)
        with self.database.connect() as conn:
            row = conn.execute("SELECT document_id,payload FROM product.jobs WHERE owner_key=%s AND id=%s",
                               (owner, job_id)).fetchone()
            if row is None:
                raise ResourceNotFound()
            self._document(conn, owner, row["document_id"])
            return Job.model_validate(row["payload"])

    def save_parse_result(self, owner: str, result: ParseResult, raw: bytes) -> ParseResult:
        """Trusted unadmitted storage capture; fixtures do not imply a live parse.

        Admitted jobs must use the fenced worker lifecycle. This transaction
        persists validated immutable captures only for unadmitted intents.
        """
        owner = _owner(owner)
        result = ParseResult.model_validate(result.model_dump(mode="json"))
        if not isinstance(raw, bytes) or len(raw) != result.raw.size_bytes or sha256(raw).hexdigest() != result.raw.sha256:
            raise PersistenceConflict("Raw artifact does not match capture metadata")
        try:
            # Validate syntax only. Store and download the original bytes,
            # including whitespace, key order and unknown provider fields.
            json.loads(raw, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError) as exc:
            raise PersistenceConflict("Raw capture must contain valid JSON") from exc
        with self.database.connect() as conn:
            # Storage fixtures may capture unadmitted jobs. Once worker intent
            # exists, only the fenced lifecycle may publish terminal output.
            conn.execute("SELECT pg_advisory_xact_lock(729041, 103)")
            if conn.execute("SELECT 1 FROM product.worker_executions WHERE job_id=%s", (result.job_id,)).fetchone():
                raise PersistenceConflict("Admitted jobs require a current worker claim")
            self._document(conn, owner, result.document_id, lock=True)
            row = conn.execute(
                "SELECT payload FROM product.jobs WHERE owner_key=%s AND document_id=%s AND id=%s FOR UPDATE",
                (owner, result.document_id, result.job_id),
            ).fetchone()
            if row is None:
                raise ResourceNotFound()
            job = Job.model_validate(row["payload"])
            if job.settings != result.settings or result.created_at < job.created_at:
                raise PersistenceConflict("Result does not match job intent")
            existing = conn.execute("SELECT payload FROM product.parse_results WHERE job_id=%s", (job.id,)).fetchone()
            if existing:
                if ParseResult.model_validate(existing["payload"]) != result:
                    raise PersistenceConflict("Job already has an immutable result")
                # Verify exact stored bytes too, rather than trusting metadata alone.
                if self.storage.get(result.raw.id, sha256=result.raw.sha256, size_bytes=result.raw.size_bytes) != raw:
                    raise PersistenceConflict("Result bytes differ")
                return result
            if job.status in {"succeeded", "failed", "cancelled", "submission_unknown"}:
                raise PersistenceConflict("Job is not eligible for successful capture")
            self.storage.put(result.raw.id, raw)
            self._insert_artifact(conn, owner, result.document_id, result.raw)
            conn.execute(
                """INSERT INTO product.parse_results
                   (id,owner_key,document_id,job_id,raw_artifact_id,payload) VALUES (%s,%s,%s,%s,%s,%s)""",
                (result.id, owner, result.document_id, job.id, result.raw.id, _json(result)),
            )
            finished = max(datetime.now(timezone.utc), result.created_at, job.updated_at)
            completed = Job.model_validate({
                **job.model_dump(), "status": "succeeded", "result_id": result.id,
                "raw_response": result.raw, "started_at": job.started_at or job.created_at,
                "finished_at": finished, "updated_at": finished, "usage": result.usage,
            })
            conn.execute("UPDATE product.jobs SET result_id=%s,raw_artifact_id=%s,payload=%s WHERE id=%s",
                         (result.id, result.raw.id, _json(completed), job.id))
        return result

    def get_parse_result(self, owner: str, result_id: UUID) -> ParseResult:
        owner = _owner(owner)
        with self.database.connect() as conn:
            row = conn.execute("SELECT document_id,payload FROM product.parse_results WHERE owner_key=%s AND id=%s",
                               (owner, result_id)).fetchone()
            if row is None:
                raise ResourceNotFound()
            self._document(conn, owner, row["document_id"])
            return ParseResult.model_validate(row["payload"])

    def read_artifact(self, owner: str, artifact_id: UUID) -> bytes:
        owner = _owner(owner)
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM product.artifacts WHERE owner_key=%s AND id=%s",
                               (owner, artifact_id)).fetchone()
            if row is None:
                raise ResourceNotFound()
            # Lock against a concurrent tombstone until bytes have been read.
            self._document(conn, owner, row["document_id"], lock=True)
            return self.storage.get(artifact_id, sha256=row["sha256"], size_bytes=row["size_bytes"])

    def list_document_jobs(self, owner: str, document_id: UUID) -> tuple[tuple[Job, str], ...]:
        """Bounded durable history; only an immutable allowance proves simulation.

        Old authored captures have no provider qualification evidence and remain
        unverified. No response content is inspected to infer a successful live run.
        """
        owner = _owner(owner)
        with self.database.connect() as conn:
            self._document(conn, owner, document_id)
            rows = conn.execute(
                """SELECT j.payload, r.job_id IS NOT NULL AS simulated
                   FROM product.jobs j LEFT JOIN product.test_allowance_reservations r
                   ON r.job_id=j.id WHERE j.owner_key=%s AND j.document_id=%s
                   ORDER BY (j.payload->>'created_at')::timestamptz DESC,j.id DESC LIMIT 100""",
                (owner, document_id),
            ).fetchall()
            return tuple((Job.model_validate(row["payload"]),
                          "simulation" if row["simulated"] else "unverified") for row in rows)

    def job_evidence_kind(self, owner: str, job_id: UUID) -> str:
        owner = _owner(owner)
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT j.document_id,r.job_id IS NOT NULL AS simulated FROM product.jobs j
                   LEFT JOIN product.test_allowance_reservations r ON r.job_id=j.id
                   WHERE j.owner_key=%s AND j.id=%s""", (owner, job_id),
            ).fetchone()
            if row is None:
                raise ResourceNotFound()
            self._document(conn, owner, row["document_id"])
            return "simulation" if row["simulated"] else "unverified"

    def download_artifact(self, owner: str, artifact_id: UUID) -> tuple[Artifact, str, bytes, str]:
        """Authorize metadata and exact-byte read under the document's lock."""
        owner = _owner(owner)
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM product.artifacts WHERE owner_key=%s AND id=%s",
                               (owner, artifact_id)).fetchone()
            if row is None:
                raise ResourceNotFound()
            document = self._document(conn, owner, row["document_id"], lock=True)
            artifact = Artifact(id=row["id"], sha256=row["sha256"], size_bytes=row["size_bytes"], media_type=row["media_type"])
            data = self.storage.get(artifact_id, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
            evidence = "source"
            filename = document["display_name"]
            if artifact.media_type == "application/json":
                job = conn.execute(
                    """SELECT r.job_id IS NOT NULL AS simulated FROM product.jobs j
                       LEFT JOIN product.test_allowance_reservations r ON r.job_id=j.id
                       WHERE j.owner_key=%s AND j.document_id=%s AND j.raw_artifact_id=%s""",
                    (owner, row["document_id"], artifact_id),
                ).fetchone()
                evidence = "simulation" if job and job["simulated"] else "unverified"
                filename = str(artifact_id) + ".json"
            return artifact, filename, data, evidence

    def delete_document(self, owner: str, document_id: UUID) -> None:
        with self.database.connect() as conn:
            self._document(conn, _owner(owner), document_id, lock=True)
            conn.execute("UPDATE product.documents SET state='deleted',deleted_at=clock_timestamp() WHERE id=%s",
                         (document_id,))
