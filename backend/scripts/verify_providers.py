"""Probe OpenRouter and write PROVIDER_NOTES.md plus redacted fixtures.

Reads keys from the environment. Never prints key values.
HTTP calls are capped by CallBudget (MAX_HTTP_CALLS).
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from scripts.provider_notes import (
    MAX_HTTP_CALLS,
    CallBudget,
    CallBudgetExceeded,
    VerificationReport,
    redact,
    render_notes,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "providers"
DEFAULT_NOTES_PATH = Path("/docs/PROVIDER_NOTES.md")

WEB_SEARCH_TASK = (
    "Given a web search query, retrieve relevant passages that answer the query"
)
LEGAL_TASK = (
    "Given a Dutch question about EU AI, privacy, or cybersecurity law, "
    "retrieve the relevant statutory provision"
)

DOC_PROVIDER = (
    "„aanbieder”: een natuurlijke of rechtspersoon, overheidsinstantie, "
    "agentschap of ander orgaan die/dat een AI-systeem of een AI-model voor "
    "algemene doeleinden ontwikkelt of laat ontwikkelen en dat systeem of "
    "model in de handel brengt of het AI-systeem in gebruik stelt onder de "
    "eigen naam of merk, al dan niet tegen betaling;"
)
DOC_RECRUITMENT = (
    "AI-systemen die bedoeld zijn om te worden gebruikt voor het werven of "
    "selecteren van natuurlijke personen, met name voor het plaatsen van "
    "gerichte vacatures, het analyseren en filteren van sollicitaties, en "
    "het beoordelen van kandidaten;"
)
DOC_CHATBOT = (
    "Aanbieders zorgen ervoor dat AI-systemen die voor directe interactie "
    "met natuurlijke personen zijn bedoeld, zodanig worden ontworpen en "
    "ontwikkeld dat de betrokken natuurlijke personen worden geïnformeerd "
    "dat zij interageren met een AI-systeem, tenzij dit duidelijk is vanuit "
    "het oogpunt van een normaal geïnformeerde en redelijk omzichtige en "
    "oplettende natuurlijke persoon."
)

QUERY_PROVIDER = (
    "Wat is het verschil tussen een aanbieder en een "
    "gebruiksverantwoordelijke volgens de AI-verordening?"
)
QUERY_RECRUITMENT = (
    "Is een AI-systeem dat sollicitaties filtert een AI-systeem met een hoog risico?"
)

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
                    "document": {
                        "type": "string",
                        "enum": ["AI-verordening", "AVG", "CRA", "Omnibus"],
                    },
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


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def _l2_norm(vector: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return float("nan")
    na = _l2_norm(a)
    nb = _l2_norm(b)
    if na == 0.0 or nb == 0.0:
        return float("nan")
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def _normalize(vector: list[float]) -> list[float]:
    n = _l2_norm(vector)
    if n == 0.0:
        return list(vector)
    return [x / n for x in vector]


def _format_query(task: str, query: str) -> str:
    return f"Instruct: {task}\nQuery:{query}"


def _matches_type(value: Any, schema_type: Any) -> bool:
    if isinstance(schema_type, list):
        return any(_matches_type(value, t) for t in schema_type)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "null":
        return value is None
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    return False


def _validate_schema(value: Any, schema: dict[str, Any]) -> bool:
    if "type" in schema and not _matches_type(value, schema["type"]):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if schema.get("type") == "object" or (
        isinstance(schema.get("type"), list) and "object" in schema["type"]
    ):
        if not isinstance(value, dict):
            return _matches_type(value, schema.get("type", "object"))
        required = schema.get("required", [])
        if any(key not in value for key in required):
            return False
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}))
            if any(key not in allowed for key in value):
                return False
        for key, child in schema.get("properties", {}).items():
            if key in value and not _validate_schema(value[key], child):
                return False
        return True
    if schema.get("type") == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        if item_schema is None:
            return True
        return all(_validate_schema(item, item_schema) for item in value)
    return True


def _content_valid(body: dict[str, Any], schema: dict[str, Any]) -> bool:
    try:
        choices = body.get("choices") or []
        if not choices:
            return False
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            return False
        parsed = json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError, KeyError, IndexError):
        return False
    return _validate_schema(parsed, schema)


def _usage_paths(body: dict[str, Any]) -> dict[str, str | None]:
    usage = body.get("usage") or {}
    paths: dict[str, str | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
    }
    if "prompt_tokens" in usage:
        paths["prompt_tokens"] = "usage.prompt_tokens"
    if "completion_tokens" in usage:
        paths["completion_tokens"] = "usage.completion_tokens"
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict) and "reasoning_tokens" in details:
        paths["reasoning_tokens"] = "usage.completion_tokens_details.reasoning_tokens"
    elif "reasoning_tokens" in usage:
        paths["reasoning_tokens"] = "usage.reasoning_tokens"
    return paths


def _reasoning_fields(body: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return fields
    if message.get("reasoning"):
        fields.append("message.reasoning")
    if message.get("reasoning_details"):
        fields.append("message.reasoning_details")
    return fields


class ProviderVerifier:
    def __init__(self) -> None:
        self.embedding_base = _require_env("EMBEDDING_BASE_URL").rstrip("/")
        self.llm_base = _require_env("LLM_BASE_URL").rstrip("/")
        self.embedding_key = _require_env("EMBEDDING_API_KEY")
        self.llm_key = _require_env("LLM_API_KEY")
        self.embedding_model = os.environ.get(
            "EMBEDDING_MODEL", "qwen/qwen3-embedding-8b"
        )
        self.llm_model = os.environ.get("SELECTION_MODEL", "qwen/qwen3.8-27b")
        self.dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "2000"))
        self.budget = CallBudget(max_calls=MAX_HTTP_CALLS)
        self.secrets = [self.embedding_key, self.llm_key]
        self.fixtures: dict[str, Any] = {}
        self.notes_path = Path(
            os.environ.get("PROVIDER_NOTES_PATH", str(DEFAULT_NOTES_PATH))
        )
        timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
        self.client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def _headers(self, key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        key: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | list[Any] | str, float]:
        self.budget.acquire()
        started = time.perf_counter()
        response = self.client.request(
            method,
            url,
            headers=self._headers(key),
            json=json_body,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            body: dict[str, Any] | list[Any] | str = response.json()
        except json.JSONDecodeError:
            body = response.text
        if response.status_code >= 400:
            redacted = redact(body, secrets=self.secrets)
            print(
                f"HTTP {response.status_code} for {method} {url}: "
                f"{json.dumps(redacted)[:500]}",
                file=sys.stderr,
            )
        return response.status_code, body, elapsed_ms

    def _save_fixture(self, name: str, body: Any) -> None:
        self.fixtures[name] = redact(body, secrets=self.secrets)

    def verify_routing(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "embedding_providers": [],
            "llm_providers": [],
            "embedding_context_length": None,
            "llm_context_length": None,
        }
        status, body, _ = self._request(
            "GET",
            f"{self.llm_base}/models",
            key=self.llm_key,
        )
        if status != 200 or not isinstance(body, dict):
            return result
        self._save_fixture("models_excerpt", {"data": (body.get("data") or [])[:5]})
        for item in body.get("data") or []:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            ctx = item.get("context_length") or item.get("top_provider", {}).get(
                "context_length"
            )
            if model_id == self.embedding_model:
                result["embedding_context_length"] = ctx
            if model_id == self.llm_model:
                result["llm_context_length"] = ctx

        for model, field in (
            (self.embedding_model, "embedding_providers"),
            (self.llm_model, "llm_providers"),
        ):
            status, body, _ = self._request(
                "GET",
                f"{self.llm_base}/models/{model}/endpoints",
                key=self.llm_key,
            )
            if status != 200 or not isinstance(body, dict):
                continue
            data = body.get("data") or {}
            endpoints = data.get("endpoints") or []
            providers = []
            for endpoint in endpoints:
                if isinstance(endpoint, dict):
                    name = endpoint.get("provider_name") or endpoint.get("name")
                    if name:
                        providers.append(name)
            result[field] = providers
        return result

    def verify_dimensions(self) -> dict[str, Any]:
        text = "Dimensietest: korte Nederlandse zin over AI-systemen."
        status_with, body_with, _ = self._request(
            "POST",
            f"{self.embedding_base}/embeddings",
            key=self.embedding_key,
            json_body={
                "model": self.embedding_model,
                "input": [text],
                "dimensions": self.dimensions,
            },
        )
        status_native, body_native, _ = self._request(
            "POST",
            f"{self.embedding_base}/embeddings",
            key=self.embedding_key,
            json_body={"model": self.embedding_model, "input": [text]},
        )

        vec_with: list[float] | None = None
        vec_native: list[float] | None = None
        if status_with == 200 and isinstance(body_with, dict):
            self._save_fixture("embeddings_dimensions", body_with)
            data = body_with.get("data") or []
            if data:
                vec_with = data[0].get("embedding")
        if status_native == 200 and isinstance(body_native, dict):
            self._save_fixture("embeddings_native", body_native)
            data = body_native.get("data") or []
            if data:
                vec_native = data[0].get("embedding")

        returned_with = len(vec_with) if vec_with else None
        returned_native = len(vec_native) if vec_native else None
        honored = returned_with == self.dimensions
        cosine = None
        if vec_with and vec_native and len(vec_native) >= self.dimensions:
            truncated = _normalize(vec_native[: self.dimensions])
            cosine = _cosine(_normalize(vec_with), truncated)

        fallback = None if honored else "truncate to 2000 and re-normalize"
        return {
            "requested": self.dimensions,
            "returned_with_param": returned_with,
            "returned_without_param": returned_native,
            "normalized_with_param": (
                abs(_l2_norm(vec_with) - 1.0) < 0.05 if vec_with else None
            ),
            "normalized_without_param": (
                abs(_l2_norm(vec_native) - 1.0) < 0.05 if vec_native else None
            ),
            "cosine_vs_truncated_native": (
                round(cosine, 6) if cosine is not None else None
            ),
            "honored": honored,
            "fallback": fallback,
            "status_with_param": status_with,
            "status_without_param": status_native,
        }

    def verify_query_instruction(self) -> dict[str, Any]:
        docs = [DOC_PROVIDER, DOC_RECRUITMENT, DOC_CHATBOT]
        status, body, _ = self._request(
            "POST",
            f"{self.embedding_base}/embeddings",
            key=self.embedding_key,
            json_body={
                "model": self.embedding_model,
                "input": docs,
                "dimensions": self.dimensions,
            },
        )
        if status != 200 or not isinstance(body, dict):
            return {"error": f"document embed failed with status {status}"}
        doc_vecs = [row["embedding"] for row in body["data"]]

        variants = {
            "bare": lambda q: q,
            "web_search": lambda q: _format_query(WEB_SEARCH_TASK, q),
            "legal": lambda q: _format_query(LEGAL_TASK, q),
        }
        pairs = [
            ("provider", QUERY_PROVIDER, 0),
            ("recruitment", QUERY_RECRUITMENT, 1),
        ]
        distractor_idx = 2
        comparison: dict[str, Any] = {}
        margins: dict[str, list[float]] = {name: [] for name in variants}

        for name, formatter in variants.items():
            inputs = [formatter(q) for _, q, _ in pairs]
            status, body, _ = self._request(
                "POST",
                f"{self.embedding_base}/embeddings",
                key=self.embedding_key,
                json_body={
                    "model": self.embedding_model,
                    "input": inputs,
                    "dimensions": self.dimensions,
                },
            )
            if status != 200 or not isinstance(body, dict):
                comparison[name] = {"error": status}
                continue
            for i, (pair_name, _, match_idx) in enumerate(pairs):
                qvec = body["data"][i]["embedding"]
                match = _cosine(qvec, doc_vecs[match_idx])
                distractor = _cosine(qvec, doc_vecs[distractor_idx])
                margin = match - distractor
                margins[name].append(margin)
                comparison[f"{name}_{pair_name}"] = {
                    "match_cosine": round(match, 6),
                    "distractor_cosine": round(distractor, 6),
                    "margin": round(margin, 6),
                }

        mean_margins = {
            name: (sum(vals) / len(vals) if vals else float("-inf"))
            for name, vals in margins.items()
        }
        best = max(mean_margins, key=mean_margins.get)
        recommended_task = None
        if best == "legal":
            recommended_task = LEGAL_TASK
        elif best == "web_search":
            recommended_task = WEB_SEARCH_TASK
        return {
            "format": "Instruct: {task}\\nQuery:{query}",
            "recommended_task": recommended_task
            or "(no instruction; bare query scored highest)",
            "recommended_variant": best,
            "mean_margins": {k: round(v, 6) for k, v in mean_margins.items()},
            "comparison": comparison,
        }

    def verify_limits(self) -> dict[str, Any]:
        sizes = [1, 8, 32, 100]
        ok: list[int] = []
        failed: list[int] = []
        latency: dict[str, float] = {}
        for size in sizes:
            inputs = [f"batch item {i}" for i in range(size)]
            status, _, elapsed = self._request(
                "POST",
                f"{self.embedding_base}/embeddings",
                key=self.embedding_key,
                json_body={
                    "model": self.embedding_model,
                    "input": inputs,
                    "dimensions": self.dimensions,
                },
            )
            latency[str(size)] = round(elapsed, 1)
            if status == 200:
                ok.append(size)
            else:
                failed.append(size)
                if size == 100:
                    status64, _, elapsed64 = self._request(
                        "POST",
                        f"{self.embedding_base}/embeddings",
                        key=self.embedding_key,
                        json_body={
                            "model": self.embedding_model,
                            "input": [f"batch item {i}" for i in range(64)],
                            "dimensions": self.dimensions,
                        },
                    )
                    latency["64"] = round(elapsed64, 1)
                    if status64 == 200:
                        ok.append(64)
                    else:
                        failed.append(64)
                break
        practical = max(ok) if ok else None
        return {
            "batch_sizes_ok": ok,
            "batch_sizes_failed": failed,
            "practical_batch_size": practical,
            "latency_ms": latency,
        }

    def _chat(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        prompt: str,
        reasoning: dict[str, Any] | None = None,
        reasoning_effort: str | None = None,
        max_tokens: int = 4096,
    ) -> tuple[int, dict[str, Any] | list[Any] | str, float]:
        body: dict[str, Any] = {
            "model": self.llm_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Reply with JSON that matches the schema exactly.",
                },
                {"role": "user", "content": prompt},
            ],
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
        if reasoning is not None:
            body["reasoning"] = reasoning
        if reasoning_effort is not None:
            body["reasoning_effort"] = reasoning_effort
        return self._request(
            "POST",
            f"{self.llm_base}/chat/completions",
            key=self.llm_key,
            json_body=body,
        )

    def verify_structured_and_reasoning(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        selection_ok = 0
        answer_ok = 0
        selection_attempts = 10
        answer_attempts = 10
        usage_sample: dict[str, str | None] = {
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
        }
        providers_seen: list[str] = []

        for i in range(selection_attempts):
            status, body, _ = self._chat(
                schema_name="selection_result",
                schema=SELECTION_SCHEMA,
                prompt=SELECTION_PROMPT,
            )
            if status == 200 and isinstance(body, dict):
                if i == 0:
                    self._save_fixture("chat_selection_schema", body)
                    usage_sample = _usage_paths(body)
                if body.get("provider"):
                    providers_seen.append(str(body["provider"]))
                if _content_valid(body, SELECTION_SCHEMA):
                    selection_ok += 1

        for i in range(answer_attempts):
            status, body, _ = self._chat(
                schema_name="answer_result",
                schema=ANSWER_SCHEMA,
                prompt=ANSWER_PROMPT,
            )
            if status == 200 and isinstance(body, dict):
                if i == 0:
                    self._save_fixture("chat_answer_schema", body)
                    for key, path in _usage_paths(body).items():
                        if path and not usage_sample.get(key):
                            usage_sample[key] = path
                if body.get("provider"):
                    providers_seen.append(str(body["provider"]))
                if _content_valid(body, ANSWER_SCHEMA):
                    answer_ok += 1

        structured = {
            "selection_successes": selection_ok,
            "selection_attempts": selection_attempts,
            "answer_successes": answer_ok,
            "answer_attempts": answer_attempts,
            "response_format": "json_schema",
            "providers_seen": sorted(set(providers_seen)),
        }

        reasoning_param: dict[str, Any] | None = {
            "effort": "medium",
            "exclude": False,
        }
        reasoning_effort_fallback: str | None = None
        failure_modes: list[str] = []
        content_fields: list[str] = []
        works = False

        status, body, _ = self._chat(
            schema_name="selection_result",
            schema=SELECTION_SCHEMA,
            prompt=SELECTION_PROMPT,
            reasoning=reasoning_param,
        )
        if status >= 400:
            failure_modes.append(
                f"reasoning object rejected with HTTP {status}; trying reasoning_effort"
            )
            reasoning_param = None
            reasoning_effort_fallback = "medium"
            status, body, _ = self._chat(
                schema_name="selection_result",
                schema=SELECTION_SCHEMA,
                prompt=SELECTION_PROMPT,
                reasoning_effort=reasoning_effort_fallback,
            )
            if status >= 400:
                failure_modes.append(
                    f"reasoning_effort also rejected with HTTP {status}"
                )

        sel_reason_ok = 0
        ans_reason_ok = 0
        if status < 400 and isinstance(body, dict):
            self._save_fixture("chat_selection_reasoning_medium", body)
            content_fields = _reasoning_fields(body)
            for key, path in _usage_paths(body).items():
                if path:
                    usage_sample[key] = path
            if _content_valid(body, SELECTION_SCHEMA):
                sel_reason_ok += 1
                works = True
            finish = (body.get("choices") or [{}])[0].get("finish_reason")
            if finish == "length":
                failure_modes.append("finish_reason=length with reasoning enabled")

            for _ in range(9):
                st, bd, _ = self._chat(
                    schema_name="selection_result",
                    schema=SELECTION_SCHEMA,
                    prompt=SELECTION_PROMPT,
                    reasoning=reasoning_param,
                    reasoning_effort=reasoning_effort_fallback,
                )
                if (
                    st == 200
                    and isinstance(bd, dict)
                    and _content_valid(bd, SELECTION_SCHEMA)
                ):
                    sel_reason_ok += 1

            for i in range(10):
                st, bd, _ = self._chat(
                    schema_name="answer_result",
                    schema=ANSWER_SCHEMA,
                    prompt=ANSWER_PROMPT,
                    reasoning=reasoning_param,
                    reasoning_effort=reasoning_effort_fallback,
                )
                if st == 200 and isinstance(bd, dict):
                    if i == 0:
                        content_fields = sorted(
                            set(content_fields + _reasoning_fields(bd))
                        )
                        for key, path in _usage_paths(bd).items():
                            if path:
                                usage_sample[key] = path
                    if _content_valid(bd, ANSWER_SCHEMA):
                        ans_reason_ok += 1
                        works = True

        parameter: dict[str, Any]
        if reasoning_param is not None:
            parameter = {"reasoning": reasoning_param}
        elif reasoning_effort_fallback is not None:
            parameter = {"reasoning_effort": reasoning_effort_fallback}
        else:
            parameter = {}

        reasoning = {
            "parameter": parameter,
            "works_with_structured_output": works,
            "content_fields": content_fields,
            "selection_successes_with_reasoning": sel_reason_ok,
            "selection_attempts_with_reasoning": 10 if status < 400 else 0,
            "answer_successes_with_reasoning": ans_reason_ok,
            "answer_attempts_with_reasoning": 10 if status < 400 else 0,
            "failure_modes": failure_modes,
        }
        return structured, reasoning, usage_sample

    def build_decisions(
        self,
        *,
        dimensions: dict[str, Any],
        query_instruction: dict[str, Any],
        limits: dict[str, Any],
        structured: dict[str, Any],
        reasoning: dict[str, Any],
        usage: dict[str, Any],
    ) -> list[str]:
        decisions: list[str] = []
        decisions.append(
            "Embeddings request shape: `dimensions` is a top-level field on the "
            "request body, never nested under a `parameters` object. `input` "
            "must always be a JSON array, even for a single text - a bare "
            "string is rejected with HTTP 400 (OpenRouter error code 20015)."
        )
        if dimensions.get("honored"):
            decisions.append(
                f"Send dimensions={self.dimensions} on every embeddings request "
                "and raise if the returned length differs."
            )
        else:
            decisions.append(
                "dimensions is not honored by the provider; request the native "
                "vector, truncate to 2000, and re-normalize before storage."
            )

        task = query_instruction.get("recommended_task")
        if task and not str(task).startswith("("):
            decisions.append(
                "embed_query must prefix with "
                f"`Instruct: {task}\\nQuery:` + the user query. "
                "embed_documents must send the raw text."
            )
        else:
            decisions.append(
                "Query instruction did not improve separation on the probe set; "
                "still apply the model-card Instruct/Query format with the legal "
                f"task wording for consistency: `{LEGAL_TASK}`."
            )

        batch = limits.get("practical_batch_size")
        decisions.append(
            f"Use embedding batch size {batch} "
            f"(largest successful probe; failed={limits.get('batch_sizes_failed')})."
        )
        decisions.append(
            "Request structured output with response_format type=json_schema, "
            "strict=true, additionalProperties=false, schemas shaped like "
            "SelectionResult and AnswerResult."
        )
        decisions.append(
            f"Reasoning parameter for OpenRouter: {reasoning.get('parameter')}. "
            f"Works with structured output: "
            f"{reasoning.get('works_with_structured_output')}."
        )
        decisions.append(
            "Parse only message.content. Discard reasoning / reasoning_details. "
            f"Observed reasoning fields: {reasoning.get('content_fields')}."
        )
        decisions.append(
            "Usage paths: "
            f"prompt={usage.get('prompt_tokens')}, "
            f"completion={usage.get('completion_tokens')}, "
            f"reasoning={usage.get('reasoning_tokens')}."
        )
        decisions.append(
            "Structured-output success rates (no reasoning): "
            f"selection {structured.get('selection_successes')}/"
            f"{structured.get('selection_attempts')}, "
            f"answer {structured.get('answer_successes')}/"
            f"{structured.get('answer_attempts')}."
        )
        return decisions

    def write_outputs(self, report: VerificationReport) -> None:
        notes = render_notes(report)
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        self.notes_path.write_text(notes, encoding="utf-8")
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        for name, body in self.fixtures.items():
            path = FIXTURES_DIR / f"{name}.json"
            path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        print(f"Wrote {self.notes_path}")
        print(f"Wrote {len(self.fixtures)} fixtures under {FIXTURES_DIR}")
        print(f"HTTP calls used: {self.budget.used}/{self.budget.max_calls}")

    def run(self) -> int:
        print("Using EMBEDDING_API_KEY for embeddings and LLM_API_KEY for chat.")
        print(f"Call budget: {MAX_HTTP_CALLS}")
        try:
            routing = self.verify_routing()
            dimensions = self.verify_dimensions()
            query_instruction = self.verify_query_instruction()
            limits = self.verify_limits()
            structured, reasoning, usage = self.verify_structured_and_reasoning()
            if structured.get("providers_seen"):
                routing["llm_providers"] = sorted(
                    set(routing.get("llm_providers") or [])
                    | set(structured["providers_seen"])
                )
            decisions = self.build_decisions(
                dimensions=dimensions,
                query_instruction=query_instruction,
                limits=limits,
                structured=structured,
                reasoning=reasoning,
                usage=usage,
            )
            report = VerificationReport(
                max_http_calls=MAX_HTTP_CALLS,
                calls_used=self.budget.used,
                embedding_model=self.embedding_model,
                llm_model=self.llm_model,
                dimensions=dimensions,
                query_instruction=query_instruction,
                limits=limits,
                structured_output=structured,
                reasoning=reasoning,
                usage=usage,
                routing=routing,
                decisions=decisions,
            )
            self.write_outputs(report)
            return 0
        except CallBudgetExceeded as exc:
            print(str(exc), file=sys.stderr)
            return 1
        finally:
            self.close()


def main() -> None:
    raise SystemExit(ProviderVerifier().run())


if __name__ == "__main__":
    main()
