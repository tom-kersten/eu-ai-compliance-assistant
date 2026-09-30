"""Parser for EUR-Lex consolidated HTML (AI Act, AVG, CRA)."""

from __future__ import annotations

import re
from collections.abc import Callable

from bs4 import BeautifulSoup, NavigableString, Tag

from app.ingestion.markers import (
    MarkerTracker,
    extract_marker_text,
    is_marker_element,
    strip_marker_glyphs,
)
from app.ingestion.models import ParsedProvision

_ARTICLE_ID = re.compile(r"^art_[^.]+$")
_ANNEX_ID = re.compile(r"^anx_[^.]+$")
_CHAPTER_ID = re.compile(r"^cpt_[^.]+$")
_SECTION_ID = re.compile(r"^cpt_[^.]+\.sct_[^.]+$")
_WS = re.compile(r"[ \t\xa0\u202f]+")
_MULTI_SPACE = re.compile(r" {2,}")
_ARTICLE_HEADING = re.compile(r"^Artikel\s+", re.IGNORECASE)
_ANNEX_HEADING = re.compile(r"^BIJLAGE\s+", re.IGNORECASE)
_CHAPTER_HEADING = re.compile(r"^HOOFDSTUK\s+", re.IGNORECASE)
_SECTION_HEADING = re.compile(r"^AFDELING\s+", re.IGNORECASE)

_HEADING_CLASSES = {
    "title-article-norm",
    "stitle-article-norm",
    "title-annex-1",
    "title-annex-2",
    "eli-title",
}
_SKIP_TAGS = {"hr", "br", "script", "style", "col", "colgroup"}


def parse_consolidated(html: str) -> list[ParsedProvision]:
    """Parse a consolidated EUR-Lex HTML document into provisions."""
    soup = BeautifulSoup(html, "lxml")
    tracker = MarkerTracker()
    provisions: list[ParsedProvision] = []
    root = soup.body if soup.body is not None else soup
    _walk(root, tracker, provisions)
    return provisions


def _walk(
    node: Tag | NavigableString,
    tracker: MarkerTracker,
    provisions: list[ParsedProvision],
) -> None:
    if isinstance(node, NavigableString) or not isinstance(node, Tag):
        return

    node_id = node.get("id")
    if isinstance(node_id, str):
        if _ARTICLE_ID.match(node_id):
            provisions.append(_parse_article(node, node_id, tracker))
            return
        if _ANNEX_ID.match(node_id):
            provisions.append(_parse_annex(node, node_id, tracker))
            return

    if _handle_marker_node(node, tracker):
        return

    for child in node.children:
        _walk(child, tracker, provisions)


def _handle_marker_node(node: Tag, tracker: MarkerTracker) -> bool:
    """Apply a marker-only node to the tracker. Return True if fully handled."""
    classes = set(node.get("class") or [])
    if "modref" in classes:
        _apply_modref(node, tracker)
        return True
    if "arrow" in classes or is_marker_element(node):
        text = extract_marker_text(node)
        if text is not None:
            tracker.apply_marker_text(text)
        return True
    return False


def _apply_modref(node: Tag, tracker: MarkerTracker) -> str | None:
    """Update tracker from a modref element; return leftover body text if any."""
    leftover_parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            leftover_parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        marker = extract_marker_text(child)
        if marker is not None or is_marker_element(child):
            text = extract_marker_text(child) or child.get_text(strip=True)
            tracker.apply_marker_text(text)
            continue
        leftover_parts.append(child.get_text())
    leftover = _normalize_ws("".join(leftover_parts))
    leftover = strip_marker_glyphs(leftover).strip()
    return leftover or None


def _normalize_ws(text: str) -> str:
    return _WS.sub(" ", text.replace("\n", " ").replace("\r", " ")).strip()


def _collapse_spaces(text: str) -> str:
    return _MULTI_SPACE.sub(" ", text).strip()


def _text(node: Tag | NavigableString | None) -> str:
    if node is None:
        return ""
    return _normalize_ws(node.get_text())


def _parse_article(
    element: Tag, anchor: str, tracker: MarkerTracker
) -> ParsedProvision:
    heading = element.find("p", class_="title-article-norm", recursive=False)
    label = _ARTICLE_HEADING.sub("", _text(heading)).strip()
    title_el = element.find("p", class_="stitle-article-norm")
    title = _text(title_el) or None
    chapter_numeral, chapter_title, section_numeral, section_title = _lineage(element)
    body, amended_by = _render_body(element, tracker)
    return ParsedProvision(
        anchor=anchor,
        kind="article",
        label=label,
        title=title,
        chapter_numeral=chapter_numeral,
        chapter_title=chapter_title,
        section_numeral=section_numeral,
        section_title=section_title,
        body=body,
        amended_by=amended_by,
    )


def _parse_annex(element: Tag, anchor: str, tracker: MarkerTracker) -> ParsedProvision:
    annex_headings = element.find_all("p", class_="title-annex-1", recursive=False)
    label = ""
    title: str | None = None
    if annex_headings:
        label = _ANNEX_HEADING.sub("", _text(annex_headings[0])).strip()
        if len(annex_headings) > 1:
            title = _text(annex_headings[1]) or None
    title_el = element.find("p", class_="title-annex-2", recursive=False)
    if title_el is not None:
        title = _text(title_el) or None
    body, amended_by = _render_body(element, tracker)
    return ParsedProvision(
        anchor=anchor,
        kind="annex",
        label=label,
        title=title,
        body=body,
        amended_by=amended_by,
    )


def _lineage(
    element: Tag,
) -> tuple[str | None, str | None, str | None, str | None]:
    chapter_numeral: str | None = None
    chapter_title: str | None = None
    section_numeral: str | None = None
    section_title: str | None = None
    for ancestor in element.parents:
        if not isinstance(ancestor, Tag):
            continue
        ancestor_id = ancestor.get("id")
        if not isinstance(ancestor_id, str):
            continue
        if section_numeral is None and _SECTION_ID.match(ancestor_id):
            section_numeral, section_title = _division_heading(
                ancestor, _SECTION_HEADING
            )
        elif chapter_numeral is None and _CHAPTER_ID.match(ancestor_id):
            chapter_numeral, chapter_title = _division_heading(
                ancestor, _CHAPTER_HEADING
            )
            break
    return chapter_numeral, chapter_title, section_numeral, section_title


def _division_heading(
    container: Tag,
    prefix: re.Pattern[str],
) -> tuple[str | None, str | None]:
    numeral_el = container.find("p", class_="title-division-1", recursive=False)
    title_el = container.find("p", class_="title-division-2", recursive=False)
    numeral = prefix.sub("", _text(numeral_el)).strip() or None
    title = _text(title_el) or None
    return numeral, title


def _render_body(element: Tag, tracker: MarkerTracker) -> tuple[str, list[str]]:
    """Render provision body lines; update tracker; return body and amended_by."""
    saw_m1 = False
    lines: list[str] = []

    def note(text: str) -> None:
        nonlocal saw_m1
        if text and tracker.current_code == "M1":
            saw_m1 = True
            tracker.observe_text(text)

    def emit(text: str) -> None:
        cleaned = _collapse_spaces(strip_marker_glyphs(_normalize_ws(text)))
        if cleaned:
            note(cleaned)
            lines.append(cleaned)

    for child in element.children:
        _render_node(child, tracker, emit, note)

    amended = ["Omnibus"] if saw_m1 else []
    return "\n".join(lines), amended


def _has_class(node: Tag, name: str) -> bool:
    classes = node.get("class") or []
    return name in classes


def _class_names(node: Tag) -> set[str]:
    return set(node.get("class") or [])


def _is_heading(node: Tag) -> bool:
    return bool(_class_names(node) & _HEADING_CLASSES)


def _render_node(
    node: Tag | NavigableString,
    tracker: MarkerTracker,
    emit: Callable[[str], None],
    note: Callable[[str], None],
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
    if _is_heading(node):
        return

    classes = _class_names(node)

    if "modref" in classes:
        leftover = _apply_modref(node, tracker)
        if leftover:
            emit(leftover)
        return

    if "arrow" in classes or (
        is_marker_element(node) and "grid-container" not in classes
    ):
        # Pure marker wrappers (not list containers that happen to contain markers).
        if _is_pure_marker_wrapper(node):
            text = extract_marker_text(node)
            if text is not None:
                tracker.apply_marker_text(text)
            return

    if node.name == "span" and _has_class(node, "no-parag"):
        # Handled by the parent div.norm.
        return

    if (
        node.name == "div"
        and _has_class(node, "norm")
        and not _has_class(node, "inline-element")
    ):
        _render_numbered_block(node, tracker, emit, note)
        return

    if node.name == "div" and "grid-container" in classes and "grid-list" in classes:
        _render_grid_list_item(node, tracker, emit, note)
        return

    if node.name == "table":
        _render_table(node, tracker, emit, note)
        return

    if node.name == "p":
        if any(c.startswith("title-gr-seq") for c in classes) or "norm" in classes:
            text = _inline_text(node, tracker, note)
            if text:
                emit(text)
            # Nested lists after a lead paragraph live as siblings, not children of p.
            return
        # Other paragraphs: only emit if they have real text.
        text = _inline_text(node, tracker, note)
        if text:
            emit(text)
        return

    if node.name == "div":
        # Annex hanging-indent lists and other wrappers.
        for child in node.children:
            _render_node(child, tracker, emit, note)
        return

    # Fallback: recurse.
    for child in node.children:
        _render_node(child, tracker, emit, note)


def _is_pure_marker_wrapper(node: Tag) -> bool:
    """True if the node is a marker and has no other legal text."""
    if not is_marker_element(node):
        return False
    leftover = strip_marker_glyphs(_normalize_ws(node.get_text()))
    # Strip marker codes like M1, C1, B left after glyph removal.
    leftover = re.sub(r"\b[BMC]\d*\b", "", leftover).strip()
    leftover = re.sub(r"[—\-–]+", "", leftover).strip()
    return not leftover


def _render_numbered_block(
    node: Tag,
    tracker: MarkerTracker,
    emit: Callable[[str], None],
    note: Callable[[str], None],
) -> None:
    """Render a div.norm that may start with span.no-parag."""
    number = ""
    inline: Tag | None = None
    for child in node.children:
        if isinstance(child, NavigableString):
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "span" and _has_class(child, "no-parag"):
            number = _normalize_ws(child.get_text())
            continue
        if _handle_inner_marker(child, tracker):
            continue
        if child.name == "div" and _has_class(child, "norm"):
            inline = child
            continue
        if child.name == "p" and _has_class(child, "norm"):
            # Unusual: numbered block might not use inline-element.
            text = _inline_text(child, tracker, note)
            emit(f"{number} {text}".strip() if number else text)
            number = ""
            continue
        if child.name == "div" and "grid-container" in (_class_names(child)):
            if number:
                emit(number.rstrip("."))
                number = ""
            _render_grid_list_item(child, tracker, emit, note)
            continue

    if inline is not None:
        _render_inline_element(inline, number, tracker, emit, note)
    elif number:
        emit(number)


def _render_inline_element(
    node: Tag,
    number: str,
    tracker: MarkerTracker,
    emit: Callable[[str], None],
    note: Callable[[str], None],
) -> None:
    """Render div.norm.inline-element, optionally prefixed with a paragraph number."""
    lead_parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                lead_parts.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if _handle_inner_marker(child, tracker):
            continue
        if child.name == "p" and _has_class(child, "norm"):
            # Lead sentence before a list.
            if lead_parts:
                lead = _collapse_spaces(
                    strip_marker_glyphs(_normalize_ws(" ".join(lead_parts)))
                )
                if lead:
                    note(lead)
                    emit(f"{number} {lead}".strip() if number else lead)
                    number = ""
                    lead_parts = []
            text = _inline_text(child, tracker, note)
            if text:
                emit(f"{number} {text}".strip() if number else text)
                number = ""
            continue
        if child.name == "div" and "grid-container" in _class_names(child):
            if lead_parts:
                lead = _collapse_spaces(
                    strip_marker_glyphs(_normalize_ws(" ".join(lead_parts)))
                )
                if lead:
                    note(lead)
                    emit(f"{number} {lead}".strip() if number else lead)
                    number = ""
                    lead_parts = []
            elif number:
                # Number with no lead text before the list (rare).
                emit(number)
                number = ""
            _render_grid_list_item(child, tracker, emit, note)
            continue
        # Nested inline content without a wrapping p.
        if child.name != "div" and "grid-container" not in _class_names(child):
            fragment = _inline_text(child, tracker, note)
            if fragment:
                lead_parts.append(fragment)
            continue
        _render_node(child, tracker, emit, note)

    if lead_parts:
        joined = _normalize_ws(" ".join(lead_parts))
        lead = _collapse_spaces(strip_marker_glyphs(joined))
        if lead:
            note(lead)
            emit(f"{number} {lead}".strip() if number else lead)


def _handle_inner_marker(node: Tag, tracker: MarkerTracker) -> bool:
    classes = _class_names(node)
    if "modref" in classes:
        _apply_modref(node, tracker)
        return True
    if is_marker_element(node) and _is_pure_marker_wrapper(node):
        text = extract_marker_text(node)
        if text is not None:
            tracker.apply_marker_text(text)
        return True
    return False


def _render_grid_list_item(
    node: Tag,
    tracker: MarkerTracker,
    emit: Callable[[str], None],
    note: Callable[[str], None],
) -> None:
    label = ""
    body_parts: list[str] = []
    for child in node.children:
        if not isinstance(child, Tag):
            continue
        classes = _class_names(child)
        # First column often uses class "list" and/or "grid-list-column-1".
        if "grid-list-column-1" in classes or (
            "list" in classes and "grid-list-column-2" not in classes
        ):
            label = _normalize_ws(child.get_text())
            continue
        if "grid-list-column-2" in classes:
            for sub in child.children:
                if isinstance(sub, NavigableString):
                    text = str(sub).strip()
                    if text:
                        body_parts.append(text)
                    continue
                if not isinstance(sub, Tag):
                    continue
                if _handle_inner_marker(sub, tracker):
                    continue
                if sub.name == "div" and "grid-container" in _class_names(sub):
                    # Nested list: emit parent line first, then recurse.
                    continue
                text = _inline_text(sub, tracker, note)
                if text:
                    body_parts.append(text)
            # Emit this item, then nested lists as their own lines.
            body = _collapse_spaces(
                strip_marker_glyphs(_normalize_ws(" ".join(body_parts)))
            )
            line = f"{label} {body}".strip() if label else body
            if line:
                note(line)
                emit(line)
            for sub in child.children:
                if isinstance(sub, Tag) and "grid-container" in _class_names(sub):
                    _render_grid_list_item(sub, tracker, emit, note)
            return

    # Fallback if structure was unexpected.
    text = _inline_text(node, tracker, note)
    if text:
        emit(text)


def _render_table(
    node: Tag,
    tracker: MarkerTracker,
    emit: Callable[[str], None],
    note: Callable[[str], None],
) -> None:
    # Definition lists used by AVG Article 4.
    terms = node.find_all("p", class_="dlist-term")
    if terms:
        for row in node.find_all("tr"):
            term = row.find("p", class_="dlist-term")
            definition = row.find("p", class_="dlist-definition")
            if term is None and definition is None:
                continue
            term_text = _inline_text(term, tracker, note) if term else ""
            def_text = _inline_text(definition, tracker, note) if definition else ""
            line = f"{term_text} {def_text}".strip()
            if line:
                emit(line)
        return

    # Data tables (for example annex tables): one line per row.
    for row in node.find_all("tr"):
        cells = [
            _inline_text(cell, tracker, note) for cell in row.find_all(["td", "th"])
        ]
        cells = [c for c in cells if c]
        if cells:
            emit(" ".join(cells))


def _inline_text(
    node: Tag | None, tracker: MarkerTracker, note: Callable[[str], None]
) -> str:
    """Collect visible text from a node, applying inline markers as they appear."""
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
        if _handle_inner_marker(n, tracker):
            return
        classes = _class_names(n)
        if "grid-container" in classes:
            # Nested lists are rendered by the caller as separate lines.
            return
        for child in n.children:
            walk(child)

    walk(node)
    text = _collapse_spaces(strip_marker_glyphs(_normalize_ws("".join(parts))))
    if text:
        note(text)
    return text
