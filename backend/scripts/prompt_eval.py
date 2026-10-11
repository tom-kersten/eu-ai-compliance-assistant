"""Run the eval set with the current selection and answer prompts.

Embeds the corpus once (without the status line), retrieves with
the committed threshold and top_k, then calls the real select / resolve /
answer steps against OpenRouter chat/completions. Writes a JSON report.
Never prints API keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.errors import AnswerInvalid, SelectionInvalid
from app.ingestion.chunker import chunk_indexed
from app.ingestion.manifest import load_indexed_provisions, load_manifest
from app.pipeline.answer import answer
from app.pipeline.prompts.answer import ANSWER_PROMPT_VERSION
from app.pipeline.prompts.selection import (
    SELECTION_PROMPT_VERSION,
    build_selection_prompt,
)
from app.pipeline.resolve import resolve
from app.pipeline.select import select, validate_selection
from app.schemas.domain import Provision
from app.schemas.llm import AnswerResult, Message, SelectionResult, Situation
from eval.metrics import score_question
from eval.reliability import (
    ANSWER_SCHEMA,
    SELECTION_SCHEMA,
    chat_request,
    message_content,
)
from eval.tuning import embedding_text, rank_similarities, retrieved_refs

QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery:"
)
CANNOT_ANSWER = "Kan geen antwoord geven."


class MemoryLookup:
    """In-memory provision lookup for resolve()."""

    def __init__(self, provisions: list[Provision]) -> None:
        self._by_parent: dict[str, list[Provision]] = {}
        self._by_ref = {provision.ref: provision for provision in provisions}
        for provision in provisions:
            self._by_parent.setdefault(provision.parent_ref, []).append(provision)

    async def get_by_parent_ref(self, parent_ref: str) -> list[Provision]:
        return list(self._by_parent.get(parent_ref, []))

    async def get_by_refs(self, refs: list[str]) -> list[Provision]:
        return [self._by_ref[ref] for ref in refs if ref in self._by_ref]


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


def _embed_batch(
    client: httpx.Client,
    *,
    url: str,
    key: str,
    model: str,
    dimensions: int,
    texts: list[str],
) -> list[list[float]]:
    response = None
    last_status = 0
    last_body = ""
    for attempt in range(3):
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": texts, "dimensions": dimensions},
        )
        if response.status_code == 200:
            break
        last_status = response.status_code
        last_body = response.text[:300]
        if response.status_code not in {400, 429, 500, 502, 503}:
            break
        time.sleep(1.0 * (attempt + 1))
    if response is None or response.status_code != 200:
        raise SystemExit(f"embeddings failed with HTTP {last_status}: {last_body}")
    data = response.json().get("data") or []
    data.sort(key=lambda item: item.get("index", 0))
    vectors = [item["embedding"] for item in data]
    if len(vectors) != len(texts):
        raise SystemExit("embeddings response length does not match the batch")
    for vector in vectors:
        if len(vector) != dimensions:
            raise SystemExit(
                f"embedding dimension {len(vector)} != configured {dimensions}"
            )
    return vectors


def _embed_all(
    client: httpx.Client,
    *,
    url: str,
    key: str,
    model: str,
    dimensions: int,
    texts: list[str],
    batch_size: int,
) -> list[list[float]]:
    unique = list(dict.fromkeys(texts))
    vectors: list[list[float]] = []
    for start in range(0, len(unique), batch_size):
        batch = unique[start : start + batch_size]
        print(
            f"embedding {start + len(batch)}/{len(unique)}",
            file=sys.stderr,
        )
        vectors.extend(
            _embed_batch(
                client,
                url=url,
                key=key,
                model=model,
                dimensions=dimensions,
                texts=batch,
            )
        )
    by_text = dict(zip(unique, vectors, strict=True))
    return [by_text[text] for text in texts]


class ChatCompletionsLLM:
    """LLM Protocol adapter using the verified OpenRouter chat/completions path.

    Returns a dict that validates as the requested schema, with an optional
    ``usage`` key for token accounting (stripped by callers that forbid extras).
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        key: str,
        selection_model: str,
        answer_model: str,
    ) -> None:
        self._client = client
        self._url = url
        self._key = key
        self._selection_model = selection_model
        self._answer_model = answer_model
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0

    async def respond(
        self,
        *,
        prompt: str | None = None,
        messages: list[dict] | None = None,
        schema: type[BaseModel] | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        if schema is SelectionResult:
            model = self._selection_model
            schema_name = "selection_result"
            schema_dict = SELECTION_SCHEMA
        elif schema is AnswerResult:
            model = self._answer_model
            schema_name = "answer_result"
            schema_dict = ANSWER_SCHEMA
        else:
            raise ValueError(f"unsupported schema: {schema}")

        clean_messages: list[dict[str, str]]
        if messages is not None:
            clean_messages = [
                {"role": m["role"], "content": m["content"]} for m in messages
            ]
        elif prompt is not None:
            clean_messages = [{"role": "user", "content": prompt}]
        else:
            raise ValueError("messages or prompt is required")

        body = chat_request(
            model=model,
            schema_name=schema_name,
            schema=schema_dict,
            messages=clean_messages,
            reasoning_effort=reasoning_effort,
            max_tokens=8192,
        )
        self.calls += 1
        response = await self._client.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        response.raise_for_status()
        payload = response.json()
        content = message_content(payload)
        if content is None:
            raise ValueError("empty LLM content")
        parsed = json.loads(content)
        usage = payload.get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        details = usage.get("completion_tokens_details") or {}
        self.reasoning_tokens += int(details.get("reasoning_tokens", 0) or 0)
        # Return schema payload only; callers validate with extra="forbid".
        return parsed


async def _run_question(
    *,
    question: dict,
    ranked: list[tuple[str, float]],
    by_ref: dict[str, Provision],
    lookup: MemoryLookup,
    documents: list[dict[str, str]],
    document_keys: list[str],
    snapshot: Any,
    top_k: int,
    threshold: float,
    max_added: int,
    selection_effort: str | None,
    answer_effort: str | None,
    llm: ChatCompletionsLLM,
) -> dict[str, Any]:
    refs = retrieved_refs(ranked, top_k=top_k, threshold=threshold)
    retrieved = [by_ref[ref] for ref in refs if ref in by_ref]
    must = list(question.get("must") or [])
    expected = question["expected_behavior"]

    if not retrieved:
        scores = score_question(
            must_refs=must,
            expected_behavior=expected,
            retrieved_refs=[],
            final_refs=[],
            action="cannot_answer",
            llm_call_count=0,
        )
        return {
            "id": question["id"],
            "expected_behavior": expected,
            "action": "cannot_answer",
            "answer": CANNOT_ANSWER,
            "clarifying_questions": [],
            "citations": [],
            "retrieved_refs": [],
            "kept": [],
            "added": [],
            "final_refs": [],
            "unavailable": [],
            "prompt_versions": {},
            **scores,
        }

    conversation = [Message(role="user", content=question["question"])]
    situation = Situation()
    retrieved_dicts = [
        {"ref": p.ref, "header": p.header, "body": p.body} for p in retrieved
    ]
    sel_msgs = build_selection_prompt(
        conversation,
        situation,
        retrieved_dicts,
        documents,
        snapshot,
        max_added=max_added,
    )

    selection_result: SelectionResult | None = None
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            selection_result = await select(
                llm, sel_msgs, reasoning_effort=selection_effort
            )
            validate_selection(selection_result, [p.ref for p in retrieved])
            break
        except (SelectionInvalid, ValidationError, ValueError, httpx.HTTPError) as exc:
            last_error = exc
            selection_result = None
            continue
    if selection_result is None:
        scores = score_question(
            must_refs=must,
            expected_behavior=expected,
            retrieved_refs=refs,
            final_refs=[],
            action="error",
            llm_call_count=llm.calls,
        )
        return {
            "id": question["id"],
            "expected_behavior": expected,
            "action": "error",
            "error": f"selection failed: {last_error!r}",
            "answer": None,
            "clarifying_questions": [],
            "citations": [],
            "retrieved_refs": refs,
            "kept": [],
            "added": [],
            "final_refs": [],
            "unavailable": [],
            "prompt_versions": {"selection": SELECTION_PROMPT_VERSION},
            **scores,
        }

    resolved = await resolve(
        selection_result.request,
        selection_result.external_references,
        kept=selection_result.keep,
        document_keys=document_keys,
        lookup=lookup,
        max_added=max_added,
    )
    final_rows = [by_ref[ref] for ref in selection_result.keep if ref in by_ref] + list(
        resolved.added
    )
    final_dicts = [
        {"ref": p.ref, "header": p.header, "body": p.body} for p in final_rows
    ]
    unavailable = [
        {"citation": u.citation, "reason": u.reason, "detail": u.detail}
        for u in resolved.unavailable
    ]
    final_refs = [p.ref for p in final_rows]

    if not final_refs:
        scores = score_question(
            must_refs=must,
            expected_behavior=expected,
            retrieved_refs=refs,
            final_refs=[],
            action="cannot_answer",
            llm_call_count=llm.calls,
        )
        return {
            "id": question["id"],
            "expected_behavior": expected,
            "action": "cannot_answer",
            "answer": CANNOT_ANSWER,
            "clarifying_questions": [],
            "citations": [],
            "retrieved_refs": refs,
            "kept": selection_result.keep,
            "added": [],
            "final_refs": [],
            "unavailable": [u["citation"] for u in unavailable],
            "prompt_versions": {"selection": SELECTION_PROMPT_VERSION},
            **scores,
        }

    answer_result: AnswerResult | None = None
    last_error = None
    calls_before_answer = llm.calls
    for _attempt in range(2):
        try:
            answer_result = await answer(
                llm,
                conversation,
                situation,
                final_dicts,
                unavailable,
                documents,
                snapshot,
                reasoning_effort=answer_effort,
            )
            break
        except (AnswerInvalid, ValidationError, ValueError, httpx.HTTPError) as exc:
            last_error = exc
            answer_result = None
            # do not count failed parse toward a stuck loop forever
            continue
    if answer_result is None:
        scores = score_question(
            must_refs=must,
            expected_behavior=expected,
            retrieved_refs=refs,
            final_refs=final_refs,
            action="error",
            llm_call_count=llm.calls,
        )
        return {
            "id": question["id"],
            "expected_behavior": expected,
            "action": "error",
            "error": f"answer failed: {last_error!r}",
            "answer": None,
            "clarifying_questions": [],
            "citations": [],
            "retrieved_refs": refs,
            "kept": selection_result.keep,
            "added": [p.ref for p in resolved.added],
            "final_refs": final_refs,
            "unavailable": [u["citation"] for u in unavailable],
            "prompt_versions": {
                "selection": SELECTION_PROMPT_VERSION,
                "answer": ANSWER_PROMPT_VERSION,
            },
            **scores,
        }

    scores = score_question(
        must_refs=must,
        expected_behavior=expected,
        retrieved_refs=refs,
        final_refs=final_refs,
        action=answer_result.action,
        llm_call_count=llm.calls,
    )
    return {
        "id": question["id"],
        "expected_behavior": expected,
        "action": answer_result.action,
        "answer": answer_result.answer,
        "clarifying_questions": answer_result.clarifying_questions,
        "citations": answer_result.citations,
        "reasoning": answer_result.reasoning,
        "situation": answer_result.situation.model_dump(),
        "retrieved_refs": refs,
        "kept": selection_result.keep,
        "added": [p.ref for p in resolved.added],
        "final_refs": final_refs,
        "unavailable": [u["citation"] for u in unavailable],
        "prompt_versions": {
            "selection": SELECTION_PROMPT_VERSION,
            "answer": ANSWER_PROMPT_VERSION,
        },
        "answer_attempts": llm.calls - calls_before_answer,
        **scores,
    }


async def _async_main(args: argparse.Namespace) -> dict[str, Any]:
    embedding_key = _require("EMBEDDING_API_KEY")
    llm_key = _require("LLM_API_KEY")
    embedding_base = os.environ.get(
        "EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1"
    ).rstrip("/")
    llm_base = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip(
        "/"
    )
    embedding_model = os.environ.get("EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
    selection_model = os.environ.get("SELECTION_MODEL", "qwen/qwen3.8-27b")
    answer_model = os.environ.get("ANSWER_MODEL", "qwen/qwen3.8-27b")
    dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "2000"))
    batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE", "100"))
    timeout_seconds = float(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))
    # Bound connect separately so a hung provider cannot stall past the read budget.
    http_timeout = httpx.Timeout(
        connect=30.0,
        read=timeout_seconds,
        write=30.0,
        pool=30.0,
    )
    top_k = int(os.environ.get("RETRIEVAL_TOP_K", "10"))
    threshold = float(os.environ.get("SIMILARITY_THRESHOLD", "0.5959"))
    max_added = int(os.environ.get("MAX_ADDED_PROVISIONS", "1"))
    selection_effort = os.environ.get("SELECTION_REASONING_EFFORT", "low")
    answer_effort = os.environ.get("ANSWER_REASONING_EFFORT", "medium")
    if selection_effort in {"", "none"}:
        selection_effort_opt: str | None = None
    else:
        selection_effort_opt = selection_effort

    manifest = load_manifest(Path(args.corpus))
    corpus_root = Path(args.corpus).parent
    indexed = load_indexed_provisions(manifest, corpus_root)
    documents_by_key = {doc.key: doc for doc in manifest.documents}
    provisions = chunk_indexed(indexed, documents_by_key, token_limit=30000)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.question:
        questions = [q for q in questions if q["id"] == args.question]
        if not questions:
            raise SystemExit(f"unknown question id: {args.question}")

    texts = [
        embedding_text(provision.header, provision.body, include_status=False)
        for provision in provisions
    ]
    query_texts = [QUERY_PREFIX + question["question"] for question in questions]

    with httpx.Client(timeout=http_timeout) as client:
        embedded = _embed_all(
            client,
            url=f"{embedding_base}/embeddings",
            key=embedding_key,
            model=embedding_model,
            dimensions=dimensions,
            texts=texts + query_texts,
            batch_size=batch_size,
        )
    provision_vectors = dict(
        zip([p.ref for p in provisions], embedded[: len(provisions)], strict=True)
    )
    query_vectors = {
        question["id"]: vector
        for question, vector in zip(questions, embedded[len(provisions) :], strict=True)
    }
    ranked = {
        question["id"]: rank_similarities(
            query_vectors[question["id"]], provision_vectors
        )
        for question in questions
    }

    documents = [
        {
            "key": doc.key,
            "short_name": doc.short_name,
            "identifier": doc.identifier,
        }
        for doc in manifest.documents
    ]
    document_keys = [d["key"] for d in documents]
    by_ref = {p.ref: p for p in provisions}
    lookup = MemoryLookup(provisions)

    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=http_timeout) as async_client:
        for question in questions:
            llm = ChatCompletionsLLM(
                async_client,
                url=f"{llm_base}/chat/completions",
                key=llm_key,
                selection_model=selection_model,
                answer_model=answer_model,
            )
            started = time.perf_counter()
            print(f"running {question['id']}", file=sys.stderr, flush=True)
            try:
                item = await _run_question(
                    question=question,
                    ranked=ranked[question["id"]],
                    by_ref=by_ref,
                    lookup=lookup,
                    documents=documents,
                    document_keys=document_keys,
                    snapshot=manifest.snapshot,
                    top_k=top_k,
                    threshold=threshold,
                    max_added=max_added,
                    selection_effort=selection_effort_opt,
                    answer_effort=answer_effort,
                    llm=llm,
                )
            except httpx.TimeoutException as exc:
                must = list(question.get("must") or [])
                refs = retrieved_refs(
                    ranked[question["id"]], top_k=top_k, threshold=threshold
                )
                scores = score_question(
                    must_refs=must,
                    expected_behavior=question["expected_behavior"],
                    retrieved_refs=refs,
                    final_refs=[],
                    action="error",
                    llm_call_count=llm.calls,
                )
                item = {
                    "id": question["id"],
                    "expected_behavior": question["expected_behavior"],
                    "action": "error",
                    "error": f"timeout: {exc!r}",
                    "answer": None,
                    "clarifying_questions": [],
                    "citations": [],
                    "retrieved_refs": refs,
                    "kept": [],
                    "added": [],
                    "final_refs": [],
                    "unavailable": [],
                    "prompt_versions": {
                        "selection": SELECTION_PROMPT_VERSION,
                        "answer": ANSWER_PROMPT_VERSION,
                    },
                    **scores,
                }
                print(
                    f"{question['id']} timed out after {timeout_seconds}s",
                    file=sys.stderr,
                    flush=True,
                )
            item["latency_seconds"] = round(time.perf_counter() - started, 3)
            item["prompt_tokens"] = llm.prompt_tokens
            item["completion_tokens"] = llm.completion_tokens
            item["reasoning_tokens"] = llm.reasoning_tokens
            items.append(item)
            print(
                f"{question['id']} action={item['action']} "
                f"context_hit={item['context_hit']} "
                f"behavior_match={item['behavior_match']} "
                f"calls={item['llm_call_count']}",
                file=sys.stderr,
                flush=True,
            )

    return {
        "selection_prompt_version": SELECTION_PROMPT_VERSION,
        "answer_prompt_version": ANSWER_PROMPT_VERSION,
        "embedding_model": embedding_model,
        "selection_model": selection_model,
        "answer_model": answer_model,
        "similarity_threshold": threshold,
        "retrieval_top_k": top_k,
        "max_added_provisions": max_added,
        "selection_reasoning_effort": selection_effort,
        "answer_reasoning_effort": answer_effort,
        "items": items,
        "summary": {
            "context_hits": sum(1 for i in items if i["context_hit"]),
            "behavior_matches": sum(1 for i in items if i["behavior_match"]),
            "questions": len(items),
        },
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        default="eval/reports/prompt_eval.json",
    )
    parser.add_argument("--corpus", default="/app/corpus/manifest.yaml")
    parser.add_argument(
        "--questions",
        default="eval/eval_questions.json",
    )
    parser.add_argument("--question", type=str, default=None)
    args = parser.parse_args(argv)
    report = asyncio.run(_async_main(args))
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
