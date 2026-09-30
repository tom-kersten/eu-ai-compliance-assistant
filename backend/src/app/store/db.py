"""Async connection pool for Postgres with pgvector."""

from __future__ import annotations

from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


async def _prepare_connection(conn: AsyncConnection) -> None:
    await register_vector_async(conn)


def create_pool(database_url: str) -> AsyncConnectionPool:
    """Build a pool that is not yet open. Caller opens it at startup."""
    return AsyncConnectionPool(
        conninfo=database_url,
        open=False,
        configure=_prepare_connection,
    )
