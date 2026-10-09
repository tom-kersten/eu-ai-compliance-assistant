"""API tests for GET /health."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.store.health import HealthResult

from .conftest import make_health


@pytest.mark.api
def test_health_healthy_returns_ok_exactly() -> None:
    async def healthy() -> None:
        return None

    client = TestClient(create_app(Settings(), health_check=healthy))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.api
@pytest.mark.parametrize(
    "reason",
    [
        "database_unreachable",
        "pending_migrations",
        "missing_index",
        "embedding_mismatch",
    ],
)
def test_health_unhealthy_reason(reason: str) -> None:
    async def unhealthy() -> HealthResult:
        return make_health(reason, detail=f"{reason} detail")  # type: ignore[arg-type]

    client = TestClient(create_app(Settings(), health_check=unhealthy))
    response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body == {
        "status": "unhealthy",
        "reason": reason,
        "detail": f"{reason} detail",
    }
    assert body["detail"]


@pytest.mark.api
def test_health_recovers_after_check_flips() -> None:
    state: dict[str, HealthResult | None] = {
        "result": make_health("missing_index", detail="no index"),
    }

    async def check() -> HealthResult | None:
        return state["result"]

    app = create_app(Settings(), health_check=check)
    client = TestClient(app)

    first = client.get("/health")
    assert first.status_code == 503
    assert first.json()["reason"] == "missing_index"

    state["result"] = None
    second = client.get("/health")
    assert second.status_code == 200
    assert second.json() == {"status": "ok"}
