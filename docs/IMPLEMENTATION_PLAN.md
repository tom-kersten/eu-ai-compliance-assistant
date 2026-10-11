# Implementation Plan (v1)

> Each task is handed to Cursor, which produces a local build plan and implements it test-first.
> Scope and behavior: `REFERENCE.md`. Structure: `ARCHITECTURE.md`. Prompts: `PROMPT_SPEC.md`. Rules: `AGENTS.md` and `.cursor/rules/`.

## How to use this plan

**Handoff prompt** for each task:

```
Implement Task <N> from docs/IMPLEMENTATION_PLAN.md.
1. Read AGENTS.md, the documents and rule files listed under "Read first" in the task.
2. Write a local build plan: files to create or change, the tests you will write first
   (in order), and how you will check each acceptance criterion.
3. Implement test-first in small steps. Each step ends green (make test, make lint).
4. Finish with a summary: what changed, test results, anything that deviates from the
   documents (nothing should, without asking), and what the next task needs to know.
```

**Rules for every task:** stay inside the task's scope, leave `make test` and `make lint` green, and update documents and `.env` examples when behavior or configuration changes.

## Overview

| ID | Task | Pri | Est. | Depends on |
|---|---|---|---|---|
| T0 | Scaffold: compose, Makefile, Dockerfiles, tooling | P0 | 60 min | none |
| T1 | Provider verification and `PROVIDER_NOTES.md` | P0 | 60 min | T0 |
| T2 | Migration runner and initial schema | P0 | 30 min | T0 |
| T3 | Settings and Pydantic schemas | P0 | 30 min | T0 |
| T4 | Parser for the consolidated texts, amendment markers | P0 | 75 min | T3 |
| T5 | Omnibus parser and corpus manifest | P0 | 30 min | T4 |
| T6 | Header builder and chunker | P0 | 45 min | T4, T5 |
| T7 | Repository | P0 | 45 min | T2, T3 |
| T8 | Provider interfaces, fakes, OpenAI-compatible adapters | P0 | 60 min | T1, T3 |
| T9 | Ingestion command | P0 | 45 min | T2, T6, T7, T8 |
| T10 | Query building, retrieval, prompt budget | P0 | 30 min | T3, T8 |
| T11 | Selection step and reference resolution | P0 | 60 min | T7, T10 |
| T12 | Answer step and validation | P0 | 60 min | T11 |
| T13 | Orchestrator | P0 | 45 min | T10, T11, T12 |
| T14 | Eval runner and dev CLI | P0 | 45 min | T9, T13 |
| T15 | API with SSE | P0 | 60 min | T13 |
| T16 | Streamlit frontend | P0 | 75 min | T15 |
| T17 | Calibration and reliability tests | P1 | 60 min | T14 |
| T18 | Prompt tuning against the eval set | P1 | 45 min | T17 |
| T19 | README and documentation pass | P0 | 45 min | T16 |
| T20 | Offline profile | P1 | 45 min | T16 |
| T21 | Final hardening and clean-clone check | P1 | 30 min | all |

Estimates are rough, include review time, and assume Cursor does the typing. They total about 18 hours. See [Time and cut lines](#time-and-cut-lines).

**Milestones**

| | After | State |
|---|---|---|
| M1 | T9 | The corpus is parsed, chunked, embedded, and indexed. |
| M2 | T14 | The pipeline answers the eval questions from the command line. |
| M3 | T16 | The full application runs. |
| M4 | T18 | The eval behavior targets are met. |
| M5 | T21 | Ready to submit. |

## Phase A: Foundations

### T0. Scaffold

**Objective:** a repository skeleton where every later task runs in containers.

**Read first:** `ARCHITECTURE.md` sections 2, 3, 4, 10, 11. Rules: `docker.mdc`, `backend-python.mdc`.

**Deliverables:**
- Directory layout from `ARCHITECTURE.md` section 3, with empty packages.
- `docs/` and `eval/` populated with the design documents and `eval_questions.json`.
- `docker-compose.yml` with `db`, `migrate` (a placeholder that exits successfully until T2), `backend`, `frontend`, and the `test` profile (`db-test`, `backend-test`, `frontend-test`). Pinned image tags.
- Multi-stage Dockerfiles (`runtime` and `dev`), `uv` with a lockfile, non-root user.
- `Makefile` with the targets from `ARCHITECTURE.md` section 11, each with a `##` description. Targets that need later code may fail with a clear message.
- `.env.example` and `.env.offline.example`, `.gitignore`, `ruff` and `pytest` configuration with the markers `unit`, `db`, `api`, `live`.
- A minimal `/health` endpoint in the backend and a hello page in the frontend.

**Tests first:** a trivial test per suite, to prove the test profile runs in containers.

**Acceptance:**
- `make build && make up` starts the services, and `/health` responds.
- `make test` runs the suites and passes, `make lint` is clean, `make help` lists every target.
- `.env` is ignored by git. No host Python is needed.

### T1. Provider verification

**Objective:** replace assumptions about OpenRouter with recorded facts, before adapters are written.

**Read first:** `ARCHITECTURE.md` sections 6 and 10, `providers.mdc`. Requires an OpenRouter key supplied by the user.

**Deliverables:**
- `backend/scripts/verify_providers.py` and `make verify-providers`. Reads keys from the environment and never prints them. Caps the number of calls, which is documented.
- `docs/PROVIDER_NOTES.md` with the verified request and response shapes, ready to copy into the adapters.
- Recorded responses (keys redacted) in `backend/tests/fixtures/providers/`, to be used by adapter tests.

**What to verify and record:**
1. **Embeddings `dimensions`:** does `qwen/qwen3-embedding-8b` return 2000 dimensions when asked? Are vectors normalized? If the parameter is ignored, record the fallback (truncate to 2000 and re-normalize) and check that it gives similar results.
2. **Query instruction:** the exact format from the model card, and a comparison on a few Dutch query and provision pairs with and without it. Record the recommended instruction wording.
3. **Limits:** maximum inputs per embeddings request, practical batch size, latency.
4. **Structured output:** JSON-schema `response_format` with schemas shaped like `SelectionResult` and `AnswerResult` on `qwen/qwen3.8-27b`. Success rate over about ten runs each.
5. **Reasoning:** how effort is specified on OpenRouter, what comes back (reasoning content, reasoning token count), and whether structured output still works with `medium` effort. Record failure modes.
6. **Usage fields:** the exact names for prompt, completion, and reasoning tokens.
7. **Routing:** which providers serve each model, and the context window actually reported.

**Tests first:** unit tests for the redaction helper and the notes renderer. The live calls are the deliverable.

**Acceptance:** every item above has a recorded result or an explicit "not supported, use fallback X". `PROVIDER_NOTES.md` states the decisions that T8 must follow.

### T2. Migration runner and initial schema

**Objective:** versioned, checksummed, forward-only migrations.

**Read first:** `ARCHITECTURE.md` section 5 (data model, Migrations). Rule: `migrations.mdc`.

**Deliverables:** `store/migrate.py` with the `migrate` command, `postgres/migrations/0001_init.sql` (extension, `provisions`, `index_meta`, from the DDL in the document), `make migrate`, `make new-migration`, the `migrate` compose service running the real command, and a function that reports pending migrations (used later by `/health`).

**Tests first (`db`, and one `unit`):**
- Applies all migrations to an empty database and creates the expected tables and constraints.
- Re-running is a no-op.
- Files apply in numeric order, each in its own transaction (a failing file leaves nothing behind).
- A changed, already applied file stops with a checksum error.
- `new-migration` produces the next zero-padded number.

**Acceptance:** `make migrate` on a fresh database yields the schema. `make test-db` is green.

### T3. Settings and schemas

**Objective:** typed configuration and all shared models.

**Read first:** `ARCHITECTURE.md` sections 6, 8, 10. Rule: `backend-python.mdc`.

**Deliverables:**
- `config.py` with every variable in `ARCHITECTURE.md` section 10, validated (for example the dimension is positive and the threshold is between 0 and 1).
- `schemas/llm.py`: `Message` (with the optional `action` on assistant messages), `Situation`, `RequestedProvision`, `ExternalReference`, `SelectionResult`, `AnswerResult`.
- `schemas/api.py`: `AskRequest`, the event models (`status`, `retrieved`, `selection`, `final`, `error`), corpus info.
- `schemas/domain.py`: provision and retrieved-provision models.
- Shape validation on the models: `AnswerResult` with `clarify` needs one or two questions and no answer text, `answer` needs text and at least one citation, `cannot_answer` needs an explanation and no questions.

**Tests first:** defaults and environment overrides, invalid settings rejected, `extra="forbid"`, each shape rule, event serialization round trips, and a test that every `Settings` field appears in `.env.example`.

**Acceptance:** all schemas importable without side effects, and the tests pass.

## Phase B: Corpus and ingestion

### T4. Parser for the consolidated texts

**Objective:** turn the AI Act, AVG, and CRA HTML into structured provisions, with correct lineage and amendment state.

**Read first:** `ARCHITECTURE.md` section 5 (header and body format, amendment markers). Rule: `ingestion.mdc`. Real files in `corpus/raw`.

**Deliverables:** `ingestion/models.py` (parsed provision), `ingestion/markers.py` (running-state tracker and stripper), `ingestion/parsers/consolidated.py`.

**Tests first (against the real files):**
- Counts: AI Act 119 articles and 14 annexes, AVG 99 articles, CRA 71 articles and 8 annexes.
- Labels read from headings: `4 bis`, `60 bis`, `75 bis` to `75 quater`, annex numerals.
- Titles and lineage: AI Act Article 6 (Hoofdstuk III, Afdeling 1), Article 26 (Afdeling 3), AVG Article 22 (Hoofdstuk III, Afdeling 4), AVG Article 9 (chapter only), CRA Article 12, AI Act Annex III (annex, no chapter).
- Body excludes the heading elements, and each numbered paragraph and list item is on its own line.
- **Markers:** no `▼`, `►`, or `◄` character remains in any body. `amended_by` is true for Articles 4, 4 bis, 6, 60 bis, and 75 bis (whole-article insertions included), and false for AI Act Article 12 and for every AVG article. Corrigendum markers do not set it.
- Deterministic output on repeated runs.

**Acceptance:** all tests pass on the real files, with no network access.

### T5. Omnibus parser and corpus manifest

**Objective:** parse the Omnibus layout and select what gets indexed.

**Read first:** `ARCHITECTURE.md` section 5 (Ingestion, Manifest). Rule: `ingestion.mdc`.

**Deliverables:** `ingestion/parsers/oj.py`, `ingestion/manifest.py` (YAML to typed model, validation, include filters), `corpus/manifest.yaml` as in the document.

**Tests first:**
- The manifest loads, and rejects a missing file, an unknown parser, or a malformed include.
- The Omnibus parser yields 47 recitals labeled `Overweging (1)` to `(47)` and four articles. Recital 40 starts with "Artikel 113 van Verordening (EU) 2024/1689".
- Article 4 has the title "Inwerkingtreding en toepassing".
- After the include filters, the Omnibus contributes 48 provisions, and the whole corpus is 359.
- The XML declaration in the Omnibus file is handled without warnings.

**Acceptance:** the filtered provision set across all four documents has exactly 359 entries, with unique refs.

### T6. Header builder and chunker

**Objective:** the lineage header, the split rule, and refs.

**Read first:** `ARCHITECTURE.md` section 5 (header format, real examples). Rule: `ingestion.mdc`.

**Deliverables:** `ingestion/headers.py`, `ingestion/chunker.py`, `ingestion/tokens.py` (the replaceable estimator).

**Tests first:**
- **The seven real examples** from `ARCHITECTURE.md` section 5 reproduce exactly, including the status line only where the provision is amended.
- The synthetic part example (`Deel 2 van 3: leden 3 tot en met 5`), the annex wording (`punten`), and the added internal heading for an annex split under one.
- Chunker: no split under the limit. Above it, the fewest parts that fit, balanced in size, split at paragraph boundaries, with the header counted toward the limit. A single over-long paragraph splits at sentence boundaries.
- Refs: `AI-verordening:art_4a`, part refs `AVG:art_9#2`, with `parent_ref`, `part_no`, and `part_count`.
- Embedded text is `header + "\n\n" + body`.
- Characterization test: no real provision is split, and the largest chunk is under the limit.

**Acceptance:** every chunk of the real corpus has a header with the correct lineage, and all tests pass.

## Phase C: Storage and providers

### T7. Repository

**Objective:** all SQL in one place, tested against the real database.

**Read first:** `ARCHITECTURE.md` section 5. Rules: `backend-python.mdc`, `testing.mdc`.

**Deliverables:** `store/db.py` (async pool), `store/repository.py`: bulk upsert, truncate, get by refs, get by parent ref (all parts, in order), similarity search (top-k and threshold, cosine), read and write `index_meta`, corpus summary counts.

**Tests first (`db`):**
- Upsert then fetch. Parent lookup returns parts in order.
- Similarity search with hand-made vectors: ordering, top-k, threshold exclusion, nothing above threshold returns empty.
- `index_meta` holds at most one row. Inserting a vector of the wrong dimension fails.
- No SQL outside `store/`.

**Acceptance:** `make test-db` is green.

### T8. Providers

**Objective:** swappable, verified adapters and usable fakes.

**Read first:** `ARCHITECTURE.md` section 6, `PROVIDER_NOTES.md` (from T1), `providers.mdc`.

**Deliverables:** `providers/base.py` (Protocols), `providers/fakes.py` (deterministic hash-based embedder, scripted LLM recording its calls), `providers/openai_compat.py` (embeddings and LLM), the per-provider reasoning mapping function.

**Tests first:**
- With `respx` and the recorded fixtures: the embeddings request carries the model, inputs, and `dimensions`. A wrong returned length raises. The query instruction is applied only to queries. Batching respects the configured size.
- LLM: the request includes the JSON schema and the reasoning setting as verified in T1. An invalid structured output is retried up to `LLM_MAX_RETRIES`, then raises. Usage includes reasoning tokens. Reasoning content is not returned.
- Retries on 429, 5xx, and timeouts with backoff (time patched).
- API keys never appear in logs, and bodies only at DEBUG.
- The fakes are deterministic, and the scripted LLM serves queued responses in order and fails loudly when the queue is empty.

**Acceptance:** adapter behavior matches `PROVIDER_NOTES.md`, and all tests pass without network access.

### T9. Ingestion command

**Objective:** one command builds the index.

**Read first:** `ARCHITECTURE.md` section 5 (Ingestion). Rule: `ingestion.mdc`.

**Deliverables:** `ingestion/run.py` with the `ingest` command and `--reset`, `corpus_hash`, batched embedding, dimension verification, a single transaction, `index_meta` written, a per-document summary printed, `make ingest` and `make ingest-reset`, and container entrypoint support for `migrate` and `ingest`.

**Tests first (`db`, with fakes):**
- Ingesting the real corpus gives 359 rows and a populated `index_meta` with the configured dimension.
- Re-running without `--reset` is idempotent. With `--reset` it replaces the content.
- A failure midway (for example the embedder raising) leaves the database unchanged.
- A wrong dimension aborts before anything is written.
- `corpus_hash` is stable across runs and changes when a file changes.

**Acceptance:** with real keys, `make ingest` builds the index (**M1**). Record the run time and the approximate cost in the summary.

## Phase D: Pipeline

### T10. Query building, retrieval, prompt budget

**Read first:** `REFERENCE.md` section 9, `ARCHITECTURE.md` section 6. Rule: `pipeline.mdc`.

**Deliverables:** `pipeline/query.py`, `pipeline/retrieve.py`, `pipeline/budget.py`.

**Tests first:**
- Query: the last `RETRIEVAL_HISTORY_TURNS` user messages only, assistant messages excluded, fewer messages than the limit, empty history.
- Retrieve (fake embedder, in-memory repository): top-k ordering, threshold cut, nothing passes gives an empty result, the query instruction path is used.
- Budget: drops the lowest-ranked provisions until the estimate fits. The top provision is kept even if it alone exceeds the budget, with a logged warning.

**Acceptance:** each step is a pure function of explicit inputs, with the repository and embedder injected.

### T11. Selection step and reference resolution

**Read first:** `PROMPT_SPEC.md` sections 2 and 3, `ARCHITECTURE.md` section 6. Rules: `pipeline.mdc`, `prompts.mdc`.

**Deliverables:** the selection prompt and its builder (`pipeline/prompts/`), `pipeline/select.py` (call and validation), `pipeline/resolve.py`.

**Tests first:**
- **Prompt builder:** golden file for fixed fixtures. Every supplied provision appears once in the `<provision ref="...">` format.
- **Validation:** `keep` and `discard` cover the retrieved refs exactly once each. An unknown ref is invalid, triggering the retry path.
- **Resolve:**
  - Exact lookup by document, kind, and label, accepting printed and anchor forms (`4 bis`, `4bis`, and `4a` all resolve to `art_4a`, and `III` and `iii` to `anx_III`, `40` and `(40)` to `rct_40`).
  - Duplicates of kept provisions are dropped.
  - The cap `MAX_ADDED_PROVISIONS` applies in the model's order, and the overflow is reported.
  - Omnibus Articles 1 to 3 give `not_indexed`. Unknown documents and all `external_references` give `external`. Nothing is dropped silently.
  - A split article returns all its parts.

**Acceptance:** the outputs feed directly into the answer step.

### T12. Answer step and validation

**Read first:** `PROMPT_SPEC.md` sections 2 and 4, `ARCHITECTURE.md` section 6. Rules: `pipeline.mdc`, `prompts.mdc`.

**Deliverables:** the answer prompt and builder, `pipeline/answer.py`, the validators.

**Tests first:**
- **Prompt builder:** golden file. Unavailable references are listed with their reason. The situation and the conversation are included. Reasoning settings come from configuration.
- **Validation:** citations are a subset of the final context. `clarify` is rejected when the last assistant message had `action = clarify` (this triggers the retry path). Shape rules from T3 hold.
- **Soft check:** article numbers mentioned in the answer that are not in the context produce a logged warning, not a failure.
- **Situation:** the request's situation is the input, and the returned situation is what the UI shows.

**Acceptance:** with a scripted LLM, each decision (`answer`, `clarify`, `cannot_answer`) is produced and validated correctly.

### T13. Orchestrator

**Read first:** `REFERENCE.md` section 9, `ARCHITECTURE.md` sections 6 and 7. Rule: `pipeline.mdc`.

**Deliverables:** `pipeline/orchestrator.py`, an async generator yielding typed events, usage aggregation (calls, tokens, prompt versions), error mapping.

**Tests first (fakes and an in-memory repository):**
- Nothing above the threshold gives `final` with `cannot_answer` and **zero** LLM calls.
- The happy path yields events in order: status (searching), retrieved, status (selecting), selection, status (answering), final.
- An empty final context gives `cannot_answer` after **one** LLM call.
- Unavailable references reach call 2's input.
- A clarify path, and a blocked second clarify leading to a retry.
- Exhausted retries give an `error` event.
- The budget is applied before each call.
- Across all paths, **never more than two LLM calls**.
- Closing the generator early stops further calls.

**Acceptance:** the whole flow is exercised without network access.

### T14. Eval runner and dev CLI

**Read first:** `eval/eval_questions.json`, `REFERENCE.md` section 12.

**Deliverables:** `eval/run_eval.py` and `make eval`. It runs the orchestrator against the real index and providers, or against fakes with a flag. It reports hit rate after vector search and after selection, whether the expected behavior (`answer`, `clarify`, `cannot_answer`) happened, LLM call count, tokens, and latency. The output is a table plus a JSON report in `eval/reports/`. A single-question mode (`--question Q03 --verbose`) prints every event, serving as the command-line interface to the pipeline.

**Tests first:**
- Metric functions on synthetic results.
- The eval file validates against its schema.
- **Every expected and optional ref in the eval file exists in the parsed, filtered corpus.** This needs no database or network.

**Acceptance:** with real keys, the runner runs all nine questions (**M2**). Numbers are not expected to be good yet.

## Phase E: Application

### T15. API with SSE

**Read first:** `ARCHITECTURE.md` sections 7 and 8. Rule: `backend-python.mdc`.

**Deliverables:** the app factory and lifespan (pool, clients, startup checks), `GET /health`, `GET /v1/corpus`, `POST /v1/ask` as Server-Sent Events, error-code mapping, request id middleware, disconnect handling between steps.

**Tests first (`api`):**
- `/health`: healthy, pending migrations, missing index, embedding model or dimension mismatch. Each gives a clear reason.
- `/v1/ask` streams the events in order in proper SSE format (`event:` and JSON `data:`), with the headers from the document.
- A missing index gives 503. A malformed request gives 422.
- A client disconnect stops the pipeline.
- Message content does not appear in INFO logs.

**Acceptance:** the endpoints work against the real database with fake providers, and with real providers through `make up`.

### T16. Streamlit frontend

**Read first:** `ARCHITECTURE.md` section 9. Rule: `frontend-streamlit.mdc`.

**Deliverables:** `client.py` (SSE to typed events), `state.py`, `strings.py` (all Dutch text, error-code mapping), components, `app.py`.

**Tests first:**
- The SSE parser against recorded event streams, including a partial chunk and an `error` event.
- State helpers, including storing the `action` on assistant messages and sending the history back.
- Error-code to Dutch message mapping is complete.
- A smoke test with `streamlit.testing.v1.AppTest` and a stub client.

**Acceptance (**M3**):** in `make up`, asking a question shows live progress (found, kept, added), then the answer with citations in expanders. A clarifying question appears as an assistant message and its reply works. The situation panel is editable and sent with each request. The disclaimer, the EU assumption, and the snapshot date are always visible.

## Phase F: Quality

### T17. Calibration and reliability

**Read first:** `REFERENCE.md` section 14, `ARCHITECTURE.md` section 13.

**Objective:** replace the "to be tuned" values with measured ones.

**Work:**
- Tune `SIMILARITY_THRESHOLD` so Q09 is rejected while Q01 to Q08 are admitted, and review `RETRIEVAL_TOP_K` and `MAX_ADDED_PROVISIONS`.
- A/B the status line in the embedded text (with and without), comparing retrieval hit rates. If there is no clear benefit, drop it.
- Decide `SELECTION_REASONING_EFFORT` by comparing selection quality, latency, and cost.
- **Structured-output reliability test** (`make test-live`): run both calls repeatedly with the configured reasoning settings, hosted and, if available, self-hosted. Record the parse-valid rate and set the retry strategy.

**Deliverables:** `docs/EVAL_RESULTS.md` with the configuration used, tables of results, and the decisions. The chosen values committed to `.env.example`.

**Acceptance:** no "to be tuned" value remains in the documents or configuration. The reliability result is recorded.

### T18. Prompt tuning

**Read first:** `PROMPT_SPEC.md`, `docs/EVAL_RESULTS.md`.

**Work:** iterate on the prompts against the eval set and manual review, with each change versioned through the prompt version string.

**Targets:**
- Q01 to Q08: the expected provisions are in the final context.
- Q08 gives `clarify`, and Q09 gives `cannot_answer` with zero LLM calls.
- Answers are in Dutch, use the source terminology, and cite only provisions in the context.
- No verdicts, and recitals are labeled as explanatory.

**Acceptance (**M4**):** targets met and recorded in `EVAL_RESULTS.md`. Any miss is documented with a hypothesis.

## Phase G: Delivery

### T19. README and documentation pass

**Objective:** a README written for new users and contributors, and documents consistent with what was built.

**Deliverables:**
- `README.md`: what and why, quickstart for the online and offline profiles, the architecture diagram, key design decisions and trade-offs, eval results, known limitations, and a short "what I would do next at production scale" (consolidated and versioned texts, reranking or hybrid search, multi-turn evaluation, persistence, authentication, observability).
- A short list of example questions for a demo.
- `docs/ARCHITECTURE.md` and `docs/REFERENCE.md` updated wherever the implementation diverged, with the reason.

**Acceptance:** following the README from a clean clone works.

### T20. Offline profile

**Read first:** `ARCHITECTURE.md` section 11 (Deployment, Offline notes). Rule: `docker.mdc`.

**Deliverables:** the vLLM services in compose, `.env.offline.example`, `make up-offline`, and `docs/OFFLINE.md` covering hardware needs, quantization options, maximum context length, the `--served-model-name` alignment, and the verified flags.

**Acceptance:**
- `docker compose --profile offline config` validates.
- If GPU hardware is available, `make test-live` passes against the local endpoints, the embedding dimension check included, and the result is recorded.
- Otherwise the flags are clearly marked unverified in `OFFLINE.md`.

### T21. Final hardening

**Work:** a clean clone running `make up`, `make ingest`, `make eval`. Review logs for leaked content or keys. Secret scan. `make lint` and `make test` green. Check that the README and the documents match. Remove dead code and stray TODOs.

**Acceptance (**M5**):** everything above passes from a fresh clone.

## Time and cut lines

The estimates add up to about 18 hours. That is well above the four-hour allocation, so scope needs a decision. If time is a hard limit, cut in this order:

1. **T20 verification.** Keep the compose services and `OFFLINE.md`, marked unverified.
2. **T17 A/B tests** (status line, selection reasoning). Keep threshold tuning and the reliability test.
3. **T18 depth.** Stop once Q08 and Q09 behave and retrieval is reasonable.
4. **T5 and T6 polish.** Keep the seven golden headers and the split rule's synthetic test.

**Do not cut:** the tests, the two-call pipeline behavior, the README, or T1 (an unverified provider assumption costs more than it saves).

## Risks

| Risk | Mitigation |
|---|---|
| `dimensions` is not honored, or structured output fails with reasoning on | T1 runs first, and the notes define the fallbacks before T8 builds on them. |
| Parser edge cases in the HTML | T4 works on the real files, with counts and golden lineage. |
| Free-form LLM output breaks validation | Pydantic validation with bounded retries, and the T17 reliability test. |
| Threshold too strict or too loose | T17 calibrates it on the eval set, with Q09 as the negative case. |
| Self-hosted models need GPU hardware that is not available | T20 accepts documented but unverified flags. |
