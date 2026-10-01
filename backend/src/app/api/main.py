from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.api import routes


def create_app(
    settings: Any = None,
    *,
    providers: Any | None = None,
    repository_factory: Callable[..., Any] | None = None,
    health_check: Callable[..., Any] | None = None,
    corpus: Any | None = None,
) -> FastAPI:
    """
    Create and return a FastAPI app instance. Designed to be used as an
    application factory so startup side-effects are controlled by the lifespan.
    """

    app = FastAPI()

    # Attach injected collaborators for tests
    app.state.providers = providers
    app.state.repository_factory = repository_factory
    app.state.health_check = health_check
    app.state.settings = settings
    app.state.corpus = corpus

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        # Startup: create clients, pools, etc. Tests may inject fakes instead.
        yield
        # Shutdown: close pools/clients if present.

    app.router.lifespan_context = lifespan  # type: ignore[attr-defined]

    # Register routes from routes.py
    app.include_router(routes.router)

    return app
