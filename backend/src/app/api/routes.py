"""HTTP routes: /health, /v1/corpus, and POST /v1/ask (SSE)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.api.sse import stream_events
from app.config import Settings
from app.errors import AnswerInvalid, SelectionInvalid
from app.ingestion.manifest import CorpusManifest
from app.pipeline.orchestrator import run
from app.providers.base import EmbeddingDimensionError
from app.schemas.api import AskRequest, CorpusDocument, CorpusInfo, ErrorEvent
from app.store.health import HealthResult
from app.store.health import check as health_check_fn
from app.store.repository import Repository

logger = logging.getLogger(__name__)


def _bind_request_id(request: Request) -> None:
    """Re-bind the request id for logging inside handlers and stream bodies."""
    # Lazy import avoids a circular dependency with app.api.main.
    from app.api.main import _request_id_var

    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        _request_id_var.set(request_id)


router = APIRouter()


class HealthyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class UnhealthyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "unhealthy"
    reason: str
    detail: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


_ERROR_MESSAGES: dict[str, str] = {
    "database_unreachable": "database unreachable",
    "pending_migrations": "pending migrations",
    "missing_index": "index missing or empty",
    "embedding_mismatch": "embedding model or dimension mismatch",
    "selection_invalid": "selection output invalid",
    "answer_invalid": "answer output invalid",
    "provider_error": "provider error",
    "internal_error": "internal error",
}


def map_exception(exc: BaseException) -> tuple[str, str]:
    """Map an escaped domain/provider exception to (code, short message)."""
    if isinstance(exc, SelectionInvalid):
        return "selection_invalid", _ERROR_MESSAGES["selection_invalid"]
    if isinstance(exc, AnswerInvalid):
        return "answer_invalid", _ERROR_MESSAGES["answer_invalid"]
    if isinstance(
        exc,
        (httpx.HTTPError, TimeoutError, EmbeddingDimensionError),
    ):
        return "provider_error", _ERROR_MESSAGES["provider_error"]
    return "internal_error", _ERROR_MESSAGES["internal_error"]


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        settings = Settings()
        request.app.state.settings = settings
    return settings  # type: ignore[no-any-return]


def _documents_for_prompts(corpus: CorpusManifest | None) -> list[dict[str, str]]:
    if corpus is None:
        return []
    return [
        {
            "key": doc.key,
            "short_name": doc.short_name,
            "identifier": doc.identifier,
        }
        for doc in corpus.documents
    ]


async def _run_health(request: Request) -> HealthResult | None:
    """Live health check: injected callable, or real check over a connection."""
    injected: Callable[..., Any] | None = getattr(
        request.app.state, "health_check", None
    )
    if injected is not None:
        result = injected()
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[misc]
        return result  # type: ignore[no-any-return]

    factory = getattr(request.app.state, "repository_factory", None)
    if factory is None:
        return HealthResult(
            reason="database_unreachable",
            detail="database pool not available",
        )
    try:
        async with factory() as repo:
            conn = getattr(repo, "_conn", None)
            if conn is None:
                # Injected stub without a connection: treat as unreachable unless
                # tests also inject health_check (handled above).
                return HealthResult(
                    reason="database_unreachable",
                    detail="no database connection",
                )
            return await health_check_fn(conn, _settings(request))
    except Exception as exc:
        logger.exception("health check failed")
        return HealthResult(
            reason="database_unreachable",
            detail=str(exc)[:200] or "database unreachable",
        )


@router.get("/health")
async def health(request: Request) -> Any:
    _bind_request_id(request)
    result = await _run_health(request)
    if result is None:
        return HealthyBody().model_dump()
    return JSONResponse(
        status_code=503,
        content=UnhealthyBody(
            reason=result.reason,
            detail=result.detail,
        ).model_dump(),
    )


@router.get("/v1/corpus")
async def corpus(request: Request) -> Any:
    _bind_request_id(request)
    factory = getattr(request.app.state, "repository_factory", None)
    corpus_manifest: CorpusManifest | None = getattr(request.app.state, "corpus", None)
    if factory is None:
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="database_unreachable",
                message=_ERROR_MESSAGES["database_unreachable"],
            ).model_dump(),
        )
    if corpus_manifest is None:
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="missing_index",
                message=_ERROR_MESSAGES["missing_index"],
            ).model_dump(),
        )

    async with factory() as repo:
        meta = await repo.read_index_meta()
        if meta is None:
            return JSONResponse(
                status_code=503,
                content=ErrorBody(
                    code="missing_index",
                    message=_ERROR_MESSAGES["missing_index"],
                ).model_dump(),
            )
        counts = await repo.corpus_counts()
        counts_by_doc = {c.doc: c.provision_count for c in counts}
        documents = [
            CorpusDocument(
                key=doc.key,
                short_name=doc.short_name,
                identifier=doc.identifier,
                provision_count=counts_by_doc.get(doc.key, 0),
            )
            for doc in corpus_manifest.documents
        ]
        return CorpusInfo(
            documents=documents,
            snapshot_date=meta.corpus_snapshot,
        )


async def _ask_event_source(
    request: Request,
    body: AskRequest,
    *,
    repository: Repository | Any,
    snapshot: date,
) -> AsyncIterator[object]:
    """Run the orchestrator and map escaped exceptions to ErrorEvents."""
    providers = request.app.state.providers
    settings = _settings(request)
    corpus_manifest: CorpusManifest | None = request.app.state.corpus
    documents = _documents_for_prompts(corpus_manifest)

    logger.info(
        "ask start messages=%s",
        len(body.messages),
    )
    # Message content only at DEBUG.
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "ask content=%s",
            [m.model_dump() for m in body.messages],
        )

    try:
        async for event in run(
            body,
            settings=settings,
            embedder=providers.embedder,
            llm=providers.llm,
            repository=repository,
            documents=documents,
            snapshot=snapshot,
        ):
            yield event
            if isinstance(event, ErrorEvent):
                return
    except Exception as exc:
        code, message = map_exception(exc)
        logger.exception("ask failed code=%s", code)
        yield ErrorEvent(code=code, message=message)


@router.post("/v1/ask")
async def ask(request: Request, body: AskRequest) -> Any:
    # FastAPI already validated the body (422 on bad shape).
    _bind_request_id(request)
    result = await _run_health(request)
    if result is not None:
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code=result.reason,
                message=result.detail
                or _ERROR_MESSAGES.get(result.reason, result.reason),
            ).model_dump(),
        )

    factory = getattr(request.app.state, "repository_factory", None)
    if factory is None:
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="database_unreachable",
                message=_ERROR_MESSAGES["database_unreachable"],
            ).model_dump(),
        )

    providers = getattr(request.app.state, "providers", None)
    if providers is None:
        return JSONResponse(
            status_code=503,
            content=ErrorBody(
                code="provider_error",
                message=_ERROR_MESSAGES["provider_error"],
            ).model_dump(),
        )

    request_id = getattr(request.state, "request_id", None) or "-"

    async def event_stream() -> AsyncIterator[str]:
        _bind_request_id(request)
        async with factory() as repository:
            # Snapshot from index_meta when available; fall back for stubs.
            snapshot: date
            read_meta = getattr(repository, "read_index_meta", None)
            if read_meta is not None:
                meta = await read_meta()
                if meta is not None:
                    snapshot = meta.corpus_snapshot
                else:
                    corpus_manifest = request.app.state.corpus
                    snapshot = (
                        corpus_manifest.snapshot
                        if corpus_manifest is not None
                        else date.today()
                    )
            else:
                corpus_manifest = request.app.state.corpus
                snapshot = (
                    corpus_manifest.snapshot
                    if corpus_manifest is not None
                    else date.today()
                )

            source = _ask_event_source(
                request,
                body,
                repository=repository,
                snapshot=snapshot,
            )
            async for chunk in stream_events(request, source):
                yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Request-Id": str(request_id),
        },
    )
