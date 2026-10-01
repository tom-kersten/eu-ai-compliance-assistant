"""Query building utilities for the retrieval pipeline."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.llm import Message


def build_query(messages: Sequence[Message], history_turns: int) -> str:
    """Build a retrieval query from the last `history_turns` user messages.

    - Filter messages to role == "user".
    - Take the last `history_turns` (chronological order preserved).
    - Join their `content` with `"\n"`.
    - If history_turns == 0 or no user messages, return empty string.
    """
    if history_turns <= 0:
        return ""
    user_msgs = [m for m in messages if m.role == "user"]
    if not user_msgs:
        return ""
    # keep chronological order and take last N
    last = user_msgs[-history_turns:] if history_turns < len(user_msgs) else user_msgs
    return "\n".join(m.content for m in last)
