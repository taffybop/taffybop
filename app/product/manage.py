"""Explicit local administration; never invoked on API import or startup."""

import argparse
import os

import psycopg

from app.product.database import Database, MigrationError


def main() -> None:
    parser = argparse.ArgumentParser(description="TaffyBop product database administration")
    parser.add_argument("command", choices=("migrate",))
    parser.parse_args()
    dsn = os.environ.get("TAFFYBOP_DATABASE_URL")
    if not dsn:
        parser.exit(2, "Set server-side TAFFYBOP_DATABASE_URL before migrating.\n")
    try:
        applied = Database(dsn).migrate()
    except (psycopg.Error, MigrationError, OSError):
        # DSN/driver details may contain secrets; do not print the exception.
        parser.exit(1, "Product migration failed; inspect private database configuration and migration checksums.\n")
    print(f"Applied {len(applied)} product migration(s).")


if __name__ == "__main__":
    main()
