"""Live startup and request health checks against the database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from psycopg import AsyncConnection
from psycopg import Error as PsycopgError

from app.config import Settings
from app.store.migrate import DEFAULT_MIGRATIONS_DIR, pending_migrations
from app.store.repository import Repository

HealthReason = Literal[
    "database_unreachable",
    "pending_migrations",
    "missing_index",
    "embedding_mismatch",
]


@dataclass(frozen=True)
class HealthResult:
    """Unhealthy outcome. Healthy checks return None instead."""

    reason: HealthReason
    detail: str


async def check(conn: AsyncConnection, settings: Settings) -> HealthResult | None:
    """Return None when healthy, or a reason and short detail when not.

    Order: pending migrations first, then index presence, then embedding match.
    """
    try:
        pending = await pending_migrations(conn, DEFAULT_MIGRATIONS_DIR)
        if pending:
            return HealthResult(
                reason="pending_migrations",
                detail=f"pending migrations: {', '.join(pending)}",
            )

        repo = Repository(conn)
        meta = await repo.read_index_meta()
        counts = await repo.corpus_counts()
        total = sum(c.provision_count for c in counts)
        if meta is None or total == 0:
            return HealthResult(
                reason="missing_index",
                detail="index_meta missing or zero provisions",
            )

        if (
            meta.embedding_model != settings.embedding_model
            or meta.dimension != settings.embedding_dimensions
        ):
            return HealthResult(
                reason="embedding_mismatch",
                detail=(
                    f"index model={meta.embedding_model} dim={meta.dimension}; "
                    f"config model={settings.embedding_model} "
                    f"dim={settings.embedding_dimensions}"
                ),
            )
    except PsycopgError as exc:
        return HealthResult(
            reason="database_unreachable",
            detail=str(exc)[:200] or "database unreachable",
        )
    return None
