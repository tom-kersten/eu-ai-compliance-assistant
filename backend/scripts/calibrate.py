"""Measure retrieval and selection settings on the eval set.

Reads provider keys from the environment. Never prints key values.
Writes a JSON summary (no vectors, no prompt text) to the given path.
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
from pydantic import ValidationError

from app.errors import SelectionInvalid
from app.ingestion.chunker import chunk_indexed
from app.ingestion.manifest import load_indexed_provisions, load_manifest
from app.pipeline.prompts.selection import build_selection_prompt
from app.pipeline.resolve import resolve
from app.pipeline.select import validate_selection
from app.schemas.domain import Provision
from app.schemas.llm import Message, SelectionResult, Situation
from eval.reliability import (
    SELECTION_SCHEMA,
    chat_request,
    message_content,
    parse_valid,
)
from eval.tuning import (
    can_separate,
    count_vector_hits,
    decide_reasoning,
    decide_status_line,
    embedding_text,
    is_admitted,
    quantize_threshold,
    rank_similarities,
    required_added_cap,
    retrieved_refs,
    review_top_k,
    suggest_threshold,
    vector_hit,
)

QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages "
    "that answer the query\nQuery:"
)
GOOD_IDS = [f"Q0{index}" for index in range(1, 9)]
BAD_ID = "Q09"
EFFORTS = ("none", "low", "medium")
CURRENT_TOP_K = 10


class MemoryLookup:
    """In-memory provision lookup for the selection cap."""

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
    last_status = 0
    last_body = ""
    response = None
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


def _variant_ranked(
    questions: list[dict],
    query_vectors: dict[str, list[float]],
    provision_vectors: dict[str, list[float]],
) -> dict[str, list[tuple[str, float]]]:
    return {
        question["id"]: rank_similarities(
            query_vectors[question["id"]],
            provision_vectors,
        )
        for question in questions
    }


def _variant_stats(
    ranked: dict[str, list[tuple[str, float]]],
    questions: list[dict],
) -> dict[str, Any]:
    top_k = review_top_k(
        ranked,
        questions,
        good_ids=GOOD_IDS,
        current=CURRENT_TOP_K,
    )
    separable = can_separate(
        ranked,
        questions,
        good_ids=GOOD_IDS,
        bad_id=BAD_ID,
        top_k=top_k,
    )
    if separable:
        threshold = suggest_threshold(
            ranked,
            questions,
            good_ids=GOOD_IDS,
            bad_id=BAD_ID,
            top_k=top_k,
        )
        threshold = quantize_threshold(
            threshold,
            ranked,
            questions,
            good_ids=GOOD_IDS,
            bad_id=BAD_ID,
            top_k=top_k,
        )
    else:
        bad_max = ranked[BAD_ID][0][1]
        threshold = bad_max
    hits = count_vector_hits(
        ranked,
        questions,
        good_ids=GOOD_IDS,
        top_k=top_k,
        threshold=threshold if separable else ranked[BAD_ID][0][1] + 1.0,
    )
    return {
        "top_k": top_k,
        "separable": separable,
        "threshold": threshold if separable else None,
        "vector_hits": hits,
        "ranked": ranked,
    }


def _question_rows(
    ranked: dict[str, list[tuple[str, float]]],
    questions: list[dict],
    *,
    top_k: int,
    threshold: float,
) -> list[dict[str, Any]]:
    rows = []
    by_id = {question["id"]: question for question in questions}
    for question_id, scores in ranked.items():
        question = by_id[question_id]
        must_rows = []
        positions = {ref: index for index, (ref, _) in enumerate(scores)}
        score_by_ref = {ref: score for ref, score in scores}
        for ref in question.get("must") or []:
            must_rows.append(
                {
                    "ref": ref,
                    "rank": positions.get(ref, -1) + 1 if ref in positions else None,
                    "score": score_by_ref.get(ref),
                }
            )
        top1_ref, top1_score = scores[0]
        rows.append(
            {
                "id": question_id,
                "admitted": is_admitted(scores, top_k=top_k, threshold=threshold),
                "vector_hit": vector_hit(
                    scores,
                    list(question.get("must") or []),
                    top_k=top_k,
                    threshold=threshold,
                ),
                "top1_ref": top1_ref,
                "top1_score": round(top1_score, 4),
                "must": must_rows,
            }
        )
    return rows


def _completion_tokens(body: dict[str, Any]) -> int:
    usage = body.get("usage") if isinstance(body, dict) else None
    if not isinstance(usage, dict):
        return 0
    return int(usage.get("completion_tokens") or 0)


async def _selection_hit(
    content: str | None,
    *,
    retrieved: list[Provision],
    must: list[str],
    lookup: MemoryLookup,
    document_keys: list[str],
    max_added: int,
) -> bool:
    if not parse_valid(content, SelectionResult):
        return False
    try:
        result = SelectionResult.model_validate(json.loads(content or ""))
        validate_selection(result, [provision.ref for provision in retrieved])
    except (ValidationError, SelectionInvalid, json.JSONDecodeError):
        return False
    resolved = await resolve(
        result.request,
        result.external_references,
        kept=result.keep,
        document_keys=document_keys,
        lookup=lookup,
        max_added=max_added,
    )
    found = set(result.keep) | {provision.ref for provision in resolved.added}
    return set(must).issubset(found)


def _run_reasoning(
    client: httpx.Client,
    *,
    url: str,
    key: str,
    model: str,
    questions: list[dict],
    provisions: list[Provision],
    ranked: dict[str, list[tuple[str, float]]],
    top_k: int,
    threshold: float,
    max_added: int,
    documents: list[dict[str, str]],
    snapshot: Any,
) -> list[dict[str, Any]]:
    by_ref = {provision.ref: provision for provision in provisions}
    lookup = MemoryLookup(provisions)
    document_keys = [document["key"] for document in documents]
    trials = []
    for effort in EFFORTS:
        hits = 0
        latencies: list[float] = []
        tokens: list[int] = []
        per_question = []
        for question in questions:
            if question["id"] not in GOOD_IDS:
                continue
            refs = retrieved_refs(
                ranked[question["id"]],
                top_k=top_k,
                threshold=threshold,
            )
            retrieved = [by_ref[ref] for ref in refs if ref in by_ref]
            if not retrieved:
                per_question.append(
                    {
                        "id": question["id"],
                        "selection_hit": False,
                        "called": False,
                    }
                )
                continue
            messages = build_selection_prompt(
                [Message(role="user", content=question["question"])],
                Situation(),
                [
                    {
                        "ref": provision.ref,
                        "header": provision.header,
                        "body": provision.body,
                    }
                    for provision in retrieved
                ],
                documents,
                snapshot,
                max_added,
            )
            payload = chat_request(
                model=model,
                schema_name="selection_result",
                schema=SELECTION_SCHEMA,
                messages=[
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                reasoning_effort=None if effort == "none" else effort,
                max_tokens=8192,
            )
            started = time.perf_counter()
            try:
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            except httpx.HTTPError:
                elapsed = time.perf_counter() - started
                latencies.append(elapsed)
                tokens.append(0)
                per_question.append(
                    {
                        "id": question["id"],
                        "selection_hit": False,
                        "called": True,
                        "latency_seconds": round(elapsed, 3),
                        "completion_tokens": 0,
                        "http_status": 0,
                    }
                )
                print(
                    f"selection {effort} {question['id']} hit=False http=0",
                    file=sys.stderr,
                )
                continue
            elapsed = time.perf_counter() - started
            body: dict[str, Any] = {}
            if response.status_code == 200:
                parsed = response.json()
                if isinstance(parsed, dict):
                    body = parsed
            content = message_content(body) if body else None
            hit = asyncio.run(
                _selection_hit(
                    content,
                    retrieved=retrieved,
                    must=list(question.get("must") or []),
                    lookup=lookup,
                    document_keys=document_keys,
                    max_added=max_added,
                )
            )
            if hit:
                hits += 1
            latencies.append(elapsed)
            tokens.append(_completion_tokens(body))
            per_question.append(
                {
                    "id": question["id"],
                    "selection_hit": hit,
                    "called": True,
                    "latency_seconds": round(elapsed, 3),
                    "completion_tokens": _completion_tokens(body),
                    "http_status": response.status_code,
                }
            )
            print(
                f"selection {effort} {question['id']} "
                f"hit={hit} http={response.status_code}",
                file=sys.stderr,
            )
        call_count = len(latencies) or 1
        trials.append(
            {
                "effort": effort,
                "selection_hits": hits,
                "questions": len(GOOD_IDS),
                "mean_latency_seconds": round(sum(latencies) / call_count, 3),
                "mean_completion_tokens": round(sum(tokens) / call_count),
                "questions_detail": per_question,
            }
        )
    return trials


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        default="eval/reports/calibration.json",
    )
    parser.add_argument("--corpus", default="/app/corpus/manifest.yaml")
    parser.add_argument(
        "--questions",
        default="eval/eval_questions.json",
    )
    args = parser.parse_args(argv)

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
    dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "2000"))
    batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE", "100"))
    timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))

    manifest = load_manifest(Path(args.corpus))
    corpus_root = Path(args.corpus).parent
    indexed = load_indexed_provisions(manifest, corpus_root)
    documents_by_key = {doc.key: doc for doc in manifest.documents}
    provisions = chunk_indexed(indexed, documents_by_key, token_limit=30000)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    cap = required_added_cap(questions)

    texts_with = [
        embedding_text(provision.header, provision.body, include_status=True)
        for provision in provisions
    ]
    texts_without = [
        embedding_text(provision.header, provision.body, include_status=False)
        for provision in provisions
    ]
    query_texts = [QUERY_PREFIX + question["question"] for question in questions]

    with httpx.Client(timeout=timeout) as client:
        embedded = _embed_all(
            client,
            url=f"{embedding_base}/embeddings",
            key=embedding_key,
            model=embedding_model,
            dimensions=dimensions,
            texts=texts_with + texts_without + query_texts,
            batch_size=batch_size,
        )
        with_vectors = embedded[: len(provisions)]
        without_vectors = embedded[len(provisions) : len(provisions) * 2]
        query_vectors_list = embedded[len(provisions) * 2 :]
        query_vectors = {
            question["id"]: vector
            for question, vector in zip(questions, query_vectors_list, strict=True)
        }
        refs = [provision.ref for provision in provisions]
        ranked_with = _variant_ranked(
            questions,
            query_vectors,
            dict(zip(refs, with_vectors, strict=True)),
        )
        ranked_without = _variant_ranked(
            questions,
            query_vectors,
            dict(zip(refs, without_vectors, strict=True)),
        )
        stats_with = _variant_stats(ranked_with, questions)
        stats_without = _variant_stats(ranked_without, questions)
        decision = decide_status_line(
            vector_hits_with=stats_with["vector_hits"],
            vector_hits_without=stats_without["vector_hits"],
            separable_with=stats_with["separable"],
            separable_without=stats_without["separable"],
        )
        chosen = stats_with if decision == "keep" else stats_without
        if not chosen["separable"] or chosen["threshold"] is None:
            raise SystemExit("chosen embedding variant cannot separate Q09")
        threshold = float(chosen["threshold"])
        top_k = int(chosen["top_k"])
        documents = [
            {
                "key": doc.key,
                "short_name": doc.short_name,
                "identifier": doc.identifier,
            }
            for doc in manifest.documents
        ]
        trials = _run_reasoning(
            client,
            url=f"{llm_base}/chat/completions",
            key=llm_key,
            model=selection_model,
            questions=questions,
            provisions=provisions,
            ranked=chosen["ranked"],
            top_k=top_k,
            threshold=threshold,
            max_added=cap,
            documents=documents,
            snapshot=manifest.snapshot,
        )
    effort = decide_reasoning(trials)
    report = {
        "embedding_model": embedding_model,
        "selection_model": selection_model,
        "dimensions": dimensions,
        "provision_count": len(provisions),
        "query_instruction": QUERY_PREFIX,
        "status_line": decision,
        "with_status": {
            "separable": stats_with["separable"],
            "vector_hits": stats_with["vector_hits"],
            "top_k": stats_with["top_k"],
            "threshold": stats_with["threshold"],
        },
        "without_status": {
            "separable": stats_without["separable"],
            "vector_hits": stats_without["vector_hits"],
            "top_k": stats_without["top_k"],
            "threshold": stats_without["threshold"],
        },
        "similarity_threshold": threshold,
        "retrieval_top_k": top_k,
        "max_added_provisions": cap,
        "selection_reasoning_effort": effort,
        "questions": _question_rows(
            chosen["ranked"],
            questions,
            top_k=top_k,
            threshold=threshold,
        ),
        "reasoning": [
            {key: value for key, value in trial.items() if key != "ranked"}
            for trial in trials
        ],
    }
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
