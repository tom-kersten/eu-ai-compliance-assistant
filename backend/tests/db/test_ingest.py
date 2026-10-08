"""Database tests for the ingestion command."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import Settings
from app.ingestion.manifest import load_manifest
from app.ingestion.run import corpus_hash, ingest
from app.providers.base import EmbeddingDimensionError
from app.providers.fakes import FakeEmbedder
from app.schemas.domain import IndexMeta, StoredProvision
from app.store.migrate import migrate
from app.store.repository import Repository

from .conftest import MIGRATIONS_DIR

CORPUS = Path("/app/corpus")
MANIFEST_PATH = CORPUS / "manifest.yaml"
# Must match the vector(2000) column fixed by the migration.
_DIM = 2000


@pytest.fixture
async def migrated_conn(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    await migrate(conn, MIGRATIONS_DIR)
    yield conn


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        embedding_dimensions=_DIM,
        embedding_batch_size=100,
        embedding_model="fake-embed",
        serving_profile="online",
    )


def _stray(*, embedding: list[float] | None = None) -> StoredProvision:
    vec = embedding if embedding is not None else [0.0] * _DIM
    return StoredProvision(
        ref="stray:art_999",
        doc="stray",
        kind="article",
        label="999",
        parent_ref="stray:art_999",
        part_no=1,
        part_count=1,
        title="Stray",
        chapter=None,
        section=None,
        part_label=None,
        header="stray header",
        body="stray body",
        token_estimate=1,
        amended_by=[],
        embedding=vec,
    )


async def _provision_count(conn: AsyncConnection) -> int:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT count(*) AS n FROM provisions")
        row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


async def _all_provision_snapshots(
    conn: AsyncConnection,
) -> list[tuple[str, str, list[float]]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT ref, header, embedding
            FROM provisions
            ORDER BY ref
            """
        )
        rows = await cur.fetchall()
    result: list[tuple[str, str, list[float]]] = []
    for row in rows:
        embedding = row["embedding"]
        if hasattr(embedding, "to_list"):
            embedding = embedding.to_list()
        result.append((row["ref"], row["header"], list(embedding)))
    return result


@pytest.mark.db
async def test_ingest_real_corpus_writes_359_and_index_meta(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    embedder = FakeEmbedder(dimension=settings.embedding_dimensions)
    summary = await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=False,
    )

    assert summary.chunk_count == 359
    assert await _provision_count(migrated_conn) == 359

    repo = Repository(migrated_conn)
    meta = await repo.read_index_meta()
    assert meta is not None
    assert meta.dimension == settings.embedding_dimensions
    assert meta.embedding_model == settings.embedding_model
    assert meta.serving_profile == settings.serving_profile
    assert meta.corpus_snapshot.isoformat() == "2026-08-11"
    assert meta.corpus_hash
    manifest = load_manifest(MANIFEST_PATH)
    assert meta.corpus_hash == corpus_hash(MANIFEST_PATH, manifest)


@pytest.mark.db
async def test_ingest_rerun_without_reset_is_idempotent(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    embedder = FakeEmbedder(dimension=settings.embedding_dimensions)
    await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=False,
    )
    first_rows = await _all_provision_snapshots(migrated_conn)
    first_meta = await Repository(migrated_conn).read_index_meta()
    assert first_meta is not None

    await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=False,
    )
    second_rows = await _all_provision_snapshots(migrated_conn)
    second_meta = await Repository(migrated_conn).read_index_meta()
    assert second_meta is not None

    assert len(second_rows) == 359
    assert second_rows == first_rows
    assert second_meta.corpus_hash == first_meta.corpus_hash
    assert second_meta.dimension == first_meta.dimension
    assert second_meta.embedding_model == first_meta.embedding_model
    assert second_meta.serving_profile == first_meta.serving_profile
    assert second_meta.corpus_snapshot == first_meta.corpus_snapshot


@pytest.mark.db
async def test_ingest_reset_removes_stray_row(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    repo = Repository(migrated_conn)
    await repo.upsert_provisions([_stray()])
    await migrated_conn.commit()
    assert await _provision_count(migrated_conn) == 1

    embedder = FakeEmbedder(dimension=settings.embedding_dimensions)
    await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=False,
    )
    assert await _provision_count(migrated_conn) == 360
    found = await repo.get_by_refs(["stray:art_999"])
    assert len(found) == 1

    await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=True,
    )
    assert await _provision_count(migrated_conn) == 359
    assert await repo.get_by_refs(["stray:art_999"]) == []


class _RaisingOnSecondBatch(FakeEmbedder):
    """Raises on the second embed_documents call."""

    def __init__(self, dimension: int) -> None:
        super().__init__(dimension=dimension)
        self._calls = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self._calls += 1
        if self._calls >= 2:
            raise RuntimeError("embedder failed on second batch")
        return await super().embed_documents(texts)


@pytest.mark.db
async def test_embedder_raise_mid_run_leaves_empty_db_unchanged(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    settings = settings.model_copy(update={"embedding_batch_size": 50})
    embedder = _RaisingOnSecondBatch(dimension=settings.embedding_dimensions)

    with pytest.raises(RuntimeError, match="second batch"):
        await ingest(
            settings=settings,
            embedder=embedder,
            conn=migrated_conn,
            corpus_dir=CORPUS,
            reset=False,
        )

    assert await _provision_count(migrated_conn) == 0
    assert await Repository(migrated_conn).read_index_meta() is None


@pytest.mark.db
async def test_embedder_raise_mid_run_with_reset_leaves_seeded_db_intact(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    settings = settings.model_copy(update={"embedding_batch_size": 50})
    repo = Repository(migrated_conn)
    seed = _stray()
    await repo.upsert_provisions([seed])
    seed_meta = IndexMeta(
        embedding_model="seed-model",
        dimension=_DIM,
        serving_profile="online",
        corpus_snapshot=date(2020, 1, 1),
        corpus_hash="seed-hash",
        ingested_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    await repo.write_index_meta(seed_meta)
    await migrated_conn.commit()

    embedder = _RaisingOnSecondBatch(dimension=settings.embedding_dimensions)
    with pytest.raises(RuntimeError, match="second batch"):
        await ingest(
            settings=settings,
            embedder=embedder,
            conn=migrated_conn,
            corpus_dir=CORPUS,
            reset=True,
        )

    assert await _provision_count(migrated_conn) == 1
    found = await repo.get_by_refs(["stray:art_999"])
    assert len(found) == 1
    meta = await repo.read_index_meta()
    assert meta is not None
    assert meta.corpus_hash == "seed-hash"
    assert meta.embedding_model == "seed-model"


@pytest.mark.db
async def test_transaction_rollback_keeps_old_rows_when_index_meta_fails(
    migrated_conn: AsyncConnection,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = FakeEmbedder(dimension=settings.embedding_dimensions)
    await ingest(
        settings=settings,
        embedder=embedder,
        conn=migrated_conn,
        corpus_dir=CORPUS,
        reset=False,
    )
    before_rows = await _all_provision_snapshots(migrated_conn)
    before_meta = await Repository(migrated_conn).read_index_meta()
    assert before_meta is not None
    assert len(before_rows) == 359

    async def _raise(self: Repository, meta: IndexMeta) -> None:
        raise RuntimeError("write_index_meta failed")

    monkeypatch.setattr(Repository, "write_index_meta", _raise)

    with pytest.raises(RuntimeError, match="write_index_meta failed"):
        await ingest(
            settings=settings,
            embedder=embedder,
            conn=migrated_conn,
            corpus_dir=CORPUS,
            reset=True,
        )

    after_rows = await _all_provision_snapshots(migrated_conn)
    after_meta = await Repository(migrated_conn).read_index_meta()
    assert after_rows == before_rows
    assert after_meta is not None
    assert after_meta.corpus_hash == before_meta.corpus_hash
    assert after_meta.embedding_model == before_meta.embedding_model
    assert after_meta.ingested_at == before_meta.ingested_at


@pytest.mark.db
async def test_wrong_dimension_raises_and_writes_nothing(
    migrated_conn: AsyncConnection,
    settings: Settings,
) -> None:
    embedder = FakeEmbedder(dimension=settings.embedding_dimensions + 1)

    with pytest.raises(EmbeddingDimensionError):
        await ingest(
            settings=settings,
            embedder=embedder,
            conn=migrated_conn,
            corpus_dir=CORPUS,
            reset=False,
        )

    assert await _provision_count(migrated_conn) == 0
    assert await Repository(migrated_conn).read_index_meta() is None
