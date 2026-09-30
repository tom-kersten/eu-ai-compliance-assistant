"""All provision and index_meta SQL. Callers own the transaction."""

from __future__ import annotations

from collections.abc import Sequence

from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.schemas.domain import (
    DocumentCount,
    IndexMeta,
    RetrievedProvision,
    StoredProvision,
)

_PROVISION_COLUMNS = """
    ref, doc, kind, label, parent_ref, part_no, part_count,
    title, chapter, section, part_label, header, body,
    token_estimate, amended_by, embedding
"""


def _row_to_stored(row: dict[str, object]) -> StoredProvision:
    embedding = row["embedding"]
    if isinstance(embedding, Vector):
        embedding_list = embedding.to_list()
    else:
        embedding_list = list(embedding)  # type: ignore[arg-type]
    return StoredProvision(
        ref=row["ref"],  # type: ignore[arg-type]
        doc=row["doc"],  # type: ignore[arg-type]
        kind=row["kind"],  # type: ignore[arg-type]
        label=row["label"],  # type: ignore[arg-type]
        parent_ref=row["parent_ref"],  # type: ignore[arg-type]
        part_no=row["part_no"],  # type: ignore[arg-type]
        part_count=row["part_count"],  # type: ignore[arg-type]
        title=row["title"],  # type: ignore[arg-type]
        chapter=row["chapter"],  # type: ignore[arg-type]
        section=row["section"],  # type: ignore[arg-type]
        part_label=row["part_label"],  # type: ignore[arg-type]
        header=row["header"],  # type: ignore[arg-type]
        body=row["body"],  # type: ignore[arg-type]
        token_estimate=row["token_estimate"],  # type: ignore[arg-type]
        amended_by=list(row["amended_by"] or []),  # type: ignore[arg-type]
        embedding=embedding_list,
    )


class Repository:
    """Async SQL access for provisions and index_meta."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._registered = False

    async def _ensure_vector(self) -> None:
        if not self._registered:
            await register_vector_async(self._conn)
            self._registered = True

    async def upsert_provisions(
        self,
        provisions: Sequence[StoredProvision],
    ) -> None:
        """Insert or replace provision rows. Does not commit."""
        if not provisions:
            return
        await self._ensure_vector()
        async with self._conn.cursor() as cur:
            for provision in provisions:
                await cur.execute(
                    """
                    INSERT INTO provisions (
                        ref, doc, kind, label, parent_ref, part_no, part_count,
                        title, chapter, section, part_label, header, body,
                        token_estimate, amended_by, embedding
                    ) VALUES (
                        %(ref)s, %(doc)s, %(kind)s, %(label)s, %(parent_ref)s,
                        %(part_no)s, %(part_count)s, %(title)s, %(chapter)s,
                        %(section)s, %(part_label)s, %(header)s, %(body)s,
                        %(token_estimate)s, %(amended_by)s, %(embedding)s
                    )
                    ON CONFLICT (ref) DO UPDATE SET
                        doc = EXCLUDED.doc,
                        kind = EXCLUDED.kind,
                        label = EXCLUDED.label,
                        parent_ref = EXCLUDED.parent_ref,
                        part_no = EXCLUDED.part_no,
                        part_count = EXCLUDED.part_count,
                        title = EXCLUDED.title,
                        chapter = EXCLUDED.chapter,
                        section = EXCLUDED.section,
                        part_label = EXCLUDED.part_label,
                        header = EXCLUDED.header,
                        body = EXCLUDED.body,
                        token_estimate = EXCLUDED.token_estimate,
                        amended_by = EXCLUDED.amended_by,
                        embedding = EXCLUDED.embedding
                    """,
                    {
                        "ref": provision.ref,
                        "doc": provision.doc,
                        "kind": provision.kind,
                        "label": provision.label,
                        "parent_ref": provision.parent_ref,
                        "part_no": provision.part_no,
                        "part_count": provision.part_count,
                        "title": provision.title,
                        "chapter": provision.chapter,
                        "section": provision.section,
                        "part_label": provision.part_label,
                        "header": provision.header,
                        "body": provision.body,
                        "token_estimate": provision.token_estimate,
                        "amended_by": provision.amended_by,
                        "embedding": Vector(provision.embedding),
                    },
                )

    async def get_by_refs(self, refs: Sequence[str]) -> list[StoredProvision]:
        """Return found provisions in the order of ``refs``. Missing refs omitted."""
        if not refs:
            return []
        await self._ensure_vector()
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT {_PROVISION_COLUMNS}
                FROM provisions
                WHERE ref = ANY(%s)
                """,
                (list(refs),),
            )
            rows = await cur.fetchall()
        by_ref = {row["ref"]: _row_to_stored(row) for row in rows}
        return [by_ref[ref] for ref in refs if ref in by_ref]

    async def get_by_parent_ref(self, parent_ref: str) -> list[StoredProvision]:
        """Return all parts of a parent provision, ordered by part_no."""
        await self._ensure_vector()
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT {_PROVISION_COLUMNS}
                FROM provisions
                WHERE parent_ref = %s
                ORDER BY part_no
                """,
                (parent_ref,),
            )
            rows = await cur.fetchall()
        return [_row_to_stored(row) for row in rows]

    async def truncate_provisions(self) -> None:
        """Remove all provision rows. Leaves index_meta untouched."""
        await self._conn.execute("TRUNCATE provisions")

    async def search_similar(
        self,
        query: Sequence[float],
        *,
        top_k: int,
        threshold: float,
    ) -> list[RetrievedProvision]:
        """Cosine similarity search: top-k above threshold."""
        await self._ensure_vector()
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT {_PROVISION_COLUMNS},
                       1 - (embedding <=> %(query)s) AS similarity
                FROM provisions
                WHERE 1 - (embedding <=> %(query)s) >= %(threshold)s
                ORDER BY embedding <=> %(query)s, ref
                LIMIT %(top_k)s
                """,
                {
                    "query": Vector(list(query)),
                    "threshold": threshold,
                    "top_k": top_k,
                },
            )
            rows = await cur.fetchall()
        results: list[RetrievedProvision] = []
        for row in rows:
            stored = _row_to_stored(row)
            results.append(
                RetrievedProvision(
                    **stored.model_dump(exclude={"embedding"}),
                    similarity=float(row["similarity"]),  # type: ignore[arg-type]
                )
            )
        return results

    async def write_index_meta(self, meta: IndexMeta) -> None:
        """Upsert the single index_meta row."""
        await self._conn.execute(
            """
            INSERT INTO index_meta (
                id, embedding_model, dimension, serving_profile,
                corpus_snapshot, corpus_hash, ingested_at
            ) VALUES (
                true, %(embedding_model)s, %(dimension)s, %(serving_profile)s,
                %(corpus_snapshot)s, %(corpus_hash)s, %(ingested_at)s
            )
            ON CONFLICT (id) DO UPDATE SET
                embedding_model = EXCLUDED.embedding_model,
                dimension = EXCLUDED.dimension,
                serving_profile = EXCLUDED.serving_profile,
                corpus_snapshot = EXCLUDED.corpus_snapshot,
                corpus_hash = EXCLUDED.corpus_hash,
                ingested_at = EXCLUDED.ingested_at
            """,
            {
                "embedding_model": meta.embedding_model,
                "dimension": meta.dimension,
                "serving_profile": meta.serving_profile,
                "corpus_snapshot": meta.corpus_snapshot,
                "corpus_hash": meta.corpus_hash,
                "ingested_at": meta.ingested_at,
            },
        )

    async def read_index_meta(self) -> IndexMeta | None:
        """Return the index_meta row, or None if empty."""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT embedding_model, dimension, serving_profile,
                       corpus_snapshot, corpus_hash, ingested_at
                FROM index_meta
                WHERE id = true
                """
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return IndexMeta(
            embedding_model=row["embedding_model"],
            dimension=row["dimension"],
            serving_profile=row["serving_profile"],
            corpus_snapshot=row["corpus_snapshot"],
            corpus_hash=row["corpus_hash"],
            ingested_at=row["ingested_at"],
        )

    async def corpus_counts(self) -> list[DocumentCount]:
        """Return provision counts grouped by document key."""
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT doc, count(*)::int AS provision_count
                FROM provisions
                GROUP BY doc
                ORDER BY doc
                """
            )
            rows = await cur.fetchall()
        return [
            DocumentCount(doc=row["doc"], provision_count=row["provision_count"])
            for row in rows
        ]
