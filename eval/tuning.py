from __future__ import annotations

import math

from collections.abc import Iterable, Sequence


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vector lengths differ")
    num = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        num += x * y
        na += x * x
        nb += y * y
    den = math.sqrt(na) * math.sqrt(nb)
    if den == 0:
        return 0.0
    return num / den


def compute_hit_rates(
    query_vectors: dict[str, Sequence[float]],
    provision_vectors: dict[str, Sequence[float]],
    questions: Iterable[dict],
    top_k: int,
    threshold: float,
) -> dict:
    """Compute vector and top-1 statistics for the provided eval questions.

    query_vectors: mapping question id -> vector
    provision_vectors: mapping provision ref -> vector
    questions: iterable of question dicts (must list)
    """
    results = {}
    for q in questions:
        qid = q["id"]
        must = set(q.get("must", []))
        qv = query_vectors[qid]
        # compute similarities
        sims = []
        for ref, pv in provision_vectors.items():
            sims.append((ref, _cosine(qv, pv)))
        sims.sort(key=lambda t: t[1], reverse=True)
        topk = [r for r, s in sims[:top_k]]
        top1 = sims[0][0] if sims else None
        # vector_hit if all must in top_k and above threshold somewhere
        above = {r for r, s in sims if s >= threshold}
        vector_hit = must.issubset(above)
        results[qid] = {"vector_hit": vector_hit, "top1": top1, "topk": topk}
    return results


def suggest_threshold(
    query_vectors: dict[str, Sequence[float]],
    provision_vectors: dict[str, Sequence[float]],
    good_qids: Iterable[str],
    bad_qid: str,
    top_k: int,
) -> float:
    """Suggest a threshold midpoint between the worst-good and best-bad similarities.

    Raises ValueError when margin is not positive.
    """
    # for good questions, compute minimum similarity over expected provisions (top match)
    good_mins = []
    for qid in good_qids:
        qv = query_vectors[qid]
        # similarity to each required provision (provision_vectors keyed by ref)
        sims = [_cosine(qv, pv) for pv in provision_vectors.values()]
        if not sims:
            raise ValueError("no provision vectors available")
        good_mins.append(min(sims))
    min_good = min(good_mins)
    # for bad question, take maximum top-1 similarity
    bv = query_vectors[bad_qid]
    bad_sims = [_cosine(bv, pv) for pv in provision_vectors.values()]
    max_bad = max(bad_sims) if bad_sims else 0.0
    margin = min_good - max_bad
    if margin <= 0:
        raise ValueError("positive margin required to suggest a threshold")
    return (min_good + max_bad) / 2.0


def ab_status_line_in_memory(chunks: Iterable[dict]) -> tuple[list[str], list[str]]:
    """Return two lists of embedded texts: with and without the status line.

    Each chunk is expected to be a dict with 'header' and 'body' keys. The
    'status line' is assumed to be the first line of the header that starts
    with 'Status:' (a conservative heuristic used in tests).
    """
    with_texts = []
    without_texts = []
    for c in chunks:
        header = c.get("header", "")
        body = c.get("body", "")
        with_text = header + "\n\n" + body if header else body
        # remove only a 'Status:' line if present as the first header line
        lines = header.splitlines()
        if lines and lines[0].startswith("Status:"):
            no_status_header = "\n".join(lines[1:])
        else:
            no_status_header = header
        without_text = no_status_header + "\n\n" + body if no_status_header else body
        with_texts.append(with_text)
        without_texts.append(without_text)
    return with_texts, without_texts

