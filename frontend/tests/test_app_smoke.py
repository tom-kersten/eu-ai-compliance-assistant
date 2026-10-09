"""AppTest smoke tests with a stub backend client."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import strings
from ui.client import CorpusInfo

from .conftest import StubClient

APP_PATH = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"


def _all_markdown(at: AppTest) -> str:
    parts: list[str] = [str(m.value) for m in at.markdown]
    for msg in at.chat_message:
        for child in msg:
            val = getattr(child, "value", None)
            if isinstance(val, str):
                parts.append(val)
    for status in at.status:
        parts.append(str(getattr(status, "label", "")))
        for child in status:
            val = getattr(child, "value", None)
            if isinstance(val, str):
                parts.append(val)
            else:
                parts.append(str(child))
    return "\n".join(parts)


def test_first_load_without_backend(monkeypatch) -> None:
    stub = StubClient()
    stub.set_corpus_error(ConnectionError("unreachable"))
    monkeypatch.setattr("ui.client.get_client", lambda: stub)

    at = AppTest.from_file(str(APP_PATH))
    at.run()

    assert not at.exception
    assert at.title[0].value == strings.PAGE_TITLE
    blob = _all_markdown(at)
    assert strings.DISCLAIMER in blob
    assert strings.EU_ASSUMPTION in blob
    assert strings.SNAPSHOT_FALLBACK in blob


def test_answer_flow_shows_progress_answer_citations(monkeypatch) -> None:
    stub = StubClient()
    stub.set_corpus(
        CorpusInfo(
            documents=[
                {
                    "key": "ai-act",
                    "short_name": "AI-verordening",
                    "identifier": "x",
                    "provision_count": 1,
                }
            ],
            snapshot_date="2026-10-01",
        )
    )
    stub.queue_ask("full.events")
    monkeypatch.setattr("ui.client.get_client", lambda: stub)

    at = AppTest.from_file(str(APP_PATH))
    at.run()
    assert not at.exception

    at.chat_input[0].set_value("Wat is artikel 4a?").run()
    assert not at.exception

    blob = _all_markdown(at)
    assert strings.PROGRESS_FOUND in blob or "art_4a" in blob
    assert strings.PROGRESS_KEPT in blob or "art_4a" in blob
    assert strings.PROGRESS_ADDED in blob or "anx_III" in blob
    assert strings.PROGRESS_UNAVAILABLE in blob or "CRA:art_1" in blob
    assert "Dit is een antwoord." in blob

    expander_labels = [e.label for e in at.expander]
    assert any("Artikel 4a" in label for label in expander_labels)

    # Expander body
    bodies = []
    for exp in at.expander:
        for child in exp:
            val = getattr(child, "value", None)
            if isinstance(val, str):
                bodies.append(val)
    assert any("Volledige tekst" in b for b in bodies)

    assert "2026-10-01" in blob


def test_clarify_flow_followup_sends_action(monkeypatch) -> None:
    stub = StubClient()
    stub.set_corpus(CorpusInfo(documents=[], snapshot_date="2026-10-01"))
    stub.queue_ask("clarify.events")
    stub.queue_ask("full.events")
    monkeypatch.setattr("ui.client.get_client", lambda: stub)

    at = AppTest.from_file(str(APP_PATH))
    at.run()
    assert not at.exception

    at.chat_input[0].set_value("Wat moet ik doen?").run()
    assert not at.exception
    assert len(stub.ask_calls) == 1

    blob = _all_markdown(at)
    assert "aanbieder" in blob.lower() or "gebruiksverantwoordelijke" in blob.lower()

    # Edit domain in the situation panel before the follow-up.
    domain_inputs = [
        ti
        for ti in at.sidebar.text_input
        if strings.DOMAIN_LABEL in str(getattr(ti, "label", ""))
    ]
    if domain_inputs:
        domain_inputs[0].set_value("hr")
        at.run()
        assert not at.exception

    at.chat_input[0].set_value("Ik ben de aanbieder.").run()
    assert not at.exception
    assert len(stub.ask_calls) == 2

    second = stub.ask_calls[1]
    history = second["messages"]
    assistant_msgs = [m for m in history if m.get("role") == "assistant"]
    assert assistant_msgs
    assert assistant_msgs[0].get("action") == "clarify"
    assert second["situation"]["role"] in {
        "unknown",
        "provider",
        "deployer",
        "importer",
        "distributor",
    }
    # Edited domain should be present when the widget edit succeeded.
    if domain_inputs:
        assert second["situation"]["domain"] == "hr"
