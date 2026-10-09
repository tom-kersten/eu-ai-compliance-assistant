"""Simple fake runner for --use-fakes mode used by tests."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.schemas.api import (
    DisplayCitation,
    FinalEvent,
    RetrievedEvent,
    RetrievedItem,
    SelectionEvent,
    Usage,
)


def fake_for_question(
    qid: str,
    must: Iterable[str],
    expected_behavior: str = "answer",
) -> tuple[RetrievedEvent | None, SelectionEvent | None, FinalEvent]:
    """Return scripted events for one eval question.

    Empty must (Q09) simulates empty retrieval: cannot_answer with 0 LLM calls.
    Fakes mode checks plumbing only, not retrieval quality.
    """
    del qid  # reserved for per-question scripts if needed later
    must_list = list(must)
    if not must_list:
        usage = Usage(
            calls=0,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            prompt_versions={},
        )
        final = FinalEvent(
            action="cannot_answer",
            answer="Kan geen antwoord geven.",
            clarifying_questions=[],
            citations=[],
            situation={},
            usage=usage,
            corpus_snapshot=date.today(),
        )
        return RetrievedEvent(provisions=[]), None, final

    provisions = [RetrievedItem(ref=r, title=None, similarity=0.9) for r in must_list]
    retrieved = RetrievedEvent(provisions=provisions)
    kept = list(must_list)
    selection = SelectionEvent(kept=kept, discarded=[], added=[], unavailable=[])
    usage = Usage(
        calls=1,
        prompt_tokens=10,
        completion_tokens=20,
        reasoning_tokens=0,
        prompt_versions={},
    )
    action = (
        expected_behavior
        if expected_behavior
        in {
            "answer",
            "clarify",
            "cannot_answer",
        }
        else "answer"
    )
    if action == "clarify":
        answer_text: str | None = None
        questions = ["Kunt u preciseren?"]
        citations: list[DisplayCitation] = []
    elif action == "cannot_answer":
        answer_text = "Kan geen antwoord geven."
        questions = []
        citations = []
    else:
        answer_text = "faked"
        questions = []
        citations = [DisplayCitation(ref=r, header="", body="") for r in kept]
    final = FinalEvent(
        action=action,  # type: ignore[arg-type]
        answer=answer_text,
        clarifying_questions=questions,
        citations=citations,
        situation={},
        usage=usage,
        corpus_snapshot=date.today(),
    )
    return retrieved, selection, final
