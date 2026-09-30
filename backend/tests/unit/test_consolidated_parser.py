"""Unit tests for the consolidated EUR-Lex HTML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.parsers.consolidated import parse_consolidated

CORPUS_RAW = Path("/app/corpus/raw")
AIACT = CORPUS_RAW / "2024-1689_AIACT.html"
AVG = CORPUS_RAW / "2016-679_GDPR.html"
CRA = CORPUS_RAW / "2024-2847_CRA.html"


def _by_anchor(path: Path) -> dict[str, object]:
    return {p.anchor: p for p in parse_consolidated(path.read_text(encoding="utf-8"))}


@pytest.mark.unit
def test_consolidated_parser_counts_ai_act_articles_and_annexes() -> None:
    provisions = parse_consolidated(AIACT.read_text(encoding="utf-8"))
    articles = [p for p in provisions if p.kind == "article"]
    annexes = [p for p in provisions if p.kind == "annex"]
    assert len(articles) == 119
    assert len(annexes) == 14


@pytest.mark.unit
def test_consolidated_parser_counts_avg_articles() -> None:
    provisions = parse_consolidated(AVG.read_text(encoding="utf-8"))
    assert len(provisions) == 99
    assert all(p.kind == "article" for p in provisions)


@pytest.mark.unit
def test_consolidated_parser_counts_cra_articles_and_annexes() -> None:
    provisions = parse_consolidated(CRA.read_text(encoding="utf-8"))
    articles = [p for p in provisions if p.kind == "article"]
    annexes = [p for p in provisions if p.kind == "annex"]
    assert len(articles) == 71
    assert len(annexes) == 8


@pytest.mark.unit
def test_consolidated_parser_reads_lettered_article_labels_from_headings() -> None:
    by_anchor = _by_anchor(AIACT)
    assert by_anchor["art_4a"].label == "4 bis"
    assert by_anchor["art_60a"].label == "60 bis"
    assert by_anchor["art_75a"].label == "75 bis"
    assert by_anchor["art_75b"].label == "75 ter"
    assert by_anchor["art_75c"].label == "75 quater"
    assert by_anchor["art_75d"].label == "75 quinquies"


@pytest.mark.unit
def test_consolidated_parser_reads_annex_numeral_from_heading() -> None:
    by_anchor = _by_anchor(AIACT)
    assert by_anchor["anx_III"].label == "III"


@pytest.mark.unit
def test_consolidated_parser_ai_act_article_6_lineage_and_title() -> None:
    art = _by_anchor(AIACT)["art_6"]
    assert art.chapter_numeral == "III"
    assert art.chapter_title == "AI-SYSTEMEN MET EEN HOOG RISICO"
    assert art.section_numeral == "1"
    assert art.section_title == (
        "Classificatie van AI-systemen als AI-systemen met een hoog risico"
    )
    assert art.title == "Classificatieregels voor AI-systemen met een hoog risico"


@pytest.mark.unit
def test_consolidated_parser_ai_act_article_26_section() -> None:
    art = _by_anchor(AIACT)["art_26"]
    assert art.chapter_numeral == "III"
    assert art.section_numeral == "3"
    assert art.section_title == (
        "Verplichtingen van aanbieders en gebruiksverantwoordelijken "
        "van AI-systemen met een hoog risico en andere partijen"
    )


@pytest.mark.unit
def test_consolidated_parser_avg_article_22_lineage_and_title() -> None:
    art = _by_anchor(AVG)["art_22"]
    assert art.chapter_numeral == "III"
    assert art.chapter_title == "Rechten van de betrokkene"
    assert art.section_numeral == "4"
    assert art.section_title == (
        "Recht van bezwaar en geautomatiseerde individuele besluitvorming"
    )
    assert art.title == (
        "Geautomatiseerde individuele besluitvorming, waaronder profilering"
    )


@pytest.mark.unit
def test_consolidated_parser_avg_article_9_chapter_only() -> None:
    art = _by_anchor(AVG)["art_9"]
    assert art.chapter_numeral == "II"
    assert art.chapter_title == "Beginselen"
    assert art.section_numeral is None
    assert art.section_title is None
    assert art.title == "Verwerking van bijzondere categorieën van persoonsgegevens"


@pytest.mark.unit
def test_consolidated_parser_cra_article_12_lineage_and_title() -> None:
    art = _by_anchor(CRA)["art_12"]
    assert art.chapter_numeral == "I"
    assert art.chapter_title == "ALGEMENE BEPALINGEN"
    assert art.section_numeral is None
    assert art.title == "AI-systemen met een hoog risico"


@pytest.mark.unit
def test_consolidated_parser_ai_act_annex_iii_no_chapter() -> None:
    annex = _by_anchor(AIACT)["anx_III"]
    assert annex.kind == "annex"
    assert annex.chapter_numeral is None
    assert annex.section_numeral is None
    assert annex.title == (
        "In artikel 6, lid 2, bedoelde AI-systemen met een hoog risico"
    )


@pytest.mark.unit
def test_consolidated_parser_body_excludes_headings_and_structures_paragraphs() -> None:
    art = _by_anchor(AIACT)["art_1"]
    lines = art.body.splitlines()
    assert lines[0].startswith("1. Deze verordening heeft tot doel")
    assert "Artikel 1" not in art.body
    assert "Onderwerp" not in art.body
    assert any(line.startswith("a) ") for line in lines)
    assert any(line.startswith("g) ") for line in lines)


@pytest.mark.unit
def test_consolidated_parser_body_keeps_lettered_paragraph_on_own_line() -> None:
    art = _by_anchor(AIACT)["art_6"]
    lines = art.body.splitlines()
    assert any(line.startswith("1 bis. ") for line in lines)


@pytest.mark.unit
def test_consolidated_parser_body_avg_definition_list_items() -> None:
    art = _by_anchor(AVG)["art_4"]
    lines = art.body.splitlines()
    assert any(line.startswith("1) ") for line in lines)


@pytest.mark.unit
def test_consolidated_parser_annex_body_excludes_heading() -> None:
    annex = _by_anchor(AIACT)["anx_III"]
    assert "BIJLAGE III" not in annex.body
    assert annex.body


@pytest.mark.unit
def test_consolidated_parser_body_normalizes_whitespace() -> None:
    for path in (AIACT, AVG, CRA):
        for provision in parse_consolidated(path.read_text(encoding="utf-8")):
            assert "\xa0" not in provision.body
            assert "\u202f" not in provision.body
            assert "  " not in provision.body


@pytest.mark.unit
def test_consolidated_parser_strips_all_marker_characters() -> None:
    for path in (AIACT, AVG, CRA):
        for provision in parse_consolidated(path.read_text(encoding="utf-8")):
            assert "▼" not in provision.body
            assert "►" not in provision.body
            assert "◄" not in provision.body


@pytest.mark.unit
def test_consolidated_parser_amended_by_omnibus_for_marked_ai_act_articles() -> None:
    by_anchor = _by_anchor(AIACT)
    for anchor in ("art_4", "art_4a", "art_6", "art_60a", "art_75a"):
        assert by_anchor[anchor].amended_by == ["Omnibus"], anchor


@pytest.mark.unit
def test_consolidated_parser_amended_by_false_for_unmarked_ai_act_article_12() -> None:
    art = _by_anchor(AIACT)["art_12"]
    assert art.amended_by == []


@pytest.mark.unit
def test_consolidated_parser_amended_by_false_for_every_avg_article() -> None:
    for provision in parse_consolidated(AVG.read_text(encoding="utf-8")):
        assert provision.amended_by == [], provision.anchor


@pytest.mark.unit
def test_consolidated_parser_is_deterministic() -> None:
    for path in (AIACT, AVG, CRA):
        html = path.read_text(encoding="utf-8")
        first = [p.model_dump() for p in parse_consolidated(html)]
        second = [p.model_dump() for p in parse_consolidated(html)]
        assert first == second
