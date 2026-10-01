from datetime import date

from app.pipeline.prompts.selection import (
    SELECTION_PROMPT_VERSION,
    build_selection_prompt,
)
from app.schemas.llm import Message, Situation


def test_build_selection_prompt_contains_provisions_once():
    conv = [Message(role="user", content="Hallo")]
    situation = Situation(role="provider", domain="test")
    retrieved = [
        {"ref": "DOC:art_1", "header": "H1", "body": "B1"},
        {"ref": "DOC:art_2", "header": "H2", "body": "B2"},
    ]
    documents = [{"key": "DOC", "short_name": "Doc", "identifier": "X"}]
    msgs = build_selection_prompt(
        conv, situation, retrieved, documents, date(2026, 1, 1), max_added=None
    )
    # last message is the prompt
    prompt = msgs[-1].content
    assert SELECTION_PROMPT_VERSION in prompt
    # each provision appears exactly once in provision tags
    assert prompt.count('<provision ref="DOC:art_1">') == 1
    assert prompt.count('<provision ref="DOC:art_2">') == 1
