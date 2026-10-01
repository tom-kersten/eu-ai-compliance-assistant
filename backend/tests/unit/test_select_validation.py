import asyncio

import pytest

from app.errors import SelectionInvalid
from app.pipeline.select import select, validate_selection
from app.providers.fakes import ScriptedLLM
from app.schemas.llm import SelectionResult


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
        # use a minimal Message-like dict to pass through
        m = __import__("pydantic").BaseModel.parse_obj({"role": "user", "content": "x"})
        out = await select(llm, [m], reasoning_effort=None)
        return out

    # we only assert that scripted llm returns without raising
    asyncio.get_event_loop().run_until_complete(run())
