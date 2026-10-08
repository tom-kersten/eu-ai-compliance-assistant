"""Unit tests for corpus_hash and batched embedding during ingest."""

from __future__ import annotations

import math
import shutil
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.ingestion.chunker import chunk_indexed
from app.ingestion.headers import text_for_embedding
from app.ingestion.manifest import load_indexed_provisions, load_manifest
from app.ingestion.run import corpus_hash, ingest
from app.providers.fakes import FakeEmbedder

CORPUS = Path("/app/corpus")
MANIFEST_PATH = CORPUS / "manifest.yaml"


def _copy_corpus(tmp_path: Path) -> Path:
    """Copy the real corpus into tmp_path and return the copy root."""
    dest = tmp_path / "corpus"
    shutil.copytree(CORPUS, dest)
    return dest


@pytest.mark.unit
def test_corpus_hash_stable_across_two_calls(tmp_path: Path) -> None:
    corpus = _copy_corpus(tmp_path)
    manifest_path = corpus / "manifest.yaml"
    manifest = load_manifest(manifest_path)

    first = corpus_hash(str(manifest_path), manifest)
    second = corpus_hash(str(manifest_path), manifest)

    assert first == second
    assert len(first) == 64


@pytest.mark.unit
def test_corpus_hash_changes_when_raw_file_changes(tmp_path: Path) -> None:
    corpus = _copy_corpus(tmp_path)
    manifest_path = corpus / "manifest.yaml"
    manifest = load_manifest(manifest_path)
    before = corpus_hash(str(manifest_path), manifest)

    raw = corpus / manifest.documents[0].file
    raw.write_bytes(raw.read_bytes() + b"\n<!-- changed -->\n")

    after = corpus_hash(str(manifest_path), manifest)
    assert after != before


@pytest.mark.unit
def test_corpus_hash_changes_when_manifest_changes(tmp_path: Path) -> None:
    corpus = _copy_corpus(tmp_path)
    manifest_path = corpus / "manifest.yaml"
    manifest = load_manifest(manifest_path)
    before = corpus_hash(str(manifest_path), manifest)

    text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(text + "\n# comment\n", encoding="utf-8")
    after = corpus_hash(str(manifest_path), manifest)
    assert after != before


class _CountingFakeEmbedder(FakeEmbedder):
    """FakeEmbedder that records every embed_documents call."""

    def __init__(self, dimension: int = 2000) -> None:
        super().__init__(dimension=dimension)
        self.calls: list[list[str]] = []

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return await super().embed_documents(texts)


@pytest.mark.unit
async def test_ingest_batches_embeddings_preserving_order() -> None:
    settings = Settings(
        _env_file=None,
        embedding_batch_size=100,
        embedding_dimensions=8,
    )
    embedder = _CountingFakeEmbedder(dimension=settings.embedding_dimensions)
    manifest = load_manifest(MANIFEST_PATH)
    items = load_indexed_provisions(manifest, CORPUS)
    chunks = chunk_indexed(items, manifest.documents, settings.split_token_limit)
    expected_texts = [text_for_embedding(c.header, c.body) for c in chunks]
    expected_batches = math.ceil(len(chunks) / settings.embedding_batch_size)

    conn = MagicMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)

    with (
        patch("app.ingestion.run.Repository.upsert_provisions", new_callable=AsyncMock),
        patch("app.ingestion.run.Repository.write_index_meta", new_callable=AsyncMock),
        patch(
            "app.ingestion.run.Repository.truncate_provisions", new_callable=AsyncMock
        ),
        patch("app.ingestion.run.Repository._ensure_vector", new_callable=AsyncMock),
    ):
        summary = await ingest(
            settings=settings,
            embedder=embedder,
            conn=conn,
            corpus_dir=str(CORPUS),
            reset=False,
        )

    assert len(chunks) == 359
    assert len(embedder.calls) == expected_batches
    assert summary.chunk_count == 359
    assert summary.batch_count == expected_batches
    concatenated = [text for batch in embedder.calls for text in batch]
    assert concatenated == expected_texts
