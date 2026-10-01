from __future__ import annotations

import json
from datetime import date

import pytest


def _make_event_classes():
    from app.schemas.api import (
        DisplayCitation,
        FinalEvent,
        RetrievedEvent,
        RetrievedItem,
        SelectionEvent,
        Usage,
    )

    def _retrieved(must):
        provisions = [RetrievedItem(ref=r, title=None, similarity=0.9) for r in must]
        return RetrievedEvent(provisions=provisions)

    def _selection(must):
        return SelectionEvent(kept=list(must), discarded=[], added=[], unavailable=[])

    def _final(must):
        usage = Usage(
            calls=1,
            prompt_tokens=10,
            completion_tokens=20,
            reasoning_tokens=0,
            prompt_versions={},
        )
        citations = [DisplayCitation(ref=r, header="", body="") for r in must]
        return FinalEvent(
            action="answer" if must else "cannot_answer",
            answer="faked" if must else "Kan geen antwoord geven.",
            clarifying_questions=[],
            citations=citations,
            situation={},
            usage=usage,
            corpus_snapshot=date.today(),
        )

    return _retrieved, _selection, _final


def test_live_path_runs_and_writes_report(tmp_path, monkeypatch):
    # prepare a small eval file
    eval_file = tmp_path / "eval.json"
    q = {"id": "Q01", "question": "?", "expected_behavior": "answer", "must": ["p1"]}
    eval_file.write_text(json.dumps([q]))

    # monkeypatch orchestrator.run to yield events
    _retrieved, _selection, _final = _make_event_classes()

    async def fake_run(req, **kwargs):
        yield _retrieved(q["must"])
        yield _selection(q["must"])
        yield _final(q["must"])

    # monkeypatch Settings to have keys
    class FakeSettings:
        embedding_api_key = "e"
        llm_api_key = "l"

    monkeypatch.setattr("app.pipeline.orchestrator.run", fake_run)
    monkeypatch.setattr("app.config.Settings", FakeSettings)

    # run the backend eval runner main
    from eval import run_eval as runner

    outdir = tmp_path / "reports"
    runner.main(["--reports-dir", str(outdir), "--eval-file", str(eval_file)])
    files = list(outdir.iterdir())
    assert files, "report file not written"
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert "items" in data
    assert data["items"][0]["llm_call_count"] == 1


def test_missing_config_raises(monkeypatch, tmp_path):
    # empty eval file
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps([]))

    class BadSettings:
        embedding_api_key = ""
        llm_api_key = ""

    monkeypatch.setattr("app.config.Settings", BadSettings)
    from eval import run_eval as runner

    with pytest.raises(SystemExit):
        runner.main(["--reports-dir", str(tmp_path), "--eval-file", str(eval_file)])


def test_use_fakes_path_unchanged(tmp_path):
    eval_file = tmp_path / "eval.json"
    q = {
        "id": "QFAKE",
        "question": "?",
        "expected_behavior": "cannot_answer",
        "must": [],
    }
    eval_file.write_text(json.dumps([q]))
    from backend.src.eval import run_eval as runner

    outdir = tmp_path / "reports"
    runner.main(
        [
            "--use-fakes",
            "--reports-dir",
            str(outdir),
            "--eval-file",
            str(eval_file),
        ]
    )
    files = list(outdir.iterdir())
    assert files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["items"][0]["actual_action"] in ("cannot_answer", "answer")
