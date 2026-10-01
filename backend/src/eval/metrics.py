# Evaluation metric helpers (backend copy).
from __future__ import annotations

from collections.abc import Iterable

from app.schemas.api import RetrievedEvent, SelectionEvent


def vector_hit(retrieved: RetrievedEvent, must_refs: Iterable[str]) -> bool:
    found = {item.ref for item in retrieved.provisions}
    return set(must_refs).issubset(found)


def selection_hit(selection: SelectionEvent, must_refs: Iterable[str]) -> bool:
    kept_and_added = set(selection.kept) | set(selection.added)
    return set(must_refs).issubset(kept_and_added)
