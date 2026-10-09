"""API tests for request-id logging and no message content at INFO."""

from __future__ import annotations

import logging
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
    selection_payload,
)

DISTINCTIVE = "UNIQUE_SECRET_QUESTION_XYZ_991"


@pytest.mark.api
def test_ask_logs_request_id_without_message_content_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    caplog.clear()
    with caplog.at_level(logging.INFO):
        response = client.post(
            "/v1/ask",
            json={"messages": [{"role": "user", "content": DISTINCTIVE}]},
            headers={"X-Request-Id": "log-req-42"},
        )

    assert response.status_code == 200
    assert response.headers.get("x-request-id") == "log-req-42"

    # Only assert on application loggers; TestClient's httpx logger runs
    # outside the request context.
    app_records = [r for r in caplog.records if r.name.startswith("app.")]
    info_records = [r for r in app_records if r.levelno == logging.INFO]
    assert info_records, "expected at least one INFO log record from app.*"
    for record in app_records:
        assert getattr(record, "request_id", None) == "log-req-42"
        assert DISTINCTIVE not in record.getMessage()
