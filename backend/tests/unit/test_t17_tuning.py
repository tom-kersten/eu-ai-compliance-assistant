from __future__ import annotations

import pytest

from eval import tuning


def test_compute_hit_rates_simple():
    # two provisions with orthogonal vectors
    provision_vectors = {"p1": [1.0, 0.0], "p2": [0.0, 1.0]}
    # query matching p1
    query_vectors = {"q1": [1.0, 0.0], "qbad": [0.1, 0.1]}
    questions = [{"id": "q1", "must": ["p1"]}, {"id": "qbad", "must": []}]
    res = tuning.compute_hit_rates(
        query_vectors, provision_vectors, questions, top_k=1, threshold=0.5
    )
    assert res["q1"]["vector_hit"] is True
    assert res["q1"]["top1"] == "p1"


def test_suggest_threshold_positive_margin():
    provision_vectors = {"p1": [1.0, 0.0], "p2": [0.0, 1.0]}
    query_vectors = {
        "g1": [0.9, 0.1],
        "g2": [0.8, 0.2],
        "bad": [0.0, 1.0],
    }
    thr = tuning.suggest_threshold(
        query_vectors, provision_vectors, ["g1", "g2"], "bad", top_k=1
    )
    assert 0.0 <= thr <= 1.0


def test_suggest_threshold_negative_margin_raises():
    provision_vectors = {"p1": [1.0, 0.0]}
    query_vectors = {"g1": [0.0, 1.0], "bad": [0.9, 0.1]}
    with pytest.raises(ValueError):
        tuning.suggest_threshold(
            query_vectors, provision_vectors, ["g1"], "bad", top_k=1
        )


def test_ab_status_line_in_memory_removes_status():
    chunks = [{"header": "Status: amended\nHeader line 2", "body": "body"}]
    with_texts, without_texts = tuning.ab_status_line_in_memory(chunks)
    assert "Status:" in with_texts[0]
    assert "Status:" not in without_texts[0]
