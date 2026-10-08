from datetime import date
from pathlib import Path

import pytest

from app.pipeline.prompts.selection import (
    SELECTION_PROMPT_VERSION,
    build_selection_prompt,
)
from app.schemas.llm import Message, Situation

GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "prompts" / "selection.txt"

pytestmark = pytest.mark.unit


def _fixture_messages(*, max_added: int | None = 1) -> list[Message]:
    conv = [Message(role="user", content="Hallo")]
    situation = Situation(role="provider", domain="werving", notes="cv-screening")
    retrieved = [
        {"ref": "DOC:art_1", "header": "H1", "body": "B1"},
        {"ref": "DOC:art_2", "header": "H2", "body": "B2"},
    ]
    documents = [{"key": "DOC", "short_name": "Doc", "identifier": "X"}]
    return build_selection_prompt(
        conv,
        situation,
        retrieved,
        documents,
        date(2026, 1, 1),
        max_added=max_added,
    )


def test_build_selection_prompt_contains_provisions_once():
    msgs = _fixture_messages()
    prompt = msgs[-1].content
    assert SELECTION_PROMPT_VERSION.startswith("T18")
    assert SELECTION_PROMPT_VERSION in prompt
    assert prompt.count('<provision ref="DOC:art_1">') == 1
    assert prompt.count('<provision ref="DOC:art_2">') == 1


def test_build_selection_prompt_renders_situation_and_cap():
    msgs = _fixture_messages(max_added=1)
    prompt = msgs[-1].content
    assert "aanbieder" in prompt
    assert "werving" in prompt
    assert "cv-screening" in prompt
    assert "at most 1" in prompt.lower() or "maximum of 1" in prompt.lower()


def test_build_selection_prompt_includes_spec_rules():
    msgs = _fixture_messages()
    prompt = msgs[-1].content.lower()
    assert "keep" in prompt and "discard" in prompt
    assert "exactly once" in prompt
    assert "when unsure, keep" in prompt
    assert "explicitly" in prompt
    assert "presumption of conformity" in prompt or "named article" in prompt
    assert "bare identifier" in prompt or "'6'" in msgs[-1].content
    assert "external_references" in prompt or "external reference" in prompt
    assert "date" in prompt or "deadline" in prompt
    assert "do not answer the question" in prompt
    assert "dutch" in prompt
    assert "eu" in prompt
    assert "2026-01-01" in msgs[-1].content
    assert "one-line" in prompt or "one line" in prompt


def test_build_selection_prompt_matches_golden():
    msgs = _fixture_messages()
    prompt = msgs[-1].content
    assert prompt == GOLDEN.read_text(encoding="utf-8")
