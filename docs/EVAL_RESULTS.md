# Evaluation results

Measured on the hosted profile (OpenRouter). Self-hosted vLLM was not running, so that half of the reliability check is recorded as unavailable.

## Configuration

| Setting | Value |
|---|---|
| Embedding model | `qwen/qwen3-embedding-8b` |
| Embedding dimensions | 2000 |
| Query instruction | `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` |
| Selection and answer model | `qwen/qwen3.8-27b` |
| Provisions embedded | 359 |
| `RETRIEVAL_TOP_K` | 10 |
| `SIMILARITY_THRESHOLD` | 0.5959 |
| `MAX_ADDED_PROVISIONS` | 1 |
| `SELECTION_REASONING_EFFORT` | `low` |
| `ANSWER_REASONING_EFFORT` | `medium` |
| `LLM_MAX_RETRIES` | 1 |

Cosine similarity is `1 - (embedding <=> query)`. A question is admitted when at least one provision is inside the top 10 and at or above the threshold. Q09 must not be admitted, so the pipeline makes no LLM call.

## Similarity threshold and top 10

The threshold is the midpoint between Q09's best score and the lowest top score among Q01–Q08, on embeddings that omit the status line. Q02 is the tight case.

| Question | Admitted | Vector hit | Best provision | Expected provisions (rank, score) |
|---|---|---|---|---|
| Q01 | yes | yes | art_25, 0.7508 | art_3 (3, 0.714) |
| Q02 | yes | yes | art_50, 0.6008 | art_50 (1, 0.601) |
| Q03 | yes | yes | anx_III, 0.7290 | art_6 (3, 0.704), anx_III (1, 0.729) |
| Q04 | yes | yes | art_27, 0.8422 | art_26 (8, 0.764), AVG art_35 (2, 0.813) |
| Q05 | yes | yes | art_4a, 0.8693 | art_4a (1, 0.869), art_10 (3, 0.671), AVG art_9 (4, 0.644) |
| Q06 | yes | no | Omnibus rct_19, 0.7793 | art_12 (2, 0.776), art_15 (11, 0.680), art_42 (4, 0.723) |
| Q07 | yes | no | art_16, 0.7669 | art_113 (41, 0.676), anx_III (2, 0.767) |
| Q08 | yes | no | anx_III, 0.6491 | art_6 (100, 0.564), anx_III (1, 0.649), art_16 (19, 0.607), art_26 (2, 0.643) |
| Q09 | no | — | art_3, 0.5910 | — |

Q09's best score is 0.591, below 0.5959. Every question Q01–Q08 has a top score above 0.5959, so all eight are admitted.

`RETRIEVAL_TOP_K` stays 10. Raising it to the worst expected rank (Q08 art_6 at rank 100) would hand selection a large irrelevant set on every question, and that provision scores 0.564, below Q09, so no threshold can both retrieve it and reject Q09. Expected provisions outside the top 10:

- Q06 art_15, rank 11. The eval file lists it as `via_reference`, so selection can add it under the cap.
- Q07 art_113, rank 41.
- Q08 art_16, rank 19, and art_6, rank 100.

Vector hit at this threshold and top 10 is 5/8 (Q01–Q05).

## Added-provision cap

The longest `via_reference` list in the eval set has one entry (Q03–Q08). `MAX_ADDED_PROVISIONS` is 1. The cap is applied in the model's order, and anything past it is reported as unavailable rather than dropped silently.

## Status line in the embedding

Both variants use top 10. Hit counts are vector hits on Q01–Q08.

| Embedding text | Separates Q09 | Vector hits | Threshold |
|---|---|---|---|
| Header including `Gewijzigd bij` | yes | 5 | 0.6014 |
| Header without that line | yes | 5 | 0.5959 |

No clear benefit, so the status line is not part of the embedding input. It stays on the stored header, which is what the model and the user see.

## Selection reasoning

Eight questions (Q01–Q08), one selection call each, retrieved with top 10 and threshold 0.5959. A hit means every expected provision is in `keep` or in the provisions added under the cap. Cost is mean `completion_tokens` per call.

| Effort | Selection hits | Mean latency | Mean completion tokens |
|---|---|---|---|
| none | 4/8 | 115.4 s | 5740 |
| low | 5/8 | 17.3 s | 741 |
| medium | 5/8 | 33.8 s | 2017 |

`low` matches `medium` on hits and costs less time and tokens, so `SELECTION_REASONING_EFFORT` is `low`. Both miss Q06, Q07, and Q08. `none` also misses Q01. The answer step stays at `medium`.

## Structured-output reliability

`make test-live` repeats the selection call and the answer call, each 10 times, with the reasoning settings above, and checks that `message.content` parses and validates. The retry budget is taken from the worse of the two rates: 1 when at least 99% validate, 2 when at least 90% do, otherwise 3.

Hosted result, model `qwen/qwen3.8-27b`:

| Call | Reasoning | Valid | Attempts |
|---|---|---|---|
| Selection | low | 10 | 10 |
| Answer | medium | 10 | 10 |

Both rates are 10/10, so `LLM_MAX_RETRIES` stays 1: one retry remains for a rare invalid output, and the pipeline still stops after that and emits an error.

Self-hosted (`http://vllm-llm:8000/v1`): not running during this measurement.

## Prompt tuning (T18)

Hosted run against the committed retrieval settings above. Prompts: selection `T18v3`, answer `T18v3`. Report: `backend/src/eval/reports/prompt_eval.json` (Q06 answer step retried once after a `JSONDecodeError` and merged from a single-question re-run).

A context hit means every `must` ref is in the final context (kept plus added). Behavior match means the final action equals `expected_behavior`. Q09 must make zero LLM calls.

| Question | Context hit | Action | Expected | Behavior match | LLM calls | Notes |
|---|---|---|---|---|---|---|
| Q01 | yes | answer | answer | yes | 2 | |
| Q02 | yes | answer | answer | yes | 2 | Duty placed on the aanbieder |
| Q03 | yes | answer | answer | yes | 2 | |
| Q04 | yes | answer | answer | yes | 3 | |
| Q05 | yes | clarify | answer | no | 3 | See miss below |
| Q06 | yes | answer | answer | yes | 2 | `art_15` added under the cap; recital labeled as overweging |
| Q07 | yes | answer | answer | yes | 2 | `art_113` added under the cap |
| Q08 | no | clarify | clarify | yes | 2 | `art_6` added; `art_16` still missing |
| Q09 | yes | cannot_answer | cannot_answer | yes | 0 | No LLM call |

Totals: context hits **8/9**, behavior matches **8/9**.

### Qualitative review

Answers for Q01–Q04, Q06, and Q07 are in Dutch, address the user formally, and use source terms (`aanbieder`, `gebruiksverantwoordelijke`). Citations stayed inside the final context (enforced by validation). No compliance verdicts were observed. Where an Omnibus recital was used (Q06), the answer labeled it as an overweging. Clarifying questions (Q05, Q08) were short Dutch role questions with empty answer text.

### Misses and hypotheses

- **Q05 (behavior).** Final context has `art_4a`, `art_10`, and AVG `art_9`, but the model asked for role and high-risk status instead of answering. Hypothesis: it treats “wij” as role-ambiguous even though artikel 4a already assigns the bias-processing exception to aanbieders; a prefer-answer-when-the-provision-names-the-role rule is already in the prompt but is not followed reliably.
- **Q08 (context).** Behavior is correct (`clarify`). `art_6` was requested and added; `art_16` is rank 19 and never enters the top 10, and the added-provision cap is 1, so both cannot be recovered. Hypothesis: retrieval miss for provider obligations, not a prompt bug; raising the cap would trade off other questions.
- **Q06 (transient).** The first full-suite answer call returned truncated JSON (`JSONDecodeError`). Selection had already added `art_15` correctly after label normalization accepted forms like `Artikel15`. A single re-run answered successfully. Hypothesis: occasional long structured outputs under `ANSWER_REASONING_EFFORT=medium` still fail parse; the existing retry budget covers this when the second attempt is valid.

### Prompt and resolve changes that moved the needle

- Selection and answer prompts rewritten to match `PROMPT_SPEC` (keep/discard, clarify conditions, no role inference from “gebruiken”, bare request labels).
- `normalize_label` strips common prefixes (`Artikel15`, `art.6`, `bijlage III`) so requested provisions resolve to indexed refs. That fixed Q06 `art_15` and Q07 `art_113` context misses from the earlier T18v2 run.

## Full-stack `make eval` run (first real run through the production path)

Everything above ran through bespoke scripts (`backend/scripts/calibrate.py`, `backend/scripts/prompt_eval.py`) that call OpenRouter directly rather than through `app.providers.openai_compat.OpenRouterAdapter`. Fixing T14 (the `make eval` Makefile target was a stub until then) finally exercised `app.pipeline.orchestrator.run` together with a real `Repository` and the real adapter for the first time, which surfaced three adapter bugs that had been invisible because nothing had ever called that code path with real credentials: a wrong endpoint (`/responses` instead of `/chat/completions`), a `response_format` shape that didn't match the one `make verify-providers` actually verified, and — the one that mattered — `respond()` returning the raw provider envelope instead of the parsed `message.content`, so every real structured-output call was guaranteed to fail validation. All three are fixed in `openai_compat.py`.

With those fixed, `make eval` (hosted, `qwen/qwen3.8-27b`, same retrieval settings as above):

| Question | Expected | Actual | Behavior match | Vector hit | Selection hit | LLM calls | Latency (s) |
|---|---|---|---|---|---|---|---|
| Q01 | answer | answer | yes | yes | yes | 2 | 53.7 |
| Q02 | answer | answer | yes | yes | yes | 2 | 34.8 |
| Q03 | answer | answer | yes | yes | yes | 2 | 29.1 |
| Q04 | answer | answer | yes | yes | yes | 2 | 45.7 |
| Q05 | answer | answer | yes | yes | yes | 2 | 75.3 |
| Q06 | answer | answer | yes | no | no | 3 | 134.8 |
| Q07 | answer | answer | yes | no | no | 2 | 27.2 |
| Q08 | clarify | clarify | yes | no | no | 2 | 105.8 |
| Q09 | cannot_answer | cannot_answer | yes | yes | yes | 0 | 7.4 |

Behavior matches **9/9**, including Q05, which missed behavior in the `prompt_eval.py` run above. `vector_hit`/`selection_hit` here are computed slightly differently than the table above (strict "all must-refs in `kept`+`added`" rather than allowing for retrieval-ranked recovery), so Q06-Q08 show `no` despite answering correctly — consistent with, not a contradiction of, the retrieval gaps already documented for those three questions. Q06's 3 calls reflect one retried answer-step attempt, same transient-JSON pattern noted above. Report: `eval/reports/<timestamp>.json`.

### Run-to-run variance

A second `make eval` on 2026-10-11, from a freshly built stack with a newly ingested index and the same configuration, matched behavior on **7/9**:

| Question | Expected | Actual | Behavior match | Vector hit | Selection hit | LLM calls | Latency (s) |
|---|---|---|---|---|---|---|---|
| Q01 | answer | answer | yes | yes | yes | 2 | 31.6 |
| Q02 | answer | answer | yes | yes | yes | 2 | 25.6 |
| Q03 | answer | answer | yes | yes | yes | 2 | 33.6 |
| Q04 | answer | answer | yes | yes | yes | 2 | 36.7 |
| Q05 | answer | clarify | no | yes | yes | 2 | 105.6 |
| Q06 | answer | answer | yes | no | yes | 2 | 44.3 |
| Q07 | answer | answer | yes | no | yes | 2 | 21.0 |
| Q08 | clarify | answer | no | no | no | 2 | 104.3 |
| Q09 | cannot_answer | cannot_answer | yes | yes | yes | 0 | 5.0 |

Retrieval is deterministic for a given index, and the vector hits match the run above. The differences come from the two LLM steps. Q05 and Q08 sit on the boundary between answering and asking a clarifying question: whether the stated situation is specific enough is a judgment call, and the model makes it differently between runs. Selection also varies, so Q06 and Q07 recovered their expected provisions this time. A single run is therefore one sample, not a stable score. A reliable figure would need several runs per question, reported as a rate.

This run also completed without hangs after `LLM_TIMEOUT_SECONDS` became a deadline on each whole LLM attempt. Before that change, a provider that kept the connection alive without finishing could stall `make eval` indefinitely.
