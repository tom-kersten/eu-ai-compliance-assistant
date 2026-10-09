"""Session state helper tests."""

from __future__ import annotations

from ui import state
from ui.client import FinalEvent


def test_final_stores_action_on_assistant_message() -> None:
    session: dict = {}
    state.ensure_session(session)
    event = FinalEvent(
        action="clarify",
        answer=None,
        clarifying_questions=["Is dit duidelijk?"],
        citations=[],
        situation={"role": "provider", "domain": None, "notes": None},
        usage={"calls": 1, "prompt_tokens": 1, "completion_tokens": 1},
        corpus_snapshot="2026-10-01",
    )
    state.apply_event(session, event)
    assert session["history"][-1]["role"] == "assistant"
    assert session["history"][-1]["action"] == "clarify"
    assert session["history"][-1]["content"] == "Is dit duidelijk?"
    assert session["situation"]["role"] == "provider"
    assert session["last_response"] is event
    assert session["corpus_snapshot"] == "2026-10-01"


def test_final_answer_stores_answer_text() -> None:
    session: dict = {}
    state.ensure_session(session)
    event = FinalEvent(
        action="answer",
        answer="Dit is het antwoord.",
        clarifying_questions=[],
        citations=[{"ref": "r", "header": "H", "body": "B"}],
        situation={"role": "deployer", "domain": "hr", "notes": "n"},
        usage={"calls": 2, "prompt_tokens": 1, "completion_tokens": 1},
        corpus_snapshot="2026-10-01",
    )
    state.apply_event(session, event)
    assert session["history"][-1]["content"] == "Dit is het antwoord."
    assert session["history"][-1]["action"] == "answer"
    assert "citations" not in session["history"][-1]


def test_serialize_history_includes_action_only_on_assistant() -> None:
    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Ok", "action": "answer"},
    ]
    serialized = state.serialize_history_for_request(history)
    assert "action" not in serialized[0]
    assert serialized[1]["action"] == "answer"
    assert set(serialized[1].keys()) == {"role", "content", "action"}


def test_situation_from_final_replaces_panel_values() -> None:
    session: dict = {}
    state.ensure_session(session)
    assert session["situation"]["role"] == "unknown"
    event = FinalEvent(
        action="answer",
        answer="Tekst",
        clarifying_questions=[],
        citations=[{"ref": "r", "header": "H", "body": "B"}],
        situation={"role": "provider", "domain": "werving", "notes": "extra"},
        usage={"calls": 1, "prompt_tokens": 1, "completion_tokens": 1},
        corpus_snapshot="2026-10-01",
    )
    state.apply_event(session, event)
    assert session["situation"] == {
        "role": "provider",
        "domain": "werving",
        "notes": "extra",
    }


def test_user_edits_win_on_serialize() -> None:
    session: dict = {}
    state.ensure_session(session)
    event = FinalEvent(
        action="answer",
        answer="Tekst",
        clarifying_questions=[],
        citations=[{"ref": "r", "header": "H", "body": "B"}],
        situation={"role": "provider", "domain": "werving", "notes": None},
        usage={"calls": 1, "prompt_tokens": 1, "completion_tokens": 1},
        corpus_snapshot="2026-10-01",
    )
    state.apply_event(session, event)
    # User edits the situation after the final event.
    session["situation"] = {
        "role": "deployer",
        "domain": "hr",
        "notes": "handmatig",
    }
    serialized = state.serialize_situation(session["situation"])
    assert serialized["role"] == "deployer"
    assert serialized["domain"] == "hr"
    assert serialized["notes"] == "handmatig"


def test_serialize_situation_empty_strings_become_null() -> None:
    out = state.serialize_situation({"role": "unknown", "domain": "", "notes": "  "})
    assert out["domain"] is None
    assert out["notes"] is None


def test_append_user_message() -> None:
    session: dict = {}
    state.ensure_session(session)
    state.append_user_message(session, "Hallo")
    assert session["history"] == [{"role": "user", "content": "Hallo"}]
