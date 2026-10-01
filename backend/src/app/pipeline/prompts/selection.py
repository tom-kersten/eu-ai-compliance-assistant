from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.schemas.llm import Message, Situation

from . import load_prompt
from .provision_format import format_provision

SELECTION_PROMPT_VERSION = "T11v1"


def build_selection_prompt(
    conversation: Iterable[Message],
    situation: Situation,
    retrieved: Iterable[dict],
    documents: Iterable[dict],
    snapshot: date,
    max_added: int | None,
) -> list[Message]:
    """Build a simple selection prompt message list.

    - `retrieved` is an iterable of dicts with keys: ref, header, body.
    - `documents` is an iterable of dicts with keys: key, short_name, identifier.
    """
    provisions = []
    for r in retrieved:
        provisions.append(
            format_provision(r["ref"], r.get("header", ""), r.get("body", ""))
        )
    prov_block = "\n\n".join(provisions)
    docs_lines = []
    for d in documents:
        docs_lines.append(
            f"{d['key']}: {d.get('short_name', '')} ({d.get('identifier', '')})"
        )
    prompt_template = load_prompt("selection")
    content = prompt_template.format(
        version=SELECTION_PROMPT_VERSION,
        provisions=prov_block,
        documents="\n".join(docs_lines),
        snapshot=snapshot.isoformat(),
    )
    # include conversation as system/user/history messages before the prompt
    msgs = [m for m in conversation]
    msgs.append(Message(role="user", content=content))
    return msgs
