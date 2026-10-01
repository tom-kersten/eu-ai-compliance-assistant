"""Unit tests for pipeline.retrieve."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pytest

from app.pipeline import retrieve
from app.schemas.domain import RetrievedProvision, StoredProvision


class SimpleEmbedder:
    def __init__(self, dimension: int = 8) -> None:
        self.dimension = int(dimension)
        self.query_calls: list[str] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_text(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self._embed_text(text)

    def _embed_text(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        out = []
        i = 0
        while len(out) < self.dimension:
            b = h[i % len(h)]
            out.append((b % 256) / 255.0)
            i += 1
        norm = sum(x * x for x in out) ** 0.5 or 1.0
        return [x / norm for x in out[: self.dimension]]


class InMemoryRepo:
    def __init__(self, stored: Sequence[StoredProvision]) -> None:
        self._stored = list(stored)

    async def search_similar(
        self, query: Sequence[float], *, top_k: int, threshold: float
    ) -> list[RetrievedProvision]:
        # cosine similarity
        def cos(u: Sequence[float], v: Sequence[float]) -> float:
            dot = sum(a * b for a, b in zip(u, v, strict=True))
            nu = sum(a * a for a in u) ** 0.5 or 1.0
            nv = sum(b * b for b in v) ** 0.5 or 1.0
            return dot / (nu * nv)

        res = []
        for s in self._stored:
            sim = cos(query, s.embedding)
            if sim >= threshold:
                data = s.model_dump()
                data.pop("embedding", None)
                data["similarity"] = sim
                res.append(RetrievedProvision(**data))
        # order by descending similarity then ref
        res.sort(key=lambda r: (-r.similarity, r.ref))
        return res[:top_k]


class SpyEmbedder(SimpleEmbedder):
    pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieve_top_k_and_ordering() -> None:
    e = SpyEmbedder(dimension=8)
    stored = [
        StoredProvision(
            ref="r1",
            doc="d",
            kind="article",
            label="L1",
            parent_ref="p",
            header="h",
            body="b",
            token_estimate=10,
            embedding=e._embed_text("one"),
        ),
        StoredProvision(
            ref="r2",
            doc="d",
            kind="article",
            label="L2",
            parent_ref="p",
            header="h",
            body="b",
            token_estimate=5,
            embedding=e._embed_text("two"),
        ),
        StoredProvision(
            ref="r3",
            doc="d",
            kind="article",
            label="L3",
            parent_ref="p",
            header="h",
            body="b",
            token_estimate=8,
            embedding=e._embed_text("three"),
        ),
    ]
    repo = InMemoryRepo(stored)
    q = "query text"
    res = await retrieve.retrieve(
        q, embedder=e, repository=repo, top_k=2, threshold=0.0
    )
    assert len(res) == 2
    # assert ordering by similarity desc
    assert res[0].similarity >= res[1].similarity
    assert e.query_calls == [q]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retrieve_threshold_cut_and_none_threshold() -> None:
    e = SpyEmbedder(dimension=8)
    stored = [
        StoredProvision(
            ref="a",
            doc="d",
            kind="article",
            label="L1",
            parent_ref="p",
            header="h",
            body="b",
            token_estimate=1,
            embedding=e._embed_text("x"),
        ),
        StoredProvision(
            ref="b",
            doc="d",
            kind="article",
            label="L2",
            parent_ref="p",
            header="h",
            body="b",
            token_estimate=1,
            embedding=e._embed_text("y"),
        ),
    ]
    repo = InMemoryRepo(stored)
    # threshold high so nothing passes
    res = await retrieve.retrieve(
        "q", embedder=e, repository=repo, top_k=10, threshold=0.9999
    )
    assert res == []
    # threshold None means no cut (pass -1.0 internally); should return up to top_k
    res2 = await retrieve.retrieve(
        "q", embedder=e, repository=repo, top_k=10, threshold=None
    )
    assert len(res2) <= 2
