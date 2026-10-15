from pathlib import Path

import psycopg

from isss_bot import config

MIGRATIONS_DIR = config.ROOT / "migrations"
LOCK_ID = 7_412_093


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def apply(database_url: str | None = None) -> list[str]:
    applied_now = []
    with psycopg.connect(database_url or config.DATABASE_URL) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            conn.commit()
            for path in migration_files():
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                applied_now.append(path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
            conn.commit()
    return applied_now
