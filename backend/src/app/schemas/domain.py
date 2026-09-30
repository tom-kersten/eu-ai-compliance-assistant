"""Domain models for indexed and retrieved provisions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Document keys come from the corpus manifest, not a fixed enum.
DocumentName = Annotated[str, Field(min_length=1)]
ProvisionKind = Literal["article", "annex", "recital"]


class Provision(BaseModel):
    """One indexed provision row, without the embedding vector."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    doc: DocumentName
    kind: ProvisionKind
    label: str
    parent_ref: str
    part_no: int = 1
    part_count: int = 1
    title: str | None = None
    chapter: str | None = None
    section: str | None = None
    part_label: str | None = None
    header: str
    body: str
    token_estimate: int
    amended_by: list[str] = Field(default_factory=list)


class RetrievedProvision(Provision):
    """A provision returned by vector search, with cosine similarity."""

    similarity: float
