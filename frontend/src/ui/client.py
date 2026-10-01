from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


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


class SSEParser:
    """
    Minimal SSE parser for the frontend tests.
    Call feed() with bytes; it returns a list of typed events parsed up to the
    last complete double-newline. Call feed(b"") to flush any remaining data.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, data: bytes) -> list[Any]:
        text = data.decode("utf-8") if data else ""
        # Normalize CRLF to LF
        text = text.replace("\r\n", "\n")
        self._buf += text
        events: list[Any] = []

        # If called with an empty chunk, try to flush any remaining event(s).
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

    def _parse_chunk(self, chunk: str) -> Any | None:
        lines = [line for line in chunk.split("\n") if line.strip() != ""]
        event_name = None
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
            else:
                # ignore other fields or comments
                pass

        data_text = "\n".join(data_lines) if data_lines else ""
        try:
            payload = json.loads(data_text) if data_text else {}
        except Exception:
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
        # Unknown event - ignore
        return None


def __all__() -> list[str]:
    return [
        "SSEParser",
        "StatusEvent",
        "RetrievedEvent",
        "SelectionEvent",
        "FinalEvent",
        "ErrorEvent",
    ]
