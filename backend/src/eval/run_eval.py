# CLI to run the evaluation set (backend copy).
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime
from pathlib import Path

from app.config import Settings
from app.pipeline import orchestrator as orch
from app.schemas.api import AskRequest
from app.schemas.llm import Message, Situation

from . import metrics as eval_metrics
from .fakes import fake_for_question
from .models import EvalReport, EvalReportItem


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
    # main imports are at module level

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
        settings = Settings()
        if not settings.embedding_api_key or not settings.llm_api_key:
            raise SystemExit("Missing provider configuration for live eval")

        async def _run_one(q):
            msg = Message(role="user", content=q["question"])
            req = AskRequest(messages=[msg], situation=Situation())
            retrieved = None
            selection = None
            final = None
            async for ev in orch.run(
                req,
                settings=settings,
                embedder=None,
                llm=None,
                repository=None,
                documents=[],
                snapshot=date.today(),
            ):
                if getattr(ev, "event", None) == "retrieved":
                    retrieved = ev
                if getattr(ev, "event", None) == "selection":
                    selection = ev
                if getattr(ev, "event", None) == "final":
                    final = ev
                    break
            vv = False
            if retrieved:
                vv = bool(eval_metrics.vector_hit(retrieved, q.get("must", [])))
            sv = False
            if selection:
                sv = bool(eval_metrics.selection_hit(selection, q.get("must", [])))
            return EvalReportItem(
                id=q["id"],
                expected_behavior=q["expected_behavior"],
                actual_action=final.action if final else "error",
                behavior_match=(
                    (q["expected_behavior"] == final.action) if final else False
                ),
                vector_hit=vv,
                selection_hit=sv,
                llm_call_count=final.usage.calls if final else 0,
                prompt_tokens=final.usage.prompt_tokens if final else 0,
                completion_tokens=final.usage.completion_tokens if final else 0,
                reasoning_tokens=final.usage.reasoning_tokens if final else 0,
                latency_seconds=0.0,
            )

        items = [asyncio.run(_run_one(q)) for q in questions]
        report = EvalReport(generated_at=datetime.utcnow(), items=items, summary={})

    outdir = Path(args.reports_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{datetime.utcnow().isoformat()}.json"
    out_path.write_text(report.model_dump_json())
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
