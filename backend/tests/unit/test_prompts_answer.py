import re
from datetime import date
from pathlib import Path

import pytest

from app.pipeline.prompts.answer import ANSWER_PROMPT_VERSION, build_answer_prompt
from app.schemas.llm import Message, Situation

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "prompts" / "answer.txt"

pytestmark = pytest.mark.unit


def _fixture_messages() -> list[Message]:
    conv = [Message(role="user", content="Hallo")]
    situation = Situation(role="provider", domain="werving", notes="nota")
    final_context = [
        {"ref": "DOC:art_1", "header": "H1", "body": "B1"},
        {"ref": "DOC:art_2", "header": "H2", "body": "B2"},
    ]
    documents = [{"key": "DOC", "short_name": "Doc", "identifier": "X"}]
    unavailable = [
        {"citation": "DOC:art_99", "reason": "not_indexed", "detail": "no row"},
        {"citation": "OTHER:art_1", "reason": "external", "detail": None},
        {"citation": "DOC:art_3", "reason": "over_cap", "detail": "max=1"},
    ]
    return build_answer_prompt(
        conv,
        situation,
        final_context,
        unavailable,
        documents,
        date(2026, 1, 1),
    )


def test_build_answer_prompt_contains_provisions_once():
    msgs = _fixture_messages()
    prompt = msgs[-1].content
    assert re.fullmatch(r"v\d+", ANSWER_PROMPT_VERSION)
    assert ANSWER_PROMPT_VERSION in prompt
    assert prompt.count('<provision ref="DOC:art_1">') == 1
    assert prompt.count('<provision ref="DOC:art_2">') == 1
    assert msgs[0].role == "user"
    assert msgs[-1].role == "user"


def test_build_answer_prompt_includes_clarify_conditions():
    prompt = _fixture_messages()[-1].content.lower()
    assert "materially different" in prompt
    assert "situation" in prompt and "conversation" in prompt
    assert "previous assistant" in prompt or "already a clarifying" in prompt
    assert "cannot_answer" in prompt
    assert "leave answer empty" in prompt or "answer empty" in prompt
    assert "do not infer a role" in prompt
    assert "gebruiken" in prompt


def test_build_answer_prompt_includes_content_rules():
    prompt = _fixture_messages()[-1].content.lower()
    assert "no verdict" in prompt or "do not state that" in prompt
    assert "overweging" in prompt
    assert "gewijzigd bij" in prompt
    assert "situation panel" in prompt or "wins over" in prompt
    assert "dutch" in prompt
    assert "formally" in prompt or "u, uw" in prompt or "(u, uw)" in prompt
    assert "aanbieder" in prompt
    assert "gebruiksverantwoordelijke" in prompt
    assert "not in the corpus (not indexed)" in prompt
    assert "external reference, not in the corpus" in prompt
    assert "context limit was reached" in prompt
    assert "2026-01-01" in _fixture_messages()[-1].content
    assert "eu" in prompt


def test_build_answer_prompt_matches_golden():
    prompt = _fixture_messages()[-1].content
    assert prompt == GOLDEN.read_text(encoding="utf-8")
