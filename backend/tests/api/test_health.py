"""Scaffold checks for the api suite."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.api
def test_health_returns_ok() -> None:
    from app.api.main import create_app

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
