"""Lineage header construction for indexed provisions."""

from __future__ import annotations

from collections.abc import Mapping

from app.errors import UnknownAmendment
from app.ingestion.manifest import DocumentSpec
from app.ingestion.models import ParsedProvision, ProvisionKind


def embedded_text(header: str, body: str) -> str:
    """Header plus body, including the status line. Shown to the LLM and the user."""
    return f"{header}\n\n{body}"


def text_for_embedding(header: str, body: str) -> str:
    """Embedding input. The status line is left out.

    On the eval set, including `Gewijzigd bij` did not raise the vector-hit
    count, so it is not part of the embedded text. The stored header still
    carries it for the model and the UI.
    """
    kept = [
        line for line in header.splitlines() if not line.startswith("Gewijzigd bij:")
    ]
    used = "\n".join(kept)
    if not used:
        return body
    return f"{used}\n\n{body}"


def chapter_display(numeral: str, title: str) -> str:
    return f"Hoofdstuk {numeral}: {title}"


def section_display(numeral: str, title: str) -> str:
    return f"Afdeling {numeral}: {title}"


def provision_display(kind: ProvisionKind, label: str, title: str | None) -> str:
    if kind == "article":
        if title:
            return f"Artikel {label}: {title}"
        return f"Artikel {label}"
    if kind == "annex":
        if title:
            return f"Bijlage {label}: {title}"
        return f"Bijlage {label}"
    return f"Overweging ({label})"


def part_display(part_no: int, part_count: int, part_label: str) -> str:
    return f"Deel {part_no} van {part_count}: {part_label}"


def status_display(amending: DocumentSpec) -> str:
    """Status line using the amending document's long name and identifier."""
    return f"Gewijzigd bij: {amending.long_name} ({amending.identifier})"


def build_header(
    provision: ParsedProvision,
    doc: DocumentSpec,
    *,
    part_no: int = 1,
    part_count: int = 1,
    part_label: str | None = None,
    documents_by_key: Mapping[str, DocumentSpec],
) -> str:
    """Build the full lineage header for one chunk."""
    lines: list[str] = [
        f"{doc.short_name} ({doc.long_name}), {doc.identifier}",
    ]
    if provision.chapter_numeral is not None and provision.chapter_title is not None:
        lines.append(
            chapter_display(provision.chapter_numeral, provision.chapter_title)
        )
    if provision.section_numeral is not None and provision.section_title is not None:
        lines.append(
            section_display(provision.section_numeral, provision.section_title)
        )
    lines.append(provision_display(provision.kind, provision.label, provision.title))
    if part_count > 1:
        if part_label is None:
            msg = "part_label is required when part_count > 1"
            raise ValueError(msg)
        lines.append(part_display(part_no, part_count, part_label))
    if provision.amended_by:
        for key in provision.amended_by:
            amending = documents_by_key.get(key)
            if amending is None:
                raise UnknownAmendment(key)
            lines.append(status_display(amending))
    return "\n".join(lines)
