import pytest

from eval.metrics import (
    behavior_match,
    context_hit,
    empty_retrieval_ok,
    score_question,
)

pytestmark = pytest.mark.unit


def test_context_hit_requires_every_must_ref():
    assert context_hit(["a", "b", "c"], ["a", "c"])
    assert not context_hit(["a", "b"], ["a", "c"])


def test_behavior_match():
    assert behavior_match("clarify", "clarify")
    assert not behavior_match("clarify", "answer")


def test_empty_retrieval_ok_for_out_of_corpus():
    assert empty_retrieval_ok(
        retrieved_count=0, action="cannot_answer", llm_call_count=0
    )
    assert not empty_retrieval_ok(
        retrieved_count=0, action="cannot_answer", llm_call_count=1
    )
    assert not empty_retrieval_ok(
        retrieved_count=1, action="cannot_answer", llm_call_count=0
    )


def test_score_question_combines_flags():
    result = score_question(
        must_refs=["AI-verordening:art_3"],
        expected_behavior="answer",
        retrieved_refs=["AI-verordening:art_3", "AI-verordening:art_25"],
        final_refs=["AI-verordening:art_3"],
        action="answer",
        llm_call_count=2,
    )
    assert result["vector_hit"] is True
    assert result["context_hit"] is True
    assert result["behavior_match"] is True
    assert result["empty_retrieval_ok"] is False
    assert result["llm_call_count"] == 2
