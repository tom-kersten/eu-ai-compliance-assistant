"""Prompt budget application utilities."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TypeVar

from app.schemas.domain import Provision

P = TypeVar("P", bound=Provision)

logger = logging.getLogger(__name__)


def apply_budget[P](provisions: Sequence[P], budget: int | None) -> list[P]:
    """Keep top provisions while respecting a token budget.

    - Preserves order of `provisions`.
    - If budget is None, return all.
    - Always keep the first item. If the first alone exceeds the budget,
      keep it and log a warning with its ref and the numbers.
    - Otherwise drop items from the tail until the total token_estimate
      is <= budget.
    """
    if not provisions:
        return []
    if budget is None:
        return list(provisions)

    kept: list[P] = list(provisions)
    total = sum(p.token_estimate for p in kept)
    # always keep first
    first = kept[0]
    if first.token_estimate > budget:
        logger.warning(
            "Top provision exceeds budget",
            extra={
                "ref": first.ref,
                "top_tokens": first.token_estimate,
                "budget": budget,
            },
        )
        return [first]

    # drop from tail until fits
    while total > budget and len(kept) > 1:
        removed = kept.pop()  # drop lowest-ranked (tail)
        total -= removed.token_estimate
    return kept
