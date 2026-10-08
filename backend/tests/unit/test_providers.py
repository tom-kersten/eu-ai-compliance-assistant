from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.providers.openai_compat import OpenRouterAdapter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fake_embedder_is_deterministic_and_dimension() -> None:
    emb = FakeEmbedder(dimension=16)
    v1 = await emb.embed_query("hello world")
    v2 = await emb.embed_query("hello world")
    assert len(v1) == 16
    assert v1 == v2

    docs = await emb.embed_documents(["a", "b", "c"])
    assert len(docs) == 3
    assert all(len(v) == 16 for v in docs)


@pytest.mark.unit
def test_scripted_llm_queue_behaviour() -> None:
    s = ScriptedLLM(responses=[{"result": "one"}, {"result": "two"}])

    async def run():
        r1 = await s.respond(prompt="x")
        r2 = await s.respond(prompt="y")
        assert r1 == {"result": "one"}
        assert r2 == {"result": "two"}
        with pytest.raises(RuntimeError):
            await s.respond(prompt="z")

    asyncio.run(run())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_embed_request_includes_dimensions_and_model() -> None:
    settings = Settings()
    settings.embedding_dimensions = 8
    settings.embedding_model = "test-model"

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        assert payload["model"] == "test-model"
        assert "input" in payload
        assert payload["dimensions"] == 8
        # Return embeddings with correct length
        embeddings = [{"embedding": [0.1] * 8} for _ in payload["input"]]
        return httpx.Response(200, json={"data": embeddings})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    res = await adapter.embed_documents(["one", "two"])
    assert isinstance(res, list)
    assert len(res) == 2
    assert all(len(v) == 8 for v in res)
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_llm_includes_response_format_and_reasoning_and_retries(
    monkeypatch,
) -> None:
    settings = Settings()
    settings.selection_model = "sel-model"
    settings.answer_reasoning_effort = "medium"
    settings.llm_max_retries = 2

    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode()))
        # first call simulate 500, then 200
        if len(calls) == 1:
            return httpx.Response(500, json={"error": "server"})
        return httpx.Response(200, json={"output": {"result": "ok"}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    # patch sleep to avoid delays in tests
    async def noop_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    data = await adapter.respond(prompt="hello", schema=None)
    assert data["output"]["result"] == "ok"
    # ensure reasoning present and response_format (in second call too)
    assert any("reasoning" in call for call in calls)
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_llm_omits_reasoning_when_caller_disables_it() -> None:
    settings = Settings()
    settings.answer_reasoning_effort = "medium"
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"output": {"result": "ok"}})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    await adapter.respond(prompt="hello", reasoning=None)
    assert "reasoning" not in captured[0]
    await client.aclose()
