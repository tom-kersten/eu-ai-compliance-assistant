"""Shared fixtures for the frontend suite. Stub client lives here, not in production."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ui.client import CorpusInfo, ErrorEvent, SSEParser

FIXTURES = Path(__file__).parent / "fixtures" / "sse"


def _parse_fixture(name: str) -> list[Any]:
    data = (FIXTURES / name).read_bytes()
    parser = SSEParser()
    return parser.feed(data) + parser.feed(b"")


class StubClient:
    """Replays fixture event streams and records request payloads."""

    def __init__(self) -> None:
        self.ask_calls: list[dict[str, Any]] = []
        self._ask_queues: list[list[Any]] = []
        self._corpus: CorpusInfo | None = None
        self._corpus_error: Exception | None = None
        self._default_ask: list[Any] | None = None

    def queue_ask(self, fixture_name: str) -> None:
        self._ask_queues.append(_parse_fixture(fixture_name))

    def set_default_ask(self, fixture_name: str) -> None:
        self._default_ask = _parse_fixture(fixture_name)

    def set_corpus(self, info: CorpusInfo) -> None:
        self._corpus = info
        self._corpus_error = None

    def set_corpus_error(self, exc: Exception) -> None:
        self._corpus_error = exc
        self._corpus = None

    def ask(
        self,
        messages: list[dict[str, Any]],
        situation: dict[str, Any],
    ) -> Iterator[Any]:
        self.ask_calls.append({"messages": messages, "situation": situation})
        if self._ask_queues:
            events = self._ask_queues.pop(0)
        elif self._default_ask is not None:
            events = self._default_ask
        else:
            events = [
                ErrorEvent(code="client_incomplete_stream", message="no script"),
            ]
        yield from events

    def fetch_corpus(self) -> CorpusInfo:
        if self._corpus_error is not None:
            raise self._corpus_error
        if self._corpus is None:
            raise ConnectionError("corpus unavailable")
        return self._corpus


@pytest.fixture
def stub_client() -> StubClient:
    return StubClient()
