"""API tests for client disconnect between SSE steps."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.api.sse import stream_events
from app.providers.fakes import ScriptedLLM
from app.schemas.api import StatusEvent

from .conftest import StubRepository


class _FakeRequest:
    def __init__(self) -> None:
        self._calls = 0

    async def is_disconnected(self) -> bool:
        self._calls += 1
        # After the first event is yielded and checked, report disconnected.
        return self._calls >= 1


@pytest.mark.api
async def test_disconnect_closes_generator_and_releases_factory() -> None:
    released = {"done": False}
    closed = {"done": False}
    llm = ScriptedLLM(
        [{"keep": [], "discard": [], "request": [], "external_references": []}]
    )
    repo = StubRepository()
    search_before = repo.search_calls

    async def orchestrator() -> AsyncIterator[object]:
        try:
            yield StatusEvent(step="searching")
            # Would call search / LLM next if not stopped
            await repo.search_similar([0.0], top_k=1, threshold=0.0)
            await llm.respond(messages=[{"role": "user", "content": "x"}])
            yield StatusEvent(step="selecting")
        finally:
            closed["done"] = True

    @asynccontextmanager
    async def factory() -> AsyncIterator[StubRepository]:
        try:
            yield repo
        finally:
            released["done"] = True
            repo.released = True

    request = _FakeRequest()
    gen = stream_events(request, orchestrator())

    # Also exercise the ask-level path: acquire factory, wrap, release.
    chunks: list[str] = []
    async with factory() as _repo:
        async for chunk in gen:
            chunks.append(chunk)

    assert len(chunks) == 1
    assert "searching" in chunks[0]
    assert closed["done"] is True
    assert released["done"] is True
    assert repo.released is True
    # Pipeline did not advance past the first event
    assert repo.search_calls == search_before
    assert len(llm._queue) == 1
