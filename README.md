What and why

This repository implements a Dutch-language Q&A assistant over four EU legal texts
(AI-verordening, AVG, CRA, Digitale omnibus inzake AI). It is a small, test-driven
proof-of-concept that demonstrates retrieval from a legal corpus, a two-step LLM
pipeline (selection + answer), and a Streamlit frontend for assessors.

Quickstart (online)

1. Copy the example env and set keys:

   cp .env.example .env
   # edit .env and set LLM_API_KEY and EMBEDDING_API_KEY

2. Start the online stack:

   make up

3. Ingest the corpus (once):

   make ingest

4. Open the frontend at http://localhost:8501 and the backend health at
   http://localhost:8000/health

5. Run evaluation and tests:

   make eval
   make test
   make lint

Quickstart (offline)

The offline profile uses self-hosted vLLM services and is not verified in this
repository. Copy and edit the offline env:

   cp .env.offline.example .env.offline
   # edit .env.offline to match your hardware and models

Then start:

   make up-offline

Note: running offline requires suitable GPU hardware and is covered in T20.

Architecture

Overview (simplified):

  Browser -> Streamlit frontend (8501)
       -> FastAPI backend (8000) -> Postgres + pgvector
       -> Embedding endpoint (hosted or vLLM)
       -> LLM endpoint (hosted or vLLM)

Design decisions and trade-offs

- Stateless backend; session state lives in the Streamlit frontend.
- Postgres with pgvector, exact cosine search, fixed embedding dimension (2000).
- Two LLM calls per question maximum: selection (one call) and answer (one call).
- Prompts written in English; UI and outputs in Dutch.
- No third-party orchestration frameworks; small, testable functions.

Eval results

See docs/EVAL_RESULTS.md and the latest report in eval/reports/ for the recorded
evaluation metrics and the configuration used. The README does not introduce new
numbers; it links to the canonical report files in docs/ and eval/reports/.

Known limitations

- Single-turn evaluation set only; multi-turn behavior is not fully validated.
- The retrieval threshold was tuned on a small eval set; some misses remain
  (notably Q06–Q08 retrieval gaps recorded in the eval reports).
- Offline (vLLM) profile is documented but unverified without GPU hardware.
- The corpus is not a consolidated single document; provenance and versioning
  are manual via the manifest.

Next steps at production scale

- Consolidate and version the legal texts; sign each snapshot.
- Add reranking or a hybrid sparse + dense retrieval layer.
- Multi-turn evaluation and user studies for clarifying questions.
- Persistence, authentication, and observability for production APIs.

Demo questions (Dutch, verbatim)

- Wat is het verschil tussen een aanbieder en een gebruiksverantwoordelijke volgens de AI-verordening?
- Moeten wij gebruikers laten weten dat ze met een chatbot praten?
- Is een AI-systeem dat sollicitaties filtert een AI-systeem met een hoog risico?
- Wij gebruiken AI om cv's te screenen. Wat moeten wij doen om aan de regels te voldoen?  (expected: clarify)
- Welke eisen stelt de Colorado AI Act aan bedrijven?  (expected: cannot_answer)

Test and eval commands

Use the Makefile targets:

- make test
- make eval
- make test-live

Evaluation reports are written to eval/reports/

