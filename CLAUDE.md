@AGENTS.md

## Claude Code notes

Area-specific rules live in `.cursor/rules/*.mdc`. They are plain Markdown with a small header, so read the matching file before working in that area:

| Working in | Read |
|---|---|
| `backend/src/**` | `backend-python.mdc` |
| `backend/src/app/providers/**` | `providers.mdc` |
| `backend/src/app/ingestion/**`, `corpus/**` | `ingestion.mdc` |
| `backend/src/app/pipeline/**` | `pipeline.mdc` |
| `backend/src/app/pipeline/prompts/**` | `prompts.mdc` |
| `postgres/migrations/**` | `migrations.mdc` |
| `frontend/**` | `frontend-streamlit.mdc` |
| any `tests/` directory | `testing.mdc` |
| `docker-compose.yml`, `Makefile`, Dockerfiles, `.env*` | `docker.mdc` |

- Run tests and services through `make` targets. Do not run `pytest` on the host.
- When refining the implementation plan, and a task is unclear or conflicts with a document, propose a change to the plan or the document. Do not guess.
