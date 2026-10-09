"""Offline env example: profile, dimensions, URLs, and compose-only vars."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

OFFLINE_ENV_PATH = Path("/env/.env.offline.example")

COMPOSE_ONLY_KEYS = (
    "LLM_LOCAL_MODEL",
    "EMBEDDING_LOCAL_MODEL",
    "LLM_MAX_MODEL_LEN",
    "VLLM_LLM_EXTRA_ARGS",
    "VLLM_EMBED_EXTRA_ARGS",
)


def _parse_env(path: Path) -> dict[str, str]:
    assert path.is_file(), f"missing {path}"
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def test_offline_env_profile_dimensions_and_base_urls() -> None:
    values = _parse_env(OFFLINE_ENV_PATH)
    assert values.get("SERVING_PROFILE") == "offline"
    assert values.get("EMBEDDING_DIMENSIONS") == "2000"
    assert values.get("LLM_BASE_URL") == "http://vllm-llm:8000/v1"
    assert values.get("EMBEDDING_BASE_URL") == "http://vllm-embed:8000/v1"


def test_offline_env_compose_only_vars_defined() -> None:
    values = _parse_env(OFFLINE_ENV_PATH)
    for key in COMPOSE_ONLY_KEYS:
        assert key in values, f"missing compose-only var {key}"
    assert values["LLM_LOCAL_MODEL"].strip()
    assert values["EMBEDDING_LOCAL_MODEL"].strip()
    assert values["LLM_MAX_MODEL_LEN"].strip()
    # Extra args may be empty for LLM; embed example includes --runner pooling.
    assert "VLLM_LLM_EXTRA_ARGS" in values
    assert values["VLLM_EMBED_EXTRA_ARGS"].strip()
