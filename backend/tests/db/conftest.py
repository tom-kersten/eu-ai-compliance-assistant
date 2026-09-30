"""Fixtures for the db suite: one throwaway database per test."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from psycopg import AsyncConnection
from psycopg.rows import tuple_row

MIGRATIONS_DIR = Path("/app/postgres/migrations")


def _admin_url(database_url: str) -> str:
    """Point the URL at the maintenance database used for CREATE/DROP DATABASE."""
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


def _db_url(database_url: str, name: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path=f"/{name}"))


@pytest.fixture
async def database_url() -> AsyncIterator[str]:
    base_url = os.environ["TEST_DATABASE_URL"]
    name = f"migtest_{uuid.uuid4().hex}"
    admin_url = _admin_url(base_url)
    target_url = _db_url(base_url, name)

    async with await psycopg.AsyncConnection.connect(
        admin_url,
        autocommit=True,
        row_factory=tuple_row,
    ) as admin:
        await admin.execute(f'CREATE DATABASE "{name}"')

    try:
        yield target_url
    finally:
        async with await psycopg.AsyncConnection.connect(
            admin_url,
            autocommit=True,
            row_factory=tuple_row,
        ) as admin:
            await admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (name,),
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(database_url) as connection:
        yield connection
