"""Database tests for store.health.check."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from psycopg import AsyncConnection

from app.config import Settings
from app.schemas.domain import IndexMeta, StoredProvision
from app.store.health import check
from app.store.migrate import migrate
from app.store.repository import Repository

from .conftest import MIGRATIONS_DIR

_DIM = 2000


def _vec(*prefix: float) -> list[float]:
    values = list(prefix)
    return values + [0.0] * (_DIM - len(values))


def _meta(**overrides: object) -> IndexMeta:
    base: dict[str, object] = {
        "embedding_model": "qwen/qwen3-embedding-8b",
        "dimension": _DIM,
        "serving_profile": "online",
        "corpus_snapshot": date(2026, 1, 15),
        "corpus_hash": "hash-one",
        "ingested_at": datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return IndexMeta(**base)  # type: ignore[arg-type]


def _stored(ref: str = "AVG:art_1") -> StoredProvision:
    return StoredProvision(
        ref=ref,
        doc="AVG",
        kind="article",
        label="1",
        parent_ref=ref,
        part_no=1,
        part_count=1,
        title="Titel",
        chapter=None,
        section=None,
        part_label=None,
        header=f"header for {ref}",
        body="1. tekst",
        token_estimate=10,
        amended_by=[],
        embedding=_vec(1.0),
    )


@pytest.fixture
async def migrated_conn(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    await migrate(conn, MIGRATIONS_DIR)
    yield conn


@pytest.mark.db
async def test_health_pending_migrations_on_unmigrated_db(
    conn: AsyncConnection,
) -> None:
    settings = Settings()
    result = await check(conn, settings)
    assert result is not None
    assert result.reason == "pending_migrations"
    assert result.detail


@pytest.mark.db
async def test_health_missing_index_when_empty(
    migrated_conn: AsyncConnection,
) -> None:
    settings = Settings()
    result = await check(migrated_conn, settings)
    assert result is not None
    assert result.reason == "missing_index"
    assert result.detail


@pytest.mark.db
async def test_health_embedding_mismatch_wrong_model(
    migrated_conn: AsyncConnection,
) -> None:
    repo = Repository(migrated_conn)
    await repo.upsert_provisions([_stored()])
    await repo.write_index_meta(_meta(embedding_model="other-model"))
    settings = Settings(embedding_model="qwen/qwen3-embedding-8b")
    result = await check(migrated_conn, settings)
    assert result is not None
    assert result.reason == "embedding_mismatch"
    assert result.detail


@pytest.mark.db
async def test_health_embedding_mismatch_wrong_dimension(
    migrated_conn: AsyncConnection,
) -> None:
    repo = Repository(migrated_conn)
    await repo.upsert_provisions([_stored()])
    await repo.write_index_meta(_meta(dimension=999))
    settings = Settings(embedding_dimensions=_DIM)
    result = await check(migrated_conn, settings)
    assert result is not None
    assert result.reason == "embedding_mismatch"
    assert result.detail


@pytest.mark.db
async def test_health_ok_when_index_matches(
    migrated_conn: AsyncConnection,
) -> None:
    repo = Repository(migrated_conn)
    await repo.upsert_provisions([_stored()])
    await repo.write_index_meta(_meta())
    settings = Settings(
        embedding_model="qwen/qwen3-embedding-8b",
        embedding_dimensions=_DIM,
    )
    result = await check(migrated_conn, settings)
    assert result is None
