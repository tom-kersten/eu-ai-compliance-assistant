"""Shared fixtures and helpers for the api suite."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from app.config import Settings
from app.ingestion.manifest import CorpusManifest, DocumentSpec
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.schemas.domain import RetrievedProvision
from app.store.health import HealthReason, HealthResult


@dataclass
class FakeProviders:
    embedder: FakeEmbedder
    llm: ScriptedLLM


@dataclass
class StubRepository:
    """In-memory repository for api tests. Optionally raises on search."""

    results: list[RetrievedProvision] = field(default_factory=list)
    search_error: Exception | None = None
    search_calls: int = 0
    released: bool = False

    async def search_similar(
        self, query: Sequence[float], *, top_k: int, threshold: float
    ) -> list[RetrievedProvision]:
        self.search_calls += 1
        if self.search_error is not None:
            raise self.search_error
        return list(self.results)

    async def get_by_parent_ref(self, parent_ref: str) -> list[Any]:
        return []

    async def get_by_refs(self, refs: Sequence[str]) -> list[Any]:
        return []


def make_retrieved(ref: str, *, similarity: float = 0.9) -> RetrievedProvision:
    return RetrievedProvision(
        ref=ref,
        doc="DOC",
        kind="article",
        label="1",
        parent_ref=ref,
        header="H",
        body="B",
        token_estimate=1,
        similarity=similarity,
    )


def make_manifest() -> CorpusManifest:
    return CorpusManifest(
        snapshot=date(2026, 8, 11),
        documents=[
            DocumentSpec(
                key="DOC",
                file="raw/doc.html",
                parser="consolidated",
                short_name="DOC",
                long_name="Document",
                identifier="Verordening (EU) 0000/0",
                include="all",
            ),
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


def make_health(
    reason: HealthReason | None = None,
    detail: str = "detail",
) -> HealthResult | None:
    if reason is None:
        return None
    return HealthResult(reason=reason, detail=detail)


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse raw SSE text into (event_name, data_dict) pairs."""
    import json

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


def selection_payload(ref: str = "DOC:art_1") -> dict[str, Any]:
    return {
        "keep": [ref],
        "discard": [],
        "request": [],
        "external_references": [],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }


def answer_payload(ref: str = "DOC:art_1") -> dict[str, Any]:
    return {
        "reasoning": "r",
        "action": "answer",
        "answer": "antwoord",
        "clarifying_questions": [],
        "citations": [ref],
        "situation": {"role": "unknown", "domain": None, "notes": None},
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }


@pytest.fixture
def settings() -> Settings:
    return Settings(
        llm_api_key="test",
        embedding_api_key="test",
        embedding_model="qwen/qwen3-embedding-8b",
        embedding_dimensions=2000,
        similarity_threshold=0.5,
        llm_max_retries=0,
    )


def repository_factory_for(repo: StubRepository):
    @asynccontextmanager
    async def factory() -> AsyncIterator[StubRepository]:
        try:
            yield repo
        finally:
            repo.released = True

    return factory
