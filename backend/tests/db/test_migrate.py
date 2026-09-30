"""Database tests for the migration runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from psycopg import AsyncConnection, Error

from app.errors import ChecksumMismatch
from app.store.migrate import migrate, pending_migrations

from .conftest import MIGRATIONS_DIR


@pytest.mark.db
async def test_migrate_creates_schema_on_empty_database(
    conn: AsyncConnection,
) -> None:
    applied = await migrate(conn, MIGRATIONS_DIR)
    assert applied == ["0001"]

    tables = await conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('provisions', 'index_meta', 'schema_migrations')
        ORDER BY table_name
        """
    )
    assert [row[0] for row in await tables.fetchall()] == [
        "index_meta",
        "provisions",
        "schema_migrations",
    ]

    extension = await conn.execute(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    )
    assert await extension.fetchone() == (1,)

    index = await conn.execute(
        """
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'provisions_parent_idx'
        """
    )
    assert await index.fetchone() == (1,)

    kind_check = await conn.execute(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'provisions'::regclass
          AND contype = 'c'
          AND conname LIKE '%kind%'
        """
    )
    kind_def = (await kind_check.fetchone())[0]
    assert "article" in kind_def and "recital" in kind_def and "annex" in kind_def

    index_meta_check = await conn.execute(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'index_meta'::regclass
          AND contype = 'c'
        """
    )
    defs = [row[0] for row in await index_meta_check.fetchall()]
    assert any("id" in d for d in defs)

    embedding_type = await conn.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        WHERE a.attrelid = 'provisions'::regclass
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    )
    assert (await embedding_type.fetchone())[0] == "vector(2000)"

    versions = await conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )
    assert [row[0] for row in await versions.fetchall()] == ["0001"]


@pytest.mark.db
async def test_migrate_rerun_does_not_reapply(conn: AsyncConnection) -> None:
    await migrate(conn, MIGRATIONS_DIR)
    first = await conn.execute(
        "SELECT version, applied_at FROM schema_migrations WHERE version = '0001'"
    )
    first_row = await first.fetchone()
    assert first_row is not None

    applied = await migrate(conn, MIGRATIONS_DIR)
    assert applied == []

    second = await conn.execute(
        "SELECT version, applied_at FROM schema_migrations WHERE version = '0001'"
    )
    second_row = await second.fetchone()
    assert second_row == first_row


@pytest.mark.db
async def test_migrate_applies_files_in_numeric_order(
    conn: AsyncConnection,
    tmp_path: Path,
) -> None:
    (tmp_path / "0002_insert.sql").write_text(
        "INSERT INTO order_probe (id) VALUES (2);\n"
    )
    (tmp_path / "0001_create.sql").write_text(
        "CREATE TABLE order_probe (id int PRIMARY KEY);\n"
        "INSERT INTO order_probe (id) VALUES (1);\n"
    )

    applied = await migrate(conn, tmp_path)
    assert applied == ["0001", "0002"]

    rows = await conn.execute("SELECT id FROM order_probe ORDER BY id")
    assert [row[0] for row in await rows.fetchall()] == [1, 2]


@pytest.mark.db
async def test_migrate_rolls_back_failed_file(
    conn: AsyncConnection,
    tmp_path: Path,
) -> None:
    (tmp_path / "0001_ok.sql").write_text(
        "CREATE TABLE keep_me (id int PRIMARY KEY);\n"
    )
    (tmp_path / "0002_fail.sql").write_text(
        "CREATE TABLE should_not_exist (id int PRIMARY KEY);\nSELECT 1 / 0;\n"
    )

    with pytest.raises(Error):
        await migrate(conn, tmp_path)

    tables = await conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('keep_me', 'should_not_exist')
        ORDER BY table_name
        """
    )
    assert [row[0] for row in await tables.fetchall()] == ["keep_me"]

    versions = await conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    )
    assert [row[0] for row in await versions.fetchall()] == ["0001"]


@pytest.mark.db
async def test_migrate_stops_when_applied_file_changes(
    conn: AsyncConnection,
    tmp_path: Path,
) -> None:
    first = tmp_path / "0001_ok.sql"
    first.write_text("CREATE TABLE checksum_probe (id int PRIMARY KEY);\n")
    await migrate(conn, tmp_path)

    first.write_text(
        "CREATE TABLE checksum_probe (id int PRIMARY KEY);\n"
        "CREATE TABLE should_not_exist (id int PRIMARY KEY);\n"
    )
    (tmp_path / "0002_later.sql").write_text(
        "CREATE TABLE later_table (id int PRIMARY KEY);\n"
    )

    with pytest.raises(ChecksumMismatch) as exc_info:
        await migrate(conn, tmp_path)

    assert exc_info.value.version == "0001"

    tables = await conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('should_not_exist', 'later_table')
        """
    )
    assert await tables.fetchall() == []


@pytest.mark.db
async def test_pending_migrations_lists_unapplied_files(
    conn: AsyncConnection,
    tmp_path: Path,
) -> None:
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int PRIMARY KEY);\n")
    (tmp_path / "0002_b.sql").write_text("CREATE TABLE b (id int PRIMARY KEY);\n")
    (tmp_path / "0003_c.sql").write_text("CREATE TABLE c (id int PRIMARY KEY);\n")

    assert await pending_migrations(conn, tmp_path) == ["0001", "0002", "0003"]

    exists = await conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'schema_migrations'
        )
        """
    )
    assert (await exists.fetchone())[0] is False

    first_only = tmp_path / "first_only"
    first_only.mkdir()
    (first_only / "0001_a.sql").write_text((tmp_path / "0001_a.sql").read_text())
    await migrate(conn, first_only)

    assert await pending_migrations(conn, tmp_path) == ["0002", "0003"]
