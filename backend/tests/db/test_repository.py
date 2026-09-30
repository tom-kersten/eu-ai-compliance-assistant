"""Database tests for the provisions repository."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
from psycopg import AsyncConnection, Error
from psycopg.rows import dict_row

from app.schemas.domain import DocumentCount, IndexMeta, StoredProvision
from app.store.db import create_pool
from app.store.migrate import migrate
from app.store.repository import Repository

from .conftest import MIGRATIONS_DIR

_DIM = 2000


def _vec(*prefix: float) -> list[float]:
    """Build a length-2000 vector starting with the given values."""
    values = list(prefix)
    if len(values) > _DIM:
        msg = f"prefix longer than {_DIM}"
        raise ValueError(msg)
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


def _stored(
    *,
    ref: str,
    doc: str = "AI-verordening",
    kind: str = "article",
    label: str = "6",
    parent_ref: str | None = None,
    part_no: int = 1,
    part_count: int = 1,
    title: str | None = "Titel",
    part_label: str | None = None,
    body: str = "1. tekst",
    embedding: list[float] | None = None,
    amended_by: list[str] | None = None,
) -> StoredProvision:
    return StoredProvision(
        ref=ref,
        doc=doc,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        parent_ref=parent_ref or ref,
        part_no=part_no,
        part_count=part_count,
        title=title,
        chapter=None,
        section=None,
        part_label=part_label,
        header=f"header for {ref}",
        body=body,
        token_estimate=10,
        amended_by=amended_by or [],
        embedding=embedding if embedding is not None else _vec(1.0),
    )


@pytest.fixture
async def migrated_conn(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    await migrate(conn, MIGRATIONS_DIR)
    yield conn


@pytest.fixture
async def repo(migrated_conn: AsyncConnection) -> Repository:
    return Repository(migrated_conn)


@pytest.mark.db
async def test_upsert_then_fetch_by_refs(repo: Repository) -> None:
    row = _stored(ref="AI-verordening:art_6", label="6")
    await repo.upsert_provisions([row])

    found = await repo.get_by_refs(["AI-verordening:art_6"])
    assert len(found) == 1
    assert found[0].ref == "AI-verordening:art_6"
    assert found[0].body == "1. tekst"
    assert found[0].title == "Titel"
    assert len(found[0].embedding) == _DIM


@pytest.mark.db
async def test_upsert_updates_existing_row(repo: Repository) -> None:
    first = _stored(ref="AI-verordening:art_6", body="oud")
    second = _stored(ref="AI-verordening:art_6", body="nieuw", title="Nieuw")
    await repo.upsert_provisions([first])
    await repo.upsert_provisions([second])

    found = await repo.get_by_refs(["AI-verordening:art_6"])
    assert len(found) == 1
    assert found[0].body == "nieuw"
    assert found[0].title == "Nieuw"


@pytest.mark.db
async def test_get_by_refs_preserves_order_and_skips_missing(
    repo: Repository,
) -> None:
    await repo.upsert_provisions(
        [
            _stored(ref="AVG:art_1", doc="AVG", label="1"),
            _stored(ref="AVG:art_2", doc="AVG", label="2"),
        ]
    )

    found = await repo.get_by_refs(
        ["AVG:art_2", "missing:art_9", "AVG:art_1", "AVG:art_2"]
    )
    assert [p.ref for p in found] == ["AVG:art_2", "AVG:art_1", "AVG:art_2"]


@pytest.mark.db
async def test_get_by_parent_ref_returns_parts_in_order(repo: Repository) -> None:
    parent = "AVG:art_9"
    await repo.upsert_provisions(
        [
            _stored(
                ref=f"{parent}#2",
                doc="AVG",
                label="9",
                parent_ref=parent,
                part_no=2,
                part_count=3,
                part_label="leden 3 tot en met 5",
            ),
            _stored(
                ref=f"{parent}#1",
                doc="AVG",
                label="9",
                parent_ref=parent,
                part_no=1,
                part_count=3,
                part_label="leden 1 tot en met 2",
            ),
            _stored(
                ref=f"{parent}#3",
                doc="AVG",
                label="9",
                parent_ref=parent,
                part_no=3,
                part_count=3,
                part_label="lid 6",
            ),
        ]
    )

    parts = await repo.get_by_parent_ref(parent)
    assert [p.ref for p in parts] == [f"{parent}#1", f"{parent}#2", f"{parent}#3"]
    assert [p.part_no for p in parts] == [1, 2, 3]


@pytest.mark.db
async def test_get_by_parent_ref_unknown_returns_empty(repo: Repository) -> None:
    assert await repo.get_by_parent_ref("AVG:art_missing") == []


@pytest.mark.db
async def test_wrong_dimension_vector_raises_and_leaves_no_row(
    repo: Repository,
    migrated_conn: AsyncConnection,
) -> None:
    bad = _stored(ref="AI-verordening:art_6", embedding=[0.1, 0.2, 0.3])
    with pytest.raises(Error):
        await repo.upsert_provisions([bad])
    await migrated_conn.rollback()

    async with migrated_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT count(*) AS n FROM provisions")
        row = await cur.fetchone()
    assert row is not None
    assert row["n"] == 0


@pytest.mark.db
async def test_search_similar_orders_by_cosine_similarity(repo: Repository) -> None:
    await repo.upsert_provisions(
        [
            _stored(ref="doc:a", embedding=_vec(1.0, 0.0), title="exact"),
            _stored(ref="doc:b", embedding=_vec(1.0, 1.0), title="angle45"),
            _stored(ref="doc:c", embedding=_vec(0.0, 1.0), title="orthogonal"),
        ]
    )

    results = await repo.search_similar(_vec(1.0, 0.0), top_k=10, threshold=0.0)
    assert [r.ref for r in results] == ["doc:a", "doc:b", "doc:c"]
    assert results[0].similarity == pytest.approx(1.0, abs=1e-6)
    assert results[1].similarity == pytest.approx(0.70710678, abs=1e-5)
    assert results[2].similarity == pytest.approx(0.0, abs=1e-6)


@pytest.mark.db
async def test_search_similar_respects_top_k(repo: Repository) -> None:
    await repo.upsert_provisions(
        [
            _stored(ref="doc:a", embedding=_vec(1.0, 0.0)),
            _stored(ref="doc:b", embedding=_vec(1.0, 1.0)),
            _stored(ref="doc:c", embedding=_vec(0.0, 1.0)),
        ]
    )

    results = await repo.search_similar(_vec(1.0, 0.0), top_k=2, threshold=0.0)
    assert [r.ref for r in results] == ["doc:a", "doc:b"]


@pytest.mark.db
async def test_search_similar_excludes_below_threshold(repo: Repository) -> None:
    await repo.upsert_provisions(
        [
            _stored(ref="doc:a", embedding=_vec(1.0, 0.0)),
            _stored(ref="doc:b", embedding=_vec(1.0, 1.0)),
            _stored(ref="doc:c", embedding=_vec(0.0, 1.0)),
        ]
    )

    results = await repo.search_similar(_vec(1.0, 0.0), top_k=10, threshold=0.8)
    assert [r.ref for r in results] == ["doc:a"]
    assert results[0].similarity >= 0.8


@pytest.mark.db
async def test_search_similar_empty_when_nothing_above_threshold(
    repo: Repository,
) -> None:
    await repo.upsert_provisions([_stored(ref="doc:c", embedding=_vec(0.0, 1.0))])

    results = await repo.search_similar(_vec(1.0, 0.0), top_k=10, threshold=0.5)
    assert results == []


@pytest.mark.db
async def test_read_index_meta_empty_returns_none(repo: Repository) -> None:
    assert await repo.read_index_meta() is None


@pytest.mark.db
async def test_write_index_meta_keeps_single_row(
    repo: Repository,
    migrated_conn: AsyncConnection,
) -> None:
    await repo.write_index_meta(_meta(corpus_hash="first"))
    await repo.write_index_meta(_meta(corpus_hash="second", serving_profile="offline"))

    meta = await repo.read_index_meta()
    assert meta is not None
    assert meta.corpus_hash == "second"
    assert meta.serving_profile == "offline"

    async with migrated_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT count(*) AS n FROM index_meta")
        row = await cur.fetchone()
    assert row is not None
    assert row["n"] == 1


@pytest.mark.db
async def test_truncate_provisions_keeps_index_meta(repo: Repository) -> None:
    await repo.upsert_provisions([_stored(ref="AVG:art_1", doc="AVG", label="1")])
    await repo.write_index_meta(_meta())

    await repo.truncate_provisions()

    assert await repo.get_by_refs(["AVG:art_1"]) == []
    meta = await repo.read_index_meta()
    assert meta is not None
    assert meta.corpus_hash == "hash-one"


@pytest.mark.db
async def test_corpus_counts_groups_by_doc(repo: Repository) -> None:
    await repo.upsert_provisions(
        [
            _stored(ref="AVG:art_1", doc="AVG", label="1"),
            _stored(ref="AVG:art_2", doc="AVG", label="2"),
            _stored(ref="CRA:art_1", doc="CRA", label="1"),
        ]
    )

    counts = await repo.corpus_counts()
    assert counts == [
        DocumentCount(doc="AVG", provision_count=2),
        DocumentCount(doc="CRA", provision_count=1),
    ]


@pytest.mark.db
async def test_create_pool_checks_out_connection(database_url: str) -> None:
    async with await AsyncConnection.connect(database_url) as setup:
        await migrate(setup, MIGRATIONS_DIR)

    pool = create_pool(database_url)
    await pool.open()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                assert await cur.fetchone() == (1,)
    finally:
        await pool.close()
