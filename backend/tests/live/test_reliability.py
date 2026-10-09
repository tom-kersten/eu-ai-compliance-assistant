"""Structured-output reliability against the configured providers.

Opt-in (`make test-live`). Hosted OpenRouter is required. Self-hosted vLLM
is recorded when the offline endpoint answers, and skipped when it does not.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from eval.reliability import (
    ANSWER_PROMPT,
    ANSWER_SCHEMA,
    SELECTION_PROMPT,
    SELECTION_SCHEMA,
    chat_request,
    message_content,
    parse_valid,
    suggest_max_retries,
)

from app.config import Settings
from app.schemas.llm import AnswerResult, SelectionResult

REPEATS = 10
REPORT_PATH = Path("/app/eval/reports/reliability.json")
SELF_HOSTED_URL = os.environ.get("SELF_HOSTED_LLM_BASE_URL", "http://vllm-llm:8000/v1")


def _attempt(
    client: httpx.Client,
    *,
    url: str,
    api_key: str,
    body: dict,
    model: type[SelectionResult] | type[AnswerResult],
) -> bool:
    response = client.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    if response.status_code != 200:
        return False
    payload = response.json()
    if not isinstance(payload, dict):
        return False
    return parse_valid(message_content(payload), model)


def _run_pair(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    selection_effort: str | None,
    answer_effort: str,
    timeout: float,
) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions"
    selection_body = chat_request(
        model=model_name,
        schema_name="selection_result",
        schema=SELECTION_SCHEMA,
        prompt=SELECTION_PROMPT,
        reasoning_effort=selection_effort,
    )
    answer_body = chat_request(
        model=model_name,
        schema_name="answer_result",
        schema=ANSWER_SCHEMA,
        prompt=ANSWER_PROMPT,
        reasoning_effort=answer_effort,
    )
    selection_valid = 0
    answer_valid = 0
    with httpx.Client(timeout=timeout) as client:
        for _ in range(REPEATS):
            if _attempt(
                client,
                url=url,
                api_key=api_key,
                body=selection_body,
                model=SelectionResult,
            ):
                selection_valid += 1
            if _attempt(
                client,
                url=url,
                api_key=api_key,
                body=answer_body,
                model=AnswerResult,
            ):
                answer_valid += 1
    worse_valid = min(selection_valid, answer_valid)
    return {
        "selection": {"valid": selection_valid, "attempts": REPEATS},
        "answer": {"valid": answer_valid, "attempts": REPEATS},
        "suggested_max_retries": suggest_max_retries(
            valid=worse_valid,
            attempts=REPEATS,
        ),
    }


def _self_hosted_reachable(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code < 500


@pytest.mark.live
def test_structured_output_reliability() -> None:
    settings = Settings(_env_file=None)
    if not settings.llm_api_key:
        pytest.skip("LLM_API_KEY is not set")
    hosted = _run_pair(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model_name=settings.selection_model,
        selection_effort=settings.selection_reasoning_effort,
        answer_effort=settings.answer_reasoning_effort,
        timeout=float(settings.llm_timeout_seconds),
    )
    report: dict = {
        "hosted": hosted,
        "selection_reasoning_effort": settings.selection_reasoning_effort,
        "answer_reasoning_effort": settings.answer_reasoning_effort,
        "model": settings.selection_model,
    }
    if _self_hosted_reachable(SELF_HOSTED_URL):
        report["self_hosted"] = _run_pair(
            base_url=SELF_HOSTED_URL,
            api_key=settings.llm_api_key or "local",
            model_name=settings.selection_model,
            selection_effort=settings.selection_reasoning_effort,
            answer_effort=settings.answer_reasoning_effort,
            timeout=float(settings.llm_timeout_seconds),
        )
    else:
        report["self_hosted"] = {"available": False}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert hosted["selection"]["attempts"] == REPEATS
    assert hosted["answer"]["attempts"] == REPEATS
    assert hosted["selection"]["valid"] > 0
    assert hosted["answer"]["valid"] > 0
