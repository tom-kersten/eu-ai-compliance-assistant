from eval.run_eval import load_questions, run_use_fakes


def test_run_eval_use_fakes_writes_report(tmp_path):
    questions = load_questions(__import__("pathlib").Path("eval/eval_questions.json"))
    report = run_use_fakes(questions)
    assert report.items
    # Ensure items count equals questions
    assert len(report.items) == len(questions)
