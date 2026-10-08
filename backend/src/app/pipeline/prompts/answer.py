from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from app.schemas.llm import Message, Situation

from . import load_prompt
from .provision_format import format_provision
from .situation_format import format_situation

ANSWER_PROMPT_VERSION = "T18v3"

UNAVAILABLE_REASON_TEXT = {
    "not_indexed": "not in the corpus (not indexed)",
    "external": "external reference, not in the corpus",
    "over_cap": "in the corpus but not provided because the context limit was reached",
}


def build_answer_prompt(
    conversation: Iterable[Message],
    situation: Situation,
    final_context: Iterable[dict],
    unavailable: Sequence[dict],
    documents: Iterable[dict],
    snapshot: date,
) -> list[Message]:
    """Build answer prompt messages from conversation and final context.

    - `final_context` is an iterable of dicts with keys: ref, header, body.
    - `unavailable` is an iterable of dicts with keys:
      citation, reason, detail (optional).
    - `documents` is an iterable of dicts with keys: key, short_name, identifier.
    """
    provisions = [
        format_provision(p["ref"], p.get("header", ""), p.get("body", ""))
        for p in final_context
    ]
    docs_lines = [
        f"{d['key']}: {d.get('short_name', '')} ({d.get('identifier', '')})"
        for d in documents
    ]
    unavailable_lines = []
    for u in unavailable:
        reason_text = UNAVAILABLE_REASON_TEXT.get(
            u.get("reason", ""), u.get("reason", "")
        )
        detail = u.get("detail")
        if detail:
            unavailable_lines.append(f"{u.get('citation')}: {reason_text} ({detail})")
        else:
            unavailable_lines.append(f"{u.get('citation')}: {reason_text}")

    content = load_prompt("answer").format(
        version=ANSWER_PROMPT_VERSION,
        provisions="\n\n".join(provisions),
        documents="\n".join(docs_lines),
        unavailable="\n".join(unavailable_lines),
        situation=format_situation(situation),
        snapshot=snapshot.isoformat(),
    )
    msgs = list(conversation)
    msgs.append(Message(role="user", content=content))
    return msgs
