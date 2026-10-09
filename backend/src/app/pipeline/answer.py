from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from datetime import date

from app.pipeline.prompts.answer import ANSWER_PROMPT_VERSION, build_answer_prompt
from app.pipeline.validators import (
    validate_answer_citations,
    validate_clarify_allowed,
    warn_unknown_article_mentions,
)
from app.schemas.llm import AnswerResult, Message

logger = logging.getLogger(__name__)


async def answer(
    llm,
    conversation: Iterable[Message],
    situation,
    final_context: Iterable[dict],
    unavailable: Sequence[dict],
    documents: Iterable[dict],
    snapshot: date,
    *,
    reasoning_effort: str | None,
) -> AnswerResult:
    logger.info("ANSWER_PROMPT_VERSION=%s", ANSWER_PROMPT_VERSION)
    msgs = build_answer_prompt(
        conversation,
        situation,
        final_context,
        unavailable,
        documents,
        snapshot,
    )
    msg_dicts = [m.model_dump() for m in msgs]
    res = await llm.respond(
        messages=msg_dicts, schema=AnswerResult, reasoning_effort=reasoning_effort
    )
    # pydantic will raise ValidationError on shape errors
    out = AnswerResult.model_validate(res)
    # validate citations subset
    context_refs = [p["ref"] for p in final_context]
    validate_answer_citations(out, context_refs)
    # validate clarify rule
    validate_clarify_allowed(out, conversation)
    # soft check: warn about article mentions not in context
    try:
        warn_unknown_article_mentions(out.answer or "", final_context, logger)
    except Exception:
        # best effort only; don't fail the step
        logger.debug("warn_unknown_article_mentions failed", exc_info=True)
    # return the model output; caller handles retries
    return out
