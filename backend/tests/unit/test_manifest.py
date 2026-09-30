"""Unit tests for the corpus manifest loader and include filters."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.errors import MissingCorpusFile
from app.ingestion.manifest import (
    DocumentInclude,
    DocumentSpec,
    load_indexed_provisions,
    load_manifest,
    select_provisions,
)
from app.ingestion.parsers.oj import parse_oj

CORPUS = Path("/app/corpus")
MANIFEST_PATH = CORPUS / "manifest.yaml"
OMNIBUS = CORPUS / "raw" / "2026-1744_Omnibus.html"


def _write_manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.unit
def test_manifest_loads_real_corpus() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    assert manifest.snapshot.isoformat() == "2026-08-11"
    assert len(manifest.documents) == 4
    by_key = {doc.key: doc for doc in manifest.documents}
    assert by_key["AI-verordening"].parser == "consolidated"
    assert by_key["AI-verordening"].include == "all"
    assert by_key["AVG"].short_name == "AVG"
    assert by_key["CRA"].identifier == "Verordening (EU) 2024/2847"
    omnibus = by_key["Omnibus"]
    assert omnibus.parser == "oj"
    assert omnibus.short_name == "Omnibus"
    assert omnibus.long_name == "Digitale omnibus inzake AI"
    assert omnibus.identifier == "Verordening (EU) 2026/1744"
    assert isinstance(omnibus.include, DocumentInclude)
    assert omnibus.include.recitals == "all"
    assert omnibus.include.articles == ["art_4"]
    assert omnibus.include.annexes is None


@pytest.mark.unit
def test_manifest_rejects_missing_file(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        """
snapshot: 2026-08-11
documents:
  - key: Omnibus
    file: raw/does-not-exist.html
    parser: oj
    short_name: Omnibus
    long_name: Digitale omnibus inzake AI
    identifier: Verordening (EU) 2026/1744
    include: all
""",
    )
    with pytest.raises(MissingCorpusFile):
        load_manifest(path)


@pytest.mark.unit
def test_manifest_rejects_unknown_parser() -> None:
    with pytest.raises(ValidationError):
        DocumentSpec.model_validate(
            {
                "key": "Omnibus",
                "file": "raw/2026-1744_Omnibus.html",
                "parser": "unknown",
                "short_name": "Omnibus",
                "long_name": "Digitale omnibus inzake AI",
                "identifier": "Verordening (EU) 2026/1744",
                "include": "all",
            }
        )


@pytest.mark.unit
def test_manifest_rejects_malformed_include() -> None:
    with pytest.raises(ValidationError):
        DocumentInclude.model_validate({"articles": "sometimes"})
    with pytest.raises(ValidationError):
        DocumentInclude.model_validate({"articles": 42})
    with pytest.raises(ValidationError):
        DocumentInclude.model_validate({})
    with pytest.raises(ValidationError):
        DocumentInclude.model_validate({"articles": []})


@pytest.mark.unit
def test_manifest_omnibus_include_keeps_48_provisions() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    omnibus = next(doc for doc in manifest.documents if doc.key == "Omnibus")
    parsed = parse_oj(OMNIBUS.read_text(encoding="utf-8"))
    assert len(parsed) == 51
    selected = select_provisions(parsed, omnibus.include)
    assert len(selected) == 48
    assert sum(1 for p in selected if p.kind == "recital") == 47
    assert [p.anchor for p in selected if p.kind == "article"] == ["art_4"]


@pytest.mark.unit
def test_manifest_filtered_corpus_has_359_unique_refs() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    indexed = load_indexed_provisions(manifest, CORPUS)
    assert len(indexed) == 359
    refs = [f"{doc.key}:{provision.anchor}" for doc, provision in indexed]
    assert len(refs) == len(set(refs))
    by_doc: dict[str, int] = {}
    for doc, _provision in indexed:
        by_doc[doc.key] = by_doc.get(doc.key, 0) + 1
    assert by_doc == {
        "AI-verordening": 133,
        "AVG": 99,
        "CRA": 79,
        "Omnibus": 48,
    }
