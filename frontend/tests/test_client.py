"""BackendClient tests with httpx MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ui.client import BackendClient, ErrorEvent, FinalEvent, StatusEvent

FIXTURES = Path(__file__).parent / "fixtures" / "sse"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_ask_full_stream_yields_events() -> None:
    body = _load("full.events")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/ask"
        import json

        data = json.loads(request.content.decode())
        assert "messages" in data
        assert "situation" in data
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    events = list(
        client.ask(
            messages=[{"role": "user", "content": "vraag"}],
            situation={"role": "unknown", "domain": None, "notes": None},
        )
    )
    assert isinstance(events[0], StatusEvent)
    assert isinstance(events[-1], FinalEvent)
    assert events[-1].action == "answer"


def test_ask_non_200_yields_client_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"code": "missing_index", "message": "index missing"},
        )

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    events = list(
        client.ask(
            messages=[{"role": "user", "content": "vraag"}],
            situation={"role": "unknown"},
        )
    )
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "client_http_error"


def test_ask_connection_error_yields_client_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    events = list(
        client.ask(
            messages=[{"role": "user", "content": "vraag"}],
            situation={"role": "unknown"},
        )
    )
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].code == "client_connection_error"


def test_ask_incomplete_stream_yields_client_incomplete_stream() -> None:
    body = b'event: status\ndata: {"event":"status","step":"searching"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    events = list(
        client.ask(
            messages=[{"role": "user", "content": "vraag"}],
            situation={"role": "unknown"},
        )
    )
    assert isinstance(events[0], StatusEvent)
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "client_incomplete_stream"


def test_fetch_corpus_parses_snapshot_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/corpus"
        return httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "key": "ai-act",
                        "short_name": "AI-verordening",
                        "identifier": "Verordening (EU) 2024/1689",
                        "provision_count": 120,
                    }
                ],
                "snapshot_date": "2026-10-01",
            },
        )

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    info = client.fetch_corpus()
    assert info.snapshot_date == "2026-10-01"
    assert info.documents[0]["key"] == "ai-act"


def test_fetch_corpus_raises_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"code": "missing_index", "message": "x"})

    transport = httpx.MockTransport(handler)
    client = BackendClient(
        base_url="http://test",
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    with pytest.raises(httpx.HTTPError):
        client.fetch_corpus()
