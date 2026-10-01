from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 0


class EmbeddingDimensionError(ValueError):
    """Raised when a provider returns vectors of an unexpected length."""


class StructuredOutputError(ValueError):
    """Raised when structured output cannot be produced after retries."""


# Minimal placeholder schemas exported for convenience/import stability in tests.
class SelectionResultSchema(BaseModel):
    # Minimal shape used to request structured output; concrete schemas live
    # in schemas/llm.py
    result: Any


class AnswerResultSchema(BaseModel):
    result: Any


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LLM(Protocol):
    async def respond(
        self,
        *,
        prompt: str | None = None,
        messages: Sequence[dict] | None = None,
        schema: BaseModel | None = None,
        reasoning: dict | None = None,
    ) -> dict: ...
