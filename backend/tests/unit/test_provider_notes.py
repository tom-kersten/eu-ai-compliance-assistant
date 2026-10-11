"""Unit tests for provider verification helpers (redaction, notes, call cap)."""

from __future__ import annotations

import pytest

from scripts.provider_notes import (
    MAX_HTTP_CALLS,
    CallBudget,
    CallBudgetExceeded,
    VerificationReport,
    redact,
    render_notes,
)


@pytest.mark.unit
def test_redact_replaces_authorization_and_key_substrings() -> None:
    secret = "sk-or-v1-supersecretvalue"
    payload = {
        "Authorization": f"Bearer {secret}",
        "api_key": secret,
        "nested": {"token": secret, "ok": True},
        "message": f"using {secret} in text",
        "keep": "plain",
    }

    result = redact(payload, secrets=[secret])

    assert result["Authorization"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["token"] == "[REDACTED]"
    assert result["nested"]["ok"] is True
    assert "[REDACTED]" in result["message"]
    assert secret not in result["message"]
    assert result["keep"] == "plain"


@pytest.mark.unit
def test_render_notes_covers_every_check() -> None:
    report = VerificationReport(
        max_http_calls=MAX_HTTP_CALLS,
        calls_used=12,
        embedding_model="qwen/qwen3-embedding-8b",
        llm_model="qwen/qwen3.8-27b",
        dimensions={
            "requested": 2000,
            "returned_with_param": 2000,
            "returned_without_param": 4096,
            "normalized_with_param": True,
            "normalized_without_param": True,
            "cosine_vs_truncated_native": 0.99,
            "honored": True,
            "fallback": None,
        },
        query_instruction={
            "format": "Instruct: {task}\\nQuery:{query}",
            "recommended_task": (
                "Given a Dutch question about EU AI, privacy, or cybersecurity "
                "law, retrieve the relevant statutory provision"
            ),
            "comparison": "legal instruction ranked the match above the distractor",
        },
        limits={
            "batch_sizes_ok": [1, 8, 32],
            "batch_sizes_failed": [100],
            "practical_batch_size": 32,
            "latency_ms": {"1": 120.0, "8": 200.0},
        },
        structured_output={
            "selection_successes": 10,
            "selection_attempts": 10,
            "answer_successes": 9,
            "answer_attempts": 10,
            "response_format": "json_schema",
        },
        reasoning={
            "parameter": {"reasoning": {"effort": "medium", "exclude": False}},
            "works_with_structured_output": True,
            "content_fields": ["message.reasoning"],
            "failure_modes": [],
        },
        usage={
            "prompt_tokens": "usage.prompt_tokens",
            "completion_tokens": "usage.completion_tokens",
            "reasoning_tokens": "usage.completion_tokens_details.reasoning_tokens",
        },
        routing={
            "embedding_providers": ["ProviderA"],
            "llm_providers": ["ProviderB"],
            "embedding_context_length": 32768,
            "llm_context_length": 1000000,
        },
        decisions=[
            "Send dimensions=2000 and verify length.",
            "Prefix queries with the recommended Instruct/Query format.",
        ],
    )

    notes = render_notes(report)

    assert "# Provider notes" in notes
    assert "## 1. Embeddings dimensions" in notes
    assert "## 2. Query instruction" in notes
    assert "## 3. Limits" in notes
    assert "## 4. Structured output" in notes
    assert "## 5. Reasoning" in notes
    assert "## 6. Usage fields" in notes
    assert "## 7. Routing" in notes
    assert "## Implementation decisions" in notes
    assert "T8" not in notes
    assert f"MAX_HTTP_CALLS = {MAX_HTTP_CALLS}" in notes
    assert "docs/OFFLINE.md" in notes


@pytest.mark.unit
def test_render_notes_records_dimensions_fallback() -> None:
    report = VerificationReport(
        max_http_calls=MAX_HTTP_CALLS,
        calls_used=2,
        embedding_model="qwen/qwen3-embedding-8b",
        llm_model="qwen/qwen3.8-27b",
        dimensions={
            "requested": 2000,
            "returned_with_param": 4096,
            "returned_without_param": 4096,
            "normalized_with_param": True,
            "normalized_without_param": True,
            "cosine_vs_truncated_native": 1.0,
            "honored": False,
            "fallback": "truncate to 2000 and re-normalize",
        },
        query_instruction={},
        limits={},
        structured_output={},
        reasoning={},
        usage={},
        routing={},
        decisions=[
            "dimensions not honored; truncate to 2000 and re-normalize",
        ],
    )

    notes = render_notes(report)

    assert "truncate to 2000 and re-normalize" in notes
    assert "not honored" in notes.lower() or "honored: false" in notes.lower()


@pytest.mark.unit
def test_call_budget_stops_before_cap() -> None:
    budget = CallBudget(max_calls=MAX_HTTP_CALLS)

    for _ in range(MAX_HTTP_CALLS):
        budget.acquire()

    assert budget.used == MAX_HTTP_CALLS

    with pytest.raises(CallBudgetExceeded):
        budget.acquire()

    assert budget.used == MAX_HTTP_CALLS
