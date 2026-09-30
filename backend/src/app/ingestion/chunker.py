"""Split parsed provisions into indexed Provision rows."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.errors import ChunkTooLarge
from app.ingestion.headers import (
    build_header,
    chapter_display,
    embedded_text,
    section_display,
)
from app.ingestion.manifest import DocumentSpec
from app.ingestion.models import ParsedProvision, ProvisionKind
from app.ingestion.tokens import estimate_tokens
from app.schemas.domain import Provision

_ARTICLE_PARA = re.compile(r"^(\d+)\.\s")
_ANNEX_PUNT = re.compile(r"^(\d+)\)\s")
_INTERNAL_HEADING = re.compile(r"^(Deel|Klasse|Afdeling)\s+\S+")
_ABBREVIATIONS = frozenset(
    {
        "art",
        "nr",
        "nrs",
        "lid",
        "leden",
        "punt",
        "punten",
        "blz",
        "vgl",
        "zie",
        "etc",
        "dr",
        "mr",
        "mrs",
        "prof",
        "eng",
        "incl",
        "excl",
        "eg",
        "ie",
        "nl",
        "eu",
    }
)


@dataclass(frozen=True)
class _Unit:
    """One numbered paragraph (or unnumbered block) for splitting."""

    number: int | None
    body: str
    heading: str | None


def chunk_indexed(
    items: Sequence[tuple[DocumentSpec, ParsedProvision]],
    documents: Mapping[str, DocumentSpec] | Sequence[DocumentSpec],
    token_limit: int,
) -> list[Provision]:
    """Chunk every indexed provision using the full document map for status lines."""
    documents_by_key = (
        dict(documents)
        if isinstance(documents, Mapping)
        else {doc.key: doc for doc in documents}
    )
    result: list[Provision] = []
    for doc, provision in items:
        result.extend(
            chunk_provision(
                provision,
                doc,
                token_limit=token_limit,
                documents_by_key=documents_by_key,
            )
        )
    return result


def chunk_provision(
    provision: ParsedProvision,
    doc: DocumentSpec,
    *,
    token_limit: int,
    documents_by_key: Mapping[str, DocumentSpec],
) -> list[Provision]:
    """Turn one parsed provision into one or more indexed Provision rows."""
    parent_ref = f"{doc.key}:{provision.anchor}"
    units = _group_units(provision.body, provision.kind)
    if not units:
        units = [_Unit(number=None, body=provision.body, heading=None)]

    whole_header = build_header(provision, doc, documents_by_key=documents_by_key)
    whole_body = "\n".join(unit.body for unit in units)
    if estimate_tokens(embedded_text(whole_header, whole_body)) <= token_limit:
        return [
            _to_provision(
                provision,
                doc,
                parent_ref=parent_ref,
                part_no=1,
                part_count=1,
                part_label=None,
                body=whole_body,
                header=whole_header,
                documents_by_key=documents_by_key,
            )
        ]

    expanded = _expand_overlong_units(
        units,
        provision=provision,
        doc=doc,
        token_limit=token_limit,
        documents_by_key=documents_by_key,
    )
    return _partition_units(
        expanded,
        provision=provision,
        doc=doc,
        parent_ref=parent_ref,
        token_limit=token_limit,
        documents_by_key=documents_by_key,
    )


def format_part_label(
    kind: ProvisionKind,
    numbers: Sequence[int | None],
    heading: str | None = None,
) -> str:
    """Build the part range label, optionally with one shared internal heading."""
    concrete = [n for n in numbers if n is not None]
    if concrete:
        start = concrete[0]
        end = concrete[-1]
        if kind == "annex":
            if start == end:
                base = f"punt {start}"
            else:
                base = f"punten {start} tot en met {end}"
        else:
            if start == end:
                base = f"lid {start}"
            else:
                base = f"leden {start} tot en met {end}"
    else:
        base = "tekst"
    if heading:
        return f"{base}, {heading}"
    return base


def _group_units(body: str, kind: ProvisionKind) -> list[_Unit]:
    if not body:
        return []
    number_re = _ANNEX_PUNT if kind == "annex" else _ARTICLE_PARA
    units: list[_Unit] = []
    current_lines: list[str] = []
    current_number: int | None = None
    current_heading: str | None = None
    pending_heading: str | None = None

    def flush() -> None:
        nonlocal current_lines, current_number
        if not current_lines:
            return
        units.append(
            _Unit(
                number=current_number,
                body="\n".join(current_lines),
                heading=current_heading,
            )
        )
        current_lines = []
        current_number = None

    for line in body.split("\n"):
        if _INTERNAL_HEADING.match(line):
            flush()
            current_heading = line
            pending_heading = line
            continue
        match = number_re.match(line)
        if match:
            flush()
            current_number = int(match.group(1))
            if pending_heading is not None:
                current_lines = [pending_heading, line]
                pending_heading = None
            else:
                current_lines = [line]
            continue
        if not current_lines:
            current_number = None
            if pending_heading is not None:
                current_lines = [pending_heading, line]
                pending_heading = None
            else:
                current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    return units


def _expand_overlong_units(
    units: list[_Unit],
    *,
    provision: ParsedProvision,
    doc: DocumentSpec,
    token_limit: int,
    documents_by_key: Mapping[str, DocumentSpec],
) -> list[_Unit]:
    """Sentence-split any unit that cannot fit as a singleton part."""
    expanded: list[_Unit] = []
    # Use a large digit width so "Deel 1 van N" is not under-counted when N grows.
    guess_count = 99
    for unit in units:
        label = format_part_label(provision.kind, [unit.number], unit.heading)
        header = build_header(
            provision,
            doc,
            part_no=1,
            part_count=guess_count,
            part_label=label,
            documents_by_key=documents_by_key,
        )
        if estimate_tokens(embedded_text(header, unit.body)) <= token_limit:
            expanded.append(unit)
            continue
        for sentence_unit in _split_unit_at_sentences(unit, provision.kind):
            s_label = format_part_label(
                provision.kind, [sentence_unit.number], sentence_unit.heading
            )
            s_header = build_header(
                provision,
                doc,
                part_no=1,
                part_count=guess_count,
                part_label=s_label,
                documents_by_key=documents_by_key,
            )
            tokens = estimate_tokens(embedded_text(s_header, sentence_unit.body))
            if tokens > token_limit:
                raise ChunkTooLarge(tokens, token_limit)
            expanded.append(sentence_unit)
    return expanded


def _split_unit_at_sentences(unit: _Unit, kind: ProvisionKind) -> list[_Unit]:
    body = unit.body
    heading_prefix = ""
    rest = body
    if unit.heading is not None and body.startswith(unit.heading + "\n"):
        heading_prefix = unit.heading + "\n"
        rest = body[len(heading_prefix) :]

    number_re = _ANNEX_PUNT if kind == "annex" else _ARTICLE_PARA
    match = number_re.match(rest)
    if match:
        number_prefix = match.group(0)
        text = rest[len(number_prefix) :]
    else:
        number_prefix = ""
        text = rest

    sentences = _split_sentences(text)
    if not sentences:
        return [unit]

    result: list[_Unit] = []
    for index, sentence in enumerate(sentences):
        prefix = heading_prefix if index == 0 else ""
        result.append(
            _Unit(
                number=unit.number,
                body=f"{prefix}{number_prefix}{sentence}",
                heading=unit.heading,
            )
        )
    return result


def _split_sentences(text: str) -> list[str]:
    """Split on .!? followed by a space, skipping short abbreviations."""
    if not text:
        return []
    sentences: list[str] = []
    start = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ".!?" and i + 1 < len(text) and text[i + 1].isspace():
            if ch == "." and _is_abbreviation_before(text, i):
                i += 1
                continue
            end = i + 1
            sentences.append(text[start:end].strip())
            i = end
            while i < len(text) and text[i].isspace():
                i += 1
            start = i
            continue
        i += 1
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _is_abbreviation_before(text: str, period_index: int) -> bool:
    j = period_index - 1
    while j >= 0 and text[j].isalpha():
        j -= 1
    word = text[j + 1 : period_index].lower()
    if not word:
        return False
    if word in _ABBREVIATIONS:
        return True
    # Single-letter initials and very short abbreviations (art., nr.).
    return len(word) <= 2 and word.isalpha()


def _partition_units(
    units: list[_Unit],
    *,
    provision: ParsedProvision,
    doc: DocumentSpec,
    parent_ref: str,
    token_limit: int,
    documents_by_key: Mapping[str, DocumentSpec],
) -> list[Provision]:
    n = len(units)
    if n == 0:
        msg = "cannot partition empty unit list"
        raise ValueError(msg)

    for part_count in range(1, n + 1):
        best: tuple[int, int, tuple[int, ...], list[Provision]] | None = None
        for counts in _compositions(n, part_count):
            evaluated = _evaluate_partition(
                units,
                counts,
                part_count=part_count,
                provision=provision,
                doc=doc,
                parent_ref=parent_ref,
                token_limit=token_limit,
                documents_by_key=documents_by_key,
            )
            if evaluated is None:
                continue
            spread, max_tokens, parts = evaluated
            key = (spread, max_tokens, counts)
            if best is None or key < (best[0], best[1], best[2]):
                best = (spread, max_tokens, counts, parts)
        if best is not None:
            return best[3]

    # Should be unreachable if expand raised for unsplittable sentences.
    largest = max(estimate_tokens(unit.body) for unit in units)
    raise ChunkTooLarge(largest, token_limit)


def _evaluate_partition(
    units: list[_Unit],
    counts: tuple[int, ...],
    *,
    part_count: int,
    provision: ParsedProvision,
    doc: DocumentSpec,
    parent_ref: str,
    token_limit: int,
    documents_by_key: Mapping[str, DocumentSpec],
) -> tuple[int, int, list[Provision]] | None:
    parts: list[Provision] = []
    sizes: list[int] = []
    index = 0
    for part_no, count in enumerate(counts, start=1):
        slice_units = units[index : index + count]
        index += count
        headings = {unit.heading for unit in slice_units}
        shared_heading = next(iter(headings)) if len(headings) == 1 else None
        part_label = format_part_label(
            provision.kind,
            [unit.number for unit in slice_units],
            shared_heading,
        )
        body = _join_unit_bodies(slice_units, provision.kind)
        header = build_header(
            provision,
            doc,
            part_no=part_no,
            part_count=part_count,
            part_label=part_label,
            documents_by_key=documents_by_key,
        )
        tokens = estimate_tokens(embedded_text(header, body))
        if tokens > token_limit:
            return None
        sizes.append(tokens)
        parts.append(
            _to_provision(
                provision,
                doc,
                parent_ref=parent_ref,
                part_no=part_no,
                part_count=part_count,
                part_label=part_label,
                body=body,
                header=header,
                documents_by_key=documents_by_key,
            )
        )
    spread = max(sizes) - min(sizes)
    return spread, max(sizes), parts


def _compositions(n: int, k: int) -> list[tuple[int, ...]]:
    """All ordered k-tuples of positive integers that sum to n."""
    if k == 1:
        return [(n,)]
    result: list[tuple[int, ...]] = []
    for first in range(1, n - k + 2):
        for rest in _compositions(n - first, k - 1):
            result.append((first, *rest))
    return result


def _join_unit_bodies(units: Sequence[_Unit], kind: ProvisionKind) -> str:
    """Join units into body text.

    Consecutive sentence-parts that share a paragraph number are merged back
    into one numbered paragraph with spaces between sentences.
    """
    if not units:
        return ""
    parts: list[str] = []
    index = 0
    while index < len(units):
        end = index + 1
        while (
            end < len(units)
            and units[index].number is not None
            and units[end].number == units[index].number
        ):
            end += 1
        group = list(units[index:end])
        if len(group) == 1:
            parts.append(group[0].body)
        else:
            parts.append(_merge_sentence_group(group, kind))
        index = end
    return "\n".join(parts)


def _merge_sentence_group(group: Sequence[_Unit], kind: ProvisionKind) -> str:
    number_re = _ANNEX_PUNT if kind == "annex" else _ARTICLE_PARA
    heading: str | None = None
    prefix: str | None = None
    sentences: list[str] = []
    for unit in group:
        body = unit.body
        if unit.heading is not None and body.startswith(unit.heading + "\n"):
            if heading is None:
                heading = unit.heading
            body = body[len(unit.heading) + 1 :]
        match = number_re.match(body)
        if match is None:
            return "\n".join(unit.body for unit in group)
        if prefix is None:
            prefix = match.group(0)
        sentences.append(body[len(match.group(0)) :])
    merged = f"{prefix}{' '.join(sentences)}"
    if heading is not None:
        return f"{heading}\n{merged}"
    return merged


def _to_provision(
    provision: ParsedProvision,
    doc: DocumentSpec,
    *,
    parent_ref: str,
    part_no: int,
    part_count: int,
    part_label: str | None,
    body: str,
    header: str,
    documents_by_key: Mapping[str, DocumentSpec],
) -> Provision:
    del documents_by_key  # header already built by caller
    ref = parent_ref if part_count == 1 else f"{parent_ref}#{part_no}"
    chapter = None
    if provision.chapter_numeral is not None and provision.chapter_title is not None:
        chapter = chapter_display(provision.chapter_numeral, provision.chapter_title)
    section = None
    if provision.section_numeral is not None and provision.section_title is not None:
        section = section_display(provision.section_numeral, provision.section_title)
    return Provision(
        ref=ref,
        doc=doc.key,
        kind=provision.kind,
        label=provision.label,
        parent_ref=parent_ref,
        part_no=part_no,
        part_count=part_count,
        title=provision.title,
        chapter=chapter,
        section=section,
        part_label=part_label if part_count > 1 else None,
        header=header,
        body=body,
        token_estimate=estimate_tokens(embedded_text(header, body)),
        amended_by=list(provision.amended_by),
    )
