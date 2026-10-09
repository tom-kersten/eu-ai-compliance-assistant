"""Parse-valid scoring for structured LLM output.

The live suite calls the provider. These helpers only judge a response.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError


def message_content(body: dict[str, Any]) -> str | None:
    """Final assistant content. Reasoning fields are ignored."""
    choices = body.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if content is None:
        return None
    return str(content)


def parse_valid(content: str | None, model: type[BaseModel]) -> bool:
    """True when content is JSON that validates as `model`."""
    if content is None or not content.strip():
        return False
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    try:
        model.model_validate(payload)
    except ValidationError:
        return False
    return True


SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "keep": {"type": "array", "items": {"type": "string"}},
        "discard": {"type": "array", "items": {"type": "string"}},
        "request": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "document": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["article", "annex", "recital"],
                    },
                    "label": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["document", "kind", "label", "reason"],
            },
        },
        "external_references": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "citation": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["citation", "reason"],
            },
        },
    },
    "required": ["keep", "discard", "request", "external_references"],
}

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reasoning": {"type": "string"},
        "action": {
            "type": "string",
            "enum": ["answer", "clarify", "cannot_answer"],
        },
        "answer": {"type": ["string", "null"]},
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array", "items": {"type": "string"}},
        "situation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "role": {
                    "type": "string",
                    "enum": [
                        "provider",
                        "deployer",
                        "importer",
                        "distributor",
                        "unknown",
                    ],
                },
                "domain": {"type": ["string", "null"]},
                "notes": {"type": ["string", "null"]},
            },
            "required": ["role", "domain", "notes"],
        },
    },
    "required": [
        "reasoning",
        "action",
        "answer",
        "clarifying_questions",
        "citations",
        "situation",
    ],
}

SELECTION_PROMPT = (
    "Return JSON only. keep=['AI-verordening:art_3'], "
    "discard=['AI-verordening:art_50'], request=[], external_references=[]."
)
ANSWER_PROMPT = (
    "Return JSON only. action='answer', answer='Een aanbieder brengt een "
    "AI-systeem in de handel.', clarifying_questions=[], "
    "citations=['AI-verordening:art_3'], situation role='unknown', "
    "domain=null, notes=null, and a short reasoning string first."
)


def chat_request(
    *,
    model: str,
    schema_name: str,
    schema: dict[str, Any],
    prompt: str | None = None,
    messages: list[dict[str, str]] | None = None,
    reasoning_effort: str | None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """OpenRouter chat body verified in PROVIDER_NOTES.

    `reasoning_effort` of None or \"none\" omits the reasoning parameter.
    """
    if messages is None:
        if prompt is None:
            raise ValueError("prompt or messages is required")
        messages = [
            {
                "role": "system",
                "content": "Reply with JSON that matches the schema exactly.",
            },
            {"role": "user", "content": prompt},
        ]
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        },
        "max_tokens": max_tokens,
    }
    if reasoning_effort and reasoning_effort != "none":
        body["reasoning"] = {"effort": reasoning_effort, "exclude": False}
    return body


def suggest_max_retries(*, valid: int, attempts: int) -> int:
    """Retry budget from the worse observed parse-valid rate.

    A fully valid sample keeps a single retry for a rare future failure.
    Lower rates get a larger budget. The bound stays small: the pipeline
    still stops after this many retries and emits an error.
    """
    if attempts <= 0 or valid < 0 or valid > attempts:
        raise ValueError("valid count must fall inside the attempt count")
    rate = valid / attempts
    if rate >= 0.99:
        return 1
    if rate >= 0.9:
        return 2
    return 3
