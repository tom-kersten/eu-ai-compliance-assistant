# AGENTS.md

## What this is

A Dutch-language Q&A assistant over four EU legal texts (AI-verordening, AVG, CRA, Digitale omnibus inzake AI) for companies that build or run AI applications. Streamlit frontend, FastAPI backend, Postgres with pgvector, everything in Docker.

It explains and cites provisions; it does not make compliance decisions. Clarity, tests, and sound trade-offs matter more than breadth.

## Source of truth

Read the relevant documents before planning any work. They are decided. Do not contradict them.

| Document | Covers |
|---|---|
| `docs/REFERENCE.md` | Scope, behavior, non-goals |
| `docs/ARCHITECTURE.md` | Services, data model, chunk header format, API, configuration, tests, build order |
| `docs/PROMPT_SPEC.md` | What the two LLM prompts must do |
| `eval/eval_questions.json` | Evaluation questions and expected provisions |
| `docs/PROVIDER_NOTES.md` | Verified provider behavior (created by the provider verification task) |

If a document is ambiguous, or the implementation needs to differ from it, stop and ask. Do not deviate silently. When a change is agreed, update the documents in the same change.

## Settled decisions (do not revisit without asking)

- Postgres with pgvector, exact cosine search, no vector index, `vector(2000)`.
- A chunk is one article, annex, or recital. Split only above 30,000 tokens, evenly at paragraph boundaries.
- Retrieval: top 10 above a similarity threshold, whole provisions only. Then one LLM selection call, exact lookup of referenced provisions, and one LLM answer call. Never more than two LLM calls per question.
- The backend is stateless. Session state lives in Streamlit. Progress is streamed to the UI as Server-Sent Events.
- LLM and embedding calls use plain `httpx` against OpenAI-compatible endpoints, behind our own Protocols. No LangChain, LlamaIndex, or similar frameworks.
- Dutch only: corpus, interface, answers. Prompts are written in English and instruct Dutch output.
- The evaluation set is single-turn.

## Non-negotiables

1. **Test-driven.** Write the failing test first, see it fail, then write the code. No feature without tests.
2. **Docker only.** Nothing may require a host Python environment. Use `make` targets (`make test`, `make lint`, ...) to run tests and checks. Never invoke `pytest`, `ruff`, or similar directly on the host: dev dependencies exist only inside the Docker images, so a direct host invocation will fail even when the code and the containerized tests are fine.
3. **Configuration over code.** No hardcoded model names, URLs, thresholds, or dimensions. A new setting goes in `app/config.py`, in both `.env` example files, and in `docs/ARCHITECTURE.md` section 10.
4. **Legal text is never invented or edited.** Corpus content comes only from `corpus/raw`, through the manifest. Normalization is limited to whitespace and amendment-marker stripping.
5. **Do not assume provider behavior.** Parameter names and behavior for OpenRouter and vLLM (`dimensions`, reasoning effort, structured output together with reasoning, the Qwen query instruction) are unverified until recorded in `docs/PROVIDER_NOTES.md`.
6. **Secrets and privacy.** Never commit `.env` or keys. Never log keys. Log message content only at DEBUG.
7. **Language.** Code, comments, docs, and commit messages are in English. User-facing strings are in Dutch, kept in one place in the frontend.

## Commands

Run `make help` for the full list.

| Command | Purpose |
|---|---|
| `make up`, `make up-offline`, `make down`, `make clean` | Run or stop the stack |
| `make migrate`, `make new-migration name=x`, `make ingest`, `make ingest-reset`, `make psql` | Database |
| `make test`, `make test-unit`, `make test-api`, `make test-db`, `make test-frontend` | Tests without keys or GPUs |
| `make test-live` | Opt-in tests against real providers |
| `make eval` | Retrieval evaluation |
| `make lint`, `make fmt` | ruff |

CI (`.github/workflows/ci.yml`) runs `make build`, `make lint`, `make test`, and `make test-frontend` on every push and pull request. A change is not done until CI is green.

## Workflow

1. Read the task, the relevant documents, and the matching files in `.cursor/rules/`.
2. Write a short local plan: files to touch, the tests to write first, and the acceptance criteria. Stay inside the task's scope.
3. Implement in small steps. Each step ends green (`make test`, `make lint`).
4. Do not expand scope. Mention unrelated ideas in your summary instead of implementing them.
5. Definition of done: acceptance criteria met, tests written first and passing, `make lint` clean, documents and `.env` examples updated if behavior or configuration changed, no stray TODOs or dead code.

## Code conventions

- Python 3.12 or newer, type hints on all functions, Pydantic v2 at every boundary, `ruff` for formatting and linting.
- Async for all I/O. Plain SQL with parameters. No ORM.
- Small, explicit functions. Clear over clever. Comments explain why, not what.
- Add dependencies only when needed, through `uv`, and commit the lockfile.
- Area-specific rules are in `.cursor/rules/*.mdc`. The repository layout is in `docs/ARCHITECTURE.md` section 3.
