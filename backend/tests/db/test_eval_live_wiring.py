"""Live eval CLI must construct real Repository and OpenRouterAdapter."""

from __future__ import annotations

import concurrent.futures
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from psycopg import AsyncConnection

from app.providers.openai_compat import OpenRouterAdapter
from app.schemas.domain import IndexMeta
from app.store.migrate import migrate
from app.store.repository import Repository

from .conftest import MIGRATIONS_DIR

_DIM = 2000


@pytest.fixture
async def migrated_conn(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    await migrate(conn, MIGRATIONS_DIR)
    yield conn


@pytest.mark.db
async def test_live_main_constructs_repository_and_adapter(
    database_url: str,
    migrated_conn: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """main() without --use-fakes builds real deps before orchestrator.run."""
    repo = Repository(migrated_conn)
    await repo.write_index_meta(
        IndexMeta(
            embedding_model="qwen/qwen3-embedding-8b",
            dimension=_DIM,
            serving_profile="online",
            corpus_snapshot=date(2026, 1, 15),
            corpus_hash="eval-wiring",
            ingested_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
        )
    )
    # Commit so the pool connection opened by main() can see the row.
    await migrated_conn.commit()

    eval_file = tmp_path / "eval.json"
    eval_file.write_text(
        json.dumps(
            [
                {
                    "id": "Q09",
                    "question": "Wat is de hoofdstad van Frankrijk?",
                    "expected_behavior": "cannot_answer",
                    "must": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    reports_dir = tmp_path / "reports"

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EMBEDDING_API_KEY", "test-embed-key")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", str(_DIM))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        inputs = payload.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        embeddings = [{"embedding": [0.01] * _DIM} for _ in inputs]
        return httpx.Response(200, json={"data": embeddings})

    transport = httpx.MockTransport(handler)
    adapters: list[OpenRouterAdapter] = []

    class PatchedAdapter(OpenRouterAdapter):
        def __init__(self, settings) -> None:  # noqa: ANN001
            super().__init__(settings)
            self.client = httpx.AsyncClient(transport=transport)
            adapters.append(self)

    captured: dict[str, object] = {}

    import eval.run_eval as runner

    from app.pipeline import orchestrator as orch

    monkeypatch.setattr(runner, "OpenRouterAdapter", PatchedAdapter)

    real_run = orch.run

    async def wrapping_run(req, **kwargs):  # noqa: ANN001, ANN003
        captured.clear()
        captured.update(kwargs)
        async for event in real_run(req, **kwargs):
            yield event

    monkeypatch.setattr(runner.orch, "run", wrapping_run)

    def _call_main() -> None:
        runner.main(
            [
                "--eval-file",
                str(eval_file),
                "--reports-dir",
                str(reports_dir),
            ]
        )

    # main() uses asyncio.run; call it from a fresh thread.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_call_main).result(timeout=60)

    assert "repository" in captured
    assert isinstance(captured["repository"], Repository)
    assert isinstance(captured["embedder"], OpenRouterAdapter)
    assert isinstance(captured["llm"], OpenRouterAdapter)
    assert captured["embedder"] is captured["llm"]
    assert adapters, "OpenRouterAdapter was never constructed"
    assert captured["embedder"] is adapters[0]
    assert captured["documents"], "documents must come from the corpus manifest"
    assert all("key" in doc for doc in captured["documents"])  # type: ignore[union-attr]
    assert captured["snapshot"] == date(2026, 1, 15)

    files = list(reports_dir.iterdir())
    assert files, "report file not written"
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["items"][0]["id"] == "Q09"
    assert data["items"][0]["actual_action"] == "cannot_answer"
    assert data["items"][0]["llm_call_count"] == 0
