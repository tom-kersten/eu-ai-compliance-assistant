"""CLI to run the evaluation set."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.ingestion.manifest import load_manifest
from app.pipeline import orchestrator as orch
from app.providers.openai_compat import OpenRouterAdapter
from app.schemas.api import AskRequest, SelectionEvent
from app.schemas.llm import Message, Situation
from app.store.db import create_pool
from app.store.repository import Repository

from . import metrics as eval_metrics
from .fakes import fake_for_question
from .models import EvalReport, EvalReportItem

DEFAULT_CORPUS_MANIFEST = Path("/app/corpus/manifest.yaml")


def load_questions(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_use_fakes(questions: list[dict]) -> EvalReport:
    items = []
    for q in questions:
        qid = q["id"]
        must = q.get("must", [])
        retrieved, selection, final = fake_for_question(
            qid, must, expected_behavior=q["expected_behavior"]
        )
        vector_ok = (
            bool(eval_metrics.vector_hit(retrieved, must))
            if retrieved is not None
            else False
        )
        selection_ok = bool(
            eval_metrics.selection_hit(
                selection
                if selection is not None
                else SelectionEvent(kept=[], discarded=[], added=[], unavailable=[]),
                must,
            )
        )
        items.append(
            EvalReportItem(
                id=qid,
                expected_behavior=q["expected_behavior"],
                actual_action=final.action,
                behavior_match=(q["expected_behavior"] == final.action),
                vector_hit=vector_ok,
                selection_hit=selection_ok,
                llm_call_count=final.usage.calls,
                prompt_tokens=final.usage.prompt_tokens,
                completion_tokens=final.usage.completion_tokens,
                reasoning_tokens=final.usage.reasoning_tokens,
                latency_seconds=0.0,
            )
        )
    return EvalReport(
        generated_at=datetime.now(UTC),
        items=items,
        summary=_summarize(items, questions),
    )


def _documents_from_manifest(manifest_path: Path) -> list[dict]:
    manifest = load_manifest(manifest_path)
    return [
        {
            "key": doc.key,
            "short_name": doc.short_name,
            "identifier": doc.identifier,
        }
        for doc in manifest.documents
    ]


def _summarize(items: list[EvalReportItem], questions: list[dict]) -> dict:
    """Hit rates are over questions with a non-empty must set only."""
    must_by_id = {q["id"]: q.get("must", []) for q in questions}
    scored = [item for item in items if must_by_id.get(item.id)]
    total = len(items)
    return {
        "total": total,
        "scored_for_hits": len(scored),
        "behavior_match_rate": (
            sum(1 for i in items if i.behavior_match) / total if total else 0.0
        ),
        "vector_hit_rate": (
            sum(1 for i in scored if i.vector_hit) / len(scored) if scored else None
        ),
        "selection_hit_rate": (
            sum(1 for i in scored if i.selection_hit) / len(scored) if scored else None
        ),
    }


def _print_table(items: list[EvalReportItem]) -> None:
    headers = (
        "id",
        "behavior",
        "match",
        "vector",
        "selection",
        "calls",
        "latency_s",
    )
    print("\t".join(headers))
    for item in items:
        print(
            "\t".join(
                [
                    item.id,
                    f"{item.expected_behavior}->{item.actual_action}",
                    str(item.behavior_match),
                    str(item.vector_hit),
                    str(item.selection_hit),
                    str(item.llm_call_count),
                    f"{item.latency_seconds:.2f}",
                ]
            )
        )


def _score_hits(
    *,
    retrieved,
    selection,
    must: list[str],
) -> tuple[bool, bool]:
    vector_ok = (
        bool(eval_metrics.vector_hit(retrieved, must))
        if retrieved is not None
        else False
    )
    # Missing SelectionEvent means an empty context (approved plan).
    sel_event = selection
    if sel_event is None:
        sel_event = SelectionEvent(kept=[], discarded=[], added=[], unavailable=[])
    selection_ok = bool(eval_metrics.selection_hit(sel_event, must))
    return vector_ok, selection_ok


async def _run_live(
    questions: list[dict],
    *,
    settings: Settings,
    verbose: bool,
    manifest_path: Path = DEFAULT_CORPUS_MANIFEST,
) -> EvalReport:
    pool = create_pool(settings.database_url)
    await pool.open()
    adapter = OpenRouterAdapter(settings)
    try:
        async with pool.connection() as conn:
            repository = Repository(conn)
            meta = await repository.read_index_meta()
            if meta is None:
                raise SystemExit(
                    "Index is empty (no index_meta row). Run `make ingest` first."
                )
            documents = _documents_from_manifest(manifest_path)
            snapshot = meta.corpus_snapshot
            items: list[EvalReportItem] = []
            for q in questions:
                started = time.perf_counter()
                msg = Message(role="user", content=q["question"])
                req = AskRequest(messages=[msg], situation=Situation())
                retrieved = None
                selection = None
                final = None
                async for ev in orch.run(
                    req,
                    settings=settings,
                    embedder=adapter,
                    llm=adapter,
                    repository=repository,
                    documents=documents,
                    snapshot=snapshot,
                ):
                    if verbose:
                        print(ev)
                    event_name = getattr(ev, "event", None)
                    if event_name == "retrieved":
                        retrieved = ev
                    elif event_name == "selection":
                        selection = ev
                    elif event_name == "final":
                        final = ev
                        break
                latency = time.perf_counter() - started
                must = q.get("must", [])
                vector_ok, selection_ok = _score_hits(
                    retrieved=retrieved,
                    selection=selection,
                    must=must,
                )
                items.append(
                    EvalReportItem(
                        id=q["id"],
                        expected_behavior=q["expected_behavior"],
                        actual_action=final.action if final else "error",
                        behavior_match=(
                            (q["expected_behavior"] == final.action) if final else False
                        ),
                        vector_hit=vector_ok,
                        selection_hit=selection_ok,
                        llm_call_count=final.usage.calls if final else 0,
                        prompt_tokens=final.usage.prompt_tokens if final else 0,
                        completion_tokens=(
                            final.usage.completion_tokens if final else 0
                        ),
                        reasoning_tokens=(final.usage.reasoning_tokens if final else 0),
                        latency_seconds=latency,
                    )
                )
            return EvalReport(
                generated_at=datetime.now(UTC),
                items=items,
                summary=_summarize(items, questions),
            )
    finally:
        await adapter.close()
        await pool.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the retrieval evaluation set.")
    parser.add_argument("--use-fakes", action="store_true")
    parser.add_argument("--question", type=str)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--reports-dir", default="eval/reports")
    parser.add_argument("--eval-file", default="eval/eval_questions.json")
    args = parser.parse_args(argv)

    questions = load_questions(Path(args.eval_file))
    if args.question:
        matched = [q for q in questions if q["id"] == args.question]
        if not matched:
            raise SystemExit(f"Unknown question id: {args.question}")
        questions = matched

    if args.use_fakes:
        report = run_use_fakes(questions)
    else:
        settings = Settings()
        if not settings.embedding_api_key or not settings.llm_api_key:
            raise SystemExit("Missing provider configuration for live eval")
        report = asyncio.run(
            _run_live(questions, settings=settings, verbose=args.verbose)
        )

    _print_table(report.items)
    outdir = Path(args.reports_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / f"{datetime.now(UTC).isoformat()}.json"
    out_path.write_text(report.model_dump_json(), encoding="utf-8")
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
