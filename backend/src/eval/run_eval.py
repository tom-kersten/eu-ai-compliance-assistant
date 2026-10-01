# CLI to run the evaluation set (backend copy).
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

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
