import json
from pathlib import Path

from eval.models import EvalFile


def test_eval_file_validates():
    path = Path("eval/eval_questions.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    # The approved format is a list; wrap into EvalFile.questions for validation.
    wrapped = {"questions": data}
    ef = EvalFile.model_validate(wrapped)
    assert len(ef.questions) == 9
    ids = {q.id for q in ef.questions}
    assert "Q01" in ids and "Q09" in ids
