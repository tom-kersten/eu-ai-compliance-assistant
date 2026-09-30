"""Replaceable character-based token estimator for chunking."""

from __future__ import annotations

import math


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: ceil(len(text) / 3)."""
    if not text:
        return 0
    return math.ceil(len(text) / 3)
