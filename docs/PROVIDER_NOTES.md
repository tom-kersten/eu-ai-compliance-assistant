# Provider notes

Verified request and response shapes for OpenRouter, recorded by
`make verify-providers`. Keys are never written here.

HTTP call cap for the verification script: `MAX_HTTP_CALLS = 60` (this run used 53).

- Embedding model: `qwen/qwen3-embedding-8b`
- LLM model: `qwen/qwen3.8-27b`

## 1. Embeddings dimensions

- requested: 2000
- returned_with_param: 2000
- returned_without_param: 4096
- normalized_with_param: True
- normalized_without_param: True
- cosine_vs_truncated_native: 0.997546
- honored: True
- fallback: None
- status_with_param: 200
- status_without_param: 200

dimensions parameter was **honored**. Send `dimensions` from configuration and verify the returned length.

## 2. Query instruction

- format: Instruct: {task}\nQuery:{query}
- recommended_task: Given a web search query, retrieve relevant passages that answer the query
- recommended_variant: web_search
- mean_margins:
  - bare: 0.172738
  - web_search: 0.180065
  - legal: 0.117958
- comparison:
  - bare_provider:
    - match_cosine: 0.680859
    - distractor_cosine: 0.521255
    - margin: 0.159604
  - bare_recruitment:
    - match_cosine: 0.675101
    - distractor_cosine: 0.489229
    - margin: 0.185872
  - web_search_provider:
    - match_cosine: 0.755799
    - distractor_cosine: 0.601806
    - margin: 0.153993
  - web_search_recruitment:
    - match_cosine: 0.703365
    - distractor_cosine: 0.497228
    - margin: 0.206137
  - legal_provider:
    - match_cosine: 0.741169
    - distractor_cosine: 0.604158
    - margin: 0.137011
  - legal_recruitment:
    - match_cosine: 0.677434
    - distractor_cosine: 0.578529
    - margin: 0.098906

## 3. Limits

- batch_sizes_ok:
  - 1
  - 8
  - 32
  - 100
- batch_sizes_failed:
  (none)
- practical_batch_size: 100
- latency_ms:
  - 1: 330.8
  - 8: 485.3
  - 32: 885.9
  - 100: 3424.0

## 4. Structured output

- selection_successes: 10
- selection_attempts: 10
- answer_successes: 10
- answer_attempts: 10
- response_format: json_schema
- providers_seen:
  - Phala
  - Wafer

## 5. Reasoning

- parameter:
  - reasoning:
    - effort: medium
    - exclude: False
- works_with_structured_output: True
- content_fields:
  - message.reasoning
  - message.reasoning_details
- selection_successes_with_reasoning: 10
- selection_attempts_with_reasoning: 10
- answer_successes_with_reasoning: 10
- answer_attempts_with_reasoning: 10
- failure_modes:
  (none)

T8 must parse only `message.content`. Do not store or return reasoning text.

## 6. Usage fields

- prompt_tokens: usage.prompt_tokens
- completion_tokens: usage.completion_tokens
- reasoning_tokens: usage.completion_tokens_details.reasoning_tokens

## 7. Routing

- embedding_providers:
  - Nebius
  - DeepInfra
  - SiliconFlow
- llm_providers:
  - AkashML
  - Alibaba
  - Cerebras
  - Chutes
  - Cloudflare
  - CoreWeave
  - Darkbloom
  - DeepInfra
  - DekaLLM
  - Ionstream
  - Mancer 2
  - ModelRun
  - Novita
  - Parasail
  - Phala
  - Reka
  - Venice
  - Wafer
- embedding_context_length: None
- llm_context_length: 1000000

## Decisions for T8

- Embeddings request shape: `dimensions` is a top-level field on the request body, never nested under a `parameters` object. `input` must always be a JSON array, even for a single text - a bare string is rejected with HTTP 400 (OpenRouter error code 20015). Both were real bugs found after T8/verification shipped with the wrong shapes; code against this confirmed shape, not an assumed one.
- Send dimensions=2000 on every embeddings request and raise if the returned length differs.
- embed_query must prefix with `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` + the user query. embed_documents must send the raw text.
- Use embedding batch size 100 (largest successful probe; failed=[]).
- Request structured output with response_format type=json_schema, strict=true, additionalProperties=false, schemas shaped like SelectionResult and AnswerResult.
- Reasoning parameter for OpenRouter: {'reasoning': {'effort': 'medium', 'exclude': False}}. Works with structured output: True.
- Parse only message.content. Discard reasoning / reasoning_details. Observed reasoning fields: ['message.reasoning', 'message.reasoning_details'].
- Usage paths: prompt=usage.prompt_tokens, completion=usage.completion_tokens, reasoning=usage.completion_tokens_details.reasoning_tokens.
- Structured-output success rates (no reasoning): selection 10/10, answer 10/10.
