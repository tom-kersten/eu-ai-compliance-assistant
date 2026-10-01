from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.schemas.domain import Provision
from app.schemas.llm import ExternalReference, RequestedProvision


def normalize_label(kind: str, label: str) -> str:
    lab = label.strip()
    # remove surrounding parens
    lab = re.sub(r"^\(+|\)+$", "", lab).strip()
    if kind == "article":
        # match number and optional bis/ter/quater or trailing letter
        m = re.match(r"^(\d+)\s*(bis|ter|quater|[a-c])?$", lab, flags=re.IGNORECASE)
        if not m:
            # fallback: remove spaces
            lab = lab.replace(" ", "")
            return f"art_{lab}"
        num = m.group(1)
        suf = m.group(2) or ""
        suf = suf.lower()
        suf_map = {"bis": "a", "ter": "b", "quater": "c"}
        letter = suf_map.get(suf, suf)
        return f"art_{num}{letter}"
    elif kind == "annex":
        # roman numerals -> uppercase
        r = lab.upper()
        r = re.sub(r"[^IVXLCDM]", "", r)
        return f"anx_{r}"
    elif kind == "recital":
        num = re.sub(r"[^\d]", "", lab)
        return f"rct_{num}"
    else:
        return label


@dataclass
class UnavailableReference:
    citation: str
    reason: str  # 'not_indexed' | 'external' | 'over_cap'
    detail: str | None = None


@dataclass
class ResolveResult:
    added: list[Provision]
    unavailable: list[UnavailableReference]


class LookupProtocol(Protocol):
    async def get_by_parent_ref(self, parent_ref: str) -> list[Provision]: ...

    async def get_by_refs(self, refs: Iterable[str]) -> list[Provision]: ...


async def resolve(
    requests: Iterable[RequestedProvision],
    external_references: Iterable[ExternalReference],
    *,
    kept: Iterable[str],
    document_keys: Iterable[str],
    lookup: LookupProtocol,
    max_added: int | None,
) -> ResolveResult:
    kept_set = set(kept)
    added: list[Provision] = []
    unavailable: list[UnavailableReference] = []
    seen_parents: set[str] = set()
    added_count = 0

    # external references become unavailable external
    for ext in external_references:
        unavailable.append(
            UnavailableReference(
                citation=ext.citation, reason="external", detail=ext.reason
            )
        )

    for req in requests:
        parent_anchor = normalize_label(req.kind, req.label)
        parent_ref = f"{req.document}:{parent_anchor}"
        if req.document not in set(document_keys):
            unavailable.append(
                UnavailableReference(
                    citation=f"{req.document}:{req.kind}:{req.label}",
                    reason="external",
                    detail="unknown document",
                )
            )
            continue
            continue
        if parent_ref in seen_parents:
            # repeated request -> skip
            continue
        seen_parents.add(parent_ref)
        # drop requests already kept by parent (skip parts already kept)
        if any(
            k.startswith(f"{req.document}:")
            and k.split(":", 1)[1].startswith(parent_anchor)
            for k in kept_set
        ):
            # already kept, skip
            continue
        rows = await lookup.get_by_parent_ref(parent_ref)
        if not rows:
            # not indexed
            unavailable.append(
                UnavailableReference(
                    citation=parent_ref, reason="not_indexed", detail="no row in index"
                )
            )
            continue
        # apply cap
        if max_added is not None and added_count >= max_added:
            unavailable.append(
                UnavailableReference(
                    citation=parent_ref,
                    reason="over_cap",
                    detail=f"max_added={max_added}",
                )
            )
            continue
        # add all parts
        for p in rows:
            added.append(p)
        added_count += 1

    return ResolveResult(added=added, unavailable=unavailable)
