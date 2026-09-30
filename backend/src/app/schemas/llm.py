"""Pydantic models for LLM messages and structured outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.domain import DocumentName, ProvisionKind

AnswerAction = Literal["answer", "clarify", "cannot_answer"]
RoleName = Literal["user", "assistant"]
SituationRole = Literal["provider", "deployer", "importer", "distributor", "unknown"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: RoleName
    content: str
    action: AnswerAction | None = None

    @model_validator(mode="after")
    def _action_only_on_assistant(self) -> Message:
        if self.action is not None and self.role != "assistant":
            msg = "action is only allowed on assistant messages"
            raise ValueError(msg)
        return self


class Situation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SituationRole = "unknown"
    domain: str | None = None
    notes: str | None = None


class RequestedProvision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentName
    kind: ProvisionKind
    label: str
    reason: str


class ExternalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation: str
    reason: str


class SelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: list[str]
    discard: list[str]
    request: list[RequestedProvision]
    external_references: list[ExternalReference]


class AnswerResult(BaseModel):
    """Field order matters: reasoning comes first for structured output."""

    model_config = ConfigDict(extra="forbid")

    reasoning: str
    action: AnswerAction
    answer: str | None
    clarifying_questions: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    situation: Situation

    @model_validator(mode="after")
    def _shape_for_action(self) -> AnswerResult:
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
