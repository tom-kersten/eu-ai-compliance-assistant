"""Unit tests for domain provision schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.domain import Provision, RetrievedProvision


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
