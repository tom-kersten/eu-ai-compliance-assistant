"""Unit tests for lineage header building."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import UnknownAmendment
from app.ingestion.headers import build_header, embedded_text
from app.ingestion.manifest import DocumentSpec, load_indexed_provisions, load_manifest
from app.ingestion.models import ParsedProvision

CORPUS = Path("/app/corpus")
MANIFEST_PATH = CORPUS / "manifest.yaml"
GOLDEN = Path("/app/tests/golden/headers")


def _docs_by_key() -> dict[str, DocumentSpec]:
    return {doc.key: doc for doc in load_manifest(MANIFEST_PATH).documents}


def _provision(anchor: str, doc_key: str) -> tuple[DocumentSpec, ParsedProvision]:
    items = load_indexed_provisions(load_manifest(MANIFEST_PATH), CORPUS)
    for doc, provision in items:
        if doc.key == doc_key and provision.anchor == anchor:
            return doc, provision
    msg = f"provision not found: {doc_key}:{anchor}"
    raise AssertionError(msg)


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8").rstrip("\n")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("doc_key", "anchor", "golden_name"),
    [
        ("AI-verordening", "art_6", "ai_act_art_6.txt"),
        ("AI-verordening", "art_4a", "ai_act_art_4a.txt"),
        ("AVG", "art_22", "avg_art_22.txt"),
        ("CRA", "art_12", "cra_art_12.txt"),
        ("AI-verordening", "anx_III", "ai_act_anx_III.txt"),
        ("Omnibus", "rct_40", "omnibus_rct_40.txt"),
        ("Omnibus", "art_4", "omnibus_art_4.txt"),
    ],
)
def test_header_builder_matches_golden_examples(
    doc_key: str, anchor: str, golden_name: str
) -> None:
    doc, provision = _provision(anchor, doc_key)
    header = build_header(provision, doc, documents_by_key=_docs_by_key())
    assert header == _golden(golden_name)


@pytest.mark.unit
def test_header_status_line_only_when_amended() -> None:
    docs = _docs_by_key()
    amended_doc, amended = _provision("art_6", "AI-verordening")
    plain_doc, plain = _provision("art_22", "AVG")
    amended_header = build_header(amended, amended_doc, documents_by_key=docs)
    plain_header = build_header(plain, plain_doc, documents_by_key=docs)
    status = "Gewijzigd bij: Digitale omnibus inzake AI (Verordening (EU) 2026/1744)"
    assert status in amended_header.splitlines()
    assert status not in plain_header.splitlines()
    assert amended.amended_by == ["Omnibus"]
    assert plain.amended_by == []


@pytest.mark.unit
def test_header_synthetic_part_line_for_avg_article_9() -> None:
    doc, provision = _provision("art_9", "AVG")
    header = build_header(
        provision,
        doc,
        part_no=2,
        part_count=3,
        part_label="leden 3 tot en met 5",
        documents_by_key=_docs_by_key(),
    )
    expected = (
        "AVG (algemene verordening gegevensbescherming), Verordening (EU) 2016/679\n"
        "Hoofdstuk II: Beginselen\n"
        "Artikel 9: Verwerking van bijzondere categorieën van persoonsgegevens\n"
        "Deel 2 van 3: leden 3 tot en met 5"
    )
    assert header == expected
    assert "Gewijzigd bij:" not in header


@pytest.mark.unit
def test_header_annex_part_uses_punten_and_internal_heading() -> None:
    doc, provision = _provision("anx_I", "CRA")
    header = build_header(
        provision,
        doc,
        part_no=2,
        part_count=3,
        part_label=(
            "punten 1 tot en met 2, "
            "Deel II Vereisten inzake de respons op kwetsbaarheden"
        ),
        documents_by_key=_docs_by_key(),
    )
    lines = header.splitlines()
    assert lines[0].startswith("CRA (")
    assert lines[1].startswith("Bijlage I:")
    assert lines[2] == (
        "Deel 2 van 3: punten 1 tot en met 2, "
        "Deel II Vereisten inzake de respons op kwetsbaarheden"
    )
    assert "Gewijzigd bij:" not in header


@pytest.mark.unit
def test_header_unknown_amendment_raises() -> None:
    doc, provision = _provision("art_12", "CRA")
    provision = provision.model_copy(update={"amended_by": ["UnknownLaw"]})
    with pytest.raises(UnknownAmendment):
        build_header(provision, doc, documents_by_key=_docs_by_key())


@pytest.mark.unit
def test_embedded_text_joins_header_and_body_with_blank_line() -> None:
    assert embedded_text("HEADER", "BODY") == "HEADER\n\nBODY"
