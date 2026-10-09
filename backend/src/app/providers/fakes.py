from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from collections.abc import Sequence

from pydantic import BaseModel

from .base import LLM, Embedder


class FakeEmbedder(Embedder):
    """Deterministic hash-based embedder for unit tests."""

    def __init__(self, dimension: int = 2000) -> None:
        self.dimension = int(dimension)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_text(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._embed_text(query)

    def _embed_text(self, text: str) -> list[float]:
        # Use sha256 digest to produce deterministic bytes and normalize.
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand to needed length
        out = []
        i = 0
        while len(out) < self.dimension:
            # cycle through digest with index
            b = h[i % len(h)]
            out.append((b % 256) / 255.0)
            i += 1
        # normalize vector to unit length
        norm = sum(x * x for x in out) ** 0.5 or 1.0
        return [x / norm for x in out[: self.dimension]]


class ScriptedLLM(LLM):
    """A simple scripted LLM that returns queued responses for tests.

    Each response is a dict that will be returned as-is from `respond`.
    If the queue is empty, raise RuntimeError to fail loudly in tests.
    """

    def __init__(self, responses: Sequence[dict] | None = None) -> None:
        self._queue: deque[dict] = deque(responses or [])

    def push(self, response: dict) -> None:
        self._queue.append(response)

    async def respond(
        self,
        *,
        messages: Sequence[dict],
        schema: type[BaseModel] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        await asyncio.sleep(0)  # keep async signature
        if not self._queue:
            raise RuntimeError("ScriptedLLM queue is empty")
        result = self._queue.popleft()
        # Allow tests to attach a `usage` key to the queued response.
        # If a schema is provided, validate only the payload without `usage`,
        # since the structured-output schemas forbid extras.
        if schema is not None:
            payload = dict(result)
            payload.pop("usage", None)
            schema.model_validate(payload)
        return result
