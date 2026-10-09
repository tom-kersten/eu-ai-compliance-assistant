# Provider notes

Verified request and response shapes for OpenRouter, recorded by
`make verify-providers`. Keys are never written here.

Self-hosted (vLLM) image pins, quantization, and context-length notes:
`docs/OFFLINE.md`.

HTTP call cap for the verification script: `MAX_HTTP_CALLS = 60` (this run used 50).

- Embedding model: `qwen/qwen3-embedding-8b`
- LLM model: `qwen/qwen3.8-27b`

## 1. Embeddings dimensions

- requested: 2000
- returned_with_param: 2000
- returned_without_param: 4096
- normalized_with_param: True
- normalized_without_param: True
- cosine_vs_truncated_native: 0.996198
- honored: True
- fallback: None
- status_with_param: 200
- status_without_param: 200

dimensions parameter was **honored**. Send `dimensions` from configuration and verify the returned length.

## 2. Query instruction

- format: Instruct: {task}\nQuery:{query}
- recommended_task: (no instruction; bare query scored highest)
- recommended_variant: bare
- mean_margins:
  - bare: 0.16454
  - web_search: -inf
  - legal: 0.109874
- comparison:
  - bare_provider:
    - match_cosine: 0.679498
    - distractor_cosine: 0.528477
    - margin: 0.151021
  - bare_recruitment:
    - match_cosine: 0.674869
    - distractor_cosine: 0.49681
    - margin: 0.178059
  - web_search:
    - error: 400
  - legal_provider:
    - match_cosine: 0.740589
    - distractor_cosine: 0.611067
    - margin: 0.129522
  - legal_recruitment:
    - match_cosine: 0.675837
    - distractor_cosine: 0.585612
    - margin: 0.090225

## 3. Limits

- batch_sizes_ok:
  (none)
- batch_sizes_failed:
  - 1
- practical_batch_size: None
- latency_ms:
  - 1: 509.9

## 4. Structured output

- selection_successes: 10
- selection_attempts: 10
- answer_successes: 9
- answer_attempts: 10
- response_format: json_schema
- providers_seen:
  - AkashML
  - CoreWeave
  - Darkbloom
  - Ionstream
  - Reka
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
- Query instruction did not improve separation on the probe set; still apply the model-card Instruct/Query format with the legal task wording for consistency: `Given a Dutch question about EU AI, privacy, or cybersecurity law, retrieve the relevant statutory provision`.
- Use embedding batch size None (largest successful probe; failed=[1]).
- Request structured output with response_format type=json_schema, strict=true, additionalProperties=false, schemas shaped like SelectionResult and AnswerResult.
- Reasoning parameter for OpenRouter: {'reasoning': {'effort': 'medium', 'exclude': False}}. Works with structured output: True.
- Parse only message.content. Discard reasoning / reasoning_details. Observed reasoning fields: ['message.reasoning', 'message.reasoning_details'].
- Usage paths: prompt=usage.prompt_tokens, completion=usage.completion_tokens, reasoning=usage.completion_tokens_details.reasoning_tokens.
- Structured-output success rates (no reasoning): selection 10/10, answer 9/10.
