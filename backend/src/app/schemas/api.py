"""API request, corpus info, and SSE event models."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.llm import AnswerAction, Message, Situation


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[Message]
    situation: Situation = Field(default_factory=Situation)


class CorpusDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    short_name: str
    identifier: str
    provision_count: int


class CorpusInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[CorpusDocument]
    snapshot_date: date


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int = 0


class DisplayCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    header: str
    body: str


class RetrievedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    title: str | None
    similarity: float


class StatusEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["status"] = "status"
    step: Literal["searching", "selecting", "answering"]


class RetrievedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["retrieved"] = "retrieved"
    provisions: list[RetrievedItem]


class SelectionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["selection"] = "selection"
    kept: list[str]
    discarded: list[str]
    added: list[str]
    unavailable: list[str]


class FinalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["final"] = "final"
    action: AnswerAction
    answer: str | None = None
    clarifying_questions: list[str] = Field(default_factory=list)
    citations: list[DisplayCitation] = Field(default_factory=list)
    situation: Situation
    usage: Usage
    corpus_snapshot: date

    @model_validator(mode="after")
    def _shape_for_action(self) -> FinalEvent:
        questions = self.clarifying_questions
        answer_text = self.answer
        if self.action == "answer":
            if answer_text is None or not answer_text.strip():
                msg = "answer requires non-empty answer text"
                raise ValueError(msg)
            if not self.citations:
                msg = "answer requires at least one citation"
                raise ValueError(msg)
            if questions:
                msg = "answer must not include clarifying questions"
                raise ValueError(msg)
        elif self.action == "clarify":
            if answer_text is not None:
                msg = "clarify must not include answer text"
                raise ValueError(msg)
            if not 1 <= len(questions) <= 2:
                msg = "clarify requires one or two clarifying questions"
                raise ValueError(msg)
            if any(not q.strip() for q in questions):
                msg = "clarifying questions must be non-empty"
                raise ValueError(msg)
        else:  # cannot_answer
            if answer_text is None or not answer_text.strip():
                msg = "cannot_answer requires an explanation in answer"
                raise ValueError(msg)
            if questions:
                msg = "cannot_answer must not include clarifying questions"
                raise ValueError(msg)
        return self


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Literal["error"] = "error"
    code: str
    message: str


AskEvent = Annotated[
    StatusEvent | RetrievedEvent | SelectionEvent | FinalEvent | ErrorEvent,
    Field(discriminator="event"),
]
