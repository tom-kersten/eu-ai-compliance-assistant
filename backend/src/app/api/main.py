"""FastAPI application factory, lifespan, and request-id logging."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import routes
from app.config import Settings
from app.ingestion.manifest import load_manifest
from app.ingestion.run import DEFAULT_CORPUS_DIR
from app.providers.openai_compat import OpenRouterAdapter
from app.store.db import create_pool
from app.store.repository import Repository

logger = logging.getLogger(__name__)

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Accept only safe request ids: no whitespace or control characters, bounded length.
_REQUEST_ID_RE = re.compile(r"^[!-~]{1,128}$")

_log_factory_installed = False


def get_request_id() -> str:
    return _request_id_var.get()


def _install_request_id_log_factory() -> None:
    """Ensure every LogRecord carries request_id from the context var."""
    global _log_factory_installed
    if _log_factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = _request_id_var.get()  # type: ignore[attr-defined]
        return record

    logging.setLogRecordFactory(factory)
    _log_factory_installed = True

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(levelname)s request_id=%(request_id)s %(name)s %(message)s"
            )
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)


def _resolve_request_id(header_value: str | None) -> str:
    if header_value and _REQUEST_ID_RE.match(header_value):
        return header_value
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Pure ASGI middleware so the context var covers the full SSE body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        header_value: str | None = None
        for key, value in scope.get("headers") or []:
            if key == b"x-request-id":
                header_value = value.decode("latin-1")
                break
        request_id = _resolve_request_id(header_value)
        scope.setdefault("state", {})
        # Starlette Request.state is filled from scope["state"] when present.
        if not isinstance(scope.get("state"), dict):
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        token = _request_id_var.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            _request_id_var.reset(token)


def create_app(
    settings: Any = None,
    *,
    providers: Any | None = None,
    repository_factory: Callable[..., Any] | None = None,
    health_check: Callable[..., Any] | None = None,
    corpus: Any | None = None,
) -> FastAPI:
    """Create and return a FastAPI app. No module-level app instance."""
    _install_request_id_log_factory()

    resolved_settings = settings if settings is not None else Settings()
    app = FastAPI()
    app.state.settings = resolved_settings
    app.state.providers = providers
    app.state.repository_factory = repository_factory
    app.state.health_check = health_check
    app.state.corpus = corpus
    app.state.pool = None
    app.state._owns_pool = False
    app.state._owns_adapter = False
    app.state.adapter = None

    @asynccontextmanager
    async def lifespan(app_: FastAPI) -> AsyncGenerator[None, None]:
        settings_ = app_.state.settings
        assert isinstance(settings_, Settings)

        if app_.state.corpus is None:
            manifest_path = Path(DEFAULT_CORPUS_DIR) / "manifest.yaml"
            try:
                app_.state.corpus = load_manifest(manifest_path)
            except Exception:
                logger.exception("failed to load corpus manifest at startup")
                app_.state.corpus = None

        if app_.state.providers is None:
            adapter = OpenRouterAdapter(settings_)
            app_.state.adapter = adapter
            app_.state.providers = type(
                "Providers",
                (),
                {"embedder": adapter, "llm": adapter},
            )()
            app_.state._owns_adapter = True

        if app_.state.repository_factory is None:
            pool = create_pool(settings_.database_url)
            try:
                await pool.open()
                app_.state.pool = pool
                app_.state._owns_pool = True

                @asynccontextmanager
                async def pool_repository_factory() -> AsyncGenerator[Repository, None]:
                    async with pool.connection() as conn:
                        yield Repository(conn)

                app_.state.repository_factory = pool_repository_factory
            except Exception:
                logger.exception("failed to open database pool at startup")
                app_.state.pool = None
                try:
                    await pool.close()
                except Exception:
                    logger.debug("pool close after failed open", exc_info=True)

        try:
            yield
        finally:
            if app_.state._owns_pool and app_.state.pool is not None:
                try:
                    await app_.state.pool.close()
                except Exception:
                    logger.exception("error closing database pool")
                app_.state.pool = None
            if app_.state._owns_adapter and app_.state.adapter is not None:
                try:
                    await app_.state.adapter.close()
                except Exception:
                    logger.exception("error closing provider adapter")
                app_.state.adapter = None

    app.router.lifespan_context = lifespan  # type: ignore[attr-defined]
    app.add_middleware(RequestIdMiddleware)
    app.include_router(routes.router)
    return app
