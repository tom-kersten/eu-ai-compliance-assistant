"""Ingestion entrypoint and helpers (skeleton for T9 step 1)."""

from __future__ import annotations

from typing import Any


def corpus_hash(manifest_path: str, manifest: dict) -> str:
    """Return a stable sha256 over the manifest and the listed files.

    This is a minimal placeholder. The real implementation will hash the
    manifest bytes and then each listed file's bytes in manifest order.
    """
    raise NotImplementedError("corpus_hash not implemented yet")


class IngestSummary(dict):
    """Minimal placeholder for the real IngestSummary dataclass used later."""


async def ingest(
    *,
    settings: Any,
    embedder: Any,
    conn_or_pool: Any,
    corpus_dir: str,
    reset: bool = False,
) -> IngestSummary:
    """Placeholder async ingest function so imports resolve during testing.

    The real implementation will be added in later steps per the plan.
    """
    raise NotImplementedError("ingest not implemented yet")


def main() -> None:
    """CLI entrypoint placeholder."""
    raise NotImplementedError("ingest CLI not yet implemented")
