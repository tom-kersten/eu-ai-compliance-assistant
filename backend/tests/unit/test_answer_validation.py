import logging

import pytest

from app.errors import AnswerInvalid
from app.pipeline.validators import (
    validate_answer_citations,
    validate_clarify_allowed,
    warn_unknown_article_mentions,
)
from app.schemas.llm import AnswerResult, Message


def test_citation_subset_passes_and_fails():
    res = AnswerResult(
        reasoning="r",
        action="answer",
        answer="ok",
        clarifying_questions=[],
        citations=["DOC:art_1"],
        situation={"role": "unknown"},
    )
    # should not raise
    validate_answer_citations(res, ["DOC:art_1"])
    # missing citation
    with pytest.raises(AnswerInvalid):
        validate_answer_citations(res, ["DOC:art_2"])


def test_clarify_after_clarify_rejected():
    conv = [
        Message(role="user", content="q"),
        Message(role="assistant", content="c", action="clarify"),
    ]
    res = AnswerResult(
        reasoning="r",
        action="clarify",
        answer=None,
        clarifying_questions=["q1"],
        citations=[],
        situation={"role": "unknown"},
    )
    with pytest.raises(AnswerInvalid):
        validate_clarify_allowed(res, conv)


def test_warn_unknown_article_mentions_logs_warning(caplog):
    caplog.set_level(logging.WARNING)
    answer_text = "Volgens artikel 99 is dit anders."
    final_context = [
        # article 26 present
        type("P", (), {"kind": "article", "label": "26"}),
    ]
    warn_unknown_article_mentions(answer_text, final_context, logging.getLogger("test"))
    assert any("missing article mentions" in r.message for r in caplog.records)
