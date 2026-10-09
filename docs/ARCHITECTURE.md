# EU AI Compliance Assistant: Architecture (v1)

> Companion to `REFERENCE.md`, which defines scope and behavior. This document defines how the system is built.
> Status: draft. Items still to be settled are listed in [section 13](#13-open-items).

## 1. Principles

- **Simple, but extendable.** Three services, two model endpoints, plain Python. No orchestration framework.
- **Ports and adapters.** The pipeline depends on small interfaces (LLM, embeddings, store). Everything outside is swappable, including fakes in tests.
- **Stateless backend.** All session state lives in Streamlit and travels with each request.
- **Test-driven.** Every component is designed so it can be tested without network access, except where the test is about the real thing (database, real providers).
- **Configuration over code** for models, providers, thresholds, and the corpus list.

## 2. System overview

```mermaid
flowchart LR
    U[Browser] --> FE["frontend<br/>Streamlit"]
    FE -->|"HTTP + SSE"| BE["backend<br/>FastAPI"]
    BE --> DB[("db<br/>Postgres + pgvector")]
    BE -->|"OpenAI-compatible API"| LLM{{LLM endpoint}}
    BE -->|"OpenAI-compatible API"| EMB{{Embedding endpoint}}
    LLM -.->|online| OR[OpenRouter]
    EMB -.->|online| OR
    LLM -.->|"offline profile"| VL["vllm-llm"]
    EMB -.->|"offline profile"| VE["vllm-embed"]
```

| Service | Role | Image |
|---|---|---|
| `db` | Stores provisions, embeddings, and index metadata. | Official pgvector Postgres image. |
| `backend` | API, pipeline, and the ingestion command. | Built from `backend/`. |
| `frontend` | Chat UI, session state, progress display. | Built from `frontend/`. |
| `migrate` | One-shot job that applies pending database migrations, then exits. | Same image as `backend`. |
| `db-test`, `backend-test`, `frontend-test` | Throwaway test database and test runners. Only in the `test` profile. | Pgvector image, and the `dev` build targets. |
| `vllm-llm` | Self-hosted LLM. Only in the `offline` profile. | Pinned vLLM OpenAI-compatible image. |
| `vllm-embed` | Self-hosted embedding model. Only in the `offline` profile. | Pinned vLLM OpenAI-compatible image. |

The LLM and embedding endpoints are selected independently by configuration, so any mix of hosted and self-hosted works.

## 3. Repository layout

```
.
├── Makefile                      # common operations, see section 11
├── docker-compose.yml
├── .env.example                  # online defaults
├── .env.offline.example          # overrides for the offline profile
├── postgres/
│   └── migrations/               # numbered, forward-only SQL: 0001_init.sql, 0002_...
├── corpus/
│   ├── manifest.yaml             # which documents and which provisions to index
│   └── raw/                      # EUR-Lex HTML (NL), with snapshot date
├── backend/
│   ├── Dockerfile                # targets: runtime, dev
│   ├── pyproject.toml
│   ├── src/app/
│   │   ├── config.py             # pydantic-settings
│   │   ├── schemas/              # api.py, llm.py, domain.py (Pydantic)
│   │   ├── providers/            # base.py (protocols), openai_compat.py, fakes.py
│   │   ├── ingestion/            # parsers/, chunker.py, headers.py, run.py
│   │   ├── store/                # db.py, repository.py, migrate.py
│   │   ├── pipeline/             # query.py, retrieve.py, select.py, resolve.py,
│   │   │                         # answer.py, prompts/, orchestrator.py
│   │   └── api/                  # main.py, routes.py, sse.py
│   └── tests/                    # unit/, db/, api/, live/
├── frontend/
│   ├── Dockerfile                # targets: runtime, dev
│   ├── pyproject.toml
│   ├── src/ui/                   # app.py, client.py, state.py, components.py
│   └── tests/
├── eval/                         # single package: run_eval.py, models, metrics,
│                                 # fakes, reliability, tuning, eval_questions.*,
│                                 # reports/; mounted into backend-test as /app/eval
└── docs/                         # REFERENCE.md, ARCHITECTURE.md
```

There is no `backend/src/eval` copy. Tests and `make eval` import the root `eval/` package via the `backend-test` mount and `PYTHONPATH=/app/src:/app`.

**Dependency rule:** `pipeline` imports only `schemas` and the protocols in `providers/base.py`. `api` wires concrete providers and the repository into the pipeline. `ingestion` and `pipeline` do not import each other.

## 4. Tooling

| Concern | Choice |
|---|---|
| Language and dependencies | Python 3.12 or newer, `uv`. |
| Backend framework | FastAPI, Pydantic v2. The same models define API contracts and structured LLM outputs. |
| Configuration | `pydantic-settings`, environment variables, `.env.example`. |
| Database access | `psycopg` 3, `pgvector-python`, plain SQL. No ORM. |
| Schema management | Plain SQL migrations in `postgres/migrations/`, applied by a small runner in the backend. Forward-only. |
| LLM and embedding clients | OpenAI Python SDK against OpenAI-compatible endpoints. |
| HTML parsing | BeautifulSoup with lxml. |
| Frontend HTTP | `httpx` with streaming. |
| Testing | `pytest`, `pytest-asyncio`, `respx`, a throwaway pgvector container (`db-test`) for database tests. |
| Linting and formatting | `ruff`. |
| Task runner | `make`, as a thin wrapper around `docker compose` and `pytest` in containers. |

## 5. Data model

Chunks are articles, annexes, and (for the Omnibus) recitals, per the chunking rules in `REFERENCE.md`. A chunk is one row. The schema is created by migrations (see below). The DDL shown here is the content of `postgres/migrations/0001_init.sql`.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE provisions (
    ref            text PRIMARY KEY,          -- 'AI-verordening:art_6', 'AI-verordening:art_4a',
                                              -- split parts: 'AVG:art_9#2'
    doc            text NOT NULL,             -- 'AI-verordening' | 'AVG' | 'CRA' | 'Omnibus'
    kind           text NOT NULL CHECK (kind IN ('article', 'recital', 'annex')),
    label          text NOT NULL,             -- '6', '4a', 'III'
    parent_ref     text NOT NULL,             -- ref without part suffix
    part_no        int  NOT NULL DEFAULT 1,
    part_count     int  NOT NULL DEFAULT 1,
    title          text,
    chapter        text,                      -- display line, e.g. 'Hoofdstuk III: AI-SYSTEMEN MET EEN HOOG RISICO'
    section        text,                      -- display line, e.g. 'Afdeling 1: Classificatie van ...'
    part_label     text,                      -- split provisions only, e.g. 'leden 3 tot en met 5'
    header         text NOT NULL,             -- full lineage header, part of embedded and displayed text
    body           text NOT NULL,             -- legal text, amendment markers stripped
    token_estimate int  NOT NULL,
    amended_by     text[] NOT NULL DEFAULT '{}',   -- e.g. {'Omnibus'}, from amendment markers (running state, see below)
    embedding      vector(2000) NOT NULL      -- fixed by this migration, must match EMBEDDING_DIMENSIONS
);
CREATE INDEX provisions_parent_idx ON provisions (parent_ref);

CREATE TABLE index_meta (
    id               boolean PRIMARY KEY DEFAULT true CHECK (id),   -- single row
    embedding_model  text NOT NULL,
    dimension        int  NOT NULL,
    serving_profile  text NOT NULL,
    corpus_snapshot  date NOT NULL,
    corpus_hash      text NOT NULL,
    ingested_at      timestamptz NOT NULL
);
```

- **No vector index.** With a few hundred rows, exact search is instant, exact, and deterministic. An HNSW index on a `vector(2000)` column can be added later as a migration.
- **Reference scheme.** `ref = {doc}:{anchor}`, using the EUR-Lex anchor as it appears in the HTML (`art_6`, `art_4a`, `anx_III`, `rct_40`). Lettered articles (`4a`, `75b`) are therefore ordinary refs.
- **Split provisions.** A part has its own row and the suffix `#n`. Looking up a parent ref returns all its parts in order.
- **Similarity** is cosine: `1 - (embedding <=> query)`. The threshold is applied to that value.
- **Embeddings are created from the header and body with the status line removed.** The stored header, including the status line, is what is shown to the LLM and the user. See `docs/EVAL_RESULTS.md`.

### Chunk header and body format

Every chunk starts with a header that gives its full lineage, from the document down to the most specific heading. The header is generated from structured fields, stored in `provisions.header`, prepended to the body for embedding, and shown to the LLM and the user. There is one line per level, and levels that do not exist for a provision are omitted.

| Line | Format | Present when |
|---|---|---|
| Document | `{short_name} ({long_name}), {identifier}` | Always. Values come from the manifest. |
| Chapter | `Hoofdstuk {numeral}: {title}` | The provision sits in a chapter. |
| Section | `Afdeling {n}: {title}` | The chapter has sections. |
| Provision | `Artikel {label}: {title}`, `Bijlage {numeral}: {title}`, or `Overweging ({n})` | Always. |
| Part | `Deel {k} van {n}: {range}` | Split provisions only. |
| Status | `Gewijzigd bij: {short_name} ({identifier})` | The provision contains text under an Omnibus amendment marker. |

**Rules:**

- **Labels and titles come from the source headings**, with whitespace normalized. `4 bis` and `75 quater` therefore appear as printed in the regulation. The words `Hoofdstuk`, `Afdeling`, `Artikel`, and `Bijlage` are generated by the builder, because the source varies in casing between documents (`HOOFDSTUK`, `Afdeling`, `AFDELING`).
- **Titles keep the source capitalization.** Chapter titles in the AI Act and the CRA are uppercase. Sentence-casing is possible later, but acronyms such as `AI` need care.
- **The part range** uses `lid` and `leden` for articles, `punt` and `punten` for annexes: `Deel 2 van 3: leden 3 tot en met 5`, or `Deel 3 van 3: lid 6`. If an annex is split under an internal heading (for example `Deel II` in CRA Annex I), that heading is added to the part line.
- **The ref is not part of the header.** It is stored separately and added by the prompt formatter (see `PROMPT_SPEC.md`).
- **Stored text** is `header + "\n\n" + body`, status line included. **Embedding input** drops lines that start with `Gewijzigd bij:`. On the eval set that line did not raise the vector-hit count (`docs/EVAL_RESULTS.md`).

**Real examples** (these are the golden tests for the header builder):

```
AI-verordening (verordening artificiële intelligentie), Verordening (EU) 2024/1689
Hoofdstuk III: AI-SYSTEMEN MET EEN HOOG RISICO
Afdeling 1: Classificatie van AI-systemen als AI-systemen met een hoog risico
Artikel 6: Classificatieregels voor AI-systemen met een hoog risico
Gewijzigd bij: Digitale omnibus inzake AI (Verordening (EU) 2026/1744)
```

```
AI-verordening (verordening artificiële intelligentie), Verordening (EU) 2024/1689
Hoofdstuk I: ALGEMENE BEPALINGEN
Artikel 4 bis: Verwerking van bijzondere categorieën persoonsgegevens met het oog op de opsporing en correctie van vooringenomenheid
Gewijzigd bij: Digitale omnibus inzake AI (Verordening (EU) 2026/1744)
```

```
AVG (algemene verordening gegevensbescherming), Verordening (EU) 2016/679
Hoofdstuk III: Rechten van de betrokkene
Afdeling 4: Recht van bezwaar en geautomatiseerde individuele besluitvorming
Artikel 22: Geautomatiseerde individuele besluitvorming, waaronder profilering
```

```
CRA (Verordening cyberweerbaarheid), Verordening (EU) 2024/2847
Hoofdstuk I: ALGEMENE BEPALINGEN
Artikel 12: AI-systemen met een hoog risico
```

```
AI-verordening (verordening artificiële intelligentie), Verordening (EU) 2024/1689
Bijlage III: In artikel 6, lid 2, bedoelde AI-systemen met een hoog risico
```

```
Omnibus (Digitale omnibus inzake AI), Verordening (EU) 2026/1744
Overweging (40)
```

```
Omnibus (Digitale omnibus inzake AI), Verordening (EU) 2026/1744
Artikel 4: Inwerkingtreding en toepassing
```

The part line is illustrated by a synthetic test case, since no real provision reaches the split limit:

```
AVG (algemene verordening gegevensbescherming), Verordening (EU) 2016/679
Hoofdstuk II: Beginselen
Artikel 9: Verwerking van bijzondere categorieën van persoonsgegevens
Deel 2 van 3: leden 3 tot en met 5
```

**Body format.** The body excludes the heading elements, since the header already carries them. Each numbered paragraph (`1.`, `2.`) and each list item (`a)`, `b)`) starts on its own line, so the structure survives and splitting at paragraph boundaries is possible.

**Amendment markers** appear in the consolidated texts in two forms: block markers as separate elements between paragraphs or articles (`▼B` original text, `▼M1` Omnibus, `▼C1` and `▼C2` corrigenda), and inline markers around a stretch of text (`►M1 ... ◄`). The parser must:

- Track the current marker as a **running state** while walking the document in order. A marker before an article element applies to everything after it until the next marker. Checking only for markers inside an article element misses whole articles: Article 4, Article 4 bis, Article 60 bis, and Articles 75 bis to 75 quater all start under `▼M1`, with the marker outside their elements.
- Record `amended_by = ['Omnibus']` for any provision with text under an `M1` marker. Corrigendum markers (`C1`, `C2`) are not amendments and do not set it.
- Strip all marker characters from the body. A unit test asserts that no marker character remains in any chunk of the real files.

### Migrations

- **Location:** `postgres/migrations/`, plain SQL files named `NNNN_description.sql` (for example `0001_init.sql`, `0002_add_feedback.sql`). Schema changes and reference data are migrations. Corpus content is not: it is loaded by ingestion.
- **Forward-only.** There are no down migrations in v1. A mistake is fixed by a new migration.
- **Runner:** a small module in the backend (`store/migrate.py`, command `migrate`). It creates `schema_migrations (version, checksum, applied_at)` if missing, then applies unapplied files in order, each in its own transaction, recording its checksum.
- **Immutability:** if an already applied file has changed, the runner stops with an error. Applied migrations are never edited.
- **When it runs:** the `migrate` compose service runs it before the backend starts. `make migrate` runs it by hand. `/health` reports unhealthy while migrations are pending.
- **Embedding dimension:** the vector column dimension is fixed in the migration. Changing the dimension or the embedding model means a new migration that recreates the column, followed by re-ingestion.
- **Adding one:** `make new-migration name=add_feedback` creates the next numbered file.
- **Tests:** the `db` suite covers applying to an empty database, re-running (idempotent), ordering, and checksum mismatch.

### Ingestion

Run with `make ingest`. `make ingest-reset` clears existing provisions first. Ingestion assumes the schema exists and does not create it.

1. Read `corpus/manifest.yaml`: documents, file names, parser type, and which provisions to include (this is where the Omnibus decision becomes one line of configuration).
2. **Parse** with a parser per HTML layout. The consolidated texts (AI Act, AVG, CRA) and the Omnibus use different markup, but share the element ids (`art_*`, `rct_*`, `anx_*`), which serve as common anchors. Parsers produce `Provision` objects: kind, label, title, chapter, body, and amendment markers.
3. **Clean**: track amendment markers as running state, record `amended_by`, strip every marker character, and normalize whitespace (see above).
4. **Chunk**: one chunk per article, annex, or recital. Split only above the limit, evenly at paragraph boundaries. Token counts use a conservative character-based estimate, since the limit is far above any real provision.
5. **Header**: build the lineage header as specified above.
6. **Embed** documents in batches through the embedding provider, then write provisions and `index_meta` in one transaction.
7. **Verify** that every vector has the configured dimension before committing.

**Manifest.** `corpus/manifest.yaml` lists the documents and what to index from each. The Omnibus decision is expressed here: its 47 recitals and Article 4 are indexed, and Articles 1 to 3 are not. Article 1 duplicates the consolidated AI Act and is about 19K tokens, and Articles 2 and 3 amend other regulations.

```yaml
snapshot: YYYY-MM-DD            # date the EUR-Lex files were downloaded
documents:
  - key: AI-verordening
    file: raw/2024-1689_AIACT.html
    parser: consolidated
    short_name: AI-verordening
    long_name: verordening artificiële intelligentie
    identifier: Verordening (EU) 2024/1689
    include: all
  - key: AVG
    file: raw/2016-679_GDPR.html
    parser: consolidated
    short_name: AVG
    long_name: algemene verordening gegevensbescherming
    identifier: Verordening (EU) 2016/679
    include: all
  - key: CRA
    file: raw/2024-2847_CRA.html
    parser: consolidated
    short_name: CRA
    long_name: Verordening cyberweerbaarheid
    identifier: Verordening (EU) 2024/2847
    include: all
  - key: Omnibus
    file: raw/2026-1744_Omnibus.html
    parser: oj
    short_name: Omnibus
    long_name: Digitale omnibus inzake AI
    identifier: Verordening (EU) 2026/1744
    include:
      recitals: all
      articles: [art_4]
```

The resulting corpus is 359 provisions.

## 6. Backend components

### Provider interfaces

```python
class EmbeddingClient(Protocol):
    model: str
    dimensions: int
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...   # applies the task instruction

class LLMClient(Protocol):
    async def complete(self, *, step: str, messages: list[Message],
                       schema: type[T]) -> LLMResult[T]: ...     # validated Pydantic object + usage
```

- `OpenAICompatibleEmbeddings` sends the `dimensions` parameter and verifies the length of what comes back. `embed_query` prefixes the model's task instruction, `embed_documents` does not.
- `OpenAICompatibleLLM` requests JSON-schema structured output, validates with Pydantic, and retries up to `LLM_MAX_RETRIES` on invalid output. The live reliability run kept that budget at 1 (`docs/EVAL_RESULTS.md`).
- **Reasoning is a per-step setting.** `ANSWER_REASONING_EFFORT` is `medium`, and `SELECTION_REASONING_EFFORT` is a separate setting. The pipeline only sees the effort level. The adapter translates it into the provider's request format: OpenRouter's reasoning parameter for the hosted endpoint, and the model's chat-template option for vLLM. The exact mappings are to be verified per provider. Reasoning content returned by the model is neither shown nor stored, only the final content is parsed, and reasoning tokens are counted in `usage`.
- `fakes.py` provides a deterministic fake embedder and a scripted fake LLM that returns queued responses, so pipeline tests need no network.

### Pipeline

The pipeline is a set of small functions behind one orchestrator. Each step is testable on its own.

| Step | Module | Responsibility |
|---|---|---|
| Build query | `query.py` | Turns the conversation into the retrieval query (see [open items](#13-open-items)). |
| Retrieve | `retrieve.py` | Embeds the query, runs vector search, applies top-k (10) and the similarity threshold. |
| Select (call 1) | `select.py` | Prompt, `SelectionResult` schema, validation that keep and discard refer to retrieved provisions. |
| Resolve | `resolve.py` | Exact lookup of requested provisions, deduplication, cap, single round, unavailable list. |
| Answer (call 2) | `answer.py` | Prompt, `AnswerResult` schema, citation validation, situation update. |
| Orchestrate | `orchestrator.py` | An async generator that runs the steps and yields events. |

The orchestrator yields events instead of returning a result. The API streams them, and tests collect them.

### Structured outputs

```python
class RequestedProvision(BaseModel):
    document: str
    kind: Literal["article", "annex", "recital"]
    label: str                      # '6', '4a', 'III'
    reason: str

class ExternalReference(BaseModel):
    citation: str                   # e.g. 'Verordening (EU) 2019/881, artikel 54'
    reason: str

class SelectionResult(BaseModel):
    keep: list[str]                 # refs from the retrieved set
    discard: list[str]              # refs from the retrieved set
    request: list[RequestedProvision]          # provisions of the four corpus documents
    external_references: list[ExternalReference]   # needed provisions of other legislation

class Situation(BaseModel):
    role: Literal["provider", "deployer", "importer", "distributor", "unknown"] = "unknown"
    domain: str | None = None
    notes: str | None = None

class AnswerResult(BaseModel):      # field order matters: reasoning comes first
    reasoning: str
    action: Literal["answer", "clarify", "cannot_answer"]
    answer: str | None
    clarifying_questions: list[str] # 0 when answering, 1 or 2 when clarifying
    citations: list[str]            # refs, must be in the final context
    situation: Situation
```

**Validation rules** (each has tests):

- Every ref in `keep` and `discard` belongs to the retrieved set.
- Every retrieved provision appears in exactly one of `keep` and `discard`.
- Every requested provision is resolved by exact lookup. A provision that is not indexed (for example Omnibus Articles 1 to 3) and every external reference is reported as unavailable, never dropped silently.
- Every citation is in the final context.
- `answer` requires an answer text and at least one citation. `clarify` requires one or two questions and no answer text. `cannot_answer` requires an explanation in the answer text and no clarifying questions. A `clarify` is not allowed when the last assistant message was already a clarifying question.

### Prompts

Prompts are files in `pipeline/prompts/`, loaded at startup, and follow the requirements in `PROMPT_SPEC.md`. Prompt builders are pure functions from inputs to messages, so they can be tested with golden files. They are written in English with an explicit instruction to answer in Dutch and to use the terminology of the provided text. This is a provisional choice, since instruction-following is typically more reliable in English. It is checked with the eval set.

## 7. Request flow

```mermaid
sequenceDiagram
    participant UI as Streamlit
    participant API as FastAPI
    participant EMB as Embedding endpoint
    participant DB as Postgres + pgvector
    participant LLM as LLM endpoint
    UI->>API: POST /v1/ask (messages, situation)
    API-->>UI: event status (searching)
    API->>EMB: embed_query
    API->>DB: top 10 by cosine, above threshold
    API-->>UI: event retrieved
    alt nothing above threshold
        API-->>UI: event final (cannot_answer)
    else
        API-->>UI: event status (selecting)
        API->>LLM: call 1, selection
        API->>DB: exact lookup of requested provisions
        API-->>UI: event selection
        alt final context empty
            API-->>UI: event final (cannot_answer)
        else
            API-->>UI: event status (answering)
            API->>LLM: call 2, reasoning and answer
            API-->>UI: event final
        end
    end
```

The API checks for client disconnection between steps and stops calling the LLM if the client has gone.

## 8. API contract

| Endpoint | Purpose |
|---|---|
| `GET /health` | Database reachable, index present, configured embedding model and dimension match `index_meta`. Returns the failing reason if not. |
| `GET /v1/corpus` | Documents, provision counts, snapshot date. Used for the UI footer. |
| `POST /v1/ask` | Runs the pipeline and streams events as Server-Sent Events. |

**Request** (`POST /v1/ask`): the full message history and the current `situation`. Each message has a `role` and `content`, and assistant messages also carry the `action` they took (`answer`, `clarify`, or `cannot_answer`), taken from the `final` event. The backend needs this to enforce that a clarifying question is never followed by another one. It stores nothing.

**Events** (`event:` name, JSON `data:`):

| Event | Payload |
|---|---|
| `status` | `step`: `searching`, `selecting`, or `answering`. |
| `retrieved` | Provisions found by vector search: `ref`, title, similarity. |
| `selection` | `kept`, `discarded`, `added`, and `unavailable` (referenced but not in the corpus). |
| `final` | `action` (`answer`, `clarify`, `cannot_answer`), answer text or clarifying questions, `citations` with the provision text for display, updated `situation`, `usage` (calls, tokens, prompt_versions), `corpus_snapshot`. |
| `error` | Error `code` and a short message. The UI maps codes to Dutch text. |

Responses use `Cache-Control: no-cache`. There is no reverse proxy in v1, so no further buffering concerns.

Health endpoint shape and documented error codes:
- `/health` returns 200 with the minimal healthy body:

  {"status":"ok"}

  When unhealthy it returns HTTP 503 with a short machine-friendly shape:

  {"status":"unhealthy","reason":"<code>","detail":"<short message>"}

  The documented `reason` codes are:
  - database_unreachable
  - pending_migrations
  - missing_index
  - embedding_mismatch
  - retrieval_failed
  - llm_invalid_output
  - selection_invalid
  - answer_invalid
  - provider_error
  - internal_error

## 9. Frontend

Streamlit, with no business logic beyond rendering and session state.

- **State** (`st.session_state`): message history, current situation, last response.
- **Progress:** `st.status` shows the steps as `status`, `retrieved`, and `selection` events arrive, including which provisions were found, kept, and added.
- **Answer:** the answer text with citations. Each cited provision appears in an expander showing its header and full text.
- **Clarification:** clarifying questions are shown as a normal assistant message. The user's next message answers them.
- **Situation panel:** shows "what I understand about your situation" with editable fields (role, domain, notes). The values are sent with every request.
- **Always visible:** the not-legal-advice disclaimer, the EU assumption, and the corpus snapshot date.
- **Client module:** `client.py` wraps the SSE stream, so the UI code only sees typed events.

## 10. Configuration

All configuration is environment variables. `.env.example` holds the online defaults and `.env.offline.example` the overrides for the offline profile. They are copied to `.env` and `.env.offline`, and `make up` and `make up-offline` select the right file.

| Variable | Online default | Notes |
|---|---|---|
| `LLM_BASE_URL` | OpenRouter API URL | Offline: `http://vllm-llm:8000/v1` |
| `LLM_API_KEY` | (secret) | Not needed offline. |
| `SELECTION_MODEL`, `ANSWER_MODEL` | `qwen/qwen3.8-27b` | One setting per step, same default. |
| `ANSWER_REASONING_EFFORT` | `medium` | Reasoning on for the final answer. |
| `SELECTION_REASONING_EFFORT` | `low` | Measured against `none` and `medium`. |
| `EMBEDDING_BASE_URL` | OpenRouter API URL | Offline: `http://vllm-embed:8000/v1` |
| `EMBEDDING_API_KEY` | (secret) | |
| `EMBEDDING_MODEL` | `qwen/qwen3-embedding-8b` | Offline: the name the vLLM server is started with. |
| `EMBEDDING_DIMENSIONS` | `2000` | Must match the index. |
| `EMBEDDING_BATCH_SIZE` | `100` | Practical batching size for provider requests. |
| `DATABASE_URL` | internal `db` service | |
| `RETRIEVAL_TOP_K` | `10` | |
| `SIMILARITY_THRESHOLD` | `0.5959` | Q09 falls below it; Q01–Q08 do not. |
| `MAX_ADDED_PROVISIONS` | `1` | Longest `via_reference` list in the eval set. |
| `SPLIT_TOKEN_LIMIT` | `30000` | |
| `PROMPT_TOKEN_BUDGET` | per profile | Lower-ranked chunks are dropped above it. Offline: derive from `LLM_MAX_MODEL_LEN` (about half); see `docs/OFFLINE.md`. |
| `RETRIEVAL_HISTORY_TURNS` | `5` | Number of most recent user messages used to form the retrieval query. |
| `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES` | `120`, `1` | |
| `SERVING_PROFILE` | `online` | Which serving profile to record in index_meta (`online` or `offline`). |

Compose-only variables for the `offline` profile (interpolated by Compose into the vLLM `command`; **not** in `app/config.py`):

| Variable | Example | Notes |
|---|---|---|
| `LLM_LOCAL_MODEL` | `Qwen/Qwen3.8-27B` | Hugging Face id for `vllm-llm --model`. |
| `EMBEDDING_LOCAL_MODEL` | `Qwen/Qwen3-Embedding-8B` | Hugging Face id for `vllm-embed --model`. |
| `LLM_MAX_MODEL_LEN` | `8192` | Passed as `--max-model-len` to `vllm-llm`. |
| `VLLM_LLM_EXTRA_ARGS` | (empty) | Extra CLI args (quantization, tensor parallel, …). Empty optional args vanish because the command is string-form. |
| `VLLM_EMBED_EXTRA_ARGS` | `--runner pooling` | Extra CLI args for the embedding server. |

## 11. Deployment

`make up` starts `db`, runs `migrate` to completion, then starts `backend` and `frontend`. `make up-offline` does the same with the `offline` profile, which adds the two vLLM services and uses `.env.offline`. Ingestion runs once per corpus or embedding change (`make ingest`).

Sketch of the relevant compose parts:

```yaml
services:
  db:
    image: pgvector/pgvector:<pinned tag>
    environment:
      POSTGRES_DB: compliance
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d compliance"]
  migrate:
    build: { context: ./backend, target: runtime }
    command: ["migrate"]
    env_file: ${ENV_FILE:-.env}
    depends_on: { db: { condition: service_healthy } }
    volumes: ["./postgres:/app/postgres:ro"]
  backend:
    build: { context: ./backend, target: runtime }
    env_file: ${ENV_FILE:-.env}
    depends_on: { migrate: { condition: service_completed_successfully } }
    volumes: ["./corpus:/app/corpus:ro", "./postgres:/app/postgres:ro"]
    ports: ["8000:8000"]
  frontend:
    build: { context: ./frontend, target: runtime }
    environment: { BACKEND_URL: http://backend:8000 }
    depends_on: [backend]
    ports: ["8501:8501"]
  vllm-llm:
    profiles: [offline]
    image: vllm/vllm-openai:v0.31.0
    # String-form command so empty optional args vanish.
    command: >-
      --model ${LLM_LOCAL_MODEL}
      --served-model-name ${SELECTION_MODEL}
      --max-model-len ${LLM_MAX_MODEL_LEN}
      ${VLLM_LLM_EXTRA_ARGS:-}
    volumes: [hf-cache:/root/.cache/huggingface]
    deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: all, capabilities: [gpu] }] } } }
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')\""]
      start_period: 600s
  vllm-embed:
    profiles: [offline]
    image: vllm/vllm-openai:v0.31.0
    command: >-
      --model ${EMBEDDING_LOCAL_MODEL}
      --served-model-name ${EMBEDDING_MODEL}
      ${VLLM_EMBED_EXTRA_ARGS:-}
    volumes: [hf-cache:/root/.cache/huggingface]
    deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: all, capabilities: [gpu] }] } } }
    healthcheck:
      test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')\""]
      start_period: 600s
  db-test:
    profiles: [test]
    image: pgvector/pgvector:<pinned tag>
    tmpfs: [/var/lib/postgresql/data]
    environment: { POSTGRES_DB: test, POSTGRES_USER: app, POSTGRES_PASSWORD: test }
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d test"]
  backend-test:
    profiles: [test]
    build: { context: ./backend, target: dev }
    environment:
      TEST_DATABASE_URL: "postgresql://app:test@db-test:5432/test"
      PYTHONPATH: /app/src:/app
    depends_on: { db-test: { condition: service_healthy } }
    volumes:
      ["./backend:/app", "./eval:/app/eval", "./postgres:/app/postgres:ro",
       "./corpus:/app/corpus:ro"]
volumes: { pgdata: {}, hf-cache: {} }
```

### Makefile

The Makefile in the repository root holds the common operations. Each target is a thin wrapper around `docker compose` or around `pytest` inside a container, with no logic of its own. `make` with no target prints this list.

| Target | Action |
|---|---|
| `make help` | List all targets with a one-line description. |
| `make build` | Build all images. |
| `make up` | Start the online stack: `db`, `migrate`, `backend`, `frontend`. |
| `make up-offline` | Start the same stack plus the vLLM services, using `.env.offline`. |
| `make down` | Stop all services. |
| `make clean` | Stop all services and delete volumes, including the database. |
| `make logs` | Follow the logs of all running services. |
| `make ps` | Show service status. |
| `make migrate` | Apply pending migrations. |
| `make new-migration name=<name>` | Create the next numbered migration file in `postgres/migrations/`. |
| `make ingest` | Run ingestion into the migrated database. |
| `make ingest-reset` | Clear existing provisions, then run ingestion. |
| `make psql` | Open a `psql` shell in the database. |
| `make test` | Run the unit, api, and db suites (no keys or GPUs needed). |
| `make test-unit`, `make test-api`, `make test-db`, `make test-frontend` | Run one suite. |
| `make test-live` | Run the opt-in suite against real providers. |
| `make eval` | Run the retrieval evaluation against the current index. |
| `make lint`, `make fmt` | Check or apply `ruff` formatting and lint rules. |

**Offline notes:** see `docs/OFFLINE.md` (hardware, quantization, maximum context length, `--served-model-name` alignment, pinned image tag, and verified/unverified flags). Summary:

- Quantization and maximum context length are vLLM arguments supplied through compose-only environment variables (`VLLM_*_EXTRA_ARGS`, `LLM_MAX_MODEL_LEN`).
- vLLM flags for embedding models, and for reduced (Matryoshka) output dimensions, differ between versions. Pin the version and verify the flags. The embedding dimension test catches a misconfiguration.
- An index is built and queried with the same serving setup. Switching profile means running ingestion again.

## 12. Testing

| Suite | Scope | Dependencies |
|---|---|---|
| `unit` | Parsers (against the real HTML files), chunker, headers, query building, selection and answer validation, resolve logic, config. | None. |
| `db` | Migrations (empty database, re-run, ordering, checksum mismatch). Repository: upsert, exact lookup by ref and parent ref, similarity search, `index_meta` check. | `db-test` container. |
| `api` | Endpoints and SSE events, with the pipeline running on fake providers. | None. |
| `live` | Real providers, hosted or self-hosted: embedding dimension, and structured-output reliability run with the configured reasoning settings. | Opt-in, needs keys or GPUs. |
| eval | Retrieval hit rate at two stages with the real index, on the Dutch eval set. | Real embeddings. |

### Eval runner

`make eval` runs `python -m eval.run_eval` inside `backend-test` (same pattern as `verify-providers`). The runtime `backend` service is not used. The database must be up and ingested; `.env` must exist. Useful flags:

| Flag | Effect |
|---|---|
| `--use-fakes` | Scripted fakes only; no keys or database required (still needs `.env` present for the Makefile). |
| `--question Q03` | Run a single eval question. |
| `--verbose` | Print every orchestrator event. |
| `--reports-dir DIR` | Report directory (default `eval/reports`). |

Reports are written to `eval/reports/<timestamp>.json`. Each report has `generated_at`, a `summary` block (totals and hit/behavior rates over questions with a non-empty `must` set), and `items` with: `id`, `expected_behavior`, `actual_action`, `behavior_match`, `vector_hit`, `selection_hit`, `llm_call_count`, token counts, and `latency_seconds`. Example: `make eval ARGS="--question Q03 --verbose"`.

No new settings were added for the eval runner; the `.env` examples are unchanged.

Fixtures: a deterministic fake embedder, a scripted fake LLM, and a small test corpus in a throwaway database. Golden tests use real provisions from the corpus, for example `art_4a` (lettered article), `art_6` (amendment markers between paragraphs), and Omnibus Article 1 (excluded or oversized, depending on the manifest).

### Build order

The detailed task breakdown, with acceptance criteria per task, is in `IMPLEMENTATION_PLAN.md`. This is the summary.

| Priority | Steps |
|---|---|
| Core | 0. Compose skeleton, Makefile, and the `test` profile, so every later step runs in containers. 1. Parser, cleaner, chunker, headers, manifest. 2. Migrations, store, and repository. 3. Provider interfaces, fakes, and OpenAI-compatible adapters. 4. Pipeline steps and orchestrator. 5. API with SSE. 6. Streamlit UI. 7. README. |
| Next | 8. Eval runner and threshold tuning. 9. Structured-output reliability test. |
| Last | 10. Offline profile: compose services, configuration, documentation. |

The offline profile is last on purpose. It is configuration and documentation rather than code, and it needs GPU hardware to test.

## 13. Open items

- **Retrieval query for follow-ups.** Vector search on "and if we are the deployer?" finds nothing useful. v1 forms the query from the last five user messages (`RETRIEVAL_HISTORY_TURNS=5`). The risk is the opposite one: after a change of topic within a session, older questions dilute the query. The eval set is single-turn for now, so this behavior is covered by unit tests of the query builder only, and the two risks stay untested end to end.
- **Reasoning settings.** Decided: `low` for selection and `medium` for the final answer (`docs/EVAL_RESULTS.md`). Still open: the vLLM parameter mapping, and whether the explicit `reasoning` field in `AnswerResult` is still needed now that native reasoning is on, or is kept only as a short visible rationale.
- **Prompt language** (English with Dutch output, provisional), checked against the eval set.
- **Logging of user input.** Questions may contain confidential system descriptions, so logs record request ids, step timings, and token counts, and message content only at debug level.
- **Embedding task instruction** wording, and its exact format per the model card.
- **vLLM version and flags** for both self-hosted models.
