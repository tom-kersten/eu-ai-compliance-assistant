import asyncio

import pytest

from app.errors import SelectionInvalid
from app.pipeline.select import select, validate_selection
from app.providers.fakes import ScriptedLLM
from app.schemas.llm import Message, SelectionResult

pytestmark = pytest.mark.unit


def make_result(keep, discard, requests=None):
    return SelectionResult(
        keep=keep, discard=discard, request=requests or [], external_references=[]
    )


def test_valid_partition_passes():
    retrieved = ["A", "B", "C"]
    res = make_result(["A", "B"], ["C"])
    # should not raise
    validate_selection(res, retrieved)


def test_unknown_ref_raises():
    retrieved = ["A", "B"]
    res = make_result(["A"], ["C"])
    with pytest.raises(SelectionInvalid):
        validate_selection(res, retrieved)


def test_missing_retrieved_ref_raises():
    retrieved = ["A", "B"]
    res = make_result(["A"], [])
    with pytest.raises(SelectionInvalid):
        validate_selection(res, retrieved)


def test_select_calls_llm_and_validates():
    llm = ScriptedLLM()
    payload = {
        "keep": ["A"],
        "discard": ["B"],
        "request": [],
        "external_references": [],
    }
    llm.push(payload)

    async def run():
        m = Message(role="user", content="x")
        out = await select(llm, [m], reasoning_effort=None)
        return out

    out = asyncio.run(run())
    assert out.keep == ["A"]
    assert out.discard == ["B"]


def test_select_passes_only_the_effort_level():
    captured: dict = {}

    class RecordingLLM:
        async def respond(self, **kwargs):
            captured.update(kwargs)
            return {"keep": [], "discard": [], "request": [], "external_references": []}

    m = Message(role="user", content="x")
    asyncio.run(select(RecordingLLM(), [m], reasoning_effort="low"))
    assert captured["reasoning_effort"] == "low"
    assert "reasoning" not in captured
