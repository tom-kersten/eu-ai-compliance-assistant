"""Session-state keys and helpers for the Streamlit UI."""

from __future__ import annotations

from typing import Any

from ui.client import ErrorEvent, FinalEvent


def default_situation() -> dict[str, Any]:
    return {"role": "unknown", "domain": None, "notes": None}


def ensure_session(session: dict[str, Any]) -> None:
    session.setdefault("history", [])
    session.setdefault("situation", default_situation())
    session.setdefault("last_response", None)
    session.setdefault("corpus_snapshot", None)
    session.setdefault("situation_pending", False)
    session.setdefault("progress_events", [])


def append_user_message(session: dict[str, Any], content: str) -> None:
    ensure_session(session)
    session["history"].append({"role": "user", "content": content})


def _assistant_content(event: FinalEvent) -> str:
    if event.action == "clarify":
        questions = event.clarifying_questions or []
        return "\n".join(q for q in questions if q)
    return event.answer or ""


def apply_event(session: dict[str, Any], event: Any) -> None:
    """Apply a stream event to session state.

    A final event stores the assistant message with its action, updates
    last_response and corpus_snapshot, and writes final.situation into the
    situation key (and marks situation_pending so the app can copy into
    widget keys before the panel renders on the next run).
    """
    ensure_session(session)

    if isinstance(event, ErrorEvent):
        session["last_response"] = event
        return

    if not isinstance(event, FinalEvent):
        session.setdefault("progress_events", []).append(event)
        return

    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": _assistant_content(event),
    }
    if event.action is not None:
        assistant_msg["action"] = event.action
    session["history"].append(assistant_msg)

    if event.situation:
        session["situation"] = {
            "role": event.situation.get("role", "unknown"),
            "domain": event.situation.get("domain"),
            "notes": event.situation.get("notes"),
        }
        session["situation_pending"] = True

    session["last_response"] = event
    if event.corpus_snapshot is not None:
        session["corpus_snapshot"] = event.corpus_snapshot


def serialize_history_for_request(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the messages payload. Assistant messages carry action; users do not."""
    out: list[dict[str, Any]] = []
    for msg in history:
        item: dict[str, Any] = {
            "role": msg.get("role"),
            "content": msg.get("content") or "",
        }
        if msg.get("role") == "assistant" and msg.get("action") is not None:
            item["action"] = msg["action"]
        out.append(item)
    return out


def serialize_situation(situation: dict[str, Any]) -> dict[str, Any]:
    """Build the situation payload; empty domain/notes become null."""
    role = situation.get("role") or "unknown"
    domain = situation.get("domain")
    notes = situation.get("notes")
    if isinstance(domain, str) and not domain.strip():
        domain = None
    if isinstance(notes, str) and not notes.strip():
        notes = None
    return {"role": role, "domain": domain, "notes": notes}
