\"\"\"Pydantic models for eval files and reports.\"\"\"
from __future__ import annotations
from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class EvalQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    question: str
    expected_behavior: str
    must: List[str] = Field(default_factory=list)
    optional: List[str] = Field(default_factory=list)
    via_reference: List[str] = Field(default_factory=list)


class EvalFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: List[EvalQuestion]


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
    items: List[EvalReportItem]
    summary: dict

