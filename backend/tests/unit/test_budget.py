"""Unit tests for pipeline.budget."""

from __future__ import annotations

import logging

import pytest

from app.pipeline.budget import apply_budget
from app.schemas.domain import RetrievedProvision


def make_r(ref: str, tokens: int) -> RetrievedProvision:
    return RetrievedProvision(
        ref=ref,
        doc="d",
        kind="article",
        label="L",
        parent_ref="p",
        header="h",
        body="b",
        token_estimate=tokens,
        similarity=0.5,
    )


@pytest.mark.unit
def test_budget_within_keeps_all() -> None:
    items = [make_r("a", 10), make_r("b", 5)]
    kept = apply_budget(items, budget=20)
    assert [p.ref for p in kept] == ["a", "b"]


@pytest.mark.unit
def test_budget_drops_tail_until_fit() -> None:
    items = [make_r("a", 10), make_r("b", 8), make_r("c", 7)]
    kept = apply_budget(items, budget=18)
    # total tokens kept should be <= 18 and order preserved
    assert [p.ref for p in kept] == ["a", "b"]
    assert sum(p.token_estimate for p in kept) <= 18


@pytest.mark.unit
def test_budget_top_exceeds_warns(caplog) -> None:
    caplog.set_level(logging.WARNING)
    items = [make_r("top", 50), make_r("other", 5)]
    kept = apply_budget(items, budget=20)
    assert [p.ref for p in kept] == ["top"]
    assert any("Top provision exceeds budget" in r.message for r in caplog.records)


@pytest.mark.unit
def test_budget_none_keeps_all() -> None:
    items = [make_r("a", 3), make_r("b", 4)]
    kept = apply_budget(items, budget=None)
    assert [p.ref for p in kept] == ["a", "b"]
