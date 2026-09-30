"""Unit tests for LLM structured-output schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.llm import (
    AnswerResult,
    ExternalReference,
    Message,
    RequestedProvision,
    SelectionResult,
    Situation,
)


def _situation() -> Situation:
    return Situation(role="unknown", domain=None, notes=None)


@pytest.mark.unit
def test_selection_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SelectionResult(
            keep=[],
            discard=[],
            request=[],
            external_references=[],
            unexpected=True,  # type: ignore[call-arg]
        )


@pytest.mark.unit
def test_answer_result_valid_answer() -> None:
    result = AnswerResult(
        reasoning="Artikel 3 definieert aanbieder.",
        action="answer",
        answer="Een aanbieder brengt een AI-systeem in de handel.",
        clarifying_questions=[],
        citations=["AI-verordening:art_3"],
        situation=_situation(),
    )
    assert result.action == "answer"


@pytest.mark.unit
def test_answer_result_valid_clarify() -> None:
    result = AnswerResult(
        reasoning="Rol bepaalt de verplichtingen.",
        action="clarify",
        answer=None,
        clarifying_questions=["Bent u de aanbieder of de gebruiksverantwoordelijke?"],
        citations=[],
        situation=_situation(),
    )
    assert result.action == "clarify"


@pytest.mark.unit
def test_answer_result_valid_cannot_answer() -> None:
    result = AnswerResult(
        reasoning="Geen dekking in de context.",
        action="cannot_answer",
        answer="De verstrekte bepalingen dekken deze vraag niet.",
        clarifying_questions=[],
        citations=[],
        situation=_situation(),
    )
    assert result.action == "cannot_answer"


@pytest.mark.unit
def test_answer_rejects_clarify_with_answer_text() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="clarify",
            answer="Dit mag niet.",
            clarifying_questions=["Vraag?"],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_clarify_with_zero_questions() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="clarify",
            answer=None,
            clarifying_questions=[],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_clarify_with_three_questions() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="clarify",
            answer=None,
            clarifying_questions=["a?", "b?", "c?"],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_answer_without_text() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="answer",
            answer=None,
            clarifying_questions=[],
            citations=["AI-verordening:art_3"],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_answer_without_citations() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="answer",
            answer="Tekst zonder bron.",
            clarifying_questions=[],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_cannot_answer_without_explanation() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="cannot_answer",
            answer=None,
            clarifying_questions=[],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_answer_rejects_cannot_answer_with_questions() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(
            reasoning="x",
            action="cannot_answer",
            answer="Uitleg.",
            clarifying_questions=["Nog een vraag?"],
            citations=[],
            situation=_situation(),
        )


@pytest.mark.unit
def test_message_rejects_action_on_user_role() -> None:
    with pytest.raises(ValidationError):
        Message(role="user", content="Hallo", action="answer")


@pytest.mark.unit
def test_message_allows_action_on_assistant() -> None:
    msg = Message(role="assistant", content="Antwoord", action="answer")
    assert msg.action == "answer"


@pytest.mark.unit
def test_answer_result_json_schema_lists_reasoning_first() -> None:
    schema = AnswerResult.model_json_schema()
    props = list(schema["properties"])
    assert props[0] == "reasoning"
    assert props[1] == "action"


@pytest.mark.unit
def test_requested_provision_and_external_reference_round_trip() -> None:
    selection = SelectionResult(
        keep=["AI-verordening:art_6"],
        discard=["AVG:art_9"],
        request=[
            RequestedProvision(
                document="AI-verordening",
                kind="annex",
                label="III",
                reason="Classificatie verwijst hiernaar.",
            ),
            RequestedProvision(
                document="DSA",
                kind="article",
                label="1",
                reason="Extra corpus document is allowed by schema.",
            ),
        ],
        external_references=[
            ExternalReference(
                citation="Verordening (EU) 2019/881, artikel 54",
                reason="Verwezen in de bijlage.",
            )
        ],
    )
    restored = SelectionResult.model_validate(selection.model_dump())
    assert restored == selection
    assert restored.request[1].document == "DSA"
