from datetime import date

from app.pipeline.prompts.answer import ANSWER_PROMPT_VERSION, build_answer_prompt
from app.schemas.llm import Message, Situation


def test_build_answer_prompt_matches_golden(tmp_path):
    conv = [Message(role="user", content="Hallo")]
    situation = Situation(role="provider", domain="test", notes="nota")
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
    msgs = build_answer_prompt(
        conv,
        situation,
        final_context,
        unavailable,
        documents,
        date(2026, 1, 1),
    )
    prompt = msgs[-1].content
    assert ANSWER_PROMPT_VERSION in prompt
    # each provision appears exactly once
    assert prompt.count('<provision ref="DOC:art_1">') == 1
    assert prompt.count('<provision ref="DOC:art_2">') == 1
    # conversation precedes prompt
    assert msgs[0].role == "user"
    assert msgs[-1].role == "user"
