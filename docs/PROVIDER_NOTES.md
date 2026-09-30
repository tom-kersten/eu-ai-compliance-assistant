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
- cosine_vs_truncated_native: 0.999932
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
  - bare: 0.170391
  - web_search: 0.179377
  - legal: 0.112517
- comparison:
  - bare_provider:
    - match_cosine: 0.685707
    - distractor_cosine: 0.527933
    - margin: 0.157774
  - bare_recruitment:
    - match_cosine: 0.680467
    - distractor_cosine: 0.497459
    - margin: 0.183008
  - web_search_provider:
    - match_cosine: 0.755718
    - distractor_cosine: 0.601712
    - margin: 0.154006
  - web_search_recruitment:
    - match_cosine: 0.702008
    - distractor_cosine: 0.497259
    - margin: 0.204749
  - legal_provider:
    - match_cosine: 0.741696
    - distractor_cosine: 0.610358
    - margin: 0.131337
  - legal_recruitment:
    - match_cosine: 0.671229
    - distractor_cosine: 0.577532
    - margin: 0.093697

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
  - 1: 242.8
  - 8: 447.0
  - 32: 1121.6
  - 100: 1666.0

## 4. Structured output

- selection_successes: 10
- selection_attempts: 10
- answer_successes: 10
- answer_attempts: 10
- response_format: json_schema
- providers_seen:
  - Darkbloom
  - Ionstream
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
  - Chutes
  - Cloudflare
  - CoreWeave
  - Darkbloom
  - DeepInfra
  - DekaLLM
  - Ionstream
  - Mancer 2
  - Novita
  - Parasail
  - Phala
  - Reka
  - Venice
  - Wafer
- embedding_context_length: None
- llm_context_length: 1000000

## Decisions for T8

- Send dimensions=2000 on every embeddings request and raise if the returned length differs.
- embed_query must prefix with `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` + the user query. embed_documents must send the raw text.
- Use embedding batch size 100 (largest successful probe; failed=[]).
- Request structured output with response_format type=json_schema, strict=true, additionalProperties=false, schemas shaped like SelectionResult and AnswerResult.
- Reasoning parameter for OpenRouter: {'reasoning': {'effort': 'medium', 'exclude': False}}. Works with structured output: True.
- Parse only message.content. Discard reasoning / reasoning_details. Observed reasoning fields: ['message.reasoning', 'message.reasoning_details'].
- Usage paths: prompt=usage.prompt_tokens, completion=usage.completion_tokens, reasoning=usage.completion_tokens_details.reasoning_tokens.
- Structured-output success rates (no reasoning): selection 10/10, answer 10/10.
