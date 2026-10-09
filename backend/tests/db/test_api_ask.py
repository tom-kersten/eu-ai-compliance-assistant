"""Real-database API tests for /health, /v1/corpus, and /v1/ask."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from psycopg import AsyncConnection

from app.api.main import create_app
from app.config import Settings
from app.ingestion.manifest import CorpusManifest, DocumentSpec
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.schemas.domain import IndexMeta, StoredProvision
from app.store.db import create_pool
from app.store.migrate import migrate
from app.store.repository import Repository

from .conftest import MIGRATIONS_DIR

_DIM = 2000  # must match vector(2000) from the migration
_QUESTION = "wat is artikel 1"


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for chunk in raw.split("\n\n"):
        if not chunk.strip():
            continue
        event_name: str | None = None
        data_lines: list[str] = []
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
        if event_name is None:
            continue
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        events.append((event_name, payload))
    return events


def _manifest() -> CorpusManifest:
    return CorpusManifest(
        snapshot=date(2026, 8, 11),
        documents=[
            DocumentSpec(
                key="AVG",
                file="raw/avg.html",
                parser="consolidated",
                short_name="AVG",
                long_name="AVG",
                identifier="Verordening (EU) 2016/679",
                include="all",
            ),
        ],
    )


async def _seed(
    conn: AsyncConnection, settings: Settings, embedding: list[float]
) -> None:
    repo = Repository(conn)
    await repo.upsert_provisions(
        [
            StoredProvision(
                ref="AVG:art_1",
                doc="AVG",
                kind="article",
                label="1",
                parent_ref="AVG:art_1",
                part_no=1,
                part_count=1,
                title="Titel",
                chapter=None,
                section=None,
                part_label=None,
                header="header AVG art 1",
                body="1. tekst van artikel 1",
                token_estimate=10,
                amended_by=[],
                embedding=embedding,
            )
        ]
    )
    await repo.write_index_meta(
        IndexMeta(
            embedding_model=settings.embedding_model,
            dimension=settings.embedding_dimensions,
            serving_profile="online",
            corpus_snapshot=date(2026, 8, 11),
            corpus_hash="testhash",
            ingested_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )
    )
    await conn.commit()


def _selection(ref: str = "AVG:art_1") -> dict[str, Any]:
    return {
        "keep": [ref],
        "discard": [],
        "request": [],
        "external_references": [],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _answer(ref: str = "AVG:art_1") -> dict[str, Any]:
    return {
        "reasoning": "r",
        "action": "answer",
        "answer": "antwoord uit de wet",
        "clarifying_questions": [],
        "citations": [ref],
        "situation": {"role": "unknown", "domain": None, "notes": None},
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


@pytest.fixture
async def seeded_stack(
    database_url: str,
) -> AsyncIterator[tuple[Any, Any]]:
    async with await AsyncConnection.connect(database_url) as conn:
        await migrate(conn, MIGRATIONS_DIR)
        settings = Settings(
            database_url=database_url,
            embedding_model="test-embed",
            embedding_dimensions=_DIM,
            similarity_threshold=0.0,
            llm_max_retries=0,
        )
        embedder = FakeEmbedder(dimension=_DIM)
        embedding = await embedder.embed_query(_QUESTION)
        await _seed(conn, settings, embedding)

    pool = create_pool(database_url)
    await pool.open()

    @asynccontextmanager
    async def repository_factory() -> AsyncIterator[Repository]:
        async with pool.connection() as conn:
            yield Repository(conn)

    llm = ScriptedLLM([_selection(), _answer()])
    providers = type("P", (), {"embedder": embedder, "llm": llm})()
    # Real health check via repository connections; no injected health_check.
    app = create_app(
        settings,
        providers=providers,
        repository_factory=repository_factory,
        corpus=_manifest(),
    )
    try:
        yield app, pool
    finally:
        await pool.close()


@pytest.mark.db
async def test_real_db_health_corpus_and_ask_sequence(
    seeded_stack: tuple[Any, Any],
) -> None:
    app, _pool = seeded_stack
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        corpus = await client.get("/v1/corpus")
        assert corpus.status_code == 200
        body = corpus.json()
        assert body["snapshot_date"] == "2026-08-11"
        assert body["documents"][0]["key"] == "AVG"
        assert body["documents"][0]["provision_count"] == 1

        ask = await client.post(
            "/v1/ask",
            json={"messages": [{"role": "user", "content": _QUESTION}]},
        )
        assert ask.status_code == 200
        assert ask.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(ask.text)
        names = [n for n, _ in events]
        assert names == [
            "status",
            "retrieved",
            "status",
            "selection",
            "status",
            "final",
        ]
        assert events[0][1]["step"] == "searching"
        assert events[-1][1]["action"] == "answer"


@pytest.mark.db
async def test_two_concurrent_asks_use_distinct_connections(
    database_url: str,
) -> None:
    async with await AsyncConnection.connect(database_url) as conn:
        await migrate(conn, MIGRATIONS_DIR)
        settings = Settings(
            database_url=database_url,
            embedding_model="test-embed",
            embedding_dimensions=_DIM,
            similarity_threshold=0.0,
            llm_max_retries=0,
        )
        embedder = FakeEmbedder(dimension=_DIM)
        embedding = await embedder.embed_query(_QUESTION)
        await _seed(conn, settings, embedding)

    gate = asyncio.Event()
    entered = asyncio.Event()
    in_flight: list[int] = []
    lock = asyncio.Lock()

    class TrackingRepo(Repository):
        async def search_similar(  # type: ignore[no-untyped-def]
            self, query, *, top_k, threshold
        ):
            async with self._conn.cursor() as cur:
                await cur.execute("SELECT pg_backend_pid()")
                row = await cur.fetchone()
            assert row is not None
            pid = int(row[0])
            async with lock:
                in_flight.append(pid)
                if len(in_flight) >= 2:
                    entered.set()
            await gate.wait()
            return await super().search_similar(query, top_k=top_k, threshold=threshold)

    pool = create_pool(database_url)
    await pool.open()

    @asynccontextmanager
    async def repository_factory() -> AsyncIterator[Repository]:
        async with pool.connection() as conn:
            yield TrackingRepo(conn)

    class ConcurrentLLM:
        """Schema-based stub so concurrent asks do not race a shared queue."""

        async def respond(self, **kwargs: Any) -> dict[str, Any]:
            schema = kwargs.get("schema")
            name = getattr(schema, "__name__", "") if schema is not None else ""
            if name == "SelectionResult":
                return _selection()
            return _answer()

    providers = type("P", (), {"embedder": embedder, "llm": ConcurrentLLM()})()

    async def healthy() -> None:
        return None

    app = create_app(
        settings,
        providers=providers,
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=_manifest(),
    )

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:

            async def one() -> httpx.Response:
                return await client.post(
                    "/v1/ask",
                    json={"messages": [{"role": "user", "content": _QUESTION}]},
                    timeout=30.0,
                )

            t1 = asyncio.create_task(one())
            t2 = asyncio.create_task(one())
            await asyncio.wait_for(entered.wait(), timeout=10.0)
            assert len(set(in_flight[:2])) == 2
            gate.set()
            r1, r2 = await asyncio.gather(t1, t2)
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert _parse_sse(r1.text)[-1][0] == "final"
            assert _parse_sse(r2.text)[-1][0] == "final"
    finally:
        await pool.close()
