"""Live checks for self-hosted vLLM endpoints (offline profile).

Opt-in via `make test-live`. Skips with a clear reason when unreachable.
Does not duplicate structured-output reliability from test_reliability.py.
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.config import Settings

pytestmark = pytest.mark.live


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def _embeddings_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/embeddings"


def _get_models(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(_models_url(base_url))
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or []
    return [item.get("id", "") for item in data if isinstance(item, dict)]


@pytest.mark.live
def test_offline_embedding_endpoint_dimension_and_served_name() -> None:
    settings = Settings(_env_file=None)
    base_url = settings.embedding_base_url
    if "vllm-embed" not in base_url and os.environ.get("SERVING_PROFILE") != "offline":
        pytest.skip("embedding base URL is not the offline vLLM embed service")
    timeout = float(settings.llm_timeout_seconds)
    try:
        with httpx.Client(timeout=timeout) as client:
            ids = _get_models(client, base_url)
            assert settings.embedding_model in ids, (
                f"served model {settings.embedding_model!r} not in {ids}"
            )
            response = client.post(
                _embeddings_url(base_url),
                headers=(
                    {"Authorization": f"Bearer {settings.embedding_api_key}"}
                    if settings.embedding_api_key
                    else {}
                ),
                json={
                    "model": settings.embedding_model,
                    "input": ["offline dimension probe"],
                    "dimensions": int(settings.embedding_dimensions),
                },
            )
            response.raise_for_status()
            vectors = response.json().get("data") or []
            assert vectors, "embeddings response had no data"
            length = len(vectors[0]["embedding"])
            assert length == int(settings.embedding_dimensions), (
                f"expected {settings.embedding_dimensions} dims, got {length}"
            )
    except httpx.HTTPError as exc:
        pytest.skip(f"offline embedding endpoint unreachable: {exc}")


@pytest.mark.live
def test_offline_llm_endpoint_served_name() -> None:
    settings = Settings(_env_file=None)
    base_url = settings.llm_base_url
    if "vllm-llm" not in base_url and os.environ.get("SERVING_PROFILE") != "offline":
        pytest.skip("LLM base URL is not the offline vLLM LLM service")
    timeout = float(settings.llm_timeout_seconds)
    try:
        with httpx.Client(timeout=timeout) as client:
            ids = _get_models(client, base_url)
            assert settings.selection_model in ids, (
                f"served model {settings.selection_model!r} not in {ids}"
            )
    except httpx.HTTPError as exc:
        pytest.skip(f"offline LLM endpoint unreachable: {exc}")
