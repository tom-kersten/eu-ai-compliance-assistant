"""API tests for SSE error events and exception mapping."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.errors import AnswerInvalid, SelectionInvalid
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.schemas.api import StatusEvent

from .conftest import (
    FakeProviders,
    StubRepository,
    make_manifest,
    make_retrieved,
    parse_sse,
)


def _client(*, repo: StubRepository | None = None) -> TestClient:
    stub = repo or StubRepository(results=[make_retrieved("DOC:art_1")])

    @asynccontextmanager
    async def repository_factory():
        yield stub

    async def healthy() -> None:
        return None

    app = create_app(
        Settings(similarity_threshold=0.5, llm_max_retries=0),
        providers=FakeProviders(FakeEmbedder(), ScriptedLLM()),
        repository_factory=repository_factory,
        health_check=healthy,
        corpus=make_manifest(),
    )
    return TestClient(app)


@pytest.mark.api
def test_orchestrator_error_event_passes_through_once() -> None:
    repo = StubRepository(search_error=RuntimeError("db down"))
    client = _client(repo=repo)
    response = client.post(
        "/v1/ask",
        json={"messages": [{"role": "user", "content": "vraag"}]},
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    error_events = [(n, p) for n, p in events if n == "error"]
    assert len(error_events) == 1
    assert error_events[0][1]["code"] == "retrieval_failed"
    # Stream closes after the error: no events after it
    assert events[-1][0] == "error"


@pytest.mark.api
@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (SelectionInvalid(["bad"]), "selection_invalid"),
        (AnswerInvalid(["bad"]), "answer_invalid"),
        (httpx.ConnectError("boom"), "provider_error"),
        (RuntimeError("surprise"), "internal_error"),
    ],
)
def test_escaped_exception_maps_to_error_code(exc: Exception, code: str) -> None:
    async def raising_run(*_args: Any, **_kwargs: Any) -> AsyncIterator[object]:
        yield StatusEvent(step="searching")
        raise exc

    with patch("app.api.routes.run", raising_run):
        client = _client()
        response = client.post(
            "/v1/ask",
            json={"messages": [{"role": "user", "content": "vraag"}]},
        )
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[0][0] == "status"
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == code
    assert events[-1][1]["message"]
    # No user content in the message
    assert "vraag" not in events[-1][1]["message"]
    assert len([e for e in events if e[0] == "error"]) == 1
