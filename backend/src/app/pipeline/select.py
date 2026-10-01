from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.errors import SelectionInvalid
from app.schemas.llm import Message, SelectionResult


def validate_selection(result: SelectionResult, retrieved_refs: Sequence[str]) -> None:
    problems: list[str] = []
    keep = result.keep
    discard = result.discard
    # duplicates within a list
    for lst_name, lst in (("keep", keep), ("discard", discard)):
        seen = set()
        for r in lst:
            if r in seen:
                problems.append(f"duplicate {r} in {lst_name}")
            seen.add(r)
    # overlap
    overlap = set(keep) & set(discard)
    if overlap:
        problems.append(f"refs in both keep and discard: {', '.join(sorted(overlap))}")
    # unknown refs in keep/discard
    retrieved_set = set(retrieved_refs)
    unknown = [r for r in keep + discard if r not in retrieved_set]
    if unknown:
        problems.append(f"unknown refs: {', '.join(sorted(set(unknown)))}")
    # missing retrieved refs
    provided = set(keep) | set(discard)
    missing = retrieved_set - provided
    if missing:
        problems.append(f"missing retrieved refs: {', '.join(sorted(missing))}")
    if problems:
        raise SelectionInvalid(problems)


async def select(
    llm, messages: Iterable[Message], *, reasoning_effort: str | None
) -> SelectionResult:
    # send messages as dicts
    msg_dicts = [m.model_dump() for m in messages]
    effort_payload = (
        {"effort": reasoning_effort, "exclude": False}
        if reasoning_effort is not None
        else None
    )
    res = await llm.respond(
        messages=msg_dicts, schema=SelectionResult, reasoning=effort_payload
    )
    # Validate and return
    return SelectionResult.model_validate(res)
