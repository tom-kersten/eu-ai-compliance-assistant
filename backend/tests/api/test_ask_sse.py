"""API tests for POST /v1/ask SSE happy path."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.providers.fakes import FakeEmbedder, ScriptedLLM

from .conftest import (
    FakeProviders,
    StubRepository,
    answer_payload,
    make_manifest,
    make_retrieved,
    parse_sse,
    selection_payload,
)


@pytest.mark.api
def test_ask_sse_event_order_and_headers() -> None:
    ref = "DOC:art_1"
    repo = StubRepository(results=[make_retrieved(ref)])
    llm = ScriptedLLM([selection_payload(ref), answer_payload(ref)])

    @asynccontextmanager
    async def repository_factory():
        yield repo

    async def healthy() -> None:
        return None

    app = create_app(
        Settings(similarity_threshold=0.5, llm_max_retries=0),
        providers=FakeProviders(FakeEmbedder(), llm),
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=make_manifest(),
    )
    client = TestClient(app)
    response = client.post(
        "/v1/ask",
        json={"messages": [{"role": "user", "content": "vraag"}]},
        headers={"X-Request-Id": "req-test-123"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-request-id") == "req-test-123"

    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == [
        "status",
        "retrieved",
        "status",
        "selection",
        "status",
        "final",
    ]
    assert events[0][1]["step"] == "searching"
    assert events[2][1]["step"] == "selecting"
    assert events[4][1]["step"] == "answering"
    assert events[5][1]["action"] == "answer"

    # Raw SSE shape: event line, data line, blank-line separator
    chunks = [c for c in response.text.split("\n\n") if c.strip()]
    for chunk in chunks:
        lines = chunk.split("\n")
        assert any(line.startswith("event:") for line in lines)
        assert any(line.startswith("data:") for line in lines)


@pytest.mark.api
def test_ask_generates_request_id_when_absent() -> None:
    ref = "DOC:art_1"
    repo = StubRepository(results=[make_retrieved(ref)])
    llm = ScriptedLLM([selection_payload(ref), answer_payload(ref)])

    @asynccontextmanager
    async def repository_factory():
        yield repo

    async def healthy() -> None:
        return None

    app = create_app(
        Settings(similarity_threshold=0.5, llm_max_retries=0),
        providers=FakeProviders(FakeEmbedder(), llm),
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=make_manifest(),
    )
    client = TestClient(app)
    response = client.post(
        "/v1/ask",
        json={"messages": [{"role": "user", "content": "vraag"}]},
    )
    request_id = response.headers.get("x-request-id")
    assert request_id
    assert " " not in request_id
