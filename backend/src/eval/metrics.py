# Evaluation metric helpers (backend copy).
from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.schemas.api import RetrievedEvent, SelectionEvent


def vector_hit(retrieved: RetrievedEvent, must_refs: Iterable[str]) -> bool:
    found = {item.ref for item in retrieved.provisions}
    return set(must_refs).issubset(found)


def selection_hit(selection: SelectionEvent, must_refs: Iterable[str]) -> bool:
    kept_and_added = set(selection.kept) | set(selection.added)
    return set(must_refs).issubset(kept_and_added)


def context_hit(final_refs: Iterable[str], must_refs: Iterable[str]) -> bool:
    """True when every must-ref is in the final context (kept plus added)."""
    return set(must_refs).issubset(set(final_refs))


def behavior_match(expected: str, actual: str) -> bool:
    return expected == actual


def empty_retrieval_ok(
    *,
    retrieved_count: int,
    action: str,
    llm_call_count: int,
) -> bool:
    """Q09-style: empty retrieval yields cannot_answer with zero LLM calls."""
    if retrieved_count != 0:
        return False
    return action == "cannot_answer" and llm_call_count == 0


def score_question(
    *,
    must_refs: Sequence[str],
    expected_behavior: str,
    retrieved_refs: Sequence[str],
    final_refs: Sequence[str],
    action: str,
    llm_call_count: int,
) -> dict[str, bool | int]:
    """Pure scoring for one eval question after a pipeline run."""
    return {
        "vector_hit": set(must_refs).issubset(set(retrieved_refs)),
        "context_hit": context_hit(final_refs, must_refs),
        "behavior_match": behavior_match(expected_behavior, action),
        "empty_retrieval_ok": empty_retrieval_ok(
            retrieved_count=len(retrieved_refs),
            action=action,
            llm_call_count=llm_call_count,
        ),
        "llm_call_count": llm_call_count,
    }
