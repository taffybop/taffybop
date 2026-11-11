"""Explicit PostgreSQL connections and checksum-verified transactional migrations.

No connection is opened on import. The caller supplies a server-side DSN; it is
never included in logs, public contracts or error messages by this module.
"""

from hashlib import sha256
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class MigrationError(RuntimeError):
    pass


class Database:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def connect(self):
        # Short-lived connections close/commit or roll back with the context.
        # A bounded pool belongs with the API/worker process in later stories.
        return psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=5)

    def migrate(self, migrations_dir: Path | None = None) -> tuple[str, ...]:
        directory = migrations_dir or Path(__file__).with_name("migrations")
        files = sorted(directory.glob("[0-9][0-9][0-9]_*.sql"))
        if not files:
            raise MigrationError("No product migrations found")
        applied = []
        with self.connect() as conn:
            # Transaction-scoped lock serializes even the initial schema create.
            conn.execute("SELECT pg_advisory_xact_lock(729041, 102)")
            conn.execute("CREATE SCHEMA IF NOT EXISTS product")
            conn.execute("""CREATE TABLE IF NOT EXISTS product.schema_migrations (
                version text PRIMARY KEY, sha256 text NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT now())""")
            existing = {r["version"]: r["sha256"] for r in conn.execute(
                "SELECT version, sha256 FROM product.schema_migrations"
            )}
            available = {path.name for path in files}
            if existing.keys() - available:
                raise MigrationError("Applied product migration is missing")
            for path in files:
                source = path.read_bytes()
                digest = sha256(source).hexdigest()
                if path.name in existing:
                    if existing[path.name] != digest:
                        raise MigrationError("Applied product migration checksum changed")
                    continue
                if existing and path.name < max(existing):
                    raise MigrationError("Product migrations must be appended in order")
                conn.execute(source.decode("utf-8"), prepare=False)
                conn.execute(
                    "INSERT INTO product.schema_migrations(version, sha256) VALUES (%s, %s)",
                    (path.name, digest),
                )
                applied.append(path.name)
        return tuple(applied)
