"""API tests for POST /v1/ask prechecks (503 / 422)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.store.health import HealthResult

from .conftest import FakeProviders, StubRepository, make_health, make_manifest


def _app(*, health_result: HealthResult | None):
    async def check() -> HealthResult | None:
        return health_result

    @asynccontextmanager
    async def repository_factory():
        yield StubRepository()

    return create_app(
        Settings(),
        providers=FakeProviders(FakeEmbedder(), ScriptedLLM()),
        repository_factory=repository_factory,
        health_check=check,
        corpus=make_manifest(),
    )


@pytest.mark.api
def test_ask_missing_index_returns_503_without_stream() -> None:
    client = TestClient(
        _app(health_result=make_health("missing_index", detail="no index"))
    )
    response = client.post(
        "/v1/ask",
        json={"messages": [{"role": "user", "content": "vraag"}]},
    )
    assert response.status_code == 503
    body = response.json()
    assert body == {"code": "missing_index", "message": body["message"]}
    assert body["message"]
    content_type = response.headers.get("content-type", "")
    assert "text/event-stream" not in content_type


@pytest.mark.api
@pytest.mark.parametrize(
    "body",
    [
        {},  # missing messages
        {"messages": [{"role": "user", "content": "x"}], "extra": "nope"},
        {"messages": [{"role": "system", "content": "x"}]},  # bad role
    ],
)
def test_ask_malformed_body_returns_422(body: dict) -> None:
    client = TestClient(
        _app(health_result=make_health("missing_index", detail="no index"))
    )
    response = client.post("/v1/ask", json=body)
    assert response.status_code == 422
