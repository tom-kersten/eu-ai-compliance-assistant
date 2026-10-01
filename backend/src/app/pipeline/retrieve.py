"""Retrieval helpers: protocols and retrieval function."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.providers.base import Embedder  # only for type checking
from app.schemas.domain import RetrievedProvision


class ProvisionSearch(Protocol):
    async def search_similar(
        self, query: Sequence[float], *, top_k: int, threshold: float
    ) -> list[RetrievedProvision]: ...


async def retrieve(
    query_text: str,
    *,
    embedder: Embedder,
    repository: ProvisionSearch,
    top_k: int,
    threshold: float | None,
) -> list[RetrievedProvision]:
    """Embed a text query and run repository vector search.

    - Calls `embedder.embed_query(query_text)` once.
    - If `threshold is None` pass -1.0 to repository to disable the cut.
    - Returns the repository results as-is (repository is responsible for ordering).
    """
    vector = await embedder.embed_query(query_text)
    th = threshold if threshold is not None else -1.0
    results = await repository.search_similar(vector, top_k=top_k, threshold=th)
    return results
