"""Models for parsed corpus provisions before chunking and indexing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProvisionKind = Literal["article", "annex", "recital"]


class ParsedProvision(BaseModel):
    """One provision extracted from a corpus HTML file."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    kind: ProvisionKind
    label: str
    title: str | None = None
    chapter_numeral: str | None = None
    chapter_title: str | None = None
    section_numeral: str | None = None
    section_title: str | None = None
    body: str = ""
    amended_by: list[str] = Field(default_factory=list)
