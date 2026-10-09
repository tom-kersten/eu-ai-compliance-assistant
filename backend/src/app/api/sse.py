"""Server-Sent Event formatting and disconnect-aware streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request


def format_sse(event: BaseModel) -> str:
    """Format a Pydantic event model as one SSE message."""
    data = event.model_dump(mode="json")
    # Event name is the discriminator field on AskEvent models.
    name = data.get("event")
    if not isinstance(name, str) or not name:
        msg = f"event model missing event name: {type(event)!r}"
        raise ValueError(msg)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {payload}\n\n"


async def stream_events(
    request: Request,
    source: AsyncIterator[Any],
) -> AsyncIterator[str]:
    """Yield SSE text for each event; stop and aclose on client disconnect.

    Always acloses the source in finally, including on CancelledError.
    CancelledError is re-raised after cleanup.
    """
    try:
        async for event in source:
            yield format_sse(event)
            if await request.is_disconnected():
                return
    finally:
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()
