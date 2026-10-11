# EU AI Compliance Assistant: High-Level Reference (v1)

> Scope and decisions for v1 are fixed. Tuned values and deployment choices are listed in [section 14](#14-tuned-values-and-deployment-choices).
> This document covers *what* the system is and does. Architecture and implementation details belong in separate documents.

## 1. Purpose

A question-answering tool over a fixed set of EU legal texts. It helps companies that build or operate an AI application understand what the regulations require of them, with every answer grounded in and cited to the source text.

The tool explains and points to provisions. It does not make compliance decisions.

## 2. Target user and assumptions

**User:** a product owner, engineer, or compliance lead at a Dutch company with an AI application, in design or in production.

**Assumptions built into v1:**

- The user operates in the EU. Territorial scope is taken as given and stated in the UI. It is not assessed per question.
- The user is Dutch. The corpus, the interface, questions, answers, and clarifying questions are all in Dutch.
- Sessions are short: a handful of questions, then done.

## 3. Corpus

| Document | Identifier | Why it is included |
|---|---|---|
| Artificial Intelligence Act | Regulation (EU) 2024/1689 (CELEX 32024R1689) | Primary text. Risk tiers, roles, obligations, transparency, GPAI. |
| General Data Protection Regulation | Regulation (EU) 2016/679 (CELEX 32016R0679) | Personal data in AI systems. DPIAs, lawful basis, automated decisions. |
| Cyber Resilience Act | Regulation (EU) 2024/2847 (CELEX 32024R2847) | Cybersecurity requirements for products with digital elements. Overlaps with AI Act cybersecurity requirements for high-risk systems. |
| Digital Omnibus on AI | Regulation (EU) 2026/1744 (ELI `reg/2026/1744/oj`) | Amends the AI Act, notably application dates for high-risk obligations. |

**Corpus notes:**

- **Language: Dutch only.** The official Dutch (NL) versions are indexed, so retrieved text, terminology, and citations match what Dutch users read and cite. The EUR-Lex links collected so far point to the English versions. For the ingestion source, the language code in each URL changes (`EN` to `NL` in the CELEX links, `eng` to `nld` in the ELI link), which should be verified when the links are set up.
- Source: EUR-Lex HTML versions, in Dutch. The AI Act, GDPR (AVG), and CRA are EUR-Lex **consolidated texts**. The AI Act file is the consolidation of 27 July 2026, so it already contains the Omnibus amendments.
- **Consolidated texts contain no recitals.** Only the Omnibus file has recitals (47). The indexed corpus is 359 provisions (about 230K tokens): AI Act 119 articles and 14 annexes, AVG 99 articles, CRA 71 articles and 8 annexes, and from the Omnibus its 47 recitals and Article 4.
- **Amended text is marked in the AI Act file.** Original text is marked `▼B` and text inserted or changed by the Omnibus `▼M1`. The markers are not part of the legal text and are stripped from chunk text. Some markers sit between article elements, so ingestion has to track them as a running state. They can be kept as metadata ("amended by Omnibus").
- **Identifiers are not plain numbers.** The AI Act has lettered articles (`4 bis`, `60 bis`, `75 bis` to `75 quater`), and paragraphs with Latin suffixes (`1 bis`, `1 ter`, `1 quater`). The identifier scheme and exact lookup must handle them.
- The corpus is a dated snapshot. The snapshot date is recorded at ingestion and shown in the UI.
- **The Omnibus articles are amending instructions.** Article 1 (about 19K tokens) quotes all replacement text for the AI Act, Articles 2 and 3 amend other regulations, and Article 4 is the entry-into-force clause. The consolidated AI Act supersedes Articles 1 to 3. **Decision:** index the 47 recitals and Article 4, and leave out Articles 1 to 3. Article 1 duplicates the consolidated AI Act and would dominate the answer context, and Articles 2 and 3 amend other regulations.
- Recitals exist only for the Omnibus. They are indexed as a distinct chunk type, so they can be retrieved and cited but are distinguishable from operative articles.

## 4. What users ask

Questions are asked in Dutch. The table shows the type of question, with English glosses.

| Type | Example |
|---|---|
| Lookup | "What does Article 50 require?" |
| Obligations | "What must we do if we deploy an AI system for CV screening?" |
| Applicability | "Are we a provider or a deployer under the AI Act?" |
| Deadlines | "When do the high-risk obligations apply?" |
| Cross-law | "Do we need a DPIA for this?" / "How does the CRA relate to AI Act cybersecurity requirements?" |

## 5. v1 capabilities

1. **Grounded answers.** Plain-language answers in Dutch, based only on retrieved corpus text.
2. **Citations.** Every substantive claim cites its provision (article, paragraph, recital, or annex), and the UI shows the cited source text.
3. **Cross-document retrieval.** A single question can draw on several regulations.
4. **Reference-aware answers.** Provisions that the initially retrieved text depends on (for example an annex a classification rule points to) are identified and added before the answer is written.
5. **Role awareness.** Where obligations differ by role (provider, deployer, importer, distributor), the answer distinguishes them, using the terminology of the indexed text.
6. **Time awareness.** Where the Omnibus changes an answer (e.g. application dates), the answer says so.
7. **Clarifying questions.** See [section 7](#7-clarification-behavior).
8. **Honest refusal.** When retrieval is weak or the question is out of scope, the tool says so and describes what the corpus does cover. Provisions that are referenced but not in the corpus are named as gaps, not guessed at.
9. **Short multi-turn sessions.** Follow-up questions work within a session.

## 6. Non-goals for v1

- Determining whether the user's system is high-risk, or what their compliance status is. The tool explains criteria and cites provisions. The user applies them.
- Giving legal advice. A disclaimer is shown in the UI and reflected in the answer style.
- Covering anything outside the corpus: national implementing laws, harmonised standards, guidelines, case law, or general web knowledge.
- Analysing the user's own documents, code, or systems.
- Accounts, persistent sessions, or multi-tenancy.
- Monitoring legal changes or updating the corpus automatically.
- Languages other than Dutch.
- Keyword search, hybrid search, or reranking.
- Repeated or recursive reference lookup (v1 looks up references once).

## 7. Clarification behavior

The tool can ask the user for missing context instead of requiring it up front.

**Rules:**

- **Ask only when the answer forks.** If the relevant provisions point in materially different directions depending on role or domain, and the user hasn't said which applies, ask. Otherwise answer directly.
- **One round, at most two questions.** If the user doesn't know or doesn't answer, give a branched answer ("if you are the provider... if you are the deployer..."). Never block on missing information.
- **Retrieve first, then decide.** The decision to ask is made after retrieval and context selection, based on what the provisions contain, not on a generic habit.
- **Remember the answers.** Once stated, the user's situation (role, use-case domain, and similar) is kept as structured session context and not asked again.
- **Show the situation.** The UI displays "what I understand about your situation" and lets the user correct it.

**Shape:** the decision is part of the structured output of the answer step (see [section 9](#9-chunking-and-retrieval)): `answer` or `clarify`, together with the updated situation context.

## 8. Answer requirements

- Every substantive claim is traceable to a cited provision.
- Every cited provision was actually in the context given to the model. Citations to anything else are rejected.
- No claim without support in the retrieved text.
- Hedged, explanatory tone. Criteria and provisions, not verdicts.
- Answers touching amended provisions state that the Omnibus applies.
- Legal terms follow the indexed Dutch text rather than being translated from memory.
- The "I don't know" response is a first-class outcome, not a failure.

## 9. Chunking and retrieval

### Chunking

- The unit is the **article**. Articles are not split unless they do not fit.
- **"Fits"** means at most 30,000 tokens (the embedding model's context is 32K, leaving headroom for the header). An article over the limit is split **evenly**: at sub-article (paragraph) boundaries, into the fewest parts that each fit, with part sizes balanced. If a single paragraph alone exceeds the limit, it is split evenly at sentence boundaries.
- Recitals (Omnibus only) are one chunk each. Annexes follow the same rule as articles: whole unless they do not fit, then split by their internal structure.
- **Every chunk carries a header** in the chunk text, describing where it sits: document, chapter (and section where present), article number and title, and, for split provisions, the part number. The header is part of what is embedded and of what the model sees, so it is also counted toward the token limit. The exact format is specified in `ARCHITECTURE.md`.
- Each chunk also has metadata: document, chunk type (article, recital, annex), article and paragraph number, parent reference, and chapter. This supports exact lookup by identifier.

### Retrieval: two stages, two LLM calls

**Stage 1: vector search.**

1. The query is embedded and compared with chunk embeddings by vector similarity.
2. At most **10** chunks are returned, and only those above a **similarity threshold**. Less context is better, so the threshold is the main control and 10 is a ceiling, not a target.
3. If no chunk passes the threshold, the tool says it cannot answer and stops, without calling the LLM.
4. Whole provisions are always returned: a full article or sub-article, never a fragment.

**Stage 2: context selection and answer.**

1. **Call 1, selection.** The LLM receives the question, the session situation, and the provisions found by vector search. It decides which of them to **keep** and which to **discard**. It also identifies provisions that the kept text refers to and that are needed to answer (other articles, annexes, or provisions of other regulations in the corpus), and returns them as a list of additional provisions (document, article or annex, optional paragraph) with a short reason each. Keep, discard, and additional lists may each be empty.
2. **Resolution.** The backend resolves each requested provision by exact lookup on metadata, not by vector search. Duplicates of provisions already kept are dropped. Requests that do not exist in the corpus (including references to legislation that is not indexed) are not silently lost: they are passed on as "referenced but not available". Selection happens once, with no further rounds, and the number of added provisions is capped. The final context is the kept provisions plus the resolved additions.
3. **Call 2, reasoning and answer.** The LLM receives the question, the situation, the final context, and the list of unavailable references. Its structured output is ordered deliberately: first its **reasoning** over the provisions, then the decision (`answer`, `clarify`, or `cannot_answer` when the provisions do not cover the question), the answer with citations or the clarifying questions, and the updated situation context.
4. **Validation.** The backend validates the structured output and rejects citations to provisions that were not in the final context. Discarded provisions are not shown in the UI.

If call 1 leaves the final context empty (everything discarded and nothing to add), the tool says it cannot answer and skips call 2.

Each question that passes the threshold therefore costs two LLM calls. Each call is configured separately and defaults to the same model. A smaller model for the selection call is a possible later optimisation.

## 10. Technology and deployment

**Stack:** Streamlit (frontend), FastAPI (backend), PostgreSQL with pgvector (storage and retrieval), Docker Compose (one-command setup).

**Models and providers, switchable by configuration:**

| Component | Default (online) | Alternative (offline) |
|---|---|---|
| LLM | OpenRouter, `qwen/qwen3.8-27b` | Same model, self-hosted with vLLM in Docker (OpenAI-compatible server) |
| Embeddings | OpenRouter, `qwen/qwen3-embedding-8b` | Same model, self-hosted with vLLM in Docker (OpenAI-compatible server) |

Both models have open weights. The offline profile runs both locally with no outbound network calls. LLM and embedding providers are selected independently, so a mixed setup (for example hosted LLM with local embeddings) also works.

**Design consequences:**

- **One client interface per model type.** OpenRouter and vLLM both expose OpenAI-compatible APIs, so switching is a base URL, key, and model name change.
- **Model names are configuration, not code**, and each LLM step (selection, answer) has its own model setting.
- **Embedding dimension is 2000.** Qwen3-Embedding-8B is trained with Matryoshka Representation Learning (MRL), so its 4096-dimension output can be reduced. The dimension is set to 2000 through the `dimensions` parameter of the embeddings request. This sits exactly at pgvector's indexing limit for the standard `vector` type, so an index remains possible, though for a corpus of a few thousand chunks exact search is also adequate.
- **Embedding model identity is stored with the index.** The model name, dimension, and serving profile are recorded, and the backend fails fast on startup if the configuration doesn't match. A different embedding model requires re-ingestion.
- **Queries and documents are embedded differently.** Qwen3-Embedding is instruction-aware: queries are typically prefixed with a task instruction, documents are not. The embedding interface therefore has separate query and document paths.
- **The prompt budget is configured, not assumed.** The hosted LLM has a 1M-token context window on OpenRouter, but a self-hosted deployment will run with a much smaller maximum context than the model's nominal window because of memory limits. The maximum amount of retrieved text per call is therefore a setting with a per-profile default, and lower-ranked chunks are dropped when it would be exceeded.
- **Quantization is left to the deployer.** The offline profile exposes the relevant vLLM settings (model variant, quantization method, maximum context length) through configuration and documents the trade-offs, but prescribes no specific quantization. Because quantization changes vectors slightly, an index should be built and queried with the same serving setup. The recommended practice is to re-ingest when switching profile, and the eval set can confirm an existing index is still adequate.
- **The backend is stateless** (see next section).

## 11. Session handling

Streamlit holds the conversation history and the situation context in its session state and sends what is needed with each request. Nothing is persisted. Closing the session ends it.

## 12. Evaluation

- A small, hand-written set of **5 to 10 questions in Dutch**, each paired with the provisions that should be retrieved.
- Retrieval is measured at two points: **hit rate after vector search**, and **hit rate after context selection** (are the expected provisions in the final context, neither wrongly discarded nor missed by the reference lookup?). A few questions are chosen specifically because their answer depends on a referenced provision.
- The set includes a couple of clarification cases: questions where the system should ask, and questions where it should answer directly. Over-asking is the failure to watch.
- **Structured-output reliability test:** run both LLM calls repeatedly on fixed prompts and measure how often the output parses and validates, on both the hosted and the self-hosted LLM.
- **Embedding configuration check:** a test asserting that returned vectors have the configured dimension (2000), on both the hosted and the self-hosted embedding service.
- Generated answers vary between runs, so they are not asserted on exactly. LLM-as-judge evaluation is a noted future addition.

## 13. Development approach

Development is test-driven. No feature is considered done without tests written for it first.

| Layer | What the tests cover |
|---|---|
| Ingestion and parsing | Structure extraction, chunk boundaries, header content, the even-split rule (with a synthetic over-long article), metadata. |
| Retrieval, stage 1 | Eval-set hit rate against a fixed index. Threshold cutoff. The no-result path making no LLM calls. |
| Context selection, stage 2 | Keep and discard handling, exact lookup by identifier, deduplication, handling of references to provisions not in the corpus, the cap, single-round behavior, the empty-context path making no second call. |
| Provider abstraction | LLM and embedding providers behind interfaces, swappable for fakes. Separate query and document embedding paths. Configured dimension honored. |
| Answer logic | Decision behavior using a stubbed LLM, validation of malformed structured output, rejection of citations outside the context. |
| API | Request and response contracts, error handling, stateless behavior. |
| UI | Kept thin, with logic in the backend so it is testable there. |

Unit and API tests run against fake LLM and embedding providers, so they are deterministic and need no network. Tests against real providers (hosted or self-hosted) are a separate, opt-in suite.

## 14. Tuned values and deployment choices

Measured values for the similarity threshold (`0.5959`), the top-10 ceiling, the added-provision cap (`1`), selection reasoning (`low`), and the structured-output retry budget are recorded in `docs/EVAL_RESULTS.md`.

Quantization and the offline prompt budget are the deployer's choice. Options, defaults, and the budget rule are documented in `docs/OFFLINE.md`.

## 15. Extension points (designed for, not built)

- Guidance documents as additional corpus, for example the EDPB opinion on AI models and personal data. This needs PDF ingestion, since it is not available in structured HTML.
- A smaller model for the selection call.
- Further selection rounds, or deterministic reference extraction at ingestion.
- Omnibus amendment metadata: keeping the `▼M1` markers of the consolidated AI Act as "amended by Omnibus" metadata on provisions, so answers can say which text is new. Adding links to the Omnibus recitals that explain each change would build on this.
- Keyword or hybrid search, and reranking.
- Guided classification: a questionnaire walking through risk-tier logic.
- Obligations checklist by role and risk tier.
- Config-driven addition of new documents.
- Consolidated, versioned texts with effective dates.
- Persistent sessions and history.
- Additional languages.
- LLM-as-judge evaluation.
