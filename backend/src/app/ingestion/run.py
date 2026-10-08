"""Ingestion entrypoint: parse, chunk, embed, and write the index."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import math
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.ingestion.chunker import chunk_indexed
from app.ingestion.headers import text_for_embedding
from app.ingestion.manifest import (
    CorpusManifest,
    load_indexed_provisions,
    load_manifest,
)
from app.ingestion.tokens import estimate_tokens
from app.providers.base import EmbeddingDimensionError
from app.providers.openai_compat import OpenRouterAdapter
from app.schemas.domain import DocumentCount, IndexMeta, StoredProvision
from app.store.db import create_pool
from app.store.repository import Repository

logger = logging.getLogger(__name__)

DEFAULT_CORPUS_DIR = Path("/app/corpus")


class Embedder(Protocol):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class IngestSummary(BaseModel):
    """Summary printed after a successful ingest run."""

    model_config = ConfigDict(extra="forbid")

    documents: list[DocumentCount]
    chunk_count: int
    batch_count: int
    estimated_tokens: int
    runtime_seconds: float


def corpus_hash(manifest_path: str | Path, manifest: CorpusManifest) -> str:
    """Return a stable sha256 over the manifest and its listed files.

    The manifest.yaml bytes are hashed first, then each listed file's bytes
    in manifest order. The manifest itself is included because include
    filters change which provisions are indexed without changing the raw
    HTML files.
    """
    path = Path(manifest_path)
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    base = path.parent
    for doc in manifest.documents:
        digest.update((base / doc.file).read_bytes())
    return digest.hexdigest()


async def ingest(
    *,
    settings: Settings,
    embedder: Embedder,
    conn: AsyncConnection,
    corpus_dir: str | Path,
    reset: bool = False,
) -> IngestSummary:
    """Parse, chunk, embed, and write provisions in one transaction.

    Embeddings are produced entirely in memory and every vector length is
    checked before any database write. A dimension mismatch raises
    EmbeddingDimensionError and leaves the database untouched. The optional
    truncate, upsert, and index_meta write share one transaction so any
    failure rolls them all back.
    """
    started = time.perf_counter()
    corpus_root = Path(corpus_dir)
    manifest_path = corpus_root / "manifest.yaml"
    manifest = load_manifest(manifest_path)
    items = load_indexed_provisions(manifest, corpus_root)
    chunks = chunk_indexed(items, manifest.documents, settings.split_token_limit)

    texts = [text_for_embedding(chunk.header, chunk.body) for chunk in chunks]
    batch_size = settings.embedding_batch_size
    batch_count = math.ceil(len(texts) / batch_size) if texts else 0
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        logger.debug("embedding batch size=%s offset=%s", len(batch), start)
        batch_vectors = await embedder.embed_documents(batch)
        vectors.extend(batch_vectors)

    expected_dim = settings.embedding_dimensions
    if len(vectors) != len(chunks):
        msg = f"embedder returned {len(vectors)} vectors for {len(chunks)} chunks"
        raise EmbeddingDimensionError(msg)
    for index, vector in enumerate(vectors):
        if len(vector) != expected_dim:
            msg = f"vector {index} has dimension {len(vector)}, expected {expected_dim}"
            raise EmbeddingDimensionError(msg)

    hash_value = corpus_hash(manifest_path, manifest)
    stored = [
        StoredProvision(**chunk.model_dump(), embedding=vector)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    repo = Repository(conn)
    async with conn.transaction():
        if reset:
            await repo.truncate_provisions()
        await repo.upsert_provisions(stored)
        await repo.write_index_meta(
            IndexMeta(
                embedding_model=settings.embedding_model,
                dimension=settings.embedding_dimensions,
                serving_profile=settings.serving_profile,
                corpus_snapshot=manifest.snapshot,
                corpus_hash=hash_value,
                ingested_at=datetime.now(UTC),
            )
        )

    counts_by_doc: dict[str, int] = {}
    for chunk in chunks:
        counts_by_doc[chunk.doc] = counts_by_doc.get(chunk.doc, 0) + 1
    documents = [
        DocumentCount(doc=doc.key, provision_count=counts_by_doc.get(doc.key, 0))
        for doc in manifest.documents
    ]
    estimated = sum(estimate_tokens(text) for text in texts)
    runtime = time.perf_counter() - started
    return IngestSummary(
        documents=documents,
        chunk_count=len(chunks),
        batch_count=batch_count,
        estimated_tokens=estimated,
        runtime_seconds=runtime,
    )


def _print_summary(summary: IngestSummary) -> None:
    for doc in summary.documents:
        print(f"{doc.doc}: {doc.provision_count}")
    print(f"chunks: {summary.chunk_count}")
    print(f"batches: {summary.batch_count}")
    print(f"estimated_tokens: {summary.estimated_tokens}")
    print(f"runtime_seconds: {summary.runtime_seconds:.2f}")


async def _run(reset: bool) -> IngestSummary:
    settings = Settings()
    pool = create_pool(settings.database_url)
    await pool.open()
    embedder = OpenRouterAdapter(settings)
    try:
        async with pool.connection() as conn:
            return await ingest(
                settings=settings,
                embedder=embedder,
                conn=conn,
                corpus_dir=DEFAULT_CORPUS_DIR,
                reset=reset,
            )
    finally:
        await embedder.close()
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Only ``--reset`` is accepted."""
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="truncate existing provisions before writing",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        summary = asyncio.run(_run(reset=args.reset))
    except Exception:
        logger.exception("ingest failed")
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
