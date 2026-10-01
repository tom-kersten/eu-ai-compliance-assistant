\"\"\"Simple fake runner for --use-fakes mode used by tests.\"
from __future__ import annotations
from datetime import date
from typing import Iterable

from app.schemas.api import RetrievedEvent, RetrievedItem, SelectionEvent, FinalEvent, Usage, DisplayCitation


def fake_for_question(qid: str, must: Iterable[str]) -> tuple[RetrievedEvent | None, SelectionEvent | None, FinalEvent]:
    # Retrieved returns the must refs as RetrievedItems (simulate perfect retrieval)
    provisions = [RetrievedItem(ref=r, title=None, similarity=0.9) for r in must]
    retrieved = RetrievedEvent(provisions=provisions)

    kept = [r for r in must]
    selection = SelectionEvent(kept=kept, discarded=[], added=[], unavailable=[])

    usage = Usage(calls=1, prompt_tokens=10, completion_tokens=20, reasoning_tokens=0, prompt_versions={})
    final = FinalEvent(
        action="answer" if must else "cannot_answer",
        answer="faked" if must else "Kan geen antwoord geven.",
        clarifying_questions=[],
        citations=[DisplayCitation(ref=r, header="", body="") for r in kept],
        situation={},
        usage=usage,
        corpus_snapshot=date.today(),
    )
    return retrieved, selection, final

