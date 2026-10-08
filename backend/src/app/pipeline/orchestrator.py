from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.config import Settings
from app.pipeline.budget import apply_budget
from app.pipeline.prompts.answer import ANSWER_PROMPT_VERSION
from app.pipeline.prompts.selection import (
    SELECTION_PROMPT_VERSION,
    build_selection_prompt,
)
from app.pipeline.query import build_query
from app.pipeline.resolve import ResolveResult, resolve
from app.pipeline.retrieve import ProvisionSearch, retrieve
from app.pipeline.select import select, validate_selection
from app.providers.base import LLM
from app.providers.base import Usage as ProviderUsage
from app.schemas.api import (
    AskRequest,
    ErrorEvent,
    FinalEvent,
    RetrievedEvent,
    RetrievedItem,
    SelectionEvent,
    StatusEvent,
    Usage,
)
from app.schemas.domain import Provision

logger = logging.getLogger(__name__)

# Dutch cannot-answer explanation (minimal placeholder; frontend owns copy)
CANNOT_ANSWER_EXPLANATION = "Kan geen antwoord geven."


@dataclass
class _TrackingLLM:
    """Wrap an injected LLM to count calls and aggregate provider usage.

    - Counts one call per `respond()` invocation (including failed attempts).
    - Sums tokens from a returned `usage` dict when present.
    - Removes the `usage` key from returned dicts so downstream validators
      (which forbid extras) do not fail.
    """

    inner: LLM
    usage: ProviderUsage = field(default_factory=ProviderUsage)

    async def respond(self, **kwargs: Any) -> dict:
        # Count the attempt immediately
        self.usage.calls += 1
        try:
            res = await self.inner.respond(**kwargs)
        except Exception:
            # propagate; orchestrator maps provider errors
            raise
        # extract usage if present
        u = res.get("usage") if isinstance(res, dict) else None
        if isinstance(u, dict):
            # prompt/completion tokens
            self.usage.prompt_tokens += int(u.get("prompt_tokens", 0) or 0)
            self.usage.completion_tokens += int(u.get("completion_tokens", 0) or 0)
            # nested reasoning tokens path: completion_tokens_details.reasoning_tokens
            ctd = u.get("completion_tokens_details") or {}
            self.usage.reasoning_tokens += int(ctd.get("reasoning_tokens", 0) or 0)
        # return a copy without `usage` so schema validation (extra="forbid") succeeds
        if isinstance(res, dict) and "usage" in res:
            out = dict(res)
            out.pop("usage", None)
            return out
        return res


async def run(
    request: AskRequest,
    *,
    settings: Settings,
    embedder,
    llm,
    repository: ProvisionSearch,
    documents: Iterable[dict],
    snapshot: date,
) -> AsyncIterator[object]:
    """Orchestrate the two-step pipeline and yield AskEvents."""
    tracker = _TrackingLLM(llm)

    # 1. searching
    yield StatusEvent(step="searching")

    # build query from recent user messages
    q = build_query(request.messages, settings.retrieval_history_turns)
    try:
        retrieved = await retrieve(
            q,
            embedder=embedder,
            repository=repository,
            top_k=settings.retrieval_top_k,
            threshold=settings.similarity_threshold,
        )
    except Exception:
        # retrieval failed
        yield ErrorEvent(code="retrieval_failed", message="retrieval failed")
        return

    # Emit retrieved (possibly empty)
    items = [
        RetrievedItem(ref=p.ref, title=p.title, similarity=p.similarity)
        for p in retrieved
    ]
    yield RetrievedEvent(provisions=items)

    # No retrieval -> cannot answer, zero LLM calls
    if not retrieved:
        usage = Usage(calls=0, prompt_tokens=0, completion_tokens=0, reasoning_tokens=0)
        usage.prompt_versions = {}
        yield FinalEvent(
            action="cannot_answer",
            answer=CANNOT_ANSWER_EXPLANATION,
            clarifying_questions=[],
            citations=[],
            situation=request.situation,
            usage=usage,
            corpus_snapshot=snapshot,
        )
        return

    # Selecting
    yield StatusEvent(step="selecting")

    # apply budget for selection prompt
    trimmed = apply_budget(retrieved, settings.prompt_token_budget)
    # build selection prompt messages
    retrieved_dicts = [
        {"ref": p.ref, "header": p.header, "body": p.body} for p in trimmed
    ]
    sel_msgs = build_selection_prompt(
        request.messages,
        request.situation,
        retrieved_dicts,
        documents,
        snapshot,
        max_added=settings.max_added_provisions,
    )

    # selection attempts
    max_attempts = 1 + settings.llm_max_retries
    selection_result = None
    for attempt in range(max_attempts):
        try:
            selection_result = await select(
                tracker, sel_msgs, reasoning_effort=settings.selection_reasoning_effort
            )
            # validate against trimmed refs
            validate_selection(selection_result, [p.ref for p in trimmed])
            # record prompt version
            break
        except Exception:
            # retryable: SelectionInvalid or pydantic.ValidationError
            if attempt + 1 >= max_attempts:
                yield ErrorEvent(
                    code="llm_invalid_output", message="invalid LLM output"
                )
                return
            continue

    # mark selection prompt version in usage
    # prepare usage container
    # convert provider usage to API Usage later
    # produce selection event: resolve requested provisions
    try:
        rr: ResolveResult = await resolve(
            selection_result.request,
            selection_result.external_references,
            kept=selection_result.keep,
            document_keys=[d["key"] for d in documents],
            lookup=repository,
            max_added=settings.max_added_provisions,
        )
    except Exception:
        yield ErrorEvent(code="retrieval_failed", message="retrieval failed")
        return

    selection_event = SelectionEvent(
        kept=selection_result.keep,
        discarded=selection_result.discard,
        added=[p.ref for p in rr.added],
        unavailable=[u.citation for u in rr.unavailable],
    )
    yield selection_event

    # final context is kept followed by added
    final_context_refs = list(selection_result.keep) + [p.ref for p in rr.added]
    if not final_context_refs:
        # final cannot_answer after exactly one call (selection)
        api_usage = Usage(
            calls=tracker.usage.calls,
            prompt_tokens=tracker.usage.prompt_tokens,
            completion_tokens=tracker.usage.completion_tokens,
            reasoning_tokens=tracker.usage.reasoning_tokens,
        )
        # record selection prompt version
        api_usage.prompt_versions = {"selection": SELECTION_PROMPT_VERSION}
        yield FinalEvent(
            action="cannot_answer",
            answer=CANNOT_ANSWER_EXPLANATION,
            clarifying_questions=[],
            citations=[],
            situation=request.situation,
            usage=api_usage,
            corpus_snapshot=snapshot,
        )
        return

    # answering
    yield StatusEvent(step="answering")

    # resolve final_context provisions (we already have rr.added rows)
    # build final_context list of dicts (keep order: kept then added)
    kept_rows: list[Provision] = []
    # map refs to Provision for kept items from trimmed retrieved or rr.added
    by_ref = {p.ref: p for p in retrieved}
    for r in selection_result.keep:
        if r in by_ref:
            kept_rows.append(by_ref[r])
    final_candidates = kept_rows + rr.added
    # apply budget for final answer
    final_kept = apply_budget(final_candidates, settings.prompt_token_budget)
    final_context_dicts = [
        {"ref": p.ref, "header": p.header, "body": p.body} for p in final_kept
    ]

    # map unavailable references to dicts for the answer prompt
    unavailable_for_prompt = [
        {"citation": u.citation, "reason": u.reason, "detail": u.detail}
        for u in rr.unavailable
    ]

    # answer attempts — answer() builds the prompt from the conversation once
    answer_result = None
    for attempt in range(max_attempts):
        try:
            from app.pipeline.answer import answer as answer_step

            answer_result = await answer_step(
                tracker,
                request.messages,
                request.situation,
                final_context_dicts,
                unavailable_for_prompt,
                documents,
                snapshot,
                reasoning_effort=settings.answer_reasoning_effort,
            )
            break
        except Exception:
            if attempt + 1 >= max_attempts:
                yield ErrorEvent(
                    code="llm_invalid_output", message="invalid LLM output"
                )
                return
            continue

    # build citations display from answer_result.citations (refs)
    cited = []
    final_by_ref = {p.ref: p for p in final_kept}
    for ref in answer_result.citations:
        p = final_by_ref.get(ref)
        if p is not None:
            cited.append({"ref": p.ref, "header": p.header, "body": p.body})

    api_usage = Usage(
        calls=tracker.usage.calls,
        prompt_tokens=tracker.usage.prompt_tokens,
        completion_tokens=tracker.usage.completion_tokens,
        reasoning_tokens=tracker.usage.reasoning_tokens,
    )
    api_usage.prompt_versions = {
        "selection": SELECTION_PROMPT_VERSION,
        "answer": ANSWER_PROMPT_VERSION,
    }

    final_event = FinalEvent(
        action=answer_result.action,
        answer=answer_result.answer,
        clarifying_questions=answer_result.clarifying_questions,
        citations=[  # display citations mapping
            {"ref": c["ref"], "header": c["header"], "body": c["body"]} for c in cited
        ],
        situation=answer_result.situation,
        usage=api_usage,
        corpus_snapshot=snapshot,
    )
    yield final_event
