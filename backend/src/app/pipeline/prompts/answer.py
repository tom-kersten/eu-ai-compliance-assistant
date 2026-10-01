from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from app.schemas.llm import Message, Situation

from . import load_prompt
from .provision_format import format_provision

ANSWER_PROMPT_VERSION = "T12v1"

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
    """Build the answer prompt messages list.

    - `final_context` is an iterable of dicts with keys: ref, header, body.
    - `unavailable` is an iterable of dicts with keys:
      citation, reason, detail (optional).
    - `documents` is an iterable of dicts with keys: key, short_name, identifier.
    """
    provisions = []
    for p in final_context:
        provisions.append(
            format_provision(p["ref"], p.get("header", ""), p.get("body", ""))
        )
    prov_block = "\n\n".join(provisions)

    docs_lines = []
    for d in documents:
        docs_lines.append(
            f"{d['key']}: {d.get('short_name', '')} ({d.get('identifier', '')})"
        )

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

    prompt_template = load_prompt("answer")
    content = prompt_template.format(
        version=ANSWER_PROMPT_VERSION,
        provisions=prov_block,
        documents="\n".join(docs_lines),
        unavailable="\n".join(unavailable_lines),
        situation=situation.model_dump(),
        snapshot=snapshot.isoformat(),
    )
    msgs = [m for m in conversation]
    msgs.append(Message(role="user", content=content))
    return msgs
