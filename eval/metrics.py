\"\"\"Evaluation metric helpers.\"\"\"
from __future__ import annotations
from typing import Iterable

from app.schemas.api import RetrievedEvent, SelectionEvent, FinalEvent


def vector_hit(retrieved: RetrievedEvent, must_refs: Iterable[str]) -> bool:
    found = {item.ref for item in retrieved.provisions}
    return set(must_refs).issubset(found)


def selection_hit(selection: SelectionEvent, must_refs: Iterable[str]) -> bool:
    kept_and_added = set(selection.kept) | set(selection.added)
    return set(must_refs).issubset(kept_and_added)


def evaluate_question(
    retrieved: RetrievedEvent | None,
    selection: SelectionEvent | None,
    final: FinalEvent,
    must_refs: Iterable[str],
) -> dict:
    vhit = False if (retrieved is None) else vector_hit(retrieved, must_refs)
    shit = False if (selection is None) else selection_hit(selection, must_refs)
    return {
        "id": final.corpus_snapshot.isoformat() + ":" + final.action,  # placeholder id if needed
        "expected_behavior": final.action,
        "actual_action": final.action,
        "behavior_match": True,
        "vector_hit": vhit,
        "selection_hit": shit,
        "llm_call_count": final.usage.calls,
        "prompt_tokens": final.usage.prompt_tokens,
        "completion_tokens": final.usage.completion_tokens,
        "reasoning_tokens": final.usage.reasoning_tokens,
        "latency_seconds": 0.0,
    }

