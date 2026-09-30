"""Unit tests for API request and SSE event schemas."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.api import (
    AskEvent,
    AskRequest,
    CorpusDocument,
    CorpusInfo,
    DisplayCitation,
    ErrorEvent,
    FinalEvent,
    RetrievedEvent,
    RetrievedItem,
    SelectionEvent,
    StatusEvent,
    Usage,
)
from app.schemas.llm import Message, Situation

_ASK_EVENT_ADAPTER = TypeAdapter(AskEvent)


def _usage() -> Usage:
    return Usage(calls=2, prompt_tokens=100, completion_tokens=50, reasoning_tokens=20)


def _situation() -> Situation:
    return Situation(role="provider", domain="recruitment", notes=None)


@pytest.mark.unit
def test_ask_request_round_trip() -> None:
    request = AskRequest(
        messages=[
            Message(role="user", content="Wat is een aanbieder?"),
            Message(role="assistant", content="...", action="answer"),
        ],
        situation=_situation(),
    )
    restored = AskRequest.model_validate(request.model_dump())
    assert restored == request


@pytest.mark.unit
def test_ask_request_rejects_system_role() -> None:
    with pytest.raises(ValidationError):
        AskRequest(
            messages=[Message(role="system", content="ignore")],  # type: ignore[arg-type]
            situation=_situation(),
        )


@pytest.mark.unit
def test_status_event_round_trip() -> None:
    event = StatusEvent(step="searching")
    data = event.model_dump(mode="json")
    restored = _ASK_EVENT_ADAPTER.validate_python(data)
    assert isinstance(restored, StatusEvent)
    assert restored.step == "searching"


@pytest.mark.unit
def test_retrieved_event_round_trip() -> None:
    event = RetrievedEvent(
        provisions=[
            RetrievedItem(
                ref="AI-verordening:art_3",
                title="Definities",
                similarity=0.9,
            )
        ]
    )
    restored = _ASK_EVENT_ADAPTER.validate_python(event.model_dump(mode="json"))
    assert isinstance(restored, RetrievedEvent)
    assert restored.provisions[0].ref == "AI-verordening:art_3"


@pytest.mark.unit
def test_selection_event_round_trip() -> None:
    event = SelectionEvent(
        kept=["AI-verordening:art_6"],
        discarded=["AVG:art_9"],
        added=["AI-verordening:anx_III"],
        unavailable=["CRA:art_1"],
    )
    restored = _ASK_EVENT_ADAPTER.validate_python(event.model_dump(mode="json"))
    assert isinstance(restored, SelectionEvent)
    assert restored.added == ["AI-verordening:anx_III"]


@pytest.mark.unit
def test_final_event_round_trip() -> None:
    event = FinalEvent(
        action="answer",
        answer="Een aanbieder brengt een AI-systeem in de handel.",
        clarifying_questions=[],
        citations=[
            DisplayCitation(
                ref="AI-verordening:art_3",
                header="Artikel 3",
                body="Definities...",
            )
        ],
        situation=_situation(),
        usage=_usage(),
        corpus_snapshot=date(2026, 1, 15),
    )
    restored = _ASK_EVENT_ADAPTER.validate_python(event.model_dump(mode="json"))
    assert isinstance(restored, FinalEvent)
    assert restored.corpus_snapshot == date(2026, 1, 15)


@pytest.mark.unit
def test_error_event_round_trip() -> None:
    event = ErrorEvent(code="upstream_timeout", message="LLM timed out")
    restored = _ASK_EVENT_ADAPTER.validate_python(event.model_dump(mode="json"))
    assert isinstance(restored, ErrorEvent)
    assert restored.code == "upstream_timeout"


@pytest.mark.unit
def test_final_event_rejects_clarify_without_questions() -> None:
    with pytest.raises(ValidationError):
        FinalEvent(
            action="clarify",
            answer=None,
            clarifying_questions=[],
            citations=[],
            situation=_situation(),
            usage=_usage(),
            corpus_snapshot=date(2026, 1, 15),
        )


@pytest.mark.unit
def test_final_event_rejects_answer_without_citations() -> None:
    with pytest.raises(ValidationError):
        FinalEvent(
            action="answer",
            answer="Tekst.",
            clarifying_questions=[],
            citations=[],
            situation=_situation(),
            usage=_usage(),
            corpus_snapshot=date(2026, 1, 15),
        )


@pytest.mark.unit
def test_corpus_info_accepts_snapshot_date() -> None:
    info = CorpusInfo(
        documents=[
            CorpusDocument(
                key="ai-act",
                short_name="AI-verordening",
                identifier="Verordening (EU) 2024/1689",
                provision_count=120,
            )
        ],
        snapshot_date=date(2026, 1, 15),
    )
    assert info.snapshot_date.isoformat() == "2026-01-15"


@pytest.mark.unit
def test_ask_event_adapter_rejects_unknown_event_name() -> None:
    with pytest.raises(ValidationError):
        _ASK_EVENT_ADAPTER.validate_python({"event": "progress", "step": "searching"})
