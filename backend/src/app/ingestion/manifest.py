"""Corpus manifest: typed YAML, validation, and include filters."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.errors import MissingCorpusFile
from app.ingestion.models import ParsedProvision, ProvisionKind
from app.ingestion.parsers.consolidated import parse_consolidated

ParserName = Literal["consolidated", "oj"]
IncludeKindFilter = Annotated[
    Literal["all"] | list[str],
    Field(union_mode="left_to_right"),
]


class DocumentInclude(BaseModel):
    """Per-kind include filter. Omitted kinds are excluded."""

    model_config = ConfigDict(extra="forbid")

    articles: IncludeKindFilter | None = None
    recitals: IncludeKindFilter | None = None
    annexes: IncludeKindFilter | None = None

    @field_validator("articles", "recitals", "annexes", mode="before")
    @classmethod
    def _validate_kind_filter(cls, value: object) -> object:
        if value is None or value == "all":
            return value
        if isinstance(value, list):
            if not value:
                raise ValueError("include list must be non-empty")
            if not all(isinstance(item, str) and item for item in value):
                raise ValueError("include list must contain non-empty strings")
            return value
        raise ValueError("include value must be 'all' or a list of anchors")

    @model_validator(mode="after")
    def _require_at_least_one_kind(self) -> DocumentInclude:
        if self.articles is None and self.recitals is None and self.annexes is None:
            raise ValueError("include mapping must name at least one kind")
        return self


DocumentIncludeSpec = Annotated[
    Literal["all"] | DocumentInclude,
    Field(union_mode="left_to_right"),
]


class DocumentSpec(BaseModel):
    """One document entry from corpus/manifest.yaml."""

    model_config = ConfigDict(extra="forbid")

    key: str
    file: str
    parser: ParserName
    short_name: str
    long_name: str
    identifier: str
    include: DocumentIncludeSpec


class CorpusManifest(BaseModel):
    """Root of corpus/manifest.yaml."""

    model_config = ConfigDict(extra="forbid")

    snapshot: date
    documents: list[DocumentSpec]


def load_manifest(path: Path) -> CorpusManifest:
    """Load and validate a corpus manifest; require listed files to exist."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = CorpusManifest.model_validate(data)
    base = path.parent
    for doc in manifest.documents:
        file_path = (base / doc.file).resolve()
        if not file_path.is_file():
            raise MissingCorpusFile(str(base / doc.file))
    return manifest


def select_provisions(
    provisions: list[ParsedProvision],
    include: DocumentIncludeSpec,
) -> list[ParsedProvision]:
    """Apply an include filter to a parsed provision list."""
    if include == "all":
        return list(provisions)

    selected: list[ParsedProvision] = []
    for provision in provisions:
        if _is_included(provision, include):
            selected.append(provision)
    return selected


def _is_included(provision: ParsedProvision, include: DocumentInclude) -> bool:
    kind_filter = _filter_for_kind(provision.kind, include)
    if kind_filter is None:
        return False
    if kind_filter == "all":
        return True
    return provision.anchor in kind_filter


def _filter_for_kind(
    kind: ProvisionKind, include: DocumentInclude
) -> IncludeKindFilter | None:
    if kind == "article":
        return include.articles
    if kind == "recital":
        return include.recitals
    if kind == "annex":
        return include.annexes
    return None


def load_indexed_provisions(
    manifest: CorpusManifest, corpus_root: Path
) -> list[tuple[DocumentSpec, ParsedProvision]]:
    """Parse each document and return the filtered provisions with their docs."""
    from app.ingestion.parsers.oj import parse_oj

    results: list[tuple[DocumentSpec, ParsedProvision]] = []
    for doc in manifest.documents:
        html = (corpus_root / doc.file).read_text(encoding="utf-8")
        if doc.parser == "consolidated":
            parsed = parse_consolidated(html)
        else:
            parsed = parse_oj(html)
        for provision in select_provisions(parsed, doc.include):
            results.append((doc, provision))
    return results
