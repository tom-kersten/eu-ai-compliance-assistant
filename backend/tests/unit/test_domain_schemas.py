"""Unit tests for domain provision schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.domain import (
    DocumentCount,
    IndexMeta,
    Provision,
    RetrievedProvision,
    StoredProvision,
)


def _provision_kwargs() -> dict[str, object]:
    return {
        "ref": "AI-verordening:art_6",
        "doc": "AI-verordening",
        "kind": "article",
        "label": "6",
        "parent_ref": "AI-verordening:art_6",
        "header": "AI-verordening ...\nArtikel 6: ...",
        "body": "1. ...",
        "token_estimate": 120,
    }


def _index_meta_kwargs() -> dict[str, object]:
    return {
        "embedding_model": "qwen/qwen3-embedding-8b",
        "dimension": 2000,
        "serving_profile": "online",
        "corpus_snapshot": date(2026, 1, 15),
        "corpus_hash": "abc123",
        "ingested_at": datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
    }


@pytest.mark.unit
def test_provision_requires_core_fields() -> None:
    provision = Provision(**_provision_kwargs())
    assert provision.ref == "AI-verordening:art_6"
    assert provision.part_no == 1
    assert provision.amended_by == []


@pytest.mark.unit
def test_provision_rejects_illegal_kind() -> None:
    kwargs = _provision_kwargs()
    kwargs["kind"] = "chapter"
    with pytest.raises(ValidationError):
        Provision(**kwargs)


@pytest.mark.unit
def test_provision_accepts_additional_document_name() -> None:
    kwargs = _provision_kwargs()
    kwargs["doc"] = "DSA"
    kwargs["ref"] = "DSA:art_1"
    kwargs["parent_ref"] = "DSA:art_1"
    provision = Provision(**kwargs)
    assert provision.doc == "DSA"


@pytest.mark.unit
def test_provision_rejects_empty_doc() -> None:
    kwargs = _provision_kwargs()
    kwargs["doc"] = ""
    with pytest.raises(ValidationError):
        Provision(**kwargs)


@pytest.mark.unit
def test_provision_forbids_extra_fields() -> None:
    kwargs = _provision_kwargs()
    kwargs["embedding"] = [0.1, 0.2]
    with pytest.raises(ValidationError):
        Provision(**kwargs)


@pytest.mark.unit
def test_retrieved_provision_carries_similarity() -> None:
    retrieved = RetrievedProvision(**_provision_kwargs(), similarity=0.87)
    assert retrieved.similarity == 0.87
    assert retrieved.ref == "AI-verordening:art_6"


@pytest.mark.unit
def test_stored_provision_requires_embedding() -> None:
    with pytest.raises(ValidationError):
        StoredProvision(**_provision_kwargs())


@pytest.mark.unit
def test_stored_provision_carries_embedding() -> None:
    stored = StoredProvision(**_provision_kwargs(), embedding=[0.1, 0.2, 0.3])
    assert stored.embedding == [0.1, 0.2, 0.3]
    assert stored.ref == "AI-verordening:art_6"


@pytest.mark.unit
def test_stored_provision_forbids_extra_fields() -> None:
    kwargs = _provision_kwargs()
    kwargs["embedding"] = [0.1]
    kwargs["extra"] = "nope"
    with pytest.raises(ValidationError):
        StoredProvision(**kwargs)


@pytest.mark.unit
def test_index_meta_accepts_required_fields() -> None:
    meta = IndexMeta(**_index_meta_kwargs())
    assert meta.dimension == 2000
    assert meta.corpus_hash == "abc123"


@pytest.mark.unit
def test_index_meta_forbids_extra_fields() -> None:
    kwargs = _index_meta_kwargs()
    kwargs["extra"] = "nope"
    with pytest.raises(ValidationError):
        IndexMeta(**kwargs)


@pytest.mark.unit
def test_document_count_fields() -> None:
    count = DocumentCount(doc="AVG", provision_count=99)
    assert count.doc == "AVG"
    assert count.provision_count == 99


@pytest.mark.unit
def test_document_count_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DocumentCount(doc="AVG", provision_count=99, extra="nope")
