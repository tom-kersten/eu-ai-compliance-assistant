# Thin wrappers around docker compose / pytest in containers.
# Prefer `make help` for the list of targets.

COMPOSE ?= docker compose
ENV_FILE ?= .env
PROFILE_TEST := --profile test

.DEFAULT_GOAL := help

.PHONY: help build up up-offline down clean logs ps migrate new-migration \
	ingest ingest-reset psql test test-unit test-api test-db test-frontend \
	test-live eval lint fmt verify-providers

help: ## List all targets with a one-line description
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} \
		/^[a-zA-Z0-9_-]+:.*##/ { printf "  %-18s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

build: ## Build all images
	$(COMPOSE) build

up: ## Start the online stack: db, migrate, backend, frontend
	@test -f .env || { echo "Missing .env. Copy .env.example to .env and fill secrets."; exit 1; }
	ENV_FILE=.env $(COMPOSE) --env-file .env up -d --build db migrate backend frontend

up-offline: ## Start the stack using .env.offline (vLLM services come in T20)
	@test -f .env.offline || { echo "Missing .env.offline. Copy .env.offline.example to .env.offline."; exit 1; }
	ENV_FILE=.env.offline $(COMPOSE) --env-file .env.offline up -d --build db migrate backend frontend

down: ## Stop all services
	$(COMPOSE) --profile test --profile offline down

clean: ## Stop all services and delete volumes, including the database
	$(COMPOSE) --profile test --profile offline down -v

logs: ## Follow the logs of all running services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Apply pending migrations
	@test -f .env || { echo "Missing .env. Copy .env.example to .env."; exit 1; }
	ENV_FILE=.env $(COMPOSE) --env-file .env run --rm migrate

new-migration: ## Create the next numbered migration file in postgres/migrations/
	@test -n "$(name)" || { echo "Usage: make new-migration name=<snake_case>"; exit 1; }
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps \
		-v "$(CURDIR)/postgres/migrations:/migrations:rw" \
		backend-test \
		python -m app.store.migrate new-migration "$(name)" --directory /migrations

ingest: ## Run ingestion into the migrated database
	@test -f .env || { echo "Missing .env. Copy .env.example to .env."; exit 1; }
	ENV_FILE=.env $(COMPOSE) --env-file .env run --rm backend ingest

ingest-reset: ## Clear existing provisions, then run ingestion
	@test -f .env || { echo "Missing .env. Copy .env.example to .env."; exit 1; }
	ENV_FILE=.env $(COMPOSE) --env-file .env run --rm backend ingest --reset

psql: ## Open a psql shell in the database
	@test -f .env || { echo "Missing .env. Copy .env.example to .env."; exit 1; }
	$(COMPOSE) --env-file .env exec db psql -U app -d compliance

test: ## Run the unit, api, and db suites (no keys or GPUs needed)
	$(COMPOSE) $(PROFILE_TEST) run --rm backend-test \
		pytest -m "unit or api or db"

test-unit: ## Run the unit suite
	$(COMPOSE) $(PROFILE_TEST) run --rm backend-test \
		pytest -m unit -o addopts=

test-api: ## Run the api suite
	$(COMPOSE) $(PROFILE_TEST) run --rm backend-test \
		pytest -m api -o addopts=

test-db: ## Run the db suite against db-test
	$(COMPOSE) $(PROFILE_TEST) run --rm backend-test \
		pytest -m db -o addopts=

test-frontend: ## Run the frontend suite
	$(COMPOSE) $(PROFILE_TEST) run --rm frontend-test pytest

test-live: ## Run the opt-in suite against real providers
	@test -f .env || { echo "Missing .env. Copy .env.example to .env and fill secrets."; exit 1; }
	set -a; . ./.env; set +a; \
	$(COMPOSE) $(PROFILE_TEST) run --rm \
		-e LLM_API_KEY -e EMBEDDING_API_KEY \
		-e LLM_BASE_URL -e EMBEDDING_BASE_URL \
		-e EMBEDDING_MODEL -e SELECTION_MODEL -e ANSWER_MODEL \
		-e EMBEDDING_DIMENSIONS -e LLM_TIMEOUT_SECONDS \
		-e ANSWER_REASONING_EFFORT -e SELECTION_REASONING_EFFORT \
		-e SIMILARITY_THRESHOLD -e MAX_ADDED_PROVISIONS -e RETRIEVAL_TOP_K \
		-e LLM_MAX_RETRIES \
		backend-test \
		pytest -m live -o addopts=

verify-providers: ## Probe OpenRouter and write PROVIDER_NOTES.md (needs keys)
	@test -f .env || { echo "Missing .env. Copy .env.example to .env and fill secrets."; exit 1; }
	set -a; . ./.env; set +a; \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps \
		-e LLM_API_KEY -e EMBEDDING_API_KEY \
		-e LLM_BASE_URL -e EMBEDDING_BASE_URL \
		-e EMBEDDING_MODEL -e SELECTION_MODEL -e ANSWER_MODEL \
		-e EMBEDDING_DIMENSIONS -e LLM_TIMEOUT_SECONDS \
		-v "$(CURDIR)/docs:/docs:rw" \
		-e PROVIDER_NOTES_PATH=/docs/PROVIDER_NOTES.md \
		-e PYTHONPATH=/app/src:/app \
		backend-test \
		python scripts/verify_providers.py

eval: ## Run the retrieval evaluation against the current index (needs T14)
	@echo "eval: not implemented until T14 (eval runner)."
	@exit 1

lint: ## Check ruff formatting and lint rules
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps backend-test \
		ruff check src tests scripts && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps backend-test \
		ruff format --check src tests scripts && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps frontend-test \
		ruff check src tests && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps frontend-test \
		ruff format --check src tests

fmt: ## Apply ruff formatting and lint fixes
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps backend-test \
		ruff check --fix src tests scripts && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps backend-test \
		ruff format src tests scripts && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps frontend-test \
		ruff check --fix src tests && \
	$(COMPOSE) $(PROFILE_TEST) run --rm --no-deps frontend-test \
		ruff format src tests
