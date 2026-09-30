"""Unit tests for provision chunking and refs."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.errors import ChunkTooLarge
from app.ingestion.chunker import chunk_indexed, chunk_provision
from app.ingestion.headers import build_header, embedded_text
from app.ingestion.manifest import DocumentSpec, load_indexed_provisions, load_manifest
from app.ingestion.models import ParsedProvision
from app.ingestion.tokens import estimate_tokens
from app.schemas.domain import Provision

CORPUS = Path("/app/corpus")
MANIFEST_PATH = CORPUS / "manifest.yaml"


def _docs_by_key() -> dict[str, DocumentSpec]:
    return {doc.key: doc for doc in load_manifest(MANIFEST_PATH).documents}


def _avg_doc() -> DocumentSpec:
    return _docs_by_key()["AVG"]


def _ai_doc() -> DocumentSpec:
    return _docs_by_key()["AI-verordening"]


def _cra_doc() -> DocumentSpec:
    return _docs_by_key()["CRA"]


def _article(
    *,
    anchor: str = "art_9",
    label: str = "9",
    title: str = "Verwerking van bijzondere categorieën van persoonsgegevens",
    body: str,
    chapter_numeral: str = "II",
    chapter_title: str = "Beginselen",
) -> ParsedProvision:
    return ParsedProvision(
        anchor=anchor,
        kind="article",
        label=label,
        title=title,
        chapter_numeral=chapter_numeral,
        chapter_title=chapter_title,
        body=body,
    )


def _annex(
    *,
    anchor: str = "anx_I",
    label: str = "I",
    title: str = "ESSENTIËLE CYBERBEVEILIGINGSVEREISTEN",
    body: str,
) -> ParsedProvision:
    return ParsedProvision(
        anchor=anchor,
        kind="annex",
        label=label,
        title=title,
        body=body,
    )


def _pad_paragraph(number: int, token_budget: int) -> str:
    """Build 'N. ' + filler so the paragraph alone is about token_budget tokens."""
    prefix = f"{number}. "
    # estimate_tokens uses ceil(len/3); aim for roughly token_budget.
    target_len = token_budget * 3 - len(prefix)
    filler = ("woord " * ((target_len // 6) + 1))[: max(target_len, 0)]
    return prefix + filler


@pytest.mark.unit
def test_chunker_no_split_when_under_limit() -> None:
    provision = _article(body="1. Kort.\n2. Ook kort.")
    chunks = chunk_provision(
        provision,
        _avg_doc(),
        token_limit=30000,
        documents_by_key=_docs_by_key(),
    )
    assert len(chunks) == 1
    assert chunks[0].part_count == 1
    assert chunks[0].part_no == 1
    assert chunks[0].part_label is None
    assert chunks[0].ref == "AVG:art_9"
    assert chunks[0].parent_ref == "AVG:art_9"


@pytest.mark.unit
def test_chunker_splits_when_one_token_over_limit() -> None:
    # Two equal paragraphs; together with header just over a small limit.
    docs = _docs_by_key()
    doc = _avg_doc()
    body = "1. " + ("abc" * 40) + "\n2. " + ("def" * 40)
    provision = _article(body=body)
    full_header = build_header(provision, doc, documents_by_key=docs)
    full_tokens = estimate_tokens(embedded_text(full_header, body))
    assert full_tokens > 1

    # Under the full size: must split.
    chunks = chunk_provision(
        provision,
        doc,
        token_limit=full_tokens - 1,
        documents_by_key=docs,
    )
    assert len(chunks) == 2
    assert all(c.part_count == 2 for c in chunks)
    assert chunks[0].part_no == 1
    assert chunks[1].part_no == 2
    assert chunks[0].ref == "AVG:art_9#1"
    assert chunks[1].ref == "AVG:art_9#2"
    assert chunks[0].parent_ref == "AVG:art_9"
    assert "Deel 1 van 2:" in chunks[0].header
    assert "Deel 2 van 2:" in chunks[1].header
    for chunk in chunks:
        assert chunk.token_estimate <= full_tokens - 1


@pytest.mark.unit
def test_chunker_balances_equal_paragraphs_into_two_and_two() -> None:
    docs = _docs_by_key()
    doc = _avg_doc()
    # Four equal paragraphs that need exactly two parts of two.
    paras = [_pad_paragraph(i, 50) for i in range(1, 5)]
    body = "\n".join(paras)
    provision = _article(body=body)
    base_header = build_header(provision, doc, documents_by_key=docs)
    # Limit: one part of two paragraphs fits; three does not.
    two_body = "\n".join(paras[:2])
    three_body = "\n".join(paras[:3])
    # Account for part line growing the header.
    header_two = build_header(
        provision,
        doc,
        part_no=1,
        part_count=2,
        part_label="leden 1 tot en met 2",
        documents_by_key=docs,
    )
    two_tokens = estimate_tokens(embedded_text(header_two, two_body))
    header_three = build_header(
        provision,
        doc,
        part_no=1,
        part_count=2,
        part_label="leden 1 tot en met 3",
        documents_by_key=docs,
    )
    three_tokens = estimate_tokens(embedded_text(header_three, three_body))
    # Choose limit between two-para and three-para sizes.
    token_limit = (two_tokens + three_tokens) // 2
    if token_limit < two_tokens:
        token_limit = two_tokens
    if token_limit >= three_tokens:
        token_limit = three_tokens - 1
    assert estimate_tokens(embedded_text(base_header, body)) > token_limit

    chunks = chunk_provision(
        provision, doc, token_limit=token_limit, documents_by_key=docs
    )
    assert len(chunks) == 2
    assert chunks[0].part_label == "leden 1 tot en met 2"
    assert chunks[1].part_label == "leden 3 tot en met 4"
    assert chunks[0].body == two_body
    assert chunks[1].body == "\n".join(paras[2:])


@pytest.mark.unit
def test_chunker_counts_header_toward_limit() -> None:
    docs = _docs_by_key()
    doc = _avg_doc()
    # Long equal paragraphs: body alone fits a limit that header+body does not.
    para = ("woord " * 200).strip()
    body = f"1. {para}\n2. {para}"
    provision = _article(body=body)
    body_tokens = estimate_tokens(body)
    full_header = build_header(provision, doc, documents_by_key=docs)
    full_tokens = estimate_tokens(embedded_text(full_header, body))
    assert body_tokens < full_tokens

    part_header = build_header(
        provision,
        doc,
        part_no=1,
        part_count=99,
        part_label="lid 1",
        documents_by_key=docs,
    )
    one_para_tokens = estimate_tokens(embedded_text(part_header, f"1. {para}"))
    # Limit: each single paragraph with its part header fits; whole does not.
    token_limit = max(body_tokens + 1, one_para_tokens)
    assert token_limit < full_tokens
    assert one_para_tokens <= token_limit

    chunks = chunk_provision(
        provision, doc, token_limit=token_limit, documents_by_key=docs
    )
    assert len(chunks) >= 2


@pytest.mark.unit
def test_chunker_keeps_list_items_with_paragraph() -> None:
    docs = _docs_by_key()
    doc = _avg_doc()
    body = (
        "1. Lead text.\n"
        "a) first item that is long enough " + ("woord " * 80) + "\n"
        "b) second item " + ("woord " * 80) + "\n"
        "2. " + ("woord " * 120)
    )
    provision = _article(body=body)
    part1_body = (
        "1. Lead text.\n"
        "a) first item that is long enough " + ("woord " * 80) + "\n"
        "b) second item " + ("woord " * 80)
    )
    part_header = build_header(
        provision,
        doc,
        part_no=1,
        part_count=99,
        part_label="lid 1",
        documents_by_key=docs,
    )
    token_limit = estimate_tokens(embedded_text(part_header, part1_body))
    full_header = build_header(provision, doc, documents_by_key=docs)
    assert estimate_tokens(embedded_text(full_header, body)) > token_limit

    chunks = chunk_provision(
        provision,
        doc,
        token_limit=token_limit,
        documents_by_key=docs,
    )
    lead_chunk = next(c for c in chunks if c.body.startswith("1. Lead"))
    assert "a) first item" in lead_chunk.body
    assert "b) second item" in lead_chunk.body
    assert not any(line.startswith("2. ") for line in lead_chunk.body.splitlines())


@pytest.mark.unit
def test_chunker_splits_overlong_paragraph_at_sentences() -> None:
    docs = _docs_by_key()
    doc = _avg_doc()
    sentences = [
        f"Dit is zin nummer {i} met voldoende tekst erin." for i in range(1, 21)
    ]
    body = "1. " + " ".join(sentences)
    provision = _article(body=body)
    # Limit fits a few sentences with a part header, but not the whole paragraph.
    sample_header = build_header(
        provision,
        doc,
        part_no=1,
        part_count=10,
        part_label="lid 1",
        documents_by_key=docs,
    )
    three = "1. " + " ".join(sentences[:3])
    token_limit = estimate_tokens(embedded_text(sample_header, three))
    whole_header = build_header(provision, doc, documents_by_key=docs)
    assert estimate_tokens(embedded_text(whole_header, body)) > token_limit

    chunks = chunk_provision(
        provision, doc, token_limit=token_limit, documents_by_key=docs
    )
    assert len(chunks) >= 2
    joined_bodies = []
    for chunk in chunks:
        assert chunk.body.startswith("1. ")
        assert chunk.token_estimate <= token_limit
        assert "lid 1" in (chunk.part_label or "")
        joined_bodies.append(chunk.body[3:])
    assert " ".join(joined_bodies) == " ".join(sentences)


@pytest.mark.unit
def test_chunker_raises_when_single_sentence_exceeds_limit() -> None:
    docs = _docs_by_key()
    doc = _avg_doc()
    body = "1. " + ("woord " * 500)
    provision = _article(body=body)
    with pytest.raises(ChunkTooLarge):
        chunk_provision(provision, doc, token_limit=10, documents_by_key=docs)


@pytest.mark.unit
def test_chunker_refs_for_lettered_article_and_split_parts() -> None:
    docs = _docs_by_key()
    # Real art_4a unsplit.
    items = load_indexed_provisions(load_manifest(MANIFEST_PATH), CORPUS)
    art_4a = next(
        p for d, p in items if d.key == "AI-verordening" and p.anchor == "art_4a"
    )
    chunks = chunk_provision(
        art_4a, _ai_doc(), token_limit=30000, documents_by_key=docs
    )
    assert len(chunks) == 1
    assert chunks[0].ref == "AI-verordening:art_4a"
    assert chunks[0].parent_ref == "AI-verordening:art_4a"

    # Synthetic AVG art_9 split into 3.
    paras = [_pad_paragraph(i, 40) for i in range(1, 7)]
    body = "\n".join(paras)
    provision = _article(body=body)
    doc = _avg_doc()
    header_two = build_header(
        provision,
        doc,
        part_no=1,
        part_count=3,
        part_label="leden 1 tot en met 2",
        documents_by_key=docs,
    )
    two_tokens = estimate_tokens(embedded_text(header_two, "\n".join(paras[:2])))
    chunks = chunk_provision(
        provision, doc, token_limit=two_tokens, documents_by_key=docs
    )
    assert len(chunks) == 3
    assert chunks[1].ref == "AVG:art_9#2"
    assert chunks[1].parent_ref == "AVG:art_9"
    assert chunks[1].part_no == 2
    assert chunks[1].part_count == 3
    assert chunks[1].part_label == "leden 3 tot en met 4"


@pytest.mark.unit
def test_chunker_embedded_text_is_header_blank_line_body() -> None:
    docs = _docs_by_key()
    provision = _article(body="1. Tekst.")
    chunks = chunk_provision(
        provision, _avg_doc(), token_limit=30000, documents_by_key=docs
    )
    chunk = chunks[0]
    assert embedded_text(chunk.header, chunk.body) == f"{chunk.header}\n\n{chunk.body}"
    assert chunk.token_estimate == estimate_tokens(
        embedded_text(chunk.header, chunk.body)
    )


@pytest.mark.unit
def test_chunker_annex_part_label_includes_single_internal_heading() -> None:
    docs = _docs_by_key()
    doc = _cra_doc()
    body = (
        "Deel I Eerste deel titel hier\n"
        "1) Eerste punt " + ("woord " * 60) + "\n"
        "2) Tweede punt " + ("woord " * 60) + "\n"
        "Deel II Vereisten inzake de respons op kwetsbaarheden\n"
        "1) Derde punt " + ("woord " * 60) + "\n"
        "2) Vierde punt " + ("woord " * 60)
    )
    provision = _annex(body=body)
    # Limit must fit the largest singleton (Deel II heading is longer than Deel I).
    largest_unit = (
        "Deel II Vereisten inzake de respons op kwetsbaarheden\n"
        "1) Derde punt " + ("woord " * 60)
    )
    header_one = build_header(
        provision,
        doc,
        part_no=1,
        part_count=99,
        part_label=("punt 1, Deel II Vereisten inzake de respons op kwetsbaarheden"),
        documents_by_key=docs,
    )
    token_limit = estimate_tokens(embedded_text(header_one, largest_unit))
    full_header = build_header(provision, doc, documents_by_key=docs)
    assert estimate_tokens(embedded_text(full_header, body)) > token_limit

    chunks = chunk_provision(
        provision, doc, token_limit=token_limit, documents_by_key=docs
    )
    assert len(chunks) >= 2
    deel_ii_chunks = [
        c
        for c in chunks
        if c.part_label
        and "Deel II Vereisten inzake de respons op kwetsbaarheden" in c.part_label
    ]
    assert deel_ii_chunks
    for chunk in deel_ii_chunks:
        assert "Deel I Eerste" not in (chunk.part_label or "")
        assert "punt" in (chunk.part_label or "")

    for chunk in chunks:
        if "Deel I Eerste" in chunk.body and "Deel II Vereisten" in chunk.body:
            assert "Deel I Eerste" not in (chunk.part_label or "")
            assert "Deel II Vereisten" not in (chunk.part_label or "")


@pytest.mark.unit
def test_chunker_annex_punten_wording_for_range() -> None:
    docs = _docs_by_key()
    doc = _cra_doc()
    body = "\n".join(f"{i}) " + ("punttekst " * 40) for i in range(1, 5))
    provision = _annex(body=body)
    header_two = build_header(
        provision,
        doc,
        part_no=1,
        part_count=2,
        part_label="punten 1 tot en met 2",
        documents_by_key=docs,
    )
    two_body = "\n".join(f"{i}) " + ("punttekst " * 40) for i in range(1, 3))
    token_limit = estimate_tokens(embedded_text(header_two, two_body))
    chunks = chunk_provision(
        provision, doc, token_limit=token_limit, documents_by_key=docs
    )
    assert len(chunks) == 2
    assert chunks[0].part_label == "punten 1 tot en met 2"
    assert chunks[1].part_label == "punten 3 tot en met 4"


@pytest.mark.unit
def test_chunk_indexed_real_corpus_characterization() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    items = load_indexed_provisions(manifest, CORPUS)
    assert len(items) == 359
    docs = {doc.key: doc for doc in manifest.documents}
    limit = Settings(_env_file=None).split_token_limit
    chunks = chunk_indexed(items, docs, token_limit=limit)

    assert len(chunks) == 359
    refs = [c.ref for c in chunks]
    assert len(refs) == len(set(refs))

    for chunk in chunks:
        assert chunk.part_count == 1
        assert chunk.part_no == 1
        assert chunk.part_label is None
        assert chunk.token_estimate <= limit
        assert "▼" not in chunk.body
        assert "►" not in chunk.body
        assert "◄" not in chunk.body
        assert "▼" not in chunk.header

        # Rebuild expected header from the matching parsed provision.
        parsed = next(
            p
            for d, p in items
            if d.key == chunk.doc and f"{d.key}:{p.anchor}" == chunk.parent_ref
        )
        doc = docs[chunk.doc]
        expected = build_header(parsed, doc, documents_by_key=docs)
        assert chunk.header == expected
        if parsed.amended_by:
            assert chunk.header.splitlines()[-1].startswith("Gewijzigd bij:")
        else:
            assert "Gewijzigd bij:" not in chunk.header

        assert isinstance(chunk, Provision)
        if chunk.chapter is not None:
            assert chunk.chapter.startswith("Hoofdstuk ")
        if chunk.section is not None:
            assert chunk.section.startswith("Afdeling ")
