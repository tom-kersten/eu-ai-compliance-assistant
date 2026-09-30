"""Parser for EUR-Lex Official Journal HTML (Omnibus)."""

from __future__ import annotations

import re
from collections.abc import Callable

from bs4 import BeautifulSoup, NavigableString, Tag

from app.ingestion.models import ParsedProvision

_RECITAL_ID = re.compile(r"^rct_\d+$")
_ARTICLE_ID = re.compile(r"^art_[^.]+$")
_WS = re.compile(r"[ \t\xa0\u202f]+")
_MULTI_SPACE = re.compile(r" {2,}")
_ARTICLE_HEADING = re.compile(r"^Artikel\s+", re.IGNORECASE)
_RECITAL_LABEL = re.compile(r"^\((\d+)\)$")
_SKIP_TAGS = {"hr", "br", "script", "style", "col", "colgroup"}
_HEADING_CLASSES = {"oj-ti-art", "oj-sti-art"}
_XML_DECL = re.compile(r"^\s*<\?xml[^?]*\?>\s*", re.IGNORECASE)

EmitFn = Callable[[str], None]


def parse_oj(html: str) -> list[ParsedProvision]:
    """Parse an Official Journal EUR-Lex HTML document into provisions."""
    stripped = _XML_DECL.sub("", html, count=1)
    soup = BeautifulSoup(stripped, "lxml")
    provisions: list[ParsedProvision] = []
    root = soup.body if soup.body is not None else soup
    _walk(root, provisions)
    return provisions


def _walk(node: Tag | NavigableString, provisions: list[ParsedProvision]) -> None:
    if isinstance(node, NavigableString) or not isinstance(node, Tag):
        return

    node_id = node.get("id")
    if isinstance(node_id, str):
        if _RECITAL_ID.match(node_id):
            provisions.append(_parse_recital(node, node_id))
            return
        if _ARTICLE_ID.match(node_id):
            provisions.append(_parse_article(node, node_id))
            return

    for child in node.children:
        _walk(child, provisions)


def _normalize_ws(text: str) -> str:
    return _WS.sub(" ", text.replace("\n", " ").replace("\r", " ")).strip()


def _collapse_spaces(text: str) -> str:
    return _MULTI_SPACE.sub(" ", text).strip()


def _text(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    return _normalize_ws(node.get_text())


def _has_class(node: Tag, name: str) -> bool:
    return name in (node.get("class") or [])


def _class_names(node: Tag) -> set[str]:
    return set(node.get("class") or [])


def _is_heading(node: Tag) -> bool:
    return bool(_class_names(node) & _HEADING_CLASSES)


def _parse_recital(element: Tag, anchor: str) -> ParsedProvision:
    table = element.find("table", recursive=False)
    if table is None:
        table = element.find("table")
    label = ""
    body = ""
    if table is not None:
        row = table.find("tr")
        if row is not None:
            cells = row.find_all("td", recursive=False)
            if len(cells) >= 1:
                raw_label = _text(cells[0])
                match = _RECITAL_LABEL.match(raw_label)
                label = match.group(1) if match else raw_label.strip("()")
            if len(cells) >= 2:
                body = _render_body(cells[1])
    return ParsedProvision(
        anchor=anchor,
        kind="recital",
        label=label,
        body=body,
    )


def _parse_article(element: Tag, anchor: str) -> ParsedProvision:
    heading = element.find("p", class_="oj-ti-art")
    label = _ARTICLE_HEADING.sub("", _text(heading)).strip()
    title_el = element.find("p", class_="oj-sti-art")
    title = _text(title_el) or None
    body = _render_body(element, skip_headings=True)
    return ParsedProvision(
        anchor=anchor,
        kind="article",
        label=label,
        title=title,
        body=body,
    )


def _render_body(element: Tag, *, skip_headings: bool = False) -> str:
    lines: list[str] = []

    def emit(text: str) -> None:
        cleaned = _collapse_spaces(_normalize_ws(text))
        if cleaned:
            lines.append(cleaned)

    for child in element.children:
        _render_node(child, emit, skip_headings=skip_headings)
    return "\n".join(lines)


def _render_node(
    node: Tag | NavigableString,
    emit: EmitFn,
    *,
    skip_headings: bool = False,
) -> None:
    if isinstance(node, NavigableString):
        text = str(node).strip()
        if text:
            emit(text)
        return
    if not isinstance(node, Tag):
        return
    if node.name in _SKIP_TAGS:
        return
    if skip_headings and _is_heading(node):
        return
    if skip_headings and node.name == "div" and _has_class(node, "eli-title"):
        return

    if node.name == "table":
        _render_table(node, emit)
        return

    if node.name == "p":
        text = _inline_text(node)
        if text:
            emit(text)
        return

    for child in node.children:
        _render_node(child, emit, skip_headings=skip_headings)


def _render_table(table: Tag, emit: EmitFn) -> None:
    for row in table.find_all("tr", recursive=False):
        _render_table_row(row, emit)
    # Some OJ tables nest tbody.
    for tbody in table.find_all("tbody", recursive=False):
        for row in tbody.find_all("tr", recursive=False):
            _render_table_row(row, emit)


def _render_table_row(row: Tag, emit: EmitFn) -> None:
    cells = row.find_all(["td", "th"], recursive=False)
    if not cells:
        return
    if len(cells) == 1:
        _render_cell_contents(cells[0], emit)
        return

    marker = _inline_text(cells[0])
    # Lead text in the second cell before nested tables.
    lead_parts: list[str] = []
    nested_tables: list[Tag] = []
    trailing: list[Tag] = []
    after_nested = False
    for child in cells[1].children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text and not after_nested:
                lead_parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "table":
            nested_tables.append(child)
            after_nested = True
            continue
        if child.name in _SKIP_TAGS:
            continue
        if after_nested:
            trailing.append(child)
            continue
        if child.name == "p":
            text = _inline_text(child)
            if text:
                lead_parts.append(text)
            continue
        # Nested divs or other wrappers before nested tables.
        text = _inline_text(child)
        if text and not child.find("table"):
            lead_parts.append(text)
        elif child.find("table"):
            for nested in child.find_all("table", recursive=False):
                nested_tables.append(nested)
            after_nested = True
        else:
            lead_parts.append(_inline_text(child))

    lead = _collapse_spaces(_normalize_ws(" ".join(lead_parts)))
    if marker or lead:
        line = f"{marker} {lead}".strip() if marker else lead
        if line:
            emit(line)
    for nested in nested_tables:
        _render_table(nested, emit)
    for node in trailing:
        _render_node(node, emit)


def _render_cell_contents(cell: Tag, emit: EmitFn) -> None:
    for child in cell.children:
        _render_node(child, emit)


def _inline_text(node: Tag | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []

    def walk(n: Tag | NavigableString) -> None:
        if isinstance(n, NavigableString):
            parts.append(str(n))
            return
        if not isinstance(n, Tag):
            return
        if n.name in _SKIP_TAGS:
            return
        if n.name == "table":
            return
        for child in n.children:
            walk(child)

    walk(node)
    return _collapse_spaces(_normalize_ws("".join(parts)))
