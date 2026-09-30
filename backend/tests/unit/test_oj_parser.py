"""Unit tests for the Official Journal (Omnibus) HTML parser."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from app.ingestion.parsers.oj import parse_oj

CORPUS_RAW = Path("/app/corpus/raw")
OMNIBUS = CORPUS_RAW / "2026-1744_Omnibus.html"


def _by_anchor() -> dict[str, object]:
    return {p.anchor: p for p in parse_oj(OMNIBUS.read_text(encoding="utf-8"))}


@pytest.mark.unit
def test_oj_parser_yields_47_recitals_and_4_articles() -> None:
    provisions = parse_oj(OMNIBUS.read_text(encoding="utf-8"))
    recitals = [p for p in provisions if p.kind == "recital"]
    articles = [p for p in provisions if p.kind == "article"]
    assert len(recitals) == 47
    assert len(articles) == 4
    assert [f"Overweging ({p.label})" for p in recitals] == [
        f"Overweging ({n})" for n in range(1, 48)
    ]
    assert [p.anchor for p in articles] == ["art_1", "art_2", "art_3", "art_4"]
    assert [p.label for p in articles] == ["1", "2", "3", "4"]


@pytest.mark.unit
def test_oj_parser_recital_40_starts_with_article_113() -> None:
    art = _by_anchor()["rct_40"]
    assert art.body.startswith("Artikel 113 van Verordening (EU) 2024/1689")


@pytest.mark.unit
def test_oj_parser_article_4_title() -> None:
    art = _by_anchor()["art_4"]
    assert art.title == "Inwerkingtreding en toepassing"
    assert art.label == "4"
    assert "Artikel" not in art.body.split("\n", 1)[0]
    assert "Inwerkingtreding en toepassing" not in art.body
    assert art.body.startswith("Deze verordening treedt in werking")


@pytest.mark.unit
def test_oj_parser_xml_declaration_emits_no_warnings() -> None:
    html = OMNIBUS.read_text(encoding="utf-8")
    assert html.lstrip().startswith("<?xml")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        parse_oj(html)
    xml_warnings = [
        w
        for w in caught
        if "XML" in str(w.message) or "XMLParsedAsHTML" in type(w.message).__name__
    ]
    assert xml_warnings == []
