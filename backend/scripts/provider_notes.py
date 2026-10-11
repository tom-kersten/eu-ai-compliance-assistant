"""Pure helpers for provider verification: redaction, call budget, notes rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_HTTP_CALLS = 60
REDACTED = "[REDACTED]"


class CallBudgetExceeded(RuntimeError):
    """Raised when the verification script would exceed its HTTP call cap."""


@dataclass
class CallBudget:
    max_calls: int = MAX_HTTP_CALLS
    used: int = 0

    def acquire(self) -> None:
        if self.used >= self.max_calls:
            raise CallBudgetExceeded(
                f"HTTP call budget exhausted ({self.used}/{self.max_calls})"
            )
        self.used += 1


def redact(value: Any, *, secrets: list[str]) -> Any:
    """Return a deep copy of value with secrets and Bearer tokens removed."""
    secret_set = {s for s in secrets if s}

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = key.lower()
            if key_lower in {"authorization", "api_key", "token", "x-api-key"}:
                out[key] = REDACTED
            else:
                out[key] = redact(item, secrets=list(secret_set))
        return out
    if isinstance(value, list):
        return [redact(item, secrets=list(secret_set)) for item in value]
    if isinstance(value, str):
        text = value
        if text.lower().startswith("bearer "):
            return REDACTED
        for secret in secret_set:
            if secret and secret in text:
                text = text.replace(secret, REDACTED)
        return text
    return value


@dataclass
class VerificationReport:
    max_http_calls: int
    calls_used: int
    embedding_model: str
    llm_model: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    query_instruction: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    structured_output: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    decisions: list[str] = field(default_factory=list)


def _yamlish(value: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}(none)"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}- {key}:")
                lines.extend(_yamlish(item, indent + 1))
            else:
                lines.append(f"{prefix}- {key}: {item}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}(none)"]
        return [f"{prefix}- {item}" for item in value]
    return [f"{prefix}{value}"]


def render_notes(report: VerificationReport) -> str:
    """Render PROVIDER_NOTES.md content from a verification report."""
    lines: list[str] = [
        "# Provider notes",
        "",
        "Verified request and response shapes for OpenRouter, recorded by",
        "`make verify-providers`. Keys are never written here.",
        "",
        "Self-hosted (vLLM) image pins, quantization, and context-length notes:",
        "`docs/OFFLINE.md`.",
        "",
        f"HTTP call cap for the verification script: `MAX_HTTP_CALLS = "
        f"{report.max_http_calls}` "
        f"(this run used {report.calls_used}).",
        "",
        f"- Embedding model: `{report.embedding_model}`",
        f"- LLM model: `{report.llm_model}`",
        "",
        "## 1. Embeddings dimensions",
        "",
    ]
    lines.extend(_yamlish(report.dimensions))
    if report.dimensions.get("honored") is False:
        fallback = report.dimensions.get("fallback") or (
            "truncate to 2000 and re-normalize"
        )
        lines.extend(
            [
                "",
                f"dimensions parameter was **not honored**. Fallback: {fallback}.",
            ]
        )
    elif report.dimensions.get("honored") is True:
        lines.extend(
            [
                "",
                "dimensions parameter was **honored**. Send `dimensions` from "
                "configuration and verify the returned length.",
            ]
        )

    lines.extend(["", "## 2. Query instruction", ""])
    lines.extend(_yamlish(report.query_instruction))

    lines.extend(["", "## 3. Limits", ""])
    lines.extend(_yamlish(report.limits))

    lines.extend(["", "## 4. Structured output", ""])
    lines.extend(_yamlish(report.structured_output))

    lines.extend(["", "## 5. Reasoning", ""])
    lines.extend(_yamlish(report.reasoning))
    lines.extend(
        [
            "",
            "The adapter must parse only `message.content`. Do not store or return "
            "reasoning text.",
        ]
    )

    lines.extend(["", "## 6. Usage fields", ""])
    lines.extend(_yamlish(report.usage))

    lines.extend(["", "## 7. Routing", ""])
    lines.extend(_yamlish(report.routing))

    lines.extend(["", "## Implementation decisions", ""])
    if report.decisions:
        lines.extend(f"- {item}" for item in report.decisions)
    else:
        lines.append("- (none recorded)")
    lines.append("")
    return "\n".join(lines)
