import asyncio

import pytest

from app.errors import AnswerInvalid
from app.pipeline.answer import answer
from app.schemas.llm import AnswerResult, Message, Situation


class DummyLLM:
    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    async def respond(self, *, messages=None, schema=None, reasoning=None):
        self.last_kwargs = {
            "messages": messages,
            "schema": schema,
            "reasoning": reasoning,
        }
        return self.response


def make_answer_payload(action="answer", citations=None, situation=None):
    return {
        "reasoning": "r",
        "action": action,
        "answer": "text" if action == "answer" else None,
        "clarifying_questions": ["q"] if action == "clarify" else [],
        "citations": citations or [],
        "situation": situation or {"role": "unknown"},
    }


def test_answer_step_valid_and_validation():
    conv = [Message(role="user", content="hi")]
    situation = Situation(role="provider")
    final_context = [{"ref": "DOC:art_1", "header": "", "body": ""}]
    documents = [{"key": "DOC", "short_name": "Doc", "identifier": "X"}]
    unavailable = []

    # valid answer
    payload = make_answer_payload(action="answer", citations=["DOC:art_1"])
    llm = DummyLLM(payload)

    async def run():
        out = await answer(
            llm,
            conv,
            situation,
            final_context,
            unavailable,
            documents,
            __import__("datetime").date(2026, 1, 1),
            reasoning_effort="medium",
        )
        return out

    res = asyncio.get_event_loop().run_until_complete(run())
    assert isinstance(res, AnswerResult)
    # reasoning payload passed through
    assert llm.last_kwargs["reasoning"] == {"effort": "medium", "exclude": False}

    # bad citation -> AnswerInvalid
    bad_payload = make_answer_payload(action="answer", citations=["DOC:art_99"])
    llm2 = DummyLLM(bad_payload)

    async def run2():
        await answer(
            llm2,
            conv,
            situation,
            final_context,
            unavailable,
            documents,
            __import__("datetime").date(2026, 1, 1),
            reasoning_effort=None,
        )

    with pytest.raises(AnswerInvalid):
        asyncio.get_event_loop().run_until_complete(run2())
