from __future__ import annotations

from typing import Any


def ensure_session(session: dict[str, Any]) -> None:
    session.setdefault("history", [])
    session.setdefault("situation", {"role": "", "domain": "", "notes": ""})
    session.setdefault("last_response", None)


def apply_event(session: dict[str, Any], event: Any) -> None:
    """
    Apply a FinalEvent-like object to the session.
    Stores an assistant message with the action, updates situation.
    """
    ensure_session(session)
    has_action = getattr(event, "action", None) is not None
    has_answer = getattr(event, "answer", None) is not None
    if has_action or has_answer:
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": getattr(event, "answer", None),
        }
        if getattr(event, "action", None) is not None:
            assistant_msg["action"] = event.action
        session["history"].append(assistant_msg)
    # update situation if provided
    if getattr(event, "situation", None):
        session["situation"] = event.situation
    # last_response for convenience
    session["last_response"] = getattr(event, "answer", None)


def serialize_history_for_request(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in history:
        item = {"role": msg.get("role"), "content": msg.get("content")}
        if msg.get("role") == "assistant" and "action" in msg:
            item["action"] = msg.get("action")
        out.append(item)
    return out
