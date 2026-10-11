from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.schemas.llm import Message, Situation

from . import load_prompt
from .provision_format import format_provision
from .situation_format import format_situation

SELECTION_PROMPT_VERSION = "v3"


def build_selection_prompt(
    conversation: Iterable[Message],
    situation: Situation,
    retrieved: Iterable[dict],
    documents: Iterable[dict],
    snapshot: date,
    max_added: int | None,
) -> list[Message]:
    """Build selection prompt messages from conversation and retrieved provisions.

    - `retrieved` is an iterable of dicts with keys: ref, header, body.
    - `documents` is an iterable of dicts with keys: key, short_name, identifier.
    """
    provisions = [
        format_provision(r["ref"], r.get("header", ""), r.get("body", ""))
        for r in retrieved
    ]
    docs_lines = [
        f"{d['key']}: {d.get('short_name', '')} ({d.get('identifier', '')})"
        for d in documents
    ]
    cap = 0 if max_added is None else max_added
    content = load_prompt("selection").format(
        version=SELECTION_PROMPT_VERSION,
        provisions="\n\n".join(provisions),
        documents="\n".join(docs_lines),
        snapshot=snapshot.isoformat(),
        situation=format_situation(situation),
        max_added=cap,
    )
    msgs = list(conversation)
    msgs.append(Message(role="user", content=content))
    return msgs
