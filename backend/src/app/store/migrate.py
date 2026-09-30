"""Forward-only, checksummed SQL migration runner."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import AsyncClientCursor, AsyncConnection

from app.errors import ChecksumMismatch

logger = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_MIGRATION_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

DEFAULT_MIGRATIONS_DIR = Path("/app/postgres/migrations")


def _list_migration_files(directory: Path) -> list[Path]:
    files: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = _MIGRATION_FILE.match(path.name)
        if match is None:
            continue
        files.append((int(match.group(1)), path))
    files.sort(key=lambda item: item[0])
    return [path for _, path in files]


def _version_of(path: Path) -> str:
    match = _MIGRATION_FILE.match(path.name)
    if match is None:
        msg = f"invalid migration filename: {path.name}"
        raise ValueError(msg)
    return match.group(1)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_migration(directory: Path, name: str) -> Path:
    """Create the next numbered migration file and return its path."""
    if not _MIGRATION_NAME.match(name):
        msg = f"migration name must be snake_case: {name!r}"
        raise ValueError(msg)

    directory.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in _list_migration_files(directory):
        highest = max(highest, int(_version_of(path)))

    next_version = f"{highest + 1:04d}"
    path = directory / f"{next_version}_{name}.sql"
    path.write_text("")
    return path


async def _ensure_schema_migrations(conn: AsyncConnection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


async def _applied_checksums(conn: AsyncConnection) -> dict[str, str]:
    rows = await conn.execute("SELECT version, checksum FROM schema_migrations")
    result = await rows.fetchall()
    return {version: checksum for version, checksum in result}


async def pending_migrations(
    conn: AsyncConnection,
    directory: Path,
) -> list[str]:
    """Return unapplied migration versions in order, without writing."""
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
    row = await exists.fetchone()
    applied: set[str] = set()
    if row is not None and row[0]:
        applied = set((await _applied_checksums(conn)).keys())

    return [
        _version_of(path)
        for path in _list_migration_files(directory)
        if _version_of(path) not in applied
    ]


async def migrate(conn: AsyncConnection, directory: Path) -> list[str]:
    """Apply pending migrations. Returns the versions that were applied.

    Each file runs in its own committed transaction. The connection is
    switched to autocommit for the duration so a failed file cannot leave
    earlier files uncommitted.
    """
    previous = conn.autocommit
    if not previous:
        # Leave IDLE so autocommit can be enabled; migrate owns the connection.
        await conn.rollback()
    await conn.set_autocommit(True)
    try:
        async with conn.transaction():
            await _ensure_schema_migrations(conn)

        applied = await _applied_checksums(conn)
        newly_applied: list[str] = []

        for path in _list_migration_files(directory):
            version = _version_of(path)
            digest = _checksum(path)

            if version in applied:
                if applied[version] != digest:
                    raise ChecksumMismatch(version, applied[version], digest)
                continue

            sql_text = path.read_text()
            async with conn.transaction():
                async with AsyncClientCursor(conn) as cur:
                    await cur.execute(sql_text)
                await conn.execute(
                    """
                    INSERT INTO schema_migrations (version, checksum)
                    VALUES (%s, %s)
                    """,
                    (version, digest),
                )
            newly_applied.append(version)
            logger.info("applied migration version=%s", version)

        return newly_applied
    finally:
        await conn.set_autocommit(previous)


async def _run_migrate(database_url: str, directory: Path) -> None:
    async with await psycopg.AsyncConnection.connect(database_url) as conn:
        applied = await migrate(conn, directory)
    if applied:
        print(f"applied: {', '.join(applied)}")
    else:
        print("no pending migrations")


def _cli_new_migration(directory: Path, name: str) -> None:
    path = create_migration(directory, name)
    print(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate")
    sub = parser.add_subparsers(dest="command")

    migrate_parser = sub.add_parser("run", help="apply pending migrations")
    migrate_parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
    )

    new_parser = sub.add_parser(
        "new-migration",
        help="create the next numbered migration file",
    )
    new_parser.add_argument("name")
    new_parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
    )

    # Default command is migrate when invoked as `python -m app.store.migrate`
    # or via the `migrate` shell wrapper with no subcommand.
    args = parser.parse_args(argv)
    command = args.command

    if command is None:
        # Treat bare invocation as run.
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("DATABASE_URL is required", file=sys.stderr)
            return 1
        import asyncio

        asyncio.run(_run_migrate(database_url, DEFAULT_MIGRATIONS_DIR))
        return 0

    if command == "run":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            print("DATABASE_URL is required", file=sys.stderr)
            return 1
        import asyncio

        asyncio.run(_run_migrate(database_url, args.directory))
        return 0

    if command == "new-migration":
        _cli_new_migration(args.directory, args.name)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
