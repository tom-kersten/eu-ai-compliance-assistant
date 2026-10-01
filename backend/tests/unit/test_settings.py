"""Unit tests for typed application settings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

_SETTINGS_ENV_NAMES = {
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "SELECTION_MODEL",
    "ANSWER_MODEL",
    "ANSWER_REASONING_EFFORT",
    "SELECTION_REASONING_EFFORT",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "DATABASE_URL",
    "RETRIEVAL_TOP_K",
    "SIMILARITY_THRESHOLD",
    "MAX_ADDED_PROVISIONS",
    "SPLIT_TOKEN_LIMIT",
    "PROMPT_TOKEN_BUDGET",
    "RETRIEVAL_HISTORY_TURNS",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "SERVING_PROFILE",
}

_ENV_VAR_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _SETTINGS_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.unit
def test_settings_import_does_not_construct_instance() -> None:
    import app.config as config_module

    assert not hasattr(config_module, "settings")
    assert callable(config_module.Settings)


@pytest.mark.unit
def test_settings_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.llm_api_key == ""
    assert settings.selection_model == "qwen/qwen3.8-27b"
    assert settings.answer_model == "qwen/qwen3.8-27b"
    assert settings.answer_reasoning_effort == "medium"
    assert settings.selection_reasoning_effort is None
    assert settings.embedding_base_url == "https://openrouter.ai/api/v1"
    assert settings.embedding_api_key == ""
    assert settings.embedding_model == "qwen/qwen3-embedding-8b"
    assert settings.embedding_dimensions == 2000
    assert settings.database_url == "postgresql://app:app@db:5432/compliance"
    assert settings.retrieval_top_k == 10
    assert settings.similarity_threshold is None
    assert settings.max_added_provisions is None
    assert settings.split_token_limit == 30000
    assert settings.prompt_token_budget is None
    assert settings.retrieval_history_turns == 5
    assert settings.llm_timeout_seconds == 120
    assert settings.llm_max_retries == 1
    assert settings.serving_profile == "online"


@pytest.mark.unit
def test_settings_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_TOP_K", "7")
    settings = Settings(_env_file=None)
    assert settings.retrieval_top_k == 7


@pytest.mark.unit
def test_settings_loads_from_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("RETRIEVAL_TOP_K=3\nSIMILARITY_THRESHOLD=0.4\n")
    settings = Settings(_env_file=env_path)
    assert settings.retrieval_top_k == 3
    assert settings.similarity_threshold == 0.4


@pytest.mark.unit
def test_settings_environment_wins_over_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text("RETRIEVAL_TOP_K=3\n")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "9")
    settings = Settings(_env_file=env_path)
    assert settings.retrieval_top_k == 9


@pytest.mark.unit
def test_settings_does_not_load_env_example(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_settings_env(monkeypatch)
    example = tmp_path / ".env.example"
    example.write_text("RETRIEVAL_TOP_K=99\n")
    # Default lookup still starts from cwd; point env_file at a missing .env
    # so only process env and defaults apply, never .env.example.
    settings = Settings(_env_file=tmp_path / ".env")
    assert settings.retrieval_top_k == 10


@pytest.mark.unit
def test_settings_empty_optional_becomes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "")
    monkeypatch.setenv("MAX_ADDED_PROVISIONS", "")
    monkeypatch.setenv("PROMPT_TOKEN_BUDGET", "")
    monkeypatch.setenv("SELECTION_REASONING_EFFORT", "")
    settings = Settings(_env_file=None)
    assert settings.similarity_threshold is None
    assert settings.max_added_provisions is None
    assert settings.prompt_token_budget is None
    assert settings.selection_reasoning_effort is None


@pytest.mark.unit
def test_settings_rejects_non_positive_embedding_dimensions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.unit
def test_settings_rejects_similarity_threshold_outside_unit_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.unit
def test_settings_forbids_unknown_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, not_a_real_setting=1)  # type: ignore[call-arg]


@pytest.mark.unit
def test_settings_fields_listed_in_env_examples() -> None:
    example_paths = [
        Path("/env/.env.example"),
        Path("/env/.env.offline.example"),
    ]
    field_names = {name.upper() for name in Settings.model_fields}
    for path in example_paths:
        text = path.read_text()
        present = set(_ENV_VAR_LINE.findall(text))
        missing = field_names - present
        assert not missing, f"{path} missing Settings fields: {sorted(missing)}"
