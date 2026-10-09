"""HTTP client and SSE parser for the backend API."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BACKEND_URL = "http://backend:8000"


@dataclass(frozen=True)
class StatusEvent:
    step: str | None


@dataclass(frozen=True)
class RetrievedEvent:
    provisions: list[dict[str, Any]]


@dataclass(frozen=True)
class SelectionEvent:
    kept: list[str]
    discarded: list[str]
    added: list[str]
    unavailable: list[str]


@dataclass(frozen=True)
class FinalEvent:
    action: str | None
    answer: str | None
    clarifying_questions: list[str] | None
    citations: list[dict[str, Any]]
    situation: dict[str, Any]
    usage: dict[str, Any]
    corpus_snapshot: str | None


@dataclass(frozen=True)
class ErrorEvent:
    code: str
    message: str


@dataclass(frozen=True)
class CorpusInfo:
    documents: list[dict[str, Any]]
    snapshot_date: str


AskEvent = StatusEvent | RetrievedEvent | SelectionEvent | FinalEvent | ErrorEvent


class SSEParser:
    """Incremental SSE parser. Call feed() with bytes; flush with feed(b"")."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, data: bytes) -> list[AskEvent]:
        text = data.decode("utf-8") if data else ""
        text = text.replace("\r\n", "\n")
        self._buf += text
        events: list[AskEvent] = []

        if data == b"" and self._buf.strip():
            raw = self._buf
            self._buf = ""
            ev = self._parse_chunk(raw)
            if ev is not None:
                events.append(ev)
            return events

        while "\n\n" in self._buf:
            chunk, self._buf = self._buf.split("\n\n", 1)
            if not chunk.strip():
                continue
            ev = self._parse_chunk(chunk)
            if ev is not None:
                events.append(ev)
        return events

    def _parse_chunk(self, chunk: str) -> AskEvent | None:
        lines = [line for line in chunk.split("\n") if line.strip() != ""]
        event_name: str | None = None
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())

        data_text = "\n".join(data_lines) if data_lines else ""
        try:
            payload: dict[str, Any] = json.loads(data_text) if data_text else {}
        except json.JSONDecodeError:
            payload = {}

        if event_name == "status":
            return StatusEvent(step=payload.get("step"))
        if event_name == "retrieved":
            return RetrievedEvent(provisions=payload.get("provisions", []))
        if event_name == "selection":
            return SelectionEvent(
                kept=payload.get("kept", []),
                discarded=payload.get("discarded", []),
                added=payload.get("added", []),
                unavailable=payload.get("unavailable", []),
            )
        if event_name == "final":
            return FinalEvent(
                action=payload.get("action"),
                answer=payload.get("answer"),
                clarifying_questions=payload.get("clarifying_questions"),
                citations=payload.get("citations", []),
                situation=payload.get("situation", {}),
                usage=payload.get("usage", {}),
                corpus_snapshot=payload.get("corpus_snapshot"),
            )
        if event_name == "error":
            return ErrorEvent(
                code=payload.get("code", "client_error"),
                message=payload.get("message", ""),
            )
        return None


class BackendClient:
    """Thin wrapper around POST /v1/ask (SSE) and GET /v1/corpus."""

    def __init__(
        self,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BACKEND_URL).rstrip("/")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self._base_url,
            timeout=None,
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def ask(
        self,
        messages: list[dict[str, Any]],
        situation: dict[str, Any],
    ) -> Iterator[AskEvent]:
        """Stream typed events from POST /v1/ask. Never raises for ask failures."""
        parser = SSEParser()
        saw_terminal = False
        try:
            with self._http.stream(
                "POST",
                "/v1/ask",
                json={"messages": messages, "situation": situation},
            ) as response:
                if response.status_code != 200:
                    # Drain the body so the connection can be reused.
                    _ = response.read()
                    yield ErrorEvent(
                        code="client_http_error",
                        message=f"HTTP {response.status_code}",
                    )
                    return
                for chunk in response.iter_bytes():
                    for event in parser.feed(chunk):
                        if isinstance(event, (FinalEvent, ErrorEvent)):
                            saw_terminal = True
                        yield event
                for event in parser.feed(b""):
                    if isinstance(event, (FinalEvent, ErrorEvent)):
                        saw_terminal = True
                    yield event
        except httpx.HTTPError as exc:
            yield ErrorEvent(
                code="client_connection_error",
                message=str(exc) or "connection error",
            )
            return

        if not saw_terminal:
            yield ErrorEvent(
                code="client_incomplete_stream",
                message="stream ended without final or error",
            )

    def fetch_corpus(self) -> CorpusInfo:
        """GET /v1/corpus. Raises httpx.HTTPError on failure."""
        response = self._http.get("/v1/corpus")
        response.raise_for_status()
        data = response.json()
        snapshot = data.get("snapshot_date")
        if not isinstance(snapshot, str):
            snapshot = str(snapshot) if snapshot is not None else ""
        return CorpusInfo(
            documents=list(data.get("documents", [])),
            snapshot_date=snapshot,
        )


def get_client() -> BackendClient:
    """Injection seam for the Streamlit app and tests."""
    base_url = os.environ.get("BACKEND_URL", DEFAULT_BACKEND_URL)
    return BackendClient(base_url=base_url)
