import asyncio

from app.pipeline.resolve import normalize_label, resolve
from app.schemas.domain import Provision
from app.schemas.llm import ExternalReference, RequestedProvision


def test_normalize_label_cases():
    assert normalize_label("article", "4 bis") == "art_4a"
    assert normalize_label("article", "4bis") == "art_4a"
    assert normalize_label("article", "4a") == "art_4a"
    assert normalize_label("annex", "III") == "anx_III"
    assert normalize_label("annex", "iii") == "anx_III"
    assert normalize_label("recital", "(40)") == "rct_40"


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


def test_resolve_basic():
    rows = {"DOC:art_1": [make_provision("DOC:art_1")]}
    lookup = StubLookup(rows)
    req = RequestedProvision(document="DOC", kind="article", label="1", reason="r")
    res = asyncio.get_event_loop().run_until_complete(
        resolve(
            [req],
            [],
            kept=[],
            document_keys=["DOC"],
            lookup=lookup,
            max_added=None,
        )
    )
    assert len(res.added) == 1
    assert not res.unavailable


def test_resolve_not_indexed_and_external():
    rows = {}
    lookup = StubLookup(rows)
    req = RequestedProvision(document="DOC", kind="article", label="1", reason="r")
    ext = ExternalReference(citation="http://x", reason="r")
    res = asyncio.get_event_loop().run_until_complete(
        resolve(
            [req],
            [ext],
            kept=[],
            document_keys=["DOC"],
            lookup=lookup,
            max_added=None,
        )
    )
    assert any(u.reason == "not_indexed" for u in res.unavailable)
    assert any(u.reason == "external" for u in res.unavailable)


def test_resolve_over_cap():
    rows = {
        "DOC:art_1": [make_provision("DOC:art_1")],
        "DOC:art_2": [make_provision("DOC:art_2")],
    }
    lookup = StubLookup(rows)
    reqs = [
        RequestedProvision(document="DOC", kind="article", label="1", reason="r"),
        RequestedProvision(document="DOC", kind="article", label="2", reason="r"),
    ]
    res = asyncio.get_event_loop().run_until_complete(
        resolve(reqs, [], kept=[], document_keys=["DOC"], lookup=lookup, max_added=1)
    )
    assert len(res.added) == 1
    assert any(u.reason == "over_cap" for u in res.unavailable)
