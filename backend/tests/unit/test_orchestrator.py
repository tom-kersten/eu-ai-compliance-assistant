import asyncio
from datetime import date

from app.config import Settings
from app.pipeline.orchestrator import run
from app.providers.fakes import FakeEmbedder, ScriptedLLM
from app.schemas.api import AskRequest
from app.schemas.domain import RetrievedProvision
from app.schemas.llm import Message


class StubRepository:
    def __init__(self, results):
        self._results = results

    async def search_similar(self, query, *, top_k, threshold):
        return list(self._results)

    # resolve lookup used by resolve(): get_by_parent_ref and get_by_refs
    async def get_by_parent_ref(self, parent_ref):
        return []

    async def get_by_refs(self, refs):
        return []


def make_retrieved(ref: str) -> RetrievedProvision:
    return RetrievedProvision(
        ref=ref,
        doc="DOC",
        kind="article",
        label="1",
        parent_ref=ref,
        header="H",
        body="B",
        token_estimate=1,
        similarity=0.9,
    )


def collect_events(evt_iter):
    out = []

    async def _collect():
        async for e in evt_iter:
            out.append(e)

    asyncio.get_event_loop().run_until_complete(_collect())
    return out


def test_empty_retrieval_no_llm_calls():
    settings = Settings()
    embedder = FakeEmbedder()
    repo = StubRepository([])
    llm = ScriptedLLM()
    req = AskRequest(messages=[Message(role="user", content="hello")])
    events = collect_events(
        run(
            req,
            settings=settings,
            embedder=embedder,
            llm=llm,
            repository=repo,
            documents=[],
            snapshot=date.today(),
        )
    )
    # expecting searching, retrieved, final
    assert len(events) == 3
    assert events[0].step == "searching"
    assert events[1].event == "retrieved"
    assert events[2].event == "final"
    assert events[2].usage.calls == 0
    assert events[2].usage.prompt_versions == {}


def test_happy_path_basic_usage_and_order():
    settings = Settings()
    embedder = FakeEmbedder()
    # one retrieved provision
    prov = make_retrieved("DOC:art_1")
    repo = StubRepository([prov])
    # scripted LLM: selection then answer
    llm = ScriptedLLM()
    selection_payload = {
        "keep": ["DOC:art_1"],
        "discard": [],
        "request": [],
        "external_references": [],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "completion_tokens_details": {"reasoning_tokens": 1},
        },
    }
    answer_payload = {
        "reasoning": "r",
        "action": "answer",
        "answer": "antwoord",
        "clarifying_questions": [],
        "citations": ["DOC:art_1"],
        "situation": {"role": "unknown", "domain": None, "notes": None},
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }
    llm.push(selection_payload)
    llm.push(answer_payload)
    req = AskRequest(messages=[Message(role="user", content="vraag")])
    events = collect_events(
        run(
            req,
            settings=settings,
            embedder=embedder,
            llm=llm,
            repository=repo,
            documents=[{"key": "DOC", "short_name": "DOC", "identifier": "id"}],
            snapshot=date.today(),
        )
    )
    # expecting searching, retrieved, selecting, selection, answering, final
    kinds = [getattr(e, "event", getattr(e, "step", None)) for e in events]
    assert "searching" in kinds[0]
    assert events[-1].event == "final"
    # usage aggregated: two calls
    assert events[-1].usage.calls == 2
    assert events[-1].usage.prompt_tokens == 8
    assert events[-1].usage.completion_tokens == 9
    assert events[-1].usage.reasoning_tokens == 3
    assert events[-1].usage.prompt_versions.get("selection") is not None
    assert events[-1].usage.prompt_versions.get("answer") is not None
