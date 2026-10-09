"""Pure decision rules for retrieval calibration.

Live measurements feed these functions. They do not call providers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

STATUS_LINE_PREFIX = "Gewijzigd bij:"


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vector lengths differ")
    numerator = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for x_value, y_value in zip(left, right, strict=True):
        numerator += x_value * y_value
        left_norm += x_value * x_value
        right_norm += y_value * y_value
    denominator = math.sqrt(left_norm) * math.sqrt(right_norm)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def rank_similarities(
    query: Sequence[float],
    provisions: Mapping[str, Sequence[float]],
) -> list[tuple[str, float]]:
    """Rank provision refs by cosine similarity, highest first."""
    ranked = [(ref, _cosine(query, vector)) for ref, vector in provisions.items()]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def retrieved_refs(
    ranked: Sequence[tuple[str, float]],
    *,
    top_k: int,
    threshold: float,
) -> list[str]:
    """Refs inside top-k whose similarity is at least the threshold."""
    return [ref for ref, score in ranked[:top_k] if score >= threshold]


def is_admitted(
    ranked: Sequence[tuple[str, float]],
    *,
    top_k: int,
    threshold: float,
) -> bool:
    """A question is admitted when retrieval returns at least one provision."""
    return bool(retrieved_refs(ranked, top_k=top_k, threshold=threshold))


def vector_hit(
    ranked: Sequence[tuple[str, float]],
    must: Sequence[str],
    *,
    top_k: int,
    threshold: float,
) -> bool:
    """Every expected ref is inside the retrieved set."""
    found = set(retrieved_refs(ranked, top_k=top_k, threshold=threshold))
    return set(must).issubset(found)


def _question_by_id(questions: Sequence[Mapping], question_id: str) -> Mapping:
    for question in questions:
        if question["id"] == question_id:
            return question
    raise KeyError(question_id)


def _ceiling(
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    top_k: int,
) -> tuple[float, float | None]:
    """Return (lowest good top-1, lowest in-top-k must score).

    The second value is None when a must ref is missing or outside top-k.
    """
    top1_scores: list[float] = []
    must_scores: list[float] = []
    must_complete = True
    for question_id in good_ids:
        ranked = list(ranked_by_question[question_id])
        if not ranked:
            raise ValueError(f"{question_id} has no scores")
        top1_scores.append(ranked[0][1])
        question = _question_by_id(questions, question_id)
        positions = {ref: index for index, (ref, _) in enumerate(ranked)}
        scores = {ref: score for ref, score in ranked}
        for ref in question.get("must") or []:
            if ref not in scores or positions[ref] >= top_k:
                must_complete = False
                continue
            must_scores.append(scores[ref])
    if not top1_scores:
        raise ValueError("no good questions")
    if must_complete and must_scores:
        return min(top1_scores), min(must_scores)
    return min(top1_scores), None


def suggest_threshold(
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    bad_id: str,
    top_k: int,
) -> float:
    """Midpoint that rejects the bad question and admits every good one.

    When every expected provision of the good questions sits inside top-k and
    still scores above the bad question, the midpoint also keeps those
    provisions above the cut. Otherwise the midpoint only guarantees admission
    (a non-empty retrieval).
    """
    bad_ranked = list(ranked_by_question[bad_id])
    if not bad_ranked:
        raise ValueError("bad question has no scores")
    bad_max = bad_ranked[0][1]
    min_top1, must_floor = _ceiling(
        ranked_by_question,
        questions,
        good_ids=good_ids,
        top_k=top_k,
    )
    if min_top1 <= bad_max:
        raise ValueError("positive margin required to suggest a threshold")
    ceiling = min_top1
    if must_floor is not None and must_floor > bad_max:
        ceiling = must_floor
    threshold = (bad_max + ceiling) / 2
    if not (bad_max < threshold <= ceiling):
        threshold = math.nextafter(bad_max, math.inf)
        if threshold > ceiling:
            raise ValueError("positive margin required to suggest a threshold")
    return threshold


def quantize_threshold(
    threshold: float,
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    bad_id: str,
    top_k: int,
) -> float:
    """Round the threshold without letting Q09 through or dropping a good question."""
    for places in (4, 6, 8):
        candidate = round(threshold, places)
        if _threshold_holds(
            candidate,
            ranked_by_question,
            questions,
            good_ids=good_ids,
            bad_id=bad_id,
            top_k=top_k,
        ):
            return candidate
    return threshold


def _threshold_holds(
    threshold: float,
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    bad_id: str,
    top_k: int,
) -> bool:
    if is_admitted(ranked_by_question[bad_id], top_k=top_k, threshold=threshold):
        return False
    for question_id in good_ids:
        if not is_admitted(
            ranked_by_question[question_id],
            top_k=top_k,
            threshold=threshold,
        ):
            return False
    return True


def can_separate(
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    bad_id: str,
    top_k: int,
) -> bool:
    try:
        suggest_threshold(
            ranked_by_question,
            questions,
            good_ids=good_ids,
            bad_id=bad_id,
            top_k=top_k,
        )
    except ValueError:
        return False
    return True


def count_vector_hits(
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    top_k: int,
    threshold: float,
) -> int:
    hits = 0
    for question_id in good_ids:
        question = _question_by_id(questions, question_id)
        if vector_hit(
            ranked_by_question[question_id],
            list(question.get("must") or []),
            top_k=top_k,
            threshold=threshold,
        ):
            hits += 1
    return hits


def review_top_k(
    ranked_by_question: Mapping[str, Sequence[tuple[str, float]]],
    questions: Sequence[Mapping],
    *,
    good_ids: Sequence[str],
    current: int,
) -> int:
    """Keep the configured ceiling.

    Admission only needs each good question's top hit, which is inside any
    ceiling of 1 or more. Raising the ceiling to the worst must-ref rank
    would pass a large irrelevant set into selection on every question.
    Missing must refs are an error so a bad corpus fails loudly.
    """
    for question_id in good_ids:
        ranked = list(ranked_by_question[question_id])
        positions = {ref: index for index, (ref, _) in enumerate(ranked)}
        question = _question_by_id(questions, question_id)
        for ref in question.get("must") or []:
            if ref not in positions:
                raise ValueError(f"{ref} missing from ranking for {question_id}")
    return current


def required_added_cap(questions: Sequence[Mapping]) -> int:
    """Smallest cap that can hold every via_reference list in the eval set."""
    if not questions:
        return 0
    return max(len(question.get("via_reference") or []) for question in questions)


def strip_status_lines(header: str) -> str:
    """Remove Omnibus status lines. Other header lines stay."""
    kept = [
        line for line in header.splitlines() if not line.startswith(STATUS_LINE_PREFIX)
    ]
    return "\n".join(kept)


def embedding_text(header: str, body: str, *, include_status: bool) -> str:
    """Text sent to the embedding model, with or without the status line."""
    used = header if include_status else strip_status_lines(header)
    if not used:
        return body
    return f"{used}\n\n{body}"


def decide_status_line(
    *,
    vector_hits_with: int,
    vector_hits_without: int,
    separable_with: bool,
    separable_without: bool,
) -> str:
    """Keep the status line only when it is what makes retrieval separable,
    or when it strictly raises the vector-hit count. Otherwise drop it.
    """
    if separable_with and not separable_without:
        return "keep"
    if vector_hits_with > vector_hits_without and separable_with:
        return "keep"
    if vector_hits_with > vector_hits_without and not separable_without:
        return "keep"
    return "drop"


def decide_reasoning(trials: Sequence[Mapping]) -> str:
    """Lowest token cost among the efforts with the best selection-hit count.

    Latency breaks remaining ties. Effort name is the last tie-break so the
    choice is stable.
    """
    if not trials:
        raise ValueError("no reasoning trials")
    best_hits = max(int(trial["selection_hits"]) for trial in trials)
    candidates = [
        trial for trial in trials if int(trial["selection_hits"]) == best_hits
    ]
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}

    def sort_key(trial: Mapping) -> tuple[float, float, int]:
        return (
            float(trial["mean_completion_tokens"]),
            float(trial["mean_latency_seconds"]),
            order.get(str(trial["effort"]), 9),
        )

    candidates.sort(key=sort_key)
    return str(candidates[0]["effort"])
