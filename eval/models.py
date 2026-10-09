# Pydantic models for eval files and reports (backend copy).
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    question: str
    expected_behavior: str
    must: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    via_reference: list[str] = Field(default_factory=list)


class EvalFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[EvalQuestion]


class EvalReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    expected_behavior: str
    actual_action: str
    behavior_match: bool
    vector_hit: bool
    selection_hit: bool
    llm_call_count: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_seconds: float


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    items: list[EvalReportItem]
    summary: dict
