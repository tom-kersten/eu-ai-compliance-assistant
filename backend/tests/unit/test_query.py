"""Unit tests for pipeline.query."""

from __future__ import annotations

import pytest

from app.pipeline.query import build_query
from app.schemas.llm import Message


@pytest.mark.unit
def test_build_query_last_n_user_messages() -> None:
    msgs: list[Message] = [
        Message(role="user", content="Q1"),
        Message(role="assistant", content="A1"),
        Message(role="user", content="Q2"),
        Message(role="user", content="Q3"),
    ]
    out = build_query(msgs, history_turns=2)
    assert out == "Q2\nQ3"


@pytest.mark.unit
def test_build_query_fewer_than_n() -> None:
    msgs = [
        Message(role="assistant", content="A1"),
        Message(role="user", content="Only"),
    ]
    out = build_query(msgs, history_turns=5)
    assert out == "Only"


@pytest.mark.unit
def test_build_query_excludes_assistant() -> None:
    msgs = [
        Message(role="assistant", content="A1"),
        Message(role="assistant", content="A2"),
    ]
    out = build_query(msgs, history_turns=2)
    assert out == ""


@pytest.mark.unit
def test_build_query_empty_history_and_zero_turns() -> None:
    msgs: list[Message] = []
    assert build_query(msgs, history_turns=0) == ""
    msgs = [Message(role="assistant", content="A1")]
    assert build_query(msgs, history_turns=0) == ""
