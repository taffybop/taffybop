# PX1-02 PostgreSQL and local artifact persistence

Historical completed checkpoint. [PX1-03](WORKER.md) adds migration 002 for
the fenced lifecycle and 003 for finite simulated allowances; the evidence below
remains explicitly scoped to PX1-02.

Completed: 2026-11-11. This records the private repository layer at PX1-02.
[PX1-04](ROUTES.md) subsequently connected its local product routes and saved
library; v1 remains a separate compatibility screen. No worker or provider
submission was enabled by PX1-02 itself.

## Components and invariants

- [Database](../../app/product/database.py) opens short-lived PostgreSQL
  connections. [SQL migrations](../../app/product/migrations/001_persistence.sql)
  run in one transaction under an advisory lock; a checksum ledger rejects
  altered, missing or out-of-order applied files. Replays apply nothing.
- [Repository](../../app/product/repository.py) persists server-derived owner
  keys, documents, parse intent, immutable settings and successful result
  captures. Owner/document composite foreign keys prevent linking another
  owner's records, including through direct SQL. Parse idempotency is unique
  per owner and key; a different document or settings conflicts.
- [Storage](../../app/product/storage.py) publishes UUID-addressed files with
  atomic no-replace links and file/directory fsync. Files are read-only and the
  dedicated root is private. Symlinks and nonregular objects are rejected;
  length and SHA-256 are checked on every read. Same-byte retries are allowed;
  different bytes cannot replace an artifact. There is no shared hash-based
  deduplication across owners.
- A successful capture writes raw bytes, inserts the result and publishes the
  succeeded job in one database transaction. Deferred constraints require the
  document, settings and raw artifact metadata to agree. Results/artifact
  metadata cannot be updated/deleted; terminal job snapshots permit only later
  usage reconciliation and its update timestamp. Null usage stays unknown.
- Raw JSON syntax is checked without rewriting bytes. Unknown properties,
  whitespace and key order survive download. Normalized page order and repeated
  page IDs remain unchanged; reported provider version stays null when absent.
- Every repository resource read checks the owner and active, unexpired source
  document. Tombstoning immediately revokes its jobs/results/artifacts too.
  A source read locks the document against concurrent deletion until the byte
  read completes. Physical cleanup, backup deletion and restore enforcement
  remain PX5 work.

Bytes are fsynced **before** database references commit. A crash or rejected
transaction can leave a private unreferenced file; it cannot publish accepted
metadata before its bytes exist. No orphan collector is enabled yet. Storage
alone is a trusted private adapter, not a public authorization API.

`create_document` accepts already detected/validated intake metadata. It checks
the frozen document contract and size; actual MIME/page/pixel detection remains
the API intake validator's responsibility. Owners are supplied by trusted
server code, not request input. This is not production authentication or RLS.

`save_parse_result` is a trusted persistence capture operation, currently tested
with authored results. It can complete queued intent for storage tests. PX1-03
must add actual submission state, provider IDs, lease/fencing and reconciliation
before using this boundary from a real worker. There is no budget reservation,
fair scheduler or full-job capacity claim in PX1-02.

## Isolated local database and commands

The existing PostgreSQL 16.3 binaries were used. The postgres-owned installation
cluster and default port were untouched. The task cluster lives in ignored
`tmp/px1-02/pgdata`, with a private Unix socket in `tmp/px1-02/socket` and loopback
listener at `127.0.0.1:55471`. Host authentication is SCRAM with no test password
configured; tests use the private local socket. This is a development cluster,
not a hosting configuration. It is stopped at handoff; its data is retained.

The pinned `psycopg[binary]==3.3.8` driver was installed only in the workspace
virtual environment. `uv.lock` includes it and reconciles the earlier direct
httpx/Pydantic declarations; all previously locked versions stayed unchanged.
The built wheel contains the SQL migration and pinned driver requirement.

Run from the repository root to resume the retained cluster:

```sh
/Library/PostgreSQL/16/bin/pg_ctl -D tmp/px1-02/pgdata \
  -l tmp/px1-02/postgres.log \
  -o '-h 127.0.0.1 -p 55471 -k /path/to/taffybop/tmp/px1-02/socket' -w start
export TAFFYBOP_DATABASE_URL='host=/path/to/taffybop/tmp/px1-02/socket port=55471 user=local_user dbname=postgres'
.venv/bin/python -m app.product.manage migrate
export TAFFYBOP_TEST_DATABASE_URL="$TAFFYBOP_DATABASE_URL"
.venv/bin/python -m pytest tests/test_product_persistence.py tests/test_product_storage.py -q
/Library/PostgreSQL/16/bin/pg_ctl -D tmp/px1-02/pgdata -m fast -w stop
```

Initialization/server/socket access required local sandbox execution permission.
The first sandboxed `initdb` failed at shared-memory creation and removed its
incomplete directory; the authorized retry succeeded. PyPI access was needed
to install the driver and refresh the lock. No provider key was used.

For a fresh cluster, use a new private directory and unused port rather than
overwriting this cluster. Do not place data outside ignored local storage or
reuse the postgres-owned installation cluster. SQL migrations are packaged;
apply them explicitly using the server-side DSN, never as an API import effect.

## Actual evidence

The [starting snapshot](PUBLIC_VALIDATION.md) records branch/HEAD, starting
dirty status and 88 non-secret dirty-file hashes. A tracked binary patch is
retained privately in ignored `tmp/px1-02/tracked-before.patch`. No commit/reset
or cleanup of earlier work occurred.

The real PostgreSQL suite covers migration repeat/drift/missing/failure and
concurrent replay, idempotency races, direct-SQL rejection of cross-owner and
inconsistent captures, immutable records, disk-failure rollback, raw JSON
syntax/fidelity and revocation. Storage checks cover concurrent writers,
interrupted writes, corruption, private modes and path attacks.

[Restart preparation](PUBLIC_VALIDATION.md) wrote two authored
sources (PDF/PNG), two jobs, one explicitly synthetic result and one queued job.
PostgreSQL was actually stopped and started. A separate Python process ran
[restart verification](PUBLIC_VALIDATION.md): both source files,
job/result snapshots and raw bytes matched, queued idempotency survived, migration
replay was empty, and nine inaccessible/absent reads returned the same error.
The [reproducible script](PUBLIC_VALIDATION.md) refuses to count
the same Python process or unchanged PostgreSQL start time as restart evidence.

[Four real HTTP checks](PUBLIC_VALIDATION.md) used an isolated loopback
API with the provider key deliberately empty: config disabled, upload rejected
before submission, missing v1 job 404 and pending `/v2/documents` 404. The API
was stopped. Browser/frontend checks were not rerun because no UI or route was
changed; the PX1-01 browser report remains historical evidence only.

No provider/model call, live parse, measured credit charge, plan change,
extraction or deployment occurred. Successful durable provider parsing remains
an acceptance gate after worker admission and explicit spending conditions.

Implementation references: [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html),
[PostgreSQL 16 constraints](https://www.postgresql.org/docs/16/sql-createtable.html).
