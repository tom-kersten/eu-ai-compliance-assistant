"""SSE parser tests against recorded event streams."""

from __future__ import annotations

from pathlib import Path

from ui.client import (
    ErrorEvent,
    FinalEvent,
    RetrievedEvent,
    SelectionEvent,
    SSEParser,
    StatusEvent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sse"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_full_stream_parses_typed_events_in_order() -> None:
    data = load_fixture("full.events")
    parser = SSEParser()
    events = parser.feed(data) + parser.feed(b"")

    assert [type(e) for e in events] == [
        StatusEvent,
        RetrievedEvent,
        StatusEvent,
        SelectionEvent,
        StatusEvent,
        FinalEvent,
    ]
    assert events[0].step == "searching"
    assert events[1].provisions[0]["ref"] == "AI-verordening:art_4a"
    assert events[3].kept == ["AI-verordening:art_4a"]
    assert events[3].added == ["AI-verordening:anx_III"]
    assert events[3].unavailable == ["CRA:art_1"]
    final = events[5]
    assert isinstance(final, FinalEvent)
    assert final.action == "answer"
    assert final.answer == "Dit is een antwoord."
    assert final.citations[0]["header"] == "Artikel 4a"
    assert final.situation["role"] == "provider"
    assert final.corpus_snapshot == "2026-10-01"


def test_partial_chunk_reconstruction() -> None:
    data = load_fixture("partial_chunk.events")
    half = len(data) // 2
    parser = SSEParser()
    events = parser.feed(data[:half]) + parser.feed(data[half:]) + parser.feed(b"")
    finals = [e for e in events if isinstance(e, FinalEvent)]
    assert len(finals) == 1
    assert finals[0].answer == "Deel1 Deel2"


def test_error_event_parses() -> None:
    data = load_fixture("error.events")
    parser = SSEParser()
    events = parser.feed(data) + parser.feed(b"")
    assert any(isinstance(e, ErrorEvent) for e in events)
    err = next(e for e in events if isinstance(e, ErrorEvent))
    assert err.code == "retrieval_failed"
    assert err.message == "retrieval failed"


def test_crlf_line_endings() -> None:
    raw = (
        b"event: status\r\n"
        b'data: {"event":"status","step":"searching"}\r\n'
        b"\r\n"
        b"event: error\r\n"
        b'data: {"event":"error","code":"internal_error","message":"boom"}\r\n'
        b"\r\n"
    )
    parser = SSEParser()
    events = parser.feed(raw) + parser.feed(b"")
    assert isinstance(events[0], StatusEvent)
    assert isinstance(events[1], ErrorEvent)
    assert events[1].code == "internal_error"


def test_multiline_data_field() -> None:
    # SSE joins successive data: lines with a newline; the result must be valid JSON.
    raw = (
        b"event: final\n"
        b'data: {"event":"final","action":"answer","answer":"Hallo"\n'
        b'data: ,"clarifying_questions":[],"citations":'
        b'[{"ref":"r","header":"H","body":"B"}],'
        b'"situation":{"role":"unknown","domain":null,"notes":null},'
        b'"usage":{"calls":1,"prompt_tokens":1,"completion_tokens":1,'
        b'"reasoning_tokens":0,"prompt_versions":{}},"corpus_snapshot":"2026-01-01"}\n'
        b"\n"
    )
    parser = SSEParser()
    events = parser.feed(raw) + parser.feed(b"")
    assert len(events) == 1
    assert isinstance(events[0], FinalEvent)
    assert events[0].answer == "Hallo"


def test_clarify_fixture_parses() -> None:
    data = load_fixture("clarify.events")
    parser = SSEParser()
    events = parser.feed(data) + parser.feed(b"")
    final = next(e for e in events if isinstance(e, FinalEvent))
    assert final.action == "clarify"
    assert final.answer is None
    assert final.clarifying_questions == [
        "Bent u de aanbieder of de gebruiksverantwoordelijke?"
    ]
