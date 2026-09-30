"""Scaffold checks for the db suite."""

import os

import psycopg
import pytest


@pytest.mark.db
async def test_db_test_database_accepts_connections() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]

    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            row = await cur.fetchone()

    assert row == (1,)
