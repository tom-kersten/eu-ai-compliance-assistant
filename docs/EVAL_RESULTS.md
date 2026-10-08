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
