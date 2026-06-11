"""Database pool and lightweight helpers."""

from __future__ import annotations

from typing import Any, AsyncIterator

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def init_pool(dsn: str) -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )
        await _pool.open()
        await _pool.wait()
    return _pool


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_db_connection() -> AsyncIterator[Any]:
    async with get_pool().connection() as conn:
        yield conn


async def fetchone(conn: Any, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cur = await conn.execute(query, params)
    return await cur.fetchone()


async def fetchall(conn: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = await conn.execute(query, params)
    rows = await cur.fetchall()
    return list(rows)
