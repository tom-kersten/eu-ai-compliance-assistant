from pathlib import Path

import pytest

from eval.run_eval import load_questions, run_use_fakes

pytestmark = pytest.mark.unit


def test_run_eval_use_fakes_covers_every_question():
    questions = load_questions(Path("eval/eval_questions.json"))
    report = run_use_fakes(questions)
    assert len(report.items) == len(questions)
