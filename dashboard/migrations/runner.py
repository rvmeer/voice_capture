"""Apply SQL migrations in order, tracking schema_migrations table."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).parent / "sql"

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version int PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


async def run_migrations(dsn: str):
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(CREATE_MIGRATIONS_TABLE)
        cur = await conn.execute("SELECT version FROM schema_migrations")
        applied_rows = await cur.fetchall()
        applied = {row[0] for row in applied_rows}

        sql_files = sorted(SQL_DIR.glob("*.sql"))
        for sql_file in sql_files:
            version = int(sql_file.name.split("_")[0])
            if version in applied:
                continue
            sql = sql_file.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            print(f"Applied migration {version}: {sql_file.name}")


def run_migrations_sync(dsn: str):
    asyncio.run(run_migrations(dsn))


if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_DSN", "dbname=recordings")
    asyncio.run(run_migrations(dsn))
