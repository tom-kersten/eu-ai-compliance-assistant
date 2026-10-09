from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 0


class EmbeddingDimensionError(ValueError):
    """Raised when a provider returns vectors of an unexpected length."""


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LLM(Protocol):
    async def respond(
        self,
        *,
        messages: Sequence[dict],
        schema: type[BaseModel] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict: ...
