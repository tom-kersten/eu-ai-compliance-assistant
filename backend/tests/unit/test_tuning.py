"""Decision rules for retrieval calibration. Measurements are applied separately."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from eval.reliability import (
    chat_request,
    message_content,
    parse_valid,
    suggest_max_retries,
)
from eval.tuning import (
    can_separate,
    count_vector_hits,
    decide_reasoning,
    decide_status_line,
    embedding_text,
    is_admitted,
    quantize_threshold,
    rank_similarities,
    required_added_cap,
    review_top_k,
    strip_status_lines,
    suggest_threshold,
    vector_hit,
)


def _questions() -> list[dict]:
    return [
        {
            "id": "Q01",
            "must": ["AI-verordening:art_3"],
            "via_reference": [],
        },
        {
            "id": "Q02",
            "must": ["AI-verordening:art_50"],
            "via_reference": ["AVG:art_35"],
        },
        {"id": "Q09", "must": [], "via_reference": []},
    ]


def _ranked() -> dict[str, list[tuple[str, float]]]:
    return {
        "Q01": [("AI-verordening:art_3", 0.80), ("other", 0.40)],
        "Q02": [("AI-verordening:art_50", 0.70), ("AVG:art_35", 0.55)],
        "Q09": [("unrelated", 0.45), ("other", 0.20)],
    }


@pytest.mark.unit
def test_rank_similarities_orders_by_cosine() -> None:
    provisions = {"p1": [1.0, 0.0], "p2": [0.0, 1.0]}
    ranked = rank_similarities([1.0, 0.0], provisions)
    assert ranked[0][0] == "p1"
    assert ranked[0][1] == pytest.approx(1.0)
    assert ranked[1][0] == "p2"


@pytest.mark.unit
def test_suggest_threshold_admits_good_questions_and_rejects_bad() -> None:
    ranked = _ranked()
    questions = _questions()
    threshold = suggest_threshold(
        ranked,
        questions,
        good_ids=["Q01", "Q02"],
        bad_id="Q09",
        top_k=10,
    )
    # Lowest must-ref still above Q09's best score is 0.70; midpoint with 0.45.
    assert threshold == pytest.approx((0.70 + 0.45) / 2)
    assert is_admitted(ranked["Q01"], top_k=10, threshold=threshold)
    assert is_admitted(ranked["Q02"], top_k=10, threshold=threshold)
    assert not is_admitted(ranked["Q09"], top_k=10, threshold=threshold)
    assert vector_hit(
        ranked["Q01"],
        ["AI-verordening:art_3"],
        top_k=10,
        threshold=threshold,
    )
    assert vector_hit(
        ranked["Q02"],
        ["AI-verordening:art_50"],
        top_k=10,
        threshold=threshold,
    )


@pytest.mark.unit
def test_suggest_threshold_uses_top1_when_must_refs_fall_outside_top_k() -> None:
    ranked = {
        "Q01": [("noise", 0.90), ("AI-verordening:art_3", 0.40)],
        "Q09": [("unrelated", 0.50)],
    }
    questions = [{"id": "Q01", "must": ["AI-verordening:art_3"]}]
    threshold = suggest_threshold(
        ranked,
        questions,
        good_ids=["Q01"],
        bad_id="Q09",
        top_k=1,
    )
    assert threshold == pytest.approx((0.90 + 0.50) / 2)
    assert is_admitted(ranked["Q01"], top_k=1, threshold=threshold)
    assert not is_admitted(ranked["Q09"], top_k=1, threshold=threshold)
    assert not vector_hit(
        ranked["Q01"],
        ["AI-verordening:art_3"],
        top_k=1,
        threshold=threshold,
    )


@pytest.mark.unit
def test_quantize_threshold_keeps_admission_and_rejection() -> None:
    ranked = _ranked()
    questions = _questions()
    raw = suggest_threshold(
        ranked,
        questions,
        good_ids=["Q01", "Q02"],
        bad_id="Q09",
        top_k=10,
    )
    quantized = quantize_threshold(
        raw,
        ranked,
        questions,
        good_ids=["Q01", "Q02"],
        bad_id="Q09",
        top_k=10,
    )
    assert quantized == pytest.approx(round(raw, 4))
    assert is_admitted(ranked["Q01"], top_k=10, threshold=quantized)
    assert not is_admitted(ranked["Q09"], top_k=10, threshold=quantized)


@pytest.mark.unit
def test_suggest_threshold_raises_when_bad_question_outranks_good() -> None:
    ranked = {
        "Q01": [("AI-verordening:art_3", 0.40)],
        "Q09": [("unrelated", 0.55)],
    }
    questions = [{"id": "Q01", "must": ["AI-verordening:art_3"]}]
    with pytest.raises(ValueError):
        suggest_threshold(
            ranked,
            questions,
            good_ids=["Q01"],
            bad_id="Q09",
            top_k=10,
        )
    assert not can_separate(
        ranked,
        questions,
        good_ids=["Q01"],
        bad_id="Q09",
        top_k=10,
    )


@pytest.mark.unit
def test_vector_hit_requires_every_must_ref_inside_top_k_and_threshold() -> None:
    ranked = [("must-a", 0.9), ("must-b", 0.6), ("other", 0.2)]
    assert vector_hit(ranked, ["must-a", "must-b"], top_k=2, threshold=0.5)
    assert not vector_hit(ranked, ["must-a", "must-b"], top_k=1, threshold=0.5)
    assert not vector_hit(ranked, ["must-a", "must-b"], top_k=2, threshold=0.7)


@pytest.mark.unit
def test_review_top_k_keeps_current_when_must_refs_already_fit() -> None:
    questions = _questions()
    assert (
        review_top_k(
            _ranked(),
            questions,
            good_ids=["Q01", "Q02"],
            current=10,
        )
        == 10
    )


@pytest.mark.unit
def test_review_top_k_keeps_ceiling_when_a_must_ref_ranks_lower() -> None:
    ranked = {
        "Q01": [("noise", 0.9)]
        + [(f"n{i}", 0.5) for i in range(10)]
        + [("AI-verordening:art_3", 0.4)],
    }
    questions = [{"id": "Q01", "must": ["AI-verordening:art_3"]}]
    assert review_top_k(ranked, questions, good_ids=["Q01"], current=10) == 10


@pytest.mark.unit
def test_required_added_cap_is_the_longest_via_reference_list() -> None:
    assert required_added_cap(_questions()) == 1


@pytest.mark.unit
def test_eval_file_added_cap_covers_every_via_reference_list() -> None:
    path = Path("/app/eval/eval_questions.json")
    questions = json.loads(path.read_text(encoding="utf-8"))
    cap = required_added_cap(questions)
    lengths = [len(question["via_reference"]) for question in questions]
    assert cap == max(lengths)
    assert all(length <= cap for length in lengths)


@pytest.mark.unit
def test_strip_status_lines_removes_gewijzigd_bij_only() -> None:
    header = (
        "AI-verordening (verordening artificiële intelligentie), "
        "Verordening (EU) 2024/1689\n"
        "Artikel 6: Classificatieregels\n"
        "Gewijzigd bij: Digitale omnibus inzake AI (Verordening (EU) 2026/1744)"
    )
    stripped = strip_status_lines(header)
    assert "Gewijzigd bij:" not in stripped
    assert "Artikel 6:" in stripped
    untouched = strip_status_lines("Status: amended\nArtikel 1")
    assert untouched == "Status: amended\nArtikel 1"


@pytest.mark.unit
def test_embedding_text_omits_status_line_when_disabled() -> None:
    header = "Doc\nGewijzigd bij: Omnibus (id)"
    with_status = embedding_text(header, "body", include_status=True)
    without_status = embedding_text(header, "body", include_status=False)
    assert "Gewijzigd bij:" in with_status
    assert "Gewijzigd bij:" not in without_status
    assert without_status == "Doc\n\nbody"


@pytest.mark.unit
def test_decide_status_line_drops_unless_there_is_a_clear_benefit() -> None:
    assert (
        decide_status_line(
            vector_hits_with=6,
            vector_hits_without=6,
            separable_with=True,
            separable_without=True,
        )
        == "drop"
    )
    assert (
        decide_status_line(
            vector_hits_with=7,
            vector_hits_without=6,
            separable_with=True,
            separable_without=True,
        )
        == "keep"
    )
    assert (
        decide_status_line(
            vector_hits_with=6,
            vector_hits_without=6,
            separable_with=False,
            separable_without=True,
        )
        == "drop"
    )
    assert (
        decide_status_line(
            vector_hits_with=5,
            vector_hits_without=6,
            separable_with=True,
            separable_without=False,
        )
        == "keep"
    )


@pytest.mark.unit
def test_count_vector_hits_counts_only_good_questions() -> None:
    hits = count_vector_hits(
        _ranked(),
        _questions(),
        good_ids=["Q01", "Q02"],
        top_k=10,
        threshold=0.6,
    )
    assert hits == 2


@pytest.mark.unit
def test_decide_reasoning_prefers_lower_cost_when_hit_counts_tie() -> None:
    chosen = decide_reasoning(
        [
            {
                "effort": "medium",
                "selection_hits": 6,
                "mean_latency_seconds": 4.0,
                "mean_completion_tokens": 800,
            },
            {
                "effort": "none",
                "selection_hits": 6,
                "mean_latency_seconds": 1.0,
                "mean_completion_tokens": 200,
            },
            {
                "effort": "low",
                "selection_hits": 6,
                "mean_latency_seconds": 2.0,
                "mean_completion_tokens": 400,
            },
        ]
    )
    assert chosen == "none"


@pytest.mark.unit
def test_decide_reasoning_keeps_higher_effort_when_it_hits_more() -> None:
    chosen = decide_reasoning(
        [
            {
                "effort": "none",
                "selection_hits": 4,
                "mean_latency_seconds": 1.0,
                "mean_completion_tokens": 100,
            },
            {
                "effort": "medium",
                "selection_hits": 7,
                "mean_latency_seconds": 5.0,
                "mean_completion_tokens": 900,
            },
        ]
    )
    assert chosen == "medium"


@pytest.mark.unit
def test_parse_valid_accepts_schema_and_rejects_malformed_content() -> None:
    class Sample(BaseModel):
        model_config = ConfigDict(extra="forbid")
        keep: list[str]

    assert parse_valid('{"keep": ["a"]}', Sample)
    assert not parse_valid("not-json", Sample)
    assert not parse_valid('{"keep": "a"}', Sample)
    assert not parse_valid(None, Sample)


@pytest.mark.unit
def test_message_content_reads_only_the_final_content_field() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "content": '{"keep": []}',
                    "reasoning": "hidden",
                }
            }
        ]
    }
    assert message_content(body) == '{"keep": []}'
    assert message_content({"choices": []}) is None


@pytest.mark.unit
def test_chat_request_omits_reasoning_when_effort_is_off() -> None:
    schema = {"type": "object", "additionalProperties": False}
    off = chat_request(
        model="m",
        schema_name="selection_result",
        schema=schema,
        prompt="p",
        reasoning_effort=None,
    )
    assert "reasoning" not in off
    assert off["response_format"]["type"] == "json_schema"
    assert off["response_format"]["json_schema"]["strict"] is True
    on = chat_request(
        model="m",
        schema_name="selection_result",
        schema=schema,
        prompt="p",
        reasoning_effort="low",
    )
    assert on["reasoning"] == {"effort": "low", "exclude": False}


@pytest.mark.unit
def test_suggest_max_retries_stays_at_one_when_output_always_validates() -> None:
    assert suggest_max_retries(valid=10, attempts=10) == 1
    assert suggest_max_retries(valid=9, attempts=10) == 2
    assert suggest_max_retries(valid=8, attempts=10) == 3
