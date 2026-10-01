\"\"\"CLI to run the evaluation set."""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

from .models import EvalReport, EvalReportItem
from .fakes import fake_for_question


def load_questions(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_use_fakes(questions):
    items = []
    for q in questions:
        qid = q["id"]
        must = q.get("must", [])
        retrieved, selection, final = fake_for_question(qid, must)
        items.append(
            EvalReportItem(
                id=qid,
                expected_behavior=q["expected_behavior"],
                actual_action=final.action,
                behavior_match=(q["expected_behavior"] == final.action),
                vector_hit=bool(retrieved and len(retrieved.provisions) > 0),
                selection_hit=bool(selection and len(selection.kept) > 0),
                llm_call_count=final.usage.calls,
                prompt_tokens=final.usage.prompt_tokens,
                completion_tokens=final.usage.completion_tokens,
                reasoning_tokens=final.usage.reasoning_tokens,
                latency_seconds=0.0,
            )
        )
    report = EvalReport(generated_at=datetime.utcnow(), items=items, summary={})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-fakes", action="store_true")
    parser.add_argument("--question", type=str)
    parser.add_argument("--reports-dir", default="eval/reports")
    parser.add_argument("--eval-file", default="eval/eval_questions.json")
    args = parser.parse_args(argv)

    questions = load_questions(Path(args.eval_file))
    if args.use_fakes:
        report = run_use_fakes(questions)
    else:
        raise SystemExit("Only --use-fakes is implemented in this test runner.")

    outdir = Path(args.reports_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{datetime.utcnow().isoformat()}.json"
    out_path.write_text(report.model_dump_json())
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()

