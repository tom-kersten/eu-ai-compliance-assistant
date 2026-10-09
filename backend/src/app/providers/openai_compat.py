from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.schemas.llm import AnswerResult

from .base import LLM, Embedder, EmbeddingDimensionError

logger = logging.getLogger(__name__)


def openrouter_reasoning_params(effort: str | None) -> dict:
    """Map a reasoning effort level to OpenRouter's verified request fields.

    The vLLM equivalent is not verified yet (docs/PROVIDER_NOTES.md), so this is
    the only mapping and it is used for both profiles.
    """
    if not effort:
        return {}
    return {"reasoning": {"effort": effort, "exclude": False}}


class OpenRouterAdapter(Embedder, LLM):
    """Adapter implementing embeddings and LLM calls compatible with
    OpenRouter-like APIs.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
        # Keep attribute for test injection.
        self.client = self._client

    def _auth_headers(self, api_key: str) -> dict[str, str]:
        if not api_key:
            return {}
        return {"Authorization": f"Bearer {api_key}"}

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        url = f"{self.settings.embedding_base_url.rstrip('/')}/embeddings"
        payload = {
            "model": self.settings.embedding_model,
            "input": list(texts),
            "dimensions": int(self.settings.embedding_dimensions),
        }
        logger.debug(
            "embeddings request payload prepared",
            extra={"model": self.settings.embedding_model},
        )
        resp = await self.client.post(
            url,
            json=payload,
            headers=self._auth_headers(self.settings.embedding_api_key),
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        expected = int(self.settings.embedding_dimensions)
        for vec in embeddings:
            if len(vec) != expected:
                raise EmbeddingDimensionError("vector has wrong dimension")
        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        instruct = (
            "Instruct: Given a web search query, retrieve relevant passages "
            "that answer the query\nQuery:"
        )
        return (await self.embed_documents([f"{instruct}{query}"]))[0]

    async def respond(
        self,
        *,
        messages: Sequence[dict],
        schema: type[BaseModel] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        url = f"{self.settings.llm_base_url.rstrip('/')}/chat/completions"
        # The output schema identifies the pipeline step, so it also picks the model.
        model = (
            self.settings.answer_model
            if schema is AnswerResult
            else self.settings.selection_model
        )
        body: dict[str, Any] = {"model": model, "messages": list(messages)}
        if schema is not None:
            name = "".join(
                f"_{c.lower()}" if c.isupper() else c for c in schema.__name__
            ).lstrip("_")
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": name,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            }
        body.update(openrouter_reasoning_params(reasoning_effort))

        attempt = 0
        max_retries = int(self.settings.llm_max_retries)
        while True:
            try:
                logger.debug("LLM request prepared", extra={"model": body.get("model")})
                resp = await self.client.post(
                    url,
                    json=body,
                    headers=self._auth_headers(self.settings.llm_api_key),
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                parsed["usage"] = data.get("usage", {})
                return parsed
            except (
                httpx.HTTPStatusError,
                httpx.TimeoutException,
                json.JSONDecodeError,
                KeyError,
            ) as exc:
                if attempt >= max_retries:
                    logger.error("LLM request failed after retries", exc_info=exc)
                    raise
                backoff = 0.1 * (2**attempt)
                attempt += 1
                logger.debug(
                    "LLM request failed; retrying",
                    extra={"attempt": attempt, "backoff": backoff},
                )
                await asyncio.sleep(backoff)

    async def close(self) -> None:
        await self._client.aclose()
