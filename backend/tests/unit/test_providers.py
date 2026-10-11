from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.providers.openai_compat import OpenRouterAdapter
from app.schemas.llm import AnswerResult, SelectionResult


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
    msgs = [{"role": "user", "content": "x"}]

    async def run():
        r1 = await s.respond(messages=msgs)
        r2 = await s.respond(messages=msgs)
        assert r1 == {"result": "one"}
        assert r2 == {"result": "two"}
        with pytest.raises(RuntimeError):
            await s.respond(messages=msgs)

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
    settings.llm_max_retries = 2

    calls = []

    def _chat_completion(result: dict) -> dict:
        return {
            "choices": [{"message": {"content": json.dumps(result)}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode()))
        # first call simulate 500, then 200
        if len(calls) == 1:
            return httpx.Response(500, json={"error": "server"})
        return httpx.Response(200, json=_chat_completion({"result": "ok"}))

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    # patch sleep to avoid delays in tests
    async def noop_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", noop_sleep)

    data = await adapter.respond(
        messages=[{"role": "user", "content": "hello"}],
        schema=None,
        reasoning_effort="medium",
    )
    assert data["result"] == "ok"
    assert len(calls) == 2
    # The adapter maps the effort level to OpenRouter's verified format.
    for call in calls:
        assert call["reasoning"] == {"effort": "medium", "exclude": False}
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_llm_uses_the_model_for_the_calling_step() -> None:
    """select() always passes schema=SelectionResult, answer() always passes
    schema=AnswerResult, so respond() must route to selection_model /
    answer_model accordingly, even when the two differ."""
    settings = Settings()
    settings.selection_model = "sel-model"
    settings.answer_model = "ans-model"
    sent_models: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent_models.append(json.loads(request.content.decode())["model"])
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"result": "ok"})}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    await adapter.respond(
        messages=[{"role": "user", "content": "x"}], schema=SelectionResult
    )
    await adapter.respond(
        messages=[{"role": "user", "content": "x"}], schema=AnswerResult
    )
    assert sent_models == ["sel-model", "ans-model"]
    await client.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_llm_omits_reasoning_when_effort_is_off() -> None:
    settings = Settings()
    settings.answer_reasoning_effort = "medium"
    settings.selection_reasoning_effort = "low"
    captured: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"result": "ok"})}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    await adapter.respond(
        messages=[{"role": "user", "content": "hello"}], reasoning_effort=None
    )
    # Settings must not leak in as a default; None means reasoning is off.
    await adapter.respond(messages=[{"role": "user", "content": "hello"}])
    assert "reasoning" not in captured[0]
    assert "reasoning" not in captured[1]
    await client.aclose()


class _KeepAliveBody(httpx.AsyncByteStream):
    """A body that sends a byte now and then but never finishes, like a
    provider that keeps the connection alive while the model hangs."""

    async def __aiter__(self):
        while True:
            await asyncio.sleep(0.01)
            yield b" "


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_llm_deadline_covers_the_whole_call() -> None:
    """httpx timeouts only bound the gap between bytes, so a trickling body
    would never time out. LLM_TIMEOUT_SECONDS must bound each whole attempt."""
    settings = Settings()
    settings.llm_timeout_seconds = 0.2
    settings.llm_max_retries = 1
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=_KeepAliveBody())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenRouterAdapter(settings)
    adapter.client = client

    task = asyncio.create_task(
        adapter.respond(messages=[{"role": "user", "content": "x"}])
    )
    done, _ = await asyncio.wait({task}, timeout=5)
    if not done:
        task.cancel()
        pytest.fail("respond() kept waiting on a body that never finishes")
    with pytest.raises(TimeoutError):
        task.result()
    # The deadline counts as a retryable failure, like an httpx timeout.
    assert calls == 2
    await client.aclose()
