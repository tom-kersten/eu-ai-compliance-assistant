import asyncio

from app.pipeline.resolve import resolve
from app.pipeline.select import select, validate_selection
from app.providers.fakes import ScriptedLLM
from app.schemas.domain import Provision


class StubLookup:
    def __init__(self, rows_by_parent):
        self.rows_by_parent = rows_by_parent

    async def get_by_parent_ref(self, parent_ref):
        return self.rows_by_parent.get(parent_ref, [])

    async def get_by_refs(self, refs):
        out = []
        for r in refs:
            out.extend(self.rows_by_parent.get(r, []))
        return out


def make_provision(ref):
    return Provision(
        ref=ref,
        doc="DOC",
        kind="article",
        label="1",
        parent_ref=ref,
        header="h",
        body="b",
        token_estimate=1,
    )


async def run_integration():
    llm = ScriptedLLM()
    # scripted selection result
    payload = {
        "keep": ["DOC:art_1"],
        "discard": [],
        "request": [],
        "external_references": [],
    }
    llm.push(payload)
    msgs = [{"role": "user", "content": "x"}]
    res = await select(llm, msgs, reasoning_effort=None)
    # validate
    validate_selection(res, ["DOC:art_1"])
    # resolve (no requests)
    lookup = StubLookup({"DOC:art_1": [make_provision("DOC:art_1")]})
    rr = await resolve(
        [], [], kept=res.keep, document_keys=["DOC"], lookup=lookup, max_added=None
    )
    return res, rr


def test_selection_integration():
    res, rr = asyncio.get_event_loop().run_until_complete(run_integration())
    assert res.keep == ["DOC:art_1"]
    assert len(rr.added) == 0 or len(rr.added) == 1
