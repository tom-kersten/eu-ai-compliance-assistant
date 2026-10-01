from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from app.errors import AnswerInvalid
from app.pipeline import resolve
from app.schemas.domain import Provision


def validate_answer_citations(result, context_refs: Iterable[str]) -> None:
    problems: list[str] = []
    cited = set(result.citations or [])
    context_set = set(context_refs)
    missing = cited - context_set
    if missing:
        problems.append("missing citations: " + ", ".join(sorted(missing)))
    if problems:
        raise AnswerInvalid(problems)


def validate_clarify_allowed(result, conversation: Iterable[object]) -> None:
    # conversation is an iterable of Message-like objects with .role and .action
    last_assistant = None
    for m in conversation:
        if getattr(m, "role", None) == "assistant":
            last_assistant = m
    if last_assistant is not None:
        if (
            getattr(last_assistant, "action", None) == "clarify"
            and result.action == "clarify"
        ):
            raise AnswerInvalid(["second clarify not allowed after assistant clarify"])


def warn_unknown_article_mentions(
    answer_text: str, final_context: Iterable[Provision], logger: logging.Logger
) -> None:
    # extract article numbers mentioned like:
    # "artikel 26", "artikelen 26 en 27", or "artikel 26, lid 3"
    nums = re.findall(r"artikel[^\d\n]*([0-9]+)", answer_text, flags=re.IGNORECASE)
    if not nums:
        return
    mentioned = {f"art_{n}" for n in nums}
    # collect article labels present in final_context
    present = set()
    for p in final_context:
        # support both Provision objects and dicts
        kind = getattr(p, "kind", None) or (
            p.get("kind") if isinstance(p, dict) else None
        )
        label = getattr(p, "label", None) or (
            p.get("label") if isinstance(p, dict) else None
        )
        if kind == "article" and label is not None:
            present.add(resolve.normalize_label("article", label))
    missing = sorted(m for m in mentioned if m not in present)
    if missing:
        logger.warning("missing article mentions: %s", ", ".join(missing))
