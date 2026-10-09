"""Unit coverage for eval CLI config checks and the --use-fakes path."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


def test_missing_config_raises(monkeypatch, tmp_path):
    eval_file = tmp_path / "eval.json"
    eval_file.write_text(json.dumps([]))

    class BadSettings:
        embedding_api_key = ""
        llm_api_key = ""

    from eval import run_eval as runner

    monkeypatch.setattr(runner, "Settings", BadSettings)

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
    from eval import run_eval as runner

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
