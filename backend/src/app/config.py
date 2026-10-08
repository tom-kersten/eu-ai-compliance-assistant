"""Typed application settings from the environment or a `.env` file."""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_str_to_none(value: object) -> object:
    if value == "":
        return None
    return value


EmptyAsNoneFloat = Annotated[float | None, BeforeValidator(_empty_str_to_none)]
EmptyAsNoneInt = Annotated[int | None, BeforeValidator(_empty_str_to_none)]
EmptyAsNoneStr = Annotated[str | None, BeforeValidator(_empty_str_to_none)]


class Settings(BaseSettings):
    """Runtime configuration. Construct explicitly; never at import time."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    selection_model: str = "qwen/qwen3.8-27b"
    answer_model: str = "qwen/qwen3.8-27b"
    answer_reasoning_effort: str = "medium"
    selection_reasoning_effort: EmptyAsNoneStr = "low"
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    embedding_api_key: str = ""
    embedding_model: str = "qwen/qwen3-embedding-8b"
    embedding_dimensions: Annotated[int, Field(gt=0)] = 2000
    embedding_batch_size: Annotated[int, Field(gt=0)] = 100
    database_url: str = "postgresql://app:app@db:5432/compliance"
    serving_profile: str = "online"
    retrieval_top_k: Annotated[int, Field(gt=0)] = 10
    similarity_threshold: EmptyAsNoneFloat = 0.5959
    max_added_provisions: EmptyAsNoneInt = 1
    split_token_limit: Annotated[int, Field(gt=0)] = 30000
    prompt_token_budget: EmptyAsNoneInt = None
    retrieval_history_turns: Annotated[int, Field(ge=0)] = 5
    llm_timeout_seconds: Annotated[int, Field(gt=0)] = 120
    llm_max_retries: Annotated[int, Field(ge=0)] = 1

    @field_validator("similarity_threshold")
    @classmethod
    def _similarity_in_unit_interval(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            msg = "similarity_threshold must be between 0 and 1"
            raise ValueError(msg)
        return value

    @field_validator("max_added_provisions", "prompt_token_budget")
    @classmethod
    def _non_negative_optional_int(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            msg = "must be greater than or equal to 0"
            raise ValueError(msg)
        return value
