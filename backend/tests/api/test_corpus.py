"""API tests for GET /v1/corpus."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.schemas.domain import DocumentCount, IndexMeta

from .conftest import FakeProviders, StubRepository, make_manifest


class CorpusRepo(StubRepository):
    """Stub that serves corpus counts and index_meta for /v1/corpus."""

    def __init__(
        self,
        *,
        counts: list[DocumentCount],
        meta: IndexMeta | None,
    ) -> None:
        super().__init__()
        self._counts = counts
        self._meta = meta

    async def corpus_counts(self) -> list[DocumentCount]:
        return list(self._counts)

    async def read_index_meta(self) -> IndexMeta | None:
        return self._meta


@pytest.mark.api
def test_corpus_returns_documents_counts_and_snapshot() -> None:
    meta = IndexMeta(
        embedding_model="qwen/qwen3-embedding-8b",
        dimension=2000,
        serving_profile="online",
        corpus_snapshot=date(2026, 8, 11),
        corpus_hash="abc",
        ingested_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    )
    # AVG has no count row -> provision_count 0
    repo = CorpusRepo(
        counts=[DocumentCount(doc="DOC", provision_count=3)],
        meta=meta,
    )

    @asynccontextmanager
    async def repository_factory():
        yield repo

    async def healthy() -> None:
        return None

    app = create_app(
        Settings(),
        providers=FakeProviders(FakeEmbedder(), ScriptedLLM()),
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=make_manifest(),
    )
    client = TestClient(app)
    response = client.get("/v1/corpus")
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_date"] == "2026-08-11"
    docs = {d["key"]: d for d in body["documents"]}
    assert docs["DOC"]["provision_count"] == 3
    assert docs["DOC"]["short_name"] == "DOC"
    assert docs["DOC"]["identifier"] == "Verordening (EU) 0000/0"
    assert docs["AVG"]["provision_count"] == 0


@pytest.mark.api
def test_corpus_missing_index_meta_returns_503() -> None:
    repo = CorpusRepo(counts=[], meta=None)

    @asynccontextmanager
    async def repository_factory():
        yield repo

    async def healthy() -> None:
        return None

    app = create_app(
        Settings(),
        providers=FakeProviders(FakeEmbedder(), ScriptedLLM()),
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=make_manifest(),
    )
    client = TestClient(app)
    response = client.get("/v1/corpus")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "missing_index"
    assert body["message"]
